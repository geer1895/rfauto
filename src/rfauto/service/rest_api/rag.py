"""rest_api.rag —— RAG 只读检索端点（W3-S2 T2 拆分，逐字节搬迁）。"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .common import _error, _failure, _json_body, _ok, _opt_int, _opt_str


async def _rag_corpus_call(request: Request, corpus_fn: Any) -> JSONResponse:
    """rag query/explain 共用薄壳：docs_dir/runs_dir 缺省 docs/runs、
    显式 null 跳过该来源（与 CLI/MCP 同口径）；top_k/runs_limit 薄层
    校验挡掉 service 的 ValueError（那里抛出，这里进 400 信封）。"""
    body = await _json_body(request)
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return _error(400, "invalid_request", "text 必须是非空字符串")
    kwargs: dict[str, Any] = {"base_dir": "."}
    top_k = _opt_int(body, "top_k")
    if top_k is not None:
        if top_k < 1:
            return _error(400, "invalid_request", "top_k 必须 >= 1")
        kwargs["top_k"] = top_k
    runs_limit = _opt_int(body, "runs_limit")
    if runs_limit is not None:
        if runs_limit < 0:
            return _error(400, "invalid_request", "runs_limit 必须是非负整数")
        kwargs["runs_limit"] = runs_limit
    for key, default in (("docs_dir", "docs"), ("runs_dir", "runs")):
        if key in body:
            value = _opt_str(body, key)
            if value is not None:
                kwargs[key] = value
        else:
            kwargs[key] = default
    result = corpus_fn(text, **kwargs)
    if not result.get("ok"):
        return _failure(result)
    return _ok(result)


async def api_rag_query(request: Request) -> JSONResponse:
    """RAG 词法检索（rag_service.query_corpus 薄壳，只读、citation 可溯）。"""
    from rfauto.service.rag_service import query_corpus  # lazy: run-path（执行面按需取用）

    return await _rag_corpus_call(request, query_corpus)


async def api_rag_explain(request: Request) -> JSONResponse:
    """RAG 检索 + 逐词 BM25 分数明细（rag_service.explain_corpus 薄壳）。"""
    from rfauto.service.rag_service import explain_corpus  # lazy: run-path（执行面按需取用）

    return await _rag_corpus_call(request, explain_corpus)
