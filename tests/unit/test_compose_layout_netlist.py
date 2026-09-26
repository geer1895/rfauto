"""DP-8 组合引擎离线审计（P1+P2；#212 制度化升级）。

权威口径：docs/plan_deepdive_specs_20260924.md §DP-8 +
runs/df6_dp8compose/criteria.md（C1-C3 判据预声明；C4/C5 留 P3）。

覆盖：
  C1 golden 门：首例「MSL 过渡+SIW 直段+MSL 过渡」组合输出与
     tests/golden/compose_siw_chain_simulation.py 逐字节一致（sha256/diff=0）；
  C2 组合 fixture 离线审计：exec 截断于 FDTD.Run（秒级零仿真）——图元落
     CSX（属性 ns/过孔数/心距）、netlist 入口断言（结缝跨实例导体 1 连通
     分量、FDTD 端口数=exposed 数、内部 pin 零端口）、#152/#283/#347 守卫
     在文本、D1-D6/P1-P5 守卫全 ok、compose_meta 确定性（双跑逐字节同）；
  C3 pin 负例 ≥4（错位/不可对向/阻抗失配/截面-基板失配，报错含两 pin id）
     + 附加负例（未注册模板/siw v1 拒绝/P4 越界/D4 msl 内连/D6 实例漂移/
     D3 合并集地板/D1 面不贴界/孤立实例/exposed>4）；
  缺省渲染不变门：siw v1=80d24e93…（既有钉同值复验）+ msl_siw_taper
     缺省=c5aeb12c…（DP-8 改动前基线冻结）+ siw v2=f9524bf1…（组合消费
     路径不得漂移 standalone v2）；
  五消费者核对：TEMPLATE_META 增 port_pins 键不改模板数（45）/params 键集。
"""

from __future__ import annotations

import copy
import hashlib
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.compose.layout_netlist import (
    ComposeError,
    canonical_json,
    compose_netlist,
)
from rfauto.service.compose_service import (
    GOLDEN_NETLISTS,
    compose_from_netlist,
    compose_from_yaml_file,
    compose_write,
    list_composable_templates,
    load_golden_netlist,
    verify_compose_provenance,
)

BAND = (9.75, 10.25)
BASE = 0.4e-3
H = 0.508e-3
SUB = {"h_mm": 0.508, "er": 3.66, "tan_d": 0.0037}

# 缺省渲染字节钉（§3 判据；taper/v2 二值=DP-8 改动前实测基线冻结）
_V1_RENDER_SHA256 = "80d24e932c826b61906964aa0e5bad084a721ec905cbf656bc598adea030e2af"
_TAPER_RENDER_SHA256 = "c5aeb12cf6edda74eb527523f449fe967daf24ed8be036e956cedc9113c07a48"
_SIW_V2_RENDER_SHA256 = "f9524bf1fe128626e6a672a18f02d0331857c80f401e935c4e206ab96bf73d1f"

_GOLDEN = REPO / "tests" / "golden" / "compose_siw_chain_simulation.py"


def _contracts() -> dict:
    from rfauto.adapters.openems_templates import COMPOSE_CONTRACTS

    return dict(COMPOSE_CONTRACTS)


def _schema_map() -> dict:
    from rfauto.adapters.openems_templates import TEMPLATE_META

    return {t: m["port_pins"] for t, m in TEMPLATE_META.items()
            if m.get("port_pins")}


def _chain() -> dict:
    """净 netlist 深拷贝（防用例间共享 fixture 变异互染）。"""
    return copy.deepcopy(GOLDEN_NETLISTS["siw_chain"])


def _compose(netlist=None):
    text, meta = compose_netlist(netlist or _chain(), _contracts(),
                                 _schema_map())
    return text, meta


def _load_exec(text: str) -> dict:
    """exec 截断于 FDTD.Run（test_siw_template 同 harness；秒级零仿真）。"""
    cut = text.index("FDTD.Run(")
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_compose_audit.py")}
    exec(compile(text[:cut], "compose_audit", "exec"), scope)
    return scope


def _props(scope: dict) -> dict[str, list]:
    """CSX 属性名 → 原语列表（exec 审计：看脚本实际建了什么）。"""
    csx = scope["CSX"]
    out: dict[str, list] = {}
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        out.setdefault(str(prop.GetName()), []).append(prop)
    return out


