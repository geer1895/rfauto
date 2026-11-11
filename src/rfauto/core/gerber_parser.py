"""Gerber RS-274X 光绘文件结构化解析内核（aurora_q 席位 Q-X59，2026-11-07）。

PCB 制造事实标准 **Gerber RS-274X**（Ucamco Gerber Layer Format Specification，
公开规范口径，与 gerber_overview/gerbonara 等实现公开文档相互印证）的只读
指令级结构化解析：光绘命令词法 + 几何落地面（aperture 闪光/画线/区域多边
形/包络盒）。全部词法与几何语义在 core 确定性内核（铁律 7：结构化数字只
出自数据源文本本身；LLM/agent 永不产生物理数字）。服务包装见
:mod:`rfauto.service.fab_gerber_service`（规则 4 JSON 进出），CLI 薄壳
= cli/fab_app 的 ``fab parse``/``fab summary`` 两叶。

本内核与既有统计级读入口 :mod:`rfauto.service.gerber_overview_service`
（T-Q6 席，"禁写完整解析器"口径下的声明聚合）分工不同：本模块是**指令级
状态机解析**（坐标模态/D-code 模态/插值模式/区域模式全跟踪），两模块零
import 关系（单源各自成立，消费面不同层级）。

词法覆盖面（逐条落地）：

- **语句终止符 ``*``** 与**扩展命令块 ``%...%``**（块内可含多个 ``*``
  分隔字段）；``G04`` 注释到语句 ``*`` 止（整语句收编不计）；
- ``%FSLAX35Y35*%`` 格式说明：零省略 L/T + 记法 A/I + X/Y 各 (整数位,
  小数位)——**坐标定长拆分核心**（无小数点定长数字按 FS 拆分）；
- ``%MOIN*%``/``%MOMM*%`` 单位（IN=英寸→×25.4 换 mm；MO 缺失如实
  units=None，坐标保持原值换算单位不定标）；``%LPD*%``/``%LPC*%`` 极性
  （D 画/C 清，登记如实，不清算叠加）；
- aperture 定义 ``%ADD10R,5.1X2.3*%``/``%ADD11C,1.5*%``/``%ADD12O,...*%``
  /``%ADD13P,...*%``：R 矩形/C 圆/O 长圆/P 正多边形（params 数值拆解）
  + **宏孔径** ``%AMname*1,0,...*%``：宏名登记 + 原语体整块保存
  （``expanded=False`` 如实标记不展开——宏原语求值属出图器职责，本内核
  不做参数代换）；``%ADD`` 引用未登记宏名如实保留 + warning；
- 绘图指令：``G01``/``G02``/``G03`` 线性/顺弧/逆弧（I/J 圆心偏移）；
  ``D01`` 画线/``D02`` 移动/``D03`` 闪光（aperture stamp）；``G54Dxx``
  选刀前缀兼容（历史 RS-274D 惯语）；D-code 选择 ``D10``+（模态保持）；
- ``G36``/``G37`` 区域模式开/关：区域内 ``D01`` 路径收集=铜多边形
  （``paths`` 外环列表；内环/挖孔不做布尔运算，如实逐环记录 + 极性）；
- ``M02``/``M00`` 结束（其后残余语句 warning 如实忽略）；
- ``G04``/``%`` 注释、``G90``/``G91``（RS-274X 恒绝对坐标，出现时登记
  warning 不改语义）、``G70``/``G71``/``G74``/``G75``（单位/象限模式
  惯语，登记如实）。

坐标语义（公开规范逐条落地）：

- **FS 定长拆分**：``FSLAX35Y35`` 下坐标词 ``X0012345`` → 整数 12345
  → ÷10^5 → 0.12345 文件单位；无小数点（RS-274X 禁小数点，历史文件
  有则 warning + 按浮点直读 fail-soft）；L=前导零省略/T=尾随零省略
  （数字按整数读后定标，L/T 两种写法同值——拆分算法与零省略模式无关，
  零省略只影响"缺位补零方向"，整数值恒为字面量整值）；I/J 同 X/Y 拆分；
- **缺省模态**：坐标词只给 X 或只给 Y 时，缺轴沿用上次当前点值（规范
  定义的模态续用，如实遵循）；未给任何坐标词的 ``D01``（纯 D 码重复）
  画零长段（当前点→当前点）如实记录；
- **单位换算**：``MOMM`` 原值即 mm；``MOIN`` ×25.4 → mm（输出统一
  ``x_mm``/``y_mm``）；MO 缺失时 ``_mm`` 键如实 None（单位不明不猜，
  gerber_overview #316 兜底方向同款——多报不冒充）。

几何落地面（任务书口径）：

- ``flashes``：D03 闪光点表 ``{dcode, x_mm, y_mm}``；
- ``draws``：D01 画线表 ``{dcode, from: [x,y], to: [x,y], interpolation}``
  （linear/cw_arc/ccw_arc）；弧段 I/J 相对圆心偏移原值记录（不展开弧
  中间点）；
- ``regions``：G36..G37 之间 D01 路径收集 ``{paths: [[(x,y)...]],
  polarity}``（区域当前点起始，逐环闭合判定不强制——开放环如实保留）；
- ``outline_bbox_mm``：全部元素（flash 点/画线端点/区域顶点）端点包络
  盒——**弧段 endpoint-only**（弧鼓出不经 I/J 精确展开，如实标注
  ``bbox_mode="endpoint-only"``，宁近似不报错值）；无任何几何元素时
  bbox=None；
- :func:`gerber_layer_summary`：按 D-code 分组元素计数 + 每 aperture
  类型统计（消费面=层摘要）；
- :func:`gerber_bbox`：包络盒独立消费函数（含 ``endpoint-only`` 限定
  声明）。

fail-soft 口径（citi_parser/gdsii_parser 家法）：单条命令词法/语义违规
→ warning + 跳过该条，已收面如实保留；``truncated=True`` 标记（未遇
M02 即流尾）；FS 缺失时的坐标词（无法定标）→ warning + 整数原值如实
保留（``_mm`` 置 None）；未知扩展命令（``%TF/%TA/%TD`` X2 属性族、
``%SR`` 步骤重复、``%IN/%IP/%AS`` 等）→ 计数登记不猜语义。文件级错误
（空文件/不像 Gerber——无任何 FS/MO/ADD/D 指令）→
:class:`GerberParseError`（服务层转 error 信封）。

确定性（同输入同输出）、零 IO 消费面（文本进 dict 出）、零第三方依赖。
本模块不设 ``__all__``（无 __all__ 文件不进 tests/gold/public_api.json
——verilog_netlist_parser/gdsii_parser 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: aperture 基本模板名（R/C/O/P；宏名引用不在表内）。
STANDARD_TEMPLATES = ("C", "R", "O", "P")

#: 插值模式 → 记录名（draws/regions 路径段消费面）。
INTERPOLATION_LINEAR = "linear"
INTERPOLATION_CW_ARC = "cw_arc"
INTERPOLATION_CCW_ARC = "ccw_arc"

#: INCH → mm 换算系数（规范定义 1 inch = 25.4 mm，精确十进制）。
INCH_TO_MM = 25.4


class GerberParseError(ValueError):
    """Gerber 文件级错误（空/不像 RS-274X——区别于流中逐条 fail-soft）。"""


# ── 词法正则（RS-274X 规范词法即大写；容错收小写短语按 warning 降级） ────────

#: 扩展命令块 ``%...%``（含 DOTALL——宏体可跨行）。
_EXT_BLOCK_RE = re.compile(r"%([^%]*)%", re.DOTALL)
#: FS 格式说明：FS + 零省略(L/T) + 记法(A/I) + X(int)(dec) + Y(int)(dec)。
_FS_RE = re.compile(r"^FS([LT])([AI])X(\d)(\d)Y(\d)(\d)$")
#: MO 单位：MO + MM/IN。
_MO_RE = re.compile(r"^MO(MM|IN)$")
#: LP 极性：LP + D/C。
_LP_RE = re.compile(r"^LP([DC])$")
#: ADD aperture 定义：D 码（≥10）+ 模板名（C/R/O/P 或宏名）+ 逗号参数。
_ADD_RE = re.compile(r"^ADD(\d+)([A-Za-z0-9_.$\-]+)(?:,(.*))?$")
#: AM 宏定义首字段：AM + 宏名。
_AM_RE = re.compile(r"^AM([A-Za-z0-9_.$\-]+)$")
#: 体指令坐标词串（X/Y/I/J + 符号整数；含无坐标纯 G/M/D 形态）。
_COORD_WORDS_RE = re.compile(r"([XYIJ])([+-]?\d+(?:\.\d+)?)")
#: 体指令尾部 D 码（语句已按 ``*`` 分割、尾部无终止符；D01/02/03 可缩写
#: D1/D2/D3；D≥10 选刀；G54Dxx 前缀兼容）。
_TRAIL_D_RE = re.compile(r"D0*(\d+)$")
#: 前导 G 码词（G01/G02/G03/G36/G37/G54/G70/G71/G74/G75/G90/G91/G04）。
_G_WORD_RE = re.compile(r"G(\d+)")
#: M 码词（M00/M02）。
_M_WORD_RE = re.compile(r"M(\d+)")


def _warn(warnings: list[str], message: str) -> None:
    """warning 同文去重追加（逐条披露不改据；gdsii_parser 同款）。"""
    if message not in warnings:
        warnings.append(message)


# ── FS 与坐标定长拆分（表驱动核心）────────────────────────────────────────


class FormatSpec:
    """FS 格式说明（坐标定长拆分表）。

    ``FSLAX35Y35`` → zero_omission="L"、notation="A"、x=(3,5)、y=(3,5)。
    非法（dec>9/int+dec>13 超规范上限等）在 :func:`parse_format_spec`
    fail-soft 返回 None 不抛（文件级继续，坐标词逐条 warning）。
    """

    __slots__ = ("notation", "x_dec", "x_int", "y_dec", "y_int", "zero_omission")

    def __init__(self, zero_omission: str, notation: str,
                 x_int: int, x_dec: int, y_int: int, y_dec: int) -> None:
        self.zero_omission = zero_omission
        self.notation = notation
        self.x_int = x_int
        self.x_dec = x_dec
        self.y_int = y_int
        self.y_dec = y_dec

    def decimals_for(self, axis: str) -> int:
        """轴 → 小数位（坐标拆分定标表；轴外轴如实取 x 位表）。"""
        return self.x_dec if axis != "Y" else self.y_dec

    def as_dict(self) -> dict[str, Any]:
        """结构化落键（zero_omission/notation/x/y=[int,dec]）。"""
        return {
            "zero_omission": self.zero_omission,
            "notation": self.notation,
            "x": [self.x_int, self.x_dec],
            "y": [self.y_int, self.y_dec],
        }


def parse_format_spec(field: str) -> FormatSpec | None:
    """``FSLAX35Y35`` 词 → :class:`FormatSpec`；非法形态 fail-soft None。

    规范上限：整数/小数位各一位数字（1-9）；小数位 0=非法（坐标无法
    定标）；int+dec>13（Ucamco 规范 5.6.1 数字总数上限 13+符号）=非法。
    """
    m = _FS_RE.match(field)
    if m is None:
        return None
    xi, xd, yi, yd = (int(m.group(3)), int(m.group(4)),
                      int(m.group(5)), int(m.group(6)))
    if xd == 0 or yd == 0:
        return None
    if xi + xd > 13 or yi + yd > 13:
        return None
    if xi == 0 or yi == 0:
        return None
    return FormatSpec(m.group(1), m.group(2), xi, xd, yi, yd)


def split_fs_number(raw: str, decimals: int) -> Fraction | None:
    """FS 定长坐标数字 → 精确文件单位值（Fraction，零浮点早损）。

    ``FSLAX35Y35`` + ``"0012345"`` → 12345/10^5 = 0.12345（表驱动已知量
    断言家法 #118：解码器先对已知量验证——tests 钉同表）。无小数点定长
    数字按 FS 拆分：整数值 = 字面量整值（L/T 零省略只影响缺位补零方向，
    出现在文件里的数字本身恒完整）、定标 = ÷10^decimals。带小数点的
    历史/异端形态按浮点直读（warning 由调用方配）。非法字面量如实 None。
    """
    if not raw:
        return None
    if "." in raw:
        try:
            return Fraction(raw)
        except (ValueError, ZeroDivisionError):
            return None
    if not re.fullmatch(r"[+-]?\d+", raw):
        return None
    return Fraction(int(raw), 10 ** decimals)


class _UnitConv:
    """文件单位 → mm 换算（MO 已知=MOMM 恒等/MOIN ×25.4；缺失=不定标）。"""

    def __init__(self, units: str | None) -> None:
        self.units = units
        self._factor: Fraction | None
        if units == "MM":
            self._factor = Fraction(1)
        elif units == "IN":
            self._factor = Fraction(127, 5)  # 25.4 精确十进制
        else:
            self._factor = None

    def to_mm(self, value_unit: Fraction | None) -> float | None:
        """文件单位值 → mm；单位未知/入参 None 如实 None（不猜）。"""
        if value_unit is None or self._factor is None:
            return None
        return round(float(value_unit * self._factor), 9)

    def _pair_mm(self, x: Fraction | None,
                 y: Fraction | None) -> list[float | None]:
        """(x, y) 文件单位 → [x_mm, y_mm]（区域路径消费面）。"""
        return [self.to_mm(x), self.to_mm(y)]


def _parse_aperture_params(template: str, params_raw: str,
                           warnings: list[str]) -> dict[str, Any]:
    """``%ADD`` 参数串 → 数值拆解 dict（float 逐个；坏参 warning 保留原文）。"""
    out: dict[str, Any] = {"raw": params_raw}
    if not params_raw:
        return out
    parts = params_raw.split("X")
    nums: list[float] = []
    ok = True
    for p in parts:
        try:
            nums.append(float(p))
        except ValueError:
            ok = False
            _warn(warnings, f"aperture D{template} 参数 {p!r} 非数值，原样保留")
            break
    if ok:
        out["values"] = nums
        if template == "C" and len(nums) >= 1:
            out["diameter"] = nums[0]
            out["hole"] = nums[1] if len(nums) > 1 else None
        elif template in ("R", "O") and len(nums) >= 2:
            out["width"] = nums[0]
            out["height"] = nums[1]
            out["hole"] = nums[2] if len(nums) > 2 else None
        elif template == "P" and len(nums) >= 1:
            out["outer_diameter"] = nums[0]
            out["vertices"] = nums[1] if len(nums) > 1 else None
            out["rotation"] = nums[2] if len(nums) > 2 else None
    return out


# ── 主解析状态机 ──────────────────────────────────────────────────────────


def parse_gerber(text: str) -> dict[str, Any]:
    """Gerber RS-274X 文本 → 结构化文档（确定性、零 IO、fail-soft warnings）。

    Returns:
        doc：``{"schema", "units", "format_spec", "apertures",
        "macros", "flashes", "draws", "regions", "outline_bbox_mm",
        "polarity_current", "stats", "truncated", "warnings",
        "unknown_extended"}``（schema 见模块 docstring）。

    Raises:
        GerberParseError: 空文本或不像 RS-274X（无 FS/MO/ADD/AM/宏/D 指令
        任何指纹）——文件级错误，区别于流中逐条 fail-soft。
    """
    warnings: list[str] = []
    unknown_extended: dict[str, int] = {}

    units: str | None = None
    fs: FormatSpec | None = None
    apertures: dict[int, dict[str, Any]] = {}
    macros: dict[str, dict[str, Any]] = {}
    flashes: list[dict[str, Any]] = []
    draws: list[dict[str, Any]] = []
    regions: list[dict[str, Any]] = []
    polarity_current: str | None = None

    # 体状态（模态续用单源）
    conv = _UnitConv(None)
    cur_x: Fraction | None = None
    cur_y: Fraction | None = None
    interpolation: str = INTERPOLATION_LINEAR
    current_dcode: int | None = None
    in_region = False
    region: dict[str, Any] | None = None
    region_path: list[tuple[Fraction, Fraction]] = []
    truncated = True

    saw_any_fingerprint = False

    def _xy_from_words(words: dict[str, str]) -> tuple[Fraction | None, Fraction | None]:
        """坐标词 + 模态续用 → (x, y) 文件单位 Fraction（FS 缺失 None 面）。"""
        nonlocal cur_x, cur_y
        x = cur_x
        y = cur_y
        for axis in ("X", "Y"):
            if axis not in words:
                continue
            if fs is None:
                _warn(warnings, "FS 格式说明缺失，坐标词无法定标（原值保留）")
                val: Fraction | None = None
            else:
                val = split_fs_number(words[axis], fs.decimals_for(axis))
                if val is None:
                    _warn(warnings, f"坐标词 {axis}{words[axis]} 非法定长数字，跳过该轴")
            if axis == "X":
                x = val
            else:
                y = val
        return x, y

    def _to_pair(x: Fraction | None, y: Fraction | None) -> list[float | None]:
        """(Fraction, Fraction) → [x_mm, y_mm]（单位未知/缺轴如实 None）。"""
        return [conv.to_mm(x), conv.to_mm(y)]

    def _bbox_points_iter():
        """全部几何端点产出（flash/draw/region；弧段 endpoint-only 声明面）。"""
        for f in flashes:
            if f["x_mm"] is not None and f["y_mm"] is not None:
                yield f["x_mm"], f["y_mm"]
        for d in draws:
            for pt in (d["from"], d["to"]):
                if pt[0] is not None and pt[1] is not None:
                    yield pt[0], pt[1]
        for r in regions:
            for path in r["paths"]:
                for pt in path:
                    if pt[0] is not None and pt[1] is not None:
                        yield pt[0], pt[1]

    # ── 第一遍：扩展块收割（FS/MO/LP/ADD/AM；AM 宏体整块收编） ────────────
    body_parts: list[str] = []
    pos = 0
    for m in _EXT_BLOCK_RE.finditer(text):
        body_parts.append(text[pos:m.start()])
        pos = m.end()
        fields = [f for f in m.group(1).split("*")]
        idx = 0
        while idx < len(fields):
            fld = fields[idx].strip()
            idx += 1
            if not fld:
                continue
            saw_any_fingerprint = True
            if fld.startswith("AM"):
                am = _AM_RE.match(fld)
                if am is None:
                    _warn(warnings, f"扩展命令 {fld!r} 非 AM 宏形态，跳过")
                    continue
                # 宏原语体=剩余字段整块保存（跨 "%" 边界的宏体按规范不会
                # 出现；字段序保持原样，expanded=False 不展开）
                body_raw = "*".join(fields[idx:])
                idx = len(fields)
                macros[am.group(1)] = {
                    "name": am.group(1),
                    "body_raw": body_raw,
                    "expanded": False,
                }
                continue
            fm = _FS_RE.match(fld)
            if fm is not None:
                spec = parse_format_spec(fld)
                if spec is None:
                    _warn(warnings, f"FS 格式说明 {fld!r} 超规范上限，fail-soft 忽略")
                else:
                    fs = spec
                    saw_any_fingerprint = True
                continue
            if _MO_RE.match(fld):
                units = fld[2:]
                conv = _UnitConv(units)
                continue
            lp = _LP_RE.match(fld)
            if lp:
                polarity_current = lp.group(1)
                continue
            ad = _ADD_RE.match(fld)
            if ad:
                dcode = int(ad.group(1))
                if dcode < 10:
                    _warn(warnings, f"ADD D 码 {dcode} <10 非规范（保留登记）")
                template = ad.group(2)
                entry: dict[str, Any] = {
                    "dcode": dcode,
                    "shape": template,
                    "params": _parse_aperture_params(template,
                                                     ad.group(3) or "",
                                                     warnings),
                }
                if template not in STANDARD_TEMPLATES:
                    # 宏引用：登记引用名；未登记宏名 warning（定义可后置）
                    entry["macro"] = template
                    if template not in macros:
                        _warn(warnings,
                              f"ADD D{dcode} 引用宏 {template} 未在本文件定义")
                apertures[dcode] = entry
                continue
            # X2 属性（TF/TA/TD/TD）与 SR/IP/AS/IN 等扩展：计数登记不猜语义
            key = fld.split(",")[0][:2] if fld[:2] in (
                "TF", "TA", "TD", "SR", "IN", "IP", "AS", "IR", "MI",
                "OF", "SF", "LM", "LR", "LS") else fld.split(",")[0]
            unknown_extended[key] = unknown_extended.get(key, 0) + 1
    body_parts.append(text[pos:])
    body = "".join(body_parts)

    # ── 第二遍：体指令状态机（``*`` 逐语句推进） ─────────────────────────
    for stmt_raw in body.split("*"):
        stmt = stmt_raw.strip()
        if not stmt:
            continue
        # G04 注释：整语句收编（内容不计）
        if stmt.upper().startswith("G04"):
            continue
        saw_any_fingerprint = saw_any_fingerprint or bool(
            _G_WORD_RE.search(stmt) or _M_WORD_RE.search(stmt)
            or _TRAIL_D_RE.search(stmt))

        words = dict(_COORD_WORDS_RE.findall(stmt))
        has_coords = bool(words)

        # G 码面（G54 前缀历史惯语兼容；G01/02/03 插值模态；G36/37 区域）
        g_codes = [int(g) for g in _G_WORD_RE.findall(stmt)]
        g_effective = [g for g in g_codes if g != 54]
        for g in g_effective:
            if g in (1,):
                interpolation = INTERPOLATION_LINEAR
            elif g == 2:
                interpolation = INTERPOLATION_CW_ARC
            elif g == 3:
                interpolation = INTERPOLATION_CCW_ARC
            elif g == 36:
                if in_region:
                    _warn(warnings, "G36 嵌套 G36（上一区域未 G37 收口），如实开新区域")
                    _close_region(regions, region, region_path, warnings, conv)
                region = {"polarity": polarity_current or "D"}
                region_path = []
                in_region = True
            elif g == 37:
                if not in_region:
                    _warn(warnings, "G37 无在制 G36 区域，忽略")
                else:
                    _close_region(regions, region, region_path, warnings, conv)
                    region = None
                    region_path = []
                    in_region = False
            elif g in (70, 71):
                _warn(warnings, f"G{g} 单位选择惯语（RS-274X 单位只由 %MO% 定），登记忽略")
            elif g in (74, 75):
                _warn(warnings, f"G{g} 象限模式惯语（弧段只记端点不展开），登记忽略")
            elif g in (90, 91):
                _warn(warnings, f"G{g} 坐标模式惯语（RS-274X 恒绝对坐标），登记忽略")

        # M 码面
        m_codes = [int(mm) for mm in _M_WORD_RE.findall(stmt)]
        if any(mm in (0, 2) for mm in m_codes):
            truncated = False
            break  # M02/M00 后残余忽略（如规范）

        # 尾部 D 码（D01/D02/D03 + D≥10 选刀）
        dm = _TRAIL_D_RE.search(stmt)
        dcode_op: int | None = None
        is_select = False
        if dm:
            d = int(dm.group(1))
            if d in (1, 2, 3):
                dcode_op = d
            elif d >= 10:
                current_dcode = d
                is_select = True
            else:
                _warn(warnings, f"D{d} 保留码不在 01/02/03/≥10 语义面，忽略")

        if dcode_op is None and not is_select and not g_effective \
                and not has_coords:
            # 纯未知体语句（无 D 无 G 无坐标）
            _warn(warnings, f"未识别体语句 {stmt[:40]!r}，跳过")
            continue

        # 坐标解析（模态续用；前点捕获先于移动——坐标词=本语句目标点，
        # D01 起点=移动前的当前点，规范语义）
        prev_x: Fraction | None = cur_x
        prev_y: Fraction | None = cur_y
        if has_coords:
            x, y = _xy_from_words(words)
            if x is not None:
                cur_x = x
            if y is not None:
                cur_y = y
            i_off = split_fs_number(words["I"], fs.x_dec) if (
                fs is not None and "I" in words) else None
            j_off = split_fs_number(words["J"], fs.y_dec) if (
                fs is not None and "J" in words) else None
            if "I" in words and fs is None:
                _warn(warnings, "FS 缺失，I 偏移量无法定标")
            if "J" in words and fs is None:
                _warn(warnings, "FS 缺失，J 偏移量无法定标")
        else:
            i_off = None
            j_off = None

        if in_region and dcode_op == 1:
            # 区域路径段收集（目标点入环；D02 切环见下）
            region_path.append((cur_x, cur_y))
            continue

        if dcode_op == 2:
            # D02 移动：当前点已更新；区域模式下=新环起点（切环物化+新环
            # 以本点为起始顶点——闭合轮廓首顶点如规范入环）
            if in_region:
                assert region is not None
                if region_path:
                    _close_region_path(region, region_path, conv)
                    region_path = []
                region_path.append((cur_x, cur_y))
            continue

        if dcode_op == 3:
            flashes.append({
                "dcode": current_dcode,
                "x_mm": conv.to_mm(cur_x),
                "y_mm": conv.to_mm(cur_y),
            })
            continue

        if dcode_op == 1:
            draws.append({
                "dcode": current_dcode,
                "from": [conv.to_mm(prev_x), conv.to_mm(prev_y)],
                "to": [conv.to_mm(cur_x), conv.to_mm(cur_y)],
                "interpolation": interpolation,
                "i_mm": conv.to_mm(i_off),
                "j_mm": conv.to_mm(j_off),
            })
            continue

    if in_region:
        _warn(warnings, "流尾 G36 区域未 G37 收口，按截断态物化")
        _close_region(regions, region, region_path, warnings, conv)
        truncated = True

    if not saw_any_fingerprint:
        raise GerberParseError(
            "不像 RS-274X Gerber 文件（无 FS/MO/ADD/AM 扩展命令也无 G/M/D 体指令）")

    # ── 几何落地面：端点包络盒（弧段 endpoint-only 如实声明） ─────────────
    pts = list(_bbox_points_iter())
    if pts:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        outline_bbox = [min(xs), min(ys), max(xs), max(ys)]
    else:
        outline_bbox = None

    stats = {
        "n_flashes": len(flashes),
        "n_draws": len(draws),
        "n_regions": len(regions),
        "n_apertures": len(apertures),
        "n_macros_unexpanded": sum(
            1 for mm in macros.values() if not mm["expanded"]),
        "n_warnings": len(warnings),
    }

    return {
        # 自描述键统一口径（R-22 schema 升位批）：``"<域>/<N.0>"`` 复合键。
        "schema": f"gerber/{PARSER_SCHEMA_VERSION}",
        "units": units,
        "format_spec": fs.as_dict() if fs is not None else None,
        "apertures": {str(k): v for k, v in apertures.items()},
        "macros": macros,
        "flashes": flashes,
        "draws": draws,
        "regions": regions,
        "outline_bbox_mm": outline_bbox,
        "bbox_mode": "endpoint-only" if outline_bbox is not None else None,
        "polarity_current": polarity_current,
        "stats": stats,
        "truncated": truncated,
        "warnings": warnings,
        "unknown_extended": unknown_extended,
    }


def _close_region_path(region: dict[str, Any],
                       path: list[tuple[Fraction | None, Fraction | None]],
                       conv: _UnitConv) -> None:
    """在制区域单环物化（path → mm 对列表入 region["paths"]）。"""
    region.setdefault("paths", []).append(
        [conv._pair_mm(px, py) for px, py in path])


def _close_region(regions: list[dict[str, Any]],
                  region: dict[str, Any] | None,
                  path: list[tuple[Fraction | None, Fraction | None]],
                  warnings: list[str],
                  conv: _UnitConv) -> None:
    """在制区域收口物化（开放环如实保留；空环 warning 如实披露）。"""
    if region is None:
        return
    _close_region_path(region, path, conv)
    if not region["paths"][-1]:
        _warn(warnings, "区域环零路径段（G36..G37 间无 D01），空环如实保留")
    regions.append(region)


# ── 几何落地面（消费函数）─────────────────────────────────────────────────


def gerber_bbox(doc: dict[str, Any]) -> dict[str, Any]:
    """Gerber 文档 → 包络盒消费面（含 endpoint-only 限定声明）。

    Returns:
        ``{"bbox_mm": [xmin, ymin, xmax, ymax] | None, "mode":
        "endpoint-only"|None, "n_points"}``——``bbox_mm`` 复用
        ``outline_bbox_mm`` 单源（弧鼓出不做 I/J 精确展开，宁近似不报
        错值；声明随 mode 键恒在）。
    """
    bbox = doc.get("outline_bbox_mm")
    return {
        "bbox_mm": list(bbox) if bbox is not None else None,
        "mode": doc.get("bbox_mode"),
        "n_points": (doc.get("stats", {}).get("n_flashes", 0)
                     + doc.get("stats", {}).get("n_draws", 0)
                     + sum(len(p) for r in doc.get("regions") or []
                           for p in r.get("paths") or [])),
    }


def gerber_layer_summary(doc: dict[str, Any]) -> dict[str, Any]:
    """Gerber 文档 → 层摘要（按 D-code 分组元素计数 + aperture 类型统计）。

    Returns:
        ``{"per_dcode": {dcode: {n_flashes, n_draws}}, "per_shape":
        {shape: n_apertures}, "n_dcodes_used", "undefined_dcodes":
        [闪光/画线用到但未 %ADD% 定义的 D 码...]（如实多报）}``。
    """
    per_dcode: dict[int, dict[str, int]] = {}
    for f in doc.get("flashes") or []:
        dc = f.get("dcode")
        entry = per_dcode.setdefault(dc, {"n_flashes": 0, "n_draws": 0})
        entry["n_flashes"] += 1
    for d in doc.get("draws") or []:
        dc = d.get("dcode")
        entry = per_dcode.setdefault(dc, {"n_flashes": 0, "n_draws": 0})
        entry["n_draws"] += 1

    per_shape: dict[str, int] = {}
    for ap in (doc.get("apertures") or {}).values():
        shape = str(ap.get("shape"))
        per_shape[shape] = per_shape.get(shape, 0) + 1

    undefined = sorted({dc for dc in per_dcode
                        if dc is not None and str(dc) not in (doc.get("apertures") or {})})

    return {
        "per_dcode": {str(k): v for k, v in sorted(
            per_dcode.items(), key=lambda kv: (kv[0] is None, kv[0]))},
        "per_shape": dict(sorted(per_shape.items())),
        "n_dcodes_used": len(per_dcode),
        "undefined_dcodes": [str(d) for d in undefined],
    }


def arc_chord_warning(doc: dict[str, Any]) -> list[str]:
    """弧段 endpoint-only 近似如实披露清单（消费面提示，非错误）。"""
    n_arcs = sum(1 for d in doc.get("draws") or []
                 if d.get("interpolation") in (INTERPOLATION_CW_ARC,
                                               INTERPOLATION_CCW_ARC))
    if not n_arcs:
        return []
    return [f"{n_arcs} 条弧段按端点计入 bbox（I/J 圆心鼓出未展开，"
            f"mode=endpoint-only）"]
