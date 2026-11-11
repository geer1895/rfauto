"""T-N5 单目标优化器族竞赛架单测（aurora_n W1-D；aurora_p E1 扩 turbo_multi）。

判据（任务书预声明，runs/aurora_n/recon/PROPOSALS.md §T-N5）：
- 七引擎注册齐全（tpe/gp/cmaes/turbo/turbo_multi/eipu/sbo）；
- 负例=退化常数目标（#195 语义）拒绝开跑显式报错；nan 探针 /
  band 退化 / sbo 缺 known_optimum / 未知引擎 / 输入守卫同样显式；
- 确定性钉=同 seed 组重跑报表逐位一致（JSON 逐字节相等；钉快速引擎
  组 tpe/cmaes/turbo/eipu——gp/sbo 的确定性由其内核既有钉与引擎
  smoke 覆盖，全七引擎另出 smoke）；
- 两阶段记分：早停引擎轨迹按终值补齐（n_evals_used 如实反映实际
  评估数，best@半程从补齐曲线读）；
- 引擎接入=公开 API（#118：judge 只消费轨迹记分，与被测零共享代码
  路径）。

aurora_p E1（turbo_multi 补榜接入）增量：注册名单钉扩列（纯增量，
既有六引擎零变化）；turbo_multi 专项钉=同 seed 逐位确定性 / 预算
精确消费 / 启动段与 turbo 同源 + 多域轮转段结构性分叉。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.optimization import competition_scalar as comp_mod
from rfauto.optimization.competition_scalar import (
    ScalarProblem,
    format_report_markdown,
    list_scalar_engines,
    register_scalar_engine,
    run_competition_scalar,
)

#: 快速引擎组（单组合 <1s）——确定性钉与排名表用
FAST_ENGINES = ["tpe", "cmaes", "turbo", "eipu"]
ALL_ENGINES = ["tpe", "gp", "cmaes", "turbo", "eipu", "sbo", "turbo_multi"]

SPHERE_BOUNDS = {"x0": (0.0, 1.0), "x1": (0.0, 1.0)}


def _sphere(p: dict[str, float]) -> float:
    return (p["x0"] - 0.71) ** 2 + (p["x1"] - 0.19) ** 2


def _sphere_problem(**kw: object) -> ScalarProblem:
    kwargs: dict = {"name": "sphere2d", "bounds": dict(SPHERE_BOUNDS),
                    "objective_fn": _sphere, "target": 0.01,
                    "known_optimum": 0.0}
    kwargs.update(kw)
    return ScalarProblem(**kwargs)


def test_seven_engines_registered() -> None:
    """注册名单钉（aurora_p E1 扩列 turbo_multi，既有六引擎序零变化）。"""
    assert list_scalar_engines() == [
        "tpe", "gp", "cmaes", "turbo", "eipu", "sbo", "turbo_multi"]


class TestRankingAndStages:
    def test_ranking_tables_and_runs_shape(self) -> None:
        """两阶段排名表 + 逐 run 记分结构（快速引擎组，2 问题×2 seed）。"""
        prob_a = _sphere_problem()
        prob_b = _sphere_problem(
            name="sphere_shift", objective_fn=lambda p: _sphere(p) + 0.5,
            target=0.51, known_optimum=0.5)
        r = run_competition_scalar(
            [prob_a, prob_b], FAST_ENGINES, n_eval=12, seeds=[0, 1])
        assert r["schema"] == "competition-scalar-v1"
        assert r["stages"] == {"stage1_horizon": 6, "stage2_horizon": 12}
        assert len(r["runs"]) == 4 * 2 * 2
        for row in (r["ranking_stage1"], r["ranking_stage2"],
                    r["ranking_target"]):
            assert {x["engine"] for x in row} == set(FAST_ENGINES)
            means = [x["mean_rank"] for x in row]
            assert means == sorted(means)  # 升序排列
            assert abs(sum(x["mean_rank"] for x in row) / 4 - 2.5) < 1e-9
        run0 = r["runs"][0]
        assert run0["n_evals_used"] == 12
        assert run0["best_final"] <= run0["best_half"]
        assert run0["auc"] >= 0.0 and math.isfinite(run0["auc"])
        # 达标次数：达标为正整数或未达标记 None（预算内不保证达标）
        assert (run0["n_evals_to_target"] is None
                or (isinstance(run0["n_evals_to_target"], int)
                    and run0["n_evals_to_target"] >= 1))

    def test_band_is_engine_independent(self) -> None:
        """归一化带由 judge 探针定（对全部引擎同值——组内公平前提）。"""
        prob = _sphere_problem()
        r = run_competition_scalar([prob], ["tpe", "cmaes"], 8, [0])
        assert r["problems"][0]["band"][0] == 0.0
        assert r["problems"][0]["band"][1] > 0.0

    def test_markdown_report_deterministic(self) -> None:
        prob = _sphere_problem()
        r = run_competition_scalar([prob], ["tpe", "cmaes"], 8, [0])
        md1 = format_report_markdown(r)
        md2 = format_report_markdown(r)
        assert md1 == md2
        assert "# T-N5" in md1 and "| 排名 | 引擎 | 平均秩 |" in md1


def _strip_wallclock(result: dict) -> dict:
    """剥离墙钟 provenance 字段（elapsed_s——唯一预声明的非确定性字段）。"""
    out = json.loads(json.dumps(result))
    for run in out["runs"]:
        run.pop("elapsed_s", None)
    return out


class TestDeterminismPin:
    def test_same_seed_rerun_bitwise_identical(self) -> None:
        """确定性钉：同 seed 组重跑 → 记分面 JSON 逐字节一致（快速引擎组）。

        预声明口径：``elapsed_s`` 是墙钟 provenance（唯一非确定性字段），
        逐字节比对前剥离；其余全部字段（AUC/best/达标次数/排名）逐位一致。
        """
        prob = _sphere_problem()
        kw = {"problems": [prob], "engines": FAST_ENGINES, "n_eval": 10,
              "seeds": [0]}
        r1 = _strip_wallclock(run_competition_scalar(**kw))
        r2 = _strip_wallclock(run_competition_scalar(**kw))
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)

    def test_seed_change_changes_trajectory(self) -> None:
        """换 seed 换轨迹（随机面存在性——与确定性钉互补）。"""
        prob = _sphere_problem()
        r0 = run_competition_scalar([prob], ["tpe"], 10, [0])
        r1 = run_competition_scalar([prob], ["tpe"], 10, [1])
        assert r0["runs"][0]["best_final"] != r1["runs"][0]["best_final"]


class TestNegativeGuards:
    def test_constant_objective_rejected(self) -> None:
        """负例：退化常数目标拒绝开跑（#195 常数陷阱语义）。"""
        prob = ScalarProblem(
            name="constant", bounds=dict(SPHERE_BOUNDS),
            objective_fn=lambda p: 3.14, target=3.0, known_optimum=3.14)
        with pytest.raises(ValueError, match="退化常数目标"):
            run_competition_scalar([prob], ["tpe"], 10, [0])

    def test_nonfinite_probe_rejected(self) -> None:
        prob = ScalarProblem(
            name="nan_fn", bounds=dict(SPHERE_BOUNDS),
            objective_fn=lambda p: float("nan"))
        with pytest.raises(ValueError, match="非有限"):
            run_competition_scalar([prob], ["tpe"], 10, [0])

    def test_degenerate_band_rejected(self) -> None:
        """known_optimum ≥ 探针最差值 → band 退化显式拒绝。"""
        prob = _sphere_problem(known_optimum=10.0)
        with pytest.raises(ValueError, match="band 退化"):
            run_competition_scalar([prob], ["tpe"], 10, [0])

    def test_sbo_requires_known_optimum(self) -> None:
        from rfauto.optimization.competition_scalar import run_scalar_engine

        prob = _sphere_problem(known_optimum=None)
        with pytest.raises(ValueError, match="known_optimum"):
            run_scalar_engine(prob, "sbo", 6, 0)

    def test_unknown_engine_and_input_guards(self) -> None:
        prob = _sphere_problem()
        with pytest.raises(ValueError, match="未知引擎"):
            run_competition_scalar([prob], ["nope"], 10, [0])
        with pytest.raises(ValueError, match="n_eval 必须 >0"):
            run_competition_scalar([prob], ["tpe"], 0, [0])
        with pytest.raises(ValueError, match="不得为空"):
            run_competition_scalar([prob], ["tpe"], 10, [])
        with pytest.raises(ValueError, match="不得为空"):
            run_competition_scalar([], ["tpe"], 10, [0])

    def test_duplicate_engine_registration_rejected(self) -> None:
        with pytest.raises(ValueError, match="重复注册"):
            register_scalar_engine("tpe")(lambda p, n, s: [0.0])
        with pytest.raises(ValueError, match="不得为空"):
            register_scalar_engine("  ")(lambda p, n, s: [0.0])

    def test_problem_book_validation(self) -> None:
        with pytest.raises(ValueError, match="lo<hi"):
            ScalarProblem(name="bad", bounds={"x": (1.0, 0.0)},
                          objective_fn=_sphere)
        with pytest.raises(ValueError, match="不得为空"):
            ScalarProblem(name="empty", bounds={}, objective_fn=_sphere)
        with pytest.raises(ValueError, match="target 须有限"):
            ScalarProblem(name="nan_t", bounds=dict(SPHERE_BOUNDS),
                          objective_fn=_sphere, target=float("nan"))


