"""均匀化通用族（MM-7，内核 core/homogenization.py，本模块只做注册壳）。

规格 研究扩充 round17 §五 :154（B 流超材料，
2026-10-02）「三混合式提升通用 core 内核+Wiener 界+Pendry 1999 SRR μ 公式
+线媒质 ωp（Pendry 1996 PRL）」。四键：
- homog_mix_eff：三混合式统一面（MG/Bruggeman/Looyenga，复数通用核+
  depolarization 因子 L 形状族）+Wiener 双界与界内判读（复数输入界不
  有序，in_wiener_bounds 如实 None）。
- srr_permeability：Pendry 1999 Lorentz μ(ω)（F 与 f_mp 二选一入参）。
- wire_media_plasma：Pendry 1996 ωp²=2πc0²/(a²ln(a/r))+Drude ε(ω)。
- retrieve_eff_params：单频 (S11,S21)→(ε,μ,n,Z) 对称面板反演（Smith
  2002 同族；branch_m 显式支编号，分支自动判据=MM-5 显式不做）。

depolarization_factors/mix_eff 边界守卫/slab_panel_rt 正向对偶面/
wiener_bounds 为 core 纯函数不注册（分析面走 core 直调）。诚实边界：
SRR 几何闭式 ω0(环尺寸) 原文常数需回 PDF 逐位核（#118 家族纪律）留
MM-11 极化率库；GSTC χ 面与平板 (n,Z) 面统一换算显式不做。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator


def _c2j(x: Any) -> list[float]:
    """complex → [re, im]（service JSON 复数约定）。"""
    c = complex(x)
    return [float(c.real), float(c.imag)]


@register_calculator(
    "homog_mix_eff",
    "MM-7 三混合式统一面（规格 §五 :154，通用 core 内核）：rule ∈ "
    "maxwell_garnett（Garnett 1904 球夹杂稀疏极限，depol 因子 L 椭球"
    "广义）/bruggeman（Bruggeman 1935 对称有效介质，要求 L∈(0,1]）/"
    "looyenga（Looyenga 1965 立方根加权）——复数 ε 全程（e^{-jωt} 口径 "
    "Im≥0 无源）。depol 形状族：球=1/3、沿场细棒=0（仅 MG，退化为 "
    "Wiener 上界并联）、法向薄片=1（MG 退化为 Wiener 下界串联）。附 "
    "Wiener 双界（算术/调和）；实数输入报告界内判读、复数输入界不有序 "
    "如实 None。L=1/3 实数输入与 humidity_drift 球形闭式逐式一致",
    (("rule", "str 'maxwell_garnett'|'bruggeman'|'looyenga'"),
     ("er_matrix", "float|[re,im] 基质 ε_m（Re>0，Im≥0）"),
     ("er_inclusion", "float|[re,im] 夹杂 ε_i（Re>0，Im≥0）"),
     ("v_inclusion", "float 夹杂体积分数 ∈[0,1]（端点恒等直返）"),
     ("depol", "float depolarization 因子 L ∈[0,1]（默认 1/3=球形）")),
    required=("rule", "er_matrix", "er_inclusion", "v_inclusion"),
)
def homog_mix_eff(rule: str, er_matrix: Any, er_inclusion: Any,
                  v_inclusion: Any, depol: Any = 1.0 / 3.0) -> dict:
    from rfauto.core.homogenization import mix_eff as _mix

    out = _mix(rule, er_matrix, er_inclusion, v_inclusion, depol)
    in_bounds = out["in_wiener_bounds"]
    return {
        "eps_eff": _c2j(out["eps_eff"]),
        "rule": out["rule"],
        "depol": float(out["depol"]),
        "wiener_lower": _c2j(out["wiener_lower"]),
        "wiener_upper": _c2j(out["wiener_upper"]),
        "in_wiener_bounds": in_bounds,
    }


@register_calculator(
    "srr_permeability",
    "MM-7 Pendry 1999 SRR 阵列等效磁导率（IEEE TMTT 47(11):2075 Lorentz "
    "形，arXiv 2006.13861 同式互证）：μ(ω)=1−F·ω²/(ω²−ω0²+iΓω)。F 填充"
    "因子与 f_mp（磁等离子频率）二选一入参（f_mp>f_res，F=1−(f_res/"
    "f_mp)²）。解析锚：μ(0)=1、μ(∞)=1−F、无损 μ(f_mp)=0、Re μ<0 带恰 "
    "=(f_res,f_mp)、Γ>0 全带 Im μ>0（无源性）。无损谐振点（分母零）与 "
    "非物理域显式拒绝。诚实边界：几何闭式 ω0(环尺寸) 原文常数需回 PDF "
    "逐位核（#118），留 MM-11 极化率库——本键只收 Lorentz 参数化",
    (("freq_ghz", "float 工作频率 GHz（>0）"),
     ("f_res_ghz", "float 环谐振频率 f_res=ω0/2π GHz（>0）"),
     ("fill_factor", "float 填充因子 F ∈(0,1)（与 f_mp_ghz 二选一）"),
     ("f_mp_ghz", "float 磁等离子频率 GHz（>f_res；与 fill_factor 二选一）"),
     ("gamma_ghz", "float 阻尼 Γ/2π GHz（≥0，默认 0=无损）")),
    required=("freq_ghz", "f_res_ghz"),
)
def srr_permeability(freq_ghz: Any, f_res_ghz: Any,
                     fill_factor: Any = None, f_mp_ghz: Any = None,
                     gamma_ghz: Any = 0.0) -> dict:
    from rfauto.core.homogenization import srr_permeability as _srr

    out = _srr(freq_ghz, f_res_ghz, fill_factor=fill_factor,
               f_mp_ghz=f_mp_ghz, gamma_ghz=gamma_ghz)
    return {
        "mu": _c2j(out["mu"]),
        "mu_prime": float(out["mu_prime"]),
        "mu_double_prime": float(out["mu_double_prime"]),
        "fill_factor": float(out["fill_factor"]),
        "f_res_ghz": float(out["f_res_ghz"]),
        "f_mp_ghz": float(out["f_mp_ghz"]),
        "gamma_ghz": float(out["gamma_ghz"]),
        "negative_mu": out["negative_mu"],
    }


@register_calculator(
    "wire_media_plasma",
    "MM-7 Pendry 1996 线媒质等离子频率（PRL 76:4773）：ωp²=2π·c0²/"
    "(a²·ln(a/r))，a=晶格常数、r=线半径（a/r≥2 才入稀疏口径域）；附 "
    "Drude ε(ω)=1−ωp²/(ω(ω+jν))（e^{-jωt}：ν>0 → Im ε>0 无损正性、"
    "ν=0 ω<ωp → Re ε<0、ω=ωp 精确零点）。freq_ghz 给出时附 ε 报告。"
    "锚量级：a=1mm、r=1µm → f_p≈45.5 GHz（比金属光学等离子（~1e15 Hz）"
    "低 ~4 个量级——extremely low frequency 量化锚）",
    (("lattice_mm", "float 晶格常数 a（mm，>0）"),
     ("wire_radius_mm", "float 线半径 r（mm，0<r<a 且 a/r≥2）"),
     ("freq_ghz", "float 可选工作频率 GHz（>0；给出时附 Drude ε 报告）"),
     ("nu_rad_s", "float 碰撞频率 ν（rad/s，≥0，默认 0=无损）")),
    required=("lattice_mm", "wire_radius_mm"),
)
def wire_media_plasma(lattice_mm: Any, wire_radius_mm: Any,
                      freq_ghz: Any = None, nu_rad_s: Any = 0.0) -> dict:
    from rfauto.core.homogenization import wire_media_plasma as _wm

    out = _wm(lattice_mm, wire_radius_mm, freq_ghz=freq_ghz, nu_rad_s=nu_rad_s)
    result: dict[str, Any] = {
        "omega_p_rad_s": float(out["omega_p_rad_s"]),
        "f_p_ghz": float(out["f_p_ghz"]),
        "ln_a_over_r": float(out["ln_a_over_r"]),
        "nu_rad_s": float(out["nu_rad_s"]),
    }
    if "eps" in out:
        result["eps"] = _c2j(out["eps"])
        result["eps_prime"] = float(out["eps_prime"])
        result["eps_double_prime"] = float(out["eps_double_prime"])
        result["negative_eps"] = out["negative_eps"]
    return result


@register_calculator(
    "retrieve_eff_params",
    "MM-7 等效参数反演（Smith 2002 PRB 65:195104 同族口径）：单频 "
    "(S11,S21)（[re,im] 对）法向入射对称面板厚度 d → (ε,μ,n,Z)。时间 "
    "约定 e^{-jωt}（τ=e^{+jk0·nd}，无耗 Im(n)=0、有耗 Im(n)>0）。无源 "
    "守卫：能量 |S11|²+|S21|²≤1+1e-9、|τ|≤1+1e-9、Im(n)<0 显式拒绝；"
    "退化域（(1−S11)²−S21²=0、1−P·Γ=0、τ=0）显式拒绝。branch_m=相位 "
    "回绕支编号（相邻支差 2π/(k0·d) 恒等式可自检）；分支自动判据/"
    "Kramers-Kronig 因果核=MM-5 显式不做。slab_panel_rt=core 正向对偶"
    "面（合成回收对拍用，core 直调不注册）",
    (("freq_ghz", "float 频率 GHz（>0）"),
     ("s11", "float|[re,im] 反射系数 S11"),
     ("s21", "float|[re,im] 透射系数 S21"),
     ("thickness_mm", "float 面板厚度 d（mm，>0）"),
     ("branch_m", "int 折射率支编号（ℤ，默认 0=主枝；d<λ/2 时主枝）")),
    required=("freq_ghz", "s11", "s21", "thickness_mm"),
)
def retrieve_eff_params(freq_ghz: Any, s11: Any, s21: Any,
                        thickness_mm: Any, branch_m: int = 0) -> dict:
    from rfauto.core.homogenization import retrieve_eff_params as _ret

    out = _ret(freq_ghz, s11, s21, thickness_mm, branch_m)
    return {
        "eps_eff": _c2j(out["eps_eff"]),
        "mu_eff": _c2j(out["mu_eff"]),
        "n_eff": _c2j(out["n_eff"]),
        "z_eff": _c2j(out["z_eff"]),
        "k0_rad_m": float(out["k0_rad_m"]),
        "thickness_m": float(out["thickness_m"]),
        "branch_m": out["branch_m"],
        "energy": float(out["energy"]),
        "tau": _c2j(out["tau"]),
        "gamma_interface": _c2j(out["gamma_interface"]),
    }
