"""DS-1 工具执行瀑布类型/驱动器叶（T1 终章解环；架构批 W1-S1）。

从 agent_safety 叶化：五段瀑布的**纯类型面与驱动器**——裁决/结果常量
（GUARD_*/OUTCOME_*/POST_*）、事件总线 ToolEvent、GuardVerdict/PostAction、
组件基类 WaterfallComponent 与四段 ABC（PreExecutePolicy/ToolGuard/
ApprovalHandler/PostExecuteHook）、DenyByDefaultApproval 缺省审批器
（含 _DENY_BY_DEFAULT_APPROVAL 模块级单例）、ToolWaterfall 驱动器与
_as_post_actions 归一 helper。本叶只依赖 envelope 与 stdlib，被
agent_runtime（RuntimeRequest.waterfall / RuntimeResult.tool_events 的
TYPE_CHECKING 类型边）与 agent_safety（装配面）消费。叶化后 agent_runtime
的 TYPE_CHECKING import 改读本叶，静态图上不再出现 agent_runtime→
agent_safety 边（agent_runtime→agent_safety→systemone→agent_runtime
三角环第一条边断；第二条 systemone→agent_runtime 边由 llm_transport 叶
断——R1 架构深审 v3 §2.2 S1，内部证据目录）。

留驻 agent_safety 的面（本叶不感知）：三段注册表（_WaterfallRegistry/
GuardRegistry/PrePolicyRegistry/PostHookRegistry）、具体组件
（SandboxWhitelistGuard/PromptInjectionGuard）、SystemOnePrescreenPolicy
（systemone 预筛口：lazy ``ask_systemone`` 是 systemone 方向单向边、
不构成环，按 R1 裁决原形态保留）与安全三件套/注入防线本体。

消费面与测试缝保真声明：
- agent_safety 顶层同名再导出本叶全部名（``X as X``），既有
  ``from rfauto.service.agent_safety import ToolEvent/ToolWaterfall/...``
  消费路径零改动（test_w5_b_waterfall/test_registry_kit/test_agent_safety
  等全数走再导出面；类对象同一，isinstance/子类化语义零变化）；
- 全测试树无 setattr/monkeypatch 替换本叶符号的站点（grep 实证：瀑布
  相关 patch 只钉 systemone_service.ask_systemone 模块属性，与本叶无
  关）；_DENY_BY_DEFAULT_APPROVAL 随 ToolWaterfall 同叶，``_stage_approval``
  经叶内全局解析，语义不变；
- 定义体逐字节搬迁（仅本 docstring 与节注新写），不 change 任何行为。

五段事件级瀑布（宏图 v3.2 §十 DS-1；借鉴 deepseek-harness 模式，只采模式
不锁框架）：
  1. pre-execute：策略注记（分类/置审批位）+ System One 预筛口（可选，
     缺省关零行为变化——与 W1-G systemone_service 的 provider 缺省契约同款）；
  2. guards：deny/abstain 裁决（首个非 allow 短路；注册序 FIFO）；
  3. approval：一次性询问（一次性=只问一次不重问）；无交互环境=deny-by-
     default 可配置（不真阻塞测试）；
  4. execute：around 建议——超时/重试/指标（缺省全关=直执行）；
  5. post-execute：block/replace/addContext；addContext 进
     additionalContexts FIFO（钩子注册序即追加序，顺序钉在单测）。
工程护栏：#105（瀑布任何段故障只降级记 stage_errors/metrics，不阻塞工具
主路径）；铁律 7（System One 预筛输出只作注记/路由元数据，不产生物理
数字）；#139（预筛测试全 mock 钉通道）；规则 3（组件基类+注册表）。
缺省装配=空瀑布，与既有直执行路径行为等价（缺省路径零变化）。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Any

from rfauto.service.envelope import error_envelope, skipped_envelope

GUARD_ALLOW = "allow"
GUARD_DENY = "deny"
GUARD_ABSTAIN = "abstain"
OUTCOME_OK = "ok"
OUTCOME_ERROR = "error"
OUTCOME_TIMEOUT = "timeout"
POST_BLOCK = "block"
POST_REPLACE = "replace"
POST_ADD_CONTEXT = "add_context"


@dataclass
class ToolEvent:
    """一次工具调用的瀑布现场（事件级：跨段传递、逐段留痕、可回放）。

    事件是五段瀑布的唯一总线：pre-execute 段写 ``pre`` 注记；guards 段写
    ``decision*``；approval 段写 ``approval``；execute 段写 ``result``/
    ``error``/``metrics``；post-execute 段写 ``blocked*`` 与
    ``additional_contexts``。任何一段的降级留痕进 ``stage_errors``
    （#105：段故障不阻塞工具主路径）。
    """

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    seq: int = 0                        # 瀑布实例内单调序号（FIFO 审计）
    pre: dict[str, Any] = field(default_factory=dict)
    decision: str = GUARD_ALLOW         # guards 段裁决（allow|deny|abstain）
    decision_by: str = ""               # 裁决来源守卫名
    decision_reason: str = ""
    requires_approval: bool = False     # 策略/守卫可置位 → 走 approval 段
    approval: str | None = None         # granted | denied | denied_default
    result: dict[str, Any] | None = None
    error: str | None = None
    blocked: bool = False               # post-execute block（结果被拦截替换）
    blocked_reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    additional_contexts: list[dict[str, Any]] = field(default_factory=list)
    stage_errors: list[str] = field(default_factory=list)

    def final_result(self) -> dict[str, Any]:
        """喂给模型的最终工具结果（未执行面=skip/错误信封，执行面=原结果）。

        判定序：deny → abstain → approval 未过 → post-block → 原结果 →
        执行错误。deny/abstain/block 走信封构造器（AU-2：新代码禁止裸
        dict 信封）；abstain/approval-denied 是"执行链成立但本项未产出
        结果"= skipped 语义而非失败。执行错误面（``{"error": ...}``）是
        有意的同形复用：与既有循环的工具异常回传约定同形（waterfall 开关
        两侧模型看到的错误形态一致），属工具消息面历史约定、非信封面。
        """
        if self.decision == GUARD_DENY:
            return error_envelope(
                [f"工具调用被守卫拒绝：{self.decision_reason or '未给原因'}"],
                stage="guard", guard=self.decision_by, decision=GUARD_DENY)
        if self.decision == GUARD_ABSTAIN:
            return skipped_envelope(
                self.decision_reason or "守卫建议本轮弃权",
                stage="guard", decision=GUARD_ABSTAIN,
                hint="该工具本轮弃权：请基于已有信息继续作答或向用户澄清")
        if self.approval in ("denied", "denied_default"):
            return skipped_envelope(
                "工具调用需要用户批准，本次一次性询问未通过",
                stage="approval", approval=self.approval,
                hint="不要重复发起同一调用；如确需执行请告知用户走人工批准")
        if self.blocked:
            return error_envelope(
                [f"工具结果被后置检查拦截：{self.blocked_reason or '未给原因'}"],
                stage="post_execute", blocked=True)
        if self.result is not None:
            return self.result
        if self.error is not None:
            return {"error": self.error}
        return error_envelope(["工具调用未产出结果"], stage="waterfall")


@dataclass
class GuardVerdict:
    """guards 段单守卫裁决：allow（继续）/ deny（拒绝执行）/ abstain（弃权）。

    ``requires_approval`` 只在 allow 时生效（守卫可把调用路由进 approval
    段）；deny/abstain 时该位无意义（调用已终止于 guards 段）。
    """

    decision: str = GUARD_ALLOW
    reason: str = ""
    requires_approval: bool = False


@dataclass
class PostAction:
    """post-execute 段单动作：block（拦截结果）/ replace（换载荷）/
    add_context（追加附加上下文，入 additionalContexts FIFO）。"""

    kind: str
    reason: str = ""
    payload: dict[str, Any] | None = None


class WaterfallComponent:
    """瀑布组件基类：name + ``tools`` 作用域白名单（"*"=全工具）。

    跨工具族不耦合：组件互不感知、按注册序独立 FIFO 生效；作用域只靠
    ``tools`` 声明，新增工具族=注册新组件、不改既有组件（注册表模式）。
    """

    name: str = "base"
    tools: tuple[str, ...] = ("*",)

    def applies(self, event: ToolEvent) -> bool:
        return "*" in self.tools or event.name in self.tools


class PreExecutePolicy(WaterfallComponent, ABC):
    """pre-execute 段策略：只注记/置审批位，不裁决（裁决归 guards 段）。"""

    @abstractmethod
    def on_pre_execute(self, event: ToolEvent) -> None:
        """注记进 event.pre / 置 event.requires_approval；禁止抛出意图外异常。"""


class ToolGuard(WaterfallComponent, ABC):
    """guards 段守卫：对事件给 allow/deny/abstain 裁决。"""

    @abstractmethod
    def check(self, event: ToolEvent) -> GuardVerdict:
        """纯裁决面：只读事件、返回裁决（不执行工具、不改事件）。"""


class ApprovalHandler(ABC):
    """approval 段一次性询问处理器（一次性=只问一次，无重问循环）。"""

    name: str = "base"

    @abstractmethod
    def request_approval(self, event: ToolEvent, reason: str) -> bool:
        """返回 True=批准执行；False=拒绝（事件记 approval 留痕）。"""


class DenyByDefaultApproval(ApprovalHandler):
    """缺省审批器：无交互环境（测试/无人值守）恒拒绝——deny-by-default。

    可配置替换：交互面（UI/CLI）传入真审批器即可启用人工批准；
    缺省装配下审批段被 DenyByDefaultApproval 拒绝，测试不被阻塞。
    """

    name = "deny_by_default"

    def request_approval(self, event: ToolEvent, reason: str) -> bool:
        return False


#: 模块级缺省审批器（无状态单例；approval_handler=None 时启用）
_DENY_BY_DEFAULT_APPROVAL = DenyByDefaultApproval()


class PostExecuteHook(WaterfallComponent, ABC):
    """post-execute 段钩子：对执行结果给 block/replace/addContext 动作。"""

    @abstractmethod
    def after_execute(
        self, event: ToolEvent,
    ) -> PostAction | list[PostAction] | None:
        """返回单动作/动作列表（FIFO 序）/None（不干预）。"""


class ToolWaterfall:
    """DS-1 五段工具执行瀑布驱动器（pre→guards→approval→execute→post）。

    缺省装配=空瀑布（无策略/守卫/钩子、无审批位、无超时、单次执行），
    与既有直执行路径行为等价（缺省路径零变化）。组件经注册表按名装配
    （GuardRegistry/PrePolicyRegistry/PostHookRegistry），跨工具族不耦合：
    互不感知、按注册序 FIFO 生效、作用域 ``tools`` 白名单声明。

    段故障降级（#105）：策略/守卫异常→跳过该组件并记 stage_errors（守卫
    fail-open，不阻塞工具主路径）；审批面异常→按拒处理（审批不 fail-open）；
    钩子异常→跳过该钩子记留痕。``run`` 只经 ToolEvent 回传结果，永不向
    调用方抛业务异常。
    """

    def __init__(self,
                 guards: tuple[Any, ...] | list[Any] = (),
                 pre_policies: tuple[Any, ...] | list[Any] = (),
                 post_hooks: tuple[Any, ...] | list[Any] = (),
                 approval_handler: ApprovalHandler | None = None,
                 approval_tools: tuple[str, ...] = (),
                 timeout_s: float | None = None,
                 max_attempts: int = 1,
                 retry_backoff_s: float = 0.0):
        self.guards = list(guards)
        self.pre_policies = list(pre_policies)
        self.post_hooks = list(post_hooks)
        self.approval_handler = approval_handler  # None → DenyByDefaultApproval
        self.approval_tools = tuple(approval_tools)
        self.timeout_s = timeout_s
        self.max_attempts = max(1, int(max_attempts))
        self.retry_backoff_s = max(0.0, float(retry_backoff_s))
        self._seq = 0

    # ── 主入口 ────────────────────────────────────────────────────────────
    def run(self, name: str, args: dict[str, Any] | None,
            executor: Any) -> ToolEvent:
        """执行一次五段瀑布，返回事件现场（结果取 ``event.final_result()``）。"""
        self._seq += 1
        event = ToolEvent(name=str(name), args=dict(args or {}), seq=self._seq)
        self._stage_pre(event)
        verdict = self._stage_guards(event)
        if verdict.decision != GUARD_ALLOW:
            return event
        needs_approval = (event.requires_approval
                          or event.name in self.approval_tools)
        if needs_approval and not self._stage_approval(event):
            return event
        self._stage_execute(event, executor)
        self._stage_post(event)
        return event

    # ── 段 1：pre-execute（策略注记） ─────────────────────────────────────
    def _stage_pre(self, event: ToolEvent) -> None:
        for policy in self.pre_policies:
            if not policy.applies(event):
                continue
            try:
                policy.on_pre_execute(event)
            except Exception as exc:  # #105：策略故障降级留痕，不阻塞
                event.stage_errors.append(f"pre:{policy.name}:{exc}")

    # ── 段 2：guards（deny/abstain 裁决，首个非 allow 短路） ──────────────
    def _stage_guards(self, event: ToolEvent) -> GuardVerdict:
        for guard in self.guards:
            if not guard.applies(event):
                continue
            try:
                verdict = guard.check(event)
            except Exception as exc:
                # 守卫故障语义按类型分流（审查 P2-1，2026-10-05）：拒绝型
                # 防线（Guard 子类）崩溃=防线失效当次静默放行不可接受 →
                # fail-closed（deny + 留痕，可经组件属性 fail_open=True 显式
                # 降级为观测型）；观测型组件维持 fail-open（#105 观测面
                # 不阻塞主路径的红线只约束观测，不约束防线）。
                fail_open = bool(getattr(guard, "fail_open", False))
                event.stage_errors.append(
                    f"guard:{guard.name}:{'fail-open' if fail_open else 'fail-closed'}:{exc}")
                if not fail_open:
                    event.decision = GUARD_DENY
                    event.decision_by = guard.name
                    event.decision_reason = (
                        f"guard {guard.name} 崩溃（fail-closed 缺省）：{exc}")
                    event.metrics["decision"] = GUARD_DENY
                    return GuardVerdict(decision=GUARD_DENY,
                                        reason=event.decision_reason)
                continue
            if verdict.requires_approval:
                event.requires_approval = True
            if verdict.decision in (GUARD_DENY, GUARD_ABSTAIN):
                event.decision = verdict.decision
                event.decision_by = guard.name
                event.decision_reason = verdict.reason
                event.metrics["decision"] = verdict.decision
                return verdict
        return GuardVerdict()

    # ── 段 3：approval（一次性询问；无交互=deny-by-default 可配置） ───────
    def _stage_approval(self, event: ToolEvent) -> bool:
        handler = self.approval_handler or _DENY_BY_DEFAULT_APPROVAL
        reason = event.decision_reason or "策略/守卫要求人工批准本次工具调用"
        try:
            granted = bool(handler.request_approval(event, reason))
        except Exception as exc:  # 审批面故障按拒处理（审批不 fail-open）
            event.stage_errors.append(f"approval:{handler.name}:{exc}")
            granted = False
        if granted:
            event.approval = "granted"
        else:
            event.approval = ("denied_default"
                              if isinstance(handler, DenyByDefaultApproval)
                              else "denied")
        event.metrics["approval"] = event.approval
        return granted

    # ── 段 4：execute（around：超时/重试/指标） ───────────────────────────
    def _stage_execute(self, event: ToolEvent, executor: Any) -> None:
        t0 = time.perf_counter()
        attempts = 0
        last_error: str | None = None
        timed_out = False
        while attempts < self.max_attempts:
            attempts += 1
            try:
                if self.timeout_s is not None:
                    event.result = self._call_with_timeout(
                        executor, event.name, event.args, float(self.timeout_s))
                else:
                    event.result = executor(event.name, event.args)
                last_error = None
                break
            except FuturesTimeoutError:  # 超时不重试：挂起调用重试大概率再挂
                # py3.11+ 起 concurrent.futures.TimeoutError 与内建 TimeoutError
                # 同类：工具自身抛的超时（如 socket timeout）也归入此支——
                # 分类为 timeout（不重试）是保守侧，误差可接受且 metrics 留痕。
                timed_out = True
                last_error = f"工具执行超时（>{self.timeout_s:g}s）"
                break
            except Exception as exc:
                last_error = str(exc)
                if attempts < self.max_attempts and self.retry_backoff_s > 0:
                    time.sleep(self.retry_backoff_s)
        event.metrics.update({
            "attempts": attempts,
            "retries": max(0, attempts - 1),
            "timed_out": timed_out,
            "outcome": (OUTCOME_TIMEOUT if timed_out
                        else (OUTCOME_OK if last_error is None else OUTCOME_ERROR)),
            "elapsed_s": time.perf_counter() - t0,
        })
        if last_error is not None:
            event.error = last_error
            event.result = None

    @staticmethod
    def _call_with_timeout(executor: Any, name: str, args: dict[str, Any],
                           timeout_s: float) -> dict[str, Any]:
        """带超时的单次调用（工作线程跑工具；超时后调用方先走、线程不杀）。"""
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rfauto-tool-wf")
        try:
            future = pool.submit(executor, name, args)
            return future.result(timeout=timeout_s)
        finally:
            pool.shutdown(wait=False)  # 不等挂起线程（杀不掉，交由其自然结束）

    # ── 段 5：post-execute（block/replace/addContext；注册序 FIFO） ───────
    def _stage_post(self, event: ToolEvent) -> None:
        for hook in self.post_hooks:
            if event.blocked or not hook.applies(event):
                continue  # block 短路后续钩子（结果已拦截，无需再判）
            try:
                actions = hook.after_execute(event)
            except Exception as exc:  # #105：钩子故障降级留痕，不阻塞
                event.stage_errors.append(f"post:{hook.name}:{exc}")
                continue
            for action in _as_post_actions(actions):
                if action.kind == POST_BLOCK:
                    event.blocked = True
                    event.blocked_reason = action.reason
                    break
                if action.kind == POST_REPLACE:
                    if isinstance(action.payload, dict):
                        event.result = action.payload  # 后续钩子看到的是新载荷
                    else:
                        event.stage_errors.append(
                            f"post:{hook.name}:replace 载荷非 dict")
                elif action.kind == POST_ADD_CONTEXT:
                    if isinstance(action.payload, dict):
                        # FIFO：钩子注册序即追加序（顺序钉在单测）
                        event.additional_contexts.append(action.payload)
                    else:
                        event.stage_errors.append(
                            f"post:{hook.name}:add_context 载荷非 dict")
                else:
                    event.stage_errors.append(f"post:{hook.name}:未知动作 {action.kind}")


def _as_post_actions(actions: PostAction | list[PostAction] | None) -> list[PostAction]:
    """钩子返回值归一为动作列表（None/单动作/列表；保持返回序=FIFO 序）。"""
    if actions is None:
        return []
    if isinstance(actions, PostAction):
        return [actions]
    return list(actions)
