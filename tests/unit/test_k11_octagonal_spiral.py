"""octagonal_spiral 八角螺旋电感模板测试（aurora_k K11，反馈 F1）。

零仿真（exec 截断于 FDTD.Run 之前，秒级）：Mohan 论文数表抽查（#55/#56
值+页码来源标注）+ CALC 键面门行为 + 布局单源几何/守卫 + #212 exec 审计
（单连通/地平面隔离/端口跨隙）+ fake 自洽（L 回收/SRF 对拍/参数驱动）+
注册面同步。判据预声明 内部证据档（先声明后实测）。

数字出处（#118 家法，#331 审计 dump 原文纪律）：
- Mohan-Schneider-Chibante, "Simple Accurate Expressions for Planar
  Spiral Inductances", IEEE JSSC 34(10) 1999, pp.1419-1424——Table IV
  八角实测例 #55（n=4, d_out=346μm, w=18μm, s=2μm, L_meas=5.90nH）与
  #56（n=5 同几何 L_meas=7.50nH），原文 pp.1422-1423 数表；系数表
  （Table I/II/III）原文 600dpi 渲染逐位目检在案（core/nfc_coil 模块头）；
- 用户实测参考（反馈 F1 原文）：HFSS 默认网格 L=4.226nH/Q=10.86/
  SRF=6.32GHz；金属局部 5μm 网格后 4.312nH/13.44/7.18GHz（P6 网格收敛
  教训）——名义几何闭式 4.1147nH 对拍 +2.7%/+4.8%（±25% 门内；用户几何
  未给全 W/S/N/Din，同量级参考对拍非逐位锚）。
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

from rfauto.adapters.openems_templates import (
    OCTAGONAL_SPIRAL_NOMINAL,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    _octagonal_spiral_layout,
    geometry_spec,
    octagonal_spiral_geometry_spec,
    render_script,
    template_meta,
)
from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.core.nfc_coil import CoilGeometry, spiral_inductance, winding_parasitic_capacitance_f
from rfauto.service.calculator_service import run_calculator
from tests.unit import _geometry_audit_helpers as gh

NOM = dict(OCTAGONAL_SPIRAL_NOMINAL)
BAND = (2.0 - 0.25, 2.0 + 0.25)


def _closed_geom(n: float, din_um: float, w_um: float,
                 s_um: float) -> CoilGeometry:
    """μm 参数 → CoilGeometry（d_out 闭式导出，CALC 键同语义 #154）。"""
    d_out = (din_um + 2.0 * n * w_um + 2.0 * (n - 1.0) * s_um) * 1e-6
    return CoilGeometry("octagon", n, d_out, w_um * 1e-6, s_um * 1e-6)


# ─── 1) Mohan 论文数表抽查（值+页码来源标注）────────────────────────────────

