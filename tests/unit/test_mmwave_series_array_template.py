"""mmwave_series_array 串馈毫米波阵模板测试（df7+ C10d，#212 离线审计制度化）。

零仿真（exec 截断于 FDTD.Run 之前，秒级）：渲染→exec 几何段→CSXCAD 实测
单连通/激励非零/最小间距 + 相位递推闭式自洽门（core/array_synthesis
series_feed_*：C2 极限锚/AF 峰位/衰减不变性/方向图积抽查/既有 array_factor
等价）+ 设计链往返（draft_recipe==NOMINAL 逐位）+ fake 派发（谷位=设计式
精确逆，未标定如实）+ 注册四件套 + 引擎预算预声明复核（#328 口径，
cells/dt/NrTS 以 exec 实测终网格复核预声明值——零发射）。判据预声明
runs/df7_c10d/criteria.md（先声明后实测）。
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
    MMWAVE_SERIES_META,
    MMWAVE_SERIES_NOMINAL,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    _mmwave_series_layout,
    array_elem_len_mm,
    array_elem_w_mm,
    array_line_w_mm,
    geometry_spec,
    mmwave_series_design_params,
    render_script,
    template_meta,
)
from rfauto.core.array_synthesis import (
    array_factor,
    patch_element_field,
    series_feed_array_factor,
    series_feed_beam_direction_cosine,
    series_feed_excitations,
    series_feed_progressive_phase,
    uniform_weights,
)
from tests.unit import _geometry_audit_helpers as gh

NOM = dict(MMWAVE_SERIES_NOMINAL)
F0 = float(MMWAVE_SERIES_META["f0_ghz"])
BAND = (F0 - 0.25, F0 + 0.25)
_AUDIT_MESH_MM = 0.2
_C_MM_GHZ = 299.792458


def _beta_g(feed_w_mm: float, f0_ghz: float = F0, er: float = 3.0,
            h_mm: float = 0.127) -> float:
    """HJ βg（与模板段同口径：k0·√εeff(HJ @feed_w)）。"""
    lam0 = _C_MM_GHZ / f0_ghz
    k0 = 2.0 * math.pi / lam0
    from rfauto.adapters.openems_templates import _ant2_eps_eff
    return k0 * math.sqrt(_ant2_eps_eff(feed_w_mm, f0_ghz, er, h_mm))


# ─── 1) 布局单源：几何/守卫/闭式自洽 ────────────────────────────────────────

class TestMmwaveSeriesLayout:
    def test_nominal_layout_single_source(self):
        lay = _mmwave_series_layout(NOM, BAND)
        n = int(NOM["n_elem"])
        length, s = NOM["elem_len_mm"], NOM["link_len_mm"]
        assert lay["n"] == n
        assert len(lay["boxes"]) == 2 * n              # N 贴片 + (N-1) 互联 + 端接 stub
        assert len(lay["elements_mm"]) == n
        # 链几何逐位：首元 −y 边=−DOM+margin、元距 d=L+s、链顶+端接 ≤ 域
        dom = lay["dom_mm"]
        y0 = -dom + NOM["feed_margin_mm"]
        assert lay["boxes"][0][3] == pytest.approx(y0, rel=1e-12)
        assert lay["pitch_mm"] == pytest.approx(length + s, rel=1e-12)
        # 负载盒挂在 stub 末段正下方（z=0..h，顶面触线）
        lb = lay["load_box"]
        assert lb[2] == 0.0 and lb[5] == pytest.approx(NOM["h_mm"], rel=1e-12)
        stub = lay["boxes"][-1]
        assert lb[4] == pytest.approx(stub[6], rel=1e-12)   # 同 y 末缘
        assert lb[1] > stub[3]                              # 在 stub 后半段

    def test_c2_limit_anchor_broadside(self):
        """C2 极限锚：s=λg/2=π/βg 时递推闭式 u0=0（同相侧射，C2 相位账连续）。"""
        bg = _beta_g(NOM["feed_w_mm"])
        s_lg2 = math.pi / bg            # λg/2（未舍入；舍入残差另见倾斜门）
        lay = _mmwave_series_layout(dict(NOM, link_len_mm=s_lg2), BAND)
        assert abs(lay["u0_pred"]) <= 1e-12

    def test_u0_closed_form_matches_core(self):
        """布局 u0_pred == core 闭式（同参逐位，跨文件单源）。"""
        lay = _mmwave_series_layout(NOM, BAND)
        u0 = series_feed_beam_direction_cosine(
            lay["pitch_mm"], lay["k0_rad_mm"], NOM["link_len_mm"],
            lay["beta_g_rad_mm"])
        assert lay["u0_pred"] == pytest.approx(u0, rel=1e-12)
        assert lay["u0_pred"] == pytest.approx(0.30, abs=2e-5)

    def test_guard_rejects_out_of_visible_range(self):
        """主波束落可见区外（小 s：Δφ mod 2π 大而 k0·d 小）显式 ValueError。"""
        with pytest.raises(ValueError, match="可见区"):
            _mmwave_series_layout(dict(NOM, link_len_mm=0.01), BAND)

    def test_guard_rejects_oversized_chain(self):
        with pytest.raises(ValueError, match="超域"):
            _mmwave_series_layout(dict(NOM, n_elem=40), BAND)
        with pytest.raises(ValueError, match="n_elem"):
            _mmwave_series_layout(dict(NOM, n_elem=1), BAND)

    def test_guard_rejects_coarse_mesh_266(self):
        """#266 族：NEAR > feed_w/3 拒渲染（线宽分辨守卫，离线可复跑）。"""
        bad = NOM["feed_w_mm"] * 3.0 * 4.0   # base=12·fw → NEAR=3·fw > fw/3
        with pytest.raises(ValueError, match="#266"):
            _mmwave_series_layout(NOM, BAND, mesh_resolution_mm=bad)

    def test_guard_rejects_347_probe_in_nearfield(self):
        """#347：|MeasPlaneShift−FeedShift| < 3.9·NEAR 拒渲染（危险带=
        margin/3 ∈ (6.1, 13.9)·NEAR，自动档 NEAR=fw/16 时 margin≈0.5 落带内）。"""
        with pytest.raises(ValueError, match="#347"):
            _mmwave_series_layout(dict(NOM, feed_margin_mm=0.5), BAND)


