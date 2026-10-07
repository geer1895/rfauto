"""AD-8 level2 链尾闭环测试（level2_closure：certify+锚回写草案+replan）。

全部离线（fake 闭式链，秒级）；判据单源钉面：replan 路由复用
replan_service 决策表、certify 委托 certify_design 内核——本套件不另立阈值。
"""

from __future__ import annotations

import json

import yaml

from rfauto.service.level2_closure import (
    anchor_writeback_draft,
    build_certify_samples,
    certify_chain_design,
    certify_objectives,
    close_level2_chain,
    replan_after_chain,
)
from rfauto.service.level2_design import design_chain

_WILKINSON_PROMPT = "设计一个 2.4GHz Wilkinson 功分器，50 欧姆"


def _wilkinson_record(task_id: str = "c8_probe") -> dict:
    return design_chain({"id": task_id, "prompt": _WILKINSON_PROMPT}, None)


class TestCertifyObjectives:
    def test_resonant_family_single_threshold(self):
        objs = certify_objectives("wilkinson", 2.4)
        assert len(objs) == 1
        assert objs[0]["op"] == "max_below"
        assert objs[0]["metric"] == "s11_db_min"

    def test_atten_pi_interval_decomposed_into_two_thresholds(self):
        objs = certify_objectives("atten_pi", 2.4, {"atten_db": 10.0})
        ops = sorted(o["op"] for o in objs)
        assert ops == ["max_below", "min_above"]
        # 区间 [-(a+tol), -(a-tol)] 忠实二分解
        values = sorted(o["value"] for o in objs)
        assert values == [-11.0, -9.0]

    def test_flat_family_envelope(self):
        objs = certify_objectives("mline", 2.4)
        assert objs[0]["metric"] == "s11_db" and objs[0]["op"] == "max_below"


class TestBuildCertifySamples:
    def test_samples_shape_and_requirement_keys_excluded(self):
        record = _wilkinson_record()
        built = build_certify_samples(record, n_samples=9, seed=42)
        assert built["ok"] and len(built["samples"]) == 9
        assert "f0_ghz" not in built["bounds"]  # 需求量键不进公差盒
        assert set(built["bounds"]) == {"arm_len_mm", "series_w_mm",
                                        "shunt_w_mm"}
        for sample in built["samples"]:
            assert "cost" in sample and sample["metrics"]

    def test_deterministic_same_seed_same_json(self):
        record = _wilkinson_record()
        a = build_certify_samples(record, n_samples=7, seed=42)
        b = build_certify_samples(record, n_samples=7, seed=42)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_missing_family_rejected(self):
        out = build_certify_samples({"synthesis_params": {"x_mm": 1.0}})
        assert not out["ok"]

    def test_missing_params_rejected(self):
        out = build_certify_samples({"family": "wilkinson"})
        assert not out["ok"]

    def test_bad_tolerance_rejected(self):
        out = build_certify_samples(_wilkinson_record(), tolerance_pct=1.5)
        assert not out["ok"] and "tolerance_pct" in out["errors"][0]


class TestCertifyChainDesign:
    def test_certificate_is_three_value(self):
        record = _wilkinson_record()
        out = certify_chain_design(record)
        assert out["ok"] and out["step"] == "certify"
        cert = out["certificate"]
        assert cert["ok"]
        verdicts = {c["verdict"] for c in cert["certificates"]}
        assert verdicts <= {"PASS", "FAIL", "UNKNOWN"}
        assert cert["n_pass"] + cert["n_fail"] + cert["n_unknown"] == len(
            cert["certificates"])

    def test_deterministic_verdicts(self):
        record = _wilkinson_record()
        a = certify_chain_design(record)
        b = certify_chain_design(record)
        assert a["certificate"]["verdict"] == b["certificate"]["verdict"]

    def test_samples_persisted_when_out_dir(self, tmp_path):
        out = certify_chain_design(_wilkinson_record("c8_persist"),
                                   out_dir=tmp_path)
        assert out["ok"] and out["samples_path"]
        path = tmp_path / "certify_samples_c8_persist.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert {"samples", "bounds", "objectives"} <= set(payload)

    def test_no_temp_file_leak_without_out_dir(self):
        out = certify_chain_design(_wilkinson_record("c8_notmp"))
        assert out["ok"] and out["samples_path"] is None
        cert = out["certificate"]
        # 临时样本集即用即清
        import os

        assert not os.path.exists(cert["samples_path"])


