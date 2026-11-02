"""T-O3 PCB 叠层横截面图 .drawio 生成器钉（aurora_o，2026-11-01）。

五验收钉（任务书口径）：
1. 6 层 S/G/S/P/G/S 样例 XML 合法 + 层带高度∝thickness——xml.etree 解析
   + mxfile>diagram>mxGraphModel>root 结构断言 + 官方清单（id 页内唯一/
   含 cell 0,1/vertex 全带 geometry、edge relative="1"/边两端 id 存在/
   无 compressed）+ T-O2 内核 read 面回读；层序=声明序自顶向下逐带堆叠、
   相邻带首尾相接、每带 height==thickness·PX_PER_MM（比例尺单源）；
2. 线宽标注数字单源——用户显式值原样标注（format_number 单源断言）+
   合成单源（service.synthesis_width_annotation → core/synthesis.
   nominal_width_mm 返回值逐位直通标注 dict 与 XML 文本，repr 同串）；
   信封逐条 source/synthesis provenance 回显；合成层叠 (εr,h) 与相邻介质
   不一致 warnings 守卫；
3. 负例显式——空层/缺 layers/kind 非法/负厚度/零厚度/非有限/多余键/缺
   必填/重名/er<1/线宽引用不存在层/线宽落介质层/width≤0/合成键未知；
4. 确定性——同输入两跑 XML/文件逐字节相同（id 形态总表逐位、零 uuid）；
5. 既有路径零改动——新件新叶独立：diagram 子应用既有三叶注册序不变、
   stackup 叶追加于末；内核模块零换算（grep 面）、core 不 import synthesis
   （单源在 service 层注入，core 零物理）。
另：信封+CLI 双路径（--json 信封+rich；usage 类 exit 2 / service 失败
exit 1；--stackup 与 --stackup-file 恰给一；--width-synth 单源通道）。
"""

from __future__ import annotations

import ast
import inspect
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rfauto.core.stackup_diagram as sdm
from rfauto.cli.main import app as root_app
from rfauto.core.drawio_xml import parse_diagram
from rfauto.core.stackup_diagram import (
    KIND_TABLE,
    LABEL_H,
    LABEL_VGAP,
    PX_PER_MM,
    STACK_W,
    STACK_X,
    STACK_Y0,
    build_stackup_diagram_xml,
    build_stackup_plan,
    format_number,
    normalize_stackup,
)
from rfauto.core.synthesis import nominal_width_mm
from rfauto.service.diagram_stackup_service import (
    SOURCE_INPUT,
    SOURCE_SYNTHESIS,
    generate_stackup_diagram,
    synthesis_width_annotation,
)

_SUB50 = "rogers4350b_h0.508"

# ─── 叠层 fixtures ──────────────────────────────────────────────────────────

#: 6 层板 S/G/S/P/G/S（6 铜层+5 介质层=11 带；自顶向下声明序）
STACK_6L = {
    "title": "6 层板 S/G/S/P/G/S",
    "layers": [
        {"name": "L1_TOP", "kind": "signal", "thickness_mm": 0.035,
         "material": "Cu"},
        {"name": "PP1", "kind": "dielectric", "thickness_mm": 0.2,
         "material": "FR4 PP", "er": 4.2},
        {"name": "L2_GND", "kind": "plane", "thickness_mm": 0.035,
         "material": "Cu"},
        {"name": "CORE1", "kind": "dielectric", "thickness_mm": 0.5,
         "material": "FR4 core", "er": 4.5},
        {"name": "L3_SIG", "kind": "signal", "thickness_mm": 0.035,
         "material": "Cu"},
        {"name": "PP2", "kind": "dielectric", "thickness_mm": 0.2,
         "material": "FR4 PP", "er": 4.2},
        {"name": "L4_PWR", "kind": "plane", "thickness_mm": 0.035,
         "material": "Cu"},
        {"name": "CORE2", "kind": "dielectric", "thickness_mm": 0.5,
         "material": "FR4 core", "er": 4.5},
        {"name": "L5_GND", "kind": "plane", "thickness_mm": 0.035,
         "material": "Cu"},
        {"name": "PP3", "kind": "dielectric", "thickness_mm": 0.2,
         "material": "FR4 PP", "er": 4.2},
        {"name": "L6_BOT", "kind": "signal", "thickness_mm": 0.035,
         "material": "Cu"},
    ],
    "width_annotations": [
        {"layer": "L1_TOP", "width_mm": 0.36, "note": "50 ohm microstrip"},
        {"layer": "L3_SIG", "width_mm": 0.15},
    ],
}

#: 微带三带（介质=rogers4350b_h0.508 同参：εr 3.66 / h 0.508——合成一致例）
STACK_MS = {
    "title": "微带 50Ω（RO4350B 0.508mm）",
    "layers": [
        {"name": "TOP", "kind": "signal", "thickness_mm": 0.035,
         "material": "Cu"},
        {"name": "SUB", "kind": "dielectric", "thickness_mm": 0.508,
         "material": "RO4350B", "er": 3.66},
        {"name": "GND", "kind": "plane", "thickness_mm": 0.035,
         "material": "Cu"},
    ],
}

