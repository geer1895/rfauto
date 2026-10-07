"""RECAST 通用重放回收钉（月计划 F 流 B4 扩面；core/recast.py）。

判据预声明（core/recast.py 模块 docstring 同源）：
- 三向标注：same=归档/重放 V&V 类相同；flip=类不同（翻案必须显式浮出）；
  not_judged=任一侧证据缺失或归档侧开向（UNDECIDED/UNKNOWN 等）；
- 零改写：replay_one 对产物 dict 只读（快照逐键比对）；
- 加载合同：schema=criteria/v2 + REQUIRED_TOP 必备键（pilot 同款），
  坏条目登记不静默跳；nearest_reference_gate 登记 not_machine_replayable；
- 真档冒烟（runs/ 资产缺在即 skip，与 test_vv_recast 同约定）：
  df5_c3fix 哨四门 FAIL 档重放须 same（不翻案）。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.core.recast import (
    DIRECTION_FLIP,
    DIRECTION_NOT_JUDGED,
    DIRECTION_SAME,
    load_criteria_dir,
    replay_batch,
    replay_one,
)

REPO = Path(__file__).resolve().parents[2]
V2 = REPO / "knowledge" / "criteria" / "v2"
RUNS = REPO / "runs"


def _threshold_criteria(**over) -> dict:
    base = {
        "schema": "criteria/v2",
        "criteria_id": "syn_threshold_j1c",
        "title": "合成覆盖门",
        "status": "active_v2",
        "runner_binding": "followUp",
        "claim": {"quantity": "phase_coverage_deg", "template": "ms_patch",
                  "f_ghz": 10.0},
        "evidence_fields": ["gate.phase_coverage_deg"],
        "u_val": {"u_num": {"source": "none_declared", "rule": "r"},
                  "u_input": {"source": "none_declared", "rule": "r"},
                  "u_D": {"source": "none_declared", "rule": "r"}},
        "decision_rule": {"form": "threshold_gate", "threshold": 300.0,
                          "comparison": ">=",
                          "on_fail": "FAIL 如实落档（#122）",
                          "overall": "≥300°→PASS；<300°→FAIL"},
        "verdict_map": {"PASS": "validated", "FAIL": "not_validated"},
        "provenance": {"commit": "0" * 7, "devlog": "syn", "referee_run": "runs/x",
                       "gate_db_legacy": "syn"},
    }
    base.update(over)
    return base


def _multi_gate_criteria() -> dict:
    crit = _threshold_criteria(criteria_id="syn_multi_four_gates")
    crit["decision_rule"] = {
        "form": "multi_gate_all_pass",
        "gates": {
            "dev": {"op": "<=", "threshold": 0.5, "evidence": "g.dev.obs"},
            "span": {"op": ">=", "threshold": 20.0, "evidence": "g.span.obs"},
        },
        "budget_conditional": {"op": "<=", "ratio_limit": 1.5,
                               "on_exceed": "conditionally_validated"},
        "overall": "两门全过→PASS；任一不过→FAIL",
    }
    crit["verdict_map"] = {"PASS": "validated", "FAIL": "not_validated",
                           "PARTIAL": "conditionally_validated"}
    return crit


# ── 真判据目录加载（repo 资产，恒在） ───────────────────────────────────────

class TestLoadRealCriteriaDir:
    def test_three_registered_criteria_load_ok(self):
        entries = load_criteria_dir(V2)
        assert len(entries) == 3
        by_id = {e["criteria_id"]: e for e in entries}
        assert by_id["df5_c3fix_sentinel_four_gates"]["ok"]
        assert (by_id["df5_c3fix_sentinel_four_gates"]
                ["decision_rule_form"] == "multi_gate_all_pass")
        assert by_id["df6_dp10_scan_j1c_coverage"]["ok"]
        assert (by_id["df6_dp10_scan_j1c_coverage"]
                ["decision_rule_form"] == "threshold_gate")
        m1 = by_id["hfss_interdigital_check_m1"]
        assert m1["ok"]
        assert m1["decision_rule_form"] == "nearest_reference_gate"

    def test_missing_dir_empty_not_crash(self, tmp_path):
        assert load_criteria_dir(tmp_path / "nope") == []

    def test_bad_yaml_and_wrong_schema_registered_not_silent(self, tmp_path):
        (tmp_path / "broken.yaml").write_text("a: [unclosed", encoding="utf-8")
        (tmp_path / "wrong.yaml").write_text("schema: other/1\n",
                                             encoding="utf-8")
        entries = load_criteria_dir(tmp_path)
        assert len(entries) == 2
        assert all(not e["ok"] for e in entries)
        assert any("YAML 解析失败" in str(e["errors"]) for e in entries)
        assert any("criteria/v2" in str(e["errors"]) for e in entries)


# ── threshold_gate：三向标注回收 ────────────────────────────────────────────

class TestThresholdGateReplay:
    def test_same_direction_pass(self):
        crit = _threshold_criteria()
        art = {"gate": {"phase_coverage_deg": 340.0}, "verdict": "PASS"}
        rep = replay_one(art, crit, evidence_path="gate.phase_coverage_deg")
        assert rep["replay_verdict"] == "PASS"
        assert rep["replay_vv_status"] == "validated"
        assert rep["archived_vv_status"] == "validated"
        assert rep["direction"] == DIRECTION_SAME

    def test_same_direction_fail(self):
        crit = _threshold_criteria()
        art = {"gate": {"phase_coverage_deg": 200.0}, "verdict": "FAIL"}
        rep = replay_one(art, crit, evidence_path="gate.phase_coverage_deg")
        assert rep["replay_verdict"] == "FAIL"
        assert rep["direction"] == DIRECTION_SAME

    def test_flip_surfaced_not_silent(self):
        crit = _threshold_criteria()
        art = {"gate": {"phase_coverage_deg": 200.0}, "verdict": "PASS"}
        rep = replay_one(art, crit, evidence_path="gate.phase_coverage_deg")
        assert rep["direction"] == DIRECTION_FLIP
        assert any("翻案" in n for n in rep["notes"])
        assert rep["archived_verdict"] == "PASS"  # 原样保留，零改名

    def test_missing_evidence_not_judged(self):
        crit = _threshold_criteria()
        rep = replay_one({"verdict": "PASS"}, crit,
                         evidence_path="gate.phase_coverage_deg")
        assert rep["direction"] == DIRECTION_NOT_JUDGED
        assert rep["replay_verdict"] is None

    def test_unbound_evidence_path_not_judged_no_guess(self):
        crit = _threshold_criteria()
        rep = replay_one({"gate": {"phase_coverage_deg": 340.0},
                          "verdict": "PASS"}, crit)
        assert rep["direction"] == DIRECTION_NOT_JUDGED
        assert "不猜" in (rep["detail"].get("reason") or "")

    def test_archived_open_class_not_judged(self):
        crit = _threshold_criteria()
        art = {"gate": {"phase_coverage_deg": 340.0}, "verdict": "UNDECIDED"}
        rep = replay_one(art, crit, evidence_path="gate.phase_coverage_deg")
        assert rep["replay_vv_status"] == "validated"  # 重放侧有结论
        assert rep["archived_vv_status"] == "validation_not_attempted"
        assert rep["direction"] == DIRECTION_NOT_JUDGED

    def test_missing_archived_verdict_not_judged(self):
        crit = _threshold_criteria()
        art = {"gate": {"phase_coverage_deg": 340.0}}
        rep = replay_one(art, crit, evidence_path="gate.phase_coverage_deg")
        assert rep["direction"] == DIRECTION_NOT_JUDGED
        assert rep["archived_verdict"] is None


# ── multi_gate_all_pass + budget 注记 ──────────────────────────────────────

class TestMultiGateReplay:
    def test_all_pass_same(self):
        art = {"g": {"dev": {"obs": 0.406}, "span": {"obs": 24.0}},
               "budget": {"declared": 12000, "actual": 15600},
               "verdict": "PASS"}
        rep = replay_one(art, _multi_gate_criteria())
        assert rep["replay_verdict"] == "PASS"
        assert rep["direction"] == DIRECTION_SAME
        assert rep["detail"]["gates"]["dev"]["ok"] is True

    def test_gate_fail_same_as_archived_fail(self):
        art = {"g": {"dev": {"obs": 0.406}, "span": {"obs": 12.443}},
               "budget": {"declared": 12000, "actual": 15600},
               "verdict": "FAIL（fail_kind=gates）"}
        rep = replay_one(art, _multi_gate_criteria())
        assert rep["replay_verdict"] == "FAIL"
        assert rep["direction"] == DIRECTION_SAME  # 带尾注串前缀识别

    def test_budget_exceed_partial_annotation(self):
        art = {"g": {"dev": {"obs": 0.1}, "span": {"obs": 30.0}},
               "budget": {"declared": 1000, "actual": 2000},  # 比值 2.0>1.5
               "verdict": "PARTIAL"}
        rep = replay_one(art, _multi_gate_criteria())
        assert rep["replay_verdict"] == "PARTIAL"
        assert rep["replay_vv_status"] == "conditionally_validated"
        assert rep["archived_vv_status"] == "conditionally_validated"
        assert rep["direction"] == DIRECTION_SAME
        assert rep["detail"]["budget_ratio"] == pytest.approx(2.0)

    def test_hard_gate_fail_beats_budget(self):
        art = {"g": {"dev": {"obs": 0.9}, "span": {"obs": 30.0}},
               "budget": {"declared": 1000, "actual": 2000},
               "verdict": "FAIL"}
        rep = replay_one(art, _multi_gate_criteria())
        assert rep["replay_verdict"] == "FAIL"  # 硬门优先，预算注记救不了

    def test_flip_archived_pass_but_gates_fail(self):
        art = {"g": {"dev": {"obs": 0.9}, "span": {"obs": 10.0}},
               "verdict": "PASS"}
        rep = replay_one(art, _multi_gate_criteria())
        assert rep["direction"] == DIRECTION_FLIP

    def test_missing_gate_evidence_not_judged(self):
        art = {"g": {"dev": {"obs": 0.1}}, "verdict": "PASS"}  # span 缺
        rep = replay_one(art, _multi_gate_criteria())
        assert rep["replay_verdict"] is None
        assert rep["direction"] == DIRECTION_NOT_JUDGED


# ── nearest_reference_gate：登记不直放 ─────────────────────────────────────

class TestNearestReferenceRegistered:
    def test_registered_not_machine_replayable(self):
        entries = {e["criteria_id"]: e for e in load_criteria_dir(V2)}
        m1 = entries["hfss_interdigital_check_m1"]["criteria"]
        rep = replay_one({}, m1)
        assert rep["replay_verdict"] is None
        assert rep["direction"] == DIRECTION_NOT_JUDGED
        assert "非机器直放" in (rep["detail"].get("reason") or "")


# ── 批量重放（新判据→旧产物 双方向同一路径） ────────────────────────────────

class TestReplayBatch:
    def _write_dir(self, tmp_path: Path) -> Path:
        import yaml

        d = tmp_path / "v2"
        d.mkdir()
        (d / "t.yaml").write_text(
            yaml.safe_dump(_threshold_criteria(), allow_unicode=True),
            encoding="utf-8")
        (d / "m.yaml").write_text(
            yaml.safe_dump(_multi_gate_criteria(), allow_unicode=True),
            encoding="utf-8")
        return d

    def test_batch_counts_and_bindings(self, tmp_path):
        d = self._write_dir(tmp_path)
        arts = {
            "old_run_a": {"gate": {"phase_coverage_deg": 340.0},
                          "verdict": "PASS"},
            "old_run_b": {"gate": {"phase_coverage_deg": 200.0},
                          "verdict": "PASS"},  # 翻案样本
        }
        rep = replay_batch(arts, d, evidence_paths={
            "syn_threshold_j1c": "gate.phase_coverage_deg"})
        assert rep["summary"]["n_criteria"] == 2
        assert rep["summary"]["n_pairs"] == 4  # 2 判据 × 2 产物
        assert rep["summary"]["n_flip"] >= 1
        assert rep["summary"]["n_same"] >= 1
        assert rep["ok"] is True
        import json

        json.dumps(rep, ensure_ascii=False)

    def test_bad_criteria_does_not_poison_batch(self, tmp_path):

        d = self._write_dir(tmp_path)
        (d / "z_broken.yaml").write_text("schema: [", encoding="utf-8")
        rep = replay_batch(
            {"a": {"gate": {"phase_coverage_deg": 340.0}, "verdict": "PASS"}},
            d, evidence_paths={"syn_threshold_j1c": "gate.phase_coverage_deg"})
        assert rep["summary"]["n_criteria_error"] == 1
        assert rep["summary"]["n_pairs"] == 2
        assert rep["ok"] is False  # 有坏条目 → ok=False（多报方向）

    def test_archive_zero_rewrite(self, tmp_path):
        d = self._write_dir(tmp_path)
        art = {"gate": {"phase_coverage_deg": 340.0}, "verdict": "PASS"}
        snapshot = copy.deepcopy(art)
        replay_batch({"x": art}, d,
                     evidence_paths={"syn_threshold_j1c": "gate.phase_coverage_deg"})
        assert art == snapshot  # 输入逐键不变（#325/#326 零改写）


# ── 真档冒烟：df5_c3fix 哨四门（缺档 skip，同 test_vv_recast 约定） ─────────

def test_recast_real_sentinel_same_direction() -> None:
    verdict_path = RUNS / "df5_c3fix" / "sentinel_verdict.json"
    if not verdict_path.exists():
        pytest.skip("runs/df5_c3fix/sentinel_verdict.json 不在（干净检出）")
    import json

    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    entries = {e["criteria_id"]: e for e in load_criteria_dir(V2)}
    crit = entries["df5_c3fix_sentinel_four_gates"]["criteria"]
    snapshot = copy.deepcopy(verdict)
    # 哨档的归档 verdict 串在 four_gates.verdict（"FAIL（fail_kind=gates…）"）
    rep = replay_one(verdict, crit, archived_verdict_path="four_gates.verdict")
    assert verdict == snapshot  # 归档零改写
    assert rep["replay_verdict"] == "FAIL"  # 四门两门不过（span/s21_inf）→ FAIL
    assert rep["direction"] == DIRECTION_SAME  # 不翻案（与 bespoke 钉同向）
