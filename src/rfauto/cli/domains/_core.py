"""CLI 单点共享态：app 对象/console/_emit 等 helper（回调注册在此，先于全部域模块导入）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="rfauto",
    help=(
        "HFSS ↔ ADS 自动化仿真调优框架\n\n"
        "新手路径（五步零 license 跑通，详见 docs/tutorials/getting-started.md）：\n"
        "  1. rfauto doctor          环境体检（--env 环境变量 / --extras 可选依赖组）\n"
        "  2. rfauto syn mline       闭式综合（参数→几何）\n"
        "  3. rfauto calc …          计算器交叉核对\n"
        "  4. rfauto run … --adapter fake   零 license 冒烟运行\n"
        "  5. rfauto runs health     运行健康体检"
    ),
    no_args_is_help=True,
)
def _force_utf8_stdio() -> None:
    """Windows GBK 控制台下 rich 打印 '✓' 等字符会 UnicodeEncodeError 崩溃，
    统一将 stdio 重配为 UTF-8（防再犯：P0 验收审计发现，2026-08-28）。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # 已重定向的管道可能不支持，保持原样
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8")


_force_utf8_stdio()


def _setup_logging_from_env() -> None:
    """按 RFAUTO_LOG_LEVEL 启用 loguru（孤岛接线，缺口 8 顺手项）。

    未设置环境变量时保持静默（零开销，不抢 typer/rich 的输出）；
    设置为 debug/info/warning/error 之一才初始化 sink。
    在 app 回调中执行（每次命令运行时检查，而非模块导入时一次）。
    """
    import os

    level = os.environ.get("RFAUTO_LOG_LEVEL", "").strip().upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        return
    from rfauto.infra.logging import setup_logging

    setup_logging(level=level)


@app.callback()
def _main_callback() -> None:
    """全局入口：每次命令执行前应用环境配置。"""
    _setup_logging_from_env()

console = Console()


# ═══ WP3.3 CLI 半边 + 全仓 scattered 薄壳（cli-mcp-api-shell-bundle）═══════════
# 全部零逻辑转发 service（规则 4）；数值只在确定性内核（铁律 7）。
# 与 mcp_server.py 同源同名 service 函数，JSON 进出。


def _attach_error_hints(envelope: dict) -> None:
    """失败信封 best-effort 注入 ``hints`` 键（W1-A 单元13 主挂点；#105 纪律）。

    仅 ``_emit`` 的 --json 失败分支调用：惰性导入 error_hints_service +
    try/except 全包裹——hint 生成失败绝不遮蔽原错误（宁无 hint 不阻塞；
    观测面不得成为业务主路径故障点）。原 errors 文本逐字节不动，只追加
    ``hints`` 键（命中提示列表，未命中=空表如实回显，键恒存在）。
    成功路径零变化（本函数不被调用，热路径零开销）。
    """
    try:
        from rfauto.service.error_hints_service import hint_for_message

        text = "\n".join(str(e) for e in (envelope.get("errors") or []))
        envelope["hints"] = hint_for_message(text).get("hits") or []
    except Exception:  # #105：best-effort 观测面，吞一切异常
        envelope.setdefault("hints", [])


def _print_error_hints_text(errs: list) -> None:
    """A10 错误三段式（红字面）②③段：建议 next command → 文档锚（W2-G 残差）。

    ``--json`` 失败分支 W1 已挂 hints（``_attach_error_hints``）；本函数补
    human 分支（无 --json 的红字输出）：✗ 原因（既有第①段）之后逐 hit 打
    "→ 建议: …（refs 坑号/docs 指针）"。best-effort（#105）：hint 生成失败
    静默返回，绝不遮蔽原错误；未命中零输出（不编造提示，同映射层约束）。
    """
    try:
        from rfauto.service.error_hints_service import hint_for_message

        text = "\n".join(str(e) for e in (errs or []))
        hits = hint_for_message(text).get("hits") or []
        for hit in hits:
            hint = str(hit.get("hint") or "").strip()
            if not hint:
                continue
            refs = str(hit.get("refs") or "").strip()
            line = f"  [cyan]→ 建议: {hint}[/cyan]"
            if refs:
                line += f" [dim]（{refs}）[/dim]"
            console.print(line)
    except Exception:  # #105：观测面失败不阻塞错误输出主路径
        return


