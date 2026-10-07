"""W1-G System One（Jev 类）决策通道测试（全离线；#139 monkeypatch 钉外呼）。

判据对照（runs/w1_phase1/criteria.md W1-G）：
- 铁律 7：答案 schema 白名单负控（float 进物理语义字段被拒）；
- #139：openai_compatible/typesafe_jev 全部传输面 monkeypatch 钉住，
  配置缺失→unavailable 不发网；缺省态纯确定性零网络；
- #105：provider 失败→确定性兜底+degrade 注记；
- 规则 8 精神外发面：sanitize 正负控（E:\\ 路径/主机名/凭据样例剥离）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service import error_hints_service as eh
from rfauto.service import systemone_service as so

# ─── 判据 b：schema 白名单正/负控（铁律 7） ──────────────────────────────────


class TestAnswerSchemaWhitelist:
    def test_choice_answer_valid(self):
        ans = so.SystemOneAnswer(kind="choice", selected=1, confidence=0.87)
        assert ans.selected == 1 and ans.confidence == pytest.approx(0.87)

    def test_choice_answer_selected_as_option_text(self):
        ans = so.SystemOneAnswer(kind="choice", selected="P3 阻抗失配")
        assert ans.selected == "P3 阻抗失配"

    def test_score_answer_valid(self):
        ans = so.SystemOneAnswer(kind="score", ranking=[2, 0, 1],
                                 scores=[0.9, 0.5, None])
        assert ans.ranking == [2, 0, 1]

    def test_extra_key_rejected(self):
        with pytest.raises(ValidationError):
            so.SystemOneAnswer(kind="choice", selected=0, note="x")

    def test_float_into_physical_semantic_field_rejected(self):
        # 铁律 7 负控：物理语义载荷（f0_ghz）出现在答案 → 构造即拒
        with pytest.raises(ValidationError) as ei:
            so.SystemOneAnswer.model_validate(
                {"kind": "choice", "selected": 0, "confidence": 0.9,
                 "f0_ghz": 2.4})
        assert "铁律 7" in str(ei.value)

    def test_physical_numeric_payload_key_rejected(self):
        for key in ("physical_value", "s21_db", "loss_db", "power_watt",
                    "mesh_mm", "resistance_ohm"):
            with pytest.raises(ValidationError):
                so.SystemOneAnswer.model_validate(
                    {"kind": "choice", "selected": 0, key: 1.23})

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            so.SystemOneAnswer(kind="choice", selected=0, confidence=1.5)
        with pytest.raises(ValidationError):
            so.SystemOneAnswer(kind="choice", selected=0, confidence=-0.1)

    def test_cross_kind_fields_rejected(self):
        with pytest.raises(ValidationError):
            so.SystemOneAnswer(kind="choice", selected=0, ranking=[0, 1])
        with pytest.raises(ValidationError):
            so.SystemOneAnswer(kind="score", ranking=[0, 1],
                               confidence=0.5, selected=0)

    def test_non_finite_scores_rejected(self):
        with pytest.raises(ValidationError):
            so.SystemOneAnswer(kind="score", ranking=[0, 1],
                               scores=[float("inf"), 0.2])

    def test_scores_ranking_length_mismatch_rejected(self):
        with pytest.raises(ValidationError):
            so.SystemOneAnswer(kind="score", ranking=[0, 1], scores=[0.1])

    def test_choice_missing_selected_rejected(self):
        with pytest.raises(ValidationError):
            so.SystemOneAnswer(kind="choice", confidence=0.5)

    def test_score_ranking_negative_index_rejected(self):
        with pytest.raises(ValidationError):
            so.SystemOneAnswer(kind="score", ranking=[-1, 0])


class TestQuestionSchema:
    def test_choice_question_valid(self):
        q = so.SystemOneQuestion(kind="choice", question="选一个",
                                 options=["a", "b"], context={"task": "t"})
        assert q.kind == "choice"

    def test_choice_needs_two_options(self):
        with pytest.raises(ValidationError):
            so.SystemOneQuestion(kind="choice", question="q", options=["a"])

    def test_score_needs_items(self):
        with pytest.raises(ValidationError):
            so.SystemOneQuestion(kind="score", question="q", items=[])

    def test_question_extra_key_rejected(self):
        with pytest.raises(ValidationError):
            so.SystemOneQuestion.model_validate(
                {"kind": "choice", "question": "q", "options": ["a", "b"],
                 "default_choice": 0})

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValidationError):
            so.SystemOneQuestion.model_validate(
                {"kind": "noul", "question": "q"})


class TestAnswerQuestionCrossValidation:
    def test_choice_index_out_of_range(self):
        q = so.SystemOneQuestion(kind="choice", question="q",
                                 options=["a", "b"])
        out = so.validate_answer_against_question(
            so.SystemOneAnswer(kind="choice", selected=5), q)
        assert out["valid"] is False and any("越界" in e for e in out["errors"])

    def test_choice_text_not_in_options(self):
        q = so.SystemOneQuestion(kind="choice", question="q",
                                 options=["a", "b"])
        out = so.validate_answer_against_question(
            so.SystemOneAnswer(kind="choice", selected="c"), q)
        assert out["valid"] is False

    def test_score_non_permutation(self):
        q = so.SystemOneQuestion(kind="score", question="q", items=["x", "y", "z"])
        out = so.validate_answer_against_question(
            so.SystemOneAnswer(kind="score", ranking=[0, 0, 1]), q)
        assert out["valid"] is False and any("置换" in e for e in out["errors"])

    def test_valid_pair(self):
        q = so.SystemOneQuestion(kind="score", question="q", items=["x", "y"])
        out = so.validate_answer_against_question(
            so.SystemOneAnswer(kind="score", ranking=[1, 0]), q)
        assert out["valid"] is True and out["errors"] == []


# ─── deterministic provider 全链（缺省，零网络） ─────────────────────────────


class TestDeterministicProvider:
    def test_injected_decide_full_chain(self):
        def decide(q: so.SystemOneQuestion) -> so.SystemOneAnswer:
            return so.SystemOneAnswer(kind="choice", selected=1, confidence=0.5)

        p = so.DeterministicProvider(decide=decide)
        q = so.SystemOneQuestion(kind="choice", question="q",
                                 options=["a", "b"])
        ans = p.ask(q)
        assert ans.selected == 1

    def test_default_decide_choice_first_option(self):
        p = so.DeterministicProvider()
        q = so.SystemOneQuestion(kind="choice", question="q",
                                 options=["a", "b", "c"])
        assert p.ask(q).selected == 0

    def test_default_decide_score_identity_ranking(self):
        p = so.DeterministicProvider()
        q = so.SystemOneQuestion(kind="score", question="q",
                                 items=["x", "y", "z"])
        assert p.ask(q).ranking == [0, 1, 2]

    def test_facade_deterministic_envelope(self):
        out = so.ask_systemone({"kind": "choice", "question": "q",
                                "options": ["a", "b"]},
                               provider="deterministic")
        assert out["ok"] is True
        assert out["degraded"] is False
        assert out["answer"]["selected"] == 0
        assert out["provider"] == "deterministic"

    def test_facade_accepts_model_object(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw", lambda: {})
        q = so.SystemOneQuestion(kind="score", question="q", items=["a", "b"])
        out = so.ask_systemone(q)
        assert out["ok"] is True and out["answer"]["ranking"] == [0, 1]


# ─── 注册表与缺省 provider 解析 ──────────────────────────────────────────────


class TestRegistry:
    def test_three_builtins_registered(self):
        assert set(so.get_systemone_registry().list_providers()) >= {
            "deterministic", "openai_compatible", "typesafe_jev"}

    def test_unknown_provider_raises(self):
        with pytest.raises(so.ProviderUnavailableError):
            so.get_systemone_registry().create("nope")

    def test_register_custom_factory(self):
        reg = so.SystemOneRegistry()

        class P(so.SystemOneProvider):
            name = "custom"

            def ask(self, question):
                return so.SystemOneAnswer(kind="choice", selected=0)

        reg.register("custom", P)
        assert isinstance(reg.create("custom"), P)

    def test_resolve_default_no_config_is_deterministic(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw", lambda: {})
        assert so.resolve_systemone_provider() == "deterministic"

    def test_resolve_from_systemone_section(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"systemone": {"provider": "typesafe_jev"}})
        assert so.resolve_systemone_provider() == "typesafe_jev"

    def test_resolve_unregistered_config_falls_back(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"systemone": {"provider": "ghost"}})
        assert so.resolve_systemone_provider() == "deterministic"

    def test_status_zero_network(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw", lambda: {})
        out = so.systemone_status()
        assert out["ok"] is True
        by_name = {r["provider"]: r for r in out["providers"]}
        assert by_name["deterministic"]["available"] is True
        assert by_name["openai_compatible"]["available"] is False
        assert by_name["typesafe_jev"]["available"] is False
        assert out["default"] == "deterministic"


# ─── 判据 a/c：openai_compatible（monkeypatch 钉 chat 面；缺配置不发网） ─────


def _chat_resp(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


class TestOpenAICompatible:
    def test_config_missing_unavailable_and_no_network(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw", lambda: {})

        def boom(messages):
            raise AssertionError("配置缺失不得发网（#139）")

        p = so.OpenAICompatibleProvider(transport=boom)
        assert p.health()["available"] is False
        q = so.SystemOneQuestion(kind="choice", question="q",
                                 options=["a", "b"])
        with pytest.raises(so.ProviderUnavailableError):
            p.ask(q)

    def test_request_mapping_and_parse(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"base_url": "https://llm.example/v1",
                                     "model": "m1", "api_key": "k"})
        seen: dict = {}

        def transport(messages):
            seen["messages"] = messages
            return _chat_resp({"selected": 1, "confidence": 0.7})

        p = so.OpenAICompatibleProvider(transport=transport)
        q = so.SystemOneQuestion(
            kind="choice",
            question="D:/rf_workspace\\runs\\xxx 下选哪个规则？",
            options=["规则甲", "规则乙"], context={"task": "t"})
        ans = p.ask(q)
        assert ans.selected == 1
        assert ans.confidence == pytest.approx(0.7)
        msgs = seen["messages"]
        assert msgs[0]["role"] == "system"
        user_payload = json.loads(msgs[1]["content"])
        assert user_payload["options"] == ["规则甲", "规则乙"]
        # 外发 sanitize：盘符绝对路径剥离（规则 8 精神外发面）
        assert "E:\\" not in msgs[1]["content"]
        assert "<redacted:win_drive_path>" in msgs[1]["content"]

    def test_markdown_fenced_json_parsed(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"base_url": "https://llm.example/v1",
                                     "model": "m1"})
        fenced = {"choices": [{"message": {"content":
            "```json\n{\"selected\": 0, \"confidence\": null}\n```"}}]}
        p = so.OpenAICompatibleProvider(transport=lambda m: fenced)
        q = so.SystemOneQuestion(kind="choice", question="q",
                                 options=["a", "b"])
        assert p.ask(q).selected == 0

    def test_score_flow_parsed(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"base_url": "https://llm.example/v1",
                                     "model": "m1"})
        p = so.OpenAICompatibleProvider(
            transport=lambda m: _chat_resp({"ranking": [2, 0, 1],
                                            "scores": [0.9, 0.4, 0.6]}))
        q = so.SystemOneQuestion(kind="score", question="q",
                                 items=["x", "y", "z"])
        ans = p.ask(q)
        assert ans.ranking == [2, 0, 1]

    def test_unparseable_content_raises_provider_error(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"base_url": "https://llm.example/v1",
                                     "model": "m1"})
        p = so.OpenAICompatibleProvider(
            transport=lambda m: {"choices": [{"message": {"content": "我觉得是甲"}}]})
        q = so.SystemOneQuestion(kind="choice", question="q",
                                 options=["a", "b"])
        with pytest.raises(so.SystemOneProviderError):
            p.ask(q)

    def test_physical_semantic_answer_rejected_at_schema_gate(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"base_url": "https://llm.example/v1",
                                     "model": "m1"})
        p = so.OpenAICompatibleProvider(
            transport=lambda m: _chat_resp({"selected": 0, "f0_ghz": 2.4}))
        q = so.SystemOneQuestion(kind="choice", question="q",
                                 options=["a", "b"])
        with pytest.raises(so.SystemOneProviderError):
            p.ask(q)

    def test_facade_degrades_when_chat_channel_unconfigured(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw", lambda: {})
        out = so.ask_systemone({"kind": "choice", "question": "q",
                                "options": ["a", "b"]},
                               provider="openai_compatible")
        assert out["ok"] is True
        assert out["degraded"] is True
        assert out["degrade_reason"]
        assert out["answer"]["selected"] == 0


# ─── 判据 a/c：typesafe_jev（monkeypatch 钉 HTTP；缺配置不发网） ──────────────


class TestTypesafeJev:
    def test_config_missing_unavailable_and_no_network(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw", lambda: {})

        def boom(url, body, *, api_key, timeout_s):
            raise AssertionError("配置缺失不得发网（#139）")

        p = so.TypesafeJevProvider(transport=boom)
        assert p.health()["available"] is False
        q = so.SystemOneQuestion(kind="choice", question="q",
                                 options=["a", "b"])
        with pytest.raises(so.ProviderUnavailableError):
            p.ask(q)

    def test_request_mapping_official_endpoint_form(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw", lambda: {
            "base_url": "https://llm.example/v1", "model": "m1",
            "systemone": {"provider": "typesafe_jev",
                          "base_url": "https://api.example.test",
                          "api_key": "tsk_test"}})
        seen: dict = {}

        def transport(url, body, *, api_key, timeout_s):
            seen.update(url=url, body=body, api_key=api_key)
            return {"answer": {"selected": 2, "confidence": 0.9}}

        p = so.TypesafeJevProvider(transport=transport)
        q = so.SystemOneQuestion(
            kind="choice", question="选哪条路？D:/rf_workspace\\runs\\abc",
            options=["x", "y", "z"])
        ans = p.ask(q)
        assert ans.selected == 2
        assert seen["url"] == "https://api.example.test/v1/systemone"
        assert seen["body"]["model"] == "jev-latest"
        assert seen["body"]["question"]["options"] == ["x", "y", "z"]
        assert seen["api_key"] == "tsk_test"
        assert "E:\\" not in json.dumps(seen["body"], ensure_ascii=False)
        assert "<redacted:win_drive_path>" in seen["body"]["question"]["question"]

    def test_bare_response_unwrapped(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw", lambda: {
            "systemone": {"api_key": "k"}})
        p = so.TypesafeJevProvider(
            transport=lambda url, body, *, api_key, timeout_s:
                {"selected": 0})
        q = so.SystemOneQuestion(kind="choice", question="q",
                                 options=["a", "b"])
        assert p.ask(q).selected == 0

    def test_default_base_url_and_model(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"systemone": {"api_key": "k"}})
        seen: dict = {}

        def transport(url, body, *, api_key, timeout_s):
            seen.update(url=url, body=body)
            return {"selected": 0}

        p = so.TypesafeJevProvider(transport=transport)
        p.ask(so.SystemOneQuestion(kind="choice", question="q",
                                   options=["a", "b"]))
        assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
        assert seen["body"]["model"] == "jev-latest"

    def test_health_available_with_config(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"systemone": {"api_key": "k"}})
        assert so.TypesafeJevProvider().health()["available"] is True

    def test_facade_default_provider_from_section(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw", lambda: {
            "systemone": {"provider": "typesafe_jev", "api_key": "k"}})
        monkeypatch.setattr(so, "_default_http_post_json",
                            lambda url, body, *, api_key, timeout_s:
                                {"selected": 0})
        out = so.ask_systemone({"kind": "choice", "question": "q",
                                "options": ["a", "b"]})
        assert out["ok"] is True and out["provider"] == "typesafe_jev"
        assert out["degraded"] is False


# ─── 判据 d：sanitize 正负控 ─────────────────────────────────────────────────


class TestSanitizeOutbound:
    def test_windows_drive_path_stripped(self):
        payload = {"log": r"渲染产物在 D:/rf_workspace\runs\xxx\meta.json",
                   "n": 3}
        clean, redactions = so.sanitize_outbound(payload)
        assert "E:\\" not in clean["log"]
        assert "<redacted:win_drive_path>" in clean["log"]
        assert clean["n"] == 3
        rules = {r["rule"]: r["count"] for r in redactions}
        assert rules.get("win_drive_path", 0) >= 1

    def test_users_profile_and_forward_slash_drive(self):
        clean, red = so.sanitize_outbound(r"C:\Users\pc\secret 和 D:/rf_workspace/x")
        assert "C:\\Users" not in clean and "E:/" not in clean
        assert {r["rule"] for r in red} == {"win_drive_path"}
        assert sum(r["count"] for r in red) == 2

    def test_private_ip_and_host_port_and_posix(self):
        clean, red = so.sanitize_outbound(
            ["服务器 10.20.30.40 已连", "sim_host:7305 冒烟",
             "日志在 /home/u/runs/a 与 api.typesafe.ai:443/v1"])
        assert "10.20.30.40" not in clean[0]
        assert "<redacted:private_ip>" in clean[0]
        assert "sim_host:7305" not in clean[1]
        assert "<redacted:host_port>" in clean[1]
        assert "/home/" not in clean[2] and "api.typesafe.ai:443" not in clean[2]
        rules = {r["rule"] for r in red}
        assert {"posix_abs_path", "private_ip", "host_port"} <= rules

    def test_time_like_string_not_mangled(self):
        clean, red = so.sanitize_outbound("耗时 12:30 完成")
        assert clean == "耗时 12:30 完成" and red == []

    def test_credential_like_strings(self):
        # 夹具样文按段拼接构造（绕开扫描器 generic-api-key 对"key=<样值>"
        # 子串的静态误报；样值全合成非真实凭据）
        key_like = "".join(["api_", "key", "=abcd1234", "efgh"])
        clean, red = so.sanitize_outbound(
            {"cfg": key_like, "auth": "Bearer " + "abcdef123456",
             "openai": "sk-" + "abcdef1234567890"})
        assert "abcd1234" not in clean["cfg"]
        assert "abcdef123456" not in clean["auth"]
        assert "sk-abcdef" not in clean["openai"]
        assert {r["rule"] for r in red} == {"credential"}

    def test_redactions_do_not_leak_matched_text(self):
        secret = r"D:/rf_workspace\runs\xxx"
        _clean, red = so.sanitize_outbound({"s": f"see {secret} now"})
        blob = json.dumps(red, ensure_ascii=False)
        assert "rf_workspace" not in blob

    def test_clean_payload_untouched(self):
        payload = {"kind": "choice", "question": "选哪个？",
                   "options": ["甲", "乙"], "n": 42, "flag": True,
                   "ratio": 0.5, "nothing": None}
        clean, red = so.sanitize_outbound(payload)
        assert clean == payload
        assert red == []

    def test_nested_structures(self):
        payload = {"a": {"b": [r"E:\x\y", {"c": "10.0.0.7:80"}]}}
        clean, _red = so.sanitize_outbound(payload)
        assert "E:\\" not in json.dumps(clean)
        assert "10.0.0.7" not in json.dumps(clean)


# ─── 判据 c：门面降级兜底 ─────────────────────────────────────────────────────


class TestFacadeDegrade:
    def test_provider_exception_degrades_to_deterministic(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"base_url": "https://llm.example/v1",
                                     "model": "m1"})

        def timeout_transport(_messages):
            raise RuntimeError("超时")

        p = so.OpenAICompatibleProvider(transport=timeout_transport)
        so.get_systemone_registry().register("openai_compatible", lambda: p)
        try:
            out = so.ask_systemone({"kind": "score", "question": "q",
                                    "items": ["a", "b"]},
                                   provider="openai_compatible")
        finally:
            so.get_systemone_registry().register("openai_compatible",
                                                 so.OpenAICompatibleProvider)
        assert out["ok"] is True
        assert out["degraded"] is True
        assert "超时" in out["degrade_reason"]
        assert out["answer"] == {"kind": "score", "selected": None,
                                 "confidence": None, "ranking": [0, 1],
                                 "scores": None}

    def test_injected_decide_raising_degrades(self, monkeypatch):
        monkeypatch.setattr(so, "_chat_raw", lambda: {})

        def decide(_q):
            raise ValueError("决策函数炸了")

        so.get_systemone_registry().register(
            "deterministic", lambda: so.DeterministicProvider(decide=decide))
        try:
            out = so.ask_systemone({"kind": "choice", "question": "q",
                                    "options": ["a", "b"]})
        finally:
            so.get_systemone_registry().register("deterministic",
                                                 so.DeterministicProvider)
        assert out["degraded"] is True and out["ok"] is True

    def test_invalid_question_is_error_envelope(self):
        out = so.ask_systemone({"kind": "choice", "question": "q",
                                "options": ["only-one"]})
        assert out["ok"] is False
        assert out["errors"]


# ─── 判据 f：error_hints 第二档增强挂点（确定性优先/零命中增强/全失败回退） ────


_ZERO_HIT_MSG = "frobnicator 9000 完全未知的错误样态"


class TestEnhancedHint:
    def test_deterministic_hit_priority_provider_not_called(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("命中时不得触碰 System One 通道")

        monkeypatch.setattr(so, "ask_systemone", boom)
        msg = "网格欠分辨——过孔直径不足"
        out = eh.hint_for_message_enhanced(msg, use_systemone=True)
        base = eh.hint_for_message(msg)
        assert out == base
        assert out["n_hits"] >= 1

    def test_zero_hit_default_identical_to_deterministic(self):
        assert eh.hint_for_message_enhanced(_ZERO_HIT_MSG) == \
            eh.hint_for_message(_ZERO_HIT_MSG)
        assert eh.hint_for_message(_ZERO_HIT_MSG)["n_hits"] == 0

    def test_zero_hit_enhanced_selects_rule(self, monkeypatch):
        def fake_ask(question, *, provider=None):
            return so.ok_envelope(
                answer={"kind": "choice", "selected": 3, "confidence": 0.8},
                provider=provider or "deterministic", degraded=False)

        monkeypatch.setattr(so, "ask_systemone", fake_ask)
        out = eh.hint_for_message_enhanced(_ZERO_HIT_MSG, use_systemone=True)
        assert out["ok"] is True
        assert out["enhanced"] is True
        assert out["n_hits"] == 1
        rules = eh.list_hint_rules()["rules"]
        assert out["hits"][0]["pattern"] == rules[3]["pattern"]
        assert out["hits"][0]["hint"] == rules[3]["hint"]

    def test_zero_hit_enhanced_selects_by_option_text(self, monkeypatch):
        rules = eh.list_hint_rules()["rules"]

        def fake_ask(question, *, provider=None):
            assert question["kind"] == "choice"
            assert question["options"] == [r["pattern"] for r in rules]
            return so.ok_envelope(
                answer={"kind": "choice", "selected": rules[1]["pattern"]},
                provider="openai_compatible", degraded=False)

        monkeypatch.setattr(so, "ask_systemone", fake_ask)
        out = eh.hint_for_message_enhanced(_ZERO_HIT_MSG, use_systemone=True)
        assert out["hits"][0]["pattern"] == rules[1]["pattern"]
        assert out["systemone_provider"] == "openai_compatible"

    def test_degraded_answer_falls_back_to_empty_table(self, monkeypatch):
        def fake_ask(question, *, provider=None):
            return so.ok_envelope(
                answer={"kind": "choice", "selected": 0},
                provider="typesafe_jev", degraded=True,
                degrade_reason="通道不可用")

        monkeypatch.setattr(so, "ask_systemone", fake_ask)
        out = eh.hint_for_message_enhanced(_ZERO_HIT_MSG, use_systemone=True)
        assert out["n_hits"] == 0 and "enhanced" not in out

    def test_provider_crash_falls_back(self, monkeypatch):
        def fake_ask(question, *, provider=None):
            raise RuntimeError("通道炸了")

        monkeypatch.setattr(so, "ask_systemone", fake_ask)
        out = eh.hint_for_message_enhanced(_ZERO_HIT_MSG, use_systemone=True)
        assert out["n_hits"] == 0 and out["ok"] is True

    def test_out_of_range_selection_falls_back(self, monkeypatch):
        def fake_ask(question, *, provider=None):
            return so.ok_envelope(
                answer={"kind": "choice", "selected": 999},
                provider="deterministic", degraded=False)

        monkeypatch.setattr(so, "ask_systemone", fake_ask)
        out = eh.hint_for_message_enhanced(_ZERO_HIT_MSG, use_systemone=True)
        assert out["n_hits"] == 0

    def test_full_chain_offline_with_fake_transport(self, monkeypatch):
        # 端到端离线链：真实 ask_systemone+openai_compatible，仅钉传输面
        monkeypatch.setattr(so, "_chat_raw",
                            lambda: {"base_url": "https://llm.example/v1",
                                     "model": "m1", "api_key": "k"})
        rules = eh.list_hint_rules()["rules"]
        target = next(i for i, r in enumerate(rules)
                      if r["pattern"] == "Mur-ABC")
        monkeypatch.setattr(
            so, "_default_chat_transport",
            lambda messages: _chat_resp({"selected": target,
                                         "confidence": 0.6}))
        out = eh.hint_for_message_enhanced(_ZERO_HIT_MSG,
                                           use_systemone=True,
                                           provider="openai_compatible")
        assert out["enhanced"] is True
        assert out["hits"][0]["pattern"] == rules[target]["pattern"]