_SYNTH_SPEC = {"layer": "TOP", "z0_ohm": 50, "freq_ghz": 2.5,
               "stackup_name": _SUB50}


def _copy(obj):
    return json.loads(json.dumps(obj))


# ─── 解析 helpers ───────────────────────────────────────────────────────────


def _parse(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text)  # 结构非法即抛 ParseError=红


def _cells(root: ET.Element) -> dict[str, ET.Element]:
    return {c.get("id"): c for c in root.findall(".//mxGraphModel/root/mxCell")}


def _geom(cell: ET.Element) -> tuple[float, float, float, float]:
    g = cell.find("mxGeometry")
    assert g is not None, f"cell {cell.get('id')!r} 缺 mxGeometry"
    return (float(g.get("x")), float(g.get("y")),
            float(g.get("width")), float(g.get("height")))


def _bands(root: ET.Element, n: int) -> list[tuple[float, float, float, float]]:
    cells = _cells(root)
    return [_geom(cells[f"layer{i}"]) for i in range(n)]


def _envelope(result) -> dict:
    out = result.output
    assert out.strip(), f"空输出（exit={result.exit_code}）"
    payload, _ = json.JSONDecoder().raw_decode(out[out.index("{"):])
    return payload


def _invoke(args: list[str]):
    return CliRunner().invoke(root_app, args)


# ─── 验收①：6 层 S/G/S/P/G/S XML 合法 + 层带高度∝thickness ──────────────────


def test_xml_structure_valid_official_checklist():
    xml = build_stackup_diagram_xml(STACK_6L)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
    root = _parse(xml)
    assert root.tag == "mxfile"
    diagrams = root.findall("diagram")
    assert len(diagrams) == 1
    assert "compressed" not in root.attrib
    model = diagrams[0].find("mxGraphModel")
    assert model is not None
    mx_root = model.find("root")
    assert mx_root is not None
    cells = mx_root.findall("mxCell")
    ids = [c.get("id") for c in cells]
    assert len(ids) == len(set(ids)), "cell id 页内不唯一"
    assert ids[0] == "0" and ids[1] == "1"
    assert cells[1].get("parent") == "0"
    id_set = set(ids)
    for c in cells:
        if c.get("vertex") == "1":
            g = c.find("mxGeometry")
            assert g is not None and g.get("as") == "geometry"
            for k in ("x", "y", "width", "height"):
                assert g.get(k) is not None, (c.get("id"), k)
        if c.get("edge") == "1":
            g = c.find("mxGeometry")
            assert g is not None and g.get("relative") == "1"
            assert c.get("source") in id_set and c.get("target") in id_set
    # T-O2 内核 read 面可回读（未压缩 mxfile 形态）
    view = parse_diagram(xml)
    assert view["n_pages"] == 1
    page = view["pages"][0]
    assert page["diagram_id"] == "stackup-diagram"
    # 11 带 + 11 标注 + 标题 + 2 线宽×2 锚点 = 27 vertex；
    # 2 线宽 edge + 11 引线 edge = 13 edge
    assert len(page["vertices"]) == 11 + 11 + 1 + 4
    assert len(page["edges"]) == 2 + 11


def test_six_layer_band_order_and_contiguity():
    root = _parse(build_stackup_diagram_xml(STACK_6L))
    bands = _bands(root, 11)
    assert bands[0][1] == STACK_Y0
    for i, (x, y, w, _h) in enumerate(bands):
        assert x == STACK_X and w == STACK_W, i
        if i:
            _px, py, _pw, ph = bands[i - 1]
            assert y > py, f"层序非自顶向下：带 {i}"
            assert math.isclose(py + ph, y, abs_tol=1e-6), f"带 {i} 与上带不相接"


def test_six_layer_band_height_proportional_to_thickness():
    root = _parse(build_stackup_diagram_xml(STACK_6L))
    bands = _bands(root, 11)
    ths = [lay["thickness_mm"] for lay in STACK_6L["layers"]]
    for i, ((_, _, _, h), th) in enumerate(zip(bands, ths, strict=True)):
        assert math.isclose(h, th * PX_PER_MM, abs_tol=1e-6), (i, h, th)
    ratios = [h / th for (_, _, _, h), th in zip(bands, ths, strict=True)]
    for r in ratios:
        assert math.isclose(r, ratios[0], rel_tol=1e-9)
    # 两两比值逐对（core 0.5 / pp 0.2 = 2.5；铜箔六层等高）
    assert math.isclose(bands[3][3] / bands[1][3], 0.5 / 0.2, rel_tol=1e-9)
    copper = {bands[i][3] for i in (0, 2, 4, 6, 8, 10)}
    assert len(copper) == 1


