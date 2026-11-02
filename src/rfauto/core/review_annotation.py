"""评审标注双层 .drawio 生成器（T-O8：底图锁定 + 标注层三件组）。

"算画同源"评审面（aurora_o T-O8，2026-11-01）：输入=底图（形态 A 既有
rfauto .drawio / 形态 B 外部 PNG/JPEG 位图）+ 标注 JSON（唯一数据源，
声明式零计算），产出**双层评审图**——底图层锁定（评审人不可误动被审
图元）+ 标注层（三色圈/编号/右侧意见栏/虚线关联）。形态规格单源 =
runs/aurora_o/design_specs/T-O8_ANNOTATION_SPEC.md（本模块照搬实现，
裁决不改动）。

与 core/drawio_xml 内核的关系（消费面说明，如实声明）：
- **read 面**（形态 A 校验/几何扫描/id 集）：走
  :func:`rfauto.core.drawio_xml.parse_diagram`（T-O2 预留的 T-O8 消费点，
  内核 docstring 消费预留节同账）；
- **写面**：本模块自装 ElementTree——两个规格级理由：①形态 A 的验收
  生命线是"底图零改动"（spec 钉 2：原 cell 集合逐 cell 全等），必须
  在**解析树上原地追加**而非经 DrawioDocument 重建（重建即触碰每一
  原 cell 属性序与文档结构）；②spec §3.3 钉死标注三件组为 **UserObject
  包装形态**（tooltip 悬空即读意见），而内核 v1 写面边界="UserObject
  不支持、extra_attrs 直写 mxCell 等价"（core/drawio_xml.py 边界节）——
  spec 裁决优先，边界扩展在本模块内落，不回改内核（内核零改动红线）。
  页面属性缺省复用内核 :data:`DEFAULT_PAGE_ATTRS`/:func:`page_attrs`。

数据面（铁律 7）：标注内容（意见文本/优先级/区域坐标）全部来自调用方
JSON 原值——图上数字只有编号 i（表序 1 起）与坐标原样文本，零派生物理
数字零公式；意见文本/label 原样标注（转义由 ElementTree 负责，回读逐字
还原）。

两族底图（spec §0.2/§3.1/§3.2）：
- 形态 A：唯一对原文件的修改 = ``id="1"`` 层 cell 加 ``locked="1"``
  （空 value 时补层名"底图（评审锁定）"）+ root 尾部追加 ``annot``
  标注层与其子元素（层序=cell 出现序，定义在后=渲染在上）；
- 形态 B：新建文档，底图= ``shape=image`` 单 cell 挂默认层（锁定走
  style 五旗标 movable/resizable/rotatable/deletable/editable=0——层锁
  会连标注层一起锁，两族锁定落点不同，spec §3.2），**data URI 不带
  ``;base64``**（``;`` 是 style 分隔符，格式红线；检测钉=style 串零
  ``;base64`` 子串）。

确定性：同输入两次构建 XML 逐字节相同——cell id 全部确定性命名
（spec §3.4 前缀表 anc/anm/ane/ant/anh/ans，禁 uuid）、零时间戳、
ElementTree 属性序=插入序、``ET.indent(space="  ")`` 幂等。

多评审人合并（aurora_p A4，T-O8 spec §六.3 v2 位）：:func:
`merge_annotation_plans` 把同一底图的多个评审人标注集合入单一输出——
合并表序=按 reviewer 名升序**稳定**排序（入参顺序无关，同 reviewer
保入参相对序、文件内保表序）；描边=评审人调色表 :data:`REVIEWER_PALETTE`
按排序去重序号轮转，填充=优先级三色语义；生成 cell id=合并表序全局
顺序号，输入 id 原样进 ``an_id``（铁律 7 零变换，跨文件重复 → 逐 id
warnings）；意见卡 label 带 ``·评审人`` 署名、栏头带逐评审人计数。
合并语义设计单源=runs/aurora_p/a4/MERGE_DESIGN.md；既有单评审人路径
（:func:`build_annotation_plan` 全链）零变化。

零 IO 落盘（本模块只返回 XML 文本与 plan dict；读底图文件+落盘在
service 层）、零第三方依赖（仅 xml.etree/base64/math/re/pathlib 标准
库 + 同层 core.drawio_xml read 面）。
"""

from __future__ import annotations

import base64
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from rfauto.core.drawio_xml import (
    DEFAULT_PAGE_ATTRS,
    DrawioReadError,
    page_attrs,
    parse_diagram,
)

__all__ = [
    "ANNOT_LAYER_ID",
    "CARD_ID_PREFIX",
    "CIRCLE_ID_PREFIX",
    "CROSS_EDGE_ID_PREFIX",
    "PRIORITY_TABLE",
    "REVIEWER_PALETTE",
    "TARGET_EDGE_ID_PREFIX",
    "build_annotation_plan",
    "merge_annotation_plans",
    "normalize_annotations",
]

# ─── 常量单源（spec §2.3/§3.4 钉死；测试逐键断言 hex） ─────────────────────

#: 优先级三色映射（fillColor, strokeColor, 中文短标）——spec §2.3 常量表，
#: 单源=本模块（与 T-O1 蓝色族 #dae8fc/#6c8ebf 构成四色族：蓝=图元内容色，
#: 红/橙/绿=评审语义色）。未知 priority 在 normalize 显式拒绝（不走缺省）。
PRIORITY_TABLE: dict[str, tuple[str, str, str]] = {
    "high": ("#f8cecc", "#b85450", "高"),
    "medium": ("#ffe6cc", "#d79b00", "中"),
    "low": ("#d5e8d4", "#82b366", "低"),
}

#: 评审人描边调色表（aurora_p A4 合并路径专用单源；drawio 经典色板）——
#: 与 PRIORITY_TABLE 三描边（#b85450/#d79b00/#82b366）及 T-O1 内容蓝
#: #dae8fc 族可区分（测试钉互斥）。映射=排序去重 reviewer 序号轮转
#: （``palette[i % len]``，超表长确定性循环）；填充色仍走 PRIORITY_TABLE
#: （优先级三色语义保持——设计单源=runs/aurora_p/a4/MERGE_DESIGN.md）。
REVIEWER_PALETTE: tuple[str, ...] = (
    "#6c8ebf",   # 蓝
    "#9673a6",   # 紫
    "#10739e",   # 青
    "#d6b656",   # 暗黄
    "#666666",   # 灰
)

