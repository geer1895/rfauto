"""射频传输线族闭式（微带/CPW/CPWG/带状线/CPS/悬置带线 + 共用底座与锚消费）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .registry import C_MM_GHZ, register_calculator

# ─── 共用底座 ────────────────────────────────────────────────────────────────

def _ad_hoc_stackup(epsilon_r: float, h_mm: float, tand: float):
    """构造临时 Stackup（不落 materials.yaml），复用 synthesis 的 skrf 口径。"""
    from rfauto.core.synthesis import Stackup

    return Stackup(name="ad_hoc", epsilon_r=float(epsilon_r),
                   thickness_mm=float(h_mm), loss_tangent=float(tand))


def _media_z0_eps(media: Any, freq_ghz: float, er_default: float) -> tuple[float, float]:
    """skrf media → (z0_real, eps_eff)。εeff 提取链与 synthesis.forward_z0
    同口径：ep_reff → er_eff → β 反推 → 体介电常数兜底。"""

    z0 = float(np.real(media.z0[0]))
    try:
        eps_eff = float(np.real(media.ep_reff[0]))
    except AttributeError:
        try:
            eps_eff = float(media.er_eff[0])
        except AttributeError:
            try:
                beta = float(np.real(media.beta[0]))
                omega = 2 * math.pi * freq_ghz * 1e9
                eps_eff = (beta * 299792458.0 / omega) ** 2
            except Exception:
                eps_eff = er_default
    return z0, eps_eff


def _lambda_g_mm(freq_ghz: float, eps_eff: float) -> float:
    return C_MM_GHZ / (freq_ghz * math.sqrt(eps_eff))


# ─── 微带 ────────────────────────────────────────────────────────────────────

def _microstrip_media(width_mm: float, freq_ghz: float,
                      epsilon_r: float, h_mm: float, tand: float):
    import skrf

    return skrf.media.MLine(
        frequency=skrf.Frequency(freq_ghz, freq_ghz, 1, unit="GHz"),
        w=width_mm * 1e-3, h=h_mm * 1e-3, ep_r=epsilon_r, tand=tand,
        model="hammerstadjensen",
    )


@register_calculator(
    "microstrip_analysis",
    "微带线分析：线宽 → (Z0, εeff)。skrf HJ 模型",
    (("width_mm", "float mm 导带宽度"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度"),
     ("tand", "float - 损耗正切（默认 0）")),
    required=("width_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def microstrip_analysis(width_mm: float, freq_ghz: float,
                        epsilon_r: float, h_mm: float, tand: float = 0.0) -> dict:
    if h_mm <= 0.0:
        raise ValueError(
            f"微带定义域：h>0，得到 h_mm={h_mm!r}"
            "（h≤0 时 skrf HJ 模型除零/开方定义域错，审查 R1-3）")
    if epsilon_r < 1.0:
        raise ValueError(
            f"微带定义域：εr≥1，得到 epsilon_r={epsilon_r!r}"
            "（εr<1 时 HJ εeff 出非物理 <1 值静默透传——实测 er=0.5 返"
            " eps_eff=0.6483，A-14 勘误补守卫；空气微带不在本模型域）")
    from rfauto.core.synthesis import forward_z0

    z0, eps_eff = forward_z0(width_mm, freq_ghz,
                             _ad_hoc_stackup(epsilon_r, h_mm, tand))
    return {"z0_ohm": round(z0, 2), "eps_eff": round(eps_eff, 4),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


@register_calculator(
    "microstrip_synthesis",
    "微带线综合：目标 Z0 → 线宽（brentq 求逆 + 自洽回代）",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度"),
     ("tand", "float - 损耗正切（默认 0）")),
    required=("z0_ohm", "freq_ghz", "epsilon_r", "h_mm"),
)
def microstrip_synthesis(z0_ohm: float, freq_ghz: float,
                         epsilon_r: float, h_mm: float, tand: float = 0.0) -> dict:
    if z0_ohm <= 0.0 or freq_ghz <= 0.0 or epsilon_r < 1.0 or h_mm <= 0.0:
        raise ValueError(
            f"微带综合定义域：z0>0、freq>0、εr≥1、h>0，得到 "
            f"z0_ohm={z0_ohm!r}、freq_ghz={freq_ghz!r}、"
            f"epsilon_r={epsilon_r!r}、h_mm={h_mm!r}"
            "（非法入参直入 skrf+brentq 裸报 'The function value is "
            "NaN'——A-13 入口域盒守卫，参数回显；与 microstrip_analysis "
            "域守卫同源）")
    from rfauto.core.synthesis import forward_z0, inverse_width

    stackup = _ad_hoc_stackup(epsilon_r, h_mm, tand)
    width_mm, z0_actual, status = inverse_width(z0_ohm, freq_ghz, stackup)
    _, eps_eff = forward_z0(width_mm, freq_ghz, stackup)
    return {"width_mm": round(width_mm, 4), "z0_actual_ohm": round(z0_actual, 2),
            "eps_eff": round(eps_eff, 4), "status": status,
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


@register_calculator(
    "microstrip_lambda_g",
    "微带 λg：给定几何/频率 → εeff、λ0、λg",
    (("width_mm", "float mm 导带宽度"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度")),
    required=("width_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def microstrip_lambda_g(width_mm: float, freq_ghz: float,
                        epsilon_r: float, h_mm: float) -> dict:
    media = _microstrip_media(width_mm, freq_ghz, epsilon_r, h_mm, 0.0)
    z0, eps_eff = _media_z0_eps(media, freq_ghz, epsilon_r)
    return {"eps_eff": round(eps_eff, 4),
            "lambda_0_mm": round(C_MM_GHZ / freq_ghz, 3),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3),
            "z0_ohm": round(z0, 2)}


# ─── CPW ─────────────────────────────────────────────────────────────────────

def _cpw_media(w_mm: float, gap_mm: float, freq_ghz: float,
               epsilon_r: float, h_mm: float, tand: float):
    import skrf

    return skrf.media.CPW(
        frequency=skrf.Frequency(freq_ghz, freq_ghz, 1, unit="GHz"),
        w=w_mm * 1e-3, s=gap_mm * 1e-3, h=h_mm * 1e-3,
        ep_r=epsilon_r, tand=tand,
    )


@register_calculator(
    "cpw_analysis",
    "共面波导分析：(w, gap) → (Z0, εeff)。skrf CPW 准静态模型",
    (("w_mm", "float mm 中心导带宽度"),
     ("gap_mm", "float mm 导带-地缝隙"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度"),
     ("tand", "float - 损耗正切（默认 0）")),
    required=("w_mm", "gap_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def cpw_analysis(w_mm: float, gap_mm: float, freq_ghz: float,
                 epsilon_r: float, h_mm: float, tand: float = 0.0) -> dict:
    if epsilon_r <= 1.0:
        raise ValueError(
            f"CPW 定义域：εr>1，得到 epsilon_r={epsilon_r!r}"
            "（skrf CPW 色散修正含 √(εr−1) 除零，εr≤1 静默返 nan，审查 R1-3；"
            "空气 CPW 不在本模型域）")
    media = _cpw_media(w_mm, gap_mm, freq_ghz, epsilon_r, h_mm, tand)
    z0, eps_eff = _media_z0_eps(media, freq_ghz, epsilon_r)
    return {"z0_ohm": round(z0, 2), "eps_eff": round(eps_eff, 4),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


@register_calculator(
    "cpw_synthesis",
    "共面波导综合：目标 Z0 → 中心导带宽度（固定 gap，brentq 求逆）",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("gap_mm", "float mm 导带-地缝隙"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度")),
    required=("z0_ohm", "gap_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def cpw_synthesis(z0_ohm: float, gap_mm: float, freq_ghz: float,
                  epsilon_r: float, h_mm: float) -> dict:
    from scipy.optimize import brentq

    if (z0_ohm <= 0.0 or gap_mm <= 0.0 or freq_ghz <= 0.0
            or epsilon_r <= 1.0 or h_mm <= 0.0):
        raise ValueError(
            f"CPW 综合定义域：z0>0、gap>0、freq>0、εr>1、h>0，得到 "
            f"z0_ohm={z0_ohm!r}、gap_mm={gap_mm!r}、freq_ghz={freq_ghz!r}、"
            f"epsilon_r={epsilon_r!r}、h_mm={h_mm!r}"
            "（非法入参直入 skrf+brentq 裸报 'The function value is "
            "NaN'——A-15 入口域盒守卫，参数回显；εr≤1 除零机理与 "
            "cpw_analysis 域守卫（审查 R1-3）同源）")

    def objective(w_mm: float) -> float:
        media = _cpw_media(w_mm, gap_mm, freq_ghz, epsilon_r, h_mm, 0.0)
        return _media_z0_eps(media, freq_ghz, epsilon_r)[0] - z0_ohm

    # Z0 随 w 单调递减；扫描找括号，找不到如实报错
    w_lo, w_hi = 0.05, max(10.0, 20.0 * gap_mm)
    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    if z_lo < z0_ohm or z_hi > z0_ohm:
        raise ValueError(
            f"目标 {z0_ohm}Ω 超出可达范围 "
            f"[{z_hi:.1f}, {z_lo:.1f}]Ω（gap={gap_mm}mm 括号扫描）")
    w_mm = brentq(objective, w_lo, w_hi, xtol=1e-6)
    media = _cpw_media(w_mm, gap_mm, freq_ghz, epsilon_r, h_mm, 0.0)
    z_actual, eps_eff = _media_z0_eps(media, freq_ghz, epsilon_r)
    return {"w_mm": round(w_mm, 4), "z0_actual_ohm": round(z_actual, 2),
            "eps_eff": round(eps_eff, 4),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


# ─── CPWG（底接地共面波导，共形映射闭式）─────────────────────────────────────

_EPS0 = 8.8541878128e-12   # F/m（真空介电常数）
_C0_MS = 299792458.0       # m/s（光速）


def _cpwg_ri(w_mm: float, gap_mm: float, h_mm: float,
             epsilon_r: float) -> tuple[float, float]:
    """CPWG 准静态共形映射闭式：(εeff, Z0)。

    几何：中心带 a=w/2、半周期 b=w/2+gap、基板厚 h、底面接地。
    部分电容：C_air=2ε0(r1+r4)、C_tot=2ε0(r1+εr·r4)，其中
      k1 = a/b（上半空间共面映射），
      k4 = tanh(πa/2h)/tanh(πb/2h)（接地介质板映射），
      r = K(k)/K'(k)（椭圆积分比，scipy ellipk(m) 的 m=k²）。
    εeff = C/C_air = (r1+εr·r4)/(r1+r4)；Z0 = 1/(c√(C·C_air))。

    极限自洽（有单测）：h→∞ 退化为无地 CPW 无限厚基板
    （εeff→(1+εr)/2，Z0 与 skrf CPW 同式）；h→0 时 εeff→εr。
    实测锚（#193/#198）：rogers4350b w=4.035 gap=0.2 → 引擎 β 实测
    εeff=3.084 vs 闭式 3.03（−1.6%）；闭式 Z0=18.2Ω → |S11|=−6.56dB
    与冒烟实测 −6.5dB 精确对应（该几何是 18Ω 线，50Ω 是参照系错位）。
    """
    from scipy.special import ellipk

    a = w_mm / 2.0
    b = w_mm / 2.0 + gap_mm
    k1 = a / b
    k4 = (math.tanh(math.pi * a / (2.0 * h_mm))
          / math.tanh(math.pi * b / (2.0 * h_mm)))
    r1 = float(ellipk(k1 * k1)) / float(ellipk(1.0 - k1 * k1))
    r4 = float(ellipk(k4 * k4)) / float(ellipk(1.0 - k4 * k4))
    if not (math.isfinite(r1) and math.isfinite(r4)):
        raise ValueError("CPWG 闭式退化（k→1 数值溢出）：h 相对 w 过薄，"
                         "超出准静态共形映射适用域")
    eps_eff = (r1 + epsilon_r * r4) / (r1 + r4)
    z0 = 1.0 / (2.0 * _EPS0 * _C0_MS * math.sqrt(
        (r1 + epsilon_r * r4) * (r1 + r4)))
    return eps_eff, z0


@register_calculator(
    "cpwg_analysis",
    "底接地共面波导（CPWG）分析：共形映射闭式 (w, gap) → (Z0, εeff)。",
    (("w_mm", "float mm 中心导带宽度"),
     ("gap_mm", "float mm 导带-地缝隙"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度（底接地距离）"),
     ("freq_ghz", "float GHz 频率（可选，给了才返回 λg）")),
    required=("w_mm", "gap_mm", "epsilon_r", "h_mm"),
)
def cpwg_analysis(w_mm: float, gap_mm: float, epsilon_r: float, h_mm: float,
                  freq_ghz: float | None = None) -> dict:
    eps_eff, z0 = _cpwg_ri(w_mm, gap_mm, h_mm, epsilon_r)
    out: dict[str, Any] = {"z0_ohm": round(z0, 2),
                           "eps_eff": round(eps_eff, 4)}
    if freq_ghz:
        out["lambda_g_mm"] = round(_lambda_g_mm(freq_ghz, eps_eff), 3)
    return out


@register_calculator(
    "cpwg_synthesis",
    "底接地共面波导（CPWG）综合：目标 Z0 → 中心带宽度（固定 gap，brentq）",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("gap_mm", "float mm 导带-地缝隙"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度（底接地距离）")),
    required=("z0_ohm", "gap_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def cpwg_synthesis(z0_ohm: float, gap_mm: float, freq_ghz: float,
                   epsilon_r: float, h_mm: float) -> dict:
    from scipy.optimize import brentq

    def objective(w_mm: float) -> float:
        return _cpwg_ri(w_mm, gap_mm, h_mm, epsilon_r)[1] - z0_ohm

    # Z0 随 w 单调递减（细条高阻→宽带低阻）；括号越界如实报错
    w_lo, w_hi = 1e-4, max(10.0, 20.0 * gap_mm)
    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    if z_lo < z0_ohm or z_hi > z0_ohm:
        raise ValueError(
            f"目标 {z0_ohm}Ω 超出可达范围 "
            f"[{z_hi:.1f}, {z_lo:.1f}]Ω（gap={gap_mm}mm 括号扫描）")
    w_mm = brentq(objective, w_lo, w_hi, xtol=1e-7)
    eps_eff, z_actual = _cpwg_ri(w_mm, gap_mm, h_mm, epsilon_r)
    return {"w_mm": round(w_mm, 4), "z0_actual_ohm": round(z_actual, 2),
            "eps_eff": round(eps_eff, 4),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


# ─── 带状线（零厚度对称，椭圆积分共形映射闭式）───────────────────────────────

def _stripline_z0(w_mm: float, b_mm: float, epsilon_r: float) -> float:
    """零厚度对称带状线共形映射精确解：Z0 = 30π/√εr · K(k')/K(k)。

    k = tanh(πw/2b)；K(k)=π/(2·agm(1,k'))、K'(k)=π/(2·agm(1,k))（AGM 恒等式），
    故 Z0 = 30π/√εr / r，r = K(k)/K'(k) 经 _kk_ratio_tanh 稳定计算。

    旧实现直调 scipy ellipk：w/b ≳ 12.1 后 tanh 双精度饱和（k≡1）→
    1−k² 下溢为 0、ellipk(1)=inf → ratio=0 → Z0 静默返 0（本仓审查
    R1-1，runs/review_ge8e/r1_calculators/REPORT.md）；AGM 形态两式数学
    恒等、饱和域不塌（#333 _kk_ratio_tanh 同款先例：k'=sech(x) 直取避免
    1−k² 相消）。极限：w→0 时 r→0 → Z0→∞（细条高阻）、w→∞ 时 r→∞
    → Z0→0（x≥710 cosh 溢出 r=inf → Z0=0 正确极限）。
    """
    x = math.pi * w_mm / (2.0 * b_mm)
    r = _kk_ratio_tanh(x)
    if r == 0.0:
        return math.inf
    return 30.0 * math.pi / (r * math.sqrt(epsilon_r))


@register_calculator(
    "stripline_analysis",
    "对称带状线分析（零厚度闭式，椭圆积分）：(w, b) → Z0",
    (("w_mm", "float mm 中心导带宽度"),
     ("b_mm", "float mm 两接地平面间距"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("freq_ghz", "float GHz 频率（可选，给了才返回 λg）")),
    required=("w_mm", "b_mm", "epsilon_r"),
)
def stripline_analysis(w_mm: float, b_mm: float, epsilon_r: float,
                       freq_ghz: float | None = None) -> dict:
    if w_mm <= 0.0 or b_mm <= 0.0:
        raise ValueError(
            f"带状线定义域：w>0、b>0，得到 w_mm={w_mm!r}/b_mm={b_mm!r}"
            "（w=0 时 Z0→∞ 非有限静默透传，审查 R1-3）")
    if epsilon_r < 1.0:
        raise ValueError(
            f"带状线定义域：εr≥1，得到 epsilon_r={epsilon_r!r}（审查 R1-3）")
    z0 = _stripline_z0(w_mm, b_mm, epsilon_r)
    out: dict[str, Any] = {"z0_ohm": round(z0, 2), "eps_eff": epsilon_r}
    if freq_ghz:
        out["lambda_g_mm"] = round(_lambda_g_mm(freq_ghz, epsilon_r), 3)
    return out


@register_calculator(
    "stripline_synthesis",
    "对称带状线综合（零厚度闭式求逆）：目标 Z0 → w",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("b_mm", "float mm 两接地平面间距"),
     ("epsilon_r", "float - 基板相对介电常数")),
    required=("z0_ohm", "b_mm", "epsilon_r"),
)
def stripline_synthesis(z0_ohm: float, b_mm: float, epsilon_r: float) -> dict:
    from scipy.optimize import brentq

    def objective(w_mm: float) -> float:
        return _stripline_z0(w_mm, b_mm, epsilon_r) - z0_ohm

    w_lo, w_hi = 1e-4 * b_mm, 20.0 * b_mm
    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    if z_lo < z0_ohm or z_hi > z0_ohm:
        raise ValueError(
            f"目标 {z0_ohm}Ω 超出可达范围 [{z_hi:.1f}, {z_lo:.1f}]Ω")
    w_mm = brentq(objective, w_lo, w_hi, xtol=1e-7)
    z_back = _stripline_z0(w_mm, b_mm, epsilon_r)
    # 回代自洽保险带（A-18，siw_synthesis 同款形态）：brentq 解出的 w 回代
    # 正问题须复得目标 Z0（w 域 xtol=1e-7 → Z 域实测残差 ≤~1e-6 rel@z0=300；
    # 1e-4 rel 保险带只在内核真坏（inf/0 饱和域塌缩类）时触发）。
    if not (math.isfinite(z_back)
            and abs(z_back - z0_ohm) <= 1e-4 * z0_ohm):
        raise ValueError("stripline_synthesis: 回代自洽失败（数值内部错误）")
    return {"w_mm": round(w_mm, 5),
            "z0_actual_ohm": round(z_back, 3)}


# ─── CPS（共面带，无地有限厚基板；共形映射部分电容闭式，C9 传输线族 II）───────

def _kk_ratio(k: float) -> float:
    """r(k) = K(k)/K'(k)（scipy ellipk(m) 的 m=k²）；k→0 时 r→0、k→1 时 r→∞。"""
    from scipy.special import ellipk

    return float(ellipk(k * k)) / float(ellipk(1.0 - k * k))


def _cps_ri(w_mm: float, gap_mm: float, h_mm: float,
            epsilon_r: float, corner2d: bool = False) -> tuple[float, float]:
    """CPS（coplanar strips，双带无地）准静态共形映射闭式 + FD 定标：(εeff, Z0)。

    corner2d=True 时叠加角落二维修正（h_eff = γ(εr)·E2(a/h,b/h,εr)·h，见
    cps_corner2d_gamma_factor；a/h<1 与缺省路径逐位一致，缺省 False 保守
    维持定标域内已验证口径）。

    几何：两条等宽带 w 并行，中央缝 gap；a=gap/2（内缘半距）、b=gap/2+w
    （外缘半距）、基板厚 h、基板下方为空气（无地）。
    出处（docs/rf_template_references.md §11.1）：
      · 均匀介质（空气）CPS：Wadell《Transmission Line Design Handbook》
        (1991) p.83 eqs 3.4.6.x —— Z0 = 120π·K(k1)/K'(k1)/√εeff，k1=a/b
        （MathWorks RF PCB Toolbox 官方例 MoM 对拍；与 CPW 互补对偶
        Z_CPS·Z_CPW=η0²/4=(60π)² 自洽：repo CPW 30π·K'/K 同 k）；
        等价 C_air = ε0·K'(k1)/K(k1) = ε0/r1。
      · 有限厚基板：Gupta/Ghione 部分电容技术（同 _cpwg_ri 框架），介质
        超额项用接地板 tanh 映射 k3 = tanh(πa/2h_eff)/tanh(πb/2h_eff)：
        C = ε0/r1 + (εr−1)·ε0/(2·r3)，εeff = C/C_air = 1+(εr−1)·r1/(2·r3)。
      · **FD 定标（2026-09-18 w2f-c9-refs，核心/quasistatic_fd.py 裁判，#118）**：
        裸 tanh 映射（h_eff=h）对无地薄基板系统性偏低——基板下方无地时介质
        场向基板外泄漏，等效于"更厚的接地映射板"：h_eff = γ(εr)·h，
        γ(εr) = 1 + 0.9014·εr^(−0.6361)（εr→∞ 场受限 γ→1，εr=3.66 γ=1.395）。
        定标源：裁判在 εr∈{1.5,2.2,3.0,3.66,4.4,6.15,10.2,12.9}×6 几何
        （w/gap ∈ {2.95/0.5, 0.5/0.5, 1.27/0.508, 1.0/0.2, 4.0/1.0, 0.4/0.1}，
        h=0.508）逐 εr 相对误差最小二乘 γ，再幂律拟合（每档 max|err| ≤0.6%）；
        独立验证族 a/h∈[0.05,1]×b/h∈[1.5,12]（35 点，εr=3.66）max|err| 1.4%、
        rms 0.7%（裸映射 −2.9~−12.4%）；w=s=0.5 h∈[0.15,8] 族 ≤1.7%。
        标称 w=2.95/gap=0.5/h=0.508/εr=3.66：裸 1.5712（−5.7%）→ 定标 1.6761
        vs FD 1.667（Richardson）/收尾批临时 FD ≈1.68。
        **适用域边界（2026-09-18 w2f 后续定标批 ③，b/h 维 FD 复扫，#122 如实）**：
        定标域 a/h≲1 且 b/h≲3 之外（宽带缝角落）γ(εr) 单参数修正**数据不支持**
        ——逐点最优 γ 的增强比 γ_lsq/γ_now 为 (a/h, b/h) 二维曲面（a/h=0.25→3.0
        时 0.97→1.20，固定 a/h 随 b/h 非单调，εr 再混叠），单参数/b/h 一维因子
        拟合残差与效应同量级，不硬凑。实测闭式低估：a/h=2、b/h=6、εr=10.2
        → −2.8%；a/h=3、b/h=6、εr=12.9 → −5.7%（FD 单档裁判，test_cps_template
        钉住该边界）；比此前 refs 注记的"−2~−4%"更负且随 εr 加重。repo CPS
        模板名义 a/h=0.49、b/h=6.3 在定标域内（INFO 门 ≤1.2%）。
        **角落二维修正（2026-09-21 C5 followUp，corner2d=True opt-in）**：a/h≥1
        角落区按 160 点在档 FD 拟合 log E2 全二次面（γ 空间，10 系数，
        LOOCO max 2.13%；修正后角落残差 max 0.40% vs 修正前 −5.77%），
        定标域/系数/复现入口见 cps_corner2d_gamma_factor；缺省 False，
        缺省路径与上面钉住的边界证据表逐位一致。
    极限自洽（有单测，定标不改变）：h→0 εeff→1；h→∞ εeff→(1+εr)/2（Wen
    半空间口径，γ 不影响）；gap→0 Z0→0、gap→∞ Z0→∞；Z0 随 w 单调递减；
    εeff∈(1, εr)。Z0 = 1/(c·√(C·C_air))（L=1/(c²C_air) 准静态恒等式）。
    """
    if w_mm <= 0 or gap_mm <= 0 or h_mm <= 0 or epsilon_r < 1.0:
        raise ValueError("CPS 闭式定义域：w>0、gap>0、h>0、εr≥1")
    a = gap_mm / 2.0
    b = gap_mm / 2.0 + w_mm
    k1 = a / b
    h_eff = h_mm * cps_effective_thickness_factor(epsilon_r)
    if corner2d:
        h_eff *= cps_corner2d_gamma_factor(a / h_mm, b / h_mm, epsilon_r)
    k3 = (math.tanh(math.pi * a / (2.0 * h_eff))
          / math.tanh(math.pi * b / (2.0 * h_eff)))
    r1 = _kk_ratio(k1)
    r3 = _kk_ratio(k3)  # h≪w 时 k3→1、r3→inf（1/inf=0，超额项自然归零）
    if not (math.isfinite(r1) and r1 > 0.0):
        raise ValueError("CPS 闭式退化（k1→0 或 →1 数值溢出）：gap/w 比例"
                         "超出准静态共形映射适用域")
    c_air = 1.0 / r1                       # 以 ε0 为单位
    c_tot = c_air + (epsilon_r - 1.0) / (2.0 * r3)
    eps_eff = c_tot / c_air
    z0 = 1.0 / (_EPS0 * _C0_MS * math.sqrt(c_air * c_tot))
    return eps_eff, z0


#: CPS 有效厚度定标常数 γ(εr) = 1 + C·εr^(−P)（来源见 _cps_ri docstring；
#: 复现：scripts/fd_laplace_tline_referee.py --refit-cps-gamma）
CPS_H_EFF_GAMMA_C = 0.9014
CPS_H_EFF_GAMMA_P = 0.6361

# ── 锚消费（DP-3 第二批改道，df7 锚消费接线）────────────────────────────────
# 公式锚消费走 core/anchors 的活注册表接插点（core 零 IO：provider 由
# infra/anchors_store 导入时反向注册；未注册/任何失败 → None → 走下方原闭式
# ——回退值与锚值逐位相等，零行为变化，#105 best-effort）。
_CPS_GAMMA_ER_ANCHOR_ID = "cps.gamma_er.fdref-v1"
_SIW_W_EFF_ANCHOR_ID = "siw.w_eff.lit-v1"


def _live_anchor_set() -> Any:
    """惰性取活锚注册表（core/anchors 接插点；未注册/失败 → None）。"""
    try:
        from rfauto.core.anchors import live_anchor_set

        return live_anchor_set()
    except Exception:  # best-effort：锚内核任何故障不阻塞闭式主路径（#105）
        return None


def _cps_gamma_er_anchor_value(er: float) -> float | None:
    """cps.gamma_er 公式锚求值（er 已收敛 float；不可解析 → None 走闭式回退）。

    命中条件=hit 且 source=anchor 且非 stale 且值有限；域外
    （er<1.5 或 >12.9）resolve 结构化 fallback → None → 闭式，与改道前逐位同。"""
    anchor_set = _live_anchor_set()
    if anchor_set is None:
        return None
    try:
        got = anchor_set.resolve_anchor(_CPS_GAMMA_ER_ANCHOR_ID, {"er": er})
        value = got.get("value")
    except Exception:  # best-effort（#105）
        return None
    if (got.get("hit") and got.get("source") == "anchor"
            and not got.get("stale")
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))):
        return float(value)
    return None


def _siw_w_eff_anchor_value(w_mm: float, d_mm: float, s_mm: float
                            ) -> float | None:
    """siw.w_eff 公式锚求值（入参已收敛 float；不可解析 → None 走闭式回退）。"""
    anchor_set = _live_anchor_set()
    if anchor_set is None:
        return None
    try:
        got = anchor_set.resolve_anchor(
            _SIW_W_EFF_ANCHOR_ID,
            {"w_mm": w_mm, "d_mm": d_mm, "s_mm": s_mm})
        value = got.get("value")
    except Exception:  # best-effort（#105）
        return None
    if (got.get("hit") and got.get("source") == "anchor"
            and not got.get("stale")
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))):
        return float(value)
    return None