def test_custom_px_per_mm_scales_heights_not_labels():
    half = PX_PER_MM / 2
    plan_a = build_stackup_plan(STACK_6L)
    plan_b = build_stackup_plan(STACK_6L, px_per_mm=half)
    for la, lb in zip(plan_a["layers"], plan_b["layers"], strict=True):
        assert math.isclose(lb["height_px"], la["height_px"] / 2, abs_tol=1e-6)
        assert lb["zmin_mm"] == la["zmin_mm"]  # 标注量与比例尺无关
    ca = _cells(_parse(plan_a["xml"]))
    cb = _cells(_parse(plan_b["xml"]))
    assert ca["layer1.label"].get("value") == cb["layer1.label"].get("value")
    # 缺省标题含实际比例尺（标题与几何同源不撒谎）
    no_title = {k: v for k, v in STACK_6L.items() if k != "title"}
    tb = _cells(_parse(build_stackup_diagram_xml(no_title, px_per_mm=half)))
    assert f"比例尺 {format_number(half)}px/mm" in tb["title"].get("value")
    ta = _cells(_parse(build_stackup_diagram_xml(no_title)))
    assert f"比例尺 {format_number(PX_PER_MM)}px/mm" in ta["title"].get("value")
    assert PX_PER_MM == 200.0  # 缺省比例尺钉（1oz 铜 7px 过可见阈值）


def test_kind_colors_single_source():
    cells = _cells(_parse(build_stackup_diagram_xml(STACK_6L)))
    assert set(KIND_TABLE) == {"signal", "plane", "dielectric"}
    for i, lay in enumerate(STACK_6L["layers"]):
        fill, stroke = KIND_TABLE[lay["kind"]]
        style = cells[f"layer{i}"].get("style")
        assert f"fillColor={fill};" in style
        assert f"strokeColor={stroke};" in style


def test_layer_label_text_material_thickness_er_zmin():
    plan = build_stackup_plan(STACK_6L)
    cells = _cells(_parse(plan["xml"]))
    assert cells["layer0.label"].get("value") == (
        "L1_TOP（signal）\nCu  0.035 mm\nz=0 mm")
    assert cells["layer1.label"].get("value") == (
        "PP1（dielectric）\nFR4 PP  0.2 mm  εr 4.2\nz=0.035 mm")
    assert cells["layer3.label"].get("value") == (
        "CORE1（dielectric）\nFR4 core  0.5 mm  εr 4.5\nz=0.27 mm")
    # zmin=自顶累计（确定性加法，round 6 位）——回显与图文同源
    acc = 0.0
    for i, lay in enumerate(STACK_6L["layers"]):
        echo = plan["layers"][i]
        assert echo["zmin_mm"] == round(acc, 6)
        assert f"z={format_number(echo['zmin_mm'])} mm" in (
            cells[f"layer{i}.label"].get("value"))
        acc += lay["thickness_mm"]
    assert plan["layers"][10]["zmin_mm"] == 1.775


def test_label_column_greedy_non_overlap_with_leaders():
    cells = _cells(_parse(build_stackup_diagram_xml(STACK_6L)))
    prev_bottom = None
    for i in range(11):
        _, by, _, bh = _geom(cells[f"layer{i}"])
        lx, ly, _, lh = _geom(cells[f"layer{i}.label"])
        assert lx > STACK_X + STACK_W, "标注须在层带右侧"
        ideal = by + bh / 2 - lh / 2
        assert ly >= ideal - 1e-6, f"标注 {i} 被上移（只许下移）"
        if prev_bottom is None:
            assert math.isclose(ly, ideal, abs_tol=1e-6)  # 首卡在理想位
        else:
            assert ly >= prev_bottom + LABEL_VGAP - 1e-6, f"标注 {i} 与上卡互叠"
        prev_bottom = ly + lh
        leader = cells[f"layer{i}.leader"]
        assert leader.get("edge") == "1"
        assert leader.get("source") == f"layer{i}.label"
        assert leader.get("target") == f"layer{i}"
        assert "endArrow=none" in leader.get("style")
    # 6 层样例薄铜带密集：至少一张卡确实被下移（贪心生效，非空转）
    shifted = [i for i in range(11)
               if _geom(cells[f"layer{i}.label"])[1] > (
                   _geom(cells[f"layer{i}"])[1] + _geom(cells[f"layer{i}"])[3] / 2
                   - LABEL_H / 2 + 1e-6)]
    assert shifted


def test_label_centered_on_band_when_room():
    # 厚层叠（每带 100px ≫ 卡高 42+4）：无互叠 → 全部居中于带（不下移）
    thick = {"layers": [
        {"name": f"D{i}", "kind": "dielectric", "thickness_mm": 1.0}
        for i in range(4)]}
    cells = _cells(_parse(build_stackup_diagram_xml(thick)))
    for i in range(4):
        _, by, _, bh = _geom(cells[f"layer{i}"])
        _, ly, _, lh = _geom(cells[f"layer{i}.label"])
        assert math.isclose(ly + lh / 2, by + bh / 2, abs_tol=1e-6), i


