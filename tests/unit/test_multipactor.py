"""MP-3 multipactor 微放电击穿阈值内核单测（core/multipactor.py，round15
§三 :84）。

裁判 = 外部独立来源（#118：不是被测实现的自我推导）：
  * 渡越谐振闭式：一阶运动方程 x(t)=(eE0/mω²)[sin φ0−sin(φ0+θ)+θcos φ0]
    的手工代入回收——fd=1 GHz·mm 时 K=224.4597 V、V_1=K/π=71.4477 V、
    带边 K/√(4+π²)=60.2707 V 与 K/2=112.2298 V（经典 Hatch-Williams/
    Vaughan 1988 一阶口径的量级带；ECSS 实验包络 fd≈1 处 silver≈38 V，
    理想化带边偏保守同量级——非逐点锚，见 docstring 局限声明）；
  * 封闭轨道碰撞能量：E_imp=2K/(2tanφ0+x)² 恒等式 + φ0=0 轨道 45.485 eV、
    带边最优相位 23.032 eV 手算回收；
  * SEY crossover 窗口：Kishek & Lau PAC97 (7P061)「δ>1 仅在两 crossover
    之间」口径 + Vaughan 曲线构造恒等式（δ(Emax)=δmax、δ(E1)=δ(E2)=1）；
  * SEY 材料表 M1–M6：arXiv:2507.17881v1 Table 1 逐值（2026-10-02 实取）；
  * 角依赖：arXiv:1710.01636 §II 转引式 θ=π/4 手算回收；
  * N 载波：非相干 RSS P_eq=ΣPi 与相干 (Σ√Pi)² 恒等式（相干 ≥ 非相干）；
  * 20-gap 串接：链级阈值 = N_g·单隙阈值的纯缩放恒等（ASSUMPTION 口径）；
  * 合成判据：fd=1、M2 窗（E1=42/E2=3056 eV）带 1=[68.7960, 71.4477] V
    手算链 + margin/pass 方向 + JSON 契约。

确定性：无网络、无真机、无文件 IO、无随机。
"""

from __future__ import annotations

import json
import math
from itertools import pairwise

import pytest

from rfauto.core.multipactor import (
    E_CHARGE_C,
    M_E_KG,
    SEY_MATERIALS,
    multi_carrier_equivalent_power_w,
    multipactor_susceptibility_check,
    orbit_impact_energy_ev,
    order_sustainable_band_v,
    series_gap_chain_threshold_v,
    sey_crossover_energies_ev,
    susceptibility_band_v,
    susceptibility_scale_v,
    transit_resonance_voltage_v,
    vaughan_angle_adjusted,
    vaughan_yield,
)

# fd = 1 GHz·mm 的手算常数（K = m·ω²·d²/e，独立于被测实现的算术路径）
_FD1 = dict(freq_hz=1.0e9, gap_m=1.0e-3)
_OMEGA1 = 2.0 * math.pi * 1.0e9
_K1 = M_E_KG * _OMEGA1 * _OMEGA1 * 1.0e-6 / E_CHARGE_C  # 224.4597 V
_X1 = math.pi
_E1_M2 = 42.0
_E2_M2 = 3056.0


# ---------------------------------------------------------------- 谐振线/几何带


