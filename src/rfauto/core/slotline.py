"""槽线（slotline）闭式：Janaswamy–Schaubert 曲线拟合式（闭式裁判面）。

权威口径（常数逐个有出处、分段声明有效范围、超范围显式报错不外推）
---------------------------------------------------------------------------
- R. Janaswamy and D. H. Schaubert, "Characteristic Impedance of a Wide Slotline
  on Low-Permittivity Substrates," IEEE Trans. MTT-34(8), pp. 900–902, Aug. 1986。
  开放获取原稿：NASA NTRS N86-30893（UMass 报告 Appendix A，1985-07），式 (8)–(15)；
  同一套式子亦见 R. Janaswamy 博士论文 "Radiation Pattern Analysis of the Tapered
  Slot Antenna"（UMass 1986，NASA NTRS 19870016815）§3.3 式 (3.9)–(3.16)。
  数据来源：谱域 Galerkin（SDA）计算 120 点最小二乘拟合；各段给出平均误差 Av 与
  最大误差 Max（本模块 docstring 逐段照录）。
- 常数双源核对（2026-09-16）：NTRS 两份 OCR 文本 + P. Majumdar & A. K. Verma,
  IJMOT 4(2) 2009 pp.83-89 的重排式（其 0.0599/8.3695 = −0.148+0.0881 与
  0.083695 = 0.0881×0.95 等展开系数逐位闭合）+ NJIT 论文 (Tumialan 1996) 附录
  FORTRAN 源码（εr² √(W/λ0) 项）+ dokumen.pub《Networks and Devices Using Planar
  Transmission Lines》eq (9.4.19)–(9.4.22)（Z4 = 12.48(1+0.18 ln εr) 符号定版）。
- 高介电常数段（9.7 ≤ εr ≤ 20）为 R. Garg & K. C. Gupta, IEEE Trans. MTT-24,
  p.532, 1976（Cohn/Mariani 等效波导模型曲线拟合）——**本模块未实现**（原文
  未取得可双源核对的文本，禁止凭记忆写常数）；同理 Janaswamy–Schaubert 宽槽段
  0.075 < W/λ0 ≤ 1.0 的式 (10)/(11)/(14)/(15) OCR 不可靠亦未实现，调用时显式
  ValueError。

几何/记号
---------
- W：槽宽（金属面上的缝，横向 y 方向）；d：基板厚（本仓库习惯记 h）；εr：基板
  相对介电常数；λ0=c/f 自由空间波长；金属零厚、单面金属、基板下方为空气（开放
  槽线，无背板）。
- 输出：λ'/λ0（槽波长比）、εeff=(λ0/λ')²、β=k0·√εeff、Z0（功率-电压定义
  Z0=|V0|²/(2P)，Janaswamy 式 (1)，与 NGSolve 模场后处理口径一致）。

有效范围（三条同时满足，任一越界 ValueError）
--------------------------------------------
- 0.006 ≤ d/λ0 ≤ 0.06（全部式子共同前提）
- 窄槽段 0.0015 ≤ W/λ0 ≤ 0.075
- εr 段：2.22 ≤ εr ≤ 3.8（式 (8)/(9)）或 3.8 < εr ≤ 9.8（式 (12)/(13)）

各段拟合误差（原文）：(8) Av 0.37% / Max 2.2%；(9) Av 0.67% / Max 2.7%；
(12) Av 0.6% / |Max| 3%（W/d>1 且 εr>6 处）；(13) Av 1.58% / Max 5.4%（W/d>1.67 处）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

C0 = 299792458.0

# 有效域常量（原文声明；模块级导出供模板/脚本复用）
D_OVER_LAMBDA0_RANGE: tuple[float, float] = (0.006, 0.06)
W_OVER_LAMBDA0_NARROW_RANGE: tuple[float, float] = (0.0015, 0.075)
EPS_R_LOW_RANGE: tuple[float, float] = (2.22, 3.8)
EPS_R_MID_RANGE: tuple[float, float] = (3.8, 9.8)

#: 原文各段拟合误差（分数），供调用方设门（闭式自身精度 ~2%）
FIT_ERROR_MAX = {
    "lambda_low": 0.022, "z0_low": 0.027,
    "lambda_mid": 0.03, "z0_mid": 0.054,
}


@dataclass(frozen=True)
class SlotlineResult:
    """一次槽线闭式评估的全部量（SI：β rad/m、Z0 Ω）。"""

    lambda_ratio: float      # λ'/λ0
    eps_eff: float           # (λ0/λ')²
    beta_rad_m: float        # k0·√εeff
    z0_ohm: float
    segment: str             # "low"（2.22–3.8）或 "mid"（3.8–9.8）
    w_over_lambda0: float
    d_over_lambda0: float
    w_over_d: float


def _validate_inputs(w_mm: float, d_mm: float, eps_r: float, freq_ghz: float) -> None:
    for name, val in (("w_mm", w_mm), ("d_mm", d_mm), ("eps_r", eps_r),
                      ("freq_ghz", freq_ghz)):
        v = float(val)
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError(f"slotline: {name} 必须为正有限数，得到 {val!r}")


def slotline_segment(w_mm: float, d_mm: float, eps_r: float, freq_ghz: float) -> str:
    """判定 (W/λ0, d/λ0, εr) 落在哪个已实现分段；越界抛 ValueError（不外推）。

    返回 "low"（2.22 ≤ εr ≤ 3.8）或 "mid"（3.8 < εr ≤ 9.8）。
    """
    _validate_inputs(w_mm, d_mm, eps_r, freq_ghz)
    lam0_mm = C0 / (float(freq_ghz) * 1e9) * 1e3
    w_l = float(w_mm) / lam0_mm
    d_l = float(d_mm) / lam0_mm
    er = float(eps_r)
    lo, hi = D_OVER_LAMBDA0_RANGE
    if not (lo <= d_l <= hi):
        raise ValueError(
            f"slotline: d/λ0={d_l:.5f} 超出 Janaswamy–Schaubert 有效域 [{lo}, {hi}]"
            "（不外推；调整基板厚/频率）")
    lo, hi = W_OVER_LAMBDA0_NARROW_RANGE
    if w_l < lo:
        raise ValueError(
            f"slotline: W/λ0={w_l:.5f} 低于窄槽段下限 {lo}（不外推）")
    if w_l > hi:
        raise ValueError(
            f"slotline: W/λ0={w_l:.5f} 高于窄槽段上限 {hi}——宽槽段式 (10)/(11)/(14)/(15)"
            " 常数未取得双源核对文本，本模块未实现（显式拒绝，不外推）")
    if EPS_R_LOW_RANGE[0] <= er <= EPS_R_LOW_RANGE[1]:
        return "low"
    if EPS_R_MID_RANGE[0] < er <= EPS_R_MID_RANGE[1]:
        return "mid"
    if er > EPS_R_MID_RANGE[1]:
        raise ValueError(
            f"slotline: εr={er} > 9.8——高介电常数段为 Garg–Gupta 1976 式，本模块未实现"
            "（原文常数未取得双源核对文本，显式拒绝）")
    raise ValueError(
        f"slotline: εr={er} < {EPS_R_LOW_RANGE[0]}，低于 Janaswamy–Schaubert 拟合下限"
        "（不外推）")


def _lambda_ratio_low(w_d: float, d_l: float, er: float) -> float:
    """式 (8)：2.22 ≤ εr ≤ 3.8，0.0015 ≤ W/λ0 ≤ 0.075（Av 0.37%，Max 2.2%）。

    λ'/λ0 = 1.045 − 0.365 ln εr + 6.3 (W/d) εr^0.945 / (238.64 + 100 W/d)
            − [0.148 − 8.81 (εr + 0.95) / (100 εr)] ln(d/λ0)
    """
    ln_er = math.log(er)
    return (1.045 - 0.365 * ln_er
            + 6.3 * w_d * er ** 0.945 / (238.64 + 100.0 * w_d)
            - (0.148 - 8.81 * (er + 0.95) / (100.0 * er)) * math.log(d_l))


def _z0_low(w_d: float, w_l: float, d_l: float, er: float) -> float:
    """式 (9)：2.22 ≤ εr ≤ 3.8，0.0015 ≤ W/λ0 ≤ 0.075（Av 0.67%，Max 2.7%）。

    Z0 = 60 + 3.69 sin[(εr − 2.22)π/2.36] + 133.5 ln(10 εr) √(W/λ0)
         + 2.81 [1 − 0.011 εr (4.48 + ln εr)] (W/d) ln(100 d/λ0)
         + 131.1 (1.028 − ln εr) √(d/λ0)
         + 12.48 (1 + 0.18 ln εr) (W/d) / √(εr − 2.06 + 0.85 (W/d)²)
    """
    ln_er = math.log(er)
    return (60.0
            + 3.69 * math.sin((er - 2.22) * math.pi / 2.36)
            + 133.5 * math.log(10.0 * er) * math.sqrt(w_l)
            + 2.81 * (1.0 - 0.011 * er * (4.48 + ln_er)) * w_d * math.log(100.0 * d_l)
            + 131.1 * (1.028 - ln_er) * math.sqrt(d_l)
            + 12.48 * (1.0 + 0.18 * ln_er) * w_d
            / math.sqrt(er - 2.06 + 0.85 * w_d * w_d))


def _lambda_ratio_mid(w_d: float, w_l: float, d_l: float, er: float) -> float:
    """式 (12)：3.8 ≤ εr ≤ 9.8，0.0015 ≤ W/λ0 ≤ 0.075（Av 0.6%，|Max| 3%）。

    λ'/λ0 = 0.9217 − 0.277 ln εr + 0.0322 (W/d) √(εr / (W/d + 0.435))
            − 0.01 ln(d/λ0) [4.6 − 3.65 / (εr² √(W/λ0) (9.06 − 100 W/λ0))]
    """
    return (0.9217 - 0.277 * math.log(er)
            + 0.0322 * w_d * math.sqrt(er / (w_d + 0.435))
            - 0.01 * math.log(d_l)
            * (4.6 - 3.65 / (er * er * math.sqrt(w_l) * (9.06 - 100.0 * w_l))))


def _z0_mid(w_d: float, w_l: float, d_l: float, er: float) -> float:
    """式 (13)：3.8 ≤ εr ≤ 9.8，0.0015 ≤ W/λ0 ≤ 0.075（Av 1.58%，Max 5.4%）。

    Z0 = 73.6 − 2.15 εr + (638.9 − 31.37 εr)(W/λ0)^0.6
         + (36.23 √(εr² + 41) − 225) (W/d) / (W/d + 0.876 εr − 2)
         + 0.51 (εr + 2.12)(W/d) ln(100 d/λ0) − 0.753 εr (d/λ0) / √(W/λ0)
    """
    return (73.6 - 2.15 * er
            + (638.9 - 31.37 * er) * w_l ** 0.6
            + (36.23 * math.sqrt(er * er + 41.0) - 225.0) * w_d / (w_d + 0.876 * er - 2.0)
            + 0.51 * (er + 2.12) * w_d * math.log(100.0 * d_l)
            - 0.753 * er * d_l / math.sqrt(w_l))


def slotline_closed_form(w_mm: float, d_mm: float, eps_r: float,
                         freq_ghz: float) -> SlotlineResult:
    """槽线闭式主入口：分段判定 → λ'/λ0、εeff、β、Z0（超范围 ValueError）。"""
    seg = slotline_segment(w_mm, d_mm, eps_r, freq_ghz)
    f_hz = float(freq_ghz) * 1e9
    lam0_m = C0 / f_hz
    w_l = float(w_mm) * 1e-3 / lam0_m
    d_l = float(d_mm) * 1e-3 / lam0_m
    w_d = float(w_mm) / float(d_mm)
    er = float(eps_r)
    if seg == "low":
        ratio = _lambda_ratio_low(w_d, d_l, er)
        z0 = _z0_low(w_d, w_l, d_l, er)
    else:
        ratio = _lambda_ratio_mid(w_d, w_l, d_l, er)
        z0 = _z0_mid(w_d, w_l, d_l, er)
    if not (0.0 < ratio < 1.0):
        raise ValueError(
            f"slotline: 闭式给出非物理 λ'/λ0={ratio:.4f}（应在 (0,1)），输入 "
            f"W={w_mm} d={d_mm} εr={eps_r} f={freq_ghz}GHz——拒绝输出")
    eps_eff = 1.0 / (ratio * ratio)
    k0 = 2.0 * math.pi * f_hz / C0
    return SlotlineResult(lambda_ratio=ratio, eps_eff=eps_eff,
                          beta_rad_m=k0 * math.sqrt(eps_eff), z0_ohm=z0,
                          segment=seg, w_over_lambda0=w_l, d_over_lambda0=d_l,
                          w_over_d=w_d)


