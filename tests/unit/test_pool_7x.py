"""阶段 7.x 原型池测试：7.1 战役管理器 / 7.2 逆设计前滤波 / 7.3 MCTS /
7.6 可认证设计（全部确定性内核，真服务输出回验）。"""

from __future__ import annotations

import json

import pytest
import yaml


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
        "limits": {"max_trials": 20, "max_wall_hours": 4},
        "optimization": {"params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
            "shunt_w_mm": {"low": 0.90, "high": 1.30},
        }},
    }
    path = tmp_path / "r.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


@pytest.fixture
def samples_path(tmp_path):
    """二次型指标语料：s11 = -20 + 5(a-20)² + 10(s-0.35)²（最小 -20）。"""
    json.dumps({})  # 占位避免误用
    bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
    samples = []
    for i in range(12):
        a = 18.0 + i * (23.0 - 18.0) / 11
        s = 0.25 + (i % 4) * 0.0666
        s11 = -20.0 + 5.0 * (a - 20.0) ** 2 + 10.0 * (s - 0.35) ** 2
        samples.append({"params": {"arm_len_mm": round(a, 6),
                                   "series_w_mm": round(s, 6)},
                        "metrics": {"s11_db_max_in_band": round(s11, 6)}})
    data = {"bounds": bounds,
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "max_below", "value": -15}],
            "samples": samples}
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestCampaignManager:
    def test_plan_shape_and_order(self, recipe_path):
        from rfauto.service.campaign_manager import plan_campaign

        r = plan_campaign(recipe_path)
        assert r["ok"], r.get("errors")
        names = [s["stage"] for s in r["stages"]]
        assert names[0] == "calibrate" and "prefilter" in names
        assert r["stages"][-1]["adapter"] == "hfss"  # 终验压轴
        assert r["stages"][-1]["license_gated"] is True
        for s in r["stages"]:
            for d in s["depends_on"]:
                assert names.index(d) < names.index(s["stage"])  # 依赖无环

    def test_plan_requires_objectives(self, tmp_path):
        from rfauto.service.campaign_manager import plan_campaign

        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.safe_dump({"model": "wilkinson_power_divider"}),
                       encoding="utf-8")
        assert not plan_campaign(bad)["ok"]

    def test_events_state_machine(self, recipe_path):
        from rfauto.service.campaign_manager import apply_event, plan_campaign

        plan = plan_campaign(recipe_path)
        assert apply_event(plan, "calibrate", "stage_done")["ok"]
        assert plan["verdict"] == "RUNNING"
        r = apply_event(plan, "prefilter", "stage_failed", detail="ρ=0.3")
        assert r["ok"] and r["verdict"] == "ABORTED"
        status = {s["stage"]: s["status"] for s in plan["stages"]}
        assert status["prefilter"] == "failed"
        assert status["tune"] == "aborted"      # 死胡同下游自动放弃
        assert status["final_verify"] == "aborted"

    def test_save_plan(self, recipe_path, tmp_path):
        from rfauto.service.campaign_manager import plan_campaign, save_plan

        plan = plan_campaign(recipe_path)
        out = save_plan(plan, tmp_path / "camp")
        assert out.exists() and "campaign.plan.json" in out.name
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["model"] == "wilkinson_power_divider"


class TestInversePrefilter:
    def test_candidates_in_bounds_and_deterministic(self, recipe_path):
        from rfauto.service.inverse_prefilter import prefilter_candidates

        target = {"s11_db_max_in_band": -20.0}
        r1 = prefilter_candidates(recipe_path, target, n_corpus=24, k=4,
                                  seed=11)
        assert r1["ok"], r1.get("errors")
        assert len(r1["candidates"]) == 4
        bounds = {"arm_len_mm": (18.0, 23.0), "series_w_mm": (0.25, 0.45),
                  "shunt_w_mm": (0.90, 1.30)}
        for c in r1["candidates"]:
            for n, (lo, hi) in bounds.items():
                assert lo <= c["params"][n] <= hi, (n, c["params"])
        r2 = prefilter_candidates(recipe_path, target, n_corpus=24, k=4,
                                  seed=11)
        assert (r1["candidates"][0]["params"]
                == r2["candidates"][0]["params"])  # 同种子同结果

    def test_rejects_empty_target(self, recipe_path):
        from rfauto.service.inverse_prefilter import prefilter_candidates

        assert not prefilter_candidates(recipe_path, {})["ok"]


