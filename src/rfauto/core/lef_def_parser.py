"""LEF/DEF 物理设计交换格式结构化解析内核（aurora_q Q-X57，2026-11-07）。

LEF（Library Exchange Format）与 DEF（Design Exchange Format）5.8 语法
子集的只读结构化解析——OpenLane/OpenROAD 数字后端流程的科技库（LEF：
层/via/site/单元 macro 抽象）与版图（DEF：组件摆放/引脚/网/走线）交换
骨干格式（Q-X41 调研席确认）。数模混合/RF 用户读取 PnR 产物做结构分析
（单元闭合/网连接度/引脚名对齐）时的单源入口。词法与语义全部在 core
确定性内核（铁律 7：结构化数字只出自输入文本本身；LLM/agent 永不产生
物理数字）。服务包装见 :mod:`rfauto.service.lef_def_service`（规则 4
JSON 进出），CLI 薄壳见 cli/domains/lefdef.py。

词法（LEF/DEF 共用，:func:`tokenize_lefdef`）：

- 空白分词；``#`` 在词首起行注释（词中 ``#`` 属名字，如 ``net#1``）；
- 双引号字符串 ``"..."``（``\\`` 转义；未闭合不抛——吞到文末并记
  ``unterminated_string`` 警告，截断文件不崩）；
- ``;`` ``(`` ``)`` 恒为独立标点（``0.14;`` / ``(0 0)`` 贴身写法容忍）；
  唯一例外：词内已开的 ``(`` 由同词 ``)`` 配平（BUSBITCHARS ``"()"``
  形态的总线位名 ``a(0)`` 保持一词）；
- 语句无显式续行符——语句跨任意多行直到 ``;``（多行 COMPONENTS/NETS
  条目与单行同解）；
- **关键字大小写容忍**（``layer``/``LAYER`` 同义，比较一律走 Token.key
  大写归一）；**名字大小写敏感**（层名/单元名/网名比较走原文 text）。

LEF 语义面（:func:`parse_lef`）：VERSION/BUSBITCHARS/DIVIDERCHAR/
UNITS（``DATABASE MICRONS`` 等，键=``<量>_<单位>`` 小写如
``database_microns``）/MANUFACTURINGGRID；LAYER（TYPE ROUTING/CUT/
MASTERSLICE/OVERLAY/IMPLANT、DIRECTION、PITCH、WIDTH、SPACING（首值+
全部规则原文）、THICKNESS、OFFSET、MINWIDTH、AREA）；VIA（DEFAULT 标志+
RESISTANCE+LAYER/RECT/POLYGON 几何）；VIARULE（GENERATE/DEFAULT+逐层
DIRECTION/ENCLOSURE/WIDTH TO/RECT/SPACING BY/RESISTANCE+VIA 名录）；
SITE；MACRO（CLASS 主类+子类、SIZE、ORIGIN、FOREIGN、SYMMETRY、SITE；
PIN 段 DIRECTION INPUT/OUTPUT[TRISTATE]/INOUT/FEEDTHRU+USE SIGNAL/ANALOG/
POWER/GROUND/CLOCK+SHAPE+多 PORT 块（每 PORT 内 LAYER+RECT/POLYGON/PATH
多几何+VIA 落点，``port_index`` 区分）；OBS 段同 PORT 几何形态）。LEF
数值本身即 µm（``*_um`` 字段直取，无 DBU 换算；DATABASE MICRONS 只是给
DEF 消费方的 DBU 换算因子，原值落 units）。

DEF 语义面（:func:`parse_def`）：VERSION/DIVIDERCHAR/BUSBITCHARS/DESIGN/
TECHNOLOGY/UNITS DISTANCE MICRONS/DIEAREA（≥2 点，bbox 汇总）/ROW/
TRACKS；COMPONENTS（名+模型+PLACED/FIXED/COVER 坐标朝向/UNPLACED+
SOURCE）；PINS（NET/SPECIAL/DIRECTION/USE/PLACED·FIXED·COVER 坐标朝向/
LAYER+RECT/POLYGON/VIA，多 PORT ``port_index``）；NETS（连接 ``(comp
pin)``/``(PIN p)`` 列表+ROUTED/FIXED/COVER/NOSHIELD 走线段——层+路径点
（``*`` 沿用前点同轴值）+VIA 落点+NEW 分段+USE）；SPECIALNETS（同 NETS
形态容忍：走线段层名后的线宽、``+ SHAPE``/``+ STYLE`` 续接、``( * pin )``
通配连接）；VIAS（RECT/POLYGON 自定义形态+VIARULE 生成参数原文）；
END DESIGN 收尾。**DEF 坐标是 DBU 整数**：``*_dbu`` 落原值，``*_um`` =
DBU ÷ ``UNITS DISTANCE MICRONS``（预扫全文取换算因子，语句序无关）；缺
UNITS 时 ``*_um`` 如实 None（不臆造缺省因子）并记警告。DEF PINS 的
LAYER 几何按 DEF 语义是**相对引脚落点**的局部坐标，原样保留不做变换。
走线段 ``layer`` = 段首声明层（段内经 via 换层不追踪；via 名与落点
坐标如实登记在 ``vias``）。
节头声明计数（``COMPONENTS 3 ;``）与实际解析条目数对账入
``section_counts``，不等记 ``count_mismatch`` 警告。

fail-soft 纪律（#149/#208 家法）：未知关键字语句整句跳过记
``unknown_statement`` 警告（合法但未建模的 LEF/DEF 语句——ANTENNA*/
PROPERTY/SPACINGTABLE 等——收进 ``other_statements``/``other_options``
原文、不记警告：词表在本模块常量）；病态语句（缺值/非数值/括号不配平）
降级警告+跳语句，DEF 条目内单个 ``+`` 选项坏只丢该选项不丢条目；语句缺
``;`` 时读到 ``END``/条目起始 ``-`` 即止（防吞后续块）；块缺 END 时遇
新块头/外层 END 隐式收尾；解析器每步至少消费一个词（零进展死循环守卫）。
未建模的已知块（LEF PROPERTYDEFINITIONS/NONDEFAULTRULE/BEGINEXT…、DEF
REGIONS/BLOCKAGES/FILLS/SCANCHAINS/GROUPS…）整块跳过并登记。

拓扑提取三函数（LEF/DEF 无方向语义网表——驱动/负载判定一律不做，宁不
报不误报 #122 口径）：

- :func:`def_component_macro_closure`：COMPONENTS.model ⊆ LEF macros 键
  闭合校验（缺名表+逐缺名组件表如实返回；多份 LEF 合并口径）；
- :func:`def_net_connectivity`：逐网连接度、零连接悬空网、单连接网（信
  息桶非判错）、连接引用未知组件/未知顶层 PIN、引脚引用未知网；
- :func:`def_pin_lef_alignment`：DEF PINS 名 ↔ LEF 对应 macro（缺省=DEF
  DESIGN 同名 macro）引脚名双向缺席+方向不一致；实例级 ``(comp pin)``
  引用的引脚名在组件模型 macro 中缺席检测——字符串精确比较（不做转义
  归一），差异如实列表。

确定性（同输入同输出）、零 IO（纯文本进出）、零第三方依赖。本模块不设
``__all__``（无 __all__ 文件不进 tests/gold/public_api.json——
verilog_netlist_parser/sdc_parser 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: LEF LAYER TYPE 合法值（5.8 子集；IMPLANT 为 LEF 合法层型，容忍收录）。
LEF_LAYER_TYPES = ("ROUTING", "CUT", "MASTERSLICE", "OVERLAY", "IMPLANT")

#: LEF 布线层 DIRECTION 合法值。
LAYER_DIRECTIONS = ("HORIZONTAL", "VERTICAL", "DIAG45", "DIAG135")

#: 引脚方向合法值（LEF PIN DIRECTION 与 DEF PINS ``+ DIRECTION`` 同表）。
PIN_DIRECTIONS = ("INPUT", "OUTPUT", "INOUT", "FEEDTHRU")

#: LEF PIN USE 合法值。
LEF_PIN_USES = ("SIGNAL", "ANALOG", "POWER", "GROUND", "CLOCK")

#: DEF 网/引脚 USE 合法值（DEF 词表比 LEF 多 TIEOFF/SCAN/RESET）。
DEF_USES = ("SIGNAL", "ANALOG", "POWER", "GROUND", "CLOCK", "TIEOFF", "SCAN", "RESET")

#: LEF MACRO CLASS 主类合法值（子类=第二词，如 ``PAD INPUT``/``CORE TIEHIGH``）。
MACRO_CLASSES = ("COVER", "RING", "BLOCK", "PAD", "CORE", "ENDCAP")

#: DEF 摆放朝向合法值（N/S/E/W + 翻转 FN/FS/FE/FW；LEF FOREIGN 同表）。
ORIENTATIONS = ("N", "S", "E", "W", "FN", "FS", "FE", "FW")

#: DEF 组件/引脚摆放状态合法值。
PLACEMENT_STATUSES = ("PLACED", "FIXED", "COVER", "UNPLACED")

#: DEF 走线段状态关键字（NETS 常规走线 + SPECIALNETS ``SHIELD <net>``）。
ROUTE_STATUSES = ("ROUTED", "FIXED", "COVER", "NOSHIELD", "SHIELD")

# ── LEF 词表（已建模走字段；已知未建模收原文不记警告；其余=未知记警告）──

#: LEF 块起始关键字（块内语句位置出现=当前块缺 END 的隐式收尾信号；
#: 各作用域按自身合法语句再剔除，见 ``_LEF_*_FOREIGN``）。
_LEF_BLOCK_STARTERS = frozenset({
    "UNITS", "LAYER", "VIA", "VIARULE", "SITE", "MACRO", "NONDEFAULTRULE",
    "PROPERTYDEFINITIONS", "BEGINEXT", "IRDROP", "NOISETABLE",
    "CORRECTIONTABLE", "ARRAY",
})

#: LEF 顶层已知块 → 收尾词（None=以块名收尾 ``END <name>``；BEGINEXT 以
#: ``ENDEXT`` 收尾）。整块跳过登记 ``skipped_blocks``。
_LEF_TOP_SKIP_BLOCKS: dict[str, str | None] = {
    "PROPERTYDEFINITIONS": "PROPERTYDEFINITIONS",
    "SPACING": "SPACING",
    "IRDROP": "IRDROP",
    "NOISETABLE": "NOISETABLE",
    "CORRECTIONTABLE": "CORRECTIONTABLE",
    "NONDEFAULTRULE": None,
    "ARRAY": None,
    "BEGINEXT": "ENDEXT",
}

#: LEF 顶层已知简单语句（合法 LEF、本内核不建模；ANTENNA* 前缀同此）。
_LEF_TOP_KNOWN = frozenset({
    "NAMESCASESENSITIVE", "NOWIREEXTENSIONATPIN", "USEMINSPACING",
    "CLEARANCEMEASURE", "MAXVIASTACK", "FIXEDMASK", "MINFEATURE",
    "DIELECTRIC", "INPUTPINANTENNASIZE", "OUTPUTPINANTENNASIZE",
    "INOUTPINANTENNASIZE",
})

#: LEF 顶层全部关键字面（散落 ``END x`` 判 x 是否为名字用）。
_LEF_TOP_ALL = (
    frozenset({"VERSION", "BUSBITCHARS", "DIVIDERCHAR", "MANUFACTURINGGRID",
               "LIBRARY"})
    | _LEF_BLOCK_STARTERS | frozenset(_LEF_TOP_SKIP_BLOCKS) | _LEF_TOP_KNOWN
)

#: LAYER 块已知语句（含已建模键——二次出现的 WIDTH 等收原文不记警告）。
_LEF_LAYER_KNOWN = frozenset({
    "TYPE", "DIRECTION", "PITCH", "WIDTH", "SPACING", "THICKNESS", "OFFSET",
    "MINWIDTH", "AREA", "MASK", "RESISTANCE", "CAPACITANCE",
    "EDGECAPACITANCE", "HEIGHT", "WIREEXTENSION", "SHRINKAGE",
    "CAPMULTIPLIER", "MINENCLOSEDAREA", "MINSTEP", "MAXWIDTH", "MINIMUMCUT",
    "MINIMUMDENSITY", "MAXIMUMDENSITY", "DENSITYCHECKWINDOW",
    "DENSITYCHECKSTEP", "FILLACTIVESPACING", "PROTRUSIONWIDTH",
    "SPACINGTABLE", "WIDTHTABLE", "ENCLOSURE", "PREFERENCLOSURE",
    "ARRAYSPACING", "DIAGPITCH", "DIAGWIDTH", "DIAGSPACING",
    "DIAGMINEDGELENGTH", "MINSIZE", "PROPERTY", "ACCURRENTDENSITY",
    "DCCURRENTDENSITY", "FREQUENCY", "TABLEENTRIES", "CUTCLASS",
})
_LEF_LAYER_FOREIGN = _LEF_BLOCK_STARTERS

#: VIA 块已知语句（LEF 5.6+ 生成式 via 参数 VIARULE/CUTSIZE/… 收原文）。
_LEF_VIA_KNOWN = frozenset({
    "LAYER", "RECT", "POLYGON", "RESISTANCE", "PROPERTY", "VIARULE",
    "CUTSIZE", "LAYERS", "CUTSPACING", "ENCLOSURE", "ROWCOL", "ORIGIN",
    "OFFSET", "PATTERN", "FOREIGN",
})
_LEF_VIA_FOREIGN = _LEF_BLOCK_STARTERS - {"LAYER"}

#: VIARULE 块已知语句。
_LEF_VIARULE_KNOWN = frozenset({
    "LAYER", "VIA", "DIRECTION", "ENCLOSURE", "WIDTH", "RECT", "SPACING",
    "RESISTANCE", "OVERHANG", "METALOVERHANG", "PROPERTY",
})
_LEF_VIARULE_FOREIGN = _LEF_BLOCK_STARTERS - {"LAYER", "VIA"}

#: SITE 块已知语句。
_LEF_SITE_KNOWN = frozenset({"CLASS", "SYMMETRY", "SIZE", "ROWPATTERN", "PROPERTY"})
_LEF_SITE_FOREIGN = _LEF_BLOCK_STARTERS

#: MACRO 块已知语句与子块（PIN/OBS/DENSITY/TIMING 走子块分派）。
_LEF_MACRO_KNOWN = frozenset({
    "CLASS", "FOREIGN", "ORIGIN", "SIZE", "SYMMETRY", "SITE", "FIXEDMASK",
    "EEQ", "LEQ", "PROPERTY", "SOURCE", "POWER", "PIN", "OBS", "DENSITY",
    "TIMING",
})
_LEF_MACRO_FOREIGN = _LEF_BLOCK_STARTERS - {"SITE"}

#: PIN 块已知语句（电气特征类老语法整句收原文；ANTENNA* 前缀同此）。
_LEF_PIN_KNOWN = frozenset({
    "DIRECTION", "USE", "SHAPE", "PORT", "TAPERRULE", "NETEXPR",
    "SUPPLYSENSITIVITY", "GROUNDSENSITIVITY", "MUSTJOIN", "PROPERTY",
    "CAPACITANCE", "RESISTANCE", "LEAKAGE", "RISETHRESH", "FALLTHRESH",
    "RISESATCUR", "FALLSATCUR", "VLO", "VHI", "TIEOFFR",
    "RISEVOLTAGETHRESHOLD", "FALLVOLTAGETHRESHOLD", "RISESLEWLIMIT",
    "FALLSLEWLIMIT", "CURRENTSOURCE", "POWER", "INPUTNOISEMARGIN",
    "OUTPUTNOISEMARGIN", "OUTPUTRESISTANCE", "MAXDELAY", "MAXLOAD",
    "IV_TABLES", "FOREIGN",
})
_LEF_PIN_FOREIGN = (
    frozenset({"PIN", "OBS", "DENSITY", "TIMING"})
    | (_LEF_BLOCK_STARTERS - {"LAYER", "VIA", "SITE"})
)

#: PORT 块内合法语句（几何 + PORT CLASS）；PIN 级关键字出现=PORT 缺 END。
_LEF_GEOM_KEYS = frozenset({"LAYER", "RECT", "POLYGON", "PATH", "WIDTH", "VIA"})
_LEF_PORT_FOREIGN = (
    frozenset({"DIRECTION", "USE", "SHAPE", "PORT", "MUSTJOIN", "TAPERRULE",
               "NETEXPR", "SUPPLYSENSITIVITY", "GROUNDSENSITIVITY",
               "PROPERTY"})
    | _LEF_PIN_FOREIGN
)

#: OBS/DENSITY 块：MACRO 级关键字出现=该块缺 END。
_LEF_OBS_FOREIGN = (
    frozenset({"PIN", "OBS", "DENSITY", "CLASS", "FOREIGN", "ORIGIN", "SIZE",
               "SYMMETRY", "SITE", "EEQ", "LEQ", "PROPERTY", "FIXEDMASK",
               "SOURCE", "POWER", "TIMING"})
    | (_LEF_BLOCK_STARTERS - {"LAYER", "VIA"})
)

# ── DEF 词表 ──────────────────────────────────────────────────────────────

#: DEF 已建模条目节（节头 ``KEY n ;``+``- ... ;`` 条目+``END KEY``）。
_DEF_SECTIONS = ("VIAS", "COMPONENTS", "PINS", "SPECIALNETS", "NETS")

#: DEF 已知未建模节（整节跳过到 ``END KEY``，登记 ``skipped_sections``）。
_DEF_SKIP_SECTIONS = frozenset({
    "PROPERTYDEFINITIONS", "STYLES", "NONDEFAULTRULES", "REGIONS",
    "PINPROPERTIES", "BLOCKAGES", "SLOTS", "FILLS", "SCANCHAINS", "GROUPS",
})

#: DEF 顶层已知简单语句（不建模、收原文不记警告）。
_DEF_TOP_KNOWN = frozenset({
    "NAMESCASESENSITIVE", "HISTORY", "GCELLGRID", "COMPONENTMASKSHIFT",
})

#: DEF 顶层全部关键字面（节内出现=节缺 END 的隐式收尾信号）。
_DEF_TOP_ALL = (
    frozenset({"VERSION", "DIVIDERCHAR", "BUSBITCHARS", "DESIGN",
               "TECHNOLOGY", "UNITS", "DIEAREA", "ROW", "TRACKS",
               "BEGINEXT"})
    | frozenset(_DEF_SECTIONS) | _DEF_SKIP_SECTIONS | _DEF_TOP_KNOWN
)

#: COMPONENTS 条目已知未建模选项。
_DEF_COMP_KNOWN = frozenset({
    "EEQMASTER", "GENERATE", "WEIGHT", "REGION", "MASKSHIFT", "HALO",
    "ROUTEHALO", "PROPERTY", "FOREIGN",
})

#: PINS 条目已知未建模选项（ANTENNA* 前缀同此）。
_DEF_PIN_KNOWN = frozenset({
    "NETEXPR", "SUPPLYSENSITIVITY", "GROUNDSENSITIVITY", "PROPERTY",
})

#: NETS/SPECIALNETS 条目已知未建模选项。
_DEF_NET_KNOWN = frozenset({
    "SHIELDNET", "VPIN", "SUBNET", "XTALK", "NONDEFAULTRULE", "SOURCE",
    "FIXEDBUMP", "FREQUENCY", "ORIGINAL", "PATTERN", "ESTCAP", "WEIGHT",
    "PROPERTY", "VOLTAGE", "RECT", "POLYGON", "VIA",
})

#: 走线段续接选项（SPECIALNETS ``+ SHAPE``/``+ STYLE`` 属当前走线段）。
_DEF_ROUTE_CONTINUATION = frozenset({"SHAPE", "STYLE"})

#: VIAS 条目生成参数键（原文值表落 ``rule_params``）。
_DEF_VIA_RULE_PARAMS = frozenset({
    "CUTSIZE", "LAYERS", "CUTSPACING", "ENCLOSURE", "ROWCOL", "ORIGIN",
    "OFFSET", "PATTERN",
})


class LefDefParseError(ValueError):
    """LEF/DEF 语句级结构违规（ValueError 子类，带行号文本）。

    内核 fail-soft：语句/选项解析中抛出的本异常由安全包装捕获降级为
    ``warnings`` 条目，不穿透到 :func:`parse_lef`/:func:`parse_def`。
    """


# ── 词法（tokenizer）────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Token:
    """一个词：kind（word/str/punct）+ 原文 + 起始行号 + 关键字归一键。

    ``key`` = ``text.upper()``（word 专属，关键字大小写容忍比较用）；
    str/punct 的 key 为空串（永不与关键字相等）。名字比较一律用 ``text``
    原文（LEF/DEF 名字大小写敏感）。str 的 text 是去引号后的内容。
    """

    kind: str
    text: str
    line: int
    key: str = ""


def _scan(text: str) -> tuple[list[Token], list[dict[str, Any]]]:
    """词法主循环：文本 → (token 序列, 词法警告)。永不抛（截断容忍）。"""
    tokens: list[Token] = []
    issues: list[dict[str, Any]] = []
    i = 0
    n = len(text)
    line = 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if c == "#":
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if c == '"':
            start_line = line
            j = i + 1
            buf: list[str] = []
            closed = False
            while j < n:
                ch = text[j]
                if ch == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    if text[j + 1] == "\n":
                        line += 1
                    j += 2
                    continue
                if ch == '"':
                    closed = True
                    break
                if ch == "\n":
                    line += 1
                buf.append(ch)
                j += 1
            tokens.append(Token("str", "".join(buf), start_line))
            if closed:
                i = j + 1
            else:
                issues.append({
                    "line": start_line, "name": "unterminated_string",
                    "note": "字符串未闭合（吞到文末，截断文件容忍）"})
                i = n
            continue
        if c in ";()":
            tokens.append(Token("punct", c, line))
            i += 1
            continue
        j = i
        depth = 0  # 词内已开 '(' 的配平深度（总线位名 a(0) 保持一词）
        while j < n:
            ch = text[j]
            if ch.isspace() or ch == ";":
                break
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    break
                depth -= 1
            j += 1
        word = text[i:j]
        tokens.append(Token("word", word, line, word.upper()))
        i = j
    return tokens, issues


def tokenize_lefdef(text: str) -> list[Token]:
    """LEF/DEF 共用词法：文本 → token 序列（永不抛；词法警告随
    :func:`parse_lef`/:func:`parse_def` 的 ``warnings`` 披露）。"""
    return _scan(text)[0]


_INT_RE = re.compile(r"[+-]?\d+")
_NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def parse_lefdef_number(text: str) -> int | float | None:
    """LEF/DEF 数字字面量 → int（整数字面）/ float（含小数点或指数）/ None。

    ``nan``/``inf`` 等 Python float 能吃的非 LEF/DEF 字面一律 None（正则
    白名单，不走 ``float()`` 兜底）。
    """
    raw = text.strip()
    if _INT_RE.fullmatch(raw):
        return int(raw)
    if _NUM_RE.fullmatch(raw):
        return float(raw)
    return None


def _raw(tokens: list[Token]) -> str:
    """token 序列 → 语句原文（确定性重建：词间单空格、字符串回加引号）。"""
    return " ".join(f'"{t.text}"' if t.kind == "str" else t.text for t in tokens)


def _is_punct(tok: Token | None, text: str) -> bool:
    return tok is not None and tok.kind == "punct" and tok.text == text


def _split_plus(tokens: list[Token]) -> tuple[list[Token], list[list[Token]]]:
    """DEF 条目体按括号深度 0 的 ``+`` 切分 → (头部, 选项块列表)。

    括号内的 ``+``（NETS 连接 ``( u1 A + SYNTHESIZED )``）不切。
    """
    head: list[Token] = []
    opts: list[list[Token]] = []
    cur = head
    depth = 0
    for tok in tokens:
        if tok.kind == "punct":
            if tok.text == "(":
                depth += 1
            elif tok.text == ")":
                depth = max(0, depth - 1)
        if depth == 0 and tok.kind == "word" and tok.text == "+":
            cur = []
            opts.append(cur)
            continue
        cur.append(tok)
    return head, opts


# ── 解析游标基类 ────────────────────────────────────────────────────────────


class _Cursor:
    """token 游标 + 警告面 + 语句读取（LEF/DEF 解析器共用）。"""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.warnings: list[dict[str, Any]] = []

    def peek(self, ahead: int = 0) -> Token | None:
        idx = self.pos + ahead
        return self.tokens[idx] if idx < len(self.tokens) else None

    def next(self) -> Token | None:
        tok = self.peek()
        if tok is not None:
            self.pos += 1
        return tok

    def last_line(self) -> int:
        return self.tokens[-1].line if self.tokens else 0

    def warn(self, line: int, name: str, note: str) -> None:
        self.warnings.append({"line": line, "name": name, "note": note})

    def statement(self, *, stop_at_dash: bool = False) -> list[Token]:
        """读一条语句（首词无条件消费，读到 ``;`` 止并消费 ``;``）。

        缺 ``;`` 时遇 ``END``（及 DEF 条目起始 ``-``，``stop_at_dash``）
        即止且不消费——防一条坏语句吞掉后续块头/条目；EOF 同止。止于非
        ``;`` 记 ``missing_semicolon`` 警告。返回 ``;`` 前的 token 表
        （空语句 ``;`` 返回空表）。
        """
        first = self.next()
        if first is None or _is_punct(first, ";"):
            return []
        out = [first]
        while True:
            tok = self.peek()
            if tok is None:
                reason = "EOF"
                break
            if _is_punct(tok, ";"):
                self.pos += 1
                return out
            if tok.kind == "word" and (
                    tok.key == "END" or (stop_at_dash and tok.text == "-")):
                reason = f"遇 {tok.text}"
                break
            out.append(tok)
            self.pos += 1
        self.warn(first.line, "missing_semicolon",
                  f"{first.text} 语句缺 ';' 收尾（{reason}，已读部分照常解析）")
        return out

    def safe_stmt(self, fn: Callable[[list[Token]], Any], stmt: list[Token],
                  label: str | None = None) -> Any:
        """语句级 fail-soft：``fn(stmt)`` 抛 :class:`LefDefParseError` →
        记 ``statement_parse_failed`` 警告返回 None（语句已整句消费，
        无需重同步）。"""
        try:
            return fn(stmt)
        except LefDefParseError as exc:
            what = label or stmt[0].text
            self.warn(stmt[0].line, "statement_parse_failed",
                      f"{what} 语句解析失败降级跳过：{exc}")
            return None

    def skip_until_end(self, closer: str, *, keyword: bool, label: str,
                       line: int) -> None:
        """跳块直到 ``END <closer>``（keyword=True 大小写容忍；closer=
        ``ENDEXT`` 时跳到 ENDEXT 词）。EOF 兜底记 ``unterminated_block``。"""
        while True:
            tok = self.next()
            if tok is None:
                self.warn(line, "unterminated_block",
                          f"{label} 块未闭合（END {closer} 缺失，EOF 兜底）")
                return
            if tok.kind != "word":
                continue
            if closer == "ENDEXT":
                if tok.key == "ENDEXT":
                    return
                continue
            if tok.key == "END":
                nxt = self.peek()
                if nxt is not None and nxt.kind == "word" and (
                        nxt.key == closer if keyword else nxt.text == closer):
                    self.pos += 1
                    return

    def num(self, tok: Token | None, what: str) -> float:
        """LEF µm 数值（float 归一）；缺值/非数值抛 :class:`LefDefParseError`。"""
        if tok is None:
            raise LefDefParseError(f"{what} 缺数值")
        val = parse_lefdef_number(tok.text) if tok.kind == "word" else None
        if val is None:
            raise LefDefParseError(
                f"第 {tok.line} 行：{what} 期望数值，实得 {tok.text!r}")
        return float(val)

    def count(self, tok: Token | None, what: str) -> int:
        """非负整数（计数/阵列数）；缺值/非整数抛 :class:`LefDefParseError`。"""
        if tok is None:
            raise LefDefParseError(f"{what} 缺整数")
        val = parse_lefdef_number(tok.text) if tok.kind == "word" else None
        if not isinstance(val, int) or val < 0:
            raise LefDefParseError(
                f"第 {tok.line} 行：{what} 期望非负整数，实得 {tok.text!r}")
        return val

    def enum(self, args: list[Token], allowed: tuple[str, ...], what: str,
             line: int) -> str | None:
        """枚举值（大小写容忍归一大写）：缺值抛错；非法值记
        ``invalid_enum`` 警告并返回 None（字段如实缺席不臆断）。"""
        if not args:
            raise LefDefParseError(f"第 {line} 行：{what} 缺值")
        val = args[0].key
        if val in allowed:
            return val
        self.warn(line, "invalid_enum",
                  f"{what} 非法值 {args[0].text!r}（合法: {'/'.join(allowed)}；"
                  "字段记 None）")
        return None


# ── LEF 解析器 ──────────────────────────────────────────────────────────────


def _geom_group(layer: str | None, port_index: int | None) -> dict[str, Any]:
    """几何组（一个 LAYER 语句起的 RECT/POLYGON/PATH 收集桶）。"""
    group: dict[str, Any] = {}
    if port_index is not None:
        group["port_index"] = port_index
    group.update({"layer": layer, "rects": [], "polygons": [], "paths": []})
    return group


class _LefParser(_Cursor):
    """LEF 递归下降解析器（token 流 → LEF 文档；fail-soft 警告面）。"""

    def __init__(self, tokens: list[Token]) -> None:
        super().__init__(tokens)
        self.doc: dict[str, Any] = {
            "version": None,
            "bus_bit_chars": None,
            "divider_char": None,
            "units": {},
            "manufacturing_grid_um": None,
            "layers": [],
            "vias": [],
            "viarules": [],
            "sites": [],
            "macros": {},
            "macro_order": [],
            "skipped_blocks": [],
            "other_statements": [],
            "ended": False,
        }

    # ── 通用块循环 ──
    def other(self, container: dict[str, Any], stmt: list[Token], *,
              known: bool, scope: str) -> None:
        """未建模语句收原文；非已知词表的再记 ``unknown_statement`` 警告。"""
        container["other_statements"].append({
            "keyword": stmt[0].key, "raw": _raw(stmt), "line": stmt[0].line})
        if not known:
            self.warn(stmt[0].line, "unknown_statement",
                      f"{scope} 内未知语句 {stmt[0].text}（整句跳过）")

    def close_named(self, name: str, vocab: frozenset[str],
                    outer_names: tuple[str, ...], label: str) -> bool:
        """命名块遇 END：返回 True=块已收尾（消费或留给外层），False=散落
        END 已消费、块继续。

        判定序：``END <name>`` 正常收尾；``END LIBRARY``/``END <外层名>``
        =本块缺 END（不消费，留外层）；``END END``/``END <本块关键字>``/
        ``END <标点>`` =内层未知块的散落 END（只消费 END）；其余=块名
        不匹配（警告后按收尾处理）。
        """
        end_tok = self.peek()
        assert end_tok is not None
        nxt = self.peek(1)
        if nxt is None:
            self.pos += 1
            self.warn(end_tok.line, "unterminated_block",
                      f"{label} {name} 的 END 后缺块名（EOF）")
            return True
        if nxt.kind == "word" and nxt.text == name:
            self.pos += 2
            return True
        if nxt.kind == "word" and (nxt.key == "LIBRARY" or nxt.text in outer_names):
            self.warn(end_tok.line, "unterminated_block",
                      f"{label} {name} 未闭合（遇 END {nxt.text}，按隐式收尾处理）")
            return True
        if nxt.kind != "word" or nxt.key == "END" or nxt.key in vocab:
            self.pos += 1
            self.warn(end_tok.line, "stray_end",
                      f"{label} {name} 内散落 END（跳过）")
            return False
        self.pos += 2
        self.warn(end_tok.line, "end_name_mismatch",
                  f"{label} {name} 以 END {nxt.text} 收尾（名不匹配，按收尾处理）")
        return True

    def block_loop(self, name: str, vocab: frozenset[str],
                   foreign: frozenset[str],
                   on_stmt: Callable[[list[Token]], None], label: str, *,
                   on_keyword: dict[str, Callable[[], None]] | None = None,
                   outer_names: tuple[str, ...] = ()) -> None:
        """命名块体主循环（``END <name>`` 收尾；foreign 关键字=隐式收尾）。"""
        while True:
            tok = self.peek()
            if tok is None:
                self.warn(self.last_line(), "unterminated_block",
                          f"{label} {name} 未闭合（EOF 兜底）")
                return
            if tok.kind != "word":
                if not _is_punct(tok, ";"):
                    self.warn(tok.line, "stray_token",
                              f"{label} {name} 内散落 {tok.text!r}（跳过）")
                self.pos += 1
                continue
            if tok.key == "END":
                if self.close_named(name, vocab, outer_names, label):
                    return
                continue
            if tok.key in foreign and not self.inline_form():
                self.warn(tok.line, "unterminated_block",
                          f"{label} {name} 未闭合（遇 {tok.text} 起新块，按隐式收尾处理）")
                return
            if on_keyword and tok.key in on_keyword:
                on_keyword[tok.key]()
                continue
            stmt = self.statement()
            if stmt:
                self.safe_stmt(on_stmt, stmt)

    def inline_form(self) -> bool:
        """游标处关键字是否为 ``KEY name ;`` 单行语句形态（非块头）。

        LEF 块头（``VIA name``/``VIARULE name``/``SITE name``…）名后从不
        紧跟 ``;``；生成式 VIA 体内的 ``VIARULE ruleName ;`` 即此形态——
        不得误判为新块起始。名为纯数字的（``NOISETABLE 1 ;`` 类表头）除外。
        """
        name_tok = self.peek(1)
        return (name_tok is not None and name_tok.kind == "word"
                and parse_lefdef_number(name_tok.text) is None
                and _is_punct(self.peek(2), ";"))

    def bare_block_loop(self, outer_name: str, foreign: frozenset[str],
                        on_stmt: Callable[[list[Token]], None], label: str,
                        line: int) -> None:
        """裸 END 收尾块（PORT/OBS/DENSITY）主循环。

        ``END <外层名>``=本块缺 END（不消费留外层）；其余 ``END`` 只消费
        END 本身收尾；PIN/MACRO 级关键字出现=隐式收尾。
        """
        while True:
            tok = self.peek()
            if tok is None:
                self.warn(line, "unterminated_block", f"{label} 块未闭合（EOF 兜底）")
                return
            if tok.kind != "word":
                if not _is_punct(tok, ";"):
                    self.warn(tok.line, "stray_token",
                              f"{label} 块内散落 {tok.text!r}（跳过）")
                self.pos += 1
                continue
            if tok.key == "END":
                nxt = self.peek(1)
                if nxt is not None and nxt.kind == "word" and nxt.text == outer_name:
                    self.warn(tok.line, "unterminated_block",
                              f"{label} 块未闭合（遇 END {outer_name}，按隐式收尾处理）")
                    return
                self.pos += 1
                return
            if tok.key in foreign or tok.key.startswith("ANTENNA"):
                self.warn(tok.line, "unterminated_block",
                          f"{label} 块未闭合（遇 {tok.text}，按隐式收尾处理）")
                return
            stmt = self.statement()
            if stmt:
                self.safe_stmt(on_stmt, stmt)

    def block_name(self, hdr: Token, label: str) -> str | None:
        """块头名（缺名=记 ``missing_name`` 警告返回 None，调用方放弃该块）。"""
        tok = self.peek()
        if tok is None or tok.kind != "word":
            self.warn(hdr.line, "missing_name", f"{label} 缺名（块跳过）")
            return None
        self.pos += 1
        return tok.text

    # ── 顶层 ──
    def parse(self) -> None:
        handlers: dict[str, Callable[[], None]] = {
            "UNITS": self.parse_units,
            "LAYER": self.parse_layer,
            "VIA": self.parse_via,
            "VIARULE": self.parse_viarule,
            "SITE": self.parse_site,
            "MACRO": self.parse_macro,
        }
        while True:
            tok = self.peek()
            if tok is None:
                return
            if tok.kind != "word":
                if not _is_punct(tok, ";"):
                    self.warn(tok.line, "stray_token", f"顶层散落 {tok.text!r}（跳过）")
                self.pos += 1
                continue
            key = tok.key
            if key == "END":
                nxt = self.peek(1)
                if nxt is not None and nxt.kind == "word" and nxt.key == "LIBRARY":
                    self.pos += 2
                    self.doc["ended"] = True
                    rest = self.peek()
                    if rest is not None:
                        self.warn(rest.line, "trailing_after_end",
                                  f"END LIBRARY 之后仍有 {len(self.tokens) - self.pos} 个词（忽略）")
                    return
                self.warn(tok.line, "stray_end", "顶层散落 END（无对应块，跳过）")
                self.pos += 1
                if nxt is not None and nxt.kind == "word" and nxt.key not in _LEF_TOP_ALL:
                    self.pos += 1  # END <名字> 整体跳过
                continue
            handler = handlers.get(key)
            if handler is not None:
                handler()
                continue
            if key in _LEF_TOP_SKIP_BLOCKS:
                self.skip_top_block(key)
                continue
            stmt = self.statement()
            if stmt:
                self.safe_stmt(self.apply_top_stmt, stmt)

    def apply_top_stmt(self, stmt: list[Token]) -> None:
        key = stmt[0].key
        args = stmt[1:]
        if key in ("VERSION", "BUSBITCHARS", "DIVIDERCHAR"):
            if not args:
                raise LefDefParseError(f"第 {stmt[0].line} 行：{stmt[0].text} 缺值")
            field_name = {"VERSION": "version", "BUSBITCHARS": "bus_bit_chars",
                          "DIVIDERCHAR": "divider_char"}[key]
            self.doc[field_name] = args[0].text
            return
        if key == "MANUFACTURINGGRID":
            self.doc["manufacturing_grid_um"] = self.num(
                args[0] if args else None, "MANUFACTURINGGRID")
            return
        self.other(self.doc, stmt,
                   known=key in _LEF_TOP_KNOWN or key.startswith("ANTENNA"),
                   scope="LEF 顶层")

    def skip_top_block(self, key: str) -> None:
        """顶层已知未建模块整块跳过（登记 skipped_blocks）。"""
        hdr = self.next()
        assert hdr is not None
        closer = _LEF_TOP_SKIP_BLOCKS[key]
        name: str | None = None
        if closer is None:
            name = self.block_name(hdr, key)
            if name is None:
                return
            self.skip_until_end(name, keyword=False, label=key, line=hdr.line)
        else:
            self.skip_until_end(closer, keyword=True, label=key, line=hdr.line)
        self.doc["skipped_blocks"].append(
            {"keyword": key, "name": name, "line": hdr.line})

    def parse_units(self) -> None:
        """``UNITS ... END UNITS``：``<量> <单位> 值 ;`` → units[<量>_<单位>]。"""
        hdr = self.next()
        assert hdr is not None
        while True:
            tok = self.peek()
            if tok is None:
                self.warn(hdr.line, "unterminated_block", "UNITS 块未闭合（EOF 兜底）")
                return
            if tok.kind != "word":
                self.pos += 1
                continue
            if tok.key == "END":
                nxt = self.peek(1)
                if nxt is not None and nxt.kind == "word" and nxt.key == "UNITS":
                    self.pos += 2
                    return
                self.warn(tok.line, "unterminated_block",
                          "UNITS 块未闭合（遇非 END UNITS 的 END，按隐式收尾处理）")
                return
            if tok.key in _LEF_BLOCK_STARTERS:
                self.warn(tok.line, "unterminated_block",
                          f"UNITS 块未闭合（遇 {tok.text}，按隐式收尾处理）")
                return
            stmt = self.statement()
            if stmt:
                self.safe_stmt(self.apply_units_stmt, stmt)

    def apply_units_stmt(self, stmt: list[Token]) -> None:
        if len(stmt) < 3:
            raise LefDefParseError(
                f"第 {stmt[0].line} 行：UNITS 条目期望 '<量> <单位> 值'，实得 {_raw(stmt)!r}")
        val = parse_lefdef_number(stmt[2].text) if stmt[2].kind == "word" else None
        if val is None:
            raise LefDefParseError(
                f"第 {stmt[0].line} 行：UNITS {stmt[0].text} 值非数值 {stmt[2].text!r}")
        self.doc["units"][f"{stmt[0].key.lower()}_{stmt[1].key.lower()}"] = val

    # ── LAYER ──
    def parse_layer(self) -> None:
        hdr = self.next()
        assert hdr is not None
        name = self.block_name(hdr, "LAYER")
        if name is None:
            return
        layer: dict[str, Any] = {
            "name": name, "type": None, "direction": None,
            "pitch_um": None, "pitch_y_um": None, "width_um": None,
            "spacing_um": None, "spacing_rules": [], "thickness_um": None,
            "offset_um": None, "offset_y_um": None, "min_width_um": None,
            "area_um2": None, "other_statements": [], "line": hdr.line,
        }
        self.block_loop(name, _LEF_LAYER_KNOWN, _LEF_LAYER_FOREIGN,
                        lambda s: self.apply_layer_stmt(layer, s), "LAYER")
        if any(lay["name"] == name for lay in self.doc["layers"]):
            self.warn(hdr.line, "duplicate_layer", f"LAYER {name} 重复定义（两份均保留）")
        self.doc["layers"].append(layer)

    def apply_layer_stmt(self, layer: dict[str, Any], stmt: list[Token]) -> None:
        key = stmt[0].key
        args = stmt[1:]
        line = stmt[0].line
        if key == "TYPE":
            layer["type"] = self.enum(args, LEF_LAYER_TYPES, "LAYER TYPE", line)
        elif key == "DIRECTION":
            layer["direction"] = self.enum(args, LAYER_DIRECTIONS, "LAYER DIRECTION", line)
        elif key == "PITCH":
            vals = [self.num(t, "PITCH") for t in args]
            if not vals:
                raise LefDefParseError(f"第 {line} 行：PITCH 缺值")
            layer["pitch_um"] = vals[0]
            layer["pitch_y_um"] = vals[1] if len(vals) > 1 else None
        elif key == "WIDTH" and layer["width_um"] is None and len(args) == 1:
            layer["width_um"] = self.num(args[0], "WIDTH")
        elif key == "SPACING":
            first = self.num(args[0] if args else None, "SPACING")
            layer["spacing_rules"].append(_raw(stmt))
            if layer["spacing_um"] is None:
                layer["spacing_um"] = first
        elif key == "THICKNESS":
            layer["thickness_um"] = self.num(args[0] if args else None, "THICKNESS")
        elif key == "OFFSET":
            vals = [self.num(t, "OFFSET") for t in args]
            if not vals:
                raise LefDefParseError(f"第 {line} 行：OFFSET 缺值")
            layer["offset_um"] = vals[0]
            layer["offset_y_um"] = vals[1] if len(vals) > 1 else None
        elif key == "MINWIDTH":
            layer["min_width_um"] = self.num(args[0] if args else None, "MINWIDTH")
        elif key == "AREA":
            layer["area_um2"] = self.num(args[0] if args else None, "AREA")
        else:
            self.other(layer, stmt,
                       known=key in _LEF_LAYER_KNOWN or key.startswith("ANTENNA"),
                       scope=f"LAYER {layer['name']}")

    # ── 几何（VIA/PORT/OBS 共用）──
    def geom_values(self, stmt: list[Token]) -> list[float]:
        """RECT/POLYGON/PATH 数值表（剥 ``MASK n`` 前缀与容忍括号；ITERATE
        阵列形态不在子集→抛错交安全包装降级）。"""
        args = list(stmt[1:])
        if args and args[0].key == "MASK":
            args = args[2:]
        if any(t.key == "ITERATE" for t in args):
            raise LefDefParseError(
                f"第 {stmt[0].line} 行：{stmt[0].text} ITERATE 阵列形态不在解析子集")
        return [self.num(t, stmt[0].text) for t in args if t.kind != "punct"]

    def apply_geometry(self, acc: dict[str, Any], stmt: list[Token]) -> bool:
        """几何语句 → acc（groups/vias/current/width/port_index）；非几何
        关键字返回 False（调用方按作用域处置）。"""
        key = stmt[0].key
        args = stmt[1:]
        line = stmt[0].line
        if key == "LAYER":
            if not args or args[0].kind != "word":
                raise LefDefParseError(f"第 {line} 行：LAYER 缺层名")
            group = _geom_group(args[0].text, acc["port_index"])
            acc["groups"].append(group)
            acc["current"] = group
            acc["width"] = None
            return True
        if key in ("RECT", "POLYGON", "PATH"):
            vals = self.geom_values(stmt)
            if key == "RECT" and len(vals) != 4:
                raise LefDefParseError(f"第 {line} 行：RECT 期望 4 个数值，实得 {len(vals)}")
            if key == "POLYGON" and (len(vals) < 6 or len(vals) % 2):
                raise LefDefParseError(
                    f"第 {line} 行：POLYGON 期望 ≥3 个点（偶数个数值），实得 {len(vals)}")
            if key == "PATH" and (len(vals) < 2 or len(vals) % 2):
                raise LefDefParseError(
                    f"第 {line} 行：PATH 期望 ≥1 个点（偶数个数值），实得 {len(vals)}")
            group = acc["current"]
            if group is None:
                self.warn(line, "geometry_without_layer",
                          f"{stmt[0].text} 出现在任何 LAYER 之前（层名记 None）")
                group = _geom_group(None, acc["port_index"])
                acc["groups"].append(group)
                acc["current"] = group
            if key == "RECT":
                group["rects"].append(vals)
            else:
                pts = [[vals[k], vals[k + 1]] for k in range(0, len(vals), 2)]
                if key == "POLYGON":
                    group["polygons"].append(pts)
                else:
                    group["paths"].append({"width_um": acc["width"], "points": pts})
            return True
        if key == "WIDTH":
            acc["width"] = self.num(args[0] if args else None, "WIDTH")
            return True
        if key == "VIA":
            rest = [t for t in args if t.kind != "punct"]
            if rest and rest[0].key == "MASK":
                rest = rest[2:]
            if any(t.key == "ITERATE" for t in rest):
                raise LefDefParseError(f"第 {line} 行：VIA ITERATE 阵列形态不在解析子集")
            if len(rest) < 3:
                raise LefDefParseError(f"第 {line} 行：VIA 期望 'x y viaName'，实得 {_raw(stmt)!r}")
            entry: dict[str, Any] = {}
            if acc["port_index"] is not None:
                entry["port_index"] = acc["port_index"]
            entry.update({"name": rest[2].text,
                          "x_um": self.num(rest[0], "VIA x"),
                          "y_um": self.num(rest[1], "VIA y")})
            acc["vias"].append(entry)
            return True
        return False

    # ── VIA / VIARULE / SITE ──
    def parse_via(self) -> None:
        hdr = self.next()
        assert hdr is not None
        name = self.block_name(hdr, "VIA")
        if name is None:
            return
        via: dict[str, Any] = {
            "name": name, "default": False, "generated": False,
            "resistance": None, "layers": [], "other_statements": [],
            "line": hdr.line,
        }
        while True:  # 头部标志（头行无 ';'）
            tok = self.peek()
            if tok is None or tok.kind != "word" or tok.key not in (
                    "DEFAULT", "GENERATED", "TOPOFSTACKONLY"):
                break
            self.pos += 1
            if tok.key == "DEFAULT":
                via["default"] = True
            elif tok.key == "GENERATED":
                via["generated"] = True
        acc: dict[str, Any] = {"groups": via["layers"], "vias": [], "current": None,
                               "width": None, "port_index": None}

        def on_stmt(stmt: list[Token]) -> None:
            key = stmt[0].key
            if key == "RESISTANCE":
                via["resistance"] = self.num(stmt[1] if len(stmt) > 1 else None,
                                             "RESISTANCE")
            elif key in ("LAYER", "RECT", "POLYGON"):
                self.apply_geometry(acc, stmt)
            else:
                self.other(via, stmt, known=key in _LEF_VIA_KNOWN, scope=f"VIA {name}")

        self.block_loop(name, _LEF_VIA_KNOWN, _LEF_VIA_FOREIGN, on_stmt, "VIA")
        self.doc["vias"].append(via)

    def parse_viarule(self) -> None:
        hdr = self.next()
        assert hdr is not None
        name = self.block_name(hdr, "VIARULE")
        if name is None:
            return
        rule: dict[str, Any] = {
            "name": name, "generate": False, "default": False, "layers": [],
            "vias": [], "other_statements": [], "line": hdr.line,
        }
        while True:
            tok = self.peek()
            if tok is None or tok.kind != "word" or tok.key not in ("GENERATE", "DEFAULT"):
                break
            self.pos += 1
            rule["generate" if tok.key == "GENERATE" else "default"] = True
        state: dict[str, Any] = {"current": None}

        def on_stmt(stmt: list[Token]) -> None:
            key = stmt[0].key
            args = stmt[1:]
            line = stmt[0].line
            if key == "LAYER":
                if not args or args[0].kind != "word":
                    raise LefDefParseError(f"第 {line} 行：LAYER 缺层名")
                state["current"] = {
                    "layer": args[0].text, "direction": None,
                    "enclosure_um": None, "width_range_um": None, "rects": [],
                    "spacing_um": None, "resistance": None,
                }
                rule["layers"].append(state["current"])
                return
            if key == "VIA":
                if not args:
                    raise LefDefParseError(f"第 {line} 行：VIA 缺 via 名")
                rule["vias"].append(args[0].text)
                return
            cur = state["current"]
            if key in ("DIRECTION", "ENCLOSURE", "WIDTH", "RECT", "SPACING",
                       "RESISTANCE") and cur is None:
                raise LefDefParseError(f"第 {line} 行：{stmt[0].text} 出现在任何 LAYER 之前")
            if key == "DIRECTION":
                cur["direction"] = self.enum(args, LAYER_DIRECTIONS, "VIARULE DIRECTION", line)
            elif key == "ENCLOSURE":
                vals = [self.num(t, "ENCLOSURE") for t in args[:2]]
                if len(vals) != 2:
                    raise LefDefParseError(f"第 {line} 行：ENCLOSURE 期望 2 个数值")
                cur["enclosure_um"] = vals
            elif key == "WIDTH":
                if len(args) < 3 or args[1].key != "TO":
                    raise LefDefParseError(f"第 {line} 行：WIDTH 期望 'min TO max'")
                cur["width_range_um"] = [self.num(args[0], "WIDTH min"),
                                         self.num(args[2], "WIDTH max")]
            elif key == "RECT":
                vals = self.geom_values(stmt)
                if len(vals) != 4:
                    raise LefDefParseError(f"第 {line} 行：RECT 期望 4 个数值，实得 {len(vals)}")
                cur["rects"].append(vals)
            elif key == "SPACING":
                if len(args) < 3 or args[1].key != "BY":
                    raise LefDefParseError(f"第 {line} 行：SPACING 期望 'x BY y'")
                cur["spacing_um"] = [self.num(args[0], "SPACING x"),
                                     self.num(args[2], "SPACING y")]
            elif key == "RESISTANCE":
                cur["resistance"] = self.num(args[0] if args else None, "RESISTANCE")
            else:
                self.other(rule, stmt, known=key in _LEF_VIARULE_KNOWN,
                           scope=f"VIARULE {name}")

        self.block_loop(name, _LEF_VIARULE_KNOWN, _LEF_VIARULE_FOREIGN, on_stmt, "VIARULE")
        self.doc["viarules"].append(rule)

    def size_of(self, args: list[Token], line: int) -> dict[str, float]:
        """``SIZE w BY h`` 参数 → ``{width_um, height_um}``。"""
        if len(args) < 3 or args[1].key != "BY":
            raise LefDefParseError(f"第 {line} 行：SIZE 期望 'w BY h'")
        return {"width_um": self.num(args[0], "SIZE w"),
                "height_um": self.num(args[2], "SIZE h")}

    def parse_site(self) -> None:
        hdr = self.next()
        assert hdr is not None
        name = self.block_name(hdr, "SITE")
        if name is None:
            return
        site: dict[str, Any] = {"name": name, "class": None, "symmetry": [],
                                "size": None, "other_statements": [], "line": hdr.line}

        def on_stmt(stmt: list[Token]) -> None:
            key = stmt[0].key
            args = stmt[1:]
            if key == "CLASS":
                site["class"] = self.enum(args, ("PAD", "CORE"), "SITE CLASS", stmt[0].line)
            elif key == "SYMMETRY":
                site["symmetry"] = [t.key for t in args]
            elif key == "SIZE":
                site["size"] = self.size_of(args, stmt[0].line)
            else:
                self.other(site, stmt, known=key in _LEF_SITE_KNOWN, scope=f"SITE {name}")

        self.block_loop(name, _LEF_SITE_KNOWN, _LEF_SITE_FOREIGN, on_stmt, "SITE")
        self.doc["sites"].append(site)

    # ── MACRO / PIN / PORT / OBS ──
    def parse_macro(self) -> None:
        hdr = self.next()
        assert hdr is not None
        name = self.block_name(hdr, "MACRO")
        if name is None:
            return
        macro: dict[str, Any] = {
            "name": name, "class": None, "class_subtype": None,
            "foreign": None, "origin": None, "size": None, "symmetry": [],
            "site": None, "pins": {}, "pin_order": [], "obs_geoms": [],
            "obs_vias": [], "other_statements": [], "line": hdr.line,
        }
        self.block_loop(
            name, _LEF_MACRO_KNOWN, _LEF_MACRO_FOREIGN,
            lambda s: self.apply_macro_stmt(macro, s), "MACRO",
            on_keyword={
                "PIN": lambda: self.parse_pin(macro),
                "OBS": lambda: self.parse_obs(macro),
                "DENSITY": lambda: self.parse_density(macro),
                "TIMING": lambda: self.skip_macro_timing(macro),
            })
        if name in self.doc["macros"]:
            self.warn(hdr.line, "duplicate_macro", f"MACRO {name} 重复定义（后者覆盖前者）")
        else:
            self.doc["macro_order"].append(name)
        self.doc["macros"][name] = macro

    def apply_macro_stmt(self, macro: dict[str, Any], stmt: list[Token]) -> None:
        key = stmt[0].key
        args = stmt[1:]
        line = stmt[0].line
        if key == "CLASS":
            macro["class"] = self.enum(args, MACRO_CLASSES, "MACRO CLASS", line)
            macro["class_subtype"] = args[1].key if len(args) > 1 else None
        elif key == "FOREIGN":
            if not args:
                raise LefDefParseError(f"第 {line} 行：FOREIGN 缺单元名")
            rest = [t for t in args[1:] if t.kind == "word"]
            foreign: dict[str, Any] = {"name": args[0].text, "x_um": None,
                                       "y_um": None, "orientation": None}
            if len(rest) >= 2:
                foreign["x_um"] = self.num(rest[0], "FOREIGN x")
                foreign["y_um"] = self.num(rest[1], "FOREIGN y")
            if len(rest) >= 3:
                foreign["orientation"] = self.enum(rest[2:], ORIENTATIONS,
                                                   "FOREIGN 朝向", line)
            macro["foreign"] = foreign
        elif key == "ORIGIN":
            rest = [t for t in args if t.kind == "word"]
            if len(rest) < 2:
                raise LefDefParseError(f"第 {line} 行：ORIGIN 期望 'x y'")
            macro["origin"] = {"x_um": self.num(rest[0], "ORIGIN x"),
                               "y_um": self.num(rest[1], "ORIGIN y")}
        elif key == "SIZE":
            macro["size"] = self.size_of(args, line)
        elif key == "SYMMETRY":
            macro["symmetry"] = [t.key for t in args]
        elif key == "SITE" and macro["site"] is None and args:
            macro["site"] = args[0].text
        else:
            self.other(macro, stmt, known=key in _LEF_MACRO_KNOWN,
                       scope=f"MACRO {macro['name']}")

    def parse_pin(self, macro: dict[str, Any]) -> None:
        hdr = self.next()
        assert hdr is not None
        name = self.block_name(hdr, "PIN")
        if name is None:
            return
        pin: dict[str, Any] = {
            "name": name, "direction": None, "tristate": False, "use": None,
            "shape": None, "port_geoms": [], "port_vias": [], "n_ports": 0,
            "other_statements": [], "line": hdr.line,
        }
        self.block_loop(
            name, _LEF_PIN_KNOWN, _LEF_PIN_FOREIGN,
            lambda s: self.apply_pin_stmt(pin, s), "PIN",
            on_keyword={"PORT": lambda: self.parse_port(pin)},
            outer_names=(macro["name"],))
        if name in macro["pins"]:
            self.warn(hdr.line, "duplicate_pin",
                      f"MACRO {macro['name']} 的 PIN {name} 重复定义（后者覆盖前者）")
        else:
            macro["pin_order"].append(name)
        macro["pins"][name] = pin

    def apply_pin_stmt(self, pin: dict[str, Any], stmt: list[Token]) -> None:
        key = stmt[0].key
        args = stmt[1:]
        line = stmt[0].line
        if key == "DIRECTION":
            pin["direction"] = self.enum(args, PIN_DIRECTIONS, "PIN DIRECTION", line)
            pin["tristate"] = len(args) > 1 and args[1].key == "TRISTATE"
        elif key == "USE":
            pin["use"] = self.enum(args, LEF_PIN_USES, "PIN USE", line)
        elif key == "SHAPE":
            pin["shape"] = self.enum(args, ("ABUTMENT", "RING", "FEEDTHRU"), "PIN SHAPE", line)
        else:
            self.other(pin, stmt,
                       known=key in _LEF_PIN_KNOWN or key.startswith("ANTENNA"),
                       scope=f"PIN {pin['name']}")

    def parse_port(self, pin: dict[str, Any]) -> None:
        hdr = self.next()
        assert hdr is not None
        acc: dict[str, Any] = {"groups": pin["port_geoms"], "vias": pin["port_vias"],
                               "current": None, "width": None,
                               "port_index": pin["n_ports"]}
        pin["n_ports"] += 1

        def on_stmt(stmt: list[Token]) -> None:
            if self.apply_geometry(acc, stmt):
                return
            self.other(pin, stmt, known=stmt[0].key == "CLASS",
                       scope=f"PIN {pin['name']} PORT")

        self.bare_block_loop(pin["name"], _LEF_PORT_FOREIGN, on_stmt, "PORT", hdr.line)

    def parse_obs(self, macro: dict[str, Any]) -> None:
        hdr = self.next()
        assert hdr is not None
        acc: dict[str, Any] = {"groups": macro["obs_geoms"], "vias": macro["obs_vias"],
                               "current": None, "width": None, "port_index": None}

        def on_stmt(stmt: list[Token]) -> None:
            if stmt[0].key in _LEF_GEOM_KEYS and self.apply_geometry(acc, stmt):
                return
            self.other(macro, stmt, known=False, scope=f"MACRO {macro['name']} OBS")

        self.bare_block_loop(macro["name"], _LEF_OBS_FOREIGN, on_stmt, "OBS", hdr.line)

    def parse_density(self, macro: dict[str, Any]) -> None:
        """DENSITY 块（已知未建模）：逐语句收原文进 macro other_statements。"""
        hdr = self.next()
        assert hdr is not None
        macro["other_statements"].append(
            {"keyword": "DENSITY", "raw": "DENSITY", "line": hdr.line})
        self.bare_block_loop(
            macro["name"], _LEF_OBS_FOREIGN,
            lambda s: self.other(macro, s, known=True, scope="DENSITY"),
            "DENSITY", hdr.line)

    def skip_macro_timing(self, macro: dict[str, Any]) -> None:
        """老语法 ``TIMING ... END TIMING`` 整块跳过（登记 other_statements）。"""
        hdr = self.next()
        assert hdr is not None
        self.skip_until_end("TIMING", keyword=True, label="TIMING", line=hdr.line)
        macro["other_statements"].append(
            {"keyword": "TIMING", "raw": "TIMING ... END TIMING", "line": hdr.line})


# ── DEF 解析器 ──────────────────────────────────────────────────────────────


def _prescan_dbu(tokens: list[Token]) -> int | float | None:
    """预扫 ``UNITS DISTANCE MICRONS n``（DBU→µm 换算因子，语句序无关）。"""
    for k in range(len(tokens) - 3):
        if (tokens[k].key == "UNITS" and tokens[k + 1].key == "DISTANCE"
                and tokens[k + 2].key == "MICRONS"):
            val = parse_lefdef_number(tokens[k + 3].text)
            if val is not None and val > 0:
                return val
    return None


class _DefParser(_Cursor):
    """DEF 递归下降解析器（token 流 → DEF 文档；fail-soft 警告面）。"""

    def __init__(self, tokens: list[Token]) -> None:
        super().__init__(tokens)
        self.dbu = _prescan_dbu(tokens)
        self.doc: dict[str, Any] = {
            "version": None,
            "design_name": None,
            "divider_char": None,
            "bus_bit_chars": None,
            "technology": None,
            "units": {"distance_microns": None},
            "die_area": None,
            "rows": [],
            "tracks": [],
            "components": [],
            "pins": [],
            "nets": [],
            "specialnets": [],
            "vias": [],
            "section_counts": {},
            "skipped_sections": [],
            "other_statements": [],
            "ended": False,
        }
        self.units_seen = False

    # ── 单位换算 ──
    def um(self, val: int | float | None) -> float | None:
        """DBU → µm（缺 UNITS 时如实 None）。"""
        if val is None or not self.dbu:
            return None
        return val / self.dbu

    def um_pts(self, pts: list[list[int | float]]) -> list[list[float]] | None:
        if not self.dbu:
            return None
        return [[p[0] / self.dbu, p[1] / self.dbu] for p in pts]

    def um_rect(self, rect: list[int | float]) -> list[float] | None:
        if not self.dbu:
            return None
        return [v / self.dbu for v in rect]

    def dbu_val(self, tok: Token | None, what: str) -> int | float:
        """DBU 数值（整数字面保持 int）；缺值/非数值抛 :class:`LefDefParseError`。"""
        if tok is None:
            raise LefDefParseError(f"{what} 缺数值")
        val = parse_lefdef_number(tok.text) if tok.kind == "word" else None
        if val is None:
            raise LefDefParseError(f"第 {tok.line} 行：{what} 期望数值，实得 {tok.text!r}")
        return val

    def take_point(self, toks: list[Token], i: int,
                   prev: list[int | float] | None) -> tuple[list[int | float], int]:
        """``toks[i]`` 起的 ``( x y [ext] )`` → ([x, y], 下一索引)。

        ``*`` 沿用 prev 同轴值（无前点抛错）；第三值（走线延伸）校验后
        忽略。
        """
        if i >= len(toks) or not _is_punct(toks[i], "("):
            found = toks[i].text if i < len(toks) else "<语句尾>"
            raise LefDefParseError(f"期望 '(' 起始坐标，实得 {found!r}")
        j = i + 1
        vals: list[Token] = []
        while j < len(toks) and not _is_punct(toks[j], ")"):
            vals.append(toks[j])
            j += 1
        if j >= len(toks):
            raise LefDefParseError(f"第 {toks[i].line} 行：坐标括号未闭合")
        if not 2 <= len(vals) <= 3:
            raise LefDefParseError(
                f"第 {toks[i].line} 行：坐标期望 2-3 个值，实得 {len(vals)}")
        xy: list[int | float] = []
        for axis, tok in enumerate(vals[:2]):
            if tok.text == "*":
                if prev is None:
                    raise LefDefParseError(f"第 {tok.line} 行：'*' 坐标无前点可沿用")
                xy.append(prev[axis])
            else:
                xy.append(self.dbu_val(tok, "坐标"))
        if len(vals) == 3 and vals[2].text != "*":
            self.dbu_val(vals[2], "坐标延伸值")
        return xy, j + 1

    def take_points(self, toks: list[Token], i: int) -> list[list[int | float]]:
        """``toks[i:]`` 全部 ``( x y )`` 点（不允许 ``*``）。"""
        pts: list[list[int | float]] = []
        while i < len(toks):
            pt, i = self.take_point(toks, i, None)
            pts.append(pt)
        return pts

    def orient(self, tok: Token | None, line: int, what: str) -> str | None:
        """朝向（大小写容忍）：缺/非法记警告返回 None（不丢宿主条目）。"""
        if tok is None or tok.kind != "word":
            self.warn(line, "missing_orientation", f"{what} 缺朝向（记 None）")
            return None
        if tok.key in ORIENTATIONS:
            return tok.key
        self.warn(line, "invalid_enum",
                  f"{what} 朝向非法值 {tok.text!r}（合法: {'/'.join(ORIENTATIONS)}；记 None）")
        return None

    def other_opt(self, container: dict[str, Any], opt: list[Token], *,
                  known: bool, scope: str, line: int) -> None:
        container["other_options"].append({"keyword": opt[0].key, "raw": _raw(opt)})
        if not known:
            self.warn(line, "unknown_option",
                      f"{scope} 未知选项 + {opt[0].text}（跳过）")

    def safe_opt(self, fn: Callable[[], None], opt: list[Token], line: int,
                 scope: str) -> None:
        """选项级 fail-soft：坏选项只丢该选项不丢宿主条目。"""
        try:
            fn()
        except LefDefParseError as exc:
            self.warn(line, "option_parse_failed",
                      f"{scope} 选项 + {opt[0].text} 解析失败降级跳过：{exc}")

    # ── 顶层 ──
    def parse(self) -> None:
        while True:
            tok = self.peek()
            if tok is None:
                return
            if tok.kind != "word":
                if not _is_punct(tok, ";"):
                    self.warn(tok.line, "stray_token", f"顶层散落 {tok.text!r}（跳过）")
                self.pos += 1
                continue
            key = tok.key
            if key == "END":
                nxt = self.peek(1)
                if nxt is not None and nxt.kind == "word" and nxt.key == "DESIGN":
                    self.pos += 2
                    self.doc["ended"] = True
                    rest = self.peek()
                    if rest is not None:
                        self.warn(rest.line, "trailing_after_end",
                                  f"END DESIGN 之后仍有 {len(self.tokens) - self.pos} 个词（忽略）")
                    return
                self.warn(tok.line, "stray_end", "顶层散落 END（无对应节，跳过）")
                self.pos += 1
                if nxt is not None and nxt.kind == "word" and nxt.key not in _DEF_TOP_ALL:
                    self.pos += 1
                continue
            if key in _DEF_SECTIONS:
                self.parse_section(key)
                continue
            if key in _DEF_SKIP_SECTIONS:
                self.next()
                self.skip_until_end(key, keyword=True, label=key, line=tok.line)
                self.doc["skipped_sections"].append({"keyword": key, "line": tok.line})
                continue
            if key == "BEGINEXT":
                self.next()
                self.skip_until_end("ENDEXT", keyword=True, label="BEGINEXT", line=tok.line)
                self.doc["skipped_sections"].append({"keyword": key, "line": tok.line})
                continue
            stmt = self.statement(stop_at_dash=True)
            if stmt:
                self.safe_stmt(self.apply_top_stmt, stmt)

    def apply_top_stmt(self, stmt: list[Token]) -> None:
        key = stmt[0].key
        args = stmt[1:]
        line = stmt[0].line
        simple = {"VERSION": "version", "DIVIDERCHAR": "divider_char",
                  "BUSBITCHARS": "bus_bit_chars", "DESIGN": "design_name",
                  "TECHNOLOGY": "technology"}
        if key in simple:
            if not args:
                raise LefDefParseError(f"第 {line} 行：{stmt[0].text} 缺值")
            self.doc[simple[key]] = args[0].text
        elif key == "UNITS":
            if len(args) < 3 or args[0].key != "DISTANCE" or args[1].key != "MICRONS":
                raise LefDefParseError(f"第 {line} 行：UNITS 期望 'DISTANCE MICRONS n'")
            val = self.dbu_val(args[2], "UNITS DISTANCE MICRONS")
            if val <= 0:
                raise LefDefParseError(f"第 {line} 行：UNITS DISTANCE MICRONS 须为正，实得 {val}")
            if self.units_seen:
                self.warn(line, "duplicate_units", "UNITS 重复声明（换算因子取首个）")
            else:
                self.doc["units"]["distance_microns"] = val
            self.units_seen = True
        elif key == "DIEAREA":
            pts = self.take_points(args, 0)
            if len(pts) < 2:
                raise LefDefParseError(f"第 {line} 行：DIEAREA 期望 ≥2 个点")
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
            self.doc["die_area"] = {
                "points_dbu": pts, "points_um": self.um_pts(pts),
                "bbox_dbu": bbox, "bbox_um": self.um_rect(bbox),
                "is_rectangle": len(pts) == 2,
            }
        elif key == "ROW":
            self.apply_row(stmt)
        elif key == "TRACKS":
            self.apply_tracks(stmt)
        else:
            self.doc["other_statements"].append(
                {"keyword": key, "raw": _raw(stmt), "line": line})
            if key not in _DEF_TOP_KNOWN:
                self.warn(line, "unknown_statement",
                          f"DEF 顶层未知语句 {stmt[0].text}（整句跳过）")

    def apply_row(self, stmt: list[Token]) -> None:
        """``ROW name site x y orient [DO nx BY ny [STEP sx sy]] [+ ...]``。"""
        args, opts = _split_plus(stmt[1:])
        line = stmt[0].line
        if len(args) < 5:
            raise LefDefParseError(f"第 {line} 行：ROW 期望 'name site x y orient'")
        x = self.dbu_val(args[2], "ROW x")
        y = self.dbu_val(args[3], "ROW y")
        row: dict[str, Any] = {
            "name": args[0].text, "site": args[1].text,
            "x_dbu": x, "y_dbu": y, "x_um": self.um(x), "y_um": self.um(y),
            "orientation": self.orient(args[4], line, f"ROW {args[0].text}"),
            "num_x": None, "num_y": None,
            "step_x_dbu": None, "step_y_dbu": None,
            "step_x_um": None, "step_y_um": None, "line": line,
        }
        i = 5
        if i < len(args) and args[i].key == "DO":
            if i + 3 >= len(args) or args[i + 2].key != "BY":
                raise LefDefParseError(f"第 {line} 行：ROW DO 期望 'DO nx BY ny'")
            row["num_x"] = self.count(args[i + 1], "ROW DO nx")
            row["num_y"] = self.count(args[i + 3], "ROW BY ny")
            i += 4
            if i < len(args) and args[i].key == "STEP":
                if i + 2 >= len(args):
                    raise LefDefParseError(f"第 {line} 行：ROW STEP 期望 'sx sy'")
                sx = self.dbu_val(args[i + 1], "ROW STEP sx")
                sy = self.dbu_val(args[i + 2], "ROW STEP sy")
                row.update({"step_x_dbu": sx, "step_y_dbu": sy,
                            "step_x_um": self.um(sx), "step_y_um": self.um(sy)})
                i += 3
        if i < len(args):
            self.warn(line, "extra_tokens", f"ROW {args[0].text} 尾部多余词 {_raw(args[i:])!r}（忽略）")
        _ = opts  # + PROPERTY 类选项不建模
        self.doc["rows"].append(row)

    def apply_tracks(self, stmt: list[Token]) -> None:
        """``TRACKS [MASK n [SAMEMASK]] X|Y start DO num STEP step [MASK ..] [LAYER l ...]``。"""
        toks = stmt[1:]
        line = stmt[0].line
        i = 0

        def skip_mask(k: int) -> int:
            if k < len(toks) and toks[k].key == "MASK":
                k += 2
                if k < len(toks) and toks[k].key == "SAMEMASK":
                    k += 1
            return k

        i = skip_mask(i)
        if i + 5 >= len(toks) or toks[i].key not in ("X", "Y") \
                or toks[i + 2].key != "DO" or toks[i + 4].key != "STEP":
            raise LefDefParseError(f"第 {line} 行：TRACKS 期望 'X|Y start DO num STEP step'")
        start = self.dbu_val(toks[i + 1], "TRACKS start")
        step = self.dbu_val(toks[i + 5], "TRACKS step")
        track: dict[str, Any] = {
            "direction": toks[i].key,
            "start_dbu": start, "start_um": self.um(start),
            "num": self.count(toks[i + 3], "TRACKS DO num"),
            "step_dbu": step, "step_um": self.um(step),
            "layers": [], "line": line,
        }
        i = skip_mask(i + 6)
        if i < len(toks) and toks[i].key == "LAYER":
            track["layers"] = [t.text for t in toks[i + 1:] if t.kind == "word"]
        elif i < len(toks):
            self.warn(line, "extra_tokens", f"TRACKS 尾部多余词 {_raw(toks[i:])!r}（忽略）")
        self.doc["tracks"].append(track)

    # ── 条目节 ──
    def parse_section(self, keyword: str) -> None:
        hdr_stmt = self.statement(stop_at_dash=True)
        line = hdr_stmt[0].line if hdr_stmt else self.last_line()
        declared: int | None = None
        if len(hdr_stmt) >= 2:
            val = parse_lefdef_number(hdr_stmt[1].text)
            if isinstance(val, int) and val >= 0:
                declared = val
            else:
                self.warn(line, "bad_section_count",
                          f"{keyword} 节头计数非非负整数 {hdr_stmt[1].text!r}（记 None）")
        else:
            self.warn(line, "bad_section_count", f"{keyword} 节头缺计数（记 None）")
        entry_fn: Callable[[list[Token]], dict[str, Any]] = {
            "COMPONENTS": self.component_entry,
            "PINS": self.pin_entry,
            "NETS": lambda s: self.net_entry(s, special=False),
            "SPECIALNETS": lambda s: self.net_entry(s, special=True),
            "VIAS": self.via_entry,
        }[keyword]
        bucket: list[dict[str, Any]] = self.doc[keyword.lower()]
        parsed = 0
        while True:
            tok = self.peek()
            if tok is None:
                self.warn(line, "unterminated_section",
                          f"{keyword} 节未闭合（END {keyword} 缺失，EOF 兜底）")
                break
            if tok.kind != "word":
                if not _is_punct(tok, ";"):
                    self.warn(tok.line, "stray_token", f"{keyword} 节内散落 {tok.text!r}（跳过）")
                self.pos += 1
                continue
            if tok.key == "END":
                nxt = self.peek(1)
                if nxt is not None and nxt.kind == "word" and nxt.key == keyword:
                    self.pos += 2
                    break
                if nxt is not None and nxt.kind == "word" and nxt.key == "DESIGN":
                    self.warn(tok.line, "unterminated_section",
                              f"{keyword} 节未闭合（遇 END DESIGN，按隐式收尾处理）")
                    break
                if nxt is not None and nxt.kind == "word" and nxt.key in _DEF_TOP_ALL:
                    self.pos += 2
                    self.warn(tok.line, "end_name_mismatch",
                              f"{keyword} 节以 END {nxt.text} 收尾（名不匹配，按收尾处理）")
                    break
                self.pos += 1
                self.warn(tok.line, "stray_end", f"{keyword} 节内散落 END（跳过）")
                continue
            if tok.text == "-":
                stmt = self.statement(stop_at_dash=True)
                entry = self.safe_stmt(entry_fn, stmt, label=f"{keyword} 条目")
                if entry is not None:
                    bucket.append(entry)
                    parsed += 1
                continue
            if tok.key in _DEF_TOP_ALL:
                self.warn(tok.line, "unterminated_section",
                          f"{keyword} 节未闭合（遇 {tok.text}，按隐式收尾处理）")
                break
            stmt = self.statement(stop_at_dash=True)
            self.warn(tok.line, "stray_statement",
                      f"{keyword} 节内非条目语句 {_raw(stmt)!r}（跳过）")
        self.doc["section_counts"][keyword] = {"declared": declared, "parsed": parsed}
        if declared is not None and declared != parsed:
            self.warn(line, "count_mismatch",
                      f"{keyword} 节头声明 {declared} 条，实际解析 {parsed} 条")

    def component_entry(self, stmt: list[Token]) -> dict[str, Any]:
        line = stmt[0].line
        if len(stmt) < 3 or stmt[1].kind != "word" or stmt[2].kind != "word":
            raise LefDefParseError(f"第 {line} 行：COMPONENTS 条目缺组件名或模型名")
        name = stmt[1].text
        head, opts = _split_plus(stmt[3:])
        comp: dict[str, Any] = {
            "name": name, "model": stmt[2].text, "status": None,
            "x_dbu": None, "y_dbu": None, "x_um": None, "y_um": None,
            "orientation": None, "source": None, "other_options": [],
            "line": line,
        }
        if head:
            self.warn(line, "extra_tokens", f"组件 {name} 名/模型后多余词 {_raw(head)!r}（忽略）")
        placements = 0
        for opt in opts:
            if not opt:
                self.warn(line, "empty_option", f"组件 {name} 孤立 '+'（跳过）")
                continue
            key = opt[0].key

            def place(opt: list[Token] = opt, key: str = key) -> None:
                nonlocal placements
                if key == "UNPLACED":
                    comp["status"] = "UNPLACED"
                    placements += 1
                    if len(opt) > 1 and _is_punct(opt[1], "("):  # 老语法带坐标
                        pt, i = self.take_point(opt, 1, None)
                        comp.update({"x_dbu": pt[0], "y_dbu": pt[1],
                                     "x_um": self.um(pt[0]), "y_um": self.um(pt[1])})
                        if i < len(opt):
                            comp["orientation"] = self.orient(opt[i], line, f"组件 {name}")
                    return
                pt, i = self.take_point(opt, 1, None)
                comp.update({
                    "status": key, "x_dbu": pt[0], "y_dbu": pt[1],
                    "x_um": self.um(pt[0]), "y_um": self.um(pt[1]),
                    "orientation": self.orient(opt[i] if i < len(opt) else None,
                                               line, f"组件 {name}"),
                })
                placements += 1

            if key in PLACEMENT_STATUSES:
                self.safe_opt(place, opt, line, f"组件 {name}")
            elif key == "SOURCE":
                comp["source"] = opt[1].key if len(opt) > 1 else None
            else:
                self.other_opt(comp, opt, known=key in _DEF_COMP_KNOWN,
                               scope=f"组件 {name}", line=line)
        if placements > 1:
            self.warn(line, "duplicate_placement", f"组件 {name} 多个摆放选项（末个生效）")
        return comp

    def pin_entry(self, stmt: list[Token]) -> dict[str, Any]:
        line = stmt[0].line
        if len(stmt) < 2 or stmt[1].kind != "word":
            raise LefDefParseError(f"第 {line} 行：PINS 条目缺引脚名")
        name = stmt[1].text
        head, opts = _split_plus(stmt[2:])
        pin: dict[str, Any] = {
            "name": name, "net": None, "special": False, "direction": None,
            "use": None, "status": None, "x_dbu": None, "y_dbu": None,
            "x_um": None, "y_um": None, "orientation": None,
            "layer_geoms": [], "vias": [], "placements": [],
            "other_options": [], "line": line,
        }
        if head:
            self.warn(line, "extra_tokens", f"引脚 {name} 名后多余词 {_raw(head)!r}（忽略）")
        state = {"port": 0, "seen_port": False}
        scope = f"引脚 {name}"

        def skip_layer_opts(opt: list[Token], i: int) -> int:
            while i < len(opt) and opt[i].kind == "word" and opt[i].key in (
                    "MASK", "SPACING", "DESIGNRULEWIDTH"):
                i += 2
            return i

        for opt in opts:
            if not opt:
                self.warn(line, "empty_option", f"{scope} 孤立 '+'（跳过）")
                continue
            key = opt[0].key

            def apply(opt: list[Token] = opt, key: str = key) -> None:
                if key == "NET":
                    if len(opt) < 2:
                        raise LefDefParseError("NET 缺网名")
                    pin["net"] = opt[1].text
                elif key == "SPECIAL":
                    pin["special"] = True
                elif key == "DIRECTION":
                    pin["direction"] = self.enum(opt[1:], PIN_DIRECTIONS, f"{scope} DIRECTION", line)
                elif key == "USE":
                    pin["use"] = self.enum(opt[1:], DEF_USES, f"{scope} USE", line)
                elif key == "PORT":
                    if state["seen_port"] or pin["layer_geoms"] or pin["placements"]:
                        state["port"] += 1
                    state["seen_port"] = True
                elif key in ("LAYER", "POLYGON"):
                    if len(opt) < 2 or opt[1].kind != "word":
                        raise LefDefParseError(f"{key} 缺层名")
                    pts = self.take_points(opt, skip_layer_opts(opt, 2))
                    if key == "LAYER":
                        if len(pts) != 2:
                            raise LefDefParseError(f"LAYER 矩形期望 2 个点，实得 {len(pts)}")
                        rect = [pts[0][0], pts[0][1], pts[1][0], pts[1][1]]
                        pin["layer_geoms"].append({
                            "port_index": state["port"], "layer": opt[1].text,
                            "kind": "rect", "rect_dbu": rect, "rect_um": self.um_rect(rect)})
                    else:
                        if len(pts) < 3:
                            raise LefDefParseError(f"POLYGON 期望 ≥3 个点，实得 {len(pts)}")
                        pin["layer_geoms"].append({
                            "port_index": state["port"], "layer": opt[1].text,
                            "kind": "polygon", "points_dbu": pts,
                            "points_um": self.um_pts(pts)})
                elif key == "VIA":
                    if len(opt) < 2 or opt[1].kind != "word":
                        raise LefDefParseError("VIA 缺 via 名")
                    pt, _ = self.take_point(opt, skip_layer_opts(opt, 2), None)
                    pin["vias"].append({
                        "port_index": state["port"], "name": opt[1].text,
                        "x_dbu": pt[0], "y_dbu": pt[1],
                        "x_um": self.um(pt[0]), "y_um": self.um(pt[1])})
                elif key in ("PLACED", "FIXED", "COVER"):
                    pt, i = self.take_point(opt, 1, None)
                    placement = {
                        "port_index": state["port"], "status": key,
                        "x_dbu": pt[0], "y_dbu": pt[1],
                        "x_um": self.um(pt[0]), "y_um": self.um(pt[1]),
                        "orientation": self.orient(opt[i] if i < len(opt) else None,
                                                   line, scope),
                    }
                    pin["placements"].append(placement)
                    if len(pin["placements"]) == 1:
                        pin.update({k: placement[k] for k in (
                            "status", "x_dbu", "y_dbu", "x_um", "y_um", "orientation")})
                else:
                    self.other_opt(pin, opt,
                                   known=key in _DEF_PIN_KNOWN or key.startswith("ANTENNA"),
                                   scope=scope, line=line)

            self.safe_opt(apply, opt, line, scope)
        return pin

    def net_entry(self, stmt: list[Token], *, special: bool) -> dict[str, Any]:
        line = stmt[0].line
        label = "SPECIALNETS" if special else "NETS"
        if len(stmt) < 2 or stmt[1].kind != "word":
            raise LefDefParseError(f"第 {line} 行：{label} 条目缺网名")
        name = stmt[1].text
        head, opts = _split_plus(stmt[2:])
        net: dict[str, Any] = {
            "name": name, "special": special, "conns": [], "routes": [],
            "use": None, "other_options": [], "line": line,
        }
        scope = f"网 {name}"
        i = 0
        while i < len(head):
            tok = head[i]
            if _is_punct(tok, "("):
                j = i + 1
                inner: list[Token] = []
                while j < len(head) and not _is_punct(head[j], ")"):
                    inner.append(head[j])
                    j += 1
                if j >= len(head):
                    self.warn(line, "bad_connection", f"{scope} 连接括号未闭合（截断）")
                    break
                words = [t.text for t in inner
                         if t.kind == "word" and t.text != "+" and t.key != "SYNTHESIZED"]
                if len(words) >= 2:
                    net["conns"].append([words[0], words[1]])
                else:
                    self.warn(line, "bad_connection",
                              f"{scope} 连接期望 '( comp pin )'，实得 {_raw(inner)!r}（跳过）")
                i = j + 1
                continue
            if tok.kind == "word" and tok.key == "MUSTJOIN":
                i += 1
                continue
            self.warn(line, "extra_tokens", f"{scope} 连接区散落 {tok.text!r}（跳过）")
            i += 1
        k = 0
        while k < len(opts):
            opt = opts[k]
            k += 1
            if not opt:
                self.warn(line, "empty_option", f"{scope} 孤立 '+'（跳过）")
                continue
            key = opt[0].key
            if key in ROUTE_STATUSES:
                chunk = list(opt)
                while k < len(opts) and opts[k] and opts[k][0].key in _DEF_ROUTE_CONTINUATION:
                    chunk.extend(opts[k])  # SPECIALNETS + SHAPE/+ STYLE 续接当前走线段
                    k += 1
                self.safe_opt(lambda c=chunk: net["routes"].extend(self.parse_routes(c, special)),
                              chunk, line, scope)
            elif key == "USE":
                self.safe_opt(lambda o=opt: net.update(
                    use=self.enum(o[1:], DEF_USES, f"{scope} USE", line)), opt, line, scope)
            else:
                self.other_opt(net, opt, known=key in _DEF_NET_KNOWN,
                               scope=scope, line=line)
        return net

    def parse_routes(self, chunk: list[Token], special: bool) -> list[dict[str, Any]]:
        """走线选项块 → 走线段表（NEW 分段；SPECIALNETS 层名后取线宽）。"""
        status = chunk[0].key
        i = 1
        shield_net: str | None = None
        if status == "SHIELD":
            if i >= len(chunk) or chunk[i].kind != "word":
                raise LefDefParseError("SHIELD 缺屏蔽网名")
            shield_net = chunk[i].text
            i += 1
        segments: list[dict[str, Any]] = []
        while i < len(chunk):
            if chunk[i].kind != "word":
                raise LefDefParseError(f"走线段期望层名，实得 {chunk[i].text!r}")
            seg: dict[str, Any] = {
                "status": status, "layer": chunk[i].text, "shield_net": shield_net,
                "width_dbu": None, "width_um": None, "shape": None, "style": None,
                "points_dbu": [], "points_um": None, "vias": [], "rects_dbu": [],
            }
            i += 1
            if special and i < len(chunk) and chunk[i].kind == "word" \
                    and parse_lefdef_number(chunk[i].text) is not None:
                width = self.dbu_val(chunk[i], "走线宽")
                seg["width_dbu"] = width
                seg["width_um"] = self.um(width)
                i += 1
            last: list[int | float] | None = None
            while i < len(chunk):
                tok = chunk[i]
                if _is_punct(tok, "("):
                    pt, i = self.take_point(chunk, i, last)
                    seg["points_dbu"].append(pt)
                    last = pt
                    continue
                if tok.kind != "word":
                    raise LefDefParseError(f"走线内散落 {tok.text!r}")
                key = tok.key
                if key == "NEW":
                    i += 1
                    break
                if key == "TAPER":
                    i += 1
                    continue
                if key in ("TAPERRULE", "STYLE", "SHAPE", "MASK"):
                    if i + 1 >= len(chunk):
                        raise LefDefParseError(f"{tok.text} 缺值")
                    if key == "STYLE":
                        seg["style"] = chunk[i + 1].text
                    elif key == "SHAPE":
                        seg["shape"] = chunk[i + 1].key
                    i += 2
                    continue
                if key == "RECT":
                    if i + 6 >= len(chunk) or not _is_punct(chunk[i + 1], "(") \
                            or not _is_punct(chunk[i + 6], ")"):
                        raise LefDefParseError("走线 RECT 期望 '( dx1 dy1 dx2 dy2 )'")
                    seg["rects_dbu"].append(
                        [self.dbu_val(t, "RECT") for t in chunk[i + 2:i + 6]])
                    i += 7
                    continue
                if key == "VIRTUAL":
                    pt, i = self.take_point(chunk, i + 1, last)
                    last = pt  # 虚拟点只作 '*' 沿用参照，不入走线端点
                    continue
                if last is None:
                    raise LefDefParseError(f"走线 via {tok.text} 之前无坐标点")
                via: dict[str, Any] = {
                    "name": tok.text, "x_dbu": last[0], "y_dbu": last[1],
                    "x_um": self.um(last[0]), "y_um": self.um(last[1]),
                    "orientation": None,
                }
                i += 1
                if i < len(chunk) and chunk[i].kind == "word" and chunk[i].key in ORIENTATIONS:
                    via["orientation"] = chunk[i].key
                    i += 1
                seg["vias"].append(via)
            seg["points_um"] = self.um_pts(seg["points_dbu"])
            segments.append(seg)
        return segments

    def via_entry(self, stmt: list[Token]) -> dict[str, Any]:
        line = stmt[0].line
        if len(stmt) < 2 or stmt[1].kind != "word":
            raise LefDefParseError(f"第 {line} 行：VIAS 条目缺 via 名")
        name = stmt[1].text
        head, opts = _split_plus(stmt[2:])
        via: dict[str, Any] = {
            "name": name, "viarule": None, "rule_params": {}, "rects": [],
            "polygons": [], "other_options": [], "line": line,
        }
        if head:
            self.warn(line, "extra_tokens", f"via {name} 名后多余词 {_raw(head)!r}（忽略）")
        scope = f"via {name}"
        k = 0
        while k < len(opts):
            opt = opts[k]
            k += 1
            if not opt:
                self.warn(line, "empty_option", f"{scope} 孤立 '+'（跳过）")
                continue
            key = opt[0].key
            if key in ("RECT", "POLYGON"):
                body = list(opt)
                # ``+ RECT layer + MASK n pt pt``：MASK 选项块携带坐标，续接
                if k < len(opts) and opts[k] and opts[k][0].key == "MASK" \
                        and not any(_is_punct(t, "(") for t in body):
                    body.extend(opts[k][2:])
                    k += 1

                def shape(body: list[Token] = body, key: str = key) -> None:
                    if len(body) < 2 or body[1].kind != "word":
                        raise LefDefParseError(f"{key} 缺层名")
                    j = 2
                    if j < len(body) and body[j].key == "MASK":
                        j += 2
                    pts = self.take_points(body, j)
                    if key == "RECT":
                        if len(pts) != 2:
                            raise LefDefParseError(f"RECT 期望 2 个点，实得 {len(pts)}")
                        rect = [pts[0][0], pts[0][1], pts[1][0], pts[1][1]]
                        via["rects"].append({"layer": body[1].text, "rect_dbu": rect,
                                             "rect_um": self.um_rect(rect)})
                    else:
                        if len(pts) < 3:
                            raise LefDefParseError(f"POLYGON 期望 ≥3 个点，实得 {len(pts)}")
                        via["polygons"].append({"layer": body[1].text, "points_dbu": pts,
                                                "points_um": self.um_pts(pts)})

                self.safe_opt(shape, opt, line, scope)
            elif key == "VIARULE":
                via["viarule"] = opt[1].text if len(opt) > 1 else None
            elif key in _DEF_VIA_RULE_PARAMS:
                via["rule_params"][key] = [t.text for t in opt[1:]]
            else:
                self.other_opt(via, opt, known=False, scope=scope, line=line)
        return via


# ── 文档级入口 ──────────────────────────────────────────────────────────────


def _sorted_warnings(lex: list[dict[str, Any]], parse: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """词法+解析警告按行号稳定排序（同行保持产生序）。"""
    return sorted([*lex, *parse], key=lambda w: w["line"])


def parse_lef(text: str) -> dict[str, Any]:
    """LEF 文本 → 结构化文档。

    返回::

        {
          "schema": f"lef_def/{PARSER_SCHEMA_VERSION}", "format": "LEF",
          "version", "bus_bit_chars",
          "divider_char", "units": {"database_microns": int, ...},
          "manufacturing_grid_um",
          "layers": [{name, type, direction, pitch_um, pitch_y_um,
                      width_um, spacing_um, spacing_rules, thickness_um,
                      offset_um, offset_y_um, min_width_um, area_um2,
                      other_statements, line}],
          "vias": [{name, default, generated, resistance,
                    layers: [{layer, rects, polygons, paths}], ...}],
          "viarules": [{name, generate, default, layers, vias, ...}],
          "sites": [{name, class, symmetry, size, ...}],
          "macros": {name: {name, class, class_subtype, foreign, origin,
                            size: {width_um, height_um}, symmetry, site,
                            pins: {pin: {name, direction, tristate, use,
                                         shape, port_geoms, port_vias,
                                         n_ports, ...}},
                            pin_order, obs_geoms, obs_vias, ...}},
          "macro_order", "skipped_blocks", "other_statements", "ended",
          "warnings": [{line, name, note}], "stats": {...},
        }

    永不抛（fail-soft：一切结构违规进 ``warnings`` 带行号披露）。
    """
    tokens, lex_issues = _scan(text)
    parser = _LefParser(tokens)
    parser.parse()
    doc = parser.doc
    recognized = (doc["version"] is not None or doc["bus_bit_chars"] is not None
                  or doc["divider_char"] is not None or doc["units"]
                  or doc["manufacturing_grid_um"] is not None or doc["layers"]
                  or doc["vias"] or doc["viarules"] or doc["sites"] or doc["macros"]
                  or doc["skipped_blocks"] or doc["ended"])
    if tokens and not recognized:
        parser.warn(tokens[0].line, "no_recognized_constructs",
                    "全文未识别出任何 LEF 结构（非 LEF 文件？）")
    macros = doc["macros"].values()
    stats = {
        "n_tokens": len(tokens),
        "n_layers": len(doc["layers"]),
        "n_routing_layers": sum(1 for lay in doc["layers"] if lay["type"] == "ROUTING"),
        "n_cut_layers": sum(1 for lay in doc["layers"] if lay["type"] == "CUT"),
        "n_vias": len(doc["vias"]),
        "n_viarules": len(doc["viarules"]),
        "n_sites": len(doc["sites"]),
        "n_macros": len(doc["macros"]),
        "n_pins": sum(len(m["pins"]) for m in macros),
    }
    warnings = _sorted_warnings(lex_issues, parser.warnings)
    stats["n_warnings"] = len(warnings)
    # 自描述键统一口径（R-22 schema 升位批）：``"<域>/<N.0>"`` 复合键；
    # LEF/DEF 子形态由既有 "format" 键区分（本批不动其语义）。
    return {"schema": f"lef_def/{PARSER_SCHEMA_VERSION}", "format": "LEF",
            **doc,
            "warnings": warnings, "stats": stats}


def parse_def(text: str) -> dict[str, Any]:
    """DEF 文本 → 结构化文档。

    返回::

        {
          "schema": f"lef_def/{PARSER_SCHEMA_VERSION}", "format": "DEF",
          "version", "design_name",
          "divider_char", "bus_bit_chars", "technology",
          "units": {"distance_microns": DBU/µm 换算因子 | None},
          "die_area": {points_dbu, points_um, bbox_dbu, bbox_um,
                       is_rectangle} | None,
          "rows": [{name, site, x_dbu, y_dbu, x_um, y_um, orientation,
                    num_x, num_y, step_*_dbu, step_*_um, line}],
          "tracks": [{direction, start_dbu, start_um, num, step_dbu,
                      step_um, layers, line}],
          "components": [{name, model, status, x_dbu, y_dbu, x_um, y_um,
                          orientation, source, other_options, line}],
          "pins": [{name, net, special, direction, use, status, x_*/y_*,
                    orientation, layer_geoms, vias, placements, ...}],
          "nets": [{name, special, conns: [[comp, pin], ...],
                    routes: [{status, layer, shield_net, width_*, shape,
                              style, points_dbu, points_um, vias,
                              rects_dbu}], use, other_options, line}],
          "specialnets": [同 nets 形态], "vias": [{name, viarule,
                          rule_params, rects, polygons, ...}],
          "section_counts": {节: {declared, parsed}}, "skipped_sections",
          "other_statements", "ended", "warnings", "stats",
        }

    ``*_um`` = ``*_dbu`` ÷ ``units.distance_microns``（缺 UNITS 时 None）。
    永不抛（fail-soft）。
    """
    tokens, lex_issues = _scan(text)
    parser = _DefParser(tokens)
    parser.parse()
    doc = parser.doc
    if tokens and doc["units"]["distance_microns"] is None:
        parser.warn(tokens[0].line, "missing_units",
                    "DEF 缺 UNITS DISTANCE MICRONS：DBU→µm 换算不可做"
                    "（*_um 字段记 None，*_dbu 原值保留）")
    recognized = (doc["version"] is not None or doc["design_name"] is not None
                  or doc["units"]["distance_microns"] is not None
                  or doc["die_area"] is not None or doc["rows"] or doc["tracks"]
                  or doc["components"] or doc["pins"] or doc["nets"]
                  or doc["specialnets"] or doc["vias"]
                  or doc["skipped_sections"] or doc["ended"])
    if tokens and not recognized:
        parser.warn(tokens[0].line, "no_recognized_constructs",
                    "全文未识别出任何 DEF 结构（非 DEF 文件？）")
    all_nets = [*doc["nets"], *doc["specialnets"]]
    stats = {
        "n_tokens": len(tokens),
        "n_components": len(doc["components"]),
        "n_placed": sum(1 for c in doc["components"]
                        if c["status"] in ("PLACED", "FIXED", "COVER")),
        "n_unplaced": sum(1 for c in doc["components"] if c["status"] == "UNPLACED"),
        "n_pins": len(doc["pins"]),
        "n_nets": len(doc["nets"]),
        "n_specialnets": len(doc["specialnets"]),
        "n_vias": len(doc["vias"]),
        "n_rows": len(doc["rows"]),
        "n_tracks": len(doc["tracks"]),
        "n_conns": sum(len(n["conns"]) for n in all_nets),
        "n_route_segments": sum(len(n["routes"]) for n in all_nets),
    }
    warnings = _sorted_warnings(lex_issues, parser.warnings)
    stats["n_warnings"] = len(warnings)
    return {"schema": f"lef_def/{PARSER_SCHEMA_VERSION}", "format": "DEF",
            **doc,
            "warnings": warnings, "stats": stats}


# ── 拓扑提取 ────────────────────────────────────────────────────────────────


def _lef_macros(lef: dict[str, Any] | list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """单份或多份 LEF 文档的 macros 合并视图（后者同名覆盖前者——科技
    LEF+单元 LEF 分文件的常见组合）。"""
    docs = [lef] if isinstance(lef, dict) else list(lef)
    merged: dict[str, Any] = {}
    for doc in docs:
        merged.update(doc.get("macros") or {})
    return merged


def def_component_macro_closure(
    def_doc: dict[str, Any],
    lef: dict[str, Any] | list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """COMPONENTS.model ⊆ LEF macros 键闭合校验。

    返回 ``{closed, n_components, n_models, models_used, missing_models,
    components_missing_model: {model: [组件名(DEF 序)]},
    n_components_missing_model, n_lef_macros, unused_lef_macros,
    n_unused_lef_macros}``——缺名表如实返回（名字精确比较）；
    ``unused_lef_macros`` 是信息桶（单元库常远大于设计用量，非判错）。
    """
    macros = _lef_macros(lef)
    by_model: dict[str, list[str]] = {}
    for comp in def_doc.get("components") or []:
        by_model.setdefault(comp["model"], []).append(comp["name"])
    missing = sorted(m for m in by_model if m not in macros)
    unused = sorted(set(macros) - set(by_model))
    return {
        "closed": not missing,
        "n_components": sum(len(v) for v in by_model.values()),
        "n_models": len(by_model),
        "models_used": sorted(by_model),
        "missing_models": missing,
        "components_missing_model": {m: by_model[m] for m in missing},
        "n_components_missing_model": sum(len(by_model[m]) for m in missing),
        "n_lef_macros": len(macros),
        "unused_lef_macros": unused,
        "n_unused_lef_macros": len(unused),
    }


def def_net_connectivity(def_doc: dict[str, Any]) -> dict[str, Any]:
    """逐网连接度+悬空网+引用完整性（DEF 内部结构校验，不做驱动判定）。

    - ``nets``：逐网 ``{name, degree, n_component_conns, n_pin_conns,
      n_route_segments, routed, use}``（degree=连接数）；
    - ``dangling_nets``：零连接网；``single_connection_nets``：单连接网
      （信息桶——单端网常见于未完成连接/天线类，非终判）；
    - ``degree_histogram``：``[[degree, 网数], ...]`` 升序；
    - ``unknown_component_refs``：连接引用 COMPONENTS 中不存在的组件
      ``[[net, comp, pin], ...]``；``unknown_toplevel_pin_refs``：
      ``( PIN p )`` 引用 PINS 中不存在的顶层引脚 ``[[net, pin], ...]``；
    - ``pins_with_unknown_net``：PINS ``+ NET`` 指向 NETS/SPECIALNETS 都
      没有的网 ``[[pin, net], ...]``；``pins_without_net``：缺 ``+ NET``；
    - ``specialnets``：特殊网逐网 ``{name, degree, wildcard_conns,
      n_route_segments, use}``（``( * pin )`` 通配连接计 wildcard）。

    LEF/DEF 无方向语义网表：只读/不驱动判定不做（宁不报不误报）。
    """
    comps = {c["name"] for c in def_doc.get("components") or []}
    pins = {p["name"] for p in def_doc.get("pins") or []}
    nets = def_doc.get("nets") or []
    specialnets = def_doc.get("specialnets") or []
    rows: list[dict[str, Any]] = []
    dangling: list[str] = []
    single: list[str] = []
    hist: dict[int, int] = {}
    unknown_comp: list[list[str]] = []
    unknown_pin: list[list[str]] = []
    for net in nets:
        conns = net["conns"]
        degree = len(conns)
        hist[degree] = hist.get(degree, 0) + 1
        if degree == 0:
            dangling.append(net["name"])
        elif degree == 1:
            single.append(net["name"])
        for comp, pin in conns:
            if comp == "PIN":
                if pin not in pins:
                    unknown_pin.append([net["name"], pin])
            elif comp != "*" and comp not in comps:
                unknown_comp.append([net["name"], comp, pin])
        rows.append({
            "name": net["name"], "degree": degree,
            "n_component_conns": sum(1 for c, _ in conns if c not in ("PIN", "*")),
            "n_pin_conns": sum(1 for c, _ in conns if c == "PIN"),
            "n_route_segments": len(net["routes"]),
            "routed": bool(net["routes"]),
            "use": net["use"],
        })
    special_rows = []
    for net in specialnets:
        conns = net["conns"]
        for comp, pin in conns:
            if comp == "PIN":
                if pin not in pins:
                    unknown_pin.append([net["name"], pin])
            elif comp != "*" and comp not in comps:
                unknown_comp.append([net["name"], comp, pin])
        special_rows.append({
            "name": net["name"], "degree": len(conns),
            "wildcard_conns": sum(1 for c, _ in conns if c == "*"),
            "n_route_segments": len(net["routes"]),
            "use": net["use"],
        })
    net_names = {n["name"] for n in nets} | {n["name"] for n in specialnets}
    pins_unknown_net = [[p["name"], p["net"]] for p in def_doc.get("pins") or []
                        if p["net"] is not None and p["net"] not in net_names]
    pins_no_net = [p["name"] for p in def_doc.get("pins") or [] if p["net"] is None]
    return {
        "n_nets": len(nets),
        "n_specialnets": len(specialnets),
        "nets": rows,
        "dangling_nets": dangling,
        "single_connection_nets": single,
        "degree_histogram": [[d, hist[d]] for d in sorted(hist)],
        "max_degree": max(hist) if hist else None,
        "unknown_component_refs": unknown_comp,
        "unknown_toplevel_pin_refs": unknown_pin,
        "pins_with_unknown_net": pins_unknown_net,
        "pins_without_net": pins_no_net,
        "specialnets": special_rows,
        "direction_analysis": None,
        "note": "LEF/DEF 无方向语义网表：驱动/负载判定不做（宁不报不误报）",
    }


def def_pin_lef_alignment(
    def_doc: dict[str, Any],
    lef: dict[str, Any] | list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    macro: str | None = None,
) -> dict[str, Any]:
    """DEF 引脚名 ↔ LEF macro 引脚名对齐（字符串精确比较，差异如实列表）。

    ``top_level``：DEF PINS 名 vs LEF 对应 macro（缺省=DEF DESIGN 同名
    macro，``macro`` 参数显式覆盖）的引脚名——``missing_in_lef``（DEF 有
    LEF 无，DEF 序）/``missing_in_def``（LEF 有 DEF 无，LEF 声明序）/
    ``direction_mismatches``（两侧方向都声明且不同）；LEF 无该 macro 时
    ``applicable=False`` 如实不判（层次化流程里块抽象 LEF 才含设计同名
    macro）。

    ``instance_pins``：NETS/SPECIALNETS ``( comp pin )`` 引用的引脚名在
    组件模型 macro 中缺席 → ``unknown_pin_refs``；组件未知或模型不在 LEF
    的引用计 ``skipped_refs`` 不判（闭合缺口由
    :func:`def_component_macro_closure` 报）；``( * pin )`` 通配与
    ``( PIN p )`` 顶层引用不进本面。
    """
    macros = _lef_macros(lef)
    target = macro if macro is not None else def_doc.get("design_name")
    def_pins = def_doc.get("pins") or []
    top: dict[str, Any] = {
        "macro": target,
        "applicable": target is not None and target in macros,
        "missing_in_lef": [],
        "missing_in_def": [],
        "direction_mismatches": [],
        "reason": None,
    }
    if top["applicable"]:
        lef_macro = macros[target]
        lef_pins = lef_macro["pins"]
        def_names: list[str] = []
        for p in def_pins:
            if p["name"] not in def_names:
                def_names.append(p["name"])
        def_set = set(def_names)
        top["missing_in_lef"] = [n for n in def_names if n not in lef_pins]
        top["missing_in_def"] = [n for n in lef_macro["pin_order"] if n not in def_set]
        for p in def_pins:
            lp = lef_pins.get(p["name"])
            if lp is None or p["direction"] is None or lp["direction"] is None:
                continue
            if p["direction"] != lp["direction"]:
                top["direction_mismatches"].append({
                    "pin": p["name"], "def_direction": p["direction"],
                    "lef_direction": lp["direction"]})
    else:
        top["reason"] = ("DEF 无 DESIGN 名且未指定 macro" if target is None
                         else f"LEF 中无 macro {target!r}（top-level 对齐不适用）")
    model_of = {c["name"]: c["model"] for c in def_doc.get("components") or []}
    unknown_refs: list[dict[str, str]] = []
    checked = 0
    skipped = 0
    for net in [*(def_doc.get("nets") or []), *(def_doc.get("specialnets") or [])]:
        for comp, pin in net["conns"]:
            if comp in ("PIN", "*"):
                continue
            model = model_of.get(comp)
            if model is None or model not in macros:
                skipped += 1
                continue
            checked += 1
            if pin not in macros[model]["pins"]:
                unknown_refs.append({"net": net["name"], "component": comp,
                                     "model": model, "pin": pin})
    return {
        "top_level": top,
        "instance_pins": {
            "checked_refs": checked,
            "skipped_refs": skipped,
            "unknown_pin_refs": unknown_refs,
        },
    }
