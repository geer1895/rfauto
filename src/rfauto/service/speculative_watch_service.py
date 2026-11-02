"""devtest 投机执行 watcher 档（T-O11 扩容，aurora_p F1-deep）——文件系统
轮询自动触发 + 事件洪峰 Batch 合并 + 确定性 Fast Path。

Super-agent 机制化用（思想吸收非代码复制；源=DeepSeek
dsh-superagent-prototype，MIT，实读档案见 runs/aurora_p/f1deep/ABSORB_DEEP.md）：
- **事件洪峰 Batch 合并**（docs/007 evaluateDue 同 Thread 多 Trigger 合并为一次
  Eval）：debounce 窗内的多次 src 变更合并为**一次**预跑发射，窗口终态指纹为准
  （devtest._changed_src 是全量 diff 视图，天然只关心最终态，不追中间态）；
- **确定性 Fast Path**（论文《Exploring Super-agent Design》§3.1 两级过滤——
  程序策略先行、昂贵路径靠后；rfauto 语境下"昂贵路径"=预跑子进程）：
  src 未变/缓存命中/单实例占用/#261 census 忙四类确定性条件直判 wait/no-op，
  零子进程零文件写（全链无 LLM——规则 7 铁律天然满足）；
- **Source 轮询循环四件套**（docs/008-cookbook：cursor/健康报告/abort/轮询
  间隔下限）：内存指纹 cursor、白名单 jsonl 逐轮观测、should_stop 优雅停止、
  MIN_INTERVAL_S 资源下限一一对应。

分层与单源（规则 3/4）：
- 纯逻辑核心（:func:`evaluate_tick`/:func:`wait_decision`）与 IO 面
  （:func:`watch_loop`）分离——核心零 sleep 全注入；
- 触发/互斥/缓存**全链复用 T-O11**（service/devtest_speculative_service.py
  公开函数，零复制）：watcher 是周期性调用 speculative_run 的确定性编排面；
- 变更检测由薄驱动消费 ``devtest._changed_src`` 单源后以 ``collect_fn``
  显式注入（scripts 不可被 src 导入，分层家法同 T-O11 docstring 口径）。

红线（任务书口径）：
1. **缺省关**：模块 import 零副作用；watch_loop 生成器无人消费零后台行为
   零写（T-O12 watch_loop 家法）；显式触发/查询档（T-O11 原两模式）与本
   模块无关、逐字节不变（content_digest 缺省 None 时 T-O11 指纹逐位同）。
2. **单实例+互斥 fail-closed**：复用 T-O11 心跳与 census 判据——在跑/不可
   验证 → 本轮 wait（不发射不落 declined 假记录，暂态让位下轮重判）。
3. **资源上限**：轮询间隔下限 MIN_INTERVAL_S；xdist 顶/墙钟数值沿用 T-O11
   常量单源（WORKERS_CAP/DEFAULT_TIMEOUT_S 不在本模块复制）。
4. **白名单写面**：唯一写点=每轮观测 jsonl，经 ``dss.guard_cache_path``
   落 runs/devtest_speculative/ 白名单单根（#144 反向钉），写失败降级
   ``sink_write_ok=False`` 不抛（#105 观测面 best-effort）。

消费面：scripts/devtest_speculative.py 的 ``watch`` 子命令（显式 opt-in）。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rfauto.service import devtest_speculative_service as dss
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "DEFAULT_DEBOUNCE_S",
    "DEFAULT_INTERVAL_S",
    "DEFAULT_ROUNDS",
    "MIN_INTERVAL_S",
    "WATCH_STATE_SCHEMA",
    "WatchConfig",
    "changed_fingerprint",
    "content_digest_of",
    "evaluate_tick",
    "resolve_watch_cache_root",
    "wait_decision",
    "watch_loop",
]

#: 观测 jsonl 行 schema 标记（形态自描述；缓存内容面仍走 T-O11 两个 schema）。
WATCH_STATE_SCHEMA = "rfauto-speculative-watch-v1"

#: 资源上限（红线 3）：轮询间隔下限 1s（探底不探顶——更密的轮询只在显式
#: 缩小 interval 且不低于本限时生效）。
MIN_INTERVAL_S = 1.0
#: 缺省轮询间隔（s）。
DEFAULT_INTERVAL_S = 5.0
#: 缺省 debounce 窗（s）：采样到新变更面后静默等待窗满再复采样——窗内演进
#: （复采样指纹变化）则续等下一窗，**窗口终态指纹为准**（docs/007
#: evaluateDue 合并语义：洪峰合并为一次决策，只发最终态）。
DEFAULT_DEBOUNCE_S = 3.0
#: 缺省轮数（0=无限——显式 opt-in 后台常驻缺省形态；测试/冒烟传正整数）。
DEFAULT_ROUNDS = 0

_TICK_SLICE_S = 0.2  # sleep 分片粒度（停止响应 ≤ 一片）


@dataclass(frozen=True)
class WatchConfig:
    """watch 档配置（纯值对象；缺省=常量/T-O11 单源）。"""

    interval_s: float = DEFAULT_INTERVAL_S
    debounce_s: float = DEFAULT_DEBOUNCE_S
    rounds: int = DEFAULT_ROUNDS
    workers: int = dss.WORKERS_CAP
    timeout_s: float = dss.DEFAULT_TIMEOUT_S
    min_trigger_interval_s: float = dss.DEFAULT_MIN_TRIGGER_INTERVAL_S
    cache_root: str | os.PathLike[str] | None = None
    #: 观测 jsonl 开关（缺省开——观测是 watch 档的合法性证据面）；写面仍受
    #: 白名单守卫。单测可关（零写面断言更直）。
    sink_enabled: bool = True


# ── 纯逻辑核心（零 sleep、IO 全注入） ────────────────────────────────────────


def changed_fingerprint(
    changed_src: Sequence[str],
    *,
    tests: Sequence[str],
    head: str | None,
    map_digest: str | None,
    content_digest: str | None,
) -> tuple[str, list[str], list[str]]:
    """变更面指纹采样（纯函数，watch 档与 T-O11 共用 dss.compute_fingerprint
    单源）：返回 (fp, kept_tests, dropped_tests)。真机面先剔（红线 1）再入
    指纹——与 speculative_run 内部同判据，同 tree 同输入 → 同 fp（确定性⑤）。"""
    changed = sorted({str(c).replace("\\", "/") for c in changed_src if str(c)})
    kept, dropped = dss.strip_real_machine_tests(tests)
    fp, _fields = dss.compute_fingerprint(
        changed, head=head, map_digest=map_digest, tests=kept, content_digest=content_digest
    )
    return fp, kept, dropped


def content_digest_of(
    changed_src: Sequence[str], *, root: str | os.PathLike[str] | None = None
) -> str | None:
    """变更文件**内容**摘要（watch 档内容感知口径）：对每个变更文件读字节
    sha256 后对清单摘要。空清单/全部不可读 → None（调用方退化为路径集口径）。
    纯读零写；单测用 tmp 树注入 root。"""
    base = Path(root) if root is not None else dss.repo_root()
    parts: list[str] = []
    for rel in sorted({str(c).replace("\\", "/") for c in changed_src if str(c)}):
        p = base / rel
        try:
            parts.append(rel + ":" + hashlib.sha256(p.read_bytes()).hexdigest())
        except OSError:
            parts.append(rel + ":-")
    text = "\n".join(parts)
    if not parts:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _in_flight_alive(record: object, alive_fn: Callable[[object], bool]) -> bool:
    """在飞判定：指纹记录 state=running 且 child_pid 存活（T-O11
    speculative_run/speculative_status 内联判据同款——此处只读复刻为纯谓词，
    判据字段（state/child_pid）与存活口径与 T-O11 一致，零新语义）。"""
    if not isinstance(record, dict):
        return False
    if record.get("state") != "running":
        return False
    child = record.get("child_pid")
    return child is not None and bool(alive_fn(child))


def wait_decision(
    fingerprint: str,
    *,
    in_flight_fp: str | None,
    in_flight_alive: bool,
    heartbeat_busy: bool,
    census_ok: bool,
    debounce_remaining: float = 0.0,
) -> dict[str, Any]:
    """单指纹的确定性 Fast Path 判定（纯函数，规则表 R2-R5 单源）。

    返回 ok 信封：state ∈ fire / wait / absorbed。判定序=规则表序
    （吸收 → R2 单实例 → R3 census → R4 防抖 → 发射）。R1（src 未变/缓存
    命中）在 :func:`evaluate_tick` 前置直判（需读缓存文件，不在本纯函数）。"""
    if in_flight_fp is not None and in_flight_alive and fingerprint == in_flight_fp:
        return ok_envelope(
            state="absorbed",
            fingerprint=fingerprint,
            reason="同指纹在飞（Batch 合并：窗口内后续变更并入在飞轮，不二发）",
        )
    if heartbeat_busy:
        return ok_envelope(
            state="wait",
            fast_path="single_instance",
            fingerprint=fingerprint,
            reason="Fast Path R2：上一轮 child/owner 存活（单实例）——等待，不落拒绝记录",
        )
    if not census_ok:
        return ok_envelope(
            state="wait",
            fast_path="mutex_busy_or_unverified",
            fingerprint=fingerprint,
            reason=(
                "Fast Path R3：#261 census 忙（在跑 pytest/runner/求解进程）"
                "或不可验证（fail-closed 同 T-O11）——等待"
            ),
        )
    if debounce_remaining > 0:
        return ok_envelope(
            state="wait",
            fast_path="debounce_window",
            fingerprint=fingerprint,
            reason=f"Fast Path R4：debounce 窗余 {debounce_remaining:.1f}s（窗口终态为准）",
        )
    return ok_envelope(state="fire", fingerprint=fingerprint, reason="规则全绿——发射一轮预跑")


def evaluate_tick(
    changed_src: Sequence[str],
    *,
    tests: Sequence[str],
    head: str | None,
    map_digest: str | None,
    cache_root: str | os.PathLike[str],
    config: WatchConfig,
    content_digest: str | None = None,
    debounce_remaining: float = 0.0,
    alive_fn: Callable[[object], bool] | None = None,
    census_fn: Callable[[], list[dict[str, Any]] | None] | None = None,
    spawn_fn: Callable[[list[str], Path], int] | None = None,
    owner_pid: int | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """单 tick 评估（核心）：采样态 → Fast Path 规则表 → （全绿时）发射一轮。

    返回信封含 ``decision``（fire/wait/absorbed/nothing_to_do）与发射结果
    （fire 时嵌 ``trigger``=speculative_run 信封）。零子进程直到 fire 且
    规则全绿；本函数不 sleep、不写观测面（IO 归 watch_loop）。"""
    now_ts = time.time() if now is None else float(now)
    alive = alive_fn or dss.pid_alive
    changed = sorted({str(c).replace("\\", "/") for c in changed_src if str(c)})
    if not changed:
        return ok_envelope(
            decision="nothing_to_do",
            state="nothing_to_do",
            reason="git diff 无 src/rfauto 变更——Fast Path 直判零子进程",
        )
    try:
        root = dss.validate_cache_root(dss.resolve_cache_root(cache_root))
    except dss.SpeculativeGuardError as exc:
        return error_envelope(f"缓存根白名单校验拒绝：{exc}")

    fp, _kept, _dropped = changed_fingerprint(
        changed, tests=tests, head=head, map_digest=map_digest, content_digest=content_digest
    )
    # Fast Path R1：同指纹且缓存 done+summary 命中 → 直判零子进程
    # （T-O11 speculative_run 也会幂等返回 cached，但那条路仍会跑 census——
    # 这里先判省一次 PS 探针，语义等价）。
    record = dss._read_json(root / dss.FINGERPRINT_NAME)
    if (
        isinstance(record, dict)
        and record.get("fingerprint") == fp
        and record.get("state") == "done"
    ):
        summary = dss._read_json(root / dss.SUMMARY_NAME)
        if isinstance(summary, dict) and summary.get("fingerprint") == fp:
            return ok_envelope(
                decision="nothing_to_do",
                state="cached",
                fast_path="cache_hit",
                fingerprint=fp,
                summary=summary,
                reason="Fast Path R1：同指纹缓存命中——红绿已有，零子进程",
            )
    in_flight = _in_flight_alive(record, alive)
    in_flight_fp = record.get("fingerprint") if isinstance(record, dict) else None
    if in_flight and in_flight_fp == fp:
        # Batch 合并吸收路径零探针：同指纹在飞直接判 absorbed（不跑 census/
        # 心跳复核——在飞即忙的充分条件，省一次 PS 探针）。
        return {
            **wait_decision(
                fp, in_flight_fp=in_flight_fp, in_flight_alive=True,
                heartbeat_busy=False, census_ok=True,
            ),
            "decision": "absorbed",
        }
    hb_busy, _why = dss._runner_conflict(
        dss.read_heartbeat(root / dss.HEARTBEAT_NAME),
        alive,
        int(owner_pid) if owner_pid is not None else os.getpid(),
    )
    hits = (census_fn or dss.default_local_census)()
    decision = wait_decision(
        fp,
        in_flight_fp=in_flight_fp,
        in_flight_alive=in_flight,
        heartbeat_busy=bool(hb_busy),
        census_ok=hits is not None and len(hits) == 0,
        debounce_remaining=debounce_remaining,
    )
    if decision["state"] != "fire":
        return {**decision, "decision": decision["state"]}
    trigger = dss.speculative_run(
        changed,
        tests=tests,
        head=head,
        map_digest=map_digest,
        cache_root=root,
        workers=config.workers,
        timeout_s=config.timeout_s,
        min_trigger_interval_s=config.min_trigger_interval_s,
        census_fn=census_fn,
        pid_alive_fn=alive,
        spawn_fn=spawn_fn,
        owner_pid=owner_pid,
        now=now_ts,
        content_digest=content_digest,
    )
    trig_state = trigger.get("state")
    if trig_state == "cached":
        return ok_envelope(
            decision="nothing_to_do",
            state="cached",
            fast_path="cache_hit",
            fingerprint=fp,
            summary=trigger.get("summary"),
            reason="发射口幂等命中（同指纹缓存 done）——零新发射",
        )
    if trig_state in ("declined", "already_running"):
        return ok_envelope(
            decision="wait",
            state=trig_state,
            guard=trigger.get("guard"),
            fingerprint=fp,
            census_hits=trigger.get("census_hits"),
            reason=f"发射口守卫如实回传（{trig_state}）：{trigger.get('reason')}",
        )
    if trig_state == "nothing_to_do":
        return ok_envelope(
            decision="nothing_to_do",
            state="nothing_to_do",
            fingerprint=fp,
            reason=f"发射口如实回传：{trigger.get('reason')}",
        )
    return ok_envelope(
        decision="fire",
        state=trig_state,
        fingerprint=fp,
        trigger=trigger,
        reason="watch 档发射一轮预跑（Batch 窗口终态指纹）",
    )


# ── IO 面（轮询循环；生成器形态——T-O12 watch_loop 家法） ─────────────────────


def resolve_watch_cache_root(cache_root: str | os.PathLike[str] | None = None) -> Path:
    """watch 档缓存根解析：缺省=仓根/runs/devtest_speculative（T-O11 白名单
    单根同源——本档零新写点根）。"""
    if cache_root is None:
        return dss.repo_root() / dss.CACHE_ROOT_REL
    return Path(os.path.abspath(str(cache_root)))


def _append_watch_line(sink: Path, payload: dict[str, Any]) -> bool:
    """best-effort 追加一行观测 jsonl（#105；T-O12 _append_jsonl 家法）。"""
    try:
        sink.parent.mkdir(parents=True, exist_ok=True)
        with open(sink, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return True
    except OSError:
        return False


def _resolve_sink(
    root: Path, sink_path: str | os.PathLike[str] | None, enabled: bool
) -> Path | None:
    """观测面解析：enabled=False → None（零写）；否则白名单守卫（显式
    sink_path 覆写也必须落单根内——越界 ValueError 同 T-O12 watch_loop）。"""
    if not enabled:
        return None
    candidate = dss.guard_cache_path(root, f"watch_{os.getpid()}.jsonl")
    sink = Path(os.path.abspath(str(sink_path))) if sink_path is not None else candidate
    tail = dss._norm_key(sink)
    head_root = dss._norm_key(Path(os.path.abspath(root))).rstrip("/")
    if not (tail == head_root or tail.startswith(head_root + "/")):
        raise dss.SpeculativeGuardError(
            f"watch 观测面越出白名单单根：{sink} 不在 {root} 内"
        )
    return sink


def watch_loop(
    collect_fn: Callable[
        [], tuple[Sequence[str], str | None, str | None, Sequence[str]]
    ],
    *,
    cache_root: str | os.PathLike[str] | None = None,
    config: WatchConfig | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    census_fn: Callable[[], list[dict[str, Any]] | None] | None = None,
    alive_fn: Callable[[object], bool] | None = None,
    spawn_fn: Callable[[list[str], Path], int] | None = None,
    owner_pid: int | None = None,
    content_digest_fn: Callable[[Sequence[str]], str | None] = lambda _c: None,
    sink_path: str | os.PathLike[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """watch 轮询循环（**生成器**，显式驱动——默认无人消费=零后台零写）。

    collect_fn（薄驱动注入，零复制 devtest 单源）：每次采样返回
    ``(changed_src, head, map_digest, tests)``——changed/tests/map 摘要由
    devtest._changed_src/_get_selection/_ensure_map 单源消费后传入；
    content_digest 由 ``content_digest_fn(changed)`` 派生（缺省 None=路径集
    口径；驱动传 :func:`content_digest_of` 得内容感知口径）。

    **Batch 合并语义**：tick 采样到非空变更面 → 进入 debounce 窗（分片可打
    断 sleep）→ 窗满复采样：指纹仍演进则续等下一窗（最后指纹为准），收敛
    则以终态采样调用 :func:`evaluate_tick`（一窗至多一发射；洪峰两次变更
    合并为一次预跑——验收钉 C）。

    每 tick 产出一行决策信封（附 ``tick``/``sink_write_ok``）；观测 jsonl
    落白名单单根 ``watch_<pid>.jsonl``（sink_enabled=False 零写；写失败
    如实标注零抛）。``rounds`` 0=无限（should_stop 是唯一出口），正整数=
    显式轮数（测试/冒烟）。白名单/sink 越界校验在**调用期急切**执行
    （T-O12 家法：误用当场报，不等首轮迭代）。"""
    cfg = config or WatchConfig()
    root = dss.validate_cache_root(resolve_watch_cache_root(cache_root))
    sink = _resolve_sink(root, sink_path, cfg.sink_enabled)
    return _watch_iter(
        collect_fn, root, cfg, should_stop, sleep_fn, clock,
        census_fn, alive_fn, spawn_fn, owner_pid, content_digest_fn, sink,
    )


def _watch_iter(
    collect_fn: Callable[[], tuple[Sequence[str], str | None, str | None, Sequence[str]]],
    root: Path,
    cfg: WatchConfig,
    should_stop: Callable[[], bool],
    sleep_fn: Callable[[float], None],
    clock: Callable[[], float],
    census_fn: Callable[[], list[dict[str, Any]] | None] | None,
    alive_fn: Callable[[object], bool] | None,
    spawn_fn: Callable[[list[str], Path], int] | None,
    owner_pid: int | None,
    content_digest_fn: Callable[[Sequence[str]], str | None],
    sink: Path | None,
) -> Iterator[dict[str, Any]]:
    """watch_loop 迭代体（独立生成器函数：白名单校验保持在调用期急切执行）。"""
    interval = max(float(cfg.interval_s), MIN_INTERVAL_S)
    debounce = max(float(cfg.debounce_s), 0.0)

    def _stop_sleep(total: float) -> None:
        """分片可打断 sleep（停止响应 ≤ 一片）。"""
        remaining = max(float(total), 0.0)
        while remaining > 0 and not should_stop():
            step = min(_TICK_SLICE_S, remaining)
            sleep_fn(step)
            remaining -= step

    def _sample() -> tuple[Sequence[str], str | None, str | None, Sequence[str], str | None]:
        changed, head_sha, map_digest, tests = collect_fn()
        return changed, head_sha, map_digest, tests, content_digest_fn(changed)

    def _fp_of(sample: tuple[Any, ...]) -> str | None:
        changed, head_sha, map_digest, tests, digest = sample
        if not [c for c in changed if str(c)]:
            return None
        fp, _kept, _dropped = changed_fingerprint(
            changed, tests=tests, head=head_sha, map_digest=map_digest, content_digest=digest
        )
        return fp

    def _emit(decision: dict[str, Any], tick: int) -> dict[str, Any]:
        trig = decision.get("trigger")
        row = {
            "schema": WATCH_STATE_SCHEMA,
            "ts": clock(),
            "tick": tick,
            "decision": decision.get("decision"),
            "state": decision.get("state"),
            "fast_path": decision.get("fast_path"),
            "fingerprint": decision.get("fingerprint"),
            "trigger_state": trig.get("state") if isinstance(trig, dict) else None,
        }
        sink_ok = bool(_append_watch_line(sink, row)) if sink is not None else False
        return {**decision, "tick": tick, "sink_write_ok": sink_ok}

    tick = 0
    while True:
        cap = int(cfg.rounds)
        if cap > 0 and tick >= cap:
            return
        if should_stop():
            return
        tick += 1
        try:
            sample = _sample()
        except SystemExit as exc:
            yield ok_envelope(
                decision="error",
                state="collect_failed",
                reason=f"变更面/映射链失败（薄驱动如实上报）：{exc}",
                tick=tick,
                sink_write_ok=False,
            )
            return
        # Batch 合并：非空变更面 → debounce 窗（窗内演进续等，终态为准）。
        if _fp_of(sample) is not None and debounce > 0 and not should_stop():
            while not should_stop():
                _stop_sleep(debounce)
                if should_stop():
                    return
                resampled = _sample()
                if _fp_of(resampled) == _fp_of(sample):
                    sample = resampled
                    break
                sample = resampled  # 窗内演进：以新指纹为准续等下一窗
            if should_stop():
                return
        changed, head_sha, map_digest, tests, digest = sample
        decision = evaluate_tick(
            changed,
            tests=tests,
            head=head_sha,
            map_digest=map_digest,
            cache_root=root,
            config=cfg,
            content_digest=digest,
            alive_fn=alive_fn,
            census_fn=census_fn,
            spawn_fn=spawn_fn,
            owner_pid=owner_pid,
            now=clock(),
        )
        yield _emit(decision, tick)
        if cap > 0 and tick >= cap:
            return
        _stop_sleep(interval)
