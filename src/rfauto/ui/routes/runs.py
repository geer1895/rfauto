"""run 域路由（清单/详情/对比/SSE/run 执行/报告图片）——自 ui/server.py 逐函数搬家。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- GET  /api/runs                              api_runs
- GET  /api/runs/diff                         api_runs_diff（双 run 只读对比）
- GET  /api/runs/{run_id}                     api_run_detail
- GET  /api/runs/{run_id}/events/stream       api_run_events_stream（P-1 SSE 桥）
- POST /api/run                               api_run（复用 service.run_once）
- GET  /api/runs/{run_id}/figs/{name:path}    api_run_fig（报告图片白名单）
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from rfauto.ui.params import _int_param, _json_body


async def api_runs(request: Request) -> JSONResponse:
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    limit = _int_param(request.query_params.get("limit"), 50, "limit")
    return JSONResponse(
        annotate_contract("list_runs", ui_service.list_runs(limit=limit)))


async def api_run_detail(request: Request) -> JSONResponse:
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    detail = ui_service.run_detail(request.path_params["run_id"])
    return JSONResponse(annotate_contract("run_detail", detail))


async def api_runs_diff(request: Request) -> JSONResponse:
    """双 run 只读对比（PR-4 报告页深化 ③，规格 §D-8）。

    业务在 rfauto.ui.runs_diff（ui 层，向下只 import service，分层契约
    允许）；只读零副作用。**必须注册在 /api/runs/{run_id} 之前**——否则
    "diff" 被参数路由当 run_id 吃掉（starlette 按注册序匹配，
    test_compare_endpoint_route_order 同款坑）。
    """
    from rfauto.ui.runs_diff import runs_diff

    q = request.query_params
    return JSONResponse(runs_diff(q.get("a", ""), q.get("b", "")))


#: P-1 SSE 桥参数（research_expansion round3 P-1：events.jsonl→单 endpoint
#: 按 run_id 过滤；前端 EventSource 自动重连，既有 3s 轮询端点保留为降级）。
_SSE_POLL_INTERVAL_S = 1.0
_SSE_MAX_IDLE_S = 300.0  # 无事件也定时断流——EventSource 自动重连续传


def _mirror_run_event(run_id: str, ev: dict) -> None:
    """UI-R3 统一事件流 runs 域懒馈送：桥读到的每条事件镜像进统一总线
    （kind=旧 event_type、payload=旧事件 dict 原样——旧字段零消失）。
    观测面 best-effort（#105）：吞一切异常，帧产出路径零影响。"""
    try:
        from rfauto.ui.routes.event_bus import try_publish

        try_publish(
            str(ev.get("event_type", "progress")), "runs", ev,
            dedupe_key=f"run:{run_id}:"
                       f"{ev.get('event_id') or ev.get('timestamp')}")
    except Exception:
        pass


async def api_run_events_stream(request: Request) -> Any:
    """P-1 战役进度 SSE 端点：``/api/runs/{run_id}/events/stream``。

    service.read_run_events 增量轮询 events.jsonl，每事件一帧 SSE
    （event=事件类型，data=事件 JSON），读到终态（run_completed/
    run_failed）后发 end 帧收束连接。长空闲自动断流靠 EventSource
    自动重连续传（浏览器语义），旧 3s 轮询端点不动（降级路径保留）。
    sse-starlette 缺装→503 JSON（best-effort #105，不拖垮整个 UI）。
    """
    from rfauto.service import ui_service

    try:
        from sse_starlette.sse import EventSourceResponse
    except ImportError as exc:
        # A8-D 信封收编：裸 dict → error_envelope 单源（键集不变）
        from rfauto.service.envelope import error_envelope

        return JSONResponse(
            error_envelope(
                [f"sse-starlette 未安装（pip install rfauto[ui]）: {exc}"]),
            status_code=503)

    run_id = str(request.path_params["run_id"])

    async def _gen():
        offset = 0
        idle_s = 0.0
        while True:
            snap = ui_service.read_run_events(run_id, offset)
            if not snap.get("ok"):
                yield {"event": "error",
                       "data": json.dumps({"errors": snap.get("errors", [])},
                                          ensure_ascii=False)}
                return
            if not snap.get("exists"):
                yield {"event": "end",
                       "data": json.dumps({"exists": False, "run_id": run_id},
                                          ensure_ascii=False)}
                return
            events = snap.get("events") or []
            for ev in events:
                _mirror_run_event(run_id, ev)  # UI-R3 统一流懒馈送（帧零改动）
                yield {"event": str(ev.get("event_type", "progress")),
                       "id": str(ev.get("event_id", "")),
                       "data": json.dumps(ev, ensure_ascii=False)}
            offset = int(snap.get("offset") or 0)
            if snap.get("terminal"):
                yield {"event": "end", "data": json.dumps(
                    {"terminal": True, "run_id": run_id}, ensure_ascii=False)}
                return
            idle_s = 0.0 if events else idle_s + _SSE_POLL_INTERVAL_S
            if idle_s >= _SSE_MAX_IDLE_S:
                return  # EventSource 自动重连后从 events.jsonl 重放续传
            await asyncio.sleep(_SSE_POLL_INTERVAL_S)

    return EventSourceResponse(_gen(), ping=15.0)


async def api_run(request: Request) -> JSONResponse:

    body: dict[str, Any] = await _json_body(request)
    from rfauto.service.api import run_once

    # A6 P1-3（review_aurora_next，R8-ENG2 落地）：run_once 同步全仿真此前
    # 裸跑在事件循环上——单次 run 期间（openEMS 分钟级）全部并发请求含
    # SSE 心跳一并冻结。照 api_tune_start 的下放范式改工作线程执行；
    # 单写锁仍在 service 层（并发语义不变）。
    result = await run_in_threadpool(
        run_once, body.get("path", ""),
        adapter_name=body.get("adapter", "fake"))
    return JSONResponse(result)


async def api_run_fig(request: Request) -> JSONResponse | FileResponse:
    """报告中心图片白名单路由（项 2 裂图修复）：只允许
    runs/<run_id>/results/figs/ 下的 .png/.svg；穿越/越界/缺失一律 404，
    前端 onerror 显示"该 run 无此图"占位（不裂图）。"""
    from rfauto.service.ui_service import run_fig_file

    fig = run_fig_file(request.path_params["run_id"],
                       request.path_params["name"])
    if fig is None:
        # A8-D 信封收编：裸 dict → error_envelope 单源（键集不变）
        from rfauto.service.envelope import error_envelope

        return JSONResponse(
            error_envelope(
                ["该 run 无此图（白名单：runs/<run_id>/results/figs/ "
                 "下的 .png/.svg）"]),
            status_code=404)
    return FileResponse(fig)
