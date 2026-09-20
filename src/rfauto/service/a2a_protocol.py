"""A2A 协议层（WP3.8 三层栈·第 3 层）——Agent 间互操作的最小确定性实现。

方案口径（2025-26 收敛三层栈）：
A2A（Agent2Agent，Google 发起、Linux 基金会托管）负责**Agent 间**互操作——
与 MCP（人/模型 ↔ 工具）互补。本模块落其核心数据契约的进程内子集，
transport（HTTP/JSON-RPC、agent card 发现端点）留待后续轮次：

- **AgentCard**：自描述元数据（name/description/url/version/capabilities/
  默认模态/skills）——A2A 发现面（规范内等价于
  ``/.well-known/agent-card.json`` 的载荷）；
- **Message/Part**：一次交互的载荷（TextPart/DataPart，DataPart 携带
  typed JSON——rfauto 的 typed tool call 铁律 7 同构）;
- **Task 生命周期**：submitted→working→completed/failed/canceled
  （+input_required），非法跃迁拒绝；
- **A2ARegistry**：按名字注册 Agent、卡发现、消息分发；handler 异常折入
  failed Task，不向调用方抛协议外异常。

数值铁律：本模块只搬 typed JSON，不产生任何物理数字。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

#: A2A 规范的 agent card 发现路径（记录口径；进程内分发不经过 HTTP）。
WELL_KNOWN_CARD_PATH = "/.well-known/agent-card.json"

#: A2A 协议版本口径（本实现锚定的规范快照）。
PROTOCOL_VERSION = "0.2"


class TaskState(str, Enum):
    """A2A task 生命周期状态（规范 TaskState 子集）。"""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


#: 终态集合（终态不得再跃迁）。
_TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
#: 合法跃迁表（source → 允许的 target 集合）。
LEGAL_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.SUBMITTED: {TaskState.WORKING, TaskState.INPUT_REQUIRED,
                          TaskState.COMPLETED, TaskState.FAILED,
                          TaskState.CANCELED},
    TaskState.WORKING: {TaskState.WORKING, TaskState.INPUT_REQUIRED,
                        TaskState.COMPLETED, TaskState.FAILED,
                        TaskState.CANCELED},
    TaskState.INPUT_REQUIRED: {TaskState.WORKING, TaskState.COMPLETED,
                               TaskState.FAILED, TaskState.CANCELED},
}
for _t in _TERMINAL_STATES:
    LEGAL_TRANSITIONS[_t] = set()


def can_transition(src: TaskState, dst: TaskState) -> bool:
    """src→dst 是否为合法跃迁（终态不可出）。"""
    return dst in LEGAL_TRANSITIONS.get(src, set())


class A2AError(ValueError):
    """A2A 契约错误（非法跃迁/未知 Agent/空载荷等）。"""


# ─── 卡与载荷 ────────────────────────────────────────────────────────────────
@dataclass
class AgentSkill:
    """Agent 能力单元（A2A AgentSkill：id/name/description/tags/examples）。"""

    id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name,
            "description": self.description,
            "tags": list(self.tags), "examples": list(self.examples),
        }


@dataclass
class AgentCard:
    """A2A AgentCard：Agent 的自描述元数据（发现面载荷）。"""

    name: str
    description: str = ""
    url: str = ""                       # 进程内实现留空/写 in-process://
    version: str = "0.1.0"
    protocol_version: str = PROTOCOL_VERSION
    capabilities: dict[str, bool] = field(default_factory=lambda: {
        "streaming": False, "push_notifications": False,
        "state_transition_history": True,
    })
    default_input_modes: list[str] = field(
        default_factory=lambda: ["application/json"])
    default_output_modes: list[str] = field(
        default_factory=lambda: ["application/json"])
    skills: list[AgentSkill] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "url": self.url or f"in-process://{self.name}",
            "version": self.version,
            "protocolVersion": self.protocol_version,
            "capabilities": dict(self.capabilities),
            "defaultInputModes": list(self.default_input_modes),
            "defaultOutputModes": list(self.default_output_modes),
            "skills": [s.to_dict() for s in self.skills],
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> AgentCard:
        """从发现面 JSON 重建（大小驼峰与 snake_case 均收）。"""
        skills = [AgentSkill(
            id=str(s.get("id", "")), name=str(s.get("name", "")),
            description=str(s.get("description", "")),
            tags=[str(t) for t in (s.get("tags") or [])],
            examples=[str(e) for e in (s.get("examples") or [])],
        ) for s in (doc.get("skills") or []) if isinstance(s, dict)]
        return cls(
            name=str(doc.get("name", "")),
            description=str(doc.get("description", "")),
            url=str(doc.get("url", "")),
            version=str(doc.get("version", "0.1.0")),
            protocol_version=str(
                doc.get("protocolVersion", doc.get("protocol_version",
                                                    PROTOCOL_VERSION))),
            capabilities=dict(doc.get("capabilities") or {}),
            default_input_modes=[str(m) for m in (
                doc.get("defaultInputModes") or
                doc.get("default_input_modes") or ["application/json"])],
            default_output_modes=[str(m) for m in (
                doc.get("defaultOutputModes") or
                doc.get("default_output_modes") or ["application/json"])],
            skills=skills,
        )


@dataclass
class DataPart:
    """typed JSON 载荷（A2A DataPart）——typed tool call 的载体。"""

    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "data", "data": dict(self.data)}


@dataclass
class TextPart:
    """文本载荷（A2A TextPart）。"""

    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "text", "text": self.text}


def part_to_dict(part: TextPart | DataPart) -> dict[str, Any]:
    return part.to_dict()


@dataclass
class A2AMessage:
    """A2A Message：role（user/agent）+ parts + message_id。"""

    role: str
    parts: list[TextPart | DataPart] = field(default_factory=list)
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "parts": [part_to_dict(p) for p in self.parts],
                "messageId": self.message_id}

    def data_payloads(self) -> list[dict[str, Any]]:
        """全部 DataPart 的 data（typed 通道；TextPart 不混入）。"""
        return [dict(p.data) for p in self.parts if isinstance(p, DataPart)]

    @classmethod
    def with_data(cls, role: str, data: dict[str, Any]) -> A2AMessage:
        return cls(role=role, parts=[DataPart(data=dict(data))])


@dataclass
class A2ATask:
    """A2A Task：一次有状态的交互单元（生命周期 + 历史）。"""

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    context_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: TaskState = TaskState.SUBMITTED
    history: list[A2AMessage] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def transition(self, dst: TaskState, *, error: str = "") -> None:
        """受控跃迁：非法跃迁拒绝（A2A 语义），终态不可出。"""
        src = self.state
        if not can_transition(src, dst):
            raise A2AError(f"非法任务状态跃迁: {src.value} → {dst.value}")
        self.state = dst
        self.error = str(error)
        self.updated_at = time.time()

    def add_message(self, message: A2AMessage) -> None:
        self.history.append(message)
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id, "contextId": self.context_id,
            "state": self.state.value, "error": self.error,
            "history": [m.to_dict() for m in self.history],
            "artifacts": [dict(a) for a in self.artifacts],
            "createdAt": self.created_at, "updatedAt": self.updated_at,
        }


# ─── Agent 协议与注册表 ──────────────────────────────────────────────────────
class A2AAgent(Protocol):
    """A2A Agent 最小契约：自描述卡 + 消息处理器（确定性函数即可）。"""

    @property
    def card(self) -> AgentCard: ...

    def handle(self, message: A2AMessage) -> A2ATask: ...


class A2ARegistry:
    """按名字注册/发现/分发（进程内 transport；网络留待后续轮次）。

    dispatch 契约：
    - 未知 agent → 立即 failed Task（协议面错误折入任务，不外抛）；
    - handler 内部异常 → failed Task（错误消息进 error 字段）；
    - handler 正常返回的 Task 直接回传（状态由 handler 决定）。
    """

    def __init__(self) -> None:
        self._agents: dict[str, A2AAgent] = {}

    def register(self, agent: A2AAgent) -> AgentCard:
        name = agent.card.name
        if not name:
            raise A2AError("AgentCard.name 不能为空")
        if name in self._agents:
            raise A2AError(f"Agent 重复注册: {name}")
        self._agents[name] = agent
        return agent.card

    def names(self) -> list[str]:
        return sorted(self._agents)

    def agent_card(self, name: str) -> dict[str, Any]:
        """单卡发现（规范 agent card 载荷）。未知 agent 抛 A2AError。"""
        agent = self._agents.get(str(name))
        if agent is None:
            raise A2AError(f"未知 Agent: {name}")
        return agent.card.to_dict()

    def list_agent_cards(self) -> list[dict[str, Any]]:
        """全量卡发现（等价 /.well-known/agent-card.json 枚举）。"""
        return [self.agent_card(n) for n in self.names()]

    def dispatch(self, agent_name: str, message: A2AMessage) -> A2ATask:
        """把一条 Message 派给目标 Agent，回传其 Task（协议边界内吞异常）。"""
        name = str(agent_name)
        agent = self._agents.get(name)
        if agent is None:
            task = A2ATask(state=TaskState.FAILED,
                           error=f"未知 Agent: {name}")
            task.add_message(message)
            return task
        try:
            task = agent.handle(message)
            task.add_message(message)
            return task
        except Exception as exc:  # 协议边界：异常折入 failed Task
            task = A2ATask(state=TaskState.FAILED,
                           error=f"agent {name} handler 异常: {exc}")
            task.add_message(message)
            return task
