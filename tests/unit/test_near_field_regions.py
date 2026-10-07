"""AP-3 近场区界判据族锚测试（round17 §三 AP-3，2026-10-03）。

锚口径（#118/#300：≥2 独立基准/件，门值预声明）：

- Fraunhofer 2D²/λ：闭式手算锚 D=0.5m@10GHz=16.6782m（c 精确值
  现算）；标度恒等 D×2→×4、f×2→×2。
- 相位判据独立几何互证：R=2D²/λ 处口径边缘-中心程差
  √(R²+(D/2)²)−R = λ/16 → 相位 2π·(λ/16)/λ=π/8（几何前提数值
  直接评估，与闭式换算 r=πD²/(4λΔφ) 两推导路径独立）；π/8→2D²/λ、
  π/16→4D²/λ 恒等。
- 反应近场 0.62√(D³/λ)：D=λ→0.62λ、D=2λ→0.62√8·λ=1.753634λ
  手算值；小天线惯例 λ/2π：1GHz→0.0477465m。
- 区界排序成立域 D ≥ 0.62²λ/4 = λ/10.4058：D/λ=0.05 ValueError、
  D/λ=0.2 OK（代数解边界，测试钉两侧）。
- 测量惯例档：pi_16=2×pi_8、ten_d2=5×pi_8（ten_d2 独立文献出处
  UNVERIFIED——模块 docstring #122 标注，测试只钉自洽标度）。
- 分类/评估面：三区连续划分含边界等号；far_field_assessment JSON
  可序列化。
"""

from __future__ import annotations

import json
import math

import pytest

from rfauto.core.near_field_regions import (
    C0_M_S,
    classify_region,
    far_field_assessment,
    far_field_range_for_phase_error_m,
    fraunhofer_distance_m,
    fresnel_region_m,
    measurement_range_m,
    reactive_near_field_m,
    reactive_near_field_small_antenna_m,
    wavelength_m,
)


class TestWavelength:
    def test_value(self):
        assert wavelength_m(10e9) == pytest.approx(0.0299792458, rel=1e-12)
        with pytest.raises(ValueError, match="正"):
            wavelength_m(-1.0)
        with pytest.raises(ValueError, match="bool"):
            wavelength_m(True)


class TestFraunhofer:
    def test_hand_value(self):
        # D=0.5m@10GHz：2·0.25/0.0299792458 = 16.6782m（闭式手算锚）
        d_f = fraunhofer_distance_m(0.5, 10e9)
        assert d_f == pytest.approx(2.0 * 0.25 / 0.0299792458, rel=1e-12)
        assert d_f == pytest.approx(16.6782, rel=1e-4)

    def test_scaling_identities(self):
        base = fraunhofer_distance_m(1.0, 10e9)
        assert fraunhofer_distance_m(2.0, 10e9) == pytest.approx(4.0 * base)
        assert fraunhofer_distance_m(1.0, 20e9) == pytest.approx(2.0 * base)


class TestPhaseCriterion:
    def test_pi8_identity(self):
        # π/8 相位判据 ↔ 2D²/λ 恒等（两条推导路径的交叉验证）
        d, f = 2.0, 10e9
        assert far_field_range_for_phase_error_m(
            d, f, math.pi / 8) == pytest.approx(
            fraunhofer_distance_m(d, f), rel=1e-12)
        assert far_field_range_for_phase_error_m(
            d, f, math.pi / 16) == pytest.approx(
            2.0 * fraunhofer_distance_m(d, f), rel=1e-12)

    def test_geometric_premise_numeric(self):
        # 几何前提独立评估：R=2D²/λ 处程差≈λ/16 → 相位≈π/8。
        # 门 1e-5：闭式 2D²/λ 是程差 D²/(8R) 的抛物（paraxial）近似，
        # 残差 O((D/4R)²)~6e-6 相对（D=3m@5GHz 实测 6.2e-6，预声明）
        d_m, f_hz = 3.0, 5e9
        r = fraunhofer_distance_m(d_m, f_hz)
        lam = C0_M_S / f_hz
        path_diff = math.sqrt(r**2 + (d_m / 2.0) ** 2) - r
        assert path_diff == pytest.approx(lam / 16.0, rel=1e-5)
        phase = 2.0 * math.pi * path_diff / lam
        assert phase == pytest.approx(math.pi / 8.0, rel=1e-5)

    def test_domain_guard(self):
        with pytest.raises(ValueError, match=r"\(0, π\]"):
            far_field_range_for_phase_error_m(1.0, 10e9, 0.0)
        with pytest.raises(ValueError, match=r"\(0, π\]"):
            far_field_range_for_phase_error_m(1.0, 10e9, 4.0)


