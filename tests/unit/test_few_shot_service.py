"""AD-3 few-shot 精选注入面测试（few_shot_service + agent_runtime.extra_system）。

LLM 通道纪律（#139）：本面全部离线——会话档/records 均为合成 fixture，
无任何 LLM/网络调用；extra_system 注入用 scripted transport 钉死。
"""

from __future__ import annotations

import json

from rfauto.service.agent_runtime import BuiltinOpenAIRuntime, RuntimeRequest
from rfauto.service.few_shot_service import (
    build_few_shot_system,
    candidates_from_records,
    mine_session_candidates,
    render_few_shot_section,
    select_few_shots,
    session_is_success,
    tokenize,
)


def _session_doc(session_id: str, *, turns: int = 1, tools: int = 1,
                 fallback: bool = False, final: str = "已完成提案",
                 schema: str = "rfauto-chat-session-v1") -> dict:
    history = [{"role": "user", "content": "调优 wilkinson 功分器参数"},
               {"role": "assistant", "content": final}]
    if fallback:
        history[1]["content"] = "[LLM 调用失败，已回退指令模式: x]\n" + final
    return {"schema": schema, "session_id": session_id,
            "history": history,
            "tool_calls": [{"action": f"tool_{i}"} for i in range(tools)],
            "stats": {"turns": turns}}


class TestSessionSuccessCriteria:
    def test_happy_path_is_success(self):
        assert session_is_success(_session_doc("s1"))

    def test_zero_turns_rejected(self):
        assert not session_is_success(_session_doc("s1", turns=0))

    def test_no_tools_rejected(self):
        assert not session_is_success(_session_doc("s1", tools=0))

    def test_llm_fallback_mark_rejected(self):
        assert not session_is_success(_session_doc("s1", fallback=True))

    def test_empty_final_rejected(self):
        assert not session_is_success(_session_doc("s1", final="   "))

    def test_unknown_schema_rejected(self):
        assert not session_is_success(_session_doc("s1", schema="other/v9"))

    def test_tokenize_words_and_cjk(self):
        tokens = tokenize("Wilkinson 功分器 arm_len_mm 调优")
        assert "wilkinson" in tokens and "arm_len_mm" not in tokens
        assert "功" in tokens and "分" in tokens


class TestMineAndSelect:
    def test_mine_skips_bad_and_unsuccessful(self, tmp_path):
        good = _session_doc("chat_good")
        (tmp_path / "chat_good.json").write_text(
            json.dumps(good, ensure_ascii=False), encoding="utf-8")
        (tmp_path / "chat_bad.json").write_text("{broken", encoding="utf-8")
        (tmp_path / "chat_fail.json").write_text(
            json.dumps(_session_doc("chat_fail", tools=0), ensure_ascii=False),
            encoding="utf-8")
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        out = mine_session_candidates(tmp_path)
        assert [c["id"] for c in out] == ["chat_good"]
        assert out[0]["tools"] == ["tool_0"]
        assert out[0]["task_text"].startswith("调优")

    def test_mine_missing_dir_empty(self, tmp_path):
        assert mine_session_candidates(tmp_path / "nope") == []

    def test_records_source_filters_error_and_empty(self):
        recs = [
            {"id": "ok1", "prompt": "p1",
             "trajectory": [{"tool": "run_detail"}]},
            {"id": "bad", "prompt": "p2",
             "trajectory": [{"tool": "run_detail"}], "error": "boom"},
            {"id": "empty", "prompt": "p3", "trajectory": []},
        ]
        out = candidates_from_records(recs)
        assert [c["id"] for c in out] == ["ok1"]

    def test_select_orders_by_relevance_then_id(self):
        cands = [
            {"id": "b", "task_text": "branchline 电桥调优", "tools": []},
            {"id": "a", "task_text": "wilkinson 功分器调优", "tools": []},
            {"id": "c", "task_text": "wilkinson 功分器调优", "tools": []},
        ]
        picked = select_few_shots("wilkinson 功分器参数提案", cands, k=2)
        assert [c["id"] for c in picked] == ["a", "c"]

    def test_select_k_cap_and_zero(self):
        cands = [{"id": f"c{i}", "task_text": "t", "tools": []}
                 for i in range(5)]
        assert len(select_few_shots("t", cands, k=3)) == 3
        assert select_few_shots("t", cands, k=0) == []


