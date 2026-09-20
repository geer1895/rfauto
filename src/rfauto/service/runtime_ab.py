"""Runtime A/B token 效率仪表（WP3.1 验收件：离线结构 A/B + live 真模型 A/B）。

方案口径（runtime 通道可替换，A/B 对照）：runtime: pydantic_ai
与 builtin A/B token 效率后再决定是否切默认。

离线结构 A/B（compare_runtime_token_efficiency，确定性、进测试）：同一脚本化
模型轨迹（相同的工具调用序列、参数与脚本 token 计数）分别通过两个 runtime 的
注入缝驱动——builtin 注入 transport、pydantic_ai 注入 runner——逐次记录出站
载荷（messages+工具表 JSON 字符数）。它度量的是「runtime 层注入的结构性增量」：
builtin 的末段催办 system 消息、工具结果 4000 字符截断等；库内序列化差异如实记
``lib_overhead``（不假装测过）。

live 真模型 A/B（live_runtime_ab，需外网+API key，#139 禁入测试，运行时批次
由 scripts/runtime_ab_live.py 调用、证据落 scripts/runtime_ab_live_out/）：同一
prompt/系统提示/只读工具表/预算，交替经 builtin（真实 transport）与 pydantic_ai
（默认 runner 同款 build+run，仅 http_client 换成带请求钩子的客户端）各跑
repeats 次，逐次记录模型上报 token、真实出站 body 字节、工具序列、收尾与耗时。

默认裁决 recommend_default()：只有「真机（真模型）A/B 留档 + 库可用 + 相对
builtin 节省 ≥5%」三条件齐备才建议切默认；live 模式按模型上报总 token
（prompt+completion 均值）计节省，离线/缺 token 时按总线字符计。
真机实测（evidence.json）：builtin 17663 vs pydantic_ai 18135 token
（省 −2.7%）、pydantic_ai 1/3 budget_exhausted → 维持 builtin。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rfauto.service.agent_runtime import (
    BuiltinOpenAIRuntime,
    RuntimeRequest,
    RuntimeResult,
    ToolExecutor,
    ToolSpec,
)
from rfauto.service.pydantic_ai_runtime import (
    PaiRunInput,
    PaiRunResult,
    PydanticAIRuntime,
    RuntimeBudgetExceeded,
)

# 切默认门槛：挑战者相对 builtin 至少省 5%，且有真模型 A/B 佐证
SWITCH_MIN_SAVING_RATIO = 0.05
NUDGE_MARK = "工具预算只剩"
EST_HEURISTIC = "CJK 字符=1 token/字，其余=4 字符/token（粗估，只用于量级对比）"

# live A/B 默认任务：只读探索（不触发 Gate/沙箱写面），两轨工具结果同源（真实 run 库）
LIVE_PROMPT = ("列出最近 3 个 run，挑其中 1 个查看指标，然后用中文给出简短结论"
               "（只读探索，不要提议或修改参数）。")
LIVE_READONLY_TOOLS = ("list_solvers", "list_runs", "run_detail", "validate_recipe", "diagnose_run")
WIRE_NOTE = ("wire 字节=各自真实出站 HTTP body（builtin: urllib+json.dumps ensure_ascii；"
             "pydantic_ai: openai SDK/httpx2 序列化）——序列化器不同，字节数只作量级参考，"
             "裁决按模型上报 token")


def lib_available() -> bool:
    """pydantic_ai 是否可导入（find_spec，不真正 import）。"""
    from importlib.util import find_spec

    try:
        return find_spec("pydantic_ai") is not None
    except Exception:
        return False


def lib_version() -> str | None:
    """已装 pydantic-ai-slim 版本（缺失 None；留档用）。"""
    from importlib.metadata import PackageNotFoundError, version

    for dist in ("pydantic-ai-slim", "pydantic-ai"):
        try:
            return version(dist)
        except PackageNotFoundError:
            continue
    return None


def estimate_tokens(text: str) -> int:
    """确定性粗估（EST_HEURISTIC）：CJK 记 1 token/字，其余 4 字符/token。"""
    cjk = sum(1 for ch in text if "\u3000" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff")
    other = len(text) - cjk
    return cjk + -(-other // 4)


@dataclass
class ScriptedTurn:
    """脚本化模型轮：工具调用或最终文本 + 脚本 token 计数（两轨同源）。"""

    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    text: str | None = None
    prompt_tokens: int = 100
    completion_tokens: int = 20


class BuiltinScriptedTransport:
    """builtin 注入缝：逐次回脚本响应，记录每次出站载荷字符数与催办注入。"""

    def __init__(self, turns: list[ScriptedTurn]):
        self.turns = list(turns)
        self.wire_chars: list[int] = []
        self.nudge_hits = 0
        self.nudge_chars = 0
        self.nudge_text_sample: str = ""

    def __call__(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        chars = (len(json.dumps(messages, ensure_ascii=False, default=str))
                 + len(json.dumps(tools, ensure_ascii=False, default=str)))
        self.wire_chars.append(chars)
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "system" and NUDGE_MARK in str(m.get("content")):
                self.nudge_hits += 1
                blob = len(json.dumps(m, ensure_ascii=False, default=str))
                self.nudge_chars += blob
                self.nudge_text_sample = self.nudge_text_sample or str(m.get("content"))
                break
        turn = self.turns.pop(0)
        usage = {"prompt_tokens": turn.prompt_tokens,
                 "completion_tokens": turn.completion_tokens,
                 "prompt_tokens_details": {"cached_tokens": 0}}
        if turn.text is not None:
            return {"choices": [{"message": {"role": "assistant", "content": turn.text}}],
                    "usage": usage}
        tool_calls = [{"id": f"t{i + 1}", "type": "function",
                       "function": {"name": n,
                                    "arguments": json.dumps(a, ensure_ascii=False)}}
                      for i, (n, a) in enumerate(turn.tool_calls)]
        return {"choices": [{"message": {"role": "assistant", "content": None,
                                         "tool_calls": tool_calls}}],
                "usage": usage}


def make_pai_scripted_runner(
        turns: list[ScriptedTurn],
        ledger: dict[str, Any]) -> Callable[[PaiRunInput], PaiRunResult]:
    """pydantic_ai 注入缝：镜像 builtin 的逐轮载荷结构（历史增长+同款截断），
    唯一差集 = runtime 注入内容（pydantic_ai 适配器侧为 0 注入）。"""

    def run(inp: PaiRunInput) -> PaiRunResult:
        acc: list[dict[str, Any]] = [dict(m) for m in inp.messages]
        schemas = [t.to_schema() for t in inp.tools]
        prompt_tokens = completion_tokens = 0
        text: str | None = None
        rounds = max(1, int(inp.max_rounds))
        for i in range(rounds):
            if i >= len(turns):
                break
            turn = turns[i]
            ledger["wire_chars"].append(
                len(json.dumps(acc, ensure_ascii=False, default=str))
                + len(json.dumps(schemas, ensure_ascii=False, default=str)))
            prompt_tokens += turn.prompt_tokens
            completion_tokens += turn.completion_tokens
            if turn.text is not None:
                text = turn.text
                acc.append({"role": "assistant", "content": text})
                break
            tool_calls = [{"id": f"t{j + 1}", "type": "function",
                           "function": {"name": n,
                                        "arguments": json.dumps(a, ensure_ascii=False)}}
                          for j, (n, a) in enumerate(turn.tool_calls)]
            acc.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except Exception:
                    args = {}
                out = inp.executor(tc["function"]["name"], args)
                # 镜像 builtin 的 4000 字符截断，保持两轨差集只有注入内容
                acc.append({"role": "tool", "tool_call_id": tc["id"],
                            "content": json.dumps(out, ensure_ascii=False,
                                                  default=str)[:4000]})
        if text is None:
            raise RuntimeBudgetExceeded("脚本轨迹耗尽且未出现最终文本")
        return PaiRunResult(text=str(text), prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens, cached_tokens=0,
                            requests=min(len(turns), rounds), messages=acc)

    return run


def _echo_executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "tool": name}


def compare_runtime_token_efficiency(
        turns: list[ScriptedTurn] | None = None,
        *,
        max_rounds: int = 4,
        tools: list[ToolSpec] | None = None,
        executor: ToolExecutor | None = None,
        messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """离线结构 A/B：返回两轨逐轮载荷、注入差、公平性与默认裁决。"""
    from rfauto.service.agent_runtime import default_tool_specs

    if turns is None:
        turns = [ScriptedTurn(tool_calls=[("list_runs", {"limit": 3})]),
                 ScriptedTurn(tool_calls=[("run_detail", {"run_id": "r1"})]),
                 ScriptedTurn(text="结论：两个 run 指标正常。")]
    if tools is None:
        tools = default_tool_specs()
    executor = executor or _echo_executor
    if messages is None:
        messages = [{"role": "system", "content": "你是 rfauto 助手，用中文简洁回答。"},
                    {"role": "user", "content": "列出最近 run 并给出结论。"}]

    tr = BuiltinScriptedTransport(turns)
    rb = BuiltinOpenAIRuntime(transport=tr).submit(
        RuntimeRequest(messages=list(messages), tools=list(tools), max_rounds=max_rounds),
        executor)
    ledger: dict[str, Any] = {"wire_chars": []}
    rp = PydanticAIRuntime(runner=make_pai_scripted_runner(turns, ledger)).submit(
        RuntimeRequest(messages=list(messages), tools=list(tools), max_rounds=max_rounds),
        executor)

    b, p = rb.usage, rp.usage
    # 公平性：两轨执行了同样的工具序列、同样的收尾。token 同源性只在 stop
    # 路径可比——预算路径上离线脚本 runner 不带 usage（adapter 记 0），而
    # builtin 逐轮累计，这是离线仪表的一项真实遥测不对称，如实进报告，不塞
    # 进公平性布尔里掩盖（真机默认 runner 已由 run_sync 改 agent.iter() 回传
    # 现场+usage，live 模式两轨可比）。
    same_tools = b.tool_calls == p.tool_calls
    same_finish = rb.finish_reason == rp.finish_reason
    tokens_comparable = rb.finish_reason == "stop" and rp.finish_reason == "stop"
    same_tokens = (b.prompt_tokens == p.prompt_tokens
                   and b.completion_tokens == p.completion_tokens)
    fair = same_tools and same_finish and (same_tokens or not tokens_comparable)
    builtin_total = sum(tr.wire_chars)
    pai_total = sum(ledger["wire_chars"])
    est_per_nudge = estimate_tokens(tr.nudge_text_sample)
    # 注入开销 = 催办消息 JSON + 列表分隔符（json.dumps 的 ", "，+2 字符/处）
    nudge_overhead = tr.nudge_chars + 2 * tr.nudge_hits
    report: dict[str, Any] = {
        "mode": "offline_structural",
        "max_rounds": max_rounds,
        "scripted_turns": len(turns),
        "est_heuristic": EST_HEURISTIC,
        "runtimes": {
            "builtin": {
                "llm_calls": b.llm_calls, "tool_calls": b.tool_calls,
                "prompt_tokens": b.prompt_tokens,
                "completion_tokens": b.completion_tokens,
                "cached_tokens": b.cached_tokens,
                "wire_chars_total": builtin_total,
                "wire_chars_per_call": list(tr.wire_chars),
                "nudge_hits": tr.nudge_hits,
                "nudge_chars_total": tr.nudge_chars,
                "est_tokens_per_nudge": est_per_nudge,
                "est_tokens_runtime_added_total": est_per_nudge * tr.nudge_hits,
                "finish_reason": rb.finish_reason,
            },
            "pydantic_ai": {
                "llm_calls": p.llm_calls, "tool_calls": p.tool_calls,
                "prompt_tokens": p.prompt_tokens,
                "completion_tokens": p.completion_tokens,
                "cached_tokens": p.cached_tokens,
                "wire_chars_total": pai_total,
                "wire_chars_per_call": list(ledger["wire_chars"]),
                "runtime_injected_chars": 0,
                "est_tokens_runtime_added_total": 0,
                "finish_reason": rp.finish_reason,
            },
        },
        "structural_delta_chars": builtin_total - pai_total,
        "nudge_injection_overhead_chars": nudge_overhead,
        "fairness": {
            "same_tool_calls": same_tools,
            "same_finish_reason": same_finish,
            "tokens_comparable": tokens_comparable,
            "same_tokens": same_tokens,
            "note": ("预算路径：离线脚本 runner 不带 usage（prompt/completion 记 0），"
                     "builtin 逐轮累计——离线仪表的真实遥测不对称，如实记录；真机默认 "
                     "runner 已由 run_sync 改 agent.iter() 事件流回传现场+usage（②）"),
        },
        "lib_overhead": ("unmeasured_offline" if not lib_available()
                         else "not_measured_in_offline_mode"),
        "fair": fair,
    }
    report["decision"] = recommend_default(report)
    return report


# ─── live 真模型 A/B（外网+API key；#139 禁入测试，运行时批次调用）──────────

def _make_hooked_async_client(sink: list[int]) -> Any:
    """带请求钩子的 AsyncClient：记录每次出站 body 字节数。

    优先 httpx2（pydantic-ai 2.x 默认客户端族，传 legacy httpx 会告警），回退 httpx。
    """

    async def on_request(request: Any) -> None:
        sink.append(len(getattr(request, "content", b"") or b""))

    try:
        import httpx2 as hx
    except ImportError:  # 旧 pydantic-ai（1.x）走 legacy httpx
        import httpx as hx
    return hx.AsyncClient(timeout=hx.Timeout(timeout=120, connect=5),
                          event_hooks={"request": [on_request]})


def _trial_record(out: RuntimeResult, wire: list[int], wall_s: float) -> dict[str, Any]:
    u = out.usage
    return {
        "finish_reason": out.finish_reason,
        "llm_calls": u.llm_calls, "tool_calls": u.tool_calls,
        "tools_used": list(out.tools_used),
        "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
        "cached_tokens": u.cached_tokens,
        "total_tokens": u.prompt_tokens + u.completion_tokens,
        "wire_bytes_per_call": list(wire), "wire_bytes_total": sum(wire),
        "wall_s": round(wall_s, 2),
        "text_head": (out.text or "")[:160],
    }


def _mean(trials: list[dict[str, Any]], key: str) -> float:
    vals = [float(t.get(key) or 0) for t in trials if "error" not in t]
    return round(sum(vals) / len(vals), 1) if vals else 0.0


def live_runtime_ab(
        *,
        prompt: str = LIVE_PROMPT,
        repeats: int = 3,
        max_rounds: int = 6,
        tools: list[ToolSpec] | None = None,
        executor: ToolExecutor | None = None,
        system: str | None = None,
        log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """真模型 A/B：同任务交替跑 builtin / pydantic_ai 各 repeats 次，回 mode="live" 报告。

    通道 configs/chat_settings.yaml（base_url/model/api_key，缺任一即报错，不伪造）。
    两轨同源：同一 system 提示（生产 _SYSTEM_PROMPT）、同一 prompt、同一只读工具表
    （默认 LIVE_READONLY_TOOLS，不触发 Gate/沙箱写面）、同一真实工具执行器
    （r3_services._execute_tool，读真实 run 库）、同一 max_rounds、同 temperature
    0.3。pydantic_ai 轨走默认 runner 同款 build_pai_agent+run_pai_agent，仅
    http_client 换成带请求钩子的客户端以抓真实出站字节。单次失败（网络/通道）
    如实记 error，不重试不掩盖。
    """
    from rfauto.service.agent_runtime import default_tool_specs, openai_chat_completion
    from rfauto.service.pydantic_ai_runtime import build_pai_agent, run_pai_agent
    from rfauto.service.r3_services import _SYSTEM_PROMPT, _execute_tool, get_chat_settings_raw

    cfg = get_chat_settings_raw()
    model_name = str(cfg.get("model") or "")
    base_url = str(cfg.get("base_url") or "")
    api_key = cfg.get("api_key")
    if not (model_name and base_url and api_key):
        raise RuntimeError("live A/B 需要 configs/chat_settings.yaml 配好 base_url/model/api_key")
    if tools is None:
        tools = [t for t in default_tool_specs() if t.name in LIVE_READONLY_TOOLS]
    executor = executor or _execute_tool
    system_text = _SYSTEM_PROMPT if system is None else system
    messages = [{"role": "system", "content": system_text},
                {"role": "user", "content": prompt}]
    emit = log or (lambda _m: None)

    def request() -> RuntimeRequest:
        return RuntimeRequest(messages=[dict(m) for m in messages], tools=list(tools),
                              max_rounds=max_rounds)

    def run_builtin() -> dict[str, Any]:
        wire: list[int] = []

        def transport(msgs: list[dict[str, Any]], tool_dicts: list[dict[str, Any]]) -> dict[str, Any]:
            # 与 agent_runtime.openai_chat_completion 同构造的 body（字节数即真实出站）
            body = json.dumps({"model": model_name, "messages": msgs, "tools": tool_dicts,
                               "temperature": 0.3}).encode("utf-8")
            wire.append(len(body))
            return openai_chat_completion(msgs, tool_dicts)

        t0 = time.perf_counter()
        out = BuiltinOpenAIRuntime(transport=transport).submit(request(), executor)
        return _trial_record(out, wire, time.perf_counter() - t0)

    def run_pai() -> dict[str, Any]:
        wire: list[int] = []
        client = _make_hooked_async_client(wire)

        def runner(inp: PaiRunInput) -> PaiRunResult:
            bundle = build_pai_agent(inp, model_name=model_name, base_url=base_url,
                                     api_key=api_key, http_client=client)
            return run_pai_agent(bundle, inp)

        t0 = time.perf_counter()
        out = PydanticAIRuntime(runner=runner).submit(request(), executor)
        return _trial_record(out, wire, time.perf_counter() - t0)

    trials: dict[str, list[dict[str, Any]]] = {"builtin": [], "pydantic_ai": []}
    for i in range(max(1, int(repeats))):
        for name, fn in (("builtin", run_builtin), ("pydantic_ai", run_pai)):  # 交替，抑制时漂
            emit(f"[live A/B] repeat {i + 1}/{repeats} runtime={name} ...")
            try:
                rec = fn()
            except Exception as exc:  # 单次失败如实入档
                rec = {"error": f"{type(exc).__name__}: {exc}", "finish_reason": "error",
                       "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                       "wire_bytes_total": 0}
            trials[name].append(rec)
            emit(f"[live A/B]   -> finish={rec.get('finish_reason')} tokens={rec.get('total_tokens')} "
                 f"tools={rec.get('tools_used')} wire={rec.get('wire_bytes_total')}B "
                 f"wall={rec.get('wall_s')}s{' ERROR ' + rec['error'] if 'error' in rec else ''}")

    def agg(name: str) -> dict[str, Any]:
        ts = trials[name]
        return {
            "trials": ts,
            "errors": sum(1 for t in ts if "error" in t),
            "finish_reasons": [t.get("finish_reason") for t in ts],
            "llm_calls": _mean(ts, "llm_calls"), "tool_calls": _mean(ts, "tool_calls"),
            "prompt_tokens": _mean(ts, "prompt_tokens"),
            "completion_tokens": _mean(ts, "completion_tokens"),
            "cached_tokens": _mean(ts, "cached_tokens"),
            "total_tokens": _mean(ts, "total_tokens"),
            "wire_chars_total": _mean(ts, "wire_bytes_total"),  # recommend_default 兼容键（字节）
            "wall_s": _mean(ts, "wall_s"),
        }

    b, p = agg("builtin"), agg("pydantic_ai")
    no_errors = b["errors"] == 0 and p["errors"] == 0
    all_stop = (all(r == "stop" for r in b["finish_reasons"])
                and all(r == "stop" for r in p["finish_reasons"]))
    tokens_comparable = (all(t.get("prompt_tokens", 0) > 0 for t in trials["builtin"])
                         and all(t.get("prompt_tokens", 0) > 0 for t in trials["pydantic_ai"]))
    from urllib.parse import urlparse

    report: dict[str, Any] = {
        "mode": "live",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model_name,
        "base_url_host": urlparse(base_url).netloc,
        "lib_version": lib_version(),
        "repeats": repeats, "max_rounds": max_rounds, "temperature": 0.3,
        "prompt": prompt, "tools": [t.name for t in tools],
        "runtimes": {"builtin": b, "pydantic_ai": p},
        "fairness": {
            "no_errors": no_errors,
            "all_finish_stop": all_stop,
            "tokens_comparable": tokens_comparable,
            "same_tool_calls_mean": b["tool_calls"] == p["tool_calls"],
            "note": ("真模型逐次响应不完全确定（工具序列可异），公平性只要求两轨零故障、"
                     "全部 stop 收尾、token 同为模型上报；节省按 repeats 均值"),
        },
        "wire_note": WIRE_NOTE,
        "fair": bool(no_errors and all_stop and tokens_comparable),
    }
    report["decision"] = recommend_default(report)
    return report


def recommend_default(report: dict[str, Any]) -> dict[str, Any]:
    """默认裁决：builtin 维持为默认，除非（真模型 A/B + 库可用 + 省 ≥5% + 公平）。

    节省度量：live 且两轨都有模型上报 token → 按总 token（prompt+completion）；
    否则按总线字符（离线结构差）。
    """
    reasons: list[str] = []
    lib_ok = lib_available()
    if not lib_ok:
        reasons.append("pydantic_ai 未安装（venv 实测 ModuleNotFoundError），切默认即断 LLM 通道")
    live = report.get("mode") == "live"
    if not live:
        reasons.append("离线结构 A/B 只度量 runtime 注入的结构性增量，"
                       "不构成真模型 token 效率证据（真机 A/B 未做）")
    b = report.get("runtimes", {}).get("builtin", {})
    p = report.get("runtimes", {}).get("pydantic_ai", {})
    base = max(1, int(b.get("wire_chars_total") or 0))
    saving_wire = (base - int(p.get("wire_chars_total") or 0)) / base
    nudge_clause = ""
    if b.get("nudge_chars_total") is not None:  # 离线结构 A/B 才有催办注入分解
        nudge_clause = (f"；其中 builtin 催办注入 {b.get('nudge_chars_total')} chars ≈ "
                        f"{b.get('est_tokens_runtime_added_total')} est-tokens")
    reasons.append(
        f"结构差：builtin 总线 {b.get('wire_chars_total')} chars vs pydantic_ai "
        f"{p.get('wire_chars_total')} chars（省 {saving_wire:.1%}{nudge_clause}）")
    b_tok = int(b.get("prompt_tokens") or 0) + int(b.get("completion_tokens") or 0)
    p_tok = int(p.get("prompt_tokens") or 0) + int(p.get("completion_tokens") or 0)
    tokens_known = live and b_tok > 0 and p_tok > 0
    saving_tokens = (b_tok - p_tok) / b_tok if b_tok > 0 else 0.0
    if tokens_known:
        reasons.append(
            f"真机 token（模型上报，repeats 均值）：builtin {b_tok} vs pydantic_ai {p_tok}"
            f"（省 {saving_tokens:.1%}；裁决按此计，门槛 {SWITCH_MIN_SAVING_RATIO:.0%}）")
    metric = "total_tokens" if tokens_known else "wire_chars"
    saving = saving_tokens if tokens_known else saving_wire
    if live and not report.get("fair"):
        reasons.append("live 公平性未满足（故障/非 stop 收尾/token 缺失），不切")
    switch = bool(lib_ok and live and saving >= SWITCH_MIN_SAVING_RATIO and report.get("fair"))
    return {"default": "pydantic_ai" if switch else "builtin",
            "switch": switch,
            "metric": metric,
            "saving": round(saving, 4),
            "min_saving_ratio": SWITCH_MIN_SAVING_RATIO,
            "reasons": reasons}
