"""coil_nfc NFC/WPC 线圈模板测试（df7+ C10b 残余，#212 离线审计制度化）。

零仿真（exec 截断于 FDTD.Run 之前，秒级）：渲染→exec 几何段→CSXCAD 实测
单连通/激励非零/最小间距，+ 闭式设计链往返（draft_recipe==NOMINAL 逐位）+
f0/Q 自洽 + fake 派发（参数驱动）+ 注册四件套 + core 数值参考门（(a) ≤5%/
(b) 机器钉与互易）。判据预声明 runs/df7_nfc/criteria.md（先声明后实测）。
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
    COIL_NFC_NOMINAL,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    _coil_nfc_layout,
    geometry_spec,
    render_script,
    template_meta,
)
from rfauto.core.nfc_coil import (
    CIRCLE_SIDES,
    MU0,
    CoilGeometry,
    coil_impedance,
    coil_mutual_inductance,
    coupling_coefficient,
    grover_mutual_coaxial_loops,
    loop_pair_mutual_numeric,
    polygon_loop_vertices,
    resonant_frequency,
    spiral_inductance,
    spiral_numeric_inductance,
    strip_gmd,
)
from tests.unit import _geometry_audit_helpers as gh

NOM = dict(COIL_NFC_NOMINAL)
BAND = (0.01356 - 0.25, 0.01356 + 0.25)


# ─── 1) 布局单源：几何/守卫 ──────────────────────────────────────────────────

class TestCoilNfcLayout:
    def test_turn_ladder_matches_core_d_in(self):
        """布局匝梯与 core CoilGeometry d_in 定义逐位一致（跨通道同语义）。"""
        lay = _coil_nfc_layout(NOM, BAND)
        a0, a_min = lay["a0"], lay["a_min"]
        assert a0 == pytest.approx(NOM["d_out_mm"] * 1e-3 / 2
                                   - NOM["w_mm"] * 1e-3 / 2, rel=1e-12)
        geom = CoilGeometry("square", float(NOM["n_turns"]),
                            NOM["d_out_mm"] * 1e-3, NOM["w_mm"] * 1e-3,
                            NOM["s_mm"] * 1e-3)
        assert a_min - lay["w"] / 2.0 == pytest.approx(geom.d_in_m / 2,
                                                       rel=1e-12)

    def test_port_span_is_gap(self):
        lay = _coil_nfc_layout(NOM, BAND)
        px0, py0, px1, py1 = lay["port_box"]
        assert px1 - px0 == pytest.approx(lay["w"], rel=1e-12)
        assert py1 - py0 == pytest.approx(NOM["gap_mm"] * 1e-3, rel=1e-12)

    def test_bridge_layer_clear_of_traces(self):
        """桥层（z=H+h_b）与螺旋层（z=H）z 向分离；竖直桥段确有跨接对象
        （桥不悬空、也不与被跨走线同层接触）。"""
        from rfauto.adapters.openems_templates import _coil_nfc_seg_box

        lay = _coil_nfc_layout(NOM, BAND)
        assert lay["h_bridge"] >= lay["base"]
        trace_boxes = [_coil_nfc_seg_box(*s, lay["w"], lay["h"])
                       for s in lay["segs"]]
        bridge_boxes = [_coil_nfc_seg_box(*s, lay["w"],
                                          lay["h"] + lay["h_bridge"])
                        for s in lay["bridge_segs"]]
        crossed = 0
        for tb in trace_boxes:
            for bb in bridge_boxes:
                ox = min(tb[3], bb[3]) - max(tb[0], bb[0])
                oy = min(tb[4], bb[4]) - max(tb[1], bb[1])
                if ox > 0 and oy > 0:
                    crossed += 1
                    assert bb[2] >= tb[5] - 1e-15   # 桥恒在走线之上
        assert crossed >= 2, "竖直桥段未跨过任何底边（跨接无效）"

    def test_infeasible_geometry_rejected(self):
        bad = dict(NOM, n_turns=40)
        with pytest.raises(ValueError, match="不可行"):
            _coil_nfc_layout(bad, BAND)
        with pytest.raises(ValueError, match="n_turns"):
            _coil_nfc_layout(dict(NOM, n_turns=0), BAND)

    def test_near_guard_rejects_underresolved_mesh(self):
        """#266 守卫：NEAR > min(s,gap)/3 显式拒绝（离线可复跑）。"""
        bad_mesh = NOM["s_mm"] * 1e-3 * 4 * 3 * 1e3 * 2  # base=8×s → NEAR=2s
        with pytest.raises(ValueError, match="#266"):
            _coil_nfc_layout(NOM, BAND, mesh_resolution_mm=bad_mesh)


