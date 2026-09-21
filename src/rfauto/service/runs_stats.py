"""runs_stats：runs 数据库化查询/统计层（阶段 5.5，SQLite 起步）。

在注册表数据库（缺省 runs/registry.sqlite，record_run 逐 run upsert；env
RFAUTO_REGISTRY_DB / settings db.path 可覆盖）之上提供只读聚合：
- 按 model/adapter/status 分组计数；
- 时间窗查询；
- schema_version 表 + PRAGMA user_version——换 Postgres 时此层是
  唯一需要替换的接缝（SQL 方言迁移点集中于此）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        from rfauto.infra.db import default_registry_db_path

        p = default_registry_db_path()
    else:
        p = Path(db_path)  # #140：PathLike 入参第一行先 Path() 收敛
    if not p.exists():
        raise FileNotFoundError(f"runs 索引库不存在: {p}（先跑一次 run/tune，"
                                "或用 rfauto db reindex-runs 回填）")
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version ("
                 "version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
    return conn


def runs_summary(db_path: str | Path | None = None,
                 since: str | None = None) -> dict[str, Any]:
    """runs 总览：总数、按 model/adapter/status 分组计数、最近 10 条。"""
    try:
        conn = _connect(db_path)
    except FileNotFoundError as exc:
        return {"ok": False, "errors": [str(exc)]}
    try:
        where, params = "", []
        if since:
            where = "WHERE timestamp >= ?"
            params.append(since)
        total = conn.execute(f"SELECT COUNT(*) FROM runs {where}",
                             params).fetchone()[0]
        by_model = {r[0]: r[1] for r in conn.execute(
            f"SELECT model, COUNT(*) FROM runs {where} "
            "GROUP BY model ORDER BY 2 DESC", params)}
        by_adapter = {r[0]: r[1] for r in conn.execute(
            f"SELECT adapter, COUNT(*) FROM runs {where} "
            "GROUP BY adapter ORDER BY 2 DESC", params)}
        by_status = {r[0]: r[1] for r in conn.execute(
            f"SELECT status, COUNT(*) FROM runs {where} "
            "GROUP BY status", params)}
        recent = []
        for r in conn.execute(
                f"SELECT run_id, model, adapter, status, timestamp, metrics "
                f"FROM runs {where} ORDER BY timestamp DESC LIMIT 10", params):
            recent.append({
                "run_id": r["run_id"], "model": r["model"],
                "adapter": r["adapter"], "status": r["status"],
                "timestamp": r["timestamp"],
                "metrics": (json.loads(r["metrics"])
                            if r["metrics"] else {}),
            })
        return {"ok": True, "total": total, "by_model": by_model,
                "by_adapter": by_adapter, "by_status": by_status,
                "recent": recent, "schema_version": SCHEMA_VERSION}
    finally:
        conn.close()


def query_runs(db_path: str | Path | None = None, *,
               model: str | None = None,
               adapter: str | None = None,
               status: str | None = None,
               limit: int = 50) -> dict[str, Any]:
    """条件查询 runs 索引（全部为可选过滤，AND 语义）。"""
    try:
        conn = _connect(db_path)
    except FileNotFoundError as exc:
        return {"ok": False, "errors": [str(exc)]}
    try:
        clauses, params = [], []
        for col, val in (("model", model), ("adapter", adapter),
                         ("status", status)):
            if val:
                clauses.append(f"{col} = ?")
                params.append(val)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT run_id, model, adapter, status, timestamp, metrics "
            f"FROM runs {where} ORDER BY timestamp DESC LIMIT ?",
            [*params, int(limit)])
        runs = [{"run_id": r["run_id"], "model": r["model"],
                 "adapter": r["adapter"], "status": r["status"],
                 "timestamp": r["timestamp"],
                 "metrics": (json.loads(r["metrics"])
                             if r["metrics"] else {})}
                for r in rows]
        return {"ok": True, "n_runs": len(runs), "runs": runs}
    finally:
        conn.close()