def _prims(prop) -> list:
    return list(prop.GetAllPrimitives())


# ─── C1：golden 逐字节门 ────────────────────────────────────────────────────

def test_c1_golden_byte_identical():
    """C1 硬门：组合输出 sha256==goldfile（diff=0）；meta.netlist_sha 稳定。"""
    assert _GOLDEN.exists(), f"goldfile 缺失: {_GOLDEN}"
    text, meta = _compose()
    golden = _GOLDEN.read_bytes()
    assert text.encode("utf-8") == golden, (
        "C1 字节同失败：组合输出与 goldfile 漂移——有意改动必须换钉并留 "
        "unified diff 证据（runs/df6_dp8compose/criteria.md §2 C1）")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == (
        meta["render_sha256"])


def test_c1_golden_netlist_fixture_is_single_source():
    """goldfile 的 netlist=GOLDEN_NETLISTS['siw_chain']（canonical sha 一致）。"""
    from rfauto.core.compose.layout_netlist import normalize_netlist

    assert _GOLDEN.exists()
    _, meta = _compose()
    assert canonical_json(meta["netlist"]) == canonical_json(
        normalize_netlist(_chain()))


# ─── C2：组合 fixture 离线审计（#212 升级）──────────────────────────────────

@pytest.fixture(scope="module")
def composed():
    text, meta = _compose()
    return text, meta, _load_exec(text)


def test_c2_properties_namespaced_and_bot_unified(composed):
    """图元落 CSX：实例属性带 ns 后缀；统一底板 compose_bot 单属性。"""
    _text, _meta, scope = composed
    names = set(_props(scope))
    for expect in ("substrate", "compose_bot", "msl_top__taper_in",
                   "siw_via__taper_in", "siw_top__run", "siw_via__run",
                   "msl_top__taper_out", "siw_via__taper_out"):
        assert expect in names, f"缺属性 {expect}（实际 {sorted(names)}）"


def test_c2_via_counts_and_pitch(composed):
    """过孔藩篱：taper(siwl_len=2.6) 3 孔/列×2、run(v2) 63 孔/列×2；心距=s。"""
    _text, _meta, scope = composed
    props = _props(scope)
    for name, n_per_col in (("siw_via__taper_in", 3), ("siw_via__run", 63),
                            ("siw_via__taper_out", 3)):
        cyl = _prims(props[name][0])
        assert len(cyl) == 2 * n_per_col, (
            f"{name}: 过孔数 {len(cyl)} ≠ 2×{n_per_col}")
        ys = sorted({round(float(c.GetStart()[1]), 12) for c in cyl})
        assert len(ys) == n_per_col
        assert all(b - a == pytest.approx(1e-3, abs=1e-12)
                   for a, b in pairwise(ys))


def test_c2_netlist_entry_port_count_and_internal_silent(composed):
    """netlist 入口断言①：FDTD 端口数=exposed 数（2）；内部 pin 零端口。"""
    text, meta, scope = composed
    assert "_port1" in scope and "_port2" in scope
    assert "_port3" not in text and "AddLumpedPort" not in text, (
        "D4 内部 pin 泄漏成 FDTD 端口（run.p1/p2、taper.siw 均须静默省略）")
    assert meta["exposed_ports"] == [
        {"port_nr": 1, "instance": "taper_in", "pin": "msl",
         "port_type": "msl", "z_ref_ohm": 50.0},
        {"port_nr": 2, "instance": "taper_out", "pin": "msl",
         "port_type": "msl", "z_ref_ohm": 50.0}]


