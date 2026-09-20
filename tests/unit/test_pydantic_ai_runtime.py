"""WP3.1 pydantic-ai Runtime 协议注册单测（离线，不需要安装 pydantic-ai）。

覆盖：注册表发现（create("pydantic_ai")）、适配器协议翻译（注入 fake runner）、
库无关纯函数（tool_spec_to_callable / build_pai_history / pai_messages_to_openai /
extract_usage，用假类钉死映射）、默认 runner 的可选依赖报错路径（sys.modules
钉住 import 通道，#139：不网络、不依赖真库是否在装）、② agent.iter() 事件流
预算路径无损续跑（假 AgentRun 钉死：耗尽时 all_messages/usage 回传）、③ 真类
离线构造冒烟（装了 pydantic-ai 的环境才跑，不发请求）。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from rfauto.service.agent_runtime import RuntimeRegistry, RuntimeRequest, ToolSpec
from rfauto.service.pydantic_ai_runtime import (
    PaiAgentBundle,
    PaiRunInput,
    PaiRunResult,
    PydanticAINotInstalled,
    PydanticAIRuntime,
    RuntimeBudgetExceeded,
    _run_coroutine_sync,
    build_pai_agent,
    build_pai_history,
    default_pydantic_ai_runner,
    extract_usage,
    pai_messages_to_openai,
    run_pai_agent,
    tool_spec_to_callable,
)
from rfauto.service.runtime_ab import lib_available, lib_version

NUDGE_MARK = "单轮上限"


def _echo_executor(name, args):
    return {"echo": name, "args": args}


def _request(max_rounds=4):
    return RuntimeRequest(
        messages=[{"role": "system", "content": "你是助手"},
                  {"role": "user", "content": "查一下"}],
        max_rounds=max_rounds)


# ─── 注册表发现 ──────────────────────────────────────────────────────────────

class TestRegistryDiscovery:
    def test_pydantic_ai_registered(self):
        runtime = RuntimeRegistry.create("pydantic_ai")
        assert isinstance(runtime, PydanticAIRuntime)
        assert runtime.name == "pydantic_ai"

    def test_builtin_and_pydantic_ai_coexist(self):
        # create 未命中时按需导入插件，两实现同表可换
        assert "builtin" in RuntimeRegistry.available()
        RuntimeRegistry.create("pydantic_ai")
        assert "pydantic_ai" in RuntimeRegistry.available()

    def test_unknown_name_still_raises(self):
        from rfauto.service.agent_runtime import OPTIONAL_RUNTIME_PLUGINS
        # 插件清单登记（模块路径，懒加载入口）
        assert any(p.endswith("pydantic_ai_runtime") for p in OPTIONAL_RUNTIME_PLUGINS)
        with pytest.raises(KeyError):
            RuntimeRegistry.create("_no_such_runtime_xyz")


# ─── 适配器协议翻译（注入 fake runner，不触碰 pydantic-ai）───────────────────

class TestAdapterContract:
    def test_text_only_stop(self):
        def runner(inp):
            assert inp.max_rounds == 4 and inp.temperature == 0.3
            return PaiRunResult(text="答案", prompt_tokens=11, completion_tokens=7,
                                cached_tokens=3, requests=1,
                                messages=[*inp.messages, {"role": "assistant", "content": "答案"}])

        out = PydanticAIRuntime(runner=runner).submit(_request(), _echo_executor)
        assert out.finish_reason == "stop" and out.text == "答案"
        assert out.usage.llm_calls == 1
        assert out.usage.prompt_tokens == 11 and out.usage.completion_tokens == 7
        assert out.usage.cached_tokens == 3
        assert out.messages[-1] == {"role": "assistant", "content": "答案"}
        assert out.tools_used == [] and out.action is None

    def test_tool_round_tracked(self):
        def runner(inp):
            out = inp.executor("list_runs", {"limit": 3})
            assert out == {"echo": "list_runs", "args": {"limit": 3}}
            return PaiRunResult(text="完成", prompt_tokens=10, completion_tokens=5,
                                messages=inp.messages)

        out = PydanticAIRuntime(runner=runner).submit(_request(), _echo_executor)
        assert out.tools_used == ["list_runs"] and out.action == "list_runs"
        assert out.usage.tool_calls == 1 and out.usage.llm_calls == 1

    def test_executor_exception_wrapped(self):
        def boom(name, args):
            raise ValueError("炸了")

        seen = {}

        def runner(inp):
            seen["out"] = inp.executor("run_detail", {"run_id": "x"})
            return PaiRunResult(text="收到", messages=inp.messages)

        out = PydanticAIRuntime(runner=runner).submit(_request(), boom)
        assert "炸了" in seen["out"]["error"]  # 工具异常兜底回传模型（同 builtin）
        assert out.finish_reason == "stop" and out.usage.tool_calls == 1

    def test_budget_exhausted_contract(self):
        def runner(inp):
            inp.executor("list_runs", {})
            inp.executor("run_detail", {"run_id": "r1"})
            raise RuntimeBudgetExceeded("request_limit exceeded")

        out = PydanticAIRuntime(runner=runner).submit(_request(), _echo_executor)
        assert out.finish_reason == "budget_exhausted"
        assert NUDGE_MARK in out.text and "继续" in out.text  # builtin 同款续跑契约
        assert out.tools_used == ["list_runs", "run_detail"]
        assert out.action == "run_detail"
        assert out.usage.tool_calls == 2 and out.usage.llm_calls == 1
        assert out.messages[0] == {"role": "system", "content": "你是助手"}  # 现场兜底

    def test_default_runner_is_real_impl(self):
        runtime = PydanticAIRuntime()
        assert runtime._runner is default_pydantic_ai_runner


# ─── 默认 runner 的可选依赖路径（钉住 import 通道，无网络无真库依赖）─────────

class TestDefaultRunnerDependency:
    def test_missing_lib_raises_clear_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pydantic_ai", None)  # None → ImportError
        inp = PaiRunInput(messages=[{"role": "user", "content": "hi"}],
                          tools=[], executor=_echo_executor)
        with pytest.raises(PydanticAINotInstalled, match="pydantic-ai-slim"):
            default_pydantic_ai_runner(inp)

    def test_missing_lib_propagates_from_submit(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pydantic_ai", None)
        runtime = PydanticAIRuntime()  # 默认 runner
        with pytest.raises(PydanticAINotInstalled):
            runtime.submit(_request(), _echo_executor)


class TestChatRuntimeSelection:
    def test_config_runtime_selects_pydantic_ai_and_falls_back(self, monkeypatch, tmp_path):
        """配置 runtime: pydantic_ai + 库缺失 → chat 层既有回退链兜住（#105/#139）。"""
        from rfauto.service import agent_runtime as ar
        from rfauto.service import r3_services
        monkeypatch.setitem(sys.modules, "pydantic_ai", None)  # 钉住：无论环境装没装
        monkeypatch.setattr(ar, "SESSIONS_DIR", tmp_path / "sess")  # 不落真实 runs/
        monkeypatch.setattr(r3_services, "get_chat_settings",
                            lambda: {"ok": True, "configured": True})
        monkeypatch.setattr(r3_services, "get_chat_settings_raw",
                            lambda: {"runtime": "pydantic_ai", "max_tool_rounds": 6})
        chat = r3_services.AgentChat()
        out = chat.chat("solvers")
        assert out["action"] == "list_solvers"  # 关键词路由照常答
        assert "[LLM" in out["text"] and "pydantic-ai" in out["text"]  # 失败原因明示


