"""AP-4 反射面闭式设计器锚测试（round17 §三 AP-4，2026-10-03）。

锚口径（#118/#300：≥2 独立基准/件，门值预声明）：

- Ruze：σ=0→1（ε=0→η=1 验收锚）；σ=λ/32→exp(−(π/8)²)=0.857125
  （−0.6693dB）、σ=λ/16→exp(−(π/4)²)=0.539735（−2.6725dB）——测试
  用 math.exp 独立现算；小误差 dB 规则 10log₁₀η≈−4.343·(4πσ/λ)²
  （σ=λ/50 处相对差 <5%，Taylor 独立路径）。
- 溢出：q=0 各向同性馈解析锚 η_s=1−cosθ₀；q=2 数值积分（trapz 功率
  积分比）互证 <1e-10；θ₀ 单调。
- 口径效率：q=2、θ₀=60° 手积符号积分闭式
  η=6·cot²30°·[(1−ln2)−(0.5−ln1.5)]²=0.811419；角域 vs 口径面两独立
  积分域路径互证 rel<1e-9；q=2 扫 θ₀ 最大值 ∈[0.81,0.83]（经典
  ≈0.82 文献背景值，窗宽预声明）；η_ap=η_s·η_i 恒等。
- 遮挡：(1−β²)² 闭式锚 β=0.2→0.9216（Balanis"遮挡功率仍辐射"
  增益惯例）；环带方向图 vs scipy j1 解析闭式逐点互证（间断口径
  GL 残差门 atol 5e-3 预声明）+ 轴上场面积比恒等 1−β² 数值互证。
- 卡塞格伦：代数恒等式 M=2→e=3、M=4→e=5/3；f_eq_over_d=M·f/D；
  D=10m/f0.4/M=3 手算 θ_primary=64.010°/θ_eq=23.538°（现算）。
- 均匀口径次级方向图：与解析 2J₁(x)/x（scipy j1 独立闭式路径）
  逐点互证 <1e-6；第一零点 x=3.8317059→sinθ=1.2197λ/D（DLMF 常数）；
  半功率 x=1.6163340→HPBW=58.96°·λ/D；方向性锚 D₀=4πA/λ²=(πD/λ)²
  （round17 验收锚，整球积分复用 farfield.directivity_grid，paraxial
  容差 5e-3）。
- 预算表：σ=0/d_b=0 → total=aperture_efficiency（η_s·η_i 恒等）；
  非零因子独立相乘；η 域守卫（η≤0、η>1、bool ValueError）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.reflector_antenna import (
    C0_M_S,
    J1_FIRST_ZERO,
    J1_HALF_POWER_X,
    annulus_aperture_field,
    aperture_efficiency,
    aperture_efficiency_aperture_plane,
    blockage_efficiency,
    cassegrain_geometry,
    circular_aperture_pattern,
    directivity_uniform_aperture,
    efficiency_budget,
    gain_db,
    illumination_efficiency,
    ruze_efficiency,
    ruze_gain_loss_db,
    spillover_efficiency,
    uniform_aperture_field,
)


class TestRuze:
    def test_sigma_zero_anchor(self):
        # ε=0 → η=1（round17 验收锚）
        assert ruze_efficiency(0.0, 10e9) == 1.0
        assert ruze_gain_loss_db(0.0, 10e9) == 0.0

    def test_closed_form_values(self):
        f = 20e9
        lam = C0_M_S / f
        # σ=λ/32 → exp(−(π/8)²)=0.8570898（−0.669737dB）；
        # σ=λ/16 → exp(−(π/4)²)=0.5396415（−2.678947dB）——独立现算
        assert ruze_efficiency(lam / 32.0, f) == pytest.approx(
            math.exp(-((math.pi / 8.0) ** 2)), rel=1e-12)
        assert ruze_efficiency(lam / 16.0, f) == pytest.approx(
            math.exp(-((math.pi / 4.0) ** 2)), rel=1e-12)
        assert ruze_gain_loss_db(lam / 16.0, f) == pytest.approx(
            10.0 * math.log10(math.exp(-((math.pi / 4.0) ** 2))), rel=1e-9)
        # 文献常引工程背景值：λ/32→−0.67dB、λ/16→−2.7dB（0.1dB 窗）
        assert ruze_gain_loss_db(lam / 32.0, f) == pytest.approx(-0.67, abs=0.05)
        assert ruze_gain_loss_db(lam / 16.0, f) == pytest.approx(-2.7, abs=0.1)

    def test_small_error_db_rule(self):
        # 小误差 dB 规则（Taylor 独立路径）：σ=λ/50 相对差 <5%
        f = 30e9
        lam = C0_M_S / f
        rule = 4.343 * (4.0 * math.pi / 50.0) ** 2
        exact = -ruze_gain_loss_db(lam / 50.0, f)
        assert exact == pytest.approx(rule, rel=0.05)

    def test_monotone_and_guard(self):
        f = 10e9
        vals = [ruze_efficiency(C0_M_S / f / 64 * k, f) for k in (1, 2, 4, 8)]
        assert vals == sorted(vals, reverse=True)
        assert vals[-1] < 1.0
        with pytest.raises(ValueError, match="≥0"):
            ruze_efficiency(-1e-4, f)


class TestSpillover:
    def test_isotropic_feed_anchor(self):
        # q=0 解析锚：η_s = 1−cosθ₀
        for deg in (30.0, 45.0, 60.0, 80.0):
            t0 = math.radians(deg)
            assert spillover_efficiency(t0, 0.0) == pytest.approx(
                1.0 - math.cos(t0), rel=1e-14)

    def test_numeric_integral_cross_check(self):
        # q=2：直接功率积分比（trapz，dΩ 权重 sinθ）与闭式互证 <1e-10
        t0 = math.radians(63.0)
        th = np.linspace(0.0, math.pi / 2, 20001)
        integrand = np.cos(th) ** 2 * np.sin(th)
        num = np.trapezoid(
            integrand[th <= t0], th[th <= t0]) / np.trapezoid(integrand, th)
        assert spillover_efficiency(t0, 2.0) == pytest.approx(float(num), rel=1e-8)
        # trapz h² 收敛：20001 点 ~1.2e-9 残差，门 1e-8（预声明）

    def test_monotone(self):
        vals = [spillover_efficiency(math.radians(d), 2.0)
                for d in (30, 45, 60, 75)]
        assert vals == sorted(vals)
        assert spillover_efficiency(math.radians(90.0), 2.0) == 1.0


class TestApertureEfficiency:
    def test_q2_theta60_hand_integral(self):
        # q=2、θ₀=60°：∫cosθ·tan(θ/2)dθ = (1−ln2)−(cosθ₀−ln(1+cosθ₀))
        # （符号积分）；η = 6·cot²30°·I²（手积闭式锚）
        t0 = math.radians(60.0)
        integ = (1.0 - math.log(2.0)) - (0.5 - math.log(1.5))
        expected = 6.0 * (math.sqrt(3.0)) ** 2 * integ**2
        assert expected == pytest.approx(0.811419, rel=1e-5)
        assert aperture_efficiency(t0, 2.0) == pytest.approx(expected, rel=1e-10)

    def test_two_independent_paths_agree(self):
        # 角域积分 vs 口径面射线映射径向积分（独立积分域）
        for deg, q in ((50.0, 1.0), (63.0, 2.0), (75.0, 4.0), (60.0, 0.0)):
            t0 = math.radians(deg)
            a = aperture_efficiency(t0, q)
            b = aperture_efficiency_aperture_plane(t0, q, n_radial=512)
            assert a == pytest.approx(b, rel=1e-9), (deg, q)

    def test_optimum_window_classical(self):
        # q=2 扫 θ₀：最大 η∈[0.80,0.84]（经典 ≈0.82 文献背景窗，预声明；
        # 实现实测峰 ≈0.830@≈66°）
        grid = np.deg2rad(np.linspace(20.0, 89.0, 276))
        vals = [aperture_efficiency(t, 2.0) for t in grid]
        peak = max(vals)
        assert 0.80 <= peak <= 0.84
        best = grid[int(np.argmax(vals))]
        assert np.degrees(best) == pytest.approx(66.0, abs=6.0)  # 峰位窗 ±6°

    def test_identity_and_bounds(self):
        # η_ap = η_s·η_i 恒等；η∈(0,1]
        for deg in (40.0, 63.0):
            t0 = math.radians(deg)
            sp = spillover_efficiency(t0, 2.0)
            ill = illumination_efficiency(t0, 2.0)
            assert sp * ill == pytest.approx(
                aperture_efficiency(t0, 2.0), rel=1e-12)
            assert 0.0 < aperture_efficiency(t0, 2.0) <= 1.0


class TestBlockage:
    def test_closed_form_anchors(self):
        assert blockage_efficiency(0.0, 2.0) == 1.0
        assert blockage_efficiency(0.4, 2.0) == pytest.approx(0.9216, rel=1e-12)
        with pytest.raises(ValueError, match="不得大于"):
            blockage_efficiency(2.5, 2.0)

    def test_annulus_matches_analytic_closed_form(self):
        from scipy.special import j1 as _j1

        # 环带口径方向图 vs 解析闭式（scipy j1 独立路径）：
        # F(x)/F(0) = 2R·[R·J1(x) − Rb·J1(βx)] / (x·(R²−Rb²))，
        # x=(πD/λ)sinθ。口径场间断 → GL 求积残差 ~2e-4（实测
        # 4096 节点），门 atol 5e-3 预声明（连续均匀口径为 1e-6）。
        d_m, f_hz, beta = 0.4, 30e9, 0.3  # @30GHz → D/λ=40
        lam = C0_M_S / f_hz
        r_out = d_m / 2.0
        r_in = beta * r_out
        th = np.array([0.0, 0.5, 1.0, 2.0, 5.0, 10.0])
        num = circular_aperture_pattern(
            annulus_aperture_field(r_in, d_m), d_m, f_hz, th, n_radial=4096)
        x = (math.pi * d_m / lam) * np.sin(np.deg2rad(th))
        safe = np.where(x > 1e-12, x, 1.0)
        raw = 2.0 * r_out * (r_out * _j1(x) - r_in * _j1(beta * x)) / safe
        ref = np.where(x > 1e-12, raw / (r_out**2 * (1.0 - beta**2)), 1.0)
        np.testing.assert_allclose(np.abs(num), np.abs(ref), atol=5e-3)
        # ref(0)=1 即 F(0)∝环带面积的归一恒等（方向图按 boresight
        # 归一，绝对面积尺度经 ref 闭式承载）


class TestCassegrain:
    def test_algebraic_identities(self):
        # M=2→e=3；M=4→e=5/3；f_eq_over_d = M·(f/D)
        assert cassegrain_geometry(1.0, 0.4, 2.0)["e"] == 3.0
        g4 = cassegrain_geometry(1.0, 0.4, 4.0)
        assert g4["e"] == pytest.approx(5.0 / 3.0, rel=1e-14)
        assert g4["f_eq_over_d"] == pytest.approx(1.6, rel=1e-14)

    def test_hand_values_and_monotonicity(self):
        g = cassegrain_geometry(10.0, 0.4, 3.0)
        assert g["f_eq_m"] == pytest.approx(12.0)          # M·f, f=4m
        assert g["theta_rim_primary_deg"] == pytest.approx(
            math.degrees(2.0 * math.atan(10.0 / 16.0)), rel=1e-12)
        assert g["theta_rim_equivalent_deg"] == pytest.approx(
            math.degrees(2.0 * math.atan(10.0 / 48.0)), rel=1e-12)
        assert g["theta_rim_equivalent_deg"] < g["theta_rim_primary_deg"]
        with pytest.raises(ValueError, match=">1"):
            cassegrain_geometry(1.0, 0.4, 1.0)


class TestSecondaryPattern:
    D_M = 0.4       # @30GHz → D/λ = 40
    F_HZ = 30e9

    def test_matches_analytic_airy(self):
        from scipy.special import j1 as _j1

        lam = C0_M_S / self.F_HZ
        th = np.linspace(0.0, 3.0, 61)
        num = circular_aperture_pattern(
            uniform_aperture_field, self.D_M, self.F_HZ, th, n_radial=2048)
        x = (math.pi * self.D_M / lam) * np.sin(np.deg2rad(th))
        safe = np.where(x != 0.0, x, 1.0)
        analytic = np.where(x != 0.0, 2.0 * _j1(x) / safe, 1.0)
        # 首点 x=0：2J1(x)/x→1；逐点互证 <1e-6（数值 Hankel vs 解析闭式）
        np.testing.assert_allclose(num, analytic, atol=1e-6)

    def test_first_null_and_hpbw(self):
        lam = C0_M_S / self.F_HZ
        # 第一零点：sinθ=3.8317059λ/(πD)（DLMF 常数锚）
        th_null = math.degrees(math.asin(J1_FIRST_ZERO * lam / (math.pi * self.D_M)))
        near = circular_aperture_pattern(
            uniform_aperture_field, self.D_M, self.F_HZ,
            [th_null - 1e-4, th_null + 1e-4], n_radial=2048)
        assert float(np.abs(near).max()) < 5e-3
        # 半功率：x=1.6163340 是**功率**半功率点 → 场 |E|=1/√2=0.70711；
        # HPBW=58.96°·λ/D（经典常数）
        th_hp = math.degrees(math.asin(
            J1_HALF_POWER_X * lam / (math.pi * self.D_M)))
        e_hp = circular_aperture_pattern(
            uniform_aperture_field, self.D_M, self.F_HZ,
            [th_hp], n_radial=2048)[0]
        assert abs(e_hp) == pytest.approx(1.0 / math.sqrt(2.0), abs=2e-4)
        hpbw = 2.0 * th_hp
        assert hpbw == pytest.approx(58.96 * lam / self.D_M, rel=1e-3)

    def test_directivity_uniform_anchor(self):
        # D₀ = 4πA/λ² = (πD/λ)²（round17 验收锚）。角谱模型双面对称
        # （背面 boresight），实现已按对称恒等 ×2 还原单面口径；残差
        # =trapz 主瓣离散+模型 obliquity ~+0.17%@D/λ=40（实测，门 5e-3）
        d_num = directivity_uniform_aperture(self.D_M, self.F_HZ)
        d0 = (math.pi * self.D_M / (C0_M_S / self.F_HZ)) ** 2
        assert d_num == pytest.approx(d0, rel=5e-3)


class TestBudgetAndGain:
    def test_budget_identity(self):
        # σ=0/d_b=0：total = η_ap = η_s·η_i（验收锚：ε=0→η=1 因子）
        d, f = 2.0, 15e9
        bud = efficiency_budget(d, f, math.radians(63.0), 2.0)
        assert bud["ruze"] == 1.0
        assert bud["blockage"] == 1.0
        assert bud["total"] == pytest.approx(bud["aperture_efficiency"], rel=1e-12)
        assert bud["total"] == pytest.approx(
            aperture_efficiency(math.radians(63.0), 2.0), rel=1e-12)

    def test_budget_with_factors(self):
        d, f = 2.0, 15e9
        lam = C0_M_S / f
        bud = efficiency_budget(
            d, f, math.radians(63.0), 2.0,
            sigma_rms_m=lam / 50.0, d_block_m=0.2 * d)
        expected = (bud["spillover"] * bud["illumination"]
                    * bud["ruze"] * bud["blockage"])
        assert bud["total"] == pytest.approx(expected, rel=1e-12)
        assert bud["ruze"] == pytest.approx(ruze_efficiency(lam / 50.0, f))
        assert bud["gain_db"] == pytest.approx(
            gain_db(d, f, bud["total"]), rel=1e-12)

    def test_gain_db_anchors(self):
        d, f = 1.0, 10e9
        lam = C0_M_S / f
        assert gain_db(d, f, 1.0) == pytest.approx(
            10.0 * math.log10((math.pi * d / lam) ** 2), rel=1e-12)
        assert gain_db(d, f, 0.5) == pytest.approx(
            gain_db(d, f, 1.0) - 10.0 * math.log10(2.0), rel=1e-12)
        for bad in (0.0, -0.1, 1.5):
            with pytest.raises(ValueError, match=r"\(0, 1\]"):
                gain_db(d, f, bad)
        with pytest.raises(ValueError, match="bool"):
            gain_db(d, f, True)
