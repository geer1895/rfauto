"""PR-6 战役监控仪表盘：成本热图 + trial 表（虚拟列表数据面，JSON 进出）。

规格=研究扩充 round16 §四 PR-6："SSE+成本热图+
trial 虚拟列表（1000 行 60fps）"。本模块承担**数据面**（前端只渲染，
 坑族口径）：

- **成本热图**：trials 审计 → (x_param, y_param) 确定性等宽分箱
  （feasibility_heatmap 同款分箱算法，E10 姊妹面）——格内 {n, cost_mean,
  cost_min, best_trial}；x/y 显式参数或按"全 trial 均为有限数值的参数键"
  字典序自动取前两（自动选取在载荷里如实标注 ``params_source:
  "auto"|"explicit"``）；
- **trial 表**：逐 trial {trial_number, cost, params} 全量列表（前端虚拟
  滚动渲染）；超 :data:`MAX_TABLE_ROWS` 截断并如实标 ``table_truncated``
  （虚拟列表面向千行级，万行截断护栏防载荷失控）；
- **SSE**：既有 ``/api/runs/{run_id}/events/stream``（P-1）不重做，前端
  仪表盘监听该流刷新本端点数据（server.py 路由注释指路）。

数字出处：cost/params 全部来自 trials 审计文件（优化器落盘），本模块
只做分箱聚合，零物理数字产生。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.service._helpers import load_run_trials as _load_trials
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "MAX_TABLE_ROWS",
    "campaign_dashboard",
]

#: trial 表行数护栏（虚拟列表数据面截断点；截断如实标注不静默）。
MAX_TABLE_ROWS = 10000


def _trial_no_key(value: Any, *, missing: float) -> float:
    """trial_number 归一为可排序 float。

    缺号/非数值/非有限（#320 导入面使外来 trial json 真实可达，任何形态
    都不可再炸 TypeError——S2-1/W4c：裸元组比较 None vs int）按 ``missing``
    落位：best 选取传 +inf（缺号排序末位），表排序传 0.0（与旧 ``or 0``
    口径逐位一致，非崩溃输入零行为变化）。
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool) \
            and math.isfinite(float(value)):
        return float(value)
    return missing


def _numeric_params(trials: list[dict[str, Any]]) -> list[str]:
    """全 trial 均给出有限数值（非 bool）的参数键（字典序）。"""
    if not trials:
        return []
    keys: set[str] = set(trials[0].get("params") or {})
    for t in trials:
        keys &= set(t.get("params") or {})
    out = []
    for k in sorted(keys):
        if all(
            isinstance((t.get("params") or {}).get(k), (int, float))
            and not isinstance((t.get("params") or {}).get(k), bool)
            and math.isfinite(float(t["params"][k]))
            for t in trials
        ):
            out.append(k)
    return out


def _cell(v: float, lo: float, hi: float, grid_n: int) -> int:
    """确定性分箱（等宽格右端点归末格；feasibility_heatmap 同款）。"""
    idx = int((v - lo) / (hi - lo) * grid_n)
    return min(max(idx, 0), grid_n - 1)


