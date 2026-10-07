"""F-ME 器件族批 1：压缩感知 / ℓ1 重加权（IRWL1）稀疏阵布阵内核。

纯确定性优化内核（零全波、零求解器、零 IO、零新依赖，纯 numpy——
最小二乘回代用 np.linalg.lstsq），round3 方案
研究扩充 round3 §二 F-F 表件 8
（"合成方向图 vs 密度锥削参考 + PSLL/栅瓣门"）。

口径与法源（铁律 5：法源写 docstring；裁判=独立路径，#118）
================================================================

- **ℓ1 重加权最小化（IRWL1）**：E. J. Candès, M. B. Wakin, S. P. Boyd,
  "Enhancing Sparsity by Reweighted l1 Minimization", Journal of Fourier
  Analysis and Applications, vol. 14, pp. 877-905, 2008。外层迭代：
  第 k 步解加权 LASSO（权重 ω⁽ᵏ⁾ₙ = 1/(|w⁽ᵏ⁻¹⁾ₙ| + ε)），收敛判据
  ‖w⁽ᵏ⁾−w⁽ᵏ⁻¹⁾‖/‖w⁽ᵏ⁾‖ < tol 或触 max_iter。原文献用 log-sum 罚的
  一阶近似导出该权重更新；本实现按文献同款倒数权重钉死。
- **问题口径（BPDN）**：min_w 0.5·‖A·w − b‖² + λ_reg·Σ_n |w_n|
  （基追踪去噪 basis pursuit denoising，S. S. Chen, D. L. Donoho,
  M. A. Saunders, SIAM Review 43(1), 2001）。目标 b 先按 max|b| 归一
  （λ_reg 与权重绝对尺度解耦；尺度信息由调用方按需回乘）。
- **求解器（ISTA）**：A. Beck, M. Teboulle, "A Fast Iterative
  Shrinkage-Thresholding Algorithm for Linear Inverse Problems", SIAM J.
  Imaging Sciences 2(1), 2009——梯度步 step=1/L（L=σ_max(A)²，np.linalg.norm(A,2)
  谱范数实测）+ 软阈值 prox。FISTA 加速不取（动量项破坏目标函数单调性，
  单调 ISTA 的目标非增恒等式是本内核单测裁判之一）。
- **稀疏阵 CS 综合的应用口径**：ℓ1 谱阵论文族（H. Yao, W. Wang 等的
  reweighted-ℓ1 thinned array 综合路线；L. Poli, G. Oliveri, A. Massa 的
  CS 阵列稀疏综合族）——共同框架即上述 BPDN+IRWL1 在阵列流形上的实例，
  本模块不引入其中任何经验调参，只实现通用内核。
- **前向算子**：A[m,n] = exp(j·2π·p_n·(u_m − u0))，p_n 候选位置（波长
  单位）、u_m 方向余弦、u0 扫描方向余弦——与
  rfauto.core.array_synthesis.array_factor(normalize=False) 的
  ψ_n = 2π·d·(u−u0)·n 口径逐位同构（等间距 p_n = n·d 时的恒等式由单测
  钉死）；θ(度)→u 映射直接复用 array_synthesis.direction_cosine（只读
  复用，不重复实现）；PSLL 复用 array_synthesis.peak_sidelobe_level_db。

复数权重的 ℓ1 处理（钉死决定）
==============================
选**复软阈值**（单列字典），不选拆实虚双列。理由：

1. 物理语义：单元的开/关由 |w_n| = 0 判定——复软阈值是 |w_n| 的群稀疏
   prox（实虚同生同灭）；拆双列则 Re/Im 独立稀疏，会出现"某单元只剩
   虚部"的非物理中间态，且变量数翻倍后 ℓ1 的各向异性偏差不一致。
2. prox 封闭式干净：S_t(z) = z·max(0, 1 − t/|z|)（幅值收缩、相位保持，
   = 复数域 |·| 的近端算子），z=0 时返回 0（无 nan 路径）。
3. Candès 2008 的重加权只依赖 |w_n|，复软阈值口径下 ω⁽ᵏ⁾ₙ = 1/(|w⁽ᵏ⁾ₙ|+ε)
   与文献公式逐项对应，不需双列改写。

诚实边界（预声明，#122）
========================
- **实值目标 = 包络拟合**：b 为实数组（典型 |AF| 曲线）时，核按复最小
  二乘拟合该非负实包络——最优场在采样点上逼近实包络。当理想方向图
  存在副瓣符号翻转（真实场 = ±包络）时，包络的最优复场解**不等于**
  原场权重（严格幅度拟合是相位检索问题，非凸，超出 BPDN 口径）——
  因此"合成回收"主判据用复目标场 b = A·w_true（方向图亦可为复场），
  包络路径只做 PSLL/对照面的工程综合，不做权重回收承诺。
- **栅格相干条件**：候选位置间距 < λ/2 时字典列相干性上升（μ→1），
  支撑集可辨识性退化——mutual_coherence 随结果返回供调用方对照
  预声明条件（间距 ≥ λ/2；均匀 u 网格上 Δp = λ/2 整数倍的列近正交）。
- IRWL1 不保证全局最优（ℓ1 松弛+重加权均为启发式链条）；PSLL 相对
  密度锥削参考只预声明"+2 dB 带"（irwl1_psll ≤ taper_psll + 2 dB），
  不保证更优，实测值如实返回。
- 不含互耦、单元方向图（方向图积由调用方组合）、量化/失配/位置误差；
  权重与位置均为连续理想值。

接口：全部函数纯 numpy 进出、零 IO；数值 0.0 合法（判缺失一律
is not None）；入参 bool 显式拒收（df7+⑯）；随机性仅密度锥削抽稀
（np.random.default_rng 固定 seed，缺省 20260927）；dataclass 结果带
to_dict（复数 → [re, im]，非有限 float → None）；不进 calculators
注册表（器件族域内约定，同 aging/tma_array，消费者是 service 层）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from rfauto.core.array_synthesis import direction_cosine, peak_sidelobe_level_db

__all__ = [
    "DEFAULT_TAPER_SEED",
    "PSLL_BAND_DB",
    "DensityTaperComparison",
    "SparseArrayDesign",
    "density_taper_indices",
    "forward_matrix",
    "irwl1_reweight",
    "mutual_coherence",
    "soft_threshold",
    "synthesize_sparse_array",
    "u_values_from_theta",
    "weighted_lasso_ista",
]

#: 密度锥削抽稀的缺省随机种子（固定值保证对照面可复现）
DEFAULT_TAPER_SEED = 20260927
#: 预声明对照带（dB）：irwl1_psll ≤ taper_psll + PSLL_BAND_DB（不保证更优，如实实测）
PSLL_BAND_DB = 2.0

_TINY = 1e-300
"""非零守卫下限（仅防 0 除；物理零值走显式分支，不用 or 惯语，#364④）。"""