class TestMohanPaperAnchors:
    def test_table4_octagon_55(self):
        """Table IV 八角例 #55（pp.1422-1423 数表）：n=4/d_out=346/w=18/s=2
        μm，L_meas=5.90nH——键面 μm 口径端到端回放，偏差 ≤5%（原文印刷
        误差列 ≤1% 口径宽化档）。"""
        din = 346.0 - 2.0 * 4 * 18.0 - 2.0 * 3 * 2.0   # =190μm 闭式回演
        out = run_calculator("octagonal_spiral_inductance", {
            "n_turns": 4, "din_um": din, "w_um": 18.0, "s_um": 2.0,
            "dout_um": 346.0})
        assert out["ok"] is True, out
        out = out["result"]
        l_nh = out["l_main_nh"]
        assert l_nh == pytest.approx(5.90, rel=0.05), (
            f"Table IV #55 回放 {l_nh}nH vs 5.90nH（Mohan JSSC 34(10) 1999 "
            "pp.1422-1423 数表）")
        # 单源一致：CALC 键 L 与 core/nfc_coil 直算逐位同源
        direct = spiral_inductance(
            _closed_geom(4, din, 18.0, 2.0), "current_sheet")
        assert l_nh * 1e-9 == pytest.approx(direct, rel=1e-12)

    def test_table4_octagon_56(self):
        """Table IV 八角例 #56（同 #55 几何，n=5）：L_meas=7.50nH。"""
        din = 346.0 - 2.0 * 5 * 18.0 - 2.0 * 4 * 2.0   # =150μm
        out = run_calculator("octagonal_spiral_inductance", {
            "n_turns": 5, "din_um": din, "w_um": 18.0, "s_um": 2.0,
            "dout_um": 346.0})
        assert out["ok"] is True
        out = out["result"]
        assert out["l_main_nh"] == pytest.approx(7.50, rel=0.05), (
            "Table IV #56 回放（Mohan JSSC 34(10) 1999 pp.1422-1423 数表）")

    def test_three_expression_spread_bounded(self):
        """三表达式互一致（Mohan 原文三式对同几何的散布 ≤10%——拟合库
        预声明精度档量级；八角系数 Table I/II/III 原文锚）。"""
        out = run_calculator("octagonal_spiral_inductance", {
            "n_turns": 5, "din_um": 80.0, "w_um": 10.0, "s_um": 5.0})
        assert out["result"]["l_expressions_spread_pct"] < 10.0

    def test_user_reference_deviation_within_gate(self):
        """用户实测参考（反馈 F1）：名义几何闭式 4.1147nH 对 HFSS 实测
        4.226/4.312nH 偏差 +2.7%/+4.8%（±25% 门内，未标定注记）。"""
        out = run_calculator("octagonal_spiral_inductance", {
            "n_turns": 5, "din_um": 80.0, "w_um": 10.0, "s_um": 5.0})
        out = out["result"]
        assert out["l_main_nh"] == pytest.approx(4.1147, abs=5e-4)
        for meas, expect_dev in ((4.226, 2.71), (4.312, 4.80)):
            dev = (meas - out["l_main_nh"]) / out["l_main_nh"] * 100.0
            assert dev == pytest.approx(expect_dev, abs=0.05)
            assert abs(dev) <= 25.0


# ─── 2) CALC 键面：门行为与守卫 ─────────────────────────────────────────────

_GATE_BASE: dict = {"n_turns": 5, "din_um": 80.0, "w_um": 10.0,
                    "s_um": 5.0}


class TestCalcGateBehavior:
    BASE = _GATE_BASE

    def test_l_gate_pass_and_fail(self):
        ok = run_calculator("octagonal_spiral_inductance",
                            {**self.BASE, "reference_l_nh": 4.226})
        assert ok["result"]["gates"]["l_vs_reference"]["pass"] is True
        bad = run_calculator("octagonal_spiral_inductance",
                             {**self.BASE, "reference_l_nh": 8.0})
        gate = bad["result"]["gates"]["l_vs_reference"]
        assert gate["pass"] is False
        assert gate["deviation_pct"] == pytest.approx(
            (8.0 - 4.114657) / 4.114657 * 100.0, abs=1e-3)
        assert bad["ok"] is True   # FAIL 如实呈现不抛异常（#122）
        assert bad["result"]["ok"] is True

    def test_srf_gate_pass_and_fail(self):
        ok = run_calculator("octagonal_spiral_inductance", {
            **self.BASE, "f0_ghz": 2.0, "c_par_ff": 80.75})
        assert ok["result"]["gates"]["srf_over_f0"]["pass"] is True
        assert ok["result"]["srf_ghz"] == pytest.approx(8.731, abs=5e-3)
        bad = run_calculator("octagonal_spiral_inductance", {
            **self.BASE, "f0_ghz": 2.0, "c_par_ff": 800.0})
        assert bad["result"]["gates"]["srf_over_f0"]["pass"] is False

    def test_dout_consistency_guard(self):
        """dout_um 与闭式导出漂移 >1% 显式拒绝（#154 跨通道同语义）——
        service 层把 ValueError 翻译成 ok=False 信封（不抛，#122）。"""
        out = run_calculator("octagonal_spiral_inductance",
                             {**self.BASE, "dout_um": 300.0})
        assert out["ok"] is False and "dout_um" in out["error"]
        ok = run_calculator("octagonal_spiral_inductance",
                            {**self.BASE, "dout_um": 220.0})
        assert ok["ok"] is True and ok["result"]["ok"] is True

    def test_guards_domain_errors(self):
        for params in ({"n_turns": 0}, {"n_turns": 0.5}, {"din_um": 0.0},
                       {"w_um": -1.0}, {"s_um": 0.0}):
            out = run_calculator("octagonal_spiral_inductance",
                                 {**self.BASE, **params})
            assert out["ok"] is False and out.get("error"), params
            assert "result" not in out or out["result"] is None or isinstance(out["result"], dict)

    def test_q_dc_report_and_esr_branch(self):
        out = run_calculator("octagonal_spiral_inductance", {
            **self.BASE, "f0_ghz": 2.0, "include_esr": True})
        out = out["result"]
        l_h = out["l_main_nh"] * 1e-9
        q_expect = 2.0 * math.pi * 2.0e9 * l_h / out["loss"]["r_dc_ohm"]
        assert out["q_dc_at_f0"] == pytest.approx(q_expect, rel=1e-3)
        assert out["q_dc_at_f0"] > 10.0   # 一阶量级（未标定如实声明）
        assert "esr_ohm" in out["loss"]

    def test_track_length_matches_layout_family(self):
        """键面导带总长与渲染匝梯同族（±20%——渲染路径每匝省 BR 切角但
        加下平边内延+换匝竖尾，三笔二阶项部分抵消（名义档 +16%）；跳桥
        附加长度不计（CALC docstring 如实声明口径）。"""
        out = run_calculator("octagonal_spiral_inductance",
                             dict(self.BASE))["result"]
        lay = _octagonal_spiral_layout(dict(NOM), BAND)
        assert lay["track"] == pytest.approx(out["geometry"]["track_length_mm"]
                                             * 1e-3, rel=0.20)


