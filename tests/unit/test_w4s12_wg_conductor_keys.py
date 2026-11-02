"""aurora_j W4-S12 波导+导体域三键锚树（2026-10-23）。

候选定稿 runs/aurora_j/w4_candidates.md §1.3 A1-A3：
- conductor_surface_impedance（薄注册，公式单源 core/conductor_loss）
- wg_evanescent_attenuation（wg_evanescent.py）
- cavity_tm010_perturbation_shift（cavity.py 原位扩展）

数值锚口径（#118：锚值先独立实测后写死，不赌推导）：
- A1：铜 σ=5.8e7 @1GHz 教科书值逐位锚（独立脚本 scipy/numpy 复算：
  δ=2.089806784e-6 m=2.0898µm、Rs=8.250226499069e-3 Ω/sq）+Rs·σ·δ=1
  恒等式构造级残差+μr 幂律标度精确锚+薄度逐位（wrapper vs core 直调）。
- A2：WR-90 fc=6.557140376202975 GHz 教科书锚；α 两式恒等（√(kc²−k²)
  独立代数路径 rel≤1e-12）；深截止 α→kc 极限；f→fc⁻ α→0 连续性；ηc
  纯虚/模量锚（ηc@5GHz=444.1Ω 档独立复算）；行波区/边界显式拒绝。
- A3：合成样品回收（#340 合成回收钉）：已知 εr→正解 Δf→反解回收（逐位
  级）；x01/J1² 锚（scipy jn_zeros/j1 独立复算 x01=2.4048255576957724、
  J1²=0.269514123941917、2J1²=0.539028247883834=文献 0.539 圆整）；
  细杆极限 F→(Vs/Vc)/J1² 相对偏差 ~ (k·rs)²/4 量级锚；MSI 93.6mm 腔
  f0≈2.4518GHz（厂商页标称 2453MHz，档差 ≤1e-3 系其尺寸圆整，如实带
  注记）；Q 面正反解往返；εr≤1/Δf≥0/双给/缺基准显式拒绝。

注意：本文件只跑 fake/闭式内核（无网络无真机）。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

# ─── 独立路线锚（本文件头部独立复算写死，非实现侧产物）───────────────────────
_MU0 = 1.25663706212e-6
_EPS0 = 8.8541878128e-12
_C0 = 299792458.0


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"], out
    return out["result"]


# ═══ A1 conductor_surface_impedance ═══════════════════════════════════════

def test_a1_registered_and_group():
    assert "conductor_surface_impedance" in CALCULATOR_REGISTRY.names()
    from rfauto.core.calculators import CALC_GROUP_TABLE
    assert CALC_GROUP_TABLE["conductor_surface_impedance"] == "传输线正反解"


def test_a1_copper_1ghz_textbook_anchor():
    """铜@1GHz 教科书锚：独立复算逐位（rel 1e-12）。"""
    f_hz, sigma = 1e9, 5.8e7
    # 独立路线：δ=√(2/(ωμ0σ))、Rs=√(ωμ0/(2σ))——与实现同式异推（impl 走
    # core/conductor_loss；此处锚值独立重算+档位带）
    delta_ref = math.sqrt(2.0 / (2 * math.pi * f_hz * _MU0 * sigma))
    rs_ref = math.sqrt(2 * math.pi * f_hz * _MU0 / (2.0 * sigma))
    r = _run("conductor_surface_impedance",
             {"f_hz": f_hz, "sigma_s_per_m": sigma})
    assert r["delta_m"] == pytest.approx(delta_ref, rel=1e-12)
    assert r["rs_ohm_per_sq"] == pytest.approx(rs_ref, rel=1e-12)
    # 教科书档位带（Pozar §1.7.1 铜@1GHz：δ≈2.09µm、Rs≈8.25 mΩ/sq）
    assert r["delta_m"] == pytest.approx(2.0898e-6, rel=1e-3)
    assert r["rs_ohm_per_sq"] == pytest.approx(8.250e-3, rel=1e-3)


def test_a1_identity_and_complex_zs():
    """Rs·σ·δ=1 恒等式（构造级残差）+Zs=Rs(1+j) 45° 口径。"""
    r = _run("conductor_surface_impedance",
             {"f_hz": 2.4e9, "sigma_s_per_m": 5.8e7, "mu_r": 1.0})
    # 恒等式在实现未舍入域精确；出口 round(x,15) 对 1e-3 量级 Rs 给
    # ~1e-10 相对舍入底——容差按舍入面预声明（rel 1e-9）
    assert r["rs_ohm_per_sq"] * 5.8e7 * r["delta_m"] == pytest.approx(
        1.0, rel=1e-9)
    zs = r["zs_complex"]
    assert zs[0] == pytest.approx(zs[1], rel=1e-12)
    assert zs[0] == pytest.approx(r["rs_ohm_per_sq"], rel=1e-12)
    assert r["zs_mag_ohm"] == pytest.approx(
        r["rs_ohm_per_sq"] * math.sqrt(2.0), rel=1e-12)


def test_a1_mur_power_law_scaling():
    """μr 幂律标度：μr×4 → δ×½（δ∝1/√μr）、Rs×2（Rs∝√μr）精确。"""
    base = _run("conductor_surface_impedance",
                {"f_hz": 1e9, "sigma_s_per_m": 5.8e7})
    q = _run("conductor_surface_impedance",
             {"f_hz": 1e9, "sigma_s_per_m": 5.8e7, "mu_r": 4.0})
    assert q["delta_m"] == pytest.approx(0.5 * base["delta_m"], rel=1e-12)
    assert q["rs_ohm_per_sq"] == pytest.approx(
        2.0 * base["rs_ohm_per_sq"], rel=1e-12)


def test_a1_thin_wrapper_bitwise_vs_core():
    """薄度守卫：wrapper 输出与 core 直调逐位一致（polarization_reg 先例）。"""
    from rfauto.core.conductor_loss import skin_depth, smooth_surface_resistance
    r = _run("conductor_surface_impedance",
             {"f_hz": 10e9, "sigma_s_per_m": 5.8e7})
    assert r["delta_m"] == round(skin_depth(10e9, 5.8e7), 15)
    assert r["rs_ohm_per_sq"] == round(smooth_surface_resistance(10e9, 5.8e7),
                                       15)


def test_a1_guards():
    for bad in ({"f_hz": 0.0, "sigma_s_per_m": 5.8e7},
                {"f_hz": 1e9, "sigma_s_per_m": -1.0},
                {"f_hz": 1e9, "sigma_s_per_m": 5.8e7, "mu_r": 0.0},
                {"f_hz": 1e9, "sigma_s_per_m": 5.8e7, "mu_r": True},
                {"f_hz": True, "sigma_s_per_m": 5.8e7}):
        out = run_calculator("conductor_surface_impedance", bad)
        assert out["ok"] is False and out.get("error"), bad


# ═══ A2 wg_evanescent_attenuation ═════════════════════════════════════════

def test_a2_registered_and_group():
    assert "wg_evanescent_attenuation" in CALCULATOR_REGISTRY.names()
    from rfauto.core.calculators import CALC_GROUP_TABLE
    assert CALC_GROUP_TABLE["wg_evanescent_attenuation"] == "传输线正反解"


def test_a2_wr90_fc_textbook_anchor():
    """WR-90（a=22.86mm）TE10 截止 fc=6.5571GHz 教科书锚。"""
    r = _run("wg_evanescent_attenuation", {"a_mm": 22.86, "f_ghz": 5.0})
    fc_ref = _C0 / (2 * 0.02286)
    assert r["fc_ghz"] == pytest.approx(fc_ref / 1e9, rel=1e-12)
    assert r["fc_ghz"] == pytest.approx(6.5571, rel=1e-5)
    assert r["kc_rad_per_m"] == pytest.approx(math.pi / 0.02286, rel=1e-12)


def test_a2_alpha_two_path_identity_and_value():
    """α 两式恒等（√(kc²−k²) vs k√((fc/f)²−1) 独立代数路径，rel≤1e-12）。

    锚值：WR-90@5GHz 独立复算 α=88.9095 Np/m（=772.26 dB/m）。
    """
    f_ghz = 5.0
    k = 2 * math.pi * f_ghz * 1e9 / _C0
    alpha_ref = math.sqrt((math.pi / 0.02286) ** 2 - k ** 2)
    r = _run("wg_evanescent_attenuation", {"a_mm": 22.86, "f_ghz": f_ghz})
    assert r["alpha_np_m"] == pytest.approx(alpha_ref, rel=1e-12)
    assert r["alpha_np_m"] == pytest.approx(88.9095, rel=1e-5)
    assert r["alpha_db_m"] == pytest.approx(
        alpha_ref * 20.0 / math.log(10.0), rel=1e-12)
    assert r["gamma_identity_rel_dev"] <= 1e-12


def test_a2_deep_cutoff_limit_and_fc_continuity():
    """深截止 α→kc 极限（f=fc/10 偏差 <0.6%）+f→fc⁻ α→0 连续性。

    连续性锚：α=k√((fc/f)²−1) 在 f/fc=1−1e-6 独立复算逐位 + α/kc<3e-3
    （√(2·(1−f/fc)) 小量行为，趋于零）。
    """
    fc = _C0 / (2 * 0.02286) / 1e9
    deep = _run("wg_evanescent_attenuation",
                {"a_mm": 22.86, "f_ghz": fc / 10.0})
    assert deep["deep_cutoff_alpha_over_kc"] == pytest.approx(1.0, rel=6e-3)
    f_near = fc * 0.999999
    k_near = 2 * math.pi * f_near * 1e9 / _C0
    alpha_ref = k_near * math.sqrt((fc / f_near) ** 2 - 1.0)
    near = _run("wg_evanescent_attenuation",
                {"a_mm": 22.86, "f_ghz": f_near})
    assert near["alpha_np_m"] == pytest.approx(alpha_ref, rel=1e-12)
    assert near["alpha_np_m"] / near["kc_rad_per_m"] < 3e-3


def test_a2_eta_evanescent_pure_imaginary():
    """ηc=jη/√((fc/f)²−1) 纯虚感抗；WR-90@5GHz 模量独立复算 444.1Ω 档。"""
    r = _run("wg_evanescent_attenuation", {"a_mm": 22.86, "f_ghz": 5.0})
    eta0 = math.sqrt(_MU0 / _EPS0)
    fc = _C0 / (2 * 0.02286)
    eta_ref = eta0 / math.sqrt((fc / 5e9) ** 2 - 1.0)
    assert r["eta_evanescent"][0] == 0.0
    assert r["eta_evanescent"][1] == pytest.approx(eta_ref, rel=1e-12)
    assert r["eta_evanescent_mag_ohm"] == pytest.approx(444.1, rel=1e-3)
    assert r["eta_evanescent_mag_ohm"] > eta0  # 深截止区 TE 倏逝感抗增大


def test_a2_fill_guard_b_optional():
    """b_mm 可选（TE10 量与 b 无关）+b>a 拒绝+εr<1/μr≤0 拒绝。"""
    r1 = _run("wg_evanescent_attenuation", {"a_mm": 22.86, "f_ghz": 5.0})
    r2 = _run("wg_evanescent_attenuation",
              {"a_mm": 22.86, "f_ghz": 5.0, "b_mm": 10.16})
    assert r1["alpha_np_m"] == r2["alpha_np_m"]
    for bad in ({"a_mm": -1.0, "f_ghz": 5.0},
                {"a_mm": 22.86, "f_ghz": 5.0, "b_mm": 30.0},
                {"a_mm": 22.86, "f_ghz": 5.0, "epsilon_r": 0.5},
                {"a_mm": 22.86, "f_ghz": 5.0, "mu_r": 0.0},
                {"a_mm": True, "f_ghz": 5.0}):
        out = run_calculator("wg_evanescent_attenuation", bad)
        assert out["ok"] is False and out.get("error"), bad


def test_a2_traveling_region_explicit_reject():
    """f≥fc 行波区显式拒绝（镜像惯例：coax 截止衰减器 f≥fc 拒绝同款）。"""
    fc = _C0 / (2 * 0.02286) / 1e9
    for f_bad in (fc, fc * 1.05, 10.0):
        out = run_calculator("wg_evanescent_attenuation",
                             {"a_mm": 22.86, "f_ghz": f_bad})
        assert out["ok"] is False and out.get("error"), f_bad


# ═══ A3 cavity_tm010_perturbation_shift ═══════════════════════════════════

def test_a3_registered_and_group():
    assert "cavity_tm010_perturbation_shift" in CALCULATOR_REGISTRY.names()
    from rfauto.core.calculators import CALC_GROUP_TABLE
    assert (CALC_GROUP_TABLE["cavity_tm010_perturbation_shift"]
            == "谐振器与腔体")


def test_a3_f0_and_bessel_constants():
    """f0=x01·c/2πa 与 Bessel 常数锚（scipy 独立复算逐位+文献圆整档）。"""
    from scipy.special import j1, jn_zeros

    x01_ref = float(jn_zeros(0, 1)[0])
    r = _run("cavity_tm010_perturbation_shift",
             {"a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
              "sample_height_mm": 50.0, "epsilon_r": 2.1})
    assert r["x01"] == pytest.approx(x01_ref, rel=1e-14)
    assert r["x01"] == pytest.approx(2.4048255576957724, rel=1e-14)
    assert r["j1_sq_x01"] == pytest.approx(
        float(j1(x01_ref)) ** 2, rel=1e-12)
    assert r["j1_sq_x01"] == pytest.approx(0.269514123941917, rel=1e-9)
    # 文献通行 TM010 几何常数=0.539（=2J1² 三位圆整）/0.269（=J1² 三位
    # 截断式书写——0.2695 的三位圆整应为 0.270，通行书写与真值差 ≤2e-3，
    # 故档位 rel 5e-3）
    assert r["two_j1_sq"] == pytest.approx(0.539, rel=5e-3)
    assert r["j1_sq_x01"] == pytest.approx(0.269, rel=5e-3)
    assert r["f0_ghz"] == pytest.approx(
        x01_ref * _C0 / (2 * math.pi * 0.0468) / 1e9, rel=1e-12)
    # MSI 93.6mm 直径腔标称 2453MHz（厂商页尺寸圆整档差 ≤1e-3，如实）
    assert r["f0_ghz"] == pytest.approx(2.453, rel=1e-3)


def test_a3_filling_factor_exact_vs_thin_rod():
    """F 精确场权 vs 细杆极限 (Vs/Vc)/J1²：rs=2mm 腔 a=46.8mm 偏差 <0.3%。"""
    from scipy.special import j0, j1, jn_zeros

    x01 = float(jn_zeros(0, 1)[0])
    a_m, h_m, rs_m, hs_m = 0.0468, 0.05, 0.002, 0.05
    kr = x01 / a_m * rs_m
    f_exact = (math.pi * rs_m ** 2 * hs_m
               * (float(j0(kr)) ** 2 + float(j1(kr)) ** 2)) / (
        math.pi * a_m ** 2 * h_m * float(j1(x01)) ** 2)
    f_thin = (math.pi * rs_m ** 2 * hs_m) / (
        math.pi * a_m ** 2 * h_m) / float(j1(x01)) ** 2
    r = _run("cavity_tm010_perturbation_shift",
             {"a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
              "sample_height_mm": 50.0, "epsilon_r": 2.1})
    assert r["filling_factor"] == pytest.approx(f_exact, rel=1e-12)
    assert r["filling_factor"] == pytest.approx(f_thin, rel=3e-3)


def test_a3_forward_inverse_roundtrip_recovery():
    """合成样品回收（#340 钉）：已知 εr→正解 Δf→反解回收（1e-10 级）。"""
    geom = {"a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
            "sample_height_mm": 50.0}
    fwd = _run("cavity_tm010_perturbation_shift",
               {**geom, "epsilon_r": 2.1})
    assert fwd["route"] == "forward_shift"
    assert fwd["df_ghz"] < 0.0
    inv = _run("cavity_tm010_perturbation_shift",
               {**geom, "df_ghz": fwd["df_ghz"]})
    assert inv["route"] == "inverse_eps_r"
    assert inv["epsilon_r"] == pytest.approx(2.1, rel=1e-10)
    # 微扰定理方向自检：εr↑ → 频移更负（单调）
    fwd3 = _run("cavity_tm010_perturbation_shift",
                {**geom, "epsilon_r": 3.0})
    assert fwd3["df_ghz"] < fwd["df_ghz"] < 0.0