def cps_effective_thickness_factor(epsilon_r: float) -> float:
    """CPS 无地薄基板 tanh 映射的有效厚度因子 γ(εr)=1+C·εr^(−P)（≥1）。

    εr=1 时超额项恒为零（γ 值无关）；εr→∞ γ→1（接地映射趋精确）。
    值源（DP-3 第二批改道）：优先 cps.gamma_er.fdref-v1 公式锚
    （knowledge/anchors.yaml，expr=1 + 0.9014*er**-0.6361，域 er∈[1.5,12.9]）；
    锚不可解析（未注册/域外/失败）回退本闭式——回退值与锚值逐位相等
    （同 op 序，test_anchors_core a3 / test_anchor_wire_df7 钉），零行为变化。"""
    if epsilon_r < 1.0:
        raise ValueError("εr≥1")
    got = _cps_gamma_er_anchor_value(float(epsilon_r))
    if got is not None:
        return got
    return 1.0 + CPS_H_EFF_GAMMA_C * float(epsilon_r) ** (-CPS_H_EFF_GAMMA_P)


#: CPS 角落二维修正常数（2026-09-21 C5 followUp，#333 方法论；定标数据=
#: runs/w2f_rescale_batch/cps_bh_scan.json 160 点 a/h×b/h×εr FD 单档裁判，
#: 复现：scripts/fd_laplace_tline_referee.py --refit-cps-corner2d，侦察与
#: 形状族对比脚本 runs/cps_corner2d_fit/explore_fit.py）。模型（γ 空间，
#: 进 tanh 映射，εr=1 / h→0 / h→∞ 三支极限由框架自动保持）：
#:   log E2 = Σ c·φ，x = a/h − 1，
#:   φ = (1, x, ln(b/h), ln(εr), x², ln²(b/h), ln²(εr),
#:        x·ln(b/h), x·ln(εr), ln(b/h)·ln(εr))
#: 角落区 = a/h ≥ 1（γ(εr) 定标域边界；a/h<1 时 E2 ≡ 1 逐位不动）。
#: 结构对比（leave-one-cell-out，20 格）：线性 4 系数 LOOCO max 6.07% →
#: 加对角二次 7 系数 4.06% → 全二次 10 系数 2.13%；全量拟合后角落残差
#: max 0.40%/rms 0.17%（修正前 −2.8~−5.77%）。定标域：
#:   1.0 ≤ a/h ≤ 3.0、a/h < b/h ≤ 6.0、1.5 ≤ εr ≤ 12.9（FD 扫描网格内；
#:   域外显式拒绝不外推——(a/h=3, b/h≈a/h) 邻域与 b/h>6 外推方向无数据约束）
CPS_CORNER2D_COEFFS = (
    0.07944011580288148,
    0.15367879549434305,
    0.04932249237139794,
    -0.023693621533094955,
    0.003343053804404557,
    -0.04214467442272382,
    0.0005920149590515455,
    -0.025771928077387082,
    -0.022407272476807582,
    0.004118895177757769,
)
CPS_CORNER2D_AH_MIN = 1.0
CPS_CORNER2D_AH_MAX = 3.0
CPS_CORNER2D_BH_MAX = 6.0
CPS_CORNER2D_ER_MIN = 1.5
CPS_CORNER2D_ER_MAX = 12.9