# ─── 2) #212 离线审计（渲染→exec→CSXCAD 实测）───────────────────────────────

class TestOfflineAudit:
    def test_exec_primitives_and_ports(self):
        text = render_script("coil_nfc", NOM, BAND, mesh_resolution_mm=0.4)
        marker = text.find("# ── 求解 ──")
        head = text[:marker if marker >= 0 else text.index("FDTD.Run(")]
        scope: dict = {"__name__": "__main__",
                       "__file__": str(REPO / "_coil_nfc_audit_sim.py")}
        exec(compile(head, "coil_nfc_audit", "exec"), scope)
        prims = gh.extract_primitives(scope["CSX"])
        metal = [p for p in prims if p.kind == "Metal"]
        lumped = [p for p in prims if p.kind == "LumpedElement"]
        assert metal, "无金属原语"
        assert len([p for p in prims if p.kind == "Material"]) == 1
        assert lumped, "无端口集总元"
        # openEMS LumpedPort(编号 1) 的电阻片原语名固定 port_resist_1
        # （ports.py lbl_temp = prefix+'port_{}'+'_1'），非 "port1"
        assert lumped[0].prop == "port_resist_1", "集总元端口名非 port_resist_1"
        assert gh.off_mesh_planes(prims, scope) == []
        ports = gh.port_objects(scope)
        assert sorted(ports) == [1]
        port = ports[1]
        start = np.asarray(port.start, dtype=float)
        stop = np.asarray(port.stop, dtype=float)
        ext = np.abs(stop - start)
        assert ext[1] == pytest.approx(NOM["gap_mm"] * 1e-3, rel=1e-12)
        assert ext[2] > 1e-9  # 激励体积非零（#174）

    def test_single_conductor_network(self):
        """螺旋+跳桥+过孔+pad+端口集总元=单一连通分量（跨隙单通路定义）。"""
        _, prims = gh.load_geometry("coil_nfc")
        _, labels = gh.conductor_labels(prims)
        assert len(set(labels)) == 1, "导体网络必须单连通（跳桥断开即红）"

    def test_mesh_min_gap_guard(self):
        scope, _ = gh.load_geometry("coil_nfc")
        for axis in ("x", "y", "z"):
            lines = gh.mesh_lines(scope, axis)
            assert bool(np.all(np.diff(lines) > 1e-6)), f"{axis} 轴近重合线"

    def test_f0_fc_wired(self):
        scope, _ = gh.load_geometry("coil_nfc")
        f0 = float(TEMPLATE_META["coil_nfc"]["f0_ghz"])
        assert float(scope["F0"]) == pytest.approx(f0 * 1e9, rel=1e-12)
        assert float(scope["FC"]) == pytest.approx(0.25e9, rel=1e-12)

    def test_n_turns_truncation_drives_geometry(self):
        """n_turns 宣染取整：7→9.603（审计扰动口径）→9 匝，几何必变。"""
        _, base_prims = gh.load_geometry("coil_nfc")
        sig0 = gh.conductor_signature(base_prims)
        pert = dict(NOM, n_turns=7 * 1.37 + 0.013)
        _, prims1 = gh.load_geometry("coil_nfc", pert)
        assert gh.conductor_signature(prims1) != sig0


# ─── 3) 设计链往返 + f0/Q 自洽（判据 c）──────────────────────────────────────

