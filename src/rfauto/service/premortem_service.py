"""premortem_service：Pre-mortem 失败预演薄封装（XN-1，第十九轮 P1）。

内核在 core/premortem.py（确定性规则引擎，LLM 不产失败模式——硬规则 7）；
本模块只做 JSON 进出薄壳——负例（未知 task_kind）转 ok=False+errors，不抛穿。

消费挂点（round19 口径"战役/设计开工前自动生成"）：
- service/campaign_manager.plan_campaign 在战役计划成形后附带
  plan["premortem"]（best-effort #105，不阻塞战役）——战役=param_sweep 主类。
- 独立调用：premortem_report(task_kind, context) 任意开工面可用
  （真机求解/校准/综合注册/模板注册等，五类起步）。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rfauto.core.premortem import (
    DEFAULT_TOP_K,
    TASK_KINDS,
    premortem,
    render_premortem_markdown,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _pitfall_notes(task_kind: Any, context: Any) -> list[str]:
    """坑账索引按 task_kind+context 关键词的命中注记（X6 消费第一接线）。

    best-effort（#105 观测性纪律）：索引缺席/畸形/检索失败一律静默空列表，
    绝不让增强面成为 premortem 主路径的故障点。keywords 确定性
    （task_kind + context 的键名），同输入两次逐位一致。
    """
    try:
        from rfauto.service.pitfall_index_service import (
            load_pitfall_index,
            pitfall_notes_for,
        )

        index = load_pitfall_index()
        if not index.get("ok"):
            return []
        keywords = [str(task_kind)]
        if isinstance(context, Mapping):
            keywords.extend(str(k) for k in context)
        return pitfall_notes_for(index, keywords)
    except Exception:  # best-effort：失败静默 skip 不阻塞（任务书 F-16 口径）
        return []


def premortem_report(task_kind: Any, context: Any = None, *,
                     top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """开工前失败预演报告（JSON 进出；未知 task_kind → ok=False+errors）。

    透传 core.premortem.premortem（同输入两次逐位一致）；附 markdown 渲染面
    与坑账索引命中注记 pitfall_notes（best-effort，索引缺席时无该键）。
    """
    try:
        result = premortem(task_kind, context, top_k=top_k)
    except ValueError as exc:
        return error_envelope([str(exc)])
    result["markdown"] = render_premortem_markdown(result)
    notes = _pitfall_notes(task_kind, context)
    if notes:
        result["pitfall_notes"] = notes
    return result


def premortem_task_kinds() -> dict[str, Any]:
    """五类起步任务清单（供薄壳列表渲染；确定性 TASK_KINDS 序）。"""
    return ok_envelope(task_kinds=list(TASK_KINDS), n_kinds=len(TASK_KINDS))


#: 战役计划附带块的模式裁剪数（计划 JSON 体积友好；全量走 premortem_report）。
_CAMPAIGN_TOP_MODES = 10


def campaign_premortem_block(model: Any = "", recipe: Any = "") -> dict[str, Any]:
    """战役开工 premortem 附带块（campaign_manager.plan_campaign 消费）。

    战役 = param_sweep 主类；context 传战役声明面（model/recipe 名）——
    探针按"在案？"判定，开工时未声明即如实报 open（防线清单，不假装已闭合）。
    返回裁剪块：top 模式（id/模式/档/探针）+ 核对表 + 未闭合探针清单。
    """
    ctx: dict[str, Any] = {"campaign_model": str(model or ""),
                           "recipe": str(recipe or "")}
    report = premortem("param_sweep", ctx)
    if not report.get("ok"):
        return report
    return ok_envelope(
        task_kind=report["task_kind"],
        task_kind_label=report["task_kind_label"],
        n_modes_total=report["n_modes_total"],
        top_modes=[
            {"mode_id": m["mode_id"], "mode": m["mode"],
             "likelihood_band": m["likelihood_band"],
             "detection_probe": m["detection_probe"],
             "mitigation_ref": m["mitigation_ref"]}
            for m in report["failure_modes"][:_CAMPAIGN_TOP_MODES]
        ],
        checklist=report["checklist"],
        open_probes=[
            {"probe_id": p["probe_id"], "question": p["question"],
             "detail": p["detail"]}
            for p in report.get("probe_report", []) if not p["ok"]
        ],
        n_open_probes=report.get("n_probes_open", 0),
    )


def premortem_for_context(task: Mapping[str, Any]) -> dict[str, Any]:
    """从任务描述映射推断 task_kind 并出报告（level2/agent 编排友好口）。

    识别键：task_kind（规范 id/别名，优先）/ kind；都缺省按 param_sweep
    （战役面缺省——round19"战役/设计开工前"主场景）。context 原样透传。
    """
    kind = task.get("task_kind") or task.get("kind") or "param_sweep"
    return premortem_report(kind, dict(task))


def save_premortem_report(report: Mapping[str, Any], path: str | Path) -> dict[str, Any]:
    """premortem 报告落盘（UTF-8 JSON，sort_keys 字节稳定；观测 best-effort 面）。"""
    import json

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dict(report), ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")
    return ok_envelope(path=str(target))
