"""S-2 置换检验+BCa 自助：ΔLML 置信区间化单测（合成回收，固定种子）。

判据（研究扩充 round3 §3.1 S-2）：
- 合成正态已知差回收：CI 覆盖真值 ≥19/20 种子（覆盖率钉 ≥95%）；
- 配对置换检验：同分布 p 不过度偏小（松界）、强偏移 p<0.01；
- 往返恒等：delta_point==median(lml_a−lml_b) 逐位；
- 退化：n<4/全同差/单域——如实 None/零宽，不炸；
- select_domain_with_ci：显著/并列/单域三判定 + rng 固定逐字节确定性；
- loo_loglik_per_point 与 loo_loglik 同序累加逐位相等（纯增量证明）。

覆盖率钉注：BCa 对连续正态差的真覆盖 ≈0.95，设计期标定（scipy
1.18.1 固定种子确定性，runs 探针实测四组构造均 19/20、落选种子缺
口 0.066 nats）——≥19/20 恰为规格门；固定种子+固定 scipy 版本下
本组断言逐字节确定，不随重跑漂移。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.metric_transform import (
    delta_lml_ci,
    loo_loglik,
    loo_loglik_per_point,
    select_domain_with_ci,
)

#: 覆盖率回收实验参数（设计期标定值，见模块 docstring 钉注）
_COVER_N = 80
_COVER_N_SEEDS = 20
_COVER_TRUE_DELTA = 2.5


def _paired_lml(
    seed: int,
    n: int,
    delta: float,
    sigma: float = 1.0,
    base_scale: float = 50.0,
) -> tuple[np.ndarray, np.ndarray]:
    """构造两域逐点 LML：lml_a − lml_b 的中位真值 = delta。

    base 为两域共享的逐点公共部分（LML 量纲量级），差 = delta + 对称
    正态噪声——正态对称 ⇒ 总体中位差恰为 delta。
    """
    rng = np.random.default_rng(1000 + seed)
    base = rng.normal(0.0, base_scale, size=n)
    diff = delta + rng.normal(0.0, sigma, size=n)
    return base + diff, base


class TestDeltaLmlCiRecovery:
    """判据 a：合成正态已知差回收 + 往返恒等。"""

    def test_delta_point_roundtrip_identity(self):
        """delta_point==median(lml_a−lml_b) 逐位（含负差方向语义）。"""
        for seed in (0, 7, 42):
            a, b = _paired_lml(seed, n=40, delta=-1.3, sigma=0.8)
            result = delta_lml_ci(a, b, rng_seed=seed)
            assert result["delta_point"] == float(np.median(a - b))
            assert result["delta_point"] < 0.0  # 负差如实（a 劣于 b）

    def test_coverage_recovers_known_delta(self):
        """CI 覆盖真值：20 种子重复 ≥19 覆盖（覆盖率钉 ≥95%，见钉注）。"""
        covered = 0
        for seed in range(_COVER_N_SEEDS):
            a, b = _paired_lml(seed, n=_COVER_N, delta=_COVER_TRUE_DELTA)
            result = delta_lml_ci(a, b, rng_seed=seed)
            assert result["ci_lo"] is not None and result["ci_hi"] is not None
            assert result["ci_lo"] <= result["ci_hi"]
            if result["ci_lo"] <= _COVER_TRUE_DELTA <= result["ci_hi"]:
                covered += 1
        assert covered >= 19, f"覆盖率 {covered}/20 低于规格门 ≥19/20"

    def test_statistic_mean_parameterization(self):
        """mean 统计量显式参数化：delta_point==mean(diff) 逐位。"""
        a, b = _paired_lml(3, n=30, delta=1.0)
        result = delta_lml_ci(a, b, rng_seed=3, statistic="mean")
        assert result["delta_point"] == float(np.mean(a - b))
        assert any(s == "statistic=mean" for s in result["method_notes"])


class TestDeltaLmlCiPermutation:
    """判据 b：配对置换检验 p 值行为。"""

    def test_null_p_not_excessively_small(self):
        """同分布（差对称零均值）：p>0.05 占比 ≥0.7（松界防 flaky）。"""
        above = 0
        seeds = 20
        for seed in range(seeds):
            rng = np.random.default_rng(2000 + seed)
            base = rng.normal(0.0, 30.0, size=30)
            d = rng.normal(0.0, 1.0, size=30)  # 对称 ⇒ H0 成立
            result = delta_lml_ci(base + d / 2.0, base - d / 2.0,
                                  rng_seed=seed)
            assert result["p_perm"] is not None
            if result["p_perm"] > 0.05:
                above += 1
        assert above / seeds >= 0.7, f"H0 下 p>0.05 占比仅 {above}/{seeds}"

    def test_strong_shift_p_below_0p01(self):
        """强偏移样本：p<0.01（检出力方向）。"""
        for seed in (0, 1, 2):
            a, b = _paired_lml(seed, n=30, delta=3.0, sigma=1.0)
            result = delta_lml_ci(a, b, rng_seed=seed)
            assert result["p_perm"] is not None
            assert result["p_perm"] < 0.01
            # CI 与 p 判向一致：显著时不含 0 且下界为正
            assert result["ci_lo"] > 0.0


class TestDeltaLmlCiDegenerate:
    """判据 d：退化守卫——不炸不虚构。"""

    def test_insufficient_n_returns_none_honestly(self):
        a, b = _paired_lml(0, n=3, delta=1.0)
        result = delta_lml_ci(a, b, rng_seed=0)
        assert result["n"] == 3
        assert "insufficient_n" in result["method_notes"]
        assert result["ci_lo"] is None and result["ci_hi"] is None
        assert result["p_perm"] is None  # 判缺失用 is None（p=0.0 合法）
        assert result["delta_point"] == float(np.median(a - b))

    def test_all_identical_diffs_zero_width_ci(self):
        n = 12
        a = np.arange(float(n))
        b = a - 1.5  # 逐点差恒为 1.5
        result = delta_lml_ci(a, b, rng_seed=0)
        assert "degenerate_all_identical" in result["method_notes"]
        assert result["p_perm"] == 1.0
        assert result["ci_lo"] == result["ci_hi"] == result["delta_point"]
        assert result["delta_point"] == 1.5

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="长度不一致"):
            delta_lml_ci(np.arange(5.0), np.arange(4.0))

    def test_nonfinite_raises(self):
        a = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
        b = np.zeros(5)
        with pytest.raises(ValueError, match="非有限"):
            delta_lml_ci(a, b)

    def test_unknown_statistic_raises(self):
        a, b = _paired_lml(0, n=10, delta=1.0)
        with pytest.raises(ValueError, match="未知差统计量"):
            delta_lml_ci(a, b, statistic="mode")

    def test_byte_identical_across_calls(self):
        """同输入同种子两次调用逐字节一致（rng 固定确定性）。"""
        a, b = _paired_lml(9, n=40, delta=0.8)
        r1 = delta_lml_ci(a, b, rng_seed=9)
        r2 = delta_lml_ci(a, b, rng_seed=9)
        assert r1 == r2

    def test_partial_ties_bca_nan_reported_as_none(self):
        """部分结（两点差）下 BCa 不可算（NaN，实测）——区间如实 None。"""
        a = np.array([-0.5] * 30 + [1.0] * 20)
        b = np.zeros_like(a)
        result = delta_lml_ci(a, b, rng_seed=0)
        assert "bca_degenerate_ci" in result["method_notes"]
        assert result["ci_lo"] is None and result["ci_hi"] is None
        # p 值有限仍如实返回（判缺失 is None，p=0.0 合法）
        assert result["p_perm"] is not None


class TestSelectDomainWithCi:
    """select_domain_with_ci 三判定语义 + 确定性。"""

    def test_significant_when_top_beats_all(self):
        rng = np.random.default_rng(3000)
        base = rng.normal(0.0, 40.0, size=60)
        top = base + 4.0 + rng.normal(0.0, 0.5, size=60)
        mid = base + rng.normal(0.0, 0.5, size=60)
        low = base - 0.5 + rng.normal(0.0, 0.5, size=60)
        result = select_domain_with_ci(
            {"dB": top, "gamma_linear": mid, "re_im": low}, rng_seed=1)
        assert result["selected"] == "dB"
        assert result["verdict"] == "significant"
        assert result["top_domain"] == "dB"
        assert all(v["verdict"] == "top_significant"
                   for v in result["pairwise"].values())
        assert result["method_notes"][-1] == "verdict=significant"

    def test_tied_reports_honestly_and_keeps_point_estimate_top(self):
        n = 40
        other = np.zeros(n)
        top = 0.15 + 0.5 * np.random.default_rng(4001).normal(0.0, 1.0, n)
        result = select_domain_with_ci({"dB": top, "gamma_linear": other},
                                       rng_seed=2)
        assert result["selected"] == "dB"  # 点估计最高（0.15*n 主导 sums）
        assert result["verdict"] == "tied"  # 0.15 偏移在 CI 内 ⇒ 并列如实
        assert result["pairwise"]["gamma_linear"]["verdict"] == "tied"
        assert "selection_not_ci_confirmed" in result["method_notes"]

    def test_single_domain_verdict(self):
        result = select_domain_with_ci({"dB": np.arange(10.0)}, rng_seed=0)
        assert result["verdict"] == "single_domain"
        assert result["selected"] == "dB"
        assert result["pairwise"] == {}

    def test_insufficient_n_undecidable(self):
        result = select_domain_with_ci(
            {"dB": np.arange(3.0), "gamma_linear": np.arange(3.0) + 1.0},
            rng_seed=0)
        assert result["verdict"] == "undecidable"
        assert result["selected"] == "gamma_linear"  # 点估计锚：sum 更高
        assert result["pairwise"]["dB"]["verdict"] == "undecidable"

    def test_beaten_reports_ci_contradiction_honestly(self):
        """CI 证据与点估计矛盾（多数小负+少数大正）：beaten 如实上报。

        逐点差：40 个 ≈−0.3 + 10 个 ≈+3.0 ⇒ sum=+21（top 点估计仍最高）
        但 median 差 ≈−0.27 的 CI 不含 0 且 p<alpha ⇒ other_significant。
        """
        rng = np.random.default_rng(21)
        other = np.zeros(50)
        top = np.concatenate([-0.3 + 0.05 * rng.random(40),
                              3.0 + 0.5 * rng.random(10)])
        result = select_domain_with_ci({"dB": top, "gamma_linear": other},
                                       rng_seed=5)
        assert result["selected"] == "dB"  # 点估计锚不变（sum=+21）
        assert result["verdict"] == "beaten"
        assert result["pairwise"]["gamma_linear"]["verdict"] == "other_significant"
        assert "selection_not_ci_confirmed" in result["method_notes"]

    def test_byte_identical_across_calls(self):
        rng = np.random.default_rng(5000)
        base = rng.normal(0.0, 40.0, size=50)
        domains = {
            "dB": base + 2.0 + rng.normal(0.0, 0.5, size=50),
            "gamma_linear": base + rng.normal(0.0, 0.5, size=50),
        }
        r1 = select_domain_with_ci(domains, rng_seed=7)
        r2 = select_domain_with_ci(domains, rng_seed=7)
        assert r1 == r2

    def test_unequal_lengths_raise(self):
        with pytest.raises(ValueError, match="同长"):
            select_domain_with_ci({"dB": np.arange(5.0),
                                   "gamma_linear": np.arange(6.0)})


class TestLooLoglikPerPointEquivalence:
    """逐点 producer 与 loo_loglik 同序累加逐位相等（纯增量证明）。"""

    def test_sum_equals_loo_loglik_bitwise(self):
        sklearn_gpr = pytest.importorskip("sklearn.gaussian_process")
        assert sklearn_gpr is not None  # 惰性依赖显式门（core 内部 lazy import）
        rng = np.random.default_rng(0)
        x = np.linspace(0.0, 1.0, 10)[:, None]
        y = np.sin(3.0 * x[:, 0]) + 0.05 * rng.normal(size=10)
        per_point = loo_loglik_per_point(x, y, random_state=0)
        assert per_point.shape == (10,)
        assert bool(np.all(np.isfinite(per_point)))
        total = 0.0
        for v in per_point:
            total += float(v)
        assert total == loo_loglik(x, y, random_state=0)
