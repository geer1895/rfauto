"""SDF（Standard Delay Format，IEEE 1497）时序标注结构化解析内核（aurora_q Q-X61，2026-11-07）。

数字后端**时序标注交换格式** SDF（IEEE 1497-2001 / OVI SDF 3.0）的只读结构化
解析——OpenSTA/PrimeTime/Vivado 等 STA 工具输出、门级仿真器反标
（``$sdf_annotate``）输入；数字后端三件套（SDC 约束 Q-X36 / SPEF 寄生 Q-X60 /
SDF 时序标注=本席）收官面。词法、S 表达式文法与 SDF 语义全部在 core 确定性
内核（铁律 7：结构化数字只出自数据源文本本身；时间单位换算=显式 TIMESCALE
表驱动，LLM/agent 永不产生物理数字）。服务包装见
:mod:`rfauto.service.sdf_service`（规则 4 JSON 进出），CLI 薄壳见
cli/domains/sdf.py。

两层结构（与 sdc_parser 的"Tcl 词法层+SDC 命令语义层"同代分层）：

1. S 表达式层（:func:`parse_sexpr`）——正则词法（括号/引号串/原子三类词元）
   +栈式解析为嵌套 :class:`SdfList`/:class:`SdfAtom` 树：

   - 注释：``/* ... */`` 块注释整段收编（可跨行；内含括号/引号不影响配平；
     未闭合=致命）与 ``//`` 行注释（IEEE 1497 两形态）；
   - 引号串 ``"..."``（``\\"``/``\\\\`` 转义解开，quoted=True 标记）；原子=
     连续非空白非括号非引号字符；``\\x`` 转义字整体并入原子并**保留反斜杠
     原文**（SDF 标识符转义语义——如 ``a\\[3\\]`` 与总线下标 ``a[3]`` 不同——
     解析层不解转义，名字如实）；
   - 深度守卫 :data:`MAX_NEST_DEPTH` =512（病态深嵌套 fail-closed）；栈式
     实现零 Python 递归（渲染 :func:`render_sexpr`/转换 :func:`sexpr_to_plain`
     同为迭代）；
   - 括号失配/引号串或块注释未闭合 → :class:`SdfParseError`（ValueError
     子类，带行号）。

2. SDF 语义层（:func:`parse_sdf`）：

   - 头部键闭集 :data:`HEADER_KEYWORDS`（SDFVERSION/DESIGN/DATE/VENDOR/
     PROGRAM/VERSION/DIVIDER/VOLTAGE/PROCESS/TEMPERATURE/TIMESCALE——IEEE 1497
     sdf_header 全集）；闭集外头部键（如 CELLDIVIDER——非 IEEE 1497 关键字）
     warning+``header["unknown"]`` 保留原文；重复键后者覆盖+warning；
   - TIMESCALE（**数值单位换算单源**）：乘数 1/10/100 × 单位 s/ms/us/ns/ps/fs
     的 18 档显式表 :data:`TIMESCALE_FACTORS`；表外（乘数 5、单位 xs 等）
     **fail-closed** 抛 :class:`SdfParseError`（ValueError 子类）——绝不静默
     猜量纲；缺省=IEEE 1497 规定 1ns（如实标 source=default 并 warning；
     OpenSTA SdfReader 缺省 timescale_=1.0E-9 同口径）；
   - DIVIDER 缺省 ``.``（IEEE 1497-2001 原文 "If the SDF file does not contain
     a hierarchy divider then the default hierarchy divider shall be the
     period"；OpenSTA 内部缺省 '/' 属其网络约定，本内核按标准）；
   - CELL：CELLTYPE（QSTRING）+INSTANCE 三态——``(INSTANCE)``=top-level
     （instance=None）/``(INSTANCE *)``=通配（instance_wildcard=True；全星号
     变体如 ``**`` 非 IEEE 1497 形态，同按通配处理并 warning 登记）/具体层次
     名（instance_path 按 DIVIDER 切分，转义分隔符 ``\\.`` 不切）；
   - DELAY：ABSOLUTE / INCREMENT（INCREMENTAL 拼写同收）两模式（条目 mode
     键如实 absolute/increment）下的 IOPATH/INTERCONNECT/PORT/NETDELAY/DEVICE
     五类 del_def + COND/CONDELSE 条件块（条件表达式按词元级重建原文，**只
     携带不求值**）+ PATHPULSE/PATHPULSEPERCENT（后者值为百分比，**不做**
     时间换算，unit=percent 如实标注）；
   - TIMINGCHECK：SETUP/HOLD/SETUPHOLD/RECOVERY/REMOVAL/RECREM/SKEW/TIMESKEW/
     FULLSKEW/WIDTH/PERIOD/NOCHANGE 十二类（IEEE 1497 tchk_def 全集）按定位
     元数（端口数, 值数）解析；端口级 ``(COND expr port)`` 与 SCOND/CCOND
     如实携带；
   - TIMINGENV/LABEL 及一切面外构造：warning+``unsupported`` 保留原文（不
     中断——宁全量带警告，不半途而废，sdc_parser 同口径）。

值与三元组（:func:`parse_sdf_triple`）：值括号内原子拼接后按 ``:`` 切分——
三槽=min:typ:max（空槽如实 None 不猜）；单值=三槽同值（IEEE 1497 语义，
OpenSTA ``makeTriple(v)`` 三指针同址同口径；form=single 如实标注）；
``()``=全槽 None（form=empty）；非法=form=invalid+warning。时间值**双录**：
文件时间单位原值（min/typ/max）+秒（min_s/typ_s/max_s）——秒值经 Decimal
十进制精确缩放后单次舍入（``0.100``×1ns → 恰为最近 double ``1e-10``；朴素
float 乘法 ``0.1 * 1e-9`` 实测得 ``1.0000000000000002e-10``）。delval 个数 1/2/3/6/12 为 IEEE
合法档（rise=首值、fall=次值；单值时 fall 继承 rise 并标
fall_inherited=True——OpenSTA ``triple_count == 1`` 全跳变共用同口径），其余
个数如实保留+warning；复合 delval ``((d) (r) (e))`` 的脉冲限值进
pulse_limits，RETAIN 值进 retain。

每 CELL 的 ``delays`` 恒含 :data:`DELAY_KINDS` （7）+ :data:`TIMING_CHECK_KINDS`
（12）全部 19 个桶键（缺席=空表，稳定 schema）；条目 ``section`` 键区分
DELAY/TIMINGCHECK。

查询三函数（服务/CLI 上层消费，纯派生视图不改 doc）：

- :func:`sdf_cell_lookup`：CELLTYPE+实例查——instance=None 只命中 top-level；
  instance="*" 只命中通配条目；具体实例名命中**精确相等条目+该 CELLTYPE 的
  通配条目**（IEEE 1497：``(INSTANCE *)`` 适用该 celltype 全部实例；层次名
  按原文字符串精确比较，不做分隔符归一），返回项带 match 键
  （top/exact/wildcard），按文档序；
- :func:`sdf_delay_paths`：该 celltype 全部 IOPATH/INTERCONNECT 平坦清单
  （from→to+rise/fall 秒值）；排序键=(CELL 文档序, 类别序 IOPATH<INTERCONNECT,
  from, to, 条目文档序)——同端点多条（COND 变体等）按文档序稳定；
- :func:`sdf_timing_check_summary`：全库 TIMINGCHECK 十二类计数+每类最坏值
  （全部条目全部值的 max 槽秒值取最大；max 槽 None 的值跳过；并列取文档序
  首个）。

确定性（同输入同输出）、零 IO（纯文本进出）、零第三方依赖。本模块不设
``__all__``（无 __all__ 的非门面文件不进 tests/gold/public_api.json——
sdc_parser/spef_parser 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: 括号嵌套深度上限（病态深嵌套 fail-closed；真实 SDF 嵌套深度 <10）。
MAX_NEST_DEPTH = 512

#: TIMESCALE 表（IEEE 1497 timescale_number 1|10|100 × timescale_unit
#: s|ms|us|ns|ps|fs 全 18 档 → 秒因子；表外 fail-closed）。
TIMESCALE_FACTORS: dict[str, float] = {
    "1s": 1.0,
    "10s": 10.0,
    "100s": 100.0,
    "1ms": 1e-3,
    "10ms": 1e-2,
    "100ms": 1e-1,
    "1us": 1e-6,
    "10us": 1e-5,
    "100us": 1e-4,
    "1ns": 1e-9,
    "10ns": 1e-8,
    "100ns": 1e-7,
    "1ps": 1e-12,
    "10ps": 1e-11,
    "100ps": 1e-10,
    "1fs": 1e-15,
    "10fs": 1e-14,
    "100fs": 1e-13,
}

#: IEEE 1497 缺省时间单位（缺 TIMESCALE 时）。
DEFAULT_TIMESCALE = "1ns"

#: IEEE 1497 缺省层次分隔符（缺 DIVIDER 时）。
DEFAULT_DIVIDER = "."

#: 头部键闭集 → header 字段名（IEEE 1497 sdf_header 全集）。
_HEADER_FIELDS: dict[str, str] = {
    "SDFVERSION": "sdf_version",
    "DESIGN": "design",
    "DATE": "date",
    "VENDOR": "vendor",
    "PROGRAM": "program",
    "VERSION": "version",
    "DIVIDER": "divider",
    "VOLTAGE": "voltage",
    "PROCESS": "process",
    "TEMPERATURE": "temperature",
    "TIMESCALE": "timescale",
}

#: 头部键闭集（公开只读视图）。
HEADER_KEYWORDS: tuple[str, ...] = tuple(_HEADER_FIELDS)

#: DELAY 段条目桶（del_def 五类 + deltype 级脉冲两类）。
DELAY_KINDS: tuple[str, ...] = (
    "IOPATH", "INTERCONNECT", "PORT", "NETDELAY", "DEVICE",
    "PATHPULSE", "PATHPULSEPERCENT",
)

#: TIMINGCHECK 段条目桶（IEEE 1497 tchk_def 全集）。
TIMING_CHECK_KINDS: tuple[str, ...] = (
    "SETUP", "HOLD", "SETUPHOLD", "RECOVERY", "REMOVAL", "RECREM",
    "SKEW", "TIMESKEW", "FULLSKEW", "WIDTH", "PERIOD", "NOCHANGE",
)

#: 端口边沿标识（IEEE 1497 edge_identifier；输出统一小写）。
EDGE_IDENTIFIERS = frozenset(
    {"posedge", "negedge", "01", "10", "0z", "z1", "1z", "z0"})

#: 时序检查定位元数：(端口数, 值数)——尾部 SCOND/CCOND 先剥离。
_TCHK_ARITY: dict[str, tuple[int, int]] = {
    "SETUP": (2, 1),
    "HOLD": (2, 1),
    "SETUPHOLD": (2, 2),
    "RECOVERY": (2, 1),
    "REMOVAL": (2, 1),
    "RECREM": (2, 2),
    "SKEW": (2, 1),
    "TIMESKEW": (2, 1),
    "FULLSKEW": (2, 2),
    "WIDTH": (1, 1),
    "PERIOD": (1, 1),
    "NOCHANGE": (2, 2),
}

#: ABSOLUTE/INCREMENT 内的 del_def 五类（COND 包裹目标同集）。
_DEL_DEF_KINDS = frozenset(
    {"IOPATH", "INTERCONNECT", "PORT", "NETDELAY", "DEVICE"})

#: deltype → mode（INCREMENTAL 为部分工具拼写，同收为 increment）。
_DELTYPE_MODES: dict[str, str] = {
    "ABSOLUTE": "absolute",
    "INCREMENT": "increment",
    "INCREMENTAL": "increment",
}

#: delval 个数合法档（IEEE 1497 rvalue_list：1/2/3/6/12）。
_DELVAL_COUNTS = frozenset({1, 2, 3, 6, 12})

#: 平坦路径清单收录类别（类别序即排序第二键）。
_PATH_KINDS: tuple[str, ...] = ("IOPATH", "INTERCONNECT")

_ALL_KINDS: tuple[str, ...] = (*DELAY_KINDS, *TIMING_CHECK_KINDS)
_SLOT_KEYS: tuple[str, ...] = ("min", "typ", "max")
_NO_COND: tuple[str | None, str | None, bool] = (None, None, False)

_NUM_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_TIMESCALE_RE = re.compile(r"(\d+(?:\.\d*)?)\s*([A-Za-z]+)")
_TIMESCALE_MULTIPLIERS = (Decimal(1), Decimal(10), Decimal(100))
#: 秒因子的精确十进制形态（repr 为最短往返串，10 的幂次恰为精确十进制）。
_TIMESCALE_DECIMAL: dict[str, Decimal] = {
    key: Decimal(repr(value)) for key, value in TIMESCALE_FACTORS.items()
}
_UNESCAPE_RE = re.compile(r"\\(.)", re.DOTALL)
#: 词元正则（全字符覆盖：空白/换行/注释/括号/引号串/原子；坏注释与坏引号串
#: 作为兜底分支命中即致命）。原子内 ``/`` 仅在不起注释时并入。
_TOKEN_RE = re.compile(
    r"""
    (?P<ws>[^\S\n]+)
    |(?P<nl>\n)
    |(?P<bcomment>/\*.*?\*/)
    |(?P<bad_bcomment>/\*)
    |(?P<lcomment>//[^\n]*)
    |(?P<lp>\()
    |(?P<rp>\))
    |(?P<qstr>"(?:\\.|[^"\\])*")
    |(?P<bad_qstr>")
    |(?P<atom>(?:\\.|\\\Z|[^\s()"\\/]|/(?![*/]))+)
    """,
    re.VERBOSE | re.DOTALL,
)


class SdfParseError(ValueError):
    """SDF 词法/结构违规或文件身份致命错误（ValueError 子类，带行号文本）。

    覆盖：括号失配、引号串/块注释未闭合、嵌套深度越限、空文本、缺
    DELAYFILE 头、未知 TIMESCALE（fail-closed）。语义层病态（面外构造/
    非法值）不走本异常（warning+如实登记口径）。
    """


# ─── S 表达式层 ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class SdfAtom:
    """原子词元：text=原文（引号串为解转义后的内容）+行号+quoted 标记。"""

    text: str
    line: int
    quoted: bool = False


@dataclass(slots=True)
class SdfList:
    """括号表：items=有序子节点（SdfAtom/SdfList）+左括号所在行号。"""

    items: list[SdfAtom | SdfList]
    line: int


def parse_sexpr(
    text: str, *, max_depth: int = MAX_NEST_DEPTH
) -> list[SdfAtom | SdfList]:
    """S 表达式文本 → 顶层节点表（栈式，零递归；纯函数零 IO）。

    ``max_depth``：括号嵌套深度上限（缺省 :data:`MAX_NEST_DEPTH`）；越限、
    括号失配、引号串/块注释未闭合一律抛 :class:`SdfParseError`。
    """
    root: list[SdfAtom | SdfList] = []
    stack: list[SdfList] = []
    pos, n, line = 0, len(text), 1
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if m is None:  # 词法全字符覆盖，防御位
            raise SdfParseError(f"第 {line} 行：无法识别的字符 {text[pos]!r}")
        kind = m.lastgroup
        token = m.group()
        pos = m.end()
        container = stack[-1].items if stack else root
        if kind == "nl":
            line += 1
        elif kind in ("ws", "lcomment"):
            continue
        elif kind == "bcomment":
            line += token.count("\n")
        elif kind == "lp":
            if len(stack) >= max_depth:
                raise SdfParseError(
                    f"第 {line} 行：括号嵌套深度超过上限 {max_depth}"
                    "（病态深嵌套 fail-closed）")
            node = SdfList(items=[], line=line)
            container.append(node)
            stack.append(node)
        elif kind == "rp":
            if not stack:
                raise SdfParseError(f"第 {line} 行：多余的右括号（括号失配）")
            stack.pop()
        elif kind == "qstr":
            container.append(SdfAtom(
                text=_UNESCAPE_RE.sub(r"\1", token[1:-1]), line=line,
                quoted=True))
            line += token.count("\n")
        elif kind == "atom":
            container.append(SdfAtom(text=token, line=line))
            line += token.count("\n")
        elif kind == "bad_bcomment":
            raise SdfParseError(f"第 {line} 行：块注释 /* 未闭合")
        else:  # bad_qstr
            raise SdfParseError(f"第 {line} 行：引号字符串未闭合")
    if stack:
        raise SdfParseError(
            f"第 {stack[-1].line} 行起的括号未闭合（文件尾仍缺 {len(stack)} 个右括号）")
    return root


def _atom_source(atom: SdfAtom) -> str:
    """原子的源文形态（引号串重新加引号并转义 ``\\``/``"``）。"""
    if atom.quoted:
        body = atom.text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{body}"'
    return atom.text


def render_sexpr(node: SdfAtom | SdfList) -> str:
    """节点 → 紧凑源文（单空格分词，括号内侧无空格；迭代实现零递归）。"""
    if isinstance(node, SdfAtom):
        return _atom_source(node)
    tokens: list[str] = ["("]
    stack = [iter(node.items)]
    while stack:
        child = next(stack[-1], None)
        if child is None:
            stack.pop()
            tokens.append(")")
        elif isinstance(child, SdfList):
            tokens.append("(")
            stack.append(iter(child.items))
        else:
            tokens.append(_atom_source(child))
    out: list[str] = []
    prev = "("
    for tok in tokens:
        if out and tok != ")" and prev != "(":
            out.append(" ")
        out.append(tok)
        prev = tok
    return "".join(out)


def sexpr_to_plain(node: SdfAtom | SdfList) -> Any:
    """节点 → 纯 Python 嵌套列表（原子=源文 str，引号串带引号；迭代实现）。"""
    if isinstance(node, SdfAtom):
        return _atom_source(node)
    root: list[Any] = []
    stack: list[tuple[SdfList, list[Any]]] = [(node, root)]
    while stack:
        src, dst = stack.pop()
        for child in src.items:
            if isinstance(child, SdfList):
                sub: list[Any] = []
                dst.append(sub)
                stack.append((child, sub))
            else:
                dst.append(_atom_source(child))
    return root


def _split_head(
    node: SdfAtom | SdfList,
) -> tuple[str | None, list[SdfAtom | SdfList]]:
    """表头关键字（大写，大小写不敏感）+其余子节点；非表/空表/头非裸原子 → (None, [])。"""
    if isinstance(node, SdfList) and node.items:
        first = node.items[0]
        if isinstance(first, SdfAtom) and not first.quoted:
            return first.text.upper(), node.items[1:]
    return None, []


def _render_items(items: list[SdfAtom | SdfList]) -> str:
    """子节点序列 → 空格拼接源文（COND 条件表达式词元级重建）。"""
    return " ".join(render_sexpr(item) for item in items)


def _bare_atoms(items: list[SdfAtom | SdfList]) -> list[SdfAtom] | None:
    """全部为裸原子（非引号串）时返回原子表，否则 None。"""
    atoms = [item for item in items
             if isinstance(item, SdfAtom) and not item.quoted]
    return atoms if len(atoms) == len(items) else None


# ─── 值 / 三元组 / TIMESCALE ───────────────────────────────────────────────


def _triple_from_text(text: str, scale: Decimal | None) -> dict[str, Any]:
    """值文本 → 三元组 dict（scale 非 None 时加秒值双录）。"""
    compact = "".join(text.split())
    slots: list[str | None]
    if compact == "":
        form, slots = "empty", [None, None, None]
    else:
        pieces = compact.split(":")
        if len(pieces) == 1:
            form, slots = "single", [pieces[0], pieces[0], pieces[0]]
        elif len(pieces) == 3:
            form, slots = "triple", [p or None for p in pieces]
        else:
            form, slots = "invalid", [None, None, None]
        if form != "invalid" and any(
                s is not None and not _NUM_RE.fullmatch(s) for s in slots):
            form, slots = "invalid", [None, None, None]
    triple: dict[str, Any] = {"raw": compact, "form": form}
    for key, slot in zip(_SLOT_KEYS, slots, strict=True):
        triple[key] = None if slot is None else float(slot)
    if scale is not None:
        for key, slot in zip(_SLOT_KEYS, slots, strict=True):
            triple[f"{key}_s"] = (
                None if slot is None else float(Decimal(slot) * scale))
    return triple


def _invalid_triple(raw: str, scaled: bool) -> dict[str, Any]:
    triple: dict[str, Any] = {
        "raw": raw, "form": "invalid", "min": None, "typ": None, "max": None}
    if scaled:
        triple.update(min_s=None, typ_s=None, max_s=None)
    return triple


def parse_sdf_triple(
    text: str, timescale_factor: float | None = None
) -> dict[str, Any]:
    """值文本（括号内内容）→ 三元组 dict。

    返回 ``{"raw", "form", "min", "typ", "max"}``（form ∈ triple/single/
    empty/invalid；文件单位原值，空槽如实 None）；``timescale_factor``
    （秒/文件单位）给出时追加 ``min_s/typ_s/max_s`` 秒值（Decimal 精确
    缩放后单次舍入）。单值=三槽同值（IEEE 1497 语义）。
    """
    scale = (None if timescale_factor is None
             else Decimal(repr(float(timescale_factor))))
    return _triple_from_text(text, scale)


def _canonical_timescale(spec: str) -> tuple[str, int, str]:
    """TIMESCALE 文本 → (表键, 乘数, 单位)；表外 fail-closed 抛 SdfParseError。"""
    m = _TIMESCALE_RE.fullmatch(spec.strip())
    if m is None:
        raise SdfParseError(
            f"TIMESCALE {spec!r} 无法解析（期望 1|10|100 + s|ms|us|ns|ps|fs）"
            "——fail-closed")
    number, unit_raw = m.group(1), m.group(2)
    multiplier = Decimal(number)
    if multiplier not in _TIMESCALE_MULTIPLIERS:
        raise SdfParseError(
            f"TIMESCALE 乘数 {number} 不在 IEEE 1497 闭集 1/10/100——fail-closed")
    unit = unit_raw.lower()
    key = f"{int(multiplier)}{unit}"
    if key not in TIMESCALE_FACTORS:
        raise SdfParseError(
            f"TIMESCALE 单位 {unit_raw!r} 不在 IEEE 1497 闭集 s/ms/us/ns/ps/fs"
            "——fail-closed")
    return key, int(multiplier), unit


def sdf_timescale_factor(spec: str) -> float:
    """TIMESCALE 文本（如 ``1ns``/``100 ps``/``1.0NS``）→ 秒因子（表驱动）。

    单位大小写不敏感、数与单位间可有空白；表外（乘数非 1/10/100、单位非
    s/ms/us/ns/ps/fs）抛 :class:`SdfParseError`（ValueError 子类，fail-closed）。
    """
    return TIMESCALE_FACTORS[_canonical_timescale(spec)[0]]


def _timescale_entry(spec: str, source: str) -> dict[str, Any]:
    key, multiplier, unit = _canonical_timescale(spec)
    return {
        "raw": spec,
        "key": key,
        "multiplier": multiplier,
        "unit": unit,
        "factor_s": TIMESCALE_FACTORS[key],
        "source": source,
    }


# ─── 语义层上下文与通用件 ──────────────────────────────────────────────────


@dataclass
class _Ctx:
    """单次解析上下文：秒缩放因子（Decimal）+层次分隔符+带行号 warning 收集。"""

    scale: Decimal
    divider: str
    warnings: list[tuple[int, str]]

    def warn(self, line: int, message: str) -> None:
        self.warnings.append((line, message))


def _value_from_node(
    node: SdfAtom | SdfList, ctx: _Ctx, what: str, *, scaled: bool = True
) -> dict[str, Any]:
    """值节点 ``(v)``/``(a:b:c)``/``()`` → 三元组；裸原子/形态非法如实 warning。"""
    scale = ctx.scale if scaled else None
    if isinstance(node, SdfList):
        atoms = _bare_atoms(node.items)
        if atoms is None:
            raw = render_sexpr(node)
            ctx.warn(node.line, f"{what} 值形态非法 {raw}——三槽如实 None")
            return _invalid_triple(raw, scaled)
        text = "".join(atom.text for atom in atoms)
    elif not node.quoted:
        ctx.warn(node.line, f"{what} 值 {node.text!r} 未加括号（IEEE 1497 值形态为"
                            " (v)/(min:typ:max)）——按原文解析")
        text = node.text
    else:
        raw = render_sexpr(node)
        ctx.warn(node.line, f"{what} 值为引号串 {raw}——三槽如实 None")
        return _invalid_triple(raw, scaled)
    triple = _triple_from_text(text, scale)
    if triple["form"] == "invalid":
        ctx.warn(node.line, f"{what} 值 {text!r} 非法（非数值或槽数≠1/3）——三槽如实 None")
    return triple


def _delval_from_node(
    node: SdfAtom | SdfList, ctx: _Ctx, what: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """delval → (延迟三元组, 脉冲限值或 None)；复合形态 ``((d) (r) (e))`` 拆三。"""
    if isinstance(node, SdfList) and node.items and all(
            isinstance(item, SdfList) for item in node.items):
        inner = node.items
        if len(inner) > 3:
            ctx.warn(node.line, f"{what} 复合 delval 含 {len(inner)} 个 rvalue"
                                "（IEEE 1497 至多 3）——取前 3")
        delay = _value_from_node(inner[0], ctx, what)
        if len(inner) == 1:
            return delay, None
        pulse = {
            "reject": _value_from_node(inner[1], ctx, what),
            "error": (_value_from_node(inner[2], ctx, what)
                      if len(inner) >= 3 else None),
        }
        return delay, pulse
    return _value_from_node(node, ctx, what), None


def _collect_delvals(
    items: list[SdfAtom | SdfList], ctx: _Ctx, what: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """delval 序列 → (延迟三元组表, 脉冲限值表[带 index])。"""
    triples: list[dict[str, Any]] = []
    pulses: list[dict[str, Any]] = []
    for item in items:
        triple, pulse = _delval_from_node(item, ctx, what)
        if pulse is not None:
            pulses.append({"index": len(triples), **pulse})
        triples.append(triple)
    return triples, pulses


def _attach_triples(
    entry: dict[str, Any], triples: list[dict[str, Any]], ctx: _Ctx,
    line: int, what: str,
) -> None:
    """延迟条目落 triples/n_triples/rise_triple/fall_triple/fall_inherited。"""
    count = len(triples)
    entry["triples"] = triples
    entry["n_triples"] = count
    if count == 0:
        ctx.warn(line, f"{what} 无延迟值——rise/fall 如实 None")
        entry.update(rise_triple=None, fall_triple=None, fall_inherited=False)
        return
    if count not in _DELVAL_COUNTS:
        ctx.warn(line, f"{what} 延迟值 {count} 个，非 IEEE 1497 合法档"
                       "（1/2/3/6/12）——如实保留，rise/fall 取前两值")
    if count == 1:
        entry.update(rise_triple=dict(triples[0]),
                     fall_triple=dict(triples[0]), fall_inherited=True)
    else:
        entry.update(rise_triple=dict(triples[0]),
                     fall_triple=dict(triples[1]), fall_inherited=False)


def _delay_entry(
    kind: str, mode: str | None, line: int,
    cond: tuple[str | None, str | None, bool],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "section": "DELAY",
        "mode": mode,
        "cond": cond[0],
        "cond_name": cond[1],
        "condelse": cond[2],
        "line": line,
    }


def _unsupported(
    cell: dict[str, Any], node: SdfAtom | SdfList, note: str
) -> None:
    head, _ = _split_head(node)
    cell["unsupported"].append({
        "keyword": head,
        "line": node.line,
        "raw": render_sexpr(node),
        "note": note,
    })


def _port_spec(
    node: SdfAtom | SdfList, ctx: _Ctx, what: str
) -> dict[str, Any] | None:
    """port_spec：裸端口名 / ``(edge port)`` 边沿形态；非法 → None+warning。"""
    if isinstance(node, SdfAtom):
        if node.quoted:
            ctx.warn(node.line, f"{what} 端口名带引号（IEEE 1497 为标识符）——如实采纳")
        return {"pin": node.text, "edge": None}
    head, args = _split_head(node)
    if (head is not None and head.lower() in EDGE_IDENTIFIERS
            and len(args) == 1 and isinstance(args[0], SdfAtom)):
        return {"pin": args[0].text, "edge": head.lower()}
    ctx.warn(node.line, f"{what} 形态非法 {render_sexpr(node)}——条目跳过")
    return None


def _pin_name(node: SdfAtom | SdfList, ctx: _Ctx, what: str) -> str | None:
    """port_instance / net 名：须为原子（引号串如实采纳+warning）。"""
    if isinstance(node, SdfAtom):
        if node.quoted:
            ctx.warn(node.line, f"{what} 名带引号（IEEE 1497 为标识符）——如实采纳")
        return node.text
    ctx.warn(node.line, f"{what} 形态非法 {render_sexpr(node)}——条目跳过")
    return None


def _quoted_name(
    items: list[SdfAtom | SdfList],
) -> tuple[str | None, list[SdfAtom | SdfList]]:
    """COND/SCOND/CCOND 可选 QSTRING 名：剥离首个引号串。"""
    if items and isinstance(items[0], SdfAtom) and items[0].quoted:
        return items[0].text, items[1:]
    return None, items


def _split_hier(name: str, divider: str) -> list[str]:
    """层次名按分隔符切分（``\\`` 转义的分隔符不切，段内保留转义原文）。"""
    parts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(name)
    while i < n:
        ch = name[i]
        if ch == "\\" and i + 1 < n:
            buf.append(name[i: i + 2])
            i += 2
            continue
        if ch == divider:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


# ─── DELAY 段 ──────────────────────────────────────────────────────────────


def _parse_del_def(
    node: SdfAtom | SdfList, mode: str, ctx: _Ctx, cell: dict[str, Any],
    cond: tuple[str | None, str | None, bool] = _NO_COND,
) -> None:
    """ABSOLUTE/INCREMENT 内单个 del_def（含 COND/CONDELSE 包裹）。"""
    head, args = _split_head(node)
    if head == "COND" and cond is _NO_COND:
        name, rest = _quoted_name(args)
        target_head = _split_head(rest[-1])[0] if rest else None
        if target_head not in _DEL_DEF_KINDS:
            ctx.warn(node.line, "COND 缺被包裹的延迟定义（期望 (COND expr (IOPATH ...))）"
                                "——如实登记 unsupported")
            _unsupported(cell, node, "COND 形态非法")
            return
        if target_head != "IOPATH":
            ctx.warn(node.line, f"COND 包裹 {target_head}（IEEE 1497 仅 IOPATH）——如实携带")
        cond_items = rest[:-1]
        if not cond_items:
            ctx.warn(node.line, "COND 条件表达式为空——cond 如实 None")
        _parse_del_def(rest[-1], mode, ctx, cell,
                       cond=(_render_items(cond_items) or None, name, False))
        return
    if head == "CONDELSE" and cond is _NO_COND:
        if len(args) != 1 or _split_head(args[0])[0] not in _DEL_DEF_KINDS:
            ctx.warn(node.line, "CONDELSE 形态非法（期望 (CONDELSE (IOPATH ...))）"
                                "——如实登记 unsupported")
            _unsupported(cell, node, "CONDELSE 形态非法")
            return
        _parse_del_def(args[0], mode, ctx, cell, cond=(None, None, True))
        return
    if head not in _DEL_DEF_KINDS:
        label = head if head is not None else render_sexpr(node)
        ctx.warn(node.line, f"DELAY 内面外延迟定义 {label!r}——如实登记 unsupported")
        _unsupported(cell, node, "DELAY 面外延迟定义")
        return
    if head == "IOPATH":
        _parse_iopath(node, args, mode, ctx, cell, cond)
    elif head == "INTERCONNECT":
        _parse_interconnect(node, args, mode, ctx, cell, cond)
    elif head == "PORT":
        _parse_single_pin(node, args, "PORT", "pin", mode, ctx, cell, cond)
    elif head == "NETDELAY":
        _parse_single_pin(node, args, "NETDELAY", "net", mode, ctx, cell, cond)
    else:
        _parse_device(node, args, mode, ctx, cell, cond)


def _parse_iopath(
    node: SdfAtom | SdfList, args: list[SdfAtom | SdfList], mode: str,
    ctx: _Ctx, cell: dict[str, Any],
    cond: tuple[str | None, str | None, bool],
) -> None:
    if len(args) < 2:
        ctx.warn(node.line, "IOPATH 端口不足（期望 源端口 宿端口 值...）——如实登记 unsupported")
        _unsupported(cell, node, "IOPATH 端口不足")
        return
    src = _port_spec(args[0], ctx, "IOPATH 源端口")
    dst = _port_spec(args[1], ctx, "IOPATH 宿端口")
    if src is None or dst is None:
        _unsupported(cell, node, "IOPATH 端口形态非法")
        return
    if dst["edge"] is not None:
        ctx.warn(node.line, "IOPATH 宿端口带边沿（IEEE 1497 宿端为 port_instance）——边沿忽略")
    retain: list[dict[str, Any]] = []
    value_items: list[SdfAtom | SdfList] = []
    for item in args[2:]:
        item_head, item_args = _split_head(item)
        if item_head == "RETAIN":
            retain.extend(_value_from_node(sub, ctx, "RETAIN") for sub in item_args)
        else:
            value_items.append(item)
    triples, pulses = _collect_delvals(value_items, ctx, "IOPATH")
    entry = _delay_entry("IOPATH", mode, node.line, cond)
    entry.update(from_pin=src["pin"], from_edge=src["edge"], to_pin=dst["pin"])
    _attach_triples(entry, triples, ctx, node.line, "IOPATH")
    entry["retain"] = retain
    entry["pulse_limits"] = pulses
    cell["delays"]["IOPATH"].append(entry)


def _parse_interconnect(
    node: SdfAtom | SdfList, args: list[SdfAtom | SdfList], mode: str,
    ctx: _Ctx, cell: dict[str, Any],
    cond: tuple[str | None, str | None, bool],
) -> None:
    if len(args) < 2:
        ctx.warn(node.line, "INTERCONNECT 端点不足（期望 源 宿 值...）——如实登记 unsupported")
        _unsupported(cell, node, "INTERCONNECT 端点不足")
        return
    src = _pin_name(args[0], ctx, "INTERCONNECT 源端点")
    dst = _pin_name(args[1], ctx, "INTERCONNECT 宿端点")
    if src is None or dst is None:
        _unsupported(cell, node, "INTERCONNECT 端点形态非法")
        return
    triples, pulses = _collect_delvals(args[2:], ctx, "INTERCONNECT")
    entry = _delay_entry("INTERCONNECT", mode, node.line, cond)
    entry.update(from_pin=src, to_pin=dst)
    _attach_triples(entry, triples, ctx, node.line, "INTERCONNECT")
    entry["pulse_limits"] = pulses
    cell["delays"]["INTERCONNECT"].append(entry)


def _parse_single_pin(
    node: SdfAtom | SdfList, args: list[SdfAtom | SdfList], kind: str,
    key: str, mode: str, ctx: _Ctx, cell: dict[str, Any],
    cond: tuple[str | None, str | None, bool],
) -> None:
    """PORT（pin）/NETDELAY（net）：单名+delval 序列。"""
    if not args:
        ctx.warn(node.line, f"{kind} 缺名字——如实登记 unsupported")
        _unsupported(cell, node, f"{kind} 缺名字")
        return
    name = _pin_name(args[0], ctx, kind)
    if name is None:
        _unsupported(cell, node, f"{kind} 名形态非法")
        return
    triples, pulses = _collect_delvals(args[1:], ctx, kind)
    entry = _delay_entry(kind, mode, node.line, cond)
    entry[key] = name
    _attach_triples(entry, triples, ctx, node.line, kind)
    entry["pulse_limits"] = pulses
    cell["delays"][kind].append(entry)


def _parse_device(
    node: SdfAtom | SdfList, args: list[SdfAtom | SdfList], mode: str,
    ctx: _Ctx, cell: dict[str, Any],
    cond: tuple[str | None, str | None, bool],
) -> None:
    """DEVICE：可选 port_instance + delval 序列（缺端口=作用全部输出）。"""
    pin: str | None = None
    rest = args
    if args and isinstance(args[0], SdfAtom):
        pin = _pin_name(args[0], ctx, "DEVICE")
        rest = args[1:]
    triples, pulses = _collect_delvals(rest, ctx, "DEVICE")
    entry = _delay_entry("DEVICE", mode, node.line, cond)
    entry["pin"] = pin
    _attach_triples(entry, triples, ctx, node.line, "DEVICE")
    entry["pulse_limits"] = pulses
    cell["delays"]["DEVICE"].append(entry)


def _parse_pathpulse(
    node: SdfAtom | SdfList, kind: str, ctx: _Ctx, cell: dict[str, Any]
) -> None:
    """PATHPULSE/PATHPULSEPERCENT：[输入 输出] 值 [值]（后者百分比不换算）。"""
    _, args = _split_head(node)
    lead = 0
    while lead < len(args) and isinstance(args[lead], SdfAtom):
        lead += 1
    pins = [atom.text for atom in args[:lead] if isinstance(atom, SdfAtom)]
    rest = args[lead:]
    if len(pins) not in (0, 2):
        ctx.warn(node.line, f"{kind} 端口 {len(pins)} 个（IEEE 1497 为 0 或 2：输入 输出）"
                            "——如实记录")
    scaled = kind == "PATHPULSE"
    values = [_value_from_node(item, ctx, kind, scaled=scaled) for item in rest]
    if not 1 <= len(values) <= 2:
        ctx.warn(node.line, f"{kind} 值 {len(values)} 个（IEEE 1497 为 1 或 2：reject [error]）"
                            "——如实保留")
    entry = _delay_entry(kind, None, node.line, _NO_COND)
    entry.update(
        from_pin=pins[0] if pins else None,
        to_pin=pins[1] if len(pins) > 1 else None,
        pins=pins,
        unit="time" if scaled else "percent",
        triples=values,
        n_triples=len(values),
        reject=values[0] if values else None,
        error=values[1] if len(values) > 1 else None,
    )
    cell["delays"][kind].append(entry)


# ─── TIMINGCHECK 段 ────────────────────────────────────────────────────────


def _port_tchk(
    node: SdfAtom | SdfList, ctx: _Ctx, what: str
) -> dict[str, Any] | None:
    """port_tchk：port_spec 或 ``(COND [名] 条件 port_spec)``（条件只携带不求值）。"""
    head, args = _split_head(node)
    if head == "COND":
        name, rest = _quoted_name(args)
        if not rest:
            ctx.warn(node.line, f"{what} 端口 COND 缺端口——条目跳过")
            return None
        port = _port_spec(rest[-1], ctx, f"{what} 端口")
        if port is None:
            return None
        cond_items = rest[:-1]
        if not cond_items:
            ctx.warn(node.line, f"{what} 端口 COND 条件表达式为空——cond 如实 None")
        port["cond"] = _render_items(cond_items) or None
        port["cond_name"] = name
        return port
    port = _port_spec(node, ctx, f"{what} 端口")
    if port is not None:
        port["cond"] = None
        port["cond_name"] = None
    return port


def _parse_tchk(node: SdfAtom | SdfList, ctx: _Ctx, cell: dict[str, Any]) -> None:
    head, args = _split_head(node)
    arity = _TCHK_ARITY.get(head) if head is not None else None
    if head is None or arity is None:
        label = head if head is not None else render_sexpr(node)
        ctx.warn(node.line, f"TIMINGCHECK 内面外检查 {label!r}（非 IEEE 1497 tchk_def）"
                            "——如实登记 unsupported")
        _unsupported(cell, node, "TIMINGCHECK 面外检查")
        return
    items = list(args)
    conds: dict[str, tuple[str | None, str | None]] = {}
    while items:
        tail_head, tail_args = _split_head(items[-1])
        if tail_head is None or tail_head not in ("SCOND", "CCOND"):
            break
        items.pop()
        name, rest = _quoted_name(tail_args)
        key = tail_head.lower()
        if key in conds:
            ctx.warn(node.line, f"{head} 重复 {tail_head}——取首个（自左向右）")
        conds[key] = (_render_items(rest) or None, name)
    n_ports, n_values = arity
    if len(items) != n_ports + n_values:
        ctx.warn(node.line, f"{head} 参数 {len(items)} 个，期望 {n_ports + n_values}"
                            f"（端口 {n_ports}+值 {n_values}）——按定位元数如实解析")
    if len(items) < n_ports:
        _unsupported(cell, node, f"{head} 端口不足")
        return
    ports: list[dict[str, Any]] = []
    for item in items[:n_ports]:
        port = _port_tchk(item, ctx, head)
        if port is None:
            _unsupported(cell, node, f"{head} 端口形态非法")
            return
        ports.append(port)
    triples = [_value_from_node(item, ctx, head) for item in items[n_ports:]]
    scond = conds.get("scond", (None, None))
    ccond = conds.get("ccond", (None, None))
    entry: dict[str, Any] = {
        "kind": head,
        "section": "TIMINGCHECK",
        "check_type": head,
        "pin": ports[0]["pin"],
        "edge": ports[0]["edge"],
        "ref_pin": ports[1]["pin"] if n_ports > 1 else None,
        "ref_edge": ports[1]["edge"] if n_ports > 1 else None,
        "ports": ports,
        "cond": next((p["cond"] for p in ports if p["cond"] is not None), None),
        "scond": scond[0],
        "scond_name": scond[1],
        "ccond": ccond[0],
        "ccond_name": ccond[1],
        "triples": triples,
        "n_triples": len(triples),
        "line": node.line,
    }
    cell["delays"][head].append(entry)


# ─── CELL / 头部 / 文档 ────────────────────────────────────────────────────


def _cell_type_value(
    args: list[SdfAtom | SdfList], line: int, ctx: _Ctx
) -> str | None:
    if len(args) != 1 or not isinstance(args[0], SdfAtom):
        ctx.warn(line, "CELLTYPE 形态非法（期望单个 QSTRING）——celltype 如实 None")
        return None
    if not args[0].quoted:
        ctx.warn(line, "CELLTYPE 未加引号（IEEE 1497 为 QSTRING）——如实采纳")
    return args[0].text


def _apply_instance(
    cell: dict[str, Any], args: list[SdfAtom | SdfList], line: int, ctx: _Ctx
) -> None:
    """INSTANCE 三态：空=top-level / 全星号=通配 / 层次名（按 DIVIDER 切分）。"""
    if not args:
        return
    if len(args) > 1:
        ctx.warn(line, f"INSTANCE 含 {len(args)} 个词（期望 0/1）——取首个")
    first = args[0]
    if not isinstance(first, SdfAtom):
        ctx.warn(line, f"INSTANCE 名形态非法 {render_sexpr(first)}——按 top-level 处理")
        return
    if first.quoted:
        ctx.warn(line, "INSTANCE 名带引号（IEEE 1497 为层次标识符）——如实采纳")
    text = first.text
    if text and set(text) == {"*"}:
        if text != "*":
            ctx.warn(line, f"INSTANCE 通配写作 {text!r}（IEEE 1497 通配仅单个 *）"
                           "——按通配处理")
        cell.update(instance=text, instance_wildcard=True, instance_path=[text])
        return
    cell.update(instance=text, instance_path=_split_hier(text, ctx.divider))


def _parse_cell(node: SdfAtom | SdfList, index: int, ctx: _Ctx) -> dict[str, Any]:
    _, args = _split_head(node)
    cell: dict[str, Any] = {
        "index": index,
        "celltype": None,
        "instance": None,
        "instance_wildcard": False,
        "instance_path": None,
        "delays": {kind: [] for kind in _ALL_KINDS},
        "unsupported": [],
        "line": node.line,
    }
    seen_celltype = seen_instance = False
    for item in args:
        head, item_args = _split_head(item)
        if head == "CELLTYPE":
            if seen_celltype:
                ctx.warn(item.line, "CELL 重复 CELLTYPE——取首个")
                continue
            seen_celltype = True
            cell["celltype"] = _cell_type_value(item_args, item.line, ctx)
        elif head == "INSTANCE":
            if seen_instance:
                ctx.warn(item.line, "CELL 重复 INSTANCE——取首个")
                continue
            seen_instance = True
            _apply_instance(cell, item_args, item.line, ctx)
        elif head == "DELAY":
            for deltype in item_args:
                dhead, dargs = _split_head(deltype)
                mode = _DELTYPE_MODES.get(dhead) if dhead is not None else None
                if mode is not None:
                    for del_def in dargs:
                        _parse_del_def(del_def, mode, ctx, cell)
                elif dhead in ("PATHPULSE", "PATHPULSEPERCENT"):
                    _parse_pathpulse(deltype, dhead, ctx, cell)
                else:
                    label = dhead if dhead is not None else render_sexpr(deltype)
                    ctx.warn(deltype.line, f"DELAY 内面外 deltype {label!r}"
                                           "——如实登记 unsupported")
                    _unsupported(cell, deltype, "DELAY 面外 deltype")
        elif head == "TIMINGCHECK":
            for tchk in item_args:
                _parse_tchk(tchk, ctx, cell)
        elif head in ("TIMINGENV", "LABEL"):
            ctx.warn(item.line, f"{head} 段本内核暂不解析——如实登记 unsupported 原文")
            _unsupported(cell, item, f"{head} 段（本内核面外）")
        else:
            label = head if head is not None else render_sexpr(item)
            ctx.warn(item.line, f"CELL 内面外构造 {label!r}——如实登记 unsupported")
            _unsupported(cell, item, "CELL 内面外构造")
    if not seen_celltype:
        ctx.warn(node.line, "CELL 缺 CELLTYPE——celltype 如实 None")
    if not seen_instance:
        ctx.warn(node.line, "CELL 缺 INSTANCE 子句——按 top-level（instance=None）处理")
    return cell


def _new_header() -> dict[str, Any]:
    return {
        "sdf_version": None,
        "design": None,
        "date": None,
        "vendor": None,
        "program": None,
        "version": None,
        "divider": DEFAULT_DIVIDER,
        "divider_source": "default",
        "voltage": None,
        "process": None,
        "temperature": None,
        "timescale": _timescale_entry(DEFAULT_TIMESCALE, "default"),
        "unknown": [],
    }


def _header_string(
    args: list[SdfAtom | SdfList], key: str, line: int, ctx: _Ctx
) -> str | None:
    if not args:
        ctx.warn(line, f"{key} 无值——如实 None")
        return None
    if len(args) == 1 and isinstance(args[0], SdfAtom):
        if not args[0].quoted:
            ctx.warn(line, f"{key} 值未加引号（IEEE 1497 为 QSTRING）——如实采纳")
        return args[0].text
    ctx.warn(line, f"{key} 值形态非常规（{len(args)} 个词元）——按空格拼接原文")
    return _render_items(args)


def _header_triple(
    args: list[SdfAtom | SdfList], key: str, line: int, ctx: _Ctx
) -> dict[str, Any] | None:
    """VOLTAGE/TEMPERATURE：rtriple 或单值（无括号原子形态；无时间换算）。"""
    if not args:
        ctx.warn(line, f"{key} 无值——如实 None")
        return None
    atoms = _bare_atoms(args)
    if atoms is None and len(args) == 1 and isinstance(args[0], SdfList):
        atoms = _bare_atoms(args[0].items)
    if atoms is None:
        raw = _render_items(args)
        ctx.warn(line, f"{key} 值形态非法 {raw}——三槽如实 None")
        return _invalid_triple(raw, scaled=False)
    triple = _triple_from_text("".join(atom.text for atom in atoms), None)
    if triple["form"] == "invalid":
        ctx.warn(line, f"{key} 值 {triple['raw']!r} 非法——三槽如实 None")
    return triple


def _apply_header(
    header: dict[str, Any], nodes: list[SdfAtom | SdfList], ctx: _Ctx,
    file_line: int,
) -> None:
    seen: set[str] = set()
    for node in nodes:
        key, args = _split_head(node)
        if key is None:  # 调用方只传闭集头部键节点，防御位
            continue
        if key in seen:
            ctx.warn(node.line, f"头部键 {key} 重复——后者覆盖前者")
        seen.add(key)
        field = _HEADER_FIELDS[key]
        if key == "TIMESCALE":
            if any(isinstance(arg, SdfList) for arg in args):
                raise SdfParseError(
                    f"第 {node.line} 行：TIMESCALE 形态非法 {render_sexpr(node)}——fail-closed")
            spec = "".join(arg.text for arg in args if isinstance(arg, SdfAtom))
            try:
                header["timescale"] = _timescale_entry(spec, "declared")
            except SdfParseError as exc:
                raise SdfParseError(f"第 {node.line} 行：{exc}") from exc
        elif key == "DIVIDER":
            if len(args) == 1 and isinstance(args[0], SdfAtom) and len(args[0].text) == 1:
                value = args[0].text
                if value not in (".", "/"):
                    ctx.warn(node.line, f"DIVIDER {value!r} 不在 IEEE 1497 闭集（. 或 /）"
                                        "——如实采用")
                header["divider"] = value
                header["divider_source"] = "declared"
            else:
                ctx.warn(node.line, f"DIVIDER 形态非法 {render_sexpr(node)}"
                                    f"——保持缺省 {DEFAULT_DIVIDER!r}")
        elif key in ("VOLTAGE", "TEMPERATURE"):
            header[field] = _header_triple(args, key, node.line, ctx)
        else:
            header[field] = _header_string(args, key, node.line, ctx)
    if "SDFVERSION" not in seen:
        ctx.warn(file_line, "缺 SDFVERSION（IEEE 1497 必备头部键）——sdf_version 如实 None")
    if "TIMESCALE" not in seen:
        ctx.warn(file_line, "缺 TIMESCALE——按 IEEE 1497 缺省 1ns 换算（source=default）")


def parse_sdf(text: str) -> dict[str, Any]:
    """SDF 文本 → 结构化 dict（纯函数零 IO；schema 见模块 docstring）。

    返回键集（PARSER_SCHEMA_VERSION=1.0 契约；全 JSON 原生类型）::

        {
          "schema": "sdf/1.0",
          "header": {sdf_version, design, date, vendor, program, version,
                     divider, divider_source, voltage, process,
                     temperature, timescale: {raw,key,multiplier,unit,
                     factor_s,source}, unknown: [{keyword,line,raw}]},
          "cells": [{index, celltype, instance, instance_wildcard,
                     instance_path, delays: {19 桶}, unsupported, line}],
          "celltypes": [str, ...],          # 去重，文档序
          "stats": {...计数面},
          "warnings": ["第 N 行：...", ...],  # 按行号稳定排序
        }

    空文本/缺 DELAYFILE 头/词法结构违规/未知 TIMESCALE →
    :class:`SdfParseError`（service 层转 error 信封）。
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    forms = parse_sexpr(text)
    if not forms:
        raise SdfParseError("空文本（无任何 S 表达式）——非 SDF 文件，拒绝解析")
    top_head, top_items = _split_head(forms[0])
    if top_head != "DELAYFILE":
        raise SdfParseError(
            f"第 {forms[0].line} 行：首个顶层表达式不是 (DELAYFILE ...)"
            "——缺 DELAYFILE 头，非 SDF 文件")
    raw_warnings: list[tuple[int, str]] = []
    if len(forms) > 1:
        raw_warnings.append((forms[1].line, f"DELAYFILE 之后另有 {len(forms) - 1} 个"
                                            "顶层表达式——忽略"))
    header = _new_header()
    header_nodes: list[SdfAtom | SdfList] = []
    cell_nodes: list[SdfAtom | SdfList] = []
    for item in top_items:
        head, _ = _split_head(item)
        if head == "CELL":
            cell_nodes.append(item)
        elif head in _HEADER_FIELDS:
            if cell_nodes:
                raw_warnings.append((item.line, f"头部键 {head} 出现在 CELL 之后"
                                                "（IEEE 1497 头部须先于 CELL）——如实采纳"))
            header_nodes.append(item)
        elif head is None:
            kind = "原子" if isinstance(item, SdfAtom) else "表达式"
            raw_warnings.append((item.line, f"DELAYFILE 内游离{kind} "
                                            f"{render_sexpr(item)!r}——跳过"))
        else:
            raw_warnings.append((item.line, f"未知头部键 {head}（非 IEEE 1497 头部键闭集）"
                                            "——原文保留于 header.unknown"))
            header["unknown"].append(
                {"keyword": head, "line": item.line, "raw": render_sexpr(item)})
    header_ctx = _Ctx(scale=Decimal(1), divider=DEFAULT_DIVIDER, warnings=raw_warnings)
    _apply_header(header, header_nodes, header_ctx, forms[0].line)
    ctx = _Ctx(
        scale=_TIMESCALE_DECIMAL[header["timescale"]["key"]],
        divider=header["divider"],
        warnings=raw_warnings,
    )
    cells = [_parse_cell(node, index, ctx) for index, node in enumerate(cell_nodes)]
    celltypes: list[str] = []
    for cell in cells:
        if cell["celltype"] is not None and cell["celltype"] not in celltypes:
            celltypes.append(cell["celltype"])
    warnings = [f"第 {line} 行：{message}"
                for line, message in sorted(raw_warnings, key=lambda w: w[0])]
    by_kind = {kind: sum(len(cell["delays"][kind]) for cell in cells)
               for kind in _ALL_KINDS}
    delay_entries = [entry for cell in cells for kind in DELAY_KINDS
                     for entry in cell["delays"][kind]]
    stats = {
        "n_cells": len(cells),
        "n_top_cells": sum(1 for c in cells
                           if c["instance"] is None and not c["instance_wildcard"]),
        "n_wildcard_cells": sum(1 for c in cells if c["instance_wildcard"]),
        "n_celltypes": len(celltypes),
        "n_delay_entries": len(delay_entries),
        "n_timing_checks": sum(by_kind[kind] for kind in TIMING_CHECK_KINDS),
        "n_cond_entries": sum(1 for e in delay_entries
                              if e["cond"] is not None or e["condelse"]),
        "n_absolute": sum(1 for e in delay_entries if e["mode"] == "absolute"),
        "n_increment": sum(1 for e in delay_entries if e["mode"] == "increment"),
        "n_unsupported": sum(len(c["unsupported"]) for c in cells),
        "n_unknown_header": len(header["unknown"]),
        "by_kind": by_kind,
        "n_warnings": len(warnings),
    }
    return {
        "schema": f"sdf/{PARSER_SCHEMA_VERSION}",
        "header": header,
        "cells": cells,
        "celltypes": celltypes,
        "stats": stats,
        "warnings": warnings,
    }


# ─── 查询三函数（纯派生视图；不改 doc）────────────────────────────────────


def sdf_cell_lookup(
    doc: dict[str, Any], celltype: str, instance: str | None = None
) -> list[dict[str, Any]]:
    """按 CELLTYPE+实例查 CELL（返回浅拷贝+match 键，按文档序）。

    匹配规则（IEEE 1497 通配语义如实）：

    - ``instance=None``：只命中 top-level 条目（``(INSTANCE)``，match=top）；
    - ``instance="*"``：只命中通配条目本身（match=wildcard）；
    - 具体实例名：命中 INSTANCE 原文**精确相等**条目（match=exact）+ 该
      CELLTYPE 的通配条目（match=wildcard——``(INSTANCE *)`` 适用该
      celltype 全部实例）；层次名不做分隔符归一。

    CELLTYPE 大小写敏感精确比较；未命中返回空表（调用方分型）。
    """
    matches: list[dict[str, Any]] = []
    for cell in doc["cells"]:
        if cell["celltype"] != celltype:
            continue
        match: str | None = None
        if instance is None:
            if cell["instance"] is None and not cell["instance_wildcard"]:
                match = "top"
        elif cell["instance_wildcard"]:
            match = "wildcard"
        elif instance != "*" and cell["instance"] == instance:
            match = "exact"
        if match is not None:
            matches.append({**cell, "match": match})
    return matches


def _seconds_view(triple: dict[str, Any] | None) -> dict[str, Any] | None:
    if triple is None:
        return None
    return {"min": triple.get("min_s"), "typ": triple.get("typ_s"),
            "max": triple.get("max_s")}


def sdf_delay_paths(doc: dict[str, Any], celltype: str) -> list[dict[str, Any]]:
    """该 celltype 全部 IOPATH/INTERCONNECT 平坦清单（from→to+rise/fall 秒值）。

    排序键=(CELL 文档序, 类别序 IOPATH<INTERCONNECT, from, to, 条目文档序)
    ——同端点多条（COND 变体/ABSOLUTE+INCREMENT 叠加）按文档序稳定。
    每行：kind/cell_index/celltype/instance/instance_wildcard/mode/from_pin/
    from_edge/to_pin/cond/cond_name/condelse/rise_s/fall_s（{min,typ,max}
    秒）/fall_inherited/line。未知 celltype 返回空表。
    """
    keyed: list[tuple[tuple[int, int, str, str, int], dict[str, Any]]] = []
    for cell in doc["cells"]:
        if cell["celltype"] != celltype:
            continue
        for rank, kind in enumerate(_PATH_KINDS):
            for seq, entry in enumerate(cell["delays"][kind]):
                row = {
                    "kind": kind,
                    "cell_index": cell["index"],
                    "celltype": cell["celltype"],
                    "instance": cell["instance"],
                    "instance_wildcard": cell["instance_wildcard"],
                    "mode": entry["mode"],
                    "from_pin": entry["from_pin"],
                    "from_edge": entry.get("from_edge"),
                    "to_pin": entry["to_pin"],
                    "cond": entry["cond"],
                    "cond_name": entry["cond_name"],
                    "condelse": entry["condelse"],
                    "rise_s": _seconds_view(entry["rise_triple"]),
                    "fall_s": _seconds_view(entry["fall_triple"]),
                    "fall_inherited": entry["fall_inherited"],
                    "line": entry["line"],
                }
                key = (cell["index"], rank, entry["from_pin"] or "",
                       entry["to_pin"] or "", seq)
                keyed.append((key, row))
    keyed.sort(key=lambda pair: pair[0])
    return [row for _, row in keyed]


def sdf_timing_check_summary(doc: dict[str, Any]) -> dict[str, Any]:
    """全库 TIMINGCHECK 十二类计数+每类最坏值（max of max 槽，秒）。

    最坏值口径：该类全部条目全部值的 max 槽秒值取最大（max 槽 None 跳过；
    并列取文档序首个）——setup/hold/width 等"越大越紧"语义统一。返回::

        {"n_timing_checks": int,
         "types_present": [有条目的类别，十二类定序],
         "by_type": {类别: {count, worst_max_s, worst_max,
                             worst_at: {cell_index, celltype, instance,
                                        pin, ref_pin, triple_index, line}
                                       | None}}}
    """
    by_type: dict[str, dict[str, Any]] = {}
    total = 0
    for kind in TIMING_CHECK_KINDS:
        count = 0
        worst_s: float | None = None
        worst_raw: float | None = None
        worst_at: dict[str, Any] | None = None
        for cell in doc["cells"]:
            for entry in cell["delays"][kind]:
                count += 1
                for index, triple in enumerate(entry["triples"]):
                    value = triple.get("max_s")
                    if value is None:
                        continue
                    if worst_s is None or value > worst_s:
                        worst_s = value
                        worst_raw = triple.get("max")
                        worst_at = {
                            "cell_index": cell["index"],
                            "celltype": cell["celltype"],
                            "instance": cell["instance"],
                            "pin": entry["pin"],
                            "ref_pin": entry["ref_pin"],
                            "triple_index": index,
                            "line": entry["line"],
                        }
        by_type[kind] = {
            "count": count,
            "worst_max_s": worst_s,
            "worst_max": worst_raw,
            "worst_at": worst_at,
        }
        total += count
    return {
        "n_timing_checks": total,
        "types_present": [kind for kind in TIMING_CHECK_KINDS
                          if by_type[kind]["count"]],
        "by_type": by_type,
    }


def sdf_celltype_summary(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """逐 celltype 汇总（首次出现序）：CELL 数/top/通配/具体实例数+延迟与检查条目数。"""
    order: list[str | None] = []
    acc: dict[str | None, dict[str, Any]] = {}
    for cell in doc["cells"]:
        celltype = cell["celltype"]
        if celltype not in acc:
            acc[celltype] = {
                "celltype": celltype,
                "n_cells": 0,
                "n_top": 0,
                "n_wildcard": 0,
                "n_instances": 0,
                "n_delay_entries": 0,
                "n_timing_checks": 0,
            }
            order.append(celltype)
        row = acc[celltype]
        row["n_cells"] += 1
        if cell["instance_wildcard"]:
            row["n_wildcard"] += 1
        elif cell["instance"] is None:
            row["n_top"] += 1
        else:
            row["n_instances"] += 1
        row["n_delay_entries"] += sum(len(cell["delays"][k]) for k in DELAY_KINDS)
        row["n_timing_checks"] += sum(
            len(cell["delays"][k]) for k in TIMING_CHECK_KINDS)
    return [acc[celltype] for celltype in order]
