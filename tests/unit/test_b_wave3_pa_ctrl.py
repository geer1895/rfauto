"""批 B Wave3 W3-CORE3：G11 余量 PA/控制件四键单测（pa_arch 原位扩展）。

ET 包络跟踪效率 / PIN 二极管限幅器 / 步进衰减器 / 倍频链预算。

裁判口径（#118 双路径：实现路线=pa_arch 闭式；独立第二路线=本文件
不同算法重算——scipy 数值积分/ABCD 级联/镜像阻抗回代/逐级恒等式，
2026-10-13 实现前独立复算后写死）：

- **ET**：能量口径 η=E[Pout]/E[Pdc] 闭式（式 ET1，含供电下限 f 与轨上
  硬削顶）vs scipy quad 数值积分 E[v²]/E[max(v,f)v]（不同算法）；
  结构锚 f=0 → π/4 与 PAPR 无关（ET 全部要义）、f=1 → 逐位等于定供
  B 类对照（无跟踪退化恒等式）；η_ET ≥ η_fixed 全域（供电恒不高于
  定供的单调性物理锚）。
- **PIN**：并联导纳二口 S 的 ABCD 独立级联第二路线；功率三分和=1
  （无源网络能量守恒精确）；R_on=Z0/2 → 吸收恰 50%（dP_abs/dy=0
  解析极值点）；门限 P_th=V_f²/(2Z0) 手工复算。
- **步进衰减器**：位组合=确定性算术（31→全位/10.5→量化余量 0.5）；
  逐位 π/T 电阻单源消费 rf_match（薄度：本面零公式复制）+镜像阻抗
  A=(N+1/N)/2 回代独立核对；worst-case/RSS 堆叠双口径手工复算。
- **倍频链**：逐级累计恒等式 Σ20log10(M_i)=20log10(∏M_i) 逐位；
  ×2×2 与 ×4 分解不变性；dBm 预算=算术；剩余相噪功率和手工复算。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from scipy.integrate import quad  # 第二路线数值积分

from rfauto.core.calc_families.pa_arch import (
    envelope_tracking_efficiency,
    multiplier_chain_budget,
    pin_diode_limiter,
    step_attenuator_design,
)
from rfauto.service.calculator_service import run_calculator

# ─── ET 独立复算锚（实现前 scipy/手工复算，六位小数写死）──────────────────────

PAPR_2_DB = 10.0 * math.log10(2.0)
PAPR_4_DB = 10.0 * math.log10(4.0)   # 6.0206 dB
PAPR_8_DB = 10.0 * math.log10(8.0)   # 9.0309 dB
ETA_PI4 = math.pi / 4.0


def _eta_et_numeric(f_floor: float, papr_lin: float) -> float:
    """独立第二路线：Rayleigh 包络能量口径数值积分（不同算法）。

    v=min(u,1)（u Rayleigh，E[u²]=1/ξ）、η=(π/4)E[v²]/E[max(v,f)v]。
    """
    def _num(expr) -> float:
        val, _ = quad(
            lambda u: expr(min(u, 1.0)) * 2.0 * papr_lin * u
            * math.exp(-papr_lin * u * u),
            0.0, 12.0, limit=200)
        return val

    return (math.pi / 4.0) * _num(lambda v: v * v) / _num(
        lambda v: max(v, f_floor) * v)


def _eta_fixed_supply(papr_lin: float) -> float:
    """定供 B 类对照（能量口径）：η=(π/4)E[v²]/E[v]。"""
    e = math.exp(-papr_lin)
    e_v2 = (1.0 - e) / papr_lin
    e_v = math.sqrt(math.pi) / (2.0 * math.sqrt(papr_lin)) * math.erf(
        math.sqrt(papr_lin))
    return (math.pi / 4.0) * e_v2 / e_v


class TestEnvelopeTrackingEfficiency:
    def test_f0_gives_pi4_regardless_of_papr(self):
        """结构锚：f=0 → η=π/4 逐位，与 PAPR 无关（ET 的全部要义）。"""
        for papr in (0.0, 3.0103, PAPR_2_DB, PAPR_4_DB, PAPR_8_DB, 12.0):
            out = envelope_tracking_efficiency(papr, 0.0)
            assert out["eta_et"] == pytest.approx(ETA_PI4, abs=1e-12)

    def test_f1_equals_fixed_supply_identity(self):
        """结构恒等：f=1（无跟踪退化）逐位等于定供 B 类对照。"""
        for papr in (1.0, PAPR_2_DB, PAPR_4_DB, 10.0):
            out = envelope_tracking_efficiency(papr, 1.0)
            assert out["eta_et"] == out["eta_fixed_supply"]
            assert out["eta_et"] == pytest.approx(
                _eta_fixed_supply(10.0 ** (papr / 10.0)), rel=1e-12)

    def test_closed_form_vs_numeric_integration(self):
        """#118 第二路线：闭式 vs scipy 数值积分 ≤1e-8（不同算法）。"""
        for f_floor, xi in ((0.1, 4.0), (0.2, 8.0), (0.3, 2.0),
                            (0.5, 4.0), (0.05, 6.309573444801933)):
            out = envelope_tracking_efficiency(10.0 * math.log10(xi),
                                               f_floor)
            num = _eta_et_numeric(f_floor, xi)
            assert out["eta_et"] == pytest.approx(num, abs=1e-8)

    def test_spec_anchors_six_digits(self):
        """规格锚（独立复算写死）：0.785188 / 0.773744 / 0.437042。"""
        out1 = envelope_tracking_efficiency(PAPR_4_DB, 0.1)
        assert out1["eta_et"] == pytest.approx(0.785188249699, abs=5e-12)
        out2 = envelope_tracking_efficiency(PAPR_8_DB, 0.2)
        assert out2["eta_et"] == pytest.approx(0.773743533759, abs=5e-12)
        out3 = envelope_tracking_efficiency(PAPR_4_DB, 1.0)
        assert out3["eta_et"] == pytest.approx(0.437041922847, abs=5e-12)

    def test_eta_ge_fixed_supply_monotone_in_floor(self):
        """物理单调：η_ET(f) ≥ η_fixed 全域（供电恒不高于定供）。"""
        for papr in (PAPR_2_DB, PAPR_4_DB, 12.0):
            eta_fixed = _eta_fixed_supply(10.0 ** (papr / 10.0))
            prev = None
            for i in range(11):
                out = envelope_tracking_efficiency(papr, i / 10.0)
                assert out["eta_et"] >= eta_fixed - 1e-12
                if prev is not None:
                    assert out["eta_et"] <= prev + 1e-12
                prev = out["eta_et"]

    def test_probability_fields_consistent(self):
        """clipping/supply_floor 概率字段与闭式自洽。"""
        out = envelope_tracking_efficiency(PAPR_4_DB, 0.1)
        assert out["clipping_prob"] == pytest.approx(
            math.exp(-4.0), abs=1e-12)
        assert out["supply_floor_prob"] == pytest.approx(
            1.0 - math.exp(-0.04), abs=1e-12)

    def test_domain_guards(self):
        for papr, f in ((-0.5, 0.1), (15.5, 0.1), (6.0, -0.1),
                        (6.0, 1.5)):
            with pytest.raises(ValueError, match="envelope_tracking"):
                envelope_tracking_efficiency(papr, f)
        for papr in (-0.5, 15.5):
            env = run_calculator("envelope_tracking_efficiency",
                                 {"papr_db": papr})
            assert env["ok"] is False and env.get("error")


