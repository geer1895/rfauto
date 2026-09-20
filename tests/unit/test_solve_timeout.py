"""watchdog 求解超时接线测试（计划内缺口 7）。

原先 Watchdog 计时器零引用、HfssAdapter.solve 的 timeout_s 是死参数。
本文件用 stub 会话验证超时强杀路径（不依赖真实 AEDT）。
"""

from __future__ import annotations

import threading
import time

from rfauto.adapters.hfss_adapter import HfssAdapter
from rfauto.core.interfaces import SolveReport


class StubHfss:
    """模拟 pyaedt Hfss：analyze 慢，Abort 可中止。"""

    def __init__(self, analyze_seconds: float = 5.0):
        self.analyze_seconds = analyze_seconds
        self.abort_calls = 0
        self._abort_event = threading.Event()
        self.odesign = self

    def Abort(self):
        self.abort_calls += 1
        self._abort_event.set()

    def analyze_setup(self, name: str, blocking: bool = True) -> bool:
        # 被 Abort：返回非成功
        return not self._abort_event.wait(timeout=self.analyze_seconds)

    def get_setup(self, name: str):
        return None


class StubSession:
    def __init__(self, hfss):
        self.hfss = hfss


def _adapter_with(stub: StubHfss) -> HfssAdapter:
    ad = HfssAdapter()
    ad.session = StubSession(stub)
    return ad


class TestSolveTimeout:
    def test_timeout_aborts_and_reports_failure(self):
        stub = StubHfss(analyze_seconds=5.0)
        ad = _adapter_with(stub)
        start = time.time()
        report = ad.solve("Setup1", timeout_s=0.2)
        elapsed = time.time() - start

        assert isinstance(report, SolveReport)
        assert report.success is False
        assert "超时" in report.message
        assert stub.abort_calls == 1, "超时必须调用 odesign.Abort() 强杀"
        assert elapsed < 3.0, f"Abort 后应尽快返回，实际 {elapsed:.1f}s"

    def test_normal_solve_within_timeout(self):
        stub = StubHfss(analyze_seconds=0.05)
        ad = _adapter_with(stub)
        report = ad.solve("Setup1", timeout_s=10)
        assert report.success is True
        assert stub.abort_calls == 0

    def test_watchdog_cancelled_after_solve(self):
        """正常求解后计时器必须被取消，不得在后台误触发。"""
        stub = StubHfss(analyze_seconds=0.02)
        ad = _adapter_with(stub)
        report = ad.solve("Setup1", timeout_s=0.2)
        assert report.success
        time.sleep(0.4)  # 若计时器未取消，此刻已触发 Abort
        assert stub.abort_calls == 0

    def test_analyze_exception_returns_failure_report(self):
        class ExplodingStub(StubHfss):
            def analyze_setup(self, name: str, blocking: bool = True) -> bool:
                raise RuntimeError("gRPC channel closed")

        ad = _adapter_with(ExplodingStub())
        report = ad.solve("Setup1", timeout_s=10)
        assert report.success is False
        assert "gRPC" in report.message

    def test_watchdog_fired_but_solve_completed_accepts_result(self):
        """竞态：watchdog 到点但 Abort 失败（analyze 已正常返回）→ 接受真实结果。

        2026-09-03 真机教训：93 分钟才解完的 HFSS 求解被 1h watchdog 判超时
        丢弃。Abort 打断不了已完成的求解时不得把算完的解当超时扔掉。
        """
        stub = StubHfss(analyze_seconds=0.6)

        class AbortFailsStub(stub.__class__):
            def Abort(self):
                self.abort_calls += 1
                raise RuntimeError("Failed to execute gRPC AEDT command: Abort")

        stub2 = AbortFailsStub(analyze_seconds=0.6)
        ad = _adapter_with(stub2)
        report = ad.solve("Setup1", timeout_s=0.2)
        assert report.success is True, "求解实际完成时不得判超时失败"
        assert stub2.abort_calls == 1  # watchdog 确实试过 Abort 但失败了

    def test_env_override_raises_timeout(self, monkeypatch):
        monkeypatch.setenv("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "3600")
        stub = StubHfss(analyze_seconds=0.05)
        ad = _adapter_with(stub)
        report = ad.solve("Setup1", timeout_s=1)
        assert report.success is True  # 环境变量覆盖后 1s 参数不生效为超时
        assert stub.abort_calls == 0
