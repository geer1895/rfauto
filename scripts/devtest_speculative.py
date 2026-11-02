"""devtest 投机执行档薄驱动（T-O11，aurora_o）——触发/查询/child 三模式。

独立脚本而非给 scripts/devtest.py 加参的选型理由：devtest.main() 的
``--changed`` 必选流与 exit code 契约（0/1/2/3）自成一体，投机档是"发射/
查询/收尾"三种不同语义，塞进同一 argparse 会纠缠互斥校验；本驱动零改
devtest.py，且把变更检测/映射选择**单源复用**其内部函数（零复制，ABSORB
T-O11"单源不复制"口径）：

    devtest._changed_src   git diff 变更 src 清单（--changed-src 显式覆盖）
    devtest._ensure_map    映射指纹新鲜度（过期自动再生，仅触发模式）
    devtest._get_selection 变更面 → 受影响测试清单
    build_impact_map.default_fingerprint_path → map 指纹文件（摘要入指纹）

用法::

    # 触发后台预跑（默认）：
    python scripts/devtest_speculative.py [--staged|--base REF] [--scope direct]
        [--workers N(<=4)] [--map PATH] [--cache-root PATH] [--timeout-s S]
        [--min-trigger-interval-s S] [--changed-src P1 P2 ...] [--json]
    # 查询（指纹命中秒回 / stale 如实；纯文件读零子进程）：
    python scripts/devtest_speculative.py --status [同上选择参数] [--json]
    # child（内部模式，由 service 分离发射；测试落日志、summary 落缓存）：
    python scripts/devtest_speculative.py --child --fingerprint FP --log PATH
        [--cache-root PATH] [--workers N] [--timeout-s S] -- tests...
    # watch（F1-deep，显式 opt-in 轮询自动触发档；不传 --watch 时上述
    # 三模式行为逐字节同 T-O11 现状）：
    python scripts/devtest_speculative.py --watch [--interval S(>=1)]
        [--debounce S] [--rounds N(0=无限)] [--no-sink] [同上选择参数]

--changed-src：显式变更面覆盖（E2E/定向触发用）——绕过 git diff，其余链路
（映射选择→指纹→缓存）完全同径。

exit code：0=查询/触发/watch 应答诚实（launched/cached/declined/…都算应答
成立，child 全绿同，watch 优雅停止同）；1=child 跑完有红测；2=用法错；
3=内部错（git 失败/映射不可用/子进程发射失败）。

红线（service 层单源强制，本驱动零旁路）：预跑永不真机（real_edt 路径剔除
+ `-m "not real_edt"` 双保险）；缓存白名单单根 runs/devtest_speculative；
xdist 硬顶 4、墙钟缺省 600s 超时 kill。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_REPO = _SCRIPTS.parent
for _p in (str(_SCRIPTS), str(_REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_impact_map as bim  # noqa: E402  （scripts 同目录：指纹路径单源）
import devtest  # noqa: E402  （scripts 同目录单源；本脚本 __file__ 已保证可达）
from rfauto.service import devtest_speculative_service as dss  # noqa: E402
from rfauto.service import speculative_watch_service as sws  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="devtest 投机执行档：src 变更后台预跑 + 指纹缓存秒回（T-O11）",
        epilog="exit code：0=应答成立/全绿；1=红测；2=用法错；3=内部错。详见模块 docstring。",
    )
    ap.add_argument("--status", action="store_true", help="查询模式：按当前变更面指纹查缓存（不发射）")
    ap.add_argument("--child", action="store_true", help="内部模式：执行预跑子进程体（service 发射，勿手调）")
    ap.add_argument("--staged", action="store_true", help="只看暂存区变更（透传 devtest 口径）")
    ap.add_argument("--base", default=None, help="对比指定 git 基线（透传 devtest 口径）")
    ap.add_argument(
        "--scope", choices=("direct", "closed"), default="direct",
        help="影响面口径（透传 devtest：direct=开发循环粒度缺省；closed=全量闭包）",
    )
    ap.add_argument(
        "--workers", type=int, default=dss.WORKERS_CAP,
        help=f"xdist worker 数（投机档硬顶 {dss.WORKERS_CAP}，探底不探顶）",
    )
    ap.add_argument("--map", default=str(devtest.DEFAULT_MAP), help="映射 YAML 路径")
    ap.add_argument("--cache-root", default=None, help="缓存根（缺省 runs/devtest_speculative，白名单单根）")
    ap.add_argument(
        "--timeout-s", type=float, default=dss.DEFAULT_TIMEOUT_S,
        help=f"单轮墙钟上限秒（缺省 {dss.DEFAULT_TIMEOUT_S:.0f}，超时 kill 进程树）",
    )
    ap.add_argument(
        "--min-trigger-interval-s", type=float,
        default=dss.DEFAULT_MIN_TRIGGER_INTERVAL_S,
        help="触发防抖窗秒（0=关闭；上一轮记录落成后窗内新指纹触发拒绝）",
    )
    ap.add_argument(
        "--changed-src", nargs="+", default=None,
        help="显式变更面覆盖（绕过 git diff；E2E/定向触发用，其余链路同径）",
    )
    ap.add_argument("--fingerprint", default=None, help="child 模式：变更面指纹（service 下发）")
    ap.add_argument("--log", default=None, help="child 模式：pytest 日志路径（缓存单根内）")
    ap.add_argument(
        "--watch", action="store_true",
        help="watch 档（F1-deep，显式 opt-in）：轮询 src 变更自动触发（debounce 洪峰合并"
             "+Fast Path 确定性直判；不传本旗标时三模式行为同 T-O11）",
    )
    ap.add_argument(
        "--interval", type=float, default=sws.DEFAULT_INTERVAL_S,
        help=f"watch：轮询间隔秒（下限 {sws.MIN_INTERVAL_S:.0f}，探底不探顶；缺省 {sws.DEFAULT_INTERVAL_S:.0f}）",
    )
    ap.add_argument(
        "--debounce", type=float, default=sws.DEFAULT_DEBOUNCE_S,
        help=f"watch：事件洪峰合并窗秒（窗口终态指纹为准；缺省 {sws.DEFAULT_DEBOUNCE_S:.0f}，0=关窗）",
    )
    ap.add_argument(
        "--rounds", type=int, default=sws.DEFAULT_ROUNDS,
        help="watch：轮数上限（0=无限常驻，Ctrl+C 优雅停；正整数=测试/冒烟）",
    )
    ap.add_argument(
        "--no-sink", action="store_true",
        help="watch：关闭观测 jsonl（缺省落缓存白名单单根 watch_<pid>.jsonl）",
    )
    ap.add_argument("--json", action="store_true", help="机器读：只打印信封 JSON（缺省人读摘要行）")
    return ap


def _emit(envelope: dict, *, as_json: bool, human_tag: str) -> None:
    if as_json:
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
        return
    state = envelope.get("state")
    print(f"[speculative] {human_tag} state={state}")
    for key in ("reason", "guard", "fingerprint", "child_pid", "tests_count",
                "workers", "log_path", "cached_fingerprint"):
        if envelope.get(key) not in (None, []):
            print(f"[speculative]   {key}={envelope[key]}")
    summary = envelope.get("summary")
    if isinstance(summary, dict):
        print(
            f"[speculative]   summary: passed={summary.get('passed')} "
            f"failed={summary.get('failed')} failed_ids={summary.get('failed_ids')} "
            f"log={summary.get('log_path')}"
        )


def _collect_inputs(args: argparse.Namespace) -> tuple[list[str], str | None, str | None, list[str], list[str]]:
    """变更面/HEAD/map 摘要/受影响测试/未入映射 —— devtest 单源消费（触发与
    查询共径）。_ensure_map 仅触发模式再生（status 纯读零再生，秒回口径）。"""
    if args.changed_src:
        changed = sorted({str(p).replace("\\", "/") for p in args.changed_src})
    else:
        changed = devtest._changed_src(args.staged, args.base)
    head = devtest._head()
    map_path = Path(args.map)
    if not args.status:
        devtest._ensure_map(map_path, args.scope)
    tests, not_in_map, _per_file = devtest._get_selection(map_path, args.scope, changed)
    map_digest = dss.map_fingerprint_digest(bim.default_fingerprint_path(map_path))
    return changed, head, map_digest, tests, not_in_map


def _run_trigger(args: argparse.Namespace, as_json: bool) -> int:
    try:
        changed, head, map_digest, tests, not_in_map = _collect_inputs(args)
    except SystemExit as exc:  # devtest._git/_ensure_map 的失败通道（人话已打印）
        _emit({"ok": False, "errors": [f"变更面/映射链失败：{exc}"]}, as_json=as_json,
              human_tag="trigger")
        return 3
    envelope = dss.speculative_run(
        changed,
        tests=tests,
        head=head,
        map_digest=map_digest,
        cache_root=args.cache_root,
        workers=args.workers,
        timeout_s=args.timeout_s,
        min_trigger_interval_s=args.min_trigger_interval_s,
    )
    if not_in_map and envelope.get("state") not in (None, "nothing_to_do"):
        envelope = {**envelope, "not_in_map": not_in_map}
    _emit(envelope, as_json=as_json, human_tag="trigger")
    if not envelope.get("ok"):
        return 3
    return 0


def _run_status(args: argparse.Namespace, as_json: bool) -> int:
    map_path = Path(args.map)
    if not map_path.exists():
        # status 纯读零再生（秒回口径）：映射缺失如实报，不触发 builder。
        _emit(
            {"ok": True, "state": "map_missing",
             "reason": f"映射缺失 {map_path}——status 不再生（先跑一次触发模式）"},
            as_json=as_json, human_tag="status",
        )
        return 0
    try:
        changed, head, map_digest, tests, not_in_map = _collect_inputs(args)
    except SystemExit as exc:
        _emit({"ok": False, "errors": [f"变更面/映射链失败：{exc}"]}, as_json=as_json,
              human_tag="status")
        return 3
    envelope = dss.speculative_status(
        changed, tests=tests, head=head, map_digest=map_digest, cache_root=args.cache_root
    )
    if not_in_map:
        envelope = {**envelope, "not_in_map": not_in_map}
    _emit(envelope, as_json=as_json, human_tag="status")
    return 0 if envelope.get("ok") else 3


def _run_child(args: argparse.Namespace, extra: list[str], as_json: bool) -> int:
    if not args.fingerprint or not args.log:
        _emit({"ok": False, "errors": ["--child 需要 --fingerprint 与 --log"]},
              as_json=as_json, human_tag="child")
        return 2
    tests = [t for t in extra if t != "--"]
    if not tests:
        _emit({"ok": False, "errors": ["--child 需要受影响测试清单（`--` 之后）"]},
              as_json=as_json, human_tag="child")
        return 2
    # stdout 重绑日志追加模式（单写者纪律）：分离发射的继承句柄无 CRT 追加
    # 语义（Windows 各进程按自己句柄位写互踩），本进程内统一 append 落日志。
    with contextlib.suppress(OSError):
        # SIM115 豁免：此句柄是 child 进程生命周期内的新 stdout（非泄漏），
        # 进程退出由 OS 回收；重绑失败沿用继承句柄兜底（#105）。
        sys.stdout = open(args.log, "a", buffering=1, encoding="utf-8")  # noqa: SIM115
    summary = dss.run_speculative_child(
        fingerprint=args.fingerprint,
        tests=tests,
        log_path=args.log,
        cache_root=args.cache_root,
        workers=args.workers,
        timeout_s=args.timeout_s,
        repo=_REPO,
    )
    _emit(summary, as_json=as_json, human_tag="child")
    if summary.get("state") == "failed":
        return 3
    if summary.get("pytest_rc") == 1:
        return 1
    return 0


def _run_watch(args: argparse.Namespace, as_json: bool) -> int:
    """watch 档驱动（F1-deep）：映射一次性保鲜 → 周期采样（devtest 单源零复制）
    → sws.watch_loop 消费。Ctrl+C 经 Event 优雅停（分片 sleep 响应 ≤ 一片）。"""
    import signal
    import threading

    if args.interval < sws.MIN_INTERVAL_S:
        print(
            f"[watch] --interval {args.interval} < 下限 {sws.MIN_INTERVAL_S:.0f}s"
            "（资源上限红线）→ 收敛"
        )
        args.interval = sws.MIN_INTERVAL_S
    map_path = Path(args.map)
    try:
        devtest._ensure_map(map_path, args.scope)  # 映射保鲜：watch 启动时一次（触发口径）
    except SystemExit as exc:
        _emit({"ok": False, "errors": [f"映射链失败：{exc}"]}, as_json=as_json, human_tag="watch")
        return 3
    cache_root = sws.resolve_watch_cache_root(args.cache_root)
    sink_note = "off（--no-sink）" if args.no_sink else str(cache_root / f"watch_{os.getpid()}.jsonl")
    print(
        f"[watch] opt-in 轮询档启动：interval={args.interval:.0f}s debounce={args.debounce:.0f}s "
        f"rounds={args.rounds} scope={args.scope} cache_root={cache_root} sink={sink_note}"
    )

    def collect():
        if args.changed_src:
            changed = sorted({str(p).replace("\\", "/") for p in args.changed_src})
        else:
            changed = devtest._changed_src(args.staged, args.base)
        head = devtest._head()
        tests, _not_in_map, _per_file = devtest._get_selection(map_path, args.scope, changed)
        map_digest = dss.map_fingerprint_digest(bim.default_fingerprint_path(map_path))
        return changed, head, map_digest, tests

    stop = threading.Event()

    def _on_stop(signum: int, _frame: object) -> None:
        stop.set()  # 观测面 best-effort：优雅置位，分片 sleep 内退出（#105 不抛栈）

    for sig in ("SIGINT", "SIGBREAK"):
        handler = getattr(signal, sig, None)
        if handler is not None:
            with contextlib.suppress(ValueError, OSError):
                signal.signal(handler, _on_stop)  # 仅主线程合法；非主线程静默跳过

    cfg = sws.WatchConfig(
        interval_s=args.interval,
        debounce_s=args.debounce,
        rounds=args.rounds,
        workers=args.workers,
        timeout_s=args.timeout_s,
        min_trigger_interval_s=args.min_trigger_interval_s,
        cache_root=cache_root,
        sink_enabled=not args.no_sink,
    )
    for decision in sws.watch_loop(
        collect,
        cache_root=cache_root,
        config=cfg,
        should_stop=stop.is_set,
        census_fn=dss.default_local_census,
        owner_pid=os.getpid(),
        content_digest_fn=lambda changed: sws.content_digest_of(changed, root=_REPO),
    ):
        if as_json:
            print(json.dumps(decision, ensure_ascii=False, default=str))
        else:
            trig = decision.get("trigger")
            extra = ""
            if isinstance(trig, dict):
                extra = (
                    f" child={trig.get('child_pid')} tests={trig.get('tests_count')} "
                    f"log={trig.get('log_path')}"
                )
            print(
                f"[watch] tick={decision.get('tick')} decision={decision.get('decision')} "
                f"state={decision.get('state')} "
                f"fast_path={decision.get('fast_path')} "
                f"fp={str(decision.get('fingerprint'))[:12]} "
                f"sink_ok={decision.get('sink_write_ok')}{extra}",
                flush=True,
            )
    print("[watch] 优雅停止（信号/轮数耗尽）——exit 0")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args, extra = parser.parse_known_args(argv)
    if extra and extra[0] == "--":
        extra = extra[1:]
    if args.workers > dss.WORKERS_CAP:
        print(f"[speculative] --workers {args.workers} 超投机档硬顶 {dss.WORKERS_CAP}（资源上限红线）→ 收敛")
        args.workers = dss.WORKERS_CAP
    if args.workers < 1:
        parser.error("--workers 必须 >= 1")
    if args.child and args.status:
        parser.error("--child 与 --status 互斥")
    if args.watch and (args.status or args.child):
        parser.error("--watch 与 --status/--child 互斥（watch 是独立第四模式）")
    if args.watch and args.rounds < 0:
        parser.error("--rounds 必须 >= 0（0=无限）")
    if args.status:
        return _run_status(args, args.json)
    if args.child:
        return _run_child(args, extra, args.json)
    if args.watch:
        return _run_watch(args, args.json)
    if extra:
        parser.error(f"未识别参数：{extra}（透传仅 --child 模式支持）")
    return _run_trigger(args, args.json)


if __name__ == "__main__":
    sys.exit(main())
