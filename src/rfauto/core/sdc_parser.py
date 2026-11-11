"""SDC（Synopsys Design Constraints）结构化解析内核（aurora_q Q-X36，2026-11-07）。

数字 IC 标准**约束格式** SDC（Tcl 语法子集）的只读结构化解析——数模混合
设计中 RF 用户需要读取 SDC 做 clock/timing/IO 引用时的单源入口。Tcl 词法
与 SDC 命令语义全部在 core 确定性内核（铁律 7：结构化数字只出自数据源
文本本身；LLM/agent 永不产生物理数字）。服务包装见
:mod:`rfauto.service.sdc_service`（规则 4 JSON 进出），CLI 薄壳见
cli/domains/sdc.py。

Tcl 词法覆盖面（SDC 是 Tcl 子集；本内核按 Tcl 正式规则解析）：

- 命令分隔：换行或 ``;``；一命令=命令名+参数词表；
- 注释：命令位 ``#`` 起注释到行尾（Tcl 正式规则；``;#`` 同）；词位
  起头的 ``#`` 按 SDC 工具宽容惯例同样作行注释（严格 Tcl 会当普通
  词——SDC 生态行尾注释两形态都常见，取宽容口径并在此如实声明）；
  词中 ``#`` 是普通字符（``net#1`` 保真）；
- 词形态：裸词 / ``"引号词"``（可含空白，转义+替换生效）／
  ``{花括号词}``（**零替换**、嵌套配平、可跨行——SDC 多行列表惯例）
  ＋ ``[方括号]`` 命令替换（词首或词中皆可；内容作为子脚本原文保留，
  按需递归解析——``[get_ports {a, b}]`` 对象访问器惯例）；一词可多段
  拼接（``clk$idx``／``pad[get_cells x]`` 类，parts 有序保留）；
- 变量替换：``$name`` / ``${name}``——``set`` 命令按解析序即时更新
  环境变量表，后续引用取最新值；``\\$`` 转义字面 ``$``；未定义变量
  如实保留原文 ``$name``（静态解析无运行时语义，不猜不炸）；
- 转义：词内 ``\\x`` 取下一字面字（``\\"`` ``\\[`` 惯例）；行尾反斜
  杠（下一字符=换行）为行连续；
- 词中字面：``"``/``{``/``}`` 只在词首特殊（Tcl 语义）；词中一律普通
  字符；词内扫描边界=空白/换行/``;``/``[``/``$``。

SDC 命令语义面（结构化输出 schema）：

- clocks：create_clock（-name/-period/-waveform/-add；无名时钟从源
  对象首 pattern 派生并如实标 auto_named）/ create_generated_clock
  （-source/-divide_by/-multiply_by/-edges/-master_clock，kind=
  generated）；
- delays：set_input_delay / set_output_delay（-clock/-max/-min 布尔
  旗标；既无 -max 又无 -min 时 Synopsys 语义=双边同时置值，max=min=
  true 如实落键）；
- paths：set_false_path / set_max_delay / set_min_delay（-from/
  -through/-to 对象引用；value 为 max/min delay 数值，false_path 无值）；
- constraints：set_load（-capacitance/-pin_count）、set_driving_cell
  （-lib_cell）、set_fanout_load、set_case_analysis（value 字面
  0/1/rising/falling）、set_multicycle_path（-setup/-hold/-end/-start
  +倍数）、set_clock_latency（-source/-late/-early）、
  set_clock_uncertainty（-setup/-hold）；false_paths 为 paths 中
  false_path 的镜像桶（消费面两口径各取所需）；
- 对象访问器：get_ports/get_pins/get_cells/get_nets/get_clocks（内联
  子命令与顶层独立命令两条路径统一收集 patterns；pattern 列表按空白
  +逗号切分——SDC 惯例空白分隔，``{clk_p, clk_n}`` 逗号形兼容收取）。

未知命令不报错（SDC 文件合法地含工具私有命令），进 ``warnings``
（line+name）如实披露后继续解析——宁全量带警告，不半途而废。

错误：词法/结构违规（引号/花括号/方括号未闭合等）抛
:class:`SdcParseError`（ValueError 子类，带行号定位）——服务层转
error 信封，CLI 层 exit 1。零 IO（纯文本进出）、零依赖、确定性
（同输入同输出）。本模块不设 ``__all__``（无 __all__ 文件不进
tests/gold/public_api.json——hfss_run_report_service 同款先例，新
模块零金快照漂移）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_VAR_NAME_RE = re.compile(r"[A-Za-z0-9_:]+")
_NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_INT_RE = re.compile(r"[+-]?\d+")
#: 旗标词判定：``-`` 后以字母起头（负数值 ``-1.0`` 不会被当旗标）
_FLAG_RE = re.compile(r"-[A-Za-z][A-Za-z0-9_]*")


class SdcParseError(ValueError):
    """SDC/Tcl 词法或结构违规（ValueError 子类，带行号文本）。"""


#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"


# ─── Tcl 词法（tokenizer）──────────────────────────────────────────────────


def _resolve_var(name: str, env: dict[str, str]) -> str:
    """变量替换：环境命中给值，未命中如实保留 ``$name`` 原文。"""
    if name in env:
        return env[name]
    return "$" + name


@dataclass(frozen=True)
class TclWord:
    """一个 Tcl 词：kind（bare/quoted/braced/mixed）+ 有序分段 parts。

    - ``value``：词值（var 段按环境替换后的拼接串；script 段以
      ``[...]`` 原文形态并入）；
    - ``scripts``：词内全部 ``[...]`` 子脚本原文（按出现序）——SDC
      对象访问器 ``[get_ports ...]`` 的入口；
    - ``literal``：True=花括号词（Tcl 语义零替换）。
    """

    kind: str
    parts: tuple[tuple[str, str], ...]

    @property
    def value(self) -> str:
        out: list[str] = []
        for tag, text in self.parts:
            if tag == "script":
                out.append("[" + text + "]")
            else:
                out.append(text)
        return "".join(out)

    @property
    def scripts(self) -> tuple[str, ...]:
        return tuple(text for tag, text in self.parts if tag == "script")

    @property
    def literal(self) -> bool:
        return self.kind == "braced"


@dataclass(frozen=True)
class TclCommand:
    """一条命令：命令名+词表+起始行号+原文。"""

    name: str
    args: tuple[TclWord, ...]
    line: int
    raw: str

    def flag_map(
        self, boolean_flags: frozenset[str] | set[str] = frozenset()
    ) -> tuple[dict[str, TclWord | bool], list[TclWord]]:
        """旗标/位置参数两分（SDC 语义层单源）。

        规则：``-字母`` 起头的词为旗标（负数值 ``-1.0`` 不误判）；布尔
        旗标（``boolean_flags`` 用**带连字符全名**比对）不取值；其余旗
        标吃紧跟的下一词作值（下一词也是旗标或缺位时如实记 True——静
        态解析无上下文可判，宁标注不臆断）；非旗标词按序进 positional。
        返回（flags: {去连字符名: TclWord|True},
        positional: [TclWord]）——词态保留使 ``-from [get_ports a]``
        类脚本值可进 :func:`parse_object_spec`。
        """
        flags: dict[str, TclWord | bool] = {}
        positional: list[TclWord] = []
        i = 0
        words = self.args
        while i < len(words):
            text = words[i].value
            if _FLAG_RE.fullmatch(text):
                key = text[1:]
                nxt = words[i + 1] if i + 1 < len(words) else None
                if text in boolean_flags or nxt is None or \
                        _FLAG_RE.fullmatch(nxt.value):
                    flags[key] = True
                else:
                    flags[key] = nxt
                    i += 1
            else:
                positional.append(words[i])
            i += 1
        return flags, positional


def _read_quoted(
    text: str, i: int, env: dict[str, str], line: int
) -> tuple[str, int, int]:
    """引号词体：转义+变量替换+``[...]`` 子命令保留。

    script 段替换结果静态解析无值可代入——如实保留 ``[...]`` 原文
    （与未定义变量同口径）。返回（值, 越过闭引号位, 末行号）。
    """
    n = len(text)
    line0 = line
    buf: list[str] = []
    while i < n:
        c = text[i]
        if c == '"':
            return "".join(buf), i + 1, line
        if c == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "\n":
                buf.append(" ")
                line += 1
            else:
                buf.append(nxt)
            i += 2
            continue
        if c == "$":
            if text[i + 1: i + 2] == "{":
                end = text.find("}", i + 2)
                if end < 0:
                    raise SdcParseError(
                        f"第 {line} 行：${{...}} 变量名花括号未闭合")
                buf.append(_resolve_var(text[i + 2: end], env))
                i = end + 1
                continue
            m = _VAR_NAME_RE.match(text, i + 1)
            if m:
                buf.append(_resolve_var(m.group(0), env))
                i = m.end()
                continue
            buf.append("$")
            i += 1
            continue
        if c == "[":
            body, i2, line2 = _read_bracketed(text, i + 1, line)
            buf.append("[" + body + "]")
            i, line = i2, line2
            continue
        if c == "\n":
            line += 1
        buf.append(c)
        i += 1
    raise SdcParseError(f"第 {line0} 行：引号词未闭合")


def _read_braced(text: str, i: int, line: int) -> tuple[str, int, int]:
    """花括号体：零替换、嵌套配平、可跨行。返回（体原文, 越过 ``}`` 位, 末行）。"""
    n = len(text)
    depth = 1
    start = i
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1, line
        elif c == "\n":
            line += 1
        i += 1
    raise SdcParseError(f"第 {line} 行：花括号词未闭合（缺右花括号）")


def _read_bracketed(text: str, i: int, line: int) -> tuple[str, int, int]:
    """方括号子脚本体：``]`` 配平（引号体内的 ``]`` 不计）。

    返回（体原文, 越过 ``]`` 位, 末行）。
    """
    n = len(text)
    depth = 1
    start = i
    while i < n:
        c = text[i]
        if c == "]":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1, line
        if c == "[":
            depth += 1
        elif c == '"':
            _, i2, line2 = _read_quoted(text, i + 1, {}, line)
            i, line = i2, line2  # 已越过闭引号，主循环无需回退
            continue
        elif c == "\n":
            line += 1
        i += 1
    raise SdcParseError(f"第 {line} 行：方括号子命令未闭合（缺 ]）")


def _read_word(
    text: str, i: int, env: dict[str, str], line: int
) -> tuple[TclWord, int, int]:
    """从词首读单个词（调用方保证 ``i`` 不在空白/分隔/注释位）。"""
    n = len(text)
    parts: list[tuple[str, str]] = []
    kinds: set[str] = set()
    while i < n:
        c = text[i]
        if c in " \t\r\n;":
            break
        if c == '"' and not parts:
            kinds.add("quoted")
            seg, i, line = _read_quoted(text, i + 1, env, line)
            parts.append(("text", seg))
            continue
        if c == "{" and not parts:
            kinds.add("braced")
            body, i, line = _read_braced(text, i + 1, line)
            parts.append(("text", body))
            continue
        if c == "[":
            kinds.add("script")
            body, i, line = _read_bracketed(text, i + 1, line)
            parts.append(("script", body))
            continue
        if c == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "\n":
                line += 1
                i += 2
                continue
            parts.append(("text", nxt))
            i += 2
            continue
        if c == "$":
            if text[i + 1: i + 2] == "{":
                end = text.find("}", i + 2)
                if end < 0:
                    raise SdcParseError(
                        f"第 {line} 行：${{...}} 变量名花括号未闭合")
                parts.append(("text", _resolve_var(text[i + 2: end], env)))
                i = end + 1
                continue
            m = _VAR_NAME_RE.match(text, i + 1)
            if m:
                parts.append(("text", _resolve_var(m.group(0), env)))
                i = m.end()
                continue
            parts.append(("text", "$"))
            i += 1
            continue
        # 裸词字符：吃到边界（空白/换行/;/[/$）；词中 " { } # 按字面
        j = i
        while j < n and text[j] not in " \t\r\n;[$":
            j += 1
        parts.append(("text", text[i:j]))
        i = j
    kind = "mixed" if len(kinds) > 1 else (
        next(iter(kinds)) if kinds else "bare")
    return TclWord(kind=kind, parts=tuple(parts)), i, line


def _skip_line_comment(text: str, i: int, line: int) -> tuple[int, int]:
    """``#`` 行注释：吃到行尾（反斜杠续行的注释行同样并入）。"""
    n = len(text)
    while i < n and text[i] != "\n":
        if text[i] == "\\" and text[i + 1: i + 2] == "\n":
            line += 1
            i += 2
            continue
        i += 1
    return i, line


