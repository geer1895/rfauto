"""W1-F 席 H-02/H-03：判读收口纯函数助手回归钉。

H-02（K-8 G4 哨兵口径二义，R6-5）：无源性硬门与截断哨兵双口径分列——
二义带（1.0 < max|S| ≤ 硬门）必须双报，硬门绿不静默采信。
H-03（量级合理性旁注惯例，R6-6）：预期带外旁注作为判读器可调用面。

阈值全部调用方传入（本模块零物理数字， 规则 7）；k8 哨门值
（≤1.05 / #262 的 1.0）仅作为测试入参示例，出处 runs/k8_rerun/criteria.md §3。
"""
from __future__ import annotations

import pytest

from rfauto.core.judge_notes import magnitude_band_note, sentinel_dual_report


class TestSentinelDualReport:
    def test_clean_pass_no_suspect(self):
        r = sentinel_dual_report(0.9379, passivity_limit=1.05)
        assert r["passivity"] == "PASS"
        assert r["truncation_suspect"] is False
        assert r["ambiguous_band"] is False
        assert r["dual_report_required"] is False
        assert r["notes"] == []

    def test_exact_physical_bound_not_suspect(self):
        """恰等 1.0：物理无源性边界，截断哨兵严格 > 不亮。"""
        r = sentinel_dual_report(1.0, passivity_limit=1.05)
        assert r["passivity"] == "PASS"
        assert r["truncation_suspect"] is False

    def test_ambiguous_band_requires_dual_report(self):
        """二义带 (1.0, 1.05]：硬门 PASS 但哨兵亮——双报强制、绿不采信。"""
        r = sentinel_dual_report(1.02, passivity_limit=1.05)
        assert r["passivity"] == "PASS"
        assert r["truncation_suspect"] is True
        assert r["ambiguous_band"] is True
        assert r["dual_report_required"] is True
        assert any("#262" in n for n in r["notes"])

    def test_fail_above_limit(self):
        r = sentinel_dual_report(1.20, passivity_limit=1.05)
        assert r["passivity"] == "FAIL"
        assert r["truncation_suspect"] is True
        assert r["ambiguous_band"] is False

    def test_none_observed_unknown_not_fabricated(self):
        r = sentinel_dual_report(None, passivity_limit=1.05)
        assert r["passivity"] == "UNKNOWN"
        assert r["truncation_suspect"] is False
        assert any("UNKNOWN" in n for n in r["notes"])

    def test_non_finite_observed_unknown(self):
        r = sentinel_dual_report(float("nan"), passivity_limit=1.05)
        assert r["passivity"] == "UNKNOWN"
        r2 = sentinel_dual_report(float("inf"), passivity_limit=1.05)
        assert r2["passivity"] == "UNKNOWN"

    def test_inverted_limits_rejected(self):
        with pytest.raises(ValueError, match="passivity_limit"):
            sentinel_dual_report(0.9, passivity_limit=0.99,
                                 truncation_threshold=1.0)

    def test_k8_rerun_observation_shape(self):
        """k8_rerun 实测 0.9379：哨门绿无双报需求（verdict 同判）。"""
        r = sentinel_dual_report(0.9379, passivity_limit=1.05,
                                 truncation_threshold=1.0)
        assert r == {
            "max_abs_s": 0.9379,
            "passivity_limit": 1.05,
            "truncation_threshold": 1.0,
            "passivity": "PASS",
            "truncation_suspect": False,
            "ambiguous_band": False,
            "dual_report_required": False,
            "notes": [],
        }


class TestMagnitudeBandNote:
    def test_in_band_returns_none(self):
        assert magnitude_band_note("S21@f0 dB", -2.8, -3.0, 0.0) is None
        assert magnitude_band_note("x", 0.0, 0.0, 0.0) is None  # 边界含

    def test_below_band_noted(self):
        note = magnitude_band_note("span_db", 12.4, 20.0, 60.0)
        assert note is not None
        assert "span_db" in note and "预期带外" in note
        assert "12.4" in note and "20" in note

    def test_above_band_noted(self):
        note = magnitude_band_note("S11_db", -2.0, -20.0, -10.0)
        assert note is not None and "预期带" in note

    def test_missing_observed_noted_not_silent(self):
        note = magnitude_band_note("q_loaded", None, 100.0, 500.0)
        assert note is not None and "缺失" in note

    def test_non_finite_noted(self):
        note = magnitude_band_note("eta", float("nan"), 0.55, 0.79)
        assert note is not None and "非有限" in note
        note2 = magnitude_band_note("eta", float("inf"), 0.55, 0.79)
        assert note2 is not None and "非有限" in note

    def test_inverted_band_rejected(self):
        with pytest.raises(ValueError, match="预期带非法"):
            magnitude_band_note("x", 1.0, 5.0, 1.0)

    def test_bool_observed_treated_as_non_numeric(self):
        """bool 是 int 子类——按非数值如实带外，不消费真值语义。"""
        note = magnitude_band_note("flag", True, 0, 1)
        assert note is not None and "非有限" in note
