"""测试连接图 .drawio 生成器（T-O6：声明式场景 → 原生可编辑 mxGraph 工程图）。

与 T-O1 链路框图（数字标图，Friis 内核单源）正好互补的两极：本模块是
**纯声明式生成器**——零物理内核零公式（铁律 7 的另一面）：图上若出现
"数字"只有一类=线缆损耗/长度等**用户 JSON 显式给的标注值**，原样标图
（source=输入 JSON 键，零换算零 dB 运算——grep 面见测试钉）。
第一验收面=**拓扑正确性**：JSON 连接表 ↔ XML edge 集合双射、端口引用
完整性（负例显式 ValueError）、端口标签在图上可见——全部确定性可断言。
零换算红线：装配代码路径零对数/幂运算调用（测试 grep 面钉死）。

XML 装配走 T-O2 通用内核 :mod:`rfauto.core.drawio_xml`（DrawioDocument
写面；本模块禁止另写文档级装配器）。形态出处（spec
runs/aurora_o/design_specs/T-O6_TESTSETUP_SPEC.md 钉死 + T-O1 家法）：

- 仪器卡 = mxCell + 自定义属性（kind/role/ports/note/placeholders）——
  spec §3.3 的 UserObject 包装形态在内核 v1 的**等价形态**（内核边界钉：
  UserObject 包装不支持，``extra_attrs`` 直写 mxCell 属性等价可读回，见
  core/drawio_xml.py docstring 边界节）；label 三行=主标签/kind/note。
- 端口点 = 仪器**子 cell**（``parent=<仪器 id>``、几何相对父左上、id 形态
  ``<inst>.<port>``）——draw.io 组内端口原生惯例，人工拖仪器端口跟随；
  ``<inst>.<port>`` 全局唯一由"仪器 id 禁 ``.``"（``[A-Za-z0-9_-]+``）保证。
- 连接边 = 正交 edge（T-O1 ``_EDGE_STYLE`` 同串+fontSize 段），
  source/target=端口点 id（端口语义精确到点，不指仪器主体）；边标签=
  cable 拼接串（``<label>  <loss> dB  <length> m``，两空格分隔）+自由
  标注拼接（先 cable 后自由）。
- CAL 校准面 = cal_plane 边的**子 label cell**（内核返回元素上挂子元素
  ——docstring 许可的扩展点；``relative="1"`` 几何 + value "▎CAL" 红色
  加粗）；cal_plane=false 边零子 cell。
- 布局 = role→五列常量表分层（stim/inline/dut/anal/aux 列 x 单源），
  同列多台按 JSON 序自上而下；DUT 列垂直居中于全图行跨中位（视觉中心）；
  端口点按 role 落仪器卡左/右缘（stim/inline 右缘、anal/aux 左缘、dut
  按声明序对半分，奇数时中间端口落右缘顶部+warnings 提示）。v1 诚实
  边界：不做通用正交布线器——层间正交边由 draw.io
  ``orthogonalEdgeStyle;jettySize=auto`` 自动路由，残余交叉靠人工微调
  （产出=原生可编辑文件），同列 >2 台在 warnings 提示交叉风险。

确定性：同输入两次构建 XML 逐字节相同——cell id 全部确定性命名
（仪器 id 原样/端口 ``<inst>.<port>``/``conn<i>``/``note<i>``/标题
"title"，禁 uuid）、零时间戳、ElementTree 属性序=插入序。

标注数值文本单源 = :func:`format_quantity`（装配与测试断言同函数；
spec §3.5 示例锚：loss_db=0.5→"0.5 dB"、length_m=1.0→"1 m"——整数
值不带小数点，非整数值=JSON 原值最短往返表示）。

aurora_p A3 扩展（2026-11-01，opt-in 双档零破坏）：

- **CISPR/EMI kind 扩展**：:data:`CISPR_KIND_TABLE` 六键并入
  :data:`EFFECTIVE_KIND_TABLE` 查表（既有 :data:`KIND_TABLE` 保持 10 键
  不动=既有逐键断言钉）；未知 kind 拒绝语义不变（枚举=合并视图）。
- **专业形状档**：scene 顶层新 opt-in 键 ``shapes``（缺省/None=缺省档
  零形状名依赖——XML 逐字节同 T-O6 现状，A/B 兼容钉在测试）。串值
  ``"electrical"`` 走 :data:`SHAPE_PROFILES` 档（kind→mxgraph.electrical.*
  映射，形状名全部实读核对——证据 runs/aurora_p/a3_shapes/
  SHAPE_EVIDENCE.md，#215 纪律）；dict=per-kind 形状名覆盖。无忠实
  stencil 的 kind **如实不映射**保持缺省矩形卡（grep 负证据落盘）。

零 IO（纯函数返回 XML 文本与 plan dict；落盘在 service 层）、零第三方
依赖（仅 xml.etree/math/re 标准库 + 同层 core.drawio_xml）。
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from typing import Any

from rfauto.core.drawio_xml import DEFAULT_PAGE_ATTRS, new_document, page_attrs

__all__ = [
    "build_testsetup_diagram_xml",
    "build_testsetup_plan",
    "format_quantity",
    "normalize_scene",
]

# ─── 常量单源（kind→role/颜色查表 = 本模块单源，测试逐键断言） ──────────────

#: kind 枚举（基础档定死 10 个，未知 kind 显式 ValueError——不静默 generic；
#: CISPR/EMI 扩展键见下方 CISPR_KIND_TABLE，查表走 EFFECTIVE_KIND_TABLE）→
#: (role 缺省, fillColor, strokeColor)（drawio 经典色板，spec §2.4 表）
KIND_TABLE: dict[str, tuple[str, str, str]] = {
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

#: aurora_p A3 扩展 kind（CISPR/EMI 测试场景，2026-11-01）——**拆表并入**：
#: 既有 KIND_TABLE 保持 10 键不动（逐键断言=测试金标准），扩展键查表走
#: EFFECTIVE_KIND_TABLE 合并视图（缺省 role/色板与基础表同风格）。场景件：
#: EMI 测量接收机（CISPR 16-1-1）/电流探头（CISPR 25 电流探头法）/
#: 参考接地板/负载模拟器/蓄电池（DC 馈电）/天线杆（辐射发射场）。
CISPR_KIND_TABLE: dict[str, tuple[str, str, str]] = {
    "emi_receiver": ("anal", "#ffe6cc", "#d79b00"),
    "current_probe": ("anal", "#ffe6cc", "#d79b00"),
    "anchor_plane": ("aux", "#f5f5f5", "#666666"),
    "load_simulator": ("aux", "#f5f5f5", "#666666"),
    "battery": ("aux", "#f5f5f5", "#666666"),
    "antenna_mast": ("aux", "#f5f5f5", "#666666"),
}

#: kind 查表合并视图（基础 10 键 + CISPR 扩展键；两表无重叠键，写法上
#: KIND_TABLE 后并=基础键优先，防御式）——normalize/装配单源入口。
EFFECTIVE_KIND_TABLE: dict[str, tuple[str, str, str]] = {
    **CISPR_KIND_TABLE, **KIND_TABLE}

#: role 枚举（布局分派五列）
ROLES: tuple[str, ...] = ("stim", "inline", "dut", "anal", "aux")

#: role → 列 x（px，spec §3.2 五列布局常量表单源）
ROLE_COLUMN_X: dict[str, int] = {
    "stim": 40, "inline": 320, "dut": 600, "anal": 880, "aux": 1160,
}

#: 行几何（px）：行 y0=100、行步距=160（仪器卡 120×64 + 行距 96）
ROW_Y0 = 100
ROW_STEP = 160
CARD_W = 120
CARD_H = 64
#: 端口点几何（px）：8×8 圆点，贴仪器卡缘（父缘坐标 x==父宽-4 或 -4）
PORT_SIZE = 8
_PORT_X_RIGHT = CARD_W - 4   # 右缘（相对父左上）
_PORT_X_LEFT = -4            # 左缘
_PORT_Y_FIRST = 8            # 缘上首端口 y（顶/底各留 8px 缘距）
_TITLE_Y = 20
_TITLE_W = 420
_TITLE_H = 26
_MARGIN_X = 40
_NOTE_GAP = 60               # 注记区起点=仪器区底+60（spec §3.6）
_NOTE_H = 26
_NOTE_STEP = 38              # 注记行步距（行高+间距）
_PAGE_BOTTOM_PAD = 40

_DEFAULT_TITLE = "测试连接图（声明式场景；损耗/长度=用户标注原值，零换算）"

#: 样式串（与 T-O1 同族；边=T-O1 _EDGE_STYLE 同串+fontSize 段）
_TITLE_STYLE = ("text;html=1;strokeColor=none;fillColor=none;align=left;"
                "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontStyle=1")
_NOTE_STYLE = ("text;html=1;strokeColor=none;fillColor=none;align=left;"
               "verticalAlign=top;whiteSpace=wrap;rounded=0;")
_PORT_STYLE = "ellipse;fillColor=#ffffff;strokeColor=#333333;html=1;fontSize=9;"
_EDGE_STYLE = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
               "jettySize=auto;html=1;fontSize=10;")
_CAL_LABEL_STYLE = ("text;html=1;fontStyle=1;fontColor=#b85450;align=left;"
                    "verticalAlign=middle;whiteSpace=wrap;rounded=0;")
_CAL_VALUE = "▎CAL"
_ANCHOR_EDGE_STYLE = ("edgeStyle=orthogonalEdgeStyle;dashed=1;endArrow=none;"
                      "strokeColor=#999999;html=1;")


def _card_style(fill: str, stroke: str) -> str:
    return f"rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"


# ─── 形状档（aurora_p A3 opt-in；缺省档=零形状名依赖，逐字节不变） ──────────

#: electrical 档：kind → draw.io 内置电气形状名（mxgraph.electrical.*）。
#: 实读核对表——证据=runs/aurora_p/a3_shapes/SHAPE_EVIDENCE.md（jgraph/
#: drawio dev 分支 Sidebar-Electrical.js 逐字行号落盘，Apache-2.0；#215
#: 纪律零想象命名）。部分 kind 无忠实 stencil（vna/specan/powermeter/
#: coupler/emi_receiver/load_simulator/current_probe——grep 负证据见证据
#: 笔记 §四）→ **如实不映射**（走缺省矩形卡），不凑专业形状。lisn→filter
#: 与 anchor_plane→signal_ground 为近似映射（无专名 stencil，语义最近者）。
ELECTRICAL_SHAPE_BY_KIND: dict[str, str] = {
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

#: scene.shapes 串值档注册表（档名 → kind→shape 映射；per-kind dict 覆盖
#: 形态不经本表，normalize 直校验）。缺省（无 shapes 键 / None / 空 dict）
#: =缺省档零形状名依赖。
SHAPE_PROFILES: dict[str, dict[str, str]] = {
    "electrical": ELECTRICAL_SHAPE_BY_KIND,
}


def _shape_card_style(shape: str, fill: str, stroke: str) -> str:
    """electrical 档仪器卡 style：官方公共前缀序（verticalLabelPosition=bottom;
    shadow=0;dashed=0;align=center;html=1;verticalAlign=top——
    Sidebar-Electrical.js L10 逐字）+ shape 名 + kind 色板（官方模板惯例
    fillColor=strokeColor 实心，本生成器有意偏离改用 kind 色板——保留 kind
    色语义）+ outlineConnect=0。"""
    return (f"verticalLabelPosition=bottom;shadow=0;dashed=0;align=center;"
            f"html=1;verticalAlign=top;shape={shape};fillColor={fill};"
            f"strokeColor={stroke};outlineConnect=0;")


#: warnings 文案（信封逐条可断言，spec §四.9 四类）
_WARN_NO_CONNECTIONS = "无连接：connections 为空，产出纯仪器清单图"
_WARN_EMPTY_PORTS = "仪器 {id!r} 无端口（纯辅助件，端口点未建）"
_WARN_COLUMN_CROSSING = (
    "列 {role} 有 {n} 台仪器（>2）：正交自动布线可能交叉，"
    "产出为原生可编辑文件，建议 draw.io 人工微调")
_WARN_ODD_DUT_PORTS = (
    "DUT 仪器 {id!r} 端口数 {n} 为奇数：中间端口已落右缘顶部，"
    "左右对半归属请人工核对")

#: 仪器 id 形态约束（端口点 id ``<inst>.<port>`` 依赖 id 不含 ``.``
#: ——spec §2.2：``[A-Za-z0-9_-]+``）
_INST_ID_RE = re.compile(r"[A-Za-z0-9_-]+")
#: 生成器保留 id 命名空间（conn<i>/note<i> 边与注记、title 标题、基 cell
#: 0/1——spec §3.7 id 形态总表；仪器 id 占用即 id 冲突，显式拒绝）
_RESERVED_ID_RE = re.compile(r"(?:conn|note)\d+")
_RESERVED_IDS = frozenset({"0", "1", "title"})


# ─── 标注数值文本单源（零换算） ─────────────────────────────────────────────


def format_quantity(value: Any) -> str:
    """标注数值 → 文本（格式化单源：XML 装配与测试断言消费同一函数）。

    分档：整数值（int 或 ``is_integer()`` 的 float）不带小数点（1.0→"1"）；
    非整数值=JSON 原值最短往返表示（0.5→"0.5"）——spec §3.5 示例锚
    ``value="RF1  0.5 dB  1 m"``。**零换算**：本函数不做任何单位/dB 运算
    （铁律 7：JSON 给什么写什么）。
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