def _emit(result: dict, fail_msg: str, *, json_output: bool = True) -> None:
    """薄壳共用出口：ok=False → 失败信封（--json）或红字 errors/error + 退出码 1；否则 JSON 直出。"""
    if not result.get("ok"):
        errs = result.get("errors") or ([result["error"]] if result.get("error") else [])
        if json_output:
            # 失败信封与成功路径同构：result 里已有的 errors/error 原样带上；
            # 两者都缺时 fail_msg 兜底入 errors 一元列表（--json 下失败路径不许非 JSON）
            envelope = dict(result)
            if not envelope.get("errors") and "error" not in envelope:
                envelope["errors"] = [fail_msg]
            _attach_error_hints(envelope)
            console.print_json(json.dumps(envelope, indent=2, ensure_ascii=False, default=str))
        else:
            console.print(f"[red]✗ {fail_msg}[/red]")
            for err in errs:
                console.print(f"  [red]- {err}[/red]")
            _print_error_hints_text(errs)
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def _load_json_file(path: str, what: str) -> dict:
    """读 JSON 对象文件（payload 型命令共用；不存在/非对象 → 退出码 2）。"""
    p = Path(path)
    if not p.exists():
        console.print(f"[red]✗ {what}不存在: {p}[/red]")
        raise typer.Exit(code=2)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        console.print(f"[red]✗ {what}不可读: {exc}[/red]")
        raise typer.Exit(code=2) from None
    if not isinstance(data, dict):
        console.print(f"[red]✗ {what}必须是 JSON 对象[/red]")
        raise typer.Exit(code=2)
    return data


def _kv_floats(items: list[str] | None, flag: str) -> dict[str, float]:
    """--flag 名=值（可多次）→ {名: float}。"""
    out: dict[str, float] = {}
    for item in items or []:
        if "=" not in item:
            console.print(f"[red]✗ {flag} 格式应为 参数名=值：{item}[/red]")
            raise typer.Exit(code=2)
        name, _, val = item.partition("=")
        try:
            out[name.strip()] = float(val)
        except ValueError:
            console.print(f"[red]✗ {flag} 值不是数字：{item}[/red]")
            raise typer.Exit(code=2) from None
    return out


# ─── SN-19（W6-A，2026-10-06）：--watch 泛化（jobs watch / runs watch）───────

_TERMINAL_STATES = ("done", "failed", "cancelled", "solve_failed")


def _watch_poll(
    poll_id: str,
    *,
    interval_s: float,
    timeout_s: float,
    json_output: bool,
    label: str,
) -> None:
    """轮询打点直到终态/超时（SN-19 CLI 轮询面；与 MCP wait_job 同源数据）。

    每 tick 经 ``api.poll_job`` 查一次（进程内注册表 → runs/<id>/meta.json
    磁盘回落链原样复用），打一行进度点（--json 下为 JSONL 逐行信封，管道
    友好）；终态或超时即停。退出码：done=0；failed/cancelled/solve_failed/
    超时=1。纯轮询零写入（观测面，#105 语义）。
    """
    import time

    from rfauto.service.api import poll_job

    deadline = time.monotonic() + max(0.0, float(timeout_s))
    ticks = 0
    last: dict = {}
    while True:
        last = poll_job(poll_id)
        ticks += 1
        state = str(last.get("state", "unknown"))
        pct = last.get("progress_pct")
        stage = last.get("stage") or ""
        if json_output:
            console.print_json(json.dumps(
                {"tick": ticks, "job_id": poll_id, "state": state,
                 "progress_pct": pct, "stage": stage},
                ensure_ascii=False, default=str))
        else:
            pct_s = f"{pct:.0f}%" if isinstance(pct, (int, float)) else "?"
            console.print(f"  [{ticks}] {label} {poll_id}  state={state}"
                          f"  progress={pct_s}{'  stage=' + stage if stage else ''}",
                          markup=False)
        if state in _TERMINAL_STATES:
            break
        if time.monotonic() >= deadline:
            console.print(
                f"[red]✗ watch 超时（{timeout_s}s，末态 state={state}）[/red]")
            raise typer.Exit(code=1)
        time.sleep(max(0.1, float(interval_s)))

    if str(last.get("state")) != "done":
        raise typer.Exit(code=1)
    if not json_output:
        console.print(f"[green]✓ 终态 done：{poll_id}[/green]")
