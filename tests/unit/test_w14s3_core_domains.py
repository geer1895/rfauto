"""架构批 W14-S3 席锚树：内核新域批 4 五键（云雾衰减 P.840-9 两键+穿墙
建筑媒质 P.2040-4 两键+SAR 斜视多普勒几何一键）。

数值断言口径（#118 锚先独立实测再写死，锚值=开工日独立算术预算——测试
内表达式路径独立于键内实现（原始 SI 常数内联，不消费模块系数常量）；
#122 三态/UNVERIFIED 如实不凑绿）：

- 云雾比衰减（cloud_specific_attenuation）：①常数转录锚=ε₀(300K)=77.66、
  ε₁=0.0671ε₀、ε₂=3.52、f_p(300K)=20.20、f_s=39.8f_p 逐位（双 Debye 式
  (6)-(10) 原文值）；②K_l 数值锤（30GHz/273.75K=0.7583525209827271、
  100GHz=4.880396761488907——测试内独立算术逐位，itu-rpy 公开实现同式
  双源）；③ρ_l→0 退化=0 恒等+γ_c=K_l·ρ_l 线性恒等；④低频 Rayleigh f²
  标度（K_l(0.5)/K_l(1.0)=1/4 恒等+闭式极限系数带）；⑤300K f_p/fs 恒等
  逐位；⑥温度行为档（30GHz 降温 K_l 增：273.75K>288K>300K 单调）；
  ⑦f 越 [1,200] 域/负 ρ_l 显式拒绝。
- 斜路径云衰减（cloud_attenuation_slant）：①K_L 数值锤（30GHz=
  0.7078539583865608、100GHz=4.690657803867758，式(12) Gaussian 修正
  独立算术）；②θ=90° 退化 A_c=K_L·L 逐位（sin=1）+sin θ 标度
  （30°=2×90° 恒等）；③L→0 零分支 zero_reason 如实；④官方参考温档
  T=273.75K 语义（K_l@273.75 进 K_L 链）；⑤仰角越 [5,90]/L<0 拒绝。
- 材料电性质（building_material_properties）：①Table 3 转录锚（concrete
  1GHz ε′=5.24/σ=0.0462 逐位——b=0 恒值行 σ(1GHz)=c 精确）；②幂律标度
  σ(4)/σ(1)=4^0.7822 恒等；③ε″=σ/(ωε₀) 精确 vs 式(59) 圆化 17.98σ/f
  （rel +2.7e-4 带如实）；④tanδ=σ/(ωε₀ε′) 独立算术（concrete@1GHz
  0.1585<0.5 式(27a) 适用域声明）；⑤A_diel=1636σ/√ε′=33.01867422771128
  数值锤；⑥未知名/行频域越界拒绝。
- 墙板穿透（wall_slab_transmission）：①无耗能量守恒 |R|²+|T|²=1（d/θ
  多档，机器精度）；②半波窗 d=λ₀/(2√ε′) → |R|≈0/|T|=1（Airy 式内恒等
  结构）；③Brewster TM θ_B=atan(√ε′) → |R|≈0 逐位+TE 同角 |R|>0（极化
  分工）；④d→0 透明极限 |T|→1/|R|→0；⑤垂直入射混凝土界面反射功率
  |r|²=0.15717991920179167 独立算术（20cm 板 7.79dB 量级互证）；⑥材料
  名/显式档双给互斥+部分给拒绝+pol 非法拒绝。
- SAR 斜视多普勒（sar_doppler_geometry）：①头号锚 ψ=0 退化 f_dc=0 逐位+
  B_D=B_D_broadside 逐位；②f_dc=2v·sinψ/λ 独立算术（30° 档 =v/λ 逐位）
  +±ψ 反对称恒等；③B_D 精确三角式 vs 小角近似（rel≤1e-4 小 β 带）+
  正侧视 2v/D 工程口径带；④PRF 双约束（B_D 与 2|f_dc|+B_D）单调+判据
  面布尔如实；⑤驻留 T_sa=R_g·β/(v·cos²ψ)（30°/0° 比=sec²30°=4/3 逐位）
  +L_sa=v·T_sa 恒等；⑥ψ≥90/波束前缘 ψ+β/2≥90 显式拒绝。
"""

