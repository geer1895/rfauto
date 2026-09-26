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

from itertools import pairwise

import pytest

from rfauto.core.anchors import (
    EXPECTED_ANCHORS,
    AnchorRecord,
    AnchorSet,
    compile_anchor_formula,
)

# ── 内核单源与构造语义 ─────────────────────────────────────────────────────


def test_expected_anchors_single_source_shape() -> None:
    assert len(EXPECTED_ANCHORS) == 6
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

def _live_anchor_set() -> AnchorSet:
    """从真实注册表构造（零 IO 依赖由 conftest 仓库根保证；直接 yaml 读会
    与 store 层重复，这里用 infra 装载面共享缓存）。"""
    from rfauto.infra.anchors_store import load_anchors

    return load_anchors()


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
    anchor_set = _live_anchor_set()
    # γ(3.66)=1.3949…；观测偏差 < 5% 门 → ok 不 stale
    got = anchor_set.note_anchor_residual("cps.gamma_er.fdref-v1",
                                          {"er": 3.66}, 1.40)
    assert got["ok"] and got["stale"] is False and got["alarm"] is None
    rec = anchor_set.get("cps.gamma_er.fdref-v1")
    assert rec is not None and rec.status == "active"


def test_c6_residual_beyond_threshold_stale_alarm() -> None:
    anchor_set = _live_anchor_set()
    # 观测偏差远超 max(3σ, 5%) 门 → 内存面翻 stale + 告警
    got = anchor_set.note_anchor_residual("cps.gamma_er.fdref-v1",
                                          {"er": 3.66}, 2.0)
    assert got["ok"] and got["stale"] is True
    assert got["alarm"] and "stale" in got["alarm"]
    rec = anchor_set.get("cps.gamma_er.fdref-v1")
    assert rec is not None and rec.status == "stale"  # 仅内存面；YAML 零改写
