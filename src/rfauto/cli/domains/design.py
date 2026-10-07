"""design 子应用（SN-3，W6-A 2026-10-06）：level2 设计链/闭环链 shell 面。

链路本体在 service/level2_design.py（design_chain 零 LLM 缺省路径）与
service/level2_closure.py（close_level2_chain 三步闭环）；本模块是薄壳
（规则 4：JSON 进出走 service，铁律 7：数值只由确定性内核产出）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

design_app = typer.Typer(help="level2 设计链（NL 意图→族路由→综合→kickoff 草稿→闭环）")
app.add_typer(design_app, name="design")


@design_app.command("kickoff")
def design_kickoff_cmd(
    prompt: str = typer.Argument(..., help="一句自然语言设计任务（族关键词路由，零 LLM 缺省）"),
    out_dir: str = typer.Option(None, "--out-dir",
                                help="草稿落点（缺省 runs/level2_design/任务号）"),
    optimize: bool = typer.Option(False, "--optimize",
                                  help="追加第 8 环代理寻优 kickoff（缺省关，链路逐字节同七环节）"),
    anchor_correction: bool = typer.Option(False, "--anchor-correction",
                                           help="综合后锚偏差面修正（XC-A；缺省关）"),
    rel_span: float = typer.Option(0.2, "--rel-span",
                                   help="kickoff 搜索域相对跨度（0,1 开区间）"),
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """设计 kickoff：意图→族路由→闭式综合→离线评→bounds/objectives 配方草稿。

    产物：recipe_draft.yaml（可直接喂 rfauto tune）+ record.json（供
    design close 闭环消费），缺省落 runs/level2_design/。零 LLM 零网络
    （铁律 7：数值只来自综合内核与离线评）。
    """
    from rfauto.service.level2_design import design_kickoff

    result = design_kickoff(
        prompt, out_dir=out_dir, enable_optimize=optimize,
        enable_anchor_correction=anchor_correction, rel_span=rel_span)
    if json_output:
        _emit(result, "设计 kickoff 失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 设计 kickoff 失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ 设计 kickoff 完成[/green]  族: {result.get('family')}"
                  f"  任务: {result.get('task_id')}")
    console.print(f"  配方草稿: {result.get('recipe_path')}")
    console.print(f"  record:   {result.get('record_path')}（rfauto design close 消费）")
    bounds = result.get("bounds") or {}
    if bounds:
        console.print("  kickoff 搜索域:")
        for k in sorted(bounds):
            lo, hi = bounds[k]
            console.print(f"    {k}: [{lo:g}, {hi:g}]", markup=False)
    for obj in result.get("objectives") or []:
        console.print(f"  目标: {obj.get('metric')} {obj.get('op')} {obj.get('value')}"
                      f"  band={obj.get('band')}", markup=False)
    for warn in result.get("errors") or []:
        console.print(f"  [yellow]- {warn}[/yellow]")


@design_app.command("close")
def design_close_cmd(
    record: str = typer.Argument(..., help="record.json 路径（design kickoff 产物）"),
    out_dir: str = typer.Option(None, "--out-dir",
                                help="闭环产物落点（缺省 runs/level2_closure）"),
    no_certify: bool = typer.Option(False, "--no-certify", help="跳过 certify 步"),
    no_anchor_writeback: bool = typer.Option(False, "--no-anchor-writeback",
                                             help="跳过锚回写草稿步"),
    no_replan: bool = typer.Option(False, "--no-replan", help="跳过 replan 步"),
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """设计闭环：certify → 锚回写草稿 → replan（单步失败不拖垮其余）。

    三步链本体 = service/level2_closure.close_level2_chain（AD-8）；样本集
    与锚回填草案落盘留证，人工审阅后才可 promote（写面不越权）。
    """
    from rfauto.service.level2_design import design_close

    result = design_close(
        record, out_dir=out_dir, certify=not no_certify,
        anchor_writeback=not no_anchor_writeback, replan=not no_replan)
    if json_output:
        _emit(result, "设计闭环失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[yellow]○ 设计闭环未全通过（逐步结果如实如下）[/yellow]")
    else:
        console.print("[green]✓ 设计闭环完成[/green]")
    console.print(f"  task: {result.get('task_id')}  族: {result.get('family')}")
    for step in ("certify", "anchor_writeback", "replan"):
        sub = result.get(step)
        if sub is None:
            continue
        status = "ok" if (sub or {}).get("ok") else "failed"
        console.print(f"  {step}: [{status}]")
        for err in (sub or {}).get("errors") or []:
            console.print(f"    [red]- {err}[/red]", markup=False)
    for err in result.get("errors") or []:
        console.print(f"  [yellow]- {err}[/yellow]")
    if not result.get("ok"):
        raise typer.Exit(code=1)
