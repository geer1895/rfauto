"""KD-9 案例库（CBR）检索面（round16 P3，J 流）——失败知识→案例检索。

定位（任务书口径）：KD-4（failure_knowledge.py）的**对偶消费面**——
KD-4 回答"开工前这类任务怎么死"（预检注入），KD-9 回答"手上这个失败/
症状，历史上哪个坑长得像"（事后检索，CBR 检索-复用-修订循环的检索
半环）。**复用不重写**：库（FAILURE_MODE_LIBRARY）与检索核（关键词
交集/确定性全序）都只在 core/failure_knowledge.py 单源，本模块零新库、
零新检索算法——只做"五元组案例形态包装 + 相似案例面"。

CBR 五元组（案例形态，round16 KD-9"五元组"口径按失败库载体落位）：
  problem   = 失败模式一句话 + 症状指纹（early_signals）
  context   = task_kind（premortem 五类）
  solution  = 缓解引用（mitigation_ref，坑号可溯）
  outcome   = 避免复发（failure 库载体的 outcome 形态——坑已在账）
  provenance= mode_id（坑号）+ lesson_refs + source

设计约束（确定性，铁律 7）：同输入两次输出逐位一致；检索语义与
KD-4 逐位同（同一函数 failure_knowledge_for）——检索行为差异=零；
未命中如实空表（不回退全量）；未知 task_kind 沿 KD-4 负例契约
ValueError。

用法::

    from rfauto.service.cbr_case_service import (
        find_similar_cases, case_base_summary)

    r = find_similar_cases("real_solve", "整树无声消失 求解进程没了")
    r["cases"]     # 相似案例（五元组+score），坑号可溯
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rfauto.core.failure_knowledge import (
    FAILURE_KNOWLEDGE_SCHEMA,
    failure_knowledge_for,
    keywords_from_campaign,
    normalize_keywords,
)
from rfauto.service.envelope import ok_envelope

#: CBR 案例面契约版本。
CBR_CASE_SCHEMA = "rfauto-cbr-case-v1"

#: 案例检索缺省产出条数（与 KD-4 DEFAULT_TOP_K 同口径）。
DEFAULT_TOP_K_CASES = 5


def _case_from_hit(hit: Mapping[str, Any], task_kind: str) -> dict[str, Any]:
    """KD-4 命中条目 → CBR 五元组案例（纯包装，零新数据）。"""
    return {
        "case_id": f"FK-{hit['mode_id']}",
        "problem": str(hit.get("summary", "")),
        "symptoms": list(hit.get("early_signals") or []),
        "context": task_kind,
        "solution": str(hit.get("mitigation_ref", "")),
        "outcome": "avoided（坑已在账，按缓解引用预检可免复发）",
        "provenance": {
            "mode_id": hit.get("mode_id"),
            "lesson_refs": list(hit.get("lesson_refs") or []),
            "source": hit.get("source", ""),
            "detection_probe": hit.get("detection_probe", ""),
        },
        "score": int(hit.get("score", 0)),
        "matched_keywords": list(hit.get("matched") or []),
        "likelihood_band": hit.get("likelihood_band", ""),
    }


def find_similar_cases(task_kind: Any,
                       query_text: str | Sequence[str] | None = None,
                       keywords: str | Sequence[str] | None = None,
                       *,
                       top_k: int = DEFAULT_TOP_K_CASES,
                       min_score: int = 1) -> dict[str, Any]:
    """按 task_kind + 查询文本检索相似失败案例（KD-9 主入口，确定性）。

    与 KD-4 的分工面：query_text 是"手头的失败/症状描述"（自由文本），
    本函数用 failure_knowledge.keywords_from_campaign 同款分词提关键词
    后交 failure_knowledge_for 检索——**检索语义与 KD-4 逐位同**（同
    函数），案例形态=五元组包装。显式 keywords 与 query_text 并存时
    取并集（都规范化去重）。

    返回::

        {ok, schema, task_kind, query_keywords, n_cases_total, n_cases,
         cases: [五元组案例（score 降序=KD-4 全序）]}
    """
    kw_set: set[str] = set()
    if query_text is not None:
        tokens = keywords_from_campaign(str(query_text))
        kw_set.update(tokens)
    if keywords is not None:
        kw_set.update(normalize_keywords(keywords))
    merged = sorted(kw_set)

    fk = failure_knowledge_for(task_kind, merged or None,
                               top_k=top_k, min_score=min_score)
    kind = fk["task_kind"]
    cases = [_case_from_hit(h, kind) for h in fk["hits"]]
    return ok_envelope(
        schema=CBR_CASE_SCHEMA,
        task_kind=kind,
        task_kind_label=fk["task_kind_label"],
        query_keywords=merged,
        n_cases_total=fk["n_modes_total"],
        n_cases=len(cases),
        cases=cases,
        reused_face=("core/failure_knowledge.failure_knowledge_for"
                     "（KD-4 同源检索，零新库零新算法）"),
        kd4_schema=FAILURE_KNOWLEDGE_SCHEMA,
    )


def case_base_summary() -> dict[str, Any]:
    """案例库覆盖摘要（确定性；只读消费 premortem 库计数）。"""
    from rfauto.core.premortem import FAILURE_MODE_LIBRARY, TASK_KIND_LABELS
    per_kind = {k: len(v) for k, v in FAILURE_MODE_LIBRARY.items()}
    return ok_envelope(
        schema=CBR_CASE_SCHEMA,
        n_cases=sum(per_kind.values()),
        n_task_kinds=len(per_kind),
        per_task_kind=per_kind,
        task_kind_labels=dict(TASK_KIND_LABELS),
        library_face="core/premortem.FAILURE_MODE_LIBRARY（KD-4/KD-9 同库两面）",
    )


def render_case_report(result: Mapping[str, Any]) -> str:
    """find_similar_cases 结果 → 确定性 markdown（CBR 检索报告块）。"""
    if not result.get("ok"):
        return ""
    cases = list(result.get("cases") or [])
    if not cases:
        return ""
    label = str(result.get("task_kind_label", result.get("task_kind", "")))
    kws = "、".join(result.get("query_keywords") or []) or "无"
    lines = [f"## 相似案例检索（CBR，{label}，关键词：{kws}）", ""]
    for c in cases:
        refs = "、".join(c["provenance"]["lesson_refs"]) or "无坑号"
        lines.append(f"- **{c['case_id']}**（score={c['score']}）："
                     f"{c['problem']}")
        for s in c["symptoms"]:
            lines.append(f"  - 症状：{s}")
        lines.append(f"  - 解法/缓解：{c['solution']}（{refs}）")
    lines.append("")
    return "\n".join(lines)
