"""异步 job 注册表（审查修复 C3）—— job_id ↔ 后台任务 ↔ 真实 run_id 的关联。

审查发现的原始问题：run_once_async 返回的 job_id 与 run_once 内部生成的
run_id 毫无关联，poll_job 永远查不到；后台结果写入 result_holder 后无人读取。

本模块提供进程内、线程安全的注册表：
- create() 发放 job_id（job_ 前缀，与 yyyymmdd_* 格式的 run_id 可区分）
- 后台线程通过 finish()/fail() 回填真实 run_id 与结果
- poll 侧先查注册表（内存），未命中再回落到 runs/<id>/meta.json（磁盘）

进程内语义：MCP/CLI 与后台线程同进程时有效；跨进程重启后注册表丢失，
此时用 run_id 走磁盘路径仍可查询（meta.json 是持久层）。
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

#: 开启 job 持久化的环境开关：
#: ``RFAUTO_JOB_REGISTRY_DB=1``（默认路径 runs/registry.sqlite）、
#: ``=true``/``=on`` 同义，或直接给数据库文件路径；未设/``0``/``false``/``off``
#: 时回落 settings ``db.job_registry_persist``（默认 False，行为不变）。
ENV_JOB_REGISTRY_DB = "RFAUTO_JOB_REGISTRY_DB"

_FALSY_SWITCH = ("0", "false", "off")
_TRUTHY_SWITCH = ("1", "true", "on")


def _open_default_registry() -> Any:
    """按缺省路径（infra.db.default_registry_db_path）构造 RegistryDB。

    best-effort：构造/迁移失败返回 None（回落纯内存，#105）。
    """
    try:
        from rfauto.infra.db import RegistryDB  # 惰性导入：默认路径零依赖开销

        db = RegistryDB()
        db.migrate()
        return db
    except Exception:
        return None


def _env_persist_backend(enabled: bool | None = None) -> Any:
    """构造 RegistryDB 持久化后端；关闭或不可用返回 None。

    解析链（R2-D-03 ③半）：显式参数 ``enabled`` > 环境变量
    ``RFAUTO_JOB_REGISTRY_DB``（现行为不变：truthy/falsy/路径值三态，
    路径值直接作库文件）> settings ``db.job_registry_persist`` > 默认关。
    默认（不设 env、YAML false）与纯内存旧行为逐字节一致。

    best-effort（#105）：持久化后端不可用绝不阻塞 job 主路径——回落纯内存。
    """
    if enabled is not None:
        return _open_default_registry() if enabled else None
    raw = os.environ.get(ENV_JOB_REGISTRY_DB, "").strip()
    if not raw:
        # env 未设：回落 settings 键（YAML 显式 true 可开启；默认 False 不变）
        try:
            from rfauto.infra.config import load_settings

            if not load_settings().db.job_registry_persist:
                return None
        except Exception:
            return None
        return _open_default_registry()
    if raw.lower() in _FALSY_SWITCH:
        return None
    try:
        from rfauto.infra.db import RegistryDB  # 惰性导入：默认路径零依赖开销

        path = None if raw.lower() in _TRUTHY_SWITCH else raw
        db = RegistryDB(path=path)
        db.migrate()
        return db
    except Exception:
        return None


@dataclass
class _JobEntry:
    job_id: str
    state: str = "running"  # running | cancel_requested | cancelled | done | failed
    run_id: str = ""
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    thread: threading.Thread | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    started: bool = False
    #: 编排席位记账：本作业当前占用的资源席位（resource_scheduler 资源键）
    seats: tuple[str, ...] = ()


class JobRegistry:
    """线程安全的进程内 job 注册表（带容量上限防内存无限增长）。

    增加可选持久化后端 ``persist``（RegistryDB）：开启后 create/finish/
    fail/cancel/mark_cancelled 同步写 jobs 表；``get`` 未命中内存时先查表
    再返回 None（poll 调用方的磁盘 meta.json 回落链保持不变）。持久化
    全程 best-effort（#105）：写失败静默，绝不影响内存主路径。
    """

    def __init__(self, max_entries: int = 256, *,
                 persist: Any = None) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, _JobEntry] = {}
        self._max_entries = max_entries
        self._persist = persist

    # -- 持久化（best-effort） ----------------------------------------------

    def _persist_upsert(self, entry: _JobEntry) -> None:
        if self._persist is None:
            return
        # 观测性/持久化故障不得成为业务主路径故障点（#105）
        with contextlib.suppress(Exception):
            self._persist.upsert_job(
                job_id=entry.job_id, run_id=entry.run_id, state=entry.state,
                result=entry.result, error=entry.error,
                created_at=entry.created_at, finished_at=entry.finished_at,
                metadata={"seats": list(entry.seats)},
            )

    def _persist_get(self, job_id: str) -> dict[str, Any] | None:
        if self._persist is None:
            return None
        try:
            return self._persist.get_job(job_id)
        except Exception:
            return None

    def create(self, job_id: str, thread: threading.Thread | None = None) -> None:
        with self._lock:
            self._jobs[job_id] = _JobEntry(job_id=job_id, thread=thread)
            self._prune_locked()
            self._persist_upsert(self._jobs[job_id])

    def finish(self, job_id: str, *, run_id: str = "", result: dict[str, Any] | None = None) -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                return
            entry.state = "done"
            entry.run_id = run_id
            entry.result = result
            entry.finished_at = time.time()
            self._persist_upsert(entry)

    def fail(self, job_id: str, *, run_id: str = "", result: dict[str, Any] | None = None,
             error: str = "") -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                return
            entry.state = "failed"
            entry.run_id = run_id
            entry.result = result
            entry.error = error or (
                "; ".join(result.get("errors", [])) if result else ""
            )
            entry.finished_at = time.time()
            self._persist_upsert(entry)

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        """请求取消 job（jobs cancel 的落点）。

        语义（诚实边界）：
        - job 还在排队（未获单写锁 / 线程未开始执行）：置 cancel_event，
          后台线程在执行前检查并直接跳过 → cancelled
        - job 已在执行：置 cancel_requested 快照返回；AEDT 求解无法安全
          中断（强杀会泄漏 license），后台线程跑完后按 cancel_event 丢弃
          结果 → cancelled
        - 已结束的 job：快照原样返回，cancel 为空操作
        """
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                return None
            if entry.state in ("done", "failed", "cancelled"):
                return self._snapshot(entry)
            entry.cancel_event.set()
            if not entry.started:
                entry.state = "cancelled"
                entry.finished_at = time.time()
            else:
                entry.state = "cancel_requested"
            self._persist_upsert(entry)
            return self._snapshot(entry)

    def is_cancelled(self, job_id: str) -> bool:
        """后台线程/执行器侧查询取消标志。"""
        with self._lock:
            entry = self._jobs.get(job_id)
            return entry.cancel_event.is_set() if entry is not None else False

    def mark_cancelled(self, job_id: str, run_id: str = "") -> None:
        """执行器侧确认取消终态（cancel_requested → cancelled）。

        用于"执行中收到取消、跑完后丢弃结果"的场景（AEDT 求解不可安全中断）。
        非 cancel_requested 状态时为空操作。
        """
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None or entry.state != "cancel_requested":
                return
            entry.state = "cancelled"
            entry.run_id = run_id
            entry.finished_at = time.time()
            self._persist_upsert(entry)

    def mark_started(self, job_id: str) -> bool:
        """后台线程在真正开始执行（获得单写锁）后调用。

        Returns:
            False 表示已被取消（调用方应跳过执行直接返回）。
        """
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                return True  # 注册表被清空（测试隔离），不阻塞执行
            entry.started = True
            return not entry.cancel_event.is_set()

    # ── 编排接线：席位记账（哪类资源被哪个作业占用，可查询） ──────
    def assign_seats(self, job_id: str, seats: Sequence[str]) -> bool:
        """登记作业占用的资源席位（加性字段；未知作业返回 False）。"""
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                return False
            entry.seats = tuple(str(s) for s in seats)
            return True

    def release_seats(self, job_id: str) -> tuple[str, ...]:
        """清空并返回作业占用的席位（未知作业返回空元组）。"""
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                return ()
            released = entry.seats
            entry.seats = ()
            return released

    def seats_of(self, job_id: str) -> tuple[str, ...]:
        """作业当前占用的席位（未知作业返回空元组）。"""
        with self._lock:
            entry = self._jobs.get(job_id)
            return entry.seats if entry is not None else ()

    def seat_occupancy(self) -> dict[str, list[str]]:
        """席位 → 占用作业列表（按注册序，确定性）。

        只反映当前登记的占用：作业释放/淘汰后席位随之消失，因此该表
        永远是账本实时快照，可作并发编排的查询接口。
        """
        with self._lock:
            table: dict[str, list[str]] = {}
            for job_id, entry in self._jobs.items():
                for seat in entry.seats:
                    table.setdefault(seat, []).append(job_id)
            return table

    def get(self, job_id: str) -> dict[str, Any] | None:
        """返回 job 快照 dict；未知 job_id 返回 None。

        开启持久化后端时，内存未命中先查 jobs 表（跨进程重启后
        仍可查到终态）；表也未命中才返回 None——调用方既有 meta.json
        磁盘回落链（poll 侧）不变。
        """
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is not None:
                return self._snapshot(entry)
        row = self._persist_get(job_id)
        if row is not None:
            return row
        return None

    @staticmethod
    def _snapshot(entry: _JobEntry) -> dict[str, Any]:
        return {
            "job_id": entry.job_id,
            "state": entry.state,
            "run_id": entry.run_id,
            "result": entry.result,
            "error": entry.error,
            "created_at": entry.created_at,
            "finished_at": entry.finished_at,
            "seats": list(entry.seats),
        }

    def wait(self, job_id: str, timeout_s: float = 300.0) -> dict[str, Any] | None:
        """阻塞等待 job 结束（join 后台线程），返回最终快照；超时返回当前快照。

        主要供测试与 CLI 前台等待使用；MCP 轮询场景不调用。
        """
        thread: threading.Thread | None = None
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                return None
            thread = entry.thread
        if thread is not None:
            thread.join(timeout=timeout_s)
        return self.get(job_id)

    def _prune_locked(self) -> None:
        """超容量时按完成时间淘汰最旧的已结束条目（运行中的不淘汰）。"""
        if len(self._jobs) <= self._max_entries:
            return
        finished = [
            (e.finished_at if e.finished_at is not None else float("inf"), job_id)
            for job_id, e in self._jobs.items()
            if e.state != "running"
        ]
        finished.sort()
        overflow = len(self._jobs) - self._max_entries
        for _, job_id in finished[:overflow]:
            del self._jobs[job_id]


class SingleWriteLock:
    """单写锁（计划内缺口 1）—— 同一时间只允许一个占用者执行。

    背景：job_registry 只跟踪状态不互斥，并发提交多个 hfss job 会开多个
    AEDT 会话抢 license。本锁提供 FIFO 排队的互斥语义：先到先得，其余在
    条件变量上排队，占用者 release 后队首自动获得锁。

    进程内语义（与 JobRegistry 一致）；跨进程的 license 互斥由 AEDT
    license 服务器承担，不在本层。
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._owner: str | None = None
        self._queue: list[str] = []

    def acquire(self, job_id: str, timeout_s: float | None = None) -> bool:
        """获取锁；FIFO 排队等待。timeout_s=None 表示无限等待。"""
        with self._cond:
            self._queue.append(job_id)
            deadline = None if timeout_s is None else time.monotonic() + timeout_s
            while self._owner is not None or self._queue[0] != job_id:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    if job_id in self._queue:
                        self._queue.remove(job_id)
                    return False
                self._cond.wait(remaining)
            self._queue.pop(0)
            self._owner = job_id
            return True

    def release(self, job_id: str) -> None:
        """释放锁（仅持有者可释放），并唤醒队首。"""
        with self._cond:
            if self._owner != job_id:
                return
            self._owner = None
            self._cond.notify_all()

    @property
    def owner(self) -> str | None:
        """当前持有者 job_id（无持有者时为 None）。"""
        with self._cond:
            return self._owner

    @property
    def queue_length(self) -> int:
        """排队等待的 job 数。"""
        with self._cond:
            return len(self._queue)


_write_lock = SingleWriteLock()


def get_write_lock() -> SingleWriteLock:
    """进程内单写锁单例——并发 hfss job 的 license 互斥点。"""
    return _write_lock


_registry: JobRegistry | None = None
_registry_initialized = False


def get_job_registry() -> JobRegistry:
    """进程内单例（首次访问按环境开关决定是否挂持久化后端）。"""
    global _registry, _registry_initialized
    if not _registry_initialized:
        _registry = JobRegistry(persist=_env_persist_backend())
        _registry_initialized = True
    assert _registry is not None
    return _registry


def reset_job_registry() -> None:
    """清空注册表（测试隔离用）——重读环境开关，未开启时即纯内存注册表。"""
    global _registry, _registry_initialized
    _registry = JobRegistry(persist=_env_persist_backend())
    _registry_initialized = True
