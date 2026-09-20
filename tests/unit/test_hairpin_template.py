"""WP2.3 Tier 1：发夹线（hairpin）带通滤波器模板单测（#206 理论核验轮 + #212）。

模板已**正式注册**（2026-09-12 合流待办①）：openems_templates.HAIRPIN_META/
HAIRPIN_NOMINAL 同对象入 TEMPLATE_META/TEMPLATE_NOMINAL，注册四件套同步——
docs/templates/hairpin/meta.yaml、test_template_geometry_audit 的
EXPECTED_TEMPLATES（17→18）、fake_adapter 派发（_hairpin_sparams）、
models/template_specs（_register_hairpin）。render_script("hairpin", ...)
经 _TEMPLATE_PORT_AXES/_TEMPLATE_RADIATOR 既有键功能完整（渲染段零改动）。

理论核验轮口径（来源见 openems_templates 文末 WP2.3 hairpin 段）：
① 展开臂长 L_tot = λg/2 = c/(2 f0 √εeff)（Pozar；与 core/thermo_mech 同式）；
② 平行耦合半波谐振器 k = (Z0e − Z0o)/(Z0e + Z0o)（Hong §5.4；Z0e/Z0o 取
   Kirschning-Jansen 1984 耦合微带准静态闭式，零厚/无盖口径）；
③ C13 映射 k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)（Hong §5.2/5.3）；
④ 抽头外部 Q：Q_e = (π/2)(Z0/Z_r)sec²(πτ)（本仓派生，单测以精确分布参数
   Y_res(ω) 数值微分独立校核，#118）。

独立裁判（非自证）：
- 经典切比雪夫 g 值闭式（Pozar §8.4，core/matching.chebyshev_g_values）与
  C13 矩阵映射互检：Q_e=g0·g1/FBW、k_{i,i+1}=FBW/√(g_i g_{i+1})（实测 ±0.002%）；
- C13 矩阵理想频响 coupling_matrix_response：f0 处 |S21|=0、带边回损≈−RL、
  带外抑制（带通定义性质）；
- #212 离线几何审计：render → exec 几何段 → CSXCAD 实测原语/网格/端口
  （连通性判据对耦合滤波器族是**N 个 DC 隔离谐振器**，与功分器族不同）。
"""

from __future__ import annotations

import math
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot
from rfauto.core.matching import chebyshev_g_values
from tests.unit import _geometry_audit_helpers as gh

MESH_MM = 0.4          # 收敛档网格（#198/#212 口径）
BAND = (2.25, 2.75)    # 审计频带（f0=2.5GHz ±0.25）
F0 = 2.5
FBW = 0.05
RL_DB = 20.0
NOMINAL = dict(ot.HAIRPIN_NOMINAL)
DESIGN = ot.hairpin_design_from_order(3, F0, FBW, RL_DB)


def _load(params: dict | None = None, mesh_mm: float = MESH_MM):
    """渲染 hairpin → exec 几何段（FDTD.Run 之前）→ (脚本作用域, 原语列表)。"""
    resolved = dict(NOMINAL if params is None else params)
    text = ot.render_script("hairpin", resolved, BAND, mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_hairpin_audit_sim.py")}
    exec(compile(head, "hairpin_audit", "exec"), scope)
    return scope, gh.extract_primitives(scope["CSX"])


def _ripple_db(rl_db: float) -> float:
    """回损纹波 RL(dB) → 切比雪夫通带纹波 L_Ar(dB)：ε²=1/(10^(RL/10)−1)。"""
    return 10.0 * math.log10(1.0 + 1.0 / (10.0 ** (rl_db / 10.0) - 1.0))


# ─── 正式注册（2026-09-12 合流待办①：原"附加不注册"边界升格）───────────────

def test_hairpin_registered_in_registry():
    """hairpin 已正式注册：同对象入两表（#230 契约的注册态半边）。"""
    assert ot.HAIRPIN_META["f0_ghz"] > 0 and ot.HAIRPIN_NOMINAL["order"] >= 2
    # 注册 = 同对象入两表（单一事实源，防双份字典漂移）
    assert ot.TEMPLATE_META["hairpin"] is ot.HAIRPIN_META
    assert ot.TEMPLATE_NOMINAL["hairpin"] is ot.HAIRPIN_NOMINAL
    # 注册表两表条目集一致（含 hairpin 后仍闭合）
    assert "hairpin" in ot.TEMPLATE_META and "hairpin" in ot.TEMPLATE_NOMINAL
    assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)
    meta = ot.template_meta("hairpin")
    assert meta["template"] == "hairpin"
    assert meta["f0_ghz"] == ot.HAIRPIN_META["f0_ghz"]
    assert meta["n_ports"] == 2
    assert meta["nominal_params"] == ot.HAIRPIN_NOMINAL
    # 渲染派发键保持（单轴 PML + 非辐射器件）
    assert ot._TEMPLATE_PORT_AXES["hairpin"] == ("x",)
    assert ot._TEMPLATE_RADIATOR["hairpin"] is False


def test_hairpin_registration_surface_complete():
    """注册四件套同步（合流待办①）：docs meta.yaml / EXPECTED_TEMPLATES /
    template_specs；fake 派发见 TestHairpinFakeDispatch。"""
    import yaml

    data = yaml.safe_load(
        (REPO / "docs" / "templates" / "hairpin" / "meta.yaml")
        .read_text(encoding="utf-8"))
    assert data["template"] == "hairpin"
    assert float(data["f0_ghz"]) == pytest.approx(
        float(ot.HAIRPIN_META["f0_ghz"]), rel=1e-12)
    assert int(data["n_ports"]) == ot.HAIRPIN_META["n_ports"]
    assert list(data["params"]) == list(ot.HAIRPIN_META["params"])
    assert {k: float(v) if not isinstance(v, int) else v
            for k, v in data["nominal_params"].items()} \
        == dict(ot.HAIRPIN_NOMINAL)
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES
    assert "hairpin" in EXPECTED_TEMPLATES
    # 覆盖基线历史：17→18（hairpin，2026-09-12）→25（coupled_bpf + 天线族 II 六件，
    # 2026-09-14）→28（§C3）→30（C9）→36（§C4/C2，2026-09-16 树面实测）。精确计数由
    # test_template_geometry_audit.test_template_coverage_locked 单源锁定（#97/#228：
    # 多轨并行时本处再钉一份只会在他轨合流瞬间假红），本处只钉 hairpin 归属与两表闭合。
    assert len(EXPECTED_TEMPLATES) >= 36
    assert EXPECTED_TEMPLATES.issubset(ot.TEMPLATE_META)
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("hairpin")
    assert spec.meta["n_ports"] == 2
    assert callable(TEMPLATE_SPECS.component("hairpin", "render_script"))
    assert callable(TEMPLATE_SPECS.component("hairpin", "fake_model"))
    roles = dict(spec.physics_roles)
    assert roles["w_mm"] == "line_width_mm"
    assert roles["arm_len_mm"] == "resonator_length_mm"


