"""aurora_g W6-S3 席锚树：内核新域首批六键（微带不连续寄生三键+雷达杂波
MTI 三键）。

数值断言口径（#118 锚先独立实测再写死，锚值=开工日独立算术预算；
#122 三态/UNVERIFIED 如实不凑绿）：

- 微带弯角（microstrip_bend_parasitics）：①W/h=2 氧化铝 0.5mm/0.25mm
  @10GHz 未切角 |S11|=−15.10dB 正中 fake_adapter._bend_sparams 弯角寄生
  门 −15dB 文献口径（消费面同仓双源对拍带 [−17,−13]）+50% 切角档改善
  （S11 抬升 ≥3dB）；②L/C 转录锚=测试内独立算术逐位（KJK 式(20)-(23)
  多步复算，非键内同式二次抄写——独立表达式路径）；③未切角 L 负值域
  （W/h≲1.4，TU/e thesis "validity limited to w/h≳1"）显式拒绝；
  ④validity 守卫（εr/W/h/f·h 三窗）。
- T 接（microstrip_t_junction_parasitics）：①对称 T La==Lb、Ta==Tb、
  da==db 逐位+支臂位移 r=1 结构恒等（d2/√(DaDb)=0.5−0.05−0.7e^{−1.6}
  −0.25q 逐位）；②准静态极限 f→0：Bt→0、Ta→1（|·|<1e-6）；③极端阻抗
  比参考面交叉（L2≤0）显式拒绝；④Z0 与 microstrip_analysis 同源逐位
  （skrf HJ 单源跨键一致性）。
- 阶跃（microstrip_step_parasitics）：①W1=W2 → Ls≡0 逐位（r−1=0 与
  lg1=0 双项归零，同文件 _step_ls_nh 双路径）；②拟合零交叉下侧与展宽
  方向显式拒绝（εr=9.9 零交叉 W1/W2≈1.27）；③Cs/Ls 独立算术逐位+
  L' 权重面（窄线权重大、和为 1）。
- MTI 频响（mti_frequency_response）：①凹口 |H|(k·PRF)=0 与峰值
  |H|((k+1/2)·PRF)=2 逐位+周期恒等 H(f+PRF)=H(f) 逐位+半凹口 √2 逐位；
  ②盲速 v_n=n·λ·PRF/2 独立算术+v1 多普勒恒等式闭环（f=v·2/λ 反解=
  凹口频率）；③标量/列表输入同值。
- 改善因子（mti_improvement_factor）：①闭式 I=1/(1−ρ) 与复化梯形数值
  积分双路径互证（rel<1e-9，#118）；②窄谱渐近 I≈1/(2π²σ_f²Tr²)
  （1−ρ≈expo 一阶，rel<1e-3）；③σ_v 单调递减+大谱宽 →1 上界；④SCV
  恒等式 scv=i_db−required 逐位；⑤文献典型值带（land σv=0.3 → ~21.6dB、
  sea σv=1.0 → ~11.3dB，Greco 讲义谱宽口径）；窄谱数值域守卫。
- σ0（clutter_sigma0_model）：①γ 档正弦恒等（σ0=γ·sinψ 独立算术逐位）
  +dB 闭环 roundtrip；②常数档 10^(db/10) 逐位+σc=σ0·Ac 恒等+Ac=
  R·ρ·θaz·secψ 独立算术；③GIT/部分几何/ψ 越域显式拒绝（#122 GIT 缺席
  如实）。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.calc_families.microstrip_disc import (
    _step_ls_nh,
    microstrip_bend_parasitics,
    microstrip_step_parasitics,
    microstrip_t_junction_parasitics,
)
from rfauto.core.calc_families.radar_clutter import (
    clutter_sigma0_model,
    mti_frequency_response,
    mti_improvement_factor,
)

# ─── 微带直角弯寄生（microstrip_bend_parasitics）─────────────────────────────

def test_bend_s11_fake_gate_band_and_transcription():
    """未切角 |S11| 落 fake_adapter 弯角寄生门 −15dB 带 + L/C 独立算术。"""
    w_mm, h_mm, er, f_ghz = 0.5, 0.25, 9.9, 10.0
    res = microstrip_bend_parasitics(w_mm, h_mm, er, f_ghz)
    # 消费面同仓双源：fake_adapter 未切角直角弯 |S11| 绝对门 −15dB 文献口径
    assert -17.0 <= res["s11_unmitered_db"] <= -13.0
    # 50% 切角改善反射（dB 抬升 ≥3dB——切角档 dB 值更小=反射更弱）
    assert res["s11_unmitered_db"] - res["s11_mitered50_db"] >= 3.0
    # 转录锚：KJK 式(20)-(23) 测试内独立算术（独立表达式路径非键内同式）
    u = w_mm / h_mm
    c_plain = 1e-3 * w_mm * (10.35 * er * u + 2.5 * u + 2.6 * er + 5.64)
    l_plain = 220.0 * h_mm * 1e-3 * (
        1.0 - 1.35 * math.exp(-0.18 * u ** 1.39))
    c_mit = 1e-3 * w_mm * (3.93 * er * u + 0.62 * u + 7.6 * er + 3.80)
    l_mit = 440.0 * h_mm * 1e-3 * (
        1.0 - 1.062 * math.exp(-0.177 * u ** 0.947))
    assert res["c_unmitered_pf"] == pytest.approx(c_plain, rel=1e-12)
    assert res["l_unmitered_nh"] == pytest.approx(l_plain, rel=1e-12)
    assert res["c_mitered50_pf"] == pytest.approx(c_mit, rel=1e-12)
    assert res["l_mitered50_nh"] == pytest.approx(l_mit, rel=1e-12)
    # 物理方向：切角去角金属 → 角部储能电容下降
    assert res["c_mitered50_pf"] < res["c_unmitered_pf"]


def test_bend_s11_independent_abcd_path():
    """S11 面独立 ABCD 级联复算（#118 同文件双路径——非键内同式抄写）。"""
    res = microstrip_bend_parasitics(0.5, 0.25, 9.9, 10.0)
    omega = 2.0 * math.pi * 10e9
    z_l = 1j * omega * res["l_unmitered_nh"] * 1e-9
    y_c = 1j * omega * res["c_unmitered_pf"] * 1e-12
    # ABCD = Series(Z_L)·Shunt(Y_C)·Series(Z_L)（矩阵乘法路径）
    a = 1.0 + z_l * y_c
    b = 2.0 * z_l + z_l * z_l * y_c
    c = y_c
    d = a
    z_ref = 50.0
    s11 = (a + b / z_ref - c * z_ref - d) / (a + b / z_ref + c * z_ref + d)
    assert res["s11_unmitered_db"] == pytest.approx(
        20.0 * math.log10(abs(s11)), rel=1e-12)


