"""公差/良率分析（P6）—— Monte Carlo 模拟。

分析参数公差对性能的影响，估算良率。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ToleranceAnalyzer:
    """公差/良率分析器。

    用 Monte Carlo 方法分析参数公差对性能的影响。
    """

    def __init__(self, n_samples: int = 1000, seed: int = 42) -> None:
        """
        Args:
            n_samples: Monte Carlo 采样数
            seed: 随机种子
        """
        self.n_samples = n_samples
        self.seed = seed
        # 局部 Generator：避免 np.random.seed() 污染进程级全局随机态
        self._rng = np.random.default_rng(seed)

    def analyze(
        self,
        nominal_params: dict[str, float],
        tolerances: dict[str, float],
        objective_fn: Callable[[dict[str, float]], dict[str, float]],
        specs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """公差分析。

        Args:
            nominal_params: 标称参数值
            tolerances: 参数公差（如 {"arm_len_mm": 0.1} 表示 ±0.1mm）
            objective_fn: 目标函数，输入参数字典，返回指标字典
            specs: 性能规格（如 {"s11_db": {"max": -15}}）

        Returns:
            dict with keys: yield_rate, n_pass, n_fail, stats, worst_case
        """
        # 生成 Monte Carlo 样本（使用局部 Generator，不污染全局随机态）
        samples = self._generate_samples(nominal_params, tolerances)

        # 评估每个样本
        results = []
        pass_count = 0
        fail_count = 0

        for i, sample in enumerate(samples):
            try:
                metrics = objective_fn(sample)
                meets_spec = self._check_specs(metrics, specs)

                results.append({
                    "params": sample,
                    "metrics": metrics,
                    "meets_spec": meets_spec,
                })

                if meets_spec:
                    pass_count += 1
                else:
                    fail_count += 1

            except Exception as e:
                logger.warning("样本 %d 评估失败: %s", i, e)
                fail_count += 1

        # 计算统计信息
        yield_rate = pass_count / (pass_count + fail_count) if (pass_count + fail_count) > 0 else 0

        stats = self._compute_stats(results, specs)
        worst_case = self._find_worst_case(results, specs)

        logger.info(
            "Monte Carlo 分析完成: %d 样本, 良率 %.1f%%",
            self.n_samples, yield_rate * 100,
        )

        return {
            "ok": True,
            "yield_rate": yield_rate,
            "n_pass": pass_count,
            "n_fail": fail_count,
            "n_samples": self.n_samples,
            "stats": stats,
            "worst_case": worst_case,
        }

    def _generate_samples(
        self,
        nominal: dict[str, float],
        tolerances: dict[str, float],
    ) -> list[dict[str, float]]:
        """生成 Monte Carlo 样本。"""
        samples = []
        param_names = list(nominal.keys())

        for _ in range(self.n_samples):
            sample = {}
            for name in param_names:
                nom = nominal[name]
                tol = tolerances.get(name, 0)
                # 正态分布采样，3σ = 公差
                sigma = tol / 3
                value = self._rng.normal(nom, sigma)
                sample[name] = float(value)
            samples.append(sample)

        return samples

    def _check_specs(
        self,
        metrics: dict[str, float],
        specs: dict[str, dict[str, Any]],
    ) -> bool:
        """检查指标是否满足规格。"""
        for metric_name, spec in specs.items():
            value = metrics.get(metric_name)
            if value is None:
                continue

            if "max" in spec and value > spec["max"]:
                return False
            if "min" in spec and value < spec["min"]:
                return False

        return True

    def _compute_stats(
        self,
        results: list[dict[str, Any]],
        specs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """计算统计信息。"""
        stats = {}

        for metric_name in specs:
            values = [r["metrics"].get(metric_name) for r in results if r["metrics"].get(metric_name) is not None]
            if values:
                stats[metric_name] = {
                    "mean": float(np.mean(values)),
                    "std": float(np.std(values)),
                    "min": float(np.min(values)),
                    "max": float(np.max(values)),
                    "median": float(np.median(values)),
                }

        return stats

    def _find_worst_case(
        self,
        results: list[dict[str, Any]],
        specs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """找到最差情况（违规裕量最大的失败样本）。"""
        worst = None
        worst_margin = float("-inf")

        for r in results:
            if not r["meets_spec"]:
                # 计算与规格的差距（越大越差）
                margin = 0
                for metric_name, spec in specs.items():
                    value = r["metrics"].get(metric_name)
                    if value is None:
                        continue
                    if "max" in spec:
                        margin = max(margin, value - spec["max"])
                    if "min" in spec:
                        margin = max(margin, spec["min"] - value)

                if margin > worst_margin:
                    worst_margin = margin
                    worst = r

        return worst