# ─── 验收②：线宽标注数字单源 ─────────────────────────────────────────────────


def test_width_annotation_user_value_verbatim():
    cells = _cells(_parse(build_stackup_diagram_xml(STACK_6L)))
    assert format_number(0.36) == "0.36"
    assert cells["w0"].get("value") == "0.36 mm  50 ohm microstrip"
    assert cells["w1"].get("value") == "0.15 mm"  # 无 note 只标数值
    assert cells["w0"].get("source") == "w0.a"
    assert cells["w0"].get("target") == "w0.b"
    # 标签白底+法向上移（mxGeometry 子 mxPoint as="offset"，y=-12）
    assert "labelBackgroundColor=#ffffff;" in cells["w0"].get("style")
    offset = cells["w0"].find("mxGeometry/mxPoint")
    assert offset is not None
    assert offset.attrib == {"x": "0", "y": "-12", "as": "offset"}


def test_format_number_tiers_and_type_negatives():
    assert format_number(1.0) == "1"
    assert format_number(20) == "20"
    assert format_number(0.5) == "0.5"
    assert format_number(1.1134) == "1.1134"
    for bad in ("0.5", True, None, [0.5]):
        with pytest.raises(ValueError):
            format_number(bad)
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            format_number(bad)


def test_width_synthesis_single_source_bitwise():
    expected = nominal_width_mm(50.0, 2.5, _SUB50)
    # synthesis docstring 钉住的标称档（XC-W 权威源，test_width_single_source 同锚）
    assert expected == 1.1134
    ann = synthesis_width_annotation("TOP", 50, 2.5, _SUB50)
    assert ann["width_mm"] == expected
    assert repr(ann["width_mm"]) == repr(expected)
    stack = _copy(STACK_MS)
    stack["width_annotations"] = [ann]
    xml = build_stackup_diagram_xml(stack)
    value = _cells(_parse(xml))["w0"].get("value")
    assert value.startswith(f"{format_number(expected)} mm")
    # XML 文本回读的数字与合成内核返回值逐位相等（图内数字=内核数值）
    assert float(value.split(" mm")[0]) == expected
    assert value.split(" mm")[0] == repr(expected)


def test_width_synthesis_service_envelope_provenance(tmp_path):
    stack = _copy(STACK_MS)
    stack["width_annotations"] = [{"layer": "TOP", "width_mm": 1.2,
                                   "note": "user"}]
    out = tmp_path / "ms.drawio"
    r = generate_stackup_diagram(stack, out, width_synthesis=_SYNTH_SPEC)
    assert r["ok"] is True, r
    assert r["n_width_annotations"] == 2
    user, synth = r["width_annotations"]
    assert user["source"] == SOURCE_INPUT == "input"
    assert user["width_mm"] == 1.2
    assert "synthesis" not in user
    assert synth["source"] == SOURCE_SYNTHESIS == "synthesis.nominal_width_mm"
    assert synth["width_mm"] == nominal_width_mm(50.0, 2.5, _SUB50)
    assert synth["note"] == "50Ω@2.5GHz nominal_width_mm(rogers4350b_h0.508)"
    assert synth["synthesis"] == {"z0_ohm": 50, "freq_ghz": 2.5,
                                  "stackup_name": _SUB50, "digits": 4}
    text = out.read_text(encoding="utf-8")
    assert "1.1134 mm  50Ω@2.5GHz nominal_width_mm(rogers4350b_h0.508)" in text
    # 合成层叠与相邻介质（SUB εr 3.66/h 0.508）一致 → 无不一致告警
    assert not [w for w in r["warnings"] if "合成层叠" in w]


def test_width_synthesis_mismatch_warning(tmp_path):
    stack = _copy(STACK_MS)
    stack["layers"][1] = {"name": "SUB", "kind": "dielectric",
                          "thickness_mm": 0.2, "material": "FR4", "er": 4.2}
    r = generate_stackup_diagram(stack, tmp_path / "m.drawio",
                                 width_synthesis=[_SYNTH_SPEC])
    assert r["ok"] is True
    hits = [w for w in r["warnings"] if "合成层叠" in w]
    assert hits == [
        "线宽标注 0（层 'TOP'）合成层叠 'rogers4350b_h0.508'（εr=3.66, "
        "h=0.508 mm）与相邻介质层声明不一致或相邻介质缺 εr——线宽数字仍为 "
        "nominal_width_mm 单源原值，请核对叠层声明与合成层叠键是否对应"]
    # 数字不因告警改变（宁可多报，不改数）
    assert r["width_annotations"][0]["width_mm"] == 1.1134
    # 相邻介质缺 εr 同样提示（无法核对=如实告警）
    stack["layers"][1] = {"name": "SUB", "kind": "dielectric",
                          "thickness_mm": 0.508}
    r = generate_stackup_diagram(stack, tmp_path / "m2.drawio",
                                 width_synthesis=_SYNTH_SPEC)
    assert [w for w in r["warnings"] if "合成层叠" in w]


