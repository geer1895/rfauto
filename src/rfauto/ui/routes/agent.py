"""agent 协作域路由（LLM 对话/沙箱草稿/审批收件箱/求解器注册表）——自 ui/server.py 逐函数搬家。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- POST      /api/chat             api_chat（同步 LLM 调用下放工作线程）
- GET/POST  /api/chat/settings    api_chat_settings
- POST      /api/chat/reset       api_chat_reset
- GET       /api/chat/prompt      api_chat_prompt（系统提示词只读面）
- GET       /api/chat/stats       api_chat_stats
- GET       /api/sandbox/drafts   api_sandbox_drafts
- GET       /api/sandbox/diff     api_sandbox_diff
- POST      /api/sandbox/promote  api_sandbox_promote
- GET       /api/solvers          api_solvers
- GET       /api/solvers/viz      api_solvers_viz
- GET       /api/inbox            api_inbox（待审批清单）
- POST      /api/inbox/approve    api_inbox_approve

_CHAT_INSTANCE/_chat_session 是进程内会话单例（历史在同一 UI 进程内保留）：
测试经 ``monkeypatch.setattr(rfauto.ui.routes.agent, "_CHAT_INSTANCE", None)``
重置（aurora_d UI-R1 自 server_mod 机械重靶，语义不变）。
"""

from __future__ import annotations

from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.ui.params import _int_param, _json_body

_CHAT_INSTANCE = None


def _chat_session():
    """会话级单例：历史在同一 UI 进程内保留（每请求新建会丢历史）。"""
    global _CHAT_INSTANCE
    if _CHAT_INSTANCE is None:
        from rfauto.service.r3_services import AgentChat
        _CHAT_INSTANCE = AgentChat()
    return _CHAT_INSTANCE


async def api_sandbox_drafts(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    return JSONResponse(ui_service.sandbox_drafts())


async def api_sandbox_diff(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    return JSONResponse(
        ui_service.sandbox_diff(request.query_params.get("recipe", "")))


async def api_sandbox_promote(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    body: dict[str, Any] = await _json_body(request)
    return JSONResponse(ui_service.sandbox_promote(
        body.get("recipe", ""), body.get("adapter", "fake")))


async def api_solvers(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import list_registered_solvers

    # P8-4（aurora_f W1-S1 真机实证）：冷扫 2.9-4.2s 系同步阻塞面（适配器
    # import+is_available 探测），原样在事件循环上直调会把整个 UI 服务停摆
    # ——并发请求（/api/tune/status 等）全部排队到扫完，前端渐进首绘被
    # 连坐。挪 worker 线程（api_chat 同款既有模式），循环不被阻塞。
    return JSONResponse(await run_in_threadpool(list_registered_solvers))


async def api_solvers_viz(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import list_solver_visualizations
    solver = request.query_params.get("solver")
    return JSONResponse(list_solver_visualizations(solver))


async def api_inbox(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import list_pending_approvals
    limit = _int_param(request.query_params.get("limit"), 20, "limit")
    return JSONResponse(list_pending_approvals(limit=limit))


async def api_inbox_approve(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import approve_proposal
    body: dict[str, Any] = await _json_body(request)
    result = approve_proposal(
        body.get("token_hash", ""),
        body.get("recipe", ""),
        body.get("adapter", "fake"),
    )
    return JSONResponse(result)


async def api_chat(request: Request) -> JSONResponse:
    body: dict[str, Any] = await _json_body(request)
    # A6 P1-3：chat 是同步 LLM 网络调用（真实配置下秒级到分钟级），此前
    # 裸跑在事件循环上——对话期间 SSE/全部轮询冻结。下放工作线程；会话
    # 单例与历史仍在本进程内（_chat_session 语义不变）。
    session = _chat_session()
    reply = await run_in_threadpool(session.chat, body.get("message", ""))
    return JSONResponse(reply)


async def api_chat_settings(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import get_chat_settings, save_chat_settings
    if request.method == "POST":
        body: dict[str, Any] = await _json_body(request)
        return JSONResponse(save_chat_settings(
            body.get("base_url", ""), body.get("model", ""), body.get("api_key", "")))
    return JSONResponse(get_chat_settings())


async def api_chat_reset(request: Request) -> JSONResponse:
    return JSONResponse(_chat_session().reset())


async def api_chat_prompt(request: Request) -> JSONResponse:
    from rfauto.service import r3_services
    from rfauto.service.envelope import ok_envelope

    # A8-D 信封收编：裸 dict → ok_envelope 单源（键集不变）
    return JSONResponse(ok_envelope(prompt=r3_services.get_system_prompt()))


async def api_chat_stats(request: Request) -> JSONResponse:
    from rfauto.service.envelope import ok_envelope

    return JSONResponse(ok_envelope(stats=_chat_session().stats))
