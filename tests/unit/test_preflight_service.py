"""XC-F preflight 统一门面锚树（plan_deepdive_specs B-4）。

判据（#122 预声明）：本面零新物理判据——各分门 verdict 直译既有内核
（bounds/high_power/fab_service/precision_profiles），锚树验证的是
**组装语义**：best-effort 分区（#105：段缺/门崩不阻塞）、verdict 聚合
（fail>0→issues；warn/unknown>0→attention；否则 clean，与 design_lint
同式）、status 直译表（Bode-Fano 三态、thermal 三值、power all_pass）。

数值基准（独立手算）：Bode-Fano 取 R=50Ω/C=1pF、Γm=0.3、BW=1GHz：
limit=π/RC=6.283e10，actual=2π·BW·ln(1/Γm)=7.564e9 → reachable（裕度
比 0.88）；BW=100GHz → actual=7.564e11 > limit → unreachable。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service import preflight_service as pf

# ─── 组装语义：段缺/verdict 聚合 ─────────────────────────────────────────────


class TestFacadeAggregation:
    def test_empty_payload_all_unknown_attention(self):
        out = pf.preflight({})
        assert out["ok"] is True
        assert [g["name"] for g in out["gates"]] == list(pf._GATES)
        assert all(g["status"] == "unknown" for g in out["gates"])
        assert out["verdict"] == "attention"
        assert out["summary"]["unknown"] == len(pf._GATES)

    def test_clean_run_power_thermal(self):
        out = pf.preflight({
            "power": {"power_levels_w": [1.0, 5.0],
                      "reference_power_w": 1.0,
                      "reference_field_peak_mv_per_m": 1.0,
                      "material": "air"},
            "thermal": {"power_w": 1.0, "theta_jc_c_per_w": 10.0,
                        "max_junction_c": 150.0},
        })
        by = {g["name"]: g for g in out["gates"]}
        assert by["power"]["status"] == "pass"
        assert by["thermal"]["status"] == "pass"
        # precision/limits/fab 段缺 → unknown → attention（不阻断已 pass 门）
        assert out["verdict"] == "attention"
        assert out["summary"]["pass"] == 2

    def test_fail_gives_issues(self):
        out = pf.preflight({
            "power": {"power_levels_w": [1.0],
                      "reference_power_w": 1.0,
                      "reference_field_peak_mv_per_m": 1e9,
                      "material": "air"},
        })
        assert out["verdict"] == "issues"
        assert out["summary"]["fail"] == 1

    def test_subset_selection_and_unknown_gate(self):
        out = pf.preflight({"gates": ["power"]})
        assert [g["name"] for g in out["gates"]] == ["power"]
        with pytest.raises(ValueError, match="未知子门"):
            pf.preflight({"gates": ["nope"]})

    def test_gate_crash_degrades_to_unknown_not_blocking(self, monkeypatch):
        def _boom(payload):
            raise RuntimeError("门内爆炸")
        monkeypatch.setitem(pf._GATES, "power", _boom)
        out = pf.preflight({
            "power": {"power_levels_w": [1.0], "reference_power_w": 1.0,
                      "reference_field_peak_mv_per_m": 1000.0},
            "thermal": {"power_w": 1.0, "theta_jc_c_per_w": 10.0,
                        "max_junction_c": 150.0},
        })
        by = {g["name"]: g for g in out["gates"]}
        assert by["power"]["status"] == "unknown"
        assert "门内爆炸" in by["power"]["detail"]
        assert by["thermal"]["status"] == "pass"   # 崩溃不阻塞其余门（#105）
        assert out["blocked"] == ["power"]
        assert out["verdict"] == "attention"


# ─── limits 门：Bode-Fano 三态 + Chu 信息界 ─────────────────────────────────


class TestLimitsGate:

    @staticmethod
    def _row(out, name):
        by = {g["name"]: g for g in out["gates"]}
        return by[name]

    def _limits(self, bw_hz: float) -> dict:
        return {"limits": {"bode_fano": {"load": [50.0, 1e-12],
                                         "gamma_target": 0.3,
                                         "bandwidth": bw_hz},
                           "chu": {"bbox_m": [0.01, 0.01, 0.01],
                                   "f_ghz": 1.0}}}

    def test_reachable_is_info_not_fail(self):
        out = pf.preflight(self._limits(1e9))
        row = self._row(out, "limits")
        assert row["name"] == "limits"
        # Chu=info + Bode reachable=pass 语义 → 门 status=info（信息行）
        assert row["status"] == "info"
        assert "reachable" in row["detail"] or "Chu" in row["detail"]

    def test_unreachable_is_fail(self):
        out = pf.preflight(self._limits(1e11))
        row = self._row(out, "limits")
        assert row["status"] == "fail"
        assert "不可达" in row["detail"]
        assert out["verdict"] == "issues"

    def test_marginal_is_warn(self):
        # 贴界：裕度比 ≤5%——BW 使 actual≈limit·(1−0.03)
        # actual=2π·BW·ln(1/0.3)，limit=π/RC=6.2832e10
        # → BW = limit·0.97/(2π·1.20397) = 8.0548e9
        out = pf.preflight(self._limits(8.0548e9))
        row = self._row(out, "limits")
        assert row["status"] == "warn"
        assert out["verdict"] == "attention"

    def test_chu_only_is_info(self):
        out = pf.preflight({"limits": {"chu": {"bbox_m": [0.01, 0.01, 0.01],
                                               "f_ghz": 1.0}}})
        row = self._row(out, "limits")
        assert row["status"] == "info"
        assert row["result"]["chu"]["ka"] == pytest.approx(
            3.141592653589793 * 0.01 / 0.299792458, rel=1e-9)

    def test_bad_input_is_fail(self):
        out = pf.preflight({"limits": {"bode_fano": {"load": [50.0, 1e-12],
                                                     "gamma_target": 1.5,
                                                     "bandwidth": 1e9}}})
        assert self._row(out, "limits")["status"] == "fail"


# ─── thermal 三值直译 ────────────────────────────────────────────────────────


class TestThermalGate:

    @staticmethod
    def _row(out, name):
        by = {g["name"]: g for g in out["gates"]}
        return by[name]

    def test_no_limit_is_info(self):
        out = pf.preflight({"thermal": {"power_w": 1.0,
                                        "theta_jc_c_per_w": 10.0}})
        row = self._row(out, "thermal")
        assert row["status"] == "info"
        assert row["result"]["pass"] is None

    def test_breach_is_fail(self):
        out = pf.preflight({"thermal": {"power_w": 20.0,
                                        "theta_jc_c_per_w": 10.0,
                                        "max_junction_c": 150.0}})
        row = self._row(out, "thermal")
        assert row["status"] == "fail"
        assert row["result"]["junction_temp_c"] == pytest.approx(225.0)

    def test_missing_params_unknown(self):
        out = pf.preflight({"thermal": {"power_w": 1.0}})
        assert self._row(out, "thermal")["status"] == "unknown"


# ─── precision 门（XC-P 挂点直译） ──────────────────────────────────────────


class TestPrecisionGate:

    @staticmethod
    def _row(out, name):
        by = {g["name"]: g for g in out["gates"]}
        return by[name]

    def test_in_domain_pass(self):
        out = pf.preflight({"precision": {"checks": [
            {"kernel_id": "synthesis.forward_z0", "quantity": "z0",
             "point": {"w_mm": 1.0}}]}})
        row = self._row(out, "precision")
        assert row["status"] in ("pass", "unknown")  # 域点可判→pass；缺变量→unknown
        if row["status"] == "pass":
            assert row["result"]["details"][0]["in_domain"] is True

    def test_unknown_kernel_is_fail(self):
        out = pf.preflight({"precision": {"checks": [
            {"kernel_id": "no_such_kernel", "quantity": "x"}]}})
        assert self._row(out, "precision")["status"] == "fail"

    def test_absent_section_unknown(self):
        out = pf.preflight({"precision": {}})
        assert self._row(out, "precision")["status"] == "unknown"