def test_bend_narrow_line_l_negative_rejected():
    """未切角 L 式负值域（W/h≲1.4 拟合域外，TU/e thesis 明示）显式拒绝。"""
    with pytest.raises(ValueError, match="L≤0"):
        microstrip_bend_parasitics(0.6, 0.635, 9.9)


def test_bend_validity_guards():
    """validity 三窗守卫：εr / W/h / f·h（KJK 拟合原文域）。"""
    with pytest.raises(ValueError, match="εr 域"):
        microstrip_bend_parasitics(0.5, 0.25, 1.0)
    with pytest.raises(ValueError, match="W/h 域"):
        microstrip_bend_parasitics(0.5, 0.04, 9.9)  # W/h=12.5
    with pytest.raises(ValueError, match="f·h≤12"):
        microstrip_bend_parasitics(0.5, 0.25, 9.9, 50.0)  # 12.5 GHz·mm


# ─── T 接头寄生（microstrip_t_junction_parasitics）───────────────────────────

def test_tee_symmetric_bit_exact_identities():
    """对称 T：La==Lb、Ta==Tb、da==db 逐位 + 支臂位移 r=1 结构恒等。"""
    res = microstrip_t_junction_parasitics(0.6, 0.6, 0.6, 0.635, 9.9, 5.0)
    assert res["l_main_a_mm"] == res["l_main_b_mm"]
    assert res["turn_ratio_a"] == res["turn_ratio_b"]
    assert res["d_ref_a_mm"] == res["d_ref_b_mm"]
    # r=1：ln(1)=0、e^{−1.6} 逐位 → d2/√(DaDb) = 0.5−0.05−0.7e^{−1.6}
    # −0.17·ln(1)（0.25·r·q 项 q>0 在内）；Da 由键面 z0/εeff 独立反解
    # （Da=η0·h/(Z·√εeff) 平行板恒等式，对称时 √(DaDb)==Da）
    f_ghz, fp = 5.0, res["fp_main_a_ghz"]
    q = (f_ghz / fp) ** 2
    expect = 0.5 - (0.05 + 0.7 * math.exp(-1.6) + 0.25 * q)
    da_w_mm = (376.73031346958504364963 * 0.635
               / (res["z0_main_a_ohm"] * math.sqrt(res["eps_eff_main_a"])))
    assert res["d_ref_side_mm"] / da_w_mm == pytest.approx(
        expect, rel=1e-12)
    # 主臂变比 f/fp≈0.16 档：Ta=1−πq((Za/Z3)²/12+(0.5−d2/Da)²)≈0.990
    # （独立复算同式；f→0→1 恒等另由 test_tee_quasistatic_limits 钉）
    ta_expect = 1.0 - math.pi * q * (1.0 / 12.0
                                     + (0.5 - expect) ** 2)
    assert res["turn_ratio_a"] == pytest.approx(ta_expect, rel=1e-12)
    assert 0.98 < res["turn_ratio_a"] <= 1.0
    # 规范几何负长度如实标记（docstring 记载 L_2≈−0.26mm 档）
    assert res["reference_planes_crossed"] is True