class TestRenderAndBuild:
    def test_render_contains_tools_and_snippet(self):
        section = render_few_shot_section([
            {"id": "x", "source": "record", "task_text": "做任务",
             "tools": ["run_detail", "propose_params"],
             "result_snippet": "给出提案"}])
        assert "### 案例 1（x，来源 record）" in section
        assert "`run_detail → propose_params`" in section
        assert "禁止照抄" in section

    def test_render_empty_is_empty(self):
        assert render_few_shot_section([]) == ""

    def test_build_from_records(self):
        recs = [{"id": "t1", "prompt": "wilkinson 调优",
                 "trajectory": [{"tool": "run_detail"}]}]
        out = build_few_shot_system("wilkinson 调优", records=recs)
        assert out["ok"] and out["n_candidates"] == 1
        assert out["exemplars"][0]["id"] == "t1"
        assert out["section"].startswith("\n")

    def test_build_no_candidates_zero_section(self, tmp_path):
        out = build_few_shot_system("任意任务", sessions_dir=tmp_path)
        assert out["ok"] and out["section"] == "" and out["n_candidates"] == 0


class TestRuntimeExtraSystemInjection:
    """agent_runtime.RuntimeRequest.extra_system 最小追加的契约钉。"""

    @staticmethod
    def _transport(captured: list):
        def transport(messages, tools):
            captured.append([dict(m) for m in messages])
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        return transport

    def test_default_none_is_byte_identical_and_no_mutation(self):
        msgs = [{"role": "system", "content": "S"},
                {"role": "user", "content": "U"}]
        captured: list = []
        runtime = BuiltinOpenAIRuntime(transport=self._transport(captured))
        out = runtime.submit(RuntimeRequest(messages=msgs, max_rounds=1),
                             lambda n, a: {})
        assert len(msgs) == 2  # 调用方列表零改动（缺省路径与旧版逐字节同）
        assert len(out.messages) == 2
        assert captured[0][0]["content"] == "S"

    def test_extra_system_inserted_after_system_block(self):
        msgs = [{"role": "system", "content": "S1"},
                {"role": "system", "content": "S2"},
                {"role": "user", "content": "U"}]
        captured: list = []
        runtime = BuiltinOpenAIRuntime(transport=self._transport(captured))
        out = runtime.submit(RuntimeRequest(messages=msgs, max_rounds=1,
                                            extra_system="FEWSHOT-SECTION"),
                             lambda n, a: {})
        assert len(msgs) == 3  # 调用方列表不被注入污染
        assert out.messages[2] == {"role": "system",
                                   "content": "FEWSHOT-SECTION"}
        assert [m["role"] for m in captured[0][:3]] == [
            "system", "system", "system"]
        assert captured[0][3]["role"] == "user"

    def test_few_shot_section_feeds_extra_system(self, tmp_path):
        from rfauto.service.few_shot_service import build_few_shot_system

        recs = [{"id": "t1", "prompt": "wilkinson 调优",
                 "trajectory": [{"tool": "run_detail"}]}]
        section = build_few_shot_system("wilkinson 调优", records=recs)["section"]
        assert section
        runtime = BuiltinOpenAIRuntime(
            transport=self._transport([]))
        out = runtime.submit(RuntimeRequest(
            messages=[{"role": "user", "content": "U"}], max_rounds=1,
            extra_system=section), lambda n, a: {})
        assert "成功案例参考" in out.messages[0]["content"]
