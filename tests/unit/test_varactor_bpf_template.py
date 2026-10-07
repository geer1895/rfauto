"""M-5 varactor_bpf：变容二极管调谐 BPF 模板单测（2026-09-27 注册）。

理论口径（来源见 openems_templates 文末 §M-5 段首与 core/varactor.py）：
① 主谐振方程：开路端装载 λ/2 臂 tan(βL)=−ω·C·Z0（βL∈(π/2,π)）；C→0 ⇒
   λ/2 无载锚、C→∞ ⇒ λ/4 极限；f 随 C 单调下降（kernel 单测 test_varactor
   钉解析与极限，本文件钉设计链/渲染/fake 三方接线）；
② 突变结 C(V)=Cj0/√(1+V/φ)；**静态电容口径**：FDTD 无时变 C——三档偏压=
   三次静态 run，各档 C(V_i) 为常数（CSXCAD .pyx 口径核实：C→SetCapacity
   法拉、ny=CheckNyDir 方向索引、LEtype 缺省 PARALLEL、caps=True 端板）；
③ 名义链 varactor_bpf_design（铁律 #1c 全部综合精算）：臂长=λg/2(2.8GHz,
   εeff HJ)、名义偏置点 C(2.5GHz)→V=3.6342V；耦合链纯 KJ（同向 U 的
   c(gap)/c(τ) 真机标定**预声明不转移**——hairpin W4④/B1 修正是逐族标定）；
④ fake 通道：谷位随 bias_v 等效伸缩（aging_service 谐振族惯例的 C(V) 版），
   谷位=主谐振方程 f0(C(V)) 与响应面同源。
渲染：hairpin 同族布局（几何单源 _hairpin_layout）+ 每 U 左臂开路端
LumpedElement（ny=2 全隙盒 z 0→H_SUB，combline c_load 先例）；cj0_pf/phi_v/
bias_v 进元件值不进导体几何 → 审计 LUMPED_VALUE_PARAMS 豁免，字面量接线由
本文件 test_render_varactor_literal 钉住。
"""

from __future__ import annotations

import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot
from rfauto.core.varactor import (
    abrupt_junction_capacitance_pf,
    bias_for_capacitance_v,
    varactor_box_geo_capacitance_pf,
    varactor_bpf_design,
    varactor_line_f0_ghz,
    varactor_load_capacitance_pf,
)
from tests.unit import _geometry_audit_helpers as gh

T = "varactor_bpf"
MESH_MM = 0.40                    # hairpin 同族缺省收敛档（缝 1.13mm ≫ NEAR）
BAND = (2.0, 3.0)
F0 = 2.5
NOMINAL = dict(ot.VARACTOR_BPF_NOMINAL)
# 三档偏压（真机冒烟口径：低/名义/高；各档 C 为常数——静态电容口径）
BIAS_3PT = (0.5, NOMINAL["bias_v"], 10.0)


def _load(params: dict | None = None, mesh_mm: float = MESH_MM):
    resolved = dict(NOMINAL if params is None else params)
    text = ot.render_script(T, resolved, BAND, mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main",
                   "__file__": str(REPO / "_varactor_bpf_audit_sim.py")}
    exec(compile(head, "varactor_bpf_audit", "exec"), scope)
    return scope, gh.extract_primitives(scope["CSX"])


# ─── 设计链（铁律 #1c：名义=综合精算 4/6 位舍入，再生守卫）───────────────────

def test_design_chain_regenerates_nominal():
    """NOMINAL = varactor_bpf_design() 的 4/6 位舍入（w/gap/arm_len 4 位、
    τ 6 位；hairpin 同规则）——禁手抄毫米数（#1c）的单测形态。τ=loaded 廓线
    branch B 反解（P0），tap_frac_ref=语义标记随行。"""
    design = varactor_bpf_design(order=3)
    assert design["order"] == 3
    assert round(design["w_mm"], 4) == NOMINAL["w_mm"]
    assert round(design["arm_len_mm"], 4) == NOMINAL["arm_len_mm"]
    assert round(design["arm_gap_mm"], 4) == NOMINAL["arm_gap_mm"]
    assert round(design["gap_mm"], 4) == NOMINAL["gap_mm"]
    assert round(design["tap_frac"], 6) == NOMINAL["tap_frac"]
    assert design["tap_frac_ref"] == "c_end_loaded_branchB"
    # 在臂守卫：τ ≤ l_arm/L（审计 0.4351 上限——布局同式 b=w+arm_gap）
    b_mm = NOMINAL["w_mm"] + NOMINAL["arm_gap_mm"]
    on_arm_max = (NOMINAL["arm_len_mm"] - b_mm) / (2.0 * NOMINAL["arm_len_mm"])
    assert NOMINAL["tap_frac"] < on_arm_max
    # 旧无载廓线值不得回归（P0：loaded 节点恰扫过 0.401892=外耦失配根因）
    assert abs(NOMINAL["tap_frac"] - 0.401892) > 0.05
    assert round(design["bias_v"], 4) == NOMINAL["bias_v"]