# ─── 2) #212 离线审计（渲染→exec→CSXCAD 实测）────────────────────────────────

class TestOfflineAudit:
    def test_exec_primitives_and_ports(self):
        text = render_script("mmwave_series_array", NOM, BAND,
                             mesh_resolution_mm=_AUDIT_MESH_MM)
        marker = text.find("# ── 求解 ──")
        head = text[:marker if marker >= 0 else text.index("FDTD.Run(")]
        scope: dict = {"__name__": "__main__",
                       "__file__": str(REPO / "_mmwave_audit_sim.py")}
        exec(compile(head, "mmwave_audit", "exec"), scope)
        prims = gh.extract_primitives(scope["CSX"])
        metal = [p for p in prims if p.kind == "Metal"]
        lumped = [p for p in prims if p.kind == "LumpedElement"]
        assert metal, "无金属原语"
        assert len([p for p in prims if p.kind == "Material"]) == 1
        assert lumped and lumped[0].prop == "load", "无端接集总元"
        assert gh.off_mesh_planes(prims, scope) == []
        ports = gh.port_objects(scope)
        assert sorted(ports) == [1]
        start = np.asarray(ports[1].start, dtype=float)
        stop = np.asarray(ports[1].stop, dtype=float)
        ext = np.abs(stop - start)
        # MSLPort 面贴 PML_8 域边（y=−DOM）
        assert abs(start[1]) == pytest.approx(float(scope["DOM_Y"]), abs=1e-12)
        assert int(np.sum(ext > 1e-9)) >= 2

    def test_single_conductor_network_with_termination(self):
        """串馈链+端接负载=单一连通分量（负载脱焊即双分量红）。"""
        _, prims = gh.load_geometry("mmwave_series_array")
        _, labels = gh.conductor_labels(prims)
        assert len(set(labels)) == 1, "导体网络必须单连通（链/端接断开即红）"

    def test_mesh_min_gap_guard(self):
        scope, _ = gh.load_geometry("mmwave_series_array")
        for axis in ("x", "y", "z"):
            lines = gh.mesh_lines(scope, axis)
            assert bool(np.all(np.diff(lines) > 1e-6)), f"{axis} 轴近重合线"

    def test_f0_fc_and_load_r_wired(self):
        scope, _ = gh.load_geometry("mmwave_series_array")
        assert float(scope["F0"]) == pytest.approx(F0 * 1e9, rel=1e-12)
        assert float(scope["FC"]) == pytest.approx(0.25e9, rel=1e-12)
        assert float(scope["LOAD_R"]) == pytest.approx(NOM["load_r_ohm"],
                                                       rel=1e-12)

    def test_perturbation_rendering_changes_geometry(self):
        """×1.37+0.013 扰动渲染全绿且几何必变（link/n_elem 双键抽查）。"""
        base_sig = gh.conductor_signature(
            gh.load_geometry("mmwave_series_array")[1])
        for key, value in (("link_len_mm", NOM["link_len_mm"] * 1.37 + 0.013),
                           ("n_elem", int(NOM["n_elem"] * 1.37 + 0.013)),
                           ("elem_w_mm", NOM["elem_w_mm"] * 1.37 + 0.013),
                           ("h_mm", NOM["h_mm"] * 1.37 + 0.013),
                           ("feed_margin_mm",
                            NOM["feed_margin_mm"] * 1.37 + 0.013)):
            _, prims = gh.load_geometry("mmwave_series_array",
                                        dict(NOM, **{key: value}))
            assert gh.conductor_signature(prims) != base_sig, key