# ─── 输入校验 ──────────────────────────────────────────────────────────────────


def _reject_bool(value: Any, name: str) -> None:
    """bool 显式拒收（float(True)=1.0 静默污染统计，df7+⑯）。"""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 不接受 bool")


def _finite_float(value: Any, name: str) -> float:
    _reject_bool(value, name)
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


def _positive_int(value: Any, name: str) -> int:
    _reject_bool(value, name)
    if isinstance(value, float) and not float(value).is_integer():
        raise ValueError(f"{name} 必须为整数，收到 {value!r}")
    out = int(value)
    if out < 1:
        raise ValueError(f"{name} 必须 >= 1，收到 {value!r}")
    return out


def _nonneg_int(value: Any, name: str) -> int:
    """非负整数（允许 0；seed 类入参）。"""
    _reject_bool(value, name)
    if isinstance(value, float) and not float(value).is_integer():
        raise ValueError(f"{name} 必须为整数，收到 {value!r}")
    out = int(value)
    if out < 0:
        raise ValueError(f"{name} 必须 >= 0，收到 {value!r}")
    return out


def _validate_positions(positions_lambda) -> np.ndarray:
    """候选位置栅格（波长单位）校验：1-D、有限、≥2 个、无重复（保输入序）。"""
    _reject_bool(np.asarray(positions_lambda), "positions_lambda")
    p = np.asarray(positions_lambda, dtype=float)
    if p.ndim != 1:
        raise ValueError(f"positions_lambda 必须是一维数组，收到 shape={p.shape}")
    if p.size < 2:
        raise ValueError(f"positions_lambda 至少需要 2 个候选位置，收到 {p.size}")
    if not np.all(np.isfinite(p)):
        raise ValueError("positions_lambda 含非有限值（nan/inf）")
    if p.size != np.unique(np.round(p, 12)).size:
        raise ValueError("positions_lambda 含重复候选位置（1e-12 λ 容差内）")
    return p


