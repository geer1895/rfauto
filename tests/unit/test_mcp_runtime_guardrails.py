"""VB-7 MCP 运行期护栏测试（aurora_r Wave2 席 R-14，2026-11-10）。

验收（runs/aurora_q/qx40_vbridge/PROPOSALS.md VB-7）：
① 子进程钉：stdio 会话中调用一个故意 print 的测试工具，stdout 每行仍可
   json.loads，print 内容出现在 stderr；
② 限流纯函数钉（注入时钟，窗口/上限边界：第 N 次过/第 N+1 拒/窗口滑出
   恢复）；
③ 只读工具永不被限（表断言 + 与 _annotations 四类一致性）；
④ 测试清空 ``RFAUTO_MCP_`` 前缀环境变量全集（#139 家法）；
⑤ 限流错误走 error_envelope 并提示合并调用。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import types
from pathlib import Path
from typing import Any

import pytest

from rfauto.mcp_tools._ratelimit import (
    RATE_LIMIT_HINT,
    RATE_LIMIT_WINDOW_S,
    RATE_LIMITS,
    TIER_CAMPAIGN,
    TIER_LAUNCH,
    UNLIMITED_ENV,
    RateLimitDecision,
    SlidingWindowRateLimiter,
    StdioChannelPurityMiddleware,
    ToolRateLimitMiddleware,
    rate_limit_error_envelope,
    rate_limit_snapshot,
    rate_limit_table_problems,
    redirect_python_stdout_to_stderr,
    unlimited_env_active,
)


@pytest.fixture(autouse=True)
def _clear_rfauto_mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """#139 家法：清空 ``RFAUTO_MCP_`` 前缀环境变量全集（不止解除开关）。"""
    for key in list(os.environ):
        if key.startswith("RFAUTO_MCP_"):
            monkeypatch.delenv(key, raising=False)


class _FakeClock:
    """可拨动的注入时钟（纯函数钉：同一轨迹逐位复现）。"""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


# ─── ③ 表一致性 + 只读工具永不被限 ────────────────────────────────────────


class TestRateLimitTable:
    def test_table_consistent_with_annotations(self) -> None:
        """限流表与 _annotations 四类一致性（stale/只读入表/棘轮缺登/正数）。"""
        assert rate_limit_table_problems() == []

    def test_readonly_tools_never_in_table(self) -> None:
        """只读工具零条目=永不限流（逐名断言，验收③表断言）。"""
        from rfauto.mcp_tools._annotations import readonly_tool_names

        readonly = readonly_tool_names()
        assert readonly, "注解表只读集合为空=分类表损坏"
        overlap = sorted(set(readonly) & set(RATE_LIMITS))
        assert overlap == []

    def test_readonly_tool_acquires_are_always_allowed(self) -> None:
        """抽样只读工具连打 1000 次全放行且零记账（limit=None）。"""
        from rfauto.mcp_tools._annotations import readonly_tool_names

        clock = _FakeClock()
        limiter = SlidingWindowRateLimiter(clock=clock)
        sample = readonly_tool_names()[:3]
        for name in sample:
            for _ in range(1000):
                decision = limiter.acquire(name)
                assert decision.allowed is True
                assert decision.limit is None
                assert decision.count_in_window is None

    def test_table_shape_and_window(self) -> None:
        """表内容形态：限额∈两档、窗口=60s、每条带入选理由。"""
        snap = rate_limit_snapshot()
        assert set(snap) == set(RATE_LIMITS)
        assert RATE_LIMIT_WINDOW_S == 60.0
        for name, item in snap.items():
            assert item["limit"] in (TIER_LAUNCH, TIER_CAMPAIGN)
            assert item["window_s"] == RATE_LIMIT_WINDOW_S
            assert item["reason"], f"{name} 缺入选理由"
        # 求解/发射类 11 工具全数在表（long_running 全覆盖由一致性棘轮背书）
        assert "create_run" in snap and "start_tune" in snap and "run_sweep" in snap


# ─── ② 滑窗纯函数钉（注入时钟，窗口/上限边界）────────────────────────────


