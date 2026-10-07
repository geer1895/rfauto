"""MP-2 电晕/局放判据内核单测（core/corona.py，round15 §三 :82）。

裁判 = 外部独立来源（#118：不是被测实现的自我推导）：
  * Schumann 空气均匀场经验式：经典实测量级锚——δ=1 时 1 mm 间隙
    ≈4.4 kV、1 cm ≈30 kV（Kuffel, Zaengl & Kuffel, "High Voltage
    Engineering: Fundamentals" 口径的空气 V(pd) 实测带）；
  * Townsend-Paschen：Lieberman & Lichtenberg 2nd ed. Table 14.1 空气
    常数（A=15/B=365/γ=0.01）代入闭式的手算回收（1 mm 海平面
    ≈5035 V）+ Paschen 最小值点闭式（pd_min=e·ln(1+1/γ)/A、
    V_min=B·pd_min/e）自洽 + 左支无解域显式拒绝；
  * Peek：海平面 1 cm 导线起始场量级锚（峰值 39.0 kV/cm、rms 27.6
    kV/cm——经典 "~30 kV/cm" 带内；Peek 原书 rms 常数 21.1/0.3081）；
  * 几何因子：镜像定理恒等式（wire_plane(h) ≡ two_wire(D=2h) 精确）、
    two_wire 渐近 2r·ln(D/r)、coax 精确 r·ln(R/r)；
  * ISA：US Standard Atmosphere 1976 标准表值（p(11 km)=22632.1 Pa、
    p(10 km)=26436.2 Pa、T(11 km)=−56.5 °C）；
  * 海拔降额：10 km / 1 mm 间隙 δ=(p/p0)·(T/T0) 手算链
    （δ≈0.3369、降额比≈0.4447）+ 单调性。

确定性：无网络、无真机、无文件 IO、无随机。
"""

from __future__ import annotations

import json
import math
from itertools import pairwise

import pytest

from rfauto.core.corona import (
    AIR_TOWNSEND_A_PER_CM_TORR,
    AIR_TOWNSEND_B_V_PER_CM_TORR,
    AIR_TOWNSEND_GAMMA_SE,
    PEEK_E0_KV_PER_CM_PEAK,
    PEEK_E0_KV_PER_CM_RMS,
    air_density_factor,
    altitude_derated_breakdown_v,
    corona_geometry_factor_m,
    corona_onset_voltage_v,
    corona_pd_check,
    corona_uniform_gap_breakdown_v,
    isa_pressure_pa,
    isa_temperature_c,
    partial_discharge_inception_v,
    peek_onset_field_kv_per_cm,
    townsend_paschen_voltage_v,
)

# ---------------------------------------------------------------- Sa/TP 基准


class TestSchumannAirForm:
    """Schumann 空气工程式：经典实测量级锚（主判口径）。"""

    def test_one_mm_sea_level_classic_anchor(self) -> None:
        # δ=1、1 mm：V = 24.22·0.1 + 6.08·√0.1 = 4.3447 kV（实测 ≈4.4 kV）
        v = corona_uniform_gap_breakdown_v(0.001, delta=1.0)
        assert v == pytest.approx(4344.665, rel=1e-3)
        assert 4200.0 <= v <= 4500.0

    def test_one_cm_sea_level_classic_anchor(self) -> None:
        # δ=1、1 cm：V = 24.22 + 6.08 = 30.3 kV（实测 ≈30 kV）
        v = corona_uniform_gap_breakdown_v(0.01, delta=1.0)
        assert v == pytest.approx(30300.0, rel=1e-4)
        assert 29000.0 <= v <= 31500.0

    def test_delta_correction_monotone_and_reference(self) -> None:
        v1 = corona_uniform_gap_breakdown_v(0.001, delta=1.0)
        v_low = corona_uniform_gap_breakdown_v(0.001, delta=0.3)
        assert v_low < v1  # δ 降 → 击穿电压降（海拔降额方向）
        assert corona_uniform_gap_breakdown_v(0.001, delta=1.0) == pytest.approx(
            corona_uniform_gap_breakdown_v(0.001))

    def test_delta_manual_chain(self) -> None:
        # 手算独立链：δ=0.5、1 mm → 24.22·0.05 + 6.08·√0.05 = 2.5723 kV
        v = corona_uniform_gap_breakdown_v(0.001, delta=0.5)
        assert v == pytest.approx(2572.27, rel=1e-3)


