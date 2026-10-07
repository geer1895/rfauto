"""QM-3 判据 JSON Schema 化（ge8b 席B8）：core/criteria_schema 合同钉。

三层钉：
1. **注册面真样本**——knowledge/criteria/v2 全库（3 active + 45 骨架，
   2026-10-03 实测）零 error；三 active 档的 criteria_id/decision_rule.form
   逐一钉死；
2. **词表收敛钉**——form/op/status/V&V 值域与 core/recast、core/vv_mapping
   一致；发明新词表（新 form/新 op/新状态）显式拒收；
3. **ge7 criteria.md 真实样本回放钉**——runs/ge7_ffrender 与
   runs/ge7_clwide 的预声明门转写为 criteria/v2（数值逐字取自 criteria.md
   冻结值），过 schema 后交 core/recast.replay_one 对归档产物重放，
   重放方向与归档判读一致（same/如实 not_judged）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rfauto.core.criteria_schema import (
    CRITERIA_SCHEMA_ID,
    DecisionRuleForm,
    GateOp,
    VVStatus,
    preflight_for_replay,
    validate_criteria_document,
    validate_registered_dir,
)
from rfauto.core.recast import replay_one

REPO = Path(__file__).resolve().parents[2]
CRITERIA_DIR = REPO / "knowledge" / "criteria" / "v2"

# ─── ① 注册面真样本（criteria/v2 全库） ─────────────────────────────────────


def test_registered_corpus_zero_error() -> None:
    """全库注册校验：3 active + 骨架全过、零 error（#316 方向：坏档不静默）。"""
    report = validate_registered_dir(CRITERIA_DIR)
    assert report["ok"] is True, report["errors"]
    assert report["n_active"] == 3
    assert report["n_skeleton"] >= 40  # 2026-10-03 实测 45；只钉下限防脆
    assert len(report["errors"]) == 0


def test_three_active_documents_pinned() -> None:
    """三 active 判据逐一过全合同；criteria_id 与 form 钉死（既有词表）。"""
    expected = {
        "df5_c3fix_sentinel.yaml": (
            "df5_c3fix_sentinel_four_gates", "multi_gate_all_pass"),
        "df6_dp10_scan.yaml": (
            "df6_dp10_scan_j1c_coverage", "threshold_gate"),
        "hfss_interdigital_check_m1.yaml": (
            "hfss_interdigital_check_m1", "nearest_reference_gate"),
    }
    for name, (cid, form) in expected.items():
        data = yaml.safe_load(
            (CRITERIA_DIR / name).read_text(encoding="utf-8"))
        doc = validate_criteria_document(data)
        assert doc.schema_id == CRITERIA_SCHEMA_ID
        assert doc.criteria_id == cid
        assert doc.decision_rule.form.value == form
        assert doc.status.value == "active_v2"
        # 词表收敛面：u_val 三分量齐、verdict_map 值域在 V&V 词表
        assert doc.u_val.u_num.source
        assert all(v in {m.value for m in VVStatus}
                   for v in doc.verdict_map.values())


# ─── ② 词表收敛（不发明新词表） ─────────────────────────────────────────────


def test_form_vocabulary_matches_recast() -> None:
    """form 枚举 ⊇ recast 三支持形态且逐字一致；重放二形=recast 直放面。"""
    from rfauto.core import recast as rc

    schema_forms = {m.value for m in DecisionRuleForm}
    recast_forms = {rc._FORM_MULTI_GATE, rc._FORM_THRESHOLD,
                    rc._FORM_NEAREST_REF}
    assert recast_forms <= schema_forms
    assert schema_forms - recast_forms == {"unmigrated_skeleton"}


def test_op_vocabulary_matches_recast_cmp() -> None:
    """门算子词表 = recast._cmp 支持域（≤/≥ 边界含、</> 严格）。"""
    assert {op.value for op in GateOp} == {"<=", ">=", "<", ">"}


def test_invented_form_rejected() -> None:
    """发明新 form（不在既有词表）→ 显式 ValidationError 不放行。"""
    data = yaml.safe_load(
        (CRITERIA_DIR / "df6_dp10_scan.yaml").read_text(encoding="utf-8"))
    data["decision_rule"]["form"] = "super_gate"
    with pytest.raises(ValidationError):
        validate_criteria_document(data)


