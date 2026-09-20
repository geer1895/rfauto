"""离线单测：MSL↔slotline 过渡 + Marchand 巴伦。

理论设计数（闭式/综合）、判据纯函数（合成数据）、布局校验、渲染脚本结构与
#212 几何审计（exec 头 → CSXCAD 实测）、抽头基线因子（独立来源 skrf 裁判）。
pyaedt/openEMS 求解一律不触发。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from rfauto.adapters.slotline_lumped_template import two_wave_beta_fit
from rfauto.adapters.slotline_transitions_template import (
    METAL_SEAM_OVERLAP,
    N_PROBE_STATIONS,
    PORT_INSET_BASE,
    RUN_MARKER,
    balun_ideal_baselines_db,
    marchand_balun_layout,
    msl_slot_transition_layout,
    render_marchand_balun,
    render_msl_slot_transition,
    tap_receive_factor_db,
    tap_source_factor_db,
)
from rfauto.core.slotline import slotline_closed_form
from rfauto.core.slotline_transitions import (
    BALUN_GATES,
    TRANSITION_GATES,
    balun_metrics,
    marchand_design,
    microstrip_open_end_delta_l_mm,
    transition_design,
    transition_metrics,
)

BAND = (2.25, 2.75)
F0 = 2.5
CF = slotline_closed_form(1.0, 1.524, 3.66, F0)


# ─────────────────────────────── 理论设计数 ───────────────────────────────
class TestDesignNumbers:
    def test_slot_anchor_matches_route_ab_design_point(self):
        d = transition_design(2.5, 1.524, 3.66, 1.0)
        assert d.z_slot_ohm == pytest.approx(110.92, abs=0.01)
        assert d.l_short_mm == pytest.approx(93.4624 / 4, abs=1e-3)
        assert d.eps_eff_slot == pytest.approx(1.6462, abs=1e-3)

    def test_msl_synthesis_and_stub_length(self):
        d = transition_design(2.5, 1.524, 3.66, 1.0)
        assert d.z_msl_ohm == pytest.approx(50.0, abs=0.5)
        assert d.w_msl_mm == pytest.approx(3.3439, abs=0.01)
        # 支节 = λg_m/4 + Δl_open（Hammerstad）；λg_m = λ0/√εeff
        import math

        lam_m = 299792458.0 / (2.5e9) / math.sqrt(d.eps_eff_msl) * 1e3
        assert d.dl_open_mm == pytest.approx(
            microstrip_open_end_delta_l_mm(d.w_msl_mm, 1.524, d.eps_eff_msl))
        assert d.l_stub_mm == pytest.approx(lam_m / 4 + d.dl_open_mm, abs=1e-9)

    def test_open_end_delta_l_formula_and_domain(self):
        # 手算锚：w/h=2.195、εeff=2.853 → Δl/h = 0.412·3.153·2.459/(2.595·3.008)
        dl = microstrip_open_end_delta_l_mm(3.3439, 1.524, 2.8530)
        assert dl == pytest.approx(0.6236, abs=0.002)
        with pytest.raises(ValueError):
            microstrip_open_end_delta_l_mm(1.0, 1.0, 0.2)

    def test_marchand_geometry_derivation(self):
        m = marchand_design(2.5, 1.524, 3.66, 1.0)
        assert m.d_center_mm == pytest.approx(m.w_msl_mm + 1.0, abs=1e-9)
        assert m.a1_mm == pytest.approx(m.d_center_mm / 2 - 0.5, abs=1e-9)
        assert m.a2_mm == pytest.approx(m.d_center_mm / 2 + 0.5, abs=1e-9)
        assert 0 < m.a1_mm < m.a2_mm

    def test_design_rejects_out_of_domain_slotline(self):
        # 示例 h=0.508 @2.5GHz：d/λ0<0.006 落闭式域外 → 显式拒绝不外推
        with pytest.raises(ValueError):
            transition_design(2.5, 0.508, 3.66, 1.0)

    def test_gates_predeclared_match_task(self):
        assert BALUN_GATES == {"amp_imbalance_db_le": 1.0, "rl_db_le": -10.0,
                               "isolation_db_le": -15.0, "s21_db_ge": -3.5}
        assert TRANSITION_GATES["band_max_s11_db_le"] == -10.0
        assert TRANSITION_GATES["excess_loss_db_f0_le"] == 1.0


# ─────────────────────────────── 判据纯函数（合成数据） ───────────────────────────────
class TestMetrics:
    f = np.linspace(2.0e9, 3.0e9, 201)

    def test_transition_metrics_ideal_passes(self):
        base = tap_receive_factor_db(110.92, 110.92)
        s21 = np.full(len(self.f), 10.0 ** (base / 20.0)) * np.exp(
            -1j * 2 * np.pi * self.f / 2.5e9)
        m = transition_metrics(self.f, np.zeros(len(self.f)), s21, BAND,
                               s21_ideal_db_f0=base)
        assert m["gates"]["band_max_s11_le_minus10db"] is True
        assert m["excess_loss_db_f0"] == pytest.approx(0.0, abs=1e-9)
        assert m["gates"]["excess_loss_f0_le_1db"] is True

    def test_transition_metrics_flags_excess_loss_and_rl(self):
        base = tap_receive_factor_db(110.92, 110.92)
        s21 = np.full(len(self.f), 10.0 ** ((base - 2.0) / 20.0))  # 超额 2dB
        s11 = np.full(len(self.f), 10.0 ** (-6.0 / 20.0))          # 回损 6dB
        m = transition_metrics(self.f, s11, s21, BAND, s21_ideal_db_f0=base)
        assert m["gates"]["band_max_s11_le_minus10db"] is False
        assert m["gates"]["excess_loss_f0_le_1db"] is False
        assert m["excess_loss_db_f0"] == pytest.approx(2.0, abs=1e-6)

    def test_balun_metrics_ideal_pushpull_and_splitter_signature(self):
        n = len(self.f)
        ideal = 10.0 ** (-3.0103 / 20.0)
        for s31_sign, expect_ph in ((+1.0, 0.0), (-1.0, 180.0)):
            # 两臂含共同传播相位：push-pull ⇒ 相位差 0/180（极性约定见模块 docstring）
            s21 = ideal * np.exp(-1j * 0.3) * np.ones(n, dtype=complex)
            s31 = s31_sign * ideal * np.exp(-1j * 0.3) * np.ones(n)
            m = balun_metrics(self.f, np.zeros(n, complex), s21, s31, None,
                              BAND)
            assert m["phase_diff_deg_f0"] == pytest.approx(expect_ph, abs=1e-6)
            assert m["amp_imbalance_db_f0"] == pytest.approx(0.0, abs=1e-9)
            assert m["gates"]["amp_imbalance_le_1db"] is True
            assert m["gates"]["rl_le_minus10db"] is True
            assert m["gates"]["s21_ge_minus3p5db"] is True

    def test_balun_metrics_isolation_gate_and_imbalance_fail(self):
        n = len(self.f)
        s21 = np.full(n, 10.0 ** (-3.0 / 20.0))
        s31 = np.full(n, 10.0 ** (-4.5 / 20.0))            # 不平衡 1.5dB > 1
        s23 = np.full(n, 10.0 ** (-12.0 / 20.0))           # 隔离 12dB < 15
        m = balun_metrics(self.f, np.zeros(n, complex), s21, s31, s23, BAND)
        assert m["gates"]["amp_imbalance_le_1db"] is False
        assert m["gates"]["isolation_le_minus15db"] is False
        assert m["band_max_s23_db"] == pytest.approx(-12.0, abs=1e-6)

    def test_band_mask_excludes_out_of_band_spikes(self):
        n = len(self.f)
        s11 = np.zeros(n)
        s11[0] = 10.0 ** (-3.0 / 20.0)                     # 2.0GHz 带外尖峰
        m = transition_metrics(self.f, s11, np.zeros(n, complex), BAND)
        assert m["gates"]["band_max_s11_le_minus10db"] is True


# ─────────────────────────────── 抽头基线（独立来源 skrf 裁判） ───────────────────────────────
class TestTapBaselines:
    def test_matched_case_is_two_thirds(self):
        rx = tap_receive_factor_db(110.92, 110.92)
        src = tap_source_factor_db(110.92, 110.92)
        expect = 20 * np.log10(2 / 3)
        assert rx == pytest.approx(expect)
        assert src == pytest.approx(expect)
        base = balun_ideal_baselines_db(110.92, 110.92)
        assert base["s23_baseline_db"] == pytest.approx(2 * expect)

    def test_skrf_shunt_section_reproduces_receive_factor(self):
        # 独立裁判：Z0 系统中并联 Z=Z0 的 ABCD=[[1,0],[1/Z,1]] → skrf a2s 转换
        # 给出波传输 |S21|=1+Γ=2/3（与解析推导不同源的数值路径）
        import skrf

        z0 = 110.92
        f = skrf.Frequency(2.5, 2.5, 1, unit="GHz")
        a = np.array([[[1.0, 0.0], [1.0 / z0, 1.0]]])
        net = skrf.Network(frequency=f, z0=z0, a=a)
        assert abs(net.s[0, 1, 0]) == pytest.approx(2 / 3, rel=1e-9)
        assert tap_receive_factor_db(z0, z0) == pytest.approx(
            20 * np.log10(abs(net.s[0, 1, 0])))

    def test_mismatched_r_changes_factor_and_rejects_bad_input(self):
        # R≠Z0（如 HFSS Zpv 105.76 vs 闭式 110.92）：Z_node=R∥Z0，Γ=(Z_node−Z0)/…
        r, z0 = 105.76, 110.92
        z_node = r * z0 / (r + z0)
        expect = 20 * np.log10(abs(1 + (z_node - z0) / (z_node + z0)))
        assert tap_receive_factor_db(r, z0) == pytest.approx(expect)
        with pytest.raises(ValueError):
            tap_receive_factor_db(0.0, 50.0)
        with pytest.raises(ValueError):
            tap_source_factor_db(50.0, -1.0)


# ─────────────────────────────── 布局校验 ───────────────────────────────
class TestLayouts:
    def test_transition_layout_numbers(self):
        lay = msl_slot_transition_layout({}, BAND)
        assert lay.r_slot_ohm == pytest.approx(CF.z0_ohm, abs=0.01)
        assert lay.l_short_m == pytest.approx(23.3656e-3, abs=1e-6)
        assert lay.dom_x_m == pytest.approx(
            lay.x_port_m + PORT_INSET_BASE * lay.base_m)
        assert lay.y_stub_tip_m == pytest.approx(
            lay.s_m / 2 + lay.l_stub_m, abs=1e-9)
        # H4 纪律：MSLPort 段起点出 PML_8（≈8·BASE）+ FeedShift 2.5·BASE 净空
        assert lay.y_p1_edge_m == pytest.approx(
            -lay.dom_y_m + 14.0 * lay.base_m, abs=1e-12)
        assert abs(lay.y_p1_edge_m) - 8.0 * lay.base_m             > 10 * lay.near_m + 2.5 * lay.base_m   # 激励面出 PML
        assert lay.y_p1_inner_m == pytest.approx(
            lay.y_p1_edge_m + 10e-3, abs=1e-12)
        assert len(lay.probe_x_m) == N_PROBE_STATIONS
        assert all(-0.9 * lay.x_port_m <= x <= -0.1 * lay.x_port_m
                   for x in lay.probe_x_m)

    def test_balun_layout_numbers_and_probes(self):
        lay = marchand_balun_layout({}, BAND)
        assert lay.d_center_m == pytest.approx(lay.w_msl_m + lay.s_m, abs=1e-12)
        assert 0 < lay.a1_m < lay.a2_m
        assert lay.y_stub_tip_m == pytest.approx(-(lay.a2_m + lay.l_stub_m),
                                                 abs=1e-9)
        assert lay.y_p1_edge_m == pytest.approx(
            lay.dom_y_m - 14.0 * lay.base_m, abs=1e-12)
        assert lay.y_p1_inner_m == pytest.approx(
            lay.y_p1_edge_m - 10e-3, abs=1e-12)
        assert set(lay.probe_a_x_m) == {-x for x in lay.probe_b_x_m}
        assert all(0.1 * lay.x_port_m <= x <= 0.9 * lay.x_port_m
                   for x in lay.probe_a_x_m)

    @pytest.mark.parametrize("bad", [
        {"h_mm": 0.0005}, {"msl_port_len_mm": 1.0}, {"er": 0.5},
        {"x_port_mm": -1.0}, {"dom_y_mm": 0.0},
    ])
    def test_layout_rejects_bad_inputs(self, bad):
        with pytest.raises(ValueError):
            msl_slot_transition_layout({**bad}, BAND)

    def test_layout_rejects_stub_into_boundary(self):
        # dom_y 压到支节端贴 MUR → 显式拒绝
        with pytest.raises(ValueError):
            msl_slot_transition_layout({"dom_y_mm": 20.0}, BAND)
        with pytest.raises(ValueError):
            marchand_balun_layout({"dom_y_mm": 22.0}, BAND)


# ─────────────────────────────── 渲染脚本结构 ───────────────────────────────
class TestRenderStructure:
    def test_transition_compiles_and_carries_contract(self):
        text = render_msl_slot_transition({}, BAND)
        compile(text, "gen", "exec")
        assert RUN_MARKER in text and text.index(RUN_MARKER) < text.index(
            "FDTD.Run(")
        assert '"PML_8", "PML_8", "MUR", "MUR", "MUR", "MUR"' in text
        assert text.count("LumpedPort(CSX,") == 1
        assert "MSLPort(CSX, port_nr=1" in text
        assert "excite=1.0," in text                       # 只有 P1 激励
        assert "RX_DB = " in text and "R_SLOT = " in text
        assert "two_wave_beta_fit" in text                 # 单源注入
        assert "gnd.AddBox((X_SH, -DOM_Y, 0.0)" in text    # 封口盒

    @pytest.mark.parametrize("ep", [1, 2, 3])
    def test_balun_compiles_excite_mapping(self, ep):
        text = render_marchand_balun({}, BAND, excite_port=ep)
        compile(text, "gen", "exec")
        assert f"EXCITE_PORT = {ep}" in text
        assert text.count("LumpedPort(CSX,") == 2
        assert "excite=1.0 if EXCITE_PORT == 1 else 0" in text
        assert "excite=1.0 if EXCITE_PORT == 2 else 0" in text
        assert "excite=1.0 if EXCITE_PORT == 3 else 0" in text
        assert "SEAM = " in text and "SRC_DB = " in text
        assert "vslot_a_" in text and "vslot_b_" in text

    def test_balun_rejects_bad_excite_port(self):
        with pytest.raises(ValueError):
            render_marchand_balun({}, BAND, excite_port=4)
        with pytest.raises(ValueError):
            render_msl_slot_transition({}, BAND, excite_port=2)


# ─────────────────────────────── #212 几何审计（exec 头 → CSXCAD） ───────────────────────────────
class TestGeometryAudit:
    """#212 离线审计：exec 脚本头（RUN_MARKER 前）→ CSXCAD 实测连通/尺寸。"""

    @staticmethod
    def _prims(csx, type_str: str):
        out = []
        for pi in range(csx.GetQtyProperties()):
            prop = csx.GetProperty(pi)
            if str(prop.GetTypeString()) != type_str:
                continue
            for prim in prop.GetAllPrimitives():
                s = np.array(prim.GetStart(), dtype=float)
                e = np.array(prim.GetStop(), dtype=float)
                out.append((prop.GetName(), np.minimum(s, e), np.maximum(s, e)))
        return out

    @pytest.fixture(scope="class")
    def sims(self, tmp_path_factory):
        pytest.importorskip("CSXCAD")
        tmp = tmp_path_factory.mktemp("slotline_trans_audit")
        out = {}
        for tag, text in (
                ("trans", render_msl_slot_transition({}, BAND)),
                ("balun", render_marchand_balun({}, BAND, excite_port=1))):
            head = text.split(RUN_MARKER)[0]
            g = {"__name__": "__main__", "__file__": str(tmp / f"{tag}.py")}
            exec(compile(head, tag, "exec"), g)
            out[tag] = g
        return out

    def test_transition_slot_gap_and_short_bridge(self, sims):
        g = sims["trans"]
        lay = msl_slot_transition_layout({}, BAND)
        gnd = [m for m in self._prims(g["CSX"], "Metal") if m[0] == "gnd_slot"]
        assert len(gnd) == 3
        w2 = lay.s_m / 2
        los = sorted(m[1][1] for m in gnd)   # 各盒 y 下缘
        his = sorted(m[2][1] for m in gnd)   # 各盒 y 上缘
        assert los[-1] == pytest.approx(+w2, abs=1e-12)   # 最高盒起于槽缘 +s/2
        assert his[0] == pytest.approx(-w2, abs=1e-12)    # 最低盒止于槽缘 -s/2（槽真断开）
        # 封口盒 C 全宽、起于 X_SH（短路臂端；以 x 起点=X_SH 唯一识别）
        box_c = [m for m in gnd
                 if m[1][0] == pytest.approx(lay.l_short_m, abs=1e-12)]
        assert len(box_c) == 1
        assert box_c[0][1][1] == pytest.approx(-lay.dom_y_m, abs=1e-12)
        assert box_c[0][2][1] == pytest.approx(lay.dom_y_m, abs=1e-12)
        # A/B 向 +x 搭接 SEAM（不关槽）
        for m in gnd:
            if m is not box_c[0]:
                assert m[2][0] == pytest.approx(
                    lay.l_short_m + METAL_SEAM_OVERLAP * lay.near_m, abs=1e-12)

    def test_transition_msl_stub_and_port(self, sims):
        g = sims["trans"]
        lay = msl_slot_transition_layout({}, BAND)
        msl = [m for m in self._prims(g["CSX"], "Metal") if m[0] == "msl_top"]
        assert len(msl) == 2
        # 支节端 + 馈线段（MSLPort 自画）在 y0−SEAM 搭接连通
        y_edges = sorted([m[1][1] for m in msl] + [m[2][1] for m in msl])
        assert y_edges[0] == pytest.approx(-lay.dom_y_m, abs=1e-12)
        assert y_edges[-1] == pytest.approx(lay.y_stub_tip_m, abs=1e-12)
        # 支节盒与馈线盒 y 向重叠（同金属连通，不靠精确共边）
        feed = [m for m in msl if m[2][1] == pytest.approx(lay.y_p1_inner_m)]
        stub = [m for m in msl
                if m[2][1] == pytest.approx(lay.y_stub_tip_m, abs=1e-12)]
        assert len(feed) == 1 and len(stub) == 1
        assert stub[0][1][1] < feed[0][2][1]     # 重叠非空
        port = g["_port2"]
        d = port.stop - port.start
        assert d[0] > 0 and d[1] == pytest.approx(lay.s_m) and d[2] > 0
        assert port.exc_ny == 1
        assert lay.r_slot_ohm == pytest.approx(g["_port2"].R)
        assert "port_excite_2" not in [
            g["CSX"].GetProperty(i).GetName()
            for i in range(g["CSX"].GetQtyProperties())]

    def test_balun_two_apertures_and_middle_strip(self, sims):
        g = sims["balun"]
        lay = marchand_balun_layout({}, BAND)
        gnd = [m for m in self._prims(g["CSX"], "Metal") if m[0] == "gnd_slot"]
        assert len(gnd) == 5

        def inside(x, y):
            hit = [n for n, lo, hi in gnd
                   if lo[0] - 1e-12 <= x <= hi[0] + 1e-12
                   and lo[1] - 1e-12 <= y <= hi[1] + 1e-12]
            return hit

        ym = 0.5 * (lay.a1_m + lay.a2_m)
        assert inside(0.0, ym) == []                    # 槽 1 开口
        assert inside(0.0, -ym) == []                   # 槽 2 开口
        assert inside(0.0, 0.0)                         # 中条
        assert inside(lay.l_short_m + 1e-3, -ym)        # 槽 2 封口（M4）
        assert inside(-lay.l_short_m - 1e-3, ym)        # 槽 1 封口（M5）
        assert inside(0.0, lay.dom_y_m - 1e-3)          # 外地（M1）
        # 五盒并集恰好两个开口：开口只允许出现在 (slot1)/(slot2) 采样线内
        for x in np.linspace(-lay.l_short_m + 1e-3, lay.dom_x_m - 5e-3, 25):
            assert inside(float(x), ym) == [] or float(x) < -lay.l_short_m
        # 端口盒：P2 跨槽 1、P3 跨槽 2（极性约定：均 y 递增）
        for pn, ylo, yhi in ((2, lay.a1_m, lay.a2_m),
                             (3, -lay.a2_m, -lay.a1_m)):
            port = g[f"_port{pn}"]
            assert port.start[1] == pytest.approx(ylo, abs=1e-12)
            assert port.stop[1] == pytest.approx(yhi, abs=1e-12)
            d = port.stop - port.start
            assert d[0] > 0 and d[2] > 0
            assert lay.r_slot_ohm == pytest.approx(port.R)

    def test_mesh_lines_pin_features(self, sims):
        for tag, lay in (("trans", msl_slot_transition_layout({}, BAND)),
                         ("balun", marchand_balun_layout({}, BAND))):
            mesh = sims[tag]["mesh"]
            lx = np.asarray(mesh.GetLines("x"), dtype=float)
            ly = np.asarray(mesh.GetLines("y"), dtype=float)

            def has(lines, v):
                return bool(np.min(np.abs(lines - v)) < 1e-12)

            assert has(lx, lay.l_short_m)
            assert has(lx, -lay.x_port_m) if tag == "trans" else (
                has(lx, lay.x_port_m) and has(lx, -lay.x_port_m))
            if tag == "trans":
                assert has(ly, lay.s_m / 2) and has(ly, -lay.s_m / 2)
            else:
                for v in (lay.a1_m, -lay.a1_m, lay.a2_m, -lay.a2_m):
                    assert has(ly, v)
            for px in lay.probe_x_m:
                assert has(lx, px)
            for lines in (lx, ly, np.asarray(mesh.GetLines("z"), float)):
                assert np.diff(lines).min() > 1e-6      # #152 近重合守卫

    def test_probes_count_and_two_wave_source_injected(self, sims):
        lay = marchand_balun_layout({}, BAND)
        assert len(lay.probe_a_x_m) == N_PROBE_STATIONS
        g = sims["balun"]
        names = [g["CSX"].GetProperty(i).GetName()
                 for i in range(g["CSX"].GetQtyProperties())]
        assert sum(1 for n in names if n.startswith("vslot_a_")) == N_PROBE_STATIONS
        assert sum(1 for n in names if n.startswith("vslot_b_")) == N_PROBE_STATIONS
        # 双行波拟合函数本身可对合成驻波工作（注入源健全性）
        x = np.linspace(-0.03, 0.03, 7)
        v = np.exp(-1j * 67.2 * x)[:, None] + 0.2 * np.exp(1j * 67.2 * x)[:, None]
        beta, _g, _r = two_wave_beta_fit(x, v, np.array([67.2]), span=0.5)
        assert beta[0] == pytest.approx(67.2, rel=1e-3)


