"""WP2.5 Tier 2：SMA 边缘弹射（同轴↔微带，edge-launch 夹具口径）模板单测。

方案行："SMA launcher
（放最后，验收靠文献曲线）"。2026-09-16 wp25-sma-launcher-rootcause：
- 真机 FAIL 根治（pt2：|S11|=+5.42dB 非物理、|S21|≈−375dB、port2 表观 εeff
  2866）。scripts/diag_sma_launcher.py 精确接触图在旧几何上实证（接触图
  留档诊断归档）：
  H2 引脚柱盒-壳底壁实交叠（信号链对地短路）、H1 地侧针与壳/墙/底板零接触
  （串馈口基准端悬空）、H4 port1 整体落在 y-min PML_8 内、H5 壳顶距域顶
  0.25mm。旧测试漏洞：短路循环不含 shell、净空判据只算 x 半对角忽略 z。
- 新几何（连接器厂商 end-launch 图纸口径，docs/rf_template_references.md
  SMA 节）：针水平搭焊微带（针底切线=基板顶）、壳体在板边切口之外、地链
  壳—夹具块—PEC 底板实触；port1=同轴截面集总桥（LumpedPort R=50Ω，针顶→
  壳内壁顶沿 z）；PCB 抬高 Z_G=r_os−r_i−H_SUB（几何单源 sma_launcher_layout）。
- 正式注册四件套（TEMPLATE_META/NOMINAL、docs meta.yaml、EXPECTED_TEMPLATES、
  fake 派发、template_specs）——test_registered_* 钉。
- 锚判据：port2 β→HJ（port1 集总桥无 β）；|S11| 文献曲线门（edge-launch
  SMA 带内回损常规 15-20dB，保守地板 -10dB）；fake=同轴段+微带段理想级联
  （独立 skrf 级联构造互证，#118）。
- #212 制度化：render → exec 几何段 → CSXCAD 实测（秒级零仿真）+ 精确实体
  接触图（圆盘/圆环-矩形距离判据，禁 bbox 近似）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import diag_sma_launcher as diag
from rfauto.adapters import fake_adapter as fa
from rfauto.adapters import openems_templates as ot
from tests.unit import _geometry_audit_helpers as gh

MESH_MM = 0.4
BAND = (2.25, 2.75)
F0 = 2.5
BOARD_MM = 60.0
H_SUB_MM = 0.508
NOMINAL = dict(ot.SMA_LAUNCHER_NOMINAL)
LAY = ot.sma_launcher_layout(NOMINAL, H_SUB_MM * 1e-3, MESH_MM * 1e-3)


def _load(params: dict | None = None, mesh_mm: float = MESH_MM):
    """渲染 sma_launcher → exec 几何段 → (脚本作用域, 精确实体列表)。"""
    resolved = dict(NOMINAL if params is None else params)
    text = ot.render_script("sma_launcher", resolved, BAND,
                            mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_sma_audit_sim.py")}
    exec(compile(head, "sma_audit", "exec"), scope)
    return scope, diag.extract_solids(scope["CSX"])


def _bbox_prims(params: dict | None = None):
    """gh 包围盒口径（轴向感知柱扩张），供签名/网格判据复用。"""
    resolved = dict(NOMINAL if params is None else params)
    return gh.load_geometry("sma_launcher", resolved, MESH_MM)


# ─── 注册四件套 ──────────────────────────────────────────────────────────────

def test_registered_in_registry():
    assert ot.TEMPLATE_META["sma_launcher"] is ot.SMA_LAUNCHER_META
    assert ot.TEMPLATE_NOMINAL["sma_launcher"] is ot.SMA_LAUNCHER_NOMINAL
    assert set(ot.SMA_LAUNCHER_META["params"]) == set(NOMINAL)
    assert ot._TEMPLATE_PORT_AXES["sma_launcher"] == ("y",)
    assert ot._TEMPLATE_RADIATOR["sma_launcher"] is False
    assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)


def test_registration_surface_complete():
    import yaml

    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

    bootstrap_template_specs()
    assert "sma_launcher" in EXPECTED_TEMPLATES
    spec = TEMPLATE_SPECS.get("sma_launcher")
    assert spec is not None
    assert TEMPLATE_SPECS.component("sma_launcher", "fake_model") is fa._sma_launcher_sparams
    assert spec.hfss_plugin is None
    assert spec.physics_roles["w_msl_mm"] == "line_width_mm"
    assert callable(TEMPLATE_SPECS.component("sma_launcher", "render_script"))
    meta = yaml.safe_load((REPO / "docs" / "templates" / "sma_launcher"
                           / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["template"] == "sma_launcher" and meta["n_ports"] == 2
    assert set(meta["params"]) == set(NOMINAL)
    for k, v in NOMINAL.items():
        assert float(meta["nominal_params"][k]) == pytest.approx(float(v), rel=1e-12), k
    assert "r_os_mm" not in meta["params"], "r_os 为派生量（r_o+shell_t），不进 params"


# ─── 同轴闭式、几何单源与综合链 ─────────────────────────────────────────────

def test_coax_closed_form_roundtrip():
    """Z0=(60/√εr)·ln(r_o/r_i)：NOMINAL (r_i,r_o) 回代恰 50Ω；反解再生。"""
    ri, ro, er = NOMINAL["r_i_mm"], NOMINAL["r_o_mm"], NOMINAL["er_fill"]
    z0 = 60.0 / er ** 0.5 * np.log(ro / ri)
    assert float(z0) == pytest.approx(50.0, abs=0.01)
    assert ot.sma_launcher_r_o_mm(ri, er, 50.0) == pytest.approx(ro, rel=1e-4)
    assert ot.sma_launcher_r_o_mm(ri, er, 30.0) == pytest.approx(
        ri * np.exp(30.0 * er ** 0.5 / 60.0), rel=1e-12)


def test_layout_single_source_matches_script_scope():
    """脚本内 Z_G/Z_TOP/Z_AX/Y_* 字面量与 sma_launcher_layout 逐位同源；
    夹具口径关系：Z_AX=r_os、壳底=0、针底切线=Z_TOP=基板顶、Z_G>0。"""
    scope, _ = _load()
    for key, name in (("z_ax", "Z_AX"), ("z_g", "Z_G"), ("z_top", "Z_TOP"),
                      ("y_b", "Y_B"), ("y_p0", "Y_P0"), ("y_e", "Y_E"),
                      ("y_pe", "Y_PE"), ("y1", "Y1"), ("ros", "ROS"),
                      ("f_w", "F_W"), ("f_t", "F_T"), ("f_z", "F_Z")):
        assert float(scope[name]) == LAY[key], name
    # v2 连接器体前脸：半宽/顶 = 壳外径 + 2 cells，厚 2 cells，与板边（Y_E）齐平
    assert LAY["f_w"] == pytest.approx(LAY["ros"] + 2 * MESH_MM * 1e-3, abs=1e-15)
    assert LAY["f_t"] == pytest.approx(2 * MESH_MM * 1e-3, abs=1e-15)
    assert LAY["f_z"] == pytest.approx(LAY["z_ax"] + LAY["ros"] + 2 * MESH_MM * 1e-3, abs=1e-15)
    assert LAY["z_ax"] == LAY["ros"]
    assert LAY["z_ax"] - LAY["ros"] == 0.0
    assert LAY["z_top"] == pytest.approx(LAY["z_ax"] - LAY["ri"], abs=1e-15)
    assert LAY["z_g"] > 0.0 and LAY["z_top"] == LAY["z_g"] + H_SUB_MM * 1e-3
    # port1 面距 y-min 边界 12 cells；开口同轴端再后退 2 cells
    assert LAY["y_p0"] == pytest.approx(-0.060 + 12 * MESH_MM * 1e-3, abs=1e-15)
    assert LAY["y_b"] == pytest.approx(LAY["y_p0"] - 2 * MESH_MM * 1e-3, abs=1e-15)
    assert LAY["y_e"] == pytest.approx(LAY["y_p0"] + NOMINAL["shell_len_mm"] * 1e-3, abs=1e-15)


def test_layout_validation():
    with pytest.raises(ValueError):
        ot.sma_launcher_layout(dict(NOMINAL, r_i_mm=3.0), H_SUB_MM * 1e-3, 0.4e-3)
    with pytest.raises(ValueError):
        ot.sma_launcher_layout(dict(NOMINAL, shell_t_mm=0.0), H_SUB_MM * 1e-3, 0.4e-3)
    with pytest.raises(ValueError):   # r_os−r_i ≤ H_SUB：抬板高度非正
        ot.sma_launcher_layout(dict(NOMINAL, r_i_mm=0.635, r_o_mm=0.9,
                                    shell_t_mm=0.1), H_SUB_MM * 1e-3, 0.4e-3)
    with pytest.raises(ValueError):   # 体带越板
        ot.sma_launcher_layout(dict(NOMINAL, line_len_mm=120.0), H_SUB_MM * 1e-3, 0.4e-3)


def test_synthesis_matches_nominal():
    from rfauto.core.synthesis import synthesize_sma_launcher_model

    synth = synthesize_sma_launcher_model(
        50.0, F0, r_i_mm=NOMINAL["r_i_mm"], er_fill=NOMINAL["er_fill"],
        shell_thick_mm=NOMINAL["shell_t_mm"], shell_len_mm=NOMINAL["shell_len_mm"],
        line_len_mm=NOMINAL["line_len_mm"], pin_lay_mm=NOMINAL["pin_lay_mm"],
        port_len_mm=NOMINAL["port_len_mm"])
    for key in NOMINAL:
        assert round(synth.params[key], 4) == pytest.approx(NOMINAL[key], rel=1e-12), key
    assert set(synth.params) == set(NOMINAL) | {"f0_ghz"}
    # -10dB 文献保守地板进 objectives（方案行"验收靠文献曲线"口径）
    obj = synth.recipe_draft["objectives"][0]
    assert obj["metric"] == "s11_db" and obj["value"] == -10.0


def test_synthesis_validation():
    from rfauto.core.synthesis import synthesize_sma_launcher_model

    with pytest.raises(ValueError):
        synthesize_sma_launcher_model(r_i_mm=0.01)
    with pytest.raises(ValueError):
        synthesize_sma_launcher_model(er_fill=0.5)
    with pytest.raises(ValueError):
        synthesize_sma_launcher_model(shell_thick_mm=0.0)


# ─── fake 裁判：同轴+微带理想级联（独立 skrf 构造互证，#118）─────────────────

FREQS = np.linspace(2.0, 3.0, 201)
_C0 = 299792458.0


def test_fake_matches_independent_skrf_cascade():
    """两段独立长度级联 vs skrf DefinedGammaZ0 级联（全带逐点一致）。"""
    import skrf

    e_coax, e_msl = 2.1, 2.852725
    s = fa._sma_launcher_sparams(FREQS, eps_eff_coax=e_coax,
                                 eps_eff_msl=e_msl, z_coax=50.0, z_msl=50.0,
                                 coax_len_mm=5.0, msl_len_mm=40.0, tan_d=0.0)
    freq = skrf.Frequency(float(FREQS[0]), float(FREQS[-1]), len(FREQS),
                          unit="GHz")

    def _gamma(ere: float) -> np.ndarray:
        return 1j * 2.0 * np.pi * (FREQS * 1e9) * ere ** 0.5 / _C0

    seg1 = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0,
                                     gamma=_gamma(e_coax)).line(
        5.0, unit="mm", z0=50.0)
    seg2 = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0,
                                     gamma=_gamma(e_msl)).line(
        40.0, unit="mm", z0=50.0)
    net = skrf.network.connect(seg1, 1, seg2, 0)
    assert float(np.max(np.abs(s - net.s))) < 1e-9


def test_fake_lossless_reciprocal_matched():
    """理想弹射：无耗幺正+互易；同阻级联 S11≈0（引擎偏差=寄生主信号）。"""
    s = fa._sma_launcher_sparams(FREQS, eps_eff_coax=2.1, eps_eff_msl=2.8527,
                                 z_coax=50.0, z_msl=50.0,
                                 coax_len_mm=5.0, msl_len_mm=40.0, tan_d=0.0)
    p = np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2
    assert float(np.max(np.abs(p - 1.0))) < 1e-9
    assert float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0]))) < 1e-12
    assert float(np.max(np.abs(s[:, 0, 0]))) < 1e-9
    i0 = int(np.argmin(np.abs(FREQS - F0)))
    ph = -(2 * np.pi * F0 * 1e9 / _C0) * (2.1 ** 0.5 * 5.0e-3
                                          + 2.8527 ** 0.5 * 40.0e-3)
    assert float(np.angle(s[i0, 1, 0])) == pytest.approx(
        float(np.angle(np.exp(1j * ph))), abs=1e-6)


def test_fake_dispatch_matches_closed_form_phase():
    """FakeAdapter(model_type='sma_launcher') 派发：S21 解缠相位斜率 = 同轴 TEM
    段 + 微带 HJ 段闭式；同轴 50Ω 闭式 → S11≈0；er_fill 驱动电气（#154）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter
    from rfauto.core.synthesis import Stackup, forward_z0

    ad = FakeAdapter(model_type="sma_launcher", n_ports=2,
                     freq_ghz=(2.25, 2.75, 201), f0_ghz=F0)
    ad.connect({})
    ad.set_variables({k: f"{v}mm" if k != "er_fill" else str(v)
                      for k, v in NOMINAL.items()})
    ad.solve("main_setup")
    net = ad.get_sparams()
    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    _, eps_msl = forward_z0(NOMINAL["w_msl_mm"], F0, st)
    phase = np.unwrap(np.angle(net.s[:, 1, 0]))
    slope = np.polyfit(net.f, phase, 1)[0]   # −2π(√εc·Lc + √εm·Lm)/c
    elec = (NOMINAL["er_fill"] ** 0.5 * NOMINAL["shell_len_mm"]
            + eps_msl ** 0.5 * NOMINAL["line_len_mm"]) * 1e-3
    assert -slope * _C0 / (2 * np.pi) == pytest.approx(elec, rel=2e-3)
    assert float(np.max(np.abs(net.s[:, 0, 0]))) < 1e-3
    ad.set_variables({"er_fill": "3.0"})
    ad.solve("main_setup")
    assert not np.allclose(np.angle(ad.get_sparams().s[:, 1, 0]), np.angle(net.s[:, 1, 0]))


