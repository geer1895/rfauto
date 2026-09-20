"""§10.3 C2 阵列族：1×4 corporate / 2×2 H-tree / 1×3 串馈 三模板单测（2026-09-15）。

方案行（阵列族｜阵列因子综合接口，接 D5 内核）。
- 注册态钉：ARRAY_META/ARRAY_NOMINAL 同对象入 TEMPLATE_META/TEMPLATE_NOMINAL；
  渲染四链路键（PORT_AXES/RADIATOR/render_fns/ff 元组）；注册四件套 docs
  meta.yaml ×3 / EXPECTED_TEMPLATES / fake 派发 _array_sparams / template_specs
  _register_patch_array（绝对计数钉在 test_template_geometry_audit，本文件只做
  集合断言防他轨并发计数竞争）。
- 闭式设计链（确定性内核）：单元 Balanis Ch.14 传输线模型（W=c/(2f)√(2/(εr+1))、
  L=c/(2f√εeff)−2ΔL），线宽/λ/4/λg/2 skrf HJ 精算（铁律 1c）——标称 = 设计链
  4 位舍入（互检）；独立裁判 = core/symbolic_fit.patch_resonance_hj_ghz +
  core/calculators.patch_length + core/synthesis.synthesize_patch。
- fake（设计口径裁判）：f0 = 设计式精确逆 + 一阶串联谐振；R 一阶常数
  （G1≈(W/λ0)²/90 边馈 + 插入馈 cos² 因子），S 参数不含方向图物理。
- #212 制度化离线审计：render → exec 几何段 → CSXCAD 实测（零厚面入网/端口
  激励非零/单连通分量/审计 ×1.37 扰动域），另加布局级零交叉/缺口触点判据。
- 方向图裁判 = 积定理闭式（openEMS 无官方阵列教程，官方基线仅 Simple Patch
  Antenna 单元口径；真机 nf2ff 对照 = scripts/smoke_array_anchor.py followUp）。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot
from tests.unit import _geometry_audit_helpers as gh

MESH_MM = 0.4
BAND = (5.55, 6.05)
F0 = 5.8
C_MM_GHZ = 299.792458
EXPECTED_PORT_COUNT = {t: 1 for t in ot.ARRAY_TEMPLATES}
N_ELEMENTS = {"patch_array_1x4": 4, "patch_array_2x2": 4, "patch_array_series": 3}


def _load(template: str, params: dict | None = None, mesh_mm: float = MESH_MM):
    """渲染 C2 模板 → exec 几何段 → (脚本作用域, 原语列表)（antenna2 同款）。"""
    resolved = dict(params if params is not None else ot.ARRAY_NOMINAL[template])
    text = ot.render_script(template, resolved, BAND, mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_array_audit_sim.py")}
    exec(compile(head, "array_audit", "exec"), scope)
    return scope, gh.extract_primitives(scope["CSX"])


# ─── 注册态 ──────────────────────────────────────────────────────────────────

def test_array_registered_in_registry():
    for t in ot.ARRAY_TEMPLATES:
        assert ot.TEMPLATE_META[t] is ot.ARRAY_META[t], t
        assert ot.TEMPLATE_NOMINAL[t] is ot.ARRAY_NOMINAL[t], t
        assert t in ot._TEMPLATE_PORT_AXES, t
        assert ot._TEMPLATE_RADIATOR[t] is True, t
        meta = ot.template_meta(t)
        assert meta["template"] == t
        assert meta["f0_ghz"] == F0
        assert meta["n_ports"] == 1
        assert meta["nominal_params"] == ot.ARRAY_NOMINAL[t]
        assert set(meta["params"]) == set(ot.ARRAY_NOMINAL[t]), t
        assert ot.array_meta(t)["nominal_params"] == ot.ARRAY_NOMINAL[t]
    # 渲染四链路键保持
    render_fns = {
        "patch_array_1x4": ot._patch_array_1x4_lines,
        "patch_array_2x2": ot._patch_array_2x2_lines,
        "patch_array_series": ot._patch_array_series_lines,
    }
    for t, fn in render_fns.items():
        assert callable(fn), t
    # 端口轴：1×4/2×2 底探针集总馈全 MUR（patch 口径）；串馈 MSLPort 在 y 板边
    assert ot._TEMPLATE_PORT_AXES["patch_array_1x4"] == ()
    assert ot._TEMPLATE_PORT_AXES["patch_array_2x2"] == ()
    assert ot._TEMPLATE_PORT_AXES["patch_array_series"] == ("y",)
    with pytest.raises(KeyError):
        ot.array_meta("patch")


def test_array_registration_surface_complete():
    import yaml

    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

    bootstrap_template_specs()
    assert set(ot.ARRAY_TEMPLATES) <= EXPECTED_TEMPLATES
    assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)
    for t in ot.ARRAY_TEMPLATES:
        data = yaml.safe_load(
            (REPO / "docs" / "templates" / t / "meta.yaml")
            .read_text(encoding="utf-8"))
        assert data["template"] == t
        assert float(data["f0_ghz"]) == pytest.approx(F0, rel=1e-12)
        assert int(data["n_ports"]) == 1
        assert list(data["params"]) == list(ot.ARRAY_META[t]["params"]), t
        assert data["nominal_params"] == ot.ARRAY_NOMINAL[t], t
        assert "smoke_note" in data, f"{t}: 真机冒烟判读须入 meta.yaml"
        spec = TEMPLATE_SPECS.get(t)
        assert spec.meta["n_ports"] == 1
        assert callable(TEMPLATE_SPECS.component(t, "render_script"))
        assert callable(TEMPLATE_SPECS.component(t, "fake_model"))
        assert spec.hfss_plugin is None
        # 综合入口：全参数设计链再生 == NOMINAL（4 位舍入口径）
        draft = TEMPLATE_SPECS.draft_recipe(t, f0_ghz=F0)
        got = {k: v["value"] for k, v in draft["params"].items()}
        assert got == ot.ARRAY_NOMINAL[t], t
        # UI 预览：单端口 + 单元数（4/4/3）+ 接地阵保留基板/整板地盒
        spec_geo = ot.geometry_spec(t, dict(ot.ARRAY_NOMINAL[t]))
        assert len(spec_geo["ports"]) == 1, t
        assert len(spec_geo["elements"]) == N_ELEMENTS[t], t
        names = [b["name"] for b in spec_geo["boxes"]]
        assert "substrate" in names and "ground" in names, t
    roles = dict(TEMPLATE_SPECS.get("patch_array_1x4").physics_roles)
    assert roles["elem_len_mm"] == "resonator_length_mm"
    assert roles["elem_feed_mm"] == "feed_offset_mm"
    assert roles["q_len_mm"] == "line_length_mm"
    # spacing 无词表角色不映射（antenna2 同口径：只映射语义确定的键）
    assert "spacing_mm" not in roles


# ─── 闭式设计链（确定性内核；独立裁判互证）────────────────────────────────────

def test_nominal_matches_design_chain():
    for t in ot.ARRAY_TEMPLATES:
        assert ot.array_design_params(t, F0) == ot.ARRAY_NOMINAL[t], t


def test_design_chain_against_independent_referees():
    """独立裁判三方互证：symbolic_fit HJ 逆式 / calculators patch_length /
    synthesis.synthesize_patch（数字全部出自确定性内核）。"""
    from rfauto.core.calculators import CALCULATOR_REGISTRY
    from rfauto.core.symbolic_fit import patch_resonance_hj_ghz
    from rfauto.core.synthesis import Stackup, inverse_width, synthesize_patch

    nom1 = ot.ARRAY_NOMINAL["patch_array_1x4"]
    # ① 设计式 → 独立 HJ 谐振裁判（舍入级一致）
    assert patch_resonance_hj_ghz(nom1["elem_len_mm"], nom1["elem_w_mm"],
                                  3.66, 0.508) == pytest.approx(F0, rel=1e-4)
    # ② patch_length 计算器（同公式独立实现）逐位一致
    calc = CALCULATOR_REGISTRY.get("patch_length").func(
        f0_ghz=F0, epsilon_r=3.66, h_mm=0.508)
    assert calc["patch_w_mm"] == nom1["elem_w_mm"]
    assert calc["patch_l_mm"] == nom1["elem_len_mm"]
    # ③ synthesize_patch（core/synthesis 主入口，2 位舍入）±0.02mm
    sp = synthesize_patch(F0, 3.66, 0.508).params
    assert abs(sp["patch_len_mm"] - nom1["elem_len_mm"]) <= 0.02
    assert abs(sp["patch_w_mm"] - nom1["elem_w_mm"]) <= 0.02
    # ④ 线宽/λ 段：HJ 直调复算（先舍入再取 εeff 的口径与设计链一致）
    stackup = Stackup(name="c2_ref", epsilon_r=3.66, thickness_mm=0.508)
    fw, _, _ = inverse_width(50.0, F0, stackup)
    qw, _, _ = inverse_width(50.0 * np.sqrt(2), F0, stackup)
    assert round(fw, 4) == nom1["feed_w_mm"]
    assert round(qw, 4) == nom1["q_w_mm"]
    assert round(ot.array_quarter_len_mm(nom1["q_w_mm"], F0), 4) == nom1["q_len_mm"]
    assert round(ot.array_half_guided_len_mm(nom1["feed_w_mm"], F0),
                 4) == ot.ARRAY_NOMINAL["patch_array_series"]["link_len_mm"]
    # ⑤ εeff 合理域与单元间距尺度
    eps = ot._ant2_eps_eff(nom1["q_w_mm"], F0, 3.66, 0.508)
    assert 1.0 < eps < 3.66
    lam0 = C_MM_GHZ / F0
    assert nom1["spacing_mm"] == pytest.approx(0.484 * lam0, abs=1e-4)
    assert nom1["elem_feed_mm"] == pytest.approx(0.3 * nom1["elem_len_mm"], abs=1e-4)


def test_design_chain_guards():
    with pytest.raises(KeyError):
        ot.array_design_params("nope")
    with pytest.raises(ValueError):
        ot.array_elem_w_mm(0.0)
    with pytest.raises(ValueError):
        ot.array_elem_len_mm(-1.0, 16.9311)
    with pytest.raises(ValueError):
        ot.array_line_w_mm(50.0, 0.0)
    with pytest.raises(ValueError):
        ot._arr_layout("nope", {})


# ─── fake 派发（设计口径裁判；R/Q 一阶常数不进锚）─────────────────────────────

class TestArrayFakeDispatch:
    F = np.linspace(5.3, 6.3, 401)

    def test_resonance_is_exact_inverse_of_design(self):
        from rfauto.adapters.fake_adapter import array_resonance_ghz

        for t in ot.ARRAY_TEMPLATES:
            assert array_resonance_ghz(
                t, ot.ARRAY_NOMINAL[t]) == pytest.approx(F0, rel=2e-5), t
        # 非标称点往返：f0'=6.3 设计（未舍入）→ 精确逆回 6.3
        w = ot.array_elem_w_mm(6.3)
        length = ot.array_elem_len_mm(6.3, w)
        assert array_resonance_ghz(
            "patch_array_1x4", {"elem_len_mm": length, "elem_w_mm": w}) == \
            pytest.approx(6.3, rel=1e-9)

    def test_dip_position_depth_and_passivity(self):
        from rfauto.adapters.fake_adapter import _array_sparams

        depth_window = {"patch_array_1x4": (-8.0, -4.0),
                        "patch_array_2x2": (-8.0, -4.0),
                        "patch_array_series": (-3.5, -1.0)}
        for t in ot.ARRAY_TEMPLATES:
            s = _array_sparams(self.F, t, ot.ARRAY_NOMINAL[t])
            assert s.shape == (len(self.F), 1, 1), t
            s11 = 20 * np.log10(np.abs(s[:, 0, 0]))
            assert float(self.F[np.argmin(s11)]) == pytest.approx(F0, abs=0.003), t
            lo, hi = depth_window[t]
            assert lo < float(s11.min()) < hi, (t, float(s11.min()))
            assert float(np.max(np.abs(s[:, 0, 0]))) <= 1.0 + 1e-12, t

    def test_scale_law_and_feed_depth_semantics(self):
        """尺寸是唯一进锚自由度：L×1.1 ⇒ 谷位÷1.1；插入深度只改谷深不改谷位。"""
        from rfauto.adapters.fake_adapter import _array_sparams

        f_wide = np.linspace(4.8, 6.3, 401)   # 盖住尺度律谷位
        p = dict(ot.ARRAY_NOMINAL["patch_array_1x4"])
        p["elem_len_mm"] *= 1.1
        s = _array_sparams(f_wide, "patch_array_1x4", p)
        f_dip = float(f_wide[np.argmin(np.abs(s[:, 0, 0]))])
        # 期望 = 设计式闭式直接代入（L×1.1、ΔL=0.483585 不缩放的二阶修正）
        d_l = 0.483585
        expected = F0 * (12.9058 + 2 * d_l) / (1.1 * 12.9058 + 2 * d_l)
        assert f_dip == pytest.approx(expected, abs=0.006)
        base = _array_sparams(f_wide, "patch_array_1x4",
                              ot.ARRAY_NOMINAL["patch_array_1x4"])
        shallow = dict(ot.ARRAY_NOMINAL["patch_array_1x4"])
        shallow["elem_feed_mm"] = 0.15 * shallow["elem_len_mm"]
        sh = _array_sparams(f_wide, "patch_array_1x4", shallow)
        base_db = float(20 * np.log10(np.abs(base[:, 0, 0])).min())
        shallow_db = float(20 * np.log10(np.abs(sh[:, 0, 0])).min())
        assert abs(shallow_db) < abs(base_db)          # 更浅
        assert float(f_wide[np.argmin(np.abs(sh[:, 0, 0]))]) == \
            pytest.approx(F0, abs=0.003)               # 谷位不动

    def test_fake_adapter_dispatch_all_three(self):
        from rfauto.adapters.fake_adapter import FakeAdapter

        for t in ot.ARRAY_TEMPLATES:
            ad = FakeAdapter(model_type=t, f0_ghz=F0, freq_ghz=(5.3, 6.3, 101))
            ad.connect({})
            ad.set_variables({k: str(v) for k, v in ot.ARRAY_NOMINAL[t].items()})
            ad.build_and_setup(lambda a: None, None)
            assert ad.solve("Setup1").success, t
            net = ad.get_sparams()
            assert net.s.shape[1:] == (1, 1), t
            f_dip = float(net.f[np.argmin(np.abs(net.s[:, 0, 0]))] / 1e9)
            assert f_dip == pytest.approx(F0, abs=0.006), t

    def test_fake_validation(self):
        from rfauto.adapters.fake_adapter import (
            _array_sparams,
            array_feed_rin_ohm,
            array_resonance_ghz,
        )

        with pytest.raises(ValueError):
            array_resonance_ghz("nope", {})
        with pytest.raises(ValueError):
            array_resonance_ghz("patch_array_1x4", {"elem_len_mm": 0.0,
                                                    "elem_w_mm": 16.9311})
        with pytest.raises(ValueError):
            array_feed_rin_ohm("patch_array_1x4",
                               {"elem_len_mm": 12.9058, "elem_w_mm": 16.9311,
                                "elem_feed_mm": 7.0}, F0)   # 插入 ≥ L/2=6.45
        with pytest.raises(ValueError):
            _array_sparams(self.F, "patch", ot.ARRAY_NOMINAL["patch_array_1x4"])


# ─── #212 制度化：CSXCAD 实测离线审计 ─────────────────────────────────────────

@pytest.mark.parametrize("template", sorted(ot.ARRAY_TEMPLATES))
def test_primitives_nonzero_and_in_mesh(template):
    scope, prims = _load(template)
    metal = [p for p in prims if p.kind == "Metal"]
    diel = [p for p in prims if p.kind == "Material"]
    assert metal, f"{template}: 无金属原语"
    assert len(diel) == 1, f"{template}: 接地贴片阵应恰一块基板"
    for p in metal:
        assert int(np.sum(p.extent[:2] > 1e-12)) >= 1, \
            f"{template}: 零退化金属盒 {p.prop} ext={p.extent}"
    assert gh.off_mesh_planes(prims, scope) == [], \
        f"{template}: 零厚面未入网 {gh.off_mesh_planes(prims, scope)}"


@pytest.mark.parametrize("template", sorted(ot.ARRAY_TEMPLATES))
def test_ports_single_and_excitation_nonzero(template):
    scope, prims = _load(template)
    ports = gh.port_objects(scope)
    assert len(ports) == EXPECTED_PORT_COUNT[template], f"{template}: 端口数"
    conductors = [p for p in prims if gh.is_conductor(p)]
    for nr, port in ports.items():
        start = np.asarray(port.start, dtype=float)
        stop = np.asarray(port.stop, dtype=float)
        ext = np.abs(stop - start)
        assert np.max(ext) > 1e-9, f"{template} port{nr}: 退化端口"
        if template == "patch_array_series":
            # MSLPort：端口面贴 y=−BOARD 板边（#174 铁律）
            assert abs(abs(start[1]) - float(scope["BOARD"])) <= 1e-9
        else:
            # 底探针集总馈：激励向 z 跨度 = H_SUB > 0（#174）
            assert ext[2] > 1e-9
            assert abs(start[2]) <= 1e-12 and abs(stop[2] - float(scope["H_SUB"])) <= 1e-12
        box = _PrimBox(start, stop)
        assert any(gh.connected(box, c) for c in conductors), \
            f"{template} port{nr}: 端口盒不邻接任何导体（悬空馈电）"


def _PrimBox(start, stop):
    from types import SimpleNamespace

    return SimpleNamespace(prop="port", kind="Metal",
                           lo=np.minimum(start, stop), hi=np.maximum(start, stop))


@pytest.mark.parametrize("template", sorted(ot.ARRAY_TEMPLATES))
def test_single_conductor_component(template):
    """全阵同一导体连通分量（馈树/互联导通；#212 pt5/pt6 家族教训）。"""
    _scope, prims = _load(template)
    conductors = [p for p in prims if gh.is_conductor(p)]
    labels = gh.component_labels(conductors)
    assert len(set(labels)) == 1, \
        f"{template}: 金属分裂为 {len(set(labels))} 分量"
    ports = gh.port_objects(_scope)
    for nr, port in ports.items():
        comp = gh.containing_labels(gh.port_feed_point(port), conductors, labels)
        assert comp, f"{template} port{nr}: 馈电点不在任何导体上"


