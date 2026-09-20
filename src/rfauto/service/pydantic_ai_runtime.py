"""pydantic-ai Runtime：AgentRuntime 协议的 pydantic-ai 实现（WP3.1）。

方案行（runtime 通道可替换，pydantic_ai 实现）：
实现协议注册 ``runtime: pydantic_ai``，与 builtin A/B token 效率后再决定是否
切默认。选择入口已有：configs/chat_settings.yaml 的 ``runtime:`` 键
（r3_services._llm_turn 读 raw.get("runtime", "builtin") → RuntimeRegistry.create，
插件按需导入见 agent_runtime.OPTIONAL_RUNTIME_PLUGINS）。

可选依赖纪律：
- pydantic-ai 不进硬依赖（pyproject 可选组 ``pai`` = pydantic-ai-slim[openai]）。
  未安装时 create("pydantic_ai") 照常可用（注册表只登记类，不 import 库），
  submit() 才抛 PydanticAINotInstalled，chat 层既有异常回退链兜住（#105：可选
  路径不阻塞主链路）。
- 库内 API 全部懒加载 + 防御式取值，token 字段同时兼容 1.x 前后两代命名
  （input_tokens/request_tokens/prompt_tokens 等，见 extract_usage）。
- 真实 API 口径按上游源码核对（1.x 源码与 venv 实装
  pydantic-ai-slim 2.43.0 逐项 introspect 复核）：
  · OpenAIChatModel(model_name, *, provider=...)；2.x 已删旧名 OpenAIModel
    （getattr 回退只为 <1.0 兼容）；OpenAIProvider(base_url, api_key,
    openai_client, http_client)——http_client 是 A/B 仪表抓真实出站载荷的注入缝。
  · RunUsage.input_tokens/output_tokens/cache_read_tokens/requests/tool_calls；
    **AgentRun.usage 与 AgentRunResult.usage 在 2.x 是 property**（1.x 是方法）
    ——一律把属性原样交 extract_usage（callable 才调用），不能写 ``.usage()``
    （2.x 上 TypeError，③ 离线构造冒烟抓出的真差异）。
  · UsageLimits(request_limit=...) 在每次模型请求前检查（usage.py
    check_before_request），耗尽抛 UsageLimitExceeded(RuntimeError)。
  · Agent.iter(user_prompt|None, *, message_history, model_settings, usage_limits)
    是 async 上下文管理器；AgentRun.all_messages()/usage 在**运行中即可读**
    （run.py：「all messages for the run so far」「usage ... so far」）——
    这是 ② 预算路径无损续跑的依据（run_sync 抛 UsageLimitExceeded 时整轮现场丢失）。
  · user_prompt=None 且 message_history 末尾是 ModelRequest（工具结果）时直接
    复用该请求续跑（_agent_graph.py UserPromptNode），即 build_pai_history 的
    续跑现场语义；空串 prompt 必须转 None（否则多出空 UserPromptPart）。
  · 同步工具函数走 run_in_executor 线程执行（_function_schema.py），同一响应
    多个工具调用并发——适配器遥测计数加锁。

测试缝：runner 可注入（PaiRunner），单测用脚本化 runner 离线钉死协议翻译
（不开网络、不需要安装 pydantic-ai）；库无关纯函数（tool_spec_to_callable /
build_pai_history / pai_messages_to_openai / extract_usage）用假类直接单测；
build_pai_agent 离线可构造（不发请求），装了库的环境跑真类构造冒烟（③）。

A/B 仪表见 runtime_ab.py（离线结构 A/B + live 真模型 A/B）。默认裁决口径
runtime_ab.recommend_default（真机留档 + 库可用 + 省 ≥5% 三条件）；裁决留档
scripts/runtime_ab_live_out/evidence.json，配置键 ``runtime:`` 随时可回滚。

默认裁决（真机 A/B，3×2 交替，max_rounds=6）：**维持
builtin**——模型上报总 token 均值 builtin 17663 vs pydantic_ai 18135（pydantic_ai
多用 2.7%，未达省 5% 门槛）；pydantic_ai 3 次中 1 次 budget_exhausted（无 builtin
的末段催办注入，模型把 6 轮预算全花在 run_detail 探索上），公平性未满足。该次
预算耗尽 trial 仍记到 19602/944 token 与 6 次工具调用——即 ② iter() 无损续跑的
真机实证（run_sync 契约下此处为 0/进入时现场）。
"""

