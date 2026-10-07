"""TA 批第三批两模板测试：TA-5 diplexer（LP+HP T 结）+ TA-6 ridged_wg
空气脊波导（2026-10-02，#212 离线审计制度化；test_sicl_nway_templates
同构）。

零仿真（exec 截断于 FDTD.Run 之前，秒级）：渲染→exec 几何段→CSXCAD 实测
T 结三端口单网络/集总断口桥接与脊波导全金属封闭腔拓扑 + 内核设计链独立
闭式复算（diplexer_compose element_values / ridged_waveguide
design_ridge_depth 4 位舍入回代）+ 内核锚（CR 对三恒等式 verdict /
XC-P 精度域 g/b≥0.4）+ 渲染守卫（深脊拒渲染/判读带单模域/#266 特征
分辨/阶数域/#347）+ 注册五件套 + docs meta.yaml 一致性。

方案锚：研究扩充 round15 §二·2 TA-5/TA-6——
「内核就绪缺模板」件；闭式单源 core（diplexer_compose.diplexer_lpf_hpf /
ridged_waveguide.design_ridge_depth），本模板层零数值产出（铁律 7/#1c）。
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

import numpy as np

from rfauto.adapters.openems_templates import (
    _THREE_PORT_ROTATION_TEMPLATES,
    DIPLEXER_NOMINAL,
    RIDGED_WG_NOMINAL,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    _diplexer_layout,
    diplexer_design_params,
    geometry_spec,
    render_script,
    ridged_wg_design_params,
    ridged_wg_layout,
    template_meta,
)
from tests.unit import _geometry_audit_helpers as gh
from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

DIP = dict(DIPLEXER_NOMINAL)
RWG = dict(RIDGED_WG_NOMINAL)
BAND = (2.25, 2.75)
RWG_BAND = (4.95, 5.45)   # 审计频带（meta f0=5.2 ±0.25）


# ─── 1) 设计链独立闭式复算（#1c：名义值禁手算捷径）─────────────────────────────

class TestDesignChainSelfConsistent:
    def test_diplexer_design_params_reproduce_nominal(self):
        """diplexer_design_params() 缺省实参重算 == TEMPLATE_NOMINAL 逐键。"""
        design = diplexer_design_params()
        assert set(design) == set(DIP)
        for key in sorted(DIP):
            assert design[key] == pytest.approx(DIP[key], rel=1e-9), key

    def test_diplexer_element_values_independent_closed_form(self):
        """元件值独立闭式复算（#118：数值裁判独立来源）：一阶 CR 对
        L=Z0/ωc、C=1/(ωc·Z0)（g_eff=1 定标）按 math 闭式重算 round4。"""
        fc = 2.5e9
        z0 = 50.0
        wc = 2.0 * math.pi * fc
        assert DIP["l_lpf_nh"] == round(z0 / wc * 1e9, 4)
        assert DIP["c_hpf_pf"] == round(1.0 / (wc * z0) * 1e12, 4)
        # 内核 element_values 同值（结构对拍，双路径）
        from rfauto.core.diplexer_compose import diplexer_lpf_hpf

        d = diplexer_lpf_hpf([fc], fc, 1, 1, z0)
        assert d["element_values"]["lpf"] == [("series_L", z0 / wc)]
        assert d["element_values"]["hpf"] == [("series_C", 1.0 / (wc * z0))]

    def test_diplexer_feed_width_single_source(self):
        """w_feed=nominal_width_mm(50)@2.5GHz（XC-W 单源，无字面量落表）。"""
        from rfauto.core.synthesis import nominal_width_mm

        assert DIP["w_feed_mm"] == nominal_width_mm(50.0, 2.5,
                                                    "rogers4350b_h0.508")

    def test_ridged_wg_design_params_reproduce_nominal(self):
        """ridged_wg_design_params() 缺省实参重算 == TEMPLATE_NOMINAL 逐键
        （er/h_mm 为空气填充占位键，pyramid_horn 家族同构——非设计链产出，
        另钉）。"""
        design = ridged_wg_design_params()
        assert set(design) == set(RWG)
        for key in sorted(RWG):
            assert design[key] == pytest.approx(RWG[key], rel=1e-9), key
        assert RWG["er"] == 1.0 and RWG["h_mm"] == 0.0

    def test_ridged_wg_depth_roundtrip_independent(self):
        """d_mm 4 位舍入档回代（#1c 反解链质量门）：round(d,4) 对 fc_target
        回代 |Δfc|/fc ≤1e-4（实测 ~3.8e-6）+ design_ridge_depth 未舍入值
        恒等复算。"""
        from rfauto.core.ridged_waveguide import (
            RidgedWaveguide,
            cutoff_fc_hz,
            design_ridge_depth,
        )

        r = design_ridge_depth(5.0e9, RWG["a_mm"] * 1e-3, RWG["b_mm"] * 1e-3,
                               RWG["s_mm"] * 1e-3, False)
        assert round(float(r["d_m"]) * 1e3, 4) == RWG["d_mm"]
        wg = RidgedWaveguide(a=RWG["a_mm"] * 1e-3, b=RWG["b_mm"] * 1e-3,
                             s=RWG["s_mm"] * 1e-3, d=RWG["d_mm"] * 1e-3,
                             double=False)
        fc = cutoff_fc_hz(wg)
        assert abs(fc - 5.0e9) / 5.0e9 <= 1e-4

    def test_nominal_literal_table_matches_registry(self):
        """模块 NOMINAL 字面量与注册表同对象（单一事实源，#247 口径）。"""
        assert TEMPLATE_NOMINAL["diplexer"] is DIPLEXER_NOMINAL
        assert TEMPLATE_NOMINAL["ridged_wg"] is RIDGED_WG_NOMINAL


