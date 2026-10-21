"""rest_api.runs —— run 查询端点（W3-S2 T2 拆分，逐字节搬迁）。"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from .common import _error, _failure, _ok


async def api_list_runs(request: Request) -> JSONResponse:
    """run 列表（ui_service.list_runs 薄壳）。"""
    from rfauto.service import ui_service  # lazy: run-path（执行面按需取用）

    raw = request.query_params.get("limit", "50")
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return _error(400, "invalid_request", f"limit 必须是整数，收到 {raw!r}")
    if limit < 1 or limit > 1000:
        return _error(400, "invalid_request", f"limit 必须在 [1, 1000]，收到 {limit}")
    return _ok(ui_service.list_runs(limit=limit))


async def api_run_detail(request: Request) -> JSONResponse:
    """单次 run 全量中间产物（ui_service.run_detail 薄壳）。"""
    from rfauto.service import ui_service  # lazy: run-path（执行面按需取用）

    result = ui_service.run_detail(request.path_params["run_id"])
    if not result.get("ok"):
        return _failure(result)
    return _ok(result)