from __future__ import annotations

import asyncio
import json
import keyword
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from rfauto.service.agent_runtime import (
    AgentRuntime,
    RuntimeRegistry,
    RuntimeRequest,
    RuntimeResult,
    RuntimeUsage,
    ToolExecutor,
    ToolSpec,
)

# 工具执行器：名字+参数 → 结果 dict（异常由运行时兜底回传模型）
# PaiRunner：整轮 pydantic-ai 运行的注入缝（默认实现 default_pydantic_ai_runner）
PaiRunner = Callable[["PaiRunInput"], "PaiRunResult"]


class PydanticAINotInstalled(RuntimeError):
    """pydantic-ai 依赖缺失或通道配置缺失（提示安装/配置，不静默降级）。"""


class RuntimeBudgetExceeded(RuntimeError):
    """runner 侧预算耗尽哨兵（默认 runner 由 UsageLimitExceeded 翻译而来）。

    ② 无损续跑：默认 runner 走 agent.iter() 事件流，预算耗尽时把截至当前的
    all_messages（已转 OpenAI 风格）与 usage（extract_usage 字段）挂在异常上
    回传；适配器优先取之，缺省（脚本化/旧 runner 未带）才退回进入时现场与 0 usage。
    """

    def __init__(self, message: str = "", *,
                 messages: list[dict[str, Any]] | None = None,
                 usage: dict[str, int] | None = None):
        super().__init__(message)
        self.messages = messages
        self.usage = usage


@dataclass
class PaiRunInput:
    """传给 runner 的完整现场：OpenAI 风格消息 + 工具表 + 循环预算。"""

    messages: list[dict[str, Any]]
    tools: list[ToolSpec]
    executor: ToolExecutor
    max_rounds: int = 12
    temperature: float = 0.3


@dataclass
class PaiRunResult:
    """runner 产物：最终文本 + OpenAI 风格现场（续跑用）+ 归一化 usage。"""

    text: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    requests: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PaiAgentBundle:
    """build_pai_agent 产物：已装工具表的 Agent + 翻译好的 message_history/prompt
    + 懒加载符号表（run_pai_agent 消费；③ 冒烟只构造不运行）。"""

    agent: Any
    history: list[Any]
    prompt: str
    pai: SimpleNamespace


# ─── 库无关纯函数（单测用假类直接钉死，无需安装 pydantic-ai）─────────────────

_JSON_TYPE_MAP: dict[str, type[Any]] = {
    "integer": int, "number": float, "string": str,
    "boolean": bool, "object": dict, "array": list,
}


def json_type_to_python(json_type: Any) -> Any:
    """JSON schema 类型名 → Python 注解（未知/缺失回退 Any）。"""
    return _JSON_TYPE_MAP.get(str(json_type or "").lower(), Any)


def _dispatch_tool_args(
        spec: ToolSpec, executor: ToolExecutor, required: set[str],
        kwargs: dict[str, Any]) -> dict[str, Any]:
    """pydantic-ai 工具函数 → 协议执行器。可选参数未给（None）时不透传，
    保持与 builtin（模型只发给了的参数）相同的执行器语义。"""
    clean = {k: v for k, v in kwargs.items() if v is not None or k in required}
    return executor(spec.name, clean)


