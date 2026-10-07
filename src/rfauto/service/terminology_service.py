"""术语卡服务（QW-6；服务层 JSON 进出， 硬限 4）。

数据单一事实源：knowledge/terminology.yaml（首版 50 条，schema 见该文件
头注：term/definition 必填，unit/scope/see_also 可选）。三条主入口全部
只读、不抛异常，ok 信封（同 mcp_server 设计红线）：

- list_terms(scope=None)：全量/按 scope 过滤的术语清单（附可用 scope 集）；
- get_term(term)：单条查询（term 大小写不敏感）；未知 term → ok=False；
- report_footnotes(terms)：按引用序出脚注列表（首次引用定序、重复引用
  去重、未知术语进 unknown 不阻塞整体）——QW-6 报告链挂接的**降级路径**：
  不侵入 report_render/report_narrative 既有文件，由报告组装方调用本函数
  拼脚注节；后续要深挂报告链时由报告侧接入（任务书预告的降级方向）。

铁律 7 面一致：本模块只搬运 YAML 既有文本，不产生任何物理数字。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from rfauto.service.envelope import ok_envelope

__all__ = ["get_term", "list_terms", "report_footnotes"]

_TERMINOLOGY_PATH = (
    Path(__file__).resolve().parents[3] / "knowledge" / "terminology.yaml"
)


def load_terminology() -> dict[str, Any]:
    """读取 knowledge/terminology.yaml；缺失/损坏时返回空表（不抛异常）。"""
    if not _TERMINOLOGY_PATH.exists():
        return {}
    try:
        with open(_TERMINOLOGY_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _terms_raw() -> list[dict[str, Any]]:
    data = load_terminology()
    terms = data.get("terms")
    if not isinstance(terms, list):
        return []
    return [t for t in terms if isinstance(t, dict)]


def list_terms(scope: str | None = None) -> dict[str, Any]:
    """术语清单（JSON 进出）。

    scope=None 返回全量；scope 给定时按 term 的 scope 标签精确过滤
    （缺 scope 标签的条目视为 general）。
    """
    terms = _terms_raw()
    scopes = sorted({str(t.get("scope", "general")) for t in terms})
    if scope is not None:
        terms = [t for t in terms if str(t.get("scope", "general")) == scope]
    return ok_envelope(count=len(terms), scopes=scopes, terms=terms)


def get_term(term: str) -> dict[str, Any]:
    """单条术语查询（term 大小写不敏感精确匹配；未知 → ok=False）。"""
    key = str(term).strip().lower()
    for t in _terms_raw():
        if str(t.get("term", "")).strip().lower() == key:
            return ok_envelope(term=t)
    return {
        "ok": False,
        "error": f"unknown term: {term!r}（见 list_terms 的可用清单）",
    }


def report_footnotes(terms: list[str]) -> dict[str, Any]:
    """按引用序出脚注列表（报告组装方调用；QW-6 报告链降级挂接点）。

    - 首次引用定编号（重复引用去重，编号不重排）；
    - 未知术语不阻塞整体：进 unknown 清单如实上报，不伪造脚注；
    - 返回 footnotes: [{no, term, definition, unit?, see_also?}]。
    """
    by_key: dict[str, dict[str, Any]] = {}
    for t in _terms_raw():
        by_key[str(t.get("term", "")).strip().lower()] = t

    footnotes: list[dict[str, Any]] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for raw in terms:
        key = str(raw).strip().lower()
        if key not in by_key:
            if str(raw).strip() and str(raw).strip() not in unknown:
                unknown.append(str(raw).strip())
            continue
        if key in seen:
            continue
        seen.add(key)
        src = by_key[key]
        note: dict[str, Any] = {
            "no": len(footnotes) + 1,
            "term": src.get("term", ""),
            "definition": src.get("definition", ""),
        }
        if "unit" in src:
            note["unit"] = src["unit"]
        if "see_also" in src:
            note["see_also"] = src["see_also"]
        footnotes.append(note)

    return ok_envelope(count=len(footnotes), footnotes=footnotes, unknown=unknown)
