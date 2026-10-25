"""aurora_f W2-S6 内核池件批 2 锚树：D2 混频器变换面 + D4 定向电桥 + D8 射频开关件面。

三域八键（R2_core_tier3 §③ D2/D4/D8 立项）。#118 双源口径：每个闭式
锚都由测试侧独立重算（不同代数路线/常数链），不赌实现自身推导；
同仓双源（跨键/跨族）互证逐位。empirical 档如实（SPDT 切换时间常数
不产数字，见 rf_switch.py 模块 docstring 注记）。
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

_SPLIT_DB = 10.0 * math.log10(2.0)          # 3.0102999566398120
_T0_K = 290.0


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"], f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


# ─── D2 键 1：mixer_ssb_nf（镜像噪声折入）────────────────────────────────────

def test_mixer_ssb_nf_3db_fold_limit_exact():
    """IR=0/t=1 → fold=+3.0103dB 教科书 3dB 极限逐位；完美抑制→0。"""
    r = _run("mixer_ssb_nf", {"nf_dsb_db": 6.0, "image_rejection_db": 0.0,
                              "t_image_ratio": 1.0})
    assert r["fold_db"] == pytest.approx(_SPLIT_DB, abs=1e-12)
    assert r["nf_ssb_db"] == pytest.approx(6.0 + _SPLIT_DB, abs=1e-12)
    r_inf = _run("mixer_ssb_nf", {"nf_dsb_db": 6.0,
                                  "image_rejection_db": None})
    assert r_inf["fold_db"] == 0.0
    assert r_inf["nf_ssb_db"] == pytest.approx(6.0, abs=1e-12)
    r_cold = _run("mixer_ssb_nf", {"nf_dsb_db": 6.0, "t_image_ratio": 0.0})
    assert r_cold["fold_db"] == 0.0


def test_mixer_ssb_nf_identity_independent_recompute():
    """恒等式 F_SSB=(1+g·t)·F_DSB 测试侧独立重算（一般点）。"""
    for nf_dsb, ir, t in ((6.0, 20.0, 0.7), (3.5, 40.0, 1.0), (9.0, 10.0, 0.3)):
        r = _run("mixer_ssb_nf", {"nf_dsb_db": nf_dsb,
                                  "image_rejection_db": ir,
                                  "t_image_ratio": t})
        g = 10.0 ** (-ir / 10.0)
        f_dsb = 10.0 ** (nf_dsb / 10.0)
        nf_ssb_ref = 10.0 * math.log10((1.0 + g * t) * f_dsb)
        assert r["nf_ssb_db"] == pytest.approx(nf_ssb_ref, abs=1e-12)
        assert r["t_ssb_k"] == pytest.approx(
            _T0_K * ((1.0 + g * t) * f_dsb - 1.0), rel=1e-12)
        assert r["fold_residual_db"] <= 1e-12


def test_mixer_ssb_nf_guards():
    """负 NF/负 IR/t 越界显式拒绝（ok=False 信封）。"""
    for params in ({"nf_dsb_db": -1.0},
                   {"nf_dsb_db": 6.0, "image_rejection_db": -3.0},
                   {"nf_dsb_db": 6.0, "t_image_ratio": 1.5}):
        out = run_calculator("mixer_ssb_nf", params)
        assert out["ok"] is False


# ─── D2 键 2：mixer_conversion_loss（变频损耗 SSB/DSB 口径）─────────────────

def test_mixer_cl_split_identity_and_recompute():
    """SSB/DSB 等分恒等式 +3.0103dB 逐位；增益线性测试侧重算。"""
    r = _run("mixer_conversion_loss", {"conversion_loss_ssb_db": 6.0,
                                       "iip3_dbm": 15.0})
    assert r["gain_dsb_db"] == pytest.approx(r["gain_ssb_db"] + _SPLIT_DB,
                                             abs=1e-12)
    assert r["conversion_loss_dsb_db"] == pytest.approx(6.0 - _SPLIT_DB,
                                                        abs=1e-12)
    assert r["gain_ssb_linear"] == pytest.approx(10.0 ** (-0.6), rel=1e-12)
    assert r["oip3_dbm"] == pytest.approx(15.0 - 6.0, abs=1e-12)


def test_mixer_cl_passive_floor_crosskey_double_source():
    """无源混频噪声地板与 mixer_ssb_nf 跨键互证：F_SSB=2·F_DSB=CL_lin。"""
    cl = 6.0
    r = _run("mixer_conversion_loss", {"conversion_loss_ssb_db": cl})
    nf_floor_dsb = r["nf_floor_dsb_db"]
    assert nf_floor_dsb == pytest.approx(cl - _SPLIT_DB, abs=1e-12)
    assert r["nf_floor_ssb_db"] == pytest.approx(cl, abs=1e-12)
    # 跨键：以地板 DSB-NF+无镜像抑制喂 ssb_nf → SSB-NF 必须逐位回到 CL
    r2 = _run("mixer_ssb_nf", {"nf_dsb_db": nf_floor_dsb,
                               "image_rejection_db": 0.0,
                               "t_image_ratio": 1.0})
    assert r2["nf_ssb_db"] == pytest.approx(cl, abs=1e-9)


def test_mixer_cl_guards():
    out = run_calculator("mixer_conversion_loss",
                         {"conversion_loss_ssb_db": -0.1})
    assert out["ok"] is False


# ─── D2 键 3：mixer_image_plan（镜像规划 + IRR 同式双源）────────────────────

def test_mixer_image_plan_geometry_exact():
    """低/高本振镜像几何：f_IF、f_image=f_LO∓f_IF、间距 2f_IF 恒等逐位。"""
    r = _run("mixer_image_plan", {"f_rf_hz": 1575.42e6, "f_lo_hz": 1500.0e6})
    assert r["injection_side"] == "low"
    assert r["f_if_hz"] == pytest.approx(75.42e6, abs=1e-3)
    assert r["f_image_hz"] == pytest.approx(1500.0e6 - 75.42e6, abs=1e-3)
    assert r["image_offset_hz"] == pytest.approx(2.0 * 75.42e6, abs=1e-3)
    assert r["lo_offset_sensitivity"] == 1.0
    r_hi = _run("mixer_image_plan", {"f_rf_hz": 1500.0e6, "f_lo_hz": 1575.42e6})
    assert r_hi["injection_side"] == "high"
    assert r_hi["f_image_hz"] == pytest.approx(1575.42e6 + 75.42e6, abs=1e-3)
    assert r_hi["image_offset_hz"] == pytest.approx(2.0 * 75.42e6, abs=1e-3)


def test_mixer_image_plan_irr_same_formula_crosskey():
    """IRR 与 iq_imbalance_irr 同式独立复算——同仓双源互证逐位。"""
    for a_db, phi in ((0.5, 5.0), (1.0, -10.0), (0.0, 30.0)):
        r = _run("mixer_image_plan", {"f_rf_hz": 1575.42e6,
                                      "f_lo_hz": 1500.0e6,
                                      "amp_imbalance_db": a_db,
                                      "phase_imbalance_deg": phi})
        r_ref = _run("iq_imbalance_irr", {"amp_imbalance_db": a_db,
                                          "phase_imbalance_deg": phi})
        assert r["irr_db"] == pytest.approx(r_ref["irr_db"], abs=1e-9)


def test_mixer_image_plan_guards():
    """零中频（镜像=信号）与负频镜像（f_LO<f_IF）显式拒绝。"""
    out = run_calculator("mixer_image_plan",
                         {"f_rf_hz": 1500.0e6, "f_lo_hz": 1500.0e6})
    assert out["ok"] is False
    out = run_calculator("mixer_image_plan",
                         {"f_rf_hz": 1800.0e6, "f_lo_hz": 500.0e6})
    assert out["ok"] is False  # f_LO<f_IF → 镜像落负频轴（无物理镜像面）


# ─── D4 键 1：directional_bridge_s_matrix（电阻反射计桥 S 矩阵）─────────────

_IDEAL_S = [[0.0, 0.5, 0.0], [0.5, 0.0, -0.5], [0.0, -0.5, 0.0]]


def _independent_bridge_s(r1: float, r2: float, r3: float):
    """测试侧独立节点分析（numpy linalg.solve，与实现高斯消元异路线）。

    激励 p∈{1,2,3}，未知 [V_A, V_M1, V_M2]：
      A : (g1+g3+1)xA − g1 x1 − g3 x2 = 2a1
      M1: −g1 xA + (g1+g2+1)x1 − x2 = 2a3
      M2: −g3 xA − x1 + (g3+2)x2 = 2a2 − 2a3
    """
    import numpy as np
    g1, g2, g3 = 1.0 / r1, 1.0 / r2, 1.0 / r3
    m = np.array([[g1 + g3 + 1.0, -g1, -g3],
                  [-g1, g1 + g2 + 1.0, -1.0],
                  [-g3, -1.0, g3 + 2.0]])
    s = [[0j] * 3 for _ in range(3)]
    for col, (a1, a2, a3) in enumerate(((1, 0, 0), (0, 1, 0), (0, 0, 1))):
        x = np.linalg.solve(m, np.array([2 * a1, 2 * a3, 2 * a2 - 2 * a3]))
        xa, x1, x2 = x
        b = (xa - a1, x2 - a2, (x1 - x2) - a3)
        for row in range(3):
            s[row][col] = complex(b[row])
    return s


def test_bridge_s_ideal_closed_form_exact():
    """对称平衡闭式矩阵逐位（|S21|=|S32|=0.5、三口全匹配、S31=0）。"""
    r = _run("directional_bridge_s_matrix", {"z0_ohm": 50.0})
    s = r["s_matrix"]
    for i in range(3):
        for j in range(3):
            assert s[i][j][0] == pytest.approx(_IDEAL_S[i][j], abs=1e-12)
            assert s[i][j][1] == pytest.approx(0.0, abs=1e-12)
    assert r["through_loss_db"] == pytest.approx(-20.0 * math.log10(0.5),
                                                 abs=1e-12)
    assert r["reflection_coupling_db"] == pytest.approx(
        -20.0 * math.log10(0.5), abs=1e-12)
    assert r["reflection_path_db"] == pytest.approx(
        20.0 * math.log10(4.0), abs=1e-12)
    assert r["directivity_db"] is None  # S31=0 → ∞（JSON 契约）
    assert r["ideal_closed_form_residual"] <= 1e-12


def test_bridge_s_reciprocity_passivity_dissipation():
    """互易 S=Sᵀ 残差 ≤1e-15；行功率 [0.25, 0.5, 0.25]（臂耗散恒等）。"""
    r = _run("directional_bridge_s_matrix", {"z0_ohm": 50.0})
    assert r["reciprocity_residual"] <= 1e-15
    assert r["row_power_max"] <= 0.5 + 1e-12
    assert r["row2_dissipation"] == pytest.approx(0.5, abs=1e-12)


def test_bridge_s_tolerance_linear_law():
    """容差→有限方向性：S31 近线性随容差（二阶小量 ~0.5%@1%）；互易仍成立。"""
    r1 = _run("directional_bridge_s_matrix", {"arm_tolerance_pct": 0.01})
    r2 = _run("directional_bridge_s_matrix", {"arm_tolerance_pct": 0.02})
    s31_1 = r1["s31_linear"]
    s31_2 = r2["s31_linear"]
    assert s31_1 > 0.0 and s31_2 > 0.0
    assert s31_2 / s31_1 == pytest.approx(2.0, rel=0.01)
    assert r1["directivity_db"] == pytest.approx(-20.0 * math.log10(s31_1),
                                                 abs=1e-9)  # 15 位舍入地板
    assert r1["reciprocity_residual"] <= 1e-15
    # 独立节点分析重算（异路线 #118）
    s_ref = _independent_bridge_s(1.02, 0.98, 1.02)
    for i in range(3):
        for j in range(3):
            got = complex(r2["s_matrix"][i][j][0], r2["s_matrix"][i][j][1])
            assert got == pytest.approx(s_ref[i][j], abs=1e-12)


def test_bridge_s_independent_nodal_ideal():
    """理想档独立节点分析重算逐位（numpy 异路线）。"""
    r = _run("directional_bridge_s_matrix", {})
    s_ref = _independent_bridge_s(1.0, 1.0, 1.0)
    for i in range(3):
        for j in range(3):
            got = complex(r["s_matrix"][i][j][0], r["s_matrix"][i][j][1])
            assert got == pytest.approx(s_ref[i][j], abs=1e-12)


# ─── D4 键 2：directional_bridge_response（反射计响应闭式）──────────────────

def test_bridge_response_floor_identity_crosskey():
    """完美负载读回损=方向性地板恒等；与 vna_reflection_uncertainty 同值。"""
    r = _run("directional_bridge_response", {"gamma_mag": 0.0,
                                             "directivity_db": 40.0})
    assert r["rl_floor_db"] == pytest.approx(40.0, abs=1e-12)
    assert r["rl_meas_db_upper"] == pytest.approx(40.0, abs=1e-12)
    r_ref = _run("vna_reflection_uncertainty",
                 {"gamma_mag": 0.0, "directivity_db": -40.0,
                  "source_match_db": -35.0, "tracking_db": 0.05})
    assert r_ref["rl_floor_db"] == pytest.approx(r["rl_floor_db"], abs=1e-12)


def test_bridge_response_perfect_device_exact():
    """D→∞+理想对称桥（s=0）→ Γ_meas=Γ 精确回收；含 s 项独立重算。"""
    r = _run("directional_bridge_response", {"gamma_mag": 0.3,
                                             "gamma_phase_deg": 20.0,
                                             "directivity_db": None})
    assert r["gamma_meas_mag_upper"] == pytest.approx(0.3, abs=1e-12)
    assert r["gamma_meas_mag_lower"] == pytest.approx(0.3, abs=1e-12)
    assert r["dominant_error"] == "none_perfect"
    r_s = _run("directional_bridge_response", {"gamma_mag": 0.5,
                                               "directivity_db": None,
                                               "source_match_loss_db": 10.0})
    g = 0.5
    s = 10.0 ** (-10.0 / 20.0)
    hi = g / (1.0 - g * s)
    lo = g / (1.0 + g * s)
    assert r_s["gamma_meas_mag_upper"] == pytest.approx(hi, abs=1e-12)
    assert r_s["gamma_meas_mag_lower"] == pytest.approx(lo, abs=1e-12)


def test_bridge_response_small_gamma_asymptote():
    """|Γ|≪1 单方向性项支配：Γ_meas≈Γ+d 渐近残差→小量；主导项判别。"""
    r = _run("directional_bridge_response", {"gamma_mag": 0.01,
                                             "directivity_db": 30.0})
    assert r["dominant_error"] == "directivity"
    assert r["small_gamma_asymptote_residual"] <= 1e-6
    d = 10.0 ** (-30.0 / 20.0)
    assert r["directivity_error_linear"] == pytest.approx(d, rel=1e-12)


# ─── D8 键 1：pin_switch_s2p（PIN 两态 S + cutoff FOM）───────────────────────

def test_pin_series_state_formulas_recompute():
    """串联两态公式测试侧独立重算；fc FOM=1/(2πR_onC_off) 逐位。"""
    r = _run("pin_switch_s2p", {"topology": "series", "r_on_ohm": 1.0,
                                "c_off_f": 0.1e-12,
                                "freq_ghz": [1.0, 2.0, 4.0, 8.0]})
    z0 = 50.0
    s21_on = 2.0 * z0 / (2.0 * z0 + 1.0)
    assert r["state_on"] == "through" and r["state_off"] == "isolation"
    assert isinstance(r["il_through_db"], float)
    assert isinstance(r["isolation_db"], list)
    assert r["il_through_db"] == pytest.approx(-20.0 * math.log10(s21_on),
                                               abs=1e-12)
    assert r["fc_fom_hz"] == pytest.approx(
        1.0 / (2.0 * math.pi * 1.0 * 0.1e-12), rel=1e-12)
    for f, iso in zip(r["freq_ghz"], r["isolation_db"], strict=True):
        w = 2.0 * math.pi * f * 1e9
        z = abs(1.0 / (w * 0.1e-12))
        s21_off = 2.0 * z0 / math.hypot(2.0 * z0, z)
        assert iso == pytest.approx(-20.0 * math.log10(s21_off), abs=1e-9)
    # 隔离随频率近 +6dB/倍频程（低频渐近 1/(ωC) 幂律；精确式含 2Z0 项
    # → 偏差 ~0.05dB@1GHz 档，abs=0.1 如实）
    assert (r["isolation_db"][0] - r["isolation_db"][1]) == pytest.approx(
        6.0206, abs=0.1)


def test_pin_ideal_limit_and_shunt_states():
    """R_on→0/C_off→0 理想极限（插损 0/隔离 ∞）；并联拓扑状态语义。"""
    r = _run("pin_switch_s2p", {"topology": "series", "r_on_ohm": 1e-9,
                                "c_off_f": 1e-18, "freq_ghz": [2.0]})
    assert r["il_through_db"] <= 1e-6
    iso_ref = -20.0 * math.log10(2.0 * 50.0 * 2.0 * math.pi * 2e9 * 1e-18)
    assert r["isolation_db"][0] == pytest.approx(iso_ref, abs=1e-6)  # ~118dB
    r_sh = _run("pin_switch_s2p", {"topology": "shunt", "r_on_ohm": 2.0,
                                   "c_off_f": 0.05e-12, "freq_ghz": [2.0]})
    assert r_sh["state_on"] == "isolation"
    assert r_sh["state_off"] == "through"
    # 并联导通隔离（标量面）测试侧重算：|S21|=2/(2+Z0/R_on)
    s21_iso = 2.0 / (2.0 + 50.0 / 2.0)
    assert r_sh["isolation_db"] == pytest.approx(
        -20.0 * math.log10(s21_iso), abs=1e-12)
    # 并联截止直通插损（逐频列表）=容性小量
    w = 2.0 * math.pi * 2.0 * 1e9
    s21_thru = abs(2.0 / (2.0 + 1j * w * 0.05e-12 * 50.0))
    assert r_sh["il_through_db"][0] == pytest.approx(
        -20.0 * math.log10(s21_thru), abs=1e-12)
    out = run_calculator("pin_switch_s2p",
                         {"topology": "spdt", "r_on_ohm": 1.0,
                          "c_off_f": 0.1e-12, "freq_ghz": [2.0]})
    assert out["ok"] is False


def test_pin_fc_product_scaling():
    """R_on·C_off 乘积单值标度：乘×2 → fc 恰 /4（FOM 恒等式）。"""
    r1 = _run("pin_switch_s2p", {"topology": "series", "r_on_ohm": 1.0,
                                 "c_off_f": 0.1e-12, "freq_ghz": [2.0]})
    r2 = _run("pin_switch_s2p", {"topology": "series", "r_on_ohm": 2.0,
                                 "c_off_f": 0.2e-12, "freq_ghz": [2.0]})
    assert r2["fc_fom_hz"] == pytest.approx(r1["fc_fom_hz"] / 4.0, rel=1e-12)


# ─── D8 键 2：rf_switch_spdt_quarter_wave（λ/4 SPDT 频响）───────────────────

def test_spdt_ideal_limit_at_f0():
    """R_on→0/C_off→0 理想极限：f0 处插损→0、回损→0、隔离→巨。"""
    r = _run("rf_switch_spdt_quarter_wave",
             {"f0_ghz": 2.0, "r_on_ohm": 1e-9, "c_off_f": 1e-18,
              "freq_ghz": [2.0]})
    assert r["il_at_f0_db"] <= 1e-6
    assert r["s11_db"][0] >= 120.0
    assert r["iso_at_f0_db"] >= 200.0


def test_spdt_f0_isolation_asymptote_formula():
    """f0 隔离≈20log10(Z0/R_on) 渐近（C_off 修正小量）+无源性 |b|≤1 档。"""
    r_on = 2.0
    r = _run("rf_switch_spdt_quarter_wave",
             {"f0_ghz": 2.0, "r_on_ohm": r_on, "c_off_f": 0.05e-12,
              "freq_ghz": [2.0]})
    asymptote = 20.0 * math.log10(50.0 / r_on)
    assert r["iso_at_f0_db"] == pytest.approx(asymptote, abs=1.5)
    assert r["iso_at_f0_db"] >= asymptote - 1.5  # 不劣于渐近带
    assert r["il_at_f0_db"] <= 0.5  # 直通插损小量（0.05pF@2GHz 二阶）


def test_spdt_detune_bandwidth_semantics_and_len():
    """λ/4 失谐退化（f0/2 隔离 < f0 隔离=开关带宽语义）；臂长/er 标度。"""
    r = _run("rf_switch_spdt_quarter_wave",
             {"f0_ghz": 2.0, "r_on_ohm": 2.0, "c_off_f": 0.05e-12,
              "freq_ghz": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]})
    idx_f0 = r["freq_ghz"].index(2.0)
    assert r["iso_db"][idx_f0] == pytest.approx(r["iso_at_f0_db"], abs=1e-12)
    assert max(r["iso_db"]) == pytest.approx(r["iso_at_f0_db"], abs=1e-9)
    assert r["iso_db"][1] < r["iso_db"][idx_f0]      # f0/2 退化
    assert r["iso_db"][-1] < r["iso_db"][idx_f0]     # 2f0 退化
    length = 299.792458 / (4.0 * 2.0 * math.sqrt(1.0))
    assert r["arm_len_mm"] == pytest.approx(length, rel=1e-12)
    r_er = _run("rf_switch_spdt_quarter_wave",
                {"f0_ghz": 2.0, "r_on_ohm": 2.0, "c_off_f": 0.05e-12,
                 "freq_ghz": [2.0], "er_eff": 4.0})
    assert r_er["arm_len_mm"] == pytest.approx(length / 2.0, rel=1e-12)


# ─── D8 键 3：rf_switch_matrix_path（开关链二态预算）─────────────────────────

def test_switch_path_additivity_identity():
    """dB 可加性恒等：N=1 退化/倍程双倍/空表零损/显式和逐位。"""
    els = [{"il_db": 0.3, "iso_db": 25.0, "gamma": 0.05},
           {"il_db": 0.5, "iso_db": 30.0},
           {"il_db": 0.2, "iso_db": 28.0, "gamma": 0.08}]
    r = _run("rf_switch_matrix_path", {"elements": els})
    assert r["total_il_db"] == pytest.approx(1.0, abs=1e-12)
    assert r["total_iso_db"] == pytest.approx(83.0, abs=1e-12)
    r_one = _run("rf_switch_matrix_path", {"elements": [els[0]]})
    assert r_one["total_il_db"] == pytest.approx(0.3, abs=1e-15)
    r_double = _run("rf_switch_matrix_path",
                    {"elements": [els[0], els[0]]})
    assert r_double["total_il_db"] == pytest.approx(2.0 * 0.3, abs=1e-15)
    assert r_double["total_iso_db"] == pytest.approx(2.0 * 25.0, abs=1e-15)
    r_empty = _run("rf_switch_matrix_path", {"elements": []})
    assert r_empty["total_il_db"] == 0.0
    assert r_empty["total_iso_db"] == 0.0


def test_switch_path_ripple_recompute_and_guards():
    """纹波界 Σ20log10(1+γ_iγ_{i+1}) 测试侧重算；gamma 缺省反推；守卫。"""
    els = [{"il_db": 0.3, "iso_db": 25.0, "gamma": 0.05},
           {"il_db": 0.5, "iso_db": 30.0, "gamma": 0.1},
           {"il_db": 0.2, "iso_db": 28.0, "gamma": 0.08}]
    r = _run("rf_switch_matrix_path", {"elements": els, "absorptive": True})
    ripple = sum(20.0 * math.log10(1.0 + els[i]["gamma"] * els[i + 1]["gamma"])
                 for i in range(2))
    assert r["mismatch_ripple_bound_db"] == pytest.approx(ripple, abs=1e-12)
    assert r["worst_case_il_db"] == pytest.approx(1.0 + ripple, abs=1e-12)
    assert r["absorptive"] is True
    # gamma 缺省按 IL 反推：γ=10^(−IL/20)（IL=0.4dB → 10^(−0.02)）
    r_def = _run("rf_switch_matrix_path",
                 {"elements": [{"il_db": 0.4, "iso_db": 20.0}]})
    assert r_def["gammas"][0] == pytest.approx(10.0 ** (-0.4 / 20.0),
                                               rel=1e-12)
    for params in ({"elements": [{"il_db": -1.0}]},
                   {"elements": [{"il_db": 0.3, "gamma": 1.2}]},
                   {"elements": "three"}):
        assert run_calculator("rf_switch_matrix_path", params)["ok"] is False


# ─── 描述形态门（八键 spec 完整性）───────────────────────────────────────────

def test_w2s6_keys_describe_shape():
    """八键描述/参数元数据完整（JSON 进出契约 + 必填参数一致）。"""
    import json
    by_name = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
    keys = ("mixer_ssb_nf", "mixer_conversion_loss", "mixer_image_plan",
            "directional_bridge_s_matrix", "directional_bridge_response",
            "pin_switch_s2p", "rf_switch_spdt_quarter_wave",
            "rf_switch_matrix_path")
    for key in keys:
        entry = by_name[key]
        assert entry["description"]
        json.dumps(entry, ensure_ascii=False)
        required = {p["name"] for p in entry["params"] if p["required"]}
        assert required == set(CALCULATOR_REGISTRY.get(key).required)
    assert by_name["directional_bridge_s_matrix"]["group"] == "测量与校准"
    assert by_name["mixer_ssb_nf"]["group"] == "收发链路·频综"
    assert by_name["pin_switch_s2p"]["group"] == "匹配·功分·衰减·耦合"
