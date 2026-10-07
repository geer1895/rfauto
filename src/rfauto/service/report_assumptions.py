"""XN-5 报告假设论证模式（round19 P2，ge8c 席C6）——报告自动附三段假设论证。

定位（round19 口径"报告自动附'适用边界+潜在反例+未验证假设'三段（从
docstring UNVERIFIED 标签与判据 domain 盾自动抽取）"）：

1. **适用边界**（boundary）：调用方注入的判据 domain 盾清单（#274 族：
   门/物理合理窗按 template 作用域分派——"判据 X 仅适用域 Y"）逐条转
   边界陈述；
2. **潜在反例**（counterexamples）：调用方注入的 bounds/极限裁决清单
   （unreachable/marginal/undefined——core/bounds.BoundVerdict 语义）逐条
   转反例提示；undefined 如实记"无判定目标"不冒充反例；
3. **未验证假设**（unverified）：对指定模块/文件做 AST docstring 扫描，
   抽取含 ``UNVERIFIED`` 标签的行（仓内诚实语义的既有标签，逐条带模块+
   行号可溯）。

扫描面安全约束：按**模块名**走 ``importlib.util.find_spec`` 解析源文件路径
（只读文件文本，不执行模块代码）；按**文件路径**直读。解析失败/路径缺失
按条如实记 skipped（#105：观测面不炸主路径）。

三段齐全即"假设论证模式"——报告消费方把本输出直接挂报告尾部；全部内容
来自确定性抽取与调用方注入，本模块不产生物理数字（铁律 7）。
"""

from __future__ import annotations

import ast
import importlib.util
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.service.envelope import ok_envelope

__all__ = [
    "ASSUMPTIONS_SCHEMA",
    "UNVERIFIED_TAG",
    "collect_unverified_from_sources",
    "render_assumptions_markdown",
    "report_assumptions",
]

#: 假设论证 schema 标识（JSON 消费面稳定钉）。
ASSUMPTIONS_SCHEMA = "rfauto-report-assumptions-v1"

#: docstring 未验证标签（仓内诚实语义既有惯例的收敛词）。
UNVERIFIED_TAG = "UNVERIFIED"

#: 单文件扫描体积上限（防大文件拖垮；超出如实记 skipped）。
_SOURCE_CAP_BYTES = 400_000


def _extract_unverified_lines(source: str) -> list[tuple[int, str]]:
    """AST 解析 → 全部 docstring 中含 UNVERIFIED 标签的行（(行号, 文本)）。

    行号 = docstring 节点在该行内的相对偏移（docstring 起始行 + 段内行序）；
    文本剥离行首尾空白。语法非法 → ValueError（调用方逐条捕获记 skipped）。
    """
    tree = ast.parse(source)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if not doc or UNVERIFIED_TAG not in doc:
            continue
        start = 1  # Module 无 lineno；docstring 恒为首语句
        body = node.body
        if body and isinstance(body[0], ast.Expr) and \
                isinstance(body[0].value, ast.Constant) and \
                isinstance(body[0].value.value, str):
            start = body[0].lineno
        for i, line in enumerate(doc.splitlines()):
            if UNVERIFIED_TAG in line:
                hits.append((start + i, line.strip()))
    return hits


def _resolve_source_path(source: str) -> Path:
    """模块名 → 源文件路径；已是路径 → 原样（存在性由调用方核）。"""
    candidate = Path(source)
    if candidate.suffix == ".py":
        return candidate
    spec = importlib.util.find_spec(source)
    if spec is None or not spec.origin:
        raise ModuleNotFoundError(f"module not found: {source}")
    return Path(spec.origin)