class TestTownsendPaschen:
    """Townsend-Paschen 物理形式：手算回收 + 最小值自洽 + 域守卫。"""

    def test_sea_level_one_mm_manual_recovery(self) -> None:
        # 手算：x=76.0 Torr·cm → V = 365·76/(ln(15·76) − ln(ln 101)) ≈ 5035 V
        v = townsend_paschen_voltage_v(101325.0, 0.001)
        assert v == pytest.approx(5034.99, rel=1e-4)
        # 与实测 ≈4.4 kV 同量级（+14%，右支工程域可用性口径）
        assert 4400.0 <= v <= 5800.0

    def test_pd_product_unit_conversion(self) -> None:
        # 1 Pa·m = 0.750062 Torr·cm：101325 Pa × 1 mm = 76.0 Torr·cm
        v_mm = townsend_paschen_voltage_v(101325.0, 0.001)
        v_equiv = townsend_paschen_voltage_v(101325.0 * 10.0, 0.0001)
        assert v_mm == pytest.approx(v_equiv, rel=1e-12)  # 同 p·d 同 V

    def test_paschen_minimum_self_consistency(self) -> None:
        # 最小值点闭式：dV/dx=0 → 分母=1 → x_min = e·ln(1+1/γ)/A，
        # V_min = B·x_min（对 x_min 处分母恰为 1）
        a = AIR_TOWNSEND_A_PER_CM_TORR
        b = AIR_TOWNSEND_B_V_PER_CM_TORR
        gamma = AIR_TOWNSEND_GAMMA_SE
        ln_term = math.log(1.0 + 1.0 / gamma)
        pd_min = math.e * ln_term / a
        # pd_min [Torr·cm] ↔ (p, d) 反解：p=101325 Pa，d = pd_min/(p·0.75)
        d_m = pd_min / (101325.0 * (760.0 / 101325.0) * 100.0)
        v_at_min = townsend_paschen_voltage_v(101325.0, d_m)
        assert v_at_min == pytest.approx(b * pd_min, rel=1e-9)
        assert v_at_min == pytest.approx(305.27, rel=1e-3)
        assert v_at_min == pytest.approx(330.0, rel=0.15)  # 实测空气最小同量级

    def test_u_shape_monotonicity_around_minimum(self) -> None:
        # 最小值两侧：左支 V 随 pd 增大而降、右支随 pd 增大而升
        def v_at_pd(x_torr_cm: float) -> float:
            d_m = x_torr_cm / (101325.0 * (760.0 / 101325.0) * 100.0)
            return townsend_paschen_voltage_v(101325.0, d_m)

        left = [v_at_pd(x) for x in (0.55, 0.65, 0.78)]
        assert left[0] > left[1] > left[2]
        right = [v_at_pd(x) for x in (1.0, 5.0, 20.0, 76.0)]
        assert right[0] < right[1] < right[2] < right[3]

    def test_no_solution_domain_refused(self) -> None:
        # x < ln(1+1/γ)/A ≈ 0.3077 Torr·cm：Townsend 判据无解 → 显式拒绝
        below = math.log(1.0 + 1.0 / AIR_TOWNSEND_GAMMA_SE) / AIR_TOWNSEND_A_PER_CM_TORR
        d_m = 0.5 * below / (101325.0 * (760.0 / 101325.0) * 100.0)
        with pytest.raises(ValueError, match="无解域"):
            townsend_paschen_voltage_v(101325.0, d_m)

    def test_invalid_inputs_refused(self) -> None:
        with pytest.raises(ValueError):
            townsend_paschen_voltage_v(0.0, 0.001)
        with pytest.raises(ValueError):
            townsend_paschen_voltage_v(101325.0, -0.001)
        with pytest.raises(ValueError):
            townsend_paschen_voltage_v(101325.0, 0.001, gamma_se=0.0)


# ---------------------------------------------------------------- Peek 电晕