# ─── 2) 内核锚（离线裁判恒等式）───────────────────────────────────────────────

class TestKernelAnchors:
    def test_diplexer_cr_verdict_exact_anchors(self):
        """CR 一阶对三恒等式（内核对名义设计精确成立）：verdict 四门全绿
        （能量守恒/交越=fc/通带 S11/互补），S11 全带深谷。"""
        from rfauto.core.diplexer_compose import diplexer_lpf_hpf, diplexer_verdict

        fc = 2.5e9
        d = diplexer_lpf_hpf(np.linspace(0.3e9, 6e9, 2291), fc, 1, 1, 50.0)
        v = diplexer_verdict(d, fc, s11_max_db=-15.0, crossover_tol_frac=0.1)
        assert v["overall"] == "pass"
        assert v["energy_max_dev"] <= 1e-8
        assert abs(v["crossover_ghz"] * 1e9 - fc) <= 0.1 * fc
        assert v["s11_worst_db"] < -100.0   # S11≡0（恒阻对偶，机器精度）

    def test_ridged_wg_nominal_in_xcp_domain(self):
        """名义 g/b=0.454 落 XC-P 精度域（≥0.4）且 fc 回代 5GHz；深脊点
        g/b<0.4 被 design 链显式拒绝（守卫移植）。"""
        from rfauto.core.ridged_waveguide import (
            RidgedWaveguide,
            cutoff_fc_hz,
        )

        wg = RidgedWaveguide(a=RWG["a_mm"] * 1e-3, b=RWG["b_mm"] * 1e-3,
                             s=RWG["s_mm"] * 1e-3, d=RWG["d_mm"] * 1e-3,
                             double=False)
        assert wg.gap_ratio == pytest.approx(0.4544, abs=1e-3)
        assert wg.gap_ratio >= 0.4
        assert cutoff_fc_hz(wg) == pytest.approx(5.0e9, rel=1e-4)
        with pytest.raises(ValueError, match="g/b"):
            ridged_wg_design_params(fc_target_ghz=4.0)

    def test_ridged_wg_band_domain_and_feed_invariant(self):
        """判读带 (0.8, 1.26)·fc ⊂ 单模域（fc_feed、馈段 TE20、外廓 TE10）
        且 a_feed>4a/3 构造不变式；消逝衰减锚 @0.8fc ≈22dB（L_ridge=40mm）。"""
        lay = ridged_wg_layout(RWG, (0.8 * 5.0, 1.26 * 5.0))
        assert lay["a_feed_mm"] > 4.0 * RWG["a_mm"] / 3.0
        assert lay["fc_feed_ghz"] < 0.8 * 5.0
        assert min(1.5 * lay["fc_ridge_ghz"],
                                lay["fc_outline_ghz"]) > 1.26 * 5.0
        assert lay["atten_lo_db"] == pytest.approx(21.9, abs=1.0)


