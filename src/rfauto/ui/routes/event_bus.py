"""UI 统一实时事件流总线（架构批 UI-R3 席）——routes 层单源广播/订阅 helper。

背景：现役实时面三套语义并存——runs 的 SSE 桥（routes/runs.py
api_run_events_stream，events.jsonl 偏移轮询）、tune 轮询（routes/tune.py
_TUNE_STATE + 前端 3s 轮询）、campaign 队列轮询（campaign_app.py
api_campaign_queue + 前端轮询）。本模块把"进程内事件"收编为**一个**总线：
所有域（runs/tune/campaign）共用同一信封、同一 seq 单调轴、同一订阅/
回放/清理语义，防止每个域各造一套队列（任务书红线）。

统一事件信封（任务书形态，键集钉死）::

    {"seq": int, "ts": float, "kind": str, "domain": str, "payload": dict}

- seq：进程内单调递增（锁保护），业务帧同时作为 SSE ``id:`` 帧——浏览器
  EventSource 断线重连携带 Last-Event-ID 头即可从该 seq 续传（对齐既有
  runs 桥的 events.jsonl 偏移续传语义；控制帧 hello/resync 产帧**省略
  id**——无 ``id:`` 行不清客户端游标，UI-R9 P1-A）；
- ts：time.time() 浮点纪元秒（与 core/events.py Event.timestamp 同口径）；
- kind：事件种类字符串。**向后兼容**：domain="runs" 的信封 kind=旧
  event_type、payload=旧事件 dict 原样透传（event_type/event_id/run_id/
  timestamp 等旧字段一个不消失，test_ui_event_stream 钉住）；
- domain："runs" | "tune" | "campaign"（DOMAINS），控制帧用 "system"。

发布面（谁在发布）：
- routes/tune.py：调参状态转移（tune_started/tune_completed/tune_failed）
  + 逐 trial 探针（trial_new，走 service start_tune 既有 on_trial 挂点，
  服务层零改动）；
- routes/runs.py：P-1 桥逐事件懒镜像（帧零改动，domain="runs"）；
- routes/events.py：campaign 队列 tick 检测器（计划文件快照差分 →
  campaign_new/stage_changed/launch_completed）。

背压与防护（任务书：连接数与背压防护）：
- 环形缓冲（EventBus(ring_size=...)，缺省 512 条）——慢客户端不阻塞发布
  方；游标落后于缓冲窗口 → ``since()`` 报 truncated，流端发 resync 控制
  帧（客户端整页刷新对齐既有消费纪律）；
- 去重窗（dedupe_key → seq，OrderedDict 容量上限淘汰最旧）——多客户端
  各自 tick 检测同一转移时恰好发布一次；
- 订阅注册表（每连接恰一个订阅句柄）+ 数量上限（max_subscribers，超限
  subscribe() 返回 None → 端点 503 信封）；断开清理=生成器 finally
  unsubscribe（无 per-client 队列可泄漏，游标语义天然无泄漏，
  test_ui_event_stream::aclose 清理钉）。

线程模型：publish 可从任意线程调用（tune 业务跑在后台线程，#A6 P1-3
下放范式）——threading.Lock 保护 seq/环形/去重/注册表全部可变面。
观测面 best-effort（#105）：try_publish 吞一切异常，推送故障绝不影响
业务主路径。禁 ``__all__``（public_api 金快照零扰动，check_public_api
只钉带 __all__ 模块）。
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict, deque
from typing import Any

#: 统一信封键集（形态钉：set(env) == EVENT_ENVELOPE_KEYS）
EVENT_ENVELOPE_KEYS = ("seq", "ts", "kind", "domain", "payload")

#: 业务域清单（kind 值域开放——未知 kind 前端按 refresh 处理，前向兼容）
DOMAIN_RUNS = "runs"
DOMAIN_TUNE = "tune"
DOMAIN_CAMPAIGN = "campaign"
DOMAINS = (DOMAIN_RUNS, DOMAIN_TUNE, DOMAIN_CAMPAIGN)
#: 控制帧域（hello/resync 不走环形缓冲、不入去重窗；产帧省略 id 键——
#: EventSource 语义下不清客户端 Last-Event-ID 游标，UI-R9 P1-A）
DOMAIN_SYSTEM = "system"

#: 环形缓冲缺省容量（回放窗口；超过即淘汰最旧并推进截断基线）
DEFAULT_RING_SIZE = 512
#: 去重窗容量（dedupe_key → seq；多客户端 tick 恰好一次语义）
DEFAULT_DEDUPE_SIZE = 4096
#: 订阅数上限（每连接一个订阅句柄；超限端点回 503 信封）
DEFAULT_MAX_SUBSCRIBERS = 64


class EventBus:
    """进程内统一事件总线（线程安全；单实例挂模块尾 ``_BUS``）。

    订阅是**游标语义**（对齐 runs 桥的文件偏移续传）：订阅句柄只记起点
    seq，消费经 ``since(cursor)`` 拉增量——无 per-client 队列，断开清理
    只是注册表摘除，结构性无泄漏。
    """

    def __init__(
        self,
        *,
        ring_size: int = DEFAULT_RING_SIZE,
        dedupe_size: int = DEFAULT_DEDUPE_SIZE,
        max_subscribers: int = DEFAULT_MAX_SUBSCRIBERS,
    ) -> None:
        self._lock = threading.Lock()
        self._ring: deque[dict[str, Any]] = deque(maxlen=int(ring_size))
        self._seq = 0
        #: 已被淘汰的最旧 seq（环形窗口左界外的最后一条；0=无淘汰）
        self._evicted_through = 0
        self._dedupe: OrderedDict[str, int] = OrderedDict()
        self._dedupe_size = int(dedupe_size)
        self._max_subscribers = int(max_subscribers)
        self._subs: dict[int, dict[str, Any]] = {}
        self._sub_ids = 0

    # ── 发布面（任意线程可调）──────────────────────────────────────────

    def publish(
        self,
        kind: str,
        domain: str,
        payload: dict[str, Any] | None = None,
        *,
        dedupe_key: str | None = None,
    ) -> dict[str, Any] | None:
        """发布统一信封；``dedupe_key`` 命中去重窗时返回 None（已发布过）。"""
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"kind 必须非空 str，实际 {kind!r}")
        if not isinstance(domain, str) or not domain:
            raise ValueError(f"domain 必须非空 str，实际 {domain!r}")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError(f"payload 必须是 dict，实际 {type(payload).__name__}")
        with self._lock:
            if dedupe_key is not None and dedupe_key in self._dedupe:
                return None
            self._seq += 1
            env: dict[str, Any] = {
                "seq": self._seq,
                "ts": time.time(),
                "kind": kind,
                "domain": domain,
                "payload": dict(payload or {}),
            }
            if len(self._ring) == self._ring.maxlen and self._ring.maxlen:
                evicted = self._ring[0]
                self._evicted_through = max(self._evicted_through,
                                            int(evicted.get("seq") or 0))
            self._ring.append(env)
            if dedupe_key is not None:
                self._dedupe[dedupe_key] = self._seq
                while len(self._dedupe) > self._dedupe_size:
                    self._dedupe.popitem(last=False)
            return env

    # ── 消费面（游标语义）──────────────────────────────────────────────

    def since(self, cursor: int) -> tuple[list[dict[str, Any]], bool]:
        """返回 ``(seq > cursor 的信封按序, truncated)``。

        truncated=True = 游标落后于环形窗口（有事件已被淘汰未送达）——
        消费方应发 resync 控制帧并跳到 head（客户端整页刷新兜底）。
        """
        cursor = int(cursor)
        with self._lock:
            events = [e for e in self._ring if int(e["seq"]) > cursor]
            truncated = bool(
                self._evicted_through and cursor < self._evicted_through)
            return events, truncated

    def head_seq(self) -> int:
        with self._lock:
            return self._seq

    # ── 订阅注册面（连接数防护 + 断开清理）────────────────────────────

    def subscribe(self, last_seq: int = 0, *, source: str = "") -> dict[str, Any] | None:
        """登记一个订阅句柄（每客户端连接恰一个）；满员返回 None。

        句柄是普通 dict（非可等待对象）：游标语义下消费方自持迭代状态，
        注册表只承担连接数守卫与清理对账。
        """
        with self._lock:
            if len(self._subs) >= self._max_subscribers:
                return None
            self._sub_ids += 1
            sub = {
                "id": self._sub_ids,
                "last_seq": int(last_seq),
                "source": str(source or ""),
                "opened_ts": time.time(),
                "closed": False,
            }
            self._subs[sub["id"]] = sub
            return sub

    def unsubscribe(self, sub: dict[str, Any] | None) -> bool:
        """摘除订阅句柄（幂等）；返回是否本次确有摘除。"""
        if not sub:
            return False
        with self._lock:
            sub["closed"] = True
            return self._subs.pop(sub.get("id"), None) is not None

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)


#: 模块级单实例（进程内单源；测试经 monkeypatch.setattr(event_bus, "_BUS",
#: EventBus(...)) 换隔离实例——端点经 bus() 取用，不缓存引用）。
_BUS = EventBus()


def bus() -> EventBus:
    """取当前总线单例（每次调用现读模块属性——测试换血零缓存面）。"""
    return _BUS


def try_publish(
    kind: str,
    domain: str,
    payload: dict[str, Any] | None = None,
    *,
    dedupe_key: str | None = None,
    bus_: EventBus | None = None,
) -> dict[str, Any] | None:
    """best-effort 发布（#105：观测面绝不成为业务主路径故障点）。

    吞一切异常返回 None——发布方（tune 后台线程/runs 桥/campaign tick）
    零感知推送故障。
    """
    try:
        return (bus_ or bus()).publish(kind, domain, payload,
                                       dedupe_key=dedupe_key)
    except Exception:
        return None


def sse_frame(env: dict[str, Any]) -> dict[str, str]:
    """业务信封 → sse-starlette 帧（named 事件形态与既有 runs 桥对齐）。

    ``event=<kind>`` + ``id=<seq>``（Last-Event-ID 续传锚）+
    ``data=<信封 JSON>``——旧字段消费方在 data.payload 里原样找到。
    控制帧（hello/resync/end）不走本函数（省略 id，见 control_frame）。
    """
    return {
        "event": str(env["kind"]),
        "id": str(env["seq"]),
        "data": json.dumps(env, ensure_ascii=False),
    }


def control_frame(kind: str, payload: dict[str, Any]) -> dict[str, str]:
    """控制帧（hello/resync/end 同形态；domain=system，不经总线）。

    UI-R9 P1-A：帧**省略 ``id`` 键**——EventSource 规范下无 ``id:`` 行
    不更新 lastEventId，hello/resync 不把客户端游标清回 0（旧行为 id=0
    会使重连携 ``Last-Event-ID: 0`` 全环形窗口重放或误触 resync）。重连
    起点引导走 hello payload 的 ``cursor``（=head seq）。data 内信封形态
    不变（EVENT_ENVELOPE_KEYS，seq 恒 0 仅表"非业务帧"）。
    """
    return {
        "event": str(kind),
        "data": json.dumps({"seq": 0, "ts": time.time(), "kind": kind,
                            "domain": DOMAIN_SYSTEM, "payload": payload},
                           ensure_ascii=False),
    }
