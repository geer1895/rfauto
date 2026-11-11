"""sdc 子应用——SDC（Synopsys Design Constraints）结构化解析 CLI 薄壳
（T-Q36 席位 Q-X36，aurora_q 数字自动化借鉴方向，2026-11-07）。

零逻辑转发 service/sdc_service（单源；规则 4 薄壳）；Tcl 词法与 SDC
命令语义全在 core/sdc_parser 确定性内核（铁律 7）：
  rfauto sdc parse <file.sdc> [--clocks] [--timing] [--paths] [--constraints] [--json]
  rfauto sdc list <file.sdc> [--json]

缺省紧凑输出（汇总行+计数）；--clocks/--timing/--paths/--constraints
在 human 分支展开对应节（--json 恒全结构信封）。纯只读：不落盘、
零网络、零真机。

注册=域内自注册（dag/loop/anim/vendor-docs/liberty 同款：模块级
add_typer，main.py 只 re-export，二次 add_typer 会双注册打红
zero-shadow 钉）；顶层无同名 `sdc` 域（零撞名自查 2026-11-07：全 CLI
树零 sdc 前缀组/命令，唯一近名是 knowledge 术语表的 Sdc 混模 S 参数
词条，语义无关；单源=core/sdc_parser+service/sdc_service）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

sdc_app = typer.Typer(
    help="SDC（Synopsys Design Constraints）约束结构化解析（时钟/IO 延迟/"
         "路径例外/负载驱动，Tcl 语法子集只读面）")
app.add_typer(sdc_app, name="sdc")


def _fmt_obj(obj: dict | None) -> str:
    """对象引用 spec → 单行人读串（patterns 逗号连；空如实连字符）。"""
    if not obj:
        return "-"
    patterns = obj.get("patterns") or []
    if patterns:
        return escape(", ".join(str(p) for p in patterns))
    return escape(str(obj.get("raw") or "-"))


def _render_clocks(clocks: list) -> None:
    console.print("[bold]clocks[/bold]")
    for clock in clocks:
        period = clock.get("period")
        period_s = "-" if period is None else str(period)
        wave = clock.get("waveform") or []
        wave_s = ",".join(str(v) for v in wave) if wave else "-"
        auto = " auto_named" if clock.get("auto_named") else ""
        console.print(
            f"  {escape(str(clock.get('name')))}  kind={clock.get('kind')}"
            f"{auto}  period={escape(period_s)}  waveform={escape(wave_s)}")
        src = clock.get("sources")
        if isinstance(src, dict) and src.get("patterns"):
            console.print(f"    sources: {_fmt_obj(src)}")
        if clock.get("kind") == "generated":
            gen_bits = []
            if clock.get("divide_by") is not None:
                gen_bits.append(f"divide_by={clock.get('divide_by')}")
            if clock.get("multiply_by") is not None:
                gen_bits.append(f"multiply_by={clock.get('multiply_by')}")
            if clock.get("master_clock"):
                gen_bits.append(
                    f"master={escape(str(clock.get('master_clock')))}")
            if clock.get("edges"):
                gen_bits.append(f"edges={clock.get('edges')}")
            console.print("    " + "  ".join(gen_bits))


def _render_delays(delays: list) -> None:
    console.print("[bold]delays（IO 延迟）[/bold]")
    for d in delays:
        bound_bits = []
        if d.get("max"):
            bound_bits.append("max")
        if d.get("min"):
            bound_bits.append("min")
        clock = d.get("clock") or "-"
        value = d.get("value")
        value_s = "-" if value is None else str(value)
        console.print(
            f"  {escape(str(d.get('type')))}  value={escape(value_s)}"
            f"  bound={'+'.join(bound_bits) or '-'}"
            f"  clock={escape(str(clock))}  ports={_fmt_obj(d.get('from'))}")


def _render_paths(paths: list) -> None:
    console.print("[bold]paths（路径例外）[/bold]")
    for p in paths:
        value = p.get("value")
        value_s = "-" if value is None else str(value)
        mods = " ".join(m for m in ("setup", "hold") if p.get(m))
        head = (f"  {escape(str(p.get('type')))}  value={escape(value_s)}"
                + (f"  {mods}" if mods else ""))
        console.print(
            head + f"  from={_fmt_obj(p.get('from'))}"
                   f"  through={_fmt_obj(p.get('through'))}"
                   f"  to={_fmt_obj(p.get('to'))}")


def _render_constraints(cons: dict) -> None:
    console.print("[bold]constraints（负载/驱动/扇出/案例/时钟网络）[/bold]")
    for load in cons.get("loads") or []:
        bits = []
        if load.get("capacitance") is not None:
            bits.append(f"cap={load.get('capacitance')}")
        if load.get("pin_count") is not None:
            bits.append(f"pins={load.get('pin_count')}")
        console.print(
            f"  load  {' '.join(bits) or '-'}"
            f"  objects={_fmt_obj(load.get('objects'))}")
    for cell in cons.get("driving_cells") or []:
        console.print(
            f"  driving_cell  lib_cell={escape(str(cell.get('lib_cell')))}"
            f"  pin={escape(str(cell.get('pin')))}"
            f"  objects={_fmt_obj(cell.get('objects'))}")
    for fanout in cons.get("fanout_loads") or []:
        console.print(
            f"  fanout_load  value={fanout.get('value')}"
            f"  objects={_fmt_obj(fanout.get('objects'))}")
    for case in cons.get("case_analyses") or []:
        console.print(
            f"  case_analysis  value={escape(str(case.get('value')))}"
            f"  objects={_fmt_obj(case.get('objects'))}")
    for mc in cons.get("multicycles") or []:
        ref = mc.get("reference") or "-"
        console.print(
            f"  multicycle  multiplier={mc.get('multiplier')}"
            f"  ref={escape(str(ref))}"
            f"  from={_fmt_obj(mc.get('from'))}"
            f"  to={_fmt_obj(mc.get('to'))}")
    for lat in cons.get("clock_latency") or []:
        src = " -source" if lat.get("source") else ""
        console.print(
            f"  clock_latency  value={lat.get('value')}{src}"
            f"  objects={_fmt_obj(lat.get('objects'))}")
    for unc in cons.get("clock_uncertainty") or []:
        mods = " ".join(m for m in ("setup", "hold") if unc.get(m))
        console.print(
            f"  clock_uncertainty  value={unc.get('value')}"
            f"  {mods}  objects={_fmt_obj(unc.get('objects'))}")


@sdc_app.command("parse")
def sdc_parse_cmd(
    file: str = typer.Argument(..., help="SDC 约束文件路径（Tcl 语法子集）"),
    clocks: bool = typer.Option(
        False, "--clocks", help="human 分支展开 clocks 节（时钟定义）"),
    timing: bool = typer.Option(
        False, "--timing", help="human 分支展开 delays 节（IO 延迟）"),
    paths: bool = typer.Option(
        False, "--paths", help="human 分支展开 paths 节（路径例外）"),
    constraints: bool = typer.Option(
        False, "--constraints",
        help="human 分支展开 constraints 节（负载/驱动/扇出/案例/时钟网络）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 SDC 约束（缺省紧凑汇总；--json 恒全结构信封）。"""
    from rfauto.service.sdc_service import parse_sdc_file  # lazy: 叶内延迟导入（Q-X36）

    result = parse_sdc_file(file)
    _emit(result, "SDC 解析失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats", {})
    console.print(
        f"[green]✓ SDC: {escape(str(result.get('path')))}[/green]"
        f"  commands={stats.get('n_commands')}"
        f"  clocks={stats.get('n_clocks')}"
        f"  delays={stats.get('n_delays')}"
        f"  paths={stats.get('n_paths')}"
        f"  warnings={stats.get('n_warnings')}")
    if clocks:
        _render_clocks(result.get("clocks") or [])
    if timing:
        _render_delays(result.get("delays") or [])
    if paths:
        _render_paths(result.get("paths") or [])
    if constraints:
        _render_constraints(result.get("constraints") or {})
    for warn in result.get("warnings") or []:
        console.print(
            f"  [yellow]! 第 {warn.get('line')} 行 {escape(str(warn.get('name')))}:"
            f" {escape(str(warn.get('note')))}[/yellow]")


