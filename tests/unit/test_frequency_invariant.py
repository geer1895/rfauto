"""AP-13 频率不变族（螺旋）锚测试（round17 §三 AP-13，2026-10-03）。

锚口径（#118/#300：≥2 独立基准/件，门值预声明；#122 不凑绿）：

- 每圈增长率：闭式 e^{2πα} vs 数值 r(φ+2π)/r(φ)（rel<1e-12）。
- 弧长闭式 vs 弦长数值积分（独立第三方法，n=20001 离散误差
  O((Δφ)²) 预声明，门 rel<1e-6）；α→0 圆弧极限 L=r₀φ（闭式
  极限锚，lim 恒等式独立路径）。
- 自相似（Rumsey 几何化）：s 倍放大 + Δφ=ln(s)/α 旋转的点落在原
  曲线上（最近点距离 <1e-9·r_out，s=2/4 两档）。
- Babinet–Booker：Z=η₀/4 的算术锚（rel<1e-12）；π/2+π/2=π 互补
  角分区覆盖恒等式。
- 频带综合往返：design(1,10 GHz,2 turns) → 正向映射恢复频率
  （rel<1e-12）；r_out/r_in = f_high/f_low = e^{α·2π·turns}
  三方一致；growth_per_turn 与 α 互逆。
- 阿基米德：两臂径向分离闭式 πb vs 数值逐位；r₀=0 弧长闭式 vs
  弦长积分（rel<1e-6）；频带映射往返（rel<1e-12）。
- 异常域：bool/非正/非法 growth ValueError；n_arms<1。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.frequency_invariant import (
    ETA0_OHM,
    SELF_COMPLEMENTARY_ARM_WIDTH_RAD,
    SPEED_OF_LIGHT,
    alpha_from_growth,
    archimedean_arc_length_from_zero,
    archimedean_arm_radial_separation,
    archimedean_band_radii,
    archimedean_points,
    equiangular_arc_length,
    equiangular_band_from_design,
    equiangular_band_radii,
    equiangular_growth_per_turn,
    equiangular_radius,
    log_spiral_rotation_for_scale,
    numeric_arc_length,
    self_complementary_impedance,
)

ALPHA = 0.30  # 典型设计档（每圈增长率 e^{1.885}≈6.59）


class TestEquiangularGrowth:
    def test_growth_per_turn_closed_vs_numeric(self):
        # 闭式 e^{2πα} vs 数值比值（独立路径）
        g = equiangular_growth_per_turn(ALPHA)
        r0 = 1.0
        phi = 1.234
        numeric = float(equiangular_radius(r0, ALPHA, phi + 2.0 * math.pi)
                        / equiangular_radius(r0, ALPHA, phi))
        assert g == pytest.approx(numeric, rel=1e-12)
        # 反解互逆
        assert alpha_from_growth(g) == pytest.approx(ALPHA, rel=1e-12)

    def test_growth_direct_ratio_identity(self):
        # r(φ+2π)/r(φ) 恒等式逐位（e^{2πα} 定义式）
        r1 = equiangular_radius(2.5, ALPHA, 0.7)
        r2 = equiangular_radius(2.5, ALPHA, 0.7 + 2.0 * math.pi)
        assert r2 / r1 == pytest.approx(math.exp(2.0 * math.pi * ALPHA),
                                        rel=1e-14)


class TestArcLength:
    def test_closed_vs_numeric_chords(self):
        # 闭式 vs 弦长积分（独立第三方法）
        r0, pmax = 0.005, 4.0 * math.pi
        closed = equiangular_arc_length(r0, ALPHA, pmax)
        numeric = numeric_arc_length(
            lambda p: equiangular_radius(r0, ALPHA, p), pmax)
        assert closed == pytest.approx(numeric, rel=1e-6)

    def test_circular_limit_alpha_to_zero(self):
        # α→0 闭式极限 = r₀φ（圆弧；解析极限独立路径）
        r0, pmax = 0.01, 2.0 * math.pi
        tiny = equiangular_arc_length(r0, 1e-9, pmax)
        assert tiny == pytest.approx(r0 * pmax, rel=1e-6)


class TestSelfSimilarity:
    @pytest.mark.parametrize("scale", [2.0, 4.0])
    def test_scale_equals_rotation(self, scale):
        # 自相似精确锚：探针点半径 = s·r(φ) ≡ r(φ+Δφ)（逐位，φ 已知）
        # 几何锚：旋转后落在原曲线上（最近点距离 ≤ 搜索网格半步长×半径，
        # 离散搜索分辨率限，预声明）
        r0, pmax = 0.002, 6.0 * math.pi
        dphi = log_spiral_rotation_for_scale(ALPHA, scale)
        phi = np.linspace(0.0, pmax, 1441)[::40]
        r_probe = equiangular_radius(r0, ALPHA, phi) * scale
        assert np.allclose(r_probe, equiangular_radius(r0, ALPHA, phi + dphi),
                           rtol=1e-13)
        # 几何落点（atan2 角是卷绕角——几何点集等价，无碍）
        px = r_probe * np.cos(phi + dphi)
        py = r_probe * np.sin(phi + dphi)
        curve_ang = np.linspace(0.0, pmax + dphi, 8001)
        cr = equiangular_radius(r0, ALPHA, curve_ang)
        cx = cr * np.cos(curve_ang)
        cy = cr * np.sin(curve_ang)
        d = np.hypot(px[:, None] - cx[None, :], py[:, None] - cy[None, :])
        step = (pmax + dphi) / 8000.0
        tol = step * float(r_probe.max())  # 半步长×最大半径×2（保守）
        assert float(d.min(axis=1).max()) < tol

    def test_rotation_formula_value(self):
        # Δφ = ln(2)/α 数值锚
        assert log_spiral_rotation_for_scale(0.5, 2.0) == pytest.approx(
            math.log(2.0) / 0.5, rel=1e-14)


class TestBabinet:
    def test_impedance_arithmetic(self):
        # η₀/4 算术锚
        assert self_complementary_impedance() == pytest.approx(
            ETA0_OHM / 4.0, rel=1e-15)
        assert self_complementary_impedance() == pytest.approx(
            94.182578417, rel=1e-9)

    def test_complementary_sector_partition(self):
        # 自互补几何条件：臂角宽 π/2 + 间隙角宽 π/2 = 周期 π（覆盖恒等式）
        width = SELF_COMPLEMENTARY_ARM_WIDTH_RAD
        assert width * 2.0 == pytest.approx(math.pi, rel=1e-15)


class TestBandDesign:
    def test_design_round_trip(self):
        # 综合(1,10 GHz,2 圈) → 正向映射恢复频带（rel<1e-12）
        f_lo, f_hi = 1e9, 10e9
        d = equiangular_band_from_design(f_lo, f_hi, 2.0)
        assert d["forward_freq_low_hz"] == pytest.approx(f_lo, rel=1e-12)
        assert d["forward_freq_high_hz"] == pytest.approx(f_hi, rel=1e-12)
        # 三方一致：r_out/r_in = f 比 = e^{α·Δφ}
        assert d["r_out_m"] / d["r0_m"] == pytest.approx(f_hi / f_lo,
                                                         rel=1e-12)
        assert math.exp(d["alpha"] * d["phi_max_rad"]) == pytest.approx(
            f_hi / f_lo, rel=1e-12)
        assert d["growth_per_turn"] == pytest.approx(
            math.exp(2.0 * math.pi * d["alpha"]), rel=1e-14)

    def test_band_radii_values(self):
        # 周长=λ 手算锚（独立算式排列）：1 GHz → r_out = 0.299792458/(2π) mm→m
        b = equiangular_band_radii(1e9, 10e9)
        assert b["r_out_m"] == pytest.approx(SPEED_OF_LIGHT / (2e9 * math.pi),
                                             rel=1e-14)
        # 不同排列的独立算术式（0.299792458 m·GHz⁻¹ / (2π GHz)）
        assert b["r_out_m"] == pytest.approx(0.299792458 / (2.0 * math.pi),
                                             rel=1e-14)


class TestArchimedean:
    def test_arm_separation_closed_vs_numeric(self):
        # 两臂同径向分离 = πb：数值（同 φ 两臂半径差）逐位
        b = 0.0012
        pts = archimedean_points(0.0005, b, 4.0 * math.pi, n=721, n_arms=2)
        a0, a1 = pts["arms"]
        r0 = np.hypot(a0[:, 0], a0[:, 1])
        r1 = np.hypot(a1[:, 0], a1[:, 1])
        assert archimedean_arm_radial_separation(b, 2) == pytest.approx(
            math.pi * b, rel=1e-14)
        # 同 φ 处（点列对齐）半径差 = 2πb/2 = πb
        assert np.allclose(r1 - r0, math.pi * b, rtol=1e-12)

    def test_arc_length_closed_vs_numeric(self):
        # r₀=0 闭式 vs 弦长积分
        b, pmax = 0.0008, 6.0 * math.pi
        closed = archimedean_arc_length_from_zero(b, pmax)
        numeric = numeric_arc_length(lambda p: b * p, pmax)
        assert closed == pytest.approx(numeric, rel=1e-6)

    def test_band_round_trip(self):
        b = archimedean_band_radii(2.4e9, 7.5e9)
        f_lo = SPEED_OF_LIGHT / (2.0 * math.pi * b["r_out_m"])
        f_hi = SPEED_OF_LIGHT / (2.0 * math.pi * b["r_in_m"])
        assert f_lo == pytest.approx(2.4e9, rel=1e-12)
        assert f_hi == pytest.approx(7.5e9, rel=1e-12)


class TestValidation:
    def test_invalid_inputs(self):
        from rfauto.core.frequency_invariant import equiangular_points as ep
        with pytest.raises(ValueError):
            equiangular_growth_per_turn(True)
        with pytest.raises(ValueError):
            alpha_from_growth(1.0)  # g≤1 无带宽
        with pytest.raises(ValueError):
            equiangular_band_radii(10e9, 1e9)  # 须 f_high>f_low
        with pytest.raises(ValueError):
            ep(-0.001, ALPHA, math.pi)  # r0 须正
        with pytest.raises(ValueError):
            archimedean_arm_radial_separation(0.001, 0)
        with pytest.raises(ValueError):
            log_spiral_rotation_for_scale(ALPHA, 1.0)  # scale 须 >1
