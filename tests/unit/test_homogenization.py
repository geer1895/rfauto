"""MM-7 均匀化通用内核锚树（round17 §五 :154 规格，B 流超材料）。

判据映射（任务书预声明，#118 双路径：期望一律测试内独立公式离线复算/
跨模块对照，不调被测函数拼期望）：
- depolarization 闭式：球=立方=1/3 恒等、盘 (0,0,1)/棒 (0,1/2,1/2)、
  ΣL=1 恒等（test_depolarization_*）；
- Wiener 界：端点逐位、三混合式全网格落界内、MG 形状极限=界本身
  （L=0→上界并联/L=1→下界串联）（test_wiener_*）；
- 三混合式通用核：L=1/3 实数网格与 humidity_drift 专用闭式跨模块一致
  rel≤1e-12（"提升通用核"直接证据）、Bruggeman 换相对称恒等式、
  复数无源混合 Im>0、显式拒绝面（test_mix_*）；
- Pendry 1999 SRR μ：μ(0)=1/μ(∞)=1−F 渐近锚、无损 μ(f_mp)=0 逐位、
  Re μ<0 带=(f_res,f_mp) 采样判读、Γ>0 全带 Im μ>0 无源性、双参数化
  互证、极点/非物理域显式拒绝（test_srr_*）；
- 线媒质 ωp（Pendry 1996）：a=1mm/r=1µm 手算链（测试内独立复算）、
  单调性、Drude ω=ωp 精确零点/带内 Re<0/ν>0 Im>0、a/r<2 显式拒绝
  （test_wire_media_*）；
- 等效参数反演：合成回收（测试内独立正向实现+core 正向对偶面双路径，
  roundtrip ≤1e-10/1e-12）、无耗能量恒等、自由空间恒等、支编号差
  2π/(k0d) 恒等、厚面板回绕支恢复、能量/退化域显式拒绝、service 面
  JSON 契约（test_retrieve_*）。

零随机零 IO（铁律 7/#144）：全部合成内存数据，不触真实 runs/。
"""

from __future__ import annotations

import cmath
import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import homogenization as hm
from rfauto.core.humidity_drift import (
    bruggeman_mix,
    looyenga_mix,
    maxwell_garnett_mix,
)
from rfauto.service.calculator_service import run_calculator

C0 = 299792458.0  # 测试内独立常量（#118 双路径：不 import 被测模块常量拼期望）


def _rel(a: complex, b: complex) -> float:
    return abs(a - b) / max(1.0, abs(b))


# ─── 形状族 depolarization 因子 ──────────────────────────────────────────────


class TestDepolarization:
    def test_sphere_cube_third_identity(self):
        assert hm.depolarization_factors("sphere") == (1 / 3, 1 / 3, 1 / 3)
        assert hm.depolarization_factors("cube") == (1 / 3, 1 / 3, 1 / 3)

    def test_disk_rod_limits(self):
        assert hm.depolarization_factors("disk") == (0.0, 0.0, 1.0)
        assert hm.depolarization_factors("rod") == (0.0, 0.5, 0.5)

    def test_sum_rule_identity_all_shapes(self):
        for shape in ("sphere", "cube", "disk", "rod"):
            lx, ly, lz = hm.depolarization_factors(shape)
            assert abs(lx + ly + lz - 1.0) < 1e-15, shape

    def test_unknown_shape_rejected_with_options(self):
        with pytest.raises(ValueError, match="sphere"):
            hm.depolarization_factors("tetrahedron")


# ─── Wiener 界 ────────────────────────────────────────────────────────────────


