"""siw_anchor_smoke.py 共享锁面单测（round6 A3-⑦ / L-E5 裁定；全离线）。

被测对象：scripts/siw_anchor_smoke.py 的 lock_acquire/lock_release——
runs/.oe_collect.lock O_CREAT|O_EXCL 原子占锁（对同锁面消费者无 TOCTOU）、
stale 持有进程接管、忙等超时拒跑、释放幂等。锁路径 monkeypatch 到
tmp_path，零真跑、零 PowerShell（_pid_alive 一并 stub）。
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "siw_anchor_smoke.py"


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("_siw_anchor_lock", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LOCK_PATH", tmp_path / "t.lock")
    return mod


def _write_lock(path: Path, pid: int, task: str = "other_task") -> None:
    path.write_text(json.dumps({"pid": pid, "task": task, "ts": "T"}),
                    encoding="utf-8")


def test_acquire_free_and_release_idempotent(mod):
    res = mod.lock_acquire(timeout_s=1.0)
    assert res["acquired"] is True and res["owner"] is None
    data = json.loads(mod.LOCK_PATH.read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid()
    assert data["task"] == "siw_anchor_smoke"
    mod.lock_release()
    assert not mod.LOCK_PATH.exists()
    mod.lock_release()  # 幂等：二次释放不抛


def test_acquire_busy_alive_owner_times_out(mod, monkeypatch):
    _write_lock(mod.LOCK_PATH, pid=12345)
    monkeypatch.setattr(mod, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(mod, "LOCK_POLL_S", 0.01)  # 忙等轮询 stub（勿真睡 30s）
    res = mod.lock_acquire(timeout_s=0.2)
    assert res["acquired"] is False
    assert res["owner"] == {"pid": 12345, "task": "other_task", "ts": "T"}
    assert mod.LOCK_PATH.exists()  # 不误删他轨活锁


def test_acquire_takes_over_stale_lock(mod, monkeypatch):
    _write_lock(mod.LOCK_PATH, pid=999999)
    monkeypatch.setattr(mod, "_pid_alive", lambda pid: False)
    res = mod.lock_acquire(timeout_s=5.0)
    assert res["acquired"] is True
    assert res["owner"] is None  # 接管后 owner=本次占锁（None=无等待）
    data = json.loads(mod.LOCK_PATH.read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid() and data["task"] == "siw_anchor_smoke"


def test_acquire_corrupt_lock_waits_not_crashes(mod, monkeypatch):
    # 锁文件损坏（空文件）：owner=None → 不接管（保守），走忙等超时拒跑
    mod.LOCK_PATH.write_text("", encoding="utf-8")
    monkeypatch.setattr(mod, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(mod, "LOCK_POLL_S", 0.01)
    res = mod.lock_acquire(timeout_s=0.2)
    assert res["acquired"] is False
    assert res["owner"] is None
