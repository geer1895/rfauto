"""Direction 1 mf_backend + Direction 8a synthesis engines tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


class TestHypervolumeContribution:
    """真独占超体积贡献（P1 修复：旧实现算单点盒体积，被支配点得正份额）。

    四点集口径：X=(0.5,3) Y=(3,0.5) W=(1.5,1.5) Z=(1,1)，ref=(4,4)，
    双目标 minimize——W 被 Z 支配，独占贡献恒 0；Z 的独占区域 = 其盒
    减去 X/Y/W 的盒 = 1.75，X/Y 各 0.5（去点法 HV(S)−HV(S∖i) 精确可验）。
    """

    def test_empty_points(self):
        from rfauto.optimization.mf_backend import hypervolume_contribution
        assert hypervolume_contribution([], {"a": "minimize"}) == []

    def test_single_point(self):
        from rfauto.optimization.mf_backend import hypervolume_contribution
        result = hypervolume_contribution(
            [{"a": 1.0, "b": 2.0}], {"a": "minimize", "b": "minimize"})
        assert len(result) == 1
        assert result[0] == 1.0  # only point gets full contribution

    def test_two_points_different_contribution(self):
        from rfauto.optimization.mf_backend import hypervolume_contribution
        result = hypervolume_contribution(
            [{"a": 1.0, "b": 3.0}, {"a": 3.0, "b": 1.0}],
            {"a": "minimize", "b": "minimize"})
        assert len(result) == 2
        assert result[0] == pytest.approx(result[1])  # 对称互不支配
        assert sum(result) == pytest.approx(1.0)

    def test_dominated_point_zero_exclusive_share(self):
        from rfauto.optimization.mf_backend import hypervolume_contribution
        pts = [{"x": 0.5, "y": 3.0}, {"x": 3.0, "y": 0.5},
               {"x": 1.5, "y": 1.5}, {"x": 1.0, "y": 1.0}]  # X, Y, W, Z
        shares = hypervolume_contribution(
            pts, {"x": "minimize", "y": "minimize"}, ref={"x": 4.0, "y": 4.0})
        # 旧实现返回 [0.082, 0.082, 0.317, 0.518]：被支配的 W 排第二
        assert shares[2] == pytest.approx(0.0)   # W（index 2）被支配 → 独占贡献 0
        assert shares[3] == pytest.approx(1.75 / 2.75)  # Z（index 3）最大份额
        assert shares[0] == pytest.approx(0.5 / 2.75)
        assert shares[1] == pytest.approx(0.5 / 2.75)
        assert sum(shares) == pytest.approx(1.0)

    def test_default_ref_never_inside_dominated_region(self):
        # 缺省 ref 对 dB 类负值指标不得收进支配域（旧 max*1.1 的坑）
        from rfauto.optimization.mf_backend import hypervolume_contribution
        pts = [{"x": -30.0, "y": -30.0}, {"x": -10.0, "y": -10.0}]
        shares = hypervolume_contribution(pts, {"x": "minimize", "y": "minimize"})
        # (−10,−10) 比 (−30,−30) 劣 → 被支配 → 份额 0
        assert shares[1] == pytest.approx(0.0)
        assert shares[0] == pytest.approx(1.0)

    def test_maximize_direction(self):
        from rfauto.optimization.mf_backend import hypervolume_contribution
        shares = hypervolume_contribution(
            [{"g": 1.0}, {"g": 5.0}], {"g": "maximize"})
        assert shares[1] == pytest.approx(1.0)  # maximize：值大者独占
        assert shares[0] == pytest.approx(0.0)

    def test_invalid_direction_rejected(self):
        from rfauto.optimization.mf_backend import hypervolume_contribution
        with pytest.raises(ValueError, match="maximize/minimize"):
            hypervolume_contribution([{"g": 1.0}], {"g": "smaller_better"})

    def test_missing_metric_key_rejected(self):
        from rfauto.optimization.mf_backend import hypervolume_contribution
        with pytest.raises(ValueError, match="缺指标键"):
            hypervolume_contribution([{"g": 1.0}],
                                     {"g": "minimize", "h": "minimize"})


class TestSelectTopK:
    def test_select_from_trials(self):
        from rfauto.optimization.mf_backend import select_top_k_by_hv
        trials = [
            {"params": {"x": 1}, "cost": 0.5, "metrics": {"s11_db_max_in_band": -15.0}},
            {"params": {"x": 2}, "cost": 0.3, "metrics": {"s11_db_max_in_band": -20.0}},
            {"params": {"x": 3}, "cost": 0.8, "metrics": {"s11_db_max_in_band": -10.0}},
        ]
        top = select_top_k_by_hv(trials, k=2,
                                 objectives={"s11_db_max_in_band": "minimize"})
        assert len(top) == 2
        assert all("_hv_contribution" in t for t in top)

    def test_empty_trials(self):
        from rfauto.optimization.mf_backend import select_top_k_by_hv
        assert select_top_k_by_hv([], k=5,
                                  objectives={"a": "minimize"}) == []

    def test_dominated_point_does_not_displace_pareto(self):
        # P1 修复：旧实现 W 份额 0.317 挤掉非支配点 Y；真独占贡献下
        # 选点面 = 非支配点
        from rfauto.optimization.mf_backend import select_top_k_by_hv
        trials = [
            {"params": {"p": "X"}, "metrics": {"a": 0.5, "b": 3.0}},
            {"params": {"p": "Y"}, "metrics": {"a": 3.0, "b": 0.5}},
            {"params": {"p": "W"}, "metrics": {"a": 1.5, "b": 1.5}},  # 被 Z 支配
            {"params": {"p": "Z"}, "metrics": {"a": 1.0, "b": 1.0}},
        ]
        top = select_top_k_by_hv(trials, k=3,
                                 objectives={"a": "minimize", "b": "minimize"})
        assert {t["params"]["p"] for t in top} == {"X", "Y", "Z"}

    def test_maximize_direction_selects_largest(self):
        from rfauto.optimization.mf_backend import select_top_k_by_hv
        trials = [
            {"params": {"x": 1}, "metrics": {"gain_db_max": 1.0}},
            {"params": {"x": 2}, "metrics": {"gain_db_max": 5.0}},
        ]
        top = select_top_k_by_hv(trials, k=1, objectives={"gain_db_max": "maximize"})
        assert top[0]["params"]["x"] == 2

    def test_trial_missing_objective_key_skipped(self):
        from rfauto.optimization.mf_backend import select_top_k_by_hv
        trials = [
            {"params": {"x": 1}, "metrics": {"a": 1.0}},                 # 缺 b
            {"params": {"x": 2}, "metrics": {"a": 1.0, "b": 2.0}},
        ]
        top = select_top_k_by_hv(trials, k=2,
                                 objectives={"a": "minimize", "b": "minimize"})
        assert len(top) == 1
        assert top[0]["params"]["x"] == 2

    def test_objectives_none_falls_back_to_cost_order(self):
        """objectives=None（配方目标无单调方向语义的回退，#105）→ 按 cost 升序。"""
        from rfauto.optimization.mf_backend import select_top_k_by_hv
        trials = [
            {"params": {"p": 2}, "metrics": {"a": 1.0}, "cost": 0.5},
            {"params": {"p": 1}, "metrics": {"a": 0.5}, "cost": 0.1},
            {"params": {"p": 3}, "metrics": {"a": 2.0}, "cost": 0.9},
        ]
        top = select_top_k_by_hv(trials, k=2, objectives=None)
        assert [t["params"]["p"] for t in top] == [1, 2]


