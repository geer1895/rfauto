"""EM-1 近场屏蔽效能单测（电/磁偶极源波阻抗修正闭式族，2026-10-02）。

锚树口径（#118 教训：锚值独立复算/独立公式，不赌推导）：
- 远场退化一致性：r≥λ/2π 时近场口径钳位 Z_w=η0，SE 逐式与 QW-11
  Schelkunoff 平面波（calc_families/shield.shielding_effectiveness）
  相等（跨模块互证锚，实测 |Δ|≤1e-9 dB，门 ≤0.1 dB）。
- Z_w 定义：|Z_wh|=ω·μ0·r、|Z_we|=η0·λ/(2πr)（独立闭式直算）、
  对偶积 |Z_we|·|Z_wh|≡η0²、r=λ/2π 处两支连续取 η0。
- Ott dB 简化式（独立来源裁判）：R_p≈168−10lg(f μr/σr)、
  R_h≈14.6+10lg(f r² σr/μr)、R_e≈322+10lg(σr/(μr f³ r²))（页码
  UNVERIFIED，数值一致性钉在各自有效域内）。
- Ott 铜箔 0.1mm@1MHz 典型带（round17 EM-1 验收锚）。
- A+R+B ≡ −20lg|S21_ABCD| 恒等式在广义 Z_w 下精确成立
  （ABCD 独立裁判路，Z_w 参数化推广 test_qw10_qw11._se_abcd_independent）。
"""
from __future__ import annotations

import cmath
import math

import pytest

from rfauto.core.calculators import shielding_effectiveness
from rfauto.core.near_field_se import (
    ETA0_OHM,
    MU0_H_M,
    SOURCE_ELECTRIC_DIPOLE,
    SOURCE_MAGNETIC_DIPOLE,
    SOURCE_PLANE_WAVE,
    absorption_loss_db,
    multiple_reflection_db,
    near_field_se,
    reflection_loss_db,
    skin_depth_m,
    source_wave_impedance_ohm,
)

_SIGMA_CU = 5.8e7
_T_01MM = 1.0e-4


def _zs_copper(f_hz: float, sigma: float = _SIGMA_CU,
               mu_r: float = 1.0) -> complex:
    """独立复算屏蔽体表面阻抗 Z_s=√(jωμ/σ)（与内核同式、测试内独立书写）。"""
    return cmath.sqrt(1j * 2.0 * math.pi * f_hz * MU0_H_M * mu_r / sigma)


def _se_abcd_general(f_hz: float, t_m: float, sigma: float, mu_r: float,
                     z_w: float) -> float:
    """独立裁判路：屏蔽体有耗 TL 段 ABCD 嵌入广义 Z_w 系统的 −20lg|S21|。

    与内核 A+R+B 分解不同源（#118）：Z_w 由外部闭式给定后，本函数
    只验证三段分解的恒等性，不依赖内核任何函数。
    """
    mu = MU0_H_M * mu_r
    omega = 2.0 * math.pi * f_hz
    delta = math.sqrt(2.0 / (omega * mu * sigma))
    gamma = (1.0 + 1j) / delta
    z_s = cmath.sqrt(1j * omega * mu / sigma)
    s21 = 2.0 / (2.0 * cmath.cosh(gamma * t_m)
                 + (z_s / z_w + z_w / z_s) * cmath.sinh(gamma * t_m))
    return -20.0 * math.log10(abs(s21))


# ─── 远场退化一致性（跨模块互证锚：vs QW-11 Schelkunoff 平面波）──────────────

@pytest.mark.parametrize("f_hz", [1.0e5, 1.0e6, 1.0e7])
@pytest.mark.parametrize(
    "source", [SOURCE_ELECTRIC_DIPOLE, SOURCE_MAGNETIC_DIPOLE,
               SOURCE_PLANE_WAVE])
