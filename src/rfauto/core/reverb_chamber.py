"""EM-8 混响室（reverberation chamber, RC）闭式统计与品质因数面。

规格：研究扩充 round17 §四 EM-8——"Weyl 模式数/
Q 上界/χ² 统计/搅拌独立数（Hill/IEC 61000-4-21 Annex K 次级源双源）+RC-SAC
换算文档"（P3 探索升主序）。模块 = 纯闭式/统计函数叶子，零 IO、不进
calculators 注册表（同席 2/3 约定）。

模块面
------
- ``weyl_mode_count``：Weyl 渐近模式数 N(f)=8πV(f√εr/c0)³/3（双极化口径）。
  与 core/microwave_heating.weyl_mode_stats（LT-5）同式异消费——本模块
  自实现 + 单测跨模块互证（#118：交叉锚），不引入对 LT 模块的运行时依赖。
- ``quality_factor_wall_loss``：搅拌良好腔壁损 Q 上界 Q = (3/2)·V/(μ_r,S·δ)
  （电大腔、各向同性场口径；Hill 1994/IEC 61000-4-21 口径，标准正文收费，
  公式以公开文献口径承载，页码 UNVERIFIED）。附能量法自洽推导（docstring）
  与两条结构锚：δ∝f^(-1/2) → Q∝f^(+1/2)；μ_r=1 时系数 3/2 与
  P=(ωμ/2Q)·... 量纲自洽。
- ``well_stirred_chi2``：搅拌良好场统计——单直角分量 |E_i|² 归一后为
  χ²(df=2)=Exp(1)（Kostas-Boverie 1991 口径：E_i 复高斯）；三分量能量密度
  ∼χ²(df=6)。pdf/cdf/quantile + N 样本 max 期望（指数 max 期望=调和数 H_N
  精确恒等式，scipy.stats.chi2 作独立裁判，测试内比较）。
- ``independent_stirrer_samples``：搅拌独立采样数 N_ind = floor(B·Q/f)——
  平均模带宽 Δf ≈ f/Q（IEC 61000-4-21 口径，次级源双源：Hill 文献+IEC
  目录可核，页码 UNVERIFIED 如实）；下限 0、非整数向下取整（可实现的
  独立样本数语义）。
- ``rc_vs_sac_note``：RC ↔ SAC（半电波暗室）发射测量换算**口径文档面**——
  只声明两法可比性条件与换算要素清单，不产数值换算系数（无权威闭式，
  铁律 7 / #122：无基准如实不做）。

物理口径（全 SI）
------------------
* 搅拌良好场假设：腔内场统计各向同性、各分量复高斯（中心极限，模数
  足够多时）。χ² 归一口径：u = |E_i|²/⟨|E_i|²⟩，u ~ χ²(df=2)/2 = Exp(1)。
* Q 上界推导（rms 相量口径，本模块自洽约定）：壁损 P = (Rs/2)∫|H_t|²dS，
  各向同性场下每面 ⟨|H_t|²⟩ = (2/3)⟨|H|²⟩，⟨|H|²⟩ = ⟨|E|²⟩/η²；储能
  W = ε0⟨|E|²⟩V/2 + μ0⟨|H|²⟩V/2 = ε0⟨|E|²⟩V（时间平均，rms 口径均分）；
  Q = ωW/P = ωε0η²·(3V)/(3·Rs·S·(2/3)·...) —— 化简关键一步：Rs = ωμ_wδ/2
  与 δ=√(2/(ωμ_wσ_w))，得 Q = (3/2)·V/(μ_rw·S·δ)，与 Hill/IEC 公开口径
  一致（μ_rw = 壁材相对磁导率）。
* 设计约束：core 叶子层纯标准库+numpy（χ² 用 math 打闭式，不引 scipy——
  测试侧才用 scipy 裁判）；非法输入显式 ValueError；dict 输出 JSON 可
  序列化（有限数）。

出处（双源纪律）
------------------
1. round 文档：研究扩充 round17 §四 EM-8。
2. 原文面：D. A. Hill, "Electromagnetic theory of reverberation chambers",
   NIST TN 1506 (1998)（公开 PDF，公式面口径）；IEC 61000-4-21:2023
   （标准正文收费——只作口径名引用，页码 UNVERIFIED 如实标注）。
   Kostas-Boverie: IEEE T-EMC 33(3) 1991（χ² 统计口径）。
"""
from __future__ import annotations

import math
from typing import Any

