"""lake_service.lineage —— 跨 run 血缘查询/校验/md 渲染（XD-1）。

自 lake_service.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体自原节「跨 run lineage」逐字节搬迁。
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from rfauto.infra.run_store import RUN_LINEAGE_TABLE
from rfauto.service.envelope import error_envelope, ok_envelope

from .index import (
    LAKE_INDEX_TABLE,
    _import_duckdb,
    configure_duckdb_connection,
    default_lake_index_db_path,
)

logger = logging.getLogger(__name__)


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