class TestHvObjectivesFromRecipe:
    """配方 objectives → {指标键: 方向}（worst-case 键序，#195 口径）。"""

    def test_max_below_maps_minimize_on_measured_keys(self):
        from rfauto.optimization.mf_backend import _hv_objectives_from_recipe
        recipe = {"objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            {"metric": "s11_db_min", "band": [2.3, 2.5], "op": "max_below", "value": -40},
        ]}
        trials = [{"metrics": {"s11_db_max_in_band": -12.0,
                               "s11_db_min_in_band": -38.0}}]
        out = _hv_objectives_from_recipe(recipe, trials)
        assert out == {"s11_db_max_in_band": "minimize",
                       "s11_db_min_in_band": "minimize"}

    def test_min_above_maps_maximize(self):
        from rfauto.optimization.mf_backend import _hv_objectives_from_recipe
        recipe = {"objectives": [
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "min_above", "value": -3.5},
        ]}
        trials = [{"metrics": {"s21_db_mean_in_band": -3.0}}]
        assert _hv_objectives_from_recipe(recipe, trials) == {
            "s21_db_mean_in_band": "maximize"}

    def test_mean_within_rejected(self):
        from rfauto.optimization.mf_backend import _hv_objectives_from_recipe
        recipe = {"objectives": [
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "mean_within",
             "value": [-3.5, -3.0]}]}
        trials = [{"metrics": {"s21_db_mean_in_band": -3.2}}]
        with pytest.raises(ValueError, match="方向语义"):
            _hv_objectives_from_recipe(recipe, trials)

    def test_missing_product_key_rejected(self):
        from rfauto.optimization.mf_backend import _hv_objectives_from_recipe
        recipe = {"objectives": [
            {"metric": "iso_s23_db", "band": [2.3, 2.5], "op": "max_below", "value": -20}]}
        trials = [{"metrics": {"s11_db_max_in_band": -12.0}}]
        with pytest.raises(ValueError, match="不在 trial metrics"):
            _hv_objectives_from_recipe(recipe, trials)