__all__ = [
    "C0_M_S",
    "CHI2_STATISTICS_SOURCE",
    "Q_WALL_FORMULA_SOURCE",
    "STIRRER_SAMPLES_SOURCE",
    "chi2_df6_cdf",
    "chi2_df6_pdf",
    "independent_stirrer_samples",
    "max_of_n_exponential_mean",
    "quality_factor_wall_loss",
    "rc_vs_sac_note",
    "skin_depth_wall_m",
    "well_stirred_chi2_cdf",
    "well_stirred_chi2_pdf",
    "well_stirred_chi2_quantile",
    "weyl_mode_count",
]

C0_M_S = 299792458.0

Q_WALL_FORMULA_SOURCE = (
    "Q=(3/2)V/(mu_r S delta)：Hill NIST TN 1506 (1998) 公开 PDF 公式面 + "
    "IEC 61000-4-21 口径名（正文收费，页码 UNVERIFIED，#122 如实）；"
    "本模块 docstring 附能量法自洽推导与结构锚（Q∝f^(1/2)）"
)
CHI2_STATISTICS_SOURCE = (
    "Kostas-Boverie IEEE T-EMC 33(3) 1991（单分量复高斯→|E|2 χ²(df=2)；"
    "三分量 χ²(df=6)）；页码 UNVERIFIED 如实"
)
STIRRER_SAMPLES_SOURCE = (
    "N_ind = B·Q/f：平均模带宽 Δf≈f/Q 口径（IEC 61000-4-21 + Hill 文献"
    "双源口径名；页码 UNVERIFIED，#122 如实）"
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


# ─── Weyl 模式数（与 microwave_heating.weyl_mode_stats 同式，跨模块互证）─────
def weyl_mode_count(volume_m3: Any, f_hz: Any, er: Any = 1.0) -> dict[str, float]:
    """Weyl 渐近模式数 N(f)=8πV(f√εr/c0)³/3（双极化口径）+ 模式密度 + 间距。

    返回 {n_modes, density_per_hz, spacing_hz}。电大腔渐近口径——N<1 时
    如实返回小数（渐近式不截断，语义由调用方解释）。
    """
    v = _positive(volume_m3, "volume_m3")
    f = _positive(f_hz, "f_hz")
    er = _positive(er, "er")
    lam = C0_M_S / (f * math.sqrt(er))
    n = 8.0 * math.pi * v / (3.0 * lam**3)
    density = 8.0 * math.pi * v * er**1.5 * f**2 / C0_M_S**3
    spacing = 1.0 / density if density > 0.0 else math.inf
    return {
        "n_modes": n,
        "density_per_hz": density,
        "spacing_hz": spacing,
    }


def skin_depth_wall_m(f_hz: Any, conductivity_wall_s_per_m: Any,
                      mu_r_wall: Any = 1.0) -> float:
    """壁材趋肤深度 δ = sqrt(2/(ω μ σ))（m）。"""
    f = _positive(f_hz, "f_hz")
    sigma = _positive(conductivity_wall_s_per_m, "conductivity_wall_s_per_m")
    mu_r = _positive(mu_r_wall, "mu_r_wall")
    mu0 = 4.0e-7 * math.pi
    return math.sqrt(2.0 / (2.0 * math.pi * f * mu0 * mu_r * sigma))


def quality_factor_wall_loss(volume_m3: Any, surface_area_m2: Any,
                             f_hz: Any, conductivity_wall_s_per_m: Any,
                             mu_r_wall: Any = 1.0) -> dict[str, float]:
    """搅拌良好腔壁损 Q 上界 Q = (3/2)·V/(μ_rw·S·δ) + 派生量。

    电大腔（f ≫ 最低可用频率 LUF）、无泄漏口径的壁损 Q；孔缝泄漏通道
    使实际 Q 更低——本式是**上界**语义，调用方不得当实测预测用。
    返回 {q_wall, skin_depth_m, delta_over}。
    """
    v = _positive(volume_m3, "volume_m3")
    s = _positive(surface_area_m2, "surface_area_m2")
    f = _positive(f_hz, "f_hz")
    sigma = _positive(conductivity_wall_s_per_m, "conductivity_wall_s_per_m")
    mu_r = _positive(mu_r_wall, "mu_r_wall")
    delta = skin_depth_wall_m(f, sigma, mu_r)
    q = 1.5 * v / (mu_r * s * delta)
    return {"q_wall": q, "skin_depth_m": delta, "mu_r_wall": mu_r}


# ─── 搅拌良好场 χ² 统计（df=2 / df=6）───────────────────────────────────────
def well_stirred_chi2_pdf(u: Any) -> float:
    """归一单分量功率 u=|E_i|²/⟨|E_i|²⟩ 的 pdf：Exp(1)=χ²(2)/2，u≥0。

    p(u) = e^{-u}。
    """
    uu = _nonneg(u, "u")
    return math.exp(-uu)


def well_stirred_chi2_cdf(u: Any) -> float:
    """Exp(1) 的 cdf：1−e^{-u}。"""
    uu = _nonneg(u, "u")
    return 1.0 - math.exp(-uu)


def well_stirred_chi2_quantile(p: Any) -> float:
    """Exp(1) 分位：u_p = −ln(1−p)（p∈[0,1)）。"""
    pp = float(p)
    if not (0.0 <= pp < 1.0):
        raise ValueError(f"p 必须在 [0,1)，实际 {p!r}")
    return -math.log1p(-pp)


def chi2_df6_pdf(x: Any) -> float:
    """χ²(df=6) 的 pdf（三分量能量密度）：x⁴e^{-x/2}/(2³Γ(3))，x≥0。

    Γ(3)=2 → 归一化常数 1/16。
    """
    xx = _nonneg(x, "x")
    if xx == 0.0:
        return 0.0
    return xx * xx * math.exp(-xx / 2.0) / 16.0


def chi2_df6_cdf(x: Any) -> float:
    """χ²(df=6) 的 cdf 闭式：1 − e^{−x/2}(1 + x/2 + x²/8)（Erlang(3,2) 和）。"""
    xx = _nonneg(x, "x")
    return 1.0 - math.exp(-xx / 2.0) * (1.0 + xx / 2.0 + xx * xx / 8.0)


def max_of_n_exponential_mean(n: Any) -> float:
    """N 个独立 Exp(1) 样本最大值的期望 = 调和数 H_N（精确恒等式）。

    E[max] = Σ_{k=1..N} 1/k。指数序统计量标准结果（max-H_N 恒等式
    由 Exp(1) 的 cdf F(u)=1−e^{-u} 与序分布直接积分可得）。
    """
    nn = int(n)
    if nn < 1:
        raise ValueError(f"n 必须为 >=1 整数，实际 {n!r}")
    return math.fsum(1.0 / k for k in range(1, nn + 1))


def independent_stirrer_samples(bandwidth_hz: Any, frequency_hz: Any,
                                q_wall: Any) -> dict[str, float]:
    """带宽 B 内可实现的搅拌独立采样数 N_ind = floor(B·Q/f)。

    口径：平均模带宽 Δf ≈ f/Q（Q 越高模带宽越窄、独立样本越多）；
    返回 {mode_bandwidth_hz, n_independent}。floor 语义 = 可实现的整数
    独立位置数；B·Q/f < 1 时如实给 0（该带宽内无独立样本可言）。
    """
    bw = _nonneg(bandwidth_hz, "bandwidth_hz")
    f = _positive(frequency_hz, "frequency_hz")
    q = _positive(q_wall, "q_wall")
    delta_f = f / q
    n_ind = math.floor(bw / delta_f) if delta_f > 0.0 else 0.0
    return {"mode_bandwidth_hz": delta_f, "n_independent": float(n_ind)}


def rc_vs_sac_note() -> dict[str, str]:
    """RC ↔ SAC 发射测量换算口径文档面（不产数值系数——铁律 7）。

    两法可比性条件与换算要素清单（口径声明，全部为文档语义）：
    - RC 测的是总辐射功率（stirred 模式下与方向/EUT 姿态近似无关）；
      SAC 浬的是特定距离的方向化场强（含地面反射与天线方向图）。
    - 可比性要素：EUT 电尺寸/低频可用性（LUF 与 SAC 低频限）、
      搅拌独立样本数（本模块 independent_stirrer_samples）、天线口径、
      地面反射模型（SAC 侧）。
    - 换算实施路径：功率口径折算（EIRP = P_rad·D_max，SAC 侧由
      场强反演 EIRP 后比对），不做单值经验系数（无权威闭式，#122）。
    """
    return {
        "comparison_statement": (
            "RC=总辐射功率口径（stirred 统计平均，姿态无关）；"
            "SAC=特定距离方向化场强口径（含地面反射）。"
        ),
        "factors": (
            "LUF/EUT 电尺寸; 独立样本数; 天线方向图; 地面反射模型; "
            "EIRP=Prad·Dmax 折算链"
        ),
        "numeric_conversion": (
            "不做单值经验系数（无权威闭式，铁律 7/#122）；"
            "换算经 EIRP 功率口径在消费层实施"
        ),
        "standards_scope": (
            "IEC 61000-4-21（RC 口径名）+ CISPR 16-1-1/CISPR 25（SAC "
            "辐射发射口径名）；标准正文收费，页码 UNVERIFIED 如实"
        ),
    }
