"""T-O6 测试连接图 .drawio 生成器钉（aurora_o，2026-11-01）。

六验收钉（任务书口径，形态规格=runs/aurora_o/design_specs/
T-O6_TESTSETUP_SPEC.md）：
1. XML 结构合法——xml.etree 解析 + mxfile>diagram>mxGraphModel>root 结构
   断言 + 官方九条清单（format_notes §6：id 页内唯一/含 cell 0,1/vertex
   全带 geometry、edge relative="1"/边两端 id 存在/无 compressed）；
2. drawio 语义——连接表↔边集双射（每条 connection 恰一 conn<i> edge，
   source/target 精确等于端口点 id）+ 端口点子 cell（parent=仪器 id、
   缘位 x==父宽-4 或 -4）+ CAL 校准面子 label cell 恰一/零；
3. 端口引用完整性四负例（生命线）——引用不存在仪器/引用未声明端口/
   端口名含 `.`/仪器 id 含 `.` 全显式 ValueError（严格键校验 normalize
   家法：多余键/未知 kind/未知 role/端口重名同章）；
4. 数字原样标注（铁律 7）——图上文本恰为 "0.5 dB"/"1 m"（format_quantity
   单源断言，零换算；grep 面：装配模块零 log10）；
5. 确定性——同输入两跑 XML/文件逐字节相同（id 形态总表逐位、零时间戳
   零 uuid）；
6. 信封+CLI——service 同构信封（counts/instruments/warnings 回显）；
   ``rfauto diagram testsetup`` 双路径（--json 信封 + rich），usage 类
   exit 2 / service 失败 exit 1，--scene 与 --scene-file 恰给一。
"""

from __future__ import annotations

import inspect
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rfauto.core.testsetup_diagram as tsm
from rfauto.cli.main import app as root_app
from rfauto.core.testsetup_diagram import (
    CISPR_KIND_TABLE,
    EFFECTIVE_KIND_TABLE,
    ELECTRICAL_SHAPE_BY_KIND,
    KIND_TABLE,
    ROLE_COLUMN_X,
    ROLES,
    SHAPE_PROFILES,
    build_testsetup_diagram_xml,
    build_testsetup_plan,
    format_quantity,
    normalize_scene,
)
from rfauto.service.diagram_testsetup_service import generate_testsetup_diagram

_src_dir = Path(__file__).resolve().parents[2] / "src"
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))


# ─── 场景 fixtures（spec §四.10 两示例） ────────────────────────────────────

SCENE_VNA = {
    "title": "VNA 双端口 S 参数测量",
    "instruments": [
        {"id": "vna1", "kind": "vna", "label": "VNA (ESG)",
         "ports": ["P1 GEN", "P2 REC"], "note": "端口面 SOLR 校准"},
        {"id": "eut", "kind": "dut", "label": "DUT", "ports": ["RF1", "RF2"]},
    ],
    "connections": [
        {"from": "vna1.P1 GEN", "to": "eut.RF1",
         "cable": {"label": "RF1", "loss_db": 0.5, "length_m": 1.0},
         "cal_plane": True},
        {"from": "vna1.P2 REC", "to": "eut.RF2",
         "cable": {"label": "RF2", "loss_db": 0.5, "length_m": 1.0}},
    ],
    "notes": [{"text": "校准面在 VNA 端口法兰处（SOLR），线缆损耗已扣除",
               "anchor": "conn0"}],
}

SCENE_CISPR = {
    "title": "CISPR 传导发射测试连接（频谱仪+LISN+EUT）",
    "instruments": [
        {"id": "siggen1", "kind": "siggen", "label": "信号源 (SMB100A)",
         "ports": ["RF OUT"]},
        {"id": "lisn1", "kind": "lisn", "label": "LISN (ENV216)",
         "ports": ["EUT", "RF"], "note": "50 uH / 50 Ohm"},
        {"id": "eut", "kind": "dut", "label": "EUT", "ports": ["ANT"]},
        {"id": "specan1", "kind": "specan", "label": "频谱仪 (FSW)",
         "ports": ["RF IN"], "note": "端口面 SOLR 校准"},
    ],
    "connections": [
        {"from": "siggen1.RF OUT", "to": "lisn1.EUT",
         "cable": {"label": "RF1", "loss_db": 0.5, "length_m": 1.0},
         "label": "1 m N-N"},
        {"from": "lisn1.EUT", "to": "eut.ANT",
         "cable": {"label": "RF2", "loss_db": 0.3, "length_m": 1}},
        {"from": "lisn1.RF", "to": "specan1.RF IN",
         "cable": {"label": "RF3", "loss_db": 9.5, "length_m": 3.0},
         "cal_plane": True},
    ],
    "notes": [
        {"text": "校准面在频谱仪端口法兰处（SOLR），线缆损耗已扣除",
         "anchor": "conn2"},
        {"text": "LISN 接地平面与 EUT 距离 40 cm"},
    ],
}


# ─── 解析 helpers ───────────────────────────────────────────────────────────


def _parse(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text)  # 结构非法即抛 ParseError=红


def _by_id(root: ET.Element) -> dict[str, ET.Element]:
    """root 直接子 mxCell → id 表（扁平列表口径；边子 label cell 不含）。"""
    return {c.get("id"): c for c in
            root.findall(".//mxGraphModel/root/mxCell")}


def _all_cells(root: ET.Element) -> dict[str, ET.Element]:
    """全树 id→cell 表（含边子 label cell）。"""
    return {c.get("id"): c for c in root.iter("mxCell")}


def _edges(root: ET.Element) -> dict[str, ET.Element]:
    return {c.get("id"): c for c in _by_id(root).values()
            if c.get("edge") == "1"}


def _envelope(result) -> dict:
    out = result.output
    assert out.strip(), f"空输出（exit={result.exit_code}）"
    payload, _ = json.JSONDecoder().raw_decode(out[out.index("{"):])
    return payload


# ─── 验收①②：XML 结构合法 + drawio 语义（官方九条清单） ────────────────────