def test_far_field_degeneracy_vs_qw11(f_hz, source):
    """r=10·λ/2π（深远场）：近场口径 SE 逐段与 QW-11 相等（门 ≤0.1 dB）。"""
    r_far = 10.0 * (299792458.0 / f_hz) / (2.0 * math.pi)
    qw = shielding_effectiveness(
        frequency_hz=f_hz, thickness_m=5.0e-4,
        conductivity_s_per_m=_SIGMA_CU)
    mine = near_field_se(
        frequency_hz=f_hz, thickness_m=5.0e-4,
        conductivity_s_per_m=_SIGMA_CU, source=source, distance_m=r_far)
    for key in ("se_absorption_db", "se_reflection_db", "se_multiple_db",
                "se_total_db"):
        assert abs(mine[key][0] - qw[key][0]) <= 1e-6, (key, source, f_hz)


def test_far_field_degeneracy_meets_0p1db_gate():
    """任务书锚显式化：跨模块对拍 ≤0.1 dB（实测 1e-9 量级，余量充分）。"""
    f_hz = 1.0e6
    r_far = 10.0 * (299792458.0 / f_hz) / (2.0 * math.pi)
    qw = shielding_effectiveness(
        frequency_hz=f_hz, thickness_m=_T_01MM,
        conductivity_s_per_m=_SIGMA_CU)
    mine = near_field_se(
        frequency_hz=f_hz, thickness_m=_T_01MM,
        conductivity_s_per_m=_SIGMA_CU, source=SOURCE_MAGNETIC_DIPOLE,
        distance_m=r_far)
    assert abs(mine["se_total_db"][0] - qw["se_total_db"][0]) <= 0.1


# ─── 源波阻抗定义（独立闭式 + 对偶积 + 边界连续性）───────────────────────────

def test_wave_impedance_closed_forms_and_duality():
    """|Z_wh|=ωμ0r、|Z_we|=η0λ/(2πr) 独立闭式直算 + 对偶积 ≡ η0²。"""
    f_hz, r_m = 1.0e6, 0.1
    z_wh = source_wave_impedance_ohm(f_hz, SOURCE_MAGNETIC_DIPOLE, r_m)
    z_we = source_wave_impedance_ohm(f_hz, SOURCE_ELECTRIC_DIPOLE, r_m)
    z_wh_ref = 2.0 * math.pi * f_hz * MU0_H_M * r_m  # ω·μ0·r（独立物理式）
    z_we_ref = ETA0_OHM * (299792458.0 / f_hz) / (2.0 * math.pi * r_m)
    # 容差下限：ETA0_OHM 字面值 12 位截断 vs μ0·c 实际 rel 5.5e-10（实测）
    assert z_wh == pytest.approx(z_wh_ref, rel=1e-8)
    assert z_we == pytest.approx(z_we_ref, rel=1e-8)
    assert z_wh * z_we == pytest.approx(ETA0_OHM ** 2, rel=1e-7)
    # 手算量级锚：1 MHz/r=0.1 m 磁场源 0.79 Ω ≪ η0；电场源 ~1.8e5 Ω ≫ η0
    assert 0.7 < z_wh < 0.9
    assert 1.5e5 < z_we < 2.0e5


def test_wave_impedance_boundary_continuous_at_kr1():
    """r=λ/2π 处两支都精确取 η0（拼接连续），跨界 SE 无跳变。"""
    f_hz = 1.0e6
    lam = 299792458.0 / f_hz
    r0 = lam / (2.0 * math.pi)
    for source in (SOURCE_ELECTRIC_DIPOLE, SOURCE_MAGNETIC_DIPOLE):
        z_at = source_wave_impedance_ohm(f_hz, source, r0)
        assert z_at == pytest.approx(ETA0_OHM, rel=1e-9)
        se_lo = near_field_se(frequency_hz=f_hz, thickness_m=_T_01MM,
                              conductivity_s_per_m=_SIGMA_CU, source=source,
                              distance_m=r0 * (1.0 - 1.0e-9))
        se_hi = near_field_se(frequency_hz=f_hz, thickness_m=_T_01MM,
                              conductivity_s_per_m=_SIGMA_CU, source=source,
                              distance_m=r0 * (1.0 + 1.0e-9))
        assert abs(se_lo["se_total_db"][0]
                   - se_hi["se_total_db"][0]) <= 1.0e-5


