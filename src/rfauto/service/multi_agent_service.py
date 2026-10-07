"""多 Agent 编排服务（WP3.8 三层栈·组装层）——评审/调优/验证分工端到端。

方案口径（续跑计划 §4 WP3.8 + 扩充提案 F1）：2025-26 收敛三层栈——
**LangGraph 式工作流状态机**（agent_graph，propose→verify→fix 自愈环的图
实现）+ **MCP 工具层**（agent_mcp_layer，同 mcp_server 生态标准工具协议的
进程内桥）+ **A2A 协议**（a2a_protocol，Agent 间互操作）——评审（reviewer）/
调优（tuner）/验证（verifier）三个角色 Agent 分工协作。

分工（数值铁律  规则 7：所有物理数字都出自确定性内核，角色只编排）：
- **调优 Agent（tuner）**：调内核 ``rf_propose_params``——初值=界中点；
  后续轮把 reviewer 的 typed fixes 落成候选参数（scale 修正 + 宽度组
  ±step 探测候选），本身不产生数字；
- **验证 Agent（verifier）**：调内核 ``rf_run_sampler``（注入的确定性
  采样器，真机即 autotune_service 同口径引擎采样器）逐候选取
  metrics/valley_ghz——唯一允许产数的环节；
- **评审 Agent（reviewer）**：调内核 ``rf_critique_point``（autotune_service
  确定性评判器）+ ``rf_spec_cost``（SpecEvaluator 加权 cost）逐测量评判，
  择 cost 最优者，裁决 PASS / FAIL，并定路由（继续调优 / 终止）；
  FAIL 如实上报，不凑绿（#122）。

三层如何咬合：图节点间不直接调函数，而是经 **A2A** 派 typed DataPart
消息给角色 Agent；角色 Agent 经 **MCP 工具层** 调确定性内核；**状态机**
只管控制流与护栏（max_steps / max_rounds）。
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.core.objectives import Objective, SpecEvaluator
from rfauto.service.a2a_protocol import (
    A2AMessage,
    A2ARegistry,
    A2ATask,
    AgentCard,
    AgentSkill,
    TaskState,
)
from rfauto.service.agent_graph import GRAPH_END, StateGraph
from rfauto.service.agent_mcp_layer import MCPToolLayer
from rfauto.service.autotune_service import critique_point
from rfauto.service.envelope import error_envelope, ok_envelope

SamplerFn = Callable[[dict[str, float]], dict[str, Any]]

#: 参数值统一 6 位小数（与 critique_point 的 round 口径一致，保逐字节可复现）。
_PARAM_DP = 6


# ─── 确定性内核（纯函数，可独立单测）─────────────────────────────────────────
def initial_proposal(bounds: dict[str, tuple[float, float]]) -> dict[str, float]:
    """初值 = 各参数界中点（确定性，无 LLM）。"""
    return {name: round((float(b[0]) + float(b[1])) / 2.0, _PARAM_DP)
            for name, b in (bounds or {}).items()}


def _clamp(name: str, value: float,
           bounds: dict[str, tuple[float, float]]) -> float:
    if name in bounds:
        return max(float(bounds[name][0]), min(float(bounds[name][1]), value))
    return value


def apply_fixes(
    params: dict[str, float],
    fixes: list[dict[str, Any]],
    bounds: dict[str, tuple[float, float]],
) -> tuple[dict[str, float], list[dict[str, float]], list[str]]:
    """typed fixes → (下一参数, 候选列表, 已应用类别)。

    - ``op=scale``（critique_point 的频率尺度修正，value=已算好的新值）：
      直接落值并限界；
    - ``op=coord_probe``（宽度组 RL 探测，value=步长比例）：对组内首个参数
      展开 ±step 两个候选（方向由评审面按 cost 择优，同 autotune 的坐标
      探测语义）；
    - 候选列表首元素恒为"仅 scale 修正"的基准候选，探测候选排后。
    """
    next_params = {k: float(v) for k, v in (params or {}).items()}
    candidates: list[dict[str, float]] = []
    applied: list[str] = []
    for f in fixes or []:
        op = str(f.get("op", ""))
        if op == "scale" and isinstance(f.get("param"), str):
            name = f["param"]
            if name in next_params:
                v = _clamp(name, float(f["value"]), bounds)
                next_params[name] = round(v, _PARAM_DP)
                applied.append("scale")
        elif op == "coord_probe":
            names = f.get("param") or []
            if isinstance(names, str):
                names = [names]
            step = abs(float(f.get("value", 0.1)))
            for name in names[:1]:
                if name not in next_params:
                    continue
                base = float(next_params[name])
                for sign in (1.0, -1.0):
                    v = _clamp(name, base * (1.0 + sign * step), bounds)
                    if round(v, _PARAM_DP) != round(base, _PARAM_DP):
                        cand = dict(next_params)
                        cand[name] = round(v, _PARAM_DP)
                        candidates.append(cand)
                applied.append("coord_probe")
    candidates.insert(0, dict(next_params))
    return next_params, candidates, sorted(set(applied))


def cost_of(metrics: dict[str, float], objectives: list[dict[str, Any]]) -> float:
    """SpecEvaluator 加权 cost（≥0，越小越好，0=全满足）。"""
    objs = [Objective(**o) for o in (objectives or [])]
    return float(SpecEvaluator.evaluate_objectives(
        {k: float(v) for k, v in (metrics or {}).items()}, objs))


def critique_measurement(
    metrics: dict[str, float],
    objectives: list[dict[str, Any]],
    *,
    valley_ghz: float | None = None,
    bounds: dict[str, tuple[float, float]] | None = None,
    current_params: dict[str, float] | None = None,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
) -> dict[str, Any]:
    """确定性评判（autotune_service.critique_point 的透传壳，便于 MCP 化）。"""
    return critique_point(
        {k: float(v) for k, v in (metrics or {}).items()},
        list(objectives or []),
        valley_ghz=valley_ghz,
        bounds=bounds,
        current_params=({k: float(v) for k, v in (current_params or {}).items()}
                        if current_params else None),
        f0_tolerance=f0_tolerance,
        rl_floor_db=rl_floor_db,
        max_step_pct=max_step_pct,
    )


# ─── MCP 工具层装配（第 2 层：内核 → 生态标准工具协议）───────────────────────
def build_tool_layer(
    sampler_fn: SamplerFn,
    *,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
) -> MCPToolLayer:
    """把三个确定性内核注册成 MCP 工具（tools/list + tools/call 契约）。"""
    layer = MCPToolLayer(server_name="rfauto-wp38-multi-agent")

    def propose(args: dict[str, Any]) -> dict[str, Any]:
        bounds = {k: (float(v[0]), float(v[1]))
                  for k, v in (args.get("bounds") or {}).items()}
        current = args.get("current_params")
        fixes = args.get("fixes") or []
        if current:
            nxt, cands, applied = apply_fixes(
                {k: float(v) for k, v in current.items()}, fixes, bounds)
        else:
            nxt = initial_proposal(bounds)
            cands, applied = [dict(nxt)], []
        return {"params": nxt, "candidates": cands, "applied_kinds": applied}

    layer.register(_mk_tool(
        "rf_propose_params",
        "调优内核：界中点初值 / typed fixes 落参 + 探测候选展开（无数字产出）",
        {
            "type": "object",
            "properties": {
                "bounds": {"type": "object"},
                "current_params": {"type": "object"},
                "fixes": {"type": "array"},
            },
            "required": ["bounds"],
        },
        propose))

    def run_sampler(args: dict[str, Any]) -> dict[str, Any]:
        params = {k: float(v) for k, v in (args.get("params") or {}).items()}
        out = sampler_fn(params)  # 注入的确定性采样器（真机=引擎采样器）
        if not isinstance(out, dict) or "metrics" not in out:
            raise ValueError("采样器契约：必须返回含 metrics 的 dict")
        return out

    layer.register(_mk_tool(
        "rf_run_sampler",
        "验证内核：params → {metrics, valley_ghz}（唯一产数环节，引擎采样器）",
        {
            "type": "object",
            "properties": {"params": {"type": "object",
                                       "additionalProperties": {"type": "number"}}},
            "required": ["params"],
        },
        run_sampler))

    layer.register(_mk_tool(
        "rf_critique_point",
        "评审内核：metrics+objectives(+谷位) → PASS/issues/typed fixes",
        {
            "type": "object",
            "properties": {
                "metrics": {"type": "object"},
                "objectives": {"type": "array"},
                "valley_ghz": {"type": ["number", "null"]},
                "bounds": {"type": "object"},
                "current_params": {"type": "object"},
            },
            "required": ["metrics", "objectives"],
        },
        lambda a: critique_measurement(
            a.get("metrics") or {}, a.get("objectives") or [],
            valley_ghz=a.get("valley_ghz"),
            bounds={k: (float(v[0]), float(v[1]))
                    for k, v in (a.get("bounds") or {}).items()} or None,
            current_params=a.get("current_params"),
            f0_tolerance=f0_tolerance, rl_floor_db=rl_floor_db,
            max_step_pct=max_step_pct)))

    layer.register(_mk_tool(
        "rf_spec_cost",
        "评审内核：SpecEvaluator 加权 cost（≥0，越小越好）",
        {
            "type": "object",
            "properties": {
                "metrics": {"type": "object"},
                "objectives": {"type": "array"},
            },
            "required": ["metrics", "objectives"],
        },
        lambda a: {"cost": cost_of(a.get("metrics") or {},
                                    a.get("objectives") or [])}))
    return layer


def _mk_tool(name: str, description: str, schema: dict[str, Any],
             handler: Callable[[dict[str, Any]], dict[str, Any]]):
    """构造 MCPTool（延迟导入供读者对齐；也便于未来拆分注册表）。"""
    from rfauto.service.agent_mcp_layer import MCPTool

    return MCPTool(name=name, description=description, input_schema=schema,
                   handler=handler)


# ─── A2A 角色 Agent（第 3 层：评审/调优/验证分工）────────────────────────────
def _card(name: str, description: str, skill_id: str, skill_name: str,
          skill_desc: str) -> AgentCard:
    return AgentCard(
        name=name, description=description,
        url=f"in-process://{name}",
        skills=[AgentSkill(id=skill_id, name=skill_name,
                           description=skill_desc,
                           tags=["rf", "wp38"])])


class TuningAgent:
    """调优 Agent：typed fixes → 候选参数（数字全部来自内核工具）。"""

    def __init__(self, tools: MCPToolLayer) -> None:
        self._tools = tools
        self.card = _card(
            "rf-tuner", "调优 Agent：出候选参数（typed，不产数）",
            "tuning.propose", "propose_params",
            "由界中点初值或 reviewer typed fixes 生成候选参数组")

    def handle(self, message: A2AMessage) -> A2ATask:
        task = A2ATask()
        task.transition(TaskState.WORKING)
        payload = (message.data_payloads() or [{}])[0]
        result = self._tools.call_tool("rf_propose_params", {
            "bounds": payload.get("bounds") or {},
            "current_params": payload.get("current_params"),
            "fixes": payload.get("fixes") or [],
        })
        if result.get("isError"):
            task.transition(TaskState.FAILED,
                            error=str(result.get("error", "rf_propose_params 失败")))
            return task
        out = result.get("structuredContent") or {}
        task.artifacts.append({
            "params": out.get("params") or {},
            "candidates": out.get("candidates") or [],
            "applied_kinds": out.get("applied_kinds") or [],
        })
        task.transition(TaskState.COMPLETED)
        return task


class VerifierAgent:
    """验证 Agent：逐候选调采样器内核取 metrics（唯一产数环节）。"""

    def __init__(self, tools: MCPToolLayer) -> None:
        self._tools = tools
        self.card = _card(
            "rf-verifier", "验证 Agent：确定性采样器取数",
            "verify.sample", "run_sampler",
            "逐候选 params 调 rf_run_sampler 取 metrics/valley_ghz")

    def handle(self, message: A2AMessage) -> A2ATask:
        task = A2ATask()
        task.transition(TaskState.WORKING)
        payload = (message.data_payloads() or [{}])[0]
        measurements: list[dict[str, Any]] = []
        for cand in payload.get("candidates") or []:
            res = self._tools.call_tool("rf_run_sampler", {"params": cand})
            if res.get("isError"):
                task.transition(TaskState.FAILED,
                                error=str(res.get("error", "rf_run_sampler 失败")))
                return task
            out = res.get("structuredContent") or {}
            measurements.append({
                "params": dict(cand),
                "metrics": out.get("metrics") or {},
                "valley_ghz": out.get("valley_ghz"),
            })
        task.artifacts.append({"measurements": measurements})
        task.transition(TaskState.COMPLETED)
        return task


class ReviewAgent:
    """评审 Agent：逐测量评判 → 择优 → 裁决与路由（FAIL 如实）。"""

    def __init__(self, tools: MCPToolLayer) -> None:
        self._tools = tools
        self.card = _card(
            "rf-reviewer", "评审 Agent：确定性评判与裁决",
            "review.judge", "judge",
            "rf_critique_point 逐测量评判 + rf_spec_cost 择优，产出裁决与路由")

    def handle(self, message: A2AMessage) -> A2ATask:
        task = A2ATask()
        task.transition(TaskState.WORKING)
        payload = (message.data_payloads() or [{}])[0]
        objectives = list(payload.get("objectives") or [])
        bounds = payload.get("bounds") or {}
        rounds = int(payload.get("rounds") or 0)
        max_rounds = int(payload.get("max_rounds") or 1)
        scored: list[dict[str, Any]] = []
        for m in payload.get("measurements") or []:
            critique = self._tools.call_tool("rf_critique_point", {
                "metrics": m.get("metrics") or {}, "objectives": objectives,
                "valley_ghz": m.get("valley_ghz"), "bounds": bounds,
                "current_params": m.get("params"),
            })
            if critique.get("isError"):
                task.transition(TaskState.FAILED, error=str(
                    critique.get("error", "rf_critique_point 失败")))
                return task
            cost = self._tools.call_tool("rf_spec_cost", {
                "metrics": m.get("metrics") or {}, "objectives": objectives,
            })
            if cost.get("isError"):
                task.transition(TaskState.FAILED, error=str(
                    cost.get("error", "rf_spec_cost 失败")))
                return task
            scored.append({
                "measurement": m,
                "critique": critique.get("structuredContent") or {},
                "cost": float((cost.get("structuredContent") or {}).get("cost", 0.0)),
            })
        if not scored:
            task.transition(TaskState.FAILED, error="无测量可评审")
            return task
        best = min(scored, key=lambda s: s["cost"])  # 平局取序（确定性）
        best_m = best["measurement"]
        critique = best["critique"]
        verdict = str(critique.get("verdict", "FAIL"))
        fixes = list(critique.get("fixes") or [])
        route = "tune"
        reason = ""
        if verdict == "PASS":
            route, reason = "END", "评审通过"
        elif rounds >= max_rounds:
            route, reason = "END", f"轮次预算用尽（{rounds}/{max_rounds}），如实 FAIL"
        elif not fixes:
            route, reason = "END", "FAIL 且无可执行 typed fixes，终止（不空转）"
        task.artifacts.append({
            "verdict": verdict,
            "route": route,
            "reason": reason,
            "best_index": scored.index(best),
            "params": best_m.get("params") or {},
            "metrics": best_m.get("metrics") or {},
            "valley_ghz": best_m.get("valley_ghz"),
            "cost": best["cost"],
            "critique": critique,
            "fixes": fixes,
            "rounds": rounds,
            "all_costs": [s["cost"] for s in scored],
        })
        task.transition(TaskState.COMPLETED)
        return task


# ─── 端到端编排（第 1 层图驱动 + 三层咬合）───────────────────────────────────
def run_review_tune_verify(
    bounds: dict[str, tuple[float, float]],
    objectives: list[dict[str, Any]],
    sampler_fn: SamplerFn,
    *,
    max_rounds: int = 4,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
    run_id: str = "",
) -> dict[str, Any]:
    """评审/调优/验证分工的端到端一例（确定性，离线可复现）。

    图：``tune → verify → review →（PASS/终止？END : tune）``，护栏
    max_rounds（评审面轮次预算）+ 图级 max_steps（agent_graph 默认）。
    返回 JSON 安全 dict：verdict/params/metrics/history/trace + 三层审计面
    （a2a 卡与任务转录、mcp 工具表）。
    """
    tools = build_tool_layer(
        sampler_fn, f0_tolerance=f0_tolerance, rl_floor_db=rl_floor_db,
        max_step_pct=max_step_pct)
    registry = A2ARegistry()
    registry.register(TuningAgent(tools))
    registry.register(VerifierAgent(tools))
    registry.register(ReviewAgent(tools))
    transcript: list[dict[str, Any]] = []

    def dispatch(role: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """A2A 派发 + 转录（图节点间唯一通信方式）。"""
        task = registry.dispatch(role, A2AMessage.with_data("user", payload))
        transcript.append({"agent": role, "task": task.to_dict()})
        if task.state == TaskState.FAILED:
            return "failed", {"error": task.error}
        return "ok", (task.artifacts[0] if task.artifacts else {})

    def node_tune(state: dict[str, Any]) -> dict[str, Any]:
        status, art = dispatch("rf-tuner", {
            "bounds": {k: list(v) for k, v in (state["bounds"]).items()},
            "current_params": state.get("params"),
            "fixes": state.get("fixes") or [],
        })
        if status == "failed":
            return {"verdict": "ERROR", "route": "END", "error": art["error"]}
        update: dict[str, Any] = {"params": art["params"],
                                  "candidates": art["candidates"],
                                  "applied_kinds": art["applied_kinds"]}
        if state.get("fixes"):
            update["rounds"] = int(state.get("rounds", 0)) + 1
        return update

    def node_verify(state: dict[str, Any]) -> dict[str, Any]:
        if state.get("verdict") == "ERROR":  # 上游执行错误：透传不掩盖
            return {}
        status, art = dispatch("rf-verifier",
                               {"candidates": state.get("candidates") or []})
        if status == "failed":
            return {"verdict": "ERROR", "route": "END", "error": art["error"]}
        return {"measurements": art["measurements"]}

    def node_review(state: dict[str, Any]) -> dict[str, Any]:
        if state.get("verdict") == "ERROR":  # 上游执行错误：透传不掩盖
            return {"route": "END"}
        status, art = dispatch("rf-reviewer", {
            "measurements": state.get("measurements") or [],
            "objectives": state["objectives"],
            "bounds": {k: list(v) for k, v in state["bounds"].items()},
            "rounds": int(state.get("rounds", 0)),
            "max_rounds": int(state["max_rounds"]),
        })
        if status == "failed":
            return {"verdict": "ERROR", "route": "END", "error": art["error"]}
        history = list(state.get("history") or [])
        fix_kinds = [str(f.get("kind", "")) for f in (art.get("fixes") or [])]
        history.append({
            "round": int(state.get("rounds", 0)),
            "params": art["params"], "metrics": art["metrics"],
            "valley_ghz": art["valley_ghz"], "cost": art["cost"],
            "verdict": art["verdict"], "fix_kinds": fix_kinds,
        })
        return {"verdict": art["verdict"], "route": art["route"],
                "reason": art["reason"], "params": art["params"],
                "metrics": art["metrics"], "valley_ghz": art["valley_ghz"],
                "cost": art["cost"], "fixes": art["fixes"],
                "history": history}

    def router(state: dict[str, Any]) -> str:
        if state.get("route") == "END":
            return GRAPH_END
        return "tune"

    graph = (StateGraph()
             .add_node("tune", node_tune)
             .add_node("verify", node_verify)
             .add_node("review", node_review)
             .set_entry_point("tune")
             .add_edge("tune", "verify")
             .add_edge("verify", "review")
             .add_conditional_edge("review", router)
             .compile())

    init_state: dict[str, Any] = {
        "run_id": str(run_id),
        "bounds": {k: (float(v[0]), float(v[1])) for k, v in bounds.items()},
        "objectives": [dict(o) for o in objectives],
        "max_rounds": int(max_rounds),
        "rounds": 0,
        "history": [],
    }
    final = graph.invoke(init_state)
    verdict = str(final.get("verdict", "ERROR"))
    return {
        "ok": verdict != "ERROR",
        "verdict": verdict,
        "reason": str(final.get("reason", "")),
        "rounds": int(final.get("rounds", 0)),
        "params": final.get("params") or {},
        "metrics": final.get("metrics") or {},
        "valley_ghz": final.get("valley_ghz"),
        "cost": final.get("cost"),
        "history": final.get("history") or [],
        "graph": {"nodes": graph.node_names(),
                  "trace": final.get("trace") or [],
                  "steps_used": int(final.get("steps_used", 0)),
                  "finished": bool(final.get("finished"))},
        "a2a": {"cards": registry.list_agent_cards(),
                "tasks": transcript,
                "protocol_version": "0.2"},
        "mcp": {"server": tools.server_name,
                "tools": tools.list_tools()},
        "error": str(final.get("error", "")),
    }


# ─── JSON 进出入口（CLI/MCP 薄壳消费；0bt① followUp：4 内核工具 + 端到端）───
KERNEL_TOOL_NAMES: tuple[str, ...] = (
    "rf_propose_params", "rf_run_sampler", "rf_critique_point", "rf_spec_cost")


def _recipe_context(recipe_path: Any) -> dict[str, Any]:
    """配方 → {ok, model, bounds, objectives, freq_range_ghz}（同 autotune 口径）。"""
    from pathlib import Path

    import yaml

    path = Path(str(recipe_path))
    if not path.exists():
        return error_envelope([f"配方不存在: {path}"])
    with open(path, encoding="utf-8") as f:
        recipe = yaml.safe_load(f) or {}
    opt = recipe.get("optimization") or {}
    try:
        bounds = {k: (float(v["low"]), float(v["high"]))
                  for k, v in (opt.get("params") or {}).items()}
    except (KeyError, TypeError, ValueError) as exc:
        return error_envelope([f"optimization.params 形状非法: {exc}"])
    if not bounds:
        return error_envelope(["配方无 optimization.params，无搜索空间"])
    objectives = list(recipe.get("objectives") or [])
    if not objectives:
        return error_envelope(["配方无 objectives，无从评判"])
    freq_range = tuple((recipe.get("setup") or {}).get("freq_range_ghz", (1.0, 5.0)))
    return ok_envelope(
        model=str(recipe.get("model", "")),
        bounds=bounds,
        objectives=objectives,
        freq_range_ghz=freq_range,
        recipe=recipe,
        path=str(path),
    )


def make_recipe_sampler(recipe_path: Any, *,
                        mesh_resolution_mm: float = 0.0) -> SamplerFn:
    """配方 → 真机 openEMS 快验证采样器（autotune_service 同口径，串行纪律）。

    只在 verifier 真要产数时才构造（延迟到调用点）；测试/离线用注入的
    sampler_fn 代替（#139 零真机）。
    """
    from pathlib import Path

    from rfauto.core.state import generate_run_id
    from rfauto.service.autotune_service import _make_openems_sampler

    ctx = _recipe_context(recipe_path)
    if not ctx.get("ok"):
        raise ValueError("; ".join(ctx.get("errors") or ["配方不可用"]))
    return _make_openems_sampler(
        ctx["model"], tuple(ctx["freq_range_ghz"]), ctx["objectives"],
        mesh_resolution_mm=float(mesh_resolution_mm),
        work_root=Path("runs") / f"multi_agent_work_{generate_run_id()}")


def _no_sampler(_params: dict[str, float]) -> dict[str, Any]:
    raise RuntimeError(
        "rf_run_sampler 需要采样器：注入 sampler_fn 或给 recipe_path（真机 openEMS）")


def call_kernel_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    sampler_fn: SamplerFn | None = None,
    recipe_path: Any | None = None,
    mesh_resolution_mm: float = 0.0,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
) -> dict[str, Any]:
    """MCP 工具层单次 tools/call（JSON 进出；薄壳零逻辑转发点）。

    - rf_propose_params / rf_critique_point / rf_spec_cost：纯确定性内核，
      无需采样器；
    - rf_run_sampler：唯一产数环节——用注入的 sampler_fn，否则按
      recipe_path 构造真机 openEMS 采样器；两者皆无则 ok=False 显式报错。
    返回 {ok, tool, result} 或 {ok: False, tool, errors}（isError 折入，不抛）。
    """
    from rfauto.service.agent_mcp_layer import unwrap_tool_result

    tool = str(name)
    if tool not in KERNEL_TOOL_NAMES:
        return {"ok": False, "tool": tool,
                "errors": [f"未知内核工具: {tool}（可用: {list(KERNEL_TOOL_NAMES)}）"]}
    sampler = sampler_fn
    if tool == "rf_run_sampler" and sampler is None:
        if recipe_path is None:
            return {"ok": False, "tool": tool, "errors": [
                "rf_run_sampler 需要 sampler_fn 或 recipe_path（真机 openEMS 采样器）"]}
        try:
            sampler = make_recipe_sampler(recipe_path,
                                          mesh_resolution_mm=mesh_resolution_mm)
        except Exception as exc:
            return {"ok": False, "tool": tool, "errors": [str(exc)]}
    layer = build_tool_layer(
        sampler or _no_sampler, f0_tolerance=f0_tolerance,
        rl_floor_db=rl_floor_db, max_step_pct=max_step_pct)
    wire = layer.call_tool(tool, dict(arguments or {}))
    if wire.get("isError"):
        return {"ok": False, "tool": tool, "errors": [str(wire.get("error", ""))]}
    return ok_envelope(tool=tool, result=unwrap_tool_result(wire))


def multi_agent_run(
    recipe_path: Any,
    *,
    sampler_fn: SamplerFn | None = None,
    max_rounds: int = 4,
    mesh_resolution_mm: float = 0.0,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
) -> dict[str, Any]:
    """配方驱动的评审/调优/验证端到端（JSON 进出；CLI/MCP 薄壳入口）。

    bounds/objectives 取自配方（optimization.params / objectives）；采样器
    缺省为真机 openEMS 快验证通道（串行纪律），测试注入 sampler_fn。
    返回 run_review_tune_verify 的 JSON 记录 + recipe/model 来源字段。
    """
    ctx = _recipe_context(recipe_path)
    if not ctx.get("ok"):
        return ctx
    sampler = sampler_fn
    if sampler is None:
        try:
            sampler = make_recipe_sampler(recipe_path,
                                          mesh_resolution_mm=mesh_resolution_mm)
        except Exception as exc:
            return error_envelope([f"采样器构造失败: {exc}"])
    from rfauto.core.state import generate_run_id

    run_id = generate_run_id()
    result = run_review_tune_verify(
        ctx["bounds"], ctx["objectives"], sampler,
        max_rounds=int(max_rounds), f0_tolerance=f0_tolerance,
        rl_floor_db=rl_floor_db, max_step_pct=max_step_pct, run_id=run_id)
    result["run_id"] = run_id
    result["recipe"] = ctx["path"]
    result["model"] = ctx["model"]
    return result


# ═══ DS-4 agentTeams 样板（experimental，2026-10-05 Phase 5 W5-C）══════════════
#
# dsh subsystems/agent-team 的模式移植（**experimental**：采纳模式与不变量，
# 不锁框架；形态未定前不做 MCP/CLI 消费面）。在本模块既有三层栈（图状态机/
# MCP 工具层/A2A 角色）之上叠三件：
# - **roster 持久化**：runs/agent_teams/<team_id>.json（席位/角色/状态，
#   schema=rfauto-agent-team-v1）——跨进程存续，存续语义与 goal 域同款
#   （原子替换；显式 root > 环境变量 RFAUTO_AGENT_TEAMS_DIR > cwd 相对
#   runs/agent_teams）；
# - **mailbox 解耦**：席位间消息队列面（TeamMailbox，纯内存 FIFO+可选
#   jsonl 落盘审计）——席位间不再直接递引用，通信只经消息（与 A2A 派发
#   契约一致：图节点间不直接调函数）；
# - **任务板可视**：team_board 状态摘要信封（席位态/在飞/排队/邮箱积压
#   一屏读）。
#
# 调度形式化＝**合成 scheduler 面**（TeamScheduler，有界并发）：7 子代理
# 排满/结束即派（submit 时槽满入队、complete 后立即补位派发队头）——
# executor 与 clock 全部注入（mock executor 只记录调用，**零真模型调用**，
# #139；合成时钟单测定序，零线程零 sleep，确定性可复现）。缺省并发帽
# TEAM_MAX_ACTIVE=7（dsh 七席位惯例；帽值显式传参可调）。
#
# 铁律 7：本节零数值面——席位/调度/信箱只编排，物理数字仍只出自上方
# 三层栈的确定性内核工具（rf_run_sampler 唯一产数环节）。

#: agentTeams 持久化文件 schema 版本。
AGENT_TEAM_SCHEMA = "rfauto-agent-team-v1"

#: agentTeams 目录根的环境变量覆盖名（显式 root 参数优先于此）。
TEAMS_DIR_ENV = "RFAUTO_AGENT_TEAMS_DIR"

#: 缺省有界并发帽（7 子代理排满；dsh 七席位惯例）。
TEAM_MAX_ACTIVE = 7

#: 席位状态词表（roster 持久化与调度面共用；词表外拒收）。
SEAT_STATUSES: tuple[str, ...] = ("idle", "working", "done", "failed")

#: 任务状态词表（scheduler 面；与席位状态解耦——任务终态≠席位终态）。
TASK_STATUSES: tuple[str, ...] = ("queued", "working", "done", "failed")


def teams_root(root: str | Path | None = None) -> Path:
    """teams 目录根解析：显式 > 环境变量 > cwd 相对 runs/agent_teams。"""
    import os

    if root is not None:
        return Path(root)
    env = os.environ.get(TEAMS_DIR_ENV, "").strip()
    if env:
        return Path(env)
    return Path("runs") / "agent_teams"


def team_path(team_id: str, root: str | Path | None = None) -> Path:
    """team_id → roster 持久化路径（teams_root/<team_id>.json）。"""
    return teams_root(root) / f"{team_id}.json"


def _validate_team_id(team_id: str) -> str | None:
    """team_id 白名单校验（防路径穿越/非法文件名字符，同 goal 域口径）。"""
    tid = str(team_id or "").strip()
    if not tid or len(tid) > 120:
        return None
    if any(ch in tid for ch in "\\/:*?\"<>|"):
        return None
    if tid in (".", "..") or tid.startswith("."):
        return None
    return tid


def _atomic_write_json_file(path: Path, record: dict[str, Any]) -> None:
    """原子替换落盘（goal_domain/campaign_manager 同款，防 kill 截断）。"""
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True,
                   default=str),
        encoding="utf-8")
    os.replace(tmp, path)


def create_team(
    team_id: str,
    seats: list[dict[str, Any]],
    *,
    description: str = "",
    root: str | Path | None = None,
) -> dict[str, Any]:
    """立 agentTeam roster 并持久化（runs/agent_teams/<team_id>.json）。

    seats 契约：``[{"seat_id": str, "role": str}, ...]``（status 缺省
    idle）；seat_id 必须唯一非空。**experimental**：本域形态未定，信封
    与持久化文件均带 experimental 标记。
    """
    tid = _validate_team_id(team_id)
    if tid is None:
        return error_envelope(
            [f"team_id 非法（禁路径分隔符/点前缀，长度≤120）: {team_id!r}"])
    if not isinstance(seats, list) or not seats:
        return error_envelope(["seats 必须为非空列表（席位/角色/状态）"])
    seen: set[str] = set()
    roster_seats: list[dict[str, Any]] = []
    for seat in seats:
        if not isinstance(seat, dict):
            return error_envelope([f"席位项必须是对象: {seat!r}"])
        sid = str(seat.get("seat_id") or "").strip()
        role = str(seat.get("role") or "").strip()
        if not sid or sid in seen:
            return error_envelope(
                [f"席位 seat_id 必须唯一非空: {sid!r}（重复或空）"])
        seen.add(sid)
        roster_seats.append({
            "seat_id": sid,
            "role": role,
            "status": "idle",
        })
    record: dict[str, Any] = {
        "schema": AGENT_TEAM_SCHEMA,
        "team_id": tid,
        "description": str(description or ""),
        "experimental": True,
        "seats": roster_seats,
        "created_at": _team_now_iso(),
        "updated_at": _team_now_iso(),
    }
    path = team_path(tid, root)
    _atomic_write_json_file(path, record)
    return ok_envelope(experimental=True, team_id=tid, path=str(path),
                       n_seats=len(roster_seats), team=record)


def _team_now_iso() -> str:
    from datetime import datetime as _dt

    return _dt.now().isoformat(timespec="seconds")


def get_team(team_id: str, root: str | Path | None = None) -> dict[str, Any]:
    """读 roster（跨进程存续查询口；不存在/损坏/schema 不符如实失败）。"""
    tid = _validate_team_id(team_id)
    if tid is None:
        return error_envelope([f"team_id 非法: {team_id!r}"])
    path = team_path(tid, root)
    if not path.is_file():
        return error_envelope(
            [f"agentTeam roster 不存在: {path}（先 create_team 落盘）"])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return error_envelope([f"roster 不可读: {exc}"])
    if not isinstance(data, dict) or data.get("schema") != AGENT_TEAM_SCHEMA:
        return error_envelope(
            [f"roster schema 不符: {path}（期望 {AGENT_TEAM_SCHEMA}）"])
    return ok_envelope(experimental=True, team_id=tid, path=str(path),
                       team=data)


def save_team(record: dict[str, Any], root: str | Path | None = None) -> dict[str, Any]:
    """回写 roster（席位状态流转出口；schema 校验+updated_at 刷新）。"""
    tid = _validate_team_id(str(record.get("team_id") or ""))
    if tid is None:
        return error_envelope(["roster 记录缺合法 team_id，拒收回写"])
    seats = record.get("seats")
    if not isinstance(seats, list) or not seats:
        return error_envelope(["roster.seats 必须为非空列表"])
    for seat in seats:
        status = str((seat or {}).get("status") or "")
        if status not in SEAT_STATUSES:
            return error_envelope(
                [f"席位状态非法: {status!r}（词表 {list(SEAT_STATUSES)}）"])
    out = dict(record)
    out["schema"] = AGENT_TEAM_SCHEMA
    out["experimental"] = True
    out["updated_at"] = _team_now_iso()
    path = team_path(tid, root)
    _atomic_write_json_file(path, out)
    return ok_envelope(experimental=True, team_id=tid, path=str(path),
                       team=out)


def set_seat_status(
    team_id: str,
    seat_id: str,
    status: str,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """席位状态流转（词表 SEAT_STATUSES；roster 落盘后返回新记录）。"""
    if status not in SEAT_STATUSES:
        return error_envelope(
            [f"席位状态非法: {status!r}（词表 {list(SEAT_STATUSES)}）"])
    loaded = get_team(team_id, root)
    if not loaded.get("ok"):
        return loaded
    team = loaded["team"]
    seat = next((s for s in team.get("seats") or []
                 if str(s.get("seat_id")) == str(seat_id)), None)
    if seat is None:
        return error_envelope(
            [f"席位不存在: {seat_id!r}（team={team_id}）"])
    seat["status"] = status
    return save_team(team, root)


# ─── mailbox（席位间消息队列面；纯内存 FIFO+可选 jsonl 落盘审计）──────────────

class TeamMailbox:
    """席位间信箱（experimental）：每席位一条 FIFO 队列，纯内存。

    - ``send(to_seat, payload, ...)``：入队+序号自增（每席位独立计数，
      确定性）；``spill_dir`` 给定时同步追加 jsonl 行（审计副本，写失败
      **不阻塞**主路径——观测面 best-effort，#105）；
    - ``recv(seat)``：FIFO 取队首（空返回 None，不抛）；
    - ``pending(seat) / pending_all()``：积压计数（任务板消费）。

    零线程零锁：单进程编排面内使用（跨进程协调走 runs 落盘面，不在本类
    职责内——mailbox 是解耦**消息面**，不是 IPC 基座）。
    """

    def __init__(self, *, spill_dir: str | Path | None = None) -> None:
        self._queues: dict[str, deque] = {}
        self._seq: dict[str, int] = {}
        self.spill_dir = Path(spill_dir) if spill_dir is not None else None

    def send(self, to_seat: str, payload: dict[str, Any], *,
             from_seat: str = "", kind: str = "") -> dict[str, Any]:
        """入队一条消息（FIFO 尾插；返回带 seq 的消息回执）。"""
        seat = str(to_seat or "").strip()
        if not seat:
            return error_envelope(["send 缺 to_seat（消息必须有收席）"])
        self._seq[seat] = self._seq.get(seat, 0) + 1
        message = {
            "seq": self._seq[seat],
            "from_seat": str(from_seat or ""),
            "kind": str(kind or ""),
            "payload": payload if isinstance(payload, dict) else {"value": payload},
        }
        self._queues.setdefault(seat, deque()).append(message)
        self._spill(seat, message)
        return ok_envelope(experimental=True, to_seat=seat,
                           seq=message["seq"])

    def _spill(self, seat: str, message: dict[str, Any]) -> None:
        """审计落盘副本（best-effort #105：失败不阻塞消息主路径）。"""
        if self.spill_dir is None:
            return
        try:
            self.spill_dir.mkdir(parents=True, exist_ok=True)
            path = self.spill_dir / f"mailbox_{seat}.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(message, ensure_ascii=False,
                                   sort_keys=True, default=str) + "\n")
        except OSError:
            pass

    def recv(self, seat: str) -> dict[str, Any] | None:
        """FIFO 取队首消息（空队列返回 None——调用方如实判空）。"""
        queue = self._queues.get(str(seat or ""))
        if not queue:
            return None
        return queue.popleft()

    def pending(self, seat: str) -> int:
        """单席位积压数。"""
        return len(self._queues.get(str(seat or "")) or ())

    def pending_all(self) -> dict[str, int]:
        """全席位积压计数（任务板摘要消费）。"""
        return {seat: len(q) for seat, q in sorted(self._queues.items()) if q}


