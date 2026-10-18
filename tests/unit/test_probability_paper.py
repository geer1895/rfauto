"""XD-15 概率纸坐标变换与 Weibull 作图回归单测（core/probability_paper.py）。

裁判 = 线性化恒等式 + 独立常数 + 跨路线互证（#118 不自证）：
- Weibull 概率纸线性化恒等式（任务锚）：精确分位数样本
  t_i=η·(−ln(1−p_i))^{1/β}（p_i=Benard 中位秩）作 OLS → 斜率机器精度
  回收形状参数 β、η̂=exp(−intercept/slope) 机器精度回收特征寿命、
  残差≈0（实测 ≤3e-15）；坐标恒等式 y=β·(x−ln η) 逐位；
- Benard 中位秩（Benard & Bos-Levenbach 1953；NIST e-Handbook §8.2.2.3）：
  p_1=(0.7)/(n+0.4) 独立常数式、对称恒等式 p_i+p_{n+1−i}=1（≤1e-15）、
  严格单调、恒落开区间 (0,1)；
- 正态概率纸（probit=Φ⁻¹，scipy.special.ndtri）：p=0.5→0、
  Φ⁻¹(0.8413447460685429)=1.0（1σ 点独立常数）、对称恒等式
  Φ⁻¹(1−p)=−Φ⁻¹(p)（≤1e-12）、对数正态纸 log_x 横轴 ln t；
- 跨路线互证：同一完全样本上作图 OLS vs alt_planning.fit_loglinear_
  weibull（MLE）——Benard-OLS 与 MLE 是不同估计量（有限样本已知差，
  n=50 实测 β 差 3.8%），预声明统计容差带 5%（β）/2%（η）互证一致，
  不逐位（估计量口径不同，如实注记）；
- 乱序输入自动升序排序后配秩（作图位=次序统计量约定），排序不变性
  钉（乱序/升序拟合结果逐位同）；
- 域守卫：n<2/全同 t（S_xx=0）/p 越界 (0,1)/t≤0/非有限值/长度不配
  显式拒绝。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.probability_paper import (
    benard_median_ranks,
    fit_weibull_paper,
    normal_paper_xy,
    weibull_paper_xy,
)

ONE_SIGMA_P = 0.8413447460685429   # Φ(1)（测试侧独立常数）


def _exact_weibull_sample(beta: float, eta: float, n: int) -> np.ndarray:
    """精确 Weibull 分位数样本（Benard 位反演，测试侧独立构造）。"""
    p = benard_median_ranks(n)
    return eta * (-np.log(1.0 - p)) ** (1.0 / beta)


# ─── Benard 中位秩：常数式 / 对称恒等式 / 单调 / 守卫 ────────────────────────


def test_benard_ranks_symmetry_and_bounds():
    """p_1=0.7/(n+0.4) 独立常数式；p_i+p_{n+1−i}=1 对称恒等式；开区间。"""
    for n in (1, 2, 8, 50):
        p = benard_median_ranks(n)
        assert p.shape == (n,)
        assert p[0] == pytest.approx(0.7 / (n + 0.4), rel=1e-15)
        assert p[-1] == pytest.approx((n - 0.3) / (n + 0.4), rel=1e-15)
        assert bool(np.all(np.diff(p) > 0.0)), "中位秩须严格单调增"
        assert bool(np.all((p > 0.0) & (p < 1.0))), "作图位须落开区间 (0,1)"
        assert bool(np.all(np.abs(p + p[::-1] - 1.0) <= 1e-15)), \
            "对称恒等式 p_i+p_{n+1−i}=1（1 ulp 容差）"
    assert benard_median_ranks(1)[0] == pytest.approx(0.5, rel=1e-15)
    for bad in (0, -3, 2.5, True):
        with pytest.raises(ValueError):
            benard_median_ranks(bad)


# ─── Weibull 纸：线性化恒等式 + 作图回归机器精度回收（任务锚）────────────────


def test_weibull_paper_identity_and_fit_recovery():
    """任务锚：精确分位数样本 OLS 斜率=β、η̂=η 机器精度回收，残差≈0。"""
    beta, eta, n = 2.5, 1000.0, 20
    t = _exact_weibull_sample(beta, eta, n)
    fit = fit_weibull_paper(t)
    assert fit["slope_beta"] == pytest.approx(beta, abs=1e-9)
    assert fit["eta_hat"] == pytest.approx(eta, rel=1e-12)
    assert fit["intercept"] == pytest.approx(-beta * math.log(eta),
                                             abs=1e-9)
    assert fit["residual_max_abs"] <= 1e-12
    assert fit["residual_rms"] <= 1e-12
    assert fit["r_squared"] == pytest.approx(1.0, abs=1e-12)
    assert fit["n"] == n
    # 坐标恒等式：y=β·(x−ln η)（测试侧独立式，≤1e-12）
    p = benard_median_ranks(n)
    x, y = weibull_paper_xy(t, p)
    assert float(np.max(np.abs(np.asarray(y)
                               - beta * (np.asarray(x) - math.log(eta))))) \
        <= 1e-12
    # 特征寿命点锚：t=η → p=1−e^{−1}、y=ln(−ln(e^{−1}))=0、x=ln η（标量出）
    sx, sy = weibull_paper_xy(eta, 1.0 - math.exp(-1.0))
    assert sx == pytest.approx(math.log(eta), rel=1e-15)
    assert sy == pytest.approx(0.0, abs=1e-15)


def test_fit_sort_invariance_and_mle_cross_check():
    """乱序输入排序不变性（逐位）；同数据 vs alt_planning MLE 统计带互证。"""
    beta, eta = 1.8, 500.0
    t = _exact_weibull_sample(beta, eta, 50)
    fit_sorted = fit_weibull_paper(t)
    rng = np.random.default_rng(7)
    shuffled = np.asarray(t)[rng.permutation(50)]
    fit_shuffled = fit_weibull_paper(shuffled)
    assert fit_shuffled["slope_beta"] == fit_sorted["slope_beta"]
    assert fit_shuffled["eta_hat"] == fit_sorted["eta_hat"]
    assert fit_sorted["slope_beta"] == pytest.approx(beta, abs=1e-9)
    # 排序落盘可复核：plotting_x 升序、benard_p 逐位同 benard_median_ranks
    assert bool(np.all(np.diff(fit_sorted["plotting_x"]) > 0.0))
    assert bool(np.array_equal(fit_sorted["benard_p"],
                               benard_median_ranks(50)))
    # 跨路线互证（预声明统计容差带）：Benard-OLS vs MLE 有限样本已知差
    # 实测 β 3.8%——带 5%（β）/2%（η）钉一致，不逐位（估计量口径不同）
    from rfauto.core.alt_planning import fit_loglinear_weibull
    mle = fit_loglinear_weibull(np.empty((50, 0)), t_obs_h=t.tolist(),
                                status=[1] * 50)
    assert fit_sorted["slope_beta"] == pytest.approx(mle["beta"], rel=0.05)
    assert fit_sorted["eta_hat"] == pytest.approx(
        math.exp(mle["coefficients"][0]), rel=0.02)


# ─── 正态纸：probit 独立常数 / 对称恒等式 / 对数正态横轴 ─────────────────────


def test_normal_paper_anchors_and_rejections():
    """p=0.5→0、1σ 点→1.0（独立常数）；对称恒等式；log_x；域守卫族。"""
    x, y = normal_paper_xy(2.5, 0.5)
    assert (x, y) == (2.5, 0.0)
    _, y1 = normal_paper_xy(1.0, ONE_SIGMA_P)
    assert y1 == pytest.approx(1.0, abs=1e-12)
    p = np.array([0.01, 0.2, 0.3, 0.5, 0.7, 0.93, 0.99])
    _, yv = normal_paper_xy(np.ones_like(p), p)
    _, yv_c = normal_paper_xy(np.ones_like(p), 1.0 - p)
    assert float(np.max(np.abs(np.asarray(yv) + np.asarray(yv_c)))) <= 1e-12
    # 对数正态纸：横轴 ln t（测试侧独立式）
    t = np.array([1.0, 10.0, 100.0])
    xl, _ = normal_paper_xy(t, np.array([0.3, 0.5, 0.7]), log_x=True)
    assert bool(np.array_equal(np.asarray(xl), np.log(t)))
    # 守卫族：p 越界开区间 / t≤0（log_x）/ 长度不配 / 非有限
    for pp in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            normal_paper_xy(1.0, pp)
    with pytest.raises(ValueError):
        normal_paper_xy(0.0, 0.5, log_x=True)
    with pytest.raises(ValueError):
        normal_paper_xy([1.0, 2.0], [0.5])
    with pytest.raises(ValueError):
        weibull_paper_xy([1.0, float("nan")], [0.5])
    with pytest.raises(ValueError):
        weibull_paper_xy([1.0, 2.0], [0.5])


def test_fit_degenerate_and_domain_rejections():
    """n<2 / 全同 t（S_xx=0）/ t≤0 / 非有限显式拒绝（回归退化不猜）。"""
    with pytest.raises(ValueError, match="n≥2"):
        fit_weibull_paper([100.0])
    with pytest.raises(ValueError, match="S_xx=0"):
        fit_weibull_paper([100.0, 100.0, 100.0])
    with pytest.raises(ValueError):
        fit_weibull_paper([100.0, 0.0, 50.0])
    with pytest.raises(ValueError):
        fit_weibull_paper([100.0, float("inf"), 50.0])
