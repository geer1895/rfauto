"""TA 批两模板测试：TA-1 schiffman 移相器 + TA-2 qwt_multisection 变换器
（2026-10-02，#212 离线审计制度化）。

零仿真（exec 截断于 FDTD.Run 之前，秒级）：渲染→exec 几何段→CSXCAD 实测
双路径 DC 隔离拓扑/缝内内部线/端接盒导通/端口贴板边 + HJ/KJ 设计链综合
反解自洽（design_params()==TEMPLATE_NOMINAL 逐键 rtol 1e-9）+ 内核闭式锚
（Δφ@f0=90°/ABCD 级联中心匹配恒等式）+ 渲染守卫（板内越界/路径净空/#347
测量面分离/级联溢出）+ 注册五件套 + docs meta.yaml 一致性。

方案锚：研究扩充 round15 §二·2 TA-1/TA-2——
「内核就绪缺模板」件；闭式单源 core/synthesis（synthesize_schiffman /
schiffman_delta_phase / synthesize_multisection_quarter_wave），本模板层
零数值产出（铁律 7/#1c）。近似级别如实登记见两 META smoke_note。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import (
    _FOUR_PORT_ROTATION_TEMPLATES,
    QWT_MULTISECTION_NOMINAL,
    SCHIFFMAN_NOMINAL,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    _qwt_layout,
    _schiffman_layout,
    geometry_spec,
    qwt_multisection_design_params,
    render_script,
    schiffman_design_params,
    template_meta,
)
from tests.unit import _geometry_audit_helpers as gh
from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

SCH_NOM = dict(SCHIFFMAN_NOMINAL)
QWT_NOM = {k: (list(v) if isinstance(v, list) else v)
           for k, v in QWT_MULTISECTION_NOMINAL.items()}
BAND = (2.25, 2.75)


# ─── 1) HJ/KJ 设计链综合反解自洽（#1c：名义值禁手算捷径）──────────────────────

class TestDesignChainSelfConsistent:
    def test_schiffman_design_params_reproduce_nominal(self):
        """schiffman_design_params() 缺省实参重算 == TEMPLATE_NOMINAL 逐键。"""
        design = schiffman_design_params()
        assert set(design) == set(SCH_NOM)
        for key in sorted(SCH_NOM):
            assert design[key] == pytest.approx(SCH_NOM[key], rel=1e-9), key

    def test_qwt_design_params_reproduce_nominal(self):
        """qwt_multisection_design_params() 缺省实参重算 == TEMPLATE_NOMINAL。"""
        design = qwt_multisection_design_params()
        assert set(design) == set(QWT_NOM)
        for key in sorted(QWT_NOM):
            got = design[key]
            want = QWT_NOM[key]
            if isinstance(want, list):
                assert len(got) == len(want)
                for g, w in zip(got, want, strict=True):
                    assert g == pytest.approx(w, rel=1e-9)
            else:
                assert got == pytest.approx(want, rel=1e-9), key

    def test_nominal_literal_table_matches_registry(self):
        """模块 NOMINAL 字面量与注册表同对象（单一事实源，#247 口径）。"""
        assert TEMPLATE_NOMINAL["schiffman"] is SCHIFFMAN_NOMINAL
        assert TEMPLATE_NOMINAL["qwt_multisection"] is QWT_MULTISECTION_NOMINAL


# ─── 2) 内核闭式锚（离线裁判恒等式）───────────────────────────────────────────