def tool_spec_to_callable(spec: ToolSpec, executor: ToolExecutor) -> Callable[..., dict[str, Any]]:
    """ToolSpec → pydantic-ai 可注册的具名函数（schema 由签名注解推导）。

    pydantic-ai 不收任意 JSON schema，需从函数签名推导（_function_schema），
    故用受控模板动态建签名：参数名过 isidentifier 白名单、类型映射注解、
    可选参数默认 None（_dispatch 内剔除）。name/描述经 __name__/__doc__ 注入。
    """
    names = [n for n in spec.parameters
             if isinstance(n, str) and n.isidentifier() and not keyword.iskeyword(n)]
    required = set(spec.required or [])
    params = ", ".join(n if n in required else f"{n}=None" for n in names)
    pairs = ", ".join(f"{n!r}: {n}" for n in names)
    src = f"def _dynamic_tool({params}):\n    return _dispatch({{{pairs}}})\n"
    ns: dict[str, Any] = {
        "_dispatch": lambda kw: _dispatch_tool_args(spec, executor, required, kw)}
    exec(src, ns)  # 受控模板：参数名经 isidentifier 白名单过滤
    fn: Callable[..., dict[str, Any]] = ns["_dynamic_tool"]
    fn.__name__ = spec.name
    fn.__doc__ = spec.description or spec.name
    fn.__annotations__ = {n: json_type_to_python((spec.parameters.get(n) or {}).get("type"))
                          for n in names}
    fn.__annotations__["return"] = dict
    return fn


