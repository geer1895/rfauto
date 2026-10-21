"""架构批 W11-S4 席锚树：内核新域批 3 四键（FMCW 域内扩展两键+微带
全族扩展两键）。

数值断言口径（#118 锚先独立实测再写死，锚值=开工日独立算术预算——测试
内表达式路径独立于键内实现（原始 SI 常数内联/独立 skrf media 构造，不消
费模块系数常量）；#122 三态/UNVERIFIED 如实不凑绿；网源逐字在
内部证据目录）：

- FMCW chirp 设计（fmcw_chirp_design）：①IF 带限档 B=c/(2ΔR)（0.15m→
  999.31MHz）与 S=c·BW_IF/(2R_max) 独立算术+量程处拍频==BW_IF 饱和恒等
  （rel 1e-15）+fs_min=2·f_b(R_max)；②跨档一致性=BW_IF=fs/2 时 IF 档与
  Nyquist 档斜率逐位一致+显式档 roundtrip（设计斜率回灌既有键
  fmcw_bandwidth_range_resolution 回收 R_max）；③载频波长面独立算术；
  ④三选一互斥（部分给/全缺显式拒绝）。
- FMCW IF 链规划（fmcw_if_signal_chain）：①Nyquist 量程 c·fs/(4S) 独立
  算术+矩形窗观测分辨率==距离 bin 宽逐位恒等（ΔR_obs=c/(2·S·T_obs)、
  bin=c·fs/(2SN)，T_obs=N/fs）+bins=⌊N/2⌋；②相参积累增益 10lg(N) 独立
  算术+LPF 量程面 c·f_lpf/(2S) 独立算术；③设计量程拍频独立算术+LPF 通
  带需求==拍频逐位；④折叠守卫族（设计量程超 Nyquist/LPF 超 Nyquist/
  观测窗超 chirp/非整数 N 显式拒绝）。
- 微带开路端（microstrip_open_end_parasitics）：①Kirschning Δl 系数转
  录锚=测试内独立算术逐位（msopen.cpp Q1..Q5 原文常数内联+独立 skrf
  media）+等效电容恒等式 C·Z0·c0/√εeff==Δl 逐位（msopen C 段同式）；
  ②HB 0.412 档==仓内单源 slotline_transitions 逐位（复用不重derive）+
  双模型一致带 ≤5%（数值锤 W/h∈[0.3,5] 实测 max 4.89%，名义点 2.29%）；
  ③Δl 宽度单调+正值。
- 微带串联间隙（microstrip_gap_parasitics）：①等宽对称 C1==C2/q3==q4
  逐位+Cs 系数转录锚=测试内独立算术（msgap.cpp Q1..Q5/Cs 原文常数内联）
  ；②非对称 flip 恒等（W1↔W2 交换→Cs 逐位+并联电容精确换位）；
  ③π 网络无源 |S11|²+|S21|²=1（1e-12）+|S11| 独立复算（输出电容回代
  独立 y→s 公式）+宽间隙 Cs 指数衰减（3mm/0.3mm <1e-3）；④宽比 >3
  validity 守卫+εr<1 域守卫显式拒绝。
"""

from __future__ import annotations

import itertools
import math

import pytest

from rfauto.core.calc_families.fmcw_radar import (
    fmcw_bandwidth_range_resolution,
    fmcw_chirp_design,
    fmcw_if_signal_chain,
)
from rfauto.core.calc_families.microstrip_disc import (
    microstrip_gap_parasitics,
    microstrip_open_end_parasitics,
)
from rfauto.core.slotline_transitions import microstrip_open_end_delta_l_mm

# 测试内独立物理常数（原始 SI，不消费模块常量——#118）
_C = 299792458.0


def _hj_media(w_mm: float, h_mm: float, er: float, f_ghz: float):
    """独立 skrf HJ media 构造（不消费键内 helper——#118 路径分离）。"""
    import skrf

    return skrf.media.MLine(
        frequency=skrf.Frequency(f_ghz, f_ghz, 1, unit="GHz"),
        w=w_mm * 1e-3, h=h_mm * 1e-3, ep_r=er, tand=0.0,
        model="hammerstadjensen",
    )


