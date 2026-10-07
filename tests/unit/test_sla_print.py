"""core/sla_print.py（P5 SLA 打印微波件工艺约束闭式）测试。

独立基准（#118/#300，全离线）：
- 趋肤深度两代数形互证：√(2/(ωμσ)) vs 1/√(πfμσ) 全频段逐位一致；
- 电流份额闭式 1−e^(−t/δ) vs 数值积分 ∫e^(−z/δ)dz 归一（梯形法独立实现）；
- 3δ 惯例闭式回收：份额≥0.95 ⇔ t≥ln(20)·δ≈3.0δ；
- #340 埋点回收：薄特征/薄壁/中空无排液孔/镀层不足/未测 εr 全拦；
- UNVERIFIED_machine_specific 口径：占位档透出 profile_unverified。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.sla_print import (
    SLAPrinterProfile,
    check_printability,
    current_fraction_in_thickness,
    material_prior_gate,
    plating_check,
    skin_depth,
)

SIGMA_CU = 5.8e7  # 退火铜电导率量级（调用方给定的常量级事实）


class TestSkinDepth:
    def test_two_algebraic_forms_agree(self):
        """√(2/(ωμσ)) 与 1/√(πfμσ) 全频段逐位一致（代数形互证）。"""
        for f in (1e6, 1e9, 2.4e9, 1e10, 7.8e10):
            d1 = skin_depth(f, SIGMA_CU)
            d2 = 1.0 / np.sqrt(np.pi * f * 4e-7 * np.pi * SIGMA_CU)
            assert d1 == pytest.approx(float(d2), rel=1e-12)

    def test_copper_10ghz_order(self):
        """铜 10 GHz δ 量级自检：~0.66 µm（由常量直接算得，非文献抄写）。"""
        delta = skin_depth(1e10, SIGMA_CU)
        assert delta == pytest.approx(0.66e-6, rel=0.03)

    def test_scaling_laws(self):
        """标度律：δ ∝ f^(−1/2) 与 δ ∝ σ^(−1/2)（闭式性质回收）。"""
        d1 = skin_depth(1e9, SIGMA_CU)
        assert skin_depth(4e9, SIGMA_CU) == pytest.approx(d1 / 2, rel=1e-12)
        assert skin_depth(1e9, SIGMA_CU / 4) == pytest.approx(2 * d1, rel=1e-12)

    def test_guards(self):
        with pytest.raises(ValueError, match="freq_hz"):
            skin_depth(0, SIGMA_CU)
        with pytest.raises(ValueError, match="sigma_s_m"):
            skin_depth(1e9, -1.0)


class TestCurrentFraction:
    def test_closed_form_vs_numeric_integral(self):
        """份额闭式 1−e^(−t/δ) vs 梯形积分 ∫e^(−z/δ)dz/t 独立实现。"""
        delta = skin_depth(2.4e9, SIGMA_CU)
        for t_factor in (0.5, 1.0, 3.0, 8.0):
            t = t_factor * delta
            z = np.linspace(0.0, t, 200001)
            # 份额=∫₀ᵗe^(−z/δ)dz / ∫₀^∞e^(−z/δ)dz（归一化基准=δ）
            fraction_numeric = float(np.trapezoid(np.exp(-z / delta), z)) / delta
            assert current_fraction_in_thickness(t, delta) == \
                pytest.approx(fraction_numeric, rel=1e-4)

    def test_three_delta_rule(self):
        """t=3δ 时份额=1−e^(−3)=0.9502 ≥ 0.95（3δ 惯例闭式来源）。"""
        delta = 1e-6
        frac = current_fraction_in_thickness(3.0 * delta, delta)
        assert frac == pytest.approx(1.0 - np.exp(-3.0), rel=1e-12)
        assert frac >= 0.95

    def test_plating_check_boundary(self):
        """镀层检查：t=3δ 过、t=2δ（份额 0.865）拒、shortfall 如实。"""
        freq, sigma = 1e10, SIGMA_CU
        delta = skin_depth(freq, sigma)
        ok_case = plating_check(freq, sigma, 3.0 * delta)
        assert ok_case["ok"] is True
        assert ok_case["fraction"] == pytest.approx(0.9502, rel=1e-3)
        bad_case = plating_check(freq, sigma, 2.0 * delta)
        assert bad_case["ok"] is False
        assert bad_case["fraction"] == pytest.approx(
            1.0 - np.exp(-2.0), rel=1e-6)
        # shortfall = ln(20)·δ − 2δ（min_t=ln(1/(1−0.95))·δ，非整 δ）
        assert bad_case["shortfall_m"] == pytest.approx(
            (float(np.log(20.0)) - 2.0) * delta, rel=1e-9)


class TestPrintability:
    def test_good_geometry_passes(self):
        out = check_printability(
            {"min_feature_mm": 0.5, "height_mm": 20.0, "aspect_ratio": 4.0,
             "min_wall_mm": 1.5, "is_hollow": True, "drain_hole_mm": 3.0})
        assert out["ok"] is True
        assert all(c["status"] != "fail" for c in out["constraints"])
        assert out["profile_unverified"] is True  # 占位档口径透出

    def test_planted_violations_all_caught(self):
        """#340 埋点回收：薄特征/高纵横比/薄壁/中空无排液孔全拦。"""
        out = check_printability(
            {"min_feature_mm": 0.02, "aspect_ratio": 50.0,
             "min_wall_mm": 0.1, "is_hollow": True})
        fails = {c["name"] for c in out["constraints"] if c["status"] == "fail"}
        assert fails == {"min_feature", "aspect_ratio", "min_wall",
                         "drain_hole"}
        assert out["ok"] is False

    def test_missing_fields_unknown_not_fail(self):
        """缺项=unknown（不判 FAIL 也不静默 PASS），ok 仍 True。"""
        out = check_printability({})
        assert out["ok"] is True
        unknowns = {c["name"] for c in out["constraints"]
                    if c["status"] == "unknown"}
        assert {"min_feature", "layer_count", "aspect_ratio",
                "min_wall"} <= unknowns

    def test_layer_count_closed_form(self):
        """层数 = ceil(高/层厚)（离散化闭式）。"""
        out = check_printability({"height_mm": 10.1})
        lc = next(c for c in out["constraints"] if c["name"] == "layer_count")
        assert lc["actual"] == 202  # 10.1 / 0.05

    def test_custom_profile_overrides(self):
        """显式传机型档覆盖占位档（UNVERIFIED 占位口径不进生产）。"""
        prof = SLAPrinterProfile(
            name="spec_sheet_machine", laser_spot_mm=0.05, layer_mm=0.025,
            min_wall_mm=0.5, max_aspect_ratio=10.0, tolerance_mm=0.05,
            drain_hole_min_mm=1.0, notes="规格书核对档")
        out = check_printability(
            {"min_feature_mm": 0.08, "is_hollow": True, "drain_hole_mm": 0.5},
            profile=prof)
        by_name = {c["name"]: c for c in out["constraints"]}
        assert by_name["min_feature"]["status"] == "pass"  # 0.08 ≥ 0.05
        assert by_name["drain_hole"]["status"] == "fail"  # 0.5 < 1.0
        assert out["profile"] == "spec_sheet_machine"
        assert out["profile_unverified"] is False


class TestMaterialPriorGate:
    def test_no_measurement_fails(self):
        """未测 εr → FAIL（'先测 εr 再设计'守卫，P5 流程核心）。"""
        out = material_prior_gate(None)
        assert out["ok"] is False
        assert "先测" in out["reason"]

    def test_in_window_passes(self):
        out = material_prior_gate(2.9, 0.02)
        assert out["ok"] is True
        assert out["gate"] == "pass"

    def test_out_of_window_fails(self):
        assert material_prior_gate(0.5)["ok"] is False   # 快于空气，非物理
        assert material_prior_gate(50.0)["ok"] is False  # 越出树脂先验窗
        assert material_prior_gate(float("nan"))["ok"] is False

    def test_custom_window(self):
        assert material_prior_gate(2.9, plausibility_window=(2.0, 4.0))["ok"] \
            is True
        assert material_prior_gate(2.9, plausibility_window=(3.0, 4.0))["ok"] \
            is False
