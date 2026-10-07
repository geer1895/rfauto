"""ring_resonator 环形谐振器模板测试（F-A P2 前置段，#212 离线审计制度化）。

零仿真（exec 截断于 FDTD.Run 之前，秒级）：渲染→exec 几何段→CSXCAD 实测
间隙耦合三分量拓扑/缝内内部线/环孔空腔/端口贴板边 + HJ 设计链综合反解自洽
（ring_resonator_design_params()==TEMPLATE_NOMINAL 逐位/rtol 1e-9）+ f_n 闭
式往返 + 渲染守卫（#266 缝分辨/#347 测量面分离/r_in>0）+ 注册四件套 + docs
meta.yaml 一致性。

方案锚：研究扩充 F-A §2 M3——闭式
f_n ≈ n·c/(2π·r_mean·√εeff)；近似级别（直微带 HJ εeff、间隙电容耦合 v1、
无栅格化慢波补偿）如实登记于 RING_RESONATOR_META.smoke_note 与 docs meta。
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
    RING_RESONATOR_NOMINAL,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    _ring_resonator_layout,
    geometry_spec,
    render_script,
    ring_resonator_design_params,
    template_meta,
)
from tests.unit import _geometry_audit_helpers as gh
from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

NOM = dict(RING_RESONATOR_NOMINAL)
T = "ring_resonator"
F1 = 2.5
BAND = (F1 - 0.25, F1 + 0.25)
_C0 = 299792458.0


# ─── 1) HJ 设计链综合反解自洽（#1c：名义值禁手算捷径）────────────────────────

class TestDesignChainSelfConsistent:
    def test_design_params_reproduce_nominal(self):
        """ring_resonator_design_params() 缺省实参重算 == TEMPLATE_NOMINAL。

        字面量落表（避免模块导入期 IO）与单源重算函数的逐位一致性恒等式——
        名义漂移（改 nominal 不改链路或反之）即红。
        """
        design = ring_resonator_design_params()
        assert set(design) == set(NOM)
        for key in sorted(NOM):
            assert design[key] == pytest.approx(NOM[key], rel=1e-9), key

    def test_r_mean_closed_form_roundtrip(self):
        """独立重演设计链：w 名义档 → HJ εeff → c/(2πf1√εeff) == r_mean。"""
        from rfauto.core.synthesis import Stackup, forward_z0

        sub = Stackup.from_materials_yaml("rogers4350b_h0.508")
        _z0, eeff = forward_z0(NOM["w_mm"], F1, sub)
        r_mean = _C0 / (2.0 * math.pi * F1 * 1e9 * math.sqrt(eeff)) * 1e3
        assert r_mean == pytest.approx(NOM["r_mean_mm"], rel=1e-9)

    def test_feed_width_is_50ohm_hj(self):
        """馈线宽 50Ω HJ 反解回代（#1c 全名义值精算口径）。"""
        from rfauto.core.synthesis import Stackup, inverse_width

        sub = Stackup.from_materials_yaml("rogers4350b_h0.508")
        w_feed, z0, status = inverse_width(50.0, F1, sub)
        assert status == "ok"
        assert round(w_feed, 4) == pytest.approx(NOM["feed_w_mm"])
        assert z0 == pytest.approx(50.0, abs=0.5)

    def test_harmonic_ladder_closed_form(self):
        """闭式谐波梯：f_n = n·f1（n=1..3，基模闭环周长=λg）。"""
        from rfauto.core.synthesis import Stackup, forward_z0

        sub = Stackup.from_materials_yaml("rogers4350b_h0.508")
        _z0, eeff = forward_z0(NOM["w_mm"], F1, sub)
        circ_m = 2.0 * math.pi * NOM["r_mean_mm"] * 1e-3
        for n in (1, 2, 3):
            f_n = n * _C0 / (circ_m * math.sqrt(eeff)) / 1e9
            assert f_n == pytest.approx(n * F1, rel=1e-9), f"n={n}"

    def test_sensitivity_anchor(self):
        """设计敏感度锚：1µm r_mean ≈ 0.221MHz f1 漂移（提取批判读参考）。"""
        from rfauto.core.synthesis import Stackup, forward_z0

        sub = Stackup.from_materials_yaml("rogers4350b_h0.508")
        _z0, eeff = forward_z0(NOM["w_mm"], F1, sub)

        def _f1(r_mm: float) -> float:
            return (_C0 / (2.0 * math.pi * r_mm * 1e-3 * math.sqrt(eeff))
                    / 1e9)

        df_mhz = abs(_f1(NOM["r_mean_mm"] + 1e-3) - _f1(NOM["r_mean_mm"])) * 1e3
        assert df_mhz == pytest.approx(0.2212, abs=1e-3)


