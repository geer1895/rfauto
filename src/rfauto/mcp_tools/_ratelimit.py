"""MCP 运行期护栏单源（VB-7，aurora_r Wave2 席 R-14，2026-11-10）。

提案源：runs/aurora_q/qx40_vbridge/PROPOSALS.md VB-7（代码级可参考·MIT，
模式极短已按 rfauto 信封/中间件惯例重写，未复制目标仓实质性片段）。
模块名取主件 (b) 限流；两件护栏同居一文件（单文件承载单提案惯例，同
_annotations.py/_resources.py 先例）：

(a) **stdio 信道纯度**（``StdioChannelPurityMiddleware``）：stdio 会话在
    客户端 initialize 时（传输启动后，mcp 1.30.0 ``mcp/server/stdio.py``
    已在 ``stdio_server()`` 进入时以 ``TextIOWrapper(sys.stdout.buffer)``
    自持协议输出流）一次性把 Python 级 ``sys.stdout`` 指向 stderr——
    此后工具执行期任何 ``print``/库打印只落 stderr，协议帧不受影响。
    不用逐调用 ``redirect_stdout``（跨线程不可重入，fastmcp 同步工具经
    线程池执行）；C 级直接写 fd 1（原生库打印）不在覆盖面（PROPOSALS
    边界，fd 级注入列 followUp）。

(b) **逐工具滑窗限流**（``ToolRateLimitMiddleware``，经 FastMCP
    ``on_call_tool`` 中间件钩子）：单源表 ``RATE_LIMITS`` 只列求解/发射类
    工具（候选池=``_annotations.py`` 四类的 LONG_RUNNING 11 个 + MND 24
    个；实选=全部 11 个 LONG_RUNNING，MND 全为本地文件写/进程内计算、
    零求解发射故 0 个入选；GUI 抓取类本 MCP 面 0 个——get_model_3d/
    farfield_view 均离线只读解析，无 GUI 截取工具）。60s 滑窗；只读工具
    不在表内即永不限流；``RFAUTO_MCP_UNLIMITED=1`` 关闭；限流拒绝走
    ``error_envelope`` 并附合并调用提示文案。

接线（mcp_server.main，stdio 会话面）：main() 挂两中间件后
``mcp.run(transport="stdio")``；in-memory 通道（cli/mcp_chat 本地助手）
不挂——护栏面向外部 Agent 会话，缺省进程内消费零行为变化。

数值口径：表内限额/窗口均为调度参数而非物理数值（铁律 7）——它们约束
的是"多久发射一次求解"的 Agent 行为，不参与任何物理计算。
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from rfauto.mcp_tools._annotations import _TOOLS as _ANNOTATIONS
from rfauto.mcp_tools._annotations import LONG_RUNNING, READ_ONLY
from rfauto.service.envelope import error_envelope

# ─── 限流参数（调度参数，非物理数值）────────────────────────────────────────

#: 滑窗宽度（秒）。调度参数：覆盖"Agent 死循环连续发射求解"的典型节律。
RATE_LIMIT_WINDOW_S = 60.0

#: 单点发射档：单点求解/模拟器子进程（占用求解轨但不占战役编排面）。
TIER_LAUNCH = 6

#: 战役发射档：多 trial 战役/优化环（每次发射都是长占用）。
TIER_CAMPAIGN = 3

#: 解除开关（PROPOSALS VB-7 口径）：值 ∈ {1,true,yes,on}（大小写不敏感）。
UNLIMITED_ENV = "RFAUTO_MCP_UNLIMITED"

_UNLIMITED_TRUTHY = frozenset({"1", "true", "yes", "on"})


# ─── (b) 单源限流表 ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _RateEntry:
    """单工具限流条目（limit=滑窗内允许次数；reason=入选理由单行）。"""

    limit: int
    reason: str


#: 求解/发射类单源限流表（60s 滑窗；只读工具零条目=永不限流）。
RATE_LIMITS: dict[str, _RateEntry] = {
    # ── 单点发射档（TIER_LAUNCH=6/60s）──
    "create_run": _RateEntry(
        TIER_LAUNCH, "api.run_once 同步发射单点求解（占求解轨，run 目录+meta 落盘）"
    ),
    "create_run_async": _RateEntry(
        TIER_LAUNCH, "run_once_async 后台线程发射单点求解（同 create_run 异步形态）"
    ),
    "rf_run_sampler": _RateEntry(
        TIER_LAUNCH, "call_kernel_tool('rf_run_sampler') 发射单点采样求解"
    ),
    "netlist_goldset_replay": _RateEntry(
        TIER_LAUNCH, "发射 qucsator 等模拟器子进程（外部求解器轨）"
    ),
    "ads_circuit_run": _RateEntry(
        TIER_LAUNCH, "写工作目录+发射 hpeesofsim 求解（ADS 仿真轨）"
    ),
    # ── 战役发射档（TIER_CAMPAIGN=3/60s）──
    "warm_start_optimize": _RateEntry(
        TIER_CAMPAIGN, "warm-start 优化战役（多 trial 连续发射 adapter 求解）"
    ),
    "multi_agent_run": _RateEntry(
        TIER_CAMPAIGN, "多轮 agent 环（每轮发射求解，环内自身有节律）"
    ),
    "autotune_self_verify": _RateEntry(
        TIER_CAMPAIGN, "粗/细网格自验证环（多轮发射求解）"
    ),
    "start_tune": _RateEntry(
        TIER_CAMPAIGN, "发射 Optuna 调优战役（多 trial 求解长占用）"
    ),
    "run_sweep": _RateEntry(
        TIER_CAMPAIGN, "发射参数扫描战役（批量求解长占用）"
    ),
    "edb_build_solve": _RateEntry(
        TIER_CAMPAIGN, "pyaedt 建 EDB+发射 AEDT 求解（占 HFSS 轨/license）"
    ),
}

#: 限流拒绝的合并调用提示文案（PROPOSALS 验收⑤）。
RATE_LIMIT_HINT = (
    "本次调用被逐工具滑窗限流（保护求解/许可资源，防 Agent 死循环连续发射）。"
    "建议：合并多次调用为一次批量操作（单点求解可合并为 run_sweep 参数扫描、"
    "多战役查询合并到 plan/get_campaign_status），或等待窗口滑出后重试"
    "（retry_after_s 给出预计秒数）。运维解除：设 RFAUTO_MCP_UNLIMITED=1"
    "（自担求解资源风险）。"
)


def unlimited_env_active(environ: Mapping[str, str] | None = None) -> bool:
    """``RFAUTO_MCP_UNLIMITED`` 解除开关是否激活（纯函数，environ 可注入）。"""
    env = os.environ if environ is None else environ
    return env.get(UNLIMITED_ENV, "").strip().lower() in _UNLIMITED_TRUTHY


@dataclass(frozen=True)
class RateLimitDecision:
    """单次工具调用的限流判定（纯数据，注入时钟下可逐位复现）。"""

    tool: str
    allowed: bool
    limit: int | None  # None=不在表内（不限流）
    window_s: float
    count_in_window: int | None  # 判定后窗口内记录数（允许时含本次）
    retry_after_s: float | None  # 仅拒绝时给出（预计滑出秒数）


class SlidingWindowRateLimiter:
    """逐工具 60s 滑窗限流器（纯逻辑，时钟可注入；threading.Lock 防并发）。"""

    def __init__(
        self,
        window_s: float = RATE_LIMIT_WINDOW_S,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._window_s = float(window_s)
        self._clock = clock or time.monotonic
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def acquire(self, tool: str) -> RateLimitDecision:
        """记录/判定一次工具调用（判定即记账——允许的调用入窗）。"""
        entry = RATE_LIMITS.get(tool)
        if entry is None:
            # 不在表内（含全部只读工具）：零记账零限流。
            return RateLimitDecision(
                tool=tool, allowed=True, limit=None,
                window_s=self._window_s, count_in_window=None,
                retry_after_s=None,
            )
        now = self._clock()
        with self._lock:
            dq = self._hits.setdefault(tool, deque())
            cutoff = now - self._window_s
            # 窗口=半开区间 (now-window, now]：age 恰=window 的旧记录滑出。
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) < entry.limit:
                dq.append(now)
                return RateLimitDecision(
                    tool=tool, allowed=True, limit=entry.limit,
                    window_s=self._window_s, count_in_window=len(dq),
                    retry_after_s=None,
                )
            retry_after = max(0.0, self._window_s - (now - dq[0]))
            return RateLimitDecision(
                tool=tool, allowed=False, limit=entry.limit,
                window_s=self._window_s, count_in_window=len(dq),
                retry_after_s=retry_after,
            )


def rate_limit_error_envelope(decision: RateLimitDecision) -> dict[str, Any]:
    """限流拒绝 → error_envelope（信封纪律：只走构造器）。"""
    return error_envelope(
        [
            f"tool '{decision.tool}' 触发滑窗限流："
            f"{decision.limit} 次/{decision.window_s:.0f}s 窗口已满"
        ],
        tool=decision.tool,
        limit=decision.limit,
        window_s=decision.window_s,
        retry_after_s=decision.retry_after_s,
        hint=RATE_LIMIT_HINT,
    )


# ─── (b) FastMCP 中间件 ───────────────────────────────────────────────────


class ToolRateLimitMiddleware(Middleware):
    """``on_call_tool`` 钩子挂滑窗限流（表外工具直通，零额外开销）。"""

    def __init__(self, limiter: SlidingWindowRateLimiter | None = None) -> None:
        self._limiter = limiter or SlidingWindowRateLimiter()

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: Callable[[MiddlewareContext[Any]], Any],
    ) -> Any:
        if unlimited_env_active():
            return await call_next(context)
        name = getattr(context.message, "name", "") or ""
        decision = self._limiter.acquire(name)
        if decision.allowed:
            return await call_next(context)
        payload = rate_limit_error_envelope(decision)
        return ToolResult(
            content=[
                TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))
            ],
            structured_content=payload,
            is_error=True,
        )


# ─── (a) stdio 信道纯度中间件 ─────────────────────────────────────────────


def redirect_python_stdout_to_stderr(stdout: Any, stderr: Any) -> bool:
    """一次性把 Python 级 sys.stdout 指向 stderr（纯函数体，流对可注入）。

    返回是否发生了重定向；None 流/已同流一律 no-op。协议帧不受影响——
    mcp stdio_server 进入时已自持 ``sys.stdout.buffer`` 包装流（源码实证）。
    """
    if stdout is None or stderr is None or stdout is stderr:
        return False
    # flush best-effort（#105：观测面不得成为主路径故障点）
    with contextlib.suppress(OSError, ValueError):
        stdout.flush()
    sys.stdout = stderr
    return True


class StdioChannelPurityMiddleware(Middleware):
    """``on_initialize`` 钩子一次性重定向（传输启动后=首个 initialize 时）。

    时序实证：fastmcp ``run_stdio_async`` 先 ``async with stdio_server()``
    （协议流自持）再 ``_mcp_server.run``——initialize 请求处理发生在
    stdio_server 进入之后，此处重定向不触协议信道。
    """

    def __init__(self) -> None:
        self.redirected = False

    async def on_initialize(
        self,
        context: MiddlewareContext[Any],
        call_next: Callable[[MiddlewareContext[Any]], Any],
    ) -> Any:
        if not self.redirected:
            self.redirected = redirect_python_stdout_to_stderr(
                sys.stdout, sys.stderr
            )
        return await call_next(context)


# ─── 表一致性自证（测试判定面；import 零炸原则同 _annotations.py）──────────


def rate_limit_snapshot() -> dict[str, dict[str, Any]]:
    """限流表快照（tool → {limit, reason, window_s}；键排序）。"""
    return {
        name: {
            "limit": entry.limit,
            "reason": entry.reason,
            "window_s": RATE_LIMIT_WINDOW_S,
        }
        for name, entry in sorted(RATE_LIMITS.items())
    }


def rate_limit_table_problems(
    classification: Mapping[str, str] | None = None,
) -> list[str]:
    """限流表与注解分类表的一致性问题清单（空=一致）。

    判定面（tests/unit/test_mcp_runtime_guardrails.py 消费）：
    - 限流表条目必须在注解分类表中存在（陈旧条目=问题）；
    - read_only 类工具禁止入表（只读工具永不入表）；
    - long_running 类工具必须在表内（棘轮只收不放：未来新发射类工具
      落 LONG_RUNNING 即须同步入限流表）；
    - limit/window 为正数。
    """
    snap = classification if classification is not None else {
        n: e.category.key for n, e in _ANNOTATIONS.items()
    }
    problems: list[str] = []
    for name, entry in RATE_LIMITS.items():
        cat = snap.get(name)
        if cat is None:
            problems.append(f"stale: {name} 不在注解分类表")
        elif cat == READ_ONLY.key:
            problems.append(f"readonly-in-table: {name} 声明只读却入限流表")
        if entry.limit <= 0:
            problems.append(f"non-positive-limit: {name} limit={entry.limit}")
    for name, entry in _ANNOTATIONS.items():
        if entry.category is LONG_RUNNING and name not in RATE_LIMITS:
            problems.append(f"long-running-missing: {name} 未入限流表（棘轮）")
    if RATE_LIMIT_WINDOW_S <= 0:
        problems.append(f"non-positive-window: {RATE_LIMIT_WINDOW_S}")
    return problems