def slotline_lambda_ratio(w_mm: float, d_mm: float, eps_r: float, freq_ghz: float) -> float:
    """λ'/λ0（槽波长/自由空间波长）。"""
    return slotline_closed_form(w_mm, d_mm, eps_r, freq_ghz).lambda_ratio


def slotline_eps_eff(w_mm: float, d_mm: float, eps_r: float, freq_ghz: float) -> float:
    """有效介电常数 εeff = (λ0/λ')²。"""
    return slotline_closed_form(w_mm, d_mm, eps_r, freq_ghz).eps_eff


def slotline_z0(w_mm: float, d_mm: float, eps_r: float, freq_ghz: float) -> float:
    """特性阻抗 Z0（Ω，功率-电压定义）。"""
    return slotline_closed_form(w_mm, d_mm, eps_r, freq_ghz).z0_ohm


def slotline_beta(w_mm: float, d_mm: float, eps_r: float, freq_ghz: float) -> float:
    """相位常数 β = 2πf√εeff/c（rad/m）。"""
    return slotline_closed_form(w_mm, d_mm, eps_r, freq_ghz).beta_rad_m


def slotline_guide_wavelength_mm(w_mm: float, d_mm: float, eps_r: float,
                                 freq_ghz: float) -> float:
    """槽波长 λ' = (λ'/λ0)·λ0（mm）。"""
    r = slotline_closed_form(w_mm, d_mm, eps_r, freq_ghz)
    return r.lambda_ratio * C0 / (float(freq_ghz) * 1e9) * 1e3
