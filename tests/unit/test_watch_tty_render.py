"""tune/jobs --watch TTY rich 渲染抽检（R3_followups §② #12，W7-D 2026-10-11）。

非 TTY 路径既有钉不动（test_w6_a_sn_platform.TestSn19Watch 直调/CliRunner 面、
test_w1d_watch_detach.py 的非终端逐行播报面）；本文件补 **TTY 路径新钉**：
rich ``Console(record=True, force_terminal=True)`` 记录态快照——渲染含关键
节头（tick 行/终态行/播报表头/caption）、全程无例外。零真终端、零 sleep
（time.sleep 打桩）、零 job 后台面（poll_job 打桩）。
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import typer
from rich.console import Console


def _tty_console() -> Console:
    """记录态 TTY Console：force_terminal 打开终端支路，record 留快照。"""
    return Console(file=io.StringIO(), width=100, force_terminal=True,
                   legacy_windows=False, record=True)


def _patch_sleep(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def _scripted_poll(states: list[dict]):
    """按序吐状态脚本（running 轨迹 → 终态），超序取末态。"""
    it = iter(states)

    def _poll(job_id: str) -> dict:
        try:
            return dict(next(it))
        except StopIteration:
            return dict(states[-1])

    return _poll


class TestJobsWatchTtyRender:
    """jobs --watch（_watch_poll）终端路径：rich 记录态快照。"""

    def test_tty_done_path_renders_ticks_and_final(self, monkeypatch):
        tty = _tty_console()
        monkeypatch.setattr("rfauto.cli.domains._core.console", tty)
        monkeypatch.setattr("rfauto.service.api.poll_job", _scripted_poll([
            {"state": "running", "progress_pct": 12, "stage": "mesh"},
            {"state": "running", "progress_pct": 55, "stage": "solve"},
            {"state": "done", "progress_pct": 100, "stage": ""},
        ]))
        _patch_sleep(monkeypatch)

        from rfauto.cli.domains._core import _watch_poll

        _watch_poll("job_tty1", interval_s=0.01, timeout_s=5.0,
                    json_output=False, label="job")  # 无例外即 exit 0 面

        out = tty.export_text()
        # 关键节头：逐 tick 进度行（markup=False 字面括号保留）+ 终态行
        assert "[1] job job_tty1" in out
        assert "state=running" in out and "progress=12%" in out
        assert "stage=solve" in out
        assert "state=done" in out and "progress=100%" in out
        assert "✓ 终态 done：job_tty1" in out
        assert "✗" not in out  # 成功路径无失败行

    def test_tty_timeout_renders_red_line_and_exits_1(self, monkeypatch):
        tty = _tty_console()
        monkeypatch.setattr("rfauto.cli.domains._core.console", tty)
        monkeypatch.setattr("rfauto.service.api.poll_job", _scripted_poll([
            {"state": "running", "progress_pct": 40, "stage": "solve"},
        ]))
        _patch_sleep(monkeypatch)

        from rfauto.cli.domains._core import _watch_poll

        with pytest.raises(typer.Exit) as ei:
            _watch_poll("job_tty2", interval_s=0.01, timeout_s=0.0,
                        json_output=False, label="job")
        assert ei.value.exit_code == 1
        out = tty.export_text()
        assert "watch 超时" in out and "末态 state=running" in out
        assert "✓ 终态 done" not in out

    def test_tty_failed_terminal_exits_1_without_done_line(self, monkeypatch):
        tty = _tty_console()
        monkeypatch.setattr("rfauto.cli.domains._core.console", tty)
        monkeypatch.setattr("rfauto.service.api.poll_job", _scripted_poll([
            {"state": "solve_failed", "progress_pct": None, "stage": "solve"},
        ]))
        _patch_sleep(monkeypatch)

        from rfauto.cli.domains._core import _watch_poll

        with pytest.raises(typer.Exit) as ei:
            _watch_poll("job_tty3", interval_s=0.01, timeout_s=5.0,
                        json_output=False, label="job")
        assert ei.value.exit_code == 1
        out = tty.export_text()
        assert "state=solve_failed" in out
        assert "✓ 终态 done" not in out


class TestTuneWatchTtyRender:
    """tune --watch（_TrialWatchReporter）终端路径：Live 表格记录态快照。

    TTY 下回调只刷 Live 不走逐行直出（非 TTY 分支的既有钉在
    test_w1d_watch_detach.py，此处不破）。
    """

    @staticmethod
    def _trial(number: int, value):
        class _T:
            state = "COMPLETE"

        t = _T()
        t.number = number
        t.value = value
        return t

    def test_tty_live_snapshot_contains_header_rows_caption(self):
        from rfauto.cli.domains.workflow import _TrialWatchReporter

        tty = _tty_console()
        reporter = _TrialWatchReporter(tty)
        with reporter:  # __enter__/__exit__（Live 起停）全程无例外
            reporter(None, self._trial(0, 2.5))
            reporter(None, self._trial(1, 2.1))
            reporter(None, self._trial(2, 2.3))

        out = tty.export_text()
        assert "tune --watch 逐 trial 播报" in out  # 表题节头
        assert "trial" in out and "state" in out   # 列头
        assert "2.5000" in out and "+0.2000" in out  # 行值与 Δ
        assert "best cost: 2.1000" in out and "trial 1" in out  # caption

    def test_tty_pruned_row_renders_em_dash(self):
        from rfauto.cli.domains.workflow import _TrialWatchReporter

        tty = _tty_console()
        reporter = _TrialWatchReporter(tty)
        with reporter:
            reporter(None, self._trial(0, 1.0))
            t = self._trial(1, None)
            t.state = "PRUNED"
            reporter(None, t)
        out = tty.export_text()
        assert "PRUNED" in out and "best cost: 1.0000" in out


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
