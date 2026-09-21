"""WP2.5 Tier 2：MSL↔CPWG 过渡模板单测（附加模板口径，同 coupled_bpf 段）。

方案行：MSL↔CPW、
MSL↔slotline（Marchand，随 slotline 端口原语缺失阻塞，归 C5 行）、
SMA launcher。本件覆盖 MSL↔CPW：
- 正式注册（2026-09-16 wp25-sma-launcher-rootcause）：MSL_CPW_META/NOMINAL
  同对象入 TEMPLATE_META/TEMPLATE_NOMINAL + docs/templates/msl_cpw/meta.yaml +
  EXPECTED_TEMPLATES + fake 派发 + template_specs——test_registered_* 钉。
  几何/网格由真机 PASS 冻结（真机冒烟 pt1：|S11|@2.5G
  −20.0dB、β +0.37%/−1.04%，1076s@0.4mm）——勿动。
- 锚判据（wstep/via 族同型，Tier 2 无谐振）：双端口 β 金标准
  （port1→HJ εeff、port2→CPWG 共形映射闭式，|Δ|≤2%）+ 两段理想 TL
  级联裁判（_msl_cpw_sparams；渐变/地缘/过孔栅栏寄生=引擎-理想偏差）。
- #212 制度化：render → exec 几何段（FDTD.Run 之前）→ CSXCAD 实测，
  秒级零仿真（字符串门抓不住画法错误）。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import fake_adapter as fa
from rfauto.adapters import openems_templates as ot
from tests.unit import _geometry_audit_helpers as gh

MESH_MM = 0.4
BAND = (2.25, 2.75)
F0 = 2.5
NOMINAL = dict(ot.MSL_CPW_NOMINAL)


# ─── 本地 CSXCAD 实测夹具（gh.extract_primitives 不识别柱向；局部扩展）───────

@dataclass
class _Prim:
    prop: str
    kind: str
    ptype: str
    lo: np.ndarray
    hi: np.ndarray
    radius: float | None = None

    @property
    def extent(self) -> np.ndarray:
        return self.hi - self.lo


def _extract_prims(csx) -> list[_Prim]:
    """属性表 → 原语包围盒；柱/柱壳按轴向扩张半径（gh 只认 z 向柱）。"""
    out: list[_Prim] = []
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        kind = str(prop.GetTypeString())
        for prim in prop.GetAllPrimitives():
            ptype = str(prim.GetType())
            start = np.asarray(prim.GetStart(), dtype=float)
            stop = np.asarray(prim.GetStop(), dtype=float)
            lo = np.minimum(start, stop)
            hi = np.maximum(start, stop)
            radius: float | None = None
            if ptype in ("5", "6"):  # CSPrimCylinder / CSPrimCylindricalShell
                radius = float(prim.GetRadius())
                if ptype == "6":
                    radius += float(prim.GetShellWidth()) / 2.0
                axis = int(np.argmax(hi - lo))
                for ax in range(3):
                    if ax != axis:
                        lo[ax] -= radius
                        hi[ax] += radius
            out.append(_Prim(str(prop.GetName()), kind, ptype, lo, hi, radius))
    return out


def _load(params: dict | None = None, mesh_mm: float = MESH_MM):
    """渲染 msl_cpw → exec 几何段 → (脚本作用域, 原语列表)。"""
    resolved = dict(NOMINAL if params is None else params)
    text = ot.render_script("msl_cpw", resolved, BAND,
                            mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_msl_cpw_audit_sim.py")}
    exec(compile(head, "msl_cpw_audit", "exec"), scope)
    return scope, _extract_prims(scope["CSX"])


# ─── 注册四件套（2026-09-16 wp25-sma-launcher-rootcause 正式注册）────────────

def test_registered_in_registry():
    """正式注册：TEMPLATE_META/NOMINAL 同对象入表；端口轴/辐射标志不变。"""
    assert ot.TEMPLATE_META["msl_cpw"] is ot.MSL_CPW_META
    assert ot.TEMPLATE_NOMINAL["msl_cpw"] is ot.MSL_CPW_NOMINAL
    assert set(ot.MSL_CPW_META["params"]) == set(NOMINAL)
    assert ot._TEMPLATE_PORT_AXES["msl_cpw"] == ("y",)
    assert ot._TEMPLATE_RADIATOR["msl_cpw"] is False
    assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)


def test_registration_surface_complete():
    import yaml

    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

    bootstrap_template_specs()
    assert "msl_cpw" in EXPECTED_TEMPLATES
    spec = TEMPLATE_SPECS.get("msl_cpw")
    assert spec is not None and spec.hfss_plugin is None
    assert TEMPLATE_SPECS.component("msl_cpw", "fake_model") is fa._msl_cpw_sparams
    assert spec.physics_roles["gap_cpw_mm"] == "gap_width_mm"
    meta = yaml.safe_load((REPO / "docs" / "templates" / "msl_cpw"
                           / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["template"] == "msl_cpw" and meta["n_ports"] == 2
    assert set(meta["params"]) == set(NOMINAL)
    for k, v in NOMINAL.items():
        assert float(meta["nominal_params"][k]) == pytest.approx(float(v), rel=1e-12), k


def test_fake_dispatch_matches_closed_form_phase():
    """FakeAdapter(model_type='msl_cpw') 派发：两段等长级联 S21 相位斜率 =
    (√εeff_msl + √εeff_cpwg)·L/2 闭式；同阻 → S11≈0（#154 同名同义）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter
    from rfauto.core.calculators import _cpwg_ri
    from rfauto.core.synthesis import Stackup, forward_z0

    ad = FakeAdapter(model_type="msl_cpw", n_ports=2,
                     freq_ghz=(2.25, 2.75, 201), f0_ghz=F0)
    ad.connect({})
    ad.set_variables({k: f"{v}mm" for k, v in NOMINAL.items()})
    ad.solve("main_setup")
    net = ad.get_sparams()
    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    _, eps_msl = forward_z0(NOMINAL["w_msl_mm"], F0, st)
    eps_cpw, _ = _cpwg_ri(NOMINAL["w_cpw_mm"], NOMINAL["gap_cpw_mm"],
                          st.thickness_mm, st.epsilon_r)
    phase = np.unwrap(np.angle(net.s[:, 1, 0]))
    slope = np.polyfit(net.f, phase, 1)[0]
    elec = (eps_msl ** 0.5 + eps_cpw ** 0.5) * NOMINAL["line_len_mm"] / 2 * 1e-3
    assert -slope * 299792458.0 / (2 * np.pi) == pytest.approx(elec, rel=2e-3)
    assert float(np.max(np.abs(net.s[:, 0, 0]))) < 2e-3   # 50Ω/50Ω 级联地板
    ad.set_variables({"gap_cpw_mm": "0.6mm"})
    ad.solve("main_setup")
    assert not np.allclose(np.angle(ad.get_sparams().s[:, 1, 0]), np.angle(net.s[:, 1, 0]))