def collect_unverified_from_sources(
    sources: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """多来源 UNVERIFIED 行收集（返回 (hits, skipped)；负例不炸批次）。

    hits：{source, line, text}（source 序 + 行号序，确定性全序）；
    skipped：{source, reason}（找不到/语法错/超限如实留痕）。
    """
    hits: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for src in sources:
        try:
            path = _resolve_source_path(str(src))
            if not path.is_file():
                raise FileNotFoundError(f"source not found: {path}")
            text = path.read_text(encoding="utf-8")
            if len(text) > _SOURCE_CAP_BYTES:
                raise ValueError(f"source exceeds cap: {len(text)} bytes")
            for lineno, line in _extract_unverified_lines(text):
                hits.append({"source": str(src), "line": lineno,
                             "text": line})
        except (ModuleNotFoundError, FileNotFoundError, SyntaxError,
                ValueError, OSError, UnicodeDecodeError) as exc:
            skipped.append({"source": str(src), "reason": str(exc)})
    hits.sort(key=lambda h: (h["source"], h["line"]))
    return hits, skipped


def report_assumptions(
    *,
    criteria_domains: Sequence[Mapping[str, Any]] = (),
    bounds_verdicts: Sequence[Mapping[str, Any]] = (),
    sources: Sequence[str] = (),
) -> dict[str, Any]:
    """三段假设论证报告（JSON 进出；三段可能各自为空——空段如实空表）。

    Args:
        criteria_domains: 判据 domain 盾清单，条目 {id, domain, gate?}——
            domain 缺失/空 = 该判据未声明适用域 → 如实记"未声明"条目
            （不假装有界）。
        bounds_verdicts: 极限裁决清单，条目 {id, verdict}——verdict 取
            core/bounds.BoundVerdict 词表（unreachable/marginal/reachable/
            undefined）；unreachable/marginal 转反例提示；undefined 如实
            记"无判定目标"；其余不进反例段。
        sources: 模块名/文件路径清单（UNVERIFIED docstring 扫描面）。
    """
    boundary: list[dict[str, Any]] = []
    for cd in criteria_domains:
        cid = str(cd.get("id") or "?")
        domain = str(cd.get("domain") or "").strip()
        boundary.append({
            "criteria_id": cid,
            "domain": domain or None,
            "statement": (f"判据 {cid} 仅适用于域「{domain}」；域外结论不可外推"
                          if domain else
                          f"判据 {cid} 未声明适用域（domain 盾缺失，域外使用无据）"),
            "declared": bool(domain),
        })

    counterexamples: list[dict[str, Any]] = []
    for bv in bounds_verdicts:
        bid = str(bv.get("id") or "?")
        verdict = str(bv.get("verdict") or "?")
        if verdict in ("unreachable", "marginal"):
            hint = ("存在可达性反例：极限界不可达/贴界（裕度比 ≤5% 量级），"
                    "目标值附近的结构性反例应先排查" if verdict == "unreachable"
                    else "贴界状态（裕度比 ≤5% 量级）：设计点对扰动敏感，"
                         "是天然反例候选带")
            counterexamples.append({"bound_id": bid, "verdict": verdict,
                                    "statement": hint})
        elif verdict == "undefined":
            counterexamples.append({"bound_id": bid, "verdict": verdict,
                                    "statement": "无判定目标/参数不足——"
                                                 "如实未判，不构成反例也不构成安全"})

    unverified, skipped = collect_unverified_from_sources(sources)
    n_all = len(boundary) + len(counterexamples) + len(unverified)
    return ok_envelope(
        schema=ASSUMPTIONS_SCHEMA,
        sections={
            "boundary": boundary,
            "counterexamples": counterexamples,
            "unverified": unverified,
        },
        skipped_sources=skipped,
        n_items=n_all,
        note="三段内容全部来自确定性抽取与调用方注入；空段=如实无项",
    )


def render_assumptions_markdown(result: Mapping[str, Any]) -> str:
    """三段假设论证 → Markdown（报告尾部直接挂载形态）。"""
    if not result.get("ok"):
        return f"# 假设论证\n\n- 生成失败：{result.get('errors')}\n"
    sec = result.get("sections") or {}
    lines = ["# 假设论证（适用边界 / 潜在反例 / 未验证假设）", ""]

    lines += ["## 一、适用边界"]
    boundary = sec.get("boundary") or []
    if boundary:
        lines += [f"- {b['statement']}" for b in boundary]
    else:
        lines.append("- 本报告消费面未注入判据域声明（如实空，非「全域适用」）。")

    lines += ["", "## 二、潜在反例"]
    cex = sec.get("counterexamples") or []
    if cex:
        lines += [f"- {c['statement']}（{c['bound_id']}，verdict={c['verdict']}）"
                  for c in cex]
    else:
        lines.append("- 无已登记的极限反例裁决（如实空）。")

    lines += ["", "## 三、未验证假设（docstring UNVERIFIED 抽取）"]
    unver = sec.get("unverified") or []
    if unver:
        lines += [f"- `{h['source']}:{h['line']}` {h['text']}" for h in unver]
    else:
        lines.append("- 扫描面内无 UNVERIFIED 标签（如实空，非「已验证」）。")
    skipped = result.get("skipped_sources") or []
    if skipped:
        lines += ["", "### 扫描跳过（如实留痕）"]
        lines += [f"- `{s['source']}`：{s['reason']}" for s in skipped]
    lines.append("")
    return "\n".join(lines) + "\n"
