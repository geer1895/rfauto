"""aurora_g W7-S3 席锚树：内核新域批 2 七键（HF 电离层天波三键+FMCW
波形映射两键+SAR 几何两键）。

数值断言口径（#118 锚先独立实测再写死，锚值=开工日独立算术预算——测试
内表达式路径独立于键内实现（原始 SI 常数内联，不消费模块系数常量）；
#122 三态/UNVERIFIED 如实不凑绿）：

- HF 天波（critical_frequency）：①系数转录锚=e/(2π√(m_e·ε₀)) 测试内
  独立算术逐位（非键内 F_P_COEF_HZ_M15 消费）+N_e=1e12 m⁻³ → 8.978663
  MHz 数值锤+教科书 9√Ne[kHz,cm⁻³] 口径带（≤0.3%）；②反解闭环
  N_e=(f/coef)²→回代 f_p 逐位回收（双向恒等）+f_p²∝N_e 标度（N_e×4 →
  f_p×2 逐位）；③零/负/NaN 密度显式拒绝。
- 割线定律（secant_law_muf）：①sec(60°)=2 → MUF=2·f_o（approx rel
  1e-12）+i→0 退化 MUF==f_o 逐位+i 单调递增；②平地几何档 sin(i)=
  (d/2)/√(h²+(d/2)²) 独立算术（h=300km/d=2000km → i=73.3008°/sec=
  3.4801——经典 M(3000) 因子量级互证/MUF 逐位）；③i≥90° 发散守卫+
  直给/几何档双给与缺省互斥+几何档部分给显式拒绝；④sec(i)=1/cos(i)
  恒等逐位抽查。
- 折射指数（ionospheric_plasma_frequency）：①传播档 n²=1−(f_p/f)² 独
  立算术+v_ph·v_g=c² 恒等+v_ph>c（色散相速超光速正常属性）；②f=f_p
  截止 n=0/f<f_p 渐消 n=None 且 n²<0（不出 NaN——#122）；③f≤0/N_e≤0
  显式拒绝。
- FMCW（fmcw_range_doppler）：①前向拍频 f_b=2SR/c 与 f_D=2v·fc/c 独立
  算术+f_up=f_b−f_D/f_down=f_b+f_D 逐位+静止目标 f_up==f_down 逐位对
  称；②forward→inverse→forward roundtrip 逐位闭环；③解耦恒等式
  (f_up+f_down)/2=2SR/c、(f_down−f_up)/2=f_D 独立复算+远离目标（v<0）
  f_up>f_down 方向恒等；④拍频负值折叠（|f_D|>f_b,R）显式拒绝+mode 非
  法/缺参显式拒绝。
- FMCW 分辨率（fmcw_bandwidth_range_resolution）：①ΔR=c/(2B) 独立算术
  （1GHz→14.99cm/4GHz→3.75cm 车载口径）；②IF 量程面 R_max=c·BW_IF/(2S)
  独立算术+f_b(R_max)==BW_IF 饱和恒等逐位+T_chirp=B/S；③IF 面部分给/
  B≤0 显式拒绝。
- SAR 方位分辨率（sar_azimuth_resolution）：①头号锚 δ_az=D/2 与 R、λ
  无关——变更 R/λ 平台速度输出 δ_az 逐位不变；②真实孔径对照面 θ=λ/D、
  δ_ra=R·λ/D、L_sa、T_sa=L_sa/v 独立算术+δ_ra≫δ_az 对比（12km vs 1m）；
  ③孔径面部分给/速度缺孔径面显式拒绝。
- SAR 条带（sar_swath_coverage）：①几何闭式 R=h/cosθ、G=h·tanθ、
  W_ground=h·(tan_far−tan_near)、W_slant 独立算术逐位；②PRF 不模糊窗
  z_amb=c/(2·PRF) 恒等+2kHz 窗内（74.9km>181.7km 斜距条带？否——判据
  W_slant≤z_amb 实测 False 如实钉）/高 PRF 更窄窗单调；③天线照明面
  β=λ/D_w、W_beam=R_mid·β/cosθ_mid 独立算术；④角序倒置/θ_far≥90/照明
  面部分给显式拒绝。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.calc_families.fmcw_radar import (
    fmcw_bandwidth_range_resolution,
    fmcw_range_doppler,
)
from rfauto.core.calc_families.hf_skywave import (
    critical_frequency,
    ionospheric_plasma_frequency,
    secant_law_muf,
)
from rfauto.core.calc_families.sar_geometry import (
    sar_azimuth_resolution,
    sar_swath_coverage,
)

# 测试内独立物理常数（原始 SI 2021/CODATA 2018，不消费模块常量——#118）
_E = 1.602176634e-19
_ME = 9.1093837015e-31
_EPS0 = 8.8541878128e-12
_C = 299792458.0
_COEF = _E / (2.0 * math.pi * math.sqrt(_ME * _EPS0))  # 8.978662820487434


# ─── critical_frequency（HF 天波键 1）────────────────────────────────────────

def test_critical_frequency_coefficient_transcription_and_value():
    """系数转录锚（测试内独立算术逐位）+F2 层典型值+教科书口径带。"""
    res = critical_frequency(1e12)
    # 系数逐位=测试内独立算术（原始常数路径）
    assert res["coefficient_hz_m15"] == pytest.approx(_COEF, rel=1e-15)
    # N_e=1e12 m⁻³ → f_p 数值锤（开工日独立算术 8.978662820487434 MHz）
    assert res["f_p_hz"] == pytest.approx(_COEF * 1e6, rel=1e-15)
    assert res["f_p_mhz"] == pytest.approx(8.978662820487434, rel=1e-12)
    # 教科书 "9√Ne [kHz, cm⁻³]" 圆化口径带（1e12 m⁻³ = 1e6 cm⁻³ → 9 MHz）
    assert abs(res["f_p_mhz"] - 9.0) / 9.0 <= 0.003


def test_critical_frequency_inverse_closure_and_scaling():
    """反解闭环 N_e=(f/coef)²→回代逐位回收 + f_p²∝N_e 标度恒等。"""
    f_target = 10e6
    ne_inverse = (f_target / _COEF) ** 2
    res = critical_frequency(ne_inverse)
    assert res["f_p_hz"] == pytest.approx(f_target, rel=1e-12)
    # 标度：N_e×4 → f_p×2（√ 标度恒等）
    lo = critical_frequency(1e11)
    hi = critical_frequency(4e11)
    assert hi["f_p_hz"] == pytest.approx(2.0 * lo["f_p_hz"], rel=1e-15)


def test_critical_frequency_domain_guards():
    """零/负/非有限电子密度显式拒绝（任务书守卫纪律）。"""
    for bad in (0.0, -1e12, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            critical_frequency(bad)


# ─── secant_law_muf（HF 天波键 2）────────────────────────────────────────────

def test_muf_secant_identity_degenerate_and_monotone():
    """sec(60°)=2 恒等 + i→0 退化 MUF==f_o 逐位 + i 单调递增。"""
    fo = 8e6
    res60 = secant_law_muf(fo, incidence_deg=60.0)
    assert res60["secant_factor"] == pytest.approx(2.0, rel=1e-12)
    assert res60["muf_hz"] == pytest.approx(16e6, rel=1e-12)
    # i→0 退化恒等：MUF==f_o 逐位（cos(0)=1 精确）
    res0 = secant_law_muf(fo, incidence_deg=0.0)
    assert res0["muf_hz"] == fo
    assert res0["secant_factor"] == 1.0
    # sec(i) 在 [0,90) 单调递增 → MUF 单调
    mufs = [secant_law_muf(fo, incidence_deg=i)["muf_hz"]
            for i in (10.0, 30.0, 50.0, 70.0, 80.0)]
    assert mufs == sorted(mufs)
    assert len(set(mufs)) == len(mufs)
    # sec 恒等逐位抽查：MUF/f_o == 1/cos(i) 独立算术
    i_rad = math.radians(35.0)
    res35 = secant_law_muf(fo, incidence_deg=35.0)
    assert res35["muf_hz"] / fo == pytest.approx(1.0 / math.cos(i_rad),
                                                 rel=1e-14)


def test_muf_flat_earth_geometry_path():
    """平地单跳几何档 sin(i)=(d/2)/√(h²+(d/2)²) 测试内独立算术逐位。"""
    h_km, d_km = 300.0, 2000.0
    half = d_km * 500.0  # (d/2) m
    hm = h_km * 1000.0
    i_exp = math.asin(half / math.sqrt(hm * hm + half * half))
    sec_exp = 1.0 / math.cos(i_exp)
    res = secant_law_muf(8e6, hop_km=d_km, virtual_height_km=h_km)
    assert res["geometry"] == "flat_earth_single_hop"
    assert res["incidence_rad"] == pytest.approx(i_exp, rel=1e-14)
    assert res["secant_factor"] == pytest.approx(sec_exp, rel=1e-14)
    assert res["muf_hz"] == pytest.approx(8e6 * sec_exp, rel=1e-14)
    # 开工日数值锤：i=73.3008°、sec=3.4801（平地口径；经典 M(3000)F2
    # 曲线因子量级一致——球形地球修正在 ITU 曲线面，本键如实声明平地）
    assert res["incidence_deg"] == pytest.approx(73.30075576600639,
                                                 rel=1e-12)
    assert res["secant_factor"] == pytest.approx(3.480102169636853,
                                                 rel=1e-12)


def test_muf_divergence_and_path_exclusivity_guards():
    """i≥90° 发散守卫 + 直给/几何档互斥 + 缺省/部分给显式拒绝。"""
    with pytest.raises(ValueError):  # i=90 → cos=0 MUF 无界
        secant_law_muf(8e6, incidence_deg=90.0)
    with pytest.raises(ValueError):  # i>90 域外
        secant_law_muf(8e6, incidence_deg=100.0)
    with pytest.raises(ValueError):  # 双给互斥
        secant_law_muf(8e6, incidence_deg=30.0, hop_km=2000.0,
                       virtual_height_km=300.0)
    with pytest.raises(ValueError):  # 全缺
        secant_law_muf(8e6)
    with pytest.raises(ValueError):  # 几何档部分给
        secant_law_muf(8e6, hop_km=2000.0)


# ─── ionospheric_plasma_frequency（HF 天波键 3）──────────────────────────────

def test_plasma_index_propagating_identity_and_velocities():
    """传播档 n² 独立算术 + v_ph·v_g=c² 恒等 + v_ph>c 色散属性。"""
    ne, f = 1e12, 20e6
    fp = _COEF * math.sqrt(ne)
    res = ionospheric_plasma_frequency(ne, f)
    n2_exp = 1.0 - (fp / f) ** 2
    assert res["n_squared"] == pytest.approx(n2_exp, rel=1e-14)
    assert res["n"] == pytest.approx(math.sqrt(n2_exp), rel=1e-14)
    assert res["propagating"] is True
    # v_ph·v_g = c² 恒等（冷等离子体标度）
    assert (res["phase_velocity_mps"] * res["group_velocity_mps"]
            == pytest.approx(_C * _C, rel=1e-12))
    assert res["phase_velocity_mps"] > _C  # 相速超光速=色散正常属性
    assert res["group_velocity_mps"] < _C
    # n 由 n² 独立开方路径复核
    assert res["n"] ** 2 == pytest.approx(res["n_squared"], rel=1e-14)


def test_plasma_index_cutoff_and_evanescent_honest():
    """f=f_p 截止 n=0；f<f_p 渐消 n=None 且 n²<0（不出 NaN——#122）。"""
    ne = 1e12
    fp = _COEF * math.sqrt(ne)
    cut = ionospheric_plasma_frequency(ne, fp)
    assert cut["n"] == 0.0 and cut["n_squared"] == 0.0
    assert cut["propagating"] is False
    assert cut["phase_velocity_mps"] is None
    evo = ionospheric_plasma_frequency(ne, 5e6)
    assert evo["n"] is None
    assert evo["n_squared"] < 0.0
    assert evo["propagating"] is False
    assert evo["phase_velocity_mps"] is None


