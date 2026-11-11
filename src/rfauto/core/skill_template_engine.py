"""SKILL 模板引擎（T-Q27 席 Q-X32，aurora_q CAD 大扩展——零 Virtuoso 依赖）。

外部使用者（Cadence Virtuoso 用户群）需要**从 Python 确定性生成 SKILL 代码
脚本**以自动化 Virtuoso 操作（打开 cellview/创建 layout 图形/运行仿真/导出
数据）。借鉴化用 virtuoso-bridge-lite 的核心模式（Python 客户端生成 SKILL
代码字符串 → IPC/文件交换 → Virtuoso 侧加载执行）的**前半段**：本模块只做
"Python → SKILL 代码字符串"的模板化生成与语法守卫，产物是 ``.il`` 文件——
执行侧完全在用户本地的 Virtuoso 环境里，本仓零 Cadence 依赖、零真机调用。

模板语法（Jinja2 形态自制微实现，零新依赖——不 import jinja2）：

- ``{{ expr }}``   输出标签：变量路径自动渲染为 SKILL 字面量
  （str→带引号转义字符串 / bool→t,nil / int,float→数字 / None→nil /
  list,tuple→``list(...)`` 函数形态 / dict→显式报错）；
  过滤器 ``|raw``=原样插入（须为 str，预成形 SKILL 片段）、
  ``|default(literal)``=变量缺失时取字面量兜底（literal 为 Python 字面量）；
- ``{% for x in path %} ... {% endfor %}``   循环（体内 ``loop.index``/
  ``loop.index0`` 可用）；嵌套循环内层遮蔽外层循环变量；
- ``{% if cond %} / {% elif cond %} / {% else %} / {% endif %}``
  条件分支；cond 为安全表达式（比较/and/or/not/in/括号/字面量/变量路径，
  自制递归下降求值，**永不 ``eval()``**）；
- ``{# ... #}``    模板注释（输出剔除）。

铁律：``{{ }}`` 标签必须占一个完整 SKILL token 位，禁止嵌在 SKILL 字符串
字面量内部（字符串引号由自动字面量渲染负责）——lint 对残留 ``{{``/``{%``
标签与源内嵌位同抓（fail-loud）。

SKILL 语法守卫（:func:`skill_lint_issues`，纯函数零 IO）：

- 括号配对（跳过字符串字面量与 ``;`` 行注释后计数，负深度/末尾余深即红）；
- 引号闭合（逐行未转义 ``"`` 计数为偶，奇数即红）；
- ``let`` 绑定形态（``let`` 头后必须紧跟绑定表 ``(``）；
- 已知函数名白名单（:data:`KNOWN_SKILL_FUNCTIONS`——凡"标识符后跟 ``(``"
  按函数头校验，未知名即红；``(`` 后首标识符不校验（let 绑定表/数据列表
  非函数调用）；属性读写 ``var~>attr`` 与语句级赋值 ``var = expr`` 不按
  函数校验）。

结构化 SKILL 代码生成器：:func:`skill_literal` / :func:`skill_call` /
:func:`skill_let` / :func:`skill_if` / :func:`skill_foreach`（供模板与调用
方拼装 let 块/条件分支/循环——生成面全部纯字符串操作）。

确定性：同 (模板, 变量) 两跑逐字节同（零时间戳零 uuid 零随机——铁律 7：
SKILL 代码=模板+变量直出，零手抄电路数值；本模块不产生任何物理数字）。

出处声明（#1c/#122 如实口径）：模板函数名面见
:mod:`rfauto.core.skill_templates` 各模板 docstring——本模块白名单只收
模板实际生成面 + SKILL 语言核心字（let/foreach/if/list/sprintf 等），
不宣称对任意 Cadent release 的 API 全覆盖；用户按本地 SKILL Language
Reference 校准后可用 ``|raw`` 拼接自有片段。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = [
    "CALC_SKILL_FUNCTIONS",
    "CORE_SKILL_FUNCTIONS",
    "EDA_SKILL_FUNCTIONS",
    "KNOWLEDGE_FILTERS",
    "KNOWN_SKILL_FUNCTIONS",
    "SkillTemplateError",
    "list_template_var_info",
    "list_template_vars",
    "render_template",
    "skill_call",
    "skill_foreach",
    "skill_if",
    "skill_let",
    "skill_lint_issues",
    "skill_literal",
]

# ──────────────── 异常（fail-loud 单源） ────────────────


class SkillTemplateError(Exception):
    """模板解析/渲染错误（message 带 1-based 行号定位）。"""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.line = line
        suffix = f" (line {line})" if line is not None else ""
        super().__init__(f"{message}{suffix}")


# ──────────────── 函数名白名单（单源；lint 与模板共用） ────────────────

#: SKILL 语言核心字（生成面用到的子集——非 Cadence API 全集）
CORE_SKILL_FUNCTIONS = frozenset({
    "let", "letseq", "if", "when", "unless", "foreach", "foreachi",
    "lambda", "progn", "setq", "list", "append", "cons", "car", "cdr",
    "caar", "cadr", "caddr", "cdar", "cddr", "nth", "length", "reverse",
    "assoc", "mapcar", "printf", "sprintf", "fprintf", "strcat", "error",
    "errset", "warn", "load",
})

#: 模板生成面 EDA 函数（cell/schematic/tech/OCEAN——出处声明见各模板
#: docstring；发布版须对照本地 SKILL Language Reference 校准）
EDA_SKILL_FUNCTIONS = frozenset({
    # layout / cellview（SKILL ref dbCreate* 惯例形态）
    "dbOpenCellViewByType", "dbCreateRect", "dbCreatePath", "dbCreateLabel",
    "dbCreateInst", "dbSave", "dbClose",
    # schematic
    "schCreateWire",
    # techfile（layer setup 脚手架——发布版校准点）
    "ddGetObj", "techGetTechFile", "techAddLayer", "techUpdateTechFile",
    # ADE XL OCEAN XL（仿真启动+汇总导出）
    "ocnxlRun", "ocnxlOutputSummaryCSV", "ocnxlExit",
    # OCEAN 波形导出
    "ocnPrint",
    # 窗口句柄
    "hiGetCurrentWindow",
})

#: 波形计算器函数子集（OCEAN calculator 常用面——raw 表达式里出现；
#: 词表外函数名 lint 记 warning 不记 error——Cadence API 面远大于本子集）
CALC_SKILL_FUNCTIONS = frozenset({
    "v", "i", "VDC", "IDC", "VAC", "IAC", "VTRAN", "ITRAN", "VTIME",
    "ITIME", "mag", "db10", "db20", "phase", "real", "imag", "value",
    "versus", "deriv", "integral", "log", "log10", "exp", "abs", "sqrt",
})

#: lint 白名单 = 核心字 ∪ 模板 EDA 面 ∪ 计算器面（单源导出，模板注册表按此自查）
KNOWN_SKILL_FUNCTIONS = (CORE_SKILL_FUNCTIONS | EDA_SKILL_FUNCTIONS
                         | CALC_SKILL_FUNCTIONS)

#: 模板过滤器词表（输出标签 ``|`` 后合法名；default 带字面量参数）
KNOWLEDGE_FILTERS = frozenset({"raw", "default"})

# ──────────────── 模板词法（token 切分） ────────────────

_TAG_RE = re.compile(r"(\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\})", re.DOTALL)
_OPEN_TAGS = ("{{", "{%", "{#")


def _line_of(source: str, pos: int) -> int:
    """1-based 行号（错误定位单源）。"""
    return source.count("\n", 0, pos) + 1


def _split_source(source: str) -> list[tuple[str, str, int]]:
    """源串 → [(kind, body, pos)]，kind ∈ {"text", "out", "stmt", "comment"}。

    未闭合标签/字符串内嵌标签在切分后统一 fail-loud（parse 前置检查）。
    """
    parts: list[tuple[str, str, int]] = []
    pos = 0
    for m in _TAG_RE.finditer(source):
        if m.start() > pos:
            parts.append(("text", source[pos:m.start()], pos))
        raw = m.group(0)
        if raw.startswith("{{"):
            parts.append(("out", raw[2:-2].strip(), m.start()))
        elif raw.startswith("{%"):
            parts.append(("stmt", raw[2:-2].strip(), m.start()))
        else:
            parts.append(("comment", "", m.start()))
        pos = m.end()
    if pos < len(source):
        parts.append(("text", source[pos:], pos))
    for kind, body, pos_i in parts:
        if kind == "text":
            for tag in _OPEN_TAGS:
                idx = body.find(tag)
                if idx >= 0:
                    raise SkillTemplateError(
                        f"未闭合的模板标签 {tag}...（或标签跨行未闭合）",
                        _line_of(source, pos_i + idx))
    return parts


# ──────────────── 输出标签表达式（路径+过滤器） ────────────────

_FILTER_SPEC_RE = re.compile(r"^(\w+)(?:\((.*)\))?$", re.DOTALL)


def _parse_output_expr(expr: str, line: int) -> tuple[str, list[tuple[str, Any]]]:
    """``path|filter|filter(arg)`` → (路径, [(过滤名, 参数或 None)])。"""
    segs = [s.strip() for s in expr.split("|")]
    if not segs[0]:
        raise SkillTemplateError("输出标签缺变量路径", line)
    for seg in segs[0].split("."):
        if not re.fullmatch(r"[A-Za-z_]\w*", seg or ""):
            raise SkillTemplateError(f"非法变量路径段 {seg!r}", line)
    filters: list[tuple[str, Any]] = []
    for seg in segs[1:]:
        m = _FILTER_SPEC_RE.match(seg)
        if not m:
            raise SkillTemplateError(f"非法过滤器形态 {seg!r}", line)
        name, arg = m.group(1), m.group(2)
        if name not in KNOWLEDGE_FILTERS:
            raise SkillTemplateError(
                f"未知过滤器 {name!r}（合法：{sorted(KNOWLEDGE_FILTERS)}）", line)
        if name == "raw" and arg is not None:
            raise SkillTemplateError("raw 过滤器不收参数", line)
        if name == "default":
            if arg is None:
                raise SkillTemplateError("default 过滤器必须带字面量参数", line)
            try:
                filters.append(("default", _parse_literal(arg, line)))
            except SkillTemplateError:
                raise
            continue
        filters.append((name, None))
    return segs[0], filters


def _parse_literal(text: str, line: int) -> Any:
    """过滤器参数 → Python 字面量（json.loads 单源；失败 fail-loud）。"""
    import json

    try:
        return json.loads(text)
    except ValueError as exc:
        raise SkillTemplateError(f"非法字面量参数 {text!r}（{exc}）", line) from None


# ──────────────── 条件表达式（安全递归下降，零 eval） ────────────────

_COND_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<op>==|!=|>=|<=|>|<|\(|\))
      | (?P<word>[A-Za-z_][\w.]*)
      | (?P<num>\d+\.\d+(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)
      | (?P<dq>"(?:[^"\\]|\\.)*")
      | (?P<sq>'[^']*')
    )""",
    re.VERBOSE,
)