def test_c2_netlist_entry_seam_conductor_one_component(composed):
    """netlist 入口断言②：每 connection 结缝跨实例顶板导体 1 连通分量。"""
    _text, meta, scope = composed
    props = _props(scope)
    metal = {n: ps for n, ps in props.items()
             if n.startswith(("msl_top", "siw_top", "compose_bot"))}
    for conn in meta["connections"]:
        seam = conn["seam_y_m"]
        tol = 1e-9
        intervals: list[tuple[float, float]] = []
        for _name, ps in metal.items():
            for prop in ps:
                for prim in _prims(prop):
                    bb = np.asarray(prim.GetBoundBox(), dtype=float)
                    lo, hi = bb[0], bb[1]
                    if hi[2] - lo[2] > 1e-12:
                        continue  # 只看 z=H_SUB 面内导体（顶板/带/锥）
                    if abs(hi[2] - 0.000508) > 1e-12:
                        continue
                    if lo[1] - tol <= seam <= hi[1] + tol:
                        intervals.append((float(lo[0]), float(hi[0])))
        merged: list[list[float]] = []
        for lo, hi in sorted(intervals):
            if merged and lo <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        assert len(merged) == 1, (
            f"结缝 y={seam!r} 顶板导体 {len(merged)} 个连通分量（须 1）"
            f"：{merged}")
        assert merged[0][0] <= -0.00606585 and merged[0][1] >= 0.00606585, (
            "结缝导体未覆盖过孔藩篱截面 ±w/2")


def test_c2_runtime_guards_in_text_and_meta_guards_ok(composed):
    """#152/#283/#347 生成期守卫在文本；D1-D6/P1-P5 守卫全 ok（各一正例）。"""
    text, meta, _scope = composed
    assert '"152"' in text and '"283"' in text
    assert text.count('"347"') == 2  # 双 taper 契约自带守卫
    g = meta["guards"]
    for key in ("D1", "D2", "D3", "D4", "D5", "D6",
                "P1", "P2", "P3", "P4", "P5"):
        assert g[key] == "ok", f"守卫 {key} 未 ok：{g}"


def test_c2_d1_domain_union_and_boundary_faces(composed):
    """D1 正例细节：合并域=∪dom；两 exposed msl 面各贴 y_min/y_max。"""
    _text, meta, _scope = composed
    dom = meta["domain_m"]
    assert dom["y_min"] == pytest.approx(-0.0175121, abs=1e-12)
    assert dom["y_max"] == pytest.approx(0.0833845, abs=1e-12)
    pins = {i["id"]: i["pins"] for i in meta["instances"]}
    assert pins["taper_in"]["msl"]["position_m"][1] == dom["y_min"]
    assert pins["taper_out"]["msl"]["position_m"][1] == dom["y_max"]
    assert pins["taper_in"]["msl"]["exposed"] is True
    assert pins["run"]["p1"]["exposed"] is False
    assert pins["run"]["p1"]["port_nr"] is None


def test_c2_d2_seam_diagnostics_and_d5_estimates(composed):
    """D2 诊断（跨缝藩篱间隙=0.8362mm 如实记录不判门）+ D5 dt/NrTS 估算。"""
    _text, meta, _scope = composed
    seams = meta["connections"]
    assert len(seams) == 2
    for s in seams:
        assert s["seam_via_gap_m"] == pytest.approx(0.9362e-3, abs=1e-9)
    est = meta["estimates"]
    assert est["nrts"] == 100000
    assert 0 < est["dt_s"] < 1e-10  # min 格 0.1mm 量级 / (c·√3)
    assert "CFL" in est["dt_basis"] or "#328" in est["dt_basis"]


def test_c2_frame_placement_and_compose_meta_determinism():
    """摆位确定性：双跑文本逐字节同；taper_out 帧=rot180+平移解析值。"""
    t1, m1 = _compose()
    t2, m2 = _compose()
    assert t1 == t2 and m1 == m2
    frames = {i["id"]: i["frame"] for i in m1["instances"]}
    assert frames["taper_in"] == [0.0, 0.0, False]
    assert frames["run"][2] is False
    assert frames["run"][1] == pytest.approx(0.0329362, abs=1e-15)
    assert frames["taper_out"][2] is True
    assert frames["taper_out"][1] == pytest.approx(0.0658724, abs=1e-12)


def test_c2_z_mesh_and_boundary_lines(composed):
    """组合域 D5 口径：y 端 PML_8/z 底 PEC/顶 MUR；z 网格=基板 4 层+AIR_TOP。"""
    text, _meta, _scope = composed
    assert ('FDTD.SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", '
            '"PEC", "MUR"])') in text
    assert 'mesh.AddLine("z", np.linspace(0, H_SUB, 5))' in text
    assert 'mesh.AddLine("z", H_SUB + AIR_TOP)' in text


