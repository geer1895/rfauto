"""lefdef 子应用——LEF/DEF 物理设计交换格式结构化解析 CLI 薄壳
（T-Q57 席位 Q-X57，aurora_q CAD 扩展方向，2026-11-07）。

零逻辑转发 service/lef_def_service（单源；规则 4 薄壳）；词法与 LEF/DEF
结构语义全在 core/lef_def_parser 确定性内核（铁律 7）：
  rfauto lefdef parse [--lef <x.lef> ...] [--def <design.def>] [--json]
  rfauto lefdef check --lef <x.lef> [--lef ...] --def <design.def> [--macro <名>] [--json]

parse 的 --lef（可重复：科技 LEF 与单元 LEF 分文件）/--def 可单给可组合；
缺省紧凑汇总，--json 恒全结构信封（失败路径同为 JSON 信封、exit 1）。
check 跑单元闭合/网连接度/引脚名对齐三件套，verdict=clean/attention/
issues（违规≠exit 1，drc validate 同家法）。两叶的必需输入都走 service
层校验（缺输入=error 信封 exit 1，--json 下不出 typer 红字 usage）。
纯只读：不落盘、零网络、零真机。

**注册形态说明（合流契约——citi/gdsii 域同款挂账合流）**：本模块自带
独立 typer 根 ``lefdef_app``（**不**在模块级 add_typer 到共享 app——
开工时检出 cli/main.py 并发接线风险窗口（同窗 spef/fab 席在制、citi/
gdsii 两域待主代批量接线），按主代合流纪律④延后接线；
tests/gold/cli_registration_order.json 与 count_cli()==322 锚均为冻结
面，先接线后重锚是主代理显式评审动作）。合流接线三步：
  1. main.py 注册序尾追加 re-export + add_typer（vendor_docs/citi 同款）::
       from rfauto.cli.domains.lefdef import lefdef_app as lefdef_app
       from rfauto.cli.domains.lefdef import lefdef_check_cmd as lefdef_check_cmd
       from rfauto.cli.domains.lefdef import lefdef_parse_cmd as lefdef_parse_cmd
       from rfauto.cli.domains._core import app as _lefdef_reg_app  # noqa
       _lefdef_reg_app.add_typer(lefdef_app, name="lefdef")
  2. cli/help_groups.py HELP_PANEL_OF 补一行（TestCliHelpPanels 集合相等钉）::
       "lefdef": "综合与设计",
  3. 金快照重钉（+1 顶层 lefdef、+2 叶 parse/check）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
     并同步 count_cli 锚 +2（test_check_numbers/test_cli/test_cli_registration_order
     叶数钉等共享面，主代统一对账）；同笔移除本席测试的 cli.main 零导入钉。
本席测试经 ``lefdef_app`` 直连（CliRunner），零共享 app 污染、零金快照
漂移。顶层无同名 `lefdef` 域（零撞名自查 2026-11-07：全 src/tests/
scripts 零 lefdef/lef_def 前缀命中，零既有 LEF/DEF 解析面；单源=
core/lef_def_parser+service/lef_def_service）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

lefdef_app = typer.Typer(
    help="LEF/DEF 物理设计交换格式结构化解析（科技库 LEF 层/via/macro/引脚"
         "几何+版图 DEF 组件/引脚/网/走线+交叉校验三件套，只读面）")

#: human 紧凑面逐类列举上限（单元库 macro 常上百，超出折叠计数）。
_LIST_CAP = 12
#: human 面警告展示上限。
_WARN_CAP = 20


def _fmt(val: object) -> str:
    """数值紧凑显示（None → '-'）。"""
    return "-" if val is None else f"{val:g}" if isinstance(val, float) else str(val)


def _render_warnings(warnings: list | None) -> None:
    """解析警告 human 展开（动态段一律 escape）。"""
    items = warnings or []
    for warn in items[:_WARN_CAP]:
        console.print(
            f"  [yellow]! 第 {warn.get('line')} 行 {escape(str(warn.get('name')))}:"
            f" {escape(str(warn.get('note')))}[/yellow]")
    if len(items) > _WARN_CAP:
        console.print(f"  [yellow]… 另 {len(items) - _WARN_CAP} 条警告（--json 看全量）[/yellow]")


def _render_lef(env: dict) -> None:
    """单份 LEF 信封 human 紧凑面。"""
    stats = env.get("stats") or {}
    console.print(
        f"[green]✓ LEF: {escape(str(env.get('path')))}[/green]"
        f"  version={escape(str(env.get('version')))}"
        f"  layers={stats.get('n_layers')}"
        f"  vias={stats.get('n_vias')}"
        f"  macros={stats.get('n_macros')}"
        f"  pins={stats.get('n_pins')}"
        f"  warnings={stats.get('n_warnings')}")
    layers = env.get("layers") or []
    for layer in layers[:_LIST_CAP]:
        console.print(
            f"  layer {escape(str(layer.get('name')))}"
            f"  {layer.get('type') or '-'} {layer.get('direction') or '-'}"
            f"  pitch={_fmt(layer.get('pitch_um'))}"
            f"  width={_fmt(layer.get('width_um'))}"
            f"  spacing={_fmt(layer.get('spacing_um'))} µm")
    if len(layers) > _LIST_CAP:
        console.print(f"  … 另 {len(layers) - _LIST_CAP} 层")
    names = env.get("macro_order") or []
    macros = env.get("macros") or {}
    for name in names[:_LIST_CAP]:
        macro = macros.get(name) or {}
        size = macro.get("size") or {}
        console.print(
            f"  macro {escape(str(name))}  {macro.get('class') or '-'}"
            f"  {_fmt(size.get('width_um'))}x{_fmt(size.get('height_um'))} µm"
            f"  pins={escape(', '.join(macro.get('pin_order') or []))}")
    if len(names) > _LIST_CAP:
        console.print(f"  … 另 {len(names) - _LIST_CAP} 个 macro")
    _render_warnings(env.get("warnings"))


def _render_def(env: dict) -> None:
    """DEF 信封 human 紧凑面。"""
    stats = env.get("stats") or {}
    console.print(
        f"[green]✓ DEF: {escape(str(env.get('path')))}[/green]"
        f"  design={escape(str(env.get('design_name')))}"
        f"  components={stats.get('n_components')}"
        f"  pins={stats.get('n_pins')}"
        f"  nets={stats.get('n_nets')}"
        f"  specialnets={stats.get('n_specialnets')}"
        f"  warnings={stats.get('n_warnings')}")
    units = env.get("units") or {}
    die = env.get("die_area") or {}
    bbox = die.get("bbox_um") or die.get("bbox_dbu")
    if bbox:
        unit = "µm" if die.get("bbox_um") else "DBU"
        console.print(
            f"  DIEAREA ({_fmt(bbox[0])}, {_fmt(bbox[1])})-({_fmt(bbox[2])}, {_fmt(bbox[3])}) {unit}"
            f"  DBU/µm={_fmt(units.get('distance_microns'))}")
    console.print(
        f"  摆放: placed={stats.get('n_placed')} unplaced={stats.get('n_unplaced')}"
        f"  连接={stats.get('n_conns')}  走线段={stats.get('n_route_segments')}"
        f"  rows={stats.get('n_rows')} tracks={stats.get('n_tracks')}")
    for section, counts in (env.get("section_counts") or {}).items():
        if counts.get("declared") is not None and counts.get("declared") != counts.get("parsed"):
            console.print(
                f"  [yellow]{escape(str(section))} 声明 {counts.get('declared')}"
                f" 条/解析 {counts.get('parsed')} 条[/yellow]")
    _render_warnings(env.get("warnings"))


@lefdef_app.command("parse")
def lefdef_parse_cmd(
    lef: list[str] | None = typer.Option(  # noqa: B008
        None, "--lef",
        help="LEF 文件路径（可重复：科技 LEF 与单元 LEF 分文件时多次给出）"),
    def_path: str | None = typer.Option(None, "--def", help="DEF 文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 LEF/DEF（--lef/--def 可单给可组合；缺省紧凑汇总，--json 恒全结构信封）。"""
    from rfauto.service.lef_def_service import (
        parse_lef_def,  # lazy: 叶内延迟导入（Q-X57）
    )

    result = parse_lef_def(lef or [], def_path)
    _emit(result, "LEF/DEF 解析失败", json_output=json_output)
    if json_output:
        return
    for env in result.get("lef") or []:
        _render_lef(env)
    if result.get("def"):
        _render_def(result["def"])


