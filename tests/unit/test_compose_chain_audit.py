"""compose 级联端口兼容审计锚树（XC 模板积木 W4 审计补落点）。

判据（#122）：审计谓词与组合器守卫**同容差单源**（IMPEDANCE_RTOL import
layout_netlist，禁双头）；真契约端到端（siw/msl_siw_taper 现役注册表）：
- 链 [msl_siw_taper, siw, siw] @0.5mm 网格 → 两 junction 全 compatible
  （z_ref 22.8393Ω 同源、截面同 kind 同参）、暴露端口 {msl, lumped}
  D4 可发射、verdict=clean；
- 参数分裂（w_mm 变 → R_port 变）→ P3 mismatch → issues；
- 无契约模板 → unknown 行 → attention（不炸）。
内核单测用合成 pin（容差边界手算：P3 相对差 1e-6 恰界外/界内）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.compose.cascade_audit import (
    audit_junction,
    chain_axis_of,
    chain_endpoints,
)
from rfauto.service import compose_chain_audit_service as ccs


def _pin(pin_id, direction, z, kind="siw", **cs):
    return {"pin_id": pin_id, "direction": list(direction),
            "z_ref_ohm": z, "port_type": "lumped",
            "ref_plane_offset_m": 0.0, "width_m": 1e-3,
            "cross_section": {"kind": kind, "h_mm": 0.508, "er": 3.66, **cs}}


class TestJunctionKernel:
    def test_compatible(self):
        j = audit_junction(_pin("a", (0, 1), 22.8393),
                           _pin("b", (0, -1), 22.8393))
        assert j["verdict"] == "compatible"
        assert j["direction"]["ok"] is True
        assert j["impedance"]["ok"] is True
        assert j["cross_section"]["ok"] is True

    def test_direction_mismatch(self):
        j = audit_junction(_pin("a", (0, 1), 50.0), _pin("b", (0, 1), 50.0))
        assert j["verdict"] == "mismatch"
        assert j["direction"]["ok"] is False

    def test_impedance_mismatch_and_exempt(self):
        a, b = _pin("a", (0, 1), 50.0), _pin("b", (0, -1), 40.0)
        assert audit_junction(a, b)["verdict"] == "mismatch"
        j = audit_junction(a, b, allow_mismatch=True)
        assert j["verdict"] == "compatible"  # 豁免留痕不翻 verdict
        assert j["impedance"]["exempted"] is True

    def test_p3_tolerance_boundary(self):
        # 同 50Ω：相对差 1e-9（界内）vs 1e-3（界外，IMPEDANCE_RTOL=1e-6）
        assert audit_junction(_pin("a", (0, 1), 50.0),
                              _pin("b", (0, -1), 50.0 * (1 + 1e-9))
                              )["impedance"]["ok"] is True
        assert audit_junction(_pin("a", (0, 1), 50.0),
                              _pin("b", (0, -1), 50.0 * (1 + 1e-3))
                              )["impedance"]["ok"] is False

    def test_cross_section_er_mismatch(self):
        a = _pin("a", (0, 1), 50.0)
        b = _pin("b", (0, -1), 50.0, er=4.4)
        j = audit_junction(a, b)
        assert j["verdict"] == "mismatch"
        assert any(f.startswith("er:") for f in
                   j["cross_section"]["fields_diff"])

    def test_unknown_pin_missing_keys(self):
        j = audit_junction({"pin_id": "x"}, _pin("b", (0, -1), 50.0))
        assert j["verdict"] == "unknown"
        assert j["problems"]


class TestChainHelpers:
    def test_axis_and_endpoints(self):
        pins = {"p1": _pin("p1", (0, -1), 50.0),
                "p2": _pin("p2", (0, 1), 50.0)}
        assert chain_axis_of(pins) == "y"
        assert chain_endpoints(pins, "y") == (["p1"], ["p2"])

    def test_ambiguous_axis_none(self):
        pins = {"p1": _pin("p1", (0, -1), 50.0),
                "p2": _pin("p2", (1, 0), 50.0)}
        assert chain_axis_of(pins) is None


class TestChainAuditService:
    BAND = (9.75, 10.25)

    def test_siw_chain_clean(self):
        out = ccs.compose_chain_audit({
            "chain": [{"template": "msl_siw_taper"},
                      {"template": "siw"}, {"template": "siw"}],
            "band_ghz": self.BAND, "mesh_resolution_mm": 0.5})
        assert out["ok"] is True
        assert out["n_instances"] == 3
        assert out["summary"]["n_junctions"] == 2
        assert all(j["verdict"] == "compatible" for j in out["junctions"])
        assert out["d6_substrate_consistent"] is True
        assert out["d5_bc_compat_consistent"] is True
        assert out["exposed_plan"]["d4_emittable"] is True
        assert [e["port_type"] for e in out["exposed_plan"]["exposed"]] == \
            ["msl", "lumped"]
        assert out["verdict"] == "clean"

    def test_param_split_p3_mismatch(self):
        out = ccs.compose_chain_audit({
            "chain": [{"template": "siw"},
                      {"template": "siw", "params": {"w_mm": 15.0}}],
            "band_ghz": self.BAND, "mesh_resolution_mm": 0.5})
        assert out["summary"]["n_mismatch"] >= 1
        assert out["verdict"] == "issues"
        j = out["junctions"][0]
        assert j["impedance"]["ok"] is False

    def test_missing_contract_unknown_attention(self):
        out = ccs.compose_chain_audit({
            "chain": [{"template": "mline"}, {"template": "siw"}],
            "band_ghz": self.BAND, "mesh_resolution_mm": 0.5})
        assert out["ok"] is True
        assert len(out["unknown_instances"]) == 1
        assert "无组合契约" in out["unknown_instances"][0]["reason"]
        assert out["verdict"] == "attention"

    def test_program_errors_ok_false(self):
        out = ccs.compose_chain_audit({"chain": []})
        assert out["ok"] is False
        out = ccs.compose_chain_audit({"chain": [{"template": "siw"}]})
        assert out["ok"] is False  # 缺 band
        out = ccs.compose_chain_audit({"chain": [{"template": "siw"}],
                                       "band_ghz": (9.0, 10.0)})
        assert out["ok"] is False  # 缺 mesh

    def test_contract_guard_rejection_is_unknown_row(self):
        # 网格欠分辨守卫（1mm base 对 0.6mm 过孔）→ 契约 ValueError → unknown
        out = ccs.compose_chain_audit({
            "chain": [{"template": "siw"}], "band_ghz": self.BAND,
            "mesh_resolution_mm": 1.0})
        assert out["ok"] is True
        assert "网格欠分辨" in out["unknown_instances"][0]["reason"]

    # ── 基板高单源（审查 A3 P3-5 回归钉）───────────────────────────────

    def test_declared_substrate_h_mm_unit(self):
        # 声明 h_mm（mm）须 mm→m 换算后进 layout——旧码直传 0.508 当米
        # （1000× 单位偏差）且与 D6 声明比对口径自相矛盾（d6 必假）
        out = ccs.compose_chain_audit({
            "chain": [{"template": "siw"}],
            "band_ghz": self.BAND, "mesh_resolution_mm": 0.5,
            "substrate": {"h_mm": 0.508, "er": 3.66}})
        assert out["ok"] is True
        assert out["instances"][0]["substrate"]["h_m"] == \
            pytest.approx(0.508e-3, rel=1e-12)
        assert out["d6_substrate_consistent"] is True
        assert out["verdict"] == "clean"

    def test_declared_h_mm_zero_not_shadowed(self):
        # 显式 h_mm=0 不被 ``or 缺省`` 顶替——layout 正有限守卫如实报
        # unknown 行（attention），不静默用 0.508mm 兜底
        out = ccs.compose_chain_audit({
            "chain": [{"template": "siw"}],
            "band_ghz": self.BAND, "mesh_resolution_mm": 0.5,
            "substrate": {"h_mm": 0}})
        assert out["ok"] is True
        assert out["verdict"] == "attention"
        assert "h 必须为正有限" in out["unknown_instances"][0]["reason"]

    def test_substrate_non_dict_ok_false(self):
        # 程序性入参错转 ok=False（JSON 进出薄面契约；旧码 AttributeError）
        out = ccs.compose_chain_audit({
            "chain": [{"template": "siw"}], "band_ghz": self.BAND,
            "mesh_resolution_mm": 0.5, "substrate": [0.508]})
        assert out["ok"] is False
        assert "substrate" in out["errors"][0]

    def test_h_missing_declaration_fail_fast(self, monkeypatch):
        # 全链无 h_mm 声明（无 substrate + 模板 nominal 无 h_mm）→
        # fail-fast ok=False，不静默兜底硬编码基板（与 mesh 缺失同口径）
        from rfauto.adapters.oe_templates import render_siw

        monkeypatch.setitem(render_siw.TEMPLATE_NOMINAL, "siw",
                            {"w_mm": 12.0})
        out = ccs.compose_chain_audit({
            "chain": [{"template": "siw"}],
            "band_ghz": self.BAND, "mesh_resolution_mm": 0.5})
        assert out["ok"] is False
        assert "基板高" in out["errors"][0]
