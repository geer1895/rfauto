"""rest_api.db —— 注册表只读端点（W3-S2 T2 拆分，逐字节搬迁）。"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .common import _error, _failure, _json_body, _ok, _opt_int, _opt_str

# ---- db / rag / 工作目录发现 / slotline·transitions（只读透传，F-R2-3）-----
# 四批新增壳的 REST/SDK 只读查询面补齐：零逻辑转发 service 层（规则 4）；
# db 只暴露 status/query_safe 只读口（init/migrate/reindex 写操作不暴露），
# importer 只暴露 discover（import 写数据集不暴露）；slotline/transitions
# 五入口全是确定性计算（数值只出内核，铁律 7）。

async def api_db_status(request: Request) -> JSONResponse:
    """注册表状态盘点（db_service.db_status 薄壳，只读不建库）。

    A4 P0-2：非 SQLite 文件/目录路径的服务层失败信封 → 400（同模块
    ``_failure`` 收口惯例，不再 500 纯文本裸崩）。"""
    from rfauto.service.db_service import db_status  # lazy: run-path（执行面按需取用）

    result = db_status(request.query_params.get("db_path") or None)
    if not result.get("ok"):
        return _failure(result)
    return _ok(result)


async def api_db_query(request: Request) -> JSONResponse:
    """只读查询注册表（db_service.db_query_safe 薄壳：SELECT 白名单 +
    ? 占位符参数绑定；拒绝/执行错误进信封）。"""
    from rfauto.service.db_service import db_query_safe  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    sql = body.get("sql")
    if not isinstance(sql, str) or not sql:
        return _error(400, "invalid_request", "sql 必须是非空字符串")
    kwargs: dict[str, Any] = {}
    params = body.get("params")
    if params is not None:
        if not isinstance(params, list):
            return _error(400, "invalid_request", "params 必须是标量数组或省略")
        kwargs["params"] = params
    limit = _opt_int(body, "limit")
    if limit is not None:
        kwargs["limit"] = limit
    db_path = _opt_str(body, "db_path")
    if db_path is not None:
        kwargs["db_path"] = db_path
    result = db_query_safe(sql, **kwargs)
    if not result.get("ok"):
        return _failure(result)
    return _ok(result)
