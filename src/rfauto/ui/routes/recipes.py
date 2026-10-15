"""配方/建模域路由（配方视图/保存/清单、模型 3D 预览、文件浏览）——自 ui/server.py 逐函数搬家。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- GET       /api/recipe     api_recipe（配方表单化视图，只读）
- POST      /api/recipe     api_recipe_save（保存/新建，写面在 service 守卫）
- GET       /api/recipes    api_recipes（配方清单）
- GET/POST  /api/model3d    api_model3d（参数 → 3D 预览 / 配方 → 3D 预览）
- GET       /api/fs/list    api_fs_list（文件浏览，fs_read_fence 围栏在 service）
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.ui.params import _json_body


async def api_recipe(request: Request) -> JSONResponse:
    """配方表单化视图（只读）。

    W8-B P2-1（2026-10-12）：空 path 时 Path("") 归一为 cwd 目录——
    recipe_view 的 fs_read_fence/exists 检查对目录均放行，``open('.')``
    在 Windows 抛 PermissionError（POSIX IsADirectoryError）未捕获直冒
    500。路由层兜底：空路径 400；目录/权限类 OSError（两者同为 OSError
    子类）包 400 error 信封（信封单源构造器，AU-2），语义化读失败不再
    打 500。"""
    from rfauto.service import ui_service
    from rfauto.service.envelope import error_envelope

    path = request.query_params.get("path", "")
    if not path.strip():
        return JSONResponse(
            error_envelope(["路径为空：请先提供配方文件路径（recipes/ 下 .yaml）"]),
            status_code=400)
    try:
        return JSONResponse(ui_service.recipe_view(path))
    except OSError as exc:
        return JSONResponse(
            error_envelope([f"配方路径不可读（目录或权限受限）: {exc}"]),
            status_code=400)


async def api_recipe_save(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    body: dict[str, Any] = await _json_body(request)
    if body.get("create") is not None:
        # 新建配方（工程导入向导用）：YAML 序列化/落盘全在 service（#90/#92）
        return JSONResponse(
            ui_service.recipe_create(body.get("path", ""), body["create"]))
    result = ui_service.recipe_save(body.get("path", ""), body.get("updates", {}))
    return JSONResponse(result)


async def api_model3d(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    if request.method == "POST":
        body: dict[str, Any] = await _json_body(request)
        # 几何求解在 service/确定性内核；UI 层只传模板名+参数（#90/#92）
        return JSONResponse(ui_service.model3d_for_params(
            body.get("template", "wilkinson"),
            body.get("params", {}) or {},
            body.get("substrate"),
        ))
    return JSONResponse(
        ui_service.model3d_for_recipe(request.query_params.get("path", ""))
    )


async def api_fs_list(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import fs_list
    return JSONResponse(fs_list(request.query_params.get("path", "")))


async def api_recipes(request: Request) -> JSONResponse:
    from rfauto.service.r3_services import list_recipes
    return JSONResponse(list_recipes())