class TestWiener:
    def test_endpoints_bitwise(self):
        for v in (0.0, 1.0):
            b = hm.wiener_bounds(2.2, 7.9, v)
            want = 2.2 if v == 0.0 else 7.9
            assert b["upper_arithmetic"] == want
            assert b["lower_harmonic"] == want

    def test_harmonic_leq_arithmetic_grid(self):
        grid = [(em, ei, v)
                for em in (1.5, 2.2, 9.8)
                for ei in (2.2, 7.9, 40.0)
                for v in [i / 10 for i in range(1, 10)]]
        for em, ei, v in grid:
            b = hm.wiener_bounds(em, ei, v)
            assert b["lower_harmonic"].real <= b["upper_arithmetic"].real
            # 独立复算（#118）：调和 1/((1−v)/em+v/ei)、算术 (1−v)em+v·ei
            lo_want = 1.0 / ((1 - v) / em + v / ei)
            hi_want = (1 - v) * em + v * ei
            assert _rel(b["lower_harmonic"], lo_want) < 1e-14
            assert _rel(b["upper_arithmetic"], hi_want) < 1e-14

    def test_all_rules_inside_bounds_grid(self):
        grid = [(em, ei, v)
                for em in (1.5, 2.2, 9.8)
                for ei in (2.2, 7.9, 40.0)
                for v in [i / 10 for i in range(1, 10)]]
        for em, ei, v in grid:
            b = hm.wiener_bounds(em, ei, v)
            lo = b["lower_harmonic"].real
            hi = b["upper_arithmetic"].real
            for eff in (hm.maxwell_garnett_eff(em, ei, v),
                        hm.bruggeman_eff(ei, em, v),
                        hm.looyenga_eff(em, ei, v)):
                assert lo - 1e-12 <= eff.real <= hi + 1e-12, (em, ei, v, eff)

    def test_mg_shape_limits_are_wiener_bounds_themselves(self):
        """MG 取 L=0（沿场细棒）=上界并联、L=1（法向薄片）=下界串联。"""
        for em, ei, v in [(2.2, 7.9, 0.3), (9.8, 1.5, 0.6), (3.0, 3.0, 0.4)]:
            b = hm.wiener_bounds(em, ei, v)
            assert _rel(hm.maxwell_garnett_eff(em, ei, v, depol=0.0),
                        b["upper_arithmetic"]) < 1e-13
            assert _rel(hm.maxwell_garnett_eff(em, ei, v, depol=1.0),
                        b["lower_harmonic"]) < 1e-13

    def test_complex_input_bounds_not_ordered_honest_none(self):
        out = hm.mix_eff("maxwell_garnett", 2.2 + 0.01j, 7.9, 0.3)
        assert out["in_wiener_bounds"] is None


# ─── 三混合式通用核 ───────────────────────────────────────────────────────────

_MIX_GRID = [(em, ei, v)
             for em in (1.5, 2.2, 9.8)
             for ei in (2.2, 7.9, 40.0)
             for v in [i / 10 for i in range(1, 10)]]


class TestMixRules:
    def test_mg_sphere_matches_humidity_module(self):
        """L=1/3 与 humidity_drift 球形闭式跨模块一致（通用核提升证据）。"""
        for em, ei, v in _MIX_GRID:
            got = hm.maxwell_garnett_eff(em, ei, v, depol=1 / 3)
            want = maxwell_garnett_mix(em, ei, v)
            assert _rel(got, want) < 1e-12, (em, ei, v)

    def test_looyenga_matches_humidity_module(self):
        for em, ei, v in _MIX_GRID:
            got = hm.looyenga_eff(em, ei, v)
            want = looyenga_mix(em, ei, v)
            assert _rel(got, want) < 1e-12, (em, ei, v)

    def test_bruggeman_matches_humidity_module(self):
        """L=1/3 与 humidity_drift 闭式根一致（v 同为 phase_a 分数语义）。"""
        for em, ei, v in _MIX_GRID:
            got = hm.bruggeman_eff(ei, em, v, depol=1 / 3)
            want = bruggeman_mix(ei, em, v)
            assert _rel(got, want) < 1e-12, (em, ei, v)

    def test_bruggeman_phase_swap_symmetry(self):
        for em, ei, v in _MIX_GRID:
            a = hm.bruggeman_eff(ei, em, v, depol=1 / 3)
            b = hm.bruggeman_eff(em, ei, 1.0 - v, depol=1 / 3)
            assert _rel(a, b) < 1e-12, (em, ei, v)

    def test_endpoints_bitwise_all_rules(self):
        for v in (0.0, 1.0):
            want = 2.2 if v == 0.0 else 7.9
            assert hm.maxwell_garnett_eff(2.2, 7.9, v) == want
            assert hm.bruggeman_eff(7.9, 2.2, v) == want  # v=夹杂数
            assert hm.looyenga_eff(2.2, 7.9, v) == want

    def test_bruggeman_depolarization_zero_rejected(self):
        with pytest.raises(ValueError, match="L=0"):
            hm.bruggeman_eff(2.2, 7.9, 0.3, depol=0.0)

    def test_lossy_mixture_keeps_passive_imaginary(self):
        """无源两相（Im≥0）的混合仍无源（Im>0）——e^{−jωt} 口径小网格。"""
        for ei_im in (0.01, 0.1, 1.0):
            for v in (0.05, 0.2, 0.5):
                for rule in ("maxwell_garnett", "bruggeman", "looyenga"):
                    out = hm.mix_eff(rule, 2.2, 7.9 + ei_im * 1j, v)
                    assert out["eps_eff"].imag > 0.0, (rule, ei_im, v)

    def test_gain_inclusion_rejected(self):
        for fn in (hm.maxwell_garnett_eff, hm.looyenga_eff):
            with pytest.raises(ValueError, match="增益"):
                fn(2.2, 7.9 - 0.1j, 0.3)
        with pytest.raises(ValueError, match="增益"):
            hm.bruggeman_eff(7.9 - 0.1j, 2.2, 0.3)

    def test_nonphysical_eps_and_fraction_rejected(self):
        with pytest.raises(ValueError, match="Re>0"):
            hm.maxwell_garnett_eff(-2.2, 7.9, 0.3)
        with pytest.raises(ValueError, match="\\[0,1\\]"):
            hm.maxwell_garnett_eff(2.2, 7.9, 1.5)
        with pytest.raises(ValueError, match="bool"):
            hm.maxwell_garnett_eff(True, 7.9, 0.3)
        with pytest.raises(ValueError, match="depol"):
            hm.maxwell_garnett_eff(2.2, 7.9, 0.3, depol=1.5)

    def test_mix_eff_rule_dispatch_and_invalid(self):
        out = hm.mix_eff("looyenga", 2.2, 7.9, 0.2)
        assert out["rule"] == "looyenga"
        assert _rel(out["eps_eff"], hm.looyenga_eff(2.2, 7.9, 0.2)) == 0.0
        with pytest.raises(ValueError, match="rule"):
            hm.mix_eff("lichtenecker", 2.2, 7.9, 0.2)


