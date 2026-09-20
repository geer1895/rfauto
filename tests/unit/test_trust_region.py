"""WP3.2 stage-2 信任域精修环单测（TR-ARS + Bandler 加性输出映射）。

判据口径（cjors.2025184 综述锚：trust-region surrogate 综述）——
粗模型=代理快档（poly_ridge 全局面），细跑=合成解析裁判（零真机），
验收=stage-2 vs stage-1 真评估次数/终值对照。

裁判问题与 test_surrogate_loop 同源：耦合二次碗 + 正弦纹波 s11 谷深
（value=-47 无零平台防种子彩票）。

冻结常量来自本机实测（2026-09-12，.venv，三种子 {7, 2026, 42}）：
- baseline（stage-1-only，max_real=24）finals=[1.1206, 0.9708, 0.6923]，
  median=0.9708；
- two-stage（stage-1 max_real=12 + stage-2 余量 12）finals=[0.6398, 0.9152,
  0.7483]，median=0.7483——中位数优于 baseline；**如实记录** seed=42
  two-stage（0.7483）劣于 baseline（0.6923）：该种子 stage-1 截断到 12 次
  的起点最差（2.4805），TR 精修 7 次真跑恢复到 0.7483 但未追平 24 次全程
  stage-1——改进或持平如实呈现，不凑绿；
- 达"baseline 终值水平"的真评估数 [baseline, two-stage] 逐种子 =
  [[18, 13], [17, 17], [17, None]]（seed=42 未达该水平，诚实记录）——
  3 种子中 ≥2 个 two-stage 用量 ≤ baseline。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# 确保 src 在 path 中（同 test_surrogate_loop 模式）
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.core.objectives import (
    MetricOp,
    Objective,
    SpecEvaluator,
)
from rfauto.optimization.sample_design import lhs_points
from rfauto.optimization.surrogate_loop import (
    best_so_far_trace,
    run_surrogate_loop,
)
from rfauto.optimization.trust_region import (
    refine_trust_region,
    run_two_stage,
)

BOUNDS = {"x_mm": (0.0, 1.0), "y_mm": (0.0, 1.0)}
X_STAR, Y_STAR = 0.30, 0.62
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


def _combined_best_trace(two: dict) -> list[float]:
    """two-stage 合成 best-so-far 轨迹：stage1 段 + stage2 段拼接。"""
    t1 = best_so_far_trace(two["stage1"]["real_cost_trace"])
    t2 = best_so_far_trace(two["stage2"]["real_cost_trace"])
    return best_so_far_trace(t1 + t2)


def _evals_to_target(trace: list[float], target: float) -> int | None:
    return next((i + 1 for i, c in enumerate(trace) if c <= target), None)


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


class TestTwoStageVsStage1:
    """§10.9 1b 验收裁判：合成解析面上 stage-2 vs stage-1 对照。"""

    @pytest.fixture(scope="class")
    def calibrated(self):
        base = {}
        two = {}
        for seed in LOOP_SEEDS:
            base[seed] = run_surrogate_loop(
                BOUNDS, OBJS, bowl_metrics, n_init=10, top_k=3,
                max_real=24, virtual_trials=600, seed=seed)
            two[seed] = run_two_stage(
                BOUNDS, OBJS, bowl_metrics,
                stage1={"n_init": 10, "top_k": 3, "max_real": 12,
                        "virtual_trials": 600, "seed": seed},
                stage2={"max_real": 12, "virtual_trials": 400, "seed": seed})
        return base, two

    def test_median_final_improves(self, calibrated):
        base, two = calibrated
        finals_base = sorted(base[s]["best"]["cost"] for s in LOOP_SEEDS)
        finals_two = sorted(two[s]["best"]["cost"] for s in LOOP_SEEDS)
        med_base = finals_base[1]
        med_two = finals_two[1]
        # 校准实测 0.9708 → 0.7483；留 0.1 量化余量防浮点/库版本抖动
        assert med_two < med_base - 0.1, (
            f"stage-2 中位数终值未改善: {med_two:.4f} vs {med_base:.4f}")

    def test_stage2_never_worse_than_its_stage1(self, calibrated):
        # 环契约：stage-2 只接受严格改善，final 不得劣于本条 stage-1 终值
        _base, two = calibrated
        for seed in LOOP_SEEDS:
            t = two[seed]
            assert t["ok"]
            assert t["stage2"]["best"]["cost"] <= \
                t["stage1"]["best"]["cost"] + 1e-12

    def test_evals_to_baseline_level(self, calibrated):
        """真评估次数对照：≥2/3 种子 two-stage 达 baseline 终值水平
        所用真评估 ≤ baseline（seed=42 未达，docstring 如实记录）。"""
        base, two = calibrated
        wins = 0
        report: list[tuple[int, int | None, int | None]] = []
        for seed in LOOP_SEEDS:
            target = base[seed]["best"]["cost"]
            n_base = _evals_to_target(
                best_so_far_trace(base[seed]["real_cost_trace"]), target)
            n_two = _evals_to_target(_combined_best_trace(two[seed]), target)
            report.append((n_base, n_two, seed))
            if n_two is not None and n_base is not None and n_two <= n_base:
                wins += 1
        assert wins >= 2, f"真评估次数对照不足: {report}"

    def test_total_budget_respected(self, calibrated):
        _base, two = calibrated
        for seed in LOOP_SEEDS:
            t = two[seed]
            total = t["stage1"]["n_attempts"] + t["stage2"]["n_attempts"]
            assert total <= 24
            assert t["n_attempts_total"] == total


class TestRefineContract:
    def test_deterministic_same_seed(self):
        start = {"x_mm": 0.35, "y_mm": 0.55}
        init = lhs_points(BOUNDS, 10, seed=11)["points"]

        def run():
            return refine_trust_region(
                BOUNDS, OBJS, bowl_metrics, start_params=start,
                warm_samples=[{"params": dict(p),
                               "metrics": bowl_metrics(p)} for p in init],
                max_real=8, virtual_trials=120, seed=5)

        r1, r2 = run(), run()
        # elapsed_s 是墙钟，不入确定性比较
        r1.pop("elapsed_s")
        r2.pop("elapsed_s")
        assert r1 == r2
        assert r1["ok"]
        assert r1["stop_reason"] in {
            "stagnation", "budget", "trust_region_min", "no_new_points",
            "insufficient_region_samples"}
        assert r1["n_attempts"] == r1["n_real_used"] + r1["n_failures"]
        assert r1["n_attempts"] <= 8
        assert r1["best"]["cost"] <= r1["start_cost"] + 1e-12

    def test_start_exact_match_reuses_warm_cost(self):
        start = {"x_mm": 0.30, "y_mm": 0.62}
        warm = [{"params": dict(start), "metrics": bowl_metrics(start)}]
        res = refine_trust_region(
            BOUNDS, OBJS, bowl_metrics, start_params=start,
            warm_samples=warm, max_real=6, virtual_trials=60, seed=3)
        assert res["ok"]
        # 起点与 warm 完全相同 → 不应再花真跑重测起点
        assert res["start_cost"] == pytest.approx(_cost(start))
        assert all(f["params"] != start for f in res["failures"])

    def test_failure_budgeted_not_fatal(self):
        def flaky(params):
            if abs(params["x_mm"] - 0.5) < 0.08 and \
                    abs(params["y_mm"] - 0.5) < 0.08:
                raise RuntimeError("求解失败注入")
            return bowl_metrics(params)

        res = refine_trust_region(
            BOUNDS, OBJS, flaky, start_params={"x_mm": 0.8, "y_mm": 0.2},
            max_real=10, virtual_trials=100, seed=9)
        assert res["ok"]
        assert res["n_attempts"] == res["n_real_used"] + res["n_failures"]
        assert res["n_attempts"] <= 10

    def test_local_mapping_variant_runs(self):
        start = {"x_mm": 0.4, "y_mm": 0.6}
        init = lhs_points(BOUNDS, 10, seed=21)["points"]
        res = refine_trust_region(
            BOUNDS, OBJS, bowl_metrics, start_params=start,
            warm_samples=[{"params": dict(p),
                           "metrics": bowl_metrics(p)} for p in init],
            max_real=8, virtual_trials=120, seed=5, mapping_kind="local")
        assert res["ok"]
        assert res["mapping_kind"] == "local"
        assert res["n_attempts"] <= 8
        assert res["best"]["cost"] <= _cost(start) + 1e-12

    def test_invalid_inputs_rejected(self):
        assert not refine_trust_region({}, OBJS, bowl_metrics,
                                       start_params={"x": 0.1})["ok"]
        assert not refine_trust_region(BOUNDS, [], bowl_metrics,
                                       start_params={"x_mm": 0.1})["ok"]
        assert not refine_trust_region(
            BOUNDS, OBJS, bowl_metrics,
            start_params=None)["ok"]
        assert not refine_trust_region(
            BOUNDS, OBJS, bowl_metrics, start_params={"x_mm": 0.1},
            mapping_kind="bogus")["ok"]


class TestTwoStageInterface:
    def test_run_two_stage_contract(self):
        res = run_two_stage(
            BOUNDS, OBJS, bowl_metrics,
            stage1={"n_init": 6, "top_k": 2, "max_real": 10,
                    "virtual_trials": 150, "seed": 42},
            stage2={"max_real": 6, "virtual_trials": 100, "seed": 42})
        assert res["ok"]
        assert res["algorithm"] == "two_stage_sbo_trust_region"
        assert res["stage2"] is not None
        assert res["best"]["cost"] <= res["stage1"]["best"]["cost"] + 1e-12
        assert res["n_real_used_total"] == (
            res["stage1"]["n_real_used"] + res["stage2"]["n_real_used"])
        assert res["n_attempts_total"] <= 16

    def test_run_two_stage_all_init_fail(self):
        def always_fail(params):
            raise RuntimeError("求解失败注入")

        res = run_two_stage(
            BOUNDS, OBJS, always_fail,
            stage1={"n_init": 4, "top_k": 2, "max_real": 6,
                    "virtual_trials": 50, "seed": 42})
        assert res["ok"]
        assert res["stage2"] is None
        assert res["best"] is None