class TestKernelAnchors:
    def test_schiffman_delta_phase_at_f0_is_90(self):
        """Δφ(f0)=+90° 精确回代（全通匹配 ρ=2 设计点，内核自洽）。"""
        from rfauto.core.synthesis import schiffman_delta_phase, synthesize_schiffman

        rho = 2.0
        z_e, z_o = 50.0 * math.sqrt(rho), 50.0 / math.sqrt(rho)
        d = synthesize_schiffman(z_e, z_o, 3.66, 0.508e-3, 2.5)
        f0 = 2.5
        dphi = schiffman_delta_phase(
            np.array([f0]), d["coupled_length_m"], z_e, z_o, 3.66, 0.508e-3,
            l_reference_m=d["reference_length_m"])
        assert float(dphi[0]) == pytest.approx(90.0, abs=1e-6)

    def test_schiffman_low_er_reachable_domain_honest(self):
        """ρ=2.4 在 RO4350B 不可达（内核显式拒绝）——nominal_derivation 声明
        的可达域上限必须真实（#122 不凑 ρ=3）。"""
        from rfauto.core.synthesis import synthesize_schiffman

        with pytest.raises(ValueError, match="可达域外"):
            synthesize_schiffman(50.0 * math.sqrt(2.4), 50.0 / math.sqrt(2.4),
                                 3.66, 0.508e-3, 2.5)

    def test_qwt_sections_symmetry_and_center_match(self):
        """谱系恒等式：Z_i·Z_{N+1-i}=Z0·ZL、奇 N 中节=√(Z0·ZL)；λ/4 全节级联
        @f0 把 ZL=100 变换回 Z0=50（binomial 全 N 中心精确匹配，内核口径）。"""
        from rfauto.core.synthesis import synthesize_multisection_quarter_wave

        d = synthesize_multisection_quarter_wave(
            50.0, 100.0, 3, profile="binomial", ripple_db=-20.0, f0_ghz=2.5)
        zs = [s["z_ohm"] for s in d["sections"]]
        assert zs[0] * zs[2] == pytest.approx(5000.0, rel=1e-9)
        assert zs[1] == pytest.approx(math.sqrt(5000.0), rel=1e-9)
        # 全节 λ/4 级联 ABCD（θ=π/2）：M = ∏[[0, jZ_k],[j/Z_k, 0]]；末端 ZL
        # 的输入阻抗 Z_in=(A·ZL+B)/(C·ZL+D) 必须回到 50Ω（Γ_in=0）
        m = np.array([[1.0, 0.0], [0.0, 1.0]])
        for z in zs:
            m = np.array([[0.0, 1j * z], [1j / z, 0.0]]) @ m
        zl = 100.0
        z_in = (m[0, 0] * zl + m[0, 1]) / (m[1, 0] * zl + m[1, 1])
        assert z_in.real == pytest.approx(50.0, rel=1e-9)
        assert abs(z_in.imag) < 1e-9

    def test_qwt_nominal_lists_match_kernel_shape(self):
        """名义节列表长度=3（binomial N=3）；带宽估计 FBW>0 有限。"""
        from rfauto.core.synthesis import synthesize_multisection_quarter_wave

        assert len(QWT_NOM["widths_mm"]) == len(QWT_NOM["lengths_mm"]) == 3
        d = synthesize_multisection_quarter_wave(
            50.0, 100.0, 3, profile="binomial", ripple_db=-20.0, f0_ghz=2.5)
        fbw = d["bandwidth_estimate"]["fbw"]
        assert math.isfinite(fbw) and fbw > 0.0


# ─── 3) #212 离线几何审计（CSXCAD 实测，零仿真）──────────────────────────────

