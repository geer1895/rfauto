"""r3_services.chat —— LLM 对话面（6j AgentChat + system prompt 面 + chat 设置读写 + function-calling 工具映射）。

自 r3_services.py 巨石按职责域拆分（架构批 W7-S1 T2，AU-1 工艺）：代码体自原「6j LLM Conversation」节逐字节搬迁。
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from rfauto.service.chat_settings_io import (  # T1 解环：设置读面叶化，transport 侧改读本叶
    CHAT_SETTINGS_PATH,
    get_chat_settings_raw,
)
from rfauto.service.envelope import error_envelope, ok_envelope

from .fence import list_recipes
from .solvers import list_registered_solvers

# ─── 6j: LLM Conversation ────────────────────────────────────────────────────

class AgentChat:
    """Self-built LLM conversation loop (direct service layer calls).

    6j: No external MCP needed. Each tool call = service function call.
    Supports dual channel: embedded (this class) or MCP client (external).
    """

    def __init__(self, model: str = "default"):
        import time as _time
        import uuid as _uuid

        from rfauto.pipeline.quota_guard import CostLedger

        self.model = model
        self.history: list[dict[str, str]] = []
        self.tool_calls: list[dict[str, Any]] = []
        # 会话级遥测（UI 统计条数据源；UI 进程内累计，重启清零）
        self.stats: dict[str, Any] = {
            "turns": 0, "llm_calls": 0, "llm_elapsed_s": 0.0,
            "tool_calls": 0, "tool_elapsed_s": 0.0,
            "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
        }
        # G14 成本账本：LLM token 记账（RuntimeUsage 经
        # agent_runtime.usage_to_cost_ledger 薄适配喂入；batch=session_id，
        # actor=模型名；rollup 可供 report/quota_guard 既有消费方使用）
        self.cost_ledger: CostLedger = CostLedger()
        # 工具预算耗尽时保留的对话现场（用户说"继续"则原样续跑，不重探索）
        self._pending_messages: list[dict[str, Any]] | None = None
        # AD-2 会话注入 memo（SK-V §2.1-2）：当轮任务词集键 → 已组装
        # extra_system（""=已组装但两段皆空）；同键多轮追问复用，不重复检索
        # 不重复占预算。键口径 knowledge_injection_service.injection_key。
        self._last_injection_key: str | None = None
        self._last_extra_system: str | None = None
        # Pi 式会话存档（schema 版本化 JSON，runs/chat_sessions/）
        self.session_id = "chat_" + _time.strftime("%Y%m%d_%H%M%S") + "_" + _uuid.uuid4().hex[:6]
        self._session_doc: dict[str, Any] | None = None
        # EC-23 结构化追踪（W2-S10 E1）：三级 span 自记 JSONL，懒建于首轮
        # （agent_trace.AgentTracer，落 runs/chat_sessions/<session_id>.
        # trace.jsonl；缺省开、RFAUTO_AGENT_TRACE=off 关；全程 best-effort
        # #105——trace 任何故障不阻塞对话）。_turn_traced 标记 LLM 路径
        # 是否已在 _llm_turn 发过 turn_end（回退/关键词路由路径由 chat()
        # 补发；正常路径一条 turn 恰一条 turn_end——用户中断
        # BaseException 分支不保证，W6-P3-2 口径收窄）。
        self._tracer: Any = None
        self._turn_traced: bool = False
        self._trace_session_opened: bool = False

    def _trace(self) -> Any:
        """会话追踪器懒建（best-effort，建失败返回 None 不阻塞 #105）。"""
        if self._tracer is None:
            try:
                from rfauto.service.agent_trace import AgentTracer
                self._tracer = AgentTracer(self.session_id)
            except Exception:
                return None
        return self._tracer

    def chat(self, message: str) -> dict[str, Any]:
        """Process a user message and return response.

        工具循环在 AgentRuntime（默认 builtin，可经 RuntimeRegistry 换
        pydantic-ai 等实现）；未配置 LLM API 时回退关键词路由。
        """
        self.history.append({"role": "user", "content": message})
        self.stats["turns"] += 1

        # EC-23 trace：session_start（首次）+ turn_start（每轮，含消息长度；
        # best-effort，tracer 故障不影响后续对话 #105）
        turn_no = int(self.stats["turns"])
        self._turn_traced = False
        tracer = None
        try:
            tracer = self._trace()
            if tracer is not None:
                if not getattr(self, "_trace_session_opened", False):
                    tracer.session("session_start", model=self.model)
                    self._trace_session_opened = True
                tracer.turn(turn_no, "turn_start", message_chars=len(message))
        except Exception:
            tracer = None  # trace 装配失败=本轮无追踪，对话照常（#105）

        cfg = get_chat_settings()
        if cfg.get("configured"):
            try:
                if (self._pending_messages
                        and message.strip().lower() in ("继续", "continue", "go", "接着分析")):
                    response = self._llm_turn("", pending= self._pending_messages)
                    self._pending_messages = None
                else:
                    self._pending_messages = None
                    response = self._llm_turn(message)
            except Exception as exc:  # LLM 故障回退关键词路由（#105 原则）
                fallback = self._route_message(message)
                fallback["text"] = f"[LLM 调用失败，已回退指令模式: {exc}]\n" + fallback["text"]
                response = fallback
        else:
            response = self._route_message(message)

        self.history.append({"role": "assistant", "content": response["text"]})
        response["stats"] = dict(self.stats)
        self._persist_session()
        # EC-23 trace：turn_end（LLM 路径已在 _llm_turn 发过——带 LLM 遥测；
        # 回退/关键词路由路径此处补发；正常路径一条 turn 恰一条 turn_end，
        # 用户中断分支不保证——W6-P3-2 口径收窄）
        if tracer is not None and not self._turn_traced:
            with contextlib.suppress(Exception):
                tracer.turn(turn_no, "turn_end", path="fallback",
                            action=str(response.get("action") or ""))
        return response

    def reset(self) -> dict[str, Any]:
        """清空会话（历史/工具记录/续跑现场/统计/成本账本），换新 session_id。"""
        import time as _time
        import uuid as _uuid

        from rfauto.pipeline.quota_guard import CostLedger

        self.history.clear()
        self.tool_calls.clear()
        self._pending_messages = None
        # AD-2 注入 memo 一并清空（新会话不继承上一会话注入缓存）
        self._last_injection_key = None
        self._last_extra_system = None
        self._session_doc = None
        # EC-23 trace：旧会话收尾 span + 追踪器重置（新 session_id 首轮
        # 懒建新 trace 文件，不跨会话串行号）
        try:
            if self._tracer is not None:
                self._tracer.session("session_end", reason="reset")
        except Exception:
            pass
        self._tracer = None
        self._turn_traced = False
        self._trace_session_opened = False
        self.cost_ledger = CostLedger()
        for key in self.stats:
            self.stats[key] = 0 if not isinstance(self.stats[key], float) else 0.0
        self.session_id = ("chat_" + _time.strftime("%Y%m%d_%H%M%S")
                           + "_" + _uuid.uuid4().hex[:6])
        return ok_envelope(session_id=self.session_id)

    def _persist_session(self) -> None:
        """Pi 式会话存档（观测路径 best-effort，不阻塞对话 #105）。"""
        try:
            from rfauto.service.agent_runtime import new_session_doc, persist_session
            if self._session_doc is None:
                self._session_doc = new_session_doc(self.session_id, {"model": self.model})
            self._session_doc["history"] = list(self.history)
            self._session_doc["tool_calls"] = list(self.tool_calls)
            self._session_doc["stats"] = dict(self.stats)
            persist_session(self._session_doc)
        except Exception:
            pass

    def _compose_extra_system(self, task_text: str) -> str | None:
        """AD-2+AD-3 注入组装（extra_system 单通道；缺省关=返回 None 零变化）。

        固定序 few_shot + knowledge（SK-V §2.1-2），共享 2400 chars 单账本：
        few-shot 整块截断 ≤900（clamp_few_shot_section），知识节预算=
        min(section, extra_system−len(few))。空命中两段皆空 → None（与不
        注入档逐字节一致）。会话级 memo 按当轮词集键复用（多轮追问不重复
        检索）。全链 best-effort #105：组装失败返回 None 不阻塞对话。
        """
        try:
            from rfauto.service.knowledge_injection_service import (
                EXTRA_SYSTEM_MAX,
                FEW_SHOT_MAX,
                KNOWLEDGE_INJECTION_SCHEMA,
                SECTION_MAX,
                clamp_few_shot_section,
                compose_knowledge_injection,
                injection_key,
                knowledge_injection_settings,
            )
            settings = knowledge_injection_settings()
            if not settings.get("enabled"):
                return None
        except Exception:  # 开关面故障=零注入，不阻塞对话（#105）
            return None
        key = injection_key(task_text)
        if key == self._last_injection_key:
            return self._last_extra_system or None
        budgets = dict(settings.get("budgets") or {})
        budgets.setdefault("few_shot", FEW_SHOT_MAX)
        budgets.setdefault("extra_system", EXTRA_SYSTEM_MAX)
        budgets.setdefault("section", SECTION_MAX)

        few_raw = ""
        few_dropped = 0
        try:
            from rfauto.service.few_shot_service import build_few_shot_system
            few_raw = str(build_few_shot_system(task_text).get("section") or "")
        except Exception:  # few-shot 源故障不阻塞知识注入（#105）
            few_raw = ""
        few, few_dropped = clamp_few_shot_section(
            few_raw, max_chars=int(budgets["few_shot"]))

        knowledge_usage: dict[str, Any] = {}
        entries: list[dict[str, Any]] = []
        know = ""
        try:
            remaining = int(budgets["extra_system"]) - len(few)
            result = compose_knowledge_injection(
                task_text,
                budgets={**budgets,
                         "section": min(int(budgets["section"]),
                                        max(remaining, 0))})
            if result.get("ok"):
                know = str(result.get("section") or "")
                entries = list(result.get("entries") or [])
                knowledge_usage = dict(result.get("usage") or {})
        except Exception:  # 知识源故障=零知识注入，不阻塞对话（#105）
            know = ""
        extra = few + know if (few or know) else ""
        extra = extra.strip("\n") or ""
        if not extra:
            self._last_injection_key = key
            self._last_extra_system = ""
            return None
        self._record_injections(KNOWLEDGE_INJECTION_SCHEMA, entries,
                                knowledge_usage, len(few), few_dropped)
        self._last_injection_key = key
        self._last_extra_system = extra
        return extra

    def _record_injections(self, schema: str, entries: list[dict[str, Any]],
                           usage: dict[str, Any], few_shot_chars: int,
                           few_shot_dropped: int) -> None:
        """注入留痕进会话档 meta.injections（best-effort，persist 不阻塞 #105）。"""
        try:
            from rfauto.service.agent_runtime import new_session_doc
            if self._session_doc is None:
                self._session_doc = new_session_doc(
                    self.session_id, {"model": self.model})
            meta = self._session_doc.setdefault("meta", {})
            meta["injections"] = {
                "schema": schema,
                "entries": [dict(e) for e in entries],
                "usage": {**usage, "few_shot_chars": int(few_shot_chars),
                          "few_shot_truncated_blocks": int(few_shot_dropped)},
            }
        except Exception:  # 观测留痕失败不阻塞对话主路径（#105）
            pass

    def _llm_turn(self, message: str, pending: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """一轮 LLM 对话：循环策略在 AgentRuntime（默认 builtin，可换实现）。"""
        import time as _time

        from rfauto.service.agent_runtime import (
            RuntimeRegistry,
            RuntimeRequest,
            default_tool_specs,
            usage_to_cost_ledger,
        )

        if pending is not None:
            messages = pending  # 续跑：沿用上次的完整工具现场（含中间结果）
            extra_system = None  # 现场 messages 已含已插入注入条，不重组（Q3）
        else:
            menu = list_recipes().get("recipes", [])
            menu_lines = "\n".join(f"- {r['path']}（{r['model']}）" for r in menu) or "-（无）"
            messages = [{"role": "system",
                         "content": get_system_prompt()
                         + "\n当前可用配方（propose_params 的 recipe 参数请用这些完整路径）：\n" + menu_lines}]
            messages += [{"role": m["role"], "content": m["content"]}
                         for m in self.history[-16:]]
            # AD-2 知识注入 + AD-3 few-shot：extra_system 单通道单账本
            # （SK-V §2.1-2；缺省关=逐字节不变；绝不进 get_system_prompt
            # 本体——AD-1 指纹门）。
            extra_system = self._compose_extra_system(message)
        try:
            raw = get_chat_settings_raw()
            max_rounds = max(4, int(raw.get("max_tool_rounds", 12)))
            runtime_name = str(raw.get("runtime", "builtin"))
            model_name = str(raw.get("model") or runtime_name)
        except Exception:
            max_rounds, runtime_name = 12, "builtin"
            model_name = runtime_name

        def _executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
            t1 = _time.perf_counter()
            try:
                result = _execute_tool(name, args)
            except Exception as exc:  # 工具异常回传给模型自行调整
                result = {"error": str(exc)}
            self.stats["tool_calls"] += 1
            self.stats["tool_elapsed_s"] += _time.perf_counter() - t1
            # EC-23 trace：tool 级 span（tool 名/参数摘要/耗时/ok；ok 口径=
            # 结果无顶层 error 键——异常兜底回传形态，信封内层 ok 不在此判）
            if self._tracer is not None:
                try:
                    from rfauto.service.agent_trace import args_summary
                    self._tracer.tool(
                        int(self.stats["turns"]), name,
                        elapsed_s=_time.perf_counter() - t1,
                        ok="error" not in result,
                        args=args_summary(args))
                except Exception:  # 观测面故障不阻塞工具执行（#105）
                    pass
            # DS-2 留痕：工具结果正文摘要随 tool_calls 落会话档（与运行时
            # 注入消息同渲染单源 agent_runtime.tool_context_content）——
            # "LLM 可见即留痕"的写入侧；比对侧见 _llm_turn 尾部挂点。
            entry: dict[str, Any] = {"action": name, "args": args}
            try:
                from rfauto.service.agent_runtime import tool_context_content
                from rfauto.service.session_audit_service import content_digest

                entry["result_digest"] = content_digest(
                    tool_context_content(result))
            except Exception:  # 留痕摘要属观测面，失败不阻塞工具执行（#105）
                pass
            self.tool_calls.append(entry)
            return result

        request = RuntimeRequest(messages=messages, tools=default_tool_specs(),
                                 max_rounds=max_rounds,
                                 extra_system=extra_system)
        out = RuntimeRegistry.create(runtime_name).submit(request, _executor)
        self.stats["llm_calls"] += out.usage.llm_calls
        self.stats["llm_elapsed_s"] += out.usage.llm_elapsed_s
        self.stats["prompt_tokens"] += out.usage.prompt_tokens
        self.stats["completion_tokens"] += out.usage.completion_tokens
        self.stats["cached_tokens"] += out.usage.cached_tokens
        # EC-23 trace：turn_end（LLM 路径带遥测聚合；先发后置标记，chat()
        # 看到标记即不补发 fallback turn_end——正常路径一条 turn 恰一条
        # turn_end，用户中断 BaseException 分支不保证，W6-P3-2 口径收窄）
        if self._tracer is not None:
            try:
                self._tracer.turn(
                    int(self.stats["turns"]), "turn_end", path="llm",
                    runtime=runtime_name, model=model_name,
                    finish_reason=str(out.finish_reason),
                    llm_calls=int(out.usage.llm_calls),
                    llm_elapsed_s=round(float(out.usage.llm_elapsed_s), 6),
                    prompt_tokens=int(out.usage.prompt_tokens),
                    completion_tokens=int(out.usage.completion_tokens),
                    tools_used=list(out.tools_used))
                self._turn_traced = True
            except Exception:  # 观测面故障不阻塞对话主路径（#105）
                pass
        # G14：RuntimeUsage → CostLedger token 记账（batch=session_id，
        # actor=模型名；薄适配与字段口径见 agent_runtime.usage_to_cost_ledger）
        usage_to_cost_ledger(out.usage, self.cost_ledger,
                             batch=self.session_id, actor=model_name)
        if out.finish_reason == "budget_exhausted":
            self._pending_messages = out.messages  # 保留工具现场，用户说"继续"即无损续跑
        # DS-2 "LLM 可见即留痕"比对挂点（best-effort，告警不阻断 #105）：
        # 本轮上下文的 role=tool 消息逐条对会话留痕（history+tool_calls
        # 摘要集）核可溯性，违例计数进 stats/response 注记，绝不 raise。
        response: dict[str, Any] = {"text": out.text,
                                    "action": out.action or "chat",
                                    "result": out.result,
                                    "tools": out.tools_used}
        audit = self._audit_turn(out.messages)
        if audit is not None:
            self.stats["audit_violates"] = (int(self.stats.get(
                "audit_violates") or 0) + int(audit.violate_count or 0))
            response["session_audit"] = audit.as_dict()
        return response

    def _audit_turn(self, turn_messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        """DS-2 不变量逐轮校验（缺省开、告警不阻断；chat_settings 可关）。

        会话留痕单源 = 本实例内存 trail（history+tool_calls，每轮经
        _persist_session 落 runs/chat_sessions）。校验层任何异常收敛为
        {ok: False, error: …} 回执（session_audit_service.audit_turn_
        best_effort，#105）；``session_audit_invariant: off`` 时返回
        None（不校验、response 无 session_audit 键）。
        """
        try:
            raw = get_chat_settings_raw()
            enabled = str(raw.get("session_audit_invariant", "on")) != "off"
        except Exception:
            enabled = True  # 配置读取故障不静默关不变量（缺省开）
        if not enabled:
            return None
        try:
            from rfauto.service.session_audit_service import audit_turn_best_effort
        except Exception as exc:  # #105：校验层自身故障不阻塞主对话路径
            return error_envelope(f"session_audit 导入失败: {exc}",
                                  source="session_audit")

        trail = {"history": list(self.history),
                 "tool_calls": list(self.tool_calls)}
        return audit_turn_best_effort(turn_messages, trail,
                                      session_id=self.session_id)

    def _route_message(self, message: str) -> dict[str, Any]:
        """Route message to appropriate service function."""
        msg_lower = message.lower().strip()

        if msg_lower.startswith("list solvers") or msg_lower == "solvers":
            # T1 解环：同模块自引用 lazy import 冗余（R1 审计伪影边），改直呼；
            # 全测试树无 setattr(r3_services, "list_registered_solvers") 钉点
            result = list_registered_solvers()
            return {"text": json.dumps(result, indent=2), "action": "list_solvers", "result": result}

        if msg_lower.startswith("list runs") or msg_lower == "runs":
            from rfauto.infra.run_store import list_runs
            runs = list_runs()
            return {"text": f"Found {len(runs)} runs", "action": "list_runs", "result": {"runs": runs}}

        if msg_lower.startswith("validate "):
            recipe_path = message[9:].strip()
            from rfauto.service.agent_actions import validate_recipe
            result = validate_recipe(recipe_path)
            return {"text": json.dumps(result, indent=2), "action": "validate", "result": result}

        if msg_lower.startswith("diagnose "):
            run_id = message[9:].strip()
            from rfauto.service.agent_actions import get_metrics
            result = get_metrics(run_id)
            if result.get("ok"):
                diagnosis = result["data"].get("diagnosis", {})
                return {"text": json.dumps(diagnosis, indent=2), "action": "diagnose", "result": diagnosis}
            return {"text": f"Run not found: {run_id}", "action": "error", "result": result}

        if msg_lower.startswith("propose "):
            parts = message[8:].strip().split(" ", 1)
            recipe_path = parts[0]
            params_str = parts[1] if len(parts) > 1 else "{}"
            try:
                params = json.loads(params_str)
            except json.JSONDecodeError:
                params = {}
            from rfauto.service.agent_actions import agent_propose
            result = agent_propose(recipe_path, params)
            self.tool_calls.append({"action": "propose", "params": params, "result": result})
            return {"text": json.dumps(result, indent=2), "action": "propose", "result": result}

        # Default: help message
        return {
            "text": "Available commands:\n"
                    "  solvers - List registered solvers\n"
                    "  runs - List recent runs\n"
                    "  validate <recipe> - Validate a recipe\n"
                    "  diagnose <run_id> - Diagnose a run\n"
                    "  propose <recipe> [params_json] - Propose parameter changes\n"
                    "  help - Show this message",
            "action": "help",
        }

    def get_history(self) -> list[dict[str, str]]:
        return self.history

    def get_tool_calls(self) -> list[dict[str, Any]]:
        return self.tool_calls


# ─── LLM 对话设置与真实模型接入（OpenAI 兼容 /chat/completions）──────────────

_SYSTEM_PROMPT = (
    "你是 rfauto（HFSS/ADS 射频仿真调优框架）的助手。可用工具：\n"
    "list_solvers() 列出求解器；list_runs(limit) 列出 run；"
    "run_detail(run_id) 查看 run 指标与产物；validate_recipe(path) 校验配方；"
    "diagnose_run(run_id) 给出诊断；propose_params(recipe, params) 生成参数提案"
    "（走三层 Gate，需用户在收件箱批准）。\n"
    "改配方必须走沙箱：edit_recipe_draft(recipe, params) 把修改写入草稿副本"
    "（不触碰真实配方），diff_recipe_draft 查看差异，promote_recipe_draft 提交审批。"
    "你没有直接修改 recipes/ 目录的能力，也不要向用户声称已直接改了配方。\n"
    "工作规范：\n"
    "1. 探索要节制：每次任务最多先调 1-2 次只读工具（如 run_detail 看最新 run），"
    "不要重复调用同一工具，也不要逐个遍历所有 run。\n"
    "2. 用户要『提议/优化参数』时：读一次 run_detail 或 validate_recipe 后，"
    "**立即调用 propose_params**——参数键名用配方 optimization.params 里的参数名"
    "（如 arm_len_mm），数值必须落在其 low/high 范围内，通常给出 2-4 个参数的组合。\n"
    "3. 用户要『直接改配方』时：先 edit_recipe_draft 写草稿并 promote，"
    "向用户说明需在收件箱批准。\n"
    "4. 单轮任务尽量在 6 次工具调用内完成并给出最终答复。\n"
    "5. 回答用中文，简洁，结尾给出下一步建议。")


def get_system_prompt() -> str:
    """Agent 系统提示词的公开访问口（F-4；AD-1 §D-4 起单源=外置文件）。

    读 configs/prompts/system_prompt.md（frontmatter {schema,version,changelog}
    + 正文；写入约定正文末尾恰一个换行符收尾，读取时剥除，正文与内置版
    逐字节可比）。文件缺失/frontmatter 非法 → 回退内置 ``_SYSTEM_PROMPT``
    并 WARN 一次（进程级去重——回退必须可见但不刷屏；#105 观测路径不得
    阻塞对话主路径）。ui/server 等外部消费面不得穿透私有名
    （``r3_services._SYSTEM_PROMPT``），一律走本函数。
    """
    global _prompt_warn_emitted
    doc = _load_prompt_doc()
    if doc.get("ok"):
        return doc["prompt"]
    if not _prompt_warn_emitted:
        _prompt_warn_emitted = True
        try:
            import logging

            logging.getLogger(__name__).warning(
                "系统提示词外置文件不可用（%s），回退内置版：%s",
                doc.get("path"), "; ".join(doc.get("errors") or []))
        except Exception:
            pass
    return _SYSTEM_PROMPT


# AD-1 系统提示词版本化：外置单源（frontmatter {schema,version,changelog}+正文）。
# 锚仓库根（__file__ 推导，cwd 无关——相对 configs/ 读在 cd 后静默落空，#295 同族）。
SYSTEM_PROMPT_SCHEMA = "rfauto.system_prompt/1"
SYSTEM_PROMPT_PATH = (Path(__file__).resolve().parent.parent.parent.parent.parent
                      / "configs" / "prompts" / "system_prompt.md")
_prompt_warn_emitted = False


def _load_prompt_doc() -> dict[str, Any]:
    """读取并解析外置系统提示词（内部：任何失败返回 ok=False+errors，不抛）。

    解析口径：须以 ``---\\n`` 起，第一个 ``\\n---\\n`` 收 frontmatter（yaml）；
    其后为正文，末尾恰一个换行符是写入约定、读取时剥除。
    """
    import yaml

    path = str(SYSTEM_PROMPT_PATH)
    try:
        raw = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "source": "builtin", "path": path,
                "errors": [f"读取失败: {exc}"]}
    try:
        if not raw.startswith("---\n"):
            raise ValueError("缺 frontmatter 开头（须以 '---' 行起）")
        close = raw.find("\n---\n", 4)
        if close < 0:
            raise ValueError("缺 frontmatter 收尾（'---' 行）")
        front = yaml.safe_load(raw[4:close]) or {}
        if not isinstance(front, dict):
            raise ValueError("frontmatter 必须是映射")
        schema = str(front.get("schema") or "")
        if schema != SYSTEM_PROMPT_SCHEMA:
            raise ValueError(
                f"schema 不识别: {schema!r}（期望 {SYSTEM_PROMPT_SCHEMA!r}）")
        body = raw[close + 5:]
        if body.endswith("\n"):
            body = body[:-1]  # 写入约定：正文末尾恰一个收尾换行
        if not body.strip():
            raise ValueError("提示词正文为空")
    except Exception as exc:
        return {"ok": False, "source": "builtin", "path": path,
                "errors": [f"{type(exc).__name__}: {exc}"]}
    return ok_envelope(
        source="file",
        path=path,
        errors=[],
        prompt=body,
        schema=schema,
        version=front.get("version"),
        changelog=str(front.get("changelog") or ""),
    )


def get_system_prompt_meta() -> dict[str, Any]:
    """系统提示词元数据与指纹（AD-1）：实际生效正文的 sha256 + 版本溯源。

    返回 {ok, source: "file"|"builtin", path, schema, version, changelog,
    sha256, errors}——source="builtin" 即已回退（errors 说明原因）；
    sha256 对**实际生效正文**计算（file/builtin 同文则同指纹，prompt 回归门
    可据此判"两版无差"）。
    """
    import hashlib

    doc = _load_prompt_doc()
    text = doc["prompt"] if doc.get("ok") else _SYSTEM_PROMPT
    return {"ok": bool(doc.get("ok")), "source": doc.get("source"),
            "path": doc.get("path"), "schema": doc.get("schema"),
            "version": doc.get("version"), "changelog": doc.get("changelog"),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "errors": list(doc.get("errors") or [])}


def get_chat_settings() -> dict[str, Any]:
    """读取 LLM 对话设置；api_key 不回传明文。"""
    import yaml

    if not CHAT_SETTINGS_PATH.exists():
        return ok_envelope(configured=False, base_url="", model="", runtime="builtin", api_key_set=False)
    data = yaml.safe_load(CHAT_SETTINGS_PATH.read_text(encoding="utf-8")) or {}
    return ok_envelope(
        configured=bool(data.get("api_key")),
        base_url=data.get("base_url", ""),
        model=data.get("model", ""),
        runtime=data.get("runtime", "builtin"),
        api_key_set=bool(data.get("api_key")),
    )


def save_chat_settings(base_url: str, model: str, api_key: str = "") -> dict[str, Any]:
    """保存 LLM 对话设置（api_key 落本地 configs/，空串=不修改已存 key）。"""
    import yaml

    data = {}
    if CHAT_SETTINGS_PATH.exists():
        data = yaml.safe_load(CHAT_SETTINGS_PATH.read_text(encoding="utf-8")) or {}
    if base_url:
        data["base_url"] = base_url
    if model:
        data["model"] = model
    if api_key:
        data["api_key"] = api_key
    CHAT_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHAT_SETTINGS_PATH.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ok_envelope(base_url=data.get("base_url", ""), model=data.get("model", ""), api_key_set=bool(data.get("api_key")))


def _llm_chat_completion(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """兼容别名：传输层已移至 agent_runtime.openai_chat_completion。"""
    from rfauto.service.agent_runtime import default_tool_specs, openai_chat_completion
    return openai_chat_completion(messages, [t.to_schema() for t in default_tool_specs()])


def _execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """工具名 → service 函数（LLM function-calling 专用映射）。"""
    if name == "list_solvers":
        return list_registered_solvers()
    if name == "list_runs":
        from rfauto.infra.run_store import list_runs
        return {"runs": list_runs()}
    if name == "run_detail":
        from rfauto.service.agent_actions import get_metrics
        return get_metrics(args["run_id"])
    if name == "validate_recipe":
        from rfauto.service.agent_actions import validate_recipe
        return validate_recipe(args["path"])
    if name == "diagnose_run":
        from rfauto.service.agent_actions import get_metrics
        r = get_metrics(args["run_id"])
        return r.get("data", {}).get("diagnosis", r)
    if name == "propose_params":
        from rfauto.service.agent_actions import agent_propose
        return agent_propose(_resolve_recipe(args["recipe"]), args.get("params", {}))
    if name in ("edit_recipe_draft", "diff_recipe_draft", "promote_recipe_draft"):
        # 沙箱写面：只动 runs/recipe_sandbox/ 草稿，生效必须走 Gate（agent_sandbox）
        from rfauto.service.agent_sandbox import RecipeSandbox
        recipe = _resolve_recipe(args["recipe"])
        sandbox = RecipeSandbox()
        if name == "edit_recipe_draft":
            return sandbox.apply_param_edits(recipe, args.get("params") or {})
        if name == "diff_recipe_draft":
            return sandbox.diff(recipe)
        return sandbox.promote(recipe)
    return {"error": f"unknown tool {name}"}


def _resolve_recipe(recipe: str) -> str:
    """配方路径模糊解析：LLM 常传裸短名（"wilkinson"），按 recipes/ 目录
    匹配唯一/首个命中（路径或模型名包含即算）；无命中保持原样让下游报错。"""
    p_ = Path(recipe)
    if p_.exists():
        return str(p_)
    recipes = list_recipes().get("recipes", [])
    needle = recipe.lower().removesuffix(".yaml")
    hits = [r["path"] for r in recipes
            if needle in r["path"].lower() or needle in r.get("model", "").lower()]
    return hits[0] if hits else recipe