def _hj_z0_eps(w_mm: float, h_mm: float, er: float, f_ghz: float):
    media = _hj_media(w_mm, h_mm, er, f_ghz)
    return (float(abs(complex(media.z0[0]))),
            float(complex(media.ep_reff[0]).real))


# ─── fmcw_chirp_design（FMCW 设计键）─────────────────────────────────────────

def test_fmcw_chirp_design_if_mode_independent_arithmetic():
    """IF 带限档：B/S/T 逐项独立算术+饱和恒等+采样率需求。"""
    d_r, r_max, bwif = 0.15, 200.0, 40e6
    res = fmcw_chirp_design(range_resolution_m=d_r, max_range_m=r_max,
                            if_bandwidth_hz=bwif)
    assert res["bandwidth_hz"] == pytest.approx(_C / (2.0 * d_r), rel=1e-15)
    slope_expect = _C * bwif / (2.0 * r_max)
    assert res["slope_hz_per_s"] == pytest.approx(slope_expect, rel=1e-15)
    assert res["chirp_duration_s"] == pytest.approx(
        (_C / (2.0 * d_r)) / slope_expect, rel=1e-12)
    # 饱和恒等：量程处拍频恰满 IF 带（W7-S3 键 2 同式口径）
    assert res["beat_at_rmax_hz"] == pytest.approx(bwif, rel=1e-15)
    # 实采样最低率=2·f_b(R_max)
    assert res["adc_sample_rate_min_hz"] == pytest.approx(
        2.0 * bwif, rel=1e-15)
    assert res["slope_mode"] == "if_bandwidth_limited"


def test_fmcw_chirp_design_cross_mode_consistency_and_roundtrip():
    """BW_IF=fs/2 时两定档斜率逐位一致+显式档回灌既有键回收 R_max。"""
    d_r, r_max, fs = 0.15, 200.0, 80e6
    r_if = fmcw_chirp_design(range_resolution_m=d_r, max_range_m=r_max,
                             if_bandwidth_hz=fs / 2.0)
    r_fs = fmcw_chirp_design(range_resolution_m=d_r, max_range_m=r_max,
                             adc_sample_rate_hz=fs)
    # 跨档一致性：S=c·BW/(2R) 与 S=c·fs/(4R) 在 BW=fs/2 逐位同值
    assert r_if["slope_hz_per_s"] == r_fs["slope_hz_per_s"]
    assert r_fs["slope_mode"] == "adc_nyquist_limited"
    assert r_fs["beat_at_rmax_hz"] == pytest.approx(fs / 2.0, rel=1e-15)
    # 显式档 roundtrip：设计斜率回灌既有带宽-分辨率键回收 R_max（同族消费）
    r_ex = fmcw_chirp_design(range_resolution_m=d_r, max_range_m=r_max,
                             slope_hz_per_s=r_fs["slope_hz_per_s"])
    back = fmcw_bandwidth_range_resolution(
        bandwidth_hz=r_ex["bandwidth_hz"],
        if_bandwidth_hz=r_ex["beat_at_rmax_hz"],
        slope_hz_per_s=r_ex["slope_hz_per_s"])
    assert back["max_range_m"] == pytest.approx(r_max, rel=1e-12)


def test_fmcw_chirp_design_carrier_face():
    """载频波长面独立算术（77GHz 车载口径）。"""
    res = fmcw_chirp_design(range_resolution_m=0.15, max_range_m=200.0,
                            if_bandwidth_hz=40e6, carrier_hz=77e9)
    assert res["wavelength_m"] == pytest.approx(_C / 77e9, rel=1e-15)
    assert res["carrier_hz"] == 77e9