# ─── 库无关纯函数 ────────────────────────────────────────────────────────────

class TestToolSpecToCallable:
    SPEC_JSON: ClassVar[dict[str, dict[str, str]]] = {"run_id": {"type": "string"},
                                                      "limit": {"type": "integer"}}

    def _spec(self):
        from rfauto.service.agent_runtime import ToolSpec
        return ToolSpec(name="run_detail", description="查看 run 的指标",
                        parameters=dict(self.SPEC_JSON), required=["run_id"])

    def test_name_doc_annotations(self):
        fn = tool_spec_to_callable(self._spec(), _echo_executor)
        assert fn.__name__ == "run_detail"
        assert "run 的指标" in (fn.__doc__ or "")
        assert fn.__annotations__["run_id"] is str
        assert fn.__annotations__["limit"] is int
        assert fn.__annotations__["return"] is dict

    def test_optional_omitted_not_passed(self):
        seen = {}

        def cap(name, args):
            seen["call"] = (name, args)
            return {"ok": True}

        fn = tool_spec_to_callable(self._spec(), cap)
        fn("r9")
        assert seen["call"] == ("run_detail", {"run_id": "r9"})  # 未给的 limit 不透传
        fn("r9", 3)
        assert seen["call"] == ("run_detail", {"run_id": "r9", "limit": 3})

    def test_invalid_param_names_filtered(self):
        from rfauto.service.agent_runtime import ToolSpec
        spec = ToolSpec(name="weird", description="d",
                        parameters={"a-b": {"type": "string"}, "class": {"type": "string"}})
        seen = {}
        fn = tool_spec_to_callable(spec, lambda n, a: seen.update(n=n, a=a) or {})
        fn()
        assert seen == {"n": "weird", "a": {}}  # 非法/关键字参数名不进签名