from __future__ import annotations

import cmath
import math

import pytest

from rfauto.core.calc_families.building_penetration import (
    building_material_properties,
    wall_slab_transmission,
)
from rfauto.core.calc_families.itu_link import (
    cloud_attenuation_slant,
    cloud_specific_attenuation,
)
from rfauto.core.calc_families.sar_geometry import sar_doppler_geometry
from rfauto.service.calculator_service import run_calculator

# 测试内独立物理常数（原始 SI 2019/CODATA 2018，不消费模块常量——#118）
_EPS0 = 8.8541878128e-12
_C0 = 299792458.0


def _kl_p840(f_ghz: float, t_k: float) -> float:
    """P.840-9 式(2)-(10) 测试内独立书写路径（与键实现同文献独立转录）。"""
    theta = 300.0 / t_k
    e0 = 77.66 + 103.3 * (theta - 1.0)
    e1 = 0.0671 * e0
    e2 = 3.52
    fp = 20.20 - 146.0 * (theta - 1.0) + 316.0 * (theta - 1.0) ** 2
    fs = 39.8 * fp
    epp = (f_ghz * (e0 - e1) / (fp * (1.0 + (f_ghz / fp) ** 2))
           + f_ghz * (e1 - e2) / (fs * (1.0 + (f_ghz / fs) ** 2)))
    ep = ((e0 - e1) / (1.0 + (f_ghz / fp) ** 2)
          + (e1 - e2) / (1.0 + (f_ghz / fs) ** 2) + e2)
    eta = (2.0 + ep) / epp
    return 0.819 * f_ghz / (epp * (1.0 + eta * eta))


# ─── cloud_specific_attenuation（云雾键 1）───────────────────────────────────

def test_cloud_debye_constants_transcription():
    """常数转录锚：ε₀/ε₁/ε₂/f_p/f_s @300K 逐位（式(6)-(10) 原文值）。"""
    res = cloud_specific_attenuation(30.0, 300.0, 0.5)
    assert res["eps0"] == pytest.approx(77.66, rel=1e-15)
    assert res["eps1"] == pytest.approx(0.0671 * 77.66, rel=1e-15)
    assert res["eps2"] == pytest.approx(3.52, rel=1e-15)
    assert res["f_p_ghz"] == pytest.approx(20.20, rel=1e-15)
    assert res["f_s_ghz"] == pytest.approx(39.8 * 20.20, rel=1e-15)


def test_cloud_kl_value_hammers_and_dual_path():
    """K_l 数值锤（测试内独立算术逐位）+itu-rpy 同式双源量级带。"""
    for f_ghz, t_k in ((30.0, 273.75), (100.0, 273.75), (30.0, 288.0)):
        res = cloud_specific_attenuation(f_ghz, t_k, 0.5)
        expect = _kl_p840(f_ghz, t_k)
        assert res["k_l_db_km_per_g_m3"] == pytest.approx(expect, rel=1e-14)
    # 开工日数值锤（独立算术预算，逐位）
    assert cloud_specific_attenuation(30.0, 273.75, 0.5)[
        "k_l_db_km_per_g_m3"] == pytest.approx(0.7583525209827271, rel=1e-12)
    assert cloud_specific_attenuation(100.0, 273.75, 0.5)[
        "k_l_db_km_per_g_m3"] == pytest.approx(4.880396761488907, rel=1e-12)


def test_cloud_zero_lwc_and_linearity():
    """ρ_l→0 退化=0 恒等 + γ_c=K_l·ρ_l 线性恒等（逐位）。"""
    assert cloud_specific_attenuation(30.0, 273.75, 0.0)[
        "gamma_cloud_db_per_km"] == 0.0
    kl = cloud_specific_attenuation(30.0, 273.75, 0.0)[
        "k_l_db_km_per_g_m3"]
    for rho in (0.01, 0.05, 0.5):
        res = cloud_specific_attenuation(30.0, 273.75, rho)
        assert res["gamma_cloud_db_per_km"] == pytest.approx(kl * rho,
                                                             rel=1e-15)


