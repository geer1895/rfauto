"""tri_view 三视图联动单测（aurora_q 席位 Q-X38）。

钉面：
- 1:1 映射（ref 为键）：三视图俱在=linked/one_to_one；缺面/重号/多出 ref 如实
  ERROR 断裂；值/引脚/网络不一致 WARN 不进 1:1；
- 同源：原理图位置=kicad_sch_gen 布局几何、网络=readback_nets 回读+证书 PASS；
  版图=kicad_edb_bridge 桥接焊盘；3D=叠层 z 账（physical/topological/声明铜厚）、
  外部体表（Q-X37 接口约定）、layered_stack 分层体（lint 投影逐体等价）；
- 交叉高亮：三面板 id 每 ref 恰一、data-ref 联动、同 ref 同色、lint 类三面同着；
- geometry_lint 标注：layered_stack 名义 2 WARN 端口→位号、焊盘重叠 ERROR 自查
  闭环、未解析对象如实列出、坏报告 error 信封；
- CLI 叶（测试局部父 Typer 挂 tri_view_app——零共享 app 污染、零金快照漂移）
  --json 信封/落盘/'-' 不落盘/错误信封/help 构建；合流契约静态钉。
零网络零真机零 KiCad 子进程（纯合成 extract_pcb 契约 dict）。
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from rfauto.adapters.kicad_sch_gen import (
    SchGridLayout,
    pin_world_pos,
    readback_nets,
    render_schematic,
    symbol_slot_xy,
)
from rfauto.adapters.layered_stack_spec import (
    LayeredStackSpec,
    layered_stack_layout,
    layered_stack_lint_projection,
)
from rfauto.service.geometry_lint_service import LintGeometry, lint_geometry
from rfauto.service.kicad_sch_service import spec_from_payload, spec_to_gen
from rfauto.service.tri_view_service import (
    BODIES_SCHEMA,
    EXPLODED_VIEW_SCHEMA,
    TRI_VIEW_SCHEMA,
    annotate_lint,
    build_tri_view,
    normalize_kicad_net,
    ref_sid,
    render_tri_view_svg,
    tri_view_link,
    tri_view_lint_projection,
)

SVG_NS = "{http://www.w3.org/2000/svg}"

#: RC 低通（kicad_sch 既有 fixture 同形；本文件内联，不依赖他席 fixture 文件）
SCH: dict[str, Any] = {
    "schema": "rfauto-sch-spec-v1",
    "components": [
        {"ref": "R1", "value": "10k", "lib_id": "Device:R"},
        {"ref": "R2", "value": "20k", "lib_id": "Device:R"},
        {"ref": "C1", "value": "100n", "lib_id": "Device:C",
         "footprint": "Capacitor_SMD:C_0402_1005Metric"},
    ],
    "nets": [
        {"name": "VIN", "pins": [{"ref": "R1", "pin": "1"}]},
        {"name": "MID", "pins": [{"ref": "R1", "pin": "2"}, {"ref": "R2", "pin": "1"},
                                 {"ref": "C1", "pin": "1"}]},
        {"name": "GND", "pins": [{"ref": "R2", "pin": "2"}, {"ref": "C1", "pin": "2"}]},
    ],
}

#: 单传输线（layered_stack 分层体联动用）
SCH_TL: dict[str, Any] = {
    "schema": "rfauto-sch-spec-v1",
    "components": [{"ref": "TL1", "value": "SSL50", "lib_id": "rfauto:SuspendedStripline"}],
    "nets": [{"name": "P1", "pins": [{"ref": "TL1", "pin": "1"}]},
             {"name": "P2", "pins": [{"ref": "TL1", "pin": "2"}]}],
}
TL_BIND = {"strip": "TL1", "Port1": "TL1", "Port2": "TL1"}


def _pad(num: str, net: str, x: float, y: float, w: float = 1.0, h: float = 1.2,
         layers: tuple[str, ...] = ("F.Cu",)) -> dict[str, Any]:
    return {"number": num, "net": net, "shape": 1, "x_mm": x, "y_mm": y,
            "w_mm": w, "h_mm": h, "layers": list(layers)}


def _board(diel_mm: float = 1.51) -> dict[str, Any]:
    return {"kicad_version": "10.0.6", "layer_count": 2, "copper_layers": ["F.Cu", "B.Cu"],
            "thickness_mm": 1.6, "substrate_er": 4.4, "substrate_note": "合成",
            "stackup": {"dielectrics": [{"name": "dielectric 1", "thickness_mm": diel_mm,
                                         "er": 4.4, "tan_d": 0.02}]}}


def _pcb() -> dict[str, Any]:
    """合成 extract_pcb 契约（KiCad 根图网名 "/X" 口径；footprints 序 C1,R1,R2）。"""
    return {
        "ok": True,
        "board": _board(),
        "traces": [{"net": "/MID", "layer": "F.Cu", "width_mm": 0.3, "length_mm": 8.0,
                    "points_mm": [[11.0, 10.0], [19.0, 10.0]]}],
        "vias": [{"net": "/GND", "x_mm": 22.0, "y_mm": 16.0,
                  "pad_diameter_mm": 0.6, "drill_mm": 0.3}],
        "outline": {"min_mm": [0.0, 0.0], "max_mm": [40.0, 25.0],
                    "width_mm": 40.0, "height_mm": 25.0},
        "zones": [],
        "footprints": [
            {"reference": "C1", "value": "100n", "x_mm": 25.0, "y_mm": 14.0,
             "pads": [_pad("1", "/MID", 24.5, 14.0, 0.6, 0.6), _pad("2", "/GND", 25.5, 14.0, 0.6, 0.6)]},
            {"reference": "R1", "value": "10k", "x_mm": 10.0, "y_mm": 10.0,
             "pads": [_pad("1", "/VIN", 9.0, 10.0), _pad("2", "/MID", 11.0, 10.0)]},
            {"reference": "R2", "value": "20k", "x_mm": 20.0, "y_mm": 10.0,
             "pads": [_pad("1", "/MID", 19.0, 10.0), _pad("2", "/GND", 21.0, 10.0)]},
        ],
    }


def _pcb_tl() -> dict[str, Any]:
    return {
        "ok": True, "board": _board(0.25), "traces": [], "vias": [],
        "outline": {"min_mm": [-3.0, -1.0], "max_mm": [3.0, 1.0], "width_mm": 6.0, "height_mm": 2.0},
        "zones": [],
        "footprints": [{"reference": "TL1", "value": "SSL50", "x_mm": 0.0, "y_mm": 0.0,
                        "pads": [_pad("1", "/P1", -2.4, 0.0, 0.3, 0.52),
                                 _pad("2", "/P2", 2.4, 0.0, 0.3, 0.52)]}],
    }


def _tl_payload() -> dict[str, Any]:
    return {"schema": BODIES_SCHEMA, "layered_stack": {}, "ref_bindings": dict(TL_BIND)}


def _by_id(root: ET.Element, ident: str) -> ET.Element:
    for el in root.iter():
        if el.get("id") == ident:
            return el
    raise AssertionError(f"SVG 缺 id={ident}")


def _cli() -> typer.Typer:
    """测试局部父 Typer 挂 tri_view_app（=合流后 rfauto tri-view 同构；不碰共享 app）。"""
    from rfauto.cli.domains.tri_view import tri_view_app

    parent = typer.Typer()
    parent.add_typer(tri_view_app, name="tri-view")
    return parent


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    sch_file, pcb_file = tmp_path / "rc.json", tmp_path / "rc_pcb.json"
    sch_file.write_text(json.dumps(SCH, ensure_ascii=False), encoding="utf-8")
    pcb_file.write_text(json.dumps(_pcb(), ensure_ascii=False), encoding="utf-8")
    return sch_file, pcb_file


# ── 1:1 映射 ────────────────────────────────────────────────────────────


def test_one_to_one_all_linked():
    tri = build_tri_view(SCH, _pcb())
    assert tri["ok"] is True
    assert tri["schema"] == TRI_VIEW_SCHEMA
    assert tri["one_to_one"] is True
    assert tri["refs"] == ["C1", "R1", "R2"]
    c = tri["counts"]
    assert (c["refs"], c["linked"], c["sch_symbols"], c["pcb_footprints"], c["ref_groups_3d"]) == (3, 3, 3, 3, 3)
    assert (c["issues_error"], c["issues_warn"], c["net_mismatch"]) == (0, 0, 0)
    for ref in tri["refs"]:
        m = tri["mapping"][ref]
        assert m["status"] == "linked"
        assert m["views_present"] == ["sch", "pcb", "3d"]
        assert m["missing"] == []
        assert m["svg_ids"] == {"sch": f"sch-{ref}", "pcb": f"pcb-{ref}", "3d": f"3d-{ref}"}
    assert tri["issues"] == []
    assert tri["warnings"] == []
    # JSON 进出：信封 JSON 往返逐键同形（tuple 已原生化）
    assert json.loads(json.dumps(tri, ensure_ascii=False)) == tri


def test_mapping_positions_three_views():
    tri = build_tri_view(SCH, _pcb())
    m = tri["mapping"]["R1"]
    assert m["pcb"]["bbox"] == pytest.approx([8.5, 9.4, 11.5, 10.6])
    assert m["pcb"]["position"] == [10.0, 10.0]
    assert (m["pcb"]["side"], m["pcb"]["layers"], m["pcb"]["count"]) == ("top", ["F.Cu"], 1)
    assert [p["name"] for p in m["pcb"]["pads"]] == ["R1-1", "R1-2"]
    assert m["3d"]["bodies"] == ["pad:R1-1@F.Cu", "pad:R1-2@F.Cu"]
    assert m["3d"]["bbox"] == pytest.approx([8.5, 9.4, 1.51, 11.5, 10.6, 1.51])
    sx0, sy0, sx1, sy1 = m["sch"]["bbox"]
    assert sx0 < sx1 and sy0 < sy1
    for px, py in m["sch"]["pins"].values():
        assert sx0 <= px <= sx1 and sy0 <= py <= sy1
    assert (m["sch"]["lib_id"], m["sch"]["value"]) == ("Device:R", "10k")
    assert tri["mapping"]["C1"]["sch"]["footprint"] == "Capacitor_SMD:C_0402_1005Metric"
    assert m["checks"] == {"value_match": True, "pins_without_pad": [], "pads_not_in_sch": []}


def test_missing_footprint_breaks_one_to_one():
    pcb = _pcb()
    pcb["footprints"] = [fp for fp in pcb["footprints"] if fp["reference"] != "C1"]
    tri = build_tri_view(SCH, pcb)
    assert tri["ok"] is True
    assert tri["one_to_one"] is False
    c1 = tri["mapping"]["C1"]
    assert c1["status"] == "partial"
    assert c1["views_present"] == ["sch"]
    assert c1["missing"] == ["pcb", "3d"]
    assert c1["pcb"] is None and c1["3d"] is None
    assert c1["svg_ids"] == {"sch": "sch-C1"}
    miss = [it for it in tri["issues"] if it["kind"] == "missing_in_view"]
    assert [(it["ref"], it["level"], it["views"]) for it in miss] == [("C1", "ERROR", ["pcb", "3d"])]
    assert tri["counts"]["linked"] == 2


def test_pcb_only_ref_and_duplicate_ref():
    pcb = _pcb()
    pcb["footprints"].append({"reference": "TP1", "value": "TP", "x_mm": 30.0, "y_mm": 20.0,
                              "pads": [_pad("1", "/GND", 30.0, 20.0)]})
    pcb["footprints"].append({"reference": "R1", "value": "10k", "x_mm": 5.0, "y_mm": 20.0,
                              "pads": [_pad("1", "/VIN", 4.0, 20.0), _pad("2", "/MID", 6.0, 20.0)]})
    tri = build_tri_view(SCH, pcb)
    assert tri["one_to_one"] is False
    tp = tri["mapping"]["TP1"]
    assert (tp["views_present"], tp["missing"], tp["sch"]) == (["pcb", "3d"], ["sch"], None)
    r1 = tri["mapping"]["R1"]
    assert r1["pcb"]["count"] == 2
    assert len(r1["pcb"]["pads"]) == 4  # 同位号焊盘按位号合并（桥接展平后不可区分，如实）
    dup = [it for it in tri["issues"] if it["kind"] == "duplicate_ref"]
    assert [(it["ref"], it["count"], it["level"]) for it in dup] == [("R1", 2, "ERROR")]
    assert tri["views"]["pcb"]["duplicate_refs"] == ["R1"]
    # 体名唯一化（重号焊盘 #2 后缀）——体名即 lint 对象名
    names = [b["name"] for b in tri["views"]["3d"]["bodies"]]
    assert len(names) == len(set(names))
    assert "pad:R1-1@F.Cu#2" in names


def test_value_and_pin_mismatch_warn_not_one_to_one():
    pcb = _pcb()
    pcb["footprints"][2]["value"] = "22k"                          # R2 值不一致
    pcb["footprints"][0]["pads"] = pcb["footprints"][0]["pads"][:1]  # C1 仅剩 1 号焊盘
    tri = build_tri_view(SCH, pcb)
    assert tri["one_to_one"] is True  # WARN 级不进 1:1 判定
    assert tri["mapping"]["R2"]["checks"]["value_match"] is False
    assert tri["mapping"]["C1"]["checks"]["pins_without_pad"] == ["2"]
    assert tri["mapping"]["C1"]["checks"]["value_match"] is True
    keyed = [(it["kind"], it.get("ref") or it.get("net"), it["level"]) for it in tri["issues"]]
    assert keyed == [("pin_without_pad", "C1", "WARN"), ("value_mismatch", "R2", "WARN"),
                     ("net_mismatch", "GND", "WARN")]


def test_bad_inputs_error_envelopes():
    bad_sch = build_tri_view({"components": [{"ref": "R1", "lib_id": "Device:R"}]}, _pcb())
    assert bad_sch["ok"] is False
    assert bad_sch["errors"][0].startswith("原理图面构建失败")
    bad_pcb = build_tri_view(SCH, {"ok": False, "errors": ["x"]})
    assert bad_pcb["ok"] is False
    assert bad_pcb["errors"] == ["版图桥接失败（kicad_edb_bridge.kicad_to_edb_spec）",
                                 "kicad_data 为失败契约（ok=False）", "x"]


# ── 同源：原理图面 ──────────────────────────────────────────────────────


def test_sch_positions_same_source_as_generator():
    tri = build_tri_view(SCH, _pcb())
    lay = SchGridLayout()
    syms = tri["views"]["sch"]["symbols"]
    for idx, ref in enumerate(["R1", "R2", "C1"]):  # SchSpec 元件序 = 生成器槽位序
        inst = symbol_slot_xy(idx, lay)
        assert syms[ref]["at"] == pytest.approx(list(inst), abs=1e-9)
        pins = list(syms[ref]["pins"])
        assert pins == ["1", "2"]
        for j, pin in enumerate(pins):
            assert syms[ref]["pins"][pin] == pytest.approx(list(pin_world_pos(j, 2, inst, lay)), abs=1e-6)


def test_sch_nets_from_readback_and_certificate():
    tri = build_tri_view(SCH, _pcb())
    sv = tri["views"]["sch"]
    assert sv["certificate_pass"] is True
    assert sv["certificate_diff"] == []
    assert sv["nets"] == {"GND": [["C1", "2"], ["R2", "2"]],
                          "MID": [["C1", "1"], ["R1", "2"], ["R2", "1"]],
                          "VIN": [["R1", "1"]]}
    text = render_schematic(*spec_to_gen(spec_from_payload(SCH)))
    rb = readback_nets(text)
    assert sv["nets"] == {k: [list(p) for p in v] for k, v in rb.nets.items()}
    assert sv["sch_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert all(w["net"] in {"VIN", "MID", "GND"} for w in sv["wires"])  # 每条 stub 落 label 网
    assert len(sv["wires"]) == len(sv["labels"]) == 6


# ── 网络交叉 ────────────────────────────────────────────────────────────


def test_normalize_kicad_net_root_sheet_rule():
    # 真机口径：kicad-cli 10.0.6 netlist 根图局部 label 实读 "/GND" "/MID" "/VIN"
    assert normalize_kicad_net("/MID") == "MID"
    assert normalize_kicad_net("GND") == "GND"
    assert normalize_kicad_net("/sub/X") == "/sub/X"  # 层次图不归一
    assert normalize_kicad_net("/") == "/"
    assert normalize_kicad_net("") == ""


def test_net_cross_highlight_match():
    tri = build_tri_view(SCH, _pcb())
    nets = tri["nets"]
    assert sorted(nets) == ["GND", "MID", "VIN"]
    mid = nets["MID"]
    assert mid["match"] is True
    assert mid["nid"] == "MID"
    assert mid["sch_pins"] == [["C1", "1"], ["R1", "2"], ["R2", "1"]]
    assert mid["pcb_pads"] == mid["sch_pins"]
    assert (mid["only_sch"], mid["only_pcb"]) == ([], [])
    assert len(mid["sch_points"]) == 6  # 3 引脚连接点 + 3 label 锚点
    assert len(mid["pcb_rects"]) == 3
    assert mid["bodies"] == ["pad:C1-1@F.Cu", "pad:R1-2@F.Cu", "pad:R2-1@F.Cu"]


def test_net_mismatch_warn():
    pcb = _pcb()
    pcb["footprints"][1]["pads"][1]["net"] = "/VIN"  # R1-2：MID→VIN
    tri = build_tri_view(SCH, pcb)
    assert tri["one_to_one"] is True
    mid, vin = tri["nets"]["MID"], tri["nets"]["VIN"]
    assert (mid["match"], mid["only_sch"], mid["only_pcb"]) == (False, [["R1", "2"]], [])
    assert (vin["match"], vin["only_sch"], vin["only_pcb"]) == (False, [], [["R1", "2"]])
    assert [(it["kind"], it["net"], it["level"]) for it in tri["issues"]] == [
        ("net_mismatch", "MID", "WARN"), ("net_mismatch", "VIN", "WARN")]
    assert tri["counts"]["net_mismatch"] == 2


# ── 3D 面 ──────────────────────────────────────────────────────────────


def test_3d_physical_stack_and_sheet_copper():
    tri = build_tri_view(SCH, _pcb())
    d3 = tri["views"]["3d"]
    assert (d3["source"], d3["z_mode"], d3["z_units"]) == ("pcb_stack", "physical", "mm")
    assert [(r["name"], r["type"], r["z_lo"], r["z_hi"], r["thickness_source"]) for r in d3["layers"]] == [
        ("B.Cu", "copper", 0.0, 0.0, "sheet_unresolved"),
        ("dielectric 1", "dielectric", 0.0, 1.51, "kicad_stackup"),
        ("F.Cu", "copper", 1.51, 1.51, "sheet_unresolved"),
    ]
    diel = d3["bodies"][0]
    assert diel["name"] == "diel:dielectric 1"
    assert diel["coords"] == [0.0, 0.0, 0.0, 40.0, 25.0, 1.51]  # 板框 × 介质 z
    assert (diel["ref"], diel["solve_inside"], diel["material"]) == (None, True, "dielectric")
    pads = [b for b in d3["bodies"] if b["name"].startswith("pad:")]
    assert len(pads) == 6
    assert all(b["coords"][2] == b["coords"][5] == 1.51 for b in pads)  # 铜厚契约未含 → 零厚 sheet
    assert all(b["is_metal"] is True and b["layer"] == "F.Cu" for b in pads)


def test_3d_declared_copper_thickness():
    tri = build_tri_view(SCH, _pcb(), copper_thickness_mm=0.035)
    layers = tri["views"]["3d"]["layers"]
    assert [r["thickness_source"] for r in layers] == ["declared", "kicad_stackup", "declared"]
    top = layers[2]
    assert top["z_lo"] == pytest.approx(0.035 + 1.51)
    assert top["z_hi"] == pytest.approx(2 * 0.035 + 1.51)
    r1 = [b for b in tri["views"]["3d"]["bodies"] if b["ref"] == "R1"]
    assert r1 and all(b["coords"][2] == top["z_lo"] and b["coords"][5] == top["z_hi"] for b in r1)
    bad = build_tri_view(SCH, _pcb(), copper_thickness_mm=-1.0)
    assert bad["ok"] is False and "copper_thickness_mm" in bad["errors"][0]


def test_3d_topological_when_dielectric_unresolved():
    pcb = _pcb()
    pcb["board"]["stackup"] = {"dielectrics": []}
    tri = build_tri_view(SCH, pcb, copper_thickness_mm=0.035)
    d3 = tri["views"]["3d"]
    assert (d3["z_mode"], d3["z_units"]) == ("topological", "layer_index")
    assert [(r["z_lo"], r["z_hi"]) for r in d3["layers"]] == [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
    assert any("topological" in w for w in tri["warnings"])
    assert any("copper_thickness_mm 不适用" in w for w in tri["warnings"])
    assert any(w.startswith("pcb: 介质层数目失配") for w in tri["warnings"])  # 桥接告警如实透传
    assert tri["one_to_one"] is True


def test_external_bodies_interface_contract():
    bodies = [
        {"name": "blk_R1", "material": "copper", "coords": [8, 9, 0, 12, 11, 0.1], "ref": "R1", "is_metal": True},
        {"name": "blk_R2", "material": "copper", "coords": [18, 9, 0, 22, 11, 0.1], "ref": "R2", "is_metal": True},
        {"name": "blk_C1", "material": "copper", "coords": [24, 13, 0, 26, 15, 0.1]},
        {"name": "sub", "material": "dielectric", "coords": [0, 0, -1, 40, 25, 0], "solve_inside": True},
    ]
    payload = {"schema": BODIES_SCHEMA, "bodies": bodies, "ref_bindings": {"blk_C1": "C1"}}
    tri = build_tri_view(SCH, _pcb(), bodies=payload)
    assert tri["ok"] is True and tri["one_to_one"] is True
    d3 = tri["views"]["3d"]
    assert (d3["source"], d3["z_mode"], d3["z_units"]) == ("external", "external", "mm")
    assert tri["mapping"]["C1"]["3d"]["bodies"] == ["blk_C1"]  # ref_bindings 绑定生效
    dup = build_tri_view(SCH, _pcb(), bodies=[bodies[0], bodies[0]])
    assert dup["ok"] is False and "体名重复" in dup["errors"][0]
    no_schema = build_tri_view(SCH, _pcb(), bodies={"bodies": bodies})
    assert no_schema["ok"] is False and "schema" in no_schema["errors"][0]
    bad_port = build_tri_view(SCH, _pcb(), bodies=[{"name": "p", "role": "port", "coords": [0, 0, 0, 1, 1, 1]}])
    assert bad_port["ok"] is False and "恰一轴零厚" in bad_port["errors"][0]
    unknown_bind = build_tri_view(SCH, _pcb(), bodies={**payload, "ref_bindings": {"ghost": "C1"}})
    assert unknown_bind["ok"] is False and "未知体名" in unknown_bind["errors"][0]


def test_exploded_view_scene_interface_contract():
    """Q-X37 exploded_view 场景（数据级接口约定，合成同形 dict——不依赖在制模块）→ 3D 面。"""
    scene = {
        "schema": EXPLODED_VIEW_SCHEMA, "source_kind": "layered_stack", "units": "mm",
        "solids": [
            {"name": "layer0_silicon", "layer_index": 0, "kind": "solid", "material": "silicon",
             "box_mm": [-2.55, -0.6, -0.303, 2.55, 0.6, -0.053], "offset_mm": 0.0},
            {"name": "layer1_gold", "layer_index": 1, "kind": "solid", "material": "gold",
             "box_mm": [-2.55, -0.6, -0.053, 2.55, 0.6, -0.05], "offset_mm": 0.375},
            {"name": "strip", "layer_index": 2, "kind": "sheet", "material": "pec",
             "box_mm": [-2.55, -0.26, 0.0, 2.55, 0.26, 0.0], "offset_mm": 0.75},
            {"name": "trace_0000", "layer_index": 2, "kind": "trace", "material": "copper", "net": "/P1",
             "box_mm": [-2.55, -0.1, 0.0, -2.0, 0.1, 0.0], "offset_mm": 0.75},
        ],
        "cavity": {"name": "cavity", "layer_index": 2, "box_mm": [-2.55, -0.45, -0.25, 2.55, 0.45, 0.25]},
    }
    payload = {"schema": BODIES_SCHEMA, "exploded_view": scene, "ref_bindings": {"strip": "TL1"}}
    tri = build_tri_view(SCH_TL, _pcb_tl(), bodies=payload)
    assert tri["ok"] is True and tri["one_to_one"] is True
    d3 = tri["views"]["3d"]
    assert (d3["source"], d3["z_mode"], d3["z_units"]) == ("exploded_view", "external", "mm")
    by = {b["name"]: b for b in d3["bodies"]}
    assert list(by) == ["layer0_silicon", "layer1_gold", "strip", "trace_0000"]  # cavity 挖除区不成体
    for s in scene["solids"]:  # box_mm 直取未爆炸一手坐标（offset_mm 只是显示偏移，不叠加）
        assert by[s["name"]]["coords"] == s["box_mm"]
    assert (by["layer0_silicon"]["is_metal"], by["layer0_silicon"]["solve_inside"]) == (False, True)
    assert (by["layer1_gold"]["is_metal"], by["layer1_gold"]["solve_inside"]) == (True, False)
    assert (by["strip"]["is_metal"], by["strip"]["ref"], by["strip"]["layer"]) == (True, "TL1", "layer2")
    assert tri["mapping"]["TL1"]["3d"]["bodies"] == ["strip"]
    assert tri["nets"]["P1"]["bodies"] == ["trace_0000"]  # 场景 net 经根图归一落网络联动
    drift = build_tri_view(SCH_TL, _pcb_tl(),
                           bodies={**payload, "exploded_view": {**scene, "schema": "exploded-view/v1"}})
    assert drift["ok"] is False and EXPLODED_VIEW_SCHEMA in drift["errors"][0]
    two = build_tri_view(SCH_TL, _pcb_tl(), bodies={**payload, "layered_stack": {}})
    assert two["ok"] is False and "恰含" in two["errors"][0]


def test_layered_stack_bodies_projection_identity():
    layout = layered_stack_layout(LayeredStackSpec())
    ref_proj = layered_stack_lint_projection(layout)
    tri = build_tri_view(SCH_TL, _pcb_tl(), bodies=_tl_payload())
    assert tri["ok"] is True and tri["one_to_one"] is True
    assert tri["views"]["3d"]["source"] == "layered_stack"
    names = [b["name"] for b in tri["views"]["3d"]["bodies"]]
    assert names == [b["name"] for b in ref_proj["boxes"]] + [p["name"] for p in ref_proj["ports"]]
    proj = tri_view_lint_projection(tri)
    assert LintGeometry.model_validate(proj) == LintGeometry.model_validate(ref_proj)
    assert lint_geometry(proj) == lint_geometry(ref_proj)
    tl = tri["mapping"]["TL1"]
    assert sorted(tl["3d"]["bodies"]) == ["Port1", "Port2", "strip"]


# ── geometry_lint 标注 ─────────────────────────────────────────────────


def test_lint_annotation_layered_stack_nominal_two_warns():
    tri = build_tri_view(SCH_TL, _pcb_tl(), bodies=_tl_payload())
    report = lint_geometry(layered_stack_lint_projection(layered_stack_layout(LayeredStackSpec())))
    assert report["lint_pass"] is True and report["counts"] == {"error": 0, "warn": 2}
    ann = annotate_lint(tri, report)
    assert ann["ok"] is True
    assert ann["counts"]["issues"] == 2
    assert (ann["counts"]["unresolved"], ann["unresolved_objects"]) == (0, [])
    assert ann["flagged_refs"] == {"TL1": "WARN"}
    assert [a["objects"][0]["name"] for a in ann["annotations"]] == ["Port1", "Port2"]
    tl = tri["mapping"]["TL1"]
    for a in ann["annotations"]:
        assert (a["check"], a["level"], a["refs"]) == ("port_cross_section_connectivity", "WARN", ["TL1"])
        head = a["objects"][0]
        assert (head["resolved_as"], head["ref"]) == ("port", "TL1")
        assert head["positions"]["sch"] == tl["sch"]["bbox"]
        assert head["positions"]["pcb"] == tl["pcb"]["bbox"]
        assert head["positions"]["3d"][0] == head["positions"]["3d"][3]  # 端口片 x 零厚
        ctx = [o for o in a["objects"][1:] if o["ref"] is None]
        assert ctx
        for o in ctx:  # 无 ref 上下文体：只有 3D 位置，sch/pcb 如实 None
            assert o["resolved_as"] == "body"
            assert o["positions"]["sch"] is None and o["positions"]["pcb"] is None
            assert o["positions"]["3d"] is not None
    assert ann["flagged_bodies"]["Port1"] == "WARN"


def test_self_lint_pad_overlap_end_to_end():
    pcb = _pcb()
    pcb["footprints"][2]["pads"] = [_pad("1", "/MID", 11.4, 10.0), _pad("2", "/GND", 13.4, 10.0)]
    tri = build_tri_view(SCH, pcb, copper_thickness_mm=0.035)
    report = lint_geometry(tri_view_lint_projection(tri))
    assert report["lint_pass"] is False and report["counts"] == {"error": 1, "warn": 0}
    issue = report["issues"][0]
    assert issue["check"] == "partial_intersection"
    assert sorted(issue["objects"]) == ["pad:R1-2@F.Cu", "pad:R2-1@F.Cu"]
    ann = annotate_lint(tri, report)
    assert ann["flagged_refs"] == {"R1": "ERROR", "R2": "ERROR"}
    objs = {o["name"]: o for o in ann["annotations"][0]["objects"]}
    r12 = objs["pad:R1-2@F.Cu"]
    assert (r12["resolved_as"], r12["ref"]) == ("body", "R1")
    assert r12["positions"]["sch"] == tri["mapping"]["R1"]["sch"]["bbox"]
    assert r12["positions"]["pcb"] == tri["mapping"]["R1"]["pcb"]["bbox"]
    body = next(b for b in tri["views"]["3d"]["bodies"] if b["name"] == "pad:R1-2@F.Cu")
    assert r12["positions"]["3d"] == body["coords"]
    root = ET.fromstring(render_tri_view_svg(tri, lint_annotation=ann))
    for ref in ("R1", "R2"):
        for panel in ("sch", "pcb", "3d"):
            assert "lint-error" in _by_id(root, f"{panel}-{ref}").get("class", "").split()
    for panel in ("sch", "pcb", "3d"):
        assert "lint-error" not in _by_id(root, f"{panel}-C1").get("class", "").split()
    # 缺省零厚铜：同重叠场景 lint ④ 不判 sheet 相交（lint 口径如实，docstring 已登记）
    tri0 = build_tri_view(SCH, pcb)
    assert lint_geometry(tri_view_lint_projection(tri0))["counts"] == {"error": 0, "warn": 0}


def test_lint_annotation_pad_ref_unresolved_and_bad_reports():
    tri = build_tri_view(SCH, _pcb())
    report = {"ok": True, "lint_pass": False, "issues": [
        {"check": "partial_intersection", "level": "ERROR", "objects": ["R1-2", "C1", "Ghost"], "message": "m"}]}
    ann = annotate_lint(tri, report)
    assert ann["ok"] is True
    objs = {o["name"]: o for o in ann["annotations"][0]["objects"]}
    r12 = objs["R1-2"]
    assert (r12["resolved_as"], r12["ref"], r12["pad"]) == ("pad", "R1", "2")
    pin = tri["mapping"]["R1"]["sch"]["pins"]["2"]
    assert r12["positions"]["sch"] == [pin[0], pin[1], pin[0], pin[1]]
    assert r12["positions"]["pcb"] == pytest.approx([10.5, 9.4, 11.5, 10.6])
    r12_body = next(b for b in tri["views"]["3d"]["bodies"] if b["name"] == "pad:R1-2@F.Cu")
    assert r12["positions"]["3d"] == r12_body["coords"]
    assert objs["C1"]["resolved_as"] == "ref"
    assert objs["C1"]["positions"]["3d"] == tri["mapping"]["C1"]["3d"]["bbox"]
    assert objs["Ghost"] == {"name": "Ghost", "resolved_as": None, "ref": None,
                             "positions": {"sch": None, "pcb": None, "3d": None}}
    assert ann["unresolved_objects"] == ["Ghost"]
    assert ann["counts"] == {"issues": 1, "objects": 3, "resolved": 2, "unresolved": 1, "flagged_refs": 2}
    assert ann["flagged_refs"] == {"C1": "ERROR", "R1": "ERROR"}
    assert annotate_lint(tri, {"nope": 1})["ok"] is False
    failed = annotate_lint(tri, {"ok": False, "errors": ["LintGeometry 校验失败: x"], "issues": []})
    assert failed["ok"] is False and "LintGeometry 校验失败: x" in failed["errors"]


# ── 交叉高亮 / SVG 三联 ─────────────────────────────────────────────────


def test_ref_sid_injective_and_safe():
    samples = ["R1", "R_1", "R__1", "R-1", "R)1", "R_29_1", "U1.A", "电阻1", "", "_"]
    sids = [ref_sid(s) for s in samples]
    assert len(set(sids)) == len(samples)
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", s) for s in sids)
    assert (ref_sid("R1"), ref_sid("R_1"), ref_sid("R)1"), ref_sid("")) == ("R1", "R__1", "R_29_1", "_")


def test_svg_triptych_ids_colors_and_linked_highlight():
    tri = build_tri_view(SCH, _pcb())
    svg = render_tri_view_svg(tri, highlight_refs=["R2"])
    root = ET.fromstring(svg)
    ids = [el.get("id") for el in root.iter() if el.get("id")]
    assert len(ids) == len(set(ids))  # id 全局唯一
    for panel in ("sch", "pcb", "3d"):
        pg = _by_id(root, f"panel-{panel}")
        for ref in tri["refs"]:
            assert ids.count(f"{panel}-{ref}") == 1  # 每面板每 ref 恰一锚元素
            assert sum(1 for el in pg.iter() if el.get("data-ref") == ref) >= 1
        assert "hl" in _by_id(root, f"{panel}-R2").get("class", "").split()
        assert "hl" not in _by_id(root, f"{panel}-R1").get("class", "").split()
    color = tri["mapping"]["R1"]["color"]
    sch_rect = next(_by_id(root, "sch-R1").iter(f"{SVG_NS}rect"))
    pcb_rects = list(_by_id(root, "pcb-R1").iter(f"{SVG_NS}rect"))
    bodies_3d = [el for el in _by_id(root, "panel-3d").iter(f"{SVG_NS}polygon") if el.get("data-ref") == "R1"]
    assert sch_rect.get("fill") == color
    assert len(pcb_rects) == 2 and all(r.get("fill") == color for r in pcb_rects)
    assert len(bodies_3d) == 2 and all(p.get("fill") == color for p in bodies_3d)
    nets = {el.get("data-net") for el in root.iter() if el.get("data-net")}
    assert {"MID", "GND", "VIN"} <= nets  # 网络联动键三面可达
    script = next(root.iter(f"{SVG_NS}script"))
    assert "data-ref" in (script.text or "") and "data-net" in (script.text or "")
    assert root.get("data-schema") == TRI_VIEW_SCHEMA


def test_link_outputs_deterministic_bytes(tmp_path):
    sch_file, pcb_file = _write_inputs(tmp_path)
    outs = []
    for sub in ("a", "b"):
        res = tri_view_link(sch_file, pcb_file, out_dir=tmp_path / sub, self_lint=True, copper_thickness_mm=0.035)
        assert res["ok"] is True
        svg_bytes = Path(res["svg_path"]).read_bytes()
        map_bytes = Path(res["map_path"]).read_bytes()
        assert res["svg_sha256"] == hashlib.sha256(svg_bytes).hexdigest()
        assert res["map_sha256"] == hashlib.sha256(map_bytes).hexdigest()
        outs.append((svg_bytes, map_bytes, res))
    assert outs[0][0] == outs[1][0]  # 同输入逐字节同
    assert outs[0][1] == outs[1][1]
    doc = json.loads(outs[0][1].decode("utf-8"))
    res = outs[0][2]
    assert doc["schema"] == TRI_VIEW_SCHEMA and doc["mapping"] == res["mapping"]
    assert doc["inputs"] == {"sch": "rc.json", "pcb": "rc_pcb.json", "bodies": None, "lint": "self"}
    assert doc["lint"]["report"]["lint_pass"] is True
    assert Path(res["svg_path"]).name == "rc.tri_view.svg"


# ── CLI 叶 ──────────────────────────────────────────────────────────────


def test_cli_link_json_writes_files(tmp_path):
    sch_file, pcb_file = _write_inputs(tmp_path)
    out = tmp_path / "out"
    runner = CliRunner()
    res = runner.invoke(_cli(), ["tri-view", "link", str(sch_file), str(pcb_file),
                                 "--out-dir", str(out), "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["ok"] is True and payload["one_to_one"] is True
    assert payload["counts"]["linked"] == 3
    svg_path, map_path = Path(payload["svg_path"]), Path(payload["map_path"])
    assert svg_path.is_file() and map_path.is_file()
    assert json.loads(map_path.read_text(encoding="utf-8"))["mapping"] == payload["mapping"]
    human = runner.invoke(_cli(), ["tri-view", "link", str(sch_file), str(pcb_file),
                                   "--out-dir", str(tmp_path / "out2")])
    assert human.exit_code == 0, human.output
    assert "三视图联动完成" in human.output and "one_to_one=True" in human.output


def test_cli_out_dash_and_error_envelopes(tmp_path):
    sch_file, pcb_file = _write_inputs(tmp_path)
    runner = CliRunner()
    res = runner.invoke(_cli(), ["tri-view", "link", str(sch_file), str(pcb_file), "--out-dir", "-", "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["svg_str"].startswith("<?xml") and payload["svg_path"] is None
    assert list(tmp_path.glob("*.tri_view.*")) == []  # '-' 不落盘
    bad_pcb = tmp_path / "bad_pcb.json"
    bad_pcb.write_text(json.dumps({"ok": False, "errors": ["PCB 文件不存在: x"]}), encoding="utf-8")
    res = runner.invoke(_cli(), ["tri-view", "link", str(sch_file), str(bad_pcb), "--json"])
    assert res.exit_code == 1
    fail = json.loads(res.output)
    assert fail["ok"] is False and fail["errors"][0].startswith("版图桥接失败")
    assert "hints" in fail  # _emit 失败信封 hints 键恒在
    res = runner.invoke(_cli(), ["tri-view", "link", str(sch_file), str(pcb_file),
                                 "--lint", "x.json", "--self-lint", "--json"])
    assert res.exit_code == 1 and "互斥" in json.loads(res.output)["errors"][0]
    res = runner.invoke(_cli(), ["tri-view", "link", str(tmp_path / "nope.json"), str(pcb_file), "--json"])
    assert res.exit_code == 1 and "不存在" in json.loads(res.output)["errors"][0]
    res = runner.invoke(_cli(), ["tri-view", "link", "--help"])
    assert res.exit_code == 0 and "--copper-thickness-mm" in res.output


def test_cli_domain_merge_contract_static():
    import rfauto.cli.domains.tri_view as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    # 合流契约：不在模块级（亦不在任何处）add_typer 到共享 app、不引共享 app
    assert not any(isinstance(n, ast.Attribute) and n.attr == "add_typer" for n in ast.walk(tree))
    core_names = {a.name for n in ast.walk(tree)
                  if isinstance(n, ast.ImportFrom) and n.module == "rfauto.cli.domains._core"
                  for a in n.names}
    assert "app" not in core_names and {"_emit", "console"} <= core_names
    assert '{"ok"' not in src  # 信封棘轮：零裸 dict 信封字面
    lines = src.splitlines()
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for sub in ast.walk(fn):
            if isinstance(sub, ast.ImportFrom) and (sub.module or "").startswith("rfauto"):
                assert "# lazy:" in lines[sub.lineno - 1]  # lazy 棘轮零增量
    group = typer.main.get_command(_cli()).commands["tri-view"]
    assert sorted(group.commands) == ["link"]
    leaf = group.commands["link"]
    texts = [leaf.help or ""] + [getattr(p, "help", None) or "" for p in leaf.params]
    assert all("[" not in t and "%" not in t for t in texts)  # help 卫生（#305/rich markup）
    assert any("--json" in getattr(p, "opts", ()) for p in leaf.params)
