"""OP-10 convergence_service 单测：n_duplicate_evals / improvement_rate / 并行坐标图。

optuna 5.0.0 可视化 API venv 实测（plot_parallel_coordinate 返回 plotly
go.Figure，本机 plotly 7.1.0 在装，零网络）；study 全部 in-memory，
零文件零真机。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import optuna
import pytest

from rfauto.service.convergence_service import (
    convergence_report,
    duplicate_evals,
    improvement_rate,
    parallel_coordinate_figure,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


def _study_with_values(values: list[float], *, dup_at: list[dict] | None = None):
    """in-memory study，按序 tell 指定目标值；dup_at 追加 enqueue 的重复点。"""
    study = optuna.create_study()
    for v in values:
        t = study.ask()
        t.suggest_float("x", 0.0, 1.0)
        study.tell(t, v)
    for params in dup_at or []:
        study.enqueue_trial(params)
        t = study.ask()
        t.suggest_float("x", 0.0, 1.0)
        study.tell(t, 0.123)  # 目标值任意（重复判据只看 params）
    return study


# ---------------------------------------------------------------------------
# duplicate_evals
# ---------------------------------------------------------------------------

def test_duplicate_evals_counts_enqueued_duplicates():
    # enqueue 固定 x=0.5 三次：两个重复评估（首现+2 重复，组大小 3）；
    # 前 2 个随机 trial 的 x 与 0.5 不重合（suggest_float 随机）。
    study = _study_with_values([0.5, 0.3],
                               dup_at=[{"x": 0.5}, {"x": 0.5}, {"x": 0.5}])
    rep = duplicate_evals(study)
    assert rep["ok"] is True
    assert rep["n_evals"] == 5
    assert rep["n_duplicate_evals"] == 2
    assert rep["duplicate_rate"] == pytest.approx(0.4)
    assert len(rep["groups"]) == 1
    assert len(rep["groups"][0]) == 3  # 首现 + 2 个重复


def test_duplicate_evals_no_duplicates_clean_study():
    study = _study_with_values([0.5, 0.3, 0.2])
    rep = duplicate_evals(study)
    assert rep["n_duplicate_evals"] == 0
    assert rep["groups"] == []


def test_duplicate_evals_accepts_plain_records():
    recs = [
        {"number": 0, "params": {"x": 1.0, "y": 2.0}, "value": 10.0},
        {"number": 1, "params": {"y": 2.0, "x": 1.0}, "value": 9.0},  # 键序无关
        {"number": 2, "params": {"x": 1.0, "y": 3.0}, "value": 8.0},
    ]
    rep = duplicate_evals(recs)
    assert rep["n_evals"] == 3
    assert rep["n_duplicate_evals"] == 1


def test_duplicate_evals_empty_is_honest_reject():
    study = optuna.create_study()
    rep = duplicate_evals(study)
    assert rep["ok"] is False
    assert "拒绝空跑" in rep["errors"][0]


def test_duplicate_evals_rejects_non_mapping_records():
    with pytest.raises(TypeError, match="不是映射"):
        duplicate_evals(["not-a-mapping"])


# ---------------------------------------------------------------------------
# improvement_rate
# ---------------------------------------------------------------------------

def test_improvement_rate_known_series():
    study = _study_with_values([3.0, 2.0, 2.0, 1.0])
    rep = improvement_rate(study)
    assert rep["ok"] is True
    assert rep["n_evals"] == 4
    assert rep["improvement_events"] == 2  # 3→2 与 2→1
    assert rep["improvement_rate"] == 0.5
    assert rep["best_first"] == 3.0
    assert rep["best_last"] == 1.0
    assert rep["relative_improvement"] == pytest.approx(2.0 / 3.0)
    assert rep["best_so_far"] == [3.0, 2.0, 2.0, 1.0]


def test_improvement_rate_monotone_worse_series_zero_events():
    study = _study_with_values([1.0, 2.0, 3.0])
    rep = improvement_rate(study)
    assert rep["improvement_events"] == 0
    assert rep["improvement_rate"] == 0.0
    assert rep["relative_improvement"] == pytest.approx(0.0)


def test_improvement_rate_zero_baseline_gives_none_not_inf():
    """best_first=0 时相对改进如实 None（不除零不伪造，#122）。"""
    study = _study_with_values([0.0, -1.0])
    rep = improvement_rate(study)
    assert rep["relative_improvement"] is None
    assert rep["improvement_events"] == 1


def test_improvement_rate_skips_nonfinite_values():
    recs = [
        {"number": 0, "params": {"x": 1.0}, "value": 5.0},
        {"number": 1, "params": {"x": 2.0}, "value": None},        # 缺值跳过
        {"number": 2, "params": {"x": 3.0}, "value": float("nan")},  # NaN 跳过
        {"number": 3, "params": {"x": 4.0}, "value": 4.0},
    ]
    rep = improvement_rate(recs)
    assert rep["n_evals"] == 2
    assert rep["improvement_events"] == 1
    assert math.isfinite(rep["best_last"])


def test_improvement_rate_empty_rejects():
    rep = improvement_rate(optuna.create_study())
    assert rep["ok"] is False


# ---------------------------------------------------------------------------
# 聚合报告与 optuna 5.0 并行坐标图
# ---------------------------------------------------------------------------

def test_convergence_report_aggregates_both():
    study = _study_with_values([0.5, 0.3], dup_at=[{"x": 0.5}, {"x": 0.5}])
    rep = convergence_report(study)
    assert rep["ok"] is True
    assert rep["duplicates"]["n_duplicate_evals"] == 1
    # 目标值 0.5→0.3→0.123→0.123 严格递减段：基线外 2 次改进事件
    assert rep["improvement"]["improvement_events"] == 2
    assert rep["errors"] == []


def test_parallel_coordinate_figure_real_optuna5_call():
    """optuna 5.0 plot_parallel_coordinate 实调：返回 plotly Figure 且带数据。"""
    study = _study_with_values([0.9, 0.4, 0.1])
    fig = parallel_coordinate_figure(study, params=["x"])
    assert hasattr(fig, "data")  # plotly go.Figure
    assert len(fig.data) >= 1  # 并行坐标轨迹已构建（零网络，纯数据对象）
