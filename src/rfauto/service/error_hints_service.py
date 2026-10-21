"""error_hints_service：错误消息 → 可行动提示映射层（XC 错误信息工程）。

**纯映射层**（硬规则 7 的对偶：映射表也是确定性数据，LLM/人不改判据）：
仓库高频错误指纹（本仓内核/引擎/环境真实错误串的子串或正则）→
{hint（可行动修复建议）, refs（坑号/docs 指针，#NNN 按 D1 裁决保留）,
severity}。映射表模块内自持（LINT_REGISTRY 惯例），新增条目=加一行
_HINT_RULES（pattern/match/hint/refs/severity 五字段）。

设计约束：
- 匹配永远基于**异常类型名 + 消息原文子串**，不做模糊语义推断；
- 一条消息可命中多条规则（全部返回，按 severity 排序 error>warn>info）；
- 未命中 → 空表如实返回（不编造提示）；
- 零 I/O、零物理数字（提示里的阈值都指回内核守卫原文）。
"""

from __future__ import annotations

import re
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.hint_rules import (  # T1 解环：规则表叶化（定义体在 hint_rules）
    _HINT_RULES,
    _SOURCE,
    list_hint_rules,
)

#: 规则表：pattern 子串或正则；refs=坑号/文档指针；severity: error|warn|info

_SEV_ORDER = {"error": 0, "warn": 1, "info": 2}


def _compiled_rules() -> list[tuple[re.Pattern[str] | str, dict[str, str]]]:
    out: list[tuple[re.Pattern[str] | str, dict[str, str]]] = []
    for rule in _HINT_RULES:
        if rule.get("match") == "regex":
            out.append((re.compile(rule["pattern"]), rule))
        else:
            out.append((rule["pattern"], rule))
    return out


def hint_for_message(text: str) -> dict[str, Any]:
    """错误消息文本 → 命中提示表（全部命中随行；未命中 hits=[]）。"""
    if not isinstance(text, str):
        return error_envelope(["text 必须是字符串"])
    hits: list[dict[str, str]] = []
    for pattern, rule in _compiled_rules():
        matched = (pattern in text if isinstance(pattern, str)
                   else pattern.search(text) is not None)
        if matched:
            hits.append({"pattern": rule["pattern"],
                         "match": str(rule.get("match", "substring")),
                         "hint": rule["hint"], "refs": rule["refs"],
                         "severity": rule["severity"]})
    hits.sort(key=lambda h: _SEV_ORDER.get(h["severity"], 3))
    return ok_envelope(hits=hits, n_hits=len(hits), source=_SOURCE)


def hint_for_exception(exc: BaseException) -> dict[str, Any]:
    """异常对象 → 提示表（类型名+消息原文一并入匹配）。"""
    text = f"{type(exc).__name__}: {exc}"
    out = hint_for_message(text)
    out["exception_type"] = type(exc).__name__
    return out


def hint_for_message_enhanced(
    message: str, *, use_systemone: bool = False, provider: str | None = None
) -> dict[str, Any]:
    """第二档增强：确定性映射优先照旧，零命中时可选 System One 选规则。

    - ``hint_for_message`` 命中（或 ``use_systemone=False``，或缺省）→
      **原样返回确定性结果，System One 通道零触碰**；
    - 仅当零命中且 ``use_systemone=True``：构造 choice 问题（options=规则
      pattern 清单）走 ``ask_systemone`` 选规则出单条 hint（信封附
      ``enhanced=True``+``systemone_provider``）；
    - 任何失败（provider 不可用/降级/选索引越界/通道异常）→ 回退确定性
      结果（零命中=空表如实，不编造提示；#105：增强档永不遮蔽主路径）。
    本函数只读不写：不改既有 hint_for_message/_emit 任何行为。
    """
    base = hint_for_message(message)
    if not isinstance(message, str) or base.get("n_hits") or not use_systemone:
        return base
    try:
        from rfauto.service.systemone_service import ask_systemone

        rules = list_hint_rules().get("rules") or []
        options = [str(r.get("pattern", "")) for r in rules]
        if not options:
            return base
        question = {
            "kind": "choice",
            "question": "为下述错误消息选择最可能的修复提示规则（只返回选项）：\n"
                        + message,
            "options": options,
            "context": {"task": "hint_rule_select", "n_options": len(options)},
        }
        out = ask_systemone(question, provider=provider)
        if not out.get("ok") or out.get("degraded"):
            return base
        selected = (out.get("answer") or {}).get("selected")
        if isinstance(selected, int) and not isinstance(selected, bool):
            idx = selected
        else:
            idx = options.index(str(selected)) if str(selected) in options else -1
        if not (0 <= idx < len(rules)):
            return base
        rule = rules[idx]
        hit = {"pattern": rule["pattern"],
               "match": str(rule.get("match", "substring")),
               "hint": rule["hint"], "refs": rule["refs"],
               "severity": rule["severity"]}
        return ok_envelope(hits=[hit], n_hits=1, source=_SOURCE,
                           enhanced=True,
                           systemone_provider=out.get("provider"))
    except Exception:  # #105：增强档任何失败回退确定性结果
        return base