def test_cloud_low_frequency_rayleigh_f_squared_scaling():
    """低频 Rayleigh f² 标度：K_l(1)/K_l(2)=1/4 恒等带 + 闭式极限系数带。"""
    kl_lo = cloud_specific_attenuation(1.0, 273.75, 0.5)[
        "k_l_db_km_per_g_m3"]
    kl_hi = cloud_specific_attenuation(2.0, 273.75, 0.5)[
        "k_l_db_km_per_g_m3"]
    assert kl_lo / kl_hi == pytest.approx(0.25, rel=1e-3)
    # f→0 极限 K_l/f² → 0.819·a/(2+ε₀)²（a=dε″/df 低频斜率）闭式；
    # f=1 处 (f/f_p)² 有限修正 ~2.5e-5 → rel=1e-4 带
    theta = 300.0 / 273.75
    e0 = 77.66 + 103.3 * (theta - 1.0)
    fp = 20.20 - 146.0 * (theta - 1.0) + 316.0 * (theta - 1.0) ** 2
    fs = 39.8 * fp
    a_slope = (e0 - 0.0671 * e0) / fp + (0.0671 * e0 - 3.52) / fs
    limit = 0.819 * a_slope / (2.0 + e0) ** 2
    assert kl_lo == pytest.approx(limit, rel=1e-4)


def test_cloud_temperature_behavior_band_specific():
    """温度行为档：30GHz（f>f_p 带内）降温 K_l 单调增（273.75>288>300）。"""
    kls = [cloud_specific_attenuation(30.0, tk, 0.5)["k_l_db_km_per_g_m3"]
           for tk in (300.0, 288.0, 273.75)]
    assert kls == sorted(kls)  # 降温 K_l 单调增（f=30>f_p(T) 带内行为档）
    assert len(set(kls)) == 3


def test_cloud_domain_guards():
    """f 越 [1,200] Rayleigh 域/负 ρ_l 显式拒绝。"""
    with pytest.raises(ValueError):
        cloud_specific_attenuation(250.0, 273.75, 0.5)
    with pytest.raises(ValueError):
        cloud_specific_attenuation(0.5, 273.75, 0.5)
    with pytest.raises(ValueError):
        cloud_specific_attenuation(30.0, -5.0, 0.5)
    with pytest.raises(ValueError):
        cloud_specific_attenuation(30.0, 273.75, -1.0)


# ─── cloud_attenuation_slant（云雾键 2）──────────────────────────────────────

def test_cloud_slant_kl_mass_hammer():
    """K_L 数值锤：式(12) Gaussian 修正链独立算术逐位（分母 σ 无平方）。"""
    a1, a2, a3 = 0.1522, 11.51, -10.4912
    f1, f2 = -23.9589, 219.2096
    s1, s2 = 3.2991e3, 2.7595e6
    for f_ghz, hammer in ((30.0, 0.7078539583865608),
                          (100.0, 4.690657803867758)):
        res = cloud_attenuation_slant(f_ghz, 1.0, 90.0)
        kl273 = _kl_p840(f_ghz, 273.75)
        corr = (a1 * math.exp(-((f_ghz - f1) ** 2) / s1)
                + a2 * math.exp(-((f_ghz - f2) ** 2) / s2) + a3)
        assert res["k_l_273_db_km_per_g_m3"] == pytest.approx(kl273,
                                                              rel=1e-14)
        assert res["gaussian_correction"] == pytest.approx(corr, rel=1e-14)
        assert res["k_l_mass_db_per_mm"] == pytest.approx(kl273 * corr,
                                                          rel=1e-14)
        assert res["k_l_mass_db_per_mm"] == pytest.approx(hammer, rel=1e-12)