# ─── C3：pin 负例（≥4；报错含两 pin id+坐标+差值）──────────────────────────

def _taper_siw_z() -> float:
    lay = _contracts()["msl_siw_taper"]["layout"](
        {"siw_len_mm": 2.8}, BAND, BASE, H, (0.0, 0.0, False))
    return float(lay["pins"]["siw"]["z_ref_ohm"])


def _stub_contract(*, pin_dir=(0, -1), z=None, er=3.66, port_type="lumped",
                   ref_plane=0.0, box_dy=5e-4):
    z = _taper_siw_z() if z is None else z

    def layout(params, band, base, h, frame):
        from rfauto.core.compose.layout_netlist import frame_apply_dir, frame_apply_point

        pos = frame_apply_point(frame, (0.0, 0.0))
        dirv = frame_apply_dir(frame, pin_dir)
        xlo = min(frame_apply_point(frame, (-7e-3, 0.0))[0],
                  frame_apply_point(frame, (7e-3, 0.0))[0])
        xhi = max(frame_apply_point(frame, (-7e-3, 0.0))[0],
                  frame_apply_point(frame, (7e-3, 0.0))[0])
        pin = {"pin_id": "q", "position": [pos[0], pos[1]],
               "direction": [dirv[0], dirv[1]], "z_ref_ohm": z,
               "ref_plane_offset_m": ref_plane, "port_type": port_type,
               "n_modes": None,
               "cross_section": {"kind": "siw", "w_mm": 12.1317,
                                 "d_mm": 0.6, "s_mm": 1.0, "h_mm": 0.508,
                                 "er": er},
               "width_m": 0.0121317}
        prims = [
            {"kind": "box", "prop": "stub_top",
             "start": [xlo, pos[1] - box_dy, H],
             "stop": [xhi, pos[1] + box_dy, H], "priority": 10},
            {"kind": "port", "pin": "q", "port_type": port_type,
             "prop": "stub_top",
             "start": [xlo, pos[1] - 1e-4, 0.0],
             "stop": [xhi, pos[1] + 1e-4, H],
             "axis": "z", "ref_impedance": z, "priority": 5},
        ]
        if port_type == "msl":
            prims[1]["feed_shift"] = 10.0 * base
            prims[1]["meas_plane_shift"] = base
        return {"pins": {"q": pin},
                "dom": (xlo, pos[1] - box_dy - 2e-3,
                        xhi, pos[1] + box_dy + 2e-3),
                "bbox": (xlo, pos[1] - box_dy, xhi, pos[1] + box_dy),
                "primitives": prims,
                "plates_top": [(xlo, pos[1] - box_dy, xhi,
                                pos[1] + box_dy)],
                "bottom_plate": (xlo, pos[1] - box_dy - 2e-3,
                                 xhi, pos[1] + box_dy + 2e-3),
                "bc_compat": "siw_family",
                "face_on_boundary": {"q": port_type == "msl"},
                "clearance_m": {"q": 0.0},
                "span_m": {"q": 2e-3},
                "substrate": {"h_m": H, "er": 3.66, "tan_d": 0.0037},
                "guards_text": []}

    return {"layout": layout}


def test_c3_p1_misalignment_reports_both_pins_and_delta():
    """C3-1 错位：冗余第 4 连接（两端已摆位）→ P1 报双 pin id+|Δ|=全链长。"""
    nl = _chain()
    nl["connections"].append({"a": ["taper_in", "siw"],
                              "b": ["taper_out", "siw"]})
    with pytest.raises(ComposeError) as ei:
        compose_netlist(nl, _contracts(), _schema_map())
    msg = str(ei.value)
    assert "P1" in msg and "taper_in.siw" in msg and "taper_out.siw" in msg
    assert "|Δ|" in msg and "dx=" in msg and "dy=" in msg


