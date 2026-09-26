"""SIW 族第二成员=MSL 锥形过渡+SIW 直段（df6 A2，2026-09-24）离线审计测试。

权威口径：runs/df6_a2siwmsl/criteria.md（Deslandes-Wu 两段论/文献互证账/
G3' 预声明门/预算）。覆盖（#212 制度化 + #118 数值裁判 + #231 注册四件套）：
  1) 设计式与单源链互洽：layout 派生量（w_eff/β/Z_PV/w50/w_end/锥装配）与
     core 单源逐位对账；锥长候选的对称双锥级联实测（criteria §1.1 勘误账）；
  2) 渲染离线 exec 审计：藩篱（数量/心距/贯通/末孔缘不越板缘）、顶层金属
     三段连通（馈线-锥-板同属性+SEAM 搭接）、端口面贴域界 PML（#174）、
     #347 间距断言、port_beta.csv 契约（8 列）、激励契约、孔间缝内部线
     （#311）、#349/#152 网格地板；
  3) 注册四件套：TEMPLATE_META/NOMINAL 同对象、meta.yaml、spec（render/
     fake/synthesizer）、槽线族字典尾契约（#247）、EXPECTED_TEMPLATES 45；
  4) fake 派发：对称双锥带内 |S11| 过预声明门、参数驱动响应（锥长 λg/4
     变体劣化）、SIW 段截止下衰减；
  5) siw 缺省渲染字节钉保持（本批零语义改动的自证）。
秒级零仿真（FDTD.Run 之前截断 exec）。
"""

from __future__ import annotations

import hashlib
import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.calculators import (
    siw_beta_rad_m,
    siw_effective_width_mm,
)

C0 = 299792458.0
ER = 3.66
H = 0.508
NOM = {"w_mm": 12.1317, "d_mm": 0.6, "s_mm": 1.0,
       "taper_len_mm": 10.5121, "siw_len_mm": 63.0724}
BAND = (9.75, 10.25)


# ─── 1) 设计式与单源链互洽（#118/#300：数值裁判，不凑推导）───────────────────

def _layout(params=None, base_m=0.4e-3, band=BAND, h_mm=H):
    from rfauto.adapters.openems_templates import msl_siw_taper_layout

    resolved = dict(NOM)
    if params:
        resolved.update(params)
    return msl_siw_taper_layout(resolved, band, base_m, h_mm * 1e-3)


def test_layout_derived_values_match_single_source_chain():
    """layout 派生量与 core/calculators + inverse_width 单源链逐位互洽。"""
    from rfauto.core.synthesis import Stackup, inverse_width

    lay = _layout()
    weff = siw_effective_width_mm(NOM["w_mm"], NOM["d_mm"], NOM["s_mm"])
    beta, fc10 = siw_beta_rad_m(weff, ER, 10.0)
    assert lay["weff"] * 1e3 == pytest.approx(weff, rel=1e-12)
    assert lay["beta"] == pytest.approx(beta, rel=1e-12)
    assert lay["fc10"] == pytest.approx(fc10, rel=1e-12)
    # λg 名义锚（criteria §1）
    assert 2 * math.pi / beta * 1e3 == pytest.approx(21.0241, abs=1e-3)
    # Z_PV = 2b·Z_TE/w_eff（电压基连续性，_siw_r_port_ohm 同链）
    z_te = 2.0 * math.pi * 10e9 * 1.25663706212e-6 / beta
    assert lay["z_pv"] == pytest.approx(2 * H * 1e-3 * z_te / (weff * 1e-3),
                                        rel=1e-12)
    assert lay["z_pv"] == pytest.approx(22.8393, abs=1e-3)  # criteria §1 钉值
    # w50/w_end = inverse_width（skrf HJ 单源；inverse_width 返回 mm→米）
    stackup = Stackup(name="audit", epsilon_r=ER, thickness_mm=H,
                      loss_tangent=0.0037)
    w50_mm, z50, st50 = inverse_width(50.0, 10.0, stackup)
    w_end_mm, zend, stend = inverse_width(lay["z_pv"], 10.0, stackup)
    assert st50 == "ok" and stend == "ok"
    assert lay["w50"] * 1e3 == pytest.approx(w50_mm, rel=1e-12)
    assert lay["w_end"] * 1e3 == pytest.approx(w_end_mm, rel=1e-12)
    assert z50 == pytest.approx(50.0, abs=0.5)
    assert zend == pytest.approx(lay["z_pv"], abs=0.5)
    assert w50_mm == pytest.approx(1.1198, abs=1e-3)   # criteria §1 钉值
    assert w_end_mm == pytest.approx(3.361, abs=1e-3)
    # 几何装配恒等式：dom_y = y_plate + taper + feed；dom_x = w/2 + w_eff/2
    assert lay["y_feed_in"] == pytest.approx(lay["y_plate"]
                                             + lay["taper_len"], rel=1e-15)
    assert lay["dom_y"] == pytest.approx(lay["y_feed_in"]
                                         + lay["feed_len"], rel=1e-15)
    assert lay["dom_x"] == pytest.approx(NOM["w_mm"] * 1e-3 / 2
                                         + weff * 1e-3 / 2, rel=1e-15)


