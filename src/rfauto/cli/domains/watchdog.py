"""watchdog 子应用（seat 粒度三证判活 CLI 出口；aurora_p F2 接线席，2026-11-02）。

叶 watch（单叶双形态——一次性视图是缺省动作，常驻循环显式旗标开启）：
service/watchdog_service（T-O12，aurora_o）的 CLI 出口——

- 缺省（无 ``--watch``）：``seat_liveness_view`` 单次采样即返回——零后台
  线程零文件写（#105 观测面；缺省行为逐字节同 service 直调，service 参数
  缺省值原样生效）；
- ``--watch``：``watch_loop`` 生成器逐轮消费（每轮一行 jsonl 追加 sink，
  白名单单根 ``runs/watchdog/`` 越界急切显式报错）；``--duration`` 给定按
  ceil(duration/interval) 折算轮数，缺省长驻至 Ctrl+C 优雅停（轮数常量
  上限，非线程——T-O12 生成器非线程家法零变化）；轮间隔下限复用 service
  家族既有常量 ``speculative_watch_service.MIN_INTERVAL_S``（单源，CLI
  不另立下限数）。

target 三形态透传 service（判定表纯函数单源零复制）：

- ``--pid N``：pid 直查（存活证=pid 存活）；
- ``--fingerprint TEXT``：#261 命令行指纹 census 证（可配 ``--process-name``
  收窄进程域——Mapping 形态）；
- 全缺省：None 纯产物证视图（批量 run 目录行复用语义）。

零数值逻辑转发 service（规则 4）；带 ``--json``（信封契约：成功+失败同构；
unknown 恒 ok=True 如实不凑判——#122；sink 写失败降级如实标注不阻塞——
#105）。
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console
from rfauto.service.envelope import error_envelope, ok_envelope

watchdog_app = typer.Typer(
    help="seat 粒度三证判活（watchdog 方法论 CLI 出口；service/"
         "watchdog_service 薄壳）：watch=单席判活一次性视图（缺省动作）或 "
         "--watch 常驻循环（显式开启；jsonl 落白名单 runs/watchdog/，"
         "Ctrl+C 优雅停）")
app.add_typer(watchdog_app, name="watchdog")

#: state → 人读 rich 样式（unknown 不凑判同 stalled 黄色警示）。
_STATE_STYLE = {
    "alive": "green",
    "stalled": "yellow",
    "dead": "red",
    "unknown": "yellow",
}
#: --watch 无 --duration 时的轮数上限（生成器非线程——range 惰性，实际
#: 由 Ctrl+C 终止；取值足够大以等效长驻，非语义承诺）。
_WATCH_ROUNDS_UNBOUNDED = 10 ** 9


def _emit_view_human(result: dict) -> None:
    """一次性视图人读分支（动态段一律 escape——campaign 叶 markup 纪律）。"""
    if not result.get("ok"):
        console.print("[red]✗ 判活视图失败[/red]")
        for err in result.get("errors") or []:
            console.print(f"  [red]- {escape(str(err))}[/red]")
        raise typer.Exit(code=1)
    state = str(result.get("state"))
    style = _STATE_STYLE.get(state, "white")
    console.print(
        f"[bold]watchdog 判活[/bold]  state=[{style}]{escape(state)}[/{style}]"
        f"（三证判定表单源 service/watchdog_service）")
    ev = result.get("evidence") or {}
    console.print(
        f"  进程存活={ev.get('process_alive')}  CPU 增长={ev.get('cpu_growing')}"
        f"  产物新鲜={ev.get('artifact_fresh')}")
    reason = result.get("reason")
    if reason:
        console.print(f"  reason: {escape(str(reason))}")


@watchdog_app.command("watch")
def watchdog_watch_cmd(
    pid: int = typer.Option(
        None, "--pid",
        help="target 形态一：pid 直查（存活证=pid 存活；与 --fingerprint "
             "恰给一）"),
    fingerprint: str = typer.Option(
        None, "--fingerprint",
        help="target 形态二：#261 命令行指纹正则（census 证全进程域；"
             "与 --pid 恰给一；可配 --process-name 收窄）"),
    process_name: str = typer.Option(
        None, "--process-name",
        help="（仅 --fingerprint 形态）收窄 census 进程域的进程名"),
    artifact_glob: list[str] = typer.Option(  # noqa: B008
        None, "--artifact-glob",
        help="产物新鲜度证 glob（可多次；缺省未配置=本证缺席 unknown "
             "不凑判）"),
    stall_window_s: float = typer.Option(
        900.0, "--stall-window-s",
        help="产物新鲜度窗（s）：mtime 距今超过即停滞（缺省=service 既有"
             " DEFAULT_STALL_WINDOW_S）"),
    watch: bool = typer.Option(
        False, "--watch",
        help="常驻循环形态（缺省关：无本旗标=单次采样即返回，零后台线程"
             "零文件写）"),
    interval: float = typer.Option(
        30.0, "--interval",
        help="（--watch）轮间隔秒（下限=service 家族 MIN_INTERVAL_S 单源，"
             "更小值被抬到下限）"),
    duration: float = typer.Option(
        None, "--duration",
        help="（--watch）可选总时长秒（按 ceil(duration/interval) 折算轮数；"
             "缺省长驻至 Ctrl+C 优雅停）"),
    sink: str = typer.Option(
        None, "--sink",
        help="（--watch）jsonl sink 路径（必须在白名单单根 runs/watchdog/ "
             "内，越界启动即报错；缺省 runs/watchdog/cli/watch.jsonl）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """单席三证判活：pid / census 指纹 / 纯产物三形态 → alive·stalled·dead·
    unknown 信封（unknown=证据缺失如实不凑判）。

    一次性视图（缺省）：rfauto watchdog watch --pid 1234
    常驻循环（显式开启，jsonl 落白名单）：
    rfauto watchdog watch --watch --interval 120 --fingerprint "_rfauto_runner"

    判定=service/watchdog_service 三证判定表（进程存活/CPU 增长/产物 mtime
    新鲜；任一正证 alive、全负证 stalled、两证全缺 unknown 不凑判）。本叶
    零数值逻辑（薄壳转发）；--json 信封成功+失败同构；Ctrl+C 优雅停并出
    已收轮数汇总信封（退出码 0）。
    """
    from rfauto.service import watchdog_service as wd
    from rfauto.service.speculative_watch_service import MIN_INTERVAL_S

    # ── target 形态恰一（CLI 面 usage 错误；service 判定表零复制） ──
    if pid is not None and fingerprint:
        _emit_usage_error(
            "--pid 与 --fingerprint 恰给一（互斥；全缺省=纯产物证视图）",
            json_output=json_output)
        return
    if process_name and not fingerprint:
        _emit_usage_error(
            "--process-name 仅在 --fingerprint 形态可用",
            json_output=json_output)
        return
    if fingerprint:
        if process_name:
            target: int | str | dict[str, object] | None = {
                "process_name": process_name, "fingerprint": fingerprint}
        else:
            target = fingerprint
    elif pid is not None:
        target = pid
    else:
        target = None

    view_kwargs: dict[str, object] = {
        "artifact_globs": tuple(artifact_glob or ()),
        "stall_window_s": float(stall_window_s),
    }

    # ── 缺省形态：一次性视图（零后台线程零文件写，逐字节同 service 直调） ──
    if not watch:
        result = wd.seat_liveness_view(target, **view_kwargs)
        if json_output:
            _emit(result, "判活视图失败", json_output=True)
            return
        _emit_view_human(result)
        return

    # ── 常驻形态（显式 --watch）：watch_loop 生成器逐轮消费 ──
    if duration is not None and float(duration) < 0:
        _emit_usage_error("--duration 须为非负秒数", json_output=json_output)
        return
    interval_s = max(float(interval), float(MIN_INTERVAL_S))
    # --duration 给定按 ceil 折算轮数；缺省=长驻上限常量（Ctrl+C 实际终止）
    rounds = (
        max(1, math.ceil(float(duration) / interval_s))
        if duration is not None else _WATCH_ROUNDS_UNBOUNDED)
    if sink:
        sink_path = Path(os.path.abspath(str(sink)))
    else:
        sink_path = wd.repo_root() / wd.WATCHDOG_ROOT_REL / "cli" / "watch.jsonl"

    try:
        gen = wd.watch_loop(
            target, sink=sink_path, rounds=rounds, interval_s=interval_s,
            **view_kwargs)
    except ValueError as exc:
        # 白名单越界在 watch_loop 调用期急切抛出——转失败信封（--json 下
        # 失败路径也是信封，禁裸文本）
        result = error_envelope([f"watch 循环无法启动: {exc}"])
        if json_output:
            _emit(result, "watch 循环无法启动", json_output=True)
            return
        console.print("[red]✗ watch 循环无法启动[/red]")
        for err in result.get("errors") or []:
            console.print(f"  [red]- {escape(str(err))}[/red]")
        raise typer.Exit(code=1) from None

    counts = {"alive": 0, "stalled": 0, "dead": 0, "unknown": 0}
    rounds_done = 0
    sink_write_ok = True
    interrupted = False
    try:
        for view in gen:
            rounds_done += 1
            sink_write_ok = sink_write_ok and bool(view.get("sink_write_ok"))
            state = str(view.get("state"))
            if state in counts:
                counts[state] += 1
            if json_output:
                # 逐轮 JSONL 行（管道友好，_watch_poll 同款口径）
                console.print_json(json.dumps(
                    view, ensure_ascii=False, default=str))
            else:
                vstyle = _STATE_STYLE.get(state, "white")
                console.print(
                    f"  轮 {view.get('watch_round')}: "
                    f"state=[{vstyle}]{escape(state)}[/{vstyle}]"
                    f"  sink_write_ok={view.get('sink_write_ok')}")
    except KeyboardInterrupt:
        # Ctrl+C 优雅停：已收轮数如实带出（观测面 #105——采样中断不是故障）
        interrupted = True

    summary = ok_envelope(
        mode="watch",
        rounds_done=rounds_done,
        rounds_planned=rounds,
        interrupted=interrupted,
        interval_s=interval_s,
        duration_s=None if duration is None else float(duration),
        sink=str(sink_path),
        sink_write_ok=sink_write_ok,
        state_counts=counts,
    )
    if json_output:
        _emit(summary, "watch 循环失败", json_output=True)
        return
    tail = "（Ctrl+C 优雅停）" if interrupted else ""
    console.print(
        f"[green]✓ watch 结束[/green]  轮数 {rounds_done}{tail}  "
        f"state 计数 {escape(str(counts))}  sink {escape(str(sink_path))}"
        f"（sink_write_ok={sink_write_ok}）")
