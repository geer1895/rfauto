"""TW-1（round19 P2）twin_runtime 编排层 单元测试。

判据预声明（#118 双基准，全合成/闭式，零真机零 LLM——#139；离线演练模式）：

1. **drift 线**：anchor_drift_report 复用（MK 趋势内核仓内已锚）——强单调
   序列 verdict=drifted、零均值振荡序列 verdict=stable（构造使然）；
2. **aging/RUL 闭式手算**：er0=100, k=−0.01, q=1, spec=1%：
   100h 投影 detune=(√(100/98)−1)·100≈1.0153% → FAIL；RUL 反解
   d*=(1−1/1.0201)/0.01≈1.9706 → t*≈93.44h（手算公式同构比对）；
   k=−0.0001 → 10^12 h 内不达 spec → 如实 None；
3. **三档判据表**：replace>eol FAIL；recalibrate>drifted+eol PASS；
   observe>stable+eol PASS——优先级用同参数只改单因子验证；
4. **时间线**：确定性 echo（不编数）+ error 行如实不阻塞。
"""

from __future__ import annotations

import pytest

from rfauto.service.twin_runtime_service import (
    detune_of_decades,
    rul_log_law,
    twin_step,
    twin_timeline,
)

_ER0 = 100.0
_K = -0.01
_SPEC = 1.0


def _stable_series() -> list[float]:
    return [5.0 + 0.1 * ((i % 4) - 1.5) for i in range(30)]


def _trending_series() -> list[float]:
    return [10.0 * i + (0.5 if i % 2 else -0.5) for i in range(24)]


def _aging(**extra) -> dict:
    base = {"er0": _ER0, "aging_frac_per_decade": _K, "spec_pct": _SPEC,
            "fill_fraction": 1.0}
    base.update(extra)
    return base


class TestClosedFormHandChecks:
    def test_projection_detune_hand_value(self):
        """100h（d=2）：er=98 → detune=(√(100/98)−1)·100≈1.0153%。"""
        assert detune_of_decades(_ER0, _K, 2.0) == pytest.approx(
            ( (_ER0 / 98.0) ** 0.5 - 1.0) * 100.0, rel=1e-12)
        assert detune_of_decades(_ER0, _K, 2.0) == pytest.approx(1.015254,
                                                                 abs=1e-5)

    def test_rul_hand_formula(self):
        """|detune(d*)|=1 ⇔ 1/(1−0.01d*)=1.0201 ⇔ d*=1.9706 → 93.44h。"""
        rep = rul_log_law(_ER0, _K, _SPEC)
        assert rep["rul_h"] is not None
        d_hand = (1.0 - 1.0 / (1.0 + _SPEC / 100.0) ** 2) / 0.01
        assert rep["decades"] == pytest.approx(d_hand, rel=1e-6)
        assert rep["rul_h"] == pytest.approx(10.0 ** d_hand, rel=1e-6)
        assert rep["rul_h"] == pytest.approx(93.44, abs=0.05)
        assert "log-律" in rep["note"]

    def test_rul_zero_drift_honest_infinite(self):
        rep = rul_log_law(_ER0, 0.0, _SPEC)
        assert rep["rul_h"] is None and "零漂移率" in rep["note"]

    def test_rul_beyond_horizon_honest_none(self):
        """k=−1e-4 → d=12 处 detune≈0.06% <1% → 超外推域如实 None。"""
        rep = rul_log_law(_ER0, -0.0001, _SPEC)
        assert rep["rul_h"] is None
        assert "超出" in rep["note"]


class TestTwinStepVerdicts:
    def test_stable_and_healthy_observes(self):
        rep = twin_step({"residuals": _stable_series(),
                         "aging": _aging(), "projection_h": 10.0})
        assert rep["ok"] is True
        assert rep["drift"]["verdict"] == "stable"
        assert rep["aging_eol"]["verdict"] == "PASS"
        assert rep["recommendation"]["action"] == "observe"
        assert rep["mode"] == "offline_drill"

    def test_drifted_and_healthy_recalibrates(self):
        rep = twin_step({"residuals": _trending_series(),
                         "aging": _aging(), "projection_h": 10.0})
        assert rep["ok"] is True
        assert rep["drift"]["verdict"] in ("warning", "drifted")
        assert rep["aging_eol"]["verdict"] == "PASS"
        assert rep["recommendation"]["action"] == "recalibrate"

    def test_eol_fail_replaces_with_priority(self):
        """同一 drifted 序列，投影 100h 处 EOL FAIL → 换件压过校准。"""
        rep = twin_step({"residuals": _trending_series(),
                         "aging": _aging(), "projection_h": 100.0})
        assert rep["aging_eol"]["verdict"] == "FAIL"
        assert rep["recommendation"]["action"] == "replace"
        assert any("闭式判据表第 1 条" in r
                   for r in rep["recommendation"]["reasons"])

    def test_rul_exhaustion_replaces(self):
        """EOL PASS（10h）但 t_now 已过 RUL 93.44h → 剩余寿命判换件。"""
        rep = twin_step({"residuals": _stable_series(),
                         "aging": _aging(t_now_h=94.0),
                         "projection_h": 10.0})
        assert rep["aging_eol"]["verdict"] == "PASS"
        assert rep["recommendation"]["action"] == "replace"
        assert any("剩余寿命" in r
                   for r in rep["recommendation"]["reasons"])

    def test_criteria_table_echoed(self):
        rep = twin_step({"residuals": _stable_series(), "aging": _aging(),
                         "projection_h": 10.0})
        actions = [c["action"] for c in rep["criteria_table"]]
        assert actions == ["replace", "recalibrate", "observe"]

    def test_snapshots_mode_passthrough(self):
        snaps = [{"at": f"t{i}", "values": _stable_series()[i:i + 6]}
                 for i in range(0, 24, 6)]
        rep = twin_step({"snapshots": snaps, "aging": _aging(),
                         "projection_h": 10.0})
        assert rep["ok"] is True
        assert rep["drift"]["mode"] == "snapshots"

    def test_missing_aging_honest(self):
        rep = twin_step({"residuals": _stable_series()})
        assert rep["ok"] is False and "aging 缺失" in rep["reason"]

    def test_bad_fill_fraction_honest(self):
        rep = twin_step({"residuals": _stable_series(),
                         "aging": _aging(fill_fraction=1.5)})
        assert rep["ok"] is False


class TestTwinTimeline:
    def test_timeline_echo_and_summary(self):
        s_observe = twin_step({"residuals": _stable_series(),
                               "aging": _aging(), "projection_h": 10.0})
        s_replace = twin_step({"residuals": _trending_series(),
                               "aging": _aging(), "projection_h": 100.0})
        rep = twin_timeline({"steps": [
            {"at": "d1", "step": s_observe},
            {"at": "d2", "step": s_replace},
            {"at": "d3", "step": {"ok": False}},
        ]})
        assert rep["ok"] is True
        assert [e["action"] for e in rep["events"][:2]] == \
            ["observe", "replace"]
        assert rep["events"][2]["status"] == "error"  # 如实不阻塞
        assert rep["summary"]["action_counts"] == {"observe": 1,
                                                   "replace": 1}
        assert rep["summary"]["last_action"] == "replace"

    def test_inline_step_payload(self):
        rep = twin_timeline({"steps": [
            {"at": "d1", "step_payload": {
                "residuals": _stable_series(), "aging": _aging(),
                "projection_h": 10.0}}]})
        assert rep["ok"] is True
        assert rep["events"][0]["action"] == "observe"

    def test_empty_steps_honest(self):
        assert twin_timeline({"steps": []})["ok"] is False