class TestMctsSearch:
    def test_search_improves_and_stays_in_bounds(self, samples_path):
        from rfauto.service.mcts_search import mcts_search

        r = mcts_search(samples_path, n_simulations=40, n_steps=4, seed=3)
        assert r["ok"], r.get("errors")
        assert r["best_cost_pred"] <= r["root_cost_pred"] + 1e-9  # 不劣化
        for n, v in r["best_params"].items():
            lo, hi = (18.0, 23.0) if n == "arm_len_mm" else (0.25, 0.45)
            assert lo - 1e-9 <= v <= hi + 1e-9, (n, v)

    def test_deterministic_same_seed(self, samples_path):
        from rfauto.service.mcts_search import mcts_search

        a = mcts_search(samples_path, n_simulations=20, n_steps=3, seed=5)
        b = mcts_search(samples_path, n_simulations=20, n_steps=3, seed=5)
        assert a["ok"] and b["ok"]
        assert a["best_params"] == b["best_params"]

    def test_rejects_thin_samples(self, tmp_path):
        from rfauto.service.mcts_search import mcts_search

        p = tmp_path / "thin.json"
        p.write_text(json.dumps({"bounds": {"a": [0, 1]}, "samples": []}),
                     encoding="utf-8")
        assert not mcts_search(p)["ok"]


class TestCertifyDesign:
    @pytest.fixture
    def linear_path(self, tmp_path):
        """线性指标语料：s11 = -15 + 2(a-20)。注意 ridge 收缩带偏置
        （实测二次语料中心偏差可达数 dB），故判定边界测试一律用线性
        语料 + 扫描法，不依赖个别点的拟合精度。"""
        bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
        samples = []
        for i in range(10):
            a = 18.0 + i * 5.0 / 9
            s = 0.25 + (i % 3) * 0.08
            samples.append({
                "params": {"arm_len_mm": round(a, 6), "series_w_mm": round(s, 6)},
                "metrics": {"s11_db_max_in_band": round(-15 + 2 * (a - 20), 6)}})
        data = {"bounds": bounds,
                "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                                "op": "max_below", "value": -15}],
                "samples": samples}
        path = tmp_path / "linear_samples.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_pass_deep_in_spec(self, linear_path):
        from rfauto.service.certify_design import certify_design

        r = certify_design(linear_path, {"arm_len_mm": 19.0,
                                         "series_w_mm": 0.35},
                           tolerance_pct=0.02)
        assert r["ok"], r.get("errors")
        s11 = next(c for c in r["certificates"] if c["metric"] == "s11_db")
        assert s11["verdict"] == "PASS" and r["verdict"] == "CERTIFIED"

    def test_fail_violated(self, linear_path):
        from rfauto.service.certify_design import certify_design

        r = certify_design(linear_path, {"arm_len_mm": 21.0,
                                         "series_w_mm": 0.35},
                           tolerance_pct=0.02)
        s11 = next(c for c in r["certificates"] if c["metric"] == "s11_db")
        assert s11["verdict"] == "FAIL" and r["verdict"] == "FAIL"

    def test_unknown_straddle_sweep(self, linear_path):
        """阈值穿越点附近细扫：区间横跨阈值 → UNKNOWN（不证明）。"""
        from rfauto.service.certify_design import certify_design

        verdicts = set()
        for i in range(11):
            a = 19.9 + i * 0.05
            r = certify_design(linear_path, {"arm_len_mm": round(a, 3),
                                             "series_w_mm": 0.35},
                               tolerance_pct=0.02)
            assert r["ok"], r.get("errors")
            verdicts.add(r["certificates"][0]["verdict"])
        assert "UNKNOWN" in verdicts

    def test_missing_axis_rejected(self, samples_path):
        from rfauto.service.certify_design import certify_design

        r = certify_design(samples_path, {"arm_len_mm": 20.0})
        assert not r["ok"]