def _first_int(obj: Any, names: tuple[str, ...]) -> int:
    for n in names:
        v = getattr(obj, n, None)
        if isinstance(v, bool):  # bool 是 int 子类，排除
            continue
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def extract_usage(usage_obj: Any) -> dict[str, int]:
    """pydantic-ai usage（对象、property 值或 1.x 的 usage() 绑定方法）→ 协议遥测字段。

    兼容三代命名：input_tokens（1.x/2.x）/ request_tokens（0.x 遗留别名）/
    prompt_tokens（OpenAI 风格）；输出侧同理。缺失记 0，不猜测。调用方把
    ``run.usage`` 属性原样传入：1.x 是方法（callable → 调用），2.x 是 property
    （RunUsage 实例 → 直接读字段）。
    """
    if usage_obj is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "requests": 0}
    u = usage_obj() if callable(usage_obj) else usage_obj
    return {
        "prompt_tokens": _first_int(u, ("input_tokens", "request_tokens", "prompt_tokens")),
        "completion_tokens": _first_int(u, ("output_tokens", "response_tokens", "completion_tokens")),
        "cached_tokens": _first_int(u, ("cache_read_tokens", "cached_tokens")),
        "requests": _first_int(u, ("requests",)),
    }


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def pai_messages_to_openai(messages: Any) -> list[dict[str, Any]]:
    """pydantic-ai ModelMessage 列表 → OpenAI 风格 dicts（续跑现场/落盘）。

    按类名分派（isinstance 需要真类，这里连真类都懒加载，用类名最稳）；
    未知 part（ThinkingPart/FilePart 等）best-effort 跳过。
    """
    out: list[dict[str, Any]] = []
    for m in messages or []:
        kind = type(m).__name__
        parts = list(getattr(m, "parts", None) or [])
        if kind == "ModelRequest":
            for p in parts:
                pk = type(p).__name__
                if pk == "SystemPromptPart":
                    out.append({"role": "system", "content": _as_text(getattr(p, "content", ""))})
                elif pk == "UserPromptPart":
                    out.append({"role": "user", "content": _as_text(getattr(p, "content", ""))})
                elif pk == "ToolReturnPart":
                    content = getattr(p, "content", None)
                    if content is None:
                        content = getattr(p, "result", None)
                    out.append({"role": "tool",
                                "tool_call_id": str(getattr(p, "tool_call_id", "") or ""),
                                "name": str(getattr(p, "tool_name", "") or ""),
                                "content": _as_text(content)})
                elif pk == "RetryPromptPart":
                    out.append({"role": "user", "content": _as_text(getattr(p, "content", ""))})
        elif kind == "ModelResponse":
            text_bits: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for p in parts:
                pk = type(p).__name__
                if pk == "TextPart":
                    text_bits.append(_as_text(getattr(p, "content", "")))
                elif pk == "ToolCallPart":
                    args = getattr(p, "args", None)
                    tool_calls.append({
                        "id": str(getattr(p, "tool_call_id", "") or f"call_{len(tool_calls)}"),
                        "type": "function",
                        "function": {"name": str(getattr(p, "tool_name", "") or ""),
                                     "arguments": args if isinstance(args, str)
                                     else json.dumps(args or {}, ensure_ascii=False)}})
            msg: dict[str, Any] = {"role": "assistant",
                                   "content": "\n".join(b for b in text_bits if b) or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
    return out


def build_pai_history(messages: list[dict[str, Any]], cls: Any) -> tuple[list[Any], str]:
    """OpenAI 风格消息 → (pydantic-ai message_history, 尾随 user prompt)。

    pydantic-ai 约定新轮 prompt 单独传（iter/run_sync 首参），不进 message_history；
    续跑现场（止于 tool 结果、无尾随 user）时 prompt=""，调用方转 None 后由
    pydantic-ai 复用末尾 ModelRequest 续跑（上游 UserPromptNode 语义）。cls 是
    含所需类的命名空间（真模块或测试假类），保持本函数库无关。
    """
    history: list[Any] = []
    msgs = list(messages or [])
    prompt = ""
    if msgs and msgs[-1].get("role") == "user":
        prompt = str(msgs[-1].get("content") or "")
        msgs = msgs[:-1]
    for m in msgs:
        role = m.get("role")
        if role == "system":
            history.append(cls.ModelRequest(
                parts=[cls.SystemPromptPart(content=str(m.get("content") or ""))]))
        elif role == "user":
            history.append(cls.ModelRequest(
                parts=[cls.UserPromptPart(content=str(m.get("content") or ""))]))
        elif role == "assistant":
            parts: list[Any] = []
            text = m.get("content")
            if text:
                parts.append(cls.TextPart(content=str(text)))
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                raw = fn.get("arguments")
                try:
                    args = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    args = {}
                parts.append(cls.ToolCallPart(
                    tool_name=str(fn.get("name") or ""), args=args,
                    tool_call_id=str(tc.get("id") or "")))
            if parts:
                history.append(cls.ModelResponse(parts=parts))
        elif role == "tool":
            history.append(cls.ModelRequest(parts=[cls.ToolReturnPart(
                tool_name=str(m.get("name") or ""),
                content=str(m.get("content") or ""),
                tool_call_id=str(m.get("tool_call_id") or ""))]))
    return history, prompt


# ─── 默认 runner（唯一触碰 pydantic-ai 真库的路径，懒加载）───────────────────

def _import_pai() -> SimpleNamespace:
    """懒加载 pydantic-ai 真库符号（模块内唯一 import 点；缺失抛 PydanticAINotInstalled）。"""
    try:
        from pydantic_ai import Agent
        from pydantic_ai.exceptions import UsageLimitExceeded
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            SystemPromptPart,
            TextPart,
            ToolCallPart,
            ToolReturnPart,
            UserPromptPart,
        )
        from pydantic_ai.models import openai as pai_openai_models
        from pydantic_ai.providers.openai import OpenAIProvider
        from pydantic_ai.usage import UsageLimits
    except ImportError as exc:
        raise PydanticAINotInstalled(
            "pydantic-ai 未安装：安装 'pydantic-ai-slim[openai]'（pip install rfauto[pai]）"
            "后方可使用 runtime: pydantic_ai（当前默认 builtin 不受影响）") from exc
    # 1.x 改名 OpenAIModel→OpenAIChatModel，2.x 只剩新名（旧名 getattr 回退仅为 <1.0 兼容）
    model_cls = (getattr(pai_openai_models, "OpenAIChatModel", None)
                 or getattr(pai_openai_models, "OpenAIModel", None))
    if model_cls is None:
        raise PydanticAINotInstalled("不识别的 pydantic-ai 版本：缺 OpenAIChatModel/OpenAIModel")
    return SimpleNamespace(
        Agent=Agent, UsageLimitExceeded=UsageLimitExceeded, UsageLimits=UsageLimits,
        OpenAIProvider=OpenAIProvider, model_cls=model_cls,
        classes=SimpleNamespace(
            ModelRequest=ModelRequest, ModelResponse=ModelResponse,
            SystemPromptPart=SystemPromptPart, UserPromptPart=UserPromptPart,
            TextPart=TextPart, ToolCallPart=ToolCallPart, ToolReturnPart=ToolReturnPart))