def _split_words(
    text: str, start: int, env: dict[str, str], line: int
) -> tuple[list[TclWord], int, int]:
    """从命令位起读一命令的词表，直到命令分隔符（换行/``;``）。

    词位起头的 ``#`` 按 SDC 宽容惯例作行注释（结束本命令）。
    返回（词表, 下一扫描位, 末行号）。
    """
    words: list[TclWord] = []
    i, n = start, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r":
            i += 1
            continue
        if c == "\n":
            line += 1
            i += 1
            break
        if c == ";":
            i += 1
            break
        if c == "\\" and text[i + 1: i + 2] == "\n":
            line += 1
            i += 2
            continue
        if c == "#":
            i, line = _skip_line_comment(text, i, line)
            break
        word, i, line = _read_word(text, i, env, line)
        words.append(word)
    return words, i, line


def parse_tcl(
    text: str, variables: dict[str, str] | None = None
) -> list[TclCommand]:
    """Tcl 文本 → 命令表（词法层；SDC 语义在 :func:`parse_sdc`）。

    ``variables``：外部变量环境初值；``set`` 命令按解析序即时更新同一
    环境（后续 ``$name`` 取最新值）；传入 dict 者可读回终态。
    """
    env: dict[str, str] = dict(variables or {})
    commands: list[TclCommand] = []
    i, n = 0, len(text)
    line = 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r;":
            i += 1
            continue
        if c == "\\" and text[i + 1: i + 2] == "\n":
            line += 1
            i += 2
            continue
        if c == "#":
            i, line = _skip_line_comment(text, i, line)
            continue
        line0 = line
        start = i
        words, i, line = _split_words(text, i, env, line)
        if words:
            commands.append(TclCommand(
                name=words[0].value,
                args=tuple(words[1:]),
                line=line0,
                raw=text[start: i].strip().rstrip(";").strip(),
            ))
            if words[0].value == "set" and len(words) >= 3:
                env[words[1].value] = words[2].value
    if variables is not None:
        variables.clear()
        variables.update(env)
    return commands


