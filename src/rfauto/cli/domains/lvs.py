"""lvs 子应用——LVS 网表对照 CLI 薄壳（Q-X49 aurora_q）。

叶 compare（单叶——两份网表拓扑一致性对照用户出口）：
service/lvs_compare_service（netgen 思想借鉴化用自研实现）的 CLI 出口——

  rfauto lvs compare <layout_netlist> <schematic_netlist>
      [--tolerance 0.01] [--rf/--no-rf] [--format auto] [--json]

- 两侧网表（SPICE 三格式/Verilog 门级子集）归一到统一图表示 → 图同构
  （1-WL 颜色精化 + 回溯）→ 元件清单（missing/extra）+ 同构映射下参数
  容差比对（mismatched）→ ``{verdict, score, differences, summary}``
  对照报告信封；
- ``--rf``：S 参数端口数量/序号/阻抗比对 + 传输线串联/并联/耦合线分类
  比对（结构性不齐=MISMATCH，阻抗出窗=PARTIAL）；
- verdict 退出码（LVS 拦截语义，与 layout lvs LVS_FLAG 同族）：
  MATCH=0 / PARTIAL=1 / MISMATCH=1（区分看信封 verdict；exit 2 保留
  usage 错 #ge1㉙ 契约）。

零数值逻辑转发 service（规则 4）；带 ``--json``（信封契约：成功+失败
同构——usage 错 exit 2，service 信封失败 exit 1）。
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

lvs_app = typer.Typer(
    help="LVS 网表对照（Layout vs Schematic，netgen 思想借鉴化用；"
         "service/lvs_compare_service 薄壳）：compare=两份网表拓扑一致性"
         "（图同构+missing/extra/mismatched+RF 特化）")
app.add_typer(lvs_app, name="lvs")


def _render_human(result: dict) -> None:
    """人读摘要分支（动态段一律 escape——markup 纪律）。"""
    verdict = str(result.get("verdict"))
    style = {"MATCH": "green", "MISMATCH": "red", "PARTIAL": "yellow"}.get(
        verdict, "white")
    summary = result.get("summary") or {}
    layout = result.get("layout") or {}
    schematic = result.get("schematic") or {}
    console.print(
        f"[bold]LVS 网表对照[/bold]  verdict=[{style}]{escape(verdict)}[/{style}]"
        f"  score={result.get('score')}"
        f"  tolerance={escape(str((result.get('params') or {}).get('tolerance')))}"
        f"  rf={escape(str((result.get('params') or {}).get('rf')))}")
    console.print(
        f"  layout:    {escape(str(layout.get('path')))}"
        f"（{escape(str(layout.get('format')))}"
        f" 元件 {layout.get('n_elements')} 网络 {layout.get('n_nets')}"
        f" 端口 {layout.get('n_ports')}）")
    console.print(
        f"  schematic: {escape(str(schematic.get('path')))}"
        f"（{escape(str(schematic.get('format')))}"
        f" 元件 {schematic.get('n_elements')} 网络 {schematic.get('n_nets')}"
        f" 端口 {schematic.get('n_ports')}）")
    console.print(
        f"  差异: missing {summary.get('n_missing')}"
        f"  extra {summary.get('n_extra')}"
        f"  mismatched {summary.get('n_mismatched')}"
        f"  同构对 {summary.get('matched_element_pairs')}"
        f"/{summary.get('pairable_elements')}")
    for d in (result.get("differences") or [])[:12]:
        console.print(
            f"  [{escape(str(d.get('category')))}] "
            f"{escape(str(d.get('type')))}: "
            f"{escape(str(d.get('detail')))}")
    total = int(summary.get("n_differences") or 0)
    if total > 12:
        console.print(f"  … 其余 {total - 12} 条差异 --json 看 "
                      "differences 明细")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")


@lvs_app.command("compare")
def lvs_compare_cmd(
    layout_netlist: str = typer.Argument(
        ..., help="版图侧网表文件（SPICE 三格式或 Verilog 门级；--format "
                  "auto 内容判定）"),
    schematic_netlist: str = typer.Argument(
        ..., help="原理图侧网表文件（参照侧；missing=仅 schematic 有，"
                  "extra=仅 layout 有）"),
    tolerance: str = typer.Option(
        "0.01", "--tolerance",
        help="相对容差（|a-b| <= tol*max(|a|,|b|)；参数/端口阻抗出窗判定）"),
    rf: bool | None = typer.Option(
        None, "--rf/--no-rf",
        help="RF 特化比对开关（缺省关：S 参数端口数量/序号/阻抗+传输线"
             "串联/并联/耦合线分类——#277 typer 陷阱家法三态）"),
    fmt: str = typer.Option(
        "auto", "--format",
        help="网表格式: auto=内容判定 / spice / verilog（显式覆盖判定）"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """LVS 网表对照（图同构+元件/参数/端口差异清单+对照报告）。

    示例：rfauto lvs compare layout.sp schematic.sp --json
          rfauto lvs compare layout.cir schematic.cir --rf --tolerance 0.05

    verdict：MATCH=同构+零差异 / MISMATCH=结构性不一致（missing/extra/
    同构失败/端口或分类不齐）/ PARTIAL=结构一致但值级出窗（参数/阻抗超
    容差或同构预算耗尽不可判定）。score∈【0,1】对照一致度（公式见
    service/lvs_compare_service docstring）。退出码：MATCH=0，其余=1
    （LVS 拦截语义；usage 错=2）。
    """
    from rfauto.service.lvs_compare_service import (  # lazy: run-path
        LVS_FORMATS,
        compare_netlist_files,
    )

    fmt_eff = str(fmt).strip().lower()
    if fmt_eff not in LVS_FORMATS:
        _emit_usage_error(
            f"--format {fmt!r} 不在词表 {list(LVS_FORMATS)}"
            "（auto/spice/verilog）",
            json_output=json_output)
        return
    try:
        tol_val = float(str(tolerance).strip())
    except ValueError:
        _emit_usage_error(
            f"--tolerance {tolerance!r} 不是数值（相对容差，如 0.01）",
            json_output=json_output)
        return
    if tol_val < 0:
        _emit_usage_error(
            f"--tolerance 须 >= 0，实际 {tol_val}",
            json_output=json_output)
        return
    rf_eff = False if rf is None else bool(rf)
    result = compare_netlist_files(
        Path(layout_netlist), Path(schematic_netlist),
        tolerance=tol_val, rf=rf_eff, fmt=fmt_eff)
    if json_output:
        _emit(result, "LVS 网表对照失败", json_output=True)
        # 失败信封 _emit 已 raise Exit(1)；成功信封按 verdict 出拦截码
        # （json 模式零红字追加——stdout 纯 JSON 不污染，layout lvs 先例）
        if str(result.get("verdict")) != "MATCH":
            raise typer.Exit(code=1)
        return
    if not result.get("ok"):
        _emit(result, "LVS 网表对照失败", json_output=False)
        return
    _render_human(result)
    if str(result.get("verdict")) != "MATCH":
        console.print(f"[red]✗ LVS_FLAG[/red] verdict={result.get('verdict')}"
                      f" score={result.get('score')}")
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)