def test_c3_p2_perpendicular_direction_unsolvable():
    """C3-2 同向/不可对向：stub x 向 pin 连 taper.siw（y 向）→ P2 双 pin id。"""
    contracts = {**_contracts(), "stub": _stub_contract(pin_dir=(1, 0))}
    nl = _chain()
    nl["instances"].append({"id": "stubx", "template": "stub", "params": {}})
    nl["connections"].append({"a": ["taper_in", "siw"],
                              "b": ["stubx", "q"]})
    with pytest.raises(ComposeError) as ei:
        compose_netlist(nl, contracts, None)
    msg = str(ei.value)
    assert "P2" in msg and "taper_in.siw" in msg and "stubx.q" in msg
    assert "dot=" in msg


def test_c3_p3_impedance_mismatch_and_allow_mismatch_exemption():
    """C3-3 阻抗失配：stub z=25Ω → P3 双 pin id；allow_mismatch 放行+留痕。"""
    contracts = {**_contracts(), "stub": _stub_contract(z=25.0)}
    nl = _chain()
    nl["instances"].append({"id": "stubz", "template": "stub", "params": {}})
    nl["connections"].append({"a": ["taper_in", "siw"],
                              "b": ["stubz", "q"]})
    nl["exposed_ports"].append({"instance": "stubz", "pin": "q"})
    with pytest.raises(ComposeError) as ei:
        compose_netlist(nl, contracts, None)
    msg = str(ei.value)
    assert "P3" in msg and "taper_in.siw" in msg and "stubz.q" in msg
    assert "25.0" in msg and "allow_mismatch" in msg
    # 显式豁免：组合成功 + compose_meta 留痕
    nl["connections"][-1]["allow_mismatch"] = True
    _text, meta = compose_netlist(nl, contracts, None)
    notes = meta["p3_impedance_exemptions"]
    assert len(notes) == 1 and notes[0]["pin_a"] == "siw" and (
        notes[0]["pin_b"] == "q")
    assert notes[0]["exempted_by"] == "connection.allow_mismatch"


def test_c3_p5_cross_section_substrate_mismatch_reports_both_pins():
    """C3-4 基板/截面失配：stub 截面 εr=4.4（D6 substrate 相符不截胡）→
    P5 报双 pin id+失配字段。"""
    contracts = {**_contracts(), "stub": _stub_contract(er=4.4)}
    nl = _chain()
    nl["instances"].append({"id": "stubsub", "template": "stub",
                            "params": {}})
    nl["connections"].append({"a": ["taper_in", "siw"],
                              "b": ["stubsub", "q"]})
    nl["exposed_ports"].append({"instance": "stubsub", "pin": "q"})
    with pytest.raises(ComposeError) as ei:
        compose_netlist(nl, contracts, None)
    msg = str(ei.value)
    assert "P5" in msg and "taper_in.siw" in msg and "stubsub.q" in msg
    assert "er" in msg


def test_c3_real_contracts_feature_size_mismatch_guard_precedence():
    """真契约补例：run s_mm=1.2（D6 substrate 全符）——s_mm 进入 Z_PV 闭式
    （w_eff(w,d,s) 同链），按规格 P1→P5 顺序 P3 阻抗守卫先触发（双 pin id）；
    纯截面失配（不动 z_ref 链）由 stub P5 用例覆盖。如实记录守卫优先级。"""
    nl = _chain()
    nl["instances"][1]["params"]["s_mm"] = 1.2
    with pytest.raises(ComposeError) as ei:
        compose_netlist(nl, _contracts(), _schema_map())
    msg = str(ei.value)
    assert "P3" in msg and "taper_in.siw" in msg and "run.p1" in msg
    assert "22.6209" in msg  # s_mm=1.2 的 Z_PV 闭式同源重算值


# ─── 附加负例（≥4 之外的显式拒绝面）────────────────────────────────────────

def test_neg_unregistered_template_explicit():
    """opt-in 渐进：未注册组合契约的模板显式报错，不静默。"""
    nl = _chain()
    nl["instances"][1]["template"] = "patch"
    with pytest.raises(ComposeError, match="未注册组合契约"):
        compose_netlist(nl, _contracts(), _schema_map())


