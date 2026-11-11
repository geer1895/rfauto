"""gdsii 子应用——GDSII 版图交换格式结构化解析 CLI 薄壳
（aurora_q 席位 Q-X58，2026-11-07）。

零逻辑转发 service/gdsii_service（Q-X58 单源；规则 4 薄壳）；字节级
记录流与 GDSII 结构语义全在 core/gdsii_parser 确定性内核（铁律 7）：
  rfauto gdsii parse --file <path.gds> [--json]
  rfauto gdsii layers --file <path.gds> [--json]

parse 缺省紧凑输出（库/版本/单位 + 逐结构计数）；--json 恒全结构失败
同构信封（--json 恒全信封：成功/失败路径都走 print_json，#ge1㉙ 家
法）。纯只读：不落盘、零网络、零真机。

**注册形态说明（合流契约——citi 域同款）**：本模块自带独立 typer 根
``gdsii_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli()==322 锚均为冻结面，Q-X58 禁改；先接线后重锚是主代理显式
评审动作）。合流接线两步：
  1. main.py 追加 re-export + add_typer（vendor_docs/citi 同款）::
       from rfauto.cli.domains.gdsii import gdsii_app as gdsii_app
       from rfauto.cli.domains._core import app as _gdsii_reg_app  # noqa
       _gdsii_reg_app.add_typer(gdsii_app, name="gdsii")
  2. 金快照重钉（+1 顶层 gdsii、+2 叶 =324）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
     并同步 test_check_numbers.py 的 CLI 锚 322→324。
本席测试经 ``gdsii_app`` 直连（CliRunner），零共享 app 污染、零金快照
漂移（自证测试钉住 cli.main 不导入本域；顶层无同名 `gdsii` 域——零
撞名自查 2026-11-07：全 CLI 树零 gdsii 前缀组/命令，唯一近名=
layout_interchange/format_overview 内的 gdsii 字样属格式名提及，非命
令面；单源=core/gdsii_parser+service/gdsii_service）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

gdsii_app = typer.Typer(
    help="GDSII 版图交换格式结构化解析（二进制记录流只读面：边界/路径/"
         "引用/文本六桶+层级统计+层汇总）")


@gdsii_app.command("parse")
def gdsii_parse_cmd(
    file: str = typer.Option(..., "--file", help="GDSII (.gds) 文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 GDSII 文件（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.gdsii_service import parse_gdsii_file  # lazy: 叶内延迟导入

    result = parse_gdsii_file(str(file))
    _emit(result, "GDSII 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats", {})
    console.print(
        f"[green]✓ GDSII: {escape(str(result.get('path')))}[/green]"
        f"  lib={escape(str(result.get('lib_name')))}"
        f"  version={result.get('version')}"
        f"  structures={stats.get('n_structures')}"
        f"  boundaries={stats.get('n_boundaries')}"
        f"  paths={stats.get('n_paths')}"
        f"  srefs={stats.get('n_srefs')}"
        f"  arefs={stats.get('n_arefs')}"
        f"  texts={stats.get('n_texts')}"
        f"  boxes={stats.get('n_boxes')}"
        f"  warnings={stats.get('n_warnings')}")
    units = result.get("units") or {}
    console.print(
        f"  units: db_um={units.get('db_um')}  user_um={units.get('user_um')}")
    for name, body in (result.get("structures") or {}).items():
        console.print(
            f"  [bold]{escape(str(name))}[/bold]"
            f"  boundaries={len(body.get('boundaries') or [])}"
            f"  paths={len(body.get('paths') or [])}"
            f"  srefs={len(body.get('srefs') or [])}"
            f"  arefs={len(body.get('arefs') or [])}"
            f"  texts={len(body.get('texts') or [])}"
            f"  boxes={len(body.get('boxes') or [])}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@gdsii_app.command("layers")
def gdsii_layers_cmd(
    file: str = typer.Option(..., "--file", help="GDSII (.gds) 文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """层汇总（逐 (layer,datatype) 元素计数+包围盒，只读）。"""
    from rfauto.service.gdsii_service import (  # lazy: 叶内延迟导入
        gdsii_layer_report,
    )

    result = gdsii_layer_report(str(file))
    _emit(result, "GDSII 层汇总失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓ GDSII 层汇总: {escape(str(result.get('path')))}[/green]"
        f"  layer_keys={result.get('n_layer_keys')}")
    for ent in result.get("layers") or []:
        bbox = ent.get("bbox_dbu")
        bbox_s = ("-" if bbox is None
                  else f"[{bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]}]")
        kinds = ent.get("by_kind") or {}
        kind_s = "  ".join(f"{k}={v}" for k, v in kinds.items())
        console.print(
            f"  layer={ent.get('layer')}  datatype={ent.get('datatype')}"
            f"  n={ent.get('n_elements')}  {kind_s}"
            f"  bbox_dbu={bbox_s}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")
