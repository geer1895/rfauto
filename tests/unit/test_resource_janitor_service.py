"""resource_janitor_service 回归钉——janitor 扫描/白名单清理/内存闸（doctor --janitor 面）。

进程面用注入 sys.modules 的假 psutil 隔离（零真机进程依赖）；锁面用 tmp
工作根；CLI 烟测对 service 函数 monkeypatch（不扫真实 runs/）。
"""

from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.domains._core import app as cli_app
from rfauto.cli.domains.system import doctor
from rfauto.service import resource_janitor_service as rj
from rfauto.service.envelope import ok_envelope
from rfauto.service.resource_janitor_service import janitor_clean, janitor_scan, memory_gate

# ─── 假 psutil 注入（service 层惰性 import psutil → 取 sys.modules 假体）──────


class _FakeMem:
    def __init__(self, rss: int) -> None:
        self.rss = rss


class _FakeCpuTimes:
    def __init__(self) -> None:
        self.user = 1.0
        self.system = 2.0
        self.children_user = 0.5
        self.children_system = 0.5


class _FakeProc:
    def __init__(
        self,
        *,
        pid: int,
        name: str,
        parent: _FakeProc | None = None,
        rss_bytes: int = 800 * 1024**2,
        create_time: float = 1700000000.0,
        cmdline: list[str] | None = None,
    ) -> None:
        self.pid = pid
        self._name = name
        self._parent = parent
        self._rss = rss_bytes
        self._create = create_time
        self._cmdline = cmdline or []

    def name(self) -> str:
        return self._name

    def parent(self) -> _FakeProc | None:
        return self._parent

    def memory_info(self) -> _FakeMem:
        return _FakeMem(self._rss)

    def cpu_times(self) -> _FakeCpuTimes:
        return _FakeCpuTimes()

    def create_time(self) -> float:
        return self._create

    def cmdline(self) -> list[str]:
        return self._cmdline


class _FakePsutilError(Exception):
    """假 psutil 的 Error/NoSuchProcess/TimeoutExpired 同源异常类。"""


def _install_fake_psutil(monkeypatch: pytest.MonkeyPatch, procs: list[_FakeProc]) -> None:
    by_pid = {p.pid: p for p in procs}

    class _FakeProcess:
        def __init__(self, pid: int) -> None:
            self._proc = by_pid.get(int(pid))

        def name(self) -> str:
            if self._proc is None:
                raise _FakePsutilError("no such process")
            return self._proc.name()

    fake = types.SimpleNamespace(
        process_iter=lambda attrs=None: iter(procs),
        Process=_FakeProcess,
        Error=_FakePsutilError,
        NoSuchProcess=_FakePsutilError,
        TimeoutExpired=_FakePsutilError,
    )
    monkeypatch.setitem(sys.modules, "psutil", fake)


def _make_lock_root(tmp_path: Path) -> tuple[Path, str]:
    """tmp 工作根：proj.aedt + proj.lock（伴生对）。返回 (根, 锁路径串)。"""
    root = tmp_path / "runs"
    root.mkdir()
    (root / "proj.aedt").write_text("x", encoding="utf-8")
    lock = root / "proj.lock"
    lock.write_text("x", encoding="utf-8")
    return root, str(lock)


# ─── janitor_scan：进程清点 ──────────────────────────────────────────────────


