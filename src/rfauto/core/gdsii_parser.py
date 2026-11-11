"""GDSII 二进制结构确定性解析内核（aurora_q 席位 Q-X58，2026-11-07）。

版图交换事实标准 GDSII（Calma/GDSII Stream Format **公开规范**口径，与
KLayout/gdstk/magic 等开源实现的公开文档相互印证——非专有资料）的只读
结构化解析：纯 Python 字节级解析，**零第三方依赖**（gdstk/gdspy 属大依
赖不入仓；字节级确定性内核正是本席要点）。层级/几何语义全在 core 确定
性内核（铁律 7：结构化数字只出自数据源字节本身）；服务包装见
:mod:`rfauto.service.gdsii_service`（规则 4 JSON 进出），CLI 薄壳见
cli/domains/gdsii.py。

格式口径（公开规范，逐条落地）：

- **记录头 = 4 字节**：2 字节大端 length（**含头自身 4 字节**）+ 1 字节
  record type + 1 字节 data type，负载长 = length-4（任务书"2+2+2"系
  笔误——公开规范与全部开源实现均为 4 字节头，本模块按公开规范落地）；
- **data type**：0x00 无负载 / 0x01 bitarray(2B) / 0x02 int2(2B) /
  0x03 int4(4B) / 0x04 real4(4B) / 0x05 real8(8B)，全部大端；
- **GDSII 实数**（real4/real8）：1 位符号 + 7 位指数（16 为底、偏移
  64）+ 尾数（real8 56 位 / real4 24 位，16 进分数）——value =
  sign·mant·2^(4·exp−尾数位宽)。精确解码走 **int/int 正确舍入除法**
  （CPython ``long_true_divide`` 语义）与整数左移：56/24 位尾数超
  double 53 位有效位，``float(mant)`` 先行转换会丢位（禁用）——先整
  数移位、后一次舍入，才是对精确有理数的最近 double；
- 全零字节特判 0.0；仅符号位形态如实解码出 -0.0；
- **ASCII 记录**（LIBNAME/STRNAME/SNAME/STRING）：偶字节对齐、尾部 NUL
  填充——尾 NUL 清理后 ascii 解码（非 ASCII 字节 → U+FFFD 替换如实
  显示，不猜编码）。

结构面（记录流状态机，任务书口径）：库层 HEADER(version)/BGNLIB/
LIBNAME/UNITS(双 real8)/BGNSTR/STRNAME/ENDSTR/ENDLIB；元素层
BOUNDARY(LAYER+DATATYPE+XY 闭多边形)/PATH(LAYER+DATATYPE+WIDTH+
PATHTYPE+XY 中心线)/SREF(SNAME+STRANS/MAG/ANGLE+XY 1 点)/AREF(SNAME+
STRANS/MAG/ANGLE+COLROW+XY 3 锚点)/TEXT(LAYER+TEXTTYPE+PRESENTATION+
STRANS/MAG/ANGLE+XY+STRING)/BOX(LAYER+BOXTYPE+XY 5 点)。

fail-soft 口径（citi_parser 家法）：记录流逐记录推进——头截断 /
length<4（含零 length 死循环面）/ 负载越界 → warning + 停流，已收面
如实保留 + ``truncated=True``；未知记录号 → warning + 跳过；重名结构 →
warning + 桶合并；无 STRNAME 领衔的元素 → warning + 丢弃；元素未
ENDEL 收口即遇新记录 → 按截断态物化 + warning；NODE/TEXTNODE（本席
契约外元素）→ warning + 跳到 ENDEL。warning 同文去重（逐条披露不改
据）。**首个记录即不可读**（零字节/过短/首记录长度非法）→
:class:`GdsiiParseError`（文件级错误，区别于流中截断）。

STRANS 语义（公开规范）：bitarray bit15=反射（关于 x 轴，**先反射后
旋转**）；MAG 缺省 1.0、ANGLE 缺省 0.0（逆时针，度）。

拓扑提取三函数（输入 = 本模块结构化文档 dict）：

- :func:`gdsii_hierarchy_stats`：逐结构被引用计数（SREF/AREF 目标统计）
  + 未定义引用（SNAME 不在 structures）+ 孤儿结构（零引用零元素）与
  零引用结构两桶（宁多报口径）；
- :func:`gdsii_layer_summary`：逐 (layer, datatype) 元素计数 + 包围盒
  （text 按 texttype、box 按 boxtype 归并到 datatype 位）；
- :func:`gdsii_expand_bbox`：指定结构递归展开包围盒——SREF/AREF 平移/
  反射/旋转**仅 0/90/180/270 精确**展开（整数坐标变换零近似）；任意角
  度或 mag≠1 如实 skip 记 warning 不近似展开；循环引用/深度守卫 +
  warning。

坐标口径：XY 全程原值 DBU（int）落盘；DBU→µm 走显式函数
:func:`dbu_to_um`（UNITS real8 双值按任务书口径落键 db_um/user_um，
标准规范语义（DB in user units / DB in meters）原值双录 ``units_raw``
不失真）。确定性（同输入同输出）、零 IO 消费面（bytes 进 dict 出）、
零第三方依赖。本模块不设 ``__all__``（无 __all__ 文件不进
tests/gold/public_api.json——verilog_netlist_parser 同款先例，新模块
零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

# ── 记录号常量表（公开规范；0x37-0x3F 保留、其余未列号=未分配）──────────────

HEADER = 0x00
BGNLIB = 0x01
LIBNAME = 0x02
UNITS = 0x03
ENDLIB = 0x04
BGNSTR = 0x05
STRNAME = 0x06
ENDSTR = 0x07
BOUNDARY = 0x08
PATH = 0x09
SREF = 0x0A
AREF = 0x0B
TEXT = 0x0C
LAYER = 0x0D
DATATYPE = 0x0E
WIDTH = 0x0F
XY = 0x10
ENDEL = 0x11
SNAME = 0x12
COLROW = 0x13
TEXTNODE = 0x14
NODE = 0x15
TEXTTYPE = 0x16
PRESENTATION = 0x17
STRING = 0x19
STRANS = 0x1A
MAG = 0x1B
ANGLE = 0x1C
REFLIBS = 0x1F
FONTS = 0x20
PATHTYPE = 0x21
GENERATIONS = 0x22
ATTRTABLE = 0x23
STYPTABLE = 0x25
ELFLAGS = 0x26
BOX = 0x2D
BOXTYPE = 0x2E
PLEX = 0x2F
BGNEXTN = 0x30
ENDEXTN = 0x31
TAPENUM = 0x32
TAPECODE = 0x33
FORMAT = 0x36

#: 记录号 → 名称（已知记录全集单源；不在表内=未知记录号，fail-soft warning）。
RECORD_NAMES: dict[int, str] = {
    HEADER: "HEADER", BGNLIB: "BGNLIB", LIBNAME: "LIBNAME", UNITS: "UNITS",
    ENDLIB: "ENDLIB", BGNSTR: "BGNSTR", STRNAME: "STRNAME", ENDSTR: "ENDSTR",
    BOUNDARY: "BOUNDARY", PATH: "PATH", SREF: "SREF", AREF: "AREF",
    TEXT: "TEXT", LAYER: "LAYER", DATATYPE: "DATATYPE", WIDTH: "WIDTH",
    XY: "XY", ENDEL: "ENDEL", SNAME: "SNAME", COLROW: "COLROW",
    TEXTNODE: "TEXTNODE", NODE: "NODE", TEXTTYPE: "TEXTTYPE",
    PRESENTATION: "PRESENTATION", STRING: "STRING", STRANS: "STRANS",
    MAG: "MAG", ANGLE: "ANGLE", REFLIBS: "REFLIBS", FONTS: "FONTS",
    PATHTYPE: "PATHTYPE", GENERATIONS: "GENERATIONS",
    ATTRTABLE: "ATTRTABLE", STYPTABLE: "STYPTABLE", ELFLAGS: "ELFLAGS",
    BOX: "BOX", BOXTYPE: "BOXTYPE", PLEX: "PLEX", BGNEXTN: "BGNEXTN",
    ENDEXTN: "ENDEXTN", TAPENUM: "TAPENUM", TAPECODE: "TAPECODE",
    FORMAT: "FORMAT",
}

# ── data type 常量 ─────────────────────────────────────────────────────────

DT_NODATA = 0x00
DT_BITARRAY = 0x01
DT_INT2 = 0x02
DT_INT4 = 0x03
DT_REAL4 = 0x04
DT_REAL8 = 0x05

#: STRANS bitarray bit15（MSB）= 关于 x 轴反射（先反射后旋转，公开规范）。
STRANS_REFLECT_BIT = 0x8000

#: 元素六桶（结构化输出与逐桶统计的单源键面）。
ELEMENT_BUCKETS = ("boundaries", "paths", "srefs", "arefs", "texts", "boxes")

#: 递归展开的层级深度守卫（病态深层级防 RecursionError；超限如实 warning）。
MAX_HIERARCHY_DEPTH = 256

#: 精确旋转角集合（仅这些角度整数坐标变换零近似；模 360 归一后比对）。
_EXACT_ANGLES = (0.0, 90.0, 180.0, 270.0)


class GdsiiParseError(ValueError):
    """GDSII 文件级错误（零字节/过短/首记录不可读——非流中截断）。"""


# ── 单值解码（字节级手解）───────────────────────────────────────────────────


def decode_gds_real8(data: bytes) -> float:
    """GDSII real8（8 字节：1 符号+7 指数 16 底偏移 64+56 位尾数）→ float。

    精确口径：value = sign·mant·2^(4·exp−56)。56 位尾数超 double 53 位
    有效位——``float(mant)`` 先行转换即丢位，禁用；正确实现=整数移位后
    一次舍入：移位为负（值放大）走精确整数左移再 ``float()``（单次舍
    入，且上限 2^252 有限无溢出），移位为正（值缩小）走 CPython
    ``int/int`` 正确舍入除法。全零字节 → 0.0（特判）；仅符号位形态 →
    -0.0 如实保留。负载长度非 8 抛 :class:`GdsiiParseError`（不猜不改）。
    """
    if len(data) != 8:
        raise GdsiiParseError(f"real8 需 8 字节负载，实得 {len(data)}")
    if data == b"\x00" * 8:
        return 0.0
    sign = -1.0 if data[0] & 0x80 else 1.0
    exp = (data[0] & 0x7F) - 64
    mant = int.from_bytes(data[1:], "big")
    shift = 56 - 4 * exp          # value = mant / 2**shift（shift 可负）
    if shift >= 0:
        return sign * (mant / (1 << shift))
    return sign * float(mant << (-shift))


def decode_gds_real4(data: bytes) -> float:
    """GDSII real4（4 字节：1 符号+7 指数+24 位尾数）→ float。

    与 :func:`decode_gds_real8` 同构（尾数 24 位：2^(4·exp−24)）。
    """
    if len(data) != 4:
        raise GdsiiParseError(f"real4 需 4 字节负载，实得 {len(data)}")
    if data == b"\x00" * 4:
        return 0.0
    sign = -1.0 if data[0] & 0x80 else 1.0
    exp = (data[0] & 0x7F) - 64
    mant = int.from_bytes(data[1:], "big")
    shift = 24 - 4 * exp
    if shift >= 0:
        return sign * (mant / (1 << shift))
    return sign * float(mant << (-shift))


def decode_gds_ascii(data: bytes) -> str:
    """ASCII 记录负载 → 字符串（尾部 NUL 填充清理；非 ASCII 字节 →
    U+FFFD 替换如实显示，不猜编码）。"""
    stripped = data.rstrip(b"\x00")
    return stripped.decode("ascii", errors="replace")


def dbu_to_um(value_dbu: int | float, units: dict[str, Any]) -> float | None:
    """DBU 坐标 → µm（显式换算单源；UNITS 缺失（db_um=None）→ None 如实，
    不假设任何缺省因子）。"""
    factor = (units or {}).get("db_um")
    if factor is None:
        return None
    return value_dbu * factor


# ── 记录负载读取（带 fail-soft 校验）───────────────────────────────────────


def _warn(warnings: list[str], message: str) -> None:
    """同文去重追加（fail-soft 告警逐条披露不改据、不刷屏）。"""
    if message not in warnings:
        warnings.append(message)


def _rd_int2(payload: bytes, warnings: list[str], label: str) -> int | None:
    if len(payload) == 2:
        return int.from_bytes(payload, "big", signed=True)
    _warn(warnings,
          f"{label} 负载应 2 字节（int2），实得 {len(payload)}，字段如实置 None")
    return None


def _rd_int4(payload: bytes, warnings: list[str], label: str) -> int | None:
    if len(payload) == 4:
        return int.from_bytes(payload, "big", signed=True)
    _warn(warnings,
          f"{label} 负载应 4 字节（int4），实得 {len(payload)}，字段如实置 None")
    return None


def _rd_bitarray(payload: bytes, warnings: list[str],
                 label: str) -> int | None:
    if len(payload) == 2:
        return int.from_bytes(payload, "big", signed=False)
    _warn(warnings,
          f"{label} 负载应 2 字节（bitarray），实得 {len(payload)}，字段如实置 None")
    return None


def _rd_real8(payload: bytes, warnings: list[str], label: str) -> float | None:
    try:
        return decode_gds_real8(payload)
    except GdsiiParseError:
        _warn(warnings,
              f"{label} 负载应 8 字节（real8），实得 {len(payload)}，字段如实置 None")
        return None


def _rd_xy(payload: bytes, warnings: list[str]) -> list[list[int]]:
    """XY 记录 → ``[[x, y], ...]``（int4 对，大端）；非 8 倍数负载 →
    截断到整点对 + warning（fail-soft 宁少存不猜尾点）。"""
    n_full = len(payload) // 8
    if len(payload) % 8 != 0:
        _warn(warnings,
              f"XY 负载 {len(payload)} 字节非 8 倍数（int4 对），"
              f"截断到前 {n_full} 整点")
    out: list[list[int]] = []
    for k in range(n_full):
        chunk = payload[k * 8:(k + 1) * 8]
        out.append([
            int.from_bytes(chunk[0:4], "big", signed=True),
            int.from_bytes(chunk[4:8], "big", signed=True),
        ])
    return out


# ── 元素物化 ───────────────────────────────────────────────────────────────


def _ref_defaults(elem: dict[str, Any]) -> tuple[float, float, bool]:
    """SREF/AREF/TEXT 公共变换面归一：angle 缺省 0.0、mag 缺省 1.0、
    reflected 取 STRANS bit15（缺省 False）。缺省判据显式 ``is not None``
    （#364-④ falsy 陷阱家法：0.0 是合法 angle 非"缺失"）。"""
    angle = elem["angle"] if elem.get("angle") is not None else 0.0
    mag = elem["mag"] if elem.get("mag") is not None else 1.0
    strans = elem.get("strans")
    reflected = bool(strans & STRANS_REFLECT_BIT) if strans is not None else False
    return angle, mag, reflected


