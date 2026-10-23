"""天线口径效率分解域两键（aurora_j W4-S13）：反射面效率分量 + 最优角锥喇叭。

提升核/薄注册双形态（antenna_q 注册面先例）：物理公式单源在库内既有
core 模块，本模块只做注册包装（入参收敛 + θ₀/σ 几何换算 + 字段映射），
零公式复制（#116 死副本教训）：

- ``aperture_efficiency_components``——焦馈抛物面反射面效率分解，公式
  单源 ``rfauto.core.reflector_antenna``（AP-4 反射面闭式设计器，在库
  零键的注册面）：
  * 溢出效率 η_s = 1 − cos^{q+1}(θ₀)（cos^q 功率方向图、前半球馈，
    Balanis Ch.15 口径；core.spillover_efficiency）；
  * 照射效率 η_i = η_ap/η_s，其中 η_ap=2(q+1)·cot²(θ₀/2)·|∫₀^{θ₀}
    cos^{q/2}θ·tan(θ/2)dθ|² 即任务口径 η_i=|∫E_a dA|²/(A·∫|E_a|²dA)
    的射线映射实现（core.aperture_efficiency / illumination_efficiency，
    口径面独立路径 aperture_efficiency_aperture_plane 同仓互证）；
  * 极化效率 η_p=显式入参（Balanis §15 效率预算分解项，馈源极化纯度
    工程口径）；
  * Ruze 表面公差效率 η_δ = exp[−(4πσ/λ)²]（J. Ruze, "Antenna Tolerance
    Theory—A Review", Proc. IEEE 54(4):633-640, 1966；
    core.ruze_efficiency）；
  * 方向性（η 加权口径增益）= 10·log10(η_ap·(πD/λ)²)（core.gain_db；
    无耗口径模型下增益=方向性，如实口径）。
  分布档（档名进 docstring，任务书惯例）：``uniform``（q=0 各向同性
  馈，η_s=1−cosθ₀ 解析锚档）/ ``cos2``（q=2 cos² 功率方向图，经典
  −10 dB 量级边照/η_ap≈0.82 最优档）；另收显式 ``q_power`` 覆盖（≥0
  任意指数，core 同参数域）。θ₀=反射面边缘半角：cot(θ₀/2)=4F/D
  （抛物面几何恒等式）⇒ θ₀=2·atan(1/(4·f/D))，f/D≥1/4（θ₀≤90° 前半
  球馈域）显式守卫。
- ``horn_aperture_efficiency``——最优角锥喇叭增益/效率/波束宽度，公式
  单源 ``rfauto.core.horn_synthesis``（ME-7，Orfanidis Ch.21 主源 +
  Balanis Ch.13 对照源，2026-09-26 双源核对引文在彼处 docstring）：
  * 口径效率 η_ap(σ_h,σ_e)=(1/8)|F1(0,σ_h)|²|F0(0,σ_e)|²（Orfanidis
    (21.4.3) 一阶 Fresnel 闭式，core.aperture_efficiency 单源）；
  * 最优条件：δ_H=σ_h²/4=3λ/8（H 面）、δ_E=σ_e²/4=λ/4（E 面），δ=
    口径尺寸²/(8·径向长)（Balanis Ch.13 最优厚度条件；等价 σ_h=√1.5/
    σ_e=1，对应 η_ap≈0.514——文献通称 0.51 最优口径效率常数；外部
    互证：Nikolova McMaster L18 (18.24)/(18.37)/(18.41) A³=3λ²R₀、
    B²=2λR₀、ε_ap=0.81·0.80·0.79≅0.51）；
  * 增益 G = η_ap·(4π/λ²)·a_p·b_p（Orfanidis (21.4.2) 装配；与本仓
    horn_gain_direct 公开路径同式，单测几何互证逐位钉）；
  * 半功率波束宽度近似式（Balanis Ch.13 最优喇叭设计关系）：
    HPBW_E ≈ 54°·λ/b_p（E 面）、HPBW_H ≈ 78°·λ/a_p（H 面）。引文核
    （任务书"不确定的形态不臆写"处置记录）：54λ/B 经外部教科书章节
    摘录（svbitec ch.5-6 "θB≅54λ/B in the yz-plane"）+H 面 78° 与最优
    口径效率同页讲义摘录互证；本仓一阶 Fresnel 口径积分独立数值复算
    （tests/test_w4s13 锚树）：E 面 54.0（b_p≥4λ 偏差 ≤0.2%）、H 面
    77.8–78.2（≤1.3%），两系数据此入 docstring。近似式适用域=大口径
    （a_p,b_p ≳ 3λ），小口径偏差如实放大不守卫（note 声明）。
    本键 HPBW 输出恒按最优关系式给值（口径=最优喇叭设计关系），给定
    几何偏离最优时以 delta_*_over_lambda 与 near_optimum 判定如实暴露
    （不隐式换算非最优口径的真实方向图——那是另一条数值路径，不在本
    键，horn_gain_exact_aperture 在库可取）。

诚实边界
--------
- 两键均为无耗口径模型：不含馈源损耗/壁损耗/遮挡/边缘绕射（B2 遮挡
  因子在 core.efficiency_budget 有、本键不展开；B3 壁损在
  core.horn_wall_loss_db 有，同仓库分端不混装）。
- B2 η_p 为显式入参非物理模型（馈源极化纯度工程口径，>1/≤0 显式拒绝）。
- B3 HPBW 近似式与 0.51 常数均为"最优喇叭"口径——给定几何偏离最优时
  HPBW 仅量级参考，near_optimum 字段如实判定。

锚（#118 独立算术，tests/unit/test_w4s13_antenna_aperture_keys.py）
------------------------------------------------------------------
B2：①Ruze 曲线锚 σ/λ=0→η_δ=1、σ/λ=1/32→0.857125（core 同锚透传）；
②能量守恒 η_s·η_i·η_p·η_δ=η_ap 乘积恒等 + η_s·η_i=core.aperture_
efficiency（η_ap=η_s·η_i 恒等钉）；③core 手积闭式锚透传 q=2、θ₀=60°
→ η_ap=0.811419；④uniform 档 η_s=1−cosθ₀ 解析恒等；⑤增益独立复算
10log10(η_ap)+20log10(πD/λ)；⑥η_p=0.5 → η_ap 恰半（线性透传）。
B3：①最优几何（a_p=4λ,b_p=2λ,δ_H=3λ/8,δ_E=λ/4）→ η_ap∈[0.50,0.53]
（0.51 常数带）；②G 恒等式 G/(η_ap·4πab/λ²)=1；③HPBW 恒等式
54λ/b_p、78λ/a_p 逐位 + 大口径 Fresnel 数值第三方法 ≤1.5%；④与
core.horn_gain_direct 同几何互证（σ/η/G 逐位）；⑤偏离最优判定翻转。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import horn_synthesis as _horn_syn
from rfauto.core import reflector_antenna as _refl_ant

from .registry import register_calculator

_SOURCE_REFLECTOR = (
    "出处见 rfauto.core.reflector_antenna 模块 docstring（Balanis Ch.15 "
    "效率预算口径 cos^q 馈；Ruze 1966 Proc. IEEE 54(4):633-640；本键为"
    "提升核注册面，公式零复制）"
)
_SOURCE_HORN = (
    "出处见 rfauto.core.horn_synthesis 模块 docstring（Orfanidis "
    "Electromagnetic Waves & Antennas Ch.21 (21.4.2)/(21.4.3) 主源 + "
    "Balanis Antenna Theory Ch.13 最优厚度条件 δ_H=3λ/8、δ_E=λ/4 对照源"
    "（0.51 最优口径效率常数文献口径）；HPBW≈54°λ/b_p、78°λ/a_p 经外部"
    "讲义引文+Fresnel 口径积分数值互证；本键为提升核注册面，公式零复制）"
)

#: B2 分布档 → 馈源功率指数 q（cos^q 族；档名单源）。
_PROFILE_Q: dict[str, float] = {"uniform": 0.0, "cos2": 2.0}

#: B3 最优 HPBW 近似式系数（deg，Balanis Ch.13 最优喇叭设计关系；
#: 数值互证门 ≤1.5% 见模块 docstring）。
_HPBW_E_DEG_COEF = 54.0
_HPBW_H_DEG_COEF = 78.0

#: B3 最优厚度判定的相对容带（δ 与最优值 3/8、1/4 的绝对差 ≤ tol×λ）。
_DELTA_OPT_TOL = 0.05


def _pos_finite(value: Any, name: str) -> float:
    """正有限数守卫（bool 显式拒收；尺寸/频率类入参惯例）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，得 {value!r}")
    return out


