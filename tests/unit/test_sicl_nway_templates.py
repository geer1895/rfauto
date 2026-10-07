"""TA 批第二批两模板测试：TA-3 sicl 基片集成同轴线 + TA-4 nway_wilkinson
树形功分器（2026-10-02，#212 离线审计制度化；test_schiffman_qwt_templates
同构）。

零仿真（exec 截断于 FDTD.Run 之前，秒级）：渲染→exec 几何段→CSXCAD 实测
矩形同轴腔拓扑（条带-地板 DC 隔离/过孔墙贯通/条带中面落格）/树形功分器
单网络零交叉 + 共形闭式/HJ 设计链综合反解自洽（design_params()==
TEMPLATE_NOMINAL 逐键 rtol 1e-9）+ 内核闭式锚（Z0 回代/tree 阻抗级恒等
式）+ 渲染守卫（板内越界/#347 测量面分离/过孔网格欠分辨/n_way 域）+
注册五件套 + docs meta.yaml 一致性。

方案锚：研究扩充 round15 §二·2 TA-3/TA-4——
「内核就绪缺模板」件；闭式单源 core（sicl_line.sicl_closed_form /
synthesize_nway_wilkinson tree 分支），本模板层零数值产出（铁律 7/#1c）。
近似级别如实登记见两 META smoke_note。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import (
    _NWAY_PORT_ROTATION_TEMPLATES,
    NWAY_WILKINSON_NOMINAL,
    SICL_NOMINAL,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    _nway_layout,
    geometry_spec,
    nway_wilkinson_design_params,
    render_script,
    sicl_design_params,
    sicl_layout,
    template_meta,
)
from tests.unit import _geometry_audit_helpers as gh
from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

SICL = dict(SICL_NOMINAL)
NWAY = dict(NWAY_WILKINSON_NOMINAL)
BAND = (2.25, 2.75)


# ─── 1) 设计链综合反解自洽（#1c：名义值禁手算捷径）──────────────────────────────

class TestDesignChainSelfConsistent:
    def test_sicl_design_params_reproduce_nominal(self):
        """sicl_design_params() 缺省实参重算 == TEMPLATE_NOMINAL 几何键逐键
        （材料键 h_mm/er/tan_d 为 RO4350B 双板口径常量，slotline/siw 家族
        同构——非设计链产出，另钉）。"""
        design = sicl_design_params()
        assert set(design) == {"w_mm", "a_mm", "d_mm", "s_mm", "line_len_mm"}
        for key in sorted(design):
            assert design[key] == pytest.approx(SICL[key], rel=1e-9), key
        assert SICL["h_mm"] == pytest.approx(2 * 0.508, abs=1e-12)
        assert SICL["er"] == pytest.approx(3.66, rel=1e-12)
        assert SICL["tan_d"] == pytest.approx(0.0037, rel=1e-12)

    def test_nway_design_params_reproduce_nominal(self):
        """nway_wilkinson_design_params() 缺省实参重算 == TEMPLATE_NOMINAL。"""
        design = nway_wilkinson_design_params()
        assert set(design) == set(NWAY)
        for key in sorted(NWAY):
            assert design[key] == pytest.approx(NWAY[key], rel=1e-9), key

    def test_nominal_literal_table_matches_registry(self):
        """模块 NOMINAL 字面量与注册表同对象（单一事实源，#247 口径）。"""
        assert TEMPLATE_NOMINAL["sicl"] is SICL_NOMINAL
        assert TEMPLATE_NOMINAL["nway_wilkinson"] is NWAY_WILKINSON_NOMINAL


# ─── 2) 内核闭式锚（离线裁判恒等式）───────────────────────────────────────────