# ─── 3) #212 离线几何审计（CSXCAD 实测，零仿真）──────────────────────────────

class TestGeometryAudit:
    def test_diplexer_single_network_and_lumped_bridges(self):
        """全 3 端口单导体网络（T 结经断口 LumpedElement 导通）；恰 2 支
        集总元件（LPF L+HPF C），断口几何=layout 单源。"""
        scope, prims = gh.load_geometry("diplexer")
        ports = gh.port_objects(scope)
        assert sorted(ports) == [1, 2, 3]
        conductors, labels = gh.conductor_labels(prims)
        comps = {n: gh.containing_labels(gh.port_feed_point(p), conductors,
                                         labels)
                 for n, p in ports.items()}
        all_comp = set().union(*comps.values())
        assert len(all_comp) == 1, (
            f"T 结网络分裂：{[sorted(c) for c in comps.values()]}")
        lumps = [p for p in prims if p.kind == "LumpedElement"]
        assert len(lumps) == 2, f"集总元件支数 {len(lumps)}（预期 2）"
        lay = _diplexer_layout(dict(DIP))
        by_x = sorted(r.lo[0] for r in lumps)
        assert by_x == pytest.approx([-(lay["x_e"] + lay["gap"]),
                                      lay["x_e"]], abs=1e-12)

    def test_diplexer_arm_gaps_break_metal(self):
        """断口处金属真断开（LumpedElement 桥接前 DC 隔离段存在）：断口
        区间 [x_e, x_e+gap] 内无金属原语覆盖全宽（HPF 臂对称）。"""
        _scope, prims = gh.load_geometry("diplexer")
        lay = _diplexer_layout(dict(DIP))
        metals = [p for p in prims if p.kind == "Metal"]
        for xc in (lay["x_e"] + lay["gap"] / 2.0,
                   -(lay["x_e"] + lay["gap"] / 2.0)):
            spanning = [p for p in metals
                        if p.lo[0] < xc < p.hi[0]
                        and p.lo[1] <= -lay["wf"] / 2 + 1e-12
                        and p.hi[1] >= lay["wf"] / 2 - 1e-12]
            assert not spanning, f"断口 x={xc} 处金属直通（桥接失效嫌疑）"

    def test_ridged_wg_all_metal_closed_waveguide(self):
        """全金属封闭腔拓扑：脊块实体（顶壁悬出）+ 馈段壁 + 阶跃框板；无
        介质原语（NO_SUBSTRATE 口径）；端口=双 RectWGPort 截面含导体。"""
        scope, prims = gh.load_geometry("ridged_wg")
        ports = gh.port_objects(scope)
        assert sorted(ports) == [1, 2]
        assert [p.prop for p in prims if p.kind == "Material"] == []
        walls = [p for p in prims if p.kind == "Metal"]
        assert len(walls) == 17, (
            f"金属原语数 {len(walls)}（预期 17：4 脊段壁+1 脊块+8 馈段壁"
            "+4 框板）")
        # 脊块：顶壁悬出实体（z 从 b/2−d 到 b/2，x∈±s/2）
        b = float(RWG["b_mm"]) * 1e-3
        d = float(RWG["d_mm"]) * 1e-3
        s = float(RWG["s_mm"]) * 1e-3
        ridge = [p for p in walls
                 if p.lo[2] == pytest.approx(b / 2 - d, abs=1e-12)
                 and p.hi[2] == pytest.approx(b / 2, abs=1e-12)
                 and p.lo[0] == pytest.approx(-s / 2, abs=1e-12)
                 and p.hi[0] == pytest.approx(s / 2, abs=1e-12)]
        assert len(ridge) == 1, "脊块缺失/几何漂移"
        for n, p in ports.items():
            lo = np.minimum(np.asarray(p.start, dtype=float),
                            np.asarray(p.stop, dtype=float))
            hi = np.maximum(np.asarray(p.start, dtype=float),
                            np.asarray(p.stop, dtype=float))
            inside = [q for q in prims if gh.is_conductor(q)
                      and bool(np.all(q.hi >= lo - 1e-9))
                      and bool(np.all(q.lo <= hi + 1e-9))]
            assert inside, f"port{n}: 端口截面无导体（模式端口无效）"

    def test_ridged_wg_rect_domain_literal(self):
        """矩形域 DOM_X/DOM_Y 字面注入（layout 单源一致；H_SUB=0/ER=1 占
        位键）。"""
        scope, _ = gh.load_geometry("ridged_wg")
        lay = ridged_wg_layout(dict(RWG), RWG_BAND, 0.4)
        assert float(scope["DOM_X"]) == pytest.approx(
            lay["dom_x_mm"] * 1e-3, rel=1e-12)
        assert float(scope["DOM_Y"]) == pytest.approx(
            lay["dom_y_mm"] * 1e-3, rel=1e-12)
        assert float(scope["H_SUB"]) == 0.0
        assert float(scope["ER"]) == 1.0

    def test_geometry_spec_port_counts(self):
        """geometry_spec 端口数=meta n_ports（diplexer=3、ridged_wg=2）。"""
        for t, n in (("diplexer", 3), ("ridged_wg", 2)):
            spec = geometry_spec(t, dict(TEMPLATE_NOMINAL[t]))
            assert len(spec["ports"]) == n == int(TEMPLATE_META[t]["n_ports"])