def test_neg_siw_v1_rejected_in_compose_only():
    """组合内 siw v1 显式拒绝；standalone 缺省 v1 不受影响（字节钉另测）。"""
    nl = _chain()
    nl["instances"][1]["params"]["_port_mode"] = "v1"
    with pytest.raises(ValueError, match="_port_mode"):
        compose_netlist(nl, _contracts(), _schema_map())
    from rfauto.adapters.openems_templates import render_script
    nom = {"w_mm": 12.1317, "d_mm": 0.6, "s_mm": 1.0, "line_len_mm": 63.0724}
    text = render_script("siw", dict(nom), BAND, mesh_resolution_mm=0.4)
    assert "_port_mode" not in text  # standalone 未携带旋钮=v1 缺省路径


def test_neg_p4_ref_plane_beyond_span():
    """P4 参考面望远镜越界：stub offset=10m > 实例跨度 1mm。"""
    contracts = {**_contracts(),
                 "stub": _stub_contract(ref_plane=10.0)}
    nl = _chain()
    nl["instances"].append({"id": "stubp4", "template": "stub", "params": {}})
    nl["connections"].append({"a": ["taper_in", "siw"],
                              "b": ["stubp4", "q"]})
    nl["exposed_ports"].append({"instance": "stubp4", "pin": "q"})
    with pytest.raises(ComposeError) as ei:
        compose_netlist(nl, contracts, None)
    msg = str(ei.value)
    assert "P4" in msg and "stubp4.q" in msg and "10.0" in msg


def test_neg_d4_internal_msl_pin_rejected():
    """D4：漏 expose 第二个 taper 的 msl pin（内连）→ 显式拒绝（馈线缺失）。"""
    nl = _chain()
    nl["exposed_ports"] = [{"instance": "taper_in", "pin": "msl"},
                           {"instance": "run", "pin": "p1"}]
    with pytest.raises(ComposeError, match="D4"):
        compose_netlist(nl, _contracts(), _schema_map())


def test_neg_d6_instance_substrate_drift():
    """D6：run 实例 εr=4.4 与 netlist 3.66 漂移（band/substrate 必须一致）。"""
    nl = _chain()
    nl["instances"][1]["params"]["er"] = 4.4
    with pytest.raises(ComposeError, match="D6"):
        compose_netlist(nl, _contracts(), _schema_map())


def test_neg_d3_merged_floor_violation():
    """D3：stub 盒缘距结缝 6µm < 10µm 地板（#349 在合并集重跑触发）。"""
    contracts = {**_contracts(), "stub": _stub_contract(box_dy=6e-6)}
    nl = _chain()
    nl["instances"].append({"id": "stubd3", "template": "stub", "params": {}})
    nl["connections"].append({"a": ["taper_in", "siw"],
                              "b": ["stubd3", "q"]})
    nl["exposed_ports"].append({"instance": "stubd3", "pin": "q"})
    with pytest.raises(ComposeError, match="D3"):
        compose_netlist(nl, contracts, None)


def test_neg_d1_exposed_msl_face_not_on_boundary():
    """D1：exposed msl pin 面不在合并域界（stub 接 run 末端）→ 显式拒绝。"""
    contracts = {**_contracts(), "stub": _stub_contract(port_type="msl")}
    nl = _chain()
    nl["instances"].append({"id": "stubd1", "template": "stub", "params": {}})
    nl["connections"].append({"a": ["run", "p2"], "b": ["stubd1", "q"]})
    nl["exposed_ports"] = [{"instance": "taper_in", "pin": "msl"},
                           {"instance": "taper_out", "pin": "msl"},
                           {"instance": "stubd1", "pin": "q"}]
    with pytest.raises(ComposeError, match="D1"):
        compose_netlist(nl, contracts, None)


def test_neg_orphan_instance_and_exposed_overflow():
    """孤立实例（无 connections 锚定）与 exposed>4 显式拒绝。"""
    nl = _chain()
    nl["instances"].append({"id": "orphan", "template": "siw", "params": {}})
    with pytest.raises(ComposeError, match="孤立实例"):
        compose_netlist(nl, _contracts(), _schema_map())
    nl = _chain()
    nl["exposed_ports"] = [{"instance": "taper_in", "pin": "msl"}] * 5
    with pytest.raises(ComposeError, match="D4 上限"):
        compose_netlist(nl, _contracts(), _schema_map())


# ─── 缺省渲染不变门（字节钉复验）────────────────────────────────────────────

