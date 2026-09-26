"""E3 代理模型单元测试。"""

from __future__ import annotations

import pytest

from rfauto.optimization.surrogate_analysis import (
    SurrogateAnalysisResult,
    analyze_run_surrogate,
)


def _make_trials(n: int = 10) -> list[dict]:
    """创建测试用 trial 数据。"""
    import numpy as np
    rng = np.random.default_rng(42)
    trials = []
    for _i in range(n):
        params = {
            "arm_len": float(rng.uniform(17, 21)),
            "series_w": float(rng.uniform(1.5, 2.5)),
        }
        cost = (params["arm_len"] - 18.0) ** 2 + (params["series_w"] - 1.8) ** 2
        trials.append({"params": params, "cost": cost})
    return trials


class TestSurrogateAnalysis:
    def test_basic_analysis(self):
        trials = _make_trials(10)
        result = analyze_run_surrogate("test_001", trials)
        assert isinstance(result, SurrogateAnalysisResult)
        assert result.n_samples == 10
        assert result.n_params == 2
        assert result.best_cost >= 0

    def test_too_few_trials(self):
        with pytest.raises(ValueError, match="至少需要 3 个"):
            analyze_run_surrogate("test", [{"params": {"a": 1}, "cost": 1}])

    def test_to_dict(self):
        trials = _make_trials(5)
        result = analyze_run_surrogate("test_001", trials)
        d = result.to_dict()
        assert "run_id" in d
        assert "best_params" in d

    def test_param_importance(self):
        trials = _make_trials(20)
        result = analyze_run_surrogate("test_001", trials)
        assert len(result.param_importance) == 2
        assert abs(sum(result.param_importance.values()) - 1.0) < 0.01


class TestQualityMetrics:
    """B-33：代理质量内核（ρ/残差/RMS）——与独立实现对照，非占位。"""

    def test_kernel_matches_independent_formula(self):
        import numpy as np

        from rfauto.optimization.surrogate_analysis import surrogate_fit_quality

        y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y_pred = np.array([1.5, 2.0, 2.0, 4.5, 3.0])
        q = surrogate_fit_quality(y_true, y_pred)
        resid = y_true - y_pred
        assert q["available"] is True
        assert q["n"] == 5
        assert q["rms_error"] == pytest.approx(float(np.sqrt(np.mean(resid ** 2))))
        assert q["mae"] == pytest.approx(float(np.mean(np.abs(resid))))
        assert q["max_abs_residual"] == pytest.approx(float(np.max(np.abs(resid))))
        assert q["r2"] == pytest.approx(
            1.0 - float(np.sum(resid ** 2)) / float(np.sum((y_true - y_true.mean()) ** 2)))
        # Spearman 独立对照（scipy 随 sklearn 安装；缺失则跳过）
        spearmanr = pytest.importorskip("scipy.stats").spearmanr
        ref = spearmanr(y_true, y_pred)
        rho = getattr(ref, "statistic", None)
        if rho is None:  # pragma: no cover - 旧版 scipy 字段名
            rho = ref.correlation
        assert q["spearman_rho"] == pytest.approx(float(rho))

    def test_constant_series_has_no_rank_correlation(self):
        from rfauto.optimization.surrogate_analysis import surrogate_fit_quality

        q = surrogate_fit_quality([1.0, 1.0, 1.0], [1.0, 2.0, 3.0])
        assert q["available"] is True
        assert q["spearman_rho"] is None
        assert q["r2"] is None

    def test_analyze_reports_cross_validated_quality(self):
        trials = _make_trials(12)
        result = analyze_run_surrogate("test_q", trials)
        q = result.quality
        assert q["available"] is True
        assert q["kind"] == "cross_validation_out_of_fold"
        assert q["n"] == 12
        assert q["cv_folds"] >= 2
        assert q["rms_error"] > 0
        assert -1.0 <= q["spearman_rho"] <= 1.0
        assert abs(sum(result.param_importance.values()) - 1.0) < 1e-6
        assert result.to_dict()["quality"]["rms_error"] == pytest.approx(
            q["rms_error"], abs=1e-6)

    def test_analyze_quality_reacts_to_data(self):
        # 非占位证据：噪声数据 → 交叉验证误差显著大于平滑数据
        smooth = [{"params": {"a": float(i), "b": float(i % 3)},
                   "cost": float(i)} for i in range(10)]
        noisy = [{"params": {"a": float(i), "b": float(i % 3)},
                  "cost": float(i) + (5.0 if i % 2 else -5.0)} for i in range(10)]
        q_smooth = analyze_run_surrogate("smooth", smooth).quality
        q_noisy = analyze_run_surrogate("noisy", noisy).quality
        assert q_smooth["kind"] == "cross_validation_out_of_fold"
        assert q_noisy["rms_error"] > q_smooth["rms_error"]


class TestMetricDomainMeta:
    """DP-15 C1：fit meta 的 metric_domain / domain_selection 接线。

    判据（runs/df6_dp15c1/criteria.md）：缺省路径行为零变化（只加键）；
    auto_domain=True 才跑逐域 LOO-LML；显式统计量指标名豁免。
    """

    def test_default_path_unchanged(self):
        trials = _make_trials(8)
        result = analyze_run_surrogate("test_dom", trials)
        assert result.metric_domain == "dB"
        assert result.domain_selection is None
        d = result.to_dict()
        assert d["metric_domain"] == "dB"
        assert d["domain_selection"] is None
        # 既有键不受影响
        for key in ("run_id", "n_samples", "best_params", "best_cost",
                    "param_importance", "prediction_error", "quality"):
            assert key in d

    def test_auto_domain_runs_selection_on_cost(self):
        trials = _make_trials(12)
        result = analyze_run_surrogate("test_auto", trials, auto_domain=True)
        sel = result.domain_selection
        assert sel is not None
        assert "dB" in sel["loo_loglik"]
        assert "gamma_linear" in sel["loo_loglik"]
        # 标量 cost（无频率轴/无相位）：diff 与 re_im 如实排除
        assert "diff" in sel["excluded"] and "re_im" in sel["excluded"]
        assert sel["selected"] in ("dB", "gamma_linear")
        assert result.metric_domain == sel["selected"]

    def test_explicit_statistic_metric_name_is_exempt(self):
        trials = _make_trials(10)
        result = analyze_run_surrogate(
            "test_exempt", trials, metric_name="s11_db_min", auto_domain=True)
        # 显式统计量指标名不被自动选择覆盖：域钉在声明来源域
        assert result.metric_domain == "dB"
        assert result.domain_selection is not None
        assert result.domain_selection["loo_loglik"] is None
        assert "豁免" in result.domain_selection["exempt"]
        # to_dict 透传
        d = result.to_dict()
        assert d["metric_domain"] == "dB"
        assert d["domain_selection"]["exempt"]

    def test_auto_domain_selection_failure_is_best_effort(self):
        # 目标全为常数 → var=0 的退化输入仍要出报告，不炸分析主路径（#105）
        trials = [{"params": {"a": float(i)}, "cost": 1.0} for i in range(6)]
        result = analyze_run_surrogate("test_deg", trials, auto_domain=True)
        assert result.domain_selection is not None
        assert result.metric_domain in ("dB", "gamma_linear")

