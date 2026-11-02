"""DP-15 C1 变换域注册表与逐域 LOO-LML 选择器单测（合成回收，快路径）。

判据（预声明 runs/df6_dp15c1/criteria.md §a）：逐域 forward/inverse 回路、
dB 钳制、diff 缺频率轴如实排除、平局保序、已知域选择（#370 深谷形态）、
选择确定性。全组 <10s（小样本 + GP 重启数压低）。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.metric_transform import (
    DB_FLOOR_DB,
    DB_FLOOR_LINEAR,
    DEFAULT_TIE_EPSILON,
    forward_domain,
    inverse_domain,
    loo_loglik,
    select_metric_domain,
)


def _gamma_curves(n: int = 24, m: int = 21) -> tuple[np.ndarray, np.ndarray]:
    """合成复数 Γ 曲线（带内谐振谷形态，相位线性）。"""
    freqs = np.linspace(2.4, 2.6, m)
    w = np.linspace(0.5, 2.0, n)
    depth = 0.55 - 0.25 * np.cos(2.0 * np.pi * (w - 0.5) / 1.5)
    f0 = 2.45 + 0.1 * (w - 1.0)
    shape = 1.0 - depth[:, None] * np.exp(
        -((freqs[None, :] - f0[:, None]) / 0.015) ** 2)
    gamma = shape * 0.35 * np.exp(1j * 2.0 * np.pi * 8.0 * freqs[None, :])
    return gamma, freqs


class TestDomainRegistryRoundTrip:
    """判据 a-1：已知域合成数据逐域恢复。"""

    def test_db_round_trip_exact_in_clamp_domain(self):
        mag = np.array([0.5, 0.05, 1e-3, DB_FLOOR_LINEAR, 0.9])
        y = forward_domain("dB", mag)
        recovered = inverse_domain("dB", y)
        assert np.allclose(recovered, mag, rtol=1e-12, atol=0)

    def test_gamma_linear_round_trip_identity(self):
        mag = np.array([0.5, 0.05, 1e-6, 0.0, 0.9])
        y = forward_domain("gamma_linear", mag)
        assert np.array_equal(y, mag)
        assert np.array_equal(inverse_domain("gamma_linear", y), mag)

    def test_re_im_round_trip_exact_complex(self):
        z = np.array([0.5 + 0.1j, -0.2 + 0.05j, 0.0 - 0.01j])
        y = forward_domain("re_im", z)
        assert y.shape == (3, 2)
        recovered = inverse_domain("re_im", y)
        assert np.array_equal(recovered, z)

    def test_diff_inverse_recovers_magnitude_up_to_constant(self):
        # 纯实指数族 Γ=A·e^{bf}：|dΓ/df| = b·|Γ|，inverse（exp+累积
        # 梯形积分）恢复 |Γ| 至多差一个加性常数 −A（精确至差分/梯形误差）
        f = np.linspace(0.0, 0.2, 201)
        a_coef, b_coef = 0.2, 3.0
        gamma = a_coef * np.exp(b_coef * f)[None, :]
        y = forward_domain("diff", gamma, f)
        recovered = inverse_domain("diff", y, f)[0]
        analytic = a_coef * np.exp(b_coef * f)
        delta = recovered - analytic
        assert float(np.max(np.abs(delta - delta.mean()))) < 1e-4

    def test_db_forward_clamps_at_floor(self):
        """判据 a-2：dB 域下限钳 −120 dB 防 inf。"""
        y = forward_domain("dB", np.array([0.0, 1e-30, DB_FLOOR_LINEAR]))
        assert np.all(y == DB_FLOOR_DB)
        assert np.all(np.isfinite(y))

    def test_diff_forward_clamps_zero_derivative(self):
        freqs = np.linspace(2.4, 2.6, 21)
        flat = np.full((1, 21), 0.05)
        y = forward_domain("diff", flat, freqs)
        assert np.all(np.isfinite(y))  # 零导数钳地板，无 −inf


class TestCandidateDomains:
    """判据 a-3：diff 缺频率轴如实排除（不报错、不静默选中）。"""

    def test_diff_excluded_without_freq_axis(self):
        from rfauto.core.metric_transform import available_domains

        available, excluded = available_domains((10,), None, False)
        assert "diff" not in available
        assert excluded.get("diff")
        assert available == ["dB", "gamma_linear"]

    def test_diff_available_with_curve_and_freqs(self):
        from rfauto.core.metric_transform import available_domains

        available, _excluded = available_domains((10, 21),
                                                 np.linspace(2.4, 2.6, 21),
                                                 True)
        assert "diff" in available and "re_im" in available

    def test_re_im_excluded_without_complex(self):
        from rfauto.core.metric_transform import available_domains

        _available, excluded = available_domains((10, 21),
                                                 np.linspace(2.4, 2.6, 21),
                                                 False)
        assert excluded.get("re_im")

    def test_select_metric_domain_1d_excludes_diff_and_re_im(self):
        rng = np.random.default_rng(7)
        X = rng.uniform(0.5, 2.0, (12, 1))
        y_db = -20.0 - 5.0 * X[:, 0] + 0.1 * rng.standard_normal(12)
        report = select_metric_domain(X, y_db, values_domain="dB")
        assert set(report["loo_loglik"]) == {"dB", "gamma_linear"}
        assert "diff" in report["excluded"] and "re_im" in report["excluded"]


class TestSelection:
    """判据 a-4/a-5：平局保序 + 已知域选择（#370 深谷形态）。"""

    def _moving_resonance_curves(
        self, n: int = 12, m: int = 4,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """#370 合成形态：谐振频率随 w 移动的深谷曲线族。

        dB 表示下每个 (w, f) 单元在谐振扫过该频点时是 tens-of-dB 悬崖；
        线性 |Γ| 同一物理光滑可预测——LML 差异的真实机制（m2 实证同源）。
        """
        w = np.linspace(0.5, 2.0, n)
        freqs = np.linspace(2.4, 2.6, m)
        f0 = 2.44 + 0.12 * (w - 0.5) / 1.5
        depth = 0.93 + 0.03 * np.cos(3.0 * w)
        base = 0.30 + 0.06 * np.cos(2.0 * np.pi * (w - 0.5) / 1.5)
        shape = 1.0 - depth[:, None] * np.exp(
            -((freqs[None, :] - f0[:, None]) / 0.006) ** 2)
        mag = np.maximum(base[:, None] * shape, DB_FLOOR_LINEAR)
        return w[:, None], mag, freqs

    def test_deep_valley_selects_gamma_linear_with_big_margin(self):
        X, mag, freqs = self._moving_resonance_curves()
        report = select_metric_domain(X, mag, freqs=freqs,
                                      values_domain="gamma_linear",
                                      n_restarts=0)
        assert report["selected"] == "gamma_linear"
        assert report["delta_lml_vs_db"] is not None
        # m2 判据同款显著性：ΔLML ≥ 5 nats 相对 dB
        assert report["delta_lml_vs_db"] >= 5.0
        assert not report["tie_broken_by_priority"]

    def test_tie_broken_by_priority_keeps_db(self):
        """ΔLML<ε 平局按优先序取先（保向后兼容：现缺省 dB）。"""
        X, mag, freqs = self._moving_resonance_curves()
        report = select_metric_domain(X, mag, freqs=freqs,
                                      values_domain="gamma_linear",
                                      epsilon=1e12, n_restarts=0)
        assert report["selected"] == "dB"
        assert report["tie_broken_by_priority"] is True
        # ε 内平局机制真实生效：所选域 LML 与最优域差 < ε
        best = max(report["loo_loglik"].values())
        assert best - report["selected_lml"] < 1e12

    def test_selection_is_deterministic(self):
        X, mag, freqs = self._moving_resonance_curves(n=8, m=4)
        r1 = select_metric_domain(X, mag, freqs=freqs,
                                  values_domain="gamma_linear",
                                  n_restarts=0)
        r2 = select_metric_domain(X, mag, freqs=freqs,
                                  values_domain="gamma_linear",
                                  n_restarts=0)
        assert r1["loo_loglik"] == r2["loo_loglik"]
        assert r1["selected"] == r2["selected"]

    def test_loo_loglik_prefers_perfect_function_over_noise(self):
        rng = np.random.default_rng(42)
        X = rng.uniform(0.0, 1.0, (12, 1))
        clean = 3.0 * X[:, 0]
        noisy = clean + 2.0 * rng.standard_normal(12)
        assert loo_loglik(X, clean, n_restarts=0) > loo_loglik(X, noisy,
                                                               n_restarts=0)

    def test_complex_curves_all_four_domains(self):
        """复数曲线 + 频率轴 → 四域全参评（re_im 双列、diff 沿频率轴）。"""
        gamma, freqs = _gamma_curves(n=8, m=5)
        X = np.linspace(0.5, 2.0, 8)[:, None]
        report = select_metric_domain(
            X, np.abs(gamma), freqs=freqs, complex_values=gamma,
            values_domain="gamma_linear", n_restarts=0)
        assert set(report["loo_loglik"]) == {"dB", "gamma_linear", "re_im",
                                             "diff"}
        assert report["excluded"] == {}
        assert report["selected"] in report["loo_loglik"]

    def test_meta_contract_keys(self):
        X, mag, freqs = self._moving_resonance_curves(n=8, m=4)
        report = select_metric_domain(X, mag, freqs=freqs,
                                      values_domain="gamma_linear",
                                      n_restarts=0)
        for key in ("selected", "selected_lml", "loo_loglik", "excluded",
                    "delta_lml_vs_db", "tie_broken_by_priority", "epsilon",
                    "n_samples", "values_domain", "priority", "gp"):
            assert key in report
        assert report["gp"] == {"n_restarts": 0, "random_state": 0}
        assert report["priority"] == ["dB", "gamma_linear", "re_im", "diff"]
        assert report["epsilon"] == pytest.approx(DEFAULT_TIE_EPSILON)


class TestExplicitStatisticExemption:
    """判据 a-6：显式统计量指标名豁免（与 metric_key_candidates 同口径）。"""

    def test_is_explicit_statistic_name_matches_evaluator_rule(self):
        from rfauto.core.metric_transform import is_explicit_statistic_name
        from rfauto.core.objectives import MetricOp, SpecEvaluator

        # 同口径证据：显式统计量名在 metric_key_candidates 里直接命中
        # 变体（绕过 op 猜测）——豁免判据与该规则一致
        for name in ("s11_db_min", "s11_db_max", "iso_s23_db_min"):
            assert is_explicit_statistic_name(name)
        for name in ("s11_db", "s21_db", "cost", "", None):
            assert not is_explicit_statistic_name(name)
        assert SpecEvaluator.metric_key_candidates(
            "s11_db_min", MetricOp.MAX_BELOW)[0] == "s11_db_min_in_band"
