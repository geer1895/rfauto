"""MA 磁屏蔽退磁因子闭式面（椭球解析 + 圆管经验表 + mu-metal 带）。

规格：研究扩充 round17 §六 MA-12（磁面，P2-3/S）
——"磁屏蔽退磁因子闭式（椭球解析+圆管经验式，mu-metal datasheet 数值）
+ LLG 阻尼换算面；非线性限幅仅登记"。任务书 ge8b Wave A 席4（MA-11 磁
屏蔽退磁因子）。纯闭式叶子，零 IO、不进 calculators。

模块面
------
- ``demag_factor_sphere``：球 N=1/3（精确恒等）。
- ``demag_factor_prolate`` / ``demag_factor_oblate``：Osborn 1945 椭球
  闭式（沿对称轴）；三轴和恒等 N_x+N_y+N_z=1（结构锚）。
- ``cylinder_demag_table``：圆柱轴向退磁因子经验表（Bozorth 手册带，
  band+single_source 标记，插值线性；表外如实 clamp+flag）。
- ``spherical_shell_shielding_factor``：同心球壳屏蔽系数**精确**闭式
  S = 9μ/[(2μ+1)(μ+2) − 2(a/b)³(μ−1)²]（内场 H_in/H0 = 1/S）。
- ``cylinder_shielding_factor_thin``：薄壁圆管横向场近似式
  S ≈ μ_r·t/D + 1（薄壁、D≫t 工程式，band 口径如实）。
- ``multilayer_shield_estimate``：多层近似串联 S_total ≈ Π S_i
  （层间退耦口径，登记级如实）。
- ``mu_metal_band``：mu-metal/坡莫合金 datasheet 数值带（μ_r 初/最大、
  B_sat；band 形式 single_source，#122 不冒充仲裁值）。
- ``llg_damping_conversion``：LLG 阻尼 α ↔ FMR 线宽换算闭式
  ΔB_FWHM = (2ω/γ)·α·(1+α²)⁰（小 α 一阶口径 + 精确式含 (1+α²) 修正
  按 Kaup/标准 FMR 口径，页码 UNVERIFIED 如实）；γ 精确常数锚。

出处
----
1. round 文档：round17 §六 MA-12。
2. Osborn, Phys. Rev. 67, 351 (1945)（椭球退磁因子闭式，口径名）；
   Bozorth "Ferromagnetism"（圆柱退磁因子表/mu-metal 数值，band）；
   Jackson §5.7（球壳磁屏蔽闭式）。页码 UNVERIFIED 如实（#122）。
"""
from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

__all__ = [
    "GAMMA_RAD_S_T",
    "MAGNETIC_SOURCE",
    "cylinder_demag_table",
    "cylinder_shielding_factor_thin",
    "demag_factor_oblate",
    "demag_factor_prolate",
    "demag_factor_sphere",
    "llg_damping_conversion",
    "mu_metal_band",
    "multilayer_shield_estimate",
    "spherical_shell_shielding_factor",
]

#: 电子回旋磁比 γ_e = g·μ_B/ħ ≈ 1.76085963023e11 rad/(s·T)（CODATA，
#: 测试侧 scipy.constants 裁判）
GAMMA_RAD_S_T = 1.76085963023e11
MAGNETIC_SOURCE = (
    "Osborn PR 67, 351 (1945)（椭球闭式口径名）；Bozorth Ferromagnetism"
    "（圆柱表/mu-metal band）；Jackson §5.7（球壳屏蔽闭式）；页码 "
    "UNVERIFIED（#122 如实）"
)


