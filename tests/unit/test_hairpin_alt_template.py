"""hairpin_alt：交替取向发夹线 BPF 模板单测（2026-09-18 根修；#212 离线零真机）。

背景（离线审计 #11）：同向 hairpin 真机 k_EM(gap) 非单调、极大
0.0155@0.65 ≪ k_KJ 0.0515——相邻臂开路端对齐 → 电/磁耦合反号相消，FBW5% 名义在同向
参数空间内无自洽设计点。根修 = 经典交替取向（奇数序谐振器上下翻转，相邻臂一端开路/
一端弯带互补，电/磁耦合同号叠加）。本文件钉住：

① 注册四件套（TEMPLATE_META/NOMINAL 同对象、docs meta.yaml、EXPECTED_TEMPLATES 单源、
   template_specs、fake 派发）+ 既有键不重排（#247：hairpin_alt 紧随 hairpin，槽线族仍居尾）；
② 名义链（铁律 #1c/#252）：四项几何 = hairpin_design_from_order(3,2.5,0.05,20) **纯 KJ**
   链舍入（不乘同向 c(gap)），arm_len×c_f0、τ 走 c(τ)，按链复算而非拷贝 hairpin；
③ 设计点自洽：综合 → 渲染布局 → 闭式回代（gap→k、arm_len/c_f0→f0、τ→Q_e）逐位往返；
④ 布局/渲染：flips/y_open/y_bend/y_taps 交替语义；orientation="same" 对照与 hairpin
   **原语签名与三轴网格逐位相同**（A/B 只隔离取向）；hairpin 模板不消费 orientation 键；
⑤ #212 CSXCAD 实测：N 个 DC 隔离谐振器、弯带 y 中心逐腔轮替、**相邻臂开路端交替**、
   缝内网格线 ≥1 且 NEAR ≤ 缝/3（#266）、端口贴板边、#152 守卫；
⑥ fake 派发纯 KJ：名义复现 C13 理想 ≤1e-3、gap↑带宽单调窄（全域，无相消支）、与同向
   fake 的差异只在 c(gap)；
⑦ k(gap) 图谱判读门（scripts/hairpin_q_extract.hairpin_alt_kgap_gate，先于真机写死）：
   真机同向表必 FAIL（单调+比值双红）、合成单调/非单调序列、比值门边界 [0.6,1.2] 含端点、
   点数/输入校验；CLI 接线（--gate/--k-target/--kgap-out、hairpin_calib --template）。

不凑绿（#122）：本文件不断言 k_EM≈k_KJ 已成立——那是真机图谱的事；meta.yaml
campaign_capable=false 并列原因，解锁判据（离线两条本文件覆盖，真机三条由判读门判）钉住。
"""

from __future__ import annotations

import importlib.util
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
from rfauto.core import coupled_microstrip as cm
from tests.unit import _geometry_audit_helpers as gh

_SPEC = importlib.util.spec_from_file_location(
    "_hairpin_q_extract_alt_gate", str(REPO / "scripts" / "hairpin_q_extract.py"))
assert _SPEC is not None and _SPEC.loader is not None
qx = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(qx)

MESH_MM = 0.4          # 收敛档网格（#198/#212 口径，与 hairpin 同）
BAND = (2.25, 2.75)
F0 = 2.5
FBW = 0.05
RL_DB = 20.0
NOMINAL = dict(ot.HAIRPIN_ALT_NOMINAL)
DESIGN = ot.hairpin_design_from_order(3, F0, FBW, RL_DB)
C_LIGHT_MM_GHZ = 299.792458


def _load(params: dict | None = None, mesh_mm: float = MESH_MM):
    """渲染 hairpin_alt → exec 几何段 → (脚本作用域, 原语列表)（会话内缓存）。"""
    return gh.load_geometry("hairpin_alt", dict(NOMINAL if params is None else params),
                            mesh_mm=mesh_mm)


def _eps_eff(w_mm: float) -> float:
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508)
    return forward_z0(w_mm, F0, stackup)[1]


# ─── ① 注册四件套 + 既有键不重排 ───────────────────────────────────────────────

def test_registered_same_object_and_dispatch_keys():
    assert ot.TEMPLATE_META["hairpin_alt"] is ot.HAIRPIN_ALT_META
    assert ot.TEMPLATE_NOMINAL["hairpin_alt"] is ot.HAIRPIN_ALT_NOMINAL
    assert ot.HAIRPIN_ALT_NOMINAL is not ot.HAIRPIN_NOMINAL          # 独立对象（alt 复标后可分叉）
    assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)
    keys = list(ot.TEMPLATE_META)
    assert keys.index("hairpin_alt") == keys.index("hairpin") + 1    # 同族段内紧随 hairpin
    # df7 C10d 起（coil_nfc 批次漏更新本钉、基线即红，随 C10d 一并修复）：
    # 槽线族退居尾 10..6、ms 四件尾 6..2、coil_nfc 尾 2、mmwave_series_array 尾 1
    assert keys[-10:-6] == ["slotline", "slotline_lumped", "msl_slot_transition",
                            "marchand_balun"]                  # 槽线族位次（#247）
    assert keys[-6:-2] == ["ms_patch", "ms_cross", "ms_jcross", "ms_array_NxN"]
    assert keys[-1] == "mmwave_series_array"
    assert ot._TEMPLATE_PORT_AXES["hairpin_alt"] == ("x",)
    assert ot._TEMPLATE_RADIATOR["hairpin_alt"] is False
    meta = ot.template_meta("hairpin_alt")
    assert meta["template"] == "hairpin_alt" and meta["n_ports"] == 2
    assert meta["nominal_params"] == NOMINAL
    alias = ot.hairpin_alt_meta()
    assert alias["template"] == "hairpin_alt" and alias["nominal_params"] == NOMINAL
    assert "coupling_matrix_response" in alias["extraction"]
    assert list(ot.HAIRPIN_ALT_META["params"]) == list(ot.HAIRPIN_META["params"])
    assert "orientation" not in ot.HAIRPIN_ALT_META["params"]        # 布局选项不进 params


