"""campaign UI 面（UX-B6 自 ui/server.py 机械拆分，2026-10-08；函数体逐字节未动）。

战役仪表盘（PR-6 ``api_campaign_dashboard``）+ 调度队列页/remote 附着块
（PR-9 ``api_campaign_queue``/``_campaign_remote_block``）三 handler 独立
成模块；server.py 以 ``from rfauto.ui.campaign_app import api_campaign_*``
薄壳 re-export，路由表注册行零改动（既有消费方零破坏）。
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse


async def api_campaign_dashboard(request: Request) -> JSONResponse:
    """PR-6 战役仪表盘（只读快照）：成本热图 + trial 表（虚拟列表数据面）。

    实时进度走既有 SSE 流 ``/api/runs/{run_id}/events/stream``（P-1，前端
    监听后回刷本端点）；本端点自身无流无副作用。
    """
    from rfauto.service.campaign_dashboard_service import campaign_dashboard

    # A6 P0-2（review_aurora_next 审查，2026-10-13）：grid_n 此前 int() 裸解析，
    # ``?grid_n=abc`` 抛 ValueError → 500 纯文本（前端 cp-n 是自由文本 input，
    # 手滑非数字即触发）。收编 A8-D 守卫单源（rfauto.ui.params，经 server.py
    # re-export 同一 exception_handlers）→ 400 error 信封。
    from rfauto.ui.params import _int_param

    q = request.query_params
    return JSONResponse(campaign_dashboard(
        request.path_params["run_id"],
        x_param=q.get("x_param") or None,
        y_param=q.get("y_param") or None,
        grid_n=_int_param(q.get("grid_n"), 12, "grid_n")))


#: PR-9 战役级 remote 附着面：mTLS 状态**如实登记不硬上**（条件项，v1 待
#: 实切；正式通道切换按服务器接入说明口径执行，本面只登记状态零真连）。
_REMOTE_MTLS_NOTE = (
    "insecure 内网冒烟通道；mTLS（ANSYS_GRPC_CERTIFICATES）v1 待实切"
    "（条件项，按服务器接入说明口径登记）")


def _campaign_remote_block(plan: dict[str, Any], machine: str) -> dict[str, Any]:
    """战役级 remote 附着块（PR-9 --remote 泛化的服务面拼装，只读零真连）。

    复用既有 ``remote_service.hfss_remote_session_config``（v1 调度面口径：
    只组装 settings 增量不写状态）；候选阶段=license_gated/adapter==hfss。
    任何异常都降级为 ok=False 块（best-effort，#105：不阻塞队列清单）。
    CLI 战役级 ``--remote`` 旗标接线仍是 v1 余项（cli 面另行登记）。
    """
    from rfauto.service.remote_service import hfss_remote_session_config

    candidates = [
        str(s.get("stage") or "") for s in plan.get("stages") or []
        if s.get("license_gated") or s.get("adapter") == "hfss"]
    try:
        cfg = hfss_remote_session_config(machine)
    except Exception as exc:  # 观测性 best-effort（#105）：宁缺勿阻塞
        return {"ok": False, "machine": machine,
                "stage_candidates": candidates,
                "errors": [f"remote 配置解析失败: {exc}"],
                "mtls": _REMOTE_MTLS_NOTE}
    return {"ok": True, "machine": machine,
            "remote_machine": cfg.get("remote"),
            "stage_candidates": candidates,
            "mtls": _REMOTE_MTLS_NOTE}


async def api_campaign_queue(request: Request) -> JSONResponse:
    """PR-9 调度队列页（只读）：战役计划队列 + G13 调度决策日志。

    数据全部出自既有服务函数（service/campaign_manager.list_campaign_plans
    + load_plan，JSON 进出），本 handler 只做清单级拼装，前端只渲染；
    损坏计划逐条如实降级（list_campaign_plans 已按 #105 口径跳坏文件）。
    ``machine=`` 显式查询时逐战役附 remote 附着面（``_campaign_remote_block``，
    mTLS 条件项按服务器接入说明口径如实登记，零真连零上传）。
    """
    from rfauto.service.campaign_manager import list_campaign_plans, load_plan

    q = request.query_params
    root = q.get("root") or "runs"
    machine = q.get("machine") or None
    listing = list_campaign_plans(root)
    campaigns: list[dict[str, Any]] = []
    for item in listing.get("campaigns", []):
        plan = (load_plan(item["path"]).get("plan")) or {}
        sched = plan.get("scheduling") or {}
        entry = dict(item)
        entry["stages"] = [
            {"stage": str(s.get("stage") or ""),
             "status": str(s.get("status") or ""),
             "adapter": str(s.get("adapter") or ""),
             "license_gated": bool(s.get("license_gated"))}
            for s in plan.get("stages") or []]
        entry["scheduling"] = {
            "ok": bool(sched.get("ok")),
            "n_jobs": sched.get("n_jobs"),
            "predictor_used": bool(sched.get("predictor_used")),
            "budget_gate_used": bool(sched.get("budget_gate_used")),
            "decision_log": list(sched.get("decision_log") or []),
        }
        if machine is not None:
            entry["remote"] = _campaign_remote_block(plan, machine)
        campaigns.append(entry)
    return JSONResponse({
        "ok": True, "root": str(root), "machine": machine,
        "campaigns": campaigns, "n_campaigns": len(campaigns)})