# ─── Pendry 1999 SRR μ（Lorentz 形）──────────────────────────────────────────


class TestSrr:
    F_RES = 9.0
    F = 0.25
    F_MP = F_RES / math.sqrt(1.0 - F)  # 10.392304845413264

    def test_dc_limit_mu_is_one(self):
        out = hm.srr_permeability(self.F_RES * 1e-6, self.F_RES,
                                  fill_factor=self.F, gamma_ghz=0.1)
        assert abs(out["mu"] - 1.0) < 1e-9

    def test_high_frequency_limit_mu_is_one_minus_f(self):
        out = hm.srr_permeability(self.F_RES * 1e6, self.F_RES,
                                  fill_factor=self.F, gamma_ghz=0.0)
        assert abs(out["mu"] - (1.0 - self.F)) < 1e-9

    def test_lossless_mu_zero_at_mp_exact(self):
        """无损 μ(f_mp)=0 逐位（磁等离子频率零点，双参数化互证）。"""
        by_f = hm.srr_permeability(self.F_MP, self.F_RES,
                                   fill_factor=self.F, gamma_ghz=0.0)
        by_ffill = hm.srr_permeability(self.F_MP, self.F_RES,
                                       f_mp_ghz=self.F_MP, gamma_ghz=0.0)
        assert abs(by_f["mu"]) < 1e-12
        assert abs(by_ffill["mu"]) < 1e-12
        # 双参数化同 μ（F=1−(f_res/f_mp)² 反演回 F 恒等）
        assert by_ffill["fill_factor"] == pytest.approx(self.F, rel=1e-12)
        assert _rel(by_f["mu"], by_ffill["mu"]) < 1e-12

    def test_negative_mu_band_sampled(self):
        """无损 Re μ<0 带恰为 (f_res, f_mp)：带内采样全负/带外全正。"""
        inside = [self.F_RES * (1.0 + 0.001 * k) for k in range(1, 25)]
        inside += [self.F_MP * (1.0 - 0.001 * k) for k in range(1, 25)]
        for f in inside:
            out = hm.srr_permeability(f, self.F_RES, fill_factor=self.F,
                                      gamma_ghz=0.0)
            assert out["mu"].real < 0.0, f
            assert out["negative_mu"] is True
        for f in (self.F_RES * 0.9, self.F_MP * 1.1, self.F_MP * 2.0):
            out = hm.srr_permeability(f, self.F_RES, fill_factor=self.F,
                                      gamma_ghz=0.0)
            assert out["mu"].real > 0.0, f

    def test_passivity_mu_double_prime_positive_with_gamma(self):
        """Γ>0 全带 Im μ>0（arXiv 2006.13861 同式 μ″>0 保证的采样判读）。"""
        for k in range(40):
            f = self.F_RES * (0.1 + 9.9 * k / 39.0)
            out = hm.srr_permeability(f, self.F_RES, fill_factor=self.F,
                                      gamma_ghz=0.3)
            assert out["mu"].imag > 0.0, f

    def test_independent_formula_recompute(self):
        """#118 双路径：测试内独立复算 Lorentz 式（含 Γ）逐位对照。"""
        f, f0, ff, g = 9.7, self.F_RES, self.F, 0.42
        w, w0, gr = 2 * math.pi * f * 1e9, 2 * math.pi * f0 * 1e9, \
            2 * math.pi * g * 1e9
        want = 1.0 - ff * w * w / complex(w * w - w0 * w0, gr * w)
        out = hm.srr_permeability(f, f0, fill_factor=ff, gamma_ghz=g)
        assert _rel(out["mu"], want) < 1e-14

    def test_nonphysical_domains_rejected(self):
        with pytest.raises(ValueError, match="二选一"):
            hm.srr_permeability(10.0, 9.0, fill_factor=self.F,
                                f_mp_ghz=self.F_MP)
        with pytest.raises(ValueError, match="至少给一个"):
            hm.srr_permeability(10.0, 9.0)
        with pytest.raises(ValueError, match="\\(0,1\\)"):
            hm.srr_permeability(10.0, 9.0, fill_factor=1.0)
        with pytest.raises(ValueError, match="f_mp_ghz 须 >"):
            hm.srr_permeability(10.0, 9.0, f_mp_ghz=9.0)
        with pytest.raises(ValueError, match="极点"):
            hm.srr_permeability(self.F_RES, self.F_RES,
                                fill_factor=self.F, gamma_ghz=0.0)
        with pytest.raises(ValueError, match="gamma_ghz"):
            hm.srr_permeability(10.0, 9.0, fill_factor=self.F, gamma_ghz=-1.0)


