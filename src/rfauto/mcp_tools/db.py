"""db_init/db_migrate/db_status/db_reindex_runs/db_query/db_analytics_attach（W1⑫ 注册表数据库薄壳）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 34. db 注册表薄壳（W1⑫ SQLite 事务型注册表 + DuckDB 分析直读） ──────────
# 六工具零逻辑转发 service/db_service（规则 4）；query 走只读 SELECT 白名单
# （拒绝进信封不抛出）；数值/物理语义不经过本层（铁律 7）。db_path 缺省
# 取 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite（相对当前工作目录）。

@mcp.tool
def db_init(db_path: str | None = None) -> dict[str, Any]:
    """注册表建库（db 域）：db_path → SQLite 建库+幂等迁移（applied 计数）。

    有副作用：创建/迁移 SQLite 文件（runs/ 已 gitignore）；等价 db_migrate，
    不用于状态盘点（走 db_status）。重放幂等 applied=0；I/O 失败 → ok=False
    信封。时序：先于 db_reindex_runs/query 消费面。

    Args:
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）

    Returns:
        dict: {ok, path, schema_version, applied, backend}
    """
    from rfauto.service.db_service import db_init as _db_init
    return _db_init(db_path)


@mcp.tool
def db_migrate(db_path: str | None = None) -> dict[str, Any]:
    """注册表幂等迁移（db 域）：schema_version 递增（重复执行零变更）。

    有副作用：迁移 SQLite 文件（不存在则创建）；不用于状态盘点（走
    db_status）。迁移失败 → ok=False 信封。时序：建库/升级后即可重放，
    幂等无顺序风险。

    Args:
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）

    Returns:
        dict: {ok, path, schema_version, applied, backend}
    """
    from rfauto.service.db_service import db_migrate as _db_migrate
    return _db_migrate(db_path)


@mcp.tool
def db_status(db_path: str | None = None) -> dict[str, Any]:
    """注册表状态盘点（db 域）：db_path → 存在性/schema 版本/各表行数。

    无副作用（文件不存在不创建）；不用于迁移（走 db_migrate）。
    探测异常 → ok=False 信封如实。只读无时序约束。

    Args:
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）

    Returns:
        dict: {ok, backend, path, exists, schema_version, tables: {表名: 行数}}
    """
    from rfauto.service.db_service import db_status as _db_status
    return _db_status(db_path)


@mcp.tool
def db_reindex_runs(runs_dir: str = "runs",
                    db_path: str | None = None) -> dict[str, Any]:
    """runs 重索引（db 域）：扫 runs/*/meta.json → runs 表 upsert 重建。

    有副作用：写注册表 runs 表（upsert 幂等可重放）；只登记 meta.json
    存在的 run，不猜无 meta 目录。单个 meta.json 失败不阻塞整体（#105），
    runs 目录不存在如实返回零值不建目录；失败清单进 errors 截断 20 条。
    时序：db_init/migrate 之后调用。

    Args:
        runs_dir: runs 目录（扫 */meta.json）
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）

    Returns:
        dict: {ok, reindexed, failed, errors(截断 20 条), db_path, note?}
    """
    from rfauto.service.db_service import reindex_runs
    return reindex_runs(runs_dir, db_path=db_path)


@mcp.tool
def db_query(
    sql: str,
    params: list[str | int | float | bool | None] | None = None,
    limit: int = 200,
    db_path: str | None = None,
) -> dict[str, Any]:
    """只读查询注册表：仅单条 SELECT + ? 占位符参数绑定（白名单纵深防御）。

    无副作用（只读）。非 SELECT/多语句/注释/禁用关键词/非法字符一律拒绝，
    拒绝原因与执行错误进 {ok: False, errors} 信封不抛出。行数上限 5000，
    超出截断并标记 truncated。示例：
    db_query("SELECT run_id, model FROM runs WHERE adapter = ?", ["hfss"])

    Args:
        sql: 单条只读 SELECT（? 占位符）
        params: 占位符标量参数列表（str/int/float/bool/null）
        limit: 返回行数上限（默认 200，最大 5000）
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）

    Returns:
        dict: {ok, columns, rows, row_count, truncated, limit} 或 {ok: False, errors, sql}
    """
    from rfauto.service.db_service import db_query_safe
    return db_query_safe(sql, params, limit=limit, db_path=db_path)


@mcp.tool
def db_analytics_attach(db_path: str | None = None,
                        sample_limit: int = 3) -> dict[str, Any]:
    """DuckDB sqlite 扩展直读注册表文件（零拷贝分析面）：逐表计数 + 最近 runs 示例。

    无副作用（只读附加为 reg）。duckdb 未装/扩展不可加载/文件不存在 →
    ok=False + reason 如实返回，绝不 raise（#105）。

    Args:
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）
        sample_limit: 示例查询最近 runs 条数

    Returns:
        dict: {ok, path, attached_as, duckdb_version, tables, sample_runs} 或
              {ok: False, reason, path, attached_as}
    """
    from rfauto.service.db_service import analytics_attach
    return analytics_attach(db_path, sample_limit=sample_limit)