def test_1x4_layout_elements_and_notch_contact():
    t = "patch_array_1x4"
    nom = ot.ARRAY_NOMINAL[t]
    lay = ot._arr_layout(t, nom)
    s, W = nom["spacing_mm"], nom["elem_w_mm"]
    centers = sorted((cx, cy) for cx, cy in lay["elements_mm"])
    assert [(round(cx, 4), round(cy, 4)) for cx, cy in centers] == [
        (-1.5 * s, 20.0), (-0.5 * s, 20.0), (0.5 * s, 20.0), (1.5 * s, 20.0)]
    assert 1.5 * s + W / 2 <= 60.0, "1×4 跨度超板"
    by_name = {(b[0], b[1]): b for b in lay["boxes"]}
    # 每元：缺口内馈段（stub）终点触缺口顶盒（中心盒）底缘 = 馈点连通
    # 盒元组索引：0=prop 1=name 2=x0 3=y0 4=z0 5=x1 6=y1 7=z1
    for i, (cx, _cy) in enumerate(centers):
        stub = by_name[(f"{t}_line", f"e{i}_stub")]
        center = by_name[(f"{t}_patch", f"e{i}_c")]
        assert stub[6] == pytest.approx(center[3], abs=1e-12), \
            f"元{i} 馈段终点未触缺口底（馈点悬空）"
        assert stub[2] == pytest.approx(cx - nom["feed_w_mm"] / 2, abs=1e-12)
        # 馈段两侧与缺口壁净空（不短接缺口）
        assert stub[2] - center[2] >= 0.5 - 1e-9
        # 变换段宽 = q_w、50Ω 段宽 = feed_w
        q = by_name[(f"{t}_qline", f"q{i}")]
        assert (q[5] - q[2]) == pytest.approx(nom["q_w_mm"], abs=1e-12)
        rise = by_name[(f"{t}_line", f"rise{i}")]
        assert (rise[5] - rise[2]) == pytest.approx(nom["feed_w_mm"], abs=1e-12)


