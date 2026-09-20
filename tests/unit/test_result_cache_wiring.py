"""P2①（§10.20 ⑨ 生产接线）：内容寻址 ResultCache 接入 api.run_once / dry_run /
optimizer.build_objective 主路径。

验收口径（result-cache 内容键）：
- 同几何不同 study 二次评估命中且 provenance=cache（run_once 与优化外环两条路径）；
- RFAUTO_CACHE=off 旁路回归不破（两路径均恒真跑）；
- 四类失效策略（recipe_version / schema_version / mesh_params / adapter_version）
  经生产派生 components_for_run 仍各自触发 miss 并给 why_miss；
- #106：recipe_version（配方文档 schema）与 schema_version（插件参数 schema）
  分列——各自改动独立换键，互不顶替。

纪律：全部 fake 适配器、零网络；优化环测试 chdir 隔离（#144）防污染真实 runs/。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rfauto.infra.result_cache import (
    CONTENT_KEY_FIELDS,
    INVALIDATION_REASONS,
    PROVENANCE_CACHE,
    PROVENANCE_COMPUTED,
    UNVERSIONED_RECIPE_VERSION,
    ResultCache,
)

RECIPE_SRC = Path(__file__).parent.parent.parent / "recipes" / "wilkinson_pd_v1.yaml"


# ─── 公共 fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_cwd(tmp_path, monkeypatch):
    """chdir 隔离（#144）：run_once/优化环往 cwd 写 runs/ 与 .rfauto_cache/。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RFAUTO_CACHE", raising=False)
    return tmp_path


@pytest.fixture
def recipe_path(isolated_cwd):
    dst = isolated_cwd / "recipe.yaml"
    shutil.copy2(RECIPE_SRC, dst)
    return dst


