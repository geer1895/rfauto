"""工具域路由（微波工具箱计算器/模板画廊/代理 Playground/剖析）——自 ui/server.py 逐函数搬家。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- GET       /api/calculators           api_calculators（计算器清单，参数自描述）
- POST      /api/calculators/run       api_calculators_run（执行计算器）
- GET       /api/gallery               api_gallery（模板卡+闭式预览通道映射）
- GET       /api/playground/runs       api_playground_runs（有校准产物的 run）
- POST      /api/playground/predict    api_playground_predict（滑条→代理预测）
- POST      /api/playground/explore    api_playground_explore（扫描切片后验曲线）
- GET/POST  /api/profile               api_profile（py-spy 剖析探测/执行）
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.ui.params import _json_body


async def api_calculators(request: Request) -> JSONResponse:
    """微波工具箱：计算器清单（E4，参数自描述）。"""
    from rfauto.service.calculator_service import list_calculators
    return JSONResponse(list_calculators())


async def api_calculators_run(request: Request) -> JSONResponse:
    """微波工具箱：执行一个计算器（E4，数值只在确定性内核）。"""
    from rfauto.service.calculator_service import run_calculator
    body: dict[str, Any] = await _json_body(request)
    return JSONResponse(
        run_calculator(body.get("name", ""), body.get("params") or {}))


async def api_gallery(request: Request) -> JSONResponse:
    """PR-5 画廊交互化（只读）：模板卡 + 名义参数 + 闭式预览通道映射。

    前端滑块改值后直接 POST 既有 /api/calculators/run（闭式纯函数零 EM
    求解）；映射/量程解释全在 service/gallery_service（前端只渲染）。
    """
    from rfauto.service.gallery_service import gallery_cards
    return JSONResponse(gallery_cards())


async def api_playground_runs(request: Request) -> JSONResponse:
    """代理 Playground：有校准产物的 run 清单（WP0.4/E3）。"""
    from rfauto.service.surrogate_playground import playground_runs
    return JSONResponse(playground_runs())


async def api_playground_predict(request: Request) -> JSONResponse:
    """代理 Playground：滑条参数 → 代理预测（WP0.4/E3，确定性内核）。"""
    from rfauto.service.surrogate_playground import playground_predict
    body: dict[str, Any] = await _json_body(request)
    return JSONResponse(
        playground_predict(body.get("run_id", ""), body.get("params") or {}))


async def api_playground_explore(request: Request) -> JSONResponse:
    """代理 Playground 探索器：参数扫描切片后验曲线（DP-16 U3，确定性内核）。

    sweep={"axis": name, "n": N}（1D）或 {"axes": [a, b], "n": N}（2D 网格）；
    mean±std 只在代理有原生逐点 σ（smt 族）时透出。
    """
    from rfauto.service.surrogate_playground import explore
    body: dict[str, Any] = await _json_body(request)
    return JSONResponse(explore(
        body.get("run_id", ""), body.get("params") or None,
        body.get("sweep") or None))


async def api_profile(request: Request) -> JSONResponse:
    """PR-8 剖析入口：GET=py-spy 可用性探测；POST=py-spy record 封装。

    火焰图/speedscope 产物落 runs/（缺省 runs/profile/），随 /runs 静态
    挂载可直接人工打开；py-spy 缺装=ok 信封 available=False（GET）/
    error 信封带安装提示（POST），不阻塞 UI 其余面。
    """
    from rfauto.service.envelope import error_envelope
    from rfauto.service.profile_service import profile_run, profile_status

    if request.method == "GET":
        return JSONResponse(profile_status())
    try:
        body: dict[str, Any] = await _json_body(request)
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
