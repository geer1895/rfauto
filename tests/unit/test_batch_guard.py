"""批处理（-BatchSolve）看门与守卫单测（batch 看门批，全 fake 零真杀）。

覆盖四路径：正常完成 / 超时击杀（核对命令行后才杀，#245）/ 孤儿发现 /
守卫 fail-open（#105）；另钉 #145 竞态完成接受真实结果、拒杀三态
（枚举失败/pid 缺表/cmdline 不匹配）与 watchdog.py re-export 门面。

铁律：全部进程面经 monkeypatch 假体注入（_enumerate/_stop_pid/
process_alive/probe_license），绝不 spawn 真实 powershell、绝不真杀进程。
"""

from __future__ import annotations

import os

import pytest

import rfauto.pipeline.watchdog as watchdog_mod
from rfauto.infra.license_probe import LICENSE_ENV_VARS
from rfauto.pipeline import batch_guard
from rfauto.pipeline.batch_guard import (
    BatchSolveWatchdog,
    GuardResult,
    ProcessInfo,
    WatchResult,
    _sanitize_pattern,
    assert_license_headroom,
    assert_ram_headroom,
    find_batch_processes,
    find_orphan_batch_processes,
    kill_process_tree,
)
from rfauto.pipeline.watchdog import Watchdog as _LegacyWatchdog

# ---------------------------------------------------------------------------
# 假体
# ---------------------------------------------------------------------------


class _FakeHandle:
    """Popen 风句柄假体：poll 按 Script 序列出码，None=仍在跑。"""

    def __init__(self, poll_sequence, pid: int = 4242, args=None):
        self._seq = list(poll_sequence)
        self.pid = pid
        self.args = args

    def poll(self):
        if not self._seq:
            return None
        return self._seq.pop(0)


_ANSYSEDT_CMDLINE = '"C:\\ANSYS Inc\\v251\\ansysedt.exe" -ng -BatchSolve run1'


def _fake_table(_pattern: str | None = None) -> list[ProcessInfo]:
    """全表假体：_enumerate 两种调用形态（按名过滤/全表）都接。"""
    return [
        ProcessInfo(pid=4242, name="ansysedt.exe", ppid=os.getpid(),
                    cmdline=_ANSYSEDT_CMDLINE),
        ProcessInfo(pid=4300, name="ansysedt.exe", ppid=4242,
                    cmdline=_ANSYSEDT_CMDLINE + " -worker"),
        ProcessInfo(pid=4400, name="notepad.exe", ppid=4242,
                    cmdline="notepad.exe /untouched"),
        ProcessInfo(pid=4500, name="explorer.exe", ppid=301,
                    cmdline="C:\\Windows\\explorer.exe"),
    ]


@pytest.fixture()
def stop_recorder(monkeypatch):
    """_stop_pid 假体：记录被点杀的 pid，恒成功。"""
    stops: list[int] = []

    def _fake_stop(pid: int) -> bool:
        stops.append(int(pid))
        return True

    monkeypatch.setattr(batch_guard, "_stop_pid", _fake_stop)
    return stops


# ---------------------------------------------------------------------------
# BatchSolveWatchdog：正常完成 + #145 竞态
# ---------------------------------------------------------------------------


class TestWatchNormalCompletion:
    def test_completes_without_kill(self, monkeypatch, stop_recorder):
        monkeypatch.setattr(batch_guard, "_enumerate", _fake_table)
        wd = BatchSolveWatchdog(timeout_s=5.0, poll_interval_s=0.01)
        result = wd.watch(_FakeHandle([0], pid=4242))
        assert isinstance(result, WatchResult)
        assert result.timed_out is False
        assert result.killed is False
        assert result.returncode == 0
        assert stop_recorder == [], "正常完成绝不触发击杀"

    def test_race_completion_accepted_over_timeout(self, stop_recorder):
        """#145：deadline 附近先探完成、后判超时——竞态完成接受真实结果。"""
        # timeout=0.05s、poll=0.03s：第 3 次 poll 落在 deadline 后，
        # 但出码非 None → 必须按完成处理（rc 优先于超时判定）。
        wd = BatchSolveWatchdog(timeout_s=0.05, poll_interval_s=0.03)
        result = wd.watch(_FakeHandle([None, None, 3], pid=4242))
        assert result.timed_out is False
        assert result.returncode == 3
        assert stop_recorder == []


