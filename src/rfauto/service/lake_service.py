"""lake_service —— runs/ 数据湖索引与分层压实 MVP（F3/df7）。

能力面（规格：方案池 F3；study 元组面
DA-1，研究扩充 round4 中件包三）：

- 索引：``build_runs_index`` 扫 runs/（一级战役目录+二级 run 点，两层
  目录**全部入索引**，目录级元数据如实留 NULL）入 DuckDB 表
  ``runs_lake_index``——查询面复用现有 DuckDB 惯例（连接管理/建表/只读
  参数化查询，参照 db_service.fidelity_shadow 同款）；``query_runs_index``
  按 template/adapter/study/campaign/日期段过滤，``?`` 占位符绑定，
  值永不拼进 SQL。
- 冷层压实：``pack_campaign`` 把战役目录打成 tar.zst + 偏移清单
  manifest JSON（每文件相对路径+offset+size+sha256，确定性文件排序+
  归一化 tar 头，同内容重打包 pack_sha256 逐位一致），原目录零改动
  （只读）。
- 内容寻址恢复：``verify_campaign`` 整包 sha256 快速校验 + 逐文件
  sha256 重算比对（偏移定位）；``restore_campaign`` 解包到**新目录**
  （目标已存在即拒——绝不覆盖），恢复后逐文件哈希复核。
- study 元组（DA-1）：extract_study_tuple 从单 run meta+trials 抽
  study→(template, target, budget) 元组（缺失字段 None 如实）；
  study_tuples_from_index 从已建索引按 study 名聚合元组；
  build_index_cli_entry 索引首建薄包装（计时统计，CLI 接线归出口批）。

绝不重写历史（#325/#326 golden 零改写同构）：本模块对 runs/ 既有内容
只读——build_runs_index 只读扫描，pack 只读打包，verify/restore 只读
归档；唯一写点是显式传入/缺省约定的 db_path、out_path 与 restore 的
target_dir（必须是不存在的新目录）。DVC/git-annex 判超配（单机无跨机
同步需求，不引入，规格原文）。

可选依赖：duckdb（dataset extra，索引/查询面缺装显式报缺）、zstandard
（冷层 tar.zst 压缩面缺装显式报缺）；其余路径不依赖二者。

分层：service 层（可 import infra）；CLI/MCP 接线本件不做（df7 另批，
报告登记缺口）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from rfauto.infra.run_store import (
    RUN_LINEAGE_DDL,
    RUN_LINEAGE_TABLE,
)
from rfauto.service.envelope import error_envelope, ok_envelope

logger = logging.getLogger(__name__)

__all__ = [
    "LAKE_INDEX_COLUMNS",
    "LAKE_INDEX_TABLE",
    "PACK_FORMAT",
    "RUN_LINEAGE_TABLE",
    "build_index_cli_entry",
    "build_runs_index",
    "configure_duckdb_connection",
    "default_lake_index_db_path",
    "export_index_parquet",
    "extract_study_tuple",
    "pack_campaign",
    "query_lineage",
    "query_runs_index",
    "render_lineage_md",
    "restore_campaign",
    "study_tuples_from_index",
    "sweep_runs",
    "verify_campaign",
    "verify_lineage",
]

# ---------------------------------------------------------------------------
# runs/ 湖索引（DuckDB）
# ---------------------------------------------------------------------------

#: DuckDB 防御性 PRAGMA 缺省值（P-5，研究扩充 round3 §3.2）：
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
# XD-1（W3-B）：跨 run lineage 三跳查询 + 边一致性校验 + md 缩进树渲染
# ---------------------------------------------------------------------------

#: lineage 查询跳数钳制带（spec 缺省 3；上界防 CTE 爆炸——风险③同源：
#: 直接同步的边未经建表验环，深度守卫保证递归必终止）。
LINEAGE_HOPS_MIN = 1
LINEAGE_HOPS_MAX = 10

_LINEAGE_NODE_COLUMNS = ("run_id", "campaign", "template", "status",
                         "created_ts", "git_sha", "render_input_sha256")


def query_lineage(
    db_path: str | Path | None = None,
    run_id: str = "",
    *,
    direction: str = "up",
    hops: int = 3,
    expand: bool = False,
    max_nodes: int = 200,
) -> dict[str, Any]:
    """跨 run 血缘查询（DuckDB ``WITH RECURSIVE`` 三跳展开，spec §10.2.3）。

    - ``direction="up"``（缺省）：反查血缘——数据集→上游 run→渲染 commit；
    - ``direction="down"``：影响面——某 run 被哪些下游数据集/报告消费
      （RB-ML-1 stale 联动 / RB-WN-1 保留白名单的第二信源）；
    - ``hops``：展开跳数上限（钳制 1-10，缺省 3）；
    - ``expand=False``（缺省）：明细 cap 在 *max_nodes*（边家族爆炸防护，
      风险③）+ ``children_count`` 摘要；``expand=True`` 展开全部明细。

    节点富化（join runs_lake_index）：model/template/git_sha/
    render_input_sha256/path/campaign——"数据集→run→脚本 commit"端点闭环
    （§10.2.4；render_input_sha256 当前写点未落 meta 键时如实 NULL）。
    孤儿 parent（不在湖索引）节点 in_lake=False、富化字段 NULL，边不删。

    返回 ok 信封：{run_id, direction, hops, n_nodes, n_nodes_total,
    children_count, n_edges_walked, truncated, expand, root, nodes,
    db_path, table}。
    """
    path = Path(db_path) if db_path is not None else default_lake_index_db_path()
    base: dict[str, Any] = {"db_path": str(path), "table": RUN_LINEAGE_TABLE}
    rid = str(run_id or "").strip()
    if not rid:
        return error_envelope(["--run 必填（起点 run id）"], **base)
    if direction not in ("up", "down"):
        return error_envelope([f"direction 只允许 up/down，收到 {direction!r}"],
                              **base)
    try:
        n_hops = int(hops)
    except (TypeError, ValueError):
        return error_envelope([f"hops 非法: {hops!r}"], **base)
    n_hops = max(LINEAGE_HOPS_MIN, min(LINEAGE_HOPS_MAX, n_hops))
    try:
        n_max = max(1, int(max_nodes))
    except (TypeError, ValueError):
        return error_envelope([f"max_nodes 非法: {max_nodes!r}"], **base)
    if not path.exists():
        return error_envelope([f"湖索引库不存在（先 rfauto lake index）: {path}"],
                              **base)
    duckdb = _import_duckdb()
    con = None
    try:
        con = duckdb.connect(str(path), read_only=True)
        configure_duckdb_connection(con)
        tables = {row[0] for row in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}
        if RUN_LINEAGE_TABLE not in tables:
            return error_envelope(
                [f"run_lineage 表不存在（先 rfauto lake index 建索引）: {path}"],
                **base)

        if direction == "up":
            seed_sql = (f"SELECT parent_run_id, edge_kind, 1 FROM "
                        f"{RUN_LINEAGE_TABLE} WHERE child_run_id = ?")
            step_sql = (f"SELECT l.parent_run_id, l.edge_kind, w.depth + 1 "
                        f"FROM {RUN_LINEAGE_TABLE} l "
                        f"JOIN walk w ON l.child_run_id = w.node_id "
                        f"WHERE w.depth < ?")
        else:
            seed_sql = (f"SELECT child_run_id, edge_kind, 1 FROM "
                        f"{RUN_LINEAGE_TABLE} WHERE parent_run_id = ?")
            step_sql = (f"SELECT l.child_run_id, l.edge_kind, w.depth + 1 "
                        f"FROM {RUN_LINEAGE_TABLE} l "
                        f"JOIN walk w ON l.parent_run_id = w.node_id "
                        f"WHERE w.depth < ?")
        walk_rows = con.execute(
            f"WITH RECURSIVE walk(node_id, edge_kind, depth) AS ( "
            f"{seed_sql} UNION ALL {step_sql}) "
            f"SELECT node_id, edge_kind, depth FROM walk",
            [rid, n_hops]).fetchall()

        # 富化面（runs_lake_index）缺失时降级：root/节点 in_lake=False
        # （直写桥单表库形态，边可查、meta 富化如实 NULL——#105）
        has_index = LAKE_INDEX_TABLE in tables
        root_row = None
        if has_index:
            root_row = con.execute(
                f"SELECT {', '.join(_LINEAGE_NODE_COLUMNS)} FROM "
                f"{LAKE_INDEX_TABLE} WHERE run_id = ? ORDER BY path LIMIT 1",
                [rid]).fetchone()
        children_count = int(con.execute(
            f"SELECT count(*) FROM {RUN_LINEAGE_TABLE} "
            f"WHERE parent_run_id = ?", [rid]).fetchone()[0])
    except Exception as exc:
        return error_envelope([f"血缘查询失败: {exc}"], **base)
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()

    # 去重：node → 最小深度（同深度并列取 edge_kind 字典序最小，确定性）
    best: dict[str, tuple[int, str]] = {}
    for node_id, edge_kind, depth in walk_rows:
        key = (int(depth), str(edge_kind))
        if node_id not in best or key < best[node_id]:
            best[node_id] = key
    n_total = len(best)
    ordered = sorted(((node, depth, kind)
                      for node, (depth, kind) in best.items()),
                     key=lambda t: (t[1], t[0]))
    truncated = (not expand) and n_total > n_max
    detail = ordered if expand else ordered[:n_max]

    enrich: dict[str, dict[str, Any]] = {}
    if detail and has_index:
        con = None
        try:
            con = duckdb.connect(str(path), read_only=True)
            configure_duckdb_connection(con)
            ph = ", ".join("?" for _ in detail)
            cols = ", ".join(_LINEAGE_NODE_COLUMNS)
            for row in con.execute(
                    f"SELECT {cols} FROM {LAKE_INDEX_TABLE} "
                    f"WHERE run_id IN ({ph}) ORDER BY path",
                    [node for node, _d, _k in detail]).fetchall():
                enrich.setdefault(str(row[0]), dict(
                    zip(_LINEAGE_NODE_COLUMNS, row, strict=True)))
        except Exception as exc:  # 富化失败降级为 in_lake=False（#105）
            logger.warning("lineage 节点富化失败（降级如实）: %s", exc)
            enrich = {}
        finally:
            if con is not None:
                with contextlib.suppress(Exception):
                    con.close()

    def _node_dict(node: str, depth: int, kind: str) -> dict[str, Any]:
        info = enrich.get(node) or {}
        return {
            "run_id": node,
            "depth": depth,
            "edge_kind": kind,
            "in_lake": bool(info),
            "path": info.get("path"),
            "campaign": info.get("campaign"),
            "model": info.get("template"),
            "git_sha": info.get("git_sha"),
            "render_input_sha256": info.get("render_input_sha256"),
        }

    root_info = dict(zip(_LINEAGE_NODE_COLUMNS, root_row, strict=True)) \
        if root_row else None
    root_node = {
        "run_id": rid,
        "in_lake": root_info is not None,
        "path": root_info.get("path") if root_info else None,
        "campaign": root_info.get("campaign") if root_info else None,
        "model": root_info.get("template") if root_info else None,
        "git_sha": root_info.get("git_sha") if root_info else None,
        "render_input_sha256":
            root_info.get("render_input_sha256") if root_info else None,
    }
    if not walk_rows and root_info is None:
        return error_envelope(
            [f"起点 {rid} 不在湖索引且零血缘边（先 rfauto lake index，"
             f"或核对 run id）"], **base)

    return ok_envelope(
        run_id=rid,
        direction=direction,
        hops=n_hops,
        n_nodes=len(detail) + 1,
        n_nodes_total=n_total + 1,
        children_count=children_count,
        n_edges_walked=len(walk_rows),
        truncated=truncated,
        expand=bool(expand),
        max_nodes=n_max,
        root=root_node,
        nodes=[_node_dict(node, depth, kind)
               for node, depth, kind in detail],
        **base)


def verify_lineage(db_path: str | Path | None = None) -> dict[str, Any]:
    """lineage 边一致性校验（spec §10.2.2 verify 挂点，判据 4）。

    child/parent 双向对湖索引 run_id 集：parent 不在湖=unknown_parent，
    child 不在湖=orphan_child；计数进报告、**边零删改**（多报不放过方向
    #316）。ok=调用成立（报告产出恒 ok）；完整性单列 ``consistent``：
    两类孤儿计数皆零=True（audit-stale 同款——计数进报告，判定归消费方），
    孤儿样本各截断前 20 条。

    返回 {ok, consistent, n_edges, n_unknown_parent, unknown_parents,
    n_orphan_child, orphan_children, db_path, table}；库/表缺失 →
    ok=False + errors。
    """
    path = Path(db_path) if db_path is not None else default_lake_index_db_path()
    base: dict[str, Any] = {"db_path": str(path), "table": RUN_LINEAGE_TABLE}
    if not path.exists():
        return error_envelope([f"湖索引库不存在（先 rfauto lake index）: {path}"],
                              **base)
    duckdb = _import_duckdb()
    con = None
    try:
        con = duckdb.connect(str(path), read_only=True)
        configure_duckdb_connection(con)
        tables = {row[0] for row in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}
        if RUN_LINEAGE_TABLE not in tables or LAKE_INDEX_TABLE not in tables:
            return error_envelope(
                [f"表缺失（需 {LAKE_INDEX_TABLE}+{RUN_LINEAGE_TABLE}，"
                 f"先 rfauto lake index 建索引）: {path}"], **base)
        edge_rows = con.execute(
            f"SELECT child_run_id, parent_run_id, edge_kind "
            f"FROM {RUN_LINEAGE_TABLE}").fetchall()
        index_ids = {str(row[0]) for row in con.execute(
            f"SELECT run_id FROM {LAKE_INDEX_TABLE}").fetchall()}
    except Exception as exc:
        return error_envelope([f"lineage 校验查询失败: {exc}"], **base)
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()
    unknown_parents = sorted({parent for _c, parent, _k in edge_rows
                              if parent not in index_ids})
    orphan_children = sorted({child for child, _p, _k in edge_rows
                              if child not in index_ids})
    n_unknown = len(unknown_parents)
    n_orphan = len(orphan_children)
    # ok=调用成立（报告产出）；完整性单列 consistent（孤儿边是如实红像，
    # 不是查询失败——audit-stale 同款：计数进报告，判定归消费方）
    return ok_envelope(
        consistent=n_unknown == 0 and n_orphan == 0,
        n_edges=len(edge_rows),
        n_unknown_parent=n_unknown,
        unknown_parents=unknown_parents[:20],
        n_orphan_child=n_orphan,
        orphan_children=orphan_children[:20],
        **base)


def render_lineage_md(result: dict[str, Any]) -> str:
    """query_lineage 结果 → md 缩进树（spec §10.2.3 md 形态：run_id+model+
    git_sha+edge_kind）。纯文本渲染（服务层数据解释，规则 4）；节点按
    depth 缩进两空格，截断时尾行如实注记。"""
    root = result.get("root") or {}
    lines: list[str] = []
    head = str(root.get("run_id") or result.get("run_id") or "?")
    head_parts = [head]
    if root.get("model"):
        head_parts.append(f"model={root['model']}")
    if root.get("git_sha"):
        head_parts.append(f"git_sha={root['git_sha']}")
    head_parts.append("(起点)" if root.get("in_lake") else "(起点，不在湖索引)")
    lines.append("  ".join(head_parts))
    for node in result.get("nodes") or []:
        indent = "  " * int(node.get("depth") or 1)
        parts = [f"└─ {node.get('run_id')}"]
        parts.append(f"depth={node.get('depth')}")
        parts.append(f"edge_kind={node.get('edge_kind')}")
        if node.get("model"):
            parts.append(f"model={node['model']}")
        if node.get("git_sha"):
            parts.append(f"git_sha={node['git_sha']}")
        if node.get("render_input_sha256"):
            parts.append(f"render_sha={str(node['render_input_sha256'])[:12]}")
        if not node.get("in_lake"):
            parts.append("(不在湖索引)")
        lines.append(indent + "  ".join(parts))
    tail = (f"n_nodes_total={result.get('n_nodes_total')}  "
            f"children_count={result.get('children_count')}  "
            f"hops={result.get('hops')}  direction={result.get('direction')}")
    if result.get("truncated"):
        tail += (f"  （明细已截断至 {result.get('max_nodes')}，"
                 f"--expand 展开）")
    lines.append(tail)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# QW-13 lake sweep：incomplete/半产物只读清点（DP-9 gc 视角，零改写）
# ---------------------------------------------------------------------------

#: sweep 判"半产物"的证据文件（存在即记原因；判定只读文件存在性，
#: 不解析不臆造状态——#144：在跑 run 的形态恰是"有 trials/无 meta"）。
_SWEEP_PRODUCT_MARKERS: tuple[tuple[str, str], ...] = (
    ("trials", "有 trials/ 无 meta（在跑或中断，meta 结束才落盘）"),
    ("samples.json", "有 samples.json 无 meta"),
    ("sparams.csv", "有 sparams.csv 无 meta"),
    ("calib.json", "有 calib.json 无 meta"),
)


def sweep_runs(runs_dir: str | Path = "runs",
               *, max_list: int = 200) -> dict[str, Any]:
    """runs/ 只读清点报告（QW-13：incomplete 标记/半产物 gc 视角）。

    分类口径（只读文件存在性，零改写零移动——与 pack/restore 同款红线）：
    - ``container``：一级战役目录且含子目录（容器位，不进四分类——战役
      层无 meta 属正常形态；run 点内的 trials/ 子目录不算容器，恰是
      #144 在跑形态的证据面）；n_dirs 含容器，四桶之和=n_dirs-n_containers；
    - ``complete``：meta 文件在（meta.json/run_meta.json 任一）；
    - ``empty``：目录零文件（空壳战役位/废弃位）；
    - ``incomplete``：无 meta 但有产物证据（trials//samples.json/
      sparams.csv/calib.json 任一）——在跑（#144 形态）或中断半产物；
    - ``unannotated``：无 meta 且无任何已知产物证据（仅杂项文件）。
    判定信息只有文件存在性与实测体积，缺失字段如实省略不臆造。

    Returns:
        dict: {"ok", "runs_dir", "n_dirs", "n_containers", "n_complete",
               "n_incomplete", "n_empty", "n_unannotated",
               "incomplete": [{path, campaign, depth, n_files, size_bytes,
               markers, reasons}], "errors"}
    """
    root = Path(runs_dir)
    base: dict[str, Any] = {"runs_dir": str(root)}
    if not root.is_dir():
        return ok_envelope(
                   **{
                   "n_dirs": 0,
                   "n_containers": 0,
                   "n_complete": 0,
                   "n_incomplete": 0,
                   "n_empty": 0,
                   "n_unannotated": 0,
                   "incomplete": [],
                   "errors": [],
                   **base,
                   "note": f"runs 目录不存在: {root}",
                   },
               )
    counts = {"complete": 0, "incomplete": 0, "empty": 0, "unannotated": 0}
    n_containers = 0
    incomplete_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for run_dir, campaign, depth in _iter_run_dirs(root):
        try:
            rel = run_dir.relative_to(root).as_posix()
            size, n_files = _dir_stats(run_dir)
            has_children = any(p.is_dir() for p in run_dir.iterdir())
        except Exception as exc:  # 单目录失败不阻塞（#105）
            if len(errors) < 20:
                errors.append(f"{run_dir}: {exc}")
            continue
        if depth == 1 and has_children:
            n_containers += 1
            continue
        if _meta_file(run_dir) is not None:
            counts["complete"] += 1
            continue
        if n_files == 0:
            counts["empty"] += 1
            continue
        markers: list[str] = []
        reasons: list[str] = []
        for name, reason in _SWEEP_PRODUCT_MARKERS:
            if (run_dir / name).exists():
                markers.append(name)
                reasons.append(reason)
        row: dict[str, Any] = {
            "path": rel, "campaign": campaign, "depth": depth,
            "n_files": n_files, "size_bytes": size, "markers": markers,
            "reasons": reasons,
        }
        if markers:
            counts["incomplete"] += 1
            if len(incomplete_rows) < max_list:
                incomplete_rows.append(row)
        else:
            counts["unannotated"] += 1
    return ok_envelope(
               **{
               "n_dirs": sum(counts.values()) + n_containers,
               "n_containers": n_containers,
               "n_complete": counts["complete"],
               "n_incomplete": counts["incomplete"],
               "n_empty": counts["empty"],
               "n_unannotated": counts["unannotated"],
               "incomplete": incomplete_rows,
               "errors": errors,
               **base,
               },
           )


# ---------------------------------------------------------------------------
# XD-9：湖陈旧审计（audit-stale——Snakemake --list-code-changes 的湖级版）
# ---------------------------------------------------------------------------
# 只读承诺：零写系统（对 runs/ 与 .rfauto_cache/ 只读；输出由调用方落盘）。
# 失效判定复用 infra/dag_cache 的键成分语义（TRIGGER_OF_COMPONENT 四类：
# code/params/budget/env），meta 缺失目录（在跑/半途 #144）如实单列 unknown。

#: config-diff 键 → budget 类（网格/预算档变化按 #343/#262 族语义单列）。
_AUDIT_BUDGET_META_KEYS: frozenset[str] = frozenset(
    {"mesh_config", "budget_tier", "mesh_resolution_mm"})


def _audit_git_head(cwd: str | Path | None = None) -> str:
    """当前 HEAD 短 SHA（best-effort #105：非 git 环境/失败 → 空串不抛穿）。"""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=30,
            cwd=str(cwd) if cwd else None)
        sha = (out.stdout or "").strip()
        return sha if out.returncode == 0 and sha else ""
    except Exception:
        return ""


