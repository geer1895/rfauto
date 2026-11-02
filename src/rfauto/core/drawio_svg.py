"""纯 Python drawio (mxGraph XML) → 静态 SVG 渲染内核（aurora_p C3，2026-11-01）。

定位：报告/服务器场景**无 draw.io 桌面 GUI**的看图件——本模块把
drawio (mxGraph XML) 图档渲染为静态 SVG（ElementTree 装配，零第三方
依赖、零上游代码复制——mxGraph XML 与 SVG 均为开放规范；jgraph/drawio
本体 Apache-2.0，本模块为自研装配器）。

v1 初级形态（框+连线+文字直映射，铁律 7 的"几何零重算"版）：
- 几何 = drawio 坐标直映射（vertex mxGeometry x/y/width/height → SVG
  用户坐标 1:1），**零布局重算**——布局语义留给 drawio XML 自身坐标；
  嵌套 vertex（parent=另一 vertex）按祖先链平移展开（纯加法）；
- 文字 = mxCell value 原值原样（XML 实体解析后由 ElementTree 序列化
  再转义回合法 XML——往返无篡改）；value 内 ``\\n`` 分行渲染为多
  ``<tspan>``；UserObject 包装 cell 以其 ``label`` 属性为展示文本原样
  （placeholders ``%name%`` 替换 **v2 不做**——原样输出）；
- edge = 直线/折线：两端 vertex 包围盒 → 边中心锚点连线（水平相邻取
  左右中点、竖直相邻取上下中点、斜向取中心距短者；重叠取中心）；
  ``<mxPoint>`` way points（mxGeometry ``<Array as="points">``）存在时
  折线（polyline）；edge 自身 geometry 的 ``mxPoint as="offset"`` 与
  edge 子 label cell（相对几何 x/y + offset）按"边中点+偏移"直映射；
- layer = ``<g id="layer-<id>">`` 分组（含基图层；组序=首引用序）。

样式支持子集（**声明式常量表单源** :data:`SUPPORTED_STYLE_KEYS` /
UNSUPPORTED_FEATURE_TRIGGERS；缺省值事实核查=官方 mxStylesheet
defaultVertex/defaultEdge 实读——存档 runs/aurora_p/c3/recon/
drawio_default_stylesheet.xml）：fillColor/strokeColor/strokeWidth/
opacity/fillOpacity/fontSize/fontColor/fontFamily/fontStyle=1 粗体/
align/verticalAlign/rounded=1/dashed=1/endArrow/startArrow（none→无箭头
其余→三角箭头）/labelBackgroundColor（白晕近似）。注意 drawio 缺省
vertex=白底黑框——"无 fill/stroke 定义"仍渲染白底黑框。
**edgeStyle=orthogonalEdgeStyle 不重排正交路径**（直线+way points 直
映射——正交化是 drawio 运行时布局行为，静态渲染不复制）；
whiteSpace=wrap 接受但**不自动折行**（分行只来自显式 \\n——v1 边界）。

降级（#122 不静默不炸）：命中 UNSUPPORTED_FEATURE_TRIGGERS 的形态
（mxgraph.* 内置形状/image/渐变/rotation/阴影/曲线边/swimlane）→
vertex 画虚线占位框+shape 信息文字、edge 直线+warning，warnings 列表
显式回显；纯未知样式键（jettySize/html 等布局提示）静默忽略不炸。

read 面关系：主结构走 core/drawio_xml.parse_diagram（该模块**只读未
扩**——其 v1 不回 UserObject 包装 cell/edge 子 cell/way points/label
offset，本模块在渲染前做**补充扫描**（对原始 XML 的二次 ElementTree
遍历，把上述四类补进页 dict 副本）——补扫只在本模块内，不回写
drawio_xml）。压缩页/坏 XML/非 mxfile/缺文件 → DrawioReadError 原样
透传（ValueError 子类，service 错误信封同路捕获）；页序越界/空页 →
:class:`DrawioSvgError` 显式报错（不静默出白图）。

零公式（铁律 7）：本模块零物理/数值语义——只做"结构渲染"；画布取
mxGraphModel pageWidth/pageHeight 原属性（缺失按内容包围盒+边距），
数值全部来自输入 XML 原属性。

确定性：同输入两次渲染逐字节相同——零时间戳/零 uuid/属性序=插入序/
ET.indent 幂等。
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any

from rfauto.core.drawio_xml import (
    DrawioReadError,
    parse_diagram,
)

__all__ = [
    "DEFAULT_FONT_FAMILY",
    "DEFAULT_FONT_SIZE",
    "DEFAULT_MARGIN",
    "SUPPORTED_STYLE_KEYS",
    "UNSUPPORTED_FEATURE_TRIGGERS",
    "DrawioReadError",
    "DrawioSvgError",
    "render_diagram_svg",
    "render_xml_text",
]

#: 支持的样式键声明表（v1 支持清单单源——超出本表且命中
#: UNSUPPORTED_FEATURE_TRIGGERS 的键才降级；纯未知键静默忽略不炸）。
SUPPORTED_STYLE_KEYS: frozenset[str] = frozenset({
    "fillColor", "strokeColor", "strokeWidth", "opacity", "fillOpacity",
    "fontSize", "fontColor", "fontFamily", "fontStyle",
    "align", "verticalAlign", "whiteSpace",
    "rounded", "dashed",
    "endArrow", "startArrow", "endFill", "startFill",
    "labelBackgroundColor",
})

#: 命中即降级占位+warning 的形态触发键（v1 不支持）。带 ``=`` 的键按
#: "键=值"精确匹配；``shape=mxgraph`` 前缀形态匹配 ``shape`` 值以
#: ``mxgraph.`` 开头；裸词键按存在匹配。序=本 dict 序（确定性）。
UNSUPPORTED_FEATURE_TRIGGERS: dict[str, str] = {
    "shape=mxgraph": "mxgraph 内置形状",
    "image": "image 形态",
    "swimlane": "swimlane 形态",
    "gradientColor": "渐变填充",
    "rotation": "rotation 旋转",
    "curved=1": "曲线边",
    "shadow=1": "阴影",
}

#: 渲染缺省值（官方 mxStylesheet defaultVertex/defaultEdge 实读——存档
#: runs/aurora_p/c3/recon/drawio_default_stylesheet.xml）
DEFAULT_FONT_SIZE = 12
DEFAULT_FONT_FAMILY = "Helvetica"
#: 无 pageWidth/pageHeight 时按内容包围盒外加边距（px）
DEFAULT_MARGIN = 20

_SVG_NS = "http://www.w3.org/2000/svg"


class DrawioSvgError(ValueError):
    """渲染面显式错误（页序越界/空页/几何坏值）——ValueError 子类，
    service 层错误信封（except ValueError）可直接捕获。read 面错误
    （压缩页/坏 XML/非 mxfile/缺文件）= drawio_xml.DrawioReadError 原样
    透传（本模块 re-export 同名同物）。"""


# ── 样式解析 ────────────────────────────────────────────────────────────────


def _parse_style(style: str) -> dict[str, str]:
    """drawio style 串 → 键值 dict（``a=b`` 键值对 + 裸词键→""；键序保留）。"""
    out: dict[str, str] = {}
    for tok in (style or "").split(";"):
        tok = tok.strip()
        if not tok:
            continue
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[tok] = ""
    return out


def _unsupported_fragments(style_map: dict[str, str]) -> list[str]:
    """命中 UNSUPPORTED_FEATURE_TRIGGERS 的片段（确定性：按触发表键序）。"""
    hits: list[str] = []
    for trigger, label in UNSUPPORTED_FEATURE_TRIGGERS.items():
        if "=" in trigger:
            k, v = trigger.split("=", 1)
            matched = style_map.get(k) == v
            if not matched and k == "shape" and v.endswith("mxgraph"):
                matched = style_map.get("shape", "").startswith("mxgraph.")
        else:
            matched = trigger in style_map
        if matched:
            hits.append(label)
    return hits


def _parse_color(value: str | None) -> str | None:
    """drawio 颜色值 → SVG 颜色（none/空 → None；#hex 与 CSS 名原样透传）。"""
    if value is None:
        return None
    v = value.strip()
    if v == "" or v.lower() == "none":
        return None
    return v