class TestDesignChain:
    def test_draft_recipe_matches_nominal_bitwise(self):
        from rfauto.models.template_specs import TEMPLATE_SPECS

        assert "coil_nfc" in TEMPLATE_SPECS.names()
        draft = TEMPLATE_SPECS.draft_recipe("coil_nfc")
        params = {k: v["value"] for k, v in draft["params"].items()}
        assert set(params) == set(TEMPLATE_NOMINAL["coil_nfc"])
        for key, value in TEMPLATE_NOMINAL["coil_nfc"].items():
            assert params[key] == value, key

    def test_synthesizer_goal_f0_self_consistent(self):
        from rfauto.models.template_specs import TEMPLATE_SPECS

        result = TEMPLATE_SPECS.get("coil_nfc").synthesizer()
        f0_real = result.goal["f0_realized_mhz"]
        assert abs(f0_real - 13.56) / 13.56 <= 1e-4

    def test_resonant_frequency_closed_form(self):
        geom = CoilGeometry("square", float(NOM["n_turns"]),
                            NOM["d_out_mm"] * 1e-3, NOM["w_mm"] * 1e-3,
                            NOM["s_mm"] * 1e-3)
        l_h = spiral_inductance(geom, "current_sheet")
        c_f = 47e-12
        f0 = resonant_frequency(l_h, c_f)
        assert f0 == pytest.approx(1.0 / (2 * math.pi * math.sqrt(l_h * c_f)),
                                   rel=1e-15)
        assert abs(f0 - 13.56e6) / 13.56e6 <= 1e-4

    def test_loaded_q_report_honest(self):
        q_l = 35.0
        l_h = 2.931e-6
        f0 = resonant_frequency(l_h, 47e-12)
        omega = 2 * math.pi * f0
        r_s = omega * l_h / q_l
        report = coil_impedance(f0, l_h, r_s)
        assert report["q_unloaded"] == pytest.approx(q_l, rel=1e-12)
        assert report["q_loaded"] == pytest.approx(q_l, rel=1e-12)
        # 有载（互感耦合次级）：反射电阻抬高 Re(Z_in) → Q_loaded 降（物理方向）
        report_c = coil_impedance(f0, l_h, r_s, m_h=0.3 * l_h, l2_h=l_h,
                                  r2_ohm=2.0,
                                  z_load_ohm=complex(0.0, -omega * l_h))
        assert 0.0 < report_c["q_loaded"] < q_l
        report_r = coil_impedance(f0, l_h, r_s, m_h=0.3 * l_h, l2_h=l_h,
                                  r2_ohm=2.0, z_load_ohm=complex(50.0))
        assert 0.0 < report_r["q_loaded"] < q_l
        assert report["q_unloaded"] is not None
        # R≤0 → q=None（不虚构无穷，边界诚实）
        assert coil_impedance(f0, l_h, 0.0)["q_unloaded"] is None


# ─── 4) fake 派发（参数驱动真实响应，未标定口径如实）────────────────────────

class TestFakeDispatch:
    def test_fake_dip_at_f0_and_passive(self):
        from rfauto.adapters.fake_adapter import _coil_nfc_sparams

        freqs = np.linspace(0.0130, 0.0142, 201)
        s11 = np.abs(_coil_nfc_sparams(freqs)[:, 0, 0])
        assert bool(np.all(s11 <= 1.0 + 1e-12))
        i0 = int(np.argmin(s11))
        assert 20 * math.log10(s11[i0]) < -1.0    # 有可见 f0 谷
        assert abs(freqs[i0] * 1e3 - 13.56) <= (freqs[1] - freqs[0]) * 1e3

    def test_fake_param_response_direction(self):
        """几何变小 → L 变小 → f0 上移（dip 右移；参数驱动非常数裁判）。"""
        from rfauto.adapters.fake_adapter import _coil_nfc_sparams

        freqs = np.linspace(0.0130, 0.0180, 401)
        i_a = int(np.argmin(np.abs(_coil_nfc_sparams(freqs)[:, 0, 0])))
        i_b = int(np.argmin(np.abs(
            _coil_nfc_sparams(freqs, d_out_mm=30.0)[:, 0, 0])))
        assert freqs[i_b] > freqs[i_a]

    def test_fake_dispatch_via_adapter(self):
        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter(model_type="coil_nfc", n_ports=1,
                         freq_ghz=(0.0130, 0.0142, 121), f0_ghz=0.01356)
        ad.connect({})
        ad.solve("main_setup")
        net = ad.get_sparams()
        s11 = np.abs(net.s[:, 0, 0])
        i0 = int(np.argmin(s11))
        assert 20 * math.log10(s11[i0]) < -1.0
        f_axis = np.asarray(net.f)   # skrf Frequency.f 单位 Hz
        assert abs(f_axis[i0] / 1e6 - 13.56) <= 0.05


