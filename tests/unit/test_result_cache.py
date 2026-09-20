"""§10.20 ⑨ 补强：result_cache 内容寻址跨 study 复用 + 失效策略显式化（#106/#158）。

验收口径：
- 内容寻址键覆盖 渲染脚本内容 + 网格参数 + 适配器版本 + recipe_version +
  schema_version（分列，便于定位失效原因）；
- key 与 study/seed 解耦——同几何不同 study 命中同一缓存并标 provenance=cache
  （#158：配对实验合法；新轨迹须换 study/seed）；
- 改 recipe_version/schema_version/mesh_params/adapter_version 各触发 miss，
  并给出 why_miss 原因。
"""

from __future__ import annotations

import pytest

from rfauto.infra.result_cache import (
    CONTENT_KEY_FIELDS,
    INVALIDATION_REASONS,
    KEY_EXCLUDED_SCOPES,
    PROVENANCE_CACHE,
    PROVENANCE_MISS,
    ResultCache,
)

BASE_COMPONENTS = {
    "model_name": "wilkinson_power_divider",
    "rendered_script_hash": "sha256:render-v1",
    "geometry_spec_hash": "sha256:geom-v1",
    "material_config_hash": "sha256:mat-v1",
    "mesh_params": '{"max_delta_mm":0.1}',
    "params_canonical_json": '{"arm_len_mm":20.5}',
    "setup_hash": "sha256:setup-v1",
    "export_contract_hash": "sha256:contract-v1",
    "adapter_version": "hfss-2026.1",
    "aedt_version": "2026.1",
    "plugin_version": "schema1",
    "recipe_version": "1",
    "schema_version": "1",
}


def components(**overrides) -> dict[str, str]:
    data = dict(BASE_COMPONENTS)
    data.update(overrides)
    return data


def store_entry(cache, key, tmp_path, *, comps=None, study="", seed="",
                model="wilkinson_power_divider"):
    src = tmp_path / ("src-" + key[:10])
    src.mkdir(parents=True, exist_ok=True)
    (src / "params.s3p").write_text("# touchstone\n", encoding="utf-8")
    return cache.store(key, src, model_name=model, study=study, seed=seed,
                       components=comps)


@pytest.fixture
def cache(tmp_path):
    return ResultCache(cache_dir=tmp_path / "cache")


class TestContentAddressedKey:
    """内容寻址键：稳定、分列覆盖、非法输入报错。"""

    def test_key_is_stable_and_hex64(self):
        k1 = ResultCache.compute_content_key(**components())
        k2 = ResultCache.compute_content_key(**components())
        assert k1 == k2, "同输入两次必须得到同一 key"
        assert len(k1) == 64 and all(c in "0123456789abcdef" for c in k1)

    def test_base_components_match_declared_fields(self):
        assert set(BASE_COMPONENTS) == set(CONTENT_KEY_FIELDS)

    @pytest.mark.parametrize("field", sorted(BASE_COMPONENTS))
    def test_every_declared_field_changes_key(self, field):
        base = ResultCache.compute_content_key(**components())
        changed = ResultCache.compute_content_key(
            **components(**{field: "CHANGED"})
        )
        assert base != changed, field + " 变化必须改变内容寻址键"

    def test_unknown_component_rejected(self):
        with pytest.raises(TypeError, match="未知缓存键成分"):
            ResultCache.compute_content_key(**components(), bogus="x")

    def test_study_seed_rejected_as_components(self):
        assert KEY_EXCLUDED_SCOPES == ("study", "seed")
        for scope in KEY_EXCLUDED_SCOPES:
            with pytest.raises(TypeError, match="未知缓存键成分"):
                ResultCache.compute_content_key(**components(), **{scope: "x"})

    def test_non_string_component_rejected(self):
        with pytest.raises(TypeError, match="必须是字符串"):
            ResultCache.compute_content_key(**components(mesh_params=0.1))

    def test_dict_component_canonicalized(self):
        a = ResultCache.compute_content_key(
            **components(mesh_params={"b": 2, "a": 1})
        )
        b = ResultCache.compute_content_key(
            **components(mesh_params='{"a":1,"b":2}')
        )
        assert a == b, "dict 成分须规范化后参与键计算"


