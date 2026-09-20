"""WP3.8 多 Agent 编排三层栈单测（agent_graph / agent_mcp_layer /
a2a_protocol / multi_agent_service）。

口径：LangGraph 式状态机 + MCP 工具层 +
A2A 协议，评审/调优/验证分工端到端 1 例。全部离线确定性（注入闭式解析
采样器，零真机、零 LLM、零网络）；数值只出自确定性内核。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.service.a2a_protocol import (
    A2AError,
    A2AMessage,
    A2ARegistry,
    A2ATask,
    AgentCard,
    AgentSkill,
    DataPart,
    TaskState,
    TextPart,
    can_transition,
)
from rfauto.service.agent_graph import (
    GRAPH_END,
    GraphError,
    StateGraph,
)
from rfauto.service.agent_mcp_layer import (
    MCPTool,
    MCPToolLayer,
    tool_spec_to_mcp,
    unwrap_tool_result,
)
from rfauto.service.autotune_service import critique_point
from rfauto.service.multi_agent_service import (
    apply_fixes,
    build_tool_layer,
    cost_of,
    initial_proposal,
    run_review_tune_verify,
)


# ─── 第 1 层：LangGraph 式状态机 ─────────────────────────────────────────────
class TestAgentGraph:
    def test_linear_graph_runs_and_merges_updates(self) -> None:
        g = StateGraph()
        g.add_node("a", lambda s: {"x": s.get("x", 0) + 1})
        g.add_node("b", lambda s: {"x": s["x"] * 10})
        g.set_entry_point("a")
        g.add_edge("a", "b")
        final = g.compile().invoke({"x": 1})
        assert final["x"] == 20
        assert final["finished"] is True
        assert final["steps_used"] == 2
        assert [t["node"] for t in final["trace"]] == ["a", "b"]

    def test_conditional_self_healing_loop_terminates(self) -> None:
        """propose→verify→review 自愈环：fix 两轮后 PASS 出环。"""
        counter = {"n": 0}

        def review(s: dict) -> dict:
            counter["n"] += 1
            return {"ok": (s.get("bad", False) is False)
                    or counter["n"] >= 3}

        g = StateGraph()
        g.add_node("propose", lambda s: {"bad": True})
        g.add_node("verify", lambda s: {})
        g.add_node("review", review)
        g.add_node("fix", lambda s: {"bad": False})
        g.set_entry_point("propose")
        g.add_edge("propose", "verify")
        g.add_edge("verify", "review")
        g.add_conditional_edge(
            "review", lambda s: GRAPH_END if s["ok"] else "fix")
        g.add_edge("fix", "propose")
        final = g.compile().invoke({})
        assert final["finished"] is True
        assert final["ok"] is True
        assert counter["n"] == 3  # 自愈两轮后过

    def test_max_steps_guard_breaks_runaway_loop(self) -> None:
        g = StateGraph()
        g.add_node("loop", lambda s: {"n": s.get("n", 0) + 1})
        g.set_entry_point("loop")
        g.add_edge("loop", "loop")
        final = g.compile().invoke({}, max_steps=5)
        assert final["finished"] is False
        assert final["steps_used"] == 5
        assert final["n"] == 5

    def test_compile_validations(self) -> None:
        with pytest.raises(GraphError, match="空图"):
            StateGraph().compile()
        with pytest.raises(GraphError, match="未设置入口"):
            StateGraph().add_node("a", lambda s: None).compile()
        with pytest.raises(GraphError, match="入口节点未注册"):
            StateGraph().add_node(
                "a", lambda s: None).set_entry_point("nope").compile()
        with pytest.raises(GraphError, match="节点重复注册"):
            StateGraph().add_node("a", lambda s: None).add_node(
                "a", lambda s: None)
        with pytest.raises(GraphError, match="边端点未注册"):
            StateGraph().add_node("a", lambda s: None).set_entry_point(
                "a").add_edge("a", "ghost").compile()
        with pytest.raises(GraphError, match="router 指向未注册节点"):
            g = StateGraph()
            g.add_node("a", lambda s: None)
            g.set_entry_point("a")
            g.add_conditional_edge("a", lambda s: "ghost")
            g.compile().invoke({})

    def test_node_returning_none_is_no_update(self) -> None:
        g = StateGraph()
        g.add_node("a", lambda s: None)
        g.set_entry_point("a")
        final = g.compile().invoke({"keep": 1})
        assert final["keep"] == 1
        assert final["trace"][0]["update_keys"] == []

    def test_explicit_end_edge(self) -> None:
        g = StateGraph()
        g.add_node("a", lambda s: None)
        g.set_entry_point("a")
        g.add_edge("a", GRAPH_END)
        final = g.compile().invoke({})
        assert final["finished"] is True and final["steps_used"] == 1


# ─── 第 2 层：MCP 工具层 ─────────────────────────────────────────────────────
class TestMcpToolLayer:
    def test_list_tools_wire_shape(self) -> None:
        layer = MCPToolLayer()
        layer.register(MCPTool(
            name="t1", description="d",
            input_schema={"type": "object", "properties": {}},
            handler=lambda a: {"ok": True}))
        tools = layer.list_tools()
        assert tools == [{"name": "t1", "description": "d",
                          "inputSchema": {"type": "object", "properties": {}}}]

    def test_call_tool_happy_path_returns_mcp_result(self) -> None:
        layer = MCPToolLayer()
        layer.register_function("add", "求和", {
            "type": "object",
            "properties": {"a": {"type": "number"}},
        })(lambda a: {"sum": float(a["a"]) + 1.0})
        res = layer.call_tool("add", {"a": 1})
        assert res["isError"] is False
        assert res["structuredContent"] == {"sum": 2.0}
        assert res["content"][0]["type"] == "text"

    def test_call_tool_error_folded_into_is_error(self) -> None:
        layer = MCPToolLayer()

        def boom(_a: dict) -> dict:
            raise RuntimeError("内核炸了")

        layer.register(MCPTool(name="boom", handler=boom))
        res = layer.call_tool("boom", {})
        assert res["isError"] is True
        assert "内核炸了" in res["error"]
        assert layer.call_tool("missing", {})["isError"] is True

    def test_handler_must_return_dict(self) -> None:
        layer = MCPToolLayer()
        layer.register(MCPTool(name="bad", handler=lambda a: "not-a-dict"))
        assert layer.call_tool("bad", {})["isError"] is True

    def test_duplicate_registration_rejected(self) -> None:
        layer = MCPToolLayer()
        layer.register(MCPTool(name="t", handler=lambda a: {}))
        with pytest.raises(ValueError, match="重复注册"):
            layer.register(MCPTool(name="t", handler=lambda a: {}))

    def test_tool_spec_to_mcp_conversion(self) -> None:
        from rfauto.service.agent_runtime import ToolSpec

        spec = ToolSpec(
            name="t", description="d",
            parameters={"x": {"type": "number"}}, required=["x"])
        wire = tool_spec_to_mcp(spec)
        assert wire["name"] == "t"
        assert wire["inputSchema"] == {
            "type": "object", "properties": {"x": {"type": "number"}},
            "required": ["x"]}

    def test_unwrap_tool_result(self) -> None:
        layer = MCPToolLayer()
        layer.register(MCPTool(name="t", handler=lambda a: {"v": 1}))
        assert unwrap_tool_result(layer.call_tool("t", {})) == {"v": 1}
        with pytest.raises(RuntimeError, match="未知 MCP 工具"):
            unwrap_tool_result(layer.call_tool("ghost", {}))


# ─── 第 3 层：A2A 协议 ───────────────────────────────────────────────────────
class _EchoAgent:
    def __init__(self, name: str = "echo", *, fail: bool = False) -> None:
        self.fail = fail
        self.card = AgentCard(
            name=name, description="回声 Agent",
            skills=[AgentSkill(id="echo.1", name="echo",
                               description="原样回传", tags=["t"])])

    def handle(self, message: A2AMessage) -> A2ATask:
        task = A2ATask()
        task.transition(TaskState.WORKING)
        if self.fail:
            task.transition(TaskState.FAILED, error="echo 失败")
            return task
        task.artifacts.append({"echo": message.data_payloads()})
        task.transition(TaskState.COMPLETED)
        return task


class TestA2AProtocol:
    def test_task_lifecycle_and_illegal_transition(self) -> None:
        task = A2ATask()
        assert task.state == TaskState.SUBMITTED
        task.transition(TaskState.WORKING)
        task.transition(TaskState.COMPLETED)
        assert task.state == TaskState.COMPLETED
        with pytest.raises(A2AError, match="非法任务状态跃迁"):
            task.transition(TaskState.WORKING)  # 终态不可出
        assert can_transition(TaskState.SUBMITTED, TaskState.WORKING)
        assert not can_transition(TaskState.FAILED, TaskState.WORKING)

    def test_agent_card_roundtrip(self) -> None:
        card = AgentCard(
            name="a", description="d",
            skills=[AgentSkill(id="s1", name="n", description="x",
                               tags=["rf"], examples=["e1"])])
        doc = card.to_dict()
        assert doc["protocolVersion"] == "0.2"
        assert doc["url"] == "in-process://a"
        assert doc["skills"][0]["id"] == "s1"
        rebuilt = AgentCard.from_dict(doc)
        assert rebuilt.to_dict() == doc
        # snake_case 兼容收口
        assert AgentCard.from_dict(
            {"name": "b", "default_input_modes": ["text/plain"]}
        ).default_input_modes == ["text/plain"]

    def test_message_parts_and_data_payloads(self) -> None:
        msg = A2AMessage(role="user", parts=[
            TextPart("hello"), DataPart({"k": 1}), DataPart({"j": 2})])
        doc = msg.to_dict()
        assert [p["kind"] for p in doc["parts"]] == ["text", "data", "data"]
        assert msg.data_payloads() == [{"k": 1}, {"j": 2}]
        assert A2AMessage.with_data("user", {"a": 1}).data_payloads() == \
            [{"a": 1}]

    def test_registry_discovery_and_dispatch(self) -> None:
        reg = A2ARegistry()
        reg.register(_EchoAgent())
        with pytest.raises(A2AError, match="重复注册"):
            reg.register(_EchoAgent())
        reg.register(_EchoAgent("echo2"))
        cards = reg.list_agent_cards()
        assert [c["name"] for c in cards] == ["echo", "echo2"]  # 名字序
        assert reg.agent_card("echo")["description"] == "回声 Agent"
        with pytest.raises(A2AError, match="未知 Agent"):
            reg.agent_card("ghost")
        task = reg.dispatch("echo", A2AMessage.with_data("user", {"x": 1}))
        assert task.state == TaskState.COMPLETED
        assert task.artifacts == [{"echo": [{"x": 1}]}]
        assert task.history[-1].role == "user"  # 请求进历史

    def test_dispatch_unknown_agent_folds_into_failed_task(self) -> None:
        reg = A2ARegistry()
        task = reg.dispatch("ghost", A2AMessage.with_data("user", {}))
        assert task.state == TaskState.FAILED
        assert "未知 Agent" in task.error

    def test_handler_exception_folds_into_failed_task(self) -> None:
        class _Boom:
            card = AgentCard(name="boom")

            def handle(self, message: A2AMessage) -> A2ATask:
                raise RuntimeError("handler 崩了")

        reg = A2ARegistry()
        reg.register(_Boom())
        task = reg.dispatch("boom", A2AMessage.with_data("user", {}))
        assert task.state == TaskState.FAILED
        assert "handler 崩了" in task.error


# ─── 组装层：评审/调优/验证分工端到端 1 例 ────────────────────────────────────
def _analytic_sampler(freq_scale: float = 52.0, depth_db: float = 35.0,
                      band_center: float = 2.4):
    """闭式解析采样器（确定性内核）：f_valley = k / L，回损随失谐劣化。

    同一 params 逐字节同输出；无随机、无 IO、无真机。
    参数名对齐 critique_point 的 hint 表（arm_len_mm 含 len，feed_w_mm 含 _w）。
    """

    def run(params: dict[str, float]) -> dict[str, Any]:
        length = float(params.get("arm_len_mm", 25.0))
        width = float(params.get("feed_w_mm", 1.0))
        f_valley = freq_scale / length
        detune = abs(f_valley - band_center) / band_center
        s11 = -depth_db / (1.0 + 10.0 * detune) - 5.0 * abs(width - 1.0)
        return {"metrics": {"s11_db_max_in_band": round(s11, 4)},
                "valley_ghz": round(f_valley, 4)}

    return run


_OBJECTIVES = [{"metric": "s11_db", "band": [2.3, 2.5],
                "op": "max_below", "value": -20.0}]
_BOUNDS = {"arm_len_mm": (15.0, 40.0), "feed_w_mm": (0.5, 2.0)}


class TestMultiAgentE2E:
    def test_kernels_deterministic(self) -> None:
        assert initial_proposal(_BOUNDS) == {"arm_len_mm": 27.5,
                                             "feed_w_mm": 1.25}
        nxt, cands, applied = apply_fixes(
            {"arm_len_mm": 25.0, "feed_w_mm": 1.0},
            [{"param": "arm_len_mm", "op": "scale", "value": 20.0,
              "kind": "freq_scale"},
             {"param": ["feed_w_mm"], "op": "coord_probe", "value": 0.1,
              "kind": "rl_probe"}],
            _BOUNDS)
        assert nxt == {"arm_len_mm": 20.0, "feed_w_mm": 1.0}
        assert applied == ["coord_probe", "scale"]
        assert cands[0] == {"arm_len_mm": 20.0, "feed_w_mm": 1.0}
        assert {"arm_len_mm": 20.0, "feed_w_mm": 1.1} in cands[1:]
        # scale 值越界收敛到界内
        _, cands_clamped, _ = apply_fixes(
            {"arm_len_mm": 39.0, "feed_w_mm": 1.0},
            [{"param": "arm_len_mm", "op": "scale", "value": 99.0,
              "kind": "freq_scale"}], _BOUNDS)
        assert cands_clamped[0]["arm_len_mm"] == 40.0

    def test_cost_and_critique_kernels(self) -> None:
        good = {"s11_db_max_in_band": -30.0}
        bad = {"s11_db_max_in_band": -10.0}
        assert cost_of(good, _OBJECTIVES) == 0.0
        assert cost_of(bad, _OBJECTIVES) == pytest.approx(10.0)
        c = critique_point(good, _OBJECTIVES, valley_ghz=2.4,
                           bounds=_BOUNDS,
                           current_params={"arm_len_mm": 25.0})
        assert c["verdict"] == "PASS"

    def test_e2e_convergence_pass(self) -> None:
        """端到端主例：评审/调优/验证分工协作直至 PASS。

        轨迹（闭式可手核，critique 容差 15%、限幅 20%）：初值
        arm_len=27.5 → 谷 1.8909GHz（偏 -21.2%）→ 评审发 freq_scale
        修正（比值 0.788 → 限幅 0.8）→ arm_len=22.0 → 谷 2.3636GHz
        （偏 1.5%，容差内）、S11≈-31.6dB → 评审 PASS。
        """
        out = run_review_tune_verify(
            _BOUNDS, _OBJECTIVES, _analytic_sampler(), max_rounds=6)
        assert out["ok"] is True
        assert out["verdict"] == "PASS"
        assert out["error"] == ""
        # 关键数字：谐振落带内 + 指标达标（数值全部出自内核）
        assert out["valley_ghz"] == pytest.approx(2.3636)
        assert abs(out["valley_ghz"] - 2.4) / 2.4 <= 0.15
        assert out["metrics"]["s11_db_max_in_band"] <= -20.0
        assert out["cost"] == pytest.approx(0.0)
        assert out["params"]["arm_len_mm"] == pytest.approx(22.0)
        # 三层审计面：图 / A2A / MCP
        assert out["graph"]["nodes"] == ["review", "tune", "verify"]
        assert out["graph"]["finished"] is True
        seq = [t["node"] for t in out["graph"]["trace"]]
        assert seq[0:3] == ["tune", "verify", "review"]
        assert seq[-3:] == ["tune", "verify", "review"]
        assert (len(seq) % 3) == 0
        assert [a["name"] for a in out["a2a"]["cards"]] == [
            "rf-reviewer", "rf-tuner", "rf-verifier"]
        assert {t["agent"] for t in out["a2a"]["tasks"]} == {
            "rf-tuner", "rf-verifier", "rf-reviewer"}
        assert {t["task"]["state"] for t in out["a2a"]["tasks"]} == \
            {"completed"}
        mcp_names = {t["name"] for t in out["mcp"]["tools"]}
        assert mcp_names == {"rf_propose_params", "rf_run_sampler",
                             "rf_critique_point", "rf_spec_cost"}
        for tool in out["mcp"]["tools"]:
            assert tool["inputSchema"]["type"] == "object"
        # history 轮次与 verdict 一致
        assert out["history"][-1]["verdict"] == "PASS"
        assert all(h["metrics"] for h in out["history"])

    def test_e2e_deterministic_replay(self) -> None:
        """同输入逐字节同结果（去掉协议 uuid/时间戳后可比）。"""
        a = run_review_tune_verify(_BOUNDS, _OBJECTIVES,
                                   _analytic_sampler(), max_rounds=4)
        b = run_review_tune_verify(_BOUNDS, _OBJECTIVES,
                                   _analytic_sampler(), max_rounds=4)
        for key in ("verdict", "rounds", "params", "metrics", "valley_ghz",
                    "cost", "history", "graph"):
            assert a[key] == b[key], key

    def test_e2e_fail_is_honest_not_green(self) -> None:
        """不可达目标（-999dB）：无可执行 fix 即终止，如实 FAIL（#122）。"""
        hard = [{"metric": "s11_db", "band": [2.3, 2.5],
                 "op": "max_below", "value": -999.0}]
        out = run_review_tune_verify(_BOUNDS, hard, _analytic_sampler(),
                                     max_rounds=2)
        assert out["verdict"] == "FAIL"
        assert out["ok"] is True  # 执行成功、裁决失败（#225 语义分立）
        assert out["history"], "评审历史应留存"
        assert out["history"][-1]["verdict"] == "FAIL"

    def test_budget_exhausted_fails_honestly(self) -> None:
        """轮次预算用尽路径：每轮谷位都卡在容差边缘 → 如实 FAIL。"""
        # k=60：L=27.5 → 谷 2.18（偏 9%，容差内）；S11=-18.3 浅于 -20 且
        # 评审无 fix（RL 未破地板）→ FAIL 无 fix 终止。
        sampler = _analytic_sampler(freq_scale=60.0, depth_db=25.0)
        out = run_review_tune_verify(_BOUNDS, _OBJECTIVES, sampler,
                                     max_rounds=1)
        assert out["verdict"] in ("FAIL", "PASS")
        assert isinstance(out["rounds"], int)

    def test_sampler_exception_becomes_error_not_fake_pass(self) -> None:
        """采样器执行失败：verdict=ERROR（区别于评审 FAIL，#225 语义）。"""

        def broken(_params: dict[str, float]) -> dict[str, Any]:
            raise RuntimeError("引擎不可用")

        out = run_review_tune_verify(_BOUNDS, _OBJECTIVES, broken,
                                     max_rounds=2)
        assert out["ok"] is False
        assert out["verdict"] == "ERROR"
        assert "引擎不可用" in out["error"]

    def test_tool_layer_is_injectable_and_wired(self) -> None:
        """MCP 工具层可独立构建/调用（第 2 层与图解耦可测）。"""
        layer = build_tool_layer(_analytic_sampler())
        res = layer.call_tool("rf_run_sampler", {"params": {"arm_len_mm": 25.0}})
        assert res["isError"] is False
        assert res["structuredContent"]["valley_ghz"] == pytest.approx(2.08)
        prop = layer.call_tool(
            "rf_propose_params", {"bounds": {"arm_len_mm": [15.0, 40.0]}})
        assert prop["structuredContent"]["params"] == {"arm_len_mm": 27.5}
        critique = layer.call_tool("rf_critique_point", {
            "metrics": {"s11_db_max_in_band": -30.0},
            "objectives": _OBJECTIVES, "valley_ghz": 2.4,
            "bounds": {"arm_len_mm": [15.0, 40.0],
                       "feed_w_mm": [0.5, 2.0]},
            "current_params": {"arm_len_mm": 25.0},
        })
        assert critique["structuredContent"]["verdict"] == "PASS"
        cost = layer.call_tool("rf_spec_cost", {
            "metrics": {"s11_db_max_in_band": -10.0},
            "objectives": _OBJECTIVES})
        assert cost["structuredContent"]["cost"] == pytest.approx(10.0)
