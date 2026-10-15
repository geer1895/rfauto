"""df7+ R3：AQE 分段重规划多保真路由测试（replan_service，零真机零网络）。

判据/决策表/成本模型阈值预声明于 runs/df7_r3aqe/criteria.md，本文件逐条对照
（对照表见 criteria §五）。隔离纪律：tmp_path 落盘 + chdir（#144，不污染真实
runs/）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


# ─── 测试语料工厂 ────────────────────────────────────────────────────────────

def _cost_points(values: list[float]) -> list[dict]:
    return [{"cost": v, "round": i} for i, v in enumerate(values)]


# ─── 值列提取优先级（criteria §一） ──────────────────────────────────────────

class TestCostExtraction:
    def test_priority_cost_beats_explicit_metric(self):
        from rfauto.service.replan_service import extract_cost_value

        p = {"cost": 1.5, "metrics": {"s11_db_min_in_band": -20.0,
                                      "cost": 9.9},
             "s11_db_min": -18.0}
        assert extract_cost_value(p) == (1.5, "cost")

    def test_explicit_statistic_beats_alias_and_fallback(self):
        from rfauto.service.replan_service import extract_cost_value

        p = {"metrics": {"s11_db_min_in_band": -20.0, "cost": 9.9},
             "s11_db_min": -18.0}
        assert extract_cost_value(p) == (-20.0, "metrics.s11_db_min_in_band")
        assert extract_cost_value({"s11_db_min": -18.0}) == (
            -18.0, "s11_db_min")
        assert extract_cost_value({"metrics": {"cost": 3.3}}) == (3.3,
                                                                  "metrics.cost")

    def test_bool_and_nonfinite_not_values(self):
        from rfauto.service.replan_service import extract_cost_value

        # True 不得被 float() 吃成 1.0（静默污染统计）
        assert extract_cost_value({"cost": True}) is None
        assert extract_cost_value({"cost": float("nan")}) is None
        assert extract_cost_value({"cost": float("inf")}) is None
        assert extract_cost_value({"cost": "2.0"}) is None


# ─── 退化判据（criteria §一） ────────────────────────────────────────────────

class TestAssessDegeneration:
    def test_constant_corpus_degenerate(self):
        """#195 指纹：带内 max 常数陷阱 = 精确常数（std=0）。"""
        from rfauto.service.replan_service import assess_cost_degeneration

        a = assess_cost_degeneration(_cost_points([2.0] * 5))
        assert a["ok"] is True
        assert a["degenerate"] is True
        assert a["evidence"]["std"] == 0.0
        assert a["evidence"]["rel_std"] == 0.0
        assert a["rules"]["A_rel_std"]["triggered"] is True
        assert a["evidence"]["unique_ratio"] == pytest.approx(0.2)

    def test_near_constant_corpus_degenerate(self):
        """#207 平底碗族：带内起伏 ≪5%。"""
        from rfauto.service.replan_service import assess_cost_degeneration

        a = assess_cost_degeneration(
            _cost_points([2.0, 2.01, 2.005, 2.008, 2.003]))
        assert a["degenerate"] is True
        assert a["evidence"]["rel_std"] < 0.05
        assert a["rules"]["A_rel_std"]["triggered"] is True
        assert a["rules"]["B_unique_ratio"]["triggered"] is False

    def test_duplicate_heavy_corpus_degenerate_via_rule_b(self):
        """判据 B：unique_ratio ≤ 0.5 且 rel_std 大（A 不触发）→ 仍退化。"""
        from rfauto.service.replan_service import assess_cost_degeneration

        a = assess_cost_degeneration(
            _cost_points([1.0, 1.0, 1.0, 2.0, 2.0, 9.0]))
        assert a["evidence"]["rel_std"] > 0.05
        assert a["evidence"]["unique_ratio"] == pytest.approx(0.5)
        assert a["rules"]["A_rel_std"]["triggered"] is False
        assert a["rules"]["B_unique_ratio"]["triggered"] is True
        assert a["degenerate"] is True

    def test_healthy_corpus_not_degenerate(self):
        from rfauto.service.replan_service import (
            COST_REL_STD_THRESHOLD,
            assess_cost_degeneration,
        )

        vals = [1.0, 2.2, 3.9, 5.1, 8.7]
        a = assess_cost_degeneration(_cost_points(vals))
        assert a["degenerate"] is False
        assert a["evidence"]["rel_std"] > COST_REL_STD_THRESHOLD
        assert a["evidence"]["unique_ratio"] == 1.0
        assert len(a["evidence"]["histogram"]) == 5
        assert sum(b["count"] for b in a["evidence"]["histogram"]) == len(vals)
        # 证据面数值自洽：min/max/unique 保序样本
        assert a["evidence"]["min"] == 1.0
        assert a["evidence"]["max"] == 8.7
        assert a["evidence"]["unique_values"] == vals

    def test_empty_and_single_point_ok_false(self):
        from rfauto.service.replan_service import assess_cost_degeneration

        for bad in ([], _cost_points([2.0])):
            a = assess_cost_degeneration(bad)
            assert a["ok"] is False
            assert a["degenerate"] is None
            assert a["errors"]

    def test_missing_values_counted_not_guessed(self):
        from rfauto.service.replan_service import assess_cost_degeneration

        pts = [{"cost": 1.0}, {"params": {"x": 1}}, {"metrics": {}},
               {"cost": 4.0}, {"cost": 9.0}]
        a = assess_cost_degeneration(pts)
        assert a["ok"] is True
        assert a["n"] == 3
        assert a["n_missing"] == 2

    def test_all_missing_ok_false(self):
        from rfauto.service.replan_service import assess_cost_degeneration

        a = assess_cost_degeneration(
            [{"params": {"x": 1}}, {}, {"metrics": None}])
        assert a["ok"] is False

    def test_mixed_value_sources_rejected(self):
        """#121：跨口径比较禁止——混合来源如实报不合并。"""
        from rfauto.service.replan_service import assess_cost_degeneration

        pts = [{"cost": 1.0}, {"cost": 2.0},
               {"metrics": {"s11_db_min_in_band": -20.0}}]
        a = assess_cost_degeneration(pts)
        assert a["ok"] is False
        assert any("混用" in e for e in a["errors"])

    def test_zero_mean_absolute_branch(self):
        """|mean| ≤ 1e-9 走绝对分支：全零常数 → 退化。"""
        from rfauto.service.replan_service import assess_cost_degeneration

        a = assess_cost_degeneration(_cost_points([0.0, 0.0, 0.0, 0.0]))
        assert a["ok"] is True
        assert a["evidence"]["rel_std"] is None
        assert a["degenerate"] is True
        assert a["rules"]["A_rel_std"]["triggered"] is True


