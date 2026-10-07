"""M-2.1 阵列测量闭环·校准核：复增益分级解（firstcal/logcal/lincal）+ 冗余简并分析。

权威口径（机制借镜 + 纯 numpy 自实现；MIT 许可、零依赖引入）
========
- HERA-Team/hera_cal ``hera_cal/redcal.py``（GitHub master，MIT License；
  2026-09-26 经 web 抓取核对，**单源**——论文原文未逐篇另核，如实标注）：
  * firstcal：原 docstring "Solve for a calibration solution parameterized by
    a single delay and phase offset per antenna ... Delays are solved in a
    single iteration, but phase offsets are solved for iteratively to account
    for phase wraps."；增益形 ``g = exp(2j*pi*delay*freqs + 1j*offset)``——
    本模块同一符号约定（延迟 = 频域线性相位，正号）；
  * logcal：原 docstring "Takes the log to linearize redcal equations and
    minimizes chi^2"——hera_cal 用 linsolve.LogProductSolver 做**单次全局
    线性解**（组内 detrend 处理相位 wrap，detrend_phs=True）；本模块同口径
    （幅值域精确线性一次解 + 相位域 wrapped 残差迭代线性解），
    **非**逐基线序贯贪心（该印象未被源码证实，已按源码口径纠正）；
  * lincal：原 docstring "Taylor expands to linearize redcal equations and
    iteratively minimizes chi^2"（conv_crit 按解相对变化、maxiter 缺省 50）——
    本模块同语义：复增益实虚域 Gauss-Newton，解相对变化收敛判据；
  * 简并：hera_cal ``remove_degen_gains``——1pol 相位简并为 "1 overall phase
    and 2 tip-tilt terms"（按天线位置的投影矩阵，arXiv:1712.07212）。
- Omnical：Liu et al 2010（hera_cal redcal.py 内引）；HERA Memo 50
  （omnical 线性化口径，redcal.py 内引）。
- 本模块 ``redundant_group_degeneracy`` 只做**图论简并分析**（输入仅
  baseline_pairs/n_ant，无天线坐标）：已知每基线真值口径下，相位域简并
  = 每连通分量 1 维全局相位；幅值域简并 = 每二部连通分量 1 维"棋盘"模
  （+1/+1 关联矩阵零空间）。hera_cal 的位置斜坡（tip-tilt）简并需要天线
  坐标输入，超出本签名，**未涵盖**（如实标注）。

一阶模型与物理语义（不虚构）
========
- 观测模型：``V_ij(f) = g_i(f) * conj(g_j(f)) * V_ij^true(f) + n_ij(f)``，
  每元复增益 ``g_i(f) = A_i * exp(j*phi_i) * exp(2j*pi*f*tau_i)``
  （hera_cal firstcal 增益形，含幅值/相位/延迟三因子）。
- 冗余/已知真值校准**天生丢绝对指向**：全局延迟常数与跨阵延迟斜坡和源
  位置简并（延迟斜坡 = 视场平移），全局相位同理——锚定参考元后解出的
  延迟/相位只到"相对参考元"的相对量，**绝对方向信息 UNDETERMINED**，
  本模块不虚构绝对指向输出。

形状约定（全模块统一，入参违规一律 ValueError）
========
- ``V``/``v_true_by_baseline``：shape ``(n_baseline, n_freq)`` 复数矩阵
  （实数输入按虚部为零转复数；bool/NaN/Inf 拒收）；
- ``f_axis``：shape ``(n_freq,)``，严格递增（unwrap 正确性前提）；
- 增益解：shape ``(n_ant, n_freq)`` 复数；``n_ant`` 由 baseline_pairs
  推断（max index + 1），求解类函数要求基线图连通（含 ref_ant），
  不连通分量增益不可锚定 → ValueError；
- ``baseline_pairs``：``Sequence[tuple[int, int]]``，i != j、无重复、
  索引在 [0, n_ant) 内。

本模块为 core 隔离件：纯 numpy、零 IO、不进注册表；接线（array_service
calibrate 端点）留后续批次。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = [
    "apply_delay_correction",
    "firstcal_delay_solve",
    "lincal_gain_solve",
    "logcal_gain_solve",
    "redundant_group_degeneracy",
]

_TWO_PI = 2.0 * np.pi
_LOGCAL_MAX_PHASE_ITER = 50
_LOGCAL_STEP_TOL = 1e-12
_LINCAL_MAX_ITER = 50
_LINCAL_CONV_CRIT = 1e-10
_LINCAL_PINV_RCOND = 1e-10


def _wrap(x: np.ndarray) -> np.ndarray:
    """折回 (-pi, pi]。"""
    return np.angle(np.exp(1j * x))


def _as_complex_matrix(x: object, name: str) -> np.ndarray:
    """校验并转换为 (n_baseline, n_freq) 复数矩阵；bool/NaN/Inf/非二维拒收。"""
    arr = np.asarray(x)
    if arr.dtype == bool:
        raise ValueError(f"{name} 为 bool 数组，拒绝（数值入参不得含 bool）")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"{name} 必须是数值数组，得到 dtype={arr.dtype}")
    arr = arr.astype(complex)
    if arr.ndim != 2:
        raise ValueError(f"{name} 形状必须是 (n_baseline, n_freq) 二维，得到 ndim={arr.ndim}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含 NaN/Inf，拒绝")
    return arr


def _validate_f_axis(f_axis: object, n_freq: int) -> np.ndarray:
    """校验频率轴：一维、长度匹配、有限、严格递增。"""
    fa = np.asarray(f_axis)
    if fa.dtype == bool:
        raise ValueError("f_axis 为 bool 数组，拒绝")
    if not np.issubdtype(fa.dtype, np.number):
        raise ValueError(f"f_axis 必须是数值数组，得到 dtype={fa.dtype}")
    if fa.ndim != 1:
        raise ValueError(f"f_axis 必须一维，得到 ndim={fa.ndim}")
    fa = fa.astype(float)
    if fa.shape[0] != n_freq:
        raise ValueError(f"f_axis 长度 {fa.shape[0]} 与 V 的 n_freq={n_freq} 不一致")
    if not np.all(np.isfinite(fa)):
        raise ValueError("f_axis 含 NaN/Inf，拒绝")
    if not np.all(np.diff(fa) > 0):
        raise ValueError("f_axis 必须严格递增（unwrap 正确性前提）")
    return fa


def _validate_pairs(
    baseline_pairs: Sequence[tuple[int, int]], n_ant: int | None = None
) -> tuple[np.ndarray, int]:
    """校验基线对，返回 (pairs, n_ant) 数组 (M, 2)；重复/自配/越界/bool 拒收。

    n_ant 为 None 时按 max index + 1 推断（文档口径：孤立天线将导致不连通，
    由调用方的连通性检查拒绝）。
    """
    if len(baseline_pairs) == 0:
        raise ValueError("baseline_pairs 为空，至少需要 1 条基线")
    cleaned: list[tuple[int, int]] = []
    for k, pair in enumerate(baseline_pairs):
        if len(pair) != 2:
            raise ValueError(f"baseline_pairs[{k}] 长度必须是 2，得到 {len(pair)}")
        i, j = pair
        for name, v in (("i", i), ("j", j)):
            if isinstance(v, (bool, np.bool_)):
                raise ValueError(f"baseline_pairs[{k}].{name} 是 bool，拒绝")
            if not isinstance(v, (int, np.integer)):
                raise ValueError(f"baseline_pairs[{k}].{name} 必须是整数，得到 {type(v).__name__}")
        if i == j:
            raise ValueError(f"baseline_pairs[{k}] 自配对 ({i}, {j})，拒绝")
        cleaned.append((int(i), int(j)))
    inferred = max(max(p) for p in cleaned) + 1
    n = inferred if n_ant is None else n_ant
    for k, (i, j) in enumerate(cleaned):
        if not (0 <= i < n and 0 <= j < n):
            raise ValueError(f"baseline_pairs[{k}] = ({i}, {j}) 越界（n_ant={n}）")
    arr = np.asarray(cleaned, dtype=int)
    seen: set[tuple[int, int]] = set()
    for k, p in enumerate(map(tuple, arr.tolist())):
        if p in seen:
            raise ValueError(f"baseline_pairs[{k}] 重复基线 {p}，拒绝")
        seen.add(p)
    return arr, n


def _adjacency(pairs: np.ndarray, n_ant: int) -> list[list[int]]:
    adj: list[list[int]] = [[] for _ in range(n_ant)]
    for i, j in pairs.tolist():
        adj[i].append(j)
        adj[j].append(i)
    return adj


def _check_connected(pairs: np.ndarray, n_ant: int, ref_ant: int) -> None:
    """求解类函数的连通性守卫：不连通分量的增益不可锚定，如实拒绝。"""
    adj = _adjacency(pairs, n_ant)
    seen = {ref_ant}
    stack = [ref_ant]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                stack.append(v)
    if len(seen) != n_ant:
        missing = sorted(set(range(n_ant)) - seen)
        raise ValueError(
            f"基线图不连通：天线 {missing} 与参考元 {ref_ant} 无基线相连，"
            "其增益不可锚定/不可解（如实拒绝，不做不可解的插值）"
        )


def _checkerboard_side(
    pairs: np.ndarray, n_ant: int, ref_ant: int
) -> np.ndarray | None:
    """从 ref 出发 2 染色，返回 ±1 侧标签；含奇圈（非二部）返回 None。

    幅值方程 a_i + a_j = ln|W_ij| 的零空间 = 二部分量的棋盘向量
    side（跨边反号）；非二部分量该零空间为空（幅值被数据唯一确定）。
    """
    adj = _adjacency(pairs, n_ant)
    side = np.zeros(n_ant, dtype=float)
    side[ref_ant] = 1.0
    stack = [ref_ant]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if side[v] == 0.0:
                side[v] = -side[u]
                stack.append(v)
            elif side[v] == side[u]:
                return None
    return side


def _validate_ref(ref_ant: int, n_ant: int) -> int:
    if isinstance(ref_ant, (bool, np.bool_)):
        raise ValueError("ref_ant 是 bool，拒绝")
    if not isinstance(ref_ant, (int, np.integer)):
        raise ValueError(f"ref_ant 必须是整数，得到 {type(ref_ant).__name__}")
    if not 0 <= int(ref_ant) < n_ant:
        raise ValueError(f"ref_ant={ref_ant} 越界（n_ant={n_ant}）")
    return int(ref_ant)


def firstcal_delay_solve(
    V: np.ndarray,
    baseline_pairs: Sequence[tuple[int, int]],
    f_axis: np.ndarray,
    ref_ant: int = 0,
) -> dict[str, object]:
    """firstcal 纯延迟解：每基线相位斜率 → 每元延迟最小二乘（锚定参考元）。

    机制出处：hera_cal redcal.firstcal——"single delay and phase offset per
    antenna"，增益形 ``g = exp(2j*pi*delay*freqs + 1j*offset)``；延迟经
    "phase difference between ... measurements" 一次解出。本实现对每条基线
    做频率轴 ``np.unwrap`` 后线性最小二乘拟合斜率
    ``s_ij = d(angle(V_ij))/df = 2*pi*(tau_i - tau_j)``，再用带符号关联矩阵
    最小二乘解每元延迟并锚定 ``tau_ref = 0``。

    简并与物理语义：延迟零空间 = 全局常数（1 维/连通分量），锚定参考元后
    唯一；跨阵延迟斜坡与源位置简并（= 视场平移）——**绝对指向
    UNDETERMINED**，解出的是相对参考元的相对延迟。

    假设（如实标注）：相邻频点相位步进 ``2*pi*|df*tau| < pi`` 时 unwrap
    无歧义；V 的每基线真值若自带延迟，会一并落入拟合斜率（延迟分解在
    "天线/源"间不可分辨，与 hera_cal firstcal 对原始数据拟合的口径一致）。

    Parameters
    ----------
    V : ndarray, shape (n_baseline, n_freq)
        观测复可见度（行序与 baseline_pairs 一致）。
    baseline_pairs : Sequence[tuple[int, int]]
        基线对 (i, j)，i != j、无重复。
    f_axis : ndarray, shape (n_freq,)
        严格递增频率轴（Hz）。
    ref_ant : int
        参考元（锚定 tau_ref = 0）。

    Returns
    -------
    dict with keys:
        per_ant_delay_s : ndarray (n_ant,) —— 锚定后的每元延迟（秒）；
        baseline_delay_diff_s : ndarray (n_baseline,) —— 拟合斜率换算的
            每基线延迟差 (tau_i - tau_j)；
        residual_phase_after_delay : ndarray (n_baseline,) —— 每基线
            unwrap 相位对"延迟线性模型"拟合残差的 RMS（rad，衡量延迟单因子
            模型对相位-频率依赖的解释余量）；
        degeneracy_note : str —— 简并口径说明。
    """
    vm = _as_complex_matrix(V, "V")
    n_bl, n_freq = vm.shape
    pairs, n_ant = _validate_pairs(baseline_pairs)
    if pairs.shape[0] != n_bl:
        raise ValueError(f"V 行数 {n_bl} 与 baseline_pairs 数 {pairs.shape[0]} 不一致")
    fa = _validate_f_axis(f_axis, n_freq)
    ref = _validate_ref(ref_ant, n_ant)
    _check_connected(pairs, n_ant, ref)

    theta = np.unwrap(np.angle(vm), axis=1)  # (M, F)，频率轴已验严格递增
    f0 = fa - fa.mean()
    theta_c = theta - theta.mean(axis=1, keepdims=True)
    denom = float(f0 @ f0)
    slope = (theta_c @ f0) / denom  # (M,) rad/Hz
    bl_delay_diff = slope / _TWO_PI  # (M,) = tau_i - tau_j（hera_cal 正号约定）

    # 带符号关联矩阵 S（M x N）：S[b, i] = +1, S[b, j] = -1；解 S·tau = diff
    s_mat = np.zeros((n_bl, n_ant))
    rows = np.arange(n_bl)
    s_mat[rows, pairs[:, 0]] = 1.0
    s_mat[rows, pairs[:, 1]] = -1.0
    tau = np.linalg.pinv(s_mat) @ bl_delay_diff
    tau = tau - tau[ref]  # 锚定参考元（零空间 = 全局延迟常数）

    # 延迟移除后的相位残差（对每基线线性模型的拟合残差 RMS）
    model = slope[:, None] * fa[None, :] + (theta.mean(axis=1) - slope * fa.mean())[:, None]
    residual = theta - model
    residual_rms = np.sqrt(np.mean(residual**2, axis=1))

    return {
        "per_ant_delay_s": tau,
        "baseline_delay_diff_s": bl_delay_diff,
        "residual_phase_after_delay": residual_rms,
        "degeneracy_note": (
            "延迟零空间 = 全局延迟常数（每连通分量 1 维），已锚定 "
            f"tau[{ref}]=0；跨阵延迟斜坡与源位置简并（视场平移），"
            "绝对指向 UNDETERMINED——输出仅为相对参考元的相对延迟。"
        ),
    }


def apply_delay_correction(
    V: np.ndarray,
    baseline_pairs: Sequence[tuple[int, int]],
    f_axis: np.ndarray,
    per_ant_delay_s: np.ndarray,
) -> np.ndarray:
    """按 firstcal 解除每基线延迟相位：V_out = V * exp(-2j*pi*f*(tau_i-tau_j))。

    供链式流程（firstcal → logcal → lincal）使用；符号与 hera_cal
    增益形 g = exp(2j*pi*delay*freqs) 一致（见模块 docstring 一阶模型）。
    """
    vm = _as_complex_matrix(V, "V")
    pairs, n_ant = _validate_pairs(baseline_pairs)
    if vm.shape[0] != pairs.shape[0]:
        raise ValueError("V 行数与 baseline_pairs 数不一致")
    fa = _validate_f_axis(f_axis, vm.shape[1])
    tau = np.asarray(per_ant_delay_s)
    if tau.dtype == bool or not np.issubdtype(tau.dtype, np.number):
        raise ValueError("per_ant_delay_s 必须是数值数组")
    tau = tau.astype(float).reshape(-1)
    if tau.shape[0] != n_ant or not np.all(np.isfinite(tau)):
        raise ValueError("per_ant_delay_s 长度须为 n_ant 且有限")
    diff = tau[pairs[:, 0]] - tau[pairs[:, 1]]  # (M,)
    out: np.ndarray = vm * np.exp(-1j * _TWO_PI * fa[None, :] * diff[:, None])
    return out


def logcal_gain_solve(
    V: np.ndarray,
    baseline_pairs: Sequence[tuple[int, int]],
    v_true_by_baseline: np.ndarray,
    ref_ant: int = 0,
    tol: float = 1e-8,
) -> dict[str, object]:
    """logcal 对数幅相线性解（单次全局线性解口径，hera_cal 同）。

    机制出处：hera_cal redcal.logcal——"Takes the log to linearize redcal
    equations and minimizes chi^2"，linsolve.LogProductSolver 单次全局线性
    解（组内 detrend 处理 wrap）。本实现：归一观测 ``W = V / V_true`` 满足
    ``W_ij = g_i * conj(g_j)``，取对数/幅角线性化：
    * 幅值域 ``ln|W_ij| = a_i + a_j``（a = ln|g|）——**精确**线性，一次
      最小二乘（pinv 最小范数解）；
    * 相位域 ``angle(W_ij) = phi_i - phi_j (mod 2pi)``——参考元 BFS 树展开
      作初值 + wrapped 残差迭代最小二乘（等价 hera_cal 的 wrap 处理，
      机制差异：本实现逐基线 wrap 后全局解，hera_cal 组内 detrend）。
    与 hera_cal 序贯/贪心实现的差异注记：hera_cal v1 亦为全局线性解而非
    逐基线序贯更新（源码核对，2026-09-26）；两者解同一线性化方程组。

    简并处理（只动真零空间方向，不虚构）：相位域全局相位每连通分量 1 维
    → 锚定 phi_ref = 0；幅值域已知真值模型的全局幅值**不是**自由度
    （g→c·g 使 |W| 变 |c|²，非不变量）——非二部（含奇圈）分量幅值被数据
    唯一确定，参考元幅值不可重归一（除非真值本身如此）；二部分量棋盘
    自由度平移到 a_ref = 0 代表元。简并空间维度见
    :func:`redundant_group_degeneracy`。

    Parameters
    ----------
    V, v_true_by_baseline : ndarray, shape (n_baseline, n_freq)
        观测与每基线真值；真值含零元时对数无定义 → 拒收。
    baseline_pairs : Sequence[tuple[int, int]]
    ref_ant : int
    tol : float
        收敛（复残差 RMS 相对阈值）与迭代步长阈值共用。

    Returns
    -------
    dict with keys:
        gains : ndarray (n_ant, n_freq) 复数；
        iterations : int —— 相位域 wrapped 迭代次数；
        converged : bool —— 相位迭代达不动点（步长 < 1e-12）；
        residual_rms : float —— rms|W - g_i conj(g_j)| / rms|W|。
    """
    vm = _as_complex_matrix(V, "V")
    vt = _as_complex_matrix(v_true_by_baseline, "v_true_by_baseline")
    if vm.shape != vt.shape:
        raise ValueError(f"V 形状 {vm.shape} 与 v_true_by_baseline 形状 {vt.shape} 不一致")
    if np.any(np.abs(vt) == 0):
        raise ValueError("v_true_by_baseline 含零元，对数线性化无定义，拒绝")
    if np.any(np.abs(vm) == 0):
        raise ValueError("V 含零元，对数线性化无定义，拒绝")
    pairs, n_ant = _validate_pairs(baseline_pairs)
    if pairs.shape[0] != vm.shape[0]:
        raise ValueError("V 行数与 baseline_pairs 数不一致")
    ref = _validate_ref(ref_ant, n_ant)
    _check_connected(pairs, n_ant, ref)

    w_obs = vm / vt  # (M, F)：W_ij = g_i conj(g_j)
    ib, jb = pairs[:, 0], pairs[:, 1]
    n_bl, n_freq = w_obs.shape

    # 带符号关联矩阵与 +1/+1 关联矩阵（幅值域）
    s_mat = np.zeros((n_bl, n_ant))
    b_amp = np.zeros((n_bl, n_ant))
    rows = np.arange(n_bl)
    s_mat[rows, ib] = 1.0
    s_mat[rows, jb] = -1.0
    b_amp[rows, ib] = 1.0
    b_amp[rows, jb] = 1.0
    pinv_p = np.linalg.pinv(s_mat)
    pinv_a = np.linalg.pinv(b_amp)

    # 幅值域：精确线性，一次最小二乘（非二部图解唯一；二部图为最小范数代表元）
    amp = pinv_a @ np.log(np.abs(w_obs))  # (N, F)

    # 相位域：参考元 BFS 树展开初值 + wrapped 残差迭代。
    # 注意：mod-2π 系统对任意 0/π 标签 s 存在伪不动点 φ+π·s（wrap(±2π)=0，
    # 共 2^{N-1} 个分支）——树展开必须按带符号边角进入正确分支；噪声水平
    # ≪ π 时收敛后不会跨分支，残差量级由 residual_rms 供调用方复核。
    theta = np.angle(w_obs)  # (M, F)
    adj = _adjacency(pairs, n_ant)
    phi = np.zeros((n_ant, n_freq))
    visited = {ref}
    queue = [ref]
    edge_angle: dict[tuple[int, int], np.ndarray] = {}
    for b_idx, (i, j) in enumerate(zip(ib.tolist(), jb.tolist(), strict=True)):
        edge_angle[(i, j)] = theta[b_idx]
        edge_angle[(j, i)] = -theta[b_idx]  # 反向边角反号（θ_vu = φ_v−φ_u = −θ_ij）
    while queue:
        u = queue.pop(0)
        for v in adj[u]:
            if v not in visited:
                visited.add(v)
                phi[v] = phi[u] - _wrap(edge_angle[(u, v)])
                queue.append(v)

    iterations = 0
    step = np.inf
    while iterations < _LOGCAL_MAX_PHASE_ITER:
        iterations += 1
        resid = _wrap(theta - (phi[ib] - phi[jb]))  # (M, F)
        dphi = pinv_p @ resid
        phi = phi + dphi
        step = float(np.max(np.abs(dphi)))
        if step < _LOGCAL_STEP_TOL:
            break

    # 锚定（只动真零空间方向，不破坏方程）：
    # - 相位：全局相位零空间（每连通分量 1 维）→ phi_ref 归零；
    # - 幅值：已知真值模型的全局幅值**不是**自由度（g→c·g 使 |W| 变 |c|²，
    #   非不变量），非二部图幅值唯一、参考元幅值不可重归一；二部图棋盘
    #   自由度 → 平移到 a_ref = 0 的代表元。
    phi = phi - phi[ref][None, :]
    side = _checkerboard_side(pairs, n_ant, ref)
    if side is not None:
        t = amp[ref] * side[ref]
        amp = amp - t[None, :] * side[:, None]
    gains = np.exp(amp) * np.exp(1j * phi)  # (N, F)

    pred = gains[ib] * np.conj(gains[jb])
    residual_rms = float(np.sqrt(np.mean(np.abs(w_obs - pred) ** 2)) / np.sqrt(np.mean(np.abs(w_obs) ** 2)))
    return {
        "gains": gains,
        "iterations": int(iterations),
        "converged": bool(step < 1e-8),
        "residual_rms": residual_rms,
    }


def lincal_gain_solve(
    V: np.ndarray,
    baseline_pairs: Sequence[tuple[int, int]],
    v_true_by_baseline: np.ndarray,
    g_init: np.ndarray | None = None,
    ref_ant: int = 0,
    tol: float = 1e-12,
    max_iter: int = _LINCAL_MAX_ITER,
    conv_crit: float = _LINCAL_CONV_CRIT,
) -> dict[str, object]:
    """lincal 线性化最小二乘：复增益实虚域 Gauss-Newton（hera_cal 同语义）。

    机制出处：hera_cal redcal.lincal——"Taylor expands to linearize redcal
    equations and iteratively minimizes chi^2"（conv_crit 按解相对变化、
    maxiter 缺省 50，本实现同）。目标泛函 ``min sum_ij |W_ij -
    g_i conj(g_j)|^2``（W = V/V_true），对复增益实虚部分量 Gauss-Newton：
    每步组装 (2M x 2N) 实雅可比（批量按频点），pinv 最小范数步自动投影掉
    零空间（全局相位 / 二部图棋盘幅值），并逐步重锚参考元全局相位。

    初值：``g_init=None`` 时由 :func:`logcal_gain_solve` 启动（anchored）；
    外部 ``g_init`` 须全体非零（零增益使 GN 步长归一无定义）。

    Parameters
    ----------
    V, v_true_by_baseline : ndarray, shape (n_baseline, n_freq)
    g_init : ndarray (n_ant, n_freq) 复数 or None
    ref_ant : int
    tol : float —— 残差 RMS 相对阈值（提前收敛）。
    max_iter : int —— 最大 GN 迭代数（hera_cal lincal maxiter 缺省 50）。
    conv_crit : float —— 解相对变化收敛阈值（hera_cal conv_crit 语义）。

    Returns
    -------
    dict with keys:
        gains : ndarray (n_ant, n_freq) 复数；
        n_iter : int —— 实际 GN 迭代数；
        converged : bool；
        residual_rms : float —— rms|W - g_i conj(g_j)| / rms|W|。
    """
    vm = _as_complex_matrix(V, "V")
    vt = _as_complex_matrix(v_true_by_baseline, "v_true_by_baseline")
    if vm.shape != vt.shape:
        raise ValueError(f"V 形状 {vm.shape} 与 v_true_by_baseline 形状 {vt.shape} 不一致")
    if np.any(np.abs(vt) == 0):
        raise ValueError("v_true_by_baseline 含零元，归一化无定义，拒绝")
    pairs, n_ant = _validate_pairs(baseline_pairs)
    if pairs.shape[0] != vm.shape[0]:
        raise ValueError("V 行数与 baseline_pairs 数不一致")
    ref = _validate_ref(ref_ant, n_ant)
    _check_connected(pairs, n_ant, ref)

    if g_init is None:
        g = logcal_gain_solve(vm, baseline_pairs, vt, ref_ant=ref)["gains"]
        assert isinstance(g, np.ndarray)
    else:
        g = _as_complex_matrix(g_init, "g_init")
        if g.shape != (n_ant, vm.shape[1]):
            raise ValueError(f"g_init 形状 {g.shape} 与 (n_ant, n_freq)={(n_ant, vm.shape[1])} 不一致")
        if np.any(np.abs(g) == 0):
            raise ValueError("g_init 含零增益，Gauss-Newton 步长归一无定义，拒绝")
    w_obs = vm / vt
    ib, jb = pairs[:, 0], pairs[:, 1]
    n_bl, n_freq = w_obs.shape
    rows = np.arange(n_bl)
    ref_anchor = g[ref].copy()  # (F,) 逐频点复数锚（幅值模长 1 归一只转全局相位）

    def _resid_rms(cur: np.ndarray) -> float:
        pred = cur[ib] * np.conj(cur[jb])
        return float(
            np.sqrt(np.mean(np.abs(w_obs - pred) ** 2)) / np.sqrt(np.mean(np.abs(w_obs) ** 2))
        )

    residual_rms = _resid_rms(g)
    converged = residual_rms <= tol
    n_iter = 0
    while not converged and n_iter < max_iter:
        n_iter += 1
        pred = g[ib] * np.conj(g[jb])  # (M, F)
        r = w_obs - pred
        ja = np.conj(g[jb])  # d pred / d g_i（Wirtinger）
        jb_ = g[ib]  # d pred / d conj(g_j)
        # 实雅可比 (F, 2M, 2N)：偶行 = Re 残差，奇行 = Im 残差；
        # 偶列 = Re(g_k)，奇列 = Im(g_k)
        jac = np.zeros((n_freq, 2 * n_bl, 2 * n_ant))
        jac[:, 2 * rows, 2 * ib] = ja.T.real
        jac[:, 2 * rows, 2 * jb] = jb_.T.real
        jac[:, 2 * rows, 2 * ib + 1] = -ja.T.imag
        jac[:, 2 * rows, 2 * jb + 1] = jb_.T.imag
        jac[:, 2 * rows + 1, 2 * ib] = ja.T.imag
        jac[:, 2 * rows + 1, 2 * jb] = jb_.T.imag
        jac[:, 2 * rows + 1, 2 * ib + 1] = ja.T.real
        jac[:, 2 * rows + 1, 2 * jb + 1] = -jb_.T.real
        r_real = np.empty((n_freq, 2 * n_bl))
        # 残差向量 ρ = [Re(W-pred); Im(W-pred)]（正号——解 J·δ = ρ，
        # 使 pred + Jδ 向 W 逼近；符号取反会使 GN 沿最陡升残方向迭代发散）
        r_real[:, 2 * rows] = r.T.real
        r_real[:, 2 * rows + 1] = r.T.imag
        jt = jac.transpose(0, 2, 1).conj()
        hess = jt @ jac
        rhs = jt @ r_real[..., None]  # (F, 2N, 1)：批量矩阵@向量须显式升维
        delta = (np.linalg.pinv(hess, rcond=_LINCAL_PINV_RCOND) @ rhs)[..., 0]  # (F, 2N)
        d_re = delta[:, 0::2].T  # (N, F)
        d_im = delta[:, 1::2].T
        g = g + d_re + 1j * d_im
        # 重锚参考元全局相位（零空间方向；锚定因子必须投影到单位模长——
        # 全局幅值不是简并量（|c|≠1 会改变预测 |c|²倍），动幅值等于每步
        # 撤销 GN 的幅值修正并复利发散）
        c = ref_anchor / g[ref]
        g = g * (c / np.abs(c))[None, :]
        step_rel = float(np.max(np.abs(d_re + 1j * d_im) / np.abs(g)))
        residual_rms = _resid_rms(g)
        converged = residual_rms <= tol or step_rel < conv_crit

    return {
        "gains": g,
        "n_iter": int(n_iter),
        "converged": bool(converged),
        "residual_rms": residual_rms,
    }


def redundant_group_degeneracy(
    baseline_pairs: Sequence[tuple[int, int]], n_ant: int
) -> dict[str, object]:
    """冗余/已知真值口径的增益简并空间图论分析（无坐标输入）。

    机制出处：hera_cal ``remove_degen_gains``（"1 overall phase and 2
    tip-tilt terms"，按天线位置投影，arXiv:1712.07212）给出**含坐标**的
    简并投影；本函数输入仅基线图（无坐标），做纯图论分析（如实标注，
    tip-tilt 位置斜坡简并未涵盖）：

    * 相位域方程 ``phi_i - phi_j = theta_ij``：零空间 = 每连通分量 1 维
      全局相位（带符号关联矩阵秩 = N - n_components）；
    * 幅值域方程 ``a_i + a_j = ln|W_ij|``：零空间 = 每**二部**连通分量
      1 维棋盘模（两侧 +t/-t）；非二部（含奇圈）分量幅值唯一；
    * 孤立天线 = 单点分量（幅相全自由）。

    Returns
    -------
    dict with keys:
        n_components : int；
        rank_deficiency : int —— 幅值+相位域合计简并维数（锚定所需固定量）；
        amp_rank_deficiency : int；
        phase_rank_deficiency : int；
        degenerate_modes : list[str] —— 简并模描述；
        anchor_suggestion : list[int] —— 建议锚定元（每分量 1 个相位锚，
            二部分量另加 1 个幅值锚）；
        note : str —— 物理语义（绝对指向 UNDETERMINED；坐标类 tip-tilt
            简并需天线坐标输入，未涵盖）。
    """
    if isinstance(n_ant, (bool, np.bool_)):
        raise ValueError("n_ant 是 bool，拒绝")
    if not isinstance(n_ant, (int, np.integer)) or n_ant < 1:
        raise ValueError(f"n_ant 必须是正整数，得到 {n_ant!r}")
    n = int(n_ant)
    pairs = _validate_pairs(baseline_pairs, n_ant=n)[0]

    adj = _adjacency(pairs, n)
    comp_of = [-1] * n
    components: list[list[int]] = []
    for start in range(n):
        if comp_of[start] != -1:
            continue
        comp_id = len(components)
        comp_of[start] = comp_id
        members = [start]
        queue = [start]
        while queue:
            u = queue.pop(0)
            for v in adj[u]:
                if comp_of[v] == -1:
                    comp_of[v] = comp_id
                    members.append(v)
                    queue.append(v)
        components.append(members)

    # 二部判定（2 染色）
    bipartite: list[bool] = []
    for members in components:
        color: dict[int, int] = {members[0]: 0}
        stack = [members[0]]
        is_bip = True
        while stack and is_bip:
            u = stack.pop()
            for v in adj[u]:
                if v not in color:
                    color[v] = 1 - color[u]
                    stack.append(v)
                elif color[v] == color[u]:
                    is_bip = False
                    break
        bipartite.append(is_bip)

    amp_def = sum(1 for b in bipartite if b)
    phase_def = len(components)
    modes: list[str] = []
    anchors: list[int] = []
    for cid, members in enumerate(components):
        rep = min(members)
        anchors.append(rep)
        modes.append(f"分量 {cid}（天线 {members}）全局相位 1 维——锚定 g[{rep}] 相位")
        if bipartite[cid]:
            partner = min(v for v in members if v != rep) if len(members) > 1 else None
            if partner is not None:
                anchors.append(partner)
            modes.append(
                f"分量 {cid} 幅值棋盘模 1 维（二部图两侧 +t/-t）——"
                f"锚定 |g[{rep}]| 后建议另锚 |g[{partner}]|"
                if partner is not None
                else f"分量 {cid} 为孤立天线，幅相全自由——锚定 g[{rep}]"
            )
    return {
        "n_components": len(components),
        "rank_deficiency": amp_def + phase_def,
        "amp_rank_deficiency": amp_def,
        "phase_rank_deficiency": phase_def,
        "degenerate_modes": modes,
        "anchor_suggestion": anchors,
        "note": (
            "已知每基线真值口径的图论简并分析；冗余校准天生丢绝对指向"
            "（全局相位/延迟与源位置简并）——绝对方向 UNDETERMINED。"
            "hera_cal remove_degen_gains 的 tip-tilt 位置斜坡简并需天线"
            "坐标输入，超出本函数签名，未涵盖（如实标注）。"
        ),
    }