#: 标注层 id/显示名（spec §3.1 钉死层名 annot；与 T-O4 annot_sim 双名单源
#: 登记，spec §六.5——同名层语义混淆防线）
ANNOT_LAYER_ID = "annot"
ANNOT_LAYER_NAME = "评审标注"
BASE_LAYER_NAME = "底图（评审锁定）"

#: 生成 cell id 前缀表（spec §3.4：i=标注表序 1 起；输入标注 id 存
#: UserObject ``an_id`` 属性供人工对读）——确定性、零 uuid
CIRCLE_ID_PREFIX = "anc"        # 圈
CARD_ID_PREFIX = "anm"          # 意见卡
CROSS_EDGE_ID_PREFIX = "ane"    # 圈→卡虚线边
TARGET_EDGE_ID_PREFIX = "ant"   # 圈→底图 target 指示边
_HEADER_ID = "anh"              # 意见栏头
_SUMMARY_ID = "ans"             # 顶部摘要卡

#: 意见栏几何（px；spec §3.3：栏 x=底图右缘+60、卡 300×72、行距 16=步距 88）
BAR_GAP = 60
CARD_W = 300
CARD_H = 72
ROW_STEP = CARD_H + 16
_FIRST_ROW_Y = 60
_HEADER_Y = 20
_HEADER_W = 300
_HEADER_H = 26
#: 摘要卡几何（spec §3.5：x=栏x-360、y=20、w=340、h=48——落图区右上不压意见栏）
_SUMMARY_W = 340
_SUMMARY_H = 48
_SUMMARY_X_OFF = 360
_SUMMARY_Y = 20

#: 样式串（spec §3.3 原样；fill/stroke 由 PRIORITY_TABLE 注入）
_CIRCLE_STYLE = (
    "ellipse;fillColor={fill};strokeColor={stroke};fillOpacity=30;"
    "verticalAlign=middle;align=center;fontStyle=1;fontSize=14;html=1;")
_CARD_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
    "align=left;verticalAlign=top;fontSize=11;spacing=6;")
_CROSS_EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;dashed=1;endArrow=none;"
    "strokeColor={stroke};html=1;")
#: target 指示边（spec §3.3：dashed 细灰 #999999；底图在锁定层，边在本层
#: ——锁定层内元素可作边端点，仅不可动，不阻断）
_TARGET_EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;dashed=1;endArrow=none;"
    "strokeColor=#999999;html=1;")
_HEADER_STYLE = (
    "text;html=1;strokeColor=none;fillColor=none;align=left;"
    "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontStyle=1;")
_SUMMARY_STYLE = (
    "text;html=1;strokeColor=none;fillColor=none;align=left;"
    "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontStyle=1;fontSize=12;")

#: 形态 B 底图 image cell（spec §3.2 原样：五旗标锁双保险 + data URI 不带
#: ``;base64``——``;`` 是 style 分隔符，格式红线；检测钉=style 零该子串）
_IMAGE_STYLE_TEMPLATE = (
    "shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
    "imageAspect=0;aspect=fixed;"
    "movable=0;resizable=0;rotatable=0;deletable=0;editable=0;"
    "image=data:image/{mime},{b64};")
_IMAGE_MIME: dict[str, str] = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg"}

#: 形态 B 体积红线（spec §3.2：>8 MB base64 → 显式报错；2 MB → warnings）
_IMAGE_MAX_B64_BYTES = 8 * 1024 * 1024
_IMAGE_WARN_B64_BYTES = 2 * 1024 * 1024

#: mxfile 文档级属性（形态 B 新建文档用；与 core/drawio_xml 内核缺省同值
#: ——内核常量为私有不可导入，漂移属显式评审动作）
_MXFILE_ATTRS: dict[str, str] = {
    "host": "rfauto", "type": "device", "version": "24.7.7",
}

#: 标注输入 id 形态（spec §2.2：``[A-Za-z0-9_-]+``；输入 id 撞底图 id 不算
#: 错——生成 cell 一律加 anc/anm 前缀已消解，仅 warnings 提示人工对读）
_ANN_ID_RE = re.compile(r"[A-Za-z0-9_-]+")

#: warnings 文案（信封逐条可断言）
_WARN_ZERO_ANNOTATIONS = "零标注：annotations 为空，产出=底图复制+空标注层"
_WARN_ID_COLLISION = (
    "标注 id {aid!r} 与底图 cell id 同名（生成 cell 前缀 anc/anm 已隔离，"
    "人工对读时注意区分）")
_WARN_TARGET_IGNORED = (
    "标注 {aid!r} 的 target 已忽略（形态 B 无底图 id 空间，无法校验指向）")
_WARN_IMAGE_SIZE = (
    "底图 base64 体积 {n} 字节，超过 2 MB 警戒线（draw.io 打开可能缓慢）")

#: 合并路径 warnings 文案（merge_annotation_plans 专用；信封逐条可断言）
_WARN_MERGE_EMPTY_FILE = "评审人 {rev!r} 的标注表为空（0 条）"
_WARN_MERGE_DUP_INPUT_ID = (
    "标注输入 id {aid!r} 在多个标注文件间重复（生成 cell id 已按合并表序"
    "全局重编号，an_id 保留原值，按 reviewer 属性区分）")


# ─── 数值文本（原值原样，零换算） ───────────────────────────────────────────


def _finite(value: Any, name: str) -> float:
    """收敛入参为有限实数，否则 ValueError（bool 不算数——bool 是 int 子类）。

    normalize 家法（core/link_diagram.py::_finite 同款）；返回 float 仅用于
    校验，图面文本一律走 :func:`_num_text` 原值渲染。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


def _num_text(value: Any, name: str) -> str:
    """几何数值 → XML 属性文本（原值形态：int 原样、整值 float 去尾 0、
    非整值 float=str() 最短往返——零静默舍入；bool 显式拒绝）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    if value.is_integer():
        return str(int(value))
    return str(value)


# ─── 输入 normalize（标注 JSON 唯一数据源；严格键，normalize 家法） ─────────