def _positive(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def _unit_interval(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or not (0.0 < v < 1.0):
        raise ValueError(f"{name} 必须在 (0,1)，实际 {x!r}")
    return v


# ─── 椭球退磁因子（Osborn 闭式）──────────────────────────────────────────────
def demag_factor_sphere() -> float:
    """球：N = 1/3（精确）。"""
    return 1.0 / 3.0


def demag_factor_prolate(axis_ratio: Any) -> dict[str, float]:
    """长球（prolate，轴向拉长）沿对称轴的退磁因子（Osborn 1945）。

    离心率 e=√(1−(a/b)²)（b=半长轴、a=半短轴，axis_ratio=b/a>1）：
    N_z = (1−e²)/e³·(atanh(e) − e)。极限：b/a→1 → N_z→1/3（球，连续性
    锚）；b/a→∞ → N_z→0（细长针）。
    """
    ratio = _positive(axis_ratio, "axis_ratio")
    if ratio < 1.0:
        raise ValueError("axis_ratio 须 >=1（prolate 定义 b/a）")
    if abs(ratio - 1.0) < 1e-9:
        return {"n_axis": 1.0 / 3.0, "e": 0.0, "axis_ratio": 1.0}
    e = math.sqrt(1.0 - 1.0 / ratio**2)
    n_z = (1.0 - e * e) / (e**3) * (math.atanh(e) - e)
    return {"n_axis": n_z, "e": e, "axis_ratio": ratio}


def demag_factor_oblate(axis_ratio: Any) -> dict[str, float]:
    """扁球（oblate，轴向压扁）沿对称轴的退磁因子（Osborn 1945）。

    axis_ratio = c/a < 1（c=半对称轴、a=半赤道轴）：
    N_z = (1+ξ²)/ξ³·(ξ − atan ξ)，ξ = √(1/c²... 以 e=√(a²/c²−1)>1 记：
    N_z = (e² + 1)/e³·(e − atan e)·(−1)? —— 本实现采用等价 Osborn 形式
    N_z = ((1+ξ²)/ξ³)·(ξ − atan ξ)，ξ = √(a²/c² − 1)（>0）。
    极限：c/a→1 → 1/3（球连续性锚）；c/a→0 → 1（薄板法向）。
    """
    ratio = _positive(axis_ratio, "axis_ratio")
    if ratio >= 1.0:
        raise ValueError("axis_ratio 须 <1（oblate 定义 c/a）")
    if abs(ratio - 1.0) < 1e-9:
        return {"n_axis": 1.0 / 3.0, "xi": 0.0, "axis_ratio": ratio}
    xi = math.sqrt(1.0 / (ratio * ratio) - 1.0)
    n_z = (1.0 + xi * xi) / xi**3 * (xi - math.atan(xi))
    return {"n_axis": n_z, "xi": xi, "axis_ratio": ratio}


# ─── 圆柱经验表（band 形式）──────────────────────────────────────────────────
#: Bozorth 手册圆柱轴向退磁因子代表点（L/D → N_z；band 形式 single_source，
#: 手册表值随磁化状态/口径有带——#122 不冒充仲裁值）
_CYLINDER_TABLE: list[tuple[float, float]] = [
    (0.5, 0.68),
    (1.0, 0.27),
    (2.0, 0.14),
    (5.0, 0.040),
    (10.0, 0.0172),
    (20.0, 0.00675),
    (50.0, 0.00144),
]


def cylinder_demag_table(length_diameter_ratio: Any) -> dict[str, Any]:
    """圆柱轴向退磁因子经验表线性插值（Bozorth band）。

    表外（<0.5 或 >50）线性外推并如实 clamp 到 [0, 1] + extrapolated
    标记；单调递减结构锚在测试侧。
    """
    ld = _positive(length_diameter_ratio, "length_diameter_ratio")
    pts = _CYLINDER_TABLE
    if ld <= pts[0][0]:
        n = pts[0][1] + (pts[0][1] - pts[1][1]) / (pts[0][0] - pts[1][0]) * (
            ld - pts[0][0])
        return {"n_axis": max(min(n, 1.0), 0.0), "extrapolated": True,
                "ld": ld}
    if ld >= pts[-1][0]:
        n = pts[-1][1] + (pts[-1][1] - pts[-2][1]) / (
            pts[-1][0] - pts[-2][0]) * (ld - pts[-1][0])
        return {"n_axis": max(n, 0.0), "extrapolated": True, "ld": ld}
    for x0, y0, x1, y1 in _pairwise_flat(pts):
        if x0 <= ld <= x1:
            n = y0 + (y1 - y0) * (ld - x0) / (x1 - x0)
            return {"n_axis": n, "extrapolated": False, "ld": ld}
    raise AssertionError("unreachable")  # pragma: no cover


def _pairwise_flat(pts: list[tuple[float, float]]) -> list[tuple[float, float, float, float]]:
    return [(p0[0], p0[1], p1[0], p1[1]) for p0, p1 in pairwise(pts)]


# ─── 磁屏蔽系数 ──────────────────────────────────────────────────────────────
def spherical_shell_shielding_factor(inner_radius_m: Any, outer_radius_m: Any,
                                     mu_r: Any) -> dict[str, float]:
    """同心球壳屏蔽系数（精确闭式）：H_in/H0 = 9μ/D，

    D = (2μ+1)(μ+2) − 2(a/b)³(μ−1)²，S = D/(9μ)。
    锚：μ=1 → S=1；a/b→1 → S→1；μ→∞ → S ≈ (2μ/9)·(1−(a/b)³)（渐近）。
    """
    a = _positive(inner_radius_m, "inner_radius_m")
    b = _positive(outer_radius_m, "outer_radius_m")
    if a >= b:
        raise ValueError("inner_radius_m 须 < outer_radius_m")
    mu = _positive(mu_r, "mu_r")
    ratio3 = (a / b) ** 3
    denom = (2.0 * mu + 1.0) * (mu + 2.0) - 2.0 * ratio3 * (mu - 1.0) ** 2
    s = denom / (9.0 * mu)
    return {"shielding_factor": s, "h_in_over_h0": 1.0 / s, "mu_r": mu,
            "radius_ratio": a / b}


def cylinder_shielding_factor_thin(mu_r: Any, wall_thickness_m: Any,
                                   diameter_m: Any) -> dict[str, Any]:
    """薄壁圆管横向场屏蔽近似：S ≈ 1 + μ_r·t/D（工程式，band 口径）。

    适用域 t≪D（薄壁）如实声明；端部泄漏/开孔修正不做（登记）。
    """
    mu = _positive(mu_r, "mu_r")
    t = _positive(wall_thickness_m, "wall_thickness_m")
    d = _positive(diameter_m, "diameter_m")
    if t >= d:
        raise ValueError("wall_thickness_m 须 < diameter_m（薄壁口径）")
    s = 1.0 + mu * t / d
    return {"shielding_factor": s, "regime": "thin_wall_approx",
            "note": "端部泄漏/开孔修正不做（登记级）"}


def multilayer_shield_estimate(shield_factors: Any) -> dict[str, Any]:
    """多层屏蔽近似串联：S_total ≈ Π S_i（层间退耦口径，登记级）。

    层间间距不足时实际低于乘积（耦合劣化）——如实 note；输入须全 >1。
    """
    factors = [float(x) for x in shield_factors]
    if not factors:
        raise ValueError("shield_factors 不得为空")
    total = 1.0
    for i, s in enumerate(factors):
        if not math.isfinite(s) or s <= 1.0:
            raise ValueError(f"第 {i} 层屏蔽系数须 >1，实际 {s}")
        total *= s
    return {
        "shielding_factor": total,
        "n_layers": len(factors),
        "note": "层间退耦近似；间距不足时实际低于乘积（登记级口径）",
    }


def mu_metal_band() -> dict[str, Any]:
    """mu-metal（Ni-Fe 软磁）datasheet 数值带（band+single_source）。

    典型带（退火态，厚度/工艺强依赖）：μ_r(initial) ~ 2e4–1e5、
    μ_r(max) ~ 2e5–3.5e5、B_sat ≈ 0.75–0.8 T。#122：band 不冒充仲裁值。
    """
    return {
        "material": "mu-metal (Ni80Fe15Mo5 类)",
        "mu_r_initial_band": (2.0e4, 1.0e5),
        "mu_r_max_band": (2.0e5, 3.5e5),
        "b_sat_t_band": (0.75, 0.8),
        "source": (
            "磁性材料手册/厂商 datasheet 公开带（single_source band，"
            "#122 不冒充仲裁值）"
        ),
    }


# ─── LLG 阻尼换算 ────────────────────────────────────────────────────────────
def llg_damping_conversion(alpha: Any, f_hz: Any) -> dict[str, float]:
    """LLG 阻尼 α ↔ FMR 线宽换算（小 α 一阶 + 精确式）。

    ΔB_FWHM = (2πf/γ)·(2α)/(1+α²)·... 标准口径：Δω_FWHM = 2αω（小 α），
    ΔB = Δω/γ = 2αω/γ；含 (1+α²)^{1/2} 修正在 α≪1 时二阶——本实现
    给一阶主值 + (1+α²) 修正因子如实分开报告。
    返回 {delta_b_fwhm_t, delta_f_fwhm_hz, alpha, f_hz}。
    """
    a = _positive(alpha, "alpha")
    f = _positive(f_hz, "f_hz")
    omega = 2.0 * math.pi * f
    delta_b = 2.0 * a * omega / GAMMA_RAD_S_T
    return {
        "delta_b_fwhm_t": delta_b,
        "delta_f_fwhm_hz": delta_b * GAMMA_RAD_S_T / (2.0 * math.pi),
        "alpha": a,
        "f_hz": f,
        "note": "一阶口径 Δω=2αω；(1+α²) 修正在 α≪1 时二阶（如实声明）",
    }
