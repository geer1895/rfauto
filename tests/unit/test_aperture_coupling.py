"""EM-2 孔缝泄漏 SE 族单测（Bethe 极化率/传输截面 + Robinson 全链
+ 矩形缝截止穿透，2026-10-02）。

锚树口径（#118 教训：锚值独立复算/独立公式，不赌推导）：
- Bethe 原文式逐值回收：圆孔 αe=2a³/3、αm=4a³/3（规格原文式，Bethe
  1944）；方孔 2l³/(3π^{3/2})、4l³/(3π^{3/2})；方孔↔等面积圆孔精确
  相等（解析恒等）；矩形 Table 4.1 椭圆积分闭式（方孔极限连续 +
  amy=amx·(w/l)² 恒等 + 窄缝量级序）。
- 传输截面 σ_t=(2k⁴/9π)Σα²（Junqua 口径）：独立内联复算 + 圆孔约简式
  8k⁴a⁶/(9π) 双路互证；幂律恒等：σ_t∝f⁴、∝a⁶、σ_t/λ²∝(a/λ)⁶
  ——**孔径-波长幂律 −60dB/dec（SE 视角）= 1e-6 级严格恒等**（round17
  EM-2 验收锚；Robinson 腔链同域孔径斜率 ≈−47dB/dec 另行并陈钉带）。
- Robinson 1998 式(1)-(12) 全链（White Rose 后印本逐式回收，留档
  runs/em2/robinson1998_postprint.pdf）：图锚=Fig.6/7（300×120×300mm
  腔 t=1.5mm + 100×5mm 缝、p=150mm：谐振 ~700MHz 负屏蔽、
  SE_E(200MHz)≈45dB、SE 随 p 单调增、TE10 截止 500MHz——按图读数
  放宽容差）；单点全链测试内独立重写裁判（|Δ|≤1e-9 dB）；圆孔式(11)
  映射恒等；n 孔式(12) 缩放=20lg n（电小孔域）；ζ 损耗使谐振 dip
  变浅（物理方向锚）。
- 矩形缝截止穿透：f_c=c/(2L)、SE=20lg(e)·t·√((π/L)²−k0²)（f→0 极限
  27.2875·t/L dB 独立内联复算）；t→0 薄屏退化；f≥f_c 显式拒绝。
- 负例守卫：全部域出界显式拒绝（含厚壁 w_e≤0、缝半波谐振邻域、
  近似式(2)适用域 k≥1/√2）。
"""
from __future__ import annotations

import cmath
import json
import math
from itertools import pairwise

import pytest

from rfauto.core.aperture_coupling import (
    APERTURE_CIRCULAR,
    APERTURE_SLOT,
    aperture_effective_width_m,
    aperture_impedance_ohm,
    bethe_polarizability_circle,
    bethe_polarizability_rectangle,
    bethe_polarizability_square,
    bethe_transmission_cross_section_m2,
    coplanar_strip_impedance_approx_ohm,
    coplanar_strip_impedance_exact_ohm,
    robinson_enclosure_se,
    slot_cutoff_frequency_hz,
    slot_thickness_se_db,
)
from rfauto.core.metasurface_lut import C0_M_S, ETA0_OHM

# Robinson 1998 Fig.6/7 图锚几何（Table I 第一行：300×120×300mm 黄铜
# t=1.5mm；缝 100×5mm；观察 p=150mm=腔中心）
_A, _B, _D, _T = 0.3, 0.12, 0.3, 0.0015
_L_LA, _L_W, _P = 0.1, 0.005, 0.15


def _fig67_kwargs(**overrides):
    base = dict(
        enclosure_width_m=_A,
        enclosure_height_m=_B,
        enclosure_depth_m=_D,
        wall_thickness_m=_T,
        aperture_length_m=_L_LA,
        aperture_width_m=_L_W,
        observation_distance_m=_P,
    )
    base.update(overrides)
    return base


# ─── Bethe 极化率（原文式逐值回收）────────────────────────────────────────