# ─── Pendry 1996 线媒质等离子频率 ────────────────────────────────────────────


class TestWireMedia:
    def test_hand_computed_anchor_1mm_1um(self):
        """a=1mm、r=1µm：ωp²=2πc0²/(a²ln1000)，测试内独立复算（#118）。"""
        out = hm.wire_media_plasma(1.0, 0.001)
        ln_want = math.log(1000.0)
        wp_want = math.sqrt(
            2.0 * math.pi * C0 * C0 / ((1e-3 ** 2) * ln_want))
        assert out["ln_a_over_r"] == pytest.approx(ln_want, rel=1e-15)
        assert out["omega_p_rad_s"] == pytest.approx(wp_want, rel=1e-14)
        assert out["f_p_ghz"] == pytest.approx(wp_want / (2 * math.pi) / 1e9,
                                               rel=1e-14)
        # "extremely low frequency" 量化锚：比金属光学等离子（~1e15 Hz）
        # 低 ≥4 个量级
        assert out["f_p_ghz"] * 1e9 < 1e15 * 1e-4

    def test_monotonicity_in_lattice_and_radius(self):
        base = hm.wire_media_plasma(1.0, 0.001)["f_p_ghz"]
        bigger_a = hm.wire_media_plasma(2.0, 0.001)["f_p_ghz"]
        bigger_r = hm.wire_media_plasma(1.0, 0.002)["f_p_ghz"]
        assert bigger_a < base  # 晶格变大 → f_p 降
        assert bigger_r > base  # 线变粗 → f_p 升

    def test_drude_eps_anchors(self):
        wp = hm.wire_media_plasma(1.0, 0.001)["omega_p_rad_s"]
        fp = wp / (2.0 * math.pi)
        # ω=ωp 精确零点（ν=0）
        at_p = hm.wire_media_plasma(1.0, 0.001, freq_ghz=fp / 1e9)
        assert abs(at_p["eps"]) < 1e-9
        # ω<ωp → Re ε<0（等离子体判据，ν=0）
        below = hm.wire_media_plasma(1.0, 0.001, freq_ghz=0.5 * fp / 1e9)
        assert below["eps"].real < 0.0
        assert below["negative_eps"] is True
        # ω>ωp → 0<Re ε<1（渐近 1）
        above = hm.wire_media_plasma(1.0, 0.001, freq_ghz=2.0 * fp / 1e9)
        assert 0.0 < above["eps"].real < 1.0
        # ν>0 → Im ε>0（e^{−jωt} 无损正性）
        lossy = hm.wire_media_plasma(1.0, 0.001, freq_ghz=0.5 * fp / 1e9,
                                     nu_rad_s=1e9)
        assert lossy["eps"].imag > 0.0

    def test_no_freq_report_is_compact(self):
        out = hm.wire_media_plasma(1.0, 0.001)
        assert "eps" not in out and "negative_eps" not in out

    def test_sparse_and_geometry_domains_rejected(self):
        with pytest.raises(ValueError, match="a/r"):
            hm.wire_media_plasma(1.0, 0.6)  # a/r<2 稀疏口径失效
        with pytest.raises(ValueError, match="< lattice_mm"):
            hm.wire_media_plasma(1.0, 1.0)  # r≥a
        with pytest.raises(ValueError, match="nu_rad_s"):
            hm.wire_media_plasma(1.0, 0.001, nu_rad_s=-1.0)