def test_plasma_index_domain_guards():
    """f≤0/N_e≤0 显式拒绝。"""
    with pytest.raises(ValueError):
        ionospheric_plasma_frequency(0.0, 20e6)
    with pytest.raises(ValueError):
        ionospheric_plasma_frequency(1e12, 0.0)
    with pytest.raises(ValueError):
        ionospheric_plasma_frequency(1e12, -1.0)


# ─── fmcw_range_doppler（FMCW 键 1）──────────────────────────────────────────

def test_fmcw_forward_beat_identities_and_stationary_symmetry():
    """前向拍频独立算术逐位 + 静止目标 f_up==f_down 对称恒等。"""
    slope, r_m, v_mps, fc = 1e12, 100.0, 30.0, 77e9
    res = fmcw_range_doppler("forward", slope, range_m=r_m,
                             velocity_mps=v_mps, carrier_hz=fc)
    f_b_exp = slope * 2.0 * r_m / _C
    f_d_exp = 2.0 * v_mps * fc / _C
    assert res["range_beat_hz"] == pytest.approx(f_b_exp, rel=1e-15)
    assert res["doppler_hz"] == pytest.approx(f_d_exp, rel=1e-15)
    assert res["f_up_hz"] == pytest.approx(f_b_exp - f_d_exp, rel=1e-15)
    assert res["f_down_hz"] == pytest.approx(f_b_exp + f_d_exp, rel=1e-15)
    # 开工日数值锤
    assert res["f_up_hz"] == pytest.approx(651717.5291981495, rel=1e-12)
    assert res["f_down_hz"] == pytest.approx(682538.8515944588, rel=1e-12)
    # 静止目标对称恒等（逐位）
    still = fmcw_range_doppler("forward", slope, range_m=r_m,
                               velocity_mps=0.0, carrier_hz=fc)
    assert still["f_up_hz"] == still["f_down_hz"]
    assert still["f_up_hz"] == f_b_exp