def _point_or_none(elem: dict[str, Any], warnings: list[str],
                   label: str) -> tuple[int | None, int | None]:
    """单点元素（SREF/TEXT/AREF 锚）取 XY 首点；多点取首点 + warning、
    零点 → (None, None) + warning（宁如实缺不猜 0）。"""
    xy = elem.get("xy") or []
    if not xy:
        _warn(warnings, f"{label} 缺 XY 点，坐标如实置 None")
        return None, None
    if len(xy) > 1:
        _warn(warnings, f"{label} XY 应 1 点，实得 {len(xy)}，取首点")
    return xy[0][0], xy[0][1]


def _materialize_element(kind: str, elem: dict[str, Any],
                         cur: dict[str, list] | None,
                         warnings: list[str]) -> None:
    """ENDEL 时把元素累积态物化进当前结构对应桶（缺字段如实 None）。"""
    if cur is None:
        _warn(warnings, f"{kind.upper()} 元素无 STRNAME 领衔结构，如实丢弃")
        return
    if kind == "boundary":
        if not elem.get("xy"):
            _warn(warnings, "BOUNDARY 无 XY 点，points_xy 如实空表")
        cur["boundaries"].append({
            "layer": elem.get("layer"),
            "datatype": elem.get("datatype"),
            "points_xy": elem.get("xy") or [],
        })
    elif kind == "path":
        cur["paths"].append({
            "layer": elem.get("layer"),
            "datatype": elem.get("datatype"),
            "width": elem.get("width"),
            "pathtype": elem.get("pathtype"),
            "points_xy": elem.get("xy") or [],
        })
    elif kind == "sref":
        angle, mag, reflected = _ref_defaults(elem)
        if not elem.get("sname"):
            _warn(warnings, "SREF 缺 SNAME，sname 如实置 None")
        x, y = _point_or_none(elem, warnings, "SREF")
        cur["srefs"].append({
            "sname": elem.get("sname"),
            "x": x, "y": y,
            "angle": angle, "mag": mag, "reflected": reflected,
        })
    elif kind == "aref":
        angle, mag, reflected = _ref_defaults(elem)
        if not elem.get("sname"):
            _warn(warnings, "AREF 缺 SNAME，sname 如实置 None")
        xy = elem.get("xy") or []
        if not xy:
            _warn(warnings, "AREF 缺 XY 锚点，坐标如实置 None")
            x: int | None = None
            y: int | None = None
        else:
            x, y = xy[0][0], xy[0][1]  # 首锚点=阵列原点（3 锚为规范形态）
            if len(xy) != 3:
                _warn(warnings,
                      f"AREF XY 应 3 锚点，实得 {len(xy)}，原值保留"
                      "（锚点消费方自查）")
        cols = elem.get("cols")
        rows = elem.get("rows")
        if cols is None or rows is None:
            _warn(warnings, "AREF 缺 COLROW，cols/rows 如实置 None")
        cur["arefs"].append({
            "sname": elem.get("sname"),
            "x": x, "y": y,
            "angle": angle, "mag": mag, "reflected": reflected,
            "cols": cols, "rows": rows,
            "xy": xy,
        })
    elif kind == "text":
        angle, mag, reflected = _ref_defaults(elem)
        x, y = _point_or_none(elem, warnings, "TEXT")
        cur["texts"].append({
            "layer": elem.get("layer"),
            "texttype": elem.get("texttype"),
            "presentation": elem.get("presentation"),
            "string": elem.get("string"),
            "x": x, "y": y,
            "angle": angle, "mag": mag, "reflected": reflected,
        })
    elif kind == "box":
        cur["boxes"].append({
            "layer": elem.get("layer"),
            "boxtype": elem.get("boxtype"),
            "points_xy": elem.get("xy") or [],
        })