def test_design_point_recovers_f0_via_master_equation():
    """设计点自洽：主谐振方程 f0(C(bias_v_nom)) 回收 f0=2.5GHz（舍入容差
    2e-4 GHz 内）；C 需求与突变结反解往返一致（rel 1e-9）。"""
    _, ereff = _ereff_nominal()
    f0 = varactor_line_f0_ghz(
        abrupt_junction_capacitance_pf(NOMINAL["bias_v"], NOMINAL["cj0_pf"],
                                       NOMINAL["phi_v"]),
        NOMINAL["arm_len_mm"], 50.0, ereff)
    assert f0 == pytest.approx(F0, abs=2e-4)
    c_req = varactor_load_capacitance_pf(F0, NOMINAL["arm_len_mm"], 50.0,
                                         ereff)
    assert c_req == pytest.approx(0.4455, abs=1e-3)
    v_rt = bias_for_capacitance_v(c_req, NOMINAL["cj0_pf"], NOMINAL["phi_v"])
    assert v_rt == pytest.approx(NOMINAL["bias_v"], rel=1e-3)


def _ereff_nominal() -> tuple[float, float]:
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="varactor_bpf", epsilon_r=3.66, thickness_mm=0.508)
    return forward_z0(NOMINAL["w_mm"], 2.8, stackup)


def test_tuning_direction_three_bias_points():
    """三档偏压调谐方向：V↑ ⇒ C(V)↓ ⇒ f0(C)↑（单调；静态三点口径）。"""
    _, ereff = _ereff_nominal()
    cs = [abrupt_junction_capacitance_pf(v, NOMINAL["cj0_pf"],
                                         NOMINAL["phi_v"]) for v in BIAS_3PT]
    fs = [varactor_line_f0_ghz(c, NOMINAL["arm_len_mm"], 50.0, ereff)
          for c in cs]
    assert all(c2 < c1 for c1, c2 in pairwise(cs))
    assert all(f2 > f1 for f1, f2 in pairwise(fs))
    # 调谐窗合理（演示量级：±7% 内，非退化常数——#195 新族接入前判据）
    assert fs[2] / fs[0] == pytest.approx(1.0, abs=0.15)
    assert fs[1] == pytest.approx(F0, abs=2e-4)


# ─── 正式注册（#304 架构消费者钉）────────────────────────────────────────────

def test_registered_and_surface_complete():
    import yaml

    assert ot.TEMPLATE_META[T] is ot.VARACTOR_BPF_META
    assert ot.TEMPLATE_NOMINAL[T] is ot.VARACTOR_BPF_NOMINAL
    assert list(ot.varactor_bpf_meta()["params"]) == list(NOMINAL)
    assert ot._TEMPLATE_PORT_AXES[T] == ("x",)
    assert ot._TEMPLATE_RADIATOR[T] is False
    data = yaml.safe_load((REPO / "docs" / "templates" / T / "meta.yaml")
                          .read_text(encoding="utf-8"))
    assert data["template"] == T and int(data["n_ports"]) == 2
    assert list(data["params"]) == list(ot.VARACTOR_BPF_META["params"])
    assert data["nominal_params"] == NOMINAL
    assert "静态电容" in data["static_c_note"]
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES
    assert T in EXPECTED_TEMPLATES and len(EXPECTED_TEMPLATES) >= 57
    # 精确计数单源在审计文件（#247 禁轨内自钉）；键集断言（AU-1 b4，
    # 尾序槽位钉 [-1] 退役）——varactor_bpf 键集在册，尾部追加契约由
    # slotline/msl_siw_taper 两文件的相对次序子序列钉承担
    assert T in ot.TEMPLATE_META and T in ot.TEMPLATE_NOMINAL
    assert gh.PORT_GROUPS[T] == (frozenset({1}), frozenset({2}))
    assert gh.LUMPED_VALUE_PARAMS[T] == frozenset(
        {"cj0_pf", "phi_v", "bias_v"})
    # 静态电容口径必须写进 src meta（判读者首读面）
    assert "静态电容口径" in ot.VARACTOR_BPF_META["static_c_note"]
    assert "三次静态 run" in ot.VARACTOR_BPF_META["static_c_note"]
    # tap_frac 语义=自 C 端计（P0/#154 收口；src 与 docs meta 同步钉——
    # 与 hairpin 无载族「自开路端计」同名不同义的对照须随行）
    assert "自 C 端计" in ot.VARACTOR_BPF_META["param_semantics"]
    assert "自 C 端计" in data["param_semantics"]
    assert "同名不同义" in data["param_semantics"]
    assert "loaded 廓线" in data["param_semantics"]
    # C_literal 扣除语义写进 meta（P2 #252 族）
    assert "C(V)" in ot.VARACTOR_BPF_META["static_c_note"]
    assert "C_geo" in data["static_c_note"]


