"""Direction 8b: Sensitivity analysis (Sobol/Morris methods).

Sobol: 正确的 Saltelli (2002) 采样 + 经典一阶/Jansen 总阶估计量（历史审查补强
修复——旧实现 ST=S1*1.2 是编造系数，总阶指数无统计含义）。numpy 实现，不引入
SALib 依赖。

#234 数值稳定化：一阶估计量 mean(y_A*(y_C-y_B))/V 在 E[f]≫std(f)（如 patch
f0 均值 4.48GHz、公差带内 std~0.5%）时两项大数相减失效（实测未居中
S1 0.0139 vs 真值 0.81）。Sobol 指数对加性常数平移不变，故所有模型输出先减去
常数 shift=mean(y_A∪y_B) 再进估计量——纯数值条件化，不改变敏感度结构。
结果字典附带 centering_shift（观测性字段，消费方可选读取）。

Morris: OAT elementary effects（mu_star/sigma 语义正确）。

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
            x_new[j] = min(1.0, x[j] + delta)
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