# ── 记录流状态机 ───────────────────────────────────────────────────────────

#: 元素累积态里各记录号 → 累积键（元素区内可消费字段的单源映射；不在表
#: 内的已知记录（PLEX/ELFLAGS/GENERATIONS 等规范可选负载）静默消费）。
_ELEM_FIELD_OF: dict[int, str] = {
    LAYER: "layer", DATATYPE: "datatype", BOXTYPE: "boxtype",
    WIDTH: "width", PATHTYPE: "pathtype", TEXTTYPE: "texttype",
    PRESENTATION: "presentation", COLROW: "colrow", SNAME: "sname_raw",
    STRING: "string_raw", STRANS: "strans", MAG: "mag", ANGLE: "angle",
    XY: "xy", BGNEXTN: "bgnextn", ENDEXTN: "endextn",
}

#: 元素起点记录号 → 元素桶 kind。
_ELEM_KIND_OF: dict[int, str] = {
    BOUNDARY: "boundary", PATH: "path", SREF: "sref",
    AREF: "aref", TEXT: "text", BOX: "box",
}

#: 库层杂项记录（规范合法、本席契约不消费——静默通过）。
_LIB_MISC_RECORDS = frozenset({
    BGNLIB, REFLIBS, FONTS, GENERATIONS, ATTRTABLE, STYPTABLE,
    ELFLAGS, PLEX, TAPENUM, TAPECODE, FORMAT,
})

