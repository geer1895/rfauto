"""AD-9 分层调度器测试（hierarchical_scheduler：拓扑/参数两层+引擎注册表）。

全部离线：L1 伪语料/L2 参数搜索都吃 fake 闭式评估（秒级）；配方用仓内
recipes/ 真件与 tmp 配方，无墙钟进决策的确定性钉面。
"""

from __future__ import annotations

import json

import pytest
import yaml

from rfauto.service.hierarchical_scheduler import (
    EngineRegistry,
    MCTSGridSearchEngine,
    ParamSearchEngine,
    SurrogateSearchEngine,
    _allocate,
    plan_campaign,
)

WILKINSON = "recipes/wilkinson_pd_v1.yaml"
BRANCHLINE = "recipes/branchline_coupler_v1.yaml"


@pytest.fixture()
def two_candidates():
    return [{"name": "wilkinson", "recipe_path": WILKINSON},
            {"name": "branchline", "recipe_path": BRANCHLINE}]


class TestEngineRegistry:
    def test_builtin_engines_registered(self):
        assert set(EngineRegistry.available()) >= {"surrogate", "mcts"}

    def test_unknown_engine_raises(self):
        with pytest.raises(KeyError):
            EngineRegistry.create("no_such_engine")

    def test_register_custom_engine(self):
        class Dummy(ParamSearchEngine):
            name = "dummy_test_engine"

            def search(self, *, bounds, objectives, evaluate_fn,
                       budget, seed):
                return {"ok": True, "engine": self.name,
                        "best_params": None, "best_cost": None,
                        "n_evaluations": 0}

        EngineRegistry.register(Dummy)
        try:
            engine = EngineRegistry.create("dummy_test_engine")
            out = engine.search(bounds={}, objectives=[], evaluate_fn=None,
                                budget=1, seed=1)
            assert out["engine"] == "dummy_test_engine"
        finally:
            EngineRegistry._engines.pop("dummy_test_engine", None)


class TestAllocate:
    def test_budget_conserved(self):
        assert sum(_allocate(40, 1)) == 40
        assert sum(_allocate(40, 2)) == 40
        assert sum(_allocate(40, 3)) == 40

    def test_higher_rank_gets_larger_share(self):
        shares = _allocate(100, 3)
        assert shares[0] > shares[1] > shares[2] > 0

    def test_clamped_to_available_weights(self):
        shares = _allocate(10, 7)  # 超出权重表按 3 席截断
        assert len(shares) == 3 and sum(shares) == 10


class TestPlanCampaign:
    def test_empty_candidates_rejected(self):
        out = plan_campaign([], total_budget=10)
        assert not out["ok"] and "拒绝空跑" in out["errors"][0]

    def test_nonpositive_budget_rejected(self, two_candidates):
        out = plan_campaign(two_candidates, total_budget=0)
        assert not out["ok"]

    def test_topology_ranking_and_promotion(self, two_candidates):
        out = plan_campaign(two_candidates, total_budget=12, promote_top=1,
                            engine="surrogate", seed=42)
        assert out["ok"]
        ranked = out["layers"]["topology"]["ranked"]
        assert len(ranked) == 2
        promoted = [r for r in ranked if r["promoted"]]
        assert len(promoted) == 1
        # 按 rank 排序后分数降序、同分名字典序（确定性排序钉面）
        scored_rows = sorted((r for r in ranked if r["score"] is not None),
                             key=lambda r: r["rank"])
        scores = [r["score"] for r in scored_rows]
        assert scores == sorted(scores, reverse=True)
        assert [r["rank"] for r in scored_rows] == [1, 2]
        # L2 分派与预算份额
        runs = out["layers"]["params"]["runs"]
        assert len(runs) == 1 and runs[0]["name"] == promoted[0]["name"]
        assert runs[0]["budget_share"] == 12
        assert runs[0]["ok"]
        assert runs[0]["n_evaluations"] <= 12
        assert runs[0]["best_params"]

    def test_deterministic_same_seed_same_plan(self, two_candidates):
        a = plan_campaign(two_candidates, total_budget=10, promote_top=1,
                          seed=7)
        b = plan_campaign(two_candidates, total_budget=10, promote_top=1,
                          seed=7)
        assert json.dumps(a, sort_keys=True, default=str) == json.dumps(
            b, sort_keys=True, default=str)

    def test_promote_top_two_splits_budget(self, two_candidates):
        out = plan_campaign(two_candidates, total_budget=30, promote_top=2,
                            engine="surrogate", seed=42)
        runs = out["layers"]["params"]["runs"]
        assert len(runs) == 2
        shares = [r["budget_share"] for r in runs]
        assert sum(shares) == 30 and shares[0] > shares[1]

    def test_recipe_without_bounds_not_promoted(self, tmp_path,
                                                two_candidates):
        recipe = tmp_path / "no_bounds.yaml"
        recipe.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "objectives": [{"metric": "s11_db", "op": "max_below",
                            "value": -15}],
        }), encoding="utf-8")
        out = plan_campaign([*two_candidates,
                             {"name": "nope", "recipe_path": str(recipe)}],
                            total_budget=10, promote_top=1, seed=42)
        row = next(r for r in out["layers"]["topology"]["ranked"]
                   if r["name"] == "nope")
        assert row["score"] is None and not row["promoted"]
        assert "搜索空间" in row["reason"]

    def test_mcts_engine_grid_search(self, tmp_path):
        recipe = tmp_path / "grid.yaml"
        recipe.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "objectives": [{"metric": "s11_db", "op": "max_below",
                            "value": -20, "band": [2.0, 2.8]}],
            "optimization": {"params": {
                "arm_len_mm": {"low": 15.0, "high": 25.0}}},
        }), encoding="utf-8")
        out = plan_campaign([{"name": "grid", "recipe_path": str(recipe)}],
                            total_budget=16, engine="mcts", seed=3)
        assert out["ok"]
        run = out["layers"]["params"]["runs"][0]
        assert run["ok"] and run["engine"] == "mcts"
        assert run["n_evaluations"] <= 16
        lo, hi = 15.0, 25.0
        assert lo <= run["best_params"]["arm_len_mm"] <= hi


class TestEngineContracts:
    def test_surrogate_engine_search_shape(self, tmp_path):
        recipe = tmp_path / "s.yaml"
        recipe.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "objectives": [{"metric": "s11_db", "op": "max_below",
                            "value": -20, "band": [2.0, 2.8]}],
            "optimization": {"params": {
                "arm_len_mm": {"low": 15.0, "high": 25.0}}},
        }), encoding="utf-8")
        from rfauto.service.hierarchical_scheduler import (
            _recipe_evaluator,
            _recipe_view,
        )

        view = _recipe_view(str(recipe))
        from rfauto.core.objectives import Objective

        objectives = [Objective(**o) for o in view["objectives"]]
        out = SurrogateSearchEngine().search(
            bounds=view["bounds"], objectives=objectives,
            evaluate_fn=_recipe_evaluator(view), budget=8, seed=42)
        assert out["ok"] and out["n_evaluations"] <= 8
        assert 15.0 <= out["best_params"]["arm_len_mm"] <= 25.0

    def test_mcts_engine_levels_config(self):
        engine = MCTSGridSearchEngine(levels=1)
        assert engine.levels == 2  # 下限钳位