class TestTransitResonance:
    """渡越时间谐振线：手算回收 + 标度律 + 负例。"""

    def test_n1_hand_recovery_fd1(self) -> None:
        # V_1 = K/π = 224.4597/π = 71.4477 V（fd=1 GHz·mm 手算链）
        v = transit_resonance_voltage_v(1.0e9, 1.0e-3, 1)
        assert v == pytest.approx(71.4477, rel=1e-4)
        assert v == pytest.approx(_K1 / math.pi, rel=1e-12)

    def test_order_scaling_exact(self) -> None:
        v1 = transit_resonance_voltage_v(1.0e9, 1.0e-3, 1)
        assert transit_resonance_voltage_v(1.0e9, 1.0e-3, 2) == pytest.approx(
            v1 / 3.0, rel=1e-12)
        assert transit_resonance_voltage_v(1.0e9, 1.0e-3, 3) == pytest.approx(
            v1 / 5.0, rel=1e-12)

    def test_scale_voltage_constant(self) -> None:
        # K = m·ω²·d²/e：独立算术路径回收（224.4597 V @fd=1 GHz·mm）
        assert susceptibility_scale_v(1.0e9, 1.0e-3) == pytest.approx(
            _K1, rel=1e-12)
        assert susceptibility_scale_v(1.0e9, 1.0e-3) == pytest.approx(
            224.4597, rel=1e-4)

    def test_fd_scaling_laws(self) -> None:
        # V_n ∝ ω²d²：频率×2 → ×4；间隙×2 → ×4（相似标度律，V 随 f·d 同向）
        v0 = transit_resonance_voltage_v(1.0e9, 1.0e-3, 1)
        assert transit_resonance_voltage_v(2.0e9, 1.0e-3, 1) == pytest.approx(
            4.0 * v0, rel=1e-12)
        assert transit_resonance_voltage_v(1.0e9, 2.0e-3, 1) == pytest.approx(
            4.0 * v0, rel=1e-12)

    def test_invalid_inputs_refused(self) -> None:
        with pytest.raises(ValueError):
            transit_resonance_voltage_v(0.0, 1.0e-3, 1)
        with pytest.raises(ValueError):
            transit_resonance_voltage_v(1.0e9, -1.0e-3, 1)
        with pytest.raises(ValueError):
            transit_resonance_voltage_v(1.0e9, 1.0e-3, 0)
        with pytest.raises(ValueError):
            transit_resonance_voltage_v(1.0e9, 1.0e-3, 1.5)


class TestSusceptibilityBand:
    """序 n 几何敏感带：带边手算 + 单调性 + 谐振线在带内。"""

    def test_band1_edges_fd1(self) -> None:
        band = susceptibility_band_v(1.0e9, 1.0e-3, 1)
        assert band["scale_v"] == pytest.approx(224.4597, rel=1e-4)
        # 模块带边经 round(·,9) 落盘 → 对解析值放 rel=1e-9
        assert band["band_low_v"] == pytest.approx(
            _K1 / math.sqrt(4.0 + math.pi * math.pi), rel=1e-9)
        assert band["band_low_v"] == pytest.approx(60.2707, rel=1e-4)
        assert band["band_high_v"] == pytest.approx(112.2298, rel=1e-4)
        assert band["band_high_v"] == pytest.approx(_K1 / 2.0, rel=1e-9)
        # 最优发射相位 arctan(2/π) = 32.48°（round 12 位 → rel=1e-9）
        assert band["phase_at_low_rad"] == pytest.approx(math.atan2(2.0, _X1),
                                                         rel=1e-9)
        # 谐振线在带内
        assert band["band_low_v"] < band["v_resonance_v"] < band["band_high_v"]

    def test_band_low_monotone_decreasing_in_order(self) -> None:
        lows = [susceptibility_band_v(1.0e9, 1.0e-3, n)["band_low_v"]
                for n in range(1, 7)]
        assert all(lo2 < lo1 for lo1, lo2 in pairwise(lows))
        highs = [susceptibility_band_v(1.0e9, 1.0e-3, n)["band_high_v"]
                 for n in range(1, 7)]
        assert all(h == pytest.approx(_K1 / 2.0, rel=1e-9) for h in highs)

    def test_resonance_line_inside_band_all_orders(self) -> None:
        for n in range(1, 8):
            band = susceptibility_band_v(1.0e9, 1.0e-3, n)
            assert band["band_low_v"] < band["v_resonance_v"] < band["band_high_v"]

    def test_invalid_order_refused(self) -> None:
        with pytest.raises(ValueError):
            susceptibility_band_v(1.0e9, 1.0e-3, 0)


