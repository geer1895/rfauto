"""Verilog 网表结构化解析内核（aurora_q Q-X47，2026-11-07）。

数字 IC 标准**网表格式** Verilog HDL（IEEE 1364）结构子集的只读结构化
解析——数字后端（综合/PnR）输出的 gate-level netlist 是数字自动化的
标准交接面，数模混合设计中 RF 用户需要读取 Verilog 网表做结构分析
（module/port/wire/assign/instance primitive/parameter/defparam）时
的单源入口。词法与语义全部在 core 确定性内核（铁律 7：结构化数字只
出自数据源文本本身；LLM/agent 永不产生物理数字）。服务包装见
:mod:`rfauto.service.verilog_netlist_service`（规则 4 JSON 进出），
CLI 薄壳见 cli/domains/verilog.py。

词法覆盖面（结构网表子集；按 Verilog-2001 正式规则）：

- 注释：``//`` 行注释与 ``/* */`` 块注释（块注释未闭合抛
  :class:`VerilogParseError` 带行号）；
- 字符串字面量 ``"..."``（转义 ``\\`` ；未闭合抛错）；
- 标识符：普通标识符（``[A-Za-z_$]`` 起头）+ **转义标识符**
  ``\\name`` 到空白止（EDA 工具网表常见）；层次名 ``a.b.c`` 按普通
  标识符+点分词自然合成；
- 数字：十进制明数（含 ``_`` 位分隔）+ **位宽字面量**
  ``8'hFF`` / ``4'b0101`` / ``12'd135`` / ``1'bx``（:func:
  `parse_verilog_number` 单源；parameter 数值提取同源消费）；
- 系统任务/函数 ``$display`` 类：词法识别（``sys`` token），结构子集
  内一律随宿主构造跳过；
- 编译器指令 ``\\`timescale`` / ``\\`define`` / ``\\`include`` /
  ``\\`ifdef`` 族 / ``\\`default_nettype`` 等：整行消费（含行尾 ``\\``
  续行），指令名收进 ``directives`` 名录——网表的功能语义不依赖指令
  体，静默跳过+如实登记；
- 运算符：多字符最大吞噬（``<=`` ``>=`` ``==`` ``===`` ``!=`` ``!==``
  ``<<`` ``>>`` ``<<<`` ``>>>`` ``&&`` ``||`` ``**`` 等）+ 单字符兜底。

语义面（结构化输出 schema，模块级五桶+参数面）：

- ``ports``：``module`` 端口（**ANSI 2001 头内全声明**与 **1995 头列
  名+体内方向声明**双形态统一归一）；每项 ``{name, direction,
  width}``，direction ∈ input/output/inout（头内只列名的 1995 形态
  由体内声明回填；direction 无法判定时如实 None），width =
  ``{msb, lsb, span}``（标量位 msb=lsb=None/span=1）；
- ``wires``：``wire``/``reg``/``tri``/``wand``/``wor``/``supply0``/
  ``supply1`` 类网声明（含 ``kind`` 记录声明关键字、reg 初始化值
  ``init``、驱动强度/延迟原文）；``[msb:lsb]`` 范围同 ports 口径；
- ``assigns``：连续赋值 ``assign [#delay] lhs = rhs``（多目标逗号形
  逐条展开；delay 原文记录）；
- ``instances``：实例（两类统一 schema ``{type, name, connections,
  connection_style, range, delay, params, primitive,
  well_known_cell, line}``）：
  - **门级原语**（LRM 14 章全集：and/nand/or/nor/xor/xnor/buf/not/
    bufif0/bufif1/notif0/notif1/pmos/nmos/cmos/rpmos/rnmos/rcmos/
    tran 族/pullup/pulldown）——按 :data:`GATE_PRIMITIVES` 注册表
    （RegistryKit，AGENTS 规则 3）把位置连接归一成命名映射
    （``out``/``in1..inN``/``ctrl``；not/buf 多输出 ``out1..outN``；
    tran 族双向 ``a``/``b``）；门延迟 ``#(1,2)`` 记 ``delay`` 原文；
  - **模块实例**（类型=其他 module 名或外部单元库）——命名连接
    ``.p(net)`` 按 ``connections`` 映射保留；位置连接按序号键
    ``"1".."N"``（``connection_style="positional"``；拓扑层对已知子
    模块按子模块端口声明序对位，未知子模块如实入外部边界）；参数化
    ``#(.P(v))`` 记 ``params``、位置参数 ``#(8,4)`` 按序号键记
    ``params``；``connection_style`` ∈ named/positional；
- ``parameters``/``localparams``：``parameter``/``localparam`` 声明
  （值=表达式原文；纯数值形态可用 :func:`parse_verilog_number`
  回收 int）；模块头 ``#(parameter ...)`` 参数口原文记
  ``header_params_raw``；
- ``defparams``：``defparam inst.path.P = v``（target/param/value）。

行为块处理（fail-soft 口径）：``always``/``initial``/``function``/
``task``/``specify``/``generate``/``config`` 块整体跳过并记 warning
（结构网表解析不进行为语义；被跳过块内可能有过程赋值驱动的 reg——
孤立网检测对 reg 类网一律不判 undriven，见下）。病态实例语句
（非实例标识符开头的构造）解析失败降级为警告+跳语句，不炸全文档。

拓扑提取（:func:`extract_module_topology`，单模块作用域）：

- 三层关系：实例 →（输出端口驱动）→ 网 →（输入端口消费）→ 实例；
  ``net_drivers``/``net_readers`` 双向图（驱动/读者形态 instance/
  assign/port 三类）；实例级边表 ``instance_edges``（驱动实例→消费
  实例）；模块实例的端口方向由文档内子模块端口声明决定（位置连接
  按子模块端口声明序对位）；子模块未知的实例（外部单元库）连接网
  记 ``external_boundary_nets``（驱动方向不可判，孤立网检测豁免——
  宁不报不误报 #122 口径）；
- 孤立网检测：``undriven``（无任何驱动源且非模块 input/inout 且未接
  外部未知实例——**reg 类网不判**：过程赋值驱动被行为块跳过属已知
  盲区，无证据不下结论）与 ``unloaded``（无任何读者且非模块
  output/inout 且未接外部未知实例）两桶分开如实；
- 树深度：实例级 DAG 最长链（``depth`` + 关键路径 ``critical_path``
  实例名序表；同层取字典序=确定性）；环检测（组合反馈环）→
  ``cyclic=True`` + 环上实例名录、depth 如实置 None 不猜。

顶层文档另含：``top_modules``（未被任何模块实例化的模块=顶层候选）、
``instantiations``（父子实例边）、``external_instance_types``（未在
文档内定义的实例类型=外部单元库引用）。未知构造不中断（进 ``warnings``
带行号如实披露后继续）；确定性（同输入同输出）、零 IO（纯文本进出）、
零第三方依赖。本模块不设 ``__all__``（无 __all__ 文件不进
tests/gold/public_api.json——sdc_parser/spice_netlist_parser 同款
先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rfauto.core.registry_kit import RegistryKit

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: 方向词表（端口 direction 合法值单源）。
DIRECTIONS = ("input", "output", "inout")

#: 网/变量声明关键字 → kind 记录值（wire 族+reg；声明语义同类收集）。
NET_TYPE_KEYWORDS = (
    "wire", "wand", "wor", "tri", "tri0", "tri1", "trireg",
    "supply0", "supply1", "uwire", "reg",
)

#: 行为/生成块关键字（模块体跳过面单源）。
BEHAVIORAL_KEYWORDS = (
    "always", "initial", "function", "task", "specify",
    "generate", "config",
)


class VerilogParseError(ValueError):
    """Verilog 词法/结构违规（ValueError 子类，带行号文本）。"""


# ── 门级原语注册表（AGENTS 规则 3：基类+注册表；LRM 14 章词表）─────────────


@dataclass(frozen=True)
class GatePrimitive:
    """一个 Verilog 门级原语的连接元数据（位置→命名归一的依据）。

    - ``desc``：人读描述；
    - ``n_outputs``：输出端子数（None=变体：not/buf 多输出
      ``out1..outN``）；``n_inputs``：输入端子数（None=变体：and 族
      ≥2 可变 ``in1..inN``）；
    - ``bidirectional``：tran 族双向端子（``a``/``b``[``ctrl``]，驱动
      方向不定，拓扑两侧都不计驱动）；
    - ``output_ports``/``input_ports``：命名连接键序表（拓扑方向判定
      单源；三态/MOS 的 ctrl 在 input_ports 尾）。
    """

    name: str
    desc: str
    n_outputs: int | None
    n_inputs: int | None
    bidirectional: bool = False
    output_ports: tuple[str, ...] = ()
    input_ports: tuple[str, ...] = ()


def _build_gate_primitives() -> dict[str, GatePrimitive]:
    """LRM 14 章门级原语词表的元数据构建（模块内单源函数）。"""
    prims: dict[str, GatePrimitive] = {}
    # 多输入门：位置序 = 输出 1 + 输入 N（N≥2 可变）
    for name, zh in (
        ("and", "与门"), ("nand", "与非门"),
        ("or", "或门"), ("nor", "或非门"),
        ("xor", "异或门"), ("xnor", "同或门"),
    ):
        prims[name] = GatePrimitive(
            name, zh, 1, None,
            output_ports=("out",), input_ports=("in1", "in2"))
    # 多输出单输入：buf/not（位置序 = 输出 1..N + 输入 1）
    for name, zh in (("buf", "缓冲器"), ("not", "反相器")):
        prims[name] = GatePrimitive(
            name, zh, None, 1,
            output_ports=("out1",), input_ports=("in",))
    # 三态门：位置序 = out, in, ctrl
    ctrl_ports = ("in", "ctrl")
    for name, zh in (
        ("bufif1", "高使能三态缓冲器"), ("bufif0", "低使能三态缓冲器"),
        ("notif1", "高使能三态反相器"), ("notif0", "低使能三态反相器"),
    ):
        prims[name] = GatePrimitive(
            name, zh, 1, 2, output_ports=("out",), input_ports=ctrl_ports)
    # MOS 开关：位置序 = out, in, ctrl（r 前缀=电阻型同构）
    for name, zh in (
        ("pmos", "P 型 MOS 开关"), ("nmos", "N 型 MOS 开关"),
        ("rpmos", "P 型电阻 MOS 开关"), ("rnmos", "N 型电阻 MOS 开关"),
    ):
        prims[name] = GatePrimitive(
            name, zh, 1, 2, output_ports=("out",), input_ports=ctrl_ports)
    # CMOS 开关：位置序 = out, in, nctrl, pctrl
    for name, zh in (("cmos", "CMOS 开关"), ("rcmos", "电阻 CMOS 开关")):
        prims[name] = GatePrimitive(
            name, zh, 1, 3, output_ports=("out",),
            input_ports=("in", "nctrl", "pctrl"))
    # 双向开关：位置序 = a, b[, ctrl]——驱动方向不定，拓扑两侧都不计
    for name, zh in (
        ("tran", "双向开关"), ("rtran", "电阻双向开关"),
        ("tranif1", "高使能双向开关"), ("tranif0", "低使能双向开关"),
        ("rtranif1", "高使能电阻双向开关"), ("rtranif0", "低使能电阻双向开关"),
    ):
        ctrl = name.endswith("if0") or name.endswith("if1")
        ports = ("a", "b") + (("ctrl",) if ctrl else ())
        prims[name] = GatePrimitive(
            name, zh, 0, len(ports), bidirectional=True,
            output_ports=(), input_ports=ports)
    # 上拉/下拉：单输出无输入
    for name, zh in (("pullup", "上拉"), ("pulldown", "下拉")):
        prims[name] = GatePrimitive(
            name, zh, 1, 0, output_ports=("out",), input_ports=())
    return prims


#: 门级原语注册表（键=原语名；RegistryKit 单源，键面=LRM 14 章全集）。
GATE_PRIMITIVES: RegistryKit[GatePrimitive] = RegistryKit(
    label="Verilog 门级原语", allow_overwrite=True)
for _name, _prim in _build_gate_primitives().items():
    GATE_PRIMITIVES.register(_name, _prim)

#: 典型数字单元类型名录（非门级原语、单元库常见实例类型——仅作归类
#: 提示元数据 ``well_known_cell``，不参与连接方向判定：模块实例方向
#: 由子模块端口声明决定，子模块未知时如实记外部边界）。
WELL_KNOWN_CELL_TYPES = frozenset({
    "mux", "mux2", "mux4", "mux8", "dff", "dfr", "dffr", "dffs",
    "latch", "dlatch", "sdlatch", "flipflop", "register",
    "adder", "sub", "mult", "cmp", "counter", "decoder", "encoder",
})

_WORD_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_SIZE_NUM_RE = re.compile(r"\d[\d_]*")
_SIZED_LITERAL_RE = re.compile(
    r"(?:\d[\d_]*)?'[sS]?([bodhBODH])([0-9a-fA-FxXzZ_?]+)")
#: ANSI 头内端口缺省值/参数值等表达式捕获终止词（深度 0 判定用）。
_EXPR_STOP = frozenset({",", ";", ")", "]", "}"})

# ── 词法（tokenizer）────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Token:
    """一个词：kind（id/num/str/punct/dir/sys）+ 原文 + 起始行号。"""

    kind: str
    text: str
    line: int


#: 多字符运算符（先 3 字符后 2 字符，最大吞噬；单字符由标点集兜底）。
_OPERATORS_3 = ("===", "!==", "<<<", ">>>", "&&&")
_OPERATORS_2 = (
    "<=", ">=", "==", "!=", "<<", ">>", "&&", "||", "**",
    "~&", "~|", "~^", "^~", "->",
)
_PUNCT_CHARS = "()[]{}:;,.#=+-*/%&|^~<>?!@"


def tokenize_verilog(text: str) -> list[Token]:
    """Verilog 结构子集词法：文本 → token 序列。

    词法错误（块注释/字符串未闭合）抛 :class:`VerilogParseError`
    带行号；编译器指令整行消费（含行尾续行）为单个 ``dir`` token
    （text=指令名去反引号）。
    """
    tokens: list[Token] = []
    i = 0
    n = len(text)
    line = 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise VerilogParseError(f"第 {line} 行：块注释未闭合")
            line += text.count("\n", i, end + 2)
            i = end + 2
            continue
        if c == '"':
            j = i + 1
            closed = False
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if text[j] == '"':
                    closed = True
                    break
                j += 1
            if not closed:
                raise VerilogParseError(f"第 {line} 行：字符串未闭合")
            tokens.append(Token("str", text[i:j + 1], line))
            line += text.count("\n", i, j)
            i = j + 1
            continue
        if c == "\\":
            # 转义标识符：\name 到空白止（Verilog 转义标识符规则）
            m = re.match(r"\\(\S+)", text[i:])
            if m:
                tokens.append(Token("id", m.group(1), line))
                i += 1 + len(m.group(1))
                continue
            i += 1  # 孤立反斜杠当普通字符跳过（fail-soft）
            continue
        if c == "`":
            # 编译器指令：整行消费（行尾 \ 续行）；text=指令名去反引号
            j = i + 1
            m = _WORD_RE.match(text, j)
            name = m.group(0) if m else ""
            j = m.end() if m else j
            while j < n and text[j] != "\n":
                if text[j] == "\\" and j + 1 < n and text[j + 1] == "\n":
                    line += 1
                    j += 2
                    continue
                j += 1
            tokens.append(Token("dir", name, line))
            i = j
            continue
        if c == "$":
            m = _WORD_RE.match(text, i)
            tokens.append(Token("sys", m.group(0) if m else "$", line))
            i = m.end() if m else i + 1
            continue
        if c.isdigit():
            m = _SIZE_NUM_RE.match(text, i)
            tokens.append(Token("num", m.group(0), line))
            i = m.end()
            continue
        if c == "'":
            # 位宽字面量后半 'b1010 / 'hFF / 'd10 / 'sd15（含 x/z/? 位）
            j = i + 1
            if j < n and text[j] in "sS":
                j += 1
            if j < n and text[j] in "bodhBODH":
                j += 1
                while j < n and (text[j].isalnum() or text[j] in "_?xXzZ"):
                    j += 1
                tokens.append(Token("num", text[i:j], line))
                i = j
                continue
            tokens.append(Token("punct", "'", line))
            i += 1
            continue
        m = _WORD_RE.match(text, i)
        if m:
            tokens.append(Token("id", m.group(0), line))
            i = m.end()
            continue
        matched = 0
        for chunk in (text[i:i + 3], text[i:i + 2]):
            if len(chunk) >= 2 and chunk in (
                    _OPERATORS_3 if len(chunk) == 3 else _OPERATORS_2):
                matched = len(chunk)
                break
        if matched:
            tokens.append(Token("punct", text[i:i + matched], line))
            i += matched
            continue
        if c in _PUNCT_CHARS:
            tokens.append(Token("punct", c, line))
            i += 1
            continue
        raise VerilogParseError(f"第 {line} 行：无法识别的字符 {c!r}")
    return tokens


def parse_verilog_number(text: str) -> dict[str, Any] | None:
    """Verilog 数字字面量 → ``{value, bits, base, has_xz, raw}`` 单源解析。

    - 明数（``42`` / ``1_000``）→ value int、bits/base None；
    - 位宽字面量 ``8'hFF`` / ``4'b0101_x`` / ``12'd135`` / ``1'bx`` →
      value int（x/z/? 位按 0 计入位权、``has_xz`` 如实标注——静态
      解析不猜未知位语义）、bits/base 落键；
    - 其余（表达式、浮点等）→ None（调用方如实保留原文）。
    """
    raw = text.strip()
    if not raw:
        return None
    if "'" in raw:
        m = _SIZED_LITERAL_RE.fullmatch(raw)
        if not m:
            return None
        base_ch, digits = m.groups()
        base_map = {"b": 2, "o": 8, "d": 10, "h": 16}
        base = base_map[base_ch.lower()]
        clean = digits.replace("_", "")
        has_xz = any(ch in "xXzZ?" for ch in clean)
        value = 0
        for ch in clean:
            digit = 0 if ch in "xXzZ?" else int(ch, base)
            value = value * base + digit
        bits_m = _SIZE_NUM_RE.match(raw)
        return {
            "value": value,
            "bits": int(bits_m.group(0).replace("_", ""))
            if bits_m else None,
            "base": base_ch.lower(),
            "has_xz": has_xz,
            "raw": raw,
        }
    if _SIZE_NUM_RE.fullmatch(raw):
        return {
            "value": int(raw.replace("_", "")),
            "bits": None, "base": None, "has_xz": False, "raw": raw,
        }
    return None


# ── 表达式辅助 ──────────────────────────────────────────────────────────────

_NO_SPACE_BEFORE = frozenset({",", ";", ")", "]", "}", ":", "."})
_NO_SPACE_AFTER = frozenset({"(", "[", "{", "."})


def _join_expr(tokens: list[Token]) -> str:
    """token 序列 → 表达式原文（确定性重建：标点贴身、词间单空格）。

    ``:`` 在括号外（三目）带空格、括号内（``[msb:lsb]`` 范围冒号）贴
    身——括号深度计数区分两义。
    """
    out = ""
    depth = 0
    for k, tok in enumerate(tokens):
        piece = tok.text
        if k == 0:
            out = piece
            depth += piece in "([{"
            depth -= piece in ")]}"
            continue
        prev = tokens[k - 1].text
        no_space = (
            piece in _NO_SPACE_BEFORE
            or piece.startswith("'")
            or piece.startswith("[")
            or prev in _NO_SPACE_AFTER
            or (piece == ":" and depth > 0)
            or (prev == ":" and depth > 0)
        )
        if not no_space:
            out += " "
        out += piece
        depth += piece in "([{"
        depth -= piece in ")]}"
    return out


#: 标识符（含层次名）正则——拓扑取网基名时逐命中过滤常量。
_IDENT_FULL_RE = re.compile(
    r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*")
#: 位宽字面量整体剔除正则（防 ``3'b000`` 的 ``b000`` 被当网基名）。
_SIZED_STRIP_RE = re.compile(r"\d[\d_]*'[sS]?[bodhBODH][0-9a-fA-FxXzZ_?]+")


def _net_bases(expr: str) -> list[str]:
    """连接/表达式 → 网基名有序去重表（位选取基名、拼接展开、常量剔除）。

    ``{a, b[3], 1'b0, c[msb-1:0]}`` → ``[a, b, c]``；层次名 ``u1.n``
    整体保留（跨层引用如实登记）；纯数字/位宽字面量剔除。
    """
    bases: list[str] = []
    for m in _IDENT_FULL_RE.finditer(_SIZED_STRIP_RE.sub(" ", expr)):
        name = m.group(0)
        if parse_verilog_number(name) is not None:
            continue
        if name not in bases:
            bases.append(name)
    return bases


# ── 解析器 ──────────────────────────────────────────────────────────────────


@dataclass
class _PendingPort:
    """ANSI 头/体内端口声明的中间态（方向/类型上下文沿用）。"""

    name: str
    direction: str | None = None
    net_kind: str | None = None
    range_: tuple[str, str] | None = None


@dataclass
class _VerilogParser:
    """递归下降解析器（token 流 → 模块文档；fail-soft 警告面）。"""

    tokens: list[Token]
    pos: int = 0
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)
    module_order: list[str] = field(default_factory=list)
    doc_warnings: list[dict[str, Any]] = field(default_factory=list)
    directives: list[str] = field(default_factory=list)
    instantiations: list[dict[str, str]] = field(default_factory=list)

    # ── 基础游标 ──
    def peek(self, ahead: int = 0) -> Token | None:
        idx = self.pos + ahead
        return self.tokens[idx] if idx < len(self.tokens) else None

    def next(self) -> Token | None:
        tok = self.peek()
        if tok is not None:
            self.pos += 1
        return tok

    def at_punct(self, text: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "punct" and tok.text == text

    def at_id(self, text: str | None = None) -> bool:
        tok = self.peek()
        if tok is None or tok.kind != "id":
            return False
        return text is None or tok.text == text

    def eat_punct(self, text: str) -> bool:
        if self.at_punct(text):
            self.next()
            return True
        return False

    def expect_punct(self, text: str) -> Token:
        tok = self.next()
        if tok is None or tok.kind != "punct" or tok.text != text:
            found = tok.text if tok else "<EOF>"
            line = tok.line if tok else (
                self.tokens[-1].line if self.tokens else 0)
            raise VerilogParseError(
                f"第 {line} 行：期望 {text!r}，实得 {found!r}")
        return tok

    def expect_id(self) -> Token:
        tok = self.next()
        if tok is None or tok.kind != "id":
            found = tok.text if tok else "<EOF>"
            line = tok.line if tok else 0
            raise VerilogParseError(
                f"第 {line} 行：期望标识符，实得 {found!r}")
        return tok

    def warn(self, line: int, name: str, note: str) -> None:
        self.doc_warnings.append({"line": line, "name": name, "note": note})

    # ── 表达式捕获 ──
    def capture_expr(self, stops: frozenset[str] = _EXPR_STOP) -> str:
        """捕获表达式到深度 0 终止词止（返回原文重建；游标停在终止词）。

        深度计数对 ``()[]{}`` 三对括号配平；三目 ``?:``、位选
        ``[msb-1:0]``、拼接 ``{a, b}``、位宽字面量自然保真。
        """
        parts: list[Token] = []
        depth = 0
        while True:
            tok = self.peek()
            if tok is None:
                break
            if tok.kind == "punct":
                if tok.text in "([{":
                    depth += 1
                elif tok.text in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif depth == 0 and tok.text in stops:
                    break
            parts.append(tok)
            self.pos += 1
        return _join_expr(parts)

    def capture_range(self) -> tuple[str, str] | None:
        """``[msb:lsb]`` 范围捕获（无范围返回 None；``[i]`` 单位选按
        ``[i:i]`` 口径记，span=1）。"""
        if not self.at_punct("["):
            return None
        self.next()  # '['
        msb = self.capture_expr(frozenset({":", "]"}))
        lsb = self.capture_expr(frozenset({"]"})) \
            if self.eat_punct(":") else msb
        self.expect_punct("]")
        return (msb, lsb)

    def capture_paren_body(self) -> str:
        """``(...)`` 体捕获（``#`` 后参数/延迟面；返回括号内原文）。"""
        self.expect_punct("(")
        body = self.capture_expr(frozenset({")"}))
        self.expect_punct(")")
        return body

    # ── 跳过类构造（fail-soft，记 warning）──
    def skip_statement(self) -> None:
        """单语句跳过：到下一个 ``;`` 止（重同步点）。

        ``;`` 无条件终止——fail-soft 重同步的对象正是括号失衡的病态
        语句（``and g1 (b, a;`` 缺右括号），按括号深度判 ``;`` 会把
        失衡深度带进后续语句吞掉整个模块体（首版实测踩坑）。
        """
        while True:
            tok = self.next()
            if tok is None:
                return
            if tok.kind == "punct" and tok.text == ";":
                return

    def skip_balanced_block(self, open_kw: str, close_kw: str, line: int) -> None:
        """关键字配平跳块（begin/end、generate/endgenerate 等独立对）。"""
        depth = 1
        while depth > 0:
            tok = self.next()
            if tok is None:
                self.warn(line, "unterminated_block",
                          f"{open_kw} 块未闭合（{close_kw} 缺失，EOF 兜底）")
                return
            if tok.kind == "id":
                if tok.text == open_kw:
                    depth += 1
                elif tok.text == close_kw:
                    depth -= 1

    def skip_behavioral(self, kw: str, line: int) -> None:
        """always/initial/function/task/specify/generate/config 块跳过。

        generate/config=纯关键字配平（体是结构语句的生成块原样吞）；
        其余=签名到 ``;`` 后，begin/end 配平或逐语句推进直到块级构造
        /对应 end* 关键字（``endfunction`` 类闭合词是终止符——防吞块
        后模块体，skip 泄漏是本方法第一版实测踩过的坑）。
        """
        if kw in ("generate", "config"):
            self.skip_balanced_block(kw, "end" + kw, line)
            return
        close_kw = {
            "always": "end", "initial": "end",
            "function": "endfunction", "task": "endtask",
            "specify": "endspecify",
        }[kw]
        if kw in ("function", "task", "specify"):
            self.skip_statement()  # 签名头到 ';'
        while True:
            tok = self.peek()
            if tok is None:
                self.warn(line, "unterminated_block",
                          f"{kw} 块未闭合（EOF 兜底）")
                return
            if tok.kind == "id":
                if tok.text == close_kw or (
                        kw in ("always", "initial") and tok.text == "end"):
                    self.next()
                    return
                if tok.text == "begin":
                    self.next()
                    self.skip_balanced_block("begin", "end", tok.line)
                    return
                if tok.text in BEHAVIORAL_KEYWORDS or tok.text == "endmodule":
                    # 嵌套行为块/endmodule 留给宿主循环（游标不越权）
                    if tok.text != "endmodule":
                        self.warn(tok.line, "behavioral_skip_nested",
                                  f"{kw} 块内嵌套 {tok.text}，外层跳过到此为止")
                    return
                if tok.text in ("case", "casex", "casez"):
                    self.next()
                    self.skip_statement()  # case 头 (expr)
                    self.skip_case_body(tok.line)
                    continue
            if tok.kind == "punct" and tok.text == ";":
                self.next()
                return
            self.next()

    def skip_case_body(self, line: int) -> None:
        """case 体跳过：配平 ``case`` 族/``endcase``（begin/end 独立配平
        由宿主语句面承担，此处只对 case 嵌套计数）。"""
        depth = 1
        while depth > 0:
            tok = self.next()
            if tok is None:
                self.warn(line, "unterminated_block",
                          "case 块未闭合（EOF 兜底）")
                return
            if tok.kind == "id":
                if tok.text in ("case", "casex", "casez"):
                    depth += 1
                elif tok.text == "endcase":
                    depth -= 1

    # ── module 主循环 ──
    def parse_document(self) -> None:
        """顶层循环：module 声明 + 散落指令/杂项。"""
        while True:
            tok = self.peek()
            if tok is None:
                return
            if tok.kind == "dir":
                self.next()
                if tok.text and tok.text not in self.directives:
                    self.directives.append(tok.text)
                continue
            if tok.kind == "id" and tok.text == "module":
                self.parse_module()
                continue
            if tok.kind == "punct" and tok.text == ";":
                self.next()
                continue
            if tok.kind == "id" and tok.text in ("parameter", "localparam"):
                self.warn(tok.line, "top_level_parameter",
                          f"顶层 {tok.text} 声明（编译单元参数，跳过）")
                self.next()
                self.skip_statement()
                continue
            self.warn(tok.line, "skipped_top_level",
                      f"顶层散落构造 {tok.text!r}（结构子集外，跳过）")
            self.next()
            if tok.kind == "id" and tok.text == "endmodule":
                continue
            self.skip_statement()

    def parse_module(self) -> None:
        """``module name [#(params)] (ports) ;  body  endmodule``。"""
        mod_tok = self.expect_id()  # 'module'
        line = mod_tok.line
        name = self.expect_id().text
        header_params_raw = None
        if self.at_punct("#"):
            self.next()
            header_params_raw = self.capture_paren_body()
        pending: dict[str, _PendingPort] = {}
        ports: list[dict[str, Any]] = []
        ansi = False
        if self.at_punct("("):
            ansi = self._parse_header_ports(pending)
        # ANSI 头已带方向/类型/范围 → 直接成 port 项；1995 头只列名
        # （无任何声明痕迹）→ 由体内声明回填，此处不产半猜端口
        for pname, pend in pending.items():
            if pend.direction is not None or pend.net_kind is not None \
                    or pend.range_ is not None:
                ports.append({
                    "name": pname,
                    "direction": pend.direction,
                    "width": _width_of(pend.range_),
                })
        self.expect_punct(";")
        body: dict[str, Any] = {
            "name": name,
            "ports": ports,
            "wires": [],
            "assigns": [],
            "instances": [],
            "parameters": {},
            "localparams": {},
            "defparams": [],
            "header_params_raw": header_params_raw,
            "directives": [],
            "warnings": [],
            "ansi_ports": ansi,
        }
        self._parse_module_body(body, pending)
        self.modules[name] = body
        self.module_order.append(name)
        _ = line

    def _parse_header_ports(self, pending: dict[str, _PendingPort]) -> bool:
        """模块头端口表：返回是否 ANSI 形态（出现方向/类型/范围声明）。"""
        self.expect_punct("(")
        ansi = False
        cur_dir: str | None = None
        cur_kind: str | None = None
        cur_range: tuple[str, str] | None = None
        while True:
            tok = self.peek()
            if tok is None:
                raise VerilogParseError("模块头端口表未闭合（EOF）")
            if tok.kind == "punct" and tok.text == ")":
                self.next()
                return ansi
            if tok.kind == "id" and tok.text in DIRECTIONS:
                cur_dir = tok.text
                cur_kind = None
                cur_range = None
                ansi = True
                self.next()
                continue
            if tok.kind == "id" and tok.text in NET_TYPE_KEYWORDS:
                cur_kind = tok.text
                self.next()
                continue
            if tok.kind == "id" and tok.text == "signed":
                self.next()
                continue
            if tok.kind == "punct" and tok.text == "[":
                cur_range = self.capture_range()
                continue
            if tok.kind == "punct" and tok.text == ",":
                self.next()
                continue
            if tok.kind == "id":
                pname = self.expect_id().text
                pending[pname] = _PendingPort(
                    pname, cur_dir, cur_kind, cur_range)
                if self.at_punct("="):  # ANSI 缺省值（罕见）随声明消费
                    self.next()
                    self.capture_expr(frozenset({",", ")"}))
                continue
            self.warn(tok.line, "skipped_header_token",
                      f"端口表内散落 token {tok.text!r}（跳过）")
            self.next()

    def _parse_module_body(
        self, body: dict[str, Any], pending: dict[str, _PendingPort]
    ) -> None:
        """模块体主循环（1995 端口方向声明回填在本循环）。"""
        while True:
            tok = self.peek()
            if tok is None:
                self.warn(
                    self.tokens[-1].line if self.tokens else 0,
                    "unterminated_module",
                    f"模块 {body['name']} 未闭合（endmodule 缺失，EOF 兜底）")
                return
            if tok.kind == "dir":
                self.next()
                if tok.text and tok.text not in body["directives"]:
                    body["directives"].append(tok.text)
                continue
            if tok.kind == "punct" and tok.text == ";":
                self.next()
                continue
            if tok.kind == "id" and tok.text == "endmodule":
                self.next()
                return
            if tok.kind == "id" and tok.text in DIRECTIONS:
                self._parse_statement_safe(
                    tok.line, tok.text, self._parse_port_decl, body, pending)
                continue
            if tok.kind == "id" and tok.text in NET_TYPE_KEYWORDS:
                self._parse_statement_safe(
                    tok.line, tok.text, self._parse_net_decl, body)
                continue
            if tok.kind == "id" and tok.text in ("parameter", "localparam"):
                self._parse_statement_safe(
                    tok.line, tok.text, self._parse_param_decl, body, tok.text)
                continue
            if tok.kind == "id" and tok.text == "defparam":
                self._parse_statement_safe(
                    tok.line, tok.text, self._parse_defparam, body)
                continue
            if tok.kind == "id" and tok.text == "assign":
                self._parse_statement_safe(
                    tok.line, tok.text, self._parse_assign, body, tok.line)
                continue
            if tok.kind == "id" and tok.text in BEHAVIORAL_KEYWORDS:
                self.next()
                self.skip_behavioral(tok.text, tok.line)
                body["warnings"].append({
                    "line": tok.line, "name": tok.text,
                    "note": f"{tok.text} 行为/生成块整体跳过"
                            "（结构解析不进行为语义）",
                })
                continue
            if tok.kind == "id" and tok.text in ("begin", "end"):
                self.warn(tok.line, "stray_keyword",
                          f"模块体散落关键字 {tok.text}（跳过）")
                self.next()
                continue
            if tok.kind == "id":
                self._parse_instance_safe(body)
                continue
            self.warn(tok.line, "skipped_body_token",
                      f"模块体散落 token {tok.text!r}（结构子集外，跳过）")
            self.next()
            self.skip_statement()

    def _parse_statement_safe(
        self, line: int, kw: str, fn: Any, *args: Any
    ) -> None:
        """模块体语句 fail-soft 包装：结构违规降级警告+跳语句重同步。

        ``fn(*args)`` 解析中抛 :class:`VerilogParseError`（缺 ``;``/缺
        右值等结构违规）→ 记 warning 后从当前位置跳到下一条 ``;``（重
        同步点），不炸全文档（spice_netlist_parser fail-soft 家法；词法
        级错误——注释/字符串未闭合——仍属 :func:`tokenize_verilog` 阶段
        硬错）。
        """
        saved = self.pos
        try:
            fn(*args)
        except VerilogParseError as exc:
            self.pos = saved + 1  # 起始 token 已消费，防死循环
            self.warn(line, "statement_parse_failed",
                      f"{kw} 语句解析失败降级跳语句：{exc}")
            self.skip_statement()

    def _parse_instance_safe(self, body: dict[str, Any]) -> None:
        """实例解析 fail-soft 包装：病态构造降级警告+跳语句，不炸文档。"""
        tok = self.peek()
        start_line = tok.line if tok else 0
        saved = self.pos
        try:
            self._parse_instance(body)
        except VerilogParseError as exc:
            self.pos = saved + 1  # 起始 token 已消费，防死循环
            self.warn(start_line, "instance_parse_failed",
                      f"实例解析失败降级跳语句：{exc}")
            self.skip_statement()

    def _parse_port_decl(
        self, body: dict[str, Any], pending: dict[str, _PendingPort]
    ) -> None:
        """体内端口方向声明（1995 形态）：回填 header 端口/补隐式端口。"""
        dir_tok = self.expect_id()
        direction = dir_tok.text
        net_kind: str | None = None
        if self.at_id() and self.peek().text in NET_TYPE_KEYWORDS:
            net_kind = self.next().text
        while self.at_id() and self.peek().text == "signed":
            self.next()
        range_ = self.capture_range()
        names: list[str] = []
        while self.at_id():
            pname = self.expect_id().text
            names.append(pname)
            pend = pending.get(pname)
            if pend is None:
                pending[pname] = _PendingPort(
                    pname, direction, net_kind, range_)
            else:
                pend.direction = direction
                if net_kind:
                    pend.net_kind = net_kind
                if range_:
                    pend.range_ = range_
            if not self.eat_punct(","):
                break
        self.expect_punct(";")
        existing = {p["name"] for p in body["ports"]}
        for pname in names:
            if pname not in existing:
                body["ports"].append({
                    "name": pname,
                    "direction": direction,
                    "width": _width_of(pending[pname].range_),
                })

    def _parse_net_decl(self, body: dict[str, Any]) -> None:
        """网/reg 声明：``wire [3:0] a, b ;``（reg 初始化/强度/延迟）。

        LRM 顺序 net_type [drive_strength] [vectored|scalared] [range]
        [delay3]——范围与强度/延迟的相对序按宽容口径（attributes 循环
        消费）逐项收。
        """
        kind = self.expect_id().text
        while self.at_id() and self.peek().text in ("signed", "scalared",
                                                    "vectored"):
            self.next()
        range_: tuple[str, str] | None = None
        strength: str | None = None
        delay: str | None = None
        for _ in range(3):  # 属性三件套宽容循环（range/强度/#延迟）
            if range_ is None and self.at_punct("["):
                range_ = self.capture_range()
                continue
            if strength is None and self.at_punct("("):
                strength = self.capture_paren_body()
                continue
            if delay is None and self.at_punct("#"):
                delay = self._capture_delay()
                continue
            break
        while True:
            tok = self.peek()
            if tok is None or (tok.kind == "punct"
                               and tok.text in (")", "}", ";")):
                break
            if tok.kind == "punct" and tok.text == ",":
                self.next()
                continue
            if tok.kind == "id":
                wname = self.expect_id().text
                init = None
                if self.at_punct("="):  # reg 初始化/网初值
                    self.next()
                    init = self.capture_expr()
                body["wires"].append({
                    "name": wname, "kind": kind,
                    "width": _width_of(range_),
                    "init": init,
                    "strength": strength, "delay": delay,
                })
                continue
            self.warn(tok.line, "skipped_net_decl_token",
                      f"网声明内散落 token {tok.text!r}（跳过）")
            self.next()
        self.expect_punct(";")

    def _parse_param_decl(self, body: dict[str, Any], kw: str) -> None:
        """parameter/localparam：``parameter W = 8, H = W*2 ;``"""
        self.next()  # kw
        while self.at_id() and self.peek().text in ("signed", "integer",
                                                    "real", "type"):
            self.next()
        self.capture_range()  # 位宽参数形 [3:0]（SV 类型参数随 range 吞）
        bucket = body["parameters"] if kw == "parameter" else body["localparams"]
        while True:
            if not self.at_id():
                break
            pname = self.expect_id().text
            if self.eat_punct("="):
                bucket[pname] = self.capture_expr()
            else:
                bucket[pname] = None
            if not self.eat_punct(","):
                break
        self.expect_punct(";")

    def _capture_delay(self) -> str:
        """``#`` 延迟捕获：括号形 ``#(1,2)`` 全体捕获；裸形 ``#2`` 只取
        一个 token（延迟与 lhs 之间无分隔符，裸形贪多会吞 lhs——
        assign #2 n1[3:1] 首版实测踩坑）。"""
        self.expect_punct("#")
        if self.at_punct("("):
            return "#" + self.capture_paren_body() + ")"
        tok = self.next()
        if tok is None:
            raise VerilogParseError("延迟声明缺值（EOF）")
        return "#" + tok.text

    def _parse_defparam(self, body: dict[str, Any]) -> None:
        """defparam inst.path.P = v；多目标逗号形逐条展开。"""
        line = self.expect_id().line  # 'defparam'
        while True:
            target = self.capture_expr(frozenset({"="}))
            value = None
            if self.eat_punct("="):
                value = self.capture_expr()
            tpath, _, param = target.rpartition(".")
            body["defparams"].append({
                "target": tpath or target, "param": param, "value": value,
            })
            if not self.eat_punct(","):
                break
        self.expect_punct(";")
        _ = line

    def _parse_assign(self, body: dict[str, Any], line: int) -> None:
        """连续赋值：``assign [#d] lhs = rhs[, lhs2 = rhs2] ;``"""
        self.next()  # assign
        delay = None
        if self.at_punct("#"):
            delay = self._capture_delay()
        while True:
            lhs = self.capture_expr(frozenset({"="}))
            if not self.eat_punct("="):
                self.warn(line, "assign_without_rhs",
                          f"assign 目标 {lhs!r} 无 '=' 右值（跳过）")
                break
            rhs = self.capture_expr()
            body["assigns"].append({"lhs": lhs, "rhs": rhs, "delay": delay})
            if not self.eat_punct(","):
                break
        self.expect_punct(";")

    def _parse_instance(self, body: dict[str, Any]) -> None:
        """实例：``type [#(params/delay)] name [range] (connections) ;``"""
        type_tok = self.expect_id()
        itype = type_tok.text
        line = type_tok.line
        hash_named: dict[str, str] | None = None
        hash_positional: dict[str, str] | None = None
        if self.eat_punct("#"):
            # 参数化 ``#(.W(8))`` 与延迟 ``#(1,2)`` 同壳异义：括号形统一
            # 开括后按 "." 分流（命名=参数、裸=延迟/位置参数）
            self.expect_punct("(")
            if self.at_punct("."):
                hash_named = {}
                while True:
                    if self.at_punct("."):
                        self.next()
                        pname = self.expect_id().text
                        self.expect_punct("(")
                        pval = "" if self.at_punct(")") else self.capture_expr()
                        self.expect_punct(")")
                        hash_named[pname] = pval
                    elif self.eat_punct(","):
                        continue
                    else:
                        break
            else:
                hash_positional = {}
                while True:
                    if self.at_punct(")"):
                        break
                    if self.peek() is None:
                        raise VerilogParseError(
                            f"第 {line} 行：实例 {itype!r} 参数表未闭合（EOF）")
                    if self.eat_punct(","):
                        continue
                    k = str(len(hash_positional) + 1)
                    saved = self.pos
                    hash_positional[k] = self.capture_expr()
                    if self.pos == saved:
                        raise VerilogParseError(
                            f"第 {line} 行：实例 {itype!r} 参数表止于意外词"
                            f" {self.peek().text!r}")
            self.expect_punct(")")
        name = self.expect_id().text
        range_ = self.capture_range()
        conns_named: dict[str, str] = {}
        conns_positional: dict[str, str] = {}
        self.expect_punct("(")
        while not self.at_punct(")"):
            if self.peek() is None:
                raise VerilogParseError(
                    f"第 {line} 行：实例 {name!r} 连接表未闭合（EOF）")
            if self.at_punct("."):
                self.next()
                pname = self.expect_id().text
                self.expect_punct("(")
                val = "" if self.at_punct(")") else self.capture_expr()
                self.expect_punct(")")
                conns_named[pname] = val
            elif self.eat_punct(","):
                continue
            else:
                k = str(len(conns_positional) + 1)
                saved = self.pos
                conns_positional[k] = self.capture_expr()
                if self.pos == saved:
                    # 表达式零进展（连接表止于 ';' 类终止词——病态实例
                    # 如 ``and g1 (b, a;``）：不臆断，抛错交 safe 包装
                    # 降级跳语句（零进展死循环首版实测踩坑）
                    raise VerilogParseError(
                        f"第 {line} 行：实例 {name!r} 连接表止于意外词"
                        f" {self.peek().text!r}")
        self.expect_punct(")")
        prim = GATE_PRIMITIVES.get(itype, None)
        style = "positional" if conns_positional and not conns_named \
            else "named"
        if prim is not None:
            # 门级原语：位置→命名归一（注册表元数据单源）；#(...) 是
            # 延迟不是参数（门无参数化）
            named = _gate_positional_to_named(prim, conns_positional)
            named.update(conns_named)  # 显式命名形优先
            delay = None
            if hash_named is not None:
                delay = "#(" + ", ".join(
                    f".{k}({v})" if v else f".{k}()"
                    for k, v in hash_named.items()) + ")"
            elif hash_positional is not None:
                delay = "#(" + ", ".join(
                    hash_positional[k]
                    for k in sorted(hash_positional, key=int)) + ")"
            entry: dict[str, Any] = {
                "type": itype, "name": name, "connections": named,
                "connection_style": style, "range": _range_str(range_),
                "delay": delay, "params": None,
                "primitive": True,
                "well_known_cell": False, "line": line,
            }
        else:
            params: dict[str, str] | None = None
            if hash_named is not None:
                params = hash_named
            elif hash_positional is not None:
                params = hash_positional  # 位置参数按序号键保序
            conns = dict(conns_named) if conns_named \
                else dict(conns_positional)
            entry = {
                "type": itype, "name": name, "connections": conns,
                "connection_style": style, "range": _range_str(range_),
                "delay": None, "params": params,
                "primitive": False,
                "well_known_cell": itype in WELL_KNOWN_CELL_TYPES,
                "line": line,
            }
        self.instantiations.append({
            "parent": body["name"], "child": itype, "instance": name,
        })
        body["instances"].append(entry)


def _range_str(range_: tuple[str, str] | None) -> str | None:
    """范围二元组 → ``[msb:lsb]`` 原文串（无范围 None）。"""
    if range_ is None:
        return None
    return f"[{range_[0]}:{range_[1]}]"


def _gate_positional_to_named(
    prim: GatePrimitive, positional: dict[str, str]
) -> dict[str, str]:
    """门级原语位置连接 → 命名映射（注册表元数据单源）。

    多输入门（and 族）：位置 1=out，2..N=in1..in(N-1)；not/buf（多输
    出变体）：位置 1..N-1=out1..out(N-1)，位置 N=in；三态/MOS：out,
    in, ctrl(们)；双向 tran 族：a, b[, ctrl]。端子数超元数据键面时按
    序号键兜底+不猜（宁保序登记不臆断方向）。
    """
    n = len(positional)
    if prim.bidirectional:
        keys = list(prim.input_ports)
    elif prim.n_outputs == 1 and prim.n_inputs is None:
        keys = ["out", *(f"in{k}" for k in range(1, max(n, 2)))]
    elif prim.n_outputs is None and prim.n_inputs == 1:
        keys = [*(f"out{k}" for k in range(1, max(n, 2))), "in"]
    elif prim.n_outputs == 1 and prim.n_inputs is not None:
        keys = ["out", *prim.input_ports]
    else:
        keys = [*prim.output_ports, *prim.input_ports]
    out: dict[str, str] = {}
    for i, key in enumerate(sorted(positional, key=int)):
        out[keys[i] if i < len(keys) else str(i + 1)] = positional[key]
    return out


def _width_of(range_: tuple[str, str] | None) -> dict[str, Any]:
    """范围二元组 → width 结构（``{msb, lsb, span}``；span 数值化尽力）。"""
    if range_ is None:
        return {"msb": None, "lsb": None, "span": 1}
    msb_raw, lsb_raw = range_
    msb = parse_verilog_number(msb_raw)
    lsb = parse_verilog_number(lsb_raw)
    span: int | None = None
    if msb is not None and lsb is not None \
            and not msb["has_xz"] and not lsb["has_xz"]:
        span = abs(msb["value"] - lsb["value"]) + 1
    return {"msb": msb_raw, "lsb": lsb_raw, "span": span}


# ── 拓扑提取 ────────────────────────────────────────────────────────────────


def extract_module_topology(
    doc: dict[str, Any], module_name: str
) -> dict[str, Any]:
    """单模块作用域拓扑：三层关系+孤立网检测+实例级树深度。

    网宇宙 = 声明网（wire 族+reg）∪ 各连接/assign 表达式中出现的网基
    名（隐式网如实并入）∪ 端口名。驱动源三类：``instance``（门/模块
    实例输出端口）、``assign``（连续赋值 lhs）、``port``（模块 input/
    inout 边界馈入）；读者三类对称（instance 输入/assign rhs/port
    output/inout）。模块实例端口方向由文档内子模块端口声明决定（**位
    置连接按子模块端口声明序对位**）；子模块未知的实例（外部单元库）
    连接网记 ``external_boundary_nets``（驱动方向不可判，孤立网检测
    豁免——宁不报不误报 #122 口径）。

    reg 类网不进 undriven 孤立网候选：过程赋值驱动被行为块跳过属已
    知盲区（无证据不下结论）。对称盲区在 unloaded 侧：过程读取同样
    不可见——``behavioral_skipped=True``（模块含被跳过的行为/生成块）
    时两桶候选都是嫌疑面非终判，消费方如实对待。环检测（组合反馈环）
    → ``cyclic=True`` + 环上实例名录、depth 如实置 None。
    """
    body = doc["modules"].get(module_name)
    if body is None:
        raise KeyError(
            f"模块 {module_name!r} 不存在（可用: {', '.join(doc['modules'])}）")
    net_drivers: dict[str, list[dict[str, str]]] = {}
    net_readers: dict[str, list[dict[str, str]]] = {}

    def add(drivers: bool, net: str, source: dict[str, str]) -> None:
        table = net_drivers if drivers else net_readers
        lst = table.setdefault(net, [])
        if source not in lst:
            lst.append(source)

    port_dirs = {p["name"]: p["direction"] for p in body["ports"]}
    external_boundary: set[str] = set()
    known_modules = set(doc["modules"])

    for inst in body["instances"]:
        src_inst = {"kind": "instance", "name": inst["name"]}
        unknown_child = (not inst["primitive"]) \
            and inst["type"] not in known_modules
        out_keys: tuple[str, ...] = ()
        in_keys: tuple[str, ...] = ()
        port_order: list[str] = []
        if inst["primitive"]:
            prim = GATE_PRIMITIVES.get(inst["type"])
            if prim is not None and not prim.bidirectional:
                out_keys = prim.output_ports
                in_keys = prim.input_ports
        elif inst["type"] in known_modules:
            child = doc["modules"][inst["type"]]
            port_order = [p["name"] for p in child["ports"]]
            out_keys = tuple(
                p["name"] for p in child["ports"]
                if p["direction"] in ("output", "inout"))
            in_keys = tuple(
                p["name"] for p in child["ports"]
                if p["direction"] in ("input", "inout"))
        for port, expr in inst["connections"].items():
            bases = _net_bases(expr)
            if unknown_child:
                external_boundary.update(bases)
                continue
            resolved = port
            if inst["connection_style"] == "positional" and port_order:
                # 位置连接：序号键 → 子模块端口声明序对位
                idx = int(port) - 1 if port.isdigit() else -1
                resolved = port_order[idx] if 0 <= idx < len(port_order) \
                    else None
                if resolved is None:
                    for b in bases:
                        external_boundary.add(b)
                    continue
            for b in bases:
                if resolved in out_keys:
                    add(True, b, src_inst)
                if resolved in in_keys:
                    add(False, b, src_inst)

    for a in body["assigns"]:
        for b in _net_bases(a["lhs"]):
            add(True, b, {"kind": "assign", "name": a["lhs"]})
        for b in _net_bases(a["rhs"]):
            add(False, b, {"kind": "assign", "name": a["lhs"]})
    for pname, direction in port_dirs.items():
        if direction in ("input", "inout"):
            add(True, pname, {"kind": "port", "name": pname})
        if direction in ("output", "inout"):
            add(False, pname, {"kind": "port", "name": pname})

    declared = {w["name"]: w["kind"] for w in body["wires"]}
    universe: list[str] = list(declared)
    seen = set(declared)
    for inst in body["instances"]:
        for expr in inst["connections"].values():
            for b in _net_bases(expr):
                if b not in seen:
                    seen.add(b)
                    universe.append(b)
    for a in body["assigns"]:
        for side in (a["lhs"], a["rhs"]):
            for b in _net_bases(side):
                if b not in seen:
                    seen.add(b)
                    universe.append(b)
    for pname in port_dirs:
        if pname not in seen:
            seen.add(pname)
            universe.append(pname)

    undriven: list[str] = []
    unloaded: list[str] = []
    for net in universe:
        if net in external_boundary:
            continue
        if net not in net_drivers \
                and declared.get(net) != "reg" \
                and port_dirs.get(net) not in ("input", "inout"):
            undriven.append(net)
        if net not in net_readers \
                and port_dirs.get(net) not in ("output", "inout"):
            unloaded.append(net)

    # 实例级边与树深度（实例→网→实例折叠成实例 DAG）
    edges: list[list[str]] = []
    edge_set: set[tuple[str, str]] = set()
    for net, drivers in net_drivers.items():
        for drv in drivers:
            if drv["kind"] != "instance":
                continue
            for rdr in net_readers.get(net, []):
                if rdr["kind"] != "instance" or rdr["name"] == drv["name"]:
                    continue
                pair = (drv["name"], rdr["name"])
                if pair not in edge_set:
                    edge_set.add(pair)
                    edges.append([drv["name"], rdr["name"]])
    succ: dict[str, list[str]] = {}
    for a, b in edges:
        succ.setdefault(a, []).append(b)
    inst_set = {i["name"] for i in body["instances"]}
    color: dict[str, int] = {}  # 0=未访 1=在栈 2=完成
    memo: dict[str, int] = {}   # 自本实例起的最长链实例数
    nxt: dict[str, str | None] = {}  # 最长链后继指针（关键路径回溯）
    cyclic_nodes: set[str] = set()

    # 迭代式 DFS（显式帧栈——门级网表缓冲链可达数千级，递归会撞
    # Python 递归上限；后继指针代替逐节点路径拷贝防 O(n²) 内存）。
    # 回边 u→v（v 在栈）时把栈上 v..u 整段标为环上实例（只标回边
    # 目标会漏标环内其余节点——首版实测 g1↔g2 只报 g1）。sorted=确定性。
    for root in sorted(inst_set):
        if color.get(root, 0) != 0:
            continue
        path: list[str] = [root]
        color[root] = 1
        frames: list[list[Any]] = [
            [root, iter(sorted(succ.get(root, []))), 0, None]]
        while frames:
            frame = frames[-1]
            u, it = frame[0], frame[1]
            descended = False
            for v in it:
                state = color.get(v, 0)
                if state == 1:
                    cyclic_nodes.update(path[path.index(v):])
                    continue
                if state == 0:
                    color[v] = 1
                    path.append(v)
                    frames.append([v, iter(sorted(succ.get(v, []))), 0, None])
                    descended = True
                    break
                if memo.get(v, 0) > frame[2]:
                    frame[2], frame[3] = memo[v], v
            if descended:
                continue
            frames.pop()
            path.pop()
            color[u] = 2
            memo[u] = frame[2] + 1
            nxt[u] = frame[3]
            if frames and memo[u] > frames[-1][2]:
                frames[-1][2], frames[-1][3] = memo[u], u

    depth_val: int | None = None
    critical: list[str] = []
    if not cyclic_nodes:
        start: str | None = None
        for name in sorted(inst_set):
            d = memo.get(name, 0)
            if depth_val is None or d > depth_val:
                depth_val, start = d, name
        cursor = start
        while cursor is not None:  # 无环时后继指针链必终止
            critical.append(cursor)
            cursor = nxt.get(cursor)
        if depth_val is None:  # 零实例模块：深度 0（None 专属环语义）
            depth_val = 0

    return {
        "module": module_name,
        "net_count": len(universe),
        "instance_count": len(body["instances"]),
        "net_drivers": net_drivers,
        "net_readers": net_readers,
        "instance_edges": edges,
        "orphan_nets": {
            "undriven": sorted(undriven),
            "unloaded": sorted(unloaded),
        },
        "behavioral_skipped": bool(body["warnings"]),
        "external_boundary_nets": sorted(external_boundary),
        "tree_depth": {
            "depth": depth_val,
            "critical_path": critical,
            "cyclic": bool(cyclic_nodes),
            "cyclic_instances": sorted(cyclic_nodes),
        },
    }


# ── 文档级入口 ──────────────────────────────────────────────────────────────


def parse_verilog(text: str) -> dict[str, Any]:
    """Verilog 网表文本 → 结构化文档（modules 五桶+顶层关系面）。

    返回::

        {
          "schema": f"verilog_netlist/{PARSER_SCHEMA_VERSION}",
          "schema_version": PARSER_SCHEMA_VERSION,   # deprecated 过渡并存
          "modules": {name: {ports, wires, assigns, instances,
                             parameters, localparams, defparams,
                             header_params_raw, directives, warnings,
                             ansi_ports, name}},
          "module_order": [注册序名表],
          "top_modules": [未被实例化的顶层候选],
          "instantiations": [{parent, child, instance}],
          "external_instance_types": [未定义实例类型],
          "directives": [编译器指令名],
          "warnings": [{line, name, note}],
          "stats": {n_modules, n_ports, n_wires, n_assigns,
                    n_instances, n_parameters, n_defparams,
                    n_warnings},
        }

    词法错误抛 :class:`VerilogParseError`；结构松散处 fail-soft
    （warnings 带行号如实披露后继续）。
    """
    parser = _VerilogParser(tokenize_verilog(text))
    parser.parse_document()
    instantiated_types = {e["child"] for e in parser.instantiations}
    # 外部单元类型=实例化了但文档未定义的模块类型；门级原语是 LRM
    # 内建（非外部单元库引用），不计入
    external = sorted(
        t for t in instantiated_types
        if t not in parser.modules and t not in GATE_PRIMITIVES)
    top_modules = [
        name for name in parser.module_order
        if name not in instantiated_types
    ]
    stats = {
        "n_modules": len(parser.modules),
        "n_ports": sum(len(m["ports"]) for m in parser.modules.values()),
        "n_wires": sum(len(m["wires"]) for m in parser.modules.values()),
        "n_assigns": sum(len(m["assigns"]) for m in parser.modules.values()),
        "n_instances": sum(
            len(m["instances"]) for m in parser.modules.values()),
        "n_parameters": sum(
            len(m["parameters"]) for m in parser.modules.values()),
        "n_defparams": sum(
            len(m["defparams"]) for m in parser.modules.values()),
        "n_warnings": len(parser.doc_warnings) + sum(
            len(m["warnings"]) for m in parser.modules.values()),
    }
    return {
        # 自描述键统一口径（R-22 schema 升位批）：``"<域>/<N.0>"`` 复合键
        # （域身份+版本一体；netlist_semantic_overlay 按前缀分派的同族形态）。
        "schema": f"verilog_netlist/{PARSER_SCHEMA_VERSION}",
        # 双层兼容（R-22 升位批）：本件旧键 ``schema_version`` 有仓内消费
        # 者（service/lvs_compare_service.py ``_normalize_verilog_graph_generic``
        # 的 detail 溯源串，#315 家法 grep 实证）——新旧键并存一版，
        # 旧键 deprecated（下一升位批移除），其余 6 件改名件旧键零消费
        # 者故单键直改。
        "schema_version": PARSER_SCHEMA_VERSION,
        "modules": parser.modules,
        "module_order": parser.module_order,
        "top_modules": top_modules,
        "instantiations": parser.instantiations,
        "external_instance_types": external,
        "directives": parser.directives,
        "warnings": parser.doc_warnings,
        "stats": stats,
    }