def normalize_annotations(payload: Any) -> dict[str, Any]:
    """校验并归一标注表（spec §2 schema 钉死；非法入参显式 ValueError）。

    顶层两形态（等价）：``{"summary"?: str, "annotations": [...]}``（严格
    两键，多余键拒绝）或裸数组（=无摘要卡）。标注卡严格六键
    id/region/priority/label/comment/target（target 可省，多余键拒绝）：

    - ``id``：str 且 ``[A-Za-z0-9_-]+``，标注表内唯一（撞底图 id 不在此
      报错——生成前缀已消解，落 warnings）；
    - ``region``：dict 严格四键 x/y/w/h，有限实数（w/h 负值显式拒绝；
      x/y 允许负——drawio 画布坐标合法）；
    - ``priority``：枚举 high/medium/low（缺省/未知显式拒绝，不走缺省）；
    - ``label``/``comment``：非空 str（图面与意见栏正文，原样标注）；
    - ``target``：可省；给了必须非空 str（形态 A 存在性校验在装配期，
      形态 B 落 warnings）。

    annotations 允许空表（合法=纯复制底图+空标注层，warnings 由装配层
    记"零标注"）。返回 ``{"summary": str|None, "annotations": [...]}``，
    region 数值保留原 int/float 形态（渲染走 :func:`_num_text` 原值）。
    """
    if isinstance(payload, dict):
        extra = set(payload) - {"summary", "annotations"}
        if extra:
            raise ValueError(
                f"标注 payload 存在未支持键 {sorted(extra)}；顶层严格两键 "
                "summary（可省）/annotations")
        if "annotations" not in payload:
            raise ValueError("标注 payload 缺必填键 'annotations'")
        summary = payload.get("summary")
        if summary is not None and (
                not isinstance(summary, str) or not summary.strip()):
            raise ValueError(
                f"summary 必须是非空字符串或省略，收到 {summary!r}")
        anns = payload["annotations"]
    elif isinstance(payload, (list, tuple)):
        summary = None
        anns = payload
    else:
        raise ValueError(
            f"标注 payload 必须是 dict（summary+annotations）或数组，"
            f"收到 {type(payload)!r}")
    if not isinstance(anns, (list, tuple)):
        raise ValueError(f"annotations 必须是数组，收到 {type(anns)!r}")

    allowed = {"id", "region", "priority", "label", "comment", "target"}
    seen_ids: set[str] = set()
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(anns):
        if not isinstance(raw, dict):
            raise ValueError(
                f"annotations[{i}] 必须是 dict，收到 {type(raw)!r}")
        extra = set(raw) - allowed
        if extra:
            raise ValueError(
                f"annotations[{i}] 存在未支持键 {sorted(extra)}；标注卡"
                "严格六键 id/region/priority/label/comment/target")
        for key in ("id", "region", "priority", "label", "comment"):
            if key not in raw or raw[key] is None:
                raise ValueError(f"annotations[{i}] 缺必填键 {key!r}")
        aid = raw["id"]
        if not isinstance(aid, str) or not _ANN_ID_RE.fullmatch(aid):
            raise ValueError(
                f"annotations[{i}].id 必须匹配 [A-Za-z0-9_-]+，收到 {aid!r}")
        if aid in seen_ids:
            raise ValueError(f"annotations[{i}].id 重复：{aid!r}")
        seen_ids.add(aid)

        region_raw = raw["region"]
        if not isinstance(region_raw, dict):
            raise ValueError(
                f"annotations[{i}].region 必须是 dict，收到 "
                f"{type(region_raw)!r}")
        region_extra = set(region_raw) - {"x", "y", "w", "h"}
        if region_extra:
            raise ValueError(
                f"annotations[{i}].region 存在未支持键 "
                f"{sorted(region_extra)}；region 严格四键 x/y/w/h")
        region: dict[str, Any] = {}
        for key in ("x", "y", "w", "h"):
            if key not in region_raw or region_raw[key] is None:
                raise ValueError(f"annotations[{i}].region 缺键 {key!r}")
            _finite(region_raw[key], f"annotations[{i}].region.{key}")
            region[key] = region_raw[key]
        for key in ("w", "h"):
            if float(region_raw[key]) < 0:
                raise ValueError(
                    f"annotations[{i}].region.{key} 必须 ≥ 0（圈的尺寸非负），"
                    f"收到 {region_raw[key]!r}")

        priority = raw["priority"]
        if not isinstance(priority, str) or priority not in PRIORITY_TABLE:
            raise ValueError(
                f"annotations[{i}].priority 必须是 "
                f"{'|'.join(PRIORITY_TABLE)} 之一，收到 {priority!r}")
        label = raw["label"]
        if not isinstance(label, str) or not label.strip():
            raise ValueError(
                f"annotations[{i}].label 必须是非空字符串，收到 {label!r}")
        comment = raw["comment"]
        if not isinstance(comment, str) or not comment.strip():
            raise ValueError(
                f"annotations[{i}].comment 必须是非空字符串，收到 {comment!r}")
        target = raw.get("target")
        if target is not None and (
                not isinstance(target, str) or not target.strip()):
            raise ValueError(
                f"annotations[{i}].target 给了必须是非空字符串（可省），"
                f"收到 {target!r}")

        out.append({
            "id": aid, "region": region, "priority": priority,
            "label": label, "comment": comment, "target": target,
        })
    return {"summary": summary, "annotations": out}


# ─── 形态 B：图片头解析（纯标准库；PNG IHDR / JPEG SOF 段） ─────────────────


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    """PNG 头解像素宽高（IHDR 固定在文件头 16..24 字节；非 PNG 返回 None）。"""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    if len(data) < 24:
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """JPEG 头解像素宽高（扫描 SOF0-SOF15 段，跳过 DHT/DQT 等无尺寸段）。"""
    if data[:2] != b"\xff\xd8":
        return None
    pos = 2
    n = len(data)
    while pos + 9 < n:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0x00, 0xFF, 0xD8):  # 填充字节/独立 SOI
            pos += 2
            continue
        if marker == 0xD9:  # EOI——段扫描尽头无 SOF
            return None
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            # SOF 帧段（C4=DHT/C8=JPG/CC=DAC 非帧段）
            height = int.from_bytes(data[pos + 5:pos + 7], "big")
            width = int.from_bytes(data[pos + 7:pos + 9], "big")
            return width, height
        if pos + 4 > n:
            return None
        seg_len = int.from_bytes(data[pos + 2:pos + 4], "big")
        if seg_len < 2:
            return None
        pos += 2 + seg_len
    return None


