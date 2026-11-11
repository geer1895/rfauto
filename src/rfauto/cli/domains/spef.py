"""spef 子应用——SPEF（IEEE 1481 寄生交换格式）结构化解析 CLI 薄壳
（T-Q60 席位 Q-X60，aurora_q CAD 扩展/数字后端借鉴方向，2026-11-07）。

零逻辑转发 service/spef_service（单源；规则 4 薄壳）；SPEF 词法、
D_NET 段状态机、单位换算与拓扑派生全在 core/spef_parser 确定性内核
（铁律 7）：
  rfauto spef parse --file <file.spef> [--json]
  rfauto spef report --file <file.spef> [--top-k N] [--json]

parse 缺省紧凑输出（汇总行+逐 net 计数）；report 缺省紧凑输出（逐 net
拓扑+耦合统计+top-k 最强耦合对）；--json 恒全结构信封（失败路径同构
信封，#ge1㉙ 契约）。纯只读：不落盘、零网络、零真机。

注册=域内自注册（sdc/liberty/spice/verilog 同款：模块级 add_typer，
main.py 只 re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；
顶层无同名 `spef` 域（零撞名自查 2026-11-07：全仓零 spef/SPEF 引用；
单源=core/spef_parser+service/spef_service）。

**接线待合流**：本席禁改 cli/main.py（Q-X57/58/59 在飞接线面，P1-4
教训后既定协议）——main.py 的 re-export 导入行由主代合流统一补齐；
本席自测走局部父 Typer（tests/unit/test_spef_parser.py）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

spef_app = typer.Typer(
    help="SPEF 寄生交换格式解析（IEEE 1481 寄生网络只读面：头部/NAME_MAP/"
         "PORTS/D_NET 四段+拓扑与耦合统计）")
app.add_typer(spef_app, name="spef")


def _fmt_far(value: float | None) -> str:
    """法拉值紧凑显示（None 如实连字符）。"""
    return "-" if value is None else f"{value:.4g}F"


@spef_app.command("parse")
def spef_parse_cmd(
    file: str = typer.Option(..., "--file", "-f", help="SPEF 文件路径（.spef）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 SPEF（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.spef_service import (
        parse_spef_file,  # lazy: 叶内延迟导入（Q-X60）
    )

    result = parse_spef_file(str(file))
    _emit(result, "SPEF 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats", {})
    header = result.get("header") or {}
    console.print(
        f"[green]✓ SPEF: {escape(str(result.get('path')))}[/green]"
        f"  design={escape(str(header.get('design')))}"
        f"  nets={stats.get('n_nets')}"
        f"  ports={stats.get('n_ports')}"
        f"  name_map={stats.get('n_name_map')}"
        f"  warnings={stats.get('n_warnings')}")
    for net in result.get("nets") or []:
        rel = net.get("cap_rel_diff")
        rel_s = "-" if rel is None else f"{rel:+.3g}"
        console.print(
            f"  [bold]{escape(str(net.get('name')))}[/bold]"
            f"  conn={len(net.get('conn') or [])}"
            f"  cap_gnd={len(net.get('caps_gnd') or [])}"
            f"  cap_cpl={len(net.get('caps_cpl') or [])}"
            f"  res={net.get('res_count')}"
            f"  ind={net.get('ind_count')}"
            f"  total={_fmt_far(net.get('total_cap_far'))}"
            f"  sum={_fmt_far(net.get('cap_sum_far'))}"
            f"  rel_diff={rel_s}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@spef_app.command("report")
def spef_report_cmd(
    file: str = typer.Option(..., "--file", "-f", help="SPEF 文件路径（.spef）"),
    top_k: int = typer.Option(
        5, "--top-k", "-k", help="最强耦合对显示条数（缺省 5）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """SPEF 拓扑与耦合统计报告（逐 net 连通分量/孤立节点+耦合 top-k）。"""
    from rfauto.service.spef_service import (
        spef_report,  # lazy: 叶内延迟导入（Q-X60）
    )

    result = spef_report(str(file), top_k=top_k)
    _emit(result, "SPEF 报告失败", json_output=json_output)
    if json_output:
        return
    topo = result.get("topology") or {}
    totals = topo.get("totals") or {}
    console.print(
        f"[green]✓ SPEF 报告: {escape(str(result.get('path')))}[/green]"
        f"  design={escape(str(result.get('design')))}"
        f"  nets={totals.get('n_nets')}"
        f"  nodes={totals.get('n_nodes')}"
        f"  elements={totals.get('n_elements')}"
        f"  components={totals.get('n_components')}"
        f"  isolated={totals.get('n_isolated')}")
    for net in topo.get("nets") or []:
        iso = net.get("isolated_nodes") or []
        iso_s = escape(", ".join(iso)) if iso else "无"
        console.print(
            f"  [bold]{escape(str(net.get('name')))}[/bold]"
            f"  nodes={net.get('node_count')}"
            f"  elements={net.get('element_count')}"
            f"  components={net.get('component_count')}"
            f"  孤立节点: {iso_s}")
    cpl = result.get("coupling") or {}
    ratio = cpl.get("coupling_to_ground_ratio")
    ratio_s = "-" if ratio is None else f"{ratio:.4g}"
    console.print(
        f"  耦合: n_cpl={cpl.get('n_coupling')}"
        f"  n_gnd={cpl.get('n_ground')}"
        f"  cpl_sum={_fmt_far(cpl.get('coupling_sum_far'))}"
        f"  gnd_sum={_fmt_far(cpl.get('ground_sum_far'))}"
        f"  cpl/gnd={ratio_s}")
    for rank, pair in enumerate(cpl.get("top_pairs") or [], start=1):
        console.print(
            f"    #{rank} {escape(str(pair.get('net')))}:"
            f" {escape(str(pair.get('node1')))}"
            f" ↔ {escape(str(pair.get('node2')))}"
            f"  {_fmt_far(pair.get('value_far'))}")