@pytest.fixture
def opt_recipe(isolated_cwd, monkeypatch):
    """最小 Wilkinson 优化配方 + 临时 optuna storage（与 test_optimization 同款隔离）。"""
    db_dir = isolated_cwd / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path",
        lambda: f"sqlite:///{(db_dir / 'optuna.db').as_posix()}",
    )

    def _write(name: str = "opt_recipe.yaml", **overrides):
        recipe = {
            "model": "wilkinson_power_divider",
            "recipe_version": 1,
            "schema_version": 1,
            "params": {
                "f0_ghz": {"value": 2.4, "unit": "GHz"},
                "z0_ohm": {"value": 50, "unit": "ohm"},
                "substrate": "rogers4350b_h0.508",
                "division": "1:1",
                "arm_len_mm": {"value": 20.5},
                "series_w_mm": {"value": 0.33},
                "shunt_w_mm": {"value": 1.10},
            },
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
            "optimization": {"params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            }},
        }
        for k, v in overrides.items():
            if isinstance(v, dict) and isinstance(recipe.get(k), dict):
                recipe[k] = {**recipe[k], **v}
            else:
                recipe[k] = v
        path = isolated_cwd / name
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        return path

    return _write


def _count_fake_solves(monkeypatch) -> dict:
    from rfauto.adapters.fake_adapter import FakeAdapter

    calls = {"n": 0}
    orig = FakeAdapter.solve

    def counting(self, *a, **k):
        calls["n"] += 1
        return orig(self, *a, **k)

    monkeypatch.setattr(FakeAdapter, "solve", counting)
    return calls


def _count_fake_adapters(monkeypatch) -> list:
    from rfauto.adapters import fake_adapter as fa_mod

    created: list[int] = []
    real_init = fa_mod.FakeAdapter.__init__

    def counting_init(self, *args, **kwargs):
        created.append(1)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(fa_mod.FakeAdapter, "__init__", counting_init)
    return created


# ─── run_once：跨 study 命中 provenance=cache ────────────────────────────────


class TestRunOnceCrossStudy:
    def test_same_geometry_other_study_hits_with_provenance_cache(
        self, recipe_path, monkeypatch,
    ):
        from rfauto.service.api import run_once

        created = _count_fake_adapters(monkeypatch)

        first = run_once(recipe_path, study="study_A", seed="7")
        assert first["ok"], first.get("errors")
        assert first["from_cache"] is False
        assert first["cache"]["provenance"] == PROVENANCE_COMPUTED
        assert first["cache"]["requester_study"] == "study_A"
        assert len(created) == 1

        second = run_once(recipe_path, study="study_B", seed="99")
        assert second["ok"], second.get("errors")
        assert second["from_cache"] is True, "同几何异 study 必须命中"
        info = second["cache"]
        assert info["provenance"] == PROVENANCE_CACHE
        assert info["cross_study"] is True
        assert info["origin_study"] == "study_A"
        assert info["origin_seed"] == "7"
        assert info["requester_study"] == "study_B"
        assert info["key"] == first["cache"]["key"], "study 不进键：两次 key 相同"
        assert len(created) == 1, "命中不得再建适配器（C5 键检查前移不破）"
        # 命中侧指标与真跑一致（同 Touchstone 确定性复算）
        assert second["metrics"] == first["metrics"]

    def test_manifest_records_components_and_provenance(self, recipe_path):
        from rfauto.service.api import run_once

        res = run_once(recipe_path, study="study_A", seed="7")
        assert res["ok"], res.get("errors")
        cache = ResultCache()
        manifest = cache.read_manifest(res["cache"]["key"])
        assert manifest is not None
        assert manifest["provenance"] == PROVENANCE_COMPUTED
        assert manifest["study"] == "study_A" and manifest["seed"] == "7"
        assert manifest["model"] == "wilkinson_power_divider"
        comps = manifest["components"]
        assert set(comps) == set(CONTENT_KEY_FIELDS)
        assert comps["model_name"] == "wilkinson_power_divider"
        assert comps["adapter_version"] == "fake"
        assert comps["aedt_version"] == "fake"
        assert comps["plugin_version"] == "schema1"
        assert comps["export_contract_hash"], "run_once 契约哈希须非空"
        assert comps["params_canonical_json"].startswith("{")
        # meta.json 与返回值同源
        meta = json.loads((Path(res["run_dir"]) / "meta.json").read_text(encoding="utf-8"))
        assert meta["cache"]["key"] == res["cache"]["key"]
        assert meta["cache"]["provenance"] == PROVENANCE_COMPUTED

    def test_objectives_change_keeps_hit(self, recipe_path, monkeypatch):
        """Touchstone 与目标无关：只改 objectives 仍命中（异目标 study 合法复用）。"""
        from rfauto.service.api import run_once

        calls = _count_fake_solves(monkeypatch)
        first = run_once(recipe_path, study="A")
        assert first["ok"] and calls["n"] == 1

        data = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
        data["objectives"][0]["value"] = -12
        recipe_path.write_text(yaml.safe_dump(data), encoding="utf-8")

        second = run_once(recipe_path, study="B")
        assert second["ok"], second.get("errors")
        assert second["from_cache"] is True
        assert calls["n"] == 1, "只改目标不得触发真跑"
        assert second["cache"]["key"] == first["cache"]["key"]

    def test_default_scope_is_backward_compatible(self, recipe_path):
        """无 study/seed（历史调用方式）照常命中，cross_study=False。"""
        from rfauto.service.api import run_once

        first = run_once(recipe_path)
        second = run_once(recipe_path)
        assert first["ok"] and second["ok"]
        assert second["from_cache"] is True
        assert second["cache"]["provenance"] == PROVENANCE_CACHE
        assert second["cache"]["cross_study"] is False


# ─── dry_run：与 run_once 同键预报 ────────────────────────────────────────────


class TestDryRunSameKey:
    def test_dry_run_predicts_hit_with_same_key(self, recipe_path):
        from rfauto.service.api import dry_run, run_once

        before = dry_run(recipe_path)
        assert before["ok"] and before["cache_hit"] is False
        assert before["cache"]["provenance"] == "miss"
        assert before["cache"]["why_miss"], "miss 须给 why_miss"
        assert set(before["cache"]["components"]) == set(CONTENT_KEY_FIELDS)

        ran = run_once(recipe_path, study="S")
        assert ran["ok"], ran.get("errors")
        assert ran["cache"]["key"] == before["cache_key"], "dry-run 与真跑同键"

        after = dry_run(recipe_path)
        assert after["cache_hit"] is True
        assert after["cache"]["provenance"] == PROVENANCE_CACHE
        assert after["cache_key"] == before["cache_key"]


# ─── RFAUTO_CACHE=off 旁路回归 ────────────────────────────────────────────────


class TestBypassOff:
    def test_run_once_off_never_hits(self, recipe_path, monkeypatch):
        from rfauto.service.api import run_once

        monkeypatch.setenv("RFAUTO_CACHE", "off")
        calls = _count_fake_solves(monkeypatch)
        r1 = run_once(recipe_path, study="A")
        r2 = run_once(recipe_path, study="B")
        assert r1["ok"] and r2["ok"]
        assert r1["from_cache"] is False and r2["from_cache"] is False
        assert calls["n"] == 2
        assert r2["cache"]["provenance"] == PROVENANCE_COMPUTED
        assert any("旁路" in w for w in r2["cache"]["why_miss"])
        assert not (Path(".rfauto_cache")).exists() or not any(
            Path(".rfauto_cache").iterdir()), "off 模式不得写条目"

    def test_optimizer_off_never_hits(self, opt_recipe, monkeypatch):
        import optuna

        from rfauto.optimization.optimizer import get_storage_path, run_optimization

        monkeypatch.setenv("RFAUTO_CACHE", "off")
        calls = _count_fake_solves(monkeypatch)
        path = opt_recipe()
        fixed = {"arm_len_mm": 20.0, "series_w_mm": 0.35}
        for name in ("off_A", "off_B"):
            study = optuna.create_study(
                study_name=name, storage=get_storage_path(),
                direction="minimize", load_if_exists=True)
            study.enqueue_trial(dict(fixed))
            r = run_optimization(path, adapter_name="fake", max_trials=1,
                                 study_name=name, adapter_kwargs={"n_ports": 3})
            assert r["ok"], r.get("errors")
        assert calls["n"] == 2, "off 模式两 study 各自真跑"
        study_b = optuna.load_study(study_name="off_B", storage=get_storage_path())
        assert study_b.get_trials(deepcopy=False)[0].user_attrs.get("cache_hit") is None


# ─── 优化外环：跨 study 命中 + 全参键 ─────────────────────────────────────────


class TestOptimizerCrossStudy:
    def test_other_study_same_params_hits_with_provenance(self, opt_recipe, monkeypatch):
        import optuna

        from rfauto.optimization.optimizer import (
            SAMPLER_SEED,
            get_storage_path,
            run_optimization,
        )

        monkeypatch.setenv("RFAUTO_CACHE", "readwrite")
        calls = _count_fake_solves(monkeypatch)
        path = opt_recipe()
        fixed = {"arm_len_mm": 20.0, "series_w_mm": 0.35}

        study_a = optuna.create_study(
            study_name="probe_A", storage=get_storage_path(),
            direction="minimize", load_if_exists=True)
        study_a.enqueue_trial(dict(fixed))
        r1 = run_optimization(path, adapter_name="fake", max_trials=1,
                              study_name="probe_A", adapter_kwargs={"n_ports": 3})
        assert r1["ok"] and r1["trials_completed"] == 1
        assert calls["n"] == 1

        study_b = optuna.create_study(
            study_name="probe_B", storage=get_storage_path(),
            direction="minimize", load_if_exists=True)
        study_b.enqueue_trial(dict(fixed))
        r2 = run_optimization(path, adapter_name="fake", max_trials=1,
                              study_name="probe_B", adapter_kwargs={"n_ports": 3})
        assert r2["ok"] and r2["trials_completed"] == 1
        assert calls["n"] == 1, "异 study 同几何：零真解（秒回）"

        tb = optuna.load_study(study_name="probe_B", storage=get_storage_path())
        trial = tb.get_trials(deepcopy=False)[0]
        assert trial.user_attrs.get("cache_hit") is True
        assert trial.user_attrs.get("cache_provenance") == PROVENANCE_CACHE
        assert trial.user_attrs.get("cache_cross_study") is True
        assert trial.user_attrs.get("cache_origin_study") == "probe_A"
        ta = optuna.load_study(study_name="probe_A", storage=get_storage_path())
        assert ta.get_trials(deepcopy=False)[0].user_attrs["metrics"] == \
            trial.user_attrs["metrics"]

        # manifest：study/seed 只作 provenance；components 全 13 成分
        cache = ResultCache()
        entries = [p for p in cache.cache_dir.iterdir() if p.is_dir()]
        assert len(entries) == 1, "同几何异 study 只应有一条目"
        manifest = cache.read_manifest(entries[0].name)
        assert manifest["study"] == "probe_A"
        assert manifest["seed"] == str(SAMPLER_SEED)
        assert set(manifest["components"]) == set(CONTENT_KEY_FIELDS)
        # 审计文件带 provenance
        trial_json = json.loads(
            (Path(r2["run_dir"]) / "trials" / "trial_0.json").read_text(encoding="utf-8"))
        assert trial_json["cache_provenance"] == PROVENANCE_CACHE
        assert trial_json["cache_cross_study"] is True

    def test_fixed_param_difference_does_not_collide(self, opt_recipe, monkeypatch):
        """键用 param_system 全参：两配方仅固定参数不同、调谐参数相同 → 不串台。"""
        import optuna

        from rfauto.optimization.optimizer import get_storage_path, run_optimization

        monkeypatch.setenv("RFAUTO_CACHE", "readwrite")
        calls = _count_fake_solves(monkeypatch)
        fixed = {"arm_len_mm": 20.0, "series_w_mm": 0.35}
        p1 = opt_recipe("r1.yaml")
        p2 = opt_recipe("r2.yaml", params={"f0_ghz": {"value": 2.5, "unit": "GHz"}})
        for name, path in (("fp_A", p1), ("fp_B", p2)):
            study = optuna.create_study(
                study_name=name, storage=get_storage_path(),
                direction="minimize", load_if_exists=True)
            study.enqueue_trial(dict(fixed))
            r = run_optimization(path, adapter_name="fake", max_trials=1,
                                 study_name=name, adapter_kwargs={"n_ports": 3})
            assert r["ok"], r.get("errors")
        assert calls["n"] == 2, "固定参数 f0_ghz 不同必须各自真跑"
        cache = ResultCache()
        assert len([p for p in cache.cache_dir.iterdir() if p.is_dir()]) == 2

    def test_objectives_not_in_optimizer_key(self, opt_recipe, monkeypatch):
        import optuna

        from rfauto.optimization.optimizer import get_storage_path, run_optimization

        monkeypatch.setenv("RFAUTO_CACHE", "readwrite")
        calls = _count_fake_solves(monkeypatch)
        fixed = {"arm_len_mm": 20.0, "series_w_mm": 0.35}
        p1 = opt_recipe("o1.yaml")
        p2 = opt_recipe("o2.yaml", objectives=[
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -10},
        ])
        for name, path in (("obj_A", p1), ("obj_B", p2)):
            study = optuna.create_study(
                study_name=name, storage=get_storage_path(),
                direction="minimize", load_if_exists=True)
            study.enqueue_trial(dict(fixed))
            r = run_optimization(path, adapter_name="fake", max_trials=1,
                                 study_name=name, adapter_kwargs={"n_ports": 3})
            assert r["ok"], r.get("errors")
        assert calls["n"] == 1, "只改 objectives：Touchstone 复用、零真解"


