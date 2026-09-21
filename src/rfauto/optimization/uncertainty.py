"""GP 后验 σ 的确定性内核（B5 不确定度终止判据的数据面）。

与 ``rfauto.service.active_learning`` 的 ``_gp_posterior_predictions``
（gp 不确定度来源）**同源口径**：单位空间 RBF 核 k(a,b)=exp(-‖a-b‖²/(2ℓ²))、
z 标准化、nugget 稳定求逆、后验方差 var(x*)=k(x*,x*)-k*ᵀ(K+σ²I)⁻¹k*。

分层说明（为什么是移植不是引用）：import-linter 分层契约规定
``rfauto.optimization`` 位于 ``rfauto.service`` 下层，禁止上层模块反向
import（optimization → service 属违例）；而 surrogate_loop（B5 判据宿主）
在本层，故按零回归纪律把闭式后验移植到此（active_learning.py 一字不改，
两处实现由同一套公式与单测锚定，口径漂移由 test_uncertainty 的同源断言
拦截）。

纯函数、纯 numpy、固定超参（无优化迭代）→ 确定且快（确定性内核纪律：
数值只出确定性内核）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ["gp_cost_sigma"]


def _bounds_arrays(
    bounds: dict[str, tuple[float, float]] | dict[str, list[float]],
) -> tuple[list[str], list[float], list[float]]:
    """(names, lower, span)——span 保底 1e-12，防零宽域除零。

    同 active_learning._bounds_arrays 口径（本层禁 import service，本地同式）。
    """
    names = sorted(bounds)
    lower = [float(bounds[n][0]) for n in names]
    span = [max(float(bounds[n][1]) - float(bounds[n][0]), 1e-12)
            for n in names]
    return names, lower, span


def _normalize_points(
    points: list[dict[str, float]],
    names: list[str],
    lower: list[float],
    span: list[float],
) -> np.ndarray:
    """点集 → 归一化矩阵（缺失键回落到下界，同 _normalize 口径）。

    非数值参数显式抛 ValueError（非法输入报错，不静默当 0）。
    """
    if not points:
        return np.zeros((0, len(names)), dtype=float)
    rows = []
    for pt in points:
        if not isinstance(pt, dict):
            raise ValueError(f"点必须是参数字典: {pt!r}")
        row = []
        for i, n in enumerate(names):
            try:
                row.append((float(pt.get(n, lower[i])) - lower[i]) / span[i])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"参数 {n} 非数值: {pt.get(n)!r}") from exc
        rows.append(row)
    return np.array(rows, dtype=float)


def gp_cost_sigma(
    samples_costs: list[dict[str, Any]],
    bounds: dict[str, tuple[float, float]],
    points: list[dict[str, float]],
    *,
    length_scale: float = 0.3,
    noise: float = 1e-6,
) -> np.ndarray:
    """已评样本 cost 上拟合的 RBF-GP 后验 σ 在逐个 points 处的取值。

    输入 ``samples_costs``：[{"params": {...}, "cost": float}]（环内已评
    样本的 (params, cost) 视图）；``points``：待评分点（如 LHS 探针池）。
    输出：shape=(len(points),) 的 σ_cost（原 cost 量纲）。

    数值口径（与 active_learning._gp_posterior_predictions 同源）：
    - 参数按 bounds 归一化到单位空间；y 做 z 标准化后建 GP，σ 乘回 sd
      换算回原量纲；
    - 有限 cost 样本 <2 时全部记 σ=0（不硬拟、不编造不确定度）；
    - nugget=noise 稳定求逆（奇异退 pinv）；方差 clip 到 ≥0。
    """
    names, lower, span = _bounds_arrays(bounds)
    X = _normalize_points([s.get("params") or {} for s in samples_costs],
                          names, lower, span)
    P = _normalize_points(points, names, lower, span)
    sigmas = np.zeros(len(points), dtype=float)
    y = np.array([float(s.get("cost", np.nan)) for s in samples_costs],
                 dtype=float)
    mask = np.isfinite(y)
    if int(mask.sum()) < 2:
        return sigmas
    xm, ym = X[mask], y[mask]
    sd = float(ym.std()) + 1e-12
    l2 = max(float(length_scale), 1e-9) ** 2
    d2 = ((xm[:, None, :] - xm[None, :, :]) ** 2).sum(-1)
    k_mat = np.exp(-d2 / (2.0 * l2)) + max(float(noise), 0.0) * np.eye(len(xm))
    try:
        k_inv = np.linalg.inv(k_mat)
    except np.linalg.LinAlgError:
        k_inv = np.linalg.pinv(k_mat)
    d2p = ((P[:, None, :] - xm[None, :, :]) ** 2).sum(-1)
    k_star = np.exp(-d2p / (2.0 * l2))  # (P, n)
    var = 1.0 - np.einsum("pn,nm,pm->p", k_star, k_inv, k_star)
    sigmas = np.sqrt(np.clip(var, 0.0, None)) * sd
    return sigmas
