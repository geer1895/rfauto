"""OP-6（round16 §六）：全局-局部自动切换——代理梯度上的 trust-constr 精修。

规格原文："全局停→scipy trust-constr 在代理梯度上精修→真跑验证"。
三段式职责（每段独立可测）：

- :func:`surrogate_scalar_fn`：把代理 predict（metrics dict）收成标量
  目标闭包（多指标代理必须显式给 metric 键——不静默取首个，#122）；
- :func:`local_refine_surrogate`：scipy ``trust-constr`` 在代理面上从
  全局相位候选点精修（梯度=scipy 有限差分，确定性；bounds 走
  ``scipy.optimize.Bounds`` 硬盒）；
- :func:`global_local_switch`：全局相位候选（参数 dict 列表）→ 代理面
  top-k 精修 → **真目标验证**——只有真目标不劣于全局最优的精修点才
  被采纳（surrogate 提议、true 裁决，#122 精神：代理不承担最终结论）。

确定性：trust-constr + 中心差分梯度零随机；同输入同输出（C4）。
裁判（tests/unit/test_global_local.py）：#207 合成函数（多峰 2D）——
全局相位=种子化随机采样，判据=采纳后真目标 ≤ 全局相位真最优（单调
护栏）且合成问题上严格改善；真机验证段（openEMS/HFSS）超 unit 门。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np


def surrogate_scalar_fn(
    predict_fn: Callable[[Mapping[str, float]], Mapping[str, float]],
    names: Sequence[str],
    metric: str,
) -> Callable[[np.ndarray], float]:
    """代理 predict → x 向量标量目标闭包（列序=names）。

    predict 返回 dict 缺 metric 键或值非有限时抛 RuntimeError（不静默
    NaN——trust-constr 会被 NaN 静默带偏）。
    """
    names = list(names)
    if not metric:
        raise ValueError("metric 必须显式给出（多指标代理不静默取首个）")

    def _f(x: np.ndarray) -> float:
        params = {n: float(v) for n, v in zip(names, x, strict=True)}
        out = predict_fn(params)
        if metric not in out:
            raise RuntimeError(
                f"代理 predict 缺指标键 {metric!r}（有: {sorted(out)}）")
        val = float(out[metric])
        if not math.isfinite(val):
            raise RuntimeError(f"代理 predict 返回非有限值: {metric}={val!r}")
        return val

    return _f


def local_refine_surrogate(
    predict_fn: Callable[[Mapping[str, float]], Mapping[str, float]],
    x0: Mapping[str, float],
    bounds: Mapping[str, tuple[float, float]],
    *,
    metric: str,
    maxiter: int = 200,
    gtol: float = 1e-8,
) -> dict[str, Any]:
    """trust-constr 在代理面上从 x0 精修（确定性，零 IO）。

    Returns:
        {"x": {参数名: 值}, "fun": 代理值, "success", "message", "niter"}

    Raises:
        ValueError: x0/bounds 键集不一致或边界非法。
    """
    from scipy.optimize import Bounds, minimize

    names = sorted(bounds)
    if set(x0) != set(names):
        raise ValueError(
            f"x0 键集 {sorted(x0)} 与 bounds 键集 {names} 不一致")
    lo = np.array([float(bounds[n][0]) for n in names])
    hi = np.array([float(bounds[n][1]) for n in names])
    if np.any(hi <= lo):
        raise ValueError("bounds 须逐维 hi > lo")
    f = surrogate_scalar_fn(predict_fn, names, metric)
    x_start = np.clip(
        np.array([float(x0[n]) for n in names]), lo, hi)
    res = minimize(
        f, x_start, method="trust-constr",
        bounds=Bounds(lo, hi),
        options={"maxiter": int(maxiter), "gtol": float(gtol),
                 "xtol": 1e-12},
    )
    x_ref = np.clip(np.asarray(res.x, dtype=float), lo, hi)
    return {
        "x": {n: float(v) for n, v in zip(names, x_ref, strict=True)},
        "fun": float(f(x_ref)),
        "success": bool(res.success),
        "message": str(res.message),
        "niter": int(getattr(res, "niter", 0)),
    }


def global_local_switch(
    *,
    global_points: list[dict[str, float]],
    predict_fn: Callable[[Mapping[str, float]], Mapping[str, float]],
    true_objective: Callable[[Mapping[str, float]], float],
    bounds: Mapping[str, tuple[float, float]],
    metric: str,
    top_k: int = 3,
    maxiter: int = 200,
) -> dict[str, Any]:
    """全局-局部切换主环：代理精修 top-k → 真目标验证 → 单调护栏采纳。

    Args:
        global_points: 全局相位已评估点（参数 dict 列表，≥1）。
        predict_fn: 代理 predict（同 local_refine_surrogate）。
        true_objective: 真目标（最小化标量；合成裁判/真机适配器注入）。
        bounds / metric / maxiter: 同 local_refine_surrogate。
        top_k: 按代理值精修的全局点数（1..len(global_points) 截断）。

    Returns:
        {"global_best_params", "global_best_true", "refined": [
        {proxy_fun, true_value, params, adopted}...], "best_params",
        "best_true", "improved", "n_refined"}
        adopted=True 仅当该精修点真目标 ≤ 全局相位真最优（单调护栏）；
        best_* 取采纳点中真目标最优（无采纳点时退回全局相位最优，
        improved=False——不虚构改善）。
    """
    if not global_points:
        raise ValueError("global_points 不得为空（全局相位至少 1 个已评估点）")
    true_vals = [float(true_objective(p)) for p in global_points]
    g_best_idx = int(np.argmin(true_vals))
    g_best_params = dict(global_points[g_best_idx])
    g_best_true = true_vals[g_best_idx]

    # 按代理值排 top-k（代理面排序只决定精修顺序，不决定采纳）
    proxy_vals = [float(predict_fn(p)[metric]) for p in global_points]
    order = sorted(range(len(global_points)), key=lambda i: (proxy_vals[i], i))
    k = max(1, min(int(top_k), len(order)))

    refined: list[dict[str, Any]] = []
    adopted_best: dict[str, float] | None = None
    adopted_true = math.inf
    for i in order[:k]:
        ref = local_refine_surrogate(
            predict_fn, global_points[i], bounds, metric=metric,
            maxiter=maxiter)
        true_v = float(true_objective(ref["x"]))
        adopted = true_v <= g_best_true
        refined.append({
            "seed_params": dict(global_points[i]),
            "proxy_fun": float(ref["fun"]),
            "true_value": true_v,
            "params": ref["x"],
            "adopted": adopted,
        })
        if adopted and true_v < adopted_true:
            adopted_best, adopted_true = ref["x"], true_v

    if adopted_best is not None:
        return {
            "global_best_params": g_best_params,
            "global_best_true": g_best_true,
            "refined": refined,
            "best_params": adopted_best,
            "best_true": adopted_true,
            "improved": adopted_true < g_best_true,
            "n_refined": len(refined),
        }
    return {
        "global_best_params": g_best_params,
        "global_best_true": g_best_true,
        "refined": refined,
        "best_params": g_best_params,
        "best_true": g_best_true,
        "improved": False,
        "n_refined": len(refined),
    }
