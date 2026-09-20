"""rfauto 注册表数据库层—— SQLite 事务型注册表 + PostgreSQL 迁移接缝。

设计口径：
- 零服务器：SQLite（WAL + busy_timeout），默认文件 ``runs/registry.sqlite``，
  env ``RFAUTO_REGISTRY_DB`` 或 settings ``db.path`` 可覆盖（env 优先）；
  runs/ 已 gitignore，不入 git。
- 方言中性：DDL/DML 不用 SQLite 专有类型与函数；占位符统一写 ``?``，
  由 backend 适配（SQLite 原生即 ``?``，Postgres 翻译为 ``%s``）。
- upsert 用方言中性的 DELETE+INSERT 事务（避开 ``INSERT OR REPLACE``/
  ``ON CONFLICT`` 等 SQLite/PG 各自的专有形态）。
- 迁移接缝：``schema_version`` 表 + 递增迁移列表（幂等，重复执行零变更）；
  ``PostgresBackend`` 为 NotImplementedError 桩——团队化换 PG 时实现之，
  SQL 主体已满足方言中性，届时主要工作是驱动接入与占位符适配。
- runs 表吸收 infra/run_store.py 的既有索引字段（run_id/model/adapter/
  status/git_sha/timestamp/metrics/meta），同表名同字段，向后兼容。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# 常量与环境开关
# ---------------------------------------------------------------------------

#: 注册表数据库默认文件名（runs/ 已 gitignore）
DEFAULT_REGISTRY_DB_FILENAME = "registry.sqlite"

#: 覆盖注册表数据库路径的环境变量
ENV_REGISTRY_DB = "RFAUTO_REGISTRY_DB"

#: SQLite busy_timeout（毫秒）——写并发时等待锁而不是立刻 SQLITE_BUSY
DEFAULT_BUSY_TIMEOUT_MS = 5000

#: registry 表清单（db_status / table_counts 的遍历口径）
REGISTRY_TABLES = ("runs", "jobs", "approvals", "datasets", "owners")


def default_registry_db_path() -> Path:
    """解析注册表数据库路径：env ``RFAUTO_REGISTRY_DB`` 优先，其次 settings
    的 ``db.path``（configs/settings.yaml），缺省 runs/registry.sqlite。

    优先级与全局三层口径一致：env > YAML（settings.local.yaml 后加载覆盖）
    > 代码默认。每次调用即时读取（不在 import 期固化），测试可用 monkeypatch
    注入；settings 读取失败时静默回退缺省路径（#105：观测面不阻塞主路径）。
    """
    raw = os.environ.get(ENV_REGISTRY_DB, "").strip()
    if raw:
        return Path(raw)
    try:
        from rfauto.infra.config import load_settings  # 惰性导入，避免 import 期开销

        configured = str(load_settings().db.path or "").strip()
        if configured:
            return Path(configured)
    except Exception:
        pass
    return Path("runs") / DEFAULT_REGISTRY_DB_FILENAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 迁移列表（版本递增；幂等——重放已应用版本零变更）
# ---------------------------------------------------------------------------

_MIGRATION_V1: tuple[str, ...] = (
    # runs：吸收 run_store 既有索引字段（同表名同字段，向后兼容）
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        model TEXT,
        adapter TEXT,
        status TEXT,
        git_sha TEXT,
        timestamp TEXT,
        metrics TEXT,
        meta TEXT
    )
    """,
    # jobs：job_registry 持久化（job_id ↔ run_id ↔ 状态/结果）
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        run_id TEXT,
        state TEXT,
        result TEXT,
        error TEXT,
        created_at DOUBLE PRECISION,
        finished_at DOUBLE PRECISION,
        metadata TEXT
    )
    """,
    # approvals：审批流读模型（audit.jsonl 为产物
    # 事实源，本表存状态/审计行，payload 内 audit_file 为外键）
    """
    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        kind TEXT,
        payload TEXT,
        status TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """,
    # datasets：数据集注册索引（dataset_service 的 Parquet/HDF5 资产目录）
    """
    CREATE TABLE IF NOT EXISTS datasets (
        name TEXT PRIMARY KEY,
        manifest_path TEXT,
        format TEXT,
        visibility TEXT,
        n_rows INTEGER,
        updated_at TEXT
    )
    """,
    # owners：团队化最小面——资源 → (owner, visibility) 归属映射（独立表）
    """
    CREATE TABLE IF NOT EXISTS owners (
        resource_kind TEXT,
        resource_id TEXT,
        owner TEXT,
        visibility TEXT,
        updated_at TEXT,
        PRIMARY KEY (resource_kind, resource_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON runs (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs (state)",
    "CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals (status)",
    "CREATE INDEX IF NOT EXISTS idx_datasets_updated ON datasets (updated_at)",
)

#: 已应用迁移列表：[(version, statements), ...]——新迁移追加到尾部，版本递增
MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (1, _MIGRATION_V1),
]

#: 当前最新 schema 版本
LATEST_SCHEMA_VERSION = MIGRATIONS[-1][0]

_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
)
"""


# ---------------------------------------------------------------------------
# Backend Protocol 与实现
# ---------------------------------------------------------------------------

class DBBackend(Protocol):
    """注册表数据库后端协议——SQLite 已实现，Postgres 为迁移接缝桩。

    SQL 契约：调用方一律写 ``?`` 占位符与方言中性 SQL；backend 负责
    适配（SQLite 原生 ``?``；Postgres 翻译为 ``%s``）。
    """

    def connect(self) -> Any:
        """打开（或复用）连接，并做后端级 bootstrap（如 schema_version 表）。"""
        ...

    def close(self) -> None:
        """关闭连接；重复调用为空操作。"""
        ...

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        """执行单条写/读语句（写语句自动提交），返回 cursor。"""
        ...

    def executemany(self, sql: str, params_seq: Sequence[Sequence[Any]] = ()) -> Any:
        """批量执行同构语句，返回 cursor。"""
        ...

    def query(self, sql: str, params: Sequence[Any] = (),
              limit: int | None = None) -> list[tuple[Any, ...]]:
        """只读查询，返回行元组列表；limit 非空时最多取 limit 行。"""
        ...

    def migrate(self) -> dict[str, Any]:
        """执行幂等迁移，返回 {"applied": int, "version": int}。"""
        ...


class SQLiteBackend:
    """SQLite 后端：单连接 + 互斥锁 + WAL + busy_timeout，零服务器。"""

    def __init__(self, path: str | Path | None = None,
                 busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> None:
        # #140：PathLike 入参第一行先 Path() 收敛——注解写了 Path 不代表调用方传的是 Path
        self.path = Path(path) if path is not None else default_registry_db_path()
        self.busy_timeout_ms = int(busy_timeout_ms)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # -- 连接管理 ----------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        conn.execute(_SCHEMA_VERSION_TABLE)
        conn.commit()
        self._conn = conn
        return conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None

    def __enter__(self) -> SQLiteBackend:
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- 基础操作 ----------------------------------------------------------

    @staticmethod
    def _adapt(sql: str) -> str:
        """占位符适配：SQLite 原生 ``?``，原样返回（Postgres 桩说明见类文档）。"""
        return sql

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        conn = self.connect()
        with self._lock:
            cur = conn.execute(self._adapt(sql), tuple(params))
            conn.commit()
            return cur

    def executemany(self, sql: str, params_seq: Sequence[Sequence[Any]] = ()) -> sqlite3.Cursor:
        conn = self.connect()
        with self._lock:
            cur = conn.executemany(self._adapt(sql), [tuple(p) for p in params_seq])
            conn.commit()
            return cur

    def query(self, sql: str, params: Sequence[Any] = (),
              limit: int | None = None) -> list[tuple[Any, ...]]:
        conn = self.connect()
        with self._lock:
            cur = conn.execute(self._adapt(sql), tuple(params))
            if limit is None:
                return cur.fetchall()
            return cur.fetchmany(max(0, int(limit)))

    def query_columns(self, sql: str, params: Sequence[Any] = (),
                      limit: int | None = None) -> tuple[list[str], list[tuple[Any, ...]]]:
        """带列名的只读查询（db_query 输出 JSON 表头用；非协议方法，SQLite 扩展）。"""
        conn = self.connect()
        with self._lock:
            cur = conn.execute(self._adapt(sql), tuple(params))
            columns = [d[0] for d in cur.description or []]
            rows = (cur.fetchall() if limit is None
                    else cur.fetchmany(max(0, int(limit))))
            return columns, rows

    def transaction(self) -> _SQLiteTransaction:
        """事务上下文（非协议方法）：块内语句共享一次 commit，保证原子性。"""
        return _SQLiteTransaction(self)

    # -- 迁移 ---------------------------------------------------------------

    def migrate(self) -> dict[str, Any]:
        conn = self.connect()
        with self._lock:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = int(row[0]) if row and row[0] is not None else 0
            applied = 0
            for version, statements in MIGRATIONS:
                if version <= current:
                    continue
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (version, _utc_now_iso()),
                )
                applied += 1
            if applied:
                conn.commit()
            return {"applied": applied, "version": max(current, LATEST_SCHEMA_VERSION)}


class _SQLiteTransaction:
    """SQLiteBackend 事务上下文：enter 时 BEGIN，正常退出 COMMIT，异常 ROLLBACK。"""

    def __init__(self, backend: SQLiteBackend) -> None:
        self._backend = backend

    def __enter__(self) -> sqlite3.Connection:
        conn = self._backend.connect()
        self._backend._lock.acquire()
        conn.execute("BEGIN")
        return conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        conn = self._backend._conn
        try:
            if conn is not None:
                if exc_type is None:
                    conn.commit()
                else:
                    conn.rollback()
        finally:
            self._backend._lock.release()


class PostgresBackend:
    """PostgreSQL 迁移接缝（团队化：当前版本不实现）。

    届时实现要点：
    - 驱动：psycopg（本波禁改 pyproject.toml，不加依赖）；
    - DSN：env ``RFAUTO_REGISTRY_PG_DSN`` 提供；
    - 占位符适配：``?`` → ``%s``（SQL 主体已方言中性，无需改写调用方）；
    - ``transaction()`` 映射 BEGIN/COMMIT；upsert 可换 ``INSERT ... ON CONFLICT``；
    - ``DOUBLE PRECISION``/``TEXT``/``INTEGER`` DDL 均为 PG 原生，迁移列表可复用。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "PostgresBackend 是团队化迁移接缝（当前仅留桩）："
            "实现 psycopg 驱动接入 + ?→%s 占位符适配后启用，"
            "见 src/rfauto/infra/db.py 模块文档与类文档。"
        )

    # -- 桩方法：签名与 DBBackend 一致，实现前一律显式拒绝 ------------------

    def connect(self) -> Any:
        raise NotImplementedError("PostgresBackend.connect 待团队化实现（接缝桩）")

    def close(self) -> None:
        raise NotImplementedError("PostgresBackend.close 待团队化实现（接缝桩）")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        raise NotImplementedError("PostgresBackend.execute 待团队化实现（接缝桩）")

    def executemany(self, sql: str, params_seq: Sequence[Sequence[Any]] = ()) -> Any:
        raise NotImplementedError("PostgresBackend.executemany 待团队化实现（接缝桩）")

    def query(self, sql: str, params: Sequence[Any] = (),
              limit: int | None = None) -> list[tuple[Any, ...]]:
        raise NotImplementedError("PostgresBackend.query 待团队化实现（接缝桩）")

    def migrate(self) -> dict[str, Any]:
        raise NotImplementedError("PostgresBackend.migrate 待团队化实现（接缝桩）")