def _image_dimensions(
    data: bytes, suffix: str, image_size: tuple[Any, Any] | None,
) -> tuple[int, int]:
    """底图像素宽高：显式 ``image_size`` 优先，否则头解析（失败显式报错）。"""
    if image_size is not None:
        if len(image_size) != 2:
            raise ValueError(
                f"image_size 必须是 (宽, 高) 二元组，收到 {image_size!r}")
        w = _finite(image_size[0], "image_size[0]")
        h = _finite(image_size[1], "image_size[1]")
        if w <= 0 or h <= 0 or w != int(w) or h != int(h):
            raise ValueError(
                f"image_size 必须是正整数像素（WxH），收到 {image_size!r}")
        return int(w), int(h)
    dims = None
    if suffix == "png":
        dims = _png_dimensions(data)
    elif suffix in ("jpg", "jpeg"):
        dims = _jpeg_dimensions(data)
    if dims is None or dims[0] <= 0 or dims[1] <= 0:
        raise ValueError(
            "图片像素尺寸解析失败（非 PNG/JPEG 头或头残缺）；"
            "请显式传 image_size=(宽, 高)（CLI --image-size WxH）兜底")
    return dims


# ─── 标注层装配（三件组/栏头/摘要卡；两族共用） ────────────────────────────


def _generated_ids(n_annos: int) -> list[str]:
    """本席生成 id 全集（spec §3.4 前缀表；冲突检查与装配同表单源）。"""
    ids = [ANNOT_LAYER_ID, _HEADER_ID]
    for i in range(1, n_annos + 1):
        ids.append(f"{CIRCLE_ID_PREFIX}{i}")
        ids.append(f"{CARD_ID_PREFIX}{i}")
        ids.append(f"{CROSS_EDGE_ID_PREFIX}{i}")
        ids.append(f"{TARGET_EDGE_ID_PREFIX}{i}")
    return ids


def _tree_ids(mx_root: ET.Element) -> set[str]:
    """底图既有 id 全集（mxCell 与 UserObject 一并收——冲突检查宁全勿漏）。"""
    return {el.get("id") for el in mx_root.iter() if el.get("id")}


def _add_circle(mx_root: ET.Element, i: int, ann: dict[str, Any],
                fill: str, stroke: str, reviewer: str | None) -> None:
    """编号圈（UserObject 包装，spec §3.3 原样；tooltip=全部意见）。"""
    attrs: dict[str, str] = {
        "label": f"{i} {ann['label']}", "placeholders": "1",
        "an_id": ann["id"], "priority": ann["priority"],
        "comment": ann["comment"]}
    if ann["target"]:
        attrs["target"] = ann["target"]
    if reviewer:
        attrs["reviewer"] = reviewer
    attrs["id"] = f"{CIRCLE_ID_PREFIX}{i}"  # spec 属性序：id 收尾
    uo = ET.SubElement(mx_root, "UserObject", attrs)
    cell = ET.SubElement(uo, "mxCell", {
        "style": _CIRCLE_STYLE.format(fill=fill, stroke=stroke),
        "vertex": "1", "parent": ANNOT_LAYER_ID})
    region = ann["region"]
    tag = f"annotations[{i - 1}].region"
    ET.SubElement(cell, "mxGeometry", {
        "x": _num_text(region["x"], f"{tag}.x"),
        "y": _num_text(region["y"], f"{tag}.y"),
        "width": _num_text(region["w"], f"{tag}.w"),
        "height": _num_text(region["h"], f"{tag}.h"),
        "as": "geometry"})


def _add_card(mx_root: ET.Element, i: int, ann: dict[str, Any],
              fill: str, stroke: str, zh: str, row_y: int, bar_x: int,
              reviewer: str | None, *, label: str | None = None) -> None:
    """右侧意见卡（UserObject；label 缺省=``<i> [高/中/低] <label>`` + 真实
    换行 + ``<comment>``——换行落属性序列化为等价字符引用，回读逐字还原；
    合并路径经 ``label=`` 传 ``<i> [<zh>·<reviewer>] ...`` 署名形态，
    缺省 None=既有单评审人 label 零变化）。"""
    if label is None:
        label = f"{i} [{zh}] {ann['label']}\n{ann['comment']}"
    attrs: dict[str, str] = {
        "label": label,
        "placeholders": "1", "an_id": ann["id"],
        "priority": ann["priority"]}
    if reviewer:
        attrs["reviewer"] = reviewer
    attrs["id"] = f"{CARD_ID_PREFIX}{i}"
    uo = ET.SubElement(mx_root, "UserObject", attrs)
    cell = ET.SubElement(uo, "mxCell", {
        "style": _CARD_STYLE.format(fill=fill, stroke=stroke),
        "vertex": "1", "parent": ANNOT_LAYER_ID})
    ET.SubElement(cell, "mxGeometry", {
        "x": _num_text(bar_x, "bar_x"), "y": _num_text(row_y, "row_y"),
        "width": str(CARD_W), "height": str(CARD_H), "as": "geometry"})


def _add_dashed_edge(mx_root: ET.Element, cell_id: str, style: str,
                     source: str, target: str) -> None:
    """虚线关联边（spec §3.3：dashed+无箭头；几何=relative 惯例）。"""
    cell = ET.SubElement(mx_root, "mxCell", {
        "id": cell_id, "value": "", "style": style,
        "edge": "1", "parent": ANNOT_LAYER_ID,
        "source": source, "target": target})
    ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})


def _add_layer_cell(mx_root: ET.Element) -> None:
    """标注层容器 cell（spec §3.1 形态：``<mxCell id="annot"
    value="评审标注" parent="0"/>``，无 vertex/edge 属性——层序=出现序，
    定义在底图之后=渲染在上）。"""
    ET.SubElement(mx_root, "mxCell", {
        "id": ANNOT_LAYER_ID, "value": ANNOT_LAYER_NAME, "parent": "0"})


def _add_header(mx_root: ET.Element, counts: dict[str, int],
                bar_x: int, *, text: str | None = None) -> None:
    """意见栏头（spec §3.3 缺省文本=``评审意见（<n> 条，高 <nh>/中 <nm>/
    低 <nl>）``；合并路径经 ``text=`` 传逐评审人计数形态——缺省 None=
    既有单评审人文本零变化）。"""
    if text is None:
        n = sum(counts.values())
        text = (f"评审意见（{n} 条，高 {counts['high']}"
                f"/中 {counts['medium']}/低 {counts['low']}）")
    cell = ET.SubElement(mx_root, "mxCell", {
        "id": _HEADER_ID, "value": text, "style": _HEADER_STYLE,
        "vertex": "1", "parent": ANNOT_LAYER_ID})
    ET.SubElement(cell, "mxGeometry", {
        "x": _num_text(bar_x, "bar_x"), "y": str(_HEADER_Y),
        "width": str(_HEADER_W), "height": str(_HEADER_H),
        "as": "geometry"})


