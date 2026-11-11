"""T-Q15 LLM 错误透传+接通性分诊单测（aurora_q Q-W0-2）。

钉住 llm_error_service 归一层五形态（任务书验收口径）+ 扩展形态，
全部 monkeypatch 构造异常对象，**零网络**（#139：配置即外网分支禁真网）：

- 429 限速（body error.code=rate_limit_exceeded / 无 body code 状态兜底）；
- 429 额度（body error.code=credit_balance_exhausted / insufficient_quota——
  body 优先压过状态码兜底，429 无法区分额度 vs 限速的用户痛点根除面）；
- 401 认证（invalid_api_key）；
- 402 额度（LiteLLM 专收语义，无 body code 也判额度）；
- unknown 兜底（任意异常 message 透传）；
- 5xx 网关 / 超时 / SDK 异常类名族（duck-typed 零 import）；
- pydantic_ai_runtime.submit 归一层接线（HTTP 异常→LlmCallError；
  PydanticAINotInstalled 透传契约不破）；
- chat 回退路径透传（text 带 code+advice、llm_error 结构化键、
  [LLM 调用失败 前缀契约——few_shot 成功判据依赖）；
- test_llm_connection 接通性检测（未配置/成功/429 额度/401，通道全钉）。

runs/ 湖隔离（#144 家族）：chat 路径用例 monkeypatch.chdir(tmp_path) +
SESSIONS_DIR 重定向，不向真实 runs/ 落任何会话档/trace。
"""

from __future__ import annotations

import email.message
import io
import json
import sys
import urllib.error
from typing import Any

import pytest

from rfauto.service.envelope import error_envelope
from rfauto.service.llm_error_service import (
    ADVICE_BY_CODE,
    CODE_AUTH,
    CODE_CONNECTION,
    CODE_CREDIT,
    CODE_NOT_CONFIGURED,
    CODE_PROVIDER,
    CODE_RATE_LIMIT,
    CODE_UNKNOWN,
    LlmCallError,
    LlmError,
    classify_llm_error,
    llm_error_envelope,
)

# 注意：``test_llm_connection``（service 函数）不得进本模块顶层 import——
# pytest 收集器会把 test_* 开头的**导入名**也当测试收集（本次开发实证：
# 顶层 import 后被收集执行，读真实 configs/chat_settings.yaml 触发一次
# 真网探针，违反 #139 零网络纪律）——接通性用例一律函数内延迟导入。


def _conn() -> dict[str, Any]:
    """延迟导入的接通性检测入口（避免顶层 test_* 名被 pytest 误收集）。"""
    from rfauto.service.llm_error_service import test_llm_connection

    return test_llm_connection()

# ─── 异常构造器（零网络：urllib HTTPError 带 bytes 响应体）───────────────────


def http_error(status: int, body: dict[str, Any] | str = "") -> urllib.error.HTTPError:
    """构造带响应体的 urllib HTTPError（builtin 通道的真实异常形态）。"""
    raw = (json.dumps(body) if isinstance(body, dict) else str(body)).encode("utf-8")
    return urllib.error.HTTPError(
        "https://api.test/v1/chat/completions", status, f"HTTP Error {status}",
        email.message.Message(), io.BytesIO(raw))


class FakeStatusError(Exception):
    """duck-typed openai SDK APIStatusError（status_code+body，零 SDK import）。"""

    def __init__(self, status: int, body: dict[str, Any] | str):
        super().__init__(f"Error code: {status} - {body}")
        self.status_code = status
        self.body = body


def make_named_exc(name: str, module: str) -> type[Exception]:
    """类名族仿造（LiteLLM/Anthropic 分型兼容面：只读 __name__/__module__）。"""
    return type(name, (Exception,), {"__module__": module})


# ─── 归一层五形态（任务书验收口径）───────────────────────────────────────────


