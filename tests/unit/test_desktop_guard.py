"""desktop_guard 单源三态行为钉（桌面治理批）。

语义（范式，scripts/factory_mf_hfss_anchors.py 原型上收）：
活桌面（父进程存活）绝不代杀（strict 抛错/非 strict 记录跳过）；孤儿
（父进程已死）点杀该 PID+退出窗+复核；枚举/查询/终止失败一律不杀
（strict 抛错 fail-closed/非 strict 记录）。subprocess.run 全 mock，零真机。
"""

from __future__ import annotations

import re
import subprocess
import types

import pytest

from rfauto.infra import desktop_guard as dg


def _ps_result(rc: int, out: str, err: str = ""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def _enum_line(pid: int, ppid: int) -> str:
    return f"{pid}|{ppid}|C:\\tools\\ansysedt.exe -grpcsrv -ng"


class _FakeRun:
    """按 PowerShell 命令形状分发的 fake subprocess.run（零真机）。"""

    def __init__(self, *, enum_results: list, parent_alive: bool = False,
                  kill_rc: int = 0):
        self.enum_calls = 0
        self.enum_results = list(enum_results)  # 每次 enum 弹一个 (rc, lines)
        self.parent_alive = parent_alive
        self.kill_rc = kill_rc
        self.kills: list[int] = []

    def __call__(self, cmd, **_kw):
        joined = " ".join(cmd)
        if "Get-CimInstance" in joined:
            self.enum_calls += 1
            if self.enum_calls <= len(self.enum_results):
                rc, lines = self.enum_results[self.enum_calls - 1]
            else:
                rc, lines = 0, []
            return _ps_result(rc, "\n".join(lines),
                              "" if rc == 0 else "boom")
        if "Get-Process -Id" in joined:
            return _ps_result(0, "alive" if self.parent_alive else "dead")
        if "Stop-Process" in joined:
            m = re.search(r"Stop-Process -Id (\d+)", joined)
            assert m is not None, joined
            self.kills.append(int(m.group(1)))
            return _ps_result(self.kill_rc, "")
        raise AssertionError(f"未预期的 subprocess 调用: {joined[:120]}")


class TestKillOrphansStrict:
    """发射前/重试轮内口径（strict=True）：异常一律 fail-closed 抛错。"""

    def test_empty_field_returns_without_kill(self, monkeypatch):
        fake = _FakeRun(enum_results=[(0, [])])
        monkeypatch.setattr(subprocess, "run", fake)
        logs: list[str] = []
        dg.kill_orphan_ansysedt_desktops(log=logs.append)
        assert fake.kills == []
        assert fake.enum_calls == 1, "空场快速返回，不触发存活查询"

    def test_live_desktop_raises_no_kill(self, monkeypatch):
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222)])],
                        parent_alive=True)
        monkeypatch.setattr(subprocess, "run", fake)
        monkeypatch.setattr(dg.time, "sleep", lambda _s: None)
        with pytest.raises(RuntimeError, match="活桌面"):
            dg.kill_orphan_ansysedt_desktops(log=lambda _m: None)
        assert fake.kills == [], "活桌面（父进程在）绝不代杀（#245）"

    def test_orphan_killed_then_verified(self, monkeypatch):
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222)])],
                        parent_alive=False)
        monkeypatch.setattr(subprocess, "run", fake)
        sleeps: list[float] = []
        monkeypatch.setattr(dg.time, "sleep", sleeps.append)
        logs: list[str] = []
        dg.kill_orphan_ansysedt_desktops(log=logs.append)
        assert fake.kills == [111], "孤儿（父进程已死）点杀该 PID"
        assert sleeps and sleeps[0] > 0, "杀后留退出窗再复核"
        assert any("111" in m for m in logs)

    def test_enum_failure_raises_no_kill(self, monkeypatch):
        fake = _FakeRun(enum_results=[(1, [])])
        monkeypatch.setattr(subprocess, "run", fake)
        with pytest.raises(RuntimeError, match="枚举失败"):
            dg.kill_orphan_ansysedt_desktops(log=lambda _m: None)
        assert fake.kills == [], "枚举失败 fail-closed，不盲杀（#245）"

    def test_unparsable_enum_line_raises(self, monkeypatch):
        fake = _FakeRun(enum_results=[(0, ["garbage-line-no-pipes"])])
        monkeypatch.setattr(subprocess, "run", fake)
        with pytest.raises(RuntimeError, match="不可解析"):
            dg.kill_orphan_ansysedt_desktops(log=lambda _m: None)
        assert fake.kills == []

    def test_parent_query_failure_raises_no_kill(self, monkeypatch):
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222)])])
        monkeypatch.setattr(subprocess, "run", fake)

        def broken_run(cmd, **_kw):
            if "Get-Process -Id" in " ".join(cmd):
                return _ps_result(1, "", "query failed")
            return fake(cmd)

        monkeypatch.setattr(subprocess, "run", broken_run)
        with pytest.raises(RuntimeError, match="存活查询失败"):
            dg.kill_orphan_ansysedt_desktops(log=lambda _m: None)

    def test_kill_failure_raises(self, monkeypatch):
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222)])],
                        parent_alive=False, kill_rc=1)
        monkeypatch.setattr(subprocess, "run", fake)
        with pytest.raises(RuntimeError, match="终止失败"):
            dg.kill_orphan_ansysedt_desktops(log=lambda _m: None)

    def test_leftover_after_kill_raises(self, monkeypatch):
        # 两次枚举都返回同一孤儿（杀掉后仍存活）→ 复核失败 fail-closed
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222)]),
                                      (0, [_enum_line(111, 222)])],
                        parent_alive=False)
        monkeypatch.setattr(subprocess, "run", fake)
        monkeypatch.setattr(dg.time, "sleep", lambda _s: None)
        with pytest.raises(RuntimeError, match="仍有 1 个 ansysedt"):
            dg.kill_orphan_ansysedt_desktops(log=lambda _m: None)
        assert fake.kills == [111]

    def test_recheck_enum_failure_raises(self, monkeypatch):
        # round6 C-M1：杀后复核枚举瞬态失败 → strict fail-closed 原样抛
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222)]),
                                      (1, [])],
                        parent_alive=False)
        monkeypatch.setattr(subprocess, "run", fake)
        monkeypatch.setattr(dg.time, "sleep", lambda _s: None)
        with pytest.raises(RuntimeError, match="枚举失败"):
            dg.kill_orphan_ansysedt_desktops(log=lambda _m: None)
        assert fake.kills == [111]