def test_fmcw_roundtrip_closure():
    """forward→inverse→forward roundtrip 逐位闭环（#118 回收锚）。"""
    slope, r_m, v_mps, fc = 1e12, 137.5, -12.5, 24e9
    fwd = fmcw_range_doppler("forward", slope, range_m=r_m,
                             velocity_mps=v_mps, carrier_hz=fc)
    inv = fmcw_range_doppler("inverse", slope, f_up_hz=fwd["f_up_hz"],
                             f_down_hz=fwd["f_down_hz"], carrier_hz=fc)
    assert inv["range_m"] == pytest.approx(r_m, rel=1e-12)
    assert inv["velocity_mps"] == pytest.approx(v_mps, rel=1e-12)
    # 远离目标（v<0）方向恒等：f_up > f_down
    assert fwd["f_up_hz"] > fwd["f_down_hz"]


def test_fmcw_decoupling_identity():
    """解耦恒等式 (f_up+f_down)/2=2SR/c、(f_down−f_up)/2=f_D 独立复算。"""
    slope, r_m, v_mps, fc = 5e11, 250.0, 40.0, 60e9
    res = fmcw_range_doppler("forward", slope, range_m=r_m,
                             velocity_mps=v_mps, carrier_hz=fc)
    mean_exp = slope * 2.0 * r_m / _C
    f_d_full = 2.0 * v_mps * fc / _C
    assert 0.5 * (res["f_up_hz"] + res["f_down_hz"]) == pytest.approx(
        mean_exp, rel=1e-14)
    assert 0.5 * (res["f_down_hz"] - res["f_up_hz"]) == pytest.approx(
        f_d_full, rel=1e-14)
    assert res["doppler_hz"] == pytest.approx(f_d_full, rel=1e-14)
    # 反解路径同恒等式：R=c(f_up+f_down)/(4S)
    inv = fmcw_range_doppler("inverse", slope, f_up_hz=res["f_up_hz"],
                             f_down_hz=res["f_down_hz"])
    assert inv["range_m"] == pytest.approx(r_m, rel=1e-12)