class TestKernelAnchors:
    def test_sicl_nominal_in_referee_band_and_z0(self):
        """名义几何落内核 FD 裁判声明域（in_referee_band=True）且 Z0 回代
        50Ω（4 位舍入带 ±0.005Ω，#1c 反解链 1e-4 相对门）。"""
        from rfauto.core.sicl_line import sicl_closed_form

        res = sicl_closed_form(SICL["w_mm"], SICL["a_mm"], SICL["h_mm"],
                               0.0, SICL["er"], None)
        assert res.in_referee_band is True
        assert res.z0_ohm == pytest.approx(50.0, abs=5e-3)
        assert res.eps_eff == pytest.approx(SICL["er"], rel=1e-12)

    def test_sicl_inversion_round_trip_exact(self):
        """反解链恒等：未舍入 w 对 Z0=50 回代 ≤1e-9 相对（brentq 质量门）。"""
        from scipy.optimize import brentq

        from rfauto.core.sicl_line import sicl_z0

        a_mm = SICL["a_mm"]

        def f(w: float) -> float:
            return (sicl_z0(w, a_mm, SICL["h_mm"], 0.0, SICL["er"], None)
                    - 50.0)

        w = brentq(f, 1e-3 * SICL["h_mm"], 0.99 * SICL["h_mm"], xtol=1e-12)
        assert abs(f(w)) <= 1e-9 * 50.0
        assert round(w, 4) == SICL["w_mm"]

    def test_nway_tree_impedance_identities(self):
        """tree 阻抗级恒等式（内核单源）：臂=√2·Z0、隔离 R=2·Z0、2 级 6 臂
        3 电阻；λ/4 臂端接 Z0 的输入阻抗=2·Z0（N=2 并联回 Z0，T 结匹配）。"""
        from rfauto.core.synthesis import synthesize_nway_wilkinson

        d = synthesize_nway_wilkinson(4, 50.0, topology="tree")
        p = d["params"]
        # 内核 params 对 arm_z 落 4 位舍入（70.7107）——锚按同精度钉（消费
        # 面=design chain 直接吃 params 发布值，单一事实源）
        assert p["arm_z_ohm"] == pytest.approx(
            round(50.0 * math.sqrt(2.0), 4), abs=1e-9)
        assert p["isolation_r_ohm"] == pytest.approx(100.0, rel=1e-9)
        assert p["stages"] == 2 and p["arm_count"] == 6
        assert p["n_isolation_r"] == 3
        # λ/4 臂（Z_t=√2·Z0）端接 Z0：Z_in=Z_t²/Z0=2·Z0（N=2 并联=Z0 匹配）
        z_t = 50.0 * math.sqrt(2.0)
        z_in = z_t * z_t / 50.0
        assert z_in == pytest.approx(100.0, rel=1e-9)
        assert (z_in / 2.0) == pytest.approx(50.0, rel=1e-9)

    def test_nway_arm_len_is_quarter_wave(self):
        """臂长=λ/4 物理长（εeff 精算链回代；HJ 闭式单源）——4 位舍入
        宽度档回代（设计链以未舍入 w 精算 εeff，舍入差 ~2e-5mm，rel 1e-5
        门如实登记）。"""
        from rfauto.core.synthesis import Stackup, forward_z0

        sub = Stackup.from_materials_yaml("rogers4350b_h0.508")
        _, eps_eff = forward_z0(NWAY["w_arm_mm"], 2.5, sub)
        lam4 = 299792458.0 / (4.0 * 2.5e9 * math.sqrt(eps_eff)) * 1e3
        assert NWAY["arm_len_mm"] == pytest.approx(lam4, rel=1e-5)


# ─── 3) #212 离线几何审计（CSXCAD 实测，零仿真）──────────────────────────────

