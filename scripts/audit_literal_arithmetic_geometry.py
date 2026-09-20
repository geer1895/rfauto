"""全仓审计：字面算术表达式作几何 origin/尺寸值（#218 家族）。

HFSS 模型器表达式引擎语义（runs/mline_repro_attribution_20260911.md §二）：
  纯数字串（"-25"）        → 按模型单位补全（PyAEDT _arg_with_dim）
  带单位串（"0mm"）        → 显式单位 ✓
  字面算术表达式           → 无量纲数字按 SI 米求值 ✗（"-2.5*1.113" 曾致
                             端口 sheet 悬空域外 2.78m，r2-r4 挂起真因）
  含设计变量表达式         → 量纲随变量（变量带 mm 时安全）

本脚本对 src/rfauto/adapters/ 与 scripts/ 的几何 API 调用
（create_box/create_rectangle/create_cylinder/create_circle/create_sphere
的 origin/sizes/radius/height 实参）做 AST 扫描，逐值分类：
  WITH_UNIT          已带单位（安全）
  BARE_NUMBER        裸数字串/Python 预计算串/裸 float（PyAEDT 补模型单位，
                     现行政策建议显式单位后缀——列出不计违规）
  DESIGN_VAR_EXPR    含设计变量表达式（量纲随变量，安全）
  LITERAL_ARITH      字面算术（纯数字）→ 危险（SI 米），计违规
  LITERAL_ARITH_VAR  字面算术含插值名（f"-2.5*{W}"：插值是 HFSS 设计变量
                     则量纲安全、是 Python 浮点则 SI 米危险）→ 需人工确认，
                     默认计违规
  NON_LITERAL        非字面实参（变量/表达式传入，静态不可判，列出不计违规）

退出码：0=无未豁免违规；1=存在违规（新代码必须预计算浮点+显式单位，或经
hfss_builder_utils.Quantity 构造——字面算术在该构建期即被拒绝）。
"""
from __future__ import annotations

import ast
import re
import sys
import warnings
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [REPO / "src" / "rfauto" / "adapters", REPO / "scripts"]
SELF_NAME = Path(__file__).name

GEOMETRY_APIS = {"create_box", "create_rectangle", "create_cylinder",
                 "create_circle", "create_sphere"}
GEOMETRY_KWARGS = {"origin", "sizes", "radius", "height"}
VIOLATING_CATEGORIES = {"LITERAL_ARITH", "LITERAL_ARITH_VAR"}

# 豁免清单（人工确认后登记；违规片段须含同文件下列子串才豁免）：
# 1) scripts/hfss_mline_repro_sweep_assert.py——#218 双臂实验的缺陷复现臂
#    （--port-origin literal），故意保留字面算术以端到端复现 SI 米陷阱；
# 2) scripts/hfss_same_geometry_arbitration.py:176——插值均为 HFSS 设计
#    变量（w_in/x_half 等经 hfss[k]="…mm" 定义带 mm 量纲，:75-83 实读；
#    人工确认），#218 语义四"量纲随变量"安全类，且该手法
#    r8 真机 PASS_A 背书（runs/mline_repro_attribution_20260911.md）。
ALLOWLIST: dict[str, tuple[str, ...]] = {
    "scripts/hfss_mline_repro_sweep_assert.py": ("-2.5*",),
    "scripts/hfss_same_geometry_arbitration.py": ("-2.5*w_in",),
}

_PURE_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_NUMERIC_ARITH_RE = re.compile(r"[\d+\-*/().eE\s]+")
_UNIT_TAIL_RE = re.compile(r"[+-]?[\d.eE]+[a-zA-Z]+$")


def classify_expr_text(text: str) -> str:
    """对渲染后的静态字符串实参分类（五类，见模块 docstring）。"""
    s = text.strip()
    if not s:
        return "NON_LITERAL"
    if _PURE_NUMBER_RE.fullmatch(s):
        return "BARE_NUMBER"
    if _NUMERIC_ARITH_RE.fullmatch(s):
        return "LITERAL_ARITH"
    if _UNIT_TAIL_RE.fullmatch(s):
        return "WITH_UNIT"
    return "DESIGN_VAR_EXPR"


