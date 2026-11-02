"""cal-wizard 子应用（TRL 校准件设计向导 CLI 出口；aurora_p G1 接线席，2026-11-02）。

叶 trl（单叶——TRL 设计单用户向导面）：service/cal_wizard_service（编排
core/trl_design 设计数学 + core/testsetup_diagram 连接图场景）的 CLI 出口——

- 输入：频带（``--freq-range-ghz LO,HI``，复用 calc_vna._parse_freq_range
  同层单源）+ 介质三口径（``--medium er_eff|coax|microstrip``，微带 εeff/
  线宽全走 core/synthesis 单源——铁律 7，CLI 零数值逻辑）；
- 输出：设计单信封（Thru/Reflect/Line 逐标准件几何+容差+覆盖三态
  verdict+警告如实）；``--out-dir`` 给定时落盘三件固定名
  （trl_design_sheet.json / calkit_def.yaml / trl_testsetup.drawio），
  缺省只出信封零落盘（确定性面：文件名固定无时间戳）。

零数值逻辑转发 service（规则 4）；带 ``--json``（信封契约：成功+失败
同构——usage 错走 _emit_usage_error exit 2，service 信封失败 exit 1）。
"""

from __future__ import annotations

import typer
from rich.markup import escape

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console
from rfauto.cli.domains.calc_vna import _parse_freq_range as _parse_freq_range

cal_wizard_app = typer.Typer(
    help="校准件设计向导（TRL 设计单+覆盖核算+测试连接图；service/"
         "cal_wizard_service 薄壳）：trl=频带+介质→Thru/Reflect/Line "
         "设计单（Line λg/4、8:1 覆盖核算、多 Line 分带）")
app.add_typer(cal_wizard_app, name="cal-wizard")

#: medium 枚举 → 必填/禁用旗标表（usage 校验单源，零 service 逻辑复制）
_MEDIUM_FLAGS = {
    "er_eff": {"required": ("er_eff",), "forbidden": ("er", "h_mm", "w_mm",
                                                      "tand")},
    "coax": {"required": ("er",), "forbidden": ("er_eff", "h_mm", "w_mm",
                                                "tand")},
    "microstrip": {"required": ("er", "h_mm"), "forbidden": ("er_eff",)},
}


def _render_human(result: dict, written: dict) -> None:
    """人读渲染分支（动态段一律 escape——campaign 叶 markup 纪律）。"""
    console.print(
        f"[bold]TRL 设计单[/bold]  verdict=[cyan]{escape(str(result.get('verdict')))}[/cyan]"
        f"  covered={result.get('covered')}  "
        f"频带 {escape(str(result.get('band_ghz')))} GHz"
        f"（带心 {escape(str(result.get('f_center_ghz')))}）")
    med = result.get("medium") or {}
    console.print(
        f"  介质: kind={escape(str(med.get('kind')))}  "
        f"er_eff={escape(str(med.get('er_eff')))}  "
        f"来源={escape(str(med.get('er_eff_source')))}")
    if med.get("width_mm") is not None:
        console.print(f"  线宽: {escape(str(med.get('width_mm')))} mm  "
                      f"Z0={escape(str(med.get('z0_ohm')))} Ω")
    for std in result.get("standards") or []:
        role = str(std.get("role"))
        if role == "line":
            console.print(
                f"  Line{std.get('index')}: λg/4 @ {std.get('f_center_ghz')} GHz"
                f"  L={std.get('length_mm')} mm"
                f"  带缘 θ={escape(str(std.get('theta_at_band_edges_deg')))} deg"
                f"  容差 ±{std.get('length_tolerance_mm')} mm")
        elif role == "thru":
            console.print("  Thru: 直连 0 长度")
        elif role == "reflect":
            console.print(
                f"  Reflect: 建议 {escape(str(std.get('recommended')))}"
                f"（{escape(str(std.get('gamma_design')))}；约束 "
                f"{escape(str(std.get('constraints')))}）")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(str(warn))}[/yellow]")
    for key, path in written.items():
        console.print(f"  [green]✓[/green] {key} → [cyan]{escape(str(path))}[/cyan]")