def test_hairpin_meta_interface():
    meta = ot.hairpin_meta()
    assert meta["template"] == "hairpin"
    assert meta["f0_ghz"] == ot.HAIRPIN_META["f0_ghz"] > 0
    assert meta["n_ports"] == 2
    assert meta["max_time_ns"] > 0 and meta["mesh_resolution_mm"] >= 0
    assert meta["params"] and "coupling_matrix_response" in meta["extraction"]
    assert meta["nominal_params"] == ot.HAIRPIN_NOMINAL


def test_render_hairpin_structure():
    text = ot.render_script("hairpin", dict(NOMINAL), BAND,
                            mesh_resolution_mm=MESH_MM)
    compile(text, "gen", "exec")                     # 语法门（#201 制度化）
    for n in (1, 2):
        assert f"MSLPort(CSX, port_nr={n}" in text
    assert text.count('prop_dir="x"') == 2           # 两端口均在 x 边界
    assert "for _i in range(N):" in text             # N 阶谐振器循环渲染
    assert text.count("hairpin.AddBox") == 5         # 3（循环内）+ 2 抽头馈线
    assert "port_beta.csv" in text                   # β 金标准插桩（#162）
    # 边界：x 轴 PML（端口面）、y 轴 MUR、z-min PEC 地、z-max MUR
    assert '["PML_8", "PML_8", "MUR", "MUR", "PEC", "MUR"]' in text
    # 默认参数渲染（空 dict）与 nominal 渲染均为合法脚本
    assert compile(ot.render_script("hairpin", {}, BAND,
                                    mesh_resolution_mm=MESH_MM),
                   "gen_default", "exec") is not None


def test_near_points_exact_edges():
    """全部臂缘/弯带缘/抽头缘精确入网（#198 精确入网；防缝区吸附坍缩）。"""
    lay = ot._hairpin_layout(NOMINAL)
    nx, ny = ot._near_points("hairpin", dict(NOMINAL))
    wf = lay["wf"]
    for i in range(lay["n"]):
        for x in (lay["xs"][2 * i], lay["xs"][2 * i + 1]):
            for edge in (x - wf / 2, x + wf / 2):
                assert min(abs(v - edge) for v in nx) < 1e-12
    for edge in (lay["y0"], lay["y1"] - wf / 2, lay["y1"] + wf / 2,
                 lay["y_tap"] - wf / 2, lay["y_tap"] + wf / 2):
        assert min(abs(v - edge) for v in ny) < 1e-12


# ─── #212 离线几何审计（CSXCAD 实测，秒级零仿真）────────────────────────────

def test_primitives_nonzero_and_entered_in_mesh():
    scope, prims = _load()
    metal = [p for p in prims if p.kind == "Metal"]
    dielectric = [p for p in prims if p.kind == "Material"]
    assert len(metal) == 13                         # 3 谐振器×3 + 4 馈线原语
    assert len(dielectric) == 1                     # 基板
    for p in metal:
        assert int(np.sum(p.extent[:2] > 1e-12)) == 2   # 面内非零面积
    for p in dielectric:
        assert bool(np.all(p.extent > 1e-12))
    assert gh.off_mesh_planes(prims, scope) == []   # 零厚面恰在网格线
    lines = {ax: gh.mesh_lines(scope, ax) for ax in ("x", "y", "z")}
    for p in [q for q in prims if gh.is_conductor(q)]:
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
        stop = np.asarray(port.stop, dtype=float)
        ext = np.abs(start - stop)
        axis = int(port.prop_ny)
        assert abs(abs(start[axis]) - board) <= 1e-9, \
            f"port{number} 端口面未贴板边（{start[axis]}）"
        assert int(np.sum(ext > 1e-9)) >= 2, f"port{number} 端口面退化 {ext}"
        assert float(np.min(np.abs(z_lines - start[2]))) <= 1e-6, \
            f"port{number} 金属面 z 未入网"


def test_connectivity_n_dc_isolated_resonators():
    """耦合滤波器定义性质：N 个谐振器 DC 隔离（靠缝耦合），端口分属两端。

    与功分器族（全端口同属一个导体网络）判据相反——相邻谐振器短路即红。
    """
    scope, prims = _load()
    conductors, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == int(NOMINAL["order"])   # N 个独立连通分量
    counts = Counter(labels)
    assert min(counts.values()) >= 3                   # 每腔至少双臂+弯带
    ports = gh.port_objects(scope)
    comp_of: dict[int, int] = {}
    for number, port in ports.items():
        on = gh.containing_labels(gh.port_feed_point(port), conductors, labels)
        assert on, f"port{number} 馈电点不在任何导体上（激励悬空）"
        assert len(on) == 1
        comp_of[number] = next(iter(on))
    assert comp_of[1] != comp_of[2], "输入/输出谐振器短路（缝塌缩）"


def test_mesh_min_gap_guard_and_domain():
    scope, _ = _load()
    board = float(scope["BOARD"])
    for axis in ("x", "y", "z"):
        lines = gh.mesh_lines(scope, axis)
        assert lines.size >= 2
        diffs = np.diff(lines)
        assert bool(np.all(diffs > 1e-6)), f"{axis} 轴 <1µm 近重合线（#152）"
        assert bool(np.all(diffs > 0))
    for axis in ("x", "y"):
        lines = gh.mesh_lines(scope, axis)
        assert lines.min() == pytest.approx(-board, abs=1e-9)
        assert lines.max() == pytest.approx(board, abs=1e-9)


@pytest.mark.parametrize("key", list(ot.HAIRPIN_META["params"]))
def test_declared_params_drive_geometry(key):
    base = gh.conductor_signature(_load()[1])
    params = dict(NOMINAL)
    if key == "tap_frac":
        params[key] = float(NOMINAL[key]) * 0.9        # 保持 (0,0.5) 合法域
    else:
        params[key] = float(NOMINAL[key]) * 1.37 + 0.013
    assert gh.conductor_signature(_load(params)[1]) != base, \
        f"声明但未驱动几何的参数 {key}"


def test_layout_spacing_matches_coupling_gaps():
    lay = ot._hairpin_layout(NOMINAL)
    wf, b = lay["wf"], lay["b"]
    assert 2.0 * lay["l_arm"] + b == pytest.approx(lay["total"], rel=1e-12)
    for i in range(lay["n"]):
        assert (lay["xs"][2 * i + 1] - lay["xs"][2 * i]) - wf \
            == pytest.approx(lay["arm_gap"], rel=1e-12)
    for i in range(lay["n"] - 1):
        right_edge = lay["xs"][2 * i + 1] + wf / 2
        left_edge = lay["xs"][2 * (i + 1)] - wf / 2
        assert left_edge - right_edge == pytest.approx(lay["gaps"][i], rel=1e-9)