def test_2x2_grid_top_row_notch_up_and_zero_crossing():
    t = "patch_array_2x2"
    nom = ot.ARRAY_NOMINAL[t]
    lay = ot._arr_layout(t, nom)
    dx, dy = nom["spacing_x_mm"], nom["spacing_y_mm"]
    L, W = nom["elem_len_mm"], nom["elem_w_mm"]
    centers = sorted((cx, cy) for cx, cy in lay["elements_mm"])
    expected_centers = [(-dx / 2, 20.0 - dy / 2), (-dx / 2, 20.0 + dy / 2),
                        (dx / 2, 20.0 - dy / 2), (dx / 2, 20.0 + dy / 2)]
    for (cx, cy), (ex, ey) in zip(centers, expected_centers, strict=True):
        assert cx == pytest.approx(ex, abs=1e-9) and cy == pytest.approx(ey, abs=1e-9)
    by_name = {(b[0], b[1]): b for b in lay["boxes"]}
    # 底/顶排贴片外盒（左右件）：贴片 y 范围 = 排中心 ± L/2（盒名 = e_b_{side}_l 等）
    for tag, row_y in (("e_b", 20.0 - dy / 2), ("e_t", 20.0 + dy / 2)):
        for side in ("l", "r"):
            left = by_name[(f"{t}_patch", f"{tag}_{side}_l")]
            right = by_name[(f"{t}_patch", f"{tag}_{side}_r")]
            for part in (left, right):
                assert part[3] == pytest.approx(row_y - L / 2, abs=1e-12)
                assert part[6] == pytest.approx(row_y + L / 2, abs=1e-12)
    center_top = by_name[(f"{t}_patch", "e_t_l_c")]
    center_bot = by_name[(f"{t}_patch", "e_b_l_c")]
    assert center_top[6] == pytest.approx(20.0 + dy / 2 + L / 2 - nom["elem_feed_mm"],
                                          abs=1e-12)   # 顶排缺口自顶缘向下挖
    assert center_bot[3] == pytest.approx(20.0 - dy / 2 - L / 2 + nom["elem_feed_mm"],
                                          abs=1e-12)   # 底排缺口自底缘向上挖
    # 走廊竖线在全部贴片 x 范围之外（零交叉）；顶排内折横线在贴片上方（零交叉）
    x_corr = dx / 2 + W / 2 + 2.0
    patches = [b for b in lay["boxes"] if b[0] == f"{t}_patch"]
    for tag in ("corr_l", "corr_r"):
        corr = by_name[(f"{t}_line", tag)]
        cx_corr = (corr[2] + corr[5]) / 2
        assert abs(abs(cx_corr) - x_corr) <= 1e-9
        for pb in patches:
            assert not gh.connected(_Box(*corr[2:]), _Box(*pb[2:])), \
                f"{tag} 与贴片 {pb[1]} 相交（同层短接）"
    for tag in ("run_t_l", "run_t_r"):
        run = by_name[(f"{t}_line", tag)]
        for pb in patches:
            assert not gh.connected(_Box(*run[2:]), _Box(*pb[2:])), \
                f"{tag} 与贴片 {pb[1]} 相交（同层短接）"