def _fmt_num(value: Any, default: float | None = None) -> str:
    """坐标/尺寸 → SVG 数值文本（int 化去尾零；坏值显式报错不静默）。"""
    if value is None:
        if default is None:
            raise DrawioSvgError(f"几何数值缺失且无缺省：{value!r}")
        value = default
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise DrawioSvgError(f"几何数值不可解析：{value!r}") from exc
    text = f"{f:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-") else "0"


# ── 补充扫描（read 面 v1 缺口的渲染侧补全——不改 drawio_xml） ───────────────


def _vertex_view(cell_id: str, value: str, style: str, parent: str,
                 geometry: dict[str, Any] | None) -> dict[str, Any]:
    return {"id": cell_id, "parent": parent, "value": value, "style": style,
            "geometry": geometry, "attrs": {}}


def _supplement_page(model: ET.Element, page: dict[str, Any]) -> None:
    """对单个 mxGraphModel 元素补扫（原位并入 page 副本的 vertices/edges）：

    ① UserObject/object 包装 cell（label=value，内层 mxCell 供
    style/geometry/parent/source/target）；② edge 子 label cell（相对
    几何 + mxPoint offset——渲染按"边中点+偏移"）；③ 直挂 edge 的
    way points 与 label offset（写入 edge view 的 ``_points`` /
    ``_offset`` 键）。补扫序=文档序（确定性）。
    """
    root_el = model.find("root")
    if root_el is None:
        return
    edge_views = {v["id"]: v for v in page["edges"]}
    for el in root_el.iter():
        if el.tag == "mxCell":
            # ① edge 自身的 way points / label offset（含直挂 edge）
            if el.get("edge") == "1":
                geo = el.find("mxGeometry")
                if geo is None:
                    geo = el.find(".//mxGeometry")
                if geo is not None:
                    pts = [(p.get("x") or "0", p.get("y") or "0")
                           for arr in geo.findall("Array")
                           if arr.get("as") == "points"
                           for p in arr.findall("mxPoint")]
                    off = geo.find("mxPoint[@as='offset']")
                    view = edge_views.get(el.get("id") or "")
                    if view is not None:
                        if pts:
                            view["_points"] = pts
                        if off is not None:
                            view["_offset"] = (off.get("x") or "0",
                                               off.get("y") or "0")
            continue
        if el.tag not in ("UserObject", "object"):
            continue
        inner = el.find("mxCell")
        if inner is None:
            continue
        label = el.get("label")
        if inner.get("vertex") == "1":
            geo_el = inner.find("mxGeometry")
            geo = None if geo_el is None else {
                "x": geo_el.get("x"), "y": geo_el.get("y"),
                "width": geo_el.get("width"), "height": geo_el.get("height"),
            }
            page["vertices"].append(_vertex_view(
                el.get("id") or "", label or inner.get("value") or "",
                inner.get("style") or "", inner.get("parent") or "", geo))
        elif inner.get("edge") == "1":
            view = {"id": el.get("id") or "",
                    "parent": inner.get("parent") or "",
                    "value": label or inner.get("value") or "",
                    "style": inner.get("style") or "",
                    "source": inner.get("source") or "",
                    "target": inner.get("target") or "",
                    "attrs": {}}
            page["edges"].append(view)
            edge_views[view["id"]] = view
    # ② edge 子 label cell（mxCell 的 mxCell 子元素；文档序追加）
    for el in root_el.iter("mxCell"):
        if el.get("edge") != "1":
            continue
        for child in el.findall("mxCell"):
            if child.get("vertex") != "1":
                continue
            geo_el = child.find("mxGeometry")
            geo: dict[str, Any] | None = None
            if geo_el is not None:
                geo = {"x": geo_el.get("x"), "y": geo_el.get("y"),
                       "width": geo_el.get("width"),
                       "height": geo_el.get("height")}
                off = geo_el.find("mxPoint[@as='offset']")
                if off is not None:
                    geo["_offset"] = (off.get("x") or "0",
                                      off.get("y") or "0")
            page["vertices"].append(_vertex_view(
                child.get("id") or "", child.get("value") or "",
                child.get("style") or "", child.get("parent")
                or (el.get("id") or ""), geo))


