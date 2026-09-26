"""DP-18 C9 文献挖掘管线（降级路线全链）——scripts 唯一所有者批内工具。

规格书：docs/plan_deepdive_specs_20260924.md §18.2；判据预声明：
runs/df6_dp18c9/criteria.md（2026-09-24 开工前落盘）。

六级（降级路线：MinerU Windows VLM 后端需 GPU 不可用→PyMuPDF 文本层+md 直读）：
  1. 矿源层：仓内 md 直读（逐行文本单元+行号锚点）+ PDF→pymupdf 逐页文本层；
  2. 公式层：unicode→LaTeX 确定性翻译→sympy parse_latex(backend="lark")，
     任何解析失败如实 UNPARSEABLE 不猜（antlr 后端需 antlr4==4.11 与
     omegaconf 钉的 ==4.9.* 冲突，故走 lark 纯 Python 后端）；
  3. 抽取层：确定性 regex（公式定义式/变量集合/斜杠数值表）+显式变量-单位表；
     LLM 抽取接口预留不实现（铁律 #7 LLM 永不产数字，见 llm_schema_extract）；
  4. 双门：门 A 引文回链（formula_raw 必须在重读锚点行原样在场，否则剥除+
     cannot_answer——PaperQA2 哨兵移植）；门 B 数值回收（独立 AST 求值器
     在 8 档判据点求值 vs 预声明真值 ≤1.4% 逐档，#118/#341 独立参考实现，
     不走 sympy 求值路径并与 sympy 路径交叉对拍）；
  5. promote 面：双门全过→候选 JSON（带 provenance+register_symbolic_formula
     兼容 terms/coefficients+AST 白名单校验证明）。rules.yaml 零改动（禁改
     清单），晋级随 DP-3 锚注册表批（见文末接口注释）；
  6. 判据：γ(εr) 全管线回收 8 档逐档 ≤1.4% + 幻觉负例三连拦截。

独立实现声明：本脚本不 import rfauto（矿源与判据独立性）——AST 白名单
校验器按 core/calculators.py:3206-3236 词表独立复刻，与仓库机制的一致性
由定向测试双检钉住（tests/unit/test_lit_mine_pipeline.py）。

语料约定（本批 corpus convention，显式声明）：
  - md 行内公式以 **（加粗）、行尾、中文标点（，。；）、全角括号（）为界
    （公式上标一律半角括号，全角（）=注释起点）；
  - bullet：以可选缩进+``- `` 开的行，后续缩进行归属同 bullet 直到下一
    bullet/标题/EOF；pdf 文本以页为配对域（数值表与变量集合的配对只在
    同组内进行）；
  - 表抽取：同 bullet 内「声明变量集合 x∈{…}」配「元素个数相等的斜杠
    数值表」，个数不等=整表拒绝（table_mismatch，不猜）。

用法（零网络）：
    python scripts/lit_mine_pipeline.py \
        --docs docs/rf_template_references.md --out runs/df6_dp18c9
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import platform
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 预声明真值（runs/df6_dp18c9/criteria.md，2026-09-24 落盘；出处
# docs/rf_template_references.md §11.1 L319-323，--refit-cps-gamma 可复现）。
# 门 B 的裁判对象=本表，而非 calculators.py 常数（后者只读不入管线）。
# ---------------------------------------------------------------------------
GAMMA_EPSR_GRID: tuple[float, ...] = (1.5, 2.2, 3.0, 3.66, 4.4, 6.15, 10.2, 12.9)
GAMMA_CALIB: tuple[float, ...] = (1.706, 1.547, 1.446, 1.392, 1.348, 1.281, 1.206, 1.180)
GAMMA_REL_TOL = 0.014  # 1.4%，§11.1 独立验证族 max|err| 口径


# ---------------------------------------------------------------------------
# 变量-单位表（抽取层显式声明；表外自由符号=拒绝，不猜）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VariableDecl:
    """源文写法 → LaTeX 形 → 求值/登记用安全标识符 + 单位。"""

    symbol: str  # 源文 unicode 写法
    latex: str  # LaTeX 形（sympy 符号名 = latex 去掉首部反斜杠）
    python: str  # 独立求值器/登记表内的安全变量名
    unit: str
    description: str
    registry_key: str = ""  # 作为注册表输出键的名字（空=用 python 名）

    @property
    def sympy_name(self) -> str:
        return self.latex[1:] if self.latex.startswith("\\") else self.latex

    @property
    def out_key(self) -> str:
        return self.registry_key or self.python


DECLARED_VARIABLES: tuple[VariableDecl, ...] = (
    VariableDecl("εr", r"\epsilon_{r}", "er", "dimensionless",
                 "相对介电常数（CPS 基板）"),
    VariableDecl("γ", r"\gamma", "gamma", "dimensionless",
                 "CPS 有效厚度因子 γ(εr)=h_eff/h",
                 registry_key="cps_gamma"),
)


def variable_table() -> list[dict[str, str]]:
    return [
        {"symbol": v.symbol, "latex": v.latex, "python": v.python,
         "unit": v.unit, "description": v.description}
        for v in DECLARED_VARIABLES
    ]


# ---------------------------------------------------------------------------
# 第 1 级：矿源层
# ---------------------------------------------------------------------------
@dataclass
class TextUnit:
    """一个带锚点的文本单元：md=行（锚 L<n>），pdf=页（锚 p<n>）。"""

    doc: str
    kind: str  # "md" | "pdf"
    anchor: str
    line_no: int  # md：1-based 行号；pdf：页号
    text: str


def iter_md_units(path: Path, doc_label: str | None = None) -> list[TextUnit]:
    """md 直读：逐行 utf-8 文本单元。"""
    label = doc_label or path.name
    units: list[TextUnit] = []
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            units.append(TextUnit(doc=label, kind="md", anchor=f"L{i}",
                                  line_no=i, text=line.rstrip("\n")))
    return units


def read_pdf_units(path: Path, doc_label: str | None = None) -> tuple[
        list[TextUnit], bool]:
    """PDF→pymupdf 文本层：逐页 get_text()（按行拆分为文本单元）。

    返回 (units, pdf_available)。pymupdf 未安装时返回 ([], False)——
    md-only 如实降级，不伪造矿源。
    """
    try:
        import pymupdf
    except ImportError:
        return [], False
    label = doc_label or path.name
    units: list[TextUnit] = []
    with pymupdf.open(str(path)) as doc:
        for pno, page in enumerate(doc, start=1):
            for line in page.get_text().splitlines():
                units.append(TextUnit(doc=label, kind="pdf", anchor=f"p{pno}",
                                      line_no=pno, text=line))
    return units, True


def load_corpus(sources: Sequence[str | Path]) -> tuple[
        list[TextUnit], list[dict[str, str]]]:
    """按扩展名分派矿源；返回 (units, 每源登记)。"""
    units: list[TextUnit] = []
    registry: list[dict[str, str]] = []
    pdf_available = True
    for src in sources:
        p = Path(src)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if p.suffix.lower() == ".pdf":
            pdf_units, pdf_available = read_pdf_units(p)
            if not pdf_available:
                registry.append({"source": str(p), "kind": "pdf",
                                 "status": "pdf_unavailable_md_only_fallback"})
                continue
            units.extend(pdf_units)
            registry.append({"source": str(p), "kind": "pdf",
                             "units": str(len(pdf_units)), "status": "ok"})
        else:
            u = iter_md_units(p)
            units.extend(u)
            registry.append({"source": str(p), "kind": "md",
                             "units": str(len(u)), "status": "ok"})
    return units, registry


# ---------------------------------------------------------------------------
# 第 2 级：公式层（unicode→LaTeX→sympy parse_latex，失败如实 UNPARSEABLE）
# ---------------------------------------------------------------------------
class FormulaParseError(Exception):
    """公式层失败（UNPARSEABLE / 未知符号）——调用方如实登记，不猜。"""


_UNICODE_LATEX_MAP: tuple[tuple[str, str], ...] = (
    ("εr", r"\epsilon_{r}"),  # 先长串（εr 含 ε）
    ("γ", r"\gamma"),
    ("ε", r"\epsilon"),
    ("·", r" \cdot "),
    ("−", "-"),  # U+2212 minus
    ("×", r" \cdot "),
    ("–", "-"),  # en dash
)


def to_latex(body: str) -> str:
    """确定性 unicode→LaTeX 翻译（变量表驱动，无任何猜测补全）。"""
    out = body
    for raw, latex in _UNICODE_LATEX_MAP:
        out = out.replace(raw, latex)
    out = re.sub(r"\^\(([^()]+)\)", r"^{\1}", out)  # ^(...) → ^{...}
    return out.strip()


def parse_latex_body(body_latex: str) -> Any:
    """sympy parse_latex（lark 后端）解析公式体；失败抛 FormulaParseError。"""
    try:
        from sympy.parsing.latex import parse_latex
    except ImportError as exc:  # pragma: no cover - 环境缺依赖如实暴露
        raise FormulaParseError(f"sympy parse_latex 不可用: {exc}") from exc
    try:
        expr = parse_latex(body_latex, backend="lark")
    except Exception as exc:
        raise FormulaParseError(f"UNPARSEABLE: {exc}") from exc
    if expr is None:
        raise FormulaParseError("UNPARSEABLE: 解析器返回 None")
    return expr


def sympy_symbols_map(expr: Any) -> dict[str, Any]:
    """把表达式自由符号映射到声明表（sympy 符号名=latex 去首反斜杠）。

    表外自由符号=FormulaParseError（UNKNOWN_SYMBOL，不猜）。
    """
    declared = {v.sympy_name: v for v in DECLARED_VARIABLES}
    mapping: dict[str, Any] = {}
    for sym in expr.free_symbols:
        name = str(sym)
        if name not in declared:
            raise FormulaParseError(f"UNKNOWN_SYMBOL: {name!r} 不在声明变量表")
        mapping[name] = sym
    return mapping


# ---------------------------------------------------------------------------
# 第 3 级：抽取层（确定性 regex；LLM 抽取接口预留不实现）
# ---------------------------------------------------------------------------
# 公式定义式：fn(arg) = body（fn 含希腊/拉丁字母；body 到中文标点/加粗/
# 全角括号止——语料约定：全角（）=注释起点，公式上标一律半角括号）
_FORMULA_DEF_RE = re.compile(
    r"(?P<lhs>[A-Za-z_\u0370-\u03FF][\w\u0370-\u03FF]*\s*"
    r"\(\s*(?P<arg>[^\s()，。；;]{1,8})\s*\)\s*=\s*)"
    r"(?P<body>[^，。；;*=\n（）]+)")
# 变量集合：x∈{a,b,...}
_SET_RE = re.compile(r"(?P<var>[^\s∈{,，]+)\s*∈\s*\{(?P<set>[^}]+)\}")
# 斜杠数值表：v1/v2/…/vN（前后不粘数字/点/斜杠）
_VALUE_LIST_RE = re.compile(
    r"(?<![\d.])(?P<vals>\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)+)(?![\d./])")
_BULLET_OPEN_RE = re.compile(r"^\s*-\s")


@dataclass
class RawExtraction:
    """一个原始抽取（含出处锚点；状态机驱动，非 OK 状态如实保留）。"""

    candidate_id: str
    formula_raw: str
    lhs: str
    body: str
    arg: str
    doc: str
    line_no: int
    line_text: str
    status: str  # extracted / out_of_scope / unparseable / unknown_symbol ...
    formula_latex: str = ""
    python_expr: str = ""
    detail: str = ""


@dataclass
class TableExtraction:
    """变量集合（网格）+斜杠数值表配对（同 bullet 内、个数相等才成立）。"""

    var: str
    grid: tuple[float, ...]  # ∈{...} 集合元素（判据点网格）
    values: tuple[float, ...]  # 斜杠数值表（与集合等长）
    doc: str
    bullet_anchor: str
    set_line: int
    vals_line: int


def group_bullets(units: list[TextUnit]) -> list[list[TextUnit]]:
    """文本分组：md 按 bullet（``- `` 开行起新组，缩进续行归属同组）；
    pdf 按页（同页连续行同组——表配对以页为域）。非 bullet 正文行
    独立成组（哨兵统计）。"""
    groups: list[list[TextUnit]] = []
    current: list[TextUnit] | None = None
    for u in units:
        if u.kind == "md":
            if _BULLET_OPEN_RE.match(u.text):
                current = [u]
                groups.append(current)
            elif u.text.lstrip().startswith("#"):
                current = None
            elif current is not None:
                current.append(u)
            else:
                current = [u]
                groups.append(current)
        else:  # pdf：同页连续行归入同组
            if (current is not None and current[0].kind == "pdf"
                    and current[0].line_no == u.line_no):
                current.append(u)
            else:
                current = [u]
                groups.append(current)
    return groups


def extract_formula_defs(group: list[TextUnit]) -> list[RawExtraction]:
    """在一个文本组内抽公式定义式 fn(decl)=body。

    out_of_scope（自变量不在声明表/体不含声明变量/体不含数字）如实登记，
    不判罚不判失败——它们不是本管线的目标公式。
    """
    out: list[RawExtraction] = []
    declared_args = {v.symbol: v for v in DECLARED_VARIABLES}
    decl_symbols = [v.symbol for v in DECLARED_VARIABLES]
    for u in group:
        for m in _FORMULA_DEF_RE.finditer(u.text):
            lhs = m.group("lhs").strip()
            arg, body = m.group("arg"), m.group("body").strip()
            status = "extracted"
            if arg not in declared_args or not any(s in body for s in decl_symbols) or not any(ch.isdigit() for ch in body):
                status = "out_of_scope"
            out.append(RawExtraction(
                candidate_id="", formula_raw=(m.group("lhs") + body),
                lhs=lhs, body=body,
                arg=arg, doc=u.doc, line_no=u.line_no, line_text=u.text,
                status=status))
    return out


def extract_tables(
        group: list[TextUnit]) -> list[tuple[TableExtraction | None, str]]:
    """抽「声明变量集合 + 同组内个数相等的斜杠数值表」配对。

    配对规则：同组内与集合等长的数值表必须唯一（多张且互不一致=歧义拒绝）；
    无等长表=配对失败。两者都如实返回，不猜。
    """
    declared = {v.symbol: v for v in DECLARED_VARIABLES}
    results: list[tuple[TableExtraction | None, str]] = []
    group_lines = [(u.line_no, u.text) for u in group]
    for u in group:
        for sm in _SET_RE.finditer(u.text):
            var = sm.group("var")
            if var not in declared:
                continue  # 非声明变量集合（如 w/gap 几何档）：跳过
            try:
                set_vals = tuple(float(x) for x in sm.group("set").split(","))
            except ValueError:
                results.append((None,
                                f"var={var} set@L{u.line_no} 元素非数值"))
                continue
            matches: list[tuple[int, tuple[float, ...]]] = []
            for lno, text in group_lines:
                for vm in _VALUE_LIST_RE.finditer(text):
                    vals = tuple(float(x)
                                 for x in vm.group("vals").split("/"))
                    if len(vals) == len(set_vals):
                        matches.append((lno, vals))
            unique_vals = {vals for _, vals in matches}
            if not unique_vals:
                results.append((None, f"var={var} 集合无同组等长数值表"))
            elif len(unique_vals) > 1:
                results.append((None,
                                f"var={var} 同组多张等长数值表且互不一致"
                                "——歧义拒绝"))
            else:
                vals_line, vals = matches[0]
                bullet_anchor = f"L{group[0].line_no}"
                results.append((TableExtraction(
                    var=var, grid=set_vals, values=vals, doc=u.doc,
                    bullet_anchor=bullet_anchor,
                    set_line=u.line_no, vals_line=vals_line), "ok"))
    return results


def llm_schema_extract(unit_text: str) -> dict[str, Any]:
    """LLM 抽取接口（预留不实现——本批零 LLM 调用）。

    规格书 §18.2 的「schema 约束 LLM 抽取」段在本批以确定性 regex/sympy
    管线替代（确定性内核铁律：LLM 永不产生物理数字）。若未来接入 LLM：
    只允许其回填结构字段 {formula_latex, variables[{symbol,unit}], domain,
    source{doc,anchor}}；一切数值仍由门 B 的确定性求值器 vs 仓内真值裁定，
    且候选必须过门 A 引文回链（formula_raw 在场）才能 promote。
    本 stub 调用即抛 NotImplementedError（显式，不静默）。
    """
    raise NotImplementedError(
        "LLM 抽取段本批未接线（确定性 regex/sympy 管线替代，铁律 #7）；"
        "接口契约见本 docstring")


# ---------------------------------------------------------------------------
# 独立求值器（门 B 裁判路径）：python 表达式 + AST 白名单（复刻
# core/calculators.py:3206-3236 词表——常量/声明名/四则幂/一元±/sqrt·log）
# ---------------------------------------------------------------------------
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
_ALLOWED_FUNCS = frozenset({"sqrt", "log"})


def to_python_expr(body: str) -> str:
    """确定性 unicode→python 表达式翻译（独立于 to_latex 的求值路径）。"""
    out = body
    for v in DECLARED_VARIABLES:
        out = out.replace(v.symbol, v.python)
    for raw, repl in (("·", "*"), ("−", "-"), ("×", "*"), ("–", "-")):
        out = out.replace(raw, repl)
    out = re.sub(r"\^", "**", out)
    return re.sub(r"\s+", "", out)


def validate_ast_whitelist(expr_str: str, allowed_names: frozenset[str]) -> None:
    """复刻词表的 AST 白名单校验：违规 raise ValueError（显式不静默）。

    与仓库 _validate_symbolic_node 的一致性由定向测试双检钉住（本脚本
    不 import rfauto，保持矿源/判据独立性）。
    """
    tree = ast.parse(expr_str, mode="eval")

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            walk(node.body)
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            return
        if isinstance(node, ast.Name) and node.id in allowed_names:
            return
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
            walk(node.left)
            walk(node.right)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            walk(node.operand)
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _ALLOWED_FUNCS and not node.keywords \
                and len(node.args) == 1:
            walk(node.args[0])
            return
        raise ValueError(
            f"表达式含白名单外节点: {type(node).__name__}（词表=常量/声明变量/"
            "四则幂/一元±/sqrt·log，同 core/calculators.py 0cz 口径）")

    walk(tree)


def compile_whitelisted(expr_str: str, allowed_names: frozenset[str]) -> Any:
    """白名单校验+编译（independent eval 路径的唯一入口）。"""
    validate_ast_whitelist(expr_str, allowed_names)
    return compile(ast.parse(expr_str, mode="eval"), "<litmine:expr>", "eval")


def eval_compiled(code: Any, namespace: dict[str, float]) -> float:
    """确定性求值（math 域，__builtins__ 清空；eval 安全性由白名单编译钉住）。"""
    env = {"sqrt": math.sqrt, "log": math.log, "__builtins__": {}}
    return float(eval(code, env, dict(namespace)))  # 白名单钉安全，eval 非逃逸面


# ---------------------------------------------------------------------------
# sympy 参考路径（抽取侧求值；与门 B 独立路径交叉对拍）
# ---------------------------------------------------------------------------
def eval_sympy(expr: Any, var: VariableDecl, value: float) -> float:
    sub = {v.sympy_name: value for v in DECLARED_VARIABLES}
    return float(expr.evalf(subs=sub))


def decompose_to_register_form(expr: Any) -> tuple[list[str], list[float]] | None:
    """线性分解 Σ cᵢ·termᵢ（register_symbolic_formula 兼容形态）。

    只处理 常数 + 单变量幂项 的和；其余结构返回 None（不硬拆）。
    """
    import sympy

    py_of = {v.sympy_name: v.python for v in DECLARED_VARIABLES}
    terms: list[str] = []
    coeffs: list[float] = []
    for part in sympy.Add.make_args(sympy.expand(expr)):
        if part.is_Number:
            terms.append("1")
            coeffs.append(float(part))
            continue
        c, rest = part.as_coeff_Mul()
        if len(rest.free_symbols) != 1:
            return None
        sym = next(iter(rest.free_symbols))
        base, exp = rest.as_base_exp()
        if base != sym or not exp.is_Number:
            return None
        terms.append(f"{py_of[str(sym)]}**({float(exp)})")
        coeffs.append(float(c))
    return terms, coeffs


# ---------------------------------------------------------------------------
# 第 4 级：双门
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    """过公式层+抽取层筛选的候选（待双门）。"""

    candidate_id: str
    formula_raw: str  # 源文原样子串（门 A 回链对象）
    formula_latex: str
    python_expr: str
    lhs: str
    output_var: VariableDecl
    input_var: VariableDecl
    doc: str
    line_no: int
    line_text: str
    sympy_expr: Any = None
    code: Any = None
    register_form: tuple[list[str], list[float]] | None = None


def gate_a_backlink(candidate: Candidate, sources: Sequence[str | Path]) -> dict[
        str, Any]:
    """门 A 引文回链：重读源文档锚点，formula_raw 必须原样在场。

    md=重读锚点行；pdf=重读锚点页文本层。不在场→剥除+cannot_answer
    （PaperQA2 哨兵移植：无证据必答 cannot，不许编造）。fresh read：
    从磁盘重读，不用抽取时的内存文本。
    """
    for src in sources:
        p = Path(src)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if p.name != candidate.doc and str(p) != candidate.doc:
            continue
        if p.suffix.lower() == ".pdf":
            page_units, avail = read_pdf_units(p)
            if not avail:
                return {"pass": False, "cannot_answer": True,
                        "reason": "pdf 矿源文本层不可用（pymupdf 缺失）"}
            page_text = "\n".join(u.text for u in page_units
                                  if u.line_no == candidate.line_no)
            ok = candidate.formula_raw in page_text
            return {"pass": ok, "cannot_answer": not ok,
                    "anchor": f"p{candidate.line_no}", "doc": candidate.doc,
                    "formula_raw": candidate.formula_raw,
                    "reason": "" if ok else "formula_raw 不在重读锚点页文本层"
                                            "（回链断开）"}
        with p.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        if candidate.line_no > len(lines):
            return {"pass": False, "cannot_answer": True,
                    "reason": f"锚点行 {candidate.line_no} 超出文档行数"}
        fresh = lines[candidate.line_no - 1].rstrip("\n")
        ok = candidate.formula_raw in fresh
        return {"pass": ok, "cannot_answer": not ok,
                "anchor": f"L{candidate.line_no}", "doc": candidate.doc,
                "formula_raw": candidate.formula_raw,
                "reason": "" if ok else "formula_raw 不在重读锚点行原文中（回链断开）"}
    return {"pass": False, "cannot_answer": True,
            "reason": f"源文档 {candidate.doc} 不在矿源清单（回链无主）"}


def gate_b_numeric(candidate: Candidate, grid: Sequence[float],
                   truth: Sequence[float], rel_tol: float) -> dict[str, Any]:
    """门 B 数值回收：独立求值器逐点求值 vs 预声明真值（#118/#341 口径）。

    同时与 sympy 参考路径交叉对拍（两路径 rel 差 ≤1e-9 是断言项）。
    """
    per_point: list[dict[str, Any]] = []
    max_rel = 0.0
    max_cross = 0.0
    for x, y_true in zip(grid, truth, strict=True):
        y_indep = eval_compiled(candidate.code, {candidate.input_var.python: x})
        rel = abs(y_indep - y_true) / abs(y_true)
        y_sympy = eval_sympy(candidate.sympy_expr, candidate.input_var, x)
        cross = abs(y_indep - y_sympy) / abs(y_indep) if y_indep != 0 else abs(y_indep - y_sympy)
        max_rel = max(max_rel, rel)
        max_cross = max(max_cross, cross)
        per_point.append({candidate.input_var.python: x, "truth": y_true,
                          "indep_eval": y_indep, "sympy_eval": y_sympy,
                          "rel_err": rel, "cross_path_rel": cross})
    return {
        "pass": max_rel <= rel_tol and max_cross <= 1e-9,
        "per_point": per_point,
        "max_rel_err": max_rel,
        "max_cross_path_rel": max_cross,
        "rel_tol": rel_tol,
        "evaluator": "independent AST whitelist + math（非 sympy 路径）",
    }


# ---------------------------------------------------------------------------
# 第 5/6 级：promote 面 + 判据驱动
# ---------------------------------------------------------------------------
def build_candidates(extractions: list[RawExtraction]) -> tuple[list[Candidate],
        list[RawExtraction]]:
    """公式层处理抽取项：OK→Candidate；失败→原样保留（如实登记）。"""
    candidates: list[Candidate] = []
    failed: list[RawExtraction] = []
    out_of_scope: list[RawExtraction] = []
    numbered = 0
    for ext in extractions:
        if ext.status == "out_of_scope":
            out_of_scope.append(ext)
            continue
        numbered += 1
        ext.candidate_id = f"cand-{ext.doc}-L{ext.line_no}-{numbered:02d}"
        try:
            body_latex = to_latex(ext.body)
            expr = parse_latex_body(body_latex)
            sympy_symbols_map(expr)  # 表外自由符号在此拒绝（UNKNOWN_SYMBOL）
        except FormulaParseError as exc:
            ext.status = "unparseable" if "UNPARSEABLE" in str(exc) else "unknown_symbol"
            ext.detail = str(exc)
            ext.formula_latex = to_latex(ext.body)
            failed.append(ext)
            continue
        fn_sym = re.match(r"^([^\s(（]+)", ext.lhs)
        out_decl = next((v for v in DECLARED_VARIABLES
                         if fn_sym and v.symbol == fn_sym.group(1)), None)
        in_decl = next((v for v in DECLARED_VARIABLES if v.symbol == ext.arg),
                       None)
        if out_decl is None or in_decl is None:
            ext.status = "out_of_scope"
            ext.detail = f"lhs 首符号/自变量不在声明表: {ext.lhs!r}/{ext.arg!r}"
            ext.formula_latex = body_latex
            failed.append(ext)
            continue
        py_expr = to_python_expr(ext.body)
        try:
            code = compile_whitelisted(py_expr, frozenset({v.python for v in DECLARED_VARIABLES}))
        except (ValueError, SyntaxError) as exc:
            ext.status = "whitelist_reject"
            ext.detail = str(exc)
            ext.formula_latex = body_latex
            ext.python_expr = py_expr
            failed.append(ext)
            continue
        candidates.append(Candidate(
            candidate_id=ext.candidate_id, formula_raw=ext.formula_raw,
            formula_latex=body_latex, python_expr=py_expr, lhs=ext.lhs,
            output_var=out_decl, input_var=in_decl, doc=ext.doc,
            line_no=ext.line_no, line_text=ext.line_text, sympy_expr=expr,
            code=code, register_form=decompose_to_register_form(expr)))
    return candidates, failed + out_of_scope


def run_pipeline(
    sources: Sequence[str | Path],
    truth_grid: Sequence[float] = GAMMA_EPSR_GRID,
    truth_values: Sequence[float] = GAMMA_CALIB,
    rel_tol: float = GAMMA_REL_TOL,
) -> dict[str, Any]:
    """六级管线主驱动（矿源→…→双门→promote 判定），返回结构化报告 dict。"""
    units, source_registry = load_corpus(sources)
    groups = group_bullets(units)

    extractions: list[RawExtraction] = []
    tables: list[TableExtraction] = []
    table_notes: list[str] = []
    units_without_formula = 0
    for group in groups:
        defs = extract_formula_defs(group)
        in_scope = [d for d in defs if d.status != "out_of_scope"]
        if not in_scope:
            units_without_formula += 1
        extractions.extend(defs)
        for tab, note in extract_tables(group):
            if tab is not None:
                tables.append(tab)
            else:
                table_notes.append(note)

    candidates, rejected = build_candidates(extractions)

    # 表抽取一致性：抽到的（网格, 数值表）vs 预声明真值（两者一致才可信）
    table_check: dict[str, Any] = {"pass": False, "tables": [], "notes": table_notes}
    for tab in tables:
        decl = next(v for v in DECLARED_VARIABLES if v.symbol == tab.var)
        entry = {"var_python": decl.python, "grid": list(tab.grid),
                 "values": list(tab.values),
                 "doc": tab.doc, "bullet_anchor": tab.bullet_anchor,
                 "equals_truth_grid": tuple(tab.grid) == tuple(truth_grid),
                 "equals_truth_values": tuple(tab.values) == tuple(truth_values)}
        table_check["tables"].append(entry)
    relevant = [t for t in table_check["tables"] if t["var_python"] != "gamma"]
    table_check["pass"] = any(t["equals_truth_values"] and t["equals_truth_grid"]
                              for t in relevant)

    gate_a_results: dict[str, dict[str, Any]] = {}
    gate_b_results: dict[str, dict[str, Any]] = {}
    promoted: list[Candidate] = []
    for cand in candidates:
        ga = gate_a_backlink(cand, sources)
        gate_a_results[cand.candidate_id] = ga
        if not ga["pass"]:
            continue
        gb = gate_b_numeric(cand, truth_grid, truth_values, rel_tol)
        gate_b_results[cand.candidate_id] = gb
        if gb["pass"]:
            promoted.append(cand)

    # gamma 自身定义式（lhs=γ(εr)）不允许当"表"——表检查只认 εr 表（上面已滤）
    report: dict[str, Any] = {
        "task": "DP-18 C9 文献挖掘管线（降级路线全链，2026-09-24）",
        "criteria": "runs/df6_dp18c9/criteria.md（开工前预声明）",
        "env": {
            "python": platform.python_version(),
            "sympy": _safe_version("sympy"),
            "lark": _safe_version("lark"),
            "pymupdf": _safe_version("pymupdf"),
            "parse_backend": "lark",
            "antlr_note": "antlr 后端需 antlr4==4.11 与 omegaconf(==4.9.*) 冲突，"
                          "改用 lark 后端；antlr4 维持 4.9.3",
        },
        "sources": source_registry,
        "variable_table": variable_table(),
        "extraction_stats": {
            "text_units": len(units),
            "groups": len(groups),
            "formula_defs_total": len(extractions),
            "in_scope": sum(1 for e in extractions if e.status == "extracted"),
            "out_of_scope": sum(1 for e in extractions if e.status == "out_of_scope"),
            "units_without_formula": units_without_formula,
        },
        "extractions": [_ext_to_dict(e) for e in extractions],
        "rejected": [_ext_to_dict(e) for e in rejected],
        "tables": table_check,
        "gates": {
            "A_backlink": gate_a_results,
            "B_numeric": {k: _gb_to_dict(v) for k, v in gate_b_results.items()},
        },
        "cannot_answer": {
            "units_without_formula": units_without_formula,
            "sentinel_active": True,
            "stripped_candidates": [
                cid for cid, ga in gate_a_results.items() if not ga["pass"]],
        },
        "promoted_ids": [c.candidate_id for c in promoted],
        "rules_promotion": "rules.yaml 零改动（禁改清单）；晋级随 DP-3 锚注册表批",
    }
    report["promoted"] = [_cand_to_dict(c, gate_a_results[c.candidate_id],
                                        gate_b_results[c.candidate_id])
                          for c in promoted]
    return report


def _safe_version(module: str) -> str:
    try:
        mod = __import__(module)
        return str(getattr(mod, "__version__", "unknown"))
    except Exception:
        return "unavailable"


def _ext_to_dict(e: RawExtraction) -> dict[str, Any]:
    return {"candidate_id": e.candidate_id, "status": e.status,
            "formula_raw": e.formula_raw, "lhs": e.lhs, "arg": e.arg,
            "body": e.body, "formula_latex": e.formula_latex,
            "python_expr": e.python_expr, "doc": e.doc,
            "anchor": f"L{e.line_no}", "detail": e.detail}


def _gb_to_dict(gb: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in gb.items() if k != "per_point"}
    out["per_point"] = gb["per_point"]
    return out


def _cand_to_dict(c: Candidate, ga: dict[str, Any], gb: dict[str, Any]) -> dict[
        str, Any]:
    ast_proof: dict[str, Any] = {"passed": True,
                                 "validator": "复刻 core/calculators.py:3206-3236 词表",
                                 "expr": c.python_expr,
                                 "allowed_funcs": sorted(_ALLOWED_FUNCS)}
    register: dict[str, Any] = {"compatible": c.register_form is not None}
    if c.register_form is not None:
        terms, coeffs = c.register_form
        register.update({"terms": terms, "coefficients": coeffs,
                         "note": "Σ cᵢ·termᵢ 线性形态；term 串过复刻 AST 白名单"
                                 "（与仓库 0cz 机制一致性由定向测试双检）"})
    return {
        "candidate_id": c.candidate_id,
        "status": "candidate（双门全过实验态候选，未入库；登记随 DP-3 锚注册表批）",
        "output_key": c.output_var.out_key,
        "formula_raw": c.formula_raw,
        "formula_latex": c.formula_latex,
        "python_expr": c.python_expr,
        "variables": [{"symbol": c.input_var.symbol, "unit": c.input_var.unit}],
        "domain": {c.input_var.python: [min(GAMMA_EPSR_GRID), max(GAMMA_EPSR_GRID)]},
        "source": {"doc": c.doc, "anchor": f"L{c.line_no}",
                   "line_text": c.line_text.strip()},
        "gate_a_backlink": ga,
        "gate_b_numeric": gb,
        "ast_whitelist": ast_proof,
        "register_symbolic_formula_form": register,
        "provenance": {
            "pipeline": "scripts/lit_mine_pipeline.py（确定性 regex+sympy lark，"
                        "零 LLM 零网络）",
            "truth_source": "docs/rf_template_references.md §11.1 L319-323"
                            "（--refit-cps-gamma 可复现）",
            "criteria": "runs/df6_dp18c9/criteria.md",
            "llm_role": "无（接口预留 llm_schema_extract；铁律 #7）",
        },
    }


# ---------------------------------------------------------------------------
# 幻觉负例（判据 G2）：临时目录注入语料，docs/ 零触碰
# ---------------------------------------------------------------------------
def run_hallucination_negatives(
    truth_grid: Sequence[float] = GAMMA_EPSR_GRID,
    truth_values: Sequence[float] = GAMMA_CALIB,
    rel_tol: float = GAMMA_REL_TOL,
) -> dict[str, Any]:
    """三连负例：(a) 篡改常数式 vs 真表；(b) 回链断开；(c) 无公式文档。"""
    results: dict[str, Any] = {}
    tmp = Path(tempfile.mkdtemp(prefix="litmine_neg_"))
    grid_str = ",".join(str(x) for x in truth_grid)
    vals_str = "/".join(str(v) for v in truth_values)

    # (a) 幻觉公式（假常数假指数）+ 真实 8 档表 → 门 B 数值不符拦截
    fake_doc = tmp / "fake_formula.md"
    fake_doc.write_text(
        "## 幻觉注入节\n\n"
        "- 假设公式：γ(εr) = 1 + 0.75·εr^(−0.5)（幻觉负例：常数与指数均伪）\n"
        f"- 裁判在 εr∈{{{grid_str}}} 档位\n"
        f"- 二乘 γ（{vals_str}）\n",
        encoding="utf-8")
    rep_a = run_pipeline([fake_doc], truth_grid, truth_values, rel_tol)
    promoted_a = rep_a["promoted"]
    b_fail = [v for v in rep_a["gates"]["B_numeric"].values() if not v["pass"]]
    results["wrong_constant_formula"] = {
        "intercepted": len(promoted_a) == 0 and len(b_fail) > 0,
        "gate": "B_numeric",
        "promoted_count": len(promoted_a),
        "max_rel_err": max((v["max_rel_err"] for v in b_fail), default=None),
        "rel_tol": rel_tol,
    }

    # (b) 回链断开：候选声称的锚点行重读后无 formula_raw → 门 A cannot_answer
    real_doc = tmp / "real_formula.md"
    real_doc.write_text(
        "## 真公式节\n\n- γ(εr) = 1 + 0.9014·εr^(−0.6361)（真公式）\n"
        f"- 裁判在 εr∈{{{grid_str}}} 档位\n"
        f"- 二乘 γ（{vals_str}）\n",
        encoding="utf-8")
    other_doc = tmp / "other.md"
    other_doc.write_text("## 其它节\n\n- 这里没有任何公式。\n", encoding="utf-8")
    rep_real = run_pipeline([real_doc], truth_grid, truth_values, rel_tol)
    if rep_real["promoted"]:
        cand = rep_real["promoted"][0]
        # 篡改：把候选的出处指到不含公式的文档（模拟回链断开）
        tampered = Candidate(
            candidate_id=cand["candidate_id"], formula_raw=cand["formula_raw"],
            formula_latex=cand["formula_latex"], python_expr=cand["python_expr"],
            lhs="γ(εr)", output_var=DECLARED_VARIABLES[1],
            input_var=DECLARED_VARIABLES[0], doc=other_doc.name, line_no=2,
            line_text="- 这里没有任何公式。")
        ga = gate_a_backlink(tampered, [real_doc, other_doc])
        results["broken_backlink"] = {
            "intercepted": (not ga["pass"]) and bool(ga["cannot_answer"]),
            "gate": "A_backlink",
            "gate_detail": ga,
        }
    else:
        results["broken_backlink"] = {
            "intercepted": False, "gate": "A_backlink",
            "error": "基线真公式未 promote，负例无法构造"}

    # (c) 无公式文档 → 哨兵 cannot_answer、零候选、零异常
    prose_doc = tmp / "prose_only.md"
    prose_doc.write_text(
        "## 纯散文节\n\n本节讨论项目管理经验，不含任何公式定义。\n"
        "- 要点一：文档先行。\n- 要点二：判据预声明。\n",
        encoding="utf-8")
    rep_c = run_pipeline([prose_doc], truth_grid, truth_values, rel_tol)
    results["no_formula_doc"] = {
        "intercepted": (len(rep_c["promoted"]) == 0
                        and rep_c["cannot_answer"]["sentinel_active"]
                        and rep_c["cannot_answer"]["units_without_formula"] > 0),
        "gate": "cannot_answer_sentinel",
        "units_without_formula": rep_c["cannot_answer"]["units_without_formula"],
        "promoted_count": len(rep_c["promoted"]),
    }
    results["_tmp_dir"] = str(tmp)
    return results


# ---------------------------------------------------------------------------
# CLI（零网络）
# ---------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lit_mine_pipeline",
        description="DP-18 C9 文献挖掘管线（降级路线全链）")
    parser.add_argument("--docs", nargs="+", required=True,
                        help="矿源清单（.md 直读 / .pdf pymupdf 文本层）")
    parser.add_argument("--out", default="runs/df6_dp18c9",
                        help="产物输出目录（候选 JSON+报告）")
    parser.add_argument("--skip-negatives", action="store_true",
                        help="跳过幻觉负例三连（判据 G2）")
    args = parser.parse_args(argv)

    report = run_pipeline(args.docs)
    negatives = {} if args.skip_negatives else run_hallucination_negatives()
    report["negatives"] = negatives

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    for cand in report["promoted"]:
        cname = f"{cand['output_key']}_litmine_candidate.json"
        (out_dir / cname).write_text(
            json.dumps(cand, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "litmine_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    promoted = report["promoted_ids"]
    neg_ok = all(v.get("intercepted") for k, v in negatives.items()
                 if not k.startswith("_"))
    print(f"[litmine] units={report['extraction_stats']['text_units']} "
          f"defs={report['extraction_stats']['formula_defs_total']} "
          f"in_scope={report['extraction_stats']['in_scope']}")
    print(f"[litmine] promoted={promoted}")
    for cid in promoted:
        gb = report["gates"]["B_numeric"][cid]
        print(f"[litmine] {cid} max_rel_err={gb['max_rel_err']:.6f} "
              f"(tol={gb['rel_tol']}) cross={gb['max_cross_path_rel']:.2e}")
    if negatives:
        for k, v in negatives.items():
            if not k.startswith("_"):
                print(f"[litmine] negative[{k}] intercepted={v.get('intercepted')}")
    ok = bool(promoted) and (not negatives or neg_ok)
    print(f"[litmine] overall={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