# ─── 渲染结构 ────────────────────────────────────────────────────────────────

def test_render_structure():
    text = ot.render_script("sma_launcher", dict(NOMINAL), BAND,
                            mesh_resolution_mm=MESH_MM)
    compile(text, "gen", "exec")
    assert "LumpedPort(CSX, port_nr=1, R=50.0" in text
    assert 'exc_dir="z", excite=1, priority=6' in text
    assert "MSLPort(CSX, port_nr=2" in text
    assert 'CSX.AddMaterial("ptfe", epsilon=' in text
    assert 'CSX.AddMaterial("sma_notch", epsilon=1.0)' in text
    assert 'CSX.AddMetal("sma_gnd")' in text and 'CSX.AddMetal("sma_shell")' in text
    assert text.count("AddCylindricalShell") == 2
    assert 'from openEMS.ports import LumpedPort, MSLPort' in text
    # β 金标准只锚 port2（port1 集总桥无 β——LumpedPort 无 beta 属性）
    assert "beta1_rad_per_m" not in text and "beta2_rad_per_m" in text
    assert '["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"]' in text
    scope, _ = _load()
    assert float(scope["F0"]) == pytest.approx(F0 * 1e9, rel=1e-12)
    # er_fill 驱动介质材料常量（经 ER_FILL 变量进 AddMaterial，不驱动导体）
    text2 = ot.render_script("sma_launcher", dict(NOMINAL, er_fill=2.2),
                             BAND, mesh_resolution_mm=MESH_MM)
    assert "ER_FILL = 2.2" in text2