def test_layout_validation():
    bad = dict(NOMINAL, tap_frac=0.6)
    with pytest.raises(ValueError):
        ot._hairpin_layout(bad)
    with pytest.raises(ValueError):
        ot._hairpin_layout(dict(NOMINAL, order=4, gaps_mm=[1.0, 1.0]))  # 长度须 3
    with pytest.raises(ValueError):
        ot._hairpin_layout(dict(NOMINAL, gap_mm=0.0))
    # 抽头落进弯带区（τ 过大）显式报错，不静默
    with pytest.raises(ValueError):
        ot._hairpin_layout(dict(NOMINAL, arm_gap_mm=8.0, tap_frac=0.42))


# ─── 理论核验：λg/2、耦合系数、抽头 Q_e ──────────────────────────────────────

def test_arm_len_is_lambda_g_over_2():
    from rfauto.core import thermo_mech as tm
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508)
    _, eps_eff = forward_z0(1.1134, F0, stackup)
    expect = 299.792458 / (2.0 * F0 * math.sqrt(eps_eff))
    assert ot.hairpin_arm_len_mm(F0, 1.1134) == pytest.approx(expect, rel=1e-12)
    # 独立来源互检：core/thermo_mech 发夹谐振闭式（Pozar 同式）反解 f0
    assert tm.hairpin_resonance_ghz(expect, eps_eff) == pytest.approx(
        F0, rel=1e-9)


def test_coupled_microstrip_limits_and_monotonicity():
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508)
    z0_s, _ = forward_z0(1.1134, F0, stackup)
    # s→∞ 退化单线线（KJ 渐近；偏差随 s 单调收敛）
    devs = []
    for gap in (10.0, 20.0, 50.0):
        z0e, z0o, _, _ = ot.coupled_microstrip_even_odd_ohm(1.1134, gap, F0)
        devs.append(abs(z0o - z0_s) / z0_s)
        assert z0e > z0_s > z0o
    assert devs[2] < devs[1] < devs[0] < 5e-3
    # k(s) 严格单调递减（brentq 反解前置条件）
    grid = [0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0]
    ks = [ot.hairpin_k_from_gap_mm(s) for s in grid]
    assert all(a > b for a, b in pairwise(ks))
    for s, k in zip(grid, ks, strict=True):
        z0e, z0o, _, _ = ot.coupled_microstrip_even_odd_ohm(1.1134, s, F0)
        assert k == pytest.approx((z0e - z0o) / (z0e + z0o), rel=1e-12)


def test_gap_inversion_roundtrip():
    for k in (0.02, 0.035, 0.051514, 0.08, 0.12, 0.2):
        gap = ot.hairpin_gap_mm_from_k(k)
        assert gap > 0.0
        assert ot.hairpin_k_from_gap_mm(gap) == pytest.approx(k, rel=1e-6)
    with pytest.raises(ValueError):
        ot.hairpin_gap_mm_from_k(0.0)
    with pytest.raises(ValueError):
        ot.hairpin_gap_mm_from_k(0.999)     # 超出可达范围 → 显式报错


def test_tapped_line_qe_closed_form_vs_numeric():
    """抽头外部 Q 闭式 vs 精确分布参数数值微分（#118 独立校核）。

    Y_res(ω) = Y_r[tan(θτ)+tan(θ(1−τ))]，θ=πf/f0；电纳斜率
    b = (f0/2)·dB/df；Q_e = b·Z0（无损、单端口反射口径）。
    """
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508)
    z0_s, _ = forward_z0(1.1134, F0, stackup)
    f0_hz = F0 * 1e9

    def qe_numeric(tau: float, df_hz: float = 1.0e3) -> float:
        def _b(f_hz: float) -> float:
            theta = math.pi * f_hz / f0_hz
            return (math.tan(theta * tau)
                    + math.tan(theta * (1.0 - tau))) / z0_s
        dbdf = (_b(f0_hz + df_hz) - _b(f0_hz - df_hz)) / (2.0 * df_hz)
        return (f0_hz / 2.0) * dbdf * 50.0

    for tau in (0.15, 0.30, 0.4019, 0.45):
        closed = ot.hairpin_qe_from_tap_frac(tau, 50.0, z0_s)
        num = qe_numeric(tau)
        assert num == pytest.approx(closed, rel=1e-6)
        # 反解往返
        assert ot.hairpin_tap_frac_from_qe(closed, 50.0, z0_s) == \
            pytest.approx(tau, rel=1e-9)
    with pytest.raises(ValueError):
        ot.hairpin_qe_from_tap_frac(0.5)
    with pytest.raises(ValueError):
        ot.hairpin_tap_frac_from_qe(1.0)    # 低于 τ→0 可达下限


# ─── C13 映射 + 独立裁判（切比雪夫 g 值闭式 / 耦合矩阵频响）──────────────────

@pytest.mark.parametrize("order,rl,fbw", [(3, 20.0, 0.05), (4, 20.0, 0.04),
                                          (5, 15.0, 0.03)])
def test_c13_mapping_matches_chebyshev_g_values(order, rl, fbw):
    """C13 矩阵映射 k/Q_e 对照经典切比雪夫 g 值闭式（独立来源，Pozar §8.4）。"""
    design = ot.hairpin_design_from_order(order, F0, fbw, rl)
    g = chebyshev_g_values(order, _ripple_db(rl))
    assert design["qe"] == pytest.approx(g[0] * g[1] / fbw, rel=1e-3)
    for i, k in enumerate(design["k_list"], start=1):
        assert k == pytest.approx(fbw / math.sqrt(g[i] * g[i + 1]), rel=1e-3)


def test_design_geometry_roundtrip():
    from rfauto.core.synthesis import Stackup, inverse_width

    stackup = Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508)
    w_ref, _, _ = inverse_width(50.0, F0, stackup)
    assert DESIGN["w_mm"] == pytest.approx(w_ref, rel=1e-9)
    assert DESIGN["arm_len_mm"] == pytest.approx(
        ot.hairpin_arm_len_mm(F0, DESIGN["w_mm"]), rel=1e-9)
    for k, gap in zip(DESIGN["k_list"], DESIGN["gaps_mm"], strict=True):
        assert ot.hairpin_k_from_gap_mm(gap, DESIGN["w_mm"]) \
            == pytest.approx(k, rel=1e-6)
    # N=3 等 k → 等缝（模板 gap_mm 标量口径）
    assert DESIGN["gap_mm"] == pytest.approx(DESIGN["gaps_mm"][0], rel=1e-12)
    assert DESIGN["tap_frac"] == pytest.approx(
        ot.hairpin_tap_frac_from_qe(DESIGN["qe"]), rel=1e-12)


