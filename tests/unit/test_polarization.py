"""AP-1 极化指标包锚测试（round17 §三 AP-1，2026-10-03）。

锚口径（#118/#300：≥2 独立基准/件，门值预声明；无文献数值表处
以闭式极限+第三数值法互证，#122 不凑绿）：

- 轴比闭式：圆极化锚 AR=1（0 dB，round17 验收锚）；线极化（δ=0/
  π/单分量）→ AR_LINEAR_DB_CAP 封顶（真值发散）；等幅 δ=45° 解析
  锚 AR=1+√2=cot(22.5°)（恒等式 |cot(δ/2)| 独立路径）。
- 第三方法：时域椭圆数值法（单周期采样 |E| max/min，与闭式零共享
  推导），6 组 (E1,E2,δ) 相对偏差 <2e-6（采样误差 (π/N)²/2 量级
  预声明）。
- 旋向：Balanis (x̂−jŷ) 同构锚——(Eθ=1, Eφ=−j)→RH、(1,+j)→LH、
  (1,0)→linear；幅度不敏感（(1,2j)→LH）。
- 倾角：E2=0→0；(2,1,0)→26.565°、(1,2,0)→63.435°（atan2 手算值）。
- Ludwig-3：主平面归约（φ=0: co=Eθ/cross=Eφ；φ=90°: co=Eφ/
  cross=−Eθ）；Huygens 源 cross≡0（<1e-12）+ co=(1+cosθ)/2 与 φ
  无关（Balanis §4.7 经典性质，同时反证符号约定）。
- XPD：纯线极化→封顶（300 dB，真值发散，round17 验收锚"XPD→∞"）；
  |co|/|cross|=2 → 6.0206 dB。
- PLF（Balanis §4.4.3 经典锚）：线对齐 1/正交 0；圆-圆同旋向 1/
  反旋向 0；圆×线 0.5（−3.0103 dB）——**反向圆=0 锚同时防共轭/
  错相实现错误**。
- 判别/异常域：classify 三段边界（含等号）；bool 拒收、负幅度/
  全零 ValueError。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.polarization import (
    AR_LINEAR_DB_CAP,
    SENSE_LH,
    SENSE_LINEAR,
    SENSE_RH,
    axial_ratio,
    axial_ratio_db,
    axial_ratio_time_domain,
    classify_cp,
    ludwig3_components,
    polarization_grids,
    polarization_loss_factor,
    polarization_state,
    sense_code,
    tilt_angle_deg,
    xpd_db,
)

_COT225 = 1.0 + math.sqrt(2.0)  # 等幅 δ=45° 轴比解析值


class TestAxialRatio:
    def test_circular_anchor_zero_db(self):
        # 圆极化锚：等幅 ±90° → AR=1（0 dB）
        assert axial_ratio(1.0, 1.0, math.pi / 2) == pytest.approx(1.0, rel=1e-14)
        assert axial_ratio(1.0, 1.0, -math.pi / 2) == pytest.approx(1.0, rel=1e-14)
        assert axial_ratio_db(3.0, 3.0, math.pi / 2) == pytest.approx(0.0, abs=1e-12)

    def test_linear_diverges_capped(self):
        cap = 10.0 ** (AR_LINEAR_DB_CAP / 20.0)
        assert axial_ratio(1.0, 0.0, 0.3) == cap
        assert axial_ratio(2.0, 1.0, 0.0) == cap  # δ=0 线极化
        assert axial_ratio(2.0, 1.0, math.pi) == cap
        assert axial_ratio_db(1.0, 0.0, 0.0) == AR_LINEAR_DB_CAP

    def test_equal_magnitude_45deg_analytic(self):
        # 等幅 δ=45°：闭式 = 1+√2 = cot(22.5°)（恒等式独立路径）
        ar = axial_ratio(1.0, 1.0, math.pi / 4)
        assert ar == pytest.approx(_COT225, rel=1e-12)
        assert ar == pytest.approx(1.0 / math.tan(math.pi / 8), rel=1e-12)

    def test_time_domain_third_method(self):
        # 第三方法互证：6 组参数，闭式 vs 时域椭圆数值（门 2e-6 预声明）
        cases = [
            (1.0, 1.0, math.pi / 2),   # 圆
            (1.0, 1.0, -math.pi / 2),
            (1.0, 1.0, math.pi / 4),   # 1+√2
            (2.0, 1.0, math.pi / 6),
            (3.0, 0.5, 2.0),
            (1.0, 2.0, -1.1),
        ]
        for m1, m2, d in cases:
            ref = axial_ratio(m1, m2, d)
            num = axial_ratio_time_domain(m1, m2, d)
            assert num == pytest.approx(ref, rel=2e-6), (m1, m2, d)

    def test_invalid_inputs(self):
        with pytest.raises(ValueError, match="全零"):
            axial_ratio(0.0, 0.0, 0.0)
        with pytest.raises(ValueError, match="≥0"):
            axial_ratio(-1.0, 1.0, 0.0)
        with pytest.raises(ValueError, match="bool"):
            axial_ratio(True, 1.0, 0.0)
        with pytest.raises(ValueError, match="有限"):
            axial_ratio(1.0, 1.0, math.inf)


class TestTilt:
    def test_anchors(self):
        assert tilt_angle_deg(1.0, 0.0, 0.7) == pytest.approx(0.0, abs=1e-12)
        # (2,1,δ=0): τ=½·atan2(4,3)=26.565°（手算值）
        assert tilt_angle_deg(2.0, 1.0, 0.0) == pytest.approx(26.5650512, rel=1e-9)
        # (1,2,δ=0): τ=½·atan2(4,−3)=63.4349°（第二象限手算值）
        assert tilt_angle_deg(1.0, 2.0, 0.0) == pytest.approx(63.4349488, rel=1e-9)
        # 等幅 ±90°：理论圆极化轴无定义，fp 噪声（cos90°=6e-17）给
        # 任意轴——只约束在 [−45,45] 界内（公式恰返 45 或 0 均合法）
        assert abs(tilt_angle_deg(1.0, 1.0, math.pi / 2)) <= 45.0 + 1e-9


class TestSense:
    def test_phasor_anchor(self):
        # Balanis (x̂−jŷ) 同构锚：Eφ 滞后 90° → RH
        assert sense_code(1.0 + 0j, -1j) == SENSE_RH
        assert sense_code(1.0 + 0j, +1j) == SENSE_LH
        assert sense_code(1.0 + 0j, 0.0 + 0j) == SENSE_LINEAR
        assert sense_code(2.0 + 0j, 1.0 + 0j) == SENSE_LINEAR  # 同相=线

    def test_magnitude_insensitive(self):
        assert sense_code(0.3 + 0j, 2.5j) == SENSE_LH
        assert sense_code(0.3 - 0.1j, 2.5j) == SENSE_LH  # 非纯圆仍判旋向


class TestPolarizationState:
    def test_consistent_with_components(self):
        st = polarization_state(2.0 + 0j, 1.0j)
        d = math.radians(st["delta_deg"])
        assert st["ar_linear"] == pytest.approx(axial_ratio(2.0, 1.0, d), rel=1e-12)
        assert st["sense_code"] == SENSE_LH
        assert st["tilt_deg"] == pytest.approx(
            tilt_angle_deg(2.0, 1.0, d), rel=1e-12)

    def test_rhcp_state(self):
        st = polarization_state(1.0 + 0j, -1j)
        assert st["sense"] == "RH"
        assert st["ar_db"] == pytest.approx(0.0, abs=1e-10)
        assert st["delta_deg"] == pytest.approx(-90.0, rel=1e-12)

    def test_all_zero_rejected(self):
        with pytest.raises(ValueError, match="全零"):
            polarization_state(0j, 0j)


class TestClassifyCp:
    def test_three_way(self):
        assert classify_cp(0.5) == "circular"
        assert classify_cp(3.0) == "circular"  # ≤ 含等号
        assert classify_cp(10.0) == "elliptical"
        assert classify_cp(20.0) == "linear"   # ≥ 含等号
        assert classify_cp(45.0) == "linear"
        assert classify_cp(3.1, circular_max_db=3.0, linear_min_db=20.0) == "elliptical"

    def test_invalid(self):
        with pytest.raises(ValueError, match="≥0"):
            classify_cp(-0.1)
        with pytest.raises(ValueError):
            classify_cp(1.0, circular_max_db=0.0)
        with pytest.raises(ValueError):
            classify_cp(1.0, circular_max_db=5.0, linear_min_db=5.0)


class TestLudwig3:
    def test_principal_plane_reduction(self):
        # φ=0：co=Eθ、cross=Eφ；φ=90°：co=Eφ、cross=−Eθ
        et, ep = 3.0 - 1.0j, 0.5 + 2.0j
        co, cr = ludwig3_components(et, ep, 0.0)
        assert co == pytest.approx(et)
        assert cr == pytest.approx(ep)
        co, cr = ludwig3_components(et, ep, 90.0)
        assert co == pytest.approx(ep)
        assert cr == pytest.approx(-et)

    def test_huygens_source_no_cross_pol(self):
        # Huygens 源锚：Eθ∝(1+cosθ)cosφ/2、Eφ∝(1+cosθ)sinφ/2
        # → co=(1+cosθ)/2（与 φ 无关）、cross≡0（<1e-12）
        th = np.deg2rad(np.linspace(0.0, 80.0, 33))
        ph = np.deg2rad(np.linspace(0.0, 2.0 * np.pi, 25, endpoint=False))
        tg, pg = np.meshgrid(th, ph, indexing="ij")
        amp = (1.0 + np.cos(tg)) / 2.0
        et = amp * np.cos(pg)
        ep = amp * np.sin(pg)
        co, cr = ludwig3_components(et, ep, np.rad2deg(pg))
        np.testing.assert_allclose(co, amp, atol=1e-12)
        assert float(np.abs(cr).max()) < 1e-12

    def test_shape_mismatch(self):
        with pytest.raises(ValueError, match="形状"):
            ludwig3_components(np.ones(3), np.ones(4), 0.0)


class TestXpd:
    def test_anchors(self):
        assert xpd_db(1.0, 0.0) == 300.0  # 线极化锚：真值发散封顶（round17）
        assert xpd_db(1.0, 0.0, divergence_cap_db=math.inf) == math.inf
        assert xpd_db(1.0, 0.5) == pytest.approx(20 * math.log10(2.0), rel=1e-12)
        assert xpd_db(2.0, 1.0) == pytest.approx(20 * math.log10(2.0), rel=1e-12)

    def test_grid_path(self):
        co = np.array([[1.0, 2.0], [0.5, 3.0]])
        cr = np.array([[0.0, 1.0], [0.5, 1.0]])
        out = xpd_db(co, cr)
        assert out[0, 0] == 300.0
        assert out[1, 1] == pytest.approx(20 * math.log10(3.0), rel=1e-12)


class TestPlf:
    def test_linear_anchors(self):
        assert polarization_loss_factor(1, 0, 0, 1, 0, 0) == pytest.approx(1.0)
        assert polarization_loss_factor(1, 0, 0, 0, 1, 0) == 0.0  # 正交线

    def test_circular_anchors(self):
        # 同旋向圆-圆 =1；反旋向 =0（防共轭/错相实现错误的关键锚；
        # 数值路径反旋向 ~1e-33 级残差，abs 门）
        assert polarization_loss_factor(
            1, 1, -math.pi / 2, 1, 1, -math.pi / 2) == pytest.approx(1.0)
        assert polarization_loss_factor(
            1, 1, -math.pi / 2, 1, 1, +math.pi / 2) == pytest.approx(
            0.0, abs=1e-20)

    def test_circular_vs_linear_half(self):
        # 圆×线 = 1/2（−3.0103 dB，Balanis 经典锚）
        plf = polarization_loss_factor(1, 1, -math.pi / 2, 1, 0, 0)
        assert plf == pytest.approx(0.5, rel=1e-12)
        plf2 = polarization_loss_factor(1, 1, math.pi / 2, 0, 1, 0)
        assert plf2 == pytest.approx(0.5, rel=1e-12)

    def test_invalid(self):
        with pytest.raises(ValueError, match="非法"):
            polarization_loss_factor(0, 0, 0, 1, 0, 0)
        with pytest.raises(ValueError, match="bool"):
            polarization_loss_factor(True, 0, 0, 1, 0, 0)


class TestGrids:
    def test_rhcp_grid(self):
        et = np.ones((4, 5))
        ep = -1j * et
        out = polarization_grids(et, ep)
        np.testing.assert_allclose(out["ar_db"], 0.0, atol=1e-10)
        assert int((out["sense_code"] == SENSE_RH).sum()) == 20

    def test_linear_grid_sense_zero(self):
        out = polarization_grids(np.ones((2, 2)), np.zeros((2, 2)))
        assert int((out["sense_code"] == SENSE_LINEAR).sum()) == 4
        # 线极化 AR 封顶 dB
        np.testing.assert_allclose(
            out["ar_db"], AR_LINEAR_DB_CAP, rtol=1e-12)

    def test_shape_mismatch(self):
        with pytest.raises(ValueError, match="不符"):
            polarization_grids(np.ones((2, 2)), np.ones((3, 2)))
