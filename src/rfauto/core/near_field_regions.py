"""AP-3 近场区界判据族（round17 §三 AP-3，P1/S；2026-10-03）。

反应近场/辐射近场（Fresnel）/远场（Fraunhofer）三区边界闭式 +
测量距离惯例。全部**纯函数零 IO**、零求解器依赖（round17 现状行
"近场区界判据族全仓无实现"的首件；衔接 core/exposure_limits.py
far-field 注记的"Fraunhofer d=2D²/λ 需口径 D"遗留项——本模块补上
带口径 D 的判据面，service 挂接是后续项）。

出处与口径：
- Fraunhofer（远场下界）：d_F = 2·D²/λ（D=天线最大口径尺寸，
  λ=波长）。Balanis《Antenna Theory》3rd ed Chapter 2 p.34（经
  Wikipedia "Near and far field" 引注实测核对，2026-10-03 web_reader
  抓取）；并要求 d_F≫D 与 d_F≫λ 两个附带条件（同源）。
- 反应近场（大天线）：R < 0.62·√(D³/λ)（Balanis 同页口径，适用
  D 与 λ 可比的"大"天线）。
- 反应近场（电小天线惯例）：R ≈ λ/(2π)（IEEE Std 145-1983 /
  OSHA 1990 公开域文本口径，Wikipedia "Near and far field" reactive
  小节引注实测核对——"commonly considered to be a distance of
  λ/2π from the antenna surface"）。
- 相位误差判据（2D²/λ 的独立几何出处）：口径边缘对球面波与平面波
  的程差 Δr = √(R²+(D/2)²)−R ≈ D²/(8R)，对应相位误差
  Δφ = 2π·D²/(8λR)。取 Δφ=π/8 → R=2D²/λ（Fraunhofer 判据的
  几何等价）；Δφ=π/16 → 4D²/λ（低副瓣测量惯例档）。
- 测量距离惯例 10·D²/λ：round17 AP-3 规格点名，本环境未能核到
  独立原始文献（搜索后端限流）——按 #122 如实标 UNVERIFIED 实现面
  （measurement_range_m rule="ten_d2"），消费方自行裁量。

#118/#300 基准对照（预声明进 tests/unit/test_near_field_regions.py）：
1. 闭式手算值锚（D=0.5m@10GHz→d_F=16.67m 等）；
2. 2D²/λ ↔ π/8 相位判据的独立几何互证（数值路径差 vs 闭式换算，
   两推导路径独立）；
3. 区界排序约束 0.62√(D³/λ) ≤ 2D²/λ 的成立域 D ≥ λ/10.405
   （代数解，域外显式 ValueError，测试钉边界）。
"""

from __future__ import annotations

import math
from typing import Any

#: 光速（SI 精确值，与 propagation.C0_M_S / bounds.SPEED_OF_LIGHT_M_S 同值）。
C0_M_S = 299792458.0

#: 区界排序成立域：0.62²·D³/λ ≤ 4·D⁴/λ ⟺ D ≥ 0.62²·λ/4 = λ/10.4058。
_ORDER_MIN_D_OVER_LAMBDA = 0.62**2 / 4.0


