"""XD-8 M 级残差：下层不确定度流入测试（closure/component/system 传播口径）。

判据（预声明，2026-10-08 尾程席 XR；规格
docs/research_expansion_20261004_crossdomain_transplant.md:97）：
- closure 底层：流入=自身 σ（identity=0 直传 rule=identity_passthrough_bottom；
  绝对带 rule=bottom_own_sigma；relative 按 constant 自身值折算）；
- component/system：引用链下层锚（层秩严格更低的 prose 词边界提及/显式
  derived_from 声明）逐锚取 σ 后一层 RSS 聚合（GUM TSM √Σσ²）——
  identity 贡献 0 直传 / pointer 取 uncertainty 字段 / 任一不可折算或
  无下层引用 → inflow=None（不虚构，#316 多报方向）；
- 词边界守卫：suspended_stripline ⊃ stripline 子串假引用排除（实测
  live 注册表 2 条此类假命中）；
- resolve_anchor 加性键 vv_inflow（既有键零破坏；未知锚早退路径无此键
  如实）；live 注册表 75 锚全量可算（2026-10-14 架构批 GATE-FINAL 对账）、无 lower_refs_rss 边（2026-10-08
  实测口径：全部 prose 引用同层，零跨层引用边——将来加跨层引用时本钉
  随事实更新）。
"""

from __future__ import annotations

import math

from rfauto.core.anchors import (
    ANCHOR_INFLOW_SCHEMA,
    LAYER_RANK,
    AnchorSet,
    uncertainty_inflow,
)


def _rec(aid: str, *, layer: str = "closure", kind: str = "constant",
         value: float | None = 1.0, uncertainty: dict | None = None,
         quantity: dict | None = None, extra: dict | None = None) -> dict:
    raw: dict = {
        "anchor_id": aid, "kind": kind, "status": "active", "layer": layer,
        "template_family": ["t"],
        "engine_pair": {"calibrated": "closedform", "referee": None},
        "quantity": quantity or {"name": "q", "unit": None},
        "value": value, "uncertainty": uncertainty, "domain": None,
        "provenance": {}, "registered_at": "2026-10-08T00:00:00+08:00",
        "last_verified": None, "fallback": "closed_form", "consumers": [],
    }
    if extra:
        raw.update(extra)
    return raw


_IDENTITY = {"value": 0.0, "kind": "identity", "note": "闭式恒等锚"}


# ── closure 底层：直传口径 ────────────────────────────────────────────────

def test_closure_identity_passthrough_zero() -> None:
    aset = AnchorSet([_rec("kern.q.closedform-v1", uncertainty=dict(_IDENTITY))])
    got = uncertainty_inflow(aset, "kern.q.closedform-v1")
    assert got["layer"] == "closure" and got["layer_rank"] == 0
    assert got["inflow_sigma_abs"] == 0.0  # identity=0 直传（逐位）
    assert got["rule"] == "identity_passthrough_bottom"
    assert got["vv_schema"] == ANCHOR_INFLOW_SCHEMA
    assert any("全链" in n for n in got["notes"])  # 克制登记随行


def test_closure_absolute_band_own_sigma() -> None:
    aset = AnchorSet([_rec("kern.q.closedform-v1",
                           uncertainty={"value": 0.005,
                                        "kind": "rounding_band"})])
    got = uncertainty_inflow(aset, "kern.q.closedform-v1")
    assert got["inflow_sigma_abs"] == 0.005
    assert got["rule"] == "bottom_own_sigma"


def test_closure_relative_folds_at_own_constant_value() -> None:
    aset = AnchorSet([_rec("kern.q.closedform-v1", value=4.0,
                           uncertainty={"value": 0.05, "kind": "relative"})])
    got = uncertainty_inflow(aset, "kern.q.closedform-v1")
    assert got["inflow_sigma_abs"] == 0.05 * 4.0  # relative 按自身值折算
    assert got["rule"] == "bottom_own_sigma"


# ── component/system：引用链下层一层 RSS ─────────────────────────────────

def test_component_identity_ref_zero_contribution() -> None:
    aset = AnchorSet([
        _rec("kern.q.closedform-v1", uncertainty=dict(_IDENTITY)),
        _rec("dev.x.openems-hfss-v1", layer="component",
             uncertainty={"value": 0.5, "kind": "arbitration_interval"},
             extra={"provenance": {"devlog":
                                   "回代基准同 kern.q.closedform-v1 已核双源"}}),
    ])
    got = uncertainty_inflow(aset, "dev.x.openems-hfss-v1")
    assert got["rule"] == "lower_refs_rss_one_layer"
    assert got["inflow_sigma_abs"] == 0.0  # identity 下层贡献 0 直传
    assert len(got["lower_refs"]) == 1
    assert got["lower_refs"][0]["role"] == "identity_passthrough"
    assert got["lower_refs"][0]["layer"] == "closure"


