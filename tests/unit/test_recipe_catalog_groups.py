"""C22 配方目录"工作副本"分组单测（TODO:417 followUp）。

钉住：①list_recipes 三态分组（原件/工作副本/混存）——recipes 键保持只含
recipes/ 原件（既有消费者零改动），工作副本单列 workcopies（source_recipe
反查 + review_hint 入库提示）+ groups 计数 + 逐条 kind 字段；②recipe_view
的 is_workcopy/source_recipe/review_hint 视图字段（相对与绝对路径双形态）；
③pages.js loadCatalog/pageRecipe 渲染钉（函数体断言，test_nf2ff_chain 先例）。
全部 chdir tmp_path（#144 隔离口径，不读真 recipes/ 与 runs/）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from rfauto.service.r3_services import list_recipes
from rfauto.service.ui_service import recipe_view

SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(autouse=True)
def _isolated(isolated_cache_off):
    """隔离体收编 tests/conftest.py::isolated_cache_off（T5 批5 单源化）。"""
    yield


def _write_recipe(path: Path, model: str = "wilkinson_power_divider") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "model": model,
        "params": {"w_mm": {"value": 1.0, "unit": "mm",
                            "bounds": {"low": 0.5, "high": 2.0}}},
        "objectives": [{"metric": "s11_db", "op": "max_below", "value": -15}],
        "setup": {"freq_range_ghz": [2.0, 3.0], "n_points": 101},
    }, allow_unicode=True), encoding="utf-8")
    return path


class TestListRecipesGroups:
    def test_originals_only(self, tmp_path: Path) -> None:
        _write_recipe(tmp_path / "recipes" / "a.yaml")
        d = list_recipes()
        assert d["ok"]
        assert [r["path"] for r in d["recipes"]] == ["recipes/a.yaml"]
        assert d["recipes"][0]["kind"] == "original"
        assert d["workcopies"] == []
        assert d["groups"] == {"originals": 1, "workcopies": 0}

    def test_workcopies_only(self, tmp_path: Path) -> None:
        _write_recipe(tmp_path / "runs" / "recipe_workcopy" / "b.yaml")
        d = list_recipes()
        assert d["recipes"] == []
        assert [r["path"] for r in d["workcopies"]] == \
            ["runs/recipe_workcopy/b.yaml"]
        entry = d["workcopies"][0]
        assert entry["kind"] == "workcopy"
        assert entry["source_recipe"] == "recipes/b.yaml"
        assert "rfauto inbox" in entry["review_hint"]
        assert d["groups"] == {"originals": 0, "workcopies": 1}

    def test_mixed_groups(self, tmp_path: Path) -> None:
        _write_recipe(tmp_path / "recipes" / "a.yaml")
        _write_recipe(tmp_path / "recipes" / "sub" / "c.yaml")
        _write_recipe(tmp_path / "runs" / "recipe_workcopy" / "a.yaml")
        d = list_recipes()
        # 原件列表只含 recipes/（含子目录），工作副本不混入
        assert [r["path"] for r in d["recipes"]] == [
            "recipes/a.yaml", "recipes/sub/c.yaml"]
        assert [r["path"] for r in d["workcopies"]] == [
            "runs/recipe_workcopy/a.yaml"]
        assert d["workcopies"][0]["source_recipe"] == "recipes/a.yaml"
        assert d["groups"] == {"originals": 2, "workcopies": 1}

    def test_workcopy_subdir_mirror_and_broken_yaml(self, tmp_path: Path) -> None:
        _write_recipe(tmp_path / "runs" / "recipe_workcopy" / "sub" / "d.yaml")
        broken = tmp_path / "runs" / "recipe_workcopy" / "bad.yaml"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text("{ oops", encoding="utf-8")
        d = list_recipes()
        assert [r["path"] for r in d["workcopies"]] == [
            "runs/recipe_workcopy/bad.yaml", "runs/recipe_workcopy/sub/d.yaml"]
        assert "解析失败" in d["workcopies"][0]["model"]
        assert d["workcopies"][1]["source_recipe"] == "recipes/sub/d.yaml"

    def test_recipe_view_original_has_no_workcopy_fields(
            self, tmp_path: Path) -> None:
        path = _write_recipe(tmp_path / "recipes" / "a.yaml")
        v = recipe_view(path)
        assert v["ok"] and v["is_workcopy"] is False
        assert "source_recipe" not in v and "review_hint" not in v

    def test_recipe_view_workcopy_relative_and_absolute(
            self, tmp_path: Path) -> None:
        _write_recipe(tmp_path / "recipes" / "a.yaml")
        rel = tmp_path / "runs" / "recipe_workcopy" / "a.yaml"
        _write_recipe(rel)
        v = recipe_view("runs/recipe_workcopy/a.yaml")
        assert v["ok"] and v["is_workcopy"] is True
        assert v["source_recipe"] == "recipes/a.yaml"
        assert "rfauto inbox" in v["review_hint"]
        v_abs = recipe_view(rel)
        assert v_abs["is_workcopy"] is True
        assert v_abs["source_recipe"] == "recipes/a.yaml"


class TestPagesRenderPin:
    """pages.js 渲染钉（函数体断言，仿 test_nf2ff_chain 先例）。"""

    def _page_recipe_body(self) -> str:
        # UI-R2：入口+pages/ 域模块并集读（pageRecipe→pageTune 边界跨文件仍成立）
        _s = SRC / "rfauto" / "ui" / "static"
        pages = "\n".join(
            p.read_text(encoding="utf-8")
            for p in [_s / "pages.js", *sorted((_s / "pages").glob("*.js"))])
        m = re.search(r"async function pageRecipe.*?async function pageTune",
                      pages, re.S)
        assert m is not None, "pageRecipe 函数体未找到"
        return m.group(0)

    def test_catalog_groups_original_and_workcopy(self) -> None:
        body = self._page_recipe_body()
        # aurora_i 文案二遍把分组标签迁 i18n 词表（recipe.* 键域）——
        # 钉改键位形态，语义不变：原件组在上、工作副本组独立+徽章+审阅提示
        assert "t(\"recipe.orig_head\")" in body
        assert "t(\"recipe.workcopy_head\")" in body
        assert "t(\"recipe.workcopy_badge\")" in body
        assert "T.badge(t(\"recipe.workcopy_badge\")" in body
        # 工作副本条目给人工审阅入库提示（指向既有审批链入口名）
        assert "rfauto inbox" in body

    def test_loaded_recipe_workcopy_indicator(self) -> None:
        body = self._page_recipe_body()
        assert "val.is_workcopy" in body
        assert "val.review_hint" in body