def _audit_norm(path: str | Path) -> str:
    """run_dir 归一键（#318：Windows 大小写/分隔符 normcase 比较）。"""
    import os

    return os.path.normcase(str(Path(path).resolve()))


def _audit_dag_components(
    cache_dir: str | Path | None,
) -> dict[str, dict[str, str]]:
    """扫 dag 索引（DagCasIndex 落盘面），run_dir 归一 → 键成分表。

    索引目录缺失/条目损坏逐条跳过（best-effort，#105）——audit 退化为
    纯 meta 面判定，不阻塞。
    """
    import json as _json

    base = Path(cache_dir) if cache_dir else Path(".rfauto_cache") / "dag"
    out: dict[str, dict[str, str]] = {}
    if not base.is_dir():
        return out
    for child in sorted(base.glob("*.json")):
        try:
            data = _json.loads(child.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        run_dir = str(data.get("run_dir") or "")
        comps = data.get("components")
        if run_dir and isinstance(comps, dict):
            out.setdefault(_audit_norm(run_dir),
                           {str(k): str(v) for k, v in comps.items()})
    return out


def _audit_engine_record(meta: dict[str, Any]) -> str:
    """meta 面引擎版本记录（dag 成分缺档时的回退源；无记录 → 空串）。"""
    sv = meta.get("solver_versions")
    if isinstance(sv, dict) and sv:
        return _canonical_dump(sv)
    adapter = str(meta.get("adapter") or "")
    if adapter.startswith("hfss"):
        return str(meta.get("aedt_version") or "")
    if "ads" in adapter:
        return str(meta.get("ads_version") or "")
    return ""


def _canonical_dump(obj: Any) -> str:
    """稳定 JSON 串（dag_cache.canonical_json 只读复用，惰性导入）。"""
    from rfauto.infra.dag_cache import canonical_json

    return canonical_json(obj)


def normalize_config_diff(raw: Any) -> tuple[dict[str, Any], str]:
    """config-diff 载荷归一为 键→新值 映射（新值 None=只声明键变化）。

    接受三形：{"keys": [k, …]}；{"keys": {k: 新值或 {"old","new"}}}；
    扁平 {k: 新值或 {"old","new"}}。空输入（None/空对象/空键表）=合法
    零变化 → 空映射（判据 1 双态钉：空 diff 输入→清单为空）；非法
    （非 dict 非空）→ error 串。
    """
    if raw is None:
        return {}, ""
    if not isinstance(raw, dict):
        return {}, f"config-diff 必须是 JSON 对象，得到 {type(raw).__name__}"
    body: Any = raw
    if "keys" in raw and isinstance(raw["keys"], (list, dict)):
        body = raw["keys"]
    if isinstance(body, list):
        pairs: dict[str, Any] = {str(k): None for k in body}
    elif isinstance(body, dict):
        pairs = {}
        for k, v in body.items():
            if isinstance(v, dict) and "new" in v:
                pairs[str(k)] = v["new"]
            else:
                pairs[str(k)] = v
    else:
        return {}, "config-diff keys 必须是列表或对象"
    return pairs, ""


def audit_stale_runs(
    runs_dir: str | Path = "runs",
    *,
    render_commit: str | None = None,
    engine_version: str | None = None,
    config_diff: Any = None,
    cache_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
    max_detail: int = 200,
    max_depth: int | None = 6,
) -> dict[str, Any]:
    """湖陈旧审计（XD-9：给定当前成分，扫全湖列将失效 run 清单+原因分类）。

    三选择器（可组合）：
    - ``render_commit``：代码面（meta.git_sha 对照；缺省=当前 HEAD）——
      不一致=code 类（Snakemake --list-code-changes 湖级语义）；
    - ``engine_version``：引擎面——与 run 的 dag 键成分 engine_version
      对照（缺档回退 meta solver_versions/aedt/ads 记录；两处皆无=不可比，
      如实计 no_engine_record 不 inflate）——不一致=engine 类；
    - ``config_diff``：配置面（normalize_config_diff 三形）——变化的键
      命中 meta 顶键且值可对且不等 → params 类（网格/预算键 → budget 类）；
      键不在 meta → unmatched 计数不 inflate；有 dag 成分的 run 顺带比
      env_fingerprint_sha（commit 推进即 env 失效是设计语义）→ env 类。

    缺 meta 目录（在跑/半途 #144）→ unknown 清单单列。纯读零写（判据 3）；
    退出语义由 CLI 映射（0 无失效 / 1 有失效 / 2 程序性错误）。
    """
    root = Path(runs_dir)
    base: dict[str, Any] = {"runs_dir": str(root)}
    if not root.is_dir():
        return error_envelope([f"runs 目录不存在: {root}"], **base)
    pairs, diff_err = normalize_config_diff(config_diff)
    if diff_err:
        return error_envelope([diff_err], **base)

    head = _audit_git_head(repo_root or root)
    code_ref = str(render_commit) if render_commit else head
    comps_by_dir = _audit_dag_components(cache_dir)

    current_env_sha: str | None = None

    def _env_sha() -> str:
        nonlocal current_env_sha
        if current_env_sha is None:
            from rfauto.infra.dag_cache import canonical_json, env_fingerprint, sha256_text

            root_guess = Path(repo_root) if repo_root else (
                Path(__file__).resolve().parents[3])
            current_env_sha = sha256_text(
                canonical_json(env_fingerprint(root_guess)))
        return current_env_sha

    class_counts = {"code": 0, "params": 0, "engine": 0, "env": 0,
                    "budget": 0}
    n_checked = 0
    n_stale = 0
    n_unknown = 0
    n_no_engine_record = 0
    n_config_key_unmatched = 0
    stale_rows: list[dict[str, Any]] = []
    unknown_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    # 递归走湖（run 点 meta 可嵌在战役/批次多层下，两层 _iter_run_dirs
    # 覆盖不了——实测湖内 meta 大多在 3-4 层）；run 点内部子目录
    # （trials//fdtd/ 等产物位）不再按 unknown 计（其 meta 语义归属父
    # run 点）。unknown 口径对齐 sweep_runs 半途形态（_SWEEP_PRODUCT_MARKERS）。
    import os

    suppress_unknown: set[str] = set()
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d != "__pycache__"]
        here = Path(dirpath)
        try:
            depth = len(here.relative_to(root).parts)
        except ValueError:
            depth = 0
        if max_depth is not None and depth >= max_depth:
            dirnames[:] = []
        has_meta = _meta_file(here) is not None
        if not has_meta:
            if (_audit_norm(here) != _audit_norm(root)
                    and _audit_norm(here) not in suppress_unknown
                    and any((here / name).exists()
                            for name, _ in _SWEEP_PRODUCT_MARKERS)):
                n_unknown += 1
                if len(unknown_rows) < max_detail:
                    unknown_rows.append({
                        "path": here.relative_to(root).as_posix(),
                        "reason": "无 meta 但有产物证据（在跑或半途，#144 形态）"})
            continue
        # run 点：子目录视为内部产物位，不再报 unknown
        for d in dirnames:
            suppress_unknown.add(_audit_norm(here / d))
        meta = _read_json_object(_meta_file(here))
        if meta is None:  # meta 文件在但不可解析（损坏）——如实进 unknown
            n_unknown += 1
            if len(unknown_rows) < max_detail:
                unknown_rows.append({
                    "path": here.relative_to(root).as_posix(),
                    "reason": "meta 文件不可解析（损坏）"})
            continue
        n_checked += 1
        rel = here.relative_to(root).as_posix()
        campaign = rel.split("/", 1)[0] if "/" in rel else None
        classes: list[str] = []
        reasons: list[str] = []

        if code_ref:
            run_sha = str(meta.get("git_sha") or "")
            if run_sha and run_sha != code_ref:
                classes.append("code")
                reasons.append(
                    f"git_sha {run_sha} != 当前 {code_ref}（渲染/代码面已变）")

        comps = comps_by_dir.get(_audit_norm(here)) or {}
        if engine_version:
            stored_engine = str(comps.get("engine_version") or "") \
                or _audit_engine_record(meta)
            if stored_engine:
                if stored_engine != engine_version:
                    classes.append("engine")
                    reasons.append(
                        "engine_version "
                        f"{stored_engine[:24]} != 当前 {engine_version[:24]}")
            else:
                n_no_engine_record += 1

        stored_env = str(comps.get("env_fingerprint_sha") or "")
        if stored_env and stored_env != _env_sha():
            classes.append("env")
            reasons.append("env_fingerprint_sha 与当前环境不一致（git/依赖面）")

        for key, new_val in pairs.items():
            if key not in meta:
                n_config_key_unmatched += 1
                continue
            if new_val is None:
                continue  # 只声明键变化、未给新值：不可比，不计失效
            if str(meta[key]) != str(new_val):
                cls = "budget" if key in _AUDIT_BUDGET_META_KEYS else "params"
                classes.append(cls)
                reasons.append(
                    f"{key}: {str(meta[key])[:24]} -> {str(new_val)[:24]}")

        if classes:
            n_stale += 1
            for c in classes:
                class_counts[c] += 1
            if len(stale_rows) < max_detail:
                stale_rows.append({"path": rel, "campaign": campaign,
                                   "classes": classes,
                                   "reasons": reasons})
    return ok_envelope(
        n_dirs=n_checked + n_unknown,
        n_checked=n_checked,
        n_stale=n_stale,
        n_fresh=n_checked - n_stale,
        n_unknown_meta=n_unknown,
        class_counts=class_counts,
        n_no_engine_record=n_no_engine_record,
        n_config_key_unmatched=n_config_key_unmatched,
        stale=stale_rows,
        unknown=unknown_rows[:max_detail],
        selectors={"render_commit": code_ref or None,
                   "render_commit_source":
                       "explicit" if render_commit else ("git-head" if head else "unavailable"),
                   "engine_version": engine_version,
                   "config_keys": sorted(pairs)},
        errors=errors,
        **base)