# ─── 决策表（criteria §二，D1-D6 全覆盖） ────────────────────────────────────
class TestReplanRoute:
    def test_d1_hold_on_insufficient_assessment(self):
        from rfauto.service.replan_service import (
            assess_cost_degeneration,
            replan_route,
        )

        a = assess_cost_degeneration(_cost_points([1.0]))
        d = replan_route(a, {"stage": "fake_batch"})
        assert d["action"] == "hold"
        assert any("D1" in r for r in d["reasons"])

    def test_d2_escalate_on_first_batch_cost_model_true(self):
        from rfauto.service.replan_service import replan_route

        assessment = {"ok": True, "degenerate": False, "n": 8,
                      "value_source": "cost", "errors": []}
        d = replan_route(assessment, {
            "stage": "openems_first_batch",
            "cost_model": {"escalate": True, "benefit_multiple": 4.2},
        })
        assert d["action"] == "escalate_fidelity"
        assert any("D2" in r for r in d["reasons"])

    def test_d2_not_triggered_falls_through_to_d3(self):
        from rfauto.service.replan_service import replan_route

        assessment = {"ok": True, "degenerate": False, "n": 8,
                      "value_source": "cost", "errors": []}
        d = replan_route(assessment, {
            "stage": "openems_first_batch",
            "cost_model": {"escalate": False, "benefit_multiple": 0.4},
        })
        assert d["action"] == "proceed"
        assert any("D2 未触发" in r for r in d["reasons"])
        assert any("D3" in r for r in d["reasons"])

    def test_d3_proceed_on_healthy(self):
        from rfauto.service.replan_service import (
            assess_cost_degeneration,
            replan_route,
        )

        a = assess_cost_degeneration(_cost_points([1.0, 2.2, 3.9, 5.1, 8.7]))
        d = replan_route(a, {"stage": "fake_batch"})
        assert d["action"] == "proceed"
        assert any("D3" in r for r in d["reasons"])

    def test_d4_switch_metric_when_implicit_source_and_alternative(self):
        from rfauto.service.replan_service import (
            assess_cost_degeneration,
            replan_route,
        )

        a = assess_cost_degeneration(_cost_points([2.0] * 5))
        assert a["degenerate"] is True
        d = replan_route(a, {"stage": "fake_batch",
                             "metric_explicit_available": True})
        assert d["action"] == "switch_metric"
        assert any("D4" in r for r in d["reasons"])
        assert any("#195" in r for r in d["reasons"])

    def test_d5_switch_sampler_when_already_explicit(self):
        from rfauto.service.replan_service import (
            assess_cost_degeneration,
            replan_route,
        )

        pts = [{"metrics": {"s11_db_min_in_band": -30.0}} for _ in range(4)]
        a = assess_cost_degeneration(pts)
        assert a["value_source"] == "metrics.s11_db_min_in_band"
        d = replan_route(a, {"stage": "fake_batch",
                             "metric_explicit_available": True})
        assert d["action"] == "switch_sampler"
        assert any("D5" in r for r in d["reasons"])

    def test_d5_switch_sampler_when_no_explicit_alternative(self):
        from rfauto.service.replan_service import (
            assess_cost_degeneration,
            replan_route,
        )

        a = assess_cost_degeneration(_cost_points([2.0] * 5))
        d = replan_route(a, {"stage": "fake_batch"})  # 未声明显式替代
        assert d["action"] == "switch_sampler"
        assert any("D5" in r for r in d["reasons"])