def test_fmcw_chirp_design_slope_mode_guards():
    """三选一互斥：部分给/多给/全缺显式拒绝（口径歧义不静默）。"""
    base = dict(range_resolution_m=0.15, max_range_m=200.0)
    with pytest.raises(ValueError, match="全缺"):
        fmcw_chirp_design(**base)
    with pytest.raises(ValueError, match="互斥"):
        fmcw_chirp_design(**base, if_bandwidth_hz=40e6,
                          slope_hz_per_s=1e13)
    with pytest.raises(ValueError, match="互斥"):
        fmcw_chirp_design(**base, if_bandwidth_hz=40e6,
                          adc_sample_rate_hz=80e6, slope_hz_per_s=1e13)


# ─── fmcw_if_signal_chain（FMCW IF 链规划键）─────────────────────────────────

def test_fmcw_if_signal_chain_nyquist_and_bin_identity():
    """Nyquist 量程独立算术+观测分辨率==bin 宽逐位恒等+bins 面。"""
    slope, fs, n = 2.5e13, 80e6, 512
    res = fmcw_if_signal_chain(slope_hz_per_s=slope,
                               adc_sample_rate_hz=fs, n_samples=n)
    assert res["nyquist_hz"] == fs / 2.0
    assert res["max_range_adc_m"] == pytest.approx(
        _C * fs / (4.0 * slope), rel=1e-15)
    t_obs = n / fs
    assert res["observation_window_s"] == t_obs
    assert res["effective_bandwidth_hz"] == pytest.approx(
        slope * t_obs, rel=1e-15)
    # 矩形窗恒等：ΔR_obs==距离 bin 宽（逐位）
    assert res["achieved_resolution_m"] == res["range_bin_width_m"]
    assert res["range_bin_width_m"] == pytest.approx(
        _C * fs / (2.0 * slope * n), rel=1e-15)
    assert res["range_bins"] == n // 2


def test_fmcw_if_signal_chain_gain_and_lpf_face():
    """相参积累增益独立算术+LPF 量程面独立算术。"""
    slope, fs, n, f_lpf = 2.5e13, 80e6, 512, 35e6
    res = fmcw_if_signal_chain(slope_hz_per_s=slope,
                               adc_sample_rate_hz=fs, n_samples=n,
                               lpf_cutoff_hz=f_lpf)
    assert res["processing_gain_db"] == pytest.approx(
        10.0 * math.log10(n), rel=1e-15)
    assert res["max_range_lpf_m"] == pytest.approx(
        _C * f_lpf / (2.0 * slope), rel=1e-15)


def test_fmcw_if_signal_chain_design_range_face():
    """设计量程拍频独立算术+LPF 通带需求==拍频逐位。"""
    slope, r_des = 2.5e13, 200.0
    res = fmcw_if_signal_chain(slope_hz_per_s=slope,
                               adc_sample_rate_hz=80e6, n_samples=512,
                               design_range_m=r_des)
    beat_expect = 2.0 * slope * r_des / _C
    assert res["beat_at_design_hz"] == pytest.approx(beat_expect, rel=1e-15)
    assert res["lpf_passband_min_hz"] == res["beat_at_design_hz"]


def test_fmcw_if_signal_chain_fold_guards():
    """折叠守卫族：超 Nyquist/LPF 超 Nyquist/观测窗超 chirp/非整数 N。"""
    base = dict(slope_hz_per_s=2.5e13, adc_sample_rate_hz=80e6, n_samples=512)
    with pytest.raises(ValueError, match="Nyquist"):
        fmcw_if_signal_chain(**base, design_range_m=400.0)
    with pytest.raises(ValueError, match="Nyquist"):
        fmcw_if_signal_chain(**base, lpf_cutoff_hz=45e6)
    with pytest.raises(ValueError, match="chirp"):
        fmcw_if_signal_chain(**base, bandwidth_hz=1e6)
    with pytest.raises(ValueError, match="整数"):
        fmcw_if_signal_chain(slope_hz_per_s=2.5e13,
                             adc_sample_rate_hz=80e6, n_samples=512.5)
    with pytest.raises(ValueError, match="≥2"):
        fmcw_if_signal_chain(slope_hz_per_s=2.5e13,
                             adc_sample_rate_hz=80e6, n_samples=1)