# ─── 2) 布局单源与守卫 ────────────────────────────────────────────────────────

class TestRingResonatorLayout:
    def test_layout_derived_quantities(self):
        """派生量：r_out/r_in/y_end/feed_len 与手算一致（layout 单源）。"""
        lay = _ring_resonator_layout(NOM)
        r_out = NOM["r_mean_mm"] + NOM["w_mm"] / 2
        assert lay["r_out"] == pytest.approx(r_out * 1e-3)
        assert lay["r_in"] == pytest.approx(
            (NOM["r_mean_mm"] - NOM["w_mm"] / 2) * 1e-3)
        assert lay["y_end"] == pytest.approx((r_out + NOM["gap_mm"]) * 1e-3)
        assert lay["feed_len"] == pytest.approx((60.0 - r_out
                                                 - NOM["gap_mm"]) * 1e-3)

    def test_guard_near_exceeds_gap_third(self):
        """#266 缝分辨守卫：NEAR=gap/3 越界（mesh 2.0mm 档 NEAR=0.5 > 0.133）拒绝渲染。"""
        with pytest.raises(ValueError, match="缝分辨守卫"):
            render_script(T, dict(NOM), BAND, mesh_resolution_mm=2.0)

    def test_guard_feed_len_short(self):
        """#347 测量面分离守卫：r_mean 巨大化使 feed_len < 42·NEAR 拒绝渲染。"""
        bad = dict(NOM, r_mean_mm=57.0)
        with pytest.raises(ValueError, match=r"测量面-激励分离守卫|馈线长非正"):
            render_script(T, bad, BAND, mesh_resolution_mm=0.4)

    def test_guard_ring_hole_positive(self):
        """几何守卫：环带线宽吞噬环孔（w/2 ≥ r_mean）拒绝渲染。"""
        bad = dict(NOM, w_mm=2.0 * NOM["r_mean_mm"])
        with pytest.raises(ValueError, match="环孔非正"):
            _ring_resonator_layout(bad)

    def test_auto_mesh_guard_requires_explicit_mesh(self):
        """缺省自动档（λ_sub/50，NEAR=0.285mm）触发缝分辨守卫——C3 族同口径
        （耦合缝类器件须显式 mesh_resolution_mm ≤ 4·gap/3），0.4mm 档过守卫。"""
        with pytest.raises(ValueError, match="缝分辨守卫"):
            render_script(T, dict(NOM), BAND, mesh_resolution_mm=0.0)
        text = render_script(T, dict(NOM), BAND, mesh_resolution_mm=0.4)
        assert "FDTD.Run(" in text


# ─── 3) #212 离线几何审计（exec 几何段 + CSXCAD 实测）────────────────────────

