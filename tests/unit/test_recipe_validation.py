"""配方键级白名单校验测试（aurora_n 旅程席 A，F-P1-1）。

单源：rfauto/service/recipe_validation.py（RECIPE_TOP_LEVEL_KEYS /
did_you_mean / recipe_schema_errors）；消费通道 service/api/run_core.py::
validate_recipe（CLI validate / run·tune·sweep --dry-run / MCP validate_recipe /
UI recipe_save / batch validate 六通道同源）。

错误形态探针素材：runs/aurora_n/journey_recon/_typo_*.yaml（审计席证据，
本文件以行内 dict 等价复刻，避免测试依赖 runs/ 证据区）。
"""

from __future__ import annotations

from pathlib import Path

import yaml


def _legal_wilkinson() -> dict:
    """与 recipes/wilkinson_pd_v1.yaml 同构的最小合法配方（全键形态）。"""
    return {
        "model": "wilkinson_power_divider",
        "recipe_version": 1,
        "schema_version": 1,
        "notes": "2.4GHz 等分 Wilkinson",
        "params": {
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "z0_ohm": {"value": 50, "unit": "ohm"},
            "substrate": "rogers4350b_h0.508",
            "division": "1:1",
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.33},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 401},
        "ops": [],
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "mean_within",
             "value": [-3.6, -3.1]},
            {"metric": "iso_s23_db", "band": [2.3, 2.5], "op": "min_above",
             "value": 20},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            },
        },
        "limits": {"max_trials": 60, "max_wall_hours": 12},
        "export": {"touchstone": {"renorm_ohm": 50, "deembed": False}},
    }


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "recipe.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _validate(tmp_path: Path, data: dict) -> dict:
    from rfauto.service.api import validate_recipe

    return validate_recipe(_write(tmp_path, data))


class TestTopLevelKeyWhitelist:
    def test_typo_top_level_key_rejected_with_did_you_mean(self, tmp_path):
        """①objectves 拼写错 → error + did-you-mean（旧码静默放行=空目标优化）。"""
        data = _legal_wilkinson()
        data["objectves"] = data.pop("objectives")
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        assert any("未知顶层键: objectves" in e and "objectives" in e
                   for e in r["errors"]), r["errors"]

    def test_far_off_key_rejected_without_hint(self, tmp_path):
        data = _legal_wilkinson()
        data["zzz_completely_unrelated"] = 1
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        (err,) = [e for e in r["errors"] if "zzz_completely_unrelated" in e]
        assert "你是不是想写" not in err  # 远键无接近候选 → 不臆造提示

    def test_all_whitelisted_keys_pass(self, tmp_path):
        """白名单全键形态（含 tolerance/units/design_name）零 error。"""
        data = _legal_wilkinson()
        data["tolerance"] = {"tolerances": {"arm_len_mm": 0.1}}
        data["units"] = "mm"
        data["design_name"] = "MyDesign"
        r = _validate(tmp_path, data)
        assert r["ok"] is True, r["errors"]

    def test_required_keys_still_enforced(self, tmp_path):
        r = _validate(tmp_path, {"model": "wilkinson_power_divider"})
        assert r["ok"] is False
        assert any("params" in e for e in r["errors"])


class TestParamNameWhitelist:
    def test_typo_param_rejected_in_params_and_optimization(self, tmp_path):
        """②arm_len_mm_typo（params + optimization.params 双段）→ did-you-mean。"""
        data = _legal_wilkinson()
        data["params"]["arm_len_mm_typo"] = {"value": 20.5}
        data["optimization"]["params"]["arm_len_mm_typo"] = {"low": 18, "high": 23}
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        hits = [e for e in r["errors"] if "arm_len_mm_typo" in e]
        assert len(hits) == 2, r["errors"]
        assert all("arm_len_mm" in e for e in hits)

    def test_param_surface_is_per_model(self, tmp_path):
        """patch 参数写进 wilkinson 配方 → 拦（跨模型混写静默忽略就此堵住）。"""
        data = _legal_wilkinson()
        data["params"]["patch_len_mm"] = {"value": 40.0}
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        assert any("patch_len_mm" in e for e in r["errors"])

    def test_unknown_model_skips_param_surface_no_double_report(self, tmp_path):
        """模型未知：已有"未知模型"error，参数面跳过（不重复报、不误伤）。"""
        data = _legal_wilkinson()
        data["model"] = "ghost_model"
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        assert any("未知模型" in e for e in r["errors"])
        assert not any("未知参数" in e for e in r["errors"])

    def test_non_dict_params_rejected(self, tmp_path):
        data = _legal_wilkinson()
        data["params"] = ["arm_len_mm"]
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        assert any("params 必须是映射" in e for e in r["errors"])


