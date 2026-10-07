"""DP-3 锚注册表纯内核测试（判据 a 核心 + c，预声明 runs/df6_dp3anchors/criteria.md）。

- a1：c3.l_via_h 锚值与 openems_templates.C3_L_VIA_CAL_H 逐位相等；
- a3：cps.gamma_er 锚公式（AST 白名单求值）与 calculators.
  cps_effective_thickness_factor 逐位相等（8 定标点 + 域内均匀扫点）；
- a4：siw.w_eff 锚公式与 calculators.siw_effective_width_mm 逐位相等；
- c1：曲线锚构造期单调断言；c2：曲线域外直接求值 ValueError + resolve
  结构化 fallback；c3：公式 AST 白名单拒绝恶意项；c4：未知锚 fallback；
  c5：awaiting_data 骨架不可消费；c6：漂移检测 stale 门。
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest

from rfauto.core.anchors import (
    EXPECTED_ANCHORS,
    AnchorRecord,
    AnchorSet,
    compile_anchor_formula,
)

# ── 内核单源与构造语义 ─────────────────────────────────────────────────────


def test_expected_anchors_single_source_shape() -> None:
    # DP-3 P1 批 6 + HFSS 窗 B→A 批（wf:anchor-register）6 + 补批
    # （wf:anchor-register-p1x4，patch_array_1x4.f_res constant）1
    # + 指针补批（wf:anchor-pointer-register，patch_array.f_res 族级
    # pointer experimental，席 8 2x2 重跑 DISAGREE 双值）1
    # + P-KJ-EVEN P3 批（wf:goal-t5，coupled_microstrip.kj_even_domain
    # .lit-v1 KJ even 闭式适用域盒 constant）1
    # + Goal 批 T14（wf:goal-t14，mmt.inductive_post_b.hfss-v1 /
    # mmt.resonant_window_fres.hfss-v1，ME-5 MMT 销钉/谐振窗 HFSS 仲裁
    # 偏差常量 active）2
    # + ge6 Wave1 锚注册批（wf:ge6-anchor，ring.design_dk pointer/
    # experimental + mmwave.design_dk.ro3003-oe-v1 pointer/experimental
    # OE 单引擎封档）2
    # + ge6 A22 批（wf:ge6-a22，ms_cross.wg_resonance pointer/experimental，
    # ge6 席 2 HFSS 仲裁分支 A 收敛判读双值指针）1 = 20
    # + ge8b Wave A 席 1（2026-10-03）：TA-7 inverted_ms/TA-8 hmsiw/TA-9
    # fgcpw 内核恒等锚 experimental（fdref×2 + closedform×1）3 = 34
    # + ge8e X5 解析档锚批（wf:review-ge8e-x5，2026-10-04）：首批 analytic
    # 锚扩面 13 席（atten_pi/atten_t/ratrace/stripline/slotline/siw/
    # monopole/coil_nfc/pyramid_horn 九族闭式恒等锚）13 = 48
    assert len(EXPECTED_ANCHORS) == 60  # ge8e X5 批 +13  # ge8 K-4 锚演进 +1  # ge8 TA 批三 +4  # ge8 TA 批二 +4  # ge8 TA 批 20→22  # ge8b WA 席1 +3
    assert all(a.count(".") >= 2 and "-v" in a for a in EXPECTED_ANCHORS)


def test_anchor_id_format_rejects_malformed() -> None:
    with pytest.raises(ValueError, match="anchor_id"):
        AnchorRecord.from_dict({"anchor_id": "bad_id", "kind": "constant",
                                "status": "active", "value": 1.0})


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValueError, match="kind"):
        AnchorRecord.from_dict({"anchor_id": "x.y.z-v1",
                                "kind": "function", "status": "active"})


# ── 判据 a：锚值与现硬编码常量逐位相等（迁移零行为变化）────────────────────

def _live_anchor_set(*, force_reload: bool = False) -> AnchorSet:
    """从真实注册表构造（零 IO 依赖由 conftest 仓库根保证；直接 yaml 读会
    与 store 层重复，这里用 infra 装载面共享缓存）。

    force_reload=True 取洁净副本：note_anchor_residual 的 stale 翻转是进程
    内共享缓存对象的原地变更，c6 两测不论随机序（pytest-randomly）谁先跑
    都不得互相泄漏状态。"""
    from rfauto.infra.anchors_store import load_anchors

    return load_anchors(force_reload=force_reload)


def test_a1_c3_l_via_h_bit_exact() -> None:
    from rfauto.adapters.openems_templates import C3_L_VIA_CAL_H

    got = _live_anchor_set().resolve_anchor("c3.l_via_h.openems-hfss-v1")
    assert got["hit"] and got["source"] == "anchor" and got["domain_ok"]
    assert got["value"] == C3_L_VIA_CAL_H  # 逐位（0.125e-9）


_GAMMA_ER_POINTS = [1.5, 2.2, 3.0, 3.66, 4.4, 6.15, 10.2, 12.9]  # 8 定标点
_GAMMA_ER_SWEEP = [1.5 + i * (12.9 - 1.5) / 114 for i in range(115)]


def test_a3_cps_gamma_er_bit_exact() -> None:
    from rfauto.core.calculators import cps_effective_thickness_factor

    anchor_set = _live_anchor_set()
    for er in _GAMMA_ER_POINTS + _GAMMA_ER_SWEEP:
        got = anchor_set.resolve_anchor("cps.gamma_er.fdref-v1", {"er": er})
        assert got["hit"] and got["source"] == "anchor"
        # 逐位相等（同 op 序 1 + 0.9014*er**(-0.6361)，eval 语义同 float 运算）
        assert got["value"] == cps_effective_thickness_factor(er), f"er={er}"


def test_a4_siw_w_eff_bit_exact() -> None:
    from rfauto.core.calculators import siw_effective_width_mm

    anchor_set = _live_anchor_set()
    combos = [(w, d, s)
              for w in (10.0, 22.86, 63.0724)
              for d in (0.0, 0.5, 1.0, 1.525)
              for s in (1.0, 2.0, 3.05)]
    for w, d, s in combos:
        got = anchor_set.resolve_anchor(
            "siw.w_eff.lit-v1",
            {"w_mm": w, "d_mm": d, "s_mm": s})
        assert got["hit"] and got["source"] == "anchor"
        assert got["value"] == siw_effective_width_mm(w, d, s), \
            f"w={w} d={d} s={s}"


# ── 判据 c：内核语义 ───────────────────────────────────────────────────────

def test_c1_curve_monotonic_assertion() -> None:
    base = {"anchor_id": "t.k.curve-v1", "kind": "curve", "status": "active",
            "template_family": ["t"], "engine_pair": None, "quantity": {},
            "axis": {"param": "g_mm"}, "uncertainty": {"value": 0.01,
                                                       "kind": "relative"},
            "interp": {"method": "pchip", "extrapolate": "forbidden"},
            "domain": None}
    non_monotone = dict(base, points=[{"x": 0.0, "y": 1.0},
                                      {"x": 1.0, "y": 0.5},
                                      {"x": 2.0, "y": 0.8}])
    with pytest.raises(ValueError, match="非单调"):
        AnchorRecord.from_dict(non_monotone)


def _monotone_curve_set() -> AnchorSet:
    raw = [{
        "anchor_id": "t.k.curve-v1", "kind": "curve", "status": "active",
        "template_family": ["t"], "engine_pair": None, "quantity": {},
        "axis": {"param": "g_mm"},
        "points": [{"x": 0.0, "y": 1.0}, {"x": 0.5, "y": 0.6},
                   {"x": 1.0, "y": 0.3}, {"x": 2.0, "y": 0.1}],
        "interp": {"method": "pchip", "extrapolate": "forbidden"},
        "uncertainty": {"value": 0.01, "kind": "relative"},
        "domain": None, "provenance": {}, "registered_at": None,
        "consumers": [],
    }]
    return AnchorSet(raw)


def test_c2_curve_extrapolate_forbidden() -> None:
    anchor_set = _monotone_curve_set()
    rec = anchor_set.get("t.k.curve-v1")
    assert rec is not None
    # 直接求值：域外显式 ValueError（cps_corner2d"不外推"同款）
    with pytest.raises(ValueError, match="不外推"):
        rec.evaluate({"g_mm": 3.0})
    # 结构化面：resolve 域外 fallback 不抛
    got = anchor_set.resolve_anchor("t.k.curve-v1", {"g_mm": 3.0})
    assert got["hit"] and got["domain_ok"] is False
    assert got["source"] == "fallback" and got["value"] is None
    # 域内插值单调保持（pchip 保单调）
    vals = [anchor_set.resolve_anchor("t.k.curve-v1", {"g_mm": x / 20.0 * 2.0})["value"]
            for x in range(21)]
    assert all(a >= b for a, b in pairwise(vals))


def test_c3_formula_ast_whitelist_rejects_malicious() -> None:
    malicious = [
        "__import__('os').system('echo hi')",
        "open('/etc/passwd')",
        "er.__class__",
        "er.__dict__",
        "(lambda: 1)()",
        "sqrt(er, 2)",
        "[x for x in er]",
        "1; import os",
        "er if er else 0",
        "{'a': 1}",
    ]
    for expr in malicious:
        with pytest.raises(ValueError):
            compile_anchor_formula(expr, ["er"])
    # 合法词表（sqrt/log/四则/幂）放行
    assert compile_anchor_formula("1 + sqrt(er) / log(er) ** 2",
                                  ["er"]) is not None


def test_c4_unknown_anchor_fallback() -> None:
    got = AnchorSet([]).resolve_anchor("no.such.anchor-v1")
    assert got["hit"] is False and got["source"] == "fallback"
    assert got["value"] is None and got["version"] is None


def test_c5_awaiting_data_not_consumable() -> None:
    """awaiting_data 曲线锚不可消费（合成锚钉语义；真仓 k_of_g 已回填 active）。"""
    synthetic = AnchorSet([{
        "anchor_id": "synthetic.awaiting-v1",
        "kind": "curve",
        "template_family": ["t"],
        "quantity": {"name": "q", "unit": "dimensionless"},
        "axis": {"param": "g_mm"},
        "points": [],
        "interp": {"method": "pchip"},
        "status": "awaiting_data",
        "provenance": {},
    }])
    got = synthetic.resolve_anchor("synthetic.awaiting-v1", {"g_mm": 0.1})
    assert got["hit"] is False
    assert got["reason"] == "awaiting_data"
    assert got["source"] == "fallback" and got["value"] is None
    # 回填后的真仓锚可消费（active 曲线，域内求值）
    live = _live_anchor_set().resolve_anchor("c3.k_of_g.openems-hfss-v1",
                                             {"g_mm": 1.5})
    assert live["hit"] and live["status"] == "active"
    assert 0.049117 < live["value"] < 0.061579


def test_c5_formula_missing_param_fallback() -> None:
    got = _live_anchor_set().resolve_anchor("cps.gamma_er.fdref-v1")
    assert got["hit"] and got["source"] == "fallback"
    assert got["domain_ok"] is False
    assert "missing_params" in str(got.get("reason"))


def test_c5_domain_out_fallback_structured() -> None:
    got = _live_anchor_set().resolve_anchor("cps.gamma_er.fdref-v1",
                                            {"er": 15.0})
    assert got["hit"] and got["domain_ok"] is False
    assert got["source"] == "fallback" and got["value"] is None
    assert got["reason"] == "out_of_domain"


def test_c6_residual_within_threshold_ok() -> None:
    anchor_set = _live_anchor_set(force_reload=True)  # 洁净副本防跨测泄漏
    # γ(3.66)=1.3949…；观测偏差 < 5% 门 → ok 不 stale
    got = anchor_set.note_anchor_residual("cps.gamma_er.fdref-v1",
                                          {"er": 3.66}, 1.40)
    assert got["ok"] and got["stale"] is False and got["alarm"] is None
    rec = anchor_set.get("cps.gamma_er.fdref-v1")
    assert rec is not None and rec.status == "active"


def test_c6_residual_beyond_threshold_stale_alarm() -> None:
    anchor_set = _live_anchor_set(force_reload=True)  # 洁净副本防跨测泄漏
    # 观测偏差远超 max(3σ, 5%) 门 → 内存面翻 stale + 告警
    got = anchor_set.note_anchor_residual("cps.gamma_er.fdref-v1",
                                          {"er": 3.66}, 2.0)
    assert got["ok"] and got["stale"] is True
    assert got["alarm"] and "stale" in got["alarm"]
    rec = anchor_set.get("cps.gamma_er.fdref-v1")
    assert rec is not None and rec.status == "stale"  # 仅内存面；YAML 零改写


# ── HFSS 窗 B→A 批（wf:anchor-register，2026-09-29）：锚值与 verdict 互证 ──
# 三层互证：yaml 装载 → core resolve → verdict.json 实测门值逐位（只读证据，
# runs/ 归档零改写）。

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: constant 2 席：锚值 == verdict per_metric diff（judge_metric round(diff,6)）；
#: params 取声明域内名义点（constant 锚带域守卫，消费须带上下文）。
_B2A_CONSTANTS = {
    "wilkinson.f_match.openems-hfss-v1": (
        "runs/hfss_window_b2a/wilkinson/hfss_side/verdict.json",
        "f_match_ghz", {"arm_len_mm": 20.0},
    ),
    "gysel.s32_iso.openems-hfss-v1": (
        "runs/hfss_window_b2a/gysel/hfss_side/verdict.json",
        "s32_band_max_db", {"arm_len_mm": 18.0},
    ),
}

#: pointer 4 席：quantity.values 双值 == verdict 实测（oe/hfss 逐位）。
_B2A_POINTERS = {
    "stepped_impedance.f_pass.openems-hfss-v1": (
        "stepped_impedance", "f_dip_ghz"),
    "coupled_line.s31_coupling.openems-hfss-v1": (
        "coupled_line", "coupling_at_f0_db"),
    "marchand.f_null.openems-hfss-v1": (
        "marchand_balun", "f_null_ghz"),
    "branchline.f_match.openems-hfss-v1": (
        "branchline", "f_match_ghz"),
}


def _load_b2a_verdict(rel: str) -> dict:
    return json.loads((_REPO_ROOT / rel).read_text(encoding="utf-8"))


def test_b2a_window_constants_bit_exact_vs_verdict() -> None:
    _ev = Path(__file__).resolve().parents[2].joinpath("runs", "hfss_window_b2a", "wilkinson", "hfss_side", "verdict.json")
    if not _ev.exists():
        pytest.skip("runs/ 证据档缺席（公开分发视图）: " + str(_ev))
    """constant 锚值与 verdict 实测门值逐位一致（AGREE 席才可注册 constant）。"""
    anchor_set = _live_anchor_set()
    for aid, (rel, metric, params) in _B2A_CONSTANTS.items():
        verdict = _load_b2a_verdict(rel)
        assert verdict["verdict"] in ("AGREE_OPENEMS", "AGREE_JUDGE")
        assert verdict["machine"] == "sim_host"
        row = next(m for m in verdict["per_metric"] if m["metric"] == metric)
        assert row["in_gate"] is True  # 门内才定锚（DISAGREE 席改 pointer）
        got = anchor_set.resolve_anchor(aid, params)
        assert got["hit"] and got["source"] == "anchor", aid
        assert got["domain_ok"] and got["status"] == "active", aid
        assert got["value"] == row["diff"], aid  # 逐位（verdict 实测门值）
        # 源值对可回溯：per_metric 与 hfss_metrics/oe.values 同源一致
        assert row["hfss"] == verdict["hfss_metrics"][metric], aid
        assert row["oe"] == verdict["oe"]["values"][metric], aid


def test_b2a_window_pointers_dual_values_bit_exact_vs_verdict() -> None:
    _ev = Path(__file__).resolve().parents[2].joinpath("runs", "hfss_window_b2a", "gysel", "hfss_side", "verdict.json")
    if not _ev.exists():
        pytest.skip("runs/ 证据档缺席（公开分发视图）: " + str(_ev))
    """pointer 锚=双值分歧指针：不就地求值、双值逐位=verdict、消费面不接。"""
    anchor_set = _live_anchor_set()
    for aid, (seat, metric) in _B2A_POINTERS.items():
        verdict = _load_b2a_verdict(
            f"runs/hfss_window_b2a/{seat}/hfss_side/verdict.json")
        assert verdict["verdict"] == "DISAGREE"
        assert verdict["machine"] == "sim_host"
        rec = anchor_set.get(aid)
        assert rec is not None, aid
        assert rec.kind == "pointer" and rec.status == "experimental"
        # XC-A 回填（2026-10-02，374cc5b）曾给 wilkinson/branchline 两锚挂
        # +3 消费者；2026-10-04 G-07 将 branchline（pointer，evaluate 恒
        # None 不就地求值）对齐 pointer 契约清回 []——仅 wilkinson
        # （constant，XC-A 可消费）保留锚接声明，其余指针锚维持零接线
        assert rec.value is None
        if aid == "wilkinson.f_match.openems-hfss-v1":
            assert "src/rfauto/core/anchors.py" in (rec.consumers or [])
        else:
            assert rec.consumers == []
        got = anchor_set.resolve_anchor(aid)
        assert got["hit"] and got["source"] == "anchor"
        assert got["value"] is None  # pointer 不就地求值（双值在模型档案）
        vals = rec.raw["quantity"]["values"]
        assert vals["openems"] == verdict["oe"]["values"][metric], aid
        assert vals["hfss"] == verdict["hfss_metrics"][metric], aid


def test_b2a_window_anchors_stale_age_semantics() -> None:
    """stale 龄期语义：last_verified 距今严格大于 30 天才 stale（QW-3 口径）。"""
    import datetime

    from rfauto.service import anchors_service

    anchor_set = _live_anchor_set()
    for aid in (*_B2A_CONSTANTS, *_B2A_POINTERS):
        at = datetime.datetime.fromisoformat(
            anchor_set.get(aid).last_verified["at"])
        fresh = anchors_service.anchors_stale_report(
            now=at + datetime.timedelta(days=30))
        row = {r["anchor_id"]: r for r in fresh["anchors"]}
        assert row[aid]["stale"] is False, aid  # 恰 30 天不 stale（严格大于）
        aged = anchors_service.anchors_stale_report(
            now=at + datetime.timedelta(days=30, seconds=1))
        row = {r["anchor_id"]: r for r in aged["anchors"]}
        assert row[aid]["stale"] is True, aid  # 过线即 stale


# ── P-KJ-EVEN P3 批（wf:goal-t5，2026-09-30）：KJ even 闭式适用域盒锚───────
# 域盒语义钉：入盒 hit+域内基准逐位；越域消费点（P1 §4/§8.6 清单）结构化
# fallback=out_of_domain（越域告警语义，不抛）；两条域缘 MARGINAL 注记随
# provenance 落档。证据链：runs/df7_kjeven p1_audit §8.5/§8.6 → p2 判读
# §4/§6 → elmer_recheck §5（T3 核验 0795b2a 解锁）。

_KJ_DOMAIN_AID = "coupled_microstrip.kj_even_domain.lit-v1"


def test_kj_even_domain_box_in_domain_hit() -> None:
    """域内工作点（y1：u=1.8195/g=0.1614/er=3.66）hit+域内基准逐位。"""
    anchor_set = _live_anchor_set()
    got = anchor_set.resolve_anchor(_KJ_DOMAIN_AID,
                                    {"u": 1.8195, "g": 0.1614, "er": 3.66})
    assert got["hit"] and got["source"] == "anchor"
    assert got["domain_ok"] and got["status"] == "active"
    assert got["value"] == 0.66  # 域内观测最大偏差（εeff_e @y1，P1 表逐位）
    rec = anchor_set.get(_KJ_DOMAIN_AID)
    assert rec is not None
    assert rec.kind == "constant"  # 零接线断言已按 XC-A 回填时点收窄（consumers 消费面由 store_service EXPECTED 单源钉）
    # 域盒边界逐位（qucs-doc 文献声明域，P1 §8.6）
    assert rec.domain == {"u": [0.1, 10], "g": [0.1, 10], "er": [1, 18]}
    # 盒角/盒缘点在盒内（edge_a=角 0.1/0.1、edge_b=缘 10/0.1，闭区间语义）
    for params in ({"u": 0.1, "g": 0.1, "er": 3.66},
                   {"u": 10.0, "g": 0.1, "er": 3.66},
                   {"u": 1.8195, "g": 3.937, "er": 3.66},
                   {"u": 0.5906, "g": 0.1614, "er": 3.66}):
        got = anchor_set.resolve_anchor(_KJ_DOMAIN_AID, params)
        assert got["domain_ok"], params


def test_kj_even_domain_box_out_of_domain_fallback() -> None:
    """越域消费点结构化 fallback（P1 §4 三越域点+er/u 越界）。"""
    anchor_set = _live_anchor_set()
    for label, params in (
            ("lange g=0.076", {"u": 0.329, "g": 0.076, "er": 3.66}),
            ("cline6 g=0.0394", {"u": 1.355, "g": 0.0394, "er": 3.66}),
            ("bpf_fbw10 g=0.0885", {"u": 1.23, "g": 0.0885, "er": 3.66}),
            ("er 越上界", {"u": 1.8195, "g": 0.1614, "er": 18.5}),
            ("u 越下界", {"u": 0.05, "g": 1.0, "er": 3.66})):
        got = anchor_set.resolve_anchor(_KJ_DOMAIN_AID, params)
        assert got["hit"], label  # 锚在册，仅域外
        assert got["source"] == "fallback" and got["domain_ok"] is False, label
        assert got["reason"] == "out_of_domain" and got["value"] is None, label


def test_kj_even_domain_edge_notes_registered() -> None:
    """两条域缘 MARGINAL 注记随锚落档（P2 判读 §6/elmer_recheck §5.3）。"""
    rec = _live_anchor_set().get(_KJ_DOMAIN_AID)
    assert rec is not None
    note = str(rec.provenance.get("domain_note") or "")
    # 注记 1：odd u=10/g=0.1 角 ~−1.5%（MARGINAL 不设门）
    assert "u=10/g=0.1" in note and "1.5" in note and "MARGINAL" in note
    # 注记 2：even u=10 对空气盒顶高敏感（10h 顶 +1.07%）
    assert "10h" in note and "1.07" in note
    # 域内基准出处可回溯（Elmer 复核摘要+J1 门）
    assert rec.provenance.get("referee_script") == \
        "runs/df7_kjeven/elmer_recheck/elmer_recheck.py"
    assert rec.uncertainty is not None and rec.uncertainty["value"] == 1.0


# ── ge6 Wave1 锚注册批（wf:ge6-anchor，2026-10-01）：Dk 指针锚互证 ─────────
# 三层互证：yaml 装载 → core resolve → runs/ 证据档实测值逐位（只读证据，
# runs/ 归档零改写；B2A verdict 同口径——证据档仓本机在档）。

_RING_DK_AID = "ring.design_dk.openems-hfss-v1"
_MMWAVE_DK_AID = "mmwave.design_dk.ro3003-oe-v1"


def test_ge6_ring_pointer_dual_values_bit_exact_vs_prep() -> None:
    _ev = Path(__file__).resolve().parents[2].joinpath("runs", "ge5_fa3_dk", "anchor_prep.json")
    if not _ev.exists():
        pytest.skip("runs/ 证据档缺席（公开分发视图）: " + str(_ev))
    """ring Dk 指针锚：双值逐位=FA3 预备稿 anchor_prep.json（DISAGREE 实测）。"""
    prep = json.loads(
        (_REPO_ROOT / "runs" / "ge5_fa3_dk" / "anchor_prep.json")
        .read_text(encoding="utf-8"))
    assert prep["anchor_id"] == _RING_DK_AID
    assert prep["kind"] == "pointer" and prep["status"] == "experimental"
    anchor_set = _live_anchor_set()
    rec = anchor_set.get(_RING_DK_AID)
    assert rec is not None
    assert rec.kind == "pointer" and rec.status == "experimental"
    assert rec.value is None and rec.consumers == []  # 消费面不接
    got = anchor_set.resolve_anchor(_RING_DK_AID, {"f_ghz": 2.42})
    assert got["hit"] and got["source"] == "anchor"
    assert got["value"] is None  # pointer 不就地求值（双值在模型档案）
    vals = rec.raw["quantity"]["values"]
    assert vals["openems"] == prep["values"]["oe"]  # 逐位
    assert vals["hfss"] == prep["values"]["hfss"]  # 逐位
    # 方法域守卫（#302）：单频点域，越域消费=结构化 out_of_domain
    off = anchor_set.resolve_anchor(_RING_DK_AID, {"f_ghz": 3.0})
    assert off["hit"] and off["source"] == "fallback"
    assert off["domain_ok"] is False and off["reason"] == "out_of_domain"
    assert "forbidden" in str(rec.provenance.get("domain_note"))


def test_ge6_mmwave_pointer_value_bit_exact_vs_rejudge() -> None:
    _ev = Path(__file__).resolve().parents[2].joinpath("runs", "ge6_anchor", "rejudge")
    if not _ev.exists():
        pytest.skip("runs/ 证据档缺席（公开分发视图）: " + str(_ev))
    """mmwave Dk 指针锚（OE 单引擎）：值逐位=离线复判 verdict 注册值。"""
    verdict = json.loads(
        (_REPO_ROOT / "runs" / "ge6_anchor" / "verdict.json")
        .read_text(encoding="utf-8"))
    assert verdict["verdict"] == "PASS" and verdict["zero_resim"] is True
    assert verdict["gates"]["R3_old_nominal_explained_by_dk_anchor"] is True
    anchor_set = _live_anchor_set()
    rec = anchor_set.get(_MMWAVE_DK_AID)
    assert rec is not None
    assert rec.kind == "pointer" and rec.status == "experimental"
    assert rec.value is None and rec.consumers == []  # 单引擎封档零消费
    got = anchor_set.resolve_anchor(_MMWAVE_DK_AID, {"f_ghz": 78.0})
    assert got["hit"] and got["source"] == "anchor" and got["value"] is None
    assert rec.raw["quantity"]["values"]["openems"] == \
        verdict["anchor_registration"]["registered_value"]  # 逐位 3.1434
    # 越域结构化 fallback（#302 单频点）
    off = anchor_set.resolve_anchor(_MMWAVE_DK_AID, {"f_ghz": 76.2})
    assert off["source"] == "fallback" and off["reason"] == "out_of_domain"
    # unlock 条件+方法域警告随锚落档
    note = str(rec.provenance.get("domain_note") or "")
    assert "forbidden" in note and "#302" in note
    assert "HFSS" in str(rec.raw["quantity"]["semantics"])  # 仲裁腿 unlock
