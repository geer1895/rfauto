"""lake_service.index —— runs/ 湖索引核心（DuckDB 建表/查询/计数/护栏）。

自 lake_service.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体自原节「runs/ 湖索引（DuckDB）」逐字节搬迁；本域同时承载共享文件系统/JSON/duckdb 助手（lineage/audit/pack/study 各域从这里单向导入，包内零环）。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from rfauto.infra.run_store import RUN_LINEAGE_DDL, RUN_LINEAGE_TABLE
from rfauto.service.envelope import error_envelope, ok_envelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# runs/ 湖索引（DuckDB）
# ---------------------------------------------------------------------------

#: DuckDB 防御性 PRAGMA 缺省值（P-5，research_expansion round3 §3.2）：
#: 湖索引是低频批处理面（重建/查询各一次连接），给小内存上限+单线程即够，
#: 防 DuckDB 缺省吃满机器内存/核数挤占在跑真机求解（#246 同源关切）。
DEFAULT_DUCKDB_MEMORY_LIMIT = "2GB"
DEFAULT_DUCKDB_THREADS = 4

#: 索引表名（查询面复用现有 DuckDB）
LAKE_INDEX_TABLE = "runs_lake_index"

#: 表结构：(列名, DuckDB 类型)。spec 必列 path/template/adapter/study/
#: created_ts/has_meta/has_verdict/size_bytes；run_id/campaign/depth/
#: status/created_date/meta_source/verdict/n_files 为实测可得补充字段
#: （created_ts 存 meta.timestamp 原文，created_date 是解析出的日期列，
#: 供日期段过滤；缺字段一律 NULL，不臆造）。
LAKE_INDEX_COLUMNS: tuple[tuple[str, str], ...] = (
    ("path", "VARCHAR"),        # 相对 runs_dir 的 posix 路径
    ("run_id", "VARCHAR"),      # 目录名（末段）
    ("campaign", "VARCHAR"),    # 二级点所属一级战役目录名；一级目录为 NULL
    ("depth", "INTEGER"),       # 1=runs/<dir>，2=runs/<campaign>/<dir>
    ("template", "VARCHAR"),    # meta.model
    ("adapter", "VARCHAR"),     # meta.adapter
    ("study", "VARCHAR"),       # meta.study_name
    ("status", "VARCHAR"),      # meta.status
    ("created_ts", "VARCHAR"),  # meta.timestamp 原文
    ("created_date", "DATE"),   # created_ts 解析出的日期（失败 NULL）
    ("has_meta", "BOOLEAN"),    # meta.json / run_meta.json 存在
    ("meta_source", "VARCHAR"), # "meta.json" | "run_meta.json" | NULL
    ("has_verdict", "BOOLEAN"), # verdict.json 存在
    ("verdict", "VARCHAR"),     # verdict.json 的 verdict 键（缺/解析失败 NULL）
    ("size_bytes", "BIGINT"),   # 目录实测总大小（递归求和）
    ("n_files", "BIGINT"),      # 目录实测文件数
    # XD-1（W3-B）血缘端点两列（meta 已落则读，缺如实 NULL 不臆造）：
    # git_sha=渲染/代码面 commit；render_input_sha256=渲染输入指纹（当前
    # 写点未落此 meta 键，列先行为 spec §10.2.4 查询输出端点预留）。
    ("git_sha", "VARCHAR"),     # meta.git_sha
    ("render_input_sha256", "VARCHAR"),  # meta.render_input_sha256（缺 NULL）
    # RB-WN-1 ③（W3-A）VF 摘要消费列：值=run 目录 sparams.vf.json 的
    # fidelity_class（NULL=无摘要），冷层查询按摘要质量过滤零解压；摘要
    # 本体读面走 lake_compact_service.read_sparams_summary。
    ("vf_summary", "VARCHAR"),  # "lossless_equivalent"|"bounded_lossy"|NULL
)

#: 索引库缺省落点（runs/ 已整体 gitignore，运行时 DB 不进 git）
DEFAULT_LAKE_INDEX_NAME = ".lake_index.duckdb"

_META_NAMES = ("meta.json", "run_meta.json")
_VERDICT_NAME = "verdict.json"


def default_lake_index_db_path() -> Path:
    """缺省索引库路径：``runs/.lake_index.duckdb``。"""
    return Path("runs") / DEFAULT_LAKE_INDEX_NAME


def _import_duckdb() -> Any:
    """duckdb 缺装显式报缺（extras dataset 已含，缺失提示装法）。"""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "duckdb 未安装：湖索引需要 pip install rfauto[dataset]"
            f"（{exc}）") from exc
    return duckdb


def configure_duckdb_connection(
    con: Any,
    *,
    memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    threads: int | None = DEFAULT_DUCKDB_THREADS,
) -> dict[str, Any]:
    """DuckDB 连接防御性 PRAGMA 封装（P-5，best-effort #105）。

    设 ``memory_limit``/``threads``，防 DuckDB 缺省吃满机器内存/核数挤占
    在跑真机求解（湖索引是低频批处理面，小配置即够）。逐 PRAGMA 独立
    try——单条失败（旧版不认/语法漂移）不阻塞主路径，失败项进 ``applied``
    如实标 False。**ART 索引坑注记**（round3 [33] DuckDB 官方配置文档）：
    本湖索引走 DROP+CREATE 全量重建（幂等口径见 build_runs_index），
    **不要**在索引表上建 ART 二级索引——每次重建索引会连带重建纯开销，
    且 DuckDB 索引不保证跨版本持久兼容；过滤加速靠 created_date 有序
    扫描即可（行量 <1e6 级）。

    Returns:
        dict: {"applied": {"memory_limit": bool, "threads": bool},
               "errors": [...]}（零逻辑消费面可直接进 JSON 信封）
    """
    applied: dict[str, bool] = {"memory_limit": False, "threads": False}
    errors: list[str] = []
    if memory_limit is not None:
        try:
            con.execute(f"SET memory_limit='{memory_limit}'")
            applied["memory_limit"] = True
        except Exception as exc:  # 单条 PRAGMA 失败不阻塞（#105）
            errors.append(f"memory_limit={memory_limit!r}: {exc}")
    if threads is not None:
        try:
            con.execute(f"SET threads={int(threads)}")
            applied["threads"] = True
        except Exception as exc:
            errors.append(f"threads={threads!r}: {exc}")
    return {"applied": applied, "errors": errors}


def _meta_file(run_dir: Path) -> Path | None:
    """run 目录的 meta 文件：meta.json 优先，run_meta.json 兜底。"""
    for name in _META_NAMES:
        candidate = run_dir / name
        if candidate.is_file():
            return candidate
    return None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """读 JSON 对象；缺失/解析失败/非对象一律 None（best-effort #105）。

    收窄（AU-3①）：预期异常面 = (OSError, ValueError)——文件缺失/权限
    OSError，坏 JSON（JSONDecodeError）与坏编码（UnicodeDecodeError）均
    ValueError 子类；非 dict 返回值同样如实 None。此外的异常类型（如深
    嵌套 RecursionError）如实上抛，由调用面单目录兜底接住留痕，不再静默。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("lake 索引读 JSON 失败（如实 None）: %s", path,
                     exc_info=exc)
        return None
    return data if isinstance(data, dict) else None


