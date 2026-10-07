"""W4-B P3：槽线宽槽段式 (10)（Janaswamy–Schaubert 低 εr 宽槽 λ'/λ0）单测。

锚（#118/#1c）：
- 段界连续性（独立判据）：W/λ0=0.075 处式 (10) vs 已双源核对的窄槽式 (8)，
  全域网格 |Δ| ≤ 2.7%（两拟合各自声明 Max 2.2%/−2.6% 之内）；
- 手算逐项钉（εr=2.55, W/λ0=0.25, d/λ0=0.02）；
- 物理面：εeff∈(1,εr)、Z0 面显式不提供（式 (11) 未闭环）、域守卫三条；
- 手算值由测试内独立实现公式逐步重算（同源转录、独立求值路径）。
"""

from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core import slotline as sl


def _eq10_reference(w_l: float, d_l: float, er: float) -> float:
    """式 (10) 独立转录副本（JSIR 2005 排版源，与 core 实现同源不同路径）。"""
    return (1.194
            - 0.24 * math.log(er)
            - 0.62 * er ** 0.835 * w_l ** 0.48 / (1.344 + w_l / d_l)
            - 0.0617 * (1.91 - (er + 2.0) / er) * math.log(d_l))


class TestWideLowSegment:
    def test_lambda_ratio_matches_transcription(self):
        for er in (2.22, 2.55, 3.0, 3.8):
            for d_l in (0.006, 0.02, 0.06):
                for w_l in (0.075, 0.1, 0.25, 0.5, 1.0):
                    if (er, d_l, w_l) == (2.55, 0.006, 1.0):
                        continue  # 域角点拟合伪象，见 test_corner_fit_artifact
                    lam0_mm = sl.C0 / 3e9 * 1e3
                    r = sl.slotline_wide_low(w_l * lam0_mm, d_l * lam0_mm,
                                             er, 3.0)
                    assert r.lambda_ratio == pytest.approx(
                        _eq10_reference(w_l, d_l, er), rel=1e-12)

    def test_corner_fit_artifact_refused(self):
        """域角点（εr=2.55, d/λ0=0.006, W/λ0=1.0）：式 (10) 拟合越过空气极限
        0.095%（其自身 Max −2.6% 误差域内）——显式拒绝，不夹逼不外推。"""
        lam0_mm = sl.C0 / 3e9 * 1e3
        raw = sl._lambda_ratio_wide_low(1.0, 0.006, 2.55)
        assert raw > 1.0
        assert raw < 1.001  # 越界量 ≤0.1%（如实登记的拟合伪象幅度）
        with pytest.raises(ValueError, match="拟合伪象"):
            sl.slotline_wide_low(1.0 * lam0_mm, 0.006 * lam0_mm, 2.55, 3.0)

    def test_boundary_continuity_vs_narrow_eq8(self):
        """段界判据：W/λ0=0.075 处 (10) vs (8)，全域 |Δ| ≤ 2.7%。"""
        worst = 0.0
        for er in (2.22, 2.55, 3.0, 3.3, 3.8):
            for d_l in (0.006, 0.01, 0.0157, 0.03, 0.045, 0.06):
                w_d = 0.075 / d_l
                r8 = sl._lambda_ratio_low(w_d, d_l, er)
                r10 = _eq10_reference(0.075, d_l, er)
                worst = max(worst, abs(r10 / r8 - 1.0))
        assert worst <= 0.027, f"段界最坏偏差 {worst:.4f}"

    def test_derived_quantities_consistent(self):
        lam0_mm = sl.C0 / 3e9 * 1e3
        r = sl.slotline_wide_low(0.25 * lam0_mm, 0.02 * lam0_mm, 2.55, 3.0)
        assert r.eps_eff == pytest.approx(1.0 / r.lambda_ratio**2, rel=1e-12)
        assert r.beta_rad_m == pytest.approx(
            2 * math.pi * 3e9 / sl.C0 * math.sqrt(r.eps_eff), rel=1e-12)
        assert sl.slotline_wide_eps_eff(0.25 * lam0_mm, 0.02 * lam0_mm, 2.55, 3.0) \
            == pytest.approx(r.eps_eff, rel=1e-15)
        assert sl.slotline_wide_beta(0.25 * lam0_mm, 0.02 * lam0_mm, 2.55, 3.0) \
            == pytest.approx(r.beta_rad_m, rel=1e-15)
        assert sl.slotline_wide_lambda_ratio(
            0.25 * lam0_mm, 0.02 * lam0_mm, 2.55, 3.0) \
            == pytest.approx(r.lambda_ratio, rel=1e-15)

    def test_hand_calculation_pin(self):
        """εr=2.55、W/λ0=0.25、d/λ0=0.02 逐项手算（转录钉）：
        1.194 − 0.24·ln2.55 − 0.62·2.55^0.835·0.25^0.48/(1.344+12.5)
          − 0.0617·(1.91−4.55/2.55)·ln0.02。"""
        er, w_l, d_l = 2.55, 0.25, 0.02
        hand = (1.194 - 0.24 * math.log(er)
                - 0.62 * er ** 0.835 * w_l ** 0.48 / (1.344 + w_l / d_l)
                - 0.0617 * (1.91 - (er + 2.0) / er) * math.log(d_l))
        lam0_mm = sl.C0 / 3e9 * 1e3
        r = sl.slotline_wide_low(w_l * lam0_mm, d_l * lam0_mm, er, 3.0)
        assert r.lambda_ratio == pytest.approx(hand, rel=1e-12)
        # 宽槽物理趋势：λ'/λ0 高于窄槽（场更入空气）且 εeff 仍夹在 (1, εr)
        assert 1.0 < r.eps_eff < er


