"""campaign_wait_launch.py 守望者心跳/自尽/单实例守卫的钉子测试（df7）。

纯函数面（心跳读写/过期判定/自尽决策/单实例判定/父心跳超时）逐个钉；
main() 集成路径用 monkeypatch 钉住 time/memory/subprocess，禁真等内存门
（#144 家族：优化循环类测试必须隔离，不得污染真实 runs/——心跳文件一律
写 tmp_path，缺省路径仅由 --heartbeat 显式重定向后触达）。

零变化钉：既有内存门语义（exit 2 超时优先/门开发射/降级串行）与缺省
调用路径不变——缺省 flags 下不触发 exit 3/4/5 任何新路。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "campaign_wait_launch.py"
_SPEC = importlib.util.spec_from_file_location("campaign_wait_launch", _SCRIPT)
wl = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wl)


# ── 心跳写/读 ────────────────────────────────────────────────────────────────

def test_write_then_read_heartbeat_roundtrip(tmp_path: Path):
    hb = tmp_path / "hb.json"
    payload = {"pid": 123, "start_ts": 1.0, "last_poll_ts": 2.0,
               "waited_h": 0.5, "poll_s": 600,
               "gate": {"free_kb": 1, "need_kb": 2, "workers": 2, "open": False}}
    assert wl.write_heartbeat(hb, payload) is True
    assert wl.read_heartbeat(hb) == payload


def test_write_heartbeat_leaves_no_tmp_file(tmp_path: Path):
    hb = tmp_path / "hb.json"
    assert wl.write_heartbeat(hb, {"pid": 1})
    assert list(tmp_path.iterdir()) == [hb], "原子写不得残留临时文件"


def test_write_heartbeat_failure_returns_false_and_cleans_tmp(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    hb = tmp_path / "hb.json"

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    assert wl.write_heartbeat(hb, {"pid": 1}) is False
    assert list(tmp_path.iterdir()) == [], "失败路径也要清掉临时文件"


def test_write_heartbeat_bad_parent_dir_returns_false(tmp_path: Path):
    not_a_dir = tmp_path / "plain.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    hb = not_a_dir / "hb.json"  # 父路径是普通文件 → mkdir 必败
    assert wl.write_heartbeat(hb, {"pid": 1}) is False


def test_read_heartbeat_missing_or_corrupt_returns_none(tmp_path: Path):
    assert wl.read_heartbeat(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert wl.read_heartbeat(bad) is None
    nonobj = tmp_path / "arr.json"
    nonobj.write_text("[1,2]", encoding="utf-8")
    assert wl.read_heartbeat(nonobj) is None, "非 dict 视为无主"


# ── staleness / 单实例 / 自尽 / 父心跳（纯函数） ─────────────────────────────

def test_heartbeat_stale_semantics():
    now = 1000.0
    fresh = {"last_poll_ts": now - 10}
    assert wl.heartbeat_stale(fresh, now, 60.0) is False
    assert wl.heartbeat_stale({"last_poll_ts": now - 61}, now, 60.0) is True
    # 边界：恰好等于 max_age 不算超龄（> 判定）
    assert wl.heartbeat_stale({"last_poll_ts": now - 60}, now, 60.0) is False
    for bad in (None, "x", 42, {}, {"last_poll_ts": "abc"},
                {"last_poll_ts": None}, {"last_poll_ts": True}):
        assert wl.heartbeat_stale(bad, now, 60.0) is True, f"bad={bad!r}"


def test_pid_alive_current_process_true_and_invalid_false():
    assert wl.pid_alive(os.getpid()) is True
    for bad in (None, 0, -1, "abc", ""):
        assert wl.pid_alive(bad) is False, f"bad={bad!r}"


def test_pid_alive_terminated_subprocess_false():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert wl.pid_alive(proc.pid) is False


def test_single_instance_conflict_active_heartbeat_blocks():
    now = time.time()
    hb = {"pid": os.getpid(), "last_poll_ts": now - 5, "poll_s": 600}
    conflict, reason = wl.single_instance_conflict(hb, now, 600)
    assert conflict is True
    assert str(os.getpid()) in reason


def test_single_instance_conflict_stale_or_dead_or_missing_passes():
    now = time.time()
    assert wl.single_instance_conflict(None, now, 600) == (False, "")
    assert wl.single_instance_conflict({}, now, 600) == (False, "")
    # 过期（> 2×轮询周期）→ 无主遗痕不阻塞
    stale = {"pid": os.getpid(), "last_poll_ts": now - 1201, "poll_s": 600}
    assert wl.single_instance_conflict(stale, now, 600) == (False, "")
    # 新鲜但 pid 已死 → 不阻塞
    dead = {"pid": 999999999, "last_poll_ts": now - 5, "poll_s": 600}
    assert wl.single_instance_conflict(dead, now, 600)[0] is False


def test_single_instance_conflict_window_takes_max_of_both_polls():
    # 心跳自报 poll_s=600 大于新实例 poll_s=10：新鲜度窗=2×600，
    # 距今 100s 仍算活跃（防新实例用小轮询周期把旧活跃实例误判过期→双发）。
    now = time.time()
    hb = {"pid": os.getpid(), "last_poll_ts": now - 100, "poll_s": 600}
    conflict, _ = wl.single_instance_conflict(hb, now, 10)
    assert conflict is True


def test_heartbeat_self_terminate_threshold():
    assert wl.heartbeat_self_terminate(2, 3) is False
    assert wl.heartbeat_self_terminate(3, 3) is True
    assert wl.heartbeat_self_terminate(9, 3) is True
    assert wl.heartbeat_self_terminate(99, 0) is False, "0=关闭该路自尽"


def test_parent_heartbeat_timed_out_semantics(tmp_path: Path):
    parent = tmp_path / "parent.touch"
    parent.write_text("", encoding="utf-8")
    now = time.time()
    # 新鲜 touch → 不超时
    os.utime(parent, (now - 10, now - 10))
    assert wl.parent_heartbeat_timed_out(parent, now, 900.0, now - 10) is False
    # 陈旧 touch → 超时
    os.utime(parent, (now - 901, now - 901))
    assert wl.parent_heartbeat_timed_out(parent, now, 900.0, now) is True
    # 文件从未出现：以 start_ts 为基准
    missing = tmp_path / "never.touch"
    assert wl.parent_heartbeat_timed_out(
        missing, now, 900.0, now - 10) is False
    assert wl.parent_heartbeat_timed_out(
        missing, now, 900.0, now - 901) is True


# ── main() 集成（monkeypatch 钉 time/memory/subprocess，禁真等） ────────────

def test_main_launch_path_zero_change_gate_open_launches(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """缺省调用路径零变化钉：门开→发射→子进程码透传；心跳是纯增量观测面
    （写成功、gate.open=True），不改变发射决策/退出码。"""
    monkeypatch.setattr(wl, "free_physical_memory_kb",
                        lambda: 8 * 1024 * 1024)
    hb = tmp_path / "hb.json"
    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "argv",
                        ["campaign_wait_launch.py", "--heartbeat", str(hb),
                         "--poll-s", "1"])
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(subprocess, "call",
                        lambda cmd: (calls.append(cmd), 42)[1])
    rc = wl.main()
    assert rc == 42, "发射路径必须透传子进程码（与旧实现一致）"
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[1].endswith("calibration_campaign.py")
    assert cmd[cmd.index("--n-workers") + 1] == "2", "内存充足不降级 workers"
    payload = wl.read_heartbeat(hb)
    assert payload is not None
    assert payload["pid"] == os.getpid()
    assert payload["gate"]["open"] is True
    assert payload["gate"]["workers"] == 2


def test_main_timeout_exit2_unchanged_before_any_probe(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """exit 2 超时语义与位置不变：max-wait-hours=0 时立即交还人，
    不做内存探测（原实现即如此）。"""
    probed: list[int] = []

    def fake_probe():
        probed.append(1)
        return 0

    monkeypatch.setattr(wl, "free_physical_memory_kb", fake_probe)
    monkeypatch.setattr(sys, "argv",
                        ["campaign_wait_launch.py",
                         "--heartbeat", str(tmp_path / "hb.json"),
                         "--poll-s", "1", "--max-wait-hours", "0"])
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert wl.main() == 2
    assert probed == [], "超时检查必须先于内存探测（零变化钉）"


def test_main_exit3_after_consecutive_heartbeat_write_failures(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """心跳写连续失败 ≥ 阈值 → exit 3 不发射（发射器从未被调用）。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "argv",
                        ["campaign_wait_launch.py",
                         "--heartbeat", str(tmp_path / "hb.json"),
                         "--poll-s", "1",
                         "--heartbeat-max-write-failures", "3"])
    monkeypatch.setattr(wl, "free_physical_memory_kb", lambda: 0)
    monkeypatch.setattr(wl, "write_heartbeat", lambda p, d: False)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(subprocess, "call",
                        lambda cmd: (calls.append(cmd), 0)[1])
    assert wl.main() == 3
    assert calls == [], "自尽路径不得发射"


