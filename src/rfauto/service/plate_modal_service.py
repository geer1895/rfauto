"""MP-B5：Elmer 特征值模态对照面——简支 Kirchhoff 板闭式主核（round15:101）。

提案口径：简支板一阶模闭式对拍 ≤5%。本模块=闭式主核+独立第二基准+
Elmer 结果对照接口；**真跑 Elmer 非本席门**（round15 MP-B4/M 席位分界），
``compare_elmer_modes`` 只消费特征频率序列，测试一律 mock。

闭式（Navier 精确解；2026-10-03 web 多源核对——Tom Irvine "Natural
Frequencies of Rectangular Plate Bending Modes" vibrationdata.com/plate.pdf、
Leissa "Vibration of Plates" NASA SP-160 (1969)、Guguloth et al. 2019，
非凭记忆复写）::

    D    = E·h³ / (12·(1−ν²))              弯曲刚度
    ω_mn = π²·√(D/(ρh))·((m/a)² + (n/b)²)  圆频率，m,n = 1,2,...
    f_mn = ω_mn/(2π) = (π/2)·√(D/(ρh))·((m/a)² + (n/b)²)
    模态  w = sin(mπx/a)·sin(nπy/b)        精确满足四边简支 BC

独立第二基准（#118/#300 双基准纪律）：Rayleigh 商——对同一模态形状
做应变能/动能的 2D 数值积分（midpoint 求积，独立积分内核，不走闭式
代数推导）::

    U = (D/2)·∫∫[(∂²w/∂x²+∂²w/∂y²)² − 2(1−ν)((∂²w/∂x²)(∂²w/∂y²) − (∂²w/∂x∂y)²)]dA
    T_max = (ρh·ω²/2)·∫∫w² dA
    ω² = U_max 形系数 / 动能形系数（Rayleigh 商）

对 sin·sin 模态高斯曲率项积分恒为零（解析可验），数值积分独立复证
闭式——两径一致（≤1e-4 相对）即公式与实现双确认。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

__all__ = [
    "compare_elmer_modes",
    "plate_flexural_rigidity",
    "rayleigh_quotient_frequency",
    "simply_supported_mode_frequency",
]

_TOL_GATE_DEFAULT = 0.05  # round15:101 口径：闭式对拍 ≤5%


def plate_flexural_rigidity(E: float, nu: float, h: float) -> float:
    """弯曲刚度 D = E·h³/(12·(1−ν²))（各向同性 Kirchhoff 薄板，模块 docstring 出处）。"""
    E, nu, h = float(E), float(nu), float(h)
    if E <= 0 or h <= 0:
        raise ValueError(f"E/h 必须为正: E={E}, h={h}")
    if not (0.0 < nu < 0.5):
        raise ValueError(f"nu 须在 (0, 0.5): nu={nu}")
    return E * h**3 / (12.0 * (1.0 - nu * nu))


def simply_supported_mode_frequency(
    a: float, b: float, h: float, E: float, nu: float, rho: float,
    m: int = 1, n: int = 1,
) -> dict[str, Any]:
    """简支板 (m,n) 模态闭式频率（Navier 精确解，见模块 docstring 出处）。

    返回 ``{f_hz, omega_rad_s, D, mode, mode_shape}``；f_hz 为主消费口径。
    """
    a, b, h, rho = float(a), float(b), float(h), float(rho)
    m, n = int(m), int(n)
    if a <= 0 or b <= 0 or rho <= 0:
        raise ValueError(f"a/b/rho 必须为正: a={a}, b={b}, rho={rho}")
    if m < 1 or n < 1:
        raise ValueError(f"模态阶次须 ≥1: m={m}, n={n}")
    D = plate_flexural_rigidity(E, nu, h)
    omega = math.pi**2 * math.sqrt(D / (rho * h)) * (
        (m / a) ** 2 + (n / b) ** 2)
    return {
        "f_hz": omega / (2.0 * math.pi),
        "omega_rad_s": omega,
        "D": D,
        "mode": (m, n),
        "mode_shape": "sin(m*pi*x/a)*sin(n*pi*y/b)",
    }


def rayleigh_quotient_frequency(
    a: float, b: float, h: float, E: float, nu: float, rho: float,
    m: int = 1, n: int = 1, n_grid: int = 201,
) -> dict[str, float | tuple[int, int]]:
    """Rayleigh 商独立基准：模态形状能量的 2D Simpson 数值积分。

    独立内核 = 应变能/动能面积分（scipy.integrate.simpson 复合辛普森，
    非闭式代数搬运）；与闭式一致性由 ``rel_dev_vs_closed`` 暴露。求积
    选 Simpson 而非 midpoint：高阶模被积函数含 cos² 高频项，midpoint
    O(h²) 在 n_grid≈200 时残差 ~1e-3（(3,2) 模实测），Simpson O(h⁴)
    同网格 ≤1e-9。复合 Simpson 需偶数区间——偶数节点入参自动 +1。
    """
    a, b = float(a), float(b)
    m, n = int(m), int(n)
    if n_grid < 5:
        raise ValueError(f"n_grid 至少 5: {n_grid}")
    if n_grid % 2 == 0:
        n_grid += 1
    D = plate_flexural_rigidity(E, nu, h)
    alpha = m * math.pi / a
    beta = n * math.pi / b

    from scipy.integrate import simpson

    xs = np.linspace(0.0, a, n_grid)
    ys = np.linspace(0.0, b, n_grid)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    w = np.sin(alpha * X) * np.sin(beta * Y)
    w_xx = -(alpha**2) * w
    w_yy = -(beta**2) * w
    w_xy = alpha * beta * np.cos(alpha * X) * np.cos(beta * Y)

    # Kirchhoff 应变能密度（模块 docstring 公式；含 ν 高斯曲率项）
    dens = (w_xx + w_yy) ** 2 - 2.0 * (1.0 - nu) * (w_xx * w_yy - w_xy**2)
    U = 0.5 * D * float(simpson(simpson(dens, x=xs), x=ys))
    w2 = float(simpson(simpson(w * w, x=xs), x=ys))  # ∫∫w²dA
    omega_sq = (2.0 * U) / (rho * h * w2)
    f_num = math.sqrt(max(omega_sq, 0.0)) / (2.0 * math.pi)
    closed = simply_supported_mode_frequency(a, b, h, E, nu, rho, m, n)
    f_ref = float(closed["f_hz"])
    return {
        "f_hz": f_num,
        "rel_dev_vs_closed": abs(f_num - f_ref) / f_ref,
        "U": U,
        "mode": (m, n),
    }


def compare_elmer_modes(
    frequencies_hz: Sequence[float] | None,
    a: float, b: float, h: float, E: float, nu: float, rho: float,
    *,
    expected_modes: Sequence[tuple[int, int]] = ((1, 1),),
    tol: float = _TOL_GATE_DEFAULT,
) -> dict[str, Any]:
    """Elmer 特征频率 vs 闭式对拍门（round15:101：≤5% 判 AGREE）。

    对每个期望模态 (m,n) 取 Elmer 序列中**最近邻频率**配对（Elmer 求出
    的谱可含额外模态/重复根，最近邻配对不要求顺序一致）；配对偏差 ≤tol
    记 PASS，否则 FAIL。空/None 频率序列 → ok=False UNVERIFIED（拒绝
    空跑，不伪造判读，#122）。真跑 Elmer 非本席门——本函数只消费结果。
    """
    freqs = None if frequencies_hz is None else [float(f) for f in frequencies_hz]
    if not freqs:
        return {"ok": False, "gate": "UNVERIFIED", "n_elmer": 0,
                "tol": float(tol), "results": [],
                "reasons": ["Elmer 特征频率为空：UNVERIFIED（拒绝空跑判读）"]}
    results = []
    n_pass = 0
    for mn in expected_modes:
        m, n = int(mn[0]), int(mn[1])
        ref = simply_supported_mode_frequency(a, b, h, E, nu, rho, m, n)
        f_ref = float(ref["f_hz"])
        f_elmer = min(freqs, key=lambda f: abs(f - f_ref))
        rel_dev = abs(f_elmer - f_ref) / f_ref
        passed = rel_dev <= float(tol)
        n_pass += int(passed)
        results.append({
            "mode": (m, n), "f_closed_hz": f_ref, "f_elmer_hz": f_elmer,
            "rel_dev": rel_dev, "verdict": "PASS" if passed else "FAIL",
        })
    ok = n_pass == len(results)
    return {
        "ok": ok,
        "gate": "AGREE" if ok else "DISAGREE",
        "n_elmer": len(freqs),
        "tol": float(tol),
        "results": results,
        "reasons": ["全部期望模态 ≤tol"] if ok else [
            f"{r['mode']}: rel_dev={r['rel_dev']:.4g} > tol={float(tol):.4g}"
            for r in results if r["verdict"] == "FAIL"],
    }