def test_tee_quasistatic_limits():
    """f→0 准静态极限：Bt→0（λ→∞）、Ta→1（结构恒等锚）。"""
    res = microstrip_t_junction_parasitics(
        0.6, 0.6, 0.6, 0.635, 9.9, 1e-3)
    assert abs(res["shunt_susceptance_s"]) < 1e-6
    assert abs(res["turn_ratio_a"] - 1.0) < 1e-9


def test_tee_near_cutoff_structural_break_rejected():
    """f 过近高阶模截止（da·db<0，√(da·db) 结构破裂）显式拒绝。

    非对称主臂 0.4/0.8mm：da 翻转点 q>Z3/(2Za)=0.427、db 翻转点
    q>0.565——f=23GHz 恰落异号窗（q≈0.506）。"""
    with pytest.raises(ValueError, match="da·db<0"):
        microstrip_t_junction_parasitics(0.4, 0.8, 0.6, 0.635, 9.9, 23.0)


def test_tee_z0_single_source_with_microstrip_analysis():
    """Z0/εeff 与 microstrip_analysis 同源（skrf HJ 单源跨键逐位）。"""
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    res = microstrip_t_junction_parasitics(0.6, 0.6, 0.6, 0.635, 9.9, 5.0)
    ref = CALCULATOR_REGISTRY.get("microstrip_analysis").func(
        width_mm=0.6, freq_ghz=5.0, epsilon_r=9.9, h_mm=0.635)
    assert res["z0_main_a_ohm"] == pytest.approx(ref["z0_ohm"], abs=0.01)
    assert res["eps_eff_main_a"] == pytest.approx(ref["eps_eff"], abs=1e-4)


# ─── 宽度阶跃寄生（microstrip_step_parasitics）───────────────────────────────

def test_step_ls_w1w2_degenerate_bit_exact_zero():
    """W1=W2 → Ls≡0 逐位（r−1=0 与 lg(1)=0 双项归零；同文件双路径）。"""
    assert _step_ls_nh(1.0, 1.0, 0.635) == 0.0
    assert _step_ls_nh(2.5, 2.5, 0.25) == 0.0


def test_step_invalid_directions_rejected():
    """展宽（W1<W2）、直通（W1=W2 Cs<0）与零交叉下侧（<1.27@εr=9.9）
    全部显式拒绝（Garg-Bahl 拟合形态域外不凑）。"""
    with pytest.raises(ValueError, match="只收收窄阶跃"):
        microstrip_step_parasitics(0.5, 1.0, 0.635, 9.9, 10.0)
    with pytest.raises(ValueError, match="只收收窄阶跃"):
        microstrip_step_parasitics(1.0, 1.0, 0.635, 9.9, 10.0)
    with pytest.raises(ValueError, match="Cs≤0"):
        microstrip_step_parasitics(1.2, 1.0, 0.635, 9.9, 10.0)


