"""aurora_e W1-S2 席锚树：R7 第二梯队余量收口四键（T2 圆波导传播解+矩形腔
谱/Q+T9 圆锥 RCS+T10 热偶/测辐射热计换算）。

背景（#222 开工核实）：R7_core_tier2 T2/T4/T9/T10 四族核心键已由 aurora72
A2/A3/A4 落地（circular_cavity_* / linear_antenna_zin / rcs_sphere_mie+
rcs_peak_canonical / diode_square_law_detect+detector_tss_nep）；本席只收口
任务书内明确列出的四处余量：① 圆波导 TE/TM_mn 传播键（任务书"圆波导截
止/衰减/波导波长/功率容量"子项）② 矩形腔谱+Q（waveguide_closed_form 模
块 docstring 自证"留续作"）③ rcs_peak_canonical 的 cone_tip（前席 v1 如实
不做）④ 热偶/测辐射热计功率换算（全仓零命中）。

数值断言口径（#118 不自证——恒等式/独立常数/独立路线/跨键互证，不用自身
推导互证）：
- 圆波导：fc TE11 @a=10mm=8.7849GHz 独立常数窗（x'_11=1.841183781341）+
  0.293c/a 口径；λg=λ0/√(1−(fc/f)²) 独立重算 ≤1e-12；vp·vg=c0²/(εrμr)
  in-output 恒等字段逐位；TE01/TM11 同根 3.831705970208 简并 →
  Z_TE·Z_TM=η²（输出 9 位舍入级 ≤1e-11）；α_c 闭式独立重算（0.1498dB/m
  @10GHz 窗）+ in-output 数值路线 xcheck<1e-12 + σ×4→α×½ 逐位 +
  TE01<TE11 经典低损性质；功率容量 E_max TE11 轴线闭式 ωμ/(2kc)
  （J'_1 与 J_1/z 均在 0 处取极大 ½）≤1e-4 + e_br×2→P×4 逐位 + P_max
  恒等式回收；截止以下显式拒绝。
- 矩形腔谱：TE101 @30/20/60mm=5.5863GHz 独立常数重算 + 与
  cavity_perturbation_shift 空腔 f0 同仓双源 ≤1e-12；εr=4 → 全谱 ÷2 逐位
  （同 k 空间频段配对）；TE10 波导截止 c/(2a) 独立重算；主模=计算判读
  （TE101 复现）。
- 矩形腔 Q：Ue/Um≈1 谐振定理（TE101/TM110/TM111/TE011/TE111 五模式）+
  in-output quad 因子双路线 xcheck<1e-12 + Q_TE101≈1.03e4 铜腔合理带 +
  σ×4→Qc×2 逐位 + 1/Qu=1/Qc+1/Qd 合成回收 + f 与谱键跨键互证 ≤1e-12。
- 圆锥：σ=λ²tan⁴α/(16π) 测试侧独立重算 ≤1e-12；λ² 标度（f×2→σ×¼）逐位 +
  tan⁴α 标度（15°→30° 比值恒等式）逐位 + dBsm 换算恒等；尺寸无关口径
  守卫（a/b 拒绝、half_angle 必给∈(0,90)、其他形状同给拒绝）。
- 热偶/测辐射热计：γ=S·η·R_th / V_b·TCR·η·R_th/4 独立重算逐位；
  V=γ·P 往返回收（V/γ→P ≤1e-15）；P×2→V×2；τ=R_th·C_th 与
  f_3dB=1/(2πτ) 恒等；同 γ 跨类型输出逐位一致（热链单源结构恒等）；
  电桥输出与 R0 绝对值无关（R0 只进报告面）；P_min=v_noise/|γ| 回收；
  守卫族（类型封闭集/跨类型参数互斥/TCR≠0/域 [−120,30]dBm/η∈(0,1]）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.calculator_service import run_calculator

_C_MM_GHZ = 299.792458          # mm·GHz（测试侧独立常量）
_C0 = 299792458.0               # m/s
_MU0 = 1.25663706212e-6
_EPS0 = 8.8541878128e-12
_ETA0 = math.sqrt(_MU0 / _EPS0)
_X11_TE = 1.841183781341        # J'_1 首正零点（TE11；文献常数）
_X01_SHARED = 3.831705970208    # J_0' / J_1 首正零点（TE01=TM11 简并）
_X01_TM = 2.4048255577         # J_0 首正零点（TM01）


# ─── 公共小工具 ──────────────────────────────────────────────────────────────


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _reject(key: str, params: dict, needle: str | None = None) -> None:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 越界输入未拒绝: {params!r}"
    if needle is not None:
        assert needle in str(out.get("error")), (
            f"{key} 拒绝语义不符: {out.get('error')!r}")


# ─── circular_waveguide_mode_prop：截止/λg/Z/衰减/功率容量 ───────────────────


def _wg(mode_type: str, m: int, n: int, f_ghz: float, **kw) -> dict:
    base = {"mode_type": mode_type, "m": m, "n": n, "radius_mm": 10.0,
            "f_ghz": f_ghz, "conductivity_s_per_m": 5.8e7}
    base.update(kw)
    return _run("circular_waveguide_mode_prop", base)


def test_waveguide_te11_propagation_anchors():
    """TE11 @a=10mm/10GHz：fc 常数窗+λg/Z_TE/α_c 独立重算+vp·vg 恒等。"""
    r = _wg("TE", 1, 1, 10.0)
    fc_hand = _C_MM_GHZ * _X11_TE / (2.0 * math.pi * 10.0)
    assert r["fc_ghz"] == pytest.approx(fc_hand, rel=1e-9)
    assert fc_hand == pytest.approx(0.293 * _C_MM_GHZ / 10.0, rel=1e-3)
    k = 2.0 * math.pi * 10e9 / _C0
    kc = _X11_TE / 0.01
    beta = math.sqrt(k * k - kc * kc)
    assert r["lambda_g_mm"] == pytest.approx(2.0 * math.pi / beta * 1e3,
                                             rel=1e-9)
    lam0_mm = _C_MM_GHZ / 10.0
    assert r["lambda_g_check_mm"] == pytest.approx(
        lam0_mm / math.sqrt(1.0 - (fc_hand / 10.0) ** 2), rel=1e-9)
    assert r["z_mode_ohm"] == pytest.approx(k * _ETA0 / beta, rel=1e-11)
    assert r["vp_vg_identity"] == pytest.approx(1.0, abs=1e-12)
    rs = math.sqrt(math.pi * 10e9 * _MU0 / 5.8e7)
    d_fac = 1.0 - 1.0 / _X11_TE ** 2
    alpha_hand = rs * kc * kc * (1.0 + beta * beta / (kc ** 4 * 0.01 ** 2)) / (
        k * _ETA0 * beta * 0.01 * d_fac)
    assert r["alpha_c_np_per_m"] == pytest.approx(alpha_hand, rel=1e-12)
    assert r["alpha_c_db_per_m"] == pytest.approx(8.685889638065035
                                                  * alpha_hand, rel=1e-12)
    # 文献口径窗：X 波段 a=10mm Cu TE11 约 0.15 dB/m 量级
    assert 0.10 < r["alpha_c_db_per_m"] < 0.20
    assert r["alpha_c_xcheck_rel_dev"] < 1e-12


def test_waveguide_te01_tm11_degenerate_z_product():
    """TE01/TM11 同根简并（3.8317）：Z_TE·Z_TM=η²（输出舍入级）。"""
    te01 = _wg("TE", 0, 1, 20.0)
    tm11 = _wg("TM", 1, 1, 20.0)
    assert te01["x_root"] == pytest.approx(_X01_SHARED, rel=1e-9)
    assert tm11["x_root"] == pytest.approx(_X01_SHARED, rel=1e-9)
    product = te01["z_mode_ohm"] * tm11["z_mode_ohm"]
    assert product / te01["eta_ohm"] ** 2 == pytest.approx(1.0, abs=1e-11)
    # 独立重算（闭式）：Z_TE=kη/β、Z_TM=βη/k 同根同频
    k = 2.0 * math.pi * 20e9 / _C0
    kc = _X01_SHARED / 0.01
    beta = math.sqrt(k * k - kc * kc)
    assert te01["z_mode_ohm"] == pytest.approx(k * _ETA0 / beta, rel=1e-12)
    assert tm11["z_mode_ohm"] == pytest.approx(beta * _ETA0 / k, rel=1e-11)


def test_waveguide_alpha_xcheck_and_conductor_scaling():
    """α 双路线互证 <1e-12（TE01/TM01 双型）+σ×4→α×½ 逐位+TE01<TE11。"""
    te01 = _wg("TE", 0, 1, 20.0)
    tm01 = _wg("TM", 0, 1, 15.0)
    assert te01["alpha_c_xcheck_rel_dev"] < 1e-12
    assert tm01["alpha_c_xcheck_rel_dev"] < 1e-12
    # TM01 独立重算：α=Rs·ωε·J'²(x)/(aβ·J_{m+1}²(x))，m=0 时 J'_0=−J_1
    # → 比值 1 → α=Rs·ωε/(aβ)
    f = 15e9
    omega = 2.0 * math.pi * f
    k = omega / _C0
    kc = _X01_TM / 0.01
    beta = math.sqrt(k * k - kc * kc)
    rs = math.sqrt(math.pi * f * _MU0 / 5.8e7)
    assert tm01["alpha_c_np_per_m"] == pytest.approx(
        rs * omega * _EPS0 / (beta * 0.01), rel=1e-9)
    # σ×4 → Rs×½ → α×½（同频同模逐位）
    te01_better = _wg("TE", 0, 1, 20.0, conductivity_s_per_m=5.8e7 * 4)
    assert te01_better["alpha_c_np_per_m"] == pytest.approx(
        0.5 * te01["alpha_c_np_per_m"], rel=1e-12)
    # TE01 经典低损性质（f≫fc 渐近域）：同频导体衰减低于 TE11
    # （20GHz 时 TE01 近截止 kβ 惩罚占优，低损优势须远端复现）
    te01_hi = _wg("TE", 0, 1, 40.0)
    te11_hi = _wg("TE", 1, 1, 40.0)
    assert te01_hi["alpha_c_np_per_m"] < te11_hi["alpha_c_np_per_m"]
    # 介质衰减：α_d=k²tanδ/(2β) 独立重算（20GHz 同频独立换算）
    r_d = _wg("TE", 0, 1, 20.0, tan_delta=1e-4)
    k20 = 2.0 * math.pi * 20e9 / _C0
    beta20 = math.sqrt(k20 * k20 - (_X01_SHARED / 0.01) ** 2)
    assert r_d["alpha_d_np_per_m"] == pytest.approx(
        k20 * k20 * 1e-4 / (2.0 * beta20), rel=1e-12)


def test_waveguide_power_capacity():
    """功率容量：E_max TE11 轴线闭式锚+e_br×2→P×4+P_max 恒等式回收。"""
    r = _wg("TE", 1, 1, 10.0)
    kc = _X11_TE / 0.01
    emax_hand = 2.0 * math.pi * 10e9 * _MU0 / (2.0 * kc)
    assert r["e_max_per_coef_v_per_m"] == pytest.approx(emax_hand, rel=1e-4)
    assert r["p_max_w"] == pytest.approx(
        r["p_flow_per_coef_sq_w"] * (r["e_br_v_per_m"]
                                     / r["e_max_per_coef_v_per_m"]) ** 2,
        rel=1e-11)
    r_hi = _wg("TE", 1, 1, 10.0, e_br_v_per_m=6.0e6)
    assert r_hi["p_max_w"] == pytest.approx(4.0 * r["p_max_w"], rel=1e-12)
    # TM01 功率容量sanity（E_max 栅格有限正值、恒等式回收同构）
    tm = _wg("TM", 0, 1, 15.0)
    assert tm["e_max_per_coef_v_per_m"] > 0.0
    assert tm["p_max_w"] == pytest.approx(
        tm["p_flow_per_coef_sq_w"] * (tm["e_br_v_per_m"]
                                      / tm["e_max_per_coef_v_per_m"]) ** 2,
        rel=1e-11)


def test_waveguide_guards():
    """守卫族：截止拒绝/n=0/类型封闭集/尺寸与电导域。"""
    _reject("circular_waveguide_mode_prop",
            {"mode_type": "TE", "m": 1, "n": 1, "radius_mm": 10.0,
             "f_ghz": 5.0, "conductivity_s_per_m": 5.8e7}, "fc")
    _reject("circular_waveguide_mode_prop",
            {"mode_type": "TE", "m": 1, "n": 1, "radius_mm": 10.0,
             "f_ghz": 8.0, "conductivity_s_per_m": 5.8e7}, "fc")
    _reject("circular_waveguide_mode_prop",
            {"mode_type": "TE", "m": 1, "n": 0, "radius_mm": 10.0,
             "f_ghz": 10.0, "conductivity_s_per_m": 5.8e7}, "n")
    _reject("circular_waveguide_mode_prop",
            {"mode_type": "TEM", "m": 1, "n": 1, "radius_mm": 10.0,
             "f_ghz": 10.0, "conductivity_s_per_m": 5.8e7}, "mode_type")
    _reject("circular_waveguide_mode_prop",
            {"mode_type": "TE", "m": 1, "n": 1, "radius_mm": 0.0,
             "f_ghz": 10.0, "conductivity_s_per_m": 5.8e7}, "radius_mm")
    _reject("circular_waveguide_mode_prop",
            {"mode_type": "TE", "m": 1, "n": 1, "radius_mm": 10.0,
             "f_ghz": 10.0, "conductivity_s_per_m": 0.0},
            "conductivity_s_per_m")
    _reject("circular_waveguide_mode_prop",
            {"mode_type": "TE", "m": 1, "n": 1, "radius_mm": 10.0,
             "f_ghz": 10.0, "conductivity_s_per_m": 5.8e7,
             "epsilon_r": 0.5}, "epsilon_r")
    _reject("circular_waveguide_mode_prop",
            {"mode_type": "TE", "m": 1, "n": 1, "radius_mm": 10.0,
             "f_ghz": 10.0, "conductivity_s_per_m": 5.8e7,
             "e_br_v_per_m": 0.0}, "e_br_v_per_m")


# ─── rectangular_cavity_mode_spectrum：谱+TE101 双源+εr 标度 ─────────────────


def _rect_spec(f_lo: float, f_hi: float, **kw) -> dict:
    base = {"a_mm": 30.0, "b_mm": 20.0, "d_mm": 60.0,
            "f_min_ghz": f_lo, "f_max_ghz": f_hi}
    base.update(kw)
    return _run("rectangular_cavity_mode_spectrum", base)


def test_rect_spectrum_te101_double_source():
    """TE101=5.5863GHz 独立常数+cavity_perturbation_shift 空腔 f0 同仓双源。"""
    sp = _rect_spec(5.0, 6.0)
    f_hand = _C_MM_GHZ / 2.0 * math.sqrt(1.0 / 30.0 ** 2 + 1.0 / 60.0 ** 2)
    assert sp["dominant_mode"] == "TE101"
    assert sp["dominant_f_ghz"] == pytest.approx(f_hand, rel=1e-9)
    # 同仓双源：cavity_perturbation_shift 空腔 f0=(c/2)√(1/a²+1/d²)
    per = _run("cavity_perturbation_shift",
               {"a_mm": 30.0, "b_mm": 20.0, "d_mm": 60.0,
                "sample_box_mm": [14.5, 9.0, 29.0, 15.5, 11.0, 31.0]})
    assert per["f0_ghz"] == pytest.approx(sp["dominant_f_ghz"], rel=1e-12)
    # TE102 独立重算（(c/2)√(1/a²+4/d²)）
    f_te102 = _C_MM_GHZ / 2.0 * math.sqrt(1.0 / 30.0 ** 2 + 4.0 / 60.0 ** 2)
    by_name = {m["mode"]: m["f_ghz"] for m in _rect_spec(4.0, 8.0)["modes"]}
    assert by_name["TE102"] == pytest.approx(f_te102, rel=1e-9)
    assert "TE101" in by_name  # 存在性自检
    assert sp["te10_waveguide_cutoff_ghz"] == pytest.approx(
        _C_MM_GHZ / (2.0 * 30.0), rel=1e-9)


def test_rect_spectrum_epsr_scaling():
    """εr=4 → 全谱 ÷2 逐位（同 k 空间频段 [2,4]↔[4,8] 配对）。"""
    sp1 = _rect_spec(4.0, 8.0)
    sp4 = _rect_spec(2.0, 4.0, epsilon_r=4.0)
    names1 = [m["mode"] for m in sp1["modes"]]
    names4 = [m["mode"] for m in sp4["modes"]]
    assert names1 == names4 == ["TE101", "TE102", "TE011"]
    for m1, m4 in zip(sp1["modes"], sp4["modes"], strict=True):
        assert m1["f_ghz"] / 2.0 == pytest.approx(m4["f_ghz"], rel=1e-9)


def test_rect_spectrum_guards():
    """守卫族：频段倒序/尺寸非正/max_modes 溢出。"""
    _reject("rectangular_cavity_mode_spectrum",
            {"a_mm": 30.0, "b_mm": 20.0, "d_mm": 60.0,
             "f_min_ghz": 8.0, "f_max_ghz": 4.0}, "f_min_ghz")
    _reject("rectangular_cavity_mode_spectrum",
            {"a_mm": 0.0, "b_mm": 20.0, "d_mm": 60.0,
             "f_min_ghz": 4.0, "f_max_ghz": 8.0}, "a")
    # 宽频段带内模式 >500 → 显式拒绝要求收窄
    _reject("rectangular_cavity_mode_spectrum",
            {"a_mm": 30.0, "b_mm": 20.0, "d_mm": 60.0,
             "f_min_ghz": 1.0, "f_max_ghz": 40.0}, "max_modes")


# ─── rectangular_cavity_mode_q：谐振定理/双路线/标度/合成 ─────────────────────


def _rect_q(mode_type: str, m: int, n: int, p: int, **kw) -> dict:
    base = {"mode_type": mode_type, "m": m, "n": n, "p": p,
            "a_mm": 30.0, "b_mm": 20.0, "d_mm": 60.0,
            "conductivity_s_per_m": 5.8e7}
    base.update(kw)
    return _run("rectangular_cavity_mode_q", base)


def test_rect_q_te101_anchor_and_cross_key():
    """TE101：Ue/Um≈1+双路线<1e-12+铜腔合理带+f 与谱键跨键互证 ≤1e-12。"""
    q = _rect_q("TE", 1, 0, 1)
    assert q["f_ghz"] == pytest.approx(5.5863026269145895, rel=1e-9)
    assert q["ue_over_um"] == pytest.approx(1.0, abs=1e-9)
    assert q["q_xcheck_rel_dev"] < 1e-12
    assert 5.0e3 < q["q_conductor"] < 2.0e4  # 铜腔 TE101 合理带
    rs_hand = math.sqrt(math.pi * q["f_ghz"] * 1e9 * _MU0 / 5.8e7)
    assert q["rs_ohm_per_sq"] == pytest.approx(rs_hand, rel=1e-12)
    # 跨键：谱键 TE101 频率与 Q 键 f_ghz 逐位互证
    sp = _rect_spec(5.5, 5.7)
    assert sp["modes"][0]["f_ghz"] == q["f_ghz"]


def test_rect_q_resonance_theorem_multi_mode():
    """谐振定理 Ue/Um≈1 多模式（TE011/TE111/TM110/TM111）+双路线全绿。"""
    for mtype, m, n, p in (("TE", 0, 1, 1), ("TE", 1, 1, 1),
                           ("TM", 1, 1, 0), ("TM", 1, 1, 1)):
        q = _rect_q(mtype, m, n, p)
        tag = f"{mtype}{m}{n}{p}"
        assert q["ue_over_um"] == pytest.approx(1.0, abs=1e-9), tag
        assert q["q_xcheck_rel_dev"] < 1e-12, tag
        assert q["q_conductor"] > 0.0, tag


def test_rect_q_scaling_and_dielectric():
    """σ×4→Qc×2 逐位+介质串联合成回收+tanδ=0 如实返 null。"""
    q = _rect_q("TE", 1, 0, 1)
    q_better = _rect_q("TE", 1, 0, 1, conductivity_s_per_m=5.8e7 * 4)
    assert q_better["q_conductor"] == pytest.approx(
        2.0 * q["q_conductor"], rel=1e-12)
    q_d = _rect_q("TE", 1, 0, 1, tan_delta=1e-4)
    assert q_d["q_dielectric"] == pytest.approx(1.0e4, rel=1e-15)
    assert q_d["q_unloaded"] == pytest.approx(
        1.0 / (1.0 / q_d["q_conductor"] + 1.0 / q_d["q_dielectric"]),
        rel=1e-12)
    assert q["q_dielectric"] is None
    assert q["q_unloaded"] == q["q_conductor"]


def test_rect_q_mode_rule_guards():
    """模式规则守卫：TE (0,0,·)/TE p=0/TM m=0/TM p<0 显式拒绝。"""
    _reject("rectangular_cavity_mode_q",
            {"mode_type": "TE", "m": 0, "n": 0, "p": 1, "a_mm": 30.0,
             "b_mm": 20.0, "d_mm": 60.0,
             "conductivity_s_per_m": 5.8e7}, "(m,n)")
    _reject("rectangular_cavity_mode_q",
            {"mode_type": "TE", "m": 1, "n": 0, "p": 0, "a_mm": 30.0,
             "b_mm": 20.0, "d_mm": 60.0,
             "conductivity_s_per_m": 5.8e7}, "p")
    _reject("rectangular_cavity_mode_q",
            {"mode_type": "TM", "m": 0, "n": 1, "p": 0, "a_mm": 30.0,
             "b_mm": 20.0, "d_mm": 60.0,
             "conductivity_s_per_m": 5.8e7}, "m,n")
    _reject("rectangular_cavity_mode_q",
            {"mode_type": "TM", "m": 1, "n": 1, "p": -1, "a_mm": 30.0,
             "b_mm": 20.0, "d_mm": 60.0,
             "conductivity_s_per_m": 5.8e7}, "p")


# ─── rcs_peak_canonical 的 cone_tip：闭式/标度/守卫 ──────────────────────────


def test_cone_tip_anchors_and_scaling():
    """σ=λ²tan⁴α/(16π) 独立重算+λ² 标度+tan⁴α 标度+dBsm 换算恒等。"""
    r = _run("rcs_peak_canonical", {"shape": "cone_tip", "f_ghz": 10.0,
                                    "half_angle_deg": 15.0})
    lam_m = _C_MM_GHZ / 10.0 * 1e-3
    sig_hand = lam_m ** 2 * math.tan(math.radians(15.0)) ** 4 / (16.0 * math.pi)
    assert r["sigma_m2"] == pytest.approx(sig_hand, rel=1e-12)
    assert r["sigma_dbsm"] == pytest.approx(10.0 * math.log10(sig_hand),
                                            rel=1e-12)
    assert r["a_mm"] is None and r["b_mm"] is None
    assert r["effective_aperture_m2"] is None
    # λ² 标度：f×2 → σ×¼ 逐位
    r2 = _run("rcs_peak_canonical", {"shape": "cone_tip", "f_ghz": 20.0,
                                     "half_angle_deg": 15.0})
    assert r2["sigma_m2"] == pytest.approx(0.25 * r["sigma_m2"], rel=1e-12)
    # tan⁴α 标度：15°→30° 比值恒等式
    r3 = _run("rcs_peak_canonical", {"shape": "cone_tip", "f_ghz": 10.0,
                                     "half_angle_deg": 30.0})
    ratio_hand = (math.tan(math.radians(30.0))
                  / math.tan(math.radians(15.0))) ** 4
    assert r3["sigma_m2"] == pytest.approx(ratio_hand * r["sigma_m2"],
                                           rel=1e-12)


def test_cone_tip_guards_and_existing_shapes_regression():
    """cone 守卫（尺寸无关/半角域）+既有四形不回归（41.45dBsm 常数）。"""
    _reject("rcs_peak_canonical",
            {"shape": "cone_tip", "f_ghz": 10.0, "a_mm": 40.0}, "a_mm")
    _reject("rcs_peak_canonical",
            {"shape": "cone_tip", "f_ghz": 10.0, "half_angle_deg": 15.0,
             "b_mm": 40.0}, "b_mm")
    _reject("rcs_peak_canonical",
            {"shape": "cone_tip", "f_ghz": 10.0}, "half_angle_deg")
    _reject("rcs_peak_canonical",
            {"shape": "cone_tip", "f_ghz": 10.0, "half_angle_deg": 0.0},
            "half_angle_deg")
    _reject("rcs_peak_canonical",
            {"shape": "cone_tip", "f_ghz": 10.0, "half_angle_deg": 90.0},
            "half_angle_deg")
    _reject("rcs_peak_canonical",
            {"shape": "flat_plate", "f_ghz": 10.0, "a_mm": 40.0,
             "b_mm": 40.0, "half_angle_deg": 15.0}, "half_angle_deg")
    # 既有四形回归：1m² 平板@10GHz=41.45dBsm 常数锚不漂
    fp = _run("rcs_peak_canonical", {"shape": "flat_plate", "f_ghz": 10.0,
                                     "a_mm": 1000.0, "b_mm": 1000.0})
    assert fp["sigma_dbsm"] == pytest.approx(41.45, abs=0.02)


# ─── thermal_power_sensor_detect：热链恒等/跨类型/守卫 ────────────────────────


_TC = {"sensor_type": "thermocouple", "p_in_dbm": -20.0,
       "r_th_k_per_w": 500.0, "c_th_j_per_k": 1e-3,
       "seebeck_v_per_k": 2.0e-4}


def test_thermal_thermocouple_chain():
    """热偶：γ/ΔT/V_out/τ/f_3dB 独立重算逐位+往返回收+P×2→V×2。"""
    t = _run("thermal_power_sensor_detect", _TC)
    p_w = 10.0 ** (-2.0) * 1e-3
    gamma_hand = 2.0e-4 * 1.0 * 500.0
    assert t["gamma_v_per_w"] == pytest.approx(gamma_hand, rel=1e-15)
    assert t["delta_t_k"] == pytest.approx(1.0 * 500.0 * p_w, rel=1e-15)
    assert t["v_out_v"] == pytest.approx(gamma_hand * p_w, rel=1e-15)
    assert t["tau_s"] == pytest.approx(500.0 * 1e-3, rel=1e-15)
    assert t["f3db_hz"] == pytest.approx(1.0 / (2.0 * math.pi * 0.5),
                                         rel=1e-12)
    # 往返回收：V_out/γ → P_in 逐位
    p_rec = t["v_out_v"] / t["gamma_v_per_w"]
    assert p_rec == pytest.approx(p_w, rel=1e-15)
    # P×2（+3.0103dB）→ V×2 逐位
    t2 = _run("thermal_power_sensor_detect", {**_TC, "p_in_dbm": -20.0
                                              + 3.0102999566398})
    assert t2["v_out_v"] == pytest.approx(2.0 * t["v_out_v"], rel=1e-12)


def test_thermal_bolometer_and_cross_type_identity():
    """bolometer γ 重算+R0 不进输出+同 γ 跨类型输出逐位一致（结构恒等）。"""
    b = _run("thermal_power_sensor_detect", {"sensor_type": "bolometer",
                                             "p_in_dbm": -20.0,
                                             "r_th_k_per_w": 500.0,
                                             "c_th_j_per_k": 1e-3,
                                             "tcr_per_k": 4.0e-3,
                                             "v_bridge_v": 8.0,
                                             "r0_ohm": 100.0})
    gamma_hand = 8.0 / 4.0 * 4.0e-3 * 1.0 * 500.0
    assert b["gamma_v_per_w"] == pytest.approx(gamma_hand, rel=1e-15)
    assert b["r0_ohm"] == 100.0  # 只进报告面
    b_no_r0 = _run("thermal_power_sensor_detect", {"sensor_type": "bolometer",
                                                   "p_in_dbm": -20.0,
                                                   "r_th_k_per_w": 500.0,
                                                   "c_th_j_per_k": 1e-3,
                                                   "tcr_per_k": 4.0e-3,
                                                   "v_bridge_v": 8.0})
    assert b_no_r0["v_out_v"] == b["v_out_v"]  # R0 绝对值无关恒等
    # 同 γ 跨类型：热偶 S=8mV/K → γ=8mV/K·500K/W=4V/W == bolometer γ
    tc_same = _run("thermal_power_sensor_detect",
                   {**_TC, "seebeck_v_per_k": 8.0e-3})
    assert tc_same["gamma_v_per_w"] == b["gamma_v_per_w"]
    assert tc_same["v_out_v"] == b["v_out_v"]
    assert tc_same["delta_t_k"] == b["delta_t_k"]
    assert tc_same["tau_s"] == b["tau_s"]


def test_thermal_noise_floor_and_guards():
    """P_min=v_noise/|γ| 回收+守卫族（类型/跨类型互斥/TCR≠0/域/η）。"""
    t = _run("thermal_power_sensor_detect", {**_TC, "p_in_dbm": -60.0,
                                             "v_noise_rms_v": 1e-6})
    p_min_hand = 1e-6 / (2.0e-4 * 500.0)
    assert t["p_min_w"] == pytest.approx(p_min_hand, rel=1e-12)
    assert t["p_min_dbm"] == pytest.approx(10.0 * math.log10(p_min_hand)
                                           + 30.0, rel=1e-12)
    _reject("thermal_power_sensor_detect",
            {"sensor_type": "thermistor", "p_in_dbm": -20.0,
             "r_th_k_per_w": 500.0, "c_th_j_per_k": 1e-3}, "sensor_type")
    _reject("thermal_power_sensor_detect",
            {"sensor_type": "thermocouple", "p_in_dbm": -20.0,
             "r_th_k_per_w": 500.0, "c_th_j_per_k": 1e-3}, "seebeck_v_per_k")
    _reject("thermal_power_sensor_detect",
            {**_TC, "tcr_per_k": 1e-3}, "tcr_per_k")
    _reject("thermal_power_sensor_detect",
            {"sensor_type": "bolometer", "p_in_dbm": -20.0,
             "r_th_k_per_w": 500.0, "c_th_j_per_k": 1e-3}, "tcr_per_k")
    _reject("thermal_power_sensor_detect",
            {"sensor_type": "bolometer", "p_in_dbm": -20.0,
             "r_th_k_per_w": 500.0, "c_th_j_per_k": 1e-3,
             "tcr_per_k": 0.0, "v_bridge_v": 8.0}, "tcr_per_k")
    _reject("thermal_power_sensor_detect",
            {**_TC, "p_in_dbm": 31.0}, "p_in_dbm")
    _reject("thermal_power_sensor_detect",
            {**_TC, "p_in_dbm": -121.0}, "p_in_dbm")
    _reject("thermal_power_sensor_detect",
            {**_TC, "eta_abs": 1.5}, "eta_abs")
    _reject("thermal_power_sensor_detect",
            {**_TC, "r_th_k_per_w": 0.0}, "r_th_k_per_w")
