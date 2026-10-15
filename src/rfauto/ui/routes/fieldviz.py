"""场可视化域路由（远场极坐标页 + 场可视化页）——自 ui/server.py 逐函数搬家。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- GET /api/farfield           api_farfield_runs（含 nf2ff 产物的 run 清单）
- GET /api/farfield/{run_id}  api_farfield_view（方向图切面 + 增益/效率/SAR）
- GET /api/field              api_field_runs（含 DumpHDF5 场 dump 的 run 清单）
- GET /api/field/{run_id}     api_field_view（切片/等值面/远场 3D + D4 指标）
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.ui.params import ParamError, _int_param


async def api_farfield_runs(request: Request) -> JSONResponse:
    """远场极坐标页：含 nf2ff 产物的 run 清单（WP4.1，只读）。"""
    from rfauto.service.nf2ff_service import farfield_runs

    limit = _int_param(request.query_params.get("limit"), 50, "limit")
    return JSONResponse(farfield_runs(limit=limit))


async def api_farfield_view(request: Request) -> JSONResponse:
    """远场极坐标页：单 run 方向图切面 + 增益/效率/SAR 指标（WP4.1）。"""
    from rfauto.service.nf2ff_service import farfield_view

    return JSONResponse(farfield_view(request.path_params["run_id"]))


async def api_field_runs(request: Request) -> JSONResponse:
    """场可视化页：含 openEMS DumpHDF5 场 dump 的 run 清单（G9，只读）。"""
    from rfauto.service.ui_service import field_runs

    limit = _int_param(request.query_params.get("limit"), 50, "limit")
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
        try:
            levels = tuple(float(v) for v in q["levels"].split(",") if v.strip())
        except ValueError:
            raise ParamError(
                "levels 须为逗号分隔的 dB 数值"
                "（示例：levels=-3,-10,-20）") from None
    slice_index = {}
    for ax in ("x", "y", "z"):
        if q.get(f"s{ax}"):
            slice_index[ax] = _int_param(q.get(f"s{ax}"), 0, f"s{ax}")
    return JSONResponse(field_view(
        request.path_params["run_id"],
        dump=q.get("dump") or None,
        engine=q.get("engine", "auto"),
        levels_db=levels,
        slice_index=slice_index or None,
    ))
