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

    aurora_i W2-S3（采纳 #2）：逐战役附 queue-daemon 阻塞账透出
    （``queue_block``：人读阻塞原因 code/detail/since/waited_s/text）——
    数据源=campaign_queue 状态档（默认路径），读侧合并 best-effort
    （状态档缺席/损坏=守护未在跑，清单照常返回零阻塞账）；顶层
    ``queue_daemon`` 摘要块如实登记守护账状态。

    aurora_i W3-S3（采纳 #1）：逐战役附对冲告警账透出（``queue_hedge``：
    在途项"卡死但未死"停滞疑似 code/since/stalled_s/attempts/text，人读
    同源 :func:`queue_hedge_index`）——对冲监测缺省关闭（env
    RFAUTO_QUEUE_HEDGE_STALL_S），关=无此字段零变化。
    """
    from rfauto.service.campaign_manager import list_campaign_plans, load_plan

    q = request.query_params
    root = q.get("root") or "runs"
    machine = q.get("machine") or None
    listing = list_campaign_plans(root)

    def _blocks_and_summary() -> tuple[dict[str, Any], dict[str, Any],
                                       dict[str, Any]]:
        """队列状态档 → ({item_id: 阻塞块}, {item_id: 对冲账}, 守护摘要)；
        缺席/损坏=空账。"""
        from rfauto.service.campaign_queue_daemon import (
            default_queue_state_path,
            load_queue_state,
            queue_blocks_index,
            queue_hedge_index,
            queue_status_view,
        )

        state = load_queue_state(default_queue_state_path())
        loaded = bool(state.get("items")) or bool(state.get("last_tick_at"))
        return (queue_blocks_index(state), queue_hedge_index(state),
                {"loaded": loaded, **queue_status_view(state)})

    try:
        blocks, hedges, daemon_summary = _blocks_and_summary()
    except Exception:  # 观测面 best-effort（#105）：宁缺勿阻塞清单
        blocks, hedges, daemon_summary = {}, {}, {"loaded": False}

    from rfauto.service.campaign_queue_daemon import item_id_of

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
        blk = blocks.get(item_id_of(item.get("path") or ""))
        if blk is not None:
            entry["queue_block"] = blk
        hq = hedges.get(item_id_of(item.get("path") or ""))
        if hq is not None:
            entry["queue_hedge"] = hq
        if machine is not None:
            entry["remote"] = _campaign_remote_block(plan, machine)
        campaigns.append(entry)
    return JSONResponse({
        "ok": True, "root": str(root), "machine": machine,
        "queue_daemon": daemon_summary,
        "campaigns": campaigns, "n_campaigns": len(campaigns)})


async def api_remote_resources(request: Request) -> JSONResponse:
    """W2-S4 远程机器面板（只读）：resources_view + 在途战役占用面。

    数据全部出自 ``remote_scheduler_service.resources_panel_view``（JSON
    进出，本 handler 薄壳直渲染；规则 4）。返回 ``resources``（本机互斥态
    + 登记机器资源面 + 资源日历 + ``recommend`` 只读选机推荐块 +
    ``remote.probed_at`` 探测时间戳）与 ``occupancy``（单飞在途战役计数 +
    占用徽章行，max_parallel 钉 1 如实展示）；未知机器名=error 信封（ok=
    False + errors），探测降级不翻 ok（#105）。
    """
    from starlette.concurrency import run_in_threadpool

    from rfauto.service.remote_scheduler_service import resources_panel_view

    machine = request.query_params.get("machine") or None
    # 同步探测链（TCP 3s×N+SSH 10s+命令超时）下沉线程池——半死机器最坏
    # 1-2 分钟阻塞不能停摆整个 UI 事件循环（W4-R3 P2，routes/agent 先例）
    return JSONResponse(await run_in_threadpool(
        resources_panel_view, machine=machine))