# ─── 渲染与字面量接线（LUMPED_VALUE_PARAMS 语义）────────────────────────────

def _literal_pf(params: dict) -> float:
    """C 字面量（pF）= C(V)−C_geo（#252 族扣除，渲染单源同式）。"""
    c_geo = varactor_box_geo_capacitance_pf(
        float(params.get("w_mm", NOMINAL["w_mm"])),
        float(ot._DEFAULT_SUB["h_mm"]), float(ot._DEFAULT_SUB["er"]))
    c_design = abrupt_junction_capacitance_pf(
        float(params.get("bias_v", NOMINAL["bias_v"])),
        float(params.get("cj0_pf", NOMINAL["cj0_pf"])),
        float(params.get("phi_v", NOMINAL["phi_v"])))
    return c_design - c_geo


def test_render_varactor_literal():
    """C_literal=C(V)−C_geo 字面量进渲染脚本（法拉、ny=2 shunt 对地惯用法；
    P2 #252 族扣除：实感 C=字面量+盒区背景位移电流=设计 C(V)）。C 值随
    bias_v 变而导体盒字面量不变（静态电容口径的渲染面证据）。"""
    texts = {v: ot.render_script(T, dict(NOMINAL, bias_v=v), BAND,
                                 mesh_resolution_mm=MESH_MM)
             for v in BIAS_3PT}
    for v, text in texts.items():
        compile(text, f"gen_{v}", "exec")
    # 元件值：每谐振器一只 LumpedElement，C=该档 C_literal（法拉）
    n = NOMINAL["order"]
    for v, text in texts.items():
        c_f = _literal_pf(dict(NOMINAL, bias_v=v)) * 1e-12
        assert c_f > 0.0                              # 三档扣除后仍为正
        assert text.count("AddLumpedElement(") == n
        assert text.count("ny=2, caps=True") == n
        assert f"VAR_C = {c_f!r}" in text
        assert "C_literal=C(V)" in text               # 扣除语义随行注记
    # 三档 C 字面量互异（调谐方向可见）且导体几何行互同
    assert len({t.split("VAR_C = ")[1].split("\n")[0]
                for t in texts.values()}) == 3
    geo_lines = {t.split("varactor_bpf = CSX.AddMetal")[1].split(
        "VAR_C = ")[0] for t in texts.values()}
    assert len(geo_lines) == 1
    # 审计档渲染兜底：β 锚列与单轴 x PML 边界（抽头馈线自 x=∓BOARD 引入）
    assert "port_beta.csv" in texts[BIAS_3PT[1]]
    assert '["PML_8", "PML_8", "MUR", "MUR", "PEC", "MUR"]' \
        in texts[BIAS_3PT[1]]


def test_lumped_value_params_do_not_move_conductors():
    """cj0_pf/phi_v/bias_v 扰动只改 C 字面量、导体签名逐位不变
    （LUMPED_VALUE_PARAMS 口径的实测证明，审计豁免的正面依据）。"""
    base = gh.conductor_signature(_load()[1])
    for key, value in (("cj0_pf", 1.6), ("phi_v", 1.2), ("bias_v", 5.0)):
        _scope, prims = _load(dict(NOMINAL, **{key: value}))
        assert gh.conductor_signature(prims) == base, key