class TestSlidingWindowPure:
    def _limiter(self, clock: _FakeClock) -> SlidingWindowRateLimiter:
        return SlidingWindowRateLimiter(window_s=RATE_LIMIT_WINDOW_S, clock=clock)

    def test_nth_allowed_then_nth_plus_one_rejected(self) -> None:
        """上限边界：start_tune 档=3——第 3 次过、第 4 次拒（附 retry_after）。"""
        clock = _FakeClock()
        limiter = self._limiter(clock)
        for i in range(1, TIER_CAMPAIGN + 1):
            decision = limiter.acquire("start_tune")
            assert decision.allowed is True, i
            assert decision.limit == TIER_CAMPAIGN
            assert decision.count_in_window == i
        rejected = limiter.acquire("start_tune")
        assert rejected.allowed is False
        assert rejected.count_in_window == TIER_CAMPAIGN
        assert rejected.retry_after_s is not None and rejected.retry_after_s > 0

    def test_window_slide_recovers(self) -> None:
        """窗口滑出恢复：填满→拒→推时钟 60s（最老记录滑出）→再放行。"""
        clock = _FakeClock()
        limiter = self._limiter(clock)
        for _ in range(TIER_CAMPAIGN):
            limiter.acquire("run_sweep")
            clock.advance(1.0)
        assert limiter.acquire("run_sweep").allowed is False
        # t=3 拒绝后推进到 t=60：cutoff=0，t=0 记录（age=60）滑出半开窗
        clock.advance(RATE_LIMIT_WINDOW_S - 3.0)
        recovered = limiter.acquire("run_sweep")
        assert recovered.allowed is True
        assert recovered.count_in_window == TIER_CAMPAIGN

    def test_boundary_age_exactly_window_is_evicted(self) -> None:
        """半开窗边界钉：age 恰=window 的记录已滑出（<=cutoff 逐出）。

        start_tune（战役档 3/60s）t=0 连打三次填满；t=59.999 仍拒
        （retry_after=0.001）；t=60.0（age 恰=60）三条全滑出→再放行。
        """
        clock = _FakeClock()
        limiter = SlidingWindowRateLimiter(window_s=60.0, clock=clock)
        for _ in range(TIER_CAMPAIGN):
            assert limiter.acquire("start_tune").allowed is True
        clock.advance(59.999)
        rejected = limiter.acquire("start_tune")
        assert rejected.allowed is False
        assert rejected.retry_after_s == pytest.approx(0.001, abs=1e-9)
        clock.advance(0.001)  # age 恰=60.0
        recovered = limiter.acquire("start_tune")
        assert recovered.allowed is True
        assert recovered.count_in_window == 1

    def test_retry_after_s_value(self) -> None:
        """retry_after_s = window -（now-最老记录）：t=0,1,2 填满、t=3.5 拒。"""
        clock = _FakeClock()
        limiter = self._limiter(clock)
        for _ in range(TIER_CAMPAIGN):
            limiter.acquire("start_tune")
            clock.advance(1.0)  # 循环后 t=3.0
        clock.advance(0.5)  # t=3.5
        rejected = limiter.acquire("start_tune")
        assert rejected.allowed is False
        assert rejected.retry_after_s == pytest.approx(
            RATE_LIMIT_WINDOW_S - 3.5, abs=1e-9
        )

    def test_unlisted_tool_never_recorded(self) -> None:
        """表外工具零记账零限流（判 1 万次决策对象恒同形放行）。"""
        clock = _FakeClock()
        limiter = self._limiter(clock)
        for _ in range(10000):
            d = limiter.acquire("list_models")
            assert d.allowed and d.limit is None and d.retry_after_s is None
        assert clock.t == 0.0  # 未拨时钟：表外路径不消费时钟（零开销证据）


