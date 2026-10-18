"""gp_det 确定性 ARD-GP 底座单测（EC-16/17/18 共享内核的直测面）。

#118 双源：核矩阵/后验闭式 vs 手工双重循环逐位对拍；MLE 确定性同数据
同结果；nugget 联优退化（常数预测器）按 docstring 诚实标注钉住——消费
方误用面有测试锚。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.optimization.surrogate.gp_det import (
    KERNEL_KINDS,
    DetGaussianProcess,
    fit_mle,
    gp_nll,
    gp_posterior,
    matern52_ard_kernel,
    se_ard_kernel,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


def _se_manual(x: np.ndarray, ell: np.ndarray, amp: float) -> np.ndarray:
    """SE 核手工双重循环（与向量化实现互为独立路径）。"""
    n = x.shape[0]
    k = np.empty((n, n))
    for i in range(n):
        for j in range(n):
            q = float(np.sum(((x[i] - x[j]) / ell) ** 2))
            k[i, j] = amp * amp * np.exp(-0.5 * q)
    return k


class TestGpDet:
    def test_se_kernel_matches_manual_loop(self):
        rng = np.random.default_rng(5)
        x = rng.uniform(0, 1, (6, 2))
        ell = np.array([0.4, 0.7])
        np.testing.assert_allclose(
            se_ard_kernel(x, x, ell, 1.3), _se_manual(x, ell, 1.3),
            atol=1e-12)

    def test_posterior_exact_interpolation_noiseless(self):
        """近插值口径：训练点处 mean≈y、var≈0（两核各验；容差按
        Cholesky 条件数现实设定——K 近奇异时插值误差 ~1e-6 量级）。"""
        rng = np.random.default_rng(6)
        x = rng.uniform(0, 1, (10, 2))
        y = np.sin(2 * np.pi * x[:, 0]) + 0.3 * x[:, 1]
        for kind in KERNEL_KINDS:
            mean, var = gp_posterior(x, y, x, ell=np.array([0.5, 0.5]),
                                     amp=1.0, nugget=1e-8, kind=kind)
            np.testing.assert_allclose(mean, y, atol=1e-4)
            assert float(np.max(var)) < 1e-6

    def test_matern52_finite_and_symmetric(self):
        rng = np.random.default_rng(7)
        x = rng.uniform(0, 1, (5, 3))
        k = matern52_ard_kernel(x, x, np.array([0.3, 0.6, 0.9]), 0.8)
        assert np.all(np.isfinite(k))
        np.testing.assert_allclose(k, k.T, atol=1e-12)
        assert float(np.min(np.linalg.eigvalsh(k))) > 0

    def test_mle_deterministic_and_recovers_scale(self):
        """同数据同结果（C4）；拟合面在训练点近插值（nugget 固定口径）。"""
        rng = np.random.default_rng(8)
        x = rng.uniform(0, 1, (14, 1))
        y = np.exp(-3.0 * x[:, 0]) * np.cos(4.0 * np.pi * x[:, 0])
        p1 = fit_mle(x, y, kind="se")
        p2 = fit_mle(x, y, kind="se")
        assert np.array_equal(p1["ell"], p2["ell"])
        assert p1["nll"] == p2["nll"]
        gp = DetGaussianProcess(x, y, p1, "se")
        mean, _ = gp.predict(x)
        np.testing.assert_allclose(mean, y, atol=1e-3)

    def test_nugget_optimized_mle_degeneracy_documented(self):
        """联优 nugget 在小样本退化（docstring 诚实标注的负例钉）：
        √x 面上 nugget→大值、预测退化为常数面（NRMSE≈1）。"""
        rng = np.random.default_rng(7)
        x = rng.uniform(0.001, 1, (14, 1))
        y = np.sqrt(x[:, 0])
        p = fit_mle(x, y, kind="se", optimize_nugget=True)
        grid = np.linspace(0.001, 1, 100)[:, None]
        mean, _ = gp_posterior(x, y, grid, ell=p["ell"], amp=p["amp"],
                               nugget=p["nugget"], kind="se")
        tru = np.sqrt(grid[:, 0])
        nrmse = float(np.sqrt(np.mean((mean - tru) ** 2)) / np.std(tru))
        assert nrmse > 0.9  # 退化事实钉住（消费方须自证后才可开联优）
        assert gp_nll(np.log(np.r_[p["ell"], p["amp"], p["nugget"]]),
                      x, y, "se") == pytest.approx(p["nll"])