def test_width_arrow_geometry_equals_width_times_scale():
    cells = _cells(_parse(build_stackup_diagram_xml(STACK_6L)))
    for i, ann in enumerate(STACK_6L["width_annotations"]):
        ax, ay, aw, ah = _geom(cells[f"w{i}.a"])
        bx, by, bw, bh = _geom(cells[f"w{i}.b"])
        length = (bx + bw / 2) - (ax + aw / 2)
        assert math.isclose(length, ann["width_mm"] * PX_PER_MM, abs_tol=1e-6)
        assert math.isclose(ax + aw / 2, STACK_X, abs_tol=1e-6)
        idx = next(k for k, lay in enumerate(STACK_6L["layers"])
                   if lay["name"] == ann["layer"])
        _, band_y, _, band_h = _geom(cells[f"layer{idx}"])
        assert math.isclose(ay + ah / 2, band_y + band_h / 2, abs_tol=1e-6)
        assert math.isclose(by + bh / 2, band_y + band_h / 2, abs_tol=1e-6)
        assert "strokeColor=none" in cells[f"w{i}.a"].get("style")  # 不可见锚


def test_width_synthesis_negatives(tmp_path):
    with pytest.raises(ValueError, match="合成层叠键未知"):
        synthesis_width_annotation("TOP", 50, 2.5, "no_such_stackup")
    for bad in (0, -50, float("nan"), True, "50"):
        with pytest.raises(ValueError):
            synthesis_width_annotation("TOP", bad, 2.5, _SUB50)
        with pytest.raises(ValueError):
            synthesis_width_annotation("TOP", 50, bad, _SUB50)
    with pytest.raises(ValueError):
        synthesis_width_annotation("", 50, 2.5, _SUB50)
    with pytest.raises(ValueError):
        synthesis_width_annotation("TOP", 50, 2.5, "")
    with pytest.raises(ValueError):
        synthesis_width_annotation("TOP", 50, 2.5, _SUB50, digits=-1)
    with pytest.raises(ValueError):
        synthesis_width_annotation("TOP", 50, 2.5, _SUB50, note=3)
    out = tmp_path / "neg.drawio"
    cases = [
        ({**_SYNTH_SPEC, "stackup_name": "no_such_stackup"}, "合成层叠键未知"),
        ({**_SYNTH_SPEC, "bogus": 1}, "未支持键"),
        ({k: v for k, v in _SYNTH_SPEC.items() if k != "z0_ohm"}, "缺必填键"),
        ("TOP", "dict 或 dict 列表"),
        ([1], "必须是 dict"),
        ({**_SYNTH_SPEC, "layer": "SUB"}, "介质层"),
        ({**_SYNTH_SPEC, "layer": "GHOST"}, "引用不存在层名"),
    ]
    for spec, needle in cases:
        r = generate_stackup_diagram(_copy(STACK_MS), out, width_synthesis=spec)
        assert r["ok"] is False, spec
        assert needle in r["errors"][0], (spec, r["errors"])
    assert not out.exists()


def test_core_module_zero_conversion_and_no_synthesis_import():
    src = inspect.getsource(sdm)
    for banned in ("log10", "math.log", "math.exp", "math.pow", "10 **",
                   "10**", "pow(", "math.sin", "math.cos", "math.tan"):
        assert banned not in src, f"装配模块出现换算逻辑 {banned!r}（铁律 7）"
    # core 零物理：合成单源只在 service 层注入，core 不 import synthesis
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert imported == {"__future__", "math", "typing", "xml.etree.ElementTree",
                        "rfauto.core.drawio_xml"}, imported


# ─── 验收③：负例显式 ─────────────────────────────────────────────────────────


def test_negative_empty_or_missing_layers():
    for bad in ({"layers": []}, {}, {"layers": None}, {"layers": "L1"}):
        with pytest.raises(ValueError, match="非空层卡列表"):
            normalize_stackup(bad)


def test_negative_unknown_kind():
    stack = _copy(STACK_MS)
    stack["layers"][0]["kind"] = "copper"
    with pytest.raises(ValueError, match="kind 未知"):
        normalize_stackup(stack)


@pytest.mark.parametrize("bad", [-0.1, 0, 0.0, float("nan"), float("inf"),
                                 "0.1", True, None])
def test_negative_thickness(bad):
    stack = _copy(STACK_MS)
    stack["layers"][1]["thickness_mm"] = bad
    with pytest.raises(ValueError, match="thickness_mm"):
        normalize_stackup(stack)


def test_negative_extra_and_missing_keys():
    with pytest.raises(ValueError, match="未支持键"):
        normalize_stackup({**_copy(STACK_MS), "unit": "mil"})
    stack = _copy(STACK_MS)
    stack["layers"][0]["color"] = "red"
    with pytest.raises(ValueError, match="未支持键"):
        normalize_stackup(stack)
    for key in ("name", "kind", "thickness_mm"):
        stack = _copy(STACK_MS)
        del stack["layers"][0][key]
        with pytest.raises(ValueError, match="缺必填键"):
            normalize_stackup(stack)


