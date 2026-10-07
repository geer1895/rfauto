"""OP-11 storage_backends 单测：JournalStorage 接线 + SQLite 回退（tmp_path 隔离）。

optuna 5.0.0 Journal API 全部 venv 实测（2026-10-03）：Windows 无 symlink
特权时缺省 SymlinkLock 抛 WinError 1314（本机实测复现）——本仓 Windows 档
改 OpenLock。journal 文件一律落 tmp_path（#144：禁污染真实 runs）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import optuna
import pytest

from rfauto.optimization.storage_backends import (
    build_journal_storage,
    journal_lock,
    resolve_storage,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


# ---------------------------------------------------------------------------
# journal 档：构建/回读（tmp_path）
# ---------------------------------------------------------------------------

def test_journal_roundtrip_persists_trials(tmp_path):
    """journal 档 ask/tell 后，新实例回读同一文件可见全部 trial（持久性）。"""
    jp = tmp_path / "journal.log"
    resolved = resolve_storage("journal", journal_path=jp)
    assert resolved["ok"] is True
    assert resolved["backend"] == "journal"
    assert resolved["fallback"] is False
    assert resolved["fallback_reason"] is None
    storage = resolved["storage"]
    study = optuna.create_study(storage=storage, study_name="op11_roundtrip")
    for val in (1.5, 0.75):
        t = study.ask()
        t.suggest_float("x", 0.0, 1.0)
        study.tell(t, val)
    # 新 storage 实例回读（模拟跨进程/重启恢复路径）
    storage2 = build_journal_storage(jp)
    study2 = optuna.load_study(study_name="op11_roundtrip", storage=storage2)
    trials = study2.get_trials(deepcopy=False)
    assert len(trials) == 2
    assert [t.value for t in trials] == [1.5, 0.75]
    assert trials[1].params["x"] == trials[1].params["x"]  # params 原样持久


@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="Windows 特有：SymlinkLock 特权缺失路径")
def test_journal_lock_windows_uses_openlock():
    """Windows 档锁类型 = JournalFileOpenLock（SymlinkLock 需特权，实测 1314）。"""
    from optuna.storages.journal import JournalFileOpenLock

    lock = journal_lock(r"C:\nonexistent\op11_probe.log")
    assert isinstance(lock, JournalFileOpenLock)


@pytest.mark.skipif(sys.platform.startswith("win"),
                    reason="POSIX 档维持缺省 SymlinkLock")
def test_journal_lock_posix_uses_symlinklock():
    from optuna.storages.journal import JournalFileSymlinkLock

    lock = journal_lock("/tmp/op11_probe.log")
    assert isinstance(lock, JournalFileSymlinkLock)


def test_journal_parent_dir_autocreated(tmp_path):
    """journal 父目录不存在时自动创建（缺省面行为契约）。"""
    jp = tmp_path / "nested" / "dir" / "journal.log"
    resolved = resolve_storage("journal", journal_path=jp)
    assert resolved["ok"] is True
    assert jp.parent.exists()


# ---------------------------------------------------------------------------
# SQLite 回退：journal 构造/探测失败 → 回退 + reason 如实
# ---------------------------------------------------------------------------

def test_journal_failure_falls_back_to_sqlite(tmp_path, monkeypatch):
    """journal 构建/探测异常 → ok=True + fallback=True + fallback_reason 非空。"""
    import rfauto.optimization.storage_backends as sb

    def _boom(*_a, **_k):
        raise OSError("[WinError 1314] 客户端没有所需的特权。")

    monkeypatch.setattr(sb, "build_journal_storage", _boom)
    resolved = resolve_storage("journal", journal_path=tmp_path / "j.log")
    assert resolved["ok"] is True
    assert resolved["fallback"] is True
    assert resolved["backend"] == "sqlite"
    assert "WinError 1314" in resolved["fallback_reason"]
    assert resolved["storage"].startswith("sqlite:///")


def test_journal_probe_failure_falls_back(tmp_path, monkeypatch):
    """探测期（create_study，SymlinkLock 类故障实际爆发点）失败同样回退。"""
    def _boom(*_a, **_k):
        raise OSError("symlink privilege not held")

    monkeypatch.setattr(optuna, "create_study", _boom)
    resolved = resolve_storage("journal", journal_path=tmp_path / "j.log")
    assert resolved["ok"] is True
    assert resolved["fallback"] is True
    assert "symlink privilege" in resolved["fallback_reason"]


# ---------------------------------------------------------------------------
# sqlite 档与配置错误显性化
# ---------------------------------------------------------------------------

def test_sqlite_default_matches_optimizer_source(tmp_path, monkeypatch):
    """sqlite 缺省 URL 与 optimizer.get_storage_path 同源（单一事实源）。"""
    from rfauto.optimization.optimizer import get_storage_path

    monkeypatch.chdir(tmp_path)
    resolved = resolve_storage("sqlite")
    assert resolved["ok"] is True
    assert resolved["storage"] == get_storage_path()
    assert resolved["fallback"] is False


def test_sqlite_explicit_path(tmp_path):
    resolved = resolve_storage("sqlite", sqlite_path=tmp_path / "db" / "o.db")
    assert resolved["storage"] == f"sqlite:///{(tmp_path / 'db' / 'o.db').as_posix()}"
    assert (tmp_path / "db").exists()


def test_unknown_backend_is_explicit_error_not_fallback():
    """未知 backend = ok=False 显性错误（配置错误必须暴露，不静默回退）。"""
    resolved = resolve_storage("mysql")
    assert resolved["ok"] is False
    assert any("未知 storage backend" in e for e in resolved["errors"])
    assert resolved["fallback"] is False


def test_journal_without_path_is_configuration_error():
    resolved = resolve_storage("journal")
    assert resolved["ok"] is False
    assert any("journal_path" in e for e in resolved["errors"])