# ─── 升保真一阶成本模型（criteria §三） ──────────────────────────────────────

class TestEscalateCostModel:
    def test_escalate_true_all_conditions_met(self):
        from rfauto.service.replan_service import escalate_cost_model

        r = escalate_cost_model(0.2, 100.0, 600.0, 10000.0)
        assert r["ok"] is True
        assert r["escalate"] is True
        ev = r["evidence"]
        assert ev["benefit_multiple"] == pytest.approx(2000.0 / 600.0)
        assert ev["n_affordable_hfss"] == 16
        assert all(ev["conditions"][k] is True
                   for k in ("error_floor", "gain_multiple", "affordable"))

    def test_error_floor_boundary_strict(self):
        """判据 1 严 >：恰在 0.05 不升（预声明边界语义）。"""
        from rfauto.service.replan_service import escalate_cost_model

        r = escalate_cost_model(0.05, 100.0, 600.0, 40000.0)
        assert r["evidence"]["conditions"]["error_floor"] is False
        assert r["escalate"] is False
        r2 = escalate_cost_model(0.06, 100.0, 600.0, 40000.0)
        assert r2["escalate"] is True

    def test_gain_multiple_boundary_inclusive(self):
        """判据 2 ≥ 宽松界：benefit_multiple 恰 3.0 判升。"""
        from rfauto.service.replan_service import (
            HFSS_GAIN_MULTIPLE,
            escalate_cost_model,
        )

        # err=0.06, budget=30000, hfss=600 → benefit=1800, multiple=3.0
        r = escalate_cost_model(0.06, 100.0, 600.0, 30000.0)
        assert r["evidence"]["benefit_multiple"] == pytest.approx(
            HFSS_GAIN_MULTIPLE)
        assert r["evidence"]["conditions"]["gain_multiple"] is True
        assert r["escalate"] is True
        r2 = escalate_cost_model(0.06, 100.0, 600.0, 15000.0)
        assert r2["evidence"]["conditions"]["gain_multiple"] is False
        assert r2["escalate"] is False

    def test_affordability_gate(self):
        """判据 3：n_affordable < 3 否决（即便收益倍数达标）。"""
        from rfauto.service.replan_service import escalate_cost_model

        # err=1.5, budget=1700, hfss=600 → n_affordable=2, multiple≈4.25
        r = escalate_cost_model(1.5, 100.0, 600.0, 1700.0)
        assert r["evidence"]["conditions"]["gain_multiple"] is True
        assert r["evidence"]["conditions"]["affordable"] is False
        assert r["escalate"] is False

    def test_guard_oe_cheaper_than_hfss(self):
        """路由矛盾守卫：hfss ≤ oe 直接否决。"""
        from rfauto.service.replan_service import escalate_cost_model

        r = escalate_cost_model(0.2, 100.0, 80.0, 10000.0)
        assert r["ok"] is True
        assert r["escalate"] is False
        assert any("守卫否决" in s for s in r["reasons"])

    def test_invalid_inputs_ok_false_no_crash(self):
        from rfauto.service.replan_service import escalate_cost_model

        for args in [(-0.1, 100.0, 600.0, 10000.0),
                     (0.2, -1.0, 600.0, 10000.0),
                     (0.2, 100.0, float("nan"), 10000.0),
                     (0.2, 100.0, 600.0, None)]:
            r = escalate_cost_model(*args)
            assert r["ok"] is False
            assert r["escalate"] is None
            assert r["errors"]
        # hfss_cost_s=0 单独报（除零守卫）
        r = escalate_cost_model(0.2, 100.0, 0.0, 10000.0)
        assert r["ok"] is False
        assert any("hfss_cost_s" in e for e in r["errors"])