@lefdef_app.command("check")
def lefdef_check_cmd(
    lef: list[str] | None = typer.Option(  # noqa: B008
        None, "--lef", help="LEF 文件路径（可重复；至少给一个）"),
    def_path: str | None = typer.Option(None, "--def", help="DEF 文件路径（必给）"),
    macro: str | None = typer.Option(
        None, "--macro",
        help="top-level 引脚对齐用的 LEF macro 名（缺省=DEF DESIGN 名）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """LEF×DEF 交叉校验（单元闭合/网连接度/引脚名对齐；verdict=clean/attention/issues，违规不改退出码）。"""
    from rfauto.service.lef_def_service import (
        lef_def_check,  # lazy: 叶内延迟导入（Q-X57）
    )

    result = lef_def_check(lef or [], def_path, macro=macro)
    _emit(result, "LEF/DEF 交叉校验失败", json_output=json_output)
    if json_output:
        return
    verdict = result.get("verdict")
    style = {"issues": "red", "attention": "yellow"}.get(str(verdict), "green")
    console.print(
        f"[{style}]✓ LEF/DEF 交叉校验: design={escape(str(result.get('design_name')))}"
        f"  verdict={verdict}[/{style}]")
    closure = result.get("closure") or {}
    if closure.get("closed"):
        console.print(f"  单元闭合: closed（{closure.get('n_models')} 个模型全在 LEF）")
    else:
        console.print(
            f"  单元闭合: 缺 macro {escape(', '.join(closure.get('missing_models') or []))}"
            f"（涉及 {closure.get('n_components_missing_model')} 个组件）")
    conn = result.get("connectivity") or {}
    console.print(
        f"  网连接: nets={conn.get('n_nets')}"
        f"  max_degree={_fmt(conn.get('max_degree'))}"
        f"  悬空={escape(', '.join(conn.get('dangling_nets') or [])) or '无'}"
        f"  单连接={len(conn.get('single_connection_nets') or [])}")
    summary = result.get("summary") or {}
    for key in ("unknown_component_refs", "unknown_toplevel_pin_refs",
                "pins_with_unknown_net", "unknown_pin_refs"):
        if summary.get(key):
            console.print(f"  [red]{key}={summary.get(key)}[/red]")
    top = (result.get("alignment") or {}).get("top_level") or {}
    if top.get("applicable"):
        console.print(
            f"  top-level 引脚对齐（macro {escape(str(top.get('macro')))}）:"
            f"  DEF 有 LEF 无={escape(', '.join(top.get('missing_in_lef') or [])) or '无'}"
            f"  LEF 有 DEF 无={escape(', '.join(top.get('missing_in_def') or [])) or '无'}"
            f"  方向不一致={len(top.get('direction_mismatches') or [])}")
    else:
        console.print(f"  top-level 引脚对齐: 不适用（{escape(str(top.get('reason')))}）")
    if summary.get("parse_warnings"):
        console.print(
            f"  [yellow]解析警告 {summary.get('parse_warnings')} 条（--json 看全量）[/yellow]")