def _validate_u(u_values) -> np.ndarray:
    """方向余弦网格校验：1-D、有限、≥3 点、落在 [-1, 1]（1e-9 松量）。"""
    u = np.asarray(u_values, dtype=float)
    if u.ndim != 1:
        raise ValueError(f"u_values 必须是一维数组，收到 shape={u.shape}")
    if u.size < 3:
        raise ValueError("u_values 至少需要 3 个采样点（PSLL 定位副瓣要求）")
    if not np.all(np.isfinite(u)):
        raise ValueError("u_values 含非有限值（nan/inf）")
    if np.any(np.abs(u) > 1.0 + 1e-9):
        raise ValueError("方向余弦网格必须落在 [-1, 1]（可见区）")
    return np.clip(u, -1.0, 1.0)


def _validate_target(target, n_u: int) -> np.ndarray:
    """目标方向图校验：长度=网格点数、有限、非全零（空目标显式报错）。

    实数输入按包络口径原样转复数（见模块 docstring 诚实边界）。
    """
    raw = np.asarray(target)
    if raw.dtype == np.bool_:
        raise ValueError("target 不接受 bool")
    b = raw.astype(complex)
    if b.ndim != 1:
        raise ValueError(f"target 必须是一维数组，收到 shape={b.shape}")
    if b.size == 0:
        raise ValueError("target 为空（空目标无方向图可拟合）")
    if b.size != n_u:
        raise ValueError(f"target 长度（{b.size}）必须与网格点数（{n_u}）一致")
    if not np.all(np.isfinite(b.view(float))):
        raise ValueError("target 含非有限值（nan/inf）")
    if float(np.max(np.abs(b))) <= 0.0:
        raise ValueError("target 全零（空目标无方向图可拟合）")
    return b


# ─── 基本算子 ──────────────────────────────────────────────────────────────────


def soft_threshold(z, threshold):
    """复软阈值算子 S_t(z) = z·max(0, 1 − t/|z|)（幅值收缩、相位保持）。

    - |z| ≤ t → 0（含 z=0：无 nan 路径，显式分支）；
    - |z| > t → (|z| − t)·z/|z|；
    - t = 0 → z 逐位恒等（含 z=0）；
    - 实数输入退化为经典软阈值 x − t·sign(x)（|x| > t）/ 0（|x| ≤ t）。

    threshold 可为标量或与 z 可广播的逐元数组（ISTA 的 per-element 阈值
    step·λ_reg·ω_n）。这是复数域 |·| 罚项的近端算子（Beck-Teboulle 2009
    ISTA 的 prox 步），本内核唯一钉死的复 ℓ1 处理（见模块 docstring
    「复数权重的 ℓ1 处理」）。
    """
    zz = np.asarray(z)
    if zz.dtype == np.bool_:
        raise ValueError("z 不接受 bool")
    zc = zz.astype(complex)
    tt = np.asarray(threshold)
    if tt.dtype == np.bool_:
        raise ValueError("threshold 不接受 bool")
    tv = tt.astype(float)
    if not np.all(np.isfinite(tv)):
        raise ValueError("threshold 含非有限值")
    if np.any(tv < 0.0):
        raise ValueError(f"threshold 必须 >= 0，收到 {threshold!r}")
    if tv.ndim == 0:
        t = float(tv)
        if t == 0.0:
            return zc.copy()
        mag = np.abs(zc)
        out = np.zeros_like(zc)
        live = mag > t
        # live 元素：z/|z| 保持相位，幅值减 t；mag>t>0 保证分母非零
        out[live] = zc[live] * (1.0 - t / mag[live])
        return out
    tv_b = np.broadcast_to(tv, zc.shape)
    mag = np.abs(zc)
    out = np.zeros_like(zc)
    live = mag > tv_b
    factor = np.zeros_like(mag)
    factor[live] = 1.0 - tv_b[live] / mag[live]
    return zc * factor