def test_component_pointer_ref_takes_uncertainty_field() -> None:
    # system 层锚引用 component 层 pointer 锚（严格下层；pointer 取
    # uncertainty 字段为 XD-8 第二条传播规则）
    aset = AnchorSet([
        _rec("dev.ptr.openems-hfss-v1", layer="component", kind="pointer",
             value=None, quantity={"name": "q", "values":
                                   {"openems": 3.5, "hfss": 3.3}},
             uncertainty={"value": 0.13, "kind": "engine_pair_spread"}),
        _rec("sys.y.openems-hfss-v1", layer="system",
             uncertainty={"value": 0.1, "kind": "arbitration_interval"},
             extra={"provenance": {"derived_from":
                                   ["dev.ptr.openems-hfss-v1"]}}),
    ])
    got = uncertainty_inflow(aset, "sys.y.openems-hfss-v1")
    assert got["rule"] == "lower_refs_rss_one_layer"
    # pointer 取 uncertainty 字段（absolute 带直取，不折算 values）
    assert got["inflow_sigma_abs"] == 0.13
    assert got["lower_refs"][0]["role"] == "pointer_uncertainty_field"


def test_component_rss_two_refs_bit_exact() -> None:
    aset = AnchorSet([
        _rec("kern.a.closedform-v1", uncertainty=dict(_IDENTITY)),
        _rec("kern.b.closedform-v1",
             uncertainty={"value": 0.03, "kind": "rounding_band"}),
        _rec("kern.c.closedform-v1",
             uncertainty={"value": 0.04, "kind": "fd_referee_band"}),
        _rec("dev.z.openems-hfss-v1", layer="component",
             uncertainty={"value": 0.1, "kind": "arbitration_interval"},
             extra={"provenance": {"devlog":
                                   "链 A=kern.a.closedform-v1；"
                                   "链 B=kern.b.closedform-v1；"
                                   "链 C=kern.c.closedform-v1"}}),
    ])
    got = uncertainty_inflow(aset, "dev.z.openems-hfss-v1")
    assert got["rule"] == "lower_refs_rss_one_layer"
    # 与实现同式逐位（GUM TSM √Σσ²；identity 贡献 0 不影响 RSS）
    expect = math.sqrt(0.0 ** 2 + 0.03 ** 2 + 0.04 ** 2)
    assert got["inflow_sigma_abs"] == expect
    assert [r["anchor_id"] for r in got["lower_refs"]] == [
        "kern.a.closedform-v1", "kern.b.closedform-v1",
        "kern.c.closedform-v1"]  # 确定性排序


def test_component_unresolvable_ref_inflow_none_not_zero() -> None:
    # 公式锚 relative 不确定度无就地折算基准（不传 params 求值）→ 贡献不可折算
    aset = AnchorSet([
        _rec("kern.rel.closedform-v1", kind="formula", value=None,
             extra={"expr": "2*w", "variables": ["w"],
                    "uncertainty": {"value": 0.05, "kind": "relative"}}),
        _rec("dev.w.openems-hfss-v1", layer="component",
             uncertainty={"value": 0.1, "kind": "arbitration_interval"},
             extra={"provenance": {"devlog":
                                   "基准 kern.rel.closedform-v1"}}),
    ])
    got = uncertainty_inflow(aset, "dev.w.openems-hfss-v1")
    # relative 公式锚无就地折算基准 → 流入 None（不虚构，#316 多报方向）
    assert got["inflow_sigma_abs"] is None
    assert got["rule"] != "lower_refs_rss_one_layer"
    assert any("不可折算" in n for n in got["notes"])


def test_component_no_lower_refs_inflow_none() -> None:
    aset = AnchorSet([
        _rec("kern.q.closedform-v1", uncertainty=dict(_IDENTITY)),
        _rec("dev.solo.openems-hfss-v1", layer="component",
             uncertainty={"value": 0.1, "kind": "arbitration_interval"}),
    ])
    got = uncertainty_inflow(aset, "dev.solo.openems-hfss-v1")
    assert got["rule"] == "no_lower_refs"
    assert got["inflow_sigma_abs"] is None  # 无引用≠零流入


def test_same_layer_prose_mention_not_lower_ref() -> None:
    aset = AnchorSet([
        _rec("dev.p.openems-hfss-v1", layer="component",
             uncertainty={"value": 0.2, "kind": "arbitration_interval"}),
        _rec("dev.q.openems-hfss-v1", layer="component",
             uncertainty={"value": 0.1, "kind": "arbitration_interval"},
             extra={"provenance": {"devlog":
                                   "与 dev.p.openems-hfss-v1 跨案例同向互证"}}),
    ])
    got = uncertainty_inflow(aset, "dev.q.openems-hfss-v1")
    assert got["rule"] == "no_lower_refs"  # 同层互证提及≠下层流入
    assert got["lower_refs"] == []


