"""QM-9 mutmut 三段路 runner 测试（round16 P2，J 流）。

锚树：
- 段① 轮换计划：确定性、批存在性负例、批内模块/窄测/宽测字段齐、
  module 与 tests 真实存在（计划面不指幽灵文件）；
- 等价台账：装载/坏行跳过/分类（真幸存 vs 台账等价——#122 出口）；
- 段③ 复放：命令串生成含 apply/pytest/git checkout 三段；计划面把
  台账等价者排除在复放外（不浪费复放预算）；
- 报告面：markdown 渲染确定性 + schema 钉；
- 幸存行正则：`<id> survived` / `<id>: survived` 两形态；
- mutmut 可用性：装了钉 2.5.1 语义（_mutmut_exe 返回路径），未装时
  _mutmut_exe RuntimeError（诚实降级——本文件纯逻辑测试不依赖装，
  可用性测试按 find_spec skipif，df4⑤ 传递依赖判据含 scripts 助手）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "qm9_mutmut_run", _REPO / "scripts" / "qm9_mutmut_run.py")
assert _spec is not None and _spec.loader is not None
qm9 = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("qm9_mutmut_run", qm9)
_spec.loader.exec_module(qm9)

_HAS_MUTMUT = importlib.util.find_spec("mutmut") is not None


class TestRotationPlan:
    def test_plan_has_current_batch_with_fields(self):
        plan = qm9.plan_rotation()
        assert plan["ok"] and plan["batches"]
        for batch, modules in plan["batches"].items():
            for m in modules:
                for key in ("module", "tests", "replay_targets", "rationale"):
                    assert m.get(key), (batch, key)

    def test_plan_module_and_tests_exist_on_disk(self):
        # 计划面不指幽灵文件（轮换批登记=实存路径）
        for modules in qm9.ROTATION_PLAN.values():
            for m in modules:
                assert (_REPO / m["module"]).is_file(), m["module"]
                assert (_REPO / m["tests"]).is_file(), m["tests"]

    def test_single_batch_lookup(self):
        batch_id = sorted(qm9.ROTATION_PLAN)[0]
        r = qm9.plan_rotation(batch_id)
        assert r["ok"] and r["batch"] == batch_id
        assert r["modules"] == qm9.ROTATION_PLAN[batch_id]

    def test_unknown_batch_keyerror(self):
        with pytest.raises(KeyError):
            qm9.plan_rotation("1999-01")


class TestEquivalentLedger:
    def test_load_missing_file_is_empty(self, tmp_path):
        assert qm9.load_equivalent_ids(tmp_path / "none.jsonl") == {}

    def test_load_and_classify(self, tmp_path):
        p = tmp_path / "ledger.jsonl"
        p.write_text(json.dumps({
            "mutant_id": 42, "reason": "等价变异：交换独立语句序",
            "registered_by": "seat7", "registered_at": "2026-10-03T00:00:00+00:00",
        }, ensure_ascii=False) + "\n" + "not-json\n", encoding="utf-8")
        eq = qm9.load_equivalent_ids(p)
        assert 42 in eq and eq[42]["reason"].startswith("等价变异")
        # 坏行跳过留痕不中断
        assert len(eq) == 1
        c = qm9.classify_survivors([41, 42, 43], ledger_path=p)
        assert c["real_survivors"] == [41, 43]
        assert c["equivalent"] == [42]

    def test_classify_without_ledger_all_real(self, tmp_path):
        c = qm9.classify_survivors([7, 3], ledger_path=tmp_path / "none.jsonl")
        assert c["real_survivors"] == [3, 7] and c["equivalent"] == []


class TestReplayPlan:
    def test_command_has_apply_test_restore(self):
        cmd = qm9.replay_command(123, "src/rfauto/core/quantity.py",
                                 "tests/unit/test_quantity.py")
        assert cmd.startswith("mutmut apply 123")
        assert "pytest -q tests/unit/test_quantity.py" in cmd
        assert cmd.rstrip().endswith("git checkout -- src/rfauto/core/quantity.py")

    def test_plan_excludes_equivalent_from_replay(self, tmp_path, monkeypatch):
        monkeypatch.setattr(qm9, "parse_survivors", lambda: [5, 6])
        monkeypatch.setattr(qm9, "EQUIVALENT_LEDGER", tmp_path / "l.jsonl")
        batch_id = sorted(qm9.ROTATION_PLAN)[0]
        module = qm9.ROTATION_PLAN[batch_id][0]["module"]
        (tmp_path / "l.jsonl").write_text(json.dumps(
            {"mutant_id": 6, "reason": "eq", "registered_by": "t",
             "registered_at": "x"}) + "\n", encoding="utf-8")
        plan = qm9.build_replay_plan(batch_id)
        ids = [e["mutant_id"] for e in plan["replay_plan"]]
        assert plan["n_survivors_raw"] == 2
        assert plan["n_real"] == 1 and plan["n_equivalent"] == 1
        assert ids == [5]
        assert all(e["module"] == module for e in plan["replay_plan"])
        assert "选择伪幸存" in plan["replay_plan"][0]["note"]


class TestParsingAndReport:
    def test_results_section_parser_251_format(self):
        # mutmut 2.5.1 实测格式：段头→模块头→id 区间段落（2026-10-03）
        text = (
            "To apply a mutant on disk:\n"
            "    mutmut apply <id>\n"
            "\n"
            "To show a mutant:\n"
            "    mutmut show <id>\n"
            "\n"
            "\n"
            "Survived \U0001F62C (5)\n"
            "\n"
            "---- src/rfauto/core/quantity.py (5) ----\n"
            "\n"
            "1-2, 19, 24, 51-54\n"
            "\n"
            "Untested/skipped (169)\n"
            "\n"
            "---- src/rfauto/core/quantity.py (169) ----\n"
            "\n"
            "218-386\n"
        )
        sections = qm9.parse_mutmut_results_text(text)
        assert sections["Survived"] == [1, 2, 19, 24, 51, 52, 53, 54]
        assert sections["Untested/skipped"][0] == 218
        assert sections["Untested/skipped"][-1] == 386

    def test_results_parser_multiple_modules_and_sections(self):
        text = (
            "Suspicious \U0001F914 (12)\n"
            "\n"
            "---- src/a.py (12) ----\n"
            "\n"
            "3-5\n"
            "\n"
            "Survived \U0001F62C (1)\n"
            "\n"
            "---- src/b.py (1) ----\n"
            "\n"
            "9\n"
            "\n"
            "Killed \U0001F389 (100)\n"
            "\n"
            "---- src/b.py (100) ----\n"
            "\n"
            "1-8, 10\n"
        )
        sections = qm9.parse_mutmut_results_text(text)
        assert sections["Suspicious"] == [3, 4, 5]
        assert sections["Survived"] == [9]
        assert sections["Killed"] == [1, 2, 3, 4, 5, 6, 7, 8, 10]

    def test_results_parser_empty_text(self):
        assert qm9.parse_mutmut_results_text("") == {}

    @pytest.mark.skipif(not _HAS_MUTMUT,
                        reason="mutmut 未安装（dev extra）")
    def test_parse_survivors_uses_section_parser(self, monkeypatch):
        # 交接面走段解析（上一版逐行正则对 2.5.1 格式漏报 0 幸存——回归钉）
        monkeypatch.setattr(qm9, "_mutmut_exe",
                            lambda: "mutmut-stub")
        import subprocess as _sp

        class _FakeProc:
            stdout = "Survived \U0001F62C (2)\n\n---- m.py (2) ----\n\n7-8\n"
            returncode = 0

        monkeypatch.setattr(_sp, "run",
                            lambda *a, **k: _FakeProc())
        assert qm9.parse_survivors() == [7, 8]

    def test_summarize_derives_killed_from_sections(self, monkeypatch):
        # 2.5.1 不打印 Killed 段——killed=max_id−(survived+suspicious+untested)
        import subprocess as _sp

        text = ("Suspicious \U0001F914 (2)\n\n---- m.py (2) ----\n\n6-7\n"
                "Survived \U0001F62C (3)\n\n---- m.py (3) ----\n\n1-2, 9\n")
        class _FakeProc:
            stdout = text
            returncode = 0
        monkeypatch.setattr(qm9, "_mutmut_exe", lambda: "stub")
        monkeypatch.setattr(_sp, "run", lambda *a, **k: _FakeProc())
        s = qm9.summarize_results()
        assert s["n_total_mutants"] == 9
        assert s["n_survived"] == 3 and s["n_suspicious"] == 2
        assert s["n_killed"] == 4          # 9 − 3 − 2
        assert s["mutation_score_pct"] == 44.4

    def test_write_report_renders_deterministic_md(self, tmp_path, monkeypatch):
        monkeypatch.setattr(qm9, "REPORT_DIR", tmp_path)
        monkeypatch.setattr(qm9, "parse_survivors", lambda: [9])
        batch_id = sorted(qm9.ROTATION_PLAN)[0]
        path = qm9.write_report(batch_id, run_result={"ok": True, "batch": batch_id,
                                                      "results": []})
        assert path.exists() and path.name.startswith(f"report_{batch_id}_")
        md = next(f for f in tmp_path.glob("*.md"))
        text = md.read_text(encoding="utf-8")
        assert f"QM-9 mutmut 批报告：{batch_id}" in text
        assert "真幸存者全量复放计划" in text
        assert "mutant 9" in text
        # schema 钉 + JSON 可读
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema"] == "rfauto-qm9-mutmut-v1"

    def test_report_without_results_records_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(qm9, "REPORT_DIR", tmp_path)

        def boom():
            raise RuntimeError("mutmut 不可用")

        monkeypatch.setattr(qm9, "parse_survivors", boom)
        batch_id = sorted(qm9.ROTATION_PLAN)[0]
        path = qm9.write_report(batch_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "mutmut 不可用" in data["results_error"]


class TestMutmutAvailability:
    @pytest.mark.skipif(not _HAS_MUTMUT, reason="mutmut 未安装（dev extra）")
    def test_exe_resolves_when_installed(self):
        exe = qm9._mutmut_exe()
        assert Path(exe).is_file(), exe

    @pytest.mark.skipif(_HAS_MUTMUT, reason="mutmut 已安装（负例不可注入 PATH）")
    def test_exe_raises_honestly_when_missing(self):
        with pytest.raises(RuntimeError):
            qm9._mutmut_exe()
