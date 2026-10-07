"""EM-3 薄膜/涂层屏蔽 + SE 测量换算（IEEE 299/299.1）口径面。

规格：研究扩充 round17 §四 EM-3（P3/S）——
"Rs=1/(σt) 薄屏式；IEEE 299/299.1 只做口径文档"。纯闭式叶子，零 IO、
不进 calculators（同席 2/3 约定；EM-1 近场 SE / QW-11 平面波 SE 已有，
本模块只补薄膜/涂层支路与测量口径文档面）。

模块面
------
- ``thin_film_surface_impedance``：有限厚度导体膜复表面阻抗
  Z_s(t) = (1+j)/(σδ)·coth((1+j)t/δ)（Ramo-Whinnery-Van Duzer §5.5 口径，
  与 core/conductor_loss.finite_thickness_* 同式异消费——本模块自实现
  复数全量（该模块只出实部），单测互证实部）。
- ``thin_film_sheet_resistance``：薄屏极限 Rs = 1/(σt)（t≪δ，恒等锚：
  coth x → 1/x 的一阶展开精确返回，浮点容差内）。
- ``resistive_sheet_se``：自由空间中薄电阻膜的法向屏蔽效能
  t_amp = 2η0/(2η0+Rs) → SE = 20log10(1+Rs/(2η0))（shunt admittance
  ABCD 独立裁判路，#118 双路互证）；Rs→0 → SE→0、Rs=2η0 → 6.02dB
  （半电压锚）。
- ``coated_substrate_se``：介质基板上薄涂层（涂层膜 + 基板 TL 段级联
  ABCD，两侧自由空间）——透射系数与 SE（法向）。
- ``ieee299_measurement_note``：IEEE 299 / IEEE 299.1 测量换算口径
  文档面（只做口径：标准范围/试样口径/动态范围要素声明；标准正文
  收费——数值不抄录，页码 UNVERIFIED 如实 #122）。

物理口径（全 SI；时谐 e^{+jωt}，传播 e^{−jkz}）
------------------------------------------------
* 电阻膜边界条件（法向入射）：两侧切向 E 连续、H 跳变 = E/Rs
  → t_amp = 2η0/(2η0+Rs)。
* ABCD 级联：电阻膜 = 并联导纳 Y=1/Rs（ABCD=[1 0; 1/Rs 1]）；介质段
  ABCD=[cos βd, jη sin βd; j sin βd/η, cos βd]。S21 = 2/(A+B/η0+Cη0+D)。
* 设计约束：标准库+cmath；非法输入显式 ValueError；dict 输出有限数。

出处
----
1. round 文档：round17 §四 EM-3。
2. Ramo-Whinnery-Van Duzer "Fields and Waves" 3rd §5.5（coth 表面阻抗
   口径名，页码 UNVERIFIED）；IEEE 299-2006 / IEEE 299.1（测量口径名，
   标准正文收费只作口径声明，页码 UNVERIFIED）。
"""
from __future__ import annotations

import cmath
import math
from typing import Any

__all__ = [
    "C0_M_S",
    "ETA0_OHM",
    "IEEE299_SOURCE",
    "RWV_SOURCE",
    "coated_substrate_se",
    "ieee299_measurement_note",
    "resistive_sheet_se",
    "skin_depth_m",
    "thin_film_sheet_resistance",
    "thin_film_surface_impedance",
]

C0_M_S = 299792458.0
ETA0_OHM = 376.730313668  # μ0·c0（精确值按 4πe-7·c 恒等，测试钉 1e-9 相对）
RWV_SOURCE = (
    "Ramo-Whinnery-Van Duzer, Fields and Waves 3rd §5.5（coth 复表面阻抗"
    "口径名，页码 UNVERIFIED）"
)
IEEE299_SOURCE = (
    "IEEE Std 299-2006 / IEEE Std 299.1（口径名；标准正文收费，"
    "只作口径声明不抄数值，页码 UNVERIFIED，#122 如实）"
)