class TestKillOrphansNonStrict:
    """attempt 间（try 外）/收尾扫尾口径（strict=False）：只记录不抛。"""

    def test_live_desktop_logged_not_killed_no_raise(self, monkeypatch):
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222)])],
                        parent_alive=True)
        monkeypatch.setattr(subprocess, "run", fake)
        monkeypatch.setattr(dg.time, "sleep", lambda _s: None)
        logs: list[str] = []
        dg.kill_orphan_ansysedt_desktops(log=logs.append, strict=False)
        assert fake.kills == [], "非 strict 下活桌面也不杀（#245）"
        assert any("活桌面" in m for m in logs), "活桌面必须留痕"

    def test_enum_failure_logged_no_raise(self, monkeypatch):
        fake = _FakeRun(enum_results=[(1, [])])
        monkeypatch.setattr(subprocess, "run", fake)
        logs: list[str] = []
        dg.kill_orphan_ansysedt_desktops(log=logs.append, strict=False)
        assert fake.kills == []
        assert any("枚举失败" in m for m in logs)

    def test_orphans_still_killed(self, monkeypatch):
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222)])],
                        parent_alive=False)
        monkeypatch.setattr(subprocess, "run", fake)
        monkeypatch.setattr(dg.time, "sleep", lambda _s: None)
        dg.kill_orphan_ansysedt_desktops(log=lambda _m: None, strict=False)
        assert fake.kills == [111], "非 strict 只豁免'不杀'的保守向，孤儿照杀"

    def test_parent_query_failure_skips_that_pid(self, monkeypatch):
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222),
                                           _enum_line(333, 444)])])

        def broken_run(cmd, **_kw):
            joined = " ".join(cmd)
            if "Get-Process -Id 222" in joined:
                return _ps_result(1, "", "query failed")
            return fake(cmd)

        monkeypatch.setattr(subprocess, "run", broken_run)
        monkeypatch.setattr(dg.time, "sleep", lambda _s: None)
        logs: list[str] = []
        dg.kill_orphan_ansysedt_desktops(log=logs.append, strict=False)
        assert fake.kills == [333], "查询失败的按活桌面跳过，其余孤儿照杀"

    def test_kill_failure_logged_continue(self, monkeypatch):
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222)])],
                        parent_alive=False, kill_rc=1)
        monkeypatch.setattr(subprocess, "run", fake)
        logs: list[str] = []
        dg.kill_orphan_ansysedt_desktops(log=logs.append, strict=False)
        assert any("终止失败" in m for m in logs)

    def test_recheck_enum_failure_logged_no_raise(self, monkeypatch):
        # round6 C-M1：杀后复核枚举瞬态失败 → strict=False 只记录不抛
        #（收尾扫尾路径绝不因观测面失败连坐，#105；已杀 PID 留痕）
        fake = _FakeRun(enum_results=[(0, [_enum_line(111, 222)]),
                                      (1, [])],
                        parent_alive=False)
        monkeypatch.setattr(subprocess, "run", fake)
        monkeypatch.setattr(dg.time, "sleep", lambda _s: None)
        logs: list[str] = []
        dg.kill_orphan_ansysedt_desktops(log=logs.append, strict=False)
        assert fake.kills == [111]
        assert any("复核枚举失败" in m for m in logs)