def _Box(x0, y0, z0, x1, y1, z1):
    from types import SimpleNamespace

    return SimpleNamespace(prop="b", kind="Metal",
                           lo=np.array([min(x0, x1), min(y0, y1), min(z0, z1)]),
                           hi=np.array([max(x0, x1), max(y0, y1), max(z0, z1)]))


def test_series_chain_order_and_port_on_board_edge():
    t = "patch_array_series"
    nom = ot.ARRAY_NOMINAL[t]
    lay = ot._arr_layout(t, nom)
    L, link, m = nom["elem_len_mm"], nom["link_len_mm"], nom["feed_margin_mm"]
    patches = sorted((b for b in lay["boxes"] if b[1].startswith("e")),
                     key=lambda b: b[3])
    links = [b for b in lay["boxes"] if b[1].startswith("link")]
    assert len(patches) == 3 and len(links) == 2
    y = -60.0 + m
    for k, pb in enumerate(patches):
        assert pb[3] == pytest.approx(y, abs=1e-12), f"元{k} 链序漂移"
        assert pb[2] == pytest.approx(-nom["elem_w_mm"] / 2, abs=1e-12)
        if k < 2:
            lk = links[k]
            assert lk[3] == pytest.approx(y + L, abs=1e-12)
            assert lk[6] == pytest.approx(y + L + link, abs=1e-12)
        y += L + link
    assert y - link <= 59.0, "串馈链超板"
    # MSLPort 面贴 y=−BOARD（±60mm），馈段长 = margin
    port = lay["ports"][0]
    assert port["kind"] == "msl"
    assert port["start_mm"][1] == pytest.approx(-60.0, abs=1e-12)
    assert port["stop_mm"][1] == pytest.approx(-60.0 + m, abs=1e-12)
    assert port["meas_shift_mm"] == pytest.approx(m / 3.0, abs=1e-12)
    # 互联为 λg/2（HJ @feed_w；铁律 1c 禁文档毫米数）
    assert link == pytest.approx(
        ot.array_half_guided_len_mm(nom["feed_w_mm"], F0), abs=1e-4)