class TestPeekOnsetField:
    """Peek 起始场：海平面 1 cm 量级锚 + δ/半径/粗糙度单调性。"""

    def test_sea_level_one_cm_peak_anchor(self) -> None:
        # 峰值口径：30·(1+0.301/√(1·1)) = 39.03 kV/cm
        e = peek_onset_field_kv_per_cm(0.01, delta=1.0)
        assert e == pytest.approx(39.03, rel=1e-4)
        assert 25.0 <= e <= 45.0  # 经典 "~30 kV/cm 起始场" 量级带

    def test_sea_level_one_cm_rms_convention(self) -> None:
        # Peek 原书 rms 常数：21.1·(1+0.3081/1) = 27.601 kV/cm
        e = peek_onset_field_kv_per_cm(
            0.01, delta=1.0, e0_kv_per_cm=PEEK_E0_KV_PER_CM_RMS, k=0.3081)
        assert e == pytest.approx(27.601, rel=1e-4)

    def test_default_constants_are_peak_convention(self) -> None:
        assert PEEK_E0_KV_PER_CM_PEAK == 30.0
        e = peek_onset_field_kv_per_cm(0.01)
        assert e == pytest.approx(30.0 * 1.301)

    def test_smaller_wire_higher_onset_field(self) -> None:
        # √(δr) 分母：细导线起始场强更高
        e_thick = peek_onset_field_kv_per_cm(0.01)
        e_thin = peek_onset_field_kv_per_cm(0.001)
        assert e_thin == pytest.approx(58.555, rel=1e-3)
        assert e_thin > e_thick

    def test_delta_monotone(self) -> None:
        # δ 降（海拔升）→ 绝对起始场强降（电晕起始电压随海拔降的方向）
        assert peek_onset_field_kv_per_cm(0.01, delta=0.3) == pytest.approx(
            13.946, rel=1e-3)
        assert peek_onset_field_kv_per_cm(0.01, delta=0.3) < peek_onset_field_kv_per_cm(0.01)

    def test_roughness_reduces_onset(self) -> None:
        # E_c 对 m 严格线性：E(0.8·m) = 0.8·E(m)
        assert peek_onset_field_kv_per_cm(0.01, roughness=0.8) == pytest.approx(
            0.8 * peek_onset_field_kv_per_cm(0.01), rel=1e-12)

    def test_invalid_inputs_refused(self) -> None:
        with pytest.raises(ValueError):
            peek_onset_field_kv_per_cm(radius_m=0.0)
        for kwargs in (
            {"delta": 0.0}, {"roughness": 0.0},
            {"e0_kv_per_cm": -1.0}, {"k": 0.0},
        ):
            with pytest.raises(ValueError):
                peek_onset_field_kv_per_cm(0.01, **kwargs)


class TestCoronaGeometryFactor:
    """几何因子：镜像恒等式 / 渐近极限 / 精确式 / 负例。"""

    def test_wire_plane_equals_two_wire_image_theory(self) -> None:
        # 镜像定理：wire_plane(h) ≡ two_wire(D=2h)（精确恒等，非渐近）
        r = 0.005
        f_wp = corona_geometry_factor_m("wire_plane", radius_m=r, spacing_m=0.4)
        f_tw = corona_geometry_factor_m("two_wire", radius_m=r, spacing_m=0.8)
        assert f_wp == pytest.approx(f_tw, rel=1e-12)

    def test_two_wire_far_spaced_asymptote(self) -> None:
        # D/r = 1e4：exact / (2r·ln(D/r)) → 1（0.03% 内）
        r, d = 1.0e-4, 1.0
        exact = corona_geometry_factor_m("two_wire", radius_m=r, spacing_m=d)
        approx = 2.0 * r * math.log(d / r)
        assert exact / approx == pytest.approx(1.0, abs=5.0e-3)

    def test_two_wire_exact_hand_recovery(self) -> None:
        # 手算：r=1 cm、D=1 m → 2r·arcosh(50)·√(98/102) = 0.09027743 m
        f = corona_geometry_factor_m("two_wire", radius_m=0.01, spacing_m=1.0)
        assert f == pytest.approx(0.09027743, rel=1e-6)

    def test_coax_exact_identity(self) -> None:
        # 同轴精确式：factor = r·ln(R/r)
        f = corona_geometry_factor_m("coax", radius_m=0.01, spacing_m=0.1)
        assert f == pytest.approx(0.01 * math.log(10.0), rel=1e-12)

    def test_corona_onset_voltage_composition(self) -> None:
        # 报告面：V_onset = E_c[kV/cm]·1e5·factor[m]；手算 39.03×1e5×0.0230259
        rep = corona_onset_voltage_v("coax", radius_m=0.01, spacing_m=0.1)
        assert rep["onset_voltage_v"] == pytest.approx(89868.0, rel=1e-3)
        assert rep["onset_field_kv_per_cm"] == pytest.approx(39.03, rel=1e-4)
        assert rep["convention"].startswith("峰值")

    def test_two_wire_onset_voltage_magnitude(self) -> None:
        # 输电线量级：r=1 cm、D=1 m、海平面 → 起始 ~352 kV（峰值）
        rep = corona_onset_voltage_v("two_wire", radius_m=0.01, spacing_m=1.0)
        assert rep["onset_voltage_v"] == pytest.approx(352394.0, rel=1e-3)
        assert 3.0e5 <= rep["onset_voltage_v"] <= 4.0e5

    def test_unknown_geometry_refused(self) -> None:
        with pytest.raises(ValueError, match="未知几何"):
            corona_geometry_factor_m("triplate", radius_m=0.01, spacing_m=0.1)

    def test_geometry_inequalities_refused(self) -> None:
        with pytest.raises(ValueError):
            corona_geometry_factor_m("coax", radius_m=0.1, spacing_m=0.05)
        with pytest.raises(ValueError):
            corona_geometry_factor_m("two_wire", radius_m=0.01, spacing_m=0.02)
        with pytest.raises(ValueError):
            corona_geometry_factor_m("wire_plane", radius_m=0.01, spacing_m=0.01)