def test_invented_op_and_vv_status_rejected() -> None:
    """发明门算子 / V&V 状态词 → 拒收（词表=代码显式扩）。"""
    data = yaml.safe_load(
        (CRITERIA_DIR / "df5_c3fix_sentinel.yaml").read_text(
            encoding="utf-8"))
    data["decision_rule"]["gates"]["dev_db"]["op"] = "<~>"
    with pytest.raises(ValidationError):
        validate_criteria_document(data)
    data2 = yaml.safe_load(
        (CRITERIA_DIR / "df6_dp10_scan.yaml").read_text(encoding="utf-8"))
    data2["verdict_map"]["PASS"] = "probably_fine"
    with pytest.raises(ValidationError):
        validate_criteria_document(data2)


def test_skeleton_form_not_replayable() -> None:
    """骨架档过合同但 preflight replayable=False（不冒充可重放，#122）。"""
    skel = sorted((CRITERIA_DIR / "skeleton").glob("*.yaml"))[0]
    data = yaml.safe_load(skel.read_text(encoding="utf-8"))
    doc = validate_criteria_document(data)
    assert doc.status.value == "skeleton_v2"
    pf = preflight_for_replay(data)
    assert pf["ok"] is True and pf["replayable"] is False
    assert any("skeleton_v2" in r for r in pf["reasons"])


def test_preflight_matches_recast_replay_reach() -> None:
    """preflight 判定与 recast.replay_one 实况一致：multi_gate/threshold
    直放出 verdict；nearest_reference 走 bespoke 路径不出 verdict。"""
    multigate = yaml.safe_load(
        (CRITERIA_DIR / "df5_c3fix_sentinel.yaml").read_text(
            encoding="utf-8"))
    threshold = yaml.safe_load(
        (CRITERIA_DIR / "df6_dp10_scan.yaml").read_text(encoding="utf-8"))
    nearest = yaml.safe_load(
        (CRITERIA_DIR / "hfss_interdigital_check_m1.yaml").read_text(
            encoding="utf-8"))
    assert preflight_for_replay(multigate)["replayable"] is True
    assert preflight_for_replay(threshold)["replayable"] is True
    pf_near = preflight_for_replay(nearest)
    assert pf_near["replayable"] is False
    assert any("nearest_reference_gate" in r for r in pf_near["reasons"])


# ─── ③ ge7 criteria.md 真实样本回放钉 ───────────────────────────────────────
# 转写纪律：threshold/参考值逐字取自 criteria.md 冻结值；evidence_path 指向
# 归档产物 JSON 的既有字段；归档零改写（recast 只读输入，#325/#326）。

_FFR = REPO / "runs" / "ge7_ffrender"
_CLW = REPO / "runs" / "ge7_clwide"


@pytest.mark.skipif(not (_FFR / "verdict_ge7.json").is_file(),
                    reason="ge7_ffrender 归档不在本机")
def test_replay_ge7_ffrender_gates() -> None:
    """ffrender G1（指向 ≤3°）/G2（束镜比 ≥10dB）转写回放 ≡ 归档逐门判定。

    criteria.md §3：G1 |err|≤3°、G2 specular zone max 低于峰 ≥10dB；
    归档 g1.pass=true / g2.pass_abs10=true（verdict_ge7.json）。整体
    verdict=FAIL 由 G4 截断门（布尔分支，非 v2 数值门形态）单独成立——
    故本两门文档 archived_verdict_path=None（不对单门文档比整体判），
    G4 界限如实注记。
    """
    artifact = json.loads((_FFR / "verdict_ge7.json").read_text(
        encoding="utf-8"))
    base = {
        "schema": "criteria/v2",
        "status": "active_v2",
        "runner_binding": "test_replay_pin",
        "u_val": {
            "u_num": {"source": "none_declared", "rule": "单门回放钉"},
            "u_input": {"source": "none_declared", "rule": "单门回放钉"},
            "u_D": {"source": "none_declared", "rule": "单门回放钉"},
        },
        "verdict_map": {"PASS": "validated", "FAIL": "not_validated"},
        "provenance": {"criteria_md": "runs/ge7_ffrender/criteria.md §3"},
    }
    g1 = validate_criteria_document({**base, "criteria_id": "ge7_ff_g1",
                                     "title": "指向门",
                                     "claim": {"quantity":
                                               "pointing_err_deg"},
                                     "evidence_fields":
                                     ["g1.pointing_err_deg"],
                                     "decision_rule": {
                                         "form": "threshold_gate",
                                         "threshold": 3.0,
                                         "comparison": "<="}})
    r1 = replay_one(artifact, g1.model_dump(by_alias=True),
                    evidence_path="g1.pointing_err_deg",
                    archived_verdict_path=None)
    assert r1["replay_verdict"] == "PASS"
    assert r1["detail"]["obs"] == pytest.approx(0.0)
    assert artifact["g1"]["pass"] is True  # 归档逐门判定同向

    g2 = validate_criteria_document({**base, "criteria_id": "ge7_ff_g2",
                                     "title": "束结构门",
                                     "claim": {"quantity":
                                               "beam_vs_specular_db"},
                                     "evidence_fields":
                                     ["g2.beam_vs_specular_db_abs10"],
                                     "decision_rule": {
                                         "form": "threshold_gate",
                                         "threshold": 10.0,
                                         "comparison": ">="}})
    r2 = replay_one(artifact, g2.model_dump(by_alias=True),
                    evidence_path="g2.beam_vs_specular_db_abs10",
                    archived_verdict_path=None)
    assert r2["replay_verdict"] == "PASS"
    assert r2["detail"]["obs"] == pytest.approx(
        artifact["g2"]["beam_vs_specular_db_abs10"])
    assert artifact["g2"]["pass_abs10"] is True