def test_registration_surface_complete_and_campaign_gate_declared():
    import yaml

    data = yaml.safe_load((REPO / "docs" / "templates" / "hairpin_alt" / "meta.yaml")
                          .read_text(encoding="utf-8"))
    assert data["template"] == "hairpin_alt"
    assert float(data["f0_ghz"]) == pytest.approx(F0, rel=1e-12)
    assert int(data["n_ports"]) == 2
    assert list(data["params"]) == list(ot.HAIRPIN_ALT_META["params"])
    assert {k: float(v) if not isinstance(v, int) else v
            for k, v in data["nominal_params"].items()} == NOMINAL
    # ③ campaign_capable 解锁判据写进 meta.yaml：未过真机门 → false + 原因列表 + 判据结构
    assert data["campaign_capable"] is False
    assert data["campaign_capable_reasons"] and all(
        isinstance(r, str) and r for r in data["campaign_capable_reasons"])
    crit = data["campaign_unlock_criteria"]
    assert set(crit) == {"offline", "real_machine", "unlock_rule"}
    assert len(crit["offline"]) == 2 and len(crit["real_machine"]) == 3
    assert "[0.6, 1.2]" in " ".join(crit["real_machine"])            # 与判读门常数同源
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES
    assert "hairpin_alt" in EXPECTED_TEMPLATES and "hairpin" in EXPECTED_TEMPLATES
    assert frozenset(ot.TEMPLATE_META) == EXPECTED_TEMPLATES         # 单源闭合（计数由审计文件锁）
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("hairpin_alt")
    assert spec.meta["n_ports"] == 2
    assert callable(TEMPLATE_SPECS.component("hairpin_alt", "render_script"))
    assert callable(TEMPLATE_SPECS.component("hairpin_alt", "fake_model"))
    roles = dict(spec.physics_roles)
    assert roles["w_mm"] == "line_width_mm"
    assert roles["arm_len_mm"] == "resonator_length_mm"
    assert roles["gap_mm"] == "gap_width_mm"
    res = spec.synthesizer(order=3, f0_ghz=F0, fbw=FBW, rl_db=RL_DB)
    assert res.model == "hairpin_alt_bpf" and res.recipe_draft["model"] == "hairpin_alt_bpf"
    assert set(res.params) == set(NOMINAL)
    assert res.params["gap_mm"] == pytest.approx(DESIGN["gap_mm"], rel=1e-12)
    assert any("交替取向" in n for n in res.notes)


# ─── ② 名义链（#1c/#252：全部综合精算，按链复算不拷贝）────────────────────────

def test_nominal_equals_pure_kj_design_chain_rounded():
    from scipy.optimize import brentq

    from rfauto.adapters.fake_adapter import _HAIRPIN_F0_CORR, _HAIRPIN_QE_CORR

    assert DESIGN["kgap_corrected"] is False                          # 纯 KJ 链
    assert NOMINAL["order"] == 3
    assert NOMINAL["w_mm"] == round(DESIGN["w_mm"], 4)
    assert NOMINAL["arm_len_mm"] == round(DESIGN["arm_len_mm"] * _HAIRPIN_F0_CORR, 4)
    assert NOMINAL["arm_gap_mm"] == DESIGN["arm_gap_mm"] == 3.0
    assert NOMINAL["gap_mm"] == round(DESIGN["gap_mm"], 4)
    c0, c1 = _HAIRPIN_QE_CORR
    tau_star = brentq(lambda t: (c0 + c1 * t) * cm.hairpin_qe_from_tap_frac(t) - DESIGN["qe"],
                      0.05, 0.44, xtol=1e-12)
    assert NOMINAL["tap_frac"] == round(tau_star, 6)
    # 50Ω 精算（HJ）；λg/2 闭式 × c_f0；k_self(3.0) ≪ 互耦（A2 理由同源）
    from rfauto.core.synthesis import Stackup, forward_z0
    z0, _ = forward_z0(NOMINAL["w_mm"], F0,
                       Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508))
    assert z0 == pytest.approx(50.0, abs=0.01)
    assert NOMINAL["arm_len_mm"] == pytest.approx(
        cm.hairpin_arm_len_mm(F0, NOMINAL["w_mm"]) * _HAIRPIN_F0_CORR, abs=1.6e-4)
    assert cm.hairpin_k_from_gap_mm(3.0, NOMINAL["w_mm"]) * 4.0 < DESIGN["k_list"][0]
    # 名义 gap 的纯 KJ k = 设计 k（舍入量级）；同向修正链在同一缝只给 ~0.26×——alt 名义不含 c(gap)
    k_kj = cm.hairpin_k_from_gap_mm(NOMINAL["gap_mm"], NOMINAL["w_mm"])
    assert k_kj == pytest.approx(DESIGN["k_list"][0], rel=1e-3)
    k_same = cm.hairpin_k_from_gap_mm(NOMINAL["gap_mm"], NOMINAL["w_mm"],
                                      structural_correction=True)
    assert k_same < 0.3 * k_kj