def _positive(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def _nonneg(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v < 0.0:
        raise ValueError(f"{name} 必须为非负有限数，实际 {x!r}")
    return v


def skin_depth_m(f_hz: Any, sigma: Any, mu_r: Any = 1.0) -> float:
    """趋肤深度 δ = √(2/(ω μ σ))（m）。"""
    f = _positive(f_hz, "f_hz")
    s = _positive(sigma, "sigma")
    mur = _positive(mu_r, "mu_r")
    mu0 = 4.0e-7 * math.pi
    return math.sqrt(2.0 / (2.0 * math.pi * f * mu0 * mur * s))


def thin_film_surface_impedance(thickness_m: Any, sigma: Any, f_hz: Any,
                                mu_r: Any = 1.0) -> complex:
    """有限厚导体膜复表面阻抗 Z_s = (1+j)/(σδ)·coth((1+j)t/δ)（Ω/sq）。

    t>δ 时数值上 coth 大宗模 → 1（返回 (1+j)/(σδ) 半无限极限）；
    t≪δ 时 coth x → 1/x → Rs=1/(σt) 纯实（薄屏极限）。
    """
    t = _positive(thickness_m, "thickness_m")
    s = _positive(sigma, "sigma")
    f = _positive(f_hz, "f_hz")
    mur = _positive(mu_r, "mu_r")
    delta = skin_depth_m(f, s, mur)
    zs0 = (1.0 + 1.0j) / (s * delta)
    x = (1.0 + 1.0j) * t / delta
    if abs(x) > 30.0:  # coth x → 1（e^{-2x} 溢出防护，误差 ~2e^{-2|x|}<1e-6；指数衰减非平方，A-09 勘误）
        return zs0
    return zs0 / cmath.tanh(x)


def thin_film_sheet_resistance(sigma: Any, thickness_m: Any) -> float:
    """薄屏直流面电阻 Rs = 1/(σt)（Ω/sq；t≪δ 口径，纯实）。"""
    s = _positive(sigma, "sigma")
    t = _positive(thickness_m, "thickness_m")
    return 1.0 / (s * t)


def resistive_sheet_se(sheet_resistance_ohm: Any) -> dict[str, Any]:
    """自由空间薄电阻膜法向 SE：SE = 20log10(1 + η0/(2Rs))（dB）。

    边界条件推导：E 连续 + H 跳变 = 面电流 E_t/Rs →
    t_amp = E_t/E_i = 2Rs/(2Rs+η0) = 1/(1+η0/(2Rs))。ABCD 独立路
    （并联导纳 Y=1/Rs → S21=2/(2+η0/Rs)）同式（测试互证）。
    极限：Rs→∞（无膜）→ t→1、SE→0；Rs=η0/2 → t=1/2（半电压锚，
    SE=6.02dB）；Rs→0（PEC 膜）→ SE→∞（如实 inf）。
    """
    rs = _nonneg(sheet_resistance_ohm, "sheet_resistance_ohm")
    if rs == 0.0:
        return {"se_db": math.inf, "t_amplitude": 0.0,
                "sheet_resistance_ohm": 0.0}
    t_amp = 2.0 * rs / (2.0 * rs + ETA0_OHM)
    se = -20.0 * math.log10(t_amp)
    return {"se_db": se, "t_amplitude": t_amp, "sheet_resistance_ohm": rs}


def coated_substrate_se(coating_thickness_m: Any, coating_sigma: Any,
                        substrate_thickness_m: Any, substrate_er: Any,
                        f_hz: Any) -> dict[str, Any]:
    """介质基板 + 薄涂层（法向入射，两侧自由空间）透射与 SE。

    ABCD 级联：涂层膜（复 Z_s 并联导纳，全量复阻抗口径）× 基板 TL 段。
    返回 {s21_complex, se_db, zs_coating}。SE = −20log|S21|。
    """
    tc = _positive(coating_thickness_m, "coating_thickness_m")
    sc = _positive(coating_sigma, "coating_sigma")
    ts = _nonneg(substrate_thickness_m, "substrate_thickness_m")
    er = _positive(substrate_er, "substrate_er")
    f = _positive(f_hz, "f_hz")
    zs = thin_film_surface_impedance(tc, sc, f)
    y_sheet = 1.0 / zs
    # 电阻膜 ABCD（全量复导纳）：[1, 0; Y, 1]
    a_m = 1.0 + 0.0j
    b_m = 0.0 + 0.0j
    c_m = y_sheet
    d_m = 1.0 + 0.0j
    if ts > 0.0:
        eta_sub = ETA0_OHM / math.sqrt(er)
        beta = 2.0 * math.pi * f * math.sqrt(er) / C0_M_S
        cos_b = cmath.cos(beta * ts)
        sin_b = cmath.sin(beta * ts)
        a_sub, b_sub = cos_b, 1j * eta_sub * sin_b
        c_sub, d_sub = 1j * sin_b / eta_sub, cos_b
        # 级联 M = M_sheet @ M_sub
        a_t = a_m * a_sub + b_m * c_sub
        b_t = a_m * b_sub + b_m * d_sub
        c_t = c_m * a_sub + d_m * c_sub
        d_t = c_m * b_sub + d_m * d_sub
    else:
        a_t, b_t, c_t, d_t = a_m, b_m, c_m, d_m
    s21 = 2.0 / (a_t + b_t / ETA0_OHM + c_t * ETA0_OHM + d_t)
    se = -20.0 * math.log10(abs(s21)) if abs(s21) > 0.0 else math.inf
    return {"s21_complex": s21, "se_db": se, "zs_coating": zs}


def ieee299_measurement_note() -> dict[str, str]:
    """IEEE 299 / 299.1 SE 测量换算口径文档面（只做口径，不抄数值）。

    口径要素声明（文档语义，无基准数值——标准正文收费，#122）：
    - IEEE 299：大机壳/屏蔽室 SE 测量（低/共振/高 three-band 口径名）；
    - IEEE 299.1：小机壳（尺寸受限试样）口径名；
    - 换算要素：动态范围校准、试样搭接/孔缝状态、发射/接收天线极化
      与间距口径——本仓闭式面（shield/near_field_se/本模块）对哪种
      测量口径可比，由调用方按试样形态声明，不自动换算。
    """
    return {
        "ieee299_scope": "大屏蔽体/屏蔽室 SE 测量口径名（三频段结构）",
        "ieee299_1_scope": "小机壳 SE 测量口径名（尺寸受限）",
        "conversion_statement": (
            "只做口径文档：闭式 SE（本模块/EM-1/QW-11）与测量值的可比性"
            "由试样形态（连续膜/孔缝/搭接）决定，不做自动换算系数"
        ),
        "source": IEEE299_SOURCE,
    }