class TestGeometryAudit:
    def test_sicl_cavity_topology_and_dc_isolation(self):
        """矩形同轴腔拓扑：条带网络（双端口）与地板/过孔墙网络 DC 隔离
        （无接地柱触条带=器件定义性质）；域=DOM_X/DOM_Y 矩形。"""
        scope, prims = gh.load_geometry("sicl")
        ports = gh.port_objects(scope)
        assert sorted(ports) == [1, 2]
        conductors, labels = gh.conductor_labels(prims)
        comps = {n: gh.containing_labels(gh.port_feed_point(p), conductors,
                                         labels)
                 for n, p in ports.items()}
        assert comps[1] and comps[2], "端口馈电点悬空"
        assert comps[1] & comps[2], "双端口未导通（条带断链）"
        # 条带网络 ≠ 地板/过孔墙网络（DC 隔离；两分量数恰 2）
        assert len(set(labels)) == 2, (
            f"sicl 导体分量数 {len(set(labels))}（预期条带+地板墙 2）")
        strip_comp = comps[1]
        ground_prims = [p for p, lb in zip(conductors, labels, strict=True)
                        if lb not in strip_comp]
        assert any(p.prop == "sicl_via" for p in ground_prims), \
            "过孔墙缺失/不与地板导通"
        assert any(p.prop == "sicl_plates" for p in ground_prims), \
            "上下地板缺失"

    def test_sicl_strip_midplane_and_via_span(self):
        """条带在中面 z=H_SUB/2（StripLinePort height=b/2 前提）；过孔墙
        贯通全域（首末孔越 ±条带端，siw v1 藩篱口径）。"""
        _scope, prims = gh.load_geometry("sicl")
        strips = [p for p in prims if p.prop == "sicl_strip"]
        assert len(strips) >= 1
        h = float(SICL["h_mm"]) * 1e-3
        assert strips[0].lo[2] == pytest.approx(h / 2.0, abs=1e-12)
        vias = [p for p in prims if p.prop == "sicl_via"]
        assert len(vias) >= 2 * 40, "过孔墙数量异常（≥2×40 颗）"
        for p in vias:
            assert p.lo[2] == pytest.approx(0.0, abs=1e-12)
            assert p.hi[2] == pytest.approx(h, rel=1e-9)
        ys = [p.lo[1] for p in vias] + [p.hi[1] for p in vias]
        y0 = float(SICL["line_len_mm"]) * 1e-3 / -2.0
        assert min(ys) <= y0 and max(ys) >= -y0, "藩篱未覆盖条带全段"

    def test_sicl_rect_domain_literal(self):
        """矩形域 DOM_X/DOM_Y 字面注入（layout 单源一致；BOARD 字面量不
        适用口径）。"""
        scope, _ = gh.load_geometry("sicl")
        lay = sicl_layout(dict(SICL), BAND, 0.4e-3,
                          float(SICL["h_mm"]) * 1e-3)
        assert float(scope["DOM_X"]) == pytest.approx(lay["dom_x"], rel=1e-12)
        assert float(scope["DOM_Y"]) == pytest.approx(lay["dom_y"], rel=1e-12)

    def test_nway_single_network_and_resistor_bridges(self):
        """全 5 端口单导体网络（树形级联经结点/电阻导通）；3 支隔离电阻
        盒各跨接对应臂对（端面 y=臂长端）。"""
        scope, prims = gh.load_geometry("nway_wilkinson")
        ports = gh.port_objects(scope)
        assert sorted(ports) == [1, 2, 3, 4, 5]
        conductors, labels = gh.conductor_labels(prims)
        comps = {n: gh.containing_labels(gh.port_feed_point(p), conductors,
                                         labels)
                 for n, p in ports.items()}
        all_comp = set().union(*comps.values())
        assert len(all_comp) == 1, (
            f"树形网络分裂：{[sorted(c) for c in comps.values()]}")
        res = [p for p in prims if p.kind == "LumpedElement"]
        assert len(res) == 3, f"隔离电阻支数 {len(res)}（预期 3）"
        lay = _nway_layout(dict(NWAY))
        y_e1 = lay["y_e1"]
        y_e2 = lay["y_e2"]
        by_y = sorted(r.lo[1] for r in res)
        assert by_y[0] == pytest.approx(y_e1 - lay["wa"] / 2.0, abs=1e-12)
        assert by_y[1] == pytest.approx(y_e2 - lay["wa"] / 2.0, abs=1e-12)
        assert by_y[2] == pytest.approx(y_e2 - lay["wa"] / 2.0, abs=1e-12)

    def test_nway_arm_sections_match_nominal(self):
        """6 支 λ/4 臂宽度=名义 w_arm（一级 2 + 二级 4）；50Ω 支线/输出馈
        线宽度=名义 w_feed。"""
        _scope, prims = gh.load_geometry("nway_wilkinson")
        wa = float(NWAY["w_arm_mm"]) * 1e-3
        wf = float(NWAY["w_feed_mm"]) * 1e-3
        arms = [p for p in prims if p.kind == "Metal"
                and p.prop == "nway_wilkinson"
                and p.extent[1] > 1e-12
                and abs(p.extent[0] - wa) <= 1e-12
                and abs(p.extent[1] - float(NWAY["arm_len_mm"]) * 1e-3)
                <= 1e-12]
        assert len(arms) == 6, f"λ/4 臂支数 {len(arms)}（预期 6）"
        feeds = [p for p in prims if p.kind == "Metal"
                 and p.prop == "nway_wilkinson"
                 and abs(p.extent[0] - wf) <= 1e-12]
        assert len(feeds) >= 2, "50Ω 支线缺失"

    def test_geometry_spec_port_counts(self):
        """geometry_spec 端口数=meta n_ports（sicl=2、nway=5）。"""
        for t, n in (("sicl", 2), ("nway_wilkinson", 5)):
            spec = geometry_spec(t, dict(TEMPLATE_NOMINAL[t]))
            assert len(spec["ports"]) == n == int(TEMPLATE_META[t]["n_ports"])