# ── 渲染快照 ────────────────────────────────────────────────────────────────


class _VertexNode:
    """渲染用 vertex 快照。"""

    __slots__ = (
        "cell_id",
        "degrade",
        "geometry",
        "is_ellipse",
        "is_text_only",
        "parent",
        "style",
        "style_map",
        "value",
    )

    def __init__(self, view: dict[str, Any]) -> None:
        self.cell_id = view["id"]
        self.value = view["value"]
        self.style = view["style"]
        self.style_map = _parse_style(view["style"])
        self.geometry = view.get("geometry")
        self.parent = view["parent"]
        self.is_ellipse = (self.style_map.get("shape") == "ellipse"
                           or "ellipse" in self.style_map)
        self.is_text_only = (view["style"] or "").split(";")[0].strip() == "text"
        self.degrade = _unsupported_fragments(self.style_map)


def _absolute_origin(vertices: dict[str, _VertexNode],
                     cell_id: str) -> tuple[float, float]:
    """嵌套 vertex 祖先链平移展开（纯加法；环/坏值显式报错）。"""
    x = y = 0.0
    seen: set[str] = set()
    cur = cell_id
    while cur not in ("", "0") and cur not in seen:
        seen.add(cur)
        node = vertices.get(cur)
        if node is None:
            break  # parent 指向 layer/edge → 由调用方特判（edge 子 label）
        g = node.geometry or {}
        try:
            x += float(g.get("x") or 0)
            y += float(g.get("y") or 0)
        except (TypeError, ValueError) as exc:
            raise DrawioSvgError(
                f"vertex {cell_id!r} 祖先 {cur!r} 几何不可解析") from exc
        cur = node.parent
    return x, y


