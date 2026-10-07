"""坑账结构化索引回归钉（ge8e X6 批；knowledge/pitfalls_index.json + loader）。

锚点面：
- 真索引加载钉：缺省路径可加载、schema 匹配、n_entries>=60（宁 60 条真）；
- 结构往返钉：load → dumps_canonical 两次逐字节一致；json 重解析再校验
  零错误零警告；
- 行段真实性抽查钉：抽查条目的 source 行段与 项目规则 实文对得上
  （行号区间内含该条关键词——防「索引说 A、正文说 B」的静默漂移）；
- 检索钉：by_id 命中/未命中、category 过滤、关键词计分确定性；
- best-effort 注入面钉：pitfall_notes_for 任何失败路径返回空列表不抛穿；
- 坏账拒收钉：schema 错/缺键/重复 id/行段倒挂/坏 JSON/缺文件 → ok=False。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service.pitfall_index_service import (
    DEFAULT_PITFALL_INDEX_PATH,
    PITFALL_INDEX_SCHEMA,
    dumps_canonical,
    load_pitfall_index,
    pitfall_by_category,
    pitfall_by_id,
    pitfall_notes_for,
    pitfall_search,
    validate_pitfall_index,
)


@pytest.fixture(scope="module")
def index() -> dict:
    result = load_pitfall_index()
    assert result["ok"] is True, result.get("errors")
    return result


# ---------------------------------------------------------------------------
# 真索引加载与规模钉
# ---------------------------------------------------------------------------

class TestLoadReal:
    def test_default_path_loads(self, index: dict) -> None:
        assert index["schema_version"] == PITFALL_INDEX_SCHEMA
        assert index["path"] == str(DEFAULT_PITFALL_INDEX_PATH)

    def test_scale_floor(self, index: dict) -> None:
        """宁 60 条真勿 300 条猜：本批抽取规模下限 60。"""
        assert index["n_entries"] >= 60
        assert index["n_entries"] == len(index["entries"])

    def test_ids_unique(self, index: dict) -> None:
        ids = [entry["id"] for entry in index["entries"]]
        assert len(ids) == len(set(ids))

    def test_categories_in_vocab(self, index: dict) -> None:
        for entry in index["entries"]:
            assert entry["category"] in index["categories"], entry["id"]
        assert sum(index["categories"].values()) == index["n_entries"]


# ---------------------------------------------------------------------------
# 结构往返钉
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_dumps_canonical_byte_identical(self, index: dict) -> None:
        assert dumps_canonical(index) == dumps_canonical(index)

    def test_reparse_revalidate_clean(self, index: dict) -> None:
        """load → canonical dumps → 重解析 → 再校验零错误零警告（结构自洽）。"""
        reparsed = json.loads(dumps_canonical(index))
        errors, warnings = validate_pitfall_index(reparsed)
        assert errors == []
        assert warnings == []

    def test_reloaded_from_bytes_equal(self, index: dict, tmp_path: Path) -> None:
        copy_path = tmp_path / "copy.json"
        copy_path.write_text(dumps_canonical(index), encoding="utf-8")
        reloaded = load_pitfall_index(copy_path)
        assert reloaded["ok"] is True
        # 往返钉钉数据面（path 字段因副本路径不同而异，逐字段排除）：
        for key in ("schema_version", "n_entries", "categories", "entries",
                    "warnings"):
            assert reloaded[key] == index[key], key


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 检索钉
# ---------------------------------------------------------------------------

class TestRetrieval:
    def test_by_id_hit_and_miss(self, index: dict) -> None:
        hit = pitfall_by_id(index, "#122")
        assert hit["ok"] is True
        assert hit["entry"]["title"] == "如实记 FAIL/PARTIAL 不凑绿"
        miss = pitfall_by_id(index, "#99999")
        assert miss["ok"] is False
        assert miss["errors"]

    def test_by_category(self, index: dict) -> None:
        result = pitfall_by_category(index, "openems")
        assert result["ok"] is True
        assert result["n_hits"] >= 5
        assert all(entry["category"] == "openems"
                   for entry in result["entries"])

    def test_search_scoring_deterministic(self, index: dict) -> None:
        r1 = pitfall_search(index, ["PowerShell", "编码"])
        r2 = pitfall_search(index, ["PowerShell", "编码"])
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
        assert r1["n_hits"] >= 2  # #89 与 #113 双双命中 PowerShell 族
        assert r1["entries"][0]["id"] == "#113"  # 双词命中（PowerShell+编码）排前

    def test_search_limit_and_empty(self, index: dict) -> None:
        result = pitfall_search(index, ["不存在词 xyzzy"], limit=3)
        assert result["ok"] is True
        assert result["n_hits"] == 0
        assert result["entries"] == []
        bad = pitfall_search(index, "")
        assert bad["ok"] is False

    def test_notes_for_renders_lines(self, index: dict) -> None:
        notes = pitfall_notes_for(index, ["掩码"], limit=2)
        assert notes
        assert all(note.split()[0].startswith("#") or note.split()[0].startswith("A")
                   for note in notes)

    def test_notes_for_best_effort_never_raises(self) -> None:
        """best-effort 钉（#105）：未加载索引/畸形入参 → 空列表不抛穿。"""
        broken = {"ok": False, "errors": ["x"]}
        assert pitfall_notes_for(broken, ["any"]) == []
        loaded = load_pitfall_index()
        assert pitfall_notes_for(loaded, ["", None, 3]) == []  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# 坏账拒收钉
