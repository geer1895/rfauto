"""AgentRuntime：可插拔 LLM 工具循环（薄协议）。

协议只有一个方法：submit(request, executor) -> RuntimeResult。
自研 OpenAI 兼容实现为默认（BuiltinOpenAIRuntime）；未来接 pydantic-ai
等框架时按同协议实现并注册进 RuntimeRegistry 即可替换，互不影响。

借鉴 Pi（earendil-works/pi，2026-09-02 调研）两点：
- 遥测契约：每次 LLM/工具调用都进结构化计数器，随响应回传并可落盘；
- 会话公开格式：对话历史+遥测以带 schema 版本的 JSON 落盘，可复核可迁移。

DS-1 工具执行瀑布（W5-B，2026-10-05）：RuntimeRequest.waterfall 非 None
时，工具调用走 agent_safety.ToolWaterfall 五段事件级瀑布（pre-execute→
guards→approval→execute→post-execute + additionalContexts FIFO）；缺省
None 时与直执行路径逐字节相同（缺省路径零变化）。瀑布任何段故障只
降级、不阻塞工具主路径（#105）。

沙箱约定见 agent_sandbox.py：agent 自主改配方只能改沙箱草稿，
生效必须走既有三层 Gate（propose→收件箱批准→apply）。
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from rfauto.service.envelope import error_envelope

if TYPE_CHECKING:
    from rfauto.pipeline.quota_guard import CostLedger
    from rfauto.service.agent_safety import ToolEvent, ToolWaterfall

# 工具执行器：名字+参数 → 结果 dict（异常由运行时兜底回传模型）
ToolExecutor = Callable[[str, dict[str, Any]], dict[str, Any]]
# LLM 传输层：messages+工具 schema → OpenAI 兼容响应 dict
LLMTransport = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]

SESSION_SCHEMA = "rfauto-chat-session-v1"
SESSIONS_DIR = Path("runs") / "chat_sessions"

# 可选 runtime 插件：create() 按需 best-effort 导入（pydantic-ai 未装不阻塞，#105）。
OPTIONAL_RUNTIME_PLUGINS = ("rfauto.service.pydantic_ai_runtime",)

_plugin_loaded: set[str] = set()


def _load_optional_plugins() -> None:
    """按需导入可选 runtime 插件模块（注册副作用）。缺失/损坏静默跳过。"""
    import importlib

    for plugin in OPTIONAL_RUNTIME_PLUGINS:
        if plugin in _plugin_loaded:
            continue
        try:
            importlib.import_module(plugin)
        except Exception:  # 可选依赖缺失/损坏：不阻塞运行时主链路（#105）
            pass
        finally:
            _plugin_loaded.add(plugin)


# ─── 工具结果 → LLM 上下文渲染单源（DS-2 留痕不变量的"可见面"定义）────────
# 留痕摘要（session_audit_service.content_digest）与运行时注入消息必须吃
# 同一渲染，"LLM 可见即留痕"才有单一判据；改这里即同时改两处（单源）。

TOOL_CONTENT_MAX_CHARS = 4000


def render_tool_content(result: dict[str, Any]) -> str:
    """工具结果 dict → LLM 可见文本全文（json.dumps 确定性序列化）。"""
    return json.dumps(result, ensure_ascii=False, default=str)


def tool_context_content(result: dict[str, Any]) -> str:
    """注入上下文的工具消息正文（渲染 + 截断，与历史 builtin 行为逐字节同）。"""
    return render_tool_content(result)[:TOOL_CONTENT_MAX_CHARS]


def waterfall_tool_content(event: ToolEvent) -> str:
    """瀑布事件 → 工具消息正文：主结果 + additionalContexts FIFO 附加块。

    附加上下文按事件里的追加序（=钩子注册序 FIFO）逐块渲染在主结果之后，
    块前缀 ``[additionalContext]`` 便于模型区分主结果与旁注。无附加上下文
    时与 ``tool_context_content(event.final_result())`` 逐字节同（缺省路径
    零变化的渲染面契约，钉在单测）。
    """
    parts = [tool_context_content(event.final_result())]
    for ctx in event.additional_contexts:
        parts.append("[additionalContext] " + tool_context_content(ctx))
    return "\n".join(parts)


@dataclass
class ToolSpec:
    """工具声明（LLM function-calling schema 的数据形态）。"""
    name: str
    description: str
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    def to_schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object",
                           "properties": self.parameters,
                           "required": self.required}}}


@dataclass
class RuntimeRequest:
    """一次提交：完整消息列表 + 工具表 + 循环预算。

    extra_system（AD-3 few-shot 注入面，本批最小追加）：非空时在既有
    system 消息之后追加一条 system 消息（few_shot_service.render_few_shot_section
    的产物走这里）；缺省 None 时行为与本字段加入前逐字节相同（不复制
    messages、零注入）。

    waterfall（DS-1 工具执行瀑布，W5-B）：非 None 时所有工具调用经
    agent_safety.ToolWaterfall 五段事件级瀑布（策略注记→deny/abstain
    裁决→一次性审批→超时/重试执行→后置 block/replace/addContext）；
    事件现场随 RuntimeResult.tool_events 回传供审计。缺省 None 时与本
    字段加入前逐字节相同（直执行，零瀑布开销、零行为变化）。
    """
    messages: list[dict[str, Any]]
    tools: list[ToolSpec] = field(default_factory=list)
    max_rounds: int = 12
    temperature: float = 0.3
    extra_system: str | None = None
    waterfall: ToolWaterfall | None = None


@dataclass
class RuntimeUsage:
    """遥测契约：本次 submit 内的调用计数与耗时。"""
    llm_calls: int = 0
    llm_elapsed_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    tool_calls: int = 0
    tool_elapsed_s: float = 0.0


@dataclass
class RuntimeResult:
    """运行时产物：最终文本 + 现场（续跑用）+ 遥测。"""
    text: str
    finish_reason: str = "stop"          # stop | budget_exhausted
    messages: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    action: str | None = None            # 最后一次工具名（兼容 AgentChat 响应）
    result: dict[str, Any] = field(default_factory=dict)
    usage: RuntimeUsage = field(default_factory=RuntimeUsage)
    tool_events: list[ToolEvent] = field(default_factory=list)  # DS-1 瀑布现场（缺省空）


class AgentRuntime(ABC):
    """工具循环运行时接口。实现方决定循环策略，工具执行交回调用方。"""

    name: str = "base"

    @abstractmethod
    def submit(self, request: RuntimeRequest, executor: ToolExecutor) -> RuntimeResult:
        """驱动 LLM↔工具循环直至产出最终答复或预算耗尽。"""


def usage_to_cost_ledger(
    usage: RuntimeUsage, ledger: CostLedger, *, batch: str, actor: str
) -> CostLedger:
    """把一次 submit 的 RuntimeUsage 记入 G14 CostLedger（薄适配）。

    复用 pipeline.quota_guard.CostLedger 既有内核与字段口径，不新建账本；
    CostLedger 接口不匹配处只做参数搬运、零换算（记账原值直录，不产生
    新数字）。字段映射：

    * ``usage.prompt_tokens → prompt_tokens``、``usage.completion_tokens →
      completion_tokens``（显式拆分口径；"仅总数"槽位 ``tokens`` 不记，
      避免同一批 token 双计入 ``total_tokens``）；
    * ``usage.cached_tokens`` 是 prompt_tokens 的子集（OpenAI 语义，已含在
      prompt 内），CostLedger 无对应字段，不重复入账；
    * ``llm_elapsed_s`` / ``tool_elapsed_s`` 是 LLM/工具墙钟而非求解器机时，
      不记 ``solve_s``（否则会污染 wall_hours 预算门的物理语义）。

    模型名不经 RuntimeUsage 携带（遥测契约无此字段），由调用方以 ``actor``
    显式给出（如 chat 设置里的 model 名）。
    """
    from rfauto.pipeline.quota_guard import CostLedger as _CostLedger

    if not isinstance(ledger, _CostLedger):
        raise TypeError(
            f"ledger 必须是 pipeline.quota_guard.CostLedger，得 {type(ledger).__name__}")
    return ledger.add(
        str(batch), str(actor),
        prompt_tokens=int(usage.prompt_tokens),
        completion_tokens=int(usage.completion_tokens))


class RuntimeRegistry:
    """运行时注册表（基类+注册表模式，同 EMSolverRegistry）。"""

    _runtimes: ClassVar[dict[str, type[AgentRuntime]]] = {}

    @classmethod
    def register(cls, runtime_cls: type[AgentRuntime]) -> type[AgentRuntime]:
        cls._runtimes[runtime_cls.name] = runtime_cls
        return runtime_cls

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> AgentRuntime:
        if name not in cls._runtimes:
            _load_optional_plugins()  # 未命中时先尝试可选插件（pydantic_ai 等）
        if name not in cls._runtimes:
            raise KeyError(f"未注册的运行时: {name}（可用: {cls.available()}）")
        return cls._runtimes[name](**kwargs)

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._runtimes)


@RuntimeRegistry.register
class BuiltinOpenAIRuntime(AgentRuntime):
    """默认实现：OpenAI 兼容 /chat/completions + function calling。

    循环策略（自研迭代沉淀）：预算递减催办（末段强制收敛）、工具异常
    回传模型自行调整、预算耗尽保留完整现场供无损续跑。
    """

    name = "builtin"

    def __init__(self, transport: LLMTransport | None = None):
        self._transport = transport or openai_chat_completion

    def submit(self, request: RuntimeRequest, executor: ToolExecutor) -> RuntimeResult:
        usage = RuntimeUsage()
        messages = request.messages
        if request.extra_system:
            # AD-3 注入面：浅拷贝后再插（不改调用方列表；插在最后一条
            # 起始 system 消息之后，保持 system 块在前的前缀约定）
            messages = list(messages)
            idx = 0
            while idx < len(messages) and messages[idx].get("role") == "system":
                idx += 1
            messages.insert(idx, {"role": "system",
                                  "content": str(request.extra_system)})
        tools_used: list[str] = []
        tool_events: list[ToolEvent] = []
        action, result = None, None
        tool_dicts = [t.to_schema() for t in request.tools]
        max_rounds = max(1, int(request.max_rounds))

        for round_no in range(max_rounds):
            if round_no == max_rounds - 2:
                # 预算递减催办：模型常把轮数耗在探索上（实测 MiMo），末段强制收敛
                messages.append({"role": "system", "content":
                    "工具预算只剩 2 次。请立即基于已有信息完成任务：若用户要参数提案，"
                    "现在就调用 propose_params；否则直接给出最终文字答复。"
                    "不要再调用只读探索工具。"})
            t0 = time.perf_counter()
            resp = self._transport(messages, tool_dicts)
            usage.llm_calls += 1
            usage.llm_elapsed_s += time.perf_counter() - t0
            usage.prompt_tokens += int((resp.get("usage", {}) or {}).get("prompt_tokens") or 0)
            usage.completion_tokens += int(
                (resp.get("usage", {}) or {}).get("completion_tokens") or 0)
            usage.cached_tokens += int(((resp.get("usage", {}) or {})
                                        .get("prompt_tokens_details") or {})
                                       .get("cached_tokens") or 0)
            msg_out = resp["choices"][0]["message"]
            if not msg_out.get("tool_calls"):
                return RuntimeResult(text=msg_out.get("content") or "",
                                     finish_reason="stop", messages=messages,
                                     tools_used=tools_used,
                                     action=action, result=result or {},
                                     usage=usage, tool_events=tool_events)
            messages.append(msg_out)
            for tc in msg_out["tool_calls"]:
                fn = tc["function"]["name"]
                tools_used.append(fn)
                t1 = time.perf_counter()
                event: ToolEvent | None = None
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception as exc:  # 参数坏：回传模型自行调整（原行为）
                    result = {"error": str(exc)}
                else:
                    wf = request.waterfall
                    if wf is None:
                        # 缺省路径：直执行（与瀑布字段加入前逐字节相同）
                        try:
                            result = executor(fn, args)
                        except Exception as exc:  # 工具异常回传给模型自行调整
                            result = {"error": str(exc)}
                    else:
                        # DS-1 五段瀑布；瀑布自身故障只降级不阻塞主路径（#105）
                        try:
                            event = wf.run(fn, args, executor)
                            result = event.final_result()
                        except Exception as exc:
                            result = error_envelope(
                                [f"工具瀑布降级：{exc}"], stage="waterfall")
                        else:
                            tool_events.append(event)
                usage.tool_calls += 1
                usage.tool_elapsed_s += time.perf_counter() - t1
                action = fn
                content = (waterfall_tool_content(event) if event is not None
                           else tool_context_content(result))
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": content})

        summary = "、".join(dict.fromkeys(tools_used)) or "无"
        return RuntimeResult(
            text=f"本轮已完成 {len(tools_used)} 次工具调用（{summary}），达到单轮上限。"
                 f"回复『继续』将从已有进度接着分析（不重复探索）。",
            finish_reason="budget_exhausted", messages=messages,
            tools_used=tools_used, action=action, result=result or {},
            usage=usage, tool_events=tool_events)


def openai_chat_completion(
        messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    """默认传输层：OpenAI 兼容 /chat/completions（configs/chat_settings.yaml）。"""
    import urllib.request

    from rfauto.service.r3_services import get_chat_settings_raw
    cfg = get_chat_settings_raw()
    base = (cfg.get("base_url") or "").rstrip("/")
    url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    body = json.dumps({"model": cfg.get("model", ""), "messages": messages,
                       "tools": tools, "temperature": 0.3}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + (cfg.get("api_key") or "")})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def default_tool_specs() -> list[ToolSpec]:
    """内置工具表：只读探索 + Gate 提案 + 沙箱草稿（写面隔离）。"""
    return [ToolSpec(*spec) for spec in [
        ("list_solvers", "列出已注册求解器及可用性", {}, []),
        ("list_runs", "列出最近的 run", {"limit": {"type": "integer"}}, []),
        ("run_detail", "查看 run 的指标与产物",
         {"run_id": {"type": "string"}}, ["run_id"]),
        ("validate_recipe", "校验配方文件", {"path": {"type": "string"}}, ["path"]),
        ("diagnose_run", "读取 run 的诊断信息",
         {"run_id": {"type": "string"}}, ["run_id"]),
        ("propose_params", "为配方生成参数提案（走 Gate 审批）",
         {"recipe": {"type": "string"}, "params": {"type": "object"}}, ["recipe"]),
        ("edit_recipe_draft", "把参数修改写入配方的沙箱草稿（不触碰真实配方；"
         "需 promote_recipe_draft 走审批才生效）",
         {"recipe": {"type": "string"}, "params": {"type": "object"}},
         ["recipe", "params"]),
        ("diff_recipe_draft", "对比沙箱草稿与真实配方的差异",
         {"recipe": {"type": "string"}}, ["recipe"]),
        ("promote_recipe_draft", "把沙箱草稿的参数差异提交三层 Gate 审批，"
         "用户在收件箱批准后才生效",
         {"recipe": {"type": "string"}}, ["recipe"]),
    ]]


# ─── Pi 式会话公开格式（schema 版本化 JSON，可复核可迁移）────────────────────

def new_session_doc(session_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    return {"schema": SESSION_SCHEMA, "session_id": session_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "meta": meta, "history": [], "tool_calls": [], "stats": {}}


def persist_session(doc: dict[str, Any]) -> Path:
    """整会话落盘（观测路径，调用方须自行 try/except，不阻塞主链路 #105）。"""
    doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    # runs 双根收敛（R3-9）：cwd 相对缺省根 chdir 仓内子目录时收敛回仓库
    # runs/；测试 monkeypatch 的绝对 SESSIONS_DIR 原样（resolve_runs_dir 透传）。
    from rfauto.infra.runs_paths import resolve_runs_dir

    sessions_dir = resolve_runs_dir(SESSIONS_DIR)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{doc.get('session_id', 'session')}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                    encoding="utf-8")
    return path


def load_session(path: str | Path) -> dict[str, Any]:
    """读取会话存档（带 schema 校验，向前兼容留给后续版本）。"""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != SESSION_SCHEMA:
        raise ValueError(f"不支持的会话 schema: {doc.get('schema')}")
    return doc
