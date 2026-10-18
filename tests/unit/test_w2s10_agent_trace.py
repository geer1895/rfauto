"""EC-23 agent 环结构化追踪单测（aurora_e W2-S10 E1）。

覆盖面：
- AgentTracer 三级 span 的 JSONL 行结构与字段完整性（mock 环跑一轮）；
- 参数摘要截断；env 开关（off=零写盘）；写失败静默降级（#105）；
- AgentChat 真链路：回退（关键词路由）路径 span 完整性 + LLM mock 环
  （一次工具调用+最终答复）三级 span 树（session/turn/tool 恰好一条
  turn_end，LLM 遥测聚合在场）。

chdir 隔离到 tmp_path（#144：trace 缺省落 runs/chat_sessions，cwd 在仓外
tmp 时不触真实 runs/）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    monkeypatch.delenv("RFAUTO_REGISTRY_DB", raising=False)
    # 缺省开：清掉可能的外部关闭开关，开关用例自行 setenv
    monkeypatch.delenv("RFAUTO_AGENT_TRACE", raising=False)
    yield


def _read_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestAgentTracer:
    def test_three_level_span_fields(self, tmp_path):
        from rfauto.service.agent_trace import TRACE_SCHEMA, AgentTracer

        tracer = AgentTracer("sess_x", dir_path=tmp_path / "traces")
        tracer.session("session_start", model="m")
        tracer.turn(1, "turn_start", message_chars=7)
        tracer.tool(1, "list_solvers", elapsed_s=0.5, ok=True, args="{}")
        tracer.turn(1, "turn_end", path="llm", finish_reason="stop",
                    llm_calls=2, prompt_tokens=10, completion_tokens=5)
        tracer.session("session_end", reason="reset")

        path = tmp_path / "traces" / "sess_x.trace.jsonl"
        assert path.exists()
        lines = _read_lines(path)
        assert [rec["level"] for rec in lines] == [
            "session", "turn", "tool", "turn", "session"]
        assert [rec["event"] for rec in lines] == [
            "session_start", "turn_start", "tool", "turn_end", "session_end"]
        for rec in lines:
            assert rec["schema"] == TRACE_SCHEMA
            assert rec["session_id"] == "sess_x"
            assert rec["ts"]
        tool_rec = lines[2]
        assert tool_rec["tool"] == "list_solvers"
        assert tool_rec["turn"] == 1
        assert tool_rec["elapsed_s"] == 0.5
        assert tool_rec["ok"] is True
        assert tool_rec["args"] == "{}"
        end_rec = lines[3]
        assert end_rec["turn"] == 1
        assert end_rec["path"] == "llm"
        assert end_rec["llm_calls"] == 2

    def test_args_summary_truncates_with_total(self):
        from rfauto.service.agent_trace import ARGS_SUMMARY_MAX_CHARS, args_summary

        big = {"k": "x" * 500}
        text = args_summary(big)
        assert len(text) < ARGS_SUMMARY_MAX_CHARS + 60
        assert "...(truncated, total " in text
        assert args_summary({"a": 1}) == '{"a": 1}'

    def test_env_off_writes_nothing(self, tmp_path, monkeypatch):
        from rfauto.service.agent_trace import AgentTracer, trace_enabled

        monkeypatch.setenv("RFAUTO_AGENT_TRACE", "OFF")  # 大小写不敏感
        assert trace_enabled() is False
        tracer = AgentTracer("sess_off", dir_path=tmp_path)
        tracer.session("session_start")
        tracer.turn(1, "turn_start")
        assert not list(tmp_path.glob("*.trace.jsonl"))

    def test_write_failure_silent(self, tmp_path):
        # dir_path 的父级是个文件 → mkdir/open 必炸；emit 必须吞掉不 raise（#105）
        from rfauto.service.agent_trace import AgentTracer

        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir", encoding="utf-8")
        tracer = AgentTracer("sess_bad", dir_path=blocker / "sub")
        tracer.session("session_start")  # 不抛即过
        tracer.tool(1, "x", elapsed_s=0.0, ok=True, args="{}")

    def test_default_dir_is_sessions_dir(self, tmp_path, monkeypatch):
        # 缺省目录=runs/chat_sessions（会话存档同目录范式）；cwd 在仓外 tmp
        # 时不触真实 runs/（resolve_runs_dir 只收敛仓内子目录 cwd）
        from rfauto.service.agent_trace import AgentTracer

        tracer = AgentTracer("sess_def")
        assert tracer.path.parent.name == "chat_sessions"
        assert tracer.path.name == "sess_def.trace.jsonl"


def _configure_fallback(monkeypatch):
    from rfauto.service import r3_services

    monkeypatch.setattr(r3_services, "get_chat_settings",
                        lambda: {"ok": True, "configured": False})


class TestAgentChatFallbackTrace:
    def test_fallback_turn_spans(self, tmp_path, monkeypatch):
        _configure_fallback(monkeypatch)
        from rfauto.service.r3_services import AgentChat

        chat = AgentChat()
        out = chat.chat("solvers")
        assert out["action"] == "list_solvers"
        path = tmp_path / "runs" / "chat_sessions" / f"{chat.session_id}.trace.jsonl"
        assert path.exists()
        lines = _read_lines(path)
        # session_start + turn_start + turn_end（fallback 路径恰一条 turn_end）
        events = [(rec["level"], rec["event"]) for rec in lines]
        assert events == [("session", "session_start"),
                          ("turn", "turn_start"),
                          ("turn", "turn_end")]
        assert lines[1]["message_chars"] == len("solvers")
        assert lines[2]["path"] == "fallback"
        assert lines[2]["action"] == "list_solvers"

    def test_reset_emits_session_end_and_new_file(self, tmp_path, monkeypatch):
        _configure_fallback(monkeypatch)
        from rfauto.service.r3_services import AgentChat

        chat = AgentChat()
        chat.chat("solvers")
        old_id = chat.session_id
        chat.reset()
        d = tmp_path / "runs" / "chat_sessions"
        end_lines = _read_lines(d / f"{old_id}.trace.jsonl")
        assert end_lines[-1]["event"] == "session_end"
        assert end_lines[-1]["reason"] == "reset"
        # 新会话文件尚未创建（懒建于首轮 chat）
        assert not (d / f"{chat.session_id}.trace.jsonl").exists()
        chat.chat("runs")  # 触发新会话首轮
        new_lines = _read_lines(d / f"{chat.session_id}.trace.jsonl")
        assert new_lines[0]["event"] == "session_start"
        assert new_lines[0]["session_id"] == chat.session_id


class TestAgentChatLLMTrace:
    """mock 传输层跑一轮真环（一次工具调用+最终答复），钉三级 span 树。"""

    @pytest.fixture()
    def _llm_env(self, monkeypatch):
        from rfauto.service import agent_runtime, r3_services

        calls = {"n": 0}

        def fake_transport(messages, tools):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"choices": [{"message": {"tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": "list_solvers", "arguments": "{}"},
                }]}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 3}}
            return {"choices": [{"message": {"content": "已完成"}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 7}}

        monkeypatch.setattr(agent_runtime, "openai_chat_completion", fake_transport)
        monkeypatch.setattr(r3_services, "get_chat_settings",
                            lambda: {"ok": True, "configured": True})
        monkeypatch.setattr(r3_services, "get_chat_settings_raw", lambda: {
            "max_tool_rounds": 4, "runtime": "builtin", "model": "mock-model"})
        return calls

    def test_mock_loop_three_level_tree(self, tmp_path, _llm_env):
        from rfauto.service.r3_services import AgentChat

        chat = AgentChat()
        out = chat.chat("看看有哪些求解器")
        assert out["text"] == "已完成"
        path = tmp_path / "runs" / "chat_sessions" / f"{chat.session_id}.trace.jsonl"
        lines = _read_lines(path)
        events = [(rec["level"], rec["event"]) for rec in lines]
        # 三级树：session_start → turn_start → tool → turn_end（恰一条）
        assert events == [("session", "session_start"),
                          ("turn", "turn_start"),
                          ("tool", "tool"),
                          ("turn", "turn_end")]
        tool_rec = lines[2]
        assert tool_rec["tool"] == "list_solvers"
        assert tool_rec["ok"] is True
        assert tool_rec["turn"] == 1
        assert "elapsed_s" in tool_rec
        end_rec = lines[3]
        assert end_rec["path"] == "llm"
        assert end_rec["finish_reason"] == "stop"
        assert end_rec["llm_calls"] == 2
        assert end_rec["prompt_tokens"] == 31
        assert end_rec["completion_tokens"] == 10
        assert end_rec["tools_used"] == ["list_solvers"]

    def test_tool_error_marks_not_ok(self, tmp_path, _llm_env, monkeypatch):
        from rfauto.service import r3_services
        from rfauto.service.r3_services import AgentChat

        real = r3_services._execute_tool

        def boom(name, args):
            if name == "list_solvers":
                raise RuntimeError("boom")
            return real(name, args)

        monkeypatch.setattr(r3_services, "_execute_tool", boom)
        chat = AgentChat()
        chat.chat("看看有哪些求解器")
        path = tmp_path / "runs" / "chat_sessions" / f"{chat.session_id}.trace.jsonl"
        tool_recs = [r for r in _read_lines(path) if r["level"] == "tool"]
        assert len(tool_recs) == 1
        assert tool_recs[0]["ok"] is False

    def test_trace_off_env_disables_chat_trace(self, tmp_path, monkeypatch):
        _configure_fallback(monkeypatch)
        monkeypatch.setenv("RFAUTO_AGENT_TRACE", "off")
        from rfauto.service.r3_services import AgentChat

        chat = AgentChat()
        out = chat.chat("solvers")
        assert out["action"] == "list_solvers"
        d = tmp_path / "runs" / "chat_sessions"
        # 会话存档 JSON 照常（非 trace 面），trace 文件零落盘
        assert (d / f"{chat.session_id}.json").exists()
        assert not list(d.glob("*.trace.jsonl"))