def _vertex_box(node: _VertexNode, origin: tuple[float, float]
                ) -> tuple[float, float, float, float]:
    """vertex 绝对坐标包围盒 (x, y, w, h)；缺 geometry 显式报错。"""
    g = node.geometry
    if g is None:
        raise DrawioSvgError(f"vertex {node.cell_id!r} 缺 mxGeometry")
    try:
        w = float(g.get("width") or 0)
        h = float(g.get("height") or 0)
    except (TypeError, ValueError) as exc:
        raise DrawioSvgError(
            f"vertex {node.cell_id!r} 宽高不可解析：{g!r}") from exc
    return (origin[0], origin[1], w, h)


def _anchor_points(box_src: tuple[float, float, float, float],
                   box_dst: tuple[float, float, float, float]) -> tuple[
        tuple[float, float], tuple[float, float]]:
    """边端点=矩形边中心锚：水平相邻（x 区间分离且 y 重叠）取左右中点，
    竖直相邻取上下中点，斜向取中心距短者，重叠取两中心。零重算语义=
    纯几何边界判定。"""
    sx, sy, sw, sh = box_src
    tx, ty, tw, th = box_dst
    ov_x = sx < tx + tw and tx < sx + sw
    ov_y = sy < ty + th and ty < sy + sh
    scx, scy = sx + sw / 2.0, sy + sh / 2.0
    tcx, tcy = tx + tw / 2.0, ty + th / 2.0
    if ov_x and ov_y:
        return (scx, scy), (tcx, tcy)
    if not ov_x and ov_y:
        if sx + sw <= tx:
            return (sx + sw, scy), (tx, tcy)
        return (sx, scy), (tx + tw, tcy)
    if ov_x and not ov_y:
        if sy + sh <= ty:
            return (scx, sy + sh), (tcx, ty)
        return (scx, sy), (tcx, ty + th)
    if abs(scx - tcx) >= abs(scy - tcy):
        return (sx + sw, scy), (tx, tcy)
    return (scx, sy + sh), (tcx, ty)


# ── SVG 装配原语 ────────────────────────────────────────────────────────────


def _add(parent: ET.Element, tag: str, attrs: dict[str, str]) -> ET.Element:
    # SVG 侧一律平标签（svg/g/rect/...）+根元素 xmlns 属性声明命名域——
    # 避免 ElementTree ns0: 前缀污染（序列化逐字节确定性）。
    return ET.SubElement(parent, tag, attrs)