@pytest.mark.parametrize("radius_m", [1.0e-3, 2.5e-3, 1.0e-2])
def test_bethe_circle_original_formula(radius_m):
    """圆孔 αe=2a³/3、αm=4a³/3（规格原文式，Bethe 1944）逐值回收。"""
    pol = bethe_polarizability_circle(radius_m)
    a3 = radius_m ** 3
    assert pol["alpha_e_m3"] == pytest.approx(2.0 * a3 / 3.0, rel=1e-12)
    assert pol["alpha_mx_m3"] == pytest.approx(4.0 * a3 / 3.0, rel=1e-12)
    assert pol["alpha_my_m3"] == pytest.approx(4.0 * a3 / 3.0, rel=1e-12)


def test_bethe_circle_scaling_cubic():
    """α ∝ a³（同族缩放比 8，精确恒等）。"""
    p1 = bethe_polarizability_circle(1.0e-3)
    p2 = bethe_polarizability_circle(2.0e-3)
    for key in ("alpha_e_m3", "alpha_mx_m3", "alpha_my_m3"):
        assert p2[key] / p1[key] == pytest.approx(8.0, rel=1e-12)


def test_bethe_square_original_formula_and_circle_equivalence():
    """方孔闭式 2l³/(3π^{3/2})、4l³/(3π^{3/2}）+ 等面积圆孔精确相等。"""
    side = 5.0e-3
    sq = bethe_polarizability_square(side)
    denom = 3.0 * math.pi ** 1.5
    assert sq["alpha_e_m3"] == pytest.approx(
        2.0 * side ** 3 / denom, rel=1e-12)
    assert sq["alpha_mx_m3"] == pytest.approx(
        4.0 * side ** 3 / denom, rel=1e-12)
    # 同面积 π r² = l² ⇒ r = l/√π：Table 4.1 两行解析恒等（跨形互证锚）
    circ = bethe_polarizability_circle(side / math.sqrt(math.pi))
    for key in ("alpha_e_m3", "alpha_mx_m3", "alpha_my_m3"):
        assert sq[key] == pytest.approx(circ[key], rel=1e-12)


def test_bethe_rectangle_limits_and_identities():
    """矩形缝：方孔极限连续 + amy=amx·(w/l)² 恒等 + 窄缝量级序。"""
    length = 0.1
    # 方孔极限连续（w=l−1e-9 → 方孔闭式，rel ≤1e-6）
    near = bethe_polarizability_rectangle(length, length * (1.0 - 1e-9))
    sq = bethe_polarizability_square(length)
    for key in ("alpha_e_m3", "alpha_mx_m3", "alpha_my_m3"):
        assert near[key] == pytest.approx(sq[key], rel=1e-6)
    # amy/amx = (w/l)² 精确恒等（Table 4.1 两式结构比）
    for ratio in (0.5, 0.1, 0.01):
        rec = bethe_polarizability_rectangle(length, length * ratio)
        assert rec["alpha_my_m3"] / rec["alpha_mx_m3"] == pytest.approx(
            ratio * ratio, rel=1e-12)
    # 窄缝（w/l=0.01）：沿缝长磁耦合 αmx 主导，αe/αmy 快速趋零
    rec = bethe_polarizability_rectangle(length, length * 0.01)
    assert rec["alpha_mx_m3"] / rec["alpha_e_m3"] > 1.0e4
    assert rec["alpha_e_m3"] / rec["alpha_mx_m3"] < 1.0e-4


def test_bethe_rectangle_rejects_w_greater_than_l():
    with pytest.raises(ValueError, match="长轴沿缝长"):
        bethe_polarizability_rectangle(0.01, 0.1)


# ─── 传输截面 σ_t 与孔径-波长幂律 −60dB/dec 恒等（规格验收锚）──────────────


def _sigma_t_independent(f_hz: float, radius_m: float) -> float:
    """独立裁判路：σ_t=(2k⁴/9π)(αe²+αmx²+αmy²)，α 直取原文式（#118：
    与内核同式但测试内独立书写，α 不读内核返回值）。"""
    k0 = 2.0 * math.pi * f_hz / C0_M_S
    a3 = radius_m ** 3
    a_e = 2.0 * a3 / 3.0
    a_mx = 4.0 * a3 / 3.0
    a_my = 4.0 * a3 / 3.0
    return (2.0 * k0 ** 4 / (9.0 * math.pi)) * (
        a_e * a_e + a_mx * a_mx + a_my * a_my)