def test_c13_closed_form_response_is_bandpass():
    """C13 矩阵理想频响裁判：f0 处通带、带边回损≈−RL、带外抑制。"""
    from rfauto.core.calculators import coupling_matrix_response

    design = ot.hairpin_design_from_order(3, F0, FBW, RL_DB)
    f = np.linspace(F0 - 0.5, F0 + 0.5, 4001)
    resp = coupling_matrix_response(freq_ghz=list(f), f0_ghz=F0, fbw=FBW,
                                    matrix=design["coupling_matrix"])
    s11 = np.asarray(resp["s11_db"], dtype=float)
    s21 = np.asarray(resp["s21_db"], dtype=float)
    i0 = int(np.argmin(np.abs(f - F0)))
    assert s21[i0] == pytest.approx(0.0, abs=0.01)
    assert s11[i0] < -100.0
    band = (f >= F0 * (1 - FBW / 2)) & (f <= F0 * (1 + FBW / 2))
    assert s21[band].max() == pytest.approx(0.0, abs=0.02)
    assert s21[band].min() > -0.2                     # 带内纹波 ≈ 0.04dB
    assert s11[band].max() < -15.0                    # 带内回损 ≈ RL=20dB
    stop = np.abs(f - F0) / F0 > 0.10                 # 带外（4×带边外）
    assert s21[stop].min() < -30.0


def test_n4_nonuniform_gaps_variant():
    """非等 k 的横向变体：N=4 逐缝列表渲染，4 个 DC 隔离谐振器。"""
    design4 = ot.hairpin_design_from_order(4, F0, 0.04, RL_DB)
    assert design4["gap_mm"] is None                  # 不等缝 → 标量口径不适用
    assert design4["gaps_mm"][0] != pytest.approx(design4["gaps_mm"][1],
                                                  abs=1e-6)
    params = dict(NOMINAL, order=4, gaps_mm=design4["gaps_mm"],
                  arm_len_mm=design4["arm_len_mm"])
    _, prims = _load(params)
    _, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == 4


def test_geometry_spec_preview_consistency():
    """UI 3D 预览 spec 与渲染几何一致（防两处漂移）。"""
    spec = ot.geometry_spec("hairpin", dict(NOMINAL))
    names = [b["name"] for b in spec["boxes"]]
    assert names.count("substrate") == 1 and "ground" in names
    lay = ot._hairpin_layout(NOMINAL)
    assert len([n for n in names if n.startswith("hairpin_r")]) == 3 * lay["n"]
    assert "feed_in_tap" in names and "feed_out_tap" in names
    assert len(spec["ports"]) == ot.HAIRPIN_META["n_ports"]
    for port in spec["ports"]:
        assert abs(abs(port["pos_mm"][0]) - 60.0) < 1e-9


# ─── WP2.3 收口轮（2026-09-16）：A1 去嵌 / A2 名义定版 / A3 单谐振器 / A5 升格 core ───

def _port_probe_x(scope, port) -> np.ndarray:
    """复现 MSLPort 探针落点（ports.py:291-300：测量面吸附最近 x 网格线，探针 ±1 格）。"""
    lines = gh.mesh_lines(scope, "x")
    idx = int(np.argmin(np.abs(lines - float(port.measplane_pos))))
    idx = min(max(idx, 1), lines.size - 2)
    return lines[idx - 1: idx + 2]


@pytest.mark.parametrize("order", [3, 1])
def test_a1_measurement_plane_in_uniform_feed_before_tap(order):
    """A1 去嵌：两端口测量面 = 抽头结前 10·NEAR+4·H_SUB（自板边算 feed_len−该偏移），
    三探针全部落在均匀 50Ω 馈段内（首/末臂外缘之前）**且探针间距均匀**（openEMS β
    二阶差分假定均匀间距；首版纯 10·NEAR 落进结区网格加密过渡带 U_delta=[0.28,0.19]mm
    → β 金标准恒定 −23%，τ=0.30 真机实测），端口 start/FeedShift 不动。"""
    params = dict(NOMINAL)
    if order == 1:
        params = {k: v for k, v in params.items() if k != "gap_mm"}
        params["order"] = 1
    scope, _ = _load(params)
    ports = gh.port_objects(scope)
    board, near, wf = float(scope["BOARD"]), float(scope["NEAR"]), float(scope["WF"])
    h_sub, base = float(scope["H_SUB"]), float(scope["BASE"])
    offset = 10 * near + 4 * h_sub
    xs = list(scope["XS"])
    x_in, x_out = xs[0], xs[-1]
    # 请求测量面（吸附前）：port1 = XS[0]−offset；port2 = XS[-1]+offset
    assert float(ports[1].measplane_pos) == pytest.approx(x_in - offset, abs=1e-12)
    assert float(ports[2].measplane_pos) == pytest.approx(x_out + offset, abs=1e-12)
    # 端口面/激励位置不变（start 在板边，FeedShift=10·NEAR）
    assert abs(float(ports[1].start[0]) + board) <= 1e-12
    assert abs(float(ports[2].start[0]) - board) <= 1e-12
    assert float(ports[1].feed_shift) == pytest.approx(10 * near, rel=1e-12)
    # 探针全部在均匀馈段：port1 ∈ (−BOARD, XS[0]−WF/2)，port2 ∈ (XS[-1]+WF/2, BOARD)
    p1 = _port_probe_x(scope, ports[1])
    p2 = _port_probe_x(scope, ports[2])
    assert p1.size == 3 and p2.size == 3
    assert bool(np.all(p1 > -board)) and bool(np.all(p1 < x_in - wf / 2))
    assert bool(np.all(p2 < board)) and bool(np.all(p2 > x_out + wf / 2))
    # 探针间距均匀且 = base（β 二阶差分前提；加密过渡带外）
    for port in (ports[1], ports[2]):
        delta = np.abs(np.asarray(port.U_delta, dtype=float))   # port2 方向为负
        assert delta.size == 2
        assert delta[0] == pytest.approx(delta[1], rel=1e-9), delta
        assert delta[0] == pytest.approx(base, rel=0.05), (delta, base)
    # 去嵌量：吸附后测量面距板边 ≈ feed_len−offset（吸附误差 ≤ 网格半格 = BASE/2）
    feed_len = x_in + board
    assert float(ports[1].measplane_shift) == pytest.approx(feed_len - offset, abs=base / 2)
    assert float(ports[2].measplane_shift) == pytest.approx(board - x_out - offset,
                                                            abs=base / 2)
    # 旧口径 feed_len/3 留 2/3 未去嵌（≈0.49λg≈34mm）：新口径残量 ≤ offset+半格 ≈3.2mm
    assert feed_len - float(ports[1].measplane_shift) <= offset + base / 2
    assert feed_len - float(ports[1].measplane_shift) < feed_len / 10
    text = ot.render_script("hairpin", params, BAND, mesh_resolution_mm=MESH_MM)
    assert "MeasPlaneShift=(XS[0] + BOARD) - 10 * NEAR - 4 * H_SUB" in text
    assert "MeasPlaneShift=(BOARD - XS[-1]) - 10 * NEAR - 4 * H_SUB" in text
    assert "/ 3, priority" not in text.split("_port1 = MSLPort")[1].split("_port2 = MSLPort")[0]


