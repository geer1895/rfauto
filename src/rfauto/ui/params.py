"""UI 路由层参数守卫单源（ParamError + _int_param + _json_body）。

A8-D（aurora72，2026-10-12）在 ui/server.py 引入 ParamError→400 error 信封
机制（limit=abc 等 11 端点此前 handler 内 int()/float() 裸解析抛 ValueError
→ Starlette 500 纯文本，失败面无信封，契约 §4 违约面）。A6 P0-2（
review_aurora_next 审查，2026-10-13）实证 campaign_app 自 server.py 机械拆
分（UX-B6）时漏收编同款守卫（``grid_n=abc`` → 500 裸崩）——拆出本共享小
模块而非 campaign_app 反向 import server（server ⇄ campaign_app 既有单向
依赖，反向 lazy import 成环难读）；server.py 薄 re-export 保持既有引用路径
``rfauto.ui.server.ParamError`` 不变。

规则红线（内核立规注记 #90/#92）：守卫只做"参数形状合法性"判定（传输壳职责），
不碰业务解释——业务语义仍在 service 层。
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request


class ParamError(Exception):
    """路由层查询/请求参数非法（A8-D：非法参数 500 裸崩 → 400 error 信封）。

    经 create_ui_app 的 exception_handlers 归一为 400
    ``{"ok": False, "errors": [...]}``（error_envelope 单源构造器），不改任何
    成功路径行为。
    """


def _int_param(raw: Any, default: int, name: str) -> int:
    """整数参数安全解析：缺省/空串回默认值；非法值抛 ParamError（400 信封）。"""
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ParamError(
            f"{name} 须为整数，实际 {raw!r}（示例：{name}={default}）") from None


async def _json_body(request: Request) -> dict[str, Any]:
    """POST 请求体安全解析：坏 JSON / 非对象 → ParamError（400 信封）。

    A4 P0-3（review_aurora_next 审查，2026-10-13）：ui/server.py 12+ 个 POST
    handler 此前裸 ``await request.json()``，畸形 JSON 体抛
    json.JSONDecodeError 非 ParamError、无 handler → 500 纯文本（非回环部署
    ``rfauto ui --host 0.0.0.0`` 是显式支持形态，任何非浏览器客户端都易触发）。
    与程序化面 service/rest_api.py ``_json_body`` 同款守卫（双 HTTP 面失败
    语义对齐）：非法 JSON 与非对象体（数组/标量——``body.get`` 会 AttributeError
    → 同 500）都归一 400 信封。
    """
    try:
        body = await request.json()
    except Exception as exc:  # JSONDecodeError/UnicodeDecodeError 等解码面
        raise ParamError(f"请求体必须是合法 JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ParamError("请求体必须是 JSON 对象")
    return body
