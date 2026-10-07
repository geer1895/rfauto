"""pyramid_horn 角锥喇叭模板测试（ME-7 离线段，#212 离线审计制度化）。

零仿真（exec 截断于 FDTD.Run 之前，秒级）：渲染→exec 几何段→CSXCAD 实测
单导体喇叭腔/模式端口截面/壁面站线入网/口径包络 + 综合闭式（core/
horn_synthesis，Orfanidis Ch.21 × Balanis Ch.13 双源）往返恒等（rtol 1e-6）
+ 教科书锚例（Ex21.5.1/21.5.2 独立复核钉）+ 扇形乘积口径恒等 + WR 联动
+ 渲染守卫（#266 阶梯步距/#174 空气域自动外推）+ 注册四件套 + docs meta.yaml
一致性。

方案锚：月度增强方案 §三 A 流 ME-7——标准增益
公式综合入 core + openEMS 全波验证（方向图/真机冒烟=Ph3 窗，本批零发射）；
近似级别（8 段阶梯化、口径面一阶 Fresnel 模型）如实登记于
PYRAMID_HORN_META.smoke_note 与 docs meta。
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
    PYRAMID_HORN_NOMINAL,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    _pyramid_horn_layout,
    geometry_spec,
    render_script,
    template_meta,
)
from rfauto.core.horn_synthesis import (
    SIGMA_E_GAIN_MAX,
    SIGMA_H_GAIN_MAX,
    aperture_efficiency,
    aperture_to_taper_sides,
    horn_gain_direct,
    synthesize_pyramid_horn,
    synthesize_pyramid_horn_ab,
)
from rfauto.core.rw_tables import wr_lookup
from tests.unit import _geometry_audit_helpers as gh
from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

NOM = dict(PYRAMID_HORN_NOMINAL)
T = "pyramid_horn"
F0_GHZ = 10.0
BAND = (F0_GHZ - 0.25, F0_GHZ + 0.25)
_C0 = 299792458.0
#: 教科书 λ=3cm 口径（Orfanidis 锚例频率约定）
_F_BOOK = _C0 / 0.03 / 1e9


# ─── 1) 综合闭式：往返恒等 + 教科书锚（#1c 双源）─────────────────────────────

class TestSynthesisRoundtrip:
    def test_roundtrip_identity_nominal(self):
        """synthesize(15dB)→horn_gain_direct==目标（往返恒等，rtol 1e-6）。"""
        design = synthesize_pyramid_horn(15.0, F0_GHZ, "WR-90")
        back = horn_gain_direct(design["a_mm"], design["b_mm"],
                                design["a1_mm"], design["b1_mm"],
                                design["l_mm"], F0_GHZ)
        assert back["gain_db"] == pytest.approx(15.0, rel=1e-6)
        assert design["gain_db_achieved"] == pytest.approx(15.0, rel=1e-6)

    @pytest.mark.parametrize("wr_name,f_ghz,gain_db", [
        ("WR-42", 22.0, 17.0),
        ("WR-90", 10.0, 15.0),
        ("WR-62", 15.0, 20.0),
        ("WR-284", 3.0, 14.0),
    ])
    def test_roundtrip_multi_band(self, wr_name, f_ghz, gain_db):
        """跨 WR 档往返恒等（闭式可逆性主判据，多频带扫描）。"""
        design = synthesize_pyramid_horn(gain_db, f_ghz, wr_name)
        back = horn_gain_direct(design["a_mm"], design["b_mm"],
                                design["a1_mm"], design["b1_mm"],
                                design["l_mm"], f_ghz)
        assert back["gain_db"] == pytest.approx(gain_db, rel=1e-6), wr_name

    def test_anchor_orfanidis_ex2152(self):
        """教科书锚（Ex21.5.2）：WR-90@λ=30mm、G=200、最优 σ。

        书值（hopt，σa=1.2593/σb=1.0246 档）：A=19.2383cm、B=15.2093cm、
        R=34.2740cm——双源核对独立复核（本仓 Fresnel 实现复算一致，4 位）。
        """
        design = synthesize_pyramid_horn(
            10.0 * math.log10(200.0), _F_BOOK, "WR-90",
            sigma_h=SIGMA_H_GAIN_MAX, sigma_e=SIGMA_E_GAIN_MAX)
        assert design["a1_mm"] / 10 == pytest.approx(19.2383, rel=1e-4)
        assert design["b1_mm"] / 10 == pytest.approx(15.2093, rel=1e-4)
        assert design["l_mm"] / 10 == pytest.approx(34.2740, rel=1e-4)
        assert design["gain_db_achieved"] == pytest.approx(
            10.0 * math.log10(200.0), rel=1e-6)

    def test_anchor_orfanidis_ex2151(self):
        """教科书锚（Ex21.5.1）：a=1λ、b=0.35λ、G=18.68dB、最优 σ。

        书值：A=4λ、B=2.9987λ、R=3.7834λ（hopt err=3.7e-11 档）。
        """
        design = synthesize_pyramid_horn_ab(
            18.68, _F_BOOK, 30.0, 10.5,
            sigma_h=SIGMA_H_GAIN_MAX, sigma_e=SIGMA_E_GAIN_MAX)
        assert design["a1_mm"] / 30 == pytest.approx(4.0, rel=1e-4)
        assert design["b1_mm"] / 30 == pytest.approx(2.9987, rel=1e-4)
        assert design["l_mm"] / 30 == pytest.approx(3.7834, rel=1e-4)


class TestSynthesisProperties:
    def test_balanis_sigma_efficiency_anchor(self):
        """口径效率锚：e(√1.5,1)≈0.514（Balanis 0.51 口径）、
        e(1.2593,1.0246)≈0.4895（Orfanidis (21.4.5) 0.49）。"""
        eff_bal = aperture_efficiency(math.sqrt(1.5), 1.0)
        assert eff_bal == pytest.approx(0.5144, abs=2e-3)
        eff_opt = aperture_efficiency(1.2593, 1.0246)
        assert eff_opt == pytest.approx(0.4895, abs=2e-3)

    def test_sigma_gain_max_is_numeric_argmax(self):
        """增益极大 σ 档=数值极值（1.2593/1.0246 非手抄恒等，扫描复算）。"""
        from scipy.optimize import minimize_scalar

        fa = lambda s: -s * _p1(s)     # noqa: E731
        fb = lambda s: -s * _p0(s)     # noqa: E731
        ra = minimize_scalar(fa, bounds=(0.5, 3.0), method="bounded",
                             options={"xatol": 1e-5})
        rb = minimize_scalar(fb, bounds=(0.5, 3.0), method="bounded",
                             options={"xatol": 1e-5})
        assert ra.x == pytest.approx(1.2593, abs=2e-3)
        assert rb.x == pytest.approx(1.0246, abs=2e-3)

    def test_product_relation_sectoral_sum(self):
        """扇形乘积口径：G_pyr==G_E_sec+G_H_sec+10log10(πλ²/32ab)（dB 和）。"""
        g = horn_gain_direct(NOM["a_mm"], NOM["b_mm"], NOM["a1_mm"],
                             NOM["b1_mm"], NOM["l_flare_mm"], F0_GHZ)
        rhs = (g["gain_e_sectoral_db"] + g["gain_h_sectoral_db"]
               + 10.0 * math.log10(g["product_factor"]))
        assert g["gain_db"] == pytest.approx(rhs, rel=1e-9)

    def test_delta_conditions_balanis(self):
        """Balanis 最优厚度条件：δ_H=3λ/8、δ_E=λ/4（σh²/4、σe²/4 换算）。"""
        g = horn_gain_direct(NOM["a_mm"], NOM["b_mm"], NOM["a1_mm"],
                             NOM["b1_mm"], NOM["l_flare_mm"], F0_GHZ)
        assert g["delta_h_over_lambda"] == pytest.approx(0.375, abs=1e-9)
        assert g["delta_e_over_lambda"] == pytest.approx(0.25, abs=1e-9)

    def test_gain_monotone_in_target(self):
        """目标增益单调 → 口径单调（综合方程良态性）。"""
        a1s = [synthesize_pyramid_horn(g, F0_GHZ, "WR-90")["a1_mm"]
               for g in (12.0, 15.0, 18.0)]
        assert a1s[0] < a1s[1] < a1s[2]

    def test_wr_linkage_and_guards(self):
        """WR 联动（消费 wr_lookup）：口径=WR 表值；越域显式拒绝。"""
        rec = wr_lookup("WR-90")
        design = synthesize_pyramid_horn(15.0, F0_GHZ, "wr_90")   # 容错归一
        assert design["a_mm"] == rec.a_mm == pytest.approx(22.86)
        assert design["b_mm"] == rec.b_mm == pytest.approx(10.16)
        assert design["wr_name"] == "WR-90"
        with pytest.raises(ValueError, match="单传播模域"):
            synthesize_pyramid_horn(15.0, 6.0, "WR-90")       # 低于截止
        with pytest.raises(ValueError, match="推荐带"):
            synthesize_pyramid_horn(15.0, 12.8, "WR-90")   # 带外（单模域内：12.4<f<2fc）
        with pytest.raises(ValueError, match="适用域"):
            synthesize_pyramid_horn(5.0, F0_GHZ, "WR-90")
        with pytest.raises(KeyError):
            synthesize_pyramid_horn(15.0, F0_GHZ, "WR-999")


def _p1(sq: float) -> float:
    from rfauto.core.horn_synthesis import _p1_norm_sq
    return _p1_norm_sq(sq)


def _p0(sb: float) -> float:
    from rfauto.core.horn_synthesis import _p0_norm_sq
    return _p0_norm_sq(sb)


# ─── 2) 名义单源 + 布局守卫 ──────────────────────────────────────────────────

class TestNominalAndLayout:
    def test_nominal_reproduces_synthesis(self):
        """TEMPLATE_NOMINAL == 导入期综合重算（字面落表无漂移，#1c）。"""
        design = synthesize_pyramid_horn(15.0, F0_GHZ, "WR-90")
        expected = {"a_mm": design["a_mm"], "b_mm": design["b_mm"],
                    "a1_mm": design["a1_mm"], "b1_mm": design["b1_mm"],
                    "l_feed_mm": 60.0, "l_flare_mm": design["l_mm"],
                    "er": 1.0, "h_mm": 0.0}
        assert set(expected) == set(NOM)
        for key, value in expected.items():
            assert NOM[key] == pytest.approx(value, rel=1e-9), key

    def test_layout_derived_quantities(self):
        """派生量：域/盒数/端口绑定序（绑定 a=第一横向轴=z=b_phys）。"""
        lay = _pyramid_horn_layout(dict(NOM), BAND, 0.6)
        assert lay["dom_y_mm"] == pytest.approx(NOM["l_feed_mm"])
        assert lay["dom_x_mm"] == pytest.approx(
            NOM["a1_mm"] / 2 + 11.5)
        assert lay["dom_z_mm"] == pytest.approx(NOM["b1_mm"] / 2 + 11.5)
        assert lay["base_mm"] == pytest.approx(0.6)
        # 4 馈电壁 + 8 段×4 壁 + 8 框×4（含喉部框面）= 68
        assert len(lay["boxes"]) == 68
        assert lay["port"]["a_bind_mm"] == pytest.approx(NOM["b_mm"])
        assert lay["port"]["b_bind_mm"] == pytest.approx(NOM["a_mm"])
        # 端口面纪律（审查轨 B P0-1 修正）：激励/探针两面均内移 16·BASE
        # 出 PML_8（该口径只属 WaveguidePort；#154 域边口径仅 MSLPort 成立）
        inset = 16.0 * lay["base_mm"]
        assert lay["port"]["start_mm"][1] == pytest.approx(
            -lay["dom_y_mm"] + inset)
        assert (lay["port"]["stop_mm"][1] - lay["port"]["start_mm"][1]
                ) == pytest.approx(lay["meas_len_mm"])
        assert lay["meas_len_mm"] >= inset  # 探针面更深出 PML

    def test_guard_stair_step_coarse_mesh(self):
        """#266 族守卫：阶梯步距 <4·NEAR（粗网格档）拒绝渲染。"""
        with pytest.raises(ValueError, match="阶梯步距"):
            _pyramid_horn_layout(dict(NOM), BAND, 8.0)

    def test_guard_aperture_must_exceed_guide(self):
        """口径不大于波导口拒绝渲染（无张开量，Fresnel 项病态）。"""
        with pytest.raises(ValueError, match="口径必须大于波导口"):
            _pyramid_horn_layout(dict(NOM, a1_mm=NOM["a_mm"]), BAND, 0.6)

    def test_feed_tube_auto_extends_air_margin(self):
        """#174 族口径侧空气域：l_flare 扰动时管长自动外推（单参扰动合法）。"""
        big = dict(NOM, l_flare_mm=NOM["l_flare_mm"] * 1.4)
        lay = _pyramid_horn_layout(big, BAND, 0.6)
        need = lay["lambda0_mm"] / 4.0 + 4.0
        assert lay["dom_y_mm"] == pytest.approx(big["l_flare_mm"] + need)
        # 空气域余量成立
        assert lay["dom_y_mm"] - lay["l_flare_mm"] >= need - 1e-9

    def test_taper_sides_trapezoids(self):
        """口面→四壁梯形侧面：角点/半张角/逐段插值与闭式几何一致。"""
        a, b, a1, b1 = NOM["a_mm"], NOM["b_mm"], NOM["a1_mm"], NOM["b1_mm"]
        fl = NOM["l_flare_mm"]
        sides = aperture_to_taper_sides(a, b, a1, b1, fl, 8)
        ew = sides["e_wall_plus"]
        assert ew["throat_edge_mm"][0] == pytest.approx([-a / 2, 0.0, b / 2])
        assert ew["aperture_edge_mm"][1] == pytest.approx([a1 / 2, fl, b1 / 2])
        hw = sides["h_wall_minus"]
        assert hw["throat_edge_mm"][0] == pytest.approx([-a / 2, 0.0, -b / 2])
        assert hw["aperture_edge_mm"][0] == pytest.approx(
            [-a1 / 2, fl, -b1 / 2])
        assert sides["flare_half_angle_h_deg"] == pytest.approx(
            math.degrees(math.atan2(a1 - a, 2 * fl)), rel=1e-9)
        segs = sides["segments"]
        assert len(segs) == 8
        assert segs[0]["y_lo_mm"] == 0.0
        assert segs[-1]["y_hi_mm"] == pytest.approx(fl)
        # 段半尺寸=段中截面线性插值
        assert segs[3]["x_half_mm"] == pytest.approx(
            a / 2 + (a1 - a) / 2 * 3.5 / 8)
        with pytest.raises(ValueError, match="n_segments"):
            aperture_to_taper_sides(a, b, a1, b1, fl, True)   # bool 拒收