def test_negative_names_er_material():
    stack = _copy(STACK_MS)
    stack["layers"][2]["name"] = "TOP"
    with pytest.raises(ValueError, match="层名重名"):
        normalize_stackup(stack)
    stack = _copy(STACK_MS)
    stack["layers"][0]["name"] = "  "
    with pytest.raises(ValueError, match="非空字符串"):
        normalize_stackup(stack)
    for bad_er in (0.5, -3.0, float("nan"), True, "3.66"):
        stack = _copy(STACK_MS)
        stack["layers"][1]["er"] = bad_er
        with pytest.raises(ValueError, match="er"):
            normalize_stackup(stack)
    stack = _copy(STACK_MS)
    stack["layers"][1]["er"] = 1.0  # 真空下界合法
    assert normalize_stackup(stack)["layers"][1]["er"] == 1.0
    stack = _copy(STACK_MS)
    stack["layers"][1]["material"] = 4350
    with pytest.raises(ValueError, match="material"):
        normalize_stackup(stack)


def test_negative_width_annotation_references():
    base = _copy(STACK_MS)
    cases = [
        ({"layer": "GHOST", "width_mm": 1.0}, "引用不存在层名"),
        ({"layer": "SUB", "width_mm": 1.0}, "介质层"),
        ({"layer": "TOP", "width_mm": 0}, "width_mm"),
        ({"layer": "TOP", "width_mm": -1.0}, "width_mm"),
        ({"layer": "TOP", "width_mm": float("nan")}, "width_mm"),
        ({"layer": "TOP", "width_mm": "1.1"}, "width_mm"),
        ({"layer": "TOP"}, "缺必填键"),
        ({"layer": "TOP", "width_mm": 1.0, "unit": "mm"}, "未支持键"),
        ({"layer": "TOP", "width_mm": 1.0, "note": 7}, "note"),
        ("TOP", "必须是 dict"),
    ]
    for ann, needle in cases:
        stack = _copy(base)
        stack["width_annotations"] = [ann]
        with pytest.raises(ValueError, match=needle):
            normalize_stackup(stack)
    stack = _copy(base)
    stack["width_annotations"] = {"layer": "TOP", "width_mm": 1.0}
    with pytest.raises(ValueError, match="必须是列表"):
        normalize_stackup(stack)


def test_negative_not_dict_and_bad_scale():
    for bad in (None, [], "stack", 3):
        with pytest.raises(ValueError, match="必须是 dict"):
            normalize_stackup(bad)
    for bad in (0, -1.0, float("nan"), True):
        with pytest.raises(ValueError, match="px_per_mm"):
            build_stackup_plan(STACK_MS, px_per_mm=bad)


def test_service_error_envelope_and_missing_parent_dir(tmp_path):
    bad = _copy(STACK_MS)
    bad["layers"][1]["thickness_mm"] = -0.5
    out = tmp_path / "neg.drawio"
    r = generate_stackup_diagram(bad, out)
    assert r["ok"] is False
    assert isinstance(r["errors"], list) and len(r["errors"]) == 1
    assert r["errors"][0].startswith("ValueError: ")
    assert not out.exists()
    r = generate_stackup_diagram(_copy(STACK_MS),
                                 tmp_path / "missing_dir" / "x.drawio")
    assert r["ok"] is False
    assert "输出目录不存在" in r["errors"][0]
    r = generate_stackup_diagram([], tmp_path / "x.drawio")
    assert r["ok"] is False


# ─── 验收④：确定性 ───────────────────────────────────────────────────────────


def test_determinism_two_runs_byte_identical(tmp_path):
    assert build_stackup_diagram_xml(STACK_6L) == build_stackup_diagram_xml(
        _copy(STACK_6L))
    a, b = tmp_path / "a.drawio", tmp_path / "b.drawio"
    ra = generate_stackup_diagram(_copy(STACK_MS), a,
                                  width_synthesis=_SYNTH_SPEC)
    rb = generate_stackup_diagram(_copy(STACK_MS), b,
                                  width_synthesis=_SYNTH_SPEC)
    assert ra["ok"] and rb["ok"]
    assert a.read_bytes() == b.read_bytes()
    assert {k: v for k, v in ra.items() if k != "out_path"} == {
        k: v for k, v in rb.items() if k != "out_path"}


def test_id_shape_table_no_uuid():
    cells = _cells(_parse(build_stackup_diagram_xml(STACK_6L)))
    expected = {"0", "1", "title"}
    expected |= {f"layer{i}" for i in range(11)}
    expected |= {f"layer{i}.label" for i in range(11)}
    expected |= {f"layer{i}.leader" for i in range(11)}
    expected |= {"w0", "w0.a", "w0.b", "w1", "w1.a", "w1.b"}
    assert set(cells) == expected
    uuidish = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}")
    assert not any(uuidish.search(i) for i in cells)


