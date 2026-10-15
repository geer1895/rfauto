"""数据资产域路由（数据集页/标定锚页/UQ 页）——自 ui/server.py 逐函数搬家。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- GET  /api/datasets                  api_datasets（数据集注册表总览）
- GET  /api/datasets/{name}/preview   api_dataset_preview（行级抽样预览）
- GET  /api/anchors                   api_anchors（标定锚注册表摘要）
- GET  /api/anchors/{anchor_id}       api_anchor_detail（单锚 raw 记录）
- GET  /api/uq/samples                api_uq_samples（校准样本集清单）
- POST /api/uq/yield                  api_uq_yield（代理蒙特卡洛良率+敏感性）
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.ui.params import _int_param, _json_body


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
        limit=_int_param(q.get("limit"), 20, "limit"),
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

    limit = _int_param(request.query_params.get("limit"), 200, "limit")
    return JSONResponse(ui_service.uq_samples_list(limit=limit))


async def api_uq_yield(request: Request) -> JSONResponse:
    """UQ 页运行面（确定性内核）：代理蒙特卡洛良率 + 敏感性。"""
    from rfauto.service import ui_service

    body: dict[str, Any] = await _json_body(request)
    return JSONResponse(ui_service.uq_yield_run(
        body.get("samples_path", ""),
        body.get("tolerances") or {},
        n=_int_param(body.get("n"), 10000, "n"),
        seed=_int_param(body.get("seed"), 42, "seed"),
        kind=str(body.get("kind", "poly_ridge"))))