# ---------------------------------------------------------------- 碰撞能量


class TestOrbitImpactEnergy:
    """封闭轨道碰撞能量：恒等式 + 手算回收。"""

    def test_phi0_orbit_fd1(self) -> None:
        # φ0=0：E_imp = 2K/x² = 2·224.4597/π² = 45.485 eV
        e = orbit_impact_energy_ev(_K1 / _X1, 1.0e9, 1.0e-3, 0.0)
        assert e == pytest.approx(45.4850, rel=1e-4)
        assert e == pytest.approx(2.0 * _K1 / (_X1 * _X1), rel=1e-12)

    def test_cos_squared_identity(self) -> None:
        # E_imp(φ0) = E_imp(0)·cos²φ0（v(τ)∝cos φ0 的精确推论）
        e0 = orbit_impact_energy_ev(70.0, 1.0e9, 1.0e-3, 0.0)
        e1 = orbit_impact_energy_ev(70.0, 1.0e9, 1.0e-3, 0.3)
        assert e1 == pytest.approx(e0 * math.cos(0.3) ** 2, rel=1e-12)

    def test_band_edge_optimal_phase_energy(self) -> None:
        # 带边最优相位的碰撞能量 = 2K·x²/(4+x²)² = 23.032 eV @fd=1、n=1
        band = susceptibility_band_v(1.0e9, 1.0e-3, 1)
        e = orbit_impact_energy_ev(band["band_low_v"], 1.0e9, 1.0e-3,
                                   band["phase_at_low_rad"])
        assert e == pytest.approx(23.0324, rel=1e-4)

    def test_invalid_voltage_refused(self) -> None:
        with pytest.raises(ValueError):
            orbit_impact_energy_ev(-1.0, 1.0e9, 1.0e-3, 0.0)


# ---------------------------------------------------------------- Vaughan SEY


class TestVaughanYield:
    """Vaughan 普适曲线：构造恒等式 + crossover 回收（UNVERIFIED 出处，
    判定面不消费曲线）。"""

    def test_construction_identities(self) -> None:
        assert vaughan_yield(0.0, 2.09, 277.5) == 0.0
        assert vaughan_yield(277.5, 2.09, 277.5) == pytest.approx(2.09, rel=1e-12)
        # 峰两侧都低于峰值
        assert vaughan_yield(100.0, 2.09, 277.5) < 2.09
        assert vaughan_yield(600.0, 2.09, 277.5) < 2.09

    def test_monotone_branches(self) -> None:
        below = [vaughan_yield(e, 2.0, 300.0) for e in (10.0, 100.0, 200.0, 300.0)]
        assert all(b2 > b1 for b1, b2 in pairwise(below))
        above = [vaughan_yield(e, 2.0, 300.0) for e in (300.0, 500.0, 1000.0, 3000.0)]
        assert all(a2 < a1 for a1, a2 in pairwise(above))

    def test_crossover_recovery(self) -> None:
        cross = sey_crossover_energies_ev(2.09, 277.5)
        e1, e2 = cross["e1_ev"], cross["e2_ev"]
        assert e1 < 277.5 < e2
        assert vaughan_yield(e1, 2.09, 277.5) == pytest.approx(1.0, abs=1e-6)
        assert vaughan_yield(e2, 2.09, 277.5) == pytest.approx(1.0, abs=1e-6)

    def test_ks_flattens_but_keeps_peak(self) -> None:
        assert vaughan_yield(277.5, 2.09, 277.5, k_s=0.9) == pytest.approx(
            2.09, rel=1e-12)
        # 低能侧粗糙面（k_s<1）曲线更高（(v e^{1-v})^{k_s} 随 k_s 减小而升）
        assert vaughan_yield(50.0, 2.09, 277.5, k_s=0.9) > vaughan_yield(
            50.0, 2.09, 277.5, k_s=1.0)

    def test_sey_materials_table_fidelity(self) -> None:
        # arXiv:2507.17881v1 Table 1 逐值（2026-10-02 实取）
        assert SEY_MATERIALS["M2"] == {
            "delta_max": 2.09, "emax_ev": 277.5, "e1_ev": 42.0, "e2_ev": 3056.0}
        assert SEY_MATERIALS["M4"] == {
            "delta_max": 1.2, "emax_ev": 277.5, "e1_ev": 109.5, "e2_ev": 759.5}
        assert SEY_MATERIALS["M6"] == {
            "delta_max": 3.2, "emax_ev": 400.0, "e1_ev": 19.0, "e2_ev": 1550.0}
        assert len(SEY_MATERIALS) == 6

    def test_invalid_inputs_refused(self) -> None:
        with pytest.raises(ValueError):
            vaughan_yield(10.0, 1.0, 277.5)  # δmax ≤ 1 无 δ>1 窗口
        with pytest.raises(ValueError):
            vaughan_yield(-1.0, 2.0, 277.5)
        with pytest.raises(ValueError):
            vaughan_yield(10.0, 2.0, 0.0)
        with pytest.raises(ValueError):
            sey_crossover_energies_ev(0.8, 277.5)