def test_geometry_text_clean_no_repr_tail():
    xml = build_stackup_diagram_xml(STACK_6L)
    for m in re.finditer(r'(?:x|y|width|height)="([^"]+)"', xml):
        text = m.group(1)
        assert not text.endswith(".0"), text  # 整值不带 .0
        assert len(text.split(".")[-1]) <= 6 or "." not in text, text


# ─── 验收⑤：既有路径零改动（新叶独立追加） ──────────────────────────────────


def test_diagram_subapp_existing_leaves_order_unchanged():
    import typer.main

    group = typer.main.get_command(root_app)
    diagram = group.commands["diagram"]
    # aurora_p C3 2026-11-01 +1 重钉：diagram to-svg（.drawio→SVG 纯
    # Python 渲染，独立追加于栈尾——既有五叶注册序与产出零改动）
    assert list(diagram.commands) == ["link", "testsetup", "annotate",
                                      "stackup", "schematic", "to-svg"]


# ─── warnings / 页面 / 标题 / 转义 ──────────────────────────────────────────


def test_warnings_inventory_classes():
    # 缺省比例尺下 1oz 铜（35µm→7px）不触发薄带提示（比例尺选型钉）
    assert not [w for w in build_stackup_plan(STACK_6L)["warnings"]
                if "可见阈值" in w]
    # 显式 100px/mm：35µm→3.5px < 6px，六铜层逐条提示
    plan = build_stackup_plan(STACK_6L, px_per_mm=100.0)
    thin = [w for w in plan["warnings"] if "可见阈值" in w]
    assert len(thin) == 6
    assert thin[0] == ("层 'L1_TOP' 带高 3.5px（<6px 可见阈值；高度仍∝厚度"
                       "不失真，draw.io 需放大查看）")
    copper_only = {"layers": [{"name": "C", "kind": "plane",
                               "thickness_mm": 0.1}]}
    ws = build_stackup_plan(copper_only)["warnings"]
    assert "无介质层（纯导体声明；横截面仍按输入渲染）" in ws
    diel_only = {"layers": [{"name": "D", "kind": "dielectric",
                             "thickness_mm": 0.5, "er": 4.0}]}
    ws = build_stackup_plan(diel_only)["warnings"]
    assert "无导体层（signal/plane 全无；纯介质堆叠）" in ws
    wide = _copy(STACK_MS)
    wide["width_annotations"] = [{"layer": "TOP", "width_mm": 5.0}]
    ws = build_stackup_plan(wide)["warnings"]
    arrow = format_number(5.0 * PX_PER_MM)
    assert any(f"箭头长 {arrow}px 超出层带宽 {STACK_W}px" in w for w in ws)
    assert not build_stackup_plan(STACK_MS)["warnings"]  # 1oz 微带零提示


def test_page_size_adapts_to_content():
    tall = {"layers": [{"name": "D", "kind": "dielectric",
                        "thickness_mm": 10.0}]}
    page = _parse(build_stackup_diagram_xml(tall)).find(".//mxGraphModel")
    # 底=STACK_Y0+10mm×比例尺 → +40 页底边距
    assert page.get("pageHeight") == str(
        math.ceil(STACK_Y0 + 10.0 * PX_PER_MM + 40))
    assert page.get("pageWidth") == "1169"
    wide = _copy(STACK_MS)
    wide["width_annotations"] = [{"layer": "TOP", "width_mm": 20.0}]
    page = _parse(build_stackup_diagram_xml(wide)).find(".//mxGraphModel")
    # 箭头右端 STACK_X+20mm×比例尺+2 锚 → +40 边距
    assert page.get("pageWidth") == str(
        math.ceil(STACK_X + 20.0 * PX_PER_MM + 2 + 40))
    small = _parse(build_stackup_diagram_xml(STACK_MS)).find(".//mxGraphModel")
    assert small.get("pageWidth") == "1169" and small.get("pageHeight") == "826"
    # 标注列比堆叠更高（30 薄铜层：堆叠 105px、标注列 ~1.4k px）→ 页高取标注列底
    many = {"layers": [{"name": f"C{i}", "kind": "plane", "thickness_mm": 0.035}
                       for i in range(30)]}
    root = _parse(build_stackup_diagram_xml(many))
    last = _geom(_cells(root)["layer29.label"])
    expect_h = math.ceil(last[1] + last[3] + 40)
    assert expect_h > 826
    assert root.find(".//mxGraphModel").get("pageHeight") == str(expect_h)


def test_title_precedence():
    cells = _cells(_parse(build_stackup_diagram_xml(STACK_MS, title="显式")))
    assert cells["title"].get("value") == "显式"
    cells = _cells(_parse(build_stackup_diagram_xml(STACK_MS)))
    assert cells["title"].get("value") == STACK_MS["title"]


