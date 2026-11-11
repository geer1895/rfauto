"""request_receipt —— 不确定结局协议（请求回执状态机，VB-2 / aurora_r R-11）。

把 #145/#157/#225/#323 家族教训从 DAG 层下沉到通道层：远程同步通道断连后
此前无"对账"手段，盲目重试即可能二次求解。本模块提供**通道无关**的请求
回执状态机（纯 infra，零领域依赖、只 import 标准库）。

设计出处（思想级重写，MIT 源仅作机制对照、零代码复制、零署名义务）：
Q-X40 调研提案 VB-2（runs/aurora_q/qx40_vbridge/PROPOSALS.md），对照目标仓
``virtuoso/basic/resources/ramic_request_recovery.py`` 的
RecoverableRequestManager（submit/receipt/wait、_run_request 三分支、
resynchronize 探针；32 位 hex 请求号含毫秒时间戳、同号异载荷拒、TTL/容量
有界 3600s/4096 条/32MB）。

核心语义（结局四分 + 拒绝闸门）：

- ``not_started``：确定未发送——唯一允许（自动）重试的结局；
- ``completed`` / ``failed``：确定终态，随回执携带结果快照（同键同载荷
  重放快照，执行器不重复执行）；
- ``unknown``：归属不可证（发送后失联/回执缓存丢失）——**永不自动重放**，
  须凭回执对账（``reconcile``）或人工落定后才有后续；
- ``rejected``：闸门拒绝（同键异载荷 / 时间窗外 / 车道毒化），非请求结局。

车道毒化：任一请求 ``unknown`` 即毒化所在车道（lane）——归属不确定时
通道整体不可信，新提交一律拒绝；探针重同步成功（``resync_lane``）后解除。
请求自身仍保持 ``unknown``，对账前不因车道解除而放行。

回执缓存有界：TTL 3600s（过期转墓碑=同键再提交拒绝，防止旧回执漂白）、
容量 4096 条、快照总量 32MB（超限按 过期墓碑 → 终态 LRU 淘汰；在飞
pending/sent 条目尽量保留）。**进程重启后回执缓存即丢失**：对账查询
（``resume``）如实返回 ``unknown``，绝不返回 ``not_started``——缺乏证据
不得伪造成"确定未发送"。

请求预算（PROPOSALS §四 观察位 5 一并采用）：单调时钟 deadline 贯穿预检
与执行（``deadline_mono``），耗尽即 ``not_started``（确定未发送，可重试）。

并发面：全部可变状态在 ``threading.RLock`` 内迁移；执行器经
``execute_with_receipt`` 包裹，异常三分类（未发送/不确定/确定失败）决定
结局与车道处置。分层契约：本模块属 infra 层，禁止 import service 及以上。

挂账处方（无 CLI/MCP 叶）：本模块为 service 层内部件，暂无 CLI/MCP 直达
叶；如日后需要 CLI 观测叶（如 ``rfauto receipts stats``），由合流批按
"新 CLI 叶必带 --json + 信封构造器"家法接线，本 docstring 即挂账凭据。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DEFAULT_LANE",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_TTL_S",
    "OUTCOME_COMPLETED",
    "OUTCOME_FAILED",
    "OUTCOME_NOT_STARTED",
    "OUTCOME_REJECTED",
    "OUTCOME_UNKNOWN",
    "STATE_COMPLETED",
    "STATE_EXPIRED",
    "STATE_FAILED",
    "STATE_PENDING",
    "STATE_SENT",
    "NotSentError",
    "ReceiptDecision",
    "RequestReceiptLedger",
    "UncertainOutcomeError",
    "execute_with_receipt",
    "get_default_ledger",
    "new_receipt_id",
    "payload_fingerprint",
    "reset_default_ledger",
    "resolve_ledger",
]

# ── 结局四分 + 闸门拒绝 ────────────────────────────────────────────────────
OUTCOME_NOT_STARTED = "not_started"
OUTCOME_COMPLETED = "completed"
OUTCOME_FAILED = "failed"
OUTCOME_UNKNOWN = "unknown"
OUTCOME_REJECTED = "rejected"

# ── 回执条目状态机（entry.state）──────────────────────────────────────────
STATE_PENDING = "pending"      # 已登记，确定未发送（可重试窗口内）
STATE_SENT = "sent"            # 已交给执行器，归属不可证（unknown 域）
STATE_COMPLETED = "completed"  # 确定终态（有快照）
STATE_FAILED = "failed"        # 确定终态（有快照）
STATE_EXPIRED = "expired"      # TTL 过期墓碑（同键再提交=rejected，防漂白）

DEFAULT_LANE = "default"
DEFAULT_TTL_S = 3600.0
DEFAULT_MAX_ENTRIES = 4096
DEFAULT_MAX_BYTES = 32 * 1024 * 1024

_SNAPSHOT_OVERHEAD_BYTES = 256  # 条目自身（键/指纹/状态/时间戳）估算开销


class UncertainOutcomeError(Exception):
    """执行器抬出的"归属不可证"标记异常：发送动作可能已发生也可能没发生
    （如传输通道中途断连）。``execute_with_receipt`` 捕获后落 ``unknown``
    结局并毒化车道——同键永不自动重放。"""


class NotSentError(Exception):
    """执行器抬出的"确定未发送"标记异常：发送动作尚未发生（预检/装配段
    失败）。``execute_with_receipt`` 捕获后回收回执条目并返回
    ``not_started``——允许重试。"""


def new_receipt_id(now_fn: Callable[[], float] = time.time) -> str:
    """生成回执号：32 位 hex = 毫秒时间戳段(13) + 随机段(19)。

    时间戳段使回执号天然按提交时刻粗排序（诊断关联用）；随机段防撞。
    仅作关联与日志对账标识，非安全随机、不作鉴权凭据。形态对照目标仓
    32 位 hex 请求号含毫秒时间戳（机制对照，独立实现）。
    """
    ms = int(now_fn() * 1000.0) & ((1 << 53) - 1)
    return f"{ms:013x}{uuid.uuid4().hex[:19]}"


def payload_fingerprint(payload: Any) -> str:
    """载荷指纹：canonical JSON（键排序/紧凑分隔/ASCII 转义）的 SHA-256。

    载荷含不可 JSON 化对象时逐对象 ``repr`` 兜底（确定性优先于表达力——
    同一对象结构两次 repr 逐字节一致，跨进程不保证但回执缓存本就是
    进程内语义）。返回 64 位 hex，与回执号（32 hex）长度可辨。
    """
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, default=repr,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReceiptDecision:
    """回执判定（不可变值对象；service 层据此映射信封）。

    Attributes:
        outcome: 四分结局之一或 ``rejected``（闸门拒绝）。
        proceed: 调用方是否允许把请求交给执行器（仅 not_started 为 True）。
        retry_allowed: 是否允许重试。仅 not_started 为 True；unknown 恒
            False（永不自动重放）；终态无需重试；rejected 须先解闸门。
        receipt_id: 回执号（条目存在即有；纯预算拒绝无条目时为 None）。
        snapshot: 终态结果快照（completed/failed 重放时携带）。
        reason: 人读诊断（拒绝原因/预算耗尽/异常摘要）。
        diagnostics: 结构化诊断（车道/条目龄期/毒化态等）。
    """

    outcome: str
    key: str
    fingerprint: str
    proceed: bool = False
    retry_allowed: bool = False
    receipt_id: str | None = None
    snapshot: dict[str, Any] | None = None
    reason: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Entry:
    """回执条目（进程内有界缓存的一行）。"""

    key: str
    fingerprint: str
    state: str
    receipt_id: str
    created_mono: float
    expires_mono: float
    snapshot: dict[str, Any] | None = None
    bytes_est: int = _SNAPSHOT_OVERHEAD_BYTES
    note: str = ""


class RequestReceiptLedger:
    """请求回执账本（有界缓存 + 车道毒化 + 单调时钟预算）。

    单实例可跨线程共享（内部 RLock）；同一"通道/车道"应共用一个实例。
    时钟一律单调（``time.monotonic``，可注入）；TTL/容量/字节三界见
    模块 docstring。
    """

    def __init__(
        self,
        *,
        ttl_s: float = DEFAULT_TTL_S,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_s <= 0:
            raise ValueError("ttl_s 必须 > 0")
        if max_entries <= 0 or max_bytes <= 0:
            raise ValueError("max_entries/max_bytes 必须 > 0")
        self._ttl_s = float(ttl_s)
        self._max_entries = int(max_entries)
        self._max_bytes = int(max_bytes)
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._poisoned: dict[str, str] = {}  # lane -> 毒化原因
        self._bytes_total = 0

    # ── 查询/判定面 ───────────────────────────────────────────────────

    def claim(
        self,
        key: str,
        fingerprint: str,
        *,
        lane: str = DEFAULT_LANE,
        deadline_mono: float | None = None,
    ) -> ReceiptDecision:
        """提交判定（发射前唯一闸门）。

        返回 ``proceed=True``（not_started，调用方可发射）或任一
        ``proceed=False`` 判定（快照重放/unknown/拒绝/预算耗尽）。
        同键异载荷、时间窗外、车道毒化 → ``rejected``。
        """
        key = str(key)
        fingerprint = str(fingerprint)
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                return self._decide_on_entry(entry, fingerprint, lane, now)
            # 无条目：预算 → 车道 → 新建 pending（确定未发送域）
            if deadline_mono is not None and now >= float(deadline_mono):
                return ReceiptDecision(
                    outcome=OUTCOME_NOT_STARTED, key=key, fingerprint=fingerprint,
                    proceed=False, retry_allowed=True, receipt_id=None,
                    reason="请求预算耗尽（单调时钟 deadline，确定未发送）",
                    diagnostics={"budget_exhausted": True, "lane": lane},
                )
            if lane in self._poisoned:
                return ReceiptDecision(
                    outcome=OUTCOME_REJECTED, key=key, fingerprint=fingerprint,
                    reason=f"车道毒化中（归属不确定，探针重同步后解除）: "
                           f"{self._poisoned[lane][:160]}",
                    diagnostics={"lane": lane, "lane_poisoned": True},
                )
            entry = _Entry(
                key=key, fingerprint=fingerprint, state=STATE_PENDING,
                receipt_id=new_receipt_id(), created_mono=now,
                expires_mono=now + self._ttl_s,
            )
            self._entries[key] = entry
            self._enforce_bounds_locked()
            return ReceiptDecision(
                outcome=OUTCOME_NOT_STARTED, key=key, fingerprint=fingerprint,
                proceed=True, retry_allowed=True, receipt_id=entry.receipt_id,
                reason=None,
                diagnostics={"entry_state": STATE_PENDING, "lane": lane},
            )

    def resume(
        self,
        key: str,
        fingerprint: str,
        *,
        lane: str = DEFAULT_LANE,
    ) -> ReceiptDecision:
        """对账查询（只读，零状态迁移）——跨重启/人工对账入口。

        账本无此键 → **unknown**（回执缓存丢失/进程重启，如实声明；
        绝不返回 not_started——缺乏证据不得伪造成"确定未发送"）。
        有条目 → 与 claim 读侧同语义（终态重放/在飞 unknown/过期拒绝）。
        """
        key = str(key)
        fingerprint = str(fingerprint)
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return ReceiptDecision(
                    outcome=OUTCOME_UNKNOWN, key=key, fingerprint=fingerprint,
                    proceed=False, retry_allowed=False, receipt_id=None,
                    reason="回执缓存无此键（进程重启后回执丢失=如实 unknown；"
                           "不得按 not_started 重放）",
                    diagnostics={"ledger_miss": True, "lane": lane},
                )
            return self._decide_on_entry(entry, fingerprint, lane, now)

    # ── 迁移面（执行器生命周期回调）───────────────────────────────────

    def mark_sent(self, key: str) -> bool:
        """登记"已交给执行器"（发射边界）。pending → sent。幂等。"""
        with self._lock:
            entry = self._entries.get(str(key))
            if entry is None or entry.state not in (STATE_PENDING, STATE_SENT):
                return False
            entry.state = STATE_SENT
            return True

    def mark_completed(self, key: str, snapshot: dict[str, Any] | None = None) -> bool:
        """确定终态：completed（带快照）。sent/pending/completed 均可落定。"""
        return self._settle_terminal(str(key), STATE_COMPLETED, snapshot)

    def mark_failed(self, key: str, snapshot: dict[str, Any] | None = None) -> bool:
        """确定终态：failed（带快照，如 ``{"error": ...}``）。"""
        return self._settle_terminal(str(key), STATE_FAILED, snapshot)

    def mark_unknown(self, key: str, *, reason: str, lane: str = DEFAULT_LANE) -> ReceiptDecision:
        """归属不可证：条目保持 sent（unknown 域）并**毒化车道**。

        unknown 永不自动重放——同键后续 claim 落在 sent 条目上继续返回
        unknown，直到 ``reconcile`` 对账落定。
        """
        key = str(key)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.state = STATE_SENT  # unknown 域：保持 sent，不落终态
                entry.note = str(reason)[:200]
            self._poison_lane_locked(str(lane), reason)
            return ReceiptDecision(
                outcome=OUTCOME_UNKNOWN, key=key,
                fingerprint=entry.fingerprint if entry else "",
                proceed=False, retry_allowed=False,
                receipt_id=entry.receipt_id if entry else None,
                reason=str(reason)[:240],
                diagnostics={"entry_state": STATE_SENT, "lane": str(lane),
                             "lane_poisoned": True},
            )

    def rollback_pending(self, key: str) -> bool:
        """回收未发射条目（确定未发送）：删除 pending 条目，同键可重试。"""
        with self._lock:
            key = str(key)
            entry = self._entries.get(key)
            if entry is None or entry.state != STATE_PENDING:
                return False
            del self._entries[key]
            self._bytes_total -= entry.bytes_est
            return True

    def rollback_not_sent(self, key: str) -> bool:
        """回收"确定未发送"条目（执行器权威断言路径）。

        与 :meth:`rollback_pending` 的差别：执行器抬 ``NotSentError``（或
        调用方注入的 not_sent 异常）即是对"发送未发生"的**权威断言**——
        即便包裹层已乐观 ``mark_sent``（发射边界先于执行体），该断言也
        覆盖之：pending/sent 两条目均回收，同键可重试。仅 ``unknown``
        域之外的非确定态可用；终态条目不回收。
        """
        with self._lock:
            key = str(key)
            entry = self._entries.get(key)
            if entry is None or entry.state not in (STATE_PENDING, STATE_SENT):
                return False
            del self._entries[key]
            self._bytes_total -= entry.bytes_est
            return True

    def reconcile(
        self,
        key: str,
        *,
        outcome: str,
        snapshot: dict[str, Any] | None = None,
        note: str = "",
    ) -> bool:
        """人工/探针对账后显式落定 unknown 条目（"凭回执对账"的写侧）。

        outcome=completed/failed → 落终态（带快照）；outcome=not_started →
        确定未发送，回收条目（此后同键 claim 视为新提交）。其余 outcome
        或键不存在 → False（调用方如实处理，不静默）。
        """
        key = str(key)
        if outcome not in (OUTCOME_COMPLETED, OUTCOME_FAILED, OUTCOME_NOT_STARTED):
            return False
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if outcome == OUTCOME_NOT_STARTED:
                if entry.state == STATE_PENDING:
                    return self.rollback_pending(key)
                return False  # sent 条目不得凭一句话洗成"未发送"
            entry.state = STATE_COMPLETED if outcome == OUTCOME_COMPLETED else STATE_FAILED
            self._assign_snapshot(entry, snapshot)
            entry.note = str(note)[:200]
            return True

    # ── 车道面 ────────────────────────────────────────────────────────

    def poison_lane(self, lane: str, reason: str) -> None:
        """显式毒化车道（归属不确定时通道整体不可信）。"""
        with self._lock:
            self._poison_lane_locked(str(lane), reason)

    def resync_lane(self, lane: str) -> bool:
        """探针重同步成功后解除车道毒化。返回是否确有解除。"""
        with self._lock:
            return self._poisoned.pop(str(lane), None) is not None

    def lane_state(self, lane: str) -> dict[str, Any]:
        with self._lock:
            return {"lane": str(lane), "poisoned": str(lane) in self._poisoned,
                    "reason": self._poisoned.get(str(lane))}

    def peek(self, key: str) -> dict[str, Any] | None:
        """轻量只读探视（结算面用）：state/receipt_id/龄期；无键 None。"""
        with self._lock:
            entry = self._entries.get(str(key))
            if entry is None:
                return None
            return {
                "key": entry.key, "state": entry.state,
                "receipt_id": entry.receipt_id, "fingerprint": entry.fingerprint,
                "age_s": round(self._clock() - entry.created_mono, 6),
                "note": entry.note,
            }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for e in self._entries.values():
                counts[e.state] = counts.get(e.state, 0) + 1
            return {
                "entries": len(self._entries),
                "bytes_est": self._bytes_total,
                "max_entries": self._max_entries,
                "max_bytes": self._max_bytes,
                "ttl_s": self._ttl_s,
                "state_counts": counts,
                "poisoned_lanes": dict(self._poisoned),
            }

    # ── 内部 ──────────────────────────────────────────────────────────

    def _decide_on_entry(
        self, entry: _Entry, fingerprint: str, lane: str, now: float,
    ) -> ReceiptDecision:
        """对既有条目的判定（claim/resume 共用读侧；锁内调用）。"""
        age_s = round(now - entry.created_mono, 6)
        base_diag = {"entry_state": entry.state, "age_s": age_s, "lane": lane}
        if entry.state != STATE_EXPIRED and now >= entry.expires_mono:
            # TTL 窗外：转墓碑（同键再提交拒绝，防旧回执漂白成新提交）
            entry.state = STATE_EXPIRED
            entry.snapshot = None
            self._bytes_total -= entry.bytes_est
            entry.bytes_est = _SNAPSHOT_OVERHEAD_BYTES
        if entry.state == STATE_EXPIRED:
            return ReceiptDecision(
                outcome=OUTCOME_REJECTED, key=entry.key, fingerprint=fingerprint,
                receipt_id=entry.receipt_id,
                reason=f"回执时间窗外（TTL {self._ttl_s:.0f}s 已过，"
                       "旧回执不可再消费；请换新键或带证据对账）",
                diagnostics={**base_diag, "window_expired": True},
            )
        if entry.fingerprint != fingerprint:
            return ReceiptDecision(
                outcome=OUTCOME_REJECTED, key=entry.key, fingerprint=fingerprint,
                receipt_id=entry.receipt_id,
                reason="同键异载荷（载荷指纹不匹配；幂等键与载荷必须一一对应）",
                diagnostics={**base_diag, "payload_mismatch": True,
                             "stored_fingerprint": entry.fingerprint},
            )
        if entry.state in (STATE_COMPLETED, STATE_FAILED):
            return ReceiptDecision(
                outcome=entry.state, key=entry.key, fingerprint=fingerprint,
                proceed=False, retry_allowed=False, receipt_id=entry.receipt_id,
                snapshot=dict(entry.snapshot) if entry.snapshot else None,
                reason="同键同载荷终态回执（快照重放，执行器不重复执行）",
                diagnostics=base_diag,
            )
        # pending / sent：在飞或归属未落定 → unknown（永不自动重放）
        return ReceiptDecision(
            outcome=OUTCOME_UNKNOWN, key=entry.key, fingerprint=fingerprint,
            proceed=False, retry_allowed=False, receipt_id=entry.receipt_id,
            reason="同键请求已在册且结局未落定（unknown 永不自动重放，"
                   "须凭回执对账 reconcile 后处理）",
            diagnostics={**base_diag, "lane_poisoned": lane in self._poisoned},
        )

    def _settle_terminal(self, key: str, state: str,
                         snapshot: dict[str, Any] | None) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.state not in (
                STATE_PENDING, STATE_SENT, STATE_COMPLETED, STATE_FAILED,
            ):
                return False
            entry.state = state
            self._assign_snapshot(entry, snapshot)
            return True

    def _assign_snapshot(self, entry: _Entry,
                         snapshot: dict[str, Any] | None) -> None:
        self._bytes_total -= entry.bytes_est - _SNAPSHOT_OVERHEAD_BYTES
        entry.snapshot = None
        entry.bytes_est = _SNAPSHOT_OVERHEAD_BYTES
        if snapshot is None:
            return
        try:
            raw = json.dumps(snapshot, sort_keys=True, default=str,
                             ensure_ascii=True).encode("utf-8")
            n = len(raw)
        except (TypeError, ValueError):  # pragma: no cover - default=str 兜底
            n = self._max_bytes + 1
        if n > self._max_bytes:
            # 单快照超界：不存正文，存省略标记（回执仍在，快照如实降级）
            entry.snapshot = {"_snapshot_elided": True, "bytes": int(n)}
            entry.bytes_est = _SNAPSHOT_OVERHEAD_BYTES * 2
        else:
            entry.snapshot = snapshot
            entry.bytes_est = _SNAPSHOT_OVERHEAD_BYTES + int(n)
        self._bytes_total += entry.bytes_est - _SNAPSHOT_OVERHEAD_BYTES

    def _poison_lane_locked(self, lane: str, reason: str) -> None:
        self._poisoned.setdefault(lane, str(reason)[:200])

    def _enforce_bounds_locked(self) -> None:
        """三界收缩：先过期墓碑、再终态 LRU；在飞（pending/sent）尽量保留。"""
        now = self._clock()
        # ① 惰性过期（转墓碑而非删除——同键拒绝面）
        for entry in self._entries.values():
            if entry.state != STATE_EXPIRED and now >= entry.expires_mono:
                entry.state = STATE_EXPIRED
                self._bytes_total -= entry.bytes_est - _SNAPSHOT_OVERHEAD_BYTES
                entry.snapshot = None
                entry.bytes_est = _SNAPSHOT_OVERHEAD_BYTES
        if (len(self._entries) <= self._max_entries
                and self._bytes_total <= self._max_bytes):
            return
        # ② 先淘汰过期墓碑（最老优先）
        for key, entry in list(self._entries.items()):
            if entry.state == STATE_EXPIRED:
                del self._entries[key]
                self._bytes_total -= entry.bytes_est
            if (len(self._entries) <= self._max_entries
                    and self._bytes_total <= self._max_bytes):
                return
        # ③ 再淘汰终态 LRU（OrderedDict 尾=最新）
        for key, entry in list(self._entries.items()):
            if entry.state in (STATE_COMPLETED, STATE_FAILED, STATE_PENDING,
                               STATE_SENT):
                del self._entries[key]
                self._bytes_total -= entry.bytes_est
            if (len(self._entries) <= self._max_entries
                    and self._bytes_total <= self._max_bytes):
                return


def resolve_ledger(ledger: RequestReceiptLedger | None) -> RequestReceiptLedger:
    """显式账本优先，缺省进程级单例（service 接入面的统一取账本口径）。"""
    return ledger if ledger is not None else get_default_ledger()


_DEFAULT_LEDGER: RequestReceiptLedger | None = None
_DEFAULT_LOCK = threading.Lock()


def get_default_ledger() -> RequestReceiptLedger:
    """进程级缺省账本（懒建单例；同进程内所有未显式传账本的接入面共享）。"""
    global _DEFAULT_LEDGER
    with _DEFAULT_LOCK:
        if _DEFAULT_LEDGER is None:
            _DEFAULT_LEDGER = RequestReceiptLedger()
        return _DEFAULT_LEDGER


def reset_default_ledger() -> None:
    """重置缺省账本（测试专用；生产面禁止调用——重放面即丢）。"""
    global _DEFAULT_LEDGER
    with _DEFAULT_LOCK:
        _DEFAULT_LEDGER = None


# ── 执行器包裹（故障注入钉与 service 接入共用的执行面）─────────────────────

def execute_with_receipt(
    ledger: RequestReceiptLedger,
    *,
    key: str,
    fingerprint: str,
    executor: Callable[[], Any],
    lane: str = DEFAULT_LANE,
    deadline_mono: float | None = None,
    uncertain_exceptions: Iterable[type[BaseException]] = (),
    not_sent_exceptions: Iterable[type[BaseException]] = (),
) -> ReceiptDecision:
    """带回执的执行器包裹：claim → 发射边界 → 异常三分类 → 落定。

    异常三分类（先标记类、后调用方注入元组、最后确定失败）：
    - ``NotSentError`` / ``not_sent_exceptions`` → 回收条目 + ``not_started``
      （确定未发送，允许重试）；
    - ``UncertainOutcomeError`` / ``uncertain_exceptions`` → ``unknown``
      （条目保持 sent + 毒化车道，永不自动重放）；
    - 其余异常 → ``failed``（确定失败，快照 ``{"error": ...}``）。

    执行器返回值非 dict 时以 ``{"result": <value>}`` 包装落快照。

    预算判定与 claim 同源同钟（观察位 5：预检+执行共享一个单调 deadline；
    claim 的预算分支先于条目创建，耗尽即 not_started 且不落条目）。
    """
    key = str(key)
    fingerprint = str(fingerprint)
    decision = ledger.claim(key, fingerprint, lane=lane, deadline_mono=deadline_mono)
    if not decision.proceed:
        return decision
    receipt_id = decision.receipt_id
    ledger.mark_sent(key)
    not_sent_types = (NotSentError, *tuple(not_sent_exceptions))
    uncertain_types = (UncertainOutcomeError, *tuple(uncertain_exceptions))
    try:
        snapshot = executor()
    except not_sent_types as exc:  # type: ignore[misc]
        ledger.rollback_not_sent(key)
        return ReceiptDecision(
            outcome=OUTCOME_NOT_STARTED, key=key, fingerprint=fingerprint,
            proceed=False, retry_allowed=True, receipt_id=None,
            reason=f"确定未发送: {type(exc).__name__}: {str(exc)[:160]}",
            diagnostics={"not_sent": True, "lane": str(lane)},
        )
    except uncertain_types as exc:  # type: ignore[misc]
        return ledger.mark_unknown(
            key, lane=lane,
            reason=f"发送后归属不可证: {type(exc).__name__}: {str(exc)[:160]}",
        )
    except Exception as exc:  # 确定失败（执行器自身给出的明确错误）
        snap = {"error": f"{type(exc).__name__}: {str(exc)[:400]}"}
        ledger.mark_failed(key, snap)
        return ReceiptDecision(
            outcome=OUTCOME_FAILED, key=key, fingerprint=fingerprint,
            proceed=False, retry_allowed=False, receipt_id=receipt_id,
            snapshot=snap, reason=snap["error"],
            diagnostics={"lane": str(lane)},
        )
    snap = snapshot if isinstance(snapshot, dict) else {"result": snapshot}
    ledger.mark_completed(key, snap)
    return ReceiptDecision(
        outcome=OUTCOME_COMPLETED, key=key, fingerprint=fingerprint,
        proceed=False, retry_allowed=False, receipt_id=receipt_id,
        snapshot=dict(snap), reason=None, diagnostics={"lane": str(lane)},
    )