# ─── 4) 渲染守卫（渲染期显式抛错）─────────────────────────────────────────────

class TestRenderGuards:
    def test_diplexer_probe_excitation_separation_rejected(self):
        """#347 族：输入段测量面-激励盒分离守卫——粗网格档（base=8mm →
        13.9·NEAR=27.8mm > 测量面 20mm）必须拒渲染。"""
        with pytest.raises(ValueError, match="FeedShift"):
            render_script("diplexer", dict(DIP), BAND,
                          mesh_resolution_mm=8.0)

    def test_diplexer_rejects_higher_order(self):
        """渲染 v1 只支持一阶 CR 对（≥2 阶对固有回损地板），显式拒绝。"""
        with pytest.raises(ValueError, match="一阶 CR 对"):
            diplexer_design_params(lpf_order=3, hpf_order=3)

    def test_ridged_wg_deep_ridge_rejected(self):
        """深脊 g/b<0.4（XC-P 精度域外）拒渲染——d_mm 扰到 8mm。"""
        with pytest.raises(ValueError, match="g/b"):
            render_script("ridged_wg", dict(RWG, d_mm=8.0), RWG_BAND,
                          mesh_resolution_mm=0.4)

    def test_ridged_wg_feature_resolution_rejected(self):
        """NEAR > min(s,g)/3（#266 族特征分辨）拒渲染——粗网格档。"""
        with pytest.raises(ValueError, match="NEAR"):
            render_script("ridged_wg", dict(RWG), RWG_BAND,
                          mesh_resolution_mm=30.0)

    def test_ridged_wg_band_domain_rejected(self):
        """判读带越单模域拒渲染：带底 ≤1.03·fc_feed（馈段消逝）。"""
        with pytest.raises(ValueError, match="带底"):
            ridged_wg_layout(dict(RWG), (3.0, 6.3))
        with pytest.raises(ValueError, match="带顶"):
            ridged_wg_layout(dict(RWG), (4.95, 6.8))

    def test_ridged_wg_rejects_other_excite_port(self):
        """双端口单激励模板（无轮转），excite_port≠1 显式拒绝。"""
        with pytest.raises(ValueError, match="excite_port"):
            render_script("ridged_wg", dict(RWG), RWG_BAND,
                          mesh_resolution_mm=0.4, excite_port=2)


# ─── 5) 字面量接线（LUMPED_VALUE_PARAMS 口径正面钉）───────────────────────────

