"""MM-8 EBG/AMC 蘑菇内核锚树（core/amc_mushroom.py，round17 :156）。

裁判面（#118：每面 ≥2 独立基准；零臆造锚值）：
- LC 单源恒等：L=μ₀t 精确、C 与 metasurface_lut 贴片栅闭式逐位一致
  + 物理趋势（gap↓→C↑）+ f₀=1/(2π√LC)；
- 无损恒等式：|Γ|=1 全带（数值复平面）；
- 相位带双路径裁判：数值根求（bisection 找 φ=±90°/0° 交点）vs 精确
  闭式 x_low/x_high/f₀——两条独立路径对拍到 1e-6/1e-9；
- Sievenpiper 带宽律（结构性锚）：同 √(L/C) 比缩放（L,C 同除 4）
  → 分数带宽不变、f₀×4（与谐振频率无关）；
- PEC 低频极限 |φ|>179° + 报告 verdict 分派 + 域守卫负例。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.amc_mushroom import (
    amc_gap_capacitance_f,
    amc_phase_band_hz,
    amc_reflection_coeff,
    amc_reflection_phase_deg,
    amc_resonance_hz,
    amc_surface_impedance,
    amc_via_inductance_h,
    mushroom_design_report,
)
from rfauto.core.metasurface_lut import (
    MU0_H_M,
    fss_patch_grid_capacitance_f,
)

PERIOD_M = 5e-3
GAP_M = 0.5e-3
T_SUB_M = 1.6e-3
EPS_EFF = (1.0 + 4.4) / 2.0  # εr=4.4 单侧基板加载口径


def _lc() -> tuple[float, float]:
    return amc_via_inductance_h(T_SUB_M), amc_gap_capacitance_f(
        PERIOD_M, GAP_M, EPS_EFF)


class TestLCParams:
    def test_via_inductance_identity(self):
        assert amc_via_inductance_h(T_SUB_M) == pytest.approx(
            MU0_H_M * T_SUB_M, rel=1e-15)

    def test_gap_cap_single_source_and_trend(self):
        c = amc_gap_capacitance_f(PERIOD_M, GAP_M, EPS_EFF)
        assert c == float(fss_patch_grid_capacitance_f(
            PERIOD_M, GAP_M, EPS_EFF))
        assert c > 0.0
        c_tight = amc_gap_capacitance_f(PERIOD_M, GAP_M / 2.0, EPS_EFF)
        assert c_tight > c  # 缝隙收窄 → 电容增大（物理趋势）

    def test_resonance_closed_form(self):
        l_via, c_gap = _lc()
        f0 = amc_resonance_hz(l_via, c_gap)
        assert f0 == pytest.approx(1.0 / (2.0 * math.pi * math.sqrt(
            l_via * c_gap)), rel=1e-15)
        # 数值量级 sanity：mm 级周期/亚 mm 缝 → f0 落百 MHz~几十 GHz 窗
        assert 1e7 < f0 < 1e11


class TestReflection:
    def test_lossless_identity(self):
        l_via, c_gap = _lc()
        f0 = amc_resonance_hz(l_via, c_gap)
        f = np.array([0.2, 0.5, 0.8, 1.2, 3.0, 10.0]) * f0
        gam = amc_reflection_coeff(2 * np.pi * f, l_via, c_gap)
        assert np.max(np.abs(np.abs(gam) - 1.0)) <= 1e-12

    def test_phase_zero_crossing_at_resonance(self):
        """独立路径 1：相位过零在 f₀（极点两侧 |φ|→0 符号翻转）。"""
        l_via, c_gap = _lc()
        f0 = amc_resonance_hz(l_via, c_gap)
        phase_lo = float(amc_reflection_phase_deg(0.9999 * f0, l_via,
                                                  c_gap)[0])
        phase_hi = float(amc_reflection_phase_deg(1.0001 * f0, l_via,
                                                  c_gap)[0])
        assert 0.0 < phase_lo < 2.0
        assert -2.0 < phase_hi < 0.0

    def test_phase_band_edges_root_vs_closed(self):
        """独立路径 2：数值根求 ±90° 带边 vs 精确闭式（x_low/x_high）。"""
        l_via, c_gap = _lc()
        band = amc_phase_band_hz(l_via, c_gap)
        f0 = band["f0_hz"]

        def _phase(f: float) -> float:
            return float(amc_reflection_phase_deg(f, l_via, c_gap)[0])

        lo, hi = 0.05 * f0, 0.9999 * f0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if _phase(mid) > 90.0:
                lo = mid
            else:
                hi = mid
        assert 0.5 * (lo + hi) == pytest.approx(band["f_low_hz"], rel=1e-6)

        lo, hi = 1.0001 * f0, 20.0 * f0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if _phase(mid) < -90.0:
                hi = mid  # 已越过根（φ 随 f 单调降）→ 收向低端
            else:
                lo = mid
        assert 0.5 * (lo + hi) == pytest.approx(band["f_high_hz"], rel=1e-6)

    def test_fractional_bandwidth_law(self):
        """Sievenpiper 律：分数带宽=√(L/C)/η₀ 恒等 + 频率无关结构锚。"""
        l_via, c_gap = _lc()
        band = amc_phase_band_hz(l_via, c_gap)
        ratio = math.sqrt(l_via / c_gap) / 376.730313668
        assert band["fractional_bandwidth"] == pytest.approx(ratio, rel=1e-15)
        assert band["f_high_hz"] / band["f_low_hz"] == pytest.approx(
            (1.0 + ratio / math.sqrt(4.0 + ratio**2))
            / (1.0 - ratio / math.sqrt(4.0 + ratio**2)), rel=1e-12)
        # 缩放律：L,C 同除 4 → LC/16 → f₀×4；√(L/C) 不变 → 分数带宽逐位
        band2 = amc_phase_band_hz(l_via / 4.0, c_gap / 4.0)
        assert band2["fractional_bandwidth"] == pytest.approx(
            band["fractional_bandwidth"], rel=1e-15)
        assert band2["f0_hz"] == pytest.approx(4.0 * band["f0_hz"], rel=1e-15)

    def test_pec_low_frequency_limit(self):
        l_via, c_gap = _lc()
        f0 = amc_resonance_hz(l_via, c_gap)
        phase = float(amc_reflection_phase_deg(1e-4 * f0, l_via, c_gap)[0])
        assert abs(phase) > 179.0


class TestSurfaceImpedance:
    def test_pole_at_resonance(self):
        l_via, c_gap = _lc()
        w0 = 2.0 * math.pi * amc_resonance_hz(l_via, c_gap)
        zs = amc_surface_impedance(np.array([0.5 * w0, 2.0 * w0]),
                                   l_via, c_gap)
        assert zs[0].real == pytest.approx(0.0, abs=1e-9)
        assert zs[0].imag > 0.0  # 低频感性 → 感性表面
        assert zs[1].imag < 0.0  # 高频容性

    def test_guard_nonpositive_omega(self):
        l_via, c_gap = _lc()
        with pytest.raises(ValueError):
            amc_surface_impedance(np.array([0.0, 1.0]), l_via, c_gap)


class TestDesignReport:
    def test_report_verdict_paths(self):
        l_via, c_gap = _lc()
        f0 = amc_resonance_hz(l_via, c_gap)
        rep = mushroom_design_report(PERIOD_M, GAP_M, T_SUB_M, EPS_EFF,
                                     target_f0_hz=f0)
        assert rep["verdict"] == "in_band"
        rep2 = mushroom_design_report(PERIOD_M, GAP_M, T_SUB_M, EPS_EFF,
                                      target_f0_hz=100.0 * f0)
        assert rep2["verdict"] == "out_of_band"
        assert rep2["f0_deviation"] > 0.10

    def test_guard_gap_ge_period(self):
        with pytest.raises(ValueError):
            mushroom_design_report(PERIOD_M, PERIOD_M, T_SUB_M, EPS_EFF)