def test_sigma_t_matches_independent_recompute():
    """内核 σ_t 与独立复算一致（1GHz、a=1mm，rel ≤1e-12）。"""
    f_hz, radius_m = 1.0e9, 1.0e-3
    pol = bethe_polarizability_circle(radius_m)
    got = bethe_transmission_cross_section_m2(f_hz, pol)
    assert got == pytest.approx(
        _sigma_t_independent(f_hz, radius_m), rel=1e-12)


def test_sigma_t_circle_reduced_form():
    """圆孔约简式 σ_t=8k⁴a⁶/(9π)（Σα²=4a⁶ 解析约简）双路互证。"""
    f_hz, radius_m = 1.0e9, 1.0e-3
    got = bethe_transmission_cross_section_m2(
        f_hz, bethe_polarizability_circle(radius_m))
    k0 = 2.0 * math.pi * f_hz / C0_M_S
    reduced = 8.0 * k0 ** 4 * radius_m ** 6 / (9.0 * math.pi)
    assert got == pytest.approx(reduced, rel=1e-12)


def test_sigma_t_power_laws_f4_a6():
    """幂律恒等：σ_t ∝ f⁴（40dB/dec）、∝a⁶（60dB/dec），十年期斜率
    1e-9 级精确（无小量近似的解析恒等）。"""
    def sigma(f_hz, radius_m):
        return bethe_transmission_cross_section_m2(
            f_hz, bethe_polarizability_circle(radius_m))
    # f 十年期（a 固定）
    f1, f2 = 1.0e8, 1.0e9
    slope_f = 10.0 * math.log10(sigma(f2, 1.0e-3) / sigma(f1, 1.0e-3))
    assert slope_f == pytest.approx(40.0, abs=1e-9)
    # a 十年期（f 固定）
    a1, a2 = 1.0e-4, 1.0e-3
    slope_a = 10.0 * math.log10(sigma(1.0e9, a2) / sigma(1.0e9, a1))
    assert slope_a == pytest.approx(60.0, abs=1e-9)


def test_aperture_wavelength_power_law_minus_60_identity():
    """**孔径-波长幂律 −60dB/dec 恒等（round17 EM-2 验收锚）**：
    圆孔 σ_t/λ²=(32π³/9)·(a/λ)⁶ 严格 6 次幂 ⇒ SE 视角 −60dB/dec，
    任意十年期逐位恒等（1e-6 门，实际 ~1e-12 浮点底）。"""
    lam = C0_M_S / 1.0e9  # 1GHz：λ≈0.3m
    r_small, r_big = lam * 1.0e-4, lam * 1.0e-3  # a/λ 十年期 [1e-4,1e-3]
    s1 = bethe_transmission_cross_section_m2(
        1.0e9, bethe_polarizability_circle(r_small)) / lam ** 2
    s2 = bethe_transmission_cross_section_m2(
        1.0e9, bethe_polarizability_circle(r_big)) / lam ** 2
    slope_sigma = 10.0 * math.log10(s2 / s1)  # 传输视角
    assert slope_sigma == pytest.approx(60.0, abs=1e-6)
    slope_se = -slope_sigma  # SE 视角（规格原文：−60dB/dec）
    assert slope_se == pytest.approx(-60.0, abs=1e-6)


def test_sigma_t_rejects_bad_input():
    """负例守卫：f≤0 / 非 dict / 缺键 / 非有限极化率显式拒绝。"""
    pol = bethe_polarizability_circle(1.0e-3)
    with pytest.raises(ValueError, match="frequency_hz"):
        bethe_transmission_cross_section_m2(0.0, pol)
    with pytest.raises(ValueError, match="dict"):
        bethe_transmission_cross_section_m2(1.0e9, (1.0, 2.0, 3.0))
    with pytest.raises(ValueError, match="缺键"):
        bethe_transmission_cross_section_m2(1.0e9, {"alpha_e_m3": 1.0})
    bad = dict(pol)
    bad["alpha_mx_m3"] = float("nan")
    with pytest.raises(ValueError, match="有限"):
        bethe_transmission_cross_section_m2(1.0e9, bad)