# ---------------------------------------------------------------------------
# BatchSolveWatchdog：超时击杀（核对命令行后才杀）
# ---------------------------------------------------------------------------


class TestWatchTimeoutKill:
    def test_timeout_kills_verified_tree_leaf_first(self, monkeypatch,
                                                    stop_recorder):
        monkeypatch.setattr(batch_guard, "_enumerate", _fake_table)
        handle = _FakeHandle(
            [None], pid=4242,
            args=["C:\\ANSYS Inc\\v251\\ansysedt.exe", "-ng", "-BatchSolve"])
        wd = BatchSolveWatchdog(timeout_s=0.08, poll_interval_s=0.01)
        result = wd.watch(handle, on_timeout="kill")

        assert result.timed_out is True
        assert result.killed is True
        assert result.returncode is None
        # 核对串取自 handle.args[0] 映像名（小写化）
        # 后代先叶后根：匹配核对串的 4300 先杀、根 4242 后杀；
        # notepad 4400 虽是后代但 cmdline 不含核对串 → 跳过（防连坐 #157）。
        assert stop_recorder == [4300, 4242]

    def test_timeout_refuses_on_cmdline_mismatch(self, monkeypatch,
                                                 stop_recorder):
        """pid 回收/句柄漂移：核对串不在 cmdline → 拒杀（#245 不盲杀）。"""
        monkeypatch.setattr(batch_guard, "_enumerate", _fake_table)
        handle = _FakeHandle([None], pid=4242,
                             args=["C:\\other\\solver.exe", "-run"])
        wd = BatchSolveWatchdog(timeout_s=0.05, poll_interval_s=0.01)
        result = wd.watch(handle, on_timeout="kill")
        assert result.timed_out is True
        assert result.killed is False
        assert stop_recorder == [], "核对失败必须零击杀"

    def test_timeout_refuses_when_enumeration_fails(self, monkeypatch,
                                                    stop_recorder):
        """枚举失败=未知态 → 拒杀（#245 fail-closed），看门不炸主路径。"""
        def _boom(pattern):
            raise RuntimeError("enumeration timeout (E3-8)")

        monkeypatch.setattr(batch_guard, "_enumerate", _boom)
        handle = _FakeHandle([None], pid=4242, args=["ansysedt.exe"])
        wd = BatchSolveWatchdog(timeout_s=0.05, poll_interval_s=0.01)
        result = wd.watch(handle, on_timeout="kill")
        assert result.timed_out is True
        assert result.killed is False
        assert stop_recorder == []

    def test_record_mode_does_not_kill(self, monkeypatch, stop_recorder):
        monkeypatch.setattr(batch_guard, "_enumerate", _fake_table)
        wd = BatchSolveWatchdog(timeout_s=0.05, poll_interval_s=0.01)
        result = wd.watch(_FakeHandle([None], pid=4242,
                                      args=["ansysedt.exe", "-ng"]),
                          on_timeout="record")
        assert result.timed_out is True
        assert result.killed is False
        assert "no kill" in result.detail
        assert stop_recorder == []

    def test_invalid_on_timeout_raises(self):
        wd = BatchSolveWatchdog(timeout_s=1.0, poll_interval_s=0.01)
        with pytest.raises(ValueError, match="on_timeout"):
            wd.watch(_FakeHandle([None]), on_timeout="explode")

    def test_init_rejects_nonpositive_timeouts(self):
        with pytest.raises(ValueError, match="timeout_s"):
            BatchSolveWatchdog(timeout_s=0.0)
        with pytest.raises(ValueError, match="poll_interval_s"):
            BatchSolveWatchdog(timeout_s=1.0, poll_interval_s=-1.0)


