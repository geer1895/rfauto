"""AP-13 频率不变族（螺旋）闭式内核（round17 §三 AP-13，P3/S；2026-10-03）。

Rumsey 原理 + 等角（对数）螺旋/阿基米德螺旋的几何闭式与带宽设计映射。
**纯函数零 IO**、numpy/math 依赖、零求解器依赖；只做几何/标量闭式，
不做电磁求解（#122：方向图/阻抗随频率的性能声明属仿真域，不在本件）。

出处与口径
----------
- **Rumsey 原理**：形状仅由角度定义（无特征长度）的天线，其阻抗/
  方向图与频率近似无关（V.H. Rumsey, "Frequency-Independent
  Antennas", 1957 IRE National Convention Record Pt.1——页码
  UNVERIFIED 如实，#122；系统表述见 Rumsey 专著 *Frequency
  Independent Antennas*, Academic Press 1966）。
- **等角螺旋 r(φ)=r₀·e^{αφ} 的自相似性是 Rumsey 原理在几何上的
  精确化**：旋转 Δφ = ln(s)/α 等价于放大 s 倍——
      r(φ+Δφ) = r₀·e^{αφ}·e^{αΔφ} = s·r(φ)，
  即"换尺度 = 转角度"。频率换算 f→f/s 时结构在新尺度下重合 →
  性能量按对数周期（ln s）近似重复（对数周期性的几何根源）。
  每圈增长率 g = r(φ+2π)/r(φ) = e^{2πα}（精确恒等式）。
- **等角螺旋弧长闭式**：L(φ) = ∫₀^φ r₀e^{αt}√(1+α²)dt =
      r₀·√(1+α²)/α·(e^{αφ}−1)  （α>0）
  α→0 退化圆弧 L = r₀φ（极限锚）。
- **阿基米德螺旋 r(φ)=r₀+bφ**：两臂（φ 偏移 π）沿同径向的分离
  = π·b（n 臂 2πb/n）；r₀=0 时弧长闭式（∫√(r²+r'²)dφ 的标准
  积分）  L(0→Φ) = (b/2)[Φ√(1+Φ²)+asinh(Φ)]。
- **频带 ↔ 几何映射（活跃区惯例）**：周长 ≈ λ 的环带为有效辐射区
  （工程惯例口径；Duncan-Minerva 等角螺旋文献的设计惯例，出处页码
  UNVERIFIED 如实）——
      f_high ≈ c/(2π·r_in)，f_low ≈ c/(2π·r_out)，
  带宽比 = r_out/r_in = e^{α·Δφ}。给定 (f_low,f_high,圈数) 可综合
  α 与截断半径，正向映射往返闭合（测试钉）。
- **自互补阻抗（Babinet–Booker）**：平面自互补天线的输入阻抗
  Z_in = η₀/4 ≈ 94.18 Ω（Babinet 原理的 Booker 扩展；经典值）。
  两臂等角螺旋的自互补几何条件 = 臂角宽 = 间隙角宽 = π/2
  （每 π 周期金属/空气互补互换）；η₀ = 376.730313668 Ω（CODATA）。

锚（#118/#300，tests/unit/test_frequency_invariant.py）
------------------------------------------------------
1. 每圈增长率：闭式 e^{2πα} vs 数值比值 r(φ+2π)/r(φ)（rel<1e-12）。
2. 弧长闭式 vs 弦长数值积分（独立路径，rel<1e-6）；α→0 圆弧极限
   L=r₀φ（闭式极限锚）。
3. 自相似：s 倍放大 + Δφ=ln(s)/α 旋转的点落在原曲线上（最近点
   距离 <1e-9 r₀）。
4. Babinet：η₀/4 的算术锚（rel<1e-12）+ 互补角分区覆盖 π 的
   算术恒等式。
5. 频带综合往返：design→正向 band 映射恢复 (f_low,f_high)
   （rel<1e-12）；r_out/r_in = 频率比 = e^{αΔφ} 三方一致。
6. 阿基米德：分离闭式 vs 数值（逐位）；r₀=0 弧长闭式 vs 弦长积分
   （rel<1e-6）；频带映射往返。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = [
    "ETA0_OHM",
    "SELF_COMPLEMENTARY_ARM_WIDTH_RAD",
    "SPEED_OF_LIGHT",
    "alpha_from_growth",
    "archimedean_arc_length_from_zero",
    "archimedean_arm_radial_separation",
    "archimedean_band_radii",
    "archimedean_points",
    "equiangular_arc_length",
    "equiangular_band_from_design",
    "equiangular_band_radii",
    "equiangular_growth_per_turn",
    "equiangular_points",
    "equiangular_radius",
    "log_spiral_rotation_for_scale",
    "numeric_arc_length",
    "self_complementary_impedance",
]

SPEED_OF_LIGHT = 299792458.0
#: 真空波阻抗 η₀ [Ω]（CODATA 2018 值；SI-2019 下非精确定义值）。
ETA0_OHM = 376.730313668
#: 两臂等角螺旋自互补几何的臂角宽 [rad]（金属/间隙各占 π/2）。
SELF_COMPLEMENTARY_ARM_WIDTH_RAD = math.pi / 2.0


def _pos(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，得 {value!r}")
    return out


def _nonneg(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out) or out < 0.0:
        raise ValueError(f"{name} 必须为非负有限数，得 {value!r}")
    return out


# ─── 等角（对数）螺旋 ────────────────────────────────────────────────────────


def equiangular_radius(r0_m: Any, alpha: Any, phi_rad: Any) -> Any:
    """等角螺旋半径 r(φ)=r₀·e^{αφ}（α>0；标量或数组 φ）。"""
    r0 = _pos(r0_m, "r0_m")
    a = _pos(alpha, "alpha")
    return r0 * np.exp(a * np.asarray(phi_rad, dtype=float))


def equiangular_growth_per_turn(alpha: Any) -> float:
    """每圈增长率 g = e^{2πα}（r(φ+2π)/r(φ) 精确恒等式）。"""
    a = _pos(alpha, "alpha")
    return math.exp(2.0 * math.pi * a)


def alpha_from_growth(growth_per_turn: Any) -> float:
    """由每圈增长率反解 α = ln(g)/(2π)（g>1）。"""
    g = _pos(growth_per_turn, "growth_per_turn")
    if g <= 1.0:
        raise ValueError(f"growth_per_turn 必须 >1，得 {g}")
    return math.log(g) / (2.0 * math.pi)


def equiangular_points(
    r0_m: Any, alpha: Any, phi_max_rad: Any, n: Any = 721,
    n_arms: int = 2,
) -> dict[str, Any]:
    """等角螺旋臂点列：臂 k 的角偏移 2πk/n_arms。

    返回 {phi_rad:(n,), arms:[(n,2) ndarray(x,y) per arm], radii:[(n,)]}。
    """
    r0 = _pos(r0_m, "r0_m")
    a = _pos(alpha, "alpha")
    pmax = _pos(phi_max_rad, "phi_max_rad")
    if int(n) < 2:
        raise ValueError("n 须 ≥2")
    if n_arms < 1:
        raise ValueError("n_arms 须 ≥1")
    phi = np.linspace(0.0, pmax, int(n))
    arms = []
    radii = []
    for k in range(n_arms):
        r = equiangular_radius(r0, a, phi)
        pk = phi + 2.0 * math.pi * k / n_arms
        arms.append(np.stack([r * np.cos(pk), r * np.sin(pk)], axis=-1))
        radii.append(r)
    return {"phi_rad": phi, "arms": arms, "radii": radii}


def equiangular_arc_length(r0_m: Any, alpha: Any, phi_max_rad: Any) -> float:
    """弧长闭式 L = r₀·√(1+α²)/α·(e^{αφ}−1)（α>0）。

    α→0 极限 L = r₀φ（圆弧，闭式极限锚；本函数对 α>0 强制，
    圆弧极限由调用方用 equiangular_radius 退化或直接 r₀φ）。
    """
    r0 = _pos(r0_m, "r0_m")
    a = _pos(alpha, "alpha")
    pmax = _pos(phi_max_rad, "phi_max_rad")
    return r0 * math.sqrt(1.0 + a * a) / a * (math.exp(a * pmax) - 1.0)


def numeric_arc_length(
    r_of_phi: Any, phi_max_rad: Any, n: int = 20001
) -> float:
    """弦长数值弧长（第三方法/独立路径）：Σ|r(φᵢ₊₁)e^{iφᵢ₊₁}−r(φᵢ)e^{iφᵢ}|。

    r_of_phi：标量→数组 φ 的半径函数。
    """
    if n < 2:
        raise ValueError("n 须 ≥2")
    phi = np.linspace(0.0, float(phi_max_rad), int(n))
    r = np.asarray(r_of_phi(phi), dtype=float)
    x = r * np.cos(phi)
    y = r * np.sin(phi)
    return float(np.sum(np.hypot(np.diff(x), np.diff(y))))


def log_spiral_rotation_for_scale(alpha: Any, scale: Any) -> float:
    """放大 s 倍等价的旋转角 Δφ = ln(s)/α（Rumsey 自相似的精确形态）。"""
    a = _pos(alpha, "alpha")
    s = _pos(scale, "scale")
    if s <= 1.0:
        raise ValueError(f"scale 必须 >1，得 {s}")
    return math.log(s) / a


# ─── 频带 ↔ 几何映射（活跃区周长≈λ 惯例）────────────────────────────────────


def equiangular_band_radii(freq_low_hz: Any, freq_high_hz: Any) -> dict[str, float]:
    """频带 → 外/内截断半径（周长≈λ 活跃区惯例）。

    r_out = c/(2π·f_low)、r_in = c/(2π·f_high)；带宽比 = f_high/f_low。
    """
    f_lo = _pos(freq_low_hz, "freq_low_hz")
    f_hi = _pos(freq_high_hz, "freq_high_hz")
    if f_hi <= f_lo:
        raise ValueError("须 f_high > f_low")
    return {
        "r_out_m": SPEED_OF_LIGHT / (2.0 * math.pi * f_lo),
        "r_in_m": SPEED_OF_LIGHT / (2.0 * math.pi * f_hi),
        "radius_ratio": f_hi / f_lo,
    }


def equiangular_band_from_design(
    freq_low_hz: Any, freq_high_hz: Any, turns: Any,
) -> dict[str, Any]:
    """频带综合：给定 (f_low, f_high, 圈数) → (α, r₀, φ_max) 与正向校验。

    r_out/r_in = e^{α·Δφ} = f_high/f_low，Δφ = 2π·turns
    → α = ln(f_high/f_low)/(2π·turns)；r₀ = r_in。
    返回含正向 band_radii 重估的 freq_low/high（往返闭合，测试钉）。
    """
    band = equiangular_band_radii(freq_low_hz, freq_high_hz)
    t = _pos(turns, "turns")
    alpha = math.log(band["radius_ratio"]) / (2.0 * math.pi * t)
    # 正向校验：由 r_out/r_in 反估频率（周长≈λ 映射的逆）
    return {
        "alpha": alpha,
        "r0_m": band["r_in_m"],
        "r_out_m": band["r_out_m"],
        "phi_max_rad": 2.0 * math.pi * t,
        "growth_per_turn": equiangular_growth_per_turn(alpha),
        "forward_freq_low_hz": (SPEED_OF_LIGHT
                                / (2.0 * math.pi * band["r_out_m"])),
        "forward_freq_high_hz": (SPEED_OF_LIGHT
                                 / (2.0 * math.pi * band["r_in_m"])),
    }


# ─── 自互补（Babinet–Booker）────────────────────────────────────────────────


def self_complementary_impedance() -> float:
    """平面自互补天线输入阻抗 Z = η₀/4 ≈ 94.1826 Ω（Babinet–Booker）。"""
    return ETA0_OHM / 4.0


# ─── 阿基米德螺旋 ────────────────────────────────────────────────────────────


def archimedean_points(
    r0_m: Any, b_m_per_rad: Any, phi_max_rad: Any, n: Any = 721,
    n_arms: int = 2,
) -> dict[str, Any]:
    """阿基米德螺旋臂点列：r(φ)=r₀+bφ，臂 k 角偏移 2πk/n_arms。"""
    r0 = _nonneg(r0_m, "r0_m")
    b = _pos(b_m_per_rad, "b_m_per_rad")
    pmax = _pos(phi_max_rad, "phi_max_rad")
    if int(n) < 2 or n_arms < 1:
        raise ValueError("n≥2 且 n_arms≥1")
    phi = np.linspace(0.0, pmax, int(n))
    arms = []
    for k in range(n_arms):
        pk = phi + 2.0 * math.pi * k / n_arms
        r = r0 + b * pk
        arms.append(np.stack([r * np.cos(pk), r * np.sin(pk)], axis=-1))
    return {"phi_rad": phi, "arms": arms}


def archimedean_arm_radial_separation(b_m_per_rad: Any, n_arms: int = 2) -> float:
    """相邻臂沿同一径向的弧线间距 = 2π·b/n_arms（两臂默认 πb）。"""
    b = _pos(b_m_per_rad, "b_m_per_rad")
    if n_arms < 1:
        raise ValueError("n_arms 须 ≥1")
    return 2.0 * math.pi * b / n_arms


def archimedean_arc_length_from_zero(b_m_per_rad: Any, phi_max_rad: Any) -> float:
    """r₀=0 阿基米德螺旋弧长闭式：L = (b/2)[Φ√(1+Φ²)+asinh(Φ)]。"""
    b = _pos(b_m_per_rad, "b_m_per_rad")
    pmax = _pos(phi_max_rad, "phi_max_rad")
    return 0.5 * b * (pmax * math.sqrt(1.0 + pmax * pmax)
                      + math.asinh(pmax))


def archimedean_band_radii(freq_low_hz: Any, freq_high_hz: Any) -> dict[str, float]:
    """频带 → 外/内半径（周长≈λ 惯例，与等角螺旋同口径）。"""
    return equiangular_band_radii(freq_low_hz, freq_high_hz)