def test_a2_arm_gap_rationale_k_self_below_mutual():
    """A2 名义 arm_gap 3.0 的理由钉死：k_self(3.0) < 互耦 k(设计缝) < k_self(1.0)。
    旧名义 1.0 的同臂自耦反超互耦（四轮真机 FAIL 的结构性根因）。数值出自 KJ 内核。"""
    k_self_new = ot.hairpin_k_from_gap_mm(3.0)
    k_self_old = ot.hairpin_k_from_gap_mm(1.0)
    k_mutual = float(DESIGN["k_list"][0])
    assert k_self_new < k_mutual < k_self_old
    assert k_self_new == pytest.approx(0.0115, abs=5e-4)
    assert k_mutual == pytest.approx(0.05151, abs=5e-5)
    assert k_self_old == pytest.approx(0.0602, abs=5e-4)
    assert k_mutual / k_self_new > 4.0            # 互耦 ≥4× 自耦
    assert NOMINAL["arm_gap_mm"] == 3.0
    assert DESIGN["arm_gap_mm"] == 3.0            # hairpin_design_from_order 默认
    assert ot._hairpin_layout({})["arm_gap"] == pytest.approx(3.0e-3, rel=1e-12)
    assert "3.0" in ot.HAIRPIN_META["param_semantics"]


def _tau_for_design_qe() -> float:
    """B1 修正 c(τ)=c0+c1·τ 下交付设计 Q_e 的抽头比例（brentq；c≡1 退化为闭式反解）。"""
    from scipy.optimize import brentq

    from rfauto.adapters.fake_adapter import _HAIRPIN_QE_CORR

    c0, c1 = _HAIRPIN_QE_CORR
    target = float(DESIGN["qe"])
    return float(brentq(lambda t: (c0 + c1 * t) * ot.hairpin_qe_from_tap_frac(t) - target,
                        0.05, 0.44, xtol=1e-12))


def test_a2_nominal_equals_design_chain_rounded():
    """A2 名义定版：名义四项几何 = hairpin_design_from_order(3,2.5,0.05,20) 按
    scripts/hairpin_calib design_params 同规则舍入（w/arm_len/gap 4 位、τ 6 位）——
    消 w 1.1134/1.1117、arm_len 35.4653/35.4676 双份微漂；meta.yaml 同源。"""
    from rfauto.adapters.fake_adapter import _HAIRPIN_F0_CORR

    assert NOMINAL["w_mm"] == round(DESIGN["w_mm"], 4)
    # arm_len 名义 = 闭式 λg/2 × 真机谐振修正 c_f0（B2 pt4 通带中心 2.5925/2.5=1.0370；
    # f∝1/L → L·f0_act/f0），fake 端同源常数 _HAIRPIN_F0_CORR
    assert abs(_HAIRPIN_F0_CORR - 1.0370) <= 1e-4
    assert NOMINAL["arm_len_mm"] == round(DESIGN["arm_len_mm"] * _HAIRPIN_F0_CORR, 4)
    assert NOMINAL["gap_mm"] == round(DESIGN["gap_mm"], 4)
    # tap_frac 名义 = B1 真机修正 c(τ) 下交付设计 Q_e 的 τ*（fake._HAIRPIN_QE_CORR 同源）：
    # c≡1 时退化为闭式 τ；本轮 c(τ)=1.37437−0.75218·τ（τ=0.40/0.43 两点）→ τ*=0.398159
    # ≠ 闭式 0.401892（B3 终验 pt5 用单点解 0.398227，Δτ≈2.5µm≪网格）
    from rfauto.adapters.fake_adapter import _HAIRPIN_QE_CORR
    c0, c1 = _HAIRPIN_QE_CORR
    tau_n = NOMINAL["tap_frac"]
    assert ot.hairpin_qe_from_tap_frac(tau_n) * (c0 + c1 * tau_n) ==         pytest.approx(DESIGN["qe"], rel=1e-4)                       # τ 6 位舍入量级
    assert tau_n == pytest.approx(_tau_for_design_qe(), abs=5e-7)
    # 名义 w 已 4 位舍入（1.11169→1.1117），以舍入 w 复算闭式臂长×c_f0 差 ≤1.6e-4mm
    assert NOMINAL["arm_len_mm"] == pytest.approx(
        ot.hairpin_arm_len_mm(F0, NOMINAL["w_mm"]) * _HAIRPIN_F0_CORR, abs=1.6e-4)
    from rfauto.core.synthesis import Stackup, forward_z0
    z0, _ = forward_z0(NOMINAL["w_mm"], F0,
                       Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508))
    assert z0 == pytest.approx(50.0, abs=0.01)    # 旧 1.1134 为 49.95Ω


def test_a3_single_resonator_order1_design_and_layout():
    """A3 单谐振器探针：hairpin_design_from_order(1) 不再 IndexError（gap_mm=None/
    gaps_mm=[]/k_list=[]），_hairpin_layout 放开 n≥1（XS=[左臂,右臂] 两抽头），n<1 报错。"""
    d1 = ot.hairpin_design_from_order(1, F0, FBW, RL_DB)
    assert d1["order"] == 1 and d1["gap_mm"] is None
    assert d1["gaps_mm"] == [] and d1["k_list"] == []
    assert d1["qe"] > 0 and 0.0 < d1["tap_frac"] < 0.5
    lay = ot._hairpin_layout({"order": 1, "w_mm": NOMINAL["w_mm"],
                              "arm_len_mm": NOMINAL["arm_len_mm"],
                              "arm_gap_mm": 3.0, "tap_frac": 0.40})
    assert lay["n"] == 1 and len(lay["xs"]) == 2 and lay["gaps"] == []
    assert lay["xs"][0] == pytest.approx(-lay["b"] / 2, rel=1e-12)
    assert lay["xs"][1] == pytest.approx(lay["b"] / 2, rel=1e-12)
    assert lay["x_feed_in"] == lay["xs"][0] and lay["x_feed_out"] == lay["xs"][1]
    for bad in (0, -1):
        with pytest.raises(ValueError):
            ot._hairpin_layout({"order": bad})
    # τ 上限守卫（arm_gap 3.0 下 τ_max≈0.442）：0.43 合法、0.45 落进弯带区报错
    ot._hairpin_layout({"order": 1, "arm_gap_mm": 3.0, "tap_frac": 0.43,
                        "arm_len_mm": NOMINAL["arm_len_mm"], "w_mm": NOMINAL["w_mm"]})
    with pytest.raises(ValueError):
        ot._hairpin_layout({"order": 1, "arm_gap_mm": 3.0, "tap_frac": 0.45,
                            "arm_len_mm": NOMINAL["arm_len_mm"], "w_mm": NOMINAL["w_mm"]})


