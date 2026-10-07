"""solvers 子应用 + simci/inbox/chat 顶层命令（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── solvers (方向 6g/6h: 求解器可视化+管理) ────────────────────────────────────────────────

solvers_app = typer.Typer(help="求解器管理（方向 6g/6h）")
app.add_typer(solvers_app, name="solvers")


@solvers_app.command("list")
def solvers_list(
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """列出已注册求解器及其可视化能力（方向 6g/6h）。"""
    from rfauto.service.r3_services import list_registered_solvers
    result = list_registered_solvers()
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "查询失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 查询失败[/red]")
        raise typer.Exit(code=1)

    table = Table(title="已注册求解器")
    table.add_column("名称", style="cyan")
    table.add_column("类")
    table.add_column("可用")
    table.add_column("可视化")
    for s in result["solvers"]:
        avail = "[green]✓[/green]" if s["available"] else "[red]✗[/red]"
        table.add_row(s["type"], s["class"], avail, str(s["n_visualizations"]))
    console.print(table)


@solvers_app.command("viz")
def solvers_viz(
    solver: str = typer.Option(None, "--solver", "-s", help="指定求解器"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """列出求解器可视化产物声明（方向 6g 产物视图协议）。"""
    from rfauto.service.r3_services import list_solver_visualizations
    result = list_solver_visualizations(solver)
    if json_output:
        # VI-5 W6-B：失败信封（成功本即 JSON 直出，两形态同形）
        _emit(result, "查询失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 查询失败[/red]")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(result, indent=2, ensure_ascii=False))


@solvers_app.command("add")
def solvers_add(
    name: str = typer.Argument(..., help="求解器名称"),
    type_: str = typer.Option(..., "--type", "-t", help="求解器类型 (openems/hfss/fake/palace/...)"),
    exe: str = typer.Option(None, "--exe", help="可执文件路径"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """添加求解器到 configs/solvers.yaml（方向 6h）。"""
    from rfauto.service.r3_services import add_solver_to_config
    result = add_solver_to_config(name, type_, exe_path=exe)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "添加失败", json_output=True)
        return
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('errors', ['失败'])}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ 求解器 '{name}' 已添加[/green]")


@solvers_app.command("qucsator-mline")
def solvers_qucsator_mline(
    w_mm: str = typer.Option(None, "--w-mm", help="线宽 mm（缺省 1.113 openEMS 锚名义）"),
    line_len_mm: str = typer.Option(None, "--l-mm", help="线长 mm（缺省 40）"),
    freqs: str = typer.Option("2.25,2.5,2.75", "--freqs-ghz", help="逗号分隔频点 GHz"),
    work_dir: str = typer.Option(None, "--work-dir", help="产物目录（缺省临时目录）"),
    tol_rel: float = typer.Option(0.05, "--tol-rel", help="三方 β 互差容差"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """qucsatorRF mline 名义点三方 β 对照（qucsator/openEMS 金锚/HJ；DP-14 N7）。"""
    from rfauto.service.qucsator_service import solve_mline_three_way

    freqs_ghz = [float(x) for x in freqs.split(",") if x.strip()]
    result = solve_mline_three_way(
        w_mm=float(w_mm) if w_mm else None,
        line_len_mm=float(line_len_mm) if line_len_mm else None,
        freqs_ghz=freqs_ghz,
        work_dir=work_dir,
        tol_rel=tol_rel,
    )
    if json_output:
        # VI-5 W6-B：--json 信封（threeway 全载荷在 result 内）
        _emit(result, "三方对照失败", json_output=True)
        return
    if not result.get("ok"):
        console.print(f"[red]✗ {result.get('errors', ['失败'])}[/red]")
        raise typer.Exit(code=1)
    verdict = (result.get("threeway") or {}).get("verdict") or {}
    color = "green" if verdict.get("passed") else "red"
    console.print(f"[{color}]● qucsatorRF mline 三方对照[/] "
                  f"max互差={verdict.get('max_pairwise_rel'):.4f} "
                  f"culprit={verdict.get('culprit_pair')}（tol_rel={tol_rel}）")
    console.print_json(json.dumps(result["threeway"], indent=2, ensure_ascii=False))


# ─── simci（阶段 7.5：仿真 CI 夜间回归）─────────────────────────────────────

@app.command("simci")
def simci_cmd(
    recipes_dir: str = typer.Argument("recipes", help="配方目录"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="回归通道（fake 零成本）"),
    tolerance: float = typer.Option(1.0, "--tolerance", help="指标劣化容差 dB"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """全配方夜间回归：validate+run → 对照 runs 索引历史基线 → diff 报告。"""
    from rfauto.service.sim_ci_service import nightly_regression

    if not json_output:
        console.print(f"[cyan]仿真 CI 回归: {recipes_dir}（{adapter} 通道）[/cyan]")
    result = nightly_regression(recipes_dir, adapter=adapter,
                                tolerance_db=tolerance)
    if json_output:
        # VI-5 W6-B：--json 信封（成功+失败同构）；缺省 rich 路径逐字节不动
        _emit(result, "回归失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 回归失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    color = "green" if result["n_regressions"] == 0 else "red"
    console.print(f"[{color}]● 回归完成：{result['n_done']}/{result['n_recipes']} 配方，"
                  f"{result['n_regressions']} 个劣化[/{color}]")
    console.print(f"  run_id: {result['run_id']}")
    for reg in result.get("regressions", []):
        console.print(f"  [red]劣化 {reg['recipe']}: {reg['metric']} "
                      f"{reg['baseline']}→{reg['current']}（{reg['delta_db']:+.2f}dB）[/red]")
    console.print(f"  报告: {result['run_dir']}\\sim_ci_report.md")


# ─── simci-pin-baseline（XD-5：golden 基线钉定 pin/compare/drift 三动作）────
# 单叶不子应用化（spec §8.4：保 `rfauto simci` 现签名零破坏）；JSON 进出
# 走 service/sim_ci_service golden 面；退出码语义：
#   0 = 成功（pin 完成 / compare 匹配 / drift 未超限）；
#   1 = 判定不通过（compare drift / drift exceeded）；
#   2 = 程序性状态错误（golden 缺失且该动作必需 / runs 索引库缺失 /
#       golden 已存在未给 --update）。

@app.command("simci-pin-baseline")
def simci_pin_baseline_cmd(
    action: str = typer.Argument(
        ..., help="动作：pin 写入金样例 / compare 对照金样例 / drift 量化漂移"),
    adapter: str = typer.Option("fake", "--adapter", "-a",
                                help="回归通道适配器（runs 索引等值过滤）"),
    channel: str = typer.Option(None, "--channel",
                                help="通道名（缺省=adapter）"),
    baseline: str = typer.Option(None, "--baseline",
                                 help="golden 基线文件路径"
                                      "（缺省 knowledge/simci_baseline.yaml）"),
    db: str = typer.Option(None, "--db",
                           help="runs 索引库路径（缺省注册表缺省库）"),
    update: bool = typer.Option(False, "--update",
                                help="pin 时允许覆盖既有金样例"
                                     "（信封携带旧到新 digest 审计串）"),
    tolerance: float = typer.Option(0.0, "--tolerance",
                                    help="drift 判超限的指标绝对漂移容差"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """sim_ci golden 基线三动作：pin 钉定 / compare 对照 / drift 漂移量化。

    示例：rfauto simci-pin-baseline pin --adapter fake --json
    退出码：0 成功；1 判定不通过（漂移/超限）；2 状态错误
    （golden 缺失、索引库缺失、已存在未给 --update）。
    """
    from rfauto.service import sim_ci_service as scs

    acts = ("pin", "compare", "drift")
    if action not in acts:
        console.print(f"[red]✗ 未知动作: {action}（可选 {' / '.join(acts)}）[/red]")
        raise typer.Exit(code=2)

    common = {"adapter": adapter, "channel": channel, "db_path": db,
              "baseline_path": baseline}
    if action == "pin":
        result = scs.pin_baseline(update=update, **common)
    elif action == "compare":
        result = scs.compare_baseline(**common)
    else:
        result = scs.baseline_drift(tolerance=tolerance, **common)

    if not result.get("ok"):
        if json_output:
            console.print_json(json.dumps(result, indent=2,
                                          ensure_ascii=False, default=str))
        else:
            console.print("[red]✗ simci-pin-baseline 失败[/red]")
            for err in result.get("errors") or []:
                console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=2)

    outcome = str(result.get("outcome") or result.get("action") or "")
    if json_output:
        console.print_json(json.dumps(result, indent=2,
                                      ensure_ascii=False, default=str))
    elif action == "pin":
        console.print(f"[green]✓ golden 已钉定[/green]  "
                      f"action={result.get('action')}  "
                      f"digest={str(result.get('metrics_digest'))[:12]}…  "
                      f"models={result.get('n_models')}  "
                      f"路径 {result.get('baseline_path')}")
        if result.get("previous_metrics_digest"):
            console.print(f"  旧 digest: "
                          f"{str(result.get('previous_metrics_digest'))[:12]}…"
                          f"（update 审计）")
        console.print(f"  [dim]{result.get('update_audit')}[/dim]")
        console.print("  [dim]提交归调用方工作流：commit message 模板见上方审计串"
                      "（服务层零 git 写面）[/dim]")
    else:
        color = {"match": "green", "within": "green",
                 "drift": "red", "exceeded": "red"}.get(outcome, "yellow")
        console.print(f"[{color}]● {action} outcome={outcome}[/]  "
                      f"digest_match={result.get('digest_match')}  "
                      f"max_abs_delta={result.get('max_abs_delta')}  "
                      f"n_exceeded={result.get('n_exceeded', '-')}  "
                      f"tolerance={result.get('tolerance', '-')}")
        if result.get("reason"):
            console.print(f"  [yellow]{result['reason']}[/yellow]")
        for d in (result.get("exceeded") or result.get("deltas") or [])[:10]:
            console.print(f"  - {d.get('model')}.{d.get('metric')}: "
                          f"{d.get('golden')} -> {d.get('current')}"
                          f"（delta {d.get('delta')}）")

    if outcome in ("drift", "exceeded"):
        raise typer.Exit(code=1)
    if outcome in ("missing_golden", "missing_runs"):
        # 双态钉：无 golden 环境的 compare/drift 是合法"未钉定"态——
        # 如实报 outcome 后以状态错误码区分于判定不通过。
        raise typer.Exit(code=2)


# ─── inbox (方向 6i: 审批收件箱) ───────────────────────────────────────────────────

@app.command("inbox")
def inbox_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="显示条数"),
    approve: str = typer.Option(None, "--approve", "-a", help="批准指定 token 的提案"),
    recipe: str = typer.Option(None, "--recipe", "-r", help="配方路径（approve 时必填）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """审批收件箱：查看/批准待确认的 Agent 提案（方向 6i）。"""
    from rfauto.service.r3_services import approve_proposal, list_pending_approvals

    if approve:
        if not recipe:
            if json_output:
                # VI-5 W6-B：入参缺失也信封（--json 下失败路径不许非 JSON）
                _emit({"ok": False, "errors": ["--approve 需要 --recipe 指定配方路径"]},
                      "批准失败", json_output=True)
            console.print("[red]✗ --approve 需要 --recipe 指定配方路径[/red]")
            raise typer.Exit(code=1)
        result = approve_proposal(approve, recipe)
        if json_output:
            _emit(result, "批准失败", json_output=True)
            return
        if result.get("ok"):
            console.print(f"[green]✓ 提案已批准执行[/green]  run_id: {result.get('run_id', '?')}")
        else:
            console.print(f"[red]✗ 批准失败: {result.get('errors', [])}[/red]")
            raise typer.Exit(code=1)
        return

    result = list_pending_approvals(limit=limit)
    if json_output:
        # VI-5 W6-B：--json 信封（空箱如实 pending=[]，service ok_envelope 直出）
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        return
    if not result["pending"]:
        console.print("[green]无待审批项[/green]")
        return

    table = Table(title=f"审批收件箱 ({result['total']} 待处理)")
    table.add_column("时间", style="dim")
    table.add_column("Token", style="cyan")
    table.add_column("配方")
    table.add_column("参数")
    table.add_column("操作")

    for e in result["pending"]:
        ts = str(e.get("timestamp", "?"))[:19]
        token = e.get("token_hash", "?")[:12] + "..."
        recipe_name = Path(e.get("recipe", "?")).name
        params = json.dumps(e.get("params", {}), ensure_ascii=False)[:40]
        table.add_row(ts, token, recipe_name, params, f"inbox --approve {e.get('token_hash','')[:8]} --recipe {e.get('recipe','')}")

    console.print(table)


# ─── chat (方向 6j: LLM 对话窗) ─────────────────────────────────────────────────────

@app.command("chat")
def chat_cmd(
    message: str = typer.Argument(..., help="消息内容"),
    channel: str = typer.Option("service", "--channel", "-c",
                                help="通道选择（6j 双通道）: service（内嵌，默认）| mcp（MCP 客户端）"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """LLM 对话窗（方向 6j 双通道可选）：内嵌 service 直调 或 MCP 客户端。

    两路同源（同一批 service 函数）、同审计（audit.jsonl）。默认内嵌通道；
    习惯 Claude/Codex 的用户或外部编排可选 mcp 通道。
    """
    if channel == "mcp":
        from rfauto.cli.mcp_chat import MCPAgentChat
        chat = MCPAgentChat()
    elif channel == "service":
        from rfauto.service.r3_services import AgentChat
        chat = AgentChat()
    else:
        console.print(f"[red]未知通道: {channel}（可选 service | mcp）[/red]")
        raise typer.Exit(code=1)
    result = chat.chat(message)
    if json_output:
        # VI-5 W6-B：--json 信封（text/action 原样透传，channel 并入）
        console.print_json(json.dumps(
            {"ok": True, "text": result.get("text", ""),
             "action": result.get("action", "?"), "channel": channel},
            ensure_ascii=False, default=str))
        return
    console.print(result["text"])
    if result.get("action") != "help":
        console.print(f"[dim]动作: {result.get('action', '?')}（通道: {channel}）[/dim]")
