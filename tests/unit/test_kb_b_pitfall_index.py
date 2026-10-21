"""坑账结构化检索面回归钉（架构批 KB-B 席，2026-10-14）.

锚点面：
- 解析器钉（scripts/pitfall_index.py，importlib 直载）：真 项目规约.md 全量
  构建 ≥150 条（只收不放棘轮——他席往 项目规约.md 加坑只增不减不打红）、
  两次构建逐字节确定、产物过 service.validate_pitfall_index 零错误；
- 行级启发单元钉：坑号组提取（连号展开/复合组/非数字后缀不吞）、标题
  出处定语剥离（语义括号保留）、教训前导定语剥离与截断、域标签规则、
  解析失败如实计数（空条目不静默丢）；
- 消费指针并入钉：pitfall_consumption.yaml rows 按坑号交集并入
  （#154 → surface=index_search）；A<行> 行锚漂移类如实计 unmatched；
- 散档入坑账索引钉（KB-B2，2026-10-14）：runs/ SESSION_PITFALLS md 形态
  （有序 ``N. ``/无序 ``- `` 开行、折行并入、h2 分节题/blockquote 跳过）
  → id=`#<TOKEN>-<文档序号>`（文件局部空间与全局坑号隔离，devlog_ref
  如实 None）、source=runs 相对路径+行段、缺档如实计 missing 不中断、
  --number 召回正文引用的全局坑号；真 3 档（FINAL 16/GE8E 20/RX 32）
  入索引与检索命中（runs/ 属 gitignored——散档面测试在档缺失的新 clone
  如实 skip，合成面测试零依赖恒跑）；
- 真产物钉：knowledge/pitfalls_index_full.json 可经
  service.load_pitfall_index 零改动加载（同 schema 契约）+盘面条数
  ≤现构建（漂移自愈=python scripts/pitfall_index.py，--check 模式钉）；
  **漂移不做常驻门**（他席编辑 项目规约.md 属常态，常驻再生钉必红=
  门自指伪象 #355 家族；跨席面归 --check 工具位，#228 精神）；
- CLI 检索叶钉：search 关键词/域/坑号过滤 + --json 信封、get 命中/
  未命中退出码、词面计分（头部 2 分>全文 1 分）、确定性（两次输出
  逐字节同）、usage 错误 --json 退出码 2。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import pytest
from typer.testing import CliRunner

from rfauto.cli.domains.pitfalls import search_entries
from rfauto.cli.main import app  # 先于域模块导入：锁定子应用注册位次（docs cli.md 节序稳定）
from rfauto.service.pitfall_index_service import (
    DEFAULT_PITFALL_INDEX_PATH,
    load_pitfall_index,
    validate_pitfall_index,
)

_SCRIPT = REPO / "scripts" / "pitfall_index.py"
_SPEC = importlib.util.spec_from_file_location("pitfall_index_builder", _SCRIPT)
pitfall_index = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pitfall_index)

_FULL_INDEX = REPO / "knowledge" / "pitfalls_index_full.json"
_CONSUMPTION = REPO / "knowledge" / "pitfall_consumption.yaml"

#: runs/ 散档在档判定（gitignored 工作区资产——新 clone 可能不可见，
#: 散档真源面测试如实 skip；合成面测试零依赖恒跑）。
RUNS_DOCS_PRESENT = all(
    (REPO / rel).is_file() for rel in pitfall_index.RUNS_PITFALL_DOCS)

requires_runs_docs = pytest.mark.skipif(
    not RUNS_DOCS_PRESENT,
    reason="runs/ SESSION_PITFALLS 散档缺失（gitignored，新 clone 不可见）")

runner = CliRunner()


@pytest.fixture(scope="module")
def built() -> dict:
    return pitfall_index.build_index()


@pytest.fixture(scope="module")
def scattered(built: dict) -> list[dict]:
    return [e for e in built["entries"]
            if e["source"]["file"] != "项目规约.md"]


# ---------------------------------------------------------------------------
# 全量构建（真源）
# ---------------------------------------------------------------------------

class TestBuildReal:
    def test_entry_count_ratchet(self, built):
        # 只收不放：他席往 项目规约.md 踩坑速查加条目只增不减（2026-10-14
        # 基线 152；KB-B2 散档并入后总基线 220=152+68，散档缺失的新
        # clone 退回 AGENTS 面基线 152）。条目被删属异常重构，打红让
        # 维护者重导属期望行为。
        floor = 220 if RUNS_DOCS_PRESENT else 150
        assert built["n_entries"] >= floor, built["n_entries"]

    def test_deterministic(self, built):
        again = pitfall_index.build_index()
        assert (pitfall_index.dumps_canonical(built)
                == pitfall_index.dumps_canonical(again))

    def test_passes_service_validator(self, built):
        errors, warnings = validate_pitfall_index(built)
        assert errors == [], errors[:5]
        assert warnings == []

    def test_parse_failures_accounted(self, built):
        # 解析失败如实计数（当前源 0 失败；字段存在性=记账面在）
        assert isinstance(built["n_parse_failures"], int)
        assert built["n_parse_failures"] == len(built["parse_failures"])
        skipped = built["skipped_lines"]
        assert skipped["blockquote"] >= 1  # 编号勘误注记 blockquote 被跳过计数
        assert isinstance(skipped["orphan"], list)

    def test_demo_targets_present(self, built):
        by_id = {e["id"]: e for e in built["entries"]}
        assert "taskkill" in by_id["#157"]["text"]
        assert any(e["id"] == "#373" and "OpenSSL" in e["text"]
                   for e in built["entries"])
        assert "#89" in by_id and "UTF8" in by_id["#89"]["text"]
        assert any(245 in (e.get("numbers") or []) for e in built["entries"])

    def test_consumption_merged(self, built):
        rows = pitfall_index.load_consumption_rows(_CONSUMPTION)
        assert len(rows) >= 10
        cons = built["consumption"]
        assert cons["n_rows"] == len(rows)
        assert cons["n_matched_rows"] >= 7
        by_id = {e["id"]: e for e in built["entries"]}
        hit = by_id.get("#154") or {}
        surfaces = [c["surface"] for c in hit.get("consumption") or []]
        assert "index_search" in surfaces


# ---------------------------------------------------------------------------
# 行级启发单元（合成输入）
# ---------------------------------------------------------------------------

class TestHeuristics:
    def test_extract_numbers_ranges(self):
        assert pitfall_index.extract_numbers("#237-#241") == list(
            range(237, 242))
        assert pitfall_index.extract_numbers("#149/#150/#155") == [
            149, 150, 155]
        # 非数字后缀（#364-②）不吞；日期区间不误展开（跨度>60）
        assert pitfall_index.extract_numbers("#364-②") == [364]
        assert pitfall_index.extract_numbers("#100-#999") == [100, 999]
        assert pitfall_index.extract_numbers("无坑号文本") == []

    def test_clean_title(self):
        strip = pitfall_index._clean_title
        assert strip("DLL 双 install 遮蔽坑（2026-10-08 ge9 实证，簇5）") == \
            "DLL 双 install 遮蔽坑"
        assert strip("typer isinstance 陷阱（#354，）") == \
            "typer isinstance 陷阱"
        # 语义括号保留
        assert strip("recipe_version（配方 schema 版本）语义") == \
            "recipe_version（配方 schema 版本）语义"

    def test_lesson_strip_qualifier_and_truncate(self):
        lesson = pitfall_index._lesson_one_line
        out = lesson("（2026-09-08 用户立规）：HFSS 是射频领域认可度最高的 EDA"
                     "——修正路径=官方文档。")
        assert out.startswith("HFSS")
        long = "很长的教训" * 60
        assert len(lesson(long)) == 160 and lesson(long).endswith("…")

    def test_classify_category(self):
        cls = pitfall_index.classify_category
        assert cls("KiCad pcbnew ZONE_FILLER 段错误") == "kicad"
        assert cls("PowerShell taskkill 进程树") == "shell"
        assert cls("完全无关的文本没有关键词") == "process"

    def test_parse_entry_failure_accounted(self):
        seen: set[str] = set()
        fail = pitfall_index.parse_entry(42, ["- "], seen)
        assert fail["reason"] == "空条目" and fail["line"] == "42"

    def test_parse_entry_synthetic_id_and_numbers(self):
        seen: set[str] = set()
        entry = pitfall_index.parse_entry(
            7, ["- **无号坑标题**：教训主张——理由。（#201）"], seen)
        assert entry["id"] == "#201" and entry["numbers"] == [201]
        assert entry["devlog_ref"] == "#201"
        entry2 = pitfall_index.parse_entry(
            9, ["- 无坑号条目：纯教训主张——理由。"], seen)
        assert entry2["id"] == "A9" and entry2["devlog_ref"] is None


# ---------------------------------------------------------------------------
# 散档解析单元（KB-B2：合成输入零依赖恒跑）
# ---------------------------------------------------------------------------

class TestScatteredHeuristics:
    def test_scattered_id_token(self):
        tok = pitfall_index.scattered_id_token
        assert tok("runs/rx_followup/SESSION_PITFALLS_RX.md") == "RX"
        assert tok("runs/ge8_followup/SESSION_PITFALLS_FINAL.md") == "FINAL"
        assert tok("runs/x/OTHER.md") == "OTHER"

    def test_parse_entry_ordered_marker(self):
        seen: set[str] = set()
        entry = pitfall_index.parse_entry(
            5, ["12. **有序条标题**：主张——理由。"], seen)
        assert entry["id"] == "A5"  # 无 id_override → 行锚合成（12. 非坑号）
        assert entry["title"] == "有序条标题"
        # 「——」前置过短（<8 字）退回首句口径（与 AGENTS 面同规则）
        assert entry["lesson_one_line"] == "主张——理由。"
        # 有序空条目与无序同判：如实计空条目不静默丢
        fail = pitfall_index.parse_entry(7, ["12."], seen)
        assert fail["reason"] == "空条目" and fail["line"] == "7"

    def test_split_scattered_blocks(self):
        blocks, skipped = pitfall_index.split_scattered_blocks([
            "# 档题（2026-10-14）",
            "> 档头注记",
            "",
            "## 一、层甲",
            "",
            "1. **首条**：主张甲——理由。（#122）",
            "   折行续行。",
            "2. **次条**：主张乙——理由。",
            "",
            "## 二、层乙",
            "",
            "- **无序条**：主张丙——理由。",
        ])
        assert [b[0] for b in blocks] == [6, 8, 12]  # 1-based 起始行
        assert skipped == {"blank": 4, "blockquote": 1, "heading": 3,
                           "orphan": []}
        # 分节题不得并进前条：块 1 只含首条两行
        assert len(blocks[0][1]) == 2

    def test_split_scattered_orphan_accounted(self):
        blocks, skipped = pitfall_index.split_scattered_blocks(
            ["孤行无条目", "- **条**：主张——理由。"])
        assert len(blocks) == 1
        assert len(skipped["orphan"]) == 1
        assert skipped["orphan"][0]["line"] == 1

    def test_split_scattered_version_line_not_split(self):
        # 「0.7.0 绑定」类版本号续行不误切为新条目（点号后非空白非行尾）
        blocks, _ = pitfall_index.split_scattered_blocks([
            "1. **条**：主张——理由。",
            "0.7.0 绑定版本续行。",
            "2. **次条**：主张——理由。",
        ])
        assert [b[0] for b in blocks] == [1, 3]
        assert len(blocks[0][1]) == 2  # 版本行并入前条

    def test_parse_scattered_doc_synthetic(self, tmp_path):
        doc = tmp_path / "runs" / "x" / "SESSION_PITFALLS_TST.md"
        doc.parent.mkdir(parents=True)
        doc.write_text(
            "# 测试散档（2026-10-14，源稿）\n"
            "> 档头注记\n"
            "\n"
            "## 一、层甲\n"
            "\n"
            "1. **首条标题**：首条主张——理由。（#122）\n"
            "   折行续行内容。\n"
            "2. **次条标题**：次条主张——次条理由。\n"
            "\n"
            "## 二、层乙\n"
            "\n"
            "- **无序条标题**：无序主张——无序理由。\n",
            encoding="utf-8")
        rel = "runs/x/SESSION_PITFALLS_TST.md"
        seen: set[str] = set()
        out = pitfall_index.parse_scattered_doc(rel, seen, root=tmp_path)
        assert out["n_entries"] == 3 and out["n_failures"] == 0
        assert out["title"] == "测试散档（2026-10-14，源稿）"
        ids = [e["id"] for e in out["entries"]]
        assert ids == ["#TST-1", "#TST-2", "#TST-3"]
        first = out["entries"][0]
        # 正文引用全局坑号进 numbers（--number 召回），id 仍是合成档号
        # （直当 #122 用会撞全局坑号空间——隔离钉）
        assert first["numbers"] == [122] and first["id"] == "#TST-1"
        assert first["devlog_ref"] is None
        assert first["source"] == {"file": rel, "line_start": 6,
                                   "line_end": 7}
        # 合成条目过校验器零错误零警告（#TOKEN-N 形态在契约内）
        fake_index = {
            "schema_version": pitfall_index.SCHEMA_VERSION,
            "category_vocab": pitfall_index.CATEGORY_VOCAB,
            "entries": out["entries"],
        }
        errors, warnings = validate_pitfall_index(fake_index)
        assert errors == [] and warnings == []

    def test_parse_scattered_doc_failure_keeps_sequence(self, tmp_path):
        doc = tmp_path / "SESSION_PITFALLS_BAD.md"
        doc.write_text(
            "1. **好条**：主张——理由。\n"
            "2.\n"
            "- **尾条**：主张——理由。\n",
            encoding="utf-8")
        seen: set[str] = set()
        out = pitfall_index.parse_scattered_doc(
            "SESSION_PITFALLS_BAD.md", seen, root=tmp_path)
        assert out["n_entries"] == 2 and out["n_failures"] == 1
        assert out["failures"][0]["id"] == "#BAD-2"  # 失败占号，序号不塌
        assert out["entries"][1]["id"] == "#BAD-3"

    def test_build_index_missing_scattered_accounted(self, tmp_path):
        # 缺档如实计 missing 不中断构建（runs/ gitignored——新 clone 形态）
        idx = pitfall_index.build_index(runs_root=tmp_path)
        sc = idx["scattered_docs"]
        assert sc["n_missing"] == len(pitfall_index.RUNS_PITFALL_DOCS)
        assert sc["n_entries"] == 0
        assert all(e["source"]["file"] == "项目规约.md"
                   for e in idx["entries"])
        errors, warnings = validate_pitfall_index(idx)
        assert errors == [] and warnings == []


# ---------------------------------------------------------------------------
# 散档真源面（KB-B2：runs/ 3 档；gitignored——缺档新 clone 如实 skip）
# ---------------------------------------------------------------------------

_SCATTERED_N = {"FINAL": 16, "GE8E": 20, "RX": 32}


@requires_runs_docs
class TestScatteredDocsReal:
    def test_accounting(self, built, scattered):
        sc = built["scattered_docs"]
        assert sc["n_missing"] == 0 and sc["n_docs"] == 3
        assert sc["n_entries"] == len(scattered) == sum(
            _SCATTERED_N.values())
        assert sc["n_agents_entries"] == built["n_entries"] - len(scattered)
        by_tok = {pitfall_index.scattered_id_token(d["path"]): d
                  for d in sc["docs"]}
        for tok, n in _SCATTERED_N.items():
            assert by_tok[tok]["n_entries"] == n
            assert by_tok[tok]["missing"] is False
            assert by_tok[tok]["title"]
        assert built["n_parse_failures"] == 0  # 三档全形态条目零失败

    def test_ids_sources_lines(self, built, scattered):
        all_ids = [e["id"] for e in built["entries"]]
        assert len(all_ids) == len(set(all_ids))  # 全局唯一（含散档合成 id）
        n_lines = {rel: len((REPO / rel).read_text(encoding="utf-8")
                            .splitlines())
                   for rel in pitfall_index.RUNS_PITFALL_DOCS}
        for e in scattered:
            assert re.match(r"^#[A-Z0-9]+-\d+$", e["id"]), e["id"]
            assert e["devlog_ref"] is None  # 合成 id 非坑号，如实 None
            src = e["source"]
            assert src["file"].replace("\\", "/").startswith("runs/")
            assert 1 <= src["line_start"] <= src["line_end"] <= n_lines[
                src["file"].replace("\\", "/")]
        vocab = set(built["category_vocab"])
        assert {e["category"] for e in scattered} <= vocab

    def test_known_entries(self, scattered):
        by_id = {e["id"]: e for e in scattered}
        # FINAL-5 git index.lock stale
        assert "index.lock" in by_id["#FINAL-5"]["text"]
        # GE8E-10 文献裁决 V1 范式
        assert "编造" in by_id["#GE8E-10"]["title"]
        # RX-21 门口径 v2 三分法 / RX-22 行窗重锚 needle
        assert by_id["#RX-21"]["title"] == "门口径 v2 三分法"
        assert by_id["#RX-22"]["numbers"] == [122, 108]
        # FINAL-14 #222 重申条：正文引用号进 numbers，id 不占全局坑号
        assert by_id["#FINAL-14"]["numbers"] == [222]

    def test_search_hits_scattered(self, built):
        hits, n = search_entries(built["entries"], ["index.lock"])
        assert n >= 1 and hits[0]["id"] == "#FINAL-5"
        hits2, _ = search_entries(built["entries"], ["needle", "行窗"])
        assert any(e["id"] == "#RX-22" for e in hits2)
        # --number 召回：#222 证据散档与全局登记同池
        hits3, _ = search_entries(built["entries"], [], number=222)
        ids = {e["id"] for e in hits3}
        assert {"#222", "#FINAL-14", "#RX-1"} <= ids

    def test_cli_get_scattered_json(self):
        r = runner.invoke(app, ["pitfalls", "get", "#GE8E-10", "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.stdout)
        entry = payload["entry"]
        assert entry["source"]["file"].endswith(
            "SESSION_PITFALLS_GE8E.md")
        assert entry["devlog_ref"] is None

    def test_cli_search_number222_json(self):
        r = runner.invoke(app, ["pitfalls", "search", "--number", "222",
                                "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.stdout)
        assert payload["ok"] is True and payload["n_entries"] >= 220
        ids = {e["id"] for e in payload["entries"]}
        assert {"#222", "#RX-1"} <= ids

    def test_disk_artifact_has_scattered(self):
        # 只收不放棘轮（非逐位等值钉——他席加坑后未重导属 --check 自愈面，
        # 常驻等值钉=门自指伪象 #355 家族）
        disk = json.loads(_FULL_INDEX.read_text(encoding="utf-8"))
        assert disk["n_entries"] >= 220
        sc = disk["scattered_docs"]
        assert sc["n_entries"] == sum(_SCATTERED_N.values())
        assert sc["n_missing"] == 0


# ---------------------------------------------------------------------------
# 真产物（盘面）与 --check 工具位
# ---------------------------------------------------------------------------

class TestArtifactOnDisk:
    def test_loads_via_service(self):
        idx = load_pitfall_index(_FULL_INDEX)
        assert idx["ok"] is True, idx.get("errors")
        assert idx["n_entries"] >= 150

    @requires_runs_docs
    def test_ratchet_disk_not_ahead_of_source(self, built):
        # 盘面条数 ≤ 现构建（落后=需重导，--check 工具位自愈；超前不可能；
        # 散档缺失的新 clone 盘面含散档而构建不含——该面如实 skip）
        disk = json.loads(_FULL_INDEX.read_text(encoding="utf-8"))
        assert disk["n_entries"] <= built["n_entries"]

    def test_check_mode_detects_drift(self, built, tmp_path):
        out = tmp_path / "idx.json"
        out.write_text(pitfall_index.dumps_canonical(built) + "\n",
                       encoding="utf-8")
        assert pitfall_index.main(["--check", "--out", str(out)]) == 0
        out.write_text("{}\n", encoding="utf-8")
        assert pitfall_index.main(["--check", "--out", str(out)]) == 1


# ---------------------------------------------------------------------------
# 检索纯函数与 CLI 叶
# ---------------------------------------------------------------------------

class TestSearchEntries:
    def test_head_beats_text(self):
        entries = [
            {"id": "#1", "title": "无关标题", "lesson_one_line": "x",
             "category": "process", "numbers": [], "text": "提到 taskkill 的正文"},
            {"id": "#2", "title": "taskkill 整树连坐", "lesson_one_line": "y",
             "category": "shell", "numbers": [157], "text": "无关正文"},
        ]
        hits, n = search_entries(entries, ["taskkill"])
        assert n == 2 and hits[0]["id"] == "#2"  # 头部命中 2 分 > 全文 1 分

    def test_domain_and_number_filters(self, built):
        hits, _ = search_entries(built["entries"], ["OpenSSL"],
                                 domains=["hfss"])
        assert any(e["id"] == "#373" for e in hits)
        hits2, _ = search_entries(built["entries"], [], number=245)
        assert any(245 in e["numbers"] for e in hits2)

    def test_deterministic_order(self, built):
        a = search_entries(built["entries"], ["taskkill"], limit=10)
        b = search_entries(built["entries"], ["taskkill"], limit=10)
        assert [e["id"] for e in a[0]] == [e["id"] for e in b[0]]


class TestCliLeaves:
    def test_search_keyword_json(self):
        r = runner.invoke(app, ["pitfalls", "search", "taskkill", "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.stdout)
        assert payload["ok"] is True and payload["n_entries"] >= 150
        assert any(e["id"] == "#157" for e in payload["entries"])

    def test_search_number_filter(self):
        r = runner.invoke(app, ["pitfalls", "search", "--number", "245",
                                "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.stdout)
        assert payload["entries"]
        assert all(245 in e["numbers"] for e in payload["entries"])

    def test_search_domain_filter_table(self):
        r = runner.invoke(app, ["pitfalls", "search", "OpenSSL",
                                "--domain", "hfss"])
        assert r.exit_code == 0, r.output
        assert "#373" in r.output

    def test_search_usage_error_json_exit2(self):
        r = runner.invoke(app, ["pitfalls", "search", "--json"])
        assert r.exit_code == 2
        payload = json.loads(r.stdout)
        assert payload["ok"] is False and payload["errors"]

    def test_search_bad_number_json_exit2(self):
        r = runner.invoke(app, ["pitfalls", "search", "--number", "abc",
                                "--json"])
        assert r.exit_code == 2
        assert json.loads(r.stdout)["ok"] is False

    def test_get_hit_and_miss(self):
        r = runner.invoke(app, ["pitfalls", "get", "#89", "--json"])
        assert r.exit_code == 0, r.output
        entry = json.loads(r.stdout)["entry"]
        assert "PowerShell" in entry["title"] or "UTF8" in entry["text"]
        r2 = runner.invoke(app, ["pitfalls", "get", "#999999", "--json"])
        assert r2.exit_code == 1
        payload = json.loads(r2.stdout)
        assert payload["ok"] is False and payload["errors"]

    def test_get_table_mode_shows_consumption(self):
        r = runner.invoke(app, ["pitfalls", "get", "#154"])
        assert r.exit_code == 0, r.output
        assert "index_search" in r.output

    def test_search_deterministic_stdout(self):
        argv = ["pitfalls", "search", "taskkill", "--json"]
        r1 = runner.invoke(app, argv)
        r2 = runner.invoke(app, argv)
        assert r1.exit_code == r2.exit_code == 0
        assert r1.stdout == r2.stdout

    def test_search_v1_curated_index(self):
        # --index 可切人工精选 v1（同 schema 契约，同 loader 零改动）
        r = runner.invoke(app, ["pitfalls", "search", "PowerShell",
                                "--index", str(DEFAULT_PITFALL_INDEX_PATH),
                                "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.stdout)
        assert payload["n_entries"] == 66
        assert payload["entries"]


from pathlib import Path as _Path

import pytest as _pytest

#: 坑账“源文件”未随公开检出发（公开仓只分发再生后的索引产物
#: knowledge/pitfalls_index*.json）——依赖源文件再生的测试在公开检出
#: 如实跳过（同 test_ui.py 演示夹具 skipif 先例）。
_PITFALL_SOURCE_ABSENT = not (_Path(__file__).resolve().parents[2]
                              / "项目规约.md").is_file()
_SOURCE_SKIP = _pytest.mark.skipif(
    _PITFALL_SOURCE_ABSENT,
    reason="pitfall ledger source file not shipped in this checkout")

pytestmark = _SOURCE_SKIP