class TestOfflineGeometryAudit:
    def test_gap_coupled_three_components(self):
        """间隙耦合拓扑（定义性质）：馈1/环带/馈2 恰 3 个 DC 隔离分量。

        缝塌缩短路（分量数 <3 或端口同分量）= 非物理，即红（hairpin 族
        判据同向）；环带分量无直接端口（抽头耦合）。
        """
        scope, prims = gh.load_geometry(T)
        conductors, labels = gh.conductor_labels(prims)
        ports = gh.port_objects(scope)
        assert sorted(ports) == [1, 2]
        comp1 = gh.containing_labels(gh.port_feed_point(ports[1]),
                                     conductors, labels)
        comp2 = gh.containing_labels(gh.port_feed_point(ports[2]),
                                     conductors, labels)
        assert len(comp1) == 1 and len(comp2) == 1
        assert comp1 != comp2, "两馈线 DC 短路（缝塌缩）"
        all_labels = set(labels)
        assert len(all_labels) == 3, (
            f"导体分量数 {len(all_labels)} != 3（馈1/环带/馈2）")
        ring_label = (all_labels - comp1 - comp2)
        assert ring_label, "环带分量缺失"
        # 环带分量含金属原语（非悬空探针盒）
        ring_prims = [p for p, lb in zip(conductors, labels, strict=True)
                      if lb in ring_label and p.kind == "Metal"]
        assert ring_prims

    def test_rasterized_ring_band_geometry(self):
        """环带栅格化：金属包络=环带圆环，环孔内无金属。

        容差口径：逐行盒角径向越界 ≤ 半行距（行中心求弦、行端越出，
        ratrace 逐行栅格化同口径）——BASE 0.4mm 行 → tol=0.21mm。
        """
        _scope, prims = gh.load_geometry(T)
        lay = _ring_resonator_layout(NOM)
        r_out_m = lay["r_out"]
        r_in_m = lay["r_in"]
        _tol = 0.21e-3   # ≤ 半行距（0.4mm BASE 行）；盒角非圆弧的离散余量
        metal = [p for p in prims if p.kind == "Metal"]
        x_end = lay["fw"] / 2
        y_end = lay["y_end"]
        for p in metal:
            in_feed = (p.lo[0] >= -x_end - 1e-12 and p.hi[0] <= x_end + 1e-12
                       and (p.hi[1] <= -y_end + 1e-12
                            or p.lo[1] >= y_end - 1e-12))
            rr_max = max(math.hypot(x, y) for x in (p.lo[0], p.hi[0])
                         for y in (p.lo[1], p.hi[1]))
            assert in_feed or rr_max <= r_out_m + _tol, (
                f"金属原语越出环带包络 r={rr_max!r}")
            if not in_feed:
                rr_min = min(math.hypot(x, y) for x in (p.lo[0], p.hi[0])
                             for y in (p.lo[1], p.hi[1]))
                assert rr_min >= r_in_m - _tol, (
                    f"环孔内出现金属 r_min={rr_min!r}")
        # 环带外缘存在（栅格化覆盖到 |y|≈r_out 基点行；馈线延伸到 BOARD 不计）
        band = [p for p in metal
                if not (p.lo[0] >= -x_end - 1e-12 and p.hi[0] <= x_end + 1e-12
                        and (p.hi[1] <= -y_end + 1e-12
                             or p.lo[1] >= y_end - 1e-12))]
        assert max(p.hi[1] for p in band) == pytest.approx(r_out_m, abs=1e-9)
        assert min(p.lo[1] for p in band) == pytest.approx(-r_out_m, abs=1e-9)

    def test_gap_internal_grid_lines(self):
        """#311 缝内内部线 ≥1（缝缘线不算）：间隙电容耦合区必须被网格分辨。"""
        scope, _prims = gh.load_geometry(T)
        lay = _ring_resonator_layout(NOM)
        ls = np.asarray(scope["mesh"].GetLines("y"), dtype=float)
        for sign in (-1.0, 1.0):
            lo = sign * lay["y_end"]
            hi = sign * lay["r_out"]
            inside = ls[(ls > min(lo, hi) + 1e-9) & (ls < max(lo, hi) - 1e-9)]
            assert inside.size >= 1, f"缝区 ({lo},{hi})m 无内部网格线"

    def test_ports_on_board_edge_and_feeds_centered(self):
        """端口面贴 y=±BOARD（PML_8，#154 前节）+ 馈线沿 x=0 居中。"""
        scope, _prims = gh.load_geometry(T)
        ports = gh.port_objects(scope)
        board = float(scope["BOARD"])
        for number, port in ports.items():
            start = np.asarray(port.start, dtype=float)
            assert abs(abs(start[1]) - board) <= 1e-9, (
                f"port{number} 端口面未贴板边")
            assert int(port.prop_ny) == 1, "端口面须在 y 轴（prop_dir=y）"
        lay = _ring_resonator_layout(NOM)
        half_fw = lay["fw"] / 2
        for _port_no, port in ports.items():
            start = np.asarray(port.start, dtype=float)
            stop = np.asarray(port.stop, dtype=float)
            xs = sorted((start[0], stop[0]))
            assert xs[0] == pytest.approx(-half_fw, abs=1e-12)
            assert xs[1] == pytest.approx(half_fw, abs=1e-12)

    def test_mesh_min_gap_guard(self):
        """#152 最小线距（全轴 >1µm，无 CFL 塌缩线）。"""
        scope, _prims = gh.load_geometry(T)
        for axis in ("x", "y", "z"):
            ls = np.asarray(scope["mesh"].GetLines(axis), dtype=float)
            assert bool(np.all(np.diff(ls) > 1e-6)), f"{axis} 轴近重合线"

    def test_nominal_params_drive_conductor_geometry(self):
        """r_mean/w/gap/feed_w 四参各自扰动改变导体签名（声明即生效）。"""
        changed = gh.geometry_changing_params(T, list(TEMPLATE_META[T]["params"]))
        assert changed == set(TEMPLATE_META[T]["params"]), (
            f"未驱动几何的参数 {set(TEMPLATE_META[T]['params']) - changed}")

    def test_gap_perturbation_moves_feed_end(self):
        """gap 扰动移动馈端（抽头强度几何自由度单源验证）。"""
        _base_scope, base_prims = gh.load_geometry(T)
        _pert_scope, pert_prims = gh.load_geometry(
            T, dict(NOM, gap_mm=NOM["gap_mm"] * 1.5))
        assert gh.conductor_signature(base_prims) != \
            gh.conductor_signature(pert_prims)


