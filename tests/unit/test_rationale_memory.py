"""阶段 7.7：设计理由记忆（TF-IDF 检索）测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def runs_dir(tmp_path):
    """预置带理由语料的 runs/：autotune 评判 + meta + 提案。"""
    runs = tmp_path / "runs"
    r1 = runs / "20260905_aaaaaaaa_test01"
    (r1 / "calibration").mkdir(parents=True)
    (r1 / "autotune.json").write_text(json.dumps({
        "verdict": "FAIL",
        "history": [{"issues": [
            {"kind": "freq_scale_no_param", "detail": "谷位偏离但无长度类可调参数"},
            {"kind": "rl_shallow", "detail": "RL -5.0dB 浅于 -8dB"}],
            "fixes": []}]}), encoding="utf-8")
    (r1 / "meta.json").write_text(json.dumps({
        "model": "wilkinson_power_divider", "adapter": "autotune:openems",
        "metrics": {"verdict": "FAIL"}}), encoding="utf-8")
    (r1 / "calibration" / "report.md").write_text(
        "# 校准报告\nLOOCV rho 0.85 mesh 0.45mm", encoding="utf-8")
    prop = runs / "agent_proposals"
    prop.mkdir()
    (prop / "p1.json").write_text(json.dumps({
        "rationale": "调宽 feed 线宽以改善匹配"}, ensure_ascii=False),
        encoding="utf-8")
    return str(runs)


class TestRationaleMemory:
    def test_index_and_search(self, runs_dir):
        from rfauto.service.rationale_memory import build_index, search_rationale

        idx = build_index(runs_dir)
        assert idx["ok"] and idx["n_docs"] >= 3
        r = search_rationale("RL 浅于", idx, top_k=3)
        assert r["ok"] and r["hits"]
        assert "autotune" in r["hits"][0]["doc_id"]
        assert r["hits"][0]["score"] > 0

    def test_no_match_empty_hits(self, runs_dir):
        from rfauto.service.rationale_memory import build_index, search_rationale

        idx = build_index(runs_dir)
        r = search_rationale("zzz_nonexistent_term", idx)
        assert r["ok"] and r["hits"] == []

    def test_empty_runs_rejected(self, tmp_path):
        from rfauto.service.rationale_memory import build_index

        (tmp_path / "empty_runs").mkdir()
        assert not build_index(tmp_path / "empty_runs")["ok"]


# ---------------------------------------------------------------------------
# F11 自进化经验记忆：typed 经验条目 + 确定性检索 + skill_service 接线
# （验收口径：注入 #198/#219 后新模板冒烟前
#   命中"网格伪象核对表"并要求先离线审计）
# ---------------------------------------------------------------------------


class TestTypedExperienceEntry:
    def test_entry_schema_roundtrip(self):
        from rfauto.service.rationale_memory import ExperienceEntry

        entry = ExperienceEntry(
            lesson_id="#198",
            conclusion="带缘未入网 → 激励体积为零",
            evidence_paths=("经验档案（#198）", "src/rfauto/adapters/openems_templates.py"),
            applies_to=("ratrace", "带缘"),
            action="先离线审计后冒烟",
            checklist="网格伪象核对表",
            requires_offline_audit=True,
        )
        assert ExperienceEntry.from_dict(entry.to_dict()) == entry
        assert entry.to_dict()["schema_version"] == 1
        assert entry.to_dict()["evidence_paths"] == [
            "经验档案（#198）", "src/rfauto/adapters/openems_templates.py"]

    def test_payload_roundtrip_builtin(self):
        from rfauto.service.rationale_memory import (
            BUILTIN_ENTRIES,
            entries_from_payload,
            entries_to_payload,
        )

        payload = entries_to_payload(BUILTIN_ENTRIES)
        assert payload["schema_version"] == 1
        assert entries_from_payload(payload) == list(BUILTIN_ENTRIES)
        assert {e.lesson_id for e in BUILTIN_ENTRIES} >= {"#198", "#219", "#152"}

    def test_loose_lesson_aliases_normalized(self):
        from rfauto.service.rationale_memory import entry_from_lesson

        entry = entry_from_lesson({
            "坑编号": "#219",
            "结论": "栅格化伪象：六门低端全过随 f 劣化",
            "证据路径": ["经验档案（廿九）"],
            "适用场景": ["环形", "栅格化"],
            "动作": "先离线审计：查等效 εeff 是否超闭式上限",
            "核对表": "网格伪象核对表",
            "先离线审计": True,
        })
        assert entry.lesson_id == "#219"
        assert entry.evidence_paths == ("经验档案（廿九）",)
        assert entry.applies_to == ("环形", "栅格化")
        assert entry.requires_offline_audit is True


class TestDeterministicRecall:
    def test_recall_hits_mesh_checklist_for_ring_template(self):
        from rfauto.service.rationale_memory import (
            MESH_ARTIFACT_CHECKLIST,
            recall_for,
        )

        r = recall_for("新模板 ratrace 环形带缘 冒烟前检查")
        assert r["ok"]
        assert MESH_ARTIFACT_CHECKLIST in r["checklists"]
        assert r["require_offline_audit"] is True
        assert any("先离线审计" in a for a in r["actions"])
        assert {h["lesson_id"] for h in r["hits"]} >= {"#198", "#219"}
        # 命中条目带证据链与核对表
        top = r["hits"][0]
        assert top["checklist"] == MESH_ARTIFACT_CHECKLIST
        assert top["evidence_paths"]

    def test_recall_hits_for_bend_template_mapping(self):
        from rfauto.service.rationale_memory import recall_for

        r = recall_for({"template": "bend 弯折微带线", "stage": "smoke",
                        "tags": ["新模板"]})
        assert r["ok"] and r["hits"]
        assert "网格伪象核对表" in r["checklists"]
        assert r["require_offline_audit"] is True
        assert r["hits"][0]["lesson_id"] == "#198"

    def test_unrelated_task_no_hit(self):
        from rfauto.service.rationale_memory import recall_for

        r = recall_for("整理 会议纪要 与 目录 结构")
        assert r["ok"]
        assert r["hits"] == []
        assert r["checklists"] == []
        assert r["require_offline_audit"] is False

    def test_deterministic_same_input_twice(self):
        from rfauto.service.rationale_memory import recall_for

        a = json.dumps(recall_for("新模板 ratrace 环形 冒烟"),
                       ensure_ascii=False, sort_keys=True)
        b = json.dumps(recall_for("新模板 ratrace 环形 冒烟"),
                       ensure_ascii=False, sort_keys=True)
        assert a == b

    def test_empty_task_rejected(self):
        from rfauto.service.rationale_memory import recall_for

        assert recall_for("   ")["ok"] is False
        assert recall_for({})["ok"] is False

    def test_checklist_for_gate_requires_offline_audit(self):
        from rfauto.service.rationale_memory import checklist_for

        r = checklist_for("ratrace", extras="环形 带缘 新模板 冒烟")
        assert r["ok"]
        assert "网格伪象核对表" in r["checklists"]
        assert r["require_offline_audit"] is True
        assert "先离线审计" in r["gate"]

    def test_checklist_for_unrelated_template_empty(self):
        from rfauto.service.rationale_memory import checklist_for

        r = checklist_for("document_layout")
        assert r["ok"] and r["checklists"] == [] and r["gate"] == ""
        assert r["require_offline_audit"] is False


class TestInjectedLessonsRecall:
    def test_injected_198_219_hits_mesh_checklist(self):
        from rfauto.service.rationale_memory import entries_from_lessons, recall_for

        lessons = [
            {"坑编号": "#198", "结论": "带缘未入网 → 激励体积为零",
             "证据路径": ["经验档案（#198）"],
             "适用场景": ["ratrace", "带缘", "环形"],
             "动作": "先离线审计：渲染→exec 几何段→CSXCAD 实测带宽/连通性",
             "核对表": "网格伪象核对表", "先离线审计": True},
            {"坑编号": "#219", "结论": "0.4mm 阶梯环栅格化伪象",
             "证据路径": ["经验档案（廿九）"],
             "适用场景": ["ratrace", "环形", "栅格化"],
             "动作": "先离线审计：查等效 εeff 是否超闭式上限",
             "核对表": "网格伪象核对表", "先离线审计": True},
        ]
        entries = entries_from_lessons(lessons)
        r = recall_for("新模板 ratrace 环形冒烟", entries)
        assert r["ok"] and len(r["hits"]) == 2
        assert "网格伪象核对表" in r["checklists"]
        assert r["require_offline_audit"] is True
        assert all("先离线审计" in h["action"] for h in r["hits"])
        # 双向：注入的历史对不相关任务不生效（防空转）
        assert recall_for("整理 会议纪要", entries)["hits"] == []

    def test_render_checklist_contains_evidence_and_gate(self):
        from rfauto.service.rationale_memory import recall_for, render_checklist

        text = render_checklist(recall_for("ratrace 环形带缘"))
        assert "网格伪象核对表" in text
        assert "先离线审计" in text
        assert "#198" in text or "#219" in text
        assert "证据：" in text
        assert render_checklist(recall_for("整理 会议纪要")) == ""

    def test_save_load_entries_file(self, tmp_path):
        from rfauto.service.rationale_memory import (
            BUILTIN_ENTRIES,
            load_entries,
            recall_for,
            save_entries,
        )

        path = tmp_path / "experience.json"
        saved = save_entries(path, BUILTIN_ENTRIES)
        assert saved["ok"] and saved["n_entries"] == len(BUILTIN_ENTRIES)
        loaded = load_entries(path)
        assert loaded["ok"]
        assert loaded["entries"] == list(BUILTIN_ENTRIES)
        assert recall_for("ratrace 环形", loaded["entries"])["checklists"] == [
            "网格伪象核对表"]

    def test_load_missing_file_rejected(self, tmp_path):
        from rfauto.service.rationale_memory import load_entries

        assert load_entries(tmp_path / "nope.json")["ok"] is False


class TestSkillServiceExperienceWiring:
    def _recipe(self, tmp_path):
        recipe = {
            "model": "ratrace_hybrid",
            "params": {},
            "setup": {"freq_range_ghz": [2.0, 2.5]},
            "objectives": [{"metric": "s11_db", "op": "max_below", "value": -15,
                            "band": [2.0, 2.5]}],
            "optimization": {"params": {"ring_radius_mm": {"low": 5.0, "high": 9.0}}},
        }
        path = tmp_path / "recipe.yaml"
        path.write_text(yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")
        return path

    def test_experience_to_skill_contract(self):
        from rfauto.service.skill_service import experience_to_skill

        r = experience_to_skill(task="新模板 ratrace 环形带缘 冒烟")
        assert r["ok"]
        assert r["content"].startswith("---\n")
        assert f"name: {r['skill_name']}" in r["content"]
        assert "网格伪象核对表" in r["content"]
        assert "先离线审计" in r["content"]
        assert r["n_entries"] >= 3
        assert r["recall"]["require_offline_audit"] is True

    def test_write_experience_skill_idempotent(self, tmp_path):
        from rfauto.service.skill_service import write_experience_skill

        out = tmp_path / "skills"
        first = write_experience_skill(output_dir=out)
        assert first["written"]
        text_a = Path(first["output_path"]).read_text(encoding="utf-8")
        second = write_experience_skill(output_dir=out)
        assert Path(second["output_path"]).read_text(encoding="utf-8") == text_a

    def test_recipe_to_skill_with_recall_additive(self, tmp_path):
        from rfauto.service.skill_service import recipe_to_skill, recipe_to_skill_with_recall

        path = self._recipe(tmp_path)
        base = recipe_to_skill(path)
        aug = recipe_to_skill_with_recall(path, "新模板 ratrace 环形带缘 冒烟")
        assert base["ok"] and aug["ok"]
        # 既有章节原样保留（加性），核对表插在边界章之前
        for marker in ("## 标准工作流", "## 边界（硬约束）", "rfauto autotune"):
            assert marker in aug["content"]
        assert "网格伪象核对表" in aug["content"]
        assert "先离线审计" in aug["content"]
        assert aug["content"].index("网格伪象核对表") < aug["content"].index("## 边界（硬约束）")
        assert len(aug["content"]) > len(base["content"])
        assert aug["offline_audit_required"] is True

    def test_recipe_to_skill_with_recall_unrelated_noop(self, tmp_path):
        from rfauto.service.skill_service import recipe_to_skill, recipe_to_skill_with_recall

        path = self._recipe(tmp_path)
        base = recipe_to_skill(path)
        aug = recipe_to_skill_with_recall(path, "整理 会议纪要")
        assert aug["content"] == base["content"]
        assert aug["offline_audit_required"] is False