class TestVaughanAngle:
    """角依赖：θ=0 恒等 + 手算回收 + 域守卫。"""

    def test_normal_incidence_identity(self) -> None:
        adj = vaughan_angle_adjusted(0.0, 2.09, 277.5)
        assert adj["delta_max"] == pytest.approx(2.09, rel=1e-12)
        assert adj["emax_ev"] == pytest.approx(277.5, rel=1e-12)

    def test_quarter_pi_hand_recovery(self) -> None:
        # θ=π/4、k_s=1：δmax'=2.09·(1+π/32)、Emax'=277.5·(1+π/16)
        adj = vaughan_angle_adjusted(math.pi / 4.0, 2.09, 277.5, k_s=1.0)
        assert adj["delta_max"] == pytest.approx(
            2.09 * (1.0 + math.pi / 32.0), rel=1e-12)
        assert adj["emax_ev"] == pytest.approx(
            277.5 * (1.0 + math.pi / 16.0), rel=1e-12)

    def test_monotone_in_incidence(self) -> None:
        small = vaughan_angle_adjusted(0.3, 2.0, 300.0)
        large = vaughan_angle_adjusted(0.6, 2.0, 300.0)
        assert large["delta_max"] > small["delta_max"]
        assert large["emax_ev"] > small["emax_ev"]

    def test_domain_refused(self) -> None:
        with pytest.raises(ValueError, match="域"):
            vaughan_angle_adjusted(-0.1, 2.0, 300.0)
        with pytest.raises(ValueError, match="域"):
            vaughan_angle_adjusted(math.pi / 2.0 + 0.01, 2.0, 300.0)


# ---------------------------------------------------------------- SEY 门控带