def test_xml_structure_valid_official_checklist():
    root = _parse(build_testsetup_diagram_xml(SCENE_CISPR))
    assert root.tag == "mxfile"
    diagrams = root.findall("diagram")
    assert len(diagrams) == 1
    model = diagrams[0].find("mxGraphModel")
    assert model is not None
    mx_root = model.find("root")
    assert mx_root is not None
    cells = mx_root.findall("mxCell")
    # 清单①②：id 页内唯一；恒含基 cell 0/1（id=1 parent=0）
    ids = [c.get("id") for c in cells]
    assert len(ids) == len(set(ids)), "cell id 必须页内唯一"
    assert {"0", "1"} <= set(ids)
    cell1 = _by_id(root)["1"]
    assert cell1.get("parent") == "0"
    # 清单③：root 级 vertex 恰设 vertex="1" 且各带全量 mxGeometry；
    # edge 各带 relative="1" 几何
    n_vertices = sum(1 for c in cells if c.get("vertex") == "1")
    for c in cells:
        geom = c.find("mxGeometry")
        if c.get("vertex") == "1":
            assert geom is not None and all(
                geom.get(a) is not None for a in ("x", "y", "width", "height")), \
                f"vertex {c.get('id')} 缺全量 mxGeometry"
        if c.get("edge") == "1":
            assert geom is not None and geom.get("relative") == "1"
    assert n_vertices == 4 + 5 + 1 + 2  # 仪器 4 + 端口点 5 + 标题 + 注记 2
    assert len(_edges(root)) == 3 + 1  # 连接 3 + 注记锚 1
    # 清单④：每条 edge 的 source/target 引用存在 id
    all_ids = set(ids)
    for e in _edges(root).values():
        assert e.get("source") in all_ids
        assert e.get("target") in all_ids
    # 清单⑧：页不压缩——全树无 compressed 属性
    assert all(c.get("compressed") is None for c in root.iter())


def test_connection_table_edge_bijection():
    root = _parse(build_testsetup_diagram_xml(SCENE_CISPR))
    edges = _edges(root)
    conns = SCENE_CISPR["connections"]
    conn_ids = [f"conn{i}" for i in range(len(conns))]
    for i, cid in enumerate(conn_ids):
        assert cid in edges, f"connection[{i}] 缺对应 edge {cid}"
        e = edges[cid]
        assert e.get("source") == conns[i]["from"], "source 必须精确=from 端口点 id"
        assert e.get("target") == conns[i]["to"], "target 必须精确=to 端口点 id"
        assert e.get("parent") == "1"
    extra = [k for k in edges if re.fullmatch(r"conn\d+", k)
             and k not in conn_ids]
    assert not extra, f"边集超出连接表：{extra}"


def test_port_dots_child_cell_semantics():
    root = _parse(build_testsetup_diagram_xml(SCENE_VNA))
    cells = _by_id(root)
    for inst in SCENE_VNA["instruments"]:
        for port in inst["ports"]:
            pid = f"{inst['id']}.{port}"
            dot = cells[pid]
            assert dot.get("vertex") == "1"
            assert dot.get("parent") == inst["id"], "端口点必须是仪器子 cell"
            assert dot.get("value") == port, "端口标签=端口点 value（图上可见）"
            geom = dot.find("mxGeometry")
            x, y = int(geom.get("x")), int(geom.get("y"))
            assert x in (-4, 116), f"端口点必须贴父缘（x==父宽-4 或 -4），{pid}"
            assert 0 <= y <= 64 - 8
            # 子 cell 几何相对父左上：x 落在父宽带内（116=父宽-4）
            w, h = int(geom.get("width")), int(geom.get("height"))
            assert (w, h) == (8, 8)


def test_port_sides_by_role():
    scene = {
        "instruments": [
            {"id": "sg", "kind": "siggen", "label": "源", "ports": ["A", "B"]},
            {"id": "sa", "kind": "specan", "label": "分析仪", "ports": ["A"]},
            {"id": "gn", "kind": "generic", "label": "辅助", "ports": ["A"]},
        ],
        "connections": [],
    }
    cells = _by_id(_parse(build_testsetup_diagram_xml(scene)))
    assert int(cells["sg.A"].find("mxGeometry").get("x")) == 116   # stim 右缘
    assert int(cells["sg.B"].find("mxGeometry").get("x")) == 116
    assert int(cells["sa.A"].find("mxGeometry").get("x")) == -4    # anal 左缘
    assert int(cells["gn.A"].find("mxGeometry").get("x")) == -4    # aux 左缘


def test_dut_port_split_halves_and_odd_warning():
    scene_even = {
        "instruments": [
            {"id": "d", "kind": "dut", "label": "DUT",
             "ports": ["A", "B", "C", "D"]},
            {"id": "v", "kind": "vna", "label": "VNA", "ports": ["P"]},
        ],
        "connections": [],
    }
    cells = _by_id(_parse(build_testsetup_diagram_xml(scene_even)))
    # 对半分：左半=声明序前半（stim 侧）、右半=后半（anal 侧），各缘自上而下
    left_ys = [int(cells[f"d.{p}"].find("mxGeometry").get("y"))
               for p in ("A", "B")]
    right_ys = [int(cells[f"d.{p}"].find("mxGeometry").get("y"))
                for p in ("C", "D")]
    assert all(int(cells[f"d.{p}"].find("mxGeometry").get("x")) == -4
               for p in ("A", "B"))
    assert all(int(cells[f"d.{p}"].find("mxGeometry").get("x")) == 116
               for p in ("C", "D"))
    assert left_ys == sorted(left_ys) and right_ys == sorted(right_ys)
    assert left_ys == [8, 48] and right_ys == [8, 48]

    scene_odd = {
        "instruments": [
            {"id": "d", "kind": "dut", "label": "DUT",
             "ports": ["A", "B", "C"]},
            {"id": "v", "kind": "vna", "label": "VNA", "ports": ["P"]},
        ],
        "connections": [],
    }
    plan = build_testsetup_plan(scene_odd)
    cells = _by_id(_parse(plan["xml"]))
    # 奇数：左半 1 个、右半 2 个，中间端口（声明序第 2）落右缘顶部
    assert int(cells["d.A"].find("mxGeometry").get("x")) == -4
    assert int(cells["d.B"].find("mxGeometry").get("x")) == 116
    assert int(cells["d.B"].find("mxGeometry").get("y")) == 8
    assert int(cells["d.C"].find("mxGeometry").get("y")) == 48
    assert any("'d'" in w and "奇数" in w for w in plan["warnings"])


def test_cal_plane_marker_sub_cell():
    root = _parse(build_testsetup_diagram_xml(SCENE_VNA))
    edges = _edges(root)
    cal_cell = edges["conn0"]
    children = cal_cell.findall("mxCell")
    assert len(children) == 1, "cal_plane=true 边恰一子 label cell"
    label = children[0]
    assert label.get("id") == "conn0.cal"
    assert label.get("value") == "▎CAL"
    assert label.get("parent") == "conn0"
    assert label.get("vertex") == "1"
    assert "fontStyle=1" in label.get("style")
    geom = label.find("mxGeometry")
    assert geom.get("relative") == "1"
    assert geom.get("x") == "0" and geom.get("y") == "-12"
    assert geom.find("mxPoint") is not None, "edge label 几何带 offset 点"
    assert edges["conn1"].findall("mxCell") == [], "cal_plane=false 边零子 cell"