def test_layout_guards_raise():
    nom = dict(ot.ARRAY_NOMINAL["patch_array_1x4"])
    bad = dict(nom, spacing_mm=nom["elem_w_mm"])   # 单元重叠
    with pytest.raises(ValueError):
        ot._arr_layout("patch_array_1x4", bad)
    bad = dict(nom, elem_feed_mm=nom["elem_len_mm"] / 2)   # 插入越中
    with pytest.raises(ValueError):
        ot._arr_layout("patch_array_1x4", bad)
    bad = dict(ot.ARRAY_NOMINAL["patch_array_series"],
               elem_len_mm=30.0)   # 链超板
    with pytest.raises(ValueError):
        ot._arr_layout("patch_array_series", bad)


def test_layout_params_drive_geometry_at_audit_perturbation():
    """审计 ×1.37+0.013 扰动域（布局级）：每个声明参数扰动后布局可建且几何必变。"""
    for t in ot.ARRAY_TEMPLATES:
        nom = dict(ot.ARRAY_NOMINAL[t])
        base = _lay_signature(ot._arr_layout(t, nom))
        for key, val in nom.items():
            pert = dict(nom)
            pert[key] = float(val) * 1.37 + 0.013
            lay = ot._arr_layout(t, pert)   # 不抛错（扰动域内可建）
            assert _lay_signature(lay) != base, f"{t}.{key}: 未驱动几何（幽灵参数）"


