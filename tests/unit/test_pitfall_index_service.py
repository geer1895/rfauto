"""坑账结构化索引 loader 契约钉（公开分发视图不带索引数据）。

公开树口径：knowledge/pitfalls_index.json 属内部账本衍生数据，不随公开
分发视图携带。本文件钉的是 **服务契约在"数据缺席"形态下的诚实行为**：

- 缺省路径缺数据 → load ok=False + errors 显式报（不静默回退空账，
  #316 同方向：坏账/缺席如实报，不假装无坑）；
- 结构往返钉 / 检索钉 / 坏账拒收钉 / best-effort 注入面钉：全部以合成
  索引样本驱动（tmp_path，零外部数据依赖）；
- premortem 注入面（pitfall_notes_for）任何失败路径返回空列表不抛穿。
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

# ---------------------------------------------------------------------------
# 缺省路径（公开分发视图）：数据缺席 → 诚实 error 信封
# ---------------------------------------------------------------------------

class TestDefaultPathHonestMissing:
    def test_default_path_missing_reports_error(self) -> None:
        """公开分发视图不随附索引数据：缺省路径读取失败 → ok=False。"""
        if DEFAULT_PITFALL_INDEX_PATH.is_file():
            pytest.skip("本机存在索引数据（开发视图），缺席钉不适用")
        result = load_pitfall_index()
        assert result["ok"] is False
        assert result["errors"]
        assert "读取失败" in result["errors"][0]

    def test_notes_for_default_path_degrades_to_empty(self) -> None:
        """premortem 注入面对缺席数据 best-effort 空返回（#105 不抛穿）。"""
        if DEFAULT_PITFALL_INDEX_PATH.is_file():
            pytest.skip("本机存在索引数据（开发视图），缺席钉不适用")
        assert pitfall_notes_for(load_pitfall_index(), ["any"]) == []


# ---------------------------------------------------------------------------
# 合成索引样本（检索/往返/校验钉的公共夹具）
# ---------------------------------------------------------------------------

def _sample_entry(idx: str = "#7", category: str = "testing") -> dict:
    return {"id": idx, "title": f"title {idx}", "category": category,
            "lesson_one_line": f"lesson {idx}",
            "source": {"file": "internal-ledger", "line_start": 1,
                       "line_end": 2}}


def _sample_index() -> dict:
    return {
        "schema_version": PITFALL_INDEX_SCHEMA,
        "category_vocab": ["testing", "openems"],
        "entries": [
            _sample_entry("#7"),
            _sample_entry("#9", category="openems"),
            _sample_entry("A12"),
        ],
    }


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> dict:
    path = tmp_path_factory.mktemp("idx") / "sample.json"
    path.write_text(json.dumps(_sample_index(), ensure_ascii=False),
                    encoding="utf-8")
    result = load_pitfall_index(path)
    assert result["ok"] is True, result.get("errors")
    return result


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
# 检索钉（合成样本）
# ---------------------------------------------------------------------------

class TestRetrieval:
    def test_by_id_hit_and_miss(self, index: dict) -> None:
        hit = pitfall_by_id(index, "#7")
        assert hit["ok"] is True
        assert hit["entry"]["title"] == "title #7"
        miss = pitfall_by_id(index, "#99999")
        assert miss["ok"] is False
        assert miss["errors"]

    def test_by_category(self, index: dict) -> None:
        result = pitfall_by_category(index, "openems")
        assert result["ok"] is True
        assert result["n_hits"] == 1
        assert all(entry["category"] == "openems"
                   for entry in result["entries"])

    def test_search_scoring_deterministic(self, index: dict) -> None:
        r1 = pitfall_search(index, ["title", "lesson"])
        r2 = pitfall_search(index, ["title", "lesson"])
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
        # #7 双词命中（title+lesson 同现于 title/lesson 字段）排前
        assert r1["n_hits"] >= 2
        assert r1["entries"][0]["id"] == "#7"

    def test_search_limit_and_empty(self, index: dict) -> None:
        result = pitfall_search(index, ["不存在词 xyzzy"], limit=3)
        assert result["ok"] is True
        assert result["n_hits"] == 0
        assert result["entries"] == []
        bad = pitfall_search(index, "")
        assert bad["ok"] is False

    def test_notes_for_renders_lines(self, index: dict) -> None:
        notes = pitfall_notes_for(index, ["title"], limit=2)
        assert notes
        assert all(note.split()[0].startswith("#")
                   or note.split()[0].startswith("A")
                   for note in notes)

    def test_notes_for_best_effort_never_raises(self) -> None:
        """best-effort 钉（#105）：未加载索引/畸形入参 → 空列表不抛穿。"""
        broken = {"ok": False, "errors": ["x"]}
        assert pitfall_notes_for(broken, ["any"]) == []
        assert pitfall_notes_for({"ok": True, "entries": []},
                                 ["", None, 3]) == []  # type: ignore[list-item]


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
             "source": {"file": "internal-ledger", "line_start": 1,
                        "line_end": 1}}]})
        assert result["ok"] is False
        assert any("schema_version" in e for e in result["errors"])

    def _good_entry(self, idx: str = "#1") -> dict:
        return {"id": idx, "title": "t", "category": "testing",
                "lesson_one_line": "l",
                "source": {"file": "internal-ledger", "line_start": 1,
                           "line_end": 2}}

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