@register_calculator(
    "aperture_efficiency_components",
    "反射面效率分量分解（W4-S13）：焦馈抛物面 "
    "η_ap=η_s(溢出)·η_i(照射)·η_p(极化)·η_δ(表面公差)——η_s=1−cos^{q+1}θ₀"
    "（cos^q 功率方向图前半球馈）、η_i=η_ap/η_s（口径面积分口径 |∫E_a dA|²"
    "/(A∫|E_a|²dA) 的射线映射实现）、η_δ=exp[−(4πσ/λ)²]（Ruze 1966），"
    "+η-加权方向性 dBi=10log10(η_ap·(πD/λ)²)。分布档：uniform（q=0）/"
    "cos2（q=2 经典边照档），q_power 显式覆盖；θ₀=2·atan(1/(4·f/D))，"
    "f/D≥1/4 守卫。单源 core/reflector_antenna（公式零复制）",
    (("profile", "str 口径分布档：uniform/cos2（档义见模块 docstring）"),
     ("f_over_d", "float 焦径比 F/D（≥0.25；θ₀=边缘半角 ≤90° 前半球馈域）"),
     ("f_ghz", "float GHz 工作频率（>0；λ/Ruze σ 换算与方向性）"),
     ("diameter_m", "float m 反射面口径直径（>0）"),
     ("sigma_over_lambda", "float λ 口径面法向 rms 表面误差/波长（≥0，"
      "缺省 0=理想面）"),
     ("eta_polarization", "float 极化效率 η_p（∈(0,1]，缺省 1）"),
     ("q_power", "float 馈源功率指数 q 覆盖（≥0 可选；给定时忽略 profile）")),
    required=("profile", "f_over_d", "f_ghz", "diameter_m"),
)
def aperture_efficiency_components(
    profile: str,
    f_over_d: float,
    f_ghz: float,
    diameter_m: float,
    sigma_over_lambda: float = 0.0,
    eta_polarization: float = 1.0,
    q_power: float | None = None,
) -> dict[str, Any]:
    """薄委托 core/reflector_antenna（θ₀ 几何换算 + 分量组装）。"""
    if not isinstance(profile, str) or profile not in _PROFILE_Q:
        raise ValueError(
            f"profile 必须是 {sorted(_PROFILE_Q)} 之一，收到 {profile!r}")
    q = _num_q0(q_power) if q_power is not None else _PROFILE_Q[profile]
    fod = _pos_finite(f_over_d, "f_over_d")
    if fod < 0.25:
        raise ValueError(
            f"f_over_d={fod:g} 必须 ≥0.25（θ₀=2·atan(1/(4F/D)) ≤90° "
            "前半球馈域）")
    f_hz = _pos_finite(f_ghz, "f_ghz") * 1e9
    d_m = _pos_finite(diameter_m, "diameter_m")
    if isinstance(sigma_over_lambda, bool):
        raise ValueError("sigma_over_lambda 不接受 bool")
    sol = float(sigma_over_lambda)
    if not math.isfinite(sol) or sol < 0.0:
        raise ValueError(f"sigma_over_lambda 必须 ≥0 的有限数，得 {sol!r}")
    if isinstance(eta_polarization, bool):
        raise ValueError("eta_polarization 不接受 bool")
    eta_p = float(eta_polarization)
    if not math.isfinite(eta_p) or not 0.0 < eta_p <= 1.0:
        raise ValueError(f"eta_polarization 须在 (0,1] 内，得 {eta_p!r}")

    theta0 = 2.0 * math.atan(1.0 / (4.0 * fod))
    eta_s = _refl_ant.spillover_efficiency(theta0, q)
    eta_i = _refl_ant.illumination_efficiency(theta0, q)
    eta_rz = _refl_ant.ruze_efficiency(sol * _refl_ant.C0_M_S / f_hz, f_hz)
    eta_ap = eta_s * eta_i * eta_p * eta_rz
    gain_dbi = _refl_ant.gain_db(d_m, f_hz, eta_ap)
    return {
        "profile": profile,
        "q_power": q,
        "theta_rim_deg": math.degrees(theta0),
        "eta_spillover": eta_s,
        "eta_illumination": eta_i,
        "eta_polarization": eta_p,
        "eta_ruze": eta_rz,
        "eta_ap": eta_ap,
        "gain_dbi": gain_dbi,
        "note": (
            "薄注册包装：η_i 为口径面积分口径的射线映射实现（core 双路径"
            "互证）；η_p 为显式入参非物理模型；遮挡/馈损不在本键（core "
            "efficiency_budget/horn_wall_loss_db 同仓分端）；gain_dbi=η "
            "加权口径增益（无耗口径模型与方向性重合）"),
        "source": _SOURCE_REFLECTOR,
    }