class TestSustainableBand:
    """SEY 窗口门控可持续带：fd=1、M2 窗手算链 + 空带方向 + E2 门。"""

    def test_band1_m2_window_fd1(self) -> None:
        # t1=(√(2K/42)−π)/2=0.063872 → 带低边 V(t1)=68.7960 V、高边 V(0)=K/π
        band = order_sustainable_band_v(1.0e9, 1.0e-3, 1, _E1_M2, _E2_M2)
        assert band["sustainable"] is True
        assert band["band_low_v"] == pytest.approx(68.7960, rel=1e-4)
        assert band["band_high_v"] == pytest.approx(_K1 / math.pi, rel=1e-9)
        # 碰撞能量窗：(2K/(2t1+π)², 2K/π²) = (42, 45.485) eV
        assert band["impact_energy_ev_window"][0] == pytest.approx(42.0, rel=1e-4)
        assert band["impact_energy_ev_window"][1] == pytest.approx(45.4850,
                                                                   rel=1e-4)

    def test_higher_orders_empty_below_first_crossover(self) -> None:
        # n=2 最大碰撞能量 2K/(3π)² = 5.05 eV < E1=42 → 整带不可持续
        band = order_sustainable_band_v(1.0e9, 1.0e-3, 2, _E1_M2, _E2_M2)
        assert band["sustainable"] is False
        assert band["empty_reason"] == "impact_below_first_crossover"
        assert band["impact_energy_max_ev"] == pytest.approx(
            2.0 * _K1 / (3.0 * math.pi) ** 2, rel=1e-9)

    def test_lower_e1_widens_band_down_to_geometric_edge(self) -> None:
        # E1=20 eV：t1=0.798 越过最优相位 → 带低边回到几何带边 K/√(4+π²)
        band = order_sustainable_band_v(1.0e9, 1.0e-3, 1, 20.0, _E2_M2)
        assert band["sustainable"] is True
        assert band["band_low_v"] == pytest.approx(
            _K1 / math.sqrt(4.0 + math.pi * math.pi), rel=1e-9)
        assert band["band_low_v"] < order_sustainable_band_v(
            1.0e9, 1.0e-3, 1, _E1_M2, _E2_M2)["band_low_v"]

    def test_e2_gate_lifts_band_low_edge(self) -> None:
        # E2=41 eV（< 带内最大 45.485）：低 t 侧被切 → 带低边高于几何带边
        band = order_sustainable_band_v(1.0e9, 1.0e-3, 1, 20.0, 41.0)
        assert band["sustainable"] is True
        assert band["band_low_v"] > _K1 / math.sqrt(4.0 + math.pi * math.pi)
        assert band["impact_energy_ev_window"][1] == pytest.approx(41.0, rel=1e-4)

    def test_all_orders_empty_for_huge_e1(self) -> None:
        band = order_sustainable_band_v(1.0e9, 1.0e-3, 1, 1.0e6, None)
        assert band["sustainable"] is False

    def test_invalid_window_refused(self) -> None:
        with pytest.raises(ValueError, match="e2_ev"):
            order_sustainable_band_v(1.0e9, 1.0e-3, 1, 100.0, 50.0)
        with pytest.raises(ValueError):
            order_sustainable_band_v(1.0e9, 1.0e-3, 1, 0.0, None)


# ---------------------------------------------------------------- 级联/多载波


class TestMultiCarrier:
    """N 载波等效功率：双口径恒等式 + 相干 ≥ 非相干。"""

    def test_incoherent_rss(self) -> None:
        rep = multi_carrier_equivalent_power_w([10.0, 10.0])
        assert rep["equivalent_power_w"] == pytest.approx(20.0, rel=1e-12)
        assert rep["peak_voltage_v"] == pytest.approx(math.sqrt(2.0 * 20.0 * 50.0),
                                                      rel=1e-12)

    def test_coherent_worst_phase(self) -> None:
        rep = multi_carrier_equivalent_power_w([10.0, 10.0], coherent=True)
        # V = Σ√(2Pi·Z0) = 2√1000、P_eq = (Σ√Pi)² = 40
        assert rep["peak_voltage_v"] == pytest.approx(2.0 * math.sqrt(1000.0),
                                                      rel=1e-12)
        assert rep["equivalent_power_w"] == pytest.approx(40.0, rel=1e-12)
        assert rep["equivalent_power_w"] > multi_carrier_equivalent_power_w(
            [10.0, 10.0])["equivalent_power_w"]

    def test_single_carrier_conventions_coincide(self) -> None:
        a = multi_carrier_equivalent_power_w([7.0])
        b = multi_carrier_equivalent_power_w([7.0], coherent=True)
        assert a["equivalent_power_w"] == pytest.approx(7.0, rel=1e-12)
        assert b["equivalent_power_w"] == pytest.approx(7.0, rel=1e-12)

    def test_invalid_inputs_refused(self) -> None:
        with pytest.raises(ValueError):
            multi_carrier_equivalent_power_w([])
        with pytest.raises(ValueError):
            multi_carrier_equivalent_power_w([10.0, -1.0])
        with pytest.raises(ValueError):
            multi_carrier_equivalent_power_w([10.0], z0_ohm=0.0)