# ─── SDC 语义层 ────────────────────────────────────────────────────────────

#: 对象访问器命令 → 结构化 kind（schema 钉）
OBJECT_ACCESSORS = {
    "get_ports": "ports",
    "get_pins": "pins",
    "get_cells": "cells",
    "get_nets": "nets",
    "get_clocks": "clocks",
}

#: 对象访问器布尔旗标（不取值；其余旗标的值词不进 patterns——如
#: ``-filter`` 的搜索表达式，消费面要原值走 filters 原文形态再解析）
ACCESSOR_BOOLEAN_FLAGS = frozenset({"-quiet", "-expand", "-nofilter"})


def _accessor_split(args: tuple[TclWord, ...]) -> tuple[list[str], list[str]]:
    """访问器参数两分：patterns 词序 + filters 旗标名（值词不进 patterns）。"""
    patterns: list[str] = []
    filters: list[str] = []
    i = 0
    while i < len(args):
        text = args[i].value
        if _FLAG_RE.fullmatch(text):
            filters.append(text)
            if text not in ACCESSOR_BOOLEAN_FLAGS and i + 1 < len(args) \
                    and not _FLAG_RE.fullmatch(args[i + 1].value):
                i += 2  # 旗标+其值成对跳过（值不进 patterns）
                continue
            i += 1
            continue
        patterns.extend(_split_patterns(text))
        i += 1
    return patterns, filters