def _add_summary(mx_root: ET.Element, summary: str, bar_x: int) -> None:
    """顶部摘要卡（spec §3.5：summary 给了才渲染；x=栏x-360 落图区右上）。"""
    cell = ET.SubElement(mx_root, "mxCell", {
        "id": _SUMMARY_ID, "value": summary, "style": _SUMMARY_STYLE,
        "vertex": "1", "parent": ANNOT_LAYER_ID})
    ET.SubElement(cell, "mxGeometry", {
        "x": _num_text(bar_x - _SUMMARY_X_OFF, "summary.x"),
        "y": str(_SUMMARY_Y), "width": str(_SUMMARY_W),
        "height": str(_SUMMARY_H), "as": "geometry"})


def _append_annotation_layer(
    mx_root: ET.Element, norm: dict[str, Any], bar_x: int, *,
    reviewer: str | None, warnings: list[str],
    emit_target_edges: bool,
) -> None:
    """annot 层 + 栏头/摘要/逐标注三件组整体追加（两族共用装配尾段）。

    ``emit_target_edges``：形态 A=True（target 已校验存在，出 ant 指示边）；
    形态 B=False（无底图 id 空间，target 一律忽略+warnings）。
    """
    annos = norm["annotations"]
    if not annos:
        warnings.append(_WARN_ZERO_ANNOTATIONS)

    # 生成 id 与底图既有 id 冲突检查（再标注场景显式拒绝——id 唯一性是
    # draw.io viewer 连线端点语义的硬前提）
    existing = _tree_ids(mx_root)
    clash = [gid for gid in _generated_ids(len(annos)) if gid in existing]
    if clash:
        raise ValueError(
            f"生成标注 id 与底图既有 id 冲突：{sorted(clash)}"
            "（底图已含标注层或同名 cell——评审标注 v1 单标注表原子产出，"
            "请换未标注底图）")

    # 标注输入 id 撞底图 id：不算错（前缀隔离已消解），warnings 提示
    for ann in annos:
        if ann["id"] in existing:
            warnings.append(_WARN_ID_COLLISION.format(aid=ann["id"]))

    counts = {p: 0 for p in PRIORITY_TABLE}
    for ann in annos:
        counts[ann["priority"]] += 1

    _add_layer_cell(mx_root)
    _add_header(mx_root, counts, bar_x)
    if norm["summary"]:
        _add_summary(mx_root, norm["summary"], bar_x)

    for i, ann in enumerate(annos, 1):
        fill, stroke, zh = PRIORITY_TABLE[ann["priority"]]
        row_y = _FIRST_ROW_Y + (i - 1) * ROW_STEP
        _add_circle(mx_root, i, ann, fill, stroke, reviewer)
        _add_card(mx_root, i, ann, fill, stroke, zh, row_y, bar_x, reviewer)
        _add_dashed_edge(
            mx_root, f"{CROSS_EDGE_ID_PREFIX}{i}",
            _CROSS_EDGE_STYLE.format(stroke=stroke),
            source=f"{CIRCLE_ID_PREFIX}{i}", target=f"{CARD_ID_PREFIX}{i}")
        if ann["target"]:
            if not emit_target_edges:
                warnings.append(_WARN_TARGET_IGNORED.format(aid=ann["id"]))
            else:
                _add_dashed_edge(
                    mx_root, f"{TARGET_EDGE_ID_PREFIX}{i}",
                    _TARGET_EDGE_STYLE,
                    source=f"{CIRCLE_ID_PREFIX}{i}", target=ann["target"])