class TestMetricNameWhitelist:
    def test_typo_metric_rejected_with_did_you_mean(self, tmp_path):
        """③s11_db_typo → error + did-you-mean（旧码求解评估期才炸）。"""
        data = _legal_wilkinson()
        data["objectives"][0]["metric"] = "s11_db_typo"
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        (err,) = [e for e in r["errors"] if "s11_db_typo" in e]
        assert "未知指标名" in err and "s11_db" in err

    def test_constraint_metric_whitelisted_too(self, tmp_path):
        data = _legal_wilkinson()
        data["optimization"]["constraints"] = [
            {"metric": "iso_s32_db_typo", "band": [2.3, 2.5],
             "op": "min_above", "value": 20},
        ]
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        assert any("optimization.constraints[0]" in e and "iso_s32_db_typo" in e
                   for e in r["errors"])

    def test_all_documented_metrics_pass(self, tmp_path):
        from rfauto.core.objectives import OBJECTIVE_METRIC_NAMES

        for metric in sorted(OBJECTIVE_METRIC_NAMES):
            data = _legal_wilkinson()
            data["objectives"] = [
                {"metric": metric, "band": [2.3, 2.5], "op": "max_below",
                 "value": -15},
            ]
            r = _validate(tmp_path, data)
            assert r["ok"] is True, (metric, r["errors"])


class TestEmptyObjectives:
    def test_present_but_empty_rejected(self, tmp_path):
        """④objectives 在场但为空 → error（无目标=必然无意义）。"""
        data = _legal_wilkinson()
        data["objectives"] = []
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        assert any("objectives 为空" in e for e in r["errors"])

    def test_absent_objectives_ok_plain_run(self, tmp_path):
        """缺席合法：plain run 只出 S 参数/指标（语义与旧 "objectives: []" 等价）。"""
        data = _legal_wilkinson()
        del data["objectives"]
        del data["optimization"]
        r = _validate(tmp_path, data)
        assert r["ok"] is True, r["errors"]

    def test_null_objectives_clean_error_not_crash(self, tmp_path):
        """objectives: null → 干净 error（旧码 enumerate(None) 裸 TypeError）。"""
        data = _legal_wilkinson()
        data["objectives"] = None
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        assert any("objectives 为空值" in e for e in r["errors"])

    def test_non_dict_objective_element_falls_to_pydantic(self, tmp_path):
        data = _legal_wilkinson()
        data["objectives"] = ["not-a-dict"]
        r = _validate(tmp_path, data)
        assert r["ok"] is False
        assert any("objectives[0] 校验失败" in e for e in r["errors"])


class TestChannelParity:
    def test_dry_run_rejects_typo_recipe(self, tmp_path):
        """run/tune --dry-run 与 validate 同源（api.dry_run 消费同一校验）。"""
        from rfauto.service.api import dry_run

        data = _legal_wilkinson()
        data["objectves"] = data.pop("objectives")
        r = dry_run(_write(tmp_path, data), adapter_name="fake")
        assert r["ok"] is False
        assert any("objectves" in e for e in r["errors"])

    def test_ui_recipe_save_rejects_unknown_param_crafted_file(self, tmp_path, monkeypatch):
        """UI recipe_save 通道同严（非受保护路径直写）；存量未知参数配方在
        保存链上被 validate 拦截——CLI/UI 严格度倒挂修齐的行为面证据。"""
        monkeypatch.chdir(tmp_path)
        from rfauto.service.ui_service import recipe_save

        path = _write(tmp_path, _legal_wilkinson())
        path.write_text(
            yaml.safe_dump({**_legal_wilkinson(),
                            "params": {**_legal_wilkinson()["params"],
                                       "arm_len_mm_typo": {"value": 1.0}}}),
            encoding="utf-8")
        r = recipe_save(path, {"params": {"arm_len_mm": 22.0}})
        assert r["ok"] is False
        assert any("arm_len_mm_typo" in e for e in r["errors"])

    def test_batch_validate_flags_typo(self, tmp_path):
        from rfauto.service.batch_ops_service import validate_recipes_batch

        d = tmp_path / "d"
        d.mkdir()
        good = d / "good.yaml"
        good.write_text(
            yaml.safe_dump(_legal_wilkinson(), allow_unicode=True),
            encoding="utf-8")
        bad_data = _legal_wilkinson()
        bad_data["objectves"] = bad_data.pop("objectives")
        bad = d / "bad.yaml"
        bad.write_text(yaml.safe_dump(bad_data), encoding="utf-8")
        r = validate_recipes_batch(str(d))
        assert r["ok_all"] is False
        assert Path(good).name in " ".join(r["passed"])
        assert any("objectves" in e
                   for f in r["results"] for e in f["errors"])


class TestDidYouMeanSingleSource:
    def test_deterministic(self):
        from rfauto.service.recipe_validation import did_you_mean

        assert did_you_mean("objectves", ["objectives", "ops"]) == \
            did_you_mean("objectves", ["objectives", "ops"])
        assert "'objectives'" in did_you_mean("objectves", ["objectives", "ops"])
        assert did_you_mean("zzz", ["objectives"]) == ""

    def test_helper_module_is_the_single_implementation(self):
        """run_core 不自带 difflib 实现（单源红线：一次实现多处用）。"""
        import inspect

        from rfauto.service.api import run_core

        assert "get_close_matches" not in inspect.getsource(run_core)