class TestReactiveNearField:
    def test_hand_values(self):
        f = 3e9
        lam = C0_M_S / f
        # D=λ → 0.62λ；D=2λ → 0.62·√8·λ = 1.753634λ（手算锚）
        assert reactive_near_field_m(lam, f) == pytest.approx(0.62 * lam)
        assert reactive_near_field_m(2 * lam, f) == pytest.approx(
            0.62 * math.sqrt(8.0) * lam, rel=1e-12)

    def test_small_antenna_convention(self):
        # λ/2π（IEEE 145-1983 / OSHA 1990 公开域口径）；
        # c 精确值：0.299792458/(2π)=0.0477135m（首稿 0.0477465 系 c≈3e8 手误）
        assert reactive_near_field_small_antenna_m(1e9) == pytest.approx(
            0.0477135, rel=1e-5)
        assert reactive_near_field_small_antenna_m(1e9) == pytest.approx(
            C0_M_S / 1e9 / (2.0 * math.pi), rel=1e-14)


class TestFresnelRegion:
    def test_boundaries_hand_value(self):
        # D=1m@10GHz：inner=0.62·√(1/0.0299792)=3.5810m、outer=66.7127m
        region = fresnel_region_m(1.0, 10e9)
        assert region["inner_m"] == pytest.approx(
            0.62 * math.sqrt(1.0 / 0.0299792458), rel=1e-12)
        assert region["outer_m"] == pytest.approx(
            2.0 / 0.0299792458, rel=1e-12)
        assert region["inner_m"] < region["outer_m"]

    def test_ordering_validity_domain(self):
        # 排序成立域 D ≥ 0.62²λ/4 = λ/10.4058（代数解两侧钉）
        f = 10e9
        lam = C0_M_S / f
        with pytest.raises(ValueError, match=r"10\.4|判据族失效|低于"):
            fresnel_region_m(0.05 * lam, f)
        ok = fresnel_region_m(0.2 * lam, f)  # 域内不炸
        assert ok["inner_m"] <= ok["outer_m"]
        # 恰在边界值上的等式校验（代数解回代）
        d_boundary = (0.62**2 / 4.0) * lam
        region = fresnel_region_m(d_boundary, f)
        assert region["inner_m"] == pytest.approx(region["outer_m"], rel=1e-9)


class TestMeasurementRange:
    def test_rules_scaling(self):
        d, f = 1.2, 6e9
        r8, src8 = measurement_range_m(d, f, "pi_8")
        r16, _ = measurement_range_m(d, f, "pi_16")
        r10, _ = measurement_range_m(d, f, "ten_d2")
        assert r8 == pytest.approx(fraunhofer_distance_m(d, f))
        assert r16 == pytest.approx(2.0 * r8)
        assert r10 == pytest.approx(5.0 * r8)  # ten_d2：UNVERIFIED 档自洽标度
        assert "UNVERIFIED" in measurement_range_m(d, f, "ten_d2")[1]
        assert "pi/8" in src8 or "2D2" in src8
        with pytest.raises(ValueError, match="rule"):
            measurement_range_m(d, f, "bogus")


class TestClassify:
    def test_three_zone_partition(self):
        d, f = 1.0, 10e9
        region = fresnel_region_m(d, f)
        inner, outer = region["inner_m"], region["outer_m"]
        assert classify_region(0.5 * inner, d, f) == "reactive"
        assert classify_region(inner, d, f) == "reactive"      # ≤ 含等号
        assert classify_region(0.5 * (inner + outer), d, f) == "fresnel"
        assert classify_region(outer, d, f) == "fraunhofer"    # ≥ 含等号
        assert classify_region(10.0 * outer, d, f) == "fraunhofer"
        with pytest.raises(ValueError):
            classify_region(1.0, 0.01 * C0_M_S / f, f)  # D/λ=0.01 域外


class TestAssessment:
    def test_payload_and_json(self):
        out = far_field_assessment(100.0, 1.0, 10e9)
        assert out["region"] == classify_region(100.0, 1.0, 10e9)
        assert out["fraunhofer_m"] == pytest.approx(
            fraunhofer_distance_m(1.0, 10e9))
        assert "exposure_limits" in out["note"]
        json.dumps(out)  # JSON 可序列化契约
        with pytest.raises(ValueError):
            far_field_assessment(-1.0, 1.0, 10e9)
