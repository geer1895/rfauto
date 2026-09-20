"""D15 高功率效应预筛内核单测（core/high_power.py，§10.3 D15 / §10.21）。

裁判 = 外部独立来源（#118：不是被测实现的自我推导）：
  * 平行板击穿：E = V/d 经典闭式（Jackson §1.3 / Pozar）与
    20*log10(E_bd/E) 的独立代数路径；
  * 基材强度：Accuratus Alumox 数据表 16.7 ac-kV/mm
    （https://accuratus.com/alumox.html）、Insaco 经 AZoOptics 1270 ac V/mil
    = 50.0 MV/m（https://www.azooptics.com/Article.aspx?ArticleID=161）；
  * ECSS 多载流子：ECSS-E-ST-20-01C (2020) Table 5-1 节点原值（本文件
    逐字重录，不复用被测表）；
  * 温升：手算串联热阻网络 Tj = Ta + P*(theta_jc+theta_cs+theta_sa)；
  * PIM 规则：RF Cafe / 铁磁材料 PIM 文献的设计规则条目；
  * 功率容量：E ∝ sqrt(P) 线性结构口径（合成/记录数据，不真跑求解器）。

确定性：无网络、无真机、无文件 IO、无随机。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from rfauto.core.high_power import (
    AIR_BREAKDOWN_MV_PER_M,
    DEFAULT_MAX_CURRENT_DENSITY_A_PER_MM2,
    PIM_RULES,
    SUBSTRATE_DIELECTRIC_STRENGTH_MV_PER_M,
    breakdown_from_field_peak,
    field_peak_mv_per_m,
    multipactor_fd_check,
    pim_rule_check,
    power_capacity_report,
    predict,
    prescreen,
    resolve_dielectric_strength,
    thermal_from_average_power,
)

# 独立来源常量（见文件 docstring）
AIR_BD = 3.0            # calculators.py 材料表 / 空气 3 MV/m
ALUMINA_BD = 16.7       # Accuratus Alumox 16.7 ac-kV/mm
FUSED_SILICA_BD = 50.0  # Insaco 1270 ac V/mil = 50.0 MV/m

# ECSS-E-ST-20-01C Table 5-1：silver 边界节点原值（逐字录入）
ECSS_SILVER_NODES = ((1.02, 38.3), (2.62, 179.7), (10.41, 554.0), (57.59, 3659.0))

# ECSS-E-ST-20-01C Table 5-1：silver 边界低端段原值（含全局最低点，用于
# 独立复算 "minimum inflexion point"）
ECSS_SILVER_LOW_END = ((0.50, 38.3), (0.53, 33.7), (0.56, 31.7), (0.59, 30.4),
                       (0.62, 29.5), (0.66, 28.9), (0.70, 28.5), (0.74, 28.5),
                       (0.78, 28.7), (0.82, 29.7), (0.87, 30.9), (0.92, 32.9))


def _parallel_plate_field_dump(voltage_v: float, gap_mm: float, *,
                               edge_ripple: float = 0.02, n: int = 41) -> np.ndarray:
    """合成平行板场 dump：均匀场 E=V/d 叠加边缘增强（峰值 = E*(1+ripple)）。"""
    e_closed = voltage_v / (gap_mm * 1.0e-3)
    axis = np.linspace(-1.0, 1.0, n)
    xx, yy = np.meshgrid(axis, axis)
    shape = 1.0 + edge_ripple * (xx ** 2 + yy ** 2) / 2.0
    return e_closed * shape


# ---------------------------------------------------------------------------
# 1) 峰值场 → 击穿裕量
# ---------------------------------------------------------------------------

def test_field_peak_matches_parallel_plate_closed_form_within_5pct():
    voltage, gap = 120.0, 0.8
    e_closed = voltage / (gap * 1.0e-3)  # V/m
    dump = _parallel_plate_field_dump(voltage, gap, edge_ripple=0.02)
    peak = field_peak_mv_per_m(dump)
    # 合成 dump 峰值 = 闭式 E*(1+ripple)
    assert peak == pytest.approx(e_closed * 1.02 / 1.0e6, rel=1e-12)
    # 验收口径：场 dump 峰值 vs 平行板闭式 ≤5%
    assert abs(peak - e_closed / 1.0e6) / (e_closed / 1.0e6) <= 0.05
    # 由场 dump 与由闭式反推的电压得到的击穿裕量一致（≤5%）
    via_dump = breakdown_from_field_peak(peak, "air")
    via_closed = breakdown_from_field_peak(e_closed / 1.0e6, "air")
    assert abs(via_dump["margin_db"] - via_closed["margin_db"]) <= 0.5


def test_field_peak_units_and_complex_magnitude():
    base = np.array([[0.0, 1.0e6], [2.0e6, 0.0]])  # V/m
    assert field_peak_mv_per_m(base) == pytest.approx(2.0)
    assert field_peak_mv_per_m(base / 1.0e3, unit="kv_per_m") == pytest.approx(2.0)
    assert field_peak_mv_per_m(base / 1.0e6, unit="mv_per_m") == pytest.approx(2.0)
    phasor = np.array([3.0 + 4.0j]) * 1.0e6  # |E| = 5e6 V/m
    assert field_peak_mv_per_m(phasor) == pytest.approx(5.0)


def test_breakdown_margin_db_matches_independent_log_ratio():
    e_peak = 1.5  # MV/m
    out = breakdown_from_field_peak(e_peak, "air")
    assert out["breakdown_mv_per_m"] == AIR_BD
    assert out["margin_ratio"] == pytest.approx(AIR_BD / e_peak, rel=1e-9)
    assert out["margin_db"] == pytest.approx(20.0 * math.log10(AIR_BD / e_peak), rel=1e-9)
    assert out["pass"] is True


def test_breakdown_pass_fail_boundary_and_safety_factor():
    at_limit = breakdown_from_field_peak(AIR_BD, "air")
    assert at_limit["pass"] is True          # E*1 <= E_bd
    over = breakdown_from_field_peak(AIR_BD * 1.001, "air")
    assert over["pass"] is False
    sf_ok = breakdown_from_field_peak(2.0, "air", safety_factor=1.0)
    assert sf_ok["pass"] is True
    sf_fail = breakdown_from_field_peak(2.0, "air", safety_factor=2.0)
    assert sf_fail["safety_pass"] is False and sf_fail["pass"] is False
    # 要求裕量 dB 门槛
    margin_gate = breakdown_from_field_peak(1.0, "air", required_margin_db=12.0)
    assert math.isclose(margin_gate["margin_db"], 20.0 * math.log10(3.0), rel_tol=1e-9)
    assert margin_gate["pass"] is False       # 9.54 dB < 12 dB


def test_substrate_table_matches_cited_vendor_values():
    assert AIR_BREAKDOWN_MV_PER_M == AIR_BD
    assert SUBSTRATE_DIELECTRIC_STRENGTH_MV_PER_M["alumina"] == ALUMINA_BD
    assert SUBSTRATE_DIELECTRIC_STRENGTH_MV_PER_M["fused_silica"] == FUSED_SILICA_BD
    strength, source = resolve_dielectric_strength("Al2O3")
    assert strength == ALUMINA_BD and source == "substrate_table"
    out = breakdown_from_field_peak(5.0, "fused-silica")
    assert out["breakdown_mv_per_m"] == FUSED_SILICA_BD
    assert out["margin_db"] == pytest.approx(20.0 * math.log10(FUSED_SILICA_BD / 5.0), rel=1e-9)


def test_breakdown_override_and_calculator_provenance():
    e_peak = 1.2
    base = breakdown_from_field_peak(e_peak, "air")
    # 独立闭式裁判（不依赖 calculators）
    assert base["margin_db"] == pytest.approx(20.0 * math.log10(AIR_BD / e_peak), rel=1e-9)
    assert base["strength_source"] == "calculators.parallel_plate_breakdown_margin"
    override = breakdown_from_field_peak(e_peak, "fr4", material_strength_mv_per_m=20.0)
    assert override["breakdown_mv_per_m"] == 20.0
    assert override["strength_source"] == "override"
    assert override["margin_db"] == pytest.approx(20.0 * math.log10(20.0 / e_peak), rel=1e-9)


# ---------------------------------------------------------------------------
# 2) ECSS 多载流子 f·d
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("fxd", "threshold_v"), ECSS_SILVER_NODES)
def test_multipactor_fd_matches_ecss_chart_nodes(fxd, threshold_v):
    out = multipactor_fd_check(freq_ghz=fxd, gap_mm=1.0, material="silver",
                               voltage_v=threshold_v, required_margin_db=0.0)
    assert out["fxd_ghz_mm"] == pytest.approx(fxd)
    assert out["threshold_v"] == pytest.approx(threshold_v, rel=1e-12)
    assert out["region"] == "table"
    assert out["applied_voltage_v"] == pytest.approx(threshold_v, rel=1e-12)
    assert out["margin_db"] == pytest.approx(0.0, abs=1e-9)
    assert out["pass"] is True


def test_multipactor_margin_db_from_power_independent():
    freq, gap, power, z0 = 2.0, 1.5, 10.0, 50.0
    out = multipactor_fd_check(freq_ghz=freq, gap_mm=gap, power_w=power,
                               z0_ohm=z0, material="silver", required_margin_db=0.0)
    v_applied = math.sqrt(2.0 * power * z0)
    assert out["applied_voltage_v"] == pytest.approx(v_applied, rel=1e-12)
    assert out["margin_db"] == pytest.approx(20.0 * math.log10(out["threshold_v"] / v_applied), rel=1e-9)
    assert out["standard"].startswith("ECSS-E-ST-20-01C")


def test_multipactor_region_markers_outside_chart():
    below = multipactor_fd_check(freq_ghz=0.01, gap_mm=1.0, voltage_v=100.0)
    assert below["region"] == "below_chart_min"
    above = multipactor_fd_check(freq_ghz=200.0, gap_mm=1.0, voltage_v=100.0)
    assert above["region"] == "above_chart_max"


def test_multipactor_inflexion_is_chart_global_minimum():
    # 独立复算：silver 边界全局最低点（min over 重录原值）
    min_fxd, min_voltage = min(ECSS_SILVER_LOW_END, key=lambda point: point[1])
    out = multipactor_fd_check(freq_ghz=3.0, gap_mm=1.0, voltage_v=100.0)
    assert out["inflexion_fxd_ghz_mm"] == pytest.approx(min_fxd)
    assert out["inflexion_voltage_v"] == pytest.approx(min_voltage)


# ---------------------------------------------------------------------------
# 3) 平均功率 → 温升
# ---------------------------------------------------------------------------

def test_thermal_average_power_matches_series_resistance_network():
    power, ambient, jc, cs, sa = 10.0, 40.0, 2.0, 0.5, 1.5
    out = thermal_from_average_power(power, theta_jc_c_per_w=jc, ambient_c=ambient,
                                     theta_cs_c_per_w=cs, theta_sa_c_per_w=sa,
                                     max_junction_c=100.0)
    theta_total = jc + cs + sa
    assert out["theta_total_c_per_w"] == pytest.approx(theta_total)
    assert out["delta_t_c"] == pytest.approx(power * theta_total)
    assert out["junction_temp_c"] == pytest.approx(ambient + power * theta_total)
    assert out["pass"] is True
    hot = thermal_from_average_power(100.0, theta_jc_c_per_w=jc, ambient_c=ambient,
                                     theta_cs_c_per_w=cs, theta_sa_c_per_w=sa,
                                     max_junction_c=100.0)
    assert hot["pass"] is False


# ---------------------------------------------------------------------------
# 4) PIM 规则检查器
# ---------------------------------------------------------------------------

def test_pim_rule_table_declares_three_documented_rules():
    keys = [rule.key for rule in PIM_RULES]
    assert keys == ["ferromagnetic_material", "contact_current_path", "current_density"]
    for rule in PIM_RULES:
        assert rule.description and rule.source


def test_pim_ferromagnetic_material_hit_and_clean_pass():
    dirty = {"materials": [{"name": "copper"}, {"name": "stainless_steel"}]}
    out = pim_rule_check(dirty)
    assert out["pass"] is False
    assert out["violation_count"] == 1
    assert out["violations"][0]["rule"] == "ferromagnetic_material"
    clean = {"materials": [{"name": "copper", "mu_r": 1.0},
                           {"name": "ptfe", "in_rf_path": False}]}
    assert pim_rule_check(clean)["pass"] is True
    mu_hit = pim_rule_check({"materials": [{"name": "brass", "mu_r": 1.05}]})
    assert mu_hit["violation_count"] == 1
    # 非 RF 路径的铁磁材料不判违规（避免漏判的反向：命中/漏判双向）
    out_of_path = pim_rule_check({"materials": [{"name": "steel", "in_rf_path": False}]})
    assert out_of_path["pass"] is True


def test_pim_contact_current_path_both_directions():
    connector = {"junctions": [{"name": "SMA", "kind": "connector"}]}
    hit = pim_rule_check(connector)
    assert hit["pass"] is False
    assert hit["violations"][0]["rule"] == "contact_current_path"
    soldered = {"junctions": [{"name": "feed", "kind": "soldered"}]}
    assert pim_rule_check(soldered)["pass"] is True
    dissimilar = {"junctions": [{"kind": "soldered",
                                 "dissimilar_metals": ["copper", "nickel"]}]}
    assert pim_rule_check(dissimilar)["violation_count"] == 1
    oxidized = {"junctions": [{"kind": "welded", "oxidized": True}]}
    assert pim_rule_check(oxidized)["violation_count"] == 1


def test_pim_current_density_limit_both_directions():
    assert DEFAULT_MAX_CURRENT_DENSITY_A_PER_MM2 == 10.0
    ok = {"conductors": [{"name": "ring", "current_a": 5.0, "cross_section_mm2": 1.0}]}
    assert pim_rule_check(ok)["pass"] is True
    bad = {"conductors": [{"name": "ring", "current_a": 5.0, "cross_section_mm2": 0.25}]}
    out = pim_rule_check(bad)
    assert out["violations"][0]["rule"] == "current_density"
    assert out["violations"][0]["context"]["current_density_a_per_mm2"] == pytest.approx(20.0)
    assert pim_rule_check(bad, max_current_density_a_per_mm2=25.0)["pass"] is True
    explicit = {"conductors": [{"name": "ring", "current_density_a_per_mm2": 30.0}]}
    assert pim_rule_check(explicit)["violation_count"] == 1


def test_pim_skipped_when_design_absent():
    skipped = pim_rule_check(None)
    assert skipped["checked"] is False
    assert skipped["pass"] is True and skipped["violation_count"] == 0
    report = prescreen({"field_peak_mv_per_m": 0.1, "material": "air"})
    assert report["pim"]["checked"] is False
    assert report["pass"] is True


# ---------------------------------------------------------------------------
# 功率容量报告（合成/记录数据）
# ---------------------------------------------------------------------------

def test_power_capacity_report_ratrace_1w_10w_synthetic():
    reference_field = 0.4  # MV/m @ 1 W（合成记录值，不真跑）
    report = power_capacity_report([1.0, 10.0], reference_power_w=1.0,
                                   reference_field_peak_mv_per_m=reference_field,
                                   material="air", source="synthetic")
    assert report["reference"]["source"] == "synthetic"
    entry_1w, entry_10w = report["entries"]
    assert entry_1w["field_peak_mv_per_m"] == pytest.approx(reference_field)
    assert entry_10w["field_peak_mv_per_m"] == pytest.approx(reference_field * math.sqrt(10.0))
    assert entry_1w["breakdown"]["margin_db"] == pytest.approx(
        20.0 * math.log10(AIR_BD / reference_field), rel=1e-9)
    assert report["all_pass"] is True
    assert report["max_passing_power_w"] == 10.0
    assert report["first_failing_power_w"] is None
    json.dumps(report, allow_nan=False)

    blown = power_capacity_report([1.0, 100.0], reference_power_w=1.0,
                                  reference_field_peak_mv_per_m=reference_field)
    assert blown["entries"][1]["pass"] is False
    assert blown["all_pass"] is False
    assert blown["first_failing_power_w"] == 100.0


# ---------------------------------------------------------------------------
# predict / prescreen 接口与非法输入
# ---------------------------------------------------------------------------

def test_predict_flat_metrics_and_prescreen_json():
    params = {
        "field_peak_mv_per_m": 0.5,
        "material": "air",
        "freq_ghz": 2.0,
        "gap_mm": 2.0,
        "power_w": 10.0,
        "theta_jc_c_per_w": 3.0,
        "ambient_c": 50.0,
        "max_junction_c": 120.0,
        "design": {"materials": [{"name": "copper"}],
                   "junctions": [{"kind": "soldered"}],
                   "conductors": [{"name": "line", "current_a": 2.0,
                                   "cross_section_mm2": 1.0}]},
    }
    metrics = predict(params)
    assert metrics["field_peak_mv_per_m"] == pytest.approx(0.5)
    assert metrics["breakdown_margin_db"] == pytest.approx(
        20.0 * math.log10(AIR_BD / 0.5), rel=1e-9)
    assert metrics["thermal_junction_temp_c"] == pytest.approx(80.0)
    assert metrics["pim_violation_count"] == 0.0
    assert metrics["overall_pass"] == 1.0
    assert all(isinstance(value, float) for value in metrics.values())
    json.dumps(metrics, allow_nan=False)

    report = prescreen(params)
    assert report["pass"] is True
    json.dumps(report, allow_nan=False)

    # 平行板电压派生路径 E = V/d
    derived = prescreen({"voltage_v": 100.0, "gap_mm": 1.0, "material": "air"})
    assert derived["field_peak_mv_per_m"] == pytest.approx(0.1)
    assert derived["breakdown"]["margin_db"] == pytest.approx(
        20.0 * math.log10(AIR_BD / 0.1), rel=1e-9)


def test_illegal_inputs_raise():
    with pytest.raises(ValueError):
        field_peak_mv_per_m([])
    with pytest.raises(ValueError):
        field_peak_mv_per_m([[float("nan")]])
    with pytest.raises(ValueError):
        field_peak_mv_per_m([1.0], unit="furlong_per_fortnight")
    with pytest.raises(ValueError):
        breakdown_from_field_peak(-1.0)
    with pytest.raises(ValueError):
        breakdown_from_field_peak(1.0, "unobtainium")
    with pytest.raises(ValueError):
        breakdown_from_field_peak(1.0, "air", safety_factor=0.0)
    with pytest.raises(ValueError):
        multipactor_fd_check(0.0, 1.0, voltage_v=1.0)
    with pytest.raises(ValueError):
        multipactor_fd_check(1.0, 1.0)          # 缺电压/功率
    with pytest.raises(ValueError):
        pim_rule_check({"junctions": [{"kind": "glued"}]})
    with pytest.raises(ValueError):
        pim_rule_check({"conductors": [{"name": "x"}]})
    with pytest.raises(ValueError):
        pim_rule_check([1, 2, 3])
    with pytest.raises(ValueError):
        pim_rule_check({"materials": [{"name": "copper"}]},
                       max_current_density_a_per_mm2=0.0)
    with pytest.raises(ValueError):
        power_capacity_report([], reference_power_w=1.0,
                              reference_field_peak_mv_per_m=0.1)
