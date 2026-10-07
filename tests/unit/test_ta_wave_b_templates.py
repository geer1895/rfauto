"""TA-10/AP-11 两模板测试（ge8b Wave B 席 B9，2026-10-03）。

覆盖（#118 每件 ≥2 独立基准；#212 离线审计先行——几何审计由
test_template_geometry_audit 五钉泛化覆盖，本文件补模板专属判读面）：
- core/isl_line：对称退化恒等（≡_stripline_z0 逐位）/εr=1/w→∞ 串联层
  wide-limit/单调性/50Ω 设计链回代；
- core/vivaldi_tsa：指数律往返恒等/口面↔截止双向回收/单调性；
- 渲染契约：isl 悬浮基板+藩篱/顶板分层、vivaldi 阶梯化地面+跨槽馈、
  nominal 全链复算逐键钉（#1c/#252）；
- 锚树：isl_shielded.eps_eff.closedform-v1 / vivaldi_tsa.f_low_ghz.
  closedform-v1 数值回放（knowledge/anchors.yaml 对拍）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.oe_templates.render_ta_wave_b import (
    isl_layout,
    vivaldi_layout,
)
from rfauto.adapters.openems_templates import (
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    render_script,
)
from rfauto.core.calculators import _stripline_z0
from rfauto.core.isl_line import (
    inverted_ms_qs,
    isl_design_params,
    isl_two_half_c,
    suspended_ms_qs,
)
from rfauto.core.vivaldi_tsa import (
    vivaldi_low_cutoff_ghz,
    vivaldi_slot_half_width_mm,
    vivaldi_taper_k_per_mm,
    vivaldi_tsa_design,
)

C0 = 299792458.0


# ─── TA-10 内核：三精确极限（#118 独立基准）────────────────────────────────

def test_isl_symmetric_limit_reduces_to_stripline_single_source():
    """恒等基准①：h1=h2=h 且 ε1eq=ε2=εr → Z0/εeff ≡ _stripline_z0 逐位。"""
    from rfauto.core.isl_line import isl_layer_stack_eps_eq

    w, h, er = 1.111, 1.016, 3.66
    eps_eq = isl_layer_stack_eps_eq(((h, er),))  # 单层串联=er 本身
    c_med, c_air = isl_two_half_c(w * 1e-3, h * 1e-3, eps_eq,
                                  h * 1e-3, eps_eq)
    eps_eff = c_med / c_air
    z0 = math.sqrt(eps_eff) / (C0 * c_med)
    assert eps_eff == pytest.approx(er, rel=1e-12)
    assert z0 == pytest.approx(_stripline_z0(w, 2.0 * h, er), rel=1e-12)


def test_isl_er_one_limit_eps_eff_exact():
    """恒等基准②：εr=1 全空气 → εeff=1 精确。"""
    out = suspended_ms_qs(2.4818, 0.508, 0.508, 1.0, 1.016)
    assert out["eps_eff"] == pytest.approx(1.0, rel=1e-12)


def test_isl_wide_limit_series_stack_exact():
    """恒等基准③：w→∞ 且 h1=h2 → εeff = 逐径/算术混合共有的串联层精确值。"""
    g, hs, ht, er = 0.508, 0.508, 1.016, 3.66
    eps1 = (g + hs) / (g + hs / er)
    exact = (eps1 * (g + hs) + 1.0 * ht) / ((g + hs) + ht)
    out = suspended_ms_qs(20.0, g, hs, er, ht)  # w/D≈10 已进 wide 平台
    assert out["eps_eff"] == pytest.approx(exact, rel=1e-6)


def test_isl_monotonicity_in_er_and_air_gap():
    """单调性：εr↑ → εeff↑；g↑（空气份额↑）→ εeff↓。"""
    ref = suspended_ms_qs(2.4818, 0.508, 0.508, 3.66, 1.016)["eps_eff"]
    hi = suspended_ms_qs(2.4818, 0.508, 0.508, 4.66, 1.016)["eps_eff"]
    lo = suspended_ms_qs(2.4818, 0.508, 0.508, 2.66, 1.016)["eps_eff"]
    assert lo < ref < hi
    g_hi = suspended_ms_qs(2.4818, 0.808, 0.508, 3.66, 1.016)["eps_eff"]
    assert g_hi < ref


def test_isl_design_params_roundtrip():
    """50Ω 设计链：brentq 反解 → 回代自洽 |ΔZ0|≤0.01Ω；名义逐键钉。"""
    out = isl_design_params(50.0, 0.508, 0.508, 1.016, 3.66)
    assert out["w_mm"] == pytest.approx(2.4818, abs=5e-4)
    assert abs(out["z0_ohm"] - 50.0) <= 0.01
    assert out["eps_eff"] == pytest.approx(1.2854, abs=5e-4)
    nom = TEMPLATE_NOMINAL["isl_shielded"]
    assert nom["w_mm"] == pytest.approx(out["w_mm"], abs=5e-5)
    qs = suspended_ms_qs(nom["w_mm"], nom["g_air_mm"], 0.508,
                         nom["er"], nom["h_top_mm"])
    assert qs["z0_ohm"] == pytest.approx(50.0, abs=0.02)
    assert qs["eps_eff"] == pytest.approx(1.2854, abs=1e-3)


def test_isl_inverted_flavor_cross_reference():
    """倒置口径（金属/介质 z 序对调）在名义同 w 点：εeff 低于悬置口径
    （介质整体移到上半腔远离条带）——与 core/inverted_ms FD 反演面语义
    相容的定性交叉参考（FD 裁判面数值互证归真机窗，不互替）。"""
    sus = suspended_ms_qs(2.4818, 0.508, 0.508, 3.66, 1.016)
    inv = inverted_ms_qs(2.4818, 0.508, 0.508, 3.66, 1.016)
    assert inv["eps_eff"] < sus["eps_eff"]
    assert 1.0 < inv["eps_eff"] < sus["eps_eff"]


# ─── AP-11 内核：恒等式裁判 ────────────────────────────────────────────────

def test_vivaldi_roundtrip_and_cutoff_reconstruction():
    """恒等基准：指数律往返 + 口面↔截止双向回收（f_low ↔ w_mouth）。"""
    d = vivaldi_tsa_design(6.0, 0.3, 80.0)
    assert d["w_mouth_mm"] == pytest.approx(24.982705, abs=5e-7)
    assert d["f_low_ghz"] == pytest.approx(6.0, abs=1e-6)
    k = vivaldi_taper_k_per_mm(0.3, d["w_mouth_mm"], 80.0)
    assert k == pytest.approx(d["k_per_mm"], rel=1e-12)
    # 口面半波准则自洽：2·w_mouth @f_low = c/f_low（6 位舍入带 ≤1nm）
    assert 2 * d["w_mouth_mm"] * 1e-3 == pytest.approx(
        C0 / (6.0 * 1e9), abs=1e-9)
    assert vivaldi_low_cutoff_ghz(d["w_mouth_mm"]) == pytest.approx(
        6.0, abs=1e-6)


def test_vivaldi_taper_trace_and_monotonicity():
    """指数律轨迹：w(x) 端点/中点精确回收；k 随 L 增单调降（张口越缓）。"""
    k = vivaldi_taper_k_per_mm(0.3, 24.9827, 80.0)
    assert vivaldi_slot_half_width_mm(0.0, 0.3, k) == pytest.approx(0.15)
    assert vivaldi_slot_half_width_mm(80.0, 0.3, k) == pytest.approx(
        24.9827 / 2, rel=1e-9)
    mid = vivaldi_slot_half_width_mm(40.0, 0.3, k)
    assert mid == pytest.approx(0.15 * math.exp(k * 40.0), rel=1e-12)
    k_long = vivaldi_taper_k_per_mm(0.3, 24.9827, 160.0)
    assert k_long < k


# ─── 渲染契约（模板专属判读面；泛化审计在 test_template_geometry_audit）────

def _load(template: str):
    sys.path.insert(0, str(REPO / "tests"))
    from tests.unit import _geometry_audit_helpers as gh

    return gh.load_geometry(template)


def test_isl_render_stack_and_shield():
    """ISL 渲染面：基板悬浮 [g, g+h]、条带 z=基板上表面恰在网格线、顶板
    z=g+h+h_top 精确线、藩篱贯通 0..z_wall 且与条带 DC 隔离。"""
    scope, prims = _load("isl_shielded")
    nom = TEMPLATE_NOMINAL["isl_shielded"]
    z_gap = nom["g_air_mm"] * 1e-3
    z_strip = z_gap + 0.508e-3
    z_wall = z_strip + nom["h_top_mm"] * 1e-3
    by_prop = {}
    for p in prims:
        by_prop.setdefault(p.prop, []).append(p)
    assert "isl_strip" in by_prop and "isl_wall" in by_prop \
        and "isl_via" in by_prop
    strip = by_prop["isl_strip"][0]
    assert strip.lo[2] == pytest.approx(z_strip, rel=1e-9)
    assert strip.hi[2] == pytest.approx(z_strip, rel=1e-9)
    wall = by_prop["isl_wall"][0]
    assert wall.lo[2] == pytest.approx(z_wall, rel=1e-9)
    vias = by_prop["isl_via"]
    assert len(vias) >= 40  # 两列 × k_half≥20
    for v in vias:
        assert v.lo[2] == pytest.approx(0.0, abs=1e-12)
        assert v.hi[2] == pytest.approx(z_wall, rel=1e-9)
        assert abs(abs(v.lo[0]) - nom["w_mm"] * 1e-3 / 2) > 1e-4  # 净距>0.1mm
    z_lines = gh_lines(scope)
    assert any(abs(z - z_strip) <= 1e-6 for z in z_lines)
    assert any(abs(z - z_wall) <= 1e-6 for z in z_lines)


def gh_lines(scope):
    return np.asarray(scope["mesh"].GetLines("z"), dtype=float)


def test_vivaldi_render_profile_and_feed():
    """Vivaldi 渲染面：阶梯化站数=24、口面宽≈w_mouth、喉宽≈w_throat、
    馈线跨槽于 y_feed、口面外地盒封到板缘。"""
    _scope, prims = _load("vivaldi_tsa")
    nom = TEMPLATE_NOMINAL["vivaldi_tsa"]
    lay = vivaldi_layout(dict(nom))
    stairs = [p for p in prims if p.prop == "vivaldi_gnd"]
    assert len(stairs) == 2 * (len(lay["stations_y"]) - 1) + 1  # 2×站盒+口面外
    # 站盒左缘=站起点半宽；末段 [y[-2], y[-1]] 的槽缘=stations_hw[-2]
    hw_last = max(p.lo[0] for p in stairs
                  if p.lo[1] > 0 and p.hi[1] * 1e3 <= lay["y_mouth"] + 1e-9
                  and p.lo[0] > 0)
    assert hw_last == pytest.approx(lay["stations_hw"][-2] * 1e-3, rel=1e-6)
    # 3 原语=手画跨槽盒 + 双 MSLPort 自动馈段（共用 vivaldi_feed 属性）
    feed = [p for p in prims if p.prop == "vivaldi_feed"]
    assert len(feed) == 3
    assert all(p.lo[2] == pytest.approx(0.508e-3, rel=1e-9) for p in feed)
    assert any(abs(p.lo[1] - (lay["y_feed"] - lay["feed_w"] / 2) * 1e-3)
               <= 1e-9 for p in feed)


def test_meta_contract_new_templates():
    """meta 契约：n_ports/params/radiator/端口轴注册一致。"""
    from rfauto.adapters.oe_templates.registry import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
    )

    assert TEMPLATE_META["isl_shielded"]["n_ports"] == 2
    assert TEMPLATE_META["vivaldi_tsa"]["n_ports"] == 2
    assert _TEMPLATE_PORT_AXES["isl_shielded"] == ("y",)
    assert _TEMPLATE_PORT_AXES["vivaldi_tsa"] == ("x",)
    assert _TEMPLATE_RADIATOR["isl_shielded"] is False
    assert _TEMPLATE_RADIATOR["vivaldi_tsa"] is True
    for t in ("isl_shielded", "vivaldi_tsa"):
        assert set(TEMPLATE_META[t]["params"]) <= set(TEMPLATE_NOMINAL[t])


def test_isl_layout_mesh_guards_reject_bad_via():
    """守卫面：过孔直径 <4·NEAR / 孔间缝 ≤NEAR 渲染期拒绝（hmsiw 同口径）。"""
    with pytest.raises(ValueError, match="4·NEAR"):
        isl_layout({"d_mm": 0.2}, 0.4e-3, 0.508e-3)
    with pytest.raises(ValueError, match="孔间缝"):
        isl_layout({"d_mm": 0.9, "s_mm": 1.0}, 0.4e-3, 0.508e-3)


def test_vivaldi_layout_guard_mouth_standoff():
    """守卫面：口面越出板缘 MUR 净距渲染期拒绝。"""
    with pytest.raises(ValueError, match="净距"):
        vivaldi_layout({"l_mm": 130.0})


def test_anchors_replay_nominals():
    """锚树回放：knowledge/anchors.yaml 两锚值按内核链复算逐位对拍。"""
    import yaml

    data = yaml.safe_load(
        (REPO / "knowledge" / "anchors.yaml").read_text(encoding="utf-8"))
    by_id = {a["anchor_id"]: a for a in data["anchors"]}
    isl = by_id["isl_shielded.eps_eff.closedform-v1"]
    qs = suspended_ms_qs(TEMPLATE_NOMINAL["isl_shielded"]["w_mm"],
                         TEMPLATE_NOMINAL["isl_shielded"]["g_air_mm"],
                         0.508, 3.66,
                         TEMPLATE_NOMINAL["isl_shielded"]["h_top_mm"])
    assert qs["eps_eff"] == pytest.approx(float(isl["value"]), abs=1e-4)
    viv = by_id["vivaldi_tsa.f_low_ghz.closedform-v1"]
    d = vivaldi_tsa_design(
        float(viv["value"]), TEMPLATE_NOMINAL["vivaldi_tsa"]["w_throat_mm"],
        TEMPLATE_NOMINAL["vivaldi_tsa"]["l_mm"])
    assert d["f_low_ghz"] == pytest.approx(float(viv["value"]), abs=1e-6)
    assert render_script("isl_shielded", {}, (2.25, 2.75),
                         mesh_resolution_mm=0.4)
    assert render_script("vivaldi_tsa", {}, (9.75, 10.25),
                         mesh_resolution_mm=0.4)
