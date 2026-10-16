"""经典渐变线族（线性/指数/三角剖面）两键（aurora72 A8-B 席域 1，R7 §附加候选
"taper.py+指数渐变" 工程余量成席；aurora_d W3-CORE7 席原位扩展**三角剖面**
（R7 附加候选表"渐变线指数/三角 profile"残项，2026-10-14；#222 triple-grep
证据：triangular_taper 注册键面零命中——指数/线性两剖面 A8-B 已落，三角为
最后残项））。

两键：classic_taper_response（线性/指数/三角阻抗剖面逐频小反射理论 2 路——
闭式（指数 sinc/线性 Ei 指数积分/三角 sinc²）+ 剖面核数值积分交叉互证）/
classic_taper_synthesize（给定 ρ_max@f_min 反解最短长度——|Γ(βL)| 首个
符号变化括根 + brentq 精化，三剖面共用）。

与既有面的边界（#222 triple-grep 证据，2026-10-11 实测）
--------------------------------------------------------
- klopfenstein_taper=**最优 Dolph-Chebyshev 剖面**（skrf.taper.Klopfenstein
  载体 + 微带 MLine 同源宽度实现面）——本族=三**经典教科书剖面**
  （linear/exponential/triangular）纯电气口径（Z 域，不假设线工艺、无宽度
  输出），剖面族不同不并入。
- quarter_wave_transformer/synthesize_multisection_quarter_wave=离散 λ/4
  阶梯变换、t_match/rf_match=集总 L 网络、stub_tuner_*=并联支节调配、
  guanella_tlt_*=串/并复合传输线变压器——均非连续渐变线，不并入。

物理口径（docstring 写死，#1c/#300 出处纪律；#118 锚树见
tests/unit/test_a8b_taper_isolator.py 与 tests/unit/test_aurora_d_core7.py）
--------------------------------------------------------
- 小反射理论（Pozar《Microwave Engineering》§5.9 渐变线变换器节）：
  Γ_in(β) = ∫₀ᴸ K(x)·e^(−2jβx) dx，K(x)=½·d(ln Z)/dx（TEM 均匀口径，
  β=2πf/(v_f·c₀)；渐变线色散/高阶模不在口径，note 如实登记）。
  以下 u=x/L 归一化、δ=ln(z2/z1)。
- **指数剖面** Z(x)=z1·exp(δ·x/L)：K(u)=δ/(2L) 常数 →
  Γ=(δ/2)·e^(−jx)·sinc(x/π)、|Γ|=(|δ|/2)·|sinc(x/π)|（sinc(x)=sin x/x，
  Pozar 式 5.73/5.74）；βL=nπ 处 |Γ|=0（sinc 零点）。
- **线性剖面** Z(x)=z1+kx、k=(z2−z1)/L：K(u)=k/(2Z(x)) → 代换
  u=Z(x) 得 Γ=½·e^(−c·z1)·[Ei(c·z2)−Ei(c·z1)]、c=−2jβ/k（指数积分 Ei
  闭式；scipy.special.expi 复数域，与 mpmath.ei 对照 ≤1e-16 实测）。
- **三角剖面**（W3-CORE7 原位扩展）：d(ln Z)/dx 三角核（两端为零、中心
  峰值）：K(u)=(δ/2L)·4u（u≤½）、(δ/2L)·4(1−u)（u≥½）→ 三角核=两矩形
  核卷积（FT 域 sinc²）::

      Γ = (δ/2)·e^(−jx)·sinc²(x/(2π))，  |Γ| = (|δ|/2)·sinc²(x/(2π))

  （sinc 归一化形；等价展开 Γ=2δ·sin²(x/2)e^(−jx)/x²。）首零 βL=2π
  （指数剖面 π 的两倍=主瓣两倍宽、旁瓣 1/x² 快衰减）；βL→0 阶跃极限
  |δ|/2 与其余两剖面同；|Γ| 在 (0,2π) 严格单调降（sinc 在 (0,1) 单调降，
  综合首根恒 <2π）。剖面闭式：ln Z(u)=ln z1+δ·F(u)、F(u)=2u²（u≤½）、
  1−2(1−u)²（u≥½）（F'=4u/4(1−u)=三角核，Z(0)=z1、Z(1)=z2、Z(½)=√(z1z2)
  几何中点——锚树钉）。
- 公共恒等式：βL→0 极限 |Γ|→|δ|/2（阶跃反射极限，三剖面同）；|Γ(βL)|
  ≤|δ|/2（小反射理论包络上界）；剖面反转（z1↔z2）|Γ| 不变（|Γ| 只依赖
  |δ| 的对称性）。
- 综合反解：|Γ(βL)| 在第一零点内单调下降（指数 (0,π)、三角 (0,2π)；线性
  首根也可能在第一旁瓣谷——实测验证），但 ρ<|Γ(首零⁻)| 时首根在更远的
  旁瓣谷——**统一走 (0,4π] 稠密网格首个变号括根 + brentq 精化**（不赌
  单调段，最小长度=首个变号点）。

出处（Pozar《Microwave Engineering》4th ed. §5.9 Tapered Lines：指数剖面
sinc 闭式与 βL→0 阶跃极限；线性剖面 Ei 闭式与三角剖面 sinc² 闭式=该节同
一小反射积分的代换/三角核积分手续（Collin《Foundations for Microwave
Engineering》2nd ed. 渐变线节同式；三角核 FT=卷积矩形核 sinc² 恒等式为
本仓推导，实现前独立复算：闭式 vs 剖面核 Simpson 积分 ≤1.3e-16、首零
βL=2π 精确、F(½)=½ 几何中点，独立验证轨迹（内部档）；
锚树 tests/unit/test_aurora_d_core7.py 第二路线）；两路互证锚与包络恒等式
为测试侧独立重解）。

守卫：z1/z2>0 且 z1≠z2（z1==z2 步进反射 Γ0=0 渐变无意义，与
klopfenstein_taper 同界）；length_mm>0；freq_ghz 非空且 >0；profile 白
名单 {exponential, linear, triangular}；v_f∈(0,1]；synthesize 的 rho_max>0
且 <|δ|/2（≥ 阶跃极限=零长渐变即可满足，显式拒绝不凑绿）；数值 0.0 合法
（判缺失 is not None，#364④）；无 ``__all__``（公开 API 快照口径）。

接口：纯函数零 IO；math/cmath+numpy+scipy（expi/brentq/simpson）本征；
返回 JSON 可序列化结构（复数不出口，|Γ| 线性+dB 实数面；交叉互证残差
如实登记不凑零）。
"""