def build_pai_agent(inp: PaiRunInput, *, model_name: str, base_url: str,
                    api_key: str | None = None, http_client: Any = None) -> PaiAgentBundle:
    """构造 Agent（OpenAI 兼容模型 + provider + 工具表）与翻译好的现场——离线可构造。

    不发任何请求：③ 离线构造冒烟只走到这里。http_client 为 A/B 仪表注入缝
    （httpx2/httpx AsyncClient 事件钩子抓真实出站载荷字节数），生产路径 None →
    provider 自建客户端。
    """
    pai = _import_pai()
    if not model_name or not base_url:
        raise RuntimeError(
            "runtime: pydantic_ai 需要 configs/chat_settings.yaml 配置 base_url 与 model")
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    provider_kwargs: dict[str, Any] = {"base_url": base, "api_key": api_key or "missing"}
    if http_client is not None:
        provider_kwargs["http_client"] = http_client
    model = pai.model_cls(model_name, provider=pai.OpenAIProvider(**provider_kwargs))
    history, prompt = build_pai_history(inp.messages, pai.classes)
    agent = pai.Agent(model, tools=[tool_spec_to_callable(s, inp.executor) for s in inp.tools])
    return PaiAgentBundle(agent=agent, history=history, prompt=prompt, pai=pai)