def forward_matrix(
    positions_lambda,
    u_values,
    *,
    scan_direction_cosine: float = 0.0,
) -> np.ndarray:
    """前向算子 A[m, n] = exp(j·2π·p_n·(u_m − u0))（n_u × N_grid 复矩阵）。

    positions_lambda：候选位置（波长单位，1-D）；u_values：方向余弦网格
    （1-D）；scan_direction_cosine：扫描方向余弦 u0（缺省 0 = 侧射）。
    等间距 p_n = n·d 时与 array_synthesis.array_factor(normalize=False)
    逐位同构（单测钉）。
    """
    p = _validate_positions(positions_lambda)
    u = _validate_u(u_values)
    u0 = _finite_float(scan_direction_cosine, "scan_direction_cosine")
    if abs(u0) > 1.0 + 1e-9:
        raise ValueError(f"scan_direction_cosine 必须落在 [-1, 1]，收到 {u0!r}")
    phase = 2.0 * np.pi * np.outer(u - u0, p)
    return np.exp(1j * phase)


def u_values_from_theta(theta_deg, *, axis: str = "z", phi_deg: float = 0.0) -> np.ndarray:
    """θ(度) 网格 → 方向余弦 u 网格（复用 array_synthesis.direction_cosine）。"""
    _reject_bool(np.asarray(theta_deg), "theta_deg")
    u = np.atleast_1d(np.asarray(direction_cosine(theta_deg, phi_deg, axis), dtype=float))
    if u.size < 3:
        raise ValueError("theta_deg 至少需要 3 个采样点（PSLL 定位副瓣要求）")
    if not np.all(np.isfinite(u)):
        raise ValueError("theta_deg 映射出的方向余弦含非有限值")
    if np.any(np.abs(u) > 1.0 + 1e-9):
        raise ValueError("theta_deg 映射出的方向余弦超出 [-1, 1]（可见区外）")
    return np.clip(u, -1.0, 1.0)


def mutual_coherence(A: np.ndarray) -> float:
    """字典归一化相干度 μ = max_{i≠j}|g_ij|/sqrt(g_ii·g_jj)（Gram = Aᴴ A）。

    栅格相干条件的可观测面：候选间距 ≥ λ/2（均匀 u 网格）时 μ 接近 0；
    间距过密时 μ→1（支撑集不可辨识，见模块 docstring 诚实边界）。
    """
    a = np.asarray(A)
    if a.ndim != 2 or a.shape[1] < 2:
        raise ValueError("A 必须是列数 >= 2 的二维矩阵")
    gram = a.conj().T @ a
    diag = np.diag(gram).real
    off = np.abs(gram - np.diag(diag))
    idx = np.triu_indices(a.shape[1], k=1)
    pairs = off[idx]
    denom = np.sqrt(diag[idx[0]] * diag[idx[1]])
    safe = np.where(denom > _TINY, denom, np.inf)
    return float(np.max(pairs / safe))


# ─── 求解器 ────────────────────────────────────────────────────────────────────


