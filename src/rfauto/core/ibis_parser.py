"""IBIS（Input/Output Buffer Information Specification）结构化解析内核
（aurora_q Q-X46，2026-11-07）。

数字 IO buffer 行业标准格式（IBIS Open Forum，v3.2/v4.x 经典节面）的
只读结构化解析——RF/模拟用户在信号完整性（SI）设计中读取 IBIS 模型的
单源入口。解析纯函数+IV 查找表（Voltage→Current）+暂态表（time→voltage）
+线性插值全部在 core 确定性内核（铁律 7：数字只出自数据源与本内核的
声明式公式；LLM/agent 永不产生物理数字）。服务包装见
:mod:`rfauto.service.ibis_service`（规则 4 JSON 进出），CLI 薄壳见
cli/domains/ibis.py。

解析面（任务书契约）：

- 头部 keyword：[IBIS Ver]/[File Name]/[File Rev]/[Date]/[Source]
  （单行 keyword+参数值）；
- 器件面：[Component]/[Manufacturer]/[Package]（R_pkg/L_pkg/C_pkg
  typ-min-max 三列）/[Pin]（pin signal model R_pin L_pin C_pin，
  GND/VDD/NC 行=无模型两列形态）；
- 模型面：[Model Selector]（模型清单+注释）/[Model]（Model_type/
  Polarity/Enable/Vinl/Vinh/Vmeas/C_comp/Voltage_range/*_reference 等
  子参数行，``key = value`` 与三列 typ-min-max 两形态）；
- 查找表：[Pullup]/[Pulldown]/[GND Clamp]/[POWER Clamp]（Voltage+
  I(typ)/I(min)/I(max)）+[Ramp]（Ramp_load/Ramp_dR/Ramp_dF）+
  [Rising Waveform]/[Falling Waveform]（R_dut/C_dut/L_dut/V_fixture*
  元参数+time+V(typ)/V(min)/V(max)）；
- [End] 必须收尾（其后内容报错；缺失报错——ibischk 同口径）。

行语法（IBIS v4.2 §3.1）：``|`` 起注释至行尾（行中任何位置）；
keyword 形如 ``[Name] args...``（keyword 名大小写不敏感）；数据行按
当前 mode 分派。数量词法=数字+可选单位后缀，一律换算基准单位
（V/A/Ohm/H/F/s/Hz）：V/mV/uV/kV、A/mA/uA/ka、Ohm/kOhm/mOhm、
H/nH/uH/mH/pH、F/pF/nF/uF/fF、s/ms/us/ns/ps、Hz/kHz/MHz/GHz、裸 SI
前缀（k/m/u/n/p/f——IBIS 时间惯用 "10.0n" 写法）与 "X/Y" 比值形态
（Ramp_dR "-2.228/V" 家族，量值直通）；未知后缀报错（宁红不猜）。
裸 "f" 取 SI 前缀 femto（法拉在 IBIS 惯例恒带词根 pF/uF/nF/fF，
裸 F 形态不存在——如实记录口径）。

结构化输出（:func:`extract_ibis`）::

    {"header": {ibis_ver, file_name, file_rev, date, source,
                manufacturer?},          # 仅文件级 Manufacturer 落头
     "components": [{name, line, manufacturer, package, pins}],
     "models": {name: {model_type, polarity, enable, vinl, vinh, ...,
                       references, attrs, tables, ramp, waveforms}},
     "model_selectors": {name: [{model, comment}]},
     "pins": {pin: record},   # 跨器件扁平视图（单器件=器件 pins 原样；
                              # 多器件同号 pin 后者覆盖——多器件文件以
                              # components[].pins 为准，扁平视图仅便查）
     "warnings": [...]}

多 component 文件：[Component] 之后出现的 [Package]/[Pin] 归属当前
器件（IBIS 多器件惯例）；[Model]/[Model Selector] 为文件级（挂顶层
字典，不回填器件归属——如实声明）。未识别 keyword → warning+内容
忽略（真实供应商文件含大量超范围 keyword——[Diff Pin]/[Die]/[Pin
Mapping] 等，宁降级不炸；#122 族诚实语义：warning 如实回显，零静默
丢弃）。表内列数不一致/行残缺 → 报错；空表（零数据行）→ warning。

插值：:func:`interp_iv`（Voltage→Current）与 :func:`interp_waveform`
（time→voltage）线性插值+边界夹取，x 轴要求严格递增（spec 表序），
corner 可选 typ/min/max 列，缺列如实 ValueError。

错误：语法/结构违规抛 :class:`IbisParseError`（ValueError 子类，带
行号文本）——服务层转 error 信封，CLI exit 1。零 IO（纯文本进出）、
零依赖、确定性（同输入同输出）。不设 ``__all__``（无 __all__ 的非门
面文件不进 tests/gold/public_api.json——liberty_parser 同款先例，新
模块零金快照漂移）。
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

#: [Model] 内四张 IV 查找表标准键（结构化输出 schema 钉）
IV_TABLE_KINDS = ("pullup", "pulldown", "gnd_clamp", "power_clamp")

#: 暂态表方向键
WAVEFORM_KINDS = ("rising", "falling")

#: 暂态表必填 fixture 元参数（缺一报错——spec [Rising/Falling Waveform] 面）
WAVEFORM_REQUIRED_META = ("r_dut", "c_dut", "l_dut", "v_fixture")

#: [Model] 子参数中提升为结构化字段的标量键（attrs 仅存其余未识别面）
_PROMOTED_SCALARS = (
    "model_type", "polarity", "enable",
    "vinl", "vinh", "vmeas", "vref", "rref", "cref",
)

#: 提升为结构化字段的 typ-min-max 三列键
_PROMOTED_TRIPLES = ("c_comp", "voltage_range", "temperature_range")

_PROMOTED = _PROMOTED_SCALARS + _PROMOTED_TRIPLES

#: 单行头部 keyword → header 键
_HEADER_KEYWORDS = {
    "IBIS VER": "ibis_ver",
    "FILE NAME": "file_name",
    "FILE REV": "file_rev",
    "DATE": "date",
    "SOURCE": "source",
}

#: IV 查找表 keyword（keyword 名大小写不敏感）→ 表键
_IV_KEYWORDS = {
    "PULLUP": "pullup",
    "PULLDOWN": "pulldown",
    "GND CLAMP": "gnd_clamp",
    "POWER CLAMP": "power_clamp",
}

# 单位后缀 → 基准单位乘子（key 一律小写；裸单字母=SI 前缀口径见 docstring）
_UNIT_MULT: dict[str, float] = {
    "": 1.0,
    "v": 1.0, "mv": 1e-3, "uv": 1e-6, "kv": 1e3,
    "a": 1.0, "ma": 1e-3, "ua": 1e-6, "ka": 1e3,
    "ohm": 1.0, "ohms": 1.0, "kohm": 1e3, "kohms": 1e3, "mohm": 1e-3,
    "h": 1.0, "nh": 1e-9, "uh": 1e-6, "mh": 1e-3, "ph": 1e-12,
    "f": 1e-15, "ff": 1e-15, "pf": 1e-12, "nf": 1e-9, "uf": 1e-6,
    "s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12,
    "hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9,
    "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12,
}

#: 数量词法：数字（含科学计数）+ 可选后缀（后缀可含空格分隔如 "50 Ohm"）
_QTY_RE = re.compile(
    r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([^\s]*)$")
#: 比值形态后缀（"-2.228/V" 家族）→ 量值直通（乘子 1.0）
_RATIO_SUFFIX_RE = re.compile(r"^/[a-z]+$")
#: keyword 行：``[Name] args...``
_KEYWORD_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


class IbisParseError(ValueError):
    """IBIS 语法/结构/查找表违规（ValueError 子类，带行号文本）。"""


#: 解析输出 schema 版本（键集/字段形状变更时升位）。解析产物为解析树
# （非 dict），自描述键由 service 信封携带（skill_service 同款先例）。
PARSER_SCHEMA_VERSION = "1.0"


# ─── 数量词法（数字+单位后缀）───────────────────────────────────────────────


def parse_quantity(token: str, where: str) -> float:
    """IBIS 数量词（数字+单位后缀）→ 基准单位 float（V/A/Ohm/H/F/s/Hz）。

    后缀大小写不敏感；"X/Y" 比值形态量值直通；未知后缀抛
    :class:`IbisParseError`（宁红不猜——#122 族诚实语义）。
    """
    m = _QTY_RE.match(token.strip())
    if m is None:
        raise IbisParseError(f"{where}：非数量词 {token!r}")
    suffix = m.group(2).strip()
    key = suffix.lower()
    if key in _UNIT_MULT:
        mult = _UNIT_MULT[key]
    elif _RATIO_SUFFIX_RE.match(key):
        mult = 1.0
    else:
        raise IbisParseError(
            f"{where}：未知单位后缀 {suffix!r}（token={token!r}）")
    return float(m.group(1)) * mult


def try_quantity(text: str) -> float | None:
    """宽松数量解析（子参数值判定）：非数量/未知后缀 → None（保留字符串）。"""
    try:
        return parse_quantity(text, "")
    except IbisParseError:
        return None


# ─── 数据结构 ───────────────────────────────────────────────────────────────


@dataclass
class IbisPin:
    """[Pin] 行：pin 号（字符串——真实文件含 "A12" 形态）+信号+模型+RLC。"""

    pin: str
    signal: str
    model: str | None = None
    r_pin: float | None = None
    l_pin: float | None = None
    c_pin: float | None = None
    line: int = 0


@dataclass
class IbisTable:
    """IV 查找表/暂态表：x=voltage（IV）或 time（波形）+三角列+元参数。

    minc/maxc=None 表示文件只给单列（v + I_typ 两列形态），如实保留。
    """

    kind: str
    line: int
    x: list[float] = field(default_factory=list)
    typ: list[float] = field(default_factory=list)
    minc: list[float] | None = None
    maxc: list[float] | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    label: str | None = None

    @property
    def n_rows(self) -> int:
        return len(self.x)


@dataclass
class IbisModel:
    """[Model] 节：子参数 attrs+四张 IV 表+Ramp+暂态表列（文档序）。"""

    name: str
    line: int
    attrs: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, IbisTable | None] = field(
        default_factory=lambda: {k: None for k in IV_TABLE_KINDS})
    ramp: dict[str, Any] | None = None
    waveforms: list[IbisTable] = field(default_factory=list)


@dataclass
class IbisComponent:
    """[Component] 节：其后的 [Package]/[Pin] 归属此器件（文档序）。"""

    name: str
    line: int
    manufacturer: str | None = None
    package: dict[str, Any] | None = None
    pins: list[IbisPin] = field(default_factory=list)


@dataclass
class IbisFile:
    """IBIS 文件解析树（raw 形态——结构化 JSON 视图走 :func:`extract_ibis`）。"""

    header: dict[str, Any] = field(default_factory=dict)
    components: list[IbisComponent] = field(default_factory=list)
    models: dict[str, IbisModel] = field(default_factory=dict)
    model_selectors: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    ended: bool = False


# ─── 解析（单遍状态机）──────────────────────────────────────────────────────


def _split_kv(stripped: str) -> tuple[str, str]:
    """子参数行 → (键, 值串)：``key = value`` 与 ``key value...`` 两形态。"""
    if "=" in stripped:
        left, _, right = stripped.partition("=")
        return left.strip(), right.strip()
    tokens = stripped.split()
    return tokens[0], " ".join(tokens[1:])


def _kv_triple(value_str: str, where: str) -> dict[str, float] | None:
    """值串为三列数量（typ min max）→ 三列 dict；否则 None。"""
    toks = [t for t in value_str.split() if t != "="]
    if len(toks) == 3 and all(try_quantity(t) is not None for t in toks):
        return {
            "typ": parse_quantity(toks[0], where),
            "min": parse_quantity(toks[1], where),
            "max": parse_quantity(toks[2], where),
        }
    return None


def _feed_subparam(target: dict[str, Any], stripped: str, where: str) -> None:
    """通用子参数行（Model attrs/Ramp/波形元参数共用）：数量→float、
    三列→dict、单词→字符串；两列残缺 → 报错（宁红不猜）。"""
    key, value_str = _split_kv(stripped)
    if not key:
        raise IbisParseError(f"{where}：子参数行缺键")
    key_l = key.lower()
    qty = try_quantity(value_str)
    if qty is not None:
        target[key_l] = qty
        return
    triple = _kv_triple(value_str, where)
    if triple is not None:
        target[key_l] = triple
        return
    toks = [t for t in value_str.split() if t != "="]
    if len(toks) == 1:
        target[key_l] = value_str
        return
    raise IbisParseError(f"{where}：无法解释的子参数值 {value_str!r}")


def _feed_table_row(table: IbisTable, tokens: list[str], lineno: int) -> None:
    """IV/暂态数据行：x 列+1 或 3 个数据列（首行定形，其后列数必须一致）。"""
    if len(tokens) not in (2, 4):
        raise IbisParseError(
            f"第 {lineno} 行：{table.kind} 表行应 2 或 4 列，实际 {len(tokens)} 列")
    where = f"第 {lineno} 行 {table.kind} 表"
    has_mm = len(tokens) == 4
    if table.n_rows == 0:
        table.minc = [] if has_mm else None
        table.maxc = [] if has_mm else None
    elif (table.minc is not None) != has_mm:
        first = 4 if table.minc is not None else 2
        raise IbisParseError(
            f"第 {lineno} 行：{table.kind} 表行列数不一致"
            f"（首行 {first} 列，本行 {len(tokens)} 列）")
    table.x.append(parse_quantity(tokens[0], where))
    table.typ.append(parse_quantity(tokens[1], where))
    if has_mm:
        table.minc.append(parse_quantity(tokens[2], where))
        table.maxc.append(parse_quantity(tokens[3], where))


def _feed_pin_row(comp: IbisComponent, tokens: list[str], lineno: int) -> None:
    """[Pin] 行：2 列（pin signal）/3 列（+model）/6 列（+R_pin L_pin C_pin）。"""
    if len(tokens) not in (2, 3, 6):
        raise IbisParseError(
            f"第 {lineno} 行：[Pin] 行应 2/3/6 列，实际 {len(tokens)} 列")
    pin_no = tokens[0]
    if any(p.pin == pin_no for p in comp.pins):
        raise IbisParseError(
            f"第 {lineno} 行：pin {pin_no!r} 在器件 {comp.name} 中重复")
    r_pin = l_pin = c_pin = None
    if len(tokens) == 6:
        where = f"第 {lineno} 行 [Pin] {pin_no}"
        r_pin = parse_quantity(tokens[3], where)
        l_pin = parse_quantity(tokens[4], where)
        c_pin = parse_quantity(tokens[5], where)
    comp.pins.append(IbisPin(
        pin=pin_no, signal=tokens[1],
        model=tokens[2] if len(tokens) >= 3 else None,
        r_pin=r_pin, l_pin=l_pin, c_pin=c_pin, line=lineno))


def _feed_package_row(comp: IbisComponent, tokens: list[str], lineno: int) -> None:
    """[Package] 行：键+1 或 3 个数量列；R_pkg/L_pkg/C_pkg 结构化，余键透传。"""
    toks = [t for t in tokens if t != "="]
    if len(toks) < 2:
        raise IbisParseError(
            f"第 {lineno} 行：[Package] 行应 键+1/3 个数量列，实际 {len(toks)} 列")
    key = toks[0].lower()
    vals = toks[1:]
    where = f"第 {lineno} 行 [Package] {key}"
    if len(vals) == 1:
        entry: Any = parse_quantity(vals[0], where)
    elif len(vals) == 3:
        entry = {
            "typ": parse_quantity(vals[0], where),
            "min": parse_quantity(vals[1], where),
            "max": parse_quantity(vals[2], where),
        }
    else:
        raise IbisParseError(
            f"{where}：应 1 或 3 个数量列，实际 {len(vals)} 列")
    assert comp.package is not None  # keyword 分派已保证
    if key in ("r_pkg", "l_pkg", "c_pkg"):
        comp.package[key] = entry
    else:
        comp.package["attrs"][key] = entry


def parse_ibis(text: str) -> IbisFile:
    """IBIS 文本 → :class:`IbisFile` 解析树（严格：[End] 收尾+必面校验）。"""
    out = IbisFile()
    comp: IbisComponent | None = None
    model: IbisModel | None = None
    selector: str | None = None
    table: IbisTable | None = None
    mode = "top"
    seen_component = False

    def _close_table() -> None:
        nonlocal table
        if table is not None and table.n_rows == 0:
            out.warnings.append(
                f"第 {table.line} 行起：{table.kind} 表零数据行（空表如实保留）")
        table = None

    for lineno, raw in enumerate(text.splitlines(), 1):
        if out.ended:
            # [End] 之后容注释/空白，容内容即报错（ibischk 同口径）
            tail = raw.split("|", 1)[0].strip()
            if tail:
                raise IbisParseError(
                    f"第 {lineno} 行：[End] 之后存在内容 {tail!r}")
            continue
        line = raw.split("|", 1)[0]  # | 注释至行尾（IBIS v4.2 §3.1）
        stripped = line.strip()
        if not stripped:
            continue
        kw = _KEYWORD_RE.match(stripped)
        if kw is not None:
            _close_table()
            name = kw.group(1).strip().upper()
            args = kw.group(2).strip()
            if name == "END":
                out.ended = True
                continue
            if name == "COMPONENT":
                if not args:
                    raise IbisParseError(f"第 {lineno} 行：[Component] 缺器件名")
                comp = IbisComponent(name=args, line=lineno)
                out.components.append(comp)
                seen_component = True
                mode = "top"
                continue
            if name == "MANUFACTURER":
                if comp is not None:
                    comp.manufacturer = args
                else:
                    out.header["manufacturer"] = args
                continue
            if name in _HEADER_KEYWORDS:
                out.header[_HEADER_KEYWORDS[name]] = args
                continue
            if name == "PACKAGE":
                if comp is None:
                    raise IbisParseError(
                        f"第 {lineno} 行：[Package] 出现在 [Component] 之前")
                if comp.package is not None:
                    raise IbisParseError(
                        f"第 {lineno} 行：器件 {comp.name} 重复 [Package]")
                comp.package = {"r_pkg": None, "l_pkg": None, "c_pkg": None,
                                "attrs": {}}
                mode = "package"
                continue
            if name == "PIN":
                if comp is None:
                    raise IbisParseError(
                        f"第 {lineno} 行：[Pin] 出现在 [Component] 之前")
                mode = "pin"
                continue
            if name == "MODEL SELECTOR":
                if not args:
                    raise IbisParseError(
                        f"第 {lineno} 行：[Model Selector] 缺选择器名")
                if args in out.model_selectors:
                    raise IbisParseError(
                        f"第 {lineno} 行：Model Selector {args!r} 重名")
                out.model_selectors[args] = []
                selector = args
                mode = "selector"
                continue
            if name == "MODEL":
                if not args:
                    raise IbisParseError(f"第 {lineno} 行：[Model] 缺模型名")
                if args in out.models:
                    raise IbisParseError(f"第 {lineno} 行：模型 {args!r} 重名")
                model = IbisModel(name=args, line=lineno)
                out.models[args] = model
                mode = "model_attrs"
                continue
            if name in _IV_KEYWORDS:
                if model is None:
                    raise IbisParseError(
                        f"第 {lineno} 行：[{kw.group(1).strip()}] 表出现在"
                        f" [Model] 之外")
                kind = _IV_KEYWORDS[name]
                if model.tables[kind] is not None:
                    raise IbisParseError(
                        f"第 {lineno} 行：模型 {model.name} 重复 {kind} 表")
                table = IbisTable(kind=kind, line=lineno)
                model.tables[kind] = table
                mode = "iv"
                continue
            if name == "RAMP":
                if model is None:
                    raise IbisParseError(
                        f"第 {lineno} 行：[Ramp] 出现在 [Model] 之外")
                if model.ramp is not None:
                    raise IbisParseError(
                        f"第 {lineno} 行：模型 {model.name} 重复 [Ramp]")
                model.ramp = {}
                mode = "ramp"
                continue
            if name in ("RISING WAVEFORM", "FALLING WAVEFORM"):
                if model is None:
                    raise IbisParseError(
                        f"第 {lineno} 行：[{kw.group(1).strip()}] 出现在"
                        f" [Model] 之外")
                kind = "rising" if name == "RISING WAVEFORM" else "falling"
                table = IbisTable(kind=kind, line=lineno, label=args or None)
                model.waveforms.append(table)
                mode = "waveform"
                continue
            # 未识别 keyword：warning+内容忽略（零静默丢弃，#122 族）
            out.warnings.append(
                f"第 {lineno} 行：未识别 keyword [{kw.group(1).strip()}]，"
                f"其内容忽略")
            mode = "ignored"
            continue
        # ── 数据行（按 mode 分派）──
        tokens = stripped.split()
        if mode == "top":
            raise IbisParseError(
                f"第 {lineno} 行：顶层裸数据行 {stripped!r}（期望 [Keyword]）")
        if mode == "ignored":
            continue
        if mode == "package":
            _feed_package_row(comp, tokens, lineno)
        elif mode == "pin":
            assert comp is not None  # keyword 分派已保证
            _feed_pin_row(comp, tokens, lineno)
        elif mode == "selector":
            assert selector is not None  # keyword 分派已保证
            out.model_selectors[selector].append(
                {"model": tokens[0], "comment": " ".join(tokens[1:])})
        elif mode == "model_attrs":
            assert model is not None  # keyword 分派已保证
            _feed_subparam(model.attrs, stripped,
                           f"第 {lineno} 行模型 {model.name} 子参数")
        elif mode == "ramp":
            assert model is not None and model.ramp is not None
            _feed_subparam(model.ramp, stripped,
                           f"第 {lineno} 行 [Ramp] {model.name}")
        elif mode == "iv":
            if table is None:
                raise IbisParseError(f"第 {lineno} 行：IV 表未初始化（内部态）")
            _feed_table_row(table, tokens, lineno)
        elif mode == "waveform":
            if table is None:
                raise IbisParseError(f"第 {lineno} 行：暂态表未初始化（内部态）")
            if try_quantity(tokens[0]) is None:
                # 元参数行（R_dut/C_dut/L_dut/V_fixture* 等）
                _feed_subparam(table.meta, stripped,
                               f"第 {lineno} 行 {table.kind} 波形元参数")
            else:
                _feed_table_row(table, tokens, lineno)
        else:  # pragma: no cover — mode 集闭合
            raise IbisParseError(f"第 {lineno} 行：未知解析态 {mode!r}")

    if not out.ended:
        raise IbisParseError("IBIS 文件未以 [End] 结束（截断或非 IBIS 文本）")
    if not seen_component:
        raise IbisParseError("未找到 [Component]（IBIS 文件必须至少一个器件）")
    _close_table()
    for m in out.models.values():
        if "model_type" not in m.attrs:
            raise IbisParseError(
                f"第 {m.line} 行：模型 {m.name} 缺 Model_type 子参数")
        for w in m.waveforms:
            for req in WAVEFORM_REQUIRED_META:
                if req not in w.meta:
                    raise IbisParseError(
                        f"第 {w.line} 行：模型 {m.name} {w.kind} 波形缺 {req}"
                        f" 元参数")
    return out


# ─── 结构化输出（JSON 视图）────────────────────────────────────────────────


def _extract_pin(p: IbisPin) -> dict[str, Any]:
    return {
        "pin": p.pin, "signal": p.signal, "model": p.model,
        "r_pin": p.r_pin, "l_pin": p.l_pin, "c_pin": p.c_pin, "line": p.line,
    }


def _extract_table(t: IbisTable, include_body: bool) -> dict[str, Any]:
    axis = "time" if t.kind in WAVEFORM_KINDS else "voltage"
    entry: dict[str, Any] = {
        "kind": t.kind, "label": t.label, "line": t.line, "n_rows": t.n_rows,
    }
    entry.update(t.meta)  # 波形 fixture 元参数摊平（r_dut/c_dut/v_fixture*）
    if include_body:
        entry[axis] = list(t.x)
        entry["typ"] = list(t.typ)
        if t.minc is not None:
            entry["min"] = list(t.minc)
        if t.maxc is not None:
            entry["max"] = list(t.maxc)
    return entry


def _extract_model(m: IbisModel, include_tables: bool) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": m.name, "line": m.line}
    for k in _PROMOTED_SCALARS:
        entry[k] = m.attrs.get(k)
    for k in _PROMOTED_TRIPLES:
        v = m.attrs.get(k)
        entry[k] = dict(v) if isinstance(v, dict) else None
    references = {k: v for k, v in m.attrs.items() if k.endswith("_reference")}
    entry["references"] = references
    entry["attrs"] = {
        k: v for k, v in m.attrs.items() if k not in _PROMOTED and k not in references
    }
    if include_tables:
        entry["tables"] = {
            k: (_extract_table(t, True) if t is not None else None)
            for k, t in m.tables.items()
        }
        entry["ramp"] = dict(m.ramp) if m.ramp is not None else None
        entry["waveforms"] = [_extract_table(w, True) for w in m.waveforms]
    return entry


def extract_ibis(file: IbisFile, *, include_tables: bool = True) -> dict[str, Any]:
    """解析树 → 结构化 JSON 视图（任务书五键：header/components/models/
    model_selectors/pins + warnings）。

    ``include_tables=False``：剪表体面（models[].tables/waveforms/ramp
    整键缺席；stats 随视图同步缩——liberty 同款口径），模型/引脚元数据
    不受影响。多器件同号 pin 扁平视图后者覆盖（docstring 口径如实）。
    """
    components: list[dict[str, Any]] = []
    pins_flat: dict[str, dict[str, Any]] = {}
    for c in file.components:
        package = None
        if c.package is not None:
            package = dict(c.package)
            package["attrs"] = dict(c.package.get("attrs") or {})
        entry = {
            "name": c.name, "line": c.line,
            "manufacturer": c.manufacturer, "package": package,
            "pins": [_extract_pin(p) for p in c.pins],
        }
        components.append(entry)
        for p in c.pins:
            pins_flat[p.pin] = _extract_pin(p)
    models = {
        name: _extract_model(m, include_tables)
        for name, m in file.models.items()
    }
    selectors = {
        k: [dict(row) for row in v] for k, v in file.model_selectors.items()
    }
    return {
        "header": dict(file.header),
        "components": components,
        "models": models,
        "model_selectors": selectors,
        "pins": pins_flat,
        "warnings": list(file.warnings),
    }


# ─── 查找表插值（确定性内核）───────────────────────────────────────────────


def _interp_axis(xs: list[float], ys: list[float], x: float) -> float:
    """单轴线性插值+边界夹取（x 轴要求严格递增——spec 表序）。"""
    if not xs or len(xs) != len(ys):
        raise ValueError("插值表 x/y 为空或长度不符")
    if any(b <= a for a, b in pairwise(xs)):
        raise ValueError("插值表 x 轴必须严格递增")
    if len(xs) == 1:
        return ys[0]
    i = bisect_right(xs, x)
    if i <= 0:
        return ys[0]
    if i >= len(xs):
        return ys[-1]
    x0, x1 = xs[i - 1], xs[i]
    y0, y1 = ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _corner_values(table: dict[str, Any], corner: str) -> list[float]:
    if corner not in ("typ", "min", "max"):
        raise ValueError(f"corner 应为 typ/min/max，实际 {corner!r}")
    ys = table.get(corner)
    if ys is None:
        raise ValueError(
            f"表无 {corner!r} 列（单列形态无 min/max——如实不可插）")
    return ys


def interp_iv(
    table: dict[str, Any], voltage: float, corner: str = "typ"
) -> float:
    """IV 查找表（Voltage→Current）线性插值，越界按边界夹取。"""
    return _interp_axis(table["voltage"], _corner_values(table, corner), voltage)


def interp_waveform(
    table: dict[str, Any], time: float, corner: str = "typ"
) -> float:
    """暂态表（time→voltage）线性插值，越界按边界夹取。"""
    return _interp_axis(table["time"], _corner_values(table, corner), time)