# ─── schema 严格校验（normalize_chain 家法：严格键+枚举+负例显式） ──────────

_SCENE_KEYS = {"title", "instruments", "connections", "notes", "shapes"}
_INST_KEYS = {"id", "kind", "label", "role", "ports", "note"}
_INST_REQUIRED = ("id", "kind", "label", "ports")
_CONN_KEYS = {"from", "to", "cable", "cal_plane", "label"}
_CABLE_KEYS = {"label", "loss_db", "length_m"}
_NOTE_KEYS = {"text", "anchor"}


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


def normalize_scene(scene: Any) -> dict[str, Any]:
    """校验并归一声明式场景（非法入参显式 ValueError，不静默）。

    顶层五键（spec §2.1 四键 + aurora_p A3 opt-in 形状档键）::

        {"title": str 可省, "instruments": [<仪器卡>...] 必填非空,
         "connections": [<连接边>...] 允许空, "notes": [<注记>...] 允许空,
         "shapes": 档名 str 可省（"electrical"）或 per-kind dict 可省}

    ``shapes``（A3 opt-in，缺省/None=缺省档零形状名依赖逐字节同现状）：
    串值=查 :data:`SHAPE_PROFILES` 档注册表（"electrical"=实读核对的
    mxgraph.electrical.* 档）；dict=per-kind 形状名覆盖（键须在 kind 枚举
    内、值须非空字符串）。归一输出 ``shapes`` 键=kind→shape dict（缺省
    档=空 dict）。未映射的 kind 保持缺省矩形卡（负证据如实不凑形状——
    证据 runs/aurora_p/a3_shapes/SHAPE_EVIDENCE.md §四）。

    仪器卡严格六键 id/kind/label/role/ports/note（id/kind/label/ports
    必填；role 可省=kind 缺省查表；note 可省）。连接边严格五键
    from/to/cable/cal_plane/label（from/to 必填）。注记卡严格两键
    text/anchor（text 必填）。

    负例（均显式报错）：非 dict/缺 instruments/多余键/未知 kind（基础+
    CISPR 扩展枚举外）/未知 role/shapes 档名未知或 per-kind 形态违约/
    仪器 id 非 ``[A-Za-z0-9_-]+`` 或占用保留命名空间（0/1/title/conn<i>/
    note<i>）/仪器 id 重名/端口名空或含 ``.``/端口重名/引用不存在仪器/
    引用未声明端口/cable 缺 label/标注数值非有限实数/cal_plane 非 bool/
    anchor 解析失败。空 ports 列表合法（纯辅助件，进 warnings 不报错）。
    """
    if not isinstance(scene, dict):
        raise ValueError(f"scene 必须是 dict，收到 {type(scene)!r}")
    _check_no_extra(scene, _SCENE_KEYS, "scene",
                    "顶层 schema 严格五键 title/instruments/connections/"
                    "notes/shapes")
    title = None
    if scene.get("title") is not None:
        title = _check_str_nonempty(scene["title"], "scene.title")

    # shapes 形状档（A3 opt-in；None/缺省=缺省档——归一为空 dict）
    raw_shapes = scene.get("shapes")
    shape_map: dict[str, str] = {}
    if raw_shapes is not None:
        if isinstance(raw_shapes, str):
            if raw_shapes not in SHAPE_PROFILES:
                raise ValueError(
                    f"scene.shapes 未知形状档 {raw_shapes!r}；可选档 "
                    f"{sorted(SHAPE_PROFILES)}（或 per-kind dict 覆盖形态）")
            shape_map = dict(SHAPE_PROFILES[raw_shapes])
        elif isinstance(raw_shapes, dict):
            for sk, sv in raw_shapes.items():
                if sk not in EFFECTIVE_KIND_TABLE:
                    raise ValueError(
                        f"scene.shapes 键 {sk!r} 不是已知 kind；枚举仅 "
                        f"{sorted(EFFECTIVE_KIND_TABLE)}")
                if not isinstance(sv, str) or not sv.strip():
                    raise ValueError(
                        f"scene.shapes[{sk!r}] 必须是非空形状名字符串，"
                        f"收到 {sv!r}")
                shape_map[sk] = sv
        else:
            raise ValueError(
                f"scene.shapes 必须是档名字符串或 per-kind dict，收到 "
                f"{type(raw_shapes)!r}")

    raw_insts = scene.get("instruments")
    if not isinstance(raw_insts, (list, tuple)) or len(raw_insts) == 0:
        raise ValueError("scene.instruments 必须是非空仪器卡列表")
    instruments: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_insts):
        where = f"instruments[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} 必须是 dict，收到 {type(raw)!r}")
        _check_no_extra(raw, _INST_KEYS, where,
                        "仪器卡 schema 严格六键 id/kind/label/role/ports/note")
        for key in _INST_REQUIRED:
            if key not in raw or raw[key] is None:
                raise ValueError(f"{where} 缺必填键 {key!r}")
        inst_id = raw["id"]
        if not isinstance(inst_id, str) or not _INST_ID_RE.fullmatch(inst_id):
            raise ValueError(
                f"{where}.id 必须匹配 [A-Za-z0-9_-]+（端口点 id 形态"
                f" <inst>.<port> 依赖 id 不含 '.'），收到 {inst_id!r}")
        if inst_id in _RESERVED_IDS or _RESERVED_ID_RE.fullmatch(inst_id):
            raise ValueError(
                f"{where}.id {inst_id!r} 占用生成器保留 id 命名空间"
                "（0/1/title/conn<i>/note<i>），请改名")
        if inst_id in seen_ids:
            raise ValueError(f"{where}.id 仪器 id 重名：{inst_id!r}")
        seen_ids.add(inst_id)
        kind = raw["kind"]
        if kind not in EFFECTIVE_KIND_TABLE:
            raise ValueError(
                f"{where}.kind 未知 {kind!r}；枚举仅 "
                f"{sorted(EFFECTIVE_KIND_TABLE)}（不静默 generic）")
        label = _check_str_nonempty(raw["label"], f"{where}.label")
        role = raw.get("role")
        if role is None:
            role = EFFECTIVE_KIND_TABLE[kind][0]
        elif role not in ROLES:
            raise ValueError(
                f"{where}.role 未知 {role!r}；枚举仅 {list(ROLES)}")
        raw_ports = raw["ports"]
        if not isinstance(raw_ports, (list, tuple)):
            raise ValueError(f"{where}.ports 必须是字符串列表，收到 "
                             f"{type(raw_ports)!r}")
        ports: list[str] = []
        seen_ports: set[str] = set()
        for j, p in enumerate(raw_ports):
            if not isinstance(p, str) or not p.strip():
                raise ValueError(
                    f"{where}.ports[{j}] 必须是非空字符串，收到 {p!r}")
            if "." in p:
                raise ValueError(
                    f"{where}.ports[{j}] {p!r} 含 '.'（端口点 id 形态"
                    " <inst>.<port> 依赖端口名不含 '.'），请改名")
            if p in seen_ports:
                raise ValueError(f"{where}.ports[{j}] 端口名重名：{p!r}")
            seen_ports.add(p)
            ports.append(p)
        note = raw.get("note")
        if note is not None and not isinstance(note, str):
            raise ValueError(f"{where}.note 必须是字符串，收到 {type(note)!r}")
        instruments.append({
            "id": inst_id, "kind": kind, "label": label, "role": role,
            "ports": ports, "note": note,
        })

    inst_by_id = {inst["id"]: inst for inst in instruments}

    def _resolve_endpoint(value: Any, where: str) -> str:
        """``<inst_id>.<port>`` → 必须解析到已声明仪器的已声明端口（生命线）。"""
        ref = _check_str_nonempty(value, where)
        inst_id, sep, port = ref.partition(".")
        if not sep:
            raise ValueError(
                f"{where} {ref!r} 缺 '.' 分隔（形态 <inst_id>.<port>）")
        if inst_id not in inst_by_id:
            raise ValueError(
                f"{where} 引用不存在仪器：{inst_id!r}（已声明 "
                f"{sorted(inst_by_id)}）")
        if port not in inst_by_id[inst_id]["ports"]:
            raise ValueError(
                f"{where} 引用未声明端口：{ref!r}（仪器 {inst_id!r} 已声明 "
                f"端口 {inst_by_id[inst_id]['ports']}）")
        return ref

    raw_conns = scene.get("connections") or []
    if not isinstance(raw_conns, (list, tuple)):
        raise ValueError("scene.connections 必须是列表")
    connections: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_conns):
        where = f"connections[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} 必须是 dict，收到 {type(raw)!r}")
        _check_no_extra(raw, _CONN_KEYS, where,
                        "连接边 schema 严格五键 from/to/cable/cal_plane/label")
        for key in ("from", "to"):
            if key not in raw or raw[key] is None:
                raise ValueError(f"{where} 缺必填键 {key!r}")
        cable: dict[str, Any] | None = None
        raw_cable = raw.get("cable")
        if raw_cable is not None:
            if not isinstance(raw_cable, dict):
                raise ValueError(
                    f"{where}.cable 必须是 dict，收到 {type(raw_cable)!r}")
            _check_no_extra(raw_cable, _CABLE_KEYS, f"{where}.cable",
                            "cable schema 严格三键 label/loss_db/length_m")
            if "label" not in raw_cable or raw_cable["label"] is None:
                raise ValueError(f"{where}.cable 缺必填键 'label'（给了 cable "
                                 "则 label 必填）")
            cable = {"label": _check_str_nonempty(raw_cable["label"],
                                                  f"{where}.cable.label"),
                     "loss_db": None, "length_m": None}
            for key in ("loss_db", "length_m"):
                if raw_cable.get(key) is not None:
                    _finite(raw_cable[key], f"{where}.cable.{key}")
                    cable[key] = raw_cable[key]  # 原值保留（零换算标图）
        cal_plane = raw.get("cal_plane", False)
        if not isinstance(cal_plane, bool):
            raise ValueError(f"{where}.cal_plane 必须是 bool，收到 "
                             f"{cal_plane!r}")
        label = raw.get("label")
        if label is not None:
            label = _check_str_nonempty(label, f"{where}.label")
        connections.append({
            "from": _resolve_endpoint(raw["from"], f"{where}.from"),
            "to": _resolve_endpoint(raw["to"], f"{where}.to"),
            "cable": cable, "cal_plane": cal_plane, "label": label,
        })

    raw_notes = scene.get("notes") or []
    if not isinstance(raw_notes, (list, tuple)):
        raise ValueError("scene.notes 必须是列表")
    notes: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_notes):
        where = f"notes[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} 必须是 dict，收到 {type(raw)!r}")
        _check_no_extra(raw, _NOTE_KEYS, where,
                        "注记卡 schema 严格两键 text/anchor")
        text = _check_str_nonempty(raw.get("text"), f"{where}.text")
        anchor = raw.get("anchor")
        if anchor is not None:
            anchor = _check_str_nonempty(anchor, f"{where}.anchor")
            m = re.fullmatch(r"conn(\d+)", anchor)
            if anchor not in inst_by_id and not (
                    m and int(m.group(1)) < len(connections)):
                raise ValueError(
                    f"{where}.anchor 解析失败：{anchor!r}（须为已声明仪器 id "
                    f"或连接边序号 conn<0..{len(connections) - 1}>）")
        notes.append({"text": text, "anchor": anchor})

    return {"title": title, "instruments": instruments,
            "connections": connections, "notes": notes, "shapes": shape_map}