# ---------------------------------------------------------------- ISA 与海拔


class TestStandardAtmosphere:
    """ISA/US 1976：标准表值锚 + 单调性。"""

    def test_sea_level_reference(self) -> None:
        assert isa_pressure_pa(0.0) == pytest.approx(101325.0, rel=1e-12)
        assert isa_temperature_c(0.0) == pytest.approx(15.0, abs=1e-9)

    def test_tropopause_table_value(self) -> None:
        # US 1976 标准表：11 km → 22632.1 Pa、−56.5 °C
        assert isa_pressure_pa(11000.0) == pytest.approx(22632.1, abs=1.0)
        assert isa_temperature_c(11000.0) == pytest.approx(-56.5, abs=1e-9)

    def test_ten_km_table_value(self) -> None:
        # US 1976 标准表：10 km → 26436.2 Pa
        assert isa_pressure_pa(10000.0) == pytest.approx(26436.2, abs=5.0)

    def test_pressure_monotone_decreasing(self) -> None:
        altitudes = [0.0, 1000.0, 5000.0, 10999.0, 11001.0, 15000.0, 20000.0]
        pressures = [isa_pressure_pa(h) for h in altitudes]
        assert all(p2 < p1 for p1, p2 in pairwise(pressures))

    def test_out_of_domain_refused(self) -> None:
        with pytest.raises(ValueError, match="超出"):
            isa_pressure_pa(25000.0)
        with pytest.raises(ValueError):
            isa_pressure_pa(-1.0)
        with pytest.raises(ValueError):
            isa_temperature_c(25000.0)


class TestAirDensityFactor:
    """δ 因子：参考点恒等 + 压/温单调 + IEC 参考覆盖。"""

    def test_reference_point_is_one(self) -> None:
        assert air_density_factor(101325.0, 25.0) == pytest.approx(1.0, rel=1e-12)

    def test_monotone_in_pressure_and_temperature(self) -> None:
        base = air_density_factor(101325.0, 25.0)
        assert air_density_factor(101325.0 * 2.0, 25.0) > base
        assert air_density_factor(101325.0, 45.0) < base

    def test_peek_cmhg_equivalence(self) -> None:
        # Peek 原书 3.92·b/(273+θ)（b cmHg）：760 Torr/25 °C → 3.92·76/298 ≈ 1.000
        peek_delta = 3.92 * 76.0 / (273.0 + 25.0)
        assert air_density_factor(101325.0, 25.0) == pytest.approx(peek_delta, rel=2e-3)

    def test_temperature_ref_override(self) -> None:
        # IEC 60060-1 参考 20 °C：25 °C 时 δ = 293.15/298.15 < 1
        d = air_density_factor(101325.0, 25.0, t_ref_c=20.0)
        assert d == pytest.approx(293.15 / 298.15, rel=1e-9)
        assert d < 1.0

    def test_invalid_inputs_refused(self) -> None:
        with pytest.raises(ValueError):
            air_density_factor(0.0, 25.0)
        with pytest.raises(ValueError):
            air_density_factor(101325.0, -273.15)