def test_cloud_slant_zenith_degenerate_and_sin_scaling():
    """θ=90° 退化 A_c=K_L·L 逐位（sin=1）+ A(30°)=2·A(90°) sin θ 标度恒等。"""
    zenith = cloud_attenuation_slant(100.0, 1.0, 90.0)
    assert zenith["sin_el"] == 1.0
    assert zenith["a_c_db"] == pytest.approx(
        zenith["k_l_mass_db_per_mm"], rel=1e-14)
    off = cloud_attenuation_slant(100.0, 1.0, 30.0)
    assert off["a_c_db"] == pytest.approx(2.0 * zenith["a_c_db"], rel=1e-14)
    # 独立算术：A=K_L·L/sin30° 逐位
    assert off["a_c_db"] == pytest.approx(
        off["k_l_mass_db_per_mm"] / 0.5, rel=1e-14)
    # 开工日数值锤
    assert off["a_c_db"] == pytest.approx(9.381315607735518, rel=1e-12)


def test_cloud_slant_zero_lwp_and_guards():
    """L→0 零分支 zero_reason 如实 + 仰角越 [5,90]/L<0 拒绝。"""
    zero = cloud_attenuation_slant(100.0, 0.0, 30.0)
    assert zero["a_c_db"] == 0.0 and "zero_reason" in zero
    with pytest.raises(ValueError):
        cloud_attenuation_slant(100.0, 1.0, 4.0)
    with pytest.raises(ValueError):
        cloud_attenuation_slant(100.0, 1.0, 95.0)
    with pytest.raises(ValueError):
        cloud_attenuation_slant(100.0, -1.0, 30.0)


# ─── building_material_properties（穿墙键 1）────────────────────────────────

def test_material_table3_transcription_and_power_law():
    """Table 3 转录锚（concrete@1GHz ε′=5.24/σ=0.0462 逐位）+σ 幂律标度。"""
    res = building_material_properties("concrete", 1.0)
    assert res["eps_prime"] == 5.24  # b=0 恒值行逐位
    assert res["sigma_s_per_m"] == 0.0462  # σ(1GHz)=c·1^d=c 精确
    brick = building_material_properties("brick", 2.0)
    assert brick["eps_prime"] == 3.91
    assert brick["sigma_s_per_m"] == pytest.approx(0.0238 * 2.0 ** 0.16,
                                                   rel=1e-15)
    # 幂律标度恒等：σ(4)/σ(1)=4^0.7822
    s4 = building_material_properties("concrete", 4.0)["sigma_s_per_m"]
    assert s4 / res["sigma_s_per_m"] == pytest.approx(4.0 ** 0.7822,
                                                      rel=1e-15)


def test_material_eps_dprime_exact_vs_rounded_eq59():
    """ε″=σ/(ωε₀) 精确路径 vs 式(59) 圆化 17.98σ/f（rel +2.7e-5 带如实）。"""
    res = building_material_properties("concrete", 1.0)
    exact = 0.0462 / (2.0 * math.pi * 1e9 * _EPS0)
    assert res["eps_dprime"] == pytest.approx(exact, rel=1e-15)
    assert res["eps_dprime"] == pytest.approx(17.98 * 0.0462 / 1.0,
                                              rel=3e-4)
    assert abs(res["eps_dprime_eq59_rounded"] / res["eps_dprime"]
               - 1.0) < 3e-4


def test_material_tan_delta_and_atten_rate_hammer():
    """tanδ 独立算术（<0.5 式(27a) 适用域）+ A_diel=1636σ/√ε′ 数值锤。"""
    res = building_material_properties("concrete", 1.0)
    tan_d = 0.0462 / (2.0 * math.pi * 1e9 * _EPS0 * 5.24)
    assert res["tan_delta"] == pytest.approx(tan_d, rel=1e-15)
    assert res["tan_delta"] < 0.5  # 式(27a) 声明域（Table 3 全介质行）
    assert res["atten_rate_db_per_m"] == pytest.approx(
        1636.0 * 0.0462 / math.sqrt(5.24), rel=1e-15)
    assert res["atten_rate_db_per_m"] == pytest.approx(33.01867422771128,
                                                       rel=1e-12)