def _tokenize_cond(text: str, line: int) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _COND_TOKEN_RE.match(text, pos)
        if not m:
            if text[pos:].strip():
                raise SkillTemplateError(
                    f"条件表达式含非法 token {text[pos:].split()[0]!r}", line)
            break
        pos = m.end()
        kind = m.lastgroup or ""
        tokens.append((kind, m.group(kind)))
    if not tokens:
        raise SkillTemplateError("条件表达式为空", line)
    return tokens


class _CondParser:
    """or → and → not → cmp → primary 递归下降（安全求值）。"""

    def __init__(self, tokens: list[tuple[str, str]], line: int,
                 resolve: Any) -> None:
        self._toks = tokens
        self._i = 0
        self._line = line
        self._resolve = resolve

    def _peek_kind(self) -> str | None:
        return self._toks[self._i][0] if self._i < len(self._toks) else None

    def _peek_val(self) -> str | None:
        return self._toks[self._i][1] if self._i < len(self._toks) else None

    def _next(self) -> tuple[str, str]:
        tok = self._toks[self._i]
        self._i += 1
        return tok

    def parse(self) -> Any:
        val = self._parse_or()
        if self._i != len(self._toks):
            raise SkillTemplateError(
                f"条件表达式尾有多余 token {self._peek_val()!r}", self._line)
        return val

    def _parse_or(self) -> Any:
        val = self._parse_and()
        while self._peek_val() == "or":
            self._next()
            rhs = self._parse_and()
            val = bool(val) or bool(rhs)
        return val

    def _parse_and(self) -> Any:
        val = self._parse_not()
        while self._peek_val() == "and":
            self._next()
            rhs = self._parse_not()
            val = bool(val) and bool(rhs)
        return val

    def _parse_not(self) -> Any:
        if self._peek_val() == "not":
            self._next()
            return not bool(self._parse_not())
        return self._parse_cmp()

    def _parse_cmp(self) -> Any:
        left = self._parse_primary()
        val = self._peek_val()
        if val in ("==", "!=", ">=", "<=", ">", "<"):
            self._next()
            right = self._parse_primary()
            return _compare(val, left, right, self._line)
        if val == "in":
            self._next()
            return _contains(left, self._parse_primary(), self._line)
        if val == "not" and self._toks[self._i + 1:self._i + 2] and \
                self._toks[self._i + 1][1] == "in":
            self._next()
            self._next()
            return not _contains(left, self._parse_primary(), self._line)
        return left

    def _parse_primary(self) -> Any:
        kind, val = (self._next() if self._i < len(self._toks)
                     else ("", ""))
        if not kind:
            raise SkillTemplateError("条件表达式意外结束", self._line)
        if kind == "op" and val == "(":
            inner = self._parse_or()
            k2, v2 = self._next()
            if not (k2 == "op" and v2 == ")"):
                raise SkillTemplateError("条件括号未闭合", self._line)
            return inner
        if kind == "num":
            return float(val) if any(c in val for c in ".eE") else int(val)
        if kind == "dq":
            return val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if kind == "sq":
            return val[1:-1]
        if kind == "word":
            if val in ("True", "true", "t"):
                return True
            if val in ("False", "false", "nil"):
                return False
            if val == "None":
                return None
            return self._resolve(val)
        raise SkillTemplateError(f"条件表达式非法 token {val!r}", self._line)


