"""rfauto 人工核验 UI（本地 web 服务，starlette + uvicorn）。

设计红线：路由是薄壳，全部业务在 service/ui_service.py（JSON 进出）；
只读 endpoints 无副作用，POST /api/run 复用 service.run_once（单写锁在那层）。
启动：rfauto ui（默认 127.0.0.1:8642，不对外网监听）。

双 HTTP 面职责边界（A-2，code_audit_slice6）：本模块是**人工工作台**
（api/*，loopback 8642，浏览器交互消费）；程序化 REST 面在
service/rest_api.py（api/v1/*，传输壳禁业务逻辑，8644）——两边各自独立
路由表，新增能力按消费方选面，不在两边互相转发。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

_STATIC_DIR = Path(__file__).parent / "static"

# D-04（2026-10-05 W1-E）：CSP 响应头——script-src 'self' + 唯一内联脚本的
# 内容哈希钉。接地（index.html 现状）：6 个 <script> 中 5 个外链
# （3 vendor + 2 module），唯一内联是 <script type="importmap">——外部
# importmap 浏览器不支持（改外链不可行），'unsafe-inline' 又会豁免全部
# 内联脚本，故按 CSP3 对该 JSON 内容做 sha256 哈希钉：importmap 内容任何
# 改动都会被浏览器拒绝加载，tests/unit/test_w1e_ui_csp.py 会同步抓出
# 哈希失配。只下 script-src 单指令、不下 default-src（index.html 有内联
# <style> 与 style="" 属性，default-src 'self' 会连带禁掉内联样式打断
# 现有渲染）；页内处理器全部是 JS 侧 .onclick= 属性赋值（非 HTML 内联
# on* 属性），不受 script-src 影响；vendor/echarts.min.js 里的 new Function
# 是 JSON.parse 守卫后的死回退分支（实测运行路径不触），无需 unsafe-eval。
_IMPORTMAP_SHA256 = "sha256-IpwqAkJYJf7czCtp9NzVZDetH2T3BlxA1lkI/4V7auk="
CSP_HEADER = "Content-Security-Policy"
CSP_VALUE = f"script-src 'self' '{_IMPORTMAP_SHA256}'"


class ContentSecurityPolicyMiddleware:
    """纯 ASGI 中间件：全部 HTTP 响应附加 CSP 头（D-04）。

    setitem 覆写语义保证重复包裹/上游已有同名头时单头不叠；非 http scope
    （websocket/lifespan，如 SSE 由 http 起步不受影响）原样直通（#105：
    观测/加固面故障不得阻塞业务主路径——头写入本身不抛，异常面已由
    Starlette 响应生命周期兜住）。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_csp(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[CSP_HEADER] = CSP_VALUE
            await send(message)

        await self.app(scope, receive, send_with_csp)


async def api_runs(request: Request) -> JSONResponse:
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    limit = int(request.query_params.get("limit", "50"))
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


#: P-1 SSE 桥参数（研究扩充 round3 P-1：events.jsonl→单 endpoint
#: 按 run_id 过滤；前端 EventSource 自动重连，既有 3s 轮询端点保留为降级）。
_SSE_POLL_INTERVAL_S = 1.0
_SSE_MAX_IDLE_S = 300.0  # 无事件也定时断流——EventSource 自动重连续传


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
        return JSONResponse(
            {"ok": False,
             "errors": [f"sse-starlette 未安装（pip install rfauto[ui]）: {exc}"]},
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


async def api_recipe(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    path = request.query_params.get("path", "")
    return JSONResponse(ui_service.recipe_view(path))


async def api_recipe_save(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    body: dict[str, Any] = await request.json()
    if body.get("create") is not None:
        # 新建配方（工程导入向导用）：YAML 序列化/落盘全在 service（#90/#92）
        return JSONResponse(
            ui_service.recipe_create(body.get("path", ""), body["create"]))
    result = ui_service.recipe_save(body.get("path", ""), body.get("updates", {}))
    return JSONResponse(result)


async def api_model3d(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    if request.method == "POST":
        body: dict[str, Any] = await request.json()
        # 几何求解在 service/确定性内核；UI 层只传模板名+参数（#90/#92）
        return JSONResponse(ui_service.model3d_for_params(
            body.get("template", "wilkinson"),
            body.get("params", {}) or {},
            body.get("substrate"),
        ))
    return JSONResponse(
        ui_service.model3d_for_recipe(request.query_params.get("path", ""))
    )


async def api_run(request: Request) -> JSONResponse:

    body: dict[str, Any] = await request.json()
    from rfauto.service.api import run_once

    result = run_once(
        body.get("path", ""),
        adapter_name=body.get("adapter", "fake"),
    )
    return JSONResponse(result)


# ── 调参（后台线程 + 状态查询，UI 不阻塞）──────────────────────────────
_TUNE_STATE: dict[str, Any] = {"running": False, "log": [], "result": None,
                               "started_at": None, "error": None}


async def api_tune_start(request: Request) -> JSONResponse:
    import threading
    from datetime import datetime

    from rfauto.service.api import start_tune, start_tune_multi

    if _TUNE_STATE["running"]:
        return JSONResponse({"ok": False, "error": "已有调参任务在运行"})
    body: dict[str, Any] = await request.json()

    def _run() -> None:
        try:
            if body.get("multi"):
                result = start_tune_multi(
                    body.get("path", ""), adapter_name=body.get("adapter", "fake"),
                    n_gen=int(body.get("n_gen", 20)), pop_size=int(body.get("pop_size", 12)))
            else:
                result = start_tune(
                    body.get("path", ""), adapter_name=body.get("adapter", "fake"),
                    max_trials=int(body.get("max_trials", 30)),
                    sampler=body.get("sampler", "tpe"))
            _TUNE_STATE["result"] = result
        except Exception as exc:  # 线程内异常落状态，不让 UI 悬死
            _TUNE_STATE["error"] = str(exc)
        finally:
            _TUNE_STATE["running"] = False

    _TUNE_STATE.update({"running": True, "log": [], "result": None,
                        "error": None, "started_at": datetime.now().isoformat(timespec="seconds")})
    threading.Thread(target=_run, daemon=True).start()
    return JSONResponse({"ok": True, "started": True})


async def api_tune_status(request: Request) -> JSONResponse:
    return JSONResponse({k: _TUNE_STATE[k] for k in
                         ("running", "result", "error", "started_at")})


async def api_tune_trials(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    run_id = request.query_params.get("run_id") or None
    return JSONResponse(ui_service.tune_trials(run_id))


async def api_sandbox_drafts(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    return JSONResponse(ui_service.sandbox_drafts())


async def api_sandbox_diff(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    return JSONResponse(
        ui_service.sandbox_diff(request.query_params.get("recipe", "")))


async def api_sandbox_promote(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    body: dict[str, Any] = await request.json()
    return JSONResponse(ui_service.sandbox_promote(
        body.get("recipe", ""), body.get("adapter", "fake")))


async def api_solvers(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import list_registered_solvers
    return JSONResponse(list_registered_solvers())


async def api_solvers_viz(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import list_solver_visualizations
    solver = request.query_params.get("solver")
    return JSONResponse(list_solver_visualizations(solver))


async def api_inbox(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import list_pending_approvals
    limit = int(request.query_params.get("limit", "20"))
    return JSONResponse(list_pending_approvals(limit=limit))


async def api_inbox_approve(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import approve_proposal
    body: dict[str, Any] = await request.json()
    result = approve_proposal(
        body.get("token_hash", ""),
        body.get("recipe", ""),
        body.get("adapter", "fake"),
    )
    return JSONResponse(result)


_CHAT_INSTANCE = None


def _chat_session():
    """会话级单例：历史在同一 UI 进程内保留（每请求新建会丢历史）。"""
    global _CHAT_INSTANCE
    if _CHAT_INSTANCE is None:
        from rfauto.service.r3_services import AgentChat
        _CHAT_INSTANCE = AgentChat()
    return _CHAT_INSTANCE


async def api_chat(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()
    return JSONResponse(_chat_session().chat(body.get("message", "")))


async def api_chat_settings(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import get_chat_settings, save_chat_settings
    if request.method == "POST":
        body: dict[str, Any] = await request.json()
        return JSONResponse(save_chat_settings(
            body.get("base_url", ""), body.get("model", ""), body.get("api_key", "")))
    return JSONResponse(get_chat_settings())


async def api_chat_reset(request: Request) -> JSONResponse:
    return JSONResponse(_chat_session().reset())


async def api_chat_prompt(request: Request) -> JSONResponse:
    from rfauto.service import r3_services

    return JSONResponse({"ok": True, "prompt": r3_services.get_system_prompt()})


async def api_chat_stats(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "stats": _chat_session().stats})


async def api_fs_list(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import fs_list
    return JSONResponse(fs_list(request.query_params.get("path", "")))


async def api_recipes(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import list_recipes
    return JSONResponse(list_recipes())


async def api_hfss_import(request: Request) -> JSONResponse:
    """HFSS 工程导入（.aedt → 设计规格 + 配方草稿，2026-09-02 用户需求）。"""
    from rfauto.service.v3_services import hfss_import_recipe
    body: dict[str, Any] = await request.json()
    result = hfss_import_recipe(
        body.get("project", ""),
        body.get("design") or None,
        version=str(body.get("version", "2023.1")),
        out=body.get("out") or None,
    )
    return JSONResponse(result)


async def api_calibration_runs(request: Request) -> JSONResponse:
    """校准工作台：校准产物清单（阶段 3.2）。"""
    from rfauto.service.ui_service import calibration_runs
    return JSONResponse(calibration_runs())


async def api_calibration_view(request: Request) -> JSONResponse:
    """校准工作台：单次校准详情（gate/样本点/验证点/报告）。"""
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    result = ui_service.calibration_view(request.path_params["run_id"])
    if isinstance(result.get("gate"), dict):
        result["gate"] = annotate_contract("gate", result["gate"])
    return JSONResponse(result)


async def api_cross_fidelity(request: Request) -> JSONResponse:
    """跨保真对比：ρ/recall 随样本量与网格的演化（阶段 3.3）。"""
    from rfauto.service.ui_service import cross_fidelity_view
    return JSONResponse(cross_fidelity_view())


async def api_sparams(request: Request) -> JSONResponse:
    """S 参数交互视图：单 run 曲线序列，mode=db|deg（阶段 3.1）。"""
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    series = ui_service.sparams_series(
        request.path_params["run_id"],
        request.query_params.get("mode", "db"))
    return JSONResponse(annotate_contract("sparams_series", series))


async def api_cost_timeline(request: Request) -> JSONResponse:
    """成本时间线：run 级目标成本随时间 + 最新调参收敛（阶段 3.4）。"""
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    return JSONResponse(
        annotate_contract("cost_timeline", ui_service.cost_timeline()))


async def api_reports(request: Request) -> JSONResponse:
    """报告中心：runs/ 下人读报告清单（阶段 3.5）。"""
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    return JSONResponse(
        annotate_contract("reports_list", ui_service.list_reports()))


async def api_report_content(request: Request) -> JSONResponse:
    """报告中心：单份报告文本（路径白名单 runs/*.md）。"""
    from rfauto.service.ui_service import report_content
    return JSONResponse(report_content(
        request.query_params.get("path", "")))


async def api_run_fig(request: Request) -> JSONResponse | FileResponse:
    """报告中心图片白名单路由（项 2 裂图修复）：只允许
    runs/<run_id>/results/figs/ 下的 .png/.svg；穿越/越界/缺失一律 404，
    前端 onerror 显示"该 run 无此图"占位（不裂图）。"""
    from rfauto.service.ui_service import run_fig_file

    fig = run_fig_file(request.path_params["run_id"],
                       request.path_params["name"])
    if fig is None:
        return JSONResponse(
            {"ok": False,
             "errors": ["该 run 无此图（白名单：runs/<run_id>/results/figs/ "
                        "下的 .png/.svg）"]},
            status_code=404)
    return FileResponse(fig)


async def api_calculators(request: Request) -> JSONResponse:
    """微波工具箱：计算器清单（E4，参数自描述）。"""
    from rfauto.service.calculator_service import list_calculators
    return JSONResponse(list_calculators())


async def api_calculators_run(request: Request) -> JSONResponse:
    """微波工具箱：执行一个计算器（E4，数值只在确定性内核）。"""
    from rfauto.service.calculator_service import run_calculator
    body: dict[str, Any] = await request.json()
    return JSONResponse(
        run_calculator(body.get("name", ""), body.get("params") or {}))


async def api_sparams_external(request: Request) -> JSONResponse:
    """S 参数页：外部 Touchstone 导入（WP0.3/E8，只读）。"""
    from rfauto.service.ui_service import external_sparams
    body: dict[str, Any] = await request.json()
    return JSONResponse(external_sparams(
        body.get("path", ""), body.get("mode", "db")))


async def api_playground_runs(request: Request) -> JSONResponse:
    """代理 Playground：有校准产物的 run 清单（WP0.4/E3）。"""
    from rfauto.service.surrogate_playground import playground_runs
    return JSONResponse(playground_runs())


async def api_playground_predict(request: Request) -> JSONResponse:
    """代理 Playground：滑条参数 → 代理预测（WP0.4/E3，确定性内核）。"""
    from rfauto.service.surrogate_playground import playground_predict
    body: dict[str, Any] = await request.json()
    return JSONResponse(
        playground_predict(body.get("run_id", ""), body.get("params") or {}))


async def api_playground_explore(request: Request) -> JSONResponse:
    """代理 Playground 探索器：参数扫描切片后验曲线（DP-16 U3，确定性内核）。

    sweep={"axis": name, "n": N}（1D）或 {"axes": [a, b], "n": N}（2D 网格）；
    mean±std 只在代理有原生逐点 σ（smt 族）时透出。
    """
    from rfauto.service.surrogate_playground import explore
    body: dict[str, Any] = await request.json()
    return JSONResponse(explore(
        body.get("run_id", ""), body.get("params") or None,
        body.get("sweep") or None))


async def api_loop_boards(request: Request) -> JSONResponse:
    """执行看板清单（WP3.5 v1.2 增强②：自治环步骤可视）。"""
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    limit = int(request.query_params.get("limit", "20"))
    return JSONResponse(
        annotate_contract("loop_boards", ui_service.loop_boards(limit=limit)))


async def api_loop_board(request: Request) -> JSONResponse:
    """单个执行看板：当前步骤 + 里程碑验收 + 历史（GUI 观察侧）。"""
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    return JSONResponse(annotate_contract(
        "loop_board",
        ui_service.loop_board_view(request.path_params["board_id"])))


async def api_loop_control(request: Request) -> JSONResponse:
    """执行看板控制：暂停/继续/接管（环在步骤边界协作式响应）。"""
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    body: dict[str, Any] = await request.json()
    return JSONResponse(annotate_contract(
        "loop_control",
        ui_service.loop_board_control(
            body.get("board_id", ""), body.get("action", ""))))


async def api_farfield_runs(request: Request) -> JSONResponse:
    """远场极坐标页：含 nf2ff 产物的 run 清单（WP4.1，只读）。"""
    from rfauto.service.nf2ff_service import farfield_runs

    limit = int(request.query_params.get("limit", "50"))
    return JSONResponse(farfield_runs(limit=limit))


async def api_farfield_view(request: Request) -> JSONResponse:
    """远场极坐标页：单 run 方向图切面 + 增益/效率/SAR 指标（WP4.1）。"""
    from rfauto.service.nf2ff_service import farfield_view

    return JSONResponse(farfield_view(request.path_params["run_id"]))


async def api_field_runs(request: Request) -> JSONResponse:
    """场可视化页：含 openEMS DumpHDF5 场 dump 的 run 清单（G9，只读）。"""
    from rfauto.service.ui_service import field_runs

    limit = int(request.query_params.get("limit", "50"))
    return JSONResponse(field_runs(limit=limit))


async def api_field_view(request: Request) -> JSONResponse:
    """场可视化页：单 run 切片/等值面/远场 3D + D4 指标（G9）。

    query：dump=<文件名> engine=auto|pyvista|numpy levels=-3,-10,-20
           sx/sy/sz=<切片索引>（缺省中面）。数值解释全在 service/内核。
    """
    from rfauto.service.ui_service import field_view

    q = request.query_params
    levels = None
    if q.get("levels"):
        levels = tuple(float(v) for v in q["levels"].split(",") if v.strip())
    slice_index = {ax: int(q[f"s{ax}"]) for ax in ("x", "y", "z") if q.get(f"s{ax}")}
    return JSONResponse(field_view(
        request.path_params["run_id"],
        dump=q.get("dump") or None,
        engine=q.get("engine", "auto"),
        levels_db=levels,
        slice_index=slice_index or None,
    ))


async def api_smith(request: Request) -> JSONResponse:
    """S 参数页 Smith 圆图：单 run 各端口 S_ii 轨迹 + 网格几何（G9）。"""
    from rfauto.service.ui_service import smith_view

    return JSONResponse(smith_view(request.path_params["run_id"]))


async def api_smith_external(request: Request) -> JSONResponse:
    """S 参数页 Smith 圆图：外部 Touchstone 轨迹（只读）。"""
    from rfauto.service.ui_service import smith_external

    body: dict[str, Any] = await request.json()
    return JSONResponse(smith_external(body.get("path", "")))


async def api_pareto_runs(request: Request) -> JSONResponse:
    """优化洞察页 run 清单：front/trials/single 三档分组（项 3，只读）。"""
    from rfauto.service import ui_service

    limit = int(request.query_params.get("limit", "200"))
    return JSONResponse(ui_service.pareto_runs(limit=limit))


async def api_pareto_view(request: Request) -> JSONResponse:
    """优化洞察页：Pareto 前沿视图（E9，只读；pareto_front.json 直读或
    trials 现算约束 Pareto，双源在 service）。"""
    from rfauto.service.ui_service import pareto_view

    return JSONResponse(pareto_view(request.path_params["run_id"]))


async def api_feasibility(request: Request) -> JSONResponse:
    """优化洞察页：可行性热图（E10，只读；确定性分箱在 service）。"""
    from rfauto.service.ui_service import feasibility_heatmap

    q = request.query_params
    return JSONResponse(feasibility_heatmap(
        request.path_params["run_id"],
        q.get("x_param", ""), q.get("y_param", ""),
        int(q.get("grid_n", "12"))))


async def api_datasets(request: Request) -> JSONResponse:
    """数据集页清单（只读）：runs/datasets 注册表总览。"""
    from rfauto.service import ui_service
    return JSONResponse(ui_service.datasets_overview())


async def api_dataset_preview(request: Request) -> JSONResponse:
    """数据集页行级预览（只读）：抽样 N 行；model 为等值过滤便捷参。"""
    from rfauto.service import ui_service

    q = request.query_params
    return JSONResponse(ui_service.dataset_preview(
        request.path_params["name"],
        limit=int(q.get("limit", "20")),
        model=q.get("model") or None))


async def api_anchors(request: Request) -> JSONResponse:
    """标定锚页清单（只读）：注册表摘要 + stale 新鲜度合并视图。"""
    from rfauto.service import ui_service
    return JSONResponse(ui_service.anchors_overview(
        request.query_params.get("path") or None))


async def api_anchor_detail(request: Request) -> JSONResponse:
    """标定锚页单锚详情（只读）：raw 全量记录透传。"""
    from rfauto.service import ui_service
    return JSONResponse(ui_service.anchor_detail(
        request.path_params["anchor_id"],
        request.query_params.get("path") or None))


async def api_uq_samples(request: Request) -> JSONResponse:
    """UQ 页输入资产清单（只读）：runs/ 下校准样本集扫描。"""
    from rfauto.service import ui_service

    limit = int(request.query_params.get("limit", "200"))
    return JSONResponse(ui_service.uq_samples_list(limit=limit))


async def api_uq_yield(request: Request) -> JSONResponse:
    """UQ 页运行面（确定性内核）：代理蒙特卡洛良率 + 敏感性。"""
    from rfauto.service import ui_service

    body: dict[str, Any] = await request.json()
    return JSONResponse(ui_service.uq_yield_run(
        body.get("samples_path", ""),
        body.get("tolerances") or {},
        n=int(body.get("n", 10000)),
        seed=int(body.get("seed", 42)),
        kind=str(body.get("kind", "poly_ridge"))))


async def api_gallery(request: Request) -> JSONResponse:
    """PR-5 画廊交互化（只读）：模板卡 + 名义参数 + 闭式预览通道映射。

    前端滑块改值后直接 POST 既有 /api/calculators/run（闭式纯函数零 EM
    求解）；映射/量程解释全在 service/gallery_service（前端只渲染）。
    """
    from rfauto.service.gallery_service import gallery_cards
    return JSONResponse(gallery_cards())


async def api_campaign_dashboard(request: Request) -> JSONResponse:
    """PR-6 战役仪表盘（只读快照）：成本热图 + trial 表（虚拟列表数据面）。

    实时进度走既有 SSE 流 ``/api/runs/{run_id}/events/stream``（P-1，前端
    监听后回刷本端点）；本端点自身无流无副作用。
    """
    from rfauto.service.campaign_dashboard_service import campaign_dashboard

    q = request.query_params
    return JSONResponse(campaign_dashboard(
        request.path_params["run_id"],
        x_param=q.get("x_param") or None,
        y_param=q.get("y_param") or None,
        grid_n=int(q.get("grid_n", "12"))))


async def api_profile(request: Request) -> JSONResponse:
    """PR-8 剖析入口：GET=py-spy 可用性探测；POST=py-spy record 封装。

    火焰图/speedscope 产物落 runs/（缺省 runs/profile），随 /runs 静态
    挂载可直接人工打开；py-spy 缺装=ok 信封 available=False（GET）/
    error 信封带安装提示（POST），不阻塞 UI 其余面。
    """
    from rfauto.service.envelope import error_envelope
    from rfauto.service.profile_service import profile_run, profile_status

    if request.method == "GET":
        return JSONResponse(profile_status())
    try:
        body: dict[str, Any] = await request.json()
        raw_pid = body.get("pid")
        raw_cmd = body.get("cmd")
        return JSONResponse(profile_run(
            pid=int(raw_pid) if raw_pid not in (None, "") else None,
            cmd=[str(c) for c in raw_cmd] if raw_cmd else None,
            out_dir=str(body.get("out_dir") or "runs/profile"),
            duration_s=float(body.get("duration_s", 30.0)),
            rate_hz=int(body.get("rate_hz", 100)),
            fmt=str(body.get("fmt", "flamegraph")),
            out_name=str(body["out_name"]) if body.get("out_name") else None,
        ))
    except (TypeError, ValueError) as exc:
        return JSONResponse(error_envelope([f"剖析请求参数非法: {exc}"]))


#: PR-9 战役级 remote 附着面：mTLS 状态**如实登记不硬上**（条件项，v1 待
#: 实切；正式通道切换按远程资源说明口径执行，本面只登记状态零真连）。
_REMOTE_MTLS_NOTE = (
    "insecure 内网冒烟通道；mTLS（ANSYS_GRPC_CERTIFICATES）v1 待实切"
    "（条件项，按远程资源说明口径登记）")


def _campaign_remote_block(plan: dict[str, Any], machine: str) -> dict[str, Any]:
    """战役级 remote 附着块（PR-9 --remote 泛化的服务面拼装，只读零真连）。

    复用既有 ``remote_service.hfss_remote_session_config``（v1 调度面口径：
    只组装 settings 增量不写状态）；候选阶段=license_gated/adapter==hfss。
    任何异常都降级为 ok=False 块（best-effort，#105：不阻塞队列清单）。
    CLI 战役级 ``--remote`` 旗标接线仍是 v1 余项（cli 面另行登记）。
    """
    from rfauto.service.remote_service import hfss_remote_session_config

    candidates = [
        str(s.get("stage") or "") for s in plan.get("stages") or []
        if s.get("license_gated") or s.get("adapter") == "hfss"]
    try:
        cfg = hfss_remote_session_config(machine)
    except Exception as exc:  # 观测性 best-effort（#105）：宁缺勿阻塞
        return {"ok": False, "machine": machine,
                "stage_candidates": candidates,
                "errors": [f"remote 配置解析失败: {exc}"],
                "mtls": _REMOTE_MTLS_NOTE}
    return {"ok": True, "machine": machine,
            "remote_machine": cfg.get("remote"),
            "stage_candidates": candidates,
            "mtls": _REMOTE_MTLS_NOTE}


async def api_campaign_queue(request: Request) -> JSONResponse:
    """PR-9 调度队列页（只读）：战役计划队列 + G13 调度决策日志。

    数据全部出自既有服务函数（service/campaign_manager.list_campaign_plans
    + load_plan，JSON 进出），本 handler 只做清单级拼装，前端只渲染；
    损坏计划逐条如实降级（list_campaign_plans 已按 #105 口径跳坏文件）。
    ``machine=`` 显式查询时逐战役附 remote 附着面（``_campaign_remote_block``，
    mTLS 条件项按远程资源说明口径如实登记，零真连零上传）。
    """
    from rfauto.service.campaign_manager import list_campaign_plans, load_plan

    q = request.query_params
    root = q.get("root") or "runs"
    machine = q.get("machine") or None
    listing = list_campaign_plans(root)
    campaigns: list[dict[str, Any]] = []
    for item in listing.get("campaigns", []):
        plan = (load_plan(item["path"]).get("plan")) or {}
        sched = plan.get("scheduling") or {}
        entry = dict(item)
        entry["stages"] = [
            {"stage": str(s.get("stage") or ""),
             "status": str(s.get("status") or ""),
             "adapter": str(s.get("adapter") or ""),
             "license_gated": bool(s.get("license_gated"))}
            for s in plan.get("stages") or []]
        entry["scheduling"] = {
            "ok": bool(sched.get("ok")),
            "n_jobs": sched.get("n_jobs"),
            "predictor_used": bool(sched.get("predictor_used")),
            "budget_gate_used": bool(sched.get("budget_gate_used")),
            "decision_log": list(sched.get("decision_log") or []),
        }
        if machine is not None:
            entry["remote"] = _campaign_remote_block(plan, machine)
        campaigns.append(entry)
    return JSONResponse({
        "ok": True, "root": str(root), "machine": machine,
        "campaigns": campaigns, "n_campaigns": len(campaigns)})


async def index(request: Request) -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0:0:0:0:0:0:0:1"}


def _is_loopback(host: str) -> bool:
    return (host or "").strip().lower() in _LOOPBACK_HOSTS


def resolve_runs_mount(host: str, expose_runs: bool | None) -> bool:
    """三态裁决 runs/ 静态挂载：显式 True/False 优先；缺省=回环绑定开、非回环关。

    开源默认安全（R2-B-05）：runs/ 可能含未发布仿真数据，把 UI 绑到非回环地址
    （如 0.0.0.0）时不得未经确认整目录暴露，须显式 --expose-runs。
    """
    if expose_runs is not None:
        return expose_runs
    return _is_loopback(host)


def create_ui_app(include_runs_mount: bool = True) -> Starlette:
    """构建 UI 应用（测试与 rfauto ui 共用）。"""
    routes = [
        Route("/", index),
        Route("/api/runs", api_runs),
        # PR-4 双 run 对比：具体路径必须先于 /{run_id} 参数路由（顺序坑）
        Route("/api/runs/diff", api_runs_diff),
        Route("/api/runs/{run_id}", api_run_detail),
        # P-1 战役进度 SSE 桥（run_id 过滤；旧 3s 轮询端点保留为降级）
        Route("/api/runs/{run_id}/events/stream", api_run_events_stream),
        Route("/api/recipe", api_recipe),
        Route("/api/recipe", api_recipe_save, methods=["POST"]),
        Route("/api/model3d", api_model3d, methods=["GET", "POST"]),
        Route("/api/run", api_run, methods=["POST"]),
        Route("/api/tune/start", api_tune_start, methods=["POST"]),
        Route("/api/tune/status", api_tune_status),
        Route("/api/tune/trials", api_tune_trials),
        Route("/api/sandbox/drafts", api_sandbox_drafts),
        Route("/api/sandbox/diff", api_sandbox_diff),
        Route("/api/sandbox/promote", api_sandbox_promote, methods=["POST"]),
        Route("/api/solvers", api_solvers),
        Route("/api/solvers/viz", api_solvers_viz),
        Route("/api/inbox", api_inbox),
        Route("/api/inbox/approve", api_inbox_approve, methods=["POST"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Route("/api/chat/settings", api_chat_settings, methods=["GET", "POST"]),
        Route("/api/chat/reset", api_chat_reset, methods=["POST"]),
        Route("/api/chat/prompt", api_chat_prompt),
        Route("/api/chat/stats", api_chat_stats),
        Route("/api/fs/list", api_fs_list),
        Route("/api/recipes", api_recipes),
        Route("/api/hfss/import", api_hfss_import, methods=["POST"]),
        Route("/api/calibration", api_calibration_runs),
        Route("/api/calibration/{run_id}", api_calibration_view),
        Route("/api/cross_fidelity", api_cross_fidelity),
        Route("/api/sparams/external", api_sparams_external, methods=["POST"]),
        Route("/api/sparams/{run_id}", api_sparams),
        Route("/api/cost_timeline", api_cost_timeline),
        Route("/api/reports", api_reports),
        Route("/api/reports/content", api_report_content),
        Route("/api/runs/{run_id}/figs/{name:path}", api_run_fig),
        Route("/api/pareto_runs", api_pareto_runs),
        Route("/api/calculators", api_calculators),
        Route("/api/calculators/run", api_calculators_run, methods=["POST"]),
        Route("/api/playground/runs", api_playground_runs),
        Route("/api/playground/predict", api_playground_predict, methods=["POST"]),
        Route("/api/playground/explore", api_playground_explore, methods=["POST"]),
        Route("/api/loop/boards", api_loop_boards),
        Route("/api/loop/board/{board_id}", api_loop_board),
        Route("/api/loop/control", api_loop_control, methods=["POST"]),
        Route("/api/farfield", api_farfield_runs),
        Route("/api/farfield/{run_id}", api_farfield_view),
        Route("/api/field", api_field_runs),
        Route("/api/field/{run_id}", api_field_view),
        Route("/api/smith/external", api_smith_external, methods=["POST"]),
        Route("/api/smith/{run_id}", api_smith),
        Route("/api/runs/{run_id}/pareto", api_pareto_view),
        Route("/api/runs/{run_id}/feasibility", api_feasibility),
        Route("/api/datasets", api_datasets),
        Route("/api/datasets/{name}/preview", api_dataset_preview),
        Route("/api/anchors", api_anchors),
        Route("/api/anchors/{anchor_id}", api_anchor_detail),
        Route("/api/uq/samples", api_uq_samples),
        Route("/api/uq/yield", api_uq_yield, methods=["POST"]),
        Route("/api/gallery", api_gallery),
        Route("/api/runs/{run_id}/dashboard", api_campaign_dashboard),
        # PR-9 调度队列页（ge8b Wave B 席B3）：战役队列+G13 决策日志（只读）
        Route("/api/campaign_queue", api_campaign_queue),
        Route("/api/profile", api_profile, methods=["GET", "POST"]),
        Mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"),
    ]
    if include_runs_mount:
        # run 产物只读静态服务（人工核验直接看 PNG 曲线等中间产物）；
        # 非回环绑定默认关闭（R2-B-05 开源默认安全），显式 --expose-runs 才开
        routes.append(Mount("/runs", StaticFiles(directory="runs"), name="runs"))
    # D-04：CSP 头全响应附加（HTML 面为主；JSON/静态资源带同名头无害）
    return Starlette(routes=routes,
                     middleware=[Middleware(ContentSecurityPolicyMiddleware)])


def serve(
    host: str = "127.0.0.1", port: int = 8642, expose_runs: bool | None = None
) -> None:
    """阻塞启动 UI 服务器（rfauto ui 入口）。"""
    import sys

    import uvicorn

    include_runs_mount = resolve_runs_mount(host, expose_runs)
    if not _is_loopback(host):
        if include_runs_mount:
            print(
                "[rfauto ui] 警告：--expose-runs 已显式开启，runs/ 目录静态服务"
                "随非回环绑定对外暴露（内含未发布仿真数据）。",
                file=sys.stderr,
            )
        else:
            print(
                "[rfauto ui] /runs 静态服务已随非回环绑定默认关闭"
                "（--expose-runs 可显式开启）。",
                file=sys.stderr,
            )
    uvicorn.run(
        create_ui_app(include_runs_mount=include_runs_mount), host=host, port=port,
        log_level="warning",
    )