def test_default_render_byte_pins_unchanged():
    """siw v1/taper 缺省/siw v2 渲染 sha256 三钉不变（openems_templates.py
    只允许 port_pins+契约增量；任何缺省渲染漂移即红，换钉须留 diff 证据）。"""
    from rfauto.adapters.openems_templates import render_script
    nom = {"w_mm": 12.1317, "d_mm": 0.6, "s_mm": 1.0, "line_len_mm": 63.0724}
    v1 = render_script("siw", dict(nom), BAND, mesh_resolution_mm=0.4)
    assert hashlib.sha256(v1.encode("utf-8")).hexdigest() == _V1_RENDER_SHA256
    taper = render_script("msl_siw_taper", {}, BAND, mesh_resolution_mm=0.4)
    assert hashlib.sha256(taper.encode("utf-8")).hexdigest() == (
        _TAPER_RENDER_SHA256)
    v2 = render_script("siw", {**nom, "_port_mode": "v2"}, BAND,
                       mesh_resolution_mm=0.4)
    assert hashlib.sha256(v2.encode("utf-8")).hexdigest() == (
        _SIW_V2_RENDER_SHA256)


# ─── 五消费者同步核对（TEMPLATE_META 增 port_pins 键不改模板数）────────────

def test_consumers_template_count_and_params_unchanged():
    """45 不变；port_pins 只增值不改 params/nominal 键集（五消费者口径）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL
    assert len(TEMPLATE_META) == 53 and len(TEMPLATE_NOMINAL) == 53
    assert TEMPLATE_META["siw"]["params"] == ["w_mm", "d_mm", "s_mm",
                                              "line_len_mm"]
    assert TEMPLATE_META["msl_siw_taper"]["params"] == [
        "w_mm", "d_mm", "s_mm", "taper_len_mm", "siw_len_mm"]
    assert set(TEMPLATE_META["siw"]["port_pins"][0]) == {
        "pin_id", "position", "direction", "z_ref_ohm", "ref_plane_offset_m",
        "port_type", "n_modes", "cross_section"}
    schema = _schema_map()
    assert set(schema) == {"siw", "msl_siw_taper"}
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES
    assert len(EXPECTED_TEMPLATES) == 53
    assert {"siw", "msl_siw_taper"} <= set(EXPECTED_TEMPLATES)


# ─── service 层（YAML 进出 + provenance 复验）──────────────────────────────

def test_service_compose_and_provenance_roundtrip(tmp_path):
    """compose_write 三件套落盘 + verify_compose_provenance sha 对账 ok。"""
    r = compose_write(_chain(), tmp_path)
    assert r["ok"], r
    out = tmp_path / "simulation.py"
    assert out.exists() and (tmp_path / "compose_meta.json").exists()
    assert (tmp_path / "netlist.yaml").exists()
    v = verify_compose_provenance(tmp_path)
    assert v["ok"], v
    assert v["result"]["checks"] == {"render_sha256": True,
                                     "netlist_sha256": True}


def test_service_yaml_entry_and_examples(tmp_path):
    """YAML 文件入口 + load_golden_netlist + 台账（opt-in 双模板）。"""
    import yaml

    p = tmp_path / "netlist.yaml"
    p.write_text(yaml.safe_dump(_chain(), allow_unicode=True),
                 encoding="utf-8")
    r = compose_from_yaml_file(p)
    assert r["ok"], r
    assert r["result"]["meta"]["render_sha256"] == _compose()[1][
        "render_sha256"]
    g = load_golden_netlist("siw_chain")
    assert g["ok"] and g["result"]["schema"] == "rfauto-netlist-v1"
    assert not load_golden_netlist("nope")["ok"]
    lst = list_composable_templates()
    assert lst["ok"] and lst["result"]["n_templates"] == 2
    assert {t["template"] for t in lst["result"]["templates"]} == {
        "siw", "msl_siw_taper"}
    assert all(t["schema_declared"] for t in lst["result"]["templates"])


def test_service_error_translation():
    """守卫失败 → ok=False + error 原文（不抛出；报双 pin id）。"""
    nl = _chain()
    nl["instances"][1]["template"] = "patch"
    r = compose_from_netlist(nl)
    assert r["ok"] is False and "未注册组合契约" in r["error"]