class TestUnlimitedEnv:
    def test_kill_switch_truthy_set(self) -> None:
        """RFAUTO_MCP_UNLIMITED ∈ {1,true,yes,on}（大小写不敏感）激活。"""
        assert unlimited_env_active({}) is False
        assert unlimited_env_active({"RFAUTO_MCP_UNLIMITED": "1"}) is True
        assert unlimited_env_active({"RFAUTO_MCP_UNLIMITED": "TRUE"}) is True
        assert unlimited_env_active({"RFAUTO_MCP_UNLIMITED": " yes "}) is True
        assert unlimited_env_active({"RFAUTO_MCP_UNLIMITED": "on"}) is True

    def test_kill_switch_non_truthy(self) -> None:
        assert unlimited_env_active({"RFAUTO_MCP_UNLIMITED": "0"}) is False
        assert unlimited_env_active({"RFAUTO_MCP_UNLIMITED": "off"}) is False
        assert unlimited_env_active({"RFAUTO_MCP_UNLIMITED": ""}) is False
        assert unlimited_env_active({"RFAUTO_MCP_UNLIMITED": "enable-all"}) is False

    def test_default_reads_os_environ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(UNLIMITED_ENV, "1")
        assert unlimited_env_active() is True
        monkeypatch.delenv(UNLIMITED_ENV, raising=False)
        assert unlimited_env_active() is False


# ─── ⑤ 限流中间件：error_envelope 信封纪律 ────────────────────────────────


def _mw_context(name: str) -> Any:
    return types.SimpleNamespace(message=types.SimpleNamespace(name=name))


class TestToolRateLimitMiddleware:
    def _fresh_server(self) -> tuple[Any, list[int]]:
        """独立 FastMCP 实例（不触共享单例）：表内/表外假工具各一。"""
        from fastmcp import FastMCP

        executed = [0, 0]
        mcp = FastMCP("vb7-guardrail-probe")

        @mcp.tool
        def start_tune() -> dict:  # 表内名（战役档 3/60s），函数体零求解
            executed[0] += 1
            return {"ok": True, "executed": executed[0]}

        @mcp.tool
        def list_models() -> dict:  # 表外名（只读语义），函数体零 I/O
            executed[1] += 1
            return {"ok": True, "executed": executed[1]}

        mcp.add_middleware(ToolRateLimitMiddleware(SlidingWindowRateLimiter(
            window_s=RATE_LIMIT_WINDOW_S, clock=_FakeClock())))
        return mcp, executed

    def _call(self, mcp: Any, name: str) -> Any:
        from fastmcp.client import Client

        async def _run() -> Any:
            async with Client(mcp) as client:
                return await client.call_tool(name, {}, raise_on_error=False)

        return asyncio.run(_run())

    def test_rejected_call_returns_error_envelope(self) -> None:
        """验收⑤：第 4 次 start_tune → isError + ok=False 信封（构造器键形）。"""
        mcp, executed = self._fresh_server()
        for _ in range(TIER_CAMPAIGN):
            result = self._call(mcp, "start_tune")
            assert result.is_error is False
        rejected = self._call(mcp, "start_tune")
        assert rejected.is_error is True
        payload = json.loads(rejected.content[0].text)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list) and payload["errors"]
        assert "start_tune" in payload["errors"][0]
        assert payload["tool"] == "start_tune"
        assert payload["limit"] == TIER_CAMPAIGN
        assert payload["window_s"] == RATE_LIMIT_WINDOW_S
        assert payload["retry_after_s"] > 0
        assert executed[0] == TIER_CAMPAIGN  # 被拒调用未执行

    def test_envelope_carries_merge_hint(self) -> None:
        """合并调用文案在 hint 键（点名 run_sweep 合并+解除开关）。"""
        mcp, _ = self._fresh_server()
        for _ in range(TIER_CAMPAIGN + 1):
            result = self._call(mcp, "start_tune")
        payload = json.loads(result.content[0].text)
        assert payload["hint"] == RATE_LIMIT_HINT
        assert "RFAUTO_MCP_UNLIMITED" in payload["hint"]
        assert "run_sweep" in payload["hint"]

    def test_unlimited_env_bypasses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """RFAUTO_MCP_UNLIMITED=1 时同工具连打 10 次全放行（解除开关）。"""
        monkeypatch.setenv(UNLIMITED_ENV, "1")
        mcp, executed = self._fresh_server()
        for _ in range(10):
            result = self._call(mcp, "start_tune")
            assert result.is_error is False
        assert executed[0] == 10

    def test_unlisted_tool_never_limited_through_middleware(self) -> None:
        """表外（只读语义）工具 50 连打全放行（中间件面验收③）。"""
        mcp, executed = self._fresh_server()
        for _ in range(50):
            result = self._call(mcp, "list_models")
            assert result.is_error is False
        assert executed[1] == 50

    def test_error_envelope_builder_shape(self) -> None:
        """信封构造器直钉（不经中间件）：errors 恒 list[str]+键序契约。"""
        decision = RateLimitDecision(
            tool="create_run", allowed=False, limit=TIER_LAUNCH,
            window_s=RATE_LIMIT_WINDOW_S, count_in_window=TIER_LAUNCH,
            retry_after_s=12.5,
        )
        payload = rate_limit_error_envelope(decision)
        assert payload["ok"] is False
        assert payload["errors"] == [
            "tool 'create_run' 触发滑窗限流：6 次/60s 窗口已满"
        ]
        assert payload["tool"] == "create_run"
        assert payload["limit"] == TIER_LAUNCH
        assert payload["retry_after_s"] == 12.5
        assert "hint" in payload