@sdc_app.command("list")
def sdc_list_cmd(
    file: str = typer.Argument(..., help="SDC 约束文件路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """SDC 清单（命令名录+计数、时钟名录、对象 pattern 计数，只读）。"""
    from rfauto.service.sdc_service import list_sdc_commands  # lazy: 叶内延迟导入（Q-X36）

    result = list_sdc_commands(file)
    _emit(result, "SDC 清单失败", json_output=json_output)
    if json_output:
        return
    counts = result.get("counts", {})
    console.print(
        f"[green]✓ SDC 清单: {escape(str(result.get('path')))}[/green]"
        f"  commands={counts.get('commands')}"
        f"  clocks={counts.get('clocks')}"
        f"  delays={counts.get('delays')}"
        f"  paths={counts.get('paths')}"
        f"  warnings={counts.get('warnings')}")
    for clock in result.get("clocks") or []:
        period = clock.get("period")
        period_s = "-" if period is None else str(period)
        console.print(
            f"  {escape(str(clock.get('name')))}  {clock.get('kind')}"
            f"  period={escape(period_s)}")
    inv = result.get("command_counts") or {}
    inv_s = "  ".join(
        f"{escape(name)}x{n}" for name, n in inv.items())
    if inv_s:
        console.print(f"  命令面: {inv_s}")
    obj_counts = result.get("object_counts") or {}
    obj_s = "  ".join(
        f"{escape(str(k))}={v}" for k, v in obj_counts.items() if v)
    if obj_s:
        console.print(f"  对象面: {obj_s}")