class TestRunMultifidelity:
    """全链：Phase 2 必须真评估 Phase 1 选出的候选。"""

    def _recipe(self, tmp_path):
        import yaml
        recipe = {
            "model": "wilkinson_power_divider", "recipe_version": 1, "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15}],
            "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
        }
        path = tmp_path / "mf_recipe.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        return path

    def test_phase2_evaluates_enqueued_candidates(self, tmp_path):
        from rfauto.optimization.mf_backend import run_multifidelity
        result = run_multifidelity(str(self._recipe(tmp_path)),
                                   n_phase1=8, n_phase2=3, seed=42)
        assert result["ok"], result.get("errors")
        # Phase 2 评估的点 = Phase 1 top-k 的参数 → fidelity_delta 有配对
        assert len(result["phase2_results"]) >= 1
        assert result["fidelity_delta"]["n_matched_pairs"] >= 1
        # schema 对齐：S11_low/S11_high 字段在（方向 1 验收）
        delta = result["fidelity_delta"]
        assert "s11_low" in delta and "s11_high" in delta
        assert len(delta["s11_low"]) == len(delta["s11_high"]) == delta["n_matched_pairs"]
        assert result["hfss_count"] == len(result["phase2_results"])
        # P2⑤ 选点策略审计：result / fidelity_delta.json / meta.metrics
        # 三处同源（HV 可解析 → strategy=hypervolume）
        sel = result["phase2_selection"]
        assert sel["strategy"] == "hypervolume"
        assert sel["hv_objectives"] == {
            "s11_db_max_in_band": "minimize"}
        assert sel["fallback_reason"] is None
        assert sel["k"] == 3
        assert delta["phase2_selection"] == sel
        meta = json.loads((Path(result["run_dir"]) / "meta.json").read_text(
            encoding="utf-8"))
        assert meta["metrics"]["phase2_selection"] == sel

    def test_phase2_selection_fallback_when_hv_unavailable(self, tmp_path):
        """HV 目标不可解析（MEAN_WITHIN 无单调方向）→ 回退口径如实登记。"""
        import yaml

        from rfauto.optimization.mf_backend import run_multifidelity
        recipe = {
            "model": "wilkinson_power_divider", "recipe_version": 1, "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "mean_within", "value": [-40, -10]}],
            "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
        }
        path = tmp_path / "mf_recipe_fallback.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        result = run_multifidelity(str(path), n_phase1=8, n_phase2=2, seed=42)
        assert result["ok"], result.get("errors")
        sel = result["phase2_selection"]
        assert sel["strategy"] == "cost_ascending_fallback"
        assert sel["hv_objectives"] is None
        assert "mean_within" in (sel["fallback_reason"] or "")
        assert result["fidelity_delta"]["phase2_selection"] == sel