#: 库层结构级记录（元素区内出现即触发"元素截断态物化+转库层处理"）。
_STRUCTURE_LEVEL_RECORDS = frozenset({
    BGNSTR, STRNAME, ENDLIB, HEADER, LIBNAME, UNITS,
})


def _empty_structure() -> dict[str, list]:
    """结构六桶空壳（键面单源 = ELEMENT_BUCKETS）。"""
    return {bucket: [] for bucket in ELEMENT_BUCKETS}


def parse_gdsii_bytes(data: bytes) -> dict[str, Any]:
    """GDSII 字节流 → 结构化文档（确定性、零 IO、fail-soft warnings）。

    返回::

        {
          "schema": f"gdsii/{PARSER_SCHEMA_VERSION}",
          "lib_name": str|None, "version": int|None,
          "units": {"db_um": float|None, "user_um": float|None},
          "units_raw": [float|None, float|None],   # UNITS 双 real8 原值
          "structures": {name: {"boundaries": [...], "paths": [...],
                                "srefs": [...], "arefs": [...],
                                "texts": [...], "boxes": [...]}},
          "stats": {n_structures, n_boundaries, n_paths, n_srefs,
                    n_arefs, n_texts, n_boxes, n_warnings},
          "warnings": [str, ...],
          "truncated": bool,   # 流中截断（已收面如实保留）
        }

    零字节/过短/零可读记录（垃圾流）→ :class:`GdsiiParseError`（文件级
    错误）；流中截断/未知记录/结构缺陷 → warning + 已收面如实保留
    （fail-soft）。
    """
    warnings: list[str] = []
    doc: dict[str, Any] = {
        # 自描述键统一口径（R-22 schema 升位批）：``"<域>/<N.0>"`` 复合键。
        "schema": f"gdsii/{PARSER_SCHEMA_VERSION}",
        "lib_name": None,
        "version": None,
        "units": {"db_um": None, "user_um": None},
        "units_raw": [None, None],
        "structures": {},
        "stats": {},
        "warnings": warnings,
        "truncated": False,
    }
    n = len(data)
    if n == 0:
        raise GdsiiParseError("空文件：零字节非 GDSII")
    if n < 4:
        raise GdsiiParseError(
            f"文件过短（{n} 字节 < 最小记录头 4 字节），非 GDSII")

    pos = 0
    saw_endlib = False
    truncated = False
    n_records = 0                   # 成功消费的记录数（0=垃圾流→文件级错误）
    in_structure = False            # BGNSTR/STRNAME..ENDSTR 之间
    cur_name: str | None = None
    cur_struct: dict[str, list] | None = None
    elem: dict[str, Any] | None = None   # 元素累积态
    elem_kind: str | None = None
    skip_node = False               # NODE/TEXTNODE 跳到 ENDEL 态

    while pos < n:
        if saw_endlib:
            _warn(warnings, f"ENDLIB 后仍有 {n - pos} 字节尾巴，如实忽略")
            break
        if pos + 4 > n:
            _warn(warnings,
                  f"记录头截断（偏移 {pos}，余 {n - pos} 字节 < 4），流停止")
            truncated = True
            break
        length = int.from_bytes(data[pos:pos + 2], "big")
        rectype = data[pos + 2]
        datatype = data[pos + 3]
        if length < 4:
            _warn(warnings,
                  f"记录长度 {length} < 4（偏移 {pos}，类型 0x{rectype:02X}），"
                  "流停止（零长度防死循环）")
            truncated = True
            break
        end = pos + length
        if end > n:
            _warn(warnings,
                  f"记录声明长度 {length} 超出剩余 {n - pos} 字节"
                  f"（偏移 {pos}，类型 0x{rectype:02X}），流停止（截断）")
            truncated = True
            break
        payload = data[pos + 4:end]
        pos = end
        n_records += 1
        if rectype not in RECORD_NAMES:
            _warn(warnings,
                  f"未知记录号 0x{rectype:02X}（data type 0x{datatype:02X}，"
                  f"负载 {len(payload)} 字节），跳过")
            continue

        # ── 收口类记录（ENDEL/ENDSTR）优先于元素区/库层判定 ──
        if rectype == ENDSTR:
            if skip_node:
                skip_node = False
                _warn(warnings, "NODE/TEXTNODE 未 ENDEL 收口即遇 ENDSTR")
            if elem is not None:
                _warn(warnings,
                      f"{(elem_kind or '?').upper()} 未 ENDEL 收口即遇 "
                      "ENDSTR，已收字段按截断态物化")
                _materialize_element(elem_kind or "", elem, cur_struct,
                                     warnings)
                elem = None
                elem_kind = None
            if not in_structure:
                _warn(warnings, "ENDSTR 无在制结构（无匹配 STRNAME），忽略")
            in_structure = False
            cur_name = None
            cur_struct = None
            continue
        if rectype == ENDEL:
            if skip_node:
                skip_node = False
            elif elem is not None:
                _materialize_element(elem_kind or "", elem, cur_struct,
                                     warnings)
                elem = None
                elem_kind = None
            else:
                _warn(warnings, "ENDEL 无在制元素，忽略")
            continue

        # ── 元素累积区（BOUNDARY/PATH/SREF/AREF/TEXT/BOX 已开）──
        if elem is not None or skip_node:
            if rectype in _STRUCTURE_LEVEL_RECORDS:
                # 元素未收口即遇库层/结构级记录：截断态物化后落入常规处理
                if elem is not None:
                    _warn(warnings,
                          f"{(elem_kind or '?').upper()} 未 ENDEL 收口即遇 "
                          f"{RECORD_NAMES[rectype]}，按截断态物化")
                    _materialize_element(elem_kind or "", elem, cur_struct,
                                         warnings)
                    elem = None
                    elem_kind = None
                skip_node = False
                # 不 continue——落入下方库层/结构层常规处理
            elif rectype in (NODE, TEXTNODE):
                if elem is not None:
                    _warn(warnings,
                          f"元素区内出现 {(elem_kind or '?').upper()} 未收口"
                          f"即遇 {RECORD_NAMES[rectype]}，前一元素按截断态物化")
                    _materialize_element(elem_kind or "", elem, cur_struct,
                                         warnings)
                    elem = None
                    elem_kind = None
                skip_node = True
                continue
            elif rectype in _ELEM_KIND_OF:
                _warn(warnings,
                      f"{(elem_kind or '?').upper()} 未 ENDEL 收口即遇新元素 "
                      f"{RECORD_NAMES[rectype]}，前一元素按截断态物化")
                _materialize_element(elem_kind or "", elem or {}, cur_struct,
                                     warnings)
                elem = {}
                elem_kind = _ELEM_KIND_OF[rectype]
                continue
            elif skip_node:
                continue  # NODE/TEXTNODE 体（ENDEL 前全部跳过）
            else:
                field = _ELEM_FIELD_OF.get(rectype)
                if field is None:
                    continue  # 规范可选负载（PLEX/ELFLAGS 等）静默消费
                if field == "layer":
                    elem["layer"] = _rd_int2(payload, warnings, "LAYER")
                elif field in ("datatype", "texttype", "boxtype"):
                    elem[field] = _rd_int2(payload, warnings, field.upper())
                elif field in ("width", "bgnextn", "endextn"):
                    elem[field] = _rd_int4(payload, warnings, field.upper())
                elif field == "pathtype":
                    elem["pathtype"] = _rd_int2(payload, warnings, "PATHTYPE")
                elif field == "presentation":
                    elem["presentation"] = _rd_bitarray(payload, warnings,
                                                        "PRESENTATION")
                elif field == "colrow":
                    if len(payload) == 4:
                        elem["cols"] = int.from_bytes(payload[0:2], "big",
                                                      signed=True)
                        elem["rows"] = int.from_bytes(payload[2:4], "big",
                                                      signed=True)
                    else:
                        _warn(warnings,
                              f"COLROW 负载应 4 字节，实得 {len(payload)}，"
                              "cols/rows 如实置 None")
                elif field == "sname_raw":
                    elem["sname"] = decode_gds_ascii(payload)
                elif field == "string_raw":
                    elem["string"] = decode_gds_ascii(payload)
                elif field == "strans":
                    elem["strans"] = _rd_bitarray(payload, warnings, "STRANS")
                elif field == "mag":
                    elem["mag"] = _rd_real8(payload, warnings, "MAG")
                elif field == "angle":
                    elem["angle"] = _rd_real8(payload, warnings, "ANGLE")
                elif field == "xy":
                    elem["xy"] = _rd_xy(payload, warnings)
                continue

        # ── 非元素区（库层 / 结构声明层）──
        if rectype == HEADER:
            doc["version"] = _rd_int2(payload, warnings, "HEADER")
        elif rectype == LIBNAME:
            doc["lib_name"] = decode_gds_ascii(payload)
        elif rectype == UNITS:
            if len(payload) == 16:
                u0 = decode_gds_real8(payload[0:8])
                u1 = decode_gds_real8(payload[8:16])
                doc["units_raw"] = [u0, u1]
                # 任务书口径：units[0]=数据库单位尺寸（db_um）、
                # units[1]=用户单位（user_um）；标准规范语义（DB in user
                # units / DB in meters）原值双录 units_raw 不失真。
                doc["units"] = {"db_um": u0, "user_um": u1}
            else:
                _warn(warnings,
                      f"UNITS 负载应 16 字节（双 real8），实得 {len(payload)}，"
                      "units 如实置 None")
        elif rectype == ENDLIB:
            if in_structure:
                _warn(warnings,
                      f"结构 {cur_name!r} 缺 ENDSTR 即遇 ENDLIB，"
                      "按截断态收结构")
                in_structure = False
            saw_endlib = True
        elif rectype == BGNSTR:
            if in_structure:
                _warn(warnings,
                      f"结构 {cur_name!r} 缺 ENDSTR 即遇 BGNSTR，按截断态收结构")
                in_structure = False
                cur_struct = None
                cur_name = None
            in_structure = True  # BGNSTR 只带时间戳（12×int2），真名随 STRNAME
        elif rectype == STRNAME:
            name = decode_gds_ascii(payload)
            if not in_structure:
                _warn(warnings, f"STRNAME {name!r} 无前置 BGNSTR（宽容收结构）")
            if elem is not None or skip_node:
                _warn(warnings,
                      "前一结构元素未收口即遇新 STRNAME，按截断态物化")
                _materialize_element(elem_kind or "", elem or {}, cur_struct,
                                     warnings)
                elem = None
                elem_kind = None
                skip_node = False
            cur_name = name
            if name in doc["structures"]:
                _warn(warnings, f"结构重名 {name!r}，元素桶合并（同名字面唯一）")
                cur_struct = doc["structures"][name]
            else:
                cur_struct = _empty_structure()
                doc["structures"][name] = cur_struct
            in_structure = True
        elif rectype in _ELEM_KIND_OF:
            if not in_structure or cur_struct is None:
                _warn(warnings,
                      f"{RECORD_NAMES[rectype]} 出现在结构声明外（无 STRNAME "
                      "领衔），如实丢弃")
                # 启动最小吸收态防字段泄漏到库层（ENDEL 到来时静默清空）
                elem = {}
                elem_kind = _ELEM_KIND_OF[rectype]
                cur_struct = None
                continue
            elem = {}
            elem_kind = _ELEM_KIND_OF[rectype]
        elif rectype in (NODE, TEXTNODE):
            _warn(warnings,
                  f"{RECORD_NAMES[rectype]} 元素本席契约外，跳到 ENDEL"
                  "（如实披露不解析）")
            skip_node = True
        elif rectype in _LIB_MISC_RECORDS:
            continue  # 库层规范杂项（时间戳/带信息等）静默通过
        else:
            _warn(warnings,
                  f"记录 {RECORD_NAMES[rectype]} 出现在非预期区（库层），跳过")

    # 文件尾收尾：未收口面如实登记（截断态）
    if n_records == 0:
        raise GdsiiParseError(
            f"非 GDSII 文件：流首即不可读（偏移 0 处记录头非法，"
            f"文件 {n} 字节）")
    if elem is not None:
        _warn(warnings,
              f"文件尾 {(elem_kind or '?').upper()} 未 ENDEL 收口，按截断态物化")
        _materialize_element(elem_kind or "", elem, cur_struct, warnings)
    if skip_node:
        _warn(warnings, "文件尾 NODE/TEXTNODE 未 ENDEL 收口（截断态）")
    if in_structure:
        _warn(warnings,
              f"文件尾结构 {cur_name!r} 缺 ENDSTR（截断态，已收元素保留）")
    if not saw_endlib and n_records > 0:
        # 合法 GDSII 必以 ENDLIB 终止——干净 EOF 但 ENDLIB 缺失=文件级截断
        _warn(warnings, "文件尾无 ENDLIB（文件级截断，已收面如实保留）")
        truncated = True
    if truncated:
        doc["truncated"] = True

    doc["stats"] = {
        "n_structures": len(doc["structures"]),
        "n_boundaries": sum(
            len(s["boundaries"]) for s in doc["structures"].values()),
        "n_paths": sum(len(s["paths"]) for s in doc["structures"].values()),
        "n_srefs": sum(len(s["srefs"]) for s in doc["structures"].values()),
        "n_arefs": sum(len(s["arefs"]) for s in doc["structures"].values()),
        "n_texts": sum(len(s["texts"]) for s in doc["structures"].values()),
        "n_boxes": sum(len(s["boxes"]) for s in doc["structures"].values()),
        "n_warnings": len(warnings),
    }
    return doc


