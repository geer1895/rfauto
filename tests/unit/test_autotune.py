"""阶段 2.1：确定性 critique 自治环测试（fake sampler，零真机）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def recipe_path(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5}},
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
    path = tmp_path / "autotune_recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


def _fake_sampler_factory(valley_fn, rl_fn):
    """构造 fake sampler：metrics 由谷位+回损函数决定。"""

    def sampler(params: dict[str, float]) -> dict[str, float]:
        valley = valley_fn(params)
        rl = rl_fn(params)
        return {
            "metrics": {
                "s11_db_max_in_band": rl,
                "s21_db_mean_in_band": -3.3,
                "iso_s23_db_min_in_band": -30.0,
            },
            "valley_ghz": valley,
        }

    return sampler


class TestCritiquePoint:
    def test_pass_on_met_objectives(self):
        from rfauto.service.autotune_service import critique_point

        c = critique_point(
            {"s11_db_max_in_band": -20.0},
            [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
              "value": -15}],
            valley_ghz=2.4, current_params={"arm_len_mm": 18.1})
        assert c["verdict"] == "PASS"
        assert c["issues"] == []

    def test_freq_scale_fix_typed_and_bounded(self):
        from rfauto.service.autotune_service import critique_point

        # 谷位 1.6 vs 带中心 2.4：偏低 33% → 缩短臂长，且限步长 ±20%
        c = critique_point(
            {"s11_db_max_in_band": -20.0},
            [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
              "value": -15}],
            valley_ghz=1.6, bounds={"arm_len_mm": (12.0, 30.0)},
            current_params={"arm_len_mm": 20.0},
            f0_tolerance=0.15, max_step_pct=0.2)
        assert c["verdict"] == "FAIL"
        fixes = [f for f in c["fixes"] if f["kind"] == "freq_scale"]
        assert fixes, c
        f = fixes[0]
        # scale = 1/(1.6/2.4)=1.5 被限到 1.2 → 20*0.8=16（缩短方向）
        assert f["param"] == "arm_len_mm"
        assert f["value"] == pytest.approx(16.0, abs=1e-6)

    def test_valley_clamped_to_bounds(self):
        from rfauto.service.autotune_service import critique_point

        c = critique_point(
            {"s11_db_max_in_band": -20.0},
            [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
              "value": -15}],
            valley_ghz=1.0, bounds={"arm_len_mm": (18.0, 23.0)},
            current_params={"arm_len_mm": 20.0})
        f = next(x for x in c["fixes"] if x["kind"] == "freq_scale")
        assert f["value"] == 18.0  # 触底限界

    def test_rl_shallow_triggers_coord_probe(self):
        from rfauto.service.autotune_service import critique_point

        c = critique_point(
            {"s11_db_max_in_band": -5.0},
            [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
              "value": -15}],
            valley_ghz=2.4,  # 谷位准
            current_params={"arm_len_mm": 18.1, "series_w_mm": 0.35},
            rl_floor_db=-8.0)
        probes = [f for f in c["fixes"] if f["kind"] == "rl_probe"]
        assert probes and probes[0]["param"] == ["series_w_mm"]


class TestAutotuneLoop:
    def test_converges_when_frequency_fixed(self, recipe_path):
        """谷位准且 RL 达标 → 第 1 轮 PASS。"""
        from rfauto.service.autotune_service import autotune_loop

        sampler = _fake_sampler_factory(lambda p: 2.4, lambda p: -20.0)
        r = autotune_loop(recipe_path, sampler_fn=sampler, budget=3)
        assert r["ok"] and r["verdict"] == "PASS"
        assert r["rounds_used"] == 1

    def test_freq_correction_converges(self, recipe_path):
        """谷位偏低 → 长度缩放修正后第 2 轮 PASS。"""
        from rfauto.service.autotune_service import autotune_loop

        def valley(p):
            return 2.4 if p["arm_len_mm"] < 20.0 else 1.8

        sampler = _fake_sampler_factory(valley, lambda p: -20.0)
        r = autotune_loop(recipe_path, sampler_fn=sampler, budget=3)
        assert r["ok"] and r["verdict"] == "PASS"
        assert r["rounds_used"] <= 2

    def test_budget_exhausted_fail_honest(self, recipe_path):
        """无改进方向时如实 FAIL（不凑绿）。"""
        from rfauto.service.autotune_service import autotune_loop

        # RL 永远浅、且没有任何宽度参数可探测到改进 → 坐标探测无收益
        sampler = _fake_sampler_factory(lambda p: 2.4, lambda p: -5.0)
        r = autotune_loop(recipe_path, sampler_fn=sampler, budget=2,
                          rl_floor_db=-8.0)
        assert r["ok"] and r["verdict"] == "FAIL"
        assert r["history"], "FAIL 也必须留逐轮历史"

    def test_missing_recipe_rejected(self, tmp_path):
        from rfauto.service.autotune_service import autotune_loop

        assert not autotune_loop(tmp_path / "nope.yaml", budget=1)["ok"]


class TestAutotuneToSandbox:
    def test_final_params_land_in_draft(self, tmp_path, monkeypatch):
        """阶段 2.5：自治环 final_params 经沙箱草稿落地（不直接改真实配方）。"""
        import json as json_mod

        from rfauto.service.autotune_service import autotune_to_sandbox

        monkeypatch.chdir(tmp_path)
        run_id = "20260905_000000_test000"
        autotune_json = tmp_path / "runs" / run_id / "autotune.json"
        autotune_json.parent.mkdir(parents=True)
        autotune_json.write_text(json_mod.dumps({
            "verdict": "PASS",
            "final_params": {"arm_len_mm": 19.0, "series_w_mm": 0.35},
        }), encoding="utf-8")

        recipe = tmp_path / "r.yaml"
        recipe.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5}},
        }), encoding="utf-8")

        r = autotune_to_sandbox(recipe, run_id)
        assert r["ok"], r.get("errors")
        draft = Path(r["draft"])
        assert draft.exists()
        assert "sandbox" in str(draft)  # 写面只在沙箱内
        # 真实配方未被触碰
        real = yaml.safe_load(recipe.read_text(encoding="utf-8"))
        assert real["params"]["arm_len_mm"]["value"] == 20.5
        # 草稿里参数已更新
        draft_data = yaml.safe_load(draft.read_text(encoding="utf-8"))
        assert draft_data["params"]["arm_len_mm"]["value"] == 19.0

    def test_missing_run_rejected(self, tmp_path, monkeypatch):
        from rfauto.service.autotune_service import autotune_to_sandbox

        monkeypatch.chdir(tmp_path)
        recipe = tmp_path / "r.yaml"
        recipe.write_text("model: wilkinson_power_divider", encoding="utf-8")
        r = autotune_to_sandbox(recipe, "20260905_000000_nope000")
        assert not r["ok"]


class TestOrchestrateTournament:
    def test_ranks_variants_by_best_cost(self, recipe_path):
        """两个假设起点各自小预算自治环，cost 低者胜出（阶段 5.4）。"""
        from rfauto.service.autotune_service import orchestrate_tournament

        def factory(idx):
            def valley(p):
                return 2.4 if p["arm_len_mm"] < 20.0 else 1.8

            def rl(p):
                return -22.0 + idx * 3.0  # variant 0 更优

            return _fake_sampler_factory(valley, rl)

        r = orchestrate_tournament(
            recipe_path,
            [{"arm_len_mm": 19.0}, {"arm_len_mm": 21.0}],
            sampler_factory=factory, small_budget=2)
        assert r["ok"], r.get("errors")
        assert r["n_variants"] == 2
        assert r["winner"] is not None
        assert r["winner"]["variant_index"] == 0  # variant0 的 RL 更深 → cost 更低
        assert r["winner"]["best_cost"] <= r["trials"][1]["best_cost"]

    def test_empty_variants_rejected(self, recipe_path):
        from rfauto.service.autotune_service import orchestrate_tournament

        assert not orchestrate_tournament(recipe_path, [])["ok"]