def _text_element(parent: ET.Element, x: float, y: float, text: str,
                  smap: dict[str, str], anchor: str, *, bold: bool) -> None:
    """文字块（\\n 分行→tspan 纵排 1.2em；labelBackgroundColor=白晕
    （paint-order stroke 近似——v1 声明非逐位一致）；fontStyle=1 粗体）。"""
    attrs: dict[str, str] = {
        "x": _fmt_num(x), "y": _fmt_num(y),
        "font-family": _parse_color(smap.get("fontFamily"))
        or DEFAULT_FONT_FAMILY,
        "font-size": _fmt_num(smap.get("fontSize"), DEFAULT_FONT_SIZE),
        "fill": _parse_color(smap.get("fontColor")) or "#000000",
        "text-anchor": anchor,
    }
    if bold:
        attrs["font-weight"] = "bold"
    bg = _parse_color(smap.get("labelBackgroundColor"))
    if bg:
        attrs["stroke"] = bg
        attrs["stroke-width"] = "3"
        attrs["paint-order"] = "stroke"
    el = _add(parent, "text", attrs)
    lines = (text or "").split("\n")
    if len(lines) <= 1:
        el.text = lines[0] if lines else ""
        return
    el.text = None
    fs = float(attrs["font-size"])
    try:
        base_y = float(attrs["y"])
    except ValueError:
        base_y = 0.0
    for i, line in enumerate(lines):
        tspan = ET.SubElement(el, "tspan")
        tspan.set("x", attrs["x"])
        tspan.set("y", _fmt_num(base_y + i * 1.2 * fs))
        tspan.text = line


def _arrow(parent: ET.Element, tip: tuple[float, float], angle_deg: float,
           color: str, size: float = 6.0) -> None:
    """三角箭头（classic 同形）。"""
    rad = math.radians(angle_deg)
    tx, ty = tip
    bx = tx - size * math.cos(rad)
    by = ty - size * math.sin(rad)
    px, py = -math.sin(rad), math.cos(rad)
    pts = (f"{_fmt_num(tx)},{_fmt_num(ty)} "
           f"{_fmt_num(bx + px * size * 0.35)},{_fmt_num(by + py * size * 0.35)} "
           f"{_fmt_num(bx - px * size * 0.35)},{_fmt_num(by - py * size * 0.35)}")
    _add(parent, "polygon", {"points": pts, "fill": color})


def _angle_of(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))


# ── 主渲染 ──────────────────────────────────────────────────────────────────