def _num_q0(value: Any) -> float:
    """q=0 特例收敛（q_power 显式给 0 的合法档；bool/非有限拒绝）。"""
    if isinstance(value, bool):
        raise ValueError("q_power 不接受 bool")
    out = float(value)
    if not math.isfinite(out) or out < 0.0:
        raise ValueError(f"q_power 必须 ≥0 的有限数，得 {value!r}")
    return out


@register_calculator(
    "horn_aperture_efficiency",
    "最优角锥喇叭增益效率（W4-S13）：口径 "
    "a_p×b_p 与 E/H 面径向长 → η_ap（一阶 Fresnel 闭式 (21.4.3)，最优厚度"
    "条件 δ_H=3λ/8、δ_E=λ/4 → η_ap≈0.51 Balanis Ch.13 文献口径）、增益 "
    "G=η_ap·(4π/λ²)·a_p·b_p（(21.4.2)）、HPBW_E≈54°·λ/b_p、HPBW_H≈78°·λ/"
    "a_p（最优喇叭设计关系，大口径近似）。单源 core/horn_synthesis（公式"
    "零复制）；偏离最优以 delta_*/near_optimum 如实暴露",
    (("a_p_mm", "float mm 口径宽边 a_p（H 面，>0）"),
     ("b_p_mm", "float mm 口径窄边 b_p（E 面，>0）"),
     ("l_h_mm", "float mm H 面径向长 ρ₁（虚顶点→口径面，>0）"),
     ("l_e_mm", "float mm E 面径向长 ρ₂（虚顶点→口径面，>0）"),
     ("f_ghz", "float GHz 工作频率（>0；λ=自由空间 c/f）")),
    required=("a_p_mm", "b_p_mm", "l_h_mm", "l_e_mm", "f_ghz"),
)
def horn_aperture_efficiency(
    a_p_mm: float,
    b_p_mm: float,
    l_h_mm: float,
    l_e_mm: float,
    f_ghz: float,
) -> dict[str, Any]:
    """薄委托 core/horn_synthesis（σ 几何换算 + 增益装配 + HPBW 近似式）。"""
    a_p = _pos_finite(a_p_mm, "a_p_mm") * 1e-3
    b_p = _pos_finite(b_p_mm, "b_p_mm") * 1e-3
    rho_h = _pos_finite(l_h_mm, "l_h_mm") * 1e-3
    rho_e = _pos_finite(l_e_mm, "l_e_mm") * 1e-3
    f_hz = _pos_finite(f_ghz, "f_ghz") * 1e9
    lam = _horn_syn.C0 / f_hz
    # σ 参数定义（Orfanidis (21.4.9) 同式口径；core _geometry_sigmas 的
    # σa=A/√(2λRa) 直写——几何→σ 映射，效率/增益公式仍 core 单源）
    sigma_h = a_p / math.sqrt(2.0 * lam * rho_h)
    sigma_e = b_p / math.sqrt(2.0 * lam * rho_e)
    eta_ap = _horn_syn.aperture_efficiency(sigma_h, sigma_e)
    gain_linear = (4.0 * math.pi / lam**2) * a_p * b_p * eta_ap
    delta_h = sigma_h**2 / 4.0
    delta_e = sigma_e**2 / 4.0
    near_opt = (
        abs(delta_h - 0.375) <= _DELTA_OPT_TOL
        and abs(delta_e - 0.25) <= _DELTA_OPT_TOL
    )
    return {
        "lambda_mm": lam * 1e3,
        "sigma_h": sigma_h,
        "sigma_e": sigma_e,
        "delta_h_over_lambda": delta_h,
        "delta_e_over_lambda": delta_e,
        "near_optimum": near_opt,
        "eta_ap": eta_ap,
        "gain_linear": gain_linear,
        "gain_dbi": 10.0 * math.log10(gain_linear),
        "hpbw_e_deg": _HPBW_E_DEG_COEF * lam / b_p,
        "hpbw_h_deg": _HPBW_H_DEG_COEF * lam / a_p,
        "note": (
            "薄注册包装：η_ap/G 单源 core/horn_synthesis 一阶 Fresnel 口径"
            "面模型（无壁损/口面反射/边缘绕射）；HPBW 为最优喇叭设计关系"
            "近似式（a_p,b_p≳3λ 适用域，小口径偏差放大如实不守卫），偏离"
            "最优时仅量级参考（near_optimum/delta_* 判定暴露；精确方向图"
            "面走 horn_gain_exact_aperture）"),
        "source": _SOURCE_HORN,
    }