def test_design_point_self_consistency_synthesis_render_backsubstitution():
    """③ 综合 → 渲染布局（alternating）→ 闭式回代：realized 几何反演回设计电气量。"""
    from rfauto.adapters.fake_adapter import _HAIRPIN_F0_CORR, _HAIRPIN_QE_CORR

    lay = ot._hairpin_alt_layout(NOMINAL)
    wf = lay["wf"]
    assert lay["orientation"] == "alternating"
    # 渲染的耦合缝（相邻外臂边缘距）→ 纯 KJ 回代 = 设计 k
    for i in range(lay["n"] - 1):
        gap_mm = (lay["xs"][2 * i + 2] - wf / 2 - (lay["xs"][2 * i + 1] + wf / 2)) * 1e3
        assert gap_mm == pytest.approx(NOMINAL["gap_mm"], rel=1e-9)
        assert cm.hairpin_k_from_gap_mm(gap_mm, NOMINAL["w_mm"]) == pytest.approx(
            DESIGN["k_list"][i], rel=1e-3)
    # 渲染的展开长（2·臂长+臂间距）/c_f0 → λg/2 反演 f0 = 2.5GHz
    total_mm = (2.0 * lay["l_arm"] + lay["b"]) * 1e3
    assert total_mm == pytest.approx(NOMINAL["arm_len_mm"], rel=1e-12)
    f0_back = C_LIGHT_MM_GHZ / (2.0 * (total_mm / _HAIRPIN_F0_CORR)
                                * math.sqrt(_eps_eff(NOMINAL["w_mm"])))
    assert f0_back == pytest.approx(F0, abs=5e-4)
    # 抽头距各自开路端 τ·L_tot（输入未翻转腔自 y0 向上、输出腔按取向）→ Q_e 回代
    assert lay["y_taps"][0] - lay["y_open"][0] == pytest.approx(
        NOMINAL["tap_frac"] * lay["total"], rel=1e-12)
    dist_out = abs(lay["y_taps"][1] - lay["y_open"][-1])
    assert dist_out == pytest.approx(NOMINAL["tap_frac"] * lay["total"], rel=1e-12)
    tau_back = lay["y_taps"][0] - lay["y_open"][0]
    tau_back /= lay["total"]
    c0, c1 = _HAIRPIN_QE_CORR
    assert cm.hairpin_qe_from_tap_frac(tau_back) * (c0 + c1 * tau_back) == pytest.approx(
        DESIGN["qe"], rel=1e-4)


# ─── ④ 布局/渲染：交替语义 + 同向对照 ───────────────────────────────────────────

def test_layout_alternating_flips_open_ends_and_taps():
    lay3 = ot._hairpin_alt_layout(NOMINAL)
    assert lay3["flips"] == [False, True, False]
    assert lay3["y_open"] == [lay3["y0"], lay3["y1"], lay3["y0"]]
    assert lay3["y_bend"] == [lay3["y1"], lay3["y0"], lay3["y1"]]
    for a, b in pairwise(lay3["y_open"]):
        assert a != b                                              # 相邻臂开路端交替（定义性质）
    assert lay3["y_taps"] == [lay3["y_tap"], lay3["y_tap"]]        # 末腔未翻转 → 两抽头同 y
    # 既有键（臂盒几何）与同向布局逐位相同：取向只换弯带/开路端
    base = ot._hairpin_layout(NOMINAL)
    for key in ("xs", "centres", "y0", "y1", "y_tap", "total", "gaps", "l_arm", "b", "wf"):
        assert lay3[key] == base[key], key
    # 偶数阶：末腔翻转 → 输出抽头自 y1 向下计 τ·L_tot，仍落在臂上
    lay2 = ot._hairpin_alt_layout(dict(NOMINAL, order=2))
    assert lay2["flips"] == [False, True]
    assert lay2["y_tap_out"] == pytest.approx(lay2["y1"] - NOMINAL["tap_frac"] * lay2["total"])
    assert lay2["y_taps"] == [lay2["y_tap"], lay2["y_tap_out"]]
    assert lay2["y0"] < lay2["y_tap_out"] < lay2["y1"] and lay2["y_tap_out"] != lay2["y_tap"]
    lay4 = ot._hairpin_alt_layout(dict(NOMINAL, order=4))
    assert lay4["flips"] == [False, True, False, True]
    lay1 = ot._hairpin_alt_layout({k: v for k, v in NOMINAL.items() if k != "gap_mm"} | {"order": 1})
    assert lay1["flips"] == [False] and lay1["y_taps"][0] == lay1["y_taps"][1]
    # orientation="same" 对照：与 hairpin 缺省布局逐键相同
    same = ot._hairpin_alt_layout(dict(NOMINAL, orientation="same"))
    for key in base:
        assert same[key] == base[key], key
    assert same["flips"] == [False] * 3 and same["orientation"] == "same"
    # hairpin 模板不消费 orientation 键（缺省 same，逐位不变）
    assert ot._hairpin_layout(dict(NOMINAL, orientation="alternating"))["flips"] == [False] * 3
    with pytest.raises(ValueError, match="orientation"):
        ot._hairpin_alt_layout(dict(NOMINAL, orientation="mirror"))
    with pytest.raises(ValueError, match="orientation"):
        ot._hairpin_layout(NOMINAL, orientation="alt")