class TestGeometryAudit:
    def test_schiffman_two_path_dc_isolated(self):
        """双路径 DC 隔离=器件定义性质：{1,2} 耦合段一分量、{3,4} 参考段一
        分量，两分量净空 ≥3·h_sub（组判据同 gh.PORT_GROUPS["schiffman"]）。"""
        scope, prims = gh.load_geometry("schiffman")
        ports = gh.port_objects(scope)
        assert sorted(ports) == [1, 2, 3, 4]
        conductors, labels = gh.conductor_labels(prims)
        comps = {n: gh.containing_labels(gh.port_feed_point(p), conductors,
                                         labels)
                 for n, p in ports.items()}
        assert comps[1] & comps[2], "耦合段两近端未导通（桥带断链）"
        assert comps[3] & comps[4], "参考段两端未导通"
        assert not (comps[1] | comps[2]) & (comps[3] | comps[4]), \
            "双路径短路（净空塌缩）"
        # 净空实测：两分量包围盒 x 向最小间距 ≥ 3·h_sub
        comp_a = [p for p, lb in zip(conductors, labels, strict=True)
                  if lb in comps[1]]
        comp_b = [p for p, lb in zip(conductors, labels, strict=True)
                  if lb in comps[3]]
        gap_min = (min(p.lo[0] for p in comp_b)
                   - max(p.hi[0] for p in comp_a))
        assert gap_min >= 3 * 0.508e-3 - 1e-9

    def test_schiffman_gap_internal_line(self):
        """耦合缝内内部线 ≥1（#311 缝中点精确入网口径；审计门同 C4）。"""
        scope, _ = gh.load_geometry("schiffman")
        lines = gh.mesh_lines(scope, "x")
        half = float(SCH_NOM["gap_mm"]) * 1e-3 / 2.0
        inner = lines[(lines > -half + 1e-9) & (lines < half - 1e-9)]
        assert inner.size >= 1

    def test_schiffman_bridge_closes_u(self):
        """桥带闭合 U 形：双带条 lo/hi y=段两端、桥带跨度=gap+2w、桥带顶缘
        =y0+段长+桥带宽（C-section 拓扑本体；MSLPort 自画馈线盒另计）。"""
        _scope, prims = gh.load_geometry("schiffman")
        metals = [p for p in prims if p.kind == "Metal"
                  and p.prop == "schiffman"]
        lc = float(SCH_NOM["l_coupled_mm"]) * 1e-3
        w = float(SCH_NOM["w_mm"]) * 1e-3
        gap = float(SCH_NOM["gap_mm"]) * 1e-3
        y0 = -50e-3
        y1 = y0 + lc
        lines = [p for p in metals
                 if p.lo[1] == pytest.approx(y0, abs=1e-12)
                 and p.hi[1] == pytest.approx(y1, abs=1e-9)]
        assert len(lines) == 2, f"耦合段双带条缺失（{len(lines)}）"
        bridges = [p for p in metals
                   if p.lo[1] == pytest.approx(y1, abs=1e-9)
                   and p.hi[1] == pytest.approx(y1 + w, abs=1e-9)]
        assert len(bridges) == 1 and bridges[0].extent[0] == pytest.approx(
            gap + 2 * w, rel=1e-9), "远端桥带缺失/跨度错"

    def test_schiffman_meas_planes_at_section_ends(self):
        """测量面解嵌到段端面：MeasPlaneShift 字面量=板边→段端距离（layout
        单源；闭式对照含桥带整段的前提）。"""
        lay = _schiffman_layout(dict(SCH_NOM))
        assert lay["plane_feed"] == pytest.approx(
            (float(SCH_NOM["l_coupled_mm"]) * 0 - 50.0 + 60.0) * 1e-3,
            abs=1e-12)
        assert lay["plane_ref"] == pytest.approx(
            (60.0 - float(SCH_NOM["l_ref_mm"]) / 2.0) * 1e-3, abs=1e-9)

    def test_qwt_single_network_and_load_box(self):
        """单导体网络（馈线+3 节+端接盒）；LumpedElement R=ZL 盒压末节端。"""
        _scope, prims = gh.load_geometry("qwt_multisection")
        ports = gh.port_objects(_scope)
        assert sorted(ports) == [1]
        _conductors, labels = gh.conductor_labels(prims)
        assert len(set(labels)) == 1, "级联+端接盒必须单连通分量"
        loads = [p for p in prims if p.prop == "qwt_load"]
        assert len(loads) == 1 and loads[0].kind == "LumpedElement"
        y_end = _qwt_layout(dict(QWT_NOM))["y_end"]
        assert loads[0].hi[1] == pytest.approx(y_end, abs=1e-12)
        # 端接盒 z 跨满基板（对地导通：z=0..H_SUB）
        assert loads[0].lo[2] == pytest.approx(0.0, abs=1e-12)
        assert loads[0].hi[2] == pytest.approx(0.508e-3, rel=1e-9)

    def test_qwt_section_widths_match_nominal(self):
        """三节金属盒宽度逐节=名义 widths（节序沿 +y：低阻宽节在前）。"""
        _scope, prims = gh.load_geometry("qwt_multisection")
        sections = [p for p in prims if p.kind == "Metal"
                    and p.prop == "qwt_multisection"
                    and abs(p.extent[0] - float(QWT_NOM["feed_w_mm"]) * 1e-3)
                    > 1e-12]
        assert len(sections) == 3
        sections.sort(key=lambda p: p.lo[1])
        for p, w_mm in zip(sections, QWT_NOM["widths_mm"], strict=True):
            assert p.extent[0] == pytest.approx(float(w_mm) * 1e-3, rel=1e-9)


# ─── 4) 渲染守卫（渲染期显式抛错）─────────────────────────────────────────────

class TestRenderGuards:
    def test_schiffman_ref_line_overflow_rejected(self):
        bad = dict(SCH_NOM, l_ref_mm=130.0)
        with pytest.raises(ValueError, match="越板边余量"):
            render_script("schiffman", bad, BAND, mesh_resolution_mm=0.2)

    def test_schiffman_path_clearance_rejected(self):
        bad = dict(SCH_NOM, w_ref_mm=30.0)
        with pytest.raises(ValueError, match="路径净空"):
            render_script("schiffman", bad, BAND, mesh_resolution_mm=0.2)

    def test_schiffman_probe_excitation_separation_rejected(self):
        """#347 族：段端面-激励盒分离守卫——粗网格档（base=3mm→NEAR=0.75mm，
        20·NEAR=15mm > 段端面距板边 10mm）必须拒渲染。"""
        with pytest.raises(ValueError, match="测量面-激励分离"):
            render_script("schiffman", dict(SCH_NOM), BAND,
                          mesh_resolution_mm=3.0)

    def test_qwt_cascade_overflow_rejected(self):
        bad = dict(QWT_NOM, lengths_mm=[50.0, 50.0, 50.0])
        with pytest.raises(ValueError, match="越板边余量"):
            render_script("qwt_multisection", bad, BAND,
                          mesh_resolution_mm=0.4)

    def test_qwt_mismatched_lists_rejected(self):
        bad = dict(QWT_NOM, widths_mm=[0.966, 0.603])
        with pytest.raises(ValueError, match="等长非空"):
            render_script("qwt_multisection", bad, BAND,
                          mesh_resolution_mm=0.4)