def parse_gdsii_file(path: str | Path) -> dict[str, Any]:
    """读文件字节并解析（OSError 原样上抛由服务层分型；解析语义同
    :func:`parse_gdsii_bytes`）。"""
    data = Path(path).read_bytes()
    return parse_gdsii_bytes(data)


# ── 拓扑提取 1：层级统计 ────────────────────────────────────────────────────


def gdsii_hierarchy_stats(doc: dict[str, Any]) -> dict[str, Any]:
    """层级统计：逐结构被引用计数 + 未定义引用 + 孤儿/零引用双桶。

    - ``reference_counts``：SREF/AREF 目标统计（键序=结构注册序，确定性）；
    - ``undefined_references``：SNAME 不在 structures 的引用（按名排序，
      带引用次数）；
    - ``orphan_structures``：零引用**且**零元素（任务书严格口径）；
    - ``unreferenced_structures``：零引用（含非空叶/顶层——宁多报口径）。

    双向清单宁多报不误报：两桶都如实给出，消费方按需取用。
    """
    structures = doc.get("structures") or {}
    ref_counts: dict[str, int] = {name: 0 for name in structures}
    undefined: dict[str, int] = {}
    for body in structures.values():
        for bucket in ("srefs", "arefs"):
            for ref in body.get(bucket) or ():
                target = ref.get("sname")
                if target is None:
                    continue
                if target in ref_counts:
                    ref_counts[target] += 1
                else:
                    undefined[target] = undefined.get(target, 0) + 1

    def _n_elements(body: dict[str, list]) -> int:
        return sum(len(body.get(bucket) or ()) for bucket in ELEMENT_BUCKETS)

    orphans = [name for name, body in structures.items()
               if ref_counts[name] == 0 and _n_elements(body) == 0]
    unreferenced = [name for name in structures if ref_counts[name] == 0]
    return {
        "n_structures": len(structures),
        "reference_counts": ref_counts,
        "undefined_references": [
            {"sname": sname, "n_refs": cnt}
            for sname, cnt in sorted(undefined.items())
        ],
        "orphan_structures": sorted(orphans),
        "unreferenced_structures": sorted(unreferenced),
    }