# ─── 4) 渲染守卫（渲染期显式抛错）─────────────────────────────────────────────

class TestRenderGuards:
    def test_sicl_via_resolution_rejected(self):
        """过孔直径 <4·NEAR（粗网格档 base=3mm）拒渲染。"""
        with pytest.raises(ValueError, match="网格欠分辨"):
            render_script("sicl", dict(SICL), BAND, mesh_resolution_mm=3.0)

    def test_sicl_via_gap_internal_line_rejected(self):
        """孔间缝 s−d ≤ NEAR（#311 先例口径）拒渲染——s 压到 0.7（缝
        0.1mm=0.4 档 NEAR，恰等拒绝）。"""
        bad = dict(SICL, s_mm=0.7)
        with pytest.raises(ValueError, match="孔间缝"):
            render_script("sicl", bad, BAND, mesh_resolution_mm=0.4)

    def test_nway_cascade_overflow_rejected(self):
        """二级叉末端越板边余量拒渲染（y_t2+arm_len ≥ BOARD−4·NEAR）。"""
        bad = dict(NWAY, arm_len_mm=72.0)
        with pytest.raises(ValueError, match="越板边余量"):
            render_script("nway_wilkinson", bad, BAND,
                          mesh_resolution_mm=0.4)

    def test_nway_probe_excitation_separation_rejected(self):
        """#347 族：输入段测量面-激励盒分离守卫——粗网格档（base=2mm →
        20·NEAR=10mm > 输入段测量面 5mm）必须拒渲染。"""
        with pytest.raises(ValueError, match="FeedShift"):
            render_script("nway_wilkinson", dict(NWAY), BAND,
                          mesh_resolution_mm=2.0)

    def test_nway_inner_feed_clearance_rejected(self):
        """内对输出馈线边距 <3·h_sub（G2 过大）拒渲染。"""
        import rfauto.adapters.oe_templates.render_sicl_nway as mod

        old = mod._NWAY_G2_MM
        mod._NWAY_G2_MM = 7.0   # xa1−xa2=1.0 → 边距 2−1.1134=0.887<1.524
        try:
            with pytest.raises(ValueError, match="内对输出馈线边距"):
                render_script("nway_wilkinson", dict(NWAY), BAND,
                              mesh_resolution_mm=0.4)
        finally:
            mod._NWAY_G2_MM = old

    def test_nway_rejects_non_four_way(self):
        """渲染 v1 域守卫：n_way≠4 显式拒绝（N=2 与 wilkinson 同解、
        N≥8 超轮转规模，不静默兜底）。"""
        with pytest.raises(ValueError, match="只支持 n_way=4"):
            render_script("nway_wilkinson", dict(NWAY, n_way=8), BAND,
                          mesh_resolution_mm=0.4)