# ---------------------------------------------------------------------------
# P-5 冷层导出：索引表 COPY parquet（hive 分区接口）
# ---------------------------------------------------------------------------

def export_index_parquet(
    db_path: str | Path | None = None,
    out_dir: str | Path | None = None,
    *,
    partition_by: str | None = "created_date",
    overwrite: bool = False,
) -> dict[str, Any]:
    """湖索引表 → parquet 冷层（``COPY … TO … (FORMAT PARQUET,
    PARTITION_BY …)`` hive 分区接口，P-5）。

    冷层语义：索引库（.lake_index.duckdb）是易失查询面，parquet 目录是
    可被外部引擎（pandas/pyarrow/其他 DuckDB）直读的归档面；本接口只从
    **已建索引**导出，不重扫 runs/（建索引走 build_runs_index）。分区列
    缺省 created_date（NULL 分区行 DuckDB 落 ``__HIVE_DEFAULT_PARTITION__``
    ——属正常产物，如实注记不清洗）；零防御配置例外：导出连接同样走
    configure_duckdb_connection（best-effort）。只读索引库+新写 out_dir，
    原目录零改动红线不变。

    Returns:
        dict: {"ok", "db_path", "out_dir", "n_rows", "partition_by",
               "files", "errors"}（行数=导出后 SELECT count(*) 复核）
    """
    path = Path(db_path) if db_path is not None else default_lake_index_db_path()
    base: dict[str, Any] = {"db_path": str(path),
                            "out_dir": str(Path(out_dir) if out_dir is not None
                                            else path.with_suffix(".parquet")),
                            "partition_by": partition_by}
    if not path.is_file():
        return error_envelope(
            [f"湖索引库不存在（先 build_runs_index）: {path}"],
            n_rows=0, files=[], **base)
    duckdb = _import_duckdb()
    con = None
    try:
        out = Path(base["out_dir"])
        out.mkdir(parents=True, exist_ok=overwrite)
        con = duckdb.connect(str(path), read_only=True)
        configure_duckdb_connection(con)
        names = [name for name, _typ in LAKE_INDEX_COLUMNS]
        partition_sql = (f", PARTITION_BY ({partition_by})"
                         if partition_by else "")
        overwrite_sql = ", OVERWRITE_OR_IGNORE true" if overwrite else ""
        con.execute(
            f"COPY (SELECT {', '.join(names)} FROM {LAKE_INDEX_TABLE}) "
            f"TO '{out.as_posix()}' (FORMAT PARQUET{partition_sql}"
            f"{overwrite_sql})")
        n_rows = int(con.execute(
            f"SELECT count(*) FROM {LAKE_INDEX_TABLE}").fetchone()[0])
        files = sorted(str(p.relative_to(out).as_posix())
                       for p in out.rglob("*.parquet"))
        return ok_envelope(
                   **{
                   "n_rows": n_rows,
                   "files": files,
                   **base,
                   "note": "hive 分区目录可被 pandas/pyarrow/duckdb 直读；"
                         "NULL 分区列落 __HIVE_DEFAULT_PARTITION__ 属正常产物",
                   },
               )
    except Exception as exc:
        return error_envelope(
            [f"冷层导出失败: {exc}"], n_rows=0, files=[], **base)
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()

