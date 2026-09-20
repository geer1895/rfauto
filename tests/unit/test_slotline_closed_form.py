"""槽线闭式（core/slotline.py，Janaswamy–Schaubert 式）单测。

锚（文献出处逐条）：
- Janaswamy 博士论文 (UMass 1986, NASA NTRS 19870016815) Table 3.2 p.15：
  εr=2.55、d=1.57mm、W/d=1.34，2–4GHz 五频点 SDA 计算 λ'/λ0 —— 式 (8) 是这套
  SDA 数据的最小二乘拟合（Av 0.37% / Max 2.2%），本测试门 |Δ| ≤ 2.2%。
- Tumialan, "Linearly tapered slot antenna", NJIT MS thesis 1996, Table 2 p.47：
  εr=2.2 Duroid、d=10mil、10GHz，按同一 [33] 公式程序算得 w=40mil→150Ω/0.94λ0，
  w=30mil→140Ω/0.93λ0（表值取整到 10Ω / 0.01）——门 Z0 ±3%、λ'/λ0 ±0.01。
- 手算锚：式 (8) 在 εr=2.55、W/d=1.34、3GHz 的逐项手算 0.8707（见 docstring 内
  算式），钉住常数转录。
- 范围外显式报错（不外推）：d/λ0、W/λ0（含宽槽段未实现）、εr 三条边界。
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from rfauto.core import slotline as sl

# ── 文献锚数据 ────────────────────────────────────────────────────────────────
# Janaswamy 1986 Table 3.2：(f_GHz, SDA computed λ'/λ0, measured λ'/λ0)
_T32_ER, _T32_D_MM, _T32_W_OVER_D = 2.55, 1.57, 1.34
_T32_ROWS = [(2.0, 0.889, 0.873), (2.5, 0.883, 0.866), (3.0, 0.879, 0.862),
             (3.5, 0.875, 0.852), (4.0, 0.871, 0.867)]
# NJIT Table 2：(w_mil, Z0_table_ohm, lambda_ratio_table)
_NJIT_ROWS = [(40, 150.0, 0.94), (30, 140.0, 0.93)]


class TestLiteratureAnchors:
    @pytest.mark.parametrize("f_ghz,sda,meas", _T32_ROWS)
    def test_table_3_2_sda_within_fit_error(self, f_ghz, sda, meas):
        r = sl.slotline_closed_form(_T32_W_OVER_D * _T32_D_MM, _T32_D_MM, _T32_ER, f_ghz)
        assert r.segment == "low"
        assert abs(r.lambda_ratio / sda - 1.0) <= sl.FIT_ERROR_MAX["lambda_low"]
        # 实测值系统性低于 SDA ~1-2%（原文 §3.2 归因胶层/金属厚，如实记）：闭式
        # 与实测差不超过 3.5%，不作为精度门，只作物理量级守卫
        assert abs(r.lambda_ratio / meas - 1.0) <= 0.035

    def test_hand_calculation_pin_3ghz(self):
        """式 (8) 逐项手算（εr=2.55, W/d=1.34, f=3GHz, d/λ0=0.015711）：
        1.045 − 0.365·0.93609 + 6.3·1.34·2.55^0.945/(238.64+134)
        − [0.148 − 8.81·3.50/255]·ln(0.015711) = 0.8707。"""
        ln_er = math.log(2.55)
        d_l = 1.57e-3 / (sl.C0 / 3e9)
        hand = (1.045 - 0.365 * ln_er
                + 6.3 * 1.34 * 2.55 ** 0.945 / (238.64 + 134.0)
                - (0.148 - 8.81 * (2.55 + 0.95) / (100 * 2.55)) * math.log(d_l))
        assert hand == pytest.approx(0.8707, abs=5e-4)
        r = sl.slotline_closed_form(_T32_W_OVER_D * _T32_D_MM, _T32_D_MM, _T32_ER, 3.0)
        assert r.lambda_ratio == pytest.approx(hand, rel=1e-12)

    @pytest.mark.parametrize("w_mil,z0_tab,ratio_tab", _NJIT_ROWS)
    def test_njit_table_2_same_formula_program(self, w_mil, z0_tab, ratio_tab):
        # 论文用 εr=2.2（Duroid 标称），拟合下限 2.22——按下限评估（Δεr 对 Z0 影响
        # ≪ 表值 10Ω 取整）
        r = sl.slotline_closed_form(w_mil * 0.0254, 10 * 0.0254, 2.22, 10.0)
        assert abs(r.z0_ohm / z0_tab - 1.0) <= 0.03
        assert abs(r.lambda_ratio - ratio_tab) <= 0.01

    def test_z0_hand_calculation_pin(self):
        """式 (9) 逐项手算（εr=3.66, W=1.0, d=1.524mm, 2.5GHz）→ 110.9Ω。"""
        r = sl.slotline_closed_form(1.0, 1.524, 3.66, 2.5)
        er, ln_er = 3.66, math.log(3.66)
        w_d, w_l, d_l = r.w_over_d, r.w_over_lambda0, r.d_over_lambda0
        hand = (60 + 3.69 * math.sin((er - 2.22) * math.pi / 2.36)
                + 133.5 * math.log(10 * er) * math.sqrt(w_l)
                + 2.81 * (1 - 0.011 * er * (4.48 + ln_er)) * w_d * math.log(100 * d_l)
                + 131.1 * (1.028 - ln_er) * math.sqrt(d_l)
                + 12.48 * (1 + 0.18 * ln_er) * w_d / math.sqrt(er - 2.06 + 0.85 * w_d ** 2))
        assert r.z0_ohm == pytest.approx(hand, rel=1e-12)
        assert r.z0_ohm == pytest.approx(110.92, abs=0.05)
        assert r.eps_eff == pytest.approx(1.6462, abs=1e-3)


class TestPhysics:
    def test_eps_eff_between_air_and_substrate(self):
        for er in (2.22, 3.0, 3.66, 3.8, 5.0, 9.8):
            r = sl.slotline_closed_form(1.0, 1.524, er, 2.5)
            assert 1.0 < r.eps_eff < er
            assert r.beta_rad_m > 2 * math.pi * 2.5e9 / sl.C0

    def test_z0_increases_with_slot_width(self):
        z = [sl.slotline_z0(w, 1.524, 3.66, 2.5) for w in (0.4, 0.7, 1.0, 1.5, 2.5)]
        assert all(b > a for a, b in pairwise(z))

    def test_eps_eff_increases_with_thickness_ratio(self):
        # 同 εr、同 W/d：d/λ0 增大（更厚基板）→ 场更多进入介质 → εeff 上升
        e = [sl.slotline_eps_eff(0.5 * d, d, 3.66, 2.5) for d in (0.8, 1.2, 1.6, 2.4)]
        assert all(b > a for a, b in pairwise(e))

    def test_segment_switch_at_3_8(self):
        assert sl.slotline_closed_form(1.0, 1.524, 3.8, 2.5).segment == "low"
        assert sl.slotline_closed_form(1.0, 1.524, 3.81, 2.5).segment == "mid"

    def test_derived_quantities_consistent(self):
        r = sl.slotline_closed_form(1.0, 1.524, 3.66, 2.5)
        lam_g = sl.slotline_guide_wavelength_mm(1.0, 1.524, 3.66, 2.5)
        assert lam_g == pytest.approx(2 * math.pi / r.beta_rad_m * 1e3, rel=1e-12)
        assert sl.slotline_beta(1.0, 1.524, 3.66, 2.5) == pytest.approx(r.beta_rad_m)
        assert sl.slotline_lambda_ratio(1.0, 1.524, 3.66, 2.5) == pytest.approx(r.lambda_ratio)


class TestRangeGuards:
    def test_rejects_thin_substrate_project_default(self):
        # 仓库默认 h=0.508mm @2.5GHz → d/λ0=0.0042 < 0.006：显式拒绝（不外推）
        with pytest.raises(ValueError, match="d/λ0"):
            sl.slotline_closed_form(1.0, 0.508, 3.66, 2.5)

    def test_rejects_wide_slot_not_implemented(self):
        with pytest.raises(ValueError, match="宽槽段"):
            sl.slotline_closed_form(12.0, 1.524, 3.66, 2.5)  # W/λ0 ≈ 0.10

    def test_rejects_too_narrow_slot(self):
        with pytest.raises(ValueError, match="低于窄槽段下限"):
            sl.slotline_closed_form(0.1, 1.524, 3.66, 2.5)  # W/λ0 ≈ 0.0008

    def test_rejects_eps_r_out_of_fit(self):
        with pytest.raises(ValueError, match="Garg"):
            sl.slotline_closed_form(1.0, 1.524, 10.2, 2.5)
        with pytest.raises(ValueError, match="低于"):
            sl.slotline_closed_form(1.0, 1.524, 2.0, 2.5)

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_rejects_nonpositive_inputs(self, bad):
        with pytest.raises(ValueError):
            sl.slotline_closed_form(bad, 1.524, 3.66, 2.5)
        with pytest.raises(ValueError):
            sl.slotline_closed_form(1.0, 1.524, 3.66, bad)