# ─── 3) #212 离线几何审计（exec 几何段 + CSXCAD 实测）────────────────────────

class TestOfflineGeometryAudit:
    def test_single_conductor_cavity_and_mode_port(self):
        """喇叭腔=单导体连通分量（馈电壁+阶梯链+框面全闭合，缝漏即红）；
        RectWGPort 截面场端口（馈电点在腔内空气截面，FIELD_PORT 口径）：
        端口盒含 ≥1 金属原语（馈电段四壁）。"""
        scope, prims = gh.load_geometry(T)
        conductors, labels = gh.conductor_labels(prims)
        ports = gh.port_objects(scope)
        assert sorted(ports) == [1]
        metal_labels = {labels[i] for i, p in enumerate(conductors)
                        if p.kind == "Metal"}
        assert len(metal_labels) == 1, (
            f"喇叭壁连通分量数 {len(metal_labels)} != 1（阶梯链断开/框面缺失）")
        port = ports[1]
        lo = np.minimum(np.asarray(port.start, dtype=float),
                        np.asarray(port.stop, dtype=float))
        hi = np.maximum(np.asarray(port.start, dtype=float),
                        np.asarray(port.stop, dtype=float))
        inside = [p for p in prims if gh.is_conductor(p)
                  and bool(np.all(p.hi >= lo - 1e-9))
                  and bool(np.all(p.lo <= hi + 1e-9))]
        assert inside, "模式端口截面无导体（端口无效）"

    def test_port_te10_binding_and_kc(self):
        """TE10 绑定：mode=TE01（绑定参数序）、kc=π/a_phys、exc 沿 y。"""
        scope, _prims = gh.load_geometry(T)
        port = gh.port_objects(scope)[1]
        assert port.WG_mode == "TE01"
        assert port.kc == pytest.approx(math.pi / (NOM["a_mm"] * 1e-3),
                                        rel=1e-9)
        assert int(port.exc_ny) == 1
        assert int(getattr(port, "excite", 0)) == 1

    def test_wall_planes_on_mesh_lines(self):
        """全部金属壁零厚面恰在网格线上（#174 激励体积/面进网格铁律）。"""
        scope, prims = gh.load_geometry(T)
        assert gh.off_mesh_planes(prims, scope) == []

    def test_aperture_envelope_and_monotone_flare(self):
        """阶梯包络：口径侧最大 |x|/|z| =末段中截面半尺寸（半步距内到
        闭式口径），喉部/口径面位置正确。"""
        _scope, prims = gh.load_geometry(T)
        lay = _pyramid_horn_layout(dict(NOM), BAND, 0.6)
        # 口径段原语按几何挑（y≥0 的金属；馈电壁 y∈[−dom,0] 被排除）
        flare = [p for p in prims
                 if p.kind == "Metal" and p.lo[1] >= -1e-9]
        assert flare
        n = lay["n_seg"]
        xh_last = NOM["a_mm"] / 2 + (NOM["a1_mm"] - NOM["a_mm"]) / 2 * (
            (n - 0.5) / n)
        zh_last = NOM["b_mm"] / 2 + (NOM["b1_mm"] - NOM["b_mm"]) / 2 * (
            (n - 0.5) / n)
        assert max(abs(p.hi[0]) for p in flare) == pytest.approx(
            xh_last * 1e-3, rel=1e-9)
        assert max(abs(p.hi[2]) for p in flare) == pytest.approx(
            zh_last * 1e-3, rel=1e-9)
        # 半步距内逼近闭式口径（阶梯化近似幅度=步距/2）
        assert NOM["a1_mm"] / 2 - xh_last < (NOM["a1_mm"] - NOM["a_mm"]) / 2 / n
        # 喉部面 y=0、口径面 y=l_flare（末段框/壁止于口径面）
        assert min(p.lo[1] for p in flare) == pytest.approx(0.0, abs=1e-9)
        assert max(p.hi[1] for p in flare) == pytest.approx(
            NOM["l_flare_mm"] * 1e-3, rel=1e-9)

    def test_mesh_min_gap_guard(self):
        """#152 最小线距（全轴 >1µm，无 CFL 塌缩线）。"""
        scope, _prims = gh.load_geometry(T)
        for axis in ("x", "y", "z"):
            ls = np.asarray(scope["mesh"].GetLines(axis), dtype=float)
            assert bool(np.all(np.diff(ls) > 1e-6)), f"{axis} 轴近重合线"

    def test_nominal_params_drive_conductor_geometry(self):
        """六几何参各自扰动改变导体签名（声明即生效；er/h_mm 走材料豁免）。"""
        changed = gh.geometry_changing_params(T, list(TEMPLATE_META[T]["params"]))
        assert changed == set(TEMPLATE_META[T]["params"])

    def test_excitation_wiring(self):
        """激励以 meta f0 为中心；波导口缘/喉部面站线显式入网（口径侧
        站线由泛化审计的进网格检查全量覆盖）。"""
        scope, _prims = gh.load_geometry(T)
        ls = {ax: np.asarray(scope["mesh"].GetLines(ax), dtype=float)
              for ax in ("x", "y", "z")}
        assert float(np.min(np.abs(
            ls["x"] - NOM["a_mm"] / 2 * 1e-3))) <= 1e-6, "x=±a/2 未入网"
        assert float(np.min(np.abs(
            ls["z"] - NOM["b_mm"] / 2 * 1e-3))) <= 1e-6, "z=±b/2 未入网"
        assert float(np.min(np.abs(ls["y"] - 0.0))) <= 1e-6, "喉部面未入网"
        assert float(scope["F0"]) == pytest.approx(F0_GHZ * 1e9)


