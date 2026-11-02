"""T-O8 评审标注双层 .drawio 生成器钉（aurora_o，2026-11-01）。

六验收钉（任务书口径；形态规格单源
runs/aurora_o/design_specs/T-O8_ANNOTATION_SPEC.md——本测试逐钉对齐）：
1. A 族层结构——T-O1 样例 .drawio 底图：原 cells 逐字节不动（底图零改动
   生命线，钉 2）+ locked="1" 层级 + annot 层定义在 id=1 之后（层序=渲染
   序）+ 标注三件组 parent=="annot" 形态断言；
2. B 族——外部 PNG base64 底图（style 五旗标 movable=0 等 + data URI 无
   ``;base64`` 分号陷阱钉）；
3. 优先级三色映射钉（high=#f8cecc/#b85450 等 spec 常量表逐位）；
4. target 存在性校验防指错对象（负例）；形态 B target 忽略+warnings；
5. 确定性=同输入两跑逐字节；标注表序（i=表序非 id 字典序）；
6. 既有路径零改动——内核/服务既有消费面（drawio_xml/link/diagram）零触碰，
   本文件零改既有测试；写面=只读 source、只写 out_path（hash+mtime 双证）。

aurora_p A4 增量段（多评审人合并，2026-11-01）：merge_annotation_plans/
merge_annotate_diagram——署名逐键+逐评审人计数（验收 A）、底图零改动
ET 结构签名逐 cell 全等（验收 B）、两跑逐字节+入参顺序无关（验收 C）、
跨文件输入 id 冲突=合并表序全局重编号+an_id 原样+逐 id warnings、负例
显式（验收 E）。既有单评审人路径零变化=本文件既有用例零改动全绿（验收 D）。
"""

from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.core.review_annotation import (
    ANNOT_LAYER_ID,
    CARD_ID_PREFIX,
    CIRCLE_ID_PREFIX,
    CROSS_EDGE_ID_PREFIX,
    PRIORITY_TABLE,
    REVIEWER_PALETTE,
    TARGET_EDGE_ID_PREFIX,
    build_annotation_plan,
    merge_annotation_plans,
    normalize_annotations,
)
from rfauto.service.diagram_annotation_service import (
    annotate_diagram,
    merge_annotate_diagram,
)

_src_dir = Path(__file__).resolve().parents[2] / "src"
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

EXAMPLE = (Path(__file__).resolve().parents[2]
           / "examples" / "diagrams" / "rf_link_diagram_example.drawio")

#: 端到端标注表（高中低各一、一条带 target=stage2——spec 钉 11 场景）
ANNS_3 = {
    "summary": "Wilkinson 布局评审：隔离电阻位置偏近输出臂",
    "annotations": [
        {"id": "a1", "region": {"x": 300, "y": 60, "w": 190, "h": 76},
         "priority": "high", "label": "R_iso 位置",
         "comment": "隔离电阻距输出臂过近，建议左移 5 mm 后复仿真",
         "target": "stage2"},
        {"id": "a2", "region": {"x": 40, "y": 60, "w": 180, "h": 72},
         "priority": "medium", "label": "LNA 增益",
         "comment": "建议核对该级 NF 余量"},
        {"id": "a3", "region": {"x": 760, "y": 60, "w": 180, "h": 72},
         "priority": "low", "label": "中频放大",
         "comment": "下版考虑提高增益"},
    ],
}


# ─── 合成图片工具（头解析只需合法头字节，无需真图片） ────────────────────────


