"""工程导入域路由（HFSS .aedt → 设计规格 + 配方草稿）——自 ui/server.py 逐函数搬家。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- POST /api/hfss/import   api_hfss_import（同步 AEDT 调用下放工作线程）

EDB 快车道状态页（/api/edb_status，api_edb_status）本体在 ui/edb_app.py——
server.py 既有薄 re-export 保持引用路径不变（UX-B6 campaign_app 同款惯例）。
"""

from __future__ import annotations

from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.ui.params import _json_body


async def api_hfss_import(request: Request) -> JSONResponse:
    """HFSS 工程导入（.aedt → 设计规格 + 配方草稿，2026-09-02 用户需求）。"""
    from rfauto.service.v3_services import hfss_import_recipe
    body: dict[str, Any] = await _json_body(request)
    project = str(body.get("project") or "")
    # A8-D（架构批 抽查实证）：空路径此前直通 adapter——实测会真启动
    # AEDT 空工程（~30s+license 席位）并回 ok=True 空规格，误读为导入
    # 成功。路由层快速 400：单数 error 与本端点既有失败面同形（前端
    # pages.js 读 importSpec.error 渲染），不走 error_envelope 的 errors 列表。
    if not project.strip():
        return JSONResponse(
            {"ok": False,
             "error": "工程路径为空：请先提供 .aedt 工程文件路径"
                      "（浏览选择或手输绝对路径）"},
            status_code=400)
    # A6 P1-3：AEDT 启动+导入 ~30s+ 同步调用此前冻结整个事件循环（含
    # SSE 心跳）；空路径快速 400 守卫保持同步（不占线程池）。照
    # api_tune_start 下放范式改工作线程执行。
    result = await run_in_threadpool(
        hfss_import_recipe,
        project,
        body.get("design") or None,
        # A6-D（架构批 R6 F-3，2026-10-12）：缺省版本钉对齐仓库真机口径
        # "2025.1"（AGENTS 规则 0 勘误：AEDT 2025 R1/v251；同口径先例
        # adapters/edb_adapter.py _DEFAULT_AEDT_VERSION 与
        # configs/remote_machines.yaml hfss.version）——旧钉停留"已验证
        # 通道"旧口径，与 service 层另一缺省钉（v3_services 的受阻版本）
        # 双双失真。缺省钉只在请求未带 version 时生效（导入页下拉显式
        # 传值不受扰）；空串按未给处理（显式 or 归回缺省钉）。
        version=str(body.get("version") or "2025.1"),
        out=body.get("out") or None,
    )
    return JSONResponse(result)
