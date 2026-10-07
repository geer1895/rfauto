"""集合卡尔曼滤波（EnKF）/多数据同化集合平滑器（ES-MDA）数据同化内核（S3 回灌件）。

carry-over 离线件（月计划 §二.2 / 池十五 S3）：EnKF 回灌——数据同化内核，
把观测（如测量 S 参数衍生的目标量）回灌进参数集合，用于校准/回灌场景。
纯 numpy 实现，确定性（seed 驱动），无任何外部同化库依赖。

方法口径（公式即出处，#118/#300：闭式锚自含、合成回收钉独立验证）：
- EnKF 分析步（扰动观测随机实现，Evensen 2003 "The Ensemble Kalman Filter:
  theoretical formulation and practical implementation", Ocean Dynamics）：
      P_f = 经验协方差（集合去均值外积平均）
      K   = P_f Hᵀ (H P_f Hᵀ + R)⁻¹          （Kalman 增益定义式）
      x_a = x_f + K (y + ε − H x_f),  ε ~ N(0, R)   （逐集合成员扰动观测）
- 膨胀（inflation）：分析前 P_f ← β·P_f（β≥1 缓和集合协方差欠估计；
  β=1 即经典 EnKF，本内核缺省）。
- ES-MDA（Emerick & Reynolds 2013, Computational Geosciences, "Ensemble
  smoother with multiple data assimilations"）：同一观测分 N_a 次 assimilate，
  第 i 次观测误差协方差取 R_i = α_i·R，调度的不变量是 Σ_i 1/α_i = 1；
  线性情形收敛到 ES 解。本内核用常数调度 α_i = N_a（满足不变量，原文
  推荐的最简调度族）。

验证范式（#340 合成已知量回收钉；两独立基准）：
1. 线性高斯闭式对拍——单步 EnKF 集合均值/协方差 → 解析卡尔曼滤波后验
   （``closed_form_kf_update``，K 与后验 P 均为定义式）逐位容差内一致；
2. 合成参数回收——已知真值造观测，回灌后集合均值收敛到真值；
3. ES-MDA 线性情形与单步 EnKF 等价性（同后验）。

数值口径：集合维度 N 与状态/观测维度均小（nx, ny ≤ 数十），矩阵运算
全 numpy；小矩阵批量运算不触 #258（OpenBLAS 多线程退化）敏感规模。
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
    "closed_form_kf_update",
    "enkf_analysis_step",
    "es_mda",
]


def _as_matrix_h(h: Any) -> np.ndarray:
    """观测算子收敛为 (ny, nx) 二维 float ndarray，并做形状守卫。"""
    h_mat = np.asarray(h, dtype=float)
    if h_mat.ndim == 0:
        h_mat = h_mat.reshape(1, 1)
    if h_mat.ndim == 1:
        h_mat = h_mat.reshape(1, -1)
    if h_mat.ndim != 2:
        raise ValueError(f"观测算子 H 必须可收敛为 (ny, nx) 二维，收到 shape {h_mat.shape}")
    return h_mat


def _as_obs(y: Any) -> np.ndarray:
    """观测向量收敛为 (ny,) 一维 float ndarray。"""
    y_vec = np.asarray(y, dtype=float).reshape(-1)
    if y_vec.size == 0:
        raise ValueError("观测向量 y 不能为空")
    return y_vec


def _empirical_cov(ensemble: np.ndarray) -> np.ndarray:
    """集合经验协方差 P = (X−x̄)(X−x̄)ᵀ/(N−1)（无偏口径）。"""
    anom = ensemble - ensemble.mean(axis=0, keepdims=True)
    return anom.T @ anom / (ensemble.shape[0] - 1)


def closed_form_kf_update(
    prior_mean: Any,
    prior_cov: Any,
    h: Any,
    r: Any,
    obs: Any,
) -> tuple[np.ndarray, np.ndarray]:
    """线性高斯解析卡尔曼后验（独立基准，非集合实现）。

    K = P Hᵀ (H P Hᵀ + R)⁻¹；x_a = x̄ + K(y − H x̄)；P_a = (I−KH)P。
    三个量均为定义式（标准卡尔曼滤波更新方程），作为 EnKF 的闭式对拍锚。
    """
    x = np.asarray(prior_mean, dtype=float).reshape(-1)
    p = np.asarray(prior_cov, dtype=float)
    if p.ndim == 0:
        p = np.eye(x.size) * float(p)
    if p.ndim != 2 or p.shape[0] != p.shape[1]:
        raise ValueError(f"先验协方差 P 必须二维方阵，收到 shape {p.shape}")
    h_mat = _as_matrix_h(h)
    y_vec = _as_obs(obs)
    r_mat = np.asarray(r, dtype=float)
    if r_mat.ndim == 0:
        # 标量口径=各观测同方差的对角阵（ny>1 时 reshape(1,1) 形状不互洽）
        r_mat = np.eye(y_vec.size) * float(r_mat)
    elif r_mat.ndim == 1:
        r_mat = np.diag(r_mat)
    if h_mat.shape != (y_vec.size, x.size):
        raise ValueError(
            f"形状不互洽：H {h_mat.shape} 与 ny={y_vec.size}/nx={x.size} 不符")
    innov = y_vec - h_mat @ x
    s = h_mat @ p @ h_mat.T + r_mat
    k = p @ h_mat.T @ np.linalg.inv(s)
    return x + k @ innov, (np.eye(x.size) - k @ h_mat) @ p


def enkf_analysis_step(
    ensemble: Any,
    obs: Any,
    h: Any,
    r: Any,
    *,
    rng: np.random.Generator | None = None,
    seed: int | None = None,
    inflation: float = 1.0,
) -> np.ndarray:
    """单步 EnKF 分析步（扰动观测随机实现），返回后验集合 (N, nx)。

    Args:
        ensemble: 先验集合 (N, nx)。
        obs: 观测向量 (ny,)。
        h: 观测算子（(ny, nx) 或 (nx,)→(1, nx)）。
        r: 观测误差协方差（标量/对角向量/(ny, ny) 方阵）。
        rng: 已构造的 numpy Generator（显式传入优先）。
        seed: 未传 rng 时的种子（同 seed 逐位可复现）。
        inflation: 先验协方差膨胀因子 β（分析前 P←β·P；1.0=经典）。

    Returns:
        后验集合 ndarray (N, nx)。

    Raises:
        ValueError: 形状不互洽 / 集合规模 < 2 / inflation 非正。
    """
    ens = np.asarray(ensemble, dtype=float)
    if ens.ndim != 2 or ens.shape[0] < 2:
        raise ValueError(f"集合必须是 (N>=2, nx) 二维，收到 shape {ens.shape}")
    h_mat = _as_matrix_h(h)
    y_vec = _as_obs(obs)
    if h_mat.shape[1] != ens.shape[1]:
        raise ValueError(
            f"H 列数 {h_mat.shape[1]} 与状态维 {ens.shape[1]} 不符")
    if h_mat.shape[0] != y_vec.size:
        raise ValueError(
            f"H 行数 {h_mat.shape[0]} 与观测维 {y_vec.size} 不符")
    r_mat = np.asarray(r, dtype=float)
    if r_mat.ndim == 0:
        # 标量口径=各观测同方差的对角阵（全 1 矩阵奇异且非协方差语义）
        r_mat = np.eye(y_vec.size) * float(r_mat)
    elif r_mat.ndim == 1:
        r_mat = np.diag(r_mat)
    if inflation <= 0:
        raise ValueError(f"inflation 必须为正，收到 {inflation!r}")
    generator = rng if rng is not None else np.random.default_rng(seed)

    p_f = _empirical_cov(ens) * float(inflation)
    s = h_mat @ p_f @ h_mat.T + r_mat
    k = p_f @ h_mat.T @ np.linalg.inv(s)

    # 扰动观测：逐成员 ε ~ N(0, R)；扰动集合自身去均值以避免有限集合
    # 引入的观测均值偏置（标准惯例）
    perturb = generator.multivariate_normal(
        np.zeros(y_vec.size), r_mat, size=ens.shape[0])
    perturb -= perturb.mean(axis=0, keepdims=True)
    innov = (y_vec + perturb) - ens @ h_mat.T  # (N, ny)
    return ens + innov @ k.T


def es_mda(
    ensemble: Any,
    obs: Any,
    h: Any,
    r: Any,
    *,
    n_assim: int = 4,
    rng: np.random.Generator | None = None,
    seed: int | None = None,
    inflation: float = 1.0,
) -> np.ndarray:
    """ES-MDA（Emerick & Reynolds 2013）：同一观测分 N_a 次同化，R_i=α_i·R。

    常数调度 α_i = N_a（满足 Σ 1/α_i = 1）。线性情形收敛到 ES/卡尔曼后验。
    n_assim=1 时退化为单步 EnKF。

    Args/Returns/异常语义同 :func:`enkf_analysis_step`；n_assim<1 抛 ValueError。
    """
    n_assim_i = int(n_assim)
    if n_assim_i < 1:
        raise ValueError(f"n_assim 必须 >= 1，收到 {n_assim!r}")
    generator = rng if rng is not None else np.random.default_rng(seed)
    current = np.asarray(ensemble, dtype=float).copy()
    r_arr = np.asarray(r, dtype=float)
    # ES-MDA 调度核心：第 i 步观测误差协方差取 R_i = α_i·R，常数调度
    # α_i = N_a（Σ 1/α_i = N_a·(1/N_a) = 1，Emerick & Reynolds 2013）。
    # 膨胀后单步等效于"弱化观测"——多次弱同化累积逼近一次强同化。
    r_step = r_arr * n_assim_i
    for _ in range(n_assim_i):
        current = enkf_analysis_step(
            current, obs, h, r_step,
            rng=generator, inflation=inflation,
        )
    return current
