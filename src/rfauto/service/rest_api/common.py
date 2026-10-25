"""rest_api.common —— 信封/错误映射与壳层参数校验助手。

自 rest_api.py 巨石按职责域拆分（aurora_h W3-S2，AU-1 工艺）：代码体自
原「常量」「BadRequestError」「信封与错误映射」与壳层校验助手
（_require_name/_opt_*/_require_numbers）逐字节搬迁。
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.service.envelope import ok_envelope

API_PREFIX = "/api/v1"
OPENAPI_VERSION = "3.0.3"
API_TITLE = "rfauto REST API"
API_DESCRIPTION = "rfauto service 层能力的薄壳 REST 封装（G1，§10.7）"

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_NOT_FOUND_MARKERS = ("不存在", "未注册", "未找到", "not found")


class BadRequestError(Exception):
    """请求体/参数校验失败（app 级 exception handler 统一转 400 信封）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 信封与错误映射
# ---------------------------------------------------------------------------

def _ok(data: Any) -> JSONResponse:
    """成功信封出口（构造器单源收编，aurora_d REST-B；线形逐字节不变）。"""
    return JSONResponse(ok_envelope(data=data))


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
    )


def _messages(result: dict[str, Any]) -> list[str]:
    """从 service 结果抽错误文本（errors 列表优先，其次单 error 串）。"""
    errors = result.get("errors")
    if isinstance(errors, list) and errors:
        return [str(e) for e in errors]
    if result.get("error"):
        return [str(result["error"])]
    return ["service 返回 ok=False 但未提供错误信息"]


def _is_not_found(result: dict[str, Any]) -> bool:
    """service 层"资源不存在"标记 → HTTP 404（否则 400 非法输入）。"""
    return any(
        marker in message
        for message in _messages(result)
        for marker in _NOT_FOUND_MARKERS
    )


def _failure(result: dict[str, Any]) -> JSONResponse:
    messages = _messages(result)
    message = messages[0] if len(messages) == 1 else "; ".join(messages)
    if _is_not_found(result):
        return _error(404, "not_found", message)
    return _error(400, "invalid_request", message)


async def _bad_request_handler(request: Request, exc: Exception) -> JSONResponse:
    error = exc if isinstance(exc, BadRequestError) else BadRequestError(
        "bad_request", str(exc))
    return _error(400, error.code, error.message)


async def _json_body(request: Request) -> dict[str, Any]:
    """解析 JSON 请求体；非法 JSON / 非对象 → BadRequestError（400 信封）。"""
    try:
        body = await request.json()
    except Exception as exc:  # JSONDecodeError 等
        raise BadRequestError("bad_json", f"请求体必须是合法 JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise BadRequestError("invalid_request", "请求体必须是 JSON 对象")
    return body


_FALSE_STRINGS = frozenset({"0", "false", "no", "off"})


def _require_name(body: dict[str, Any]) -> str:
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise BadRequestError("invalid_request", "name 必须是非空字符串")
    return name


def _opt_int(body: dict[str, Any], key: str) -> int | None:
    """可选整数参数：缺省/None → None；非整数（含 bool）→ 400。"""
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadRequestError("invalid_request", f"{key} 必须是整数")
    return value


def _opt_bool(body: dict[str, Any], key: str) -> bool | None:
    """可选布尔参数：缺省/None → None；非 bool → 400（不做 "yes" 强转）。"""
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise BadRequestError("invalid_request", f"{key} 必须是布尔值")
    return value


def _opt_str(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadRequestError("invalid_request", f"{key} 必须是字符串")
    return value


def _opt_number(body: dict[str, Any], key: str) -> float | None:
    """可选数值参数：缺省/None → None；非数值（含 bool）→ 400。"""
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BadRequestError("invalid_request", f"{key} 必须是数值")
    return value


def _require_numbers(body: dict[str, Any],
                     keys: tuple[str, ...]) -> dict[str, Any] | None:
    """必填数值参数收集：任一缺失/非数值 → None（调用方统一回 400）。

    只挡"非 JSON 数值"；有效域/单位语义仍在 service 层（越域拒绝进信封）。
    """
    kwargs: dict[str, Any] = {}
    for key in keys:
        value = body.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        kwargs[key] = value
    return kwargs
