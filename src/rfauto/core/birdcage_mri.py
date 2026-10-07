"""NX-8 MRI 鸟笼线圈（birdcage）集总模式闭式（P3 登记级）。

规格：研究扩充 round14 §四 NX-8——"端环集总
等效+模式分解（维持 P3 不排期，仅登记）"。本模块=登记级纯闭式：
LC 梯度网络色散关系 + 正弦/余弦模式场形 + 正交驱动圆极化面。

模型（低通鸟笼：腿电感 L、每腿两端环电容各 C/2 集总等效为每格并联 C）
------------------------------------------------------------------
N 腿周期梯度的 Bloch 色散（串联 jωL + 并联 jωC 每格，周期边界
kd=2πm/N）：ω_m = (2/√(LC))·|sin(π m / N)|，m=0..N-1。
- m=0 → ω=0（直流模，非谐振）；
- 简并：ω_m = ω_{N−m}（sin 对称）——正弦/余弦空间对（sin(φ)、cos(φ)
  场形同频简并），N 偶时 m=N/2 单模；
- 谐振模语义：鸟笼"调谐频率"= m=1 模（最低非零）。
自推导（集总梯度色散标准结果）+ Jin "Electromagnetic Analysis and
Design in MRI"（口径名，页码 UNVERIFIED，#122 如实）。互感/分布效应
不做（登记级边界）。

模块面
------
- ``birdcage_mode_frequencies``：ω_m 表 + 简并结构 + 调谐频率（m=1）。
- ``birdcage_mode_shape``：模式 m 的场形函数 cos(mφ)/sin(mφ)（归一）。
- ``quadrature_drive_field``：m=1 正弦+余弦对 90° 馈电 → 圆极化纯度
  （|B1+|/|B1−| 口径：正交理想 → 单旋向，|B1−|=0 逐位）。
- ``homogeneity_note``：m=1 模中心区一阶均匀（cos φ 展开无二次项的
  登记注记）+ 登记级边界声明（不做分布/互感/屏蔽）。

出处
----
1. round 文档：round14 §四 NX-8。
2. Jin, "Electromagnetic Analysis and Design in MRI"（鸟笼集总模式
   口径名，页码 UNVERIFIED）。色散式为本模块自推导（Bloch-Floquet
   集总梯度），单测做网络级数值对拍（#118：独立数值路=格点导纳
   矩阵本征值）。
"""
from __future__ import annotations

import math
from typing import Any

__all__ = [
    "birdcage_mode_frequencies",
    "birdcage_mode_shape",
    "homogeneity_note",
    "quadrature_drive_field",
]


def _positive(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def birdcage_mode_frequencies(n_legs: Any, l_leg_h: Any,
                              c_ring_f: Any) -> dict[str, Any]:
    """低通鸟笼集总模式角频率 ω_m = (2/√(LC))·|sin(π m/N)|。

    c_ring_f：每腿一端的端环电容（两端对称，集总等效每格并联 C 的
    口径下 C = 2·c_ring——两端电容串联到该格并联等效；本函数直接
    消费 c_ring_f 为端环电容，等效并联 C=2·c_ring_f，docstring 声明）。
    返回 {n_legs, omega_rad_s(列表 m=0..N−1), f_hz(同序), m1_omega,
    degenerate_pairs}。
    """
    n = int(n_legs)
    if n < 3:
        raise ValueError("n_legs 必须 >=3（鸟笼拓扑最低阶）")
    big_l = _positive(l_leg_h, "l_leg_h")
    c_ring = _positive(c_ring_f, "c_ring_f")
    c_eff = 2.0 * c_ring  # 两端环串联到格并联的集总等效（口径声明）
    base = 2.0 / math.sqrt(big_l * c_eff)
    omegas = []
    for m in range(n):
        omegas.append(base * abs(math.sin(math.pi * m / n)))
    freqs = [w / (2.0 * math.pi) for w in omegas]
    # 简并对：ω_m = ω_{N−m}（m 与 N−m，m=1..floor((N−1)/2)）
    pairs = [[m, n - m] for m in range(1, (n + 1) // 2)]
    if n % 2 == 0:
        pairs = [[m, n - m] for m in range(1, n // 2)]
    return {
        "n_legs": n,
        "omega_rad_s": omegas,
        "f_hz": freqs,
        "m1_omega": omegas[1],
        "degenerate_pairs": pairs,
    }


def birdcage_mode_shape(n_legs: Any, mode_m: Any, phase_deg: Any) -> dict[str, float]:
    """模式 m 场形：cos(mφ) 与 sin(mφ) 线圈位置因子（φ_n=2πn/N）。

    返回给定方位角 phase_deg 处的 {cos_amp, sin_amp}（归一到峰值 1）。
    """
    n = int(n_legs)
    if n < 3:
        raise ValueError("n_legs 必须 >=3")
    m = int(mode_m)
    if not (0 <= m < n):
        raise ValueError("mode_m 须 0<=m<N")
    phi = math.radians(float(phase_deg))
    return {"cos_amp": math.cos(m * phi), "sin_amp": math.sin(m * phi)}


def quadrature_drive_field(n_phi_samples: Any) -> dict[str, float]:
    """m=1 正交驱动 wₙ=e^{jφₙ}=cosφₙ+j·sinφₙ（90° 对馈）的圆极化分解。

    旋转分量口径：B1± = (1/N)·Σₙ wₙ·e^{∓jφₙ}——
      B1− = (1/N)Σ e^{jφ}e^{−jφ} = 1（同旋向，构造性恒等）；
      B1+ = (1/N)Σ e^{2jφ} = 0（N≥3 等比求和解析零；数值残差如实报）。
    返回 {b1_co, b1_counter, counter_residue, purity}，
    purity = b1_co/(b1_co+b1_counter)。
    """
    n = int(n_phi_samples)
    if n < 3:
        raise ValueError("n_phi_samples 必须 >=3")
    phi = [2.0 * math.pi * k / n for k in range(n)]
    s_counter = sum(complex(math.cos(2.0 * p), math.sin(2.0 * p)) for p in phi) / n
    b1_co = 1.0
    b1_counter = abs(s_counter)
    return {
        "b1_co": b1_co,
        "b1_counter": b1_counter,
        "counter_residue": b1_counter,
        "purity": b1_co / (b1_co + b1_counter),
    }


def homogeneity_note() -> dict[str, str]:
    """登记级边界与均匀性口径声明（不做数值面）。"""
    return {
        "m1_uniformity": (
            "m=1 模 B1 ∝ cos φ（或 sin φ）：孔径中心区一阶均匀；"
            "径向变化 O((r/R)^2) 起二阶——精确值属全波面，本模块不做"
        ),
        "register_level_boundary": (
            "登记级：不含互感/分布参数/屏蔽/样品负载——鸟笼调谐工程值"
            "以真机/全波仲裁为准（#122 无基准不产数）"
        ),
        "source": "Jin, Electromagnetic Analysis and Design in MRI（口径名，页码 UNVERIFIED）",
    }