# ─── 3) 相位递推闭式自洽门（criteria §a，写死数字）───────────────────────────

class TestPhaseRecursionGates:
    K0 = 2.0 * math.pi / (_C_MM_GHZ / F0)
    L = NOM["elem_len_mm"]
    S = NOM["link_len_mm"]
    FW = NOM["feed_w_mm"]
    BG = _beta_g(FW)

    def test_a1_c2_limit_anchor(self):
        s_lg2 = math.pi / self.BG
        u0 = series_feed_beam_direction_cosine(self.L + s_lg2, self.K0,
                                               s_lg2, self.BG)
        assert abs(u0) <= 1e-12

    def test_a2_af_peak_matches_closed_form(self):
        """递推权重 AF 峰位 == 闭式 u0（±1 栅格，u 栅距 2e-4；三点 s）。"""
        u = np.linspace(-1.0, 1.0, 10001)
        s_lg2 = math.pi / self.BG
        for s in (0.8 * s_lg2, self.S, 1.2 * s_lg2):
            d = self.L + s
            w = series_feed_excitations(4, d, self.K0, s, self.BG)
            af = np.abs(series_feed_array_factor(u, w, d, self.K0))
            u0c = series_feed_beam_direction_cosine(d, self.K0, s, self.BG)
            assert abs(u[int(af.argmax())] - u0c) <= 2e-4, s
            i0 = int(np.argmin(np.abs(u - u0c)))
            assert 20.0 * np.log10(af[i0] / af.max()) >= -1e-6, s   # a3 对齐

    def test_a4_attenuation_invariance(self):
        """行波衰减锥化不改波束指向（α∈{0,0.5,2.0} 峰位漂移 ≤2e-4）。"""
        u = np.linspace(-1.0, 1.0, 10001)
        d = self.L + self.S
        peaks = []
        for alpha in (0.0, 0.5, 2.0):
            w = series_feed_excitations(4, d, self.K0, self.S, self.BG,
                                        attenuation_np_per_length=alpha)
            af = np.abs(series_feed_array_factor(u, w, d, self.K0))
            peaks.append(u[int(af.argmax())])
        assert max(peaks) - min(peaks) <= 2e-4

    def test_a5_pattern_multiplication_spot_check(self):
        """方向图积抽查：patch_element_field × AF 主瓣方向与 AF 单独峰位一致。

        元主瓣天顶（θ=0）、阵因子峰 u0 → 积方向图 E 面（φ=90°，含链轴 y）
        峰位与 AF 峰位差 ≤0.5°（全波单元抽查的离线替代，criteria §a5）。
        """
        u = np.linspace(-1.0, 1.0, 20001)
        d = self.L + self.S
        w = series_feed_excitations(4, d, self.K0, self.S, self.BG)
        af = np.abs(series_feed_array_factor(u, w, d, self.K0))
        u_peak = u[int(af.argmax())]
        theta_deg = np.degrees(np.arcsin(u))       # φ=90°：u=sinθ
        elem = patch_element_field(theta_deg, 90.0, len_mm=self.L,
                                   width_mm=NOM["elem_w_mm"], freq_ghz=F0,
                                   h_mm=NOM["h_mm"], axis="y")
        total = np.abs(elem) * af
        theta_af = math.degrees(math.asin(u_peak))
        theta_total = theta_deg[int(total.argmax())]
        assert abs(theta_total - theta_af) <= 0.5

    def test_lossless_equivalence_with_array_factor(self):
        """等幅复权（α=0）与既有 array_factor（扫描相位路径）复数逐位一致
        ——两独立求值路径互证（复权不经 array_factor：其实化校验会丢弃
        虚部，series_feed_array_factor 文档钉）。"""
        u = np.linspace(-1.0, 1.0, 501)
        d = self.L + self.S
        w = series_feed_excitations(4, d, self.K0, self.S, self.BG)
        mine = series_feed_array_factor(u, w, d, self.K0)
        scan = series_feed_progressive_phase(self.S, self.BG) / (self.K0 * d)
        ref = array_factor(u, uniform_weights(4),
                           spacing_lambda=d * self.K0 / (2.0 * math.pi),
                           scan_direction_cosine=scan, normalize=False)
        assert float(np.abs(mine - ref).max()) <= 1e-10


