"""rest_api.datasets —— 数据集直查/insights 八接口/工作目录发现端点。

自 rest_api.py 巨石按职责域拆分（aurora_h W3-S2，AU-1 工艺）：代码体自
原「datasets 直查」「datasets 余量（dataset_insights 八接口薄壳）」与
「工作目录形态发现」逐字节搬迁。
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .common import (
    _error,
    _failure,
    _is_not_found,
    _json_body,
    _messages,
    _ok,
    _opt_bool,
    _opt_int,
    _opt_str,
    _require_name,
)


async def api_query_dataset(request: Request) -> JSONResponse:
    """数据集直查（dataset_service.query_dataset 薄壳）。"""
    from rfauto.service.dataset_service import query_dataset  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    name = body.get("name")
    if not isinstance(name, str) or not name:
        return _error(400, "invalid_request", "name 必须是非空字符串")
    kwargs: dict[str, Any] = {}
    for key in ("where", "columns", "limit", "model", "study_name"):
        if body.get(key) is not None:
            kwargs[key] = body[key]
    result = query_dataset(name, **kwargs)
    if not result.get("ok"):
        # 错误文案收敛（审查 P1-2 同批）：仅"数据集不存在"保留原文（404
        # 语义需要）；其余拒绝一律统一文案，不透传 where 原文/引擎细节
        # ——注入 payload 的回执不得成为探测 oracle。
        if _is_not_found(result):
            messages = _messages(result)
            message = messages[0] if len(messages) == 1 else "; ".join(messages)
            return _error(404, "not_found", message)
        return _error(400, "invalid_request",
                      "查询被拒绝: where 表达式或查询参数非法"
                      "（原始引擎错误不透出）")
    return _ok(result)


# ---- datasets 余量（dataset_insights 八接口薄壳，E1 收口 re-export）-----


def _dataset_result(result: dict[str, Any]) -> JSONResponse:
    """dataset_insights 结果 → 信封：双集污染（overlap_ids 非空）映射 409
    conflict（状态冲突而非输入非法），其余沿用 _failure（404/400）。"""
    if result.get("ok"):
        return _ok(result)
    if result.get("overlap_ids"):
        messages = _messages(result)
        return _error(409, "conflict",
                      messages[0] if len(messages) == 1 else "; ".join(messages))
    return _failure(result)


async def api_list_datasets(request: Request) -> JSONResponse:
    """数据集注册表总览（dataset_insights.list_datasets 薄壳）。"""
    from rfauto.service.dataset_insights import list_datasets  # lazy: run-path（执行面按需取用）

    visibility = request.query_params.get("visibility") or None
    return _dataset_result(list_datasets(visibility=visibility))


async def api_dataset_coverage(request: Request) -> JSONResponse:
    """点数/参数空间覆盖度（dataset_insights.dataset_coverage 薄壳）。"""
    from rfauto.service.dataset_insights import dataset_coverage  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    name = _require_name(body)
    kwargs: dict[str, Any] = {}
    bins = _opt_int(body, "bins")
    if bins is not None:
        kwargs["bins"] = bins
    return _dataset_result(dataset_coverage(name, **kwargs))


async def api_dataset_annotate_ground_truth(request: Request) -> JSONResponse:
    """ground truth 标注回写（dataset_insights.annotate_ground_truth 薄壳）。"""
    from rfauto.service.dataset_insights import annotate_ground_truth  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    name = _require_name(body)
    kwargs: dict[str, Any] = {}
    threshold = _opt_int(body, "threshold")
    if threshold is not None:
        kwargs["threshold"] = threshold
    return _dataset_result(annotate_ground_truth(name, **kwargs))


async def api_dataset_neural_operator_readiness(request: Request) -> JSONResponse:
    """6.3 神经算子解锁进度（dataset_insights.neural_operator_readiness 薄壳）。"""
    from rfauto.service.dataset_insights import neural_operator_readiness  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    name = _require_name(body)
    kwargs: dict[str, Any] = {}
    threshold = _opt_int(body, "threshold")
    if threshold is not None:
        kwargs["threshold"] = threshold
    return _dataset_result(neural_operator_readiness(name, **kwargs))


async def api_dataset_set_visibility(request: Request) -> JSONResponse:
    """公开/私有切换（dataset_insights.set_dataset_visibility 薄壳）。"""
    from rfauto.service.dataset_insights import set_dataset_visibility  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    name = _require_name(body)
    visibility = body.get("visibility")
    if not isinstance(visibility, str) or not visibility:
        return _error(400, "invalid_request",
                      "visibility 必须是非空字符串（public/private）")
    return _dataset_result(set_dataset_visibility(name, visibility))


async def api_dataset_export_hf(request: Request) -> JSONResponse:
    """HuggingFace 布局导出（dataset_insights.export_hf_dataset 薄壳）。"""
    from rfauto.service.dataset_insights import export_hf_dataset  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    name = _require_name(body)
    kwargs: dict[str, Any] = {}
    lic = _opt_str(body, "license")
    if lic is not None:
        kwargs["license"] = lic
    allow_private = _opt_bool(body, "allow_private")
    if allow_private is not None:
        kwargs["allow_private"] = allow_private
    return _dataset_result(export_hf_dataset(name, **kwargs))


async def api_dataset_register_public(request: Request) -> JSONResponse:
    """公开集注册路径（dataset_insights.register_public_dataset 薄壳）。"""
    from rfauto.service.dataset_insights import register_public_dataset  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    name = _require_name(body)
    kwargs: dict[str, Any] = {}
    for key in ("source", "license"):
        value = _opt_str(body, key)
        if value is not None:
            kwargs[key] = value
    promote = _opt_bool(body, "promote")
    if promote is not None:
        kwargs["promote"] = promote
    return _dataset_result(register_public_dataset(name, **kwargs))


async def api_dataset_sets(request: Request) -> JSONResponse:
    """公开/私有双集装载 + 防污染检查（dataset_insights.load_dataset_sets
    薄壳；id 交集非空 → 409 conflict）。"""
    from rfauto.service.dataset_insights import load_dataset_sets  # lazy: run-path（执行面按需取用）

    return _dataset_result(load_dataset_sets())


async def api_dataset_discover_workdir(request: Request) -> JSONResponse:
    """工作目录形态真机产物发现（dataset_service.discover_workdir_candidates
    薄壳，只读；import 是写操作不经 REST）。"""
    from rfauto.service.dataset_service import discover_workdir_candidates  # lazy: run-path（执行面按需取用）

    models_raw = request.query_params.get("models")
    models = ([m.strip() for m in models_raw.split(",") if m.strip()]
              if models_raw else None)
    result = discover_workdir_candidates(
        request.query_params.get("runs_root") or "runs", models=models)
    if not result.get("ok"):
        return _failure(result)
    return _ok(result)