# ---------------------------------------------------------------------------
# 进程枚举 / 孤儿发现
# ---------------------------------------------------------------------------


class TestEnumerationAndOrphans:
    def test_find_batch_processes_filters_by_name_case_insensitive(
            self, monkeypatch):
        monkeypatch.setattr(batch_guard, "_enumerate", _fake_table)
        found = find_batch_processes("ansysedt")
        assert [p.pid for p in found] == [4242, 4300]
        assert all("ansysedt" in (p.name or "").lower() for p in found)
        assert found[0].cmdline == _ANSYSEDT_CMDLINE

    def test_find_batch_processes_raises_on_enumeration_failure(
            self, monkeypatch):
        """fail-closed：枚举失败抛错，勿静默返回空列表（#245 家族口径）。"""
        def _boom(pattern):
            raise RuntimeError("rc=1")

        monkeypatch.setattr(batch_guard, "_enumerate", _boom)
        with pytest.raises(RuntimeError, match="rc=1"):
            find_batch_processes("ansysedt")

    def test_find_orphans_by_dead_or_zero_ppid(self, monkeypatch):
        table = [
            ProcessInfo(pid=10, name="ansysedt.exe", ppid=999),   # 999 不在表 → 孤
            ProcessInfo(pid=11, name="ansysedt.exe", ppid=os.getpid()),  # 活父（见下）→ 非孤
            ProcessInfo(pid=12, name="ansysedt.exe", ppid=0),     # ppid=0 → 孤
            ProcessInfo(pid=13, name="ansysedt.exe", ppid=None),  # 未知 → 保守非孤
            ProcessInfo(pid=14, name="notepad.exe", ppid=1),      # 不匹配 pattern
            ProcessInfo(pid=os.getpid(), name="python.exe", ppid=301),  # 活父本体
        ]
        monkeypatch.setattr(batch_guard, "_enumerate", lambda _pat: table)
        orphans = find_orphan_batch_processes("ansysedt")
        assert [p.pid for p in orphans] == [10, 12]

    def test_sanitize_pattern_strips_quotes(self):
        assert _sanitize_pattern("an'sy\"sedt ") == "ansysedt"


# ---------------------------------------------------------------------------
# kill_process_tree 拒杀三态与降级复核
# ---------------------------------------------------------------------------


class TestKillProcessTree:
    def test_refuses_when_pid_absent_from_table(self, monkeypatch,
                                                stop_recorder):
        monkeypatch.setattr(batch_guard, "_enumerate", _fake_table)
        assert kill_process_tree(9999) is False
        assert stop_recorder == []

    def test_refuses_on_enumeration_failure(self, monkeypatch, stop_recorder):
        def _boom(_pat):
            raise RuntimeError("unparsable output")

        monkeypatch.setattr(batch_guard, "_enumerate", _boom)
        assert kill_process_tree(4242, verify_cmdline_substr="ansysedt") is False
        assert stop_recorder == []

    def test_no_verification_kills_whole_subtree(self, monkeypatch,
                                                 stop_recorder):
        """verify=None（调用方已凭 Popen.pid 归属确权）→ 全后代+根。

        BFS 后代序 [4300, 4400]，先叶后根反转 → 4400 → 4300 → 根 4242。
        """
        monkeypatch.setattr(batch_guard, "_enumerate", _fake_table)
        assert kill_process_tree(4242) is True
        assert stop_recorder == [4400, 4300, 4242]

    def test_root_stop_failure_confirmed_dead_counts_as_released(
            self, monkeypatch):
        """点杀失败但存活复核=已退出 → 席位已释放，按成功口径返回 True。"""
        monkeypatch.setattr(batch_guard, "_enumerate", _fake_table)
        monkeypatch.setattr(batch_guard, "_stop_pid", lambda _pid: False)
        monkeypatch.setattr(batch_guard.desktop_guard, "process_alive",
                            lambda _pid: False)
        assert kill_process_tree(4242) is True

    def test_descendant_cmdline_mismatch_skipped_only(self, monkeypatch,
                                                      stop_recorder):
        monkeypatch.setattr(batch_guard, "_enumerate", _fake_table)
        assert kill_process_tree(4242, verify_cmdline_substr="ansysedt") is True
        assert stop_recorder == [4300, 4242], "notepad 后代必须被核对串拦下"


