"""Direction 8b: Sensitivity analysis (Sobol/Morris/delta-moment methods).

Sobol: 正确的 Saltelli (2002) 采样 + 经典一阶/Jansen 总阶估计量（审查缺口 #11
修复——旧实现 ST=S1*1.2 是编造系数，总阶指数无统计含义）。numpy 实现，不引入
SALib 依赖。

#234 数值稳定化：一阶估计量 mean(y_A*(y_C-y_B))/V 在 E[f]≫std(f)（如 patch
f0 均值 4.48GHz、公差带内 std~0.5%）时两项大数相减失效（实测未居中
S1 0.0139 vs 真值 0.81）。Sobol 指数对加性常数平移不变，故所有模型输出先减去
常数 shift=mean(y_A∪y_B) 再进估计量——纯数值条件化，不改变敏感度结构。
结果字典附带 centering_shift（观测性字段，消费方可选读取）。

Morris: OAT elementary effects（mu_star/sigma 语义正确）。

Delta 矩独立（XD-13）：Borgonovo (2007) 分布形状敏感指数（binned 经验估计
量）——度量"固定 X_i 后输出分布整体偏移多少"，补 Sobol 只看方差的盲区
（谐振谷深族：方差不变而分布形状剧变的输入零方差指数可见、delta 指数
可见；反之亦然）。估计量统计偏置地板（irrelevant 输入 δ̂>0，~O(k^{-1/2})）
在 docstring 如实声明，门判一律用分离比不用绝对值。

Output: parameter importance ranking for tuning reports.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _to_unit_matrix(param_ranges: dict[str, dict[str, float]]) -> tuple[list[str], np.ndarray, np.ndarray]:
    names = sorted(param_ranges.keys())
    lows = np.array([float(param_ranges[n]["low"]) for n in names])
    highs = np.array([float(param_ranges[n]["high"]) for n in names])
    return names, lows, highs


def _unit_to_params(names: list[str], lows: np.ndarray, highs: np.ndarray, row: np.ndarray) -> dict[str, float]:
    return {n: float(lows[j] + row[j] * (highs[j] - lows[j])) for j, n in enumerate(names)}


def sobol_sensitivity(
    param_ranges: dict[str, dict[str, float]],
    objective_fn,
    n_samples: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    """Variance-based Sobol indices via Saltelli sampling (numpy-only).

    Args:
        param_ranges: {name: {"low": float, "high": float}}
        objective_fn: callable(params_dict) -> float
        n_samples: base sample size N；总模型求值次数 = N * (d + 2)
        seed: random seed for reproducibility

    Returns: {"ok", "sensitivity": {param: {"S1", "ST"}}, "n_samples"(=N), "method",
        "centering_shift"}
        S1 = first-order（Saltelli 经典估计量），ST = total-order（Jansen）。
        centering_shift = 进估计量前从全部模型输出中减去的常数（#234 数值
        稳定化；Sobol 指数对加性常数不变，仅条件化估计量）。
    """
    rng = np.random.default_rng(seed)
    names, lows, highs = _to_unit_matrix(param_ranges)
    d = len(names)
    if d == 0:
        return {"ok": True, "sensitivity": {}, "n_samples": 0, "method": "sobol"}

    n_base = max(int(n_samples), d + 4)  # 保证矩阵形状有效
    a = rng.uniform(0, 1, (n_base, d))   # A 矩阵
    b = rng.uniform(0, 1, (n_base, d))   # B 矩阵

    def run(mat: np.ndarray) -> np.ndarray:
        return np.array([objective_fn(_unit_to_params(names, lows, highs, row)) for row in mat])

    y_a = run(a)
    y_b = run(b)
    # C_i = B 换第 i 列为 A（与 B 只差第 i 列）→ 差分隔离 x_i 的一阶贡献
    # D_i = A 换第 i 列为 B（与 A 只差第 i 列）→ Jansen 总阶用
    y_c: dict[int, np.ndarray] = {}
    y_d: dict[int, np.ndarray] = {}
    for i in range(d):
        c = b.copy()
        c[:, i] = a[:, i]
        y_c[i] = run(c)
        dd = a.copy()
        dd[:, i] = b[:, i]
        y_d[i] = run(dd)

    # #234：先对全部模型输出做常数居中再进估计量。E[f]≫std(f) 时未居中的
    # 一阶估计量是 E[y_A·y_C]−E[y_A·y_B] 两个 ≈E[f]² 的大数相减，浮点抵消
    # 吞掉一阶信号；居中后乘积项量级落到 std²。总阶 (y_A−y_D)² 本身平移
    # 不变，统一居中只为同一条数据通路。
    shift = float(np.mean(np.concatenate([y_a, y_b])))
    yc_a = y_a - shift
    yc_b = y_b - shift
    yc_c = {i: arr - shift for i, arr in y_c.items()}
    yc_d = {i: arr - shift for i, arr in y_d.items()}

    var_y = float(np.var(np.concatenate([yc_a, yc_b]), ddof=1))
    if var_y < 1e-15:
        return {"ok": True, "sensitivity": {n: {"S1": 0.0, "ST": 0.0} for n in names},
                "n_samples": n_base, "method": "sobol", "centering_shift": shift}

    sensitivity: dict[str, dict[str, float]] = {}
    for i, name in enumerate(names):
        # Saltelli 一阶：S1_i = (1/N) Σ y_A * (y_Ci - y_B) / V
        #   （C_i 与 B 只差第 i 列 → 差分隔离 x_i；乘 y_A 消去交叉期望取方差项）
        #   #234：y 全部已居中，避免 E[f]≫std(f) 大数相减
        s1 = float(np.mean(yc_a * (yc_c[i] - yc_b)) / var_y)
        # Jansen 总阶：ST_i = (1/(2N)) Σ (y_A - y_Di)^2 / V   （D_i 与 A 只差第 i 列）
        st = float(np.mean((yc_a - yc_d[i]) ** 2) / (2.0 * var_y))
        sensitivity[name] = {"S1": max(s1, 0.0), "ST": max(st, 0.0)}

    # 观测性诊断（best-effort，#105：只记录不阻塞）：|E[f]|/std 大说明目标
    # 天然带大偏置，居中正是为该工况设计（#234 patch f0 实测 ratio≈224）。
    std_y = math.sqrt(var_y)
    if std_y > 0.0 and abs(shift) / std_y > 100.0:
        logger.info(
            "sobol_sensitivity: 目标 |E[f]|/std=%.3g 较大，已常数居中 "
            "(shift=%.6g) 进估计量（#234 数值稳定化，指数不受平移影响）",
            abs(shift) / std_y, shift,
        )

    return {"ok": True, "sensitivity": sensitivity, "n_samples": n_base,
            "method": "sobol", "centering_shift": shift}


def morris_screening(
    param_ranges: dict[str, dict[str, float]],
    objective_fn,
    n_trajectories: int = 10,
    seed: int = 42,
) -> dict[str, Any]:
    """Morris elementary effects screening (for high-dimensional problems).

    边界处理（D1-3 修复 2026-10-04，内部证据档
    REPORT.md）：x+delta 越上界时**反射**取 x−delta（Morris 1991 原始
    OAT 轨道惯例，步长仍=delta）——旧径 min(1.0, x+delta) 把上界附近
    的实际步长截半（起点 x>1−delta 时步长=1−x<delta），效应被 |Δx|
    除以名义 delta 放大/压缩失衡：线性 f=x1 全域均匀设计下 mu_star
    实测偏置 ~0.75 倍（D1 席解析），反射后≈1.0。

    Returns: {param_name: {"mu_star": float, "sigma": float}}
    """
    rng = np.random.default_rng(seed)
    names, lows, highs = _to_unit_matrix(param_ranges)
    n_params = len(names)
    if n_params == 0:
        return {"ok": True, "sensitivity": {}, "n_samples": 0, "method": "morris"}

    delta = 1.0 / (n_params + 1)  # normalized step size

    all_effects: dict[str, list[float]] = {n: [] for n in names}

    for _ in range(n_trajectories):
        # Random starting point
        x = rng.uniform(0, 1, n_params)
        y_prev = objective_fn(_unit_to_params(names, lows, highs, x))

        # One-at-a-time perturbations
        order = rng.permutation(n_params)
        for j in order:
            x_new = x.copy()
            # D1-3：越上界反射（x−delta），保持名义步长=delta（Morris OAT
            # 轨道惯例）——min(1.0,·) 截断使上界附近步长<delta，mu_star
            # 系统性偏置 ~0.75（线性 f 全域实测）
            x_new[j] = (x[j] + delta) if x[j] + delta <= 1.0 else (x[j] - delta)
            y_new = objective_fn(_unit_to_params(names, lows, highs, x_new))
            effect = (y_new - y_prev) / delta
            all_effects[names[j]].append(effect)
            x = x_new
            y_prev = y_new

    sensitivity = {}
    for name in names:
        effects = all_effects[name]
        if effects:
            mu_star = float(np.mean(np.abs(effects)))
            sigma = float(np.std(effects))
        else:
            mu_star, sigma = 0.0, 0.0
        sensitivity[name] = {"mu_star": mu_star, "sigma": sigma}

    return {"ok": True, "sensitivity": sensitivity,
            "n_samples": n_trajectories * n_params, "method": "morris"}


def delta_moment_sensitivity(
    param_ranges: dict[str, dict[str, float]],
    objective_fn,
    n_samples: int = 400,
    k_neighbors: int = 40,
    n_bins: int = 20,
    seed: int = 42,
) -> dict[str, Any]:
    """Borgonovo delta 矩独立指数（XD-13，numpy-only binned 经验估计量）。

    定义（Borgonovo 2007, RESS 92:771-784，"A new uncertainty importance
    measure"）：δ_i = (1/2)·E_{X_i}[∫|f_Y(y) − f_{Y|X_i}(y)|dy]——固定
    X_i 后输出分布与无条件分布的 L1 偏移期望；δ∈[0,1]，与输出均值/方差
    平移缩放无关（只看分布形状）。补 Sobol 只看方差的盲区：谐振谷深族
    "固定该参数让谷消失（分布形状剧变）但方差几乎不变"的输入，S1/ST 近
    零而 δ 可观。

    估计量（纯经验，无密度核）：y 等宽 n_bins 分箱得无条件质量向量
    p̂；对第 i 维把样本按 x_i 排序，k 近邻窗=排序序贯滑窗（1D kNN 恰为
    排序邻域），每窗得条件质量向量 p̂^(j)；原始统计量 δ̂ᵒˡᵈ_i = (1/2)·
    mean_j Σ_b |p̂_b − p̂_b^(j)|。**置换对照校正**：k 窗经验分布 vs 全样
    本经验分布的 L1 含正的采样噪声地板（E ≈ Σ_b √(2p_b(1−p_b)/(πk))，
    本机 f=x1 B=20/k=40 实测 0.54），直接报告会把无关输入抬高 ~0.27——
    故对每维另取 y 的随机置换（同窗结构同机器）得噪声对照 D̄_perm，
    报告 δ̂_i = max(0.5·(mean_j D_cond,j − D̄_perm), 0)（配对控制变量，
    独立情形期望归零；置换流共用 seed 确定性）。

    诚实边界（#122）：有限样本下完全确定性依赖 δ̂<1（条件分布坍缩不
    彻底 + 校正残差）；校正只消一阶噪声地板，clipping 在独立侧仍留
    微小正偏。门判一律用**分离比/排序**（强相关输入 δ̂ vs 无关输入
    δ̂），不赌绝对值；k 与 n 的生效值写入返回值供复核。

    Args:
        param_ranges: {name: {"low": float, "high": float}}（与
            sobol_sensitivity 同约定；采样在 [0,1] 平面后线性映射）
        objective_fn: callable(params_dict) -> float
        n_samples: 蒙特卡洛样本量 N（总求值次数 = N）
        k_neighbors: 条件窗宽 k（1D kNN）；生效值 = clip 到
            [4, max(4, N//5)]（过小噪声爆炸、过大偏置向 0 退化）
        n_bins: 输出等宽分箱数（>=2）
        seed: 随机种子（确定性）

    Returns: {"ok", "sensitivity": {param: {"delta"}}, "n_samples", "k",
        "n_bins", "method": "delta_moment"}；退化目标（零方差）→ 全零
        delta 如实返回（与 sobol 同口径，不猜不编）。
    """
    rng = np.random.default_rng(seed)
    names, lows, highs = _to_unit_matrix(param_ranges)
    d = len(names)
    if d == 0:
        return {"ok": True, "sensitivity": {}, "n_samples": 0, "k": 0,
                "n_bins": int(n_bins), "method": "delta_moment"}

    n = max(int(n_samples), d + 4)
    k_eff = int(min(max(int(k_neighbors), 4), max(4, n // 5)))
    bins = max(int(n_bins), 2)

    unit = rng.uniform(0.0, 1.0, (n, d))
    y = np.array([
        objective_fn(_unit_to_params(names, lows, highs, row)) for row in unit
    ])
    if not bool(np.all(np.isfinite(y))):
        raise ValueError("objective_fn 产生了非有限输出（NaN/Inf）")

    span = float(np.max(y) - np.min(y))
    if span < 1e-15 or float(np.var(y)) < 1e-15:
        return {"ok": True,
                "sensitivity": {name: {"delta": 0.0} for name in names},
                "n_samples": n, "k": k_eff, "n_bins": bins,
                "method": "delta_moment"}

    # 输出分箱（等宽覆盖 [min, max]，右端点并入末箱）；无条件质量向量。
    edges = np.linspace(0.0, 1.0, bins + 1)
    y_idx = np.clip(np.searchsorted(edges, (y - float(np.min(y))) / span,
                                    side="right") - 1, 0, bins - 1)
    p_uncond = np.bincount(y_idx, minlength=bins) / float(n)

    def _window_l1_mean(seq: np.ndarray) -> float:
        """同窗结构 L1 均值（各窗 k 样本经验分布 vs 无条件分布的 Σ|Δ|）."""
        windows = np.lib.stride_tricks.sliding_window_view(seq, k_eff)
        m = windows.shape[0]
        counts = np.zeros((m, bins), dtype=np.int64)
        rows = np.repeat(np.arange(m), k_eff)
        np.add.at(counts, (rows, windows.reshape(-1)), 1)
        p_cond = counts / float(k_eff)
        return float(np.mean(np.abs(p_cond - p_uncond[None, :]).sum(axis=1)))

    sensitivity: dict[str, dict[str, float]] = {}
    for i, name in enumerate(names):
        order = np.argsort(unit[:, i], kind="stable")
        # 条件统计量：按 x_i 排序后的 y 序列滑窗（1D kNN）。
        d_cond = _window_l1_mean(y_idx[order])
        # 置换对照：y 随机重排后走完全相同的窗机器——独立情形期望=噪声
        # 地板（配对差归零）；同 seed 确定性。
        perm = rng.permutation(n)
        d_perm = _window_l1_mean(y_idx[perm])
        delta_i = 0.5 * (d_cond - d_perm)
        sensitivity[name] = {"delta": max(delta_i, 0.0)}

    return {"ok": True, "sensitivity": sensitivity, "n_samples": n,
            "k": k_eff, "n_bins": bins, "method": "delta_moment"}
