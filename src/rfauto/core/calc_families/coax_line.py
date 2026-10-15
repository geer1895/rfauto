"""标准圆同轴传输线通用件族（aurora72 A2-C 席域 1，R7 第二梯队 T1）。

三键：coax_line_z0（特性阻抗双向解：分析 a,b→Z0 / 综合 z0→a 或 b /
ratio_only） / coax_line_attenuation（行波线衰减分解：导体 αc∝√f +
介质 αd，附 β/(2α) 线 Q 与场积分路线互证） / coax_line_power_capacity
（峰值功率容量：内导体表面场强上限 → V_max/P_max + 工作余量）。

与既有同轴面的边界（语义防撞，R7 §③ T1 三重搜索证据）
--------------------------------------------------------
- combline_resonator.coaxial_cavity_resonance = **同轴谐振腔**（TEM 谐振
  λ/2·λ/4 + 腔长双向）；本族是**行波传输线**通用件（阻抗综合/每米损耗/
  击穿功率），不碰谐振腔长。
- combline_resonator.cavity_unloaded_q = 腔 Q（驻波储能口径）；本族
  attenuation 键输出的是**每米行波衰减**（dB/m）与线 Q=β/(2α)（互证
  输出，与腔 Q 同式但语义是行波线，测试做跨键恒等互证）。
- SICL（基片集成同轴）/rf_trace_geometry（PCB 带状/共面）= 异形/印制
  截面；本族只做**标准圆同轴**（理想导体壁+均匀填充）。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 特性阻抗（TEM 精确闭式，Pozar *Microwave Engineering* §2.2 同轴线）：

      Z0 = (60/√εr)·ln(b/a) Ω（非磁性；a=内导体半径、b=外导体内半径；
      60=工程惯例记号，精确常数 η0/2π=59.9585——损耗/Q 链按精确常数
      保双路线自洽，阻抗面按惯例 60，记号差 ~0.07% 如实注记）

  单位长度电容/电感：C' = 2πε/ln(b/a)（ε=ε0εr）、L' = (μ/2π)·ln(b/a)，
  恒等式 L'·C' = με（测试钉）。综合（给 Z0）：b/a = exp(Z0·√εr/60)。
  首个高阶模 TE11 截止（保角映射 kc≈2/(a+b)）：f_c = c₀/(π(a+b)√εr)，
  f ≥ f_c 时单模 TEM 假设失效（同 combline 腔键口径，如实 note）。
- 衰减（行波口径，Pozar §2.7 传输线损耗 / Ramo-Whinnery-Van Duzer）：
  导体 Rs = √(πfμ/σ)（μ=μ0μr），TEM 场 H_φ = I/(2πρ) →

      αc = Rs·(1/a + 1/b)/(4π·Z0)   [Np/m]
      αd = (β·tanδ)/2 = π·f·√(εr·μr)·tanδ/c₀   [Np/m]
      α_total[dB/m] = 8.686·(αc + αd)

  恒等式（测试钉）：αc ∝ √f（f×4 → αc×2）、αc ∝ 1/√σ（σ×4 → αc÷2）、
  tanδ=0 → αd=0。线 Q = β/(2α_total)；导体路线互证：β/(2αc) 与
  ωμ·ln(b/a)/(Rs·(1/a+1/b))（场积分法，cavity_unloaded_q 同式）解析
  同解——本键按 β/(2αc) 路线算 xcheck，跨键测试互证 ≤1e-12。
- 峰值功率容量（TEM 场分布，击穿场强 E_br 在内导体表面 ρ=a）：

      E(ρ) = V/(ρ·ln(b/a)) → V_max = E_br·a·ln(b/a)
      P_max = V_max²/(2·Z0) = E_br²·a²·ln(b/a)·√εr/120  [W，峰值/匹配线]

  经典最优比（外径 b 固定）：功率容量最大 b/a=√e → Z0=30/√εr；
  衰减最小 b/a≈3.59112（ln x = 1+1/x 之根）→ Z0≈76.7/√εr——两常数
  作输出字段与测试锚。E_br 缺省 3.0e6 V/m = 均匀场空气击穿参考值
  （STP；同轴内导体场非均匀，工程需按海拔/湿度/安全系数降额，如实
  note 不冒充精确击穿预测）。

数值锚（#118 独立来源；锚树 tests/unit/test_a2c_coax_waveguide.py）
- 空气 50Ω：b/a = e^{5/6}（Z0=50 恒等）；a=1mm/b=3mm → 60·ln3 =
  65.916737 Ω；εr=2.25 时 Z0 准确 ÷1.5；
- TE11 截止：a=1/b=3mm 空气 → 299.792458/(4π) = 23.8567 GHz（测试侧
  独立重算）；L'·C' = με 恒等 ≤1e-12；
- 衰减：Cu σ=5.8e7、1GHz、a=1mm/b=2.301mm 空气 → αc≈0.16373 dB/m
  （实测 0.163730589366；工程窗 0.1~0.25）；√f/√σ 标度逐位；线 Q 与场积分路线 ≤1e-12（精确
  η 常数自洽），并与 cavity_unloaded_q 跨键逐位互证；
- 功率：P_max 恒等式 E_br²a²ln(b/a)√εr/120 测试侧独立重算；
  V²/(2Z0) 回代恒等；εr×4 → P_max×2（√εr 标度）；p_op=P_max/4 →
  余量 6.0206 dB；30Ω/76.7Ω 最优比常数。

守卫：分析路线 a_mm>0、b_mm>a_mm（a≥b 非物理显式拒绝）；综合路线
z0_ohm>0 且 a/b 恰给其一（同给或全缺显式拒绝）；epsilon_r ≥ 1；
f_ghz>0；conductivity_s_per_m>0；mu_r>0；tan_delta ≥ 0；e_br_v_per_m>0；
p_op_w ≥ 0；越界一律显式拒绝。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

# 真空磁导率/介电常数（SI）
_MU0 = 1.25663706212e-6
_EPS0 = 8.8541878128e-12

_SOURCES = {
    "z0": "Pozar Microwave Engineering §2.2 同轴线（TEM 精确闭式）；TE11 截止保角映射 kc≈2/(a+b)",
    "att": "Pozar §2.7 传输线损耗（导体 Rs 趋肤口径 + 介质 β·tanδ/2）；线 Q=β/(2α)",
    "pwr": "TEM 场分布 E(ρ)=V/(ρ·ln(b/a))；最优比 30Ω/76.7Ω 经典口径（b 固定）",
}


def _min_loss_ratio() -> float:
    """衰减最小直径比（外径固定）：ln x = 1 + 1/x 之根（biset 60 轮）。

    αc ∝ (1/a+1/b)/ln(b/a)，a=b/x → g(x)=(x+1)/ln x，g'=0 ⇔ ln x=1+1/x；
    经典结果 x≈3.59112 → Z0=60·ln x≈76.7Ω（空气口径）。
    """
    lo, hi = 2.7, 6.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if math.log(mid) - 1.0 - 1.0 / mid < 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


_MIN_LOSS_RATIO = _min_loss_ratio()


# ─── 键 1：特性阻抗双向解 ────────────────────────────────────────────────────

@register_calculator(
    "coax_line_z0",
    "同轴线特性阻抗双向解：标准圆同轴 TEM 精确闭式 Z0=(60/√εr)·ln(b/a)，"
    "分析（给内/外导体半径 a,b）→ Z0+单位长 L'/C'+TE11 高阶模截止 "
    "f_c=c₀/(π(a+b)√εr)；综合（给 z0_ohm+外径 b 或内径 a 恰一）→ 反解另"
    "一半径（b/a=exp(Z0√εr/60)，roundtrip 恒等）；只给 z0_ohm → 直径比 "
    "ratio_only 路线。锚：空气 50Ω ↔ b/a=e^{5/6}；a=1/b=3mm → "
    "65.916737Ω；L'·C'=με 恒等",
    (("a_mm", "float mm 内导体半径（>0；分析与 b 同给，或综合只给 a）"),
     ("b_mm", "float mm 外导体内半径（>a_mm；分析与 a 同给，或综合只给 b）"),
     ("z0_ohm", "float Ω 目标特性阻抗（>0；综合/ratio_only 路线输入）"),
     ("epsilon_r", "float 填充介质相对介电常数（≥1，缺省 1=空气）")),
    required=(),
)
def coax_line_z0(a_mm: float | None = None, b_mm: float | None = None,
                 z0_ohm: float | None = None,
                 epsilon_r: float = 1.0) -> dict[str, Any]:
    eps_r = _finite(epsilon_r, "epsilon_r")
    if eps_r < 1.0:
        raise ValueError(
            f"coax_line_z0: epsilon_r 必须 ≥1，得到 {epsilon_r!r}")
    sqrt_er = math.sqrt(eps_r)
    have_a = a_mm is not None
    have_b = b_mm is not None
    have_z0 = z0_ohm is not None

    a: float | None = None
    b: float | None = None
    z0: float | None = None
    if have_a:
        a = _finite(a_mm, "a_mm")
        if a <= 0.0:
            raise ValueError(f"coax_line_z0: a_mm 必须 >0，得到 {a_mm!r}")
    if have_b:
        b = _finite(b_mm, "b_mm")
        if b <= 0.0:
            raise ValueError(f"coax_line_z0: b_mm 必须 >0，得到 {b_mm!r}")
    if have_z0:
        z0 = _finite(z0_ohm, "z0_ohm")
        if z0 <= 0.0:
            raise ValueError(f"coax_line_z0: z0_ohm 必须 >0，得到 {z0_ohm!r}")

    if have_a and have_b:
        if b <= a:
            raise ValueError(
                f"coax_line_z0: 须 0 < a_mm < b_mm，得到 a={a_mm!r}, "
                f"b={b_mm!r}（a≥b 非物理，显式拒绝）")
        if have_z0:
            raise ValueError(
                "coax_line_z0: 分析路线（a_mm+b_mm 同给）不允许再给 z0_ohm"
                "（分析/综合互斥，显式拒绝）")
        z0 = 60.0 * math.log(b / a) / sqrt_er
        route = "analyze"
    elif have_z0 and have_a != have_b:
        # 综合：b/a = exp(Z0·√εr/60)，恰一绝对尺寸已知反解另一尺寸
        ratio = math.exp(z0 * sqrt_er / 60.0)
        if have_b:
            b = b_mm
            a = b / ratio
            route = "synthesize_inner"
        else:
            a = a_mm
            b = a * ratio
            route = "synthesize_outer"
        z0 = 60.0 * math.log(b / a) / sqrt_er  # 回代自洽
    elif have_z0:
        route = "ratio_only"
    else:
        raise ValueError(
            "coax_line_z0: 输入组合无效——分析给 a_mm+b_mm（恰给两个）；"
            "综合给 z0_ohm+a_mm 或 z0_ohm+b_mm（恰给其一）；只给 z0_ohm "
            "= ratio_only 直径比路线")

    b_over_a = b / a if (a is not None and b is not None) else None
    if b_over_a is None and z0 is not None:
        # ratio_only 路线：b/a = exp(Z0·√εr/60)（60=工程惯例记号，
        # 精确 TEM 常数 η0/2π=59.9585，见 attenuation 键 note）
        b_over_a = math.exp(z0 * sqrt_er / 60.0)
    # 单位长分布参数（有绝对几何时）：C'=2πε/ln(b/a)、L'=(μ/2π)ln(b/a)
    c_prime_pf_m: float | None = None
    l_prime_nh_m: float | None = None
    lc_product_check: float | None = None
    te11_cutoff_ghz: float | None = None
    if a is not None and b is not None and b_over_a is not None:
        ln_ratio = math.log(b_over_a)
        c_prime_pf_m = 2.0 * math.pi * _EPS0 * eps_r / ln_ratio * 1e12
        l_prime_nh_m = _MU0 * ln_ratio / (2.0 * math.pi) * 1e9
        # 恒等式 L'·C' = με（对 με 归一，应为 1）
        lc_product_check = (
            (l_prime_nh_m * 1e-9) * (c_prime_pf_m * 1e-12)
            / (_MU0 * _EPS0 * eps_r))
        te11_cutoff_ghz = C_MM_GHZ / (math.pi * (a + b) * sqrt_er)
    if route == "ratio_only":
        note = (
            "只给 z0_ohm：输出直径比 b/a=exp(Z0·√εr/60) 与最优比参考"
            "（功率最大 30/√εr、损耗最小 76.7/√εr），无绝对尺寸、无 "
            "TE11 截止（需几何）")
    elif route == "analyze":
        note = (
            "TEM 主模精确闭式；单模工作域按工作频率对照 te11_cutoff_ghz "
            "判定（f ≥ 截止 = 高阶模可传播，单模假设失效）")
    else:
        note = (
            "综合路线回代自洽（z0 回代机器精度级）；TE11 截止按综合后几何"
            "给出")
    return {
        "route": route,
        "z0_ohm": None if z0 is None else round(z0, 12),
        "a_mm": None if a is None else round(a, 12),
        "b_mm": None if b is None else round(b, 12),
        "b_over_a": None if b_over_a is None else round(b_over_a, 15),
        "epsilon_r": eps_r,
        "capacitance_pf_per_m": (
            None if c_prime_pf_m is None else round(c_prime_pf_m, 12)),
        "inductance_nh_per_m": (
            None if l_prime_nh_m is None else round(l_prime_nh_m, 12)),
        "lc_over_muepsilon": (
            None if lc_product_check is None else round(lc_product_check, 12)),
        "te11_cutoff_ghz": (
            None if te11_cutoff_ghz is None else round(te11_cutoff_ghz, 9)),
        "z0_max_power_ratio_ohm": round(30.0 / sqrt_er, 9),
        "z0_min_loss_ratio_ohm": round(60.0 * math.log(_MIN_LOSS_RATIO)
                                       / sqrt_er, 9),
        "note": note,
        "optimum_ratios_note": (
            "外径固定：功率容量最大 b/a=√e（Z0=30/√εr）；衰减最小 "
            f"b/a≈{_MIN_LOSS_RATIO:.5f}（Z0≈76.7/√εr）"),
        "source": _SOURCES["z0"],
    }


# ─── 键 2：行波衰减分解（导体+介质）─────────────────────────────────────────

@register_calculator(
    "coax_line_attenuation",
    "同轴线行波衰减分解：导体 αc=Rs·(1/a+1/b)/(4π·Z0)（Rs=√(πfμ/σ) 趋肤"
    "口径，αc∝√f∝1/√σ 测试钉）+ 介质 αd=β·tanδ/2（满充均匀假定，"
    "tanδ=0 如实返 null）；α_total dB/m=8.686(αc+αd)。附线 Q=β/(2α) 与"
    "场积分路线互证（β/(2αc) ↔ ωμ·ln(b/a)/(Rs(1/a+1/b)) 解析同解，"
    "q_xcheck_rel_dev 机器精度级）。锚：Cu/1GHz/a=1mm/b=2.301mm 空气 "
    "αc≈0.16373 dB/m（实测 0.163730589366）",
    (("f_ghz", "float GHz 工作频率（>0）"),
     ("a_mm", "float mm 内导体半径（>0）"),
     ("b_mm", "float mm 外导体内半径（>a_mm）"),
     ("conductivity_s_per_m", "float S/m 导体电导率（>0；Cu=5.8e7）"),
     ("epsilon_r", "float 填充介质相对介电常数（≥1，缺省 1）"),
     ("mu_r", "float 相对磁导率（>0，缺省 1 非磁性）"),
     ("tan_delta", "float 介质损耗角正切（≥0，缺省 0=无耗）")),
    required=("f_ghz", "a_mm", "b_mm", "conductivity_s_per_m"),
)
def coax_line_attenuation(f_ghz: float, a_mm: float, b_mm: float,
                          conductivity_s_per_m: float,
                          epsilon_r: float = 1.0, mu_r: float = 1.0,
                          tan_delta: float = 0.0) -> dict[str, Any]:
    f = _finite(f_ghz, "f_ghz")
    a = _finite(a_mm, "a_mm")
    b = _finite(b_mm, "b_mm")
    sigma = _finite(conductivity_s_per_m, "conductivity_s_per_m")
    eps_r = _finite(epsilon_r, "epsilon_r")
    mur = _finite(mu_r, "mu_r")
    tand = _finite(tan_delta, "tan_delta")
    if f <= 0.0:
        raise ValueError(
            f"coax_line_attenuation: f_ghz 必须 >0，得到 {f_ghz!r}")
    if a <= 0.0:
        raise ValueError(
            f"coax_line_attenuation: a_mm 必须 >0，得到 {a_mm!r}")
    if b <= a:
        raise ValueError(
            f"coax_line_attenuation: 须 0 < a_mm < b_mm，得到 a={a_mm!r}, "
            f"b={b_mm!r}（a≥b 非物理，显式拒绝）")
    if sigma <= 0.0:
        raise ValueError(
            f"coax_line_attenuation: conductivity_s_per_m 必须 >0，得到 "
            f"{conductivity_s_per_m!r}")
    if eps_r < 1.0:
        raise ValueError(
            f"coax_line_attenuation: epsilon_r 必须 ≥1，得到 {epsilon_r!r}")
    if mur <= 0.0:
        raise ValueError(
            f"coax_line_attenuation: mu_r 必须 >0，得到 {mu_r!r}")
    if tand < 0.0:
        raise ValueError(
            f"coax_line_attenuation: tan_delta 必须 ≥0，得到 {tan_delta!r}")

    f_hz = f * 1e9
    a_m, b_m = a * 1e-3, b * 1e-3
    mu = _MU0 * mur
    omega = 2.0 * math.pi * f_hz
    # Q 链用精确 TEM 阻抗（损耗/Q 与双路线互证须精确常数自洽）：
    # Z0 = (η0/2π)·√(μr/εr)·ln(b/a)，η0/2π=59.9585（工程记号 60 的精确形）
    eta0 = math.sqrt(_MU0 / _EPS0)
    z0 = eta0 / (2.0 * math.pi) * math.log(b_m / a_m) * math.sqrt(mur / eps_r)
    rs = math.sqrt(math.pi * f_hz * mu / sigma)               # Ω/□
    alpha_c_np = rs * (1.0 / a_m + 1.0 / b_m) / (4.0 * math.pi * z0)
    # 介质损耗：αd = β·tanδ/2，β=ω√(με)=2πf√(μ0ε0εrμr)=2πf√(εrμr)/c₀
    # （C_MM_GHZ=mm·GHz 口径光速 → c₀[m/s]=C_MM_GHZ·1e6）
    alpha_d_np = math.pi * f_hz * math.sqrt(eps_r * mur) * tand / (
        C_MM_GHZ * 1e6)
    beta = omega * math.sqrt(mu * _EPS0 * eps_r)              # rad/m
    alpha_total_db = 8.686 * (alpha_c_np + alpha_d_np)
    line_q = beta / (2.0 * (alpha_c_np + alpha_d_np))
    # 场积分路线互证（cavity_unloaded_q 同式，独立推导路线）
    q_c_field = omega * mu * math.log(b_m / a_m) / (
        rs * (1.0 / a_m + 1.0 / b_m))
    q_c_route = beta / (2.0 * alpha_c_np)
    rel_dev = abs(q_c_field - q_c_route) / q_c_route
    return {
        "f_ghz": f,
        "a_mm": a,
        "b_mm": b,
        "conductivity_s_per_m": sigma,
        "epsilon_r": eps_r,
        "mu_r": mur,
        "tan_delta": tand,
        "z0_ohm": round(z0, 12),
        "rs_ohm_per_sq": round(rs, 15),
        "alpha_conductor_db_m": round(alpha_c_np * 8.686, 12),
        "alpha_dielectric_db_m": (
            None if tand == 0.0 else round(alpha_d_np * 8.686, 12)),
        "alpha_total_db_m": round(alpha_total_db, 12),
        "beta_rad_per_m": round(beta, 12),
        "line_q": round(line_q, 9),
        "q_conductor_xcheck": round(q_c_route, 9),
        "q_conductor_field_integral": round(q_c_field, 9),
        "q_xcheck_rel_dev": round(rel_dev, 15),
        "note": (
            "行波线口径（每米衰减），非谐振腔 Q；αc 趋肤口径 ∝√f∝1/√σ；"
            "αd 满充均匀介质假定；q_xcheck=β/(2αc) 与场积分法解析同解；"
            "本键 Z0 取精确 TEM 常数 η0/2π=59.9585（工程记号 60 的精确"
            "形，记号差 ~0.07%；阻抗综合面 coax_line_z0 按惯例 60 口径）"),
        "source": _SOURCES["att"],
    }


# ─── 键 3：峰值功率容量 ─────────────────────────────────────────────────────

@register_calculator(
    "coax_line_power_capacity",
    "同轴线峰值功率容量：TEM 场 E(ρ)=V/(ρ·ln(b/a))，内导体表面（ρ=a）"
    "场强最大 → V_max=E_br·a·ln(b/a)、P_max=V_max²/(2Z0)=E_br²·a²·"
    "ln(b/a)·√εr/120 W（峰值/匹配线，频率无关）。可选 p_op_w → 工作场强"
    "余量 dB（20log10(E_br/E_op)，可负=超容量如实报告）。最优比参考："
    "外径固定功率容量最大 b/a=√e（Z0=30/√εr）。E_br 缺省 3.0e6 V/m="
    "均匀场空气击穿参考值（非均匀场需降额，如实 note）。锚：恒等式测试"
    "侧独立重算；εr×4→P×2；p_op=P_max/4→余量 6.0206 dB",
    (("a_mm", "float mm 内导体半径（>0）"),
     ("b_mm", "float mm 外导体内半径（>a_mm）"),
     ("epsilon_r", "float 填充介质相对介电常数（≥1，缺省 1）"),
     ("e_br_v_per_m", "float V/m 击穿场强参考值（>0，缺省 3.0e6 空气 STP "
      "均匀场）"),
     ("p_op_w", "float W 工作峰值功率（≥0，可选——给则输出工作场强余量）")),
    required=("a_mm", "b_mm"),
)
def coax_line_power_capacity(a_mm: float, b_mm: float,
                             epsilon_r: float = 1.0,
                             e_br_v_per_m: float = 3.0e6,
                             p_op_w: float | None = None) -> dict[str, Any]:
    a = _finite(a_mm, "a_mm")
    b = _finite(b_mm, "b_mm")
    eps_r = _finite(epsilon_r, "epsilon_r")
    e_br = _finite(e_br_v_per_m, "e_br_v_per_m")
    if a <= 0.0:
        raise ValueError(
            f"coax_line_power_capacity: a_mm 必须 >0，得到 {a_mm!r}")
    if b <= a:
        raise ValueError(
            f"coax_line_power_capacity: 须 0 < a_mm < b_mm，得到 a={a_mm!r}, "
            f"b={b_mm!r}（a≥b 非物理，显式拒绝）")
    if eps_r < 1.0:
        raise ValueError(
            f"coax_line_power_capacity: epsilon_r 必须 ≥1，得到 "
            f"{epsilon_r!r}")
    if e_br <= 0.0:
        raise ValueError(
            f"coax_line_power_capacity: e_br_v_per_m 必须 >0，得到 "
            f"{e_br_v_per_m!r}")
    p_op: float | None = None
    if p_op_w is not None:
        p_op = _finite(p_op_w, "p_op_w")
        if p_op < 0.0:
            raise ValueError(
                f"coax_line_power_capacity: p_op_w 必须 ≥0，得到 {p_op_w!r}")

    a_m, b_m = a * 1e-3, b * 1e-3
    sqrt_er = math.sqrt(eps_r)
    ln_ratio = math.log(b_m / a_m)
    z0 = 60.0 * ln_ratio / sqrt_er
    v_max = e_br * a_m * ln_ratio                     # V（峰值）
    p_max = v_max * v_max / (2.0 * z0)                # W（峰值，匹配线）
    p_max_identity = e_br * e_br * a_m * a_m * ln_ratio * sqrt_er / 120.0
    p_rel_dev = abs(p_max - p_max_identity) / p_max_identity
    a_opt_mm = b / math.sqrt(math.e)                  # 外径固定功率最大
    margin_db: float | None = None
    e_op: float | None = None
    over_drive = False
    if p_op is not None:
        v_op = math.sqrt(2.0 * p_op * z0)
        e_op = v_op / (a_m * ln_ratio)
        margin_db = 20.0 * math.log10(e_br / e_op)
        over_drive = bool(p_op > p_max)
    note = (
        "峰值功率容量（匹配线、TEM 单模）；E_br 缺省=均匀场空气击穿参考"
        "值（STP）——同轴内导体场非均匀，工程上按海拔/湿度/安全系数降额，"
        "本键不做击穿概率预测；平均功率受热限，不在本键口径")
    if over_drive:
        note += "；p_op > P_max（余量为负）=超容量工作，如实报告不拒绝"
    return {
        "a_mm": a,
        "b_mm": b,
        "epsilon_r": eps_r,
        "e_br_v_per_m": e_br,
        "z0_ohm": round(z0, 12),
        "v_max_peak_v": round(v_max, 12),
        "p_max_peak_w": round(p_max, 12),
        "p_identity_rel_dev": round(p_rel_dev, 15),
        "a_opt_max_power_mm": round(a_opt_mm, 12),
        "z0_max_power_ohm": round(30.0 / sqrt_er, 9),
        "p_op_w": p_op,
        "e_op_v_per_m": None if e_op is None else round(e_op, 12),
        "margin_db": None if margin_db is None else round(margin_db, 9),
        "over_drive": over_drive,
        "note": note,
        "source": _SOURCES["pwr"],
    }
