"""rfauto 人工核验 UI（本地 web 服务，starlette + uvicorn）。

设计红线：路由是薄壳，全部业务在 service/ui_service.py（JSON 进出）；
只读 endpoints 无副作用，POST /api/run 复用 service.run_once（单写锁在那层）。
启动：rfauto ui（默认 127.0.0.1:8642，不对外网监听）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

_STATIC_DIR = Path(__file__).parent / "static"


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

    return JSONResponse({"ok": True, "prompt": r3_services._SYSTEM_PROMPT})


async def api_chat_stats(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "stats": _chat_session().stats})


async def api_fs_list(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import fs_list
    return JSONResponse(fs_list(request.query_params.get("path", "")))


async def api_recipes(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import list_recipes
    return JSONResponse(list_recipes())


async def api_hfss_import(request: Request) -> JSONResponse:
    """HFSS 工程导入（.aedt → 设计规格 + 配方草稿）。"""
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


async def api_loop_boards(request: Request) -> JSONResponse:
    """执行看板清单（WP3.5 v1.2 增强：自治环步骤可视）。"""
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


async def index(request: Request) -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0:0:0:0:0:0:0:1"}


def _is_loopback(host: str) -> bool:
    return (host or "").strip().lower() in _LOOPBACK_HOSTS


def resolve_runs_mount(host: str, expose_runs: bool | None) -> bool:
    """三态裁决 runs/ 静态挂载：显式 True/False 优先；缺省=回环绑定开、非回环关。

    开源默认安全：runs/ 可能含未发布仿真数据，把 UI 绑到非回环地址
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
        Route("/api/runs/{run_id}", api_run_detail),
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
        Mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"),
    ]
    if include_runs_mount:
        # run 产物只读静态服务（人工核验直接看 PNG 曲线等中间产物）；
        # 非回环绑定默认关闭（R2-B-05 开源默认安全），显式 --expose-runs 才开
        routes.append(Mount("/runs", StaticFiles(directory="runs"), name="runs"))
    return Starlette(routes=routes)


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