# ─── 3) 匝间寄生电容一阶估计（确定性单源）────────────────────────────────────

class TestWindingCapacitance:
    def test_two_turn_closed_form_bitwise(self):
        """n=2 只有 1 个相邻匝对——C=ε0·εeff·t·l_0/s 逐位重算对照。"""
        geom = _closed_geom(2, 80.0, 10.0, 5.0)
        c = winding_parasitic_capacitance_f(geom, 3e-6, 12.9)
        from rfauto.core.nfc_coil import polygon_loop_vertices
        v = np.asarray(polygon_loop_vertices("octagon", geom.d_out_m / 2
                                             - 5e-6), dtype=float)
        perim0 = float(np.sum(np.hypot(*(np.roll(v, -1, axis=0) - v).T)))
        c_ref = 8.854187817e-12 * 0.5 * (1.0 + 12.9) * (3e-6 * perim0 / 5e-6)
        assert c == pytest.approx(c_ref, rel=1e-12)

    def test_monotonicity(self):
        """匝数增→C 增（匝对数与周长同增）；间距增→C 减（极板间距）。"""
        c5 = winding_parasitic_capacitance_f(_closed_geom(5, 80, 10, 5),
                                             3e-6, 12.9)
        c6 = winding_parasitic_capacitance_f(_closed_geom(6, 80, 10, 5),
                                             3e-6, 12.9)
        assert c6 > c5 > 0.0
        c_loose = winding_parasitic_capacitance_f(_closed_geom(5, 80, 10, 8),
                                                  3e-6, 12.9)
        assert c_loose < c5

    def test_guards(self):
        geom = _closed_geom(5, 80, 10, 5)
        with pytest.raises(ValueError):
            winding_parasitic_capacitance_f(geom, 3e-6, 0.5)
        with pytest.raises(ValueError):
            winding_parasitic_capacitance_f(geom, 0.0, 12.9)

    def test_nominal_c_par_and_srf_scale(self):
        """名义档 C_par=80.75fF → SRF=8.73GHz（对用户实测 6.32/7.18GHz
        同量级——一阶未标定，量级 sanity 非逐位锚）。"""
        c = winding_parasitic_capacitance_f(_closed_geom(5, 80, 10, 5),
                                            3e-6, 12.9)
        assert c == pytest.approx(80.75e-15, rel=1e-3)
        l_nom = spiral_inductance(_closed_geom(5, 80, 10, 5),
                                  "current_sheet")
        srf = 1.0 / (2.0 * math.pi * math.sqrt(l_nom * c))
        assert srf == pytest.approx(8.73e9, rel=1e-2)


# ─── 4) 布局单源：几何/守卫（#212 家法辅助）──────────────────────────────────