# ─── 5) 字面量接线（LUMPED_VALUE_PARAMS 口径正面钉）───────────────────────────

class TestLiteralWiring:
    def test_qwt_load_r_literal_wired(self):
        """z_load_ohm 进渲染脚本 LumpedElement R 字面量（导体签名不随它变，
        电阻值面必变——combline c_load_pf 同口径）。"""
        text = render_script("qwt_multisection", dict(QWT_NOM), BAND,
                             mesh_resolution_mm=0.4)
        assert f"ZL = {float(QWT_NOM['z_load_ohm'])!r}" in text
        text2 = render_script(
            "qwt_multisection",
            dict(QWT_NOM, z_load_ohm=float(QWT_NOM["z_load_ohm"]) * 1.5),
            BAND, mesh_resolution_mm=0.4)
        assert "ZL = " in text2 and text2 != text
        # 导体签名（含 LumpedElement 盒几何）不变
        _, base_prims = gh.load_geometry("qwt_multisection")
        _, pert_prims = gh.load_geometry(
            "qwt_multisection",
            dict(QWT_NOM, z_load_ohm=float(QWT_NOM["z_load_ohm"]) * 1.5))
        assert (gh.conductor_signature(base_prims)
                == gh.conductor_signature(pert_prims))

    def test_schiffman_rotation_excite_wiring(self):
        """四端口轮转：excite_port=2 渲染只激励 port2（#208 口径）。"""
        assert "schiffman" in _FOUR_PORT_ROTATION_TEMPLATES
        text = render_script("schiffman", dict(SCH_NOM), BAND,
                             mesh_resolution_mm=0.2, excite_port=2)
        assert "_PORT_EP = 2" in text
        text1 = render_script("schiffman", dict(SCH_NOM), BAND,
                              mesh_resolution_mm=0.2, excite_port=1)
        assert "_PORT_EP = 1" in text1 and text1 != text

    def test_render_deterministic(self):
        """同参渲染逐字节确定（缓存键/脚本哈希链前提）。"""
        t1 = render_script("schiffman", dict(SCH_NOM), BAND,
                           mesh_resolution_mm=0.2)
        t2 = render_script("schiffman", dict(SCH_NOM), BAND,
                           mesh_resolution_mm=0.2)
        assert t1 == t2


# ─── 6) 注册五件套 + docs meta.yaml 一致性 ────────────────────────────────────

class TestRegistration:
    @pytest.mark.parametrize("t", ["schiffman", "qwt_multisection"])
    def test_registered_in_frozen_set(self, t):
        assert t in EXPECTED_TEMPLATES
        assert t in TEMPLATE_META and t in TEMPLATE_NOMINAL
        meta = template_meta(t)
        assert meta["template"] == t
        assert set(meta["nominal_params"]) == set(TEMPLATE_NOMINAL[t])

    @pytest.mark.parametrize("t", ["schiffman", "qwt_multisection"])
    def test_smoke_note_honest(self, t):
        note = str(TEMPLATE_META[t].get("smoke_note", ""))
        assert "未冒烟" in note and "零发射" in note

    def test_port_axes_y(self):
        from rfauto.adapters.openems_templates import _TEMPLATE_PORT_AXES
        assert _TEMPLATE_PORT_AXES["schiffman"] == ("y",)
        assert _TEMPLATE_PORT_AXES["qwt_multisection"] == ("y",)

    @pytest.mark.parametrize("t", ["schiffman", "qwt_multisection"])
    def test_docs_meta_yaml_consistent(self, t):
        path = REPO / "docs" / "templates" / t / "meta.yaml"
        assert path.exists(), path
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["template"] == t
        assert set(data["params"]) == set(TEMPLATE_META[t]["params"])
        assert set(data["nominal_params"]) == set(TEMPLATE_NOMINAL[t])
        for key, value in TEMPLATE_NOMINAL[t].items():
            got = data["nominal_params"][key]
            if isinstance(value, list):
                assert len(got) == len(value)
                for g, w in zip(got, value, strict=True):
                    assert float(g) == pytest.approx(float(w), rel=1e-9)
            else:
                assert float(got) == pytest.approx(float(value), rel=1e-9)

    @pytest.mark.parametrize("t", ["schiffman", "qwt_multisection"])
    def test_geometry_spec_port_count(self, t):
        spec = geometry_spec(t, dict(TEMPLATE_NOMINAL[t]))
        assert len(spec["ports"]) == int(TEMPLATE_META[t]["n_ports"])
