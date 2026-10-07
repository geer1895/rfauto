"""OP-9（round16 §六）：鲁棒设计优化（RDO）——min μ+λσ 族 + 机会约束闭式。

规格原文："min μ+λσ 族 + PCE 分位数 Φ⁻¹ 闭式"。职责边界（铁律 7：
数值只在确定性内核）——μ/σ 来自注入的代理/估计器（surrogate.
predict_with_std 的 (mean, std) 面、sparse_pce 的均值/标准差），本模块
只做**确定性的组合与判定数学**：

- :func:`robust_objective`：μ(x) + λ·σ(x)（λ≥0 权衡稳健性；λ=0 退化为
  纯均值优化，λ→∞ 退化为纯极小化方差）；
- :func:`gaussian_quantile`：标准正态分位数 Φ⁻¹(p)（stdlib
  statistics.NormalDist.inv_cdf，零新依赖）；
- :func:`chance_constraint_bound`：机会约束闭式——高斯假设下
  P[g(x) ≤ 0] ≥ 1−α ⇔ μ_g(x) + Φ⁻¹(1−α)·σ_g(x) ≤ 0（Balis/满概率
  等价式；α=违约概率上界）。高斯假设是**声明的近似**：PCE 一阶矩/
  二阶矩非高斯时该式不严格，docstring 如实标注，判读人可对照
  sparse_pce 的多项式分位数通道复核；
- :func:`robust_design_optimization`：SLSQP 求解 min μ+λσ s.t.
  机会约束 g_α(x) ≤ 0（约束以闭式界作不等式通道；无约束时 L-BFGS-B
  硬盒）。确定性（零随机；梯度=scipy 有限差分）。

来源：机会约束规划 Charnes & Cooper (1959)；高斯闭式见任意随机规划
教材（如 Birge & Louveaux §1.2）；"min μ+λσ" 族=Markowitz (1952) 均值-
方差范式的工程化。合成裁判（tests/unit/test_rdo.py）：已知 μ(x)/σ(x)
解析形态上验证闭式界与 SLSQP 解的 KKT 一致性（#207/#118：独立来源
解析值，不用推导自证）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from statistics import NormalDist
from typing import Any

import numpy as np


def gaussian_quantile(p: float) -> float:
    """标准正态分位数 Φ⁻¹(p)，p ∈ (0,1) 开区间（0/1 处无穷，显式拒绝）。"""
    if isinstance(p, bool) or not 0.0 < float(p) < 1.0:
        raise ValueError(f"分位数概率 p 必须落在开区间 (0,1)，实得 {p!r}")
    return float(NormalDist().inv_cdf(float(p)))


def robust_objective(
    mean: float, std: float, lam: float,
) -> float:
    """μ + λ·σ（λ≥0；μ/σ 须有限，σ 须非负）。"""
    for name, val in (("mean", mean), ("std", std), ("lam", lam)):
        if isinstance(val, bool) or not math.isfinite(float(val)):
            raise ValueError(f"{name} 必须为有限数，实得 {val!r}")
    if float(std) < 0.0:
        raise ValueError(f"std 必须 ≥0，实得 {std}")
    if float(lam) < 0.0:
        raise ValueError(f"λ 必须 ≥0（负 λ 偏好方差无意义），实得 {lam}")
    return float(mean) + float(lam) * float(std)


def chance_constraint_bound(
    mean: float, std: float, alpha: float,
) -> float:
    """机会约束闭式界 g_α = μ + Φ⁻¹(1−α)·σ（高斯假设，见模块 docstring）。

    g_α ≤ 0 ⇔ P[g ≤ 0] ≥ 1−α。α ∈ (0,1) 为违约概率上界；σ≥0。
    注意 Φ⁻¹(1−α) 在 α<0.5 时为正（界上抬、约束收紧）、α>0.5 时为负
    （约束放宽）——语义如式，不隐含单调截断。
    """
    for name, val in (("mean", mean), ("std", std)):
        if isinstance(val, bool) or not math.isfinite(float(val)):
            raise ValueError(f"{name} 必须为有限数，实得 {val!r}")
    if float(std) < 0.0:
        raise ValueError(f"std 必须 ≥0，实得 {std}")
    z = gaussian_quantile(1.0 - float(alpha))
    return float(mean) + z * float(std)


def robust_design_optimization(
    *,
    mean_fn: Callable[[np.ndarray], float],
    std_fn: Callable[[np.ndarray], float] | None,
    bounds: Mapping[str, tuple[float, float]],
    lam: float,
    chance_constraints: list[dict[str, Any]] | None = None,
    x0: Mapping[str, float] | None = None,
    maxiter: int = 200,
) -> dict[str, Any]:
    """SLSQP 求解 min μ(x)+λσ(x)，可选机会约束 g_α(x) ≤ 0。

    Args:
        mean_fn / std_fn: x 向量 → μ / σ（std_fn=None 视 σ≡0）。
        bounds: {参数名: (lo, hi)}（列序=sorted(bounds)）。
        lam: 稳健权重 ≥0。
        chance_constraints: 可选列表，逐项 {"mean_fn", "std_fn", "alpha"}
            （std_fn 可省，视 σ≡0）；闭式界 >0 即违约进入 SLSQP 不等式。
        x0: 可选起点；缺省取盒心（确定性）。起点越界自动截断入盒。
        maxiter: SLSQP 最大迭代。

    Returns:
        {"x": {参数: 值}, "mean", "std", "objective", "constraint_margins":
        [逐约束闭式界], "success", "message", "niter"}

    Raises:
        ValueError: 边界/λ/α 非法或键集不一致。
    """
    from scipy.optimize import Bounds, minimize

    names = sorted(bounds)
    if not names:
        raise ValueError("bounds 不得为空")
    lo = np.array([float(bounds[n][0]) for n in names])
    hi = np.array([float(bounds[n][1]) for n in names])
    if np.any(hi <= lo):
        raise ValueError("bounds 须逐维 hi > lo")
    if float(lam) < 0.0:
        raise ValueError(f"λ 必须 ≥0，实得 {lam}")

    cons_spec = list(chance_constraints or [])
    alphas: list[float] = []
    for c in cons_spec:
        a = float(c["alpha"])
        if not 0.0 < a < 1.0:
            raise ValueError(f"机会约束 alpha 必须在 (0,1)，实得 {a}")
        alphas.append(a)

    def _vec_mean(x: np.ndarray) -> float:
        return float(mean_fn(x))

    def _vec_std(x: np.ndarray) -> float:
        return 0.0 if std_fn is None else float(std_fn(x))

    def _obj(x: np.ndarray) -> float:
        return robust_objective(_vec_mean(x), _vec_std(x), lam)

    constraints: list[dict[str, Any]] = []
    for c in cons_spec:
        cm = c["mean_fn"]
        cs = c.get("std_fn")
        a = float(c["alpha"])

        def _con(x: np.ndarray, cm=cm, cs=cs, a=a) -> float:
            cv = float(cm(x))
            sv = 0.0 if cs is None else float(cs(x))
            return -chance_constraint_bound(cv, sv, a)  # SLSQP: ≥0 即可行

        constraints.append({"type": "ineq", "fun": _con})

    if x0 is None:
        x_start = 0.5 * (lo + hi)
    else:
        if set(x0) != set(names):
            raise ValueError(
                f"x0 键集 {sorted(x0)} 与 bounds 键集 {names} 不一致")
        x_start = np.clip(
            np.array([float(x0[n]) for n in names]), lo, hi)

    res = minimize(
        _obj, x_start, method="SLSQP",
        bounds=Bounds(lo, hi), constraints=constraints,
        options={"maxiter": int(maxiter), "ftol": 1e-12},
    )
    x_out = np.clip(np.asarray(res.x, dtype=float), lo, hi)
    margins = [
        chance_constraint_bound(
            float(c["mean_fn"](x_out)),
            0.0 if c.get("std_fn") is None else float(c["std_fn"](x_out)),
            float(c["alpha"]))
        for c in cons_spec
    ]
    return {
        "x": {n: float(v) for n, v in zip(names, x_out, strict=True)},
        "mean": _vec_mean(x_out),
        "std": _vec_std(x_out),
        "objective": _obj(x_out),
        "constraint_margins": margins,
        "success": bool(res.success),
        "message": str(res.message),
        "niter": int(getattr(res, "nit", 0)),
    }