# ─── (a) stdio 信道纯度 ──────────────────────────────────────────────────


_PURITY_CHILD = '''\
"""VB-7 purity probe child: noisy tool over real stdio (acceptance (1))."""
import sys

from fastmcp import FastMCP
from rfauto.mcp_tools._ratelimit import StdioChannelPurityMiddleware

mcp = FastMCP("vb7-purity-probe")


@mcp.tool
def noisy_echo() -> dict:
    print("VB7-NOISE-LINE-FROM-TOOL")  # deliberate Python-level stdout print
    sys.stderr.write("VB7-STDERR-MARKER\\n")
    return {"ok": True, "data": "noisy-done"}


mcp.add_middleware(StdioChannelPurityMiddleware())
mcp.run(transport="stdio")
'''


class TestStdioChannelPurity:
    def test_subprocess_noisy_tool_keeps_stdout_parseable(self, tmp_path: Path) -> None:
        """验收①子进程钉：真实 stdio 会话中故意 print 的工具——stdout 每行
        仍可 json.loads，print 内容到 stderr（污染即红）。"""
        child = tmp_path / "vb7_purity_child.py"
        child.write_text(_PURITY_CHILD, encoding="utf-8")

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        for key in list(env):
            if key.startswith("RFAUTO_MCP_"):
                env.pop(key)
        proc = subprocess.Popen(
            [sys.executable, str(child)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(tmp_path),
        )
        out_lines: list[str] = []
        err_lines: list[str] = []

        def _reader(sink: list[str], stream: Any) -> None:
            for line in iter(stream.readline, ""):
                sink.append(line)

        t_out = threading.Thread(target=_reader, args=(out_lines, proc.stdout))
        t_err = threading.Thread(target=_reader, args=(err_lines, proc.stderr))
        t_out.start()
        t_err.start()
        try:
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "vb7-probe-parent", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "noisy_echo", "arguments": {}}},
            ]
            for req in requests:
                assert proc.stdin is not None
                proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            deadline = threading.Event()
            for _ in range(600):  # ≤60s：等 tools/call 响应（id==2）
                if any('"id": 2' in ln or '"id":2' in ln for ln in out_lines):
                    deadline.set()
                    break
                if proc.poll() is not None:
                    break
                threading.Event().wait(0.1)
            assert deadline.is_set(), (
                f"tools/call 未在期限内应答；stdout={out_lines!r} "
                f"stderr={err_lines[-5:]!r}"
            )
        finally:
            if proc.stdin is not None:
                proc.stdin.close()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            t_out.join(timeout=5)
            t_err.join(timeout=5)

        frames = [ln for ln in out_lines if ln.strip()]
        assert frames, "stdout 零协议帧=会话未建立"
        for line in frames:
            json.loads(line)  # 任一行不可解析即红（信道污染）
        assert not any("VB7-NOISE-LINE-FROM-TOOL" in ln for ln in out_lines)
        assert any("VB7-NOISE-LINE-FROM-TOOL" in ln for ln in err_lines)
        tool_result = [json.loads(ln) for ln in frames if '"id": 2' in ln or '"id":2' in ln]
        assert tool_result and tool_result[0]["result"]["isError"] is False
        inner = json.loads(tool_result[0]["result"]["content"][0]["text"])
        assert inner == {"ok": True, "data": "noisy-done"}

    def test_redirect_function_contracts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """纯函数钉：None 流/同流 no-op；异流才重定向并 flush 原流。"""
        import io

        monkeypatch.setattr(sys, "stdout", None, raising=False)
        assert redirect_python_stdout_to_stderr(None, io.StringIO()) is False
        fake_out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", fake_out, raising=False)
        assert redirect_python_stdout_to_stderr(fake_out, fake_out) is False
        fake_err = io.StringIO()
        assert redirect_python_stdout_to_stderr(fake_out, fake_err) is True
        assert sys.stdout is fake_err

    def test_purity_middleware_redirects_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """一次性语义：首个 initialize 重定向，后续调用不再动 sys.stdout。"""
        import io

        fake_out, fake_err = io.StringIO(), io.StringIO()
        monkeypatch.setattr(sys, "stdout", fake_out, raising=False)
        monkeypatch.setattr(sys, "stderr", fake_err, raising=False)
        mw = StdioChannelPurityMiddleware()
        calls = []

        async def call_next(_ctx: Any) -> str:
            calls.append(1)
            return "passed"

        ctx = types.SimpleNamespace(message=types.SimpleNamespace())
        assert asyncio.run(mw.on_initialize(ctx, call_next)) == "passed"
        assert sys.stdout is fake_err and mw.redirected is True
        third = io.StringIO()
        monkeypatch.setattr(sys, "stderr", third, raising=False)
        assert asyncio.run(mw.on_initialize(ctx, call_next)) == "passed"
        assert sys.stdout is fake_err  # 第二次 initialize 不再重定向
        assert len(calls) == 2  # call_next 每次都透传


