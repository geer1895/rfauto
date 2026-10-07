"""ME-16 主动子空间自实现单元测试——合成方向恢复 + 解析协方差对拍 + 守卫。

判据（计划 ME-16）：
- 合成已知主方向函数 f(x)=g(aᵀx) → 恢复 a 方向 cos 相似 ≥ 1-1e-6；
- 特征值与解析协方差对拍（手搭 C=GᵀG/n 的 eigvalsh 逐位对拍 +
  线性目标解析特征值精确断言）；
- n<p 守卫显式拒绝；形状/参数校验。
"""

import sys
from pathlib import Path

import numpy as np
import pytest

# 确保 src 在 path 中
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.core.active_subspace import active_subspace, reduce_dimension


def _ridge_fixture(seed: int = 7, d: int = 4, n: int = 60):
    """单位主方向 a + 均匀采样 X + 解析梯度（f=sin(aᵀx) → ∇f=cos(aᵀx)·a）。"""
    rng = np.random.default_rng(seed)
    a = rng.normal(size=d)
    a /= np.linalg.norm(a)
    X = rng.uniform(-1.0, 1.0, size=(n, d))
    t = X @ a
    grads = np.cos(t)[:, None] * a[None, :]
    return a, X, grads


class TestRidgeDirectionRecovery:
    """合成已知主方向恢复：f(x)=g(aᵀx) → 主方向 cos 相似 ≥ 1-1e-6。"""

    def test_exact_grads_recovers_direction(self):
        a, X, grads = _ridge_fixture()
        res = active_subspace(X, grads, 1)
        assert res["method"] == "analytic_grads"
        cos_sim = abs(float(a @ res["active_dirs"][:, 0]))
        assert cos_sim >= 1.0 - 1e-6

    def test_central_difference_recovers_direction(self):
        """无梯模式：中心差分梯度同样恢复主方向（差分误差 O(h²)+O(ε/h)）。"""
        a, X, _grads = _ridge_fixture()
        res = active_subspace(
            X, n_active=1, f=lambda x: float(np.sin(float(x @ a))))
        assert res["method"] == "central_difference"
        cos_sim = abs(float(a @ res["active_dirs"][:, 0]))
        assert cos_sim >= 1.0 - 1e-6

    def test_two_ridge_recovers_both_directions(self):
        """双脊 f=sin(a1ᵀx)+2cos(a2ᵀx)：top-2 子空间同时覆盖 a1/a2。

        cos·sin 交叉项在立方体对称采样下恒零 → C 严格秩 2：top-2 子空间
        恢复两方向（cos·cos 类交叉项非零的同奇偶脊构造不在此列），
        补空间零能量 → partition ratio 如实报 inf。
        """
        rng = np.random.default_rng(7)
        d = 4
        a = rng.normal(size=d)
        a /= np.linalg.norm(a)
        a2 = rng.normal(size=d)
        a2 -= (a2 @ a) * a
        a2 /= np.linalg.norm(a2)
        X = rng.uniform(-1.0, 1.0, size=(400, d))
        res = active_subspace(
            X, n_active=2,
            f=lambda x: float(np.sin(float(x @ a)) + 2.0 * np.cos(float(x @ a2))))
        W = res["active_dirs"]
        # 子空间投影范数（|a1ᵀw1|²+|a1ᵀw2|² 的平方根）≥ 0.99
        assert float(np.linalg.norm(W.T @ a)) >= 0.99
        assert float(np.linalg.norm(W.T @ a2)) >= 0.99
        # 严格秩 2：补空间无变化能量 → inf（诚实语义，非数值故障）
        assert res["partition_ratio"] == float("inf")

    def test_partition_ratio_finite_with_nonridge_tail(self):
        """非脊尾项 f=sin(a1ᵀx)+0.3·x_d²：补空间注入真实能量 → ratio 有限。

        cos(t1)·x_d 交叉项为奇函数（立方体对称下期望恒零），不污染主
        方向——x_d² 项给补空间注入 O(0.1) 能量，partition ratio 有限且
        显著大于 1，主方向恢复不受影响。
        """
        rng = np.random.default_rng(7)
        d = 4
        a = rng.normal(size=d)
        a /= np.linalg.norm(a)
        X = rng.uniform(-1.0, 1.0, size=(400, d))
        res = active_subspace(
            X, n_active=1,
            f=lambda x: float(np.sin(float(x @ a)) + 0.3 * float(x[-1]) ** 2))
        assert float(np.linalg.norm(res["active_dirs"].T @ a)) >= 0.99
        assert np.isfinite(res["partition_ratio"])
        assert res["partition_ratio"] > 1.0


