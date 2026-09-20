"""WP4.4b 寄生提取链 service 单测（纯离线：RF-DRC 纯几何 + 闭式锚）。

覆盖：KiCad pcell PCBDesign→RFGeometry 转换（net/sensitive/pad 口径）、
主走线选取（最长 F.Cu）、DRC 门（min_width 内联 + run_rf_drc 四规则；
门不过不进提取）、RLC 闭式锚数值、Q3D 注入对比（≤5% 门边界）、未知
字段/缺字段显式报错、DRC 可关闭、确定性幂等。
"""

from __future__ import annotations

import copy

import pytest

from rfauto.adapters.kicad_drc import RFGeometry
from rfauto.core.parasitic import interconnect_rlc_anchor
from rfauto.service.parasitic_service import (
    ANCHOR_TOLERANCE,
    extract_interconnect_rlc,
    pcb_to_rfdrc_geometry,
)

#: 50mm × 1.09mm RO4350B 直条微带（与锚默认工况同源）
BASE_PAYLOAD = {
    "pcb": {
        "traces": [
            {"start": [5.0, 5.0], "end": [55.0, 5.0], "width": 1.09},
        ],
        "vias": [
            {"position": [4.0, 4.0], "drill": 0.3, "pad": 0.6},
        ],
    },
    "substrate": {"h_mm": 0.508, "eps_r": 3.66, "tan_d": 0.0037},
    "trace_t_mm": 0.035,
    "freq_ghz": 1.0,
}


def _anchor_for_base() -> dict:
    return interconnect_rlc_anchor(
        length_mm=50.0, w_mm=1.09, t_mm=0.035, h_mm=0.508,
        eps_r=3.66, freq_ghz=1.0, loss_tangent=0.0037)


# ─── pcell→RFGeometry 转换 ───────────────────────────────────────────────────


class TestPcbToGeometry:
    def test_conversion_defaults_and_extensions(self):
        geom = pcb_to_rfdrc_geometry(BASE_PAYLOAD["pcb"])
        assert isinstance(geom, RFGeometry)
        assert len(geom.conductors) == 1
        cond = geom.conductors[0]
        assert cond.net == "RF"          # pcell 无 net 字段 → 缺省 RF
        assert cond.points == [(5.0, 5.0), (55.0, 5.0)]
        assert cond.width_mm == 1.09
        assert cond.sensitive is False
        via = geom.vias[0]
        assert via.net == "GND"
        assert via.diameter_mm == 0.6    # pad = 铜特征直径口径

    def test_explicit_nets_and_sensitive(self):
        pcb = {
            "traces": [
                {"start": [0, 0], "end": [10, 0], "width": 0.3,
                 "net": "LO_IN", "sensitive": True, "layer": "F.Cu"},
            ],
            "vias": [{"position": [1, 1], "drill": 0.3, "pad": 0.5,
                      "net": "AGND"}],
        }
        geom = pcb_to_rfdrc_geometry(pcb)
        assert geom.conductors[0].net == "LO_IN"
        assert geom.conductors[0].sensitive is True
        assert geom.vias[0].net == "AGND"

    def test_invalid_shapes_rejected(self):
        with pytest.raises(ValueError, match="\\[x, y\\]"):
            pcb_to_rfdrc_geometry({"traces": [{"start": [0], "end": [1, 0],
                                               "width": 0.3}]})
        with pytest.raises(ValueError, match="正数"):
            pcb_to_rfdrc_geometry({"traces": [{"start": [0, 0], "end": [1, 0],
                                               "width": -0.3}]})


# ─── 链路主编排 ──────────────────────────────────────────────────────────────