def test_render_structure_and_same_orientation_control_is_hairpin_identical():
    text = ot.render_script("hairpin_alt", dict(NOMINAL), BAND, mesh_resolution_mm=MESH_MM)
    compile(text, "gen", "exec")
    assert "ORIENTATION = 'alternating'" in text
    for n in (1, 2):
        assert f"MSLPort(CSX, port_nr={n}" in text
    assert text.count('prop_dir="x"') == 2
    assert "for _i in range(N):" in text and "YBEND[_i]" in text
    assert text.count("hairpin.AddBox") == 5
    assert "port_beta.csv" in text
    assert '["PML_8", "PML_8", "MUR", "MUR", "PEC", "MUR"]' in text
    assert "MeasPlaneShift=(XS[0] + BOARD) - 10 * NEAR - 4 * H_SUB" in text
    assert "MeasPlaneShift=(BOARD - XS[-1]) - 10 * NEAR - 4 * H_SUB" in text
    assert "YT[0]" in text and "YT[1]" in text
    assert compile(ot.render_script("hairpin_alt", {}, BAND, mesh_resolution_mm=MESH_MM),
                   "gen_default", "exec") is not None
    # 同向对照（orientation="same"）：CSXCAD 原语签名 + 三轴网格与 hairpin 逐位相同
    s_h, p_h = gh.load_geometry("hairpin")
    s_c, p_c = _load(dict(NOMINAL, orientation="same"))
    assert gh.conductor_signature(p_h) == gh.conductor_signature(p_c)
    for ax in ("x", "y", "z"):
        assert np.array_equal(gh.mesh_lines(s_h, ax), gh.mesh_lines(s_c, ax)), ax
    # 交替取向：x/z 网格与 hairpin 相同（臂/缝/层不变），仅 y 网格随弯带翻转而异
    s_a, p_a = _load()
    for ax in ("x", "z"):
        assert np.array_equal(gh.mesh_lines(s_h, ax), gh.mesh_lines(s_a, ax)), ax
    assert not np.array_equal(gh.mesh_lines(s_h, "y"), gh.mesh_lines(s_a, "y"))
    assert gh.conductor_signature(p_h) != gh.conductor_signature(p_a)


# ─── ⑤ #212 离线几何审计（CSXCAD 实测，秒级零仿真）──────────────────────────────

def test_primitives_nonzero_and_entered_in_mesh():
    scope, prims = _load()
    metal = [p for p in prims if p.kind == "Metal"]
    dielectric = [p for p in prims if p.kind == "Material"]
    assert len(metal) == 13                          # 3 谐振器×3 + 4 馈线原语
    assert len(dielectric) == 1
    for p in metal:
        assert int(np.sum(p.extent[:2] > 1e-12)) == 2
    assert gh.off_mesh_planes(prims, scope) == []
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
        axis = int(port.prop_ny)
        assert abs(abs(start[axis]) - board) <= 1e-9, f"port{number} 端口面未贴板边"
        assert int(np.sum(np.abs(start - stop) > 1e-9)) >= 2
        assert float(np.min(np.abs(z_lines - start[2]))) <= 1e-6


def test_connectivity_n_dc_isolated_resonators():
    scope, prims = _load()
    conductors, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == int(NOMINAL["order"])
    assert min(Counter(labels).values()) >= 3
    ports = gh.port_objects(scope)
    comp_of: dict[int, int] = {}
    for number, port in ports.items():
        on = gh.containing_labels(gh.port_feed_point(port), conductors, labels)
        assert len(on) == 1, f"port{number} 馈电点须恰在一个导体上"
        comp_of[number] = next(iter(on))
    assert comp_of[1] != comp_of[2]