def test_fmcw_beat_fold_guard_and_mode_guards():
    """拍频负值折叠（|f_D|>f_b,R）+ mode 非法/缺参显式拒绝。"""
    # 极低速 chirp+高速目标 → |f_D|>f_b,R → 一阶解耦模型折叠
    with pytest.raises(ValueError):
        fmcw_range_doppler("forward", 1e10, range_m=100.0,
                           velocity_mps=2000.0, carrier_hz=77e9)
    with pytest.raises(ValueError):
        fmcw_range_doppler("sideways", 1e12)
    with pytest.raises(ValueError):  # inverse 缺拍频
        fmcw_range_doppler("inverse", 1e12)
    with pytest.raises(ValueError):  # forward 缺载频
        fmcw_range_doppler("forward", 1e12, range_m=100.0,
                           velocity_mps=30.0)
    with pytest.raises(ValueError):  # 负拍频输入
        fmcw_range_doppler("inverse", 1e12, f_up_hz=-1.0, f_down_hz=10.0)


# ─── fmcw_bandwidth_range_resolution（FMCW 键 2）─────────────────────────────

def test_fmcw_resolution_identity_two_bandwidths():
    """ΔR=c/(2B) 独立算术（1GHz→14.99cm；4GHz→3.75cm 车载口径）。"""
    for bw, expect in ((1e9, 0.149896229), (4e9, 0.03747405725)):
        res = fmcw_bandwidth_range_resolution(bw)
        assert res["range_resolution_m"] == pytest.approx(_C / (2.0 * bw),
                                                          rel=1e-15)
        assert res["range_resolution_m"] == pytest.approx(expect, rel=1e-9)
        assert "max_range_m" not in res  # 纯分辨率档无 IF 面