def _compare(op: str, left: Any, right: Any, line: int) -> bool:
    try:
        if op == "==":
            return bool(left == right)
        if op == "!=":
            return bool(left != right)
        if op == ">=":
            return bool(left >= right)
        if op == "<=":
            return bool(left <= right)
        if op == ">":
            return bool(left > right)
        if op == "<":
            return bool(left < right)
    except TypeError as exc:
        raise SkillTemplateError(
            f"比较 {left!r} {op} {right!r} 类型不可比（{exc}）", line) from None
    raise SkillTemplateError(f"未知比较符 {op!r}", line)


def _contains(left: Any, right: Any, line: int) -> bool:
    try:
        return left in right
    except TypeError as exc:
        raise SkillTemplateError(
            f"in 判定 {left!r} in {right!r} 不可行（{exc}）", line) from None


# ──────────────── 模板 AST + 解析 ────────────────

class _Node:
    __slots__ = ()


class _Text(_Node):
    __slots__ = ("s",)

    def __init__(self, s: str) -> None:
        self.s = s


class _Out(_Node):
    __slots__ = ("filters", "line", "path")

    def __init__(self, path: str, filters: list[tuple[str, Any]],
                 line: int) -> None:
        self.path = path
        self.filters = filters
        self.line = line


class _For(_Node):
    __slots__ = ("body", "iter_default", "iter_path", "line", "var")

    def __init__(self, var: str, iter_path: str, iter_default: Any,
                 body: list[_Node], line: int) -> None:
        self.var = var
        self.iter_path = iter_path
        self.iter_default = iter_default
        self.body = body
        self.line = line