class TestJanitorScanProcesses:
    def test_lists_aedt_family_with_orphan_evidence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        orphan = _FakeProc(pid=101, name="ansysedt.exe", parent=None)
        live_child = _FakeProc(pid=102, name="ansysedt.exe", parent=_FakeProc(pid=9, name="python.exe"))
        unrelated = _FakeProc(pid=103, name="chrome.exe", parent=None)
        _install_fake_psutil(monkeypatch, [orphan, live_child, unrelated])

        result = janitor_scan(scan_roots=[])
        assert result["ok"] is True
        procs = result["processes"]
        assert sorted(p["pid"] for p in procs) == [101, 102]
        by_pid = {p["pid"]: p for p in procs}
        # 孤儿（父进程已退出）：只给证据不下结论，suspect 仅为启发式标记
        assert by_pid[101]["suspect"] is True
        assert any("parent_exited" in r for r in by_pid[101]["suspect_reasons"])
        # 活父进程（python 持有的正常 gRPC 会话）不标疑
        assert by_pid[102]["suspect"] is False
        assert by_pid[102]["parent_name"] == "python.exe"
        assert by_pid[102]["rss_gb"] == pytest.approx(800 * 1024**2 / 1024**3, rel=1e-9)
        assert by_pid[102]["cpu_time_s"] == pytest.approx(4.0)
        assert result["summary"]["n_suspect"] == 1
        assert result["summary"]["n_processes"] == 2
        assert result["summary"]["process_channel"] == "psutil"

    def test_system_session_parent_flagged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adopted = _FakeProc(pid=201, name="ansysedt.exe", parent=_FakeProc(pid=4, name="services.exe"))
        _install_fake_psutil(monkeypatch, [adopted])
        result = janitor_scan(scan_roots=[])
        assert result["processes"][0]["suspect"] is True
        assert any("parent_is_system_session" in r for r in result["processes"][0]["suspect_reasons"])

    def test_scan_without_psutil_locks_still_scanned(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setitem(sys.modules, "psutil", None)  # import psutil → ImportError 通道
        root, _lock = _make_lock_root(tmp_path)
        result = janitor_scan(scan_roots=[root])
        assert result["ok"] is True
        assert result["processes"] == []
        assert result["summary"]["process_channel"].startswith("psutil 不可用")
        assert result["summary"]["n_locks"] == 1


# ─── janitor_scan：AEDT 工程锁识别 ───────────────────────────────────────────


class TestJanitorScanLocks:
    def test_only_aedt_paired_locks_collected(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        root.mkdir()
        (root / "proj.aedt").write_text("x", encoding="utf-8")
        (root / "proj.lock").mkdir()  # 目录锁 + 伴生工程 → 收
        (root / "solo.aedt.lock").write_text("x", encoding="utf-8")  # .aedt.lock 命名 → 收
        (root / ".oe_collect.lock").write_text("x", encoding="utf-8")  # rfauto 内部锁无伴生 → 不收
        (root / "unrelated.lock").write_text("x", encoding="utf-8")  # 无伴生工程 → 不收
        locks, truncated = rj._scan_locks([root])
        names = sorted(Path(lk["path"]).name for lk in locks)
        assert names == ["proj.lock", "solo.aedt.lock"]
        assert truncated is False
        entry = {Path(lk["path"]).name: lk for lk in locks}
        assert entry["proj.lock"]["is_dir"] is True
        assert entry["proj.lock"]["paired_project"] is True
        assert entry["solo.aedt.lock"]["paired_project"] is False

    def test_truncation_cap(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rj, "_MAX_LOCK_ENTRIES", 3)
        root = tmp_path / "runs"
        root.mkdir()
        for i in range(5):
            (root / f"p{i}.aedt").write_text("x", encoding="utf-8")
            (root / f"p{i}.lock").write_text("x", encoding="utf-8")
        locks, truncated = rj._scan_locks([root])
        assert truncated is True
        assert len(locks) == 3


# ─── memory_gate：两态 + 通道不可用 ──────────────────────────────────────────


class TestMemoryGate:
    def test_pass_and_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rj, "_query_available_bytes", lambda: (20.0 * 1024**3, "psutil"))
        passed = memory_gate(8.0)
        assert passed["ok"] is True
        assert passed["available_gb"] == pytest.approx(20.0, rel=1e-9)
        assert passed["channel"] == "psutil"
        blocked = memory_gate(50.0)
        assert blocked["ok"] is False
        assert blocked.get("errors", []) == []  # 达成态走 ok 信封，errors 键缺省即空
        assert "不放行" in blocked["message"]

    def test_unreadable_channel_refuses_not_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rj, "_query_available_bytes", lambda: (None, None))
        gate = memory_gate(1.0)
        assert gate["ok"] is False  # 未知态不放行（不凑绿）
        assert gate["available_gb"] is None
        assert gate["errors"]


# ─── janitor_clean：白名单/dry_run/执行三道闸 ────────────────────────────────