# ─── 综合链（确定性内核：宽度=阻抗闭式反解，非手数）───────────────────────────

def test_synthesis_matches_nominal():
    """NOMINAL 常数是 synthesize_msl_cpw_model(50, 2.5) 的 4 位舍入。"""
    from rfauto.core.synthesis import synthesize_msl_cpw_model

    synth = synthesize_msl_cpw_model(50.0, F0, NOMINAL["line_len_mm"],
                                     NOMINAL["trans_len_mm"],
                                     NOMINAL["gap_cpw_mm"])
    for key in ("w_msl_mm", "w_cpw_mm"):
        assert round(synth.params[key], 4) == NOMINAL[key]
    assert synth.params["gap_cpw_mm"] == NOMINAL["gap_cpw_mm"]


def test_synthesis_impedance_anchors():
    """两段阻抗回代：微带 HJ 与 CPWG 共形映射闭式各回 50Ω（独立正向）。"""
    from rfauto.core.calculators import _cpwg_ri
    from rfauto.core.synthesis import Stackup, forward_z0

    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    z_msl, eeff1 = forward_z0(NOMINAL["w_msl_mm"], F0, st)
    assert z_msl == pytest.approx(50.0, abs=0.05)
    eeff2, z_cpw = _cpwg_ri(NOMINAL["w_cpw_mm"], NOMINAL["gap_cpw_mm"],
                            st.thickness_mm, st.epsilon_r)
    assert z_cpw == pytest.approx(50.0, abs=0.05)
    # εeff 双锚（与 CPW 锚模板同源口径，冒烟 |Δ|≤2% 判据的真值侧）
    assert eeff1 == pytest.approx(2.8527, abs=5e-4)
    assert eeff2 == pytest.approx(2.5673, abs=5e-4)


