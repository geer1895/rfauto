"""OP-11：Optuna storage 后端解析面（JournalStorage 选项 + SQLite 回退）。

背景（round16:213 OP-11，P3/S）：主优化链（optimizer.run_tuning 等）钉死
``sqlite:///runs/.optuna/optuna.db``（get_storage_path）；本模块提供
storage 面的独立解析层——JournalStorage（追加式日志文件，多进程安全、
无 SQLite 文件锁争用）与 SQLite 双档，供后续接线消费。

**optuna 5.0.0 API（2026-10-03 venv 实测，非臆写）**：
- ``optuna.storages.JournalStorage(JournalFileBackend(file_path, lock_obj=...))``
- Windows 无 symlink 特权时缺省 ``JournalFileSymlinkLock`` 在 append 时抛
  ``OSError [WinError 1314] 客户端没有所需的特权``（本机实测复现）——
  Windows 缺省改用 ``JournalFileOpenLock``（实测同机 PASS，含跨实例回读）；
- JournalStorage 回读 = 对同一 journal 文件新建 JournalStorage +
  ``optuna.load_study``（实测 trial 全量可见）。

回退契约（本席任务书"storage 面接线+SQLite 回退"）：
- ``backend="journal"`` 且 journal 构造/探测失败 → 回退 SQLite（ok=True、
  ``fallback=True`` + ``fallback_reason`` 如实记录，不静默——调用方日志可见）；
- 未知 backend → ``ok=False`` 显式错误，不回退（配置错误必须显性暴露）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

__all__ = [
    "build_journal_storage",
    "journal_lock",
    "resolve_storage",
]


def journal_lock(journal_path: str | Path) -> Any:
    """平台适配的 journal 文件锁（optuna 5.0 实测口径，见模块 docstring）。

    Windows 缺省 SymlinkLock 需要特权（WinError 1314），改 OpenLock；
    POSIX 维持 optuna 缺省 SymlinkLock。锁实例无状态副作用，可重复创建。
    """
    from optuna.storages.journal import JournalFileOpenLock, JournalFileSymlinkLock

    path_str = str(journal_path)
    if sys.platform.startswith("win"):
        return JournalFileOpenLock(path_str)
    return JournalFileSymlinkLock(path_str)


def build_journal_storage(journal_path: str | Path) -> Any:
    """按 optuna 5.0 Journal API 构建 JournalStorage（实测签名，见 docstring）。"""
    from optuna.storages import JournalStorage
    from optuna.storages.journal import JournalFileBackend

    path_str = str(journal_path)
    return JournalStorage(JournalFileBackend(path_str, lock_obj=journal_lock(path_str)))


def _default_sqlite_url() -> str:
    """缺省 SQLite URL 与 optimizer.get_storage_path 同源（懒导入防环/防重）。"""
    from rfauto.optimization.optimizer import get_storage_path

    return get_storage_path()


def resolve_storage(
    backend: str = "sqlite",
    *,
    sqlite_path: str | Path | None = None,
    journal_path: str | Path | None = None,
) -> dict[str, Any]:
    """解析 storage 请求 → ``{ok, storage, backend, fallback, fallback_reason, errors}``。

    参数：
      backend —— "sqlite"（缺省，返回 sqlite:/// URL 字符串）| "journal"
                  （返回 JournalStorage 实例，构造失败回退 SQLite）；
      sqlite_path —— 显式 SQLite 文件路径（None → optimizer.get_storage_path 同源缺省）；
      journal_path —— journal 日志文件路径（journal 档必填；父目录自动创建）。

    返回字段：
      ok              —— False 仅在配置错误（未知 backend / journal 缺路径）；
      storage         —— sqlite: URL 字符串；journal 成功: JournalStorage 实例；
                         回退: SQLite URL 字符串；
      backend         —— 实际生效档（"sqlite" | "journal"）；
      fallback        —— journal→sqlite 回退是否发生；
      fallback_reason —— 回退原因（发生时非空，日志面诚实记录）。
    """
    backend = str(backend).strip().lower()
    if backend == "sqlite":
        if sqlite_path is None:
            return {
                "ok": True, "storage": _default_sqlite_url(),
                "backend": "sqlite", "fallback": False, "fallback_reason": None,
                "errors": [],
            }
        p = Path(sqlite_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return {
            "ok": True, "storage": f"sqlite:///{p.as_posix()}",
            "backend": "sqlite", "fallback": False, "fallback_reason": None,
            "errors": [],
        }
    if backend == "journal":
        if journal_path is None:
            return {
                "ok": False, "storage": None, "backend": "journal",
                "fallback": False, "fallback_reason": None,
                "errors": ["backend='journal' 需要 journal_path"],
            }
        jp = Path(journal_path)
        try:
            jp.parent.mkdir(parents=True, exist_ok=True)
            storage = build_journal_storage(jp)
            # 探测性最小写读：SymlinkLock 类失败发生在首次 append（本机
            # WinError 1314 实测在 create_study 而非构造期），此处经一次
            # study 创建/读回把故障提前到 resolve 阶段暴露，回退才有意义。
            import optuna

            probe_name = "__rfauto_storage_probe__"
            _s = optuna.create_study(storage=storage, study_name=probe_name,
                                     load_if_exists=True)
            optuna.delete_study(study_name=probe_name, storage=storage)
        except Exception as exc:
            reason = f"journal storage 构建/探测失败，回退 SQLite: {type(exc).__name__}: {exc}"
            return {
                "ok": True, "storage": _default_sqlite_url() if sqlite_path is None
                else f"sqlite:///{Path(sqlite_path).as_posix()}",
                "backend": "sqlite", "fallback": True, "fallback_reason": reason,
                "errors": [],
            }
        return {
            "ok": True, "storage": storage, "backend": "journal",
            "fallback": False, "fallback_reason": None, "errors": [],
        }
    return {
        "ok": False, "storage": None, "backend": backend,
        "fallback": False, "fallback_reason": None,
        "errors": [f"未知 storage backend: {backend}（可选 sqlite | journal）"],
    }