def test_xml_escapes_special_chars():
    scene = {
        "instruments": [{"id": "g1", "kind": "generic",
                         "label": 'A<B>&"X"漂', "ports": ["P<1>"],
                         "note": "注&记"}],
        "connections": [],
    }
    cells = _by_id(_parse(build_testsetup_diagram_xml(scene)))
    value = cells["g1"].get("value")
    assert value.startswith('A<B>&"X"漂\n'), "特殊字符转义往返无损（多行标签）"
    assert cells["g1.P<1>"].get("value") == "P<1>"
    assert cells["g1"].get("note") == "注&记"


# ─── 验收④：数字原样标注（铁律 7——零换算） ─────────────────────────────────


def test_annotation_verbatim_no_conversion():
    root = _parse(build_testsetup_diagram_xml(SCENE_CISPR))
    edges = _edges(root)
    # spec §3.5 示例锚：cable+自由标注并存 → "先 cable 后自由" 两空格拼接
    assert edges["conn0"].get("value") == "RF1  0.5 dB  1 m  1 m N-N"
    assert edges["conn1"].get("value") == "RF2  0.3 dB  1 m"
    assert edges["conn2"].get("value") == "RF3  9.5 dB  3 m"


def test_format_quantity_fixed_tiers_and_single_source():
    # 分档锚（spec §四.6 示例）：0.5→"0.5"、整数值不带小数点 1.0→"1"
    assert format_quantity(0.5) == "0.5"
    assert format_quantity(1.0) == "1"
    assert format_quantity(1) == "1"
    assert format_quantity(12.25) == "12.25"
    assert format_quantity(0) == "0"
    # 装配与断言消费同一函数（单源）：边文本逐位=format_quantity 拼接
    plan = build_testsetup_plan(SCENE_CISPR)
    c0 = SCENE_CISPR["connections"][0]["cable"]
    expected = "  ".join([
        c0["label"],
        f"{format_quantity(c0['loss_db'])} dB",
        f"{format_quantity(c0['length_m'])} m",
        SCENE_CISPR["connections"][0]["label"],
    ])
    edges = _edges(_parse(plan["xml"]))
    assert edges["conn0"].get("value") == expected


def test_module_zero_conversion_grep():
    src = inspect.getsource(tsm)
    for banned in ("log10", "math.log", "10 **", "10**", "pow("):
        assert banned not in src, f"装配模块出现换算逻辑 {banned!r}（铁律 7）"


def test_format_quantity_type_negatives():
    for bad in ("0.5", True, None, [0.5]):
        with pytest.raises(ValueError):
            format_quantity(bad)
    with pytest.raises(ValueError):
        format_quantity(float("nan"))
    with pytest.raises(ValueError):
        format_quantity(float("inf"))


def test_annotation_numeric_field_negatives(tmp_path):
    out = tmp_path / "x.drawio"
    base = {"instruments": [{"id": "a", "kind": "vna", "label": "V",
                             "ports": ["P"]}],
            "connections": [{"from": "a.P", "to": "a.P"}]}
    bad_cable_str = json.loads(json.dumps(base))
    bad_cable_str["connections"][0]["cable"] = {"label": "C",
                                                "loss_db": "0.5"}
    bad_cable_bool = json.loads(json.dumps(base))
    bad_cable_bool["connections"][0]["cable"] = {"label": "C",
                                                 "length_m": True}
    bad_cable_nan = json.loads(json.dumps(base))
    bad_cable_nan["connections"][0]["cable"] = {"label": "C",
                                                "loss_db": float("nan")}
    bad_cal = json.loads(json.dumps(base))
    bad_cal["connections"][0]["cal_plane"] = "true"
    for bad in (bad_cable_str, bad_cable_bool, bad_cable_nan, bad_cal):
        result = generate_testsetup_diagram(bad, out)
        assert result["ok"] is False, bad
        assert result["errors"]
    assert not out.exists(), "失败路径不得落产物"


# ─── 验收③：端口引用完整性四负例 + 严格键校验 ───────────────────────────────


def _minimal_scene(**conn_overrides):
    scene = {
        "instruments": [
            {"id": "vna1", "kind": "vna", "label": "VNA", "ports": ["P1"]},
            {"id": "eut", "kind": "dut", "label": "DUT", "ports": ["ANT"]},
        ],
        "connections": [{"from": "vna1.P1", "to": "eut.ANT"}],
    }
    scene["connections"][0].update(conn_overrides)
    return scene


def test_negative_reference_missing_instrument():
    with pytest.raises(ValueError, match="引用不存在仪器"):
        normalize_scene(_minimal_scene(to="ghost.ANT"))


def test_negative_reference_undeclared_port():
    with pytest.raises(ValueError, match="引用未声明端口"):
        normalize_scene(_minimal_scene(to="eut.NOT_DECLARED"))
    # 端口名含 '.' 的引用形态（第二个点）→ 归入未声明端口（声明侧另有专钉）
    with pytest.raises(ValueError, match="引用未声明端口"):
        normalize_scene(_minimal_scene(**{"from": "vna1.P1.X"}))


def test_negative_port_name_contains_dot():
    scene = {"instruments": [{"id": "a", "kind": "vna", "label": "V",
                              "ports": ["P.1"]}]}
    with pytest.raises(ValueError, match="含 '\\.'"):
        normalize_scene(scene)


def test_negative_instrument_id_constraints():
    def scene_with_id(inst_id):
        return {"instruments": [{"id": inst_id, "kind": "vna",
                                 "label": "V", "ports": ["P"]}]}

    # id 含 '.'（端口点 id 形态 <inst>.<port> 依赖 id 不含点）
    with pytest.raises(ValueError, match=r"\[A-Za-z0-9_-\]\+"):
        normalize_scene(scene_with_id("vn.a"))
    with pytest.raises(ValueError):
        normalize_scene(scene_with_id("含中文"))
    with pytest.raises(ValueError):
        normalize_scene(scene_with_id("has space"))
    # 保留 id 命名空间（id 形态总表 §3.7：conn<i>/note<i>/title/基 cell 0/1）
    for reserved in ("0", "1", "title", "conn0", "note1"):
        with pytest.raises(ValueError, match="保留"):
            normalize_scene(scene_with_id(reserved))
    # 页内重名
    dup = {"instruments": [
        {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]},
        {"id": "a", "kind": "dut", "label": "D", "ports": ["Q"]}]}
    with pytest.raises(ValueError, match="重名"):
        normalize_scene(dup)


