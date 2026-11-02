"""PCB 叠层横截面图 .drawio 生成器（T-O3：声明式叠层 → 原生可编辑 mxGraph 工程图）。

"算画同源"第四件（T-O1 链路框图=Friis 数字单源、T-O6 测试连接图=声明式
零换算一极、T-O8 评审标注=双层底图锁定）：本模块与 T-O6 同极——**纯声明
式生成器**，图上若出现"数字"只有两类，全部原样标图零换算（铁律 7）：

1. 层带标注 = 用户 JSON 显式给的 material/thickness_mm/er（材料名/厚度/
   介电常数原值文本化）+ zmin（自顶累计深度——本模块内确定性加法
   ``zmin_i = Σ thickness_mm[0..i-1]``，非物理公式，round 6 位后经
   :func:`format_number` 文本化）；
2. 线宽标注 = ``width_annotations`` 用户显式给值**或**合成引擎单源值
   （service 层 :func:`rfauto.service.diagram_stackup_service.
   synthesis_width_annotation` 调 ``core/synthesis.nominal_width_mm``
   ——数字只从该确定性综合内核流入标注 dict，本模块零线宽公式）。

第一验收面=**几何正确性**：层带高度∝thickness 比例尺（每层
``height_px = round(thickness_mm·px_per_mm, 6)``，比例常数
:data:`PX_PER_MM` 单源）+ 层序=声明序自顶向下逐带堆叠；全部可从 XML
geometry 回读断言。薄带（细铜箔缩放后 <6px）不 clamp 不失真——warnings
如实提示（比例失真才是画假图），draw.io 放大查看。

XML 装配走 T-O2 通用内核 :mod:`rfauto.core.drawio_xml`（DrawioDocument
写面；本模块禁止另写文档级装配器）。形态出处（T-O1/T-O6 家法）：

- 层带 = mxCell vertex（``layer<i>`` id 按声明索引生成，禁 uuid），
  kind→颜色查表（:data:`KIND_TABLE` 单源）：signal=红（铜箔走线）/
  plane=橙（铜面）/dielectric=蓝（基板介质），经典色板与 T-O6 同族；
- 层标注 = 带右侧文本卡（``layer<i>.label``，三行=名称（kind）/
  材料  厚度 mm  εr 值 / z=累计 mm）+ 引线（``layer<i>.leader``，虚线
  无箭头 edge：卡左中→带右中）。标注列**贪心非叠**：理想位=居中于带，
  与上一卡净距不足 :data:`LABEL_VGAP` 则下移（只下移不上移，标注序=
  层序）——薄铜带中心仅隔数 px 而卡高 42px，居中直放必互叠不可读，
  下移卡由引线连回本带（叠层图标注惯例）；
- 线宽标注 = 双锚点不可见 vertex（``w<i>.a``/``w<i>.b``）+ 双箭头 edge
  （``w<i>``，箭长=width_mm×同一比例尺，横向落在层带左段），标签=
  ``<宽> mm  <note>``（两空格分隔=T-O6 cable 同族约定），白底+法向
  上移 12px（mxGeometry 子 mxPoint as="offset"——带再薄标签也可读）；
- 标题 = ``title`` 文本 cell（显式 title > 场景 title > 缺省标题）。

确定性：同输入两次构建 XML 逐字节相同——cell id 全部确定性命名、零
时间戳、几何数值 round 6 位后 str()（无 repr 长尾）。标注数值文本
单源 = :func:`format_number`（XML 装配与测试断言消费同一函数；整数
值不带小数点，非整数值=输入原值最短往返表示）。

零换算红线：装配代码路径零对数/幂/三角调用（测试 grep 面钉死）；
比例尺乘法与 zmin 加法是布局几何非数值换算，标注文本只含输入原值与
zmin 累计和，不含任何派生物理量。

零 IO（纯函数返回 XML 文本与 plan dict；落盘在 service 层）、零第三方
依赖（仅 xml.etree 标准库 + 同层 core.drawio_xml）。
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any

from rfauto.core.drawio_xml import DEFAULT_PAGE_ATTRS, new_document, page_attrs

__all__ = [
    "KIND_TABLE",
    "PX_PER_MM",
    "build_stackup_diagram_xml",
    "build_stackup_plan",
    "format_number",
    "normalize_stackup",
]

# ─── 常量单源（kind→颜色查表/布局几何 = 本模块单源，测试逐键断言） ──────────

#: kind 枚举（v1 定死 3 个，未知 kind 显式 ValueError——不静默 generic）→
#: (fillColor, strokeColor)（drawio 经典色板；signal 走线/plane 铜面/
#: dielectric 基板介质）
KIND_TABLE: dict[str, tuple[str, str]] = {
    "signal": ("#f8cecc", "#b85450"),
    "plane": ("#ffe6cc", "#d79b00"),
    "dielectric": ("#dae8fc", "#6c8ebf"),
}

#: 比例尺（px/mm 单源）：层带高度与线宽箭头长度共用同一比例尺——
#: "高度∝thickness" 断言与"箭长=width×比例尺"断言的公共常数。取 200：
#: 1oz 铜箔 35µm→7px（过 6px 可见阈值）、1.6mm 板→320px（A4 页内），
#: 仅 ≤0.5oz 薄铜触发薄带提示（如实）
PX_PER_MM = 200.0

#: 布局几何（px）：层带 x/宽、堆叠起点 y、右侧标注列几何
STACK_X = 160
STACK_W = 320
STACK_Y0 = 100
LABEL_GAP = 24          # 标注列与层带右缘间距
LABEL_W = 280
LABEL_H = 42
#: 标注列行间最小净距（px）：薄铜带中心仅隔数 px，标注卡 42px 高——
#: 理想位（居中于带）互叠时贪心下移，下移的标注由引线连回本带
LABEL_VGAP = 4
_TITLE_Y = 20
_TITLE_W = 520
_TITLE_H = 26
_MARGIN_X = 40
_PAGE_BOTTOM_PAD = 40

#: 薄带可见性提示阈值（px；低于它 warnings 提示放大查看——高度不 clamp，
#: 比例失真才是画假图）
_MIN_VISIBLE_PX = 6.0

#: 线宽箭头锚点尺寸（px；不可见锚点 cell，双箭头 edge 的几何端子）
_ANCHOR_SIZE = 2
#: 线宽标签相对箭头的法向偏移（px，负=上方；落在带外/白底可读）
_WIDTH_LABEL_OFFSET_Y = -12

#: 缺省标题模板（比例尺取实际 px_per_mm——标题文本与几何同源不撒谎）
_DEFAULT_TITLE_FMT = ("PCB 叠层横截面图（声明式输入；层带高度∝厚度，"
                      "比例尺 {scale}px/mm）")

#: 样式串（T-O1/T-O6 同族）
_TITLE_STYLE = ("text;html=1;strokeColor=none;fillColor=none;align=left;"
                "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontStyle=1")
_LABEL_STYLE = ("text;html=1;strokeColor=none;fillColor=none;align=left;"
                "verticalAlign=middle;whiteSpace=wrap;rounded=0;")
_ANCHOR_STYLE = "ellipse;html=1;fillColor=none;strokeColor=none;"
_WIDTH_EDGE_STYLE = ("endArrow=classic;startArrow=classic;endFill=1;"
                     "startFill=1;html=1;fontSize=10;strokeColor=#b85450;"
                     "labelBackgroundColor=#ffffff;")
#: 引线（标注卡左中 → 层带右中；虚线无箭头，T-O6 锚边同族灰）
_LEADER_STYLE = ("endArrow=none;dashed=1;html=1;strokeColor=#999999;"
                 "exitX=0;exitY=0.5;exitDx=0;exitDy=0;"
                 "entryX=1;entryY=0.5;entryDx=0;entryDy=0;")


def _band_style(fill: str, stroke: str) -> str:
    return f"rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"


#: warnings 文案（信封逐条可断言，固定顺序=确定性）
_WARN_THIN_BAND = (
    "层 {name!r} 带高 {h}px（<{th}px 可见阈值；高度仍∝厚度不失真，"
    "draw.io 需放大查看）")
_WARN_NO_DIELECTRIC = "无介质层（纯导体声明；横截面仍按输入渲染）"
_WARN_NO_CONDUCTOR = "无导体层（signal/plane 全无；纯介质堆叠）"
_WARN_WIDTH_OVER_BAND = (
    "线宽标注 {i}（层 {layer!r}）箭头长 {arrow}px 超出层带宽 "
    "{band_w}px（同比例尺横向绘制，视觉延伸出带）")


# ─── 标注数值文本单源（零换算） ─────────────────────────────────────────────


def format_number(value: Any) -> str:
    """标注数值 → 文本（格式化单源：XML 装配与测试断言消费同一函数）。

    分档：整数值（int 或 ``is_integer()`` 的 float）不带小数点
    （0.2mm·200px=40px 同理 1.0→"1"）；非整数值=输入原值最短往返表示
    （0.5→"0.5"、1.1134→"1.1134"）。**零换算**：本函数不做任何单位/
    dB 运算（铁律 7：输入给什么写什么）。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"标注数值必须是 int/float，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"标注数值必须为有限实数，收到 {value!r}")
    if out.is_integer():
        return str(int(out))
    return str(out)


