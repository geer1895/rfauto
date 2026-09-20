"""WP3.2 代理寻优环单测——合成解析峰缩减率裁判（方案 §4 验收口径）。

裁判问题：耦合二次响应碗 + 正弦纹波的 s11 谷深语义合成面（非轴对齐
耦合项正是"代理优于盲搜"的来源；纹波防"代理模型类恰好=真表面"的
凑绿）。value=-47 低于谷底 -46 → cost 恒 ≥1 无零平台——随机搜索不存在
"运气命中窄平台导致参考线塌陷"的种子彩票（校准实测 @40 命中 2% 平台）。

冻结常量来自校准脚本实测（2026-09-09，六轮迭代定版）：
- 随机扫描 B_RANDOM=33、5 种子 finals=[5.26, 1.39, 2.58, 2.73, 1.45]、
  median=2.578（参考线 ref 在测试内重算，确定性）；
- 代理环 seeds {7, 2026, 42} 达 ref 真跑数 = [11, 5, 1]（median 5）。
判据：median(n_ref) ≤ B_RANDOM//3（=13，≥60% 缩减）＋逐种子 ≤17（防
单种子边界抖动的安全上限）＋环 final 全部 < ref（质量严格更优）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

# 确保 src 在 path 中（同 test_optimization 模式）
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.core.objectives import (
    MetricOp,
    Objective,
    SpecEvaluator,
)
from rfauto.optimization.sample_design import lhs_points
from rfauto.optimization.surrogate_analysis import analyze_run_surrogate
from rfauto.optimization.surrogate_loop import (
    best_so_far_trace,
    run_surrogate_loop,
    select_topk,
)

BOUNDS = {"x_mm": (0.0, 1.0), "y_mm": (0.0, 1.0)}
X_STAR, Y_STAR = 0.30, 0.62
B_RANDOM = 33
LOOP_SEEDS = (7, 2026, 42)

OBJS = [Objective(metric="s11_db_min", band=[2.3, 2.5],
                  op=MetricOp.MAX_BELOW, value=-47.0, weight=1.0)]


def bowl_metrics(params: dict[str, float]) -> dict[str, float]:
    dx = params["x_mm"] - X_STAR
    dy = params["y_mm"] - Y_STAR
    depth = -46.0 + 180.0 * dx * dx + 150.0 * dy * dy - 120.0 * dx * dy
    depth += 1.5 * math.sin(3.0 * math.pi * params["x_mm"]) * \
        math.sin(3.0 * math.pi * params["y_mm"])
    return {"s11_db_min_in_band": depth}


def _cost(params: dict[str, float]) -> float:
    return SpecEvaluator.evaluate_objectives(bowl_metrics(params), OBJS)


def _random_reference() -> float:
    """B_RANDOM 点随机扫描的典型终值（5 种子 median，确定性重算）。"""
    finals = []
    for s in (7, 13, 21, 99, 2027):
        costs = [_cost(pt)
                 for pt in lhs_points(BOUNDS, B_RANDOM, seed=s)["points"]]
        finals.append(best_so_far_trace(costs)[-1])
    return sorted(finals)[len(finals) // 2]


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """环本身不落盘，但服务/CLI 测试会写 runs/——统一 chdir 隔离。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


class TestSelectTopk:
    def test_greedy_with_min_distance(self):
        bounds = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
        # 候选按预测 cost 升序；a=0.05/0.33 距已选点过近应被 min_dist 跳过
        candidates = [(1.0, {"a": 0.02, "b": 0.5}),
                      (2.0, {"a": 0.05, "b": 0.5}),
                      (3.0, {"a": 0.30, "b": 0.5}),
                      (4.0, {"a": 0.33, "b": 0.5}),
                      (5.0, {"a": 0.60, "b": 0.5})]
        picked = select_topk(candidates, 3, bounds, exclude=[],
                             min_dist=0.2)
        assert [p["a"] for _c, p in picked] == [pytest.approx(0.02),
                                                pytest.approx(0.30),
                                                pytest.approx(0.60)]
        # 两两归一化距离 ≥ min_dist（贪心多样性约束的核心语义）
        for i, (_c1, p1) in enumerate(picked):
            for _c2, p2 in picked[i + 1:]:
                d = math.sqrt((p1["a"] - p2["a"]) ** 2)
                assert d >= 0.2 - 1e-9

    def test_exclude_evaluated_points(self):
        bounds = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
        candidates = [(1.0, {"a": 0.30, "b": 0.50}),
                      (2.0, {"a": 0.32, "b": 0.50}),
                      (3.0, {"a": 0.70, "b": 0.10})]
        evaluated = [{"a": 0.31, "b": 0.50}]
        picked = select_topk(candidates, 3, bounds, exclude=evaluated,
                             min_dist=0.1)
        # 前两个候选距已评估点 < 0.1 被排除，只剩第三个
        assert len(picked) == 1
        assert picked[0][1]["a"] == pytest.approx(0.70)