def test_csxcad_bends_alternate_and_adjacent_open_ends_differ():
    """交替性从 CSXCAD 原语实测（不信布局字典）：弯带盒（x 跨两臂 = b+wf）的 y 中心逐腔
    轮替 y1/y0；每腔臂盒未被弯带覆盖的一端 = 开路端，相邻腔开路端 y 不同；相邻臂 y 跨度
    完全重叠（耦合长度 = 单臂长，翻转不缩短耦合区）。"""
    _, prims = _load()
    lay = ot._hairpin_alt_layout(NOMINAL)
    b, wf, y0, y1 = lay["b"], lay["wf"], lay["y0"], lay["y1"]
    metal = [p for p in prims if p.kind == "Metal"]
    bends = sorted((p for p in metal if abs(p.extent[0] - (b + wf)) < 1e-9),
                   key=lambda p: p.lo[0])
    assert len(bends) == lay["n"]
    y_bend_meas = [float((p.lo[1] + p.hi[1]) / 2.0) for p in bends]
    assert y_bend_meas == pytest.approx([y1, y0, y1], abs=1e-12)
    arms = sorted((p for p in metal if abs(p.extent[0] - wf) < 1e-9
                   and abs(p.extent[1] - lay["l_arm"]) < 1e-9), key=lambda p: p.lo[0])
    assert len(arms) == 2 * lay["n"]
    open_ends: list[float] = []
    for i in range(lay["n"]):
        bend = bends[i]
        for arm in arms[2 * i: 2 * i + 2]:
            assert arm.lo[1] == pytest.approx(y0, abs=1e-12)
            assert arm.hi[1] == pytest.approx(y1, abs=1e-12)
            top_covered = bend.lo[1] - 1e-12 <= arm.hi[1] <= bend.hi[1] + 1e-12
            bot_covered = bend.lo[1] - 1e-12 <= arm.lo[1] <= bend.hi[1] + 1e-12
            assert top_covered != bot_covered                     # 恰一端接弯带
            open_ends.append(float(arm.lo[1]) if top_covered else float(arm.hi[1]))
    assert open_ends == pytest.approx([y0, y0, y1, y1, y0, y0], abs=1e-12)
    for i in range(lay["n"] - 1):
        assert open_ends[2 * i + 1] != open_ends[2 * i + 2]       # 相邻臂开路端交替
        assert arms[2 * i + 1].lo[1] == pytest.approx(arms[2 * i + 2].lo[1], abs=1e-12)
        assert arms[2 * i + 1].hi[1] == pytest.approx(arms[2 * i + 2].hi[1], abs=1e-12)


def test_gap_interior_mesh_lines_and_near_guard_266():
    scope, _ = _load()
    lay = ot._hairpin_alt_layout(NOMINAL)
    wf, near = lay["wf"], float(scope["NEAR"])
    xl = gh.mesh_lines(scope, "x")
    for i in range(lay["n"] - 1):
        a = lay["xs"][2 * i + 1] + wf / 2
        c = lay["xs"][2 * i + 2] - wf / 2
        assert int(np.sum((xl > a + 1e-12) & (xl < c - 1e-12))) >= 1, f"缝 {i} 内无网格线"
        assert near <= (c - a) / 3.0 + 1e-15                      # NEAR ≤ 缝/3（#266）


def test_mesh_min_gap_guard_and_domain():
    scope, _ = _load()
    board = float(scope["BOARD"])
    for axis in ("x", "y", "z"):
        lines = gh.mesh_lines(scope, axis)
        diffs = np.diff(lines)
        assert bool(np.all(diffs > 1e-6)), f"{axis} 轴 <1µm 近重合线（#152）"
    for axis in ("x", "y"):
        lines = gh.mesh_lines(scope, axis)
        assert lines.min() == pytest.approx(-board, abs=1e-9)
        assert lines.max() == pytest.approx(board, abs=1e-9)


@pytest.mark.parametrize("key", list(ot.HAIRPIN_ALT_META["params"]))
def test_declared_params_drive_geometry(key):
    base = gh.conductor_signature(_load()[1])
    params = dict(NOMINAL)
    params[key] = float(NOMINAL[key]) * (0.9 if key == "tap_frac" else 1.37) + (
        0.0 if key == "tap_frac" else 0.013)
    assert gh.conductor_signature(_load(params)[1]) != base, key


def test_layout_validation_and_even_order_geometry_audit():
    with pytest.raises(ValueError):
        ot._hairpin_alt_layout(dict(NOMINAL, tap_frac=0.6))
    with pytest.raises(ValueError):
        ot._hairpin_alt_layout(dict(NOMINAL, order=4, gaps_mm=[1.0, 1.0]))
    with pytest.raises(ValueError):
        ot._hairpin_alt_layout(dict(NOMINAL, gap_mm=0.0))
    with pytest.raises(ValueError):
        ot._hairpin_alt_layout(dict(NOMINAL, arm_gap_mm=8.0, tap_frac=0.42))
    # N=2（末腔翻转、输出抽头 y≠输入）：CSXCAD 实测 2 隔离分量、两端口各属其一、
    # 输出馈线 y 中心 = y1−τ·L_tot
    params = dict(NOMINAL, order=2)
    scope, prims = _load(params)
    lay = ot._hairpin_alt_layout(params)
    conductors, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == 2
    ports = gh.port_objects(scope)
    comps = {n: next(iter(gh.containing_labels(gh.port_feed_point(p), conductors, labels)))
             for n, p in ports.items()}
    assert comps[1] != comps[2]
    p2 = np.asarray(ports[2].start, dtype=float)
    q2 = np.asarray(ports[2].stop, dtype=float)
    assert float((p2[1] + q2[1]) / 2.0) == pytest.approx(lay["y_tap_out"], abs=1e-12)
    assert float((p2[1] + q2[1]) / 2.0) != pytest.approx(lay["y_tap"], abs=1e-6)
    assert gh.off_mesh_planes(prims, scope) == []


