"""鳍线渐变过渡族两键（aurora_e W2-S9，K2 残差面，2026-10-18）。

**范围声明（#222 triple-grep + 文献可达性核查，2026-10-18）**：

- 鳍线**基模等效**档（Meier 1974 有效介电常数/阻抗经验式、Sharma-Hoefer
  1983（IEEE MTT-31(2):199-200）经验系数式）**未落地**：公开可达面只有
  文献引用与图例（OUADI 2007 MoL 全波、Yassin 2008 过渡设计），系数原文
  非公开可达——硬编码记忆系数即伪造（#122 如实原则），该档如实放弃，
  留待拿到原文系数表再立键。
- 本族落的是 K2 的**渐变过渡面**（任务口径"鳍线-波导过渡的渐变段长度
  估算（指数/线性渐变）"）：鳍线渐变段是**波导内 E 面结构**，波以导波
  β 传播——既有渐变线族 classic_taper_response/synthesize（TEM/微带口径，
  v_f∈(0,1] 守卫）与 klopfenstein_taper（微带宽度实现面）在结构上排除
  v_p>c 的波导档，本族补齐。

物理口径（docstring 写死，#1c/#300/#122 出处纪律）
--------------------------------------------------
- 相位常数模型（**声明近似档，empirical 级**）：β = k0·sqrt(εeff)·
  sqrt(1−(fc10/f)²)，fc10 = c0/(2a)（TE10 截止恒等式，与 core/rwg_mmt
  同口径）；εeff 缺省 1.0 = 未加载 TE10 导波口径，实际鳍线 εeff 介于 1
  与介质填充值之间（Meier 档未落地，见上），调用方可传 epsilon_eff 精化
  ——该参数属半经验输入，empirical 性质如实声明。
- 剖面反射理论（**精确闭式，共享单源**）：小反射理论
  Γ = ∫½·d(lnZ)/dx·e^(−2jβx)dx（Pozar 4th ed §5.9）——指数剖面 sinc 闭
  式 / 线性剖面 Ei 指数积分闭式，经 core/calc_families/taper_classic 的
  ``_gamma_closed``/``_gamma_quadrature`` 单源复用（不复制公式；该文件
  已含闭式 vs 剖面核数值积分双路线与 Collin 同式出处）。
- f/fc10 < 1.05 显式拒绝（截止附近 β→0、λg 发散，bethe_hole_coupler 同
  界）；z1/z2>0 且 z1≠z2（阶跃反射 Γ0=0 渐变无意义，classic_taper 同界）；
  profile 白名单 {exponential, linear}（三角剖面属 TEM 族既有件不重复）。

锚（#118 双来源）
------------------
1. β 独立来源：εeff=1 时 β·a 与 rwg_mmt TE10 口径互证（测试侧独立复算
   2π·sqrt((f/fc)²−1)·(a/λ0) 恒等）；
2. 剖面互证：闭式 vs ``_gamma_quadrature`` 剖面核数值积分残差（1e-15 量
   级，taper_classic 同款双路线）；
3. βL→0 阶跃极限 |δ|/2 包络、L=λg/2 sinc 零点（指数剖面）；
4. 综合→响应回收：synthesize 的 L 回代 response 复现 rho_max（自洽）。

无 ``__all__``（公开 API 快照口径，taper_classic.py 先例）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .registry import C_MM_GHZ, register_calculator
from .taper_classic import _gamma_closed, _gamma_quadrature

_FINLINE_PROFILES = ("exponential", "linear")
_F_OVER_FC_MIN = 1.05  # 截止附近显式拒绝下界（β→0 λg 发散；bethe 同界）
_GRID_X_MAX = 6.0 * math.pi  # 综合括根扫描上界（βL；波导 β 小于 TEM，扫描窗放宽）
_GRID_POINTS = 4096

_C_LIGHT = 299792458.0  # m/s（SI 定义值；与 rw_tables.C0 同值）


def _finline_beta_rad_per_mm(
    f_ghz: float, a_mm: float, epsilon_eff: float
) -> float:
    """鳍线渐变段相位常数 [rad/mm]（声明近似档，见模块 docstring）。"""
    f_hz = f_ghz * 1e9
    fc_hz = _C_LIGHT / (2.0 * a_mm * 1e-3)
    k0_rad_per_mm = 2.0 * math.pi * f_ghz / C_MM_GHZ
    return k0_rad_per_mm * math.sqrt(epsilon_eff) * math.sqrt(
        1.0 - (fc_hz / f_hz) ** 2)


def _validate_common(
    z1_ohm: float, z2_ohm: float, profile: str, tag: str
) -> tuple[float, float]:
    z1 = float(z1_ohm)
    z2 = float(z2_ohm)
    if not (math.isfinite(z1) and math.isfinite(z2)) or z1 <= 0 or z2 <= 0:
        raise ValueError(
            f"{tag}: z1_ohm/z2_ohm 必须 >0 有限，得到 ({z1_ohm!r}, {z2_ohm!r})")
    if z1 == z2:
        raise ValueError(
            f"{tag}: z1==z2（阶跃反射 Γ0=0）——渐变段无意义，显式拒绝"
            "（classic_taper 同界）")
    if profile not in _FINLINE_PROFILES:
        raise ValueError(
            f"{tag}: profile 须 ∈{{'exponential','linear'}}，得到 {profile!r}")
    return z1, z2


def _resolve_housing(
    wr_name: str | None, a_mm: float | None, b_mm: float | None, tag: str,
) -> tuple[float, float, str | None]:
    """波导尺寸解析：wr_name 走 rw_tables 单源，或显式 a/b；二者恰居其一。"""
    if wr_name is not None and (a_mm is not None or b_mm is not None):
        raise ValueError(
            f"{tag}: wr_name 与 a_mm/b_mm 只能二选一（避免口径冲突）")
    if wr_name is not None:
        from rfauto.core.rw_tables import wr_lookup

        try:
            rec = wr_lookup(wr_name)
        except KeyError as exc:
            # 未知名转显式 ValueError（run_calculator 信封只译 ValueError；
            # bethe_hole 同类守卫口径"未知名显式拒绝"）
            raise ValueError(str(exc)) from None
        return rec.a_mm, rec.b_mm, rec.wr_name
    if a_mm is None or b_mm is None:
        raise ValueError(
            f"{tag}: 须给 wr_name（WR 型号，rw_tables 单源）或同时给 "
            "a_mm/b_mm（显式宽窄边）")
    a = float(a_mm)
    b = float(b_mm)
    if not (math.isfinite(a) and a > 0.0 and math.isfinite(b) and b > 0.0):
        raise ValueError(
            f"{tag}: a_mm/b_mm 必须为正有限数，得到 a={a_mm!r}, b={b_mm!r}")
    return a, b, None


def _f_guard(f_ghz: float, a_mm: float, tag: str) -> float:
    f_val = float(f_ghz)
    if not math.isfinite(f_val) or f_val <= 0.0:
        raise ValueError(f"{tag}: freq_ghz 必须 >0 有限，得到 {f_ghz!r}")
    fc_ghz = _C_LIGHT / (2.0 * a_mm * 1e-3) / 1e9
    if f_val < _F_OVER_FC_MIN * fc_ghz:
        raise ValueError(
            f"{tag}: f={f_val:g} GHz 距 TE10 截止 {fc_ghz:.4f} GHz 不足 "
            f"{_F_OVER_FC_MIN:g}×（截止附近 β→0 λg 发散，显式拒绝）")
    return f_val


def _epsilon_eff_guard(epsilon_eff: float | None, tag: str) -> float:
    if epsilon_eff is None:
        return 1.0
    val = float(epsilon_eff)
    if not math.isfinite(val) or val < 1.0:
        raise ValueError(
            f"{tag}: epsilon_eff 必须 >=1.0 有限（波导加载下限=空气），"
            f"得到 {epsilon_eff!r}")
    return val


@register_calculator(
    "finline_taper_response",
    "鳍线-波导过渡渐变段频响（K2 渐变过渡面）：指数/线性阻抗剖面在**波导 "
    "TE10 导波 β** 下的小反射理论响应——β=k0·sqrt(εeff)·sqrt(1−(fc/f)²)"
    "（声明近似档：εeff 缺省 1=未加载 TE10，可传 epsilon_eff 精化；鳍线"
    "基模等效 Meier/Sharma-Hoefer 经验档系数非公开可达未落地、如实放弃）；"
    "剖面闭式（指数 sinc/线性 Ei）与剖面核数值积分交叉互证残差；βL→0 "
    "阶跃极限 |δ|/2 包络。与 classic_taper_*（TEM/微带口径 v_f≤1）的分界"
    "=波导 v_p>c 档",
    (("wr_name", "str - WR 波导型号（如 'WR-28'，rw_tables 单源；与 "
      "a_mm/b_mm 二选一）"),
     ("a_mm", "float mm 波导宽边内尺寸（显式口径，须与 b_mm 同给）"),
     ("b_mm", "float mm 波导窄边内尺寸"),
     ("z1_ohm", "float Ω 渐变段波导端阻抗（鳍线隙缝端，>0）"),
     ("z2_ohm", "float Ω 渐变段平面端阻抗（如 50Ω，>0 且 ≠z1）"),
     ("length_mm", "float mm 渐变段物理长度（>0）"),
     ("freq_ghz", "array GHz 频率轴（>0 且 >1.05·fc10）"),
     ("profile", "str 剖面白名单 exponential|linear（缺省 exponential）"),
     ("epsilon_eff", "float - 鳍线有效介电常数精化（>=1，缺省 1.0=未加载 "
      "TE10；半经验输入，empirical 如实声明）"),
     ("n_quad", "int 交叉互证数值积分点数 101..200001（缺省 20001）")),
    required=("z1_ohm", "z2_ohm", "length_mm", "freq_ghz"),
)
def finline_taper_response(
    z1_ohm: float,
    z2_ohm: float,
    length_mm: float,
    freq_ghz: list,
    wr_name: str | None = None,
    a_mm: float | None = None,
    b_mm: float | None = None,
    profile: str = "exponential",
    epsilon_eff: float | None = None,
    n_quad: int = 20001,
) -> dict[str, Any]:
    tag = "finline_taper_response"
    z1, z2 = _validate_common(z1_ohm, z2_ohm, profile, tag)
    length = float(length_mm)
    if not math.isfinite(length) or length <= 0.0:
        raise ValueError(f"{tag}: length_mm 必须 >0 有限，得到 {length_mm!r}")
    eps_eff = _epsilon_eff_guard(epsilon_eff, tag)
    nq = int(n_quad)
    if not 101 <= nq <= 200001:
        raise ValueError(f"{tag}: n_quad 须在 101..200001，实际 {n_quad!r}")
    a_val, _b_val, wr_used = _resolve_housing(wr_name, a_mm, b_mm, tag)
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError(f"{tag}: freq_ghz 不能为空")
    fc_ghz = _C_LIGHT / (2.0 * a_val * 1e-3) / 1e9
    for f in freqs:
        _f_guard(f, a_val, tag)

    step_limit = abs(math.log(z2 / z1)) / 2.0
    freq_out: list[float] = []
    beta_l_out: list[float] = []
    gamma_mag_out: list[float] = []
    gamma_db_out: list[float] = []
    cross_dev = 0.0
    envelope_ok = True
    for f in freqs:
        x_bl = _finline_beta_rad_per_mm(f, a_val, eps_eff) * length
        g_closed = _gamma_closed(x_bl, z1, z2, profile)
        g_quad = _gamma_quadrature(x_bl, z1, z2, profile, nq)
        cross_dev = max(cross_dev, abs(g_closed - g_quad))
        mag = abs(g_closed)
        envelope_ok = envelope_ok and mag <= step_limit * (1.0 + 1e-12)
        freq_out.append(f)
        beta_l_out.append(x_bl)
        gamma_mag_out.append(mag)
        gamma_db_out.append(20.0 * math.log10(max(mag, 1e-300)))
    lam_g_mm = [
        2.0 * math.pi / _finline_beta_rad_per_mm(f, a_val, eps_eff)
        for f in freq_out
    ]
    return {
        "profile": profile,
        "z1_ohm": z1,
        "z2_ohm": z2,
        "impedance_ratio": round(z2 / z1, 12),
        "length_mm": length,
        "a_mm": a_val,
        "b_mm": _b_val,
        "wr_used": wr_used,
        "epsilon_eff": eps_eff,
        "fc10_ghz": round(fc_ghz, 9),
        "freq_ghz": [round(f, 9) for f in freq_out],
        "beta_rad_per_mm": [
            round(_finline_beta_rad_per_mm(f, a_val, eps_eff), 12)
            for f in freq_out
        ],
        "lam_g_mm": [round(v, 9) for v in lam_g_mm],
        "beta_l": [round(v, 12) for v in beta_l_out],
        "gamma_mag": [round(v, 12) for v in gamma_mag_out],
        "gamma_db": [round(v, 6) for v in gamma_db_out],
        "step_reflection_limit": round(step_limit, 12),
        "envelope_bound_ok": bool(envelope_ok),
        "closed_vs_quadrature_max_dev": round(cross_dev, 15),
        "note": (
            "β=k0·sqrt(εeff)·sqrt(1−(fc10/f)²) 为声明近似档（εeff 缺省 1="
            "未加载 TE10；鳍线实际 εeff 介于 1 与介质填充值之间，Meier/"
            "Sharma-Hoefer 经验档系数非公开可达未落地——如实放弃，调用方"
            "可传 epsilon_eff 精化）；剖面小反射闭式与剖面核数值积分双路"
            "线复用 taper_classic 单源（closed_vs_quadrature_max_dev 为互"
            "证残差，实测 1e-15 量级）；βL→0 时 |Γ|→|δ|/2 阶跃极限（包络"
            "上界）；渐变线色散/高阶模不在口径"),
        "source": (
            "剖面：Pozar《Microwave Engineering》4th ed. §5.9（经 "
            "taper_classic 单源复用）；波导 β：TE10 导波恒等式 β=k0·"
            "sqrt(1−(fc/f)²)（Collin《Foundations for Microwave "
            "Engineering》，与 core/rwg_mmt 同口径）；鳍线过渡语境："
            "Meier 1974（MTT-22:1209-1216）/ Yassin 2008（ELEC LETT 44）"),
    }


@register_calculator(
    "finline_taper_length",
    "鳍线-波导过渡渐变段长度综合（K2 渐变过渡面）：给定 ρ_max@f_min 反解"
    "最短长度——|Γ(βL)|=rho_max 在 βL∈(0,6π] 首个变号括根+brentq 精化"
    "（β 为波导 TE10 导波口径，同 finline_taper_response 声明近似档）；"
    "ρ≥|δ|/2 阶跃极限显式拒绝；指数剖面 (0,π) 单调零点 βL=π",
    (("wr_name", "str - WR 波导型号（与 a_mm/b_mm 二选一）"),
     ("a_mm", "float mm 波导宽边内尺寸（须与 b_mm 同给）"),
     ("b_mm", "float mm 波导窄边内尺寸"),
     ("z1_ohm", "float Ω 渐变段波导端阻抗（>0）"),
     ("z2_ohm", "float Ω 渐变段平面端阻抗（>0 且 ≠z1）"),
     ("f_min_ghz", "float GHz 通带下限频率（>1.05·fc10；综合点）"),
     ("rho_max", "float 通带内允许 |Γ| 上限（>0 且 <|ln(z2/z1)|/2）"),
     ("profile", "str 剖面白名单 exponential|linear（缺省 exponential）"),
     ("epsilon_eff", "float - 鳍线有效介电常数精化（>=1，缺省 1.0）")),
    required=("z1_ohm", "z2_ohm", "f_min_ghz", "rho_max"),
)
def finline_taper_length(
    z1_ohm: float,
    z2_ohm: float,
    f_min_ghz: float,
    rho_max: float,
    wr_name: str | None = None,
    a_mm: float | None = None,
    b_mm: float | None = None,
    profile: str = "exponential",
    epsilon_eff: float | None = None,
) -> dict[str, Any]:
    from scipy.optimize import brentq

    tag = "finline_taper_length"
    z1, z2 = _validate_common(z1_ohm, z2_ohm, profile, tag)
    rho = float(rho_max)
    if not math.isfinite(rho) or rho <= 0.0:
        raise ValueError(f"{tag}: rho_max 必须 >0 有限，得到 {rho_max!r}")
    eps_eff = _epsilon_eff_guard(epsilon_eff, tag)
    a_val, _b_val, wr_used = _resolve_housing(wr_name, a_mm, b_mm, tag)
    f_min = _f_guard(f_min_ghz, a_val, tag)

    step_limit = abs(math.log(z2 / z1)) / 2.0
    if rho >= step_limit:
        raise ValueError(
            f"{tag}: rho_max={rho!r} ≥ 阶跃反射极限 |δ|/2={step_limit!r}"
            "——零长渐变即可满足，渐变段无意义，显式拒绝")

    beta_min = _finline_beta_rad_per_mm(f_min, a_val, eps_eff)

    def _g(x_bl: float) -> float:
        return abs(_gamma_closed(x_bl, z1, z2, profile)) - rho

    # 首个变号括根（步长 <π/2 网格不跳多零点，classic_taper_synthesize 同款）
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

    length_mm = x_star / beta_min
    achieved = abs(_gamma_closed(x_star, z1, z2, profile))
    band_edge = math.pi  # 指数剖面 sinc 零点；线性剖面 (0,π) 实测单调（taper_classic）
    preview: list[dict[str, float]] = []
    for beta_l_pt in (x_star, 0.5 * (x_star + band_edge),
                      band_edge * (1.0 - 1e-9)):
        g = _gamma_closed(beta_l_pt, z1, z2, profile)
        preview.append({"beta_l": round(beta_l_pt, 12),
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
        "a_mm": a_val,
        "b_mm": _b_val,
        "wr_used": wr_used,
        "epsilon_eff": eps_eff,
        "fc10_ghz": round(_C_LIGHT / (2.0 * a_val * 1e-3) / 1e9, 9),
        "beta_rad_per_mm_at_f_min": round(beta_min, 12),
        "lam_g_mm_at_f_min": round(2.0 * math.pi / beta_min, 9),
        "length_mm": round(length_mm, 9),
        "beta_l_at_f_min": round(x_star, 12),
        "step_reflection_limit": round(step_limit, 12),
        "achieved_gamma_mag": round(achieved, 15),
        "achieved_residual": round(abs(achieved - rho), 15),
        "response_preview": preview,
        "note": (
            "最短长度口径：|Γ(βL)|=rho_max 首个变号根（βL∈(0,6π] 网格+"
            "brentq，β 为波导 TE10 导波口径=声明近似档，同 "
            "finline_taper_response）；通带保证域=βL∈[x*,π)（指数剖面 "
            "sinc 零点；首零后旁瓣可再超 ρ，如实不冒充全带达标）；ρ≥"
            "|δ|/2 阶跃极限显式拒绝；与 classic_taper_synthesize 的分界="
            "波导 v_p>c 档（其 v_f≤1 守卫结构上排除）"),
        "source": (
            "剖面综合：Pozar《Microwave Engineering》4th ed. §5.9（经 "
            "taper_classic 单源复用）；波导 β：TE10 导波恒等式（与 "
            "core/rwg_mmt 同口径）；鳍线过渡语境：Meier 1974 / Yassin "
            "2008（渐变段长 ≥1λ0 量级的工程惯例互证）"),
    }
