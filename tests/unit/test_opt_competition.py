"""OP-5（round16 §六）：多目标优化器族同预算 HV 竞赛架 单元测试。

判据预声明（#207 合成裁判；同预算=同 n_eval 目标求值数，同 seed 组）：

1. 竞赛机制：四引擎（nsga2/rnsga3×pymoo、nsga2/nsga3×optuna）同预算
   40 eval × 3 seed 全部可跑，排名按 hv_mean 降序、平局按引擎名升序
   （确定性）；逐 run 记录 n_evaluations（optuna 引擎=精确预算）；
2. 确定性：同 problem/engines/seeds 两次竞赛排名逐字段一致；
3. 注册表面（基类+注册表，硬限制 3）：list_engines 含四内置引擎；
   重复注册同名字面拒绝；未知名 run_engine 报错列可用项；
   register_engine 空名拒绝；
4. 预算/入参守卫：n_eval≤0 / engines 空 / seeds 空显式 ValueError；
   rnsga3 缺 preference_ref_points 显式报错；
5. 问题书校验：bounds 行数/边界非法/ref_point 维数拒绝。

MOTPE 通道如实缺位说明：round16 规格的 MOTPE 依赖第三方 motpe 包
（本机未装且 API 未经源码实录，#215 禁臆写）——扩展位=ENGINE_REGISTRY
（register_engine 即入竞赛），本测试钉"注册表开放可扩展"语义。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.optimization.competition import (
    ENGINE_REGISTRY,
    CompetitionProblem,
    list_engines,
    register_engine,
    run_competition,
    run_engine,
)


def zdt1_like(x: np.ndarray) -> tuple[float, float]:
    f1 = float(x[0])
    g = 1.0 + 9.0 * float(np.mean(x[1:]))
    return (f1, float(g * (1.0 - np.sqrt(f1 / g))))


@pytest.fixture(scope="module")
def problem() -> CompetitionProblem:
    return CompetitionProblem(
        name="synth-mo", n_variables=3,
        bounds=((0.0, 1.0), (0.0, 1.0), (0.0, 1.0)),
        objective_fn=zdt1_like, n_objectives=2,
        ref_point=(1.2, 1.2),
        preference_ref_points=((0.2, 1.0), (0.8, 0.6)),
    )


ENGINES = ["nsga2_pymoo", "rnsga3_pymoo", "nsga2_optuna", "nsga3_optuna"]


class TestCompetitionMechanics:
    def test_four_engines_same_budget_ranked(self, problem):
        out = run_competition(problem, ENGINES, n_eval=40, seeds=[1, 2, 3])
        assert out["n_eval"] == 40 and out["seeds"] == [1, 2, 3]
        assert len(out["runs"]) == 12
        ranking = out["ranking"]
        # 排名=按 hv_mean 降序、平局按引擎名升序（确定性复排）
        assert ranking == sorted(
            ranking, key=lambda r: (-r["hv_mean"], r["engine"]))
        means = [r["hv_mean"] for r in ranking]
        assert means == sorted(means, reverse=True)
        for run in out["runs"]:
            assert run["n_evaluations"] >= 40
            assert run["hv"] >= 0.0

    def test_optuna_engine_budget_exact(self, problem):
        res = run_engine(problem, "nsga2_optuna", n_eval=17, seed=1)
        assert res.n_evaluations == 17
        assert len(res.F) == 17

    def test_deterministic_reruns(self, problem):
        a = run_competition(problem, ["nsga2_pymoo", "nsga2_optuna"],
                            n_eval=24, seeds=[4, 5])
        b = run_competition(problem, ["nsga2_pymoo", "nsga2_optuna"],
                            n_eval=24, seeds=[4, 5])
        assert a["ranking"] == b["ranking"]
        assert [(r["engine"], r["seed"], r["hv"]) for r in a["runs"]] == \
            [(r["engine"], r["seed"], r["hv"]) for r in b["runs"]]


class TestRegistrySurface:
    def test_builtin_engines_registered(self):
        for name in ENGINES:
            assert name in list_engines()

    def test_extension_point_open(self):
        # MOTPE 等第三方引擎经同一注册位扩展（#215：API 实录后接线）
        try:
            @register_engine("test_probe_engine")
            def _probe(problem, n_eval, seed):
                raise NotImplementedError

            assert "test_probe_engine" in list_engines()
        finally:
            ENGINE_REGISTRY.pop("test_probe_engine", None)
        assert "test_probe_engine" not in list_engines()

    def test_duplicate_and_empty_rejected(self):
        with pytest.raises(ValueError, match="重复注册"):
            @register_engine("nsga2_pymoo")
            def _dup(problem, n_eval, seed):
                return None

        with pytest.raises(ValueError, match="不得为空"):
            @register_engine("  ")
            def _empty(problem, n_eval, seed):
                return None

    def test_unknown_engine_lists_available(self, problem):
        with pytest.raises(ValueError, match="可用"):
            run_engine(problem, "motpe", 10, 1)


class TestGuardsAndValidation:
    def test_budget_and_input_guards(self, problem):
        with pytest.raises(ValueError, match="n_eval"):
            run_competition(problem, ENGINES[:1], n_eval=0, seeds=[1])
        with pytest.raises(ValueError, match="不得为空"):
            run_competition(problem, [], n_eval=10, seeds=[1])
        with pytest.raises(ValueError, match="不得为空"):
            run_competition(problem, ENGINES[:1], n_eval=10, seeds=[])

    def test_rnsga3_requires_preference_points(self):
        prob = CompetitionProblem(
            name="no-pref", n_variables=2, bounds=((0, 1), (0, 1)),
            objective_fn=zdt1_like, n_objectives=2, ref_point=(1.2, 1.2))
        with pytest.raises(ValueError, match="preference_ref_points"):
            run_engine(prob, "rnsga3_pymoo", 20, 1)

    def test_problem_book_validation(self):
        with pytest.raises(ValueError, match="不一致"):
            CompetitionProblem(
                name="bad", n_variables=3, bounds=((0, 1), (0, 1)),
                objective_fn=zdt1_like, n_objectives=2, ref_point=(1, 1))
        with pytest.raises(ValueError, match="lo<hi"):
            CompetitionProblem(
                name="bad", n_variables=1, bounds=((1.0, 0.0),),
                objective_fn=zdt1_like, n_objectives=2, ref_point=(1, 1))
        with pytest.raises(ValueError, match="ref_point 维数"):
            CompetitionProblem(
                name="bad", n_variables=1, bounds=((0, 1),),
                objective_fn=zdt1_like, n_objectives=2, ref_point=(1, 1, 1))