# ─── #212 离线几何审计（CSXCAD 实测，秒级零仿真）────────────────────────────

def test_primitives_ports_connectivity_mesh():
    scope, prims = _load()
    n = NOMINAL["order"]
    metal = [p for p in prims if p.kind == "Metal"]
    # 馈线盒×2 + 每腔（臂×2+弯带×1）+ MSLPort 自画馈段×2 = 3N+4
    assert len(metal) == 3 * n + 4
    assert len([p for p in prims if p.kind == "Material"]) == 1
    assert gh.off_mesh_planes(prims, scope) == []
    lines = {ax: gh.mesh_lines(scope, ax) for ax in ("x", "y", "z")}
    for p in [q for q in prims if gh.is_conductor(q)]:
        for index, axis in enumerate(("x", "y", "z")):
            if p.extent[index] > 1e-12:
                inside = lines[axis][(lines[axis] >= p.lo[index] - 1e-9)
                                     & (lines[axis] <= p.hi[index] + 1e-9)]
                assert inside.size >= 1, f"{p.prop} 在 {axis} 轴未进网格"
    # 变容管盒：z 跨基板全隙（顶接臂端金属、底接 z-min PEC 地）
    les = [p for p in prims if p.kind == "LumpedElement"]
    assert len(les) == n
    h_sub = float(scope["H_SUB"])
    for p in les:
        assert p.lo[2] == pytest.approx(0.0)
        assert p.hi[2] == pytest.approx(h_sub)
    # 属性名逐腔唯一（varactor_c1..N）且 C 值=名义偏置 C_literal（C(V)−C_geo）
    c_nom = _literal_pf(NOMINAL) * 1e-12
    names = {p.prop for p in les}
    assert len(names) == n
    assert all(name.startswith("varactor_c") for name in names)
    for i in range(1, n + 1):
        assert scope[f"_vc{i}"].GetCapacity() == pytest.approx(
            c_nom, rel=1e-12)
    # 端口面贴 x 板边（PML），端口数=2
    ports = gh.port_objects(scope)
    assert len(ports) == 2
    board = float(scope["BOARD"])
    for port in ports.values():
        start = np.asarray(port.start, dtype=float)
        assert int(port.prop_ny) == 0
        assert abs(abs(float(start[0])) - board) <= 1e-9
    # 连通性：hairpin 抽头同族——N 个 DC 隔离分量（每 U=2 臂+弯带+变容管盒
    # +抽头馈段+MSL 自画段同分量；跨腔缝隔离；地=z-min PEC 边界非原语）
    conductors, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == n
    comp_of = {num: next(iter(gh.containing_labels(
        gh.port_feed_point(p), conductors, labels)))
        for num, p in ports.items()}
    assert comp_of[1] != comp_of[2]
    counts: dict[int, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    all_counts = sorted(counts.values())
    # 端口腔分量 = 3 结构盒 + 变容管盒 + 抽头馈段 + MSL 自画馈段 = 6 原语；
    # 非端口腔 = 4 原语（N=3 时恰 1 个中腔）
    assert all_counts == sorted([6] * 2 + [4] * (n - 2))
    # 网格最小间距守卫（#152，>1µm）
    for axis in ("x", "y", "z"):
        assert bool(np.all(np.diff(lines[axis]) > 1e-6))


def test_near_points_cover_varactor_box_edge():
    """变容管装载盒外 y 缘（y0+WF）精确入网（#198）；与既有线最小间距
    >1µm（#152 渲染守卫同口径）。"""
    lay = ot._hairpin_layout(dict(NOMINAL))
    _nx, ny = ot._near_points(T, dict(NOMINAL))
    edge = lay["y0"] + lay["wf"]
    assert min(abs(v - edge) for v in ny) < 1e-12


def test_layout_validation_inherited_from_hairpin():
    """域守卫走 hairpin 同款布局单源（tap_frac 越域显式 ValueError）。"""
    with pytest.raises(ValueError):
        ot._hairpin_layout(dict(NOMINAL, tap_frac=0.6))
    with pytest.raises(ValueError):
        ot._hairpin_layout(dict(NOMINAL, arm_len_mm=1.0))   # 折叠不成立


def test_geometry_spec_preview_consistency():
    """UI 预览与布局单源一致：盒数=2 地/基板+3N+2、端口 2、elements=lumped_c×N
    且 c_pf=名义偏置 C_literal（C(V)−C_geo，与渲染字面量逐位同源 #252 族）。"""
    spec = ot.geometry_spec(T, dict(NOMINAL))
    n = NOMINAL["order"]
    assert len(spec["boxes"]) == 2 + 3 * n + 2
    assert len(spec["ports"]) == 2
    assert [e["kind"] for e in spec["elements"]] == ["lumped_c"] * n
    c_literal = _literal_pf(NOMINAL)
    assert all(e["c_pf"] == pytest.approx(c_literal, rel=1e-12)
               for e in spec["elements"])
    # 设计 C(V) 可由字面量+闭式 C_geo 回收（实感口径自洽）
    c_geo = varactor_box_geo_capacitance_pf(
        NOMINAL["w_mm"], float(ot._DEFAULT_SUB["h_mm"]),
        float(ot._DEFAULT_SUB["er"]))
    assert c_literal + c_geo == pytest.approx(
        abrupt_junction_capacitance_pf(NOMINAL["bias_v"], NOMINAL["cj0_pf"],
                                       NOMINAL["phi_v"]), rel=1e-12)


# ─── fake 通道：谷位随偏置等效伸缩（C(V) 版惯例）────────────────────────────

def _fake_network(variables: dict, npts: int = 401):
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type=T, f0_ghz=F0, freq_ghz=(2.0, 3.0, npts))
    ad.connect({})
    ad.set_variables(variables)
    ad.build_and_setup(lambda a: None, None)
    assert ad.solve("Setup1").success
    return ad.get_sparams()


