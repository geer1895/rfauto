r"""PK-7 封装互连闭式库测试（锚树预声明，#122 判据先行）。

每件 ≥2 独立基准（出处见 core/package_interconnect.py 模块 docstring
文献核实账）：

- TGV 同轴闭合：① L·C=με 精确恒等式；② Z0=(60/√εr)ln(b/a) 恒等式；
  ③ 数值径向 Laplace 独立实现（FD）对 C'。
- Rosa 直线自感（转写式）：① 内感分解代数恒等式
  （total−(外感−1 口径) ≡ μ0·l/(8π)）；② 正则化 Neumann 精确闭式
  （=coincident filament mutual+内感）随 l/r→∞ 收敛；③ 行业 nH/mm
  经验带（UNVERIFIED_rule_of_thumb，显式标注不作为硬物理裁判）。
- 平行丝互感：① 闭式 vs Neumann 数值内核（独立裁判）逐位一致；
  ② Greenhouse 等长互感转写式随 l/GMD→∞ 收敛到精确式。
- GMD 定义式数值：① w→0 → s；② 对数凹性 GMD<s + 单调性；
  ③ 小宽度渐近展开 s·exp(−w²/(6s²))（独立推导对照）。
- 方螺旋 Greenhouse 组装：① 结构量自洽（l_dc=l_self+m+−m− 恒等、
  垂直对不计）；② 圈数单调；③ vs Mohan 电流片（已核系数、独立文献
  模型）软带 ±20%（两模型各自声明误差面之和量级）。
- 凸点/MIM：平行板缩放恒等式族。
- QFN 腔模：(1,0,0) 模 f=c/(2a) 恒等式 + 带内风险判定两态。
- RDL 设计链：synthesis 单源回代自洽（inverse_width 契约）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.package_interconnect import (
    IPD_GLASS_STACK_REFERENCE,
    bump_inductance,
    bump_parallel_plate_capacitance,
    gmd_equal_strips,
    greenhouse_mutual_equal_length_h,
    greenhouse_segment_self_h,
    mim_capacitance,
    mohan_square_current_sheet,
    parallel_filament_mutual_exact_h,
    parallel_filament_mutual_quadrature_h,
    qfn_air_cavity_report,
    rdl_design_params,
    rosa_wire_self_inductance_h,
    spiral_square_greenhouse,
    tgv_coax_quasi_static,
    tgv_isolated_inductance,
)

_MU0 = 4.0e-7 * math.pi


def _radial_laplace_c_per_m(a: float, b: float, er: float, n: int = 20001) -> float:
    """独立实现：一维径向 Laplace FD 解同轴电容（判据 ③；带状求解）。"""
    r = np.linspace(a, b, n)
    dr = r[1] - r[0]
    ab = np.zeros((3, n))
    rhs = np.zeros(n)
    ab[1, 0] = 1.0
    rhs[0] = 1.0
    ab[1, -1] = 1.0
    lo = r[1:-1] - dr / 2.0
    di = r[1:-1]
    hi = r[1:-1] + dr / 2.0
    ab[0, 2:] = hi / dr**2          # 上对角（i, i+1）
    ab[1, 1:-1] = -2.0 * di / dr**2  # 主对角
    ab[2, :-2] = lo / dr**2          # 下对角（i, i-1）
    from scipy.linalg import solve_banded

    v = solve_banded((1, 1), ab, rhs)
    e_a = -(v[1] - v[0]) / dr  # V(a)=1、V(b)=0，E=−dV/dr
    eps0 = 1.0 / (_MU0 * 299792458.0**2)  # 与被测模块同口径（rwg_mmt 惯例）
    return 2.0 * math.pi * eps0 * er * a * e_a


class TestTgvCoaxQuasiStatic:
    def test_lc_identity_exact(self):
        out = tgv_coax_quasi_static(25e-6, 300e-6, 500e-6, 5.3)
        assert out["identity_lc_over_mu_eps"] == pytest.approx(1.0, rel=1e-12)

    def test_z0_identity_eta0_over_2pi(self):
        """Z0=(1/2π)·√(μ0/(ε0·εr))·ln(b/a) 恒等式（η0=μ0·c0，SI 定义值链）。"""
        a, b, er = 25e-6, 300e-6, 5.3
        out = tgv_coax_quasi_static(a, b, 500e-6, er)
        eta0 = _MU0 * 299792458.0
        expect = eta0 / (2.0 * math.pi) / math.sqrt(er) * math.log(b / a)
        assert out["z0_ohm"] == pytest.approx(expect, rel=1e-12)

    def test_c_per_m_vs_numeric_radial_laplace(self):
        a, b, er = 25e-6, 300e-6, 5.3
        out = tgv_coax_quasi_static(a, b, 500e-6, er)
        c_num = _radial_laplace_c_per_m(a, b, er)
        assert out["c_per_length_f_per_m"] == pytest.approx(c_num, rel=1e-4)

    def test_guards(self):
        with pytest.raises(ValueError, match="r_shield_m"):
            tgv_coax_quasi_static(300e-6, 25e-6, 1e-3, 5.3)
        with pytest.raises(ValueError, match="bool"):
            tgv_coax_quasi_static(True, 300e-6, 1e-3, 5.3)


class TestRosaWireSelf:
    def test_internal_inductance_split_identity(self):
        """代数恒等式：total−(ln(2l/r)−1 外感口径) ≡ μ0·l/(8π)（内感）。"""
        length, radius = 2e-3, 20e-6
        total = rosa_wire_self_inductance_h(length, radius)
        ext_only = _MU0 * length / (2.0 * math.pi) * (
            math.log(2.0 * length / radius) - 1.0)
        assert total - ext_only == pytest.approx(
            _MU0 * length / (8.0 * math.pi), rel=1e-12)

    def test_converges_to_regularized_neumann_closed_form(self):
        """rosa total → [coincident-filament Neumann 闭式 + 内感]，l/r→∞ 收敛。"""
        for l_over_r in (100.0, 1000.0):
            radius = 5e-6
            length = l_over_r * radius
            rosa = rosa_wire_self_inductance_h(length, radius)
            quad_closed = parallel_filament_mutual_exact_h(length, radius)                 + _MU0 * length / (8.0 * math.pi)
            assert rosa == pytest.approx(quad_closed, rel=(0.005 if l_over_r == 100
                                                           else 0.001))

    def test_industry_nh_per_mm_band_unverified_rule_of_thumb(self):
        """行业经验带（25µm 金线 ~0.5-1.5 nH/mm）——UNVERIFIED 口径软基准。"""
        val = rosa_wire_self_inductance_h(1e-3, 12.5e-6) * 1e9  # nH/mm
        assert 0.5 <= val <= 1.5, val

    def test_scope_guards(self):
        with pytest.raises(ValueError, match="l/r >= 2"):
            rosa_wire_self_inductance_h(50e-6, 50e-6)
        out = tgv_isolated_inductance(200e-6, 50e-6)
        assert out["in_declared_scope"] is False  # l/r=4：弱适用域诚实标记
        assert out["l_total_ph"] > 0


class TestMutualKernels:
    def test_closed_form_vs_neumann_quadrature(self):
        for length, d in ((1e-3, 65e-6), (600e-6, 65e-6), (2e-3, 200e-6)):
            closed = parallel_filament_mutual_exact_h(length, d)
            quad = parallel_filament_mutual_quadrature_h(length, length, d)
            assert closed == pytest.approx(quad, rel=1e-9), (length, d)

    def test_quadrature_order_convergence(self):
        q40 = parallel_filament_mutual_quadrature_h(1e-3, 1e-3, 65e-6,
                                                    n_gl=40)
        q160 = parallel_filament_mutual_quadrature_h(1e-3, 1e-3, 65e-6,
                                                     n_gl=160)
        assert q40 == pytest.approx(q160, rel=1e-10)

    def test_greenhouse_transcription_converges_to_exact(self):
        """转写互感式随 l/GMD→∞ 收敛（l/GMD=20 时相对差 <0.1%）。"""
        length, g = 1.3e-3, 65e-6
        assert length / g >= 20
        m_g = greenhouse_mutual_equal_length_h(length, g)
        m_e = parallel_filament_mutual_exact_h(length, g)
        assert m_g == pytest.approx(m_e, rel=1e-3)


class TestGmd:
    def test_thin_limit_goes_to_spacing(self):
        s = 65e-6
        assert gmd_equal_strips(s / 1000.0, s) == pytest.approx(s, rel=1e-6)

    def test_concavity_and_monotonicity(self):
        s = 65e-6
        vals = [gmd_equal_strips(w, s) for w in (5e-6, 20e-6, 50e-6)]
        assert all(v < s for v in vals)
        assert vals[0] > vals[1] > vals[2]

    def test_small_width_asymptotic_expansion(self):
        """独立推导对照：GMD ≈ s·exp(−w²/(6s²))（小宽度展开，rel<1e-3）。"""
        s, w = 65e-6, 6.5e-6
        numeric = gmd_equal_strips(w, s)
        expect = s * math.exp(-(w / s) ** 2 / 6.0)
        assert numeric == pytest.approx(expect, rel=1e-3)


class TestGreenhouseSegmentSelf:
    def test_algebraic_consistency_with_mutual_family(self):
        """同系数族 (μ0/2π)：自感/互感比值为纯对数结构（无单位残留）。"""
        length, w, t = 500e-6, 50e-6, 8e-6
        val = greenhouse_segment_self_h(length, w, t)
        manual = _MU0 * length / (2.0 * math.pi) * (
            math.log(2.0 * length / (w + t)) + 0.50049
            + (w + t) / (3.0 * length))
        assert val == pytest.approx(manual, rel=1e-15)

    def test_guard(self):
        with pytest.raises(ValueError, match=r"l/\(w\+t\) >= 2"):
            greenhouse_segment_self_h(100e-6, 50e-6, 8e-6)


class TestSpiralSquareGreenhouse:
    def test_structure_identity_n1(self):
        out = spiral_square_greenhouse(1, 50e-6, 15e-6, 8e-6, 600e-6)
        assert out["n_segments"] == 4
        assert out["n_pairs_plus"] == 0
        assert out["n_pairs_minus"] == 2
        assert out["l_dc_h"] == pytest.approx(
            out["l_self_sum_h"] + out["m_plus_h"] - out["m_minus_h"], rel=1e-15)
        assert out["l_dc_h"] > 0

    def test_pair_counts_n2(self):
        out = spiral_square_greenhouse(2, 50e-6, 15e-6, 8e-6, 600e-6)
        assert out["n_segments"] == 8
        assert out["n_pairs_plus"] == 4
        assert out["n_pairs_minus"] == 8

    def test_monotonic_in_turns(self):
        l1 = spiral_square_greenhouse(1, 50e-6, 15e-6, 8e-6, 600e-6)["l_dc_h"]
        l2 = spiral_square_greenhouse(2, 50e-6, 15e-6, 8e-6, 600e-6)["l_dc_h"]
        assert l2 > l1

    def test_crosscheck_mohan_current_sheet_soft_band(self):
        """双文献模型互检（±20% 软带；各自声明误差面之和量级，非恒等式）。"""
        n, w, s, t, d_out = 3, 50e-6, 15e-6, 8e-6, 600e-6
        g = spiral_square_greenhouse(n, w, s, t, d_out)
        pitch = w + s
        d_in = d_out - 2 * n * pitch - w  # 内开档（边到边）
        m = mohan_square_current_sheet(n, d_out + w, d_in)
        assert m["l_h"] > 0 and g["l_dc_h"] > 0
        ratio = g["l_dc_h"] / m["l_h"]
        assert 0.8 <= ratio <= 1.2, (g["l_dc_h"], m["l_h"], ratio)


class TestMohan:
    def test_canonical_value_and_coeffs(self):
        out = mohan_square_current_sheet(3, 750e-6, 160e-6)
        c = out["coeffs"]
        assert (c["c1"], c["c2"], c["c3"], c["c4"]) == (1.27, 2.07, 0.18, 0.13)
        manual = 1.27 * _MU0 * 9 * out["d_avg_m"] / 2.0 * (
            math.log(2.07 / out["fill_ratio"]) + 0.18 * out["fill_ratio"]
            + 0.13 * out["fill_ratio"] ** 2)
        assert out["l_h"] == pytest.approx(manual, rel=1e-15)

    def test_guards(self):
        with pytest.raises(ValueError, match="d_in_m"):
            mohan_square_current_sheet(2, 100e-6, 200e-6)
        with pytest.raises(ValueError, match="int"):
            mohan_square_current_sheet(True, 750e-6, 160e-6)

    def test_ipd_stack_reference_verified_geometry(self):
        ref = IPD_GLASS_STACK_REFERENCE
        assert ref["source_level"] == "peer_paper_verified"
        assert ref["glass_thickness_um"] == 250.0
        assert ref["line_pitch_um"] == 15.0


class TestBumpAndMim:
    def test_bump_squat_rejected(self):
        with pytest.raises(ValueError, match="l/r >= 2"):
            bump_inductance(80e-6, 100e-6)

    def test_bump_tall_scope_flag(self):
        out = bump_inductance(200e-6, 100e-6)
        assert out["in_declared_scope"] is False
        assert out["l_total_ph"] > 0

    def test_bump_cap_scaling_identities(self):
        c1 = bump_parallel_plate_capacitance(100e-6, 50e-6, 3.4)
        c2 = bump_parallel_plate_capacitance(100e-6 * math.sqrt(2), 50e-6, 3.4)
        c3 = bump_parallel_plate_capacitance(100e-6, 25e-6, 3.4)
        assert c2["c_f"] == pytest.approx(2.0 * c1["c_f"], rel=1e-15)
        assert c3["c_f"] == pytest.approx(2.0 * c1["c_f"], rel=1e-15)

    def test_mim_scaling_and_density(self):
        c1 = mim_capacitance(50e-6 * 50e-6, 200e-9, 4.0)
        c2 = mim_capacitance(2 * 50e-6 * 50e-6, 200e-9, 4.0)
        c3 = mim_capacitance(50e-6 * 50e-6, 400e-9, 4.0)
        assert c2["c_f"] == pytest.approx(2 * c1["c_f"], rel=1e-15)
        assert c3["c_f"] == pytest.approx(c1["c_f"] / 2, rel=1e-15)
        # 50×50µm、SiN 200nm、εr=4（调用方示例值）：0.4427 pF=442.7 fF、
        # 面密度 0.1771 fF/µm² = 177083 fF/mm²
        assert c1["c_ff"] == pytest.approx(442.7094, rel=1e-3)
        assert c1["c_density_ff_per_mm2"] == pytest.approx(177083.75, rel=1e-3)


class TestRdlDesignParams:
    def test_50ohm_design_chain_self_consistent(self):
        out = rdl_design_params(
            50.0, 28.0, rdl_thickness_mm=0.02, rdl_epsilon_r=3.4)
        assert out["status"] == "ok"
        assert abs(out["z0_actual_ohm"] - 50.0) <= 0.5
        assert 0.02 <= out["width_mm"] <= 0.2

    def test_materials_are_caller_supplied(self):
        out = rdl_design_params(
            50.0, 28.0, rdl_thickness_mm=0.02, rdl_epsilon_r=3.4,
            rdl_tan_d=0.002)
        assert out["stackup_view"]["loss_tangent"] == 0.002
        with pytest.raises(ValueError):
            rdl_design_params(50.0, 28.0, rdl_thickness_mm=0.02,
                              rdl_epsilon_r=-1.0)


class TestQfnAirCavity:
    def test_first_mode_identity_c_over_2a(self):
        out = qfn_air_cavity_report(5.0, 5.0, 0.5, (35.0, 40.0))
        expect = 299792458.0 / (2.0 * 5.0e-3) / 1e9
        assert out["first_mode_ghz"] == pytest.approx(expect, rel=1e-9)
        # 方腔 (1,0,0)/(0,1,0) 简并——按 f 排序取先者
        assert out["first_mode_mnp"] in ([1, 0, 0], [0, 1, 0])

    def test_band_risk_two_state(self):
        risk = qfn_air_cavity_report(5.0, 5.0, 0.5, (29.0, 31.0))
        assert risk["verdict"] == "resonance_risk"
        assert risk["n_modes_in_band"] >= 1
        clear = qfn_air_cavity_report(5.0, 5.0, 0.5, (35.0, 40.0))
        assert clear["verdict"] == "clear"

    def test_band_guard(self):
        with pytest.raises(ValueError, match="band_ghz"):
            qfn_air_cavity_report(5.0, 5.0, 0.5, (40.0, 35.0))