#: SDC 命令面（解释器注册表；面外命令进 warnings 如实披露）
SDC_COMMANDS = (
    "create_clock",
    "create_generated_clock",
    "set_clock_latency",
    "set_clock_uncertainty",
    "set_input_delay",
    "set_output_delay",
    "set_false_path",
    "set_multicycle_path",
    "set_max_delay",
    "set_min_delay",
    "set_load",
    "set_driving_cell",
    "set_fanout_load",
    "set_case_analysis",
    "get_ports",
    "get_pins",
    "get_cells",
    "get_nets",
    "get_clocks",
    "set",
)

#: 路径端点旗标族（-from/-through/-to 及 rise/fall 变体统一收集）
_PATH_FLAG_KEYS = (
    "-from", "-to", "-through",
    "-rise_from", "-fall_from", "-rise_to", "-fall_to",
    "-rise_through", "-fall_through",
)

_EMPTY_SPEC: dict[str, Any] = {"kind": "plain", "raw": "", "patterns": []}


def as_number(text: str) -> int | float | None:
    """数值字面量转换（整型字面量→int、其余→float；失败如实 None）。"""
    stripped = text.strip()
    if not _NUM_RE.fullmatch(stripped):
        return None
    if _INT_RE.fullmatch(stripped):
        return int(stripped)
    return float(stripped)