def test_fmcw_if_range_saturation_identity():
    """IF 量程面 R_max=c·BW_IF/(2S) 独立算术 + f_b(R_max)==BW_IF 饱和恒等
    +T_chirp=B/S。"""
    bw, bwif, slope = 1e9, 15e6, 1e12
    res = fmcw_bandwidth_range_resolution(
        bw, if_bandwidth_hz=bwif, slope_hz_per_s=slope)
    r_max_exp = _C * bwif / (2.0 * slope)
    assert res["max_range_m"] == pytest.approx(r_max_exp, rel=1e-15)
    # 饱和恒等：量程处拍频恰满 IF 带（逐位同值路径）
    assert res["beat_at_rmax_hz"] == pytest.approx(bwif, rel=1e-15)
    assert res["chirp_duration_s"] == pytest.approx(bw / slope, rel=1e-15)
    # 开工日数值锤
    assert res["max_range_m"] == pytest.approx(2248.443435, rel=1e-9)


def test_fmcw_if_partial_face_and_domain_guards():
    """IF 面部分给显式拒绝 + B≤0/斜率≤0 域守卫。"""
    with pytest.raises(ValueError):
        fmcw_bandwidth_range_resolution(1e9, if_bandwidth_hz=15e6)
    with pytest.raises(ValueError):
        fmcw_bandwidth_range_resolution(1e9, slope_hz_per_s=1e12)
    with pytest.raises(ValueError):
        fmcw_bandwidth_range_resolution(0.0)
    with pytest.raises(ValueError):
        fmcw_bandwidth_range_resolution(1e9, if_bandwidth_hz=15e6,
                                        slope_hz_per_s=0.0)


