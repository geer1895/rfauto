"""统一实时事件流端点（架构批 UI-R3 席）——tune/campaign 接入 SSE。

端点清单（route 表装配在 ui/server.py create_ui_app）：
- GET /api/events/stream                    api_events_stream（统一流，全域）
- GET /api/tune/events/stream               api_tune_events_stream（tune 域）
- GET /api/campaign_queue/events/stream     api_campaign_queue_events_stream（campaign 域）

帧形态（``event_bus.sse_frame`` 单源）：``event=<kind>`` + ``id=<seq>`` +
``data=<统一信封 JSON>``（信封 = {seq, ts, kind, domain, payload}，见
event_bus 模块 docstring）。控制帧三枚（**省略 id 行**——EventSource 语义
下不清客户端 Last-Event-ID 游标，UI-R9 P1-A；续传起点走 hello payload
的 cursor 键）：
- ``hello``（连接首帧）：{cursor, domains, run_id}——当前 head seq 引导；
- ``resync``：游标落后环形窗口（背压截断）→ 客户端整页刷新（对齐既有
  SSE 消费纪律：刷新动作幂等）；
- ``end``（仅 runs 镜像单域模式）：与既有 runs 桥 end 帧同语义
  （terminal=true / exists=false）——EventSource 自然收束。

域来源（谁把事件发进总线，event_bus 模块 docstring 有全景）：
- tune：routes/tune.py 发布钩子（tune_started/tune_completed/tune_failed
  + trial_new 探针）——本模块**无 tune tick**（状态源即路由任务槽，
  双源轮询只会造出第二条语义）；
- campaign：本模块 tick 检测器——流存活期周期性扫
  ``list_campaign_plans(root)`` + 逐计划 stage 状态，差分前快照后经
  总线发布 campaign_new / stage_changed / launch_completed（去重窗保证
  多客户端并发连接时恰好一次）；扫描走**共享 ticker 单飞**
  （``shared_campaign_snapshot``：同 root 在 TTL 窗口内至多扫一次盘，
  N 连接复用同一快照代际——连接数与扫描频次解耦，UI-R10 修 uir8
  审查 P2 的"每连接每秒各扫一遍"面）；
- runs：``?run_id=`` 镜像模式——``ui_service.read_run_events`` 偏移增量
  逐事件经总线发布（kind=旧 event_type、payload=旧事件 dict 原样，
  向后兼容钉在 test_ui_event_stream）；另有 routes/runs.py 桥逐事件懒
  镜像（桥在流时才馈送）。无 run_id 时 runs 域暂无进程内来源——如实
  登记，不假称全域有源（F-1 宣称=行为纪律）。

兼容层（任务书红线：既有轮询端点保留不动）：``/api/tune/status``、
``/api/tune/trials``、``/api/campaign_queue``、既有 runs SSE 桥零改动，
前端消费适配留后续席（静态文件本席零触碰）。

防护：订阅数上限（subscribe() 满员 → 503 信封）；参数非法 → ParamError
（A8-D 400 信封单源）；连接断开 = ASGI 取消生成器 → finally
unsubscribe（无泄漏，aclose 清理钉）。观测面 best-effort（#105）：tick
读面故障降级为该轮无事件，绝不影响流存活与业务主路径。
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from rfauto.ui.params import ParamError, _int_param
from rfauto.ui.routes.event_bus import (
    DOMAIN_CAMPAIGN,
    DOMAIN_RUNS,
    DOMAIN_TUNE,
    DOMAINS,
)

# ── 流参数（对齐既有 runs 桥的节拍口径）────────────────────────────────
_STREAM_TICK_S = 1.0
_STREAM_MAX_IDLE_S = 300.0  # 无事件也定时断流——EventSource 自动重连续传

#: campaign stage 终态（到达即补发 launch_completed——任务书"发射完成"面）
_STAGE_DONE_STATUS = "done"


# ── campaign 扫描共享 ticker（UI-R10 修 uir8 审查 P2：连接数与扫描频次解耦）──
#: 共享扫描窗口（秒）：同一 root 在窗口内至多扫一次盘，N 连接复用同一
#: 快照代际——修复前 tick 在每个流生成器循环内各调一次快照（N 连接 =
#: N 次/秒全目录扫描+逐计划解析）。取值=流 tick 周期：同一生成器相邻
#: 两轮间隔恒 ≥ tick_s（循环末尾无条件 sleep），故自身下一轮必然过期
#: 重扫，单连接变化检测时延与修复前等价；多连接窗口内复用不丢事件
#: （事件经总线广播，落后连接由环形回放补齐；差分恰一次由去重窗保证）。
_CAMPAIGN_SCAN_TTL_S = _STREAM_TICK_S
#: 缓存 root 数上限（``?root=`` 接受任意路径——有界防任意根撑爆缓存）
_CAMPAIGN_SCAN_CACHE_MAX_ROOTS = 8
_scan_cache_lock = threading.Lock()
_ScanCacheEntry = tuple[float, dict[str, dict[str, Any]]]
_scan_cache: OrderedDict[str, _ScanCacheEntry] = OrderedDict()


def _reset_campaign_scan_cache() -> None:
    """清空共享扫描缓存（测试隔离钩子——进程内跨测试防串味）。"""
    with _scan_cache_lock:
        _scan_cache.clear()


def shared_campaign_snapshot(root: str) -> dict[str, dict[str, Any]]:
    """TTL 单飞共享扫描：窗口内首个调用者扫盘，其余复用同一快照对象。

    键=abspath 归一（``runs`` vs ``./runs`` 等价写法归并、chdir 隔离下
    各归各键）；TTL 判据用 monotonic（不受系统时钟跳变影响）。单飞=
    持锁扫描（与既有事件循环串行同序，无新增阻塞面）；扫描函数经模块
    属性动态查找——测试替换 ``campaign_snapshot`` 观测点仍生效。读面
    故障降级沿 ``campaign_snapshot``（空快照=该轮无变化，#105）。
    """
    key = os.path.abspath(root)
    now = time.monotonic()
    with _scan_cache_lock:
        hit = _scan_cache.get(key)
        if hit is not None and (now - hit[0]) < _CAMPAIGN_SCAN_TTL_S:
            _scan_cache.move_to_end(key)
            return hit[1]
        snap = campaign_snapshot(root)
        _scan_cache[key] = (now, snap)
        _scan_cache.move_to_end(key)
        while len(_scan_cache) > _CAMPAIGN_SCAN_CACHE_MAX_ROOTS:
            _scan_cache.popitem(last=False)
        return snap


# ── campaign tick 检测器（快照差分，纯函数钉在 test_ui_event_stream）─────
def campaign_snapshot(root: str) -> dict[str, dict[str, Any]]:
    """扫战役计划目录 → 快照 {计划路径: {"model","verdict","stages":{名:状态}}}。

    只读（service/campaign_manager 既有函数，损坏计划逐条跳过 #105 口径）；
    任何读面异常降级为空快照（该轮视为无变化，流不炸）。
    """
    try:
        from rfauto.service.campaign_manager import list_campaign_plans, load_plan

        listing = list_campaign_plans(root)
        snap: dict[str, dict[str, Any]] = {}
        for item in listing.get("campaigns", []):
            path = str(item.get("path") or "")
            if not path:
                continue
            plan = (load_plan(path).get("plan")) or {}
            snap[path] = {
                "model": str(plan.get("model") or ""),
                "verdict": str(plan.get("verdict") or ""),
                "stages": {
                    str(s.get("stage") or ""): str(s.get("status") or "")
                    for s in plan.get("stages") or []},
            }
        return snap
    except Exception:  # 观测面 best-effort（#105）：宁缺勿炸流
        return {}


def detect_campaign_changes(
    prev: dict[str, dict[str, Any]] | None,
    cur: dict[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any], str]]:
    """快照差分 → [(kind, payload, dedupe_key)]。

    - prev=None（连接首测）：现存计划全部公告 campaign_new（清单公告语义，
      去重窗保证多连接/重连时恰好一次）；不做 stage 差分（无前态可比）；
    - prev 非 None：新计划 → campaign_new；已知计划 stage 状态翻转 →
      stage_changed（from→to）；翻转到 done → 追加 launch_completed。
    """
    out: list[tuple[str, dict[str, Any], str]] = []
    for path in sorted(cur):
        info = cur[path]
        if prev is None or path not in prev:
            out.append((
                "campaign_new",
                {"campaign": path, "model": info.get("model", ""),
                 "verdict": info.get("verdict", ""),
                 "stages": [{"stage": st, "status": status}
                            for st, status in sorted(info.get("stages", {}).items())]},
                f"cnew:{path}"))
            continue
        old_stages = prev[path].get("stages", {})
        for st in sorted(info.get("stages", {})):
            new_status = info["stages"][st]
            old_status = old_stages.get(st)
            if old_status is None or old_status == new_status:
                continue
            payload = {"campaign": path, "stage": st,
                       "from": old_status, "to": new_status}
            out.append(("stage_changed", payload,
                        f"stage:{path}:{st}:{new_status}"))
            if new_status == _STAGE_DONE_STATUS:
                out.append(("launch_completed", dict(payload),
                            f"launch:{path}:{st}:{new_status}"))
    return out


def _campaign_tick(
    prev: dict[str, dict[str, Any]] | None, root: str
) -> tuple[dict[str, dict[str, Any]], int]:
    """跑一轮 campaign 差分并把事件发进总线；返回 (新快照, 发布条数)。

    快照取自共享 ticker（``shared_campaign_snapshot``，UI-R10 P2 修复）：
    扫描频次与连接数解耦（同 root 同窗口至多一次扫盘），差分仍逐连接
    （``prev`` 为生成器本地态），跨连接恰好一次由总线去重窗保证。
    """
    from rfauto.ui.routes.event_bus import try_publish

    cur = shared_campaign_snapshot(root)
    published = 0
    for kind, payload, key in detect_campaign_changes(prev, cur):
        if try_publish(kind, "campaign", payload, dedupe_key=key) is not None:
            published += 1
    return cur, published


# ── runs 镜像 tick（events.jsonl 偏移增量 → 总线；信封向后兼容源）────────
def _runs_mirror_tick(
    run_id: str, offset: int
) -> tuple[int, bool, bool, list[dict[str, Any]]]:
    """读一轮 run 事件增量并镜像进总线。

    返回 ``(新偏移, exists, terminal, 本次镜像的信封)``。读面异常降级为
    无增量（#105）。镜像信封：kind=旧 event_type、payload=旧事件 dict
    原样（旧字段零消失）。
    """
    from rfauto.service import ui_service
    from rfauto.ui.routes.event_bus import try_publish

    try:
        snap = ui_service.read_run_events(run_id, offset)
    except Exception:  # 读面故障不炸流
        return offset, True, False, []
    if not snap.get("ok"):
        return offset, True, False, []
    if not snap.get("exists"):
        return offset, False, False, []
    mirrored: list[dict[str, Any]] = []
    for ev in snap.get("events") or []:
        kind = str(ev.get("event_type", "progress"))
        env = try_publish(kind, "runs", ev,
                          dedupe_key=f"run:{run_id}:{ev.get('event_id') or ev.get('timestamp')}")
        if env is not None:
            mirrored.append(env)
    return int(snap.get("offset") or offset), True, bool(snap.get("terminal")), mirrored


# ── 流生成器（端点薄壳共用单源；测试可直接驱动 + aclose 清理钉）──────────
def make_stream_generator(
    bus_: Any,
    sub: dict[str, Any],
    *,
    domains: tuple[str, ...],
    run_id: str | None = None,
    root: str = "runs",
    tick_s: float = _STREAM_TICK_S,
    max_idle_s: float = _STREAM_MAX_IDLE_S,
) -> Any:
    """统一 SSE 生成器：hello 首帧 → tick（campaign/runs）→ 总线增量 → 帧。

    ``bus_``/``sub`` 显式注入（端点传 bus()/subscribe() 产物；测试传隔离
    实例）；finally 必 unsubscribe——ASGI 客户端断开即取消生成器，清理
    单点（防泄漏钉）。``runs`` 镜像单域模式在 terminal/exists=false 时发
    end 帧收束（与既有桥同语义）；多域流不收束（长驻，300s 空闲回收靠
    EventSource 重连续传）。
    """
    async def _gen():
        from rfauto.ui.routes.event_bus import control_frame

        cursor = int(sub.get("last_seq") or 0)
        run_cursor = 0
        run_gone = False
        terminal_seen = False
        camp_prev: dict[str, dict[str, Any]] | None = None
        idle_s = 0.0
        try:
            yield control_frame("hello", {"cursor": bus_.head_seq(),
                                          "domains": list(domains),
                                          "run_id": run_id})
            while True:
                # 1) 域 tick：把进程外状态变化发布进总线（全部 best-effort）
                published = 0
                if "campaign" in domains:
                    camp_prev, published = _campaign_tick(camp_prev, root)
                mirror_frames: list[dict[str, Any]] = []
                if "runs" in domains and run_id and not run_gone:
                    run_cursor, exists, terminal_seen, mirror_frames = (
                        _runs_mirror_tick(run_id, run_cursor))
                    if not exists:
                        run_gone = True  # 事件流缺席（桥 empty 同语义）
                    published += len(mirror_frames)
                # 2) 总线增量 → 统一帧（含重连回放；背压截断 → resync）
                events, truncated = bus_.since(cursor)
                if truncated:
                    cursor = bus_.head_seq()
                    yield control_frame("resync", {"cursor": cursor})
                else:
                    for env in events:
                        cursor = int(env["seq"])
                        yield {"event": str(env["kind"]),
                               "id": str(env["seq"]),
                               "data": json.dumps(env, ensure_ascii=False)}
                # 3) 收束语义：runs 镜像单域模式与既有桥 end 帧同字面
                #    （data 顶层 terminal/exists——前端 sseEndMark 解析器原样可用）
                if domains == ("runs",) and (terminal_seen or run_gone):
                    data = ({"terminal": True, "run_id": run_id}
                            if terminal_seen
                            else {"exists": False, "run_id": run_id})
                    yield {"event": "end",
                           "data": json.dumps(data, ensure_ascii=False)}
                    return
                idle_s = 0.0 if (events or published or truncated) else (
                    idle_s + tick_s)
                if idle_s >= max_idle_s:
                    return  # EventSource 自动重连，Last-Event-ID 续传
                await asyncio.sleep(tick_s)
        finally:
            bus_.unsubscribe(sub)  # 断开清理单点（连接数注册表对账）

    return _gen()


# ── 端点薄壳（参数守卫 → 订阅登记 → EventSourceResponse）────────────────
def _parse_domains(raw: str | None) -> tuple[str, ...]:
    """``?domain=tune,campaign`` 解析；非法值 ParamError（400 信封单源）。"""
    if not raw:
        return DOMAINS
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    bad = [p for p in parts if p not in DOMAINS]
    if bad or not parts:
        raise ParamError(
            f"domain 须为 {'/'.join(DOMAINS)} 的逗号组合，实际 {raw!r}")
    return parts


def _events_stream_response(
    request: Request, *, domains: tuple[str, ...], run_id: str | None,
    root: str,
) -> Any:
    """共用装配：sse-starlette 缺装 503 → 参数守卫 → 订阅满员 503 → 流。"""
    try:
        from sse_starlette.sse import EventSourceResponse
    except ImportError as exc:
        from rfauto.service.envelope import error_envelope

        return JSONResponse(
            error_envelope(
                [f"sse-starlette 未安装（pip install rfauto[ui]）: {exc}"]),
            status_code=503)

    from rfauto.ui.routes.event_bus import bus

    cursor = _int_param(request.headers.get("last-event-id"), 0,
                        "Last-Event-ID")
    eb = bus()
    sub = eb.subscribe(last_seq=cursor, source="unified")
    if sub is None:
        from rfauto.service.envelope import error_envelope

        return JSONResponse(
            error_envelope(["实时事件流订阅数已达上限，请稍后重连"]),
            status_code=503)
    gen = make_stream_generator(eb, sub, domains=domains, run_id=run_id,
                                root=root)
    return EventSourceResponse(gen, ping=15.0)


async def api_events_stream(request: Request) -> Any:
    """统一事件流（全域；``?domain=`` 过滤、``?run_id=`` runs 镜像、
    ``?root=`` campaign 计划根；Last-Event-ID 头续传）。"""
    q = request.query_params
    domains = _parse_domains(q.get("domain"))
    run_id = q.get("run_id") or None
    root = q.get("root") or "runs"
    if run_id and DOMAIN_RUNS not in domains:
        domains = (DOMAIN_RUNS, *domains)  # 镜像即 runs 域消费，隐式纳入
    return _events_stream_response(request, domains=domains, run_id=run_id,
                                   root=root)


async def api_tune_events_stream(request: Request) -> Any:
    """tune 域事件流（状态转移 + 逐 trial 探针，发布源在 routes/tune.py）。"""
    return _events_stream_response(request, domains=(DOMAIN_TUNE,),
                                   run_id=None, root="runs")


async def api_campaign_queue_events_stream(request: Request) -> Any:
    """campaign 域事件流（队列 tick：campaign_new/stage_changed/
    launch_completed；``?root=`` 与既有 /api/campaign_queue 同语义）。"""
    q = request.query_params
    root = q.get("root") or "runs"
    return _events_stream_response(request, domains=(DOMAIN_CAMPAIGN,),
                                   run_id=None, root=root)