class TestUsageExtraction:
    def test_modern_names(self):
        u = SimpleNamespace(input_tokens=10, output_tokens=5,
                            cache_read_tokens=2, requests=3)
        assert extract_usage(u) == {"prompt_tokens": 10, "completion_tokens": 5,
                                    "cached_tokens": 2, "requests": 3}

    def test_legacy_aliases(self):
        u = SimpleNamespace(request_tokens=7, response_tokens=4)
        assert extract_usage(u)["prompt_tokens"] == 7
        assert extract_usage(u)["completion_tokens"] == 4

    def test_callable_usage_and_none(self):
        u = SimpleNamespace(input_tokens=1, output_tokens=2)
        assert extract_usage(lambda: u)["prompt_tokens"] == 1
        assert extract_usage(None) == {"prompt_tokens": 0, "completion_tokens": 0,
                                       "cached_tokens": 0, "requests": 0}

    def test_bool_not_counted_as_int(self):
        u = SimpleNamespace(input_tokens=True)  # bool 是 int 子类，排除
        assert extract_usage(u)["prompt_tokens"] == 0


# ─── 消息映射（假类钉死，类名分派与 pydantic-ai 真类同名）────────────────────

class ModelRequest:
    def __init__(self, parts):
        self.parts = parts


class ModelResponse:
    def __init__(self, parts):
        self.parts = parts


class SystemPromptPart:
    def __init__(self, content):
        self.content = content


class UserPromptPart:
    def __init__(self, content):
        self.content = content


class TextPart:
    def __init__(self, content):
        self.content = content


class ToolCallPart:
    def __init__(self, tool_name, args, tool_call_id):
        self.tool_name = tool_name
        self.args = args
        self.tool_call_id = tool_call_id


class ToolReturnPart:
    def __init__(self, tool_name, content, tool_call_id):
        self.tool_name = tool_name
        self.content = content
        self.tool_call_id = tool_call_id


class ThinkingPart:  # 未知 part：映射应 best-effort 跳过
    def __init__(self, content):
        self.content = content


@pytest.fixture
def fake_classes():
    return SimpleNamespace(
        ModelRequest=ModelRequest, ModelResponse=ModelResponse,
        SystemPromptPart=SystemPromptPart, UserPromptPart=UserPromptPart,
        TextPart=TextPart, ToolCallPart=ToolCallPart, ToolReturnPart=ToolReturnPart)