from __future__ import annotations

import cmath
import math
from typing import Any

import numpy as np

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

_PROFILES = ("exponential", "linear", "triangular")
_GRID_X_MAX = 4.0 * math.pi  # 综合括根扫描上界（βL）
_GRID_POINTS = 4096


def _validate_impedances(z1_ohm: float, z2_ohm: float,
                         tag: str) -> tuple[float, float]:
    z1 = _finite(z1_ohm, f"{tag}.z1_ohm")
    z2 = _finite(z2_ohm, f"{tag}.z2_ohm")
    if z1 <= 0.0 or z2 <= 0.0:
        raise ValueError(
            f"{tag}: z1_ohm/z2_ohm 必须 >0，得到 ({z1_ohm!r}, {z2_ohm!r})")
    if z1 == z2:
        raise ValueError(
            f"{tag}: z1==z2（步进反射 Γ0=0）——渐变段无意义，显式拒绝"
            "（与 klopfenstein_taper 同界）")
    return z1, z2


def _beta_rad_per_mm(f_ghz: float, v_f: float) -> float:
    return 2.0 * math.pi * f_ghz / (C_MM_GHZ * v_f)


def _sinc(x: float) -> float:
    """归一化 sinc：sinc(x)=sin(πx)/(πx)（x→0 极限 1；纯 math 无 numpy
    标量泄漏）。"""
    if x == 0.0:
        return 1.0
    px = math.pi * x
    return math.sin(px) / px


