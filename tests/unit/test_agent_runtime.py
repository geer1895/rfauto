"""AgentRuntime 薄协议 + 配方沙箱 + Pi 式会话格式 单测。

运行时循环用注入的假传输层（不开网络）；沙箱用 tmp_path 根
（不落 runs/）；promote 走真 Gate（fake adapter dry-run）。
"""

import json
from pathlib import Path

import pytest
import yaml

# ─── 假传输层 ────────────────────────────────────────────────────────────────

def _msg(content=None, tool_calls=None):
    out = {"role": "assistant", "content": content}
    if tool_calls:
        out["tool_calls"] = tool_calls
    return out


def _tool_call(cid, name, args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedTransport:
    """按脚本逐次返回响应；记录收到的 messages 供断言。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def __call__(self, messages, tools):
        self.calls.append([dict(m) for m in messages])
        return {"choices": [{"message": self.responses.pop(0)}]}


@pytest.fixture
def runtime():
    from rfauto.service.agent_runtime import BuiltinOpenAIRuntime
    return BuiltinOpenAIRuntime()


@pytest.fixture
def request_min():
    from rfauto.service.agent_runtime import RuntimeRequest
    return RuntimeRequest(messages=[{"role": "user", "content": "hi"}], max_rounds=4)


def _echo_executor(name, args):
    return {"echo": name, "args": args}


class TestRuntimeRegistry:
    def test_builtin_registered(self):
        from rfauto.service.agent_runtime import RuntimeRegistry
        assert "builtin" in RuntimeRegistry.available()

    def test_register_and_create(self):
        from rfauto.service.agent_runtime import AgentRuntime, RuntimeRegistry

        class Fake(AgentRuntime):
            name = "_fake_test"

            def submit(self, request, executor):
                raise NotImplementedError

        try:
            RuntimeRegistry.register(Fake)
            assert "_fake_test" in RuntimeRegistry.available()
            assert isinstance(RuntimeRegistry.create("_fake_test"), Fake)
        finally:
            RuntimeRegistry._runtimes.pop("_fake_test", None)

    def test_unknown_name_raises(self):
        from rfauto.service.agent_runtime import RuntimeRegistry
        with pytest.raises(KeyError):
            RuntimeRegistry.create("_no_such_runtime")


class TestBuiltinLoop:
    def test_text_only_stop(self, runtime, request_min):
        tr = ScriptedTransport([_msg(content="答案")])
        runtime._transport = tr
        out = runtime.submit(request_min, _echo_executor)
        assert out.finish_reason == "stop" and out.text == "答案"
        assert out.tools_used == [] and out.usage.llm_calls == 1

    def test_tool_round_then_stop(self, runtime, request_min):
        tr = ScriptedTransport([
            _msg(tool_calls=[_tool_call("t1", "list_runs", {"limit": 3})]),
            _msg(content="完成"),
        ])
        runtime._transport = tr
        seen = []
        out = runtime.submit(request_min,
                             lambda n, a: (seen.append(n), {"runs": []})[1])
        assert out.finish_reason == "stop" and out.text == "完成"
        assert seen == ["list_runs"] and out.tools_used == ["list_runs"]
        assert out.usage.tool_calls == 1 and out.usage.llm_calls == 2
        # 工具结果以 role=tool 消息回传模型
        tool_msgs = [m for m in tr.calls[1] if m.get("role") == "tool"]
        assert len(tool_msgs) == 1 and '"runs": []' in tool_msgs[0]["content"]

    def test_executor_exception_fed_back(self, runtime, request_min):
        def boom(name, args):
            raise ValueError("炸了")

        tr = ScriptedTransport([
            _msg(tool_calls=[_tool_call("t1", "run_detail", {"run_id": "x"})]),
            _msg(content="收到错误"),
        ])
        runtime._transport = tr
        out = runtime.submit(request_min, boom)
        assert out.finish_reason == "stop"
        tool_msgs = [m for m in tr.calls[1] if m.get("role") == "tool"]
        assert "炸了" in tool_msgs[0]["content"]

    def test_budget_exhausted_keeps_scene(self, runtime, request_min):
        request_min.max_rounds = 2
        tr = ScriptedTransport([
            _msg(tool_calls=[_tool_call(f"t{i}", "list_runs", {}) for i in range(1)]),
            _msg(tool_calls=[_tool_call("t2", "list_runs", {})]),
            _msg(content="不应到达"),
        ])
        runtime._transport = tr
        out = runtime.submit(request_min, _echo_executor)
        assert out.finish_reason == "budget_exhausted"
        assert "单轮上限" in out.text and "继续" in out.text
        # 末段催办已注入现场（续跑时模型看得到）
        assert any("工具预算只剩 2 次" in json.dumps(m, ensure_ascii=False)
                   for m in out.messages)

    def test_nudge_not_injected_early(self, runtime, request_min):
        request_min.max_rounds = 4
        tr = ScriptedTransport([
            _msg(tool_calls=[_tool_call("t1", "list_runs", {})]),
            _msg(content="好了"),
        ])
        runtime._transport = tr
        runtime.submit(request_min, _echo_executor)
        assert not any("工具预算" in json.dumps(m, ensure_ascii=False)
                       for m in tr.calls[-1])

    def test_malformed_args_fed_back(self, runtime, request_min):
        bad = {"id": "t1", "type": "function",
               "function": {"name": "list_runs", "arguments": "{not json"}}
        tr = ScriptedTransport([
            _msg(tool_calls=[bad]), _msg(content="ok"),
        ])
        runtime._transport = tr
        out = runtime.submit(request_min, _echo_executor)
        assert out.finish_reason == "stop"


# ─── 配方沙箱 ────────────────────────────────────────────────────────────────

@pytest.fixture
def recipe(tmp_path):
    data = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
        "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def sandbox(tmp_path):
    from rfauto.service.agent_sandbox import RecipeSandbox
    return RecipeSandbox(root=tmp_path / "sb")


class TestRecipeSandbox:
    def test_stage_copies_once_and_preserves_edits(self, sandbox, recipe):
        first = sandbox.stage(recipe)
        assert first["ok"] and not first["already_staged"]
        sandbox.apply_param_edits(recipe, {"arm_len_mm": 21.5})
        again = sandbox.stage(recipe)
        assert again["already_staged"]
        d = sandbox.diff(recipe)  # 二次 stage 未覆盖草稿编辑
        assert d["params_changed"]["arm_len_mm"]["new"] == 21.5

    def test_apply_edits_merge_into_value_struct(self, sandbox, recipe):
        sandbox.apply_param_edits(recipe, {"arm_len_mm": 22.0})
        data = yaml.safe_load(Path(sandbox.diff(recipe)["draft"]).read_text(encoding="utf-8"))
        assert data["params"]["arm_len_mm"]["value"] == 22.0
        assert data["params"]["arm_len_mm"]["unit"] == "mm"  # 其余字段保留

    def test_diff_reports_old_new(self, sandbox, recipe):
        sandbox.apply_param_edits(recipe, {"arm_len_mm": 19.0})
        d = sandbox.diff(recipe)
        assert d["ok"] and d["params_changed"]["arm_len_mm"] == {
            "old": 20.5, "new": 19.0}
        assert "-arm_len_mm" in d["unified_diff"] or "value: 19.0" in d["unified_diff"]

    def test_promote_only_params_goes_to_gate(self, sandbox, recipe):
        sandbox.apply_param_edits(recipe, {"arm_len_mm": 21.0})
        out = sandbox.promote(recipe)
        assert out["ok"], out
        assert out.get("sandbox_promote") and out["stage"] == "L3"
        assert out["params_proposed"] == {"arm_len_mm": 21.0}

    def test_promote_refuses_non_param_changes(self, sandbox, recipe):
        sandbox.stage(recipe)
        draft = Path(sandbox.draft_path(recipe))
        data = yaml.safe_load(draft.read_text(encoding="utf-8"))
        data["setup"]["points"] = 21  # 非 params 节
        draft.write_text(yaml.safe_dump(data), encoding="utf-8")
        out = sandbox.promote(recipe)
        assert not out["ok"] and out["stage"] == "promote"

    def test_promote_no_difference(self, sandbox, recipe):
        sandbox.stage(recipe)
        out = sandbox.promote(recipe)
        assert not out["ok"] and "无差异" in out["error"]

    def test_path_escape_blocked(self, sandbox, tmp_path):
        # 守卫对象是"沙箱内写入目标"：../ 与绝对外部路径都必须拒绝。
        # 配方源路径（stage/apply 的入参）允许在盘上任意位置——那是读取面。
        from rfauto.service.agent_sandbox import SandboxViolation
        with pytest.raises(SandboxViolation):
            sandbox._guard("../evil.yaml")
        with pytest.raises(SandboxViolation):
            sandbox._guard(str(tmp_path / "outside.yaml"))
        # 正常草稿名放行
        assert sandbox._guard("ok_draft.yaml").parent == sandbox.root

    def test_suffix_whitelist(self, sandbox, recipe):
        from rfauto.service.agent_sandbox import SandboxViolation
        tag = sandbox.draft_path(recipe).stem
        with pytest.raises(SandboxViolation):
            sandbox._guard(f"{tag}.py")

    def test_list_and_discard(self, sandbox, recipe):
        sandbox.stage(recipe)
        assert sandbox.list_drafts()["drafts"]
        sandbox.discard(recipe)
        assert sandbox.list_drafts()["drafts"] == []


# ─── Pi 式会话公开格式 ───────────────────────────────────────────────────────

class TestSessionFormat:
    def test_persist_load_roundtrip(self, tmp_path, monkeypatch):
        from rfauto.service import agent_runtime
        monkeypatch.setattr(agent_runtime, "SESSIONS_DIR", tmp_path / "sess")
        doc = agent_runtime.new_session_doc("chat_x", {"model": "m"})
        doc["history"] = [{"role": "user", "content": "你好"}]
        doc["stats"] = {"turns": 1}
        path = agent_runtime.persist_session(doc)
        loaded = agent_runtime.load_session(path)
        assert loaded["schema"] == agent_runtime.SESSION_SCHEMA
        assert loaded["history"][0]["content"] == "你好"
        assert loaded["meta"]["model"] == "m"
        assert loaded["updated_at"] >= loaded["created_at"]

    def test_load_rejects_unknown_schema(self, tmp_path):
        from rfauto.service.agent_runtime import load_session
        bad = tmp_path / "s.json"
        bad.write_text(json.dumps({"schema": "future-v99"}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_session(bad)

    def test_agentchat_persists_session(self, tmp_path, monkeypatch):
        from rfauto.service import agent_runtime, r3_services
        monkeypatch.setattr(agent_runtime, "SESSIONS_DIR", tmp_path / "sess")
        monkeypatch.setattr(r3_services, "get_chat_settings",
                            lambda: {"ok": True, "configured": False})
        chat = r3_services.AgentChat()
        chat.chat("solvers")
        files = list((tmp_path / "sess").glob("*.json"))
        assert len(files) == 1
        doc = agent_runtime.load_session(files[0])
        assert doc["history"][0]["role"] == "user"
        assert doc["stats"]["turns"] == 1

    def test_agentchat_reset_clears_state(self, monkeypatch):
        from rfauto.service import r3_services
        monkeypatch.setattr(r3_services, "get_chat_settings",
                            lambda: {"ok": True, "configured": False})
        chat = r3_services.AgentChat()
        chat.chat("solvers")
        old_id = chat.session_id
        out = chat.reset()
        assert out["ok"] and chat.session_id != old_id
        assert chat.history == [] and chat.get_tool_calls() == []
        assert chat.stats["turns"] == 0 and chat._pending_messages is None


# ─── G14：RuntimeUsage → CostLedger 记账 ───────────────────────────────────

class TestCostLedgerFeed:
    def test_usage_to_cost_ledger_books_fields(self):
        from rfauto.pipeline.quota_guard import CostLedger
        from rfauto.service.agent_runtime import RuntimeUsage, usage_to_cost_ledger

        ledger = CostLedger()
        usage = RuntimeUsage(prompt_tokens=120, completion_tokens=80, cached_tokens=30)
        out = usage_to_cost_ledger(usage, ledger, batch="sess1", actor="test-model")
        assert out is ledger  # 链式返回同一账本
        assert ledger.batches() == ["sess1"]
        assert ledger.actors("sess1") == ["test-model"]
        totals = ledger.totals()
        # 合成 usage 原值直录：prompt/completion 显式拆分，total_tokens=200
        assert totals["prompt_tokens"] == 120
        assert totals["completion_tokens"] == 80
        assert totals["total_tokens"] == 200
        # "仅总数"槽位不记（显式拆分口径，避免双计）；cached 是 prompt 子集不重复入账
        assert totals["tokens"] == 0.0
        # LLM/工具墙钟不是求解器机时，不入 solve_s（wall_hours 预算语义不受污染）
        assert totals["solve_s"] == 0.0 and totals["seat_hours"] == 0.0

    def test_usage_to_cost_ledger_accumulates(self):
        from rfauto.pipeline.quota_guard import CostLedger
        from rfauto.service.agent_runtime import RuntimeUsage, usage_to_cost_ledger

        ledger = CostLedger()
        usage_to_cost_ledger(RuntimeUsage(prompt_tokens=10, completion_tokens=5),
                             ledger, batch="b", actor="m")
        usage_to_cost_ledger(RuntimeUsage(prompt_tokens=100, completion_tokens=50),
                             ledger, batch="b", actor="m")
        totals = ledger.totals()
        assert totals["prompt_tokens"] == 110
        assert totals["completion_tokens"] == 55
        assert totals["total_tokens"] == 165  # ledger 行随 usage 累加增长

    def test_usage_to_cost_ledger_rejects_non_ledger(self):
        from rfauto.service.agent_runtime import RuntimeUsage, usage_to_cost_ledger

        with pytest.raises(TypeError):
            usage_to_cost_ledger(RuntimeUsage(), object(), batch="b", actor="m")

    def test_agentchat_books_llm_usage_into_ledger(self, tmp_path, monkeypatch):
        from rfauto.service import agent_runtime, r3_services

        class _ScriptedRuntime(agent_runtime.AgentRuntime):
            name = "_scripted_ledger"

            def __init__(self):
                self.calls = 0

            def submit(self, request, executor):
                self.calls += 1
                return agent_runtime.RuntimeResult(
                    text="ok",
                    usage=agent_runtime.RuntimeUsage(
                        prompt_tokens=100, completion_tokens=50, cached_tokens=20))

        monkeypatch.setattr(r3_services, "get_chat_settings",
                            lambda: {"ok": True, "configured": True})
        monkeypatch.setattr(r3_services, "get_chat_settings_raw",
                            lambda: {"runtime": "builtin", "model": "test-model",
                                     "max_tool_rounds": 4})
        scripted = _ScriptedRuntime()
        monkeypatch.setattr(agent_runtime.RuntimeRegistry, "create",
                            staticmethod(lambda name, **kw: scripted))
        monkeypatch.setattr(agent_runtime, "SESSIONS_DIR", tmp_path / "sess")

        chat = r3_services.AgentChat()
        chat.chat("你好")
        chat.chat("再来一轮")
        assert scripted.calls == 2
        totals = chat.cost_ledger.totals()
        assert totals["prompt_tokens"] == 200 and totals["completion_tokens"] == 100
        assert totals["total_tokens"] == 300
        assert chat.cost_ledger.batches() == [chat.session_id]
        assert chat.cost_ledger.actors(chat.session_id) == ["test-model"]

    def test_agentchat_reset_clears_ledger(self, tmp_path, monkeypatch):
        from rfauto.service import agent_runtime, r3_services

        monkeypatch.setattr(r3_services, "get_chat_settings",
                            lambda: {"ok": True, "configured": True})
        monkeypatch.setattr(r3_services, "get_chat_settings_raw",
                            lambda: {"runtime": "builtin", "model": "m"})
        scripted = agent_runtime.RuntimeResult(
            text="ok",
            usage=agent_runtime.RuntimeUsage(prompt_tokens=7, completion_tokens=3))

        class _OnceRuntime(agent_runtime.AgentRuntime):
            name = "_once_ledger"

            def submit(self, request, executor):
                return scripted

        monkeypatch.setattr(agent_runtime.RuntimeRegistry, "create",
                            staticmethod(lambda name, **kw: _OnceRuntime()))
        monkeypatch.setattr(agent_runtime, "SESSIONS_DIR", tmp_path / "sess")

        chat = r3_services.AgentChat()
        chat.chat("hi")
        assert chat.cost_ledger.totals()["total_tokens"] == 10
        old_id = chat.session_id
        chat.reset()
        assert chat.cost_ledger.batches() == []
        assert chat.cost_ledger.totals()["total_tokens"] == 0.0
        assert chat.session_id != old_id