def test_a3_single_resonator_geometry_audit():
    """A3 #212 离线几何审计覆盖 order=1：3 谐振器盒 + 2 抽头馈线 + 2 端口馈线 = 7 金属
    原语，单一导体连通分量且两端口馈电点同在其上（对称双端口探针的定义性质，
    与 N=3 的"N 个 DC 隔离谐振器"判据互补），网格守卫/端口面照旧。"""
    params = {k: v for k, v in NOMINAL.items() if k != "gap_mm"}
    params["order"] = 1
    scope, prims = _load(params)
    metal = [p for p in prims if p.kind == "Metal"]
    assert len(metal) == 7
    for p in metal:
        assert int(np.sum(p.extent[:2] > 1e-12)) == 2
    assert gh.off_mesh_planes(prims, scope) == []
    conductors, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == 1
    ports = gh.port_objects(scope)
    assert set(ports) == {1, 2}
    comps = set()
    for port in ports.values():
        on = gh.containing_labels(gh.port_feed_point(port), conductors, labels)
        assert len(on) == 1
        comps |= on
    assert len(comps) == 1                      # 两抽头同一谐振器
    for axis in ("x", "y", "z"):
        diffs = np.diff(gh.mesh_lines(scope, axis))
        assert bool(np.all(diffs > 1e-6))
    text = ot.render_script("hairpin", params, BAND, mesh_resolution_mm=MESH_MM)
    compile(text, "gen1", "exec")
    assert "N = 1\n" in text
    # geometry_spec 预览同步（3·n 个谐振器盒）
    spec = ot.geometry_spec("hairpin", params)
    assert len([b["name"] for b in spec["boxes"] if b["name"].startswith("hairpin_r")]) == 3