def test_negative_unknown_kind_and_role():
    with pytest.raises(ValueError, match="kind"):
        normalize_scene({"instruments": [{"id": "a", "kind": "mixer",
                                          "label": "M", "ports": ["P"]}]})
    with pytest.raises(ValueError, match="role"):
        normalize_scene({"instruments": [{"id": "a", "kind": "vna",
                                          "label": "M", "ports": ["P"],
                                          "role": "power"}]})


def test_negative_extra_keys():
    inst = {"id": "a", "kind": "vna", "label": "V", "ports": ["P"], "x": 1}
    with pytest.raises(ValueError, match="未支持键"):
        normalize_scene({"instruments": [inst]})
    with pytest.raises(ValueError, match="未支持键"):
        normalize_scene({"instruments": [
            {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]}],
            "connections": [{"from": "a.P", "to": "a.P", "foo": 1}]})
    with pytest.raises(ValueError, match="未支持键"):
        normalize_scene({"instruments": [
            {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]}],
            "connections": [{"from": "a.P", "to": "a.P",
                             "cable": {"label": "C", "z": 0}}]})
    with pytest.raises(ValueError, match="未支持键"):
        normalize_scene({"instruments": [
            {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]}],
            "notes": [{"text": "t", "anchor": "conn0", "q": 1}]})
    with pytest.raises(ValueError, match="未支持键"):
        normalize_scene({"instruments": [
            {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]}],
            "toplevel_extra": 1})


@pytest.mark.parametrize(
    "scene",
    [
        {},                                                       # 缺 instruments
        {"instruments": []},                                      # 空仪器表
        {"instruments": [{"id": "a", "kind": "vna", "ports": ["P"]}]},  # 缺 label
        {"instruments": [{"id": "a", "kind": "vna", "label": "",
                          "ports": ["P"]}]},                      # 空 label
        {"instruments": [{"id": "a", "kind": "vna", "label": "V",
                          "ports": ["A", "A"]}]},                 # 端口重名
        {"instruments": [{"id": "a", "kind": "vna", "label": "V",
                          "ports": [""]}]},                       # 空端口名
        {"instruments": [{"id": "a", "kind": "vna", "label": "V",
                          "ports": "P"}]},                        # ports 非列表
        {"instruments": [{"id": "a", "kind": "vna", "label": "V",
                          "ports": ["P"]}],
         "connections": [{"from": "a.P"}]},                       # 缺 to
        {"instruments": [{"id": "a", "kind": "vna", "label": "V",
                          "ports": ["P"]}],
         "connections": [{"from": "a.P", "to": "a.P",
                          "cable": {"loss_db": 1.0}}]},           # cable 缺 label
        {"instruments": [{"id": "a", "kind": "vna", "label": "V",
                          "ports": ["P"]}],
         "notes": [{"anchor": "conn0"}]},                         # 注记缺 text
        "not-a-dict",                                             # 非对象
    ],
)
def test_negative_required_keys(scene):
    with pytest.raises(ValueError):
        normalize_scene(scene)


def test_negative_anchor_resolution():
    scene = {"instruments": [
        {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]}],
        "connections": [{"from": "a.P", "to": "a.P"}],
        "notes": [{"text": "t", "anchor": "conn5"}]}   # 越界连接序号
    with pytest.raises(ValueError, match="anchor"):
        normalize_scene(scene)
    scene["notes"][0]["anchor"] = "nowhere"
    with pytest.raises(ValueError, match="anchor"):
        normalize_scene(scene)
    # 合法锚：仪器 id 与 conn<i> 各一（锚边 target 存在）
    scene["notes"][0]["anchor"] = "conn0"
    root = _parse(build_testsetup_diagram_xml(scene))
    assert _edges(root)["note0.anchor"].get("target") == "conn0"
    scene["notes"][0]["anchor"] = "a"
    root = _parse(build_testsetup_diagram_xml(scene))
    assert _edges(root)["note0.anchor"].get("target") == "a"


def test_negative_scene_not_dict_no_file(tmp_path):
    out = tmp_path / "neg.drawio"
    for bad in ([], "x", None, 42):
        result = generate_testsetup_diagram(bad, out)
        assert result["ok"] is False
        assert result["errors"] and isinstance(result["errors"], list)
    assert not out.exists(), "失败路径不得落产物"


# ─── 验收⑤：确定性（同输入两跑逐字节 + id 形态总表零 uuid） ─────────────────


def test_determinism_two_runs_byte_identical(tmp_path):
    xml1 = build_testsetup_diagram_xml(SCENE_CISPR)
    xml2 = build_testsetup_diagram_xml(SCENE_CISPR)
    assert xml1 == xml2
    out1 = tmp_path / "a.drawio"
    out2 = tmp_path / "b.drawio"
    assert generate_testsetup_diagram(SCENE_CISPR, out1)["ok"] is True
    assert generate_testsetup_diagram(SCENE_CISPR, out2)["ok"] is True
    assert out1.read_bytes() == out2.read_bytes()
    assert out1.read_text(encoding="utf-8") == xml1
    assert "modified" not in xml1 and "created" not in xml1  # 零时间戳


def test_id_shape_table_no_uuid():
    """id 形态总表（spec §3.7）：仪器原样/端口 <inst>.<port>/conn<i>/note<i>/
    title/派生 .cal 与 .anchor——全集逐位可预期，零 uuid 零时间戳 id。"""
    plan = build_testsetup_plan(SCENE_CISPR)
    root = _parse(plan["xml"])
    ids = {c.get("id") for c in root.iter("mxCell")}
    expected = {"0", "1", "title"}
    for inst in plan["instruments"]:
        expected.add(inst["id"])
        for p in inst["ports"]:
            expected.add(f"{inst['id']}.{p}")
    expected |= {f"conn{i}" for i in range(plan["n_connections"])}
    expected |= {f"note{i}" for i in range(plan["n_notes"])}
    expected |= {f"conn{i}.cal" for i, c in enumerate(SCENE_CISPR["connections"])
                 if c.get("cal_plane")}
    expected |= {f"note{i}.anchor" for i, n in enumerate(SCENE_CISPR["notes"])
                 if n.get("anchor")}
    assert ids == expected, "cell id 全集必须=确定性形态总表（禁 uuid）"
    assert not any(re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", i)
                   for i in ids)


# ─── 布局：role 五列分层 + DUT 垂直居中 + 页面自适应 ────────────────────────


