"""DS-2 "LLM 可见即留痕"不变量测试（W2-G）：负控/正常流/#105 不阻断。

判据（W2-G criteria 件 1）：
- 注入未留痕片段 → violate 计数（负控）；
- 正常流（executor 摘要随 tool_calls 留痕）→ 零 violate；
- 校验函数抛错不阻塞主路径（#105：chat 面照常出文本）；
- 配置开关 session_audit_invariant: off → 不校验；
- 全 monkeypatch（#139）：无 LLM API、无网络通道。
"""

from __future__ import annotations

import json

from rfauto.service import session_audit_service as sas
from rfauto.service.agent_runtime import (
    RuntimeResult,
    RuntimeUsage,
    tool_context_content,
)
from rfauto.service.session_audit_service import (
    assert_visible_implies_logged,
    audit_turn_best_effort,
    audit_visible_messages,
    content_digest,
)


def _doc(tool_digests: list[str] | None = None,
         history: list[dict] | None = None) -> dict:
    return {
        "schema": "rfauto-chat-session-v1",
        "session_id": "chat_test",
        "history": history or [],
        "tool_calls": [{"action": "run_detail", "args": {"run_id": "r1"},
                        "result_digest": d} for d in (tool_digests or [])],
        "stats": {},
    }


class TestSingleFragmentJudge:
    def test_unlogged_payload_is_negative_control(self):
        """负控：未留痕片段 → violate_count=1、ok=False。"""
        payload = json.dumps({"metrics": {"s11_db": -18.2}, "run": "r9"},
                             ensure_ascii=False)
        out = assert_visible_implies_logged(payload, _doc(["deadbeef" * 2]))
        assert out.ok is False
        assert out.violate_count == 1
        assert out.violations[0]["reason"]

    def test_logged_digest_passes(self):
        payload = json.dumps({"metrics": {"s11_db": -18.2}}, ensure_ascii=False)
        out = assert_visible_implies_logged(payload,
                                            _doc([content_digest(payload)]))
        assert out.ok is True and out.violate_count == 0

    def test_history_substring_passes(self):
        fragment = "校准样本集 24 点，cost 分布非退化（文件片段复述进对话）"
        doc = _doc([], history=[{"role": "assistant", "content": f"结论：{fragment}"}])
        out = assert_visible_implies_logged(fragment, doc)
        assert out.ok is True

    def test_short_payload_exempt(self):
        out = assert_visible_implies_logged("ok", _doc([]))
        assert out.ok is True and out.checked == 1

    def test_unreadable_session_ref_is_honest_fail(self, tmp_path):
        """会话档引用不可读 → ok=False 如实（不 raise、不凑 PASS）。"""
        out = assert_visible_implies_logged("x" * 64, tmp_path / "nope.json")
        assert out.ok is False
        assert "不可读" in out.error


class TestBatchJudge:
    def test_tool_message_without_digest_is_negative_control(self):
        """运行时挂点负控：未走 executor 的 tool 消息 → 计数。"""
        msgs = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]},
                {"role": "tool", "tool_call_id": "t1",
                 "content": json.dumps({"diagnosis": "深谷未收敛"})}]
        out = audit_visible_messages(msgs, _doc([]))
        assert out.ok is False and out.violate_count == 1
        assert out.checked == 1
        assert out.violations[0]["tool_call_id"] == "t1"

    def test_logged_tool_message_zero_violate(self):
        content = tool_context_content({"ok": True, "pf": 0.01})
        msgs = [{"role": "tool", "tool_call_id": "t1", "content": content}]
        out = audit_visible_messages(msgs, _doc([content_digest(content)]))
        assert out.ok is True and out.violate_count == 0

    def test_non_tool_roles_out_of_scope(self):
        """system/user/assistant 构装面不在判据内（模块 docstring 边界）。"""
        msgs = [{"role": "system", "content": "x" * 200},
                {"role": "user", "content": "y" * 200}]
        out = audit_visible_messages(msgs, _doc([]))
        assert out.checked == 0 and out.violate_count == 0


class TestBestEffort105:
    def test_audit_exception_swallowed(self, monkeypatch):
        """#105：校验函数抛错收敛为 ok=False 回执，不阻塞主路径。"""
        def boom(*a, **kw):
            raise RuntimeError("judge down")

        monkeypatch.setattr(sas, "audit_visible_messages", boom)
        out = audit_turn_best_effort([{"role": "tool", "content": "z" * 64}],
                                     _doc([]))
        assert out.ok is False
        assert out.violate_count == 0
        assert "RuntimeError" in out.error

    def test_unreadable_ref_not_raise(self, tmp_path):
        out = audit_turn_best_effort([], tmp_path / "missing.json")
        assert out.ok is False and out.checked == 0


class TestRenderSingleSource:
    def test_tool_context_content_matches_legacy_inline_form(self):
        """渲染单源与历史 builtin 内联形态逐字节同（截断 4000）。"""
        result = {"ok": True, "data": "值" * 50}
        expect = json.dumps(result, ensure_ascii=False, default=str)[:4000]
        assert tool_context_content(result) == expect

    def test_truncation_cap(self):
        from rfauto.service.agent_runtime import TOOL_CONTENT_MAX_CHARS

        big = {"blob": "x" * 10000}
        assert len(tool_context_content(big)) == TOOL_CONTENT_MAX_CHARS


