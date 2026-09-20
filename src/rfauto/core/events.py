"""事件总线（§8.7）—— pub/sub 模式，进度/告警/自愈钩子的订阅源。

所有事件带 run_id，落盘到 runs/<run_id>/events.jsonl。
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