def test_geometry_spec_preview_consistency():
    spec = ot.geometry_spec("hairpin_alt", dict(NOMINAL))
    names = [b["name"] for b in spec["boxes"]]
    assert names.count("substrate") == 1 and "ground" in names
    lay = ot._hairpin_alt_layout(NOMINAL)
    assert len([n for n in names if n.startswith("hairpin_r")]) == 3 * lay["n"]
    bends = [b for b in spec["boxes"] if b["name"].endswith("_bend")]
    yc = [(b["start_mm"][1] + b["stop_mm"][1]) / 2.0 for b in bends]
    assert yc == pytest.approx([v * 1e3 for v in lay["y_bend"]], abs=1e-9)
    assert "feed_in_tap" in names and "feed_out_tap" in names
    assert len(spec["ports"]) == 2
    assert [p["pos_mm"][1] for p in spec["ports"]] == pytest.approx(
        [v * 1e3 for v in lay["y_taps"]], abs=1e-9)
    spec2 = ot.geometry_spec("hairpin_alt", dict(NOMINAL, order=2))
    ys = [p["pos_mm"][1] for p in spec2["ports"]]
    assert ys[0] != pytest.approx(ys[1], abs=1e-6)
    # 同向对照 spec 与 hairpin spec 除模板名外逐字段相同
    spec_same = ot.geometry_spec("hairpin_alt", dict(NOMINAL, orientation="same"))
    spec_h = ot.geometry_spec("hairpin", dict(NOMINAL))
    assert set(spec_same) == set(spec_h)
    for key in spec_h:
        if key != "template":
            assert spec_same[key] == spec_h[key], key


# ─── ⑥ fake 派发：纯 KJ 电气通道 ─────────────────────────────────────────────────

class TestHairpinAltFakeDispatch:
    @staticmethod
    def _solve(model_type: str = "hairpin_alt", variables: dict | None = None,
               n_pts: int = 401):
        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter(model_type=model_type, n_ports=2, freq_ghz=(2.0, 3.0, n_pts),
                         f0_ghz=F0)
        ad.connect({})
        if variables:
            ad.set_variables(dict(variables))
        assert ad.solve("hairpin_alt_fake").success
        return ad.get_sparams()

    @staticmethod
    def _w3db(nt) -> float:
        f = nt.frequency.f / 1e9
        s21 = np.abs(nt.s[:, 1, 0])
        return float(np.ptp(f[s21 >= s21.max() / math.sqrt(2.0)]))

    def test_nominal_reproduces_c13_ideal_and_is_chebyshev(self):
        from rfauto.core.calculators import coupling_matrix_response

        nt = self._solve()
        f = nt.frequency.f / 1e9
        r = coupling_matrix_response(freq_ghz=list(f), f0_ghz=F0, fbw=FBW,
                                     matrix=DESIGN["coupling_matrix"])
        c = np.asarray(r["s_matrix"], dtype=float)
        s_ideal = c[..., 0] + 1j * c[..., 1]
        assert float(np.max(np.abs(nt.s - s_ideal))) <= 1e-3       # 舍入量级（实测 8e-5）
        s11 = 20.0 * np.log10(np.abs(nt.s[:, 0, 0]) + 1e-300)
        s21 = 20.0 * np.log10(np.abs(nt.s[:, 1, 0]) + 1e-300)
        band = (f >= F0 * (1 - FBW / 2)) & (f <= F0 * (1 + FBW / 2))
        assert s21[band].min() > -0.2 and s11[band].max() < -15.0   # 设计窗内切比雪夫
        assert s21[np.abs(f - F0) / F0 > 0.10].min() < -30.0
        assert float(np.max(np.abs(nt.s - nt.s.transpose(0, 2, 1)))) <= 1e-12
        assert float(np.max(np.abs(nt.s))) <= 1.0 + 1e-12

    def test_alt_differs_from_same_direction_only_by_kgap(self):
        """同一名义几何（显式变量，走 arm_len→f0 反演通道）：hairpin fake 乘 c(gap)
        （欠耦窄峰）、hairpin_alt 纯 KJ（设计带宽）；两者与各自 k 的解析参考 ≤1e-9。"""
        from rfauto.adapters.fake_adapter import _hairpin_sparams

        variables = {"order": "3", "w_mm": f"{NOMINAL['w_mm']}mm",
                     "arm_len_mm": f"{NOMINAL['arm_len_mm']}mm",
                     "gap_mm": f"{NOMINAL['gap_mm']}mm",
                     "tap_frac": str(NOMINAL["tap_frac"])}
        nt_alt = self._solve("hairpin_alt", variables, n_pts=1001)
        nt_same = self._solve("hairpin", variables, n_pts=1001)
        assert self._w3db(nt_alt) > 5.0 * self._w3db(nt_same)
        f = nt_alt.frequency.f / 1e9
        k_kj = cm.hairpin_k_from_gap_mm(NOMINAL["gap_mm"], NOMINAL["w_mm"])
        k_same = cm.hairpin_k_from_gap_mm(NOMINAL["gap_mm"], NOMINAL["w_mm"],
                                          structural_correction=True)
        from rfauto.adapters.fake_adapter import _HAIRPIN_F0_CORR, _HAIRPIN_QE_CORR
        c0, c1 = _HAIRPIN_QE_CORR
        tau = NOMINAL["tap_frac"]
        qe = cm.hairpin_qe_from_tap_frac(tau) * (c0 + c1 * tau)
        f0 = _HAIRPIN_F0_CORR * (299792458.0 / (
            2.0 * NOMINAL["arm_len_mm"] * 1e-3 * math.sqrt(_eps_eff(NOMINAL["w_mm"])))) / 1e9
        ref_alt = _hairpin_sparams(f, f0_ghz=f0, order=3, k_list=[k_kj, k_kj], qe=qe)
        ref_same = _hairpin_sparams(f, f0_ghz=f0, order=3, k_list=[k_same, k_same], qe=qe)
        assert float(np.max(np.abs(nt_alt.s - ref_alt))) <= 1e-9
        assert float(np.max(np.abs(nt_same.s - ref_same))) <= 1e-9

    def test_gap_sweep_bandwidth_monotone_over_whole_domain(self):
        """纯 KJ 无相消支：gap 0.5→2.2 全域 3dB 带宽单调窄（同向 fake 在 <0.65 反而变窄）。"""
        widths = [self._w3db(self._solve(variables={"gap_mm": f"{g}mm"}, n_pts=2001))
                  for g in (0.5, 0.8, 1.1328, 1.6, 2.2)]
        assert all(a > b for a, b in pairwise(widths)), widths

    def test_recipe_draft_via_spec(self):
        from rfauto.models.template_spec import TEMPLATE_SPECS
        from rfauto.models.template_specs import bootstrap_template_specs

        bootstrap_template_specs()
        draft = TEMPLATE_SPECS.draft_recipe("hairpin_alt", order=3, f0_ghz=F0, fbw=FBW,
                                            rl_db=RL_DB)
        assert draft["model"] == "hairpin_alt_bpf"
        assert set(NOMINAL) <= set(draft["params"])
        assert draft["params"]["gap_mm"]["value"] == pytest.approx(1.1328, abs=1e-3)