class TestClassifyFiveForms:
    def test_429_rate_limit(self):
        info = classify_llm_error(http_error(429, {
            "error": {"code": "rate_limit_exceeded",
                      "message": "Too many requests, retry later"}}))
        assert info.code == CODE_RATE_LIMIT
        assert info.http_status == 429
        assert info.provider_code == "rate_limit_exceeded"
        assert "Too many requests" in info.message  # 原始透传
        assert info.advice == ADVICE_BY_CODE[CODE_RATE_LIMIT]
        assert "限速" in info.advice

    def test_429_credit_body_beats_status_fallback(self):
        """429 + body credit_balance_exhausted → 额度（body 优先级最高）。"""
        info = classify_llm_error(http_error(429, {
            "error": {"code": "credit_balance_exhausted",
                      "message": "You have exhausted your credit balance"}}))
        assert info.code == CODE_CREDIT
        assert info.http_status == 429
        assert "credit balance" in info.message
        assert "额度" in info.advice

    def test_429_openai_insufficient_quota_is_credit(self):
        """OpenAI insufficient_quota 走 429——body code 识别为额度。"""
        info = classify_llm_error(http_error(429, {
            "error": {"code": "insufficient_quota",
                      "message": "You exceeded your current quota"}}))
        assert info.code == CODE_CREDIT

    def test_429_no_body_code_falls_to_status(self):
        """429 无 body code → 状态码兜底 rate_limit_exceeded。"""
        info = classify_llm_error(http_error(429))
        assert info.code == CODE_RATE_LIMIT
        assert info.http_status == 429

    def test_401_authentication(self):
        info = classify_llm_error(http_error(401, {
            "error": {"code": "invalid_api_key", "message": "Incorrect API key"}}))
        assert info.code == CODE_AUTH
        assert info.http_status == 401
        assert "api_key" in info.advice or "key" in info.advice

    def test_402_credit_litellm_semantics(self):
        """402 → 额度（LiteLLM PaymentRequiredError 专收语义，无 body code 也判）。"""
        info = classify_llm_error(http_error(402, {"error": {"message": "payment required"}}))
        assert info.code == CODE_CREDIT
        assert "充值" in info.advice

    def test_unknown_fallback_message_passthrough(self):
        info = classify_llm_error(RuntimeError("boom"))
        assert info.code == CODE_UNKNOWN
        assert info.message == "boom"  # 未映射兜底：原始 message 透传不吞
        assert info.advice == ADVICE_BY_CODE[CODE_UNKNOWN]

    def test_five_fields_always_present(self):
        info = classify_llm_error(http_error(429))
        d = info.as_dict()
        for key in ("code", "provider", "http_status", "message", "advice"):
            assert key in d
        assert "provider_code" in d  # 分诊第一手证据（body error.code 原值）


# ─── 扩展形态（5xx/超时/SDK 异常族/Anthropic body 风格/幂等）────────────────


class TestClassifyExtended:
    def test_5xx_provider_error(self):
        info = classify_llm_error(http_error(503, {"error": {"message": "upstream error"}}))
        assert info.code == CODE_PROVIDER
        assert "状态页" in info.advice

    def test_timeout_connection_error(self):
        info = classify_llm_error(TimeoutError("timed out"))
        assert info.code == CODE_CONNECTION

    def test_litellm_exception_name_family(self):
        """LiteLLM PaymentRequiredError 类名族命中（零 import，只读类名）。"""
        exc_cls = make_named_exc("PaymentRequiredError", "litellm.exceptions")
        info = classify_llm_error(exc_cls("payment required"))
        assert info.code == CODE_CREDIT
        assert info.provider == "litellm"  # __module__ 探测

    def test_openai_sdk_style_status_code_body(self):
        """openai SDK APIStatusError duck-typed：.status_code + .body。"""
        info = classify_llm_error(FakeStatusError(429, {
            "error": {"code": "rate_limit_exceeded", "message": "slow down"}}))
        assert info.code == CODE_RATE_LIMIT
        assert info.http_status == 429

    def test_anthropic_style_body_type_field(self):
        """Anthropic 风格 body（error.type 承载分型）同样识别。"""
        info = classify_llm_error(FakeStatusError(429, {
            "type": "error", "error": {"type": "rate_limit_error",
                                       "message": "Number of requests too high"}}))
        assert info.code == CODE_RATE_LIMIT

    def test_llm_call_error_is_idempotent(self):
        info0 = classify_llm_error(http_error(402))
        assert classify_llm_error(LlmCallError(info0)) is info0

    def test_http_error_without_readable_body_keeps_status(self):
        err = urllib.error.HTTPError("https://api.test", 429, "Too Many Requests",
                                     email.message.Message(), None)
        info = classify_llm_error(err)
        assert info.code == CODE_RATE_LIMIT  # 读体失败不吞状态码

    def test_error_envelope_constructor_shape(self):
        out = llm_error_envelope(http_error(402))
        assert out["ok"] is False
        assert isinstance(out["errors"], list)
        assert all(isinstance(e, str) for e in out["errors"])
        for key in ("code", "provider", "http_status", "message", "advice"):
            assert key in out
        assert out["code"] == CODE_CREDIT
        # 与裸构造器同形（信封契约：errors 恒 list[str]，结构化字段 **fields）
        assert set(out) >= set(error_envelope(["x"], code=CODE_CREDIT))


# ─── pydantic_ai_runtime.submit 归一层接线 ──────────────────────────────────