def test_step_cs_ls_independent_recompute_and_weights():
    """Cs/Ls 测试内独立算术逐位 + L' 权重面（窄线权重大、和为 1）。"""
    w1, w2, h, er = 1.0, 0.5, 0.635, 9.9
    res = microstrip_step_parasitics(w1, w2, h, er, 10.0)
    # 独立算术（Garg-Bahl 式逐项复算，非键内同式二次抄写）
    bracket = ((10.1 * math.log10(er) + 2.33) * 2.0
               - 12.6 * math.log10(er) - 3.17)
    assert res["c_shunt_pf"] == pytest.approx(
        1e-3 * math.sqrt(0.5) * bracket, rel=1e-12)
    dr = 1.0
    assert res["l_series_total_nh"] == pytest.approx(
        h * 1e-3 * (dr * (40.5 + 0.2 * dr) - 75.0 * math.log10(2.0)),
        rel=1e-12)
    # 权重面：宽线 Z 低 → L' 小 → 权重 <0.5；两端口分摊和=总
    assert 0.0 < res["weight_port1"] < 0.5
    assert (res["l_series_port1_nh"] + res["l_series_port2_nh"]
            == res["l_series_total_nh"])


# ─── MTI 频响（mti_frequency_response）───────────────────────────────────────

def test_mti_notch_peak_bit_exact_and_periodic():
    """|H|=2|sin(πfTr)| 恒等：f=0 凹口 0 逐位、峰 2 / 半凹口 √2 逐位、
    周期恒等 H(f+PRF)=H(f) 逐位（k≥1 凹口在双精度域 |sin(π)|~1e-16）。"""
    res = mti_frequency_response(
        [0.0, 1000.0, 2000.0, 500.0, 1500.0, 250.0, 1250.0],
        1000.0, 0.032)
    h = res["gain_mag"]
    assert h[0] == 0.0  # f=0 凹口逐位（sin(0)=0 精确）
    assert h[1] == pytest.approx(0.0, abs=1e-15)
    assert h[2] == pytest.approx(0.0, abs=1e-15)
    assert h[3] == 2.0 and h[4] == 2.0  # 峰 (k+1/2)·PRF 逐位（sin(π/2)=1）
    assert h[5] == math.sqrt(2.0)  # 半凹口 0.25·PRF（sin(π/4)）逐位
    assert h[6] == pytest.approx(math.sqrt(2.0), abs=1e-15)  # 1.25·PRF 差末位 ulp
    # 周期恒等 H(f+PRF)=H(f)（任意相位为末位 ulp 级；特殊角逐位见上）
    per = mti_frequency_response([300.0, 1300.0], 1000.0, 0.032)
    assert per["gain_mag"][0] == pytest.approx(per["gain_mag"][1], abs=1e-15)


def test_mti_blind_speed_identity_and_doppler_closure():
    """盲速 v_n=n·λ·PRF/2 独立算术 + 多普勒恒等式闭环（f_D=v·2/λ=凹口）。"""
    lam, prf = 0.032, 1000.0
    res = mti_frequency_response(0.0, prf, lam)
    assert res["blind_speed_1_mps"] == lam * prf / 2.0
    for n, v in enumerate(res["blind_speed_mps"], start=1):
        assert v == n * lam * prf / 2.0
    # 闭环：盲速经多普勒恒等式反解 = 凹口频率 k·PRF
    v1 = res["blind_speed_1_mps"]
    assert v1 * 2.0 / lam == 1.0 * prf


def test_mti_scalar_list_duality():
    """标量与单元素列表输入同值。"""
    a = mti_frequency_response(400.0, 1000.0, 0.032)
    b = mti_frequency_response([400.0], 1000.0, 0.032)
    assert a["gain_mag"] == b["gain_mag"]
    assert a["gain_mag"][0] == 2.0 * abs(math.sin(0.4 * math.pi))


# ─── MTI 改善因子（mti_improvement_factor）───────────────────────────────────

def test_improvement_closed_form_vs_numeric_dual_path():
    """闭式 I=1/(1−ρ) 与复化梯形数值积分双路径互证（#118，rel<1e-9）。"""
    res = mti_improvement_factor(0.3, 1000.0, 0.032)
    rel = (abs(res["i_linear"] - res["i_numeric_linear"])
           / res["i_linear"])
    assert rel < 1e-9
    # ρ/Gaussian 特征函数独立复算
    sig_f = 2.0 * 0.3 / 0.032
    rho = math.exp(-2.0 * math.pi ** 2 * sig_f ** 2 * (1.0 / 1000.0) ** 2)
    assert res["rho"] == pytest.approx(rho, rel=1e-12)
    assert res["i_linear"] == pytest.approx(1.0 / (1.0 - rho), rel=1e-12)