class TestAgentChatHook:
    """端到端（stub runtime，零网络 #139）：摘要写入+比对挂点+开关。"""

    @staticmethod
    def _stub_runtime_class(script):
        from rfauto.service.agent_runtime import AgentRuntime

        class _Stub(AgentRuntime):
            name = "_stub_w2g"

            def __init__(self, **kw):
                self._script = script

            def submit(self, request, executor):
                usage = RuntimeUsage(llm_calls=1)
                self._script(request, executor)
                return RuntimeResult(text="done", messages=request.messages,
                                     usage=usage)

        return _Stub

    @staticmethod
    def _patch_settings(monkeypatch, raw=None):
        from rfauto.service import r3_services

        monkeypatch.setattr(
            r3_services, "get_chat_settings",
            lambda: {"ok": True, "configured": True})
        monkeypatch.setattr(
            r3_services, "get_chat_settings_raw",
            lambda: {"max_tool_rounds": 4, "runtime": "builtin",
                     "model": "stub", **(raw or {})})

    def test_normal_flow_zero_violate_and_digest_logged(
            self, tmp_path, monkeypatch):
        from rfauto.service import agent_runtime, r3_services

        monkeypatch.setattr(agent_runtime, "SESSIONS_DIR",
                            tmp_path / "sess")
        self._patch_settings(monkeypatch)

        def script(request, executor):
            result = executor("list_solvers", {})
            request.messages.append(
                {"role": "tool", "tool_call_id": "t1",
                 "content": tool_context_content(result)})

        monkeypatch.setattr(
            agent_runtime.RuntimeRegistry, "create",
            classmethod(lambda cls, name, **kw: self._stub_runtime_class(script)()))

        chat = r3_services.AgentChat()
        resp = chat.chat("列出求解器")
        assert resp["text"] == "done"
        # 写入侧：executor 摘要已随 tool_calls 留痕
        assert chat.get_tool_calls()[0]["result_digest"]
        # 比对侧：正常流零 violate
        audit = resp["session_audit"]
        assert audit["ok"] is True and audit["violate_count"] == 0
        assert audit["checked"] == 1
        assert chat.stats["audit_violates"] == 0
        # 会话档落盘含 result_digest（留痕可溯载体）
        files = list((tmp_path / "sess").glob("*.json"))
        doc = json.loads(files[0].read_text(encoding="utf-8"))
        assert doc["tool_calls"][0]["result_digest"]

    def test_unlogged_fragment_negative_control_not_blocking(
            self, tmp_path, monkeypatch):
        """负控：未走 executor 的 tool 消息 → violate 计数，主路径照常。"""
        from rfauto.service import agent_runtime, r3_services

        monkeypatch.setattr(agent_runtime, "SESSIONS_DIR",
                            tmp_path / "sess")
        self._patch_settings(monkeypatch)

        def script(request, executor):
            request.messages.append(
                {"role": "tool", "tool_call_id": "t9",
                 "content": json.dumps({"secret_fragment": "x" * 80})})

        monkeypatch.setattr(
            agent_runtime.RuntimeRegistry, "create",
            classmethod(lambda cls, name, **kw: self._stub_runtime_class(script)()))

        chat = r3_services.AgentChat()
        resp = chat.chat("探针")
        assert resp["text"] == "done"  # #105：主路径不阻断
        audit = resp["session_audit"]
        assert audit["ok"] is False and audit["violate_count"] == 1
        assert chat.stats["audit_violates"] == 1

    def test_audit_failure_does_not_block(self, tmp_path, monkeypatch):
        """#105：校验层抛错 → chat 照常返回，回执带 error。"""
        from rfauto.service import agent_runtime, r3_services

        monkeypatch.setattr(agent_runtime, "SESSIONS_DIR",
                            tmp_path / "sess")
        self._patch_settings(monkeypatch)

        def script(request, executor):
            request.messages.append(
                {"role": "tool", "tool_call_id": "t1",
                 "content": "y" * 64})

        monkeypatch.setattr(
            agent_runtime.RuntimeRegistry, "create",
            classmethod(lambda cls, name, **kw: self._stub_runtime_class(script)()))

        def boom(*a, **kw):
            raise ValueError("judge exploded")

        monkeypatch.setattr(sas, "audit_visible_messages", boom)

        chat = r3_services.AgentChat()
        resp = chat.chat("探针")
        assert resp["text"] == "done"
        assert resp["session_audit"]["ok"] is False
        assert "ValueError" in resp["session_audit"]["error"]

    def test_config_off_skips_audit(self, tmp_path, monkeypatch):
        from rfauto.service import agent_runtime, r3_services

        monkeypatch.setattr(agent_runtime, "SESSIONS_DIR",
                            tmp_path / "sess")
        self._patch_settings(monkeypatch,
                             raw={"session_audit_invariant": "off"})

        def script(request, executor):
            request.messages.append(
                {"role": "tool", "tool_call_id": "t9",
                 "content": json.dumps({"unlogged": "z" * 80})})

        monkeypatch.setattr(
            agent_runtime.RuntimeRegistry, "create",
            classmethod(lambda cls, name, **kw: self._stub_runtime_class(script)()))

        chat = r3_services.AgentChat()
        resp = chat.chat("探针")
        assert "session_audit" not in resp  # 开关关：不校验、无注记键
        assert "audit_violates" not in chat.stats
