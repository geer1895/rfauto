"""ibis-ami 子应用——IBIS-AMI (.ami) 参数文件结构化解析 CLI 薄壳（aurora_q
席位 Q-X86，2026-11-08）。

零逻辑转发 service/ibis_ami_service（单源；规则 4 薄壳）；AMI 词法、
RESERVED 必备键缺失清单、Model_Specific 五键逐参/type 分派与 in-bounds
开闭区间结构化全在 core/ibis_ami_parser 确定性内核（铁律 7）：
  rfauto ibis-ami parse --file <file.ami> [--json]
  rfauto ibis-ami report --file <file.ami> [--json]

parse 缺省紧凑输出（版本/计数汇总行+逐参数 type/default/bounds 行+警告）；
report 缺省紧凑输出（汇总+逐保留参数行+逐参数行+DLL·SoC 引用+必备键
缺失清单）；--json 恒全结构信封（成功/失败路径都走 print_json，失败同构
信封 #ge1㉙ 家法）。--json 是纯旗标（无配置/env 回落语义——#277 三态不
适用，stil/bsdl 同款 bool=False）；--file 注解 str（B008 家法）。纯只读：
不落盘、零网络、零真机。

**注册形态说明（合流契约——stil/bsdl 域同款）**：本模块自带独立 typer
根 ``ibis_ami_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli() 锚均为冻结面，Q-X86 禁改；先接线后重锚是主代理显式评审动
作）。合流接线清单（两步接线处方）：
  1. main.py 追加 re-export + add_typer（vendor_docs/stil/bsdl 同款）::
       from rfauto.cli.domains.ibis_ami import ibis_ami_app as ibis_ami_app
       from rfauto.cli.domains._core import app as _ibis_ami_reg_app  # noqa
       _ibis_ami_reg_app.add_typer(ibis_ami_app, name="ibis-ami")
  2. cli/help_groups.py HELP_PANEL_OF 补一行：``"ibis-ami": "分析与研究"``
     （test_aurora_n_wave_ui_c 的 HELP_PANEL_OF 覆盖完整性断言在接线后即
     红，缺此行——stil 同款挂账）；
  3. 叶数锚 +2：本域两叶 parse/report（count_cli 口径=实注册叶子展开计
     数，+1 顶层 ibis-ami 组不计叶），test_check_numbers/test_cli 的 CLI
     计数锚由主代合流统一重钉；
  4. 注册序金快照重钉（append-only 注册序尾）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
本席测试经 ``ibis_ami_app`` 直连（CliRunner），零共享 app 污染、零金快照
漂移（自证测试钉住 cli.main 不导入本域——接线时该钉随接线一同移除；
模块 docstring 有接线清单原文）。

**撞名自查（2026-11-08 全 CLI 树 grep）**：既有 ibis 域（cli/domains/
ibis.py，Q-X46）顶层组名=无连字符的 ``ibis``；本域组名 ``ibis-ami`` 带
连字符，命令面不同名零撞（全树 grep ``ibis-ami``/``ibis_ami`` 零既有
命中；唯一近名=ibis 域本身，组名不冲突、注册序互不影响）。单源=
core/ibis_ami_parser+service/ibis_ami_service。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

ibis_ami_app = typer.Typer(
    help="IBIS-AMI (.ami) 参数文件解析（IBIS 7.0 只读面：Reserved 保留参数"
         "字典+必备键缺失清单、Model_Specific 五键逐参+type 分派+in-bounds "
         "开闭区间结构化、DLL/SoC 引用登记）")


@ibis_ami_app.command("parse")
def ibis_ami_parse_cmd(
    file: str = typer.Option(..., "--file", "-f", help="AMI 参数文件路径（.ami）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 AMI 参数文件（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.ibis_ami_service import (
        parse_ibis_ami_file,  # lazy: 叶内延迟导入（Q-X86）
    )

    result = parse_ibis_ami_file(str(file))
    _emit(result, "AMI 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ AMI: {escape(str(result.get('path')))}[/green]"
        f"  ami_version={escape(str(result.get('ami_version') or '-'))}"
        f"  reserved={stats.get('n_reserved')}"
        f"  params={stats.get('n_model_specific')}"
        f"  dll_refs={stats.get('n_dll_refs')}"
        f"  missing={stats.get('n_missing_reserved')}"
        f"  warnings={stats.get('n_warnings')}")
    for name, rec in (result.get("model_specific") or {}).items():
        default_raw = rec.get("default_raw")
        typed = rec.get("default_typed")
        typed_s = "-" if typed is None else str(typed)
        console.print(
            f"  参数 [bold]{escape(str(name))}[/bold]"
            f"  type={escape(str(rec.get('type') or '-'))}"
            f"  default={escape(str(default_raw if default_raw is not None else '-'))}"
            f"  typed={escape(typed_s)}"
            f"  bounds={escape(str(rec.get('bounds_raw') or '-'))}")
    for missing in result.get("missing_reserved") or []:
        console.print(
            f"  [yellow]! 缺必备保留键 {escape(str(missing))}[/yellow]")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@ibis_ami_app.command("report")
def ibis_ami_report_cmd(
    file: str = typer.Option(..., "--file", "-f", help="AMI 参数文件路径（.ami）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """AMI 统计报告（逐保留参数行+逐参数行+DLL/SoC 引用+缺失清单）。"""
    from rfauto.service.ibis_ami_service import (
        ibis_ami_report,  # lazy: 叶内延迟导入（Q-X86）
    )

    result = ibis_ami_report(str(file))
    _emit(result, "AMI 报告失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    console.print(
        f"[green]✓ AMI 报告: {escape(str(result.get('path')))}[/green]"
        f"  ami_version={escape(str(result.get('ami_version') or '-'))}"
        f"  reserved={stats.get('n_reserved')}"
        f"  params={stats.get('n_model_specific')}"
        f"  dll_refs={stats.get('n_dll_refs')}"
        f"  missing={stats.get('n_missing_reserved')}")
    for row in result.get("reserved_rows") or []:
        console.print(
            f"  保留 [bold]{escape(str(row.get('name')))}[/bold]"
            f" = {escape(str(row.get('value')))}")
    for row in result.get("model_rows") or []:
        console.print(
            f"  参数 [bold]{escape(str(row.get('name')))}[/bold]"
            f"  type={escape(str(row.get('type') or '-'))}"
            f"  default={escape(str(row.get('default_raw') or '-'))}"
            f"  bounds={escape(str(row.get('bounds_raw') or '-'))}")
    for key, val in (result.get("dll_refs") or {}).items():
        console.print(
            f"  引用 [bold]{escape(str(key))}[/bold]"
            f" = {escape(str(val if val is not None else '-'))}")
    for missing in result.get("missing_reserved") or []:
        console.print(
            f"  [yellow]! 缺必备保留键 {escape(str(missing))}[/yellow]")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")
