"""stdf 子应用——STDF（Standard Test Data Format，Teradyne 公开规范 V4）
半导体 ATE 产线测试记录结构子集解析 CLI 薄壳（aurora_q 席位 Q-X88，
2026-11-08）。

零逻辑转发 service/stdf_service（单源；规则 4 薄壳）；记录流状态机、
FAR 字节序自描述、MIR 链读、PTR/FTR/PIR/PRR 深解与查询三函数全在
core/stdf_parser 确定性内核（铁律 7）：
  rfauto stdf parse --file <file.stdf> [--json]
  rfauto stdf report --file <file.stdf> [--json]

parse 缺省紧凑输出（FAR 行+MIR lot/part 行+记录计数行+yield 两口径
行+告警）；report 缺省紧凑输出（far 摘要+yield+fail parts 逐行+统计
+截断态披露）；--json 恒全结构信封（成功/失败路径都走 print_json，
失败同构信封 #ge1㉙ 家法）。--json 是纯旗标（无配置/env 回落语义
——#277 三态不适用，bsdl/gdsii 同款 bool=False）；--file 注解 str
（B008 家法）。纯只读：不落盘、零网络、零真机。

**注册形态说明（合流契约——bsdl/citi/gdsii/stil 域同款）**：本模块
自带独立 typer 根 ``stdf_app``（**不**在模块级 add_typer 到共享
app——tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli() 锚均为冻结面，Q-X88 禁改；先接线后重锚是主代理显式评审
动作）。合流接线清单：
  1. main.py 追加 re-export + add_typer（vendor_docs/citi/gdsii/stil
     同款）::
         from rfauto.cli.domains.stdf import stdf_app as stdf_app
         from rfauto.cli.domains._core import app as _stdf_reg_app  # noqa
         _stdf_reg_app.add_typer(stdf_app, name="stdf")
  2. cli/help_groups.py HELP_PANEL_OF 补一行：``"stdf": "分析与研究"``
     （test_aurora_n_wave_ui_c 的 HELP_PANEL_OF 覆盖完整性断言在接线
     后即红，缺此行——bsdl/stil/vcd 同款挂账）；
  3. 叶数锚 +2：本域两叶 parse/report（count_cli 口径=实注册叶子展开
     计数，+1 顶层 stdf 组不计叶），test_check_numbers/test_cli 的
     CLI 计数锚由主代合流统一重钉；
  4. 注册序金快照重钉（append-only 注册序尾）::
         .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
本席测试经 ``stdf_app`` 直连（CliRunner），零共享 app 污染、零金快
照漂移（自证测试钉住 cli.main 不导入本域——接线时该钉随接线一同移
除；顶层无同名 `stdf` 域——零撞名自查 2026-11-08：全 CLI 树零 stdf
前缀组/命令，单源=core/stdf_parser+service/stdf_service）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

stdf_app = typer.Typer(
    help="STDF 产线测试数据解析（Teradyne V4 只读面：FAR 字节序自描述/"
         "MIR 摘要/PIR-PRR 器件/PTR-FTR 测试两记录面/良率两口径+查询）")


@stdf_app.command("parse")
def stdf_parse_cmd(
    file: str = typer.Option(..., "--file", "-f", help="STDF 文件路径（.stdf）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 STDF（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.stdf_service import (
        parse_stdf_file,  # lazy: 叶内延迟导入（Q-X88）
    )

    result = parse_stdf_file(str(file))
    _emit(result, "STDF 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    counts = result.get("counts") or {}
    trunc = "  [yellow]截断[/yellow]" if result.get("truncated") else ""
    console.print(
        f"[green]✓ STDF: {escape(str(result.get('path')))}[/green]"
        f"  cpu_type={escape(str((result.get('far') or {}).get('cpu_type')))}"
        f"  stdf_ver={escape(str((result.get('far') or {}).get('stdf_ver')))}"
        f"  records={stats.get('n_records_total')}{trunc}")
    mir = result.get("mir_summary") or {}
    console.print(
        f"  MIR lot={escape(str(mir.get('lot_id')))}"
        f"  part={escape(str(mir.get('part_typ')))}"
        f"  oper={escape(str(mir.get('oper_nam')))}"
        f"  mode={escape(str(mir.get('mode_cod')))}")
    console.print(
        f"  记录: pir={counts.get('n_pir')}  prr={counts.get('n_prr')}"
        f"  ptr={counts.get('n_ptr')}  ftr={counts.get('n_ftr')}"
        f"  pcr={counts.get('n_pcr')}  atr={counts.get('n_atr')}"
        f"  unknown={stats.get('n_unknown_skipped')}")
    console.print(
        f"  器件: parts={stats.get('n_parts')}"
        f"  passed={stats.get('n_parts_passed')}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@stdf_app.command("report")
def stdf_report_cmd(
    file: str = typer.Option(..., "--file", "-f", help="STDF 文件路径（.stdf）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """STDF 盘点报告（良率两口径+fail parts+记录计数+截断态）。"""
    from rfauto.service.stdf_service import (
        stdf_report,  # lazy: 叶内延迟导入（Q-X88）
    )

    result = stdf_report(str(file))
    _emit(result, "STDF 报告失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats") or {}
    ys = result.get("yield_stats") or {}
    console.print(
        f"[green]✓ STDF 报告: {escape(str(result.get('path')))}[/green]"
        f"  lot={escape(str(result.get('lot_id')))}"
        f"  part={escape(str(result.get('part_typ')))}")
    src = ys.get("source") or "-"
    ratio = ys.get("yield_ratio")
    ratio_s = f"{ratio:.4f}" if isinstance(ratio, (int, float)) else "-"
    console.print(
        f"  良率[{escape(str(src))}]  parts={ys.get('n_parts')}"
        f"  passed={ys.get('n_passed')}"
        f"  undecided={ys.get('n_undecided')}"
        f"  yield={ratio_s}")
    fail_parts = result.get("fail_parts") or []
    console.print(f"  fail parts: {len(fail_parts)}")
    for part in fail_parts[:20]:
        console.print(
            f"    - {escape(str(part.get('part_id')))}"
            f"  head/site={part.get('head_num')}/{part.get('site_num')}"
            f"  hard_bin={part.get('hard_bin')}  soft_bin={part.get('soft_bin')}")
    counts = result.get("counts") or {}
    console.print(
        f"  记录: ptr={counts.get('n_ptr')}  ftr={counts.get('n_ftr')}"
        f"  prr={counts.get('n_prr')}  pcr={counts.get('n_pcr')}"
        f"  unknown={stats.get('n_unknown_skipped')}"
        f"  warnings={stats.get('n_warnings')}")
    if result.get("truncated"):
        console.print("  [yellow]! 流截断（已收面如实保留）[/yellow]")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")
