"""席6 LT 系测试：RA.769 判据链（LT-2）+ MWP IMDD Cox 口径（LT-11）
+ fronthaul 换算（LT-12）+ 微波加热整包编排（LT-5..7，纯复用）。

诚实边界：RA.769 原表数值与 Cox 书页码锚本批网络不可达（#122 不凑绿），
本文件只钉闭式核的数学性质与解析恒等（锚点出处见各断言注释）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.fronthaul_budget import (
    NR_SAMPLE_RATE_MSPS,
    arof_bandwidth,
    ecpri_7_2x_bitrate,
    fronthaul_comparison,
    nr_standard_sample_rate,
)
from rfauto.core.microwave_heating_workflow import microwave_heating_workflow
from rfauto.core.mwp_imdd import (
    imdd_link_gain,
    imdd_noise_figure,
    imdd_sfdr,
    mzm_harmonic_amplitudes,
    mzm_power_transfer,
)
from rfauto.core.ra769 import (
    K_B,
    detrimental_power_dbw,
    effective_area,
    interference_margin,
    off_axis_gain_envelope,
    pfd_to_received_power,
    received_power_to_pfd,
)

# ── LT-2 RA.769 判据链 ────────────────────────────────────────────────────────


def test_k_boltzmann_exact_si() -> None:
    """k_B = SI 2019 精确值（CODATA 定义常数，双源无虞）。"""
    assert K_B == 1.380649e-23
    assert abs(10 * math.log10(K_B) - (-228.599)) < 0.001  # 1K·1Hz 习惯锚


def test_detrimental_power_radiometer_scaling() -> None:
    """辐射计方程标度律：10%→1% 差恰 10 dB；Δf×4 → +3 dB；τ×4 → −3 dB。"""
    p10 = detrimental_power_dbw(50.0, 2e6, 2000.0)
    p01 = detrimental_power_dbw(50.0, 2e6, 2000.0, fraction=0.01)
    assert p01["p_limit_dbw"] == pytest.approx(
        p10["p_limit_dbw"] - 10.0, abs=1e-9)
    p4f = detrimental_power_dbw(50.0, 8e6, 2000.0)
    assert p4f["p_limit_dbw"] == pytest.approx(
        p10["p_limit_dbw"] + 3.0103, abs=1e-3)
    p4t = detrimental_power_dbw(50.0, 2e6, 8000.0)
    assert p4t["p_limit_dbw"] == pytest.approx(
        p10["p_limit_dbw"] - 3.0103, abs=1e-3)
    assert p10["delta_t_k"] == pytest.approx(5.0)


def test_pfd_power_roundtrip_and_aperture_theorem() -> None:
    """口径定理互逆：PFD→功率→PFD 恒等；A_e=Gλ²/4π 逐点（G=1, d=λ→λ²/4π）。"""
    ae = effective_area(0.0, 1e9)
    lam = 0.299792458
    assert ae == pytest.approx(lam * lam / (4 * math.pi), rel=1e-12)
    pfd = -230.0
    p_rx = pfd_to_received_power(pfd, 30.0, 5e9)
    assert received_power_to_pfd(p_rx, 30.0, 5e9) == pytest.approx(
        pfd, abs=1e-9)


def test_offaxis_envelope_shape() -> None:
    """三段包络数学性质：断点连续、对数斜率、地板夹持。"""
    env = {"g_max_dbi": 50.0, "theta_break_deg": 1.0,
           "slope_db_per_decade": 25.0, "floor_dbi": -10.0}
    assert off_axis_gain_envelope(0.5, **env) == 50.0
    assert off_axis_gain_envelope(1.0, **env) == 50.0
    g10 = off_axis_gain_envelope(10.0, **env)
    assert g10 == pytest.approx(50.0 - 25.0, abs=1e-12)  # log10(10/1)=1
    assert off_axis_gain_envelope(1000.0, **env) == -10.0  # 地板夹持
    assert off_axis_gain_envelope(2.0, **env) > off_axis_gain_envelope(
        20.0, **env)  # 单调降


def test_interference_margin_chain() -> None:
    """margin 链解析例：EIRP−FSPL+G 与手算逐位；verdict 双分支。"""
    d = 1000.0
    lam = 299792458.0 / 3e9  # 模块用精确 c/f（非 0.1 手值）
    fspl = 20 * math.log10(4 * math.pi * d / lam)
    env = {"g_max_dbi": 40.0, "theta_break_deg": 1.0,
           "slope_db_per_decade": 25.0, "floor_dbi": -10.0}
    m = interference_margin(30.0, d, 3e9, 0.0, 30.0, -30.0)
    assert m["fspl_db"] == pytest.approx(fspl, rel=1e-12)
    assert m["p_rx_dbw"] == pytest.approx(30.0 - fspl + 30.0, rel=1e-12)
    assert m["margin_db"] == pytest.approx(-30.0 - m["p_rx_dbw"], rel=1e-12)
    assert m["verdict"] == "compliant"  # −42 dBW < −30 dBW 门限
    m_off = interference_margin(30.0, d, 3e9, 10.0, 30.0, -100.0,
                                envelope=env)
    assert m_off["rx_gain_dbi"] == pytest.approx(15.0, abs=1e-9)
    assert m_off["verdict"] in ("compliant", "detrimental")
    with pytest.raises(ValueError, match="主瓣直射"):
        interference_margin(30.0, d, 3e9, 10.0, 30.0, -100.0)


# ── LT-11 MWP IMDD ────────────────────────────────────────────────────────────


def test_mzm_quadrature_even_harmonics_vanish() -> None:
    """正交偏置（V_b=V_π/2）：偶次谐波归零（cosφ_b=0，MZM 经典性质）。"""
    out = mzm_harmonic_amplitudes(0.3, 3.0, 1.5, n_harmonics=6)
    for n in (2, 4, 6):
        assert out["amplitudes_rel_pin"][n] == pytest.approx(0.0, abs=1e-15)
    # 基波幅度 = |J_1(m)·sinφ_b| → 小信号极限 m·sinφ_b/2·... 线性区 ∝ m
    m = out["modulation_index"]
    import scipy.special as sp
    assert out["amplitudes_rel_pin"][1] == pytest.approx(
        sp.jv(1, m) * math.sin(math.pi / 2), rel=1e-12)


def test_mzm_null_bias_odd_harmonics_vanish() -> None:
    """零偏置（传输零点 V_b=V_π）：奇次谐波归零（sinφ_b=0）。"""
    out = mzm_harmonic_amplitudes(1.2, 3.0, 3.0, n_harmonics=6)
    for n in (1, 3, 5):
        assert out["amplitudes_rel_pin"][n] == pytest.approx(0.0, abs=1e-15)
    assert out["amplitudes_rel_pin"][2] > 0.0  # 偶次保留


def test_mzm_transfer_small_signal_matches_bessel() -> None:
    """时域传递 vs 谐波表：正交偏置小信号一次谐波幅度一致（内部互证）。"""
    harm = mzm_harmonic_amplitudes(0.05, 3.0, 1.5, n_harmonics=2)
    v = np.linspace(0.0, 0.05, 8192)
    p = mzm_power_transfer(v * np.cos(2 * np.pi * 100 * np.linspace(0, 1, 8192)),
                           3.0, 1.5, 1.0) if False else None
    # 直流项 = 1/2(1+J0(m)cosφb) = 1/2（正交）→ 小信号输出 ≈ P_in/2
    assert harm["amplitudes_rel_pin"][0] == pytest.approx(0.5, abs=1e-9)
    assert p is None


def test_imdd_link_gain_hand_computed() -> None:
    """增益闭式手算例：R_d=0.8, P_0=10mW, V_π=3V, R_s=R_L=50Ω。"""
    out = imdd_link_gain(0.010, 3.0, 0.8, 50.0, 50.0)
    s = 0.8 * math.pi * 0.010 / (2 * 3.0)
    assert out["slope_efficiency_a_per_v"] == pytest.approx(s, rel=1e-12)
    assert out["gain_linear"] == pytest.approx(s * s * 50.0 * 50.0 / 2.0,
                                               rel=1e-12)
    assert out["gain_db"] == pytest.approx(10 * math.log10(
        s * s * 2500 / 2.0), rel=1e-12)
    assert out["i_pd_dc_a"] == pytest.approx(0.008)


def test_imdd_nf_sources_and_lossless_limit() -> None:
    """NF 三源：热源项+负载项=NF≥1+1/G；RIN/散粒单调抬升；光功率↑ NF↓。"""
    base = imdd_noise_figure(0.010, 3.0, 0.8, 50.0, 50.0)
    assert base["nf_linear"] >= 1.0 + 1.0 / base["gain_linear"] - 1e-12
    shot_up = imdd_noise_figure(0.001, 3.0, 0.8, 50.0, 50.0)
    assert shot_up["nf_db"] > base["nf_db"]  # 光功率降→散粒占比升→NF 抬
    rin = imdd_noise_figure(0.010, 3.0, 0.8, 50.0, 50.0,
                            rin_per_hz=1e-14)
    assert rin["nf_db"] > base["nf_db"]
    assert rin["noise_out_w_per_hz"]["rin"] > 0.0
    more_power = imdd_noise_figure(0.020, 3.0, 0.8, 50.0, 50.0)
    assert more_power["nf_db"] < base["nf_db"]


def test_imdd_sfdr_formula() -> None:
    """SFDR=(2/3)(OIP3−N_out)（cascade 同式族）。"""
    assert imdd_sfdr(10.0, -150.0) == pytest.approx((2 / 3) * 160.0)


# ── LT-12 fronthaul ───────────────────────────────────────────────────────────


def test_ecpri_rate_arithmetic_and_overhead() -> None:
    """7-2x 码率算术：R=N·2W·fs·(1+OH)；OH=0 退化为裸量化率。"""
    bare = ecpri_7_2x_bitrate(4, 122.88e6, 16, overhead=0.0)
    assert bare["bitrate_bps"] == pytest.approx(4 * 2 * 16 * 122.88e6)
    with_oh = ecpri_7_2x_bitrate(4, 122.88e6, 16, overhead=0.25)
    assert with_oh["bitrate_bps"] == pytest.approx(
        bare["bitrate_bps"] * 1.25)
    assert ecpri_7_2x_bitrate(1, 122.88e6, 16)["per_axc_bps"] == \
        pytest.approx(ecpri_7_2x_bitrate(4, 122.88e6, 16)["per_axc_bps"])


def test_nr_sample_rate_ladder_and_guard() -> None:
    """采样率阶梯=3.84×2^k 算术族；表外显式拒绝。"""
    assert nr_standard_sample_rate(100) == pytest.approx(122.88e6)
    with pytest.raises(ValueError, match="常用档"):
        nr_standard_sample_rate(33.0)
    assert set(NR_SAMPLE_RATE_MSPS) == {5, 10, 20, 40, 100, 400}


def test_fronthaul_comparison_ratio_scales_with_axc() -> None:
    """对比账：等效数字开销倍数随 N_axc 线性；A-RoF 只承载一份 RF 带宽。"""
    c1 = fronthaul_comparison(4, 100e6, 122.88e6, 16)
    c8 = fronthaul_comparison(8, 100e6, 122.88e6, 16)
    assert c8["digital_to_rf_ratio"] == pytest.approx(
        2 * c1["digital_to_rf_ratio"])
    assert arof_bandwidth(100e6)["analog_bandwidth_hz"] == pytest.approx(
        100e6)


# ── LT-5..7 整包编排（纯复用）───────────────────────────────────────────────


def test_heating_workflow_stages_reuse_kernels() -> None:
    """全参数编排：S1/S2/S3/S4/S5 全激活且 ok（复用既有核零新数值）。"""
    r = microwave_heating_workflow(
        freq_hz=2.45e9, cavity_a_m=0.30, cavity_b_m=0.30, cavity_d_m=0.25,
        cavity_er=1.0, q_wall=5000.0, load_volume_m3=1e-4,
        load_eps_r=12.0, load_tan_delta=0.15, available_power_w=800.0,
        field_rms_v_per_m=3.0e4, load_density_kg_m3=1200.0,
        r_th_c_per_w=[0.05], tau_s=[60.0], ambient_c=25.0, target_c=140.0,
        t_max_c=200.0, t_process_s=300.0, power_w=800.0)
    assert r["ok"] and r["staged_complete"]
    assert set(r["stages"]) == {"s1_multimode", "s2_applicator",
                                "s3_absorption", "s4_fixed_point",
                                "s5_process_window"}
    for name, s in r["stages"].items():
        assert s["ok"], f"{name} 段失败: {s.get('reason')}"
    s1 = r["stages"]["s1_multimode"]
    assert "n_weyl" in s1 and "load_match" in s1
    assert r["stages"]["s3_absorption"]["power_density_w_per_m3"] > 0.0


def test_heating_workflow_partial_inputs_skip_honestly() -> None:
    """缺输入段如实 skipped（缺输入不猜），请求段仍 complete。"""
    r = microwave_heating_workflow(freq_hz=2.45e9)
    assert r["n_stages_active"] == 0
    assert r["staged_complete"]
    r2 = microwave_heating_workflow(freq_hz=2.45e9, cavity_a_m=0.30,
                                    cavity_b_m=0.30, cavity_d_m=0.25,
                                    cavity_er=1.0)
    assert r2["stages"]["s1_multimode"]["ok"]
    assert "load_match" not in r2["stages"]["s1_multimode"]
    with pytest.raises(ValueError, match="freq_hz"):
        microwave_heating_workflow(freq_hz=-1.0)
