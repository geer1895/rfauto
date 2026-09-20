"""E8c 链路预算单元测试。

验收标准：
① Friis 噪声级联公式正确性（对拍手算）
② 单级 = 自身
③ 级联 NF > 第一级 NF（物理事实）
④ P1dB 级联
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from rfauto.core.budget import (
    LinkBudget,
    bode_fano_integral_bound,
    bode_fano_limit,
    bode_fano_max_bandwidth,
    bode_fano_time_constant,
    coupling_coefficient_from_q,
    gamma_from_return_loss,
    loaded_q,
    unloaded_q_from_transmission,
)


class TestFriisCascade:
    """Friis 噪声级联公式测试。"""

    def test_single_stage(self):
        """单级 = 自身。"""
        b = LinkBudget()
        b.add_stage("LNA", gain_db=20, nf_db=0.8)
        r = b.compute()
        assert abs(r.cascade_gain_db - 20.0) < 0.01
        assert abs(r.cascade_nf_db - 0.8) < 0.01

    def test_cascade_nf_greater_than_first(self):
        """级联 NF > 第一级 NF（物理事实）。"""
        b = LinkBudget()
        b.add_stage("LNA", gain_db=20, nf_db=0.8)
        b.add_stage("Filter", gain_db=-2, nf_db=2.0)
        r = b.compute()
        assert r.cascade_nf_db > 0.8

    def test_friis_hand_calculation(self):
        """① Friis 手算对拍。"""
        b = LinkBudget()
        b.add_stage("Stage1", gain_db=10, nf_db=3)   # G1=10, F1=2
        b.add_stage("Stage2", gain_db=20, nf_db=6)   # G2=100, F2=4

        r = b.compute()
        # F_total = F1 + (F2-1)/G1 = 2 + (4-1)/10 = 2 + 0.3 = 2.3
        expected_nf = 10 * math.log10(2.3)
        assert abs(r.cascade_nf_db - expected_nf) < 0.05  # Friis formula tolerance

    def test_loss_stage(self):
        """损耗级（负增益）增加 NF。"""
        b = LinkBudget()
        b.add_stage("LNA", gain_db=20, nf_db=0.8)
        b.add_stage("Cable", gain_db=-3, nf_db=3)  # 无源损耗 NF=损耗
        r = b.compute()
        assert r.cascade_nf_db > 0.8

    def test_empty_chain(self):
        """空链路。"""
        b = LinkBudget()
        r = b.compute()
        assert r.cascade_gain_db == 0
        assert r.cascade_nf_db == 0

    def test_to_dict(self):
        b = LinkBudget()
        b.add_stage("LNA", gain_db=20, nf_db=0.8, p1db_dbm=15)
        r = b.compute()
        d = r.to_dict()
        assert "stages" in d
        assert "cascade_nf_db" in d

    def test_p1db_cascade(self):
        """④ P1dB 级联。"""
        b = LinkBudget()
        b.add_stage("LNA", gain_db=20, nf_db=0.8, p1db_dbm=15)
        b.add_stage("PA", gain_db=25, nf_db=5, p1db_dbm=30)
        r = b.compute()
        assert r.cascade_p1db_dbm is not None


# ─── C16（§10.3）收尾：教科书级联测例 ±0.1dB + Bode-Fano 极限 + Q 提取 ──────────

#: 教科书 Friis 测例：(级列表, 期望 NF_dB, 期望增益_dB)。
#: NF_dB 由独立 Friis 闭式手算（F_total = F1 + Σ(Fi-1)/ΠG_pre），
#: 见 test_budget.py 既有 2.3 手算例同源；None = 只做参考实现对拍。
_TEXTBOOK_CASES = [
    ([(10.0, 3.0), (20.0, 6.0)], 3.6047, 30.0),                 # F=1.99526+0.29811=2.29337
    ([(20.0, 1.5), (-3.0, 3.0), (10.0, 7.0)], 1.7683, 27.0),    # LNA+滤波+混频
    ([(-3.0, 3.0), (20.0, 1.5)], 4.5000, 17.0),                 # 电缆在前
    ([(13.0, 1.2), (25.0, 4.0), (-7.0, 7.0), (10.0, 5.0)], 1.4500, 41.0),
]


def _friis_reference(stages):
    """独立参考实现：直接展开 Friis 求和（不复用 budget.py）。"""
    f_total = 0.0
    g_lin = 1.0
    for idx, (gain_db, nf_db) in enumerate(stages):
        f = 10.0 ** (nf_db / 10.0)
        f_total = f if idx == 0 else f_total + (f - 1.0) / g_lin
        g_lin *= 10.0 ** (gain_db / 10.0)
    return 10.0 * math.log10(f_total), 10.0 * math.log10(g_lin)


def _cascade(stages):
    """用 LinkBudget 跑一条级联链。"""
    budget = LinkBudget()
    for i, (gain_db, nf_db) in enumerate(stages):
        budget.add_stage(f"S{i}", gain_db=gain_db, nf_db=nf_db)
    return budget.compute()


class TestTextbookCascadeC16:
    """C16 验收：教科书级联测例对拍 ±0.1dB。"""

    @pytest.mark.parametrize("stages,expected_nf_db,expected_gain_db", _TEXTBOOK_CASES)
    def test_within_0p1_db_of_textbook_table(self, stages, expected_nf_db, expected_gain_db):
        r = _cascade(stages)
        ref_nf, ref_gain = _friis_reference(stages)
        assert abs(r.cascade_gain_db - ref_gain) < 1e-9
        assert abs(r.cascade_gain_db - expected_gain_db) < 0.1
        assert abs(r.cascade_nf_db - ref_nf) < 0.1
        if expected_nf_db is not None:
            assert abs(r.cascade_nf_db - expected_nf_db) < 0.1

    def test_friis_two_stage_hand_value(self):
        """教科书画线：F = 2 + (4-1)/10 = 2.3 口径（NF1=3dB→F1=1.99526）。"""
        r = _cascade([(10.0, 3.0), (20.0, 6.0)])
        assert abs(r.cascade_nf_db - 3.6047) < 0.1

    def test_existing_p1db_behaviour_unchanged(self):
        """收尾要求：既有级联函数行为不变（P1dB 逐级回推 + 取最小）。"""
        b = LinkBudget()
        b.add_stage("LNA", gain_db=20, nf_db=0.8, p1db_dbm=15)
        b.add_stage("PA", gain_db=25, nf_db=5, p1db_dbm=30)
        r = b.compute()
        assert abs(r.stages[0].p1db_dbm - 15.0) < 1e-9
        assert abs(r.stages[1].p1db_dbm - 10.0) < 1e-9  # 30 - 45 + 25
        assert abs(r.cascade_p1db_dbm - 10.0) < 1e-9
        assert abs(r.cascade_gain_db - 45.0) < 1e-9


# ─── P2：三阶截点级联（功率相加形式；裁判=独立参考实现 + 手算 + 恒等式）────────

def _ip3_reference(stages):
    """独立参考实现：1/IIP3_tot = Σᵢ (Πⱼ<ᵢ Gⱼ)/IIP3ᵢ，IIP3ᵢ=OIP3ᵢ−Gᵢ。

    stages: (gain_db, nf_db, oip3_dbm|None) 序列；不复用 budget.py 内核。
    返回 (iip3_dbm | None, oip3_dbm | None, gain_total_db)。
    """
    g_pre = 1.0
    inv = 0.0
    g_tot = 1.0
    for gain_db, _nf_db, oip3_dbm in stages:
        g_lin = 10.0 ** (gain_db / 10.0)
        if oip3_dbm is not None:
            iip3_in_mw = 10.0 ** ((oip3_dbm - gain_db) / 10.0)
            inv += g_pre / iip3_in_mw
        g_pre *= g_lin
        g_tot *= g_lin
    if inv == 0.0:
        return None, None, 10.0 * math.log10(g_tot)
    iip3_dbm = 10.0 * math.log10(1.0 / inv)
    return iip3_dbm, iip3_dbm + 10.0 * math.log10(g_tot), 10.0 * math.log10(g_tot)


class TestIp3Cascade:
    """P2 收口：三阶截点级联（oip3_dbm 字段此前已定义未消费）。"""

    def _cascade(self, stages):
        budget = LinkBudget()
        for i, (gain_db, nf_db, oip3_dbm) in enumerate(stages):
            budget.add_stage(f"S{i}", gain_db=gain_db, nf_db=nf_db,
                             oip3_dbm=oip3_dbm)
        return budget.compute()

    def test_two_stage_hand_calculation(self):
        """手算例：G1=10/OIP3_1=20、G2=20/OIP3_2=30。

        IIP3_1=10dBm(10mW)、IIP3_2=10dBm(10mW) →
        1/IIP3_tot = (1 + 10)/10mW → IIP3_tot = 1/1.1 mW ≈ −0.414 dBm；
        OIP3_tot = IIP3_tot + 30dB ≈ 29.59 dBm。
        """
        r = self._cascade([(10.0, 3.0, 20.0), (20.0, 6.0, 30.0)])
        assert r.cascade_iip3_dbm == pytest.approx(-0.4139, abs=0.01)
        assert r.cascade_oip3_dbm == pytest.approx(29.5861, abs=0.01)

    def test_reference_implementation_agreement(self):
        """独立参考实现对拍（同 _friis_reference 范式，#118）。"""
        cases = [
            [(10.0, 3.0, 20.0), (20.0, 6.0, 30.0)],
            [(20.0, 1.5, 35.0), (-3.0, 3.0, None), (10.0, 7.0, 25.0)],
            [(-2.0, 1.0, 50.0), (20.0, 1.5, 35.0), (-7.0, 7.0, 45.0),
             (10.0, 5.0, None)],
            [(25.0, 5.0, 45.0)],
        ]
        for stages in cases:
            r = self._cascade(stages)
            ref_iip3, ref_oip3, _g = _ip3_reference(stages)
            if ref_iip3 is None:
                assert r.cascade_iip3_dbm is None
                continue
            assert r.cascade_iip3_dbm == pytest.approx(ref_iip3, abs=1e-9)
            assert r.cascade_oip3_dbm == pytest.approx(ref_oip3, abs=1e-9)

    def test_input_output_identity(self):
        """恒等式：OIP3_tot − IIP3_tot == 总增益（线性域定义直接推出）。"""
        stages = [(10.0, 3.0, 20.0), (-2.0, 3.0, None), (20.0, 6.0, 30.0)]
        r = self._cascade(stages)
        assert (r.cascade_oip3_dbm - r.cascade_iip3_dbm) == pytest.approx(
            r.cascade_gain_db, abs=1e-9)

    def test_single_stage_is_own_value(self):
        """单级：IIP3=OIP3−G 自身，逐级字段同值。"""
        r = self._cascade([(20.0, 1.5, 35.0)])
        assert r.cascade_iip3_dbm == pytest.approx(15.0, abs=1e-9)
        assert r.cascade_oip3_dbm == pytest.approx(35.0, abs=1e-9)
        assert r.stages[0].cumulative_iip3_dbm == pytest.approx(15.0, abs=1e-9)
        assert r.stages[0].cumulative_oip3_dbm == pytest.approx(35.0, abs=1e-9)

    def test_stage_without_oip3_is_transparent(self):
        """无 oip3 级视为理想透明：透传损耗只改增益，不改级联 OIP3。"""
        # 滤波器(-2dB 无 IP3) 在放大器(20dB, OIP3=30) 前
        r = self._cascade([(-2.0, 2.0, None), (20.0, 1.5, 30.0)])
        # IIP3_tot = IIP3_amp_in / G_flt = (30−20=10dBm)/10^(−0.2) ≈ 12.0dBm
        assert r.cascade_iip3_dbm == pytest.approx(12.0, abs=0.01)
        # OIP3_tot = IIP3_tot + G_tot(18dB) = 30dBm（透明级不改 OIP3）
        assert r.cascade_oip3_dbm == pytest.approx(30.0, abs=0.01)

    def test_no_oip3_anywhere_is_none(self):
        """全链无 oip3 → 级联 IP3 如实 None（不硬造），空链亦然。"""
        r = self._cascade([(10.0, 3.0, None), (20.0, 6.0, None)])
        assert r.cascade_iip3_dbm is None
        assert r.cascade_oip3_dbm is None
        empty = LinkBudget().compute()
        assert empty.cascade_iip3_dbm is None
        assert empty.cascade_oip3_dbm is None

    def test_to_dict_carries_ip3_fields(self):
        r = self._cascade([(10.0, 3.0, 20.0), (20.0, 6.0, 30.0)])
        d = r.to_dict()
        assert "cascade_iip3_dbm" in d and "cascade_oip3_dbm" in d
        assert d["stages"][0]["oip3_dbm"] == 20.0
        assert d["stages"][0]["cumulative_oip3_dbm"] == pytest.approx(20.0)
        assert d["cascade_iip3_dbm"] == pytest.approx(-0.41, abs=0.01)

    def test_nonfinite_oip3_rejected(self):
        budget = LinkBudget()
        with pytest.raises(ValueError):
            budget.add_stage("bad", gain_db=10, nf_db=3,
                             oip3_dbm=float("nan"))