@pytest.mark.skipif(not (_CLW / "judge_wideband.json").is_file(),
                    reason="ge7_clwide 归档不在本机")
def test_replay_ge7_clwide_gates() -> None:
    """clwide G-coupling/G-through（f0 点值 ≤0.5dB，criteria.md §2 冻结值）
    转写回放 ≡ 归档 AGREE/DISAGREE 判读。"""
    artifact = json.loads((_CLW / "judge_wideband.json").read_text(
        encoding="utf-8"))
    base = {
        "schema": "criteria/v2",
        "status": "active_v2",
        "runner_binding": "test_replay_pin",
        "u_val": {
            "u_num": {"source": "none_declared", "rule": "单门回放钉"},
            "u_input": {"source": "none_declared", "rule": "单门回放钉"},
            "u_D": {"source": "none_declared", "rule": "单门回放钉"},
        },
        "verdict_map": {"PASS": "validated", "FAIL": "not_validated"},
        "provenance": {"criteria_md": "runs/ge7_clwide/criteria.md §2"},
    }
    # G-coupling_f0：|S31_OE@2.4 − (−11.2550)| ≤ 0.5dB；归档实测差
    # 0.7837dB → 重放 FAIL ≡ 归档 DISAGREE（V&V open 向如实 not_judged）
    g_c = validate_criteria_document({**base, "criteria_id": "ge7_clw_coupling",
                                      "title": "耦合点值门",
                                      "claim": {"quantity":
                                                "s31_f0_abs_diff_db"},
                                      "evidence_fields":
                                      ["g_coupling_f0.abs_diff_db"],
                                      "decision_rule": {
                                          "form": "threshold_gate",
                                          "threshold": 0.5,
                                          "comparison": "<="}})
    rc_ = replay_one(artifact, g_c.model_dump(by_alias=True),
                     evidence_path="g_coupling_f0.abs_diff_db",
                     archived_verdict_path="g_coupling_f0.verdict")
    assert rc_["replay_verdict"] == "FAIL"
    assert rc_["detail"]["obs"] == pytest.approx(0.7837, abs=1e-9)
    assert rc_["archived_verdict"] == "DISAGREE"
    assert rc_["direction"] == "not_judged"  # DISAGREE→open，如实不对向

    # G-through_f0：|S21_OE@2.4 − (−0.6078)| ≤ 0.5dB；归档 0.1208dB
    # → 重放 PASS ≡ 归档 AGREE（direction=same）
    g_t = validate_criteria_document({**base, "criteria_id": "ge7_clw_through",
                                      "title": "through 旁证门",
                                      "claim": {"quantity":
                                                "s21_f0_abs_diff_db"},
                                      "evidence_fields":
                                      ["g_through_f0.abs_diff_db"],
                                      "decision_rule": {
                                          "form": "threshold_gate",
                                          "threshold": 0.5,
                                          "comparison": "<="}})
    rt_ = replay_one(artifact, g_t.model_dump(by_alias=True),
                     evidence_path="g_through_f0.abs_diff_db",
                     archived_verdict_path="g_through_f0.verdict")
    assert rt_["replay_verdict"] == "PASS"
    assert rt_["detail"]["obs"] == pytest.approx(
        artifact["g_through_f0"]["abs_diff_db"])
    assert rt_["archived_verdict"] == "AGREE"
    assert rt_["direction"] == "same"


def test_preflight_blocks_before_replay() -> None:
    """重放前校验语义：坏档 preflight ok=False，且不交 replay（合同门前置）。"""
    data = yaml.safe_load(
        (CRITERIA_DIR / "df6_dp10_scan.yaml").read_text(encoding="utf-8"))
    data["claim"]["quantity"] = "Not_Snake"
    pf = preflight_for_replay(data)
    assert pf["ok"] is False and pf["replayable"] is False
    assert pf["reasons"]
    with pytest.raises(ValidationError):
        validate_criteria_document(data)