class TestEigenvaluesAnalytic:
    """特征值与解析协方差对拍。"""

    def test_linear_function_exact_eigenvalue(self):
        """f=2aᵀx（常梯度 2a）→ C=4a aᵀ 解析：λ1=4，余 ≈0，partition=inf。"""
        a, X, _ = _ridge_fixture()
        grads = np.full(X.shape, 0.0)
        grads += 2.0 * a[None, :]
        res = active_subspace(X, grads, 1)
        assert res["eigenvalues"][0] == pytest.approx(4.0, abs=1e-10)
        assert float(np.max(res["eigenvalues"][1:])) <= 1e-12
        # 补空间能量低于数值精度 → 如实报 inf（不伪造有限比值）
        assert res["partition_ratio"] == float("inf")

    def test_matches_hand_built_covariance(self):
        """与手搭解析协方差 C=GᵀG/n 的 eigvalsh 逐位对拍（atol 1e-12）。"""
        _a, X, grads = _ridge_fixture()
        res = active_subspace(X, grads, 2)
        C = grads.T @ grads / len(X)
        ref = np.sort(np.linalg.eigvalsh(C))[::-1]
        np.testing.assert_allclose(res["eigenvalues"], ref, atol=1e-12)

    def test_sign_canonicalized_deterministic(self):
        """符号规范化：每列最大分量恒为正（同输入两次调用逐位一致）。"""
        _a, X, grads = _ridge_fixture()
        r1 = active_subspace(X, grads, 1)
        r2 = active_subspace(X, grads, 1)
        for col in r1["eigenvectors"].T:
            assert col[int(np.argmax(np.abs(col)))] > 0
        np.testing.assert_array_equal(r1["eigenvalues"], r2["eigenvalues"])
        np.testing.assert_array_equal(r1["eigenvectors"], r2["eigenvectors"])


class TestReduceDimension:
    """主方向投影 + 线性重建误差估计。"""

    def test_linear_target_reconstruction_exact(self):
        """y=2aᵀx+1 在主动坐标上严格线性 → rel_error ≈ 0（≤1e-10）。"""
        a, X, grads = _ridge_fixture()
        y = 2.0 * (X @ a) + 1.0
        rd = reduce_dimension(X, y, grads, n_active=1)
        assert rd["rel_error"] <= 1e-10
        assert rd["r2"] == pytest.approx(1.0, abs=1e-10)
        assert rd["intercept"] == pytest.approx(1.0, abs=1e-8)
        assert rd["X_active"].shape == (len(X), 1)
        assert rd["W1"].shape == (len(a), 1)

    def test_nonlinear_target_positive_error(self):
        """y=sin(aᵀx)：一阶线性重建必然失配 → rel_error 显著非零。"""
        a, X, grads = _ridge_fixture()
        y = np.sin(X @ a)
        rd = reduce_dimension(X, y, grads, n_active=1)
        assert rd["rel_error"] > 1e-6

    def test_constant_y_degrades_to_absolute_rms(self):
        """y 为常数（零方差）时 rel_error 退报绝对 RMS、r2=None（不除零）。"""
        _a, X, grads = _ridge_fixture()
        y = np.full(len(X), 3.14)
        rd = reduce_dimension(X, y, grads, n_active=1)
        assert rd["r2"] is None
        assert rd["rel_error"] == pytest.approx(
            float(np.sqrt(np.mean((y - rd["y_pred"]) ** 2))), rel=1e-9)


class TestGuards:
    """输入守卫：n<p 拒绝 / 形状校验 / 参数域。"""

    def test_n_lt_p_rejected(self):
        """n<p 守卫：样本数少于维度时协方差秩亏，显式拒绝。"""
        X = np.random.default_rng(0).uniform(-1, 1, size=(3, 5))
        with pytest.raises(ValueError, match=r"n<p|秩亏"):
            active_subspace(X, n_active=1, f=lambda x: 0.0)

    def test_n_lt_p_also_in_reduce_dimension(self):
        X = np.random.default_rng(0).uniform(-1, 1, size=(2, 4))
        with pytest.raises(ValueError, match="秩亏"):
            reduce_dimension(X, np.zeros(2), n_active=1, f=lambda x: 0.0)

    def test_n_active_out_of_bounds(self):
        a, X, grads = _ridge_fixture()
        with pytest.raises(ValueError, match="n_active"):
            active_subspace(X, grads, 0)
        with pytest.raises(ValueError, match="n_active"):
            active_subspace(X, grads, len(a) + 1)

    def test_grads_shape_mismatch(self):
        _a, X, grads = _ridge_fixture()
        with pytest.raises(ValueError, match="不一致"):
            active_subspace(X, grads[:-1], 1)

    def test_requires_grads_or_f(self):
        _a, X, _ = _ridge_fixture()
        with pytest.raises(ValueError, match="f"):
            active_subspace(X, n_active=1)

    def test_1d_input_rejected(self):
        with pytest.raises(ValueError, match="二维"):
            active_subspace(np.zeros(10), n_active=1, f=lambda x: 0.0)

    def test_bad_weights_rejected(self):
        _a, X, grads = _ridge_fixture()
        with pytest.raises(ValueError, match="weights"):
            active_subspace(X, grads, 1, weights=np.full(len(X) + 1, 1.0))
        with pytest.raises(ValueError, match="weights"):
            active_subspace(X, grads, 1, weights=np.full(len(X), -1.0))

    def test_nonfinite_inputs_rejected(self):
        _a, X, grads = _ridge_fixture()
        grads_bad = grads.copy()
        grads_bad[0, 0] = np.nan
        with pytest.raises(ValueError, match="非有限"):
            active_subspace(X, grads_bad, 1)
        with pytest.raises(ValueError, match="非有限"):
            reduce_dimension(X, np.full(len(X), np.nan), grads, n_active=1)

    def test_weighted_covariance_matches_manual(self):
        """加权协方差 C=Σwᵢ∇fᵢ∇fᵢᵀ/Σw 与手搭实现对拍。"""
        _a, X, grads = _ridge_fixture()
        w = np.linspace(0.5, 2.0, len(X))
        res = active_subspace(X, grads, 1, weights=w)
        C = (grads * w[:, None]).T @ grads / w.sum()
        ref = np.sort(np.linalg.eigvalsh(C))[::-1]
        np.testing.assert_allclose(res["eigenvalues"], ref, atol=1e-12)