def test_wave_impedance_plane_wave_ignores_distance():
    """plane_wave 口径 distance 不参与（省略与给值结果一致）。"""
    base = dict(thickness_m=_T_01MM, conductivity_s_per_m=_SIGMA_CU)
    no_r = near_field_se(frequency_hz=1.0e6, source=SOURCE_PLANE_WAVE, **base)
    with_r = near_field_se(frequency_hz=1.0e6, source=SOURCE_PLANE_WAVE,
                           distance_m=123.0, **base)
    for key in ("skin_depth_m", "wave_impedance_ohm", "se_absorption_db",
                "se_reflection_db", "se_multiple_db", "se_total_db"):
        assert no_r[key] == with_r[key]


# ─── Ott 铜箔 0.1mm@1MHz 典型带（round17 EM-1 验收锚）────────────────────────

def test_ott_copper_foil_01mm_1mhz_typical_band():
    """铜箔 0.1mm@1MHz（r=0.1m）：A/R 手算锚 + Ott dB 简化式独立裁判。

    独立复算：δ=1/√(πfμσ)=66.085 µm → A=8.686·t/δ=13.143 dB；
    |Z_s|=3.6896e-4∠45° Ω；Z_wh=ωμ0r=0.78957 Ω；Z_we=1.7975e5 Ω。
    """
    f_hz, r_m = 1.0e6, 0.1
    delta_ref = 1.0 / math.sqrt(math.pi * f_hz * MU0_H_M * _SIGMA_CU)
    assert skin_depth_m(f_hz, _SIGMA_CU) == pytest.approx(delta_ref, rel=1e-12)
    assert 65.0e-6 <= delta_ref <= 67.0e-6
    a_ref = (20.0 / math.log(10.0)) * _T_01MM / delta_ref

    res_h = near_field_se(frequency_hz=f_hz, thickness_m=_T_01MM,
                          conductivity_s_per_m=_SIGMA_CU,
                          source=SOURCE_MAGNETIC_DIPOLE, distance_m=r_m)
    res_e = near_field_se(frequency_hz=f_hz, thickness_m=_T_01MM,
                          conductivity_s_per_m=_SIGMA_CU,
                          source=SOURCE_ELECTRIC_DIPOLE, distance_m=r_m)
    res_p = near_field_se(frequency_hz=f_hz, thickness_m=_T_01MM,
                          conductivity_s_per_m=_SIGMA_CU,
                          source=SOURCE_PLANE_WAVE)
    for res in (res_h, res_e, res_p):
        assert res["se_absorption_db"][0] == pytest.approx(a_ref, abs=0.05)
        assert res["se_absorption_db"][0] == pytest.approx(13.143, abs=0.05)

    # Ott dB 简化式（独立来源，页码 UNVERIFIED，有效域内数值一致性）
    z_wh = 2.0 * math.pi * f_hz * MU0_H_M * r_m
    z_s_abs = abs(_zs_copper(f_hz))
    r_h_simpl = 20.0 * math.log10(z_wh / (4.0 * z_s_abs))
    r_e_simpl = 20.0 * math.log10(
        ETA0_OHM * (299792458.0 / f_hz) / (2.0 * math.pi * r_m)
        / (4.0 * z_s_abs))
    assert res_h["se_reflection_db"][0] == pytest.approx(r_h_simpl, abs=0.05)
    assert res_e["se_reflection_db"][0] == pytest.approx(r_e_simpl, abs=0.05)
    assert res_h["se_reflection_db"][0] == pytest.approx(
        14.6 + 10.0 * math.log10(f_hz * r_m ** 2), abs=0.1)
    assert res_e["se_reflection_db"][0] == pytest.approx(
        322.0 + 10.0 * math.log10(1.0 / (f_hz ** 3 * r_m ** 2)), abs=0.5)
    assert res_p["se_reflection_db"][0] == pytest.approx(
        168.0 - 10.0 * math.log10(f_hz), abs=0.2)  # QW-11 锚 108.1398
    assert res_p["se_reflection_db"][0] == pytest.approx(108.1398, abs=0.05)

    # 近场反射序：R_e > R_p > R_h（高阻场最好、低阻场最恶劣，经典 EMC 序）
    r_e = res_e["se_reflection_db"][0]
    r_p = res_p["se_reflection_db"][0]
    r_h = res_h["se_reflection_db"][0]
    assert r_e > r_p > r_h

    # 典型带验收（spec：Ott 铜箔 0.1mm@1MHz 典型带；实测 SE_h≈68.1、
    # SE_p≈121.7、SE_e≈175.3 dB）
    assert 55.0 <= res_h["se_total_db"][0] <= 90.0
    assert 100.0 <= res_p["se_total_db"][0] <= 140.0
    assert res_e["se_total_db"][0] >= 140.0


