"""bsdl 子应用——BSDL（Boundary Scan Description Language，IEEE 1149.1
附录 A）边界扫描描述结构化解析 CLI 薄壳（aurora_q 席位 Q-X77，2026-11-08）。

零逻辑转发 service/bsdl_service（单源；规则 4 薄壳）；VHDL 子集词法、
entity/port/属性面、边界寄存器单元表与控制链校验全在 core/bsdl_parser
确定性内核（铁律 7）：
  rfauto bsdl parse --file <file.bsd> [--json]
  rfauto bsdl report --file <file.bsd> [--json]

parse 缺省紧凑输出（entity 汇总行+TAP 五信号+引脚映射+边界单元逐行+
警告）；report 缺省紧凑输出（汇总+指令表+边界 function 分桶+长度一致
性三数字）；--json 恒全结构信封（成功/失败路径都走 print_json，失败同
构信封 #ge1㉙ 家法）。--json 是纯旗标（无配置/env 回落语义——#277 三态
不适用，stil/gdsii 同款 bool=False）；--file 注解 str（B008 家法）。纯
只读：不落盘、零网络、零真机。

**注册形态说明（合流契约——stil/citi/gdsii 域同款）**：本模块自带独立
typer 根 ``bsdl_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli() 锚均为冻结面，Q-X77 禁改；先接线后重锚是主代理显式评审动
作）。合流接线清单：
  1. main.py 追加 re-export + add_typer（vendor_docs/citi/gdsii/stil 同款）::
       from rfauto.cli.domains.bsdl import bsdl_app as bsdl_app
       from rfauto.cli.domains._core import app as _bsdl_reg_app  # noqa
       _bsdl_reg_app.add_typer(bsdl_app, name="bsdl")
  2. cli/help_groups.py HELP_PANEL_OF 补一行：``"bsdl": "分析与研究"``
     （test_aurora_n_wave_ui_c 的 HELP_PANEL_OF 覆盖完整性断言在接线后即
     红，缺此行——stil/vcd 同款挂账）；
  3. 叶数锚 +2：本域两叶 parse/report（count_cli 口径=实注册叶子展开计
     数，+1 顶层 bsdl 组不计叶），test_check_numbers/test_cli 的 CLI 计数
     锚由主代合流统一重钉；
  4. 注册序金快照重钉（append-only 注册序尾）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
本席测试经 ``bsdl_app`` 直连（CliRunner），零共享 app 污染、零金快照
漂移（自证测试钉住 cli.main 不导入本域——接线时该钉随接线一同移除；
顶层无同名 `bsdl` 域——零撞名自查 2026-11-08：全 CLI 树零 bsdl 前缀组/
命令，唯一近名=core/stil_parser docstring 内 BSDL 字样（Import/
Procedures 引用说明），非命令面；单源=core/bsdl_parser+
service/bsdl_service）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

bsdl_app = typer.Typer(
    help="BSDL 边界扫描描述解析（IEEE 1149.1 只读面：entity/port/TAP/"
         "引脚映射/指令表/边界寄存器单元+控制链校验+长度一致性三数字）")


@bsdl_app.command("parse")
def bsdl_parse_cmd(
    file: str = typer.Option(..., "--file", "-f", help="BSDL 文件路径（.bsd/.bsdl）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 BSDL（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.bsdl_service import (
        parse_bsdl_file,  # lazy: 叶内延迟导入（Q-X77）
    )

    result = parse_bsdl_file(str(file))
    _emit(result, "BSDL 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ BSDL: {escape(str(result.get('path')))}[/green]"
        f"  entity={escape(str(result.get('entity_name')))}"
        f"  ports={stats.get('n_ports')}"
        f"  tap={result.get('n_tap_present')}/5"
        f"  pins={stats.get('n_pins')}"
        f"  instructions={stats.get('n_instructions')}"
        f"  cells={stats.get('n_boundary_cells')}"
        f"  warnings={stats.get('n_warnings')}")
    for tap, info in (result.get("tap_ports") or {}).items():
        state = escape(str(info.get("dir"))) if info else "缺"
        console.print(f"  TAP [bold]{escape(tap.upper())}[/bold]  {state}")
    for pin, locs in (result.get("pins") or {}).items():
        console.print(
            f"  引脚 [bold]{escape(str(pin))}[/bold]"
            f" → {escape(','.join(str(x) for x in locs) or '-')}")
    for cell in result.get("boundary_cells") or []:
        port = "*" if cell.get("is_internal") else str(cell.get("port"))
        ctl = cell.get("control_cell")
        ctl_s = f"  cc={ctl}" if ctl is not None else ""
        console.print(
            f"  单元 {cell.get('num')}"
            f"  {escape(str(cell.get('cell_type')))}"
            f"  port={escape(port)}"
            f"  func={escape(str(cell.get('function')))}"
            f"  safe={escape(str(cell.get('safe')))}{ctl_s}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@bsdl_app.command("report")
def bsdl_report_cmd(
    file: str = typer.Option(..., "--file", "-f", help="BSDL 文件路径（.bsd/.bsdl）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """BSDL 统计与指令/边界一致性报告（指令表+function 分桶+长度三数字）。"""
    from rfauto.service.bsdl_service import (
        bsdl_report,  # lazy: 叶内延迟导入（Q-X77）
    )

    result = bsdl_report(str(file))
    _emit(result, "BSDL 报告失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ BSDL 报告: {escape(str(result.get('path')))}[/green]"
        f"  entity={escape(str(result.get('entity_name')))}"
        f"  cells={stats.get('n_boundary_cells')}"
        f"  control={stats.get('n_control_cells')}"
        f"  output3={stats.get('n_output3_cells')}"
        f"  chain_warn={stats.get('n_control_chain_warnings')}")
    inst = result.get("instruction_summary") or {}
    for name, bits in (inst.get("instructions") or {}).items():
        console.print(
            f"  指令 [bold]{escape(str(name))}[/bold] = {escape(str(bits))}")
    console.print(
        f"  capture={escape(str(inst.get('capture')))}"
        f"  idcode_len={inst.get('idcode_length')}"
        f"  idcode_valid={inst.get('idcode_valid')}")
    bnd = result.get("boundary_summary") or {}
    for func, count in (bnd.get("function_buckets") or {}).items():
        console.print(f"  function {escape(str(func))}: {count}")
    console.print(
        f"  长度一致性 declared={bnd.get('length_declared')}"
        f"  max_cell+1={bnd.get('length_max_cell_plus_1')}"
        f"  rel_diff={bnd.get('length_rel_diff')}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")