# ─── microstrip_open_end_parasitics（微带开路端键）───────────────────────────

def test_open_end_kirschning_transcription_and_cap_identity():
    """Kirschning Δl 系数转录锚（测试内独立算术逐位）+等效电容恒等式逐位。"""
    w_mm, h_mm, er, f_ghz = 1.27, 0.635, 9.9, 10.0
    res = microstrip_open_end_parasitics(width_mm=w_mm, h_mm=h_mm,
                                         epsilon_r=er, freq_ghz=f_ghz)
    z0, ee = _hj_z0_eps(w_mm, h_mm, er, f_ghz)
    assert res["z0_ohm"] == pytest.approx(z0, rel=1e-12)
    assert res["eps_eff"] == pytest.approx(ee, rel=1e-12)
    # msopen.cpp "Kirschning" 段原文常数内联独立复算
    u = w_mm / h_mm
    q6 = ee ** 0.81
    q7 = u ** 0.8544
    q1 = 0.434907 * (q6 + 0.26) / (q6 - 0.189) * (q7 + 0.236) / (q7 + 0.87)
    q2 = u ** 0.371 / (2.358 * er + 1.0) + 1.0
    q3 = (math.atan(0.084 * u ** (1.9413 / q2)) * 0.5274
          / ee ** 0.9236 + 1.0)
    q4 = (0.0377 * (6.0 - 5.0 * math.exp(0.036 * (1.0 - er)))
          * math.atan(0.067 * u ** 1.456) + 1.0)
    q5 = 1.0 - 0.218 * math.exp(-7.5 * u)
    dl_k_mm = q1 * q3 * q5 / q4 * h_mm
    assert res["dl_kirschning_mm"] == pytest.approx(dl_k_mm, rel=1e-12)
    # 等效电容恒等式：C=Δl·√εeff/(Z0·c0)（msopen C 段同式）逐位回代
    assert (res["c_end_f"] * z0 * _C / math.sqrt(ee)
            == res["dl_kirschning_mm"] * 1e-3)
    # HB 档电容同恒等式
    assert (res["c_end_hammerstad_f"] * z0 * _C / math.sqrt(ee)
            == res["dl_hammerstad_mm"] * 1e-3)


def test_open_end_hb_single_source_and_dual_band():
    """HB 档==仓内单源逐位（复用不重 derive）+双模型一致带 ≤5%（如实）。"""
    w_mm, h_mm, er, f_ghz = 1.27, 0.635, 9.9, 10.0
    res = microstrip_open_end_parasitics(width_mm=w_mm, h_mm=h_mm,
                                         epsilon_r=er, freq_ghz=f_ghz)
    _, ee = _hj_z0_eps(w_mm, h_mm, er, f_ghz)
    assert res["dl_hammerstad_mm"] == microstrip_open_end_delta_l_mm(
        w_mm, h_mm, ee)
    # 双模型一致带（数值锤 W/h∈[0.3,5] max 4.89%——非逐位如实记带）
    assert abs(res["dual_model_rel_diff"]) < 0.05
    # 第二点位（W/h=1 窄线档）带内
    res2 = microstrip_open_end_parasitics(width_mm=0.635, h_mm=0.635,
                                          epsilon_r=9.9, freq_ghz=10.0)
    assert abs(res2["dual_model_rel_diff"]) < 0.05
    assert res2["dl_kirschning_mm"] > 0.0


def test_open_end_width_monotonic_positive():
    """Δl 随线宽单调增（边缘场扩展物理序）+双档正值。"""
    widths = [0.635, 1.27, 2.54]
    dls = [microstrip_open_end_parasitics(width_mm=w, h_mm=0.635,
                                          epsilon_r=9.9, freq_ghz=10.0)
           for w in widths]
    for lo, hi in itertools.pairwise(dls):
        assert hi["dl_hammerstad_mm"] > lo["dl_hammerstad_mm"]
        assert hi["dl_kirschning_mm"] > lo["dl_kirschning_mm"]
    for r in dls:
        assert r["dl_hammerstad_mm"] > 0.0 and r["dl_kirschning_mm"] > 0.0
        assert r["c_end_f"] > 0.0


