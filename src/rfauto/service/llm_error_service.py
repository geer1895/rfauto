"""LLM 错误透传+接通性分诊单源（T-Q15；aurora_q Q-W0-2）。

背景（真实用户反馈 P0，微信反馈五条第 2 条）：Agent 助手遇 LLM 429 只显
通用文案（``[LLM 调用失败，已回退指令模式: …]``），用户无法区分
credit_balance_exhausted（额度/余额耗尽）与 rate_limit_exceeded（限速）。
本模块把 LLM 调用的 HTTP 4xx/5xx 异常归一为 :class:`LlmError`
（code/provider/http_status/provider_code/message/advice），分诊建议中文
面向用户：额度→充值/换 key；限速→稍后重试/降并发；401→检查 key；
网关 5xx→服务方状态页。

R8 分型结论（runs/aurora_q FEEDBACK_ABSORB 落点定稿）：LiteLLM 402
PaymentRequiredError 专收额度+未映射兜底；Anthropic
BillingError/RateLimitError 分型。仓内实际通道=OpenAI 兼容 HTTP
（llm_transport.urllib）与 pydantic-ai[openai]（openai SDK 异常族），
**不新增 litellm/anthropic 硬依赖**——按 HTTP 状态码+响应体
error.code/message 通用归一；SDK 异常类名匹配（含 litellm/anthropic 命名
族）只读 ``type(exc).__name__``，零 import，未来接入对应 SDK 时同一归一层
自动识别。

归一层分诊三优先级（预声明，任务书口径）：
  1. **响应体 error.code**（OpenAI 风格 ``error.code`` / Anthropic 风格
     ``error.type``）——同一 429 下 credit_balance_exhausted 与
     rate_limit_exceeded 只能靠它区分；
  2. **异常类型**（类名族：PaymentRequiredError/BudgetExceededError=额度，
     AuthenticationError/PermissionDeniedError=认证，
     RateLimitError=限速）；
  3. **HTTP 状态码**（402=额度 / 429=限速 / 401·403=认证 / 5xx=网关）。
未映射→unknown 兜底（原始 message 透传，不吞任何报错文本）。

信封契约：新出口一律走 envelope 构造器（:func:`llm_error_envelope`）；
结构化字段 code/provider/http_status/provider_code/message/advice 随
error_envelope **fields 附加（只增不删，既有键集不受影响）。

铁律 7 兼容：本模块不产任何物理数值，纯错误分类与文案。

测试缝：全部为纯函数+异常对象注入，单测零网络（构造
urllib.error.HTTPError(bytes body) / duck-typed SDK 假类即可）；
:func:`test_llm_connection` 探针在调用时读 ``llm_transport`` 模块属性
（monkeypatch.setattr(llm_transport, "openai_chat_completion", fake) 即
钉住通道，#139 配置即外网分支禁真网）。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "LlmCallError",
    "LlmError",
    "classify_llm_error",
    "llm_error_envelope",
    "llm_error_fields",
    "test_llm_connection",
]

# ─── 分诊码与建议文案（中文，面向用户；值即用户可见建议）─────────────────────

#: 额度/余额耗尽（LiteLLM 402 专收语义；OpenAI insufficient_quota 同族）
CODE_CREDIT = "credit_balance_exhausted"
#: 限速（429 非额度形态）
CODE_RATE_LIMIT = "rate_limit_exceeded"
#: 认证失败（401/403）
CODE_AUTH = "authentication_error"
#: 服务方网关/服务器错误（5xx）
CODE_PROVIDER = "provider_error"
#: 无法建立连接/超时（无 HTTP 状态语义的传输失败）
CODE_CONNECTION = "connection_error"
#: 接通性检测：通道未配置（缺 base_url/model）
CODE_NOT_CONFIGURED = "not_configured"
#: 未识别兜底（原始 message 透传）
CODE_UNKNOWN = "unknown"

ADVICE_BY_CODE: dict[str, str] = {
    CODE_CREDIT: (
        "额度/余额不足：请到服务方控制台充值或更换有余额的 API key，"
        "也可在 configs/chat_settings.yaml 换用其他通道/模型。"),
    CODE_RATE_LIMIT: (
        "请求被限速：请稍后重试、降低并发或请求频率；"
        "若持续出现，检查服务方套餐的限速档位（RPM/TPM）。"),
    CODE_AUTH: (
        "认证失败：请检查 configs/chat_settings.yaml 的 api_key 是否正确、"
        "是否过期、是否有该模型的访问权限（401/403）。"),
    CODE_PROVIDER: (
        "服务方网关/服务器错误（5xx）：非本机配置问题，请稍后重试，"
        "并查看服务方状态页或公告。"),
    CODE_CONNECTION: (
        "无法连接到服务端：请检查 base_url 是否正确、本机网络/代理是否可用、"
        "服务方是否在线。"),
    CODE_NOT_CONFIGURED: (
        "LLM 通道未配置：请在 configs/chat_settings.yaml（或 UI 设置页）"
        "填写 base_url、model、api_key 后重试。"),
    CODE_UNKNOWN: (
        "未识别错误：请查看下方原始报错信息；若持续出现，"
        "请核对通道配置或联系服务方排查。"),
}

# ─── 响应体 error.code 分诊关键词（小写子串匹配；body 优先级最高）───────────

_CREDIT_HINTS = ("credit", "quota", "insufficient", "billing", "balance",
                 "payment", "budget", "余额", "额度")
_RATE_HINTS = ("rate_limit", "ratelimit", "too_many_requests", "rate-limit")
_AUTH_HINTS = ("invalid_api_key", "invalid_apikey", "authentication",
               "unauthorized", "permission", "forbidden", "api_key")

# ─── SDK 异常类名族（零 import，只读 __name__/__module__）───────────────────

_CREDIT_EXC_NAMES = {"PaymentRequiredError", "BudgetExceededError"}
_AUTH_EXC_NAMES = {"AuthenticationError", "PermissionDeniedError",
                   "InvalidAPIKeyError"}
_RATE_EXC_NAMES = {"RateLimitError", "TooManyRequestsError"}
_CONN_EXC_NAMES = {"APIConnectionError", "APIRequestTimeoutError",
                   "APITimeoutError", "ConnectError", "ConnectTimeout",
                   "ReadTimeout", "WriteTimeout", "URLError"}


@dataclass(frozen=True)
class LlmError:
    """LLM 调用错误归一形态（T-Q15 透传字段集）。

    - ``code``：本模块分诊码（ADVICE_BY_CODE 键之一）；
    - ``provider``：通道族（openai / litellm / anthropic）；
    - ``http_status``：HTTP 状态码（无状态语义的传输失败为 None）；
    - ``provider_code``：服务方原始 error.code/message 键（透传，区分
      额度 vs 限速的第一手证据；未知为空串）；
    - ``message``：原始错误透传（服务方 message 或异常 str，不加工）；
    - ``advice``：中文分诊建议（面向用户，ADVICE_BY_CODE 单源）。
    """

    code: str
    provider: str
    http_status: int | None
    provider_code: str
    message: str
    advice: str

    def as_dict(self) -> dict[str, Any]:
        """结构化字段（chat 响应 ``llm_error`` 键 / 信封 fields 单源）。"""
        return {"code": self.code, "provider": self.provider,
                "http_status": self.http_status,
                "provider_code": self.provider_code,
                "message": self.message, "advice": self.advice}


class LlmCallError(RuntimeError):
    """已归一的 LLM 调用失败（``.llm`` 携带 :class:`LlmError`）。

    运行时层（pydantic_ai_runtime.submit）把 runner 抛出的 HTTP/SDK 异常
    翻译成本类上抛；消费方（chat 回退层）可 ``classify_llm_error(exc)``
    直接取回归一结果，也可当普通 RuntimeError 兜 str。非 LLM 语义的异常
    （PydanticAINotInstalled 等配置/依赖错误）**不**走本类，原样透传。
    """

    def __init__(self, llm: LlmError):
        super().__init__(llm.message)
        self.llm = llm


# ─── 归一层（唯一分类入口）───────────────────────────────────────────────────

def _decode_body(body: Any) -> Any:
    """bytes/str → 解析后的 dict 或原文 str（解析失败原样返回）。"""
    if isinstance(body, (bytes, bytearray)):
        body = bytes(body).decode("utf-8", errors="replace")
    if isinstance(body, str):
        text = body.strip()
        if not text:
            return ""
        try:
            return json.loads(text)
        except Exception:
            return text
    return body


def _body_code_message(body: Any) -> tuple[str, str]:
    """响应体 → (provider_code, message)。

    三形态：OpenAI 风格 ``{"error": {"code": …, "message": …}}``；
    Anthropic 风格 ``{"type": "error", "error": {"type": …, "message": …}}``；
    顶层平铺 ``{"code": …, "message": …}``。``error`` 为 str 时整体作 message。
    """
    parsed = _decode_body(body)
    if not isinstance(parsed, dict):
        if isinstance(parsed, str) and parsed:
            return "", parsed
        return "", ""
    err = parsed.get("error")
    if isinstance(err, dict):
        code = err.get("code") or err.get("type") or ""
        msg = err.get("message") or ""
        return str(code), str(msg)
    if isinstance(err, str):
        return "", err
    code = parsed.get("code") or parsed.get("type") or ""
    msg = parsed.get("message") or ""
    return str(code), str(msg)


def _extract_status_body(exc: BaseException) -> tuple[int | None, Any]:
    """异常 → (HTTP 状态码, 响应体原文)。duck-typing，零 SDK import。

    覆盖三族：urllib.error.HTTPError（builtin 通道，.code + .read()）；
    openai SDK APIStatusError 族（.status_code + .body）；httpx
    HTTPStatusError（.response.status_code + .response.read()）。
    """
    # urllib.error.HTTPError：code + body 流（读流失败不吞状态码）
    code = getattr(exc, "code", None)
    if isinstance(code, int) and "HTTPError" in type(exc).__name__:
        body: Any = None
        try:
            body = exc.read()  # type: ignore[union-attr]
        except Exception:
            body = None
        return code, body
    # openai SDK APIStatusError 族（含 AuthenticationError/RateLimitError/…）
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status, getattr(exc, "body", None)
    # httpx.HTTPStatusError（.response.status_code；body 惰性读）
    resp = getattr(exc, "response", None)
    if resp is not None:
        r_status = getattr(resp, "status_code", None)
        if isinstance(r_status, int):
            try:
                return r_status, resp.read()
            except Exception:
                return r_status, None
    return None, None


def _provider_of(exc: BaseException) -> str:
    """异常 → 通道族（litellm / anthropic / openai；仓内缺省 openai 兼容）。"""
    mod = (type(exc).__module__ or "").lower()
    if "litellm" in mod:
        return "litellm"
    if "anthropic" in mod:
        return "anthropic"
    if mod.startswith("openai"):
        return "openai"
    return "openai"


def _diag_from_provider_code(provider_code: str) -> str | None:
    """响应体 error.code → 分诊码（优先级 1；额度证据可翻 429 的状态兜底）。"""
    low = provider_code.lower()
    if not low:
        return None
    if any(h in low for h in _CREDIT_HINTS):
        return CODE_CREDIT
    if any(h in low for h in _RATE_HINTS):
        return CODE_RATE_LIMIT
    if any(h in low for h in _AUTH_HINTS):
        return CODE_AUTH
    return None


def _diag_from_exc_name(name: str) -> str | None:
    """异常类名族 → 分诊码（优先级 2；LiteLLM/Anthropic 分型兼容面）。"""
    if name in _CREDIT_EXC_NAMES:
        return CODE_CREDIT
    if name in _AUTH_EXC_NAMES:
        return CODE_AUTH
    if name in _RATE_EXC_NAMES:
        return CODE_RATE_LIMIT
    if name in _CONN_EXC_NAMES:
        return CODE_CONNECTION
    return None


def _diag_from_status(status: int | None) -> str | None:
    """HTTP 状态码 → 分诊码（优先级 3；402=额度 LiteLLM 专收语义）。"""
    if status is None:
        return None
    if status == 402:
        return CODE_CREDIT
    if status == 429:
        return CODE_RATE_LIMIT
    if status in (401, 403):
        return CODE_AUTH
    if status >= 500:
        return CODE_PROVIDER
    return None


def _message_of(exc: BaseException, body_message: str) -> str:
    """原始错误透传：服务方 message 优先，异常 str 兜底（不加工不吞）。"""
    if body_message:
        return body_message
    text = str(exc).strip()
    return text or type(exc).__name__


def classify_llm_error(exc: BaseException) -> LlmError:
    """任意 LLM 调用异常 → :class:`LlmError`（归一层唯一入口）。

    分诊三优先级：响应体 error.code > 异常类型 > HTTP 状态码；未映射→
    unknown 兜底。LlmCallError 直取已归一的 ``.llm``（幂等）。
    """
    if isinstance(exc, LlmCallError):
        return exc.llm
    status, body = _extract_status_body(exc)
    provider_code, body_message = _body_code_message(body)
    diag = (_diag_from_provider_code(provider_code)
            or _diag_from_exc_name(type(exc).__name__)
            or _diag_from_status(status))
    if diag is None and isinstance(exc, TimeoutError):
        # 无 HTTP 语义的传输失败（内置超时；URLError 等已在类名族命中）
        diag = CODE_CONNECTION
    code = diag or CODE_UNKNOWN
    return LlmError(code=code, provider=_provider_of(exc),
                    http_status=status, provider_code=provider_code,
                    message=_message_of(exc, body_message),
                    advice=ADVICE_BY_CODE[code])


# ─── 信封出口（构造器单源；结构化字段只增不删）───────────────────────────────

def _as_llm_error(exc_or_error: BaseException | LlmError) -> LlmError:
    if isinstance(exc_or_error, LlmError):
        return exc_or_error
    return classify_llm_error(exc_or_error)


def llm_error_fields(exc_or_error: BaseException | LlmError) -> dict[str, Any]:
    """错误信封附加字段（``{"llm_error": {...}}``；chat 响应同键单源）。"""
    return {"llm_error": _as_llm_error(exc_or_error).as_dict()}


def llm_error_envelope(exc_or_error: BaseException | LlmError,
                       **extra: Any) -> dict[str, Any]:
    """失败信封：errors 摘要 + code/provider/http_status/message/advice 平铺。

    消费面：test_llm_connection 与未来任何 LLM 错误出口（任务书「信封走
    构造器」；errors 恒 list[str]，结构化字段经 **fields 附加）。
    """
    info = _as_llm_error(exc_or_error)
    status_txt = "HTTP ?" if info.http_status is None else f"HTTP {info.http_status}"
    return error_envelope(
        [f"LLM 调用失败（{info.code}，{status_txt}）：{info.message}",
         info.advice],
        code=info.code, provider=info.provider,
        http_status=info.http_status, provider_code=info.provider_code,
        message=info.message, advice=info.advice, **extra)


# ─── 接通性检测（最小探针+分诊结论）─────────────────────────────────────────

def test_llm_connection() -> dict[str, Any]:
    """LLM 通道接通性检测（最小 1 消息探针，结论带分诊）。

    流程：读 chat_settings_raw → 未配置（缺 base_url/model）返回
    not_configured 分诊信封；已配置则经 ``llm_transport.openai_chat_completion``
    发最小探针（1 条 user "ping"、零工具）——成功返回 ok 信封（含耗时），
    失败按 :func:`classify_llm_error` 给分诊结论（额度/限速/认证/网关）。

    测试缝：探针函数在**调用时**读 ``llm_transport`` 模块属性，
    ``monkeypatch.setattr(llm_transport, "openai_chat_completion", fake)``
    即钉住通道（#139：单测禁真网）。零数值产出（铁律 7）。
    """
    from rfauto.service import llm_transport
    from rfauto.service.chat_settings_io import get_chat_settings_raw

    try:
        cfg = get_chat_settings_raw() or {}
    except Exception:
        cfg = {}
    base_url = str(cfg.get("base_url") or "")
    model = str(cfg.get("model") or "")
    if not base_url or not model:
        return error_envelope(
            ["LLM 通道未配置：缺 base_url 或 model（configs/chat_settings.yaml）",
             ADVICE_BY_CODE[CODE_NOT_CONFIGURED]],
            code=CODE_NOT_CONFIGURED, provider="openai", http_status=None,
            provider_code="", message="missing base_url/model",
            advice=ADVICE_BY_CODE[CODE_NOT_CONFIGURED])
    t0 = time.perf_counter()
    try:
        # 调用时读模块属性=monkeypatch 缝（不在 import 期绑定函数对象）
        probe = llm_transport.openai_chat_completion
        probe([{"role": "user", "content": "ping"}], [])
    except Exception as exc:
        info = classify_llm_error(exc)
        out = llm_error_envelope(info, model=model, base_url=base_url)
        out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        return out
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return ok_envelope(
        code="ok", provider="openai", http_status=200, provider_code="",
        message="LLM 通道接通正常", advice="LLM 通道可用，可正常发起对话。",
        model=model, base_url=base_url,
        api_key_set=bool(cfg.get("api_key")), elapsed_ms=elapsed_ms)