# ─── Robinson CPS 阻抗（式(2) 与 Gupta 精确式；Fig.2 读数锚）───────────────


def test_z0s_exact_fig2_anchors_and_monotonic():
    """精确式 Z0s=120π·K(k)/K'(k)：Fig.2 读数锚（k=0.01→≈100Ω、
    k=0.7→≈390Ω，±15% 图读容差）+ k 单调增 + 端限行为。"""
    z_lo = coplanar_strip_impedance_exact_ohm(0.01)
    assert z_lo == pytest.approx(100.0, rel=0.15)
    z_hi = coplanar_strip_impedance_exact_ohm(0.7)
    assert z_hi == pytest.approx(390.0, rel=0.15)
    ks = [0.01, 0.05, 0.1, 0.2, 0.4, 0.7, 0.9]
    zs = [coplanar_strip_impedance_exact_ohm(k) for k in ks]
    assert all(z2 > z1 for z1, z2 in pairwise(zs))
    # k→0⁺ 短路（k=1e-4 实测 ≈55.9Ω）、k→1⁻ 开路（0.999 实测 ≈1078Ω）
    assert 40.0 < coplanar_strip_impedance_exact_ohm(1e-4) < 70.0
    assert coplanar_strip_impedance_exact_ohm(0.999) > 800.0


def test_z0s_approx_matches_exact_in_paper_domain():
    """近似式(2) 与精确式在论文域内一致（误差随 k 对数缓增：k=0.003
    实测 5.1%→k=0.1 实测 10.4%，逐档放带宽）。"""
    for k, tol in ((0.003, 0.07), (0.01, 0.07), (0.03, 0.09), (0.1, 0.12)):
        exact = coplanar_strip_impedance_exact_ohm(k)
        approx = coplanar_strip_impedance_approx_ohm(k)
        assert abs(approx - exact) / exact < tol


def test_z0s_domain_guards():
    """负例守卫：近似式 k≥1/√2 出域、精确式 k≥1 / k=0 显式拒绝。"""
    with pytest.raises(ValueError, match="适用域"):
        coplanar_strip_impedance_approx_ohm(1.0 / math.sqrt(2.0))
    with pytest.raises(ValueError, match="\\(0,1\\)"):
        coplanar_strip_impedance_exact_ohm(1.0)
    with pytest.raises(ValueError, match="\\(0,1\\)"):
        coplanar_strip_impedance_exact_ohm(1.5)
    with pytest.raises(ValueError, match="必须 >0"):
        coplanar_strip_impedance_exact_ohm(0.0)


# ─── 厚壁修正（式(1)）─────────────────────────────────────────────────────


def test_effective_width_thin_limit_and_known_value():
    """t=0 精确返回 w（薄屏极限物理恒等）；已知值独立内联复算。"""
    w = 5.0e-3
    assert aperture_effective_width_m(w, 0.0) == w
    t = 1.5e-3
    we_expected = w - (5.0 * t / (4.0 * math.pi)) * (
        1.0 + math.log(4.0 * math.pi * w / t))
    assert aperture_effective_width_m(w, t) == pytest.approx(
        we_expected, rel=1e-12)


def test_effective_width_monotonic_in_thickness():
    """w_e 随壁厚单调降（厚壁使缝电窄）。"""
    w = 5.0e-3
    vals = [aperture_effective_width_m(w, t)
            for t in (0.0, 1e-4, 5e-4, 1.0e-3, 1.5e-3)]
    assert all(v2 < v1 for v1, v2 in pairwise(vals))


def test_effective_width_rejects_closed_slot():
    """厚壁出域（w_e≤0，缝等效闭合）显式拒绝：w=1mm、t=10mm。"""
    with pytest.raises(ValueError, match="厚壁修正出域"):
        aperture_effective_width_m(1.0e-3, 1.0e-2)


# ─── Robinson 全链图锚（Fig.6/7）与结构锚 ─────────────────────────────────


def _fig67_se_axis(**overrides) -> list[float]:
    f_axis = [f * 1.0e6 for f in range(600, 801)]
    return robinson_enclosure_se(
        f_axis_hz=f_axis, **_fig67_kwargs(**overrides))["se_electric_db"]