class TestCrossStudyReuse:
    """#158：key 与 study/seed 解耦，跨 study 复用标 provenance=cache。"""

    def test_same_geometry_different_study_hits_same_key(self, cache, tmp_path):
        comps = components()
        key_a = ResultCache.compute_content_key(**comps)
        key_b = ResultCache.compute_content_key(**comps)
        assert key_a == key_b
        store_entry(cache, key_a, tmp_path, comps=comps,
                    study="study_A", seed="7")

        hit = cache.lookup(key_b, study="study_B", seed="99", components=comps)
        assert hit["hit"] is True
        assert hit["provenance"] == PROVENANCE_CACHE
        assert hit["cross_study"] is True
        assert hit["origin_study"] == "study_A"
        assert hit["origin_seed"] == "7"
        assert hit["requester_study"] == "study_B"
        assert hit["path"] == cache.cache_dir / key_a
        assert list(hit["path"].glob("params.s*p")), "命中即拿到现成 Touchstone（秒回）"

    def test_seed_change_keeps_hit(self, cache, tmp_path):
        comps = components()
        key = ResultCache.compute_content_key(**comps)
        store_entry(cache, key, tmp_path, comps=comps, study="s", seed="1")
        hit = cache.lookup(key, study="s", seed="2", components=comps)
        assert hit["hit"] is True
        assert hit["provenance"] == PROVENANCE_CACHE
        assert hit["cross_study"] is False, "同 study 不算跨 study"

    def test_miss_reports_provenance_miss(self, cache):
        res = cache.lookup("deadbeef" * 8, study="s", seed="1",
                           components=components())
        assert res["hit"] is False
        assert res["provenance"] == PROVENANCE_MISS
        assert res["path"] is None
        assert res["why_miss"], "miss 必须给出 why_miss"

    def test_cross_study_note_documents_semantics(self, cache):
        res = cache.lookup("deadbeef" * 8)
        assert "配对实验" in res["note"]
        assert "study" in res["note"] and "recipe_version" in res["note"]


class TestInvalidationPolicy:
    """失效策略：四类必须 miss 并给原因。"""

    @pytest.mark.parametrize(
        "field",
        ["recipe_version", "schema_version", "mesh_params", "adapter_version"],
    )
    def test_field_change_forces_miss_with_reason(self, cache, tmp_path, field):
        comps = components()
        key = ResultCache.compute_content_key(**comps)
        store_entry(cache, key, tmp_path, comps=comps)
        assert cache.check(key) is not None

        changed = components(**{field: "v2-changed"})
        new_key = ResultCache.compute_content_key(**changed)
        assert new_key != key, field + " 变化必须换 key"
        assert cache.check(new_key) is None, field + " 变化必须 miss"

        res = cache.lookup(new_key, components=changed)
        assert res["hit"] is False
        why = "\n".join(res["why_miss"])
        assert field in why
        assert INVALIDATION_REASONS[field] in why, "why_miss 须含人类可读原因"

    def test_rendered_script_change_forces_miss(self, cache, tmp_path):
        comps = components()
        key = ResultCache.compute_content_key(**comps)
        store_entry(cache, key, tmp_path, comps=comps)
        changed = components(rendered_script_hash="sha256:render-v2")
        new_key = ResultCache.compute_content_key(**changed)
        assert new_key != key
        res = cache.lookup(new_key, components=changed)
        assert res["hit"] is False
        assert "rendered_script_hash" in "\n".join(res["why_miss"])

    def test_every_key_field_has_invalidation_reason(self):
        assert set(INVALIDATION_REASONS) == set(CONTENT_KEY_FIELDS)

    def test_diagnose_miss_without_history_explains(self, cache):
        why = cache.diagnose_miss(components())
        assert why and "无历史条目" in why[0]

    def test_diagnose_miss_without_components(self, cache):
        why = cache.diagnose_miss(None)
        assert why and "未提供键成分" in why[0]


class TestManifestAndProvenance:
    """manifest 往返与 provenance 标记。"""

    def test_manifest_roundtrip(self, cache, tmp_path):
        comps = components()
        key = ResultCache.compute_content_key(**comps)
        store_entry(cache, key, tmp_path, comps=comps,
                    study="study_A", seed="7")
        manifest = cache.read_manifest(key)
        assert manifest is not None
        assert manifest["key"] == key
        assert manifest["model"] == "wilkinson_power_divider"
        assert manifest["study"] == "study_A"
        assert manifest["seed"] == "7"
        assert manifest["provenance"] == "computed", "条目 provenance=真跑产出"
        assert manifest["components"] == ResultCache.content_components(**comps)

    def test_read_manifest_missing_returns_none(self, cache):
        assert cache.read_manifest("0" * 64) is None

    def test_provenance_constants(self):
        assert PROVENANCE_CACHE == "cache"
        assert PROVENANCE_MISS == "miss"

    def test_same_key_rewrite_keeps_single_entry(self, cache, tmp_path):
        comps = components()
        key = ResultCache.compute_content_key(**comps)
        store_entry(cache, key, tmp_path, comps=comps, study="A", seed="1")
        store_entry(cache, key, tmp_path, comps=comps, study="B", seed="2")
        assert cache.read_manifest(key)["study"] == "B"
        assert cache.check(key) is not None


class TestCacheModeBypass:
    """RFAUTO_CACHE=off 时 lookup 也须显式旁路。"""

    def test_off_mode_lookup_marks_bypassed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        cache = ResultCache(cache_dir=tmp_path / "cache")
        res = cache.lookup("0" * 64, study="s", components=components())
        assert res["hit"] is False
        assert res["path"] is None
        assert "旁路" in res["why_miss"][0]