def test_role_columns_layout_and_dut_centering():
    scene = {
        "instruments": [
            {"id": "v1", "kind": "vna", "label": "V1", "ports": []},
            {"id": "v2", "kind": "siggen", "label": "V2", "ports": []},
            {"id": "d", "kind": "dut", "label": "D", "ports": []},
        ],
        "connections": [],
    }
    cells = _by_id(_parse(build_testsetup_diagram_xml(scene)))
    # role→列 x 常量（spec §3.2 五列布局表）
    assert int(cells["v1"].find("mxGeometry").get("x")) == ROLE_COLUMN_X["stim"]
    assert int(cells["v2"].find("mxGeometry").get("x")) == ROLE_COLUMN_X["stim"]
    assert int(cells["d"].find("mxGeometry").get("x")) == ROLE_COLUMN_X["dut"]
    # 同列多台按 JSON 序自上而下（行步距 160）
    assert int(cells["v1"].find("mxGeometry").get("y")) == 100
    assert int(cells["v2"].find("mxGeometry").get("y")) == 260
    # DUT 垂直居中于全图行跨中位（2 行 → 中位 0.5 → y=180）
    assert int(cells["d"].find("mxGeometry").get("y")) == 180


def test_page_size_adapts_to_content():
    base = {"instruments": [{"id": "a", "kind": "vna", "label": "V",
                             "ports": ["P"]}], "connections": []}
    model = _parse(build_testsetup_diagram_xml(base)).find("diagram/mxGraphModel")
    assert model.get("pageWidth") == "1169"  # 内容最右列不超缺省页宽
    aux = {"instruments": [
        {"id": "a", "kind": "vna", "label": "V", "ports": []},
        {"id": "z", "kind": "generic", "label": "G", "ports": []}]}
    model = _parse(build_testsetup_diagram_xml(aux)).find("diagram/mxGraphModel")
    # aux 列 x=1160 + 卡宽 120 + 边距 40 → 页宽扩展到 1320
    assert model.get("pageWidth") == str(ROLE_COLUMN_X["aux"] + 120 + 40)
    many_notes = dict(base)
    many_notes["notes"] = [{"text": f"注{i}"} for i in range(40)]
    model = _parse(build_testsetup_diagram_xml(many_notes)).find(
        "diagram/mxGraphModel")
    assert int(model.get("pageHeight")) > 826  # 注记区向下扩展


def test_kind_table_single_source():
    assert sorted(KIND_TABLE) == [
        "amplifier", "attenuator", "coupler", "dut", "generic", "lisn",
        "powermeter", "siggen", "specan", "vna"]
    assert len(KIND_TABLE) == 10
    expected = {
        "vna": ("stim", "#dae8fc", "#6c8ebf"),
        "siggen": ("stim", "#dae8fc", "#6c8ebf"),
        "specan": ("anal", "#ffe6cc", "#d79b00"),
        "powermeter": ("anal", "#ffe6cc", "#d79b00"),
        "dut": ("dut", "#d5e8d4", "#82b366"),
        "lisn": ("inline", "#fff2cc", "#d6b656"),
        "attenuator": ("inline", "#f8cecc", "#b85450"),
        "coupler": ("inline", "#f8cecc", "#b85450"),
        "amplifier": ("inline", "#f8cecc", "#b85450"),
        "generic": ("aux", "#f5f5f5", "#666666"),
    }
    for kind, triple in expected.items():
        assert KIND_TABLE[kind] == triple, f"kind {kind} 缺省表漂移"
    assert ROLES == ("stim", "inline", "dut", "anal", "aux")
    assert ROLE_COLUMN_X == {"stim": 40, "inline": 320, "dut": 600,
                             "anal": 880, "aux": 1160}


def test_kind_role_default_and_color_on_card():
    scene = {"instruments": [{"id": "g", "kind": "lisn", "label": "L",
                              "ports": []}]}
    cells = _by_id(_parse(build_testsetup_diagram_xml(scene)))
    card = cells["g"]
    assert card.get("role") == "inline"           # kind→role 缺省查表
    assert "#fff2cc" in card.get("style") and "#d6b656" in card.get("style")
    scene2 = {"instruments": [{"id": "g", "kind": "lisn", "label": "L",
                               "ports": ["EUT", "RF"]}]}
    card2 = _by_id(_parse(build_testsetup_diagram_xml(scene2)))["g"]
    assert card2.get("ports") == "EUT|RF"          # 端口 pipe-join 机器回读面
    assert card2.get("value") == "L\nlisn"         # 两行=主标签/kind（无 note）


# ─── 验收⑥：信封契约（warnings 四类逐条可断言） ────────────────────────────


def test_warnings_inventory_four_classes():
    scene = {
        "instruments": [
            {"id": "s1", "kind": "siggen", "label": "S1", "ports": []},
            {"id": "s2", "kind": "siggen", "label": "S2", "ports": []},
            {"id": "s3", "kind": "siggen", "label": "S3", "ports": ["P"]},
            {"id": "d", "kind": "dut", "label": "D",
             "ports": ["A", "B", "C"]},
        ],
        "connections": [],
    }
    plan = build_testsetup_plan(scene)
    warnings = plan["warnings"]
    assert any("无连接" in w for w in warnings), "类① 无连接"
    assert sum("无端口" in w and "'s1'" in w for w in warnings) == 1, "类② 空端口"
    assert any("列 stim" in w and "3 台" in w for w in warnings), "类③ 同列>2"
    assert any("奇数" in w and "'d'" in w for w in warnings), "类④ 奇数端口"
    assert len(warnings) == 5  # 无连接 + 空端口×2（s1/s2） + 同列>2 + 奇数端口


def test_service_success_envelope_echo(tmp_path):
    out = tmp_path / "ok.drawio"
    result = generate_testsetup_diagram(SCENE_CISPR, out, title="自定义标题")
    assert result["ok"] is True
    assert result["n_instruments"] == 4
    assert result["n_connections"] == 3
    assert result["n_notes"] == 2
    assert [i["id"] for i in result["instruments"]] == [
        "siggen1", "lisn1", "eut", "specan1"]
    inst = result["instruments"][0]
    assert set(inst) == {"id", "kind", "role", "label", "ports", "note"}
    assert Path(result["out_path"]).exists()
    assert "自定义标题" in out.read_text(encoding="utf-8")


def test_service_missing_parent_dir_explicit_error(tmp_path):
    out = tmp_path / "no_such_dir" / "x.drawio"
    result = generate_testsetup_diagram(SCENE_CISPR, out)
    assert result["ok"] is False
    assert "目录不存在" in result["errors"][0]


# ─── 验收⑩：spec 两示例场景端到端 ───────────────────────────────────────────