def weighted_lasso_ista(
    A: np.ndarray,
    b: np.ndarray,
    penalty_weights,
    lambda_reg: float,
    *,
    max_iter: int = 500,
    tol: float = 1e-10,
) -> dict:
    """加权 LASSO 的 ISTA 求解：min_w 0.5·‖Aw − b‖² + λ_reg·Σ ω_n|w_n|。

    penalty_weights：逐元素正权重 ω（IRWL1 外层每轮更新）；梯度步长
    step = 1/L，L = σ_max(A)²（谱范数实测）——ISTA 目标函数单调非增
    （Beck-Teboulle 2009），单测钉。返回 dict：
    weights（复 1-D）、objective_history（list[float]）、
    n_iter、converged（相对变化 < tol）。
    """
    a = np.asarray(A, dtype=complex)
    bb = np.asarray(b, dtype=complex)
    if a.ndim != 2:
        raise ValueError("A 必须是二维矩阵")
    if bb.ndim != 1 or bb.size != a.shape[0]:
        raise ValueError("b 必须是与 A 行数一致的一维数组")
    w_pen = np.asarray(penalty_weights, dtype=float)
    if w_pen.ndim != 1 or w_pen.size != a.shape[1]:
        raise ValueError("penalty_weights 必须是与 A 列数一致的一维数组")
    if np.any(w_pen < 0.0) or not np.all(np.isfinite(w_pen)):
        raise ValueError("penalty_weights 必须全为非负有限值")
    lam = _finite_float(lambda_reg, "lambda_reg")
    if lam < 0.0:
        raise ValueError(f"lambda_reg 必须 >= 0，收到 {lambda_reg!r}")
    max_it = _positive_int(max_iter, "max_iter")
    inner_tol = _finite_float(tol, "tol")
    if inner_tol <= 0.0:
        raise ValueError(f"tol 必须 > 0，收到 {tol!r}")

    gram = a.conj().T @ a
    a_tb = a.conj().T @ bb
    lip = float(np.linalg.norm(a, 2)) ** 2  # L = σ_max²（∇(0.5‖·‖²) 的 Lipschitz 常数）
    if lip <= _TINY:
        lip = 1.0
    step = 1.0 / lip
    threshold = step * lam * w_pen

    w = np.zeros(a.shape[1], dtype=complex)
    history = [0.5 * float(np.vdot(bb, bb).real)]
    converged = False
    for _ in range(1, max_it + 1):
        grad = gram @ w - a_tb
        z = w - step * grad
        w_new = soft_threshold(z, threshold)  # λ=0 时阈值全 0 → 恒等（纯梯度下降）
        r = a @ w_new - bb
        obj_new = 0.5 * float(np.vdot(r, r).real) + lam * float(np.sum(w_pen * np.abs(w_new)))
        rel_change = float(np.linalg.norm(w_new - w)) / max(float(np.linalg.norm(w_new)), _TINY)
        w = w_new
        history.append(obj_new)
        if rel_change < inner_tol:
            converged = True
            break
    return {
        "weights": w,
        "objective_history": history,
        "n_iter": len(history) - 1,  # 每次迭代恰一条 obj 记录（初值除外）
        "converged": converged,
    }


def irwl1_reweight(
    A: np.ndarray,
    b: np.ndarray,
    *,
    lambda_reg: float = 1e-2,
    epsilon: float = 1e-2,
    max_reweight_iter: int = 15,
    tol: float = 1e-6,
    inner_max_iter: int = 500,
    inner_tol: float = 1e-10,
    nonzero_abs_tol: float = 1e-6,
) -> dict:
    """ℓ1 重加权外层循环（Candès-Wakin-Boyd 2008）。

    ω⁽ᵏ⁾ₙ = 1/(|w⁽ᵏ⁻¹⁾ₙ| + ε)，初轮 ω = 1（纯 BPDN）；外层收敛判据
    ‖Δw‖/‖w‖ < tol 或触 max_reweight_iter。返回 dict：weights（复 1-D）、
    sparsity_trajectory（每轮后 |w| > nonzero_abs_tol 的非零计数，含初轮）、
    outer_iterations、outer_converged。
    """
    lam = _finite_float(lambda_reg, "lambda_reg")
    if lam < 0.0:
        raise ValueError(f"lambda_reg 必须 >= 0，收到 {lambda_reg!r}")
    eps = _finite_float(epsilon, "epsilon")
    if eps <= 0.0:
        raise ValueError(f"epsilon 必须 > 0，收到 {epsilon!r}")
    max_outer = _positive_int(max_reweight_iter, "max_reweight_iter")
    outer_tol = _finite_float(tol, "tol")
    if outer_tol <= 0.0:
        raise ValueError(f"tol 必须 > 0，收到 {tol!r}")
    nz_tol = _finite_float(nonzero_abs_tol, "nonzero_abs_tol")
    if nz_tol < 0.0:
        raise ValueError(f"nonzero_abs_tol 必须 >= 0，收到 {nonzero_abs_tol!r}")

    a = np.asarray(A, dtype=complex)
    bb = np.asarray(b, dtype=complex)
    n_col = a.shape[1]
    pen = np.ones(n_col, dtype=float)
    trajectory: list[int] = []
    w = np.zeros(n_col, dtype=complex)
    prev_w = None
    converged = False
    for _ in range(1, max_outer + 1):
        solved = weighted_lasso_ista(
            a, bb, pen, lam, max_iter=inner_max_iter, tol=inner_tol
        )
        w = solved["weights"]
        trajectory.append(int(np.sum(np.abs(w) > nz_tol)))
        # 外层收敛判据（Candès 2008）：相对变化 < tol（prev_w is not None 判缺失，#364④）
        if prev_w is not None and _relative_l2(w, prev_w) < outer_tol:
            converged = True
            break
        prev_w = w
        pen = 1.0 / (np.abs(w) + eps)
    return {
        "weights": w,
        "sparsity_trajectory": trajectory,
        "outer_iterations": len(trajectory),  # 每轮恰一条轨迹记录
        "outer_converged": converged,
    }


