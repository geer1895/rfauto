"""goal 子应用——用户 Goal 工作模式四叶（DS-3，宏图 v3.2 §十）。

零逻辑转发 service/goal_domain（规则 4 薄壳；持久目标/续轮 driver/
campaign 适配层全在 service，铁律 7 零数值面——本模块不产生任何物理
数字，只编排）：
  rfauto goal set <objective> [--done-when JSON] [--campaign-plan PATH]
  rfauto goal status <goal_id>
  rfauto goal advance <goal_id> [--evidence-file PATH]
  rfauto goal list

`/goal` 人工命令**零模型轮**：判据评估与状态机全部确定性（service 层
spec 词表/注入函数），CLI 只透传证据文件与判据 spec，不调任何模型。

注册=域内自注册（dag/env_reliability 同款：模块级 add_typer，main.py
只 re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
`goal` 域（#df6① 冲突检查 2026-10-05：全 CLI 树零撞名）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

goal_app = typer.Typer(help="持久目标（用户 Goal 工作模式：跨重启存续+自动续轮，DS-3）")
app.add_typer(goal_app, name="goal")


# ─── 服务面（JSON 进出，CLI/MCP 同源薄壳；信封走构造器）───────────────────────

def goal_set(
    objective: str,
    done_when: str | None = None,
    campaign_plan: str | None = None,
    goal_id: str | None = None,
    max_rounds: int | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    """立持久目标（done-when 为 JSON 判据 spec 字符串，service 校验词表）。"""
    from rfauto.service.envelope import error_envelope
    from rfauto.service.goal_domain import set_goal

    spec: dict[str, Any] | None = None
    if done_when is not None and done_when.strip():
        try:
            spec = json.loads(done_when)
        except ValueError as exc:
            return error_envelope([f"--done-when JSON 不可解析: {exc}"])
        if not isinstance(spec, dict):
            return error_envelope(["--done-when 必须是 JSON 对象判据 spec"])
    return set_goal(
        objective, spec, campaign_plan=campaign_plan, goal_id=goal_id,
        max_rounds=max_rounds, root=root)


def goal_status(goal_id: str, root: str | None = None) -> dict[str, Any]:
    """读持久目标（跨进程存续查询口）。"""
    from rfauto.service.goal_domain import get_goal

    return get_goal(goal_id, root)


def goal_advance(
    goal_id: str,
    evidence_file: str | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    """推进一轮（CLI 面走声明式 spec 判据；证据=--evidence-file JSON 或
    goal 声明的 campaign_plan 适配层——两者皆缺则空证据，如实 blocked）。"""
    from rfauto.service.envelope import error_envelope
    from rfauto.service.goal_domain import advance_goal

    evidence_fn = None
    if evidence_file is not None and evidence_file.strip():
        try:
            raw = json.loads(Path(evidence_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return error_envelope([f"--evidence-file 不可读: {exc}"])
        if not isinstance(raw, dict):
            return error_envelope(["--evidence-file 必须是 JSON 对象证据"])

        def evidence_fn(_goal: dict[str, Any], _raw=raw) -> dict[str, Any]:
            return _raw  # CLI 直传证据（确定性，service 契约同形）

    return advance_goal(goal_id, root=root, evidence_fn=evidence_fn)


def goal_list(root: str | None = None) -> dict[str, Any]:
    """清点 goals 目录（只读摘要）。"""
    from rfauto.service.goal_domain import list_goals

    return list_goals(root)


# ─── CLI 薄壳四叶 ────────────────────────────────────────────────────────────

@goal_app.command("set")
def goal_set_cmd(
    objective: str = typer.Argument(..., help="目标陈述（人读，必给）"),
    done_when: str = typer.Option(
        None, "--done-when",
        help="完成判据 spec JSON（kind 词表 flag_equal/rounds_at_least/"
             "campaign_verdict）"),
    campaign_plan: str = typer.Option(
        None, "--campaign-plan",
        help="战役计划指针（done_when 可引用 campaign verdict，适配层只读）"),
    goal_id: str = typer.Option(None, "--goal-id", help="显式目标 id（缺省自动生成）"),
    max_rounds: int = typer.Option(
        None, "--max-rounds", help="轮次预算（advance 用尽即 blocked；缺省不限）"),
    root: str = typer.Option(None, "--root", help="goals 目录根（缺省 runs/goals）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """立持久目标（跨重启存续；幂等同 id 覆盖）。"""
    result = goal_set(objective, done_when, campaign_plan=campaign_plan,
                      goal_id=goal_id, max_rounds=max_rounds, root=root)
    _emit(result, "持久目标建立失败", json_output=json_output)
    if json_output:
        return
    goal = result.get("goal") or {}
    console.print(f"[green]✓ 目标已立[/green]  id={result.get('goal_id')}"
                  f"  status={result.get('status')}"
                  f"  判据={(goal.get('done_when') or {}).get('kind', '（未声明）')}")
    console.print(f"  落盘: {result.get('path')}")
    raise typer.Exit(code=0)


@goal_app.command("status")
def goal_status_cmd(
    goal_id: str = typer.Argument(..., help="目标 id"),
    root: str = typer.Option(None, "--root", help="goals 目录根（缺省 runs/goals）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """目标状态（objective/判据/轮次/历史摘要，跨进程存续读回）。"""
    result = goal_status(goal_id, root)
    _emit(result, "目标状态读取失败", json_output=json_output)
    if json_output:
        return
    goal = result.get("goal") or {}
    console.print(f"[bold]{result.get('goal_id')}[/bold]"
                  f"  status={goal.get('status')}"
                  f"  rounds={goal.get('rounds')}"
                  f"  更新={goal.get('updated_at')}")
    console.print(f"  目标: {goal.get('objective')}")
    dw = goal.get("done_when")
    console.print(f"  判据: {json.dumps(dw, ensure_ascii=False) if dw else '（未声明）'}")
    history = goal.get("history") or []
    if history:
        tail = history[-1]
        console.print(f"  最近一轮: round={tail.get('round')}"
                      f"  result={tail.get('result')}  {tail.get('reason')}")
    raise typer.Exit(code=0)


@goal_app.command("advance")
def goal_advance_cmd(
    goal_id: str = typer.Argument(..., help="目标 id"),
    evidence_file: str = typer.Option(
        None, "--evidence-file",
        help="证据 JSON 文件（判据评估输入；缺省走 campaign_plan 适配层）"),
    root: str = typer.Option(None, "--root", help="goals 目录根（缺省 runs/goals）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """推进一轮（确定性状态机：done/advancing/blocked 三态；零模型轮）。"""
    result = goal_advance(goal_id, evidence_file, root)
    _emit(result, "续轮推进失败", json_output=json_output)
    if json_output:
        return
    color = {"done": "green", "advancing": "yellow", "blocked": "red"}.get(
        str(result.get("status")), "yellow")
    console.print(f"[{color}]● {result.get('status')}[/{color}]"
                  f"  rounds={result.get('rounds')}"
                  f"  达标={result.get('criteria_met')}")
    console.print(f"  {result.get('reason')}")
    suggestion = result.get("suggestion")
    if suggestion:
        console.print(f"  下一步建议: {json.dumps(suggestion, ensure_ascii=False)}")
    raise typer.Exit(code=0)


@goal_app.command("list")
def goal_list_cmd(
    root: str = typer.Option(None, "--root", help="goals 目录根（缺省 runs/goals）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """清点全部持久目标（只读摘要）。"""
    result = goal_list(root)
    _emit(result, "goals 清点失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[bold]{result.get('root')}[/bold]  共 {result.get('n_goals')} 个目标")
    table = Table(title="持久目标（runs/goals）")
    for col in ("goal_id", "status", "rounds", "objective"):
        table.add_column(col, style="cyan" if col == "goal_id" else None)
    for g in result.get("goals") or []:
        table.add_row(g["goal_id"], g["status"], str(g.get("rounds")),
                      str(g.get("objective"))[:40])
    console.print(table)
    for name in result.get("unreadable") or []:
        console.print(f"  [red]不可读（如实注记）: {name}[/red]")
    raise typer.Exit(code=0)