def test_spec_scenario_vna_two_port_end_to_end(tmp_path):
    out = tmp_path / "vna.drawio"
    assert generate_testsetup_diagram(SCENE_VNA, out)["ok"] is True
    root = _parse(out.read_text(encoding="utf-8"))
    edges = _edges(root)
    assert edges["conn0"].get("source") == "vna1.P1 GEN"
    assert edges["conn0"].get("target") == "eut.RF1"
    assert edges["conn1"].get("target") == "eut.RF2"
    # 双口场景含 1 条校准面标记
    assert len(edges["conn0"].findall("mxCell")) == 1
    assert edges["conn1"].findall("mxCell") == []


def test_spec_scenario_cispr_conducted_end_to_end(tmp_path):
    out = tmp_path / "cispr.drawio"
    result = generate_testsetup_diagram(SCENE_CISPR, out)
    assert result["ok"] is True
    assert out.exists()
    root = _parse(out.read_text(encoding="utf-8"))
    cells = _by_id(root)
    edges = _edges(root)
    # siggen→LISN→EUT + LISN→specan（校准面）链路形态
    assert edges["conn0"].get("source") == "siggen1.RF OUT"
    assert edges["conn0"].get("target") == "lisn1.EUT"
    assert edges["conn1"].get("target") == "eut.ANT"
    assert edges["conn2"].get("target") == "specan1.RF IN"
    assert "9.5 dB" in edges["conn2"].get("value")
    assert edges["conn2"].findall("mxCell")[0].get("value") == "▎CAL"
    # 仪器卡属性承载（kind/role/ports/note）与多行标签
    lisn = cells["lisn1"]
    assert (lisn.get("kind"), lisn.get("role")) == ("lisn", "inline")
    assert lisn.get("ports") == "EUT|RF"
    assert lisn.get("value") == "LISN (ENV216)\nlisn\n50 uH / 50 Ohm"
    # 注记：锚定注记带虚线边 + 无锚注记纯文本
    assert edges["note0.anchor"].get("target") == "conn2"
    assert cells["note1"].get("value").startswith("N2. ")
    assert "note1.anchor" not in edges
    assert "校准面在频谱仪端口法兰处" in cells["note0"].get("value")


# ─── CLI 面（验收⑥：--json 信封 + rich + 恰给一 + help 渲染） ───────────────


def _invoke(args: list[str]):
    return CliRunner().invoke(root_app, args)


def test_cli_testsetup_json_success(tmp_path):
    out = tmp_path / "cli.drawio"
    r = _invoke(["diagram", "testsetup", "--scene", json.dumps(SCENE_CISPR),
                 "--out", str(out), "--json"])
    assert r.exit_code == 0, r.output[:400]
    payload = _envelope(r)
    assert payload["ok"] is True
    assert payload["n_instruments"] == 4
    assert payload["n_connections"] == 3
    assert isinstance(payload["warnings"], list)
    assert out.exists()
    _parse(out.read_text(encoding="utf-8"))


def test_cli_testsetup_rich_success(tmp_path):
    out = tmp_path / "rich.drawio"
    r = _invoke(["diagram", "testsetup", "--scene", json.dumps(SCENE_VNA),
                 "--out", str(out)])
    assert r.exit_code == 0, r.output[:400]
    assert "已写出" in r.output
    assert "仪器 2 台" in r.output
    assert out.exists()


def test_cli_testsetup_scene_file_success(tmp_path):
    scene_file = tmp_path / "scene.json"
    scene_file.write_text(json.dumps(SCENE_CISPR), encoding="utf-8")
    out = tmp_path / "file.drawio"
    r = _invoke(["diagram", "testsetup", "--scene-file", str(scene_file),
                 "--out", str(out), "--json"])
    assert r.exit_code == 0, r.output[:400]
    assert _envelope(r)["ok"] is True
    assert out.exists()


def test_cli_testsetup_service_failure_exit1_json_envelope(tmp_path):
    out = tmp_path / "neg.drawio"
    bad = json.loads(json.dumps(SCENE_CISPR))
    bad["connections"][0]["from"] = "ghost.X"
    r = _invoke(["diagram", "testsetup", "--scene", json.dumps(bad),
                 "--out", str(out), "--json"])
    assert r.exit_code == 1
    payload = _envelope(r)
    assert payload["ok"] is False
    assert "引用不存在仪器" in payload["errors"][0]
    assert not out.exists()


def test_cli_testsetup_usage_errors_exit2(tmp_path):
    scene_file = tmp_path / "scene.json"
    scene_file.write_text(json.dumps(SCENE_CISPR), encoding="utf-8")
    out = tmp_path / "x.drawio"
    # 非法 JSON → usage exit 2（--json 下必须 JSON 信封）
    r = _invoke(["diagram", "testsetup", "--scene", "{bad json",
                 "--out", str(out), "--json"])
    assert r.exit_code == 2
    assert _envelope(r)["ok"] is False
    # --scene 与 --scene-file 双给 → 互斥 usage exit 2
    r = _invoke(["diagram", "testsetup", "--scene", "{}",
                 "--scene-file", str(scene_file),
                 "--out", str(out), "--json"])
    assert r.exit_code == 2
    # 都不给 → 恰给一 usage exit 2
    r = _invoke(["diagram", "testsetup", "--out", str(out), "--json"])
    assert r.exit_code == 2
    # 场景文件非 JSON 对象 → exit 2
    list_file = tmp_path / "list.json"
    list_file.write_text("[]", encoding="utf-8")
    r = _invoke(["diagram", "testsetup", "--scene-file", str(list_file),
                 "--out", str(out), "--json"])
    assert r.exit_code == 2
    # 场景为 JSON 数组（非对象）→ service 负例 exit 1 信封
    r = _invoke(["diagram", "testsetup", "--scene", "[]",
                 "--out", str(out), "--json"])
    assert r.exit_code == 1
    assert _envelope(r)["ok"] is False


def test_cli_testsetup_help_renders():
    # help 卫生（#305/D-06 家法）：--help 可渲染无 MarkupError/格式符炸
    r = _invoke(["diagram", "testsetup", "--help"])
    assert r.exit_code == 0
    assert "--scene" in r.output
    r = _invoke(["diagram", "--help"])
    assert r.exit_code == 0


# ─── aurora_p A3：opt-in 形状档（mxgraph.electrical）+ CISPR/EMI kind 扩展 ──
# 形状名实读证据=runs/aurora_p/a3_shapes/SHAPE_EVIDENCE.md（jgraph/drawio dev
# 分支 Sidebar-Electrical.js 逐字行号落盘；#215 纪律零想象命名）。

