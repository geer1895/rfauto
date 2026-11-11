"""stil 子应用——STIL（Standard Test Interface Language，IEEE 1450）测试向量
结构化解析 CLI 薄壳（aurora_q 席位 Q-X72，2026-11-08）。

零逻辑转发 service/stil_service（单源；规则 4 薄壳）；STIL 词法、块结构
状态机、WFC 波形表与向量/时序联查全在 core/stil_parser 确定性内核（铁律
7）：
  rfauto stil parse --file <file.stil> [--json]
  rfauto stil report --file <file.stil> [--json]

parse 缺省紧凑输出（头部汇总行+逐信号方向/逐组成员+警告）；report 缺省
紧凑输出（汇总+逐 WaveformTable 周期+逐 pattern 向量/Loop/Shift 账目）；
--json 恒全结构信封（成功/失败路径都走 print_json，失败同构信封
#ge1㉙ 家法）。--json 是纯旗标（无配置/env 回落语义——#277 三态不适用，
vcd/gdsii 同款 bool=False）；--file 注解 str（B008 家法）。纯只读：不落盘、
零网络、零真机。

**注册形态说明（合流契约——citi/gdsii 域同款）**：本模块自带独立 typer
根 ``stil_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli() 锚均为冻结面，Q-X72 禁改；先接线后重锚是主代理显式评审动
作）。合流接线清单：
  1. main.py 追加 re-export + add_typer（vendor_docs/citi/gdsii 同款）::
       from rfauto.cli.domains.stil import stil_app as stil_app
       from rfauto.cli.domains._core import app as _stil_reg_app  # noqa
       _stil_reg_app.add_typer(stil_app, name="stil")
  2. cli/help_groups.py HELP_PANEL_OF 补一行：``"stil": "分析与研究"``
     （test_aurora_n_wave_ui_c 的 HELP_PANEL_OF 覆盖完整性断言在接线后即
     红，缺此行——vcd 同款挂账）；
  3. 叶数锚 +2：本域两叶 parse/report（count_cli 口径=实注册叶子展开计
     数，+1 顶层 stil 组不计叶），test_check_numbers/test_cli 的 CLI 计数
     锚由主代合流统一重钉；
  4. 注册序金快照重钉（append-only 注册序尾）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
本席测试经 ``stil_app`` 直连（CliRunner），零共享 app 污染、零金快照
漂移（自证测试钉住 cli.main 不导入本域——接线时该钉随接线一同移除；
顶层无同名 `stil` 域——零撞名自查 2026-11-08：全 CLI 树零 stil 前缀组/
命令，唯一近名=logs 域 LogDistiller 字样内含子串，非命令面；单源=
core/stil_parser+service/stil_service）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

stil_app = typer.Typer(
    help="STIL 测试向量解析（IEEE 1450 只读面：Signals/SignalGroups/Timing/"
         "Pattern 结构化提取+向量与时序事件联查+覆盖统计）")


@stil_app.command("parse")
def stil_parse_cmd(
    file: str = typer.Option(..., "--file", "-f", help="STIL 文件路径（.stil）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 STIL（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.stil_service import (
        parse_stil_file,  # lazy: 叶内延迟导入（Q-X72）
    )

    result = parse_stil_file(str(file))
    _emit(result, "STIL 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ STIL: {escape(str(result.get('path')))}[/green]"
        f"  version={escape(str(result.get('header_version')))}"
        f"  signals={stats.get('n_signals')}"
        f"  groups={stats.get('n_groups')}"
        f"  wfts={stats.get('n_wfts')}"
        f"  patterns={stats.get('n_patterns')}"
        f"  vectors={stats.get('n_vectors_total')}"
        f"  warnings={stats.get('n_warnings')}")
    for name, sig in (result.get("signals") or {}).items():
        wfcs = ",".join(str(c) for c in (sig.get("wfcs") or []))
        console.print(
            f"  信号 [bold]{escape(str(name))}[/bold]"
            f"  {escape(str(sig.get('dir')))}"
            f"  wfcs={escape(wfcs or '-')}")
    for name, members in (result.get("groups") or {}).items():
        console.print(
            f"  组 [bold]{escape(str(name))}[/bold]"
            f" = {escape(' '.join(str(m) for m in members) or '-')}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@stil_app.command("report")
def stil_report_cmd(
    file: str = typer.Option(..., "--file", "-f", help="STIL 文件路径（.stil）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """STIL 统计与 timing/pattern 清单报告（逐 WFT 周期+逐 pattern 账目）。"""
    from rfauto.service.stil_service import (
        stil_report,  # lazy: 叶内延迟导入（Q-X72）
    )

    result = stil_report(str(file))
    _emit(result, "STIL 报告失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ STIL 报告: {escape(str(result.get('path')))}[/green]"
        f"  version={escape(str(result.get('header_version')))}"
        f"  patterns={stats.get('n_patterns')}"
        f"  vectors={stats.get('n_vectors_total')}"
        f"  loop_mult={stats.get('n_loop_multiplier_total')}"
        f"  shift={stats.get('n_shift_total')}"
        f"  ann={stats.get('n_ann')}")
    for wft in result.get("timing_summary") or []:
        console.print(
            f"  WFT [bold]{escape(str(wft.get('name')))}[/bold]"
            f"  period={escape(str(wft.get('period')))}"
            f"  groups={wft.get('n_waveform_groups')}")
    for row in result.get("patterns_summary") or []:
        burst = str(row.get("burst") or "")
        full = f"{burst}.{row.get('name')}" if burst else str(row.get("name"))
        console.print(
            f"  Pattern [bold]{escape(full)}[/bold]"
            f"  wft={escape(str(row.get('wft')))}"
            f"  vectors={row.get('n_vectors')}"
            f"  loop={row.get('n_loop')}"
            f"  shift={row.get('n_shift')}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")
