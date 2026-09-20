"""E4 热/功率闭式族单测（§10.21 第九轮 E4 补强 / §4 WP0.2）。

裁判口径（#118：裁判=外部独立来源，不是本文件/被测实现的自我推导）：
  * IPC-2152 走线温升：KiCad 公开测试向量
    （qa/tests/common/test_track_width_calculations.cpp；系数来自
    Brooks & Adam 对 IPC-2152 数据的公开拟合 Table 3-1）；
  * 谐振温漂：f = c/(2L√ε) 非线性精确模型的一阶展开（解析）；
  * 热阻栈：手算电阻网络（串联 Σθ / 并联 1/Σ(1/θ)）；
  * 线热源：Pozar §2.7 的 2αP 闭式 + I²R' 独立代数路径；
  * 平行板击穿：E = V/d 闭式 + 裕量判定边界；
  * ECSS f·d：ECSS-E-ST-20-01C (2020) Table 5-1 的表节点原值。

确定性：无网络、无真机、无随机；纯闭式核 + service 契约。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import _ECSS_FD_TABLE, CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

THERMAL_KEYS = (
    "resonator_thermal_drift",
    "ipc2152_trace_temp_rise",
    "thermal_resistance_stack",
    "microstrip_loss_heat",
    "parallel_plate_breakdown_margin",
    "ecss_multipactor_fd",
)

# KiCad qa/tests/common/test_track_width_calculations.cpp 的公开参考电流
# （W=20 mil、Th=1 oz=1.378 mil、ΔT=10 °C 处）：给定电流应反算出 ΔT=10。
_KICAD_REF_CURRENT_EXTERNAL_1OZ = 1.4164291025677085
_KICAD_REF_CURRENT_INTERNAL_1OZ = 1.513124408404138
_KICAD_REF_CURRENT_INTERNAL_2OZ = 2.208736063285966
_WIDTH_20MIL_MM = 0.508  # 20 mil = 0.508 mm（精确）


def _run(name: str, params: dict) -> dict:
    out = run_calculator(name, params)
    assert out["ok"] is True, out
    assert isinstance(out["result"], dict)
    json.dumps(out, allow_nan=False)
    return out["result"]


def _fails(name: str, params: dict) -> dict:
    out = run_calculator(name, params)
    assert out["ok"] is False, out
    assert out.get("error")
    return out


# ─── 注册表 ──────────────────────────────────────────────────────────────────

def test_six_thermal_calculators_registered():
    names = set(CALCULATOR_REGISTRY.names())
    assert set(THERMAL_KEYS) <= names
    for key in THERMAL_KEYS:
        spec = CALCULATOR_REGISTRY.get(key)
        assert spec.description and spec.params


# ─── 1. 谐振温漂（§10.3 D14）────────────────────────────────────────────────

def test_resonator_thermal_drift_matches_d14_closed_form():
    """Δf/f = −CTE·ΔT − ½·TCDk·ΔT（D14 一阶闭式）。"""
    f0, dt, cte, tcdk = 10.0, 50.0, 16.0, -30.0
    res = _run("resonator_thermal_drift", {
        "f0_ghz": f0, "delta_t_c": dt,
        "cte_ppm_per_k": cte, "tcdk_ppm_per_k": tcdk})
    expected = -(cte + 0.5 * tcdk) * 1e-6 * dt
    assert res["df_over_f"] == pytest.approx(expected, rel=1e-12, abs=1e-15)
    assert res["df_over_f_ppm"] == pytest.approx(expected * 1e6, rel=1e-9)
    assert res["f_shifted_ghz"] == pytest.approx(f0 * (1.0 + expected), rel=1e-9)


def test_resonator_thermal_drift_terms_split_and_shifted_frequency():
    res = _run("resonator_thermal_drift", {
        "f0_ghz": 10.0, "delta_t_c": 50.0,
        "cte_ppm_per_k": 16.0, "tcdk_ppm_per_k": -30.0})
    assert res["cte_term_ppm"] == pytest.approx(-800.0)
    assert res["tcdk_term_ppm"] == pytest.approx(750.0)
    assert res["df_over_f_ppm"] == pytest.approx(
        res["cte_term_ppm"] + res["tcdk_term_ppm"])
    assert res["f_shifted_ghz"] == pytest.approx(10.0 + res["df_ghz"])


def test_resonator_thermal_drift_is_first_order_of_nonlinear_model():
    """无源交叉验证：f(T)=f0/[(1+CTE·ΔT)·√(1+TCDk·ΔT)] 的小 ΔT 一阶展开
    （L 线性进分母、ε 开方进分母 ⇒ −CTE·ΔT − ½·TCDk·ΔT；二阶项 ~1e−9）。"""
    f0, cte, tcdk = 2.4, 17.0, -45.0
    dt = 1.0
    res = _run("resonator_thermal_drift", {
        "f0_ghz": f0, "delta_t_c": dt,
        "cte_ppm_per_k": cte, "tcdk_ppm_per_k": tcdk})
    exact_ratio = (1.0 / ((1.0 + cte * 1e-6 * dt)
                          * math.sqrt(1.0 + tcdk * 1e-6 * dt))) - 1.0
    assert res["df_over_f"] == pytest.approx(exact_ratio, abs=2e-9)


def test_resonator_thermal_drift_monotonic_and_invalid():
    cold = _run("resonator_thermal_drift", {
        "f0_ghz": 5.0, "delta_t_c": -40.0,
        "cte_ppm_per_k": 20.0, "tcdk_ppm_per_k": 0.0})
    hot = _run("resonator_thermal_drift", {
        "f0_ghz": 5.0, "delta_t_c": 40.0,
        "cte_ppm_per_k": 20.0, "tcdk_ppm_per_k": 0.0})
    assert cold["df_over_f"] > 0 > hot["df_over_f"]
    _fails("resonator_thermal_drift", {
        "f0_ghz": 0.0, "delta_t_c": 10.0,
        "cte_ppm_per_k": 10.0, "tcdk_ppm_per_k": 10.0})
    _fails("resonator_thermal_drift", {
        "f0_ghz": 1.0, "delta_t_c": 10.0,
        "cte_ppm_per_k": 10.0})


# ─── 2. IPC-2152 走线温升 ────────────────────────────────────────────────────

def test_ipc2152_external_matches_kicad_reference_vector():
    res = _run("ipc2152_trace_temp_rise", {
        "width_mm": _WIDTH_20MIL_MM, "copper_oz": 1.0,
        "current_a": _KICAD_REF_CURRENT_EXTERNAL_1OZ})
    assert res["delta_t_c"] == pytest.approx(10.0, rel=1e-6)
    assert res["coefficients"] == [215.3, 2.0, -1.15, -1.0]
    assert res["layer"] == "external"


@pytest.mark.parametrize("copper_oz,current,coeff_k", [
    (1.0, _KICAD_REF_CURRENT_INTERNAL_1OZ, 200.0),
    (2.0, _KICAD_REF_CURRENT_INTERNAL_2OZ, 300.0),
])
def test_ipc2152_internal_matches_kicad_reference_vectors(
        copper_oz, current, coeff_k):
    res = _run("ipc2152_trace_temp_rise", {
        "width_mm": _WIDTH_20MIL_MM, "copper_oz": copper_oz,
        "current_a": current, "internal": True})
    assert res["delta_t_c"] == pytest.approx(10.0, rel=1e-6)
    assert res["coefficients"][0] == coeff_k
    assert res["layer"] == "internal"


def test_ipc2152_internal_not_derated_by_factor_two():
    """IPC-2152：内层不按 IPC-2221 老规矩温升 ×2（KiCad 同款断言）。"""
    params = {"width_mm": _WIDTH_20MIL_MM, "copper_oz": 1.0, "current_a": 1.5}
    ext = _run("ipc2152_trace_temp_rise", dict(params))
    internal = _run("ipc2152_trace_temp_rise", {**params, "internal": True})
    assert internal["delta_t_c"] < 2.0 * ext["delta_t_c"]


def test_ipc2152_coefficient_wiring_scaling():
    """拟合指数直接可验：a=2（I 平方）、b=−1.15、c=−1（外层）。"""
    base_p = {"width_mm": 0.5, "copper_oz": 1.0, "current_a": 1.0}
    base = _run("ipc2152_trace_temp_rise", base_p)["delta_t_c"]
    doubled_i = _run("ipc2152_trace_temp_rise",
                     {**base_p, "current_a": 2.0})["delta_t_c"]
    doubled_w = _run("ipc2152_trace_temp_rise",
                     {**base_p, "width_mm": 1.0})["delta_t_c"]
    doubled_th = _run("ipc2152_trace_temp_rise",
                      {**base_p, "copper_oz": 2.0})["delta_t_c"]
    assert doubled_i == pytest.approx(4.0 * base, rel=1e-9)
    assert doubled_w == pytest.approx(base * 2.0 ** -1.15, rel=1e-9)
    assert doubled_th == pytest.approx(base / 2.0, rel=1e-9)


def test_ipc2152_invalid_inputs_are_explicit():
    _fails("ipc2152_trace_temp_rise",
           {"width_mm": 0.0, "copper_oz": 1.0, "current_a": 1.0})
    _fails("ipc2152_trace_temp_rise",
           {"width_mm": 0.5, "copper_oz": -1.0, "current_a": 1.0})
    _fails("ipc2152_trace_temp_rise",
           {"width_mm": 0.5, "copper_oz": 1.0, "current_a": -0.1})


# ─── 3. 1-D 热阻栈 ────────────────────────────────────────────────────────────

def test_thermal_stack_series_hand_calculation():
    """手算：θ=1+2+3=6 °C/W，P=5 W，Ta=25 °C → Tj=55 °C。"""
    res = _run("thermal_resistance_stack", {
        "power_w": 5.0, "ambient_c": 25.0, "theta_jc_c_per_w": 1.0,
        "theta_cs_c_per_w": 2.0, "theta_sa_c_per_w": 3.0})
    assert res["theta_series_c_per_w"] == pytest.approx(6.0)
    assert res["theta_parallel_c_per_w"] is None
    assert res["theta_total_c_per_w"] == pytest.approx(6.0)
    assert res["junction_temp_c"] == pytest.approx(55.0)
    assert res["delta_t_c"] == pytest.approx(30.0)


def test_thermal_stack_parallel_hand_calculation():
    """手算：链 6 与并联 1/(1/10+1/15)=6 并联 → 3 °C/W → Tj=40 °C。"""
    res = _run("thermal_resistance_stack", {
        "power_w": 5.0, "ambient_c": 25.0, "theta_jc_c_per_w": 1.0,
        "theta_cs_c_per_w": 2.0, "theta_sa_c_per_w": 3.0,
        "parallel_paths_c_per_w": [10.0, 15.0]})
    assert res["theta_parallel_c_per_w"] == pytest.approx(6.0)
    assert res["theta_total_c_per_w"] == pytest.approx(3.0)
    assert res["junction_temp_c"] == pytest.approx(40.0)
    assert res["parallel_count"] == 2


def test_thermal_stack_invalid_inputs_are_explicit():
    _fails("thermal_resistance_stack",
           {"power_w": -1.0, "ambient_c": 25.0, "theta_jc_c_per_w": 1.0})
    _fails("thermal_resistance_stack",
           {"power_w": 1.0, "ambient_c": 25.0, "theta_jc_c_per_w": -1.0})
    _fails("thermal_resistance_stack", {
        "power_w": 1.0, "ambient_c": 25.0, "theta_jc_c_per_w": 0.0,
        "parallel_paths_c_per_w": [5.0]})
    _fails("thermal_resistance_stack", {
        "power_w": 1.0, "ambient_c": 25.0, "theta_jc_c_per_w": 1.0,
        "parallel_paths_c_per_w": [0.0]})


# ─── 4. 微带损耗 → 等效线热源 ─────────────────────────────────────────────────

_MU0 = 4.0e-7 * math.pi
_SIGMA_CU = 5.8e7
_C_MS = 299792458.0


def test_microstrip_loss_heat_conductor_matches_skin_effect_closed_form():
    params = {"freq_ghz": 10.0, "power_w": 1.0, "z0_ohm": 50.0,
              "eps_eff": 3.66, "tand": 0.0037, "width_mm": 1.113}
    res = _run("microstrip_loss_heat", dict(params))
    omega = 2.0 * math.pi * 10e9
    r_sheet = math.sqrt(omega * _MU0 / (2.0 * _SIGMA_CU))
    r_prime = r_sheet / (1.113e-3)
    alpha_c = r_prime / (2.0 * 50.0)
    assert res["r_sheet_ohm_per_sq"] == pytest.approx(r_sheet, rel=1e-12)
    assert res["alpha_conductor_np_per_m"] == pytest.approx(alpha_c, rel=1e-9)
    # 独立代数路径：P_c/m = I_rms²·R'，I_rms²=P/Z0（行波）
    i_sq = 1.0 / 50.0
    assert res["p_conductor_w_per_m"] == pytest.approx(
        i_sq * r_prime, rel=1e-9)


def test_microstrip_loss_heat_dielectric_matches_closed_form():
    params = {"freq_ghz": 10.0, "power_w": 1.0, "z0_ohm": 50.0,
              "eps_eff": 3.66, "tand": 0.0037, "width_mm": 1.113}
    res = _run("microstrip_loss_heat", dict(params))
    alpha_d = math.pi * 10e9 * 0.0037 * math.sqrt(3.66) / _C_MS
    assert res["alpha_dielectric_np_per_m"] == pytest.approx(alpha_d, rel=1e-12)
    assert res["p_dielectric_w_per_m"] == pytest.approx(
        2.0 * alpha_d, rel=1e-9)
    assert res["p_loss_w_per_m"] == pytest.approx(
        res["p_conductor_w_per_m"] + res["p_dielectric_w_per_m"])


def test_microstrip_loss_heat_surface_density_and_monotonic():
    params = {"freq_ghz": 10.0, "power_w": 1.0, "z0_ohm": 50.0,
              "eps_eff": 3.66, "tand": 0.0037, "width_mm": 1.113}
    res = _run("microstrip_loss_heat", dict(params))
    assert res["p_loss_w_per_mm2"] == pytest.approx(
        res["p_loss_w_per_m"] / 1.113 * 1e-3, rel=1e-12)
    lossier = _run("microstrip_loss_heat", {**params, "tand": 0.02})
    assert lossier["p_loss_w_per_m"] > res["p_loss_w_per_m"]
    narrower = _run("microstrip_loss_heat", {**params, "width_mm": 0.5})
    assert narrower["p_loss_w_per_mm2"] > res["p_loss_w_per_mm2"]


def test_microstrip_loss_heat_invalid_inputs_are_explicit():
    base = {"freq_ghz": 10.0, "power_w": 1.0, "z0_ohm": 50.0,
            "eps_eff": 3.66, "tand": 0.0037, "width_mm": 1.113}
    for bad in ({"freq_ghz": 0.0}, {"power_w": 0.0}, {"z0_ohm": 0.0},
                {"eps_eff": 0.0}, {"tand": -0.1}, {"width_mm": 0.0}):
        _fails("microstrip_loss_heat", {**base, **bad})


# ─── 5. 平行板击穿裕量 ────────────────────────────────────────────────────────

def test_parallel_plate_breakdown_matches_e_over_d():
    """E=V/d 闭式：1000 V / 1 mm = 1 MV/m；空气 3 MV/m → 裕量 3。"""
    res = _run("parallel_plate_breakdown_margin",
               {"voltage_v": 1000.0, "gap_mm": 1.0})
    assert res["e_field_mv_per_m"] == pytest.approx(1.0, rel=1e-12)
    assert res["breakdown_mv_per_m"] == pytest.approx(3.0)
    assert res["margin_ratio"] == pytest.approx(3.0, rel=1e-12)
    doubled_gap = _run("parallel_plate_breakdown_margin",
                       {"voltage_v": 1000.0, "gap_mm": 2.0})
    assert doubled_gap["e_field_mv_per_m"] == pytest.approx(0.5, rel=1e-12)


def test_parallel_plate_breakdown_boundary_and_safety_factor():
    at_threshold = _run("parallel_plate_breakdown_margin",
                        {"voltage_v": 3000.0, "gap_mm": 1.0})
    assert at_threshold["pass"] is True
    assert at_threshold["margin_db"] == pytest.approx(0.0, abs=1e-9)
    above = _run("parallel_plate_breakdown_margin",
                 {"voltage_v": 3000.1, "gap_mm": 1.0})
    assert above["pass"] is False
    derated = _run("parallel_plate_breakdown_margin",
                   {"voltage_v": 3000.0, "gap_mm": 1.0,
                    "safety_factor": 1.5})
    assert derated["pass"] is False


def test_parallel_plate_breakdown_table_and_invalid():
    ptfe = _run("parallel_plate_breakdown_margin",
                {"voltage_v": 1000.0, "gap_mm": 1.0, "material": "ptfe"})
    assert ptfe["breakdown_mv_per_m"] == pytest.approx(60.0)
    _fails("parallel_plate_breakdown_margin",
           {"voltage_v": 0.0, "gap_mm": 0.0})
    _fails("parallel_plate_breakdown_margin",
           {"voltage_v": 1000.0, "gap_mm": 1.0, "material": "unobtainium"})


# ─── 6. ECSS f·d 判据 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("material,fxd,vth", [
    ("aluminium", 0.70, 23.8),   # 表列最低点（inflexion）
    ("copper", 1.35, 60.3),
    ("silver", 2.77, 182.2),
    ("gold", 100.0, 7254.0),     # 表末点
])
def test_ecss_fd_table_nodes_return_tabulated_values(material, fxd, vth):
    res = _run("ecss_multipactor_fd", {
        "freq_ghz": fxd, "gap_mm": 1.0, "material": material,
        "voltage_v": 1.0})
    assert res["threshold_v"] == pytest.approx(vth, rel=1e-12)
    assert res["region"] == "table"


def test_ecss_fd_log_interpolation_midpoint():
    """表节点 (1.28, 56.2)/(1.35, 62.5) 的几何中点 → 对数插值给算术均值。"""
    fxd = math.sqrt(1.28 * 1.35)
    res = _run("ecss_multipactor_fd", {
        "freq_ghz": fxd, "gap_mm": 1.0, "material": "silver",
        "voltage_v": 1.0})
    assert res["threshold_v"] == pytest.approx((56.2 + 62.5) / 2.0, rel=1e-9)


def test_ecss_fd_margin_db_and_pass_boundary():
    res = _run("ecss_multipactor_fd", {
        "freq_ghz": 1.35, "gap_mm": 1.0, "material": "silver",
        "voltage_v": 6.25})
    assert res["threshold_v"] == pytest.approx(62.5, rel=1e-12)
    assert res["margin_db"] == pytest.approx(20.0, abs=1e-9)
    assert res["pass"] is True
    strict = _run("ecss_multipactor_fd", {
        "freq_ghz": 1.35, "gap_mm": 1.0, "material": "silver",
        "voltage_v": 6.25, "required_margin_db": 20.1})
    assert strict["pass"] is False
    hotter = _run("ecss_multipactor_fd", {
        "freq_ghz": 1.35, "gap_mm": 1.0, "material": "silver",
        "voltage_v": 12.5})
    assert hotter["margin_db"] < res["margin_db"]


def test_ecss_fd_power_and_multicarrier_voltage_conversion():
    """V=√(2PZ0)；ECSS 口径多载波平均功率 Pavg=ΣPi（Pavg=1 W ≡ 单载波 1 W）。"""
    single = _run("ecss_multipactor_fd", {
        "freq_ghz": 3.0, "gap_mm": 1.0, "material": "copper",
        "power_w": 1.0, "z0_ohm": 50.0})
    multi = _run("ecss_multipactor_fd", {
        "freq_ghz": 3.0, "gap_mm": 1.0, "material": "copper",
        "carrier_powers_w": [0.5, 0.5], "z0_ohm": 50.0})
    assert single["applied_voltage_v"] == pytest.approx(10.0, rel=1e-12)
    assert multi["applied_voltage_v"] == pytest.approx(10.0, rel=1e-12)
    two_w = _run("ecss_multipactor_fd", {
        "freq_ghz": 3.0, "gap_mm": 1.0, "material": "copper",
        "carrier_powers_w": [1.0, 1.0], "z0_ohm": 50.0})
    assert two_w["applied_voltage_v"] == pytest.approx(math.sqrt(200.0),
                                                       rel=1e-12)


def test_ecss_fd_region_flags_and_invalid_inputs():
    below = _run("ecss_multipactor_fd", {
        "freq_ghz": 1.0, "gap_mm": 0.2, "material": "gold",
        "voltage_v": 10.0})
    assert below["region"] == "below_chart_min"
    assert below["threshold_v"] == pytest.approx(_ECSS_FD_TABLE["gold"][0][1])
    above = _run("ecss_multipactor_fd", {
        "freq_ghz": 50.0, "gap_mm": 4.0, "material": "silver",
        "voltage_v": 10.0})
    assert above["region"] == "above_chart_max"
    assert above["threshold_v"] == pytest.approx(
        _ECSS_FD_TABLE["silver"][-1][1])
    _fails("ecss_multipactor_fd",
           {"freq_ghz": 0.0, "gap_mm": 1.0, "voltage_v": 10.0})
    _fails("ecss_multipactor_fd",
           {"freq_ghz": 1.0, "gap_mm": 0.0, "voltage_v": 10.0})
    _fails("ecss_multipactor_fd",
           {"freq_ghz": 1.0, "gap_mm": 1.0, "material": "titanium",
            "voltage_v": 10.0})
    _fails("ecss_multipactor_fd", {"freq_ghz": 1.0, "gap_mm": 1.0})
