"""list_datasets/query_dataset/discover_workdir_runs/import_workdir_runs（数据工厂查询与工作目录导入）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 19. 数据集查询（E11 数据面注册表） ───────────────────────────────────────

@mcp.tool
def list_datasets(
    visibility: str | None = None,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """数据集清单查询（datasets 域）：过滤词 → 注册表总览（点数/GT/可见性）。

    无副作用，可安全调用；清单由盘面 manifest 自动汇总非手工名单，不用于
    行级查询（走 query_dataset）。目录缺失 → 空清单如实；读失败 →
    ok=False。只读无时序约束。

    Args:
        visibility: 按 "public"/"private" 过滤；缺省不过滤
        out_dir: 数据集根目录（默认 runs/datasets）

    Returns:
        dict: {ok, datasets: [{name, n_points, visibility, ...}], n_datasets}
    """
    from rfauto.service.dataset_insights import list_datasets as _list
    return _list(out_dir=out_dir, visibility=visibility)


@mcp.tool
def query_dataset(
    name: str,
    where: str | None = None,
    columns: list[str] | None = None,
    limit: int = 100,
    model: str | None = None,
    study_name: str | None = None,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """数据集 DuckDB 直查（datasets 域）：SQL WHERE/列裁剪 → 行集（只读）。

    无副作用，可安全调用；where 是单条 SQL WHERE 片段（如 "cost < 0.1"）
    经白名单校验，model/study_name 等值过滤走参数绑定（值不拼进 SQL），
    不用于 DDL/DML。数据集不存在/where 非白名单 → ok=False 如实。
    只读无时序约束。

    Args:
        name: 数据集名（datasets materialize 产物）
        where: SQL WHERE 片段；缺省不过滤
        columns: 列裁剪名单；缺省取全部列
        limit: 返回行数上限（>=1，默认 100）
        model: 按模板族等值过滤（model 列）；缺省不过滤
        study_name: 按来源 study 名等值过滤；缺省不过滤
        out_dir: 数据集根目录（默认 runs/datasets）

    Returns:
        dict: {ok, rows, n_rows, columns, dataset, where, filters, limit}
    """
    from rfauto.service.dataset_service import query_dataset as _query
    return _query(
        name, where=where, columns=columns, limit=limit,
        model=model, study_name=study_name, out_dir=out_dir,
    )


@mcp.tool
def discover_workdir_runs(
    runs_root: str = "runs",
    models: list[str] | None = None,
) -> dict[str, Any]:
    """工作目录产物发现（datasets 域）：runs 扫描 → 可导入候选清单（只读）。

    无副作用，可安全调用；slotline/hairpin/marchand/mline/helix 等战役把
    sparams.csv / *.sNp 直接落在 runs/<工作目录>/<点目录>/，不在
    materialize 契约里；本工具列出可导入候选（逐目录曲线数/引擎/端口数），
    入库走 import_workdir_runs。runs_root 不存在 → ok=False errors 如实。
    只读无时序约束。

    Args:
        runs_root: runs 根目录（默认 runs）
        models: 器件族过滤名单（slotline/hairpin/marchand/mline/helix）；缺省全部

    Returns:
        dict: {ok, n_candidates, per_family, candidates: [{run_id, family,
            n_curves, adapters, curves}]} 或 {ok: False, errors}
    """
    from rfauto.service.dataset_service import discover_workdir_candidates as _disc
    return _disc(runs_root, models=models)


@mcp.tool
def import_workdir_runs(
    name: str,
    run_ids: list[str] | None = None,
    runs_root: str = "runs",
    out_dir: str = "runs/datasets",
    models: list[str] | None = None,
    health_gate: bool = True,
    fmt: str = "parquet",
) -> dict[str, Any]:
    """工作目录产物导入（datasets 域）：候选目录 → 数据集注册表行集。

    有副作用：写数据集目录 <out_dir>/<name>/（不改 runs/ 下任何产物）；
    只导入 discover_workdir_runs 列出的候选，不猜无主目录。每个曲线产物
    一行，设计参数只从内核落盘 JSON 按固定键路径取值；provenance 带来源
    目录/时间戳/touchstone 路径/n_ports；G11 目录级健康门默认开（不过门
    点如实记 unhealthy 不静默丢）。runs 目录不存在/候选解析失败 →
    ok=False errors 如实。时序：先 discover 后导入。

    Args:
        name: 数据集名（目录名，字母数字-_）
        run_ids: 工作目录名清单；缺省=所选族全部候选
        runs_root: runs 根目录（默认 runs）
        out_dir: 数据集输出根目录（默认 runs/datasets）
        models: 器件族过滤名单；缺省五族全导
        health_gate: 是否启用 G11 目录级健康门（默认 True）
        fmt: 物化格式 parquet/hdf5（默认 parquet）

    Returns:
        dict: {ok, name, dataset_dir, n_candidates, n_curves, n_points, n_rows,
            n_dup, n_points_skipped, unhealthy_points, source_runs, ...}
    """
    from rfauto.service.dataset_service import import_workdir_runs as _import
    return _import(
        run_ids, name=name, runs_root=runs_root, out_dir=out_dir,
        models=models, health_gate=health_gate, fmt=fmt,
    )
