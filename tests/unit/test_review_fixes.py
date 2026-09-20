"""回归测试：已修复缺陷的防回退钉子。

每条测试对应一个已修复的确定性缺陷，防止修复回退：
- BANDWIDTH 操作符静默失效（objectives.py 无分支）
- ToleranceAnalyzer worst_case 反逻辑（选了违规最小的样本）
- ToleranceAnalyzer 污染全局随机态
- optimizer 全部 trial 剪枝时 best_trial 抛 ValueError
- hfss_ads_link PEP 701 语法（3.10/3.11 SyntaxError）
"""

from __future__ import annotations

import numpy as np
import pytest


class TestBandwidthObjective:
    """BANDWIDTH 操作符必须在 evaluate_objectives 中生效。"""

    def _objectives(self):
        from rfauto.core.objectives import MetricOp, Objective
        return [Objective(
            metric="bw_ghz_s11_lt_-10",
            band=[2.0, 3.0],
            op=MetricOp.BANDWIDTH,
            value=0.2,
            weight=2.0,
        )]

    def test_bandwidth_shortfall_penalized(self):
        from rfauto.core.objectives import SpecEvaluator
        # 实测带宽 0.1 GHz，要求 0.2 GHz → 惩罚 2.0 * (0.2-0.1) = 0.2
        metrics = {"bw_ghz_s11_lt_-10": 0.1}
        cost = SpecEvaluator.evaluate_objectives(metrics, self._objectives())
        assert cost == pytest.approx(0.2)

    def test_bandwidth_met_zero_cost(self):
        from rfauto.core.objectives import SpecEvaluator
        metrics = {"bw_ghz_s11_lt_-10": 0.3}
        cost = SpecEvaluator.evaluate_objectives(metrics, self._objectives())
        assert cost == pytest.approx(0.0)


class TestToleranceWorstCase:
    """worst_case 必须是违规裕量最大的失败样本。"""

    def test_worst_case_is_max_violation(self):
        from rfauto.optimization.tolerance import ToleranceAnalyzer
        analyzer = ToleranceAnalyzer(n_samples=200, seed=7)
        # x+N(0, 0.2)：spec max=4.0，大量样本会失败
        nominal = {"x": 3.8}
        tolerances = {"x": 0.6}
        specs = {"x": {"max": 4.0}}

        result = analyzer.analyze(nominal, tolerances, lambda p: {"x": p["x"]}, specs)
        assert result["n_fail"] > 0, "测试前提：必须有失败样本"

        worst = result["worst_case"]
        assert worst is not None
        worst_margin = worst["metrics"]["x"] - specs["x"]["max"]
        # 用同种子重放确定性采样，复核 worst_case 确实取了违规最大的样本
        analyzer2 = ToleranceAnalyzer(n_samples=200, seed=7)
        samples = analyzer2._generate_samples(nominal, tolerances)
        max_possible = max(s["x"] for s in samples) - specs["x"]["max"]
        assert worst_margin == pytest.approx(max_possible, abs=1e-6), (
            "worst_case 应是违规最大的样本"
        )

    def test_no_global_seed_pollution(self):
        """ToleranceAnalyzer 不得修改 np.random 全局状态。"""
        from rfauto.optimization.tolerance import ToleranceAnalyzer
        state_before = np.random.get_state()[1].copy()

        analyzer = ToleranceAnalyzer(n_samples=20, seed=1)
        analyzer.analyze(
            {"x": 1.0}, {"x": 0.3}, lambda p: {"x": p["x"]}, {"x": {"max": 2.0}},
        )

        state_after = np.random.get_state()[1]
        assert np.array_equal(state_before, state_after), "全局随机态被污染"


class TestOptimizerAllPruned:
    """全部 trial 被剪枝时 run_optimization 不得崩溃（best_trial ValueError）。"""

    def test_all_pruned_returns_graceful(self, tmp_path, monkeypatch):
        import yaml

        from rfauto.optimization import optimizer as opt_mod

        monkeypatch.chdir(tmp_path)
        recipe = {
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
            "optimization": {"params": {"arm_len_mm": {"low": 15.0, "high": 25.0}}},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
        }
        recipe_path = tmp_path / "recipe.yaml"
        recipe_path.write_text(yaml.safe_dump(recipe), encoding="utf-8")

        # 注入故障：每个 trial 的 solve 都抛异常 → 全部剪枝
        from rfauto.adapters.fake_adapter import FaultInjection
        original_create = opt_mod._create_adapter

        def failing_create(adapter_name, adapter_kwargs, recipe_data):
            adapter, ver = original_create(adapter_name, adapter_kwargs, recipe_data)
            adapter.fault = FaultInjection(fail_solve=True)
            return adapter, ver

        monkeypatch.setattr(opt_mod, "_create_adapter", failing_create)

        result = opt_mod.run_optimization(
            recipe_path, adapter_name="fake", max_trials=3,
            study_name="all_pruned_test",
        )
        assert result["ok"] is True
        assert result["trials_completed"] == 0
        assert result["best_cost"] is None
        assert result["best_params"] == {}


class TestPep701Syntax:
    """hfss_ads_link 不得使用 PEP 701 语法（3.10/3.11 下 SyntaxError）。"""

    def test_module_parses_without_pep701(self):
        import pathlib
        source = pathlib.Path(
            "src/rfauto/linkage/hfss_ads_link.py"
        ).read_text(encoding="utf-8-sig")
        # 3.12 的 parser 接受 PEP 701，无法直接判否；退而检查修复目标行
        # 不再出现 f'...{x['k']}...' 同引号嵌套。
        for line in source.splitlines():
            for q in ("'", '"'):
                inner = f"f{q}"
                if inner in line:
                    start = line.index(inner) + 2
                    # 提取该 f-string 字面量（到行尾或下一个未转义引号）
                    body = line[start:]
                    if body.startswith(q):
                        # f-string 体内同一引号出现在 { } 之间即为 PEP 701
                        depth = 0
                        for ch in body[1:]:
                            if ch == "{":
                                depth += 1
                            elif ch == "}":
                                depth -= 1
                            elif ch == q and depth > 0:
                                pytest.fail(f"PEP 701 syntax found: {line.strip()}")
                                break