class TestWidePhysics:
    def test_eps_eff_bracket_and_monotone_width(self):
        lam0_mm = sl.C0 / 10e9 * 1e3
        for er in (2.22, 3.0, 3.8):
            for d_l in (0.006, 0.03, 0.06):
                prev = None
                for w_l in (0.075, 0.1, 0.2, 0.4, 0.7, 1.0):
                    r = sl.slotline_wide_low(w_l * lam0_mm, d_l * lam0_mm,
                                             er, 10.0)
                    assert 1.0 < r.eps_eff < er
                    assert 0.0 < r.lambda_ratio < 1.0
                    if prev is not None:
                        assert r.lambda_ratio > prev  # 槽越宽场越入空气
                    prev = r.lambda_ratio

    def test_eps_eff_increases_with_thickness_ratio(self):
        lam0_mm = sl.C0 / 10e9 * 1e3
        e = [sl.slotline_wide_eps_eff(0.3 * lam0_mm, d * lam0_mm, 2.55, 10.0)
             for d in (0.01, 0.02, 0.04, 0.06)]
        assert all(b > a for a, b in pairwise(e))


class TestWideRangeGuards:
    def test_rejects_below_wide_range(self):
        lam0_mm = sl.C0 / 10e9 * 1e3
        with pytest.raises(ValueError, match="宽槽段"):
            sl.slotline_wide_low(0.05 * lam0_mm, 0.02 * lam0_mm, 2.55, 10.0)

    def test_rejects_wide_z0_not_implemented(self):
        """宽槽 Z0（式 (11)）未闭环：closed_form 在宽槽显式拒绝且指向新入口。"""
        lam0_mm = sl.C0 / 10e9 * 1e3
        with pytest.raises(ValueError, match="宽槽段"):
            sl.slotline_closed_form(0.25 * lam0_mm, 0.02 * lam0_mm, 2.55, 10.0)

    def test_rejects_mid_eps_r_wide(self):
        """3.8<εr≤9.8 宽槽（式 (14)/(15)）与 Garg–Gupta 高 εr 段显式拒绝。"""
        lam0_mm = sl.C0 / 10e9 * 1e3
        with pytest.raises(ValueError, match=r"14.*15.*Garg"):
            sl.slotline_wide_low(0.25 * lam0_mm, 0.02 * lam0_mm, 9.8, 10.0)
        with pytest.raises(ValueError, match="Garg"):
            sl.slotline_closed_form(1.0, 1.524, 10.2, 2.5)

    def test_rejects_eps_r_below_fit(self):
        lam0_mm = sl.C0 / 10e9 * 1e3
        with pytest.raises(ValueError, match="拟合下限"):
            sl.slotline_wide_low(0.25 * lam0_mm, 0.02 * lam0_mm, 2.0, 10.0)

    def test_rejects_thickness_out_of_domain(self):
        lam0_mm = sl.C0 / 10e9 * 1e3
        with pytest.raises(ValueError, match="d/λ0"):
            sl.slotline_wide_low(0.25 * lam0_mm, 0.004 * lam0_mm, 2.55, 10.0)

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_rejects_nonpositive_inputs(self, bad):
        lam0_mm = sl.C0 / 10e9 * 1e3
        with pytest.raises(ValueError):
            sl.slotline_wide_low(bad, 0.02 * lam0_mm, 2.55, 10.0)
        with pytest.raises(ValueError):
            sl.slotline_wide_low(0.25 * lam0_mm, 0.02 * lam0_mm, 2.55, bad)


class TestNarrowPathsUnchanged:
    """窄槽消费面（fake_adapter/render_slotline/slotline_transitions）不受影响。"""

    def test_narrow_segment_still_evaluates(self):
        r = sl.slotline_closed_form(1.0, 1.524, 3.66, 2.5)
        assert r.segment == "low"
        # 与既有 test_slotline_closed_form 手算锚同点（εeff=1.6462 已钉）
        assert r.eps_eff == pytest.approx(1.6462, abs=1e-3)

    def test_narrow_wide_guard_message_points_to_new_entry(self):
        lam0_mm = sl.C0 / 10e9 * 1e3
        with pytest.raises(ValueError, match="slotline_wide_low"):
            sl.slotline_closed_form(0.25 * lam0_mm, 0.02 * lam0_mm, 2.55, 10.0)