def _lay_signature(lay: dict) -> tuple:
    return tuple(sorted(
        (b[0], b[1], *(round(v, 9) for v in b[2:]))
        for b in lay["boxes"]))


def test_render_far_field_ground_plane_branch():
    """far_field=True：接地贴片阵走 patch 型 NF 盒（z 底=0），渲染可执行。"""
    for t in ot.ARRAY_TEMPLATES:
        text = ot.render_script(t, dict(ot.ARRAY_NOMINAL[t]), BAND,
                                mesh_resolution_mm=MESH_MM, far_field=True)
        assert "CreateNF2FFBox" in text
        head = text[: text.index("FDTD.Run(")]
        scope: dict = {"__name__": "__main__", "__file__": "_ff_sim.py"}
        exec(compile(head, "ff_audit", "exec"), scope)


# ─── 方向图裁判 = 积定理闭式（标称几何 × D5 内核 tie-in）───────────────────────

def test_nominal_1x4_closed_form_pattern_peak_hpbw_grating():
    from rfauto.core.array_synthesis import (
        array_factor,
        array_factor_angles,
        broadside_hpbw_deg,
        grating_lobe_direction_cosines,
        patch_element_field,
        pattern_multiplication,
        uniform_weights,
    )

    nom = ot.ARRAY_NOMINAL["patch_array_1x4"]
    lam0 = C_MM_GHZ / F0
    d = nom["spacing_mm"] / lam0
    assert grating_lobe_direction_cosines(d) == ()
    th = np.linspace(-90.0, 90.0, 3601)
    af = np.abs(array_factor_angles(th, uniform_weights(4), spacing_lambda=d,
                                    scan_deg=0.0, axis="x"))
    el = patch_element_field(th, 0.0, len_mm=nom["elem_len_mm"],
                             width_mm=nom["elem_w_mm"], freq_ghz=F0, axis="y")
    total = np.abs(pattern_multiplication(el, af))
    assert th[int(np.argmax(total))] == pytest.approx(0.0, abs=0.05)
    # HPBW：精确二分 vs 渐近式 0.886λ/(Nd)（N=4 偏 ~3.7%，内核单测已钉 d=λ0/2 案）
    u_half = 1.0 / (4.0 * d)
    lo, hi = 1e-12, u_half
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if float(np.abs(array_factor(mid, uniform_weights(4), spacing_lambda=d))) > \
                1.0 / np.sqrt(2.0):
            lo = mid
        else:
            hi = mid
    hpbw_exact = float(np.degrees(2.0 * np.arcsin(0.5 * (lo + hi))))
    formula = broadside_hpbw_deg(4, d)
    assert abs(hpbw_exact - formula) / formula < 0.05
    assert float(total.max()) == pytest.approx(1.0)