def test_synthesis_rejects_out_of_domain_gap():
    """CPWG 退化域（k→1 溢出 / 反解无解）显式报错而非静默数。"""
    from rfauto.core.synthesis import synthesize_msl_cpw_model

    with pytest.raises((ValueError, RuntimeError)):
        synthesize_msl_cpw_model(50.0, F0, 40.0, 10.0, gap_cpw_mm=1e-9)


# ─── fake 裁判（两段理想 TL 级联）────────────────────────────────────────────

FREQS = np.linspace(2.0, 3.0, 201)


def test_fake_is_equal_length_two_segment_cascade():
    """_msl_cpw_sparams == 等长 _wstep_sparams（委托一致性）。"""
    s1 = fa._msl_cpw_sparams(FREQS, eps_eff1=2.8527, eps_eff2=2.5673,
                             z1=50.0, z2=50.0, seg_len_mm=15.0, tan_d=0.0)
    s2 = fa._wstep_sparams(FREQS, eps_eff1=2.8527, eps_eff2=2.5673,
                           z1=50.0, z2=50.0, seg_len_mm=15.0, tan_d=0.0)
    assert np.array_equal(s1, s2)


def test_fake_lossless_reciprocal_matched():
    """理想级联：无耗幺正 + 互易；同阻两段级联全带匹配（S11≈0 地板）。"""
    s = fa._msl_cpw_sparams(FREQS, eps_eff1=2.8527, eps_eff2=2.5673,
                            z1=50.0, z2=50.0, seg_len_mm=15.0, tan_d=0.0)
    p = np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2
    assert float(np.max(np.abs(p - 1.0))) < 1e-9
    assert float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0]))) < 1e-12
    assert float(np.max(np.abs(s[:, 0, 0]))) < 1e-9
    # S21 相位独立闭式：-（β1+β2）·15mm @2.5GHz（米制 β=2πf√εeff/c）
    i0 = int(np.argmin(np.abs(FREQS - F0)))
    c0 = 299792458.0
    ph = -(2 * np.pi * F0 * 1e9 * (2.8527 ** 0.5 + 2.5673 ** 0.5) / c0
           * 15.0e-3)
    assert float(np.angle(s[i0, 1, 0])) == pytest.approx(
        float(np.angle(np.exp(1j * ph))), abs=1e-6)


# ─── 渲染结构与边界条件 ──────────────────────────────────────────────────────

def test_render_structure():
    text = ot.render_script("msl_cpw", dict(NOMINAL), BAND,
                            mesh_resolution_mm=MESH_MM)
    compile(text, "gen", "exec")
    assert "MSLPort(CSX, port_nr=1" in text
    assert "CPWPort(CSX, port_nr=2" in text
    assert "gap_width=GAP" in text
    assert 'from openEMS.ports import LumpedPort, MSLPort, CPWPort' in text
    assert text.count('prop_dir="y"') == 2
    # 双端口 β 金标准插桩（分段 εeff 锚）
    assert "beta1_rad_per_m" in text and "beta2_rad_per_m" in text
    # 边界：y 轴 PML（端口面）、x 轴 MUR、z-min PEC 地、z-max MUR
    assert '["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"]' in text
    scope, _ = _load()
    assert float(scope["F0"]) == pytest.approx(F0 * 1e9, rel=1e-12)