class TestAltitudeDerating:
    """海拔降额：手算链 + 单调性 + 降额方向。"""

    def test_ten_km_one_mm_hand_chain(self) -> None:
        # 手算（气温缺省参考日 25 °C）：p(10km)=26436.2 → δ=0.260906 →
        # V=S(0.0260906)=1614.19、降额比 0.371528
        rep = altitude_derated_breakdown_v(0.001, 10000.0)
        assert rep["delta"] == pytest.approx(0.260906, rel=1e-4)
        assert rep["breakdown_v"] == pytest.approx(1614.19, rel=1e-3)
        assert rep["derating_ratio"] == pytest.approx(0.371528, rel=1e-3)
        # Townsend 参照（手算）：pd=19.8289 Torr·cm → V = 365·19.8289 /
        # (ln(15·19.8289) − ln(ln 101)) ≈ 1737.5 V（非线性于 pd）
        assert rep["townsend_paschen_v"] == pytest.approx(1737.46, rel=5e-3)
        assert 0.0 < rep["townsend_paschen_v"] < rep["townsend_paschen_v_sea"]

    def test_derating_monotone_in_altitude(self) -> None:
        sea = altitude_derated_breakdown_v(0.001, 0.0)
        values = [altitude_derated_breakdown_v(0.001, h)["breakdown_v"]
                  for h in (0.0, 2000.0, 6000.0, 11000.0, 16000.0)]
        assert values[0] == pytest.approx(sea["breakdown_v"], rel=1e-9)
        assert all(v2 < v1 for v1, v2 in pairwise(values))

    def test_explicit_pressure_overrides_isa(self) -> None:
        # 显式参考日条件 (101325, 25 °C) → δ=1 → 与海平面参照态逐位同
        rep = altitude_derated_breakdown_v(0.001, 10000.0, pressure_pa=101325.0,
                                           temperature_c=25.0)
        assert rep["delta"] == pytest.approx(1.0, rel=1e-12)
        assert rep["breakdown_v"] == pytest.approx(rep["breakdown_v_sea"], rel=1e-9)
        assert rep["derating_ratio"] == pytest.approx(1.0, rel=1e-9)

    def test_isa_temperature_profile_injectable(self) -> None:
        # ISA 温度剖面显式注入：10 km 实际 −50 °C，低温使 δ 回升（偏不保守侧）
        rep_cold = altitude_derated_breakdown_v(
            0.001, 10000.0, temperature_c=isa_temperature_c(10000.0))
        assert isa_temperature_c(10000.0) == pytest.approx(-50.0, abs=1e-9)
        assert rep_cold["delta"] == pytest.approx(0.348597, rel=1e-3)
        assert rep_cold["breakdown_v"] > 1614.19  # 低温修正使耐压高于 25 °C 缺省
        assert rep_cold["breakdown_v"] < rep_cold["breakdown_v_sea"]

    def test_sea_level_townsend_reference_present(self) -> None:
        rep = altitude_derated_breakdown_v(0.001, 0.0)
        assert rep["townsend_paschen_v_sea"] == pytest.approx(5034.99, rel=1e-4)


# ---------------------------------------------------------------- 局放判据


class TestPartialDischarge:
    """局放起始（均匀隙 V(pd) 口径）：小空洞量级 + 判定方向。"""

    def test_small_void_inception_scale(self) -> None:
        # 0.1 mm 气隙 @1 atm：起始 ≈850 V（微放电量级；Townsend 参照 ≈865 V）
        rep = partial_discharge_inception_v(1.0e-4)
        assert rep["inception_voltage_v"] == pytest.approx(850.2, rel=1e-3)
        assert 700.0 <= rep["inception_voltage_v"] <= 1000.0
        assert rep["townsend_paschen_inception_v"] == pytest.approx(865.02, rel=1e-3)

    def test_discharge_expected_direction(self) -> None:
        below = partial_discharge_inception_v(1.0e-4, applied_v=600.0)
        above = partial_discharge_inception_v(1.0e-4, applied_v=1200.0)
        assert below["discharge_expected"] is False
        assert below["pass"] is True
        assert above["discharge_expected"] is True
        assert above["pass"] is False

    def test_altitude_lowers_inception(self) -> None:
        sea = partial_discharge_inception_v(1.0e-4, pressure_pa=101325.0,
                                            temperature_c=25.0)
        high = partial_discharge_inception_v(1.0e-4, pressure_pa=26436.2,
                                             temperature_c=-50.0)
        assert high["inception_voltage_v"] < sea["inception_voltage_v"]

    def test_safety_factor_semantics(self) -> None:
        rep = partial_discharge_inception_v(1.0e-4, applied_v=600.0, safety_factor=2.0)
        # 850/600=1.42 < 2 → margin 不足判放电预期（保守判定语义）
        assert rep["margin_ratio"] == pytest.approx(850.2 / 600.0, rel=1e-3)
        assert rep["discharge_expected"] is True

    def test_invalid_inputs_refused(self) -> None:
        with pytest.raises(ValueError):
            partial_discharge_inception_v(0.0)
        with pytest.raises(ValueError):
            partial_discharge_inception_v(1.0e-4, applied_v=-5.0)