def test_material_unknown_name_and_range_guards():
    """未知名/行频域越界显式拒绝（brick 主档 1-40GHz）。"""
    with pytest.raises(ValueError):
        building_material_properties("rebar", 1.0)
    with pytest.raises(ValueError):
        building_material_properties("brick", 60.0)
    with pytest.raises(ValueError):
        building_material_properties("glass", 0.01)  # glass 0.1-100


# ─── wall_slab_transmission（穿墙键 2）───────────────────────────────────────

def test_slab_lossless_energy_conservation():
    """无耗能量守恒 |R|²+|T|²=1（d/θ 多档机器精度——Airy 式内恒等）。"""
    for d in (0.01, 0.05, 0.111):
        for th in (0.0, 30.0, 60.0):
            for pol in ("te", "tm"):
                res = wall_slab_transmission(10.0, d, epsilon_r=4.0,
                                             sigma=0.0, polarization=pol,
                                             incidence_deg=th)
                assert res["power_reflection"] + res["power_transmission"] \
                    == pytest.approx(1.0, abs=1e-12)
                assert res["absorbed_fraction"] == pytest.approx(
                    0.0, abs=1e-12)


def test_slab_half_wave_window():
    """半波窗锚：d=λ₀/(2√ε′) → |R|≈0/|T|=1（ Fabry-Perot 透射共振恒等）。"""
    lam0 = _C0 / 10e9
    d_half = lam0 / (2.0 * math.sqrt(4.0))
    res = wall_slab_transmission(10.0, d_half, epsilon_r=4.0, sigma=0.0)
    assert res["reflection_coeff_abs"] < 1e-12
    assert res["transmission_coeff_abs"] == pytest.approx(1.0, rel=1e-12)


def test_slab_brewster_tm_and_te_contrast():
    """Brewster 锚：θ_B=atan(√ε′) TM |R|≈0 逐位 + TE 同角 |R|>0（分工）。"""
    theta_b = math.degrees(math.atan(math.sqrt(4.0)))
    tm = wall_slab_transmission(10.0, 0.01, epsilon_r=4.0, sigma=0.0,
                                polarization="tm", incidence_deg=theta_b)
    assert tm["reflection_coeff_abs"] < 1e-12
    assert tm["transmission_coeff_abs"] == pytest.approx(1.0, rel=1e-12)
    te = wall_slab_transmission(10.0, 0.01, epsilon_r=4.0, sigma=0.0,
                                polarization="te", incidence_deg=theta_b)
    assert te["reflection_coeff_abs"] > 0.1


def test_slab_zero_thickness_transparent_limit():
    """d→0 透明极限：|T|→1/|R|→0（式(43) e^{−j2q}→1 代数恒等）。"""
    res = wall_slab_transmission(10.0, 1e-12, epsilon_r=4.0, sigma=0.0)
    assert res["reflection_coeff_abs"] < 1e-9
    assert res["transmission_coeff_abs"] == pytest.approx(1.0, rel=1e-9)


def test_slab_concrete_normal_incidence_interface_hammer():
    """垂直入射混凝土界面反射功率独立算术（r=(1−√ε_rc)/(1+√ε_rc) 模）+板量级。"""
    eps_rc = complex(5.24, -0.0462 / (2.0 * math.pi * 1e9 * _EPS0))
    root = cmath.sqrt(eps_rc)
    r0 = (1.0 - root) / (1.0 + root)
    expect_pr = abs(r0) ** 2
    res = wall_slab_transmission(1.0, 0.2, material="concrete")
    assert res["eps_rc_real"] == pytest.approx(eps_rc.real, rel=1e-14)
    assert res["eps_rc_imag"] == pytest.approx(eps_rc.imag, rel=1e-14)
    assert expect_pr == pytest.approx(0.15717991920179167, rel=1e-12)
    # 20cm 混凝土板 1GHz：界面反射+材料吸收 → 7.79dB 穿透损耗量级
    assert res["penetration_loss_db"] == pytest.approx(7.787311876076101,
                                                       rel=1e-12)
    assert 0.0 < res["power_transmission"] < 1.0
    assert res["absorbed_fraction"] > 0.0  # 有耗板吸收>0