def _relative_l2(x: np.ndarray, y: np.ndarray) -> float:
    """‖x − y‖₂ / max(‖y‖₂, tiny)（外层相对变化度量）。"""
    denom = float(np.linalg.norm(y))
    if denom <= _TINY:
        return float("inf") if float(np.linalg.norm(x)) > _TINY else 0.0
    return float(np.linalg.norm(x - y)) / denom


# ─── 对照面：密度锥削参考 ───────────────────────────────────────────────────────


def density_taper_indices(n_grid: int, k_sparse: int, *, seed: int = DEFAULT_TAPER_SEED) -> np.ndarray:
    """密度锥削抽稀：从 N_grid 个候选中等概率无放回抽 K 个（保序返回索引）。

    probabilistic thinning 惯例（均匀权、随机置位）；固定 seed 的
    default_rng 保证对照面可复现（同 seed → 同索引，单测钉）。
    """
    n = _positive_int(n_grid, "n_grid")
    k = _positive_int(k_sparse, "k_sparse")
    if k > n:
        raise ValueError(f"k_sparse（{k}）不得超过 n_grid（{n}）")
    seed_val = _nonneg_int(seed, "seed")
    rng = np.random.default_rng(seed_val)
    return np.sort(rng.choice(n, size=k, replace=False))


# ─── 结果度量 ──────────────────────────────────────────────────────────────────


def _envelope_residual_db(pattern: np.ndarray, target: np.ndarray) -> float:
    """包络残差（dB）：20·log10(‖|pattern| − |target|‖₂ / ‖target|‖₂)。

    完美拟合 → −inf（JSON 面由 to_dict 转 None）；量纲：相对目标包络
    L2 范数的电压比。
    """
    diff = float(np.linalg.norm(np.abs(pattern) - np.abs(target)))
    denom = float(np.linalg.norm(np.abs(target)))
    if denom <= _TINY:
        raise ValueError("目标包络 L2 范数为 0，无法计算残差")
    return 20.0 * math.log10(diff / denom)


def _psll_db(pattern: np.ndarray, u: np.ndarray, main_lobe_u: float) -> float:
    """PSLL（dB，相对主瓣峰值）；无副瓣候选时 −inf（如实返回）。"""
    return float(
        peak_sidelobe_level_db(
            np.abs(pattern), u, main_lobe_direction_cosine=main_lobe_u
        )
    )


# ─── 顶层综合 ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DensityTaperComparison:
    """密度锥削对照面（判据用）：均匀权随机抽稀参考 vs IRWL1 的 PSLL。"""

    taper_indices: tuple[int, ...]
    taper_psll_db: float
    irwl1_psll_db: float
    band_db: float = PSLL_BAND_DB

    @property
    def within_band(self) -> bool:
        """预声明带：irwl1_psll ≤ taper_psll + band_db（不保证更优，如实实测）。"""
        return self.irwl1_psll_db <= self.taper_psll_db + self.band_db

    def to_dict(self) -> dict:
        return {
            "taper_indices": [int(i) for i in self.taper_indices],
            "taper_psll_db": _finite_or_none(self.taper_psll_db),
            "irwl1_psll_db": _finite_or_none(self.irwl1_psll_db),
            "band_db": self.band_db,
            "within_band": bool(self.within_band),
        }