# ─── 5) 字面量接线（LUMPED_VALUE_PARAMS 口径正面钉）───────────────────────────

class TestLiteralWiring:
    def test_nway_iso_r_literal_wired(self):
        """iso_r_ohm 进渲染脚本 LumpedElement R 字面量（导体签名不随它变，
        电阻值面必变——qwt z_load_ohm 同口径）。"""
        text = render_script("nway_wilkinson", dict(NWAY), BAND,
                             mesh_resolution_mm=0.4)
        assert f"ISO_R = {float(NWAY['iso_r_ohm'])!r}" in text
        text2 = render_script(
            "nway_wilkinson",
            dict(NWAY, iso_r_ohm=float(NWAY["iso_r_ohm"]) * 1.5),
            BAND, mesh_resolution_mm=0.4)
        assert "ISO_R = " in text2 and text2 != text
        _, base_prims = gh.load_geometry("nway_wilkinson")
        _, pert_prims = gh.load_geometry(
            "nway_wilkinson",
            dict(NWAY, iso_r_ohm=float(NWAY["iso_r_ohm"]) * 1.5))
        assert (gh.conductor_signature(base_prims)
                == gh.conductor_signature(pert_prims))

    def test_nway_rotation_excite_wiring(self):
        """五端口轮转：excite_port=5 渲染只激励 port5（#208 口径推广）。"""
        assert "nway_wilkinson" in _NWAY_PORT_ROTATION_TEMPLATES
        text = render_script("nway_wilkinson", dict(NWAY), BAND,
                             mesh_resolution_mm=0.4, excite_port=5)
        assert "_PORT_EP = 5" in text
        assert "_port5.uf_inc" in text and "re_S51" in text
        text1 = render_script("nway_wilkinson", dict(NWAY), BAND,
                              mesh_resolution_mm=0.4, excite_port=1)
        assert "_PORT_EP = 1" in text1 and text1 != text

    def test_render_deterministic(self):
        """同参渲染逐字节确定（缓存键/脚本哈希链前提）。"""
        t1 = render_script("sicl", dict(SICL), BAND, mesh_resolution_mm=0.4)
        t2 = render_script("sicl", dict(SICL), BAND, mesh_resolution_mm=0.4)
        assert t1 == t2


# ─── 6) 注册五件套 + docs meta.yaml 一致性 ────────────────────────────────────

class TestRegistration:
    @pytest.mark.parametrize("t", ["sicl", "nway_wilkinson"])
    def test_registered_in_frozen_set(self, t):
        assert t in EXPECTED_TEMPLATES
        assert t in TEMPLATE_META and t in TEMPLATE_NOMINAL
        meta = template_meta(t)
        assert meta["template"] == t
        assert set(meta["nominal_params"]) == set(TEMPLATE_NOMINAL[t])

    @pytest.mark.parametrize("t", ["sicl", "nway_wilkinson"])
    def test_smoke_note_honest(self, t):
        note = str(TEMPLATE_META[t].get("smoke_note", ""))
        assert "未冒烟" in note and "零发射" in note

    def test_port_axes_y(self):
        from rfauto.adapters.openems_templates import _TEMPLATE_PORT_AXES
        assert _TEMPLATE_PORT_AXES["sicl"] == ("y",)
        assert _TEMPLATE_PORT_AXES["nway_wilkinson"] == ("y",)

    @pytest.mark.parametrize("t", ["sicl", "nway_wilkinson"])
    def test_docs_meta_yaml_consistent(self, t):
        path = REPO / "docs" / "templates" / t / "meta.yaml"
        assert path.exists(), path
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["template"] == t
        assert set(data["params"]) == set(TEMPLATE_META[t]["params"])
        assert set(data["nominal_params"]) == set(TEMPLATE_NOMINAL[t])
        for key, value in TEMPLATE_NOMINAL[t].items():
            got = data["nominal_params"][key]
            assert float(got) == pytest.approx(float(value), rel=1e-9)