def test_robinson_fig67_resonance_anchor():
    """图锚：谐振 dip ≈700MHz（原文 "approximately 700 MHz"；
    实测无损链 703MHz，窗 ±30MHz 覆盖网格粒度）且 dip 为负屏蔽
    （原文 "negative shielding (field enhancement)"）。"""
    se_axis = _fig67_se_axis()
    i_min = min(range(len(se_axis)), key=lambda i: se_axis[i])
    dip_mhz = 600 + i_min
    assert 670 <= dip_mhz <= 730
    assert se_axis[i_min] < 0.0


def test_robinson_fig67_se_levels_and_frequency_trend():
    """图锚读数：SE_E(200MHz)≈45dB（窗 [40,52]）；谐振前 SE 随频率
    下降（原文 "Below the resonant frequency, S_E decreases with
    frequency"）。"""
    r = robinson_enclosure_se(
        f_axis_hz=[5.0e7, 1.0e8, 2.0e8, 7.0e8], **_fig67_kwargs())
    se = r["se_electric_db"]
    assert 40.0 <= se[2] <= 52.0
    assert se[0] > se[1] > se[2]


def test_robinson_fig67_distance_monotonicity():
    """图锚：SE 随观察距离 p 增大（原文 "increases with distance from
    the aperture"；Fig.6 三曲线序 p=30<150<270mm @200MHz）。"""
    ses = [
        robinson_enclosure_se(
            frequency_hz=2.0e8,
            **_fig67_kwargs(observation_distance_m=p))["se_electric_db"][0]
        for p in (0.03, 0.15, 0.27)
    ]
    assert ses[0] < ses[1] < ses[2]


def test_robinson_larger_aperture_worse():
    """图锚：大孔（200×30mm，Fig.8）低频 SE 劣于小孔（100×5mm，
    Fig.7）@200MHz。"""
    se_small = robinson_enclosure_se(
        frequency_hz=2.0e8, **_fig67_kwargs())["se_electric_db"][0]
    se_big = robinson_enclosure_se(
        frequency_hz=2.0e8,
        **_fig67_kwargs(aperture_length_m=0.2, aperture_width_m=0.03)
    )["se_electric_db"][0]
    assert se_big < se_small


def test_robinson_te10_cutoff_anchor():
    """原文 "cutoff frequency of 500 MHz"（a=300mm ⇒ c/2a=499.65MHz，
    ±1MHz）。"""
    r = robinson_enclosure_se(
        frequency_hz=2.0e8, **_fig67_kwargs())
    assert r["te10_cutoff_hz"] == pytest.approx(500.0e6, abs=1.0e6)


def test_robinson_circular_mapping_identity():
    """式(11)：圆孔 l=w=√π/2·d_h 等面积方映射——与直给同尺寸缝逐位
    相等（同代码路径，1e-9）。"""
    d_h = 0.01
    side = math.sqrt(math.pi) / 2.0 * d_h
    r_circ = robinson_enclosure_se(
        frequency_hz=1.0e8,
        **_fig67_kwargs(aperture_type=APERTURE_CIRCULAR,
                        hole_diameter_m=d_h))
    r_slot = robinson_enclosure_se(
        frequency_hz=1.0e8,
        **_fig67_kwargs(aperture_length_m=side, aperture_width_m=side))
    assert r_circ["se_electric_db"] == pytest.approx(
        r_slot["se_electric_db"], abs=1e-9)
    assert r_circ["se_magnetic_db"] == pytest.approx(
        r_slot["se_magnetic_db"], abs=1e-9)


def test_robinson_array_scaling_20log_n():
    """式(12)：n 孔串联（×n）——电小孔域 SE 降=20lg(n)（n=2 →
    6.0206dB，实测差 ~0.002dB，门 0.05dB）。薄屏 t=0（小孔+厚壁会触
    厚壁出域守卫：w=2mm、t=1.5mm 时 w_e<0，缝等效闭合）。"""
    kw = _fig67_kwargs(wall_thickness_m=0.0,
                       aperture_length_m=0.01, aperture_width_m=0.002)
    se1 = robinson_enclosure_se(frequency_hz=1.0e8, **kw)["se_electric_db"][0]
    se2 = robinson_enclosure_se(
        frequency_hz=1.0e8, **{**kw, "n_apertures": 2})["se_electric_db"][0]
    assert se1 - se2 == pytest.approx(20.0 * math.log10(2.0), abs=0.05)