def test_near_points_exact_edges():
    nx, ny = ot._near_points("sma_launcher", dict(NOMINAL), base_mm=MESH_MM)
    for edge in (-LAY["ri"], LAY["ri"], -LAY["ro"], LAY["ro"], -LAY["ros"],
                 LAY["ros"], -LAY["ri"] / 2, LAY["ri"] / 2,
                 -LAY["w_m"] / 2, LAY["w_m"] / 2, -LAY["f_w"], LAY["f_w"]):
        assert min(abs(v - edge) for v in nx) < 1e-12
    for edge in (LAY["y_b"], LAY["y_p0"], LAY["y_p0"] + LAY["plen"],
                 LAY["y_e"], LAY["y_pe"], LAY["y1"], LAY["y_e"] - LAY["f_t"]):
        assert min(abs(v - edge) for v in ny) < 1e-12


# ─── #212 离线几何审计（CSXCAD 实测）────────────────────────────────────────

def test_primitives_nonzero_and_entered_in_mesh():
    scope, prims = _bbox_prims()
    metal = [p for p in prims if p.kind == "Metal"]
    dielectric = {p.prop for p in prims if p.kind == "Material"}
    lumped = [p for p in prims if p.kind == "LumpedElement"]
    assert dielectric == {"substrate", "sma_notch", "ptfe"}
    assert len(lumped) == 1
    by_prop: dict[str, list] = {}
    for p in metal:
        by_prop.setdefault(p.prop, []).append(p)
    # sma_gnd 夹具块 1；sma_face 连接器体前脸 1（孔径按优先级挖空）；sma_shell 柱壳 1；
    # sma_pin 针柱 + 接触垫 + 焊锡 = 3；sma_strip 体带 + MSLPort 自画馈段 = 2
    assert {k: len(v) for k, v in by_prop.items()} == {
        "sma_gnd": 1, "sma_face": 1, "sma_shell": 1, "sma_pin": 3, "sma_strip": 2}
    assert by_prop["sma_shell"][0].prim_type == "6"
    assert sum(1 for p in by_prop["sma_pin"] if p.prim_type == "5") == 1
    for p in metal:
        assert int(np.sum(p.extent > 1e-12)) >= 2, f"{p.prop} 零体积原语"
    assert gh.off_mesh_planes(prims, scope) == []
    lines = {ax: gh.mesh_lines(scope, ax) for ax in ("x", "y", "z")}
    for p in [q for q in prims if gh.is_conductor(q)]:
        for index, axis in enumerate(("x", "y", "z")):
            if p.extent[index] > 1e-12:
                inside = lines[axis][(lines[axis] >= p.lo[index] - 1e-9)
                                     & (lines[axis] <= p.hi[index] + 1e-9)]
                assert inside.size >= 1, f"{p.prop} 在 {axis} 轴未进网格"
    # 柱/柱壳轴向端面必须落 y 网格线（阶梯网格端面精确）
    yl = lines["y"]
    for p in [q for q in prims if q.prim_type in ("5", "6")]:
        assert float(np.min(np.abs(yl - p.lo[1]))) <= 1e-9
        assert float(np.min(np.abs(yl - p.hi[1]))) <= 1e-9


