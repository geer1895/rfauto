"""测量/报告域路由（校准工作台/跨保真/S 参数/Smith 圆图/报告中心）——自 ui/server.py 逐函数搬家。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- GET       /api/calibration          api_calibration_runs（校准产物清单）
- GET       /api/calibration/{run_id} api_calibration_view（单次校准详情）
- GET       /api/cross_fidelity       api_cross_fidelity（跨保真对比）
- GET       /api/sparams/{run_id}     api_sparams（S 参数曲线序列）
- POST      /api/sparams/external     api_sparams_external（外部 Touchstone）
- GET       /api/smith/{run_id}       api_smith（Smith 圆图轨迹）
- POST      /api/smith/external       api_smith_external（外部 Touchstone）
- GET       /api/reports              api_reports（报告清单）
- GET       /api/reports/content      api_report_content（单份报告文本）
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.ui.params import _json_body


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


async def api_sparams_external(request: Request) -> JSONResponse:
    """S 参数页：外部 Touchstone 导入（WP0.3/E8，只读）。"""
    from rfauto.service.ui_service import external_sparams
    body: dict[str, Any] = await _json_body(request)
    return JSONResponse(external_sparams(
        body.get("path", ""), body.get("mode", "db")))


async def api_smith(request: Request) -> JSONResponse:
    """S 参数页 Smith 圆图：单 run 各端口 S_ii 轨迹 + 网格几何（G9）。"""
    from rfauto.service.ui_service import smith_view

    return JSONResponse(smith_view(request.path_params["run_id"]))


async def api_smith_external(request: Request) -> JSONResponse:
    """S 参数页 Smith 圆图：外部 Touchstone 轨迹（只读）。"""
    from rfauto.service.ui_service import smith_external

    body: dict[str, Any] = await _json_body(request)
    return JSONResponse(smith_external(body.get("path", "")))