# ---------------------------------------------------------------------------
# 许可证席位预检（fail-open 三路 + 唯一硬信号）
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_license_env(monkeypatch):
    """清空 license_probe 消费的整个环境变量集合（#142 家族口径）。"""
    for var in LICENSE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


class TestLicenseHeadroom:
    def test_fail_open_when_no_server_configured(self, _clean_license_env):
        """本机/节点锁假设：无 server 可探测 → 放行 + fail_open 标记。"""
        result = assert_license_headroom(min_free=1)
        assert isinstance(result, GuardResult)
        assert result.ok is True
        assert result.fail_open is True
        assert result.status == "no_server"
        assert result.min_free == 1

    def test_fail_open_when_probe_raises(self, monkeypatch,
                                         _clean_license_env):
        """探测异常绝不进主路径（#105 双保险）：放行 + status=error。"""
        def _boom():
            raise RuntimeError("socket exploded")

        monkeypatch.setattr(batch_guard, "probe_license", _boom)
        result = assert_license_headroom()
        assert result.ok is True
        assert result.fail_open is True
        assert result.status == "error"
        assert "socket exploded" in result.detail

    def test_fail_open_when_reachable_but_seats_unverifiable(self,
                                                             monkeypatch):
        monkeypatch.setattr(
            batch_guard, "probe_license",
            lambda: {"available": True, "server": "lic.example:1055",
                     "detail": "tcp reachable"})
        result = assert_license_headroom(min_free=2)
        assert result.ok is True
        assert result.fail_open is True
        assert result.status == "reachable"
        assert result.min_free == 2
        assert "not queryable" in result.detail

    def test_hard_negative_when_server_unreachable(self, monkeypatch):
        """唯一硬信号：server 已配置且确认不可达 → ok=False（调用方决策）。"""
        monkeypatch.setattr(
            batch_guard, "probe_license",
            lambda: {"available": False, "server": "10.255.255.1:1055",
                     "detail": "connection refused"})
        result = assert_license_headroom()
        assert result.ok is False
        assert result.fail_open is False
        assert result.status == "unreachable"


# ---------------------------------------------------------------------------
# RAM 余量预检（W10 事故形态；fail-skip / fail-open 双语义 + 阈值边界）
# ---------------------------------------------------------------------------


