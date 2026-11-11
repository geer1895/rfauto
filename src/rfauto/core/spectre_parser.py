"""Spectre 网表确定性解析内核（aurora_q 席位 Q-X79，2026-11-08）。

Cadence Spectre 原生网表语法（Virtuoso ADE 输出，``simulator lang=spectre``）
的只读结构化解析——CAD 扩展方向的模拟生态补全。词法与语义全部在 core 确
定性内核（铁律 7：**表达式只保留原文不求值**——数值只出自数值字面量+单位
后缀表换算，LLM/agent 永不产生物理数字）。服务包装见
:mod:`rfauto.service.spectre_service`（规则 4 JSON 进出），CLI 薄壳见
cli/domains/spectre.py（citi/gdsii/stil 同款域形态）。

**与 Q-X33 core/spice_netlist_parser 的重叠边界（开工调研实测，三选一判定
=b 部分覆盖）**：Q-X33 的 ``flavor="spectre"`` 路径已覆盖 lang 检测、
``//``/``*``/``/* */`` 注释、行尾 ``\\`` 续行、subckt/ends、model 语句、
命名分析块、``name (nodes) master`` 实例（master 名驱动 kind 推断）与表达
式原文保留，产出五维度统一 schema（elements/subckts/controls/models/
topology——MNA 拓扑与跨方言统一比对是其独有面，本模块不复制）。**未覆盖
面=本席增量**：

① 实例名首字母器件类型映射表（:data:`SPECTRE_LETTER_TYPES` 常量闭集+
   ``unknown`` 桶）；
② ``parameters`` 声明表（名→value_raw/value_si/is_expression——Q-X33 只
   把 parameters 收作 controls 原文参数）；
③ 选项块登记（``simulatorOptions options ...``/``deserializer`` 等——Q-X33
   对其判"无法归类"结构错误，调研探针实测）；
④ ``include``/``ahdl_include``/``#include`` 引用登记（Q-X33 无
   ahdl_include 面，探针实测判结构错误）；
⑤ 层次展开统计（subckt 实例计数+最大实例化深度+平铺叶计数，不物化）；
⑥ 查询三函数（器件库存/子电路树/参数引用点）。

需要 MNA 拓扑/统一五维度跨方言比对的消费方继续走 Q-X33；本模块是
Spectre 原生视图（schema 独立 ``spectre_netlist/1.0``，风格同族：fail-soft、
原文保留、不求值、schema 版本常量、表驱动闭集）。Q-X33 文件零改动。

覆盖面（fail-soft 口径——病态语句降级为 warning+跳过，**零致命异常**：
空文件/缺 lang 声明/未闭合 subckt 均 warning 不拒）：

- 词法：``//`` 行注释与 ``/* */`` 块注释双形态（块注释跨行**保行号**——
  逐行扫描，块内换行原位保留）+ 行首 ``*`` 旧式整行注释（Q-X33 家法）+
  行首 ``#`` 注释（``#include``/``#define``/``#if`` 等预处理指令除外——
  指令如实登记**不求值**）；行尾 ``\\`` 续行（语句行号=首物理行）；
  引号/反引号内注释符不剥离；token 化感知 ``"..."``/``'...'``/
  `````...````` 与 ``[...]``/``{...}``/值内函数括号（空白不切分）。
- 语句：``simulator lang=X``（``lang=spice`` 段整段如实登记进
  ``foreign_segments`` 不解析——容 spice 形态混写；切回 spectre 恢复）；
  ``parameters k=v ...``（顶层入全局表，subckt 体内入该 subckt 参数）；
  ``[inline] subckt NAME (nodes) k=v`` … ``ends [NAME]``（嵌套栈；名不配对/
  孤立 ends/文件尾未闭合 → warning）；``include``/``ahdl_include``；
  ``model NAME master k=v``；``name (nodes) master k=v`` 实例（节点表括号
  可省的 ``name n1..nN master k=v`` 形态同收——双形态如实，master=首个
  k=v 之前末位置 token）；
  ``name type k=v`` 命名语句（analysis/options/control 三类分派）；
  ``global``/``save``/``ic``/``nodeset``/``library``/``section`` 等控制语句；
  花括号块（``statistics {...}``/``if {...}``）整块登记计语句数不展开。
- 器件类型判定序：① master 命中本文件 subckt 定义 → ``subckt_instance``
  （显式声明优先于命名惯例——Spectre 允许任意名层次实例，双形态如实）；
  ② 首字母 ``X`` → ``subckt_instance``（引用未定义子电路 → warning，
  include 外部定义不展开）；③ 首字母映射表；④ ``unknown`` 桶。首字母原
  判定恒留档 ``letter_type``（与 device_type 不同时=显式引用覆盖）。名字
  大小写敏感（Spectre 口径；Q-X33 为不敏感匹配）。
- 参数值逐键类型分派（:func:`classify_spectre_value`）：数值+单位后缀 →
  :data:`SPECTRE_UNIT_SCALE` 表换算 SI 基值；表达式（反引号/单引号/花括
  号包裹，或含运算符的裸表达式）与裸标识符参数引用 → 原文保留
  ``is_expression=True``、``value_si=None``；双引号串 → ``is_string``；
  ``[...]`` → vector。
- 单位后缀：``meg``/``mil`` 前缀特判先于单字母（``2meg``=2e6 非 2m+eg）；
  单字母 T/G/k/m/u/n/p/f（大小写不敏感）可后接单位词闭集
  :data:`UNIT_WORDS`（``1pF``=1e-12、``100mA``=0.1）。**大小写语义冲突
  如实不猜**：Spectre 原生口径大小写敏感（``M``=1e6、``a``=1e-18），SPICE
  口径不敏感（``M``=1e-3，``a`` 非比例因子）——大写 ``M`` 打头（非
  meg/mil）与单独 ``a`` 后缀两口径数值矛盾 → ``value_si=None``+
  ``suffix_status="ambiguous"``+warning（铁律 7 数值不猜）；后缀不在表/
  单位词闭集 → ``"unrecognized"`` 同样不猜。

结构化输出（schema=spectre_netlist/1.0，全 JSON 原生类型）::

    {
      "schema": "spectre_netlist/1.0",
      "lang": "spectre"|"spice"|None,          # 首个 simulator 声明
      "lang_switches": [{"lang", "line_no"}],
      "parameters": {名: {"value_raw", "value_si", "kind", "is_expression",
                          "is_string", "suffix_status", "line_no"}},
      "subckts": {名: {"name", "nodes", "params": {键: 类型化值},
                       "instances": [实例...], "line_no", "end_line_no",
                       "closed", "scope", "inline"}},
      "top_instances": [{"name", "device_type", "letter_type", "master",
                         "subckt_ref", "model_ref", "nodes",
                         "params": {键: 类型化值}, "positional_args",
                         "scope", "line_no", "raw"}],
      "models": {名: {"master", "params": {键: 原文}, "line_no", "scope"}},
      "options_blocks": [{"name", "type", "class", "kv": {键: 原文},
                          "args", "nodes", "n_statements", "line_no",
                          "scope"}],   # class ∈ options/analysis/control/
                                       # preprocessor/brace_block
      "includes": [{"kind", "path", "line_no", "scope"}],
      "foreign_segments": [{"lang", "start_line", "end_line",
                            "raw_statements"}],
      "stats": {"per_device_type_counts", "n_subckts", "max_depth", ...},
      "warnings": [str],
    }

查询三函数（服务/CLI 上层消费）：:func:`spectre_device_inventory`（器件类
型×计数+参数键频次 top）、:func:`spectre_subckt_tree`（层次树+深度，环
引用截断标记）、:func:`spectre_param_refs`（参数名→定义处+消费处，词边
界文本匹配——作用域遮蔽不解析，不求值）。

已知限制（如实）：表达式不求值不代入；选项块只登记名+键值原文摘要；
花括号块/预处理条件不展开不求值（两支语句均按出现序解析）；层次统计按
语句级（``m=`` 并联倍乘不计）；值内函数括号含空白时须引号/反引号包裹
才保整 token。确定性（同输入同输出）、零 IO（纯文本进出）、零第三方依
赖。本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——stil_parser/vcd_parser 同款先例，新模块零金
快照漂移）。

AX-6 结构化 tier 诊断（aurora_r R-02 席位；:mod:`rfauto.core.
parser_diagnostics` 四层判据单源）：每个跳行/降级事件同笔落
``diagnostics`` 新增键——``{tier, parser, reason, line, snippet}``
（snippet=语句原文，#331 不美化；diagnostics 按事件发生序，不与
``warnings`` 列表位序对齐——缺 lang 声明类 insert(0) 警告对应诊断在
事件序末尾）。定档口径：缺名/缺路径/无法归类/unrecognized 落空=
unparsed；lang=spice 外语段/master 数值形态疑似 SPICE 行=
unsupported-tier1；预处理条件不求值/外部子电路引用/层次环与超深截断=
unsupported-tier2；引号未闭合按行尾收尾/括号未闭合降级收口/后缀语义
矛盾 value_si=None/EOF 强制收口/缺 lang 按假设语法解析=
unsupported-tier3。既有 ``warnings`` 文案逐字节零变化（纯附加键）。
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

from rfauto.core.parser_diagnostics import (
    TIER_UNPARSED,
    TIER_UNSUPPORTED_1,
    TIER_UNSUPPORTED_2,
    TIER_UNSUPPORTED_3,
    line_snippet,
    make_parse_diagnostic,
)

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: 层次递归深度守卫（实例化链超深截断并标记——病态文件不触 Python 递归上限；
#: fail-soft 零致命口径）。
MAX_HIERARCHY_DEPTH = 256
#: 子电路树节点预算（菱形 DAG 树化指数膨胀守卫——超限节点截断并标记）。
MAX_TREE_NODES = 20000

#: 实例名首字母 → 器件类型（Spectre/SPICE 命名惯例常量闭集；未命中=unknown 桶）。
SPECTRE_LETTER_TYPES: dict[str, str] = {
    "M": "mosfet",
    "Q": "bjt",
    "D": "diode",
    "R": "resistor",
    "C": "capacitor",
    "L": "inductor",
    "I": "isource",
    "V": "vsource",
    "E": "vcvs",
    "F": "cccs",
    "G": "vccs",
    "H": "ccvs",
    "K": "mutual_inductor",
    "T": "transmission_line",
    "J": "jfet",
    "S": "switch",
    "X": "subckt_instance",
}
#: 首字母未命中映射表的器件类型桶。
DEVICE_TYPE_UNKNOWN = "unknown"
#: 层次实例器件类型（X 惯例或 master 命中本文件 subckt 定义）。
DEVICE_TYPE_SUBCKT = "subckt_instance"

#: 单位后缀 → SI 倍率（格式常数非物理数值；meg/mil 双字母前缀特判先于单字母）。
SPECTRE_UNIT_SCALE: dict[str, float] = {
    "meg": 1e6,
    "mil": 25.4e-6,
    "t": 1e12,
    "g": 1e9,
    "k": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}
_SINGLE_LETTER_SCALE: dict[str, float] = {
    k: v for k, v in SPECTRE_UNIT_SCALE.items() if len(k) == 1
}

#: 比例因子后可跟的单位词闭集（小写比对；纯标注不改值：``1pF``/``100mA``/``1.8V``）。
UNIT_WORDS = frozenset({
    "v", "volt", "volts", "a", "amp", "amps", "ohm", "ohms", "f", "farad",
    "h", "henry", "hz", "s", "sec", "w", "watt", "db", "deg",
})

#: Spectre 分析类型闭集（``name type k=v`` 命名语句 type 位 → class=analysis）。
SPECTRE_ANALYSIS_TYPES = frozenset({
    "ac", "dc", "tran", "noise", "sp", "xf", "stb", "pz", "dcmatch", "sens",
    "envlp", "pss", "pac", "pnoise", "pxf", "psp", "qpss", "qpac", "qpnoise",
    "qpxf", "hb", "hbac", "hbnoise", "hbsp", "sweep", "montecarlo",
})
#: 命名控制语句 type 位闭集（class=control；options 另归 class=options）。
SPECTRE_CONTROL_TYPES = frozenset({
    "info", "alter", "altergroup", "check", "checklimit", "set", "shell",
    "assert",
})
#: 选项块头闭集（小写比对；``name options ...`` type 位形态另判）。
OPTIONS_BLOCK_HEADS = frozenset({
    "simulatoroptions", "options", "saveoptions", "deserializer", "analysis",
    "netlistoptions",
})
#: 命名语句保留类型字全集（实例 master 位命中=分析/控制语句，非器件）。
_NAMED_STATEMENT_TYPES = SPECTRE_ANALYSIS_TYPES | SPECTRE_CONTROL_TYPES | {"options"}
#: 首词即语义的控制语句头闭集（小写比对；class=control 整句登记）。
CONTROL_HEADS = frozenset({
    "global", "save", "ic", "nodeset", "library", "endlibrary", "section",
    "endsection", "export", "paramset",
})
#: 引用语句头 → includes kind（如实登记不展开）。
_INCLUDE_HEADS: dict[str, str] = {
    "include": "include",
    "ahdl_include": "ahdl_include",
}

_NUMBER_RE = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)([A-Za-z]*)$")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.$]*$")
_NAME_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: 无括号实例形态的实例名守卫（``c[33]`` 总线位后缀容忍；排除含 ``=`` 键形态）。
_INSTANCE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:<\d+(?::\d+)?>|\[\d+\])?$")
_EXPR_OPERATOR_RE = re.compile(r"[-+*/^()<>=!&|?:%]")
_PREPROC_RE = re.compile(
    r"^#\s*(include|define|undef|ifdef|ifndef|if|elif|else|endif)\b", re.IGNORECASE)
_LANG_RE = re.compile(r"\blang\s*=\s*([A-Za-z_]+)", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# 数值/值类型分派
# --------------------------------------------------------------------------- #


def _finite_or_none(value: float) -> float | None:
    """非有限值（溢出 inf/nan）→ None（JSON 原生类型守卫；不造 Infinity）。"""
    return value if math.isfinite(value) else None


def parse_spectre_number(token: str) -> tuple[float | None, str] | None:
    """数值令牌 → ``(value_si, suffix_status)``；非数值形态返回 None。

    suffix_status 闭集：``none``（无后缀）/``scaled``（比例因子已换算，可后
    接单位词）/``unit_word``（仅单位词，值不变）/``ambiguous``（Spectre 原
    生与 SPICE 口径数值矛盾——大写 ``M`` 打头非 meg/mil、单独 ``a``——
    value_si=None 不猜）/``unrecognized``（后缀不在表与单位词闭集——
    value_si=None 不猜）。0.0 是合法值，缺失哨兵恒 None（#117 家法）。
    """
    m = _NUMBER_RE.match(token.strip())
    if not m:
        return None
    body, suffix = m.group(1), m.group(2)
    if not suffix:
        return _finite_or_none(float(body)), "none"
    low = suffix.lower()
    if low.startswith("meg"):
        scale, rest, status = SPECTRE_UNIT_SCALE["meg"], suffix[3:], "scaled"
    elif low.startswith("mil"):
        scale, rest, status = SPECTRE_UNIT_SCALE["mil"], suffix[3:], "scaled"
    elif suffix[0] == "M" or suffix == "a":
        return None, "ambiguous"
    elif low[0] in _SINGLE_LETTER_SCALE:
        scale, rest, status = _SINGLE_LETTER_SCALE[low[0]], suffix[1:], "scaled"
    else:
        scale, rest, status = 1.0, suffix, "unit_word"
    if rest and rest.lower() not in UNIT_WORDS:
        return None, "unrecognized"
    # 十进制精确换算（Decimal(str(倍率)) 为精确十进制——``180n``→1.8e-07 逐位，
    # 不落 float 乘法舍入尾巴 1.8000000000000002e-07）
    return _finite_or_none(float(Decimal(body) * Decimal(str(scale)))), status


def classify_spectre_value(raw: str) -> dict[str, Any]:
    """参数值原文 → 类型化值 dict（逐键类型分派单源；不求值）。

    返回 ``{"value_raw", "value_si", "kind", "is_expression", "is_string",
    "suffix_status"}``；kind 闭集 number/expression/reference/string/
    vector/raw。表达式与参数引用 value_si 恒 None（铁律 7：原文保留不代
    入）；suffix_status 只对 number 有值。
    """
    text = raw.strip()
    out: dict[str, Any] = {
        "value_raw": text,
        "value_si": None,
        "kind": "raw",
        "is_expression": False,
        "is_string": False,
        "suffix_status": None,
    }
    if not text:
        return out
    wrapped = len(text) >= 2 and (
        (text[0] == "`" and text[-1] == "`")
        or (text[0] == "'" and text[-1] == "'")
        or (text[0] == "{" and text[-1] == "}")
    )
    if wrapped:
        out["kind"] = "expression"
        out["is_expression"] = True
        return out
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        out["kind"] = "string"
        out["is_string"] = True
        return out
    if text[0] == "[" and text[-1] == "]":
        out["kind"] = "vector"
        return out
    number = parse_spectre_number(text)
    if number is not None:
        out["kind"] = "number"
        out["value_si"], out["suffix_status"] = number
        return out
    if _IDENT_RE.match(text):
        out["kind"] = "reference"
        out["is_expression"] = True
        return out
    if _EXPR_OPERATOR_RE.search(text):
        out["kind"] = "expression"
        out["is_expression"] = True
    return out


# --------------------------------------------------------------------------- #
# 词法：注释/续行 → 逻辑语句；语句 → token
# --------------------------------------------------------------------------- #


def _strip_line(raw: str, in_block: bool) -> tuple[str, bool]:
    """单物理行剥注释（块注释状态跨行携带；引号/反引号内注释符不剥）。

    返回 ``(保留文本, 行尾块注释状态)``。引号不跨行（行尾复位——fail-soft）。
    """
    out: list[str] = []
    i, n = 0, len(raw)
    quote = ""
    while i < n:
        if in_block:
            end = raw.find("*/", i)
            if end == -1:
                return "".join(out), True
            in_block = False
            i = end + 2
            out.append(" ")
            continue
        ch = raw[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if raw.startswith("//", i):
            break
        if raw.startswith("/*", i):
            in_block = True
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out), in_block


def _logical_statements(text: str, warnings: list[str],
                        diags: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """原始文本 → ``[(line_no, 语句文本), ...]``（注释剥离+续行拼接）。

    行首 ``*``（块注释外）=旧式整行注释；行首 ``#`` 非预处理指令=注释；
    行尾 ``\\`` 续行并入下一非空行（语句行号=首物理行）。
    """
    statements: list[tuple[int, str]] = []
    in_block = False
    block_start = 0
    buf = ""
    buf_line = 0
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not in_block:
            head = raw.lstrip()
            if head.startswith("*"):
                continue
            if head.startswith("#") and not _PREPROC_RE.match(head):
                continue
        was_block = in_block
        kept, in_block = _strip_line(raw, in_block)
        if in_block and not was_block:
            block_start = line_no
        piece = kept.strip()
        if not piece:
            continue
        if not buf:
            buf_line = line_no
        if piece.endswith("\\"):
            buf = (buf + " " + piece[:-1].rstrip()).strip()
            continue
        statements.append((buf_line, (buf + " " + piece).strip()))
        buf = ""
    if buf:
        statements.append((buf_line, buf))
        warnings.append(f"第 {buf_line} 行续行符 \\ 后至文件尾无后续行——按已收文本收尾")
        diags.append(make_parse_diagnostic(
            TIER_UNSUPPORTED_3, "continuation_backslash_at_eof", buf_line,
            None, parser="spectre"))
    if in_block:
        warnings.append(f"第 {block_start} 行块注释 /* 未闭合（至文件尾）——其后文本按注释丢弃")
        diags.append(make_parse_diagnostic(
            TIER_UNSUPPORTED_3, "block_comment_unclosed", block_start,
            None, parser="spectre"))
    return statements


def _tokenize(stmt: str) -> tuple[list[str], bool]:
    """语句 → token 列表（引号/反引号/方括号/花括号/值内函数括号内空白不切
    分；节点表括号 ``(``/``)`` 独立成 token）。返回 ``(tokens, 引号未闭合)``。
    """
    tokens: list[str] = []
    buf: list[str] = []
    quote = ""
    group = 0
    for ch in stmt:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch
            buf.append(ch)
            continue
        if ch in "[{":
            group += 1
            buf.append(ch)
            continue
        if ch in "]}":
            group = max(0, group - 1)
            buf.append(ch)
            continue
        if ch == "(":
            if group or (buf and "=" in "".join(buf)):
                group += 1
                buf.append(ch)
                continue
            if buf:
                tokens.append("".join(buf))
                buf = []
            tokens.append("(")
            continue
        if ch == ")":
            if group:
                group -= 1
                buf.append(ch)
                continue
            if buf:
                tokens.append("".join(buf))
                buf = []
            tokens.append(")")
            continue
        if ch.isspace() and not group:
            if buf:
                tokens.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens, bool(quote)


def _brace_balance(stmt: str) -> int:
    """语句花括号净开数（引号/反引号内不计）。"""
    balance = 0
    quote = ""
    for ch in stmt:
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch
        elif ch == "{":
            balance += 1
        elif ch == "}":
            balance -= 1
    return balance


def _merge_kv_tokens(tokens: list[str]) -> list[str]:
    """``k = v``/``k= v``/``k =v`` 分写形态合并为 ``k=v`` 单 token。"""
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "=" and merged and i + 1 < len(tokens):
            merged[-1] = merged[-1] + "=" + tokens[i + 1]
            i += 2
            continue
        if tok.endswith("=") and "=" not in tok[:-1] and i + 1 < len(tokens):
            merged.append(tok + tokens[i + 1])
            i += 2
            continue
        if tok.startswith("=") and len(tok) > 1 and merged and "=" not in merged[-1]:
            merged[-1] = merged[-1] + tok
            i += 1
            continue
        merged.append(tok)
        i += 1
    return merged


def _is_kv(token: str) -> bool:
    """token 是否 ``key=value`` 形态（值可含 ``=``；纯 ``=``/``=v`` 非首键形态排除）。"""
    head = token.partition("=")[0]
    return bool(head) and token != head and _IDENT_RE.match(head) is not None


def _kv_pairs(tokens: list[str]) -> tuple[dict[str, str], list[str]]:
    """token 段 → ``({键: 值原文}, [非键值位置 token])``（后列同键覆盖）。"""
    kv: dict[str, str] = {}
    positional: list[str] = []
    for tok in _merge_kv_tokens(tokens):
        if "=" in tok and not tok.startswith(("=", "\"", "'", "`")):
            key, _, value = tok.partition("=")
            key = key.strip()
            if key:
                kv[key] = value.strip()
                continue
        positional.append(tok)
    return kv, positional


def _extract_nodes(tokens: list[str]) -> tuple[list[str], list[str], bool]:
    """``( n1 n2 ) rest...`` → ``(nodes, rest, 括号闭合)``；无括号返回
    ``([], tokens, True)``。"""
    if not tokens or tokens[0] != "(":
        return [], list(tokens), True
    try:
        close = tokens.index(")", 1)
    except ValueError:
        return [t for t in tokens[1:] if t != ","], [], False
    nodes = [t.strip(",") for t in tokens[1:close] if t.strip(",")]
    return nodes, tokens[close + 1:], True


# --------------------------------------------------------------------------- #
# 主解析状态机
# --------------------------------------------------------------------------- #


class _ParseState:
    """单遍语句状态机（subckt 嵌套栈+lang 模式+花括号块捕获）。"""

    def __init__(self) -> None:
        self.lang: str | None = None
        self.mode = "spectre"
        self.lang_switches: list[dict[str, Any]] = []
        self.parameters: dict[str, dict[str, Any]] = {}
        self.subckts: dict[str, dict[str, Any]] = {}
        self.top_instances: list[dict[str, Any]] = []
        self.models: dict[str, dict[str, Any]] = {}
        self.options_blocks: list[dict[str, Any]] = []
        self.includes: list[dict[str, Any]] = []
        self.foreign_segments: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.diags: list[dict[str, Any]] = []
        self.stack: list[str] = []
        self.max_definition_nesting = 0
        self.brace_block: dict[str, Any] | None = None
        self.brace_depth = 0
        self.saw_preproc_conditional = False

    # ── 公共工具 ──
    def scope(self) -> list[str]:
        return list(self.stack)

    def warn(self, line_no: int, msg: str, *, tier: str = TIER_UNPARSED,
             reason: str = "statement_skipped",
             snippet: str | None = None) -> None:
        """既定文案 warning + 同笔 AX-6 tier 诊断（warnings 文案零变化）。"""
        self.warnings.append(f"第 {line_no} 行 {msg}")
        self.diag(tier=tier, reason=reason, line_no=line_no, snippet=snippet)

    def diag(self, *, tier: str, reason: str, line_no: int | None = None,
             snippet: str | None = None) -> None:
        """仅诊断入列（无行锚的收尾/统计类事件同口径）。"""
        self.diags.append(make_parse_diagnostic(
            tier, reason, line_no,
            None if snippet is None else line_snippet(snippet),
            parser="spectre"))

    def typed_params(self, kv: dict[str, str], line_no: int, owner: str) -> dict[str, dict[str, Any]]:
        params: dict[str, dict[str, Any]] = {}
        for key, raw in kv.items():
            typed = classify_spectre_value(raw)
            status = typed["suffix_status"]
            if status == "ambiguous":
                self.warn(line_no, (
                    f"{owner} 参数 {key}={raw} 单位后缀大小写语义冲突（Spectre 原生 M=1e6/"
                    "a=1e-18 vs SPICE M=1e-3）——value_si=None 不猜，原文保留"),
                    tier=TIER_UNSUPPORTED_3, reason="suffix_ambiguous_value_si_none",
                    snippet=None)
            elif status == "unrecognized":
                self.warn(line_no, (
                    f"{owner} 参数 {key}={raw} 单位后缀不在换算表/单位词闭集——value_si=None"
                    " 不猜，原文保留"),
                    tier=TIER_UNSUPPORTED_3,
                    reason="suffix_unrecognized_value_si_none",
                    snippet=None)
            params[key] = typed
        return params

    # ── 分派 ──
    def feed(self, line_no: int, stmt: str) -> None:
        if self.brace_block is not None:
            stripped = stmt.strip()
            if stripped.strip("{}").strip():  # 纯花括号闭合行不计语句数
                self.brace_block["n_statements"] += 1
            self.brace_depth += _brace_balance(stmt)
            if self.brace_depth <= 0:
                self.brace_block = None
                self.brace_depth = 0
            return
        tokens, open_quote = _tokenize(stmt)
        if not tokens:
            return
        if open_quote:
            self.warn(line_no, f"引号未闭合（按行尾收尾 token 化）: {stmt!r}",
                      tier=TIER_UNSUPPORTED_3, reason="unclosed_quote_line_folded",
                      snippet=stmt)
        head = tokens[0]
        low = head.lower()
        if low == "simulator":
            self.on_simulator(stmt, line_no)
            return
        if self.mode != "spectre":
            seg = self.foreign_segments[-1]
            seg["end_line"] = line_no
            seg["raw_statements"].append(stmt)
            return
        if head.startswith("#"):
            self.on_preprocessor(stmt, line_no)
            return
        balance = _brace_balance(stmt)
        if balance > 0:
            self.on_brace_block_start(tokens, line_no, balance)
            return
        if low in ("parameters", "parameter"):
            self.on_parameters(tokens[1:], line_no, stmt=stmt)
        elif low == "subckt" or (low == "inline" and len(tokens) > 1 and tokens[1].lower() == "subckt"):
            self.on_subckt(tokens, line_no, inline=(low == "inline"), stmt=stmt)
        elif low == "ends":
            self.on_ends(tokens, line_no, stmt=stmt)
        elif low in _INCLUDE_HEADS:
            self.on_include(_INCLUDE_HEADS[low], tokens[1:], line_no, stmt=stmt)
        elif low == "model":
            self.on_model(tokens, line_no, stmt=stmt)
        elif low in CONTROL_HEADS:
            self.on_named(tokens, line_no, block_class="control", with_type=False)
        elif len(tokens) >= 2 and tokens[1] == "(":
            nodes, rest, closed = _extract_nodes(tokens[1:])
            if not closed:
                self.warn(line_no, f"实例 {head} 节点表括号未闭合: {stmt!r}",
                          tier=TIER_UNSUPPORTED_3,
                          reason="instance_node_list_unclosed", snippet=stmt)
            self.on_instance(head, nodes, rest, stmt, line_no)
        elif len(tokens) >= 2 and _NAME_TOKEN_RE.match(tokens[1]) and self.named_class(head, tokens[1]):
            self.on_named(tokens, line_no, block_class=self.named_class(head, tokens[1]), with_type=True)
        elif low in OPTIONS_BLOCK_HEADS:
            self.on_named(tokens, line_no, block_class="options", with_type=False)
        elif not self.on_parenless_instance(tokens, stmt, line_no):
            self.warn(line_no, f"Spectre 语句无法归类（fail-soft 跳过）: {stmt!r}",
                      tier=TIER_UNPARSED, reason="statement_unclassifiable",
                      snippet=stmt)

    def on_parenless_instance(self, tokens: list[str], stmt: str, line_no: int) -> bool:
        """节点表括号可省形态 ``name n1 .. nN master k=v``（Spectre 语法括号可
        选；master=首个 k=v 之前的末位置 token）。不成形返回 False。"""
        head = tokens[0]
        if not _INSTANCE_NAME_RE.match(head):
            return False
        merged = _merge_kv_tokens(tokens[1:])
        split = next((i for i, tok in enumerate(merged) if _is_kv(tok)), len(merged))
        positional = merged[:split]
        if not positional:
            return False
        self.on_instance(head, positional[:-1], [positional[-1], *merged[split:]], stmt, line_no)
        return True

    @staticmethod
    def named_class(head: str, type_token: str) -> str | None:
        t = type_token.lower()
        if t == "options" or head.lower() in OPTIONS_BLOCK_HEADS:
            return "options"
        if t in SPECTRE_ANALYSIS_TYPES:
            return "analysis"
        if t in SPECTRE_CONTROL_TYPES:
            return "control"
        return None

    # ── 语句处理 ──
    def on_simulator(self, stmt: str, line_no: int) -> None:
        m = _LANG_RE.search(stmt)
        if not m:
            self.warn(line_no, f"simulator 语句缺 lang=…（忽略）: {stmt!r}",
                      tier=TIER_UNPARSED, reason="simulator_missing_lang",
                      snippet=stmt)
            return
        lang = m.group(1).lower()
        self.lang_switches.append({"lang": lang, "line_no": line_no})
        if self.lang is None:
            self.lang = lang
        if lang == "spectre":
            self.mode = "spectre"
            return
        if self.mode != lang:
            self.foreign_segments.append({
                "lang": lang, "start_line": line_no, "end_line": line_no,
                "raw_statements": [],
            })
        self.mode = lang
        self.warn(line_no, (
            f"simulator lang={lang} 段——非 Spectre 语法整段如实登记 foreign_segments 不解析"
            "（容 spice 形态混写；SPICE 段请走 Q-X33 spice 解析器）"),
            tier=TIER_UNSUPPORTED_1, reason="foreign_language_segment",
            snippet=stmt)

    def on_preprocessor(self, stmt: str, line_no: int) -> None:
        body = stmt[1:].strip()
        directive = body.split(None, 1)[0].lower() if body else ""
        rest = body[len(directive):].strip()
        if directive == "include":
            self.includes.append({
                "kind": "cpp_include", "path": rest.strip("\"'<>"),
                "line_no": line_no, "scope": self.scope(),
            })
            return
        if directive in ("if", "ifdef", "ifndef", "elif", "else") and not self.saw_preproc_conditional:
            self.saw_preproc_conditional = True
            self.warn(line_no, "预处理条件指令不求值——各分支语句均按出现序解析（如实）",
                      tier=TIER_UNSUPPORTED_2,
                      reason="preprocessor_conditional_not_evaluated",
                      snippet=stmt)
        self.options_blocks.append({
            "name": "#" + directive, "type": None, "class": "preprocessor",
            "kv": {}, "args": rest.split(), "nodes": [], "n_statements": 1,
            "line_no": line_no, "scope": self.scope(),
        })

    def on_brace_block_start(self, tokens: list[str], line_no: int, balance: int) -> None:
        block = {
            "name": tokens[0], "type": None, "class": "brace_block",
            "kv": {}, "args": [t for t in tokens[1:] if t not in ("{", "}")],
            "nodes": [], "n_statements": 1, "line_no": line_no, "scope": self.scope(),
        }
        self.options_blocks.append(block)
        self.brace_block = block
        self.brace_depth = balance

    def on_parameters(self, tokens: list[str], line_no: int,
                      stmt: str = "") -> None:
        kv, positional = _kv_pairs(tokens)
        if positional:
            self.warn(line_no, f"parameters 语句含非 k=v 片段（跳过）: {positional}",
                      tier=TIER_UNPARSED, reason="non_kv_fragments_skipped",
                      snippet=stmt)
        if not kv:
            self.warn(line_no, "parameters 语句无 k=v 声明",
                      tier=TIER_UNPARSED, reason="no_kv_declarations",
                      snippet=stmt)
            return
        typed = self.typed_params(kv, line_no, "parameters")
        if self.stack:
            self.subckts[self.stack[-1]]["params"].update(typed)
            return
        for name, value in typed.items():
            if name in self.parameters:
                self.warn(line_no, f"参数 {name} 重复声明（后列覆盖，前次第 {self.parameters[name]['line_no']} 行）")
            self.parameters[name] = {**value, "line_no": line_no}

    def on_subckt(self, tokens: list[str], line_no: int, *, inline: bool,
                  stmt: str = "") -> None:
        idx = 2 if inline else 1
        if len(tokens) <= idx:
            self.warn(line_no, "subckt 缺子电路名（跳过）",
                      tier=TIER_UNPARSED, reason="subckt_missing_name",
                      snippet=stmt)
            return
        name = tokens[idx]
        rest = tokens[idx + 1:]
        if rest and rest[0] == "(":
            nodes, after, closed = _extract_nodes(rest)
            if not closed:
                self.warn(line_no, f"subckt {name} 端口表括号未闭合",
                          tier=TIER_UNSUPPORTED_3,
                          reason="subckt_port_list_unclosed", snippet=stmt)
            kv, positional = _kv_pairs(after)
        else:
            kv, positional = _kv_pairs(rest)
            nodes, positional = positional, []
        if positional:
            self.warn(line_no, f"subckt {name} 端口表后含非 k=v 片段（跳过）: {positional}",
                      tier=TIER_UNPARSED, reason="non_kv_fragments_skipped",
                      snippet=stmt)
        if name in self.subckts:
            self.warn(line_no, f"subckt {name} 重复定义（后列覆盖，前次第 {self.subckts[name]['line_no']} 行）")
        self.subckts[name] = {
            "name": name,
            "nodes": nodes,
            "params": self.typed_params(kv, line_no, f"subckt {name}"),
            "instances": [],
            "line_no": line_no,
            "end_line_no": None,
            "closed": False,
            "scope": self.scope(),
            "inline": inline,
        }
        self.stack.append(name)
        self.max_definition_nesting = max(self.max_definition_nesting, len(self.stack))

    def on_ends(self, tokens: list[str], line_no: int,
                stmt: str = "") -> None:
        if not self.stack:
            self.warn(line_no, "ends 无匹配的 subckt（当前无打开的子电路，跳过）",
                      tier=TIER_UNPARSED, reason="ends_without_subckt",
                      snippet=stmt)
            return
        name = self.stack.pop()
        if len(tokens) > 1 and tokens[1] != name:
            self.warn(line_no, f"ends {tokens[1]} 与当前打开的 subckt {name} 名不配对（按栈顶 {name} 关闭）",
                      tier=TIER_UNSUPPORTED_3,
                      reason="ends_name_mismatch_closed_by_stack",
                      snippet=stmt)
        entry = self.subckts[name]
        entry["end_line_no"] = line_no
        entry["closed"] = True

    def on_include(self, kind: str, tokens: list[str], line_no: int,
                   stmt: str = "") -> None:
        if not tokens:
            self.warn(line_no, f"{kind} 缺文件路径（跳过）",
                      tier=TIER_UNPARSED, reason="include_missing_path",
                      snippet=stmt)
            return
        kv, positional = _kv_pairs(tokens[1:])
        if positional:
            self.warn(line_no, f"{kind} 路径后含非 k=v 片段（跳过）: {positional}",
                      tier=TIER_UNPARSED, reason="non_kv_fragments_skipped",
                      snippet=stmt)
        entry: dict[str, Any] = {
            "kind": kind, "path": tokens[0].strip("\"'"),
            "line_no": line_no, "scope": self.scope(),
        }
        if kv:
            entry["kv"] = kv
        self.includes.append(entry)

    def on_model(self, tokens: list[str], line_no: int,
                 stmt: str = "") -> None:
        if len(tokens) < 3:
            self.warn(line_no, f"model 令牌不足（需 model name master [k=v]）: {' '.join(tokens)!r}",
                      tier=TIER_UNPARSED, reason="model_insufficient_tokens",
                      snippet=stmt)
            return
        name, master = tokens[1], tokens[2]
        kv, _positional = _kv_pairs(tokens[3:])
        if name in self.models:
            self.warn(line_no, f"model {name} 重复定义（后列覆盖）")
        self.models[name] = {"master": master, "params": kv, "line_no": line_no, "scope": self.scope()}

    def on_instance(self, name: str, nodes: list[str], rest: list[str],
                    stmt: str, line_no: int) -> None:
        master: str | None = None
        if rest and "=" not in rest[0]:
            master, rest = rest[0], rest[1:]
        else:
            self.warn(line_no, f"实例 {name} 缺 master（器件/模型/子电路名）: {stmt!r}",
                      tier=TIER_UNSUPPORTED_3,
                      reason="instance_missing_master_degraded", snippet=stmt)
        kv, positional = _kv_pairs(rest)
        if master is not None and master.lower() in _NAMED_STATEMENT_TYPES:
            # 带节点表的分析语句（``noise1 (out 0) noise ...``/``xf1 (o 0) xf``）
            # ——master 位为保留分析/控制类型字，归选项块不计器件实例
            self.options_blocks.append({
                "name": name, "type": master, "class": self.named_class(name, master),
                "kv": kv, "args": positional, "nodes": nodes, "n_statements": 1,
                "line_no": line_no, "scope": self.scope(),
            })
            return
        if master is not None and parse_spectre_number(master) is not None:
            self.warn(line_no, (
                f"实例 {name} 的 master {master!r} 为数值形态——疑似 SPICE 形态元件行"
                "（容 spice 形态混写如实；按 Spectre 语法登记，SPICE 段请走 Q-X33）"),
                tier=TIER_UNSUPPORTED_1, reason="spice_form_line_absorbed",
                snippet=stmt)
        entry: dict[str, Any] = {
            "name": name,
            "device_type": None,
            "letter_type": None,
            "master": master,
            "subckt_ref": None,
            "model_ref": None,
            "nodes": nodes,
            "params": self.typed_params(kv, line_no, f"实例 {name}"),
            "positional_args": positional,
            "scope": self.scope(),
            "line_no": line_no,
            "raw": stmt,
        }
        if self.stack:
            self.subckts[self.stack[-1]]["instances"].append(entry)
        else:
            self.top_instances.append(entry)

    def on_named(self, tokens: list[str], line_no: int, *, block_class: str, with_type: bool) -> None:
        type_token = tokens[1] if with_type else None
        kv, positional = _kv_pairs(tokens[2:] if with_type else tokens[1:])
        self.options_blocks.append({
            "name": tokens[0], "type": type_token, "class": block_class,
            "kv": kv, "args": positional, "nodes": [], "n_statements": 1,
            "line_no": line_no, "scope": self.scope(),
        })

    # ── 收尾 ──
    def finish(self) -> None:
        for name in reversed(self.stack):
            self.warnings.append(
                f"文件结束仍有未闭合的 subckt {name}（第 {self.subckts[name]['line_no']} 行打开，缺 ends）"
                "——fail-soft 收至文件尾")
            self.diag(tier=TIER_UNSUPPORTED_3, reason="subckt_unclosed_at_eof",
                      line_no=self.subckts[name]["line_no"])
        self.stack.clear()
        if self.brace_block is not None:
            self.warn(self.brace_block["line_no"], f"花括号块 {self.brace_block['name']} 未闭合（至文件尾）",
                      tier=TIER_UNSUPPORTED_3, reason="brace_block_unclosed")
        self.resolve_device_types()

    def all_instances(self) -> list[dict[str, Any]]:
        out = list(self.top_instances)
        for sub in self.subckts.values():
            out.extend(sub["instances"])
        return out

    def resolve_device_types(self) -> None:
        """器件类型后置判定（subckt 定义可前向引用——全文收齐后统一解析）。"""
        for inst in self.all_instances():
            first = inst["name"][:1].upper()
            letter_type = SPECTRE_LETTER_TYPES.get(first, DEVICE_TYPE_UNKNOWN)
            inst["letter_type"] = letter_type
            master = inst["master"]
            if master is not None and master in self.subckts:
                inst["device_type"] = DEVICE_TYPE_SUBCKT
                inst["subckt_ref"] = master
            elif first == "X":
                inst["device_type"] = DEVICE_TYPE_SUBCKT
                inst["subckt_ref"] = master
                if master is not None:
                    self.warn(inst["line_no"], (
                        f"层次实例 {inst['name']} 引用本文件未定义的子电路 {master!r}"
                        "（include 外部定义不展开）"),
                        tier=TIER_UNSUPPORTED_2,
                        reason="subckt_reference_undefined_external",
                        snippet=inst.get("raw"))
            else:
                inst["device_type"] = letter_type
            if master is not None and master in self.models:
                inst["model_ref"] = master


# --------------------------------------------------------------------------- #
# 层次统计
# --------------------------------------------------------------------------- #


def _subckt_children(subckts: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """subckt → 体内层次实例引用的子电路名（去重保序；含未定义引用）。"""
    children: dict[str, list[str]] = {}
    for name, sub in subckts.items():
        kids: list[str] = []
        for inst in sub["instances"]:
            ref = inst.get("subckt_ref")
            if ref and ref not in kids:
                kids.append(ref)
        children[name] = kids
    return children


def _hierarchy_stats(top_instances: list[dict[str, Any]],
                     subckts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """实例化层次深度+平铺叶计数（不物化；记忆化 DFS 线性时间；环引用截断并
    标记；递归深度守卫 :data:`MAX_HIERARCHY_DEPTH` 截断并标记）。

    深度口径：顶层层次实例引用的子电路=第 1 层，其体内再引用=第 2 层…；
    未定义（外部）子电路计 1 层不透明。平铺叶计数=按层次展开后的原语实例
    数（递归求和不物化；外部子电路计 1 个不透明叶；顶层可达环/截断 → None
    如实）。
    """
    children = _subckt_children(subckts)
    flags = {"has_cycle": False, "truncated": False}
    depth_memo: dict[str, int] = {}
    leaf_memo: dict[str, int | None] = {}
    depth_stack: set[str] = set()
    leaf_stack: set[str] = set()

    def level(name: str) -> int:
        if name not in subckts:
            return 1
        if name in depth_memo:
            return depth_memo[name]
        if name in depth_stack:
            flags["has_cycle"] = True
            return 0
        if len(depth_stack) >= MAX_HIERARCHY_DEPTH:
            flags["truncated"] = True
            return 0
        depth_stack.add(name)
        best = 0
        for kid in children.get(name) or []:
            best = max(best, level(kid))
        depth_stack.discard(name)
        depth_memo[name] = 1 + best
        return depth_memo[name]

    def leaves(name: str) -> int | None:
        if name not in subckts:
            return 1
        if name in leaf_memo:
            return leaf_memo[name]
        if name in leaf_stack:
            return None
        if len(leaf_stack) >= MAX_HIERARCHY_DEPTH:
            flags["truncated"] = True
            return None
        leaf_stack.add(name)
        total: int | None = 0
        for inst in subckts[name]["instances"]:
            ref = inst.get("subckt_ref")
            part = leaves(ref) if ref else 1
            if part is None:
                total = None
                break
            total += part
        leaf_stack.discard(name)
        leaf_memo[name] = total
        return total

    max_depth = 0
    for inst in top_instances:
        ref = inst.get("subckt_ref")
        if ref:
            max_depth = max(max_depth, level(ref))
    for name in subckts:  # 未被顶层实例化的定义也走一遍环检测（库文件形态）
        level(name)
    flattened: int | None = 0
    for inst in top_instances:
        ref = inst.get("subckt_ref")
        part = leaves(ref) if ref else 1
        if part is None:
            flattened = None
            break
        flattened += part
    return {
        "max_depth": max_depth,
        "has_cycle": flags["has_cycle"],
        "truncated": flags["truncated"],
        "n_flattened_leaf_instances": flattened,
    }


def _build_stats(state: _ParseState) -> dict[str, Any]:
    instances = state.all_instances()
    counts: dict[str, int] = {}
    for inst in instances:
        counts[inst["device_type"]] = counts.get(inst["device_type"], 0) + 1
    hierarchy = _hierarchy_stats(state.top_instances, state.subckts)
    if hierarchy["has_cycle"]:
        state.warnings.append(
            "子电路层次存在环引用（自引用/互引）——深度按环截断；环自顶层可达时平铺叶计数为 None（如实）")
        state.diag(tier=TIER_UNSUPPORTED_2, reason="hierarchy_cycle_depth_truncated")
    if hierarchy["truncated"]:
        state.warnings.append(
            f"子电路实例化链超深（>{MAX_HIERARCHY_DEPTH} 层守卫）——深度截断、平铺叶计数 None（如实）")
        state.diag(tier=TIER_UNSUPPORTED_2, reason="hierarchy_depth_guard_truncated")
    return {
        "per_device_type_counts": dict(sorted(counts.items())),
        "n_instances": len(instances),
        "n_top_instances": len(state.top_instances),
        "n_body_instances": len(instances) - len(state.top_instances),
        "n_unknown_device_type": counts.get(DEVICE_TYPE_UNKNOWN, 0),
        "n_subckts": len(state.subckts),
        "n_subckt_instances": sum(1 for i in instances if i.get("subckt_ref")),
        "n_top_subckt_instances": sum(1 for i in state.top_instances if i.get("subckt_ref")),
        "max_depth": hierarchy["max_depth"],
        "max_definition_nesting": state.max_definition_nesting,
        "has_hierarchy_cycle": hierarchy["has_cycle"],
        "hierarchy_truncated": hierarchy["truncated"],
        "n_flattened_leaf_instances": hierarchy["n_flattened_leaf_instances"],
        "n_parameters": len(state.parameters),
        "n_models": len(state.models),
        "n_options_blocks": len(state.options_blocks),
        "n_includes": len(state.includes),
        "n_foreign_segments": len(state.foreign_segments),
        "n_warnings": 0,  # 收尾回填（统计面自身告警计入后定值）
    }


# --------------------------------------------------------------------------- #
# 公开入口
# --------------------------------------------------------------------------- #


def parse_spectre_text(text: str) -> dict[str, Any]:
    """Spectre 网表文本 → 结构化 dict（纯函数；fail-soft 零致命；不求值）。

    空文本/缺 ``simulator lang=spectre`` 声明 → warning 不拒（按 Spectre 语
    法解析）；键集见模块 docstring（schema=spectre_netlist/1.0）。
    """
    state = _ParseState()
    if not text.strip():
        state.warnings.append("空网表（无任何语句）——如实返回空结构")
    for line_no, stmt in _logical_statements(text, state.warnings, state.diags):
        state.feed(line_no, stmt)
    state.finish()
    if state.lang is None and text.strip():
        state.warnings.insert(0, (
            "缺 simulator lang=spectre 声明——按 Spectre 语法解析（容 spice 形态混写如实；"
            "纯 SPICE 网表请走 Q-X33 spice 解析器）"))
        state.diag(tier=TIER_UNSUPPORTED_3,
                   reason="missing_lang_declaration_assumed")
    stats = _build_stats(state)
    stats["n_warnings"] = len(state.warnings)
    return {
        "schema": f"spectre_netlist/{PARSER_SCHEMA_VERSION}",
        "lang": state.lang,
        "lang_switches": state.lang_switches,
        "parameters": state.parameters,
        "subckts": state.subckts,
        "top_instances": state.top_instances,
        "models": state.models,
        "options_blocks": state.options_blocks,
        "includes": state.includes,
        "foreign_segments": state.foreign_segments,
        "stats": stats,
        "warnings": state.warnings,
        "diagnostics": state.diags,
    }


def _doc_instances(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """文档全部实例（顶层+各 subckt 体，定义序）。"""
    out = list(doc.get("top_instances") or [])
    for sub in (doc.get("subckts") or {}).values():
        out.extend(sub.get("instances") or [])
    return out


def spectre_device_inventory(doc: dict[str, Any], *, top: int = 20) -> dict[str, Any]:
    """器件类型×计数+参数键频次 top（语句级，不按层次倍乘）。

    ``per_device_type``/``masters`` 按计数降序、同计数按名升序（确定性）；
    ``param_key_freq`` 取前 ``top`` 项（``top<=0`` 全量）。
    """
    instances = _doc_instances(doc)
    types: dict[str, int] = {}
    masters: dict[str, int] = {}
    keys: dict[str, int] = {}
    for inst in instances:
        dtype = inst.get("device_type") or DEVICE_TYPE_UNKNOWN
        types[dtype] = types.get(dtype, 0) + 1
        master = inst.get("master")
        if master:
            masters[master] = masters.get(master, 0) + 1
        for key in inst.get("params") or {}:
            keys[key] = keys.get(key, 0) + 1

    def ranked(counter: dict[str, int]) -> list[tuple[str, int]]:
        return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))

    key_rank = ranked(keys)
    if top > 0:
        key_rank = key_rank[:top]
    return {
        "n_instances": len(instances),
        "per_device_type": dict(ranked(types)),
        "n_unknown": types.get(DEVICE_TYPE_UNKNOWN, 0),
        "masters": dict(ranked(masters)),
        "param_key_freq": [{"key": k, "count": c} for k, c in key_rank],
        "n_distinct_param_keys": len(keys),
    }


def spectre_subckt_tree(doc: dict[str, Any]) -> dict[str, Any]:
    """子电路层次树+深度（根=顶层实例化的子电路，其后补未被任何实例引用的
    定义——库文件形态各自成根；再补前两类根均不可达的定义——互引环孤岛，
    保证每个定义都出现在树中；环引用以 ``recursive=True`` 叶截断）。
    """
    subckts: dict[str, dict[str, Any]] = doc.get("subckts") or {}
    children = _subckt_children(subckts)
    top_refs: list[str] = []
    for inst in doc.get("top_instances") or []:
        ref = inst.get("subckt_ref")
        if ref and ref not in top_refs:
            top_refs.append(ref)
    referenced = {k for kids in children.values() for k in kids} | set(top_refs)
    roots = list(top_refs) + [n for n in subckts if n not in referenced]
    reachable: set[str] = set()

    def mark(start: str) -> None:  # 迭代式可达标记（病态超深链不触递归上限）
        pending = [start]
        while pending:
            name = pending.pop()
            if name in reachable:
                continue
            reachable.add(name)
            pending.extend(children.get(name) or [])

    for root in roots:
        mark(root)
    for name in subckts:  # 互引环孤岛（被引用却不可达）补根——定义序确定性
        if name not in reachable:
            roots.append(name)
            mark(name)
    has_cycle = False
    truncated = False
    n_nodes = 0

    def node_for(name: str, seen: frozenset[str], depth: int) -> dict[str, Any]:
        nonlocal has_cycle, truncated, n_nodes
        n_nodes += 1
        if name in seen:
            has_cycle = True
            return {"name": name, "defined": name in subckts, "recursive": True,
                    "depth": depth, "children": []}
        sub = subckts.get(name)
        node: dict[str, Any] = {
            "name": name,
            "defined": sub is not None,
            "recursive": False,
            "depth": depth,
            "nodes": sub["nodes"] if sub else None,
            "n_body_instances": len(sub["instances"]) if sub else None,
            "children": [],
        }
        kids = children.get(name) or []
        if kids and (n_nodes >= MAX_TREE_NODES or depth >= MAX_HIERARCHY_DEPTH):
            truncated = True
            node["truncated"] = True
            return node
        for kid in kids:
            node["children"].append(node_for(kid, seen | {name}, depth + 1))
        return node

    trees = [node_for(r, frozenset(), 1) for r in roots]
    for tree in trees:
        tree["instantiated_at_top"] = tree["name"] in top_refs

    def deepest(node: dict[str, Any]) -> int:
        best = node["depth"] - 1 if node.get("recursive") else node["depth"]
        for child in node["children"]:
            best = max(best, deepest(child))
        return best

    return {
        "roots": trees,
        "n_subckts": len(subckts),
        "max_depth": max((deepest(t) for t in trees), default=0),
        "max_instantiated_depth": max((deepest(t) for t in trees if t["instantiated_at_top"]), default=0),
        "uninstantiated": [n for n in subckts if n not in referenced],
        "has_cycle": has_cycle,
        "truncated": truncated,
    }


def _ref_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_.$]){re.escape(name)}(?![A-Za-z0-9_.$])")


def spectre_param_refs(doc: dict[str, Any]) -> dict[str, Any]:
    """参数名 → 定义处+消费处清单（词边界文本匹配；作用域遮蔽不解析）。

    定义处：全局 ``parameters`` 声明（origin=parameters）与 subckt 形参
    （origin=subckt）。消费处：kind ∈ {expression, reference} 的值原文中词
    边界命中（数值/字符串不构成引用），站点 site ∈ {parameters,
    subckt_param, instance}，按行号稳定排序。
    """
    definitions: dict[str, list[dict[str, Any]]] = {}
    for name, entry in (doc.get("parameters") or {}).items():
        definitions.setdefault(name, []).append({
            "origin": "parameters", "line_no": entry.get("line_no"),
            "value_raw": entry.get("value_raw"),
        })
    subckts: dict[str, dict[str, Any]] = doc.get("subckts") or {}
    for sname, sub in subckts.items():
        for pname, typed in (sub.get("params") or {}).items():
            definitions.setdefault(pname, []).append({
                "origin": "subckt", "subckt": sname, "line_no": sub.get("line_no"),
                "value_raw": typed.get("value_raw"),
            })

    sites: list[dict[str, Any]] = []
    for pname, entry in (doc.get("parameters") or {}).items():
        sites.append({"site": "parameters", "param": pname, "line_no": entry.get("line_no"),
                      "value": entry})
    for sname, sub in subckts.items():
        for pname, typed in (sub.get("params") or {}).items():
            sites.append({"site": "subckt_param", "subckt": sname, "param": pname,
                          "line_no": sub.get("line_no"), "value": typed})
    for inst in _doc_instances(doc):
        for pname, typed in (inst.get("params") or {}).items():
            sites.append({"site": "instance", "instance": inst.get("name"), "scope": inst.get("scope") or [],
                          "param": pname, "line_no": inst.get("line_no"), "value": typed})
    sites.sort(key=lambda s: (s.get("line_no") or 0))

    refs: dict[str, Any] = {}
    for name, defs in definitions.items():
        pattern = _ref_pattern(name)
        consumers: list[dict[str, Any]] = []
        for site in sites:
            value = site["value"]
            if value.get("kind") not in ("expression", "reference"):
                continue
            if not pattern.search(str(value.get("value_raw") or "")):
                continue
            record = {k: v for k, v in site.items() if k != "value"}
            record["value_raw"] = value.get("value_raw")
            consumers.append(record)
        refs[name] = {"definitions": defs, "consumers": consumers, "n_consumers": len(consumers)}
    return refs