def _parse_date(raw: Any) -> Any:
    """ISO 时间戳字符串 → date（供日期段过滤）；解析失败 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _dir_stats(run_dir: Path) -> tuple[int, int]:
    """目录实测 (总字节数, 文件数)——os.scandir 递归，零写面。"""
    total = 0
    n_files = 0
    stack = [run_dir]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            n_files += 1
                    except OSError:
                        continue  # 单条目失败不阻塞（#105 best-effort）
        except OSError:
            continue
    return total, n_files


def _iter_run_dirs(root: Path):
    """扫 runs/ 两层：一级战役目录+二级 run 点，全部目录产出（元数据
    缺失如实 NULL）；产出 (run_dir, campaign_name_or_None, depth)。"""
    try:
        level1 = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return
    for top in level1:
        yield top, None, 1
        try:
            level2 = sorted(p for p in top.iterdir() if p.is_dir())
        except OSError:
            continue
        for sub in level2:
            yield sub, top.name, 2


def _index_row(run_dir: Path, campaign: str | None,
               depth: int, rel: str,
               meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """单目录索引行：实测可得字段全量收集，缺失字段 NULL。

    *meta* 可传调用方预读的 meta（XD-1 build 同 pass 复用一次读取，避免
    双 IO）；None 时自行读取，行为与旧签名完全一致。
    """
    meta_path = _meta_file(run_dir)
    if meta is None:
        meta = _read_json_object(meta_path) if meta_path is not None else None
    verdict_path = run_dir / _VERDICT_NAME
    has_verdict = verdict_path.is_file()
    verdict = (_read_json_object(verdict_path) or {}).get("verdict") \
        if has_verdict else None
    size, n_files = _dir_stats(run_dir)
    created_ts = meta.get("timestamp") if meta else None
    git_sha = meta.get("git_sha") if meta else None
    render_sha = meta.get("render_input_sha256") if meta else None
    # RB-WN-1 ③（W3-A）：摘要 fidelity_class（缺/坏如实 NULL）
    vf_summary = None
    vf_path = run_dir / "sparams.vf.json"
    if vf_path.is_file():
        vf_summary = (_read_json_object(vf_path) or {}).get("fidelity_class")
        vf_summary = str(vf_summary) if vf_summary is not None else None
    return {
        "path": rel,
        "run_id": run_dir.name,
        "campaign": campaign,
        "depth": depth,
        "template": str(meta.get("model")) if meta and meta.get("model") is not None else None,
        "adapter": str(meta.get("adapter")) if meta and meta.get("adapter") is not None else None,
        "study": str(meta.get("study_name")) if meta and meta.get("study_name") is not None else None,
        "status": str(meta.get("status")) if meta and meta.get("status") is not None else None,
        "created_ts": str(created_ts) if created_ts is not None else None,
        "created_date": _parse_date(created_ts),
        "has_meta": meta_path is not None,
        "meta_source": meta_path.name if meta_path is not None else None,
        "has_verdict": has_verdict,
        "verdict": str(verdict) if verdict is not None else None,
        "size_bytes": size,
        "n_files": n_files,
        "git_sha": str(git_sha) if git_sha is not None else None,
        "render_input_sha256": str(render_sha) if render_sha is not None else None,
        "vf_summary": vf_summary,
    }


def _lineage_edges_from_meta(
    meta: dict[str, Any] | None,
    child_run_id: str,
) -> list[tuple[str, str, str]]:
    """meta.derived_from → (child, parent, edge_kind) 边三元组列表。

    接受 meta 序列两形（写侧 _lineage_meta_form 的对称读面）：裸 run_id
    串（边种 derived）与 ``{"run_id", "edge_kind", "note"?}`` dict；非法
    项跳过如实（不阻塞不臆造）。child_run_id 取目录名（湖索引 run_id 同
    口径），meta.run_id 与目录名不一致时以目录名为准（join 键一致性）。
    """
    if not isinstance(meta, dict):
        return []
    raw = meta.get("derived_from")
    if raw is None:
        return []
    from rfauto.infra.run_store import normalize_derived_from

    entries, _warnings = normalize_derived_from(raw, "derived")
    return [(child_run_id, entry["run_id"], entry["edge_kind"])
            for entry in entries]


def _split_cycle_edges(
    edges: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """验环拆分（XD-1 风险①：A derived B derived A 递归 CTE 环——建表时
    拒入）。返回 (kept, rejected)：环上边（强连通分量size>1 内部边+自环）
    全部进 rejected，其余 kept。Tarjan SCC 迭代实现（边量可能上千克，
    避免递归深度爆栈）。"""
    if not edges:
        return [], []
    adj: dict[str, list[str]] = {}
    for child, parent, _kind in edges:
        adj.setdefault(child, []).append(parent)
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    scc_of: dict[str, int] = {}
    scc_sizes: dict[int, int] = {}

    for root in list(adj):
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            node, pi = work.pop()
            if pi == 0:
                index[node] = lowlink[node] = index_counter[0]
                index_counter[0] += 1
                stack.append(node)
                on_stack.add(node)
            recursed = False
            neighbors = adj.get(node, [])
            while pi < len(neighbors):
                nxt = neighbors[pi]
                pi += 1
                if nxt not in index:
                    work.append((node, pi))
                    work.append((nxt, 0))
                    recursed = True
                    break
                if nxt in on_stack:
                    lowlink[node] = min(lowlink[node], index[nxt])
            if recursed:
                continue
            if lowlink[node] == index[node]:
                members: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    scc_of[member] = index[node]
                    members.append(member)
                    if member == node:
                        break
                scc_sizes[index[node]] = len(members)
            if work:
                parent_node = work[-1][0]
                lowlink[parent_node] = min(lowlink[parent_node],
                                           lowlink[node])

    def _in_cycle(child: str, parent: str) -> bool:
        if child == parent:
            return True
        return scc_of.get(child) == scc_of.get(parent) \
            and scc_sizes.get(scc_of.get(child), 0) > 1

    kept = [e for e in edges if not _in_cycle(e[0], e[1])]
    rejected = [e for e in edges if _in_cycle(e[0], e[1])]
    return kept, rejected


def build_runs_index(
    runs_dir: str | Path = "runs",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """扫 runs/（一级+二级目录）重建 DuckDB 湖索引表（幂等可重放）。

    幂等口径：**重建=drop create**（``DROP TABLE IF EXISTS`` + ``CREATE
    TABLE`` + 全量 INSERT）——同 runs 重跑行数/内容不变，schema 一次建准
    不做增量迁移。行集=两层全部目录（一级战役目录+二级 run 点），字段只
    从实际存在的 meta.json/run_meta.json/verdict.json 读取，缺失如实
    NULL（不臆造，规格"存在才读，缺失跳过如实"）；单目录元数据解析失败
    不阻塞整体（#105），errors 留痕截断前 20 条。

    runs 目录不存在时如实返回零值不建库（reindex_runs 同款惯例）。
    返回 {"ok", "db_path", "table", "n_rows", "n_meta_rows",
    "n_verdict_rows", "errors"}；XD-1（W3-B）增列：
    - ``n_lineage_edges``：run_lineage 表实入边数（meta derived_from 扫描，
      环边拒入后）；0 边也建空表（schema 稳定，查询面不缺表）；
    - ``n_lineage_unknown_parent``：parent run_id 不在湖索引的孤儿边数
      （边保留不删——多报不放过方向 #316）；
    - ``lineage_unknown_parents``：孤儿 parent 样本（截断前 20）；
    - ``n_lineage_cycle_edges``：验环拒入边数（风险①：递归 CTE 环）。

    对拍钉（判据 3）：无环场景 n_lineage_edges = 全湖 derived_from 键计
    数；表重建=drop create 幂等（与索引表同口径）。
    """
    root = Path(runs_dir)
    base: dict[str, Any] = {
        "db_path": str(Path(db_path) if db_path is not None
                       else default_lake_index_db_path()),
        "table": LAKE_INDEX_TABLE,
    }
    lineage_zero: dict[str, Any] = {
        "n_lineage_edges": 0,
        "n_lineage_unknown_parent": 0,
        "lineage_unknown_parents": [],
        "n_lineage_cycle_edges": 0,
    }
    if not root.is_dir():
        return ok_envelope(
                   **{
                   "n_rows": 0,
                   "n_meta_rows": 0,
                   "n_verdict_rows": 0,
                   "errors": [],
                   **lineage_zero,
                   **base,
                   "note": f"runs 目录不存在: {root}",
                   },
               )
    try:
        duckdb = _import_duckdb()
    except RuntimeError as exc:
        return error_envelope([str(exc)], **{**lineage_zero, **base})

    rows: list[dict[str, Any]] = []
    edges: list[tuple[str, str, str]] = []
    errors: list[str] = []
    for run_dir, campaign, depth in _iter_run_dirs(root):
        try:
            rel = run_dir.relative_to(root).as_posix()
            meta_path = _meta_file(run_dir)
            meta = (_read_json_object(meta_path)
                    if meta_path is not None else None)
            rows.append(_index_row(run_dir, campaign, depth, rel, meta=meta))
            if meta is not None:
                edges.extend(_lineage_edges_from_meta(meta, run_dir.name))
        except Exception as exc:  # 单目录失败不阻塞（#105）
            if len(errors) < 20:
                errors.append(f"{run_dir}: {exc}")

    # 跨目录去重（同 basename run 点跨战役同父边=同三元组，PK 冲突会炸
    # 整表——图级不可区分，去重如实；对拍钉口径=去重后边数）+ 确定性排序
    edges = sorted(set(edges))
    kept_edges, cycle_edges = _split_cycle_edges(edges)
    index_run_ids = {row["run_id"] for row in rows}
    unknown_parents = sorted({parent for _c, parent, _k in kept_edges
                              if parent not in index_run_ids})

    con = None
    try:
        path = Path(base["db_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(path))
        configure_duckdb_connection(con)
        cols = ", ".join(f"{name} {typ}" for name, typ in LAKE_INDEX_COLUMNS)
        con.execute(f"DROP TABLE IF EXISTS {LAKE_INDEX_TABLE}")
        con.execute(f"CREATE TABLE {LAKE_INDEX_TABLE} ({cols})")
        names = [name for name, _typ in LAKE_INDEX_COLUMNS]
        placeholders = ", ".join("?" for _ in names)
        insert_sql = (f"INSERT INTO {LAKE_INDEX_TABLE} "
                      f"({', '.join(names)}) VALUES ({placeholders})")
        for row in rows:
            con.execute(insert_sql,
                        [row[name] for name in names])
        # XD-1：lineage 边表同 pass 重建（meta 为事实源，drop create 幂等）
        con.execute(f"DROP TABLE IF EXISTS {RUN_LINEAGE_TABLE}")
        con.execute(RUN_LINEAGE_DDL)
        for child, parent, kind in kept_edges:
            con.execute(
                f"INSERT INTO {RUN_LINEAGE_TABLE} "
                f"(child_run_id, parent_run_id, edge_kind) "
                f"VALUES (?, ?, ?)", [child, parent, kind])
        n_meta = sum(1 for row in rows if row["has_meta"])
        n_verdict = sum(1 for row in rows if row["has_verdict"])
        return ok_envelope(
                   **{
                   "n_rows": len(rows),
                   "n_meta_rows": n_meta,
                   "n_verdict_rows": n_verdict,
                   "errors": errors,
                   "n_lineage_edges": len(kept_edges),
                   "n_lineage_unknown_parent": len(unknown_parents),
                   "lineage_unknown_parents": unknown_parents[:20],
                   "n_lineage_cycle_edges": len(cycle_edges),
                   **base,
                   },
               )
    except Exception as exc:
        return error_envelope([f"索引写入失败: {exc}"], **{**lineage_zero, **base})
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()


def query_runs_index(
    db_path: str | Path | None = None,
    *,
    template: str | None = None,
    adapter: str | None = None,
    study: str | None = None,
    campaign: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
    order_by: str | None = None,
    order: str = "desc",
    depth: int | None = None,
    has_meta: bool | None = None,
    meta_source: str | None = None,
) -> dict[str, Any]:
    """湖索引只读参数化查询（等值过滤 + 日期段，``?`` 占位符绑定）。

    template/adapter/study/campaign 为等值过滤（空串/None 视为不过滤）；
    date_from/date_to 为 ``YYYY-MM-DD`` 闭区间（落在 created_date 列，
    非法日期 ValueError 信封）；行按 path 排序，limit 截断。
    返回 {"ok", "rows"(dict 列表), "n_rows", "db_path", "table"}；
    库不存在/duckdb 缺装 → ok=False 如实。

    SN-14（W6-A，2026-10-06）：``order_by`` 可选排序列（LAKE_INDEX_COLUMNS
    白名单，如 created_ts/size_bytes/n_files/template/status；None=既有
    path 排序零行为变化）；``order``=``asc``|``desc``（缺省 desc，仅
    order_by 给定时生效）。列名走白名单映射不进自由 SQL 文本面。

    S15（aurora_f W4，2026-10-18）批处理面消费三参（全 None=零行为变化）：
    ``depth``（1=runs/<dir>，2=runs/<campaign>/<dir>）、``has_meta``、
    ``meta_source``（"meta.json"|"run_meta.json"）——等值过滤，``?`` 绑定
    同防线；health/monitor/league 候选枚举接线走本查询（对齐后替换目录扫，
    缺行/滞后回退语义见 :func:`index_candidate_paths`）。
    """
    path = Path(db_path) if db_path is not None else default_lake_index_db_path()
    base: dict[str, Any] = {"db_path": str(path), "table": LAKE_INDEX_TABLE}
    order_col_sql: str | None = None
    if order_by is not None:
        valid_cols = {name for name, _typ in LAKE_INDEX_COLUMNS}
        if str(order_by) not in valid_cols:
            return error_envelope(
                [f"order_by 非法（须为索引列之一）: {order_by!r}"],
                **{"rows": [], "n_rows": 0, **base})
        if order not in ("asc", "desc"):
            return error_envelope(
                [f"order 只允许 asc|desc，收到 {order!r}"],
                **{"rows": [], "n_rows": 0, **base})
        order_col_sql = f"{order_by!s} {order}"
    if not path.exists():
        return error_envelope([f"湖索引库不存在（先 build_runs_index）: {path}"], **{"rows": [], "n_rows": 0, **base})
    try:
        duckdb = _import_duckdb()
    except RuntimeError as exc:
        return error_envelope([str(exc)], **{"rows": [], "n_rows": 0, **base})
    try:
        n_limit = max(1, int(limit))
    except (TypeError, ValueError):
        return error_envelope([f"limit 非法: {limit!r}"], **{"rows": [], "n_rows": 0, **base})

    clauses: list[tuple[str, Any]] = []
    for key, val in (("template", template), ("adapter", adapter),
                     ("study", study), ("campaign", campaign)):
        if val is None or val == "":
            continue
        if not isinstance(val, str):
            return error_envelope(
                       [f"{key} 必须是 str 或 None，"
                               f"收到 {type(val).__name__}"],
                       **{
                       "rows": [],
                       "n_rows": 0,
                       **base,
                       },
                   )
        clauses.append((f"{key} = ?", val))
    if depth is not None:
        if isinstance(depth, bool) or not isinstance(depth, int):
            return error_envelope(
                [f"depth 必须是 int 或 None，收到 {type(depth).__name__}"],
                **{"rows": [], "n_rows": 0, **base})
        clauses.append(("depth = ?", int(depth)))
    if has_meta is not None:
        if not isinstance(has_meta, bool):
            return error_envelope(
                [f"has_meta 必须是 bool 或 None，收到 {type(has_meta).__name__}"],
                **{"rows": [], "n_rows": 0, **base})
        clauses.append(("has_meta = ?", bool(has_meta)))
    if meta_source is not None:
        if not isinstance(meta_source, str) or meta_source == "":
            return error_envelope(
                [f"meta_source 必须是非空 str 或 None，"
                 f"收到 {type(meta_source).__name__}"],
                **{"rows": [], "n_rows": 0, **base})
        clauses.append(("meta_source = ?", str(meta_source)))
    try:
        if date_from is not None:
            clauses.append(("created_date >= ?", datetime.strptime(
                date_from, "%Y-%m-%d").date()))
        if date_to is not None:
            clauses.append(("created_date <= ?", datetime.strptime(
                date_to, "%Y-%m-%d").date()))
    except ValueError as exc:
        return error_envelope([f"日期段非法（YYYY-MM-DD）: {exc}"], **{"rows": [], "n_rows": 0, **base})

    # 参数化 WHERE：值只进 ? 绑定，永不拼进 SQL 文本（db_service 同款防线）
    where_parts = [clause for clause, _val in clauses]
    params = [val for _clause, val in clauses]
    names = [name for name, _typ in LAKE_INDEX_COLUMNS]
    order_sql = order_col_sql if order_col_sql is not None else "path"
    sql = (f"SELECT {', '.join(names)} FROM {LAKE_INDEX_TABLE}"
           + (" WHERE " + " AND ".join(where_parts) if where_parts else "")
           + f" ORDER BY {order_sql} LIMIT ?")
    params.append(n_limit)
    con = None
    try:
        con = duckdb.connect(str(path), read_only=True)
        configure_duckdb_connection(con)
        rows_raw = con.execute(sql, params).fetchall()
        rows = [dict(zip(names, r, strict=True)) for r in rows_raw]
        return ok_envelope(**{"rows": rows, "n_rows": len(rows), **base})
    except Exception as exc:
        errors = [f"湖索引查询失败: {exc}"]
        if "Binder" in str(exc) or "not found in FROM clause" in str(exc):
            # schema 演进（如 XD-1 增列）：旧索引库需 drop-create 重建
            errors.append("索引库 schema 疑似过时（先 rfauto lake index 重建）")
        return error_envelope(errors, **{"rows": [], "n_rows": 0, **base})
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()


# ---------------------------------------------------------------------------
# S15（aurora_f W4，2026-10-18）：批处理面候选枚举接线——lake index 主源
# + 计数护栏 + 目录扫回退（R3_perf_quality.md Top5；护栏 best-effort #105）
# ---------------------------------------------------------------------------

#: 护栏缺省阈值：|索引行数 − 目录数| > 阈值 → 判索引滞后回退目录扫。
#: 缺省 0=任何一行漂移即回退（宁慢勿错——回退路径=原有目录扫，行为不变）。
LAKE_INDEX_STALENESS_THRESHOLD = 0

#: 消费面信封注记值：enumeration_source（index=索引主源；dir_scan=回退）。
LAKE_INDEX_SOURCE_INDEX = "lake_index"
LAKE_INDEX_SOURCE_DIRSCAN = "dir_scan_fallback"


def lake_index_db_path_for(runs_dir: str | Path) -> Path:
    """runs_dir 对应的索引库路径（``<runs_dir>/.lake_index.duckdb``）。

    消费面按各自 runs_dir 推导索引库（与 build_runs_index 缺省落点同构），
    自定义 runs_dir（tmp 树/隔离域）天然指向自己的索引库。
    """
    return Path(runs_dir) / DEFAULT_LAKE_INDEX_NAME


def index_scope_dir_count(scope_dir: str | Path,
                          *, two_level: bool = False) -> int:
    """枚举域目录计数（护栏目录侧；裸 os.scandir 免 Path 包装开销）。

    实测（Win 本机 2280 一级目录）：裸 scandir 1.2ms vs Path.iterdir
    54ms——护栏必须比被替代的目录扫便宜才有意义。``two_level``=True 数
    两级（一级 + 各一级下的二级，league 域口径）；单目录 OSError 跳过
    如实（#105，与 _iter_run_dirs 同容错方向）。``is_dir`` 一律
    ``follow_symlinks=False``（审查波 2 P3-5 收账：与 _runs_fingerprint/
    _corpus_signature 同口径——symlink 目录不入计数，否则目录侧/索引侧
    在 runs/ 出现 symlink 目录时计数分叉 → 护栏误判滞后 → 无谓回退目录
    扫；方向安全但性能回退，一行对齐消音）。
    """
    root = Path(scope_dir)
    try:
        with os.scandir(root) as it:
            tops = [e for e in it if e.is_dir(follow_symlinks=False)]
    except OSError:
        return 0
    n = len(tops)
    if not two_level:
        return n
    for top in tops:
        try:
            with os.scandir(top.path) as sub:
                n += sum(1 for e in sub if e.is_dir(follow_symlinks=False))
        except OSError:
            continue
    return n


def count_runs_index(
    db_path: str | Path | None = None,
    *,
    depth: int | None = None,
    campaign: str | None = None,
) -> int | None:
    """索引行计数（护栏索引侧）；库缺/duckdb 缺/查询失败 → None 如实。

    计数口径与目录侧对齐：**不过滤 has_meta**（目录侧只数目录，meta
    存在与否不数）——行级漂移（新增/删除目录）即被捕捉。``?`` 绑定。
    """
    path = Path(db_path) if db_path is not None else default_lake_index_db_path()
    if not path.exists():
        return None
    try:
        duckdb = _import_duckdb()
    except RuntimeError:
        return None
    clauses: list[tuple[str, Any]] = []
    if depth is not None:
        if isinstance(depth, bool) or not isinstance(depth, int):
            return None
        clauses.append(("depth = ?", int(depth)))
    if campaign is not None and campaign != "":
        clauses.append(("campaign = ?", str(campaign)))
    where = (" WHERE " + " AND ".join(c for c, _v in clauses)
             if clauses else "")
    sql = f"SELECT COUNT(*) FROM {LAKE_INDEX_TABLE}{where}"
    con = None
    try:
        con = duckdb.connect(str(path), read_only=True)
        configure_duckdb_connection(con)
        return int(con.execute(
            sql, [v for _c, v in clauses]).fetchone()[0])
    except Exception:
        return None
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()


def index_candidate_paths(
    *,
    scope_dir: str | Path,
    depth: int | None = None,
    campaign: str | None = None,
    has_meta: bool | None = None,
    meta_source: str | None = None,
    two_level_dir_count: bool = False,
    db_path: str | Path | None = None,
    threshold: int = LAKE_INDEX_STALENESS_THRESHOLD,
    limit: int = 1_000_000,
) -> dict[str, Any]:
    """批处理面候选枚举探测：lake index 主源 + 滞后护栏 + 回退判定。

    消费契约（health_check_batch/monitor_cycle/league 三面同款）：
    1. 目录侧计数（:func:`index_scope_dir_count`，裸 scandir 毫秒级）；
    2. 索引侧计数（:func:`count_runs_index`）——**库缺/duckdb 缺/查询败
       → usable=False**（调用方回退原目录扫路径）；
    3. 计数差护栏：|index − dir| > ``threshold`` → usable=False + 告警
       注记（索引滞后如实）；
    4. 护栏过 → :func:`query_runs_index` 取候选相对路径（``?`` 绑定，
       查询败同样回退）。

    残余盲区如实声明（#105 best-effort 边界）：护栏覆盖**目录增删**类
    漂移（常见态=新 run 落地）；"既有目录内后补/删除 meta.json"不改行数，
    由索引重建周期（rfauto lake index）覆盖——消费面随后续逐候选读 meta
    时以实盘文件为准，不臆造。

    Returns:
        dict: ``{"usable", "paths"(相对 posix 路径列表，usable=False 时
        空列表), "warnings", "dir_count", "index_count"}``。
    """
    root = Path(scope_dir)
    warnings: list[str] = []
    dir_count = index_scope_dir_count(root, two_level=two_level_dir_count)
    unusable = {"usable": False, "paths": [], "warnings": warnings,
                "dir_count": dir_count, "index_count": None}
    index_count = count_runs_index(db_path=db_path, depth=depth,
                                   campaign=campaign)
    if index_count is None:
        warnings.append(
            f"湖索引不可用（库缺/查询失败），回退目录扫: scope={root}")
        return unusable
    unusable["index_count"] = index_count
    if abs(index_count - dir_count) > max(0, int(threshold)):
        warnings.append(
            f"索引滞后（index={index_count} 目录={dir_count} "
            f"差>{threshold}），回退目录扫（先 rfauto lake index 重建）")
        return unusable
    queried = query_runs_index(db_path, depth=depth, campaign=campaign,
                               has_meta=has_meta, meta_source=meta_source,
                               limit=limit)
    if not queried.get("ok"):
        warnings.append(
            f"湖索引查询失败，回退目录扫: {queried.get('errors')}")
        return unusable
    return {"usable": True,
            "paths": [str(row["path"]) for row in queried.get("rows", [])],
            "warnings": warnings,
            "dir_count": dir_count,
            "index_count": index_count}