# ─── 5) 注册四件套 + meta.yaml（消费者钉）────────────────────────────────────

class TestRegistration:
    def test_template_meta_and_nominal_registered(self):
        assert "coil_nfc" in TEMPLATE_META
        assert "coil_nfc" in TEMPLATE_NOMINAL
        assert set(TEMPLATE_META["coil_nfc"]["params"]) <= set(
            TEMPLATE_NOMINAL["coil_nfc"])
        meta = template_meta("coil_nfc")
        assert meta["f0_ghz"] > 0 and meta["n_ports"] == 1

    def test_geometry_spec_ports_match_meta(self):
        spec = geometry_spec("coil_nfc", NOM,
                             {"er": NOM["er"], "h_mm": NOM["h_mm"],
                              "tan_d": NOM["tan_d"]})
        assert len(spec["ports"]) == TEMPLATE_META["coil_nfc"]["n_ports"]

    def test_meta_yaml_matches_src(self):
        import yaml

        path = REPO / "docs" / "templates" / "coil_nfc" / "meta.yaml"
        assert path.exists()
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["template"] == "coil_nfc"
        assert float(data["f0_ghz"]) == float(TEMPLATE_META["coil_nfc"]["f0_ghz"])
        assert int(data["n_ports"]) == TEMPLATE_META["coil_nfc"]["n_ports"]
        assert set(data["params"]) == set(TEMPLATE_META["coil_nfc"]["params"])
        assert set(data["nominal_params"]) == set(NOM)
        for key, value in NOM.items():
            assert float(data["nominal_params"][key]) == float(value), key

    def test_render_smoke_note_honest(self):
        """smoke_note 必须如实声明未冒烟（不得虚报真机状态）。"""
        note = str(TEMPLATE_META["coil_nfc"].get("smoke_note", ""))
        assert "未冒烟" in note


# ─── 6) core 数值参考门（criteria (a) ≤5% / (b) 机器钉+互易+椭圆对和）────────

def _geom(shape: str, n: int, d_out_mm: float) -> CoilGeometry:
    return CoilGeometry(shape, float(n), d_out_mm * 1e-3, 0.5e-3, 0.5e-3)