#: 偏移清单格式标识（schema 演进锚）
PACK_FORMAT = "rfauto-lake-pack-v1"


def _import_zstandard() -> Any:
    """zstandard 缺装显式报缺（tar.zst 压缩面；pip install zstandard）。"""
    try:
        import zstandard
    except ImportError as exc:
        raise RuntimeError(
            "zstandard 未安装：冷层 tar.zst 压实需要 "
            f"pip install zstandard（{exc}）") from exc
    return zstandard


def _sha256_file(path: Path, _buf_size: int = 1 << 20) -> str:
    """文件流式 sha256（hex）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_buf_size):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_files(campaign_dir: Path) -> list[tuple[str, Path]]:
    """战役目录全部文件的确定性清单：相对 posix 路径排序（规格"确定性
    排序文件列表"），返回 [(rel_posix, absolute_path)]。"""
    entries: list[tuple[str, Path]] = []
    for current, _dirnames, filenames in os.walk(campaign_dir):
        for filename in filenames:
            abs_path = Path(current) / filename
            entries.append(
                (abs_path.relative_to(campaign_dir).as_posix(), abs_path))
    entries.sort(key=lambda pair: pair[0])
    return entries


def _manifest_path_for(out_path: Path) -> Path:
    """偏移清单缺省落点：<pack>.manifest.json。"""
    return Path(str(out_path) + ".manifest.json")