def _num(value: Any, name: str) -> float:
    """有限数校验（bool 显式拒收——df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _pos(value: Any, name: str) -> float:
    """正数域守卫（>0）。"""
    out = _num(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正，得 {out}")
    return out


def wavelength_m(f_hz: float) -> float:
    """波长 λ = c/f [m]。"""
    return C0_M_S / _pos(f_hz, "f_hz")


def fraunhofer_distance_m(d_m: float, f_hz: float) -> float:
    """远场（Fraunhofer）下界 d_F = 2·D²/λ [m]（Balanis 3rd ch.2 p.34）。

    附带条件 d_F≫D、d_F≫λ 不在本闭式内（同源口径，调用方自检）。
    锚：D=0.5m@10GHz → 16.6667m。
    """
    d = _pos(d_m, "d_m")
    lam = wavelength_m(f_hz)
    return 2.0 * d * d / lam


def reactive_near_field_m(d_m: float, f_hz: float) -> float:
    """反应近场外界（大天线）R = 0.62·√(D³/λ) [m]（Balanis 同源）。

    适用 D 与 λ 可比或更大的天线；电小天线（D≲λ/2）用
    reactive_near_field_small_antenna_m（两惯例不静默互切）。
    锚：D=λ → 0.62λ；D=2λ → 0.62√8·λ=1.75363λ。
    """
    d = _pos(d_m, "d_m")
    lam = wavelength_m(f_hz)
    return 0.62 * math.sqrt(d**3 / lam)


def reactive_near_field_small_antenna_m(f_hz: float) -> float:
    """反应近场外界（电小天线惯例）R = λ/(2π) [m]。

    IEEE Std 145-1983 / OSHA 1990 公开域口径（Wikipedia 引注实测
    核对）。锚：1GHz → 0.0477465m。
    """
    return wavelength_m(f_hz) / (2.0 * math.pi)


def fresnel_region_m(d_m: float, f_hz: float) -> dict[str, float]:
    """辐射近场（Fresnel）区界 (inner, outer) = (0.62√(D³/λ), 2D²/λ)。

    域约束：区界排序成立须 D ≥ λ/10.406（代数解，_ORDER_MIN_D_OVER_LAMBDA）；
    域外两界交叉、判据族失效，显式 ValueError（不凑数）。
    """
    d = _pos(d_m, "d_m")
    lam = wavelength_m(f_hz)
    if d < _ORDER_MIN_D_OVER_LAMBDA * lam:
        raise ValueError(
            f"D/λ={d / lam:.4g} 低于区界排序成立域 "
            f"{_ORDER_MIN_D_OVER_LAMBDA:.4g}（0.62√(D³/λ)>2D²/λ，判据族"
            "失效）——电小天线请用 reactive_near_field_small_antenna_m +"
            " 波长级惯例")
    return {
        "inner_m": reactive_near_field_m(d, f_hz),
        "outer_m": fraunhofer_distance_m(d, f_hz),
    }


def far_field_range_for_phase_error_m(
    d_m: float, f_hz: float, phase_error_rad: float = math.pi / 8.0
) -> float:
    """给定口径边缘最大相位误差容许的远场距离 R = πD²/(4λ·Δφ) [m]。

    几何出处：边缘-中心程差 Δr≈D²/(8R) → Δφ=2π·D²/(8λR)。
    Δφ=π/8 → 恒等于 2D²/λ（Fraunhofer）；Δφ=π/16 → 4D²/λ。
    Δφ 域 (0, π]。
    """
    d = _pos(d_m, "d_m")
    lam = wavelength_m(f_hz)
    dphi = _num(phase_error_rad, "phase_error_rad")
    if dphi <= 0.0 or dphi > math.pi:
        raise ValueError(f"phase_error_rad 须在 (0, π] 内，得 {dphi}")
    return math.pi * d * d / (4.0 * lam * dphi)


def measurement_range_m(
    d_m: float, f_hz: float, rule: str = "pi_8"
) -> tuple[float, str]:
    """方向图测量距离惯例 [m]（返回 (距离, 出处标注)）。

    rule：
    - "pi_8"：2D²/λ（π/8 相位判据；Fraunhofer 标准口径）
    - "pi_16"：4D²/λ（π/16 相位判据；低副瓣测量惯例档）
    - "ten_d2"：10D²/λ（round17 AP-3 规格点名的测量惯例；独立原始
      文献出处 UNVERIFIED——本环境搜索后端限流未能核实，按 #122
      如实标注，值域自洽性由测试钉）
    """
    d = _pos(d_m, "d_m")
    d_f = fraunhofer_distance_m(d, f_hz)
    if rule == "pi_8":
        return d_f, "2D2/lambda (phase pi/8, Fraunhofer, Balanis 3rd ch.2)"
    if rule == "pi_16":
        return 2.0 * d_f, "4D2/lambda (phase pi/16, low-sidelobe practice)"
    if rule == "ten_d2":
        return 5.0 * d_f, "10D2/lambda (round17 AP-3 spec; source UNVERIFIED)"
    raise ValueError(f"rule 只收 pi_8/pi_16/ten_d2，得 {rule!r}")


def classify_region(r_m: float, d_m: float, f_hz: float) -> str:
    """按距 r 的场区分类：reactive / fresnel / fraunhofer。

    边界语义（含等号）：r ≤ 0.62√(D³/λ) → reactive；< 2D²/λ →
    fresnel；≥ 2D²/λ → fraunhofer。排序失效域（D<λ/10.406）显式
    ValueError（同 fresnel_region_m）。
    """
    r = _num(r_m, "r_m")
    region = fresnel_region_m(d_m, f_hz)
    if r <= region["inner_m"]:
        return "reactive"
    if r < region["outer_m"]:
        return "fresnel"
    return "fraunhofer"


def far_field_assessment(r_m: float, d_m: float, f_hz: float) -> dict[str, Any]:
    """单点场区评估（exposure_limits.py far_field_note 的带口径 D 消费面）。

    返回 JSON 可序列化 dict：region / r_m / reactive_m / fraunhofer_m /
    wavelength_m / note（近场合规提示——远场球面判据不作近场 SAR/MPE
    合规依据，与 exposure_limits 口径互衔）。
    """
    r = _num(r_m, "r_m")
    if r < 0.0:
        raise ValueError(f"r_m 必须 ≥0（距离无负值），得 {r}")
    lam = wavelength_m(f_hz)
    region = fresnel_region_m(d_m, f_hz)
    return {
        "region": classify_region(r, d_m, f_hz),
        "r_m": r,
        "reactive_m": region["inner_m"],
        "fraunhofer_m": region["outer_m"],
        "wavelength_m": lam,
        "d_over_lambda": _pos(d_m, "d_m") / lam,
        "note": "远场球面口径仅对 r≥2D²/λ 成立；反应近场用 λ/2π 惯例"
                "（reactive_near_field_small_antenna_m）；本评估不作近场"
                "SAR/MPE 合规判据（衔接 core/exposure_limits far_field_note）",
    }
