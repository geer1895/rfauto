"""numpy 自实现 NUTS 内核单测（aurora_p E2；判据预声明，先于实验冻结）。

覆盖（预声明验收 A/D + U-Turn 行为钉 + 负例 + ESS 裁判自锚）：
- 标准后验锚（判据 A）：标准正态/相关高斯/各向异性高斯的均值-std
  置信带（写死容差，seed 固定=确定性事实）；
- U-Turn 折返行为：早停（不触顶）+大步长立即折返+深度上限尊重；
- 同 seed 确定性（判据 D）：样本/诊断逐位；
- 支撑外 −inf 回调处置（有界支撑尊重，不崩不 NaN）；
- 负例（显式报错不静默）；
- ESS 裁判面自锚（#300 家法：裁判先过已知形态——iid 链 ESS≈n、
  AR(1) 强相关链 ESS≪n）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.optimization.nuts_sampler import (
    effective_sample_size,
    nuts_sample,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


def _std_normal_5d(th: np.ndarray) -> tuple[float, np.ndarray]:
    return float(-0.5 * th @ th), -th


def _gauss_2d(prec: np.ndarray):
    def lg(th: np.ndarray) -> tuple[float, np.ndarray]:
        return float(-0.5 * th @ prec @ th), -(prec @ th)

    return lg


class TestStandardNormalAnchor:
    """判据 A：已知后验均值/std 落写死置信带（seed 固定=确定性事实）。"""

    def test_5d_mean_std_in_dead_bands(self):
        res = nuts_sample(_std_normal_5d, np.zeros(5), seed=42,
                          n_samples=500, burn=200, step_size=0.5,
                          max_tree_depth=8)
        s = res["samples"]
        assert s.shape == (500, 5)
        assert res["logp_samples"].shape == (500,)
        mean = s.mean(axis=0)
        std = s.std(axis=0)
        assert np.all(np.abs(mean) <= 0.15), f"mean 越带: {mean}"
        assert np.all(std >= 0.85) and np.all(std <= 1.15), (
            f"std 越带: {std}")
        # 健康探针：混合良好（预声明带）
        assert res["move_rate"] >= 0.9
        assert res["n_divergent"] == 0
        assert np.all(np.isfinite(res["logp_samples"]))

    def test_2d_correlated_gaussian(self):
        cov = np.array([[1.0, 0.9], [0.9, 1.0]])
        lg = _gauss_2d(np.linalg.inv(cov))
        res = nuts_sample(lg, np.zeros(2), seed=7, n_samples=800,
                          burn=300, step_size=0.35)
        s = res["samples"]
        assert np.all(np.abs(s.mean(axis=0)) <= 0.15)
        std = s.std(axis=0)
        assert np.all(std >= 0.85) and np.all(std <= 1.15), f"std: {std}"
        assert res["n_divergent"] == 0

    def test_anisotropic_scales(self):
        # 尺度差 4× 的各向异性高斯（std 0.5 与 2.0）——步长 0.25 档
        lg = _gauss_2d(np.diag([1.0 / 0.25, 1.0 / 4.0]))
        res = nuts_sample(lg, np.zeros(2), seed=11, n_samples=800,
                          burn=300, step_size=0.25)
        s = res["samples"]
        assert np.all(np.abs(s.mean(axis=0)) <= 0.2), (
            f"mean 越带: {s.mean(axis=0)}")
        std = s.std(axis=0)
        assert 0.40 <= std[0] <= 0.62, f"窄维 std: {std[0]}"
        assert 1.55 <= std[1] <= 2.35, f"宽维 std: {std[1]}"


class TestUTurnBehavior:
    """U-Turn 折返行为钉：早停、大步长立即折返、深度上限尊重。"""

    CORR = np.linalg.inv(np.array([[1.0, 0.9], [0.9, 1.0]]))

    def test_tree_terminates_before_cap(self):
        # 相关高斯上 U-Turn 应远早于触顶折返（同 seed 确定性事实）
        res = nuts_sample(_gauss_2d(self.CORR), np.zeros(2), seed=7,
                          n_samples=300, burn=100, step_size=0.35,
                          max_tree_depth=8)
        assert res["tree_depth_mean"] < 8.0, (
            "未触 U-Turn 早停——折返判据失效")
        # leapfrog 预算上界：每迭代至多 Σ_{j=0..cap}(2^{j+1}−1) 步
        budget_per_iter = sum(2 ** (j + 1) - 1 for j in range(8))
        n_iter = 400
        assert res["leapfrog_total"] < n_iter * budget_per_iter

    def test_large_step_folds_back_immediately(self):
        # 步长 ≫ 后验尺度 → 首次倍增即折返（平均树深 < 2）
        res = nuts_sample(_gauss_2d(self.CORR), np.zeros(2), seed=7,
                          n_samples=200, burn=50, step_size=2.0,
                          max_tree_depth=10)
        assert res["tree_depth_mean"] < 2.0, (
            f"大步长未立即折返: depth={res['tree_depth_mean']}")

    def test_depth_cap_respected(self):
        res = nuts_sample(_std_normal_5d, np.zeros(5), seed=3,
                          n_samples=100, burn=20, step_size=0.5,
                          max_tree_depth=1)
        assert res["tree_depth_mean"] <= 1.0
        assert res["max_tree_depth"] == 1


class TestDeterminism:
    """判据 D：同 seed 逐位复现；异 seed 链不同（随机流生效旁证）。"""

    def test_same_seed_bitwise(self):
        kw = dict(seed=99, n_samples=120, burn=40, thin=2, step_size=0.4)
        r1 = nuts_sample(_std_normal_5d, np.zeros(5), **kw)
        r2 = nuts_sample(_std_normal_5d, np.zeros(5), **kw)
        assert np.array_equal(r1["samples"], r2["samples"])
        assert np.array_equal(r1["logp_samples"], r2["logp_samples"])
        assert r1["move_rate"] == r2["move_rate"]
        assert r1["leapfrog_total"] == r2["leapfrog_total"]
        assert r1["tree_depth_mean"] == r2["tree_depth_mean"]

    def test_different_seed_differs(self):
        r1 = nuts_sample(_std_normal_5d, np.zeros(5), seed=1,
                         n_samples=50, burn=10)
        r2 = nuts_sample(_std_normal_5d, np.zeros(5), seed=2,
                         n_samples=50, burn=10)
        assert not np.array_equal(r1["samples"], r2["samples"])

    def test_chain_config_echo(self):
        res = nuts_sample(_std_normal_5d, np.zeros(5), seed=5,
                          n_samples=30, burn=10, thin=3, step_size=0.25,
                          max_tree_depth=4)
        assert res["seed"] == 5 and res["n_samples"] == 30
        assert res["burn"] == 10 and res["thin"] == 3
        assert res["step_size"] == 0.25 and res["max_tree_depth"] == 4


class TestSupportAndNumerics:
    """支撑外 −inf 回调处置：有界支撑被尊重，不崩不 NaN。"""

    def test_hard_box_support_respected(self):
        def lg_box(th: np.ndarray) -> tuple[float, np.ndarray]:
            if np.any(np.abs(th) > 2.0):
                return -np.inf, np.zeros_like(th)
            return float(-0.5 * th @ th), -th

        res = nuts_sample(lg_box, np.zeros(4), seed=13, n_samples=300,
                          burn=100, step_size=0.4)
        s = res["samples"]
        assert np.all(np.abs(s) <= 2.0 + 1e-12), "链逃出支撑盒"
        assert np.all(np.isfinite(s))
        assert np.all(np.isfinite(res["logp_samples"]))

    def test_half_space_truncated_normal(self):
        def lg_half(th: np.ndarray) -> tuple[float, np.ndarray]:
            if th[0] > 1.0:
                return -np.inf, np.zeros_like(th)
            return float(-0.5 * th @ th), -th

        res = nuts_sample(lg_half, np.zeros(2), seed=17, n_samples=400,
                          burn=100, step_size=0.4)
        assert np.all(res["samples"][:, 0] <= 1.0 + 1e-12)
        # 理论：N(0,1) 上截断于 1 → E[X|X≤1]=−φ(1)/Φ(1)≈−0.288
        # （右侧尾巴被切除，均值左移）；写死带 ±0.3 倍余量
        assert -0.6 <= res["samples"][:, 0].mean() <= 0.0, (
            f"截断均值越带: {res['samples'][:, 0].mean()}")
        # 硬边界下轨迹越界态经 −inf 走发散处置（发散计数>0 是机制
        # 证据，不是缺陷——链仍在支撑内即本钉主判据）
        assert res["n_divergent"] > 0


class TestNegative:
    """负例：非法配置/非法初值显式报错不静默（预声明契约）。"""

    def test_bad_chain_config(self):
        with pytest.raises(ValueError, match="链长非法"):
            nuts_sample(_std_normal_5d, np.zeros(5), seed=1, n_samples=0)
        with pytest.raises(ValueError, match="step_size"):
            nuts_sample(_std_normal_5d, np.zeros(5), seed=1, n_samples=4,
                        step_size=0.0)
        with pytest.raises(ValueError, match="max_tree_depth"):
            nuts_sample(_std_normal_5d, np.zeros(5), seed=1, n_samples=4,
                        max_tree_depth=13)

    def test_bad_theta0(self):
        with pytest.raises(ValueError, match="非有限"):
            nuts_sample(_std_normal_5d,
                        np.array([0.0, np.nan, 0.0, 0.0, 0.0]),
                        seed=1, n_samples=4)

    def test_initial_logp_out_of_support(self):
        def lg_outside(th: np.ndarray) -> tuple[float, np.ndarray]:
            if th[0] > 0.5:
                return -np.inf, np.zeros_like(th)
            return float(-0.5 * th @ th), -th

        with pytest.raises(ValueError, match="支撑内"):
            nuts_sample(lg_outside, np.array([1.0, 0.0]), seed=1,
                        n_samples=4)


class TestEffectiveSampleSize:
    """ESS 裁判面自锚（#300 家法：裁判先过已知形态）。"""

    def test_iid_chain_near_n(self):
        for seed in (1, 2, 3):
            x = np.random.default_rng(seed).standard_normal(2000)
            ess = effective_sample_size(x)
            assert ess >= 0.8 * 2000, f"iid ESS 过低: {ess}"

    def test_ar1_strongly_correlated_below_n(self):
        rng = np.random.default_rng(5)
        n, rho = 4000, 0.95
        x = np.empty(n)
        x[0] = rng.standard_normal()
        for i in range(1, n):
            x[i] = rho * x[i - 1] + np.sqrt(1 - rho ** 2) * \
                rng.standard_normal()
        ess = effective_sample_size(x)
        # 理论 τ≈(1+ρ)/(1−ρ)=39 → ESS≈103；写死带留倍余量
        assert ess < 0.15 * n, f"AR(1) ESS 偏高: {ess}"
        assert ess > 0, ess

    def test_short_chain_rejected(self):
        with pytest.raises(ValueError, match="链长"):
            effective_sample_size(np.array([1.0, 2.0, 3.0]))

    def test_constant_chain_nan(self):
        assert np.isnan(effective_sample_size(np.ones(100)))
