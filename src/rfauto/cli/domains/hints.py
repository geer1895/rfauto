"""hints 子应用（错误提示规则面；W1-A 孤儿接线单元13，2026-10-05）。

只读叶：规则表清单（pattern/match/hint/refs/severity，确定性序）。
主挂点不在此文件——``_core._emit`` 失败信封 best-effort 注入 ``hints``
键（hint_for_message），全部 --json 失败出口自动带提示（见 _core.py）。
零逻辑薄壳转发 service/error_hints_service（规则 4）；规则表匹配是纯
映射（硬规则 7 对偶：映射表也是确定性数据）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

hints_app = typer.Typer(help="错误提示规则面（错误指纹 → 可行动提示，只读）")
app.add_typer(hints_app, name="hints")


@hints_app.command("list")
def hints_list_cmd(
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="JSON 输出（供脚本/Agent 消费）"),
) -> None:
    """列出全部错误提示规则（指纹/提示/坑号指针/级别，确定性序）。"""
    from rfauto.service.error_hints_service import list_hint_rules

    result = list_hint_rules()
    _emit(result, "规则表读取失败", json_output=json_output)
    if json_output:
        return
    rules = result.get("rules") or []
    console.print(f"[green]✓ 错误提示规则 {len(rules)} 条[/green]")
    for rule in rules:
        # markup=False：规则指纹原文直出（pattern 含方括号类字符也不被当标记吞掉）
        console.print(
            f"  {rule.get('severity', 'info')}  {rule.get('pattern', '')}"
            f"  →  {rule.get('hint', '')}", markup=False)
        refs = rule.get("refs") or ""
        if refs:
            console.print(f"      refs: {refs}", style="dim", markup=False)
