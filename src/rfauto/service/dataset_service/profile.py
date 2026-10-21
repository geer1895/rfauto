"""dataset_service.profile —— 数据集一键画像（audit 席快速画像面，W8-S4）。

对已物化数据集做确定性描述统计（零估计量，铁律 7——所有数字来自点表
原文的计数/极值/均值/总体标准差）：行/列规模、逐模型/逐 adapter 计数、
参数逐键范围、数值指标逐键分布与 >σσ 异常值（缺省 3σ，z 用总体标准差
ddof=0；std=0 或样本 <2 时 z 不定义→异常值如实 0）、门通过率
（manifest health_verdicts 逐 run 健康门判定 + ground truth 行占比）。

数据源：``_read_points_table``（parquet 直读 / hdf5 经 h5py，与查询面
同单源）；门通过率唯一事实源=manifest（物化时落盘的逐 run 判定，本
模块不重跑健康门——画像面只读，不触发求解）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

from .common import DEFAULT_OUT_DIR, _validate_dataset_name
from .io import _load_manifest_yaml, _read_points_table

#: 画像列（列裁剪读点表，避免整表进内存——metrics/params 是 JSON 串列）
_PROFILE_COLUMNS = ("run_id", "model", "adapter", "params_json",
                    "metrics_json", "cost")

#: 异常值判定带（任务书口径 >3σ；总体 std 的 z 分数）
_OUTLIER_SIGMA = 3.0

#: 异常值样例上限（逐条 run_id+值+z；按 |z| 降序截断，计数如实不截）
_MAX_OUTLIER_EXAMPLES = 20


def _mean(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def _pstd(values: list[float], mean: float) -> float:
    """总体标准差（ddof=0）：单样本/全同值列得 0.0（z 不定义的诚实基底）。"""
    return math.sqrt(math.fsum((v - mean) ** 2 for v in values) / len(values))


def _numeric_stats(values: list[float]) -> dict[str, Any]:
    """一列数值的分布摘要（均值/总体 std/极值；计数在外层）。"""
    mean = _mean(values)
    return {"n": len(values), "mean": mean, "std": _pstd(values, mean),
            "min": min(values), "max": max(values)}


def _outliers(values: list[float], keys: list[str], *,
              sigma: float = _OUTLIER_SIGMA) -> \
        tuple[int, list[dict[str, Any]]]:
    """>σσ 异常值：返回 (计数, 样例列表)。

    z=|x−mean|/std（总体 std）；std==0（全同值）或样本 <2 时 z 不定义
    →计数 0 不臆测。样例按 |z| 降序、键名升序消并列，截断
    _MAX_OUTLIER_EXAMPLES 条（计数不截）。
    """
    n = len(values)
    if n < 2:
        return 0, []
    mean = _mean(values)
    std = _pstd(values, mean)
    if std <= 0.0:
        return 0, []
    hits: list[tuple[float, str, float]] = []
    for key, v in zip(keys, values, strict=True):
        z = abs(v - mean) / std
        if z > sigma:
            hits.append((z, key, v))
    hits.sort(key=lambda t: (-t[0], t[1]))
    examples = [
        {"run_id": key, "value": v, "z": z,
         "direction": "high" if v > mean else "low"}
        for z, key, v in hits[:_MAX_OUTLIER_EXAMPLES]]
    return len(hits), examples


def _parse_json_objects(raw_rows: list[dict[str, Any]], column: str) -> \
        list[dict[str, Any]]:
    """JSON 串列逐行解析（坏 JSON/非对象行如实跳过并计数由调用方负责）。"""
    out: list[dict[str, Any]] = []
    for row in raw_rows:
        raw = row.get(column)
        if not raw:
            out.append({})
            continue
        try:
            d = json.loads(raw)
        except (TypeError, ValueError):
            d = None
        out.append(d if isinstance(d, dict) else {})
    return out


def _ranges(objs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """参数逐键范围：数值键 min/max/计数；非数值键只计 distinct 值数。"""
    numeric: dict[str, list[float]] = {}
    distinct: dict[str, set[str]] = {}
    for obj in objs:
        for key, val in obj.items():
            if isinstance(val, bool):
                distinct.setdefault(key, set()).add(str(val))
            elif isinstance(val, (int, float)):
                numeric.setdefault(key, []).append(float(val))
            elif val is not None:
                distinct.setdefault(key, set()).add(str(val))
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(set(numeric) | set(distinct), key=str):
        if key in numeric:
            vals = numeric[key]
            out[key] = {"kind": "numeric", "n": len(vals),
                        "min": min(vals), "max": max(vals)}
        else:
            out[key] = {"kind": "categorical",
                        "n_distinct": len(distinct[key])}
    return out


def _metric_columns(objs: list[dict[str, Any]], keys: list[str]) -> \
        dict[str, dict[str, Any]]:
    """指标逐键分布 + >σ 异常值（keys=逐行 run_id，供异常值样例归属）。"""
    columns: dict[str, list[tuple[str, float]]] = {}
    for run_id, obj in zip(keys, objs, strict=True):
        for key, val in obj.items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                columns.setdefault(str(key), []).append(
                    (run_id, float(val)))
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(columns, key=str):
        pairs = columns[key]
        vals = [v for _k, v in pairs]
        stats = _numeric_stats(vals)
        n_out, examples = _outliers(vals, [k for k, _v in pairs])
        stats["n_outliers"] = n_out
        if n_out:
            stats["outliers"] = examples
        out[key] = stats
    return out


def _gates_from_manifest(manifest: dict[str, Any] | None,
                         n_rows: int) -> dict[str, Any]:
    """门通过率（manifest 单源）：health_verdicts 逐 run 判定 tally +
    healthy 占比；ground truth 行占比（ground_truth.n_gt_rows/n_rows）。"""
    hv = (manifest or {}).get("health_verdicts")
    tally: dict[str, int] = {}
    if isinstance(hv, dict):
        for _rid, verdict in hv.items():
            key = str(verdict or "unknown")
            tally[key] = tally.get(key, 0) + 1
    judged = sum(tally.values())
    healthy = tally.get("healthy", 0)
    gt = (manifest or {}).get("ground_truth")
    n_gt = gt.get("n_gt_rows") if isinstance(gt, dict) else None
    return {
        "health_verdicts": dict(sorted(tally.items())),
        "n_runs_judged": judged,
        "healthy_rate": (healthy / judged) if judged else None,
        "n_unhealthy_skipped": (manifest or {}).get("n_unhealthy_skipped"),
        "health_gate": (manifest or {}).get("health_gate"),
        "n_gt_rows": n_gt,
        "gt_row_rate": (n_gt / n_rows)
        if isinstance(n_gt, int) and n_rows else None,
    }


def dataset_profile(
    dataset_name: str,
    *,
    out_dir: str | Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    """数据集一键画像（audit 席消费者）：规模/计数/范围/异常值/门通过率。

    全部为确定性描述统计：参数逐键范围（params_json 展开）、数值指标
    逐键分布与 >3σ 异常值（总体 std 的 z 分数；std=0 如实 0 异常）、
    cost 列同口径、门通过率读 manifest（health_verdicts healthy 占比 +
    GT 行占比）。坏 JSON 行计入 n_bad_json_rows 不静默丢；数据集不存在
    /点表缺失 → ok=False 如实报错。

    Returns:
        ok 信封：``dataset``/``format``/``n_rows``/``columns``/
        ``n_runs``/``models``/``adapters``/``param_ranges``/
        ``metric_stats``（含 n_outliers/outliers）/``cost_stats``/
        ``gates``/``n_bad_json_rows``。
    """
    try:
        name = _validate_dataset_name(dataset_name)
    except (ValueError, TypeError) as exc:
        return error_envelope([str(exc)])
    dataset_dir = Path(out_dir) / name
    manifest = _load_manifest_yaml(dataset_dir)
    fmt = "parquet"
    if manifest is None and not dataset_dir.is_dir():
        return error_envelope([f"数据集不存在: {name}（缺 manifest，先 materialize）"])
    try:
        table = _read_points_table(dataset_dir, manifest, list(_PROFILE_COLUMNS))
    except FileNotFoundError:
        return error_envelope(
            [f"数据集不存在: {name}（缺点级数据文件，先 materialize）"])
    except RuntimeError as exc:
        return error_envelope([str(exc)])
    except Exception:
        return error_envelope(
            ["点级数据读取失败（文件损坏或列缺失；原始错误不透出）"])
    if manifest is not None:
        from .io import _dataset_format

        fmt = _dataset_format(manifest)

    rows = table.to_pylist()
    n_rows = len(rows)
    params_objs = _parse_json_objects(rows, "params_json")
    metrics_objs = _parse_json_objects(rows, "metrics_json")
    n_bad = sum(
        1 for row, pobj, mobj in zip(rows, params_objs, metrics_objs,
                                     strict=True)
        if (bool(row.get("params_json")) and not pobj)
        or (bool(row.get("metrics_json")) and not mobj))

    run_ids = [str(row.get("run_id") or "") for row in rows]
    cost_pairs = [(str(row.get("run_id") or ""), float(row["cost"]))
                  for row in rows
                  if isinstance(row.get("cost"), (int, float))
                  and not isinstance(row.get("cost"), bool)]
    cost_vals = [v for _k, v in cost_pairs]
    cost_stats = _numeric_stats(cost_vals) if cost_vals else {"n": 0}
    if cost_vals:
        n_cost_out, cost_examples = _outliers(
            cost_vals, [k for k, _v in cost_pairs])
        cost_stats["n_outliers"] = n_cost_out
        if n_cost_out:
            cost_stats["outliers"] = cost_examples

    models: dict[str, int] = {}
    adapters: dict[str, int] = {}
    for row in rows:
        m = str(row.get("model") or "")
        models[m] = models.get(m, 0) + 1
        a = str(row.get("adapter") or "")
        adapters[a] = adapters.get(a, 0) + 1

    # 列数口径=数据集 schema 全列（manifest["columns"] 单源；画像读面是
    # 列裁剪的 6 列，不把读取宽度冒充数据集宽度）
    manifest_cols = manifest.get("columns") if manifest else None
    columns = ([str(c) for c in manifest_cols]
               if isinstance(manifest_cols, list) and manifest_cols
               else list(table.column_names))

    return ok_envelope(
        dataset=name,
        format=fmt,
        dataset_dir=str(dataset_dir),
        n_rows=n_rows,
        columns=columns,
        n_columns=len(columns),
        n_runs=len({r for r in run_ids if r}),
        models=dict(sorted(models.items())),
        adapters=dict(sorted(adapters.items())),
        param_ranges=_ranges(params_objs),
        metric_stats=_metric_columns(metrics_objs, run_ids),
        cost_stats=cost_stats,
        gates=_gates_from_manifest(manifest, n_rows),
        n_bad_json_rows=n_bad,
    )
