"""调参域路由（后台线程启动/状态查询/trials 清单）——自 ui/server.py 逐函数搬家。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- POST /api/tune/start   api_tune_start（后台线程，任务槽=_TUNE_STATE）
- GET  /api/tune/status  api_tune_status（状态查询，ok 信封）
- GET  /api/tune/trials  api_tune_trials（历史 trials，读 service）
- GET  /api/tune/events/stream  api_tune_events_stream（UI-R3 统一事件流，
  端点在 routes/events.py；本模块是 tune 域的**发布源**——状态转移经
  _publish_tune_event 进统一总线，观测面 best-effort #105）

U4 生产写入方（架构批 W2-S7）：调参完成态经 _write_tune_terminal_event
写一条 run_completed/run_failed 事件到该 run 的 events.jsonl（有 run_id
才写）——runs 镜像 SSE 流自此有真实生产事件可读（此前只读不写）。

_TUNE_STATE 是进程内任务槽（单任务语义）：测试经
``monkeypatch.setitem(server_mod._TUNE_STATE, ...)`` 就地置位（同一 dict
对象经 server.py 薄 re-export 透传，is 同一性）。``run_seq`` 是进程内单调
启动计数——状态转移/试次探针去重键的唯一性成分（UI-R9 P1-B：秒级
started_at 曾令同秒"启动→即时失败→重试"的第二次转移被去重窗吞）。
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.ui.params import _int_param, _json_body

# ── 调参（后台线程 + 状态查询，UI 不阻塞）──────────────────────────────
_TUNE_STATE: dict[str, Any] = {"running": False, "log": [], "result": None,
                               "started_at": None, "error": None,
                               "run_seq": 0}


def _publish_tune_event(kind: str, payload: dict[str, Any],
                        dedupe_key: str | None = None) -> None:
    """tune 域事件发布（统一总线，UI-R3）；观测面 best-effort（#105：
    推送故障吞掉不抛——调参主路径零感知，业务逻辑一行未改）。"""
    try:
        from rfauto.ui.routes.event_bus import try_publish

        try_publish(kind, "tune", payload, dedupe_key=dedupe_key)
    except Exception:
        pass


def _write_tune_terminal_event(result: Any) -> None:
    """U4 SSE 生产写入方：tune 终态事件落 runs/<run_id>/events.jsonl。

    此前生产侧对 events.jsonl 零写入（core EventBus set_jsonl_sink 无生产
    调用方，W0_recon §1.3 U4 定谳）——runs 镜像 SSE 流恒空。本接线在调参
    完成态写一条 run_completed/run_failed 终态事件：读侧（read_run_events
    →SSE runs 镜像）见到 terminal 事件即推末帧并以 end 帧收束——「写入→
    SSE 端点可读」端到端自此真实发生。有 run_id 才写（结果信封未带 run_id
    如 multi/旧形态——如实零写入，不猜目录）；观测面 best-effort（#105）：
    任何异常吞掉不抛，调参主路径零感知。
    """
    try:
        if not isinstance(result, dict):
            return
        rid = str(result.get("run_id") or "").strip()
        if not rid:
            return
        from rfauto.service.ui_service import append_run_event

        ok = bool(result.get("ok"))
        append_run_event(
            rid, "run_completed" if ok else "run_failed",
            message="调参完成" if ok else "调参失败",
            data={"ok": ok,
                  "best_cost": result.get("best_cost"),
                  "trials_completed": result.get("trials_completed")})
    except Exception:
        pass


def _tune_trial_probe(study: Any, trial: Any) -> None:
    """逐 trial 完成探针（service start_tune 既有 ``on_trial`` 挂点 SN-9，
    服务层零改动；多目标 start_tune_multi 无此挂点——该模式 trial 级推送
    不支持，状态转移仍推，如实登记不假称）。"""
    # UI-R9 P1-B：键用 run_seq（跨 run 单调唯一）不用秒级 started_at——
    # 同秒两个 run 的同号 trial 曾撞同一去重键（number 只在单 run 内单调）。
    run_seq = _TUNE_STATE.get("run_seq")
    _publish_tune_event(
        "trial_new",
        {"study": str(getattr(study, "study_name", "") or ""),
         "number": getattr(trial, "number", None),
         "value": getattr(trial, "value", None),
         "state": str(getattr(trial, "state", ""))},
        dedupe_key=f"trial:{run_seq}:{getattr(trial, 'number', None)}")


async def api_tune_start(request: Request) -> JSONResponse:
    import threading
    from datetime import datetime

    from rfauto.service.api import start_tune, start_tune_multi

    if _TUNE_STATE["running"]:
        # 单数 error 遗留族（envelope 契约 §3：按域升版才统一，前端读 .error）
        return JSONResponse({"ok": False, "error": "已有调参任务在运行"})
    # W6-P3-6 TOCTOU 收口（架构批 W1-S4）：任务槽置位提前到任何 await
    # 之前——旧序（检查→await body→置位）留并发窗口，双 POST 可双双通过
    # 检查各自起后台线程。置位后 body/参数解析失败必须释放槽（A6 P0-2
    # "坏参数不占任务槽"行为保持；ParamError 由既有 400 信封面接手）。
    _TUNE_STATE["running"] = True
    try:
        body: dict[str, Any] = await _json_body(request)
        # A6 P0-2 同族收编（review_aurora_next 审查）：n_gen/pop_size/max_trials
        # 此前 int() 在后台线程内裸解析（坏值=任务槽已占+error 态假启动）——
        # 提前到路由层 _int_param 守卫，坏参数 400 信封、不占任务槽。
        n_gen = _int_param(body.get("n_gen"), 20, "n_gen")
        pop_size = _int_param(body.get("pop_size"), 12, "pop_size")
        max_trials = _int_param(body.get("max_trials"), 30, "max_trials")
    except Exception:
        _TUNE_STATE["running"] = False
        raise

    def _run() -> None:
        try:
            if body.get("multi"):
                result = start_tune_multi(
                    body.get("path", ""), adapter_name=body.get("adapter", "fake"),
                    n_gen=n_gen, pop_size=pop_size)
            else:
                # on_trial：UI-R3 逐 trial 探针挂既有服务扩展点（None 缺省
                # 行为不变；回调自身 best-effort，见 _tune_trial_probe）
                result = start_tune(
                    body.get("path", ""), adapter_name=body.get("adapter", "fake"),
                    max_trials=max_trials,
                    sampler=body.get("sampler", "tpe"),
                    on_trial=_tune_trial_probe)
            _TUNE_STATE["result"] = result
            _write_tune_terminal_event(result)  # U4：终态事件落 events.jsonl（生产写入方，best-effort）
            _publish_tune_event(
                "tune_completed",
                {"started_at": _TUNE_STATE["started_at"],
                 "ok": bool(result.get("ok")) if isinstance(result, dict) else True,
                 "multi": bool(body.get("multi"))},
                # UI-R9 P1-B：去重键唯一性由 run_seq 承担（进程内单调启动
                # 计数）——同秒"启动→即时失败→重试"两次转移都出帧。
                dedupe_key=f"tune:{run_seq}:completed")
        except Exception as exc:  # 线程内异常落状态，不让 UI 悬死
            _TUNE_STATE["error"] = str(exc)
            _publish_tune_event(
                "tune_failed",
                {"started_at": _TUNE_STATE["started_at"], "error": str(exc)},
                dedupe_key=f"tune:{run_seq}:failed")
        finally:
            _TUNE_STATE["running"] = False

    # run_seq 先于任务槽置位递增（UI-R9 P1-B，见 _run 内键注释）；闭包
    # 捕获本次计数值，后台线程读面与任务槽解耦。
    run_seq = int(_TUNE_STATE.get("run_seq") or 0) + 1
    _TUNE_STATE["run_seq"] = run_seq
    _TUNE_STATE.update({"running": True, "log": [], "result": None,
                        "error": None, "started_at": datetime.now().isoformat(timespec="seconds")})
    # UI-R3：状态转移（启动）进统一事件流——观测面 best-effort，先后序在
    # 任务槽置位之后（订阅方读 /api/tune/status 不会早于本端点可见）。
    _publish_tune_event(
        "tune_started",
        {"started_at": _TUNE_STATE["started_at"],
         "path": body.get("path", ""), "adapter": body.get("adapter", "fake"),
         "multi": bool(body.get("multi"))},
        dedupe_key=f"tune:{run_seq}:started")
    threading.Thread(target=_run, daemon=True).start()
    # A8-D 信封收编：裸 dict → ok_envelope 单源（键集不变）
    from rfauto.service.envelope import ok_envelope

    return JSONResponse(ok_envelope(started=True))


async def api_tune_status(request: Request) -> JSONResponse:
    # A8-D 补缺失面：本查询恒成立，补 ok=True 成功信封（查询语义）；
    # running/result/error/started_at 四键原样保留（前端按名读取，error
    # 为调参自身错误的历史单数键，不属信封失败面）。
    from rfauto.service.envelope import ok_envelope

    state = {k: _TUNE_STATE[k] for k in
             ("running", "result", "error", "started_at")}
    return JSONResponse(ok_envelope(**state))


async def api_tune_trials(request: Request) -> JSONResponse:
    from rfauto.service import ui_service

    run_id = request.query_params.get("run_id") or None
    return JSONResponse(ui_service.tune_trials(run_id))