@dataclass(frozen=True)
class SparseArrayDesign:
    """IRWL1 稀疏阵综合结果（支撑集 + 复权重 + 方向图面 + 对照面）。"""

    selected_indices: tuple[int, ...]
    positions_selected_lambda: np.ndarray
    weights: np.ndarray  # 复 1-D（K 个）
    u_values: np.ndarray
    pattern_reconstructed: np.ndarray  # 复 1-D（选中单元在 u 网格上的场）
    pattern_target: np.ndarray  # 归一化目标（复 1-D）
    target_was_real: bool  # True = 包络口径（实值目标），False = 复场口径
    residual_db: float  # 包络残差 20log10(‖|AF|−|b|‖/‖b‖)，−inf=完美
    psll_db: float  # 重构方向图 PSLL
    target_psll_db: float
    mutual_coherence: float
    k_sparse: int
    n_grid: int
    lambda_reg: float
    epsilon: float
    scan_direction_cosine: float
    sparsity_trajectory: tuple[int, ...]
    outer_iterations: int
    outer_converged: bool
    taper: DensityTaperComparison

    def to_dict(self) -> dict:
        """JSON 可序列化（复数 → [re, im]；非有限 float → None）。"""
        return {
            "selected_indices": [int(i) for i in self.selected_indices],
            "positions_selected_lambda": [float(v) for v in self.positions_selected_lambda],
            "weights": [[float(v.real), float(v.imag)] for v in self.weights],
            "u_values": [float(v) for v in self.u_values],
            "pattern_reconstructed": [
                [float(v.real), float(v.imag)] for v in self.pattern_reconstructed
            ],
            "pattern_target": [[float(v.real), float(v.imag)] for v in self.pattern_target],
            "target_was_real": bool(self.target_was_real),
            "residual_db": _finite_or_none(self.residual_db),
            "psll_db": _finite_or_none(self.psll_db),
            "target_psll_db": _finite_or_none(self.target_psll_db),
            "mutual_coherence": _finite_or_none(self.mutual_coherence),
            "k_sparse": int(self.k_sparse),
            "n_grid": int(self.n_grid),
            "lambda_reg": float(self.lambda_reg),
            "epsilon": float(self.epsilon),
            "scan_direction_cosine": float(self.scan_direction_cosine),
            "sparsity_trajectory": [int(v) for v in self.sparsity_trajectory],
            "outer_iterations": int(self.outer_iterations),
            "outer_converged": bool(self.outer_converged),
            "taper": self.taper.to_dict(),
        }


def _finite_or_none(value: float) -> float | None:
    """非有限 float → None（json.dumps 兼容；0.0 合法，判缺失 is not None）。"""
    out = float(value)
    return out if math.isfinite(out) else None