def test_coax_cross_section_and_layers_on_mesh():
    """同轴柱面界（z 向）、夹具底板、PCB 地、基板顶、桥两电极面恰在 z 网格线上。"""
    scope, _ = _load()
    zl = gh.mesh_lines(scope, "z")
    z_ax = LAY["z_ax"]
    for target in (0.0, z_ax - LAY["ro"], LAY["z_g"], LAY["z_top"], z_ax,
                   z_ax + LAY["ri"], z_ax + LAY["ro"], z_ax + LAY["ros"], LAY["f_z"]):
        assert float(np.min(np.abs(zl - target))) <= 1e-9, f"z={target} 未入网"
    assert float(zl.min()) == 0.0


def test_ports():
    scope, _ = _load()
    ports = gh.port_objects(scope)
    assert set(ports) == {1, 2}
    board = float(scope["BOARD"])
    p1 = ports[1]
    assert type(p1).__name__ == "LumpedPort"
    assert float(p1.R) == 50.0 and int(p1.exc_ny) == 2 and p1.excite == 1
    start1 = np.asarray(p1.start, dtype=float)
    stop1 = np.asarray(p1.stop, dtype=float)
    # 桥：x ±r_i/2、y [Y_P0, Y_P0+port_len]、z [针顶 Z_AX+r_i, 壳内壁顶 Z_AX+r_o]
    assert start1[0] == pytest.approx(-LAY["ri"] / 2) and stop1[0] == pytest.approx(LAY["ri"] / 2)
    assert start1[1] == pytest.approx(LAY["y_p0"], abs=1e-15)
    assert stop1[1] == pytest.approx(LAY["y_p0"] + LAY["plen"], abs=1e-15)
    assert start1[2] == pytest.approx(LAY["z_ax"] + LAY["ri"], abs=1e-15)
    assert stop1[2] == pytest.approx(LAY["z_ax"] + LAY["ro"], abs=1e-15)
    assert stop1[2] - start1[2] > 1e-9, "集总桥激励体积为零"
    p2 = ports[2]
    assert type(p2).__name__ == "MSLPort" and int(p2.prop_ny) == 1
    start2 = np.asarray(p2.start, dtype=float)
    stop2 = np.asarray(p2.stop, dtype=float)
    assert abs(abs(start2[1]) - board) <= 1e-9
    assert start2[2] == pytest.approx(LAY["z_top"], abs=1e-15)   # 微带面（抬板后）
    assert stop2[2] == pytest.approx(LAY["z_g"], abs=1e-15)      # 参考地 = 夹具块顶
    zl = gh.mesh_lines(scope, "z")
    assert float(np.min(np.abs(zl - start2[2]))) <= 1e-9


