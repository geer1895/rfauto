"""sandbox 子应用（SN-17，W6-A 2026-10-06）：agent 写面治理三件套 CLI 对等。

沙箱治理此前锁在浏览器（ui/server.py /api/sandbox/*）与 scattered 的
study inject 旗标；本模块补 CLI 对等（list/diff/promote），业务本体在
service/ui_service.sandbox_*（RecipeSandbox，promote 走既有三层 Gate 生成
提案进收件箱，等人工批准才生效——agent 写面隔离规则 6 不变）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

sandbox_app = typer.Typer(help="agent 配方沙箱治理（草稿列表/差异/三层 Gate 提案）")
app.add_typer(sandbox_app, name="sandbox")


@sandbox_app.command("list")
def sandbox_list_cmd(
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """列出沙箱草稿（含与真实配方的匹配 + 参数差异摘要）。"""
    from rfauto.service.ui_service import sandbox_drafts

    result = sandbox_drafts()
    _emit(result, "沙箱草稿列表失败", json_output=json_output)
    if json_output:
        return
    items = result.get("drafts") or []
    console.print(f"[bold]沙箱草稿[/bold]（{len(items)} 个）")
    for it in items:
        recipe = it.get("recipe") or "（来源配方不可辨）"
        console.print(f"  - {it.get('draft')}", markup=False)
        console.print(f"      配方: {recipe}", markup=False)
        if it.get("params_changed") is not None:
            console.print(f"      参数差异: {it['params_changed']}", markup=False)
        if it.get("has_text_diff"):
            console.print("      含文本级 diff（sandbox diff 查看）")
        if it.get("diff_error"):
            console.print(f"      [yellow]diff 失败: {it['diff_error']}[/yellow]",
                          markup=False)
    if not items:
        console.print("  [dim]（空——agent 未落草稿）[/dim]")


@sandbox_app.command("diff")
def sandbox_diff_cmd(
    recipe: str = typer.Argument(..., help="真实配方路径（草稿按确定性规则反查）"),
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """查看单个沙箱草稿与真实配方的差异（unified diff+参数差异表）。"""
    from rfauto.service.ui_service import sandbox_diff

    result = sandbox_diff(recipe)
    if json_output:
        _emit(result, "沙箱 diff 失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 沙箱 diff 失败[/red]")
        for err in [result.get("error") or e for e in result.get("errors", [])]:
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    changed = result.get("params_changed")
    console.print(f"[bold]沙箱 diff[/bold]（{recipe}）")
    if changed is not None:
        console.print(f"  参数差异 {len(changed)} 处")
        for e in changed:
            console.print(f"    {e}", markup=False)
    unified = result.get("unified_diff") or ""
    if unified:
        console.print(unified, markup=False)
    else:
        console.print("  [dim]（无文本级差异）[/dim]")


@sandbox_app.command("promote")
def sandbox_promote_cmd(
    recipe: str = typer.Argument(..., help="真实配方路径（草稿差异送三层 Gate）"),
    adapter: str = typer.Option("fake", "--adapter", "-a", help="L2 dry-run 通道适配器"),
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """草稿差异送三层 Gate（L1 白名单+L2 dry-run+L3 确认）——生成提案进收件箱。

    注意：promote 只生成提案，**等人工批准才生效**（agent 写面隔离规则 6；
    收件箱面见 UI 或既有 proposal 消费入口）。
    """
    from rfauto.service.ui_service import sandbox_promote

    result = sandbox_promote(recipe, adapter_name=adapter)
    if json_output:
        _emit(result, "沙箱 promote 失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 沙箱 promote 失败[/red]")
        for err in [result.get("error") or e for e in result.get("errors", [])]:
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ 提案已生成（待人工批准）[/green]（{recipe}）")
    for k, v in sorted(result.items()):
        if k in ("ok",):
            continue
        if isinstance(v, (str, int, float, bool)):
            console.print(f"  {k}: {v}", markup=False)