def test_a5_closed_forms_promoted_to_core_and_reexported():
    """A5 升格 core：闭式内核在 core/coupled_microstrip、设计链在 core/synthesis，
    openems_templates 仅再导出（同一函数对象，无遮蔽副本 #116）；template spec 的
    synthesizer 即 core.synthesize_hairpin_model；分层不破（core 不回引 adapters）。"""
    import ast
    import inspect

    from rfauto.core import coupled_microstrip as cm
    from rfauto.core import synthesis as syn

    for name in ("coupled_microstrip_even_odd_ohm", "hairpin_k_from_gap_mm",
                 "hairpin_gap_mm_from_k", "hairpin_qe_from_tap_frac",
                 "hairpin_tap_frac_from_qe", "hairpin_arm_len_mm"):
        assert getattr(ot, name) is getattr(cm, name), name
    assert ot.hairpin_design_from_order is syn.hairpin_design_from_order
    assert ot._HAIRPIN_50OHM_W_MM == cm.HAIRPIN_50OHM_W_MM == 1.1134
    src = inspect.getsource(ot)
    assert src.count("def coupled_microstrip_even_odd_ohm(") == 0
    assert src.count("def hairpin_design_from_order(") == 0
    # 分层不破：core 两模块（含函数体内惰性导入）不得引用 rfauto.core 之外的层
    for mod in (cm, syn):
        for node in ast.walk(ast.parse(inspect.getsource(mod))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("rfauto.") or \
                    node.module.startswith("rfauto.core"), node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("rfauto.") or \
                        alias.name.startswith("rfauto.core"), alias.name
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    assert TEMPLATE_SPECS.get("hairpin").synthesizer is syn.synthesize_hairpin_model
    res = syn.synthesize_hairpin_model(order=3, f0_ghz=F0, fbw=FBW, rl_db=RL_DB)
    assert res.model == "hairpin_bpf"
    assert set(res.params) == set(ot.HAIRPIN_NOMINAL)
    assert res.params["gap_mm"] == pytest.approx(DESIGN["gap_mm"], rel=1e-12)
    assert "gap_mm" not in syn.synthesize_hairpin_model(order=1).params   # N=1 无耦合缝


# ─── fake_adapter 派发（合流待办①③，atten 族模式）──────────────────────────

class TestHairpinFakeDispatch:
    """FakeAdapter(model_type="hairpin")：耦合矩阵理想频响裁判（确定性、零真机）。

    口径（与 _hairpin_sparams docstring 一致；2026-09-16 收口 A4 接通电气通道；
    2026-09-17 起 gap→k 乘 hairpin 结构修正 c(gap)）：
    arm_len→f0 走 λg/2 反演（hairpin_arm_len_mm 的精确逆）、order 变阶、
    gap_mm/gaps_mm→k（KJ 闭式 × c(gap) 真机表，域外 clamp）、tap_frac→Q_e（抽头
    闭式 × c(τ)）→ hairpin_coupling_matrix（规范不变）→ coupling_matrix_response。
    """

    F = np.linspace(2.0, 3.0, 401)

    @staticmethod
    def _solve(variables: dict | None = None,
               freq: tuple[float, float, int] = (2.0, 3.0, 401)):
        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter(model_type="hairpin", n_ports=2, freq_ghz=freq,
                         f0_ghz=2.5)
        ad.connect({})
        if variables:
            ad.set_variables(dict(variables))
        report = ad.solve("hairpin_fake")
        assert report.success
        return ad.get_sparams()

    def test_bandpass_shape_at_nominal(self):
        """名义几何在 EM 标定 fake 下=欠耦窄带（修正后的诚实状态）：名义 gap 1.1328 的
        k_EM=c(1.1328)·k_KJ=0.0133（c(gap) 结构修正），故 5% 设计窗内 |S21| 深陷、
        通带为 ~k_EM 限定的窄峰。修正链设计几何复现 C13 理想见
        test_a4_design_geometry_reproduces_c13_ideal。"""
        nt = self._solve()
        assert nt.s.shape[1:] == (2, 2)
        f = nt.frequency.f / 1e9
        s11 = 20.0 * np.log10(np.abs(nt.s[:, 0, 0]) + 1e-300)
        s21 = 20.0 * np.log10(np.abs(nt.s[:, 1, 0]) + 1e-300)
        assert abs(f[int(np.argmax(s21))] - 2.5) < 0.05       # 通带仍在设计 f0 附近
        band = (f >= 2.5 * (1 - 0.05 / 2)) & (f <= 2.5 * (1 + 0.05 / 2))
        # k_EM=0.0133 ≪ k_KJ=0.0515：5% 窗内欠耦（EM 真机同病，pt5 −8.6dB 同根源；
        # 无耗 fake 对称奇阶网络中心 |S21| 恒 1，欠耦只表现为窄峰+窗内回损差）
        assert s21[band].min() < -3.0
        bw3 = float(np.ptp(f[s21 >= s21.max() - 3.0]))
        assert bw3 < 0.03 * 2.5                               # 3dB 宽远窄于 5% 设计
        assert s11[band].max() > -10.0                        # 5% 窗内回损差（欠耦）
        stop = np.abs(f - 2.5) / 2.5 > 0.10
        assert s21[stop].min() < -30.0

    def test_passivity_reciprocity_mirror(self):
        nt = self._solve()
        s = nt.s
        assert float(np.max(np.abs(s - s.transpose(0, 2, 1)))) <= 1e-12
        assert float(np.max(np.abs(s[:, 0, 0] - s[:, 1, 1]))) <= 1e-12
        assert float(np.max(np.abs(s))) <= 1.0 + 1e-12

    def test_arm_len_drives_f0_lambda_g_over_2(self):
        """arm_len ×k → f0 ÷k（λg/2 反演）；函数级尺度不变 max|ΔS|=0。"""
        from rfauto.adapters.fake_adapter import _hairpin_sparams
        from rfauto.core.synthesis import Stackup, forward_z0

        stackup = Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508)
        _, eps_eff = forward_z0(1.1134, 2.5, stackup)

        def f0_of(l_mm: float) -> float:
            return (299792458.0 / (2.0 * l_mm * 1e-3
                                   * math.sqrt(eps_eff))) / 1e9

        f = self.F
        s_nom = _hairpin_sparams(f * 1.2, f0_ghz=f0_of(35.4653))
        s_scaled = _hairpin_sparams(f, f0_ghz=f0_of(35.4653 * 1.2))
        assert float(np.max(np.abs(s_scaled - s_nom))) <= 1e-12
        # 适配器级：通带峰随 arm_len 移动（网格量化 ±0.0025GHz 容差）
        nt1 = self._solve({"arm_len_mm": "35.4653mm"})
        nt2 = self._solve({"arm_len_mm": "42.55836mm"})
        p1 = (nt1.frequency.f / 1e9)[int(np.argmax(np.abs(nt1.s[:, 1, 0])))]
        p2 = (nt2.frequency.f / 1e9)[int(np.argmax(np.abs(nt2.s[:, 1, 0])))]
        assert p2 == pytest.approx(p1 / 1.2, abs=1.5 * (f[1] - f[0]))
        # 闭式互检：nominal 臂长反演 f0 ≈ 2.5（4 位舍入）
        assert f0_of(35.4653) == pytest.approx(2.5, abs=5e-4)

    def test_order_variable_rebuilds_matrix(self):
        """order 变阶：高阶带外抑制更陡（同 fbw/rl 设计点）。"""
        f = self.F
        stop = np.abs(f - 2.5) / 2.5 > 0.10
        s21_3 = 20.0 * np.log10(
            np.abs(self._solve({"order": "3"}).s[:, 1, 0]) + 1e-300)
        s21_5 = 20.0 * np.log10(
            np.abs(self._solve({"order": "5"}).s[:, 1, 0]) + 1e-300)
        assert s21_5[stop].max() < s21_3[stop].max() < 0.0

    def test_recipe_draft_via_spec(self):
        """draft_recipe 走 hairpin 设计链（确定性内核，零求解）。"""
        from rfauto.models.template_spec import TEMPLATE_SPECS
        from rfauto.models.template_specs import bootstrap_template_specs

        bootstrap_template_specs()
        draft = TEMPLATE_SPECS.draft_recipe(
            "hairpin", order=3, f0_ghz=2.5, fbw=0.05, rl_db=20.0)
        assert draft["model"] == "hairpin_bpf"
        assert {"order", "w_mm", "arm_len_mm", "arm_gap_mm", "gap_mm",
                "tap_frac"} <= set(draft["params"])
        assert draft["params"]["gap_mm"]["value"] == pytest.approx(1.1326,
                                                                   abs=1e-3)
        assert draft["objectives"][0]["value"] == -20.0

    # ─── A4 电气通道（2026-09-16 收口）：#1b 模型审计 + 几何→电气派发 ─────────────

    def test_a4_coupling_matrix_gauge_invariance(self):
        """#1b 审计：(k_list,Q_e)→N+2 矩阵在规范 fbw_g∈{0.05,0.10}（及 0.02/0.5/1.0）
        下响应不变 max|ΔS|≤1e-9——历史"fbw=1 偏差 6000dB"属未重归一的实现口径，非物理。"""
        from rfauto.adapters.fake_adapter import hairpin_coupling_matrix
        from rfauto.core.calculators import coupling_matrix_response

        k_list = [float(v) for v in DESIGN["k_list"]]
        qe = float(DESIGN["qe"])
        f = np.linspace(2.0, 3.0, 1001)

        def _s(g: float) -> np.ndarray:
            r = coupling_matrix_response(freq_ghz=list(f), f0_ghz=F0, fbw=g,
                                         matrix=hairpin_coupling_matrix(k_list, qe, g))
            c = np.asarray(r["s_matrix"], dtype=float)
            return c[..., 0] + 1j * c[..., 1]

        ref = _s(0.05)
        for g in (0.10, 0.02, 0.5, 1.0):
            assert float(np.max(np.abs(_s(g) - ref))) <= 1e-9, g
        m = np.asarray(hairpin_coupling_matrix(k_list, qe, 0.05))
        assert m.shape == (5, 5) and bool(np.all(np.diag(m) == 0.0))
        assert bool(np.allclose(m, m.T))
        assert m[0, 1] == pytest.approx(math.sqrt(1.0 / (0.05 * qe)), rel=1e-12)
        assert m[1, 2] == pytest.approx(k_list[0] / 0.05, rel=1e-12)
        with pytest.raises(ValueError):
            hairpin_coupling_matrix(k_list, qe, 0.0)
        with pytest.raises(ValueError):
            hairpin_coupling_matrix([0.05, -0.01], qe, 0.05)

    def test_a4_design_geometry_reproduces_c13_ideal(self):
        """验收（修正链口径）：**修正链**设计几何（kgap_corrected=True，gap 落设计支
        [0.65,1.1328]）经 gap→c(gap)·k_KJ / τ→Q_e×c(τ) 反演后与该设计的 C13 理想响应
        max|ΔS|≤1e-9；FBW 取设计支可达 k（k_EM 上限 ~0.0155 → FBW≈1.35%）——名义 5% 设计
        在 c(gap) 表下不可达（test_hairpin_kgap_correction 钉 ValueError），故名义几何
        改钉『EM 标定后欠耦』：fake(名义) 与 k=c·k_KJ 的模型 ≤1e-3（舍入量级）。"""
        from scipy.optimize import brentq

        from rfauto.adapters.fake_adapter import (
            _HAIRPIN_F0_CORR,
            _HAIRPIN_QE_CORR,
            _hairpin_sparams,
        )
        from rfauto.core.calculators import coupling_matrix_response
        from rfauto.core.coupled_microstrip import (
            hairpin_k_from_gap_mm,
            hairpin_kgap_design_branch_mm,
        )

        f = self.F
        g_peak, _ = hairpin_kgap_design_branch_mm(DESIGN["w_mm"])
        k_peak = hairpin_k_from_gap_mm(g_peak, DESIGN["w_mm"], structural_correction=True)
        fbw_c = 0.9 * k_peak / 1.0303                     # N=3 RL20 |M12|=1.0303
        dc = ot.hairpin_design_from_order(3, F0, fbw_c, RL_DB, kgap_corrected=True)
        r = coupling_matrix_response(freq_ghz=list(f), f0_ghz=F0, fbw=fbw_c,
                                     matrix=dc["coupling_matrix"])
        c = np.asarray(r["s_matrix"], dtype=float)
        s_ideal = c[..., 0] + 1j * c[..., 1]
        c0, c1 = _HAIRPIN_QE_CORR
        # τ 解到 0.49：该设计 Q_e≈63 超出物理抽头上限（布局 τ≤0.444 → Q_e≲50，定论
        # 『同向 hairpin 无自洽 Chebyshev 点』），此处只验 fake 电气通道数学一致性（fake
        # 不受布局限，c(τ) 线性外推）
        tau_c = float(brentq(lambda t: (c0 + c1 * t) * ot.hairpin_qe_from_tap_frac(t)
                             - dc["qe"], 0.05, 0.49, xtol=1e-12))
        nt = self._solve({"order": "3", "w_mm": f"{dc['w_mm']!r}mm",
                          "arm_len_mm": f"{dc['arm_len_mm'] * _HAIRPIN_F0_CORR!r}mm",
                          "gap_mm": f"{dc['gap_mm']!r}mm",
                          "tap_frac": f"{tau_c!r}"})
        assert float(np.max(np.abs(nt.s - s_ideal))) <= 1e-9
        # 名义（舍入）几何：EM 标定 fake 预测 = 修正 k 的耦合矩阵模型（舍入量级 ≤1e-3）
        nt_nom = self._solve()
        k_nom = hairpin_k_from_gap_mm(NOMINAL["gap_mm"], NOMINAL["w_mm"],
                                      structural_correction=True)
        assert k_nom == pytest.approx(0.0133, abs=2e-4)
        qe_nom = ot.hairpin_qe_from_tap_frac(NOMINAL["tap_frac"]) * (
            c0 + c1 * NOMINAL["tap_frac"])
        from rfauto.core.synthesis import Stackup, forward_z0
        _, eps_eff = forward_z0(NOMINAL["w_mm"], F0,
                                Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508))
        f0_nom = _HAIRPIN_F0_CORR * (299792458.0 / (
            2.0 * NOMINAL["arm_len_mm"] * 1e-3 * math.sqrt(eps_eff))) / 1e9
        ref_nom = _hairpin_sparams(f, f0_ghz=f0_nom, order=3, k_list=[k_nom, k_nom],
                                   qe=qe_nom)
        assert float(np.max(np.abs(nt_nom.s - ref_nom))) <= 1e-3

    def test_a4_gap_widens_narrows_bandwidth_monotonically(self):
        """gap↑ → k↓ → 3dB 带宽单调变窄（设计支及以上：修正 k=c(gap)·k_KJ 递减 + 域外
        clamp 段 k_KJ 递减保证；极大点左侧非单调见 test_hairpin_kgap_correction）。"""
        widths = []
        for gap in (0.8, 1.1328, 1.6, 2.2):
            nt = self._solve({"gap_mm": f"{gap}mm"})
            f = nt.frequency.f / 1e9
            s21 = np.abs(nt.s[:, 1, 0])
            widths.append(float(np.ptp(f[s21 >= s21.max() / math.sqrt(2.0)])))
        assert all(a > b for a, b in pairwise(widths)), widths

    def test_a4_tap_frac_toward_half_raises_qe(self):
        """τ→0.5 → Q_e↑（外耦合变弱）：闭式单调 + fake 响应带宽随 τ 增大而收窄。"""
        qes = [ot.hairpin_qe_from_tap_frac(t) for t in (0.30, 0.36, 0.40, 0.43)]
        assert all(a < b for a, b in pairwise(qes))
        widths = []
        for tau in (0.30, 0.36, 0.40, 0.43):
            nt = self._solve({"order": "1", "tap_frac": str(tau)})
            f = nt.frequency.f / 1e9
            s21 = np.abs(nt.s[:, 1, 0])
            assert s21.max() == pytest.approx(1.0, abs=1e-6)     # 无损单腔透射峰
            widths.append(float(np.ptp(f[s21 >= s21.max() / math.sqrt(2.0)])))
        assert all(a > b for a, b in pairwise(widths)), widths
        # 单腔闭式互检：Q_L=Q_e_fake/2（Q_u=∞，Q_e_fake=c(τ)·Q_e_closed），Δf_3dB=f0/Q_L
        # （网格 ±1 步容差）
        from rfauto.adapters.fake_adapter import _HAIRPIN_QE_CORR
        c0, c1 = _HAIRPIN_QE_CORR
        qe_fake = qes[-1] * (c0 + c1 * 0.43)
        df = float(self.F[1] - self.F[0])
        assert widths[-1] == pytest.approx(2.5 / (qe_fake / 2.0), abs=2.5 * df)

    def test_a4_gaps_list_and_order1_dispatch(self):
        """gaps_mm 列表（逐缝非等耦合）优先于标量 gap_mm；order=1 无缝派发可用。"""
        from rfauto.adapters.fake_adapter import _hairpin_sparams

        nt_list = self._solve({"order": "4", "gaps_mm": "[1.0, 1.5, 1.0]"})
        nt_scalar = self._solve({"order": "4", "gap_mm": "1.0mm"})
        assert float(np.max(np.abs(nt_list.s - nt_scalar.s))) > 1e-3
        nt1 = self._solve({"order": "1"})
        assert nt1.s.shape[1:] == (2, 2)
        assert float(np.max(np.abs(nt1.s))) <= 1.0 + 1e-12
        with pytest.raises(ValueError):
            _hairpin_sparams(self.F, order=3, k_list=[0.05], qe=17.0)   # 长度须 2