def _split_patterns(text: str) -> list[str]:
    """对象 pattern 列表切分：空白+逗号（SDC 惯例空白分隔，逗号形兼容）。"""
    return [p for p in re.split(r"[\s,]+", text.strip()) if p]


def _parse_sub_script(
    script: str, patterns: list[str], filters: list[str],
    env: dict[str, str],
) -> str | None:
    """解析一个 ``[...]`` 子脚本：取首个对象访问器的 kind 与 patterns。

    返回 kind（未知访问器=unknown；空脚本/无命令=None）。
    """
    kind: str | None = None
    for sub in parse_tcl(script, dict(env)):
        if kind is None:
            kind = OBJECT_ACCESSORS.get(sub.name, "unknown")
        sub_patterns, sub_filters = _accessor_split(sub.args)
        patterns.extend(sub_patterns)
        filters.extend(sub_filters)
    return kind


def parse_object_spec(
    word_or_text: TclWord | str, variables: dict[str, str] | None = None
) -> dict[str, Any]:
    """对象引用词 → 结构化 spec（kind/raw/patterns，含访问器 filters）。

    形态三路（都如实落键）：

    - ``[get_ports {a, b}]`` 子命令形态：kind 取访问器名（未知访问器
      kind=unknown，patterns 仍收取）；访问器旗标（如 ``-filter``）
      原文并入 filters；
    - ``{a b}`` 花括号列表 / 裸词形态：kind=plain，patterns 按空白+逗
      号切分；
    - 词内多段拼接：文本段与 script 段按 parts 有序合并（pattern 序=
      原文序；kind=首个访问器的 kind）。
    """
    env: dict[str, str] = dict(variables or {})
    if isinstance(word_or_text, TclWord):
        parts = word_or_text.parts
        text_value = word_or_text.value
    else:
        parts = (("text", word_or_text),)
        text_value = word_or_text
    patterns: list[str] = []
    filters: list[str] = []
    kind: str | None = None
    for tag, text in parts:
        if tag == "text":
            patterns.extend(_split_patterns(text))
        else:
            sub_kind = _parse_sub_script(text, patterns, filters, env)
            if kind is None and sub_kind is not None:
                kind = sub_kind
    spec: dict[str, Any] = {
        "kind": kind or "plain",
        "raw": text_value,
        "patterns": patterns,
    }
    if filters:
        spec["filters"] = list(filters)
    return spec


def _flag_str(flags: dict[str, TclWord | bool], key: str) -> str | None:
    """旗标值取字符串（词态→value；布尔态/缺位→None）。"""
    value = flags.get(key)
    return value.value if isinstance(value, TclWord) else None


def _flag_num(flags: dict[str, TclWord | bool], key: str) -> int | float | None:
    """旗标值取数值（缺位/非数值如实 None）。"""
    text = _flag_str(flags, key)
    return as_number(text) if text is not None else None


def _merge_path_flags(flags: dict[str, TclWord | bool]) -> dict[str, Any]:
    """-from/-through/-to 族 → 结构化三键（族内首个命中旗标落位）。"""
    out: dict[str, Any] = {"from": None, "through": None, "to": None}
    for key in _PATH_FLAG_KEYS:
        bare = key[1:]
        if bare not in flags:
            continue
        if "through" in key:
            slot = "through"
        elif key == "-to" or key.endswith("_to"):
            slot = "to"
        else:
            slot = "from"
        value = flags[bare]
        if out[slot] is None:
            out[slot] = parse_object_spec(value) if isinstance(
                value, TclWord) else dict(_EMPTY_SPEC)
    return out