# ─── 等效参数反演 ────────────────────────────────────────────────────────────


def _forward_reference(f_ghz: float, n: complex, z: complex,
                       d_mm: float) -> tuple[complex, complex]:
    """测试内独立正向实现（#118 双路径：不调 core slab_panel_rt 拼期望）。"""
    k0 = 2.0 * math.pi * f_ghz * 1e9 / C0
    gamma = (z - 1.0) / (z + 1.0)
    tau = cmath.exp(1j * k0 * n * (d_mm * 1e-3))
    den = 1.0 - gamma * gamma * tau * tau
    s11 = gamma * (1.0 - tau * tau) / den
    s21 = tau * (1.0 - gamma * gamma) / den
    return s11, s21


class TestRetrieve:
    N_TRUE = 2.5 + 0.08j
    Z_TRUE = 1.3
    F_GHZ = 10.0
    D_MM = 1.5

    def test_synthetic_recovery_reference_path(self):
        s11, s21 = _forward_reference(self.F_GHZ, self.N_TRUE, self.Z_TRUE,
                                      self.D_MM)
        out = hm.retrieve_eff_params(self.F_GHZ, s11, s21, self.D_MM)
        assert _rel(out["n_eff"], self.N_TRUE) < 1e-10
        assert _rel(out["z_eff"], self.Z_TRUE) < 1e-10
        assert _rel(out["eps_eff"], self.N_TRUE / self.Z_TRUE) < 1e-10
        assert _rel(out["mu_eff"], self.N_TRUE * self.Z_TRUE) < 1e-10

    def test_roundtrip_core_forward_grid(self):
        """core 正向对偶面往返（无损面板 |S11|²+|S21|²=1 恒等顺带钉）。"""
        for n in (1.5 + 0.0j, 2.5 + 0.08j, 3.2 - 0.0j):
            for z in (0.8, 1.0, 1.6):
                for d in (0.3, 1.0):
                    panel = hm.slab_panel_rt(self.F_GHZ, n, z, d)
                    s11, s21 = panel["s11"], panel["s21"]
                    if n.imag == 0.0:
                        energy = abs(s11) ** 2 + abs(s21) ** 2
                        assert abs(energy - 1.0) < 1e-12, (n, z, d)
                    out = hm.retrieve_eff_params(self.F_GHZ, s11, s21, d)
                    assert _rel(out["n_eff"], n) < 1e-12, (n, z, d)
                    assert _rel(out["z_eff"], z) < 1e-12, (n, z, d)

    def test_free_space_identity(self):
        s11, s21 = _forward_reference(self.F_GHZ, 1.0 + 0.0j, 1.0, 1.0)
        assert abs(s11) < 1e-16
        out = hm.retrieve_eff_params(self.F_GHZ, s11, s21, 1.0)
        assert _rel(out["n_eff"], 1.0 + 0.0j) < 1e-12
        assert _rel(out["z_eff"], 1.0 + 0.0j) < 1e-12

    def test_branch_ladder_identity_2pi_over_k0d(self):
        """相邻支差恒等式：n(m+1)−n(m) = 2π/(k0·d)。"""
        s11, s21 = _forward_reference(self.F_GHZ, self.N_TRUE, self.Z_TRUE,
                                      self.D_MM)
        m0 = hm.retrieve_eff_params(self.F_GHZ, s11, s21, self.D_MM, 0)
        m1 = hm.retrieve_eff_params(self.F_GHZ, s11, s21, self.D_MM, 1)
        k0d = 2.0 * math.pi * self.F_GHZ * 1e9 / C0 * (self.D_MM * 1e-3)
        assert _rel(m1["n_eff"] - m0["n_eff"], 2 * math.pi / k0d) < 1e-9

    def test_thick_panel_branch_recovery(self):
        """k0·n·d>π 相位回绕：主枝给负 n（歧义），branch_m=1 恢复真值。"""
        n_thick, d_mm = 8.0 + 0.05j, 3.0
        s11, s21 = _forward_reference(self.F_GHZ, n_thick, self.Z_TRUE, d_mm)
        m0 = hm.retrieve_eff_params(self.F_GHZ, s11, s21, d_mm, 0)
        m1 = hm.retrieve_eff_params(self.F_GHZ, s11, s21, d_mm, 1)
        assert m0["n_eff"].real < 0.0  # 主枝歧义如实（负折射假象）
        assert _rel(m1["n_eff"], n_thick) < 1e-9
        # Z 与支编号无关
        assert _rel(m0["z_eff"], self.Z_TRUE) < 1e-9
        assert _rel(m1["z_eff"], self.Z_TRUE) < 1e-9

    def test_amplifying_panel_rejected(self):
        with pytest.raises(ValueError, match="放大"):
            hm.retrieve_eff_params(self.F_GHZ, 0.1 + 0.0j, 1.2 + 0.0j, 1.0)

    def test_degenerate_denominator_rejected(self):
        with pytest.raises(ValueError, match="退化"):
            hm.retrieve_eff_params(self.F_GHZ, 0.5 + 0.0j, 0.5 + 0.0j, 1.0)

    def test_full_stopband_tau_zero_rejected(self):
        with pytest.raises(ValueError, match="全阻带"):
            hm.retrieve_eff_params(self.F_GHZ, 0.0, 0.0, 1.0)

    def test_branch_type_and_geometry_guards(self):
        s11, s21 = _forward_reference(self.F_GHZ, self.N_TRUE, self.Z_TRUE,
                                      self.D_MM)
        with pytest.raises(ValueError, match="整数"):
            hm.retrieve_eff_params(self.F_GHZ, s11, s21, self.D_MM, True)
        with pytest.raises(ValueError, match="整数"):
            hm.retrieve_eff_params(self.F_GHZ, s11, s21, self.D_MM, 0.5)
        with pytest.raises(ValueError, match="正有限"):
            hm.retrieve_eff_params(self.F_GHZ, s11, s21, 0.0)