def campaign_dashboard(
    run_id: str,
    x_param: str | None = None,
    y_param: str | None = None,
    grid_n: int = 12,
) -> dict[str, Any]:
    """战役仪表盘数据面：成本热图 + trial 表（JSON 信封）。"""
    # F-7/S3：runs 根走 infra.runs_paths 双根收敛（chdir 仓内子目录时收敛
    # 回仓库 runs/，#295 族；cwd 无 runs 且不在仓内=tmp 面行为不变）。
    from rfauto.infra.runs_paths import resolve_runs_dir

    runs_dir = resolve_runs_dir("runs")
    run_dir = runs_dir / str(run_id)
    if not run_dir.is_dir():
        return error_envelope([f"run 不存在: {run_id}"])
    trials = _load_trials(run_dir)
    if not trials:
        return error_envelope(
            [f"run {run_id} 无 trials 审计文件——战役仪表盘面向调参/优化 run，"
             "单点仿真 run 请走 Run 详情页"])

    used_rows = []
    for t in trials:
        params = t.get("params")
        cost = t.get("cost")
        if not isinstance(params, dict) or not isinstance(cost, (int, float)) \
                or isinstance(cost, bool) or not math.isfinite(float(cost)):
            continue
        used_rows.append({"trial_number": t.get("trial_number"),
                          "cost": float(cost),
                          "params": {str(k): v for k, v in params.items()}})
    if not used_rows:
        return error_envelope(
            [f"run {run_id} 的 {len(trials)} 条 trial 审计均无有限 cost——"
             "热图与表不可算（如实缺省）"])

    numeric = _numeric_params(used_rows)
    if x_param is None or y_param is None:
        if len(numeric) < 2:
            return error_envelope(
                [f"数值参数不足 2 个（现 {numeric}）——热图需 x/y 两参数；"
                 "显式传 x_param/y_param 也必须落在数值参数集内"])
        auto_x, auto_y = numeric[0], numeric[1]
        x_name = x_param if x_param is not None else auto_x
        y_name = y_param if y_param is not None else auto_y
        params_source = "explicit" if (x_param is not None or y_param is not None) else "auto"
    else:
        x_name, y_name = str(x_param), str(y_param)
        params_source = "explicit"
    if x_name == y_name:
        return error_envelope(["x_param 与 y_param 不能相同"])
    for name in (x_name, y_name):
        if name not in numeric:
            return error_envelope(
                [f"参数 {name!r} 不在数值参数集内（可用: {numeric}）——"
                 "非数值/缺失参数不可分箱"])

    grid_n = max(2, min(int(grid_n), 64))
    xs = [float(r["params"][x_name]) for r in used_rows]
    ys = [float(r["params"][y_name]) for r in used_rows]
    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(ys), max(ys)
    if x_hi <= x_lo or y_hi <= y_lo:
        return error_envelope(
            [f"{x_name}/{y_name} 在已评样本中无展宽（单点或退化）——热图不可分箱"])
    cells: dict[tuple[int, int], dict[str, Any]] = {}
    for r in used_rows:
        ci = (_cell(float(r["params"][x_name]), x_lo, x_hi, grid_n),
              _cell(float(r["params"][y_name]), y_lo, y_hi, grid_n))
        c = cells.setdefault(ci, {"n": 0, "cost_sum": 0.0, "cost_min": math.inf,
                                  "best_trial": None})
        c["n"] += 1
        c["cost_sum"] += r["cost"]
        if r["cost"] < c["cost_min"]:
            c["cost_min"] = r["cost"]
            c["best_trial"] = r["trial_number"]
    out_cells = [
        {"i": i, "j": j, "n": c["n"],
         "cost_mean": round(c["cost_sum"] / c["n"], 6),
         "cost_min": round(c["cost_min"], 6),
         "best_trial": c["best_trial"]}
        for (i, j), c in sorted(cells.items())
    ]

    # S2-1/W4c 回归钉口径：显式元组键，缺 trial_number 按 +inf 排末位，
    # 等 cost + 缺号不再炸 TypeError（min 的裸元组比较已消除）
    best = min(used_rows,
               key=lambda r: (r["cost"], _trial_no_key(r["trial_number"],
                                                       missing=math.inf)))
    rows_out = sorted(used_rows,
                      key=lambda r: _trial_no_key(r["trial_number"],
                                                  missing=0.0))
    truncated = len(rows_out) > MAX_TABLE_ROWS
    return ok_envelope(
        run_id=str(run_id),
        n_trials_total=len(trials),
        n_trials_used=len(used_rows),
        params_numeric=numeric,
        x_param=x_name,
        y_param=y_name,
        params_source=params_source,
        grid_n=grid_n,
        x_edges=[round(x_lo + (x_hi - x_lo) * k / grid_n, 9) for k in range(grid_n + 1)],
        y_edges=[round(y_lo + (y_hi - y_lo) * k / grid_n, 9) for k in range(grid_n + 1)],
        cells=out_cells,
        best={"trial_number": best["trial_number"], "cost": round(best["cost"], 6),
              "params": best["params"]},
        cost_mean=round(sum(r["cost"] for r in used_rows) / len(used_rows), 6),
        trials=rows_out[:MAX_TABLE_ROWS],
        table_truncated=truncated,
        table_rows=len(rows_out[:MAX_TABLE_ROWS]),
    )