@cal_wizard_app.command("trl")
def cal_wizard_trl_cmd(
    freq_range: str = typer.Option(
        ..., "--freq-range-ghz",
        help="设计频带 LO,HI（GHz，逗号分隔；LO 必须小于 HI）"),
    medium: str = typer.Option(
        "er_eff", "--medium",
        help="介质口径 er_eff（直给有效介电常数）/coax（均匀 TEM，εeff=εr）/"
             "microstrip（εeff+线宽走 synthesis 单源）"),
    er_eff: float = typer.Option(
        None, "--er-eff", help="（--medium er_eff）有效介电常数 εeff（≥1）"),
    er: float = typer.Option(
        None, "--er", help="（--medium coax/microstrip）介质相对介电常数 εr"),
    h_mm: float = typer.Option(
        None, "--h-mm", help="（--medium microstrip）基板厚度（mm）"),
    w_mm: float = typer.Option(
        None, "--w-mm", help="（--medium microstrip 可选）线宽（mm）；缺省 "
                             "50Ω 反解（synthesis 单源）"),
    tand: float = typer.Option(
        None, "--tand", help="（--medium microstrip 可选）损耗角正切 tanδ"),
    z0_ohm: float = typer.Option(
        50.0, "--z0-ohm", help="（--medium microstrip 可选）目标阻抗（Ω）"),
    max_lines: int = typer.Option(
        6, "--max-lines", help="多 Line 方案 Line 数上限（超限判覆盖不可达"
                               "如实拒绝）"),
    kit_id: str = typer.Option(
        "trl_wizard", "--kit-id", help="校准套件 ID（calkit_def.yaml 键）"),
    connector: str = typer.Option(
        "SMA", "--connector", help="连接图线缆标签（原值标注零换算）"),
    out_dir: str = typer.Option(
        None, "--out-dir",
        help="落盘目录（写设计单 JSON/calkit 定义 YAML/测试连接图 .drawio "
             "三件固定名；缺省=只出信封零落盘）"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """TRL 校准件设计单（频带+介质 → Thru/Reflect/Line 几何+覆盖核算）。

    示例：rfauto cal-wizard trl --freq-range-ghz 4,9 --er-eff 2.25
          rfauto cal-wizard trl --freq-range-ghz 8,12 --medium microstrip
              --er 4.4 --h-mm 1.6 --out-dir cal_wizard_out --json

    覆盖三态如实（#122）：single_line（单 Line 8:1 有效窗内）/
    multiline（k 条 λg/4 等比分带+拼接窗）/uncovered（超上限如实拒绝，
    standards 空+警告指明所需 k）。设计数学=core/trl_design（教科书锚
    在内核 docstring）；微带 εeff=core/synthesis 单源（禁手抄公式）。
    """
    from rfauto.service.cal_wizard_service import trl_wizard

    lo, hi = _parse_freq_range(freq_range)
    kind = str(medium).strip()
    if kind not in _MEDIUM_FLAGS:
        _emit_usage_error(
            f"--medium 未知 {kind!r}；枚举仅 {sorted(_MEDIUM_FLAGS)}",
            json_output=json_output)
        return
    flags = {"er_eff": er_eff, "er": er, "h_mm": h_mm, "w_mm": w_mm,
             "tand": tand}
    for name in _MEDIUM_FLAGS[kind]["forbidden"]:
        if flags.get(name) is not None:
            _emit_usage_error(
                f"--{name.replace('_', '-')} 在 --medium {kind} 口径下"
                "禁给（该口径介质参数面见 --help）",
                json_output=json_output)
            return
    medium_payload: dict = {"kind": kind}
    for name in _MEDIUM_FLAGS[kind]["required"]:
        if flags.get(name) is None:
            _emit_usage_error(
                f"--medium {kind} 需 --{name.replace('_', '-')}",
                json_output=json_output)
            return
        medium_payload[name] = flags[name]
    if kind == "microstrip":
        if w_mm is not None:
            medium_payload["w_mm"] = w_mm
        if tand is not None:
            medium_payload["tand"] = tand
        medium_payload["z0_ohm"] = z0_ohm

    result = trl_wizard({
        "f_start_ghz": lo,
        "f_stop_ghz": hi,
        "medium": medium_payload,
        "max_lines": int(max_lines),
        "kit_id": kit_id,
        "connector": connector,
    }, out_dir=out_dir)
    if json_output:
        _emit(result, "TRL 设计单失败", json_output=True)
        return
    if not result.get("ok"):
        _emit(result, "TRL 设计单失败", json_output=False)
        raise typer.Exit(code=1)
    _render_human(result, result.get("written") or {})
    raise typer.Exit(code=0)