class TestBodeFanoLimit:
    """C16：Bode-Fano 匹配带宽极限（矩形近似闭式）。"""

    def test_parallel_rc_classic_example(self):
        """R=50Ω、C=1pF、|Γ|=1/3（VSWR≤2, RL=9.5424dB）→ Δf_max≈9.10GHz。"""
        lim = bode_fano_limit("parallel_rc", 50.0, 9.542425094393248, capacitance_f=1e-12)
        assert abs(lim.tau_s - 5.0e-11) < 1e-24
        expected = 1.0 / (2.0 * 5.0e-11 * math.log(3.0))
        assert abs(lim.max_bandwidth_hz - expected) < 1.0
        assert abs(lim.max_bandwidth_hz / 1e9 - 9.1024) < 0.01
        assert abs(lim.gamma_max - 1.0 / 3.0) < 1e-12

    def test_series_rl_classic_example(self):
        """R=50Ω、L=1nH → τ=L/R=20ps；RL=10dB → Δω·ln10/2 ≤ π/τ。"""
        lim = bode_fano_limit("series_rl", 50.0, 10.0, inductance_h=1e-9)
        assert abs(lim.tau_s - 2.0e-11) < 1e-24
        expected = 1.0 / (2.0 * 2.0e-11 * math.log(10.0) / 2.0)
        assert abs(lim.max_bandwidth_hz - expected) < 1.0
        assert abs(lim.max_bandwidth_hz / 1e10 - 2.17147) < 1e-3

    def test_integral_bound_is_pi_over_tau(self):
        assert abs(bode_fano_integral_bound(5.0e-11) - math.pi / 5.0e-11) < 1e-3

    def test_rectangular_area_identity(self):
        """恒等式 Δf_max·2π·ln(1/Γmax) == π/τ（矩形近似闭式自洽）。"""
        lim = bode_fano_limit("parallel_rc", 75.0, 15.0, capacitance_f=2.2e-12)
        area = lim.return_loss_db * math.log(10.0) / 20.0
        product = lim.max_bandwidth_hz * 2.0 * math.pi * area
        assert abs(product / lim.integral_bound_rad_s - 1.0) < 1e-12

    def test_bandwidth_decreases_with_return_loss(self):
        bws = [bode_fano_max_bandwidth(5.0e-11, rl) for rl in (3.0, 6.0, 10.0, 20.0, 30.0)]
        assert all(x > y for x, y in pairwise(bws))

    def test_bandwidth_decreases_with_tau(self):
        bws = [bode_fano_max_bandwidth(tau, 10.0) for tau in (1e-11, 5e-11, 1e-10)]
        assert all(x > y for x, y in pairwise(bws))

    def test_series_and_parallel_capacitor_share_tau(self):
        a = bode_fano_limit("parallel_rc", 50.0, 10.0, capacitance_f=1e-12)
        b = bode_fano_limit("series_rc", 50.0, 10.0, capacitance_f=1e-12)
        c = bode_fano_limit("parallel_rl", 50.0, 10.0, inductance_h=1e-9)
        d = bode_fano_limit("series_rl", 50.0, 10.0, inductance_h=1e-9)
        assert abs(a.max_bandwidth_hz - b.max_bandwidth_hz) < 1e-3
        assert abs(c.max_bandwidth_hz - d.max_bandwidth_hz) < 1e-3

    def test_feasibility_boundary_just_within_and_just_over(self):
        lim = bode_fano_limit("parallel_rc", 50.0, 10.0, capacitance_f=1e-12)
        exact = lim.max_bandwidth_hz
        assert lim.within_limit(exact) is True
        assert lim.verdict(exact).within_limit is True
        assert lim.within_limit(exact * (1.0 - 1e-9)) is True
        assert lim.within_limit(exact * (1.0 + 1e-9)) is False
        v = lim.verdict(exact * 1.10)
        assert v.within_limit is False
        assert abs(v.usage_ratio - 1.10) < 1e-9
        assert v.margin_hz < 0.0

    def test_zero_target_bandwidth_is_trivially_within(self):
        lim = bode_fano_limit("series_rl", 50.0, 10.0, inductance_h=1e-9)
        assert lim.within_limit(0.0) is True
        assert lim.verdict(0.0).usage_ratio == 0.0

    def test_gamma_from_return_loss(self):
        assert abs(gamma_from_return_loss(9.542425094393248) - 1.0 / 3.0) < 1e-12
        assert abs(gamma_from_return_loss(20.0) - 0.1) < 1e-12
        assert abs(gamma_from_return_loss(1e-12) - 1.0) < 1e-9

    def test_extreme_return_loss_does_not_underflow(self):
        """Γmax 在高回波损耗下下溢为 0——带宽闭式仍须有限正值。"""
        tau, rl = 5.0e-11, 8000.0
        expected = 1.0 / (2.0 * tau * rl * math.log(10.0) / 20.0)
        bw = bode_fano_max_bandwidth(tau, rl)
        assert math.isfinite(bw) and bw > 0.0
        assert abs(bw / expected - 1.0) < 1e-12
        assert gamma_from_return_loss(rl) == 0.0  # 记录下溢事实

    def test_invalid_return_loss_raises(self):
        for bad in (0.0, -1.0, float("inf")):
            with pytest.raises(ValueError):
                bode_fano_max_bandwidth(5.0e-11, bad)

    def test_invalid_tau_raises(self):
        for bad in (0.0, -5e-11, float("nan")):
            with pytest.raises(ValueError):
                bode_fano_integral_bound(bad)

    def test_invalid_resistance_raises(self):
        for bad in (0.0, -50.0):
            with pytest.raises(ValueError):
                bode_fano_limit("parallel_rc", bad, 10.0, capacitance_f=1e-12)

    def test_wrong_or_missing_component_raises(self):
        with pytest.raises(ValueError):
            bode_fano_limit("parallel_rc", 50.0, 10.0)  # 缺 C
        with pytest.raises(ValueError):
            bode_fano_limit("parallel_rc", 50.0, 10.0, capacitance_f=1e-12, inductance_h=1e-9)
        with pytest.raises(ValueError):
            bode_fano_limit("series_rl", 50.0, 10.0, capacitance_f=1e-12)
        with pytest.raises(ValueError):
            bode_fano_limit("parallel_rc", 50.0, 10.0, capacitance_f=0.0)

    def test_unknown_load_kind_raises(self):
        with pytest.raises(ValueError):
            bode_fano_time_constant("parallel_lc", 50.0, capacitance_f=1e-12)

    def test_invalid_target_bandwidth_raises(self):
        lim = bode_fano_limit("parallel_rc", 50.0, 10.0, capacitance_f=1e-12)
        for bad in (-1.0, float("inf"), float("nan")):
            with pytest.raises(ValueError):
                lim.verdict(bad)

    def test_determinism_repeated_calls_identical(self):
        a = bode_fano_limit("parallel_rc", 50.0, 12.0, capacitance_f=1.5e-12)
        b = bode_fano_limit("parallel_rc", 50.0, 12.0, capacitance_f=1.5e-12)
        assert a == b
        assert a.to_dict() == b.to_dict()
        assert bode_fano_max_bandwidth(5e-11, 12.0) == bode_fano_max_bandwidth(5e-11, 12.0)

    def test_to_dict_and_fractional_bandwidth(self):
        lim = bode_fano_limit("series_rl", 50.0, 10.0, inductance_h=1e-9)
        d = lim.to_dict()
        assert d["load_kind"] == "series_rl"
        assert abs(d["max_bandwidth_hz"] - lim.max_bandwidth_hz) < 1e-9
        assert abs(d["integral_bound_rad_s"] - math.pi / lim.tau_s) < 1e-9
        assert abs(lim.fractional_bandwidth(2.4e9) - lim.max_bandwidth_hz / 2.4e9) < 1e-12