def test_exact_contact_graph_no_short_and_grounded():
    """精确实体接触图（H1/H2 根治回归钉，禁 bbox）：
    信号链 {针+接触垫+焊锡, 微带} 与地链 {壳, 夹具块, PEC 底板} 各自一个分量、
    互不接触；集总桥同时触针顶与壳内壁顶（桥接两链）；地链实触 PEC 底板。"""
    scope, solids = _load()
    g = diag.build_contact_graph(solids)
    rep = diag.structural_checks(scope, g)
    assert rep["signal_chain_one_component"], rep
    assert rep["ground_chain_one_component"], rep
    assert not rep["short_between_signal_and_ground"], rep
    assert rep["port1_bridges_both_chains"], rep
    # 逐对显式判据（精确几何）
    by = {}
    for s in solids:
        by.setdefault((s.prop, s.shape), []).append(s)
    pin = by[("sma_pin", "cyl")][0]
    shell = by[("sma_shell", "shell")][0]
    gnd = by[("sma_gnd", "box")][0]
    face = by[("sma_face", "box")][0]
    strips = by[("sma_strip", "box")]
    lumped = next(s for s in solids if s.kind == "LumpedElement")
    assert not diag.exact_contact_pair(pin, shell), "针-壳短路"
    assert not diag.exact_contact_pair(pin, gnd), "针-夹具短路"
    # v2 连接器体前脸：孔径由 PTFE 环/针按优先级挖空（Solid.bore），针穿孔不触；
    # 与壳/夹具/底板实触（地链）；不触微带/焊锡
    assert face.bore is not None and face.bore[2] == pytest.approx(LAY["ro"], abs=1e-15)
    assert not diag.exact_contact_pair(pin, face), "针-前脸短路（孔径挖空失效）"
    assert diag.exact_contact_pair(face, shell) and diag.exact_contact_pair(face, gnd)
    assert diag.touches_pec_floor(face)
    for st in strips:
        assert not diag.exact_contact_pair(st, shell), "微带-壳短路"
        assert not diag.exact_contact_pair(st, gnd), "微带-夹具短路（抬板失效）"
        assert not diag.exact_contact_pair(st, face), "微带-前脸短路"
    for box in by[("sma_pin", "box")]:
        assert not diag.exact_contact_pair(box, shell) and not diag.exact_contact_pair(box, gnd)
        assert not diag.exact_contact_pair(box, face), "焊锡/接触垫-前脸短路"
    assert diag.exact_contact_pair(lumped, pin) and diag.exact_contact_pair(lumped, shell)
    assert diag.exact_contact_pair(shell, gnd), "壳端未触夹具前脸"
    assert diag.touches_pec_floor(shell) and diag.touches_pec_floor(gnd)
    assert not diag.touches_pec_floor(pin)
    # 针-微带实接触（焊锡 + 针底切线）
    assert any(diag.exact_contact_pair(pin, st) for st in strips)
    assert any(diag.exact_contact_pair(box, st) for box in by[("sma_pin", "box")]
               for st in strips)
    # 同心净空（精确径向）：针外缘 < PTFE 外径 = 壳内壁（H2 旧判据只算 x 半对角）
    assert pin.r_out < shell.r_in - 1e-9