def test_main_exit4_parent_dead_blocks_launch_even_when_gate_open(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """父会话心跳超时 → exit 4 不发射；内存门开着也不许盲发（先父亡后发射）。"""
    parent = tmp_path / "parent.touch"
    parent.write_text("", encoding="utf-8")
    old = time.time() - 3600
    os.utime(parent, (old, old))
    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "argv",
                        ["campaign_wait_launch.py",
                         "--heartbeat", str(tmp_path / "hb.json"),
                         "--poll-s", "1",
                         "--parent-heartbeat", str(parent),
                         "--parent-heartbeat-timeout-s", "900"])
    monkeypatch.setattr(wl, "free_physical_memory_kb",
                        lambda: 8 * 1024 * 1024)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(subprocess, "call",
                        lambda cmd: (calls.append(cmd), 0)[1])
    assert wl.main() == 4
    assert calls == [], "父亡必须先于发射决策拦截"


def test_main_exit4_missing_parent_file_uses_start_ts_baseline(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """父心跳文件从未出现：start_ts 起算超时（父死了从未 touch 不永久空等）。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "argv",
                        ["campaign_wait_launch.py",
                         "--heartbeat", str(tmp_path / "hb.json"),
                         "--poll-s", "1",
                         "--parent-heartbeat",
                         str(tmp_path / "never.touch"),
                         "--parent-heartbeat-timeout-s", "0"])
    monkeypatch.setattr(wl, "free_physical_memory_kb", lambda: 0)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(subprocess, "call",
                        lambda cmd: (calls.append(cmd), 0)[1])
    assert wl.main() == 4
    assert calls == []


def test_main_exit5_refuses_when_active_launcher_heartbeat_present(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """单实例守卫：活跃心跳（新鲜+pid 存活）→ exit 5 拒绝双发，
    不进入主循环（不探测内存/不写自己的心跳）。"""
    hb = tmp_path / "hb.json"
    wl.write_heartbeat(hb, {"pid": os.getpid(),
                            "last_poll_ts": time.time(),
                            "poll_s": 600})
    probed: list[int] = []

    def fake_probe():
        probed.append(1)
        return 0

    monkeypatch.setattr(wl, "free_physical_memory_kb", fake_probe)
    monkeypatch.setattr(sys, "argv",
                        ["campaign_wait_launch.py", "--heartbeat", str(hb),
                         "--poll-s", "1"])
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert wl.main() == 5
    assert probed == [], "守卫必须在主循环之前拒绝"
    # 自己的心跳未被覆盖（仍是原 last_poll_ts）
    assert wl.read_heartbeat(hb)["pid"] == os.getpid()


def test_main_exit5_stale_heartbeat_does_not_block(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """无主遗痕（过期心跳）不阻塞新实例——#177 清点面语义：
    过期/死 pid 心跳是证据不是障碍。到达等待循环（2 轮 sleep）本身即证明
    守卫未以 exit 5 拦截。"""
    hb = tmp_path / "hb.json"
    wl.write_heartbeat(hb, {"pid": 999999999,
                            "last_poll_ts": time.time() - 10_000,
                            "poll_s": 600})
    monkeypatch.setattr(sys, "argv",
                        ["campaign_wait_launch.py", "--heartbeat", str(hb),
                         "--poll-s", "1"])
    monkeypatch.setattr(wl, "free_physical_memory_kb", lambda: 0)
    sleeps: list[float] = []

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", fake_sleep)
    with pytest.raises(KeyboardInterrupt):
        wl.main()
    assert len(sleeps) == 2, "进入等待循环=过期心跳未触发 exit 5"


def test_main_heartbeat_disabled_by_empty_flag(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--heartbeat ''（显式关闭）：不写心跳文件，其余行为不变（等待循环）。"""
    monkeypatch.setattr(sys, "argv",
                        ["campaign_wait_launch.py", "--heartbeat", "",
                         "--poll-s", "1"])
    monkeypatch.setattr(wl, "free_physical_memory_kb", lambda: 0)
    sleeps: list[float] = []

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 2:
            raise KeyboardInterrupt  # 打断死循环（free=0 永不达门）

    monkeypatch.setattr(time, "sleep", fake_sleep)
    with pytest.raises(KeyboardInterrupt):
        wl.main()
    assert len(sleeps) == 2
    assert not (tmp_path / "hb.json").exists()


def test_main_default_flags_take_no_new_exit_paths(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """缺省 flags（无 --parent-heartbeat、心跳可写）下 exit 3/4/5 三新路
    全不触发：free=0 走等待循环（KeyboardInterrupt 打断）= 旧行为。"""
    hb = tmp_path / "hb.json"
    monkeypatch.setattr(sys, "argv",
                        ["campaign_wait_launch.py", "--heartbeat", str(hb),
                         "--poll-s", "1"])
    monkeypatch.setattr(wl, "free_physical_memory_kb", lambda: 0)
    sleeps: list[float] = []

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", fake_sleep)
    with pytest.raises(KeyboardInterrupt):
        wl.main()
    assert len(sleeps) == 2, "两轮探测-等待（旧行为）"
    payload = wl.read_heartbeat(hb)
    assert payload is not None and payload["gate"]["open"] is False
    assert payload["parent_heartbeat"] == ""
