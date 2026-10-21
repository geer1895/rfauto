"""rest_api.system —— 系统健康端点（W3-S2 T2 拆分，逐字节搬迁）。"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from .common import _ok

# ---------------------------------------------------------------------------
# 端点（薄壳：调 service → 映射状态码）
# ---------------------------------------------------------------------------

async def api_health(request: Request) -> JSONResponse:
    """系统健康：包版本 + 已注册模型（确定性，无外部探测/网络）。"""
    from rfauto import __version__  # lazy: run-path（执行面按需取用）
    from rfauto.service.api import list_models  # lazy: run-path（执行面按需取用）

    models = list_models().get("models") or []
    return _ok({
        "status": "ok",
        "version": __version__,
        "n_models": len(models),
        "models": list(models),
    })