# ─── ⑦ k(gap) 图谱判读门（纯函数，先于真机写死）──────────────────────────────────

GAPS = [g for g, _ in cm.HAIRPIN_KGAP_TABLE_MM]        # 0.5/0.65/0.8/1.1328（同向标定 gap 网格）
W_MM = 1.1117


def _k_kj(g: float) -> float:
    return cm.hairpin_k_from_gap_mm(g, W_MM)


def test_gate_constants_predeclared():
    gate = qx.HAIRPIN_ALT_KGAP_GATE
    assert gate["c_min"] == 0.6 and gate["c_max"] == 1.2 and gate["min_points"] == 3
    assert gate["c_min"] >= 2.0 * gate["same_orientation_c_ceiling"]   # "显著高于"可证伪口径
    # 同向真机比值上限 ≈ k_EM 极大 / 设计 k_KJ（0.0155/0.0515≈0.30）与门参照一致
    k_peak = max(cm.hairpin_k_from_gap_mm(g, W_MM, structural_correction=True) for g in GAPS)
    assert k_peak / _k_kj(1.1328) == pytest.approx(gate["same_orientation_c_ceiling"], abs=0.02)
    # 上限覆盖 KJ vs NGSolve 独立源比值（1.003-1.049）
    assert gate["c_max"] > 1.05


def test_gate_rejects_real_same_orientation_table():
    """真机同向表（HAIRPIN_KGAP_TABLE_MM）必 FAIL：单调红（0.5→0.65 上升）+ 比值红（全部 <0.6）。"""
    k_em = [cm.hairpin_k_from_gap_mm(g, W_MM, structural_correction=True) for g in GAPS]
    r = qx.hairpin_alt_kgap_gate(GAPS, k_em, k_target=0.0515)
    assert r["verdict"] == "FAIL" and r["monotone"] is False and r["ratio_ok"] is False
    assert r["n_points"] == 4 and r["reachable"] is False
    assert [round(p["c"], 3) for p in r["points"]] == [0.121, 0.161, 0.194, 0.258]
    assert any("非严格递减" in s for s in r["reasons"])
    assert any("< 门 0.6" in s for s in r["reasons"])
    assert r["c_obs"][1] < qx.HAIRPIN_ALT_KGAP_GATE["c_min"]


