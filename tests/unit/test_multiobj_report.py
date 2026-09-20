"""NSGA-II 多目标优化 + Smith 圆图测试（P5）。"""

from __future__ import annotations

import numpy as np


class TestMultiObjBackend:
    """NSGA-II 多目标优化测试。"""

    def test_nsga2_basic(self):
        """基本 NSGA-II 优化测试。"""
        from rfauto.optimization.multiobj_backend import MultiObjBackend

        # 简单双目标问题：minimize (x^2, (x-1)^2)
        backend = MultiObjBackend(
            n_objectives=2,
            n_variables=1,
            bounds=(np.array([0.0]), np.array([2.0])),
        )

        def objective(x):
            return np.array([x[0] ** 2, (x[0] - 1) ** 2])

        result = backend.optimize(objective, n_gen=20, pop_size=20, seed=42)

        assert result["ok"] is True
        assert result["n_pareto"] > 0
        assert len(result["pareto_front"]) == result["n_pareto"]
        assert len(result["pareto_variables"]) == result["n_pareto"]

    def test_extract_pareto_metrics(self):
        """Pareto 前沿指标提取测试。"""
        from rfauto.optimization.multiobj_backend import MultiObjBackend

        pareto_front = [[1.0, 2.0], [1.5, 1.5], [2.0, 1.0]]
        metric_names = ["bw_ghz", "s11_db"]

        metrics = MultiObjBackend.extract_pareto_metrics(pareto_front, metric_names)

        assert len(metrics) == 3
        assert metrics[0]["bw_ghz"] == 1.0
        assert metrics[0]["s11_db"] == 2.0


class TestReportEnhancements:
    """报告增强测试（Smith 圆图 + Pareto 前沿）。"""

    def test_plot_smith_chart_import(self):
        """验证 Smith 圆图函数可导入。"""
        from rfauto.infra.report import plot_smith_chart
        assert callable(plot_smith_chart)

    def test_plot_pareto_front_import(self):
        """验证 Pareto 前沿函数可导入。"""
        from rfauto.infra.report import plot_pareto_front
        assert callable(plot_pareto_front)

    def test_plot_pareto_front(self, tmp_path):
        """Pareto 前沿绘图测试。"""
        from rfauto.infra.report import plot_pareto_front

        pareto_front = [[1.0, 2.0], [1.5, 1.5], [2.0, 1.0]]
        metric_names = ["bw_ghz", "s11_db"]

        # 创建 figs 目录
        figs_dir = tmp_path / "results" / "figs"
        figs_dir.mkdir(parents=True, exist_ok=True)

        path = plot_pareto_front(pareto_front, metric_names, figs_dir)

        assert path != ""
        assert (tmp_path / path).exists()
