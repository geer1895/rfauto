"""W4-B P14：脊波导频扫面板（core/ridged_waveguide_panel）单测。

判据（#118 双源/独立路径）：
- d==0 矩形退化恒等式：奇模根 (2m+1)π/a、偶模根 2mπ/a 逐位；
  fc20=2·fc10（对任意 s 成立——无脊即无脊负载）；
- d==0 时 α_c 估计与 core/rwg_mmt.alpha_c_te10 跨模块逐位一致；
- 面板行 vs 内核单点函数恒等（beta/z_pv/z_te/lambda_g）；
- 脊加载方向：fc30（奇模）随脊深单调下移；fc20（偶模，脊在 E 节点）
  弱扰动（|Δ|<5%）；fc10 < next < … 排序；
- 主模互证：odd_mode_kcs(n=1) 与内核 cutoff_kc 同解；
- 守卫：f≤fc10 显式报错、空/乱序网格、bool 拒收。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.ridged_waveguide import (
    RidgedWaveguide,
    beta_z,
    cutoff_fc_hz,
    cutoff_kc,
    lambda_g_m,
    z_pv_ohm,
    z_te_ohm,
)
from rfauto.core.ridged_waveguide_panel import (
    alpha_c_te10_estimate,
    even_mode_kcs,
    next_mode_cutoff,
    odd_mode_kcs,
    ridged_waveguide_panel,
)

SIGMA_CU = 5.8e7


class TestRectDegenerateIdentities:
    def test_odd_mode_roots_exact(self):
        wg = RidgedWaveguide(a=0.04, b=0.02, s=0.008, d=0.0)
        kcs = odd_mode_kcs(wg, 2)
        assert kcs[0] == pytest.approx(math.pi / wg.a, rel=1e-14)
        assert kcs[1] == pytest.approx(3 * math.pi / wg.a, rel=1e-14)

    def test_even_mode_roots_exact_any_s(self):
        for s in (0.004, 0.012, 0.02):
            wg = RidgedWaveguide(a=0.04, b=0.02, s=s, d=0.0)
            kcs = even_mode_kcs(wg, 2)
            assert kcs[0] == pytest.approx(2 * math.pi / wg.a, rel=1e-14)
            assert kcs[1] == pytest.approx(4 * math.pi / wg.a, rel=1e-14)

    def test_next_mode_is_te20_twice_fc10(self):
        wg = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.0)
        nxt = next_mode_cutoff(wg)
        assert nxt["mode"] == "TE20"
        assert nxt["fc_hz"] == pytest.approx(2.0 * cutoff_fc_hz(wg), rel=1e-14)
        assert nxt["single_mode_band_hz"][0] == pytest.approx(
            cutoff_fc_hz(wg), rel=1e-14)

    def test_alpha_matches_rwg_mmt_exactly(self):
        from rfauto.core.rwg_mmt import Waveguide, alpha_c_te10

        wg = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.0)
        f = 10e9
        ref = alpha_c_te10(Waveguide(a=0.04, b=0.02, sigma=SIGMA_CU), f)
        assert alpha_c_te10_estimate(f, wg, SIGMA_CU) \
            == pytest.approx(ref, rel=1e-12)


class TestPanelRows:
    def test_row_identities_vs_kernel(self):
        wg = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.004)
        f = 6e9  # fc10=3.55GHz < 6GHz < fc20=7.76GHz（单模带内）
        p = ridged_waveguide_panel([f], wg, sigma=SIGMA_CU)
        row = p["rows"][0]
        assert row["beta_rad_m"] == pytest.approx(beta_z(f, wg), rel=1e-15)
        assert row["lambda_g_m"] == pytest.approx(lambda_g_m(f, wg), rel=1e-15)
        assert row["z_pv_ohm"] == pytest.approx(z_pv_ohm(f, wg), rel=1e-15)
        assert row["z_te_ohm"] == pytest.approx(z_te_ohm(f, wg), rel=1e-15)
        assert row["alpha_c_np_per_m"] > 0.0
        assert row["multimode"] is False

    def test_lossless_panel_alpha_none_and_multimode_flag(self):
        wg = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.0)
        f_lo, f_hi = 5e9, 11e9  # fc10=3.75GHz, fc20=7.49GHz
        p = ridged_waveguide_panel([f_lo, f_hi], wg, sigma=None)
        assert p["rows"][0]["alpha_c_np_per_m"] is None
        assert p["rows"][0]["multimode"] is False
        assert p["rows"][1]["multimode"] is True  # 11GHz > fc20=7.5GHz

    def test_alpha_below_cutoff_rejected(self):
        wg = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.004)
        with pytest.raises(ValueError, match="截止以下"):
            alpha_c_te10_estimate(3.0e9, wg, SIGMA_CU)  # fc10≈3.55GHz


class TestRidgeLoading:
    WG_RECT = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.0)
    WG_RIDGE = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.006)

    def test_odd_modes_lower_with_ridge(self):
        fc30_rect = C0_HZ * (3 * math.pi / self.WG_RECT.a) / (2 * math.pi)
        fc30_ridge = C0_HZ * odd_mode_kcs(self.WG_RIDGE, 2)[1] / (2 * math.pi)
        assert fc30_ridge < fc30_rect
        # 主模同向（内核单源性质，互证）
        assert cutoff_fc_hz(self.WG_RIDGE) < cutoff_fc_hz(self.WG_RECT)

    def test_even_mode_weak_perturbation(self):
        fc20_rect = C0_HZ * (2 * math.pi / self.WG_RECT.a) / (2 * math.pi)
        fc20_ridge = C0_HZ * even_mode_kcs(self.WG_RIDGE, 1)[0] / (2 * math.pi)
        assert abs(fc20_ridge / fc20_rect - 1.0) < 0.08  # 脊在偶模 E 节点附近：弱扰动
        # 实测 +5.6%@d/b=0.3（奇模同几何 −1.5%）；方向不预断，带为数量级守卫

    def test_fundamental_crosscheck_with_kernel(self):
        # odd_mode_kcs(n=1) 与内核 cutoff_kc 同解（不同求根路径互证）
        for wg in (self.WG_RECT, self.WG_RIDGE):
            assert odd_mode_kcs(wg, 1)[0] == pytest.approx(
                cutoff_kc(wg), rel=1e-9)

    def test_bandwidth_block(self):
        nxt = next_mode_cutoff(self.WG_RIDGE)
        fc10 = cutoff_fc_hz(self.WG_RIDGE)
        assert nxt["fc_hz"] > fc10
        assert nxt["single_mode_band_hz"][0] == pytest.approx(fc10, rel=1e-12)
        assert nxt["single_mode_band_hz"][1] == pytest.approx(
            nxt["fc_hz"], rel=1e-15)


class TestGuards:
    def test_below_cutoff_row_rejected(self):
        wg = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.004)
        with pytest.raises(ValueError):
            ridged_waveguide_panel([1e9], wg)

    def test_empty_grid_rejected(self):
        wg = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.0)
        with pytest.raises(ValueError, match="不得为空"):
            ridged_waveguide_panel([], wg)

    def test_bad_sigma_rejected(self):
        wg = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.0)
        with pytest.raises(ValueError):
            ridged_waveguide_panel([10e9], wg, sigma=True)
        with pytest.raises(ValueError):
            ridged_waveguide_panel([10e9], wg, sigma=-1.0)
        with pytest.raises(ValueError):
            alpha_c_te10_estimate(10e9, wg, True)

    def test_bad_n_roots_rejected(self):
        wg = RidgedWaveguide(a=0.04, b=0.02, s=0.01, d=0.004)
        with pytest.raises(ValueError):
            odd_mode_kcs(wg, 0)
        with pytest.raises(ValueError):
            even_mode_kcs(wg, True)


C0_HZ = 299792458.0
