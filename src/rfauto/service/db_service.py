"""数据库注册表 service—— JSON 进出，CLI/MCP 薄壳的后端。

职责：
- init/migrate：建库 + 幂等迁移（schema_version 表，重复执行零变更）
- status：schema 版本、各表行数、文件路径（文件不存在不创建，如实报告）
- reindex_runs：扫 runs/**/meta.json 重建 runs 表（best-effort #105，不阻塞）
- query：只读参数化 SQL 白名单（仅 SELECT 单语句，注入防线与
  dataset_service 同款思路：字符白名单 + 关键词黑名单 + 参数绑定）
- analytics_attach：DuckDB 直读 SQLite 文件（sqlite 扩展可用则附加并
  示例查询；不可用则 ok=False 如实返回，绝不失败）

分层：cli/mcp → service（本模块）→ infra/db.py；数值与物理语义不经过本层。
"""

from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path
from typing import Any

from rfauto.infra.db import (
    REGISTRY_TABLES,
    RegistryDB,
    default_registry_db_path,
)

# ---------------------------------------------------------------------------
# 只读 SQL 白名单（与 dataset_service._validate_where 同款纵深防御思路）
# ---------------------------------------------------------------------------

#: 查询语句字符白名单（单条 SELECT 的合法字符集；``?`` 是占位符）
_QUERY_ALLOWED_RE = re.compile(r"""^[A-Za-z0-9_ \t\r\n.,()'"<>!=+\-*/%|?]+$""")

#: 多语句/注释/越权词根黑名单（大小写不敏感；reindex 在此是 SQL 语句词根）
_QUERY_FORBIDDEN = (";", "--", "/*", "*/", "`", "\\", "\x00")
_QUERY_FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "create", "drop", "alter", "attach",
    "detach", "pragma", "vacuum", "reindex", "replace", "copy", "grant",
    "revoke", "union", "load_extension", "readfile", "writefile", "fopen",
)

#: 单次查询默认与最大行数上限
_DEFAULT_QUERY_LIMIT = 200
_MAX_QUERY_LIMIT = 5000


def _validate_readonly_sql(sql: str) -> str:
    """校验单条只读 SELECT，返回 strip 后的安全 SQL；非法即 ValueError。"""
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql 不能为空（仅允许单条 SELECT 查询）")
    s = sql.strip()
    first_word = s.split(None, 1)[0].lower() if s.split(None, 1) else ""
    if first_word != "select":
        raise ValueError(f"仅允许 SELECT 查询（首词为 {first_word!r}）")
    lowered = s.lower()
    for token in _QUERY_FORBIDDEN:
        if token in s:
            raise ValueError(
                f"sql 含非法片段 {token!r}（仅允许单条 SELECT，"
                "禁止分号/注释/多语句）")
    for kw in _QUERY_FORBIDDEN_KEYWORDS:
        if kw in lowered:
            raise ValueError(f"sql 含禁用关键词 {kw!r}（只读白名单）")
    if not _QUERY_ALLOWED_RE.fullmatch(s):
        raise ValueError("sql 含白名单外字符（允许：字母数字下划线空格引号"
                         "括号比较/算术运算符等）")
    return s


def _validate_params(params: list[Any] | tuple[Any, ...] | None) -> tuple[Any, ...]:
    """查询参数只允许标量列表（占位符经 backend 绑定，不拼串）。"""
    if params is None:
        return ()
    if not isinstance(params, (list, tuple)):
        raise ValueError("params 必须是标量数组（? 占位符绑定）")
    for p in params:
        if p is not None and not isinstance(p, (str, int, float, bool)):
            raise ValueError(f"params 含非标量元素: {type(p).__name__}")
    return tuple(params)


def _open_registry(db_path: str | Path | None = None) -> RegistryDB:
    """打开注册表数据库：显式路径 > env RFAUTO_REGISTRY_DB > settings db.path
    > runs/registry.sqlite（后两级由 infra.db.default_registry_db_path 统一解析，
    R2-D-02 合流）。"""
    return RegistryDB(path=db_path) if db_path is not None else RegistryDB()


# ---------------------------------------------------------------------------
# init / migrate / status
# ---------------------------------------------------------------------------

def db_init(db_path: str | Path | None = None) -> dict[str, Any]:
    """建库 + 执行幂等迁移（等价 db_migrate；首次 applied=1，重放 applied=0）。"""
    return db_migrate(db_path)