def test_robinson_loss_shallows_resonance_dip():
    """ζ 损耗（式(9)(10)）使谐振 dip 变浅（物理方向锚：min SE(ζ>0) >
    min SE(ζ=0)），dip 仍落在 600–800MHz 窗。"""
    se_lossless = _fig67_se_axis()
    se_lossy = _fig67_se_axis(loss_zeta=0.1)
    assert min(se_lossy) > min(se_lossless)


def test_robinson_se_magnetic_low_freq_plateau():
    """S_M 低频平台（链内恒等：f→0 时 i_p→i_p'=v0/2Z0，SE_M→常数）
    + 谐振处 S_M 下陷。"""
    r = robinson_enclosure_se(
        f_axis_hz=[5.0e7, 1.0e8, 2.0e8, 7.0e8], **_fig67_kwargs())
    se_m = r["se_magnetic_db"]
    assert abs(se_m[0] - se_m[1]) <= 1.0
    assert se_m[3] < se_m[2]


def test_robinson_se_matches_independent_recompute():
    """单点全链独立裁判（#118：式(4)-(8) 测试内独立重写，|Δ|≤1e-9 dB）。"""
    f_hz = 2.0e8
    w = 5.0e-3
    t = 1.5e-3
    # 独立链（与内核不同源书写）
    we = w - (5.0 * t / (4.0 * math.pi)) * (
        1.0 + math.log(4.0 * math.pi * w / t))
    k = we / _B
    s = math.sqrt(1.0 - k * k)
    z0s = 120.0 * math.pi ** 2 / math.log(2.0 * (1.0 + s) / (1.0 - s))
    k0 = 2.0 * math.pi * f_hz / C0_M_S
    z_ap = 0.5 * (_L_LA / _A) * 1j * z0s * cmath.tan(k0 * _L_LA / 2.0)
    v1 = z_ap / (ETA0_OHM + z_ap)
    z1 = ETA0_OHM * z_ap / (ETA0_OHM + z_ap)
    guide = cmath.sqrt(1.0 - (C0_M_S / f_hz / (2.0 * _A)) ** 2)
    z_g = ETA0_OHM / guide
    k_g = k0 * guide
    v2 = v1 / (cmath.cos(k_g * _P) + 1j * (z1 / z_g) * cmath.sin(k_g * _P))
    z2 = (z1 + 1j * z_g * cmath.tan(k_g * _P)) / (
        1.0 + 1j * (z1 / z_g) * cmath.tan(k_g * _P))
    z3 = 1j * z_g * cmath.tan(k_g * (_D - _P))
    v_p = v2 * z3 / (z2 + z3)
    i_p = v2 / (z2 + z3)
    se_e_ref = -20.0 * math.log10(abs(2.0 * v_p))
    se_m_ref = -20.0 * math.log10(abs(2.0 * i_p * ETA0_OHM))
    r = robinson_enclosure_se(frequency_hz=f_hz, **_fig67_kwargs())
    assert r["se_electric_db"][0] == pytest.approx(se_e_ref, abs=1e-9)
    assert r["se_magnetic_db"][0] == pytest.approx(se_m_ref, abs=1e-9)


def test_robinson_small_aperture_slope_band():
    """Robinson 腔链电小孔域孔径斜率 ∈(−55,−40) dB/dec（Z_ap∝l²·
    Z0s(w_e/b) 对数缓增 ⇒ 偏离纯 −40；与 Bethe σ_t 律 −60 非同一定义，
    并陈口径见模块 docstring）。薄屏 t=0（w_e=w，隔离孔径缩放本身）。"""
    f_hz = 1.0e8
    dims = [2.0e-3, 4.0e-3, 8.0e-3]  # 缝长十年期 3 点，w=l/50 固定比
    ses = [
        robinson_enclosure_se(
            frequency_hz=f_hz,
            **_fig67_kwargs(wall_thickness_m=0.0,
                            aperture_length_m=la,
                            aperture_width_m=la / 50.0))
        ["se_electric_db"][0]
        for la in dims
    ]
    slope = (ses[2] - ses[0]) / math.log10(dims[2] / dims[0])
    assert -55.0 < slope < -40.0