# ─── 三段原语锚（A/B 物理极限）───────────────────────────────────────────────

def test_absorption_zero_thickness_exact_zero():
    """A 项 t=0 → 精确 0.0（物理恒等；t<0 显式拒绝）。"""
    assert absorption_loss_db(1.0e6, 0.0, _SIGMA_CU) == 0.0
    with pytest.raises(ValueError, match="≥0"):
        absorption_loss_db(1.0e6, -1.0e-3, _SIGMA_CU)


def test_absorption_one_skin_depth_and_sqrt_f_scaling():
    """t=δ → 8.686 dB（20/ln10）；A ∝ √f（良导体标度恒等）。"""
    f_hz = 1.0e6
    delta = skin_depth_m(f_hz, _SIGMA_CU)
    assert absorption_loss_db(f_hz, delta, _SIGMA_CU) == pytest.approx(
        20.0 / math.log(10.0), rel=1e-12)
    a_1g = absorption_loss_db(1.0e9, _T_01MM, _SIGMA_CU)
    a_1m = absorption_loss_db(1.0e6, _T_01MM, _SIGMA_CU)
    assert a_1g / a_1m == pytest.approx(math.sqrt(1.0e9 / 1.0e6), rel=1e-9)
    assert a_1g > a_1m > 0.0  # 良导体 f→∞ 时 A→∞ 的确定性标度口径


def test_multiple_reflection_limits_thin_negative_thick_zero():
    """薄屏蔽（t=0.01δ）B 为大负贡献；厚屏蔽（t=10δ）B→0（≤1e-6 dB）。"""
    f_hz = 1.0e6
    delta = skin_depth_m(f_hz, _SIGMA_CU)
    b_thin = multiple_reflection_db(f_hz, 0.01 * delta, SOURCE_PLANE_WAVE,
                                    conductivity_s_per_m=_SIGMA_CU)
    b_thick = multiple_reflection_db(f_hz, 10.0 * delta, SOURCE_PLANE_WAVE,
                                     conductivity_s_per_m=_SIGMA_CU)
    assert b_thin <= -20.0
    assert abs(b_thick) <= 1.0e-6


def test_thin_sheet_limit_independent_rs_formula():
    """深薄屏极限（t/δ≈1.5e-5）：SE ≈ 20lg(1+Z_w·σ·t/2)（独立经典薄屏式）。

    独立物理锚：表面电阻 Rs=1/(σt) 薄屏的传输系数 1/(1+Z_w/(2Rs))
    （低频薄屏极限闭式，与 TL 模型不同源）。1 nm 铜箔@1 MHz 独立
    预算：plane 21.529 / magnetic 0.197 / electric 74.343 dB。
    口径注记：SE(t→0) 趋零由 Γ²·2γt 项支配（需 t≪|1−Γ²|·δ/(2√2)
    ≈9e-11 m），1e-9 m 处薄屏 Rs 极限先于零厚极限到达——预期值
    用薄屏式而非 0（预期写 0 是物理错误，实测 1nm 铜箔确有
    ~21.5 dB 平面波 SE，与 Rs=17.24 Ω/sq 口径互证）。
    """
    f_hz, t_m, r_m = 1.0e6, 1.0e-9, 0.1
    thin_ref = {"plane": 21.529, "magnetic": 0.197, "electric": 74.343}
    cases = (
        (SOURCE_PLANE_WAVE, None, "plane"),
        (SOURCE_MAGNETIC_DIPOLE, r_m, "magnetic"),
        (SOURCE_ELECTRIC_DIPOLE, r_m, "electric"),
    )
    for source, r_used, name in cases:
        z_w = source_wave_impedance_ohm(f_hz, source, r_used)
        expected = 20.0 * math.log10(1.0 + z_w * _SIGMA_CU * t_m / 2.0)
        res = near_field_se(frequency_hz=f_hz, thickness_m=t_m,
                            conductivity_s_per_m=_SIGMA_CU, source=source,
                            distance_m=r_used)
        assert res["se_total_db"][0] == pytest.approx(expected, abs=0.05), name
        assert res["se_total_db"][0] == pytest.approx(
            thin_ref[name], abs=0.05), name