class TestMessageMapping:
    OPENAI_MSGS: ClassVar[list[dict]] = [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "查一下"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "t1", "type": "function",
                         "function": {"name": "list_runs",
                                      "arguments": json.dumps({"limit": 3})}}]},
        {"role": "tool", "tool_call_id": "t1", "name": "list_runs",
         "content": json.dumps({"runs": []}, ensure_ascii=False)},
    ]

    def test_build_history_extracts_trailing_user_prompt(self, fake_classes):
        # 正常首轮：r3 传入的现场以新 user 消息收尾 → 作为 run_sync 的 prompt 取出
        msgs = [*self.OPENAI_MSGS, {"role": "user", "content": "再查一次"}]
        history, prompt = build_pai_history(msgs, fake_classes)
        assert prompt == "再查一次"
        kinds = [type(m).__name__ for m in history]
        assert kinds == ["ModelRequest", "ModelRequest", "ModelResponse", "ModelRequest"]
        assert type(history[0].parts[0]).__name__ == "SystemPromptPart"
        tc = history[2].parts[0]
        assert tc.tool_name == "list_runs" and tc.args == {"limit": 3}
        assert tc.tool_call_id == "t1"
        tr = history[3].parts[0]
        assert tr.tool_name == "list_runs" and tr.tool_call_id == "t1"

    def test_continuation_scene_empty_prompt(self, fake_classes):
        # 续跑现场止于 tool 结果（无尾随 user）→ prompt=""（悬空工具调用由
        # pydantic-ai 侧合成收口，见 default runner docstring）
        msgs_no_user = [m for m in self.OPENAI_MSGS if m.get("role") != "user"]
        _, prompt = build_pai_history(msgs_no_user, fake_classes)
        assert prompt == ""

    def test_roundtrip_to_openai(self, fake_classes):
        history, _prompt = build_pai_history(self.OPENAI_MSGS, fake_classes)
        history.append(ModelResponse(parts=[TextPart(content="结论：正常")]))
        out = pai_messages_to_openai(history)
        assert out[0] == {"role": "system", "content": "你是助手"}
        assert {"role": "user", "content": "查一下"} in out
        assistant = next(m for m in out if m["role"] == "assistant")
        assert assistant["tool_calls"][0]["function"]["name"] == "list_runs"
        assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"limit": 3}
        tool_msg = next(m for m in out if m["role"] == "tool")
        assert tool_msg["tool_call_id"] == "t1" and "runs" in tool_msg["content"]
        assert out[-1] == {"role": "assistant", "content": "结论：正常"}

    def test_unknown_parts_skipped(self, fake_classes):
        m = ModelRequest(parts=[UserPromptPart(content="hi"), ThinkingPart(content="嗯")])
        out = pai_messages_to_openai([m])
        assert out == [{"role": "user", "content": "hi"}]

    def test_empty_and_none(self):
        assert pai_messages_to_openai(None) == []
        history, prompt = build_pai_history([], fake_classes)
        assert history == [] and prompt == ""


# ─── ② agent.iter() 事件流：预算路径无损续跑（假 AgentRun，离线钉死）────────

class _FakeUsageLimits:
    def __init__(self, request_limit=50):
        self.request_limit = request_limit


class _FakeLimitExceeded(RuntimeError):
    """镜像 pydantic_ai.exceptions.UsageLimitExceeded（RuntimeError 子类）。"""