def test_taper_length_candidates_double_taper_cascade_pinned():
    """criteria §1.1 勘误账钉：对称双锥级联实测三档锥长带内 |S11|。

    λg/4 变体达不到 15dB 门（文献口径在本阻抗比下复现失败，如实收档）；
    λg/2 缺省过门。数值裁判=fake 内核（对称双锥全路径）。
    """
    from rfauto.adapters.fake_adapter import _msl_siw_taper_sparams

    f = np.linspace(9.0, 11.0, 201)
    results = {}
    for L_mm, tag in ((5.256, "lg4"), (10.5121, "lg2")):
        s = _msl_siw_taper_sparams(
            f, weff_mm=11.7527526, siw_len_mm=NOM["siw_len_mm"],
            taper_len_mm=L_mm, w50_mm=1.1198152, w_end_mm=3.3609703,
            h_mm=H, n_steps=16)
        s11_db = 20.0 * np.log10(np.maximum(np.abs(s[:, 0, 0]), 1e-12))
        results[tag] = float(np.max(s11_db))
    assert results["lg4"] > -15.0       # λg/4 变体不达标（收档依据）
    assert results["lg2"] <= -15.0      # 缺省 λg/2 过预声明门（fake 口径）
    assert results["lg2"] == pytest.approx(-16.1, abs=0.7)  # criteria 钉值
    assert results["lg4"] == pytest.approx(-7.8, abs=0.7)


# ─── 2) 渲染离线 exec 审计（#212）────────────────────────────────────────────

def _load(params=None, mesh_mm=0.4, band=BAND):
    from rfauto.adapters.openems_templates import render_script

    resolved = dict(NOM)
    if params:
        resolved.update(params)
    text = render_script("msl_siw_taper", resolved, band,
                         mesh_resolution_mm=mesh_mm)
    cut = text.index("FDTD.Run(")
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_mslsiw_audit.py")}
    exec(compile(text[:cut], "mslsiw_audit", "exec"), scope)
    return text, scope


def test_mslsiw_boundaries_ports_and_reference():
    """y 轴 PML_8 + x 侧 MUR + z 底 PEC/顶 MUR（MSL 区微带环境）；CalcPort
    参考=50（MSL 50Ω 基主口径）；port_beta.csv 8 列契约。"""
    text, _scope = _load()
    assert ('SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"])'
            in text)
    assert "ref_impedance=50" in text
    assert text.count('MSLPort(CSX, port_nr=1, metal_prop=msl_top') == 1
    assert text.count('MSLPort(CSX, port_nr=2, metal_prop=msl_top') == 1
    assert text.count("FDTD.AddLumpedPort(") == 0   # 端口全 MSLPort 线基
    assert '"re_zl1_ohm", "im_zl1_ohm", "re_zl2_ohm", "im_zl2_ohm", ' \
           '"plane_dist_m"' in text
    # #347 断言在渲染脚本内（FeedShift/MeasPlaneShift 间距）
    assert "3.9 * NEAR" in text


