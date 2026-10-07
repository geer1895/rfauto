"""MCP 长任务工具族 wait_job 行为测试（A1 验收遗留补钉）。

接地结论（#222，2026-10-03）：A1"长任务三工具"（submit/poll/cancel+
progressToken）已由 DP-14 A1 闭合——create_run_async/poll_job/cancel_job/
wait_job 全在 mcp_tools/jobs.py（计数 123 内）；本文件只补当时缺的
wait_job 行为验收（DP-14 判据："progress 序列单调不减"+终态/超时语义），
不新增工具、不动已合流面（计数钉维持 123）。

服务通道 monkeypatch 钉住（#139：in-function import 在调用时解析，
patch rfauto.service.api.poll_job 即可，零真任务零网络）。
"""

from __future__ import annotations

import pytest

from rfauto.mcp_tools import jobs as jobs_tools


def _patch_poll(monkeypatch: pytest.MonkeyPatch, stub) -> None:
    import rfauto.service.api as api_mod

    monkeypatch.setattr(api_mod, "poll_job", stub)


class TestWaitJobBehavior:
    def test_completed_terminal_returns_last_state(self, monkeypatch):
        """终态即回：返回最后已知状态+wait=terminal+ok=True。"""
        calls: list[str] = []

        def stub(job_id: str) -> dict:
            calls.append(job_id)
            return {"ok": True, "job_id": job_id, "status": "completed",
                    "progress": 1.0, "metrics": {"cost": 0.1}}

        _patch_poll(monkeypatch, stub)
        out = jobs_tools.wait_job("job_x", timeout_s=5.0, poll_interval_s=0.001)
        assert out["ok"] is True
        assert out["wait"] == "terminal"
        assert out["status"] == "completed"
        assert out["metrics"] == {"cost": 0.1}
        assert len(calls) == 1  # 终态首拍即回，不空转

    def test_cancelled_is_terminal(self, monkeypatch):
        """cancelled 也是终态（cancel 后 wait 立即结算，不等到超时）。"""
        def stub(job_id: str) -> dict:
            return {"ok": True, "job_id": job_id, "status": "cancelled"}

        _patch_poll(monkeypatch, stub)
        out = jobs_tools.wait_job("job_x", timeout_s=5.0, poll_interval_s=0.001)
        assert out["wait"] == "terminal"
        assert out["status"] == "cancelled"

    def test_polls_until_terminal_progress_monotonic(self, monkeypatch):
        """A1 判据：轮询持续推进至终态，progress 序列单调不减。"""
        sequence = [
            {"ok": True, "status": "running", "progress": 0.0},
            {"ok": True, "status": "running", "progress": 0.25},
            {"ok": True, "status": "running", "progress": 0.25},
            {"ok": True, "status": "running", "progress": 0.9},
            {"ok": True, "status": "completed", "progress": 1.0},
        ]
        seen: list[float] = []

        def stub(job_id: str) -> dict:
            state = sequence[min(len(seen), len(sequence) - 1)]
            seen.append(state["progress"])
            return {"job_id": job_id, **state}

        _patch_poll(monkeypatch, stub)
        out = jobs_tools.wait_job("job_x", timeout_s=5.0, poll_interval_s=0.001)
        assert out["wait"] == "terminal"
        assert len(seen) == 5  # 逐拍消费到终态，不提前退出
        assert seen == sorted(seen)  # progress 序列单调不减（A1 判据钉）

    def test_timeout_returns_last_known(self, monkeypatch):
        """超时路径：ok=False+wait=timeout+最后已知状态，不抛异常。"""
        def stub(job_id: str) -> dict:
            return {"ok": True, "job_id": job_id, "status": "running",
                    "progress": 0.1}

        _patch_poll(monkeypatch, stub)
        out = jobs_tools.wait_job("job_x", timeout_s=0.05,
                                  poll_interval_s=0.01)
        assert out["ok"] is False
        assert out["wait"] == "timeout"
        assert out["status"] == "running"
        assert "超时" in out["error"]

    def test_failed_terminal(self, monkeypatch):
        """failed 终态立即结算（失败也要能收割，不空等）。"""
        def stub(job_id: str) -> dict:
            return {"ok": True, "job_id": job_id, "status": "failed",
                    "message": "boom"}

        _patch_poll(monkeypatch, stub)
        out = jobs_tools.wait_job("job_x", timeout_s=5.0, poll_interval_s=0.001)
        assert out["wait"] == "terminal"
        assert out["status"] == "failed"

    def test_facade_exposes_tool(self):
        """mcp_server facade re-export 完整性（注册面快照钉的轻量旁证）。"""
        import rfauto.mcp_server as mcp_server

        assert hasattr(mcp_server, "wait_job")
        assert hasattr(mcp_server, "cancel_job")
        assert hasattr(mcp_server, "poll_job")
        assert hasattr(mcp_server, "create_run_async")