def test_slab_mode_exclusivity_and_guards():
    """材料名/显式档双给互斥 + 部分给 + pol 非法 + θ≥90 显式拒绝。"""
    with pytest.raises(ValueError):  # 双给互斥
        wall_slab_transmission(1.0, 0.2, material="concrete",
                               epsilon_r=5.24, sigma=0.0462)
    with pytest.raises(ValueError):  # 部分给
        wall_slab_transmission(1.0, 0.2, epsilon_r=5.24)
    with pytest.raises(ValueError):  # 全缺
        wall_slab_transmission(1.0, 0.2)
    with pytest.raises(ValueError):  # pol 非法
        wall_slab_transmission(1.0, 0.2, material="concrete",
                               polarization="vv")
    with pytest.raises(ValueError):  # θ≥90
        wall_slab_transmission(1.0, 0.2, material="concrete",
                               incidence_deg=90.0)
    with pytest.raises(ValueError):  # 负厚度
        wall_slab_transmission(1.0, -0.2, material="concrete")


# ─── sar_doppler_geometry（SAR 斜视键）───────────────────────────────────────

def test_sar_doppler_broadside_degenerate_head_anchor():
    """头号锚：ψ=0 退化 f_dc=0 逐位 + B_D==B_D_broadside 逐位（同式路径）。"""
    res = sar_doppler_geometry(200.0, 0.03, 1.0, 0.0)
    assert res["doppler_centroid_hz"] == 0.0
    assert res["doppler_bandwidth_hz"] == \
        res["broadside_doppler_bandwidth_hz"]
    # 正侧视工程口径带：B_D≈2v/D（小 β 近似）
    assert res["doppler_bandwidth_hz"] == pytest.approx(2.0 * 200.0 / 1.0,
                                                        rel=1e-4)


def test_sar_doppler_centroid_identity_and_sign_asymmetry():
    """f_dc=2v·sinψ/λ 独立算术（30° 档=v/λ 逐位）+ ±ψ 反对称恒等。"""
    res = sar_doppler_geometry(200.0, 0.03, 1.0, 30.0)
    assert res["doppler_centroid_hz"] == pytest.approx(2.0 * 200.0 * 0.5
                                                       / 0.03, rel=1e-15)
    assert res["doppler_centroid_hz"] == pytest.approx(6666.666666666666,
                                                       rel=1e-12)
    res20 = sar_doppler_geometry(200.0, 0.03, 1.0, 20.0)
    assert res20["doppler_centroid_hz"] == pytest.approx(
        2.0 * 200.0 * math.sin(math.radians(20.0)) / 0.03, rel=1e-15)
    # 带宽对 ψ+β/2 与 ψ−β/2 对称 → 同 ψ 带宽与工程近似小角式同带
    assert res20["doppler_bandwidth_hz"] == pytest.approx(
        res20["doppler_bandwidth_small_angle_hz"], rel=1e-4)


def test_sar_doppler_bandwidth_exact_vs_small_angle():
    """B_D 精确三角式 vs 小角近似（小 β 带 rel≤1e-4）+ 随 ψ 收窄单调。"""
    v, lam, d = 7500.0, 0.03, 2.0
    bds = []
    for psi_deg in (0.0, 20.0, 45.0, 60.0):
        res = sar_doppler_geometry(v, lam, d, psi_deg)
        beta = lam / d
        psi = math.radians(psi_deg)
        exact = (2.0 * v / lam) * (math.sin(psi + beta / 2.0)
                                   - math.sin(psi - beta / 2.0))
        assert res["doppler_bandwidth_hz"] == pytest.approx(exact, rel=1e-14)
        assert res["doppler_bandwidth_hz"] == pytest.approx(
            res["doppler_bandwidth_small_angle_hz"], rel=1e-4)
        bds.append(res["doppler_bandwidth_hz"])
    assert bds == sorted(bds, reverse=True)  # ψ↑ B_D↓（cos ψ 收窄）
    assert len(set(bds)) == 4


