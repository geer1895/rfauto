"""Verilog-A 模拟行为级结构子集解析内核（aurora_q Q-X80，2026-11-08）。

模拟行为级建模标准 Verilog-A（Verilog-AMS 的模拟子集，Accellera 公开
规范 LRM 口径——Virtuoso ADE/I-V 曲线行为模型生态的交接语言）的**只读
结构化解析**——与仓内 Verilog-D 网表解析（:mod:`rfauto.core.
verilog_netlist_parser` Q-X47，数字 gate-level 结构面）分立：本模块面向
**模拟行为块语言面**（module/端口/net/parameter/analog 行为块/贡献语句），
供行为模型端口 I-V 关系结构化提取。词法、语句分类与表达式归一全部在
core 确定性内核（铁律 7：结构化数字只出自数据源文本本身——本模块**永不
求值、永不解释模拟求解语义**；LLM/agent 永不产生物理数字）。服务包装见
:mod:`rfauto.service.veriloga_service`（规则 4 JSON 进出），CLI 薄壳见
cli/domains/veriloga.py（独立 typer 根，citi/gdsii 同款孤儿域，接线待
主代理合流）。解析器集群四件套参照：core/verilog_netlist_parser.py
（Q-X47 词法家法）、core/skill_parser.py（Q-X62 表达式处理同代）、
cli/domains/stil.py（域形态同款）、service/verilog_netlist_service.py
（信封同款）。

覆盖面（**结构性子集**；明确不做——analog 函数体语义/模拟求解语义/
ddx·idt·integral 等模拟算子的解释/AMS 混合信号全语言/generate 块展开，
见各条目"如实登记"口径）：

- 词法（Q-X47 家法）：``//`` 行注释与 ``/* */`` 块注释（未闭合抛
  :class:`VerilogAParseError` 带行号）；字符串 ``"..."``（转义 ``\\``；
  未闭合抛错）；标识符 ``[A-Za-z_][A-Za-z0-9_$]*`` + 转义标识符
  ``\\name`` 到空白止；数字明数（int/浮点/科学计数/``_`` 位分隔）；
  编译器指令 ``\\`define`` 族整行消费为 ``dir`` token；系统任务 ``$`` 词
  识别；**属性注记** ``(* ... *)`` 两端各为独立 token 如实保留（不展开
  语义）；运算符最大吞噬（``<+`` ``**`` ``<=`` ``>=`` ``==`` ``!=``
  ``&&`` ``||``）+ 单字符兜底；括号嵌套深度守卫 :data:`MAX_NEST_DEPTH`
  （病态深嵌套 fail-closed）；零进展守卫（词法循环每轮必消耗 ≥1 字符，
  无法识别字符致命）。

- module：``module name (port, ...);`` + ``endmodule``；端口方向声明
  ``input/output/inout x;``（1995 头列名+体内方向声明 与 ANSI 头内
  声明 双形态统一归一）；net 类型 ``electrical/wire x, y;``（electrical=
  模拟节点；**自定义 discipline 声明面如实登记不展开**——``discipline
  <名> ... enddiscipline`` 只记名、体整块跳过）；``(* descend *)`` 属性
  注记 token 如实入 ``attributes`` 名录（原文形态）。endmodule 缺失
  fail-soft warning（不拒全文档）。

- 参数：``parameter real R = 50 from [0:inf);``——类型
  （:data:`PARAM_TYPES` = real/integer/string）+缺省值（表达式原文
  ``default_raw``；**纯数值字面量形态**附 ``default`` 数值回收——回收
  自源文本本身非解释，铁律 7 口径）+可选 ``from`` 范围约束（范围串
  **结构化保存不解释**：``[0:inf)`` → ``{"low": "0", "high": "inf",
  "low_inclusive": True, "high_inclusive": False, "raw": "[0:inf)"}``，
  开闭区间四形态 ``[a:b]``/``[a:b)``/``(a:b]``/``(a:b)`` 全收）；范围
  后残余子句（``exclude ...`` 族）原文入 ``extra_raw``。

- analog 行为块（结构性识别，不求值语义）：``analog begin ... end`` 与
  ``analog <单语句>;`` 双形态；语句分类计数（:data:`STMT_CATEGORIES`
  闭集）：
    - **贡献语句** ``V(out) <+ expr;`` / ``I(m) <+ expr;``——LHS 括号
      访问串 + ``<+`` 算子 + RHS 表达式归一树（逐条入
      ``contributions`` 表；RHS 归一失败 fail-soft：树置 None+警告，
      原文随 ``rhs_raw`` 保留）；
    - **控制结构** ``if/else/for/while``（块配对计数——``begin..end``
      嵌套配平，失衡 fail-soft 警告；``for (...)`` 头部括号整捕获，
      头内 ``;`` 不拆语句）；
    - **事件句法登记** ``@(initial_step)`` / ``@(cross(...))``——事件名
      +参数原文如实入 ``events`` 名录，守卫的宿主语句照常分类；
    - **函数调用形态归一** ``f(a, b)``（模拟算子 ddx/idt 等**只按调用
      形态归一，语义不解释**——结构子集边界如实）；
    - 其余散落语句 ``other`` 桶 + 赋值 ``=`` 桶。
  ``analog function`` 声明只记名、体跳 ``endfunction``+警告（函数体
  语义明确不做）。

- 表达式归一器 :func:`expr_to_prefix`：中缀 token 序 → **前缀（波兰）
  归一树**（嵌套 list 形态 ``["+", ["*", "a", "b"], "c"]``）——优先级
  表驱动（:data:`PRECEDENCE` 单源：``+ - * / % **`` ``> < >= <= ==``
  ``&& ||`` ``?:`` 闭集；一元 ``- !`` 最高；结合律按 Verilog-A/AMS 参
  考手册口径=**全表左结合、唯三目 ``?:`` 右结合**——``**`` 与
  SystemVerilog 的右结合口径不同，Verilog-A 参考手册明文例外条款仅
  conditional 一个），shunting-yard 迭代零递归；操作数分型（数字字面量/标识符/
  函数调用 ``f(a,b)`` → ``["f", args...]``/括号访问 ``V(x)`` 同函数
  调用形态/下标 ``a[i]`` → ``["[]", a, i]``/参数引用=标识符原样），
  **不求值**——数字一律字符串原样保留。超集运算符（``| ^ & << >>`` 族）
  不在优先级闭集 → :class:`ExpressionNormError`（fail-closed 不猜）。

- 结构化输出（schema :data:`PARSER_SCHEMA_VERSION`，全 JSON 原生类型）::

    {
      "schema_version": "1.0",
      "modules": {name: {"name", "ports": [{"dir", "name"}],
                         "nets": [{"type", "names"}],
                         "params": [{"name", "type", "default_raw",
                                     "default", "range", "extra_raw"}],
                         "analog": {"stmt_counts": {...},
                                    "contributions": [
                                        {"lhs", "rhs_prefix_tree"}],
                                    "events": [{"name", "args_raw"}]},
                         "attributes": [原文...]}},
      "module_order": [注册序名表],
      "disciplines": [discipline 声明名],
      "attributes": [文档级属性原文],
      "warnings": [{"line", "name", "note"}],
      "stats": {n_modules, n_ports, n_nets, n_params, n_contributions,
                n_events, n_warnings},
    }

- 查询三函数：:func:`veriloga_module_summary`（单模块汇总视图）/
  :func:`veriloga_param_table`（全模块参数平坦表）/-
  :func:`veriloga_contribution_pairs`（全部贡献对平坦清单——行为模型
  端口 I-V 关系的结构化入口）。

确定性（同输入同输出）、零 IO（纯文本进出）、零第三方依赖。本模块不设
``__all__``（无 __all__ 文件不进 tests/gold/public_api.json——
verilog_netlist_parser/skill_parser 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: 括号嵌套深度上限（病态深嵌套 fail-closed；真实 Verilog-A 嵌套 <20）。
MAX_NEST_DEPTH = 512

#: 端口方向词表（closed set）。
DIRECTIONS = ("input", "output", "inout")

#: 参数类型词表（Verilog-A parameter 类型 closed set；缺省声明如实 None）。
PARAM_TYPES = ("real", "integer", "string")

#: 已知 net/节点类型词表（electrical=模拟节点 + Verilog wire 族；词表外
#: 的类型标识符**如实登记** type 原文+温和警告——discipline 使用面宽，
#: 不猜不拒）。
KNOWN_NET_TYPES = ("electrical", "wire", "wand", "wor", "tri", "reg")

#: analog 语句分类闭集（stmt_counts 键面恒全集，缺席=0；block=begin..end
#: 配对数）。
STMT_CATEGORIES = (
    "contribution", "if", "else", "for", "while", "event",
    "function_call", "assignment", "block", "other",
)

#: 块嵌套深度上限（analog begin..end 嵌套配平的 runaway 防护）。
MAX_BLOCK_DEPTH = 256


class VerilogAParseError(ValueError):
    """Verilog-A 词法/结构致命违规（ValueError 子类，带行号文本）。

    覆盖：空文件、块注释/字符串未闭合、无法识别字符、嵌套深度越限。
    语句级病态一律 fail-soft 警告（不炸全文档）。
    """


class ExpressionNormError(ValueError):
    """表达式归一失败（ValueError 子类）。

    覆盖：括号/调用失配、优先级闭集外运算符、空表达式、悬挂运算符。
    贡献语句 RHS 归一失败时 fail-soft（树 None+警告）；独立调用本函数
    时由调用方决定 fail 语义。
    """


# ── 词法（tokenizer）────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Token:
    """一个词：kind（id/num/str/punct/sys/dir）+ 原文 + 起始行号。"""

    kind: str
    text: str
    line: int


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_NUM_RE = re.compile(
    r"(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?")
#: 多字符运算符（先 2 字符最大吞噬；含贡献算子 ``<+``）。
_OPERATORS_2 = ("<+", "**", "<=", ">=", "==", "!=", "&&", "||")
#: 属性注记两端（``(* ... *)``——独立 token，解析层如实登记）。
_ATTR_OPEN = "(*"
_ATTR_CLOSE = "*)"
_PUNCT_CHARS = "()[]{}:;,.=+-*/%<>?!@#&|^~"


def tokenize_veriloga(text: str) -> list[Token]:
    """Verilog-A 结构子集词法：文本 → token 序列。

    词法错误（块注释/字符串未闭合、无法识别字符、括号嵌套越限）抛
    :class:`VerilogAParseError` 带行号；编译器指令整行消费为单个
    ``dir`` token（text=指令名去反引号）。
    """
    tokens: list[Token] = []
    i = 0
    n = len(text)
    line = 1
    depth = 0  # 括号嵌套深度守卫（()[]{} 三对统一计数）
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
                raise VerilogAParseError(f"第 {line} 行：块注释未闭合")
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
                raise VerilogAParseError(f"第 {line} 行：字符串未闭合")
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
            raise VerilogAParseError(f"第 {line} 行：孤立反斜杠（转义标识符缺名）")
        if text.startswith(_ATTR_OPEN, i):
            tokens.append(Token("punct", _ATTR_OPEN, line))
            i += 2
            continue
        if text.startswith(_ATTR_CLOSE, i):
            tokens.append(Token("punct", _ATTR_CLOSE, line))
            i += 2
            continue
        if c == "`":
            # 编译器指令：整行消费；text=指令名去反引号
            j = i + 1
            m = _WORD_RE.match(text, j)
            name = m.group(0) if m else ""
            j = m.end() if m else j
            while j < n and text[j] != "\n":
                j += 1
            tokens.append(Token("dir", name, line))
            i = j
            continue
        if c == "$":
            # m.end() 系 text[i:] 切片坐标系——推进量必须 +=（271 行 _WORD_RE
            # 的 text 定点 match 同口径；曾误写 i = m.end() 致 i 回跳重扫死循环）
            m = re.match(r"\$[A-Za-z_][A-Za-z0-9_$]*", text[i:])
            tokens.append(Token("sys", m.group(0) if m else "$", line))
            i += m.end() if m else 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            m = _NUM_RE.match(text, i)
            tokens.append(Token("num", m.group(0), line))
            i = m.end()
            continue
        m = _WORD_RE.match(text, i)
        if m:
            tokens.append(Token("id", m.group(0), line))
            i = m.end()
            continue
        matched = 0
        chunk2 = text[i:i + 2]
        if chunk2 in _OPERATORS_2:
            matched = 2
        if matched:
            tokens.append(Token("punct", chunk2, line))
            i += matched
            continue
        if c in _PUNCT_CHARS:
            tokens.append(Token("punct", c, line))
            i += 1  # 零进展守卫：标点分支必须推进（缺此行=死循环实测）
            if c in "([{":
                depth += 1
                if depth > MAX_NEST_DEPTH:
                    raise VerilogAParseError(
                        f"第 {line} 行：括号嵌套深度超过上限 {MAX_NEST_DEPTH}"
                        "（病态深嵌套 fail-closed）")
            elif c in ")]}":
                depth = max(0, depth - 1)
            continue
        raise VerilogAParseError(f"第 {line} 行：无法识别的字符 {c!r}")
    return tokens


def parse_number_literal(raw: str) -> int | float | None:
    """数字字面量原文 → int/float 值（源文本回收，非求值解释）。

    int 形态（``50``/``1_000``）→ int；浮点/科学计数（``1.5``/``1e-3``）
    → float；其余（表达式、非数值）→ None（调用方如实保留原文）。
    """
    t = raw.strip().replace("_", "")
    if re.fullmatch(r"\d+", t):
        return int(t)
    try:
        return float(t)
    except ValueError:
        return None


# ── 表达式前缀归一（expr_to_prefix；shunting-yard 迭代零递归）───────────────

#: 二元运算符优先级表（单源）：op → (优先级, 是否左结合)。数值越大绑定
#: 越紧；结合律按 Verilog-A/AMS 参考手册=全表左结合、唯 ``?:`` 右结合
#: （``**`` 左结合——与 SystemVerilog 口径不同，Verilog-A 参考手册明文
#: 例外条款仅 conditional 一个）；``?:`` 三目不进本表（特殊处理）。
PRECEDENCE: dict[str, tuple[int, bool]] = {
    "||": (2, True),
    "&&": (3, True),
    "==": (4, True),
    "<": (5, True), ">": (5, True), "<=": (5, True), ">=": (5, True),
    "+": (6, True), "-": (6, True),
    "*": (7, True), "/": (7, True), "%": (7, True),
    "**": (8, True),
}
_UNARY_OPS = frozenset({"-", "!"})
_TERNARY_PREC = 1  # ?: 三目（右结合；: 触发折叠）
_UNARY_PREC = 9    # 一元 - !（最高、右结合、arity 1）


def _join_tokens(tokens: list[Token]) -> str:
    """token 序列 → 原文串（确定性重建：标点贴身、词间单空格）。"""
    _NO_BEFORE = frozenset({",", ";", ")", "]", "}", ":"})
    _NO_AFTER = frozenset({"(", "[", "{", ".", "<+"})
    out = ""
    for k, tok in enumerate(tokens):
        piece = tok.text
        if k == 0:
            out = piece
            continue
        prev = tokens[k - 1].text
        if piece in _NO_BEFORE or piece.startswith("'") or prev in _NO_AFTER:
            out += piece
        else:
            out += " " + piece
    return out


def _render_access(tokens: list[Token]) -> str:
    """括号访问/实参表 → 规范紧凑串（``V(p, n)`` 口径——LHS 访问串与
    事件参数原文的确定性渲染：标点贴身、左括号后与逗号后单空格、开括
    号贴头）。"""
    out = ""
    prev = ""
    for k, tok in enumerate(tokens):
        t = tok.text
        if k == 0:
            out = t
        elif t in (",", ")", "]") or prev == "(":
            out += t
        elif t == "(":
            out += "("
        else:
            out += " " + t
        prev = t
    return out


def expr_to_prefix(source: str | list[Token]) -> Any:
    """中缀表达式 → 前缀（波兰）归一树（不求值；数字字符串原样）。

    ``source``：表达式原文串（内部词法）或 token 列表。归一树形态：
    运算符/函数名为头、操作数为叶——``a + b * c`` →
    ``["+", "a", ["*", "b", "c"]]``；``f(a, b)`` → ``["f", "a", "b"]``；
    ``V(out)`` → ``["V", "out"]``（括号访问与函数调用同形归一）；
    ``a[i]`` → ``["[]", "a", "i"]``（区间下标 ``p[m:n]`` →
    ``["[]", "p", "m", "n"]``）；``c ? a : b`` → ``["?:", "c", "a",
    "b"]``（嵌套右结合 ``a ? b : c ? d : e`` → 外层 else 分支包内层）；
    一元 ``-x`` → ``["-", "x"]``（与二元减号靠 arity 区分）。括号组不
    产节点——分组语义由树结构承载。

    优先级闭集见 :data:`PRECEDENCE`（闭集外运算符、括号失配、空表达式
    抛 :class:`ExpressionNormError`）。shunting-yard 迭代实现（零递归，
    深嵌套不撞 Python 栈上限）；三目按 ``?`` 入栈/``:`` 换标/折叠点出
    三操作数的换标算法（中缀 ``?:`` 无独立闭符，``:`` 只换标不折叠，
    折叠发生在更高层运算符/帧闭合/表达式尾——嵌套与右结合由此自然成
    立）。
    """
    toks = tokenize_veriloga(source) if isinstance(source, str) \
        else list(source)
    if not toks:
        raise ExpressionNormError("空表达式（无 token）")
    out: list[Any] = []          # 操作数栈（str | list）
    ops: list[tuple[str, int, int]] = []  # (op, prec, arity)；?: 经 ?→: 换标
    frames: list[dict[str, Any]] = []     # group / call / index 帧
    expect_operand = True

    def fold_top() -> None:
        op, _prec, arity = ops.pop()
        if arity == 1:
            if not out:
                raise ExpressionNormError(f"一元 {op!r} 缺操作数")
            out.append([op, out.pop()])
        elif arity == 3:
            if len(out) < 3:
                raise ExpressionNormError("?: 操作数不足")
            rhs = out.pop()
            mid = out.pop()
            cond = out.pop()
            out.append(["?:", cond, mid, rhs])
        else:
            if len(out) < 2:
                raise ExpressionNormError(f"二元 {op!r} 操作数不足")
            rhs = out.pop()
            lhs = out.pop()
            out.append([op, lhs, rhs])

    def floor() -> int:
        return frames[-1]["ops0"] if frames else 0

    def fold_to_frame() -> None:
        while len(ops) > floor():
            fold_top()

    for tok in toks:
        text = tok.text
        if tok.kind in ("num", "id", "str"):
            out.append(text)
            expect_operand = False
            continue
        if tok.kind != "punct":
            raise ExpressionNormError(
                f"第 {tok.line} 行：表达式内不支持的 token {text!r}")
        if text in _UNARY_OPS and expect_operand:
            ops.append((text, _UNARY_PREC, 1))
            continue
        if expect_operand:
            if text == "(":
                frames.append({"kind": "group", "ops0": len(ops)})
                continue
            raise ExpressionNormError(
                f"第 {tok.line} 行：表达式期待操作数，实得 {text!r}")
        # —— 操作数之后（期待运算符/闭括号/逗号）——
        if text == "(":
            # 紧跟操作数的 ( = 函数调用/括号访问（头=弹出的标识符）
            if not out or not isinstance(out[-1], str) \
                    or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", out[-1]):
                raise ExpressionNormError(
                    f"第 {tok.line} 行：{text!r} 前缺可调用头")
            head = out.pop()
            frames.append(
                {"kind": "call", "func": head, "args": [], "ops0": len(ops)})
            expect_operand = True
            continue
        if text == "[":
            if len(out) <= floor():
                raise ExpressionNormError(f"第 {tok.line} 行：下标缺基名")
            frames.append({"kind": "index", "base": out.pop(),
                           "range_seen": False, "msb": None,
                           "ops0": len(ops)})
            expect_operand = True
            continue
        if text == ")":
            if not frames or frames[-1]["kind"] not in ("call", "group"):
                raise ExpressionNormError(
                    f"第 {tok.line} 行：多余/失配的右括号")
            frame = frames[-1]
            fold_to_frame()
            if frame["kind"] == "call":
                arg = out.pop() if len(out) > frame["ops0"] else None
                node = [frame["func"], *frame["args"]]
                if arg is not None:
                    node.append(arg)
                frames.pop()
                out.append(node)
            else:
                frames.pop()  # 纯括号组：操作数已在其上，透传
            continue
        if text == "]":
            if not frames or frames[-1]["kind"] != "index":
                raise ExpressionNormError(
                    f"第 {tok.line} 行：多余/失配的右方括号")
            frame = frames[-1]
            fold_to_frame()
            if len(out) <= frame["ops0"]:
                raise ExpressionNormError("下标缺表达式")
            idx = out.pop()
            node = ["[]", frame["base"], idx]
            if frame["range_seen"]:
                node = ["[]", frame["base"], frame["msb"], idx]
            frames.pop()
            out.append(node)
            continue
        if text == ",":
            if not frames or frames[-1]["kind"] != "call":
                raise ExpressionNormError(
                    f"第 {tok.line} 行：逗号在函数实参表外")
            fold_to_frame()
            frame = frames[-1]
            if len(out) <= frame["ops0"]:
                raise ExpressionNormError("函数实参表缺表达式")
            frame["args"].append(out.pop())
            expect_operand = True
            continue
        if text == ":":
            frame = frames[-1] if frames else None
            if frame is not None and frame["kind"] == "index" \
                    and not frame["range_seen"]:
                # 下标区间 a[m:n]：折叠到帧、暂存 msb
                fold_to_frame()
                if len(out) <= frame["ops0"]:
                    raise ExpressionNormError("下标区间缺上界")
                frame["msb"] = out.pop()
                frame["range_seen"] = True
                expect_operand = True
                continue
            # 三目 ?: ：折叠到 ？ 止（: 只换标不折叠——rhs 尚未读入）
            hit = False
            while ops:
                if ops[-1][0] == "?":
                    hit = True
                    break
                fold_top()
            if not hit:
                raise ExpressionNormError(f"第 {tok.line} 行：: 缺配对 ?")
            ops.pop()
            ops.append((":", _TERNARY_PREC, 3))
            expect_operand = True
            continue
        if text == "?":
            while len(ops) > floor() and ops[-1][1] > _TERNARY_PREC:
                fold_top()
            ops.append(("?", _TERNARY_PREC, 3))
            expect_operand = True
            continue
        prec_entry = PRECEDENCE.get(text)
        if prec_entry is None:
            raise ExpressionNormError(
                f"第 {tok.line} 行：表达式运算符 {text!r} "
                "不在优先级闭集（fail-closed 不猜）")
        prec, left_assoc = prec_entry
        while len(ops) > floor() and (
                ops[-1][1] > prec or (left_assoc and ops[-1][1] == prec)):
            fold_top()
        ops.append((text, prec, 2))
        expect_operand = True
        continue

    while ops:
        fold_top()
    if frames:
        raise ExpressionNormError("括号/调用失配（帧未闭合到表达式尾）")
    if len(out) != 1:
        raise ExpressionNormError(
            f"表达式归一歧义（栈余 {len(out)} 项）")
    return out[0]


# ── 解析器 ──────────────────────────────────────────────────────────────────


@dataclass
class _PendingPort:
    """模块头/体内端口声明中间态（方向回填）。"""

    name: str
    direction: str | None = None


@dataclass
class _VerilogAParser:
    """递归下降解析器（token 流 → Verilog-A 结构文档；fail-soft 警告面）。"""

    tokens: list[Token]
    pos: int = 0
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)
    module_order: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    disciplines: list[str] = field(default_factory=list)
    doc_attributes: list[str] = field(default_factory=list)
    pending_attributes: list[str] = field(default_factory=list)

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
            raise VerilogAParseError(
                f"第 {line} 行：期望 {text!r}，实得 {found!r}")
        return tok

    def warn(self, line: int, name: str, note: str) -> None:
        self.warnings.append({"line": line, "name": name, "note": note})

    # ── 捕获 ──
    def capture_until_semi(self) -> list[Token]:
        """捕获到深度 0 的 ``;`` 止（含括号配平；消费 ``;``；EOF 如实）。"""
        parts: list[Token] = []
        depth = 0
        while True:
            tok = self.peek()
            if tok is None:
                return parts
            if tok.kind == "punct":
                if tok.text in "([{":
                    depth += 1
                elif tok.text in ")]}":
                    if depth == 0:
                        return parts
                    depth -= 1
                elif depth == 0 and tok.text == ";":
                    self.next()
                    return parts
            parts.append(tok)
            self.next()

    def capture_balanced_paren(self) -> list[Token]:
        """``(...)`` 内 token 整捕获（括号配平；消费两侧括号；EOF 抛错）。"""
        self.expect_punct("(")
        parts: list[Token] = []
        depth = 1
        while depth > 0:
            tok = self.next()
            if tok is None:
                raise VerilogAParseError(
                    "括号体未闭合（EOF；第 "
                    f"{parts[-1].line if parts else 0} 行附近）")
            if tok.kind == "punct":
                if tok.text in "([{":
                    depth += 1
                elif tok.text in ")]}":
                    depth -= 1
                    if depth == 0:
                        return parts
            parts.append(tok)
        return parts

    def skip_balanced_keyword_block(self, open_kw: str, close_kw: str,
                                    line: int) -> None:
        """关键字配平跳块（discipline/enddiscipline 等登记面用）。"""
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

    # ── 顶层 ──
    def parse_document(self) -> None:
        """顶层循环：module 声明 + discipline/attribute/杂项。"""
        while True:
            tok = self.peek()
            if tok is None:
                return
            if tok.kind == "dir":
                self.next()
                continue
            if self.at_punct(_ATTR_OPEN):
                self._consume_attributes(target=None)
                continue
            if tok.kind == "id" and tok.text == "module":
                self.parse_module()
                continue
            if tok.kind == "id" and tok.text == "discipline":
                self.next()
                name_tok = self.next()
                dname = name_tok.text if name_tok and name_tok.kind == "id" \
                    else "<unnamed>"
                if dname not in self.disciplines:
                    self.disciplines.append(dname)
                self.skip_balanced_keyword_block(
                    "discipline", "enddiscipline", tok.line)
                continue
            if tok.kind == "id" and tok.text == "nature":
                self.next()
                self.skip_balanced_keyword_block("nature", "endnature",
                                                 tok.line)
                continue
            if tok.kind == "punct" and tok.text == ";":
                self.next()
                continue
            self.warn(tok.line, "skipped_top_level",
                      f"顶层散落构造 {tok.text!r}（结构子集外，跳过）")
            self.next()
            self.capture_until_semi()

    def _consume_attributes(self, target: dict[str, Any] | None) -> None:
        """``(* ... *)`` 属性注记整段消费（原文入 attributes 名录）。

        ``target=None`` → 暂存 pending（挂在下一个 module 上）；否则直挂
        宿主。多段连写逐段收录。
        """
        while self.at_punct(_ATTR_OPEN):
            self.next()  # '(*'
            parts: list[Token] = []
            while True:
                tok = self.peek()
                if tok is None:
                    self.warn(
                        parts[-1].line if parts else 0, "unterminated_attr",
                        "属性注记未闭合（*) 缺失，EOF 兜底）")
                    break
                if self.at_punct(_ATTR_CLOSE):
                    self.next()
                    break
                parts.append(tok)
                self.next()
            raw = _join_tokens(parts)
            if target is not None and "attributes" in target:
                target["attributes"].append(raw)
            else:
                self.pending_attributes.append(raw)

    # ── module ──
    def parse_module(self) -> None:
        """``[(* attrs *)] module name [(header_ports)] ;  body  endmodule``。"""
        self.next()  # 'module'
        name_tok = self.next()
        if name_tok is None or name_tok.kind != "id":
            raise VerilogAParseError(
                f"第 {name_tok.line if name_tok else 0} 行：module 缺名字")
        name = name_tok.text
        header_params_raw: str | None = None
        if self.at_punct("#"):
            self.next()
            body = self.capture_balanced_paren()
            header_params_raw = _join_tokens(body)
        body: dict[str, Any] = {
            "name": name,
            "ports": [],
            "nets": [],
            "params": [],
            "analog": {
                "stmt_counts": {c: 0 for c in STMT_CATEGORIES},
                "contributions": [],
                "events": [],
            },
            "attributes": list(self.pending_attributes),
        }
        self.pending_attributes = []
        pending: dict[str, _PendingPort] = {}
        if self.at_punct("("):
            self._parse_header_ports(body, pending)
        # ANSI 头已带方向 → 直接成 port 项；1995 头只列名（无方向痕迹）
        # → 由体内声明回填，此处不产半猜端口
        for pname, pend in pending.items():
            if pend.direction is not None and not any(
                    p["name"] == pname for p in body["ports"]):
                body["ports"].append(
                    {"dir": pend.direction, "name": pname})
        self.expect_punct(";")
        self._parse_module_body(body, pending)
        self.modules[name] = body
        self.module_order.append(name)
        _ = header_params_raw

    def _parse_header_ports(self, body: dict[str, Any],
                            pending: dict[str, _PendingPort]) -> None:
        """模块头端口表：``(a, b)`` 1995 形 与 ``(input a, output b)``
        ANSI 形 双态容忍（ANSI 痕迹=方向/类型/范围声明出现即挂方向）。"""
        self.expect_punct("(")
        cur_dir: str | None = None
        while True:
            tok = self.peek()
            if tok is None:
                raise VerilogAParseError("模块头端口表未闭合（EOF）")
            if self.at_punct(")"):
                self.next()
                return
            if tok.kind == "id" and tok.text in DIRECTIONS:
                cur_dir = tok.text
                self.next()
                continue
            if tok.kind == "id" and tok.text in KNOWN_NET_TYPES:
                self.next()
                continue
            if self.at_punct(","):
                self.next()
                continue
            if tok.kind == "id":
                pname = self.next().text
                if pname not in pending:
                    pending[pname] = _PendingPort(pname, cur_dir)
                elif cur_dir is not None:
                    pending[pname].direction = cur_dir
                if self.at_punct("="):  # ANSI 缺省值（罕见）随声明消费
                    self.next()
                    self.capture_until_semi()
                continue
            self.warn(tok.line, "skipped_header_token",
                      f"端口表内散落 token {tok.text!r}（跳过）")
            self.next()

    def _parse_module_body(self, body: dict[str, Any],
                           pending: dict[str, _PendingPort]) -> None:
        """模块体主循环（1995 端口方向声明回填在本循环；endmodule 缺失
        fail-soft warning 不拒）。"""
        while True:
            tok = self.peek()
            if tok is None:
                self.warn(
                    self.tokens[-1].line if self.tokens else 0,
                    "unterminated_module",
                    f"模块 {body['name']} 未闭合（endmodule 缺失，EOF 兜底）")
                return
            if self.at_punct(_ATTR_OPEN):
                self._consume_attributes(target=body)
                continue
            if tok.kind == "punct" and tok.text == ";":
                self.next()
                continue
            if tok.kind == "id" and tok.text == "endmodule":
                self.next()
                return
            if tok.kind == "id" and tok.text in DIRECTIONS:
                self._parse_direction_decl(body, pending)
                continue
            if tok.kind == "id" and tok.text in KNOWN_NET_TYPES:
                self._parse_net_decl(body, tok.text)
                continue
            if tok.kind == "id" and tok.text in ("parameter", "localparam"):
                self._parse_param_decl(body)
                continue
            if tok.kind == "id" and tok.text == "analog":
                self.next()
                self._parse_analog(body)
                continue
            if tok.kind == "id" and tok.text == "discipline":
                self.next()
                name_tok = self.next()
                dname = name_tok.text if name_tok and name_tok.kind == "id" \
                    else "<unnamed>"
                if dname not in self.disciplines:
                    self.disciplines.append(dname)
                self.skip_balanced_keyword_block(
                    "discipline", "enddiscipline", tok.line)
                continue
            # 未知类型标识符开头的网声明形态容忍（discipline 使用面宽）
            if tok.kind == "id" and self._looks_like_net_decl():
                self._parse_net_decl(body, tok.text, unknown_type=True)
                continue
            self.warn(tok.line, "skipped_module_stmt",
                      f"模块体散落构造 {tok.text!r}（结构子集外，跳语句）")
            self.next()
            self.capture_until_semi()

    def _looks_like_net_decl(self) -> bool:
        """``IDENT name[, name]* ;`` 网声明形态探测（两 id + 终止）。"""
        t1 = self.peek(1)
        if t1 is None or t1.kind != "id":
            return False
        t2 = self.peek(2)
        if t2 is None:
            return False
        return (t2.kind == "punct" and t2.text in (",", ";")) or (
            t2.kind == "id")

    def _parse_direction_decl(self, body: dict[str, Any],
                              pending: dict[str, _PendingPort]) -> None:
        """体内方向声明：``input a, b ;``（可选跟随 net 类型词）。"""
        dir_tok = self.next()
        direction = dir_tok.text
        if self.at_id() and self.peek().text in KNOWN_NET_TYPES:
            self.next()
        names: list[str] = []
        while True:
            if self.at_id():
                pname = self.next().text
                names.append(pname)
                pend = pending.get(pname)
                if pend is None:
                    pending[pname] = _PendingPort(pname, direction)
                else:
                    pend.direction = direction
            elif self.at_punct(","):
                self.next()
                continue
            else:
                break
        self.eat_punct(";")
        existing = {p["name"] for p in body["ports"]}
        for pname in names:
            if pname not in existing:
                body["ports"].append(
                    {"dir": pending[pname].direction, "name": pname})

    def _parse_net_decl(self, body: dict[str, Any], type_name: str,
                        *, unknown_type: bool = False) -> None:
        """网/节点声明：``electrical p, n ;``（同型多名一桶；未知类型
        如实登记+温和警告）。"""
        line = self.next().line  # 类型标识符
        if self.at_punct("["):  # 网范围（结构子集不记——已知限制如实）
            self.next()
            while True:
                tok = self.peek()
                if tok is None or (tok.kind == "punct" and tok.text == "]"):
                    break
                self.next()
            self.eat_punct("]")
        if unknown_type:
            self.warn(line, "unknown_net_type",
                      f"网类型 {type_name!r} 不在已知词表（discipline 使用"
                      "面——如实登记不展开）")
        names: list[str] = []
        while True:
            if self.at_id():
                names.append(self.next().text)
            elif self.at_punct(","):
                self.next()
                continue
            else:
                break
        self.eat_punct(";")
        if names:
            body["nets"].append({"type": type_name, "names": names})

    def _parse_param_decl(self, body: dict[str, Any]) -> None:
        """参数声明：``parameter real R = 50 from [0:inf) [, ...] ;``"""
        kw_tok = self.next()  # parameter/localparam
        ptype: str | None = None
        if self.at_id() and self.peek().text in PARAM_TYPES:
            ptype = self.next().text
        while True:
            if not self.at_id():
                break
            pname = self.next().text
            default_raw: str | None = None
            default: int | float | None = None
            range_info: dict[str, Any] | None = None
            extra_raw: str | None = None
            if self.eat_punct("="):
                dtoks: list[Token] = []
                depth = 0
                while True:
                    tok = self.peek()
                    if tok is None:
                        break
                    if tok.kind == "punct":
                        if tok.text in "([{":
                            depth += 1
                        elif tok.text in ")]}":
                            depth -= 1
                        elif depth == 0 and tok.text in (",", ";"):
                            break
                    elif tok.kind == "id" and depth == 0 \
                            and tok.text == "from":
                        break
                    dtoks.append(tok)
                    self.next()
                default_raw = _join_tokens(dtoks)
                if len(dtoks) == 1 and dtoks[0].kind == "num":
                    default = parse_number_literal(dtoks[0].text)
            if self.at_id() and self.peek().text == "from":
                self.next()
                range_info = self._parse_range()
            rest: list[Token] = []
            while True:
                tok = self.peek()
                if tok is None or (tok.kind == "punct"
                                   and tok.text in (",", ";")):
                    break
                rest.append(tok)
                self.next()
            if rest:
                extra_raw = _join_tokens(rest)
            body["params"].append({
                "name": pname, "type": ptype,
                "default_raw": default_raw, "default": default,
                "range": range_info, "extra_raw": extra_raw,
            })
            if not self.eat_punct(","):
                break
        self.eat_punct(";")
        _ = kw_tok

    def _parse_range(self) -> dict[str, Any] | None:
        """``from`` 范围约束结构化保存（开闭区间不解释）。

        ``[a:b]``/``[a:b)``/``(a:b]``/``(a:b)`` 四形态；缺右端（``[a:``）
        fail-soft 如实半开。返回 ``{"raw", "low", "high",
        "low_inclusive", "high_inclusive"}``。
        """
        tok = self.peek()
        if tok is None or tok.kind != "punct" or tok.text not in ("[", "("):
            self.warn(tok.line if tok else 0, "malformed_range",
                      "from 后缺区间开括号（跳过）")
            return None
        low_inclusive = tok.text == "["
        self.next()
        low_toks: list[Token] = []
        high_toks: list[Token] = []
        side_low = True
        while True:
            t = self.peek()
            if t is None:
                break
            if t.kind == "punct" and t.text == ":":
                self.next()
                side_low = False
                continue
            if t.kind == "punct" and t.text in ("]", ")"):
                high_inclusive = t.text == "]"
                self.next()
                return {
                    "raw": (
                        ("[" if low_inclusive else "(")
                        + _join_tokens(low_toks) + ":"
                        + _join_tokens(high_toks)
                        + ("]" if high_inclusive else ")")),
                    "low": _join_tokens(low_toks),
                    "high": _join_tokens(high_toks),
                    "low_inclusive": low_inclusive,
                    "high_inclusive": high_inclusive,
                }
            (low_toks if side_low else high_toks).append(t)
            self.next()
        self.warn(low_toks[-1].line if low_toks else 0, "unterminated_range",
                  "范围区间未闭合（EOF 兜底）")
        return None

    # ── analog 行为块 ──
    def _parse_analog(self, body: dict[str, Any]) -> None:
        """analog 块入口：单语句/``function`` 声明/``begin..end`` 块。"""
        analog = body["analog"]
        if self.at_id() and self.peek().text == "function":
            fn_tok = self.next()
            name_tok = self.next()
            fname = name_tok.text if name_tok and name_tok.kind == "id" \
                else "<unnamed>"
            self.skip_balanced_keyword_block("function", "endfunction",
                                             fn_tok.line)
            self.warn(fn_tok.line, "analog_function_skipped",
                      f"analog function {fname!r} 声明面登记、函数体语义"
                      "不解析（结构子集外）")
            return
        self._parse_analog_stmt(analog, in_block=False, depth=0)
        # stray end：analog 顶层只允许一条语句——块闭合后的多余 ``end``
        # 在 analog 面如实告警消费（否则落到模块面变 skipped_module_stmt）
        while self.at_id() and self.peek().text == "end":
            stray = self.next()
            self.warn(stray.line, "stray_end",
                      "多余 end（analog 语句已闭合——配平失衡如实）")

    def _parse_analog_stmt(self, analog: dict[str, Any], *,
                           in_block: bool, depth: int) -> bool:
        """单条 analog 语句/块解析。返回 True=消费了配对 ``end``。

        分类口径：``<+`` → contribution；``if/else/for/while`` → 控制
        （``for (...)`` 头整捕获）；``@(...)`` → event（宿主语句照常
        分类）；``ID ( ... )`` 完整形态 → function_call；含裸 ``=`` →
        assignment；其余 → other。``begin..end`` 配平计数，失衡 fail-soft。
        """
        if depth > MAX_BLOCK_DEPTH:
            raise VerilogAParseError(
                f"第 {self.peek().line if self.peek() else 0} 行：analog "
                f"块嵌套超过深度守卫 {MAX_BLOCK_DEPTH}（fail-closed）")
        tok = self.peek()
        if tok is None:
            if in_block:
                self.warn(
                    self.tokens[-1].line if self.tokens else 0,
                    "unterminated_block", "begin 块未闭合（end 缺失，EOF）")
            else:
                self.warn(
                    self.tokens[-1].line if self.tokens else 0,
                    "truncated_analog", "analog 块截断（EOF 兜底）")
            return False
        counts = analog["stmt_counts"]
        if self.at_punct(";"):
            self.next()
            return False
        if tok.kind == "id" and tok.text == "end":
            self.next()
            if not in_block:
                self.warn(tok.line, "stray_end",
                          "多余 end（begin 缺失——配平失衡如实）")
            return True
        if tok.kind == "id" and tok.text == "begin":
            self.next()
            counts["block"] += 1
            while True:
                nxt = self.peek()
                if nxt is not None and nxt.kind == "id" \
                        and nxt.text == "endmodule":
                    # 模块终结符出现在未闭合块内：如实告警、不消费
                    # （留给模块面收口——否则被当 other 语句吞掉）
                    self.warn(nxt.line, "unterminated_block",
                              "begin 块未闭合即遇 endmodule（fail-soft）")
                    break
                ended = self._parse_analog_stmt(
                    analog, in_block=True, depth=depth + 1)
                if ended:
                    break
                if self.peek() is None:
                    break  # EOF 警告已由内层如实登记
            return False
        if tok.kind == "id" and tok.text in ("if", "for", "while"):
            self.next()
            counts[tok.text] += 1
            if self.at_punct("("):
                self.capture_balanced_paren()  # 控制头整捕获（含 for 头 ;）
            self._parse_analog_stmt(analog, in_block=False, depth=depth + 1)
            if tok.text == "if" and self.at_id() and self.peek().text == "else":
                self.next()
                counts["else"] += 1
                self._parse_analog_stmt(
                    analog, in_block=False, depth=depth + 1)
            return False
        if self.at_punct("@"):
            self.next()
            self._parse_event(analog)
            self._parse_analog_stmt(analog, in_block=False, depth=depth + 1)
            return False
        # 简单语句：到深度 0 ``;`` 止
        stmt = self.capture_until_semi()
        self._classify_simple_stmt(analog, stmt)
        return False

    def _parse_event(self, analog: dict[str, Any]) -> None:
        """``@(name)`` / ``@(name(args))`` 事件句法登记（参数原文）。"""
        counts = analog["stmt_counts"]
        if not self.at_punct("("):
            tok = self.peek()
            self.warn(tok.line if tok else 0, "malformed_event",
                      "@ 后缺事件括号（跳过）")
            return
        self.next()  # '('
        name_tok = self.next()
        ename = name_tok.text if name_tok and name_tok.kind == "id" \
            else "<unnamed>"
        args_raw: str | None = None
        if self.at_punct("("):
            args_raw = _render_access(self.capture_balanced_paren())
        close = self.peek()
        if close is not None and self.at_punct(")"):
            self.next()
        else:
            self.warn(
                close.line if close else 0, "malformed_event",
                f"事件 {ename!r} 括号失配（EOF/异形兜底）")
        analog["events"].append({"name": ename, "args_raw": args_raw})
        counts["event"] += 1

    def _classify_simple_stmt(self, analog: dict[str, Any],
                              stmt: list[Token]) -> None:
        """简单语句分类：contribution/function_call/assignment/other。"""
        counts = analog["stmt_counts"]
        contrib_idx = next(
            (k for k, t in enumerate(stmt)
             if t.kind == "punct" and t.text == "<+"), None)
        if contrib_idx is not None:
            counts["contribution"] += 1
            lhs = _render_access(stmt[:contrib_idx])
            rhs_toks = stmt[contrib_idx + 1:]
            try:
                tree = expr_to_prefix(rhs_toks)
            except ExpressionNormError as exc:
                self.warn(
                    stmt[contrib_idx].line, "expr_normalize_failed",
                    f"贡献 {lhs!r} RHS 归一失败（原文保留）：{exc}")
                analog["contributions"].append({
                    "lhs": lhs, "rhs_prefix_tree": None,
                    "rhs_raw": _join_tokens(rhs_toks),
                })
                return
            analog["contributions"].append(
                {"lhs": lhs, "rhs_prefix_tree": tree})
            return
        if stmt and stmt[0].kind in ("id", "sys") and len(stmt) >= 3 \
                and stmt[1].kind == "punct" and stmt[1].text == "(" \
                and stmt[-1].kind == "punct" and stmt[-1].text == ")":
            counts["function_call"] += 1
            return
        if any(t.kind == "punct" and t.text == "=" for t in stmt):
            counts["assignment"] += 1
            return
        counts["other"] += 1


# ── 文档级入口 ──────────────────────────────────────────────────────────────


def parse_veriloga(text: str) -> dict[str, Any]:
    """Verilog-A 文本 → 结构化文档（modules/参数/analog 三面）。

    返回 schema 见模块 docstring。空文本抛 :class:`VerilogAParseError`；
    词法错误（注释/字符串未闭合、坏字符、深嵌套）致命；结构松散处
    fail-soft（warnings 带行号如实披露后继续——endmodule 缺失不拒）。
    """
    if not text.strip():
        raise VerilogAParseError("空文件（无任何内容）——拒绝解析")
    parser = _VerilogAParser(tokenize_veriloga(text))
    parser.parse_document()
    modules = parser.modules
    stats = {
        "n_modules": len(modules),
        "n_ports": sum(len(m["ports"]) for m in modules.values()),
        "n_nets": sum(
            len(m["nets"]) + sum(len(n["names"]) for n in m["nets"])
            for m in modules.values()),
        "n_params": sum(len(m["params"]) for m in modules.values()),
        "n_contributions": sum(
            len(m["analog"]["contributions"]) for m in modules.values()),
        "n_events": sum(
            len(m["analog"]["events"]) for m in modules.values()),
        "n_warnings": len(parser.warnings),
    }
    return {
        "schema_version": PARSER_SCHEMA_VERSION,
        "modules": modules,
        "module_order": parser.module_order,
        "disciplines": parser.disciplines,
        "attributes": parser.doc_attributes,
        "warnings": parser.warnings,
        "stats": stats,
    }


# ── 查询三函数 ──────────────────────────────────────────────────────────────


def veriloga_module_summary(doc: dict[str, Any],
                            module_name: str) -> dict[str, Any]:
    """单模块汇总视图（module 不存在抛 KeyError 带可用名录——消费方不猜）。

    返回 ``{"module", "ports", "n_ports", "nets", "n_nets", "params",
    "n_params", "stmt_counts", "contributions", "n_contributions",
    "events", "attributes"}``。
    """
    body = doc["modules"].get(module_name)
    if body is None:
        raise KeyError(
            f"模块 {module_name!r} 不存在"
            f"（可用: {', '.join(doc.get('module_order') or []) or '无'}）")
    analog = body["analog"]
    return {
        "module": module_name,
        "ports": [dict(p) for p in body["ports"]],
        "n_ports": len(body["ports"]),
        "nets": [dict(n) for n in body["nets"]],
        "n_nets": sum(len(n["names"]) for n in body["nets"]),
        "params": [dict(p) for p in body["params"]],
        "n_params": len(body["params"]),
        "stmt_counts": dict(analog["stmt_counts"]),
        "contributions": [dict(c) for c in analog["contributions"]],
        "n_contributions": len(analog["contributions"]),
        "events": [dict(e) for e in analog["events"]],
        "attributes": list(body["attributes"]),
    }


def veriloga_param_table(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """全模块参数平坦表（``module`` 列归属 + 名/类型/缺省/范围逐键）。"""
    rows: list[dict[str, Any]] = []
    for mname in doc["module_order"]:
        for p in doc["modules"][mname]["params"]:
            row = {"module": mname, **{k: p[k] for k in
                                       ("name", "type", "default_raw",
                                        "default", "range", "extra_raw")}}
            rows.append(row)
    return rows


def veriloga_contribution_pairs(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """全部贡献对平坦清单（``{module, lhs, rhs_prefix_tree}``——行为模型
    端口 I-V 关系的结构化入口；RHS 归一失败条目树如实 None）。"""
    pairs: list[dict[str, Any]] = []
    for mname in doc["module_order"]:
        for c in doc["modules"][mname]["analog"]["contributions"]:
            pairs.append({
                "module": mname,
                "lhs": c["lhs"],
                "rhs_prefix_tree": c["rhs_prefix_tree"],
            })
    return pairs