# ─── 注册面 service 契约（JSON 进出，薄壳消费）────────────────────────────────


class TestRegisteredServiceFace:
    def test_four_keys_json_roundtrip(self):
        rows = [
            ("homog_mix_eff", {"rule": "maxwell_garnett", "er_matrix": 2.2,
                               "er_inclusion": 7.9, "v_inclusion": 0.2}),
            ("srr_permeability", {"freq_ghz": 9.7, "f_res_ghz": 9.0,
                                  "fill_factor": 0.25, "gamma_ghz": 0.15}),
            ("wire_media_plasma", {"lattice_mm": 1.0, "wire_radius_mm": 0.001,
                                   "freq_ghz": 30.0}),
            ("retrieve_eff_params", {
                "freq_ghz": 10.0,
                "s11": [0.06957524811418508, -0.10918571421118077],
                "s21": [0.8367140124355552, 0.4996562934142499],
                "thickness_mm": 1.0, "branch_m": 0}),
        ]
        for name, params in rows:
            out = run_calculator(name, params)
            assert out["ok"], (name, out)
            json.dumps(out, allow_nan=False)  # JSON 契约（NaN/Inf 禁入）

    def test_retrieve_service_matches_core_direct(self):
        s11 = [0.06957524811418508, -0.10918571421118077]
        s21 = [0.8367140124355552, 0.4996562934142499]
        out = run_calculator("retrieve_eff_params", {
            "freq_ghz": 10.0, "s11": s11, "s21": s21,
            "thickness_mm": 1.0, "branch_m": 0})
        direct = hm.retrieve_eff_params(10.0, complex(*s11), complex(*s21),
                                        1.0, 0)
        assert out["result"]["n_eff"] == [direct["n_eff"].real,
                                          direct["n_eff"].imag]
        eps_want = complex(2.5, 0.08) / 1.3  # 该 (S11,S21) 的真值面板
        assert out["result"]["eps_eff"] == pytest.approx(
            [eps_want.real, eps_want.imag], abs=1e-12)

    def test_homog_mix_service_rejects_bad_rule(self):
        out = run_calculator("homog_mix_eff", {
            "rule": "lichtenecker", "er_matrix": 2.2, "er_inclusion": 7.9,
            "v_inclusion": 0.2})
        assert out["ok"] is False and out.get("error")
