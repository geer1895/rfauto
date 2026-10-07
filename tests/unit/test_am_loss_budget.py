r"""PK-8 AM RF 损耗预算测试（锚树预声明，#122 判据先行）。

每件 ≥2 独立基准（出处见 core/am_loss_budget.py 模块 docstring）：

- Ra→Rq：① 高斯 E|X|=√(2/π) 梯形积分数值复核（独立于模块常数）；
  ② 零点恒等 Rq(0)=0；③ bool/负值拒收。
- Wiener 界：① φ=0 两界合一 ≡ σ（构造恒等）；② 上界随 φ 单调、
  φ=1 归零（层理极限物理）；③ σ_eff 守卫两态。
- 波导衰减预算：① **独立实现裁判**——TE10 壁损耗功率积分
  （α=P_loss/(2·P_flow)，场解析式+梯形数值积分，与 alpha_c_te10 的
  代数推导无共同路径）相对差 <1e-3；② 与 rw_tables fc10 一致性；
  ③ 分解可加恒等式（total=ideal+excess+dielectric 构造恒等）；
  ④ smooth 档 excess=0 恒等；⑤ K 反演往返自洽。
- 粗糙度路径：K·α_c_smooth 精确乘子结构 + K(ra) 单调。
- MNSL 锚：登记槽 status=UNVERIFIED_literature（数值不进判据）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.am_loss_budget import (
    AM_PRINT_METAL_NOTES,
    MNSL_2024_WR10_EXCESS_DB,
    compare_excess_to_registered_anchor,
    gaussian_rq_over_ra,
    required_roughness_gain_for_excess,
    rq_from_ra_gaussian,
    validate_printed_sigma_eff,
    wiener_conductivity_bounds,
    wr_loss_budget,
)
from rfauto.core.rw_tables import wr_lookup

_CU_SIGMA = 5.8e7


def _te10_alpha_c_numeric_np_per_m(a: float, b: float, f_hz: float,
                                   sigma: float, n: int = 200001) -> float:
    """独立实现：TE10 壁损耗功率积分 → α=P_loss/(2·P_flow) [Np/m]。

    场解析式（e^{jωt−jβz} 约定，E_y=E0·sin(πx/a) 为唯一幅度）：
    H_x=−(β/ωμ)·E0·sin(πx/a)、H_z=j·(π/ωμa)·E0·cos(πx/a)。
    P_flow=(β/ωμ)·E0²·a·b/4；P_loss=(Rs/2)∮|H_t|²dl（侧壁闭式 +
    上下壁数值积分）。与 alpha_c_te10 的代数推导无共同路径。
    """
    mu0 = 4.0e-7 * math.pi
    k_c = math.pi / a
    fc = 299792458.0 / (2.0 * a)
    beta = 2.0 * math.pi * f_hz / 299792458.0 * math.sqrt(
        max(0.0, 1.0 - (fc / f_hz) ** 2))
    omega_mu = 2.0 * math.pi * f_hz * mu0
    rs = math.sqrt(math.pi * f_hz * mu0 / sigma)
    # P_flow（E0=1 归一）
    p_flow = beta / omega_mu * a * b / 4.0
    # 侧壁（x=0,a）：|H_t|²=|H_z|²=(k_c/ωμ)²
    p_side = rs / 2.0 * (2.0 * b) * (k_c / omega_mu) ** 2
    # 上下壁（y=0,b）：|H_t|²=(β/ωμ)²sin²+(k_c/ωμ)²cos²，两壁×Rs/2 = Rs·∫
    x = np.linspace(0.0, a, n)
    integrand = ((beta / omega_mu) ** 2 * np.sin(k_c * x) ** 2
                 + (k_c / omega_mu) ** 2 * np.cos(k_c * x) ** 2)
    p_tb = rs * float(np.trapezoid(integrand, x))
    return (p_side + p_tb) / (2.0 * p_flow)


class TestRaToRq:
    def test_gaussian_constant_by_numeric_quadrature(self):
        """独立裁判：N(0,1) 的 E|X| 数值积分 → √(2/π) → Rq/Ra=√(π/2)。"""
        x = np.linspace(-40.0, 40.0, 4000001)
        pdf = np.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)
        e_abs = float(np.trapezoid(np.abs(x) * pdf, x))
        assert e_abs == pytest.approx(math.sqrt(2.0 / math.pi), rel=1e-8)
        # 单位高斯：Rq=σ=1、Ra=E|X| → Rq/Ra = 1/E|X|
        assert gaussian_rq_over_ra() == pytest.approx(1.0 / e_abs, rel=1e-8)

    def test_zero_and_guards(self):
        assert rq_from_ra_gaussian(0.0) == 0.0
        with pytest.raises(ValueError, match="bool"):
            rq_from_ra_gaussian(True)
        with pytest.raises(ValueError, match="非负"):
            rq_from_ra_gaussian(-1e-6)


class TestWienerBounds:
    def test_zero_void_collapse_identity(self):
        out = wiener_conductivity_bounds(_CU_SIGMA, 0.0)
        assert out["parallel_upper_s_per_m"] == pytest.approx(_CU_SIGMA,
                                                              rel=1e-15)
        assert out["series_lower_s_per_m"] == 0.0

    def test_upper_monotonic_and_vanishing(self):
        up = [wiener_conductivity_bounds(_CU_SIGMA, phi)["parallel_upper_s_per_m"]
              for phi in (0.0, 0.1, 0.5, 0.99)]
        assert up == sorted(up, reverse=True)
        assert wiener_conductivity_bounds(_CU_SIGMA, 1.0)[
            "parallel_upper_s_per_m"] == 0.0

    def test_sigma_eff_guard_two_state(self):
        ok = validate_printed_sigma_eff(3.0e7, _CU_SIGMA, 0.2)
        assert ok["ok"] is True  # 上界 (1−0.2)·5.8e7=4.64e7
        bad = validate_printed_sigma_eff(5.0e7, _CU_SIGMA, 0.2)
        assert bad["ok"] is False
        assert "超出并联上界" in bad["message"]

    def test_registration_slot_has_no_value(self):
        assert AM_PRINT_METAL_NOTES["status"] == "UNVERIFIED_no_value_registered"


class TestWrLossBudget:
    def test_alpha_c_matches_independent_wall_loss_integration(self):
        """独立实现裁判：TE10 功率积分 vs alpha_c_te10（rel<1e-3）。"""
        rec = wr_lookup("WR-10")
        a = rec.a_mm * 1e-3
        b = rec.b_mm * 1e-3
        f_hz = 94e9
        num = _te10_alpha_c_numeric_np_per_m(a, b, f_hz, _CU_SIGMA)
        budget = wr_loss_budget("WR-10", 94.0, 0.0254, sigma_s_per_m=_CU_SIGMA)
        assert budget["alpha_c_smooth_np_per_m"] == pytest.approx(num, rel=1e-3)

    def test_wr_metadata_consistency(self):
        rec = wr_lookup("WR-10")
        budget = wr_loss_budget("WR-10", 94.0, 0.0254, sigma_s_per_m=_CU_SIGMA)
        assert budget["a_mm"] == rec.a_mm
        assert budget["fc10_ghz"] == pytest.approx(
            299792458.0 / (2.0 * rec.a_mm * 1e-3) / 1e9, rel=1e-12)
        assert budget["in_recommended_band"] is True

    def test_smooth_decomposition_identity_and_zero_excess(self):
        budget = wr_loss_budget("WR-10", 94.0, 0.0254, sigma_s_per_m=_CU_SIGMA)
        assert budget["roughness_gain_k"] == 1.0
        assert budget["excess_db"] == 0.0
        assert budget["total_db"] == pytest.approx(
            budget["ideal_db"] + budget["excess_db"] + budget["dielectric_db"],
            rel=1e-15)

    def test_dielectric_branch_additive(self):
        budget = wr_loss_budget("WR-10", 94.0, 0.0254, sigma_s_per_m=_CU_SIGMA,
                                tan_d=0.001)
        assert budget["dielectric_db"] > 0.0
        assert budget["total_db"] == pytest.approx(
            budget["ideal_db"] + budget["excess_db"] + budget["dielectric_db"],
            rel=1e-15)

    def test_roughness_multiplier_structure_and_monotonic(self):
        r_low = wr_loss_budget("WR-10", 94.0, 0.0254, sigma_s_per_m=_CU_SIGMA,
                               roughness={"model": "hammerstad",
                                          "ra_m": 1e-6})
        r_high = wr_loss_budget("WR-10", 94.0, 0.0254, sigma_s_per_m=_CU_SIGMA,
                                roughness={"model": "hammerstad",
                                           "ra_m": 5e-6})
        assert r_high["roughness_gain_k"] > r_low["roughness_gain_k"] > 1.0
        smooth = wr_loss_budget("WR-10", 94.0, 0.0254, sigma_s_per_m=_CU_SIGMA)
        for out in (r_low, r_high):
            assert out["alpha_c_total_np_per_m"] == pytest.approx(
                out["roughness_gain_k"] * smooth["alpha_c_smooth_np_per_m"],
                rel=1e-15)
        assert r_low["roughness"]["rq_conversion"] == "gaussian_sqrt_pi_over_2"
        assert r_low["roughness"]["rq_m"] == pytest.approx(
            math.sqrt(math.pi / 2.0) * 1e-6, rel=1e-15)

    def test_roughness_gain_inversion_roundtrip(self):
        budget = wr_loss_budget("WR-10", 94.0, 0.0254, sigma_s_per_m=_CU_SIGMA,
                                roughness={"model": "hammerstad",
                                           "ra_m": 3e-6})
        k_req = required_roughness_gain_for_excess(
            budget["excess_db"], "WR-10", 94.0, 0.0254,
            sigma_s_per_m=_CU_SIGMA)
        assert k_req["k_required"] == pytest.approx(
            budget["roughness_gain_k"], rel=1e-12)

    def test_guards(self):
        with pytest.raises(KeyError):
            wr_loss_budget("WR-999", 94.0, 0.0254, sigma_s_per_m=_CU_SIGMA)
        # WR-10 截止 59.09 GHz：截止下不外推（alpha_c_te10 契约）
        with pytest.raises(ValueError, match="截止"):
            wr_loss_budget("WR-10", 50.0, 0.0254, sigma_s_per_m=_CU_SIGMA)
        with pytest.raises(ValueError, match="未知粗糙度模型"):
            wr_loss_budget("WR-10", 94.0, 0.0254, sigma_s_per_m=_CU_SIGMA,
                           roughness={"model": "ra_to_huray_magic"})


class TestMnsAnchor:
    def test_anchor_registered_unverified(self):
        assert MNSL_2024_WR10_EXCESS_DB["value_db"] == 4.02
        assert MNSL_2024_WR10_EXCESS_DB["status"] == "UNVERIFIED_literature"

    def test_compare_report_only(self):
        out = compare_excess_to_registered_anchor(4.02)
        assert out["ratio_to_anchor"] == pytest.approx(1.0, rel=1e-15)
        assert "report_only" in out["verdict"]
        out2 = compare_excess_to_registered_anchor(0.0)
        assert out2["ratio_to_anchor"] == 0.0