def synthesize_sparse_array(
    positions_lambda,
    target,
    k_sparse,
    *,
    u_values=None,
    theta_deg=None,
    axis: str = "z",
    phi_deg: float = 0.0,
    scan_direction_cosine: float = 0.0,
    lambda_reg: float = 1e-2,
    epsilon: float = 1e-2,
    max_reweight_iter: int = 15,
    tol: float = 1e-6,
    inner_max_iter: int = 500,
    inner_tol: float = 1e-10,
    nonzero_abs_tol: float = 1e-6,
    taper_seed: int = DEFAULT_TAPER_SEED,
) -> SparseArrayDesign:
    """IRWL1 稀疏阵综合顶层入口（校验 → BPDN+重加权 → top-K 选择 → lstsq 回代 → 对照面）。

    参数
    ----
    positions_lambda : 候选位置栅格（波长单位，1-D，≥2，无重复，保输入序）
    target : 目标方向图（长度=网格点数）：复数组=复场口径；实数组=包络
        口径（|AF| 曲线，如实登记边界见模块 docstring）。内部按 max|b|
        归一（λ_reg 与绝对尺度解耦；权重为归一化尺度）。
    k_sparse : 稀疏度目标 K（1 ≤ K ≤ N_grid），top-K 截断 + 最小二乘回代
    u_values / theta_deg : 二选一（都给或都不给 → ValueError）；theta_deg
        为度，经 direction_cosine(axis, phi_deg) 映射
    scan_direction_cosine : u0（前向算子与 PSLL 主瓣定位共用）
    lambda_reg : BPDN 正则参数（≥0；<0 → ValueError）
    epsilon : 重加权地板（>0，Candès 2008 的 ε）
    max_reweight_iter / tol : 外层迭代与相对变化收敛判据
    inner_max_iter / inner_tol : ISTA 内层
    nonzero_abs_tol : 非零元计数阈值（轨迹与支撑一致性判据）
    taper_seed : 密度锥削抽稀种子（固定缺省，可复现）

    返回
    ----
    SparseArrayDesign（dataclass，to_dict 提供 JSON 面）。
    """
    p = _validate_positions(positions_lambda)
    n_grid = int(p.size)
    k = _positive_int(k_sparse, "k_sparse")
    if k > n_grid:
        raise ValueError(f"k_sparse（{k}）不得超过候选位置数 N_grid（{n_grid}）")
    lam = _finite_float(lambda_reg, "lambda_reg")
    if lam < 0.0:
        raise ValueError(f"lambda_reg 必须 >= 0，收到 {lambda_reg!r}")

    if u_values is not None and theta_deg is not None:
        raise ValueError("u_values 与 theta_deg 二选一（都给会口径歧义）")
    if u_values is None and theta_deg is None:
        raise ValueError("u_values 与 theta_deg 必须给其一")
    u = _validate_u(u_values) if u_values is not None else u_values_from_theta(
        theta_deg, axis=axis, phi_deg=phi_deg
    )

    b_raw = _validate_target(target, int(u.size))
    raw_arr = np.asarray(target)
    target_was_real = (
        True if not np.iscomplexobj(raw_arr) else not bool(np.any(raw_arr.imag))
    )
    scale = float(np.max(np.abs(b_raw)))
    b = b_raw / scale

    u0 = _finite_float(scan_direction_cosine, "scan_direction_cosine")
    if abs(u0) > 1.0 + 1e-9:
        raise ValueError(f"scan_direction_cosine 必须落在 [-1, 1]，收到 {scan_direction_cosine!r}")

    a_mat = forward_matrix(p, u, scan_direction_cosine=u0)
    coh = mutual_coherence(a_mat)

    solved = irwl1_reweight(
        a_mat,
        b,
        lambda_reg=lam,
        epsilon=epsilon,
        max_reweight_iter=max_reweight_iter,
        tol=tol,
        inner_max_iter=inner_max_iter,
        inner_tol=inner_tol,
        nonzero_abs_tol=nonzero_abs_tol,
    )

    # top-K 支撑选择（|w| 降序稳定截断）+ 最小二乘回代（去收缩偏置）
    order = np.argsort(-np.abs(solved["weights"]), kind="stable")
    support = np.sort(order[:k])
    a_sel = a_mat[:, support]
    w_sel, *_ = np.linalg.lstsq(a_sel, b, rcond=None)
    pattern = a_sel @ w_sel

    residual_db = _envelope_residual_db(pattern, b)
    psll = _psll_db(pattern, u, u0)
    target_psll = _psll_db(b, u, u0)

    # 密度锥削对照面：同栅格随机抽 K、均匀权、同网格 PSLL
    taper_idx = density_taper_indices(n_grid, k, seed=taper_seed)
    taper_pattern = a_mat[:, taper_idx] @ np.ones(k, dtype=complex)
    taper_psll = _psll_db(taper_pattern, u, u0)

    return SparseArrayDesign(
        selected_indices=tuple(int(i) for i in support),
        positions_selected_lambda=p[support],
        weights=w_sel,
        u_values=u,
        pattern_reconstructed=pattern,
        pattern_target=b,
        target_was_real=bool(target_was_real),
        residual_db=float(residual_db),
        psll_db=psll,
        target_psll_db=target_psll,
        mutual_coherence=coh,
        k_sparse=k,
        n_grid=n_grid,
        lambda_reg=lam,
        epsilon=_finite_float(epsilon, "epsilon"),
        scan_direction_cosine=u0,
        sparsity_trajectory=tuple(int(v) for v in solved["sparsity_trajectory"]),
        outer_iterations=int(solved["outer_iterations"]),
        outer_converged=bool(solved["outer_converged"]),
        taper=DensityTaperComparison(
            taper_indices=tuple(int(i) for i in taper_idx),
            taper_psll_db=taper_psll,
            irwl1_psll_db=psll,
            band_db=PSLL_BAND_DB,
        ),
    )
