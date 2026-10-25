"""C5 修复回归测试：ResultCache 行为 + 版本单源 + 缓存前移。"""

from __future__ import annotations

from pathlib import Path


class TestResultCacheSelectiveClear:
    """clear(model_name=...) 必须真正按模型清理（原先永久 no-op）。"""

    def _make_entry(self, cache_dir: Path, key: str, model: str):
        entry = cache_dir / key
        entry.mkdir(parents=True)
        (entry / "params.s3p").write_text("# touchstone\n", encoding="utf-8")
        (entry / "_manifest.json").write_text(
            __import__("json").dumps({"key": key, "model": model}),
            encoding="utf-8",
        )
        return entry

    def test_selective_clear_removes_matching_only(self, tmp_path):
        from rfauto.infra.result_cache import ResultCache
        cache = ResultCache(cache_dir=tmp_path / "cache")
        self._make_entry(cache.cache_dir, "aaa", "wilkinson_power_divider")
        keep = self._make_entry(cache.cache_dir, "bbb", "branchline_coupler")

        removed = cache.clear(model_name="wilkinson_power_divider")
        assert removed == 1
        assert not (cache.cache_dir / "aaa").exists()
        assert keep.exists()

    def test_clear_all(self, tmp_path):
        from rfauto.infra.result_cache import ResultCache
        cache = ResultCache(cache_dir=tmp_path / "cache")
        self._make_entry(cache.cache_dir, "aaa", "m1")
        self._make_entry(cache.cache_dir, "bbb", "m2")
        assert cache.clear() == 2

    def test_store_then_selective_clear_roundtrip(self, tmp_path):
        """store 写入 manifest → clear(model) 能清掉该条目（端到端）。"""
        from rfauto.infra.result_cache import ResultCache
        cache = ResultCache(cache_dir=tmp_path / "cache")
        src = tmp_path / "results"
        src.mkdir()
        snp = src / "params.s3p"
        snp.write_text("# touchstone\n", encoding="utf-8")

        key = cache.compute_key(model_name="wilkinson_power_divider")
        cache.store(key, src, snp, model_name="wilkinson_power_divider")

        assert cache.check(key) is not None, "store 后应可命中"
        assert cache.clear(model_name="wilkinson_power_divider") == 1
        assert cache.check(key) is None

    def test_partial_entry_treated_as_miss(self, tmp_path):
        """无 manifest 或无 Touchstone 的半成品条目按 miss 处理。"""
        from rfauto.infra.result_cache import ResultCache
        cache = ResultCache(cache_dir=tmp_path / "cache")
        entry = cache.cache_dir / "partial"
        entry.mkdir()
        (entry / "metrics.json").write_text("{}", encoding="utf-8")  # 无 sNp 无 manifest
        assert cache.check("partial") is None

    def test_readonly_mode(self, tmp_path, monkeypatch):
        """RFAUTO_CACHE=readonly：命中可查、不写新条目。"""
        from rfauto.infra.result_cache import ResultCache

        # 先以 readwrite 写入一条
        monkeypatch.delenv("RFAUTO_CACHE", raising=False)
        cache_rw = ResultCache(cache_dir=tmp_path / "cache")
        src = tmp_path / "results"
        src.mkdir()
        snp = src / "params.s3p"
        snp.write_text("# touchstone\n", encoding="utf-8")
        key = cache_rw.compute_key(model_name="m")
        cache_rw.store(key, src, snp, model_name="m")

        monkeypatch.setenv("RFAUTO_CACHE", "readonly")
        cache_ro = ResultCache(cache_dir=tmp_path / "cache")
        assert cache_ro.check(key) is not None, "readonly 应能命中"
        other = cache_ro.compute_key(model_name="m2")
        assert cache_ro.store(other, src, snp, model_name="m2") == src, "readonly store 应为空操作"
        assert cache_ro.check(other) is None


class TestCacheBeforeAdapter:
    """run_once 缓存命中时不得创建任何适配器会话。"""

    def test_second_run_hits_cache_without_adapter(self, tmp_path, monkeypatch):
        import shutil

        monkeypatch.chdir(tmp_path)
        src = Path(__file__).parent.parent.parent / "recipes" / "wilkinson_pd_v1.yaml"
        recipe_path = tmp_path / "recipe.yaml"
        shutil.copy2(src, recipe_path)

        from rfauto.adapters import fake_adapter as fa_mod
        from rfauto.service.api import run_once

        created = []
        real_init = fa_mod.FakeAdapter.__init__

        def counting_init(self, *args, **kwargs):
            created.append(1)
            real_init(self, *args, **kwargs)

        monkeypatch.setattr(fa_mod.FakeAdapter, "__init__", counting_init)

        first = run_once(recipe_path)
        assert first["ok"], first.get("errors")
        assert first["from_cache"] is False
        assert len(created) == 1, "首次运行应创建适配器"

        second = run_once(recipe_path)
        assert second["ok"], second.get("errors")
        assert second["from_cache"] is True
        assert len(created) == 1, "缓存命中不应再创建适配器（C5：键检查已前移）"


class TestVersionAndProvenance:
    def test_version_single_source(self):
        import rfauto
        assert rfauto.__version__ == "0.10.0"

    def test_meta_records_real_git_sha(self, tmp_path, monkeypatch):
        """run_once 的 meta.json 必须带非空 git_sha（原先被 "" 覆写）。"""
        import shutil

        monkeypatch.chdir(tmp_path)
        src = Path(__file__).parent.parent.parent / "recipes" / "wilkinson_pd_v1.yaml"
        recipe_path = tmp_path / "recipe.yaml"
        shutil.copy2(src, recipe_path)
        monkeypatch.setenv("RFAUTO_CACHE", "off")

        from rfauto.service.api import run_once
        result = run_once(recipe_path)
        assert result["ok"], result.get("errors")
        import json as json_mod
        meta = json_mod.loads(
            (Path(result["run_dir"]) / "meta.json").read_text(encoding="utf-8")
        )
        assert meta["git_sha"] not in ("", None), "git_sha 不应为空"
        assert meta["package_version"] == "0.10.0"


class TestSanityCheckWiring:
    def test_metrics_json_contains_sanity(self, tmp_path, monkeypatch):
        """两级校验第二级（sanity_check）结果应落入 metrics.json。"""
        import shutil

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        src = Path(__file__).parent.parent.parent / "recipes" / "wilkinson_pd_v1.yaml"
        recipe_path = tmp_path / "recipe.yaml"
        shutil.copy2(src, recipe_path)

        from rfauto.service.api import run_once
        result = run_once(recipe_path)
        assert result["ok"], result.get("errors")
        import json as json_mod
        data = json_mod.loads(
            (Path(result["run_dir"]) / "results" / "metrics.json").read_text(encoding="utf-8")
        )
        assert "sanity_all_ok" in data["checks"]
        assert "sanity_notes" in data["checks"]


class TestModelDocsBoundary:
    def test_minimum_zero_not_dropped(self):
        from rfauto.service.model_docs import generate_model_docs
        doc = generate_model_docs("branchline_coupler")
        # 范围列须渲染下界（2026-08-30 真机修正后 series 下界为 0.5）
        assert "0.5" in doc
        assert ">= " in doc or "[" in doc