# ─── 4) 设计链往返 + 栅瓣/域守卫（criteria §c）───────────────────────────────

class TestDesignChain:
    def test_design_params_match_nominal_bitwise(self):
        regenerated = mmwave_series_design_params()
        assert regenerated == NOM
        assert set(regenerated) == set(NOM)

    def test_draft_recipe_matches_nominal_bitwise(self):
        from rfauto.models.template_specs import TEMPLATE_SPECS

        assert "mmwave_series_array" in TEMPLATE_SPECS.names()
        draft = TEMPLATE_SPECS.draft_recipe("mmwave_series_array")
        params = {k: v["value"] for k, v in draft["params"].items()}
        assert params == NOM
        result = TEMPLATE_SPECS.get("mmwave_series_array").synthesizer()
        assert result.goal["u0_realized"] == pytest.approx(0.30, abs=1e-5)
        assert result.goal["beam_theta_deg"] == pytest.approx(
            math.degrees(math.asin(0.30)), abs=0.1)

    def test_tilt_sweep_designable(self):
        """倾斜扫描设计链可设计：u0∈{0.1,0.2,0.3} 全链有效且重建一致
        （重建容差 1e-4 = s 4 位舍入极限 ~3e-5 的宽松覆盖）。"""
        for u0 in (0.10, 0.20, 0.30):
            params = mmwave_series_design_params(tilt_u0=u0)
            bg = _beta_g(params["feed_w_mm"])
            k0 = 2.0 * math.pi / (_C_MM_GHZ / F0)
            d = params["elem_len_mm"] + params["link_len_mm"]
            assert series_feed_beam_direction_cosine(
                d, k0, params["link_len_mm"], bg) == pytest.approx(u0, abs=1e-4)

    def test_grating_design_rejected(self):
        """u0=0.5 设计点入栅瓣域 → 显式 ValueError（判据预声明 criteria §e）。"""
        with pytest.raises(ValueError, match="栅瓣"):
            mmwave_series_design_params(tilt_u0=0.5)

    def test_unit_sizing_closed_form(self):
        """单元尺寸=设计式复算（Balanis Ch.14 链零手抄）。"""
        w = array_elem_w_mm(F0, NOM["er"])
        length = array_elem_len_mm(F0, w, NOM["er"], NOM["h_mm"])
        assert round(w, 4) == NOM["elem_w_mm"]
        assert round(length, 4) == NOM["elem_len_mm"]
        assert round(array_line_w_mm(50.0, F0, NOM["er"], NOM["h_mm"]),
                     4) == NOM["feed_w_mm"]


# ─── 5) fake 派发（参数驱动真实响应，未标定口径如实）────────────────────────

