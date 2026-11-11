"""liberty 子应用——Liberty (.lib) 时序库结构化解析 CLI 薄壳（T-Q34 席位
Q-X34，aurora_q 数字自动化借鉴方向）。

零逻辑转发 service/liberty_service（单源；规则 4 薄壳）；数值面全在
core/liberty_parser 确定性内核（NLDM 查找表+双线性插值，铁律 7）：
  rfauto liberty parse <file.lib> [--cell 名称] [--pin 名称] [--timing] [--power] [--json]
  rfauto liberty list <file.lib> [--json]

缺省紧凑输出（pin 元数据+计数）；--timing/--power 展开 timing 查找表/
功率面（--json 下全结构）。--pin 必须配合 --cell（pin 属于 cell，跨
cell 扫描同名歧义——usage 类错误 exit 2 信封）。

注册=域内自注册（dag/loop/anim/vendor-docs 同款：模块级 add_typer，
main.py 只 re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；
顶层无同名 `liberty` 域（零撞名自查 2026-11-07：全 CLI 树零 liberty
前缀组/命令，core/liberty_parser 单源在 core 不上 CLI 面）。不落盘、
零网络、零真机（纯读面）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

liberty_app = typer.Typer(
    help="Liberty (.lib) 时序库结构化解析（cells/pins/timing 查找表/功率）")
app.add_typer(liberty_app, name="liberty")

_TIMING_KEYS = ("cell_rise", "cell_fall", "rise_transition", "fall_transition")


@liberty_app.command("parse")
def liberty_parse_cmd(
    file: str = typer.Argument(..., help="Liberty 文件路径（.lib）"),
    cell: str | None = typer.Option(None, "--cell", help="只看指定 cell"),
    pin: str | None = typer.Option(None, "--pin", help="只看 cell 内指定 pin（须配合 --cell）"),
    timing: bool = typer.Option(
        False, "--timing", help="展开 timing 查找表（cell_rise/cell_fall/rise_transition/fall_transition）"),
    power: bool = typer.Option(
        False, "--power", help="展开功率面（internal_power/leakage_power）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 Liberty 库（NLDM 查找表/功率/工况/模板，缺省紧凑面）。"""
    from rfauto.service.liberty_service import parse_liberty_file  # lazy: 叶内延迟导入（Q-X34）

    if pin is not None and cell is None:
        _emit_usage_error("--pin 须配合 --cell（pin 属于某个 cell）",
                          json_output=json_output)
    result = parse_liberty_file(
        file, cell=cell, pin=pin, include_timing=timing, include_power=power)
    _emit(result, "Liberty 解析失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓ Liberty: {result.get('library')}"
        f"[/green]  file_version={result.get('file_version')}"
        f"  cells={result.get('stats', {}).get('n_cells')}"
        f"  pins={result.get('stats', {}).get('n_pins')}")
    for cname, centry in result.get("cells", {}).items():
        n_tg = sum(len(p.get("timing", {})) for p in centry.get("pins", {}).values())
        n_pg = sum(len(p.get("internal_power", []))
                   for p in centry.get("pins", {}).values())
        n_lk = len(centry.get("leakage_power") or [])
        console.print(
            f"  {cname}  area={centry.get('area')}  pins={len(centry.get('pins', {}))}"
            f"  timing_groups={n_tg}  power_groups={n_pg}  leakage_groups={n_lk}")
        for pname, pentry in centry.get("pins", {}).items():
            fn = pentry.get("function")
            console.print(
                f"    {pname}  direction={pentry.get('direction')}"
                f"  function={fn if fn is not None else '-'}"
                f"  cap={pentry.get('capacitance')}")
            for tkey, tentry in pentry.get("timing", {}).items():
                n_tables = sum(1 for k in _TIMING_KEYS if tentry.get(k) is not None)
                console.print(
                    f"      timing {tkey}  sense={tentry.get('timing_sense')}"
                    f"  type={tentry.get('timing_type')}  tables={n_tables}")
            if power:
                for ientry in pentry.get("internal_power", []):
                    n_pt = sum(1 for k in ("rise_power", "fall_power", "power")
                               if ientry.get(k) is not None)
                    console.print(
                        f"      internal_power related_pin={ientry.get('related_pin')}"
                        f"  tables={n_pt}")
        if power:
            for lentry in centry.get("leakage_power", []):
                console.print(
                    f"    leakage_power value={lentry.get('value')}"
                    f"  when={lentry.get('when')}")


@liberty_app.command("list")
def liberty_list_cmd(
    file: str = typer.Argument(..., help="Liberty 文件路径（.lib）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """库清单（cell 名/面积/pin 数/表数+模板与工况名录，只读零写盘）。"""
    from rfauto.service.liberty_service import list_liberty_cells  # lazy: 叶内延迟导入（Q-X34）

    result = list_liberty_cells(file)
    _emit(result, "Liberty 清单失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats", {})
    console.print(
        f"[green]✓ {result.get('library')}[/green]"
        f"  file_version={result.get('file_version')}"
        f"  cells={stats.get('n_cells')}"
        f"  templates={stats.get('n_lu_templates')}"
        f"  operating_conditions={len(result.get('operating_condition_names', []))}")
    for row in result.get("cells", []):
        console.print(
            f"  {row.get('name')}  area={row.get('area')}  pins={row.get('n_pins')}"
            f"  timing_groups={row.get('n_timing_groups')}"
            f"  timing_tables={row.get('n_timing_tables')}"
            f"  power_groups={row.get('n_power_groups')}")
