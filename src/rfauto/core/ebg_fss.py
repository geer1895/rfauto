r"""TA-13 EBG/FSS 补单元确定性内核（Jerusalem screen/方环贴片 FSS）
（ge8b Wave B 席 B9，2026-10-03）。

规格：研究扩充 round15 §二·2 TA-13「EBG 蘑菇/
贴片周期单元、FSS 补单元（方环缝/双环带通）」+ 席 B9 任务书「Jerusalem
screen/方环贴片 FSS：LC 谐振闭式+反射相位带（MM-8 AMC 面已合流可互证
不重写）」。

规格边界（#122 如实）
--------------------
- **不注册模板、不重写 MM-8**：蘑菇 AMC 面=core/amc_mushroom.py（已合流），
  本模块只补自由悬浮（无接地）串联 LC 型 FSS 屏的带模型，与 MM-8 共享
  同一套间隙电容/线网电感单源（互证不重写）；
- **EC 初值口径**：稠密栅有效域 g≪D（Luukkonen EC 模型声明域）；绝对
  精度的系统标定（round15 补强项"FSS EC 精度域表 vs PSSFSS 系统标定"）
  是独立立项面，本内核只承诺带心初值+恒等式/极限裁判；
- 斜入射/ TE-TM 极化分解与 Floquet 全波=模板/真机面，不在本内核。

法源与公式（出处逐式；#118 单源纪律）
--------------------
- **间隙电容 C**：metasurface_lut.fss_patch_grid_capacitance_f
  （Luukkonen/Costa arXiv:0705.3548 eq.4，C=(2D/π)ε0εeff·ln(csc(πg/2D))，
  仓内单源；MM-8 amc_gap_capacitance_f 同源复用先例）。
- **线网电感 L**：metasurface_lut.fss_mesh_grid_inductance_h
  （对偶口径 L=μ0·D/(2π)·ln(csc(πw/2D))，仓内单源）——方环四边=感性
  线网段、邻胞缝=容性间隙，串联 LC 谐振是方环缝/十字缝 FSS 的标准
  EC 模型（Marcuvitz 谱论经典口径；**几何因子级偏差如实登记**：
  离散环/十字对理想线网的填充因子修正未单独建模，属 EC 初值口径）。
- **自由悬浮串联 LC 屏**（本模块新增面，损耗忽略）：

      Z_s(ω) = j·(ωL − 1/(ωC))                （串联谐振，f₀ 处 Z_s=0）
      Y_s = 1/Z_s，Y₀ = 1/η₀
      Γ = −Y_s/(Y_s + 2Y₀)，  T = 2Y₀/(Y_s + 2Y₀)

  极限自检：Z_s→∞（缝开路，DC/远带）→ Γ→0、T→1（透明）；f₀ 处
  Z_s→0 → Γ→−1、T→0（全反射带阻）——方环/十字缝 FSS 的带阻反射
  （=带通反射镜 dichroic）标准行为。
- **−3 dB 反射带边**（|T|²=1/2）：Y_s 与 2Y₀ 正交 → |Y_s|=2Y₀ ⇔
  |Z_s|=η₀/2。记 x=ω/ω₀、δ=η₀/(2ω₀L)=η₀/(2√(L/C))：

      x² ∓ δx − 1 = 0 →  x_low=(√(δ²+4)−δ)/2，x_high=(√(δ²+4)+δ)/2
      x_low·x_high=1，分数带宽（倍频域）= x_high−x_low = δ

  与 MM-8 amc_phase_band_hz 的带宽律同构（彼处 R=√(L/C)/η₀ 为接地
  并联 LC 口径；此处 δ=η0/(2√(L/C)) 为悬浮串联口径，R·δ=1/2 恒等——
  两面互证锚，tests 钉）。

独立基准（≥2，tests/unit/test_wave_b_closedforms）
------------------------------------------------
1. 带边闭式 vs |Z_s|=η₀/2 数值求根（互不共享代码路径）；
2. skrf 级联独立回收：shunt(Z_s) ABCD 二端口 S21 数值 −3 dB 交点
   （skrf 独立引擎）；
3. 极限：C→∞（缝闭合）→ f₀→0；L→∞（w→0）→ f₀→0；R·δ=1/2 与
   amc 互证恒等。

单位 SI（H/F/Hz/Ω/m）；e^{−jωt}；core 纯函数零 IO、不注册 calculators 键
（本席纪律 3）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.metasurface_lut import (
    ETA0_OHM,
    fss_mesh_grid_inductance_h,
    fss_patch_grid_capacitance_f,
)

__all__ = [
    "fss_band_edges_hz",
    "fss_design_report",
    "fss_series_lc_impedance",
    "fss_sheet_reflection_coeff",
    "fss_sheet_transmission_coeff",
    "jerusalem_screen_lc",
    "square_loop_fss_lc",
]


def _require_positive(name: str, value: float) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限实数，got {value!r}")
    return v


def _lc_pair(period_m: float, gap_m: float, w_strip_m: float,
             eps_eff: float) -> tuple[float, float]:
    """单元 LC 对（单源复用）：C=贴片栅缝电容、L=线网段电感。"""
    period = _require_positive("period_m", period_m)
    gap = _require_positive("gap_m", gap_m)
    w = _require_positive("w_strip_m", w_strip_m)
    eps = _require_positive("eps_eff", eps_eff)
    if not gap < period:
        raise ValueError(f"要求 gap<period，得 {gap}/{period}")
    if not w < period:
        raise ValueError(f"要求 w_strip<period，得 {w}/{period}")
    c_f = float(fss_patch_grid_capacitance_f(period, gap, eps))
    l_h = float(fss_mesh_grid_inductance_h(period, w))
    return l_h, c_f


def square_loop_fss_lc(period_m: float, gap_m: float, w_strip_m: float,
                       eps_eff: float = 1.0) -> dict[str, float]:
    """方环贴片 FSS 单元 LC（串联谐振初值）。

    几何：周期 D、邻环缘距 g、环带条宽 w_strip（方环=四感性边+四角/
    缘容性缝的串联 LC）；eps_eff=(1+εr)/2 单侧介质加载口径（eq.3 同源）。
    """
    l_h, c_f = _lc_pair(period_m, gap_m, w_strip_m, eps_eff)
    return {"l_h": l_h, "c_f": c_f,
            "f0_hz": 1.0 / (2.0 * math.pi * math.sqrt(l_h * c_f))}


def jerusalem_screen_lc(period_m: float, gap_m: float, w_arm_m: float,
                        eps_eff: float = 1.0) -> dict[str, float]:
    """Jerusalem screen（十字加端帽）单元 LC（串联谐振初值）。

    与方环同一 EC 对偶口径：臂=感性线网段（w_arm）、邻胞端帽缝=容性
    间隙（gap）——十字的端帽加载使实际 C 高于裸缝 EC（几何因子未建模，
    EC 初值口径如实登记；稠密栅域 g≪D）。
    """
    return square_loop_fss_lc(period_m, gap_m, w_arm_m, eps_eff)


def fss_series_lc_impedance(omega_rad_s: float | np.ndarray,
                            l_h: float, c_f: float) -> np.ndarray:
    """悬浮串联 LC 屏表面阻抗 Z_s(ω)=j(ωL−1/(ωC))（Ω；f₀ 处过零）。"""
    lh = _require_positive("l_h", l_h)
    cf = _require_positive("c_f", c_f)
    w = np.asarray(omega_rad_s, dtype=float)
    if np.any(~np.isfinite(w)) or np.any(w <= 0.0):
        raise ValueError("omega_rad_s 必须为正有限实数")
    return np.asarray(1j * (w * lh - 1.0 / (w * cf)))


def fss_sheet_reflection_coeff(omega_rad_s: float | np.ndarray,
                               l_h: float, c_f: float) -> np.ndarray:
    """法向入射反射系数 Γ=−Y_s/(Y_s+2Y₀)（无损 |Γ|=1 恒等式；f₀ 处
    Γ=−1 全反射，远带 Γ→0 透明）。"""
    zs = fss_series_lc_impedance(omega_rad_s, l_h, c_f)
    return -ETA0_OHM / (ETA0_OHM + 2.0 * zs)


def fss_sheet_transmission_coeff(omega_rad_s: float | np.ndarray,
                                 l_h: float, c_f: float) -> np.ndarray:
    """透射系数 T=2Y₀/(Y_s+2Y₀)=2Z_s/(2Z_s+η₀)（|Γ|²+|T|²=1 无损恒等式；
    两种 Y₀/Z_s 写法代数等价，Z_s 形式对 Z_s→∞（无屏透明 T→1）极限
    数值稳定）。"""
    zs = fss_series_lc_impedance(omega_rad_s, l_h, c_f)
    return 2.0 * zs / (2.0 * zs + ETA0_OHM)


def fss_band_edges_hz(l_h: float, c_f: float) -> dict[str, float]:
    """−3 dB 反射带边（|Z_s|=η₀/2）精确闭式 + 互证量 δ/R。

    返回 {f0_hz, f_low_hz, f_high_hz, fractional_bandwidth(=δ),
    delta, impedance_ratio_R}；R=√(L/C)/η₀ 与 MM-8 amc_phase_band_hz
    的带宽律互证恒等 R·δ=1/2（tests 钉）。
    """
    lh = _require_positive("l_h", l_h)
    cf = _require_positive("c_f", c_f)
    delta = ETA0_OHM / (2.0 * math.sqrt(lh / cf))
    ratio_r = math.sqrt(lh / cf) / ETA0_OHM
    root = math.sqrt(delta * delta + 4.0)
    x_low = (root - delta) / 2.0
    x_high = (root + delta) / 2.0
    f0 = 1.0 / (2.0 * math.pi * math.sqrt(lh * cf))
    if abs(x_low * x_high - 1.0) > 1e-12:
        raise ValueError("带边恒等 x_low·x_high=1 破坏（数值异常）")
    return {"f0_hz": f0,
            "f_low_hz": x_low * f0,
            "f_high_hz": x_high * f0,
            "fractional_bandwidth": delta,
            "delta": delta,
            "impedance_ratio_R": ratio_r}


def fss_design_report(period_m: float, gap_m: float, w_strip_m: float,
                      eps_eff: float = 1.0) -> dict[str, Any]:
    """单元一站式：LC → 谐振/带边/互证量（EC 初值口径）。"""
    lc = square_loop_fss_lc(period_m, gap_m, w_strip_m, eps_eff)
    band = fss_band_edges_hz(lc["l_h"], lc["c_f"])
    return {**lc, **band,
            "model": "series_lc_free_sheet_ec_v1",
            "note": "稠密栅 EC 初值口径（g≪D）；绝对精度系统标定"
                    "（PSSFSS/HFSS Floquet）归独立立项面"}
