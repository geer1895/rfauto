"""rest_api.calculators —— 计算器执行端点（W3-S2 T2 拆分，逐字节搬迁）。"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from .common import _FALSE_STRINGS, _error, _failure, _json_body, _ok


async def api_list_calculators(request: Request) -> JSONResponse:
    """计算器清单（calculator_service.list_calculators 薄壳）。

    ``?include_experimental=false`` 剔除实验键（默认列出并打 experimental 标签）。
    """
    from rfauto.service.calculator_service import list_calculators  # lazy: run-path（执行面按需取用）

    raw = request.query_params.get("include_experimental", "true")
    include_experimental = str(raw).strip().lower() not in _FALSE_STRINGS
    return _ok(list_calculators(include_experimental=include_experimental))


async def api_run_calculator(request: Request) -> JSONResponse:
    """执行一个计算器（calculator_service.run_calculator 薄壳）。

    body.allow_experimental（bool|null 三态）透传：实验性公式默认拒跑，
    True 显式放行、False 显式拒绝、缺省读配置 calculators.allow_experimental。
    """
    from rfauto.service.calculator_service import run_calculator  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    params = body.get("params")
    if params is not None and not isinstance(params, dict):
        return _error(400, "invalid_request", "params 必须是对象或省略")
    allow_experimental = body.get("allow_experimental")
    if allow_experimental is not None and not isinstance(allow_experimental, bool):
        return _error(400, "invalid_request",
                      "allow_experimental 必须是布尔值或省略")
    result = run_calculator(request.path_params["name"], params or {},
                            allow_experimental=allow_experimental)
    if not result.get("ok"):
        return _failure(result)
    return _ok(result)