def test_a3_q_face_roundtrip():
    """Q 面往返：tanδ+Q0→Qs 正解 / Qs+Q0→εr″、tanδ 反解（1e-10 级）。"""
    geom = {"a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
            "sample_height_mm": 50.0}
    fwd = _run("cavity_tm010_perturbation_shift",
               {**geom, "epsilon_r": 2.1, "tan_delta": 1e-3,
                "q_empty": 8925.0})
    assert fwd["q_sample"] < fwd["q_empty"]
    # 独立路线：1/Qs−1/Q0 = εr″·F = εr′·tanδ·F
    expect_dq = 2.1 * 1e-3 * fwd["filling_factor"]
    assert fwd["delta_inv_q"] == pytest.approx(expect_dq, rel=1e-10)
    inv = _run("cavity_tm010_perturbation_shift",
               {**geom, "df_ghz": fwd["df_ghz"],
                "q_sample": fwd["q_sample"], "q_empty": 8925.0})
    assert inv["epsilon_r_double"] == pytest.approx(2.1e-3, rel=1e-9)
    assert inv["tan_delta"] == pytest.approx(1e-3, rel=1e-9)


def test_a3_guards():
    geom = {"a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
            "sample_height_mm": 50.0}
    for bad in (
        {**geom, "epsilon_r": 2.1, "df_ghz": -0.01},          # 双给
        {**geom},                                              # 双缺
        {**geom, "epsilon_r": 0.9},                            # εr≤1
        {**geom, "epsilon_r": 1.0},
        {**geom, "df_ghz": 0.01},                              # df≥0
        {**geom, "epsilon_r": 2.1, "tan_delta": 1e-3,
         "q_sample": 7000.0, "q_empty": 8925.0},               # Q 面双给
        {**geom, "epsilon_r": 2.1, "tan_delta": 1e-3},         # Q 面缺基准
        {**geom, "epsilon_r": 2.1, "q_empty": 8925.0},         # Q 面单给
        {**geom, "a_mm": 1.0, "sample_radius_mm": 2.0},        # rs≥a
        {**geom, "epsilon_r": 2.1, "sample_height_mm": 60.0},  # hs>h
        {**geom, "epsilon_r": 2.1, "h_mm": -1.0},
        {**geom, "epsilon_r": 2.1, "q_empty": True},           # bool
    ):
        out = run_calculator("cavity_tm010_perturbation_shift", bad)
        assert out["ok"] is False and out.get("error"), bad