def db_migrate(db_path: str | Path | None = None) -> dict[str, Any]:
    """执行幂等迁移，返回 {"ok", "path", "schema_version", "applied"}。"""
    db = _open_registry(db_path)
    try:
        info = db.migrate()
        return {
            "ok": True,
            "path": str(db.path),
            "schema_version": int(info["version"]),
            "applied": int(info["applied"]),
            "backend": "sqlite",
        }
    finally:
        db.close()


def db_status(db_path: str | Path | None = None) -> dict[str, Any]:
    """注册表状态盘点：文件路径、schema 版本、各表行数（文件不存在不创建）。"""
    path = Path(db_path) if db_path is not None else default_registry_db_path()
    base: dict[str, Any] = {
        "ok": True,
        "backend": "sqlite",
        "path": str(path),
        "exists": path.exists(),
    }
    if not path.exists():
        base.update({"schema_version": 0,
                     "tables": {t: 0 for t in REGISTRY_TABLES}})
        return base
    db = _open_registry(path)
    try:
        base.update({
            "schema_version": db.current_schema_version(),
            "tables": db.table_counts(),
        })
        return base
    finally:
        db.close()


# ---------------------------------------------------------------------------
# reindex_runs（best-effort，#105：单个 meta.json 失败不阻塞整体）
# ---------------------------------------------------------------------------