def test_improvement_narrow_spectrum_asymptote_and_monotone():
    """窄谱渐近 I≈1/(2π²σ_f²Tr²) + σ_v 单调递减 + 大谱宽 →1 上界。"""
    sig_v, prf, lam = 0.05, 1000.0, 0.032
    res = mti_improvement_factor(sig_v, prf, lam)
    sig_f = 2.0 * sig_v / lam
    expo = 2.0 * math.pi ** 2 * sig_f ** 2 / prf ** 2
    assert res["i_linear"] == pytest.approx(1.0 / expo, rel=1e-3)
    vals = [mti_improvement_factor(s, prf, lam)["i_linear"]
            for s in (0.1, 0.3, 1.0, 5.0, 20.0)]
    assert vals == sorted(vals, reverse=True)
    assert vals[-1] < 1.05  # 大谱宽 → I→1（自上而下趋近）
    assert vals[0] > vals[-1] > 1.0


def test_improvement_scv_identity_and_literature_band():
    """SCV 恒等式逐位 + 文献典型值带（land ~21.6dB / sea ~11.3dB）。"""
    land = mti_improvement_factor(0.3, 1000.0, 0.032, required_scnr_db=3.0)
    assert land["scv_db"] == land["i_db"] - 3.0
    assert 20.0 <= land["i_db"] <= 23.0
    sea = mti_improvement_factor(1.0, 1000.0, 0.032)
    assert 10.0 <= sea["i_db"] <= 13.0


def test_improvement_narrow_spectrum_numeric_domain_rejected():
    """谱宽×脉间积过窄（ρ 数值 ≡1、I 无界）显式拒绝。"""
    with pytest.raises(ValueError, match="谱宽"):
        mti_improvement_factor(1e-30, 1000.0, 0.032)


# ─── σ0 模型（clutter_sigma0_model）─────────────────────────────────────────

def test_sigma0_gamma_sine_identity_and_roundtrip():
    """γ 档正弦恒等独立算术逐位 + dB 闭环 roundtrip。"""
    res = clutter_sigma0_model("gamma", 30.0, gamma=0.05)
    assert res["sigma0_linear"] == pytest.approx(0.05 * 0.5, rel=1e-12)
    res5 = clutter_sigma0_model("gamma", 5.0, gamma=0.05)
    assert res5["sigma0_linear"] == pytest.approx(
        0.05 * math.sin(math.radians(5.0)), rel=1e-12)
    assert res5["sigma0_db"] == pytest.approx(
        10.0 * math.log10(res5["sigma0_linear"]), rel=1e-12)


def test_sigma0_constant_and_clutter_rcs_identity():
    """常数档 10^(db/10) 逐位 + σc=σ0·Ac 恒等 + Ac=R·ρ·θaz·secψ 独立算术。"""
    res = clutter_sigma0_model("constant", 30.0, sigma0_db=-20.0,
                               range_m=10000.0, resolution_m=15.0,
                               az_bw_deg=2.0)
    assert res["sigma0_linear"] == pytest.approx(0.01, rel=1e-12)
    psi = math.radians(30.0)
    ac = 10000.0 * 15.0 * math.radians(2.0) / math.cos(psi)
    assert res["clutter_area_m2"] == pytest.approx(ac, rel=1e-12)
    assert res["clutter_rcs_m2"] == pytest.approx(0.01 * ac, rel=1e-12)
    assert res["clutter_rcs_dbsm"] == pytest.approx(
        -20.0 + 10.0 * math.log10(ac), rel=1e-12)


def test_sigma0_guards_git_absent_and_partial_geo():
    """GIT 缺席如实拒绝（#122）+ 部分几何参口径歧义拒绝 + ψ 越域拒绝。"""
    with pytest.raises(ValueError, match="GIT"):
        clutter_sigma0_model("git", 5.0)
    with pytest.raises(ValueError, match="要么全给"):
        clutter_sigma0_model("gamma", 5.0, gamma=0.05, range_m=1.0)
    with pytest.raises(ValueError, match="掠射角域"):
        clutter_sigma0_model("gamma", 90.0, gamma=0.05)
    with pytest.raises(ValueError, match="model='gamma' 需 gamma"):
        clutter_sigma0_model("gamma", 5.0)