class TestSurrogateLoop:
    def test_reduction_on_analytic_peak(self):
        """验收裁判：达随机参考质量的真跑数 median ≤ B/3（缩减 ≥60%）。"""
        ref = _random_reference()
        n_refs: list[int] = []
        for seed in LOOP_SEEDS:
            res = run_surrogate_loop(
                BOUNDS, OBJS, bowl_metrics,
                n_init=10, top_k=3, max_real=24, virtual_trials=800,
                seed=seed)
            assert res["ok"]
            assert res["stop_reason"] in {"stagnation", "budget"}
            assert res["best"] is not None
            trace = best_so_far_trace(res["real_cost_trace"])
            n_ref = next(
                (i + 1 for i, c in enumerate(trace) if c <= ref), None)
            assert n_ref is not None, (
                f"seed={seed} 未达随机参考质量 {ref:.3f}")
            # 单种子安全上限（17/33=52% 用量；校准实测最大 11）
            assert n_ref <= 17, f"seed={seed} 达 ref 用 {n_ref} 真跑"
            # 质量严格更优：环 final 好于随机典型终值
            assert res["best"]["cost"] < ref
            n_refs.append(n_ref)
        # §4 验收：真跑次数 ≤ 随机搜索 1/3（中位数口径，防单种子抖动）
        assert sorted(n_refs)[1] <= B_RANDOM // 3, (
            f"缩减率不足: n_refs={n_refs}")

    def test_budget_stop_and_1d_convergence(self):
        bounds = {"x_mm": (0.0, 1.0)}
        objs = [Objective(metric="s11_db_min", band=[2.3, 2.5],
                          op=MetricOp.MAX_BELOW, value=-47.0, weight=1.0)]

        def valley(params):
            depth = -46.0 + 80.0 * (params["x_mm"] - 0.4) ** 2
            return {"s11_db_min_in_band": depth}

        res = run_surrogate_loop(bounds, objs, valley,
                                 n_init=5, top_k=2, max_real=13,
                                 virtual_trials=300, seed=42)
        assert res["ok"]
        assert res["n_real_used"] <= 13
        assert res["n_attempts"] <= 13
        # 谷底 cost=1.0，环应收敛到近底（ surrogate 一阶即可拟合的 1D 面）
        assert res["best"]["cost"] < 1.5

    def test_eval_failure_budgeted_not_fatal(self):
        def flaky(params: dict[str, float]) -> dict[str, float]:
            if params["x_mm"] > 0.7:
                raise RuntimeError("求解失败注入")
            return bowl_metrics(params)

        res = run_surrogate_loop(BOUNDS, OBJS, flaky,
                                 n_init=6, top_k=2, max_real=12,
                                 virtual_trials=150, seed=42)
        assert res["ok"]
        assert res["n_failures"] > 0
        assert res["best"] is not None
        # 预算按尝试计：失败点也烧预算（否则失败面会死循环）
        assert res["n_attempts"] == res["n_real_used"] + res["n_failures"]
        assert res["best"]["params"]["x_mm"] <= 0.7

    def test_empty_inputs_rejected(self):
        res = run_surrogate_loop({}, OBJS, bowl_metrics)
        assert not res["ok"]
        res = run_surrogate_loop(BOUNDS, [], bowl_metrics)
        assert not res["ok"]