# ── 拓扑提取 2：层汇总 ──────────────────────────────────────────────────────

#: 桶 → (kind 名, 第二键字段名)（text 用 texttype、box 用 boxtype 归并）。
_LAYER_KIND_OF: tuple[tuple[str, str, str], ...] = (
    ("boundaries", "boundary", "datatype"),
    ("paths", "path", "datatype"),
    ("texts", "text", "texttype"),
    ("boxes", "box", "boxtype"),
)


def _points_bbox(points: list[list[int]]) -> tuple[int, int, int, int] | None:
    """点集 → (xmin, ymin, xmax, ymax)；空点集 → None。"""
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def gdsii_layer_summary(doc: dict[str, Any]) -> dict[str, Any]:
    """层汇总：逐 (layer, datatype) 元素计数 + 包围盒（DBU 原值）。

    text 按 texttype、box 按 boxtype 归并进 datatype 位；sref/aref 无层
    语义不入计。输出按 (layer, datatype) 排序（确定性；layer/datatype 为
    None 的病态元素如实落 None 键排尾——``(value is None, value)`` 双键）。
    """
    structures = doc.get("structures") or {}
    agg: dict[tuple[Any, Any], dict[str, Any]] = {}
    for body in structures.values():
        for bucket, kind, dt_field in _LAYER_KIND_OF:
            for el in body.get(bucket) or ():
                layer = el.get("layer")
                dt = el.get(dt_field)
                key = (layer, dt)
                ent = agg.get(key)
                if ent is None:
                    ent = {"layer": layer, "datatype": dt, "n_elements": 0,
                           "by_kind": {}, "_points": []}
                    agg[key] = ent
                ent["n_elements"] += 1
                ent["by_kind"][kind] = ent["by_kind"].get(kind, 0) + 1
                if bucket == "texts":
                    x, y = el.get("x"), el.get("y")
                    if x is not None and y is not None:
                        ent["_points"].append([x, y])
                else:
                    ent["_points"].extend(el.get("points_xy") or [])
    layers: list[dict[str, Any]] = []
    for key in sorted(agg, key=lambda k: (k[0] is None, k[0],
                                          k[1] is None, k[1])):
        ent = agg[key]
        bbox = _points_bbox(ent["_points"])
        layers.append({
            "layer": ent["layer"],
            "datatype": ent["datatype"],
            "n_elements": ent["n_elements"],
            "by_kind": dict(sorted(ent["by_kind"].items())),
            "bbox_dbu": list(bbox) if bbox is not None else None,
        })
    return {"n_layer_keys": len(layers), "layers": layers}