# ─── 4) 注册四件套（#304）────────────────────────────────────────────────────

class TestRegistration:
    def test_registered_same_object_and_tail_position(self):
        from rfauto.adapters import openems_templates as ot

        assert ot.TEMPLATE_META[T] is ot.PYRAMID_HORN_META
        assert ot.TEMPLATE_NOMINAL[T] is ot.PYRAMID_HORN_NOMINAL
        assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)
        # 键集断言（AU-1B4，尾序槽位钉 [-N:] 退役）：本批注册居尾，M-5
        # varactor_bpf（2026-09-27）尾部追加后退居其前，J2FB ms_ring_patch
        # （2026-09-30）注册于 ms 族段内不动本段——新批次尾部追加不改块内
        # 既有相对次序
        _TAIL_BLOCK = ["ring_resonator", T, "coax_waveguide_transition",
                       "varactor_bpf"]
        keys = list(ot.TEMPLATE_META)
        assert set(_TAIL_BLOCK) <= set(keys)
        _it = iter(keys)  # 相对次序：块内名字按注册序出现（子序列）
        for _name in _TAIL_BLOCK:
            assert _name in _it, f"注册相对次序漂移：{_name}"
        assert ot._TEMPLATE_PORT_AXES[T] == ("y",)
        assert ot._TEMPLATE_RADIATOR[T] is True
        assert T in ot.PYRAMID_HORN_TEMPLATES
        assert T in EXPECTED_TEMPLATES
        # 计数只与单源比对（#247 禁轨内自钉）
        assert len(ot.TEMPLATE_META) == len(EXPECTED_TEMPLATES)

    def test_template_meta_accessor(self):
        meta = template_meta(T)
        assert meta["template"] == T
        assert meta["n_ports"] == 1
        assert meta["f0_ghz"] == pytest.approx(F0_GHZ)
        assert meta["nominal_params"] == PYRAMID_HORN_NOMINAL

    def test_geometry_spec_ports_match_meta(self):
        spec = geometry_spec(T, dict(NOM))
        assert len(spec["ports"]) == int(TEMPLATE_META[T]["n_ports"]) == 1
        assert len(spec["boxes"]) == 5   # 预览口径：4 馈电壁 + 口径段包络

    def test_render_far_field_explicit_reject(self):
        """方向图/nf2ff=Ph3 窗：far_field 请求显式报错不静默降级。"""
        with pytest.raises((ValueError, TypeError)):
            render_script(T, dict(NOM), BAND, mesh_resolution_mm=0.6,
                          far_field=True)

    def test_smoke_note_honest(self):
        """smoke_note 必须如实声明未冒烟与 v1 近似级别（不虚报真机状态）。"""
        note = str(TEMPLATE_META[T].get("smoke_note", ""))
        assert "未冒烟" in note
        assert "近似级别" in note or "近似" in note
        assert "Ph3" in note