def test_mslsiw_via_fence_geometry_offline_exec():
    """藩篱：两列等长、心距精确 s、柱贯通 0..h、末孔缘不越板缘（v2 口径）。"""
    _text, scope = _load()
    csx = scope["CSX"]
    by_name = {}
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        by_name[str(prop.GetName())] = prop
    via = by_name["siw_via"]
    cyls = list(via.GetAllPrimitives())
    assert len(cyls) == 2 * (2 * 31 + 1)     # 63 孔/列 ×2 列（k_half=31）
    s = NOM["s_mm"] * 1e-3
    ys = sorted({round(float(c.GetStart()[1]), 12) for c in cyls})
    assert len(ys) == 63
    assert all(b - a == pytest.approx(s, abs=1e-12)
               for a, b in pairwise(ys))
    for c in cyls:
        assert float(c.GetStart()[2]) == 0.0
        assert float(c.GetStop()[2]) == float(scope["H_SUB"])
        assert abs(abs(float(c.GetStart()[0])) - NOM["w_mm"] * 1e-3 / 2) < 1e-12
    # 末孔缘 < 板缘（藩篱止于板缘，siw v2 口径）
    assert max(ys) + NOM["d_mm"] * 1e-3 / 2 < scope["Y_PLATE"]


def test_mslsiw_top_metal_three_segments_connected_offline_exec():
    """顶层金属单属性三段（馈线×2/锥多边形×2/顶壁板）+ MSLPort 自画馈线；
    锥多边形宽端（含 SEAM 搭接）与顶壁板 y 区间相交（连通，#310 预防）。"""
    _text, scope = _load()
    csx = scope["CSX"]
    msl_top = None
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        if str(prop.GetName()) == "msl_top":
            msl_top = prop
    assert msl_top is not None
    polys = []
    boxes = []
    for prim in msl_top.GetAllPrimitives():
        bb = np.asarray(prim.GetBoundBox(), dtype=float)
        (polys if not hasattr(prim, "GetStart") else boxes).append(bb)
    # 锥=AddPolygon 梯形×2（无 GetStart 的原语走 GetBoundBox）
    assert len(polys) == 2 and len(boxes) >= 3
    y_plate = float(scope["Y_PLATE"])
    seam = float(scope["SEAM"])
    for bb in polys:
        # 锥内端（含 SEAM 搭接）越入板区 |y|<Y_PLATE
        inner = min(abs(bb[0][1]), abs(bb[1][1]))
        assert inner < y_plate
        assert inner == pytest.approx(y_plate - seam, rel=1e-9)
    # 顶壁板：全宽 × |y|≤Y_PLATE 零厚贴 z=H_SUB
    plate = [bb for bb in boxes
             if abs(bb[1][0] - bb[0][0] - 2 * scope["DOM_X"]) < 1e-12]
    assert plate and abs(plate[0][1][1] - plate[0][0][1]
                         - 2 * y_plate) < 1e-12


def test_mslsiw_ports_on_domain_edge_and_excitation_contract():
    """端口面=±DOM_Y=域界逐位（#174）；激励仅 port1；FeedShift/MeasPlaneShift
    与 layout 单源一致；测量面距=2·(DOM_Y−FEED_LEN/3)。"""
    _text, scope = _load()
    p1, p2 = scope["_port1"], scope["_port2"]
    dom_y = float(scope["DOM_Y"])
    for port in (p1, p2):
        start = np.asarray(port.start, dtype=float)
        assert abs(abs(start[1]) - dom_y) <= 1e-12   # 面贴域界=PML 面
        assert abs(float(port.measplane_shift)
                   - float(scope["FEED_LEN"]) / 3.0) <= 1e-15
    # 激励契约：Excitation×1（port2 excite=0 仅探针+端接）
    csx = scope["CSX"]
    n_excite = sum(
        1 for i in range(csx.GetQtyProperties())
        if str(csx.GetProperty(i).GetTypeString()) == "Excitation")
    assert n_excite == 1