# ─── PIN 限幅器独立复算锚 ─────────────────────────────────────────────────────

def _shunt_s_abcd(y_norm: complex) -> tuple[complex, complex]:
    """独立第二路线：ABCD [1,0;y,1] 通用二口 S 变换（非捷径式）。"""
    a, b, c, d = 1.0 + 0j, 0j, y_norm, 1.0 + 0j
    denom = a + b + c + d
    s11 = (a + b - c - d) / denom
    s21 = 2.0 * (a * d - b * c) / denom
    return s11, s21


class TestPinDiodeLimiter:
    def test_off_state_vs_abcd_cascade(self):
        """关断态：捷径式 vs ABCD 级联第二路线逐位（rel 1e-12）。"""
        out = pin_diode_limiter(10.0, c_off_pf=0.1)
        y = 1j * 2.0 * math.pi * 10e9 * 0.1e-12 * 50.0
        s11_ref, s21_ref = _shunt_s_abcd(y)
        assert out["off_state"]["s11"]["mag"] == pytest.approx(
            abs(s11_ref), rel=1e-12)
        assert out["off_state"]["s21"]["mag"] == pytest.approx(
            abs(s21_ref), rel=1e-12)

    def test_off_state_spec_anchor(self):
        """规格锚：C=0.1pF@10GHz/50Ω → IL=0.105857 dB、|S21|=0.987887。"""
        out = pin_diode_limiter(10.0, c_off_pf=0.1)
        assert out["off_state"]["il_db"] == pytest.approx(
            0.105857213, abs=5e-9)
        assert out["off_state"]["s21"]["mag"] == pytest.approx(
            0.987886702, abs=5e-9)
        assert out["off_state"]["s11"]["mag"] == pytest.approx(
            0.155176880, abs=5e-9)

    def test_on_state_power_split_conservation(self):
        """功率三分和=1 逐位（无源网络能量守恒）+ R_on=1Ω 规格锚。"""
        out = pin_diode_limiter(10.0, r_on_ohm=1.0)
        ps = out["on_state"]["power_split"]
        assert ps["sum"] == pytest.approx(1.0, abs=1e-12)
        assert ps["reflected_frac"] == pytest.approx(0.924556213,
                                                     abs=5e-9)
        assert ps["leaked_frac"] == pytest.approx(0.001479290, abs=5e-9)
        assert ps["absorbed_frac"] == pytest.approx(0.073964497,
                                                    abs=5e-9)
        assert out["on_state"]["iso_db"] == pytest.approx(
            20.0 * math.log10(26.0), abs=5e-9)

    def test_absorption_maximum_at_r_on_half_z0(self):
        """解析极值：R_on=Z0/2（y=2）→ 吸收恰 50%（dP/dy=0 唯一极大）。"""
        out = pin_diode_limiter(10.0, r_on_ohm=25.0)
        ps = out["on_state"]["power_split"]
        assert ps["absorbed_frac"] == pytest.approx(0.5, abs=1e-12)
        assert out["on_state"]["s21"]["mag"] == pytest.approx(
            0.5, abs=1e-12)
        # 两侧吸收单调下降（y=1 → 4/9、y=4 → 16/36）
        lo = pin_diode_limiter(10.0, r_on_ohm=50.0)
        hi = pin_diode_limiter(10.0, r_on_ohm=12.5)
        assert lo["on_state"]["power_split"]["absorbed_frac"] == (
            pytest.approx(4.0 / 9.0, abs=1e-12))
        assert hi["on_state"]["power_split"]["absorbed_frac"] == (
            pytest.approx(16.0 / 36.0, abs=1e-12))

    def test_reciprocity_and_passivity_both_states(self):
        """互易（S11=S22、S12=S21 结构恒等）+ 无源（|S|≤1）两态。"""
        for kwargs in ({"c_off_pf": 0.1}, {"r_on_ohm": 1.0},
                       {"r_on_ohm": 25.0}, {"c_off_pf": 1.0}):
            out = pin_diode_limiter(10.0, **kwargs)
            assert out["identities"]["reciprocal"] is True
            assert out["identities"]["energy_conserved"] is True
            for state in ("off_state", "on_state"):
                s11 = out[state]["s11"]["mag"]
                s21 = out[state]["s21"]["mag"]
                assert 0.0 <= s11 <= 1.0 + 1e-12
                assert 0.0 <= s21 <= 1.0 + 1e-12

    def test_threshold_first_order(self):
        """门限一阶估计：V_f=0.7/50Ω → P_th=4.9mW=6.901961 dBm。"""
        out = pin_diode_limiter(10.0)
        assert out["threshold"]["p_th_w"] == pytest.approx(
            0.49 / 100.0, rel=1e-12)
        assert out["threshold"]["p_th_dbm"] == pytest.approx(
            10.0 * math.log10(4.9), abs=1e-9)

    def test_il_monotone_in_frequency_and_c(self):
        """插损随频率/电容单调增（关断态并联容性路径物理）。"""
        il_prev = 0.0
        for f in (1.0, 5.0, 10.0, 30.0):
            il = pin_diode_limiter(f, c_off_pf=0.1)["off_state"]["il_db"]
            assert il > il_prev
            il_prev = il
        il_prev = 0.0
        for c in (0.01, 0.1, 1.0):
            il = pin_diode_limiter(10.0, c_off_pf=c)["off_state"]["il_db"]
            assert il > il_prev
            il_prev = il

    def test_domain_guards(self):
        for kwargs in ({"f_ghz": 0.0}, {"f_ghz": -1.0},
                       {"f_ghz": 10.0, "r_on_ohm": 0.0},
                       {"f_ghz": 10.0, "c_off_pf": -0.1},
                       {"f_ghz": 10.0, "z0_ohm": 0.0},
                       {"f_ghz": 10.0, "v_forward_v": -0.7}):
            with pytest.raises(ValueError, match="pin_diode_limiter"):
                pin_diode_limiter(**kwargs)