# ─── ABCD 独立裁判路（广义 Z_w 恒等式，#118 纪律）────────────────────────────

@pytest.mark.parametrize(
    "f_hz,t_m,sigma,mu_r,source,r_m",
    [
        (1.0e6, 1.0e-4, 5.8e7, 1.0, SOURCE_MAGNETIC_DIPOLE, 0.1),
        (1.0e6, 1.0e-4, 5.8e7, 1.0, SOURCE_ELECTRIC_DIPOLE, 0.1),
        (1.0e5, 2.0e-4, 5.8e7, 1.0, SOURCE_MAGNETIC_DIPOLE, 0.01),
        (1.0e7, 5.0e-4, 1.0e7, 200.0, SOURCE_MAGNETIC_DIPOLE, 0.05),
        (1.0e6, 1.0e-3, 5.8e7, 1.0, SOURCE_PLANE_WAVE, None),
    ],
)
def test_identity_abcd_exact_generalized_zw(f_hz, t_m, sigma, mu_r,
                                            source, r_m):
    """SE=A+R+B ≡ −20lg|S21_ABCD|（Z_w 参数化推广 QW-11 恒等式锚）。"""
    z_w = source_wave_impedance_ohm(f_hz, source, r_m)
    res = near_field_se(frequency_hz=f_hz, thickness_m=t_m,
                        conductivity_s_per_m=sigma, mu_r=mu_r, source=source,
                        distance_m=r_m)
    se_tl = _se_abcd_general(f_hz, t_m, sigma, mu_r, z_w)
    assert res["se_total_db"][0] == pytest.approx(se_tl, abs=1e-8)


# ─── 近场方向性锚（r 扫描单调性）────────────────────────────────────────────

def test_near_field_directional_monotonicity_in_distance():
    """近场内（r<λ/2π）：R_h 随 r 增、R_e 随 r 减、R_p 常数（EMC 方向序）。"""
    f_hz = 1.0e6
    r_near = [0.01, 0.05, 0.1, 0.2, 0.5]  # 全部 < λ/2π ≈ 47.7 m
    r_h = [reflection_loss_db(f_hz, SOURCE_MAGNETIC_DIPOLE, r,
                              conductivity_s_per_m=_SIGMA_CU)
           for r in r_near]
    r_e = [reflection_loss_db(f_hz, SOURCE_ELECTRIC_DIPOLE, r,
                              conductivity_s_per_m=_SIGMA_CU)
           for r in r_near]
    assert all(r_h[i] < r_h[i + 1] for i in range(len(r_h) - 1))
    assert all(r_e[i] > r_e[i + 1] for i in range(len(r_e) - 1))
    r_p0 = reflection_loss_db(f_hz, SOURCE_PLANE_WAVE,
                              conductivity_s_per_m=_SIGMA_CU)
    assert all(abs(rv - r_p0) <= 1e-12 for rv in
               [reflection_loss_db(f_hz, SOURCE_PLANE_WAVE, r,
                                   conductivity_s_per_m=_SIGMA_CU)
                for r in r_near])


# ─── 材料表路径与 f_axis ─────────────────────────────────────────────────────

def test_material_table_path_and_steel_absorption_anchor():
    """材料表复用 QW-11 单源表；钢 μr=100 的 A 手算锚 54.57 dB。"""
    res = near_field_se(frequency_hz=1.0e6, thickness_m=_T_01MM,
                        material="steel_low_carbon",
                        source=SOURCE_MAGNETIC_DIPOLE, distance_m=0.1)
    assert res["material"] == "steel_low_carbon"
    assert res["mu_r"] == 100.0
    assert res["conductivity_s_per_m"] == 1.0e7
    delta_steel = 1.0 / math.sqrt(
        math.pi * 1.0e6 * MU0_H_M * 100.0 * 1.0e7)
    assert res["se_absorption_db"][0] == pytest.approx(
        (20.0 / math.log(10.0)) * _T_01MM / delta_steel, abs=0.05)
    with pytest.raises(ValueError, match="未知屏蔽材料"):
        near_field_se(frequency_hz=1.0e6, thickness_m=_T_01MM,
                      material="unobtainium", source=SOURCE_PLANE_WAVE)


