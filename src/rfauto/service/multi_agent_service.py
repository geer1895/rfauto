"""多 Agent 编排服务（WP3.8 三层栈·组装层）——评审/调优/验证分工端到端。

方案口径（2025-26 收敛三层栈）——
**LangGraph 式工作流状态机**（agent_graph，propose→verify→fix 自愈环的图
实现）+ **MCP 工具层**（agent_mcp_layer，同 mcp_server 生态标准工具协议的
进程内桥）+ **A2A 协议**（a2a_protocol，Agent 间互操作）——评审（reviewer）/
调优（tuner）/验证（verifier）三个角色 Agent 分工协作。

分工（数值铁律：所有物理数字都出自确定性内核，角色只编排）：
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

from collections.abc import Callable
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


# ─── JSON 进出入口（CLI/MCP 薄壳消费；4 内核工具 + 端到端）───
KERNEL_TOOL_NAMES: tuple[str, ...] = (
    "rf_propose_params", "rf_run_sampler", "rf_critique_point", "rf_spec_cost")


def _recipe_context(recipe_path: Any) -> dict[str, Any]:
    """配方 → {ok, model, bounds, objectives, freq_range_ghz}（同 autotune 口径）。"""
    from pathlib import Path

    import yaml

    path = Path(str(recipe_path))
    if not path.exists():
        return {"ok": False, "errors": [f"配方不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe = yaml.safe_load(f) or {}
    opt = recipe.get("optimization") or {}
    try:
        bounds = {k: (float(v["low"]), float(v["high"]))
                  for k, v in (opt.get("params") or {}).items()}
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "errors": [f"optimization.params 形状非法: {exc}"]}
    if not bounds:
        return {"ok": False, "errors": ["配方无 optimization.params，无搜索空间"]}
    objectives = list(recipe.get("objectives") or [])
    if not objectives:
        return {"ok": False, "errors": ["配方无 objectives，无从评判"]}
    freq_range = tuple((recipe.get("setup") or {}).get("freq_range_ghz", (1.0, 5.0)))
    return {"ok": True, "model": str(recipe.get("model", "")), "bounds": bounds,
            "objectives": objectives, "freq_range_ghz": freq_range,
            "recipe": recipe, "path": str(path)}


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
    return {"ok": True, "tool": tool, "result": unwrap_tool_result(wire)}


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
            return {"ok": False, "errors": [f"采样器构造失败: {exc}"]}
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