class TestNumericReferenceGates:
    def test_gmd_strip_identity(self):
        """Rosa e^(−3/2)：∫₀¹∫₀¹ln|x−x′|dx dx′=−3/2 数值证明（citation 免疫）。"""
        try:
            from scipy import integrate as si
        except ImportError:  # pragma: no cover
            pytest.skip("scipy 不可用")
        val, _ = si.dblquad(
            lambda x, xp: (math.log(abs(x - xp))
                           if abs(x - xp) > 1e-9 else 0.0),
            0.0, 1.0, 0.0, 1.0)
        # 容差 1e-6：对角带掩膜（|x−x′|≤1e-9 记 0）的有限带宽残差
        assert math.exp(val) == pytest.approx(math.exp(-1.5), rel=1e-6)
        assert strip_gmd(0.5e-3) == pytest.approx(0.5e-3 * math.exp(-1.5),
                                                  rel=1e-15)

    def test_segment_self_kernel_closed_form(self):
        """GMD 核自项 = 2D 数值积分（无借入系数，初等可证）。"""
        try:
            from scipy import integrate as si
        except ImportError:  # pragma: no cover
            pytest.skip("scipy 不可用")
        length, g = 0.03, strip_gmd(0.5e-3)
        closed = MU0 / (4 * math.pi) * 2 * (
            length * math.asinh(length / g)
            - math.hypot(length, g) + g)
        raw, _ = si.dblquad(
            lambda s, t: 1.0 / math.sqrt((s - t) ** 2 + g * g),
            0.0, length, 0.0, length)
        assert closed == pytest.approx(MU0 / (4 * math.pi) * raw, rel=1e-9)

    def test_gate_a_numeric_vs_mohan_le_5pct(self):
        """判据 (a)：square+octagon 必测（另两形状同门如实），≤5%。"""
        rows = []
        for n, d_mm in ((4, 25.0), (7, NOM["d_out_mm"]), (10, 50.0)):
            for shape in ("square", "octagon", "hexagon", "circle"):
                geom = _geom(shape, n, d_mm)
                if geom.d_in_m <= 0:
                    continue
                sides = 48 if shape == "circle" else CIRCLE_SIDES
                l_num = spiral_numeric_inductance(
                    geom, max_sub=8, n_gl=8, circle_sides=sides)["l_h"]
                l_cs = spiral_inductance(geom, "current_sheet")
                rows.append((shape, n, (l_num - l_cs) / l_cs))
        assert rows, "扫描无行"
        for shape, n, rel in rows:
            assert abs(rel) <= 0.05, f"{shape} n={n}: {rel * 100:+.2f}%"

    def test_gate_b_machinery_pin_and_reciprocity(self):
        """判据 (b) 机器钉：多边形离散 vs 椭圆精确式 ≤0.5%；互易逐位。"""
        r1 = r2 = 0.01
        dz = 0.005
        m_exact = grover_mutual_coaxial_loops(r1, r2, dz)
        va = polygon_loop_vertices("circle", r1)
        vb = polygon_loop_vertices("circle", r2)
        m_num = loop_pair_mutual_numeric(va, vb, dz_m=dz, max_sub=8)
        assert abs(m_num - m_exact) / m_exact <= 0.005
        m_rev = loop_pair_mutual_numeric(vb, va, dz_m=dz, max_sub=8)
        assert m_rev == pytest.approx(m_num, rel=1e-12)

    def test_gate_b_coil_level_elliptic_sum_cross_check(self):
        """判据 (b) 线圈级互证：ΣΣ 椭圆精确式（圆匝）vs 多边形求积 ≤1%
        （circle 几何同口径——两条独立数学路径：特殊函数 vs GL 求积）。

        多匝数值链可信度来源。方形单环平均半径近似不达标（criteria §b
        如实 FAIL 记档）；square-vs-circle 形状因子（c1≈1.27 同源量级）
        不进本门，由判据 (a) 对 Mohan 闭式覆盖。"""
        geom = CoilGeometry("circle", 7.0, NOM["d_out_mm"] * 1e-3,
                            NOM["w_mm"] * 1e-3, NOM["s_mm"] * 1e-3)
        pitch = geom.w_m + geom.s_m
        radii = [geom.d_out_m / 2 - geom.w_m / 2 - k * pitch
                 for k in range(int(geom.n_turns))]
        for dz in (0.010, 0.020, 0.040):
            m_ellip = math.fsum(
                grover_mutual_coaxial_loops(ra, rb, dz)
                for ra in radii for rb in radii)
            m_num = coil_mutual_inductance(geom, geom, dz, max_sub=8,
                                           circle_sides=64)
            assert abs(m_ellip - m_num) / m_num <= 0.01, f"dz={dz}"

    def test_coupling_k_report(self):
        """k 报告面：0<k<1 域守卫 + 随 dz 单调（dz 减小 → k 增）。"""
        geom = _geom("square", 7, NOM["d_out_mm"])
        l1 = spiral_inductance(geom, "current_sheet")
        ks = []
        for dz in (0.010, 0.020, 0.040):
            m_num = coil_mutual_inductance(geom, geom, dz, max_sub=8)
            ks.append(coupling_coefficient(l1, l1, m_num))
        assert all(0.0 < k < 1.0 for k in ks)
        assert ks == sorted(ks, reverse=True)   # dz 减小 → k 增