# ─── microstrip_gap_parasitics（微带串联间隙键）──────────────────────────────

def test_gap_equal_width_symmetry_and_series_transcription():
    """等宽对称 C1==C2/q3==q4 逐位+Cs 系数转录锚（msgap.cpp 原文内联）。"""
    w_mm, s_mm, h_mm, er, f_ghz = 1.27, 0.3, 0.635, 9.9, 10.0
    res = microstrip_gap_parasitics(w1_mm=w_mm, w2_mm=w_mm, gap_mm=s_mm,
                                    h_mm=h_mm, epsilon_r=er,
                                    freq_ghz=f_ghz)
    assert res["equal_width"] is True
    assert res["c_shunt_port1_f"] == res["c_shunt_port2_f"]
    assert res["q3"] == res["q4"]
    assert res["width_ratio"] == 1.0
    # msgap.cpp 原文常数内联独立复算（等宽特化：W2'=1）
    z0, ee = _hj_z0_eps(w_mm, h_mm, er, f_ghz)
    u1 = w_mm / h_mm
    s_n = s_mm / h_mm
    q5 = 1.23
    q1 = 0.04598 * (0.03 + u1 ** q5) * (0.272 + 0.07 * er)
    q2 = (0.107 * (u1 + 9.0) * s_n ** 3.23
          + 2.09 * s_n ** 1.05 * (1.5 + 0.3 * u1) / (1.0 + 0.6 * u1))
    q3 = math.exp(-0.5978) - 0.55
    # 开路端基础电容：Kirschning Δl→C 恒等（独立 Q 链）
    q6, q7 = ee ** 0.81, u1 ** 0.8544
    k1 = 0.434907 * (q6 + 0.26) / (q6 - 0.189) * (q7 + 0.236) / (q7 + 0.87)
    k2 = u1 ** 0.371 / (2.358 * er + 1.0) + 1.0
    k3 = (math.atan(0.084 * u1 ** (1.9413 / k2)) * 0.5274
          / ee ** 0.9236 + 1.0)
    k4 = (0.0377 * (6.0 - 5.0 * math.exp(0.036 * (1.0 - er)))
          * math.atan(0.067 * u1 ** 1.456) + 1.0)
    k5 = 1.0 - 0.218 * math.exp(-7.5 * u1)
    dl_mm = k1 * k3 * k5 / k4 * h_mm
    c_base = dl_mm * 1e-3 * math.sqrt(ee) / z0 / _C
    cs_expect = (5e-10 * h_mm * 1e-3 * math.exp(-1.86 * s_n) * q1
                 * (1.0 + 4.19 * (1.0 - math.exp(-0.785 * math.sqrt(1.0 / u1))))
                 )
    assert res["c_series_gap_f"] == pytest.approx(cs_expect, rel=1e-12)
    assert res["q1"] == pytest.approx(q1, rel=1e-15)
    assert res["q2"] == pytest.approx(q2, rel=1e-15)
    assert res["q3"] == pytest.approx(q3, rel=1e-15)
    assert res["c_shunt_port1_f"] == pytest.approx(
        c_base * (q2 + q3) / (q2 + 1.0), rel=1e-12)