def test_port1_outside_pml8_and_top_clearance():
    """H4/H5 回归钉：port1 桥整体越过 y-min PML_8（前 8 条网格线），域顶 MUR
    距壳顶 ≥ 4mm（根治前 0.25mm=1 cell）。"""
    scope, solids = _load()
    rep = diag.structural_checks(scope, diag.build_contact_graph(solids))
    assert not rep["port1_inside_pml8"], rep
    assert rep["port1_y_m"][0] > rep["pml8_edge_y_m"] + 1e-3, "port1 距 PML_8 边 <1mm"
    assert rep["top_clearance_m"] >= 4e-3, rep


def test_edge_launch_geometry_relations():
    """H3 文献几何口径钉：针水平搭焊（针底切线=微带面）、壳底切夹具底板、壳体
    全在板边切口之外、针搭焊段在板上、PTFE 环填满针-壳间隙。"""
    _scope, solids = _load()
    by = {}
    for s in solids:
        by.setdefault((s.prop, s.shape), []).append(s)
    pin = by[("sma_pin", "cyl")][0]
    shell = by[("sma_shell", "shell")][0]
    ptfe = by[("ptfe", "shell")][0]
    gnd = by[("sma_gnd", "box")][0]
    notch = by[("sma_notch", "box")][0]
    sub = by[("substrate", "box")][0]
    strip = min(by[("sma_strip", "box")], key=lambda s: float(s.lo[1]))
    z_top = float(strip.lo[2])
    assert float(pin.center[1]) - pin.r_out == pytest.approx(z_top, abs=1e-15)   # 针底切线
    assert float(shell.center[1]) - shell.r_out == pytest.approx(0.0, abs=1e-15)  # 壳底切底板
    assert float(shell.hi[1]) <= float(gnd.lo[1]) + 1e-12       # 壳全在板边（夹具前脸）之外
    assert float(pin.hi[1]) > float(gnd.lo[1]) + 1e-3           # 针搭上板
    assert float(pin.hi[1]) == pytest.approx(LAY["y_pe"], abs=1e-15)
    assert ptfe.r_in == pytest.approx(pin.r_out, abs=1e-15) and \
        ptfe.r_out == pytest.approx(shell.r_in, abs=1e-15)      # PTFE 填满针-壳间隙
    assert float(sub.lo[2]) == pytest.approx(LAY["z_g"]) and float(sub.hi[2]) == pytest.approx(z_top)
    assert float(notch.hi[1]) == pytest.approx(LAY["y_e"]) and notch.priority > sub.priority
    assert float(notch.lo[2]) == pytest.approx(LAY["z_g"]) and float(notch.hi[2]) == pytest.approx(z_top)
    assert float(gnd.lo[1]) == pytest.approx(LAY["y_e"]) and float(gnd.hi[2]) == pytest.approx(LAY["z_g"])
    assert ptfe.priority < shell.priority and ptfe.priority > notch.priority


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
    spec = ot.geometry_spec("sma_launcher", dict(NOMINAL))
    names = [b["name"] for b in spec["boxes"]]
    assert names.count("substrate") == 1 and "ground" in names
    assert "coax_shell（弹射壳体）" in names and "coax_pin（中心针）" in names
    assert "solder（搭焊）" in names and "msl_feed" in names
    assert any(n.startswith("body_face") for n in names)
    assert len(spec["ports"]) == 2
    sub = next(b for b in spec["boxes"] if b["name"] == "substrate")
    assert sub["start_mm"][2] == pytest.approx(LAY["z_g"] * 1e3)


