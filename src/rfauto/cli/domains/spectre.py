"""spectre 子应用——Spectre 网表（Cadence 模拟仿真器原生语法）结构化解析
CLI 薄壳（aurora_q 席位 Q-X79，2026-11-08）。

零逻辑转发 service/spectre_service（单源；规则 4 薄壳）；Spectre 词法、
parameters 声明表、subckt 嵌套栈、首字母器件类型映射与层次统计全在
core/spectre_parser 确定性内核（铁律 7：表达式只保留原文不求值）：
  rfauto spectre parse --file <netlist.scs> [--json]
  rfauto spectre report --file <netlist.scs> [--json]

parse 缺省紧凑输出（lang/计数汇总行+逐器件类型计数+警告清单）；report
缺省紧凑输出（库存 top+层次摘要+引用/选项块计数）；--json 恒全结构信封
（成功/失败路径都走 print_json，失败同构信封 #ge1㉙ 家法）。--json 是纯
旗标（无配置/env 回落语义——#277 三态不适用，vcd/gdsii 同款 bool=False）；
--file 注解 str（B008 家法）。纯只读：不落盘、零网络、零真机。

**注册形态说明（合流契约——citi/gdsii/stil 域同款）**：本模块自带独立
typer 根 ``spectre_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的 count_cli()
锚均为冻结面，Q-X79 禁改；先接线后重锚是主代理显式评审动作）。合流接线
清单：
  1. main.py 追加 re-export + add_typer（citi/gdsii/stil 同款）::
       from rfauto.cli.domains.spectre import spectre_app as spectre_app
       from rfauto.cli.domains._core import app as _spectre_reg_app  # noqa
       _spectre_reg_app.add_typer(spectre_app, name="spectre")
  2. cli/help_groups.py HELP_PANEL_OF 补一行：``"spectre": "分析与研究"``
     （test_aurora_n_wave_ui_c 的 HELP_PANEL_OF 覆盖完整性断言在接线后即
     红，缺此行——stil 同款挂账）；
  3. 叶数锚 +2：本域两叶 parse/report（count_cli 口径=实注册叶子展开计
     数，+1 顶层 spectre 组不计叶），test_check_numbers/test_cli 的 CLI
     计数锚由主代合流统一重钉；
  4. 注册序金快照重钉（append-only 注册序尾）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
本席测试经 ``spectre_app`` 直连（CliRunner），零共享 app 污染、零金快照
漂移（自证测试钉住 cli.main 不导入本域——接线时该钉随接线一同移除）。
顶层无同名 ``spectre`` 域——零撞名自查 2026-11-08：全 CLI 树零 spectre
前缀组/命令，唯一近名=既有 ``spice`` 域（Q-X33，`rfauto spice parse`）与
mcp_tools/parser_formats.py 的 flavor 词表字样 ``spectre``——均为解析
flavor 词面非命令面，单源=core/spectre_parser+service/spectre_service。
接线前 domain_survey V2 将本模块列为孤儿域模块（bsdl/citi/gdsii/stil/
odbpp 等挂账同态——该基线在 HEAD 即红非本席引入，第 1 步接线即清偿）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

spectre_app = typer.Typer(
    help="Spectre 网表解析（Cadence 模拟仿真器原生语法只读面：parameters/"
         "subckt 层次/器件库存/选项块登记，表达式只保留原文不求值）")


def _fmt(value: object) -> str:
    """人读值格式（None 如实连字符；escape 防 rich markup 误吞 ``[``）。"""
    return "-" if value is None else escape(str(value))


@spectre_app.command("parse")
def spectre_parse_cmd(
    file: str = typer.Option(..., "--file", help="Spectre 网表路径（.scs/.spc 等）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """全结构化解析（parameters 声明表/subckt 层次表/顶层实例/选项块+引用登记）。"""
    from rfauto.service.spectre_service import parse_spectre_file  # lazy: 叶内延迟导入

    result = parse_spectre_file(file)
    _emit(result, "Spectre 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓[/green] lang={_fmt(result.get('lang'))}"
        f" instances={stats.get('n_instances')} top={stats.get('n_top_instances')}"
        f" subckts={stats.get('n_subckts')} parameters={stats.get('n_parameters')}"
        f" depth={stats.get('max_depth')} warnings={len(result.get('warnings') or [])}")
    counts = stats.get("per_device_type_counts") or {}
    if counts:
        body = " ".join(f"{k}={v}" for k, v in counts.items())
        console.print(f"  devices: {body}")
    for warning in result.get("warnings") or []:
        console.print(f"  [yellow]⚠ {escape(warning)}[/yellow]")


@spectre_app.command("report")
def spectre_report_cmd(
    file: str = typer.Option(..., "--file", help="Spectre 网表路径（.scs/.spc 等）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """统计聚合（器件库存+参数键频次 top+层次摘要+参数引用点计数）。"""
    from rfauto.service.spectre_service import spectre_report  # lazy: 叶内延迟导入

    result = spectre_report(file)
    _emit(result, "Spectre 统计失败", json_output=json_output)
    if json_output:
        return
    inventory = result.get("inventory") or {}
    console.print(
        f"[green]✓[/green] instances={inventory.get('n_instances')}"
        f" unknown={inventory.get('n_unknown')}"
        f" param_keys={inventory.get('n_distinct_param_keys')}")
    per_type = inventory.get("per_device_type") or {}
    if per_type:
        body = " ".join(f"{k}={v}" for k, v in per_type.items())
        console.print(f"  devices: {body}")
    freq = inventory.get("param_key_freq") or []
    if freq:
        body = " ".join(f"{item['key']}:{item['count']}" for item in freq[:8])
        console.print(f"  param keys top: {body}")
    hierarchy = result.get("hierarchy") or {}
    console.print(
        f"  subckts={hierarchy.get('n_subckts')} depth={hierarchy.get('max_depth')}"
        f" roots={_fmt(hierarchy.get('roots'))}")
    console.print(
        f"  includes={result.get('n_includes')} options={result.get('n_options_blocks')}"
        f" foreign_segments={result.get('n_foreign_segments')}")
    for warning in result.get("warnings") or []:
        console.print(f"  [yellow]⚠ {escape(warning)}[/yellow]")