# ─── 步进衰减器独立复算锚 ─────────────────────────────────────────────────────

class TestStepAttenuatorDesign:
    def test_full_range_exact_decomposition(self):
        """31dB 目标 5 位 LSB=1 → 全位 engaged、realized=31、residual=0。"""
        out = step_attenuator_design(31.0)
        assert out["range_db"] == pytest.approx(31.0, abs=1e-12)
        assert out["realized_db"] == pytest.approx(31.0, abs=1e-12)
        assert out["residual_db"] == pytest.approx(0.0, abs=1e-12)
        assert out["engaged_bits"] == [True] * 5
        assert out["n_engaged"] == 5
        assert len(out["sections"]) == 5

    def test_quantization_residual_is_explicit(self):
        """量化余量如实输出：10.5 → realized=10、residual=0.5。"""
        out = step_attenuator_design(10.5)
        assert out["realized_db"] == pytest.approx(10.0, abs=1e-12)
        assert out["residual_db"] == pytest.approx(0.5, abs=1e-12)

    def test_bit_pattern_binary_arithmetic(self):
        """位组合=目标步数的二进制表示（12 = 4+8 → 位 2/3）。"""
        out = step_attenuator_design(12.0)
        assert out["engaged_bits"] == [False, False, True, True, False]
        assert out["n_engaged"] == 2
        assert out["realized_db"] == pytest.approx(12.0, abs=1e-12)

    def test_pad_single_source_and_image_impedance(self):
        """单源薄度+镜像阻抗回代：π 节 10dB/50Ω（单节链 LSB=10dB）→
        71.151/96.248Ω，A=(N+1/N)/2 回代（第二路线）。"""
        from rfauto.core.calc_families.rf_match import attenuator_pi

        out = step_attenuator_design(10.0, step_db=10.0, n_bits=1,
                                     pad_topology="pi")
        sec = out["sections"][0]
        ref = attenuator_pi(10.0, 50.0)
        assert sec["r_series_ohm"] == ref["r_series_mid_ohm"]
        assert sec["r_shunt_ohm"] == ref["r_shunt_end_ohm"]
        assert sec["r_series_ohm"] == pytest.approx(71.151, abs=5e-3)
        assert sec["r_shunt_ohm"] == pytest.approx(96.248, abs=5e-2)
        n = 10.0 ** (10.0 / 20.0)
        a_img = 1.0 + sec["r_series_ohm"] / sec["r_shunt_ohm"]
        assert a_img == pytest.approx((n + 1.0 / n) / 2.0, rel=1e-4)

    def test_t_topology_routes_to_attenuator_t(self):
        """T 拓扑走 attenuator_t 单源（字段名随拓扑；单节链 LSB=3dB）。"""
        from rfauto.core.calc_families.rf_match import attenuator_t

        out = step_attenuator_design(3.0, step_db=3.0, n_bits=1,
                                     pad_topology="t")
        sec = out["sections"][0]
        ref = attenuator_t(3.0, 50.0)
        assert sec["r_series_ohm"] == ref["r_series_arm_ohm"]
        assert sec["r_shunt_ohm"] == ref["r_shunt_mid_ohm"]

    def test_stackup_worst_and_rss(self):
        """堆叠双口径：[0.2,0.2,0.3,0.5,0.8] 全位 → worst 2.0/RSS
        1.029563（手工复算）；仅 engaged 位计入。"""
        acc = [0.2, 0.2, 0.3, 0.5, 0.8]
        out = step_attenuator_design(31.0, per_step_accuracy_db=acc)
        assert out["worst_case_error_db"] == pytest.approx(2.0, abs=1e-12)
        assert out["rss_error_db"] == pytest.approx(
            math.sqrt(1.06), abs=5e-9)
        # 部分位：目标 3 → 位 0/1 engaged → worst=0.4/RSS=√0.08
        out3 = step_attenuator_design(3.0, per_step_accuracy_db=acc)
        assert out3["worst_case_error_db"] == pytest.approx(0.4, abs=1e-12)
        assert out3["rss_error_db"] == pytest.approx(
            math.sqrt(0.08), abs=5e-9)

    def test_zero_target_all_bits_off(self):
        """0dB 目标合法：全位 off、无衰减节、residual=0。"""
        out = step_attenuator_design(0.0)
        assert out["realized_db"] == pytest.approx(0.0, abs=1e-12)
        assert out["n_engaged"] == 0
        assert out["sections"] == []

    def test_range_overflow_rejected(self):
        """超量程显式拒绝（不回卷）。"""
        with pytest.raises(ValueError, match="量程"):
            step_attenuator_design(32.0, step_db=1.0, n_bits=5)

    def test_domain_guards(self):
        for kwargs in ({"attenuation_db": -1.0},
                       {"attenuation_db": 5.0, "step_db": 0.0},
                       {"attenuation_db": 5.0, "n_bits": True},
                       {"attenuation_db": 5.0, "n_bits": 9},
                       {"attenuation_db": 5.0, "n_bits": 1.5},
                       {"attenuation_db": 5.0, "z0_ohm": 0.0},
                       {"attenuation_db": 5.0, "pad_topology": "ladder"},
                       {"attenuation_db": 5.0,
                        "per_step_accuracy_db": [0.2] * 3},
                       {"attenuation_db": 5.0,
                        "per_step_accuracy_db": [0.2, -0.1, 0.2, 0.2,
                                                 0.2]}):
            with pytest.raises(ValueError, match="step_attenuator"):
                step_attenuator_design(**kwargs)
        env = run_calculator("step_attenuator_design",
                             {"attenuation_db": 5.0, "n_bits": 0})
        assert env["ok"] is False and env.get("error")