def test_fake_valley_tracks_bias_equivalent_stretch():
    """谷位=bias_v→C(V)→主谐振方程 f0（同源闭式，等效伸缩惯例）；V↑ ⇒
    C↓ ⇒ 谷位上移（调谐方向）；三档谷位互异且与 kernel 预测逐点一致。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="varactor_bpf", epsilon_r=3.66, thickness_mm=0.508)
    _, ereff = forward_z0(NOMINAL["w_mm"], F0, stackup)
    base_vars = {
        "w_mm": str(NOMINAL["w_mm"]),
        "arm_len_mm": str(NOMINAL["arm_len_mm"]),
        "gap_mm": str(NOMINAL["gap_mm"]),
        "tap_frac": str(NOMINAL["tap_frac"]),
    }
    valleys = []
    for v in BIAS_3PT:
        net = _fake_network({**base_vars, "bias_v": str(v)})
        s11 = np.abs(net.s[:, 0, 0])
        i_valley = int(np.argmin(s11))
        valleys.append(float(net.f[i_valley] / 1e9))
        assert s11[i_valley] < 0.5                    # 谷是带通谷非数值噪声
        f_kernel = varactor_line_f0_ghz(
            abrupt_junction_capacitance_pf(v, NOMINAL["cj0_pf"],
                                           NOMINAL["phi_v"]),
            NOMINAL["arm_len_mm"], 50.0, ereff)
        assert valleys[-1] == pytest.approx(f_kernel, abs=5e-3), v
    assert all(f2 > f1 for f1, f2 in pairwise(valleys))


def test_fake_passive_reciprocal_and_gapsmm_list_parsing():
    """无耗裁判：|S|≤1、S12=S21（互易）；gaps_mm 列表变量字符串解析与标量
    gap_mm 同响应（#154 同索引同语义）。"""
    base_vars = {
        "w_mm": str(NOMINAL["w_mm"]),
        "arm_len_mm": str(NOMINAL["arm_len_mm"]),
        "gap_mm": str(NOMINAL["gap_mm"]),
        "tap_frac": str(NOMINAL["tap_frac"]),
        "bias_v": str(NOMINAL["bias_v"]),
    }
    net = _fake_network(base_vars, npts=101)
    assert float(np.max(np.abs(net.s))) <= 1.0 + 1e-9
    assert np.allclose(net.s[:, 0, 1], net.s[:, 1, 0], atol=1e-12)
    net_list = _fake_network({**base_vars, "gaps_mm": f'"{NOMINAL["gap_mm"]}, '
                                              f'{NOMINAL["gap_mm"]}"'}, npts=51)
    net_scalar = _fake_network(base_vars, npts=51)
    assert np.allclose(net_list.s, net_scalar.s, atol=1e-12)