def _run_coroutine_sync(coro_factory: Callable[[], Any]) -> Any:
    """同步驱动协程：无事件循环时 asyncio.run；已在循环内（async 路由同步调 chat）
    则另起线程跑独立循环，避免 'asyncio.run() cannot be called from a running event loop'。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro_factory())).result()


def run_pai_agent(bundle: PaiAgentBundle, inp: PaiRunInput) -> PaiRunResult:
    """驱动 agent.iter() 事件流到底（② 预算路径无损续跑）。

    循环预算映射 UsageLimits(request_limit=max_rounds)（每次请求前检查）。耗尽时
    UsageLimitExceeded 从 async-for 内抛出，**在上下文管理器内捕获**——此时
    AgentRun.all_messages()/usage 仍是截至当前的完整现场与累计 usage（上游 run.py
    口径），转 OpenAI 风格后挂上 RuntimeBudgetExceeded 交适配器；run_sync 契约
    在此处整轮丢失（旧实现的已记录限制，现已消除）。
    """
    pai = bundle.pai
    limits = pai.UsageLimits(request_limit=max(1, int(inp.max_rounds)))
    settings = {"temperature": inp.temperature}

    async def drive() -> tuple[Any, Any, Any, BaseException | None]:
        # 返回 (all_messages, usage 属性值, output|None, 预算异常|None)
        async with bundle.agent.iter(bundle.prompt or None, message_history=bundle.history,
                                     model_settings=settings, usage_limits=limits) as run:
            try:
                async for _node in run:
                    pass
            except pai.UsageLimitExceeded as exc:
                return run.all_messages(), getattr(run, "usage", None), None, exc
            result = run.result
            output = getattr(result, "output", "") if result is not None else ""
            return run.all_messages(), getattr(run, "usage", None), output, None

    messages, usage_attr, output, budget_exc = _run_coroutine_sync(drive)
    usage = extract_usage(usage_attr)
    oai_messages = pai_messages_to_openai(messages)
    if budget_exc is not None:
        raise RuntimeBudgetExceeded(str(budget_exc), messages=oai_messages,
                                    usage=usage) from budget_exc
    return PaiRunResult(
        text=output if isinstance(output, str) else _as_text(output),
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        cached_tokens=usage["cached_tokens"],
        requests=usage["requests"],
        messages=oai_messages)


def default_pydantic_ai_runner(inp: PaiRunInput) -> PaiRunResult:
    """真实现：configs/chat_settings.yaml 通道 → build_pai_agent → run_pai_agent。"""
    _import_pai()  # 先验依赖（缺失时不读配置直接报 PydanticAINotInstalled）
    from rfauto.service.r3_services import get_chat_settings_raw

    cfg = get_chat_settings_raw()
    bundle = build_pai_agent(inp, model_name=str(cfg.get("model") or ""),
                             base_url=str(cfg.get("base_url") or ""),
                             api_key=cfg.get("api_key"))
    return run_pai_agent(bundle, inp)


# ─── 协议实现（注册进 RuntimeRegistry；import 期不触碰 pydantic-ai）──────────

@RuntimeRegistry.register
class PydanticAIRuntime(AgentRuntime):
    """runtime: pydantic_ai —— 循环策略交 pydantic-ai Agent，工具执行交回调用方。

    与 builtin 同一遥测契约（RuntimeUsage）与预算耗尽契约（finish_reason=
    budget_exhausted + 同款「继续」续跑文本），r3_services 侧零改动可换。
    """

    name = "pydantic_ai"

    def __init__(self, runner: PaiRunner | None = None):
        self._runner = runner or default_pydantic_ai_runner

    def submit(self, request: RuntimeRequest, executor: ToolExecutor) -> RuntimeResult:
        usage = RuntimeUsage()
        tools_used: list[str] = []
        lock = threading.Lock()  # pydantic-ai 同响应多工具并发执行（sync 工具走线程池）
        t0 = time.perf_counter()

        def wrapped(name: str, args: dict[str, Any]) -> dict[str, Any]:
            t1 = time.perf_counter()
            with lock:
                tools_used.append(name)
            try:
                out = executor(name, args)
            except Exception as exc:  # 工具异常回传给模型自行调整（同 builtin）
                out = {"error": str(exc)}
            with lock:
                usage.tool_calls += 1
                usage.tool_elapsed_s += time.perf_counter() - t1
            return out

        inp = PaiRunInput(messages=[dict(m) for m in request.messages],
                          tools=list(request.tools), executor=wrapped,
                          max_rounds=request.max_rounds,
                          temperature=request.temperature)
        try:
            run = self._runner(inp)
        except RuntimeBudgetExceeded as exc:
            # ② 无损续跑：默认 runner 挂回截至当前的现场与 usage；未带时兜底进入时现场
            recovered = exc.usage or {}
            usage.llm_calls = max(1, int(recovered.get("requests") or 0))
            usage.llm_elapsed_s = time.perf_counter() - t0
            usage.prompt_tokens = int(recovered.get("prompt_tokens") or 0)
            usage.completion_tokens = int(recovered.get("completion_tokens") or 0)
            usage.cached_tokens = int(recovered.get("cached_tokens") or 0)
            summary = "、".join(dict.fromkeys(tools_used)) or "无"
            return RuntimeResult(
                text=f"本轮已完成 {len(tools_used)} 次工具调用（{summary}），达到单轮上限。"
                     f"回复『继续』将从已有进度接着分析（不重复探索）。",
                finish_reason="budget_exhausted",
                messages=exc.messages or inp.messages,
                tools_used=tools_used,
                action=tools_used[-1] if tools_used else None,
                usage=usage)

        usage.llm_calls = max(1, int(run.requests or 0))  # 真 runner 回报 requests 数
        usage.llm_elapsed_s = time.perf_counter() - t0
        usage.prompt_tokens = run.prompt_tokens
        usage.completion_tokens = run.completion_tokens
        usage.cached_tokens = run.cached_tokens
        return RuntimeResult(text=run.text, finish_reason="stop",
                             messages=run.messages or inp.messages,
                             tools_used=tools_used,
                             action=tools_used[-1] if tools_used else None,
                             usage=usage)
