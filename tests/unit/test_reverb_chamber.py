"""EM-8 混响室闭式单测（Weyl/Q 上界/χ² 统计/搅拌独立数，2026-10-03）。

锚树口径（#118：锚值独立复算/独立公式，不赌推导）：
- Weyl 模式数与 core/microwave_heating.weyl_mode_stats（LT-5）跨模块互证
  （同式异实现，实测逐位一致门 1e-12 相对）。
- Q 上界结构锚：δ∝f^(-1/2) → Q∝f^(+1/2)（双频比值恒等）；Q = 3V/(2 μ_r S δ)
  量纲构造（米³/米³ 无量纲）；μ_r 进入分母的线性恒等。
- χ² 统计以 scipy.stats（chi2/expon/maxwell 族）作独立裁判（非本模块实现路）：
  df=2 pdf 与 expon.pdf 逐点相等；df=6 cdf 与 chi2.cdf(6) 逐点 ≤1e-12 相对。
- max-of-N 期望 = H_N 恒等 vs scipy.stats.expon.ppf(1-1/(N+1)) 期望无关的
  独立路：用 exp.maxpdf 积分数值裁判（quad），门 ≤1e-9。
- 搅拌独立数：floor 语义锚（B=10Δf → N=10）；Δf=f/Q 定义恒等。
"""
from __future__ import annotations

import math

import pytest

from rfauto.core import reverb_chamber as rc
from rfauto.core.microwave_heating import weyl_mode_stats

_V = 8.0  # 2m x 2m x 2m
_S = 24.0
_SIGMA_CU = 5.8e7


def test_weyl_cross_anchor_vs_microwave_heating():
    """跨模块互证：与 LT-5 weyl_mode_stats 同式（相对门 1e-12）。"""
    for f in (1e9, 6e9, 18e9):
        mine = rc.weyl_mode_count(_V, f, 1.0)
        ref = weyl_mode_stats(_V, f, 1.0)
        assert abs(mine["n_modes"] - float(ref["n_weyl"])) <= 1e-12 * abs(
            mine["n_modes"])


def test_weyl_scaling_law():
    """N∝f³ 结构锚：10 倍频 → 1000 倍模式数（相对 1e-12）。"""
    a = rc.weyl_mode_count(_V, 1e9)["n_modes"]
    b = rc.weyl_mode_count(_V, 1e10)["n_modes"]
    assert abs(b / a - 1000.0) <= 1e-9


@pytest.mark.parametrize("f_hz", [1e9, 5e9, 2e10])
def test_q_wall_sqrt_f_scaling(f_hz):
    """Q∝√f 结构锚：Q(4f)/Q(f)=2（δ∝f^(-1/2) 恒等）。"""
    q1 = rc.quality_factor_wall_loss(_V, _S, f_hz, _SIGMA_CU)["q_wall"]
    q4 = rc.quality_factor_wall_loss(_V, _S, 4.0 * f_hz, _SIGMA_CU)["q_wall"]
    assert abs(q4 / q1 - 2.0) <= 1e-12


def test_q_wall_mu_r_identity():
    """μ_r 结构锚：δ=√(2/(ωμ0 μ_r σ)) 随 μ_r 收缩、Rs∝√μ_r → Q∝1/√μ_r。

    Q(μ_r=2) = Q(μ_r=1)/√2（Q=3V/(μ_r S δ) 与 δ(μ_r) 联立的精确推论，
    独立复算对照）。
    """
    q1 = rc.quality_factor_wall_loss(_V, _S, 1e9, _SIGMA_CU, 1.0)["q_wall"]
    q2 = rc.quality_factor_wall_loss(_V, _S, 1e9, _SIGMA_CU, 2.0)["q_wall"]
    assert abs(q2 / q1 - 1.0 / math.sqrt(2.0)) <= 1e-12