class TestSeriesGapChain:
    """20-gap 串接：链级阈值纯缩放恒等（ASSUMPTION 口径）。"""

    def test_twenty_gap_scaling(self) -> None:
        assert series_gap_chain_threshold_v(38.3, 20) == pytest.approx(
            766.0, rel=1e-12)

    def test_single_gap_identity(self) -> None:
        assert series_gap_chain_threshold_v(100.0, 1) == pytest.approx(
            100.0, rel=1e-12)

    def test_invalid_inputs_refused(self) -> None:
        with pytest.raises(ValueError):
            series_gap_chain_threshold_v(0.0, 20)
        with pytest.raises(ValueError):
            series_gap_chain_threshold_v(100.0, 0)
        with pytest.raises(ValueError):
            series_gap_chain_threshold_v(100.0, 1.5)


# ---------------------------------------------------------------- 合成判据


class TestMultipactorSusceptibilityCheck:
    """合成报告：M2 窗手算链 + margin/pass 方向 + 载波口径 + JSON 契约。"""

    def test_inside_band_is_susceptible(self) -> None:
        rep = multipactor_susceptibility_check(
            1.0e9, 1.0e-3, voltage_v=70.0,
            delta_max=2.09, e1_ev=_E1_M2, e2_ev=_E2_M2)
        assert rep["susceptible"] is True
        assert rep["susceptible_orders"] == [1]
        assert rep["onset_threshold_v"] == pytest.approx(68.7960, rel=1e-4)
        # 70 V 落带内 → margin 为负、pass False
        assert rep["margin_to_onset_db"] == pytest.approx(
            20.0 * math.log10(68.7960 / 70.0), abs=1e-3)
        assert rep["pass"] is False
        assert rep["sey"]["provenance"] == "explicit_input"

    def test_below_onset_passes_with_margin(self) -> None:
        rep = multipactor_susceptibility_check(
            1.0e9, 1.0e-3, voltage_v=5.0,
            delta_max=2.09, e1_ev=_E1_M2, e2_ev=_E2_M2)
        assert rep["susceptible"] is False
        assert rep["margin_to_onset_db"] == pytest.approx(22.7719, rel=1e-4)
        assert rep["pass"] is True

    def test_above_all_bands_semantics(self) -> None:
        # 500 V 高于全部可持续带：margin_above=16.9 dB ≥ 6 → pass True + 注记
        rep = multipactor_susceptibility_check(
            1.0e9, 1.0e-3, voltage_v=500.0,
            delta_max=2.09, e1_ev=_E1_M2, e2_ev=_E2_M2)
        assert rep["susceptible"] is False
        assert rep["margin_above_bands_db"] == pytest.approx(
            20.0 * math.log10(500.0 / 71.4477), abs=1e-3)
        assert rep["pass"] is True
        assert any("高于全部可持续带" in n for n in rep["notes"])
        # 100 V：仅 2.92 dB 裕量 < 6 → pass False（保守语义）
        tight = multipactor_susceptibility_check(
            1.0e9, 1.0e-3, voltage_v=100.0,
            delta_max=2.09, e1_ev=_E1_M2, e2_ev=_E2_M2)
        assert tight["margin_above_bands_db"] == pytest.approx(2.9202, abs=1e-3)
        assert tight["pass"] is False

    def test_power_to_voltage_convention(self) -> None:
        rep = multipactor_susceptibility_check(
            1.0e9, 1.0e-3, power_w=10.0, z0_ohm=50.0,
            delta_max=2.09, e1_ev=_E1_M2, e2_ev=_E2_M2)
        assert rep["applied_voltage_v"] == pytest.approx(
            math.sqrt(2.0 * 10.0 * 50.0), rel=1e-12)

    def test_carrier_powers_coherent_vs_incoherent(self) -> None:
        kw = dict(delta_max=2.09, e1_ev=_E1_M2, e2_ev=_E2_M2)
        rss = multipactor_susceptibility_check(
            1.0e9, 1.0e-3, carrier_powers_w=[5.0, 5.0], **kw)
        coh = multipactor_susceptibility_check(
            1.0e9, 1.0e-3, carrier_powers_w=[5.0, 5.0], carrier_coherent=True,
            **kw)
        assert rss["applied_voltage_v"] == pytest.approx(
            math.sqrt(2.0 * 10.0 * 50.0), rel=1e-12)
        assert coh["applied_voltage_v"] == pytest.approx(
            2.0 * math.sqrt(2.0 * 5.0 * 50.0), rel=1e-12)
        assert rss["carrier"]["convention"] == "incoherent_rss"
        assert coh["carrier"]["convention"] == "coherent_worst_phase"

    def test_default_sey_derived_unverified_provenance(self) -> None:
        rep = multipactor_susceptibility_check(1.0e9, 1.0e-3, voltage_v=70.0)
        assert rep["sey"]["provenance"] == "derived_vaughan_curve_UNVERIFIED"
        assert rep["sey"]["e1_ev"] < rep["sey"]["e2_ev"]
        # 派生 crossover 与 vaughan_yield 交点自洽
        assert vaughan_yield(rep["sey"]["e1_ev"], 2.0, 300.0) == pytest.approx(
            1.0, abs=1e-5)

    def test_order_max_controls_scan_depth(self) -> None:
        rep = multipactor_susceptibility_check(
            1.0e9, 1.0e-3, voltage_v=70.0, order_max=3,
            delta_max=2.09, e1_ev=_E1_M2, e2_ev=_E2_M2)
        assert len(rep["orders"]) == 3
        assert rep["order_max"] == 3

    def test_determinism_and_json_contract(self) -> None:
        rep = multipactor_susceptibility_check(
            1.0e9, 1.0e-3, carrier_powers_w=[3.0, 7.0],
            delta_max=2.09, e1_ev=_E1_M2, e2_ev=_E2_M2)
        rep2 = multipactor_susceptibility_check(
            1.0e9, 1.0e-3, carrier_powers_w=[3.0, 7.0],
            delta_max=2.09, e1_ev=_E1_M2, e2_ev=_E2_M2)
        assert json.dumps(rep, sort_keys=True, allow_nan=False) == json.dumps(
            rep2, sort_keys=True, allow_nan=False)
        text = json.dumps(rep, allow_nan=False, sort_keys=True)
        assert "NaN" not in text
        assert rep["fxd_ghz_mm"] == pytest.approx(1.0, rel=1e-12)

    def test_invalid_inputs_refused(self) -> None:
        with pytest.raises(ValueError):
            multipactor_susceptibility_check(0.0, 1.0e-3, voltage_v=70.0)
        with pytest.raises(ValueError):
            multipactor_susceptibility_check(1.0e9, 0.0, voltage_v=70.0)
        with pytest.raises(ValueError):  # 无电压来源
            multipactor_susceptibility_check(1.0e9, 1.0e-3)
        with pytest.raises(ValueError, match="成对"):  # e1/e2 只给其一
            multipactor_susceptibility_check(1.0e9, 1.0e-3, voltage_v=70.0,
                                             e1_ev=42.0)
        with pytest.raises(ValueError):  # e2 ≤ e1
            multipactor_susceptibility_check(1.0e9, 1.0e-3, voltage_v=70.0,
                                             e1_ev=42.0, e2_ev=40.0)
        with pytest.raises(ValueError):  # δmax ≤ 1
            multipactor_susceptibility_check(1.0e9, 1.0e-3, voltage_v=70.0,
                                             delta_max=1.0)
        with pytest.raises(ValueError):
            multipactor_susceptibility_check(1.0e9, 1.0e-3, voltage_v=70.0,
                                             order_max=0)