class TestPydanticRuntimeNormalization:
    def _submit(self, runner):
        from rfauto.service.pydantic_ai_runtime import PaiRunInput, PydanticAIRuntime

        inp = PaiRunInput(messages=[{"role": "user", "content": "hi"}],
                          tools=[], executor=lambda name, args: {"ok": True})
        return PydanticAIRuntime(runner=runner).submit(inp, lambda n, a: {"ok": True})

    def test_http_error_normalized_to_llm_call_error(self):
        with pytest.raises(LlmCallError) as ei:
            self._submit(lambda inp: (_ for _ in ()).throw(
                http_error(429, {"error": {"code": "credit_balance_exhausted",
                                           "message": "exhausted"}})))
        info = ei.value.llm
        assert info.code == CODE_CREDIT
        assert info.http_status == 429
        assert "exhausted" in info.message
        # LlmCallError 本身可当普通 RuntimeError 消费（str=message）
        assert "exhausted" in str(ei.value)

    def test_budget_exception_still_contract(self):
        from rfauto.service.pydantic_ai_runtime import RuntimeBudgetExceeded

        def runner(inp):
            raise RuntimeBudgetExceeded("request_limit exceeded",
                                        messages=[{"role": "user", "content": "hi"}],
                                        usage={"requests": 3})

        out = self._submit(runner)
        assert out.finish_reason == "budget_exhausted"  # 无损续跑契约不受归一层影响

    def test_not_installed_propagates_unchanged(self, monkeypatch):
        from rfauto.service.pydantic_ai_runtime import (
            PydanticAINotInstalled,
            default_pydantic_ai_runner,
        )

        monkeypatch.setitem(sys.modules, "pydantic_ai", None)  # 钉住：无论装没装
        with pytest.raises(PydanticAINotInstalled):
            self._submit(default_pydantic_ai_runner)  # 依赖缺失透传不进归一层


# ─── chat 回退路径透传（429 只显通用文案 → code+message+advice）──────────────


class TestChatFallbackTransparency:
    @pytest.fixture()
    def chat_env(self, monkeypatch, tmp_path):
        """chat 层钉缝：配置已配置+builtin 通道传输层抛 429 额度。

        #144 家族隔离：chdir(tmp_path)（runs/ 相对解析重定向）+ SESSIONS_DIR
        重定向——不向真实 runs/ 落会话档/trace。
        """
        from rfauto.service import agent_runtime as ar
        from rfauto.service import r3_services

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(ar, "SESSIONS_DIR", tmp_path / "sess")
        monkeypatch.setattr(r3_services, "get_chat_settings",
                            lambda: {"ok": True, "configured": True})
        monkeypatch.setattr(r3_services, "get_chat_settings_raw",
                            lambda: {"runtime": "builtin", "max_tool_rounds": 6})
        return ar

    def test_429_credit_full_transparency(self, chat_env, monkeypatch):
        def raiser(messages, tools):
            raise http_error(429, {"error": {"code": "credit_balance_exhausted",
                                             "message": "credit exhausted"}})

        # 传输层在实例化时读 agent_runtime 模块属性（llm_transport 叶的测试缝）
        monkeypatch.setattr(chat_env, "openai_chat_completion", raiser)
        from rfauto.service.r3_services import AgentChat

        out = AgentChat().chat("hi")
        # 三字段齐透：code/原始 message/分诊建议进人读正文
        assert "[LLM 调用失败" in out["text"]  # 前缀契约（few_shot 成功判据依赖）
        assert "credit_balance_exhausted" in out["text"]
        assert "credit exhausted" in out["text"]
        assert "额度" in out["text"]
        assert "HTTP 429" in out["text"]
        # 结构化键（UI/API 消费面）
        le = out["llm_error"]
        assert le["code"] == CODE_CREDIT
        assert le["http_status"] == 429
        assert le["advice"] == ADVICE_BY_CODE[CODE_CREDIT]
        assert "已回退指令模式" in out["text"]  # 回退语义保留
        assert out["action"] == "help"  # 关键词路由兜底照常

    def test_429_rate_limit_text_distinguishes_credit(self, chat_env, monkeypatch):
        """同 429：限速形态与额度形态文案不同（用户痛点根除面）。"""
        monkeypatch.setattr(chat_env, "openai_chat_completion",
                            lambda m, t: (_ for _ in ()).throw(
                                http_error(429, {"error": {
                                    "code": "rate_limit_exceeded",
                                    "message": "slow down"}})))
        from rfauto.service.r3_services import AgentChat

        out = AgentChat().chat("hi")
        assert "rate_limit_exceeded" in out["text"]
        assert "限速" in out["text"]
        assert "额度" not in out["text"]  # 限速形态不误报额度建议
        assert out["llm_error"]["code"] == CODE_RATE_LIMIT

    def test_generic_exception_still_falls_back(self, chat_env, monkeypatch):
        monkeypatch.setattr(chat_env, "openai_chat_completion",
                            lambda m, t: (_ for _ in ()).throw(RuntimeError("boom")))
        from rfauto.service.r3_services import AgentChat

        out = AgentChat().chat("hi")
        assert "unknown" in out["text"]
        assert "boom" in out["text"]  # message 透传
        assert out["llm_error"]["code"] == CODE_UNKNOWN