def _safe_rel_path(rel: str) -> PurePosixPath | None:
    """清单相对路径守卫：拒绝绝对路径/穿越/盘符/反斜杠（restore 写面前
    最后一道防线；pack 侧清单由本模块生成天然安全）。"""
    if not rel or "\\" in rel:
        return None
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts or pure.drive:
        return None
    return pure


def pack_campaign(
    campaign_dir: str | Path,
    out_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """战役目录 → tar.zst + 偏移清单（只读原目录，零改动）。

    - 文件清单确定性排序（相对 posix 路径全序），tar 头归一化
      （mtime=0/uid=gid=0/uname=gname 空）→ 同内容重打包 pack_sha256
      逐位一致；
    - 偏移清单 JSON：每文件 {path, offset(tar 流内数据起始字节),
      size, sha256} + 整包 pack_sha256（内容寻址锚，verify 快速路径）；
    - 原目录只读；写面仅 out_path 与 manifest（缺省
      ``<out>.manifest.json``）。

    返回 {"ok", "pack_path", "manifest_path", "n_files", "total_bytes",
    "pack_sha256", "pack_size_bytes"}；目录不存在/无文件/缺 zstandard →
    ok=False 如实。
    """
    src = Path(campaign_dir)
    base: dict[str, Any] = {
        "pack_path": str(out_path),
        "manifest_path": str(manifest_path
                             if manifest_path is not None
                             else _manifest_path_for(Path(out_path))),
    }
    if not src.is_dir():
        return error_envelope([f"战役目录不存在: {src}"], **base)
    try:
        zstandard = _import_zstandard()
    except RuntimeError as exc:
        return error_envelope([str(exc)], **base)
    files = _collect_files(src)
    if not files:
        return error_envelope([f"战役目录无文件（拒绝打空 tar）: {src}"], **base)

    out = Path(out_path)
    manifest_path_obj = Path(base["manifest_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest_path_obj.parent.mkdir(parents=True, exist_ok=True)
    tmp_tar: str | None = None
    try:
        # ① 未压缩 tar 落临时文件（确定性头），② 回读取逐成员 offset_data
        # （tarfile 自身记账，含 PAX 头），③ zstd 流式压缩到 out_path
        with tempfile.NamedTemporaryFile(
                suffix=".tar", delete=False) as tmp:
            tmp_tar = tmp.name
        with tarfile.open(tmp_tar, "w", format=tarfile.PAX_FORMAT) as tar:
            for rel, abs_path in files:
                info = tarfile.TarInfo(name=rel)
                info.size = abs_path.stat().st_size
                info.mtime = 0
                info.mode = 0o644
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                with open(abs_path, "rb") as f:
                    tar.addfile(info, f)
        offsets: dict[str, int] = {}
        with tarfile.open(tmp_tar, "r") as tar:
            for member in tar.getmembers():
                offsets[member.name] = member.offset_data
        missing_offsets = [rel for rel, _p in files if rel not in offsets]
        if missing_offsets:
            return error_envelope([f"tar 成员偏移缺失: {missing_offsets[:5]}"], **base)
        cctx = zstandard.ZstdCompressor(level=3, write_checksum=True,
                                        write_content_size=True)
        with open(tmp_tar, "rb") as src_io, open(out, "wb") as dst:
            cctx.copy_stream(src_io, dst)

        file_entries = []
        total = 0
        for rel, abs_path in files:
            size = abs_path.stat().st_size
            total += size
            file_entries.append({
                "path": rel,
                "offset": offsets[rel],
                "size": size,
                "sha256": _sha256_file(abs_path),
            })
        pack_sha = _sha256_file(out)
        manifest = {
            "format": PACK_FORMAT,
            "campaign": src.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "n_files": len(files),
            "total_bytes": total,
            "pack_file": out.name,
            "pack_sha256": pack_sha,
            "pack_size_bytes": out.stat().st_size,
            "files": file_entries,
        }
        manifest_path_obj.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return ok_envelope(
                   **{
                   "n_files": len(files),
                   "total_bytes": total,
                   "pack_sha256": pack_sha,
                   "pack_size_bytes": out.stat().st_size,
                   **base,
                   },
               )
    except Exception as exc:
        return error_envelope([f"打包失败: {exc}"], **base)
    finally:
        if tmp_tar is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_tar)


def _decompress_pack(pack_path: Path, tmp_tar: str) -> str | None:
    """zstd 流式解压到临时 tar；失败返回错误描述（None=成功）。

    收窄（AU-3①）：预期异常面 = (OSError, zstandard.ZstdError)——文件读
    写/缺失 OSError，包体损坏 ZstdError 家族；其余异常如实上抛给外层
    信封（verify/restore 的 ok=False 兜底）留痕，不再折叠成"包体损坏"。
    """
    zstandard = _import_zstandard()
    dctx = zstandard.ZstdDecompressor()
    try:
        with open(pack_path, "rb") as src, open(tmp_tar, "wb") as dst:
            dctx.copy_stream(src, dst)
    except (OSError, zstandard.ZstdError) as exc:
        return f"解压失败（包体损坏?）: {exc}"
    return None


def _load_manifest(manifest_path: Path) -> tuple[dict[str, Any] | None,
                                                 str | None]:
    """读偏移清单；格式不符/字段缺失返回错误描述。

    收窄（AU-3①）：预期异常面 = (OSError, ValueError)——清单缺失/不可读
    OSError，坏 JSON/坏编码 ValueError 子类；错误描述随返回值外显（信封
    errors），不再吞其余异常类型（上抛由调用面信封兜底）。
    """
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"清单读取/解析失败: {exc}"
    if not isinstance(manifest, dict) or manifest.get("format") != PACK_FORMAT:
        return None, f"清单格式不符（期望 {PACK_FORMAT}）"
    if not isinstance(manifest.get("files"), list):
        return None, "清单缺 files 段"
    return manifest, None


def verify_campaign(
    pack_path: str | Path,
    manifest_path: str | Path,
) -> dict[str, Any]:
    """归档校验：整包 sha256 快速校验 + 逐文件 sha256 重算（偏移定位）。

    逐文件口径：解压后在 tar 流内按清单 offset 定位、按 size 读取、
    sha256 与清单比对；offset/size 不符或哈希不匹配该文件 FAIL——
    **如实逐文件报告，不凑绿不放大**（#122/#314 同族：校验面只对独立
    证据下结论）。整包哈希不符只记 error 不中止（继续定位损坏面）；
    解压失败则无法逐文件定位，ok=False + error 如实返回。

    返回 {"ok", "pack_sha256_ok", "files": [{path, ok, reason?}],
    "n_ok", "n_fail", "errors"}。
    """
    pack = Path(pack_path)
    manifest_file = Path(manifest_path)
    base: dict[str, Any] = {"pack_path": str(pack),
                            "manifest_path": str(manifest_file)}
    if not pack.is_file():
        return error_envelope([f"归档不存在: {pack}"],
                              pack_sha256_ok=False, files=[],
                              n_ok=0, n_fail=0, **base)
    _import_zstandard()  # 缺装显式报缺（解压面）
    manifest, err = _load_manifest(manifest_file)
    if err is not None:
        return error_envelope([err], pack_sha256_ok=False, files=[],
                              n_ok=0, n_fail=0, **base)
    assert manifest is not None  # err is None ⇒ manifest 就绪
    entries: list[dict[str, Any]] = manifest["files"]

    errors: list[str] = []
    pack_sha = _sha256_file(pack)
    pack_sha_ok = pack_sha == manifest.get("pack_sha256")
    if not pack_sha_ok:
        errors.append(
            f"整包 sha256 不符（内容寻址锚失配）: 清单 "
            f"{manifest.get('pack_sha256')} vs 实测 {pack_sha}")

    results: list[dict[str, Any]] = []
    tmp_tar: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
                suffix=".tar", delete=False) as tmp:
            tmp_tar = tmp.name
        decompress_err = _decompress_pack(pack, tmp_tar)
        if decompress_err is not None:
            # 包体损坏到解不开：逐文件定位不可得，如实整体 FAIL
            return error_envelope([*errors, decompress_err],
                                  pack_sha256_ok=pack_sha_ok, files=[],
                                  n_ok=0, n_fail=0, **base)
        member_offsets: dict[str, tuple[int, int]] = {}
        with tarfile.open(tmp_tar, "r") as tar:
            for member in tar.getmembers():
                member_offsets[member.name] = (member.offset_data,
                                               member.size)
        manifest_paths = {entry.get("path") for entry in entries}
        extra = sorted(set(member_offsets) - manifest_paths)
        if extra:
            errors.append(f"tar 含清单外成员（包/清单失配）: {extra[:5]}")
        with open(tmp_tar, "rb") as tar_io:
            for entry in entries:
                rel = str(entry.get("path") or "")
                record: dict[str, Any] = {"path": rel}
                expected_off = entry.get("offset")
                expected_size = entry.get("size")
                expected_sha = entry.get("sha256")
                if rel not in member_offsets:
                    record.update(ok=False, reason="tar 内缺该成员")
                    results.append(record)
                    continue
                actual_off, actual_size = member_offsets[rel]
                if expected_off != actual_off or expected_size != actual_size:
                    record.update(
                        ok=False,
                        reason=f"offset/size 不符（清单 "
                               f"{expected_off}/{expected_size} vs tar "
                               f"{actual_off}/{actual_size}）")
                    results.append(record)
                    continue
                tar_io.seek(actual_off)
                data = tar_io.read(actual_size)
                actual_sha = hashlib.sha256(data).hexdigest()
                if actual_sha != expected_sha:
                    record.update(
                        ok=False,
                        reason=f"sha256 不符（清单 {expected_sha} vs "
                               f"实测 {actual_sha}）")
                    results.append(record)
                    continue
                record.update(ok=True)
                results.append(record)
        n_fail = sum(1 for r in results if not r["ok"])
        ok = pack_sha_ok and n_fail == 0 and not extra
        if ok:
            return ok_envelope(pack_sha256_ok=pack_sha_ok, files=results,
                               n_ok=len(results) - n_fail, n_fail=n_fail,
                               errors=errors, **base)
        return error_envelope(errors, pack_sha256_ok=pack_sha_ok,
                              files=results,
                              n_ok=len(results) - n_fail, n_fail=n_fail,
                              **base)
    except Exception as exc:
        return error_envelope([*errors, f"校验执行失败: {exc}"],
                              pack_sha256_ok=pack_sha_ok,
                              files=results, n_ok=0,
                              n_fail=sum(1 for r in results if not r["ok"]),
                              **base)
    finally:
        if tmp_tar is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_tar)