def _gamma_closed(x_bl: float, z1: float, z2: float,
                  profile: str) -> complex:
    """给定 βL 电长度 x_bl 的闭式 Γ（与频率/长度解耦的纯电长度函数；
    返回纯 python complex——确定性内核零 numpy 标量出口）。"""
    from scipy.special import expi

    if profile == "exponential":
        delta = math.log(z2 / z1)
        return complex((delta / 2.0) * cmath.exp(-1j * x_bl)
                       * _sinc(x_bl / math.pi))
    if profile == "triangular":
        # Γ=(δ/2)e^{−jx}sinc²(x/2π)（三角核=两矩形核卷积的 FT sinc² 恒等）
        delta = math.log(z2 / z1)
        s = _sinc(x_bl / (2.0 * math.pi))
        return complex((delta / 2.0) * cmath.exp(-1j * x_bl) * s * s)
    # 线性剖面：c=−2jβ/k 与 βL=x_bl、k=(z2−z1)/L 联立 → c=−2j·x_bl/(z2−z1)
    c = -2j * x_bl / (z2 - z1)
    return complex(0.5 * cmath.exp(-c * z1)
                   * (expi(c * z2) - expi(c * z1)))


def _gamma_quadrature(x_bl: float, z1: float, z2: float,
                      profile: str, n_points: int) -> complex:
    """剖面核数值积分独立路线：Γ=∫₀¹ K(u/L)·e^(−2j·x_bl·u) du
    （u=x/L 归一化；K 由剖面 Z(x) 解析式数值离散，与闭式无共享手续）。
    三角剖面 K 在 u=½ 有导数尖点：n_points 取奇数使 ½ 恰为采样节点。"""
    from scipy.integrate import simpson

    u = np.linspace(0.0, 1.0, int(n_points))
    if profile == "exponential":
        k_kernel = np.full_like(u, math.log(z2 / z1) / 2.0)
    elif profile == "triangular":
        delta = math.log(z2 / z1)
        k_kernel = np.where(u <= 0.5, 2.0 * delta * u,
                            2.0 * delta * (1.0 - u))
    else:
        k_kernel = 0.5 * (z2 - z1) / (z1 + (z2 - z1) * u)
    integrand = k_kernel * np.exp(-2j * x_bl * u)
    return complex(simpson(integrand, x=u))


def _triangular_z_profile(u: float, z1: float, z2: float) -> float:
    """三角剖面 Z(u)=z1·exp(δ·F(u))，F=2u²（u≤½）、1−2(1−u)²（u≥½）。"""
    delta = math.log(z2 / z1)
    frac = 2.0 * u * u if u <= 0.5 else 1.0 - 2.0 * (1.0 - u) ** 2
    return z1 * math.exp(delta * frac)