def test_nominal_2x2_separable_product_with_nominal_spacing():
    from rfauto.core.array_synthesis import (
        array_factor,
        direction_cosine,
        planar_array_factor,
        uniform_weights,
    )

    nom = ot.ARRAY_NOMINAL["patch_array_2x2"]
    lam0 = C_MM_GHZ / F0
    dx, dy = nom["spacing_x_mm"] / lam0, nom["spacing_y_mm"] / lam0
    th = np.linspace(0.0, 90.0, 91)[:, None]
    ph = np.linspace(0.0, 360.0, 73)[None, :]
    af = planar_array_factor(th, ph, uniform_weights(2), uniform_weights(2),
                             spacing_x_lambda=dx, spacing_y_lambda=dy)
    ref = (array_factor(direction_cosine(th, ph, "x"), uniform_weights(2),
                        spacing_lambda=dx)
           * array_factor(direction_cosine(th, ph, "y"), uniform_weights(2),
                          spacing_lambda=dy))
    assert np.array_equal(af, ref)   # 积定理逐点（可分离积，Balanis Ch.6 §6.10）
    assert float(np.abs(af[0, 0])) == pytest.approx(1.0)


def test_nominal_series_pitch_lambda_half_guided_and_grating_free():
    from rfauto.core.array_synthesis import has_grating_lobe

    nom = ot.ARRAY_NOMINAL["patch_array_series"]
    pitch = nom["elem_len_mm"] + nom["link_len_mm"]
    lam0 = C_MM_GHZ / F0
    assert pitch / lam0 == pytest.approx(0.5454, abs=1e-3)
    assert not has_grating_lobe(pitch / lam0)


