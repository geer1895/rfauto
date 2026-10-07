"""XC-A 锚→设计自动修正闭环测试（规格 规格深案
§B-2，预声明于任务书）：

- find_anchors：family+quantity 投影查询（active 过滤 / engine 去歧义 /
  大小写不敏感 / 通配族 / 零匹配空表）；
- apply_anchor_correction 三拒绝分支（规格原文，各自测试钉）：
  ① uncertainty 相对超阈（缺省 10%，wilkinson 真锚 3%/1.13% 实测拒）；
  ② status∈{experimental, stale, awaiting_data, retired}（branchline
  pointer experimental 真锚实测拒）；
  ③ domain_ok=False（wilkinson 域盒 arm_len_mm[15,25] 域外实测拒）；
- 双值锚中位断言（合成 active pointer，2 值中位=均值逐位）；
- 注入数值锚：patch.f_dip_l.openems-v1 真锚（76.8 GHz·mm，rel 5%≤10% 过门）
  修正量与手算逐位对照，L*=76.8/f0 注入综合初值；
- provenance 留痕五元组 {anchor_id, version, Δ, domain_ok, source}；
- level2 设计链挂点：默认关零漂移（公开集锚不受扰）、开启注入/拒绝留痕、
  kickoff bounds 收缩（XC-A 产物作 warm_start 候选输入不越层）。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from rfauto.core.anchors import (
    UNCERTAINTY_REL_MAX_DEFAULT,
    AnchorSet,
    anchor_correction_provenance,
    apply_anchor_correction,
    find_anchors,
)


def _live() -> AnchorSet:
    from rfauto.infra.anchors_store import load_anchors

    return load_anchors(force_reload=True)


# ── find_anchors：族×量投影查询 ────────────────────────────────────────────


class TestFindAnchors:
    def test_family_quantity_active_filter(self) -> None:
        recs = find_anchors("wilkinson", "f_match", anchor_set=_live())
        assert [r.anchor_id for r in recs] == ["wilkinson.f_match.openems-hfss-v1"]
        assert recs[0].status == "active"

    def test_active_only_excludes_experimental_pointer(self) -> None:
        aset = _live()
        assert find_anchors("branchline", "f_match", anchor_set=aset) == []
        recs = find_anchors("branchline", "f_match", active_only=False,
                            anchor_set=aset)
        assert [r.anchor_id for r in recs] == [
            "branchline.f_match.openems-hfss-v1"]
        assert recs[0].status == "experimental"

    def test_engine_disambiguates_split_engine_pair(self) -> None:
        aset = _live()
        # patch.f_dip_l 双席（openems 76.8 / hfss 99.8）：engine= 去歧义
        assert len(find_anchors("patch", "f_dip_L", anchor_set=aset)) == 2
        oe = find_anchors("patch", "f_dip_L", engine="openems", anchor_set=aset)
        assert [r.anchor_id for r in oe] == ["patch.f_dip_l.openems-v1"]
        hfss = find_anchors("patch", "f_dip_L", engine="hfss", anchor_set=aset)
        assert [r.anchor_id for r in hfss] == ["patch.f_dip_l.hfss-v1"]

    def test_case_insensitive_and_empty_query(self) -> None:
        aset = _live()
        assert [r.anchor_id for r in
                find_anchors("PATCH", "F_DIP_L", engine="openems",
                             anchor_set=aset)] == ["patch.f_dip_l.openems-v1"]
        assert find_anchors("no_such_family", "f_match", anchor_set=aset) == []
        assert find_anchors("", "", anchor_set=aset) == []

    def test_wildcard_family_matches_any(self) -> None:
        recs = find_anchors("anything", "gamma_er", anchor_set=_live())
        assert [r.anchor_id for r in recs] == ["cps.gamma_er.fdref-v1"]


# ── apply_anchor_correction：三拒绝分支 + 修正量 ──────────────────────────


def _pointer_raw(anchor_id: str = "ms_cross.wg_resonance.test-v1",
                 status: str = "active",
                 values: dict[str, float] | None = None,
                 domain: dict[str, list[float]] | None = None) -> dict[str, Any]:
    return {
        "anchor_id": anchor_id, "kind": "pointer", "status": status,
        "template_family": ["ms_cross"],
        "engine_pair": {"calibrated": "openems", "referee": "hfss"},
        "quantity": {"name": "wg_resonance", "unit": "GHz",
                     "values": values if values is not None
                     else {"openems": 11.675, "hfss": 11.4951}},
        "value": None,
        "uncertainty": {"value": 0.05, "kind": "relative"},
        "domain": domain,
        "provenance": {"arbitration_runs": ["runs/x"]},
        "fallback": "none",
    }


class TestApplyAnchorCorrectionRejections:
    def test_branch1_uncertainty_relative_exceeds_threshold(self) -> None:
        """真锚实测：wilkinson 仲裁包络 3% 对锚值 1.132503%（rel 264%≫10%）
        → 如实拒绝，弱约束锚不做修正。"""
        corr = apply_anchor_correction(
            "wilkinson", "f_match", {"arm_len_mm": 18.92}, engine="openems",
            anchor_set=_live())
        assert corr["applied"] is False
        assert corr["reason"] == "uncertainty_exceeds_threshold"
        assert corr["anchor_id"] == "wilkinson.f_match.openems-hfss-v1"
        assert corr["domain_ok"] is True  # 域内，死于不确定度门
        # 偏差带 = 3.0（absolute 仲裁包络），band_rel = 3.0/1.132503 逐位
        assert corr["band"] == 3.0
        assert corr["band_rel"] == 3.0 / 1.132503
        assert corr["band_rel"] > UNCERTAINTY_REL_MAX_DEFAULT

    def test_branch2_status_not_active(self) -> None:
        """真锚实测：branchline f_match pointer experimental → 拒绝并留状态。"""
        corr = apply_anchor_correction(
            "branchline", "f_match", {}, engine="openems", anchor_set=_live())
        assert corr["applied"] is False
        assert corr["reason"] == "status_not_active"
        assert corr["status"] == "experimental"
        assert corr["anchor_id"] == "branchline.f_match.openems-hfss-v1"
        cand = corr["candidates"][0]
        assert cand["rejected_reason"] == "status:experimental"
        assert cand["selected"] is False

    def test_branch2_synthetic_stale_rejected(self) -> None:
        raw = _pointer_raw(status="stale")
        corr = apply_anchor_correction("ms_cross", "wg_resonance", {},
                                       anchor_set=AnchorSet([raw]))
        assert corr["applied"] is False
        assert corr["reason"] == "status_not_active"
        assert corr["candidates"][0]["rejected_reason"] == "status:stale"

    def test_branch3_out_of_domain(self) -> None:
        """真锚实测：wilkinson 域盒 arm_len_mm∈[15,25]，域外 → 拒绝门 3
        （先于不确定度门判）。"""
        corr = apply_anchor_correction(
            "wilkinson", "f_match", {"arm_len_mm": 30.0}, engine="openems",
            anchor_set=_live())
        assert corr["applied"] is False
        assert corr["reason"] == "out_of_domain"
        assert corr["domain_ok"] is False
        assert corr["value"] is None  # 域外不求值

    def test_no_matching_anchor(self) -> None:
        corr = apply_anchor_correction("mline", "f_match", {},
                                       anchor_set=_live())
        assert corr["applied"] is False
        assert corr["reason"] == "no_matching_anchor"
        assert corr["candidates"] == []

    def test_ambiguous_active_anchors_rejected(self) -> None:
        a = {"anchor_id": "t.q.alpha-v1", "kind": "constant",
             "status": "active", "template_family": ["t"],
             "quantity": {"name": "q", "unit": "GHz"}, "value": 1.0,
             "uncertainty": {"value": 0.01, "kind": "relative"}}
        b = dict(a, anchor_id="t.q.beta-v1", value=2.0)
        corr = apply_anchor_correction("t", "q", {},
                                       anchor_set=AnchorSet([a, b]))
        assert corr["applied"] is False
        assert corr["reason"] == "ambiguous_active_anchors"

    def test_missing_design_value_for_absolute_unit(self) -> None:
        corr = apply_anchor_correction("patch", "f_dip_L", {},
                                       engine="openems", anchor_set=_live())
        assert corr["applied"] is False
        assert corr["reason"] == "missing_design_value"
        assert corr["value"] == 76.8  # 锚值已求出，只是缺 Δ 基准

    def test_registry_unavailable_is_structural(self, monkeypatch) -> None:
        import rfauto.core.anchors as core_anchors

        original = core_anchors._LIVE_SET_PROVIDER
        monkeypatch.setattr(core_anchors, "_LIVE_SET_PROVIDER", None)
        try:
            corr = apply_anchor_correction("wilkinson", "f_match", {})
            assert corr["applied"] is False
            assert corr["reason"] == "registry_unavailable"
        finally:
            core_anchors.set_live_anchor_set_provider(original)


class TestApplyAnchorCorrectionValues:
    def test_dual_value_anchor_median_bit_exact(self) -> None:
        """双值锚中位（规格 §B-2）：2 值中位=均值，与手算逐位相等。"""
        corr = apply_anchor_correction(
            "ms_cross", "wg_resonance", {}, design_value=12.0,
            anchor_set=AnchorSet([_pointer_raw()]))
        assert corr["applied"] is True
        assert corr["domain_ok"] is True
        assert corr["reason"] is None
        expected_median = (11.4951 + 11.675) / 2
        assert corr["value"] == expected_median  # 逐位
        assert corr["delta"] == expected_median - 12.0  # 逐位
        assert corr["delta_kind"] == "absolute"
        assert corr["unit"] == "GHz"
        assert corr["band_rel"] == pytest.approx(0.05, rel=1e-12)

    def test_percent_unit_anchor_delta_is_value_itself(self) -> None:
        raw = {"anchor_id": "t.f.dev-v1", "kind": "constant",
               "status": "active", "template_family": ["t"],
               "quantity": {"name": "f_match_dev", "unit": "percent"},
               "value": 1.5,
               "uncertainty": {"value": 0.05, "kind": "relative"}}
        corr = apply_anchor_correction("t", "f_match_dev", {},
                                       anchor_set=AnchorSet([raw]))
        assert corr["applied"] is True
        assert corr["delta_kind"] == "percent"
        assert corr["delta"] == 1.5  # 偏差型：Δ 即锚值本身（%）
        assert corr["band_rel"] == pytest.approx(0.05, rel=1e-12)

    def test_uncertainty_threshold_override_tightens(self) -> None:
        raw = _pointer_raw()
        looser = apply_anchor_correction("ms_cross", "wg_resonance", {},
                                         design_value=12.0,
                                         anchor_set=AnchorSet([raw]))
        assert looser["applied"] is True
        tighter = apply_anchor_correction("ms_cross", "wg_resonance", {},
                                          design_value=12.0,
                                          uncertainty_rel_max=0.01,
                                          anchor_set=AnchorSet([raw]))
        assert tighter["applied"] is False
        assert tighter["reason"] == "uncertainty_exceeds_threshold"

    def test_invalid_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="uncertainty_rel_max"):
            apply_anchor_correction("wilkinson", "f_match", {},
                                    uncertainty_rel_max=0.0,
                                    anchor_set=_live())


# ── 注入数值锚：patch.f_dip_l.openems-v1 真锚手算逐位对照 ─────────────────


class TestPatchNumericalAnchor:
    def test_correction_matches_hand_calculation_bit_exact(self) -> None:
        from rfauto.core.synthesis import synthesize_patch

        f0 = 2.4
        synth = synthesize_patch(f0_ghz=f0)
        l_cf = float(synth.params["patch_len_mm"])
        # 设计侧同量纲估计：f_dip·L 的闭式乘积 = f0 × L_cf（GHz·mm 对 GHz·mm）
        design_product = f0 * l_cf
        corr = apply_anchor_correction(
            "patch", "f_dip_L",
            {"f0_ghz": f0, "patch_len_mm": l_cf},
            design_value=design_product, engine="openems", anchor_set=_live())
        assert corr["applied"] is True
        assert corr["anchor_id"] == "patch.f_dip_l.openems-v1"
        assert corr["version"] == 1
        assert corr["status"] == "active"
        assert corr["source"] == "anchor"
        assert corr["unit"] == "GHz·mm"
        assert corr["value"] == 76.8  # 注册表锚值逐位
        assert corr["delta"] == 76.8 - design_product  # 手算逐位：Δ=锚值−设计乘积
        assert corr["delta_kind"] == "absolute"
        assert corr["domain_ok"] is True
        assert corr["band_rel"] == pytest.approx(0.05, rel=1e-12)

    def test_injection_constant_over_f0_hand_calc(self) -> None:
        """注入语义（anchor quantity.semantics 原文 L*=常数/f_target）：
        L* = 76.8/2.4 = 32.0mm 逐位；hfss 席（XA-1 定性禁物理消费）被
        engine 去歧义排除。"""
        from rfauto.service.level2_design import apply_synthesis_anchor_correction

        synth = {"params": {"f0_ghz": 2.4, "patch_len_mm": 32.08,
                            "patch_w_mm": 40.92, "feed_offset_mm": 10.43}}
        corr = apply_synthesis_anchor_correction("patch", synth,
                                                 anchor_set=_live())
        assert corr["applied"] is True
        assert round(76.8 / 2.4, 2) == 32.0  # 手算逐位
        assert corr["injection"] == {"key": "patch_len_mm",
                                     "mode": "constant_over_f0",
                                     "old_value": 32.08, "new_value": 32.0}
        ids = [c["anchor_id"] for c in corr["candidates"]]
        assert ids == ["patch.f_dip_l.openems-v1"]  # hfss 席不在候选

    def test_percent_anchor_family_records_honest_rejection(self) -> None:
        """wilkinson/branchline：表内只查询+判读+留痕，无注入键——拒绝如实。"""
        from rfauto.service.level2_design import apply_synthesis_anchor_correction

        synth = {"params": {"f0_ghz": 2.4, "arm_len_mm": 18.92,
                            "series_w_mm": 0.65, "shunt_w_mm": 1.12}}
        corr = apply_synthesis_anchor_correction("wilkinson", synth,
                                                 anchor_set=_live())
        assert corr["applied"] is False
        assert corr["reason"] == "uncertainty_exceeds_threshold"
        assert corr["injection"] is None
        corr2 = apply_synthesis_anchor_correction("branchline", synth,
                                                  anchor_set=_live())
        assert corr2["applied"] is False
        assert corr2["reason"] == "status_not_active"
        corr3 = apply_synthesis_anchor_correction("mline", synth,
                                                  anchor_set=_live())
        assert corr3["reason"] == "no_anchor_quantity_for_family"


# ── 审计留痕 + 服务 JSON 面 ───────────────────────────────────────────────


class TestProvenanceAndService:
    def test_provenance_five_key_envelope(self) -> None:
        from rfauto.core.synthesis import synthesize_patch

        synth = synthesize_patch(f0_ghz=2.4)
        l_cf = float(synth.params["patch_len_mm"])
        corr = apply_anchor_correction(
            "patch", "f_dip_L", {"f0_ghz": 2.4, "patch_len_mm": l_cf},
            design_value=2.4 * l_cf, engine="openems", anchor_set=_live())
        prov = anchor_correction_provenance(corr)
        # 规格 §B-2 五元组
        assert prov["anchor_id"] == "patch.f_dip_l.openems-v1"
        assert prov["version"] == 1
        assert prov["delta"] == corr["delta"]
        assert prov["domain_ok"] is True
        assert prov["source"] == "anchor"
        assert prov["applied"] is True and prov["reason"] is None
        json.dumps(prov)  # JSON 安全

    def test_provenance_rejected_branch_keeps_anchor_id(self) -> None:
        corr = apply_anchor_correction("wilkinson", "f_match",
                                       {"arm_len_mm": 18.92},
                                       engine="openems", anchor_set=_live())
        prov = anchor_correction_provenance(corr)
        assert prov["applied"] is False
        assert prov["reason"] == "uncertainty_exceeds_threshold"
        assert prov["anchor_id"] == "wilkinson.f_match.openems-hfss-v1"

    def test_service_find_and_apply_json_roundtrip(self) -> None:
        from rfauto.service.anchors_service import (
            ANCHORS_REPORT_SCHEMA_VERSION,
            apply_anchor_correction_request,
            find_anchors_request,
        )

        found = find_anchors_request("patch", "f_dip_L")
        assert found["ok"] and found["count"] == 2
        assert found["schema_version"] == ANCHORS_REPORT_SCHEMA_VERSION
        found_oe = find_anchors_request("patch", "f_dip_L", engine="openems")
        assert [a["anchor_id"] for a in found_oe["anchors"]] == [
            "patch.f_dip_l.openems-v1"]
        req = apply_anchor_correction_request(
            "patch", "f_dip_L", {"f0_ghz": 2.4, "patch_len_mm": 32.08},
            design_value=2.4 * 32.08, engine="openems")
        assert req["ok"] is True
        assert req["result"]["applied"] is True
        assert req["provenance"]["anchor_id"] == "patch.f_dip_l.openems-v1"
        json.dumps(req)
        rejected = apply_anchor_correction_request(
            "wilkinson", "f_match", {"arm_len_mm": 18.92}, engine="openems")
        assert rejected["result"]["applied"] is False
        assert rejected["result"]["reason"] == "uncertainty_exceeds_threshold"
        assert rejected["provenance"]["applied"] is False


# ── level2 设计链挂点（默认关零漂移 / 开启注入与留痕 / bounds 收缩）────────


def _task(prompt: str, tid: str = "t_xc") -> dict[str, Any]:
    return {"id": tid, "prompt": prompt}


_PATCH_PROMPT = "设计一个工作在 2.4GHz 的微带贴片天线（patch 天线），50 欧"
_WILKINSON_PROMPT = "2.4GHz Wilkinson 功分器，50 欧"
_BRANCHLINE_PROMPT = "2.4GHz 分支线电桥（branchline），50 欧"
_MLINE_PROMPT = "50 欧均匀微带校准线，2.5GHz"


class TestLevel2ChainHook:
    def test_default_off_is_byte_identical_chain(self) -> None:
        from rfauto.service.level2_design import design_chain, synthesize_initial

        rec = design_chain(_task(_PATCH_PROMPT))
        assert "anchor_correction" not in rec
        assert "anchor_correction" not in rec["provenance"]
        baseline = synthesize_initial("patch", {"f0_ghz": 2.4})
        assert rec["synthesis_params"] == baseline["params"]
        assert "XC-A" not in "\n".join(rec["synthesis_notes"])

    def test_enabled_patch_injects_and_leaves_provenance(self) -> None:
        from rfauto.service.level2_design import (
            apply_synthesis_anchor_correction,
            design_chain,
            synthesize_initial,
        )

        rec = design_chain(_task(_PATCH_PROMPT), enable_anchor_correction=True)
        assert "error" not in rec
        corr = rec["anchor_correction"]
        assert corr["applied"] is True
        assert corr["anchor_id"] == "patch.f_dip_l.openems-v1"
        baseline = synthesize_initial("patch", {"f0_ghz": 2.4})
        injection = corr["injection"]
        assert injection["old_value"] == baseline["params"]["patch_len_mm"]
        assert rec["synthesis_params"]["patch_len_mm"] == 32.0  # 76.8/2.4
        assert rec["synthesis_params"]["patch_w_mm"] == \
            baseline["params"]["patch_w_mm"]  # 只动注入键
        assert any("XC-A" in n for n in rec["synthesis_notes"])
        prov = rec["provenance"]["anchor_correction"]
        assert prov == anchor_correction_provenance(corr)
        # 注入策略与 core 解耦：链上包络 = 直调内核（同参逐位一致）
        direct = apply_synthesis_anchor_correction(
            "patch", {"params": dict(baseline["params"])}, anchor_set=_live())
        assert direct["injection"] == injection

    def test_enabled_wilkinson_honest_rejection_keeps_params(self) -> None:
        from rfauto.service.level2_design import design_chain, synthesize_initial

        rec = design_chain(_task(_WILKINSON_PROMPT),
                           enable_anchor_correction=True)
        corr = rec["anchor_correction"]
        assert corr["applied"] is False
        assert corr["reason"] == "uncertainty_exceeds_threshold"
        baseline = synthesize_initial("wilkinson",
                                      {"f0_ghz": 2.4, "z0_ohm": 50.0})
        assert rec["synthesis_params"] == baseline["params"]  # 拒绝=零注入
        prov = rec["provenance"]["anchor_correction"]
        assert prov["applied"] is False
        assert prov["anchor_id"] == "wilkinson.f_match.openems-hfss-v1"

    def test_enabled_branchline_status_rejection_recorded(self) -> None:
        from rfauto.service.level2_design import design_chain

        rec = design_chain(_task(_BRANCHLINE_PROMPT),
                           enable_anchor_correction=True)
        corr = rec["anchor_correction"]
        assert corr["applied"] is False
        assert corr["reason"] == "status_not_active"

    def test_enabled_family_without_quantity_recorded(self) -> None:
        from rfauto.service.level2_design import design_chain

        rec = design_chain(_task(_MLINE_PROMPT), enable_anchor_correction=True)
        assert rec["anchor_correction"]["reason"] == \
            "no_anchor_quantity_for_family"
        assert rec["anchor_correction"]["applied"] is False

    def test_kickoff_bounds_shrunk_by_band_rel(self) -> None:
        """XC-A 产物作 warm_start 候选输入（不越层）：修正键 bounds 收缩到
        偏差带，其余键维持缺省跨度。"""
        from rfauto.service.level2_design import (
            KICKOFF_REL_SPAN,
            design_chain,
            synthesize_initial,
        )

        rec = design_chain(_task(_PATCH_PROMPT), enable_optimize=True,
                           enable_anchor_correction=True)
        kickoff = rec["kickoff"]
        assert kickoff["kickoff_status"] in ("completed", "launched")
        corr = rec["anchor_correction"]
        assert corr["applied"] is True
        band = corr["band_rel"]
        assert 0.0 < band < KICKOFF_REL_SPAN
        corrected_len = rec["synthesis_params"]["patch_len_mm"]
        lo, hi = kickoff["bounds"]["patch_len_mm"]
        assert lo == corrected_len * (1.0 - band)  # 收缩到偏差带（逐位）
        assert hi == corrected_len * (1.0 + band)
        baseline = synthesize_initial("patch", {"f0_ghz": 2.4})
        w = baseline["params"]["patch_w_mm"]
        assert kickoff["bounds"]["patch_w_mm"] == [w * (1.0 - KICKOFF_REL_SPAN),
                                                   w * (1.0 + KICKOFF_REL_SPAN)]
        assert kickoff["rel_span_overrides"] == {"patch_len_mm": band}

    def test_kickoff_default_span_when_correction_off(self) -> None:
        from rfauto.service.level2_design import (
            KICKOFF_REL_SPAN,
            design_chain,
        )

        rec = design_chain(_task(_WILKINSON_PROMPT), enable_optimize=True)
        kickoff = rec["kickoff"]
        assert kickoff["rel_span"] == KICKOFF_REL_SPAN
        assert kickoff["rel_span_overrides"] == {}
        assert "anchor_correction" not in rec