class _If(_Node):
    __slots__ = ("branches", "else_body", "line")

    def __init__(self, branches: list[tuple[Any, list[_Node], int]],
                 else_body: list[_Node], line: int) -> None:
        self.branches = branches  # [(cond_tokens, body, line)]
        self.else_body = else_body
        self.line = line


_FOR_RE = re.compile(
    r"^for\s+([A-Za-z_]\w*)\s+in\s+([A-Za-z_][\w.]*)"
    r"(?:\s*\|\s*default\((.*)\))?$", re.DOTALL)
_IFELIF_RE = re.compile(r"^(if|elif)\s+(.*)$", re.DOTALL)
_HEAD_RE = re.compile(r"^(\w+)")


def _parse_template(source: str) -> list[_Node]:
    parts = _split_source(source)
    body, _pos = _parse_block(parts, 0, source, terminators=())
    return body


def _parse_block(parts: list[tuple[str, str, int]], idx: int, source: str,
                 terminators: tuple[str, ...]) -> tuple[list[_Node], int]:
    body: list[_Node] = []
    while idx < len(parts):
        kind, stmt, pos = parts[idx]
        if kind == "text":
            if parts[idx][1]:
                body.append(_Text(parts[idx][1]))
            idx += 1
            continue
        if kind == "comment":
            idx += 1
            continue
        if kind == "out":
            path, filters = _parse_output_expr(stmt, _line_of(source, pos))
            body.append(_Out(path, filters, _line_of(source, pos)))
            idx += 1
            continue
        # stmt
        head = stmt.split(None, 1)[0] if stmt.split(None, 1) else ""
        if head in terminators:
            return body, idx
        if head == "for":
            m = _FOR_RE.match(stmt)
            if not m:
                raise SkillTemplateError(
                    f"for 标签形态非法 {stmt!r}（for x in path[|default(lit)]）",
                    _line_of(source, pos))
            iter_default = (None if m.group(3) is None
                            else _parse_literal(m.group(3), _line_of(source, pos)))
            inner, idx2 = _parse_block(parts, idx + 1, source, ("endfor",))
            if idx2 >= len(parts) or parts[idx2][1].split(None, 1)[0] != "endfor":
                raise SkillTemplateError("for 缺 {%endfor%}",
                                         _line_of(source, pos))
            body.append(_For(m.group(1), m.group(2), iter_default, inner,
                             _line_of(source, pos)))
            idx = idx2 + 1
            continue
        if head in ("if", "elif", "else", "endif"):
            if head == "if":
                branches, else_body, idx = _parse_if(parts, idx, source)
                body.append(_If(branches, else_body, _line_of(source, pos)))
                continue
            raise SkillTemplateError(f"孤立的 {{%{head}%}}",
                                     _line_of(source, pos))
        raise SkillTemplateError(f"未知语句标签 {head!r}", _line_of(source, pos))
    if terminators:
        raise SkillTemplateError(
            f"块未闭合（缺 {'/'.join(terminators)}）",
            _line_of(source, parts[-1][2]) if parts else 1)
    return body, idx