def test_robinson_output_json_serializable():
    """输出 dict JSON 可序列化（服务层进出契约）。"""
    r = robinson_enclosure_se(
        f_axis_hz=[1.0e8, 2.0e8], **_fig67_kwargs(n_apertures=2))
    text = json.dumps(r, ensure_ascii=False)
    assert "se_electric_db" in text


# ─── 矩形缝波导截止穿透（规格："矩形缝波导截止穿透项"）─────────────────────


def test_slot_cutoff_semantics():
    """f_c=c/(2L) 原文语义：L=0.5m 半波缝谐振 → 恰 300MHz（逐位 c）。"""
    assert slot_cutoff_frequency_hz(0.5) == pytest.approx(
        C0_M_S / (2.0 * 0.5), rel=1e-15)


def test_slot_thickness_se_db_dc_limit_and_known_value():
    """f→0 极限=20lg(e)·π·t/L（独立内联复算，t=L=0.1 → ≈27.2875dB）。"""
    slot_len = 0.1
    t = 0.1
    got = slot_thickness_se_db(1.0, slot_len, t)  # f=1Hz ≈ DC 极限
    dc_limit = (20.0 / math.log(10.0)) * math.pi * t / slot_len
    assert got == pytest.approx(dc_limit, rel=1e-9)


def test_slot_thickness_se_db_frequency_monotonic_and_cutoff_vanish():
    """SE 随 f 单调降；f→f_c⁻ → 0（消失模衰减常数 →0）。"""
    slot_len, t = 0.1, 2.0e-3
    fc = slot_cutoff_frequency_hz(slot_len)
    f1, f2 = 0.3 * fc, 0.6 * fc
    se1 = slot_thickness_se_db(f1, slot_len, t)
    se2 = slot_thickness_se_db(f2, slot_len, t)
    assert se1 > se2 > 0.0
    assert slot_thickness_se_db(0.999 * fc, slot_len, t) < 2.0


def test_slot_thickness_thin_limit_degenerates_to_bethe():
    """t→0 精确退化为薄屏（Bethe 口径，SE→0；t=0 恒等返回 0.0）。"""
    assert slot_thickness_se_db(1.0e6, 0.1, 0.0) == 0.0


def test_slot_thickness_rejects_above_cutoff_and_bad_domain():
    """负例守卫：f≥f_c（高于截止缝透明）、t<0、L≤0、f≤0 显式拒绝。"""
    slot_len = 0.1
    fc = slot_cutoff_frequency_hz(slot_len)
    with pytest.raises(ValueError, match="低于缝截止"):
        slot_thickness_se_db(fc, slot_len, 1.0e-3)
    with pytest.raises(ValueError, match="低于缝截止"):
        slot_thickness_se_db(1.2 * fc, slot_len, 1.0e-3)
    with pytest.raises(ValueError, match="wall_thickness_m"):
        slot_thickness_se_db(1.0e6, slot_len, -1.0)
    with pytest.raises(ValueError, match="slot_length_m"):
        slot_thickness_se_db(1.0e6, 0.0, 1.0e-3)
    with pytest.raises(ValueError, match="frequency_hz"):
        slot_thickness_se_db(0.0, slot_len, 1.0e-3)


# ─── aperture_impedance 与 robinson_enclosure_se 负例守卫 ─────────────────


def test_aperture_impedance_guards():
    """孔缝阻抗域守卫：l>a / w_e≥b / n<1 显式拒绝（缝半波谐振邻域
    tan 给出大而非有限的值，属模型有效域问题不做硬守卫——见模块
    docstring；真正非有限值路径由 isfinite 守卫兜底）。"""
    with pytest.raises(ValueError, match="缝长沿 a 面"):
        aperture_impedance_ohm(1.0e8, 0.4, 2.0e-3, 0.3, 0.12)
    with pytest.raises(ValueError, match="CPS 模数"):
        aperture_impedance_ohm(1.0e8, 0.1, 0.13, 0.3, 0.12)
    with pytest.raises(ValueError, match="n_apertures"):
        aperture_impedance_ohm(1.0e8, 0.1, 2.0e-3, 0.3, 0.12, n_apertures=0)


