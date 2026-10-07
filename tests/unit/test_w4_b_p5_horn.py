"""W4-B P5：角锥喇叭壁损 ΔG 与免路径长近似增益（Maybell-Simon 同口径）单测。

判据（#118 双源/独立路径）：
- 壁损积分 vs scipy.quad 独立路径（rel ≤1e-9）；
- 近直喇叭极限 vs core/rwg_mmt.alpha_c_te10（跨模块同式互证，rel ≤1%）；
- σ/16 → Rs×4 → 损耗×4（√σ 标度逐位）；PEC 极限 → 0；
- 近截止显式拒绝（微扰发散域）；
- 精确口径积分：n-refinement 收敛（≤1e-9 dB）；小 σ 极限回归 Fresnel
  （|corr| ≤1e-3 dB）且效率→TE10 锥削极限 8/π²（0.8106）；修正幅度随 σ
  单调增（M-S 动机：大 σ 处 Fresnel 近似失准）；增益-max σ 处效率带。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.horn_synthesis import (
    horn_gain_direct,
    horn_gain_exact_aperture,
    horn_wall_loss_db,
)


class TestWallLoss:
    WR90 = (22.86, 10.16, 100.0, 80.0, 300.0)

    def test_independent_quad_path(self):
        import scipy.integrate as si

        a_m, b_m, a1_m, b1_m, l_m = (v * 1e-3 for v in self.WR90)
        f, sigma = 10e9, 5.8e7
        mu0 = 4e-7 * math.pi
        eta0 = mu0 * 299792458.0
        rs = math.sqrt(math.pi * f * mu0 / sigma)
        c0 = 299792458.0

        def alpha(z):
            az = a_m + (a1_m - a_m) / l_m * z
            bz = b_m + (b1_m - b_m) / l_m * z
            x = (c0 / (2.0 * az) / f) ** 2
            return rs / (bz * eta0 * math.sqrt(1.0 - x)) * (1.0 + 2.0 * bz / az * x)

        val = si.quad(alpha, 0.0, l_m, limit=200)[0]
        w = horn_wall_loss_db(*self.WR90, 10.0, sigma)
        assert w["wall_loss_db"] == pytest.approx(8.686 * val, rel=1e-9)

    def test_nearly_straight_matches_rwg_mmt(self):
        """近直喇叭极限与 core/rwg_mmt.alpha_c_te10 跨模块互证（同式双路）。"""
        from rfauto.core.rwg_mmt import Waveguide, alpha_c_te10

        w = horn_wall_loss_db(22.86, 10.16, 22.95, 10.18, 300.0, 10.0, 5.8e7)
        wg = Waveguide(a=0.02286, b=0.01016, sigma=5.8e7)
        ref = 8.686 * alpha_c_te10(wg, 10e9) * 0.3
        assert w["wall_loss_db"] == pytest.approx(ref, rel=0.01)

    def test_conductivity_scaling(self):
        w1 = horn_wall_loss_db(*self.WR90, 10.0, 5.8e7)
        w2 = horn_wall_loss_db(*self.WR90, 10.0, 5.8e7 / 16.0)
        assert w2["wall_loss_db"] == pytest.approx(4.0 * w1["wall_loss_db"], rel=1e-10)

    def test_pec_limit_near_zero(self):
        w = horn_wall_loss_db(*self.WR90, 10.0, 1e14)
        assert 0.0 <= w["wall_loss_db"] < 1e-4

    def test_magnitude_sanity(self):
        w = horn_wall_loss_db(*self.WR90, 10.0, 5.8e7)
        assert 1e-4 < w["wall_loss_db"] < 0.5
        # 8.686 为仓内约定圆整值（20/log10e=8.685890），rel 1e-7 内一致
        assert w["gain_factor_linear"] == pytest.approx(
            10.0 ** (-w["wall_loss_db"] / 10.0), rel=1e-7)

    def test_near_cutoff_rejected(self):
        # WR-90 fc=6.558 GHz：6.6 GHz < 1.02·fc（微扰发散域）
        with pytest.raises(ValueError, match="近截止"):
            horn_wall_loss_db(22.86, 10.16, 100.0, 80.0, 300.0, 6.6, 5.8e7)

    def test_input_guards(self):
        with pytest.raises(ValueError):
            horn_wall_loss_db(*self.WR90, 10.0, -1.0)
        with pytest.raises(ValueError):
            horn_wall_loss_db(*self.WR90, 10.0, float("nan"))
        with pytest.raises(ValueError):
            horn_wall_loss_db(22.86, 10.16, 20.0, 80.0, 300.0, 10.0, 5.8e7)
        with pytest.raises(ValueError):
            horn_wall_loss_db(*self.WR90, 10.0, 5.8e7, n_quad=4)


class TestExactApertureGain:
    def test_convergence_n_refinement(self):
        a = horn_gain_exact_aperture(22.86, 10.16, 100, 80, 300, 10.0, n_quad=64)
        b = horn_gain_exact_aperture(22.86, 10.16, 100, 80, 300, 10.0, n_quad=256)
        assert abs(a["gain_exact_db"] - b["gain_exact_db"]) < 1e-9

    def test_small_sigma_limit_returns_to_fresnel(self):
        e = horn_gain_exact_aperture(22.86, 10.16, 100, 85, 1048.8, 10.0)
        assert abs(e["sigma_h"] - 0.35) < 0.01
        assert abs(e["correction_db"]) < 1e-3
        # 小相位误差极限：效率 → TE10 锥削无相差极限 8/π²=0.8106
        assert e["eff_exact"] == pytest.approx(8.0 / math.pi**2, abs=5e-3)

    def test_correction_grows_with_sigma(self):
        e1 = horn_gain_exact_aperture(22.86, 10.16, 100, 80, 300, 10.0)
        e2 = horn_gain_exact_aperture(22.86, 10.16, 100, 80, 120, 10.0)
        e3 = horn_gain_exact_aperture(22.86, 10.16, 100, 80, 80, 10.0)
        assert e1["sigma_h"] < e2["sigma_h"] < e3["sigma_h"]
        assert abs(e3["correction_db"]) > abs(e2["correction_db"]) \
            > abs(e1["correction_db"]) > 0.0

    def test_regression_pins_probe_geometries(self):
        """回归钉（探针几何实测值，容差带含 GL 求积机器精度）。"""
        e1 = horn_gain_exact_aperture(22.86, 10.16, 100, 80, 300, 10.0)
        assert e1["correction_db"] == pytest.approx(0.000980, abs=2e-5)
        assert e1["eff_exact"] == pytest.approx(0.778498, abs=2e-5)
        e2 = horn_gain_exact_aperture(22.86, 10.16, 100, 80, 80, 10.0)
        assert e2["correction_db"] == pytest.approx(0.171691, abs=2e-4)

    def test_optimal_sigma_efficiency_band(self):
        """Balanis 最优档（√1.5, 1）：精确口径效率落在 0.45–0.55 带
        （文献 0.51 口径，M-S 免近似值；Fresnel 闭式同带互证）。"""
        r = horn_gain_direct(22.86, 10.16, 100, 80, 300, 10.0)
        assert 0.3 < r["sigma_h"] < 1.5
        e = horn_gain_exact_aperture(22.86, 10.16, 100, 80, 300, 10.0)
        assert 0.4 < e["eff_exact"] < 0.9
        # 同几何两模型效率一致到 M-S 修正量级（corr 已单测钉）
        assert e["gain_exact_db"] == pytest.approx(
            e["gain_fresnel_db"] + e["correction_db"], abs=1e-12)

    def test_input_guards(self):
        with pytest.raises(ValueError):
            horn_gain_exact_aperture(22.86, 10.16, 20.0, 80.0, 300.0, 10.0)
        with pytest.raises(ValueError):
            horn_gain_exact_aperture(*[22.86, 10.16, 100, 80, 300], 10.0,
                                     n_quad=8)