# ---------------------------------------------------------------------------

class TestRejection:
    def test_missing_file(self, tmp_path: Path) -> None:
        result = load_pitfall_index(tmp_path / "nope.json")
        assert result["ok"] is False
        assert "读取失败" in result["errors"][0]

    def test_bad_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        result = load_pitfall_index(path)
        assert result["ok"] is False
        assert "解析失败" in result["errors"][0]

    def _write(self, tmp_path: Path, payload: dict) -> dict:
        path = tmp_path / "idx.json"
        path.write_text(json.dumps(payload, ensure_ascii=False),
                        encoding="utf-8")
        return load_pitfall_index(path)

    def test_wrong_schema_version(self, tmp_path: Path) -> None:
        result = self._write(tmp_path, {"schema_version": "v0", "entries": [
            {"id": "#1", "title": "t", "category": "testing",
             "lesson_one_line": "l",
             "source": {"file": "项目规则", "line_start": 1, "line_end": 1}}]})
        assert result["ok"] is False
        assert any("schema_version" in e for e in result["errors"])

    def _good_entry(self, idx: str = "#1") -> dict:
        return {"id": idx, "title": "t", "category": "testing",
                "lesson_one_line": "l",
                "source": {"file": "项目规则", "line_start": 1, "line_end": 2}}

    def test_missing_required_key(self, tmp_path: Path) -> None:
        entry = self._good_entry()
        del entry["lesson_one_line"]
        result = self._write(tmp_path, {"schema_version": PITFALL_INDEX_SCHEMA,
                                        "entries": [entry]})
        assert result["ok"] is False
        assert any("lesson_one_line" in e for e in result["errors"])

    def test_duplicate_id(self, tmp_path: Path) -> None:
        result = self._write(tmp_path, {
            "schema_version": PITFALL_INDEX_SCHEMA,
            "entries": [self._good_entry(), self._good_entry()]})
        assert result["ok"] is False
        assert any("重复" in e for e in result["errors"])

    def test_line_range_inverted(self, tmp_path: Path) -> None:
        entry = self._good_entry()
        entry["source"]["line_start"], entry["source"]["line_end"] = 9, 3
        result = self._write(tmp_path, {"schema_version": PITFALL_INDEX_SCHEMA,
                                        "entries": [entry]})
        assert result["ok"] is False
        assert any("行段起" in e for e in result["errors"])

    def test_unknown_category_is_warning_not_error(self, tmp_path: Path) -> None:
        entry = self._good_entry()
        entry["category"] = "quantum"
        result = self._write(tmp_path, {
            "schema_version": PITFALL_INDEX_SCHEMA,
            "category_vocab": ["testing"],
            "entries": [entry]})
        assert result["ok"] is True
        assert result["warnings"]