class TestLiteralWiring:
    def test_diplexer_element_literal_wired(self):
        """l_lpf_nh/c_hpf_pf 进渲染脚本 LumpedElement L=/C= 字面量（导体
        签名不随它们变，元件值面必变——qwt z_load_ohm 同口径）。"""
        text = render_script("diplexer", dict(DIP), BAND,
                             mesh_resolution_mm=0.4)
        assert f"L_LPF = {float(DIP['l_lpf_nh']) * 1e-9!r}" in text
        assert f"C_HPF = {float(DIP['c_hpf_pf']) * 1e-12!r}" in text
        text2 = render_script(
            "diplexer",
            dict(DIP, l_lpf_nh=float(DIP["l_lpf_nh"]) * 1.5),
            BAND, mesh_resolution_mm=0.4)
        assert text2 != text and "L_LPF = " in text2
        _, base_prims = gh.load_geometry("diplexer")
        _, pert_prims = gh.load_geometry(
            "diplexer", dict(DIP, l_lpf_nh=float(DIP["l_lpf_nh"]) * 1.5))
        assert (gh.conductor_signature(base_prims)
                == gh.conductor_signature(pert_prims))

    def test_diplexer_rotation_excite_wiring(self):
        """三端口轮转：excite_port=3 渲染只激励 port3（#208 口径 N=3 档）。"""
        assert "diplexer" in _THREE_PORT_ROTATION_TEMPLATES
        text = render_script("diplexer", dict(DIP), BAND,
                             mesh_resolution_mm=0.4, excite_port=3)
        assert "_PORT_EP = 3" in text
        assert "_port3.uf_inc" in text and "re_S31" in text
        assert "re_S41" not in text   # 7 列 CSV（freq+3×(re,im)）
        text1 = render_script("diplexer", dict(DIP), BAND,
                              mesh_resolution_mm=0.4, excite_port=1)
        assert "_PORT_EP = 1" in text1 and text1 != text

    def test_diplexer_no_width_literal(self):
        """XC-W：渲染面零 50Ω 宽字面量（layout 缺省走 _nominal_width 惰性
        W50_MM；普查守卫见表内登记面）。"""
        import ast as _ast

        from rfauto.adapters.oe_templates import render_diplexer_ridged

        src = Path(render_diplexer_ridged.__file__).read_text(
            encoding="utf-8")
        hits = [n for n in _ast.walk(_ast.parse(src))
                if isinstance(n, _ast.Constant) and n.value in
                (1.1134, 1.1133, 1.113, 1.112, 1.1117)]
        assert hits == [], "渲染文件散落 50Ω 宽字面量（XC-W 违例）"

    def test_ridged_wg_summary_anchor_literals(self):
        """内核判读锚回显字面量（fc/gap_ratio/消逝衰减）在渲染脚本 summary
        单源注入；同参渲染逐字节确定（缓存键/脚本哈希链前提）。"""
        text = render_script("ridged_wg", dict(RWG), RWG_BAND,
                             mesh_resolution_mm=0.4)
        lay = ridged_wg_layout(dict(RWG), RWG_BAND, 0.4)
        assert f"fc_ridge_ghz={lay['fc_ridge_ghz']!r}" in text
        assert f"gap_ratio={lay['gap_ratio']!r}" in text
        t2 = render_script("ridged_wg", dict(RWG), RWG_BAND,
                           mesh_resolution_mm=0.4)
        assert t2 == text


# ─── 6) 注册五件套 + docs meta.yaml 一致性 ────────────────────────────────────

class TestRegistration:
    @pytest.mark.parametrize("t", ["diplexer", "ridged_wg"])
    def test_registered_in_frozen_set(self, t):
        assert t in EXPECTED_TEMPLATES
        assert t in TEMPLATE_META and t in TEMPLATE_NOMINAL
        meta = template_meta(t)
        assert meta["template"] == t
        assert set(meta["nominal_params"]) == set(TEMPLATE_NOMINAL[t])

    @pytest.mark.parametrize("t", ["diplexer", "ridged_wg"])
    def test_smoke_note_honest(self, t):
        note = str(TEMPLATE_META[t].get("smoke_note", ""))
        assert "未冒烟" in note and "零发射" in note

    def test_port_axes(self):
        from rfauto.adapters.openems_templates import _TEMPLATE_PORT_AXES
        assert _TEMPLATE_PORT_AXES["diplexer"] == ("x", "y")
        assert _TEMPLATE_PORT_AXES["ridged_wg"] == ("y",)

    @pytest.mark.parametrize("t", ["diplexer", "ridged_wg"])
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