def cps_corner2d_gamma_factor(a_over_h: float, b_over_h: float,
                              epsilon_r: float) -> float:
    """CPS 角落二维修正因子 E2(a/h, b/h, εr)（乘在 γ(εr) 上，opt-in）。

    a/h < 1（γ(εr) 单参数定标域内）恒返回 1.0（逐位不动）；εr = 1 亦恒 1.0
    （均匀空气超额项为零，γ 与本修正对 εeff 均无作用）；a/h ≥ 1 时按
    CPS_CORNER2D_COEFFS 的 log 二次面求值，超出 FD 定标网格显式 ValueError
    （不外推，#122 如实）。消费：_cps_ri(corner2d=True)；
    复现：scripts/fd_laplace_tline_referee.py --refit-cps-corner2d。"""
    if a_over_h < CPS_CORNER2D_AH_MIN or epsilon_r <= 1.0:
        return 1.0
    if (a_over_h > CPS_CORNER2D_AH_MAX or b_over_h > CPS_CORNER2D_BH_MAX
            or b_over_h <= a_over_h
            or epsilon_r < CPS_CORNER2D_ER_MIN or epsilon_r > CPS_CORNER2D_ER_MAX):
        raise ValueError(
            f"CPS 角落二维修正定标域：1.0≤a/h≤{CPS_CORNER2D_AH_MAX}、"
            f"a/h<b/h≤{CPS_CORNER2D_BH_MAX}、"
            f"{CPS_CORNER2D_ER_MIN}≤εr≤{CPS_CORNER2D_ER_MAX}"
            f"（got a/h={a_over_h}, b/h={b_over_h}, εr={epsilon_r}；"
            "域外无 FD 数据约束，不外推）")
    x = a_over_h - CPS_CORNER2D_AH_MIN
    lv, lw = math.log(b_over_h), math.log(epsilon_r)
    e = (CPS_CORNER2D_COEFFS[0]
         + CPS_CORNER2D_COEFFS[1] * x + CPS_CORNER2D_COEFFS[2] * lv
         + CPS_CORNER2D_COEFFS[3] * lw + CPS_CORNER2D_COEFFS[4] * x * x
         + CPS_CORNER2D_COEFFS[5] * lv * lv + CPS_CORNER2D_COEFFS[6] * lw * lw
         + CPS_CORNER2D_COEFFS[7] * x * lv + CPS_CORNER2D_COEFFS[8] * x * lw
         + CPS_CORNER2D_COEFFS[9] * lv * lw)
    return math.exp(e)