def test_mslsiw_via_gap_interior_lines_offline_exec():
    """#311 类比：相邻过孔缝隙内 CSXCAD 实测网格线 ≥1（缝缘线不计）。"""
    _text, scope = _load()
    ys = np.asarray(scope["mesh"].GetLines("y"), dtype=float)
    s = NOM["s_mm"] * 1e-3
    d = NOM["d_mm"] * 1e-3
    for k in (-5, 0, 5):
        lo, hi = k * s + d / 2, (k + 1) * s - d / 2
        inside = ys[(ys > lo + 1e-12) & (ys < hi - 1e-12)]
        assert inside.size >= 1, f"过孔缝隙 [{lo}, {hi}] 内部线 = 0"


def test_mslsiw_mesh_guard_floors_and_domain_literal():
    """#349/#152：全轴最小间距 >1µm；DOM_X/DOM_Y 字面=layout 单源；域界=
    网格界（#212 审计④；z 向下界=−AIR_TOP、上界=H_SUB+AIR_TOP）。"""
    text, scope = _load()
    lay = _layout()
    assert scope["DOM_X"] == pytest.approx(lay["dom_x"], abs=1e-15)
    assert scope["DOM_Y"] == pytest.approx(lay["dom_y"], abs=1e-15)
    assert f"DOM_X = {lay['dom_x']!r}" in text
    assert f"DOM_Y = {lay['dom_y']!r}" in text
    for ax in ("x", "y", "z"):
        ls = np.asarray(scope["mesh"].GetLines(ax), dtype=float)
        assert bool(np.all(np.diff(ls) > 1e-6))
    dom = {"x": lay["dom_x"], "y": lay["dom_y"]}
    for ax in ("x", "y"):
        ls = np.asarray(scope["mesh"].GetLines(ax), dtype=float)
        assert ls.min() == pytest.approx(-dom[ax], abs=1e-9)
        assert ls.max() == pytest.approx(dom[ax], abs=1e-9)


def test_mslsiw_min_line_gaps_match_siw_anchor_structure():
    """终网格最小格逐轴与 siw 锚同构（x 50µm/y 40µm/z 127µm，audit 档）——
    引擎 dt 同源论证（criteria §6 预算）的实测前提。"""
    _text, scope = _load()
    for ax, floor_um in (("x", 50.0), ("y", 40.0), ("z", 127.0)):
        ls = np.asarray(scope["mesh"].GetLines(ax), dtype=float)
        gap_um = float(np.diff(ls).min()) * 1e6
        assert gap_um >= floor_um - 1e-6, f"{ax} 最小格 {gap_um}µm < {floor_um}µm"


# ─── 2b) 负路径（守卫显式拒绝）───────────────────────────────────────────────

def test_mslsiw_negative_paths():
    """粗网格/孔间缝/设计规则/带低频截止/Z_PV 出设计域——全部渲染期拒绝。"""

    # 过孔欠分辨：BASE=5mm（NEAR=1.25 > d/4）
    with pytest.raises(ValueError, match="4·NEAR"):
        _layout(base_m=5.0e-3)
    # 孔间缝：s−d=0.15 ≤ NEAR（BASE=0.7）
    with pytest.raises(ValueError, match="孔间缝"):
        _layout({"d_mm": 0.85}, base_m=0.7e-3)
    # 设计规则 s>2d（core 单源复用）
    with pytest.raises(ValueError, match="2·d"):
        _layout({"s_mm": 2.5})
    # 带心低于 fc10（band (5,7)：带心 6<fc10=6.667）——传播区守卫；注意
    # 无"带低频"臂：锚带 (6,13) 有意含 6.2GHz 截止下频点（G2 滚降门）
    with pytest.raises(ValueError, match="低于 TE10 截止"):
        _layout(band=(5.0, 7.0))
    # Z_PV 出设计域（h=5mm → Z_PV=224Ω ≥ 50）
    with pytest.raises(ValueError, match="设计域"):
        _layout(h_mm=5.0)
    # 直调缺 layout 注入（#283 渲染期守卫纪律）
    with pytest.raises(ValueError, match="_msl_siw_taper_layout"):
        from rfauto.adapters.openems_templates import _msl_siw_taper_lines

        _msl_siw_taper_lines({})