def test_robinson_enclosure_se_input_guards():
    """全链输入域守卫逐项显式拒绝（二选一/尺寸/p 开区间/类型键）。"""
    base = _fig67_kwargs()
    with pytest.raises(ValueError, match="二选一"):
        robinson_enclosure_se(**base)
    with pytest.raises(ValueError, match="二选一"):
        robinson_enclosure_se(frequency_hz=1.0e8, f_axis_hz=[1.0e8], **base)
    with pytest.raises(ValueError, match="observation_distance_m"):
        robinson_enclosure_se(frequency_hz=1.0e8,
                              **_fig67_kwargs(observation_distance_m=0.0))
    with pytest.raises(ValueError, match="enclosure_depth_m"):
        robinson_enclosure_se(frequency_hz=1.0e8,
                              **_fig67_kwargs(observation_distance_m=0.3))
    with pytest.raises(ValueError, match="缝长沿 a 面"):
        robinson_enclosure_se(
            frequency_hz=1.0e8, **_fig67_kwargs(aperture_length_m=0.5))
    with pytest.raises(ValueError, match=r"CPS 模数|孔宽"):
        robinson_enclosure_se(
            frequency_hz=1.0e8, **_fig67_kwargs(aperture_length_m=0.15,
                                                aperture_width_m=0.13))
    with pytest.raises(ValueError, match="n_apertures"):
        robinson_enclosure_se(frequency_hz=1.0e8,
                              **_fig67_kwargs(n_apertures=0))
    with pytest.raises(ValueError, match="n_apertures"):
        robinson_enclosure_se(frequency_hz=1.0e8,
                              **_fig67_kwargs(n_apertures=2.5))
    with pytest.raises(ValueError, match="loss_zeta"):
        robinson_enclosure_se(frequency_hz=1.0e8,
                              **_fig67_kwargs(loss_zeta=-0.1))
    with pytest.raises(ValueError, match="aperture_type"):
        robinson_enclosure_se(frequency_hz=1.0e8,
                              **_fig67_kwargs(aperture_type="elliptic"))
    with pytest.raises(ValueError, match="z0s_mode"):
        robinson_enclosure_se(frequency_hz=1.0e8,
                              **_fig67_kwargs(z0s_mode="magic"))
    with pytest.raises(ValueError, match="hole_diameter_m"):
        robinson_enclosure_se(
            frequency_hz=1.0e8,
            **_fig67_kwargs(aperture_type=APERTURE_CIRCULAR))
    slot_no_dims = {
        k: v for k, v in
        _fig67_kwargs(aperture_type=APERTURE_SLOT).items()
        if k not in ("aperture_length_m", "aperture_width_m")}
    with pytest.raises(ValueError, match="aperture_length_m"):
        robinson_enclosure_se(frequency_hz=1.0e8, **slot_no_dims)
    with pytest.raises(ValueError, match="缝宽"):
        robinson_enclosure_se(
            frequency_hz=1.0e8,
            **_fig67_kwargs(aperture_length_m=0.01,
                            aperture_width_m=0.02))
    with pytest.raises(ValueError, match="frequency_hz"):
        robinson_enclosure_se(frequency_hz=-1.0, **base)


def test_robinson_thick_wall_guard_via_chain():
    """全链穿透厚壁出域（w=1mm、t=10mm → w_e≤0）显式拒绝。"""
    with pytest.raises(ValueError, match="厚壁修正出域"):
        robinson_enclosure_se(
            frequency_hz=1.0e8,
            enclosure_width_m=0.3,
            enclosure_height_m=0.12,
            enclosure_depth_m=0.3,
            wall_thickness_m=1.0e-2,
            aperture_length_m=0.05,
            aperture_width_m=1.0e-3,
            observation_distance_m=0.15)