class TestAnchorWriteback:
    def test_no_correction_not_applicable(self):
        out = anchor_writeback_draft(_wilkinson_record())
        assert out["ok"] and out["action"] == "not_applicable"
        assert out["draft"] is None

    def test_applied_correction_produces_draft_with_residual(self):
        record = _wilkinson_record()
        record["anchor_correction"] = {
            "applied": True, "family": "patch", "quantity": "f_dip_L",
            "anchor_id": "patch.f_dip_l.openems-v1", "version": 1,
            "kind": "constant", "value": 76.8, "unit": "GHz·mm",
            "delta": None, "delta_kind": "absolute", "band": 3.84,
            "band_rel": 0.05, "domain_ok": True,
            "injection": {"key": "patch_len_mm", "mode": "constant_over_f0",
                          "old_value": 32.0, "new_value": 32.0},
        }
        record["metrics"] = {"f_dip_ghz": 2.4}
        out = anchor_writeback_draft(record)
        assert out["ok"] and out["action"] == "update_last_verified"
        entry = out["draft"]["anchors"][0]
        assert entry["anchor_id"] == "patch.f_dip_l.openems-v1"
        assert entry["proposed_action"] == "update_last_verified"
        assert entry["status"] == "draft_pending_human_review"
        ev = entry["evidence"]
        # 预测=锚值/注入后键值；残差=实测−预测（constant_over_f0 语义）
        assert ev["predicted_f_dip_ghz"] == 76.8 / 32.0
        assert ev["residual_ghz"] == 2.4 - 76.8 / 32.0

    def test_no_injection_no_predicted_but_delta_kept(self):
        record = _wilkinson_record()
        record["anchor_correction"] = {
            "applied": True, "anchor_id": "c3.l_via_h.openems-hfss-v1",
            "version": 1, "value": 0.125e-9, "delta": -0.17e-9,
            "delta_kind": "absolute", "injection": None,
        }
        out = anchor_writeback_draft(record)
        ev = out["draft"]["anchors"][0]["evidence"]
        assert ev["predicted_f_dip_ghz"] is None
        assert ev["residual_ghz"] is None
        assert ev["correction"]["delta"] == -0.17e-9

    def test_draft_written_to_runs_style_dir(self, tmp_path):
        record = _wilkinson_record("c8_draft")
        record["anchor_correction"] = {
            "applied": True, "anchor_id": "patch.f_dip_l.openems-v1",
            "version": 1, "value": 76.8,
            "injection": {"key": "patch_len_mm",
                          "mode": "constant_over_f0",
                          "old_value": 32.0, "new_value": 32.0}}
        out = anchor_writeback_draft(record, out_dir=tmp_path)
        path = tmp_path / "anchor_writeback_c8_draft.draft.yaml"
        assert out["draft_path"] == str(path) and path.exists()
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert payload["schema"] == "anchors/v1" and payload["draft"] is True

    def test_out_dir_inside_knowledge_root_rejected(self, tmp_path,
                                                    monkeypatch):
        from rfauto.service import level2_closure

        monkeypatch.setattr(level2_closure, "_knowledge_root",
                            lambda: tmp_path.resolve())
        record = _wilkinson_record()
        record["anchor_correction"] = {"applied": True, "anchor_id": "a",
                                       "version": 1, "value": 1.0}
        out = anchor_writeback_draft(record, out_dir=tmp_path)
        assert not out["ok"] and "不得指向锚注册表目录" in out["errors"][0]


class TestReplanAfterChain:
    def test_chain_error_routes_rerun(self):
        record = {"id": "x", "error": "ValueError: 关键词零命中"}
        out = replan_after_chain(record)
        assert out["action"] == "rerun_chain"
        assert out["channel"] == "keyword_fallback"

    def test_degenerate_trace_routes_switch(self):
        record = {"kickoff": {"kickoff_status": "failed",
                              "real_cost_trace": [2.0, 2.0, 2.0, 2.0]}}
        out = replan_after_chain(record)
        # 常数轨迹退化 + 显式指标可用 → replan_service 决策表 D4/D5
        assert out["action"] in ("switch_metric", "switch_sampler")
        assert out["degenerate"] is True
        assert out["value_source"] == "cost"

    def test_healthy_trace_routes_proceed(self):
        record = {"kickoff": {"real_cost_trace": [10.0, 5.0, 2.0, 1.0]}}
        out = replan_after_chain(record)
        assert out["action"] == "proceed"

    def test_kickoff_failed_without_trace_inspects(self):
        record = {"kickoff": {"kickoff_status": "failed"}}
        out = replan_after_chain(record)
        assert out["action"] == "inspect_kickoff_error"

    def test_no_numeric_record_holds(self):
        out = replan_after_chain({"kickoff": {}})
        assert out["action"] == "hold"


class TestCloseLevel2Chain:
    def test_full_envelope_three_steps(self):
        envelope = close_level2_chain(_wilkinson_record("c8_full"),
                                      out_dir=None)
        assert envelope["ok"] and envelope["task_id"] == "c8_full"
        assert envelope["certify"]["ok"]
        assert envelope["anchor_writeback"]["ok"]
        assert envelope["replan"]["ok"]

    def test_step_flags_disable(self):
        envelope = close_level2_chain(_wilkinson_record(), out_dir=None,
                                      certify=False, anchor_writeback=False,
                                      replan=False)
        assert envelope["certify"] is None
        assert envelope["anchor_writeback"] is None
        assert envelope["replan"] is None
        assert envelope["ok"] is True  # 全关=无启用步=无失败

    def test_single_step_failure_does_not_kill_others(self):
        record = {"id": "x", "family": "wilkinson"}  # 缺 synthesis_params
        envelope = close_level2_chain(record, out_dir=None)
        assert not envelope["certify"]["ok"]
        assert envelope["anchor_writeback"]["ok"]
        assert envelope["replan"]["ok"]
        assert not envelope["ok"]  # 有启用步失败 → 包络如实 False
        assert envelope["errors"]

    def test_persisted_artifacts_layout(self, tmp_path):
        envelope = close_level2_chain(_wilkinson_record("c8_layout"),
                                      out_dir=tmp_path)
        assert envelope["ok"]
        names = {p.name for p in tmp_path.iterdir()}
        assert any(n.startswith("certify_samples_") for n in names)
        assert "anchor_writeback_c8_layout.draft.yaml" not in names  # 未命中锚
