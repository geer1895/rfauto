"""drc 子应用——DRC 规则文件结构化解析 CLI 薄壳（aurora_q Q-X48 席位
Q-X48，DRC 自动化借鉴方向，2026-11-07）。

零逻辑转发 service/drc_service（单源；规则 4 薄壳）；规则文法/单位
归一/方向判定/RF 特化检查全在 core/drc_parser 确定性内核（铁律 7）：
  rfauto drc parse <file> [--rules] [--rf] [--json]
  rfauto drc validate <design.json> [--rules <file>] [--rf] [--json]

parse：规则文件（JSON/CSV/自由文本自动检测）→ 结构化输出；缺省紧凑
汇总；``--rules`` human 分支展开规则表；``--rf`` human 分支展开 RF
检查器面（四检查器 × 命中 RF 规则数）；``--json`` 恒全结构信封。
validate：design JSON × 规则集（``--rules <file>``；未给规则且
``--rf`` 时走内置缺省 RF 规则集）→ verdict+violations；违规≠调用
失败（verdict=issues 照常 exit 0，信封 ok 语义；exit 1 保留给调用
失败——文件不可读/解析违规）。纯只读：不落盘、零网络、零真机。

注册=域内自注册（sdc/skill/layer-3d 同款：模块级 add_typer，main.py
只 re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无
同名 `drc` 域（零撞名自查 2026-11-07：全 CLI 树唯一近名 `kicad drc`
叶=KiCad 真机 DRC 运行面、`constraints check`/design-lint=渲染约束
面，语义均≠规则文件结构化解析；单源=core/drc_parser+service/
drc_service）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

drc_app = typer.Typer(
    help="DRC 规则文件结构化解析（JSON/CSV/自由文本统一 schema+RF 特化"
         "检查：阻抗精度/焊盘间距/地过孔围栏/屏蔽罩间距，只读面）")
app.add_typer(drc_app, name="drc")

#: RF 特化检查器面（与 core.RF_RULE_TYPES 同名单源镜像；human 展示用）
_RF_CHECKERS = (
    ("rf_impedance", "RF 走线阻抗精度"),
    ("rf_pad_clearance", "焊盘间距"),
    ("rf_ground_via_fence", "地过孔隔离度"),
    ("rf_shield_clearance", "屏蔽罩间距"),
)


def _fmt_value(value: object) -> str:
    """规则值 → 单行串（range 列表/rule token 列表/数值/原文兜底）。"""
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return str(value)


@drc_app.command("parse")
def drc_parse_cmd(
    file: str = typer.Argument(..., help="DRC 规则文件路径"
                               "（.json/.csv/自由文本，自动检测）"),
    rules: bool = typer.Option(
        False, "--rules", help="human 分支展开规则表（name/type/value/"
                               "layers/priority/enabled）"),
    rf: bool = typer.Option(
        False, "--rf", help="human 分支展开 RF 检查器面（四检查器 × "
                            "命中 RF 规则数）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 DRC 规则文件（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.drc_service import parse_drc_file  # lazy: 叶内延迟导入（Q-X48）

    result = parse_drc_file(file)
    _emit(result, "DRC 规则解析失败", json_output=json_output)
    if json_output:
        return
    meta = result.get("metadata", {})
    console.print(
        f"[green]✓ DRC: {escape(str(result.get('path')))}[/green]"
        f"  format={result.get('format')}"
        f"  rules={meta.get('n_rules')}"
        f"  enabled={meta.get('n_enabled')}"
        f"  disabled={meta.get('n_disabled')}"
        f"  groups={meta.get('n_groups')}"
        f"  rf_rules={meta.get('n_rf_rules')}"
        f"  warnings={meta.get('n_warnings')}")
    if rules:
        console.print("[bold]rules（规则表）[/bold]")
        for rule in result.get("rules") or []:
            state = "on" if rule.get("enabled") else "off"
            console.print(
                f"  {escape(str(rule.get('name')))}"
                f"  type={escape(str(rule.get('type')))}"
                f"  value={escape(_fmt_value(rule.get('value')))}"
                f"  unit={escape(str(rule.get('unit')))}"
                f"  layers={escape(','.join(rule.get('layer_scope') or []))}"
                f"  priority={rule.get('priority')}  {state}")
    if rf:
        console.print("[bold]RF 检查器面（--rf 启用后生效）[/bold]")
        all_rules = result.get("rules") or []
        for rtype, label in _RF_CHECKERS:
            hit = [r.get("name") for r in all_rules if r.get("type") == rtype]
            console.print(
                f"  {escape(rtype)}  {escape(label)}  命中={len(hit)}"
                + (f"  {escape(', '.join(str(n) for n in hit))}" if hit else ""))
    for warn in result.get("warnings") or []:
        console.print(
            f"  [yellow]! 第 {warn.get('line')} 行 "
            f"{escape(str(warn.get('rule')))}: "
            f"{escape(str(warn.get('note')))}[/yellow]")


@drc_app.command("validate")
def drc_validate_cmd(
    design: str = typer.Argument(..., help="design JSON 路径"
                                 "（objects 列表 + 可选 coordinate_unit）"),
    rules_file: str = typer.Option(
        None, "--rules", help="DRC 规则文件路径（缺省时须 --rf 走内置"
                              "缺省 RF 规则集）"),
    rf: bool = typer.Option(
        False, "--rf", help="启用 RF 特化检查器（规则文件中 RF 类型规则"
                            "求值；无 --rules 时用内置缺省 RF 规则集）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """design × 规则集校验（verdict=issues/attention/clean；违规≠exit 1）。"""
    from rfauto.service.drc_service import validate_design_file  # lazy: 叶内延迟导入（Q-X48）

    result = validate_design_file(design, rules_file, rf=rf)
    _emit(result, "DRC 校验失败", json_output=json_output)
    if json_output:
        return
    summary = result.get("summary", {})
    verdict = result.get("verdict")
    style = {"issues": "red", "attention": "yellow"}.get(str(verdict), "green")
    console.print(
        f"[{style}]✓ DRC 校验: {escape(str(result.get('design_path')))}"
        f"  verdict={verdict}[/{style}]"
        f"  rules={summary.get('n_rules')}"
        f"  evaluated={summary.get('n_evaluated')}"
        f"  violations={summary.get('n_violation_rules')}"
        f"  unknown={summary.get('n_unknown_rules')}"
        + (f"  rf_skipped={summary.get('n_rf_skipped')}"
           if summary.get("n_rf_skipped") else ""))
    for v in result.get("violations") or []:
        console.print(
            f"  [red]✗ {escape(str(v.get('rule')))}[/red]"
            f"  objects={escape(','.join(str(o) for o in v.get('objects') or []))}"
            f"  actual={escape(str(v.get('actual')))}"
            f"  expected={escape(str(v.get('expected')))}")
    for warn in result.get("warnings") or []:
        console.print(
            f"  [yellow]! {escape(str(warn.get('rule')))}: "
            f"{escape(str(warn.get('note')))}[/yellow]")