# ─── checkpoint 一等对象（criteria §四，幂等重放） ───────────────────────────

class TestCheckpoint:
    def _decision(self) -> dict:
        return {
            "action": "switch_metric",
            "reasons": ["D4 switch_metric：value_source=cost 非显式统计量口径",
                        "触发证据：A_rel_std=rel_std=0.000000 < 阈值 0.05"],
            "stage": "fake_batch",
            "degenerate": True,
            "nested": {"bounds": [1.0, 2.0], "n": 5, "flag": False},
        }

    def test_round_trip_exact(self, tmp_path):
        from rfauto.service.replan_service import (
            load_replan_checkpoint,
            save_replan_checkpoint,
        )

        decision = self._decision()
        p = tmp_path / "ckpt.json"
        s = save_replan_checkpoint(p, decision)
        assert s["ok"] is True
        loaded = load_replan_checkpoint(p)
        assert loaded["ok"] is True
        assert loaded["decision"] == decision

    def test_idempotent_bytes(self, tmp_path):
        from rfauto.service.replan_service import (
            load_replan_checkpoint,
            save_replan_checkpoint,
        )

        decision = self._decision()
        p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
        save_replan_checkpoint(p1, decision)
        save_replan_checkpoint(p1, decision)  # 同路径重写
        d2 = load_replan_checkpoint(p1)["decision"]
        save_replan_checkpoint(p2, d2)  # load→save 回环
        assert p1.read_bytes() == p2.read_bytes()

    def test_str_and_path_inputs(self, tmp_path):
        from rfauto.service.replan_service import (
            load_replan_checkpoint,
            save_replan_checkpoint,
        )

        decision = self._decision()
        sp = str(tmp_path / "str_path.json")
        assert save_replan_checkpoint(sp, decision)["ok"] is True
        assert load_replan_checkpoint(sp)["decision"] == decision

    def test_missing_corrupt_and_schema_mismatch(self, tmp_path):
        from rfauto.service.replan_service import load_replan_checkpoint

        r = load_replan_checkpoint(tmp_path / "nope.json")
        assert r["ok"] is False
        assert r["errors"]

        bad = tmp_path / "corrupt.json"
        bad.write_text("{not json", encoding="utf-8")
        assert load_replan_checkpoint(bad)["ok"] is False

        wrong = tmp_path / "wrong.json"
        wrong.write_text(json.dumps({"schema": "other", "decision": {}}),
                         encoding="utf-8")
        r3 = load_replan_checkpoint(wrong)
        assert r3["ok"] is False
        assert any("schema" in e for e in r3["errors"])

        nodec = tmp_path / "nodec.json"
        nodec.write_text(json.dumps({"schema":
                                     "rfauto.replan_checkpoint"}),
                         encoding="utf-8")
        r4 = load_replan_checkpoint(nodec)
        assert r4["ok"] is False
        assert any("decision" in e for e in r4["errors"])


