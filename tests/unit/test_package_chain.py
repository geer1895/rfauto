r"""SB22-PK-1 封装互连链装配器测试（锚树预声明，#122 判据先行）。

每件 ≥2 独立基准（出处见 core/package_chain.py 模块 docstring 文献
核实账；本文件只列判据树）：

- **圆导线内阻抗 Bessel 全频带内核**：①直流极限恒等式 Re(Z')→1/(σπa²)
  （rel<1e-5 @ a/δ≈0.02）；②经典内感锚 Im(Z')/ω→μ₀/(8π)（圆导线教科
  书精确值）；③趋肤渐近收敛单调（O(δ/a) 慢收敛如实宽域钉：a/δ=27 时
  Re 偏高 <2.5%、Im 比 <1%，且随 a/δ 增大单调改善）。
- **趋肤渐近式**：①量纲域守卫 a/δ≥3（域内 identity Rs=√(πfμ₀/σ)）；
  ②δ=√(1/(πfμ₀σ)) 铜常数值（1 GHz ≈2.09 µm，教科书表值 2.0–2.1 带）。
- **键合线段**：①L=rosa 逐位（PK-7 单源直调对拍）；②低频 R_ac→R_dc
  极限；③串联段 S21=2Z₀/(2Z₀+Z) 独立代数路径；④1 nH/mm 行业经验带
  （UNVERIFIED_rule_of_thumb，advisory 不作硬裁判）。
- **凸点 π 段**：①h/d<2 量纲守卫（PK-7 rosa 域级联拒绝）；②低频透明
  极限（C 并臂直流开路、L 短）|S21|→1；③L/C 与 PK-7 直调逐位。
- **TGV 线段**：①Z₀=(60/√εr)·ln(b/a) 恒等式；②群延迟=ℓ√(L'C') 恒
  等式；③低频 R'→R_dc（Bessel 全频带内核）。
- **准 TEM 线段**：①L'C'c²=εeff 恒等式（机器精度）；②匹配线 S11≡0；
  ③介质损耗 |S21| dB=8.686·α·ℓ 闭式（α=ω√εeff·tanδ/(2c)）独立代数；
  ④相位延迟 ℓ√εeff/c。
- **链装配**：①级联恒等式 assemble==s1>>s2（cable_channel 单源）；②
  加有耗段插损逐频单调增；③service JSON 形状与守卫。
- **凸点阵互感**：①首行 vs filament exact 直调逐位；②对角=自感+对称
  ；③间距单调衰减；④n/bool 守卫。
- **差分对模链**：①匹配模线 Sdd11/Scc11≡0 + 无耗 |Sdd21|=1（0 dB）；
  ②失配单段 vs 独立代数式 S11=Γ(1−e^{−2jθ})/(1−Γ²e^{−2jθ})；③模转换
  恒等零声明（对称对模型边界）；④εeff 奇<偶 → 奇模相位快（mtl_modes
  even/odd 消费闭环 z_even>z_odd）；⑤空段/非 dict 守卫。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.mtl_modes import symmetric_pair_even_odd
from rfauto.core.package_chain import (
    assemble_chain,
    bondwire_network,
    bump_array_mutual_matrix,
    bump_pi_network,
    dc_resistance_per_length,
    diff_pair_chain_report,
    quasi_tem_line_network,
    round_wire_internal_impedance_per_length,
    skin_depth_m,
    solder_ball_network,
    tgv_line_network,
    wire_skin_resistance_per_length,
)
from rfauto.core.package_interconnect import (
    bump_inductance,
    bump_parallel_plate_capacitance,
    parallel_filament_mutual_exact_h,
)
from rfauto.service.package_chain_service import (
    build_diff_pair_report,
    build_package_chain_report,
    bump_array_crosstalk_report,
)

_MU0 = 4.0e-7 * math.pi
_C0 = 299792458.0
SIGMA_CU = 5.8e7
SIGMA_AU = 4.11e7
_A_CU = 12.7e-6  # 25.4 µm（1 mil）金/铜线半径


# ─── 圆导线内阻抗（Bessel 全频带）────────────────────────────────────────────


def test_bessel_dc_resistance_identity() -> None:
    """直流极限：Re(Z')→1/(σπa²)（精确恒等式，rel<1e-5 @ a/δ≈0.02）。"""
    freq = np.array([1.0e4])
    z = round_wire_internal_impedance_per_length(freq, _A_CU, SIGMA_CU)
    r_dc = dc_resistance_per_length(_A_CU, SIGMA_CU)
    assert z.shape == (1,)
    assert abs(z[0].real - r_dc) / r_dc < 1e-5


def test_bessel_dc_internal_inductance_mu0_over_8pi() -> None:
    """经典内感锚：Im(Z')/ω → μ₀/(8π)（圆导线教科书精确值，rel<1e-5）。"""
    freq = np.array([1.0e4])
    z = round_wire_internal_impedance_per_length(freq, _A_CU, SIGMA_CU)
    l_int = z[0].imag / (2.0 * math.pi * 1.0e4)
    assert abs(l_int - _MU0 / (8.0 * math.pi)) / (_MU0 / (8.0 * math.pi)) < 1e-5


def test_bessel_skin_asymptote_convergence_monotone() -> None:
    """趋肤渐近收敛：Re/(Rs/2πa) 与 Im/(Rs/2πa) 随 a/δ 增大单调趋 1
    （O(δ/a) 慢收敛，宽域钉 <2.5%/<1% @ a/δ≈27）。"""
    freq = np.array([1.0e9, 20.0e9])
    z = round_wire_internal_impedance_per_length(freq, _A_CU, SIGMA_CU)
    ratios = []
    for i, f in enumerate(freq):
        rs = math.sqrt(math.pi * f * _MU0 / SIGMA_CU)
        r_skin = rs / (2.0 * math.pi * _A_CU)
        ratios.append((z[i].real / r_skin, z[i].imag / r_skin))
    re_lo, im_lo = ratios[0]  # a/δ≈6.1
    re_hi, im_hi = ratios[1]  # a/δ≈27.2
    assert abs(re_hi - 1.0) < 0.025
    assert abs(im_hi - 1.0) < 0.01
    assert abs(re_hi - 1.0) < abs(re_lo - 1.0)
    assert abs(im_hi - 1.0) < abs(im_lo - 1.0)


def test_skin_depth_copper_1ghz_textbook_band() -> None:
    """δ=√(1/(πfμ₀σ))：铜 1 GHz ≈2.0898 µm，落教科书表值 2.0–2.1 µm 带。"""
    delta = skin_depth_m(1.0e9, SIGMA_CU)
    expected = math.sqrt(1.0 / (math.pi * 1.0e9 * _MU0 * SIGMA_CU))
    assert abs(delta - expected) / expected < 1e-12
    assert 2.0e-6 < delta < 2.1e-6


def test_skin_resistance_guard_and_identity() -> None:
    """渐近式守卫（a/δ<3 拒）+ 域内 Rs=√(πfμ₀/σ) 恒等式。"""
    with pytest.raises(ValueError, match="a/δ"):
        wire_skin_resistance_per_length(1.0e4, _A_CU, SIGMA_CU)
    f = 10.0e9
    r = wire_skin_resistance_per_length(f, _A_CU, SIGMA_CU)
    rs = math.sqrt(math.pi * f * _MU0 / SIGMA_CU)
    assert abs(r - rs / (2.0 * math.pi * _A_CU)) / r < 1e-12


# ─── 键合线段 ────────────────────────────────────────────────────────────────


def test_bondwire_rosa_value_and_scope() -> None:
    """L=rosa 逐位（μ0·l/2π·(ln(2l/r)−0.75)，PK-7 单源）；域内 in_scope。"""
    out = bondwire_network(
        np.array([1.0e9]), length_m=1.0e-3, radius_m=_A_CU,
        sigma_s_per_m=SIGMA_AU)
    l_manual = _MU0 * 1.0e-3 / (2.0 * math.pi) * (
        math.log(2.0 * 1.0e-3 / _A_CU) - 0.75)
    assert out["l_total_h"] == pytest.approx(l_manual, rel=1e-12)
    assert out["in_declared_scope"] is True
    assert out["l_over_r"] == pytest.approx(1.0e-3 / _A_CU, rel=1e-12)


def test_bondwire_low_freq_r_ac_converges_dc() -> None:
    """低频极限：R_ac(10 kHz)→R_dc（Bessel 全频带，rel<1e-4）。"""
    out = bondwire_network(
        np.array([1.0e4, 1.0e9]), length_m=1.0e-3, radius_m=_A_CU,
        sigma_s_per_m=SIGMA_AU)
    assert out["r_ac_ohm"][0] == pytest.approx(out["r_dc_ohm"], rel=1e-4)
    assert out["r_ac_ohm"][1] > out["r_dc_ohm"]


def test_bondwire_gold_1nh_per_mm_advisory_band() -> None:
    """行业经验带（UNVERIFIED_rule_of_thumb，advisory 不作硬裁判）：
    1 mm/1 mil 金线 L≈0.86 nH 落 0.6–1.2 nH/mm 带。"""
    out = bondwire_network(
        np.array([1.0e9]), length_m=1.0e-3, radius_m=_A_CU,
        sigma_s_per_m=SIGMA_AU)
    assert 0.6e-9 < out["l_total_h"] < 1.2e-9


def test_bondwire_series_s21_independent_algebra() -> None:
    """串联段独立代数：S21 = 2Z₀/(2Z₀+Z)，幅相双钉。

    Z 组成按模块口径（Z'_int 复数全量·ℓ + jωL——内感项不可漏；独立面
    是 S21 的二端口代数转换本身）。
    """
    f = 5.0e9
    out = bondwire_network(
        np.array([f]), length_m=2.0e-3, radius_m=_A_CU,
        sigma_s_per_m=SIGMA_AU, z_ref_ohm=50.0)
    z_int = round_wire_internal_impedance_per_length(
        np.array([f]), _A_CU, SIGMA_AU)[0]
    z = complex(z_int) * 2.0e-3 + 1j * 2.0 * math.pi * f * out["l_total_h"]
    s21_expected = 2.0 * 50.0 / (2.0 * 50.0 + z)
    s21 = complex(out["network"].s[0, 1, 0])
    np.testing.assert_allclose([abs(s21), np.angle(s21)],
                               [abs(s21_expected), np.angle(s21_expected)],
                               rtol=1e-10, atol=1e-10)


# ─── 凸点 π 段 ───────────────────────────────────────────────────────────────


def test_bump_guard_h_over_d_below_2() -> None:
    """h/d<2 超 rosa 直柱量纲域 → ValueError（PK-7 守卫级联）。"""
    with pytest.raises(ValueError, match="l/r"):
        bump_pi_network(
            np.array([1.0e9]), height_m=30e-6, diameter_m=100e-6,
            pad_diameter_m=80e-6, er_between=3.2)


def test_bump_low_freq_transparent_limit() -> None:
    """低频透明极限：|S21|→1，残差=凸点柱直流电阻 R_dc/(2Z₀)（物理量，
    非数值误差——0.22 mΩ / 100 Ω ≈ 2.2e-6）。"""
    f = np.array([1.0e5])
    out = bump_pi_network(
        f, height_m=1.0e-4, diameter_m=1.0e-4, pad_diameter_m=0.9e-4,
        er_between=3.2, sigma_s_per_m=SIGMA_CU)
    s21 = complex(out["network"].s[0, 1, 0])
    r_dc_total = dc_resistance_per_length(1.0e-4 / 2.0, SIGMA_CU) * 1.0e-4
    assert abs(abs(s21) - 1.0) == pytest.approx(r_dc_total / 100.0, rel=0.3)
    assert abs(np.angle(s21)) < 1e-6


def test_bump_consumes_pk7_single_source() -> None:
    """L/C 与 PK-7 直调逐位（零复写纪律）。"""
    f = np.array([1.0e9])
    out = bump_pi_network(
        f, height_m=1.0e-4, diameter_m=1.0e-4, pad_diameter_m=0.9e-4,
        er_between=3.2, sigma_s_per_m=SIGMA_CU)
    l_pk7 = bump_inductance(1.0e-4, 1.0e-4)
    c_pk7 = bump_parallel_plate_capacitance(0.9e-4, 1.0e-4, 3.2)
    assert out["l_total_h"] == l_pk7["l_total_h"]
    assert out["c_total_f"] == c_pk7["c_f"]


def test_ball_segment_reuses_bump_machinery() -> None:
    """焊球段与凸点段同构（同入参同 L/C 逐位；几何落 rosa 域 l/r≥2）。"""
    f = np.array([1.0e9])
    kw: dict[str, object] = {
        "height_m": 5.0e-4, "diameter_m": 2.5e-4,
        "pad_diameter_m": 2.0e-4, "er_between": 4.0,
        "sigma_s_per_m": 6.9e6, "z_ref_ohm": 50.0}
    ball = solder_ball_network(f, **kw)  # type: ignore[arg-type]
    bump = bump_pi_network(f, **kw)  # type: ignore[arg-type]
    assert ball["l_total_h"] == bump["l_total_h"]
    assert ball["c_total_f"] == bump["c_total_f"]


# ─── TGV 线段 ────────────────────────────────────────────────────────────────


def test_tgv_z0_and_delay_identities() -> None:
    """Z₀=(1/2π)√(μ0/(ε0εr))·ln(b/a) 与群延迟 ℓ√(L'C') 双恒等式。

    （"60Ω" 是 √(μ0/ε0)/2π=59.958 Ω 的舍入惯称——判据用精确常数，
    避免 7e-4 级伪差。）
    """
    eps0 = 1.0 / (_MU0 * _C0 * _C0)
    out = tgv_line_network(
        np.array([1.0e9]), r_via_m=15e-6, r_shield_m=75e-6,
        length_m=0.3e-3, er_glass=4.2, tan_d=0.001)
    z0_manual = (0.5 / math.pi) * math.sqrt(_MU0 / (eps0 * 4.2)) * math.log(5.0)
    assert out["z0_coax_ohm"] == pytest.approx(z0_manual, rel=1e-12)
    td_manual = 0.3e-3 * math.sqrt(_MU0 / (2 * math.pi) * math.log(5.0)
                                   * 2 * math.pi * eps0 * 4.2 / math.log(5.0)) * 1e12
    assert out["t_delay_ps"] == pytest.approx(td_manual, rel=1e-12)


def test_tgv_low_freq_r_converges_dc() -> None:
    """TGV R'（Bessel 全频带）低频→R_dc 每米、高频单调增（√f）。"""
    f_lo, f_hi = 1.0e4, 1.0e10
    out = tgv_line_network(
        np.array([f_lo, f_hi]), r_via_m=15e-6, r_shield_m=75e-6,
        length_m=0.3e-3, er_glass=4.2)
    r = np.asarray(out["r_per_length_ohm_per_m"], dtype=float)
    r_dc_m = dc_resistance_per_length(15e-6, SIGMA_CU)
    assert r[0] == pytest.approx(r_dc_m, rel=1e-4)
    assert r[1] > r[0]


# ─── 准 TEM 线段 ─────────────────────────────────────────────────────────────


def test_qtem_lc_identity_eps_eff() -> None:
    """L'C'c²=εeff 恒等式（机器精度）。"""
    out = quasi_tem_line_network(
        np.array([1.0e9]), z0_ohm=43.5, eps_eff=3.17, length_m=2e-3)
    assert out["identity_lc_over_mu_eps"] == pytest.approx(3.17, rel=1e-14)


def test_qtem_matched_line_s11_zero() -> None:
    """匹配线 S11≡0（z0=z_ref，机器精度）。"""
    out = quasi_tem_line_network(
        np.array([1.0e9, 1.0e10]), z0_ohm=50.0, eps_eff=3.0, length_m=5e-3)
    assert float(np.max(np.abs(out["network"].s[:, 0, 0]))) < 1e-12


def test_qtem_dielectric_il_closed_form() -> None:
    """介质损耗首阶 |S21| dB=8.686·α·ℓ，α=ω√εeff·tanδ/(2c)（独立代数路径）。

    判据为低损首阶式（tanδ=0.02 高阶项 ~1e-5 级 → rel 容差 1e-4）。
    """
    f = np.array([2.0e9, 8.0e9])
    out = quasi_tem_line_network(
        f, z0_ohm=50.0, eps_eff=3.0, length_m=5e-3, tan_d=0.02)
    for i, fv in enumerate(f):
        alpha = 2.0 * math.pi * fv * math.sqrt(3.0) * 0.02 / (2.0 * _C0)
        il_expected = 8.686 * alpha * 5e-3
        assert abs(out["network"].s[i, 1, 0]) == pytest.approx(
            10 ** (-il_expected / 20.0), rel=1e-4)


def test_qtem_phase_delay_identity() -> None:
    """相位延迟=ℓ√εeff/c（无损匹配线 S21 相位）。"""
    out = quasi_tem_line_network(
        np.array([5.0e9]), z0_ohm=50.0, eps_eff=3.0, length_m=4e-3)
    phase = -float(np.angle(out["network"].s[0, 1, 0]))
    assert phase == pytest.approx(2.0 * math.pi * 5.0e9 * 4e-3 * math.sqrt(3.0)
                                  / _C0, rel=1e-10)


# ─── 链装配 ──────────────────────────────────────────────────────────────────


def _qtem_net(f: np.ndarray, z0: float, tand: float) -> object:
    return quasi_tem_line_network(
        f, z0_ohm=z0, eps_eff=3.0, length_m=3e-3, tan_d=tand)["network"]


def test_assemble_chain_cascade_identity() -> None:
    """级联恒等式：assemble_chain(s1,s2) == s1>>s2（cable_channel 单源）。"""
    f = np.array([1.0e9, 4.0e9])
    s1 = _qtem_net(f, 50.0, 0.02)
    s2 = _qtem_net(f, 45.0, 0.0)
    out = assemble_chain([s1, s2], z_ref_ohm=50.0)
    manual = s1 >> s2  # type: ignore[operator]
    np.testing.assert_allclose(np.asarray(out["network"].s),
                               np.asarray(manual.s), rtol=1e-12, atol=1e-14)


def test_chain_il_monotone_with_more_lossy_segments() -> None:
    """加有耗匹配段 → 插损逐频单调增（匹配段 IL 只加不减）。"""
    f = np.array([1.0e9, 4.0e9])
    one = assemble_chain([_qtem_net(f, 50.0, 0.02)], z_ref_ohm=50.0)
    three = assemble_chain(
        [_qtem_net(f, 50.0, 0.02), _qtem_net(f, 50.0, 0.02),
         _qtem_net(f, 50.0, 0.02)], z_ref_ohm=50.0)
    assert np.all(three["report"]["il_db"] > one["report"]["il_db"])
    assert three["report"]["passive"] and one["report"]["passive"]


def test_chain_guards_empty_segments() -> None:
    with pytest.raises(ValueError, match="非空段表"):
        assemble_chain([], z_ref_ohm=50.0)


# ─── 凸点阵互感矩阵 ──────────────────────────────────────────────────────────


def test_array_row0_matches_direct_exact_calls() -> None:
    """首行 vs filament exact 直调逐位（阵列化=零新闭式）。"""
    m = bump_array_mutual_matrix(
        4, height_m=1.0e-4, diameter_m=1.0e-4, pitch_m=1.5e-4)
    for j in range(1, 4):
        m_direct = parallel_filament_mutual_exact_h(1.0e-4, j * 1.5e-4)
        assert m["mutual_h"][0, j] == m_direct


def test_array_structure_and_monotone_decay() -> None:
    """对角=自感、矩阵对称、互感随间距单调衰减、k_neighbor∈(0,1)。"""
    m = bump_array_mutual_matrix(
        5, height_m=1.0e-4, diameter_m=1.0e-4, pitch_m=1.5e-4)
    mu = m["mutual_h"]
    assert m["l_self_h"] == bump_inductance(1.0e-4, 1.0e-4)["l_total_h"]
    np.testing.assert_array_equal(mu, mu.T)
    assert np.all(np.diag(mu) == 0.0)
    assert mu[0, 1] > mu[0, 2] > mu[0, 3] > mu[0, 4] > 0.0
    assert 0.0 < m["k_neighbor"] < 1.0


@pytest.mark.parametrize("bad_n", [0, -1])
def test_array_guard_n_bumps(bad_n: int) -> None:
    with pytest.raises(ValueError, match="n_bumps"):
        bump_array_mutual_matrix(
            bad_n, height_m=1.0e-4, diameter_m=1.0e-4, pitch_m=1.5e-4)


def test_array_guard_bool_n() -> None:
    with pytest.raises(ValueError, match="int"):
        bump_array_mutual_matrix(
            True, height_m=1.0e-4, diameter_m=1.0e-4, pitch_m=1.5e-4)  # type: ignore[arg-type]


# ─── 差分对模链 ──────────────────────────────────────────────────────────────


_ODD = {"z0_mode_ohm": 100.0, "eps_eff": 2.5, "length_m": 3e-3}
_EVEN = {"z0_mode_ohm": 25.0, "eps_eff": 3.5, "length_m": 3e-3}


def test_diffpair_matched_lines_zero_reflection_and_lossless_il() -> None:
    """匹配模线（Z0o=2Zref、Z0e=Zref/2）：Sdd11/Scc11≡0 且无耗 |Sdd21|=1。"""
    f = np.array([1.0e9, 5.0e9])
    out = diff_pair_chain_report(
        f, odd_segments=[dict(_ODD)], even_segments=[dict(_EVEN)],
        z_ref_ohm=50.0)
    s_odd = np.asarray(out["network_odd"].s)
    s_even = np.asarray(out["network_even"].s)
    assert float(np.max(np.abs(s_odd[:, 0, 0]))) < 1e-9
    assert float(np.max(np.abs(s_even[:, 0, 0]))) < 1e-9
    np.testing.assert_allclose(np.abs(s_odd[:, 1, 0]), 1.0, rtol=1e-12)


def test_diffpair_mismatch_vs_independent_algebra() -> None:
    """失配单段 vs 独立代数式 S11=Γ(1−e^{−2jθ})/(1−Γ²e^{−2jθ})。"""
    f = 6.0e9
    z0o, eps, length = 75.0, 2.8, 2.5e-3
    out = diff_pair_chain_report(
        np.array([f]),
        odd_segments=[{"z0_mode_ohm": z0o, "eps_eff": eps, "length_m": length}],
        even_segments=[dict(_EVEN)], z_ref_ohm=50.0)
    zb = 2.0 * 50.0
    gamma = (z0o - zb) / (z0o + zb)
    theta = 2.0 * math.pi * f * length * math.sqrt(eps) / _C0
    e = np.exp(-2j * theta)
    s11_expected = gamma * (1.0 - e) / (1.0 - gamma * gamma * e)
    s11 = complex(np.asarray(out["network_odd"].s)[0, 0, 0])
    assert abs(s11 - s11_expected) < 1e-10


def test_diffpair_mode_conversion_declared_zero() -> None:
    """对称对模型边界：模转换恒等零（声明值非数值估计）。"""
    f = np.array([1.0e9, 5.0e9])
    out = diff_pair_chain_report(
        f, odd_segments=[dict(_ODD)], even_segments=[dict(_EVEN)],
        z_ref_ohm=50.0)
    assert out["mode_conversion_max_linear"] == 0.0
    assert all(math.isinf(x) for x in out["sdc21_db"])


def test_diffpair_odd_faster_with_mtl_modes_consumption() -> None:
    """mtl_modes even/odd 消费闭环：z_even>z_odd、εeff 奇<偶 → 奇模相位快。"""
    pair = symmetric_pair_even_odd(
        4.0e-7, 1.2e-7, 8.0e-11, 2.5e-11)
    assert pair["z_even_ohm"] > pair["z_odd_ohm"]
    eps_even, eps_odd = 3.4, 2.6
    f = np.array([8.0e9])
    out = diff_pair_chain_report(
        f,
        odd_segments=[{"z0_mode_ohm": pair["z_odd_ohm"],
                       "eps_eff": eps_odd, "length_m": 4e-3}],
        even_segments=[{"z0_mode_ohm": pair["z_even_ohm"],
                        "eps_eff": eps_even, "length_m": 4e-3}],
        z_ref_ohm=50.0)
    phase_odd = abs(float(np.angle(np.asarray(out["network_odd"].s)[0, 1, 0])))
    phase_even = abs(float(np.angle(np.asarray(out["network_even"].s)[0, 1, 0])))
    assert phase_odd < phase_even


def test_diffpair_guards() -> None:
    """空段表/非 dict 段守卫。"""
    f = np.array([1.0e9])
    with pytest.raises(ValueError, match="非空段表"):
        diff_pair_chain_report(f, odd_segments=[], even_segments=[dict(_EVEN)])
    with pytest.raises(ValueError, match="dict"):
        diff_pair_chain_report(
            f, odd_segments=["bad"], even_segments=[dict(_EVEN)])  # type: ignore[list-item]


# ─── service 面（JSON 进出）──────────────────────────────────────────────────


def test_service_chain_report_json_shapes() -> None:
    """报告形状：全 JSON 标量/列表、passive、逐段元数据。"""
    payload = {
        "freq_hz": [1.0e9, 5.0e9, 1.0e10],
        "z_ref_ohm": 50.0,
        "segments": [
            {"kind": "bondwire", "length_m": 1.0e-3, "radius_m": 12.7e-6,
             "sigma_s_per_m": SIGMA_AU},
            {"kind": "bump", "height_m": 1.0e-4, "diameter_m": 1.0e-4,
             "pad_diameter_m": 0.9e-4, "er_between": 3.2},
            {"kind": "line", "z0_ohm": 50.0, "eps_eff": 3.0,
             "length_m": 5e-3, "tan_d": 0.02},
        ],
    }
    out = build_package_chain_report(payload)
    assert out["n_segments"] == 3
    assert out["passive"] is True
    assert isinstance(out["il_db"], list) and len(out["il_db"]) == 3
    assert all(isinstance(x, float) for x in out["il_db"])
    assert out["segments_meta"][0]["kind"] == "bondwire"
    assert out["segments_meta"][2]["source"]


def test_service_chain_il_monotone_in_payload() -> None:
    """service 面 IL 单调：3 段（含 2 个有耗 line）> 1 段逐频。"""
    base = {"freq_hz": [1.0e9, 5.0e9], "z_ref_ohm": 50.0,
            "segments": [{"kind": "line", "z0_ohm": 50.0, "eps_eff": 3.0,
                          "length_m": 5e-3, "tan_d": 0.02}]}
    more = dict(base)
    more["segments"] = list(base["segments"]) + [
        {"kind": "line", "z0_ohm": 50.0, "eps_eff": 3.0,
         "length_m": 5e-3, "tan_d": 0.02} for _ in range(2)]
    one = build_package_chain_report(base)
    three = build_package_chain_report(more)
    assert np.all(np.asarray(three["il_db"]) > np.asarray(one["il_db"]))


def test_service_line_rdl_synthesis_single_source() -> None:
    """RDL 段走 synthesis 单源：width+stackup → forward_z0 → 近匹配。"""
    from rfauto.core.synthesis import Stackup, inverse_width

    stackup = Stackup(name="t_rdl", epsilon_r=3.2, thickness_mm=0.02,
                      loss_tangent=0.02, rho=1.724e-8, rough_mm=0.0)
    w_mm, _z0_actual, status = inverse_width(50.0, 5.0, stackup, w_min_mm=4e-4,
                                             w_max_mm=2.0)
    assert status == "ok"
    payload = {
        "freq_hz": [1.0e9, 5.0e9],
        "segments": [{"kind": "line", "width_mm": w_mm,
                      "stackup": {"epsilon_r": 3.2, "thickness_mm": 0.02,
                                  "loss_tangent": 0.02},
                      "length_m": 4e-3, "tan_d": 0.02}],
    }
    out = build_package_chain_report(payload)
    note = out["segments_meta"][0]["design_note"]
    assert "forward_z0" in note
    # 单源回代：z0≈50 → 近匹配（|S11| 很小 → 回损深）
    assert min(out["rl_db"]) > 30.0


def test_service_diff_pair_report_shapes() -> None:
    out = build_diff_pair_report({
        "freq_hz": [1.0e9, 6.0e9],
        "z_ref_ohm": 50.0,
        "odd_segments": [dict(_ODD)],
        "even_segments": [dict(_EVEN)],
    })
    assert out["basis"] == {"sdd_ref_ohm": 100.0, "scc_ref_ohm": 25.0}
    assert out["mode_conversion_max_linear"] == 0.0
    assert len(out["sdd21_db"]) == 2
    assert out["passive"] is True


def test_service_bump_array_report_shapes() -> None:
    out = bump_array_crosstalk_report({
        "n_bumps": 3, "height_m": 1.0e-4, "diameter_m": 1.0e-4,
        "pitch_m": 1.5e-4})
    assert out["n_bumps"] == 3
    assert len(out["mutual_ph"]) == 3 and len(out["mutual_ph"][0]) == 3
    assert 0.0 < out["k_neighbor"] < 1.0


@pytest.mark.parametrize("bad_payload", [
    {"freq_hz": [1.0e9], "segments": [{"kind": "alien"}]},
    {"freq_hz": [1.0e9], "segments": []},
    {"freq_hz": [1.0e9], "segments": [{"kind": "bondwire"}]},
    {"freq_hz": [], "segments": [{"kind": "bondwire", "length_m": 1e-3,
                                  "radius_m": 1e-5}]},
    {"freq_hz": [2.0e9, 1.0e9], "segments": [{"kind": "bondwire",
                                              "length_m": 1e-3,
                                              "radius_m": 1e-5}]},
])
def test_service_guards(bad_payload: dict) -> None:
    with pytest.raises(ValueError):
        build_package_chain_report(bad_payload)
