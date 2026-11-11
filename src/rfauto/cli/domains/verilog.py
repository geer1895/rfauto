"""verilog 子应用——Verilog 网表结构化解析 CLI 薄壳
（T-Q47 席位 Q-X47，aurora_q 数字自动化借鉴方向，2026-11-07）。

零逻辑转发 service/verilog_netlist_service（单源；规则 4 薄壳）；
词法与 Verilog 结构语义全在 core/verilog_netlist_parser 确定性内核
（铁律 7）：
  rfauto verilog parse <file.v> [--module <name>] [--topology/--no-topology] [--json]
  rfauto verilog list <file.v> [--json]

parse 缺省紧凑输出（汇总行+逐模块计数）；--module 过滤到单模块视图；
--topology 缺省开启（bool|None 三态——#277 typer 陷阱家法：普通 bool
flag 会把缺省当显式 False 透传），--no-topology 跳过拓扑（信封
topology 字段如实 None 非 0）。纯只读：不落盘、零网络、零真机。

注册=域内自注册（sdc/liberty/spice 同款：模块级 add_typer，main.py
只 re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无
同名 `verilog` 域（零撞名自查 2026-11-07：全 CLI 树零 verilog 前缀
组/命令，唯一近名=fl1_sg13g2 脚本注释里"零 Verilog-A"语义无关；
单源=core/verilog_netlist_parser+service/verilog_netlist_service）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

verilog_app = typer.Typer(
    help="Verilog 网表结构化解析（数字后端网表只读面：module/port/"
         "wire/assign/实例/参数+拓扑三件套）")
app.add_typer(verilog_app, name="verilog")


def _render_module_counts(summary: dict) -> None:
    """单模块计数行（human 紧凑面复用；动态段一律 escape）。"""
    console.print(
        f"  {escape(str(summary.get('name')))}"
        f"  ports={summary.get('n_ports')}"
        f"  wires={summary.get('n_wires')}"
        f"  assigns={summary.get('n_assigns')}"
        f"  instances={summary.get('n_instances')}"
        f"  params={summary.get('n_parameters')}"
        f"  defparams={summary.get('n_defparams')}"
        f"  warnings={summary.get('n_warnings')}")


def _render_topology(topo: dict) -> None:
    """单模块拓扑 human 展开（--topology 旗标分支）。"""
    depth = topo.get("tree_depth") or {}
    depth_s = "-" if depth.get("depth") is None else str(depth.get("depth"))
    console.print(
        f"    拓扑: nets={topo.get('net_count')}"
        f"  edges={len(topo.get('instance_edges') or [])}"
        f"  depth={depth_s}"
        + ("  [yellow]cyclic[/yellow]" if depth.get("cyclic") else ""))
    orphans = topo.get("orphan_nets") or {}
    undriven = orphans.get("undriven") or []
    unloaded = orphans.get("unloaded") or []
    note = "（含行为块跳过盲区，嫌疑面非终判）" if topo.get("behavioral_skipped") else ""
    if undriven:
        console.print(
            f"      undriven: {escape(', '.join(undriven))}")
    if unloaded:
        console.print(
            f"      unloaded: {escape(', '.join(unloaded))}{note}")
    if not undriven and not unloaded:
        console.print("      孤立网: 无")


@verilog_app.command("parse")
def verilog_parse_cmd(
    file: str = typer.Argument(..., help="Verilog 网表文件路径（.v/.vh 结构子集）"),
    module: str | None = typer.Option(
        None, "--module", "-m",
        help="只看指定模块（单模块视图+单模块拓扑；缺省全文档）"),
    topology: bool | None = typer.Option(
        None, "--topology/--no-topology",
        help="拓扑三件套（三层关系/孤立网/树深度）；缺省开启"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 Verilog 网表（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.verilog_netlist_service import (
        parse_verilog_file,  # lazy: 叶内延迟导入（Q-X47）
        parse_verilog_module,
    )

    with_topology = True if topology is None else topology
    if module:
        result = parse_verilog_module(str(file), module,
                                      with_topology=with_topology)
    else:
        result = parse_verilog_file(str(file), with_topology=with_topology)
    _emit(result, "Verilog 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats", {})
    mod_note = f"  module={escape(str(result.get('module')))}" \
        if result.get("module") else ""
    console.print(
        f"[green]✓ Verilog: {escape(str(result.get('path')))}[/green]"
        f"  modules={stats.get('n_modules')}{mod_note}"
        f"  ports={stats.get('n_ports')}"
        f"  wires={stats.get('n_wires')}"
        f"  instances={stats.get('n_instances')}"
        f"  warnings={stats.get('n_warnings')}")
    top_modules = result.get("top_modules") or []
    if top_modules:
        console.print(
            f"  顶层候选: {escape(', '.join(top_modules))}")
    ext = result.get("external_instance_types") or []
    if ext:
        console.print(
            f"  外部单元类型: {escape(', '.join(ext))}")
    names = [result.get("module")] if result.get("module") \
        else (result.get("module_order") or [])
    topology = result.get("topology") or {}
    for name in names:
        body = (result.get("modules") or {}).get(name) or {}
        console.print(
            f"  [bold]{escape(str(name))}[/bold]"
            f"  ports={len(body.get('ports') or [])}"
            f"  wires={len(body.get('wires') or [])}"
            f"  assigns={len(body.get('assigns') or [])}"
            f"  instances={len(body.get('instances') or [])}"
            f"  params={len(body.get('parameters') or {})}")
        topo = topology.get(name)
        if topo is not None:
            _render_topology(topo)
    for warn in result.get("warnings") or []:
        console.print(
            f"  [yellow]! 第 {warn.get('line')} 行 {escape(str(warn.get('name')))}:"
            f" {escape(str(warn.get('note')))}[/yellow]")


@verilog_app.command("list")
def verilog_list_cmd(
    file: str = typer.Argument(..., help="Verilog 网表文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """Verilog 清单（模块名录+逐模块计数、顶层候选、实例化边，只读）。"""
    from rfauto.service.verilog_netlist_service import (
        list_verilog_modules,  # lazy: 叶内延迟导入（Q-X47）
    )

    result = list_verilog_modules(str(file))
    _emit(result, "Verilog 清单失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats", {})
    console.print(
        f"[green]✓ Verilog 清单: {escape(str(result.get('path')))}[/green]"
        f"  modules={stats.get('n_modules')}"
        f"  instances={stats.get('n_instances')}"
        f"  warnings={stats.get('n_warnings')}")
    top_modules = result.get("top_modules") or []
    if top_modules:
        console.print(f"  顶层候选: {escape(', '.join(top_modules))}")
    for summary in result.get("modules_summary") or []:
        _render_module_counts(summary)
    ext = result.get("external_instance_types") or []
    if ext:
        console.print(f"  外部单元类型: {escape(', '.join(ext))}")
    edges = result.get("instantiations") or []
    if edges:
        edge_s = "  ".join(
            f"{escape(str(e.get('parent')))}→{escape(str(e.get('child')))}"
            for e in edges[:12])
        more = f" …+{len(edges) - 12}" if len(edges) > 12 else ""
        console.print(f"  实例化边: {edge_s}{more}")