class _FakeRunBase:
    """镜像 AgentRun：async 迭代节点，可在第 raise_at 步抛预算异常；
    all_messages()/usage/result 在异常后仍可读（上游 run.py 契约）。"""

    def __init__(self, *, messages, usage, output=None, nodes=3, raise_at=None):
        self._messages = messages
        self._usage = usage
        self._output = output
        self._nodes = nodes
        self._raise_at = raise_at
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._raise_at is not None and self._i == self._raise_at:
            raise _FakeLimitExceeded("The next request would exceed the request_limit of 2")
        if self._i >= self._nodes:
            raise StopAsyncIteration
        self._i += 1
        return f"node{self._i}"

    def all_messages(self):
        return self._messages

    @property
    def result(self):
        return None if self._output is None else SimpleNamespace(output=self._output)


class _FakeRunUsageProperty(_FakeRunBase):
    """2.x：AgentRun.usage 是 property（RunUsage 实例）。"""

    @property
    def usage(self):
        return self._usage


class _FakeRunUsageMethod(_FakeRunBase):
    """1.x：AgentRun.usage() 是方法。"""

    def usage(self):
        return self._usage


class _FakeAgent:
    def __init__(self, run):
        self._run = run
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    @asynccontextmanager
    async def iter(self, user_prompt=None, **kw):
        self.calls.append((user_prompt, dict(kw)))
        yield self._run


def _fake_pai_messages():
    return [ModelRequest(parts=[SystemPromptPart(content="你是助手")]),
            ModelRequest(parts=[UserPromptPart(content="查一下")]),
            ModelResponse(parts=[ToolCallPart(tool_name="list_runs", args={"limit": 3},
                                              tool_call_id="t1")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="list_runs", content='{"runs": []}',
                                               tool_call_id="t1")])]


def _bundle(run, prompt="查一下"):
    return PaiAgentBundle(
        agent=_FakeAgent(run), history=["h0", "h1"], prompt=prompt,
        pai=SimpleNamespace(UsageLimits=_FakeUsageLimits,
                            UsageLimitExceeded=_FakeLimitExceeded))


def _inp(max_rounds=4):
    return PaiRunInput(messages=[{"role": "system", "content": "你是助手"},
                                 {"role": "user", "content": "查一下"}],
                       tools=[], executor=_echo_executor, max_rounds=max_rounds)