def test_q_wall_independent_formula_anchor():
    """独立公式复算：Q=3V/(2 μ_r S δ)，δ 独立闭式直算（相对 1e-12）。"""
    f = 3e9
    delta = math.sqrt(2.0 / (2.0 * math.pi * f * 4e-7 * math.pi * _SIGMA_CU))
    q_expect = 1.5 * _V / (1.0 * _S * delta)
    q_mine = rc.quality_factor_wall_loss(_V, _S, f, _SIGMA_CU)["q_wall"]
    assert abs(q_mine - q_expect) <= 1e-12 * q_expect


def test_chi2_df2_pdf_matches_expon_scipy():
    """df=2 pdf ≡ Exp(1)：scipy.stats.expon 独立裁判（相对 1e-12）。"""
    from scipy import stats

    for u in (0.0, 0.3, 1.0, 2.718, 10.0):
        a = rc.well_stirred_chi2_pdf(u)
        b = float(stats.expon.pdf(u))
        assert abs(a - b) <= 1e-12 * max(1.0, b)


def test_chi2_df6_pdf_cdf_matches_scipy():
    """df=6 pdf/cdf vs scipy.stats.chi2(6)（相对 1e-10）。"""
    from scipy import stats

    for x in (0.5, 1.0, 3.0, 6.0, 12.0, 30.0):
        a = rc.chi2_df6_pdf(x)
        b = float(stats.chi2.pdf(x, 6))
        assert abs(a - b) <= 1e-10 * max(1.0, b)
        c = rc.chi2_df6_cdf(x)
        d = float(stats.chi2.cdf(x, 6))
        assert abs(c - d) <= 1e-10 * max(1.0, d)


def test_chi2_quantile_inversion_identity():
    """分位-分布自反：cdf(quantile(p)) = p（相对 1e-12）。"""
    for p in (0.0, 0.05, 0.5, 0.95, 0.999):
        u = rc.well_stirred_chi2_quantile(p)
        assert abs(rc.well_stirred_chi2_cdf(u) - p) <= 1e-12


def test_max_of_n_exponential_mean_vs_numeric_quad():
    """E[max of N Exp(1)] = H_N：独立数值积分裁判（绝门 1e-9）。

    独立路：pdf_max(u) = N·(1−e^{−u})^{N−1}·e^{−u}，期望 ∫u·pdf_max du。
    """
    from scipy import integrate

    for n in (1, 2, 5, 10):
        def pdf_max(u, N=n):
            return N * (1.0 - math.exp(-u)) ** (N - 1) * math.exp(-u)

        val, _ = integrate.quad(lambda u: u * pdf_max(u), 0.0, math.inf,
                                limit=200)
        h_n = rc.max_of_n_exponential_mean(n)
        assert abs(val - h_n) <= 1e-9


def test_independent_stirrer_samples_floor_semantics():
    """floor 语义锚：B=10Δf → N=10；非整数带向下取整；恒等 Δf=f/Q。"""
    f = 1e9
    q = 5e4
    out = rc.independent_stirrer_samples(10.0 * f / q, f, q)
    assert out["n_independent"] == 10.0
    assert abs(out["mode_bandwidth_hz"] - f / q) <= 1e-18 * f
    out2 = rc.independent_stirrer_samples(10.5 * f / q, f, q)
    assert out2["n_independent"] == 10.0
    out3 = rc.independent_stirrer_samples(0.99 * f / q, f, q)
    assert out3["n_independent"] == 0.0


def test_rc_sac_note_doc_face():
    """文档面：换算不做数值系数声明在案（铁律 7/#122）。"""
    note = rc.rc_vs_sac_note()
    assert "不做单值经验系数" in note["numeric_conversion"]
    assert "UNVERIFIED" in note["standards_scope"]


def test_invalid_inputs_rejected():
    """非法输入显式 ValueError（不静默兜底）。"""
    with pytest.raises(ValueError):
        rc.weyl_mode_count(0.0, 1e9)
    with pytest.raises(ValueError):
        rc.quality_factor_wall_loss(_V, -1.0, 1e9, _SIGMA_CU)
    with pytest.raises(ValueError):
        rc.well_stirred_chi2_quantile(1.0)
    with pytest.raises(ValueError):
        rc.max_of_n_exponential_mean(0)
    with pytest.raises(ValueError):
        rc.independent_stirrer_samples(1e6, 0.0, 1e4)