def _parse_if(parts: list[tuple[str, str, int]], idx: int,
              source: str) -> tuple[list[tuple[Any, list[_Node], int]],
                                    list[_Node], int]:
    """idx 恒指向 ``{%if%}``/``{%elif%}`` 语句段（_parse_block 契约）。"""
    branches: list[tuple[Any, list[_Node], int]] = []
    else_body: list[_Node] = []
    while True:
        kind, stmt, pos = parts[idx]
        m = _IFELIF_RE.match(stmt) if kind == "stmt" else None
        if not m:
            raise SkillTemplateError("if 块解析异常", _line_of(source, pos))
        cond = _tokenize_cond(m.group(2), _line_of(source, pos))
        inner, idx2 = _parse_block(parts, idx + 1, source,
                                   ("elif", "else", "endif"))
        branches.append((cond, inner, _line_of(source, pos)))
        tm = _HEAD_RE.match(parts[idx2][1])
        head = tm.group(1) if tm else parts[idx2][1]
        if head == "elif":
            idx = idx2
            continue
        if head == "else":
            else_body, idx3 = _parse_block(parts, idx2 + 1, source,
                                           ("endif",))
            tm3 = _HEAD_RE.match(parts[idx3][1])
            head3 = tm3.group(1) if tm3 else parts[idx3][1]
            if head3 != "endif":
                raise SkillTemplateError("if 缺 {%endif%}",
                                         _line_of(source, parts[idx2][2]))
            return branches, else_body, idx3 + 1
        return branches, else_body, idx2 + 1


# ──────────────── 求值与渲染 ────────────────

class _Context:
    """作用域栈（for 循环变量 + loop 计数入栈，退出弹出）。"""

    def __init__(self, variables: Mapping[str, Any]) -> None:
        self._scopes: list[dict[str, Any]] = [dict(variables)]

    def push(self, frame: dict[str, Any]) -> None:
        self._scopes.append(frame)

    def pop(self) -> None:
        self._scopes.pop()

    def resolve(self, path: str) -> Any:
        segs = path.split(".")
        root = segs[0]
        for scope in reversed(self._scopes):
            if root in scope:
                val: Any = scope[root]
                for seg in segs[1:]:
                    if isinstance(val, Mapping) and seg in val:
                        val = val[seg]
                    elif isinstance(val, (list, tuple)) and seg.isdigit():
                        val = val[int(seg)]
                    else:
                        raise KeyError(path)
                return val
        raise KeyError(path)

    def has_root(self, path: str) -> bool:
        """路径首段是否在任一作用域（条件容错口径的分界判据）。"""
        root = path.split(".")[0]
        return any(root in scope for scope in self._scopes)


def _resolve_path(ctx: _Context, path: str, line: int) -> Any:
    try:
        return ctx.resolve(path)
    except KeyError:
        raise SkillTemplateError(f"变量缺失: {path}", line) from None


def _resolve_optional(ctx: _Context, path: str, line: int,
                      has_default: bool) -> Any:
    if has_default:
        try:
            return ctx.resolve(path)
        except KeyError:
            return _MISSING
    return _resolve_path(ctx, path, line)


_MISSING = object()


