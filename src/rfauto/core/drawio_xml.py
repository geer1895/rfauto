"""通用 drawio (mxGraph XML) 文档装配与回读内核（T-O2 从 link_diagram 抽取）。

XML 格式出处（实读 2026-10-31 T-O1 席 / 2026-11-01 T-O2 席；见
core/link_diagram.py docstring 与 runs/aurora_o/recon/drawio_format_notes.md）：
``mxfile > diagram > mxGraphModel > root > mxCell``——root 恒含 ``id="0"``
与 ``id="1" parent="0"`` 两个基 cell；vertex 带
``<mxGeometry x= y= width= height= as="geometry"/>``；edge 带
``edge="1" source= target=`` + ``<mxGeometry relative="1" as="geometry"/>``。
产物为**未压缩**原生 mxfile XML（官方缺省，draw.io 桌面/网页/VS Code
插件可直接打开编辑）。许可红线同 T-O1：自研 ElementTree 装配器，零第三方
依赖、零复制（AGPL 的 drawio-engineering-mcp 代码不看不抄）。

抽取关系（T-O2，2026-11-01）：本模块是 T-O1 link_diagram.py 中 mxGraph XML
装配骨架（文档结构/cell 基座/几何与连线语义/ET.indent/确定性 id+属性序）
的**通用化抽取**——link 语义（布局常量/级标签/Friis 数字消费）留在
link_diagram.py，XML 骨架装配下沉至此。抽取门 = link_diagram 既有 26 钉
测试**零改动全绿**（XML 输出逐字节不变）。

消费预留（后续席位一律走本内核，禁止再各写 XML 装配）：
- T-O3 叠层图渲染器（service/diagram_stackup_service）；
- T-O4 ADS 前仿链（可调电路图生成/人工改值回读——read 面主消费者）；
- T-O6 测试连接图（service/diagram_testsetup_service）；
- T-O8 评审标注面（底图锁定层+标注层——read 面 layers 键消费者）。

写面 API（:class:`DrawioDocument`）：``new_document`` 建骨架（mxfile/
diagram/mxGraphModel/root + 基 cell 0/1），``add_vertex``/``add_edge`` 加
图元（确定性 id 由调用方给定，重复 id 显式报错；悬空 edge 引用在
``to_xml`` 时守卫报错），``to_xml``/``write_document`` 出文本/落盘。
确定性：同输入两次构建 XML 逐字节相同——id 调用方给定（禁 uuid）、
无时间戳、ElementTree 属性序=插入序、``ET.indent(space="  ")`` 幂等。

read 面（:func:`read_diagram` / :func:`parse_diagram`）：.drawio → 结构化
dict（``pages[].page``=mxGraphModel 页面属性、``vertices``/``edges``=mxCell
解析、``layers``=parent="0" 容器 cell）。属性值一律**原样字符串**返回
（不静默做数值强转——消费方按需 float()，#121 跨源比较显式归一口径）。
负例显式报错（:class:`DrawioReadError`）：坏 XML / 非 mxfile 根 / 缺
diagram / 缺 mxGraphModel（含压缩页）/ 缺 root / 缺基 cell id=0。

边界（v1 如实声明）：read 面面向**本内核产出的未压缩 mxfile**（mxCell 为
root 直接子元素；UserObject 包装形态不支持，自定义参数标注走 ``extra_attrs``
直写 mxCell 属性——等价可读回）；draw.io 官方压缩页（diagram 内 base64）
显式不支持——缺 mxGraphModel 时报 DrawioReadError 而非静默空图。

零公式（铁律 7）：本模块零物理/数值语义——数字全部由调用方内核产出后
以文本传入；本模块只做"结构装配 + 结构回读"。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_PAGE_ATTRS",
    "DrawioDocument",
    "DrawioReadError",
    "new_document",
    "page_attrs",
    "parse_diagram",
    "read_diagram",
    "write_document",
]

#: mxGraphModel 页面属性缺省值（A4 纵向栅格页；与 T-O1 link 图产出一致，
#: 键序=属性写出序，确定性）。改动缺省 = 翻写面产出字节 = 显式评审动作。
DEFAULT_PAGE_ATTRS: dict[str, str] = {
    "dx": "1420", "dy": "800", "grid": "1", "gridSize": "10",
    "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1",
    "fold": "1", "page": "1", "pageScale": "1",
    "pageWidth": "1169", "pageHeight": "826", "math": "0", "shadow": "0",
}

#: mxfile 文档级属性缺省值（host/type/version；键序=属性写出序）
_MXFILE_ATTRS: dict[str, str] = {
    "host": "rfauto", "type": "device", "version": "24.7.7",
}


class DrawioReadError(ValueError):
    """read 面显式错误（坏 XML/缺骨架/文件不可读）——ValueError 子类，
    service 层错误信封（except ValueError）可直接捕获，不静默不凑绿。"""


def _attr_text(value: Any, name: str) -> str:
    """属性值 → 文本（str 原样；数值 str() 渲染——文本形态由调用方控制）。

    bool 显式拒绝（bool 是 int 子类，str(True)="True" 落图必是手误）；
    其余类型 str() 收敛（调用方传 float 时 "1.5" 形态自负——要固定位数
    请先格式化或直接传 str，本内核不做静默舍入）。
    """
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是 str/int/float，收到 bool {value!r}")
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        out = str(value)
        if "nan" in out.lower() or "inf" in out.lower():
            raise ValueError(f"{name} 必须为有限数值，收到 {value!r}")
        return out
    return str(value)


def page_attrs(**overrides: Any) -> dict[str, str]:
    """页面属性串构造器：缺省 :data:`DEFAULT_PAGE_ATTRS` + 覆盖键合并。

    返回新 dict（不改缺省常量）；键序=缺省序、新增覆盖键附尾——确定性。
    例：``page_attrs(pageWidth="1587", pageHeight="2245")``（A3 纵向）。
    """
    out = dict(DEFAULT_PAGE_ATTRS)
    for key, val in overrides.items():
        out[key] = _attr_text(val, f"page.{key}")
    return out


class DrawioDocument:
    """未压缩 mxfile 文档骨架装配器（写面；确定性逐字节）。

    结构：``mxfile > diagram > mxGraphModel > root > [基 cell 0/1, 图元…]``。
    cell id 由调用方给定（确定性 id 管理——按业务语义命名如 stage0/edge0，
    禁 uuid/时间戳）；重复 id 显式 ValueError。
    """

    def __init__(
        self,
        *,
        diagram_id: str,
        diagram_name: str,
        page: dict[str, str] | None = None,
        mxfile_attrs: dict[str, str] | None = None,
    ) -> None:
        if not isinstance(diagram_id, str) or not diagram_id.strip():
            raise ValueError(f"diagram_id 必须是非空字符串，收到 {diagram_id!r}")
        if not isinstance(diagram_name, str) or not diagram_name.strip():
            raise ValueError(
                f"diagram_name 必须是非空字符串，收到 {diagram_name!r}")
        self._mxfile = ET.Element(
            "mxfile", dict(mxfile_attrs) if mxfile_attrs else dict(_MXFILE_ATTRS))
        self._diagram = ET.SubElement(self._mxfile, "diagram",
                                      {"id": diagram_id, "name": diagram_name})
        self._model = ET.SubElement(self._diagram, "mxGraphModel",
                                    dict(page) if page else dict(DEFAULT_PAGE_ATTRS))
        self._root = ET.SubElement(self._model, "root")
        # mxGraph 基 cell：id=0（画布根）与 id=1（缺省图层，parent=0）
        ET.SubElement(self._root, "mxCell", {"id": "0"})
        ET.SubElement(self._root, "mxCell", {"id": "1", "parent": "0"})
        self._ids = {"0", "1"}
        self._edges: list[ET.Element] = []

    # ── 图元装配 ────────────────────────────────────────────────────────

    def _check_id(self, cell_id: str) -> None:
        if not isinstance(cell_id, str) or not cell_id.strip():
            raise ValueError(f"cell id 必须是非空字符串，收到 {cell_id!r}")
        if cell_id in self._ids:
            raise ValueError(f"cell id 重复：{cell_id!r}（id 由调用方确定性管理）")

    def add_vertex(
        self,
        cell_id: str,
        value: Any,
        *,
        style: str = "",
        x: Any,
        y: Any,
        width: Any,
        height: Any,
        parent: str = "1",
        extra_attrs: dict[str, Any] | None = None,
    ) -> ET.Element:
        """加 vertex cell（矩形/文本等块面图元；每 cell 必带 mxGeometry）。

        x/y/width/height 文本形态：str 原样、数值 str() 渲染（不静默舍入）。
        ``extra_attrs``：自定义属性（T-O4 元件标注 type/value/unit/param_key
        类；UserObject 包装形态 v1 不做——直接 mxCell 属性等价可读回）。
        返回 mxCell 元素（调用方可再挂子元素——如 mxPoint；挂完本元素即定格，
        ``to_xml`` 幂等可多次调用）。
        """
        self._check_id(cell_id)
        cell = ET.SubElement(self._root, "mxCell", {
            "id": cell_id, "value": _attr_text(value, f"{cell_id}.value"),
            "style": _attr_text(style, f"{cell_id}.style"),
            "vertex": "1", "parent": parent})
        ET.SubElement(cell, "mxGeometry", {
            "x": _attr_text(x, f"{cell_id}.x"),
            "y": _attr_text(y, f"{cell_id}.y"),
            "width": _attr_text(width, f"{cell_id}.width"),
            "height": _attr_text(height, f"{cell_id}.height"),
            "as": "geometry"})
        self._apply_extra_attrs(cell, cell_id, extra_attrs)
        self._ids.add(cell_id)
        return cell

    #: mxCell 结构性固定属性（extra_attrs 不得覆盖——防语义键被手误冲掉）
    _FIXED_CELL_ATTRS = frozenset({
        "id", "value", "style", "vertex", "edge", "parent", "source",
        "target"})

    def _apply_extra_attrs(self, cell: ET.Element, cell_id: str,
                           extra_attrs: dict[str, Any] | None) -> None:
        """附加自定义属性（UserObject 式参数标注；追加在固定属性之后，
        键序=传入序——确定性）。结构性键冲突显式报错。"""
        if not extra_attrs:
            return
        for key, val in extra_attrs.items():
            if key in self._FIXED_CELL_ATTRS:
                raise ValueError(
                    f"cell {cell_id!r} extra_attrs 键 {key!r} 与结构性固定"
                    "属性冲突（禁覆盖）")
            cell.set(key, _attr_text(val, f"{cell_id}.{key}"))

    def add_layer(
        self,
        cell_id: str,
        *,
        name: str = "",
        locked: str | None = None,
        style: str = "",
    ) -> ET.Element:
        """加图层容器 cell（parent="0"；无 vertex/edge 标志、无 geometry）。

        T-O8 评审标注预留：底图层 ``locked="1"`` 锁定 + 标注层可写；
        后续图元以 ``parent=<layer_id>`` 挂到该层（缺省 parent="1" 即
        基图层）。read 面 ``layers`` 键回读 name/locked（原样字符串）。
        """
        self._check_id(cell_id)
        attrs: dict[str, str] = {
            "id": cell_id, "name": _attr_text(name, f"{cell_id}.name"),
            "style": _attr_text(style, f"{cell_id}.style"), "parent": "0"}
        if locked is not None:
            attrs["locked"] = _attr_text(locked, f"{cell_id}.locked")
        cell = ET.SubElement(self._root, "mxCell", attrs)
        self._ids.add(cell_id)
        return cell

    def add_edge(
        self,
        cell_id: str,
        value: Any = "",
        *,
        style: str = "",
        source: str,
        target: str,
        parent: str = "1",
        extra_attrs: dict[str, Any] | None = None,
    ) -> ET.Element:
        """加 edge cell（连线；source/target 必带，悬空引用在 to_xml 守卫）。

        几何固定 ``<mxGeometry relative="1" as="geometry"/>``（drawio 边惯例）。
        ``extra_attrs``：自定义属性（T-O4 参数标注 param_key/value/unit 类）。
        """
        self._check_id(cell_id)
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError(
                f"edge {cell_id!r} source/target 必须是 cell id 字符串")
        cell = ET.SubElement(self._root, "mxCell", {
            "id": cell_id, "value": _attr_text(value, f"{cell_id}.value"),
            "style": _attr_text(style, f"{cell_id}.style"),
            "edge": "1", "parent": parent, "source": source, "target": target})
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        self._apply_extra_attrs(cell, cell_id, extra_attrs)
        self._ids.add(cell_id)
        self._edges.append(cell)
        return cell

    # ── 产出 ────────────────────────────────────────────────────────────

    def to_xml(self) -> str:
        """装配 → 完整 .drawio XML 文本（未压缩原生 mxfile，逐字节确定性）。

        悬空引用守卫：任一 edge 的 source/target 不在已登记 id 集 →
        ValueError（draw.io viewer 语义：连线端点必须引用存在 cell）。
        ``ET.indent`` 对已缩进树幂等——本方法可重复调用，结果逐字节相同。
        """
        for edge in self._edges:
            for end in ("source", "target"):
                ref = edge.get(end) or ""
                if ref not in self._ids:
                    raise ValueError(
                        f"edge {edge.get('id')!r} {end} 悬空：{ref!r} "
                        "不在已登记 cell id 集")
        ET.indent(self._mxfile, space="  ")
        xml_text = ET.tostring(self._mxfile, encoding="unicode")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_text + "\n"

    def write(self, path: Any) -> Path:
        """装配并落盘（UTF-8；父目录须已存在，不自动建目录——显式报错）。"""
        return write_document(self, path)


def new_document(
    *,
    diagram_id: str,
    diagram_name: str,
    page: dict[str, str] | None = None,
    mxfile_attrs: dict[str, str] | None = None,
) -> DrawioDocument:
    """新建空文档骨架（mxfile>diagram>mxGraphModel>root + 基 cell 0/1）。

    Args:
        diagram_id: diagram 元素 id（确定性，按图族命名如 "link-diagram"）。
        diagram_name: 页签显示名。
        page: mxGraphModel 页面属性（None=缺省；覆盖用 :func:`page_attrs`）。
        mxfile_attrs: mxfile 文档属性（None=缺省 host/type/version）。
    """
    return DrawioDocument(diagram_id=diagram_id, diagram_name=diagram_name,
                          page=page, mxfile_attrs=mxfile_attrs)


def write_document(document: DrawioDocument, path: Any) -> Path:
    """文档落盘（UTF-8 文本；不自动建目录，IO 错误显式抛出）。"""
    out = Path(path)  # PathLike 入参第一行收敛（#140）
    out.write_text(document.to_xml(), encoding="utf-8")
    return out


# ─── read 面：.drawio → 结构化 dict ────────────────────────────────────────


def _cell_view(cell: ET.Element) -> dict[str, Any]:
    """mxCell → 轻量 dict（属性原样字符串；缺属性回 ""/None 不静默造值）。

    ``attrs`` = 全部原始属性（含自定义参数标注键——T-O4 改值回读消费面）。
    """
    view: dict[str, Any] = {
        "id": cell.get("id") or "",
        "parent": cell.get("parent") or "",
        "value": cell.get("value") or "",
        "style": cell.get("style") or "",
        "attrs": dict(cell.attrib),
    }
    geom = cell.find("mxGeometry")
    if cell.get("vertex") == "1":
        view["geometry"] = None if geom is None else {
            "x": geom.get("x"), "y": geom.get("y"),
            "width": geom.get("width"), "height": geom.get("height"),
        }
    if cell.get("edge") == "1":
        view["source"] = cell.get("source") or ""
        view["target"] = cell.get("target") or ""
    return view


def _parse_page(diagram: ET.Element) -> dict[str, Any]:
    """单个 diagram 元素 → 页 dict（页面属性 + vertices/edges/layers）。"""
    model = diagram.find("mxGraphModel")
    if model is None:
        raise DrawioReadError(
            f"diagram {diagram.get('id')!r} 缺 mxGraphModel"
            "（压缩页或非本内核产物不支持——read 面面向未压缩 mxfile）")
    mx_root = model.find("root")
    if mx_root is None:
        raise DrawioReadError(
            f"diagram {diagram.get('id')!r} 缺 root 元素（mxGraph 骨架不完整）")
    cells = mx_root.findall("mxCell")
    ids = {c.get("id") for c in cells}
    if "0" not in ids:
        raise DrawioReadError(
            f"diagram {diagram.get('id')!r} root 缺基 cell id=0（mxGraph 骨架不完整）")
    vertices: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    layers: list[dict[str, Any]] = []
    for cell in cells:
        if cell.get("vertex") == "1":
            vertices.append(_cell_view(cell))
        elif cell.get("edge") == "1":
            edges.append(_cell_view(cell))
        elif (cell.get("parent") or "") == "0" and cell.get("id") != "0":
            # 图层容器 cell（含基 cell id=1；locked 属性原样透出供 T-O8）
            layers.append({
                "id": cell.get("id") or "",
                "name": cell.get("name") or "",
                "locked": cell.get("locked"),
            })
    return {
        "diagram_id": diagram.get("id") or "",
        "diagram_name": diagram.get("name") or "",
        "page": dict(model.attrib),
        "vertices": vertices,
        "edges": edges,
        "layers": layers,
    }


def parse_diagram(xml_text: str) -> dict[str, Any]:
    """.drawio XML 文本 → 结构化 dict（read 面；坏骨架显式 DrawioReadError）。

    Returns::

        {"pages": [{"diagram_id", "diagram_name",
                    "page": {mxGraphModel 页面属性原样字符串},
                    "vertices": [{id, parent, value, style, geometry?}, ...],
                    "edges": [{id, parent, value, style, source, target}, ...],
                    "layers": [{id, name, locked?}, ...]}, ...],
         "n_pages": int}

    属性值一律原样字符串（不静默强转数值）；v1 单页图取 ``pages[0]``。
    """
    if not isinstance(xml_text, str):
        raise DrawioReadError(
            f"xml_text 必须是字符串，收到 {type(xml_text)!r}")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise DrawioReadError(f"XML 解析失败：{exc}") from exc
    if root.tag != "mxfile":
        raise DrawioReadError(f"根元素必须是 mxfile，收到 {root.tag!r}")
    diagrams = root.findall("diagram")
    if not diagrams:
        raise DrawioReadError("缺 diagram 元素（mxGraph 骨架不完整）")
    pages = [_parse_page(d) for d in diagrams]
    return {"pages": pages, "n_pages": len(pages)}


def read_diagram(path: Any) -> dict[str, Any]:
    """.drawio 文件 → 结构化 dict（:func:`parse_diagram` 的文件入口）。

    文件不存在/不可读/非 UTF-8 显式 :class:`DrawioReadError`（ValueError
    子类——service 层错误信封直接捕获）。
    """
    p = Path(path)  # PathLike 入参第一行收敛（#140）
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DrawioReadError(
            f"读取失败 {p}：{type(exc).__name__}: {exc}") from exc
    return parse_diagram(text)
