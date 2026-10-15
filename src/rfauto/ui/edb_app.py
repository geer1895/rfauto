"""EDB 快车道状态页（UI 消费面，照 campaign_app 先例独立成模块）。

handler 自 ui/server.py 拆出（同 UX-B6 W1 形态）：server.py 以
``from rfauto.ui.edb_app import api_edb_status`` 薄壳 re-export，路由表
注册行最小追加（既有消费方零破坏）。只读零副作用，业务全在
service/edb_lane_service.edb_status（JSON 进出，零求解零导入）。
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse


async def api_edb_status(request: Request) -> JSONResponse:
    """EDB 快车道状态页（只读）：产物根目录资产清单 + 模板能力面。

    数据全部出自既有服务函数（service/edb_lane_service.edb_status：
    .aedb 工程/建库存证/批解日志/批后 Touchstone/发射存证按 stem 归组，
    另带五族模板支持清单），本 handler 只做查询参数薄壳，前端只渲染；
    ``root=`` 缺省 runs/edb_lane（与 CLI ``edb status --root`` 同口径）。
    目录不存在/不可读等服务侧信封（ok+空表 / ok=False+errors）原样透传。
    """
    from rfauto.service.edb_lane_service import edb_status

    root = request.query_params.get("root") or "runs/edb_lane"
    return JSONResponse(edb_status(root))