# ─── sar_azimuth_resolution（SAR 键 1）───────────────────────────────────────

def test_sar_daz_independence_head_anchor():
    """头号锚：δ_az=D/2 与 R、λ、v 无关——变更输出逐位不变。"""
    base = sar_azimuth_resolution(2.0)
    assert base["azimuth_resolution_m"] == 1.0
    v1 = sar_azimuth_resolution(2.0, range_m=500e3, wavelength_m=0.03)
    v2 = sar_azimuth_resolution(2.0, range_m=1200e3, wavelength_m=0.055)
    v3 = sar_azimuth_resolution(
        2.0, range_m=800e3, wavelength_m=0.03, platform_velocity_mps=7500.0)
    # R/λ/v 变更 δ_az 逐位不变（聚焦 SAR"悖论"恒等式）
    assert v1["azimuth_resolution_m"] == v2["azimuth_resolution_m"] == \
        v3["azimuth_resolution_m"] == base["azimuth_resolution_m"]
    # D=0.5m → δ_az=0.25m
    assert sar_azimuth_resolution(0.5)["azimuth_resolution_m"] == 0.25


def test_sar_real_aperture_reference_faces():
    """真实孔径对照面 θ=λ/D、δ_ra=R·λ/D、L_sa、T_sa 独立算术+对比量级。"""
    d_ant, r_m, lam, v_mps = 2.0, 800e3, 0.03, 7500.0
    res = sar_azimuth_resolution(
        d_ant, range_m=r_m, wavelength_m=lam,
        platform_velocity_mps=v_mps)
    assert res["real_aperture_beamwidth_rad"] == pytest.approx(
        lam / d_ant, rel=1e-15)
    assert res["real_aperture_resolution_m"] == pytest.approx(
        r_m * lam / d_ant, rel=1e-15)
    assert res["synthetic_aperture_length_m"] == pytest.approx(
        r_m * lam / d_ant, rel=1e-15)
    assert res["integration_time_s"] == pytest.approx(
        r_m * lam / d_ant / v_mps, rel=1e-15)
    # 开工日数值锤：δ_ra=L_sa=12km、T_sa=1.6s；δ_ra≫δ_az（12km vs 1m）
    assert res["real_aperture_resolution_m"] == pytest.approx(12000.0,
                                                              rel=1e-12)
    assert res["integration_time_s"] == pytest.approx(1.6, rel=1e-12)
    assert res["real_aperture_resolution_m"] > 1e4 * \
        res["azimuth_resolution_m"]


def test_sar_partial_faces_rejected():
    """孔径面部分给/速度缺孔径面显式拒绝。"""
    with pytest.raises(ValueError):
        sar_azimuth_resolution(2.0, range_m=800e3)
    with pytest.raises(ValueError):
        sar_azimuth_resolution(2.0, wavelength_m=0.03)
    with pytest.raises(ValueError):
        sar_azimuth_resolution(2.0, platform_velocity_mps=7500.0)
    with pytest.raises(ValueError):
        sar_azimuth_resolution(0.0)


# ─── sar_swath_coverage（SAR 键 2）───────────────────────────────────────────