# ─── 冒烟判据函数（scripts/smoke_array_anchor.py，离线单测）────────────────────

@pytest.fixture(scope="module")
def smoke():
    spec = importlib.util.spec_from_file_location(
        "smoke_array_anchor", REPO / "scripts" / "smoke_array_anchor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSmokeAnchorJudges:
    def test_expected_pattern_closed_form_values(self, smoke):
        e1 = smoke.expected_pattern("patch_array_1x4")
        assert e1["main_lobe_theta_deg"] == 0.0
        assert e1["grating_lobe_free"] is True
        assert e1["hpbw_deg"]["phi_0"] == pytest.approx(25.85, abs=0.5)
        assert e1["dmax_dbi"] == pytest.approx(10.53, abs=0.3)
        e2 = smoke.expected_pattern("patch_array_2x2")
        assert e2["hpbw_deg"]["phi_0"] == pytest.approx(49.49, abs=0.5)
        assert e2["dmax_dbi"] == pytest.approx(11.15, abs=0.3)
        e3 = smoke.expected_pattern("patch_array_series")
        assert e3["hpbw_deg"]["phi_90"] == pytest.approx(31.95, abs=0.5)
        with pytest.raises(KeyError):
            smoke.expected_pattern("patch")

    def test_judge_s11_window_and_depth(self, smoke):
        f = np.linspace(5.3, 6.3, 401)
        good = -20.0 * np.exp(-((f - 5.85) / 0.05) ** 2)
        v = smoke.judge_s11(f, good)
        assert v["ok"] is True
        shallow = -4.0 * np.exp(-((f - 5.85) / 0.05) ** 2)
        assert smoke.judge_s11(f, shallow)["depth_ok"] is False
        # 出窗谷：谷位 6.55 > 窗上沿 6.496（频带须盖出窗区，故用宽带合成）
        f_wide = np.linspace(5.0, 6.7, 401)
        off = -20.0 * np.exp(-((f_wide - 6.55) / 0.05) ** 2)
        assert smoke.judge_s11(f_wide, off)["window_ok"] is False
        with pytest.raises(ValueError):
            smoke.judge_s11(f[:5], good[:4])

    def test_judge_far_field_pass_and_fail(self, smoke):
        e = smoke.expected_pattern("patch_array_1x4")
        cuts = [{"phi_deg": 0.0, "peak_theta_deg": 1.0,
                 "hpbw_deg": e["hpbw_deg"]["phi_0"] * 1.1}]
        meta = {"dmax_linear": e["dmax_linear"] * 0.85, "efficiency": 0.8}
        assert smoke.judge_far_field(cuts, meta, e)["ok"] is True
        meta_bad = {"dmax_linear": e["dmax_linear"] * 0.5, "efficiency": 0.8}
        assert smoke.judge_far_field(cuts, meta_bad, e)["ok"] is False
        assert smoke.judge_far_field([], meta, e)["ok"] is False
        eta_bad = {"dmax_linear": e["dmax_linear"], "efficiency": 0.1}
        assert smoke.judge_far_field(cuts, eta_bad, e)["ok"] is False