# ─── main() 接线钉（stdio 会话面挂两护栏；in-memory 面零行为变化）──────────


class TestMainWiring:
    def test_main_attaches_both_guardrails_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() run 期间挂 ToolRateLimit+StdioChannelPurity 两中间件；
        返回前摘除（共享单例零泄漏；二次 main 拿新挂载不叠加）。"""
        from rfauto import mcp_server

        seen: list[tuple[list[str], dict]] = []
        monkeypatch.setattr(
            mcp_server.mcp, "run",
            lambda *a, **kw: seen.append(
                ([type(m).__name__ for m in mcp_server.mcp.middleware], kw)
            ),
            raising=False,
        )
        before = list(mcp_server.mcp.middleware)
        try:
            mcp_server.main()
            mcp_server.main()  # 二次会话：重新挂载（首次已在 finally 摘除）
            assert len(seen) == 2
            for kinds, kw in seen:
                assert kw.get("transport") == "stdio"
                # run 期间恰各一个（挂载幂等查重；basic DereferenceRefs 除外）
                assert kinds.count("ToolRateLimitMiddleware") == 1
                assert kinds.count("StdioChannelPurityMiddleware") == 1
            # main 返回后单例恢复原面（护栏零泄漏）
            kinds_after = [type(m).__name__ for m in mcp_server.mcp.middleware]
            assert "ToolRateLimitMiddleware" not in kinds_after
            assert "StdioChannelPurityMiddleware" not in kinds_after
            assert kinds_after == [type(m).__name__ for m in before]
        finally:
            mcp_server.mcp.middleware[:] = before

    def test_import_time_singleton_has_no_guardrails(self) -> None:
        """facade import 面+main 返回面零护栏挂载——in-memory 通道
        （mcp_chat）零行为变化（对 test_mcp_server.TestMainEntry 的进程内
        main() 调用次序鲁棒：护栏挂载被 main 的 finally 对称摘除）。"""
        from rfauto.mcp_tools._core import mcp as singleton

        kinds = [type(m).__name__ for m in singleton.middleware]
        assert "ToolRateLimitMiddleware" not in kinds
        assert "StdioChannelPurityMiddleware" not in kinds