def _handle_create_clock(cmd: TclCommand, doc: dict[str, Any]) -> None:
    flags, positional = cmd.flag_map(boolean_flags=frozenset({"-add"}))
    period = _flag_num(flags, "period")
    waveform: list[int | float] = []
    wave_text = _flag_str(flags, "waveform")
    if wave_text is not None:
        for piece in _split_patterns(wave_text):
            num = as_number(piece)
            if num is not None:
                waveform.append(num)
    sources = parse_object_spec(positional[0]) if positional else dict(
        _EMPTY_SPEC)
    name = _flag_str(flags, "name")
    auto_named = name is None
    if auto_named and sources["patterns"]:
        name = sources["patterns"][0]
    doc["clocks"].append({
        "kind": "primary",
        "name": name,
        "auto_named": auto_named,
        "period": period,
        "waveform": waveform,
        "add": bool(flags.get("add")),
        "sources": sources,
        "line": cmd.line,
    })


def _handle_create_generated_clock(
    cmd: TclCommand, doc: dict[str, Any]
) -> None:
    flags, positional = cmd.flag_map(
        boolean_flags=frozenset({"-add", "-combinational"}))
    divide_by = _flag_num(flags, "divide_by")
    multiply_by = _flag_num(flags, "multiply_by")
    edges: list[int] = []
    edges_text = _flag_str(flags, "edges")
    if edges_text is not None:
        for piece in _split_patterns(edges_text):
            num = as_number(piece)
            if isinstance(num, int):
                edges.append(num)
    source: dict[str, Any] | None = None
    source_word = flags.get("source")
    if isinstance(source_word, TclWord):
        source = parse_object_spec(source_word)
    elif positional:
        # -source 缺省时首位置参数为源对象（Synopsys 语法主形态）
        source = parse_object_spec(positional[0])
        positional = positional[1:]
    doc["clocks"].append({
        "kind": "generated",
        "name": _flag_str(flags, "name"),
        "source": source,
        "divide_by": divide_by,
        "multiply_by": multiply_by,
        "edges": edges,
        "master_clock": _flag_str(flags, "master_clock"),
        "add": bool(flags.get("add")),
        "line": cmd.line,
    })


def _handle_set_clock_latency(cmd: TclCommand, doc: dict[str, Any]) -> None:
    flags, positional = cmd.flag_map(
        boolean_flags=frozenset({"-source", "-late", "-early"}))
    value = as_number(positional[0].value) if positional else None
    targets = parse_object_spec(positional[1]) if len(positional) > 1 else \
        dict(_EMPTY_SPEC)
    doc["constraints"]["clock_latency"].append({
        "source": bool(flags.get("source")),
        "late": bool(flags.get("late")),
        "early": bool(flags.get("early")),
        "value": value,
        "objects": targets,
        "line": cmd.line,
    })


def _handle_set_clock_uncertainty(
    cmd: TclCommand, doc: dict[str, Any]
) -> None:
    flags, positional = cmd.flag_map(
        boolean_flags=frozenset({"-setup", "-hold", "-rise", "-fall"}))
    value = as_number(positional[0].value) if positional else None
    targets = parse_object_spec(positional[1]) if len(positional) > 1 else \
        dict(_EMPTY_SPEC)
    endpoints = _merge_path_flags(flags)
    doc["constraints"]["clock_uncertainty"].append({
        "setup": bool(flags.get("setup")),
        "hold": bool(flags.get("hold")),
        "value": value,
        "objects": targets,
        "from": endpoints["from"],
        "to": endpoints["to"],
        "line": cmd.line,
    })


def _handle_set_io_delay(
    io_type: str, cmd: TclCommand, doc: dict[str, Any]
) -> None:
    flags, positional = cmd.flag_map(
        boolean_flags=frozenset({"-max", "-min", "-rise", "-fall",
                                 "-add_delay",
                                 "-source_latency_included",
                                 "-network_latency_included"}))
    value = as_number(positional[0].value) if positional else None
    targets = parse_object_spec(positional[1]) if len(positional) > 1 else \
        dict(_EMPTY_SPEC)
    has_max = bool(flags.get("max"))
    has_min = bool(flags.get("min"))
    if not has_max and not has_min:
        # Synopsys 语义：不带 -max/-min = 双边同时置值
        has_max = has_min = True
    doc["delays"].append({
        "type": io_type,
        "value": value,
        "max": has_max,
        "min": has_min,
        "clock": _flag_str(flags, "clock"),
        "from": targets,
        "to": None,
        "line": cmd.line,
    })