def _serialize(mxfile: ET.Element) -> str:
    """mxfile 树 → 未压缩 XML 文本（形态同 core/drawio_xml.to_xml：声明头
    +ET.indent 双空格+尾换行；幂等确定性）。"""
    tree = ET.ElementTree(mxfile)
    ET.indent(tree, space="  ")
    xml_text = ET.tostring(mxfile, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_text + "\n"


# ─── 形态 A：既有 .drawio 底图（方案 B 层级锁定，底图零改动生命线） ──────────


def _base_right_edge(page: dict[str, Any]) -> int:
    """形态 A 底图右缘（各 vertex 几何 x+width 最大值；非数值几何 best-effort
    跳过——观测面不阻塞主路径 #105；空图回退 0 → 栏 x=60）。"""
    right = 0.0
    for v in page["vertices"]:
        geom = v.get("geometry") or {}
        try:
            edge = float(geom.get("x") or 0) + float(geom.get("width") or 0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(edge) and edge > right:
            right = edge
    return math.ceil(right)


def _prepare_form_a(
    source: Path, annotations: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """形态 A 底图准备（读取+内核骨架校验+标注 target 存在性校验）——
    单评审人/合并两路共用（aurora_p A4 抽取；行为与抽取前逐句等价）。

    target 存在性校验（spec §2.2：给了但底图无此 id → 显式报错，防指错
    对象；id 空间=全部 mxCell id + 画布根 0）。返回 (文本, page 视图)。
    """
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DrawioReadError(
            f"读取底图失败 {source}：{type(exc).__name__}: {exc}") from exc
    # 校验+结构视图走内核 read 面（T-O2 预留消费点）：坏骨架/压缩页显式报错
    parsed = parse_diagram(text)
    page = parsed["pages"][0]
    base_ids = {"0"}
    for v in page["vertices"]:
        base_ids.add(v["id"])
    for e in page["edges"]:
        base_ids.add(e["id"])
    for lay in page["layers"]:
        base_ids.add(lay["id"])
    for ann in annotations:
        if ann["target"] and ann["target"] not in base_ids:
            raise ValueError(
                f"标注 {ann['id']!r} 的 target={ann['target']!r} 不在底图"
                " cell id 集（防指错对象：请核对被审元素 id）")
    return text, page


def _assemble_root_and_lock(mxfile: ET.Element, source: Path) -> ET.Element:
    """装配树定位 mx root + id=1 层锁定（形态 A 两路共用落点段）。

    方案 B 唯一底图改动：层 cell 加 ``locked="1"``（空 value 补层名；既有
    value=draw.io 层名，保留不覆盖）。缺骨架/缺 id=1 层显式报错。
    """
    mx_root = mxfile.find("diagram/mxGraphModel/root")
    if mx_root is None:  # parse_diagram 已校验骨架——防御性显式报错
        raise DrawioReadError(f"底图骨架不完整（缺 root）：{source}")
    cell1 = mx_root.find("mxCell[@id='1']")
    if cell1 is None:
        raise ValueError(
            "底图缺 id=1 默认层 cell（mxGraph 惯例必含；层级锁定无落点）")
    cell1.set("locked", "1")
    if not cell1.get("value"):
        cell1.set("value", BASE_LAYER_NAME)
    return mx_root


def _assemble_form_a(
    source: Path, norm: dict[str, Any], *,
    reviewer: str | None, warnings: list[str],
) -> str:
    """形态 A：解析树上原地追加（底图 cell 集合零改动生命线，spec §3.1）。"""
    text, page = _prepare_form_a(source, norm["annotations"])

    # 原地装配（同一文本第二次解析；校验面与装配面树形一致——底图 cell
    # 的属性与结构在装配树中保持解析原样，序列化仅统一缩进）
    mxfile = ET.fromstring(text)
    mx_root = _assemble_root_and_lock(mxfile, source)
    _append_annotation_layer(
        mx_root, norm, _base_right_edge(page) + BAR_GAP,
        reviewer=reviewer, warnings=warnings, emit_target_edges=True)
    return _serialize(mxfile)


# ─── 形态 B：外部 PNG/JPEG 位图底图（shape=image+五旗标锁） ─────────────────


def _prepare_form_b(
    source: Path, image_size: tuple[Any, Any] | None,
    warnings: list[str],
) -> tuple[str, int, int]:
    """形态 B 位图准备（后缀校验+读字节+体积红线+像素尺寸+style 装配）→
    (底图 style 串, 宽, 高)——单评审人/合并两路共用（aurora_p A4 抽取；
    行为与抽取前逐句等价）。"""
    suffix = source.suffix.lstrip(".").lower()
    if suffix not in _IMAGE_MIME:
        raise ValueError(
            f"形态 B 底图仅支持 PNG/JPEG（收到后缀 .{suffix or '?'}）；"
            ".drawio 请走形态 A")
    data = source.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    if len(b64) > _IMAGE_MAX_B64_BYTES:
        raise ValueError(
            f"底图 base64 体积 {len(b64)} 字节超过 8 MB 红线（draw.io 手工"
            "打开性能；请压缩截图或降分辨率后再评审）")
    if len(b64) > _IMAGE_WARN_B64_BYTES:
        warnings.append(_WARN_IMAGE_SIZE.format(n=len(b64)))
    width, height = _image_dimensions(data, suffix, image_size)

    # base64 为 ASCII 纯文本写入 style（无 BOM 无分号——分号是 style 分隔符）
    style = _IMAGE_STYLE_TEMPLATE.format(mime=_IMAGE_MIME[suffix], b64=b64)
    if ";base64" in style:  # 格式红线自检（belt-and-suspenders）
        raise ValueError("内部错误：data URI 混入 ;base64（style 分隔符冲突）")
    return style, width, height


def _new_form_b_document(
    style: str, width: int, height: int, n_annos: int,
) -> ET.Element:
    """形态 B 新建文档骨架（基 cell/页面属性/底图 image cell）→ mxfile 元素
    ——单评审人/合并两路共用；页宽高随底图+意见栏自适应。"""
    row_bottom = (_FIRST_ROW_Y + max(n_annos - 1, 0) * ROW_STEP + CARD_H)
    content_bottom = max(height, row_bottom) + 40
    content_right = width + BAR_GAP + CARD_W + 40
    page = page_attrs(
        pageWidth=max(int(DEFAULT_PAGE_ATTRS["pageWidth"]), content_right),
        pageHeight=max(int(DEFAULT_PAGE_ATTRS["pageHeight"]), content_bottom),
    )
    mxfile = ET.Element("mxfile", dict(_MXFILE_ATTRS))
    diagram = ET.SubElement(mxfile, "diagram", {
        "id": "annotated-image", "name": "Annotated Image"})
    model = ET.SubElement(diagram, "mxGraphModel", dict(page))
    mx_root = ET.SubElement(model, "root")
    ET.SubElement(mx_root, "mxCell", {"id": "0"})
    ET.SubElement(mx_root, "mxCell", {"id": "1", "parent": "0"})
    baseimg = ET.SubElement(mx_root, "mxCell", {
        "id": "baseimg", "value": "", "style": style,
        "vertex": "1", "parent": "1"})
    ET.SubElement(baseimg, "mxGeometry", {
        "x": "0", "y": "0", "width": str(width), "height": str(height),
        "as": "geometry"})
    return mxfile


def _assemble_form_b(
    source: Path, norm: dict[str, Any], *,
    reviewer: str | None, image_size: tuple[Any, Any] | None,
    warnings: list[str],
) -> str:
    """形态 B：新建文档 + shape=image 底图（spec §3.2：五旗标锁双保险；
    data URI 不带 ``;base64`` 格式红线）。"""
    style, width, height = _prepare_form_b(source, image_size, warnings)
    mxfile = _new_form_b_document(style, width, height,
                                  len(norm["annotations"]))
    mx_root = mxfile.find("diagram/mxGraphModel/root")
    if mx_root is None:  # 自建骨架防御性显式报错
        raise ValueError("内部错误：形态 B 自建文档缺 root")

    # target 在形态 B 无底图 id 空间 → 一律忽略+warnings（spec §2.2）
    _append_annotation_layer(
        mx_root, norm, width + BAR_GAP,
        reviewer=reviewer, warnings=warnings, emit_target_edges=False)
    return _serialize(mxfile)


# ─── 入口：分型装配（plan dict；落盘在 service 层） ────────────────────────


def build_annotation_plan(
    source: Any,
    annotations: Any,
    *,
    reviewer: str | None = None,
    image_size: tuple[Any, Any] | None = None,
    image: bool | None = None,
) -> dict[str, Any]:
    """底图+标注表 → 双层评审图装配计划（plan dict，XML 文本不落盘）。

    Args:
        source: 底图路径（.drawio=形态 A / .png|.jpg|.jpeg=形态 B）。
        annotations: 标注表（schema 见 :func:`normalize_annotations`）。
        reviewer: 评审人署名（写入圈/意见卡 UserObject ``reviewer`` 属性，
            可省）。
        image_size: 形态 B 显式像素宽高 ``(w, h)``（头解析失败兜底）。
        image: 分型覆盖（None=按后缀自动；True=强制形态 B；False=强制
            形态 A——spec §0.2 ``image=`` 键）。

    Returns::

        {"xml": str, "form": "A"|"B", "n_annotations": int,
         "n_target_edges": int, "layers": {"base": "1", "annot": "annot"},
         "base_locked": True, "warnings": [str, ...]}

    Raises:
        ValueError: 标注 schema 违约/target 指错/id 冲突/体积红线等（显式）。
        DrawioReadError: 形态 A 底图读取/骨架校验失败（ValueError 子类）。
    """
    src = Path(source)  # PathLike 入参第一行收敛（#140）
    norm = normalize_annotations(annotations)
    warnings: list[str] = []
    is_image = src.suffix.lstrip(".").lower() in _IMAGE_MIME
    if image is True or (image is None and is_image):
        xml_text = _assemble_form_b(
            src, norm, reviewer=reviewer, image_size=image_size,
            warnings=warnings)
        form = "B"
    else:
        xml_text = _assemble_form_a(
            src, norm, reviewer=reviewer, warnings=warnings)
        form = "A"
    n_target = sum(1 for a in norm["annotations"] if a["target"]) \
        if form == "A" else 0
    return {
        "xml": xml_text,
        "form": form,
        "n_annotations": len(norm["annotations"]),
        "n_target_edges": n_target,
        "layers": {"base": "1", "annot": ANNOT_LAYER_ID},
        "base_locked": True,
        "warnings": warnings,
    }


# ─── 多评审人合并（aurora_p A4；T-O8 spec §六.3 v2 位） ────────────────────


def _append_annotation_layer_merged(
    mx_root: ET.Element, merged: list[tuple[str, dict[str, Any]]],
    bar_x: int, *, warnings: list[str], emit_target_edges: bool,
    reviewer_colors: dict[str, str], header_text: str | None,
    summary_text: str | None,
) -> None:
    """合并路径装配尾段（:func:`merge_annotation_plans` 专用；单评审人路径
    :func:`_append_annotation_layer` 零触碰）。

    与单评审人尾段的分野：描边=评审人调色（:data:`REVIEWER_PALETTE`，
    填充仍优先级三色）、意见卡 label 带 ``·评审人`` 署名、栏头/摘要=合并
    形态文本；生成 id 冲突检查/零标注/输入 id 撞底图 id/target 边语义与
    单评审人同款。
    """
    if not merged:
        warnings.append(_WARN_ZERO_ANNOTATIONS)
    # 生成 id 与底图既有 id 冲突检查（与单评审人同款——再标注显式拒绝）
    existing = _tree_ids(mx_root)
    clash = [gid for gid in _generated_ids(len(merged)) if gid in existing]
    if clash:
        raise ValueError(
            f"生成标注 id 与底图既有 id 冲突：{sorted(clash)}"
            "（底图已含标注层或同名 cell——请换未标注底图）")
    for _rev, ann in merged:
        if ann["id"] in existing:
            warnings.append(_WARN_ID_COLLISION.format(aid=ann["id"]))

    counts = {p: 0 for p in PRIORITY_TABLE}
    for _rev, ann in merged:
        counts[ann["priority"]] += 1
    _add_layer_cell(mx_root)
    _add_header(mx_root, counts, bar_x, text=header_text)
    if summary_text:
        _add_summary(mx_root, summary_text, bar_x)

    for i, (rev, ann) in enumerate(merged, 1):
        fill, _pstroke, zh = PRIORITY_TABLE[ann["priority"]]
        stroke = reviewer_colors[rev]
        row_y = _FIRST_ROW_Y + (i - 1) * ROW_STEP
        _add_circle(mx_root, i, ann, fill, stroke, rev)
        _add_card(mx_root, i, ann, fill, stroke, zh, row_y, bar_x, rev,
                  label=f"{i} [{zh}·{rev}] {ann['label']}\n{ann['comment']}")
        _add_dashed_edge(
            mx_root, f"{CROSS_EDGE_ID_PREFIX}{i}",
            _CROSS_EDGE_STYLE.format(stroke=stroke),
            source=f"{CIRCLE_ID_PREFIX}{i}", target=f"{CARD_ID_PREFIX}{i}")
        if ann["target"]:
            if not emit_target_edges:
                warnings.append(_WARN_TARGET_IGNORED.format(aid=ann["id"]))
            else:
                _add_dashed_edge(
                    mx_root, f"{TARGET_EDGE_ID_PREFIX}{i}",
                    _TARGET_EDGE_STYLE,
                    source=f"{CIRCLE_ID_PREFIX}{i}", target=ann["target"])


def _assemble_form_a_merged(
    source: Path, merged: list[tuple[str, dict[str, Any]]], *,
    warnings: list[str], reviewer_colors: dict[str, str],
    header_text: str | None, summary_text: str | None,
) -> str:
    """形态 A 合并：解析树上原地追加（底图零改动生命线与单评审人同款）。"""
    text, page = _prepare_form_a(source, [ann for _rev, ann in merged])
    mxfile = ET.fromstring(text)
    mx_root = _assemble_root_and_lock(mxfile, source)
    _append_annotation_layer_merged(
        mx_root, merged, _base_right_edge(page) + BAR_GAP,
        warnings=warnings, emit_target_edges=True,
        reviewer_colors=reviewer_colors, header_text=header_text,
        summary_text=summary_text)
    return _serialize(mxfile)


def _assemble_form_b_merged(
    source: Path, merged: list[tuple[str, dict[str, Any]]], *,
    image_size: tuple[Any, Any] | None, warnings: list[str],
    reviewer_colors: dict[str, str], header_text: str | None,
    summary_text: str | None,
) -> str:
    """形态 B 合并：新建文档 + shape=image 底图（五旗标锁/data URI 红线
    与单评审人同款）。"""
    style, width, height = _prepare_form_b(source, image_size, warnings)
    mxfile = _new_form_b_document(style, width, height, len(merged))
    mx_root = mxfile.find("diagram/mxGraphModel/root")
    if mx_root is None:  # 自建骨架防御性显式报错
        raise ValueError("内部错误：形态 B 自建文档缺 root")
    # target 在形态 B 无底图 id 空间 → 一律忽略+warnings（spec §2.2）
    _append_annotation_layer_merged(
        mx_root, merged, width + BAR_GAP,
        warnings=warnings, emit_target_edges=False,
        reviewer_colors=reviewer_colors, header_text=header_text,
        summary_text=summary_text)
    return _serialize(mxfile)


def merge_annotation_plans(
    source: Any,
    entries: Any,
    *,
    image_size: tuple[Any, Any] | None = None,
    image: bool | None = None,
) -> dict[str, Any]:
    """多评审人标注集合并 → 单一双层评审图装配计划（plan dict，XML 文本
    不落盘；T-O8 spec §六.3 v2 位，设计单源=runs/aurora_p/a4/MERGE_DESIGN.md）。

    Args:
        source: 共用底图路径（.drawio=形态 A / .png|.jpg|.jpeg=形态 B，
            底图零改动语义与 :func:`build_annotation_plan` 同款）。
        entries: ``[(reviewer, annotations), ...]`` **非空**序列——reviewer
            必须是非空字符串（署名/色分/计数的单源）；annotations 为
            :func:`normalize_annotations` 同款 payload。重复 reviewer 名
            跨文件=合入同一桶（同色、计数合并、表序按入参相对序）。
        image_size: 形态 B 显式像素宽高 ``(w, h)``（同
            :func:`build_annotation_plan`）。
        image: 分型覆盖（同 :func:`build_annotation_plan`）。

    合并语义（确定性，零时间戳零 uuid）：合并表序=按 reviewer 名升序
    **稳定**排序（入参顺序无关、同 reviewer 保入参相对序、文件内保表序）；
    描边=评审人调色表 :data:`REVIEWER_PALETTE` 按排序去重序号轮转、填充=
    优先级三色语义；生成 cell id=合并表序**全局顺序号**（anc1..ancN，
    跨文件唯一），输入 id 原样进 ``an_id``（铁律 7 零变换；跨文件重复
    输入 id → 逐 id warnings，文件内重复仍由 normalize 显式拒绝）；
    意见卡 label=``<i> [<高/中/低>·<reviewer>] <label>\\n<comment>``；
    栏头带逐评审人计数；摘要卡=各文件非空 summary 按 reviewer 排序序
    逐行 ``<rev>：<summary>`` 拼合（全空则无摘要卡）。

    Returns::

        {"xml": str, "form": "A"|"B", "n_annotations": int,
         "n_target_edges": int, "n_reviewers": int,
         "reviewers": [str, ...],          # 排序去重
         "per_reviewer": {rev: {"total": int, "high": int, "medium": int,
                                "low": int}},
         "reviewer_colors": {rev: "#hex"},
         "layers": {"base": "1", "annot": "annot"},
         "base_locked": True, "warnings": [str, ...]}

    Raises:
        ValueError: entries/reviewer 形态违约、标注 schema 违约、target
            指错、id 冲突、体积红线等（显式，不静默）。
        DrawioReadError: 形态 A 底图读取/骨架校验失败（ValueError 子类）。
    """
    src = Path(source)  # PathLike 入参第一行收敛（#140）
    if not isinstance(entries, (list, tuple)) or not entries:
        raise ValueError(
            "entries 必须是非空 [(reviewer, annotations), ...] 序列，"
            f"收到 {entries!r}")
    pairs: list[tuple[str, Any]] = []
    for k, entry in enumerate(entries):
        if isinstance(entry, (str, bytes)) or not isinstance(
                entry, (list, tuple)) or len(entry) != 2:
            raise ValueError(
                f"entries[{k}] 必须是 (reviewer, annotations) 二元组，"
                f"收到 {entry!r}")
        reviewer, payload = entry
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError(
                f"entries[{k}] 的 reviewer 必须是非空字符串（署名/色分/"
                f"计数的单源），收到 {reviewer!r}")
        pairs.append((reviewer, payload))

    # 确定性合并序：按 reviewer 名升序稳定排序（同 reviewer 保入参相对序）
    ordered = sorted(pairs, key=lambda p: p[0])
    norms = [(rev, normalize_annotations(payload))
             for rev, payload in ordered]
    merged: list[tuple[str, dict[str, Any]]] = []
    per_reviewer: dict[str, dict[str, int]] = {
        rev: {"total": 0, "high": 0, "medium": 0, "low": 0}
        for rev in sorted({rev for rev, _ in norms})}
    warnings: list[str] = []
    for rev, norm in norms:
        if not norm["annotations"]:
            warnings.append(_WARN_MERGE_EMPTY_FILE.format(rev=rev))
        for ann in norm["annotations"]:
            merged.append((rev, ann))
            per_reviewer[rev]["total"] += 1
            per_reviewer[rev][ann["priority"]] += 1

    # 跨文件输入 id 重复（文件内重复已被 normalize 拒绝）：逐 id warnings
    id_counts: dict[str, int] = {}
    for _rev, ann in merged:
        id_counts[ann["id"]] = id_counts.get(ann["id"], 0) + 1
    for aid in sorted(a for a, c in id_counts.items() if c > 1):
        warnings.append(_WARN_MERGE_DUP_INPUT_ID.format(aid=aid))

    reviewers = sorted(per_reviewer)
    reviewer_colors = {
        rev: REVIEWER_PALETTE[i % len(REVIEWER_PALETTE)]
        for i, rev in enumerate(reviewers)}
    n_total = len(merged)
    prio = {p: sum(1 for _r, a in merged if a["priority"] == p)
            for p in PRIORITY_TABLE}
    header_text = (
        f"评审意见（{n_total} 条，高 {prio['high']}/中 {prio['medium']}"
        f"/低 {prio['low']}；"
        + "、".join(f"{rev} {per_reviewer[rev]['total']} 条"
                    for rev in reviewers) + "）")
    summary_lines = [
        f"{rev}：{norm['summary']}"
        for rev, norm in norms  # norms 已按 reviewer 排序
        if norm["summary"]]
    summary_text = "\n".join(summary_lines) if summary_lines else None

    is_image = src.suffix.lstrip(".").lower() in _IMAGE_MIME
    if image is True or (image is None and is_image):
        xml_text = _assemble_form_b_merged(
            src, merged, image_size=image_size, warnings=warnings,
            reviewer_colors=reviewer_colors, header_text=header_text,
            summary_text=summary_text)
        form = "B"
    else:
        xml_text = _assemble_form_a_merged(
            src, merged, warnings=warnings,
            reviewer_colors=reviewer_colors, header_text=header_text,
            summary_text=summary_text)
        form = "A"
    n_target = sum(1 for _r, a in merged if a["target"]) \
        if form == "A" else 0
    return {
        "xml": xml_text,
        "form": form,
        "n_annotations": n_total,
        "n_target_edges": n_target,
        "n_reviewers": len(reviewers),
        "reviewers": reviewers,
        "per_reviewer": per_reviewer,
        "reviewer_colors": reviewer_colors,
        "layers": {"base": "1", "annot": ANNOT_LAYER_ID},
        "base_locked": True,
        "warnings": warnings,
    }