@register_calculator(
    "cps_analysis",
    "共面带（CPS，双带无地）分析：共形映射部分电容闭式 (w, gap, h) → (Z0, εeff)。",
    (("w_mm", "float mm 单带宽度（两带等宽）"),
     ("gap_mm", "float mm 两带间缝宽"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度（无地，基板下为空气）"),
     ("freq_ghz", "float GHz 频率（可选，给了才返回 λg）")),
    required=("w_mm", "gap_mm", "epsilon_r", "h_mm"),
)
def cps_analysis(w_mm: float, gap_mm: float, epsilon_r: float, h_mm: float,
                 freq_ghz: float | None = None) -> dict:
    eps_eff, z0 = _cps_ri(w_mm, gap_mm, h_mm, epsilon_r)
    out: dict[str, Any] = {"z0_ohm": round(z0, 2),
                           "eps_eff": round(eps_eff, 4)}
    if freq_ghz:
        out["lambda_g_mm"] = round(_lambda_g_mm(freq_ghz, eps_eff), 3)
    return out


@register_calculator(
    "cps_synthesis",
    "共面带（CPS）综合：目标 Z0 → 单带宽度（固定 gap，brentq 回代自洽）",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("gap_mm", "float mm 两带间缝宽"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度（无地）")),
    required=("z0_ohm", "gap_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def cps_synthesis(z0_ohm: float, gap_mm: float, freq_ghz: float,
                  epsilon_r: float, h_mm: float) -> dict:
    from scipy.optimize import brentq

    def objective(w_mm: float) -> float:
        return _cps_ri(w_mm, gap_mm, h_mm, epsilon_r)[1] - z0_ohm

    # Z0 随 w 单调递减（细带高阻→宽带低阻；k1=gap/(gap+2w)）；括号越界如实报错
    w_lo, w_hi = 1e-4, max(10.0, 20.0 * gap_mm)
    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    if z_lo < 0.0 or z_hi > 0.0:
        raise ValueError(
            f"目标 {z0_ohm}Ω 超出可达范围 "
            f"[{z_hi + z0_ohm:.1f}, {z_lo + z0_ohm:.1f}]Ω（gap={gap_mm}mm 括号扫描）")
    w_mm = brentq(objective, w_lo, w_hi, xtol=1e-7)
    eps_eff, z_actual = _cps_ri(w_mm, gap_mm, h_mm, epsilon_r)
    return {"w_mm": round(w_mm, 4), "z0_actual_ohm": round(z_actual, 2),
            "eps_eff": round(eps_eff, 4),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


# ─── 悬置带线（对称填充：厚 h 基板居中夹带，上下空气隙各 (b−h)/2）───────────

#: SSL（悬置带线）FD 重定标常数（2026-09-18 w2f 后续定标批；裁判=
#: core/quasistatic_fd.py，复现：scripts/fd_laplace_tline_referee.py --refit-ssl-q）。
#: 结构=软最小值（softmin）串联饱和修正的平行份额填充：
#:   εeff = 1 + (Δ^(−p) + D^(−p))^(−1/p)，Δ=(εr−1)·q̃，q̃=q·G
#:   G = 1 + u^μ1·A1·s^a1·(1−s)^b1 + u^μ2·A2·s^a2·(1−s)^b2
#:   D = D0·(1+u)^d1·(4s(1−s))^d2，p = p0+p1·s（u=w/b、s=h/b）
#: q 式把介质份额按"平行份额"（算术）计；实际 slab 与空气隙沿场路径是串联
#: 成分 → εr↑ 时有效份额饱和下降（FD 实测 q_fd 随 εr 单调降），softmin 分母
#: 表达该饱和；(1−s)^b/4s(1−s) 因子保证 s→0/s→1 两端点修正消失（极限精确）。
#: 定标源：6 u×6 s×8 εr=288 点 FD 逐点真值全局 LSQ（fit max|err| 3.84%，
#: 最差点 u=0.1/s=0.5/εr=12.9 窄带高 εr 角落；rms 0.95%）；独立验证族
#: 5u×5s×3εr=75 点（网格外）max|err| 1.94%/rms 0.74%。适用域（#122 如实）：
#: u∈[0.1,1]、s∈[0.0625,0.9]、εr∈[1.5,12.9]；域外为外推（两端点极限仍精确、
#: 全 (u,s,εr) 域单调性经 2001 点/εr 网格验证零违例）。
SSL_Q_G1 = (0.85842, 0.003, 2.38305, -0.21519)    # (A1, a1, b1, mu1)
SSL_Q_G2 = (4.19252, 0.003, 8.57574, 0.1113)      # (A2, a2, b2, mu2)
SSL_D = (31.76642, -1.85399, -0.89951)            # (D0, d1, d2)
SSL_P = (0.17662, 0.73466)                        # (p0, p1)


def _kk_ratio_tanh(x: float) -> float:
    """r = K(k)/K'(k)，k = tanh(x)：经 k' = sech(x) = 1/cosh(x) 无相消计算。

    K(k) = π/(2·agm(1,k'))、K'(k) = π/(2·agm(1,k))（AGM 恒等式），比值无需
    π；k' 直取 1/cosh(x) 避免 1−k² 相消——消除 k→1 的双精度 tanh 饱和地板
    （旧实现 w/h≥5.5 后 q 恒 0，w2f 后续定标批修复；x≥710 cosh 溢出 → r=∞，
    q→0 正确极限）。
    """
    if x <= 0.0:
        return 0.0
    k = math.tanh(x)
    kp = 1.0 / math.cosh(x) if x < 710.0 else 0.0
    if kp <= 0.0:
        return math.inf
    a, b = 1.0, kp                     # agm(1, k')
    while a - b > 1e-15 * a:
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    agm_kp = 0.5 * (a + b)
    a, b = 1.0, k                      # agm(1, k)
    while a - b > 1e-15 * a:
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    return (0.5 * (a + b)) / agm_kp


def _suspended_stripline_ri(w_mm: float, b_mm: float, h_mm: float,
                            epsilon_r: float) -> tuple[float, float]:
    """悬置带线（suspended substrate stripline，基板对称居中）闭式：(εeff, Z0)。

    几何：两接地板间距 b，零厚度带在中面 z=b/2，厚 h 的基板以带为中面对称
    填充 z∈[b/2−h/2, b/2+h/2]，两侧空气隙各 (b−h)/2（0≤h≤b）。
    出处（docs/rf_template_references.md §11）：
      · 两支精确极限锚=repo 零厚度对称带状线共形闭式 _stripline_z0
        （Cohn/Wadell 30π·K'(k)/K(k)/√εr，k=tanh(πw/2b)）：
        h→0 → 空气带状线 (1, _stripline_z0(w,b,1))；
        h→b → 全填充 (εr, _stripline_z0(w,b,εr))。
      · 填充因子基准 q = r(k_b)/r(k_h)，k_b=tanh(πw/2b)、k_h=tanh(πw/2h)
        （b 腔/h 腔共形电容比；_kk_ratio_tanh 稳定计算，旧 tanh 饱和地板撤）。
      · **FD 重定标（2026-09-18 w2f 后续定标批，核心/quasistatic_fd.py 裁判）**：
        裸 q 式把介质份额按平行份额计，中段系统性高估（标称几何 +26%；
        旧"偏低"表出自未过基准的临时 FD 已撤，#300）——softmin 串联饱和
        修正族（常数 SSL_Q_G1/G2/SSL_D/SSL_P，定标与适用域见其注），
        288 点拟合 max|err| 3.84% / 独立验证族 75 点 max|err| 1.94%
        （标称 w=0.731 点 −0.58%）。Z0 = _stripline_z0(w,b,1)/√εeff
        （Z0_air 侧 FD vs Cohn −0.1%，未动）。
    单调性：h↑ → εeff↑（严格，FD 域内 2001 点网格零违例），εeff∈[1, εr]。
    """
    if w_mm <= 0 or b_mm <= 0 or epsilon_r < 1.0:
        raise ValueError("悬置带线闭式定义域：w>0、b>0、εr≥1")
    if h_mm < 0 or h_mm > b_mm:
        raise ValueError(f"悬置带线基板厚 h={h_mm}mm 必须在 [0, b={b_mm}mm] 内"
                         "（基板不得越出接地板腔）")
    if h_mm <= 0.0:
        return 1.0, _stripline_z0(w_mm, b_mm, 1.0)
    if h_mm >= b_mm:
        return epsilon_r, _stripline_z0(w_mm, b_mm, epsilon_r)
    u = w_mm / b_mm
    s = h_mm / b_mm
    a1, b1, c1, mu1 = SSL_Q_G1
    a2, b2, c2, mu2 = SSL_Q_G2
    g = (1.0 + u ** mu1 * a1 * s ** b1 * (1.0 - s) ** c1
         + u ** mu2 * a2 * s ** b2 * (1.0 - s) ** c2)
    r_b = _kk_ratio_tanh(math.pi * u / 2.0)
    r_h = _kk_ratio_tanh(math.pi * u / (2.0 * s))
    q = r_b / r_h if math.isfinite(r_h) and r_h > 0.0 else 0.0
    dd = (epsilon_r - 1.0) * min(q * g, 1.0)
    if dd <= 0.0:                      # 极薄基板数值极限（q→0 精确）
        return 1.0, _stripline_z0(w_mm, b_mm, 1.0)
    d0_, d1_, d2_ = SSL_D
    d_cap = d0_ * (1.0 + u) ** d1_ * (4.0 * s * (1.0 - s)) ** d2_
    p = SSL_P[0] + SSL_P[1] * s
    eps_eff = 1.0 + (dd ** (-p) + d_cap ** (-p)) ** (-1.0 / p)
    z0 = _stripline_z0(w_mm, b_mm, 1.0) / math.sqrt(eps_eff)
    return eps_eff, z0


@register_calculator(
    "suspended_stripline_analysis",
    "悬置带线分析（基板厚 h 居中夹带、腔高 b）：共形电容比闭式 (w, b, h) → (Z0, εeff)",
    (("w_mm", "float mm 中心导带宽度"),
     ("b_mm", "float mm 两接地平面间距（腔高）"),
     ("h_mm", "float mm 基板厚度（0≤h≤b，以带为中面对称填充）"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("freq_ghz", "float GHz 频率（可选，给了才返回 λg）")),
    required=("w_mm", "b_mm", "h_mm", "epsilon_r"),
)
def suspended_stripline_analysis(w_mm: float, b_mm: float, h_mm: float,
                                 epsilon_r: float,
                                 freq_ghz: float | None = None) -> dict:
    eps_eff, z0 = _suspended_stripline_ri(w_mm, b_mm, h_mm, epsilon_r)
    out: dict[str, Any] = {"z0_ohm": round(z0, 2),
                           "eps_eff": round(eps_eff, 4)}
    if freq_ghz:
        out["lambda_g_mm"] = round(_lambda_g_mm(freq_ghz, eps_eff), 3)
    return out


@register_calculator(
    "suspended_stripline_synthesis",
    "悬置带线综合：目标 Z0 → w（固定 b/h，brentq 回代自洽，越界显式报错）",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("b_mm", "float mm 两接地平面间距（腔高）"),
     ("h_mm", "float mm 基板厚度（0≤h≤b）"),
     ("epsilon_r", "float - 基板相对介电常数")),
    required=("z0_ohm", "b_mm", "h_mm", "epsilon_r"),
)
def suspended_stripline_synthesis(z0_ohm: float, b_mm: float, h_mm: float,
                                  epsilon_r: float) -> dict:
    from scipy.optimize import brentq

    def objective(w_mm: float) -> float:
        return _suspended_stripline_ri(w_mm, b_mm, h_mm, epsilon_r)[1] - z0_ohm

    w_lo, w_hi = 1e-4 * b_mm, 20.0 * b_mm
    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    if z_lo < 0.0 or z_hi > 0.0:
        raise ValueError(
            f"目标 {z0_ohm}Ω 超出可达范围 "
            f"[{z_hi + z0_ohm:.1f}, {z_lo + z0_ohm:.1f}]Ω（b={b_mm} h={h_mm}）")
    w_mm = brentq(objective, w_lo, w_hi, xtol=1e-7)
    eps_eff, z_actual = _suspended_stripline_ri(w_mm, b_mm, h_mm, epsilon_r)
    return {"w_mm": round(w_mm, 5), "z0_actual_ohm": round(z_actual, 3),
            "eps_eff": round(eps_eff, 4)}
