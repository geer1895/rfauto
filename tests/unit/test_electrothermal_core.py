"""WP4.4a 电-热内核单测（core/electrothermal，纯离线确定性）。

裁判原则（#118）：每个数值断言都用**独立来源**复算——隔离电阻功率用
显式理想 S 矩阵乘法 + 能量守恒独立推导；温漂闭式与
core/calculators.resonator_thermal_drift（注册表内独立实现）逐值互证；
1-D 传导锚手算数值对拍。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.calculators import CALCULATOR_REGISTRY as _calc_registry
from rfauto.core.electrothermal import (
    band_guard,
    combiner_imbalance_case,
    conduction_stack_rise_k,
    conduction_uniform_flux_rise_k,
    divider_through_case,
    isolation_injection_case,
    resistor_power_from_waves,
    thermal_detune,
)

# ─── 独立裁判：理想 Wilkinson S 矩阵（Pozar §7.3）───────────────────────────


def _ideal_s_matrix() -> list[list[complex]]:
    """S = -j/√2 · [[0,1,1],[1,0,0],[1,0,0]]（匹配+隔离+3dB 等分）。"""
    k = -1j / math.sqrt(2.0)
    return [[0, k, k], [k, 0, 0], [k, 0, 0]]


def _resistor_power_via_conservation(a_phasors: list[complex]) -> float:
    """独立复算：P_res = Σ|a|² − Σ|b|²（网络唯一损耗=隔离电阻）。"""
    s = _ideal_s_matrix()
    b = [sum(s[i][j] * a_phasors[j] for j in range(3)) for i in range(3)]
    p_in = sum(abs(x) ** 2 for x in a_phasors)
    p_out = sum(abs(x) ** 2 for x in b)
    return p_in - p_out


class TestIsolationResistorPower:
    def test_limits_vs_s_matrix_conservation(self):
        """三个极限工况与显式 S 矩阵能量守恒复算逐值一致。"""
        # 等分直通：a1=√1, a2=a3=0 → 0
        a = [1.0 + 0j, 0j, 0j]
        assert _resistor_power_via_conservation(a) == pytest.approx(0.0, abs=1e-12)
        assert resistor_power_from_waves(0.0, 0.0) == pytest.approx(0.0)
        # 奇模注入：a2=-a3=1 → 全部入射功率 2W
        a = [0j, 1.0 + 0j, -1.0 + 0j]
        assert _resistor_power_via_conservation(a) == pytest.approx(2.0)
        assert resistor_power_from_waves(1.0, 1.0, phase_diff_deg=180.0) == \
            pytest.approx(2.0)
        # 单边隔离注入：a2=√0.8W, a3=0 → 0.4W（一半）
        p = 0.8
        a = [0j, math.sqrt(p) + 0j, 0j]
        assert _resistor_power_via_conservation(a) == pytest.approx(p / 2.0)
        assert resistor_power_from_waves(p, 0.0) == pytest.approx(p / 2.0)

    def test_phase_sweep_max_at_180_min_at_0(self):
        p = 2.0
        for deg in (-180.0, -90.0, -30.0, 30.0, 90.0, 180.0):
            direct = resistor_power_from_waves(p, p, deg)
            independent = _resistor_power_via_conservation(
                [0j, math.sqrt(p) + 0j, math.sqrt(p) * complex(
                    math.cos(math.radians(deg)), math.sin(math.radians(deg)))])
            assert direct == pytest.approx(independent, rel=1e-12)
        assert resistor_power_from_waves(p, p, 0.0) == pytest.approx(0.0)
        # φ=180°：两路等功率 p 全部进电阻 → P_res = p2+p3 = 2p
        assert resistor_power_from_waves(p, p, 180.0) == pytest.approx(2.0 * p)

    def test_negative_power_rejected(self):
        with pytest.raises(ValueError, match="p2_w"):
            resistor_power_from_waves(-1.0, 0.0)
        with pytest.raises(ValueError, match="phase_diff_deg"):
            resistor_power_from_waves(1.0, 0.0, phase_diff_deg=float("nan"))


class TestScenarioCases:
    def test_divider_through(self):
        out = divider_through_case(2.0)
        assert out["resistor_w"] == 0.0
        assert out["port2_out_w"] == pytest.approx(1.0)
        assert out["port3_out_w"] == pytest.approx(1.0)

    def test_isolation_injection(self):
        out = isolation_injection_case(1.0)
        assert out["resistor_w"] == pytest.approx(0.5)
        assert out["port1_out_w"] == pytest.approx(0.5)
        assert out["port3_out_w"] == 0.0

    def test_combiner_imbalance_conservation(self):
        out = combiner_imbalance_case(1.0, 1.0, 60.0)
        assert out["residual_w"] == pytest.approx(0.0, abs=1e-12)
        # 与通用核一致
        assert out["resistor_w"] == pytest.approx(
            resistor_power_from_waves(1.0, 1.0, 60.0))
        # φ=0 完美合路：全部出 port1
        perfect = combiner_imbalance_case(1.0, 1.0, 0.0)
        assert perfect["resistor_w"] == pytest.approx(0.0)
        assert perfect["port1_out_w"] == pytest.approx(2.0)
        # φ=180 正交相消：全部进电阻
        worst = combiner_imbalance_case(1.0, 1.0, 180.0)
        assert worst["resistor_w"] == pytest.approx(2.0)


class TestThermalDetune:
    def test_matches_calculator_registry_implementation(self):
        """与 core/calculators 注册表独立实现 resonator_thermal_drift 互证。"""
        calc = _calc_registry.get("resonator_thermal_drift").func
        for f0_ghz, dt, cte, tcdk in [
            (2.4, 36.3, 14.0, 50.0),
            (2.4, -40.0, 14.0, 50.0),
            (5.8, 85.0, 3.0, -15.0),
            (1.0, 0.0, 100.0, 200.0),
        ]:
            mine = thermal_detune(f0_ghz * 1e9, dt, cte, tcdk)
            ref = calc(f0_ghz=f0_ghz, delta_t_c=dt,
                       cte_ppm_per_k=cte, tcdk_ppm_per_k=tcdk)
            assert mine["drift_ratio"] == pytest.approx(ref["df_over_f"], rel=1e-12)
            assert mine["df_ppm"] == pytest.approx(ref["df_over_f_ppm"], rel=1e-9)
            assert mine["f0_shifted_hz"] == pytest.approx(
                ref["f_shifted_ghz"] * 1e9, rel=1e-12)

    def test_sign_and_hand_value(self):
        # ΔT=100K、CTE+TCDk/2=39 ppm/K → df/f=-3.9e-3 → 2.4GHz 偏 -9.36MHz
        out = thermal_detune(2.4e9, 100.0, 14.0, 50.0)
        assert out["drift_ratio"] == pytest.approx(-3.9e-3)
        assert out["df_hz"] == pytest.approx(-9.36e6)
        assert out["f0_shifted_hz"] == pytest.approx(2.4e9 - 9.36e6)

    def test_invalid_inputs(self):
        with pytest.raises(ValueError, match="f0_hz"):
            thermal_detune(0.0, 1.0, 1.0, 1.0)
        with pytest.raises(ValueError, match="delta_t_c"):
            thermal_detune(1e9, float("inf"), 1.0, 1.0)


class TestBandGuard:
    def test_in_and_out(self):
        inside = band_guard(2.35e9, 2.3e9, 2.5e9)
        assert inside["in_band"] is True
        assert inside["margin_hz"] == pytest.approx(50e6)
        # 2.2GHz < 2.3GHz 下带缘 → 出带，margin=-100MHz
        outside = band_guard(2.2e9, 2.3e9, 2.5e9)
        assert outside["in_band"] is False
        assert outside["margin_hz"] == pytest.approx(-100e6)

    def test_nearest_edge_selection(self):
        near_lo = band_guard(2.31e9, 2.3e9, 2.5e9)
        assert near_lo["nearest_edge_hz"] == 2.3e9
        near_hi = band_guard(2.49e9, 2.3e9, 2.5e9)
        assert near_hi["nearest_edge_hz"] == 2.5e9

    def test_invalid_band(self):
        with pytest.raises(ValueError, match="band_low_hz"):
            band_guard(2.4e9, 2.5e9, 2.3e9)


class TestConductionStackAnchor:
    def test_hand_value(self):
        """P=0.5W、A=4e-4 m²、h_sub=0.508mm/k=0.4、h_blk=0.15mm/k=1：
        rise = 1250 * (1.27e-3 + 7.5e-5) = 1.68125 K。"""
        out = conduction_stack_rise_k(
            power_w=0.5, area_m2=4e-4, h_sub_m=0.508e-3, k_sub_w_mk=0.4,
            h_blk_m=0.15e-3, k_blk_w_mk=1.0, t_base_c=25.0)
        expected_rise = 0.5 / 4e-4 * (0.508e-3 / 0.4 + 0.15e-3 / 2.0)
        assert out["rise_k"] == pytest.approx(expected_rise)
        assert out["rise_k"] == pytest.approx(1.68125)
        assert out["t_monitor_c"] == pytest.approx(25.0 + 1.68125)
        assert out["r_total_k_per_w"] == pytest.approx(expected_rise / 0.5)

    def test_invalid_inputs(self):
        with pytest.raises(ValueError, match="area_m2"):
            conduction_stack_rise_k(0.5, 0.0, 1e-3, 0.4, 1e-4, 1.0, 25.0)
        with pytest.raises(ValueError, match="power_w"):
            conduction_stack_rise_k(-0.5, 4e-4, 1e-3, 0.4, 1e-4, 1.0, 25.0)


class TestUniformFluxRise:
    def test_hand_value(self):
        """P=0.5W、A=4e-4、depth=h_sub/2=2.54e-4、k=0.4：
        rise = 0.5·2.54e-4/(0.4·4e-4) = 0.79375 K（锚工况基板中面）。"""
        out = conduction_uniform_flux_rise_k(
            power_w=0.5, area_m2=4e-4, depth_m=0.508e-3 / 2.0,
            k_w_mk=0.4, t_base_c=25.0)
        assert out["rise_k"] == pytest.approx(0.79375)
        assert out["t_monitor_c"] == pytest.approx(25.79375)
        assert out["r_total_k_per_w"] == pytest.approx(1.5875)

    def test_invalid_inputs(self):
        with pytest.raises(ValueError, match="depth_m"):
            conduction_uniform_flux_rise_k(0.5, 4e-4, 0.0, 0.4, 25.0)
        with pytest.raises(ValueError, match="k_w_mk"):
            conduction_uniform_flux_rise_k(0.5, 4e-4, 1e-3, -0.4, 25.0)
