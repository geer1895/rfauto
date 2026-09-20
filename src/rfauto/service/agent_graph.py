"""LangGraph 式工作流状态机（WP3.8 三层栈·第 1 层）。

方案口径：propose→verify→fix
自愈环的**图实现**，作为 WP3.5 self_verify_loop（过程式 while 环）的升级路径。
借鉴 LangGraph 的最小语义子集，零新增依赖：

- **StateGraph**：节点 = 确定性函数（state → state 增量 dict，LangGraph 的
  node returns update 语义，浅合并进主状态）；边分普通边与条件边
  （router: state → 下一节点名或 END）；
- **compile().invoke(state)**：同步确定性推进，逐节点记录 trace；
  max_steps 是环的硬护栏（防 router 写错导致死循环）；
- **观测 best-effort**（#105）：节点进出经 core.events.EventBus 发事件，
  失败静默不阻塞主路径。

数值铁律：本模块不含任何物理/数值决策——节点函数由调用方
注入（见 multi_agent_service.py 的评审/调优/验证分工），图只负责控制流。
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from rfauto.core.events import Event, EventType, get_event_bus

#: 终止哨兵：条件 router 返回它表示到达终点（LangGraph 的 END 同形）。
GRAPH_END = "__end__"

#: 节点函数：读全量 state，返回**增量** dict（None 视为无更新）。
NodeFn = Callable[[dict[str, Any]], dict[str, Any] | None]
#: 条件 router：读全量 state，返回下一节点名或 GRAPH_END。
EdgeRouter = Callable[[dict[str, Any]], str]

DEFAULT_MAX_STEPS = 64


class GraphError(ValueError):
    """图的静态结构错误（重复节点/未知边端点/无入口等）。"""


class StateGraph:
    """LangGraph 式状态图构建器（确定性、零依赖）。

    典型用法（propose→verify→review 自愈环）::

        g = StateGraph()
        g.add_node("propose", propose_fn)
        g.add_node("verify", verify_fn)
        g.add_node("review", review_fn)
        g.set_entry_point("propose")
        g.add_edge("propose", "verify")
        g.add_edge("verify", "review")
        g.add_conditional_edge("review", review_router)  # → tune | END
        g.add_edge("review_tune", ...)                   # 由 router 命名
        graph = g.compile()
        state = graph.invoke({"params": {...}})
    """

    def __init__(self) -> None:
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, str] = {}
        self._routers: dict[str, EdgeRouter] = {}
        self._entry: str | None = None

    # ── 构建面 ───────────────────────────────────────────────────────────
    def add_node(self, name: str, fn: NodeFn) -> StateGraph:
        key = str(name)
        if not key or key == GRAPH_END:
            raise GraphError(f"非法节点名: {key!r}")
        if key in self._nodes:
            raise GraphError(f"节点重复注册: {key}")
        self._nodes[key] = fn
        return self

    def add_edge(self, src: str, dst: str) -> StateGraph:
        s, d = str(src), str(dst)
        if d == GRAPH_END:
            # LangGraph 允许显式 END 边；内部统一收敛为条件边语义
            return self.add_conditional_edge(s, lambda _state: GRAPH_END)
        if s in self._edges or s in self._routers:
            raise GraphError(f"节点 {s} 已有出边/条件边，不得重复")
        self._edges[s] = d
        return self

    def add_conditional_edge(self, src: str, router: EdgeRouter) -> StateGraph:
        s = str(src)
        if s in self._edges or s in self._routers:
            raise GraphError(f"节点 {s} 已有出边/条件边，不得重复")
        self._routers[s] = router
        return self

    def set_entry_point(self, name: str) -> StateGraph:
        self._entry = str(name)
        return self

    # ── 编译期校验 ───────────────────────────────────────────────────────
    def compile(self) -> CompiledGraph:
        """静态校验（入口存在、边端点存在）并冻结为可执行图。"""
        if not self._nodes:
            raise GraphError("空图：先 add_node 再 compile")
        if self._entry is None:
            raise GraphError("未设置入口：set_entry_point 必须在 compile 前调用")
        if self._entry not in self._nodes:
            raise GraphError(f"入口节点未注册: {self._entry}")
        for src, dst in self._edges.items():
            if src not in self._nodes:
                raise GraphError(f"出边源节点未注册: {src}")
            if dst not in self._nodes:
                raise GraphError(f"边端点未注册: {src} → {dst}")
        for src in self._routers:
            if src not in self._nodes:
                raise GraphError(f"条件边源节点未注册: {src}")
        return CompiledGraph(
            nodes=dict(self._nodes), edges=dict(self._edges),
            routers=dict(self._routers), entry=self._entry)


class CompiledGraph:
    """编译产物：invoke 确定性推进（同输入逐字节同 trace）。"""

    def __init__(
        self,
        *,
        nodes: dict[str, NodeFn],
        edges: dict[str, str],
        routers: dict[str, EdgeRouter],
        entry: str,
    ) -> None:
        self._nodes = nodes
        self._edges = edges
        self._routers = routers
        self._entry = entry

    # ── 查询面 ───────────────────────────────────────────────────────────
    @property
    def entry(self) -> str:
        return self._entry

    def node_names(self) -> list[str]:
        return sorted(self._nodes)

    # ── 执行面 ───────────────────────────────────────────────────────────
    def invoke(
        self,
        state: dict[str, Any] | None = None,
        *,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> dict[str, Any]:
        """从入口推进到 END / max_steps，返回最终状态（含 trace/finished）。

        state 浅拷贝后推进；节点返回的增量 dict 逐键浅合并（后写胜出）。
        trace 形如 [{"step": 0, "node": "propose", "update_keys": [...]},
        ...]，与状态同回，供审计与 UI 消费。
        """
        cur: dict[str, Any] = dict(state or {})
        trace: list[dict[str, Any]] = []
        node = self._entry
        finished = False
        for step in range(int(max_steps)):
            self._emit(step, node, "node_started", cur)
            fn = self._nodes[node]
            update = fn(cur)
            update_keys: list[str] = []
            if isinstance(update, dict) and update:
                cur.update(update)
                update_keys = sorted(update)
            record = {"step": step, "node": node, "update_keys": update_keys}
            trace.append(record)
            nxt = self._next_of(node, cur)
            self._emit(step, node, "node_done", cur,
                       next_node=None if nxt == GRAPH_END else nxt)
            if nxt == GRAPH_END:
                finished = True
                break
            node = nxt
        cur["trace"] = trace
        cur["finished"] = finished
        cur["steps_used"] = len(trace)
        return cur

    # ── 内部 ─────────────────────────────────────────────────────────────
    def _next_of(self, node: str, state: dict[str, Any]) -> str:
        if node in self._routers:
            nxt = str(self._routers[node](state) or GRAPH_END)
        else:
            nxt = self._edges.get(node, GRAPH_END)
        if nxt != GRAPH_END and nxt not in self._nodes:
            raise GraphError(f"router 指向未注册节点: {node} → {nxt}")
        return nxt

    def _emit(self, step: int, node: str, phase: str,
              state: dict[str, Any], *, next_node: str | None = None) -> None:
        """观测 best-effort（#105）：事件总线不可用/异常不得阻塞图推进。"""
        with contextlib.suppress(Exception):
            get_event_bus().emit(Event(
                event_type=EventType.PROGRESS,
                run_id=str(state.get("run_id", "")),
                message=f"[agent_graph] step={step} node={node} {phase}",
                data={"step": step, "node": node, "phase": phase,
                      "next_node": next_node},
            ))
