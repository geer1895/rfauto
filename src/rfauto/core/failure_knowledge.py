"""失败知识注入查询面（KD-4，round16 P1）——XN-1 premortem 的注入对偶面。

杠杆关系声明（同库两面，不重复建库）：
- XN-1（core/premortem.py）= 开工前"生成预演"：按 task_kind 把整张失败
  模式表确定性铺开（top-10 + 探针核对表），回答"这一类任务通常怎么死"。
- KD-4（本模块）= "注入既有失败库"：同一张 ``FAILURE_MODE_LIBRARY`` 的
  **定向检索视图**——按 task_kind + 关键词交集从库里捞出与本任务文本
  相关的失败模式子集（每条带坑号溯源），在 campaign_manager 预检处
  强制调用、注入开工 context（best-effort #105 不阻塞主链）。
  库本身（46 条失败模式 = 沉睡失败知识/坑账的结构化形态，出处=
  项目规则 踩坑速查 + 批次账）只读消费，零复制、零新库。

设计约束（与 premortem / rationale_memory.recall_for 同源）：
- 确定性检索：关键词子串交集匹配（无 embedding、无网络、无 LLM——
  硬规则 7），同输入两次输出逐位一致（JSON sort_keys 往返逐字节同）；
- 命中排序：(-交集数, 可能性档, mode_id) 确定性全序；
- 空结果如实空表：关键词全不命中 → hits=[]（不回退全量、不凑数）；
- 负例契约沿 premortem：未知 task_kind → ValueError（不静默降级）。

用法::

    from rfauto.core.failure_knowledge import (
        failure_knowledge_for, keywords_from_campaign,
        render_failure_knowledge_markdown)

    r = failure_knowledge_for("real_solve", ["网格", "dt"])
    r["hits"]        # 坑号可溯的失败模式子集（交集降序）
    r["checklist"]   # 注入注记（mode_id（坑号）+ 一句话 + 缓解引用）
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from rfauto.core.premortem import (
    _LIKELIHOOD_RANK,
    FAILURE_MODE_LIBRARY,
    PROBE_REGISTRY,
    TASK_KIND_LABELS,
    FailureMode,
    _normalize_task_kind,
)

#: 查询面 schema 版本（JSON 消费面稳定钉）。
FAILURE_KNOWLEDGE_SCHEMA = "rfauto-failure-knowledge-v1"

#: 缺省产出条数（KD-4 注入面为定向子集，比 premortem 全景铺开更窄）。
DEFAULT_TOP_K = 5

#: 检索文本分词（与 service/rationale_memory._TOKEN 同口径：字母数字下划线
#: + CJK 连续段；本模块只用于战役声明面提关键词，库检索走子串交集）。
_TOKEN = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


def normalize_keywords(keywords: str | Sequence[str] | None) -> list[str]:
    """keywords（str / 序列 / None）→ 规范关键词表（strip→剔除空白→去重排序）。

    None / 全空白 → []（调用方据此按"无关键词过滤"处理）；确定性。
    """
    if keywords is None:
        return []
    if isinstance(keywords, str):
        raw: list[str] = [keywords]
    else:
        raw = [str(k) for k in keywords]
    return sorted({k.strip() for k in raw if k and k.strip()})


def _lesson_refs(mitigation_ref: str) -> tuple[str, ...]:
    """缓解引用（'#262/#343/#312' / '#df4③' / '#1b/#191'）→ 坑号元组。

    以 '/' 切分、保留 '#' 开头 token——坑号稳定 id，注入注记与 JSON 面随行。
    """
    return tuple(t for t in mitigation_ref.split("/") if t.startswith("#"))


def _searchable_text(fm: FailureMode) -> str:
    """模式条目 → 检索文本（模式名+症状指纹+缓解引用+出处+探针问句）。"""
    probe_question = (PROBE_REGISTRY[fm.detection_probe].question
                      if fm.detection_probe in PROBE_REGISTRY else "")
    return " ".join((fm.mode, probe_question, fm.mitigation_ref, fm.source,
                     *fm.early_signals))


def failure_knowledge_for(
    task_kind: Any,
    keywords: str | Sequence[str] | None = None,
    *,
    top_k: int = DEFAULT_TOP_K,
    min_score: int = 1,
) -> dict[str, Any]:
    """按 task_kind + 关键词交集检索失败知识（KD-4 主入口，确定性纯函数）。

    - task_kind：premortem 五类之一（规范 id / 别名 / 中文；未知 →
      ValueError，负例契约沿 premortem 不静默降级）；
    - keywords：None / 空表 = 不按关键词过滤（全库按可能性档铺开截
      top_k——退化即 XN-1 视图）；否则逐条模式对检索文本做子串交集
      匹配，交集数 < min_score（≥1）的不收入；
    - top_k：产出条数帽（缺省 5；0 → 空表）。

    返回 JSON 友好契约::

        {ok, schema, task_kind, task_kind_label, keywords, n_modes_total,
         n_hits, top_k, min_score,
         hits: [{mode_id, lesson_refs[], score, matched[], likelihood_band,
                 summary, early_signals[], detection_probe, probe_question,
                 mitigation_ref, source}],
         checklist: [{item, mode_id, lesson_refs[], question, mitigation_ref}]}
    """
    kind = _normalize_task_kind(task_kind)
    pool = list(FAILURE_MODE_LIBRARY[kind])
    kw_list = normalize_keywords(keywords)
    lowered = [k.lower() for k in kw_list]
    require = max(int(min_score), 1) if lowered else 0

    hits: list[dict[str, Any]] = []
    for fm in pool:
        if lowered:
            text = _searchable_text(fm).lower()
            matched = sorted({kw for kw, low in zip(kw_list, lowered, strict=True)
                              if low in text})
            score = len(matched)
            if score < require:
                continue
        else:
            matched, score = [], 0
        spec = PROBE_REGISTRY[fm.detection_probe]
        refs = _lesson_refs(fm.mitigation_ref)
        hits.append({
            "mode_id": fm.mode_id,
            "lesson_refs": list(refs),
            "score": score,
            "matched": matched,
            "likelihood_band": fm.likelihood_band,
            "summary": fm.mode,
            "early_signals": list(fm.early_signals),
            "detection_probe": fm.detection_probe,
            "probe_question": spec.question,
            "mitigation_ref": fm.mitigation_ref,
            "source": fm.source,
        })

    def _hit_key(h: dict[str, Any]) -> tuple[int, int, str]:
        fm_band = h["likelihood_band"]
        return (-int(h["score"]),
                _LIKELIHOOD_RANK.get(fm_band, len(_LIKELIHOOD_RANK)),
                str(h["mode_id"]))

    hits.sort(key=_hit_key)
    k = max(int(top_k), 0)
    hits = hits[:k]

    # 注入注记（与 rationale_memory.recall_for 的 checklist 风格对齐）：
    # mode_id（坑号）稳定 id + 一句话 + 缓解引用。
    checklist = []
    for h in hits:
        refs_note = (f"（{'、'.join(h['lesson_refs'])}）"
                     if h["lesson_refs"] else "")
        checklist.append({
            "item": (f"{h['mode_id']} [{h['likelihood_band']}] "
                     f"{h['summary']}{refs_note}"),
            "mode_id": h["mode_id"],
            "lesson_refs": list(h["lesson_refs"]),
            "question": h["probe_question"],
            "mitigation_ref": h["mitigation_ref"],
        })

    return {
        "ok": True,
        "schema": FAILURE_KNOWLEDGE_SCHEMA,
        "task_kind": kind,
        "task_kind_label": TASK_KIND_LABELS[kind],
        "keywords": kw_list,
        "n_modes_total": len(pool),
        "n_hits": len(hits),
        "top_k": k,
        "min_score": max(int(min_score), 1) if lowered else 0,
        "hits": hits,
        "checklist": checklist,
    }


def render_failure_knowledge_markdown(result: Mapping[str, Any], *,
                                      heading: str | None = None) -> str:
    """failure_knowledge_for 结果 → 确定性 markdown 注入块（无 LLM）。

    未命中 / 非 ok → 空串（注入面如实空，不产占位噪声）。注记格式与
    rationale_memory.render_checklist 对齐：``- [ ] id（坑号）一句话`` +
    症状指纹 + 检测探针 + 缓解引用随行。
    """
    if not result.get("ok"):
        return ""
    hits = list(result.get("hits") or [])
    if not hits:
        return ""
    label = str(result.get("task_kind_label", result.get("task_kind", "")))
    kws = list(result.get("keywords") or [])
    lines = [heading or (f"## 失败知识注入（{label}）"), ""]
    kw_note = "、".join(str(k) for k in kws) if kws else "无（全库铺开）"
    lines.append(f"> 命中 {len(hits)}/{result.get('n_modes_total', len(hits))} 条"
                 f"（关键词：{kw_note}）；坑号可溯。同库对偶：XN-1 premortem="
                 "生成预演，本块=注入既有失败库（KD-4）。")
    lines.append("")
    for h in hits:
        refs = "、".join(h.get("lesson_refs") or [])
        lines.append(f"- [ ] {h.get('mode_id')} [{h.get('likelihood_band')}] "
                     f"{h.get('summary')}（{refs}）")
        for sig in h.get("early_signals") or []:
            lines.append(f"  - 症状指纹：{sig}")
        lines.append(f"  - 检测探针：{h.get('probe_question')}"
                     f"（{h.get('detection_probe')}）")
        lines.append(f"  - 缓解引用：{h.get('mitigation_ref')}"
                     f"｜出处：{h.get('source')}")
    lines.append("")
    return "\n".join(lines)


def keywords_from_campaign(model: Any = "", objectives: Any = None,
                           recipe_name: str = "") -> tuple[str, ...]:
    """战役声明面 → 确定性关键词表（模型名/指标名/配方名的分词去重）。

    分词口径 = 字母数字下划线 + CJK 连续段（rationale_memory._TOKEN 同源），
    长度 ≥2 的 token 小写去重后排序（确定性）；objectives 递归扁平取文本。
    提不出任何 token → 空元组（调用方按无关键词过滤处理，如实退化）。
    """
    def flatten(value: Any) -> str:
        if isinstance(value, Mapping):
            return " ".join(flatten(value[k]) for k in sorted(value, key=str))
        if isinstance(value, (list, tuple)):
            return " ".join(flatten(v) for v in value)
        return "" if value is None else str(value)

    text = " ".join((str(model or ""), flatten(objectives),
                     str(recipe_name or "")))
    return tuple(sorted({t.lower() for t in _TOKEN.findall(text) if len(t) >= 2}))


__all__ = [
    "DEFAULT_TOP_K",
    "FAILURE_KNOWLEDGE_SCHEMA",
    "failure_knowledge_for",
    "keywords_from_campaign",
    "normalize_keywords",
    "render_failure_knowledge_markdown",
]