# ─── 接线零行为钉（autotune_loop opt-in，缺省关契约逐键不变） ────────────────

_RECIPE = {
    "model": "wilkinson_power_divider",
    "params": {"arm_len_mm": {"value": 24.0}},
    "setup": {"freq_range_ghz": [2.3, 2.5], "points": 41},
    "objectives": [
        {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
         "value": -15},
    ],
    "optimization": {"params": {
        "arm_len_mm": {"low": 12.0, "high": 30.0},
        "series_w_mm": {"low": 0.25, "high": 0.45},
        "shunt_w_mm": {"low": 0.90, "high": 1.30},
    }},
}

_BASELINE_KEYS = {"ok", "run_id", "run_dir", "verdict", "budget",
                  "rounds_used", "best", "final_params", "history",
                  "elapsed_s"}


def _fake_sampler(params: dict) -> dict:
    """metrics 恒定（cost 常数 = #195 陷阱语料），谷位随臂长频率尺度。"""
    valley = 2.4 * params["arm_len_mm"] / 20.5
    return {
        "metrics": {
            "s11_db_max_in_band": -6.0,
            "s21_db_mean_in_band": -3.3,
            "iso_s23_db_min_in_band": -30.0,
        },
        "valley_ghz": valley,
    }


class TestAutotuneLoopOptin:
    def _write_recipe(self, tmp_path) -> str:
        path = tmp_path / "autotune_recipe.yaml"
        path.write_text(yaml.safe_dump(_RECIPE), encoding="utf-8")
        return str(path)

    def test_default_path_zero_behavior(self, tmp_path):
        """缺省 replan_plan_path=None：结果契约逐键不变（零行为钉）。"""
        from rfauto.service.autotune_service import autotune_loop

        result = autotune_loop(self._write_recipe(tmp_path),
                               sampler_fn=_fake_sampler, budget=3)
        assert result["ok"] is True
        assert set(result) == _BASELINE_KEYS
        assert "replan_plan" not in result

    def test_optin_path_records_replan_and_checkpoint(self, tmp_path):
        """opt-in 开：fake 批产出即查，常数 cost 语料 → D5 switch_sampler。"""
        from rfauto.service.autotune_service import autotune_loop
        from rfauto.service.replan_service import load_replan_checkpoint

        ckpt = tmp_path / "replan" / "ckpt.json"
        result = autotune_loop(self._write_recipe(tmp_path),
                               sampler_fn=_fake_sampler, budget=3,
                               replan_plan_path=ckpt)
        assert result["ok"] is True
        # 环仍按既有语义收束（metrics 恒定 → 无确定性改进方向如实 FAIL）
        assert result["verdict"] == "FAIL"
        assert result["rounds_used"] == 3

        plan = result["replan_plan"]
        assert plan["assessment"]["ok"] is True
        assert plan["assessment"]["n"] == 3
        assert plan["assessment"]["degenerate"] is True  # 常数陷阱拦住
        assert plan["decision"]["action"] == "switch_sampler"
        assert plan["checkpoint"]["ok"] is True

        loaded = load_replan_checkpoint(ckpt)
        assert loaded["ok"] is True
        assert loaded["decision"] == plan["decision"]