class TestFidelityDelta:
    def test_no_matched_pairs(self):
        from rfauto.optimization.mf_backend import compute_fidelity_delta
        result = compute_fidelity_delta([{"params": {"x": 1}, "cost": 0.5}],
                                        [{"params": {"x": 2}, "cost": 0.3}])
        assert result["rank_flip_count"] == 0
        assert result["n_matched_pairs"] == 0

    def test_matched_pair_no_flip(self):
        from rfauto.optimization.mf_backend import compute_fidelity_delta
        low = [{"params": {"x": 1}, "cost": 0.5, "metrics": {"s11_db_max_in_band": -15.0}},
               {"params": {"x": 2}, "cost": 0.3, "metrics": {"s11_db_max_in_band": -20.0}}]
        high = [{"params": {"x": 1}, "cost": 0.6, "metrics": {"s11_db_max_in_band": -14.0}},
                {"params": {"x": 2}, "cost": 0.2, "metrics": {"s11_db_max_in_band": -21.0}}]
        result = compute_fidelity_delta(low, high, seed=42)
        assert result["n_matched_pairs"] == 2
        assert result["rank_flip_count"] == 0  # order preserved

    def test_matched_pair_with_flip(self):
        from rfauto.optimization.mf_backend import compute_fidelity_delta
        low = [{"params": {"x": 1}, "cost": 0.3}, {"params": {"x": 2}, "cost": 0.5}]
        high = [{"params": {"x": 1}, "cost": 0.6}, {"params": {"x": 2}, "cost": 0.2}]
        result = compute_fidelity_delta(low, high)
        assert result["rank_flip_count"] == 1  # order reversed
        # A-05 行为不变钉：现调用链（trial 全带 cost）零跳过、翻转计数逐位不变
        assert result["rank_pairs_skipped_missing_cost"] == 0

    def test_missing_cost_is_explicit_skip_not_zero(self):
        """A-05（#117 邻形）：缺 cost 不再隐式按 0.0 参与排序比较——None 显式
        分支跳过该配对并如实计数（0.0 是合法最优值，隐式缺省会把缺失 trial
        伪装成完美点扭曲 rank_flip）。"""
        from rfauto.optimization.mf_backend import compute_fidelity_delta
        low = [{"params": {"x": 1}, "cost": 0.3},
               {"params": {"x": 2}}]                       # 整键缺失
        high = [{"params": {"x": 1}, "cost": 0.6},
                {"params": {"x": 2}, "cost": None}]        # 显式 None
        result = compute_fidelity_delta(low, high)
        assert result["n_matched_pairs"] == 2
        assert result["rank_flip_count"] == 0              # 只剩 1 对可比，无翻转
        assert result["rank_pairs_skipped_missing_cost"] == 1


class TestSynthesisWilkinson:
    def test_returns_valid_params(self):
        from rfauto.core.synthesis import synthesize_wilkinson
        result = synthesize_wilkinson(f0_ghz=2.4)
        assert result.model == "wilkinson_power_divider"
        assert "arm_len_mm" in result.params
        assert "series_w_mm" in result.params
        assert "shunt_w_mm" in result.params
        assert result.params["arm_len_mm"] > 0
        assert result.params["series_w_mm"] > 0
        assert result.params["shunt_w_mm"] > 0

    def test_arm_length_reasonable(self):
        from rfauto.core.synthesis import synthesize_wilkinson
        result = synthesize_wilkinson(f0_ghz=2.4)
        # lambda/4 at 2.4GHz on Rogers 4350B should be ~18-22mm
        assert 15 < result.params["arm_len_mm"] < 25

    def test_recipe_draft_complete(self):
        from rfauto.core.synthesis import synthesize_wilkinson
        result = synthesize_wilkinson(f0_ghz=2.4)
        draft = result.recipe_draft
        assert draft["model"] == "wilkinson_power_divider"
        assert draft["recipe_version"] == 1
        assert "objectives" in draft


class TestSynthesisBranchline:
    def test_returns_valid_params(self):
        from rfauto.core.synthesis import synthesize_branchline
        result = synthesize_branchline(f0_ghz=2.4)
        assert result.model == "branchline_coupler"
        assert result.params["arm_len_mm"] > 0
        # series arm should be wider than shunt (35.35ohm > 50ohm line)
        assert result.params["series_w_mm"] > result.params["shunt_w_mm"]


class TestSynthesisPatch:
    def test_returns_valid_params(self):
        from rfauto.core.synthesis import synthesize_patch
        result = synthesize_patch(f0_ghz=2.4)
        assert result.model == "patch_antenna"
        assert result.params["patch_len_mm"] > 0
        assert result.params["patch_w_mm"] > 0
        assert result.params["feed_offset_mm"] > 0

    def test_patch_wider_than_long(self):
        from rfauto.core.synthesis import synthesize_patch
        result = synthesize_patch(f0_ghz=2.4)
        # For er=3.66, W > L typically
        assert result.params["patch_w_mm"] > result.params["patch_len_mm"]


class TestSynthesisCLI:
    def test_syn_wilkinson_json(self, tmp_path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["syn", "wilkinson", "--f0", "2.4", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "params" in data
        assert data["model"] == "wilkinson_power_divider"

    def test_syn_branchline_json(self, tmp_path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["syn", "branchline", "--f0", "2.4", "--json"])
        assert result.exit_code == 0, result.output

    def test_syn_patch_json(self, tmp_path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["syn", "patch", "--f0", "2.4", "--json"])
        assert result.exit_code == 0, result.output