def reindex_runs(runs_dir: str | Path = "runs",
                 db_path: str | Path | None = None) -> dict[str, Any]:
    """扫 ``runs/*/meta.json`` 重建 runs 表（upsert，幂等可重放）。

    返回 {"ok", "reindexed", "failed", "db_path", "errors"(截断前 20 条)}；
    runs 目录不存在时如实返回零值，不报错不建目录。
    """
    root = Path(runs_dir)
    if not root.is_dir():
        return {"ok": True, "reindexed": 0, "failed": 0, "errors": [],
                "db_path": str(Path(db_path) if db_path is not None
                               else default_registry_db_path()),
                "note": f"runs 目录不存在: {root}"}
    db = _open_registry(db_path)
    reindexed = 0
    failed = 0
    errors: list[str] = []
    try:
        for meta_file in sorted(root.glob("*/meta.json")):
            try:
                record = json.loads(meta_file.read_text(encoding="utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("meta.json 顶层不是对象")
                if not record.get("run_id"):
                    # run_id 缺失/为空时用目录名兜底（write_meta 正常都会写）
                    record["run_id"] = meta_file.parent.name
                db.upsert_run(record)
                reindexed += 1
            except Exception as exc:  # #105：单文件失败不阻塞整体
                failed += 1
                if len(errors) < 20:
                    errors.append(f"{meta_file}: {exc}")
        return {"ok": True, "reindexed": reindexed, "failed": failed,
                "errors": errors, "db_path": str(db.path)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# query（只读参数化 SQL 白名单）
# ---------------------------------------------------------------------------

def db_query(sql: str, params: list[Any] | tuple[Any, ...] | None = None,
             limit: int = _DEFAULT_QUERY_LIMIT,
             db_path: str | Path | None = None) -> dict[str, Any]:
    """只读查询注册表：仅 SELECT 单语句 + ? 占位符参数绑定。

    返回 {"ok", "columns", "rows", "row_count", "truncated", "limit"}；
    白名单拒绝（非 SELECT/多语句/禁用关键词/非法字符）抛 ValueError。
    行数上限 _MAX_QUERY_LIMIT，超出截断并如实标记 truncated。
    """
    safe_sql = _validate_readonly_sql(sql)
    safe_params = _validate_params(params)
    n_limit = int(limit) if limit else _DEFAULT_QUERY_LIMIT
    if n_limit < 1:
        n_limit = _DEFAULT_QUERY_LIMIT
    truncated_requested = n_limit > _MAX_QUERY_LIMIT
    n_limit = min(n_limit, _MAX_QUERY_LIMIT)
    db = _open_registry(db_path)
    try:
        # 多取 1 行用于截断判定（fetchmany(limit+1)）
        columns, rows = db.backend.query_columns(
            safe_sql, safe_params, limit=n_limit + 1)
        truncated = len(rows) > n_limit or truncated_requested
        rows = rows[:n_limit]
        return {
            "ok": True,
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
            "limit": n_limit,
        }
    finally:
        db.close()


def db_query_safe(sql: str, params: list[Any] | tuple[Any, ...] | None = None,
                  limit: int = _DEFAULT_QUERY_LIMIT,
                  db_path: str | Path | None = None) -> dict[str, Any]:
    """同 ``db_query``，但拒绝/失败返回 ``{"ok": False, "errors": [...]}`` 信封
    而非抛出——CLI/MCP 薄壳用（薄壳零逻辑直接渲染，规则 4）。

    白名单拒绝（ValueError）与 SQL 执行错误（如表/列不存在）都进信封；
    ``db_query`` 的 raise 契约不变（内核测试钉住）。
    """
    try:
        return db_query(sql, params, limit=limit, db_path=db_path)
    except ValueError as exc:
        return {"ok": False, "errors": [f"查询被拒绝: {exc}"], "sql": sql}
    except Exception as exc:  # sqlite OperationalError 等执行期错误
        return {"ok": False, "errors": [f"查询执行失败: {exc}"], "sql": sql}


# ---------------------------------------------------------------------------
# analytics_attach（DuckDB 直读 SQLite；best-effort，不可用如实返回）
# ---------------------------------------------------------------------------

def analytics_attach(sqlite_path: str | Path | None = None,
                     sample_limit: int = 3) -> dict[str, Any]:
    """用 DuckDB sqlite 扩展直读注册表文件（零拷贝分析面）。

    可用：附加为 ``reg``，逐表计数 + 最近 runs 示例查询；不可用（duckdb
    未安装 / sqlite 扩展不可加载）→ ok=False + reason，绝不 raise（#105）。
    """
    path = Path(sqlite_path) if sqlite_path is not None else default_registry_db_path()
    base: dict[str, Any] = {"path": str(path), "attached_as": "reg"}
    if not path.exists():
        return {"ok": False, "reason": f"注册表文件不存在: {path}", **base}
    try:
        import duckdb
    except ImportError as exc:
        return {"ok": False, "reason": f"duckdb 未安装: {exc}", **base}
    con = None
    try:
        con = duckdb.connect()
        try:
            con.execute("LOAD sqlite")
        except Exception as exc:
            return {"ok": False,
                    "reason": f"duckdb sqlite 扩展不可用: {exc}", **base}
        # 单引号转义防路径注入 ATTACH 语法
        literal = str(path).replace("'", "''")
        con.execute(f"ATTACH '{literal}' AS reg (TYPE sqlite)")
        tables: dict[str, int | None] = {}
        for t in REGISTRY_TABLES:
            try:
                tables[t] = int(con.execute(
                    f"SELECT COUNT(*) FROM reg.{t}").fetchone()[0])
            except Exception:
                tables[t] = None
        sample_runs: list[dict[str, Any]] = []
        try:
            rows = con.execute(
                "SELECT run_id, model, adapter, status, timestamp "
                "FROM reg.runs ORDER BY timestamp DESC LIMIT ?",
                [max(1, int(sample_limit))],
            ).fetchall()
            sample_runs = [
                {"run_id": r[0], "model": r[1], "adapter": r[2],
                 "status": r[3], "timestamp": r[4]}
                for r in rows
            ]
        except Exception:
            sample_runs = []
        version = getattr(duckdb, "__version__", "unknown")
        return {"ok": True, "duckdb_version": version, "tables": tables,
                "sample_runs": sample_runs, **base}
    except Exception as exc:
        return {"ok": False, "reason": f"attach/查询失败: {exc}", **base}
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()


# ---------------------------------------------------------------------------
# fidelity_shadow 联赛表（DP-13 Z2，runs/league.duckdb 最小建表）
# ---------------------------------------------------------------------------

#: 联赛表名与幂等键（run_id+engine+params_hash 先删后插 → 重跑行数不变）
LEAGUE_TABLE = "fidelity_shadow"
LEAGUE_IDEMPOTENCY_KEY = ("run_id", "engine", "params_hash")

#: 最小表结构（字段名即按 W1 提法对齐，specs §13.5）
LEAGUE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("engine", "VARCHAR"),
    ("template_family", "VARCHAR"),
    ("params_hash", "VARCHAR"),
    ("delta_vs_hfss_db", "DOUBLE"),
    ("wall_s", "DOUBLE"),
    ("mesh_mm", "DOUBLE"),
    ("run_id", "VARCHAR"),
)


def default_league_db_path() -> Path:
    """runs/league.duckdb 缺省路径（runs/ 已整体 gitignore，运行时 DB 不进 git）。"""
    return Path("runs") / "league.duckdb"


def _league_row_values(row: dict[str, Any]) -> tuple:
    values = []
    for col, _typ in LEAGUE_COLUMNS:
        v = row.get(col)
        values.append(None if v is None else float(v)
                      if _typ == "DOUBLE" else str(v))
    return tuple(values)


def record_fidelity_shadow(
    rows: list[dict[str, Any]],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """逐点 fidelity delta 写联赛表（幂等建表+幂等写；duckdb 缺失不 raise）。

    - 建表幂等：CREATE TABLE IF NOT EXISTS（已存在零变更）；
    - 写幂等：按 (run_id, engine, params_hash) 先删后插，同批重跑行数不变；
    - duckdb 未安装 / 打开失败 → ok=False + reason（#105 best-effort）；
    - 行缺幂等键（run_id/engine/params_hash 任一缺失）→ 整行拒收并如实计数。
    """
    path = Path(db_path) if db_path is not None else default_league_db_path()
    base: dict[str, Any] = {"db_path": str(path), "table": LEAGUE_TABLE}
    try:
        import duckdb
    except ImportError as exc:
        return {"ok": False, "reason": f"duckdb 未安装: {exc}", **base}

    valid: list[tuple] = []
    rejected: list[int] = []
    col_names = [c for c, _ in LEAGUE_COLUMNS]
    key_idx = [col_names.index(k) for k in LEAGUE_IDEMPOTENCY_KEY]
    for i, row in enumerate(rows):
        if any(not str(row.get(k) or "").strip()
               for k in LEAGUE_IDEMPOTENCY_KEY):
            rejected.append(i)
            continue
        valid.append(_league_row_values(row))

    con = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(path))
        cols = ", ".join(f"{c} {t}" for c, t in LEAGUE_COLUMNS)
        con.execute(f"CREATE TABLE IF NOT EXISTS {LEAGUE_TABLE} ({cols})")
        for values in valid:
            con.execute(
                f"DELETE FROM {LEAGUE_TABLE} WHERE run_id=? AND engine=? "
                "AND params_hash=?", [values[i] for i in key_idx])
            placeholders = ", ".join("?" for _ in LEAGUE_COLUMNS)
            con.execute(
                f"INSERT INTO {LEAGUE_TABLE} "
                f"({', '.join(c for c, _ in LEAGUE_COLUMNS)}) "
                f"VALUES ({placeholders})", list(values))
        n_total = int(con.execute(
            f"SELECT COUNT(*) FROM {LEAGUE_TABLE}").fetchone()[0])
        return {"ok": True, "n_rows_written": len(valid),
                "n_rows_rejected": len(rejected),
                "rejected_indexes": rejected,
                "n_rows_total": n_total, **base}
    except Exception as exc:
        return {"ok": False, "reason": f"联赛表写入失败: {exc}", **base}
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()


def query_fidelity_shadow(
    db_path: str | Path | None = None,
    *,
    run_id: str | None = None,
    engine: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """联赛表只读查询（SELECT；表不存在/duckdb 缺失 → ok=False 如实）。"""
    path = Path(db_path) if db_path is not None else default_league_db_path()
    base: dict[str, Any] = {"db_path": str(path), "table": LEAGUE_TABLE}
    if not path.exists():
        return {"ok": False, "reason": f"联赛库不存在: {path}", **base}
    try:
        import duckdb
    except ImportError as exc:
        return {"ok": False, "reason": f"duckdb 未安装: {exc}", **base}
    con = None
    try:
        con = duckdb.connect(str(path), read_only=True)
        where: list[str] = []
        params: list[str] = []
        if run_id is not None:
            where.append("run_id = ?")
            params.append(str(run_id))
        if engine is not None:
            where.append("engine = ?")
            params.append(str(engine))
        sql = f"SELECT {', '.join(c for c, _ in LEAGUE_COLUMNS)} FROM {LEAGUE_TABLE}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY engine, params_hash LIMIT ?"
        params.append(str(max(1, int(limit))))
        rows_raw = con.execute(sql, params).fetchall()
        cols = [c for c, _ in LEAGUE_COLUMNS]
        rows = [dict(zip(cols, r, strict=True)) for r in rows_raw]
        return {"ok": True, "rows": rows, "n_rows": len(rows), **base}
    except Exception as exc:
        return {"ok": False, "reason": f"联赛表查询失败: {exc}", **base}
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()