# ─── 3) 注册四件套（#231/#304）───────────────────────────────────────────────

def test_mslsiw_registration_quartet():
    import yaml

    from rfauto.adapters import openems_templates as ot
    from rfauto.models.template_specs import TEMPLATE_SPECS

    assert ot.TEMPLATE_META["msl_siw_taper"] is ot.MSL_SIW_TAPER_META
    assert (ot.TEMPLATE_NOMINAL["msl_siw_taper"]
            is ot.MSL_SIW_TAPER_NOMINAL)
    assert ot.TEMPLATE_META["msl_siw_taper"]["params"] == [
        "w_mm", "d_mm", "s_mm", "taper_len_mm", "siw_len_mm"]
    assert ot.TEMPLATE_META["msl_siw_taper"]["n_ports"] == 2
    assert ot._TEMPLATE_PORT_AXES["msl_siw_taper"] == ("y",)
    assert ot._TEMPLATE_RADIATOR["msl_siw_taper"] is False
    # 槽线族字典尾契约（#247）
    from rfauto.adapters.openems_templates import SLOTLINE_FAMILY_TEMPLATES

    # 注册序尾契约（df6 DP-10 起尾 4=§MS_METASURFACE 四件，槽线族退居
    # 尾 8..4；df7 C10b 起 coil_nfc 居尾，df7 C10d 起 mmwave_series_array
    # 居尾 1、coil_nfc 退居尾 2、ms 四件退居尾 6..3——次序仍钉，防中间插注漂移）
    assert list(ot.TEMPLATE_META)[-10:-6] == list(SLOTLINE_FAMILY_TEMPLATES)
    assert list(ot.TEMPLATE_NOMINAL)[-10:-6] == list(SLOTLINE_FAMILY_TEMPLATES)
    assert list(ot.TEMPLATE_META)[-6:-2] == ["ms_patch", "ms_cross",
                                             "ms_jcross", "ms_array_NxN"]
    assert list(ot.TEMPLATE_NOMINAL)[-6:-2] == ["ms_patch", "ms_cross",
                                                "ms_jcross", "ms_array_NxN"]
    assert list(ot.TEMPLATE_META)[-2] == "coil_nfc"
    assert list(ot.TEMPLATE_NOMINAL)[-2] == "coil_nfc"
    assert list(ot.TEMPLATE_META)[-1] == "mmwave_series_array"
    assert list(ot.TEMPLATE_NOMINAL)[-1] == "mmwave_series_array"
    # docs meta.yaml
    meta_path = REPO / "docs" / "templates" / "msl_siw_taper" / "meta.yaml"
    assert meta_path.exists()
    data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    assert set(data["params"]) == set(
        ot.TEMPLATE_META["msl_siw_taper"]["params"])
    for key, val in ot.TEMPLATE_NOMINAL["msl_siw_taper"].items():
        assert float(data["nominal_params"][key]) == pytest.approx(val)
    # spec 注册与组件齐备
    spec = TEMPLATE_SPECS.get("msl_siw_taper")
    assert spec.physics_roles == {"w_mm": "line_width_mm",
                                  "siw_len_mm": "line_length_mm"}
    assert callable(TEMPLATE_SPECS.component("msl_siw_taper", "fake_model"))
    assert callable(TEMPLATE_SPECS.component("msl_siw_taper", "synthesizer"))
    assert callable(TEMPLATE_SPECS.component("msl_siw_taper",
                                             "render_script"))
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

    assert "msl_siw_taper" in EXPECTED_TEMPLATES
    # 49→53（df6_dp4p3 EEP 双模板 / df7 C10d mmwave_series_array）：四件套钉
    # 随全局实测推进。
    assert len(EXPECTED_TEMPLATES) == 53