def render_diagram_svg(page: dict[str, Any]) -> tuple[ET.Element, list[str]]:
    """单页结构化 dict（parse_diagram 输出 pages[i]，可含补扫增量）→
    (SVG 根 Element, warnings)。

    负例显式报错：vertices 与 edges 全空 → DrawioSvgError（空页不静默
    出白图）；几何坏值 → DrawioSvgError。
    """
    vertices: dict[str, _VertexNode] = {}
    for v in page["vertices"]:
        vertices[v["id"]] = _VertexNode(v)
    edges = list(page["edges"])
    if not vertices and not edges:
        raise DrawioSvgError(
            f"diagram {page.get('diagram_id')!r} 无可渲染图元"
            "（vertices/edges 全空——空页不静默出白图）")

    layer_rows = {r["id"]: r for r in page.get("layers") or []}
    warnings: list[str] = []

    # 包围盒：layer 直挂/嵌套 vertex 先展开；edge 子 label 后置
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for vid, node in vertices.items():
        if node.parent in vertices or node.parent in ("", "0") \
                or node.parent in layer_rows:
            boxes[vid] = _vertex_box(
                node, _absolute_origin(vertices, vid))

    # edge 线段预演算（端点锚+way points；edge 子 label 与画布兜底消费）
    edge_lines: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}
    for e in edges:
        smap = _parse_style(e["style"])
        src_id, dst_id = e.get("source") or "", e.get("target") or ""
        if src_id not in boxes or dst_id not in boxes:
            continue
        start, end = _anchor_points(boxes[src_id], boxes[dst_id])
        pts = e.get("_points") or []
        resolved: list[tuple[float, float]] = []
        for px_s, py_s in pts:
            try:
                resolved.append((float(px_s), float(py_s)))
            except (TypeError, ValueError) as exc:
                raise DrawioSvgError(
                    f"edge {e['id']!r} way point 不可解析："
                    f"({px_s!r}, {py_s!r})") from exc
        if resolved:
            e["_resolved_points"] = resolved
        edge_lines[e["id"]] = (start, end)

    # edge 子 label vertex：定位=边中点+相对偏移+mxPoint offset
    for vid, node in vertices.items():
        if vid in boxes:
            continue
        line = edge_lines.get(node.parent)
        if line is None:
            raise DrawioSvgError(
                f"vertex {vid!r} parent={node.parent!r} 既非已知 vertex/"
                f"layer 也非可定位 edge（悬空引用）")
        g = node.geometry or {}
        try:
            dx = float(g.get("x") or 0)
            dy = float(g.get("y") or 0)
            w = float(g.get("width") or 0)
            h = float(g.get("height") or 0)
        except (TypeError, ValueError) as exc:
            raise DrawioSvgError(
                f"edge 子 label {vid!r} 几何不可解析：{g!r}") from exc
        off = g.get("_offset") or ("0", "0")
        try:
            ox, oy = float(off[0]), float(off[1])
        except (TypeError, ValueError) as exc:
            raise DrawioSvgError(
                f"edge 子 label {vid!r} offset 不可解析：{off!r}") from exc
        mx = (line[0][0] + line[1][0]) / 2.0
        my = (line[0][1] + line[1][1]) / 2.0
        boxes[vid] = (mx + dx + ox - w / 2.0, my + dy + oy - h / 2.0, w, h)

    # 画布：pageWidth/pageHeight 原属性；缺失按内容包围盒+边距
    page_attrs = page.get("page") or {}
    try:
        pw = float(page_attrs.get("pageWidth"))
        ph = float(page_attrs.get("pageHeight"))
    except (TypeError, ValueError):
        xs: list[float] = []
        ys: list[float] = []
        for (x, y, w, h) in boxes.values():
            xs.extend((x, x + w))
            ys.extend((y, y + h))
        for e in edges:
            for p in e.get("_resolved_points") or ():
                xs.append(p[0])
                ys.append(p[1])
        if xs and ys:
            pw = max(xs) + DEFAULT_MARGIN
            ph = max(ys) + DEFAULT_MARGIN
        else:
            pw, ph = 800.0, 600.0

    svg = ET.Element("svg", {
        "xmlns": _SVG_NS,
        "width": _fmt_num(pw), "height": _fmt_num(ph),
        "viewBox": f"0 0 {_fmt_num(pw)} {_fmt_num(ph)}",
    })
    title = _add(svg, "title", {})
    title.text = (f"{page.get('diagram_name') or page.get('diagram_id') or 'diagram'}"
                  " (rfauto diagram to-svg)")

    groups: dict[str, ET.Element] = {}

    def _group_of(parent_cell: str) -> ET.Element:
        """cell parent → 所属 <g>（layer id 分组；组序=首引用序；
        非 layer parent 归基图层 id=1）。"""
        gid = parent_cell if parent_cell in layer_rows else "1"
        if gid in groups:
            return groups[gid]
        if gid == "1":
            g = _add(svg, "g", {"id": "layer-1"})
            name = (layer_rows.get("1") or {}).get("name") or "1"
        else:
            g = _add(svg, "g", {"id": f"layer-{gid}"})
            name = (layer_rows.get(gid) or {}).get("name") or gid
        t = ET.SubElement(g, "title")
        t.text = name
        groups[gid] = g
        return g

    def _label_pos(node: _VertexNode, box: tuple[float, float, float, float]
                   ) -> tuple[float, float, str]:
        """框内文字定位（缺省=drawio：水平居中/竖直居中；text 形态缺省
        align=left；verticalLabelPosition=bottom → 框下方 12px）。"""
        x, y, w, h = box
        smap = node.style_map
        align = smap.get("align") or (
            "left" if node.is_text_only else "center")
        anchor = {"left": "start", "center": "middle",
                  "right": "end"}.get(align, "start")
        if smap.get("verticalLabelPosition") == "bottom":
            return x + w / 2.0, y + h + 12.0, "middle"
        valign = smap.get("verticalAlign") or "middle"
        n_lines = len((node.value or "").split("\n"))
        fs = float(smap.get("fontSize") or DEFAULT_FONT_SIZE)
        if valign == "top":
            ty = y + fs * 0.9
        elif valign == "bottom":
            ty = y + h - (n_lines - 1) * 1.2 * fs - fs * 0.3
        else:
            ty = y + h / 2.0 - ((n_lines - 1) * 1.2 * fs) / 2.0 + fs * 0.9
        if anchor == "middle":
            tx = x + w / 2.0
        elif anchor == "end":
            tx = x + w - 4.0
        else:
            tx = x + 4.0
        return tx, ty, anchor

    # vertex（渲染序=注册序）
    for vid, node in vertices.items():
        parent_group = _group_of(node.parent if node.parent not in ("", "0")
                                 else "1")
        x, y, w, h = boxes[vid]
        smap = node.style_map
        bold = smap.get("fontStyle") == "1"
        if node.degrade:
            for frag in node.degrade:
                wmsg = (f"cell {vid!r} 含不支持形态（{frag}）"
                        "——降级占位框渲染")
                if wmsg not in warnings:
                    warnings.append(wmsg)
            _add(parent_group, "rect", {
                "x": _fmt_num(x), "y": _fmt_num(y),
                "width": _fmt_num(w), "height": _fmt_num(h),
                "fill": "none", "stroke": "#999999",
                "stroke-width": "1", "stroke-dasharray": "4 3",
            })
            if node.value:
                tx, ty, anchor = _label_pos(node, boxes[vid])
                _text_element(parent_group, tx, ty, node.value, smap,
                              anchor, bold=bold)
            continue
        if node.is_text_only:
            tx, ty, anchor = _label_pos(node, boxes[vid])
            _text_element(parent_group, tx, ty, node.value, smap, anchor,
                          bold=bold)
            continue
        fill = _parse_color(smap.get("fillColor"))
        stroke = _parse_color(smap.get("strokeColor"))
        common: dict[str, str] = {}
        if fill is not None:
            common["fill"] = fill
        else:
            common["fill"] = "#ffffff"  # drawio 缺省白底（stylesheet 实读）
        if smap.get("fillOpacity"):
            common["fill-opacity"] = _fmt_num(
                float(smap["fillOpacity"]) / 100.0)
        if smap.get("opacity"):
            common["opacity"] = _fmt_num(smap["opacity"])
        if stroke is not None:
            common["stroke"] = stroke
            common["stroke-width"] = _fmt_num(
                smap.get("strokeWidth"), 1.0)
        else:
            common["stroke"] = "#000000"  # drawio 缺省黑框
            common["stroke-width"] = "1"
        if node.is_ellipse:
            _add(parent_group, "ellipse", {
                "cx": _fmt_num(x + w / 2.0), "cy": _fmt_num(y + h / 2.0),
                "rx": _fmt_num(w / 2.0), "ry": _fmt_num(h / 2.0), **common})
        else:
            shape_attrs = dict(common)
            shape_attrs["x"] = _fmt_num(x)
            shape_attrs["y"] = _fmt_num(y)
            shape_attrs["width"] = _fmt_num(w)
            shape_attrs["height"] = _fmt_num(h)
            shape_attrs["rx"] = "6" if smap.get("rounded") == "1" else "0"
            if smap.get("dashed") == "1":
                shape_attrs["stroke-dasharray"] = "3 3"
            _add(parent_group, "rect", shape_attrs)
        if node.value:
            tx, ty, anchor = _label_pos(node, boxes[vid])
            _text_element(parent_group, tx, ty, node.value, smap, anchor,
                          bold=bold)

    # edge（渲染序=注册序；端点锚+way points 直映射）
    for e in edges:
        parent_group = _group_of(e["parent"] if e["parent"] not in ("", "0")
                                 else "1")
        smap = _parse_style(e["style"])
        for frag in _unsupported_fragments(smap):
            wmsg = f"edge {e['id']!r} 含不支持形态（{frag}）——直线降级渲染"
            if wmsg not in warnings:
                warnings.append(wmsg)
        line = edge_lines.get(e["id"])
        if line is None:
            warnings.append(
                f"edge {e['id']!r} 端点缺失（source={e.get('source')!r} "
                f"target={e.get('target')!r}）——不渲染")
            continue
        start, end = line
        resolved = e.get("_resolved_points") or []
        stroke = _parse_color(smap.get("strokeColor")) or "#000000"
        stroke_w = _fmt_num(smap.get("strokeWidth"), 1.0)
        if resolved:
            pts = [start, *resolved, end]
            poly = _add(parent_group, "polyline", {
                "points": " ".join(f"{_fmt_num(px)},{_fmt_num(py)}"
                                   for px, py in pts),
                "fill": "none", "stroke": stroke, "stroke-width": stroke_w,
            })
            if smap.get("dashed") == "1":
                poly.set("stroke-dasharray", "3 3")
            # label 中点=中间段中点（way points 折线的视觉中点）
            mid_idx = len(pts) // 2
            mx = (pts[mid_idx - 1][0] + pts[mid_idx][0]) / 2.0
            my = (pts[mid_idx - 1][1] + pts[mid_idx][1]) / 2.0
        else:
            ln = _add(parent_group, "line", {
                "x1": _fmt_num(start[0]), "y1": _fmt_num(start[1]),
                "x2": _fmt_num(end[0]), "y2": _fmt_num(end[1]),
                "stroke": stroke, "stroke-width": stroke_w,
            })
            if smap.get("dashed") == "1":
                ln.set("stroke-dasharray", "3 3")
            mx, my = (start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0
        if smap.get("endArrow", "classic") != "none":
            tail = resolved[-1] if resolved else start
            _arrow(parent_group, end, _angle_of(tail, end), stroke)
        if smap.get("startArrow", "none") != "none":
            tail = resolved[0] if resolved else end
            _arrow(parent_group, start, _angle_of(tail, start), stroke)
        if e.get("value"):
            off = e.get("_offset") or ("0", "0")
            try:
                mx += float(off[0])
                my += float(off[1])
            except (TypeError, ValueError) as exc:
                raise DrawioSvgError(
                    f"edge {e['id']!r} label offset 不可解析：{off!r}"
                ) from exc
            _text_element(parent_group, mx, my, e["value"], smap, "middle",
                          bold=smap.get("fontStyle") == "1")

    return svg, warnings


def render_xml_text(xml_text: str, page_index: int = 0
                    ) -> tuple[str, dict[str, Any]]:
    """.drawio XML 文本 → (SVG 文本, 统计 dict)。

    统计：n_vertices/n_edges/n_layers（渲染面实数，含 UserObject 包装
    与 edge 子 label 补扫增量）/n_pages/n_degraded/warnings（去重保序）。
    负例：页序越界/空页 → DrawioSvgError；坏 XML/压缩页 →
    DrawioReadError（drawio_xml 原样透传）。
    """
    doc = parse_diagram(xml_text)
    # 补扫在工作副本上进行（不改 parse_diagram 语义，不动 drawio_xml）
    raw_root = ET.fromstring(xml_text)
    for diagram_el, page in zip(raw_root.findall("diagram"), doc["pages"],
                                strict=False):
        model = diagram_el.find("mxGraphModel")
        if model is not None:
            _supplement_page(model, page)
    pages = doc["pages"]
    if page_index < 0 or page_index >= len(pages):
        raise DrawioSvgError(
            f"page_index {page_index} 越界（n_pages={len(pages)}）")
    page = pages[page_index]
    svg, warnings = render_diagram_svg(page)
    ET.indent(svg, space="  ")
    svg_text = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                + ET.tostring(svg, encoding="unicode") + "\n")
    n_degraded = 0
    for v in page["vertices"]:
        if _unsupported_fragments(_parse_style(v["style"])):
            n_degraded += 1
    for e in page["edges"]:
        if _unsupported_fragments(_parse_style(e["style"])):
            n_degraded += 1
    stats = {
        "n_vertices": len(page["vertices"]),
        "n_edges": len(page["edges"]),
        "n_layers": len(page.get("layers") or []),
        "n_pages": doc["n_pages"],
        "diagram_name": page.get("diagram_name") or "",
        "n_degraded": n_degraded,
        "warnings": warnings,
    }
    return svg_text, stats