# ─── 倍频链独立复算锚 ─────────────────────────────────────────────────────────

class TestMultiplierChainBudget:
    def test_frequency_and_stage_table(self):
        """×2×3×2 → N=12、f_out=12·f_in、逐级累计倍次/频率。"""
        out = multiplier_chain_budget(1.0, [2, 3, 2])
        assert out["n_total"] == 12
        assert out["f_out_ghz"] == pytest.approx(12.0, abs=1e-12)
        assert [s["cum_n"] for s in out["stages"]] == [2, 6, 12]
        assert [s["f_out_ghz"] for s in out["stages"]] == [
            pytest.approx(v, abs=1e-12) for v in (2.0, 6.0, 12.0)]

    def test_phase_noise_law_and_identity(self):
        """20log10(N) 律 + 逐级累计恒等式 Σ20log10(M_i)=20log10(N) 逐位。"""
        out = multiplier_chain_budget(1.0, [2, 3, 2])
        assert out["pn_degradation_ideal_db"] == pytest.approx(
            20.0 * math.log10(12.0), abs=1e-9)
        assert out["pn_identity_check"] is True
        cum = 0.0
        for s, m in zip(out["stages"], (2, 3, 2), strict=True):
            cum += 20.0 * math.log10(m)
            assert s["ideal_pn_deg_db_cum"] == pytest.approx(
                cum, abs=1e-9)

    def test_factorization_invariance(self):
        """分解不变性：×2×2 与 ×4 单级同 20log10=12.041200 dB。"""
        a = multiplier_chain_budget(1.0, [2, 2])
        b = multiplier_chain_budget(1.0, [4])
        assert a["pn_degradation_ideal_db"] == pytest.approx(
            b["pn_degradation_ideal_db"], abs=1e-12)
        assert a["pn_degradation_ideal_db"] == pytest.approx(
            12.041199826559248, abs=1e-9)

    def test_power_budget_and_losses(self):
        """dBm 预算：0dBm + [7,7,3]dB → −17dBm；累计损耗列。"""
        out = multiplier_chain_budget(1.0, [2, 3, 2],
                                      stage_loss_db=[7.0, 7.0, 3.0],
                                      pin_dbm=0.0)
        assert out["total_conversion_loss_db"] == pytest.approx(
            17.0, abs=1e-12)
        assert out["pout_dbm"] == pytest.approx(-17.0, abs=1e-12)
        assert [s["cum_loss_db"] for s in out["stages"]] == [
            pytest.approx(v, abs=1e-12) for v in (7.0, 14.0, 17.0)]

    def test_residual_pn_power_sum(self):
        """剩余相噪地板功率和：[−130,−128] → 10log10(10^−13+10^−12.8)
        =−125.875574（手工复算）；缺省 null 不冒充。"""
        out = multiplier_chain_budget(
            1.0, [2, 2], stage_residual_pn_dbc_hz=[-130.0, -128.0])
        expect = 10.0 * math.log10(10.0 ** -13.0 + 10.0 ** -12.8)
        assert out["residual_pn_sum_dbc"] == pytest.approx(
            expect, abs=1e-9)
        assert out["residual_pn_sum_dbc"] == pytest.approx(
            -125.875573972, abs=5e-9)
        bare = multiplier_chain_budget(1.0, [2, 2])
        assert bare["residual_pn_sum_dbc"] is None

    def test_prime_factorization(self):
        out = multiplier_chain_budget(1.0, [2, 3, 2])
        assert out["prime_factorization"] == [2, 2, 3]
        assert math.prod(out["prime_factorization"]) == out["n_total"]

    def test_ideal_default_zero_loss(self):
        """缺省理想档：全 0 损耗、无 pin → pout 字段缺席（不冒充）。"""
        out = multiplier_chain_budget(10.0, [4, 5])
        assert out["total_conversion_loss_db"] == 0.0
        assert out["f_out_ghz"] == pytest.approx(200.0, abs=1e-9)
        assert "pout_dbm" not in out

    def test_domain_guards(self):
        for kwargs in ({"f_in_ghz": 0.0, "factors": [2]},
                       {"f_in_ghz": 1.0, "factors": []},
                       {"f_in_ghz": 1.0, "factors": [2, 1]},
                       {"f_in_ghz": 1.0, "factors": [65]},
                       {"f_in_ghz": 1.0, "factors": [2] * 9},
                       {"f_in_ghz": 1.0, "factors": [64] * 8},
                       {"f_in_ghz": 1.0, "factors": [2, 3],
                        "stage_loss_db": [7.0]},
                       {"f_in_ghz": 1.0, "factors": [2, 3],
                        "stage_loss_db": [7.0, -1.0]},
                       {"f_in_ghz": 1.0, "factors": [2, 3],
                        "stage_residual_pn_dbc_hz": [-130.0]}):
            with pytest.raises(ValueError, match="multiplier_chain"):
                multiplier_chain_budget(**kwargs)
        for factors in ([2, True], [2, 1.5], ["2", 3]):
            env = run_calculator("multiplier_chain_budget",
                                 {"f_in_ghz": 1.0, "factors": factors})
            assert env["ok"] is False and env.get("error")