# ── 拓扑提取 3：递归展开包围盒 ──────────────────────────────────────────────


def _xform_corner(x: int, y: int, reflected: bool,
                  angle: float) -> tuple[int, int]:
    """角点精确变换（先反射关于 x 轴、后旋转；仅 0/90/180/270——整数
    坐标全程无浮点）。"""
    if reflected:
        y = -y
    if angle == 90.0:
        return -y, x
    if angle == 180.0:
        return -x, -y
    if angle == 270.0:
        return y, -x
    return x, y


def _xform_bbox(bbox: tuple[int, int, int, int], reflected: bool,
                angle: float) -> tuple[int, int, int, int]:
    """局部包围盒四角精确变换后再取包围盒（平移在调用方叠加）。"""
    x0, y0, x1, y1 = bbox
    xs: list[int] = []
    ys: list[int] = []
    for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        tx, ty = _xform_corner(cx, cy, reflected, angle)
        xs.append(tx)
        ys.append(ty)
    return (min(xs), min(ys), max(xs), max(ys))


def _union_bbox(a: tuple[int, int, int, int] | None,
                b: tuple[int, int, int, int] | None
                ) -> tuple[int, int, int, int] | None:
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]),
            max(a[2], b[2]), max(a[3], b[3]))


def _shift_bbox(bbox: tuple[int, int, int, int],
                dx: int, dy: int) -> tuple[int, int, int, int]:
    return (bbox[0] + dx, bbox[1] + dy, bbox[2] + dx, bbox[3] + dy)