class TestRunWithWatchdog:
    def test_completion_returns_normally(self):
        box = {"ran": False}

        def fn():
            box["ran"] = True

        dg.run_with_watchdog(fn, timeout_s=5.0, what="t",
                             log=lambda _m: None)
        assert box["ran"]

    def test_fn_exception_propagates_verbatim(self):
        def fn():
            raise ValueError("gRPC 闪断 #191")

        with pytest.raises(ValueError, match="gRPC 闪断"):
            dg.run_with_watchdog(fn, timeout_s=5.0, what="t",
                                 log=lambda _m: None)

    def test_timeout_raises_fail_closed(self):
        import threading

        ev = threading.Event()

        def fn():
            ev.wait(10.0)  # 模拟挂死的 analyze

        with pytest.raises(RuntimeError, match="看门狗超时"):
            dg.run_with_watchdog(fn, timeout_s=0.05, what="t",
                                 log=lambda _m: None)


class TestReleaseDesktopCapped:
    def test_returns_true_when_release_returns(self):
        assert dg.release_desktop_capped(
            lambda: None, timeout_s=5.0, log=lambda _m: None) is True

    def test_release_exception_logged_not_raised(self):
        logs: list[str] = []

        def boom():
            raise RuntimeError("desktop gone")

        ret = dg.release_desktop_capped(boom, timeout_s=5.0,
                                        log=logs.append)
        assert ret is True, "finally best-effort（#105）：失败只记录不抛"
        assert any("#265" in m for m in logs)

    def test_timeout_returns_false_and_logs(self):
        import threading

        ev = threading.Event()
        logs: list[str] = []

        def stuck():
            ev.wait(10.0)  # 模拟对求解中桌面阻塞（#145 attempt1 实测 3.6h）

        ret = dg.release_desktop_capped(stuck, timeout_s=0.05,
                                        log=logs.append)
        assert ret is False
        assert any("未返回" in m for m in logs)