def skill_literal(value: Any) -> str:
    """Python 值 → SKILL 字面量（str 引号转义/bool→t,nil/None→nil/
    数值→repr/list,tuple→list(...) 函数形态/dict 显式报错 fail-loud）。"""
    if isinstance(value, str):
        esc = value.replace("\\", "\\\\").replace('"', '\\"') \
            .replace("\n", "\\n").replace("\t", "\\t")
        return f'"{esc}"'
    if isinstance(value, bool):
        return "t" if value else "nil"
    if value is None:
        return "nil"
    if isinstance(value, (int, float)):
        v = float(value)
        if v != v or v in (float("inf"), float("-inf")):
            raise SkillTemplateError(f"非有限数值不可渲染 SKILL 字面量: {value}")
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "list(" + " ".join(skill_literal(v) for v in value) + ")"
    raise SkillTemplateError(
        f"{type(value).__name__} 无 SKILL 字面量形态（模板变量只收 "
        "str/bool/int/float/None/list/tuple；dict 走 for 循环或 raw）")


def _render_nodes(nodes: list[_Node], ctx: _Context, out: list[str]) -> None:
    for node in nodes:
        if isinstance(node, _Text):
            out.append(node.s)
        elif isinstance(node, _Out):
            has_default = any(f[0] == "default" for f in node.filters)
            is_raw = any(f[0] == "raw" for f in node.filters)
            val = _resolve_optional(ctx, node.path, node.line, has_default)
            if val is _MISSING:
                val = next(farg for fname, farg in node.filters
                           if fname == "default")
            if is_raw:
                if not isinstance(val, str):
                    raise SkillTemplateError(
                        f"raw 过滤器要求 str 值（{node.path} 得 "
                        f"{type(val).__name__}）", node.line)
                out.append(val)
            else:
                out.append(skill_literal(val))
        elif isinstance(node, _For):
            seq: Any = _MISSING
            try:
                seq = ctx.resolve(node.iter_path)
            except KeyError:
                if node.iter_default is None:
                    raise SkillTemplateError(
                        f"变量缺失: {node.iter_path}", node.line) from None
            if seq is _MISSING:
                seq = node.iter_default
            if not isinstance(seq, (list, tuple)):
                raise SkillTemplateError(
                    f"for 迭代目标 {node.iter_path} 须为 list/tuple（得 "
                    f"{type(seq).__name__}）", node.line)
            for i, item in enumerate(seq):
                ctx.push({node.var: item,
                          "loop": {"index": i + 1, "index0": i}})
                _render_nodes(node.body, ctx, out)
                ctx.pop()
        elif isinstance(node, _If):
            for cond, body, line in node.branches:
                verdict = _eval_cond_tokens(cond, ctx, line)
                if verdict:
                    _render_nodes(body, ctx, out)
                    break
            else:
                _render_nodes(node.else_body, ctx, out)
        else:  # pragma: no cover - AST 节点封闭集合
            raise SkillTemplateError("未知 AST 节点")


def _resolve_cond_path(ctx: _Context, path: str, line: int) -> Any:
    """条件路径求值：首段存在但属性段缺失 → None（falsy——实例级可选键
    如 ``d.rot`` 的标准形态）；首段不存在 → fail loud（防拼写静默 falsy，
    #117 家族反像）。"""
    try:
        return ctx.resolve(path)
    except KeyError:
        if ctx.has_root(path):
            return None
        raise SkillTemplateError(f"变量缺失: {path}", line) from None


def _eval_cond_tokens(tokens: list[tuple[str, str]], ctx: _Context,
                      line: int) -> bool:
    parser = _CondParser(tokens, line,
                         lambda path: _resolve_cond_path(ctx, path, line))
    return bool(parser.parse())


def render_template(source: str, variables: Mapping[str, Any]) -> str:
    """模板源 + 变量 → SKILL 代码字符串（纯函数；同入参两跑逐字节同）。"""
    ast = _parse_template(source)
    ctx = _Context(variables)
    out: list[str] = []
    _render_nodes(ast, ctx, out)
    return "".join(out)


