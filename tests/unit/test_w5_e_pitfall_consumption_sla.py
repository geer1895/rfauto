"""T15-B12 坑账消费 SLA 门（常驻门；SPECS3 §3.3）。

门语义（预声明）：solver 四类（openems/hfss/comsol/elmer）13 条坑账
（knowledge/pitfalls_index.json）每条必须在二消费面之一有指针——
(a) playbook.yaml pit_refs（症状可机器观测族，只收确定性指纹）；
(b) knowledge/pitfall_consumption.yaml 消费指针行（W5-E 口径=13 条仅
    消费说明，不为凑门硬塞 playbook，#122 哲学）。

判据（spec ①-④）：

- ① 双态钉：回填前红（10 缺，证据 tests/gold/pitfall_sla/
  sla_red_before_backfill.json——原档 runs/w5_phase5/w5e/ 同名件
  gitignored，ge9 审查 R7 P1-1 迁 gold 入库【本机绝对路径净化】，
  runs/ 原件留痕不删）→回填后绿（本文件 real-tree 用例）；
  合成目录重演回填前态；
- ② 新增 solver 类坑不登记 → 红（合成样本）；
- ③ 指针有效性：playbook pit_refs 坑号必须能在坑账全集体（index∪
  项目规则 速查）反查（防 typo 空指针）；(b) 面 surface 枚举封闭；
- ④ consumption 登记坑账全集不存在的坑 → 红（多报不放过 #316）。

另钉（seat 指令"最低消费点检查"）：三已接线消费面（index 检索/
premortem 注入/error_hint 规则表）活体探针全绿；error_hint 行逐行
refs 实证。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

#: 项目规则速查腿（内部账本人读面）缺席的环境（公开树）下，依赖
#: "反查全集含该腿"的用例如实 skip——service 降级语义=#316 方向
#: （缺席时 index 外 ref 按 dangling 多报），跳过不代表门被拆除。
_HAS_LEDGER_DOC = (Path(__file__).resolve().parents[1] / 'PROJECT_RULES.md').exists()
_LEDGER_SKIP = pytest.mark.skipif(
    not _HAS_LEDGER_DOC,
    reason='ledger quick-ref doc (PROJECT_RULES.md) absent in this tree',
)

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.service.pitfall_consumption_sla import (
    CONSUMPTION_SCHEMA,
    SOLVER_CATEGORIES,
    check_pitfall_consumption_sla,
    id_tokens,
)

REPO = Path(__file__).resolve().parents[2]
# 红态证据=入库 gold 快照（ge9 审查 R7 P1-1：原 runs/ 路径 gitignored，
# 干净检出必红；gold 件为 runs/ 原件的净化拷贝——本机绝对路径→仓内相对，
# 其余逐值一致；runs/ 原件留痕不删）
RED_EVIDENCE = (REPO / "tests" / "gold" / "pitfall_sla"
                / "sla_red_before_backfill.json")

#: spec §3.3 点名的回填前 10 缺（顺序=spec 原文列举）。
SPEC_MISSING_10 = {"#154", "#149/#150/#155", "#208", "#212", "#232",
                   "#323", "A216", "A220", "#215/#217", "A304"}


def _mk_entry(eid: str, category: str, title: str) -> dict:
    return {
        "id": eid, "title": title, "category": category,
        "lesson_one_line": f"{title} 的教训行",
        "source": {"file": "项目规则", "line_start": 1, "line_end": 2},
    }


def _mk_index(entries: list[dict]) -> dict:
    return {
        "schema_version": "rfauto-pitfalls-index-v1",
        "generated_by": "w5e-sla-test",
        "generated_date": "2026-10-05",
        "category_vocab": ["openems", "hfss", "comsol", "elmer", "python"],
        "entries": entries,
    }


def _write_yaml(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path


class TestRealTreeGate:
    @_LEDGER_SKIP
    def test_solver_thirteen_all_covered_and_faces_alive(self):
        """门绿路径：13/13 有指针；三最低消费点活体探针全绿。"""
        rep = check_pitfall_consumption_sla()
        assert rep["ok"], f"SLA 门红：{rep['violations']}"
        assert rep["n_solver_entries"] == 13
        assert rep["n_covered"] == 13
        assert rep["violations"] == []
        assert set(rep["faces"]) == {"index_search", "premortem_note",
                                     "error_hint"}
        for name, face in rep["faces"].items():
            assert face["ok"], f"消费面 {name} 探针失败"
        for c in rep["coverage"]:
            assert c["category"] in SOLVER_CATEGORIES
            assert c["covered"], f"{c['id']} 无消费指针"

    def test_backfilled_rows_are_real_faces(self):
        """回填 10 行 surface 全部指向真实面（spec 六面为预登记不用）。"""
        cp = yaml.safe_load(
            (REPO / "knowledge" / "pitfall_consumption.yaml")
            .read_text(encoding="utf-8"))
        assert cp["schema"] == CONSUMPTION_SCHEMA
        rows = cp["rows"]
        assert len(rows) == 10
        ids = {r["id"] for r in rows}
        assert ids == SPEC_MISSING_10
        for row in rows:
            assert row["surface"] in {"index_search", "premortem_note",
                                      "error_hint"}
            assert row["pointer"].strip()
            assert row["keywords"]
            assert row["note"].strip()

    def test_red_evidence_recorded(self):
        """双态钉证据在档：回填前红（10 uncovered + 文件缺失）。"""
        assert RED_EVIDENCE.exists(), "先红后绿证据链缺失（判据①）"
        ev = json.loads(RED_EVIDENCE.read_text(encoding="utf-8"))
        assert ev["ok"] is False
        uncovered = {v["id"] for v in ev["violations"]
                     if v["kind"] == "uncovered_solver_pitfall"}
        assert uncovered == SPEC_MISSING_10
        kinds = {v["kind"] for v in ev["violations"]}
        assert "consumption_load" in kinds  # 登记面当时尚不存在


class TestSyntheticDoubleState:
    def _synthetic_setup(self, tmp_path: Path) -> dict:
        """合成坑账：solver 3 条 + 非 solver 1 条。"""
        entries = [
            _mk_entry("#900", "openems", "合成 openEMS 坑甲"),
            _mk_entry("#901", "hfss", "合成 HFSS 坑乙"),
            _mk_entry("#902", "comsol", "合成 COMSOL 坑丙"),
            _mk_entry("#903", "python", "合成 python 坑丁（非 solver）"),
        ]
        index_path = tmp_path / "index.json"
        index_path.write_text(json.dumps(_mk_index(entries),
                                         ensure_ascii=False),
                              encoding="utf-8")
        return {"index": index_path, "entries": entries}

    def test_new_solver_pitfall_unregistered_red(self, tmp_path):
        """判据②：新增 solver 类坑无任何指针 → 红（合成样本）。"""
        setup = self._synthetic_setup(tmp_path)
        playbook = _write_yaml(
            tmp_path / "playbook.yaml",
            {"schema": "rfauto-diag-playbook-v1", "rules": []})
        consumption = _write_yaml(
            tmp_path / "consumption.yaml",
            {"schema": CONSUMPTION_SCHEMA, "rows": []})
        rep = check_pitfall_consumption_sla(
            index_path=setup["index"], playbook_path=playbook,
            consumption_path=consumption)
        uncovered = {v["id"] for v in rep["violations"]
                     if v["kind"] == "uncovered_solver_pitfall"}
        assert uncovered == {"#900", "#901", "#902"}
        assert not rep["ok"]

    def test_full_cycle_green(self, tmp_path):
        """合成闭环：playbook 指针+登记行齐备 → 绿（门逻辑双向有效）。"""
        setup = self._synthetic_setup(tmp_path)
        playbook = _write_yaml(
            tmp_path / "playbook.yaml",
            {"schema": "rfauto-diag-playbook-v1",
             "rules": [{"id": "syn_rule", "pit_refs": ["#900"]}]})
        consumption = _write_yaml(
            tmp_path / "consumption.yaml",
            {"schema": CONSUMPTION_SCHEMA, "rows": [
                {"id": "#901", "surface": "index_search",
                 "pointer": "service/pitfall_index_service.py",
                 "keywords": ["HFSS"], "note": "合成行"},
                {"id": "#902", "surface": "index_search",
                 "pointer": "service/pitfall_index_service.py",
                 "keywords": ["COMSOL"], "note": "合成行"},
            ]})
        rep = check_pitfall_consumption_sla(
            index_path=setup["index"], playbook_path=playbook,
            consumption_path=consumption)
        assert rep["ok"], f"合成闭环应绿：{rep['violations']}"
        assert rep["n_solver_entries"] == 3
        assert rep["n_covered"] == 3

    def test_non_solver_category_not_sla_scoped(self, tmp_path):
        """非 solver 类（python 等）不在 SLA 范围（spec：solver 四类）。"""
        setup = self._synthetic_setup(tmp_path)
        playbook = _write_yaml(tmp_path / "playbook.yaml",
                               {"schema": "x", "rules": []})
        consumption = _write_yaml(tmp_path / "consumption.yaml",
                                  {"schema": CONSUMPTION_SCHEMA, "rows": []})
        rep = check_pitfall_consumption_sla(
            index_path=setup["index"], playbook_path=playbook,
            consumption_path=consumption)
        uncovered = {v["id"] for v in rep["violations"]
                     if v["kind"] == "uncovered_solver_pitfall"}
        assert "#903" not in uncovered


class TestPointerValidity:
    def test_dangling_pit_ref_red(self, tmp_path):
        """判据③：pit_refs 坑号在坑账全集体反查不到（typo）→ 红。"""
        playbook = _write_yaml(
            tmp_path / "playbook.yaml",
            {"schema": "rfauto-diag-playbook-v1",
             "rules": [{"id": "typo_rule", "pit_refs": ["#99999"]}]})
        rep = check_pitfall_consumption_sla(playbook_path=playbook)
        kinds = [v["kind"] for v in rep["violations"]]
        assert "dangling_pit_ref" in kinds
        assert any("#99999" in v["detail"] for v in rep["violations"])

    @_LEDGER_SKIP
    def test_index_out_of_subset_refs_are_legal(self, tmp_path):
        """index 结构化子集外的真坑 ref（如 #262）不红——反查全集含
        项目规则 速查（坑账=index+项目规则 速查，seat 口径）。"""
        playbook = _write_yaml(
            tmp_path / "playbook.yaml",
            {"schema": "rfauto-diag-playbook-v1",
             "rules": [{"id": "real_rule", "pit_refs": ["#262", "#84"]}]})
        rep = check_pitfall_consumption_sla(playbook_path=playbook)
        assert not any(v["kind"] == "dangling_pit_ref"
                       for v in rep["violations"])

    def test_unknown_surface_red(self, tmp_path):
        """判据③：未知 surface → 红（面名漂移防）。"""
        consumption = _write_yaml(
            tmp_path / "consumption.yaml",
            {"schema": CONSUMPTION_SCHEMA, "rows": [
                {"id": "#232", "surface": "ghost_face",
                 "pointer": "somewhere", "note": "面名漂移样本"}]})
        rep = check_pitfall_consumption_sla(consumption_path=consumption)
        assert any(v["kind"] == "unknown_surface"
                   for v in rep["violations"])

    def test_unknown_row_id_red(self, tmp_path):
        """判据④：登记坑账全集不存在的坑 → 红（多报不放过 #316）。"""
        consumption = _write_yaml(
            tmp_path / "consumption.yaml",
            {"schema": CONSUMPTION_SCHEMA, "rows": [
                {"id": "#88888", "surface": "index_search",
                 "pointer": "service/pitfall_index_service.py",
                 "keywords": ["x"], "note": "幽灵坑样本"}]})
        rep = check_pitfall_consumption_sla(consumption_path=consumption)
        assert any(v["kind"] == "unknown_row_id"
                   for v in rep["violations"])

    def test_error_hint_row_pointer_must_be_true(self, tmp_path):
        """error_hint 行逐行实证：refs 无其坑号 → row_pointer_false。"""
        consumption = _write_yaml(
            tmp_path / "consumption.yaml",
            {"schema": CONSUMPTION_SCHEMA, "rows": [
                {"id": "#154", "surface": "error_hint",
                 "pointer": "fabricated",
                 "keywords": ["x"], "note": "#154 不在 hint refs"}]})
        rep = check_pitfall_consumption_sla(consumption_path=consumption)
        assert any(v["kind"] == "row_pointer_false"
                   for v in rep["violations"])

    def test_empty_pointer_red(self, tmp_path):
        consumption = _write_yaml(
            tmp_path / "consumption.yaml",
            {"schema": CONSUMPTION_SCHEMA, "rows": [
                {"id": "#232", "surface": "index_search",
                 "pointer": "", "keywords": ["x"], "note": "空指针"}]})
        rep = check_pitfall_consumption_sla(consumption_path=consumption)
        assert any(v["kind"] == "empty_pointer" for v in rep["violations"])


class TestFacesAlive:
    def test_hint_face_down_red(self, monkeypatch):
        """最低消费点检查：hint 规则表不可达 → dead_face 红。"""
        def _boom():
            raise RuntimeError("hint face down")
        monkeypatch.setattr(
            "rfauto.service.error_hints_service.list_hint_rules", _boom)
        rep = check_pitfall_consumption_sla()
        assert not rep["ok"]
        assert rep["faces"]["error_hint"]["ok"] is False
        assert any(v["kind"] == "dead_face" for v in rep["violations"])

    def test_id_tokens_compound_ids(self):
        """compound id 拆分：#149/#150/#155 → 三 token；带注记文本剥离。"""
        assert id_tokens("#149/#150/#155") == ["#149", "#150", "#155"]
        assert id_tokens("#311/#266（缝与过孔网格守卫）") == ["#311", "#266"]
        assert id_tokens("A216") == ["A216"]
        assert id_tokens("DP-8 P1 守卫") == []
        assert id_tokens(None) == []
        assert id_tokens(123) == []