class TestRamHeadroom:
    """全 fake：只 patch 双通道查询函数，绝不真查内存、绝不 spawn powershell。"""

    def test_sufficient_ram_passes_confirmed(self, monkeypatch):
        """充足：psutil 通道 62.5% >= 15% → ok=True 且 fail_open=False。"""
        wmi_calls: list[int] = []

        def _fake_wmi() -> float | None:
            wmi_calls.append(1)
            return 99.0

        monkeypatch.setattr(batch_guard, "_query_free_ram_pct_psutil", lambda: 62.5)
        monkeypatch.setattr(batch_guard, "_query_free_ram_pct_wmi", _fake_wmi)
        result = assert_ram_headroom(min_free_pct=15.0)
        assert isinstance(result, GuardResult)
        assert result.ok is True
        assert result.fail_open is False
        assert result.status == "sufficient"
        assert "62.5" in result.detail
        assert "psutil" in result.detail
        assert wmi_calls == [], "psutil 命中后不得再触 WMI 兜底"

    def test_insufficient_ram_is_fail_skip(self, monkeypatch):
        """不足：8.3% < 15% → ok=False（fail-skip，调用方决定延后发射）。"""
        monkeypatch.setattr(batch_guard, "_query_free_ram_pct_psutil", lambda: 8.3)
        result = assert_ram_headroom()
        assert result.ok is False
        assert result.fail_open is False, "已确证的不足是硬信号非 fail-open"
        assert result.status == "insufficient"
        assert "8.3" in result.detail
        assert "15" in result.detail

    def test_query_failure_fails_open(self, monkeypatch):
        """查不到：psutil 缺席 + WMI 抛异常 → ok=True+fail_open=True（#105）。"""

        def _boom() -> float | None:
            raise RuntimeError("wmi exploded")

        monkeypatch.setattr(batch_guard, "_query_free_ram_pct_psutil", lambda: None)
        monkeypatch.setattr(batch_guard, "_query_free_ram_pct_wmi", _boom)
        result = assert_ram_headroom(min_free_pct=15.0)
        assert result.ok is True
        assert result.fail_open is True
        assert result.status == "error"
        assert "wmi exploded" in result.detail
        assert "fail-open" in result.detail

    def test_threshold_boundary_exact_passes_just_below_fails(self, monkeypatch):
        """阈值边界：恰等于阈值=达标放行（严格小于才拦）。"""
        monkeypatch.setattr(batch_guard, "_query_free_ram_pct_psutil", lambda: 15.0)
        result = assert_ram_headroom(min_free_pct=15.0)
        assert result.ok is True
        assert result.status == "sufficient"

        monkeypatch.setattr(batch_guard, "_query_free_ram_pct_psutil", lambda: 14.999)
        below = assert_ram_headroom(min_free_pct=15.0)
        assert below.ok is False
        assert below.status == "insufficient"

    def test_nonfinite_threshold_fails_open_not_fake_confirm(self, monkeypatch):
        """非有限阈值：NaN 侧 pct<NaN 恒 False 会产出假 confirmed
        sufficient（fail_open=False 的诚实性破口）——按"无法确证"走
        fail-open（ok=True+fail_open=True+status=error，#105 不抛）。"""
        monkeypatch.setattr(batch_guard, "_query_free_ram_pct_psutil",
                            lambda: 1.0)  # 低内存：若误比较会假 sufficient
        for bad in (float("nan"), float("inf"), float("-inf")):
            result = assert_ram_headroom(min_free_pct=bad)
            assert result.ok is True, f"非有限阈值 {bad!r} 仍须放行（#105）"
            assert result.fail_open is True, \
                f"非有限阈值 {bad!r} 不得冒充已确证裁决"
            assert result.status == "error"
            assert "non-finite" in result.detail


# ---------------------------------------------------------------------------
# watchdog.py 门面：re-export 存在 + 既有 Watchdog 语义零变化
# ---------------------------------------------------------------------------


class TestWatchdogModuleFacade:
    def test_batch_guard_reexported_from_watchdog(self):
        assert watchdog_mod.BatchSolveWatchdog is BatchSolveWatchdog
        assert watchdog_mod.WatchResult is WatchResult
        assert watchdog_mod.ProcessInfo is ProcessInfo
        assert watchdog_mod.GuardResult is GuardResult
        assert watchdog_mod.kill_process_tree is kill_process_tree
        assert watchdog_mod.find_batch_processes is find_batch_processes
        assert (watchdog_mod.find_orphan_batch_processes
                is find_orphan_batch_processes)
        assert (watchdog_mod.assert_license_headroom
                is assert_license_headroom)
        assert (watchdog_mod.assert_ram_headroom is assert_ram_headroom)

    def test_watchdog_module_has_no_all_public_api_snapshot_untouched(self):
        """两文件都不得定义 __all__（public_api 金快照按 __all__ 收录）。"""
        assert not hasattr(watchdog_mod, "__all__")
        assert not hasattr(batch_guard, "__all__")

    def test_legacy_watchdog_api_unchanged(self):
        """既有 Watchdog start/cancel/fired 冒烟（纯追加不破坏既有语义）。"""
        wd = _LegacyWatchdog()
        fired: list[bool] = []
        wd.start(timeout_s=10.0, callback=lambda: fired.append(True))
        assert wd.fired is False
        wd.cancel()
        wd.reset()  # cancel 后 reset 无 callback 时静默不炸
        assert fired == []
