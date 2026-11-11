"""ODB++（目录形态）结构化解析内核（aurora_q 席位 Q-X68，2026-11-08）。

PCB 制造数据交换的主流格式 **ODB++Design**（Siemens EDA 公开规范 8.1
Update 3；KiCad/Altium/Valor 导出、CAM/制造消费）的**结构与统计面**
只读解析：matrix 层清单（块式 ``STEP {``/``LAYER {``）+ step 目录树
（stephdr/layers features 行分类统计/netlists cadnet 网表）+ symbols
符号清单 + eda/data 顶层计数 + net→pads 库存（悬空 pad/空 net 双清单，
宁多报不误报）+ matrix↔step 层对齐校验（缺失/多余层清单）。全部词法与
数值语义在 core 确定性内核（铁律 7：结构化数字只出自数据源文本本身）。
服务包装见 :mod:`rfauto.service.odbpp_service`（规则 4 JSON 进出），CLI
薄壳= cli/domains/odbpp.py 的 ``odbpp report`` 叶（ipc356/citi 同款独立
typer 根，合流挂账）。

**与本仓既有 ODB++ 面的增量边界（调研结论，2026-11-08 实测）**：既有
面有两处——① adapters/layout_interchange.py ``import_odbpp``（ODB++→
Layout **几何语义**展开：L/P/S 记录→LayoutPath/Circle/Polygon/Via）；
② service/format_overview_service.py ``_load_odbpp``（格式速览：仅
matrix 存在性探测+几何转发①）。本模块是**第三面**：不展开几何语义，
做目录树结构化（matrix/step/netlist/eda/symbols 五文件级解析）+制造
库存清单（net→pads/悬空/空 net）+层叠对齐校验——三面零函数重叠（①不
解析 netlist/eda/symbols、无 inventory/stack 概念；②仅存在性探测），
单一职责互补。真实 KiCad 10 导出样例（tests/fixtures/external/
kicad10_microwave_odb）只读消费。

公开规范口径锚点（odbplusplus.com 规范 8.1 Update 3 PDF，页码=该 PDF）：

- **目录树**（§File System p23）：matrix/matrix、steps/<step>/stephdr、
  steps/<step>/layers/<layer>/{features,attrlist,components,tools}、
  steps/<step>/netlists/cadnet/netlist、steps/<step>/eda/data、
  symbols/<symbol>/{features,attrlist}、misc/info；
- **matrix**（§matrix/matrix p64-71）：Structured Text 块式数组
  ``STEP {``/``LAYER {``，字段 ROW/COL/CONTEXT/TYPE/NAME/POLARITY/
  OLD_NAME/DIELECTRIC_TYPE 等；TYPE 枚举 12 值（SIGNAL/POWER_GROUND/
  DIELECTRIC/MIXED/SOLDER_MASK/SOLDER_PASTE/SILK_SCREEN/DRILL/ROUT/
  DOCUMENT/COMPONENT/MASK/CONDUCTIVE_PASTE——13 值含 MASK）；NAME
  大写（KiCad 实证）↔层目录小写映射（``name.lower()``）；"Each named
  layer MUST have a layer entity defined under the layers directory
  of each step"（p68）——stack 对齐校验的规范依据；ROW 唯一正整数、
  顺序不敏感可跳号（p67）——层叠序按 ROW 排序输出；
- **matrix 子集行格式**（layout_interchange.export_odbpp 仓内口径）：
  单行 ``<row> 0 <layer_name> <file_stem> SIGNAL`` 起头 MATRIX 行——
  双形态同读取器容忍（ipc356 356/356A 双形态家法）；
- **stephdr**（§p146-147）：Structured Text，UNITS 必需（KiCad 实测
  有 UNITS=MM；规范缺省链=misc/info UNITS→imperial）；
- **features**（§p172-189）：Line Record Text；``UNITS=MM|INCH`` 必需
  （缺省=产品模型 misc/info UNITS，仍缺=imperial，p175）；段结构
  ``#`` 注释行 / ``F <n>`` 特征计数（可选）/ ``$<idx> <symbol_name>
  [I|M]`` 符号表（尺寸单位=文件 UNITS 的千分位：INCH→mil、MM→µm，
  p38+175；KiCad 实证 r304.80→0.3048mm 直径）/ ``@<idx> <attr>``
  属性名表 / ``&<idx> <text>`` 属性文本表 / ``#Layer features`` 之后的
  特征记录区（p177：属性表必须位于特征区之前——段序守卫依据）；
  特征记录顶层 token：``L xs ys xe ye <sym> <pol> <dcode>[;attrs]``、
  ``P x y <apt_def> <pol> <dcode> <orient>[;attrs]``、
  ``A xs ys xe ye xc yc <sym> <pol> <dcode> <cw>``、
  ``T x y <font> <pol> <orient> ...``、``B ...`` 条码、
  ``S <pol> <dcode>`` 表面起始、``OB x y <type>``/``OS x y``/``OC xe ye
  xc yc cw``/``OE`` 多边形段、``SE`` 表面结束——本模块只做**行分类
  统计**（特征 token 计数/坐标行数/pad 引用计数/属性子组计数），不展开
  几何语义（几何面=layout_interchange ①的职责）；
- **cadnet/netlist**（§p138-144）：Line Record Text；头行
  ``H optimize <y|n> [staggered <y|n>]``（必须首行）；net 名段
  ``$<serial_num> <net_name>``（serial 从 0）；net 点段
  ``<net_num> <radius> <x> <y> <side> [<w> <h>] <epoint> <exp>
  [可选旗标/键值]``——side ∈ T/D/B/I（T=top、D=bottom、B=both、
  I=inner；旧式 ``I<n>`` 层号后缀已废弃但仍容忍），epoint ∈ e/m，
  exp ∈ e/c/p/s；``net_num=-1`` = tooling hole（如实登记）；w/h 仅
  radius=0 时存在；可选键值 by=/arsize_top=/arsize_bot=/is_shrink=/ld=。
  UNITS 必需但 **KiCad 10 实测导出无 UNITS 行**（fixture 实证）——
  fail-soft warning 如实登记不猜单位（同 gerber MO 缺失家法）；
- **eda/data**（§p111-120）：``HDR <source>`` EDA 系统来源、
  ``LYR <name...>`` 层名清单（FID 引用）、``NET <name>;`` 电气 net
  记录、``SNT TOP|VIA|TRC|PLN ...`` 子网（TOP 带 side T|B +
  comp_num + toep_num）、``FID <type C|L|H> <lyr_num> <f_num>``、
  ``PKG <name> <pitch> <bbox>`` 包封装、``PIN <num> <S|P> <x> <y>
  <rot> <epoint> <pol>`` 引脚、``PRP <name> '<value>' [nums]`` 属性、
  ``@``/``&`` 属性查找表——本模块只做记录 token 计数与 NET/SNT/PIN
  顶层结构化（包几何 outline 不展开）；
- **components**（§p155-162）：``CMP <pkg_ref> <x> <y> <rot> <mirror>
  <comp_name> <part_name>[;attrs]``、``PRP <name> '<value>'``、
  ``TOP <pin_num> <x> <y> <rot> <mirror> <net_num> <subnet_num>
  <toeprint_name>``、BOM 记录（CPN/MPN/VND/QLF/CHS/PRIORITY/LNFILE/
  VPL_MPN/VPL_VND）；net_num 序=eda/data NET 序（p160）——元件引脚
  net 关联经该序解析；
- **symbols/**（§p96-97）：用户符号目录（attrlist+features）；标准
  符号动态渲染**零文件**（p37），名字形态 ``<prefix><params>``
  （r<d>/s<s>/rect<w>x<h>/oval<w>x<h>/di/oct/donut_*/hex_*/thr/ths/
  bfr/bfs/tri/el/moire/hole/hplate/rhplate/fhplate/radhplate/dshape/
  cross/dogbone/dpack/null…，附录 A），参数尺寸单位=文件 UNITS 的
  千分位（mil/µm，p38）——symbol_params 单位换算钉：MM 文件 612.14µm
  =0.61214mm（KiCad fixture 实证）；INCH 文件 120mil=0.120in=3.048mm；
  用户符号目录名（symbols/ 子目录）与标准符号名共用 `_STANDARD_SYMBOL_`
  前缀集判别；
- **misc/info**（§p79）：JOB_NAME/UNITS/ODB_VERSION_*/ODB_SOURCE/
  SAVE_APP 等 key=value——产品模型缺省单位单源。

**结构化输出 schema**（PARSER_SCHEMA_VERSION="1.0"；键集变更升位；
自描述键=``"schema": "odbpp/<N.0>"`` 复合键——R-22 schema 升位批统一口径）：

- :func:`parse_odb_matrix`（文本入参，零 IO）→ ``{"schema",
  "kind": "steps"(块式)|"subset"(行式), "steps": [...], "layers":
  [{"name","type","context","row","polarity","old_name",...}],
  "layer_dir_map": {小写目录名: NAME}, "raw_unit", "warnings"}``——
  大写 NAME↔小写目录映射表=layer_dir_map（KiCad 口径：matrix NAME
  大写、目录名=NAME.lower()，本仓 AGENTS 速查同口径）；
- :func:`parse_odb_stephdr`（文本）→ ``{"units", "fields", "warnings"}``；
- :func:`parse_odb_info`（文本）→ ``{"fields", "units", "job_name", ...}``；
- :func:`parse_odb_symbol_table`（features 文本符号段）→
  ``{"symbols": [{"index","name","unit_hint","shape","params","width_mm",
  "height_mm"}], "warnings"}``——$ 表解析 + 尺寸 µm/mil→mm 精确换算
  （Fraction；无法解析如实 None 不猜）；
- :func:`parse_odb_features`（文本）→ ``{"units", "declared_count",
  "symbols", "attr_names", "attr_texts", "records": {...token 计数},
  "coordinate_rows", "pad_refs", "attr_assigns", "before_features",
  "warnings"}``——行分类统计口径（见上）；
- :func:`parse_odb_cadnet`（文本）→ ``{"schema", "header":
  {"optimize","staggered"}, "units", "nets": [名按 serial 序],
  "net_points": [{"net","net_num","radius","x","y","side","w","h",
  "epoint","exp","flags":[...],"params":{...}}], "stats": {"n_nets",
  "n_points", ...}, "warnings"}``；
- :func:`parse_odb_eda_data`（文本）→ ``{"hdr", "layers": [...],
  "nets": [{"name","subnets":[...]}], "packages": [...],
  "stats": {...}, "warnings"}``——NET/SNT TOP/PIN 顶层结构化；
- :func:`parse_odb_components`（文本）→ ``{"components": [{"pkg_ref",
  "x","y","rotation","mirrored","comp_name","part_name","pins":
  [{"pin_num","net_num","toeprint"}], "properties": {...}, "bom":
  {...}}], "stats": {...}, "warnings"}``；
- :func:`parse_odb_dir`（**目录入参，唯二 IO 面**）→ 全树文档（见函数
  docstring）；
- :func:`odbpp_net_inventory`（step 文档入参）→ net→pads 映射 +
  悬空 pad（features P 记录无 net 归属）+ 空 net（cadnet/eda 有名无点
  或零 pin）双清单——**宁多报不误报**：判定缺证据即入清单；
- :func:`odbpp_layer_stack_summary`（matrix 文档+step 层目录名单）→
  对齐校验（缺失/多余层清单+对齐布尔）。

fail-soft 口径（ipc356/excellon 家法）：未知指令行/未知记录 token →
warning + 跳行（逐条披露不改据）；单位缺失 → 如实 None + warning；
目录级错误（根不存在/缺 matrix）→ :class:`OdbppParseError`（服务层转
error 信封）。空目录树面（step 无层目录等）不判错——结构与统计面如实
零计数。

确定性（同输入同输出）、除 :func:`parse_odb_dir` 外零 IO、零第三方
依赖。本模块不设 ``__all__``（无 __all__ 文件不进 tests/gold/
public_api.json——ipc356_parser 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import logging
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: matrix LAYER TYPE 枚举（公开规范 p67-68 全集；13 值）。
LAYER_TYPES = (
    "SIGNAL",
    "POWER_GROUND",
    "DIELECTRIC",
    "MIXED",
    "SOLDER_MASK",
    "SOLDER_PASTE",
    "SILK_SCREEN",
    "DRILL",
    "ROUT",
    "DOCUMENT",
    "COMPONENT",
    "MASK",
    "CONDUCTIVE_PASTE",
)

#: matrix LAYER CONTEXT 枚举（规范 p67）。
LAYER_CONTEXTS = ("BOARD", "MISC")

#: cadnet net 点 side 枚举（规范 p140-141；T=top D=down B=both I=inner）。
NET_SIDES = ("T", "D", "B", "I")

#: cadnet net 点 epoint 枚举（规范 p141：e=end m=mid）。
NET_EPOINTS = ("e", "m")

#: cadnet net 点 exp 枚举（规范 p141：e=exposed c=covered p=top covered
#: s=bottom covered）。
NET_EXPS = ("e", "c", "p", "s")

#: cadnet 净点可选布尔旗标（规范 p141-142；出现即真）。
NET_FLAGS = ("c", "v", "f", "t", "m", "x", "e")

#: cadnet 净点可选键值参数（规范 p142-143）。
NET_PARAM_KEYS = ("by", "arsize_top", "arsize_bot", "is_shrink", "ld")

#: cadnet 净点可选 staggered 子组前缀。
_NET_STAGGERED_KEYS = ("sx", "sy", "sr")

#: FID 记录 type 枚举（规范 p118：C=copper L=laminate H=hole）。
FID_TYPES = ("C", "L", "H")

#: SNT 子网形态枚举（规范 p117）。
SNT_KINDS = ("TOP", "VIA", "TRC", "PLN")

#: BOM 描述记录关键字（规范 p160-162 已见全集）。
BOM_KEYWORDS = (
    "CPN", "MPN", "VND", "QLF", "CHS", "PRIORITY", "LNFILE",
    "VPL_MPN", "VPL_VND",
)

#: 附录 A 标准符号名前缀（标准符号动态渲染零文件、名字形态
#: ``<prefix><params>``；用户符号不得使用这些前缀）。null=占位符。
STANDARD_SYMBOL_PREFIXES = (
    "r", "s", "rect", "oval", "di", "oct", "donut_r", "donut_s",
    "donut_sr", "donut_rc", "donut_o", "hex_l", "hex_s", "bfr", "bfs",
    "tri", "oval_h", "thr", "ths", "s_ths", "s_tho", "s_thr", "sr_ths",
    "rc_ths", "rc_tho", "o_ths", "oblong_ths", "hplate", "rhplate",
    "fhplate", "radhplate", "dshape", "cross", "dogbone", "dpack",
    "el", "moire", "hole", "null", "ext",
)

#: 标准符号长前缀优先匹配表（避免 rect 先于 rect... 被截断成 r 前缀；
#: 按长度降序）。
_SYMBOL_PREFIXES_BY_LEN = tuple(
    sorted(STANDARD_SYMBOL_PREFIXES, key=len, reverse=True))

#: 符号名形态：``<prefix><数字/数字x数字...>``（参数=十进制数，``x`` 分隔，
#: 可带 xr<rad>/xc<rad>/x<corners> 等尾参；规范 p37）。首参可缺
#: （零参符号形态容忍，如占位符族——尺寸如实 None）。
_SYMBOL_NAME_RE = re.compile(
    r"^(?P<prefix>[a-z][a-z_]*)(?P<params>(?:\d+(?:\.\d+)?|r\d+(?:\.\d+)?"
    r"|c\d+(?:\.\d+)?)?(?:x(?:\d+(?:\.\d+)?|r\d+(?:\.\d+)?"
    r"|c\d+(?:\.\d+)?))*)$"
)

#: 符号名参数 token（数字/r 数字/c 数字——圆角/倒角尾参）。
_SYMBOL_PARAM_RE = re.compile(r"[rc]?\d+(?:\.\d+)?")

#: $ 符号表行：``$<idx> <name> [I|M]``（规范 p176）。
_SYMBOL_LINE_RE = re.compile(r"^\$(\d+)\s+(\S+)(?:\s+([IM]))?\s*$")

#: 结构化文本 key=value 行（matrix 块内/stephdr/misc/info/attrlist）；
#: 属性键允许前导点（系统属性 .layer_dielectric 等，规范 p96 attrlist）。
_KV_LINE_RE = re.compile(r"^(\.?[A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.*)$")

#: 块式 matrix 块头：``STEP {`` / ``LAYER {``（规范 p64-66）。
_MATRIX_BLOCK_RE = re.compile(r"^(STEP|LAYER)\s*\{\s*$")

#: 未知词容忍上沿（防病态输入把 warnings 撑爆；超限只计数）。
_MAX_WARNINGS = 200


class OdbppParseError(ValueError):
    """ODB++ 目录级错误（根不存在/缺 matrix——区别于文件内逐条 fail-soft）。"""


def _warn(warnings: list[str], message: str) -> None:
    """warning 同文去重追加（逐条披露不改据；ipc356 家法）。"""
    if message not in warnings and len(warnings) < _MAX_WARNINGS:
        warnings.append(message)


def _sym_size_to_mm(
    params: list[Fraction], unit_hint: str | None
) -> tuple[float | None, float | None]:
    """符号参数尺寸 → (宽mm, 高mm)。

    口径（规范 p38+175+附录 A）：符号名数字参数单位=文件 UNITS 的
    千分位（INCH→mil、MM→µm；``I``/``M`` 后缀逐符号显式覆盖）。圆形
    族（r/bfr/bfs）参数=直径（仓内 AGENTS 速查：r304.80→0.3048mm 板内
    描边线宽）；rect/oval 参数=<w>x<h>。
    """
    if not params or unit_hint not in ("I", "M"):
        return None, None
    if unit_hint == "M":  # µm → mm
        w = params[0] / 1000
        h = (params[1] if len(params) > 1 else params[0]) / 1000
    else:  # mil → inch → mm
        w = params[0] * Fraction(254, 10000)
        h = (params[1] if len(params) > 1 else params[0]) * Fraction(254, 10000)
    return round(float(w), 9), round(float(h), 9)


def classify_symbol_name(name: str, unit_hint: str | None = None) -> dict[str, Any]:
    """标准符号名 → 形状/参数/尺寸（结构化面；几何渲染不展开）。

    Returns:
        ``{"shape", "params": [Fraction...], "unit_hint", "width_mm",
        "height_mm", "standard"}``——非标准/不可解析名如实
        ``standard=False``、params=[]、尺寸 None（不猜）。
    """
    out: dict[str, Any] = {
        "shape": None,
        "params": [],
        "unit_hint": unit_hint,
        "width_mm": None,
        "height_mm": None,
        "standard": False,
    }
    matched = _SYMBOL_NAME_RE.match(name)
    if matched is None:
        return out
    prefix = matched.group("prefix")
    if prefix not in _SYMBOL_PREFIXES_BY_LEN:
        return out
    params = [
        Fraction(tok) for tok in _SYMBOL_PARAM_RE.findall(matched.group("params"))
    ]
    out["standard"] = True
    out["params"] = params
    shape_map = {
        "r": "round", "bfr": "round", "bfs": "square", "s": "square",
        "rect": "rectangle", "oval": "oval", "di": "diamond",
        "oct": "octagon", "tri": "triangle", "el": "ellipse",
        "oval_h": "oval", "hole": "hole", "null": "null", "ext": "null",
        "donut_r": "round_donut", "donut_s": "square_donut",
        "donut_sr": "square_donut", "donut_rc": "rect_donut",
        "donut_o": "oval_donut",
    }
    out["shape"] = shape_map.get(prefix, prefix)  # 热片/板形/异形族：prefix 原样登记
    out["width_mm"], out["height_mm"] = _sym_size_to_mm(params, unit_hint)
    return out


# ---------------------------------------------------------------------------
# 结构化文本（matrix / stephdr / misc/info / attrlist 同源读取器）
# ---------------------------------------------------------------------------


def _parse_structured(text: str) -> tuple[dict[str, str], list[dict[str, str]], list[str]]:
    """Structured Text 通用读取器：顶层 key=value + 块式数组。

    Returns:
        ``(fields, blocks, warnings)``——blocks=块数组元素
        ``{"_kind": "STEP"|"LAYER"|..., 字段...}``（``_kind`` 为保留键，
        与字段名冲突面为零——规范字段全大写）。
    """
    fields: dict[str, str] = {}
    blocks: list[dict[str, str]] = []
    warnings: list[str] = []
    kind: str | None = None
    current: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        bm = _MATRIX_BLOCK_RE.match(line)
        if bm:
            kind = bm.group(1)
            current = {"_kind": kind}
            blocks.append(current)
            continue
        if line == "}":
            kind = None
            current = {}
            continue
        if kind is not None:
            kv = _KV_LINE_RE.match(line)
            if kv:
                current[kv.group(1)] = kv.group(2).strip()
                continue
            _warn(warnings, f"第 {lineno} 行块内未识别语句 {line[:40]!r}，跳过")
            continue
        kv = _KV_LINE_RE.match(line)
        if kv:
            fields[kv.group(1)] = kv.group(2).strip()
            continue
        _warn(warnings, f"第 {lineno} 行未识别语句 {line[:40]!r}，跳过")
    return fields, blocks, warnings


def parse_odb_matrix(text: str) -> dict[str, Any]:
    """matrix 文本 → 结构化层清单（块式与子集行式双形态同读取器）。

    块式（KiCad 10 原生导出/规范 p64-66）：``STEP {``/``LAYER {`` 块，
    NAME 大写 ↔ 目录小写映射 ``layer_dir_map``（name.lower()——本仓
    AGENTS 速查：块式 matrix NAME 大写↔层目录小写）。
    子集行式（layout_interchange.export_odbpp 仓内子集口径）：
    ``MATRIX`` 起头 + 行 ``<row> 0 <layer_name> <file_stem> SIGNAL``。

    Returns:
        ``{"schema", "kind": "steps"|"subset", "steps",
        "layers", "layer_dir_map", "raw_unit", "warnings"}``——layers
        按 ROW 升序（缺 ROW 的行式条目按出现序；ROW 非整数如实保留
        原值排序键置末）。
    """
    warnings: list[str] = []
    fields, blocks, st_warnings = _parse_structured(text)
    warnings.extend(st_warnings)

    if blocks:
        steps: list[str] = []
        layers: list[dict[str, Any]] = []
        layer_dir_map: dict[str, str] = {}
        for block in blocks:
            name = block.get("NAME", "").strip()
            if block.get("_kind") == "STEP":
                if name:
                    steps.append(name)
                continue
            if not name:
                _warn(warnings, "matrix LAYER 块缺 NAME，跳过")
                continue
            row_raw = block.get("ROW", "").strip()
            try:
                row: int | None = int(row_raw)
            except ValueError:
                row = None
                if row_raw:
                    _warn(warnings, f"matrix 层 {name!r} ROW 非整数"
                                    f" {row_raw!r}，排序键置末")
            entry: dict[str, Any] = {
                "name": name,
                "type": block.get("TYPE", "").strip() or None,
                "context": block.get("CONTEXT", "").strip() or None,
                "row": row,
                "polarity": block.get("POLARITY", "").strip() or None,
                "old_name": block.get("OLD_NAME", "").strip() or None,
                "dielectric_type": block.get("DIELECTRIC_TYPE", "").strip() or None,
                "add_type": block.get("ADD_TYPE", "").strip() or None,
                "start_name": block.get("START_NAME", "").strip() or None,
                "end_name": block.get("END_NAME", "").strip() or None,
            }
            layers.append(entry)
            layer_dir_map[name.lower()] = name
        layers.sort(key=lambda e: (e["row"] is None, e["row"] or 0))
        return {
            "schema": f"odbpp/{PARSER_SCHEMA_VERSION}",
            "kind": "steps",
            "steps": steps,
            "layers": layers,
            "layer_dir_map": layer_dir_map,
            "raw_unit": fields.get("UNITS"),
            "warnings": warnings,
        }

    # ── 子集行式（仓内 layout_interchange.export_odbpp 口径）──────────
    subset_layers: list[dict[str, Any]] = []
    subset_map: dict[str, str] = {}
    subset_steps: list[str] = []
    saw_matrix_line = False
    saw_layer_row = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line == "MATRIX":
            if line == "MATRIX":
                saw_matrix_line = True
            continue
        if line.startswith("UNITS="):
            continue
        parts = line.split()
        if len(parts) >= 4 and parts[1] == "0":
            layer_name = parts[2]
            file_stem = parts[3]
            ltype = parts[4] if len(parts) >= 5 else None
            subset_layers.append({
                "name": layer_name,
                "type": ltype,
                "context": None,
                "row": None,
                "polarity": None,
                "old_name": None,
                "dielectric_type": None,
                "add_type": None,
                "start_name": None,
                "end_name": None,
            })
            subset_map[file_stem] = layer_name
            saw_layer_row = True
            continue
        _warn(warnings, f"第 {lineno} 行未识别语句 {line[:40]!r}，跳过")
    kind = "subset" if saw_layer_row or saw_matrix_line else None
    if kind is None:
        _warn(warnings, "matrix 无 STEP/LAYER 块也无子集行，结构如实为空")
        kind = "steps"  # 空文档按块式空集回报告警已含
    return {
        "schema": f"odbpp/{PARSER_SCHEMA_VERSION}",
        "kind": kind,
        "steps": subset_steps,
        "layers": subset_layers,
        "layer_dir_map": subset_map,
        "raw_unit": fields.get("UNITS"),
        "warnings": warnings,
    }


def parse_odb_stephdr(text: str) -> dict[str, Any]:
    """stephdr 文本 → 结构化字段（UNITS 必需性如实：缺=units None+warning）。"""
    fields, _blocks, warnings = _parse_structured(text)
    units = fields.get("UNITS")
    if units is None:
        _warn(warnings, "stephdr 无 UNITS 指令（规范必需；缺省链=misc/info"
                        " UNITS，仍缺=imperial 不猜）")
    return {"units": units, "fields": fields, "warnings": warnings}


def parse_odb_info(text: str) -> dict[str, Any]:
    """misc/info 文本 → 结构化字段（产品模型缺省单位/来源/版本单源）。"""
    fields, _blocks, warnings = _parse_structured(text)
    return {
        "fields": fields,
        "units": fields.get("UNITS"),
        "job_name": fields.get("JOB_NAME"),
        "odb_source": fields.get("ODB_SOURCE"),
        "save_app": fields.get("SAVE_APP"),
        "odb_version": ".".join(
            v for v in (fields.get("ODB_VERSION_MAJOR"),
                        fields.get("ODB_VERSION_MINOR")) if v),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# features 文件（行分类统计；几何语义不展开）
# ---------------------------------------------------------------------------


def parse_odb_symbol_table(text: str) -> dict[str, Any]:
    """features 文本 $ 符号段 → 符号清单（含标准符号参数/尺寸换算面）。

    单位缺省链（规范 p38+p175）：符号名尺寸数字单位=文件 UNITS 的千分
    位（MM→µm、INCH→mil），行尾显式 ``I``/``M`` 后缀逐符号覆盖；KiCad
    10 实测导出无后缀（fixture 实证）→ 按文件 UNITS 换算。文件无
    UNITS 行 → effective_unit_hint=None，尺寸如实 None 不猜。
    """
    warnings: list[str] = []
    file_units: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("UNITS="):
            file_units = line[len("UNITS="):].strip().upper() or None
            break
    default_hint = {"MM": "M", "INCH": "I"}.get(file_units)
    symbols: list[dict[str, Any]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line.startswith("$"):
            continue
        sm = _SYMBOL_LINE_RE.match(line)
        if sm is None:
            _warn(warnings, f"第 {lineno} 行 $ 符号行形态异常 {line[:40]!r}，跳过")
            continue
        idx, name, unit_hint = sm.group(1), sm.group(2), sm.group(3)
        effective_hint = unit_hint or default_hint
        info = classify_symbol_name(name, effective_hint)
        symbols.append({
            "index": int(idx),
            "name": name,
            "unit_hint": unit_hint,
            "effective_unit_hint": effective_hint,
            "shape": info["shape"],
            "params": info["params"],
            "width_mm": info["width_mm"],
            "height_mm": info["height_mm"],
            "standard": info["standard"],
        })
    return {"symbols": symbols, "warnings": warnings}


def parse_odb_features(text: str) -> dict[str, Any]:
    """features 文本 → 行分类统计（不展开几何语义）。

    段结构（规范 p172-189）：UNITS / ID / F 计数 / $ 符号表 / @ 属性名表
    / & 属性文本表 / ``#Layer features`` 之后的特征记录区。特征区记录
    token 顶层分类：L/P/A/T/B/S/OB/OS/OC/OE/SE；``;`` 后属性子组按
    ``n=v`` 计数（attr_assigns）。

    Returns:
        ``{"units", "declared_count", "symbols", "attr_names",
        "attr_texts", "records": {...}, "coordinate_rows", "pad_refs",
        "attr_assigns", "before_features", "warnings"}``。
    """
    warnings: list[str] = []
    units: str | None = None
    declared_count: int | None = None
    attr_names: dict[str, str] = {}
    attr_texts: dict[str, str] = {}
    records: dict[str, int] = {}
    coordinate_rows = 0
    pad_refs = 0
    attr_assigns = 0
    before_features = 0
    in_features = False

    sym_table = parse_odb_symbol_table(text)
    warnings.extend(sym_table["warnings"])

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            if line == "#Layer features":
                in_features = True
            continue
        if line.startswith("UNITS="):
            units = line[len("UNITS="):].strip().upper() or None
            if units not in ("MM", "INCH"):
                _warn(warnings,
                      f"第 {lineno} 行 UNITS={units!r} 非规范枚举（MM/INCH），"
                      "如实登记不猜")
            continue
        if line.startswith("ID="):
            continue
        if line.startswith("F "):
            try:
                declared_count = int(line[2:].strip())
            except ValueError:
                _warn(warnings,
                      f"第 {lineno} 行 F 计数非整数 {line[:20]!r}，如实 None")
            continue
        if line.startswith("$"):
            continue  # 符号段已由 parse_odb_symbol_table 消费
        if line.startswith("@") or line.startswith("&"):
            parts = line.split(None, 1)
            table = attr_names if line.startswith("@") else attr_texts
            if len(parts) == 2:
                table[parts[0][1:]] = parts[1].strip()
            else:
                _warn(warnings,
                      f"第 {lineno} 行属性表行形态异常 {line[:40]!r}，跳过")
            continue
        if not in_features:
            before_features += 1
            _warn(warnings,
                  f"第 {lineno} 行特征区前未识别语句 {line[:40]!r}，跳过")
            continue
        head = line.split(";")[0].split()
        if not head:
            continue
        token = head[0]
        records[token] = records.get(token, 0) + 1
        attrs = line.split(";", 1)
        if len(attrs) == 2 and attrs[1].strip():
            attr_assigns += len(
                [a for a in attrs[1].split(",") if a.strip()])
        if token in ("L", "P", "A", "OB", "OS", "OC", "T"):
            coordinate_rows += 1
        if token == "P":
            pad_refs += 1
        if token not in ("L", "P", "A", "T", "B", "S", "OB", "OS", "OC",
                         "OE", "SE"):
            _warn(warnings,
                  f"第 {lineno} 行未知特征记录 token {token!r}，跳行计数")
    return {
        "units": units,
        "declared_count": declared_count,
        "symbols": sym_table["symbols"],
        "attr_names": attr_names,
        "attr_texts": attr_texts,
        "records": records,
        "coordinate_rows": coordinate_rows,
        "pad_refs": pad_refs,
        "attr_assigns": attr_assigns,
        "before_features": before_features,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# cadnet/netlist
# ---------------------------------------------------------------------------


def parse_odb_cadnet(text: str) -> dict[str, Any]:
    """cadnet/netlist 文本 → 结构化网表（头行/net 名段/net 点段）。

    点行形态（规范 p139-143）：``<net_num> <radius> <x> <y> <side>
    [<w> <h>] <epoint> <exp> [flags...] [staggered sx sy sr] [k=v...]``。
    ``net_num=-1`` = tooling hole（如实登记 net None）。
    """
    warnings: list[str] = []
    header: dict[str, str | None] = {"optimize": None, "staggered": None}
    nets_by_serial: dict[int, str] = {}
    net_order: list[str] = []
    points: list[dict[str, Any]] = []
    units: str | None = None
    saw_header = False

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("UNITS="):
            units = line[len("UNITS="):].strip().upper() or None
            continue
        if not saw_header and line.startswith("H "):
            saw_header = True
            toks = line.split()[1:]
            for key in ("optimize", "staggered"):
                if key in toks:
                    i = toks.index(key)
                    if i + 1 < len(toks):
                        header[key] = toks[i + 1]
            continue
        if line.startswith("$"):
            parts = line.split(None, 1)
            try:
                serial = int(parts[0][1:])
            except (ValueError, IndexError):
                _warn(warnings,
                      f"第 {lineno} 行 net 名行形态异常 {line[:40]!r}，跳过")
                continue
            name = parts[1].strip() if len(parts) > 1 else ""
            if not name:
                _warn(warnings, f"第 {lineno} 行 net serial {serial} 缺名，跳过")
                continue
            nets_by_serial[serial] = name
            net_order.append(name)
            continue
        toks = line.split()
        # 点行判定：首 token 为整数（net_num；含 -1 tooling hole）
        try:
            net_num = int(toks[0])
        except ValueError:
            _warn(warnings,
                  f"第 {lineno} 行未识别语句 {line[:40]!r}，跳过")
            continue
        if not saw_header:
            _warn(warnings, "点行先于 H 头行出现（规范要求首行=头行），如实登记")
        radius = _frac_or_none(toks[1]) if len(toks) > 1 else None
        x = _frac_or_none(toks[2]) if len(toks) > 2 else None
        y = _frac_or_none(toks[3]) if len(toks) > 3 else None
        idx = 4
        side: str | None = None
        w: Fraction | None = None
        h: Fraction | None = None
        if len(toks) > idx:
            cand = toks[idx].upper()
            base = cand[0]
            if base in NET_SIDES:
                side = base
                if len(cand) > 1 and cand[1:].isdigit():
                    _warn(warnings,
                          f"第 {lineno} 行 side 旧式层号后缀 {toks[idx]!r}"
                          f"（规范已废弃），按 {base} 语义登记")
                idx += 1
        # w/h（仅 radius=0 的非钻孔 pad 存在；规范 p140）
        if len(toks) > idx and radius == 0:
            w = _frac_or_none(toks[idx])
            if w is not None:
                idx += 1
                if len(toks) > idx:
                    h = _frac_or_none(toks[idx])
                    if h is not None:
                        idx += 1
        epoint: str | None = None
        exp: str | None = None
        if len(toks) > idx and toks[idx] in NET_EPOINTS:
            epoint = toks[idx]
            idx += 1
        if len(toks) > idx and toks[idx] in NET_EXPS:
            exp = toks[idx]
            idx += 1
        flags: list[str] = []
        params: dict[str, str] = {}
        staggered: list[Fraction | None] | None = None
        rest = toks[idx:]
        i = 0
        while i < len(rest):
            tok = rest[i]
            if "=" in tok:
                key, _, val = tok.partition("=")
                if key == "staggered":
                    # 规范 p139-140：staggered 亦可作键值形态（sx sy sr 跟随）
                    staggered = [_frac_or_none(v) for v in rest[i + 1:i + 4]]
                    i += 1
                    continue
                if key in NET_PARAM_KEYS or key in _NET_STAGGERED_KEYS:
                    params[key] = val
                else:
                    _warn(warnings,
                          f"第 {lineno} 行未知键值参数 {tok!r}，如实登记")
                    params[key] = val
                i += 1
                continue
            if tok == "staggered":
                staggered = [_frac_or_none(v) for v in rest[i + 1:i + 4]]
                i += 4
                continue
            if tok in NET_FLAGS:
                flags.append(tok)
                i += 1
                continue
            _warn(warnings, f"第 {lineno} 行未知旗标 token {tok!r}，跳过")
            i += 1
        net_name = nets_by_serial.get(net_num) if net_num >= 0 else None
        if net_num >= 0 and net_name is None:
            _warn(warnings,
                  f"第 {lineno} 行点引用未定义 net_num {net_num}，net 如实 None")
        points.append({
            "line": lineno,
            "net": net_name,
            "net_num": net_num,
            "tooling_hole": net_num == -1,
            "radius": float(radius) if radius is not None else None,
            "x": float(x) if x is not None else None,
            "y": float(y) if y is not None else None,
            "side": side,
            "w": float(w) if w is not None else None,
            "h": float(h) if h is not None else None,
            "epoint": epoint,
            "exp": exp,
            "flags": flags,
            "staggered": ([float(v) if v is not None else None
                           for v in staggered] if staggered else None),
            "params": params,
        })

    if units is None and points:
        _warn(warnings,
              "cadnet 无 UNITS 指令（规范必需；KiCad 10 实测导出亦缺），"
              "坐标单位如实 None 不猜")
    n_test_points = sum(1 for p in points if "t" in p["flags"])
    n_vias = sum(1 for p in points if "v" in p["flags"])
    n_tooling = sum(1 for p in points if p["tooling_hole"])
    sides_hist: dict[str, int] = {}
    for p in points:
        if p["side"]:
            sides_hist[p["side"]] = sides_hist.get(p["side"], 0) + 1
    stats = {
        "n_nets": len(net_order),
        "n_points": len(points),
        "n_test_points": n_test_points,
        "n_via_points": n_vias,
        "n_tooling_holes": n_tooling,
        "sides_hist": sides_hist,
        "n_warnings": len(warnings),
    }
    return {
        "schema": f"odbpp/{PARSER_SCHEMA_VERSION}",
        "header": header,
        "units": units,
        "nets": net_order,
        "net_points": points,
        "stats": stats,
        "warnings": warnings,
    }


def _frac_or_none(token: str) -> Fraction | None:
    """十进制 token → Fraction（``5.``/``.5``/``-1.5`` 容忍；非数=None）。"""
    try:
        return Fraction(token)
    except (ValueError, ZeroDivisionError):
        return None


# ---------------------------------------------------------------------------
# eda/data 与 components
# ---------------------------------------------------------------------------


def parse_odb_eda_data(text: str) -> dict[str, Any]:
    """eda/data 文本 → 顶层记录结构化（NET/SNT/PIN 计数与 net 序）。

    包几何 outline（PKG/PIN 后的 RC/CR/SQ/CT/OB.../CE）不展开几何——
    仅统计。PRP 记录按最近宿主（NET/PKG）归组（宿主判定=最近一条
    宿主记录行）。
    """
    warnings: list[str] = []
    hdr: str | None = None
    lyr: list[str] = []
    nets: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    current_net: dict[str, Any] | None = None
    current_pkg: dict[str, Any] | None = None
    current_host: str | None = None  # "NET"|"PKG"
    pending_snt: dict[str, Any] | None = None

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("UNITS=") or line.startswith("ID="):
            continue
        if line.startswith(("@", "&")):
            parts = line.split(None, 1)
            counts[parts[0][0]] = counts.get(parts[0][0], 0) + 1
            continue  # 属性查找表行（@idx/.name 与 &idx/text）：收编计数不解释
        toks = line.split(None, 1)
        token = toks[0]
        counts[token] = counts.get(token, 0) + 1
        rest = toks[1].strip() if len(toks) > 1 else ""
        if token == "HDR":
            hdr = rest.strip()
            continue
        if token == "LYR":
            lyr.extend(rest.split())
            continue
        if token == "NET":
            name = rest.split(";")[0].strip()
            current_net = {"name": name, "subnets": [], "line": lineno}
            nets.append(current_net)
            current_host = "NET"
            current_pkg = None
            pending_snt = None
            continue
        if token == "PKG":
            parts = rest.split(";")[0].split()
            current_pkg = {
                "name": parts[0] if parts else None,
                "pitch": _frac_or_none(parts[1]) if len(parts) > 1 else None,
                "line": lineno,
            }
            if current_pkg["pitch"] is not None:
                current_pkg["pitch"] = float(current_pkg["pitch"])
            packages.append(current_pkg)
            current_host = "PKG"
            current_net = None
            pending_snt = None
            continue
        if token == "SNT":
            kind = rest.split()[0] if rest else None
            entry: dict[str, Any] = {"kind": kind}
            if kind == "TOP" and current_net is not None:
                parts = rest.split()[1:]
                entry.update({
                    "side": parts[0] if parts else None,
                    "comp_num": _int_or_none(parts[1]) if len(parts) > 1 else None,
                    "toep_num": _int_or_none(parts[2]) if len(parts) > 2 else None,
                })
            if current_net is not None:
                current_net["subnets"].append(entry)
            pending_snt = entry
            continue
        if token == "FID":
            # FID <type> <lyr_num> <f_num>；挂在最近 SNT 上（规范 p118）
            parts = rest.split()
            if pending_snt is not None:
                fids = pending_snt.setdefault("fids", [])
                fids.append({
                    "type": parts[0] if parts else None,
                    "lyr_num": _int_or_none(parts[1]) if len(parts) > 1 else None,
                    "f_num": _int_or_none(parts[2]) if len(parts) > 2 else None,
                })
            continue
        if token in ("PIN",):
            # PIN <num> <S|P> <x> <y> <rot> <epoint> <pol>（规范 p119）
            parts = rest.split()
            pin: dict[str, Any] = {
                "num": _int_or_none(parts[0]) if parts else None,
                "net_id": parts[1] if len(parts) > 1 else None,
            }
            if current_pkg is not None:
                pins = current_pkg.setdefault("pins", [])
                pin["index"] = len(pins)
                pins.append(pin)
            continue
        if token == "PRP":
            parts = rest.split(None, 1)
            name = parts[0] if parts else None
            host = (current_net if current_host == "NET" and current_net
                    else current_pkg if current_host == "PKG" and current_pkg
                    else None)
            if host is not None:
                props = host.setdefault("properties", {})
                props[name] = (parts[1].strip() if len(parts) > 1 else None)
            continue
        if token in ("RC", "CR", "SQ", "CT", "OB", "OS", "OC", "OE", "CE",
                     "FGR"):
            continue  # outline/组记录：仅计数（records 字典已 +1）
        # 未知记录 token：warning（逐条披露不改据）
        _warn(warnings, f"第 {lineno} 行未识别记录 {token!r}，跳过")
    net_names = [n["name"] for n in nets]
    stats = {
        "n_nets": len(nets),
        "n_packages": len(packages),
        "n_layers_named": len(lyr),
        "n_pins": sum(len(p.get("pins") or []) for p in packages),
        "n_subnets": sum(len(n["subnets"]) for n in nets),
        "n_warnings": len(warnings),
    }
    return {
        "hdr": hdr,
        "layers": lyr,
        "nets": nets,
        "packages": packages,
        "net_names": net_names,
        "records": counts,
        "stats": stats,
        "warnings": warnings,
    }


def _int_or_none(token: str) -> int | None:
    try:
        return int(token)
    except (ValueError, TypeError):
        return None


def parse_odb_components(text: str) -> dict[str, Any]:
    """components 文本 → 元件/引脚/属性/BOM 结构化（几何 POLY 不展开）。

    ``CMP <pkg_ref> <x> <y> <rot> <mirror> <comp_name> <part_name>``；
    ``TOP <pin_num> <x> <y> <rot> <mirror> <net_num> <subnet_num>
    <toeprint_name>``（net_num 序=eda/data NET 序，规范 p160——关联
    解析留给消费方经 :func:`parse_odb_eda_data` 的 net 序）。
    """
    warnings: list[str] = []
    components: list[dict[str, Any]] = []
    bom: dict[str, str] = {}
    counts: dict[str, int] = {}
    current: dict[str, Any] | None = None
    in_bom = False

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            if line == "# BOM DATA":
                in_bom = True
            continue
        if line.startswith("UNITS="):
            continue
        if line.startswith(("@", "&")):
            continue  # 属性查找表行：收编跳过不解释
        toks = line.split(None, 1)
        token = toks[0]
        counts[token] = counts.get(token, 0) + 1
        rest = toks[1].strip() if len(toks) > 1 else ""
        if token == "CMP":
            parts = rest.split(";")[0].split()
            mirror = parts[4] if len(parts) > 4 else None
            current = {
                "pkg_ref": _int_or_none(parts[0]) if parts else None,
                "x": float(_frac_or_none(parts[1])) if len(parts) > 1
                     and _frac_or_none(parts[1]) is not None else None,
                "y": float(_frac_or_none(parts[2])) if len(parts) > 2
                     and _frac_or_none(parts[2]) is not None else None,
                "rotation": float(_frac_or_none(parts[3])) if len(parts) > 3
                            and _frac_or_none(parts[3]) is not None else None,
                "mirrored": mirror == "M",
                "comp_name": parts[5] if len(parts) > 5 else None,
                "part_name": parts[6] if len(parts) > 6 else None,
                "pins": [],
                "properties": {},
                "line": lineno,
            }
            if len(parts) < 7:
                _warn(warnings,
                      f"第 {lineno} 行 CMP 字段不足 7（得 {len(parts)}），"
                      "缺省字段如实 None")
            components.append(current)
            in_bom = False
            continue
        if token == "TOP" and current is not None:
            parts = rest.split()
            current["pins"].append({
                "pin_num": _int_or_none(parts[0]) if parts else None,
                "x": float(_frac_or_none(parts[1])) if len(parts) > 1
                     and _frac_or_none(parts[1]) is not None else None,
                "y": float(_frac_or_none(parts[2])) if len(parts) > 2
                     and _frac_or_none(parts[2]) is not None else None,
                "net_num": _int_or_none(parts[5]) if len(parts) > 5 else None,
                "subnet_num": _int_or_none(parts[6]) if len(parts) > 6 else None,
                "toeprint": parts[7] if len(parts) > 7 else None,
            })
            continue
        if token == "PRP":
            parts = rest.split(None, 1)
            if current is not None:
                current["properties"][parts[0]] = (
                    parts[1].strip() if len(parts) > 1 else None)
            continue
        if in_bom and token in BOM_KEYWORDS:
            bom[token] = rest.strip()
            continue
        if token not in ("CMP", "TOP", "PRP"):
            _warn(warnings, f"第 {lineno} 行未识别记录 {token!r}，跳过")
    stats = {
        "n_components": len(components),
        "n_pins": sum(len(c["pins"]) for c in components),
        "n_bom_keys": len(bom),
        "n_warnings": len(warnings),
    }
    return {
        "components": components,
        "bom": bom,
        "records": counts,
        "stats": stats,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 目录树（唯二 IO 面：parse_odb_dir / 层目录枚举）
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str | None:
    """读文本：utf-8 优先 Latin-1 兜底；不可读如实 None（fail-soft）。"""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse_odb_dir(root: str | Path) -> dict[str, Any]:
    """ODB++ 目录树 → 全结构化文档（结构与统计面；零几何展开）。

    五文件级解析（存在才解析、缺失如实 None）+ 全树统计。目录根不存在
    或 matrix/matrix 缺失 → :class:`OdbppParseError`（服务层转 error
    信封）；其余一切文件级缺失/不可读 → fail-soft 如实登记。

    Returns:
        ``{"schema", "root", "info", "matrix", "steps": [...],
        "symbols": [...], "stats", "warnings"}``——steps 元素
        ``{"name", "stephdr", "layers": [{"name","features","attrlist",
        "components","tools"}], "cadnet", "eda_data", "profile_stats",
        "dir_layers": [目录实存层名]}``。
    """
    typed_root = Path(root)
    if not typed_root.is_dir():
        raise OdbppParseError(f"ODB++ 目录不存在: {typed_root}")
    matrix_file = typed_root / "matrix" / "matrix"
    matrix_text = _read_text(matrix_file)
    if matrix_text is None:
        raise OdbppParseError(f"缺 matrix/matrix: {typed_root}")
    warnings: list[str] = []

    matrix_doc = parse_odb_matrix(matrix_text)
    warnings.extend(matrix_doc["warnings"])

    info_doc: dict[str, Any] | None = None
    info_text = _read_text(typed_root / "misc" / "info")
    if info_text is not None:
        info_doc = parse_odb_info(info_text)
        warnings.extend(info_doc["warnings"])

    model_units = (info_doc or {}).get("units") or matrix_doc.get("raw_unit")

    steps_dir = typed_root / "steps"
    step_dirs = (sorted(p for p in steps_dir.iterdir() if p.is_dir())
                 if steps_dir.is_dir() else [])
    declared_steps = set(matrix_doc["steps"])
    declared_steps_lower = {s.lower() for s in declared_steps}
    seen_steps: set[str] = set()
    step_docs: list[dict[str, Any]] = []

    for step_dir in step_dirs:
        step_name = step_dir.name
        seen_steps.add(step_name.lower())
        step_doc: dict[str, Any] = {
            "name": step_name,
            "stephdr": None,
            "layers": [],
            "cadnet": None,
            "eda_data": None,
            "profile_stats": None,
            "dir_layers": [],
        }
        hdr_text = _read_text(step_dir / "stephdr")
        if hdr_text is not None:
            step_doc["stephdr"] = parse_odb_stephdr(hdr_text)
            warnings.extend(step_doc["stephdr"]["warnings"])

        layers_dir = step_dir / "layers"
        layer_dirs = (sorted(p for p in layers_dir.iterdir() if p.is_dir())
                      if layers_dir.is_dir() else [])
        seen_layers: set[str] = set()
        for layer_dir in layer_dirs:
            lname = layer_dir.name
            seen_layers.add(lname)
            layer_doc: dict[str, Any] = {
                "name": lname,
                "matrix_name": matrix_doc["layer_dir_map"].get(lname.lower()),
                "features": None,
                "attrlist": None,
                "components": None,
                "tools": None,
            }
            features_text = _read_text(layer_dir / "features")
            if features_text is not None:
                fdoc = parse_odb_features(features_text)
                layer_doc["features"] = fdoc
                warnings.extend(fdoc["warnings"])
            attr_text = _read_text(layer_dir / "attrlist")
            if attr_text is not None:
                afields, _ab, aw = _parse_structured(attr_text)
                layer_doc["attrlist"] = afields
                warnings.extend(aw)
            comp_text = _read_text(layer_dir / "components")
            if comp_text is not None:
                cdoc = parse_odb_components(comp_text)
                layer_doc["components"] = cdoc
                warnings.extend(cdoc["warnings"])
            tools_text = _read_text(layer_dir / "tools")
            if tools_text is not None:
                tfields, _tb, tw = _parse_structured(tools_text)
                layer_doc["tools"] = tfields
                warnings.extend(tw)
            step_doc["layers"].append(layer_doc)
        step_doc["dir_layers"] = sorted(seen_layers)

        cadnet_text = _read_text(step_dir / "netlists" / "cadnet" / "netlist")
        if cadnet_text is not None:
            cadnet_doc = parse_odb_cadnet(cadnet_text)
            step_doc["cadnet"] = cadnet_doc
            warnings.extend(cadnet_doc["warnings"])
        eda_text = _read_text(step_dir / "eda" / "data")
        if eda_text is not None:
            eda_doc = parse_odb_eda_data(eda_text)
            step_doc["eda_data"] = eda_doc
            warnings.extend(eda_doc["warnings"])
        profile_text = _read_text(step_dir / "profile")
        if profile_text is not None:
            step_doc["profile_stats"] = parse_odb_features(profile_text)
            warnings.extend(step_doc["profile_stats"]["warnings"])

        # stack 对齐（matrix 声明 vs 本 step 层目录实存）
        stack = odbpp_layer_stack_summary(matrix_doc, step_doc["dir_layers"])
        step_doc["stack_summary"] = stack
        warnings.extend(stack["warnings"])
        step_docs.append(step_doc)

    for step_dir in step_dirs:
        if step_dir.name.lower() not in declared_steps_lower:
            _warn(warnings,
                  f"steps/ 目录含 matrix 未声明 step {step_dir.name!r}")
    if matrix_doc["steps"] and not seen_steps:
        _warn(warnings, "matrix 声明了 step 但 steps/ 目录无实存 step 目录")
    missing_steps = sorted(
        s for s in declared_steps if s.lower() not in seen_steps)
    for name in missing_steps:
        _warn(warnings, f"matrix 声明 step {name!r} 在 steps/ 目录缺失")

    symbols_root = typed_root / "symbols"
    symbol_docs: list[dict[str, Any]] = []
    if symbols_root.is_dir():
        for sym_dir in sorted(p for p in symbols_root.iterdir() if p.is_dir()):
            sym_doc: dict[str, Any] = {
                "name": sym_dir.name,
                "classify": classify_symbol_name(sym_dir.name, "M"),
                "features": None,
                "attrlist": None,
            }
            sym_features = _read_text(sym_dir / "features")
            if sym_features is not None:
                sym_doc["features"] = parse_odb_features(sym_features)
                warnings.extend(sym_doc["features"]["warnings"])
            sym_attr = _read_text(sym_dir / "attrlist")
            if sym_attr is not None:
                sfields, _sb, sw = _parse_structured(sym_attr)
                sym_doc["attrlist"] = sfields
                warnings.extend(sw)
            symbol_docs.append(sym_doc)

    total_features_records = 0
    total_pad_refs = 0
    for step_doc in step_docs:
        for layer_doc in step_doc["layers"]:
            fdoc = layer_doc.get("features")
            if fdoc:
                total_features_records += sum(fdoc["records"].values())
                total_pad_refs += fdoc["pad_refs"]

    stats = {
        "n_steps_declared": len(matrix_doc["steps"]),
        "n_steps_on_disk": len(step_dirs),
        "n_layers_declared": len(matrix_doc["layers"]),
        "n_layers_on_disk": sum(len(s["layers"]) for s in step_docs),
        "n_features_records": total_features_records,
        "n_pad_refs": total_pad_refs,
        "n_symbols_dirs": len(symbol_docs),
        "missing_steps_in_matrix": missing_steps,
        "n_warnings": len(warnings),
    }
    return {
        "schema": f"odbpp/{PARSER_SCHEMA_VERSION}",
        "root": str(typed_root),
        "info": info_doc,
        "matrix": matrix_doc,
        "steps": step_docs,
        "symbols": symbol_docs,
        "model_units": model_units,
        "stats": stats,
        "warnings": list(dict.fromkeys(warnings)),
    }


# ---------------------------------------------------------------------------
# 制造库存与对齐校验（纯函数，消费解析产物）
# ---------------------------------------------------------------------------


def odbpp_net_inventory(step_doc: dict[str, Any]) -> dict[str, Any]:
    """step 文档 → net 库存（net→pads 映射 + 悬空 pad + 空 net 双清单）。

    **宁多报不误报**（任务书口径）：判定缺证据即入清单——

    - ``nets``：net 名 → 归属点/pad 名录（cadnet 点行 + eda/data SNT
      TOP 的 (comp_num, toep_num) + components 层 TOP 的
      (comp_name, pin_num) 经 net_num 序关联三源合一）；
    - ``dangling_pads``：features P 记录计数>0 且该层无 net 关联证据
      （cadnet 点/eda NET/SNT 皆无）→ 该层全量 pad 计数如实入清单
      （坐标级归属需几何展开，本模块不做——计数级宁多报）；
    - ``empty_nets``：有名但零连接证据（cadnet 无点且 eda 无 SNT）的
      net。

    Returns:
        ``{"nets": {name: {"points": n, "pins": [(comp, pin)...]}},
        "dangling_pads": [...], "empty_nets": [...], "stats": {...}}``。
    """
    nets: dict[str, dict[str, Any]] = {}
    empty_nets: list[str] = []

    cadnet = step_doc.get("cadnet")
    cadnet_nets = set(cadnet.get("nets") or []) if cadnet else set()
    for name in sorted(cadnet_nets):
        nets.setdefault(name, {"points": 0, "pins": []})
    if cadnet:
        for pt in cadnet.get("net_points") or []:
            name = pt.get("net")
            if name:
                nets.setdefault(name, {"points": 0, "pins": []})
                nets[name]["points"] += 1

    eda = step_doc.get("eda_data")
    eda_net_names: list[str] = []
    eda_net_has_snt: dict[str, bool] = {}
    if eda:
        eda_net_names = list(eda.get("net_names") or [])
        for net_doc in eda.get("nets") or []:
            name = net_doc.get("name")
            if not name:
                continue
            has = bool(net_doc.get("subnets"))
            eda_net_has_snt[name] = has
            nets.setdefault(name, {"points": 0, "pins": []})
            for snt in net_doc.get("subnets") or []:
                if snt.get("kind") == "TOP":
                    comp = snt.get("comp_num")
                    toep = snt.get("toep_num")
                    if comp is not None and toep is not None:
                        nets[name]["pins"].append((f"CMP{comp}", str(toep)))

    # components 层引脚经 net_num → eda net 序关联（规范 p160）
    comp_layer = None
    for layer_doc in step_doc.get("layers") or []:
        if layer_doc.get("components"):
            comp_layer = layer_doc["components"]
            break
    if comp_layer is not None and eda:
        for comp in comp_layer.get("components") or []:
            cname = comp.get("comp_name")
            for pin in comp.get("pins") or []:
                net_num = pin.get("net_num")
                pin_num = pin.get("pin_num")
                if (cname is not None and pin_num is not None
                        and net_num is not None and 0 <= net_num < len(eda_net_names)):
                    net_name = eda_net_names[net_num]
                    nets.setdefault(net_name, {"points": 0, "pins": []})
                    nets[net_name]["pins"].append((cname, str(pin_num)))

    # 空 net：两源皆有名但零证据（cadnet 零点且 eda 零 SNT）
    for name in sorted(set(cadnet_nets) | set(eda_net_names)):
        entry = nets.get(name)
        pts = entry["points"] if entry else 0
        pins = len(entry["pins"]) if entry else 0
        if pts == 0 and pins == 0 and not eda_net_has_snt.get(name, False):
            empty_nets.append(name)

    # 悬空 pad：层 features 有 P 计数但全树无任何 net 关联证据
    # （计数级宁多报：任何 net 证据存在即不判悬空——零几何归属面）
    any_net_evidence = bool(
        (cadnet and (cadnet.get("net_points") or cadnet.get("nets")))
        or (eda and (eda.get("nets") or eda.get("packages")))
    )
    dangling: list[dict[str, Any]] = []
    for layer_doc in step_doc.get("layers") or []:
        fdoc = layer_doc.get("features")
        if fdoc and fdoc.get("pad_refs", 0) > 0 and not any_net_evidence:
            dangling.append({
                "layer": layer_doc.get("name"),
                "pad_refs": fdoc["pad_refs"],
            })

    stats = {
        "n_nets": len(nets),
        "n_empty_nets": len(empty_nets),
        "n_dangling_layers": len(dangling),
        "n_pin_refs": sum(len(v["pins"]) for v in nets.values()),
    }
    return {
        "nets": nets,
        "dangling_pads": dangling,
        "empty_nets": empty_nets,
        "stats": stats,
    }


def odbpp_layer_stack_summary(
    matrix_doc: dict[str, Any], step_layer_dirs: list[str]
) -> dict[str, Any]:
    """matrix 声明 vs step 实存层目录对齐校验（缺失/多余双清单）。

    对齐键=目录小写名（``NAME.lower()`` ↔ 目录名小写比较；KiCad 口径
    NAME 大写、目录小写）。规范 p68："Each named layer MUST have a
    layer entity defined under the layers directory of each step"。
    """
    warnings: list[str] = []
    declared = {str(dir_key).lower(): str(name)
                for dir_key, name in (matrix_doc.get("layer_dir_map")
                                      or {}).items()}
    on_disk_lower = {d.lower() for d in step_layer_dirs}
    missing = sorted(n for lw, n in declared.items() if lw not in on_disk_lower)
    extra = sorted(d for d in step_layer_dirs if d.lower() not in declared)
    for name in missing:
        warnings.append(f"matrix 声明层 {name!r} 在 step 层目录缺失")
    for d in extra:
        warnings.append(f"step 层目录 {d!r} 不在 matrix 声明中（多余层）")
    return {
        "declared": sorted(declared.values()),
        "on_disk": sorted(step_layer_dirs),
        "missing": missing,
        "extra": extra,
        "aligned": not missing and not extra,
        "warnings": warnings,
    }