# ─── 布局（role→列分层；端口点缘位） ────────────────────────────────────────


def _column_layout(instruments: list[dict[str, Any]],
                   ) -> tuple[dict[str, tuple[int, float]],
                              dict[str, list[dict[str, Any]]]]:
    """仪器 → (列 x, 行 y)（px；spec §3.2：role 落列、同列 JSON 序自上而下、
    DUT 列垂直居中于全图行跨中位）。返回 (位置表, 按列分组表)。"""
    by_role: dict[str, list[dict[str, Any]]] = {r: [] for r in ROLES}
    for inst in instruments:  # JSON 出现序
        by_role[inst["role"]].append(inst)
    max_rows = max(len(v) for v in by_role.values())
    pos: dict[str, tuple[int, float]] = {}
    for role in ROLES:
        col = by_role[role]
        if not col:
            continue
        if role == "dut":
            # DUT 组垂直居中于全图行跨中位（DUT 通常是唯一且视觉中心）
            base = (max_rows - 1) / 2.0
            for j, inst in enumerate(col):
                row = base + j - (len(col) - 1) / 2.0
                pos[inst["id"]] = (ROLE_COLUMN_X[role], ROW_Y0 + row * ROW_STEP)
        else:
            for j, inst in enumerate(col):
                pos[inst["id"]] = (ROLE_COLUMN_X[role],
                                   ROW_Y0 + j * ROW_STEP)
    return pos, by_role


