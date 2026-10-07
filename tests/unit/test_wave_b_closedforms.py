"""Wave B 席 B9 登记级闭式三件测试（TA-13 ebg_fss / AP-14 corrugated_horn /
MA-4 fpor，2026-10-03）。

每件 ≥2 独立基准（#118；#300 裁判资格先于数值）：
- ebg_fss：带边闭式 vs |Z_s|=η₀/2 brentq 数值求根（独立代码路径）+ |T|²=1/2
  定义级回检 + R·δ=1/2 与 MM-8 amc 带宽律互证恒等 + 极限（|Γ|=1 恒等）；
- corrugated_horn：Bessel 根 scipy 求根 vs 硬编码文献字面量（独立来源）+
  短路 stub 精确极限（λ/4→∞/λ/2→0/duty→1 退化为裸短线）+ λ/4 深度定义恒等；
- fpor：精确往返回收 + 全填充解析极限 f0/√εr + 一阶 k 形随 x(εr−1)→0
  收敛（SPDR 边界"k 需标定"的均匀场可推导锚）+ t→0 零微扰。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.amc_mushroom import amc_phase_band_hz
from rfauto.core.corrugated_horn import (
    TM11_KC_A,
    bessel_root_j1_first,
    bessel_root_j1p_first,
    grooved_surface_reactance_ohm,
    he11_balance_report,
    quarter_wave_depth_m,
)
from rfauto.core.dielectric_extract import C0
from rfauto.core.ebg_fss import (
    fss_band_edges_hz,
    fss_design_report,
    fss_series_lc_impedance,
    fss_sheet_reflection_coeff,
    fss_sheet_transmission_coeff,
    jerusalem_screen_lc,
    square_loop_fss_lc,
)
from rfauto.core.material_characterization import (
    fpor_er_first_order,
    fpor_er_from_fshift,
    fpor_fill_factor,
    fpor_fshift,
    fpor_pe_uniform_field,
    fpor_tand_from_q,
)

ETA0 = 376.730313668


# ─── TA-13 ebg_fss ─────────────────────────────────────────────────────────

def _band_numeric_roots(l_h: float, c_f: float) -> tuple[float, float]:
    """|Z_s(f)|=η₀/2 数值求根（brentq，与闭式不同代码路径的独立裁判）。"""
    from scipy.optimize import brentq

    def obj(f: float) -> float:
        return abs(fss_series_lc_impedance(2 * np.pi * f, l_h, c_f)) - ETA0 / 2

    rep = fss_band_edges_hz(l_h, c_f)
    f0 = rep["f0_hz"]
    f_lo = brentq(obj, 0.05 * f0, 0.999 * f0, xtol=1e-3)
    f_hi = brentq(obj, 1.001 * f0, 50.0 * f0, xtol=1e-3)
    return f_lo, f_hi


def test_fss_band_edges_vs_numeric_roots():
    """独立基准①：−3dB 带边闭式 ≡ 数值求根（真机同点）。"""
    rep = fss_design_report(10e-3, 1e-3, 0.5e-3, eps_eff=1.0)
    f_lo, f_hi = _band_numeric_roots(rep["l_h"], rep["c_f"])
    assert f_lo == pytest.approx(rep["f_low_hz"], rel=1e-9)
    assert f_hi == pytest.approx(rep["f_high_hz"], rel=1e-9)


def test_fss_band_edge_definition_level_check():
    """独立基准②：带边处 |T|²=1/2（定义级回检，不经闭式推导）。"""
    rep = fss_design_report(8e-3, 0.8e-3, 0.4e-3, eps_eff=1.0)
    for f in (rep["f_low_hz"], rep["f_high_hz"]):
        t = fss_sheet_transmission_coeff(2 * np.pi * f, rep["l_h"], rep["c_f"])
        assert abs(t) ** 2 == pytest.approx(0.5, rel=1e-9)


def test_fss_amc_bandwidth_law_cross_identity():
    """与 MM-8 互证：同一 LC 对，串联悬浮 δ 与接地并联 R 满足 R·δ=1/2
    （两带宽律同构的代数恒等；amc_phase_band_hz 为已合流单源）。"""
    l_h, c_f = 4.0e-9, 0.8e-12
    fss = fss_band_edges_hz(l_h, c_f)
    amc = amc_phase_band_hz(l_h, c_f)
    assert fss["impedance_ratio_R"] * fss["delta"] == pytest.approx(
        0.5, rel=1e-12)
    assert amc["impedance_ratio"] == pytest.approx(
        fss["impedance_ratio_R"], rel=1e-12)
    assert amc["fractional_bandwidth"] == pytest.approx(
        fss["impedance_ratio_R"], rel=1e-12)


def test_fss_limits_and_lossless_identity():
    """极限：|Γ|²+|T|²=1 无损能量守恒恒等（自由悬浮屏有透射，|Γ| 恒 1 是
    接地 AMC 口径不适用于本件）；f₀ 处 Γ=−1 全反射；远带 |Γ|→0 透明且
    频率对称；x_low·x_high=1；Jerusalem 与方环同构（同单源 EC 对偶口径）。"""
    rep = fss_design_report(10e-3, 1e-3, 0.5e-3, eps_eff=1.0)
    f = np.array([0.1 * rep["f0_hz"], rep["f0_hz"], 10.0 * rep["f0_hz"]])
    gam = fss_sheet_reflection_coeff(2 * np.pi * f, rep["l_h"], rep["c_f"])
    t = fss_sheet_transmission_coeff(2 * np.pi * f, rep["l_h"], rep["c_f"])
    assert np.allclose(np.abs(gam) ** 2 + np.abs(t) ** 2, 1.0, atol=1e-12)
    assert gam[1] == pytest.approx(-1.0, abs=1e-9)
    assert abs(gam[0]) < 0.2 and abs(gam[2]) < 0.2
    assert abs(gam[0]) == pytest.approx(abs(gam[2]), rel=1e-9)
    assert rep["f_low_hz"] * rep["f_high_hz"] == pytest.approx(
        rep["f0_hz"] ** 2, rel=1e-12)
    jer = jerusalem_screen_lc(10e-3, 1e-3, 0.5e-3)
    sq = square_loop_fss_lc(10e-3, 1e-3, 0.5e-3)
    assert jer["f0_hz"] == sq["f0_hz"]


# ─── AP-14 corrugated_horn ─────────────────────────────────────────────────

def test_bessel_roots_scipy_vs_literature_literals():
    """独立基准①：scipy 求根 vs 硬编码文献字面量（两独立来源逐位对拍）。"""
    assert bessel_root_j1p_first() == pytest.approx(1.8411837831, abs=1e-8)
    assert bessel_root_j1_first() == pytest.approx(3.8317059702, abs=1e-8)
    assert bessel_root_j1p_first() == pytest.approx(
        he11_balance_report(10e9, 10e-3, 3.75e-3)["te11_kc_a"], rel=1e-12)
    assert pytest.approx(bessel_root_j1_first(), abs=1e-8) == TM11_KC_A


def test_quarter_wave_depth_identity():
    """λ/4 深度定义恒等：d=c/(4f) 双向回收。"""
    d = quarter_wave_depth_m(10e9)
    assert d == pytest.approx(C0 / 4e10, rel=1e-15)
    assert math.isclose(d * 4 * 10e9, C0, rel_tol=1e-15)


def test_grooved_reactance_exact_limits():
    """独立基准②：短路 stub 精确极限——λ/4→+∞（开路/PMC）、λ/2→0（短路/
    PEC）、duty→1 退化裸短线、λ/4 前感性/后容性。"""
    f = 10e9
    d_qw = quarter_wave_depth_m(f)
    assert grooved_surface_reactance_ohm(f, d_qw, 0.9) == math.inf
    assert grooved_surface_reactance_ohm(f, 2 * d_qw, 0.9) == pytest.approx(0.0, abs=1e-9)
    # duty→1：裸短路线 X=η0·tan(k0·d)（d=λ/8 采样点）
    d_8 = quarter_wave_depth_m(f) / 2
    expect = ETA0 * math.tan(2 * math.pi * f * d_8 / C0)
    assert grooved_surface_reactance_ohm(f, d_8, 1.0) == pytest.approx(
        expect, rel=1e-12)
    assert grooved_surface_reactance_ohm(f, 0.9 * d_qw, 0.9) > 0
    assert grooved_surface_reactance_ohm(f, 1.1 * d_qw, 0.9) < 0


def test_he11_balance_report_shape():
    """诊断面：光壁分离度 = TM11/TE11 截止比；相位距符号随 d 跨 λ/4 翻转。"""
    f = 10e9
    rep = he11_balance_report(f, 10e-3, quarter_wave_depth_m(f) * 0.98, 0.9)
    assert rep["smooth_guide_separation"] == pytest.approx(
        3.8317059702 / 1.8411837831, rel=1e-9)
    assert rep["quarter_wave_phase_gap_rad"] < 0
    assert rep["reactance_regime"] == "inductive"
    rep2 = he11_balance_report(f, 10e-3, quarter_wave_depth_m(f) * 1.02, 0.9)
    assert rep2["quarter_wave_phase_gap_rad"] > 0
    assert rep2["reactance_regime"] == "capacitive"


# ─── MA-4 fpor ─────────────────────────────────────────────────────────────

def test_fpor_roundtrip_exact():
    """独立基准①：f0→f_s→εr 精确往返回收（均匀场串联层口径）。"""
    f0, er, t, gap = 1.0e9, 9.8, 0.1e-3, 1.0e-3
    f_s = fpor_fshift(f0, er, t, gap)
    assert f_s < f0
    assert fpor_er_from_fshift(f0, f_s, t, gap) == pytest.approx(er, rel=1e-12)


def test_fpor_full_fill_analytic_limit():
    """独立基准②：x→1（样品填满间隙）→ f_s=f0/√εr（串联层解析精确）。"""
    f0, er = 1.0e9, 9.0
    t, gap = 0.999e-3, 1.0e-3
    assert fpor_fshift(f0, er, t, gap) == pytest.approx(
        f0 / math.sqrt(er), rel=2e-3)


def test_fpor_first_order_k_form_convergence():
    """独立基准③：一阶 k 形（k=2/x 可推导）随 x(εr−1)→0 收敛到精确式
    （SPDR 边界"k 需标定"的均匀场极限锚）。"""
    f0, er, gap = 1.0e9, 2.0, 1.0e-3
    for t_mm in (0.5, 0.1, 0.02):
        t = t_mm * 1e-3
        f_s = fpor_fshift(f0, er, t, gap)
        exact = fpor_er_from_fshift(f0, f_s, t, gap)
        first = fpor_er_first_order(f0, f_s, t, gap)
        delta = fpor_fill_factor(t, gap) * (er - 1.0)
        # 一阶式误差 O(Δ)、Δ=x(εr−1)→0 收敛（门=1.2·Δ 宽于渐近常数）
        assert abs(first - exact) <= 1.2 * delta * exact, (t_mm, first, exact)
        assert first == pytest.approx(exact, rel=1.2 * delta + 1e-3), t_mm


def test_fpor_zero_perturbation_and_monotonicity():
    """t→0 零微扰恒等；εr↑ → f_s 单调降；填充因子守卫。"""
    f0 = 1.0e9
    assert fpor_fshift(f0, 9.8, 1e-9, 1e-3) == pytest.approx(f0, rel=1e-5)
    f1 = fpor_fshift(f0, 5.0, 0.1e-3, 1.0e-3)
    f2 = fpor_fshift(f0, 9.8, 0.1e-3, 1.0e-3)
    assert f2 < f1 < f0
    assert fpor_fill_factor(0.1e-3, 1.0e-3) == pytest.approx(0.1)
    with pytest.raises(ValueError, match="薄样品"):
        fpor_fill_factor(1.0e-3, 1.0e-3)


def test_fpor_loss_and_pe_model():
    """损耗面：p_e 必填 + (0,1] 域守卫；均匀场模型 p_e=x·εr/ε_eff 有界。"""
    qs, q0, pe = 200.0, 2000.0, 0.3
    td = fpor_tand_from_q(qs, q0, pe)
    assert td == pytest.approx((1 / qs - 1 / q0) / pe, rel=1e-12)
    with pytest.raises(ValueError, match="p_e"):
        fpor_tand_from_q(qs, q0, 1.5)
    pe_model = fpor_pe_uniform_field(9.8, 0.1e-3, 1.0e-3)
    assert 0.0 < pe_model < 1.0
    assert pe_model == pytest.approx(
        0.1 * 9.8 / (1 + 0.1 * (9.8 - 1)), rel=1e-12)