def _png_bytes(w: int, h: int) -> bytes:
    """最小合法 PNG（magic+IHDR+IDAT+IEND；本仓头解析只读 IHDR 尺寸段）。"""
    import struct
    import zlib

    def chunk(typ: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", b"x") + chunk(b"IEND", b""))


def _jpeg_bytes(w: int, h: int) -> bytes:
    """最小合法 JPEG 头（SOI+APP0[JFIF]+SOF0+EOI；头解析只扫 SOF 段尺寸；
    段长字段与实际段长一致——解析器按段长跳段）。"""
    import struct

    app0 = (b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00"
            + b"\x01\x02\x00\x00\x01\x00\x01\x00\x00")  # 段长 16=2+14 载荷
    sof0 = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
            + struct.pack(">HH", h, w) + b"\x03"
            + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01")
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


@pytest.fixture
def png_path(tmp_path: Path) -> Path:
    p = tmp_path / "shot.png"
    p.write_bytes(_png_bytes(1280, 720))
    return p


@pytest.fixture
def jpeg_path(tmp_path: Path) -> Path:
    p = tmp_path / "shot.jpg"
    p.write_bytes(_jpeg_bytes(640, 480))
    return p


# ─── 解析辅助 ────────────────────────────────────────────────────────────────


def _parse(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text)  # 结构非法即抛 ParseError=红


def _mxroot(xml_text: str) -> ET.Element:
    mxr = _parse(xml_text).find("diagram/mxGraphModel/root")
    assert mxr is not None
    return mxr


def _by_id(mx_root: ET.Element, cell_id: str) -> ET.Element:
    hits = [el for el in mx_root.iter() if el.get("id") == cell_id]
    assert len(hits) == 1, f"id {cell_id!r} 命中 {len(hits)} 个（应恰 1）"
    return hits[0]


def _elem_sig(el: ET.Element):
    """cell 结构签名（tag+属性全集+子树递归——钉 2 底图零改动的对拍单位）。"""
    return (el.tag, dict(el.attrib),
            tuple(_elem_sig(c) for c in list(el)))


# ─── 验收①：A 族层结构 + 底图零改动（生命线） ───────────────────────────────


def test_form_a_layer_structure_and_render_order():
    """钉 1：id=1 带 locked="1"；annot 层 parent=0 无 vertex/edge 且定义在
    id=1 之后（层序=渲染序）；三件组 parent=="annot"。"""
    plan = build_annotation_plan(EXAMPLE, ANNS_3)
    assert plan["form"] == "A"
    mxr = _mxroot(plan["xml"])
    cells = mxr.findall("mxCell")
    ids = [c.get("id") for c in cells]
    assert ids[:2] == ["0", "1"]  # 基 cell 惯例
    cell1 = _by_id(mxr, "1")
    assert cell1.get("locked") == "1"
    assert cell1.get("parent") == "0"
    assert cell1.get("value")  # 层名（空 value 补名）
    layer = _by_id(mxr, ANNOT_LAYER_ID)
    assert layer.tag == "mxCell"
    assert layer.get("parent") == "0"
    assert layer.get("value") == "评审标注"
    assert layer.get("vertex") is None and layer.get("edge") is None
    assert ids.index(ANNOT_LAYER_ID) > ids.index("1")  # 定义在后=渲染在上
    # 标注子元素全部挂 annot 层（UserObject 的内层 mxCell 同样）
    for el in mxr.iter("mxCell"):
        pid = el.get("parent") or ""
        cid = el.get("id") or ""
        if cid in {"0", "1", ANNOT_LAYER_ID} or pid == "0":
            continue
        if el in list(mxr):  # 底图直接子 cell（parent=1）不属标注层
            continue
        assert pid == ANNOT_LAYER_ID, f"{cid} parent={pid!r}"


def test_form_a_base_cells_untouched():
    """钉 2（生命线）：原 cell 集合（除 id=1）逐 cell (tag, attrib, 子树)
    全等；id=1 仅新增 locked/value 两键。"""
    src_tree = ET.fromstring(EXAMPLE.read_text(encoding="utf-8"))
    plan = build_annotation_plan(EXAMPLE, ANNS_3)
    out_tree = _parse(plan["xml"])
    src_root = src_tree.find("diagram/mxGraphModel/root")
    out_root = out_tree.find("diagram/mxGraphModel/root")
    assert src_root is not None and out_root is not None
    src_cells = {c.get("id"): c for c in src_root}
    out_orig = {}
    for c in out_root:
        cid = c.get("id")
        if cid not in src_cells and c.tag == "UserObject":
            continue  # 本席新增（UserObject 无 id=0/1 底图前身）
        if cid not in src_cells:
            continue  # 本席新增 cell（annot/anh/ans/an*/anm*/ane*/ant*）
        out_orig[cid] = c
    assert set(out_orig) == set(src_cells)
    for cid, sc in src_cells.items():
        oc = out_orig[cid]
        if cid == "1":
            added = set(oc.attrib) - set(sc.attrib)
            assert added == {"locked", "value"}
            assert oc.get("locked") == "1"
            for k, v in sc.attrib.items():  # 既有属性原值不动
                assert oc.get(k) == v
        else:
            assert _elem_sig(sc) == _elem_sig(oc), f"底图 cell {cid} 被改动"


# ─── 验收②：B 族 style 红线 ────────────────────────────────────────────────


def test_form_b_style_redline_and_flags(png_path: Path):
    """钉 3：style 含 shape=image 与 image=data:image/png, 且**零 ``;base64``
    子串**（分号=style 分隔符格式红线）；五旗标全 =0；几何=头解析像素值。"""
    plan = build_annotation_plan(png_path, ANNS_3, reviewer="张三")
    assert plan["form"] == "B"
    mxr = _mxroot(plan["xml"])
    img = _by_id(mxr, "baseimg")
    style = img.get("style") or ""
    assert "shape=image" in style
    assert "image=data:image/png," in style
    assert ";base64" not in style
    for flag in ("movable", "resizable", "rotatable", "deletable", "editable"):
        assert f"{flag}=0;" in style, f"缺五旗标 {flag}"
    geom = img.find("mxGeometry")
    assert geom is not None
    assert (geom.get("x"), geom.get("y")) == ("0", "0")
    assert (geom.get("width"), geom.get("height")) == ("1280", "720")


def test_form_b_png_jpeg_headers_and_size_override(
    png_path: Path, jpeg_path: Path, tmp_path: Path,
):
    """PNG/JPEG 头像素解析 + 显式 image_size 覆盖 + jpeg mime 形态。"""
    p_png = build_annotation_plan(png_path, ANNS_3)
    assert 'image=data:image/png,' in _by_id(
        _mxroot(p_png["xml"]), "baseimg").get("style")
    p_jpg = build_annotation_plan(jpeg_path, ANNS_3)
    img = _by_id(_mxroot(p_jpg["xml"]), "baseimg")
    assert "image=data:image/jpeg," in img.get("style")
    g = img.find("mxGeometry")
    assert g is not None and g.get("width") == "640" and g.get("height") == "480"
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n trunc")  # 头残缺
    with pytest.raises(ValueError, match="image_size"):
        build_annotation_plan(broken, ANNS_3)
    ok = build_annotation_plan(broken, ANNS_3, image_size=(800, 600))
    g2 = _by_id(_mxroot(ok["xml"]), "baseimg").find("mxGeometry")
    assert g2 is not None and g2.get("width") == "800"


def test_form_b_size_redlines(png_path: Path, tmp_path: Path):
    """>8 MB base64 → 显式报错（spec §3.2 红线）；>2 MB → warnings 警戒。"""
    big = tmp_path / "big.png"
    big.write_bytes(_png_bytes(2, 2) + b"\x00" * (7 * 1024 * 1024))
    with pytest.raises(ValueError, match="8 MB"):
        build_annotation_plan(big, ANNS_3)
    res = annotate_diagram(big, ANNS_3, tmp_path / "out.drawio")
    assert res["ok"] is False and "8 MB" in res["errors"][0]
    warn_img = tmp_path / "warn.png"
    warn_img.write_bytes(_png_bytes(2, 2) + b"\x00" * (1600 * 1024))
    p = build_annotation_plan(warn_img, ANNS_3)
    assert any("2 MB" in w for w in p["warnings"])


# ─── 验收③：优先级三色映射 ─────────────────────────────────────────────────


def test_priority_table_single_source_hex():
    """钉 4a：常量表逐键 hex=spec §2.3（high 红/medium 橙/low 绿）。"""
    assert PRIORITY_TABLE["high"] == ("#f8cecc", "#b85450", "高")
    assert PRIORITY_TABLE["medium"] == ("#ffe6cc", "#d79b00", "中")
    assert PRIORITY_TABLE["low"] == ("#d5e8d4", "#82b366", "低")


def test_priority_colors_on_xml_and_unknown_negative(png_path: Path):
    """钉 4b：三 priority → 三色逐位落 style；未知/缺 priority 显式拒绝。"""
    plan = build_annotation_plan(png_path, ANNS_3)
    mxr = _mxroot(plan["xml"])
    for i, ann in enumerate(ANNS_3["annotations"], 1):
        cell = _by_id(mxr, f"{CIRCLE_ID_PREFIX}{i}").find("mxCell")
        assert cell is not None
        fill, stroke, _zh = PRIORITY_TABLE[ann["priority"]]
        assert f"fillColor={fill};" in cell.get("style")
        assert f"strokeColor={stroke};" in cell.get("style")
    for bad in ({"priority": "urgent"}, {}):
        raw = dict(ANNS_3["annotations"][0])
        if "priority" in bad:
            raw["priority"] = bad["priority"]
        else:
            raw.pop("priority")
        with pytest.raises(ValueError, match="priority"):
            normalize_annotations([raw])
        res = annotate_diagram(png_path, [raw], png_path.with_suffix(".o"))
        assert res["ok"] is False


# ─── 验收④：三件组完整性 + target 存在性 ───────────────────────────────────


def test_triple_completeness_id_shape_and_geometry():
    """钉 5：每标注恰 1 圈+1 卡+1 关联边（+target 时恰 1 指示边）；id 形态
    anc/anm/ane/ant<i> 逐位；圈几何==region 原值（int 不带 .0）。"""
    anns = {"annotations": [
        {"id": "r1", "region": {"x": 10, "y": 20, "w": 100, "h": 50},
         "priority": "high", "label": "甲", "comment": "评语一",
         "target": "cascade"},
        {"id": "r2", "region": {"x": 10.5, "y": 20, "w": 100.5, "h": 50},
         "priority": "low", "label": "乙", "comment": "评语二"},
    ]}
    plan = build_annotation_plan(EXAMPLE, anns)
    mxr = _mxroot(plan["xml"])
    got = {el.get("id") for el in mxr.iter() if el.get("id")}
    assert {"anc1", "anm1", "ane1", "ant1", "anc2", "anm2", "ane2"} <= got
    assert not any(g.startswith("ant2") for g in got)  # 无 target 无指示边
    assert plan["n_target_edges"] == 1
    circle = _by_id(mxr, "anc1")
    uo_circle = circle if circle.tag == "UserObject" else None
    assert uo_circle is not None
    assert uo_circle.get("an_id") == "r1"
    assert uo_circle.get("comment") == "评语一"
    assert uo_circle.get("label") == "1 甲"
    inner = uo_circle.find("mxCell")
    assert inner is not None and inner.get("parent") == ANNOT_LAYER_ID
    assert inner.get("vertex") == "1"
    g = inner.find("mxGeometry")
    assert g is not None
    assert (g.get("x"), g.get("y"), g.get("width"), g.get("height")) == \
        ("10", "20", "100", "50")
    # 表序 i=1/2（非 id 字典序）：r1 在前
    assert _by_id(mxr, "anm1").get("an_id") == "r1"
    assert _by_id(mxr, "anm2").get("an_id") == "r2"
    card1 = _by_id(mxr, "anm1")
    assert card1.get("label") == "1 [高] 甲\n评语一"
    assert card1.get("priority") == "high"
    # 意见卡行 y=表序（60/148；spec 行高 72+行距 16）
    card2_geo = _by_id(mxr, "anm2").find("mxCell/mxGeometry")
    assert card2_geo is not None and card2_geo.get("y") == "148"
    # 浮点 region 原值渲染（无静默舍入）
    g2 = _by_id(mxr, "anc2").find("mxCell/mxGeometry")
    assert g2 is not None and g2.get("x") == "10.5" and g2.get("width") == "100.5"
    # 关联边：dashed+无箭头+优先级描边色
    e1 = _by_id(mxr, "ane1")
    assert e1.get("edge") == "1" and e1.get("source") == "anc1"
    assert e1.get("target") == "anm1"
    assert "dashed=1" in e1.get("style") and "endArrow=none" in e1.get("style")
    assert "strokeColor=#b85450;" in e1.get("style")
    t1 = _by_id(mxr, "ant1")
    assert t1.get("target") == "cascade"
    assert "strokeColor=#999999;" in t1.get("style")
    assert "dashed=1" in t1.get("style") and "endArrow=none" in t1.get("style")


def test_target_missing_id_negative_form_a():
    """钉 6a：形态 A target 不在底图 id 集 → 显式 ValueError（防指错对象）；
    service 走 ok=False 错误信封。"""
    bad = {"annotations": [dict(ANNS_3["annotations"][0],
                                target="ghost_box")]}
    with pytest.raises(ValueError, match=r"target.*ghost_box"):
        build_annotation_plan(EXAMPLE, bad)
    res = annotate_diagram(EXAMPLE, bad, "out.drawio")
    assert res["ok"] is False and "ghost_box" in res["errors"][0]


def test_target_ignored_form_b(png_path: Path):
    """钉 6b：形态 B 无底图 id 空间 → target 忽略+warnings 计数，零 ant 边。"""
    plan = build_annotation_plan(png_path, ANNS_3)
    assert plan["n_target_edges"] == 0
    assert sum("target 已忽略" in w for w in plan["warnings"]) == 1
    mxr = _mxroot(plan["xml"])
    assert not [el for el in mxr.iter()
                if (el.get("id") or "").startswith(TARGET_EDGE_ID_PREFIX)]


def test_generated_id_collision_rejected(tmp_path: Path):
    """底图已含生成命名空间 id（再标注）→ 显式拒绝（id 唯一性硬前提）。"""
    first = build_annotation_plan(EXAMPLE, ANNS_3)  # 首跑合法（对照）
    assert first["form"] == "A"
    twice = tmp_path / "twice.drawio"  # 首跑产物当底图=已含 anc1/annot
    twice.write_text(first["xml"], encoding="utf-8")
    with pytest.raises(ValueError, match="冲突"):
        build_annotation_plan(twice, ANNS_3)


def test_input_id_collision_with_base_is_warning_not_error():
    """输入标注 id 撞底图 id：不算错（生成前缀隔离已消解），warnings 提示。"""
    anns = {"annotations": [dict(ANNS_3["annotations"][0], id="stage2")]}
    plan = build_annotation_plan(EXAMPLE, anns)
    assert plan["form"] == "A"
    assert any("stage2" in w and "同名" in w for w in plan["warnings"])


# ─── 验收⑤：确定性 + 表序 ──────────────────────────────────────────────────


def test_byte_identical_two_runs(tmp_path: Path):
    """钉 7：同输入两次生成（内核 XML 与 service 落盘文件）逐字节相同。"""
    p1 = build_annotation_plan(EXAMPLE, ANNS_3, reviewer="张三")["xml"]
    p2 = build_annotation_plan(EXAMPLE, ANNS_3, reviewer="张三")["xml"]
    assert p1 == p2
    o1, o2 = tmp_path / "o1.drawio", tmp_path / "o2.drawio"
    r1 = annotate_diagram(EXAMPLE, ANNS_3, o1, reviewer="张三")
    r2 = annotate_diagram(EXAMPLE, ANNS_3, o2, reviewer="张三")
    assert r1["ok"] and r2["ok"]
    assert o1.read_bytes() == o2.read_bytes()


def test_order_by_table_not_id_sort(png_path: Path):
    """钉 7 补：标注表乱序 id（z9 在前 a1 在后）按表序渲染 i=1/2。"""
    anns = {"annotations": [
        {"id": "z9", "region": {"x": 1, "y": 2, "w": 3, "h": 4},
         "priority": "low", "label": "后给的前项", "comment": "c1"},
        {"id": "a1", "region": {"x": 5, "y": 6, "w": 7, "h": 8},
         "priority": "high", "label": "前给的后项", "comment": "c2"},
    ]}
    mxr = _mxroot(build_annotation_plan(png_path, anns)["xml"])
    assert _by_id(mxr, "anc1").get("an_id") == "z9"
    assert _by_id(mxr, "anc2").get("an_id") == "a1"


# ─── 验收⑥：信封/写面/schema 负例族 ────────────────────────────────────────


def test_service_envelope_shape(tmp_path: Path):
    """钉 9a：ok 信封键集与 spec §1.1 形态（layers/base_locked）。"""
    out = tmp_path / "ann.drawio"
    res = annotate_diagram(EXAMPLE, ANNS_3, out, reviewer="张三")
    assert res["ok"] is True
    assert set(res) == {"ok", "out_path", "n_annotations", "n_target_edges",
                        "form", "layers", "base_locked", "warnings"}
    assert res["layers"] == {"base": "1", "annot": ANNOT_LAYER_ID}
    assert res["base_locked"] is True
    assert res["n_annotations"] == 3
    assert res["out_path"] == str(out)


def test_source_readonly_hash_and_mtime(tmp_path: Path):
    """钉 9b：source 只读（hash+mtime 双证）；只写 out_path。"""
    work = tmp_path / "src.drawio"
    work.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    before_hash = hashlib.sha256(work.read_bytes()).hexdigest()
    before_stat = work.stat().st_mtime_ns, work.stat().st_size
    out = tmp_path / "out.drawio"
    res = annotate_diagram(work, ANNS_3, out)
    assert res["ok"] is True
    assert hashlib.sha256(work.read_bytes()).hexdigest() == before_hash
    assert (work.stat().st_mtime_ns, work.stat().st_size) == before_stat
    assert out.exists()


def test_source_equals_out_rejected(tmp_path: Path):
    """钉 9c：source==out_path → 显式 ValueError 错误信封（原稿不可覆盖；
    Windows 大小写变体同判——normcase 写面守卫）。"""
    work = tmp_path / "src.drawio"
    work.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    res = annotate_diagram(work, ANNS_3, work)
    assert res["ok"] is False and "同路径" in res["errors"][0]
    res2 = annotate_diagram(work, ANNS_3, tmp_path / "SRC.DRAWIO")
    assert res2["ok"] is False


def test_zero_annotations_warning_and_empty_layer(png_path: Path):
    """钉 9d：空标注表合法（纯复制底图+空标注层）+ warnings 记零标注。"""
    plan = build_annotation_plan(png_path, {"annotations": []})
    assert plan["n_annotations"] == 0
    assert any("零标注" in w for w in plan["warnings"])
    mxr = _mxroot(plan["xml"])
    assert _by_id(mxr, ANNOT_LAYER_ID) is not None
    assert not [el for el in mxr.iter()
                if (el.get("id") or "").startswith(CIRCLE_ID_PREFIX)]
    res = annotate_diagram(png_path, [], png_path.with_name("z.drawio"))
    assert res["ok"] is True and res["n_annotations"] == 0


def test_missing_parent_dir_explicit_error(png_path: Path):
    """钉 9e：输出目录不存在 → 显式报错（不自动补救，家法）。"""
    res = annotate_diagram(png_path, ANNS_3, png_path.parent / "no" / "o.drawio")
    assert res["ok"] is False and "输出目录不存在" in res["errors"][0]


@pytest.mark.parametrize("mutate,match", [
    (lambda a: a.update(extra_key=1), "未支持键"),
    (lambda a: a["region"].update(extra=1), "region"),
    (lambda a: a["region"].pop("h"), "缺键"),
    (lambda a: a["region"].update(w=float("nan")), "有限"),
    (lambda a: a["region"].update(w=-1), "≥ 0"),
    (lambda a: a.update(id="bad id!"), "A-Za-z0-9_-"),
    (lambda a: a.update(label=""), "label"),
    (lambda a: a.update(comment="  "), "comment"),
    (lambda a: a.update(target=""), "target"),
])
def test_schema_negatives_family(mutate, match):
    """钉 10a：schema 负例族全显式报错（normalize 家法——多余键/region
    违约/负 w/id 形态/空 label/空 comment/空 target）。"""
    raw = dict(ANNS_3["annotations"][0])
    raw["region"] = dict(raw["region"])
    mutate(raw)
    with pytest.raises(ValueError, match=match):
        normalize_annotations([raw])


def test_schema_negatives_table_shapes():
    """钉 10b：payload 顶层形态负例（非 dict/缺 annotations/多余键/重复 id/
    裸数组合法对照）。"""
    with pytest.raises(ValueError, match="数组"):
        normalize_annotations("not-a-list")
    with pytest.raises(ValueError, match="annotations"):
        normalize_annotations({"summary": "缺表"})
    with pytest.raises(ValueError, match="未支持键"):
        normalize_annotations({"annotations": [], "extra": 1})
    dup = [ANNS_3["annotations"][0], ANNS_3["annotations"][0]]
    with pytest.raises(ValueError, match="重复"):
        normalize_annotations(dup)
    bare = normalize_annotations([ANNS_3["annotations"][0]])  # 裸数组合法
    assert bare["summary"] is None and len(bare["annotations"]) == 1


# ─── 端到端样例（spec 钉 11）+ 摘要/栏头/评审人 ─────────────────────────────


def test_end_to_end_example_summary_header_bar_geometry():
    """钉 11：样例底图+3 标注 → 栏头计数/摘要卡几何/意见栏 x（底图右缘
    1220+60=1280）。"""
    plan = build_annotation_plan(EXAMPLE, ANNS_3, reviewer="张三")
    assert (plan["n_annotations"], plan["form"]) == (3, "A")
    mxr = _mxroot(plan["xml"])
    header = _by_id(mxr, "anh")
    assert header.get("value") == "评审意见（3 条，高 1/中 1/低 1）"
    hg = header.find("mxGeometry")
    assert hg is not None and hg.get("x") == "1280" and hg.get("y") == "20"
    summary = _by_id(mxr, "ans")
    assert summary.get("value") == ANNS_3["summary"]
    sg = summary.find("mxGeometry")
    assert sg is not None and sg.get("x") == "920"  # 1280-360
    rows = [148, 236]  # 行 y=60+(i-1)*88：60/148/236（此处抽后两行卡）
    for i, y in zip((2, 3), rows, strict=True):
        geo = _by_id(mxr, f"{CARD_ID_PREFIX}{i}").find("mxCell/mxGeometry")
        assert geo is not None and geo.get("x") == "1280"
        assert geo is not None and geo.get("y") == str(y)
    for i in (1, 2, 3):
        card = _by_id(mxr, f"{CARD_ID_PREFIX}{i}")
        assert card.get("reviewer") == "张三"
        circle_inner = _by_id(mxr, f"{CIRCLE_ID_PREFIX}{i}").find("mxCell")
        assert circle_inner is not None


def test_reviewer_absent_no_attr(png_path: Path):
    """reviewer 可省：不给则零 reviewer 属性（零默认值捏造）。"""
    mxr = _mxroot(build_annotation_plan(png_path, ANNS_3)["xml"])
    for i in (1, 2, 3):
        assert _by_id(mxr, f"{CARD_ID_PREFIX}{i}").get("reviewer") is None


def test_comment_verbatim_special_chars(png_path: Path):
    """铁律 7/钉 9 补：意见文本原样标注——特殊字符经转义后回读逐字还原。"""
    comment = "间距 < 0.2 mm 且 R&C 共用焊盘，需复核（ROI 5x5）"
    label = "R&C 共用 <焊盘>"
    anns = {"annotations": [
        {"id": "s1", "region": {"x": 0, "y": 0, "w": 10, "h": 10},
         "priority": "medium", "label": label, "comment": comment}]}
    mxr = _mxroot(build_annotation_plan(png_path, anns)["xml"])
    assert _by_id(mxr, "anc1").get("comment") == comment
    assert _by_id(mxr, "anc1").get("label") == f"1 {label}"
    assert _by_id(mxr, "anm1").get("label") == f"1 [中] {label}\n{comment}"


def test_module_zero_formula_grep():
    """铁律 7 grep 面：内核零对数/幂/三角运算（声明式装配——数字只有
    用户 JSON 原值与序号 i）。"""
    src = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "core" \
        / "review_annotation.py"
    text = src.read_text(encoding="utf-8")
    for banned in ("math.log", "math.exp", "math.pow", "log10",
                   "math.sin", "math.cos", "numpy", "scipy"):
        assert banned not in text, f"内核出现禁用运算形态 {banned!r}"


# ─── 分型覆盖（image= 键） ──────────────────────────────────────────────────


def test_dispatch_override_image_kwarg(png_path: Path, tmp_path: Path):
    """spec §0.2 ``image=`` 键覆盖分型：False 强制形态 A（png 即报错）、
    True 强制形态 B（.drawio 后缀不支持形态 B）。"""
    res = annotate_diagram(png_path, ANNS_3, tmp_path / "a.drawio",
                           image=False)
    assert res["ok"] is False
    res2 = annotate_diagram(EXAMPLE, ANNS_3, tmp_path / "b.drawio",
                            image=True)
    assert res2["ok"] is False and "PNG/JPEG" in res2["errors"][0]


# ─── CLI 叶（diagram annotate 第三叶） ─────────────────────────────────────


def _invoke(args: list[str]):
    return CliRunner().invoke(root_app, args)


def test_cli_annotate_json_success(tmp_path: Path):
    out = tmp_path / "ann.drawio"
    r = _invoke(["diagram", "annotate", "--source", str(EXAMPLE),
                 "--annotations", json.dumps(ANNS_3, ensure_ascii=False),
                 "--out", str(out), "--reviewer", "李四", "--json"])
    assert r.exit_code == 0, r.output
    envelope = json.loads(r.output[r.output.index("{"):])
    assert envelope["ok"] is True and envelope["n_annotations"] == 3
    assert envelope["base_locked"] is True
    assert out.exists()


def test_cli_annotate_rich_success(png_path: Path, tmp_path: Path):
    out = tmp_path / "ann.drawio"
    r = _invoke(["diagram", "annotate", "--source", str(png_path),
                 "--annotations", json.dumps(ANNS_3, ensure_ascii=False),
                 "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert "已写出" in r.output and "形态 B" in r.output


def test_cli_annotate_annotations_file_form(tmp_path: Path):
    ann_file = tmp_path / "ann.json"
    ann_file.write_text(json.dumps(ANNS_3, ensure_ascii=False),
                        encoding="utf-8")
    out = tmp_path / "ann.drawio"
    r = _invoke(["diagram", "annotate", "--source", str(EXAMPLE),
                 "--annotations", f"@{ann_file}", "--out", str(out),
                 "--json"])
    assert r.exit_code == 0, r.output
    envelope = json.loads(r.output[r.output.index("{"):])
    assert envelope["ok"] is True


def test_cli_annotate_service_failure_exit1_json_envelope(tmp_path: Path):
    bad = {"annotations": [dict(ANNS_3["annotations"][0], target="ghost")]}
    r = _invoke(["diagram", "annotate", "--source", str(EXAMPLE),
                 "--annotations", json.dumps(bad, ensure_ascii=False),
                 "--out", str(tmp_path / "o.drawio"), "--json"])
    assert r.exit_code == 1
    envelope = json.loads(r.output[r.output.rindex("{"):])
    assert envelope["ok"] is False and envelope["errors"]


def test_cli_annotate_usage_errors_exit2(tmp_path: Path):
    base = ["diagram", "annotate", "--source", str(EXAMPLE),
            "--out", str(tmp_path / "o.drawio")]
    r1 = _invoke([*base, "--annotations", "{bad json", "--json"])
    assert r1.exit_code == 2
    r2 = _invoke([*base, "--annotations", "@nope/missing.json", "--json"])
    assert r2.exit_code == 2
    r3 = _invoke([*base, "--annotations", json.dumps(ANNS_3),
                  "--image-size", "wide", "--json"])
    assert r3.exit_code == 2
    r4 = _invoke([*base, "--annotations", json.dumps(ANNS_3),
                  "--image-size", "800x600", "--json"])
    assert r4.exit_code == 0  # 合法 WxH 兜底走通


def test_cli_annotate_help_renders():
    """help 卫生：--help 渲染零异常（无裸 %/格式符炸面；括号卫生由
    test_cli_help_text_hygiene 常驻门全树扫描）。"""
    r = _invoke(["diagram", "annotate", "--help"])
    assert r.exit_code == 0, r.output
    assert "annotate" in r.output


# ═══ aurora_p A4：多评审人合并（merge_annotation_plans/merge_annotate_diagram）


#: 合并样例：两评审人各 2 条（输入 id 跨文件重复 a1/a2——冲突消解钉；
#: 张三 a1 带 target=stage2——target 指示边钉；李四无 summary——摘要
#: 逐行拼合钉）。排序序=张三(U+5F20) < 李四(U+674E)。
MERGE_ANNS_ZHANG = {
    "summary": "底图布局与隔离电阻意见",
    "annotations": [
        {"id": "a1", "region": {"x": 300, "y": 60, "w": 190, "h": 76},
         "priority": "high", "label": "R_iso 位置",
         "comment": "隔离电阻距输出臂过近，建议左移 5 mm 后复仿真",
         "target": "stage2"},
        {"id": "a2", "region": {"x": 40, "y": 60, "w": 180, "h": 72},
         "priority": "medium", "label": "LNA 增益",
         "comment": "建议核对该级 NF 余量"},
    ],
}
MERGE_ANNS_LI = {
    "annotations": [
        {"id": "a1", "region": {"x": 760, "y": 60, "w": 180, "h": 72},
         "priority": "low", "label": "中频放大",
         "comment": "下版考虑提高增益"},
        {"id": "b2", "region": {"x": 40, "y": 300, "w": 200, "h": 80},
         "priority": "high", "label": "级间匹配",
         "comment": "建议复核级间匹配网络带宽"},
    ],
}
#: 合并表序=张三(a1,a2) → 李四(a1,b2)；全局顺序号 i=1..4（三元组含优先级
#: ——两个 a1 分属不同评审人、优先级不同，禁按 aid 撞键）
_MERGE_EXPECTED_ORDER = [
    ("张三", "a1", "high"), ("张三", "a2", "medium"),
    ("李四", "a1", "low"), ("李四", "b2", "high")]
_MERGE_HEADER = "评审意见（4 条，高 2/中 1/低 1；张三 2 条、李四 2 条）"


def test_reviewer_palette_single_source_distinct_from_priority():
    """验收 A 前置：调色表单源——表内无重复、与 PRIORITY_TABLE 三描边互斥
    且不吞内容蓝 #dae8fc（蓝=图元内容色语义）。"""
    assert len(REVIEWER_PALETTE) == len(set(REVIEWER_PALETTE))
    priority_strokes = {PRIORITY_TABLE[p][1] for p in PRIORITY_TABLE}
    overlap = set(REVIEWER_PALETTE) & priority_strokes
    assert not overlap, f"评审人调色与优先级描边撞色：{sorted(overlap)}"
    assert "#dae8fc" not in REVIEWER_PALETTE


def test_reviewer_palette_rotation_beyond_table_length(png_path: Path):
    """超调色表长（>5 人）按排序序号 i%n 确定性轮转：第 6 位回首色。"""
    n = len(REVIEWER_PALETTE)
    ann = MERGE_ANNS_ZHANG["annotations"][0]
    entries = []
    for k in range(n + 1):
        entries.append((f"r{chr(ord('a') + k)}",
                        {"annotations": [dict(ann, id=f"x{k}")]}))
    plan = merge_annotation_plans(png_path, entries)
    assert plan["n_reviewers"] == n + 1
    first = f"r{chr(ord('a'))}"                # 排序第 1 位
    second_last = f"r{chr(ord('a') + n - 1)}"  # 排序第 n 位=表尾色
    last = f"r{chr(ord('a') + n)}"             # 排序第 n+1 位=轮转回首色
    assert plan["reviewer_colors"][first] == REVIEWER_PALETTE[0]
    assert plan["reviewer_colors"][second_last] == REVIEWER_PALETTE[n - 1]
    assert plan["reviewer_colors"][last] == REVIEWER_PALETTE[0]


def test_merge_two_reviewers_structure_attribution_and_counts():
    """验收 A：署名逐键进产物（圈/卡 reviewer 属性）+逐评审人计数正确
    （栏头文本/per_reviewer/摘要逐行拼合）+色分（描边=评审人、填充=优先级）+
    意见卡 label 带 ·评审人 署名。"""
    plan = merge_annotation_plans(EXAMPLE, [("张三", MERGE_ANNS_ZHANG),
                                            ("李四", MERGE_ANNS_LI)])
    assert plan["form"] == "A"
    assert plan["n_annotations"] == 4
    assert plan["n_reviewers"] == 2
    assert plan["reviewers"] == ["张三", "李四"]
    assert plan["per_reviewer"] == {
        "张三": {"total": 2, "high": 1, "medium": 1, "low": 0},
        "李四": {"total": 2, "high": 1, "medium": 0, "low": 1}}
    assert plan["reviewer_colors"] == {"张三": "#6c8ebf", "李四": "#9673a6"}
    assert plan["base_locked"] is True
    assert plan["layers"] == {"base": "1", "annot": ANNOT_LAYER_ID}
    assert any("a1" in w and "重复" in w for w in plan["warnings"])

    mxr = _mxroot(plan["xml"])
    # 合并表序=张三→李四（入参已是该序；顺序无关性另测），全局顺序号
    for i, (rev, aid, prio) in enumerate(_MERGE_EXPECTED_ORDER, 1):
        circle = _by_id(mxr, f"{CIRCLE_ID_PREFIX}{i}")
        assert circle.get("an_id") == aid and circle.get("reviewer") == rev
        card = _by_id(mxr, f"{CARD_ID_PREFIX}{i}")
        assert card.get("an_id") == aid and card.get("reviewer") == rev
        assert card.get("priority") == prio
    # 色分：描边=评审人调色、填充=优先级三色（圈+卡+圈→卡边）
    for i, (rev, _aid, prio) in enumerate(_MERGE_EXPECTED_ORDER, 1):
        stroke = plan["reviewer_colors"][rev]
        fill = PRIORITY_TABLE[prio][0]
        cell = _by_id(mxr, f"{CIRCLE_ID_PREFIX}{i}").find("mxCell")
        assert cell is not None
        assert f"strokeColor={stroke};" in cell.get("style")
        assert f"fillColor={fill};" in cell.get("style")
        ccell = _by_id(mxr, f"{CARD_ID_PREFIX}{i}").find("mxCell")
        assert ccell is not None
        assert f"strokeColor={stroke};" in ccell.get("style")
        ecell = _by_id(mxr, f"{CROSS_EDGE_ID_PREFIX}{i}")
        assert f"strokeColor={stroke};" in ecell.get("style")
    # 意见卡 label 署名形态（铁律 7：文本=JSON 原值+序号+优先级中文+署名）
    assert _by_id(mxr, "anm1").get("label") == (
        "1 [高·张三] R_iso 位置\n"
        "隔离电阻距输出臂过近，建议左移 5 mm 后复仿真")
    assert _by_id(mxr, "anm4").get("label") == (
        "4 [高·李四] 级间匹配\n建议复核级间匹配网络带宽")
    # 圈 label 不变（<i> <label>）
    assert _by_id(mxr, "anc3").get("label") == "3 中频放大"
    # 栏头=逐评审人计数形态；摘要卡=逐行 <rev>：<summary>
    assert _by_id(mxr, "anh").get("value") == _MERGE_HEADER
    assert _by_id(mxr, "ans").get("value") == "张三：底图布局与隔离电阻意见"
    # 卡行 y=合并表序（60/148/236/324）
    for i, y in enumerate((60, 148, 236, 324), 1):
        geo = _by_id(mxr, f"{CARD_ID_PREFIX}{i}").find("mxCell/mxGeometry")
        assert geo is not None and geo.get("y") == str(y)
    # target 指示边（张三 a1→stage2，细灰不变）
    t1 = _by_id(mxr, f"{TARGET_EDGE_ID_PREFIX}1")
    assert t1.get("target") == "stage2"
    assert "strokeColor=#999999;" in t1.get("style")


def test_merge_base_cells_untouched_form_a():
    """验收 B（生命线）：合并输出中底图 cell 集合逐 cell (tag, attrib, 子树)
    与原文件全等；id=1 仅新增 locked/value 两键。"""
    src_tree = ET.fromstring(EXAMPLE.read_text(encoding="utf-8"))
    plan = merge_annotation_plans(EXAMPLE, [("张三", MERGE_ANNS_ZHANG),
                                            ("李四", MERGE_ANNS_LI)])
    out_tree = _parse(plan["xml"])
    src_root = src_tree.find("diagram/mxGraphModel/root")
    out_root = out_tree.find("diagram/mxGraphModel/root")
    assert src_root is not None and out_root is not None
    src_cells = {c.get("id"): c for c in src_root}
    out_orig = {}
    for c in out_root:
        cid = c.get("id")
        if cid not in src_cells:
            continue  # 本席新增（annot 层/anh/ans/UserObject 三件组/anx 边）
        out_orig[cid] = c
    assert set(out_orig) == set(src_cells)
    for cid, sc in src_cells.items():
        oc = out_orig[cid]
        if cid == "1":
            added = set(oc.attrib) - set(sc.attrib)
            assert added == {"locked", "value"}
            assert oc.get("locked") == "1"
            for k, v in sc.attrib.items():
                assert oc.get(k) == v
        else:
            assert _elem_sig(sc) == _elem_sig(oc), f"底图 cell {cid} 被改动"


def test_merge_deterministic_and_input_order_independent(tmp_path: Path):
    """验收 C：同输入两跑逐字节（内核+service 落盘）；入参顺序无关
    （按 reviewer 名归一——entries 反序产出同字节）。"""
    p1 = merge_annotation_plans(EXAMPLE, [("张三", MERGE_ANNS_ZHANG),
                                          ("李四", MERGE_ANNS_LI)])["xml"]
    p2 = merge_annotation_plans(EXAMPLE, [("张三", MERGE_ANNS_ZHANG),
                                          ("李四", MERGE_ANNS_LI)])["xml"]
    assert p1 == p2
    p3 = merge_annotation_plans(EXAMPLE, [("李四", MERGE_ANNS_LI),
                                          ("张三", MERGE_ANNS_ZHANG)])["xml"]
    assert p3 == p1
    za, la = tmp_path / "zhang.json", tmp_path / "li.json"
    za.write_text(json.dumps(MERGE_ANNS_ZHANG, ensure_ascii=False),
                  encoding="utf-8")
    la.write_text(json.dumps(MERGE_ANNS_LI, ensure_ascii=False),
                  encoding="utf-8")
    o1, o2 = tmp_path / "m1.drawio", tmp_path / "m2.drawio"
    r1 = merge_annotate_diagram(EXAMPLE, [("张三", str(za)), ("李四", str(la))],
                                o1)
    r2 = merge_annotate_diagram(EXAMPLE, [("李四", la), ("张三", za)], o2)
    assert r1["ok"] and r2["ok"]
    assert o1.read_bytes() == o2.read_bytes()


def test_merge_input_id_conflict_renumber_and_warning():
    """id 冲突钉（选型定死=合并表序全局顺序号）：两文件同用 a1 → 生成
    cell id anc1/anc3 互异且唯一；an_id 双双保留原值 a1；warnings 逐 id
    恰一条。"""
    plan = merge_annotation_plans(EXAMPLE, [("张三", MERGE_ANNS_ZHANG),
                                            ("李四", MERGE_ANNS_LI)])
    mxr = _mxroot(plan["xml"])
    got_ids = [el.get("id") for el in mxr.iter() if el.get("id")]
    assert len(got_ids) == len(set(got_ids))  # 生成 id 全局唯一
    assert _by_id(mxr, "anc1").get("an_id") == "a1"
    assert _by_id(mxr, "anc3").get("an_id") == "a1"
    dup_warns = [w for w in plan["warnings"] if "重复" in w]
    assert len(dup_warns) == 1 and "a1" in dup_warns[0]
    # 文件内重复 id 仍由 normalize 显式拒绝（既有语义零变化）
    with pytest.raises(ValueError, match="重复"):
        merge_annotation_plans(EXAMPLE, [("张三", {"annotations": [
            MERGE_ANNS_ZHANG["annotations"][0],
            MERGE_ANNS_ZHANG["annotations"][0]]})])


def test_merge_duplicate_reviewer_same_bucket():
    """重复 reviewer 名跨文件（设计定死=合入同一桶）：同色、计数合并、
    表序=按 reviewer 排序后同 reviewer 保入参相对序（稳定排序）。"""
    def _ann(aid: str, prio: str, x: int) -> dict:
        return {"id": aid, "region": {"x": x, "y": 1, "w": 10, "h": 10},
                "priority": prio, "label": f"L-{aid}", "comment": f"C-{aid}"}
    entries = [
        ("李四", {"annotations": [_ann("x1", "low", 1)]}),
        ("张三", {"annotations": [_ann("y1", "high", 2)]}),
        ("李四", {"annotations": [_ann("x2", "medium", 3)]}),
    ]
    plan = merge_annotation_plans(EXAMPLE, entries)
    assert plan["n_reviewers"] == 2
    assert plan["reviewers"] == ["张三", "李四"]
    assert plan["reviewer_colors"] == {"张三": "#6c8ebf", "李四": "#9673a6"}
    assert plan["per_reviewer"]["李四"] == {
        "total": 2, "high": 0, "medium": 1, "low": 1}
    assert plan["per_reviewer"]["张三"]["total"] == 1
    mxr = _mxroot(plan["xml"])
    order = [(_by_id(mxr, f"{CIRCLE_ID_PREFIX}{i}").get("reviewer"),
              _by_id(mxr, f"{CIRCLE_ID_PREFIX}{i}").get("an_id"))
             for i in (1, 2, 3)]
    assert order == [("张三", "y1"), ("李四", "x1"), ("李四", "x2")]
    assert _by_id(mxr, "anh").get("value") == (
        "评审意见（3 条，高 1/中 1/低 1；张三 1 条、李四 2 条）")


def test_merge_empty_file_warning_and_zero_total(png_path: Path):
    """空标注文件：单文件空=合法（逐评审人 warning）；全空=零标注 warning
    +空标注层（per_reviewer 零条目仍登记）。"""
    plan = merge_annotation_plans(png_path, [
        ("张三", {"annotations": []}),
        ("李四", {"annotations": [MERGE_ANNS_LI["annotations"][0]]}),
    ])
    assert plan["n_annotations"] == 1
    assert plan["per_reviewer"]["张三"] == {
        "total": 0, "high": 0, "medium": 0, "low": 0}
    assert any("张三" in w and "为空" in w for w in plan["warnings"])
    plan0 = merge_annotation_plans(png_path, [
        ("张三", {"annotations": []}), ("李四", [])])
    assert plan0["n_annotations"] == 0
    assert any("零标注" in w for w in plan0["warnings"])
    assert sum("'张三'" in w and "为空" in w for w in plan0["warnings"]) == 1
    assert sum("'李四'" in w and "为空" in w for w in plan0["warnings"]) == 1
    mxr = _mxroot(plan0["xml"])
    assert _by_id(mxr, ANNOT_LAYER_ID) is not None
    assert not [el for el in mxr.iter() if (el.get("id") or "").startswith(
        CIRCLE_ID_PREFIX)]


def test_merge_negatives_explicit():
    """验收 E：负例显式不静默——reviewer 空名/非字符串、entries 空表/形态
    违约、payload 非法；service 走 ok=False 错误信封。"""
    good = {"annotations": [MERGE_ANNS_ZHANG["annotations"][0]]}
    for entries, match in [
        ([], "非空"),
        ([("张三", good), ("", good)], "reviewer"),
        ([("张三", good), ("  ", good)], "reviewer"),
        ([("张三", good), (5, good)], "reviewer"),
        ("张三", "序列"),
        ([("张三", good, "多余")], "二元组"),
        ([("张三",)], "二元组"),
        (["张三"], "二元组"),
        ([("张三", 12345)], "payload"),
        ([("张三", {"annotations": []}), ("李四", "not-a-list")], "数组"),
    ]:
        with pytest.raises(ValueError, match=match):
            merge_annotation_plans(EXAMPLE, entries)
    res = merge_annotate_diagram(EXAMPLE, [("张三", good), ("", good)],
                                 "out.drawio")
    assert res["ok"] is False and "reviewer" in res["errors"][0]
    res2 = merge_annotate_diagram(EXAMPLE, [("张三", good),
                                            ("李四", "nope/missing.json")],
                                  "out.drawio")
    assert res2["ok"] is False and "不存在" in res2["errors"][0]


def test_merge_service_envelope_readonly_and_path_guards(tmp_path: Path):
    """service 信封键集（逐评审人面）+source/标注 JSON 输入只读
    （hash+mtime 双证）+路径守卫（source==out/JSON==out 大小写变体）。"""
    out = tmp_path / "merged.drawio"
    res = merge_annotate_diagram(
        EXAMPLE, [("张三", MERGE_ANNS_ZHANG), ("李四", MERGE_ANNS_LI)], out)
    assert res["ok"] is True
    assert set(res) == {"ok", "out_path", "n_annotations", "n_reviewers",
                        "reviewers", "per_reviewer", "reviewer_colors",
                        "n_target_edges", "form", "layers", "base_locked",
                        "warnings"}
    assert (res["n_annotations"], res["n_reviewers"],
            res["n_target_edges"], res["form"]) == (4, 2, 1, "A")
    assert res["reviewers"] == ["张三", "李四"]
    assert res["base_locked"] is True and out.exists()
    # 写面纪律：source 与标注 JSON 输入全只读
    work = tmp_path / "src.drawio"
    work.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    za = tmp_path / "z.json"
    za.write_text(json.dumps(MERGE_ANNS_ZHANG, ensure_ascii=False),
                  encoding="utf-8")
    snap = {p: (p.stat().st_mtime_ns, p.stat().st_size,
                hashlib.sha256(p.read_bytes()).hexdigest())
            for p in (work, za)}
    out2 = tmp_path / "m.drawio"
    r = merge_annotate_diagram(work, [("张三", str(za)), ("李四", MERGE_ANNS_LI)],
                               out2)
    assert r["ok"] is True
    for p, (mtime, size, digest) in snap.items():
        assert (p.stat().st_mtime_ns, p.stat().st_size) == (mtime, size)
        assert hashlib.sha256(p.read_bytes()).hexdigest() == digest
    # source==out_path（normcase）与 标注 JSON==out_path 显式拒绝
    r3 = merge_annotate_diagram(work, [("张三", MERGE_ANNS_ZHANG)], work)
    assert r3["ok"] is False and "同路径" in r3["errors"][0]
    r4 = merge_annotate_diagram(work, [("张三", str(za))], za)
    assert r4["ok"] is False and "同路径" in r4["errors"][0]
    r5 = merge_annotate_diagram(work, [("张三", str(za))],
                                za.with_name(za.name.upper()))
    assert r5["ok"] is False
    r6 = merge_annotate_diagram(work, [("张三", MERGE_ANNS_ZHANG)],
                                tmp_path / "no" / "m.drawio")
    assert r6["ok"] is False and "输出目录不存在" in r6["errors"][0]


def test_merge_form_b_image_base(png_path: Path):
    """形态 B 合并：位图底图+两评审人——target 一律忽略（warnings 计数）、
    零 ant 边、底图 image cell 与锁旗标形态不变。"""
    plan = merge_annotation_plans(png_path, [("张三", MERGE_ANNS_ZHANG),
                                             ("李四", MERGE_ANNS_LI)])
    assert plan["form"] == "B"
    assert plan["n_target_edges"] == 0
    assert sum("target 已忽略" in w for w in plan["warnings"]) == 1
    mxr = _mxroot(plan["xml"])
    assert not [el for el in mxr.iter()
                if (el.get("id") or "").startswith(TARGET_EDGE_ID_PREFIX)]
    img = _by_id(mxr, "baseimg")
    style = img.get("style") or ""
    assert "shape=image" in style and ";base64" not in style
    assert _by_id(mxr, "anh").get("value") == _MERGE_HEADER
    assert _by_id(mxr, "anc1").get("reviewer") == "张三"
    assert _by_id(mxr, "anc4").get("reviewer") == "李四"


def test_merge_service_json_file_inputs(tmp_path: Path):
    """service 第二元素=JSON 文件路径（str 与 Path 混收）——读盘在 service
    层，core 零 IO 纪律不变；缺 payload 形态显式报错。"""
    za = tmp_path / "zhang.json"
    la = tmp_path / "li.json"
    za.write_text(json.dumps(MERGE_ANNS_ZHANG, ensure_ascii=False),
                  encoding="utf-8")
    la.write_text(json.dumps(MERGE_ANNS_LI, ensure_ascii=False),
                  encoding="utf-8")
    out = tmp_path / "merged.drawio"
    r = merge_annotate_diagram(EXAMPLE, [("李四", la), ("张三", str(za))], out)
    assert r["ok"] is True
    assert r["reviewers"] == ["张三", "李四"]  # 读盘后仍按 reviewer 归一排序
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    r2 = merge_annotate_diagram(EXAMPLE, [("张三", str(bad))],
                                tmp_path / "x.drawio")
    assert r2["ok"] is False and "JSON" in r2["errors"][0]
    r3 = merge_annotate_diagram(EXAMPLE, [("张三", 3.14)],
                                tmp_path / "y.drawio")
    assert r3["ok"] is False and "payload" in r3["errors"][0]