def _port_sides(inst: dict[str, Any]) -> list[str]:
    """端口声明序 → 每端口落缘（"left"/"right"；spec §3.2）。

    stim/inline 全右缘、anal/aux 全左缘；dut 按声明序对半分（左半=stim 侧、
    右半=anal 侧；奇数时中间端口即右半首位=右缘顶部，配 warnings 提示）。
    """
    role, n = inst["role"], len(inst["ports"])
    if role in ("stim", "inline"):
        return ["right"] * n
    if role in ("anal", "aux"):
        return ["left"] * n
    left = n // 2
    return ["left"] * left + ["right"] * (n - left)


def _edge_ys(n: int) -> list[int]:
    """单缘 n 个端口点的 y 序列（px，相对父顶；首/末各留 8px 缘距均布）。"""
    if n <= 1:
        return [(CARD_H - PORT_SIZE) // 2]
    first = _PORT_Y_FIRST
    last = CARD_H - _PORT_Y_FIRST - PORT_SIZE
    return [first + round(i * (last - first) / (n - 1)) for i in range(n)]


def _coord(v: float) -> int:
    """坐标数值收敛（行距/均布运算后恒为整值；float 中间量转 int 出干净文本）。"""
    out = float(v)
    if not out.is_integer():
        raise AssertionError(f"布局坐标出现非整值 {v!r}（内部错误）")
    return int(out)


# ─── 边标签（cable 拼接 + 自由标注；仅拼 JSON 原值，零换算） ────────────────


def cable_text(cable: dict[str, Any] | None) -> str:
    """线缆标注串：``<label>  <loss> dB  <length> m``（两空格分隔；可省段
    略去；数值经 :func:`format_quantity` 原值文本化，零换算）。"""
    if not cable:
        return ""
    parts = [cable["label"]]
    if cable.get("loss_db") is not None:
        parts.append(f"{format_quantity(cable['loss_db'])} dB")
    if cable.get("length_m") is not None:
        parts.append(f"{format_quantity(cable['length_m'])} m")
    return "  ".join(parts)


def edge_value(conn: dict[str, Any]) -> str:
    """连接边标签：cable 拼接串 + 自由标注（并存时拼接，先 cable 后自由）。"""
    parts = []
    ct = cable_text(conn["cable"])
    if ct:
        parts.append(ct)
    if conn["label"]:
        parts.append(conn["label"])
    return "  ".join(parts)


# ─── warnings（spec §四.9 四类，逐条可断言；固定顺序=确定性） ───────────────


def collect_warnings(norm: dict[str, Any]) -> list[str]:
    """归一场景 → warnings 列表（无连接/空端口/同列>2/DUT 奇数端口对半提示）。"""
    ws: list[str] = []
    if not norm["connections"]:
        ws.append(_WARN_NO_CONNECTIONS)
    for inst in norm["instruments"]:
        if not inst["ports"]:
            ws.append(_WARN_EMPTY_PORTS.format(id=inst["id"]))
    _, by_role = _column_layout(norm["instruments"])
    for role in ROLES:
        n = len(by_role[role])
        if n > 2:
            ws.append(_WARN_COLUMN_CROSSING.format(role=role, n=n))
    for inst in norm["instruments"]:
        if inst["role"] == "dut" and inst["ports"] and len(inst["ports"]) % 2 == 1:
            ws.append(_WARN_ODD_DUT_PORTS.format(id=inst["id"],
                                                 n=len(inst["ports"])))
    return ws


# ─── 装配（走 T-O2 内核；子 label cell 挂内核返回元素——许可扩展点） ─────────


def _attach_cal_marker(edge_cell: ET.Element, conn_id: str) -> None:
    """校准面标记：边子 label cell（drawio edge label 形态——relative 几何
    x=0 沿边中点 / y=-12 法向偏移 + offset 点；value="▎CAL" 红色加粗）。"""
    label = ET.SubElement(edge_cell, "mxCell", {
        "id": f"{conn_id}.cal", "value": _CAL_VALUE,
        "style": _CAL_LABEL_STYLE, "vertex": "1", "parent": conn_id,
        "connectable": "0"})
    geom = ET.SubElement(label, "mxGeometry", {
        "x": "0", "y": "-12", "relative": "1", "as": "geometry"})
    ET.SubElement(geom, "mxPoint", {"x": "0", "y": "-12", "as": "offset"})


def build_testsetup_plan(scene: Any, *, title: str | None = None) -> dict[str, Any]:
    """场景 → 装配计划（XML 文本 + 信封回显面；service 与内核测试同源）。

    Returns::

        {"xml": str（未压缩原生 mxfile，逐字节确定性）,
         "n_instruments"/"n_connections"/"n_notes": int,
         "instruments": [{id, kind, role, label, ports, note}, ...],
         "warnings": [str, ...]}

    Raises:
        ValueError: 场景 schema 违约（见 :func:`normalize_scene`）。
    """
    norm = normalize_scene(scene)
    warnings = collect_warnings(norm)
    pos, _ = _column_layout(norm["instruments"])

    # 页面尺寸按内容自适应（pageWidth 随最右列扩展；注记区随内容向下扩展）
    page_w = max(int(DEFAULT_PAGE_ATTRS["pageWidth"]),
                 max(x for x, _ in pos.values()) + CARD_W + _MARGIN_X)
    content_bottom = max(y + CARD_H for _, y in pos.values())
    notes_y0 = content_bottom + _NOTE_GAP
    notes_bottom = notes_y0 + len(norm["notes"]) * _NOTE_STEP
    page_h = max(int(DEFAULT_PAGE_ATTRS["pageHeight"]),
                 notes_bottom + _PAGE_BOTTOM_PAD)

    doc = new_document(diagram_id="testsetup-diagram",
                       diagram_name="Test Setup",
                       page=page_attrs(pageWidth=str(page_w),
                                       pageHeight=str(page_h)))

    # 标题（显式 title 参数 > 场景 title > 缺省标题）
    title_text = title or norm["title"] or _DEFAULT_TITLE
    doc.add_vertex("title", title_text, style=_TITLE_STYLE,
                   x=_MARGIN_X, y=_TITLE_Y, width=_TITLE_W, height=_TITLE_H)

    # 仪器卡（mxCell+属性=UserObject 等价形态）+ 端口点（子 cell，几何相对父）
    for inst in norm["instruments"]:
        extra: dict[str, Any] = {
            "kind": inst["kind"], "role": inst["role"],
            "ports": "|".join(inst["ports"]), "placeholders": "1"}
        if inst["note"]:
            extra["note"] = inst["note"]
        label_text = f"{inst['label']}\n{inst['kind']}"
        if inst["note"]:
            label_text += f"\n{inst['note']}"
        x, y = pos[inst["id"]]
        _, fill, stroke = EFFECTIVE_KIND_TABLE[inst["kind"]]
        shape = norm["shapes"].get(inst["kind"])
        style = (_shape_card_style(shape, fill, stroke) if shape
                 else _card_style(fill, stroke))
        doc.add_vertex(inst["id"], label_text,
                       style=style,
                       x=_coord(x), y=_coord(y), width=CARD_W, height=CARD_H,
                       extra_attrs=extra)
        sides = _port_sides(inst)
        side_seq = {"left": [p for p, s in zip(inst["ports"], sides, strict=True)
                             if s == "left"],
                    "right": [p for p, s in zip(inst["ports"], sides, strict=True)
                              if s == "right"]}
        ys = {"left": _edge_ys(len(side_seq["left"])),
              "right": _edge_ys(len(side_seq["right"]))}
        for side in ("left", "right"):
            px = _PORT_X_LEFT if side == "left" else _PORT_X_RIGHT
            for k, port in enumerate(side_seq[side]):
                doc.add_vertex(f"{inst['id']}.{port}", port, style=_PORT_STYLE,
                               x=px, y=ys[side][k], width=PORT_SIZE,
                               height=PORT_SIZE, parent=inst["id"])

    # 连接边（source/target=端口点 id；cal_plane 边挂 ▎CAL 子 label cell）
    for i, conn in enumerate(norm["connections"]):
        conn_id = f"conn{i}"
        cell = doc.add_edge(conn_id, edge_value(conn), style=_EDGE_STYLE,
                            source=conn["from"], target=conn["to"])
        if conn["cal_plane"]:
            _attach_cal_marker(cell, conn_id)

    # 注记（底部注记区 text cell；有锚另加虚线无箭头边）
    for i, nt in enumerate(norm["notes"]):
        note_id = f"note{i}"
        doc.add_vertex(note_id, f"N{i + 1}. {nt['text']}", style=_NOTE_STYLE,
                       x=_MARGIN_X, y=notes_y0 + i * _NOTE_STEP,
                       width=page_w - 2 * _MARGIN_X, height=_NOTE_H)
        if nt["anchor"]:
            doc.add_edge(f"note{i}.anchor", "", style=_ANCHOR_EDGE_STYLE,
                         source=note_id, target=nt["anchor"])

    return {
        "xml": doc.to_xml(),
        "n_instruments": len(norm["instruments"]),
        "n_connections": len(norm["connections"]),
        "n_notes": len(norm["notes"]),
        "instruments": [{k: inst[k] for k in
                         ("id", "kind", "role", "label", "ports", "note")}
                        for inst in norm["instruments"]],
        "warnings": warnings,
    }


def build_testsetup_diagram_xml(scene: Any, *, title: str | None = None) -> str:
    """场景 → 完整 .drawio XML 文本（未压缩原生 mxfile，逐字节确定性）。

    Args:
        scene: 声明式场景（schema 见 :func:`normalize_scene`）。
        title: 图标题文本（None 用场景 title，再 None 用缺省标题）。

    Raises:
        ValueError: 场景非法（端口引用完整性/严格键/枚举违约等，显式报错）。
    """
    return build_testsetup_plan(scene, title=title)["xml"]
