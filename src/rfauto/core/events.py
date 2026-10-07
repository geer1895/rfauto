"""事件总线（§8.7）—— pub/sub 模式，进度/告警/自愈钩子的订阅源。

所有事件带 run_id，落盘到 runs/<run_id>/events.jsonl。

W3 飞行记录仪统一事件 schema（月计划 B4 增量，2026-09-28 #222 三查接地）：
写出侧 Event 携带 ``schema`` 标识（rfauto-event/1）落盘；读出侧
:func:`validate_event_payload` / :func:`normalize_event_payload` 提供统一
校验与归一——旧档案无 schema 键照读（向后兼容，缺失不报错），坏行
:func:`parse_event_line` 返回 None（#105 best-effort，读面不炸不凑绿）。
消费面（ui_service.read_run_events / SSE 桥）透传 dict，零改动。
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

#: 统一事件 schema 标识（新事件写入携带；旧档案无此键=读面宽容）
EVENT_SCHEMA = "rfauto-event/1"

#: 必备键（缺任一=非法事件；schema 键缺失合法=旧档案兼容）
EVENT_REQUIRED_KEYS = ("event_type", "timestamp", "event_id")


class EventSchemaError(ValueError):
    """事件载荷非法（校验错误清单拼接进报文；fail-closed 多报方向）。"""


class EventType(str, Enum):
    """事件类型枚举。"""
    RUN_CREATED = "run_created"
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    TRIAL_STARTED = "trial_started"
    TRIAL_COMPLETED = "trial_completed"
    TRIAL_FAILED = "trial_failed"
    SOLVE_STARTED = "solve_started"
    SOLVE_COMPLETED = "solve_completed"
    BUILD_COMPLETED = "build_completed"
    CACHE_HIT = "cache_hit"
    SELF_HEAL = "self_heal"
    WARNING = "warning"
    ERROR = "error"
    PROGRESS = "progress"
    LICENSE_WAIT = "license_wait"
    USER_CANCEL = "user_cancel"


@dataclass
class Event:
    """不可变事件对象。"""
    event_type: EventType
    run_id: str = ""
    job_id: str = ""
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    schema: str = EVENT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonl(self) -> str:
        d = self.to_dict()
        d["event_type"] = d["event_type"].value if isinstance(d["event_type"], Enum) else d["event_type"]
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


# 事件处理器类型
EventHandler = Callable[[Event], None]


class EventBus:
    """进程内事件总线 + JSONL 落盘。

    用法：
        bus = EventBus()
        bus.subscribe(EventType.TRIAL_COMPLETED, my_handler)
        bus.emit(Event(EventType.TRIAL_COMPLETED, run_id="...", data={...}))
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._global_handlers: list[EventHandler] = []
        self._jsonl_path: Path | None = None

    def set_jsonl_sink(self, path: Path) -> None:
        """设置 JSONL 落盘路径。"""
        self._jsonl_path = path
        self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """订阅特定事件类型。"""
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """订阅所有事件。"""
        self._global_handlers.append(handler)

    def emit(self, event: Event) -> None:
        """发布事件：分发给所有匹配的订阅者 + 落盘 JSONL。"""
        # 分发给类型匹配的订阅者
        for handler in self._handlers.get(event.event_type, []):
            handler(event)
        # 分发给全局订阅者
        for handler in self._global_handlers:
            handler(event)
        # JSONL 落盘
        if self._jsonl_path:
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.write(event.to_jsonl() + "\n")


# 模块级全局事件总线（单例）
_global_bus = EventBus()


def get_event_bus() -> EventBus:
    """获取全局事件总线。"""
    return _global_bus


# ---------------------------------------------------------------------------
# W3：统一事件 schema 校验/归一（读出面；旧档案向后兼容）
# ---------------------------------------------------------------------------

_EVENT_TYPE_VALUES = frozenset(e.value for e in EventType)


def validate_event_payload(payload: Any) -> list[str]:
    """事件载荷校验（非抛出形态，返回错误清单；空=合法）。

    - 必备键：event_type / timestamp / event_id（schema 键缺失合法=旧档案）；
    - event_type 必须 ∈ EventType 值域（未识别类型多报不放过，#316）；
    - timestamp 数值且非 bool；event_id 非空串；run_id/job_id/message 若在
      场必须是 str；data 若在场必须是映射；schema 若在场必须等于
      EVENT_SCHEMA（声明了别的版本=错误，比缺失更严重）。
    """
    if not isinstance(payload, dict):
        return ["事件载荷必须是映射（dict），得 " + type(payload).__name__]
    errors: list[str] = []
    for key in EVENT_REQUIRED_KEYS:
        if key not in payload or payload[key] is None:
            errors.append(f"缺必备键 {key}")
    et = payload.get("event_type")
    if et is not None:
        et_val = et.value if isinstance(et, EventType) else et
        if et_val not in _EVENT_TYPE_VALUES:
            errors.append(f"未识别 event_type: {et_val!r}（值域 "
                          f"{sorted(_EVENT_TYPE_VALUES)}）")
    ts = payload.get("timestamp")
    if ts is not None and (isinstance(ts, bool) or not isinstance(ts, (int, float))):
        errors.append(f"timestamp 必须是数值（拒 bool），得 {ts!r}")
    eid = payload.get("event_id")
    if eid is not None and (not isinstance(eid, str) or not eid.strip()):
        errors.append(f"event_id 必须是非空字符串，得 {eid!r}")
    for key in ("run_id", "job_id", "message"):
        if key in payload and payload[key] is not None \
                and not isinstance(payload[key], str):
            errors.append(f"{key} 必须是字符串，得 {payload[key]!r}")
    if "data" in payload and payload["data"] is not None \
            and not isinstance(payload["data"], dict):
        errors.append(f"data 必须是映射，得 {type(payload['data']).__name__}")
    if "schema" in payload and payload["schema"] is not None \
            and payload["schema"] != EVENT_SCHEMA:
        errors.append(f"schema 版本不识别: {payload['schema']!r}"
                      f"（本面只认 {EVENT_SCHEMA}）")
    return errors


def normalize_event_payload(payload: Any) -> dict[str, Any]:
    """事件载荷归一：校验（非法 → EventSchemaError 汇总报文）→ 带schema副本。

    返回新 dict：原键全保留，缺 schema 键补 EVENT_SCHEMA（旧档案读面
    归一，落盘档案零改写——只动内存副本），event_type 归一为字符串值。
    输入 dict 零原地改。
    """
    errors = validate_event_payload(payload)
    if errors:
        raise EventSchemaError("事件载荷非法: " + "; ".join(errors))
    out = dict(payload)  # type: ignore[arg-type]
    out.setdefault("schema", EVENT_SCHEMA)
    et = out.get("event_type")
    if isinstance(et, EventType):
        out["event_type"] = et.value
    return out


def parse_event_line(line: str) -> dict[str, Any] | None:
    """events.jsonl 单行 → 载荷 dict；空行/损坏行/非映射 → None（#105）。"""
    line = (line or "").strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