def test_mslsiw_synthesizer_roundtrip():
    """synthesizer 产物与 TEMPLATE_NOMINAL 逐键一致（同链闭环）。"""
    from rfauto.core.synthesis import synthesize_msl_siw_taper_model

    result = synthesize_msl_siw_taper_model()
    assert result.model == "msl_siw_taper"
    for key, val in NOM.items():
        assert result.params[key] == pytest.approx(val)
    assert result.recipe_draft["model"] == "msl_siw_taper"
    assert result.params["taper_len_mm"] == pytest.approx(10.5121)
    # 过孔规则违规显式报错（越界不外推）
    with pytest.raises(ValueError):
        synthesize_msl_siw_taper_model(s_mm=2.5)


# ─── 4) fake 派发（参数驱动真实响应）─────────────────────────────────────────

def test_fake_mslsiw_dispatch_band_gate_and_param_response():
    """带内 |S11| 过预声明门（fake 口径）；锥长参数驱动响应；带内无源性。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="msl_siw_taper", n_ports=2,
                     freq_ghz=(9.0, 11.0, 201), f0_ghz=10.0)
    ad.connect({})
    ad.set_variables({k: f"{v}mm" for k, v in NOM.items()})
    ad.solve("main_setup")
    net = ad.get_sparams()
    s11 = np.abs(net.s[:, 0, 0])
    s21 = np.abs(net.s[:, 1, 0])
    assert 20 * math.log10(s11.max()) <= -15.0       # G3' RL 臂（fake 口径）
    assert 20 * math.log10(s21.max()) >= -1.5        # G3' 传输臂（fake 口径）
    assert float(np.max(s11 ** 2 + s21 ** 2)) <= 1.0 + 1e-9   # 无源性
    # 锥长变体（λg/4）→ 带内 |S11| 劣化（参数驱动真实响应）
    ad.set_variables({**{k: f"{v}mm" for k, v in NOM.items()},
                      "taper_len_mm": "5.256mm"})
    ad.solve("main_setup")
    s11_b = np.abs(ad.get_sparams().s[:, 0, 0])
    assert 20 * math.log10(s11_b.max()) > 20 * math.log10(s11.max())


def test_fake_mslsiw_siw_segment_cutoff_rolloff():
    """SIW 段在 fc 以下倏逝（γ 分支 α>0）：G2 滚降口径的 fake 侧预演。"""
    from rfauto.adapters.fake_adapter import _msl_siw_taper_sparams

    freqs = np.array([6.2, 10.0])
    s = _msl_siw_taper_sparams(
        freqs, weff_mm=11.7527526, siw_len_mm=NOM["siw_len_mm"],
        taper_len_mm=NOM["taper_len_mm"], w50_mm=1.1198152,
        w_end_mm=3.3609703, h_mm=H, n_steps=16)
    assert abs(s[0, 1, 0]) < abs(s[1, 1, 0])          # 6.2GHz 强衰减
    rolloff_db = (20 * math.log10(abs(s[1, 1, 0]))
                  - 20 * math.log10(abs(s[0, 1, 0])))
    assert rolloff_db >= 15.0                          # G2 门量级预演


# ─── 5) siw 缺省渲染字节钉保持（本批零语义改动自证）─────────────────────────

def test_siw_v1_default_render_byte_pin_preserved():
    """df6 A2 批触过 openems_templates.py——siw 缺省渲染 sha256 必须仍等于
    test_siw_template 的字节钉（v2_criteria.md §5.7）。"""
    from rfauto.adapters.openems_templates import render_script
    from tests.unit.test_siw_template import (
        _V1_RENDER_SHA256,
    )
    from tests.unit.test_siw_template import (
        BAND as SIW_BAND,
    )
    from tests.unit.test_siw_template import (
        NOM as SIW_NOMINAL,
    )

    text = render_script("siw", dict(SIW_NOMINAL), SIW_BAND,
                         mesh_resolution_mm=0.4)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == _V1_RENDER_SHA256