# ─── 4) 注册四件套（#304）────────────────────────────────────────────────────

class TestRegistration:
    def test_registered_same_object_and_tail_position(self):
        from rfauto.adapters import openems_templates as ot

        assert ot.TEMPLATE_META[T] is ot.RING_RESONATOR_META
        assert ot.TEMPLATE_NOMINAL[T] is ot.RING_RESONATOR_NOMINAL
        assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)
        # 键集断言（AU-1B4，尾序槽位钉 [-N:] 退役）：本批注册居尾，其后
        # ME-7 pyramid_horn / ME-6 coax_waveguide_transition / M-5
        # varactor_bpf 依次尾部追加、J2FB ms_ring_patch（2026-09-30）注册于
        # ms 族段内不动本段——新批次尾部追加不改块内既有相对次序
        _TAIL_BLOCK = [T, "pyramid_horn", "coax_waveguide_transition",
                       "varactor_bpf"]
        keys = list(ot.TEMPLATE_META)
        assert set(_TAIL_BLOCK) <= set(keys)
        _it = iter(keys)  # 相对次序：块内名字按注册序出现（子序列）
        for _name in _TAIL_BLOCK:
            assert _name in _it, f"注册相对次序漂移：{_name}"
        assert ot._TEMPLATE_PORT_AXES[T] == ("y",)
        assert ot._TEMPLATE_RADIATOR[T] is False
        assert T in EXPECTED_TEMPLATES
        # 计数只与单源比对（#247 禁轨内自钉）
        assert len(ot.TEMPLATE_META) == len(EXPECTED_TEMPLATES)

    def test_template_meta_accessor(self):
        meta = template_meta(T)
        assert meta["template"] == T
        assert meta["n_ports"] == 2
        assert meta["f0_ghz"] == pytest.approx(F1)
        assert meta["nominal_params"] == RING_RESONATOR_NOMINAL

    def test_geometry_spec_ports_match_meta(self):
        spec = geometry_spec(T, dict(NOM))
        assert len(spec["ports"]) == int(TEMPLATE_META[T]["n_ports"]) == 2

    def test_smoke_note_honest(self):
        """smoke_note 必须如实声明未冒烟与 v1 近似级别（不虚报真机状态）。"""
        note = str(TEMPLATE_META[T].get("smoke_note", ""))
        assert "未冒烟" in note
        assert "近似级别" in note or "近似" in note


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
        assert "nominal_derivation" in data, "HJ 反解出处须入 meta.yaml"
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