class TestIterBudgetPathLossless:
    def test_budget_exhausted_carries_messages_and_usage(self):
        usage = SimpleNamespace(input_tokens=210, output_tokens=30, cache_read_tokens=5, requests=2)
        run = _FakeRunUsageProperty(messages=_fake_pai_messages(), usage=usage, raise_at=2)
        bundle = _bundle(run)
        with pytest.raises(RuntimeBudgetExceeded) as ei:
            run_pai_agent(bundle, _inp())
        exc = ei.value
        assert "request_limit" in str(exc)
        # 截至当前的完整现场（含工具调用与工具结果），不是进入时现场
        assert [m["role"] for m in exc.messages] == ["system", "user", "assistant", "tool"]
        assert exc.messages[-1]["tool_call_id"] == "t1"
        assert exc.usage == {"prompt_tokens": 210, "completion_tokens": 30,
                             "cached_tokens": 5, "requests": 2}
        # 预算映射：request_limit=max_rounds；温度透传；history 原样传入
        user_prompt, kw = bundle.agent.calls[0]
        assert user_prompt == "查一下"
        assert kw["usage_limits"].request_limit == 4
        assert kw["model_settings"] == {"temperature": 0.3}
        assert kw["message_history"] == ["h0", "h1"]

    def test_adapter_consumes_recovered_scene(self):
        usage = SimpleNamespace(input_tokens=210, output_tokens=30, cache_read_tokens=5, requests=2)
        run = _FakeRunUsageProperty(messages=_fake_pai_messages(), usage=usage, raise_at=2)
        bundle = _bundle(run)
        out = PydanticAIRuntime(runner=lambda inp: run_pai_agent(bundle, inp)).submit(
            _request(), _echo_executor)
        assert out.finish_reason == "budget_exhausted"
        assert NUDGE_MARK in out.text and "继续" in out.text
        assert out.messages[-1]["role"] == "tool"  # 无损：续跑现场止于工具结果
        assert out.usage.prompt_tokens == 210 and out.usage.completion_tokens == 30
        assert out.usage.cached_tokens == 5 and out.usage.llm_calls == 2
        assert out.usage.llm_elapsed_s >= 0.0

    def test_legacy_runner_without_payload_falls_back_to_entry_scene(self):
        def runner(inp):
            raise RuntimeBudgetExceeded("old style")  # 不带 messages/usage

        out = PydanticAIRuntime(runner=runner).submit(_request(), _echo_executor)
        assert out.finish_reason == "budget_exhausted"
        assert out.messages[0] == {"role": "system", "content": "你是助手"}
        assert out.usage.prompt_tokens == 0 and out.usage.llm_calls == 1

    def test_stop_path_usage_property_2x(self):
        msgs = [*_fake_pai_messages(), ModelResponse(parts=[TextPart(content="结论：正常")])]
        usage = SimpleNamespace(input_tokens=300, output_tokens=60, cache_read_tokens=0, requests=3)
        run = _FakeRunUsageProperty(messages=msgs, usage=usage, output="结论：正常")
        res = run_pai_agent(_bundle(run), _inp())
        assert res.text == "结论：正常"
        assert (res.prompt_tokens, res.completion_tokens, res.requests) == (300, 60, 3)
        assert res.messages[-1] == {"role": "assistant", "content": "结论：正常"}

    def test_stop_path_usage_method_1x(self):
        msgs = [*_fake_pai_messages(), ModelResponse(parts=[TextPart(content="ok")])]
        usage = SimpleNamespace(input_tokens=7, output_tokens=4, requests=1)
        run = _FakeRunUsageMethod(messages=msgs, usage=usage, output="ok")
        res = run_pai_agent(_bundle(run), _inp())
        assert (res.prompt_tokens, res.completion_tokens, res.requests) == (7, 4, 1)

    def test_adapter_llm_calls_from_requests(self):
        msgs = [*_fake_pai_messages(), ModelResponse(parts=[TextPart(content="ok")])]
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, requests=3)
        run = _FakeRunUsageProperty(messages=msgs, usage=usage, output="ok")
        bundle = _bundle(run)
        out = PydanticAIRuntime(runner=lambda inp: run_pai_agent(bundle, inp)).submit(
            _request(), _echo_executor)
        assert out.finish_reason == "stop" and out.usage.llm_calls == 3

    def test_continuation_scene_passes_none_prompt(self):
        # 续跑现场无尾随 user → prompt=""，必须转 None（否则 pydantic-ai 多出空 UserPromptPart）
        run = _FakeRunUsageProperty(messages=_fake_pai_messages(),
                                    usage=SimpleNamespace(requests=1), output="续")
        bundle = _bundle(run, prompt="")
        run_pai_agent(bundle, _inp())
        assert bundle.agent.calls[0][0] is None

    def test_non_str_output_serialized(self):
        run = _FakeRunUsageProperty(messages=[], usage=None, output={"k": 1})
        assert run_pai_agent(_bundle(run), _inp()).text == '{"k": 1}'

    def test_run_coroutine_sync_inside_running_loop(self):
        async def inner():
            return 42

        async def outer():
            return _run_coroutine_sync(inner)  # 已在循环内 → 线程独立循环兜底

        assert asyncio.run(outer()) == 42
        assert _run_coroutine_sync(inner) == 42  # 无循环 → asyncio.run


# ─── ③ 真类离线构造冒烟（装了 pydantic-ai 才跑；只构造不请求，零网络）────────

