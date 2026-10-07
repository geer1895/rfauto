"""XC-N 名义值闭式再生巡检门锚树（round15"nominal 可由 core 链 round 再现"）。

判据（#122/#118，独立来源）：
- patch 链绝对锚（XA-5 预声明）：synthesize_patch(2.4,3.66,0.508) →
  W=40.92±0.01mm（链再生本征值，与名义注册值无关）；
- compare 语义：同 round 位数逐位一致=MATCH；任一键双值分裂=MISMATCH
  （双值随行）；无覆盖键=NOT_COVERED（不猜）；
- 巡检编排：注入脏链（注册名义+1）必须命中 MISMATCH→issues（门真的
  能拦），注入干净链（再生=注册值构造）→MATCH→clean；
- 真实现状事实（预声明，2026-10-03 实测）：patch 注册名义 34.9/50.0/10.0
  vs 当前链 32.08/40.92/10.43 → 真注册表巡检 verdict=issues 且 patch
  MISMATCH 三键——**钉现状**（名义修复=单独裁决+adapters/docs 同 commit，
  修复后本测试随动更新）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
from rfauto.core.nominal_regen import (
    NOMINAL_REGEN_CHAINS,
    compare_nominal,
    regenerate_nominal,
)
from rfauto.service import nominal_regen_service as nrs


class TestPatchChain:
    def test_absolute_geometry_anchor_xa5(self):
        nominal = {"f0_ghz": 2.4, "er": 3.66, "h_mm": 0.508}
        regen = regenerate_nominal("patch", nominal)
        assert regen["verdict"] == "OK"
        assert regen["regenerated"]["patch_w_mm"] == pytest.approx(40.92,
                                                                   abs=0.01)
        assert regen["covered"] == ["feed_offset_mm", "patch_len_mm",
                                    "patch_w_mm"]

    def test_missing_input_not_run(self):
        regen = regenerate_nominal("patch", {"f0_ghz": 2.4})
        assert regen["verdict"] == "NOT_RUN"
        assert set(regen["missing_inputs"]) == {"er", "h_mm"}

    def test_unknown_template_not_covered(self):
        regen = regenerate_nominal("mline", {})
        assert regen["verdict"] == "NOT_COVERED"


class TestCompare:
    def test_match_when_identical(self):
        out = compare_nominal("patch", {"a": 1.0, "b": 2.5},
                              {"a": 1.0, "b": 2.5})
        assert out["verdict"] == "MATCH"
        assert out["mismatches"] == []

    def test_mismatch_carries_both_values(self):
        out = compare_nominal("patch", {"a": 34.9}, {"a": 32.08})
        assert out["verdict"] == "MISMATCH"
        assert out["mismatches"][0] == {"key": "a", "regenerated": 32.08,
                                        "registered": 34.9}

    def test_missing_registered_key_flagged(self):
        out = compare_nominal("patch", {}, {"a": 1.0})
        assert out["verdict"] == "MISMATCH"
        assert "缺值" in out["mismatches"][0]["note"]


class TestAuditOrchestration:
    def test_dirty_chain_hits_mismatch(self):
        # 注入脏链：再生=注册值+1 → 必须 MISMATCH 且汇总 issues（门真能拦）
        def dirty(_nominal):
            return {"patch_w_mm": float(TEMPLATE_NOMINAL["patch"]["patch_w_mm"]) + 1.0}
        chains = {"patch": {"chain": dirty, "inputs": (), "round": 2}}
        out = nrs.nominal_regen_audit(["patch"], chains=chains)
        assert out["verdict"] == "issues"
        row = out["rows"][0]
        assert row["verdict"] == "MISMATCH"
        assert row["mismatches"][0]["regenerated"] == pytest.approx(
            row["registered"]["patch_w_mm"] + 1.0)

    def test_clean_chain_match(self):
        nominal = TEMPLATE_NOMINAL["patch"]
        def clean(_n):
            return {k: float(nominal[k])
                    for k in ("patch_len_mm", "patch_w_mm", "feed_offset_mm")}
        chains = {"patch": {"chain": clean, "inputs": (), "round": 2}}
        out = nrs.nominal_regen_audit(["patch"], chains=chains)
        assert out["verdict"] == "clean"
        assert out["rows"][0]["verdict"] == "MATCH"

    def test_uncovered_gives_attention_not_issues(self):
        out = nrs.nominal_regen_audit(["mline"])  # 无链模板
        assert out["verdict"] == "attention"
        assert out["rows"][0]["verdict"] == "NOT_COVERED"
        assert out["summary"]["mismatch"] == 0

    def test_not_in_registry_row(self):
        out = nrs.nominal_regen_audit(["no_such_template"])
        assert out["rows"][0]["verdict"] == "NOT_IN_REGISTRY"


class TestRealRegistryCurrentState:
    """真实现状钉（预声明事实：名义修复走单独裁决，修复后本类随动更新）。"""

    def test_patch_current_mismatch_is_the_finding(self):
        out = nrs.nominal_regen_audit(["patch"])
        row = out["rows"][0]
        assert out["verdict"] == "issues"
        assert row["verdict"] == "MISMATCH"
        mis = {m["key"]: m for m in row["mismatches"]}
        assert set(mis) == {"patch_len_mm", "patch_w_mm", "feed_offset_mm"}
        assert row["registered"]["patch_w_mm"] == 50.0
        assert row["regenerated"]["patch_w_mm"] == pytest.approx(40.92,
                                                                 abs=0.01)

    def test_chain_registry_has_patch(self):
        assert "patch" in NOMINAL_REGEN_CHAINS


class TestReport:
    def test_markdown_report_lists_mismatch_values(self):
        out = nrs.nominal_regen_audit(["patch"])
        text = nrs.render_nominal_regen_report(out)
        assert "XC-N 名义值闭式再生巡检报告" in text
        assert "issues" in text
        assert "34.9" in text and "32.08" in text  # 双值对照随行
        assert "50.0" in text and "40.92" in text

    def test_json_roundtrip(self):
        out = nrs.nominal_regen_audit(["patch"])
        text = nrs.audit_to_json(out)
        assert '"verdict": "issues"' in text or '"verdict":"issues"' in text