def test_xml_escapes_special_chars():
    stack = {"layers": [
        {"name": 'A<&>"B', "kind": "signal", "thickness_mm": 0.1,
         "material": "Cu & <alloy>"},
        {"name": "D", "kind": "dielectric", "thickness_mm": 0.2, "er": 3.0}],
        "width_annotations": [{"layer": 'A<&>"B', "width_mm": 0.3,
                               "note": "<50Ω & \"ref\">"}]}
    xml = build_stackup_diagram_xml(stack)
    cells = _cells(_parse(xml))  # 未转义即 ParseError=红
    assert cells["layer0.label"].get("value").startswith('A<&>"B（signal）')
    assert "Cu & <alloy>" in cells["layer0.label"].get("value")
    assert cells["w0"].get("value") == '0.3 mm  <50Ω & "ref">'


# ─── CLI 双路径 ─────────────────────────────────────────────────────────────


def test_cli_stackup_json_success_with_width_synth(tmp_path):
    out = tmp_path / "cli.drawio"
    r = _invoke(["diagram", "stackup", "--stackup", json.dumps(STACK_MS),
                 "--out", str(out), "--width-synth", json.dumps(_SYNTH_SPEC),
                 "--json"])
    assert r.exit_code == 0, r.output[:400]
    payload = _envelope(r)
    assert payload["ok"] is True
    assert payload["n_layers"] == 3
    assert payload["width_annotations"][0]["source"] == SOURCE_SYNTHESIS
    assert payload["width_annotations"][0]["width_mm"] == nominal_width_mm(
        50.0, 2.5, _SUB50)
    assert out.exists()
    _parse(out.read_text(encoding="utf-8"))


def test_cli_stackup_rich_success_markup_escaped(tmp_path):
    out = tmp_path / "rich.drawio"
    r = _invoke(["diagram", "stackup", "--stackup", json.dumps(STACK_6L),
                 "--out", str(out)])
    assert r.exit_code == 0, r.output[:400]
    assert "11 层" in r.output
    assert "[signal]" in r.output  # 动态段 escape：不被 rich 当样式吞掉
    assert "已写出" in r.output
    assert out.exists()


def test_cli_stackup_file_success(tmp_path):
    f = tmp_path / "stack.json"
    f.write_text(json.dumps(STACK_6L), encoding="utf-8")
    out = tmp_path / "file.drawio"
    r = _invoke(["diagram", "stackup", "--stackup-file", str(f),
                 "--out", str(out), "--json"])
    assert r.exit_code == 0, r.output[:400]
    assert _envelope(r)["n_layers"] == 11
    assert out.read_text(encoding="utf-8") == build_stackup_diagram_xml(STACK_6L)


def test_cli_stackup_service_failure_exit1_json_envelope(tmp_path):
    out = tmp_path / "neg.drawio"
    bad = _copy(STACK_MS)
    bad["layers"][0]["kind"] = "copper"
    r = _invoke(["diagram", "stackup", "--stackup", json.dumps(bad),
                 "--out", str(out), "--json"])
    assert r.exit_code == 1
    payload = _envelope(r)
    assert payload["ok"] is False
    assert "kind 未知" in payload["errors"][0]
    assert not out.exists()
    r = _invoke(["diagram", "stackup", "--stackup", json.dumps(bad),
                 "--out", str(out)])
    assert r.exit_code == 1
    assert "叠层图生成失败" in r.output


def test_cli_stackup_usage_errors_exit2(tmp_path):
    f = tmp_path / "stack.json"
    f.write_text(json.dumps(STACK_MS), encoding="utf-8")
    out = tmp_path / "x.drawio"
    argsets = [
        ["--stackup", "{bad json"],                          # 非法 JSON
        ["--stackup", "{}", "--stackup-file", str(f)],       # 双给
        [],                                                  # 都不给
        ["--stackup-file", str(tmp_path / "ghost.json")],    # 文件不存在
        ["--stackup", json.dumps(STACK_MS), "--width-synth", "{oops"],
    ]
    for extra in argsets:
        r = _invoke(["diagram", "stackup", *extra, "--out", str(out), "--json"])
        assert r.exit_code == 2, (extra, r.output[:300])
        assert _envelope(r)["ok"] is False
    assert not out.exists()


def test_cli_stackup_help_renders():
    r = _invoke(["diagram", "stackup", "--help"])
    assert r.exit_code == 0
    for flag in ("--stackup", "--stackup-file", "--out", "--width-synth",
                 "--json"):
        assert flag in r.output
    r = _invoke(["diagram", "--help"])
    assert r.exit_code == 0
    assert "stackup" in r.output


def test_service_public_surface():
    import rfauto.service.diagram_stackup_service as svc

    assert svc.__all__ == ["generate_stackup_diagram",
                           "synthesis_width_annotation"]
    assert sdm.__all__ == ["KIND_TABLE", "PX_PER_MM",
                           "build_stackup_diagram_xml", "build_stackup_plan",
                           "format_number", "normalize_stackup"]
    assert Path(svc.__file__).name == "diagram_stackup_service.py"