class TestFakeDispatch:
    def test_fake_dip_at_design_inverse_and_passive(self):
        from rfauto.adapters.fake_adapter import _mmwave_series_sparams
        from rfauto.core.symbolic_fit import patch_resonance_hj_ghz

        freqs = np.linspace(76.0, 80.0, 401)
        s11 = np.abs(_mmwave_series_sparams(freqs, NOM)[:, 0, 0])
        assert bool(np.all(s11 <= 1.0 + 1e-12))
        i0 = int(np.argmin(s11))
        f_dip = freqs[i0]
        f_inv = patch_resonance_hj_ghz(NOM["elem_len_mm"], NOM["elem_w_mm"],
                                       NOM["er"], NOM["h_mm"])
        assert abs(f_dip - f_inv) <= (freqs[1] - freqs[0])   # 谷位=精确逆
        assert abs(f_inv - F0) / F0 <= 1e-3                  # 4 位舍入极限
        assert 20.0 * math.log10(s11[i0]) < -1.0             # 有可见吸收谷

    def test_fake_param_response_direction(self):
        """L 变小 → f0 上移（谷右移；参数驱动非常数裁判）。"""
        from rfauto.adapters.fake_adapter import _mmwave_series_sparams

        freqs = np.linspace(60.0, 100.0, 801)
        i_a = int(np.argmin(np.abs(
            _mmwave_series_sparams(freqs, NOM)[:, 0, 0])))
        i_b = int(np.argmin(np.abs(_mmwave_series_sparams(
            freqs, dict(NOM, elem_len_mm=NOM["elem_len_mm"] * 0.9))[:, 0, 0])))
        assert freqs[i_b] > freqs[i_a]

    def test_fake_dispatch_via_adapter(self):
        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter(model_type="mmwave_series_array", n_ports=1,
                         freq_ghz=(76.0, 80.0, 201), f0_ghz=F0)
        ad.connect({})
        ad.solve("main_setup")
        net = ad.get_sparams()
        assert net.s.shape[1:] == (1, 1)
        s11 = np.abs(net.s[:, 0, 0])
        f_axis = np.asarray(net.f)
        i0 = int(np.argmin(s11))
        assert 20.0 * math.log10(s11[i0]) < -1.0
        assert abs(f_axis[i0] / 1e9 - F0) <= 0.05

    def test_uncalibrated_note_honest(self):
        """未标定口径如实声明（docstring 注记不凑真机）。"""
        from rfauto.adapters.fake_adapter import _mmwave_series_sparams

        assert "未标定" in _mmwave_series_sparams.__doc__


# ─── 6) 注册四件套 + meta.yaml + 尾序契约（消费者钉）────────────────────────