@pytest.mark.skipif(not lib_available(), reason="pydantic-ai 未安装（可选组 pai）")
class TestOfflineConstructionSmoke:
    OPENAI_MSGS: ClassVar[list[dict]] = TestMessageMapping.OPENAI_MSGS

    def _build(self, **kw):
        inp = PaiRunInput(messages=[*self.OPENAI_MSGS, {"role": "user", "content": "再查一次"}],
                          tools=[ToolSpec("run_detail", "查看 run", {"run_id": {"type": "string"}},
                                          ["run_id"])],
                          executor=_echo_executor)
        return build_pai_agent(inp, model_name=kw.get("model_name", "dummy-model"),
                               base_url=kw.get("base_url", "http://127.0.0.1:9"),
                               api_key="x")

    def test_real_classes_construct_and_roundtrip(self):
        bundle = self._build()
        assert bundle.pai.model_cls.__name__ in ("OpenAIChatModel", "OpenAIModel")
        assert bundle.agent.model.model_name == "dummy-model"
        toolset = getattr(bundle.agent, "_function_toolset", None)
        if toolset is not None and hasattr(toolset, "tools"):  # 私有属性 best-effort
            assert "run_detail" in toolset.tools
        assert bundle.prompt == "再查一次"
        kinds = [type(m).__name__ for m in bundle.history]
        assert kinds == ["ModelRequest", "ModelRequest", "ModelResponse", "ModelRequest"]
        assert bundle.history[2].parts[0].args == {"limit": 3}  # 真 ToolCallPart 保持 dict
        # 真类 → OpenAI 风格回环（续跑现场落盘路径）
        back = pai_messages_to_openai(bundle.history)
        assert [m["role"] for m in back] == ["system", "user", "assistant", "tool"]
        assert json.loads(back[2]["tool_calls"][0]["function"]["arguments"]) == {"limit": 3}
        assert bundle.pai.UsageLimits(request_limit=2).request_limit == 2
        assert issubclass(bundle.pai.UsageLimitExceeded, RuntimeError)

    def test_usage_attribute_generation(self):
        # ③ 抓出的真差异：2.x AgentRun/AgentRunResult.usage 是 property（不能 .usage()），
        # 1.x 是方法——extract_usage 对属性值原样处理两代
        from pydantic_ai.run import AgentRun, AgentRunResult
        major = int((lib_version() or "0").split(".")[0])
        is_prop = isinstance(inspect.getattr_static(AgentRun, "usage"), property)
        is_prop_res = isinstance(inspect.getattr_static(AgentRunResult, "usage"), property)
        if major >= 2:
            assert is_prop and is_prop_res
        else:
            assert not is_prop
        from pydantic_ai.usage import RunUsage
        u = RunUsage(input_tokens=5, output_tokens=2, requests=1)
        assert extract_usage(u) == {"prompt_tokens": 5, "completion_tokens": 2,
                                    "cached_tokens": 0, "requests": 1}

    def test_base_url_normalized_and_config_guard(self):
        bundle = self._build(base_url="http://127.0.0.1:9/")
        assert str(bundle.agent.model.client.base_url).rstrip("/").endswith("/v1")
        with pytest.raises(RuntimeError, match=r"chat_settings\.yaml"):
            self._build(model_name="")

    def test_default_runner_wiring_without_network(self, monkeypatch):
        from rfauto.service import pydantic_ai_runtime as mod
        from rfauto.service import r3_services
        monkeypatch.setattr(r3_services, "get_chat_settings_raw",
                            lambda: {"base_url": "http://127.0.0.1:9", "model": "dummy-model",
                                     "api_key": "x"})
        seen = {}

        def fake_run(bundle, inp):
            seen["bundle"] = bundle
            return PaiRunResult(text="wired", requests=1)

        monkeypatch.setattr(mod, "run_pai_agent", fake_run)
        res = default_pydantic_ai_runner(PaiRunInput(
            messages=[{"role": "user", "content": "hi"}], tools=[], executor=_echo_executor))
        assert res.text == "wired"
        assert seen["bundle"].prompt == "hi" and seen["bundle"].history == []
        assert seen["bundle"].agent.model.model_name == "dummy-model"
