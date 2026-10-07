r"""MM-8 EBG/AMC（高阻抗电磁表面/Sievenpiper 蘑菇）确定性内核
（round17 §五 :156「MM-8 EBG/AMC（P3/M）：Sievenpiper 蘑菇 LC 谐振+反射
相位带；HFSS Floquet 仲裁现成」，2026-10-02）。

规格边界：闭式 LC 模型+法向入射反射相位带（v1 单元集总口径）；斜入射
Floquet 色散与 HFSS 仲裁是模板/真机面，不在本内核（登记边界，round17
"HFSS Floquet 仲裁现成"指真机通路）。

法源与公式（铁律 5：出处写 docstring；#118：每面 ≥2 独立基准）：

- **D. F. Sievenpiper, L. Zhang, R. F. J. Broas, N. G. Alexópoulos,
  E. Yablonovitch, "High-Impedance Electromagnetic Surfaces with a
  Forbidden Frequency Band", IEEE Trans. MTT 47(9):1509-1514 (1999)**：
  蘑菇单元=相邻贴片间隙电容 C（边缘场）+过孔电流路径电感 L，等效
  表面阻抗（并联谐振到地）：

      Z_s(ω) = jωL / (1 − ω²·L·C)

  并联谐振 ω₀=1/√(LC) 处 Z_s→∞（PMC 口径，Γ=+1 反射相位过零）。
- **过孔电感**：L = μ₀·t（t=基板厚度）——论文 §"LC circuit model" 的
  标准结论（方形贴片下的电流路径电感近似只由介质厚度决定）。
- **间隙电容**：采用仓内单源闭式 fss_patch_grid_capacitance_f
  （metasurface_lut，Luukkonen/Costa arXiv:0705.3548 eq.4：
  C=(2D/π)ε0·ε_eff·ln(csc(πg/2D))）——与 Sievenpiper 论文的
  cosh⁻¹ 近似是同一共面间隙边缘场物理的两个近似（稠密栅有效域
  g≪D）；本席不自造第二套间隙闭式（#118 单源纪律，cosc⁻¹ 形态
  未回原文核对前不入码）。
- **反射系数与相位带**（法向平面波，等效表面阻抗边界）：

      Γ(ω) = (Z_s − η₀)/(Z_s + η₀)，  |Γ| = 1（无损恒等式）

  相位 φ(ω)=arg Γ（wrap (−180°,180°]）：低频 Z_s→0 → PEC（φ→±180°），
  ω₀ 处 Z_s→∞ → PMC（φ→0°）。记 R=√(L/C)/η₀（无量纲表面阻抗比），
  x=ω/ω₀：|φ|≤90° ⇔ R·x/(1−x²)≥1 ⇔ x²+R·x−1≥0（x<1 侧）→

      x_low = (√(R²+4)−R)/2，  x_high = 1/x_low（对称性 A(1/x)=−A(x)）
      分数带宽 = x_high − x_low = R = √(L/C)/η₀   （精确恒等式）

  最后一条即 Sievenpiper 论文的著名结论：±90° 相位带分数带宽只依赖
  √(L/C)/η₀、与谐振频率无关——本内核给出精确形式（文献口径为
  同式；数值根求交点对拍=锚树独立裁判）。

单位口径 SI（H/F/Hz/Ω/m）；e^{−jωt}；core 纯函数零 IO、不注册
（本席纪律 3：不加 calculators 键）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.metasurface_lut import (
    ETA0_OHM,
    MU0_H_M,
    fss_patch_grid_capacitance_f,
)

__all__ = [
    "amc_gap_capacitance_f",
    "amc_phase_band_hz",
    "amc_reflection_coeff",
    "amc_reflection_phase_deg",
    "amc_resonance_hz",
    "amc_surface_impedance",
    "amc_via_inductance_h",
    "mushroom_design_report",
]


def _require_positive(name: str, value: float) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限实数，got {value!r}")
    return v


# ── 1) LC 参数 ──────────────────────────────────────────────────────────


def amc_gap_capacitance_f(period_m: float, gap_m: float,
                          eps_eff: float) -> float:
    """蘑菇邻隙电容 C（F/胞）——Luukkonen/Costa 贴片栅闭式（仓内单源）。

    直接复用 metasurface_lut.fss_patch_grid_capacitance_f
    （C=(2D/π)ε0·ε_eff·ln(csc(πg/2D))，稠密栅 g≪D 有效域；eps_eff
    单侧基板加载口径 (1+εr)/2 同源）。Sievenpiper 论文自用的 cosh⁻¹
    近似为同一物理的第二近似，未回原文逐字核对前不自造（#118）。
    """
    return float(fss_patch_grid_capacitance_f(
        _require_positive("period_m", period_m),
        _require_positive("gap_m", gap_m),
        _require_positive("eps_eff", eps_eff)))


def amc_via_inductance_h(t_sub_m: float) -> float:
    """过孔电流路径电感 L=μ₀·t（H；Sievenpiper TAP 47(9):1509 (1999)
    LC 模型结论：方形贴片下电感近似只由基板厚度 t 决定）。"""
    t = _require_positive("t_sub_m", t_sub_m)
    return MU0_H_M * t


def amc_resonance_hz(l_via_h: float, c_gap_f: float) -> float:
    """AMC 谐振频率 f₀=1/(2π√(LC))（Hz；并联谐振，Γ 相位过零点）。"""
    l_via_h = _require_positive("l_via_h", l_via_h)
    c_gap_f = _require_positive("c_gap_f", c_gap_f)
    return 1.0 / (2.0 * math.pi * math.sqrt(l_via_h * c_gap_f))


# ── 2) 表面阻抗与反射系数 ────────────────────────────────────────────────


def amc_surface_impedance(omega_rad_s: float | np.ndarray,
                          l_via_h: float, c_gap_f: float) -> np.ndarray:
    """等效表面阻抗 Z_s(ω)=jωL/(1−ω²LC)（Ω；ω=ω₀ 处并联谐振极点→inf）。"""
    l_via_h = _require_positive("l_via_h", l_via_h)
    c_gap_f = _require_positive("c_gap_f", c_gap_f)
    w = np.asarray(omega_rad_s, dtype=float)
    if np.any(~np.isfinite(w)) or np.any(w <= 0.0):
        raise ValueError("omega_rad_s 必须为正有限实数")
    num = 1j * w * l_via_h
    den = 1.0 - (w * l_via_h) * (w * c_gap_f)
    with np.errstate(divide="ignore"):
        return np.asarray(num / den)


def amc_reflection_coeff(omega_rad_s: float | np.ndarray,
                         l_via_h: float, c_gap_f: float) -> np.ndarray:
    """法向入射反射系数 Γ=(Z_s−η₀)/(Z_s+η₀)（无损 |Γ|=1 恒等式）。"""
    zs = amc_surface_impedance(omega_rad_s, l_via_h, c_gap_f)
    return (zs - ETA0_OHM) / (zs + ETA0_OHM)


def amc_reflection_phase_deg(f_hz: float | np.ndarray,
                             l_via_h: float, c_gap_f: float) -> np.ndarray:
    """反射相位 φ(f)=arg Γ（deg，wrap (−180,180]；f=f₀ 处 0°，带缘
    ±90°，深低频 PEC → ±180°）。"""
    f = np.atleast_1d(np.asarray(f_hz, dtype=float))
    if np.any(~np.isfinite(f)) or np.any(f <= 0.0):
        raise ValueError("f_hz 必须为正有限实数")
    gam = amc_reflection_coeff(2.0 * np.pi * f, l_via_h, c_gap_f)
    phase = np.angle(gam, deg=True)
    # np.angle 已 wrap 到 (−180,180]；−180 归一为 +180（PEC 口径）
    phase = np.where(phase <= -180.0, 180.0, phase)
    return phase


# ── 3) ±90° 相位带（精确闭式）────────────────────────────────────────────


def amc_phase_band_hz(l_via_h: float, c_gap_f: float) -> dict[str, float]:
    """±90° 反射相位带边与分数带宽（精确闭式，Sievenpiper 带宽律）。

    推导（docstring 头部）：x_low=(√(R²+4)−R)/2、x_high=1/x_low、
    分数带宽=x_high−x_low=R=√(L/C)/η₀ 恒等（由 x²+Rx−1=0 移元
    (1−x²)/x=R）。返回 {f0_hz, f_low_hz, f_high_hz,
    fractional_bandwidth, impedance_ratio}。
    """
    l_via_h = _require_positive("l_via_h", l_via_h)
    c_gap_f = _require_positive("c_gap_f", c_gap_f)
    ratio = math.sqrt(l_via_h / c_gap_f) / ETA0_OHM
    x_low = (math.sqrt(ratio * ratio + 4.0) - ratio) / 2.0
    f0 = amc_resonance_hz(l_via_h, c_gap_f)
    return {
        "f0_hz": f0,
        "f_low_hz": x_low * f0,
        "f_high_hz": f0 / x_low,
        "fractional_bandwidth": ratio,
        "impedance_ratio": ratio,
    }


# ── 4) 单元设计报告 ─────────────────────────────────────────────────────


def mushroom_design_report(period_m: float, gap_m: float, t_sub_m: float,
                           eps_eff: float,
                           target_f0_hz: float | None = None) -> dict[str, Any]:
    """蘑菇单元设计报告（JSON 可序列化 dict）：C/L/f₀/相位带/带宽律自洽。

    target_f0_hz 给出时附设计偏差 verdict（±10% 带 |Δf|/f_target 判
    in_band/out_of_band——如实分派，不凑 PASS）。
    """
    period_m = _require_positive("period_m", period_m)
    gap_m = _require_positive("gap_m", gap_m)
    if gap_m >= period_m:
        raise ValueError(
            f"gap_m={gap_m!r} 须 < period_m={period_m!r}（稠密栅有效域）")
    t_sub_m = _require_positive("t_sub_m", t_sub_m)
    eps_eff = _require_positive("eps_eff", eps_eff)
    c = amc_gap_capacitance_f(period_m, gap_m, eps_eff)
    l_via = amc_via_inductance_h(t_sub_m)
    band = amc_phase_band_hz(l_via, c)
    report: dict[str, Any] = {
        "period_m": period_m,
        "gap_m": gap_m,
        "t_sub_m": t_sub_m,
        "eps_eff": eps_eff,
        "c_gap_f": c,
        "l_via_h": l_via,
        "f0_hz": band["f0_hz"],
        "f_low_hz": band["f_low_hz"],
        "f_high_hz": band["f_high_hz"],
        "fractional_bandwidth": band["fractional_bandwidth"],
        "impedance_ratio": band["impedance_ratio"],
    }
    if target_f0_hz is not None:
        target_f0_hz = _require_positive("target_f0_hz", target_f0_hz)
        dev = abs(band["f0_hz"] - target_f0_hz) / target_f0_hz
        report["target_f0_hz"] = target_f0_hz
        report["f0_deviation"] = dev
        report["verdict"] = "in_band" if dev <= 0.10 else "out_of_band"
    return report
