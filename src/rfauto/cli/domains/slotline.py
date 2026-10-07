"""slotline/transitions 子应用（W2⑨ 槽线与过渡薄壳）（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── slotline / transitions（W2⑨ 槽线与过渡薄壳：闭式分析/综合 + 过渡/巴伦设计） ──
# 五命令零逻辑转发 service/slotline_service（规则 4）；数值只出确定性内核
# （铁律 7：core/slotline Janaswamy–Schaubert 闭式 + core/slotline_transitions
# Roberts/Knorr 过渡、Marchand 两节耦合段电路级综合）；越有效域拒绝进信封不外推。
# 数值参数一律 float 注解，无 Path 选项（#269 同族）。

slotline_app = typer.Typer(
    help="槽线闭式（Janaswamy–Schaubert 1986：分析/综合；越有效域拒绝不外推）")
app.add_typer(slotline_app, name="slotline")

transitions_app = typer.Typer(
    help="MSL↔槽线过渡与 Marchand 巴伦设计（微带 HJ 综合 + 槽线闭式精算）")
app.add_typer(transitions_app, name="transitions")

_SLOT_H_HELP = "基板厚 mm（单面金属、基板下空气；有效域 0.006≤d/λ0≤0.06）"
_SLOT_ER_HELP = "基板相对介电常数（2.22–3.8 / 3.8–9.8 两段拟合）"


@slotline_app.command("analyze")
def slotline_analyze_cmd(
    w_mm: float = typer.Option(..., "--w-mm", help="槽宽 mm（金属面上的缝）"),
    h_mm: float = typer.Option(..., "--h-mm", help=_SLOT_H_HELP),
    eps_r: float = typer.Option(..., "--eps-r", help=_SLOT_ER_HELP),
    freq_ghz: float = typer.Option(..., "--freq-ghz", help="频率 GHz（进入拟合式，必需）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """槽线闭式分析：(w, h, εr, f) → Z0、εeff、β、λ'（越有效域拒绝不外推）。

    示例：rfauto slotline analyze --w-mm 1.0 --h-mm 1.524 --eps-r 3.66 --freq-ghz 2.5
    """
    from rfauto.service.slotline_service import slotline_analysis

    result = slotline_analysis(w_mm, h_mm, eps_r, freq_ghz)
    _emit(result, "槽线分析失败", json_output=json_output)
    if json_output:
        return
    r = result["result"]
    console.print(
        f"[green]✓ 槽线 segment={r['segment']}[/green]  Z0={r['z0_ohm']}Ω  "
        f"εeff={r['eps_eff']}  β={r['beta_rad_m']} rad/m  λ'={r['lambda_g_mm']}mm")
    console.print(f"  W/λ0={r['w_over_lambda0']}  d/λ0={r['d_over_lambda0']}  "
                  f"λ'/λ0={r['lambda_ratio']}")


@slotline_app.command("synth")
def slotline_synth_cmd(
    z0_ohm: float = typer.Option(..., "--z0-ohm", help="目标特性阻抗 Ω（功率-电压定义）"),
    h_mm: float = typer.Option(..., "--h-mm", help=_SLOT_H_HELP),
    eps_r: float = typer.Option(..., "--eps-r", help=_SLOT_ER_HELP),
    freq_ghz: float = typer.Option(..., "--freq-ghz", help="频率 GHz"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """槽线综合：目标 Z0 → 槽宽 w（窄槽段括号反解；不可达如实 realizable=False）。

    示例：rfauto slotline synth --z0-ohm 110 --h-mm 1.524 --eps-r 3.66 --freq-ghz 2.5
    """
    from rfauto.service.slotline_service import slotline_synthesis

    result = slotline_synthesis(z0_ohm, h_mm, eps_r, freq_ghz)
    _emit(result, "槽线综合失败", json_output=json_output)
    if json_output:
        return
    if not result.get("realizable", True):
        # 不可达=合法结果非错误（D5 与 marchand 两节语义统一；#122 不凑绿）
        console.print(
            f"[yellow]○ 不可达（realizable=False）[/yellow]  {result.get('reason')}")
        return
    r = result["result"]
    console.print(
        f"[green]✓ w={r['w_mm']}mm[/green]  Z0={r['z0_actual_ohm']}Ω  "
        f"εeff={r['eps_eff']}  λ'={r['lambda_g_mm']}mm  segment={r['segment']}")


def _print_transition_design(design: dict) -> None:
    console.print(
        f"  槽线: Z0={design['z_slot_ohm']}Ω  εeff={design['eps_eff_slot']}  "
        f"λ'={design['lambda_slot_mm']}mm  短路臂 l_short={design['l_short_mm']}mm")
    console.print(
        f"  微带: w={design['w_msl_mm']}mm  Z0={design['z_msl_ohm']}Ω  "
        f"εeff={design['eps_eff_msl']}  开路支节 l_stub={design['l_stub_mm']}mm"
        f"（Δl_open={design['dl_open_mm']}mm）")


@transitions_app.command("msl-slot")
def transitions_msl_slot_cmd(
    f0_ghz: float = typer.Option(..., "--f0-ghz", help="设计中心频率 GHz"),
    h_mm: float = typer.Option(..., "--h-mm", help=_SLOT_H_HELP),
    er: float = typer.Option(..., "--er", help=_SLOT_ER_HELP),
    w_slot_mm: float = typer.Option(..., "--w-slot-mm", help="槽宽 mm"),
    tan_d: float = typer.Option(0.0037, "--tan-d", help="基板损耗角正切"),
    z_msl_ohm: float = typer.Option(50.0, "--z-msl-ohm", help="微带馈线目标阻抗 Ω"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """Roberts/Knorr MSL↔槽线过渡设计参数（开路支节 λg/4+Δl、槽线短路臂 λg'/4）。

    示例：rfauto transitions msl-slot --f0-ghz 2.5 --h-mm 1.524 --er 3.66 --w-slot-mm 1.0
    """
    from rfauto.service.slotline_service import msl_slot_transition_design

    result = msl_slot_transition_design(f0_ghz, h_mm, er, w_slot_mm, tan_d, z_msl_ohm)
    _emit(result, "过渡设计失败", json_output=json_output)
    if json_output:
        return
    design = result["design"]
    console.print(f"[green]✓ MSL↔槽线过渡 @ {design['f0_ghz']}GHz[/green]")
    _print_transition_design(design)


@transitions_app.command("marchand-balun")
def transitions_marchand_balun_cmd(
    f0_ghz: float = typer.Option(..., "--f0-ghz", help="设计中心频率 GHz"),
    h_mm: float = typer.Option(..., "--h-mm", help=_SLOT_H_HELP),
    er: float = typer.Option(..., "--er", help=_SLOT_ER_HELP),
    w_slot_mm: float = typer.Option(..., "--w-slot-mm", help="槽宽 mm"),
    tan_d: float = typer.Option(0.0037, "--tan-d", help="基板损耗角正切"),
    z_msl_ohm: float = typer.Option(50.0, "--z-msl-ohm", help="微带馈线目标阻抗 Ω"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """双槽臂 Marchand 巴伦设计参数（d_c=w_msl+s_slot；在过渡参数上补槽距与 a1/a2）。"""
    from rfauto.service.slotline_service import marchand_balun_design

    result = marchand_balun_design(f0_ghz, h_mm, er, w_slot_mm, tan_d, z_msl_ohm)
    _emit(result, "Marchand 巴伦设计失败", json_output=json_output)
    if json_output:
        return
    design = result["design"]
    console.print(f"[green]✓ 双槽臂 Marchand 巴伦 @ {design['f0_ghz']}GHz[/green]")
    _print_transition_design(design)
    console.print(f"  槽距 d_c={design['d_center_mm']}mm  a1={design['a1_mm']}mm  "
                  f"a2={design['a2_mm']}mm")


@transitions_app.command("marchand2")
def transitions_marchand2_cmd(
    f0_ghz: float = typer.Option(2.5, "--f0-ghz", help="设计中心频率 GHz"),
    z_unbal_ohm: float = typer.Option(50.0, "--z-unbal-ohm", help="不平衡端阻抗 Ω"),
    z_bal_diff_ohm: float = typer.Option(280.0, "--z-bal-diff-ohm",
                                         help="平衡端差分阻抗 Ω（单端参考 Z_L/2）"),
    er: float = typer.Option(3.66, "--er", help="基板相对介电常数"),
    h_mm: float = typer.Option(1.524, "--h-mm", help="基板厚 mm"),
    tan_d: float = typer.Option(0.0037, "--tan-d", help="基板损耗角正切"),
    s_min_mm: float = typer.Option(0.1, "--s-min-mm", help="可制造最小耦合缝 mm"),
    w_max_mm: float = typer.Option(6.0, "--w-max-mm", help="耦合段线宽上限 mm"),
    z_c_ohm: float | None = typer.Option(None, "--z-c-ohm",
                                         help="耦合段 Z_c=√(Z0e·Z0o) Ω（缺省自动扫描）"),
    band_lo_ghz: float | None = typer.Option(None, "--band-lo-ghz",
                                             help="自检带下沿 GHz（缺省 0.9·f0）"),
    band_hi_ghz: float | None = typer.Option(None, "--band-hi-ghz",
                                             help="自检带上沿 GHz（缺省 1.1·f0）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """两节对称 Marchand 电路级综合（KJ 几何反解 + 电路级自检门；不可达如实 realizable=False）。

    示例：rfauto transitions marchand2 --z-bal-diff-ohm 280 --h-mm 1.524 --er 3.66
    """
    from rfauto.service.slotline_service import marchand_two_section_synthesis

    if (band_lo_ghz is None) != (band_hi_ghz is None):
        console.print("[red]✗ --band-lo-ghz 与 --band-hi-ghz 须成对给出[/red]")
        raise typer.Exit(code=1)
    band = [band_lo_ghz, band_hi_ghz] if band_lo_ghz is not None else None
    result = marchand_two_section_synthesis(
        f0_ghz, z_unbal_ohm, z_bal_diff_ohm, er, h_mm, tan_d, s_min_mm, w_max_mm,
        z_c_ohm, band)
    _emit(result, "Marchand 两节综合失败", json_output=json_output)
    if json_output:
        return
    design = result["design"]
    metrics = design["model_metrics"]
    tag = "[green]严格可达[/green]" if design["realizable"] else "[yellow]不可达→钳位最近点[/yellow]"
    console.print(
        f"✓ 两节 Marchand @ {design['f0_ghz']}GHz  {tag}  "
        f"C={design['coupling_db']:.2f}dB  Z_c={design['z_c_ohm']:.3f}Ω  "
        f"(Z0e,Z0o)=({design['z0e_realized_ohm']:.3f},{design['z0o_realized_ohm']:.3f})Ω")
    nominal = result["nominal_params"]
    console.print(
        f"  几何: w={nominal['w_mm']}  s={nominal['s_mm']}  l_sect={nominal['l_sect_mm']}  "
        f"w_feed={nominal['w_feed_mm']}  w_bal={nominal['w_bal_line_mm']} mm  "
        f"r_bal_se={nominal['r_bal_se_ohm']}Ω")
    verdict = "[green]PASS[/green]" if metrics["all_gates_pass"] else "[red]FAIL[/red]"
    console.print(
        f"  电路级自检门 {verdict}  max|S11|={metrics['band_max_s11_db']:.2f}dB  "
        f"min|S21|/|S31|={metrics['band_min_s21_db']:.3f}/{metrics['band_min_s31_db']:.3f}dB  "
        f"不平衡 {metrics['band_max_abs_imbalance_db']:.3f}dB  "
        f"相位误差 {metrics['band_max_phase_error_deg']:.2f}°")
    for note in design.get("notes") or []:
        console.print(f"  [dim]{note}[/dim]")