def _collect_vars(nodes: list[_Node], bound: set[str],
                  required: set[str], optional: set[str]) -> None:
    for node in nodes:
        if isinstance(node, _Out):
            root = node.path.split(".")[0]
            has_default = any(f[0] == "default" for f in node.filters)
            if root in bound:
                continue
            (optional if has_default else required).add(node.path)
        elif isinstance(node, _For):
            root = node.iter_path.split(".")[0]
            if root not in bound:
                (optional if node.iter_default is not None
                 else required).add(node.iter_path)
            _collect_vars(node.body, bound | {node.var, "loop"},
                          required, optional)
        elif isinstance(node, _If):
            for cond, body, _line in node.branches:
                for kind, val in cond:
                    if kind == "word" and val not in (
                            "and", "or", "not", "in", "True", "False",
                            "true", "false", "t", "nil", "None"):
                        root = val.split(".")[0]
                        if root not in bound:
                            required.add(val)
                _collect_vars(body, bound, required, optional)
            _collect_vars(node.else_body, bound, required, optional)


def list_template_var_info(source: str) -> dict[str, list[str]]:
    """模板变量盘点：{"required": [...], "optional": [...]}（sorted）。

    required=无 default 兜底的变量路径；optional=仅以 ``|default(...)``
    形态出现的变量（调用方可省略）；循环局部变量与 loop 计数不入列。
    """
    ast = _parse_template(source)
    required: set[str] = set()
    optional: set[str] = set()
    _collect_vars(ast, set(), required, optional)
    optional -= required
    return {"required": sorted(required), "optional": sorted(optional)}


def list_template_vars(source: str) -> list[str]:
    """必填变量路径清单（sorted；optional/循环局部不入列）。"""
    return list_template_var_info(source)["required"]


# ──────────────── 结构化 SKILL 代码生成器 ────────────────

def _indent_block(lines: list[str], indent: int) -> list[str]:
    pad = "  " * max(indent, 0)
    return [pad + ln if ln.strip() else ln for ln in lines]


def skill_call(name: str, *args: str, indent: int = 0) -> str:
    """函数调用行拼装：``name(arg1 arg2)``——args 为**已渲染**的 SKILL
    片段（值参数先经 :func:`skill_literal`，预成形表达式原样传入）；
    本函数只做确定性字符串拼装，不二次字面量化。"""
    line = f"{name}({'' if not args else ' '.join(args)})"
    if indent:
        line = "  " * indent + line
    return line


def skill_let(bindings: list[tuple[str, Any]], body: list[str],
              indent: int = 0) -> str:
    """let 块：``let( (name init name2)\\n  body...\\n)``——init=None 时只
    声明变量；bindings 依入参序直出（确定性）。"""
    bind_parts: list[str] = []
    for name, init in bindings:
        bind_parts.append(name if init is None else f"{name} {init}")
    lines = [f"let( ({' '.join(bind_parts)})", *_indent_block(body, 1), ")"]
    if indent:
        lines = _indent_block(lines, indent)
    return "\n".join(lines)


def skill_if(cond: str, then_body: list[str], else_body: list[str] | None = None,
             indent: int = 0) -> str:
    """if 语句块（SKILL then/else 关键字形态）：
    ``if( cond\\n  then ...\\n  else ...\\n)``。"""
    lines = [f"if( {cond}"]
    lines += _indent_block(["then", *_indent_block(then_body, 1)], 1)
    if else_body:
        lines += _indent_block(["else", *_indent_block(else_body, 1)], 1)
    lines.append(")")
    if indent:
        lines = _indent_block(lines, indent)
    return "\n".join(lines)


def skill_foreach(var: str, list_expr: str, body: list[str],
                  indent: int = 0) -> str:
    """foreach 循环块：``foreach( var list_expr\\n  body...\\n)``。"""
    lines = [f"foreach( {var} {list_expr}", *_indent_block(body, 1), ")"]
    if indent:
        lines = _indent_block(lines, indent)
    return "\n".join(lines)


# ──────────────── SKILL 语法守卫（lint） ────────────────

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_ASSIGN_TARGET_RE = re.compile(r"^[A-Za-z_]\w*(~>[A-Za-z_]\w*)?$")
_KW_ARG_RE = re.compile(r"\?[A-Za-z_]\w*")