class TestLayout:
    def test_closed_form_dout_and_turn_ladder(self):
        lay = _octagonal_spiral_layout(dict(NOM), BAND)
        assert lay["d_out"] == pytest.approx(220e-6, rel=1e-12)
        assert lay["a0"] == pytest.approx(110e-6 - 5e-6, rel=1e-12)
        assert lay["a_min"] == pytest.approx(lay["a0"] - 4 * lay["pitch"],
                                             rel=1e-12)
        assert lay["a_min"] - lay["w"] / 2.0 == pytest.approx(
            _closed_geom(5, 80, 10, 5).d_in_m / 2, rel=1e-12)

    def test_segment_counts(self):
        """每匝 4 平边+3 切角+1 换匝尾（末匝止内端无尾）——单折线连通。"""
        lay = _octagonal_spiral_layout(dict(NOM), BAND)
        assert len(lay["flats"]) == 4 * 5 + 4          # 4n + (n−1) 竖尾
        assert len(lay["diags"]) == 3 * 5              # BR 切角由换匝取代

    def test_port_span_is_gap_and_pad_outside(self):
        lay = _octagonal_spiral_layout(dict(NOM), BAND)
        px0, py0, px1, py1 = lay["port_box"]
        assert px1 - px0 == pytest.approx(NOM["gap_um"] * 1e-3 * 1e-3,
                                          rel=1e-12)
        assert py1 - py0 == pytest.approx(lay["w"], rel=1e-12)
        # 焊盘在螺旋右缘之外（gap 间隙隔开）、桥隙两缘各贴一侧金属
        assert lay["pad"][0] == pytest.approx(px1, rel=1e-12)
        assert px0 == pytest.approx(lay["a0"] + lay["w"] / 2.0, rel=1e-12)

    def test_diag_staircase_overlaps_connected(self):
        """切角阶梯盒逐对重叠（逐轴 ≥0）——FDTD 导通前提。"""
        from rfauto.adapters.oe_templates.render_octagonal_spiral import (
            _oct_diag_boxes,
        )
        lay = _octagonal_spiral_layout(dict(NOM), BAND)
        for seg in lay["diags"]:
            boxes = _oct_diag_boxes(*seg, lay["w"], lay["h"])
            assert len(boxes) >= 2
            from itertools import pairwise
            for a, b in pairwise(boxes):
                assert a[3] >= b[0] and b[3] >= a[0]   # x 重叠
                assert a[4] >= b[1] and b[4] >= a[1]   # y 重叠
            # 阶梯折线保持在中心线 ±w 带内（阶梯盒缘到段端点 ≤w）
            for seg_end in ((seg[0], seg[1]), (seg[2], seg[3])):
                dmin = min(max(abs(b[0] - seg_end[0]), abs(b[3] - seg_end[0]))
                           for b in boxes)
                assert dmin <= lay["w"] + 1e-15

    def test_cramped_inner_aperture_rejected(self):
        """渲染可行性守卫：内圈半宽 a_min=(din+w)/2 与 n 无关（d_out 随 n
        闭式同增）——din ≤ 3w 时内圈孔径 <2w 拥挤即拒（coil_nfc 守卫语义
        在 din 参数化下的触发面）。"""
        bad = dict(NOM, din_um=5.0, w_um=10.0)
        with pytest.raises(ValueError, match="几何不可行"):
            _octagonal_spiral_layout(bad, BAND)

    def test_near_guard_rejects_underresolved_mesh(self):
        with pytest.raises(ValueError, match="#266"):
            _octagonal_spiral_layout(dict(NOM), BAND,
                                     mesh_resolution_mm=0.4)

    def test_um_params_via_to_mm_single_source(self):
        """μm 参数经 core.stackup.to_mm 单源换算（K9 helper 首个消费模板
        ——1μm 参数扰动必变几何，且换算比值=1e-3 精确）。"""
        lay = _octagonal_spiral_layout(dict(NOM, w_um=10.001), BAND)
        lay0 = _octagonal_spiral_layout(dict(NOM), BAND)
        # d_out 差 = 2n·Δw（n=5）=10·1nm=10nm
        assert lay["d_out"] - lay0["d_out"] == pytest.approx(10e-9, rel=1e-9)

    def test_ground_plane_flag_drives_sheet(self):
        lay = _octagonal_spiral_layout(dict(NOM, ground_plane=1), BAND)
        assert lay["ground"] is True
        lay0 = _octagonal_spiral_layout(dict(NOM), BAND)
        assert lay0["ground"] is False

    def test_render_script_wiring(self):
        """整脚本：μ m 几何字面在档、单端口 x 向激励、无底地板缺省分支。"""
        txt = render_script("octagonal_spiral", dict(NOM), BAND)
        assert '"x", excite=1' in txt
        assert 'LumpedPort(CSX, 1, 50.0' in txt
        assert "ground.AddBox" not in txt
        assert "octagonal_spiral_meta.json" in txt
        txt_g = render_script("octagonal_spiral", dict(NOM, ground_plane=1),
                              BAND)
        assert "ground.AddBox" in txt_g

    def test_geometry_spec_shape(self):
        spec = octagonal_spiral_geometry_spec(dict(NOM), {"er": 12.9})
        assert spec["template"] == "octagonal_spiral"
        assert len(spec["ports"]) == 1
        names = [b["name"] for b in spec["boxes"]]
        assert any("spiral" in n for n in names)
        assert spec["substrate"]["er"] == 12.9
        # geometry_spec 早分发（render_core 主入口同结果）
        assert geometry_spec("octagonal_spiral", dict(NOM))["template"] \
            == "octagonal_spiral"