# ---------------------------------------------------------------------------
# RegistryDB：注册表面（runs / jobs / approvals / datasets / owners）
# ---------------------------------------------------------------------------

_RUNS_COLUMNS = ("run_id", "model", "adapter", "status", "git_sha",
                 "timestamp", "metrics", "meta")
_JOBS_COLUMNS = ("job_id", "run_id", "state", "result", "error",
                 "created_at", "finished_at", "metadata")
_APPROVALS_COLUMNS = ("id", "kind", "payload", "status", "created_at", "updated_at")
_DATASETS_COLUMNS = ("name", "manifest_path", "format", "visibility", "n_rows", "updated_at")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def _json_loads(raw: Any, fallback: Any) -> Any:
    if raw is None or raw == "":
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


class RegistryDB:
    """注册表数据库高层门面：migrate + 五张表的仓储 API。

    所有 SQL 走 backend（``?`` 占位符、方言中性）；默认后端为 SQLiteBackend。
    """

    def __init__(self, backend: DBBackend | None = None,
                 path: str | Path | None = None) -> None:
        self.backend: DBBackend = backend if backend is not None else SQLiteBackend(path=path)
        self._ensured = False

    # -- 后端转发 ----------------------------------------------------------

    @property
    def path(self) -> Path:
        """数据库文件路径（仅 SQLiteBackend 提供时；其余返回 backend repr）。"""
        return getattr(self.backend, "path", Path(str(self.backend)))

    def connect(self) -> Any:
        return self.backend.connect()

    def close(self) -> None:
        self.backend.close()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        self._ensure()
        return self.backend.execute(sql, params)

    def executemany(self, sql: str, params_seq: Sequence[Sequence[Any]] = ()) -> Any:
        self._ensure()
        return self.backend.executemany(sql, params_seq)

    def query(self, sql: str, params: Sequence[Any] = (),
              limit: int | None = None) -> list[tuple[Any, ...]]:
        self._ensure()
        return self.backend.query(sql, params, limit=limit)

    def migrate(self) -> dict[str, Any]:
        info = self.backend.migrate()
        self._ensured = True
        return info

    def _ensure(self) -> None:
        if not self._ensured:
            self.migrate()

    # -- 通用 upsert（方言中性：事务内 DELETE+INSERT） ---------------------

    def _upsert(self, table: str, key_cols: tuple[str, ...],
                columns: tuple[str, ...], values: Sequence[Any]) -> None:
        self._ensure()
        collist = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        where = " AND ".join(f"{c} = ?" for c in key_cols)
        key_vals = tuple(values[columns.index(c)] for c in key_cols)
        txn = getattr(self.backend, "transaction", None)
        if txn is not None:
            with txn() as conn:
                conn.execute(f"DELETE FROM {table} WHERE {where}", key_vals)
                conn.execute(
                    f"INSERT INTO {table} ({collist}) VALUES ({placeholders})",
                    tuple(values),
                )
        else:
            # 无事务能力的后端：退化为两条语句（不保证原子，仍语义正确）
            self.execute(f"DELETE FROM {table} WHERE {where}", key_vals)
            self.execute(f"INSERT INTO {table} ({collist}) VALUES ({placeholders})",
                         tuple(values))

    # -- runs（与 run_store.record_run/list_runs 字段级兼容） ---------------

    def upsert_run(self, record: dict[str, Any]) -> bool:
        """Upsert run 记录；``_`` 前缀键不入库（与 run_store 语义一致）。"""
        meta = {k: v for k, v in (record or {}).items() if not k.startswith("_")}
        row = (
            record.get("run_id", ""),
            record.get("model", ""),
            record.get("adapter", ""),
            record.get("status", ""),
            record.get("git_sha", ""),
            record.get("timestamp", ""),
            _json_dumps(record.get("metrics", {})),
            _json_dumps(meta),
        )
        self._upsert("runs", ("run_id",), _RUNS_COLUMNS, row)
        return True

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self.query(
            f"SELECT {', '.join(_RUNS_COLUMNS)} FROM runs WHERE run_id = ?",
            (str(run_id),), limit=1,
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "run_id": r[0], "model": r[1], "adapter": r[2], "status": r[3],
            "git_sha": r[4], "timestamp": r[5],
            "metrics": _json_loads(r[6], {}), "meta": _json_loads(r[7], {}),
        }

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """最近 runs（新→旧），行形状与 run_store.list_runs 逐字段一致。"""
        rows = self.query(
            "SELECT run_id, model, adapter, status, timestamp, metrics "
            "FROM runs ORDER BY timestamp DESC LIMIT ?",
            (int(limit),),
        )
        out: list[dict[str, Any]] = []
        for run_id, model, adapter, status, ts, metrics_json in rows:
            out.append({
                "run_id": run_id,
                "model": model,
                "adapter": adapter,
                "status": status,
                "timestamp": ts,
                "metrics": _json_loads(metrics_json, {}),
            })
        return out

    # -- jobs（job_registry 可选持久化后端） --------------------------------

    def upsert_job(self, *, job_id: str, run_id: str = "", state: str = "",
                   result: dict[str, Any] | None = None, error: str = "",
                   created_at: float | None = None,
                   finished_at: float | None = None,
                   metadata: dict[str, Any] | None = None) -> bool:
        row = (
            str(job_id), str(run_id or ""), str(state or ""),
            _json_dumps(result) if result is not None else None,
            str(error or ""),
            None if created_at is None else float(created_at),
            None if finished_at is None else float(finished_at),
            _json_dumps(metadata or {}),
        )
        self._upsert("jobs", ("job_id",), _JOBS_COLUMNS, row)
        return True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        rows = self.query(
            f"SELECT {', '.join(_JOBS_COLUMNS)} FROM jobs WHERE job_id = ?",
            (str(job_id),), limit=1,
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "job_id": r[0], "run_id": r[1], "state": r[2],
            "result": _json_loads(r[3], None), "error": r[4] or "",
            "created_at": r[5], "finished_at": r[6],
            "seats": list((_json_loads(r[7], {}) or {}).get("seats", [])),
        }

    def list_jobs(self, limit: int = 100, state: str | None = None) -> list[dict[str, Any]]:
        if state:
            rows = self.query(
                f"SELECT {', '.join(_JOBS_COLUMNS)} FROM jobs WHERE state = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (str(state), int(limit)),
            )
        else:
            rows = self.query(
                f"SELECT {', '.join(_JOBS_COLUMNS)} FROM jobs "
                "ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            )
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append({
                "job_id": r[0], "run_id": r[1], "state": r[2],
                "result": _json_loads(r[3], None), "error": r[4] or "",
                "created_at": r[5], "finished_at": r[6],
                "seats": list((_json_loads(r[7], {}) or {}).get("seats", [])),
            })
        return out

    # -- approvals（审批流读模型） ----

    def insert_approval(self, kind: str, payload: dict[str, Any] | None,
                        approval_id: str | None = None,
                        status: str = "pending") -> str:
        aid = str(approval_id) if approval_id else f"apr_{_utc_now_iso()}_{id(payload) & 0xFFFFFF:06x}"
        now = _utc_now_iso()
        row = (aid, str(kind or ""), _json_dumps(payload or {}), str(status or "pending"), now, now)
        self._upsert("approvals", ("id",), _APPROVALS_COLUMNS, row)
        return aid

    def update_approval_status(self, approval_id: str, status: str) -> bool:
        self.execute(
            "UPDATE approvals SET status = ?, updated_at = ? WHERE id = ?",
            (str(status), _utc_now_iso(), str(approval_id)),
        )
        return self.query("SELECT 1 FROM approvals WHERE id = ?",
                          (str(approval_id),), limit=1) != []

    def update_approval_payload(self, approval_id: str, payload: dict[str, Any],
                                kind: str | None = None) -> bool:
        """更新审批行载荷（不动 status/created_at；audit.jsonl 外部改写后
        由读路径回填刷新 pending 行用——文件是事实源，视图随之）。"""
        sets = ["payload = ?", "updated_at = ?"]
        values: list[Any] = [_json_dumps(payload or {}), _utc_now_iso()]
        if kind is not None:
            sets.append("kind = ?")
            values.append(str(kind))
        values.append(str(approval_id))
        self.execute(
            f"UPDATE approvals SET {', '.join(sets)} WHERE id = ?", values)
        return self.query("SELECT 1 FROM approvals WHERE id = ?",
                          (str(approval_id),), limit=1) != []

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        """按主键取单条审批行；不存在返回 None（r3_services insert-if-missing 用）。"""
        rows = self.query(
            f"SELECT {', '.join(_APPROVALS_COLUMNS)} FROM approvals WHERE id = ?",
            (str(approval_id),), limit=1,
        )
        if not rows:
            return None
        r = rows[0]
        return {"id": r[0], "kind": r[1], "payload": _json_loads(r[2], {}),
                "status": r[3], "created_at": r[4], "updated_at": r[5]}

    def list_approvals(self, status: str | None = None,
                       limit: int = 50) -> list[dict[str, Any]]:
        if status:
            rows = self.query(
                f"SELECT {', '.join(_APPROVALS_COLUMNS)} FROM approvals "
                "WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (str(status), int(limit)),
            )
        else:
            rows = self.query(
                f"SELECT {', '.join(_APPROVALS_COLUMNS)} FROM approvals "
                "ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            )
        return [
            {"id": r[0], "kind": r[1], "payload": _json_loads(r[2], {}),
             "status": r[3], "created_at": r[4], "updated_at": r[5]}
            for r in rows
        ]

    # -- datasets（数据集注册索引） -----------------------------------------

    def upsert_dataset(self, *, name: str, manifest_path: str = "",
                       format: str = "", visibility: str = "private",
                       n_rows: int | None = None,
                       updated_at: str | None = None) -> bool:
        row = (str(name), str(manifest_path or ""), str(format or ""),
               str(visibility or "private"),
               None if n_rows is None else int(n_rows),
               updated_at or _utc_now_iso())
        self._upsert("datasets", ("name",), _DATASETS_COLUMNS, row)
        return True

    def get_dataset(self, name: str) -> dict[str, Any] | None:
        rows = self.query(
            f"SELECT {', '.join(_DATASETS_COLUMNS)} FROM datasets WHERE name = ?",
            (str(name),), limit=1,
        )
        if not rows:
            return None
        r = rows[0]
        return {"name": r[0], "manifest_path": r[1], "format": r[2],
                "visibility": r[3], "n_rows": r[4], "updated_at": r[5]}

    def list_datasets(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.query(
            f"SELECT {', '.join(_DATASETS_COLUMNS)} FROM datasets "
            "ORDER BY updated_at DESC LIMIT ?",
            (int(limit),),
        )
        return [{"name": r[0], "manifest_path": r[1], "format": r[2],
                 "visibility": r[3], "n_rows": r[4], "updated_at": r[5]}
                for r in rows]

    # -- owners（团队化最小面） ----------------------------------------------

    def set_owner(self, resource_kind: str, resource_id: str, owner: str,
                  visibility: str = "private") -> bool:
        self._upsert(
            "owners", ("resource_kind", "resource_id"),
            ("resource_kind", "resource_id", "owner", "visibility", "updated_at"),
            (str(resource_kind), str(resource_id), str(owner),
             str(visibility or "private"), _utc_now_iso()),
        )
        return True

    def get_owner(self, resource_kind: str, resource_id: str) -> dict[str, Any] | None:
        rows = self.query(
            "SELECT resource_kind, resource_id, owner, visibility, updated_at "
            "FROM owners WHERE resource_kind = ? AND resource_id = ?",
            (str(resource_kind), str(resource_id)), limit=1,
        )
        if not rows:
            return None
        r = rows[0]
        return {"resource_kind": r[0], "resource_id": r[1], "owner": r[2],
                "visibility": r[3], "updated_at": r[4]}

    # -- 状态盘点 ------------------------------------------------------------

    def table_count(self, table: str) -> int | None:
        """单表行数；表不存在返回 None（调用方自行决定零值语义）。"""
        if table not in REGISTRY_TABLES:
            raise ValueError(f"非法表名: {table!r}（仅允许 {REGISTRY_TABLES}）")
        try:
            rows = self.query(f"SELECT COUNT(*) FROM {table}")
        except Exception:
            return None
        return int(rows[0][0]) if rows else None

    def table_counts(self) -> dict[str, int | None]:
        return {t: self.table_count(t) for t in REGISTRY_TABLES}

    def current_schema_version(self) -> int:
        rows = self.query("SELECT MAX(version) FROM schema_version")
        if not rows or rows[0][0] is None:
            return 0
        return int(rows[0][0])
