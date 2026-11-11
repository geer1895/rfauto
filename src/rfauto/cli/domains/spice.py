"""spice 子应用——SPICE 网表深度解析 CLI 薄壳（Q-X33 aurora_q T-Q22）。

叶 parse（单叶——三格式统一深度解析用户出口）：service/spice_netlist_service
（包装 core/spice_netlist_parser 五维度纯函数）的 CLI 出口——

  rfauto spice parse <file> [--flavor auto] [--topology/--no-topology] [--json]

- 五维度统一 JSON 结构化输出 keys {elements, subckts, controls, models,
  topology}：元件实例（端口对+参数值+单位）/子电路层次树/控制语句（分析
  +扫描步进）/模型卡/拓扑（MNA 维度+节点双向图+孤立节点+接地归一）；
- ``--flavor`` auto=内容自动判定（显式 ngspice/hspice/spectre 覆盖启发
  式）；词表校验 usage 错 exit 2（_emit_usage_error #ge1㉙ 契约）；
- ``--topology`` 缺省开启（bool|None 三态——#277 typer 陷阱家法：普通
  bool flag 会把缺省当显式 False 透传），``--no-topology`` 跳过拓扑
  （summary 拓扑派生字段如实 None 非 0）。

零数值逻辑转发 service（规则 4）；带 ``--json``（信封契约：成功+失败
同构——usage 错 exit 2，service 信封失败 exit 1）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

spice_app = typer.Typer(
    help="SPICE 网表深度解析（ngspice/HSPICE/Spectre 三格式统一结构化；"
         "service/spice_netlist_service 薄壳）：parse=五维度解析"
         "（元件/子电路/控制语句/模型卡/拓扑）")
app.add_typer(spice_app, name="spice")


def _render_human(result: dict) -> None:
    """人读摘要分支（动态段一律 escape——markup 纪律）。"""
    summary = result.get("summary") or {}
    console.print(
        f"[bold]SPICE 网表解析[/bold]  flavor=[cyan]{escape(str(result.get('flavor')))}[/cyan]"
        f"  判定={('auto' if result.get('flavor_detected') else '显式')}"
        f"  path={escape(str(result.get('path')))}")
    title = result.get("title")
    if title:
        console.print(f"  标题: {escape(str(title))}")
    console.print(
        f"  元件 {summary.get('n_elements')}  子电路 {summary.get('n_subckts')}"
        f"  控制语句 {summary.get('n_controls')}  模型卡 {summary.get('n_models')}"
        f"  X 实例 {summary.get('n_x_instances')}")
    topo = result.get("topology")
    if topo is not None:
        console.print(
            f"  拓扑: 节点 {topo.get('n_nodes')}（非地 {topo.get('n_non_ground_nodes')}）"
            f"  MNA 维度 {topo.get('mna_size')}"
            f"  分支增广 {topo.get('n_branches')}"
            f"  孤立节点 {len(topo.get('isolated_nodes') or [])}")
    if result.get("structural_errors"):
        console.print(f"  [yellow]结构错误 {len(result['structural_errors'])} 条"
                      "（--json 看 structural_errors 明细）[/yellow]")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@spice_app.command("parse")
def spice_parse_cmd(
    netlist: str = typer.Argument(
        ..., help="网表文件路径（ngspice/HSPICE/Spectre 三格式；--flavor "
                  "auto 内容自动判定）"),
    flavor: str = typer.Option(
        "auto", "--flavor",
        help="网表方言: auto=内容启发式判定 / ngspice / hspice / spectre"
             "（显式给定覆盖判定）"),
    topology: bool | None = typer.Option(
        None, "--topology/--no-topology",
        help="拓扑提取开关（缺省开启：MNA 维度+节点双向图+孤立节点检测+"
             "子电路层次树；--no-topology 跳过，summary 拓扑字段如实 null）"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """SPICE 网表深度解析（三格式统一五维度结构化输出+拓扑摘要）。

    示例：rfauto spice parse deck.cir --json
          rfauto spice parse subckt.sp --flavor spectre --no-topology

    五维度 keys {elements, subckts, controls, models, topology}——元件
    实例（R/L/C/D/M/Q/J/E/F/G/H/K/X/V/I…+端口对+单位提取）/子电路定义
    与层次树/控制语句（.op/.tran/.ac/.dc/.sp/.noise/.four+扫描步进）/
    模型卡（type/level/params）/拓扑（MNA 维度=非地节点+V/E/H 分支增广、
    节点双向图、孤立节点检测、0/gnd/gnd! 接地归一）。解析不仿真；表达式
    参数保留原文不代入（fail-soft：结构错误进 structural_errors 不中断）。
    """
    from rfauto.service.spice_netlist_service import (  # lazy: run-path
        SPICE_FLAVORS,
        parse_netlist_file,
    )

    flavor_eff = str(flavor).strip().lower()
    if flavor_eff not in SPICE_FLAVORS:
        _emit_usage_error(
            f"--flavor {flavor!r} 不在词表 {list(SPICE_FLAVORS)}"
            "（auto/ngspice/hspice/spectre）",
            json_output=json_output)
        return
    include_topology = True if topology is None else bool(topology)
    result = parse_netlist_file(
        netlist, flavor_eff, include_topology=include_topology)
    if json_output:
        _emit(result, "SPICE 网表解析失败", json_output=True)
        return
    if not result.get("ok"):
        _emit(result, "SPICE 网表解析失败", json_output=False)
        return
    _render_human(result)
    raise typer.Exit(code=0)
