"""DP-13 Z2 单测——plan v1.1 shadow_points + 影子点选择器 + fidelity_shadow 联赛表。

判据（runs/df6_dp13/criteria.md §Z2）：
- plan v1.1：final_verify 阶段带 shadow_points 配置（n_points 硬帽=budget 5）；
- 旧 v1 plan 无 shadow_points 照常 load_plan/apply_event（读面零 schema 强制）；
- 影子点选择器：cost top_k + 归一化 max-min spread 补点；确定性（同输入逐字节
  同输出）；补不满如实 shortfall；预算不超名额；
- 联赛表：tmp 路径建表+SELECT+幂等重建行数不变；缺幂等键整行拒收；
  duckdb 缺失 ok=False 不 raise。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.service.campaign_manager import (
    FINAL_VERIFY_BUDGET,
    apply_event,
    load_plan,
    plan_campaign,
    save_plan,
    select_shadow_points,
)
from rfauto.service.db_service import (
    LEAGUE_COLUMNS,
    query_fidelity_shadow,
    record_fidelity_shadow,
)


@pytest.fixture
def sample_recipe(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5}},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


class TestPlanShadowPoints:
    def test_plan_v11_final_verify_has_shadow_points(self, sample_recipe):
        plan = plan_campaign(sample_recipe)
        assert plan["ok"] is True
        assert plan["campaign_schema"] == "rfauto-campaign-plan-v1.1"
        verify = next(s for s in plan["stages"]
                      if s["stage"] == "final_verify")
        sp = verify["shadow_points"]
        assert sp["n_points"] == 3
        assert sp["top_k"] == 1
        assert sp["min_norm_dist"] == pytest.approx(0.3)
        assert sp["status"] == "pending"
        # 预算不超名额：n_points ≤ final_verify budget
        assert sp["n_points"] <= verify["budget"] == FINAL_VERIFY_BUDGET

    def test_shadow_points_capped_at_budget(self, sample_recipe):
        plan = plan_campaign(sample_recipe, shadow_points=99)
        verify = next(s for s in plan["stages"]
                      if s["stage"] == "final_verify")
        assert verify["shadow_points"]["n_points"] == FINAL_VERIFY_BUDGET
        assert verify["shadow_points"]["capped"] is True

    def test_shadow_points_explicit_zero_disables(self, sample_recipe):
        plan = plan_campaign(sample_recipe, shadow_points=0)
        verify = next(s for s in plan["stages"]
                      if s["stage"] == "final_verify")
        assert verify["shadow_points"]["n_points"] == 0

    def test_legacy_v1_plan_without_field_still_loads(
            self, tmp_path, sample_recipe):
        """旧 v1 plan 无 shadow_points 字段照常 load/apply（v1→v1.1 兼容）。"""
        plan = plan_campaign(sample_recipe)
        legacy = dict(plan)
        legacy["campaign_schema"] = "rfauto-campaign-plan-v1"
        legacy["stages"] = [
            {k: v for k, v in s.items() if k != "shadow_points"}
            for s in plan["stages"]]
        out = save_plan(legacy, tmp_path / "camp_legacy")
        loaded = load_plan(out)
        assert loaded["ok"] is True
        verify = next(s for s in loaded["plan"]["stages"]
                      if s["stage"] == "final_verify")
        assert "shadow_points" not in verify  # 旧 plan 无该字段
        ev = apply_event(loaded["plan"], "final_verify", "stage_done")
        assert ev["ok"] is True
        assert next(s["status"] for s in ev["plan"]["stages"]
                    if s["stage"] == "final_verify") == "done"


class TestSelectShadowPoints:
    def _pts(self) -> list[dict]:
        return [
            {"params": {"x": 0.0, "y": 0.0}, "cost": 0.01},
            {"params": {"x": 1.0, "y": 1.0}, "cost": 0.20},
            {"params": {"x": 0.5, "y": 0.5}, "cost": 0.10},
            {"params": {"x": 0.9, "y": 0.9}, "cost": 0.30},
            {"params": {"x": 0.1, "y": 0.0}, "cost": 0.05},
        ]

    def test_top_then_spread_fill(self):
        r = select_shadow_points(self._pts(), n_points=3, top_k=1,
                                 min_norm_dist=0.3)
        assert r["ok"] and r["n_selected"] == 3 and r["shortfall"] == 0
        # top：cost 最小者必选
        assert r["selected"][0]["cost"] == 0.01
        # spread：第二点是候选集中离 top 最远者 (1,1)
        assert r["selected"][1]["params"] == {"x": 1.0, "y": 1.0}

    def test_min_norm_dist_gate_shortfall_honest(self):
        # 候选集中除 top 外全部挤在 top 附近（<0.3，按显式绝对 bounds 归一）
        # → 如实 shortfall 不硬凑（缺省候选集 min/max 自归一会把任何
        # 两点拉满 [0,1]——调用方应传 tune 阶段搜索空间 bounds）
        pts = [
            {"params": {"x": 0.5}, "cost": 0.01},
            {"params": {"x": 0.52}, "cost": 0.10},
            {"params": {"x": 0.55}, "cost": 0.20},
        ]
        r = select_shadow_points(pts, n_points=3, top_k=1,
                                 min_norm_dist=0.3,
                                 bounds={"x": (0.0, 1.0)})
        assert r["ok"] and r["n_selected"] == 1 and r["shortfall"] == 2

    def test_top_k_multiple(self):
        r = select_shadow_points(self._pts(), n_points=4, top_k=2,
                                 min_norm_dist=0.0)
        assert r["n_selected"] == 4
        assert [p["cost"] for p in r["selected"][:2]] == [0.01, 0.05]

    def test_determinism_and_tie_break(self):
        pts = [*self._pts(),
               {"params": {"x": 0.2, "y": 0.2}, "cost": 0.10}]  # 同 cost 平局
        r1 = select_shadow_points(pts, n_points=3)
        r2 = select_shadow_points(list(reversed(pts)), n_points=3)
        # 同集合（顺序不同）逐字节同输出：选择序由 cost+规范键序决定
        assert [p["params"] for p in r1["selected"]] == \
            [p["params"] for p in r2["selected"]]

    def test_empty_and_invalid(self):
        r0 = select_shadow_points([], n_points=3)
        assert r0["ok"] and r0["n_selected"] == 0 and r0["shortfall"] == 3
        bad = select_shadow_points(self._pts(), n_points=0)
        assert bad["ok"] is False and bad["errors"]

    def test_never_exceeds_budget_semantics(self):
        r = select_shadow_points(self._pts(), n_points=99)
        assert r["n_selected"] <= 5  # 候选只有 5 个，绝不硬凑


class TestFidelityShadowLeague:
    def _rows(self, run_id="run_a"):
        return [
            {"engine": "openems", "template_family": "mline",
             "params_hash": "abc123", "delta_vs_hfss_db": 0.42,
             "wall_s": 905.0, "mesh_mm": 0.5, "run_id": run_id},
            {"engine": "openems", "template_family": "wilkinson",
             "params_hash": "def456", "delta_vs_hfss_db": -0.11,
             "wall_s": 1200.5, "mesh_mm": 0.45, "run_id": run_id},
        ]

    def test_create_select_idempotent_rebuild(self, tmp_path):
        db = tmp_path / "league.duckdb"
        r1 = record_fidelity_shadow(self._rows(), db)
        assert r1["ok"] is True
        assert r1["n_rows_written"] == 2 and r1["n_rows_total"] == 2
        # 幂等重建：同批重跑行数不变
        r2 = record_fidelity_shadow(self._rows(), db)
        assert r2["ok"] is True and r2["n_rows_total"] == 2
        # 不同 run_id 追加：行数增长
        r3 = record_fidelity_shadow(self._rows("run_b"), db)
        assert r3["n_rows_total"] == 4
        q = query_fidelity_shadow(db)
        assert q["ok"] is True and q["n_rows"] == 4
        assert set(q["rows"][0]) == {c for c, _ in LEAGUE_COLUMNS}
        qf = query_fidelity_shadow(db, run_id="run_b")
        assert qf["n_rows"] == 2
        assert all(row["run_id"] == "run_b" for row in qf["rows"])
        qe = query_fidelity_shadow(db, engine="hfss")
        assert qe["ok"] is True and qe["n_rows"] == 0

    def test_rows_missing_key_rejected(self, tmp_path):
        db = tmp_path / "league.duckdb"
        bad = [{"engine": "openems", "template_family": "mline",
                "delta_vs_hfss_db": 0.1}]  # 缺 params_hash/run_id
        r = record_fidelity_shadow([*bad, *self._rows()], db)
        assert r["ok"] is True
        assert r["n_rows_rejected"] == 1 and r["rejected_indexes"] == [0]
        assert r["n_rows_written"] == 2

    def test_duckdb_missing_honest_no_raise(self, tmp_path, monkeypatch):
        db = tmp_path / "league.duckdb"
        monkeypatch.setitem(sys.modules, "duckdb", None)  # import → ImportError
        r = record_fidelity_shadow(self._rows(), db)
        assert r["ok"] is False and "duckdb" in r["reason"]
        q = query_fidelity_shadow(db)
        assert q["ok"] is False and "duckdb" in q["reason"]

    def test_missing_db_honest(self, tmp_path):
        q = query_fidelity_shadow(tmp_path / "nope.duckdb")
        assert q["ok"] is False and "不存在" in q["reason"]
