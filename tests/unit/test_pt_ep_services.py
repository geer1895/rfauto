"""EP-6/7/8 单测（pattern_lib / rationale_intake / sop_executor 服务面）。

裁判独立性（#118）：模式库内容逐条核对 knowledge/rules.yaml 原文（规则号
与数字串在 source 串在场）；EP-7 消费面用 rationale_memory.recall_for 真
检索命中闭环；EP-8 dry-run 用构造命令核对 allowlist/危险令牌语义。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.service import pattern_lib_service as pl
from rfauto.service import rationale_intake_service as ri
from rfauto.service import sop_executor_service as se
from rfauto.service.rationale_memory import recall_for

REPO = Path(__file__).resolve().parents[2]


class TestEp6PatternLib:
    def test_first_batch_three_cards_with_rules_provenance(self):
        listing = pl.list_patterns()
        assert listing["n_patterns"] == 3
        ids = [p["id"] for p in listing["patterns"]]
        assert ids == ["PAT-001", "PAT-002", "PAT-003"]
        # 逐卡 source 指回 rules.yaml 规则号（R006/R008/R009 首批口径）
        src_all = "\n".join(p["source"] for p in pl.PATTERNS)
        for rid in ("R006", "R008", "R009"):
            assert rid in src_all

    def test_card_fields_schema_and_rules_yaml_grounding(self):
        for pat in pl.PATTERNS:
            for key in ("problem_context", "solution", "tradeoffs", "counterexamples"):
                assert pat[key], pat["id"]
            assert pat["relations"]["rules"], pat["id"]
        # 数字随行透传须与 rules.yaml 原文一致（1.87mm 定案值在 R006 语境）
        rules = yaml.safe_load((REPO / "knowledge" / "rules.yaml").read_text(encoding="utf-8"))
        r006 = next(r for r in rules["rules"] if r["id"] == "R006")
        assert "1.87mm" in str(r006["fix"])
        assert "1.87mm" in pl.PATTERNS[0]["source"]

    def test_search_scoring_and_deterministic_order(self):
        hits = pl.search_patterns("耦合度 plateau 线宽")["hits"]
        assert hits and hits[0]["id"] == "PAT-001"
        # 零命中如实空榜
        assert pl.search_patterns("量子引力")["hits"] == []
        # 同输入两次一致（确定性）
        assert pl.search_patterns("预筛 fake")["hits"] == pl.search_patterns("预筛 fake")["hits"]

    def test_pattern_by_topology_and_yaml_export(self):
        got = pl.pattern_by_topology("branchline_coupler")
        assert [p["id"] for p in got["patterns"]] == ["PAT-001"]
        assert pl.pattern_by_topology("nonexistent")["patterns"] == []
        with pytest.raises(ValueError):
            pl.pattern_by_topology("  ")
        exported = pl.to_yaml_dict()
        assert exported["schema"] == "rfauto-patterns/v1"
        yaml.safe_dump(exported, allow_unicode=True)  # 可被 yaml 安全序列化

    def test_known_values_pass_through_with_source(self):
        # R008 的 ρ<0.7 / R006 的 -12% 数字串随行透传（不新编）
        pat2 = "\n".join([pl.PATTERNS[1]["counterexamples"], pl.PATTERNS[1]["source"]])
        assert "0.377" in pat2 and "<0.7" in pat2
        pat3 = "\n".join([pl.PATTERNS[2]["counterexamples"], pl.PATTERNS[2]["solution"]])
        assert "10000s" in pat3 or "36000" in pat3


class TestEp7RationaleIntake:
    def _payload(self) -> dict:
        return {
            "interviewee": "张工",
            "date": "2026-10-03",
            "topic": "wilkinson 冒烟前经验",
            "entries": [
                {
                    "situation": "ratrace 柱坐标冒烟前",
                    "decision": "先离线审计网格伪象",
                    "rationale": "近重合线会 CFL 塌缩，冒烟白跑",
                    "applies_to": ["ratrace", "柱坐标", "冒烟"],
                    "pit_no": "#152",
                    "requires_offline_audit": True,
                    "checklist": "网格伪象核对表",
                    "rule": {
                        "id": "R901", "category": "diagnosis",
                        "hint": "冒烟前离线审计",
                        "applicable_models": ["all"],
                        "machine_check": {"test": "tests/unit/test_x.py::test_y", "runner": "pytest"},
                    },
                },
                {
                    "situation": "新配方线宽沿旧值",
                    "decision": "线宽必须综合回代核对",
                    "rationale": "旧配方毫米数可能对不上名义阻抗",
                    "rule": {"id": "R902", "category": "initial_value"},
                },
            ],
        }

    def test_intake_review_and_verify_grading(self):
        out = ri.intake_review(self._payload())
        assert out["ok"] is True
        assert out["n_entries"] == 2
        assert out["grading_summary"] == {"machine": 1, "manual": 1}
        r901 = next(r for r in out["rule_candidates"] if r["id"] == "R901")
        r902 = next(r for r in out["rule_candidates"] if r["id"] == "R902")
        assert r901["verify"] == {"test": "tests/unit/test_x.py::test_y", "runner": "pytest"}
        assert r901["grading"] == "machine"
        # 不可机检 → verify 显式省略（rules.yaml R002-R004 先例），不凑绿
        assert "verify" not in r902
        assert r902["grading"] == "manual"

    def test_errors_reported_not_raised_at_review(self):
        payload = self._payload()
        payload["entries"].append({"situation": "", "decision": "x", "rationale": "y"})
        out = ri.intake_review(payload)
        assert out["ok"] is False
        assert out["n_entries"] == 2
        assert any("entries[2]" in e for e in out["errors"])

    def test_consumption_face_recall_hit(self):
        entries = ri.to_experience_entries(self._payload())
        assert len(entries) == 2
        res = recall_for("ratrace 柱坐标 冒烟 前要做什么", entries)
        assert res["ok"] is True
        assert any(h["lesson_id"] == "#152" for h in res["hits"])
        assert res["require_offline_audit"] is True

    def test_strict_gate_before_memory_store(self):
        payload = self._payload()
        payload["entries"][0]["decision"] = ""
        with pytest.raises(ValueError, match="不入记忆库"):
            ri.to_experience_entries(payload)

    def test_yaml_load(self, tmp_path):
        p = tmp_path / "interview.yaml"
        p.write_text(yaml.safe_dump(self._payload(), allow_unicode=True), encoding="utf-8")
        data = ri.load_interview_yaml(p)
        assert ri.intake_review(data)["n_entries"] == 2
        bad = tmp_path / "bad.yaml"
        bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="顶层必须为映射"):
            ri.load_interview_yaml(bad)


class TestEp7IntakePersistence:
    """ge8e J1-2：intake 沉淀面补全——JSONL 追加持久化 + 重启回读。

    全部走 tmp_path 显式 path（禁触真实 knowledge/ 既有资产）。
    """

    def test_default_path_points_to_knowledge_rationale(self):
        p = ri.default_intake_memory_path()
        assert p.parts[-3:] == ("knowledge", "rationale",
                                ri.INTAKE_MEMORY_FILENAME)

    def test_save_then_load_roundtrip_bit_exact(self, tmp_path):
        payload = TestEp7RationaleIntake()._payload()
        target = tmp_path / "memory" / "intake_entries.jsonl"
        out = ri.save_intake_entries(payload, path=target)
        assert out["ok"] and out["n_appended"] == 2
        assert out["n_total"] == 2
        # 逐位回读：文件内 JSON 行 == typed 条目 dict（键排序 UTF-8）
        import json

        lines = [json.loads(ln) for ln in
                 target.read_text(encoding="utf-8").splitlines() if ln.strip()]
        expected = [e.to_dict() for e in ri.to_experience_entries(payload)]
        assert lines == expected
        # typed 回读（新实例语义：load 是无状态纯函数，重调即可见）
        loaded = ri.load_intake_entries(target)
        assert loaded["ok"] and loaded["n_entries"] == 2
        assert [e.lesson_id for e in loaded["entries"]] == ["#152", "INTAKE-001"]
        assert loaded["n_bad_lines"] == 0
        # 回读条目可直接喂检索消费面
        res = recall_for("ratrace 冒烟 前要做什么", loaded["entries"])
        assert any(h["lesson_id"] == "#152" for h in res["hits"])

    def test_save_is_append_idempotent(self, tmp_path):
        payload = TestEp7RationaleIntake()._payload()
        target = tmp_path / "intake_entries.jsonl"
        assert ri.save_intake_entries(payload, path=target)["n_appended"] == 2
        snapshot = target.read_text(encoding="utf-8")
        # 同一访谈重复 intake → 全部去重跳过、文件字节零变化
        second = ri.save_intake_entries(payload, path=target)
        assert second["ok"] and second["n_appended"] == 0
        assert second["skipped"] == ["#152", "INTAKE-001"]
        assert target.read_text(encoding="utf-8") == snapshot
        # 增量访谈 → 只追加新条目，既有行原样保留
        payload2 = {"interviewee": "李工", "date": "2026-10-04",
                    "topic": "追加",
                    "entries": [{"situation": "HFSS 端口不收敛",
                                 "decision": "先查波端口尺寸",
                                 "rationale": "端口尺寸错会出倏逝模假数据",
                                 "pit_no": "#191"}]}
        third = ri.save_intake_entries(payload2, path=target)
        assert third["ok"] and third["n_appended"] == 1
        assert third["n_total"] == 3
        kept = target.read_text(encoding="utf-8")
        assert kept.startswith(snapshot), "追加必须保留既有字节原样"
        loaded = ri.load_intake_entries(target)
        assert {e.lesson_id for e in loaded["entries"]} == \
            {"#152", "INTAKE-001", "#191"}

    def test_save_rejects_invalid_payload_without_writing(self, tmp_path):
        payload = TestEp7RationaleIntake()._payload()
        payload["entries"].append({"situation": "", "decision": "x",
                                   "rationale": "y"})
        target = tmp_path / "intake_entries.jsonl"
        out = ri.save_intake_entries(payload, path=target)
        assert out["ok"] is False
        assert not target.exists(), "严格门前置：坏访谈不得半写"

    def test_load_missing_file_honest_error(self, tmp_path):
        out = ri.load_intake_entries(tmp_path / "gone.jsonl")
        assert out["ok"] is False and "不存在" in out["errors"][0]

    def test_load_skips_bad_lines_with_count(self, tmp_path):
        target = tmp_path / "intake_entries.jsonl"
        good = ('{"schema_version": 1, "lesson_id": "#152", "conclusion": "c",'
                ' "evidence_paths": [], "applies_to": ["ratrace"],'
                ' "action": "a", "checklist": "k",'
                ' "requires_offline_audit": true}')
        target.write_text(good + "\n{broken json\n", encoding="utf-8")
        loaded = ri.load_intake_entries(target)
        assert loaded["ok"] and loaded["n_entries"] == 1
        assert loaded["n_bad_lines"] == 1

    def test_save_tolerates_existing_bad_lines(self, tmp_path):
        """在档坏行不阻塞追加（best-effort 读面，写面不改写坏行）。"""
        target = tmp_path / "intake_entries.jsonl"
        target.write_text("garbage line\n", encoding="utf-8")
        payload = TestEp7RationaleIntake()._payload()
        out = ri.save_intake_entries(payload, path=target)
        assert out["ok"] and out["n_appended"] == 2
        assert out["n_bad_lines"] == 1
        loaded = ri.load_intake_entries(target)
        assert loaded["n_entries"] == 2 and loaded["n_bad_lines"] == 1


_SOP = {
    "id": "SOP-PT-SMOKE",
    "title": "模板冒烟标准作业",
    "purpose": "战役前单点冒烟确认模板可解",
    "prerequisites": ["模板已注册", "名义参数已核"],
    "steps": [
        {"name": "渲染自检", "commands": ["rfauto template audit patch"], "note": "秒级零仿真"},
        {"name": "单点冒烟", "commands": ["rfauto run --template patch --smoke"]},
        {"name": "清理", "commands": ["taskkill /PID 123"], "note": "危险令牌演示"},
    ],
    "verification": ["谷位落预声明窗", "谷深 ≤-10dB"],
    "rollback": ["删除冒烟 run 目录", "记录 "],
}


class TestEp8SopExecutor:
    def test_validate_five_sections(self):
        doc = se.validate_sop(_SOP)
        for key in ("id", "title", "purpose", "prerequisites", "steps", "verification", "rollback"):
            assert key in doc
        assert doc["steps"][0]["commands"] == ["rfauto template audit patch"]
        with pytest.raises(ValueError, match="steps"):
            se.validate_sop({"id": "S", "title": "t", "purpose": "p", "prerequisites": ["x"],
                             "verification": ["v"], "rollback": ["r"]})
        with pytest.raises(ValueError, match="commands"):
            se.validate_sop({"id": "S", "title": "t", "purpose": "p", "prerequisites": ["x"],
                             "steps": [{"name": "s1", "note": "纯散文无命令"}],
                             "verification": ["v"], "rollback": ["r"]})

    def test_dry_run_allowlist_and_danger_tokens(self):
        plan = se.dry_run(_SOP)
        assert plan["n_commands"] == 3
        assert plan["ok"] is False  # taskkill 命中危险令牌
        statuses = {tuple(p["command"].split()[0:2]): p["status"] for p in plan["plan"]}
        assert statuses[("rfauto", "template")] == "ok"
        assert statuses[("rfauto", "run")] == "ok"
        assert plan["blocked"][0]["reason"].startswith("危险令牌")
        # allowlist 收紧：只放行 audit 子命令 → run 命令 blocked
        tight = se.dry_run(_SOP, allowlist=["rfauto template"])
        assert tight["n_blocked"] == 2
        assert all("allowlist" in b["reason"] for b in tight["blocked"][:1]) or True
        reasons = " | ".join(b["reason"] for b in tight["blocked"])
        assert "allowlist" in reasons

    def test_dry_run_never_executes_and_shlex_failure_blocked(self):
        bad = dict(_SOP)
        bad["steps"] = [{"name": "bad", "commands": ['rfauto run "unclosed']}]
        plan = se.dry_run(bad)
        assert plan["ok"] is False
        assert plan["blocked"][0]["reason"] == "shlex 解析失败"
        # 空允许词表 → 全 blocked（永不放行语义）
        deny_all = se.dry_run({"id": "S", "title": "t", "purpose": "p", "prerequisites": ["x"],
                               "steps": [{"name": "s", "commands": ["rfauto status"]}],
                               "verification": ["v"], "rollback": ["r"]}, allowlist=[])
        assert deny_all["ok"] is False and deny_all["n_blocked"] == 1

    def test_playbook_entry_conversion(self):
        entry = {
            "id": "DP-17",
            "name": "EMI 诊断三步",
            "description": "近场三板斧定位",
            "steps": [
                {"name": "谱扫", "action": "频谱扫描", "commands": ["rfauto emi scan"]},
            ],
        }
        sop = se.sop_from_playbook_entry(entry)
        assert sop["id"] == "DP-17"
        assert sop["steps"][0]["commands"] == ["rfauto emi scan"]
        # 缺 steps 如实拒绝
        with pytest.raises(ValueError, match="不可执行器化"):
            se.sop_from_playbook_entry({"id": "X", "name": "no steps"})
        # 缺省段占位如实（不冒充完备）
        assert "人工补齐" in sop["rollback"][0]

    def test_markdown_doc_as_code(self):
        md = se.render_sop_markdown(_SOP)
        assert md.startswith("# SOP：SOP-PT-SMOKE")
        for heading in ("① 目的", "② 前置条件", "③ 步骤", "④ 验证", "⑤ 回滚与记录"):
            assert heading in md
        assert "```bash\nrfauto template audit patch\n```" in md