def _handle_set_false_path(cmd: TclCommand, doc: dict[str, Any]) -> None:
    flags, positional = cmd.flag_map(
        boolean_flags=frozenset({"-setup", "-hold", "-rise", "-fall"}))
    if positional:
        doc["warnings"].append({
            "line": cmd.line,
            "name": cmd.name,
            "note": "set_false_path 不取位置参数（多余词如实登记）",
        })
    endpoints = _merge_path_flags(flags)
    doc["paths"].append({
        "type": "false_path",
        "setup": bool(flags.get("setup")),
        "hold": bool(flags.get("hold")),
        "value": None,
        "from": endpoints["from"],
        "through": endpoints["through"],
        "to": endpoints["to"],
        "line": cmd.line,
    })


def _handle_set_mm_delay(
    kind: str, cmd: TclCommand, doc: dict[str, Any]
) -> None:
    flags, positional = cmd.flag_map(
        boolean_flags=frozenset({"-setup", "-hold", "-rise", "-fall"}))
    value = as_number(positional[0].value) if positional else None
    endpoints = _merge_path_flags(flags)
    doc["paths"].append({
        "type": kind,
        "setup": bool(flags.get("setup")),
        "hold": bool(flags.get("hold")),
        "value": value,
        "from": endpoints["from"],
        "through": endpoints["through"],
        "to": endpoints["to"],
        "line": cmd.line,
    })


def _handle_set_multicycle_path(
    cmd: TclCommand, doc: dict[str, Any]
) -> None:
    flags, positional = cmd.flag_map(
        boolean_flags=frozenset({"-setup", "-hold", "-end", "-start"}))
    multiplier = as_number(positional[0].value) if positional else None
    endpoints = _merge_path_flags(flags)
    reference = "end" if flags.get("end") else (
        "start" if flags.get("start") else None)
    doc["constraints"]["multicycles"].append({
        "multiplier": multiplier,
        "setup": bool(flags.get("setup")),
        "hold": bool(flags.get("hold")),
        "reference": reference,
        "from": endpoints["from"],
        "through": endpoints["through"],
        "to": endpoints["to"],
        "line": cmd.line,
    })


def _handle_set_load(cmd: TclCommand, doc: dict[str, Any]) -> None:
    flags, positional = cmd.flag_map(frozenset())
    capacitance = _flag_num(flags, "capacitance")
    pin_count = _flag_num(flags, "pin_count")
    targets = parse_object_spec(positional[0]) if positional else dict(
        _EMPTY_SPEC)
    doc["constraints"]["loads"].append({
        "capacitance": capacitance,
        "pin_count": pin_count,
        "objects": targets,
        "line": cmd.line,
    })


def _handle_set_driving_cell(cmd: TclCommand, doc: dict[str, Any]) -> None:
    flags, positional = cmd.flag_map(frozenset())
    targets = parse_object_spec(positional[0]) if positional else dict(
        _EMPTY_SPEC)
    doc["constraints"]["driving_cells"].append({
        "lib_cell": _flag_str(flags, "lib_cell"),
        "pin": _flag_str(flags, "pin"),
        "objects": targets,
        "line": cmd.line,
    })


def _handle_set_fanout_load(cmd: TclCommand, doc: dict[str, Any]) -> None:
    flags, positional = cmd.flag_map(frozenset())
    if flags:
        doc["warnings"].append({
            "line": cmd.line,
            "name": cmd.name,
            "note": "set_fanout_load 只取 数值+对象 两位置参数"
                    "（多余旗标如实登记）",
        })
    value = as_number(positional[0].value) if positional else None
    targets = parse_object_spec(positional[1]) if len(positional) > 1 else \
        dict(_EMPTY_SPEC)
    doc["constraints"]["fanout_loads"].append({
        "value": value,
        "objects": targets,
        "line": cmd.line,
    })


def _handle_set_case_analysis(cmd: TclCommand, doc: dict[str, Any]) -> None:
    flags, positional = cmd.flag_map(frozenset())
    if flags:
        doc["warnings"].append({
            "line": cmd.line,
            "name": cmd.name,
            "note": "set_case_analysis 只取 值+对象 两位置参数"
                    "（多余旗标如实登记）",
        })
    raw = positional[0].value if positional else ""
    value = as_number(raw)
    targets = parse_object_spec(positional[1]) if len(positional) > 1 else \
        dict(_EMPTY_SPEC)
    doc["constraints"]["case_analyses"].append({
        "value": value if value is not None else raw,
        "objects": targets,
        "line": cmd.line,
    })