# ───────────────────────── HFSS 仲裁分析核（合成数据，pyaedt 不 import） ─────────────────────────
class TestHfssAnalysis:
    """hfss_slotline_transitions.analyze_hfss_run：广义模态 S → 判据（纯函数）。"""

    @pytest.fixture(scope="class")
    def hfss_mod(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_slot_tr_hfss", ROOT / "scripts" / "hfss_slotline_transitions.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod

    f = np.linspace(2.0e9, 3.0e9, 101)

    def _gamma_rows(self, beta_slot, beta_msl, n_ports):
        g = np.zeros((len(self.f), n_ports), dtype=complex)
        g[:, 0] = 1j * (beta_msl * self.f / (2.5e9))
        g[:, 1] = 1j * (beta_slot * self.f / (2.5e9))
        if n_ports > 2:
            g[:, 2] = g[:, 1]
        return g

    def test_trans_perfect_line_passes_and_beta_exact(self, hfss_mod):
        cf = slotline_closed_form(1.0, 1.524, 3.66, 2.5)
        n = len(self.f)
        s = np.zeros((n, 2, 2), dtype=complex)
        ph = -cf.beta_rad_m * 23.3656e-3 * self.f / 2.5e9
        s[:, 1, 0] = np.exp(1j * ph)
        s[:, 0, 1] = np.exp(1j * ph)
        g = self._gamma_rows(cf.beta_rad_m, 2 * np.pi * 2.5e9 / 299792458.0
                             * np.sqrt(2.8530) * 2.5e9 / 2.5e9, 2)
        r = hfss_mod.analyze_hfss_run("trans", self.f, s, g)
        assert r["beta_slot_vs_cf_pct"] == pytest.approx(0.0, abs=1e-9)
        assert r["metrics"]["gates"]["band_max_s11_le_minus10db"] is True
        assert r["metrics"]["gates"]["excess_loss_f0_le_1db"] is True
        assert r["metrics"]["s21_ideal_baseline_db_f0"] == 0.0   # HFSS 无抽头基线

    def test_trans_lossy_and_shifted_beta_flags(self, hfss_mod):
        cf = slotline_closed_form(1.0, 1.524, 3.66, 2.5)
        n = len(self.f)
        s = np.zeros((n, 2, 2), dtype=complex)
        s[:, 1, 0] = 10.0 ** (-1.5 / 20.0)          # 超额损耗 1.5dB > 1
        s[:, 0, 0] = 10.0 ** (-8.0 / 20.0)          # 回损 8dB > −10
        s[:, 0, 1] = s[:, 1, 0]
        g = self._gamma_rows(cf.beta_rad_m * 1.03, 60.0, 2)  # β 偏 +3%
        r = hfss_mod.analyze_hfss_run("trans", self.f, s, g)
        assert r["metrics"]["gates"]["excess_loss_f0_le_1db"] is False
        assert r["metrics"]["gates"]["band_max_s11_le_minus10db"] is False
        assert r["beta_slot_vs_cf_pct"] == pytest.approx(3.0, abs=1e-6)
        assert r["metrics"]["gates"]["band_max_s11_le_minus10db"] is False

    def test_balun_pushpull_gates_and_isolation(self, hfss_mod):
        cf = slotline_closed_form(1.0, 1.524, 3.66, 2.5)
        n = len(self.f)
        ideal = 10.0 ** (-3.0103 / 20.0)
        s = np.zeros((n, 3, 3), dtype=complex)
        ph = -cf.beta_rad_m * 16e-3 * self.f / 2.5e9   # 共同臂相位
        s[:, 1, 0] = ideal * np.exp(1j * ph)
        s[:, 2, 0] = ideal * np.exp(1j * ph)            # 同相=推挽（约定）
        s[:, 0, 1] = s[:, 1, 0]
        s[:, 0, 2] = s[:, 2, 0]
        s[:, 2, 1] = 10.0 ** (-20.0 / 20.0)             # 隔离 20dB
        s[:, 1, 2] = s[:, 2, 1]
        g = self._gamma_rows(cf.beta_rad_m, 60.0, 3)
        r = hfss_mod.analyze_hfss_run("balun", self.f, s, g)
        m = r["metrics"]
        assert m["gates"]["amp_imbalance_le_1db"] is True
        assert m["gates"]["rl_le_minus10db"] is True
        assert m["gates"]["isolation_le_minus15db"] is True
        assert m["gates"]["s21_ge_minus3p5db"] is True
        assert m["phase_diff_deg_f0"] == pytest.approx(0.0, abs=1e-9)

    def test_balun_design_constants_are_literals_consistent_with_template(
            self, hfss_mod):
        # #218：HFSS 脚本几何字面与模板布局逐键一致（防两处漂移）
        lay = marchand_balun_layout({}, BAND)
        assert pytest.approx(lay.l_short_m * 1e3, abs=1e-3) == hfss_mod.X_SH
        assert pytest.approx(lay.w_msl_m * 1e3, abs=1e-3) == hfss_mod.W_MSL
        assert pytest.approx(lay.a1_m * 1e3, abs=1e-3) == hfss_mod.A1
        assert pytest.approx(lay.a2_m * 1e3, abs=1e-3) == hfss_mod.A2
        assert pytest.approx(lay.dom_x_m * 1e3, abs=1e-2) == hfss_mod.DOM_X
        lay_t = msl_slot_transition_layout({}, BAND)
        assert pytest.approx(lay_t.l_stub_m * 1e3, abs=1e-3) == hfss_mod.L_STUB
        assert pytest.approx(
            lay_t.y_stub_tip_m * 1e3, abs=1e-3) == hfss_mod.Y_TIP_TRANS


# ───────────────────────── smoke runner 结果解析（合成 CSV，零真机） ─────────────────────────
class TestRunnerParsing:
    """smoke_slotline_transitions.analyze_*：合成产物 → 判据（真数据落地前的解析门）。"""

    @pytest.fixture()
    def runner(self, tmp_path, monkeypatch):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_slot_tr_smoke", ROOT / "scripts" / "smoke_slotline_transitions.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "OUT", tmp_path)
        return mod, tmp_path

    @staticmethod
    def _write_csv(path, header, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(",".join(header) + "\n")
            for r in rows:
                fh.write(",".join(repr(float(v)) for v in r) + "\n")

    @staticmethod
    def _write_summary(tag_dir, **extra):
        import json

        base = {"ok": True, "rx_baseline_db": -3.5218, "s21_convention": "uf_ref",
                "beta_msl_hj_f0": 88.7, "beta_msl_f0": 88.7,
                "mesh_lines": [300, 250, 180], "r_slot_ohm": 110.92, "nrts": 1000}
        base.update(extra)
        tag_dir.mkdir(parents=True, exist_ok=True)
        (tag_dir / "summary.json").write_text(json.dumps(base), encoding="utf-8")

    def test_analyze_trans_ideal_curves_all_gates_pass(self, runner):
        mod, tmp = runner
        f = np.linspace(2.25e9, 2.75e9, 51)
        cf = slotline_closed_form(1.0, 1.524, 3.66, 2.5)
        rx = -3.5218
        s21 = (10.0 ** (rx / 20.0)
                            * np.exp(-1j * cf.beta_rad_m * 0.03)
                            * np.ones(len(f)))

        self._write_csv(tmp / "trans" / "sparams.csv",
                        ["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21",
                         "re_S21_resid", "im_S21_resid"],
                        [[x, 1e-6, 0.0, s21.real[k], s21.imag[k], 0.0, 0.0]
                         for k, x in enumerate(f)])
        self._write_csv(tmp / "trans" / "slotline_beta.csv",
                        ["freq_hz", "beta_slot_rad_m", "gamma_load_mag",
                         "fit_resid_rel", "beta_slot_cf_rad_m",
                         "beta_msl_rad_m", "beta_msl_hj_rad_m"],
                        [[x, cf.beta_rad_m * x / 2.5e9, 0.1, 1e-3,
                          cf.beta_rad_m * x / 2.5e9, 88.7, 88.7]
                         for x in f])
        self._write_summary(tmp / "trans")
        import argparse

        m = mod.analyze_trans(argparse.Namespace())
        assert all(m["gates"].values())
        assert m["excess_loss_db_f0"] == pytest.approx(0.0, abs=1e-6)
        assert abs(m["beta_vs_closed_pct"]) < 1e-6
        assert m["beta_msl_vs_hj_pct"] == pytest.approx(0.0, abs=1e-9)

    def test_analyze_trans_lossy_flags_gate(self, runner):
        mod, tmp = runner
        f = np.linspace(2.25e9, 2.75e9, 51)
        cf = slotline_closed_form(1.0, 1.524, 3.66, 2.5)
        s21 = (10.0 ** (-5.5 / 20.0)
                            * np.exp(-1j * cf.beta_rad_m * 0.03)
                            * np.ones(len(f)))

        s11 = np.full(len(f), 10.0 ** (-6.0 / 20.0))
        self._write_csv(tmp / "trans" / "sparams.csv",
                        ["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21",
                         "re_S21_resid", "im_S21_resid"],
                        [[x, s11[k], 0.0, s21.real[k], s21.imag[k], 0.0, 0.0]
                         for k, x in enumerate(f)])
        self._write_csv(tmp / "trans" / "slotline_beta.csv",
                        ["freq_hz", "beta_slot_rad_m", "gamma_load_mag",
                         "fit_resid_rel", "beta_slot_cf_rad_m",
                         "beta_msl_rad_m", "beta_msl_hj_rad_m"],
                        [[x, cf.beta_rad_m * 1.1 * x / 2.5e9, 0.1, 1e-3,
                          cf.beta_rad_m * x / 2.5e9, 88.7, 88.7] for x in f])
        self._write_summary(tmp / "trans")
        import argparse

        m = mod.analyze_trans(argparse.Namespace())
        assert m["gates"]["band_max_s11_le_minus10db"] is False
        assert m["gates"]["excess_loss_f0_le_1db"] is False

    def test_analyze_balun_ep2_isolation_and_beta(self, runner):
        mod, tmp = runner
        f = np.linspace(2.25e9, 2.75e9, 51)
        # ep1：理想推挽（两口同相 −3.01dB 修正后）
        ideal = 10.0 ** ((-3.0103 - 3.5218) / 20.0)   # 原始=修正后×|1+Γ|
        s21 = ideal * np.ones(len(f), dtype=complex)
        s31 = ideal * np.ones(len(f), dtype=complex)
        self._write_csv(tmp / "balun_ep1" / "sparams.csv",
                        ["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21",
                         "re_S31", "im_S31"],
                        [[x, 1e-6, 0.0, s21.real[k], s21.imag[k],
                          s31.real[k], s31.imag[k]] for k, x in enumerate(f)])
        self._write_csv(tmp / "balun_ep1" / "slotline_beta.csv",
                        ["freq_hz", "beta_a_rad_m", "beta_b_rad_m",
                         "gamma_a_mag", "gamma_b_mag", "beta_slot_cf_rad_m"],
                        [[x, 60.0, 60.0, 0.1, 0.1, 60.0] for x in f])
        self._write_summary(tmp / "balun_ep1", excite_port=1)
        # ep2：S23 原始 −30dB（双基线修正后 −23dB）
        s23 = 10.0 ** ((-30.0) / 20.0) * np.ones(len(f))
        self._write_csv(tmp / "balun_ep2" / "sparams.csv",
                        ["freq_hz", "re_S22", "im_S22", "re_S12", "im_S12",
                         "re_S23", "im_S23"],
                        [[x, -0.3, 0.0, 0.1, 0.0, s23.real[k], s23.imag[k]]
                         for k, x in enumerate(f)])
        self._write_csv(tmp / "balun_ep2" / "slotline_beta.csv",
                        ["freq_hz", "beta_a_rad_m", "beta_b_rad_m",
                         "gamma_a_mag", "gamma_b_mag", "beta_slot_cf_rad_m"],
                        [[x, 60.0, 60.0, 0.1, 0.1, 60.0] for x in f])
        self._write_summary(tmp / "balun_ep2", excite_port=2)
        import argparse

        m1 = mod.analyze_balun(1, argparse.Namespace())
        m2 = mod.analyze_balun(2, argparse.Namespace())
        assert m1["metrics"]["gates"]["amp_imbalance_le_1db"] is True
        assert m1["metrics"]["phase_diff_deg_f0"] == pytest.approx(0.0, abs=1e-6)
        assert m2["isolation"]["s23_corr_db_f0"] == pytest.approx(-23.0, abs=0.1)
        assert m2["isolation"]["gate_isolation_le_minus15db"] is True
        # 主 gates 装配口径（smoke main 同式）
        gates = {}
        gates.update({f"balun_{k}": v
                      for k, v in m1["metrics"]["gates"].items()})
        gates["balun_isolation_le_minus15db"] = m2["isolation"][
            "gate_isolation_le_minus15db"]
        assert all(gates.values())
