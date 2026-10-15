"""优化洞察域路由（Pareto/可行性/成本时间线/执行看板）——自 ui/server.py 逐函数搬家。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- GET  /api/pareto_runs                api_pareto_runs（run 清单三档分组）
- GET  /api/runs/{run_id}/pareto       api_pareto_view（Pareto 前沿视图）
- GET  /api/runs/{run_id}/feasibility  api_feasibility（可行性热图）
- GET  /api/cost_timeline              api_cost_timeline（成本时间线）
- GET  /api/loop/boards                api_loop_boards（执行看板清单）
- GET  /api/loop/board/{board_id}      api_loop_board（单看板详情）
- POST /api/loop/control               api_loop_control（暂停/继续/接管）
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.ui.params import _int_param, _json_body


async def api_cost_timeline(request: Request) -> JSONResponse:
    """成本时间线：run 级目标成本随时间 + 最新调参收敛（阶段 3.4）。"""
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    return JSONResponse(
        annotate_contract("cost_timeline", ui_service.cost_timeline()))


async def api_loop_boards(request: Request) -> JSONResponse:
    """执行看板清单（WP3.5 v1.2 增强②：自治环步骤可视）。"""
    from rfauto.service import ui_service
    from rfauto.service.contracts import annotate_contract

    limit = _int_param(request.query_params.get("limit"), 20, "limit")
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

    body: dict[str, Any] = await _json_body(request)
    return JSONResponse(annotate_contract(
        "loop_control",
        ui_service.loop_board_control(
            body.get("board_id", ""), body.get("action", ""))))


async def api_pareto_runs(request: Request) -> JSONResponse:
    """优化洞察页 run 清单：front/trials/single 三档分组（项 3，只读）。"""
    from rfauto.service import ui_service

    limit = _int_param(request.query_params.get("limit"), 200, "limit")
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
        _int_param(q.get("grid_n"), 12, "grid_n")))