# ---------------------------------------------------------------- 合成判据


class TestCoronaPdCheck:
    """合成判据 corona_pd_check：三面裕量 + JSON 契约 + 负例。"""

    def test_overvoltage_fails_all_relevant_faces(self) -> None:
        rep = corona_pd_check(5000.0, 0.001)
        assert rep["breakdown"]["pass"] is False  # 4.34 kV < 5 kV
        assert rep["partial_discharge"]["discharge_expected"] is True
        assert rep["pass"] is False
        assert rep["corona"] is None

    def test_undervoltage_passes(self) -> None:
        rep = corona_pd_check(500.0, 0.001)
        assert rep["breakdown"]["pass"] is True
        assert rep["partial_discharge"]["pass"] is True
        assert rep["pass"] is True

    def test_corona_face_with_conductor_geometry(self) -> None:
        rep = corona_pd_check(1.0e5, 0.001, geometry="coax",
                              radius_m=0.01, spacing_m=0.1)
        assert rep["corona"] is not None
        assert rep["corona"]["onset_voltage_v"] == pytest.approx(89868.0, rel=1e-3)
        # 起始 89.87 kV < 施加 100 kV → 电晕面不过，整体不过
        assert rep["corona"]["pass"] is False
        assert rep["pass"] is False
        # 同几何降电压（40 kV）→ 电晕面裕量 2.25 过（击穿/局放面按各自口径另判）
        ok = corona_pd_check(4.0e4, 0.001, geometry="coax",
                             radius_m=0.01, spacing_m=0.1)
        assert ok["corona"]["pass"] is True

    def test_altitude_derates_verdict(self) -> None:
        # 空洞局放形态：间隙 1 mm、空洞 0.1 mm、施加 700 V
        # 海平面：击穿 4345/700=6.2、局放 850/700=1.21 → 全过
        sea = corona_pd_check(700.0, 0.001, pd_gap_m=1.0e-4)
        assert sea["pass"] is True
        # 10 km：击穿面仍过（1932/700=2.76）但局放面被降额打穿
        # （0.1 mm 空洞起始 434.5 V < 700 V）——降额先击穿局放面
        high = corona_pd_check(700.0, 0.001, pd_gap_m=1.0e-4, altitude_m=10000.0)
        assert high["breakdown"]["pass"] is True
        assert high["partial_discharge"]["pass"] is False
        assert high["partial_discharge"]["discharge_expected"] is True
        assert high["pass"] is False

    def test_missing_geometry_params_refused(self) -> None:
        with pytest.raises(ValueError, match="radius_m"):
            corona_pd_check(1000.0, 0.001, geometry="two_wire")

    def test_invalid_voltage_gap_refused(self) -> None:
        with pytest.raises(ValueError):
            corona_pd_check(0.0, 0.001)
        with pytest.raises(ValueError):
            corona_pd_check(1000.0, 0.0)
        with pytest.raises(ValueError):
            corona_pd_check(1000.0, 0.001, altitude_m=-5.0)

    def test_json_serializable_no_nan(self) -> None:
        rep = corona_pd_check(500.0, 0.001, geometry="two_wire",
                              radius_m=0.005, spacing_m=0.8)
        text = json.dumps(rep, allow_nan=False, sort_keys=True)
        assert "NaN" not in text
        assert rep["delta"] > 0.0