def _classify_joinedstr(node: ast.JoinedStr, source: str) -> str:
    """f-string 实参分类：看字面部分是否含运算符（=渲染期算术）。"""
    literals: list[str] = []
    interp_has_ident = False
    for v in node.values:
        if isinstance(v, ast.Constant):
            literals.append(str(v.value))
        else:  # FormattedValue
            seg = ast.get_source_segment(source, v.value) or ""
            if re.search(r"[A-Za-z_]", seg):
                interp_has_ident = True
    lit = "".join(literals)
    core = lit.lstrip("+-")
    if any(ch in core for ch in "*/+-"):
        return "LITERAL_ARITH_VAR" if interp_has_ident else "LITERAL_ARITH"
    if re.search(r"[a-zA-Z]$", lit):
        return "WITH_UNIT"
    return "BARE_NUMBER"


def _iter_elements(value: ast.expr) -> list[ast.expr]:
    if isinstance(value, (ast.List, ast.Tuple)):
        return list(value.elts)
    return [value]


def scan_source(source: str, rel_path: str) -> list[dict[str, str | int]]:
    """扫描一段源码中的几何 API 字面实参（可单测的纯函数）。"""
    # 被扫文件可能含 vendored/历史代码的无效转义序列——parse 期
    # SyntaxWarning 与本审计无关，静默（观测性 best-effort，#105）
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source, filename=rel_path)
    findings: list[dict[str, str | int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) not in GEOMETRY_APIS:
            continue
        for kw in node.keywords:
            if kw.arg not in GEOMETRY_KWARGS:
                continue
            for elt in _iter_elements(kw.value):
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    cat = classify_expr_text(elt.value)
                elif isinstance(elt, ast.JoinedStr):
                    cat = _classify_joinedstr(elt, source)
                elif isinstance(elt, ast.Constant):
                    cat = "BARE_NUMBER"  # 裸 float（PyAEDT 补模型单位）
                else:
                    cat = "NON_LITERAL"
                findings.append({
                    "file": rel_path,
                    "line": getattr(elt, "lineno", kw.lineno),
                    "category": cat,
                    "snippet": ast.get_source_segment(source, elt)
                    or kw.arg,
                })
    return findings


def scan_repo(roots: list[Path] | None = None) -> list[dict[str, str | int]]:
    """扫描扫描根下全部 .py（跳过本脚本），返回逐条 finding。"""
    findings: list[dict[str, str | int]] = []
    for root in (roots or SCAN_ROOTS):
        for path in sorted(root.rglob("*.py")):
            if path.name == SELF_NAME:
                continue
            rel = path.relative_to(REPO).as_posix()
            findings.extend(scan_file(path, rel))
    return findings


def scan_file(path: Path, rel: str) -> list[dict[str, str | int]]:
    source = path.read_text(encoding="utf-8")
    try:
        return scan_source(source, rel)
    except SyntaxError as exc:
        print(f"WARN 语法错误跳过: {rel}: {exc}")
        return []


def filter_violations(
    findings: list[dict[str, str | int]],
) -> list[dict[str, str | int]]:
    """违规 = 危险类且未命中豁免（豁免=同文件片段含 allowlist 子串）。"""
    out = []
    for f in findings:
        if f["category"] not in VIOLATING_CATEGORIES:
            continue
        markers = ALLOWLIST.get(str(f["file"]), ())
        if any(m in str(f["snippet"]) for m in markers):
            continue
        out.append(f)
    return out


def main() -> int:
    findings = scan_repo()
    counts = Counter(str(f["category"]) for f in findings)
    violations = filter_violations(findings)
    print("DIM_AUDIT 分类明细（file:line [类别] snippet）：")
    for f in findings:
        print(f"  {f['file']}:{f['line']} [{f['category']}] {f['snippet']!r}")
    print(f"DIM_AUDIT_SUMMARY files={len(set(str(f['file']) for f in findings))} "
          f"findings={len(findings)} counts={dict(counts)} "
          f"violations={len(violations)}")
    for v in violations:
        print(f"DIM_AUDIT_VIOLATION {v['file']}:{v['line']} {v['snippet']!r}")
    if violations:
        print("DIM_AUDIT_VIOLATIONS（修复口径：预计算浮点+显式单位，"
              "或经 hfss_builder_utils.Quantity 构造）")
        return 1
    print("DIM_AUDIT_CLEAN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