class TestScoringSemantics:
    def test_early_stop_trajectory_padded_to_horizon(self, monkeypatch) -> None:
        """早停引擎：n_evals_used 如实、best-so-far 补齐到 horizon、
        达标次数从补齐曲线读（早停不吃 AUC 便宜）。"""
        reg = dict(comp_mod.SCALAR_ENGINE_REGISTRY)
        reg["stub_short"] = lambda p, n, s: [1.0, 0.5]
        monkeypatch.setattr(comp_mod, "SCALAR_ENGINE_REGISTRY", reg)
        prob = _sphere_problem(target=0.6)
        r = run_competition_scalar([prob], ["stub_short"], 6, [0])
        run = r["runs"][0]
        assert run["n_evals_used"] == 2
        assert run["best_half"] == 0.5  # 补齐曲线 @horizon=3
        assert run["best_final"] == 0.5
        assert run["n_evals_to_target"] == 2  # best_so_far[1]=0.5 ≤ 0.6
        # AUC 按补齐曲线（2 个评估 + 4 步常数 0.5）
        band_hi = r["problems"][0]["band"][1]
        expect = (1.0 / band_hi + 5 * 0.5 / band_hi) / 6
        assert abs(run["auc"] - expect) < 1e-12

    def test_budget_exact_ask_tell_engines(self) -> None:
        """ask/tell 引擎精确消费 n_eval；sbo ≤ n_eval（轮次结构如实）。"""
        prob = _sphere_problem()
        for eng in ("tpe", "cmaes", "turbo", "eipu"):
            r = run_competition_scalar([prob], [eng], 9, [0])
            assert r["runs"][0]["n_evals_used"] == 9, eng