class TestSurrogateLoopConstraints:
    """P2⑥ sbo 软约束通道：违约量记录 + 最优可行 best + 全不可行如实报告。

    合成面（确定性、零真机）：cost 谷在 x*=0.3；约束 s21≥0 只在
    x∈[0.7167, 0.8833] 可行——无约束最优 (0.3) 落在可行域外，带约束环的
    best 必须移进可行域且 cost 变差（约束有代价，不凑绿 #122）。
    """

    BOUNDS_1D: ClassVar[dict[str, tuple[float, float]]] = {"x_mm": (0.0, 1.0)}
    OBJ: ClassVar[list[Objective]] = [
        Objective(metric="s11_db_min", band=[2.3, 2.5],
                  op=MetricOp.MAX_BELOW, value=-47.0, weight=1.0)]
    CONS: ClassVar[list[Objective]] = [
        Objective(metric="s21_db", band=[2.3, 2.5],
                  op=MetricOp.MIN_ABOVE, value=0.0, weight=1.0)]
    # s21 = 5 - 60*|x-0.8| ≥ 0 ⇔ |x-0.8| ≤ 1/12
    X_LO, X_HI = 0.8 - 1.0 / 12.0, 0.8 + 1.0 / 12.0

    @staticmethod
    def _eval(params: dict[str, float]) -> dict[str, float]:
        depth = -46.0 + 80.0 * (params["x_mm"] - 0.3) ** 2
        s21 = 5.0 - 60.0 * abs(params["x_mm"] - 0.8)
        return {"s11_db_min_in_band": depth, "s21_db_mean_in_band": s21}

    def test_constrained_best_moves_into_feasible_region(self):
        res = run_surrogate_loop(
            self.BOUNDS_1D, self.OBJ, self._eval,
            n_init=6, top_k=2, max_real=14, virtual_trials=250, seed=42,
            constraints=self.CONS)
        assert res["ok"]
        assert res["best"] is not None
        bx = res["best"]["params"]["x_mm"]
        # best 必须真可行（可行性由 evaluate_fn 判定，非代理外推）
        assert self.X_LO - 1e-9 <= bx <= self.X_HI + 1e-9
        assert res["n_feasible"] >= 1
        assert res["best_feasible"] is not None
        assert res["best_feasible"]["cost"] == pytest.approx(
            res["best"]["cost"])
        assert "all_infeasible" not in res
        # 约束有代价：可行域内最优 cost 显著劣于无约束谷底（=1.0）
        assert res["best"]["cost"] > 2.0

    def test_all_infeasible_reported_honestly(self):
        # 约束不可满足（s21 ≥ 100 不可能）→ 全不可行：best=None +
        # all_infeasible=True + n_feasible=0，不凑绿（#122）
        impossible = [Objective(metric="s21_db", band=[2.3, 2.5],
                                op=MetricOp.MIN_ABOVE, value=100.0,
                                weight=1.0)]
        res = run_surrogate_loop(
            self.BOUNDS_1D, self.OBJ, self._eval,
            n_init=5, top_k=2, max_real=8, virtual_trials=100, seed=42,
            constraints=impossible)
        assert res["ok"]  # 环跑完 ≠ 判定可行；不可行如实上报
        assert res["best"] is None
        assert res["best_feasible"] is None
        assert res["all_infeasible"] is True
        assert res["n_feasible"] == 0

    def test_unconstrained_path_key_surface_unchanged(self):
        """无约束路径行为逐字节不变：不新增 E10 三键，best=全局最优。"""
        res = run_surrogate_loop(
            BOUNDS, OBJS, bowl_metrics,
            n_init=5, top_k=2, max_real=9, virtual_trials=120, seed=42)
        assert res["ok"]
        for key in ("n_feasible", "best_feasible", "all_infeasible"):
            assert key not in res
        # best 仍是全样本最优（无可行门）
        assert res["best"]["cost"] == pytest.approx(min(res["real_cost_trace"]))


def _sbo_recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "substrate": "rogers4350b_h0.508",
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.58},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 101},
        "objectives": [
            {"metric": "s11_db_min", "band": [2.3, 2.5],
             "op": "max_below", "value": -40},
        ],
        "optimization": {
            "params": {
                "series_w_mm": {"low": 0.2, "high": 0.8},
                "shunt_w_mm": {"low": 0.6, "high": 2.0},
            },
        },
    }
    path = tmp_path / "sbo_recipe.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")
    return path


class TestService:
    def test_surrogate_optimize_service(self, tmp_path):
        from rfauto.service.surrogate_optimize_service import (
            surrogate_optimize,
        )

        recipe = _sbo_recipe(tmp_path)
        result = surrogate_optimize(
            recipe, adapter_name="fake",
            n_init=6, top_k=2, max_real=10, virtual_trials=150, seed=42)
        assert result["ok"], result.get("errors")
        assert isinstance(result["best"]["cost"], float)
        assert result["n_real_used"] <= 10
        assert result["algorithm"] == "surrogate_loop"
        # 产物落盘：surrogate_loop.json + meta.json（run 真伪判据）
        run_dir = Path(result["run_dir"])
        assert (run_dir / "surrogate_loop.json").is_file()
        meta = (run_dir / "meta.json")
        assert meta.is_file()
        meta_doc = yaml.safe_load(meta.read_text(encoding="utf-8"))
        assert meta_doc["algorithm"] == "surrogate_loop"
        assert meta_doc["adapter"] == "fake"

    def test_service_rejects_missing_recipe(self):
        from rfauto.service.surrogate_optimize_service import (
            surrogate_optimize,
        )

        result = surrogate_optimize("no_such_recipe.yaml")
        assert not result["ok"]