def _local_bbox(doc: dict[str, Any], name: str,
                memo: dict[str, tuple[int, int, int, int] | None],
                stack: tuple[str, ...],
                out: dict[str, Any]) -> tuple[int, int, int, int] | None:
    """结构局部包围盒（含子引用精确展开），memo 化 + 栈式环守卫。

    - 循环引用：warning + 该分支不入盒（截断贡献，已收面如实）；
    - 深度超 :data:`MAX_HIERARCHY_DEPTH`：warning + 该分支不入盒；
    - 任意角度/mag≠1 引用：skip 记 ``out["skipped"]``，不近似展开。
    """
    if name in memo:
        return memo[name]
    if name in stack:
        path = "→".join([*stack, name])
        _warn(out["warnings"], f"循环引用（{path}），该分支不入包围盒")
        memo[name] = None
        return None
    if len(stack) >= MAX_HIERARCHY_DEPTH:
        _warn(out["warnings"],
              f"引用深度超 {MAX_HIERARCHY_DEPTH}（{name}），该分支不入包围盒")
        return None
    body = doc["structures"].get(name)
    if body is None:
        return None
    own_points: list[list[int]] = []
    for bucket in ("boundaries", "paths", "boxes"):
        for el in body.get(bucket) or ():
            own_points.extend(el.get("points_xy") or [])
    for el in body.get("texts") or ():
        x, y = el.get("x"), el.get("y")
        if x is not None and y is not None:
            own_points.append([x, y])
    bbox = _points_bbox(own_points)

    for kind in ("srefs", "arefs"):
        for ref in body.get(kind) or ():
            out["stats"]["n_refs_seen"] += 1
            target = ref.get("sname")
            if target is None:
                out["stats"]["n_refs_skipped"] += 1
                continue
            if target not in doc["structures"]:
                _warn(out["warnings"],
                      f"结构 {name} 引用未定义结构 {target!r}，不入包围盒")
                out["stats"]["n_refs_undefined"] += 1
                continue
            angle = ref["angle"] if ref.get("angle") is not None else 0.0
            mag = ref["mag"] if ref.get("mag") is not None else 1.0
            norm = angle % 360.0
            if norm not in _EXACT_ANGLES or mag != 1.0:
                reason = ("任意角度不精确展开" if norm not in _EXACT_ANGLES
                          else "mag≠1 不近似展开")
                _warn(out["warnings"],
                      f"结构 {name} 引用 {target}（{('sref' if kind == 'srefs' else 'aref')}）"
                      f"angle={angle} mag={mag}：{reason}，不入包围盒")
                out["skipped"].append({
                    "structure": name,
                    "kind": "sref" if kind == "srefs" else "aref",
                    "sname": target,
                    "angle": angle,
                    "mag": mag,
                    "reason": reason,
                })
                out["stats"]["n_refs_skipped"] += 1
                continue
            child = _local_bbox(doc, target, memo, (*stack, name), out)
            if child is None:
                out["stats"]["n_refs_empty"] += 1
                continue
            reflected = bool(ref.get("reflected"))
            tbox = _xform_bbox(child, reflected, norm)
            if kind == "srefs":
                dx = ref["x"] if ref.get("x") is not None else 0
                dy = ref["y"] if ref.get("y") is not None else 0
                bbox = _union_bbox(bbox, _shift_bbox(tbox, dx, dy))
            else:
                # AREF：锚点在父坐标系（STRANS 只作用于被引用内容）。
                # 列/行步进 = (锚点差)/(格数-1)，格位均匀落段上 → 包围盒
                # 只依赖端点，整点端点极值法零除零、零近似。
                cols = ref.get("cols") or 1
                rows = ref.get("rows") or 1
                xy = ref.get("xy") or []
                anchor_xs: list[int] = [xy[0][0]] if len(xy) > 0 else []
                anchor_ys: list[int] = [xy[0][1]] if len(xy) > 0 else []
                if cols > 1 and len(xy) > 1:
                    anchor_xs.append(xy[1][0])
                    anchor_ys.append(xy[1][1])
                if rows > 1 and len(xy) > 2:
                    anchor_xs.append(xy[2][0])
                    anchor_ys.append(xy[2][1])
                if not anchor_xs:
                    out["stats"]["n_refs_empty"] += 1
                    continue
                placed = (tbox[0] + min(anchor_xs), tbox[1] + min(anchor_ys),
                          tbox[2] + max(anchor_xs), tbox[3] + max(anchor_ys))
                bbox = _union_bbox(bbox, placed)
            out["stats"]["n_refs_expanded"] += 1
    memo[name] = bbox
    return bbox


def gdsii_expand_bbox(doc: dict[str, Any], name: str) -> dict[str, Any]:
    """指定结构递归展开包围盒（SREF/AREF 平移/反射/精确旋转；任意角度与
    mag≠1 如实 skip）。

    返回::

        {"name", "bbox_dbu": [xmin, ymin, xmax, ymax]|None,
         "bbox_um": 同形（经 dbu_to_um；UNITS 缺失 → None）,
         "warnings": [...], "skipped_refs": [{structure, kind, sname,
         angle, mag, reason}], "stats": {n_refs_seen, n_refs_expanded,
         n_refs_skipped, n_refs_undefined, n_refs_empty}}

    未知结构名抛 KeyError（可用名录随 message，消费方不猜）。
    """
    structures = doc.get("structures") or {}
    if name not in structures:
        raise KeyError(
            f"结构 {name!r} 不存在（可用: {', '.join(structures) or '无'}）")
    out: dict[str, Any] = {
        "warnings": [],
        "skipped": [],
        "stats": {
            "n_refs_seen": 0, "n_refs_expanded": 0, "n_refs_skipped": 0,
            "n_refs_undefined": 0, "n_refs_empty": 0,
        },
    }
    bbox = _local_bbox(doc, name, {}, (), out)
    bbox_um: list[float] | None = None
    if bbox is not None:
        units = doc.get("units") or {}
        um_vals = [dbu_to_um(v, units) for v in bbox]
        if all(v is not None for v in um_vals):
            bbox_um = [float(v) for v in um_vals]  # type: ignore[arg-type]
    return {
        "name": name,
        "bbox_dbu": list(bbox) if bbox is not None else None,
        "bbox_um": bbox_um,
        "warnings": out["warnings"],
        "skipped_refs": out["skipped"],
        "stats": out["stats"],
    }