# ─── 合成 scheduler 面（有界并发：排满入队/结束即派；mock executor 注入）──────

def _default_mock_executor(task: dict[str, Any]) -> dict[str, Any]:
    """缺省 mock 执行器（#139 零真模型）：只回执不干活。

    生产/测试一律**显式注入** executor（记录调用或编排真实子代理面）；
    未注入时用本 mock 显式暴露"没有真实执行器"（回执 executor=mock，
    不静默假装执行；无 ok 键=派发面按成功缺省消费，_dispatch 同款）。
    """
    return {"executor": "mock", "task_id": task.get("task_id")}


class TeamScheduler:
    """有界并发合成调度面（experimental）：7 槽排满入队、结束即派补位。

    调度语义（确定性，零线程零 sleep——"并发"由任务状态刻画，"结束"由
    ``complete`` 显式声明，合成时钟定序）：
    - ``submit(task_id, payload, seat_id=...)``：在飞 < max_active 时立即
      派发（executor 调用一次+席位 hook working）；满则入队（executor
      **不**调用，任务态 queued）；
    - ``complete(task_id, ok=True)``：任务终态落账+席位 hook done/failed，
      然后立即补位——队列头依次派发直至在飞重达帽值或队空（结束即派）；
    - ``snapshot()``：{n_active, n_queued, n_done, n_failed, active,
      queued, done, failed}（任务板消费）。

    executor 契约：``(task) -> dict``——mock 注入只记录调用（#139 零真
    模型）；executor 抛异常=该任务 failed（如实落账，队列继续补位）。
    clock 契约：``() -> float``（缺省 time.monotonic；测试注入合成时钟）。
    seat_hook 契约：``(seat_id, status) -> None``（roster 流转钩子，可选）。
    """

    def __init__(
        self,
        *,
        max_active: int = TEAM_MAX_ACTIVE,
        executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        clock: Callable[[], float] | None = None,
        seat_hook: Callable[[str, str], None] | None = None,
    ) -> None:
        if not isinstance(max_active, int) or isinstance(max_active, bool) \
                or max_active < 1:
            raise ValueError(f"max_active 必须为正整数: {max_active!r}")
        self.max_active = int(max_active)
        self._executor = executor if executor is not None \
            else _default_mock_executor
        self._clock = clock if clock is not None else time.monotonic
        self._seat_hook = seat_hook
        self._tasks: dict[str, dict[str, Any]] = {}
        self._queue: list[str] = []
        self._submit_seq = 0

    # -- 内部 ------------------------------------------------------------
    def _dispatch(self, task_id: str) -> None:
        task = self._tasks[task_id]
        task["status"] = "working"
        task["dispatched_at"] = float(self._clock())
        if self._seat_hook is not None and task.get("seat_id"):
            self._seat_hook(str(task["seat_id"]), "working")
        try:
            result = self._executor(dict(task))
            task["executor_ok"] = bool(result.get("ok", True))
        except Exception as exc:  # executor 异常=任务失败（如实落账不吞）
            task["executor_error"] = str(exc)

    def _settle(self, task_id: str, ok: bool) -> None:
        task = self._tasks[task_id]
        task["status"] = "done" if ok else "failed"
        task["completed_at"] = float(self._clock())
        if self._seat_hook is not None and task.get("seat_id"):
            self._seat_hook(str(task["seat_id"]), "done" if ok else "failed")

    def _refill(self) -> None:
        """结束即派：队列头补位直至在飞重达帽值或队空（确定性顺序）。"""
        while self._queue and self.n_active < self.max_active:
            task_id = self._queue.pop(0)
            self._dispatch(task_id)

    # -- 公开面 ------------------------------------------------------------
    @property
    def n_active(self) -> int:
        return sum(1 for t in self._tasks.values()
                   if t.get("status") == "working")

    def submit(self, task_id: str, payload: dict[str, Any], *,
               seat_id: str = "") -> dict[str, Any]:
        """提交任务（槽满入队返回 queued；有空槽立即派发返回 working）。"""
        tid = str(task_id or "").strip()
        if not tid:
            return error_envelope(["submit 缺 task_id"])
        if tid in self._tasks or tid in self._queue:
            return error_envelope([f"任务 id 重复: {tid!r}"])
        self._submit_seq += 1
        task: dict[str, Any] = {
            "task_id": tid,
            "seq": self._submit_seq,
            "seat_id": str(seat_id or ""),
            "payload": payload if isinstance(payload, dict) else {},
            "submitted_at": float(self._clock()),
            "status": "queued",
        }
        self._tasks[tid] = task
        if self.n_active < self.max_active:
            self._dispatch(tid)
            return ok_envelope(experimental=True, task_id=tid,
                               status="working", n_active=self.n_active,
                               n_queued=len(self._queue))
        self._queue.append(tid)
        return ok_envelope(experimental=True, task_id=tid, status="queued",
                           n_active=self.n_active, n_queued=len(self._queue))

    def complete(self, task_id: str, *, ok: bool = True) -> dict[str, Any]:
        """声明任务结束并立即补位派发（结束即派；幂等拒绝重复终态）。"""
        tid = str(task_id or "").strip()
        task = self._tasks.get(tid)
        if task is None:
            return error_envelope([f"任务不存在: {tid!r}"])
        if task.get("status") not in ("working", "queued"):
            return error_envelope(
                [f"任务已终态（{task.get('status')}），拒绝重复 complete: {tid!r}"])
        if task.get("status") == "queued":
            # 未派发先完成（例如被取消）：从队列摘除后直接落终态
            self._queue.remove(tid)
            self._settle(tid, ok)
            return ok_envelope(experimental=True, task_id=tid,
                               status=task["status"], n_active=self.n_active,
                               n_queued=len(self._queue), refilled=0)
        self._settle(tid, ok)
        before = len(self._queue)
        self._refill()
        return ok_envelope(experimental=True, task_id=tid,
                           status=task["status"], n_active=self.n_active,
                           n_queued=len(self._queue),
                           refilled=before - len(self._queue))

    def snapshot(self) -> dict[str, Any]:
        """调度面状态快照（任务板/单测消费；键确定性排序）。"""
        active = sorted(tid for tid, t in self._tasks.items()
                        if t.get("status") == "working")
        queued = list(self._queue)
        done = sorted(tid for tid, t in self._tasks.items()
                      if t.get("status") == "done")
        failed = sorted(tid for tid, t in self._tasks.items()
                        if t.get("status") == "failed")
        return {
            "max_active": self.max_active,
            "n_active": len(active),
            "n_queued": len(queued),
            "n_done": len(done),
            "n_failed": len(failed),
            "active": active,
            "queued": queued,
            "done": done,
            "failed": failed,
        }