def test_f_axis_consistency_with_single_point():
    """f_axis 数组路径与单点调用逐元素一致（列表长度/数值）。"""
    f_axis = [1.0e5, 1.0e6, 1.0e7]
    axis_out = near_field_se(
        f_axis_hz=f_axis, thickness_m=_T_01MM,
        conductivity_s_per_m=_SIGMA_CU, source=SOURCE_MAGNETIC_DIPOLE,
        distance_m=0.1)
    assert len(axis_out["se_total_db"]) == 3
    for i, f_hz in enumerate(f_axis):
        single = near_field_se(
            frequency_hz=f_hz, thickness_m=_T_01MM,
            conductivity_s_per_m=_SIGMA_CU, source=SOURCE_MAGNETIC_DIPOLE,
            distance_m=0.1)
        assert axis_out["se_total_db"][i] == single["se_total_db"][0]
        assert axis_out["se_reflection_db"][i] == single["se_reflection_db"][0]


# ─── 负例守卫（全部显式拒绝）────────────────────────────────────────────────

@pytest.mark.parametrize(
    "kwargs,match",
    [
        (dict(thickness_m=0.0, conductivity_s_per_m=_SIGMA_CU,
              frequency_hz=1.0e6), "必须 >0"),
        (dict(thickness_m=-1.0e-3, conductivity_s_per_m=_SIGMA_CU,
              frequency_hz=1.0e6), "必须 >0"),
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=0.0,
              frequency_hz=1.0e6), "σ=0"),
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=-1.0,
              frequency_hz=1.0e6), "必须 >0"),
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=_SIGMA_CU,
              frequency_hz=0.0), "f=0 显式拒绝"),
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=_SIGMA_CU,
              frequency_hz=-1.0), "必须 >0"),
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=_SIGMA_CU,
              frequency_hz=1.0e6, mu_r=0.0), "mu_r 必须 >0"),
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=_SIGMA_CU,
              frequency_hz=1.0e6), "distance_m 必读"),
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=_SIGMA_CU,
              frequency_hz=1.0e6, distance_m=0.0), "distance_m 必须 >0"),
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=_SIGMA_CU,
              frequency_hz=1.0e6, distance_m=-0.1), "distance_m 必须 >0"),
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=_SIGMA_CU,
              frequency_hz=1.0e6, distance_m=0.1, source="dipole"), "未知源口径"),
        (dict(thickness_m=_T_01MM, frequency_hz=1.0e6), "二选一"),
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=_SIGMA_CU,
              material="copper", frequency_hz=1.0e6,
              source=SOURCE_PLANE_WAVE), None),  # 直给优先合法
        (dict(thickness_m=_T_01MM, conductivity_s_per_m=_SIGMA_CU,
              frequency_hz=1.0e6, f_axis_hz=[1.0e6]), "二选一"),
    ],
)
def test_guards_explicit(kwargs, match):
    """域守卫：t≤0/σ≤0/f≤0/μr≤0/r 缺失或≤0/源键未知/二选一违例显式报错。"""
    params = dict(source=SOURCE_MAGNETIC_DIPOLE)
    params.update(kwargs)
    if match is None:
        out = near_field_se(**params)
        assert out["se_total_db"][0] > 0.0
        return
    with pytest.raises(ValueError, match=match):
        near_field_se(**params)


def test_bool_rejection():
    """bool 入参显式拒收（float(True)=1.0 静默污染防护，df7+⑯ 同款）。"""
    with pytest.raises(ValueError, match="不接受 bool"):
        near_field_se(frequency_hz=1.0e6, thickness_m=True,
                      conductivity_s_per_m=_SIGMA_CU,
                      source=SOURCE_PLANE_WAVE)
    with pytest.raises(ValueError, match="不接受 bool"):
        near_field_se(frequency_hz=True, thickness_m=_T_01MM,
                      conductivity_s_per_m=_SIGMA_CU,
                      source=SOURCE_PLANE_WAVE)