# ─── 5) exec 几何审计（#212：渲染→exec→CSXCAD 实测，秒级零仿真）──────────────

class TestExecGeometryAudit:
    @pytest.fixture(scope="class")
    def scope_and_prims(self):
        return gh.load_geometry("octagonal_spiral")

    def test_single_conductor_network(self, scope_and_prims):
        """螺旋+切角阶梯+桥+焊盘+过孔+端口=单一金属连通分量（串联绕组
        口径——任何断链/短邻匝即红）。"""
        scope, prims = scope_and_prims
        conductors, labels = gh.conductor_labels(prims)
        metal_idx = [i for i, p in enumerate(conductors)
                     if p.kind == "Metal" and p.prop == "coil"]
        assert metal_idx, "无 coil 金属原语"
        assert len(set(labels[i] for i in metal_idx)) == 1, (
            "八角螺旋匝间断链/短路（连通分量 >1）")
        # 桥/焊盘/过孔与螺旋同分量
        for prop in ("bridge",):
            idx = [i for i, p in enumerate(conductors) if p.prop == prop]
            assert idx and all(labels[i] == labels[metal_idx[0]]
                               for i in idx)
        port_feed = gh.port_feed_point(scope["_port1"])
        assert gh.containing_labels(port_feed, conductors, labels), (
            "端口馈电点悬空")

    def test_ground_plane_isolated_component(self):
        """ground_plane=1：地板为独立分量（与螺旋不短路——镜像耦合属场
        维，DC 隔离是拓扑事实）。"""
        _scope, prims = gh.load_geometry(
            "octagonal_spiral", dict(NOM, ground_plane=1))
        conductors, labels = gh.conductor_labels(prims)
        coil_idx = [i for i, p in enumerate(conductors) if p.prop == "coil"]
        gnd_idx = [i for i, p in enumerate(conductors) if p.prop == "ground"]
        assert gnd_idx, "地板金属缺失"
        assert set(labels[i] for i in coil_idx).isdisjoint(
            set(labels[i] for i in gnd_idx)), "地板与螺旋短路"

    def test_no_near_coincident_mesh_lines(self, scope_and_prims):
        _, _ = scope_and_prims
        scope = scope_and_prims[0]
        for axis in ("x", "y", "z"):
            lines = gh.mesh_lines(scope, axis)
            diffs = np.diff(lines)
            assert bool(np.all(diffs > 1e-6)), f"{axis} 轴 <1µm 近重合线"

    def test_port_and_domain_wired(self, scope_and_prims):
        scope, _ = scope_and_prims
        dom_x, dom_y = gh.domain_half_extents(scope)
        assert dom_x == pytest.approx(scope["DOM_X"], rel=1e-12)
        assert dom_y == pytest.approx(scope["DOM_Y"], rel=1e-12)
        lay = _octagonal_spiral_layout(dict(NOM), BAND)
        px0, _py0, px1, _py1 = lay["port_box"]
        assert scope["_port1"].start[0] == pytest.approx(px0, rel=1e-12)
        assert scope["_port1"].stop[0] == pytest.approx(px1, rel=1e-12)