# ─── 任务板可视（状态摘要信封；experimental 字段随信封出）────────────────────

def team_board(
    team_id: str,
    *,
    root: str | Path | None = None,
    mailbox: TeamMailbox | None = None,
    scheduler: TeamScheduler | None = None,
) -> dict[str, Any]:
    """agentTeam 任务板（一屏状态摘要；**experimental** 信封）。

    roster 持久化记录（席位/角色/状态）为基底；给定 mailbox/scheduler
    时合并邮箱积压与调度面快照（不落盘，纯读视图）。零数值面：计数与
    状态词表外的数字一概不产出。
    """
    loaded = get_team(team_id, root)
    if not loaded.get("ok"):
        return loaded
    team = loaded["team"]
    seats = [dict(s) for s in team.get("seats") or []]
    summary: dict[str, Any] = {
        "n_seats": len(seats),
        "n_idle": sum(1 for s in seats if s.get("status") == "idle"),
        "n_working": sum(1 for s in seats if s.get("status") == "working"),
        "n_done": sum(1 for s in seats if s.get("status") == "done"),
        "n_failed": sum(1 for s in seats if s.get("status") == "failed"),
    }
    if mailbox is not None:
        summary["mailbox_pending"] = mailbox.pending_all()
    if scheduler is not None:
        snap = scheduler.snapshot()
        summary["scheduler"] = {
            k: snap[k] for k in ("max_active", "n_active", "n_queued",
                                 "n_done", "n_failed")}
        summary["scheduler_active"] = snap["active"]
        summary["scheduler_queued"] = snap["queued"]
    return ok_envelope(
        experimental=True, team_id=team_id, path=loaded.get("path"),
        description=team.get("description", ""),
        seats=seats, summary=summary)