class TestLoadedUnloadedQ:
    """C16：有载/无载 Q 提取（对称双端口插损法）。"""

    def test_loaded_q_definition(self):
        assert abs(loaded_q(2.4e9, 100e6) - 24.0) < 1e-12

    def test_unloaded_q_analytic_three_db(self):
        ql, il = 24.0, 3.0
        expected = ql / (1.0 - 10.0 ** (-il / 20.0))
        got = unloaded_q_from_transmission(2.4e9, 100e6, il)
        assert abs(got - expected) < 1e-9
        assert abs(expected - 82.1765) < 1e-3

    def test_unloaded_q_recovers_symmetric_coupling_relation(self):
        """Q_u = Q_L·(1+2β)（对称双端口）→ 反提须还原 Q_u。"""
        for beta in (0.25, 0.5, 1.0, 2.5):
            qu = 200.0
            ql = qu / (1.0 + 2.0 * beta)
            s21 = 1.0 - ql / qu
            il_db = -20.0 * math.log10(s21)
            got = unloaded_q_from_transmission(1e9, 1e9 / ql, il_db)
            assert abs(got / qu - 1.0) < 1e-9

    def test_lossless_resonator_infinite_unloaded_q(self):
        assert unloaded_q_from_transmission(2.4e9, 100e6, 0.0) == math.inf

    def test_negative_insertion_loss_raises(self):
        with pytest.raises(ValueError):
            unloaded_q_from_transmission(2.4e9, 100e6, -1.0)

    def test_zero_bandwidth_raises(self):
        with pytest.raises(ValueError):
            loaded_q(2.4e9, 0.0)

    def test_coupling_coefficient_from_q(self):
        for beta in (0.5, 1.0, 2.0):
            qu = 100.0
            ql = qu / (1.0 + 2.0 * beta)
            assert abs(coupling_coefficient_from_q(ql, qu) - 2.0 * beta) < 1e-9

    def test_unloaded_q_below_loaded_raises(self):
        with pytest.raises(ValueError):
            coupling_coefficient_from_q(100.0, 50.0)

