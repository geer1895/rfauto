"""WP4.4b 寄生提取闭式锚单测（core/parasitic，纯离线确定性）。

覆盖：传输线恒等式（sqrt(L/C)=Z0、v_p=c0/√εeff——对公式笔误的回归钉）、
教科书口径数值（RO4350B 50Ω 微带 ≈0.285 nH/mm / 0.111 pF/mm）、DC R
欧姆定律精确值、AC R 双区间（t≤δ 均匀 / t>δ 周长并联）、非法输入显式
ValueError、互连段总 RLC 主入口。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.parasitic import (
    COPPER_RHO_OHM_M,
    interconnect_rlc_anchor,
    microstrip_lc_per_length,
    trace_ac_resistance_per_length,
    trace_dc_resistance_ohm,
)

C0 = 299_792_458.0


# ─── 传输线恒等式（对公式笔误的回归钉）──────────────────────────────────────


class TestLCIdentity:
    def test_z0_equals_sqrt_lc_over_widths(self):
        """Z0 = sqrt(L/C)：同一锚内逐点成立（构造恒等，笔误必炸）。

        单位注意：L[nH/mm]、C[pF/mm] 下 (L/C)·1e3 才是 (H/F)²——
        nH/pF = 1e-3，漏掉该因子即测试错误（本用例曾踩，回归钉）。
        """
        for w_mm in (0.3, 1.09, 3.0):
            for eps_r in (2.2, 3.66, 4.4):
                anchor = microstrip_lc_per_length(w_mm, 0.508, eps_r, 1.0)
                z0_from_lc = math.sqrt(
                    1e3 * anchor["l_nh_per_mm"] / anchor["c_pf_per_mm"])
                assert z0_from_lc == pytest.approx(anchor["z0_ohm"], rel=1e-12)

    def test_phase_velocity_identity(self):
        """v_p = c0/√εeff = 1/sqrt(L·C)（SI 还原，核对单位换算因子）。"""
        anchor = microstrip_lc_per_length(1.09, 0.508, 3.66, 1.0)
        l_h_per_m = anchor["l_nh_per_mm"] * 1e-6   # nH/mm → H/m（×1e9/1e3）
        c_f_per_m = anchor["c_pf_per_mm"] * 1e-9   # pF/mm → F/m（×1e12/1e3）
        v_p = 1.0 / math.sqrt(l_h_per_m * c_f_per_m)
        assert v_p == pytest.approx(C0 / math.sqrt(anchor["eps_eff"]), rel=1e-12)


# ─── 教科书口径数值（独立来源：50Ω/RO4350B 常识量级 + 手算）─────────────────


class TestAnchorNumbers:
    def test_ro4350b_50ohm_typical_values(self):
        anchor = microstrip_lc_per_length(1.09, 0.508, 3.66, 1.0)
        assert anchor["z0_ohm"] == pytest.approx(50.0, abs=1.0)
        assert anchor["eps_eff"] == pytest.approx(2.85, abs=0.15)
        # 50Ω 微带典型 ~0.27-0.30 nH/mm、~0.10-0.12 pF/mm（数量级钉）
        assert 0.27 <= anchor["l_nh_per_mm"] <= 0.30
        assert 0.10 <= anchor["c_pf_per_mm"] <= 0.12

    def test_lower_epsr_raises_z0_monotonic(self):
        """同几何下 εr 越低 Z0 越高（物理单调性；替代 εr=1 空气极限——
        skrf HJ 在 ep_r=1 处内部除零告警，不作为测试工况）。"""
        z0_low = microstrip_lc_per_length(1.09, 0.508, 2.2, 1.0)["z0_ohm"]
        z0_high = microstrip_lc_per_length(1.09, 0.508, 3.66, 1.0)["z0_ohm"]
        assert z0_low > z0_high > 0.0


# ─── DC R（欧姆定律，几何精确）──────────────────────────────────────────────


class TestDCResistance:
    def test_hand_computed_value(self):
        # ρ·L/(w·t) = 1.724e-8 × 0.01 / (1e-3 × 1e-4) = 1.724e-3 Ω
        r = trace_dc_resistance_ohm(10.0, 1.0, 0.1)
        assert r == pytest.approx(1.724e-3, rel=1e-12)

    def test_ro4350b_50mm_trace(self):
        r = trace_dc_resistance_ohm(50.0, 1.09, 0.035)
        assert r == pytest.approx(0.022595019659239839, rel=1e-9)

    def test_rho_passthrough(self):
        r = trace_dc_resistance_ohm(10.0, 1.0, 0.1, rho_ohm_m=2 * COPPER_RHO_OHM_M)
        assert r == pytest.approx(2 * 1.724e-3, rel=1e-12)

    def test_nonpositive_rejected(self):
        for args in ((0.0, 1.0, 0.1), (10.0, -1.0, 0.1), (10.0, 1.0, 0.0)):
            with pytest.raises(ValueError, match="正"):
                trace_dc_resistance_ohm(*args)


# ─── AC R（双区间趋肤模型；参考值语义）──────────────────────────────────────


class TestACResistance:
    def test_skin_regime_hand_value(self):
        """1GHz 铜：δ=2.09µm < 35µm → 周长并联；Rs=8.25mΩ/sq，R=3.666mΩ/mm。"""
        out = trace_ac_resistance_per_length(1.09, 0.035, 1.0)
        assert out["regime"] == "skin_perimeter"
        assert out["skin_depth_um"] == pytest.approx(2.0897, rel=1e-3)
        assert out["rs_ohm_per_sq"] == pytest.approx(8.249e-3, rel=1e-3)
        # Rs/(2(w+t))：8.249e-3 / (2×1.125e-3) Ω/m = 3.666 Ω/m = 3.666e-3 Ω/mm
        assert out["r_ohm_per_mm"] == pytest.approx(3.666e-3, rel=1e-3)

    def test_uniform_regime_below_skin_depth(self):
        """t=1µm < δ(1GHz)=2.09µm → 均匀电流：R = ρ/(w·t)。"""
        out = trace_ac_resistance_per_length(1.09, 0.001, 1.0)
        assert out["regime"] == "uniform_dc_like"
        assert out["rs_ohm_per_sq"] is None
        expected = 1.724e-8 / (1.09e-3 * 1e-6) / 1e3  # Ω/m → Ω/mm
        assert out["r_ohm_per_mm"] == pytest.approx(expected, rel=1e-12)

    def test_frequency_scaling_sqrt(self):
        """趋肤区 Rs ∝ √f：10GHz 是 1GHz 的 √10 倍。"""
        r1 = trace_ac_resistance_per_length(1.09, 0.035, 1.0)["r_ohm_per_mm"]
        r10 = trace_ac_resistance_per_length(1.09, 0.035, 10.0)["r_ohm_per_mm"]
        assert r10 / r1 == pytest.approx(math.sqrt(10.0), rel=1e-9)


# ─── 互连段总 RLC 主入口 ─────────────────────────────────────────────────────


class TestInterconnectAnchor:
    def test_totals_scale_with_length(self):
        full = interconnect_rlc_anchor(50.0, 1.09, 0.035, 0.508, 3.66, 1.0)
        half = interconnect_rlc_anchor(25.0, 1.09, 0.035, 0.508, 3.66, 1.0)
        assert full["l_total_nh"] == pytest.approx(2 * half["l_total_nh"])
        assert full["c_total_pf"] == pytest.approx(2 * half["c_total_pf"])
        assert full["dc_r_ohm"] == pytest.approx(2 * half["dc_r_ohm"])
        # AC R 是每长度量：与段长无关
        assert full["ac_r_ohm_per_mm"] == pytest.approx(half["ac_r_ohm_per_mm"])

    def test_full_anchor_consistency_with_lc(self):
        anchor = interconnect_rlc_anchor(50.0, 1.09, 0.035, 0.508, 3.66, 1.0)
        assert anchor["l_total_nh"] == pytest.approx(
            anchor["l_nh_per_mm"] * 50.0, rel=1e-12)
        assert anchor["c_total_pf"] == pytest.approx(
            anchor["c_pf_per_mm"] * 50.0, rel=1e-12)

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError, match="eps_r"):
            microstrip_lc_per_length(1.09, 0.508, 0.9, 1.0)
        with pytest.raises(ValueError, match="正"):
            microstrip_lc_per_length(-1.09, 0.508, 3.66, 1.0)
        with pytest.raises(ValueError, match="正"):
            interconnect_rlc_anchor(0.0, 1.09, 0.035, 0.508, 3.66, 1.0)
        with pytest.raises(ValueError, match="实数"):
            microstrip_lc_per_length("1.09", 0.508, 3.66, 1.0)  # type: ignore[arg-type]