class TestCli:
    def test_tune_sbo_command(self, tmp_path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        recipe = _sbo_recipe(tmp_path)
        runner = CliRunner()
        # max-trials=n_init → 只跑初始批，零虚拟寻优（快路径冒烟）
        result = runner.invoke(app, [
            "tune", str(recipe), "--sampler", "sbo",
            "--adapter", "fake", "--max-trials", "10",
        ])
        assert result.exit_code == 0, result.output
        assert "代理寻优环完成" in result.output
        assert "stop" not in result.output or "budget" in result.output


class TestReviewHardening:
    """补强回归（空样本不炸代理 fit / 预算钳制 / 代理异常罚值）。"""

    def test_all_init_fail_no_crash(self):
        # 全部初始点真跑失败：环必须以 surrogate_fit_failed 停，
        # 不得让空样本炸代理 fit
        def always_fail(params):
            raise RuntimeError("求解失败注入")

        res = run_surrogate_loop(BOUNDS, OBJS, always_fail,
                                 n_init=4, top_k=2, max_real=8,
                                 virtual_trials=50, seed=42)
        assert res["ok"]
        assert res["stop_reason"] == "surrogate_fit_failed"
        assert res["n_failures"] >= 4
        assert res["best"] is None

    def test_n_init_clamped_to_budget(self):
        # 预算契约：n_init > max_real 时钳到 max_real
        calls = {"n": 0}

        def eval_count(params):
            calls["n"] += 1
            return bowl_metrics(params)

        res = run_surrogate_loop(BOUNDS, OBJS, eval_count,
                                 n_init=12, top_k=2, max_real=6,
                                 virtual_trials=50, seed=42)
        assert res["n_attempts"] <= 6

    def test_virtual_predict_exception_penalized(self):
        # 虚拟寻优中代理预测异常按大罚值处理，不炸环
        calls = {"n": 0}

        from rfauto.optimization.surrogate.base import SurrogateModel

        class FlakyModel(SurrogateModel):
            KIND = "flaky"

            def fit(self, samples):
                return self._mark_fitted(len(samples))

            def predict(self, params):
                calls["n"] += 1
                if calls["n"] > 2:
                    raise RuntimeError("预测失败注入")
                return bowl_metrics(params)

        from rfauto.optimization.surrogate import surrogate_registry

        surrogate_registry.register("flaky", FlakyModel)
        try:
            res = run_surrogate_loop(BOUNDS, OBJS, bowl_metrics,
                                     n_init=6, top_k=2, max_real=10,
                                     virtual_trials=60, seed=42,
                                     surrogate_kind="flaky")
        finally:
            surrogate_registry._factories.pop("flaky", None)
        assert res["ok"]


class TestQualityReport:
    """B-33：环报告携带真实代理质量（非占位）。"""

    def test_report_quality_matches_real_analysis(self):
        records: list[dict] = []

        def eval_fn(params: dict[str, float]) -> dict[str, float]:
            metrics = bowl_metrics(params)
            records.append({
                "params": dict(params),
                "cost": SpecEvaluator.evaluate_objectives(metrics, OBJS),
            })
            return metrics

        res = run_surrogate_loop(BOUNDS, OBJS, eval_fn,
                                 n_init=8, top_k=2, max_real=14,
                                 virtual_trials=200, seed=42)
        assert res["ok"]
        quality = res["surrogate_quality"]
        assert quality["source"] == "analyze_run_surrogate"
        assert quality["available"] is True
        assert quality["kind"] == "cross_validation_out_of_fold"
        assert quality["n_samples"] == len(records) == res["n_real_used"]
        assert quality["rms_error"] > 0
        # ρ 在交叉验证预测为常数时无定义（诚实返回 None，非占位 0）
        rho = quality["spearman_rho"]
        assert rho is None or -1.0 <= rho <= 1.0
        assert abs(sum(quality["param_importance"].values()) - 1.0) < 1e-6
        # 数值必须等于对同一批真实样本重跑 analyze_run_surrogate 的输出
        direct = analyze_run_surrogate("probe", records).to_dict()["quality"]
        for key in ("rms_error", "mae", "max_abs_residual",
                    "spearman_rho", "r2", "y_mean", "y_std"):
            if direct[key] is None:
                assert quality[key] is None
            else:
                assert quality[key] == pytest.approx(direct[key], abs=1e-9)

    def test_in_loop_quality_from_actual_surrogate(self):
        res = run_surrogate_loop(BOUNDS, OBJS, bowl_metrics,
                                 n_init=8, top_k=2, max_real=14,
                                 virtual_trials=200, seed=42)
        quality = res["in_loop_surrogate_quality"]
        assert quality["available"] is True
        assert quality["source"] == "surrogate_loop:poly_ridge"
        assert quality["kind"] == "in_sample_train_residual"
        assert quality["n"] == res["n_real_used"]
        assert quality["rms_error"] >= 0.0
        assert quality["spearman_rho"] is not None

