"""SKILL/OCEAN 源码 S-expression 结构化解析内核（aurora_q 席位 Q-X62，2026-11-08）。

模拟 EDA 自动化脚本生态核心语言 SKILL（Cadence Virtuoso 的 Lisp 方言）与
OCEAN（SKILL 超集+仿真命令面：analysis/sweep/ocnXxx/asi/sim/netlist 前缀
家族）的**只读结构化解析**——脚本静态分析、API 调用清单提取、define/defun
盘点、全局赋值面盘点（Virtuoso-Bridge-lite 借鉴化用方向的解析面；生成方向
见 :mod:`rfauto.core.skill_template_engine` Q-X32，两模块互不依赖）。词法、
S 表达式文法与结构提取全部在 core 确定性内核（铁律 7：零物理数字、零求值
副作用——本模块只读静态分析，**永不执行**被解析代码）。服务包装见
:mod:`rfauto.service.skill_service`（规则 4 JSON 进出；Q-X62 加性节），CLI
薄壳见 cli/domains/skill_parse.py（独立 typer 根，citi/gdsii/sdf 同款孤儿
域，接线待主代理合流）。

两层结构（sdf_parser Q-X61 的 S 表达式同代分层）：

1. 词法+S 表达式层（:func:`parse_skill`）——正则词法（全字符覆盖兜底）+
   栈式解析（迭代零递归）为 :class:`Symbol`/:class:`LispList`/
   :class:`LispVector`/:class:`Quote`/Python 原生 ``int|float|str`` 节点树
   （节点可判等可哈希；Symbol/LispList/LispVector/Quote 的 ``line`` 不参与
   判等——同名同形节点跨行等值）：

   - 注释：``;`` 行注释 + ``/* ... */`` 块注释（可跨行；内含括号/引号不
     影响配平；未闭合=致命）；
   - 字符串 ``"..."``（``\\"``/``\\\\``/``\\n``/``\\t``/``\\r`` 转义解开；
     未知转义序列如实保留反斜杠+字符原文；未闭合=致命）；
   - 数字：整数/浮点/科学计数（``1``/``1.5``/``.5``/``-2``/``3e4``/
     ``2.5e-10``），解析为 Python 原生 ``int``（优先）/``float`` 值；数字
     后紧跟 ``+``/``-``/``.``/字母时按符号如实 token 化（SKILL ``1+``/
     ``1-`` 函数名形态）；
   - 符号：``[A-Za-z0-9+-_!?<>*=.&]``+``/``（后跟 ``*`` 除外——那是块
     注释）组合；``?kw`` 关键字参数符号、``1+`` 函数名符号同字符集自然
     覆盖；``&`` 为任务书字母表的最小超集扩展（SKILL defun 定义符
     ``&optional``/``&rest``/``&key`` 形态必需，Q-X62 偏差项如实记录）；
     ``|...|`` 转义符号名（单行，内容逐字保留）；词法闭集外字符（``%``/
     反斜杠等）→ 致命（异名走 ``|...|`` 形态）；
   - **``f(`` 函数调用糖**（SKILL 语言读取器口径：符号与左括号紧邻即绑
     定）：``f(x)`` ≡ ``(f x)``——符号后**零字符间隔**紧跟 ``(`` 时，该
     符号折叠为紧随表的头部（``defun( f (x) …)`` ≡ ``(defun f (x) …)``，
     Cadence 例程的主流书写形态；冒烟实证：无此糖则 defun 盘点全空=
     解析器对真实 SKILL 语料失灵）；符号与 ``(`` 间有空白则两独立形态
     （``f (x)`` = 符号 f + 表 ``(x)``）；方括号不折叠（``x[1]`` 的数组
     下标糖不实现——向量字面量独立形态，已知限制如实）；
   - 前缀语法糖：``'x`` =quote、`` `x `` =quasiquote、``,x`` =unquote、
     ``,@x`` =unquote-splicing——**如实 token 化为 :class:`Quote` 包装，
     不展开、不求值**（糖绑定的对象=紧随的**下一个完整节点**：表形态
     整表包装——``'(1 2)`` 的 quote 不落表内首原子；quasiquote 模板静态
     保留原文，``,``/``,@ 子形态不求值）；悬挂糖（``'`` 后无表达式）=
     致命；
   - 向量字面量 ``[...]`` → :class:`LispVector`（与括号表类型区分；
     方/圆括号交叉失配=致命）；
   - 深度守卫 :data:`MAX_NEST_DEPTH` =512（括号+向量统一计数，病态深嵌套
     fail-closed）；零进展守卫（#208 家法：词法循环每轮必须消耗至少 1
     字符，防正则意外失配静默死循环）；
   - 括号失配（多余右括号/未闭合左括号/交叉失配）、引号串·块注释·转义
     符号未闭合、悬挂前缀糖、无法识别的字符 → :class:`SkillParseError`
     （ValueError 子类，带 1 基行号+列号属性）。

2. 结构提取层（静态分析不执行；**引号数据整树视为数据**——Quote 包装与
   ``(quote …)`` 显式形的子树不计定义/赋值/调用；绑定形态如实剪除：
   lambda/nlambda/defun 参数表、define 函数头签名、let 族绑定表变量位、
   setf/setq 目标位、foreach/for 循环变量、case 族分支模式位一律不计调用）：

   - :func:`skill_definitions`：``define``/``defun`` 清单（name/args/
     arity/style；define 双形态=值形态 ``(define name (lambda …))`` 与
     函数头形态 ``(define (name args) body)``；args 按原文如实含
     ``&optional``/``&rest`` 等标记符，arity=清单长度）；重复定义双列
     +warning；
   - :func:`skill_top_level_forms`：顶层形态分类计数（definition/special/
     call/expr/vector/quote/atom 闭集 + 逐头符号频次）；
   - :func:`skill_api_calls`：被调函数名频次+前缀桶分类（桶表闭集
     :data:`API_PREFIX_BUCKETS`：ocn/asi/sim/netlist/vms=ocean 桶、hi/ge/
     le/db=virtuoso 桶、其余=generic、头位置非符号=unknown 桶如实）+调用
     点顶层形态序号（form_index）+行号；特形（:data:`SPECIAL_FORMS` 闭集）
     头不计调用（语言构造非 API），其子表照常遍历；
   - :func:`skill_globals`：``setf``/``setq`` 赋值目标+作用域深度（目标
     符号名如实；目标为表达式形态（如 ``(car x)``）时 target_kind=expr+
     原文渲染；``setq`` 多对连写逐对展开；depth=0 为顶层直接赋值）；
   - :func:`skill_call_edges`：静态调用边（define→calls **只按符号名匹配
     同名 define**——无词法作用域分析，调用归属最近包围定义，递归=
     caller==callee 边如实；被调名无同名定义归 external 如实）；
   - :func:`skill_literal_eval`：**只读求值面（受限）**——仅纯字面量表达
     式（数字算术 ``+ - * /``、``quote``、``list``/``append``/``cons``、
     字符串 ``strcat``）；符号引用/未知函数/空表/向量/quasiquote 族 →
     :class:`SkillEvalError`（ValueError 子类）**fail-closed 不猜**。
     ``/`` 恒 Python 真除（float）；除零也是 SkillEvalError。

确定性（同输入同输出）、零 IO（纯文本进出）、零第三方依赖。遍历与平面
化全部迭代实现（零递归）。本模块不设 ``__all__``（无 __all__ 的非门面
文件不进 tests/gold/public_api.json——sdf_parser/verilog_netlist_parser
同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位；service 信封引用）。
PARSER_SCHEMA_VERSION = "1.0"

#: 括号/向量嵌套深度上限（病态深嵌套 fail-closed；真实 SKILL 嵌套 <20）。
MAX_NEST_DEPTH = 512

#: SKILL 特形闭集（任务书逐字闭集——结构提取层按此判定"语言构造头 vs
#: API 调用头"；SKILL 语法 case 敏感，本表精确小写匹配）。
SPECIAL_FORMS = frozenset({
    "quote", "let", "let*", "lambda", "nlambda", "define", "defun",
    "prog", "prog*", "cond", "if", "when", "unless", "and", "or",
    "case", "caseq", "foreach", "for", "setf", "setq",
    "function", "funcall", "apply",
})

#: API 前缀桶表（闭集）：桶名 → 前缀族。ocean=OCEAN 仿真命令面家族
#: （ocnXxx/asi/sim/netlist/vms），virtuoso=Virtuoso 图形/数据库 API
#: （hi/ge/le/db）。其余前缀=generic，头位置非符号=unknown（如实）。
API_PREFIX_BUCKETS: dict[str, tuple[str, ...]] = {
    "ocean": ("ocn", "asi", "sim", "netlist", "vms"),
    "virtuoso": ("hi", "ge", "le", "db"),
}

#: 桶名闭集（公开只读视图；by_bucket 计数恒含全四键，缺席=0）。
API_BUCKETS: tuple[str, ...] = ("ocean", "virtuoso", "generic", "unknown")

#: 顶层形态分类闭集。
TOP_LEVEL_CATEGORIES: tuple[str, ...] = (
    "definition", "special", "call", "expr", "vector", "quote", "atom",
)

_PLAIN_SYM_RE = re.compile(r"(?:[A-Za-z0-9+\-_!?<>*=.&]|/(?!\*))+")
#: 字符串转义：已知五形态解开，未知形态保留反斜杠原文（fail-soft 不猜）。
_STR_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
_STR_ESCAPE_RE = re.compile(r"\\(.)", re.DOTALL)
_QUOTE_PREFIXES = {"quote": "'", "quasiquote": "`",
                   "unquote": ",", "unquote-splicing": ",@"}
#: 词元正则（全字符覆盖：空白/换行/两形态注释/括号/方括号/引号串/转义符号/
#: 前缀糖/数字/符号；坏注释与坏引号串与坏转义符号作为兜底分支命中即致命）。
#: 符号内 ``/`` 仅在不起块注释时并入（``/(?!\*）``）；数字后跟 ``+-``/``.``/
#: 字母时按符号 token 化（SKILL ``1+``/``1-`` 函数名形态）。
_TOKEN_RE = re.compile(
    r"""
    (?P<ws>[^\S\n]+)
    |(?P<nl>\n)
    |(?P<lcomment>;[^\n]*)
    |(?P<bcomment>/\*.*?\*/)
    |(?P<bad_bcomment>/\*)
    |(?P<lp>\()
    |(?P<rp>\))
    |(?P<lbrk>\[)
    |(?P<rbrk>\])
    |(?P<qstr>"(?:\\.|[^"\\])*")
    |(?P<bad_qstr>")
    |(?P<vsym>\|[^|\n]*\|)
    |(?P<bad_vsym>\|)
    |(?P<unqs>,@)
    |(?P<unq>,)
    |(?P<qq>`)
    |(?P<quote>')
    |(?P<num>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?![\w.+\-]))
    |(?P<sym>(?:[A-Za-z0-9+\-_!?<>*=.&]|/(?!\*))+)
    """,
    re.VERBOSE | re.DOTALL,
)


class SkillParseError(ValueError):
    """SKILL 词法/括号结构违规（ValueError 子类，带行号+列号）。

    覆盖：括号失配（含方括号/圆括号交叉失配）、引号串/块注释/转义符号
    未闭合、嵌套深度越限、悬挂前缀糖、无法识别的字符。``line``/
    ``column`` 属性为 1 基（无法定位时 None）。
    """

    def __init__(self, message: str, *, line: int | None = None,
                 column: int | None = None) -> None:
        super().__init__(message)
        self.line = line
        self.column = column


class SkillEvalError(ValueError):
    """字面量求值面 fail-closed（非纯字面量/符号引用/未知函数——不猜）。"""


# ─── 节点树 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Symbol:
    """符号节点：name=符号名（``|...|`` 转义符号为去栏原文）。

    判等/哈希只看 name（跨行同名符号等值——调用图/定义匹配的静态按名
    口径）；line 仅定位展示。
    """

    name: str
    line: int = field(default=0, compare=False)


@dataclass(frozen=True, slots=True)
class LispList:
    """括号表：items=有序子节点（元组化保证可哈希）+左括号行号。"""

    items: tuple[SkillNode, ...]
    line: int = field(default=0, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True, slots=True)
class LispVector:
    """方括号字面向量：items=有序子节点（与括号表类型区分）。"""

    items: tuple[SkillNode, ...]
    line: int = field(default=0, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True, slots=True)
class Quote:
    """前缀语法糖包装（如实 token 化，不展开）。

    kind ∈ quote（``'``）/ quasiquote（`` ` ``）/ unquote（``,``）/
    unquote-splicing（``,@``）；quasiquote 模板静态保留原文。
    """

    item: SkillNode
    kind: str = "quote"
    line: int = field(default=0, compare=False)


#: 节点树统一类型（Symbol|int|float|str|LispList|LispVector|Quote）。
SkillNode = Symbol | int | float | str | LispList | LispVector | Quote


# ─── 词法+S 表达式层 ───────────────────────────────────────────────────────


@dataclass(slots=True)
class _Frame:
    """开容器栈帧：kind=list|vector + 已收子节点 + 开括号行列（1 基）。

    ``head``：``f(`` 调用糖折叠的表头（紧邻符号零间隔后随 ``(`` 时置位；
    闭表时前插进 items）。``prefix``：开括号时**认领**的前缀糖（' / ` / ,
    / ,@——糖绑定的下一完整节点=本表），闭表时整表包装；认领后全局待
    栈清空，内层结构与原子只见帧内新挂的糖（``'(1 (x 2))`` 的 quote 包
    外层表、不落内层表）。
    """

    kind: str
    items: list[SkillNode]
    line: int
    col: int
    head: Symbol | None = None
    prefix: list[tuple[str, int, int]] = field(default_factory=list)


def _decode_string(body: str) -> str:
    """引号串体解转义：已知五形态（\\n \\t \\r \\" \\\\）解开，未知形态
    保留反斜杠+字符原文（fail-soft 不猜）。"""
    return _STR_ESCAPE_RE.sub(
        lambda m: _STR_ESCAPES.get(m.group(1), "\\" + m.group(1)), body)


def _int_or_float(token: str) -> int | float:
    """数字词元 → Python 值（int 优先，其余 float；正则已保形）。"""
    try:
        return int(token)
    except ValueError:
        return float(token)


def _symbol_source(name: str) -> str:
    """符号 → 源文形态（不满足裸符号字符集的名字按 ``|...|`` 形态回写）。"""
    return name if _PLAIN_SYM_RE.fullmatch(name) else f"|{name}|"


def _advance_line(token: str, line: int, pos: int) -> tuple[int, int]:
    """多行词元消费后的（行号, 行首绝对偏移）——供行号/列号跟踪。"""
    newlines = token.count("\n")
    if not newlines:
        return line, -1
    return (line + newlines,
            pos - (len(token) - token.rfind("\n") - 1))


def _wrap_suffix(
    node: SkillNode, pending: list[tuple[str, int, int]]
) -> SkillNode:
    """原子绑定：全部待挂糖（帧内新挂、等待下一节点的）逆序包装本原子
    （后见者内层）并清空待栈。"""
    for kind, m_line, _col in reversed(pending):
        node = Quote(item=node, kind=kind, line=m_line)
    pending.clear()
    return node


def _wrap_prefix(
    node: SkillNode, prefix: list[tuple[str, int, int]]
) -> SkillNode:
    """闭表绑定：开括号时认领的糖（帧.prefix）逆序整表包装本表。"""
    for kind, m_line, _col in reversed(prefix):
        node = Quote(item=node, kind=kind, line=m_line)
    prefix.clear()
    return node


def parse_skill(
    text: str, *, max_depth: int = MAX_NEST_DEPTH
) -> list[SkillNode]:
    """SKILL 源文本 → 顶层节点树（栈式迭代零递归；纯函数零 IO）。

    ``max_depth``：括号+向量嵌套深度上限（缺省 :data:`MAX_NEST_DEPTH`）；
    越限、括号失配、引号串/块注释/转义符号未闭合、悬挂前缀糖一律抛
    :class:`SkillParseError`。空文本/纯注释文本返回空表（service 层
    fail-closed 判空）。
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    roots: list[SkillNode] = []
    stack: list[_Frame] = []
    #: 前缀糖待应用栈：(kind, line, col)；应用到下一个完成的节点。
    pending: list[tuple[str, int, int]] = []
    #: ``f(`` 调用糖待挂头部（符号后零间隔紧跟 ``(`` 时置位）。
    sugar_head: Symbol | None = None
    pos, n, line, line_start = 0, len(text), 1, 0
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        # 零进展守卫（#208 家法）：正则意外失配/零长匹配即致命，不静默循环
        if m is None or m.end() == pos:
            col = pos - line_start + 1
            raise SkillParseError(
                f"第 {line} 行第 {col} 列：无法识别的字符 {text[pos]!r}"
                "（词法闭集外——异名用 |...| 转义符号形态）",
                line=line, column=col)
        kind = m.lastgroup
        token = m.group()
        col = pos - line_start + 1
        pos = m.end()
        frame = stack[-1] if stack else None
        container = frame.items if frame is not None else roots
        if kind == "nl":
            line += 1
            line_start = pos
            continue
        if kind in ("ws", "lcomment"):
            continue
        if kind == "bcomment":
            new_line, new_start = _advance_line(token, line, pos)
            line, line_start = (line, line_start) if new_start < 0 \
                else (new_line, new_start)
            continue
        if kind == "lp" or kind == "lbrk":
            if len(stack) >= max_depth:
                raise SkillParseError(
                    f"第 {line} 行第 {col} 列：括号/向量嵌套深度超过上限"
                    f" {max_depth}（病态深嵌套 fail-closed）",
                    line=line, column=col)
            frame = _Frame(
                kind="list" if kind == "lp" else "vector",
                items=[], line=line, col=col,
                prefix=list(pending))
            pending.clear()  # 认领：糖绑定的下一完整节点=本表（quote 包整表）
            if kind == "lp" and sugar_head is not None:
                frame.head = sugar_head
                sugar_head = None
            stack.append(frame)
            continue
        if kind == "rp" or kind == "rbrk":
            want = "list" if kind == "rp" else "vector"
            if not stack:
                if pending:
                    p_line, p_col = pending[-1][1], pending[-1][2]
                    raise SkillParseError(
                        f"第 {p_line} 行第 {p_col} 列：前缀语法糖"
                        f"（{pending[-1][0]}）缺被引用表达式"
                        "（悬挂 ' / ` / , / ,@）",
                        line=p_line, column=p_col)
                raise SkillParseError(
                    f"第 {line} 行第 {col} 列：多余的"
                    f"{'右括号 )' if kind == 'rp' else '右方括号 ]'}（括号失配）",
                    line=line, column=col)
            if stack[-1].kind != want:
                opener = "( 表" if stack[-1].kind == "list" else "[ 向量"
                closer = ")" if kind == "rp" else "]"
                raise SkillParseError(
                    f"第 {line} 行第 {col} 列：{closer} 关闭的是第 "
                    f"{stack[-1].line} 行第 {stack[-1].col} 列起的{opener}"
                    "（括号交叉失配）",
                    line=line, column=col)
            done = stack.pop()
            if pending:
                # 帧内新挂未消费的糖（' 后无表达式就遇闭括号）=悬挂致命
                p_line, p_col = pending[-1][1], pending[-1][2]
                raise SkillParseError(
                    f"第 {p_line} 行第 {p_col} 列：前缀语法糖"
                    f"（{pending[-1][0]}）缺被引用表达式"
                    "（悬挂 ' / ` / , / ,@）",
                    line=p_line, column=p_col)
            items = tuple(done.items)
            if done.head is not None:
                items = (done.head, *items)
            node = (LispList(items, line=done.line)
                    if done.kind == "list"
                    else LispVector(items, line=done.line))
            container = stack[-1].items if stack else roots
            container.append(_wrap_prefix(node, done.prefix))
            continue
        if kind == "qstr":
            body = _decode_string(token[1:-1])
            container.append(_wrap_suffix(body, pending))
            new_line, new_start = _advance_line(token, line, pos)
            if new_start >= 0:
                line, line_start = new_line, new_start
            continue
        if kind == "vsym":
            container.append(_wrap_suffix(Symbol(token[1:-1], line=line), pending))
            continue
        if kind == "num":
            container.append(_wrap_suffix(_int_or_float(token), pending))
            continue
        if kind == "sym":
            sym = Symbol(token, line=line)
            if pos < n and text[pos] == "(":
                # SKILL f( 调用糖：符号与左括号紧邻即绑定（f(x) ≡ (f x)）；
                # 不 append，符号作为紧随表的头部（lp 分支挂 frame.head）
                sugar_head = sym
            else:
                container.append(_wrap_suffix(sym, pending))
            continue
        if kind in ("quote", "qq", "unq", "unqs"):
            pending.append((
                {"quote": "quote", "qq": "quasiquote",
                 "unq": "unquote", "unqs": "unquote-splicing"}[kind],
                line, col))
            continue
        if kind == "bad_bcomment":
            raise SkillParseError(
                f"第 {line} 行第 {col} 列：块注释 /* 未闭合",
                line=line, column=col)
        if kind == "bad_qstr":
            raise SkillParseError(
                f"第 {line} 行第 {col} 列：引号字符串未闭合",
                line=line, column=col)
        raise SkillParseError(  # bad_vsym
            f"第 {line} 行第 {col} 列：转义符号 |...| 未闭合（单行）",
            line=line, column=col)
    if pending:
        p_line, p_col = pending[-1][1], pending[-1][2]
        raise SkillParseError(
            f"第 {p_line} 行第 {p_col} 列：前缀语法糖（{pending[-1][0]}）"
            "缺被引用表达式（文件尾悬挂 ' / ` / , / ,@）",
            line=p_line, column=p_col)
    if stack:
        inner = stack[-1]
        raise SkillParseError(
            f"第 {inner.line} 行第 {inner.col} 列起的"
            f"{'括号' if inner.kind == 'list' else '向量'}未闭合"
            f"（文件尾仍缺 {len(stack)} 个关闭符）",
            line=inner.line, column=inner.col)
    return roots


# ─── 渲染 / 平面化 / 遍历 ──────────────────────────────────────────────────


def _flat_tokens(node: SkillNode) -> list[str]:
    """节点 → 渲染 token 序列（嵌套表/向量摊平进父 token 流，保持紧凑）。"""
    if isinstance(node, (LispList, LispVector)):
        opener, closer = ("(", ")") if isinstance(node, LispList) else ("[", "]")
        tokens: list[str] = [opener]
        stack: list[Iterator[SkillNode]] = [iter(node.items)]
        while stack:
            child = next(stack[-1], None)
            if child is None:
                stack.pop()
                tokens.append(closer)
            else:
                tokens.extend(_flat_tokens(child))
        return tokens
    if isinstance(node, Symbol):
        return [_symbol_source(node.name)]
    if isinstance(node, Quote):
        return [_QUOTE_PREFIXES[node.kind] + render_skill(node.item)]
    if isinstance(node, str):
        return ['"' + node.replace("\\", "\\\\").replace('"', '\\"') + '"']
    return [repr(node)]


def render_skill(node: SkillNode) -> str:
    """节点 → 紧凑源文（单空格分词，括号内侧无空格；迭代实现零递归）。

    ``|...|`` 转义符号按字符集判定回写栏形态；字符串重新加引号并转义
    ``\\``/``"``。紧凑渲染为展示形态（原始空白细节不保留）。
    """
    tokens = _flat_tokens(node)
    out: list[str] = []
    prev = tokens[0]
    for tok in tokens:
        if out and tok not in (")", "]") and prev not in ("(", "["):
            out.append(" ")
        out.append(tok)
        prev = tok
    return "".join(out)


def _plain_shell(node: SkillNode) -> Any:
    """节点 → 平面化外壳（原子=值；容器/包装=待填壳）。"""
    if isinstance(node, Symbol):
        return {"symbol": node.name}
    if isinstance(node, LispList):
        return []
    if isinstance(node, LispVector):
        return {"vector": []}
    if isinstance(node, Quote):
        return {"quote": node.kind, "of": None}
    return node


def _plain_attach(dst: Any, shell: Any) -> None:
    """子外壳挂进父外壳（list=append；vector 壳=进 vector 键；quote 壳=填 of）。"""
    if isinstance(dst, list):
        dst.append(shell)
    elif "vector" in dst:
        dst["vector"].append(shell)
    else:
        dst["of"] = shell


def node_to_plain(node: SkillNode) -> Any:
    """节点 → JSON 原生嵌套结构（迭代实现零递归）。

    Symbol→``{"symbol": name}``、int/float/str→原值、LispList→list、
    LispVector→``{"vector": [...]}``、Quote→``{"quote": kind, "of": …}``。
    """
    root = _plain_shell(node)
    stack: list[tuple[SkillNode, Any]] = [(node, root)]
    while stack:
        src, dst = stack.pop()
        if isinstance(src, Symbol) or not _node_children(src):
            continue
        for child in _node_children(src):
            shell = _plain_shell(child)
            _plain_attach(dst, shell)
            if _node_children(child):
                stack.append((child, shell))
    return root


def _node_children(node: SkillNode) -> tuple[SkillNode, ...]:
    """节点的直接子节点（表/向量=items；Quote=被包装节点；其余=空）。"""
    if isinstance(node, (LispList, LispVector)):
        return node.items
    if isinstance(node, Quote):
        return (node.item,)
    return ()


def skill_tree_stats(
    tree: list[SkillNode] | tuple[SkillNode, ...],
) -> dict[str, int]:
    """节点树计数面（迭代遍历）：顶层形态数/总节点数/分型计数/最大深度。

    depth 口径：顶层节点=0，其子节点=1（:func:`skill_globals` 作用域深度
    同口径）。
    """
    n_nodes = 0
    n_lists = n_vectors = n_symbols = n_numbers = n_strings = n_quotes = 0
    max_depth = 0
    stack: list[tuple[SkillNode, int]] = [(node, 0) for node in reversed(list(tree))]
    while stack:
        node, depth = stack.pop()
        n_nodes += 1
        max_depth = max(max_depth, depth)
        if isinstance(node, LispList):
            n_lists += 1
        elif isinstance(node, LispVector):
            n_vectors += 1
        elif isinstance(node, Symbol):
            n_symbols += 1
        elif isinstance(node, Quote):
            n_quotes += 1
        elif isinstance(node, str):
            n_strings += 1
        elif isinstance(node, (int, float)):
            n_numbers += 1
        for child in _node_children(node):
            stack.append((child, depth + 1))
    return {
        "n_top_level": len(tree),
        "n_nodes": n_nodes,
        "n_lists": n_lists,
        "n_vectors": n_vectors,
        "n_symbols": n_symbols,
        "n_numbers": n_numbers,
        "n_strings": n_strings,
        "n_quotes": n_quotes,
        "max_depth": max_depth,
    }


def _walk_containers(
    tree: list[SkillNode] | tuple[SkillNode, ...], *,
    include_quoted: bool = False,
) -> Iterator[tuple[LispList | LispVector, int, int]]:
    """深度优先先序遍历表/向量容器，产出 (node, depth, form_index)。

    form_index=该容器所属顶层形态的序号；depth：顶层=0。缺省
    ``include_quoted=False``：引号数据整树视为数据——Quote 包装子树与
    ``(quote …)`` 显式形的子树不入遍历（结构提取层的代码/数据边界）；
    ``skill_tree_stats`` 的原始计数不受此影响（独立遍历）。
    """
    for index, root in enumerate(tree):
        stack: list[tuple[SkillNode, int]] = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            if isinstance(node, Quote):
                if include_quoted:
                    stack.append((node.item, depth + 1))
                continue
            if isinstance(node, (LispList, LispVector)):
                if not include_quoted and isinstance(node, LispList):
                    head = _head_symbol(node)
                    if head is not None and head.name == "quote":
                        continue
                yield node, depth, index
                for child in reversed(node.items):
                    stack.append((child, depth + 1))


def _head_symbol(node: LispList | LispVector) -> Symbol | None:
    """表头符号（首子节点为符号时返回；空表/向量/头非符号=None）。"""
    if isinstance(node, LispList) and node.items:
        first = node.items[0]
        if isinstance(first, Symbol):
            return first
    return None


#: 调用面遍历的节点形态标记：None=普通代码表；"bindings"=let 族绑定表
#: （扁平 var/val 对，偶数位=变量名不计调用）；"clause"=case 族分支
#: （0 位=匹配模式不计调用，其余照常）；"testhead"=cond 族分支（头部=
#: 测试表达式非算子不计调用，全部子节点照常遍历）。
_CallMode = str | None


def _walk_calls(
    tree: list[SkillNode] | tuple[SkillNode, ...],
) -> Iterator[tuple[LispList | LispVector, int, int, _CallMode]]:
    """调用面遍历（api_calls/call_edges 单源）：引号数据不入 + 绑定形态剪除。

    与 :func:`_walk_containers` 的差异（代码/数据与绑定形态的静态口径）：

    - Quote 包装子树与 ``(quote …)`` 显式形子树整树不入（引号数据非代码，
      ``'(f x)`` 不计 f 调用）；
    - lambda/nlambda 参数表（items[1]）、defun 参数表（items[2]）、define
      函数头签名（items[1] 为表时）整表剪除（形参名单非调用）；
    - let/let*/prog/prog* 绑定表（items[1]）按**扁平 var/val 对**剪除
      （SKILL 口径）：偶数位=变量名不计调用，奇数位=值表达式照常遍历；
    - setf/setq 的目标位（items 奇数位）整位剪除（广义引用 ``(car x)``
      是位置不是调用）；
    - foreach/for 的循环变量（items[1] 为符号时）剪除；
    - case/caseq 分支表以 "clause" 标记下传（0 位模式剪除）；
    - cond 分支表以 "testhead" 标记下传（头部=测试表达式非算子不计调用，
      测试与体全部子节点照常遍历）。

    产出 (node, depth, form_index, mode)；mode 非 None 时该节点头部不作
    调用候选（变量名/模式名/测试位置）。
    """
    for index, root in enumerate(tree):
        stack: list[tuple[SkillNode, int, _CallMode]] = [(root, 0, None)]
        while stack:
            node, depth, mode = stack.pop()
            if isinstance(node, Quote):
                continue
            if not isinstance(node, (LispList, LispVector)):
                continue
            yield node, depth, index, mode
            if isinstance(node, LispList) and node.items:
                head = node.items[0]
                if isinstance(head, Symbol) and head.name == "quote":
                    continue
            skip: set[int] = set()
            child_modes: dict[int, _CallMode] = {}
            if mode == "bindings":
                for i in range(len(node.items)):
                    if i % 2 == 0:
                        skip.add(i)
            elif mode == "clause":
                skip.add(0)
            head = node.items[0] if isinstance(node, LispList) and node.items else None
            head_name = head.name if isinstance(head, Symbol) else None
            if head_name in ("lambda", "nlambda") and len(node.items) > 1:
                skip.add(1)
            elif head_name == "defun" and len(node.items) > 2:
                skip.add(2)
            elif head_name == "define" and len(node.items) > 1 \
                    and isinstance(node.items[1], LispList):
                skip.add(1)
            elif head_name in ("let", "let*", "prog", "prog*") \
                    and len(node.items) > 1 \
                    and isinstance(node.items[1], LispList):
                child_modes[1] = "bindings"
            elif head_name in ("case", "caseq"):
                for i in range(1, len(node.items)):
                    if isinstance(node.items[i], LispList):
                        child_modes[i] = "clause"
            elif head_name == "cond":
                for i in range(1, len(node.items)):
                    if isinstance(node.items[i], LispList):
                        child_modes[i] = "testhead"
            elif head_name in ("foreach", "for") and len(node.items) > 1 \
                    and isinstance(node.items[1], Symbol):
                skip.add(1)
            elif head_name in ("setf", "setq"):
                for i in range(1, len(node.items), 2):
                    skip.add(i)
            for i, child in reversed(list(enumerate(node.items))):
                if i in skip:
                    continue
                stack.append((child, depth + 1, child_modes.get(i)))


# ─── 结构提取层（静态分析，不执行）─────────────────────────────────────────


def _arg_names(items: tuple[SkillNode, ...]) -> list[str]:
    """参数节点序 → 参数名清单（非符号参数如实渲染原文）。"""
    names: list[str] = []
    for item in items:
        names.append(item.name if isinstance(item, Symbol)
                     else render_skill(item))
    return names


def _define_name_args(
    node: LispList,
) -> tuple[str | None, list[str], str, int | None]:
    """define/defun 形态 → (name, args, style, arity)——形态非法尽力如实。

    style ∈ defun / value（define 值形态）/ fptr（define 函数头形态）；
    value 形态的值为 (lambda (args) …)/(nlambda (args) …) 时收 args/arity。
    """
    head = _head_symbol(node)
    form = head.name if head is not None else ""
    rest = node.items[1:]
    if form == "defun":
        if not rest or not isinstance(rest[0], Symbol):
            return None, [], "defun", None
        args: list[str] = []
        arity: int | None = None
        if len(rest) > 1 and isinstance(rest[1], LispList):
            args = _arg_names(rest[1].items)
            arity = len(args)
        return rest[0].name, args, "defun", arity
    if not rest:
        return None, [], "define", None
    target = rest[0]
    if isinstance(target, Symbol):
        args, arity = [], None
        if len(rest) > 1 and isinstance(rest[1], LispList):
            value_head = _head_symbol(rest[1])
            if (value_head is not None
                    and value_head.name in ("lambda", "nlambda")
                    and len(rest[1].items) > 1
                    and isinstance(rest[1].items[1], LispList)):
                args = _arg_names(rest[1].items[1].items)
                arity = len(args)
        return target.name, args, "value", arity
    if isinstance(target, LispList) and target.items \
            and isinstance(target.items[0], Symbol):
        args = _arg_names(target.items[1:])
        return target.items[0].name, args, "fptr", len(args)
    return None, [], "define", None


def skill_definitions(
    tree: list[SkillNode] | tuple[SkillNode, ...],
) -> dict[str, Any]:
    """define/defun 清单（全树扫描；重复定义双列+warning）。

    返回::

        {"definitions": [{form, name, args, arity, style, line,
                          form_index, dup}, ...],   # 文档序
         "names": [...],          # 去重名录，首次出现序
         "duplicates": [...],     # 重复名（首次出现序）
         "warnings": ["第 N 行：…", ...],
         "stats": {n_definitions, n_unique_names, n_duplicates,
                   n_warnings}}   # n_warnings=R-22 schema 升位批补键
    """
    entries: list[dict[str, Any]] = []
    raw_warnings: list[tuple[int, str]] = []
    for node, _depth, form_index in _walk_containers(tree):
        if not isinstance(node, LispList):
            continue
        head = _head_symbol(node)
        if head is None or head.name not in ("define", "defun"):
            continue
        name, args, style, arity = _define_name_args(node)
        if name is None:
            raw_warnings.append((
                node.line, f"{style} 形态非法（缺合法名字）——name 如实 None"))
        elif (head.name == "define" and style == "value"
                and len(node.items) < 3):
            raw_warnings.append((
                node.line, f"define {name!r} 缺值——value 如实缺席"))
        entries.append({
            "form": head.name,
            "name": name,
            "args": args,
            "arity": arity,
            "style": style,
            "line": node.line,
            "form_index": form_index,
            "dup": False,
        })
    first_seen: dict[str, int] = {}
    for position, entry in enumerate(entries):
        name = entry["name"]
        if name is None:
            continue
        if name in first_seen:
            entry["dup"] = True
            entries[first_seen[name]]["dup"] = True
            raw_warnings.append((
                entry["line"],
                f"重复定义 {name!r}（首次第 {entries[first_seen[name]]['line']} 行）"
                "——两处双列如实"))
        else:
            first_seen[name] = position
    names: list[str] = []
    for entry in entries:
        name = entry["name"]
        if name is not None and name not in names:
            names.append(name)
    duplicates = [name for name in names
                  if sum(1 for e in entries if e["name"] == name) > 1]
    warnings = [f"第 {ln} 行：{msg}"
                for ln, msg in sorted(raw_warnings, key=lambda w: w[0])]
    return {
        "definitions": entries,
        "names": names,
        "duplicates": duplicates,
        "warnings": warnings,
        "stats": {
            "n_definitions": len(entries),
            "n_unique_names": len(names),
            "n_duplicates": len(duplicates),
            "n_warnings": len(warnings),
        },
    }


def skill_top_level_forms(
    tree: list[SkillNode] | tuple[SkillNode, ...],
) -> dict[str, Any]:
    """顶层形态分类计数（闭集 :data:`TOP_LEVEL_CATEGORIES` + 头符号频次）。

    返回::

        {"forms": [{index, kind, head, category, line}, ...],
         "head_counts": {head: n},          # head 非空的形态（首次出现序）
         "category_counts": {category: n},  # 闭集全键，缺席=0
         "n_top_level": N}
    """
    forms: list[dict[str, Any]] = []
    head_counts: dict[str, int] = {}
    category_counts = {cat: 0 for cat in TOP_LEVEL_CATEGORIES}
    for index, node in enumerate(tree):
        head: str | None = None
        line = 0
        if isinstance(node, LispList):
            kind = "form"
            line = node.line
            hs = _head_symbol(node)
            if hs is not None:
                head = hs.name
                if head in ("define", "defun"):
                    category = "definition"
                elif head in SPECIAL_FORMS:
                    category = "special"
                else:
                    category = "call"
            else:
                category = "expr"
        elif isinstance(node, LispVector):
            kind, category, line = "vector", "vector", node.line
        elif isinstance(node, Quote):
            kind, category, line = "quote", "quote", node.line
        elif isinstance(node, Symbol):
            kind, category, line = "atom", "atom", node.line
            head = node.name
        else:
            kind, category = "atom", "atom"
        forms.append({"index": index, "kind": kind, "head": head,
                      "category": category, "line": line})
        if head is not None:
            head_counts[head] = head_counts.get(head, 0) + 1
        category_counts[category] += 1
    return {
        "forms": forms,
        "head_counts": head_counts,
        "category_counts": category_counts,
        "n_top_level": len(tree),
    }


def api_bucket(name: str) -> str:
    """被调符号名 → 桶名（:data:`API_PREFIX_BUCKETS` 前缀表闭集驱动）。

    命中首个前缀即归桶（表序 ocean→virtuoso）；其余 generic。
    """
    for bucket, prefixes in API_PREFIX_BUCKETS.items():
        for prefix in prefixes:
            if name.startswith(prefix):
                return bucket
    return "generic"


def skill_api_calls(
    tree: list[SkillNode] | tuple[SkillNode, ...],
) -> dict[str, Any]:
    """被调函数名频次+前缀桶分类+调用点定位（静态，不执行）。

    计调口径（:func:`_walk_calls` 同源）：普通代码表的头位置为符号且
    **非特形**（:data:`SPECIAL_FORMS` 闭集外）→ 一次调用（语言构造不计
    API，其子表照常遍历）；头位置为非符号节点（计算调用/lambda 即调）→
    unknown 桶、name=None、head_raw 如实；绑定形态头部（let 族绑定表/
    case 分支表）不计；引号数据整树不计；空表不计。返回::

        {"calls": [{name, bucket, form_index, line, depth, head_raw}, ...],
         "by_name": {name: n},     # 首次出现序
         "by_bucket": {ocean, virtuoso, generic, unknown},  # 闭集全键
         "buckets": API_BUCKETS,
         "stats": {n_calls, n_names, n_unknown_head}}
    """
    calls: list[dict[str, Any]] = []
    by_name: dict[str, int] = {}
    by_bucket = {bucket: 0 for bucket in API_BUCKETS}
    n_unknown_head = 0
    for node, depth, form_index, mode in _walk_calls(tree):
        if mode is not None:
            continue
        if not isinstance(node, LispList) or not node.items:
            continue
        head = node.items[0]
        if isinstance(head, Symbol):
            if head.name in SPECIAL_FORMS:
                continue
            name: str | None = head.name
            bucket = api_bucket(name)
            head_raw: str | None = None
        else:
            name = None
            bucket = "unknown"
            head_raw = render_skill(head)
            n_unknown_head += 1
        calls.append({"name": name, "bucket": bucket,
                      "form_index": form_index, "line": node.line,
                      "depth": depth, "head_raw": head_raw})
        by_bucket[bucket] += 1
        if name is not None:
            by_name[name] = by_name.get(name, 0) + 1
    return {
        "calls": calls,
        "by_name": by_name,
        "by_bucket": by_bucket,
        "buckets": API_BUCKETS,
        "stats": {
            "n_calls": len(calls),
            "n_names": len(by_name),
            "n_unknown_head": n_unknown_head,
        },
    }


def skill_globals(
    tree: list[SkillNode] | tuple[SkillNode, ...],
) -> dict[str, Any]:
    """setf/setq 赋值目标盘点（目标名+作用域深度；静态，不执行）。

    ``setq`` 多对连写 ``(setq a 1 b 2)`` 逐对展开；目标为符号 →
    target_kind=symbol；目标为表达式形态（如 ``(car x)``）→
    target_kind=expr+target_raw 原文；目标缺配对值 → 如实记
    value_missing=True+warning。depth=赋值形态嵌套深度（顶层=0）。返回::

        {"globals": [{form, name, target_kind, target_raw, depth,
                      form_index, line, slot, value_missing}, ...],
         "n_assignments": N,
         "n_unique_targets": M,
         "targets": [...],        # 去重目标名（首次出现序）
         "warnings": [...]}
    """
    rows: list[dict[str, Any]] = []
    raw_warnings: list[tuple[int, str]] = []
    for node, depth, form_index in _walk_containers(tree):
        if not isinstance(node, LispList):
            continue
        head = _head_symbol(node)
        if head is None or head.name not in ("setf", "setq"):
            continue
        rest = node.items[1:]
        slot = 0
        i = 0
        while i < len(rest):
            target = rest[i]
            value_missing = i + 1 >= len(rest)
            if isinstance(target, Symbol):
                name: str | None = target.name
                target_kind = "symbol"
                target_raw: str | None = None
            else:
                name = None
                target_kind = "expr"
                target_raw = render_skill(target)
            rows.append({
                "form": head.name,
                "name": name,
                "target_kind": target_kind,
                "target_raw": target_raw,
                "depth": depth,
                "form_index": form_index,
                "line": node.line,
                "slot": slot,
                "value_missing": value_missing,
            })
            if value_missing:
                raw_warnings.append((
                    node.line,
                    f"{head.name} 目标 {target_raw or '符号'} 缺配对值"
                    f"（slot {slot}）——如实登记"))
            slot += 1
            i += 2
    targets: list[str] = []
    for row in rows:
        name = row["name"]
        if name is not None and name not in targets:
            targets.append(name)
    warnings = [f"第 {ln} 行：{msg}"
                for ln, msg in sorted(raw_warnings, key=lambda w: w[0])]
    return {
        "globals": rows,
        "n_assignments": len(rows),
        "n_unique_targets": len(targets),
        "targets": targets,
        "warnings": warnings,
    }


def skill_call_edges(
    tree: list[SkillNode] | tuple[SkillNode, ...],
) -> dict[str, Any]:
    """静态调用边（define→calls；只按符号名匹配同名 define）。

    无词法作用域分析（任务书如实口径）：调用归属**最近包围的
    define/defun**（嵌套定义内层优先）；递归调用=caller==callee 边如实；
    被调名无同名定义 → external 如实（全树口径，含定义体外调用）。计调
    面走 :func:`_walk_calls` 同源口径（引号数据不入+绑定形态剪除——形参
    名单/绑定变量/赋值目标/分支模式不计调用）。
    返回::

        {"edges": [{caller, callee, count}, ...],   # (caller, callee) 稳定序
         "external": [{name, count}, ...],           # (-count, name) 稳定序
         "defined_names": [...],                     # 首次出现序
         "n_edges": E, "n_external": X}
    """
    defs = skill_definitions(tree)
    defined = [name for name in defs["names"] if name]
    defined_set = set(defined)
    edge_counts: dict[tuple[str, str], int] = {}
    external_counts: dict[str, int] = {}
    #: 最近包围定义名（define/defun 内层优先）的携带栈
    stack: list[tuple[SkillNode, int, _CallMode, str | None]] = [
        (root, 0, None, None) for root in tree]
    while stack:
        node, depth, mode, ctx = stack.pop()
        if not isinstance(node, (LispList, LispVector)):
            continue
        child_ctx = ctx
        if isinstance(node, LispList) and node.items:
            head = node.items[0]
            if isinstance(head, Symbol):
                if head.name == "quote":
                    continue
                if head.name in ("define", "defun") and mode is None:
                    name, _args, _style, _arity = _define_name_args(node)
                    if name is not None:
                        child_ctx = name
                elif mode is None and head.name not in SPECIAL_FORMS:
                    if ctx is not None:
                        key = (ctx, head.name)
                        edge_counts[key] = edge_counts.get(key, 0) + 1
                    if head.name not in defined_set:
                        external_counts[head.name] = (
                            external_counts.get(head.name, 0) + 1)
        if mode == "bindings":
            skip = {i for i in range(len(node.items)) if i % 2 == 0}
        elif mode == "clause":
            skip = {0}
        else:
            skip = set()
        child_modes: dict[int, _CallMode] = {}
        if isinstance(node, LispList) and node.items:
            head = node.items[0]
            head_name = head.name if isinstance(head, Symbol) else None
            if head_name in ("lambda", "nlambda") and len(node.items) > 1:
                skip.add(1)
            elif head_name == "defun" and len(node.items) > 2:
                skip.add(2)
            elif head_name == "define" and len(node.items) > 1 \
                    and isinstance(node.items[1], LispList):
                skip.add(1)
            elif head_name in ("let", "let*", "prog", "prog*") \
                    and len(node.items) > 1 \
                    and isinstance(node.items[1], LispList):
                child_modes[1] = "bindings"
            elif head_name in ("case", "caseq"):
                for i in range(1, len(node.items)):
                    if isinstance(node.items[i], LispList):
                        child_modes[i] = "clause"
            elif head_name == "cond":
                for i in range(1, len(node.items)):
                    if isinstance(node.items[i], LispList):
                        child_modes[i] = "testhead"
            elif head_name in ("foreach", "for") and len(node.items) > 1 \
                    and isinstance(node.items[1], Symbol):
                skip.add(1)
            elif head_name in ("setf", "setq"):
                for i in range(1, len(node.items), 2):
                    skip.add(i)
        for i, child in reversed(list(enumerate(node.items))):
            if i in skip:
                continue
            stack.append((child, depth + 1, child_modes.get(i), child_ctx))
    edges = [{"caller": caller, "callee": callee, "count": count}
             for (caller, callee), count in sorted(edge_counts.items())]
    external = [{"name": name, "count": count} for name, count in
                sorted(external_counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {
        "edges": edges,
        "external": external,
        "defined_names": defined,
        "n_edges": len(edges),
        "n_external": len(external),
    }
    edges = [{"caller": caller, "callee": callee, "count": count}
             for (caller, callee), count in sorted(edge_counts.items())]
    external = [{"name": name, "count": count} for name, count in
                sorted(external_counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {
        "edges": edges,
        "external": external,
        "defined_names": defined,
        "n_edges": len(edges),
        "n_external": len(external),
    }


# ─── 只读求值面（受限）────────────────────────────────────────────────────


def skill_literal_eval(node: SkillNode) -> Any:
    """纯字面量表达式求值（只读受限面）——数字算术/quote/list/append/
    cons/strcat；非字面量 → :class:`SkillEvalError` fail-closed 不猜。

    可求值形态：自身字面量（int/float/str）、``(quote x)``（数据逐字平面
    化）、``(+ a b …)`` 数字和、``(- a)`` 取负 / ``(- a b …)`` 左折叠差、
    ``(* …)`` 积、``(/ a b …)`` 左折叠真除（恒 float；除零 fail-closed）、
    ``(list …)``、``(append l …)`` 表拼接、``(cons x l)``、
    ``(strcat s …)`` 字符串拼接。符号引用、未知函数、空表、向量、
    quasiquote 族（不展开）一律 SkillEvalError。
    """
    if isinstance(node, (int, float, str)):
        return node
    if isinstance(node, Quote):
        if node.kind == "quote":
            return node_to_plain(node.item)
        raise SkillEvalError(
            f"非字面量形态（{node.kind} 不展开不求值）：{render_skill(node)}")
    if isinstance(node, Symbol):
        raise SkillEvalError(
            f"符号引用不可静态求值：{node.name}（fail-closed 不猜）")
    if isinstance(node, LispVector):
        raise SkillEvalError(f"向量不在字面量求值闭集：{render_skill(node)}")
    if not node.items:
        raise SkillEvalError("空表不可求值：()")
    head = node.items[0]
    if not isinstance(head, Symbol):
        raise SkillEvalError(f"算子非符号不可求值：{render_skill(node)}")
    op = head.name
    args = node.items[1:]
    if op == "quote":
        if len(args) != 1:
            raise SkillEvalError(
                f"quote 期望 1 个参数，得 {len(args)}：{render_skill(node)}")
        return node_to_plain(args[0])
    if op in ("+", "-", "*", "/"):
        return _arith(op, args, node)
    if op == "list":
        return [skill_literal_eval(arg) for arg in args]
    if op == "append":
        out: list[Any] = []
        for arg in args:
            value = skill_literal_eval(arg)
            if not isinstance(value, list):
                raise SkillEvalError(
                    f"append 参数须为表：{render_skill(arg)}（fail-closed）")
            out = [*out, *value]
        return out
    if op == "cons":
        if len(args) != 2:
            raise SkillEvalError(
                f"cons 期望 2 个参数，得 {len(args)}：{render_skill(node)}")
        first = skill_literal_eval(args[0])
        rest = skill_literal_eval(args[1])
        if not isinstance(rest, list):
            raise SkillEvalError(
                f"cons 第二参数须为表：{render_skill(args[1])}（fail-closed）")
        return [first, *rest]
    if op == "strcat":
        parts = [skill_literal_eval(arg) for arg in args]
        if any(not isinstance(p, str) for p in parts):
            raise SkillEvalError(
                f"strcat 参数须全为字符串：{render_skill(node)}")
        return "".join(parts)
    raise SkillEvalError(
        f"未知算子 {op!r} 不在字面量求值闭集：{render_skill(node)}")


def _arith(
    op: str, args: tuple[SkillNode, ...], node: LispList
) -> int | float:
    """数字算术（+ - * /）；非数字参数/除零 → SkillEvalError fail-closed。"""
    if not args:
        raise SkillEvalError(f"算子 {op!r} 缺参数：()")
    values: list[int | float] = []
    for arg in args:
        value = skill_literal_eval(arg)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SkillEvalError(
                f"{op} 参数须为数字：{render_skill(arg)}（fail-closed）")
        values.append(value)
    if op == "+":
        total: int | float = 0
        for value in values:
            total = total + value
        return total
    if op == "*":
        product: int | float = 1
        for value in values:
            product = product * value
        return product
    if op == "-":
        if len(values) == 1:
            return -values[0]
        acc = values[0]
        for value in values[1:]:
            acc = acc - value
        return acc
    # 除法：恒 Python 真除（float）；除零 fail-closed
    if len(values) < 2:
        raise SkillEvalError(
            f"/ 期望至少 2 个参数，得 {len(values)}：{render_skill(node)}")
    acc = values[0]
    for value in values[1:]:
        try:
            acc = acc / value  # type: ignore[operator]
        except ZeroDivisionError as exc:
            raise SkillEvalError(
                f"除零：{render_skill(node)}（fail-closed）") from exc
    return acc