class TestAllEnginesSmoke:
    @pytest.mark.skipif(__import__("importlib.util", fromlist=["x"]).find_spec("torch") is None,
                        reason="七引擎含 torch 系采样器（CI 无 torch 装面）——诚实 skip")
    def test_all_seven_engines_produce_runs(self) -> None:
        """全七引擎（含 gp/sbo 重件）单问题 smoke：轨迹非空、排名完整。"""
        prob = _sphere_problem()
        r = run_competition_scalar([prob], ALL_ENGINES, 12, [0])
        assert len(r["runs"]) == 7
        by_engine = {run["engine"]: run for run in r["runs"]}
        assert set(by_engine) == set(ALL_ENGINES)
        sbo_run = by_engine["sbo"]
        assert 1 <= sbo_run["n_evals_used"] <= 12
        assert math.isfinite(sbo_run["best_final"])
        for eng in ("tpe", "gp", "cmaes", "turbo", "eipu", "turbo_multi"):
            assert by_engine[eng]["n_evals_used"] == 12
        assert {row["engine"] for row in r["ranking_stage2"]} == set(ALL_ENGINES)


class TestTurboMultiEngine:
    """turbo_multi 引擎专项钉（aurora_p E1；T-N10 多域 TuRBO-5 接入）。"""

    def test_budget_exact_and_finite(self) -> None:
        """ask/tell 接线预算精确消费 n_eval（含 n_init>n_eval//4 小预算档）。"""
        prob = _sphere_problem()
        for n_eval in (9, 10, 12):
            r = run_competition_scalar([prob], ["turbo_multi"], n_eval, [0])
            run = r["runs"][0]
            assert run["n_evals_used"] == n_eval
            assert math.isfinite(run["best_final"])
            assert run["auc"] >= 0.0

    def test_same_seed_rerun_bitwise_identical(self) -> None:
        """确定性钉（验收 C）：同 seed 两跑记分面 JSON 逐位一致。"""
        prob = _sphere_problem()
        kw = {"problems": [prob], "engines": ["turbo_multi"], "n_eval": 10,
              "seeds": [0]}
        r1 = _strip_wallclock(run_competition_scalar(**kw))
        r2 = _strip_wallclock(run_competition_scalar(**kw))
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)

    def test_seed_change_changes_trajectory(self) -> None:
        """换 seed 换轨迹（随机面存在性——与确定性钉互补）。"""
        prob = _sphere_problem()
        r0 = run_competition_scalar([prob], ["turbo_multi"], 10, [0])
        r1 = run_competition_scalar([prob], ["turbo_multi"], 10, [1])
        assert r0["runs"][0]["best_final"] != r1["runs"][0]["best_final"]

    def test_shared_startup_then_multi_region_divergence(self) -> None:
        """结构性钉：启动段与 turbo 同源（同 LHS 同值），多域轮转段分叉。

        turbo_multi 接线与 turbo 引擎同 n_init 公式同 seed → LHS 启动段
        评估序值逐位相同（严格可比前提）；其后多域轮转提议（K=5 域
        状态机）与单域 turbo 分叉——n_regions=5 形态确实生效（非
        turbo 别名）。
        """
        from rfauto.optimization.competition_scalar import run_scalar_engine

        prob = _sphere_problem()
        v_turbo = run_scalar_engine(prob, "turbo", 12, 0)
        v_multi = run_scalar_engine(prob, "turbo_multi", 12, 0)
        n_init = max(2, min(16, 12 // 4))
        assert len(v_multi) == 12
        assert v_multi[:n_init] == v_turbo[:n_init]  # 共享 LHS 启动段
        assert v_multi != v_turbo  # 多域轮转段结构性分叉