def skill_lint_issues(code: str) -> list[dict[str, Any]]:
    """SKILL 语法守卫（纯函数）：返回 issues 列表，元素
    {"severity": "error"|"warning", "line": int, "code": str, "message": str}。

    检查面：括号配对（paren_balance）/引号闭合（quote_closure）/
    let 绑定形态（let_binding）/已知函数名白名单（unknown_function）/
    赋值目标形态（assignment_target）/残留模板标签（template_tag）。
    字符串字面量与 ``;`` 行注释内的括号/引号不计；空代码返回空列表。
    """
    issues: list[dict[str, Any]] = []

    def issue(severity: str, line: int, code_key: str, message: str) -> None:
        issues.append({"severity": severity, "line": line,
                       "code": code_key, "message": message})

    # 残留模板标签（未渲染直出即红）
    for i, raw_line in enumerate(code.splitlines(), 1):
        for tag in _OPEN_TAGS:
            if tag in raw_line:
                issue("error", i, "template_tag",
                      f"残留模板标签 {tag}（先 render 再落盘）")
                break

    depth = 0
    ident_before_paren: list[tuple[str, int]] = []
    depth_zero_eqs: list[tuple[int, str]] = []  # (line, target_text)
    last_depth_pos_line = 1

    lines = code.splitlines()
    for lineno, raw in enumerate(lines, 1):
        in_string = False
        in_comment = False
        i = 0
        while i < len(raw):
            ch = raw[i]
            if in_comment:
                i += 1
                continue
            if in_string:
                if ch == "\\" and i + 1 < len(raw):
                    i += 2
                    continue
                if ch == '"':
                    in_string = False
                i += 1
                continue
            if ch == ";":
                in_comment = True
                i += 1
                continue
            if ch == '"':
                in_string = True
                i += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    issue("error", lineno, "paren_balance",
                          "括号负深度（右括号多于左括号）")
                    depth = 0  # 防雪崩：钳回 0 继续收后续问题
            elif ch == "=" and depth == 0:
                prev = raw[:i]
                nxt = raw[i + 1:i + 2]
                if prev[-1:] in ("!", "<>", ">", "<") or nxt == "=":
                    i += 1
                    continue
                m = re.search(r"(\S+)\s*$", prev)
                target = m.group(1) if m else ""
                depth_zero_eqs.append((lineno, target))
            i += 1
        if in_string:
            issue("error", lineno, "quote_closure",
                  "字符串字面量跨行未闭合（SKILL 字符串单行闭合）")
        # 标识符紧跟 '(' → 调用头
        for m in re.finditer(r"([A-Za-z_]\w*)\s*\(", raw):
            if not _inside_string_or_comment(raw, m.start(1)):
                ident_before_paren.append((m.group(1), lineno))
        if raw.strip():
            last_depth_pos_line = lineno

    if depth > 0:
        issue("error", last_depth_pos_line, "paren_balance",
              f"末尾仍有 {depth} 层未闭合左括号")

    # 函数头白名单：只校验 ``ident( `` 调用形态（生成面唯一调用形态）——
    # ``(`` 后首标识符不校验（let 绑定表 (cv x)/数据列表 (\"a\" \"b\") 非
    # 函数调用，lisp 括号≠调用）。docstring 同步口径。
    for name, lineno in ident_before_paren:
        _check_call_head(name, lineno, issue)

    for lineno, target in depth_zero_eqs:
        if not _ASSIGN_TARGET_RE.match(target):
            issue("error", lineno, "assignment_target",
                  f"非法赋值目标 {target!r}（var = expr / var~>attr = expr）")

    # let 头后须紧跟绑定表 '('（\blet\b 防 letseq 误报）
    for lineno, raw in enumerate(lines, 1):
        for m in re.finditer(r"\blet\b\s*([^(\s]|$)", raw):
            if _inside_string_or_comment(raw, m.start(1)):
                continue
            issue("error", lineno, "let_binding",
                  "let 头后必须紧跟绑定表 '('（let( (name init) ...)）")

    return issues


def _check_call_head(name: str, lineno: int,
                     issue: Any) -> None:
    if name in KNOWN_SKILL_FUNCTIONS:
        return
    # warning 级（非 error）：Cadence API 面远大于白名单子集，用户 .il
    # 引用词表外函数是常态；模板生成面超词表由本仓测试零 issues 钉死。
    issue("warning", lineno, "unknown_function",
          f"未知函数名 {name!r}（不在 KNOWN_SKILL_FUNCTIONS 白名单；"
          "模板生成面扩展须同步白名单单源）")


def _inside_string_or_comment(raw: str, pos: int) -> bool:
    """粗判 pos 是否落在字符串字面量或注释内（lint 专用近似——
    逐字符状态机已在主扫描处理精确面，此处只做 finditer 复核）。"""
    in_string = False
    in_comment = False
    i = 0
    while i < pos:
        ch = raw[i]
        if in_comment:
            i += 1
            continue
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == ";":
            in_comment = True
        elif ch == '"':
            in_string = True
        i += 1
    return in_string or in_comment