def test_near_points_exact_edges():
    nx, ny = ot._near_points("msl_cpw", dict(NOMINAL))
    wm = NOMINAL["w_msl_mm"] * 1e-3
    wc = NOMINAL["w_cpw_mm"] * 1e-3
    gp = NOMINAL["gap_cpw_mm"] * 1e-3
    for edge in (-wm / 2, wm / 2, -wc / 2, wc / 2,
                 wc / 2 + gp, -(wc / 2 + gp), wc / 2 + gp / 2):
        assert min(abs(v - edge) for v in nx) < 1e-12
    # 渐变区端点精确；线端走房规 edges() 括号线（±NEAR/2 外扩）
    for edge in (-5e-3, 5e-3):
        assert min(abs(v - edge) for v in ny) < 1e-12
    for edge in (-20.5e-3, 20.5e-3):
        assert min(abs(v - edge) for v in ny) < 1e-12


def _z_substrate_points(text: str) -> int:
    """渲染脚本里基板 z linspace 的点数（np.linspace(0, H_SUB, N)）。"""
    import re

    m = re.search(r'mesh\.AddLine\("z", np\.linspace\(0, H_SUB, (\d+)\)\)',
                  text)
    assert m, "基板 z linspace 行未找到"
    return int(m.group(1))


def test_g3_sub_cells_default_family_policy():
    """G3 2026-09-22 缺省变更钉（#325 语义：钉"现行缺省"，不改写历史归档）。

    依据 zconv 定案实验（runs/msl_cpw_zconv，2026-09-20 预声明判据）：
    dev −2.151→−0.971→−0.474pp（sub4→8→16），GRID_UNDERRES（网格份额
    78%）+SATURATED_RESIDUAL，sub8 即回 msl_cpw_benchmark_verdict ±2%
    锚门内——CPW/槽下场族生产缺省 _sub_cells=8（#313 z 向地板项）。
    同时钉逐字节不变面：显式 _sub_cells=4 回旧口径、且与新缺省全文 diff
    恰 1 行（z linspace 5→9 点）；显式 8 与新缺省逐字节相同；非族模板
    （mline）缺省仍 4 格 5 点。
    """
    default_text = ot.render_script("msl_cpw", dict(NOMINAL), BAND,
                                    mesh_resolution_mm=MESH_MM)
    assert _z_substrate_points(default_text) == 9  # 8 格（G3 新缺省）
    old_text = ot.render_script("msl_cpw", {**NOMINAL, "_sub_cells": 4},
                                BAND, mesh_resolution_mm=MESH_MM)
    assert _z_substrate_points(old_text) == 5  # 官方 substrate_cells=4 旧口径
    assert ot.render_script("msl_cpw", {**NOMINAL, "_sub_cells": 8}, BAND,
                            mesh_resolution_mm=MESH_MM) == default_text
    old_lines = old_text.splitlines()
    new_lines = default_text.splitlines()
    assert len(old_lines) == len(new_lines)
    changed = [i for i, (a, b) in enumerate(
        zip(old_lines, new_lines, strict=True)) if a != b]
    assert len(changed) == 1, f"缺省变更应恰动 z 一行，实动 {len(changed)} 行"
    assert "linspace(0, H_SUB, 9)" in new_lines[changed[0]]
    # 非族模板缺省逐字节不变（官方 4 格口径）
    mline_text = ot.render_script("mline", dict(ot.TEMPLATE_NOMINAL["mline"]),
                                  BAND, mesh_resolution_mm=MESH_MM)
    assert _z_substrate_points(mline_text) == 5