# ─── 注册表/service 面交叉钉 ─────────────────────────────────────────────────

class TestRegistryIntegration:
    def test_four_keys_registered_and_grouped(self):
        from rfauto.core.calculators import (
            CALC_GROUP_TABLE,
            CALCULATOR_REGISTRY,
        )

        rows = {r["name"]: r for r in
                CALCULATOR_REGISTRY.describe(include_experimental=True)}
        for key in ("envelope_tracking_efficiency", "pin_diode_limiter",
                    "step_attenuator_design", "multiplier_chain_budget"):
            assert key in rows
            assert rows[key]["group"] == CALC_GROUP_TABLE[key]
            assert rows[key]["group"] in ("收发链路·频综",
                                          "匹配·功分·衰减·耦合")

    def test_json_envelope_contract(self):
        import json

        for key, params in (
            ("envelope_tracking_efficiency",
             {"papr_db": 6.020599913279624, "supply_floor_frac": 0.1}),
            ("pin_diode_limiter", {"f_ghz": 10.0}),
            ("step_attenuator_design", {"attenuation_db": 10.5}),
            ("multiplier_chain_budget",
             {"f_in_ghz": 1.0, "factors": [2, 3, 2]}),
        ):
            env = run_calculator(key, params)
            assert env["ok"] is True, f"{key}: {env!r}"
            json.dumps(env, ensure_ascii=False, allow_nan=False)

    def test_deterministic_repeat_calls(self):
        for key, params in (
            ("envelope_tracking_efficiency",
             {"papr_db": 6.020599913279624, "supply_floor_frac": 0.1}),
            ("pin_diode_limiter", {"f_ghz": 10.0}),
            ("step_attenuator_design", {"attenuation_db": 10.5}),
            ("multiplier_chain_budget",
             {"f_in_ghz": 1.0, "factors": [2, 3, 2]}),
        ):
            a = run_calculator(key, params)
            b = run_calculator(key, params)
            assert json.dumps(a, sort_keys=True) == json.dumps(
                b, sort_keys=True)