# ─── #106 分列 + 四类失效经生产派生 ───────────────────────────────────────────


class TestInvalidationThroughProductionDerivation:
    def _components(self, recipe: dict, *, plugin_schema=1, adapter="fake", aedt="fake"):
        return ResultCache.components_for_run(
            model_name=recipe.get("model", ""),
            recipe_data=recipe,
            params_canonical_json='{"arm_len_mm":{"unit":"mm","value":20.5}}',
            plugin_version=f"schema{plugin_schema}",
            plugin_schema_version=plugin_schema,
            adapter_version=adapter,
            aedt_version=aedt,
        )

    def test_recipe_version_and_schema_version_are_separate_sources(self):
        """#106：recipe_version ← 配方文档；schema_version ← 插件类；互不顶替。"""
        recipe = yaml.safe_load(RECIPE_SRC.read_text(encoding="utf-8"))
        assert recipe["recipe_version"] == 1 and recipe["schema_version"] == 1
        base = self._components(recipe, plugin_schema=1)
        assert base["recipe_version"] == "1"
        assert base["schema_version"] == "1"

        # 配方文档升 recipe_version：只有 recipe_version 成分变化
        bumped_recipe = dict(recipe, recipe_version=2)
        c_recipe = self._components(bumped_recipe, plugin_schema=1)
        assert c_recipe["recipe_version"] == "2" and c_recipe["schema_version"] == "1"

        # 配方文档里的 schema_version 字段不是插件参数 schema 的来源
        decoy = dict(recipe, schema_version=9)
        assert self._components(decoy, plugin_schema=1)["schema_version"] == "1"

        # 插件参数 schema 升版：只有 schema_version 成分变化（plugin_version 随之）
        c_plugin = self._components(recipe, plugin_schema=2)
        assert c_plugin["schema_version"] == "2" and c_plugin["recipe_version"] == "1"

        keys = {ResultCache.compute_content_key(**c) for c in (base, c_recipe, c_plugin)}
        assert len(keys) == 3, "三种版本组合三把不同键"

    def test_unversioned_recipe_maps_to_zero(self):
        recipe = yaml.safe_load(RECIPE_SRC.read_text(encoding="utf-8"))
        recipe.pop("recipe_version")
        comps = self._components(recipe)
        assert comps["recipe_version"] == UNVERSIONED_RECIPE_VERSION == "0"

    @pytest.mark.parametrize(
        "field", ["recipe_version", "schema_version", "mesh_params", "adapter_version"],
    )
    def test_four_policies_miss_with_reason(self, tmp_path, field):
        recipe = yaml.safe_load(RECIPE_SRC.read_text(encoding="utf-8"))
        cache = ResultCache(cache_dir=tmp_path / "cache")
        base = self._components(recipe)
        key = ResultCache.compute_content_key(**base)
        src = tmp_path / "src"
        src.mkdir()
        (src / "params.s3p").write_text("# touchstone\n", encoding="utf-8")
        cache.store(key, src, model_name=recipe["model"], study="A", components=base)
        assert cache.lookup(key, study="B")["provenance"] == PROVENANCE_CACHE

        if field == "recipe_version":
            changed = self._components(dict(recipe, recipe_version=2))
        elif field == "schema_version":
            changed = self._components(recipe, plugin_schema=2)
        elif field == "mesh_params":
            changed = dict(base, mesh_params='{"max_delta_mm":0.05}')
        else:
            changed = self._components(recipe, adapter="hfss", aedt="2026.1")
        new_key = ResultCache.compute_content_key(**changed)
        assert new_key != key
        res = cache.lookup(new_key, study="B", components=changed)
        assert res["hit"] is False and res["provenance"] == "miss"
        why = "\n".join(res["why_miss"])
        assert field in why and INVALIDATION_REASONS[field] in why

    def test_setup_change_forces_miss(self):
        recipe = yaml.safe_load(RECIPE_SRC.read_text(encoding="utf-8"))
        a = self._components(recipe)
        recipe2 = dict(recipe, setup={**recipe["setup"], "points": 201})
        b = self._components(recipe2)
        assert a["setup_hash"] != b["setup_hash"]
        assert ResultCache.compute_content_key(**a) != ResultCache.compute_content_key(**b)

    def test_export_contract_hash_from_pydantic_model(self):
        from rfauto.core.contracts import AdsExchangeContract

        recipe = yaml.safe_load(RECIPE_SRC.read_text(encoding="utf-8"))
        c3 = ResultCache.components_for_run(
            model_name="m", recipe_data=recipe, params_canonical_json="{}",
            export_contract=AdsExchangeContract.for_n_ports(3))
        c4 = ResultCache.components_for_run(
            model_name="m", recipe_data=recipe, params_canonical_json="{}",
            export_contract=AdsExchangeContract.for_n_ports(4))
        c_none = ResultCache.components_for_run(
            model_name="m", recipe_data=recipe, params_canonical_json="{}")
        assert c3["export_contract_hash"] and c3["export_contract_hash"] != c4["export_contract_hash"]
        assert c_none["export_contract_hash"] == ""

    def test_legacy_compute_key_entries_are_not_reused(self, tmp_path):
        """旧 9 字段 compute_key 条目与内容寻址键不同名——不会被误命中。"""
        cache = ResultCache(cache_dir=tmp_path / "cache")
        recipe = yaml.safe_load(RECIPE_SRC.read_text(encoding="utf-8"))
        comps = self._components(recipe)
        legacy = cache.compute_key(
            model_name=comps["model_name"], plugin_version=comps["plugin_version"],
            params_canonical_json=comps["params_canonical_json"],
            setup_hash=comps["setup_hash"], adapter_version="fake", aedt_version="fake",
        )
        assert legacy != ResultCache.compute_content_key(**comps)