# ─── #212 离线几何审计（CSXCAD 实测）────────────────────────────────────────

def test_primitives_nonzero_and_entered_in_mesh():
    scope, prims = _load()
    metal = [p for p in prims if p.kind == "Metal"]
    dielectric = [p for p in prims if p.kind == "Material"]
    assert len(dielectric) == 1
    boxes = [p for p in metal if p.ptype != "5"]
    cyls = [p for p in metal if p.ptype == "5"]
    # 8 手画盒 + 2 端口自画馈段；接地栅栏 = 28 行 ×2 柱
    n_rows = int((60.0 - NOMINAL["via_offset_mm"]
                  - (NOMINAL["trans_len_mm"] / 2 + NOMINAL["via_offset_mm"]))
                 // NOMINAL["via_spacing_mm"]) + 1
    assert len(boxes) == 10
    assert len(cyls) == 2 * n_rows
    for p in metal:
        if p.ptype == "5":
            assert p.radius > 0 and p.extent[2] > 0
        else:
            assert int(np.sum(p.extent[:2] > 1e-12)) == 2
    for p in dielectric:
        assert bool(np.all(p.extent > 1e-12))
    assert gh.off_mesh_planes(prims, scope) == []
    lines = {ax: gh.mesh_lines(scope, ax) for ax in ("x", "y", "z")}
    zl = lines["z"]
    for p in [q for q in prims if gh.is_conductor(q)]:
        if p.ptype == "5":
            # 接地柱 r≪cell：阶梯化为本族既定口径（via 基元先例，不进网格
            # 线）；柱轴两端（0 与 H_SUB）必须落在 z 网格线上
            assert p.lo[2] == pytest.approx(0.0, abs=1e-12)
            assert float(np.min(np.abs(zl - p.hi[2]))) <= 1e-9
            continue
        for index, axis in enumerate(("x", "y", "z")):
            if p.extent[index] > 1e-12:
                inside = lines[axis][(lines[axis] >= p.lo[index] - 1e-9)
                                     & (lines[axis] <= p.hi[index] + 1e-9)]
                assert inside.size >= 1, f"{p.prop} 在 {axis} 轴未进网格"


def test_ports_on_boundary_and_nonzero():
    scope, _ = _load()
    ports = gh.port_objects(scope)
    assert set(ports) == {1, 2}
    board = float(scope["BOARD"])
    z_lines = gh.mesh_lines(scope, "z")
    for number, port in ports.items():
        start = np.asarray(port.start, dtype=float)
        assert int(port.prop_ny) == 1
        assert abs(abs(start[1]) - board) <= 1e-9, \
            f"port{number} 端口面未贴板边"
        assert float(np.min(np.abs(z_lines - start[2]))) <= 1e-6, \
            f"port{number} 金属面 z 未入网"
    # port2 是 CPWPort（一等端口，缝宽口径经 GAP 变量传入——CPWPort 不存属性）
    assert type(ports[2]).__name__ == "CPWPort"


def test_connectivity_two_conductor_systems():
    """中心导体链（port1+port2 同分量）与地系统（地+栅栏）分离不短路。"""
    scope, prims = _load()
    conductors, labels = gh.conductor_labels(prims)
    ports = gh.port_objects(scope)
    comp_of = {}
    for number, port in ports.items():
        on = gh.containing_labels(gh.port_feed_point(port), conductors, labels)
        assert on, f"port{number} 馈电点不在任何导体上（激励悬空）"
        comp_of[number] = on
    assert comp_of[1] & comp_of[2], "两端口未导通（渐变区断裂）"
    # 地系统分量存在且不含端口馈电点（中心导体与地缝=GAP 不短路）
    wc = NOMINAL["w_cpw_mm"] * 1e-3
    gp = NOMINAL["gap_cpw_mm"] * 1e-3
    yt = NOMINAL["trans_len_mm"] / 2 * 1e-3

    def _is_ground(p) -> bool:
        if p.prop == "msl_cpw_via":
            return True
        return (p.prop == "msl_cpw" and p.ptype != "5"
                and (p.lo[0] >= wc / 2 + gp - 1e-12
                     or p.hi[0] <= -(wc / 2 + gp) + 1e-12))

    ground_comps = {labels[i] for i, p in enumerate(conductors)
                    if _is_ground(p)}
    assert ground_comps
    assert not (ground_comps & (comp_of[1] | comp_of[2]))
    # 缝距实测（CPW 直段，y≥YT）：地内缘与中心带缘恰差 gap_cpw
    grounds = [p for p in conductors if p.prop == "msl_cpw"
               and p.lo[0] > 0 and p.lo[1] >= yt - 1e-12]
    center = [p for p in conductors if p.prop == "msl_cpw"
              and p.ptype != "5" and p.lo[1] >= yt - 1e-12
              and p.hi[0] <= wc / 2 + 1e-12]
    assert grounds and center
    assert min(g.lo[0] for g in grounds) - max(c.hi[0] for c in center) \
        == pytest.approx(gp, rel=1e-9)


def test_taper_staircase_exact():
    """渐变区实测：4 段等分（±5mm），段宽=线性内插中点值（W_M→W_C）。"""
    _scope, prims = _load()
    wm = NOMINAL["w_msl_mm"] * 1e-3
    wc = NOMINAL["w_cpw_mm"] * 1e-3
    yt0, yt1 = -NOMINAL["trans_len_mm"] / 2 * 1e-3, \
        NOMINAL["trans_len_mm"] / 2 * 1e-3
    taper = [p for p in prims if p.kind == "Metal" and p.ptype != "5"
             and p.lo[1] >= yt0 - 1e-12 and p.hi[1] <= yt1 + 1e-12]
    assert len(taper) == 4
    taper.sort(key=lambda p: p.lo[1])
    nt = 4
    for i, seg in enumerate(taper):
        w_expect = wm + (i + 0.5) * (wc - wm) / nt
        assert seg.extent[0] == pytest.approx(w_expect, rel=1e-9)
        seg_len = (yt1 - yt0) / nt
        assert seg.lo[1] == pytest.approx(yt0 + i * seg_len, abs=1e-12)


def test_mesh_min_gap_guard_and_domain():
    scope, _ = _load()
    board = float(scope["BOARD"])
    for axis in ("x", "y", "z"):
        lines = gh.mesh_lines(scope, axis)
        assert lines.size >= 2
        diffs = np.diff(lines)
        assert bool(np.all(diffs > 1e-6)), f"{axis} 轴 <1µm 近重合线（#152）"
    for axis in ("x", "y"):
        lines = gh.mesh_lines(scope, axis)
        assert lines.min() == pytest.approx(-board, abs=1e-9)
        assert lines.max() == pytest.approx(board, abs=1e-9)


def test_geometry_spec_preview():
    spec = ot.geometry_spec("msl_cpw", dict(NOMINAL))
    names = [b["name"] for b in spec["boxes"]]
    assert names.count("substrate") == 1 and "ground" in names
    assert "taper（阶梯渐变）" in names and "cpw_gnd_left" in names
    assert len(spec["ports"]) == 2


@pytest.mark.parametrize("key", sorted(NOMINAL))
def test_declared_params_drive_geometry(key):
    base = gh.conductor_signature([p for p in _load()[1]
                                   if gh.is_conductor(p)])
    params = dict(NOMINAL)
    params[key] = float(NOMINAL[key]) * 1.37 + 0.013
    changed = [p for p in _load(params)[1] if gh.is_conductor(p)]
    assert gh.conductor_signature(changed) != base, \
        f"声明但未驱动几何的参数 {key}"
