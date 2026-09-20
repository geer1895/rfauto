"""warm_start_data —— 数据面：数据集历史样本 → warm-start 先验注入。

分层职责（stage-1 的 optimization/warm_start.py 只 import 不改）：
- 本模块（service 层）从 E1 数据集（dataset_service：Parquet 物化 + DuckDB
  直查）按模板族（``model`` 列）/来源 study（``study_name`` 列）过滤历史
  run 样本，解析 ``params_json`` 列，组装 ``{"params": dict, "cost": float}``
  样本列表喂给 ``run_optimization(warm_start=...)``。
- 相似度门（键 Jaccard ≥0.5 + 落界率 ≥0.5）在 optimization.warm_start 的
  ``warm_start_points`` 内——数据面只喂料不重复设门：异族样本同样透传，
  由 stage-1 门统一拒绝。
- 数据面只做"喂料合法性"清洗并计数上报：params_json 非法 JSON / None /
  非对象、params 或 cost 含 NaN/Inf、cost 缺失或非数值 → 跳过该样本并
  计数（物化侧已在收集源头整点拦截 params/metrics 非有限值——数据面遗留②
  根治；此处拦截保留为纵深防御：直写 Parquet/外部数据集的坏行照样拦，
  不得静默喂进门）。
- model/study 过滤经 query_dataset 的 ``?`` 参数绑定下推 DuckDB（值永不
  拼进 SQL 文本，防注入面不倒退），limit 在过滤后生效（数据面遗留③）；
  Python 侧精确相等过滤保留为纵深防御，where 参数仅原样透传
  query_dataset（其内部白名单校验负责防注入）。
- CLI/MCP 是薄壳（规则 4）；run_optimization 惰性导入（optimizer 依赖重，
  且便于单测 monkeypatch 钉住通道，#139）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from rfauto.service.dataset_service import DEFAULT_OUT_DIR, query_dataset

__all__ = [
    "collect_warm_start_samples",
    "run_optimization_warm_start_from_dataset",
]

# 查询列裁剪：喂料所需最小列集（cost/params_json 为核心，run_id/point_index 供溯源）
_QUERY_COLUMNS = ["run_id", "model", "study_name", "params_json", "cost", "point_index"]


def _has_nonfinite(value: Any) -> bool:
    """递归判定容器内是否含 NaN/Inf 浮点（params 平铺但值可能嵌套）。"""
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    if isinstance(value, dict):
        return any(_has_nonfinite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_nonfinite(v) for v in value)
    return False


def collect_warm_start_samples(
    dataset: str,
    *,
    model: str | None = None,
    source_study: str | None = None,
    where: str | None = None,
    limit: int = 1000,
    out_dir: str | Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    """从数据集收集 warm-start 喂料样本（JSON 进出）。

    Args:
        dataset: 数据集名（``datasets materialize`` 产物目录名）。
        model: 按模板族过滤（``model`` 列精确匹配）；None=不过滤。
        source_study: 按来源 study 名过滤（``study_name`` 列精确匹配）；
            None=不过滤。
        where: 额外 SQL WHERE 片段，原样透传 query_dataset（白名单校验在其内）。
        limit: 行数上限（数据面遗留③根治：model/study 过滤已 ``?`` 参数化下推
            DuckDB，limit 在过滤**之后**生效，按族取样不再漏样本）。
        out_dir: 数据集根目录（与 materialize_dataset 口径一致）。

    Returns:
        ``{"ok": True, "samples": [{"params", "cost", "run_id", "point_index"}],
        "n_rows_scanned", "n_samples", "n_filtered_by_model",
        "n_filtered_by_study", "n_skipped_invalid", "skip_reasons",
        "skip_examples", "limit", "filters"}``；数据集不存在/查询失败 →
        ``{"ok": False, "errors": [...]}``（空数据集如实报错，不静默）。
        样本均无效时 ok=True 且 ``samples=[]``——是否报错由调用方
        （run_optimization_warm_start_from_dataset）决定。
    """
    q = query_dataset(
        dataset,
        where=where,
        columns=list(_QUERY_COLUMNS),
        limit=limit,
        model=model,
        study_name=source_study,
        out_dir=out_dir,
    )
    if not q.get("ok"):
        return {"ok": False, "errors": list(q.get("errors") or ["数据集查询失败"])}

    samples: list[dict[str, Any]] = []
    n_filtered_model = 0
    n_filtered_study = 0
    skip_reasons: dict[str, int] = {}
    skip_examples: list[str] = []

    def _skip(reason: str, detail: str) -> None:
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        if len(skip_examples) < 3:
            skip_examples.append(f"{reason}: {detail}")

    for row in q.get("rows") or []:
        row_model = str(row.get("model") or "")
        row_study = str(row.get("study_name") or "")
        rid = str(row.get("run_id") or "?")
        pidx = row.get("point_index")
        tag = f"{rid}[{pidx}]"
        if model is not None and row_model != model:
            n_filtered_model += 1
            continue
        if source_study is not None and row_study != source_study:
            n_filtered_study += 1
            continue

        params_json = row.get("params_json")
        if params_json is None or not str(params_json).strip():
            _skip("params_json 缺失", tag)
            continue
        try:
            params = json.loads(str(params_json))
        except (ValueError, TypeError) as exc:
            _skip("params_json 非法 JSON", f"{tag}（{exc}）")
            continue
        if not isinstance(params, dict):
            _skip("params 非对象", tag)
            continue
        if _has_nonfinite(params):
            _skip("params 含 NaN/Inf", tag)  # P2 残余显式拦截，不静默
            continue

        cost = row.get("cost")
        if cost is None or isinstance(cost, bool) or not isinstance(cost, (int, float)):
            _skip("cost 缺失或非数值", tag)
            continue
        cost_f = float(cost)
        if math.isnan(cost_f) or math.isinf(cost_f):
            _skip("cost 含 NaN/Inf", tag)
            continue

        samples.append({
            "params": params,
            "cost": cost_f,
            "run_id": rid,
            "point_index": pidx,
        })

    return {
        "ok": True,
        "dataset": str(q.get("dataset") or dataset),
        "samples": samples,
        "n_rows_scanned": int(q.get("n_rows") or 0),
        "n_samples": len(samples),
        "n_filtered_by_model": n_filtered_model,
        "n_filtered_by_study": n_filtered_study,
        "n_skipped_invalid": sum(skip_reasons.values()),
        "skip_reasons": skip_reasons,
        "skip_examples": skip_examples,
        "limit": int(q.get("limit") or limit),
        # 下推回执（观测面）：model/study 已在 SQL 侧过滤，Python 侧过滤
        # 保留为纵深防御，正常时 n_filtered_* 为 0
        "filters": dict(q.get("filters") or {}),
    }


def run_optimization_warm_start_from_dataset(
    recipe_path: str,
    dataset: str,
    *,
    model: str | None = None,
    source_study: str | None = None,
    where: str | None = None,
    limit: int = 1000,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    adapter_name: str = "fake",
    max_trials: int = 60,
    study_name: str | None = None,
    sampler: str = "tpe",
    adapter_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """数据集历史样本 → warm-start 注入优化（端到端，JSON 进出）。

    数据面：``collect_warm_start_samples`` 取样清洗 → 透传
    ``run_optimization(warm_start=...)``（相似度门/排队/优化全在 stage-1
    内）。数据集不可用或无有效样本时如实报错返回 ok=False，不偷偷降级
    冷启动（调用方明确要求 warm-start 通道时静默降级=硬凑）；stage-1 门
    拒绝异族样本属正常降级（ok=True 且 warm_start_n=0），不在本层拦截。

    Returns:
        run_optimization 结果，附加 ``warm_start_data``（数据面统计，
        不含 samples 本体防重复大对象）。
    """
    collect = collect_warm_start_samples(
        dataset, model=model, source_study=source_study, where=where,
        limit=limit, out_dir=out_dir,
    )
    data_stats = {k: v for k, v in collect.items() if k != "samples"}
    if not collect.get("ok"):
        return {
            "ok": False,
            "errors": [*collect.get("errors", []), "数据集不可用，无法构建 warm-start 喂料"],
            "warm_start_data": data_stats,
        }
    if not collect.get("samples"):
        return {
            "ok": False,
            "errors": [
                f"数据集 {dataset} 无可用历史样本"
                f"（扫描 {collect.get('n_rows_scanned', 0)} 行，"
                f"无效 {collect.get('n_skipped_invalid', 0)}，"
                f"族过滤 {collect.get('n_filtered_by_model', 0)}，"
                f"study 过滤 {collect.get('n_filtered_by_study', 0)}）"
            ],
            "warm_start_data": data_stats,
        }

    from rfauto.optimization.optimizer import run_optimization

    result = run_optimization(
        recipe_path,
        adapter_name=adapter_name,
        max_trials=max_trials,
        study_name=study_name,
        adapter_kwargs=adapter_kwargs,
        sampler=sampler,
        warm_start=collect["samples"],
    )
    # 优化失败（配方缺失/参数空间空等）也带数据面统计透出，便于归因
    if isinstance(result, dict):
        result["warm_start_data"] = data_stats
    return result
