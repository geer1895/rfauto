"""veriloga 子应用——Verilog-A 模拟行为级结构子集解析 CLI 薄壳
（aurora_q 席位 Q-X80，2026-11-08）。

零逻辑转发 service/veriloga_service（Q-X80 单源；规则 4 薄壳）；词法、
module/analog 结构与表达式前缀归一全在 core/veriloga_parser 确定性内核
（铁律 7；与 verilog 域（Q-X47 数字网表结构面）分立——一个是数字网表
结构面、一个是模拟行为块语言面）：
  rfauto veriloga parse --file <file.va> [--json]
  rfauto veriloga report --file <file.va> [--json]

parse 缺省紧凑输出（头部汇总行+逐模块端口/net/参数计数+贡献语句表+
事件名录+警告）；report 缺省紧凑输出（逐模块摘要+全模块参数表+贡献对
清单）；--json 恒全结构信封（成功/失败路径都走 print_json，失败同构
信封 #ge1㉙ 家法）。--json 是纯旗标（无配置/env 回落语义——#277 三态
不适用，stil/gdsii 同款 bool=False）；--file 注解 str（B008 家法）。纯
只读：不落盘、零网络、零真机。

**注册形态说明（合流契约——citi/gdsii/stil 域同款）**：本模块自带独立
typer 根 ``veriloga_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli() 锚均为冻结面，Q-X80 禁改；先接线后重锚是主代理显式评审动
作）。合流接线清单：
  1. main.py 追加 re-export + add_typer（citi/gdsii/stil 同款）::
       from rfauto.cli.domains.veriloga import veriloga_app as veriloga_app
       from rfauto.cli.domains._core import app as _veriloga_reg_app  # noqa
       _veriloga_reg_app.add_typer(veriloga_app, name="veriloga")
  2. cli/help_groups.py HELP_PANEL_OF 补一行：
       "veriloga": "分析与研究"
     （HELP_PANEL_OF 覆盖完整性断言在接线后即红，缺此行——stil 同款
     挂账）；
  3. 叶数锚 +2：本域两叶 parse/report（count_cli 口径=实注册叶子展开
     计数，+1 顶层 veriloga 组不计叶），test_check_numbers/test_cli 的
     CLI 计数锚由主代合流统一重钉；
  4. 注册序金快照重钉（append-only 注册序尾）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
本席测试经 ``veriloga_app`` 直连（CliRunner），零共享 app 污染、零金快
照漂移（自证测试钉住 cli.main 不导入本域——接线时该钉随接线一同移除；
顶层无同名 `veriloga` 域——零撞名自查 2026-11-08：全 CLI 树零
veriloga 前缀组/命令，唯一近名=verilog 域（Q-X47 数字网表面，名字相
邻但语义分立：Verilog-D 网表 vs Verilog-A 行为块）与 fl1_sg13g2 脚本
注释"零 Verilog-A"字样（语义无关非命令面）；单源=core/veriloga_parser+
service/veriloga_service）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

veriloga_app = typer.Typer(
    help="Verilog-A 模拟行为级结构子集解析（只读面：模块/端口/net/参数"
         "/analog 行为块+贡献语句表+表达式前缀归一）")


@veriloga_app.command("parse")
def veriloga_parse_cmd(
    file: str = typer.Option(..., "--file", "-f",
                             help="Verilog-A 文件路径（.va）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 Verilog-A（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.veriloga_service import (
        parse_veriloga_file,  # lazy: 叶内延迟导入（Q-X80）
    )

    result = parse_veriloga_file(str(file))
    _emit(result, "Verilog-A 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ Verilog-A: {escape(str(result.get('path')))}[/green]"
        f"  modules={stats.get('n_modules')}"
        f"  ports={stats.get('n_ports')}"
        f"  nets={stats.get('n_nets')}"
        f"  params={stats.get('n_params')}"
        f"  contribs={stats.get('n_contributions')}"
        f"  events={stats.get('n_events')}"
        f"  warnings={stats.get('n_warnings')}")
    for name, body in (result.get("modules") or {}).items():
        analog = body.get("analog") or {}
        counts = analog.get("stmt_counts") or {}
        console.print(
            f"  模块 [bold]{escape(str(name))}[/bold]"
            f"  ports={len(body.get('ports') or [])}"
            f"  nets={len(body.get('nets') or [])}"
            f"  params={len(body.get('params') or [])}"
            f"  contribs={len(analog.get('contributions') or [])}"
            f"  events={len(analog.get('events') or [])}"
            f"  if={counts.get('if')} for={counts.get('for')}"
            f" while={counts.get('while')}")
        for c in analog.get("contributions") or []:
            console.print(
                f"    {escape(str(c.get('lhs')))} <+ "
                f"{escape(str(c.get('rhs_prefix_tree')))}")
        for ev in analog.get("events") or []:
            args = str(ev.get("args_raw") or "")
            console.print(
                f"    @({escape(str(ev.get('name')))}"
                f"{escape('(' + args + ')') if args else ''})")
    for warn in result.get("warnings") or []:
        note = warn.get("note") if isinstance(warn, dict) else str(warn)
        console.print(f"  [yellow]! {escape(str(note))}[/yellow]")


@veriloga_app.command("report")
def veriloga_report_cmd(
    file: str = typer.Option(..., "--file", "-f",
                             help="Verilog-A 文件路径（.va）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """Verilog-A 统计报告（逐模块摘要+全模块参数表+贡献对清单）。"""
    from rfauto.service.veriloga_service import (
        veriloga_report,  # lazy: 叶内延迟导入（Q-X80）
    )

    result = veriloga_report(str(file))
    _emit(result, "Verilog-A 报告失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ Verilog-A 报告: {escape(str(result.get('path')))}[/green]"
        f"  modules={stats.get('n_modules')}"
        f"  params={stats.get('n_params')}"
        f"  contribs={stats.get('n_contributions')}"
        f"  events={stats.get('n_events')}")
    for row in result.get("modules_summary") or []:
        counts = row.get("stmt_counts") or {}
        console.print(
            f"  模块 [bold]{escape(str(row.get('name')))}[/bold]"
            f"  ports={row.get('n_ports')}  nets={row.get('n_nets')}"
            f"  params={row.get('n_params')}"
            f"  contribs={row.get('n_contributions')}"
            f"  events={row.get('n_events')}"
            f"  if={counts.get('if')}  block={counts.get('block')}")
    for p in result.get("param_table") or []:
        rng = p.get("range") or {}
        range_raw = str(rng.get("raw")) if rng else "-"
        console.print(
            f"  参数 {escape(str(p.get('module')))}."
            f"[bold]{escape(str(p.get('name')))}[/bold]"
            f"  type={escape(str(p.get('type')))}"
            f"  default={escape(str(p.get('default_raw')))}"
            f"  range={escape(range_raw)}")
    for c in result.get("contribution_pairs") or []:
        console.print(
            f"  贡献 {escape(str(c.get('module')))}:"
            f" {escape(str(c.get('lhs')))} <+ "
            f"{escape(str(c.get('rhs_prefix_tree')))}")
    for warn in result.get("warnings") or []:
        note = warn.get("note") if isinstance(warn, dict) else str(warn)
        console.print(f"  [yellow]! {escape(str(note))}[/yellow]")