def restore_campaign(
    pack_path: str | Path,
    manifest_path: str | Path,
    target_dir: str | Path,
) -> dict[str, Any]:
    """恢复归档到**新目录**（目标已存在即拒——绝不覆盖，规格原文）。

    流程：整包 sha + 清单/tar 成员集一致性预检（任一不符则在触碰目标
    目录**之前**中止）→ 解包逐文件写入（按清单偏移定位）→ 恢复后逐文件
    哈希复核（重读落盘文件比对清单 sha256）。原归档零触碰；预检失败
    不创建目标目录，逐文件复核失败保留现场如实报 FAIL（不静默清理）。

    返回 {"ok", "target_dir", "n_files", "n_verified", "total_bytes"}；
    拒绝/失败 → ok=False + errors。
    """
    pack = Path(pack_path)
    manifest_file = Path(manifest_path)
    target = Path(target_dir)
    base: dict[str, Any] = {"pack_path": str(pack),
                            "manifest_path": str(manifest_file),
                            "target_dir": str(target)}
    if target.exists():
        return error_envelope([f"目标目录已存在，拒绝恢复（绝不覆盖）: {target}"], **base)
    if not pack.is_file():
        return error_envelope([f"归档不存在: {pack}"], **base)
    _import_zstandard()  # 缺装显式报缺（解压面）
    manifest, err = _load_manifest(manifest_file)
    if err is not None:
        return error_envelope([err], **base)
    assert manifest is not None
    entries: list[dict[str, Any]] = manifest["files"]
    if not entries:
        return error_envelope(["清单无文件（空归档）"], **base)
    # 相对路径守卫：穿越/绝对路径条目预检拒绝（写面前最后一道防线）
    for entry in entries:
        if _safe_rel_path(str(entry.get("path") or "")) is None:
            return error_envelope([f"清单含非法相对路径条目: {entry.get('path')!r}"], **base)

    errors: list[str] = []
    pack_sha = _sha256_file(pack)
    pack_sha_ok = pack_sha == manifest.get("pack_sha256")
    if not pack_sha_ok:
        errors.append(
            f"整包 sha256 不符: 清单 {manifest.get('pack_sha256')} vs "
            f"实测 {pack_sha}")

    tmp_tar: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
                suffix=".tar", delete=False) as tmp:
            tmp_tar = tmp.name
        decompress_err = _decompress_pack(pack, tmp_tar)
        if decompress_err is not None:
            return error_envelope([*errors, decompress_err], **base)
        member_offsets: dict[str, tuple[int, int]] = {}
        with tarfile.open(tmp_tar, "r") as tar:
            for member in tar.getmembers():
                member_offsets[member.name] = (member.offset_data,
                                               member.size)
        manifest_paths = {str(entry.get("path")) for entry in entries}
        extra = sorted(set(member_offsets) - manifest_paths)
        missing = sorted(manifest_paths - set(member_offsets))
        if extra:
            errors.append(f"tar 含清单外成员: {extra[:5]}")
        if missing:
            errors.append(f"tar 缺清单成员: {missing[:5]}")
        if errors:
            # 预检不符：不触碰目标目录（绝不半恢复覆盖历史面）
            return error_envelope(errors, **{**base})

        target.mkdir(parents=True)
        n_verified = 0
        total = 0
        with open(tmp_tar, "rb") as tar_io:
            for entry in entries:
                rel = str(entry["path"])
                dest = target / _safe_rel_path(rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                offset, size = member_offsets[rel]
                tar_io.seek(offset)
                data = tar_io.read(size)
                digest = hashlib.sha256(data).hexdigest()
                dest.write_bytes(data)
                total += len(data)
                # 恢复后逐文件哈希复核（重读落盘文件，非写前内存值）
                written_sha = _sha256_file(dest)
                if (digest != str(entry.get("sha256"))
                        or written_sha != str(entry.get("sha256"))):
                    errors.append(
                        f"{rel}: 恢复后哈希复核不符（落盘 "
                        f"{written_sha} vs 清单 {entry.get('sha256')}）")
                    continue
                n_verified += 1
        if errors:
            return error_envelope(errors, n_files=len(entries),
                                  n_verified=n_verified, total_bytes=total,
                                  **base)
        return ok_envelope(**{"n_files": len(entries), "n_verified": n_verified, "total_bytes": total, **base})
    except Exception as exc:
        return error_envelope([f"恢复失败: {exc}"], **base)
    finally:
        if tmp_tar is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_tar)