def test_substring_false_reference_blocked_by_boundary_guard() -> None:
    # suspended_stripline ⊃ stripline 子串假引用（live 注册表实测形态）：
    # 词边界守卫（前字符 ∈ id 词表含 '_' '.'）必须排除
    aset = AnchorSet([
        _rec("stripline.z0_ohm.closedform-v1",
             uncertainty={"value": 0.02, "kind": "rounding_band"}),
        _rec("dev.fake.openems-hfss-v1", layer="component",
             uncertainty={"value": 0.1, "kind": "arbitration_interval"},
             extra={"provenance": {"devlog":
                                   "见 susp.stripline.z0_ohm.closedform-v1"}}),
    ])
    got = uncertainty_inflow(aset, "dev.fake.openems-hfss-v1")
    assert got["rule"] == "no_lower_refs"
    assert got["lower_refs"] == []


# ── 边界与 resolve 集成 ──────────────────────────────────────────────────

def test_unknown_anchor_and_missing_layer() -> None:
    aset = AnchorSet([_rec("kern.q.closedform-v1", uncertainty=dict(_IDENTITY))])
    got = uncertainty_inflow(aset, "no.such.anchor-v1")
    assert got["rule"] == "unknown_anchor"
    raw = _rec("old.x.closedform-v1",
               uncertainty=dict(_IDENTITY))  # layer 缺失=旧条目兼容形态
    del raw["layer"]
    aset2 = AnchorSet([raw])
    got2 = uncertainty_inflow(aset2, "old.x.closedform-v1")
    assert got2["rule"] == "unknown_layer" and got2["inflow_sigma_abs"] is None
    assert LAYER_RANK == {"closure": 0, "component": 1, "system": 2}


def test_resolve_anchor_carries_vv_inflow_additively() -> None:
    aset = AnchorSet([
        _rec("kern.q.closedform-v1", uncertainty=dict(_IDENTITY)),
        _rec("dev.solo.openems-hfss-v1", layer="component",
             uncertainty={"value": 0.1, "kind": "arbitration_interval"}),
    ])
    got = aset.resolve_anchor("kern.q.closedform-v1")
    assert got["hit"] and got["value"] == 1.0  # 既有键零破坏
    assert got["vv_inflow"]["rule"] == "identity_passthrough_bottom"
    assert got["vv_inflow"]["inflow_sigma_abs"] == 0.0
    # 未知锚早退路径无 vv_inflow 键（如实：未知锚无可判层级）
    miss = aset.resolve_anchor("no.such.anchor-v1")
    assert not miss["hit"] and "vv_inflow" not in miss


def test_live_registry_all_anchors_inflow_no_cross_layer_edges() -> None:
    """live 79 锚全量可算（2026-10-18 W3-S15 批后
    批次再推进 +5，closure 57/component 14/system 4）；closure=底层直传口径；零跨层引用边（2026-10-08
    实测口径——全部 prose 引用同层，将来加跨层引用时本钉随事实更新）。"""
    from rfauto.infra.anchors_store import load_anchors

    aset = load_anchors()
    assert len(aset) == 87 and not aset.load_errors  # W3-S15 批 75→79 → aurora_j W4-S15 批 79→87
    rules: dict[str, int] = {}
    for rec in aset.records:
        got = uncertainty_inflow(aset, rec.anchor_id)
        assert got["layer"] == rec.layer
        assert got["aggregation"] == "rss_one_layer"
        rules[got["rule"]] = rules.get(got["rule"], 0) + 1
        if rec.layer == "closure":
            assert got["rule"] in ("identity_passthrough_bottom",
                                   "bottom_own_sigma")
        else:
            assert got["rule"] == "no_lower_refs", rec.anchor_id
            assert got["inflow_sigma_abs"] is None
    # closure identity 锚确实按 0 直传（非全带 own_sigma 退化）
    assert rules.get("identity_passthrough_bottom", 0) >= 1
    assert rules.get("bottom_own_sigma", 0) >= 1
    assert rules.get("no_lower_refs", 0) == 21  # component 17 + system 4（W4-S15 批 +3）
    assert rules.get("lower_refs_rss_one_layer", 0) == 0


def test_service_resolve_passthrough_carries_inflow() -> None:
    from rfauto.service.anchors_service import resolve_anchor_request

    out = resolve_anchor_request("c3.l_via_h.openems-hfss-v1")
    assert out["ok"]
    assert out["result"]["vv_inflow"]["rule"] == "no_lower_refs"
    assert out["result"]["vv_inflow"]["layer"] == "component"
    assert out["result"]["hit"] and out["result"]["value"] == 0.125e-9