class TestExtractChain:
    def test_happy_path_closed_form_only(self):
        out = extract_interconnect_rlc(BASE_PAYLOAD)
        assert out["ok"] is True
        chain = out["chain"]
        assert chain["geometry"]["primary_trace"] == {
            "w_mm": 1.09, "length_mm": 50.0, "index": 0, "net": "RF"}
        assert chain["geometry"]["n_traces"] == 1
        assert chain["drc"]["passed"] is True
        assert chain["drc"]["n_errors"] == 0
        # 锚数值与 core 直算一致（单一实现）
        anchor = _anchor_for_base()
        assert chain["anchor"]["l_nh_per_mm"] == pytest.approx(
            anchor["l_nh_per_mm"])
        assert chain["anchor"]["c_total_pf"] == pytest.approx(
            anchor["c_total_pf"])
        assert chain["anchor"]["dc_r_ohm"] == pytest.approx(anchor["dc_r_ohm"])
        assert chain["q3d"] is None

    def test_primary_trace_is_longest_fcu(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["pcb"]["traces"].insert(0, {"start": [0, 0], "end": [3, 0],
                                            "width": 0.6})
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is True
        assert out["chain"]["geometry"]["primary_trace"]["index"] == 1
        assert out["chain"]["geometry"]["primary_trace"]["length_mm"] == 50.0

    def test_q3d_injection_pass_gate(self):
        anchor = _anchor_for_base()
        payload = copy.deepcopy(BASE_PAYLOAD)
        # 提取值 = 锚 × 1.02（+2% 物理合理偏差）→ 门过
        payload["q3d"] = {
            "l_total_nh": anchor["l_total_nh"] * 1.02,
            "c_total_pf": anchor["c_total_pf"] * 0.99,
            "r_total_ohm": 0.35,
        }
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is True
        q3d = out["chain"]["q3d"]
        assert q3d["l_rel_dev"] == pytest.approx(0.02, rel=1e-6)
        assert q3d["c_rel_dev"] == pytest.approx(0.01, rel=1e-6)
        assert q3d["pass_5pct"] is True
        assert q3d["dc_r_reference_ohm"] == pytest.approx(anchor["dc_r_ohm"])

    def test_q3d_injection_fail_gate(self):
        anchor = _anchor_for_base()
        payload = copy.deepcopy(BASE_PAYLOAD)
        # 提取值 = 锚 × 1.06（+6%）→ 超 5% 门，判 False（不凑绿）
        payload["q3d"] = {
            "l_total_nh": anchor["l_total_nh"] * 1.06,
            "c_total_pf": anchor["c_total_pf"],
        }
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is True
        assert out["chain"]["q3d"]["pass_5pct"] is False
        assert out["chain"]["q3d"]["l_rel_dev"] == pytest.approx(0.06, rel=1e-6)

    def test_drc_gate_blocks_extraction(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["pcb"]["traces"] = [
            {"start": [0, 0], "end": [10, 0], "width": 0.05}]
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is False
        assert out["stage"] == "drc"
        assert out["drc"]["n_errors"] == 1
        assert out["drc"]["violations"][0]["rule_name"] == "min_trace_width"
        assert "anchor" not in out

    def test_drc_sensitive_trace_without_stitch_vias_fails(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["pcb"]["traces"][0]["sensitive"] = True
        payload["pcb"]["vias"] = []
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is False
        assert out["stage"] == "drc"
        rules = {v["rule_name"] for v in out["drc"]["violations"]}
        assert "ground_stitch_integrity" in rules

    def test_drc_disabled_skips_gate(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["pcb"]["traces"] = [
            {"start": [0, 0], "end": [10, 0], "width": 0.05}]
        payload["drc"] = {"enabled": False}
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is True
        assert out["chain"]["drc"]["enabled"] is False

    def test_drc_uses_anchor_eps_eff_for_lambda(self):
        out = extract_interconnect_rlc(BASE_PAYLOAD)
        # λg = c/(f·√εeff)：εeff≈2.85 @1GHz → ~177mm（真空 300mm 对拍）
        lam = out["chain"]["drc"]["lambda_g_mm"]
        assert 160.0 < lam < 195.0

    def test_rfdrc_config_passthrough(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["drc"] = {"min_trace_width_mm": 2.0}
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is False
        assert out["stage"] == "drc"   # 1.09mm < 2.0mm 自定义门 → 拦截

    def test_deterministic_idempotent(self):
        a = extract_interconnect_rlc(BASE_PAYLOAD)
        b = extract_interconnect_rlc(BASE_PAYLOAD)
        assert a == b


# ─── 非法输入显式报错（ok=False 不抛异常）───────────────────────────────────


class TestInvalidInputs:
    def test_unknown_payload_field(self):
        out = extract_interconnect_rlc({**BASE_PAYLOAD, "extra": 1})
        assert out == {"ok": False, "error": "payload 含未知字段: ['extra']"}

    def test_missing_substrate(self):
        out = extract_interconnect_rlc({"pcb": BASE_PAYLOAD["pcb"]})
        assert out["ok"] is False
        assert "substrate" in out["error"]

    def test_unknown_substrate_field(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["substrate"]["nope"] = 1
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is False
        assert "substrate" in out["error"]

    def test_unknown_q3d_field(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["q3d"] = {"l_total_nh": 1.0, "c_total_pf": 1.0, "wat": 1}
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is False
        assert "q3d" in out["error"]

    def test_no_traces(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["pcb"] = {"traces": []}
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is False
        assert "F.Cu" in out["error"]

    def test_b_layer_traces_ignored(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["pcb"]["traces"] = [
            {"start": [0, 0], "end": [10, 0], "width": 1.0, "layer": "B.Cu"}]
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is False
        assert "F.Cu" in out["error"]

    def test_epsr_below_one_rejected(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["substrate"]["eps_r"] = 0.5
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is False
        assert "eps_r" in out["error"]

    def test_non_numeric_rejected(self):
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["trace_t_mm"] = "thick"
        out = extract_interconnect_rlc(payload)
        assert out["ok"] is False
        assert "实数" in out["error"]


def test_gate_tolerance_constant_matches_adapter():
    """服务门与适配器门同源（≤5%），漂移即测试红。"""
    from rfauto.adapters.q3d_adapter import ANCHOR_TOLERANCE as ADAPTER_TOL

    assert ANCHOR_TOLERANCE == ADAPTER_TOL == 0.05