@pytest.mark.parametrize("key", sorted(NOMINAL))
def test_declared_params_drive_geometry(key):
    base = gh.conductor_signature([p for p in _bbox_prims()[1]
                                   if gh.is_conductor(p)])
    params = dict(NOMINAL)
    if key in ("er_fill", "tan_d_fill"):
        params[key] = float(NOMINAL[key]) + (0.2 if key == "er_fill" else 0.002)
        sig = gh.conductor_signature(
            [p for p in _bbox_prims(params)[1] if gh.is_conductor(p)])
        assert sig == base, f"{key} 不应驱动导体几何（材料参数，MATERIAL_VALUE_PARAMS）"
        assert key in gh.MATERIAL_VALUE_PARAMS["sma_launcher"]
        return
    params[key] = float(NOMINAL[key]) * 1.37 + 0.013
    changed = [p for p in _bbox_prims(params)[1] if gh.is_conductor(p)]
    assert gh.conductor_signature(changed) != base, \
        f"声明但未驱动几何的参数 {key}"


# ─── ③ 变体：PTFE 介质损耗 tan_d_fill → kappa（离线 + fake 一致）──────────────

def test_tan_d_fill_variant_drives_ptfe_kappa_and_fake_loss():
    """渲染：PT_TAND 字面量进 AddMaterial kappa（同基板 TAND 口径），名义 0 无耗
    与 pt3 真跑同口径；fake：同轴段独立 tanδ（seg1_tan_d）→ |S21| 按
    exp(−π f √εr tanδ L/c) 衰减，S11 不变（匹配级联）。"""
    text0 = ot.render_script("sma_launcher", dict(NOMINAL), BAND,
                             mesh_resolution_mm=MESH_MM)
    assert "PT_TAND = 0.0" in text0
    assert 'CSX.AddMaterial("ptfe", epsilon=ER_FILL,' in text0
    assert "kappa=PT_TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER_FILL" in text0
    text1 = ot.render_script("sma_launcher", dict(NOMINAL, tan_d_fill=0.002), BAND,
                             mesh_resolution_mm=MESH_MM)
    assert "PT_TAND = 0.002" in text1
    scope, _solids = _load(dict(NOMINAL, tan_d_fill=0.002))
    ptfe_prop = next(scope["CSX"].GetProperty(i) for i in range(scope["CSX"].GetQtyProperties())
                     if str(scope["CSX"].GetProperty(i).GetName()) == "ptfe")
    kappa = float(ptfe_prop.GetMaterialProperty("kappa"))
    assert kappa == pytest.approx(0.002 * 2 * np.pi * F0 * 1e9 * 8.854187817e-12
                                  * NOMINAL["er_fill"], rel=1e-9)
    # fake：tan_d_coax 只作用同轴段
    s0 = fa._sma_launcher_sparams(FREQS, eps_eff_coax=2.1, eps_eff_msl=2.8527,
                                  z_coax=50.0, z_msl=50.0, coax_len_mm=5.0,
                                  msl_len_mm=40.0, tan_d=0.0)
    s1 = fa._sma_launcher_sparams(FREQS, eps_eff_coax=2.1, eps_eff_msl=2.8527,
                                  z_coax=50.0, z_msl=50.0, coax_len_mm=5.0,
                                  msl_len_mm=40.0, tan_d=0.0, tan_d_coax=0.002)
    i0 = int(np.argmin(np.abs(FREQS - F0)))
    alpha_l = np.pi * F0 * 1e9 * 2.1 ** 0.5 * 0.002 * 5.0e-3 / _C0
    assert abs(s1[i0, 1, 0]) / abs(s0[i0, 1, 0]) == pytest.approx(np.exp(-alpha_l), rel=1e-9)
    assert float(np.max(np.abs(s1[:, 0, 0]))) < 1e-6
    # 派发：tan_d_fill 变量进 fake（数值/字符串均可解析）
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="sma_launcher", n_ports=2,
                     freq_ghz=(2.25, 2.75, 51), f0_ghz=F0)
    ad.connect({})
    ad.set_variables(dict(NOMINAL))
    ad.solve("a")
    base_s21 = np.abs(ad.get_sparams().s[:, 1, 0])
    ad.set_variables({"tan_d_fill": 0.01})
    ad.solve("b")
    assert bool(np.all(np.abs(ad.get_sparams().s[:, 1, 0]) < base_s21))