# ─── 接通性检测（通道全 monkeypatch，零网络）────────────────────────────────


class TestConnectionCheck:
    @pytest.fixture()
    def patch_cfg(self, monkeypatch):
        from rfauto.service import chat_settings_io

        def _set(cfg: dict[str, Any]) -> None:
            monkeypatch.setattr(chat_settings_io, "get_chat_settings_raw",
                                lambda: cfg)

        return _set

    def test_not_configured_diagnosis(self, monkeypatch):
        from rfauto.service import chat_settings_io

        monkeypatch.setattr(chat_settings_io, "get_chat_settings_raw",
                            lambda: {"base_url": "", "model": ""})
        out = _conn()
        assert out["ok"] is False
        assert out["code"] == CODE_NOT_CONFIGURED
        assert out["advice"] == ADVICE_BY_CODE[CODE_NOT_CONFIGURED]
        assert out["http_status"] is None

    def test_success_ok_envelope(self, patch_cfg, monkeypatch):
        patch_cfg({"base_url": "https://api.test/v1", "model": "test-model",
                   "api_key": "sk-test"})
        calls: list[tuple[list, list]] = []

        def fake_probe(messages, tools):
            calls.append((messages, tools))
            return {"choices": [{"message": {"content": "pong"}}]}

        from rfauto.service import llm_transport

        monkeypatch.setattr(llm_transport, "openai_chat_completion", fake_probe)
        out = _conn()
        assert out["ok"] is True
        assert out["code"] == "ok"
        assert out["model"] == "test-model"
        assert out["api_key_set"] is True
        assert isinstance(out["elapsed_ms"], float)
        assert len(calls) == 1 and calls[0][1] == []  # 最小探针零工具

    def test_429_credit_diagnosis(self, patch_cfg, monkeypatch):
        patch_cfg({"base_url": "https://api.test/v1", "model": "test-model"})
        from rfauto.service import llm_transport

        monkeypatch.setattr(llm_transport, "openai_chat_completion",
                            lambda m, t: (_ for _ in ()).throw(
                                http_error(429, {"error": {
                                    "code": "credit_balance_exhausted",
                                    "message": "no credits"}})))
        out = _conn()
        assert out["ok"] is False
        assert out["code"] == CODE_CREDIT
        assert out["http_status"] == 429
        assert out["provider_code"] == "credit_balance_exhausted"
        assert "no credits" in out["message"]
        assert isinstance(out["errors"], list)  # 失败信封 errors 恒 list[str]

    def test_401_diagnosis(self, patch_cfg, monkeypatch):
        patch_cfg({"base_url": "https://api.test/v1", "model": "test-model"})
        from rfauto.service import llm_transport

        monkeypatch.setattr(llm_transport, "openai_chat_completion",
                            lambda m, t: (_ for _ in ()).throw(
                                http_error(401, {"error": {
                                    "code": "invalid_api_key",
                                    "message": "bad key"}})))
        out = _conn()
        assert out["ok"] is False
        assert out["code"] == CODE_AUTH
        assert "key" in out["advice"]

    def test_no_network_without_patch_configured(self, monkeypatch, tmp_path):
        """配置面未钉时（缺配置）也必须不触网——not_configured 早退。"""
        from rfauto.service import chat_settings_io

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(chat_settings_io, "get_chat_settings_raw", lambda: {})
        out = _conn()
        assert out["ok"] is False and out["code"] == CODE_NOT_CONFIGURED


# ─── LlmError 数据类契约 ─────────────────────────────────────────────────────


class TestLlmErrorDataclass:
    def test_as_dict_roundtrip(self):
        info = LlmError(code=CODE_RATE_LIMIT, provider="openai", http_status=429,
                        provider_code="rate_limit_exceeded", message="m",
                        advice=ADVICE_BY_CODE[CODE_RATE_LIMIT])
        d = info.as_dict()
        assert d == {"code": CODE_RATE_LIMIT, "provider": "openai",
                     "http_status": 429, "provider_code": "rate_limit_exceeded",
                     "message": "m", "advice": ADVICE_BY_CODE[CODE_RATE_LIMIT]}
