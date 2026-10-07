"""主动子空间（Active Subspace）自实现（ME-16）——纯 numpy、零 IO、零新依赖。

方法（Constantine 2015, *Active Subspaces*）：对标量目标 f，构造梯度
协方差 ``C = Σ_i w_i ∇f(x_i) ∇f(x_i)ᵀ / Σ_i w_i``，特征分解 ``C = W Λ Wᵀ``
后，前 k 个特征向量张成的子空间即"主动子空间"——f 沿该子空间的变化
远大于补空间（partition ratio = 头部能量 / 尾部能量 判据）。

自实现动机（计划 ME-16）：原作者 constantine 库停维于 py2.7，不引入；
~百行 numpy 覆盖本仓需求（模板降维主方向发现，衔接 R9 敏感度排序）。

诚实边界：
- 输入梯度不可得时用中心差分（截断 O(h²) + 舍入 O(ε/h)，h 缺省 1e-6），
  f 契约：接受一维参数向量、返回标量；
- 样本数 n < 维度 p 时协方差秩亏（rank ≤ n < p），显式拒绝（守卫）；
- C 半正定，eigh 数值负尾截断为 0；
- partition ratio 的尾部能量低于头部×1e-14（eigh 精度量级）时报 inf
  （补空间无变化能量），不伪造有限比值。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

#: 特征值与解析协方差对拍及方向恢复的数值容差基准（eigh 精度量级）
_TAIL_FLOOR_RATIO = 1e-14


def _finite_difference_jacobian(
    f: Callable[[np.ndarray], float],
    X: np.ndarray,
    h: float,
) -> np.ndarray:
    """中心差分逐点梯度：(f(x+h e_j) − f(x−h e_j)) / (2h)，返回 (n, d)。"""
    n, d = X.shape
    G = np.empty((n, d), dtype=float)
    for i in range(n):
        x = np.asarray(X[i], dtype=float)
        for j in range(d):
            xp = x.copy()
            xm = x.copy()
            xp[j] += h
            xm[j] -= h
            G[i, j] = (float(f(xp)) - float(f(xm))) / (2.0 * h)
    return G


def _validate_matrix(X: np.ndarray, name: str) -> np.ndarray:
    """输入矩阵校验：二维浮点、样本数 ≥2。"""
    arr = np.asarray(X, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"{name} 须为二维 (n_samples, n_dims)，收到 shape={arr.shape}")
    n, d = arr.shape
    if n < 2:
        raise ValueError(f"{name} 至少需要 2 个样本，收到 n={n}")
    if d < 1:
        raise ValueError(f"{name} 至少需要 1 个维度，收到 p={d}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含非有限值（NaN/Inf）")
    return arr


def active_subspace(
    X: np.ndarray,
    grads: np.ndarray | None = None,
    n_active: int | None = None,
    *,
    f: Callable[[np.ndarray], float] | None = None,
    diff_h: float = 1e-6,
    weights: np.ndarray | None = None,
) -> dict[str, Any]:
    """主动子空间主方向发现（ME-16）。

    Args:
        X: 采样点矩阵 (n, d)——n 个样本、d 维参数。守卫：n < p 显式拒绝
            （协方差秩亏，估计无意义）。
        grads: 逐点梯度矩阵 (n, d)（∂f/∂x 按行）。给定即用解析/外部梯度；
            为 None 时进入无梯差分模式，必须提供 ``f``（中心差分）。
        n_active: 主动方向数 k；None=1。须满足 1 ≤ k ≤ d。
        f: 无梯差分模式的目标函数（x(1D)→float）；grads 给定时忽略。
        diff_h: 中心差分布长（缺省 1e-6）。
        weights: 逐样本权重 (n,)（加权协方差 C = Σ w_i ∇f_i ∇f_iᵀ / Σ w_i）；
            None=均匀权重 1/n（Constantine 缺省口径）。

    Returns:
        dict（值为 numpy 数组，调用方自行拷贝/转换）：
        - eigenvalues (d,)：降序、负尾截断为 0；
        - eigenvectors (d, d)：列向量与 eigenvalues 对齐，符号规范化
          （最大分量恒为正，保证确定性输出）；
        - active_dirs (d, k)：前 k 个主方向（W1）；
        - partition_ratio：头部能量 Σλ_{1..k} / 尾部能量 Σλ_{k+1..d}；
          尾部 ≤ 头部×1e-14 时为 inf（补空间无变化能量）；
        - method："analytic_grads" | "central_difference"；
        - grads (n, d)：实际使用的梯度样本（差分模式下为差分结果）。
    """
    X = _validate_matrix(X, "X")
    n, d = X.shape
    if n < d:
        raise ValueError(
            f"主动子空间要求样本数 n ≥ 维度 p（当前 n={n}, p={d}）——"
            "n<p 时协方差秩亏（rank ≤ n），主方向估计无意义（守卫拒绝）")

    if grads is not None:
        G = _validate_matrix(grads, "grads")
        if G.shape != (n, d):
            raise ValueError(f"grads shape {G.shape} 与 X {X.shape} 不一致")
        method = "analytic_grads"
    else:
        if not callable(f):
            raise ValueError("grads 未提供时必须给 f（无梯中心差分模式）")
        if diff_h <= 0.0:
            raise ValueError(f"diff_h 必须 > 0，收到 {diff_h}")
        G = _finite_difference_jacobian(f, X, float(diff_h))
        method = "central_difference"

    k = 1 if n_active is None else int(n_active)
    if k < 1 or k > d:
        raise ValueError(f"n_active 须在 [1, {d}] 内，收到 {k}")

    w = np.ones(n, dtype=float) if weights is None else np.asarray(weights, dtype=float)
    if w.shape != (n,):
        raise ValueError(f"weights shape {w.shape} 与样本数 {n} 不一致")
    if np.any(w < 0) or not np.all(np.isfinite(w)):
        raise ValueError("weights 须为非负有限值")
    w_sum = float(w.sum())
    if w_sum <= 0.0:
        raise ValueError("weights 总和须 > 0")

    # 加权梯度协方差 C = Σ w_i ∇f_i ∇f_iᵀ / Σ w_i（Constantine 口径，未中心化）
    C = (G * w[:, None]).T @ G / w_sum
    C = (C + C.T) / 2.0  # 数值对称化
    eigvals, eigvecs = np.linalg.eigh(C)
    order = np.argsort(eigvals)[::-1]
    eigvals = np.clip(eigvals[order], 0.0, None)
    eigvecs = eigvecs[:, order]
    # 符号规范化：每列最大分量恒为正（确定性输出，方向 ±a 等价）
    for j in range(eigvecs.shape[1]):
        imax = int(np.argmax(np.abs(eigvecs[:, j])))
        if eigvecs[imax, j] < 0:
            eigvecs[:, j] = -eigvecs[:, j]

    head = float(eigvals[:k].sum())
    tail = float(eigvals[k:].sum())
    zero_tail = tail <= 0.0 or tail <= head * _TAIL_FLOOR_RATIO
    partition_ratio = float("inf") if zero_tail else head / tail

    return {
        "eigenvalues": eigvals,
        "eigenvectors": eigvecs,
        "active_dirs": eigvecs[:, :k],
        "partition_ratio": partition_ratio,
        "n_active": k,
        "method": method,
        "grads": G,
    }


def reduce_dimension(
    X: np.ndarray,
    y: np.ndarray,
    grads: np.ndarray | None = None,
    *,
    f: Callable[[np.ndarray], float] | None = None,
    n_active: int = 1,
    diff_h: float = 1e-6,
    weights: np.ndarray | None = None,
) -> dict[str, Any]:
    """降维：主方向投影 + 主动坐标线性重建误差估计（ME-16）。

    在 :func:`active_subspace` 结果之上，把 X 投影到前 k 个主方向得主动
    坐标 Z = X·W1，用最小二乘线性模型 ``y ≈ β0 + Z·β`` 重建 y，报告
    重建误差——y 在主动子空间上近似线性时误差趋 0（一阶主动子空间
    近似有效），否则偏大（线性主动子空间不足以表示该目标）。

    Returns:
        :func:`active_subspace` 全部键，另加：
        - W1 (d, k)：投影矩阵（= active_dirs）；
        - X_active (n, k)：主动坐标；
        - coef (k+1,)：线性模型系数 [截距, β...]；intercept：截距；
        - y_pred (n,)：重建值；
        - rel_error：‖y−ŷ‖₂ / ‖y−ȳ‖₂（y 全同值——零方差——时退报
          绝对 RMS）；
        - r2：1 − SS_res/SS_tot（y 全同值时 None）。
    """
    X = _validate_matrix(X, "X")
    n = X.shape[0]
    yv = np.asarray(y, dtype=float).ravel()
    if yv.shape != (n,):
        raise ValueError(f"y 长度 {yv.shape[0]} 与样本数 {n} 不一致")
    if not np.all(np.isfinite(yv)):
        raise ValueError("y 含非有限值（NaN/Inf）")

    result = active_subspace(
        X, grads, n_active, f=f, diff_h=diff_h, weights=weights)
    W1 = result["active_dirs"]
    Z = X @ W1
    design = np.hstack([np.ones((n, 1)), Z])
    coef, *_ = np.linalg.lstsq(design, yv, rcond=None)
    y_pred = design @ coef
    resid = yv - y_pred
    ss_res = float(np.sum(resid ** 2))
    # 零方差判定：y 全同值（ptp=0）时方差严格为零——退报绝对 RMS、
    # r2=None，不伪造除以零的比值。（不用 ss_tot 的 eps 地板判：均值本身
    # 含求和舍入误差，常数 y 的 ss_tot 会落在舍入量级而非精确 0，
    # 任何固定地板都不可靠；ptp 是精确判别。）
    if float(np.ptp(yv)) > 0.0:
        ss_tot = float(np.sum((yv - float(np.mean(yv))) ** 2))
        rel_error = float(np.sqrt(ss_res) / np.sqrt(ss_tot))
        r2: float | None = 1.0 - ss_res / ss_tot
    else:
        rel_error = float(np.sqrt(ss_res / n))
        r2 = None
    result.update({
        "W1": W1,
        "X_active": Z,
        "coef": coef,
        "intercept": float(coef[0]),
        "y_pred": y_pred,
        "rel_error": rel_error,
        "r2": r2,
    })
    return result