# ─── 6) fake 通道自洽（参数 → 闭式 L → 并联寄生谐振 S11）─────────────────────

def _zin_from_s11(f_ghz: np.ndarray, s11: np.ndarray,
                  z0: float = 50.0) -> np.ndarray:
    return z0 * (1.0 + s11) / (1.0 - s11)


class TestFakeSelfConsistency:
    def test_l_recovered_from_low_freq_zin(self):
        """低频段 Zin=50(1+S11)/(1−S11) → L=Im(Zin)/(2πf) 回收闭式 L
        （≤0.5%——寄生项 (f/SRF)² 二阶）。"""
        from rfauto.adapters.fake_adapter import _octagonal_spiral_sparams

        l_ref = spiral_inductance(_closed_geom(5, 80, 10, 5),
                                  "current_sheet")
        f = np.array([0.3, 0.5, 0.8])
        s = np.asarray(_octagonal_spiral_sparams(f))[:, 0, 0]
        z = _zin_from_s11(f, s)
        l_ext = np.imag(z) / (2.0 * math.pi * f * 1e9)
        assert np.allclose(l_ext, l_ref, rtol=5e-3), (l_ext, l_ref)

    def test_srf_from_zin_peak_matches_closed_form(self):
        """|Zin| 峰位=Im(Zin) 过零=1/(2π√(L·C_par))（≤1%）。"""
        from rfauto.adapters.fake_adapter import _octagonal_spiral_sparams

        geom = _closed_geom(5, 80, 10, 5)
        l_ref = spiral_inductance(geom, "current_sheet")
        c_ref = winding_parasitic_capacitance_f(geom, 3e-6, 12.9)
        srf_ref = 1.0 / (2.0 * math.pi * math.sqrt(l_ref * c_ref))
        f = np.linspace(6.0, 11.0, 501)
        s = np.asarray(_octagonal_spiral_sparams(f))[:, 0, 0]
        z = _zin_from_s11(f, s)
        f_peak = float(f[int(np.argmax(np.abs(z)))])
        assert f_peak * 1e9 == pytest.approx(srf_ref, rel=1e-2)

    def test_passivity(self):
        from rfauto.adapters.fake_adapter import _octagonal_spiral_sparams

        f = np.linspace(0.1, 20.0, 400)
        s = np.asarray(_octagonal_spiral_sparams(f))[:, 0, 0]
        assert bool(np.all(np.abs(s) <= 1.0 + 1e-9))

    def test_params_drive_response(self):
        """参数变化有真实响应：din 增 → L 增（d_avg 主项）；n 增 → L 增
        且 SRF 降（C 同增）。"""
        from rfauto.adapters.fake_adapter import _octagonal_spiral_sparams

        f = np.array([0.5])
        l_base = _zin_from_s11(f, np.asarray(
            _octagonal_spiral_sparams(f))[:, 0, 0])
        l_big = _zin_from_s11(f, np.asarray(
            _octagonal_spiral_sparams(f, din_um=120.0))[:, 0, 0])
        assert np.imag(l_big[0]) > np.imag(l_base[0])
        l_n6 = _zin_from_s11(f, np.asarray(
            _octagonal_spiral_sparams(f, n_turns=6))[:, 0, 0])
        assert np.imag(l_n6[0]) > np.imag(l_base[0])

    def test_fake_dispatch_via_adapter(self):
        """FakeAdapter 按名分发全路径（solve→network→L 回收）。"""
        import skrf

        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter(model_type="octagonal_spiral", n_ports=1,
                         freq_ghz=(0.1, 10.0, 201), f0_ghz=2.0)
        ad.connect({})
        ad.set_variables({})
        report = ad.solve("k11")
        assert report.success
        net = ad.get_sparams()
        assert isinstance(net, skrf.Network)
        f = np.asarray(net.frequency.f, dtype=float)
        s = np.asarray(net.s, dtype=complex)[:, 0, 0]
        z = _zin_from_s11(f, s)
        l_ext = np.imag(z) / (2.0 * math.pi * f)
        # 0.3–1GHz 段回收对闭式 ≤1%
        mask = (f >= 0.3e9) & (f <= 1.0e9)
        l_ref = spiral_inductance(_closed_geom(5, 80, 10, 5),
                                  "current_sheet")
        assert np.allclose(l_ext[mask], l_ref, rtol=1e-2)

    def test_variable_override_via_set_variables(self):
        """set_variables 同名同语义驱动（#154）：w_um 翻倍 → L 变化方向
        与闭式一致。"""
        from rfauto.adapters.fake_adapter import FakeAdapter

        l_ref_wide = spiral_inductance(_closed_geom(5, 80, 20.0, 5),
                                       "current_sheet")
        ad = FakeAdapter(model_type="octagonal_spiral", n_ports=1,
                         freq_ghz=(0.5, 0.5, 1), f0_ghz=2.0)
        ad.connect({})
        ad.set_variables({"w_um": 20.0})
        ad.solve("k11")
        s = np.asarray(ad.get_sparams().s, dtype=complex)[0, 0, 0]
        z = _zin_from_s11(np.array([0.5]), np.array([s]))
        # 寄生项 (f/SRF)² 二阶 ≈0.3%（0.5GHz vs SRF≈10GHz）→ 1% 宽化档
        assert np.imag(z[0]) == pytest.approx(
            2.0 * math.pi * 0.5e9 * l_ref_wide, rel=1e-2)