# ─── 5) docs meta.yaml 一致性 ────────────────────────────────────────────────

class TestDocsMetaYaml:
    def _data(self) -> dict:
        path = REPO / "docs" / "templates" / T / "meta.yaml"
        assert path.exists(), path
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_identity_and_key_sets(self):
        data = self._data()
        assert data["template"] == T
        assert float(data["f0_ghz"]) == pytest.approx(
            float(TEMPLATE_META[T]["f0_ghz"]))
        assert int(data["n_ports"]) == int(TEMPLATE_META[T]["n_ports"])
        assert set(data["params"]) == set(TEMPLATE_META[T]["params"])
        assert set(data["nominal_params"]) == set(TEMPLATE_NOMINAL[T])

    def test_nominal_values_match_src(self):
        data = self._data()
        for key, value in TEMPLATE_NOMINAL[T].items():
            assert float(data["nominal_params"][key]) == pytest.approx(
                value, rel=1e-9), key

    def test_derivation_and_smoke_note_declared(self):
        data = self._data()
        assert "nominal_derivation" in data, "综合链出处须入 meta.yaml"
        assert "smoke_note" in data
        assert "未冒烟" in data["smoke_note"]

    def test_yaml_no_half_width_hash_truncation(self):
        """#324 回归钉：plain scalar 内半角空格+'#' 截断——实读比对防静默注释化。"""
        raw = (REPO / "docs" / "templates" / T / "meta.yaml").read_text(
            encoding="utf-8")
        data = self._data()
        # 关键长字段实读非空（若 '#' 截断，行尾内容会被静默吞掉）
        assert len(str(data["mesh_note"])) > 50
        assert len(str(data["param_semantics"])) > 50
        assert "（#" in raw or "#152" in data["mesh_note"]
