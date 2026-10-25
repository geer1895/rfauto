"""lake_service.study —— study 元组抽取与索引首建 CLI 入口（DA-1）。

自 lake_service.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体自原节「study 元组抽取」逐字节搬迁。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Any

from .index import (
    LAKE_INDEX_TABLE,
    _import_duckdb,
    _iter_run_dirs,
    build_runs_index,
    configure_duckdb_connection,
)

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