# ─── 7) spec 综合与注册面同步 ────────────────────────────────────────────────

class TestRegistration:
    def test_template_meta_and_nominal_registered(self):
        meta = template_meta("octagonal_spiral")
        assert meta["n_ports"] == 1 and meta["f0_ghz"] == 2.0
        assert set(meta["params"]) <= set(TEMPLATE_NOMINAL["octagonal_spiral"])
        assert TEMPLATE_META["octagonal_spiral"]["extraction"]

    def test_gallery_family_registered(self):
        """gallery 族登记全量覆盖（#231/#304 注册表消费者纪律）。"""
        from rfauto.service.gallery_service import FAMILY_LABELS, TEMPLATE_FAMILIES
        assert "octagonal_spiral" in TEMPLATE_FAMILIES
        assert TEMPLATE_FAMILIES["octagonal_spiral"] in FAMILY_LABELS

    def test_spec_registered_and_synthesizer(self):
        """TEMPLATE_SPECS 注册（w2b 全量覆盖钉同源）+ 综合入口回代自洽：
        l_target=4.1147nH → din≈80μm（与 NOMINAL 逐位同源）。"""
        from rfauto.models.template_spec import TEMPLATE_SPECS
        from rfauto.models.template_specs import bootstrap_template_specs

        bootstrap_template_specs()
        assert "octagonal_spiral" in TEMPLATE_SPECS.names()
        draft = TEMPLATE_SPECS.draft_recipe("octagonal_spiral",
                                            l_target_nh=4.1147)
        params = draft["params"]
        assert set(params) == set(TEMPLATE_NOMINAL["octagonal_spiral"])
        assert params["din_um"]["value"] == pytest.approx(80.0, abs=0.05)
        assert params["n_turns"]["value"] == 5

    def test_calc_key_registered(self):
        assert "octagonal_spiral_inductance" in CALCULATOR_REGISTRY.names()

    def test_meta_yaml_matches_src(self):
        """docs meta.yaml ↔ src 双向逐键（0aq 口径，元数据漂移即红）。"""
        import yaml

        data = yaml.safe_load(
            (REPO / "docs" / "templates" / "octagonal_spiral" / "meta.yaml")
            .read_text(encoding="utf-8"))
        assert set(data["params"]) == set(TEMPLATE_META["octagonal_spiral"]
                                          ["params"])
        for key, val in TEMPLATE_NOMINAL["octagonal_spiral"].items():
            assert float(data["nominal_params"][key]) == pytest.approx(
                float(val), rel=1e-9)

    def test_render_smoke_note_honest(self):
        """未冒烟/真机留登记如实声明（#122 不凑绿）。"""
        note = TEMPLATE_META["octagonal_spiral"]["smoke_note"]
        assert "未冒烟" in note and "留登记" in note