def test_gap_flip_symmetry_asymmetric_widths():
    """非对称 flip 恒等：W1↔W2 交换→Cs 逐位+并联电容精确换位。"""
    kw = dict(gap_mm=0.3, h_mm=0.635, epsilon_r=9.9, freq_ghz=10.0)
    g1 = microstrip_gap_parasitics(w1_mm=2.0, w2_mm=1.0, **kw)
    g2 = microstrip_gap_parasitics(w1_mm=1.0, w2_mm=2.0, **kw)
    assert g1["c_series_gap_f"] == g2["c_series_gap_f"]
    assert g1["c_shunt_port1_f"] == g2["c_shunt_port2_f"]
    assert g1["c_shunt_port2_f"] == g2["c_shunt_port1_f"]
    # S 面 flip 不变：数学恒等但 (1+a)(1-b) 浮点序不对称——rel 1e-12 带
    # （电容面逐位已钉，S 面只钉物理不变量）
    assert g1["s11_db"] == pytest.approx(g2["s11_db"], rel=1e-12)
    assert g1["s21_db"] == pytest.approx(g2["s21_db"], rel=1e-12)
    # 非对称两侧并联电容不等（Q3≠Q4 修正）
    assert g1["c_shunt_port1_f"] != g1["c_shunt_port2_f"]
    assert g1["q3"] != g1["q4"]
    # 开路端基础电容随端口序换位（宽边基础电容大于窄边）
    assert (g1["c_open_end_base_port1_f"] == g2["c_open_end_base_port2_f"])
    assert g1["c_open_end_base_port1_f"] > g1["c_open_end_base_port2_f"]


def test_gap_network_passivity_and_wide_gap_decay():
    """π 网络无源 |S11|²+|S21|²=1+|S11| 独立回代复算+宽间隙 Cs 指数衰减。"""
    kw = dict(w1_mm=1.27, w2_mm=1.27, gap_mm=0.3, h_mm=0.635,
              epsilon_r=9.9, freq_ghz=10.0)
    res = microstrip_gap_parasitics(**kw)
    s11, s21 = 10.0 ** (res["s11_db"] / 20.0), 10.0 ** (res["s21_db"] / 20.0)
    assert s11 ** 2 + s21 ** 2 == pytest.approx(1.0, abs=1e-12)
    # 输出电容回代独立 y→s 公式复算 |S11|（损耗无损 2 端口闭式）
    omega = 2.0 * math.pi * 10e9
    y11 = 1j * omega * (res["c_shunt_port1_f"] + res["c_series_gap_f"])
    y22 = 1j * omega * (res["c_shunt_port2_f"] + res["c_series_gap_f"])
    y12 = -1j * omega * res["c_series_gap_f"]
    yn11, yn22, yn12 = y11 * 50.0, y22 * 50.0, y12 * 50.0
    den = (1.0 + yn11) * (1.0 + yn22) - yn12 * yn12
    s11_c = ((1.0 + yn22) * (1.0 - yn11) + yn12 * yn12) / den
    assert 20.0 * math.log10(abs(s11_c)) == pytest.approx(
        res["s11_db"], rel=1e-12)
    # 宽间隙：Cs 指数归零（3mm vs 0.3mm <1e-3）
    far = microstrip_gap_parasitics(w1_mm=1.27, w2_mm=1.27, gap_mm=3.0,
                                    h_mm=0.635, epsilon_r=9.9, freq_ghz=10.0)
    assert far["c_series_gap_f"] < res["c_series_gap_f"] * 1e-3
    # 宽间隙下并联电容趋近未修正开路端电容（Q 修正比→1 面：Q2→大）
    assert far["c_shunt_port1_f"] > res["c_shunt_port1_f"]


def test_gap_domain_guards():
    """宽比 >3 validity 守卫（msgap.cpp 注释原文口径）+εr<1 域守卫。"""
    base = dict(gap_mm=0.3, h_mm=0.635, epsilon_r=9.9, freq_ghz=10.0)
    with pytest.raises(ValueError, match="W2/W1"):
        microstrip_gap_parasitics(w1_mm=4.0, w2_mm=1.0, **base)
    with pytest.raises(ValueError, match="εr"):
        microstrip_gap_parasitics(w1_mm=1.0, w2_mm=1.0, epsilon_r=0.9,
                                  gap_mm=0.3, h_mm=0.635, freq_ghz=10.0)