def _handle_accessor(cmd: TclCommand, doc: dict[str, Any]) -> None:
    kind = OBJECT_ACCESSORS[cmd.name]
    bucket = doc["objects"].setdefault(kind, [])
    patterns, filters = _accessor_split(cmd.args)
    spec: dict[str, Any] = {
        "kind": kind,
        "raw": " ".join(w.value for w in cmd.args),
        "patterns": patterns,
    }
    if filters:
        spec["filters"] = filters
    bucket.append(spec)


def _handle_set(
    cmd: TclCommand, doc: dict[str, Any], env: dict[str, str]
) -> None:
    values = [w.value for w in cmd.args]
    if len(values) >= 2:
        doc["variables"][values[0]] = values[1]


_HANDLERS = {
    "create_clock": _handle_create_clock,
    "create_generated_clock": _handle_create_generated_clock,
    "set_clock_latency": _handle_set_clock_latency,
    "set_clock_uncertainty": _handle_set_clock_uncertainty,
    "set_false_path": _handle_set_false_path,
    "set_multicycle_path": _handle_set_multicycle_path,
    "set_load": _handle_set_load,
    "set_driving_cell": _handle_set_driving_cell,
    "set_fanout_load": _handle_set_fanout_load,
    "set_case_analysis": _handle_set_case_analysis,
}


def _new_document() -> dict[str, Any]:
    return {
        # 自描述键（R-22 schema 升位批）：``"<域>/<N.0>"`` 复合键（本件
        # 原无自描述键，本批补键——附加键不改既有键语义）。
        "schema": f"sdc/{PARSER_SCHEMA_VERSION}",
        "clocks": [],
        "delays": [],
        "paths": [],
        "constraints": {
            "loads": [],
            "driving_cells": [],
            "fanout_loads": [],
            "case_analyses": [],
            "false_paths": [],
            "multicycles": [],
            "clock_latency": [],
            "clock_uncertainty": [],
        },
        "objects": {"ports": [], "pins": [], "cells": [], "nets": [],
                    "clocks": []},
        "variables": {},
        "commands": [],
        "warnings": [],
    }


def parse_sdc(
    text: str, variables: dict[str, str] | None = None
) -> dict[str, Any]:
    """SDC 文本 → 结构化文档（schema 见模块 docstring；纯函数零 IO）。

    ``variables``：外部变量环境（可读回终态，同 :func:`parse_tcl`）。
    词法违规抛 :class:`SdcParseError`；面外命令进 warnings 不中断。
    """
    doc = _new_document()
    env: dict[str, str] = dict(variables or {})
    for cmd in parse_tcl(text, env):
        doc["commands"].append({
            "name": cmd.name,
            "line": cmd.line,
            "arg_count": len(cmd.args),
        })
        if cmd.name in _HANDLERS:
            _HANDLERS[cmd.name](cmd, doc)
        elif cmd.name in ("set_input_delay", "set_output_delay"):
            _handle_set_io_delay(
                "input" if cmd.name == "set_input_delay" else "output",
                cmd, doc)
        elif cmd.name in ("set_max_delay", "set_min_delay"):
            _handle_set_mm_delay(
                "max_delay" if cmd.name == "set_max_delay" else "min_delay",
                cmd, doc)
        elif cmd.name in OBJECT_ACCESSORS:
            _handle_accessor(cmd, doc)
        elif cmd.name == "set":
            _handle_set(cmd, doc, env)
        else:
            doc["warnings"].append({
                "line": cmd.line,
                "name": cmd.name,
                "note": "SDC 命令面外命令（原样保留不解释）",
            })
    # false_paths 镜像桶（paths 中 type=false_path 的约束口径视图）
    doc["constraints"]["false_paths"] = [
        {"setup": p["setup"], "hold": p["hold"], "from": p["from"],
         "through": p["through"], "to": p["to"], "line": p["line"]}
        for p in doc["paths"] if p["type"] == "false_path"
    ]
    doc["variables"] = dict(env)
    doc["stats"] = {
        "n_commands": len(doc["commands"]),
        "n_clocks": len(doc["clocks"]),
        "n_delays": len(doc["delays"]),
        "n_paths": len(doc["paths"]),
        "n_warnings": len(doc["warnings"]),
    }
    if variables is not None:
        variables.clear()
        variables.update(env)
    return doc