def test_gate_passes_synthetic_alternating_curve_and_reports_reachability():
    k_em = [0.9 * _k_kj(g) for g in GAPS]
    r = qx.hairpin_alt_kgap_gate(GAPS, k_em, k_target=0.0515)
    assert r["verdict"] == "PASS" and r["monotone"] and r["ratio_ok"] and r["reasons"] == []
    assert r["c_obs"] == pytest.approx([0.9, 0.9], rel=1e-12)
    assert r["reachable"] is True                                   # 0.0515 ∈ [k(1.1328), k(0.5)]·0.9
    assert r["k_target"] == 0.0515
    assert [p["gap_mm"] for p in r["points"]] == sorted(GAPS)
    # 显式 k_kj 与缺省内核复算逐位一致；乱序输入结果相同
    r2 = qx.hairpin_alt_kgap_gate(GAPS, k_em, [_k_kj(g) for g in GAPS])
    assert r2["points"] == r["points"]
    shuffled = [GAPS[2], GAPS[0], GAPS[3], GAPS[1]]
    r3 = qx.hairpin_alt_kgap_gate(shuffled, [0.9 * _k_kj(g) for g in shuffled])
    assert r3["points"] == r["points"] and r3["verdict"] == "PASS"
    # 设计 k 不可达（全部点 k_EM 低于 0.0515）→ reachable False 但 verdict 不受影响
    r4 = qx.hairpin_alt_kgap_gate(GAPS, [0.7 * _k_kj(g) for g in GAPS], k_target=0.09)
    assert r4["verdict"] == "PASS" and r4["reachable"] is False


@pytest.mark.parametrize("c,verdict", [(0.6, "PASS"), (1.2, "PASS"), (0.599, "FAIL"),
                                       (1.201, "FAIL"), (0.30, "FAIL")])
def test_gate_ratio_boundaries_inclusive(c, verdict):
    r = qx.hairpin_alt_kgap_gate(GAPS, [c * _k_kj(g) for g in GAPS])
    assert r["verdict"] == verdict
    assert r["monotone"] is True                                    # 单调不受比例影响
    assert r["ratio_ok"] is (verdict == "PASS")


def test_gate_nonmonotone_synthetic_fails_even_with_good_ratios():
    ks = [0.9 * _k_kj(g) for g in GAPS]
    ks[1] = ks[0] * 1.01                                            # 0.65 处抬高 → 非单调
    r = qx.hairpin_alt_kgap_gate(GAPS, ks)
    assert r["verdict"] == "FAIL" and r["monotone"] is False
    assert r["ratio_ok"] is True and len(r["reasons"]) == 1
    flat = [0.9 * _k_kj(g) for g in GAPS]
    flat[2] = flat[1]                                               # 相等亦非"严格"递减
    assert qx.hairpin_alt_kgap_gate(GAPS, flat)["monotone"] is False


def test_gate_min_points_overrides_and_input_validation():
    two = qx.hairpin_alt_kgap_gate(GAPS[:2], [0.9 * _k_kj(g) for g in GAPS[:2]])
    assert two["verdict"] == "FAIL" and two["monotone"] and two["ratio_ok"]
    assert any("点数 2 < 3" in s for s in two["reasons"])
    assert qx.hairpin_alt_kgap_gate(GAPS[:2], [0.9 * _k_kj(g) for g in GAPS[:2]],
                                    min_points=2)["verdict"] == "PASS"
    assert qx.hairpin_alt_kgap_gate(GAPS, [0.5 * _k_kj(g) for g in GAPS],
                                    c_min=0.4)["verdict"] == "PASS"
    empty = qx.hairpin_alt_kgap_gate([], [])
    assert empty["verdict"] == "FAIL" and empty["c_obs"] is None and empty["n_points"] == 0
    with pytest.raises(ValueError):
        qx.hairpin_alt_kgap_gate(GAPS, [0.05, 0.04])                # 长度不等
    with pytest.raises(ValueError):
        qx.hairpin_alt_kgap_gate(GAPS, [0.05, 0.04, 0.0, 0.02])     # 非正 k
    with pytest.raises(ValueError):
        qx.hairpin_alt_kgap_gate([0.5, 0.5, 0.8], [0.05, 0.04, 0.03])   # gap 重复
    with pytest.raises(ValueError):
        qx.hairpin_alt_kgap_gate(GAPS, [0.9 * _k_kj(g) for g in GAPS], c_min=1.3, c_max=1.2)
    with pytest.raises(ValueError):
        qx.hairpin_alt_kgap_gate(GAPS, [0.9 * _k_kj(g) for g in GAPS], k_kj=[1.0, 2.0])


def test_scripts_cli_wiring(monkeypatch, capsys):
    """判读器接线：hairpin_q_extract --gate alt/--k-target/--kgap-out 与 hairpin_calib
    --template {hairpin,hairpin_alt}（argparse 真构建，--help 不触引擎）。"""
    monkeypatch.setattr(sys, "argv", ["hairpin_q_extract.py", "--help"])
    with pytest.raises(SystemExit) as exc:
        qx.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--gate", "--k-target", "--kgap-out", "hairpin_alt_kgap_gate"):
        assert flag in out, flag
    spec = importlib.util.spec_from_file_location(
        "_hairpin_calib_alt_cli", str(REPO / "scripts" / "hairpin_calib.py"))
    assert spec is not None and spec.loader is not None
    hc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hc)
    monkeypatch.setattr(sys, "argv", ["hairpin_calib.py", "--help"])
    with pytest.raises(SystemExit) as exc2:
        hc.main()
    assert exc2.value.code == 0
    out2 = capsys.readouterr().out
    assert "--template" in out2 and "hairpin_alt" in out2
    src = (REPO / "scripts" / "hairpin_calib.py").read_text(encoding="utf-8")
    assert 'build_geometry({"template": args.template' in src
    assert '"template": args.template' in src                        # evidence 记录模板名