def test_sar_doppler_prf_constraints_and_dwell():
    """PRF 双约束判据面布尔如实 + T_sa=sec²ψ 修边恒等 + L_sa=v·T_sa。"""
    ok = sar_doppler_geometry(200.0, 0.03, 1.0, 30.0, prf_hz=8000.0,
                              ground_range_m=100e3)
    b_d = ok["doppler_bandwidth_hz"]
    f_dc = ok["doppler_centroid_hz"]
    assert ok["prf_min_doppler_hz"] == pytest.approx(b_d, rel=1e-15)
    assert ok["prf_min_centroid_shifted_hz"] == pytest.approx(
        2.0 * abs(f_dc) + b_d, rel=1e-15)
    assert ok["prf_sufficient_doppler"] is True  # 8000 > 346
    assert ok["prf_sufficient_centroid_shifted"] is False  # 8000 < 13680
    tight = sar_doppler_geometry(200.0, 0.03, 1.0, 30.0, prf_hz=14000.0)
    assert tight["prf_sufficient_doppler"] is True
    assert tight["prf_sufficient_centroid_shifted"] is True
    # 驻留时间：T(30°)/T(0°)=sec²30°=4/3 逐位（平地角速度 dψ/dt=v·cos²ψ/R_g）
    t0 = sar_doppler_geometry(200.0, 0.03, 1.0, 0.0,
                              ground_range_m=100e3)["dwell_time_s"]
    assert ok["dwell_time_s"] / t0 == pytest.approx(1.0 / math.cos(
        math.radians(30.0)) ** 2, rel=1e-14)
    assert ok["dwell_time_s"] == pytest.approx(19.999999999999996, rel=1e-12)
    assert ok["synthetic_aperture_length_m"] == pytest.approx(
        200.0 * ok["dwell_time_s"], rel=1e-14)


def test_sar_doppler_domain_guards():
    """ψ≥90/波束前缘 ψ+β/2≥90/非正参 显式拒绝。"""
    with pytest.raises(ValueError):  # ψ≥90 视轴转出前半球
        sar_doppler_geometry(200.0, 0.03, 1.0, 95.0)
    with pytest.raises(ValueError):  # ψ+β/2≥90（宽波束+大斜视）
        sar_doppler_geometry(200.0, 0.03, 0.05, 88.0)
    with pytest.raises(ValueError):
        sar_doppler_geometry(0.0, 0.03, 1.0, 30.0)
    with pytest.raises(ValueError):
        sar_doppler_geometry(200.0, 0.03, 1.0, 30.0, prf_hz=0.0)
    with pytest.raises(ValueError):
        sar_doppler_geometry(200.0, 0.03, 1.0, 30.0, ground_range_m=-1.0)


# ─── 服务层信封（envelope 契约面抽验）────────────────────────────────────────

def test_service_envelope_roundtrip():
    """run_calculator 信封面：ok=True + 关键字段在场（信封契约抽验）。"""
    out = run_calculator("cloud_attenuation_slant",
                         {"f_ghz": 100.0, "lwp_kg_m2": 1.0,
                          "elevation_deg": 30.0})
    assert out["ok"] is True
    assert out["result"]["a_c_db"] == pytest.approx(9.381315607735518,
                                                  rel=1e-12)
    out2 = run_calculator("wall_slab_transmission",
                          {"f_ghz": 1.0, "thickness_m": 0.2,
                           "material": "concrete"})
    assert out2["ok"] is True
    assert out2["result"]["penetration_loss_db"] > 0.0
    out3 = run_calculator("sar_doppler_geometry",
                          {"platform_velocity_mps": 200.0,
                           "wavelength_m": 0.03, "antenna_length_m": 1.0,
                           "squint_deg": 30.0})
    assert out3["ok"] is True
    assert out3["result"]["doppler_centroid_hz"] == pytest.approx(
        6666.666666666666, rel=1e-12)