# ---------------------------------------------------------------------------
# study 元组抽取（DA-1：study→(template, target, budget)）
# ---------------------------------------------------------------------------

#: #320 字段面优先级：params > calib_params > design_params
_STUDY_TUPLE_SECTIONS: tuple[str, ...] = (
    "params", "calib_params", "design_params")


def _study_tuple_nested(meta: dict[str, Any],
                        keys: tuple[str, ...]) -> Any:
    """按 #320 优先级扫嵌套字段面，返回首个非 None 值（全缺 None）。"""
    for section in _STUDY_TUPLE_SECTIONS:
        body = meta.get(section)
        if not isinstance(body, dict):
            continue
        for key in keys:
            value = body.get(key)
            if value is not None:
                return value
    return None


def _as_budget_int(value: Any) -> int | None:
    """预算字段 int 收敛：拒 bool（#df7+⑯ float(True)=1.0 家族）、
    非整数如实 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def extract_study_tuple(meta: dict,
                        trials: list[dict] | None = None) -> dict[str, Any]:
    """从单个 run 的 meta（+可选 trials 行）抽取 study 元组。

    字段口径（真实样例实测：2026-09-26 全量 1784 个 runs/**/meta.json，
    字段存在性见括号计数）：
    - ``study``：``meta.study_name``（真实主源，1404/1781）→ 嵌套字段面
      （``params/calib_params/design_params`` 的 ``study_name/study``，
      #320 优先级）→ ``meta.study``；全缺 None 如实。
    - ``template``：嵌套字段面（同上优先级的 ``template/model``）→
      ``meta.template`` → ``meta.model``（真实主源，1779/1781）。
    - ``target``：优化目标规格**原样透传**（dict/str 皆可）——嵌套字段面
      的 ``objective/target`` → ``meta.objective`` → ``meta.target``；
      真实 meta 顶层无此字段（objectives 在 recipe.snapshot.yaml，不属
      meta 面）→ None 如实不臆测。
    - ``budget``：``trials`` 给出时=实测条数 ``len(trials)``（含 0，如
      #144"有 trials/无 meta"反面：trials 目录为空是真实测量）；否则
      meta 预算字段 ``n_trials/budget/max_trials``（顶层优先，嵌套面
      兜底，int 收敛拒 bool）；全缺 None 如实。

    meta 非 dict 时按空 meta 处理（输入收敛，#140 惯例）。返回键恒为
    {study, template, target, budget}。
    """
    body: dict[str, Any] = meta if isinstance(meta, dict) else {}

    def _first(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    study = _first(
        body.get("study_name"),
        _study_tuple_nested(body, ("study_name", "study")),
        body.get("study"),
    )
    template = _first(
        _study_tuple_nested(body, ("template", "model")),
        body.get("template"),
        body.get("model"),
    )
    target = _first(
        _study_tuple_nested(body, ("objective", "target")),
        body.get("objective"),
        body.get("target"),
    )
    if isinstance(trials, (list, tuple)):
        budget: int | None = len(trials)
    else:
        budget = None
        for key in ("n_trials", "budget", "max_trials"):
            budget = _as_budget_int(body.get(key))
            if budget is not None:
                break
        if budget is None:
            budget = _as_budget_int(_study_tuple_nested(
                body, ("n_trials", "budget", "max_trials")))
    return {
        "study": str(study) if study is not None else None,
        "template": str(template) if template is not None else None,
        "target": target,
        "budget": budget,
    }


def study_tuples_from_index(db_path: str | Path) -> list[dict[str, Any]]:
    """从已建湖索引库聚合全部 study 元组（DA-1 索引面出口）。

    聚合口径（去重语义显式声明，round4 #14 e11 复跑膨胀警示）：
    - **按 study 名去重**：索引 ``study`` 列非 NULL 的行才参与（NULL 行
      如实跳过，无 study 名无法构成元组）；同 study 多 run 聚合为一行。
    - ``templates``=该 study 全部 run 模板的**并集**（排序去重列表，
      通常单值）；``adapters`` 同口径并集。
    - ``template``=**最新** run 的模板（``created_ts`` 字符串字典序最大，
      并列取 path 排序末位）；``last_run_id``/``last_created_ts`` 同属
      该最新行。ISO 8601 同格式下字典序等价时间序，混格式如实以字典序
      为准；最新行 template 缺失时如实 None（``templates`` 并集不受影响）。
    - ``n_runs``=该 study 的索引行数（同种子重跑/复用 #158 的重复 run
      各自计一行不合并物理 run；元组层去重仅按 study 名）。
    - ``target``/``budget`` 恒 None：索引表无 objective/预算列——DA-2
      若需 run 级补全走 ``extract_study_tuple`` 读 meta/trials。

    库不存在 → FileNotFoundError（显式报缺，勿与"无 study"混淆）；表
    缺失/查询失败 → RuntimeError。返回按 study 名排序的 dict 列表。
    """
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(
            f"湖索引库不存在（先 build_runs_index）: {path}")
    duckdb = _import_duckdb()
    con = None
    try:
        con = duckdb.connect(str(path), read_only=True)
        configure_duckdb_connection(con)
        rows_raw = con.execute(
            f"SELECT path, run_id, template, adapter, study, created_ts "
            f"FROM {LAKE_INDEX_TABLE} WHERE study IS NOT NULL "
            f"ORDER BY path").fetchall()
    except Exception as exc:
        raise RuntimeError(f"湖索引查询失败（表缺失?）: {exc}") from exc
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()

    grouped: dict[str, dict[str, Any]] = {}
    for row_path, run_id, template, adapter, study, created_ts in rows_raw:
        entry = grouped.get(study)
        if entry is None:
            entry = grouped[study] = {
                "templates": set(), "adapters": set(), "n_runs": 0,
                "last_run_id": None, "last_created_ts": None,
                "last_path": None, "template": None,
            }
        entry["n_runs"] += 1
        if template is not None:
            entry["templates"].add(template)
        if adapter is not None:
            entry["adapters"].add(adapter)
        # 最新口径：created_ts 字典序最大，并列取 path 末位（行已按 path 序）
        key = (created_ts or "", row_path)
        if (entry["last_created_ts"] or "",
                entry["last_path"] or "") <= key:
            entry["last_created_ts"] = created_ts
            entry["last_path"] = row_path
            entry["last_run_id"] = run_id
            entry["template"] = template
    return [{
        "study": study,
        "template": grouped[study]["template"],
        "templates": sorted(grouped[study]["templates"]),
        "adapters": sorted(grouped[study]["adapters"]),
        "target": None,
        "budget": None,
        "n_runs": grouped[study]["n_runs"],
        "last_run_id": grouped[study]["last_run_id"],
        "last_created_ts": grouped[study]["last_created_ts"],
    } for study in sorted(grouped)]


def build_index_cli_entry(
    runs_dir: str | Path = "runs",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """build_runs_index 薄包装（DA-1 索引首建入口；CLI 接线归 r4-插⑧
    出口批，本件只到 service 面）。

    ``db_path=None`` 走缺省库路径 ``default_lake_index_db_path()``
    （``runs/.lake_index.duckdb``）。返回统计信封（build_runs_index 原
    键全量透传，另加）：
    - ``runs_scanned``=枚举的两层目录总数（独立计数扫描，与建表解耦；
      含元数据解析失败目录）；
    - ``rows``=实际入表行数（=build_runs_index 的 n_rows；两者之差=
      单目录行构建失败数，明细见 errors，截断前 20 条）；
    - ``duration_s``=包装层墙钟秒（含枚举计数+drop-create 全量建表）。
    """
    started = time.perf_counter()
    root = Path(runs_dir)
    runs_scanned = sum(1 for _ in _iter_run_dirs(root)) \
        if root.is_dir() else 0
    result = build_runs_index(runs_dir, db_path=db_path)
    out = dict(result)
    out["runs_scanned"] = runs_scanned
    n_rows = result.get("n_rows")
    out["rows"] = int(n_rows) if n_rows is not None else 0  # #364④ 显式判缺
    out["duration_s"] = round(time.perf_counter() - started, 3)
    return out