def test_sar_swath_geometry_closed_form_identities():
    """条带几何闭式 R=h/cosθ、G=h·tanθ、W_ground/W_slant 独立算术逐位。"""
    h, th_n, th_f = 700e3, 30.0, 45.0
    res = sar_swath_coverage(h, th_n, th_f)
    rn = h / math.cos(math.radians(th_n))
    rf = h / math.cos(math.radians(th_f))
    gn = h * math.tan(math.radians(th_n))
    gf = h * math.tan(math.radians(th_f))
    assert res["slant_range_near_m"] == pytest.approx(rn, rel=1e-15)
    assert res["slant_range_far_m"] == pytest.approx(rf, rel=1e-15)
    assert res["ground_range_near_m"] == pytest.approx(gn, rel=1e-15)
    assert res["ground_range_far_m"] == pytest.approx(gf, rel=1e-15)
    assert res["swath_ground_m"] == pytest.approx(gf - gn, rel=1e-15)
    assert res["swath_slant_m"] == pytest.approx(rf - rn, rel=1e-15)
    # 开工日数值锤
    assert res["swath_ground_m"] == pytest.approx(295854.8115672619,
                                                  rel=1e-12)
    assert res["swath_slant_m"] == pytest.approx(181659.1167956905,
                                                 rel=1e-12)
    # 近远角单调：斜距/地距随角单调递增
    assert res["slant_range_far_m"] > res["slant_range_near_m"]
    assert res["ground_range_far_m"] > res["ground_range_near_m"]


def test_sar_swath_prf_unambiguous_window():
    """PRF 不模糊窗 z_amb=c/(2·PRF) 恒等 + 窗判据 W_slant≤z_amb 如实。"""
    res = sar_swath_coverage(700e3, 30.0, 45.0, prf_hz=2000.0)
    z_exp = _C / (2.0 * 2000.0)
    assert res["unambiguous_slant_window_m"] == pytest.approx(z_exp,
                                                              rel=1e-15)
    # 开工日数值锤：z_amb(2kHz)=74.948km < W_slant=181.66km → 判据 False
    assert res["unambiguous_slant_window_m"] == pytest.approx(
        74948.1145, rel=1e-9)
    assert res["swath_within_window"] is False
    # 高 PRF 窗更窄（c/(2·PRF) 单调递减）+窄条带窗内 True（平角档）
    hi = sar_swath_coverage(700e3, 30.0, 45.0, prf_hz=5000.0)
    assert hi["unambiguous_slant_window_m"] < \
        res["unambiguous_slant_window_m"]
    narrow = sar_swath_coverage(700e3, 30.0, 31.0, prf_hz=2000.0)
    assert narrow["swath_within_window"] is True
    assert narrow["swath_slant_m"] <= narrow["unambiguous_slant_window_m"]


def test_sar_swath_antenna_illumination_face():
    """天线照明面 β=λ/D_w、W_beam=R_mid·β/cosθ_mid 独立算术。"""
    h, th_n, th_f, d_w, lam = 700e3, 30.0, 45.0, 0.5, 0.03
    res = sar_swath_coverage(h, th_n, th_f, antenna_width_m=d_w,
                             wavelength_m=lam)
    th_mid = math.radians(0.5 * (th_n + th_f))
    beta_exp = lam / d_w
    w_beam_exp = (h / math.cos(th_mid)) * beta_exp / math.cos(th_mid)
    assert res["cross_track_beamwidth_rad"] == pytest.approx(beta_exp,
                                                             rel=1e-15)
    assert res["illuminated_swath_m"] == pytest.approx(w_beam_exp,
                                                       rel=1e-15)


def test_sar_swath_angle_and_face_guards():
    """角序倒置/θ_far≥90/照明面部分给显式拒绝。"""
    with pytest.raises(ValueError):  # 角序倒置
        sar_swath_coverage(700e3, 45.0, 30.0)
    with pytest.raises(ValueError):  # θ_far≥90 切地平线发散
        sar_swath_coverage(700e3, 30.0, 90.0)
    with pytest.raises(ValueError):  # θ_near<0 域外
        sar_swath_coverage(700e3, -5.0, 45.0)
    with pytest.raises(ValueError):  # 照明面部分给
        sar_swath_coverage(700e3, 30.0, 45.0, antenna_width_m=0.5)