@register_calculator(
    "classic_taper_response",
    "经典渐变线频响：线性/指数/三角阻抗剖面逐频小反射理论双路线——闭式（指"
    "数 |Γ|=(|δ|/2)|sinc(βL)| / 线性 Ei 指数积分闭式 / 三角 "
    "|Γ|=(|δ|/2)sinc²(βL/2π) 首零 βL=2π）+剖面核数值积分交叉互证残差；"
    "βL→0 阶跃极限包络 |δ|/2、剖面样本 Z(x)（三角剖面含 Z(½)=√(z1z2) 几何"
    "中点）；TEM 均匀口径（v_f 相速因子），色散/高阶模不在口径",
    (("z1_ohm", "float Ω 起端阻抗（>0）"),
     ("z2_ohm", "float Ω 末端阻抗（>0 且 ≠z1）"),
     ("length_mm", "float mm 渐变段物理长度（>0）"),
     ("freq_ghz", "array GHz 频率轴（>0）"),
     ("profile", "str 剖面白名单 exponential|linear|triangular（缺省 "
      "exponential）"),
     ("v_f", "float 相速因子（0<v_f≤1，缺省 1.0=TEM 空气口径）"),
     ("n_quad", "int 交叉互证数值积分点数 101..200001（缺省 20001，奇数时"
      "三角剖面 u=½ 尖点恰为采样节点）"),
     ("n_profile", "int 剖面样本点数 5..401（缺省 65）")),
    required=("z1_ohm", "z2_ohm", "length_mm", "freq_ghz"),
)
def classic_taper_response(z1_ohm: float, z2_ohm: float, length_mm: float,
                           freq_ghz: list, profile: str = "exponential",
                           v_f: float = 1.0, n_quad: int = 20001,
                           n_profile: int = 65) -> dict[str, Any]:
    tag = "classic_taper_response"
    z1, z2 = _validate_impedances(z1_ohm, z2_ohm, tag)
    if profile not in _PROFILES:
        raise ValueError(
            f"{tag}: profile 须 ∈{{'exponential','linear','triangular'}}，"
            f"得到 {profile!r}")
    length = _finite(length_mm, f"{tag}.length_mm")
    if length <= 0.0:
        raise ValueError(f"{tag}: length_mm 必须 >0，得到 {length_mm!r}")
    v_factor = _finite(v_f, f"{tag}.v_f")
    if not 0.0 < v_factor <= 1.0:
        raise ValueError(f"{tag}: v_f 必须 ∈(0,1]，得到 {v_f!r}")
    nq = int(n_quad)
    if not 101 <= nq <= 200001:
        raise ValueError(f"{tag}: n_quad 须在 101..200001，实际 {n_quad!r}")
    npr = int(n_profile)
    if not 5 <= npr <= 401:
        raise ValueError(f"{tag}: n_profile 须在 5..401，实际 {n_profile!r}")
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError(f"{tag}: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError(f"{tag}: 频率须 >0，得到 {freqs!r}")

    step_limit = abs(math.log(z2 / z1)) / 2.0
    freq_out: list[float] = []
    beta_l_out: list[float] = []
    gamma_mag_out: list[float] = []
    gamma_db_out: list[float] = []
    cross_dev = 0.0
    envelope_ok = True
    for f in freqs:
        x_bl = _beta_rad_per_mm(f, v_factor) * length
        g_closed = _gamma_closed(x_bl, z1, z2, profile)
        g_quad = _gamma_quadrature(x_bl, z1, z2, profile, nq)
        cross_dev = max(cross_dev, abs(g_closed - g_quad))
        mag = abs(g_closed)
        envelope_ok = envelope_ok and mag <= step_limit * (1.0 + 1e-12)
        freq_out.append(f)
        beta_l_out.append(x_bl)
        gamma_mag_out.append(mag)
        gamma_db_out.append(20.0 * math.log10(max(mag, 1e-300)))
    x_norm = np.linspace(0.0, 1.0, npr)
    if profile == "exponential":
        z_profile = [z1 * math.exp((math.log(z2 / z1)) * float(u))
                     for u in x_norm]
    elif profile == "triangular":
        z_profile = [_triangular_z_profile(float(u), z1, z2) for u in x_norm]
    else:
        z_profile = [z1 + (z2 - z1) * float(u) for u in x_norm]
    return {
        "profile": profile,
        "z1_ohm": z1,
        "z2_ohm": z2,
        "impedance_ratio": round(z2 / z1, 12),
        "length_mm": length,
        "v_f": v_factor,
        "freq_ghz": [round(f, 9) for f in freq_out],
        "beta_l": [round(v, 12) for v in beta_l_out],
        "gamma_mag": [round(v, 12) for v in gamma_mag_out],
        "gamma_db": [round(v, 6) for v in gamma_db_out],
        "step_reflection_limit": round(step_limit, 12),
        "envelope_bound_ok": bool(envelope_ok),
        "closed_vs_quadrature_max_dev": round(cross_dev, 15),
        "z_profile_ohm": [round(v, 9) for v in z_profile],
        "x_norm": [round(float(u), 9) for u in x_norm],
        "note": (
            "小反射理论 Γ=∫½·d(lnZ)/dx·e^(−2jβLx/L)dx（TEM 均匀口径，"
            "渐变线色散/高阶模/介质损耗不在口径——v_f=1 空气基准，实际线"
            "工艺按有效相速折算）；闭式（指数 sinc/线性 Ei/三角 sinc²）与"
            "剖面核数值积分双路线，closed_vs_quadrature_max_dev 为互证残差"
            "（实测 1e-15 量级；三角剖面 n_quad 缺省奇数使 u=½ 尖点恰为"
            "采样节点）；βL→0 时 |Γ|→|δ|/2 阶跃极限（包络上界）；三角剖面"
            "首零 βL=2π=指数剖面两倍；与 klopfenstein_taper 边界=最优剖面"
            "+微带宽度实现面不并入"),
        "source": (
            "Pozar《Microwave Engineering》4th ed. §5.9 Tapered Lines"
            "（指数剖面 sinc 闭式/式 5.73-5.74）；线性剖面 Ei 闭式=同节"
            "小反射积分代换 u=Z(x) 的指数积分手续（Collin《Foundations "
            "for Microwave Engineering》渐变线节同式）"),
    }


@register_calculator(
    "classic_taper_synthesize",
    "经典渐变线综合：给定 ρ_max@f_min 反解最短长度——|Γ(βL)|=ρ_max 在 "
    "βL∈(0,4π] 首个变号括根+brentq 精化（三剖面统一，不赌单调段）；βL→"
    "0 阶跃极限 |δ|/2 守卫（ρ≥阶跃极限=零长渐变即可满足，显式拒绝）；"
    "三角剖面首零 βL=2π（|Γ| 在 (0,2π) 单调降，ρ>0 首根恒 <2π）",
    (("z1_ohm", "float Ω 起端阻抗（>0）"),
     ("z2_ohm", "float Ω 末端阻抗（>0 且 ≠z1）"),
     ("f_min_ghz", "float GHz 通带下限频率（>0；综合点）"),
     ("rho_max", "float 通带内允许 |Γ| 上限（>0 且 <|ln(z2/z1)|/2）"),
     ("profile", "str 剖面白名单 exponential|linear|triangular（缺省 "
      "exponential）"),
     ("v_f", "float 相速因子（0<v_f≤1，缺省 1.0）")),
    required=("z1_ohm", "z2_ohm", "f_min_ghz", "rho_max"),
)
def classic_taper_synthesize(z1_ohm: float, z2_ohm: float,
                             f_min_ghz: float, rho_max: float,
                             profile: str = "exponential",
                             v_f: float = 1.0) -> dict[str, Any]:
    from scipy.optimize import brentq

    tag = "classic_taper_synthesize"
    z1, z2 = _validate_impedances(z1_ohm, z2_ohm, tag)
    if profile not in _PROFILES:
        raise ValueError(
            f"{tag}: profile 须 ∈{{'exponential','linear','triangular'}}，"
            f"得到 {profile!r}")
    f_min = _finite(f_min_ghz, f"{tag}.f_min_ghz")
    if f_min <= 0.0:
        raise ValueError(f"{tag}: f_min_ghz 必须 >0，得到 {f_min_ghz!r}")
    rho = _finite(rho_max, f"{tag}.rho_max")
    if rho <= 0.0:
        raise ValueError(f"{tag}: rho_max 必须 >0，得到 {rho_max!r}")
    v_factor = _finite(v_f, f"{tag}.v_f")
    if not 0.0 < v_factor <= 1.0:
        raise ValueError(f"{tag}: v_f 必须 ∈(0,1]，得到 {v_f!r}")

    step_limit = abs(math.log(z2 / z1)) / 2.0
    if rho >= step_limit:
        raise ValueError(
            f"{tag}: rho_max={rho!r} ≥ 阶跃反射极限 |δ|/2={step_limit!r}"
            "——零长渐变即可满足，渐变段无意义，显式拒绝")

    def _g(x_bl: float) -> float:
        return abs(_gamma_closed(x_bl, z1, z2, profile)) - rho

    # 首个变号括根（网格不跳多零点：步长 <π/2，第一旁瓣内单调）
    xs = np.linspace(1e-9, _GRID_X_MAX, _GRID_POINTS)
    x_star: float | None = None
    g_prev = _g(float(xs[0]))
    for i in range(1, _GRID_POINTS):
        g_cur = _g(float(xs[i]))
        if g_prev == 0.0:
            x_star = float(xs[i - 1])
            break
        if g_prev > 0.0 >= g_cur:
            x_star = brentq(_g, float(xs[i - 1]), float(xs[i]),
                            xtol=1e-14, rtol=1e-15, maxiter=200)
            break
        g_prev = g_cur
    if x_star is None:
        raise ValueError(
            f"{tag}: βL∈(0,{_GRID_X_MAX:.3f}) 内 |Γ(βL)| 未降到 rho_max="
            f"{rho!r}（剖面={profile}，|δ|/2={step_limit!r}）——参数组合"
            "超出综合域，显式拒绝")

    beta_min = _beta_rad_per_mm(f_min, v_factor)
    length_mm = x_star / beta_min
    achieved = abs(_gamma_closed(x_star, z1, z2, profile))
    # 通带保证域上界=第一零点（指数 βL=π sinc 零点、三角 βL=2π sinc² 零点、
    # 线性剖面 (0,π) 实测单调——π 档对三角保守成立，2π 档=三角精确零点）
    band_edge = 2.0 * math.pi if profile == "triangular" else math.pi
    # 预览点取第一旁瓣内（|Γ(βL)| 在 (x*,首零) 单调 ≤ρ——三剖面第一零点前
    # 单调下降实测+解析可证；首零后旁瓣可再超 ρ，如实给上界不冒充全带）
    preview: list[dict[str, float]] = []
    for beta_l_pt in (x_star, 0.5 * (x_star + band_edge),
                      band_edge * (1.0 - 1e-9)):
        g = _gamma_closed(beta_l_pt, z1, z2, profile)
        preview.append({"freq_multiple": round(beta_l_pt / x_star, 9),
                        "beta_l": round(beta_l_pt, 12),
                        "gamma_mag": round(abs(g), 12),
                        "gamma_db": round(20.0 * math.log10(
                            max(abs(g), 1e-300)), 6)})
    return {
        "profile": profile,
        "z1_ohm": z1,
        "z2_ohm": z2,
        "impedance_ratio": round(z2 / z1, 12),
        "f_min_ghz": f_min,
        "rho_max": rho,
        "v_f": v_factor,
        "length_mm": round(length_mm, 9),
        "beta_l_at_f_min": round(x_star, 12),
        "step_reflection_limit": round(step_limit, 12),
        "achieved_gamma_mag": round(achieved, 15),
        "achieved_residual": round(abs(achieved - rho), 15),
        "f_passband_max_ghz_estimate": round(
            band_edge / x_star * f_min, 9),
        "response_preview": preview,
        "note": (
            "最短长度口径：|Γ(βL)|=rho_max 的首个变号根（βL∈(0,4π] 稠密"
            "网格+brentq；指数剖面在 (0,π) 单调、三角在 (0,2π) 单调、线性"
            "首根也可能在第一旁瓣谷，统一括根不赌单调段）；通带保证域="
            "βL∈[x*,首零)（f_passband_max_ghz_estimate 即该第一瓣上界估算，"
            "三角剖面首零=2π）；首零后旁瓣包络 1/βL（指数）或 1/βL²（三角）"
            "衰减但峰值可再超 ρ，不冒充全带达标——如实登记；βL→0 阶跃极限"
            "守卫：rho_max≥|δ|/2 显式拒绝（零长即可满足）"),
        "source": (
            "Pozar《Microwave Engineering》4th ed. §5.9 渐变线长度综合"
            "口径（sinc 型方程无闭式逆，数值求根；与 klopfenstein 的 "
            "A=acosh(1/rmax) 最优剖面综合互为对照档）"),
    }
