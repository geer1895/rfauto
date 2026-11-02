"""可调 ADS 电路图 .drawio 内核（aurora_o T-O4，UserObject 三件组形态）。

形态规格（语境钉死）：runs/aurora_o/design_specs/T-O4_ADS_UX_SPEC.md §2。
用户旅程 J1 出图/J2 draw.io Edit Data 改值/J4 反标注的**图面落点**都在
本模块——service/circuit_sim_service.py 只做编排与数值，本模块零物理
数值（铁律 7）：一切参数文本由调用方给（格式化单源在 service），指标卡
数值文本由 service 经 report_render.fmt_value（.6g 单源）产出来注入。

UserObject 三件组（spec §2.1 形态规则，钉死）
----------------------------------------------
- 可调参数属性三件组 ``p_<key>`` / ``unit_<key>`` / ``src_<key>``
  （value/unit/source 成对——provenance 图版；src v1 恒 "input"）；
- label 用 placeholders（``%p_theta_in_deg%``）——draw.io Edit Data 改
  属性值后标签即时刷新（保存/重开时重渲染）；placeholder 只引用本
  UserObject 自有属性；
- ``p_sweep_<k>`` 二级嵌套 ↔ params dict ``{"sweep": {"k": ...}}``；
  ``p_<k>`` 一级（spec §2.2 命名规则钉死）。

MVP 钉死两族（用户令）：wilkinson_snp / branchline_cascade；M3 增补两族
（aurora_p A2 席，spec §八 遗留 1 实施位）：active_chain_sparam /
loadpull_hb（#293 HB 语法域——渲染语法全部在 linkage.ads_active_chain
既有渲染器，本模块只认参数键名与文本形态）。布局与参数承载卡由
:data:`_FAMILY_KEYS` 单表声明（键→承载卡），build 与 read-back 两个方向
共用同一张表（生成缺键/多余键显式报错；读回缺键由 service 按三态语义
裁决）。

XML 装配（与 core/drawio_xml 的关系）
--------------------------------------
T-O2 内核 ``DrawioDocument`` 只产 mxCell；本模块的元件卡必须是
**UserObject 包装形态**（draw.io Edit Data 表单与 label placeholders 是
UserObject 特性，spec §2.1 钉死），故骨架装配（mxfile>diagram>
mxGraphModel>root + 基 cell 0/1、页属性、ET.indent、XML 头、确定性纪律）
按同款家法在本模块自写，页属性复用内核 :data:`DEFAULT_PAGE_ATTRS`、
read 面错误复用 :class:`DrawioReadError`；内核 read 面
``parse_diagram`` 不展开 UserObject 元素（v1 边界，其 docstring 已声明），
本模块读回走自带 ET walk（同骨架校验，缺骨架同样 DrawioReadError）。

反标注（spec §4）：:func:`build_annotated_diagram_xml` 在原图 XML 上
追加 ``annot_sim`` 层（id 常量 :data:`ANNOT_LAYER_ID`）——先删旧层及其
全部子 cell 再追加新层（幂等，J5 迭代图不堆积历史层）；原 cell 零改动。
层名与 T-O8 评审标注层 ``annot`` 区分（两规格遗留节互引）。

确定性：同输入两次构建逐字节相同——id 由调用方/本模块常量表给定
（禁 uuid）、零时间戳、ElementTree 属性序=插入序、ET.indent 幂等。

分层：core 层，仅 import 标准库 + 同层 core.drawio_xml；零 linkage/
adapters 依赖（族数值缺省在 linkage.ads_template_family，由 service
注入——core 只认参数键名与文本形态，不认数值）。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from rfauto.core.drawio_xml import DEFAULT_PAGE_ATTRS, DrawioReadError

__all__ = [
    "ANNOT_LAYER_ID",
    "CircuitDiagramError",
    "build_annotated_diagram_xml",
    "build_circuit_diagram_xml",
    "family_param_keys",
    "family_param_owner",
    "parse_effective_params",
    "read_circuit_params",
    "write_circuit_xml",
]

#: 反标注层 cell id（与 T-O8 评审标注层 ``annot`` 区分，spec §4.1）
ANNOT_LAYER_ID = "annot_sim"

#: UserObject 属性三件组前缀（spec §2.1 形态规则 1）
_PARAM_PREFIX = "p_"
_UNIT_PREFIX = "unit_"
_SRC_PREFIX = "src_"

#: 一级参数键 attr 名（p_<key> → key）；sweep 二级 attr 名 p_sweep_<k>。
_SWEEP_ATTR = "sweep_"

#: 嵌套参数键唯一允许的一级段（spec §2.2：p_sweep_<k> 二级、p_<k> 一级）
_NESTED_HEAD = "sweep"

#: 频扫四键（空串/缺失 = 缺项，resolve_sweep 走 Touchstone 兜底——spec §2.2）
_SWEEP_DOTTED = ("sweep.fstart", "sweep.fstop", "sweep.npoints", "sweep.unit")


class CircuitDiagramError(ValueError):
    """电路图内核显式错误（家族未知/参数键面违约/骨架不完整/键冲突）——
    ValueError 子类，service 层错误信封（except ValueError）直接捕获。"""


# --------------------------------------------------------------------------- #
# 族布局单表：参数键 → 承载卡（build 与 read-back 两方向共用的唯一结构）
# --------------------------------------------------------------------------- #

#: 每族参数键全集与承载卡 cell id（spec §2.3 PARAM_KEYS 白名单的图面布局侧；
#: 与 service.circuit_sim_service.PARAM_KEYS 的一致性由
#: tests/unit/test_circuit_sim_service.py 白名单自证钉逐位断言——#231 家法
#: 参数版：两表面各自演化时忘同步即红）。
_FAMILY_KEYS: dict[str, dict[str, str]] = {
    "wilkinson_snp": {
        "sweep.fstart": "uobj_setup",
        "sweep.fstop": "uobj_setup",
        "sweep.npoints": "uobj_setup",
        "sweep.unit": "uobj_setup",
        "z0": "uobj_setup",
        "n_ports": "uobj_setup",
    },
    "branchline_cascade": {
        "sweep.fstart": "uobj_setup",
        "sweep.fstop": "uobj_setup",
        "sweep.npoints": "uobj_setup",
        "sweep.unit": "uobj_setup",
        "z0": "uobj_setup",
        "f0_hz": "uobj_setup",
        "z_line": "uobj_tlin1",
        "theta_in_deg": "uobj_tlin1",
        "theta_out_deg": "uobj_tlin2",
    },
    # M3 增补两族（aurora_p A2；设计定稿 runs/aurora_p/a2/M3_DESIGN.md）。
    # active_chain_sparam：FSTART/FSTOP 由渲染器从两 Touchstone 频段交集
    # 推导（非用户参数，故无 sweep.* 键）；match_snp=匹配网络 Touchstone
    # 路径（数据文件位参上图——device 走 run --snp，同 MVP snp_path
    # 排除语义的显式例外，自证钉见 tests/unit/test_circuit_diagram_active.py）。
    "active_chain_sparam": {
        "frequency_unit": "uobj_setup",
        "npoints": "uobj_setup",
        "z0": "uobj_setup",
        "match_snp": "uobj_mn",
    },
    # loadpull_hb：HB 单点无频扫；z_load_re/z_load_im 成对 ↔ 渲染器
    # z_load: complex（service 组装 complex(re, im)，负虚部括号形态 #293
    # 家法由渲染器单源承担）——自证钉同上文件。
    "loadpull_hb": {
        "f0_hz": "uobj_hb",
        "power_dbm": "uobj_hb",
        "harmonic_order": "uobj_hb",
        "frequency_unit": "uobj_hb",
        "z0": "uobj_hb",
        "z_load_re": "uobj_load",
        "z_load_im": "uobj_load",
    },
}


def family_param_keys(family: str) -> tuple[str, ...]:
    """族参数键全集（确定性序=声明序；未知族显式 CircuitDiagramError）。"""
    layout = _FAMILY_KEYS.get(family)
    if layout is None:
        raise CircuitDiagramError(
            f"未知模板族 {family!r}（支持 {sorted(_FAMILY_KEYS)}）")
    return tuple(layout)


def family_param_owner(family: str, key: str) -> str:
    """参数键 → 预期承载卡 cell id（未知键/族显式报错——错误文案消费）。"""
    layout = _FAMILY_KEYS.get(family)
    if layout is None:
        raise CircuitDiagramError(f"未知模板族 {family!r}")
    if key not in layout:
        raise CircuitDiagramError(
            f"{family} 无参数键 {key!r}（白名单见 PARAM_KEYS/{family}）")
    return layout[key]


# --------------------------------------------------------------------------- #
# 样式与几何常量（per-family 固定布局模板——spec §2.1 形态规则 4，拓扑固定）
# --------------------------------------------------------------------------- #

#: 元件卡蓝系（与 T-O1 _STAGE_STYLE 同色系）
_COMP_STYLE = "rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"
#: Setup 面板黄系（spec §2.2）
_SETUP_STYLE = "rounded=0;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;align=left;"
#: 终止卡灰系虚线（"终止"语义，spec §2.1 wilkinson/branchline 布局注记）
_TERM_STYLE = "rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;dashed=1;"
#: 信号流实线 / 终止虚线
_EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;"
_TERM_EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;dashed=1;strokeColor=#999999;"
#: 测量/信息卡灰系实线（loadpull aele 卡——渲染器产测量方程的展示位，
#: 无参数属性；与终止卡虚线区分：观测语义非信号流但卡本身非"终止"）
_INFO_STYLE = "rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;align=left;"
#: 标题文本
_TITLE_STYLE = ("text;html=1;strokeColor=none;fillColor=none;align=left;"
                "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontStyle=1")

_MXFILE_ATTRS = {"host": "rfauto", "type": "device", "version": "24.7.7"}

# 布局几何（px；A4 纵向栅格页上，右栏 1060 起为反标注列预留——反标注卡
# 几何/样式常量在 service.circuit_sim_service，卡面内容由 service 产）
_TITLE_GEOM = (40, 20, 660, 26)
_SETUP_GEOM_WILKINSON = (620, 60, 400, 140)
_SETUP_GEOM_BRANCHLINE = (40, 60, 560, 120)
_SETUP_GEOM_ACTIVE = (40, 60, 480, 120)
_SETUP_GEOM_LOADPULL = (40, 60, 500, 132)
_PORT_W, _PORT_H = 180, 56
_PORT_Y0, _PORT_STEP = 240, 74
_SNP_GEOM_WILKINSON = (300, 240, 340, 76)
_CHAIN_Y = 260
_TLIN_W, _TLIN_H = 180, 76
_SNP_GEOM_BRANCHLINE = (390, 250, 210, 76)
_TERM_Y = 400
_TERM_W, _TERM_H = 210, 48
# M3 新族链路横排（y 与 MVP _CHAIN_Y 同带；块卡 220×72）
_BLK_W, _BLK_H = 220, 72
_BLK_Y = 256
_ACTIVE2_Y = 264
_MN_X, _DEV2_X = 300, 580
_LOAD_X, _PORT2_X, _AELE_GEOM = 580, 860, (300, 384, 500, 64)


def _dotted_to_attr(key: str) -> str:
    """dotted 参数键 → attr 名段（sweep.fstart → sweep_fstart）。"""
    if key.startswith(f"{_NESTED_HEAD}."):
        return _SWEEP_ATTR + key[len(_NESTED_HEAD) + 1:]
    return key


def _attr_to_dotted(attr_key: str) -> str:
    """attr 名段 → dotted 参数键（sweep_fstart → sweep.fstart）。"""
    if attr_key.startswith(_SWEEP_ATTR):
        return f"{_NESTED_HEAD}.{attr_key[len(_SWEEP_ATTR):]}"
    return attr_key


def _setup_label(family: str) -> str:
    """Setup 卡 placeholders 文案（缺项语义上图显式化——spec §2.2；
    M3 两族 setup 形态见 runs/aurora_p/a2/M3_DESIGN.md §1）。"""
    if family == "active_chain_sparam":
        return (
            "Setup（S 参数扫频——频扫=两 SnP 频段交集，渲染时定）\n"
            "unit=%p_frequency_unit%   npoints=%p_npoints%\n"
            "Z0=%p_z0% Ohm")
    if family == "loadpull_hb":
        return (
            "HB 单点 load-pull（无频扫）\n"
            "f0=%p_f0_hz% Hz   P_in=%p_power_dbm% dBm\n"
            "Order=%p_harmonic_order%   Z0=%p_z0% Ohm   unit=%p_frequency_unit%")
    head = (
        "Setup（频扫——留空=随 SnP 频带）\n"
        "fstart=%p_sweep_fstart% %p_sweep_unit%  "
        "fstop=%p_sweep_fstop% %p_sweep_unit%\n"
        "npoints=%p_sweep_npoints%")
    if family == "wilkinson_snp":
        return head + "\nz0=%p_z0% Ohm   n_ports=%p_n_ports%"
    return head + "\nf0=%p_f0_hz% Hz   z0=%p_z0% Ohm"


def _label(family: str, owner: str, snp_name: str, n_ports: int) -> str:
    """承载卡 placeholders 文案（per-family 固定布局模板的一部分）。"""
    if owner in ("uobj_setup", "uobj_hb"):
        return _setup_label(family)
    if owner == "uobj_mn":
        return "SnP:MN（匹配网络 2 口）\nFile=%p_match_snp%"
    if owner == "uobj_dev":
        return (
            f"SnP:DEV（器件 2 口）\nFile={snp_name}\n"
            "（File 由 run --snp 指定，图上仅示名）")
    if owner == "uobj_src":
        return "Port:SRC（源）\nZ=Z0（见 Setup 卡）  P=P_in（见 Setup 卡）"
    if owner == "uobj_load":
        return "Port:P2（负载）\nZ=%p_z_load_re%+j*(%p_z_load_im%) Ohm"
    if owner == "uobj_aele":
        return ("aele 测量（渲染器产）\nPout_W / Pout_dBm / Gain_dB\n"
                "（Z_L 与 P_in 随渲染注入）")
    if owner == "uobj_snp":
        return (
            f"SnP1（NumPorts={n_ports}）\nFile={snp_name}\n"
            "（File 由 run --snp 指定，图上仅示名）")
    if owner == "uobj_tlin1":
        return "TLIN1（入线）\nZ=%p_z_line% Ohm  E=%p_theta_in_deg% deg"
    if owner == "uobj_tlin2":
        return "TLIN2（出线）\nE=%p_theta_out_deg% deg（Z 同 TLIN1 卡）"
    if owner.startswith("uobj_port"):
        return owner.replace("uobj_port", "P", 1)
    if owner.startswith("uobj_term"):
        return owner.replace("uobj_term", "P", 1) + "（匹配终止）"
    raise CircuitDiagramError(f"未知承载卡 {owner!r}")


def _owner_geometry(family: str, owner: str, n_ports: int) -> tuple[int, int, int, int]:
    """承载卡几何（x, y, w, h）——per-family 固定布局模板（坐标常量表）。"""
    if owner in ("uobj_setup", "uobj_hb"):
        if family == "wilkinson_snp":
            return _SETUP_GEOM_WILKINSON
        if family == "branchline_cascade":
            return _SETUP_GEOM_BRANCHLINE
        if family == "active_chain_sparam":
            return _SETUP_GEOM_ACTIVE
        return _SETUP_GEOM_LOADPULL
    if owner == "uobj_mn":
        return (_MN_X, _BLK_Y, _BLK_W, _BLK_H)
    if owner == "uobj_dev":
        if family == "active_chain_sparam":
            return (_DEV2_X, _BLK_Y, _BLK_W, _BLK_H)
        return (_MN_X, _BLK_Y, _BLK_W, _BLK_H)
    if owner == "uobj_src":
        return (40, _ACTIVE2_Y, _PORT_W, _PORT_H)
    if owner == "uobj_load":
        return (_LOAD_X, _BLK_Y, _BLK_W, _BLK_H)
    if owner == "uobj_aele":
        return _AELE_GEOM
    if family == "active_chain_sparam" and owner.startswith("uobj_port"):
        i = int(owner.rsplit("port", 1)[1]) - 1
        return (40, _ACTIVE2_Y, _PORT_W, _PORT_H) if i == 0 else (_PORT2_X, _ACTIVE2_Y, _PORT_W, _PORT_H)
    if owner == "uobj_snp":
        return _SNP_GEOM_WILKINSON if family == "wilkinson_snp" else _SNP_GEOM_BRANCHLINE
    if owner == "uobj_tlin1":
        return (170, _CHAIN_Y - 10, _TLIN_W, _TLIN_H)
    if owner == "uobj_tlin2":
        return (640, _CHAIN_Y - 10, _TLIN_W, _TLIN_H)
    if owner.startswith("uobj_port"):
        i = int(owner.rsplit("port", 1)[1]) - 1
        return (40, _PORT_Y0 + i * _PORT_STEP, _PORT_W, _PORT_H)
    if owner.startswith("uobj_term"):
        i = int(owner.rsplit("term", 1)[1]) - 1
        return (390 + i * 250, _TERM_Y, _TERM_W, _TERM_H)
    raise CircuitDiagramError(f"未知承载卡 {owner!r}")


def _owner_ids(family: str, n_ports: int) -> list[str]:
    """族的承载卡 id 全集（拓扑固定——spec §2.1 形态规则 4）。"""
    if family == "wilkinson_snp":
        return ["uobj_setup", "uobj_snp"] + [f"uobj_port{i}" for i in range(1, n_ports + 1)]
    if family == "branchline_cascade":
        return ["uobj_setup", "uobj_snp", "uobj_tlin1", "uobj_tlin2", "uobj_term3", "uobj_term4"]
    if family == "active_chain_sparam":
        return ["uobj_setup", "uobj_mn", "uobj_dev", "uobj_port1", "uobj_port2"]
    return ["uobj_hb", "uobj_src", "uobj_dev", "uobj_load", "uobj_aele"]


def _attr_text(value: Any, name: str) -> str:
    """属性值 → 文本（str 原样；数值 str() 收敛；bool 显式拒绝——
    bool 是 int 子类，str(True)="True" 落图必是手误；与 drawio_xml 同款家法）。"""
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


def _add_userobject(
    root: ET.Element,
    uo_id: str,
    label: str,
    *,
    style: str,
    x: Any,
    y: Any,
    width: Any,
    height: Any,
    attrs: dict[str, Any] | None = None,
    parent: str = "1",
) -> ET.Element:
    """挂一个 UserObject 包装 vertex（label+placeholders+三件组属性 +
    内层 mxCell(geometry)；parent 指向图层 cell id）。id 重复显式报错。"""
    uo_attrs: dict[str, str] = {"label": _attr_text(label, f"{uo_id}.label"),
                                "placeholders": "1", "id": uo_id}
    for key, val in (attrs or {}).items():
        if key in uo_attrs:
            raise CircuitDiagramError(
                f"UserObject {uo_id!r} 属性 {key!r} 与结构性固定属性冲突（禁覆盖）")
        uo_attrs[key] = _attr_text(val, f"{uo_id}.{key}")
    uo = ET.SubElement(root, "UserObject", uo_attrs)
    cell = ET.SubElement(uo, "mxCell", {"style": _attr_text(style, f"{uo_id}.style"),
                                        "vertex": "1", "parent": parent})
    ET.SubElement(cell, "mxGeometry", {
        "x": _attr_text(x, f"{uo_id}.x"), "y": _attr_text(y, f"{uo_id}.y"),
        "width": _attr_text(width, f"{uo_id}.width"),
        "height": _attr_text(height, f"{uo_id}.height"), "as": "geometry"})
    return uo


def _add_vertex(root: ET.Element, cell_id: str, value: str, *,
                style: str, x: Any, y: Any, width: Any, height: Any) -> ET.Element:
    """挂纯文本/块面 vertex（标题类；无参数属性）。id 重复显式报错。"""
    cell = ET.SubElement(root, "mxCell", {
        "id": cell_id, "value": _attr_text(value, f"{cell_id}.value"),
        "style": _attr_text(style, f"{cell_id}.style"), "vertex": "1", "parent": "1"})
    ET.SubElement(cell, "mxGeometry", {
        "x": _attr_text(x, f"{cell_id}.x"), "y": _attr_text(y, f"{cell_id}.y"),
        "width": _attr_text(width, f"{cell_id}.width"),
        "height": _attr_text(height, f"{cell_id}.height"), "as": "geometry"})
    return cell


def _add_edge(root: ET.Element, edge_id: str, *, source: str, target: str,
              style: str, parent: str = "1") -> ET.Element:
    """挂 edge cell（source/target 引 UserObject id；drawio 边几何惯例）。"""
    cell = ET.SubElement(root, "mxCell", {
        "id": edge_id, "value": "", "style": _attr_text(style, f"{edge_id}.style"),
        "edge": "1", "parent": parent, "source": source, "target": target})
    ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
    return cell


def _new_skeleton(diagram_id: str, diagram_name: str) -> ET.Element:
    """mxfile>diagram>mxGraphModel>root + 基 cell 0/1（T-O2 内核同款骨架；
    页属性复用内核 DEFAULT_PAGE_ATTRS）。返回 root 元素。"""
    mxfile = ET.Element("mxfile", dict(_MXFILE_ATTRS))
    ET.SubElement(mxfile, "diagram", {"id": diagram_id, "name": diagram_name})
    model = ET.SubElement(mxfile.find("diagram"), "mxGraphModel", dict(DEFAULT_PAGE_ATTRS))
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    return mxfile


def _to_xml_text(mxfile: ET.Element) -> str:
    """装配 → 完整 .drawio XML 文本（未压缩 mxfile；ET.indent 幂等逐字节）。"""
    ET.indent(mxfile, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(mxfile, encoding="unicode") + "\n"


def _parse_skeleton(xml_text: str) -> ET.Element:
    """.drawio XML 文本 → 校验骨架后返回 mxGraphModel>root 元素。

    坏 XML / 非 mxfile / 缺 diagram / 缺 mxGraphModel（含 draw.io 压缩页）/
    缺 root / 缺基 cell id=0 显式 DrawioReadError（与内核 read 面同口径）。
    """
    if not isinstance(xml_text, str):
        raise DrawioReadError(f"xml_text 必须是字符串，收到 {type(xml_text)!r}")
    try:
        mxfile = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise DrawioReadError(f"XML 解析失败：{exc}") from exc
    if mxfile.tag != "mxfile":
        raise DrawioReadError(f"根元素必须是 mxfile，收到 {mxfile.tag!r}")
    diagram = mxfile.find("diagram")
    if diagram is None:
        raise DrawioReadError("缺 diagram 元素（mxGraph 骨架不完整）")
    model = diagram.find("mxGraphModel")
    if model is None:
        raise DrawioReadError(
            f"diagram {diagram.get('id')!r} 缺 mxGraphModel"
            "（压缩页或非本内核产物不支持——read 面面向未压缩 mxfile）")
    root = model.find("root")
    if root is None:
        raise DrawioReadError("缺 root 元素（mxGraph 骨架不完整）")
    ids = {c.get("id") for c in root.findall("mxCell")}
    if "0" not in ids:
        raise DrawioReadError("root 缺基 cell id=0（mxGraph 骨架不完整）")
    return root


# --------------------------------------------------------------------------- #
# J1 出图：族 + 参数文本 → 可调电路图
# --------------------------------------------------------------------------- #

def build_circuit_diagram_xml(
    family: str,
    values: dict[str, Any],
    *,
    n_ports: int,
    snp_name: str = "",
    title: str | None = None,
) -> str:
    """族 + 参数文本表 → 可调电路图 .drawio XML（J1 出图内核）。

    Args:
        family: 模板族名（MVP 钉死 wilkinson_snp / branchline_cascade）。
        values: 参数键（dotted）→ **文本**值（格式化单源在 service；本函数
            不做数值格式化）。键集必须恰等 :func:`family_param_keys`——
            缺键/多余键显式报错（生成面永远全键在图，读回侧缺键语义由
            service 三态裁决）。
        n_ports: SnP 端口数（port 卡/SnP 卡标签与拓扑用；wilkinson 须与
            values["n_ports"] 文本一致——图内数字自洽守卫）。
        snp_name: SnP 文件名（仅入卡标签示名；File 由 run --snp 指定）。
        title: 图标题（None 用缺省标题）。

    Returns:
        未压缩 mxfile XML 文本（逐字节确定性）。
    """
    layout = _FAMILY_KEYS.get(family)
    if layout is None:
        raise CircuitDiagramError(
            f"未知模板族 {family!r}（支持 {sorted(_FAMILY_KEYS)}）")
    expected = set(layout)
    given = set(values)
    if given != expected:
        missing = sorted(expected - given)
        extra = sorted(given - expected)
        raise CircuitDiagramError(
            f"参数键面违约：缺 {missing} 多 {extra}（生成面必须恰给全键 "
            f"{sorted(expected)}——读回侧缺键语义由 service 三态裁决）")
    n = int(n_ports)
    if n < 1:
        raise CircuitDiagramError(f"端口数必须 ≥ 1，实际 {n}")
    if family == "branchline_cascade" and n != 4:
        raise CircuitDiagramError(
            f"branchline_cascade 拓扑固定 4 端口（SnP），实际 {n}")
    if family in ("active_chain_sparam", "loadpull_hb") and n != 2:
        raise CircuitDiagramError(
            f"{family} 拓扑固定 2 端口（源/负载），实际 {n}")
    if family == "wilkinson_snp":
        n_text = _attr_text(values["n_ports"], "values[n_ports]").strip()
        try:
            n_from_values = int(n_text)
        except ValueError as exc:
            raise CircuitDiagramError(
                f"n_ports 文本必须是整数，收到 {n_text!r}") from exc
        if n_from_values != n:
            raise CircuitDiagramError(
                f"n_ports 文本 {n_text!r} 与 port 卡拓扑 n_ports={n} 不一致"
                "（图内数字须自洽）")

    # 值文本 → 承载卡三件组属性（unit/src 文本由调用方给？——不：unit/src
    # 属图面 provenance 形态，本模块按键名单源生成；值文本才是调用方的）
    card_attrs: dict[str, dict[str, str]] = {
        owner: {} for owner in _owner_ids(family, n)}
    for key, text in values.items():
        owner = layout[key]
        seg = _dotted_to_attr(key)
        card_attrs[owner][f"{_PARAM_PREFIX}{seg}"] = _attr_text(text, f"values[{key}]")
        card_attrs[owner][f"{_UNIT_PREFIX}{seg}"] = _unit_of(key)
        card_attrs[owner][f"{_SRC_PREFIX}{seg}"] = "input"  # v1 参数值恒 input（spec §2.1）

    mxfile = _new_skeleton("circuit-diagram", "ADS Circuit")
    root = mxfile.find("diagram").find("mxGraphModel").find("root")

    title_text = title if title else (
        f"ADS 前仿电路图（{family}）——右键元件卡 Edit Data 改 p_* 属性后"
        "重开图看标签刷新")
    _add_vertex(root, "title", title_text, style=_TITLE_STYLE,
                x=_TITLE_GEOM[0], y=_TITLE_GEOM[1],
                width=_TITLE_GEOM[2], height=_TITLE_GEOM[3])

    for owner in _owner_ids(family, n):
        label = _label(family, owner, snp_name, n)
        x, y, w, h = _owner_geometry(family, owner, n)
        style = _SETUP_STYLE if owner in ("uobj_setup", "uobj_hb") else (
            _TERM_STYLE if owner.startswith("uobj_term")
            else (_INFO_STYLE if owner == "uobj_aele" else _COMP_STYLE))
        _add_userobject(root, owner, label, style=style, x=x, y=y, width=w, height=h,
                        attrs={**card_attrs[owner], "family": family,
                               "kind": _kind_of(owner),
                               "element_id": owner.replace("uobj_", "").upper()})

    # 连线拓扑（固定——v1 不做自由绘制/拓扑编辑，spec §2.1 诚实边界）
    if family == "wilkinson_snp":
        for i in range(1, n + 1):
            _add_edge(root, f"edge_p{i}", source=f"uobj_port{i}", target="uobj_snp",
                      style=_EDGE_STYLE)
    elif family == "active_chain_sparam":
        _add_edge(root, "edge_p1_mn", source="uobj_port1", target="uobj_mn", style=_EDGE_STYLE)
        _add_edge(root, "edge_mn_dev", source="uobj_mn", target="uobj_dev", style=_EDGE_STYLE)
        _add_edge(root, "edge_dev_p2", source="uobj_dev", target="uobj_port2", style=_EDGE_STYLE)
    elif family == "loadpull_hb":
        _add_edge(root, "edge_src_dev", source="uobj_src", target="uobj_dev", style=_EDGE_STYLE)
        _add_edge(root, "edge_dev_load", source="uobj_dev", target="uobj_load", style=_EDGE_STYLE)
        # aele=观测语义虚线（非信号流，与终止虚线同款边样式）
        _add_edge(root, "edge_dev_aele", source="uobj_dev", target="uobj_aele",
                  style=_TERM_EDGE_STYLE)
    else:
        _add_edge(root, "edge_p1", source="uobj_port1",
                  target="uobj_tlin1", style=_EDGE_STYLE)
        _add_edge(root, "edge_tlin1_snp", source="uobj_tlin1", target="uobj_snp",
                  style=_EDGE_STYLE)
        _add_edge(root, "edge_snp_tlin2", source="uobj_snp", target="uobj_tlin2",
                  style=_EDGE_STYLE)
        _add_edge(root, "edge_tlin2_p2", source="uobj_tlin2", target="uobj_port2",
                  style=_EDGE_STYLE)
        # 终止语义=虚线（非信号流，spec §2.1 布局注记）
        _add_edge(root, "edge_snp_term3", source="uobj_snp", target="uobj_term3",
                  style=_TERM_EDGE_STYLE)
        _add_edge(root, "edge_snp_term4", source="uobj_snp", target="uobj_term4",
                  style=_TERM_EDGE_STYLE)
    return _to_xml_text(mxfile)


def _kind_of(owner: str) -> str:
    if owner == "uobj_setup":
        return "SETUP"
    if owner == "uobj_hb":
        return "SETUP"
    if owner in ("uobj_snp", "uobj_mn", "uobj_dev"):
        return "SNP"
    if owner in ("uobj_src", "uobj_load"):
        return "PORT"
    if owner == "uobj_aele":
        return "MEAS"
    if owner.startswith("uobj_tlin"):
        return "TLIN"
    if owner.startswith("uobj_port"):
        return "PORT"
    if owner.startswith("uobj_term"):
        return "TERM"
    raise CircuitDiagramError(f"未知承载卡 {owner!r}")


def _unit_of(key: str) -> str:
    """参数键 → unit 三件组的 unit 文本（图面 provenance；确定性表）。"""
    units = {
        "sweep.fstart": "GHz", "sweep.fstop": "GHz", "sweep.npoints": "1",
        "sweep.unit": "GHz", "z0": "Ohm", "n_ports": "1", "f0_hz": "Hz",
        "theta_in_deg": "deg", "theta_out_deg": "deg", "z_line": "Ohm",
        "frequency_unit": "GHz", "npoints": "1", "match_snp": "path",
        "power_dbm": "dBm", "harmonic_order": "1",
        "z_load_re": "Ohm", "z_load_im": "Ohm",
    }
    if key not in units:
        raise CircuitDiagramError(f"无单位表项的参数键 {key!r}")
    return units[key]


def write_circuit_xml(xml_text: str, path: Any) -> Path:
    """XML 文本落盘（UTF-8；父目录不存在显式报错不自动补救——service 家法）。"""
    out = Path(path)  # PathLike 入参第一行收敛（#140）
    if out.parent and not out.parent.exists():
        raise CircuitDiagramError(
            f"输出目录不存在：{out.parent}（请先建目录，不自动补救）")
    out.write_text(xml_text, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# 读回：.drawio → p_* 原文表（J2 消费面）
# --------------------------------------------------------------------------- #

def read_circuit_params(xml_text: str) -> dict[str, Any]:
    """.drawio XML → p_* 属性原文表（J2 读回；属性值原样字符串不静默强转）。

    Returns::

        {"family": str | None,       # 图内 family 属性（多值冲突显式报错）
         "raw": {dotted_key: text},  # 全部 p_* 属性（含白名单外——过滤在 service）
         "units": {dotted_key: text},
         "srcs": {dotted_key: text},
         "cells": {dotted_key: cell_id},   # 逐键 provenance（哪个卡携带）
         "labels": {cell_id: label},       # UserObject 标签原文
         "n_userobjects": int}

    重复键：同文本多卡携带=去重放行；异文本=显式冲突报错（防张冠李戴，
    #154 家法）。白名单外 p_ 键不在此过滤（service 按族白名单 warnings 忽略）。
    """
    root = _parse_skeleton(xml_text)
    raw: dict[str, str] = {}
    units: dict[str, str] = {}
    srcs: dict[str, str] = {}
    cells: dict[str, str] = {}
    labels: dict[str, str] = {}
    families: set[str] = set()
    n_uo = 0
    for el in root:
        if el.tag not in ("UserObject", "mxCell"):
            continue
        cell_id = el.get("id") or ""
        if el.tag == "UserObject":
            n_uo += 1
            labels[cell_id] = el.get("label") or ""
        fam = el.get("family")
        if fam:
            families.add(fam)
        p_keys = [k for k in el.attrib if k.startswith(_PARAM_PREFIX)]
        for attr in p_keys:
            key = _attr_to_dotted(attr[len(_PARAM_PREFIX):])
            text = el.get(attr) or ""
            if key in raw and raw[key] != text:
                raise CircuitDiagramError(
                    f"参数键 {key!r} 在多卡上取值冲突：{raw[key]!r}（{cells[key]}）"
                    f" vs {text!r}（{cell_id}）——每参数键单卡承载（防张冠李戴）")
            raw[key] = text
            cells[key] = cell_id
            unit_attr = el.get(f"{_UNIT_PREFIX}{attr[len(_PARAM_PREFIX):]}")
            if unit_attr is not None:
                units[key] = unit_attr
            src_attr = el.get(f"{_SRC_PREFIX}{attr[len(_PARAM_PREFIX):]}")
            if src_attr is not None:
                srcs[key] = src_attr
    if len(families) > 1:
        raise CircuitDiagramError(
            f"图内 family 属性多值冲突：{sorted(families)}（全图必须同族）")
    return {
        "family": next(iter(families)) if families else None,
        "raw": raw,
        "units": units,
        "srcs": srcs,
        "cells": cells,
        "labels": labels,
        "n_userobjects": n_uo,
    }


# --------------------------------------------------------------------------- #
# 文本 → 数值（spec §2.4 解析单源；数值语义=渲染器/resolve_sweep 终审）
# --------------------------------------------------------------------------- #

#: 整数参数键（npoints/n_ports；其余数值键=有限实数）
_INT_PARAM_KEYS = frozenset({"n_ports", "sweep.npoints", "npoints", "harmonic_order"})
#: 字符串键（枚举/路径，原样透传；枚举合法性由渲染器 resolve_sweep 终审——
#: 同表不重造，spec §2.4；match_snp=文件路径，存在性/端口数由 service 与
#: 渲染器终审）
_STR_PARAM_KEYS = frozenset({"sweep.unit", "frequency_unit", "match_snp"})


def parse_effective_params(raw: dict[str, str]) -> dict[str, Any]:
    """p_* 原文表 → 渲染器 params dict（spec §2.4 解析单源）。

    规则（钉死）：
    - ``sweep.*`` 空串/缺失 = 缺项（键从 sweep 子 dict 剔除——resolve_sweep
      走 Touchstone 兜底；unit 缺项由 resolve_sweep 缺省 GHz）；
    - 其余键空串/缺失 = 显式 CircuitDiagramError（spec §2.4：空串视为缺项
      仅限 sweep；缺键语义=误删，fail loud 不静默兜缺省——J2 编辑防线）；
    - 数值必须有限实数（nan/inf 显式报错；npoints/n_ports 整数）。

    白名单过滤不在此（service 按族白名单 warnings 忽略后传入）。
    """
    out: dict[str, Any] = {}
    sweep: dict[str, Any] = {}
    for key in sorted(raw):
        text = raw[key]
        if "." in key:
            head, _leaf = key.split(".", 1)
            if head != _NESTED_HEAD:
                raise CircuitDiagramError(
                    f"嵌套参数键仅支持 {_NESTED_HEAD}.*，收到 {key!r}")
            if text.strip() == "":
                continue  # 缺项语义（sweep 专属）
            sweep[key.split(".", 1)[1]] = _parse_scalar(key, text)
        else:
            if text.strip() == "":
                raise CircuitDiagramError(
                    f"参数 {key!r} 值为空（空串=缺项仅限 sweep.*；"
                    "非 sweep 键空值=J2 误删，显式报错不静默）")
            out[key] = _parse_scalar(key, text)
    if sweep:
        out[_NESTED_HEAD] = sweep
    return out


def _parse_scalar(key: str, text: str) -> float | int | str:
    """单值文本 → 数值（int 键整数、unit 键字符串透传、其余有限实数）。"""
    if key in _STR_PARAM_KEYS:
        return text.strip()
    if key in _INT_PARAM_KEYS:
        try:
            return int(text.strip())
        except ValueError as exc:
            raise CircuitDiagramError(
                f"参数 {key!r} 必须是整数，收到 {text!r}") from exc
    try:
        val = float(text.strip())
    except ValueError as exc:
        raise CircuitDiagramError(
            f"参数 {key!r} 必须是有限实数，收到 {text!r}") from exc
    if val != val or val in (float("inf"), float("-inf")):
        raise CircuitDiagramError(f"参数 {key!r} 必须为有限实数，收到 {text!r}")
    return val


# --------------------------------------------------------------------------- #
# J4 反标注：指标卡表 → 原图追加 annot_sim 层（幂等）
# --------------------------------------------------------------------------- #

def build_annotated_diagram_xml(
    xml_text: str,
    cards: list[dict[str, Any]],
    *,
    layer_title: str = "前仿指标（annot_sim）",
) -> str:
    """原图 XML + 指标卡表 → 反标注 XML（spec §4：先删旧 annot_sim 层再追加）。

    Args:
        xml_text: 原图 XML 文本（--diagram 只读，改动只发生在返回文本）。
        cards: 卡表（service 产；每卡严格键 ``{id, label, style, x, y, width,
            height, attrs}``；attrs 值 str/int/float，bool 拒；样式绿色=ok
            红色=fail 由 service 按 gate_ok 选——不凑绿语义的颜色化）。
        layer_title: annot_sim 层 cell 的 value 文案。

    Returns:
        新 XML 文本（原 cell 零改动 + annot_sim 层及卡；逐字节确定性）。
    """
    if not isinstance(xml_text, str):
        raise DrawioReadError(f"xml_text 必须是字符串，收到 {type(xml_text)!r}")
    try:
        mxfile = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise DrawioReadError(f"XML 解析失败：{exc}") from exc
    if mxfile.tag != "mxfile":
        raise DrawioReadError(f"根元素必须是 mxfile，收到 {mxfile.tag!r}")
    diagram = mxfile.find("diagram")
    if diagram is None:
        raise DrawioReadError("缺 diagram 元素（mxGraph 骨架不完整）")
    model = diagram.find("mxGraphModel")
    if model is None:
        raise DrawioReadError(
            f"diagram {diagram.get('id')!r} 缺 mxGraphModel"
            "（压缩页或非本内核产物不支持——read 面面向未压缩 mxfile）")
    root = model.find("root")
    if root is None:
        raise DrawioReadError("缺 root 元素（mxGraph 骨架不完整）")
    # 幂等：删旧 annot_sim 层 cell 及其全部子 cell（J5 迭代不堆积历史层）。
    # 卡=UserObject 包装形态，parent 属性在内层 mxCell 上（非 UserObject
    # 本身）——两处都要查，漏内层则二次反标注整层堆积。
    for el in list(root):
        if el.get("id") == ANNOT_LAYER_ID:
            root.remove(el)
            continue
        inner_parent = None
        if el.tag == "UserObject":
            inner = el.find("mxCell")
            inner_parent = inner.get("parent") if inner is not None else None
        if el.get("parent") == ANNOT_LAYER_ID or inner_parent == ANNOT_LAYER_ID:
            root.remove(el)
    ET.SubElement(root, "mxCell", {
        "id": ANNOT_LAYER_ID, "value": _attr_text(layer_title, "annot_sim.value"),
        "style": "", "parent": "0"})
    for card in cards:
        missing = {"id", "label", "style", "x", "y", "width", "height"} - set(card)
        if missing:
            raise CircuitDiagramError(f"指标卡缺键 {sorted(missing)}（schema 七键+attrs）")
        uo_id = str(card["id"])
        if uo_id == ANNOT_LAYER_ID:
            raise CircuitDiagramError(f"卡 id {uo_id!r} 与层 id 冲突")
        _add_userobject(
            root, uo_id, card["label"], style=card["style"],
            x=card["x"], y=card["y"], width=card["width"], height=card["height"],
            attrs=dict(card.get("attrs") or {}), parent=ANNOT_LAYER_ID)
    return _to_xml_text(mxfile)
