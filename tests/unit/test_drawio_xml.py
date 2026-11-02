"""T-O2 通用 drawio 内核钉（aurora_o，2026-11-01）。

任务书四验收：
1. 抽取门——core/link_diagram.py 改走本内核后其 26 钉零改动全绿
   （test_diagram_service.py 未改一字节；XML 逐字节 diff 证据落
   runs/aurora_o/tn_o2/）——本文件不重复其钉，只钉内核自身契约；
2. read 面——round-trip（内核写→read→结构一致 + T-O1 链路产物文件回读）；
3. 负例——坏 XML/缺 mxGraphModel（压缩页）/缺 root/缺基 cell/文件不可读
   显式 DrawioReadError；
4. 确定性——同输入两跑逐字节（构建两次/落盘两次/ET.indent 幂等）。

消费预留：T-O3 叠层/T-O4 ADS 链（read 面主消费者）/T-O6 测试连接图/
T-O8 评审标注（layers 键消费者）——一律走 core/drawio_xml.py 内核。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from rfauto.core.drawio_xml import (
    DEFAULT_PAGE_ATTRS,
    DrawioDocument,
    DrawioReadError,
    new_document,
    page_attrs,
    parse_diagram,
    read_diagram,
    write_document,
)
from rfauto.core.link_diagram import build_link_diagram_xml
from rfauto.service.diagram_service import generate_link_diagram

CHAIN = [
    {"name": "LNA", "gain_db": 20.0, "nf_db": 0.8},
    {"name": "滤波器", "gain_db": -2.0, "nf_db": 2.0},
    {"name": "Mixer", "gain_db": -7.0, "nf_db": 7.0},
]


def _doc() -> DrawioDocument:
    doc = new_document(diagram_id="doc-1", diagram_name="Page-1")
    doc.add_vertex("a", "节点A", style="rounded=0;", x=10, y=20,
                   width=100, height=50)
    doc.add_vertex("b", "", style="text;", x=200, y=20, width=80, height=30)
    doc.add_edge("e0", "", style="edgeStyle=orthogonalEdgeStyle;",
                 source="a", target="b")
    return doc


# ─── 写面：骨架结构与 drawio 语义 ───────────────────────────────────────────


class TestWriterSkeleton:
    def test_skeleton_structure(self):
        root = ET.fromstring(_doc().to_xml())
        assert root.tag == "mxfile"
        assert root.get("host") == "rfauto"
        diagrams = root.findall("diagram")
        assert len(diagrams) == 1
        assert diagrams[0].get("id") == "doc-1"
        assert diagrams[0].get("name") == "Page-1"
        model = diagrams[0].find("mxGraphModel")
        assert model is not None
        assert model.get("pageWidth") == "1169"
        mx_root = model.find("root")
        assert mx_root is not None
        cells = mx_root.findall("mxCell")
        ids = [c.get("id") for c in cells]
        assert ids[:2] == ["0", "1"]  # 基 cell 恒在前两位
        cell1 = cells[1]
        assert cell1.get("parent") == "0"
        assert set(ids[2:]) == {"a", "b", "e0"}

    def test_default_page_attrs_match_t_o1_output(self):
        # 缺省页面属性 = T-O1 link 图产出（抽取门字节面的一部分）
        root = ET.fromstring(build_link_diagram_xml(CHAIN))
        model = root.find("diagram").find("mxGraphModel")
        assert dict(model.attrib) == DEFAULT_PAGE_ATTRS
        # 键序=写出序（确定性）
        assert list(model.attrib) == list(DEFAULT_PAGE_ATTRS)

    def test_page_attrs_override_merges_over_defaults(self):
        attrs = page_attrs(pageWidth="1587", pageHeight="2245")
        assert attrs["pageWidth"] == "1587"
        assert attrs["pageHeight"] == "2245"
        assert attrs["gridSize"] == DEFAULT_PAGE_ATTRS["gridSize"]
        assert len(attrs) == len(DEFAULT_PAGE_ATTRS)  # 纯覆盖不加键
        # 缺省常量不被污染
        assert DEFAULT_PAGE_ATTRS["pageWidth"] == "1169"

    def test_custom_page_attrs_rendered(self):
        doc = new_document(diagram_id="d", diagram_name="n",
                           page=page_attrs(pageWidth="1587"))
        root = ET.fromstring(doc.to_xml())
        model = root.find("diagram").find("mxGraphModel")
        assert model.get("pageWidth") == "1587"
        assert model.get("dy") == "800"

    def test_vertex_geometry_edge_ends_semantics(self):
        root = ET.fromstring(_doc().to_xml())
        cells = {c.get("id"): c for c in root.iter("mxCell")}
        all_ids = set(cells)
        va = cells["a"]
        assert va.get("vertex") == "1" and va.get("parent") == "1"
        geom = va.find("mxGeometry")
        assert (geom.get("x"), geom.get("y"),
                geom.get("width"), geom.get("height")) == ("10", "20", "100", "50")
        assert geom.get("as") == "geometry"
        e0 = cells["e0"]
        assert e0.get("edge") == "1"
        assert e0.get("source") == "a" and e0.get("target") == "b"
        egeom = e0.find("mxGeometry")
        assert egeom.get("relative") == "1" and egeom.get("as") == "geometry"
        for e in root.iter("mxCell"):
            if e.get("edge") == "1":
                assert e.get("source") in all_ids
                assert e.get("target") in all_ids

    def test_special_chars_escaped_by_elementtree(self):
        doc = new_document(diagram_id="d", diagram_name="n")
        doc.add_vertex("v", 'A<B>&"X"漂\n第二行', style="s;", x=0, y=0,
                       width=1, height=1)
        root = ET.fromstring(doc.to_xml())
        cell = root.find("diagram").find("mxGraphModel").find("root").find(
            "mxCell[@id='v']")
        assert cell.get("value") == 'A<B>&"X"漂\n第二行'


# ─── 写面：内核守卫负例 ─────────────────────────────────────────────────────


class TestWriterGuards:
    def test_duplicate_cell_id_rejected(self):
        doc = new_document(diagram_id="d", diagram_name="n")
        doc.add_vertex("x", "v", x=0, y=0, width=1, height=1)
        with pytest.raises(ValueError, match="重复"):
            doc.add_vertex("x", "v2", x=1, y=1, width=1, height=1)
        with pytest.raises(ValueError, match="重复"):
            doc.add_edge("x", source="x", target="0")

    def test_empty_or_nonstr_ids_rejected(self):
        with pytest.raises(ValueError):
            new_document(diagram_id="  ", diagram_name="n")
        with pytest.raises(ValueError):
            new_document(diagram_id="d", diagram_name="")
        doc = new_document(diagram_id="d", diagram_name="n")
        with pytest.raises(ValueError):
            doc.add_vertex("", "v", x=0, y=0, width=1, height=1)

    def test_dangling_edge_reference_rejected_at_to_xml(self):
        doc = new_document(diagram_id="d", diagram_name="n")
        doc.add_vertex("a", "v", x=0, y=0, width=1, height=1)
        doc.add_edge("e", source="a", target="ghost")
        with pytest.raises(ValueError, match="悬空"):
            doc.to_xml()

    def test_bool_and_nonfinite_attribute_values_rejected(self):
        doc = new_document(diagram_id="d", diagram_name="n")
        with pytest.raises(ValueError, match="bool"):
            doc.add_vertex("v", "ok", x=True, y=0, width=1, height=1)
        with pytest.raises(ValueError, match="有限"):
            doc.add_vertex("v2", "ok", x=float("nan"), y=0, width=1,
                           height=1)
        with pytest.raises(ValueError, match="有限"):
            doc.add_vertex("v3", "ok", x=0, y=0, width=float("inf"),
                           height=1)


# ─── 验收④：确定性（同输入两跑逐字节 + indent 幂等 + 落盘两次同字节） ───────


class TestDeterminism:
    def test_two_builds_byte_identical(self):
        assert _doc().to_xml() == _doc().to_xml()

    def test_to_xml_idempotent_indent(self):
        doc = _doc()
        xml1 = doc.to_xml()
        xml2 = doc.to_xml()  # ET.indent 对已缩进树幂等
        assert xml1 == xml2

    def test_write_document_twice_byte_identical(self, tmp_path):
        out1 = tmp_path / "a.drawio"
        out2 = tmp_path / "b.drawio"
        write_document(_doc(), out1)
        write_document(_doc(), out2)
        assert out1.read_bytes() == out2.read_bytes()

    def test_write_document_returns_path_no_mkdir(self, tmp_path):
        out = tmp_path / "x.drawio"
        assert write_document(_doc(), out) == out
        assert out.exists()
        missing_dir = tmp_path / "no_such_dir" / "y.drawio"
        with pytest.raises(OSError):
            write_document(_doc(), missing_dir)


# ─── 验收②：read 面 round-trip ────────────────────────────────────────────


class TestReadFaceRoundTrip:
    def test_kernel_write_read_round_trip_structure_identical(self):
        xml_text = _doc().to_xml()
        result = parse_diagram(xml_text)
        assert result["n_pages"] == 1
        page = result["pages"][0]
        assert page["diagram_id"] == "doc-1"
        assert page["diagram_name"] == "Page-1"
        assert page["page"] == DEFAULT_PAGE_ATTRS
        # vertices 结构一致（id/value/style/geometry 原样字符串）
        assert [v["id"] for v in page["vertices"]] == ["a", "b"]
        assert page["vertices"][0]["value"] == "节点A"
        assert page["vertices"][0]["style"] == "rounded=0;"
        assert page["vertices"][0]["geometry"] == {
            "x": "10", "y": "20", "width": "100", "height": "50"}
        assert page["vertices"][1]["geometry"] == {
            "x": "200", "y": "20", "width": "80", "height": "30"}
        # edges 结构一致（source/target 原样）
        assert [e["id"] for e in page["edges"]] == ["e0"]
        assert page["edges"][0]["source"] == "a"
        assert page["edges"][0]["target"] == "b"
        # 基 cell 1 = 唯一图层（v1 无自定义层）
        assert [lay["id"] for lay in page["layers"]] == ["1"]

    def test_t_o1_link_product_file_round_trip(self, tmp_path):
        # T-O1 链路产物（generate_link_diagram 落盘）→ read_diagram 回读
        out = tmp_path / "link.drawio"
        assert generate_link_diagram(CHAIN, out, title="接收前端")["ok"] is True
        result = read_diagram(out)
        page = result["pages"][0]
        assert page["diagram_id"] == "link-diagram"
        assert page["diagram_name"] == "RF Link"
        assert page["page"] == DEFAULT_PAGE_ATTRS
        vids = {v["id"] for v in page["vertices"]}
        assert vids == {"title", "stage0", "stage1", "stage2", "cascade"}
        title = next(v for v in page["vertices"] if v["id"] == "title")
        assert title["value"] == "接收前端"
        assert title["geometry"]["width"] == "420"
        # 图内数字回读 == 内核单源文本（算画同源 read 侧对拍）
        stage0 = next(v for v in page["vertices"] if v["id"] == "stage0")
        assert "G=20.00 dB  NF=0.80 dB" in stage0["value"]
        cascade = next(v for v in page["vertices"] if v["id"] == "cascade")
        assert "ΣG=11.00 dB" in cascade["value"]
        # 连线链 = 信号流向：stage_i→stage_{i+1} + 末级→cascade
        pairs = [(e["source"], e["target"]) for e in page["edges"]]
        assert ("stage0", "stage1") in pairs
        assert ("stage2", "cascade") in pairs
        assert len(pairs) == 3

    def test_extra_attrs_round_trip_for_param_annotation(self):
        # T-O4 预留：自定义参数标注（type/param_value/unit/param_key）写→读
        # 逐键一致。注：mxCell 的 value=标签文本属结构性键（extra_attrs 禁用
        # "value" 做参数名——参数值用 param_value 键，冲突守卫显式拦截）
        doc = new_document(diagram_id="d", diagram_name="n")
        doc.add_vertex("tlin1", "TLIN", style="rounded=0;", x=0, y=0,
                       width=60, height=24,
                       extra_attrs={"type": "TLIN", "param_value": "50",
                                    "unit": "Ohm", "param_key": "z0"})
        doc.add_edge("e", "", source="tlin1", target="1",
                     extra_attrs={"note": "级间连线"})
        page = parse_diagram(doc.to_xml())["pages"][0]
        vertex = page["vertices"][0]
        assert vertex["attrs"]["type"] == "TLIN"
        assert vertex["attrs"]["param_key"] == "z0"
        assert vertex["attrs"]["param_value"] == "50"
        assert vertex["attrs"]["unit"] == "Ohm"
        assert vertex["value"] == "TLIN"  # 标签与参数键不混淆
        assert page["edges"][0]["attrs"]["note"] == "级间连线"

    def test_extra_attrs_fixed_key_conflict_rejected(self):
        doc = new_document(diagram_id="d", diagram_name="n")
        with pytest.raises(ValueError, match="冲突"):
            doc.add_vertex("v", "x", x=0, y=0, width=1, height=1,
                           extra_attrs={"vertex": "0"})
        doc.add_vertex("v2", "x", x=0, y=0, width=1, height=1)
        with pytest.raises(ValueError, match="冲突"):
            doc.add_edge("e", source="v2", target="1",
                         extra_attrs={"source": "1"})


class TestLayerFace:
    def test_add_layer_and_assign_parent(self):
        # T-O8 预留：底图层 locked + 标注层；图元按 parent 挂层
        doc = new_document(diagram_id="d", diagram_name="n")
        doc.add_layer("base", name="底图", locked="1")
        doc.add_layer("notes", name="标注层")
        doc.add_vertex("mark", "标注", style="text;", x=1, y=2, width=3,
                       height=4, parent="notes")
        root = ET.fromstring(doc.to_xml())
        cells = {c.get("id"): c for c in root.iter("mxCell")}
        assert cells["base"].get("parent") == "0"
        assert cells["base"].get("locked") == "1"
        assert cells["notes"].get("locked") is None
        assert cells["mark"].get("parent") == "notes"
        # read 面 layers 键：基 cell 1 + 两个自定义层（locked 原样）
        page = parse_diagram(doc.to_xml())["pages"][0]
        lay = {item["id"]: item for item in page["layers"]}
        assert set(lay) == {"1", "base", "notes"}
        assert lay["base"]["name"] == "底图"
        assert lay["base"]["locked"] == "1"
        assert lay["notes"]["locked"] is None
        # 标注层图元归位（parent 挂层）
        assert page["vertices"][0]["parent"] == "notes"


class TestReadFaceMultiPage:
    def test_two_diagram_mxfile_parsed(self):
        mxfile = ET.Element("mxfile", {"host": "rfauto"})
        for pid in ("p1", "p2"):
            diagram = ET.SubElement(mxfile, "diagram",
                                    {"id": pid, "name": pid.upper()})
            model = ET.SubElement(diagram, "mxGraphModel", {})
            mx_root = ET.SubElement(model, "root")
            ET.SubElement(mx_root, "mxCell", {"id": "0"})
            ET.SubElement(mx_root, "mxCell", {"id": "1", "parent": "0"})
        xml_text = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                    + ET.tostring(mxfile, encoding="unicode"))
        result = parse_diagram(xml_text)
        assert result["n_pages"] == 2
        assert [p["diagram_id"] for p in result["pages"]] == ["p1", "p2"]
        assert result["pages"][0]["vertices"] == []
        assert result["pages"][0]["edges"] == []


# ─── 验收③：read 面负例（显式 DrawioReadError，不静默） ────────────────────


class TestReadFaceNegatives:
    def test_bad_xml_raises(self):
        with pytest.raises(DrawioReadError, match="解析失败"):
            parse_diagram("<mxfile><diagram>")

    def test_non_mxfile_root_raises(self):
        with pytest.raises(DrawioReadError, match="mxfile"):
            parse_diagram("<?xml version='1.0'?><html><body/></html>")

    def test_missing_diagram_raises(self):
        with pytest.raises(DrawioReadError, match="diagram"):
            parse_diagram("<?xml version='1.0'?><mxfile host='rfauto'/>")

    def test_missing_mxgraph_model_compressed_page_raises(self):
        # 压缩页（diagram 内 base64 文本、无 mxGraphModel）显式不支持
        compressed = ("<?xml version='1.0'?><mxfile host='rfauto'>"
                      "<diagram id='d' name='n'>dVZLb9MwEP4+</diagram>"
                      "</mxfile>")
        with pytest.raises(DrawioReadError, match="mxGraphModel"):
            parse_diagram(compressed)

    def test_missing_root_raises(self):
        xml_text = ("<?xml version='1.0'?><mxfile host='rfauto'>"
                    "<diagram id='d' name='n'><mxGraphModel/></diagram>"
                    "</mxfile>")
        with pytest.raises(DrawioReadError, match="root"):
            parse_diagram(xml_text)

    def test_missing_base_cell_zero_raises(self):
        xml_text = ("<?xml version='1.0'?><mxfile><diagram id='d' name='n'>"
                    "<mxGraphModel><root>"
                    "<mxCell id='1' parent='0'/></root></mxGraphModel>"
                    "</diagram></mxfile>")
        with pytest.raises(DrawioReadError, match="id=0"):
            parse_diagram(xml_text)

    def test_non_string_input_raises(self):
        with pytest.raises(DrawioReadError, match="字符串"):
            parse_diagram(b"<mxfile/>")  # type: ignore[arg-type]

    def test_read_diagram_missing_file_raises(self, tmp_path):
        with pytest.raises(DrawioReadError, match="读取失败"):
            read_diagram(tmp_path / "no_such.drawio")

    def test_read_diagram_non_utf8_file_raises(self, tmp_path):
        out = tmp_path / "bin.drawio"
        out.write_bytes(b"\xff\xfe\x00binary")
        with pytest.raises(DrawioReadError, match="读取失败"):
            read_diagram(out)

    def test_drawio_read_error_is_valueerror(self):
        # service 层错误信封（except ValueError）可直接捕获
        assert issubclass(DrawioReadError, ValueError)
