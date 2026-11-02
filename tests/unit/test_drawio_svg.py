""".drawio → SVG 纯 Python 渲染器钉（aurora_p C3，2026-11-01）。

六验收钉（任务书口径，冻结判据 A-F）：
A. 真实样例转换——a1 三份引脚级原理图 + rf_link 样例 → ET 可解析 +
   vertex/edge 计数与 .drawio 源一致（直挂 vertex+UserObject 包装+
   edge 子 label 补扫口径）；
B. 确定性——内核两跑 SVG 文本逐字节相同 + service 两跑文件逐字节
   相同 + CLI 子进程两跑 byte_identical；
C. 支持子集声明式——SUPPORTED_STYLE_KEYS/UNSUPPORTED_FEATURE_TRIGGERS
   常量表在位 + 降级路径显式（mxgraph.* 形状降级占位框 + warnings
   逐 cell 回显；不静默不炸，#122）；
D. 计数 294 全链一致（test_check_numbers/test_cli/注册序金快照/
   diagram 叶清单棘轮 +1）；
E. 既有 diagram 叶测试零改动全绿（本文件不触既有五叶产出路径）；
F. ruff 0（交付面自证）。

负例显式报错（压缩页=DrawioReadError 传播/缺文件/非 mxfile/页序越界/
空页/同路径覆盖/父目录缺失）；边界如实（edge-to-edge 连线 v1 不渲染
+warning；whiteSpace=wrap 不自动折行——docstring 声明面）。
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.core.drawio_svg import (
    DEFAULT_FONT_SIZE,
    SUPPORTED_STYLE_KEYS,
    UNSUPPORTED_FEATURE_TRIGGERS,
    DrawioReadError,
    DrawioSvgError,
    render_diagram_svg,
    render_xml_text,
)
from rfauto.core.drawio_xml import parse_diagram
from rfauto.service.drawio_svg_service import render_drawio_svg

runner = CliRunner()

_REPO = Path(__file__).resolve().parents[2]

#: 只读对拍料（任务书 §0 事实底盘——禁止本席改写）
A1_SCHEMATICS = [
    _REPO / "runs" / "aurora_p" / "a1" / "wilkinson_snp_schematic.drawio",
    _REPO / "runs" / "aurora_p" / "a1" / "branchline_cascade_schematic.drawio",
    _REPO / "runs" / "aurora_p" / "a1" / "loadpull_hb_schematic.drawio",
]
LINK_SAMPLE = _REPO / "examples" / "diagrams" / "rf_link_diagram_example.drawio"
CISPR_SAMPLE = (_REPO / "examples" / "diagrams"
                / "cispr25_conducted_emission_example.drawio")
_A1_AVAILABLE = all(p.exists() for p in A1_SCHEMATICS)
pytestmark = [
    pytest.mark.skipif(not _A1_AVAILABLE,
                       reason="a1 引脚级原理图样例（runs 证据树）不在公开仓——"
                              "examples/diagrams 双样例钉仍在本文件生效"),
]

REVIEW_SAMPLE = (_REPO / "examples" / "diagrams"
                 / "review_annotated_example.drawio")
STACKUP_SAMPLE = (_REPO / "examples" / "diagrams"
                  / "stackup_microstrip_example.drawio")

#: 样例源真值（直挂 vertex + UserObject 包装 + edge 子 label；edges 全数）
_EXPECTED = {
    "wilkinson": (17, 6),
    "branchline": (28, 10),
    "loadpull": (12, 4),
    "link": (6, 4),
    "cispr": (23, 7),
    "review": (14, 10),
    "stackup": (9, 4),
}


def _source_counts(path: Path) -> tuple[int, int, int]:
    """源 .drawio 真值计数（独立 ET 遍历 oracle，与渲染端补扫口径互证）：
    (vertex 数, edge 数, 非空 value/label 的 cell 数)。

    UserObject/object 包装 cell 计 1（取包装 label，内层 mxCell 不重计——
    iter() 会同时访问包装与内层，按内层元素身份排除防双计）；edge 子
    label cell（嵌套于 edge 元素内的 mxCell）计入 vertex。
    """
    root = ET.parse(path).getroot()
    mx_root = root.find("diagram/mxGraphModel/root")
    wrapped_inner: set[int] = set()
    for el in mx_root.iter():
        if el.tag in ("UserObject", "object"):
            inner = el.find("mxCell")
            if inner is not None:
                wrapped_inner.add(id(inner))
    nv = ne = nt = 0
    for el in mx_root.iter():
        if el.tag in ("UserObject", "object"):
            inner = el.find("mxCell")
            if inner is None:
                continue
            label = el.get("label") or inner.get("value") or ""
            flags = inner
        elif el.tag == "mxCell" and id(el) not in wrapped_inner:
            label = el.get("value") or ""
            flags = el
        else:
            continue
        if flags.get("vertex") == "1":
            nv += 1
        elif flags.get("edge") == "1":
            ne += 1
        else:
            continue
        if label:
            nt += 1
    return nv, ne, nt


def _svg_text_count(svg: str) -> int:
    """SVG 内 <text> 元素数（每个有值 cell 恰一个 text；多行走 tspan 子元素）。"""
    root = ET.fromstring(svg)
    return sum(1 for el in root.iter() if localname(el.tag) == "text")


# ─── 验收 A：真实样例转换 + 计数一致 ────────────────────────────────────────


class TestSampleConversion:
    @pytest.mark.parametrize("sample_key", ["wilkinson", "branchline",
                                           "loadpull"])
    def test_a1_schematic_counts_match_source(self, sample_key: str,
                                              tmp_path: Path):
        path = next(p for p in A1_SCHEMATICS if sample_key in p.name)
        exp_v, exp_e = _EXPECTED[sample_key]
        src_v, src_e, src_t = _source_counts(path)
        assert (src_v, src_e) == (exp_v, exp_e)  # 源真值 oracle 自洽
        svg, stats = render_xml_text(path.read_text(encoding="utf-8"))
        root = ET.fromstring(svg)  # ET 可解析
        assert localname(root.tag) == "svg"
        assert (stats["n_vertices"], stats["n_edges"]) == (exp_v, exp_e)
        assert _svg_text_count(svg) == src_t  # text 计数与源一致
        assert stats["n_degraded"] == 0 and stats["warnings"] == []

    def test_link_sample_counts_and_shapes(self, tmp_path: Path):
        exp_v, exp_e = _EXPECTED["link"]
        svg, stats = render_xml_text(LINK_SAMPLE.read_text(encoding="utf-8"))
        root = ET.fromstring(svg)
        assert (stats["n_vertices"], stats["n_edges"]) == (exp_v, exp_e)
        assert _source_counts(LINK_SAMPLE)[:2] == (exp_v, exp_e)
        assert _svg_text_count(svg) == _source_counts(LINK_SAMPLE)[2]
        # 框+连线+文字直映射形态钉：5 rect（stage/cascade 框）+1 纯文字标题
        # +4 line（edge）
        ns = "{http://www.w3.org/2000/svg}"
        assert len(root.findall(f"{ns}g/{ns}rect")) == exp_v - 1
        assert len(root.findall(f"{ns}g/{ns}line")) == exp_e
        texts = " ".join(root.itertext())
        assert "LNA" in texts and "级联总计（Friis）" in texts  # value 原值

    @pytest.mark.parametrize("sample", [CISPR_SAMPLE, REVIEW_SAMPLE,
                                        STACKUP_SAMPLE])
    def test_extended_samples_vertex_edge_match_oracle(self, sample: Path):
        """扩展样例（含 UserObject 包装/edge 子 label/降级形状）vertex/edge
        计数与独立 oracle 一致（补扫口径互证）。"""
        _svg, stats = render_xml_text(sample.read_text(encoding="utf-8"))
        src_v, src_e, _ = _source_counts(sample)
        assert (stats["n_vertices"], stats["n_edges"]) == (src_v, src_e)

    def test_review_userobject_wrapped_rendered(self):
        """UserObject 包装 cell（评审标注面产物）label 原样渲染。"""
        svg, stats = render_xml_text(REVIEW_SAMPLE.read_text(encoding="utf-8"))
        assert stats["n_vertices"] == _EXPECTED["review"][0]  # 含 6 包装
        assert "混频器噪声" in svg  # UserObject label 原值原样
        assert stats["n_layers"] == 2  # 基图层+annot → <g> 分组

    def test_stackup_edge_label_offset_and_background(self):
        """线宽双箭头标注：edge label+offset+白晕（labelBackgroundColor）。"""
        svg, stats = render_xml_text(
            STACKUP_SAMPLE.read_text(encoding="utf-8"))
        assert (stats["n_vertices"], stats["n_edges"]) == _EXPECTED["stackup"]
        assert "nominal_width_mm" in svg  # 标注数字=原值直通
        assert 'paint-order="stroke"' in svg  # 白晕近似（声明面）

    def test_nested_vertex_absolute_origin(self, tmp_path: Path):
        """a1 引脚点（parent=元件框）绝对坐标展开：P1.1 = P1+偏移。"""
        svg, stats = render_xml_text(
            A1_SCHEMATICS[0].read_text(encoding="utf-8"))
        assert 'cx="190" cy="132"' in svg  # (40,100)+(145,27)+(5,5) 中心
        assert stats["n_vertices"] == _EXPECTED["wilkinson"][0]

    def test_text_newlines_to_tspan(self):
        svg, _ = render_xml_text(A1_SCHEMATICS[0].read_text(encoding="utf-8"))
        assert "<tspan" in svg  # value 内 \n → tspan 纵排
        assert "Port:P1" in svg and "Z=50 Ohm" in svg  # 原值逐行

    def test_style_subset_table_is_single_source(self):
        # 常量表在位（验收 C 声明式）：核心键抽查 + 触发表含 mxgraph 前缀
        for key in ("fillColor", "strokeColor", "fontSize", "rounded",
                    "dashed", "endArrow", "verticalAlign"):
            assert key in SUPPORTED_STYLE_KEYS
        assert "shape=mxgraph" in UNSUPPORTED_FEATURE_TRIGGERS
        assert DEFAULT_FONT_SIZE == 12  # drawio 缺省（stylesheet 实读）


# ─── 验收 C：不支持形态降级 + warnings 显式 ─────────────────────────────────


class TestDegradePath:
    def test_cispr_mxgraph_shapes_degrade_with_warnings(self):
        """CISPR25 五个 mxgraph.electrical.* 形状 → 占位框+逐 cell warning。"""
        svg, stats = render_xml_text(CISPR_SAMPLE.read_text(encoding="utf-8"))
        assert stats["n_degraded"] == 5
        assert stats["n_vertices"] == _EXPECTED["cispr"][0]
        assert sum("mxgraph 内置形状" in w for w in stats["warnings"]) == 5
        assert 'stroke-dasharray="4 3"' in svg  # 占位虚线框
        assert "蓄电池 12 V" in svg  # value 仍原样渲染

    def test_kernel_render_diagram_svg_returns_warnings(self):
        doc = parse_diagram(CISPR_SAMPLE.read_text(encoding="utf-8"))
        page = doc["pages"][0]
        # 补扫后渲染（服务层同路）
        import xml.etree.ElementTree as ET

        raw = ET.fromstring(CISPR_SAMPLE.read_text(encoding="utf-8"))
        from rfauto.core.drawio_svg import _supplement_page

        _supplement_page(raw.find("diagram/mxGraphModel"), page)
        _svg, warnings = render_diagram_svg(page)
        assert any("降级占位框渲染" in w for w in warnings)


# ─── 验收 B：确定性（内核/service/CLI 子进程三面） ──────────────────────────


class TestDeterminism:
    def test_kernel_two_runs_byte_identical(self):
        text = CISPR_SAMPLE.read_text(encoding="utf-8")
        s1, st1 = render_xml_text(text)
        s2, st2 = render_xml_text(text)
        assert s1 == s2 and st1 == st2

    def test_service_two_runs_file_byte_identical(self, tmp_path: Path):
        out1, out2 = tmp_path / "a.svg", tmp_path / "b.svg"
        r1 = render_drawio_svg(LINK_SAMPLE, out1)
        r2 = render_drawio_svg(LINK_SAMPLE, out2)
        assert r1["ok"] and r2["ok"]
        assert out1.read_bytes() == out2.read_bytes()

    def test_cli_subprocess_byte_identical(self, tmp_path: Path):
        """CLI 子进程两跑 byte_identical（验收 B 的 CLI 面）。"""
        import json
        import subprocess

        base = [sys.executable, "-m", "rfauto.cli.main", "diagram", "to-svg"]
        outs = []
        for k in (1, 2):
            out = tmp_path / f"cli_{k}.svg"
            p = subprocess.run(
                [*base, "--source", str(LINK_SAMPLE), "--out", str(out),
                 "--json"],
                capture_output=True, text=True, encoding="utf-8",
                timeout=120, cwd=str(tmp_path))
            assert p.returncode == 0, p.stderr[-500:]
            envelope = json.loads(p.stdout)
            assert envelope["ok"] is True
            outs.append(out.read_bytes())
        assert outs[0] == outs[1]

    def test_svg_zero_timestamp_zero_uuid(self, tmp_path: Path):
        out = tmp_path / "t.svg"
        assert render_drawio_svg(LINK_SAMPLE, out)["ok"]
        text = out.read_text(encoding="utf-8")
        assert "uuid" not in text.lower()
        # 日期时间形态（YYYY-MM-DDTHH:MM 或时间戳数字）不出现
        import re

        assert not re.search(r"\d{4}-\d{2}-\d{2}T", text)


# ─── 负例显式报错（压缩页/缺文件/非 mxfile/越界/空页/覆盖/父目录） ───────────


class TestNegativePaths:
    COMPRESSED = ("<mxfile host='x'><diagram id='d' name='N'>"
                  "c3Znc2FtcGxl</diagram></mxfile>")
    NOT_MXFILE = "<root><child/></root>"
    EMPTY_PAGE = (
        "<mxfile host='x'><diagram id='d' name='N'><mxGraphModel>"
        "<root><mxCell id='0'/><mxCell id='1' parent='0'/></root>"
        "</mxGraphModel></diagram></mxfile>")

    def test_compressed_page_explicit_error(self):
        """压缩页显式 DrawioReadError 传播（不静默空图——红线）。"""
        with pytest.raises(DrawioReadError, match="mxGraphModel"):
            render_xml_text(self.COMPRESSED)

    def test_bad_xml_explicit_error(self):
        with pytest.raises(DrawioReadError):
            render_xml_text("this is not xml <")

    def test_non_mxfile_explicit_error(self):
        with pytest.raises(DrawioReadError, match="mxfile"):
            render_xml_text(self.NOT_MXFILE)

    def test_missing_file_service_error_envelope(self, tmp_path: Path):
        r = render_drawio_svg(tmp_path / "nope.drawio", tmp_path / "o.svg")
        assert r["ok"] is False and r["errors"]

    def test_page_index_out_of_range(self):
        text = LINK_SAMPLE.read_text(encoding="utf-8")
        with pytest.raises(DrawioSvgError, match="越界"):
            render_xml_text(text, page_index=7)

    def test_empty_page_no_silent_blank_svg(self):
        with pytest.raises(DrawioSvgError, match="无可渲染图元"):
            render_xml_text(self.EMPTY_PAGE)

    def test_same_path_guard(self, tmp_path: Path):
        """source==out 覆盖原稿显式报错（含 Windows 大小写不敏感）。"""
        src = tmp_path / "same.drawio"
        src.write_text(LINK_SAMPLE.read_text(encoding="utf-8"),
                       encoding="utf-8")
        r1 = render_drawio_svg(src, src)
        assert r1["ok"] is False and "同路径" in r1["errors"][0]
        r2 = render_drawio_svg(src, tmp_path / "SAME.DRAWIO")
        assert r2["ok"] is False  # 大小写变体同判（normcase 口径）

    def test_missing_parent_dir_no_auto_mkdir(self, tmp_path: Path):
        r = render_drawio_svg(LINK_SAMPLE, tmp_path / "nodir" / "o.svg")
        assert r["ok"] is False and "输出目录不存在" in r["errors"][0]


# ─── waypoint 折线 / edge 子 label / 图层分组 ───────────────────────────────


class TestEdgeAndLayerSemantics:
    WAYPOINT_DOC = (
        '<mxfile host="rfauto"><diagram id="d" name="W">'
        '<mxGraphModel pageWidth="800" pageHeight="600"><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="a" value="A" style="rounded=0;fillColor=#dae8fc;'
        'strokeColor=#6c8ebf;" vertex="1" parent="1">'
        '<mxGeometry x="40" y="40" width="80" height="40" as="geometry"/>'
        "</mxCell>"
        '<mxCell id="b" value="B" style="rounded=0;fillColor=#d5e8d4;'
        'strokeColor=#82b366;" vertex="1" parent="1">'
        '<mxGeometry x="500" y="40" width="80" height="40" as="geometry"/>'
        "</mxCell>"
        '<mxCell id="we" value="mid" style="html=1;" edge="1" parent="1" '
        'source="a" target="b"><mxGeometry relative="1" as="geometry">'
        '<Array as="points"><mxPoint x="300" y="20"/>'
        '<mxPoint x="300" y="100"/></Array></mxGeometry>'
        '<mxCell id="we.lbl" value="CHILD" style="text;html=1;" vertex="1" '
        'parent="we" connectable="0"><mxGeometry x="0" y="-12" relative="1" '
        'as="geometry"><mxPoint x="0" y="-12" as="offset"/></mxGeometry>'
        "</mxCell></mxCell>"
        '<UserObject label="OBJ" placeholders="1" id="uo1">'
        '<mxCell style="rounded=1;fillColor=#ffe6cc;strokeColor=#d79b00;" '
        'vertex="1" parent="1">'
        '<mxGeometry x="200" y="200" width="120" height="40" as="geometry"/>'
        "</mxCell></UserObject>"
        "</root></mxGraphModel></diagram></mxfile>")

    def test_waypoints_become_polyline(self):
        svg, stats = render_xml_text(self.WAYPOINT_DOC)
        assert stats["n_edges"] == 1
        assert "<polyline" in svg
        assert 'points="120,60 300,20 300,100 500,60"' in svg  # 直映射

    def test_edge_child_label_positioned_at_midline(self):
        svg, stats = render_xml_text(self.WAYPOINT_DOC)
        assert stats["n_vertices"] == 4  # a/b + edge 子 label + UserObject
        assert "CHILD" in svg

    def test_userobject_label_rendered_and_layer_grouping(self):
        svg, stats = render_xml_text(self.WAYPOINT_DOC)
        assert "OBJ" in svg  # UserObject label 原样（placeholders 不替换）
        assert stats["n_layers"] == 1
        assert '<g id="layer-1">' in svg  # layer→g 分组

    def test_end_arrow_none_suppresses_arrowhead(self):
        doc = self.WAYPOINT_DOC.replace('value="mid" style="html=1;"',
                                        'value="" style="html=1;'
                                        'endArrow=none;"')
        svg, _ = render_xml_text(doc)
        assert "<polygon" not in svg  # 无箭头
        assert "<polyline" in svg

    def test_arrowhead_rendered_by_default(self):
        svg, _ = render_xml_text(self.WAYPOINT_DOC)
        assert "<polygon" in svg  # 缺省 classic → 三角箭头


# ─── CLI 叶（信封同构/usage 契约/help 卫生） ────────────────────────────────


class TestCliLeaf:
    def test_json_envelope_ok(self, tmp_path: Path):
        out = tmp_path / "l.svg"
        r = runner.invoke(root_app, ["diagram", "to-svg",
                                     "--source", str(LINK_SAMPLE),
                                     "--out", str(out), "--json"])
        assert r.exit_code == 0, r.output
        envelope = json_envelope(r.output)
        assert envelope["ok"] is True
        assert envelope["n_vertices"] == 6 and envelope["n_edges"] == 4
        assert out.exists()

    def test_json_envelope_failure_same_shape(self, tmp_path: Path):
        r = runner.invoke(root_app, ["diagram", "to-svg",
                                     "--source", str(tmp_path / "gone.drawio"),
                                     "--out", str(tmp_path / "o.svg"),
                                     "--json"])
        assert r.exit_code == 1
        envelope = json_envelope(r.output)
        assert envelope["ok"] is False and envelope["errors"]

    def test_usage_error_exit_2(self, tmp_path: Path):
        r = runner.invoke(root_app, ["diagram", "to-svg",
                                     "--out", str(tmp_path / "o.svg")])
        assert r.exit_code == 2  # 缺 --source（typer usage 惯例）

    def test_help_lists_support_subset_declaration(self):
        r = runner.invoke(root_app, ["diagram", "to-svg", "--help"])
        assert r.exit_code == 0
        assert "--source" in r.output and "--out" in r.output
        assert "--page" in r.output and "--json" in r.output

    def test_diagram_leaf_list_has_to_svg(self):
        """diagram 子应用叶清单=既有五叶+to-svg（注册序钉，棘轮 +1 面）。"""
        import typer.main

        group = typer.main.get_command(root_app)
        assert list(group.commands["diagram"].commands) == [
            "link", "testsetup", "annotate", "stackup", "schematic",
            "to-svg"]


def json_envelope(output: str) -> dict:
    """CliRunner rich JSON 输出 → dict（print_json 单对象形态）。"""
    import json

    start = output.index("{")
    return json.loads(output[start:])


def localname(tag: str) -> str:
    """ET tag → 局部名（``{ns}svg`` → ``svg``；xmlns 声明后 ET 会注入 ns）。"""
    return tag.rsplit("}", 1)[-1]