#: CISPR 25 传导发射（电压法）样例场景（电气档 opt-in + 新 kind）——
#: 与 examples/diagrams/cispr25_conducted_emission_example.json 同文（发布
#: 样例由本 fixture 生成；测试自包含不读 examples/）。
SCENE_CISPR25 = {
    "title": "CISPR 25 传导发射测试连接（电压法：EUT+人工网络+EMI 接收机）",
    "shapes": "electrical",
    "instruments": [
        {"id": "bat", "kind": "battery", "label": "蓄电池 12 V",
         "role": "stim", "ports": ["DC+", "DC-"]},
        {"id": "lisn1", "kind": "lisn", "label": "人工网络 LISN",
         "ports": ["EUT", "BAT", "RF", "GND"], "note": "50 uH / 50 Ohm"},
        {"id": "eut", "kind": "dut", "label": "EUT 被测件",
         "ports": ["B+", "LOAD"], "note": "距参考板 50 mm"},
        {"id": "att1", "kind": "attenuator", "label": "瞬态限幅器",
         "ports": ["IN", "OUT"], "note": "10 dB"},
        {"id": "recv", "kind": "emi_receiver", "label": "EMI 接收机",
         "ports": ["RF IN"], "note": "峰值/准峰值检波"},
        {"id": "loadsim", "kind": "load_simulator", "label": "负载模拟器",
         "ports": ["HARN"]},
        {"id": "plane", "kind": "anchor_plane", "label": "参考接地板",
         "ports": [], "note": "2000 x 1000 mm"},
    ],
    "connections": [
        {"from": "bat.DC+", "to": "lisn1.BAT",
         "cable": {"label": "DC 馈线", "length_m": 1.2}},
        {"from": "eut.B+", "to": "lisn1.EUT",
         "cable": {"label": "电源线束", "length_m": 5}},
        {"from": "lisn1.RF", "to": "att1.IN",
         "cable": {"label": "RF1", "loss_db": 9.5, "length_m": 3.0},
         "cal_plane": True},
        {"from": "att1.OUT", "to": "recv.RF IN",
         "cable": {"label": "RF2", "loss_db": 3.0, "length_m": 1.0}},
        {"from": "eut.LOAD", "to": "loadsim.HARN",
         "cable": {"label": "负载线束", "length_m": 1.5}},
    ],
    "notes": [
        {"text": "校准面在 LISN RF 端口处，限幅器损耗已扣除", "anchor": "conn2"},
        {"text": "LISN/EUT 与参考板低阻抗搭接", "anchor": "plane"},
    ],
}


def test_shapes_profile_evidence_table_verbatim():
    """形状档与实读核对表逐字一致（验收 C：零想象命名）。"""
    expected = {
        "siggen": "mxgraph.electrical.instruments.signal_generator",
        "dut": "mxgraph.electrical.miscellaneous.generic_component",
        "lisn": "mxgraph.electrical.abstract.filter",
        "attenuator": "mxgraph.electrical.resistors.attenuator",
        "amplifier": "mxgraph.electrical.abstract.amplifier",
        "generic": "mxgraph.electrical.miscellaneous.generic_component",
        "battery": "mxgraph.electrical.miscellaneous.monocell_battery",
        "antenna_mast": "mxgraph.electrical.radio.aerial_-_antenna_2",
        "anchor_plane": "mxgraph.electrical.signal_sources.signal_ground",
    }
    assert {"electrical": expected} == SHAPE_PROFILES
    assert expected == ELECTRICAL_SHAPE_BY_KIND
    for name in expected.values():
        assert re.fullmatch(r"mxgraph\.electrical\.[a-z0-9_-]+\.[a-z0-9_-]+",
                            name), name
    # 负证据如实不映射：无忠实 stencil 的 kind 恰为这 7 个（证据笔记 §四）
    unmapped = set(EFFECTIVE_KIND_TABLE) - set(ELECTRICAL_SHAPE_BY_KIND)
    assert unmapped == {"vna", "specan", "powermeter", "coupler",
                        "emi_receiver", "current_probe", "load_simulator"}


def test_default_profile_ab_byte_identical():
    """验收 B：缺省档零变化——shapes 缺省/显式 None/空 dict 三态逐字节同，
    仪器卡 style 与改码前形态逐字同（无 shape= 前缀）。"""
    xml_absent = build_testsetup_diagram_xml(SCENE_CISPR)
    assert xml_absent == build_testsetup_diagram_xml(
        {**SCENE_CISPR, "shapes": None})
    assert xml_absent == build_testsetup_diagram_xml(
        {**SCENE_CISPR, "shapes": {}})
    scene = {"instruments": [{"id": "v", "kind": "vna", "label": "V",
                              "ports": ["P"]}], "connections": []}
    card = _by_id(_parse(build_testsetup_diagram_xml(scene)))["v"]
    assert card.get("style") == ("rounded=0;whiteSpace=wrap;html=1;"
                                 "fillColor=#dae8fc;strokeColor=#6c8ebf;")
    assert "shape=" not in card.get("style")


def test_electrical_profile_style_verbatim_and_partial_mapping():
    """验收 C：electrical 档 style 逐字（官方公共前缀序+kind 色板）；无忠实
    stencil 的 kind 保持缺省矩形卡（部分映射如实）。"""
    scene = {"shapes": "electrical",
             "instruments": [
                 {"id": "sg", "kind": "siggen", "label": "源",
                  "ports": ["RF"], "note": "N"},
                 {"id": "v", "kind": "vna", "label": "V", "ports": ["P"]}],
             "connections": []}
    cells = _by_id(_parse(build_testsetup_diagram_xml(scene)))
    # 映射 kind：官方前缀序 + 核对表形状名 + kind 色板（逐字）
    assert cells["sg"].get("style") == (
        "verticalLabelPosition=bottom;shadow=0;dashed=0;align=center;"
        "html=1;verticalAlign=top;"
        "shape=mxgraph.electrical.instruments.signal_generator;"
        "fillColor=#dae8fc;strokeColor=#6c8ebf;outlineConnect=0;")
    # 未映射 kind（vna 无忠实 stencil）：缺省矩形卡原样
    assert cells["v"].get("style") == ("rounded=0;whiteSpace=wrap;html=1;"
                                       "fillColor=#dae8fc;strokeColor=#6c8ebf;")
    # 机器回读属性在形状档下不变（kind/role/ports/note/placeholders）
    assert cells["sg"].get("kind") == "siggen"
    assert cells["sg"].get("role") == "stim"
    assert cells["sg"].get("ports") == "RF"
    assert cells["sg"].get("note") == "N"
    assert cells["sg"].get("placeholders") == "1"