class TestRegistration:
    def test_template_meta_and_nominal_registered(self):
        assert "mmwave_series_array" in TEMPLATE_META
        assert "mmwave_series_array" in TEMPLATE_NOMINAL
        assert set(TEMPLATE_META["mmwave_series_array"]["params"]) <= set(NOM)
        meta = template_meta("mmwave_series_array")
        assert meta["f0_ghz"] == pytest.approx(F0) and meta["n_ports"] == 1
        assert TEMPLATE_META["mmwave_series_array"] is MMWAVE_SERIES_META

    def test_geometry_spec_ports_match_meta(self):
        spec = geometry_spec("mmwave_series_array", NOM)
        assert len(spec["ports"]) == TEMPLATE_META["mmwave_series_array"]["n_ports"]
        assert spec["template"] == "mmwave_series_array"

    def test_meta_yaml_matches_src(self):
        import yaml

        path = REPO / "docs" / "templates" / "mmwave_series_array" / "meta.yaml"
        assert path.exists()
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["template"] == "mmwave_series_array"
        assert float(data["f0_ghz"]) == F0
        assert int(data["n_ports"]) == TEMPLATE_META["mmwave_series_array"]["n_ports"]
        assert set(data["params"]) == set(
            TEMPLATE_META["mmwave_series_array"]["params"])
        assert set(data["nominal_params"]) == set(NOM)
        for key, value in NOM.items():
            assert float(data["nominal_params"][key]) == float(value), key

    def test_specs_registered_with_components(self):
        from rfauto.models.template_specs import TEMPLATE_SPECS

        spec = TEMPLATE_SPECS.get("mmwave_series_array")
        assert spec.physics_roles == {
            "elem_len_mm": "resonator_length_mm",
            "elem_w_mm": "patch_width_mm",
            "feed_w_mm": "line_width_mm",
            "link_len_mm": "line_length_mm"}
        for kind in ("fake_model", "synthesizer", "render_script"):
            assert callable(TEMPLATE_SPECS.component("mmwave_series_array",
                                                     kind))

    def test_expected_templates_contains_and_counts(self):
        from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

        assert "mmwave_series_array" in EXPECTED_TEMPLATES
        assert len(EXPECTED_TEMPLATES) == 53
        assert len(TEMPLATE_META) == len(TEMPLATE_NOMINAL) == 53

    def test_tail_order_contract(self):
        """尾部追加契约（#247）：本批居尾 1，coil_nfc 退居尾 2，既有段不重排。"""
        keys = list(TEMPLATE_META)
        assert keys[-1] == "mmwave_series_array"
        assert keys[-2] == "coil_nfc"
        assert keys[-6:-2] == ["ms_patch", "ms_cross", "ms_jcross",
                               "ms_array_NxN"]
        assert keys[-10:-6] == ["slotline", "slotline_lumped",
                                "msl_slot_transition", "marchand_balun"]

    def test_render_smoke_note_honest(self):
        """smoke_note 必须如实声明未冒烟（不得虚报真机状态）。"""
        note = str(TEMPLATE_META["mmwave_series_array"].get("smoke_note", ""))
        assert "未冒烟" in note
        assert "零发射" in note


# ─── 7) 引擎预算预声明复核（criteria §d；#328 口径，零发射）─────────────────

class TestEngineBudgetDeclared:
    """预声明值（criteria §d）以 exec 实测终网格复核——发射前基线先钉。"""

    def test_cells_dt_nrts_match_declared(self):
        text = render_script("mmwave_series_array", NOM, (76.0, 81.0),
                             mesh_resolution_mm=0.1)
        marker = text.find("# ── 求解 ──")
        head = text[:marker if marker >= 0 else text.index("FDTD.Run(")]
        scope: dict = {"__name__": "__main__",
                       "__file__": str(REPO / "_mmwave_budget_sim.py")}
        exec(compile(head, "mmwave_budget", "exec"), scope)
        lines = {ax: gh.mesh_lines(scope, ax) for ax in ("x", "y", "z")}
        nx = lines["x"].size - 1
        ny = lines["y"].size - 1
        nz = lines["z"].size - 1
        cells = nx * ny * nz
        # 双档平滑（特征走廊 NEAR + 空气区 BASE）实测 5.26e6（446×786×15）
        assert 2.6e6 <= cells <= 1.1e7, f"cells={cells:.3g} 越预声明带"
        # Courant 3D（终网格最小格实算，#328）：dt = 1/(c·√(Σ 1/Δᵢ²))
        d_min = {ax: float(np.diff(lines[ax]).min()) for ax in ("x", "y", "z")}
        inv = sum(1.0 / d_min[ax] ** 2 for ax in ("x", "y", "z"))
        dt = 1.0 / (299792458.0 * math.sqrt(inv))
        assert 0.8 <= dt / 4.8e-14 <= 1.25, f"dt={dt:.3g}s 越预声明带"
        # 激励窗（FC=2.5GHz 脉冲 ~0.4ns + Q≈10 衰减 −60dB ~0.56ns）→ NrTS
        nrts = math.ceil(1.2e-9 / dt)
        assert 1.5e4 <= nrts <= 4.0e4, f"NrTS={nrts:.3g} 越预声明带"

    def test_termination_is_lumped_resistor_to_ground(self):
        """端接=shunt LumpedElement 到 z=0 PEC 地（ny=z、R=线 Z0 口径）。"""
        _, prims = gh.load_geometry("mmwave_series_array")
        load = [p for p in prims if p.kind == "LumpedElement"
                and p.prop == "load"]
        assert len(load) == 1
        ext = load[0].extent
        assert ext[2] > 1e-9 and load[0].lo[2] == pytest.approx(0.0, abs=1e-12)
