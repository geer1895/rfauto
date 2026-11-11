"""vcd 子应用——VCD（Value Change Dump，IEEE 1364 附录）波形结构化解析
CLI 薄壳（aurora_q 席位 Q-X63，2026-11-08）。

零逻辑转发 service/vcd_service（单源；规则 4 薄壳）；VCD 词法、声明段
状态机、timescale 换算与查询派生全在 core/vcd_parser 确定性内核（铁律 7）：
  rfauto vcd parse --file <file.vcd> [--json]
  rfauto vcd report --file <file.vcd> [--top N] [--json]

parse 缺省紧凑输出（头部汇总行+逐信号事件计数+警告）；report 缺省紧凑
输出（头部+时间窗直方摘要+信号活跃度 top）；--json 恒全结构信封（失败
路径同构信封，#ge1㉙ 契约）。纯只读：不落盘、零网络、零真机。

注册=域内自注册（sdc/verilog/spef 同款：模块级 add_typer，main.py 只
re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
`vcd` 域（零撞名自查 2026-11-08：全仓零 vcd/VCD 引用；单源=core/
vcd_parser+service/vcd_service）。

**接线待合流（合流钉点清单——本席禁改 cli/main.py 与金快照/数字带）**：
  1. main.py 注册序尾追加 re-export 导入行（本域模块级 add_typer 已就位
     ——main.py 导入本模块即完成注册，spef 同款）::
         from rfauto.cli.domains.vcd import vcd_app as vcd_app
         from rfauto.cli.domains.vcd import vcd_parse_cmd as vcd_parse_cmd
         from rfauto.cli.domains.vcd import vcd_report_cmd as vcd_report_cmd
  2. cli/help_groups.py HELP_PANEL_OF 补一行：``"vcd": "分析与研究"``
     （本席挂账——test_aurora_n_wave_ui_c 的 HELP_PANEL_OF 覆盖完整性
     断言在接线后即红，缺此行）；
  3. 叶数锚 +2：本域两叶 parse/report（count_cli 口径实测 +2），
     test_check_numbers/test_cli 的 CLI 计数锚由主代合流统一重钉；
  4. 注册序金快照重钉：tests/gold/cli_registration_order.json 随合流批
     同帧 ``--write-gold`` 重生成（append-only 注册序尾）。
本席测试经 ``vcd_app`` 直连（CliRunner），零金快照漂移自证。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

vcd_app = typer.Typer(
    help="VCD 波形解析（IEEE 1364 Value Change Dump 只读面：声明段/"
         "scope 层次/信号事件流+活跃度与时间窗统计）")
app.add_typer(vcd_app, name="vcd")


@vcd_app.command("parse")
def vcd_parse_cmd(
    file: str = typer.Option(..., "--file", "-f", help="VCD 文件路径（.vcd）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 VCD（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.vcd_service import (
        parse_vcd_file,  # lazy: 叶内延迟导入（Q-X63）
    )

    result = parse_vcd_file(str(file))
    _emit(result, "VCD 解析失败", json_output=json_output)
    if json_output:
        return
    header = result.get("header") or {}
    stats = result.get("stats") or {}
    ts_raw = header.get("timescale_raw")
    ts_s = header.get("timescale_factor_s")
    ts_s_s = "-" if ts_s is None else f"{ts_s:.4g}s"
    console.print(
        f"[green]✓ VCD: {escape(str(result.get('path')))}[/green]"
        f"  timescale={escape(str(ts_raw))}（{ts_s_s}）"
        f"  vars={stats.get('n_vars')}"
        f"  events={stats.get('n_events')}"
        f"  windows={stats.get('t_min')}..{stats.get('t_max')}"
        f"  warnings={stats.get('n_warnings')}")
    for vid, v in (result.get("vars") or {}).items():
        evs = (result.get("events") or {}).get(vid) or []
        console.print(
            f"  [bold]{escape(str(v.get('name')))}[/bold]"
            f"@{escape(str(v.get('scope_path')))}"
            f"  id={escape(str(vid))}"
            f"  {escape(str(v.get('type')))} w={v.get('width')}"
            f"  events={len(evs)}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@vcd_app.command("report")
def vcd_report_cmd(
    file: str = typer.Option(..., "--file", "-f", help="VCD 文件路径（.vcd）"),
    top: int = typer.Option(
        10, "--top", "-t", help="信号活跃度 top 条数（缺省 10，≥1）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """VCD 时间跨窗与信号活跃度报告（时间窗直方+top 活跃度聚合）。"""
    from rfauto.cli.domains._core import _emit_usage_error  # lazy: usage error 单源出口（cli 注册根轻载）
    from rfauto.service.arg_guard_service import (
        validate_count_args,  # lazy: 数量守卫（Q-W8-4 家法）
    )
    from rfauto.service.vcd_service import (
        vcd_report,  # lazy: 叶内延迟导入（Q-X63）
    )

    # R11 Top3 quantity 守卫铺广度（Q-W8-4 家法）：计数参数负/零显式拒绝。
    errs = validate_count_args({"--top": top})
    if errs:
        _emit_usage_error("; ".join(errs), json_output=json_output)
    result = vcd_report(str(file), top_n=top)
    _emit(result, "VCD 报告失败", json_output=json_output)
    if json_output:
        return
    header = result.get("header") or {}
    stats = result.get("stats") or {}
    windows = result.get("time_windows") or {}
    busiest = windows.get("busiest") or {}
    console.print(
        f"[green]✓ VCD 报告: {escape(str(result.get('path')))}[/green]"
        f"  timescale={escape(str(header.get('timescale_raw')))}"
        f"  vars={stats.get('n_vars')}"
        f"  events={stats.get('n_events')}"
        f"  span={stats.get('t_min')}..{stats.get('t_max')}")
    console.print(
        f"  时间窗 {windows.get('n_windows')} 个"
        f"  最繁忙 #{busiest.get('time')}（{busiest.get('n_events')} 事件）")
    for rank, row in enumerate(result.get("activity_top") or [], start=1):
        x_frac = row.get("x_fraction")
        x_s = "-" if x_frac is None else f"{x_frac:.2%}"
        console.print(
            f"  #{rank} [bold]{escape(str(row.get('name')))}[/bold]"
            f"@{escape(str(row.get('scope_path')))}"
            f"  id={escape(str(row.get('id')))}"
            f"  events={row.get('n_events')}"
            f"  x={x_s}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")