def test_shapes_per_kind_override_applies_selectively():
    """per-kind dict 覆盖：仅被点名 kind 换形状，其余保持缺省卡。"""
    scene = {"shapes": {"dut": "mxgraph.electrical.miscellaneous.chassis"},
             "instruments": [
                 {"id": "d", "kind": "dut", "label": "D", "ports": []},
                 {"id": "a", "kind": "attenuator", "label": "A",
                  "ports": []}],
             "connections": []}
    cells = _by_id(_parse(build_testsetup_diagram_xml(scene)))
    assert ("shape=mxgraph.electrical.miscellaneous.chassis;"
            in cells["d"].get("style"))
    assert "shape=" not in cells["a"].get("style")


def test_shapes_negative_envelope(tmp_path):
    """shapes 形态违约全显式 ValueError；service 失败信封+不落产物。"""
    bad_profile = {"shapes": "rf", "instruments": [
        {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]}]}
    bad_kind_key = {"shapes": {"mixer": "mxgraph.electrical.abstract.filter"},
                    "instruments": [
        {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]}]}
    bad_shape_empty = {"shapes": {"dut": "  "}, "instruments": [
        {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]}]}
    bad_shape_type = {"shapes": {"dut": 42}, "instruments": [
        {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]}]}
    bad_type = {"shapes": 42, "instruments": [
        {"id": "a", "kind": "vna", "label": "V", "ports": ["P"]}]}
    for bad in (bad_profile, bad_kind_key, bad_shape_empty, bad_shape_type,
                bad_type):
        with pytest.raises(ValueError):
            normalize_scene(bad)
    out = tmp_path / "neg.drawio"
    result = generate_testsetup_diagram(bad_type, out)
    assert result["ok"] is False and result["errors"]
    assert not out.exists(), "失败路径不得落产物"


def test_cispr_kind_table_extension_pin():
    """扩展表拆表并入钉：KIND_TABLE 基础 10 键不动、CISPR 表逐键断言、
    合并视图=16 键无重叠。"""
    assert len(KIND_TABLE) == 10
    assert sorted(CISPR_KIND_TABLE) == [
        "anchor_plane", "antenna_mast", "battery", "current_probe",
        "emi_receiver", "load_simulator"]
    assert not set(KIND_TABLE) & set(CISPR_KIND_TABLE), "两表不得重叠键"
    assert EFFECTIVE_KIND_TABLE == {**CISPR_KIND_TABLE, **KIND_TABLE}
    assert len(EFFECTIVE_KIND_TABLE) == 16
    expected_cispr = {
        "emi_receiver": ("anal", "#ffe6cc", "#d79b00"),
        "current_probe": ("anal", "#ffe6cc", "#d79b00"),
        "anchor_plane": ("aux", "#f5f5f5", "#666666"),
        "load_simulator": ("aux", "#f5f5f5", "#666666"),
        "battery": ("aux", "#f5f5f5", "#666666"),
        "antenna_mast": ("aux", "#f5f5f5", "#666666"),
    }
    for kind, triple in expected_cispr.items():
        assert CISPR_KIND_TABLE[kind] == triple, f"CISPR kind {kind} 漂移"


def test_cispr_kinds_positive_defaults_on_card():
    """新 kind 正例：未知 kind 拒绝语义保持 + 六个新 kind 缺省 role/色板上卡。"""
    with pytest.raises(ValueError, match="kind"):
        normalize_scene({"instruments": [{"id": "a", "kind": "mixer",
                                          "label": "M", "ports": ["P"]}]})
    for kind, (role, fill, stroke) in CISPR_KIND_TABLE.items():
        scene = {"instruments": [{"id": "x", "kind": kind, "label": "X",
                                  "ports": []}]}
        card = _by_id(_parse(build_testsetup_diagram_xml(scene)))["x"]
        assert card.get("kind") == kind
        assert card.get("role") == role, kind
        assert fill in card.get("style") and stroke in card.get("style")
        assert card.get("value") == "X\n" + kind


def test_cispr25_sample_end_to_end_and_determinism(tmp_path):
    """CISPR 25 传导发射样例端到端（验收 C/D/E）：electrical 档 shape 属性
    与核对表逐字一致、新 kind 上卡、校准面标记、确定性两跑逐字节。"""
    out1 = tmp_path / "a.drawio"
    out2 = tmp_path / "b.drawio"
    r1 = generate_testsetup_diagram(SCENE_CISPR25, out1)
    r2 = generate_testsetup_diagram(SCENE_CISPR25, out2)
    assert r1["ok"] is True and r2["ok"] is True
    assert out1.read_bytes() == out2.read_bytes(), "确定性两跑逐字节"
    assert r1["n_instruments"] == 7
    assert r1["n_connections"] == 5
    assert r1["n_notes"] == 2
    root = _parse(out1.read_text(encoding="utf-8"))
    cells = _all_cells(root)
    edges = _edges(root)
    # 电气档 shape 属性与核对表逐字一致（映射 kind 恰 5 个上卡）
    verbatim = {
        "bat": "shape=mxgraph.electrical.miscellaneous.monocell_battery;",
        "lisn1": "shape=mxgraph.electrical.abstract.filter;",
        "eut": "shape=mxgraph.electrical.miscellaneous.generic_component;",
        "att1": "shape=mxgraph.electrical.resistors.attenuator;",
        "plane": "shape=mxgraph.electrical.signal_sources.signal_ground;",
    }
    for cid, frag in verbatim.items():
        assert frag in cells[cid].get("style"), f"{cid} 缺 {frag}"
    # 未映射 kind（emi_receiver/load_simulator 无忠实 stencil）保持缺省卡
    assert "shape=" not in cells["recv"].get("style")
    assert "shape=" not in cells["loadsim"].get("style")
    # 新 kind 属性承载 + kind→role 缺省查表
    assert (cells["recv"].get("kind"), cells["recv"].get("role")) == \
        ("emi_receiver", "anal")
    assert (cells["plane"].get("kind"), cells["plane"].get("role")) == \
        ("anchor_plane", "aux")
    # 连接表↔边集双射（source/target 精确=端口点 id）
    conns = SCENE_CISPR25["connections"]
    for i, conn in enumerate(conns):
        assert edges[f"conn{i}"].get("source") == conn["from"]
        assert edges[f"conn{i}"].get("target") == conn["to"]
    # 校准面标记（conn2=LISN RF 口）+ 注记锚
    assert edges["conn2"].findall("mxCell")[0].get("value") == "▎CAL"
    assert edges["note0.anchor"].get("target") == "conn2"
    assert edges["note1.anchor"].get("target") == "plane"
    # 数字原样标注（铁律 7）：9.5 dB / 3 m 逐字
    assert "RF1  9.5 dB  3 m" in edges["conn2"].get("value")
    # 纯辅助件（参考板零端口）进 warnings 不报错
    assert any("无端口" in w and "'plane'" in w
               for w in r1["warnings"])
