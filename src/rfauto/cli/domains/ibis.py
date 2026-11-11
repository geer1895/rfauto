"""ibis 子应用——IBIS (.ibs) IO buffer 模型结构化解析 CLI 薄壳（aurora_q
Q-X46 席位，数字自动化借鉴方向）。

零逻辑转发 service/ibis_service（单源；规则 4 薄壳）；数值面全在
core/ibis_parser 确定性内核（IV 查找表 Voltage→Current/暂态表
time→voltage+线性插值，铁律 7）：
  rfauto ibis parse <file.ibs> [--component 名称] [--model 名称] [--tables] [--json]
  rfauto ibis list <file.ibs> [--json]

缺省紧凑输出（模型/引脚元数据+表计数）；--tables 展开查找表体（IV 表/
暂态表/Ramp；--json 下全结构信封恒含 filters 声明）。--component/
--model 过滤未知名走 service error 信封（exit 1，附可用清单）。

注册=域内自注册（skill/sdc 同款：模块级 add_typer，main.py 只
re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
`ibis` 域（零撞名自查 2026-11-07：全 CLI 树零 ibis 前缀组/命令，唯一
近名 liberty/spice 语义=其他 EDA 格式解析面）。不落盘、零网络、零真机
（纯读面）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

ibis_app = typer.Typer(
    help="IBIS (.ibs) IO buffer 模型结构化解析（IV 查找表/暂态表/引脚）")
app.add_typer(ibis_app, name="ibis")


def _fmt_triple(v: object) -> str:
    """typ/min/max 三列紧凑渲染（缺列/标量如实 '-'）。"""
    if isinstance(v, dict) and {"typ", "min", "max"} <= set(v):
        return f"{v['typ']:g}/{v['min']:g}/{v['max']:g}"
    if isinstance(v, (int, float)):
        return f"{v:g}"
    return "-"


def _fmt_opt(v: object) -> str:
    """可缺数量渲染（None → '-'）。"""
    return f"{v:g}" if isinstance(v, (int, float)) else "-"


@ibis_app.command("parse")
def ibis_parse_cmd(
    file: str = typer.Argument(..., help="IBIS 文件路径（.ibs）"),
    component: str | None = typer.Option(None, "--component", help="只看指定 component"),
    model: str | None = typer.Option(None, "--model", help="只看指定 model"),
    tables: bool = typer.Option(
        False, "--tables", help="展开查找表体（IV 表/暂态表/Ramp）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """结构化解析 IBIS 模型（缺省紧凑面：表计数在、表体不在）。"""
    from rfauto.service.ibis_service import parse_ibis_file  # lazy: 叶内延迟导入（Q-X46）

    result = parse_ibis_file(
        file, component=component, model=model, include_tables=tables)
    _emit(result, "IBIS 解析失败", json_output=json_output)
    if json_output:
        return
    header = result.get("header", {})
    stats = result.get("stats", {})
    console.print(
        f"[green]✓ IBIS: {header.get('file_name', '-')}[/green]"
        f"  ibis_ver={header.get('ibis_ver', '-')}"
        f"  components={stats.get('n_components')}"
        f"  pins={stats.get('n_pins')}"
        f"  models={stats.get('n_models')}"
        f"  selectors={stats.get('n_model_selectors')}")
    for centry in result.get("components", []):
        pkg = centry.get("package") or {}
        console.print(
            f"  {centry.get('name')}  mfr={centry.get('manufacturer') or '-'}"
            f"  R_pkg={_fmt_triple(pkg.get('r_pkg'))}"
            f"  L_pkg={_fmt_triple(pkg.get('l_pkg'))}"
            f"  C_pkg={_fmt_triple(pkg.get('c_pkg'))}"
            f"  pins={len(centry.get('pins', []))}")
        for p in centry.get("pins", []):
            console.print(
                f"    {p.get('pin')}  {p.get('signal')}"
                f"  model={p.get('model') or '-'}"
                f"  R/L/C={_fmt_opt(p.get('r_pin'))}/"
                f"{_fmt_opt(p.get('l_pin'))}/{_fmt_opt(p.get('c_pin'))}")
    for mname, mentry in result.get("models", {}).items():
        tb = mentry.get("tables") or {}
        tnames = [k for k, v in tb.items() if v is not None]
        wfs = mentry.get("waveforms", [])
        console.print(
            f"  {mname}  type={mentry.get('model_type')}"
            f"  vinl={_fmt_opt(mentry.get('vinl'))}"
            f"  vinh={_fmt_opt(mentry.get('vinh'))}"
            f"  tables={','.join(tnames) or '-'}"
            f"  waveforms={len(wfs)}"
            f"  ramp={'Y' if mentry.get('ramp') is not None else '-'}")
        if tables:
            for k in tnames:
                console.print(
                    f"      {k}  rows={tb[k].get('n_rows')}")
            for wentry in wfs:
                console.print(
                    f"      {wentry.get('kind')}"
                    f"  rows={wentry.get('n_rows')}"
                    f"  v_fixture={_fmt_opt(wentry.get('v_fixture'))}")


@ibis_app.command("list")
def ibis_list_cmd(
    file: str = typer.Argument(..., help="IBIS 文件路径（.ibs）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """清单（component/model 名录+表计数+选择器名录，只读零写盘）。"""
    from rfauto.service.ibis_service import list_ibis_inventory  # lazy: 叶内延迟导入（Q-X46）

    result = list_ibis_inventory(file)
    _emit(result, "IBIS 清单失败", json_output=json_output)
    if json_output:
        return
    stats = result.get("stats", {})
    console.print(
        f"[green]✓ IBIS: {result.get('header', {}).get('file_name', '-')}[/green]"
        f"  components={stats.get('n_components')}"
        f"  models={stats.get('n_models')}"
        f"  selectors={stats.get('n_model_selectors')}"
        f"  table_rows={stats.get('n_table_rows')}")
    for row in result.get("components", []):
        console.print(
            f"  component {row.get('name')}"
            f"  mfr={row.get('manufacturer') or '-'}"
            f"  pins={row.get('n_pins')}")
    for row in result.get("models", []):
        console.print(
            f"  model {row.get('name')}  type={row.get('model_type')}"
            f"  tables={','.join(row.get('table_names') or []) or '-'}"
            f"  waveforms={row.get('n_waveforms')}"
            f"  rows={row.get('n_table_rows')}"
            f"  ramp={'Y' if row.get('has_ramp') else '-'}")
    for sel in result.get("model_selector_names", []):
        console.print(f"  selector {sel}")