def _finite(value: Any, name: str) -> float:
    """收敛入参为有限实数，否则 ValueError（bool 不算数——bool 是 int 子类）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


# ─── schema 严格校验（normalize_scene 家法：严格键+枚举+负例显式） ──────────

_STACKUP_KEYS = {"title", "layers", "width_annotations"}
_LAYER_KEYS = {"name", "kind", "thickness_mm", "material", "er"}
_LAYER_REQUIRED = ("name", "kind", "thickness_mm")
_WIDTH_KEYS = {"layer", "width_mm", "note"}
_WIDTH_REQUIRED = ("layer", "width_mm")


def _check_no_extra(raw: dict, allowed: set[str], where: str,
                    schema_desc: str) -> None:
    extra = set(raw) - allowed
    if extra:
        raise ValueError(
            f"{where} 存在未支持键 {sorted(extra)}；{schema_desc}")


def _check_str_nonempty(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} 必须是非空字符串，收到 {value!r}")
    return value


def normalize_stackup(stackup: Any) -> dict[str, Any]:
    """校验并归一声明式叠层（非法入参显式 ValueError，不静默）。

    顶层三键::

        {"title": str 可省, "layers": [<层>...] 必填非空,
         "width_annotations": [<线宽标注>...] 允许空}

    层卡严格五键 name/kind/thickness_mm/material/er（前三必填；
    material/er 可省）。线宽标注严格三键 layer/width_mm/note
    （前两必填；note 可省）。

    负例（均显式报错）：非 dict/缺 layers/空 layers/多余键/未知 kind/
    厚度非有限实数或 ≤0/er 非有限或 <1（真空下界）/material 非 str/
    层名空或重名/线宽标注引用不存在层名/线宽标注落介质层（线宽属于
    导体）/width_mm 非有限或 ≤0/note 非 str。
    """
    if not isinstance(stackup, dict):
        raise ValueError(f"stackup 必须是 dict，收到 {type(stackup)!r}")
    _check_no_extra(stackup, _STACKUP_KEYS, "stackup",
                    "顶层 schema 严格三键 title/layers/width_annotations")
    title = None
    if stackup.get("title") is not None:
        title = _check_str_nonempty(stackup["title"], "stackup.title")

    raw_layers = stackup.get("layers")
    if not isinstance(raw_layers, (list, tuple)) or len(raw_layers) == 0:
        raise ValueError("stackup.layers 必须是非空层卡列表")
    layers: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for i, raw in enumerate(raw_layers):
        where = f"layers[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} 必须是 dict，收到 {type(raw)!r}")
        _check_no_extra(raw, _LAYER_KEYS, where,
                        "层卡 schema 严格五键 name/kind/thickness_mm/"
                        "material/er")
        for key in _LAYER_REQUIRED:
            if key not in raw or raw[key] is None:
                raise ValueError(f"{where} 缺必填键 {key!r}")
        name = _check_str_nonempty(raw["name"], f"{where}.name")
        if name in seen_names:
            raise ValueError(f"{where}.name 层名重名：{name!r}")
        seen_names.add(name)
        kind = raw["kind"]
        if kind not in KIND_TABLE:
            raise ValueError(
                f"{where}.kind 未知 {kind!r}；v1 枚举仅 "
                f"{sorted(KIND_TABLE)}（不静默 generic）")
        thickness = _finite(raw["thickness_mm"], f"{where}.thickness_mm")
        if thickness <= 0:
            raise ValueError(
                f"{where}.thickness_mm 必须 >0（层厚非正无物理意义），"
                f"收到 {thickness!r}")
        material = raw.get("material")
        if material is not None and not isinstance(material, str):
            raise ValueError(f"{where}.material 必须是字符串，收到 "
                             f"{type(material)!r}")
        er = raw.get("er")
        if er is not None:
            er = _finite(er, f"{where}.er")
            if er < 1.0:
                raise ValueError(
                    f"{where}.er 必须 ≥1（真空下界，小于 1 非物理），"
                    f"收到 {er!r}")
        layers.append({
            "name": name, "kind": kind, "thickness_mm": thickness,
            "material": material, "er": er,
        })

    layer_by_name = {lay["name"]: lay for lay in layers}

    raw_widths = stackup.get("width_annotations") or []
    if not isinstance(raw_widths, (list, tuple)):
        raise ValueError("stackup.width_annotations 必须是列表")
    width_annotations: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_widths):
        where = f"width_annotations[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} 必须是 dict，收到 {type(raw)!r}")
        _check_no_extra(raw, _WIDTH_KEYS, where,
                        "线宽标注 schema 严格三键 layer/width_mm/note")
        for key in _WIDTH_REQUIRED:
            if key not in raw or raw[key] is None:
                raise ValueError(f"{where} 缺必填键 {key!r}")
        layer_name = _check_str_nonempty(raw["layer"], f"{where}.layer")
        if layer_name not in layer_by_name:
            raise ValueError(
                f"{where} 引用不存在层名：{layer_name!r}（已声明 "
                f"{sorted(layer_by_name)}）")
        target = layer_by_name[layer_name]
        if target["kind"] == "dielectric":
            raise ValueError(
                f"{where} 落在介质层 {layer_name!r}（线宽属于导体层"
                " signal/plane，介质层无线宽语义）")
        width = _finite(raw["width_mm"], f"{where}.width_mm")
        if width <= 0:
            raise ValueError(
                f"{where}.width_mm 必须 >0（线宽非正无物理意义），"
                f"收到 {width!r}")
        note = raw.get("note")
        if note is not None and not isinstance(note, str):
            raise ValueError(f"{where}.note 必须是字符串，收到 "
                             f"{type(note)!r}")
        width_annotations.append({
            "layer": layer_name, "width_mm": width, "note": note,
        })

    return {"title": title, "layers": layers,
            "width_annotations": width_annotations}


# ─── 布局（层带自顶向下堆叠；标注列在带右；箭头横向同比例尺） ────────────────


def _r6(v: float) -> float:
    """几何/累计数值收敛：round 6 位（mm×200px 尺度下 1e-6px 远低于
    0.001px 视觉分辨率；str() 无 repr 长尾——确定性文本）。"""
    return round(float(v), 6)


def _gtxt(v: float) -> str:
    """几何数值 → XML 属性文本（round 6 位后走 :func:`format_number` 分档：
    整值不带 ``.0``——``y="100"`` 而非 ``"100.0"``；非整值最短往返）。"""
    return format_number(_r6(v))


def collect_warnings(norm: dict[str, Any],
                     *, px_per_mm: float = PX_PER_MM) -> list[str]:
    """归一叠层 → warnings 列表（薄带/无介质/无导体/箭头越带，固定顺序）。"""
    ws: list[str] = []
    kinds = {lay["kind"] for lay in norm["layers"]}
    if "dielectric" not in kinds:
        ws.append(_WARN_NO_DIELECTRIC)
    if not kinds & {"signal", "plane"}:
        ws.append(_WARN_NO_CONDUCTOR)
    for lay in norm["layers"]:
        h = _r6(lay["thickness_mm"] * px_per_mm)
        if h < _MIN_VISIBLE_PX:
            ws.append(_WARN_THIN_BAND.format(name=lay["name"], h=format_number(h),
                                             th=format_number(_MIN_VISIBLE_PX)))
    for i, ann in enumerate(norm["width_annotations"]):
        arrow = _r6(ann["width_mm"] * px_per_mm)
        if arrow > STACK_W:
            ws.append(_WARN_WIDTH_OVER_BAND.format(
                i=i, layer=ann["layer"], arrow=format_number(arrow),
                band_w=format_number(STACK_W)))
    return ws


def build_stackup_plan(stackup: Any, *,
                       title: str | None = None,
                       px_per_mm: float = PX_PER_MM) -> dict[str, Any]:
    """声明式叠层 → 装配计划（XML 文本 + 信封回显面；service 与内核测试同源）。

    Returns::

        {"xml": str（未压缩原生 mxfile，逐字节确定性）,
         "n_layers"/"n_width_annotations": int,
         "layers": [{index, name, kind, thickness_mm, material, er,
                     zmin_mm, height_px}, ...],
         "width_annotations": [{index, layer, width_mm, note}, ...],
         "warnings": [str, ...]}

    Raises:
        ValueError: 叠层 schema 违约（见 :func:`normalize_stackup`）。
    """
    norm = normalize_stackup(stackup)
    px_per_mm = _finite(px_per_mm, "px_per_mm")
    if px_per_mm <= 0:
        raise ValueError(
            f"px_per_mm 必须 >0（比例尺非正无意义），收到 {px_per_mm!r}")
    warnings = collect_warnings(norm, px_per_mm=px_per_mm)

    # 层带几何（自顶向下堆叠；zmin=自顶累计深度，确定性加法）
    band_ys: list[float] = []
    band_hs: list[float] = []
    zmin_mms: list[float] = []
    y = float(STACK_Y0)
    z = 0.0
    for lay in norm["layers"]:
        h = _r6(lay["thickness_mm"] * px_per_mm)
        band_ys.append(_r6(y))
        band_hs.append(h)
        zmin_mms.append(_r6(z))
        y += h
        z += lay["thickness_mm"]
    stack_bottom = _r6(y)

    def _label_text(idx: int) -> str:
        lay = norm["layers"][idx]
        line1 = f"{lay['name']}（{lay['kind']}）"
        segs = []
        if lay["material"]:
            segs.append(lay["material"])
        segs.append(f"{format_number(lay['thickness_mm'])} mm")
        if lay["er"] is not None:
            segs.append(f"εr {format_number(lay['er'])}")
        line2 = "  ".join(segs)
        line3 = f"z={format_number(zmin_mms[idx])} mm"
        return f"{line1}\n{line2}\n{line3}"

    # 标注列（贪心非叠：理想位=居中于带；与上一卡不足 LABEL_VGAP 净距则
    # 下移——只下移不上移，层序与标注序一致；下移卡由引线连回本带）
    label_ys: list[float] = []
    for i in range(len(norm["layers"])):
        ideal = band_ys[i] + band_hs[i] / 2.0 - LABEL_H / 2.0
        if label_ys:
            ideal = max(ideal, label_ys[-1] + LABEL_H + LABEL_VGAP)
        label_ys.append(_r6(ideal))
    labels_bottom = label_ys[-1] + LABEL_H

    # 页面尺寸按内容自适应（高度取堆叠底与标注列底之大者；宽度含标注列与
    # 最长线宽箭头右端——越带箭头也落在页内；ceil 收整数=页面属性干净文本）
    arrow_right = max(
        (STACK_X + ann["width_mm"] * px_per_mm + _ANCHOR_SIZE
         for ann in norm["width_annotations"]), default=0.0)
    content_right = max(STACK_X + STACK_W + LABEL_GAP + LABEL_W, arrow_right)
    page_w = max(int(DEFAULT_PAGE_ATTRS["pageWidth"]),
                 math.ceil(content_right + _MARGIN_X))
    page_h = max(int(DEFAULT_PAGE_ATTRS["pageHeight"]),
                 math.ceil(max(stack_bottom, labels_bottom) + _PAGE_BOTTOM_PAD))

    doc = new_document(diagram_id="stackup-diagram",
                       diagram_name="PCB Stackup",
                       page=page_attrs(pageWidth=str(page_w),
                                       pageHeight=str(page_h)))

    # 标题（显式 title 参数 > 场景 title > 缺省标题——缺省含实际比例尺）
    title_text = (title or norm["title"]
                  or _DEFAULT_TITLE_FMT.format(scale=format_number(px_per_mm)))
    doc.add_vertex("title", title_text, style=_TITLE_STYLE,
                   x=_gtxt(_MARGIN_X), y=_gtxt(_TITLE_Y),
                   width=_gtxt(_TITLE_W), height=_gtxt(_TITLE_H))

    # 层带 + 右侧标注卡 + 引线（id 按声明索引生成；引线=卡左中→带右中）
    for i, lay in enumerate(norm["layers"]):
        fill, stroke = KIND_TABLE[lay["kind"]]
        doc.add_vertex(f"layer{i}", "", style=_band_style(fill, stroke),
                       x=_gtxt(STACK_X), y=_gtxt(band_ys[i]),
                       width=_gtxt(STACK_W), height=_gtxt(band_hs[i]))
        doc.add_vertex(f"layer{i}.label", _label_text(i), style=_LABEL_STYLE,
                       x=_gtxt(STACK_X + STACK_W + LABEL_GAP),
                       y=_gtxt(label_ys[i]), width=_gtxt(LABEL_W),
                       height=_gtxt(LABEL_H))
        doc.add_edge(f"layer{i}.leader", "", style=_LEADER_STYLE,
                     source=f"layer{i}.label", target=f"layer{i}")

    # 线宽标注（双不可见锚点 + 双箭头 edge；箭长=width×同一比例尺）
    name_to_index = {lay["name"]: i for i, lay in enumerate(norm["layers"])}
    for i, ann in enumerate(norm["width_annotations"]):
        idx = name_to_index[ann["layer"]]
        cy = band_ys[idx] + band_hs[idx] / 2.0
        x0 = float(STACK_X)
        x1 = STACK_X + ann["width_mm"] * px_per_mm
        for tag, ax in (("a", x0), ("b", x1)):
            doc.add_vertex(f"w{i}.{tag}", "", style=_ANCHOR_STYLE,
                           x=_gtxt(ax - _ANCHOR_SIZE / 2.0),
                           y=_gtxt(cy - _ANCHOR_SIZE / 2.0),
                           width=_gtxt(_ANCHOR_SIZE),
                           height=_gtxt(_ANCHOR_SIZE))
        parts = [f"{format_number(ann['width_mm'])} mm"]
        if ann["note"]:
            parts.append(ann["note"])
        edge = doc.add_edge(f"w{i}", "  ".join(parts), style=_WIDTH_EDGE_STYLE,
                            source=f"w{i}.a", target=f"w{i}.b")
        # 标签法向上移（drawio edge label offset 惯例：mxGeometry 子
        # mxPoint as="offset"——内核返回元素上挂子元素=docstring 许可扩展点）
        geom = edge.find("mxGeometry")
        if geom is not None:
            ET.SubElement(geom, "mxPoint", {
                "x": "0", "y": _gtxt(_WIDTH_LABEL_OFFSET_Y), "as": "offset"})

    layers_echo = []
    for i, lay in enumerate(norm["layers"]):
        layers_echo.append({
            "index": i, "name": lay["name"], "kind": lay["kind"],
            "thickness_mm": lay["thickness_mm"], "material": lay["material"],
            "er": lay["er"], "zmin_mm": zmin_mms[i],
            "height_px": band_hs[i],
        })
    widths_echo = [{"index": i, "layer": ann["layer"],
                    "width_mm": ann["width_mm"], "note": ann["note"]}
                   for i, ann in enumerate(norm["width_annotations"])]

    return {
        "xml": doc.to_xml(),
        "n_layers": len(norm["layers"]),
        "n_width_annotations": len(norm["width_annotations"]),
        "layers": layers_echo,
        "width_annotations": widths_echo,
        "warnings": warnings,
    }


def build_stackup_diagram_xml(stackup: Any, *,
                              title: str | None = None,
                              px_per_mm: float = PX_PER_MM) -> str:
    """声明式叠层 → 完整 .drawio XML 文本（未压缩原生 mxfile，逐字节确定性）。

    Args:
        stackup: 声明式叠层（schema 见 :func:`normalize_stackup`）。
        title: 图标题文本（None 用场景 title，再 None 用缺省标题）。
        px_per_mm: 比例尺（px/mm；缺省=:data:`PX_PER_MM`，测试/大板可调，
            须为 >0 有限实数；标注文本与比例尺无关——高度∝thickness
            只改 px 数）。

    Raises:
        ValueError: 叠层非法（严格键/kind 枚举/负厚度/层引用完整性等）。
    """
    return build_stackup_plan(stackup, title=title,
                              px_per_mm=px_per_mm)["xml"]