class TestJanitorClean:
    def _env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, str]:
        root, lock_path = _make_lock_root(tmp_path)
        _install_fake_psutil(monkeypatch, [_FakeProc(pid=101, name="ansysedt.exe", parent=None)])
        return root, lock_path

    @staticmethod
    def _spy_terminator(monkeypatch: pytest.MonkeyPatch, record: list[int]) -> None:
        monkeypatch.setattr(
            rj, "_terminate_pid",
            lambda pid, timeout_s=rj._KILL_TIMEOUT_S: record.append(pid) or "killed")

    def test_whitelist_rejection_all_or_nothing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        root, lock_path = self._env(monkeypatch, tmp_path)
        killed: list[int] = []
        self._spy_terminator(monkeypatch, killed)
        result = janitor_clean(kill_pids=[101, 999], locks=[lock_path], dry_run=False, scan_roots=[root])
        assert result["ok"] is False
        assert any("999" in e for e in result["errors"])
        assert result["actions"] == []
        assert killed == []  # 整单拒绝零副作用
        assert Path(lock_path).exists()

    def test_dry_run_default_touches_nothing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        root, lock_path = self._env(monkeypatch, tmp_path)
        killed: list[int] = []
        self._spy_terminator(monkeypatch, killed)
        result = janitor_clean(kill_pids=[101], locks=[lock_path], scan_roots=[root])  # 缺省 dry_run=True
        assert result["ok"] is True
        assert result["summary"]["dry_run"] is True
        assert {a["result"] for a in result["actions"]} == {"would_kill", "would_remove"}
        assert killed == []
        assert Path(lock_path).exists()

    def test_execute_kills_and_removes_lock(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        root, lock_path = self._env(monkeypatch, tmp_path)
        killed: list[int] = []
        self._spy_terminator(monkeypatch, killed)
        result = janitor_clean(kill_pids=[101], locks=[lock_path], dry_run=False, scan_roots=[root])
        assert result["summary"]["n_killed"] == 1
        assert result["summary"]["n_lock_removed"] == 1
        assert killed == [101]
        assert not Path(lock_path).exists()

    def test_lock_outside_roots_rejected_file_survives(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        root, _lock = self._env(monkeypatch, tmp_path)
        other = tmp_path / "elsewhere"
        other.mkdir()
        (other / "other.lock").write_text("x", encoding="utf-8")
        result = janitor_clean(kill_pids=[], locks=[str(other / "other.lock")], dry_run=False, scan_roots=[root])
        assert result["ok"] is False
        assert (other / "other.lock").exists()

    def test_pid_reuse_guard_refuses_kill(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        root, _lock = self._env(monkeypatch, tmp_path)
        killed: list[int] = []
        self._spy_terminator(monkeypatch, killed)
        monkeypatch.setattr(rj, "_process_name", lambda pid: "chrome.exe")  # PID 已被复用
        result = janitor_clean(kill_pids=[101], locks=[], dry_run=False, scan_roots=[root])
        assert killed == []
        assert result["actions"][0]["result"] == "skipped_pid_reuse_or_unknown"

    def test_lock_directory_removed_via_rmtree(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        root.mkdir()
        (root / "proj.aedt").write_text("x", encoding="utf-8")
        lockdir = root / "proj.lock"
        lockdir.mkdir()
        (lockdir / "lockfile").write_text("x", encoding="utf-8")
        _install_fake_psutil(monkeypatch, [])
        result = janitor_clean(kill_pids=[], locks=[str(lockdir)], dry_run=False, scan_roots=[root])
        assert result["summary"]["n_lock_removed"] == 1
        assert not lockdir.exists()


# ─── lock_owner_verdict：AEDT 锁属主判定（aurora_l A2，K20/R4 P2）────────────


def _aedt_lock_text(pid: int, ips: tuple[str, ...] =
                    ("192.168.1.1", "192.168.19.1", "192.168.2.100")) -> str:
    """AEDT 锁文本（runs/ 真实样例实测格式：ASCII + CRLF + ConnectionParameters）。"""
    vector = ", ".join(f"'{ip}'" for ip in ips[1:])
    return (
        "$begin 'ConnectionParameters'\r\n"
        f"\tDesktopProcessID={pid}\r\n"
        "\tDesktopProcessPath='E:\\\\ANSYSINC\\\\ANSYS Inc\\\\v251\\\\"
        "AnsysEM\\\\ansysedt.exe'\r\n"
        "\tLaunchedByWB=false\r\n"
        "\tGRPCPort=56767\r\n"
        "\t$begin 'DesktopStubBlock'\r\n"
        "\t\t$begin 'CommDetails'\r\n"
        "\t\t\tTransportType=1\r\n"
        f"\t\t\tIPAddress='{ips[0]}'\r\n"
        "\t\t\tListenPort='56771'\r\n"
        f"\t\t\tIPAddressVector[2: {vector}]\r\n"
        "\t\t$end 'CommDetails'\r\n"
        "\t$end 'DesktopStubBlock'\r\n"
        "$end 'ConnectionParameters'\r\n"
    )


class TestLockOwnerVerdict:
    def _lock(self, tmp_path: Path, text: str | None) -> str:
        lock = tmp_path / "proj.aedt.lock"
        lock.write_text(text if text is not None else "x", encoding="utf-8")
        return str(lock)

    def test_owner_alive_pid_parsed_and_matched(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        lock = self._lock(tmp_path, _aedt_lock_text(101))
        _install_fake_psutil(
            monkeypatch, [_FakeProc(pid=101, name="ansysedt.exe", parent=None)])
        verdict = rj.lock_owner_verdict(lock, local_ips=["192.168.1.1"])
        assert verdict["verdict"] == "owner_alive"
        assert verdict["pid"] == 101
        assert "ansysedt" in (verdict["process_path"] or "")

    def test_owner_dead_when_pid_gone(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        lock = self._lock(tmp_path, _aedt_lock_text(999))
        _install_fake_psutil(monkeypatch, [])  # PID 无对应进程 = 属主已退出
        verdict = rj.lock_owner_verdict(lock, local_ips=["192.168.1.1"])
        assert verdict["verdict"] == "owner_dead"
        assert verdict["pid"] == 999

    def test_owner_dead_when_pid_reused_by_other_process(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        lock = self._lock(tmp_path, _aedt_lock_text(101))
        _install_fake_psutil(
            monkeypatch, [_FakeProc(pid=101, name="chrome.exe", parent=None)])
        verdict = rj.lock_owner_verdict(lock, local_ips=["192.168.1.1"])
        assert verdict["verdict"] == "owner_dead"  # 原属主（ansysedt）已退出

    def test_undetermined_when_no_pid_embedded(self, tmp_path: Path) -> None:
        lock = self._lock(tmp_path, "not a lock text")
        verdict = rj.lock_owner_verdict(lock, local_ips=["192.168.1.1"])
        assert verdict["verdict"] == "undetermined"
        assert verdict["pid"] is None
        assert "DesktopProcessID" in verdict["reason"]

    def test_undetermined_directory_lock(self, tmp_path: Path) -> None:
        lockdir = tmp_path / "proj.lock"
        lockdir.mkdir()
        verdict = rj.lock_owner_verdict(str(lockdir), local_ips=["192.168.1.1"])
        assert verdict["verdict"] == "undetermined"
        assert verdict["pid"] is None

    def test_undetermined_remote_lock_no_ip_overlap(self, tmp_path: Path) -> None:
        lock = self._lock(tmp_path, _aedt_lock_text(101))
        verdict = rj.lock_owner_verdict(lock, local_ips=["10.0.0.5"])
        assert verdict["verdict"] == "undetermined"
        assert "远程" in verdict["reason"]

    def test_stale_lock_beyond_horizon_passes_pid_check(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # 锁龄超窗 + IP 零交集：陈旧本机锁（网卡已漂移）放行 PID 检查判 dead
        # （runs/ 实测 8-9 月旧锁若按纯 IP 防线将永不可自动清理）
        import os
        import time as time_mod

        lock = self._lock(tmp_path, _aedt_lock_text(999))
        old = time_mod.time() - 3 * 24 * 3600
        os.utime(lock, (old, old))
        _install_fake_psutil(monkeypatch, [])  # PID 无对应进程
        verdict = rj.lock_owner_verdict(lock, local_ips=["10.0.0.5"])
        assert verdict["verdict"] == "owner_dead"
        assert "锁龄" in verdict["reason"]

    def test_old_lock_with_live_owner_still_kept(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # 锁龄超窗但属主进程仍存活 → owner_alive 恒保留（活 PID 必留）
        import os
        import time as time_mod

        lock = self._lock(tmp_path, _aedt_lock_text(101))
        old = time_mod.time() - 3 * 24 * 3600
        os.utime(lock, (old, old))
        _install_fake_psutil(
            monkeypatch, [_FakeProc(pid=101, name="ansysedt.exe", parent=None)])
        verdict = rj.lock_owner_verdict(lock, local_ips=["10.0.0.5"])
        assert verdict["verdict"] == "owner_alive"

    def test_undetermined_when_psutil_missing(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        lock = self._lock(tmp_path, _aedt_lock_text(101))
        monkeypatch.setitem(sys.modules, "psutil", None)  # import 通道断（探测+存活两路）
        verdict = rj.lock_owner_verdict(lock, local_ips=None)
        assert verdict["verdict"] == "undetermined"
        assert "psutil" in verdict["reason"]

    def test_read_limit_truncation_degrades_to_undetermined(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        lock = self._lock(tmp_path, _aedt_lock_text(101))
        monkeypatch.setattr(rj, "_LOCK_TEXT_READ_LIMIT", 8)  # 截掉 PID 行
        _install_fake_psutil(monkeypatch, [])
        verdict = rj.lock_owner_verdict(lock, local_ips=["192.168.1.1"])
        assert verdict["verdict"] == "undetermined"  # 解析不全=保守跳过，不误判 dead


# ─── CLI 三态旗标冒烟（service 面 monkeypatch，不扫真实 runs/）──────────────────────────────


class TestDoctorCliJanitor:
    runner = CliRunner()

    def test_doctor_has_janitor_flags(self) -> None:
        sig = inspect.signature(doctor)
        for name in ("janitor", "janitor_clean", "min_free_gb", "enforce"):
            assert name in sig.parameters

    def test_memory_gate_low_threshold_passes_exit0(self) -> None:
        result = self.runner.invoke(cli_app, ["doctor", "--min-free-gb", "0.000001", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["memory_gate"]["ok"] is True
        assert "scan" not in payload  # 未给 --janitor 不做扫描

    def test_memory_gate_enforce_blocks_with_nonzero_exit(self) -> None:
        result = self.runner.invoke(
            cli_app, ["doctor", "--min-free-gb", "100000000", "--json", "--enforce"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["memory_gate"]["ok"] is False

    def test_janitor_clean_alone_is_usage_error(self) -> None:
        result = self.runner.invoke(cli_app, ["doctor", "--janitor-clean", "--json"])
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["ok"] is False

    @staticmethod
    def _stub_scan() -> dict:
        return ok_envelope(
            processes=[{
                "pid": 7, "name": "ansysedt.exe", "ppid": None, "parent_alive": False,
                "parent_name": None, "create_time": None, "rss_gb": 0.78,
                "cpu_time_s": 4.0, "cmdline": None, "suspect": True,
                "suspect_reasons": ["parent_exited"],
            }],
            locks=[],
            summary={"n_processes": 1, "n_suspect": 1, "total_rss_gb": 0.78,
                     "n_locks": 0, "locks_truncated": False, "scan_roots": [],
                     "process_channel": "psutil"},
        )

    def test_janitor_scan_and_clean_flow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_clean(*, kill_pids: list[int], locks: list[str], dry_run: bool,
                       scan_roots: object = None) -> dict:
            captured.update(kill_pids=kill_pids, locks=locks, dry_run=dry_run)
            return ok_envelope(actions=[], summary={
                "dry_run": dry_run, "n_actions": 0, "n_killed": 0,
                "n_lock_removed": 0, "n_already_gone": 0, "n_failed": 0})

        monkeypatch.setattr(rj, "janitor_scan", lambda **kw: self._stub_scan())
        monkeypatch.setattr(rj, "janitor_clean", fake_clean)
        result = self.runner.invoke(cli_app, ["doctor", "--janitor", "--janitor-clean", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        # 清理只动扫描标疑的进程 + 扫到的锁，且执行态 dry_run=False
        assert captured == {"kill_pids": [7], "locks": [], "dry_run": False}
        assert payload["scan"]["summary"]["n_suspect"] == 1
        assert payload["clean"]["ok"] is True

    def test_janitor_human_report_smoke(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rj, "janitor_scan", lambda **kw: self._stub_scan())
        result = self.runner.invoke(cli_app, ["doctor", "--janitor"])
        assert result.exit_code == 0, result.output
        assert "ansysedt" in result.output
        assert "疑似孤儿" in result.output
