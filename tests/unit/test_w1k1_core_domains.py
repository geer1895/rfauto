"""架构批 W1-K1 席锚树：内核第五梯队批 1 七键四域（L 节匹配提升核+
矩形波导 TE10 衰减/功率容量+TDR 测量规划族+近/远场区界提升核）。

数值断言口径（#118 锚先独立实测再写死——测试内表达式路径独立于键内实现：
原始构造/常数内联、不消费模块中间量；L 节回代用**独立 ABCD 矩阵级联**与
实现内递归阻抗路径不同源；#122 惯例/UNVERIFIED 如实标注不凑绿）：

- L 节匹配（l_section_match）：①名义 50→100Ω@1GHz 低通档手算逐位——
  Q=√(100/50−1)=1、|X_s|=Q·Rs=50Ω→L=7.957747nH、|X_p|=Rl/Q=100Ω→
  C=1.591549pF（Pozar §5.1 恒等式）；②f0 共轭匹配独立 ABCD 矩阵级联回代
  Z_in=Rs（升/降阻×高/低通 6 档全扫）；③高/低通对偶恒等（串臂电抗模与
  并臂电纳模跨响应型逐位相等，元件 L↔C 对换）；④R_s=R_L→Q=0 bypass
  退化恒等；⑤Q 随阻抗比单调（√(ratio−1) 独立算术）。
- 矩形波导 TE10（wg_te10_attenuation/wg_te10_power_capacity）：①WR-90
  @10GHz 铜档手算逐位（fc=c0/2a=6.557140GHz、Rs=26.0895mΩ、
  α_c=Rs/(ηβk)·(2kc²/a+k²/b)≈0.10839dB/m 文献表值 0.108~0.11dB/m 量级、
  P_max=(ab/4η)E_br²√(1−(fc/f)²)≈1.0473MW 文献 ~1MW 量级）；②σ×4→α_c×½
  （Rs∝σ^(−1/2)）；③材料档与显式电导率同值恒等；④b 翻倍 P_max 翻倍
  （线性恒等）+f→fc⁺ P→0 连续性+P 随 f 单调；⑤截止以下/坏材料档/零
  E_br 显式拒绝。
- TDR 测量规划族：①真空 εeff=1 → d=c0·t/2 恒等（t=10ns→1.498962m）、
  εeff=4 → 距离减半恒等；②分辨率 ∝ t_rise 线性恒等（30ps/εeff=2.2 →
  3.0318mm 数值锤）；③ETS 乘法恒等 f_eq·Δt_step=1（1ps 步→1e12Hz）+
  时窗/耗时规划恒等；④速度通道二选一/超光速/εeff<1/模式越域显式拒绝。
- 近/远场区界（far_field_region）：①Balanis 数值锚 D=0.5m@10GHz →
  d_F=2D²/λ=16.6782m 逐位；②π/8 相位判据独立几何路径 R=πD²/(4λ·π/8)
  与 2D²/λ 闭式互证（两条推导路径独立）；③λ/2π 电小天线档 10GHz 数值锤
  +区界分类三态+边界等号语义；④D<λ/10.406 区界排序失效域显式拒绝。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.calc_families.antenna_regions import far_field_region
from rfauto.core.calc_families.matching_network import l_section_match
from rfauto.core.calc_families.tdr_measurement import (
    tdr_ets_equivalent_time,
    tdr_fault_location,
    tdr_resolution,
)
from rfauto.core.calc_families.wg_fundamental import (
    wg_te10_attenuation,
    wg_te10_power_capacity,
)

_C0 = 299792458.0  # 原始 SI 定义值（不消费模块常量——#118）
_MU0 = 1.25663706212e-6  # CODATA 常数内联（非模块中间量）
_EPS0 = 8.8541878128e-12
_ETA0 = math.sqrt(_MU0 / _EPS0)
_DB_PER_NP = 8.685889638065035
_OMEGA_1GHZ = 2.0 * math.pi * 1e9


# ─── l_section_match（匹配域）────────────────────────────────────────────────

def test_l_section_nominal_50_to_100_low_pass_hand_anchor():
    """名义 50→100Ω@1GHz 低通档：Q=1、X_s=50Ω、X_p=100Ω 手算逐位。"""
    res = l_section_match(50.0, 100.0, 1.0)
    assert res["q"] == pytest.approx(math.sqrt(100.0 / 50.0 - 1.0),
                                     rel=1e-15)
    assert res["bandwidth_frac"] == pytest.approx(1.0, rel=1e-15)
    assert res["shunt_side"] == "load"
    # 元件表按负载端→源端：先并 C（跨负载 100Ω 侧）后串 L（源 50Ω 臂）
    kinds = [(e["role"], e["kind"]) for e in res["elements"]]
    assert kinds == [("shunt", "C"), ("series", "L")]
    c_shunt = res["elements"][0]["value"]
    l_series = res["elements"][1]["value"]
    # 独立算术：|X_p|=Rl/Q=100Ω → C=1/(ω·100)；|X_s|=Q·Rs=50Ω → L=50/ω
    assert c_shunt == pytest.approx(1.0 / (_OMEGA_1GHZ * 100.0), rel=1e-15)
    assert l_series == pytest.approx(50.0 / _OMEGA_1GHZ, rel=1e-15)
    assert res["elements"][0]["value_pf"] == pytest.approx(1.591549430918953,
                                                           rel=1e-9)
    assert res["elements"][1]["value_nh"] == pytest.approx(7.957747154594767,
                                                           rel=1e-9)
    # f0 回代（实现内递归路径）：Z_in=50+j·0；理想构造解 |Γ| 浮点下为 0
    # → RL 按"回损无穷大记 null"惯例（与 vswr_convert 口径一致）
    assert res["zin_f0_re_ohm"] == pytest.approx(50.0, rel=1e-9)
    assert abs(res["zin_f0_im_ohm"]) < 1e-6
    assert res["match_residual_gamma_mag_f0"] < 1e-9
    assert (res["return_loss_db_f0"] is None
            or res["return_loss_db_f0"] > 120.0)


def _abcd_zin_ohm(z_source: float, z_load: float, f0_ghz: float,
                  response: str) -> complex:
    """独立 ABCD 矩阵级联回代（与实现内递归阻抗路径不同源——#118）。

    元件表为负载端→源端；自源端看入的网络级联序=反向（源→负载），
    Z_in=(A·Z_L+B)/(C·Z_L+D)。
    """
    res = l_section_match(z_source, z_load, f0_ghz, response)
    omega = 2.0 * math.pi * f0_ghz * 1e9
    mat = [[1.0 + 0j, 0j], [0j, 1.0 + 0j]]

    def _mul(m1, m2):
        return [[sum(m1[i][k] * m2[k][j] for k in range(2))
                 for j in range(2)] for i in range(2)]

    for element in reversed(res["elements"]):
        z_el = (1j * omega * element["value"] if element["kind"] == "L"
                else 1.0 / (1j * omega * element["value"]))
        m = ([[1.0 + 0j, z_el], [0j, 1.0 + 0j]] if element["role"] == "series"
             else [[1.0 + 0j, 0j], [1.0 / z_el, 1.0 + 0j]])
        mat = _mul(mat, m)
    a, b, c, d = mat[0][0], mat[0][1], mat[1][0], mat[1][1]
    return (a * z_load + b) / (c * z_load + d)


@pytest.mark.parametrize("z_source,z_load,response", [
    (50.0, 100.0, "low_pass"),
    (50.0, 100.0, "high_pass"),
    (100.0, 50.0, "low_pass"),
    (100.0, 50.0, "high_pass"),
    (50.0, 200.0, "low_pass"),
    (75.0, 300.0, "high_pass"),
])
def test_l_section_abcd_roundtrip_independent(z_source, z_load, response):
    """f0 共轭匹配独立 ABCD 矩阵级联回代：Z_in=R_s（6 档全扫）。"""
    zin = _abcd_zin_ohm(z_source, z_load, 1.0, response)
    assert zin.real == pytest.approx(z_source, rel=1e-9)
    assert abs(zin.imag) < 1e-6 * z_source
    # 键面 side 标注：并联支路恒跨大电阻侧
    res = l_section_match(z_source, z_load, 1.0, response)
    expect_side = "load" if z_load > z_source else "source"
    assert res["shunt_side"] == expect_side
    assert all(e["side"] is not None for e in res["elements"])


def test_l_section_hp_lp_dual_identity():
    """高/低通对偶恒等：串臂电抗模与并臂电纳模跨响应型逐位相等。"""
    lp = l_section_match(50.0, 100.0, 1.0, "low_pass")
    hp = l_section_match(50.0, 100.0, 1.0, "high_pass")
    omega = _OMEGA_1GHZ

    def _x_mag(el):
        return (omega * el["value"] if el["kind"] == "L"
                else 1.0 / (omega * el["value"]))

    lp_by_role = {e["role"]: e for e in lp["elements"]}
    hp_by_role = {e["role"]: e for e in hp["elements"]}
    for role in ("series", "shunt"):
        assert _x_mag(lp_by_role[role]) == pytest.approx(
            _x_mag(hp_by_role[role]), rel=1e-15)
    # 元件种类 L↔C 对换（低通串 L 并 C；高通串 C 并 L）
    assert (lp_by_role["series"]["kind"], lp_by_role["shunt"]["kind"]) == (
        "L", "C")
    assert (hp_by_role["series"]["kind"], hp_by_role["shunt"]["kind"]) == (
        "C", "L")


def test_l_section_bypass_and_q_monotone():
    """R_s=R_L→Q=0 bypass 退化恒等；Q 随阻抗比 √(ratio−1) 单调。"""
    res = l_section_match(50.0, 50.0, 1.0)
    assert res["q"] == 0.0
    assert res["elements"] == []
    assert res["bandwidth_frac"] is None
    assert res["shunt_side"] is None
    assert res["zin_f0_re_ohm"] == pytest.approx(50.0, rel=1e-15)
    assert res["return_loss_db_f0"] is None
    # Q 独立算术 + 单调
    for ratio in (2.0, 4.0, 10.0, 1.5):
        q = l_section_match(50.0, 50.0 * ratio, 1.0)["q"]
        assert q == pytest.approx(math.sqrt(ratio - 1.0), rel=1e-15)
    assert (l_section_match(50.0, 200.0, 1.0)["q"]
            > l_section_match(50.0, 100.0, 1.0)["q"])


def test_l_section_domain_guards():
    """响应型越域/非法阻抗/bool 污染显式拒绝（JSON 信封安全前置）。"""
    with pytest.raises(ValueError, match="response"):
        l_section_match(50.0, 100.0, 1.0, "bandpass")
    with pytest.raises(ValueError):
        l_section_match(0.0, 100.0, 1.0)
    with pytest.raises(ValueError):
        l_section_match(50.0, -100.0, 1.0)
    with pytest.raises(ValueError):
        l_section_match(50.0, 100.0, 0.0)
    with pytest.raises(ValueError, match="不接受 bool"):
        l_section_match(True, 100.0, 1.0)
    with pytest.raises(ValueError, match="不接受 bool"):
        l_section_match(50.0, 100.0, True)
    with pytest.raises(ValueError):
        l_section_match(50.0, float("nan"), 1.0)


# ─── wg_te10_attenuation / wg_te10_power_capacity（波导域）───────────────────

# WR-90 手算公共量（独立算术，常数内联）
_A_M = 0.02286
_B_M = 0.01016
_F_HZ = 10e9
_SIGMA_CU = 5.8e7
_FC_HZ = _C0 / (2.0 * _A_M)
_K = 2.0 * math.pi * _F_HZ / _C0
_BETA = _K * math.sqrt(1.0 - (_FC_HZ / _F_HZ) ** 2)
_RS = math.sqrt(math.pi * _F_HZ * _MU0 / _SIGMA_CU)
_KC = math.pi / _A_M
_AC_CU = _RS / (_ETA0 * _BETA * _K) * (2.0 * _KC * _KC / _A_M
                                       + _K * _K / _B_M)


def test_wg_te10_attenuation_wr90_hand_anchor():
    """WR-90@10GHz 铜档：fc/Rs/α_c 手算逐位 + 文献表值量级锤。"""
    res = wg_te10_attenuation(22.86, 10.16, 10.0)
    # 键出账按 repo 惯例 round（fc 9 位/β·α 12 位）——容差与出账精度对齐
    assert res["fc_ghz"] == pytest.approx(_FC_HZ / 1e9, rel=1e-9)
    # 文献锤：WR-90 TE10 截止 6.5571 GHz（EIA 表经典值）
    assert res["fc_ghz"] == pytest.approx(6.5571, rel=1e-4)
    assert res["rs_ohm_per_sq"] == pytest.approx(_RS, rel=1e-12)
    assert res["rs_ohm_per_sq"] == pytest.approx(0.0261, rel=1e-3)
    assert res["beta_rad_per_m"] == pytest.approx(_BETA, rel=1e-11)
    assert res["alpha_c_np_per_m"] == pytest.approx(_AC_CU, rel=1e-9)
    assert res["alpha_c_db_per_m"] == pytest.approx(_AC_CU * _DB_PER_NP,
                                                    rel=1e-9)
    # 文献表值锤：WR-90 铜 10GHz 理论导体衰减 ~0.108–0.11 dB/m
    assert res["alpha_c_db_per_m"] == pytest.approx(0.108, rel=5e-3)
    assert res["alpha_d_db_per_m"] == 0.0
    assert res["alpha_total_db_per_m"] == pytest.approx(
        res["alpha_c_db_per_m"], rel=1e-15)


def test_wg_te10_attenuation_dielectric_and_material_paths():
    """α_d 独立算术/线性；材料档与显式电导率同值恒等；σ×4→α_c×½。"""
    tand = 1e-3
    res = wg_te10_attenuation(22.86, 10.16, 10.0, tan_delta=tand)
    alpha_d_independent = _K * _K * tand / (2.0 * _BETA)
    assert res["alpha_d_np_per_m"] == pytest.approx(alpha_d_independent,
                                                    rel=1e-12)
    assert res["alpha_total_db_per_m"] == pytest.approx(
        (_AC_CU + alpha_d_independent) * _DB_PER_NP, rel=1e-12)
    # 材料档 ↔ 显式电导率同值恒等（rel 0）
    silver = wg_te10_attenuation(22.86, 10.16, 10.0, material="silver")
    explicit = wg_te10_attenuation(22.86, 10.16, 10.0,
                                   conductivity_s_per_m=6.17e7)
    assert silver["alpha_c_np_per_m"] == explicit["alpha_c_np_per_m"]
    # σ×4 → α_c×½（Rs∝σ^(-1/2)，恒等）
    quarter_sigma = wg_te10_attenuation(22.86, 10.16, 10.0,
                                        conductivity_s_per_m=_SIGMA_CU / 4.0)
    assert quarter_sigma["alpha_c_np_per_m"] == pytest.approx(
        2.0 * _AC_CU, rel=1e-12)
    # 铝档 σ 更低 → α_c 更高（单调）
    alu = wg_te10_attenuation(22.86, 10.16, 10.0, material="aluminum")
    assert alu["alpha_c_np_per_m"] > _AC_CU


def test_wg_te10_attenuation_domain_guards():
    """截止以下/几何/材料/bool 污染显式拒绝。"""
    with pytest.raises(ValueError, match="截止"):
        wg_te10_attenuation(22.86, 10.16, 5.0)  # 5GHz < fc=6.557GHz
    with pytest.raises(ValueError):
        wg_te10_attenuation(0.0, 10.16, 10.0)
    with pytest.raises(ValueError):
        wg_te10_attenuation(22.86, -10.16, 10.0)
    with pytest.raises(ValueError, match="未知材料"):
        wg_te10_attenuation(22.86, 10.16, 10.0, material="brass")
    with pytest.raises(ValueError):
        wg_te10_attenuation(22.86, 10.16, 10.0, conductivity_s_per_m=0.0)
    with pytest.raises(ValueError):
        wg_te10_attenuation(22.86, 10.16, 10.0, tan_delta=-0.1)
    with pytest.raises(ValueError):
        wg_te10_attenuation(22.86, 10.16, 10.0, epsilon_r=0.5)
    with pytest.raises(ValueError, match="不接受 bool"):
        wg_te10_attenuation(22.86, 10.16, True)
    with pytest.raises(ValueError, match="不接受 bool"):
        wg_te10_attenuation(True, 10.16, 10.0)


def test_wg_te10_power_capacity_wr90_hand_anchor():
    """WR-90@10GHz：P_max 手算逐位 + 文献 ~1MW 量级锤。"""
    e_br = 3.0e6
    res = wg_te10_power_capacity(22.86, 10.16, 10.0)
    sqrt_factor_independent = math.sqrt(1.0 - (_FC_HZ / _F_HZ) ** 2)
    p_independent = (_A_M * _B_M / (4.0 * _ETA0)) * e_br * e_br \
        * sqrt_factor_independent
    assert res["sqrt_factor"] == pytest.approx(sqrt_factor_independent,
                                               rel=1e-12)
    assert res["p_max_w"] == pytest.approx(p_independent, rel=1e-12)
    # 文献量级锤：WR-90 @10GHz 空气击穿功率容量 ~1MW
    assert res["p_max_w"] == pytest.approx(1.0473e6, rel=5e-3)
    assert res["p_max_dbm"] == pytest.approx(
        10.0 * math.log10(p_independent / 1e-3), rel=1e-10)
    assert "海拔" in res["note"]  # E_br 环境降额注记（#122 诚实边界）


def test_wg_te10_power_capacity_limits_and_monotone():
    """b 线性恒等；f→fc⁺ P→0 连续；P 随 f 单调增。"""
    base = wg_te10_power_capacity(22.86, 10.16, 10.0)["p_max_w"]
    double_b = wg_te10_power_capacity(22.86, 20.32, 10.0)["p_max_w"]
    assert double_b == pytest.approx(2.0 * base, rel=1e-15)
    # f→∞ 极限恒等：P→(ab/4η)E_br²（10×fc 附近 √ 因子 ≈0.995）
    high_f_hz = 65.6e9
    high = wg_te10_power_capacity(22.86, 10.16, high_f_hz / 1e9)["p_max_w"]
    limit = (_A_M * _B_M / (4.0 * _ETA0)) * 9.0e12
    assert high / limit == pytest.approx(
        math.sqrt(1.0 - (_FC_HZ / high_f_hz) ** 2), rel=1e-12)
    # 近截止连续趋零：f=fc·(1+1e-6) → √ 因子 ≈1.41e-3，P ≈0.19% of @10GHz
    f_ghz = _FC_HZ / 1e9 * (1.0 + 1e-6)
    near = wg_te10_power_capacity(22.86, 10.16, f_ghz)["p_max_w"]
    assert near < 5e-3 * base
    # 单调
    p7 = wg_te10_power_capacity(22.86, 10.16, 7.0)["p_max_w"]
    p12 = wg_te10_power_capacity(22.86, 10.16, 12.0)["p_max_w"]
    assert near < p7 < base < p12


def test_wg_te10_power_capacity_domain_guards():
    with pytest.raises(ValueError, match="截止"):
        wg_te10_power_capacity(22.86, 10.16, 6.0)
    with pytest.raises(ValueError):
        wg_te10_power_capacity(22.86, 10.16, 10.0, e_br_v_per_m=0.0)
    with pytest.raises(ValueError, match="不接受 bool"):
        wg_te10_power_capacity(22.86, 10.16, 10.0, e_br_v_per_m=True)


# ─── tdr_fault_location / tdr_resolution / tdr_ets_equivalent_time ───────────

def test_tdr_fault_location_vacuum_and_permittivity_identities():
    """εeff=1 真空恒等 d=c0·t/2；εeff=4 距离减半恒等；velocity 通道同值。"""
    res = tdr_fault_location(10e-9, eps_eff=1.0)
    assert res["distance_m"] == pytest.approx(_C0 * 10e-9 / 2.0, rel=1e-15)
    assert res["distance_m"] == pytest.approx(1.49896229, rel=1e-9)
    assert res["one_way_time_s"] == pytest.approx(5e-9, rel=1e-15)
    via_velocity = tdr_fault_location(10e-9, velocity_mps=_C0)
    assert via_velocity["distance_m"] == res["distance_m"]
    four = tdr_fault_location(10e-9, eps_eff=4.0)
    assert four["distance_m"] == pytest.approx(res["distance_m"] / 2.0,
                                               rel=1e-15)
    assert four["v_p_m_per_s"] == pytest.approx(_C0 / 2.0, rel=1e-15)


def test_tdr_fault_location_domain_guards():
    """速度通道二选一/超光速/εeff<1/时间域/bool 污染显式拒绝。"""
    with pytest.raises(ValueError, match="之一"):
        tdr_fault_location(10e-9)
    with pytest.raises(ValueError, match="之一"):
        tdr_fault_location(10e-9, eps_eff=4.0, velocity_mps=2e8)
    with pytest.raises(ValueError, match="超光速"):
        tdr_fault_location(10e-9, velocity_mps=4e8)
    with pytest.raises(ValueError, match="≥1"):
        tdr_fault_location(10e-9, eps_eff=0.5)
    with pytest.raises(ValueError):
        tdr_fault_location(0.0, eps_eff=4.0)
    with pytest.raises(ValueError):
        tdr_fault_location(-10e-9, eps_eff=4.0)
    with pytest.raises(ValueError, match="不接受 bool"):
        tdr_fault_location(True, eps_eff=4.0)
    with pytest.raises(ValueError, match="不接受 bool"):
        tdr_fault_location(10e-9, eps_eff=True)


def test_tdr_resolution_linear_identity_and_hammer():
    """Δd=v_p·t_rise/2 恒等；∝t_rise 线性；30ps/εeff=2.2 数值锤。"""
    res = tdr_resolution(30e-12, eps_eff=2.2)
    expect = _C0 * 30e-12 / (2.0 * math.sqrt(2.2))
    assert res["resolution_m"] == pytest.approx(expect, rel=1e-15)
    assert res["resolution_mm"] == pytest.approx(3.0318, rel=1e-4)
    double = tdr_resolution(60e-12, eps_eff=2.2)
    assert double["resolution_m"] == pytest.approx(
        2.0 * res["resolution_m"], rel=1e-15)
    # 速度通道与 εeff 通道同值
    v_equiv = _C0 / math.sqrt(2.2)
    via_v = tdr_resolution(30e-12, velocity_mps=v_equiv)
    assert via_v["resolution_m"] == res["resolution_m"]


def test_tdr_ets_identity_and_planning():
    """f_eq=1/Δt_step 乘法恒等；时窗/耗时规划恒等；缺省 None 透传。"""
    res = tdr_ets_equivalent_time(1e-12, 100e3, n_steps=1000)
    assert res["eq_sample_rate_hz"] == pytest.approx(1e12, rel=1e-15)
    assert res["eq_sample_interval_s"] == pytest.approx(1e-12, rel=1e-15)
    assert res["ets_gain"] == pytest.approx(1e12 / 100e3, rel=1e-15)
    assert res["record_window_s"] == pytest.approx(1000 * 1e-12, rel=1e-15)
    assert res["acquisition_time_s"] == pytest.approx(1000 / 100e3,
                                                      rel=1e-15)
    # 缺省 n_steps：规划字段如实 None
    bare = tdr_ets_equivalent_time(1e-12, 100e3)
    assert bare["n_steps"] is None
    assert bare["record_window_s"] is None
    assert bare["acquisition_time_s"] is None
    # 整数值 float 透传接受
    float_steps = tdr_ets_equivalent_time(1e-12, 100e3, n_steps=2.0)
    assert float_steps["n_steps"] == 2


def test_tdr_ets_domain_guards():
    with pytest.raises(ValueError, match="mode"):
        tdr_ets_equivalent_time(1e-12, 100e3, mode="m_sequence")
    with pytest.raises(ValueError, match="≥2"):
        tdr_ets_equivalent_time(1e-12, 100e3, n_steps=1)
    with pytest.raises(ValueError, match="整数"):
        tdr_ets_equivalent_time(1e-12, 100e3, n_steps=10.5)
    with pytest.raises(ValueError, match="不接受 bool"):
        tdr_ets_equivalent_time(1e-12, 100e3, n_steps=True)
    with pytest.raises(ValueError):
        tdr_ets_equivalent_time(0.0, 100e3)
    with pytest.raises(ValueError):
        tdr_ets_equivalent_time(1e-12, -100e3)


# ─── far_field_region（天线域）───────────────────────────────────────────────

def test_far_field_region_balanis_anchor():
    """Balanis 数值锚 D=0.5m@10GHz → d_F=2D²/λ=16.6782m 逐位。"""
    res = far_field_region(0.5, 10e9)
    lam = _C0 / 10e9
    d_far = 2.0 * 0.5 * 0.5 / lam
    assert res["fraunhofer_m"] == pytest.approx(d_far, rel=1e-12)
    assert res["fraunhofer_m"] == pytest.approx(16.6782, rel=1e-4)
    assert res["wavelength_m"] == pytest.approx(lam, rel=1e-15)
    # 反应近场（大天线）0.62√(D³/λ) 独立算术
    reactive = 0.62 * math.sqrt(0.5 ** 3 / lam)
    assert res["reactive_large_antenna_m"] == pytest.approx(reactive,
                                                            rel=1e-12)
    # 电小天线 λ/2π 档独立算术
    assert res["reactive_small_antenna_m"] == pytest.approx(lam / (2.0 * math.pi),
                                                            rel=1e-12)
    # Fresnel 区窗 = (反应近场界, Fraunhofer 界)
    assert res["fresnel_inner_m"] == pytest.approx(reactive, rel=1e-12)
    assert res["fresnel_outer_m"] == pytest.approx(d_far, rel=1e-12)


def test_far_field_phase_criterion_cross_path():
    """π/8 相位判据独立几何路径 R=πD²/(4λ·Δφ) 与 2D²/λ 闭式互证。"""
    d_m, f_hz = 0.5, 10e9
    lam = _C0 / f_hz
    res = far_field_region(d_m, f_hz)
    r_phase = math.pi * d_m * d_m / (4.0 * lam * (math.pi / 8.0))
    assert res["fraunhofer_m"] == pytest.approx(r_phase, rel=1e-12)


def test_far_field_region_classification_and_conventions():
    """三区分类+边界等号语义+测量距离惯例（π/8 与 10D²/λ UNVERIFIED 标注）。"""
    d_m, f_hz = 0.5, 10e9
    d_far = far_field_region(d_m, f_hz)["fraunhofer_m"]
    reactive = far_field_region(d_m, f_hz)["reactive_large_antenna_m"]
    assert far_field_region(d_m, f_hz, r_m=d_far)["region"] == "fraunhofer"
    assert far_field_region(d_m, f_hz, r_m=d_far * 2.0)["region"] == \
        "fraunhofer"
    assert far_field_region(d_m, f_hz, r_m=(reactive + d_far) / 2.0)[
        "region"] == "fresnel"
    assert far_field_region(d_m, f_hz, r_m=reactive)["region"] == "reactive"
    assert far_field_region(d_m, f_hz, r_m=reactive / 2.0)[
        "region"] == "reactive"
    res = far_field_region(d_m, f_hz)
    assert res["measurement_range_pi8_m"] == pytest.approx(d_far, rel=1e-15)
    assert res["measurement_range_ten_d2_m"] == pytest.approx(5.0 * d_far,
                                                              rel=1e-15)
    assert "UNVERIFIED" in res["measurement_range_ten_d2_rule"]  # #122 如实


def test_far_field_region_domain_guards():
    """区界排序失效域（D<λ/10.406）/零频率/负距离/bool 污染显式拒绝。"""
    # D=1mm@10GHz：D/λ≈0.033 < 0.0961（排序失效域），显式 ValueError
    with pytest.raises(ValueError):
        far_field_region(0.001, 10e9)
    with pytest.raises(ValueError):
        far_field_region(0.0, 10e9)
    with pytest.raises(ValueError):
        far_field_region(0.5, 0.0)
    with pytest.raises(ValueError):
        far_field_region(0.5, 10e9, r_m=-1.0)
    with pytest.raises(ValueError, match="不接受 bool"):
        far_field_region(True, 10e9)
    with pytest.raises(ValueError, match="不接受 bool"):
        far_field_region(0.5, 10e9, r_m=True)
