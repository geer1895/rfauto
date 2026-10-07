"""MT-5 PLL 三阶环路滤波器综合锚树（round17 §二 MT-5，规格验收+闭式恒等裁判）。

裁判口径（#118：闭式恒等式/独立数值路径，不赌文献数字——规格未给数值
算例，SNAA106C 仅指方法论）：

1. 规格验收面：综合 → 回代 open_loop_transfer 复现目标 f_c/PM（实测
   残差 1e-16/1e-14 量级，门 1e-9/1e-8）；
2. Gardner 二阶几何中值极限（r→0⁺：ωc²T1T2=uv→1、u=tan((90°−PM)/2)
   闭式回收——solve_peak_placement 数学核对 r>0 全域有效，r→0 取极限锚）；
3. 峰值相位放置：PM(0.95ωc)<PM(ωc)>PM(1.05ωc) 真峰邻域裁判+二阶差分
   |pm_peak_residual|<1e-6 deg；
4. 闭环恒等：|H(jωc)|=1/(2sin(PM/2))（numpy 复数路径 vs 闭式）、|H(0)|=1
   极限、bw_3db 独立路径复核（|H(bw)|=1/√2）；
5. CP 噪声整形：低频增益 N/Kφ 恒等+带外低通滚降（10fc 已 −31dB、
   100fc −87dB 实测）；
6. 元件闭式重构恒等（C1+C2=A0 / R2·C2=T2 / R2·C1C2/(C1+C2)=T1 /
   R3·C3=T3，全 1e-12——二阶主网络精确反演的代数恒等式）；
7. |G| 严格单调降（穿越唯一性前提，模块头预声明证明的数值面）；
8. 负例域守卫（PM/r/f_c/增益数/c3_frac/r3_ohm/NaN/bool/str/不可达窗/
   频率数组越界显式拒绝）；
9. 注册键契约（ok/有限/JSON/逐字节确定性/未知参/缺参/域错误 ok=False）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.pll_loop_filter import (
    LoopFilterSynthesis,
    closed_loop_bw_3db,
    closed_loop_transfer,
    cp_noise_to_out_transfer,
    crossover_and_pm,
    error_transfer,
    loop_filter_impedance,
    open_loop_transfer,
    solve_peak_placement,
    synthesize_loop_filter,
)
from rfauto.service.calculator_service import run_calculator

# 名义设计点（与 test_physics_invariants 输入表同源）：100 kHz 带宽 /
# PM 50° / Kφ=0.8 mA/rad / Kvco=40 MHz/V / N=40——经典整数 N 分频环量级
NOMINAL: dict = {
    "f_c_hz": 1.0e5,
    "phase_margin_deg": 50.0,
    "kp_a_per_rad": 8.0e-4,
    "kvco_hz_per_v": 4.0e7,
    "n_div": 40.0,
}

EXPECTED_FIELDS = frozenset({
    "f_c_target_hz", "pm_target_deg", "kp_a_per_rad", "kvco_hz_per_v",
    "n_div", "t3_t1_ratio", "t1_s", "t2_s", "t3_s", "a0_f",
    "c1_f", "c2_f", "r2_ohm", "c3_f", "r3_ohm",
    "f_crossover_hz", "phase_margin_deg", "fc_rel_error", "pm_abs_error_deg",
    "pm_peak_residual_deg", "closed_loop_bw_3db_hz", "h_at_crossover_db",
    "c3_loading_ratio",
})

_TWO_PI = 2.0 * math.pi


def _nominal_synthesis(**overrides) -> LoopFilterSynthesis:
    kw = dict(NOMINAL)
    kw.update(overrides)
    return synthesize_loop_filter(**kw)


def _pm_deg_numeric(freqs_hz: float, syn: LoopFilterSynthesis) -> float:
    """PM(f) 的独立数值路径（numpy 复角 vs 内核 atan 闭式，双路径互证）。

    稳定设计 arg G(jω) ∈ (−180°,−90°) 无卷绕；pm = arg + 180°。
    """
    g = open_loop_transfer(
        np.array([freqs_hz]), syn.kp_a_per_rad, syn.kvco_hz_per_v, syn.n_div,
        syn.a0_f, syn.t1_s, syn.t2_s, syn.t3_s)
    return math.degrees(float(np.angle(g[0]))) + 180.0


def _h_mag(freqs_hz: float, syn: LoopFilterSynthesis) -> float:
    """|H(f)| 独立数值路径（numpy 复数传函 vs 内核标量 |G|/|1+G|）。"""
    h = closed_loop_transfer(
        np.array([freqs_hz]), syn.kp_a_per_rad, syn.kvco_hz_per_v, syn.n_div,
        syn.a0_f, syn.t1_s, syn.t2_s, syn.t3_s)
    return float(np.abs(h[0]))


# ─── 传函基本面 ──────────────────────────────────────────────────────────────


class TestOpenLoopTform:
    def setup_method(self):
        self.syn = _nominal_synthesis()

    def test_low_frequency_asymptote_pure_integrator(self):
        """f≪极点：|G| = K'/ω²（双积分器渐近）。

        容差=首阶修正 O(½(ωT2)²)（零点项展开）：frac=1e-3 → 3.6e-6 实测
        3.53e-6 / frac=1e-4 → 3.6e-8——门放一个量级，不赌逐位。
        """
        kv_rad = _TWO_PI * self.syn.kvco_hz_per_v
        k_prime = (self.syn.kp_a_per_rad * kv_rad
                   / (self.syn.n_div * self.syn.a0_f))
        for frac in (1.0e-3, 1.0e-4):
            f = frac * self.syn.f_c_target_hz
            g = open_loop_transfer(
                np.array([f]), self.syn.kp_a_per_rad, self.syn.kvco_hz_per_v,
                self.syn.n_div, self.syn.a0_f,
                self.syn.t1_s, self.syn.t2_s, self.syn.t3_s)
            ratio = float(np.abs(g[0])) * (_TWO_PI * f) ** 2 / k_prime
            lead = (_TWO_PI * f * self.syn.t2_s) ** 2
            assert abs(ratio - 1.0) < max(lead, 1.0e-9), (frac, ratio, lead)

    def test_high_frequency_asymptote_third_order_roll(self):
        """f≫全部转折：|G| = K'·T2/(T1·T3·ω³)（三阶滚降渐近）。

        容差=首阶修正 O(½(1/(ωT1)²+1/(ωT3)²))：frac=1e3 → 7.4e-5 实测
        同量级 / frac=1e4 → 7.4e-7。
        """
        kv_rad = _TWO_PI * self.syn.kvco_hz_per_v
        k_prime = (self.syn.kp_a_per_rad * kv_rad
                   / (self.syn.n_div * self.syn.a0_f))
        for frac in (1.0e3, 1.0e4):
            f = frac * self.syn.f_c_target_hz
            g = open_loop_transfer(
                np.array([f]), self.syn.kp_a_per_rad, self.syn.kvco_hz_per_v,
                self.syn.n_div, self.syn.a0_f,
                self.syn.t1_s, self.syn.t2_s, self.syn.t3_s)
            w = _TWO_PI * f
            ratio = (float(np.abs(g[0])) * self.syn.t1_s * self.syn.t3_s * w ** 3
                     / (k_prime * self.syn.t2_s))
            lead = 0.5 * ((1.0 / (w * self.syn.t1_s)) ** 2
                          + (1.0 / (w * self.syn.t3_s)) ** 2)
            assert abs(ratio - 1.0) < max(lead, 1.0e-9), (frac, ratio, lead)

    def test_impedance_integrator_scaling_below_poles(self):
        """Z ~ 1/(s·A0)（积分形）：Z(1Hz)/Z(10Hz)=10。

        相对偏差 = 首阶修正 ½·(w2²−w1²)·(T2²−T1²−T3²) ≈ 3.5e-8（实测
        同量级），门放 1e-7 相对。
        """
        z = loop_filter_impedance(
            np.array([1.0, 10.0]), self.syn.a0_f,
            self.syn.t1_s, self.syn.t2_s, self.syn.t3_s)
        ratio = float(np.abs(z[0] / z[1]))
        assert abs(ratio / 10.0 - 1.0) < 1.0e-7, ratio

    def test_error_transfer_complement_identity(self):
        """E = 1−H 逐点恒等（三函数同源自洽）。"""
        grid = np.array([10.0, 1.0e4, 1.0e5, 1.0e6, 1.0e8])
        h = closed_loop_transfer(grid, self.syn.kp_a_per_rad,
                                 self.syn.kvco_hz_per_v, self.syn.n_div,
                                 self.syn.a0_f, self.syn.t1_s,
                                 self.syn.t2_s, self.syn.t3_s)
        e = error_transfer(grid, self.syn.kp_a_per_rad, self.syn.kvco_hz_per_v,
                           self.syn.n_div, self.syn.a0_f, self.syn.t1_s,
                           self.syn.t2_s, self.syn.t3_s)
        assert float(np.max(np.abs((1.0 - h) - e))) < 1.0e-12

    def test_open_loop_mag_strictly_monotone(self):
        """|G| 严格单调降（穿越唯一性前提；密集对数网格有限差分全负）。"""
        fc = self.syn.f_c_target_hz
        grid = np.logspace(math.log10(fc * 1.0e-3), math.log10(fc * 1.0e3), 601)
        mag = np.abs(open_loop_transfer(
            grid, self.syn.kp_a_per_rad, self.syn.kvco_hz_per_v,
            self.syn.n_div, self.syn.a0_f, self.syn.t1_s,
            self.syn.t2_s, self.syn.t3_s))
        diffs = np.diff(np.log(mag))
        assert bool(np.all(diffs < 0.0)), float(np.max(diffs))

    def test_crossover_deterministic(self):
        fc1, pm1 = crossover_and_pm(
            self.syn.kp_a_per_rad, self.syn.kvco_hz_per_v, self.syn.n_div,
            self.syn.a0_f, self.syn.t1_s, self.syn.t2_s, self.syn.t3_s)
        fc2, pm2 = crossover_and_pm(
            self.syn.kp_a_per_rad, self.syn.kvco_hz_per_v, self.syn.n_div,
            self.syn.a0_f, self.syn.t1_s, self.syn.t2_s, self.syn.t3_s)
        assert fc1 == fc2 and pm1 == pm2


# ─── 综合主面：规格验收（回代复现 f_c/PM）───────────────────────────────────


class TestSynthesisBacksubstitution:
    """规格验收：synthesize → 回代 open_loop_transfer 复现目标 f_c/PM。"""

    @pytest.mark.parametrize(("pm_deg", "ratio"), [
        (30.0, 2.0), (45.0, 3.0), (50.0, 3.0), (65.5, 4.0),
        (70.0, 10.0), (80.0, 1.2),
    ])
    def test_backsubstitution_reproduces_targets(self, pm_deg, ratio):
        syn = _nominal_synthesis(phase_margin_deg=pm_deg, t3_t1_ratio=ratio)
        fc_num, pm_num = crossover_and_pm(
            syn.kp_a_per_rad, syn.kvco_hz_per_v, syn.n_div, syn.a0_f,
            syn.t1_s, syn.t2_s, syn.t3_s)
        assert abs(fc_num / syn.f_c_target_hz - 1.0) < 1.0e-9, fc_num
        assert abs(pm_num - pm_deg) < 1.0e-8, pm_num
        # 独立路径 1：目标频点直接复数求值 |G(jωc)|=1
        g = open_loop_transfer(
            np.array([syn.f_c_target_hz]), syn.kp_a_per_rad,
            syn.kvco_hz_per_v, syn.n_div, syn.a0_f,
            syn.t1_s, syn.t2_s, syn.t3_s)
        assert abs(float(np.abs(g[0])) - 1.0) < 1.0e-9
        # 独立路径 2：PM 经 numpy 复角（vs 内核 atan 闭式）
        assert abs(_pm_deg_numeric(syn.f_c_target_hz, syn) - pm_deg) < 1.0e-8

    def test_fractional_n_and_other_scale(self):
        """分数 N/另一参数组同精度（缩放不变性抽查）。"""
        syn = synthesize_loop_filter(4.0e6, 55.0, 5.0e-4, 1.0e8, 37.5,
                                     t3_t1_ratio=4.0)
        fc_num, pm_num = crossover_and_pm(
            syn.kp_a_per_rad, syn.kvco_hz_per_v, syn.n_div, syn.a0_f,
            syn.t1_s, syn.t2_s, syn.t3_s)
        assert abs(fc_num / 4.0e6 - 1.0) < 1.0e-9
        assert abs(pm_num - 55.0) < 1.0e-8

    def test_result_fields_and_ordering(self):
        syn = _nominal_synthesis()
        assert set(syn.to_dict()) == set(EXPECTED_FIELDS)
        assert syn.t1_s < syn.t2_s, "零点必须高于主极点（C1>0 前提）"
        assert syn.t3_s > syn.t1_s, "附加极点在主极点之外（r>1 约定）"
        for value in syn.to_dict().values():
            assert math.isfinite(value)


# ─── Gardner 二阶几何中值极限（放置数学核的解析回收）────────────────────────


class TestGardnerLimit:
    """r→0⁺ 逐位回到 Gardner 二阶放置：uv=ωc²T1T2→1、u=tan((90°−PM)/2)。"""

    @pytest.mark.parametrize("pm_deg", [30.0, 45.0, 52.0, 60.0, 75.0])
    def test_uv_unit_and_closed_form_u(self, pm_deg):
        u, v = solve_peak_placement(pm_deg, 1.0e-12)
        assert abs(u * v - 1.0) < 1.0e-10, (pm_deg, u * v)
        u_hand = math.tan(math.radians((90.0 - pm_deg) / 2.0))
        assert abs(u / u_hand - 1.0) < 1.0e-10, (pm_deg, u, u_hand)

    def test_pm_condition_exact_in_limit(self):
        """PM = 90°−2·atan(u)（r=0 闭式）逐位回收。"""
        for pm_deg in (40.0, 52.0, 65.0):
            u, _v = solve_peak_placement(pm_deg, 1.0e-12)
            pm_closed = 90.0 - 2.0 * math.degrees(math.atan(u))
            assert abs(pm_closed - pm_deg) < 1.0e-9, (pm_deg, pm_closed)

    def test_solve_math_domain_accepts_r_below_one(self):
        """放置数学核对 r>0 全域有效（r<1 属重参数化；综合面才收 r>1）。"""
        u, v = solve_peak_placement(50.0, 0.5)
        assert u > 0.0 and v >= 1.0


# ─── 峰值相位放置（dPM/dω|ωc=0）─────────────────────────────────────────────


class TestPeakPlacement:
    @pytest.mark.parametrize(("pm_deg", "ratio"), [(50.0, 3.0), (45.0, 5.0), (70.0, 8.0)])
    def test_crossover_sits_at_phase_peak(self, pm_deg, ratio):
        """PM(0.95ωc) < PM(ωc) > PM(1.05ωc)——真峰邻域裁判。"""
        syn = _nominal_synthesis(phase_margin_deg=pm_deg, t3_t1_ratio=ratio)
        wc = _TWO_PI * syn.f_c_target_hz
        pm_c = _pm_deg_numeric(syn.f_c_target_hz, syn)
        pm_lo = _pm_deg_numeric(0.95 * wc / _TWO_PI, syn)
        pm_hi = _pm_deg_numeric(1.05 * wc / _TWO_PI, syn)
        assert pm_lo < pm_c and pm_hi < pm_c, (pm_lo, pm_c, pm_hi)

    def test_peak_residual_field_tiny(self):
        """二阶差分残差（综合结果字段）|·| < 1e-6 deg（实测 ~1e-8）。"""
        syn = _nominal_synthesis()
        assert abs(syn.pm_peak_residual_deg) < 1.0e-6, syn.pm_peak_residual_deg


# ─── 闭环恒等式 ──────────────────────────────────────────────────────────────


class TestClosedLoopIdentities:
    def setup_method(self):
        self.syn = _nominal_synthesis()

    def test_h_at_crossover_closed_form(self):
        """|H(jωc)| = 1/(2·sin(PM/2))（|G(ωc)|=1 的纯数学推论）。"""
        expect = 1.0 / (2.0 * math.sin(math.radians(self.syn.phase_margin_deg) / 2.0))
        assert abs(_h_mag(self.syn.f_c_target_hz, self.syn) / expect - 1.0) < 1.0e-9
        # h_at_crossover_db = −20log10(2sin(PM/2)) ≡ +20log10(expect)
        assert abs(self.syn.h_at_crossover_db - 20.0 * math.log10(expect)) < 1.0e-12

    def test_dc_unity_gain_limit(self):
        """|H(0)|=1（II 型 DC 单位增益；f→0 极限数值面）。"""
        for frac in (1.0e-6, 1.0e-7):
            assert abs(_h_mag(frac * self.syn.f_c_target_hz, self.syn) - 1.0) < 1.0e-6

    def test_bw_3db_independent_path(self):
        """bw_3db 独立复核：|H(bw)|=1/√2（numpy 路径）+ 物理邻域带。"""
        bw = self.syn.closed_loop_bw_3db_hz
        fc = self.syn.f_c_target_hz
        assert abs(_h_mag(bw, self.syn) - 1.0 / math.sqrt(2.0)) < 1.0e-8
        assert 1.0 < bw / fc < 5.0, bw / fc
        bw2 = closed_loop_bw_3db(
            self.syn.kp_a_per_rad, self.syn.kvco_hz_per_v, self.syn.n_div,
            self.syn.a0_f, self.syn.t1_s, self.syn.t2_s, self.syn.t3_s)
        assert bw2 == bw


# ─── CP 噪声整形（低通+带内 N/Kφ）───────────────────────────────────────────


class TestCpNoiseShaping:
    def setup_method(self):
        self.syn = _nominal_synthesis()
        self.n_over_kp = self.syn.n_div / self.syn.kp_a_per_rad

    def _t_mag(self, *freqs: float) -> list[float]:
        t = cp_noise_to_out_transfer(
            np.array(freqs), self.syn.kp_a_per_rad, self.syn.kvco_hz_per_v,
            self.syn.n_div, self.syn.a0_f, self.syn.t1_s,
            self.syn.t2_s, self.syn.t3_s)
        return [float(x) for x in np.abs(t)]

    def test_inband_gain_is_n_over_kp(self):
        """带内增益 N/Kφ 恒等（|H(0)|=1 的 CP 口径）。"""
        (m,) = self._t_mag(1.0e-6 * self.syn.f_c_target_hz)
        assert abs(m / self.n_over_kp - 1.0) < 1.0e-9, m

    def test_lowpass_rolloff_shape(self):
        """带外滚降：10fc 已 −31dB、100fc −87dB（实测值带），且逐十倍程下降。"""
        fc = self.syn.f_c_target_hz
        m10, m100 = self._t_mag(10.0 * fc, 100.0 * fc)
        assert m10 / self.n_over_kp < 0.05, m10 / self.n_over_kp
        assert m100 / self.n_over_kp < 1.0e-4, m100 / self.n_over_kp
        assert m100 < m10

    def test_passband_flat_before_peak(self):
        """0.01fc 处仍 ≈N/Kφ（带内平坦）。"""
        (m,) = self._t_mag(0.01 * self.syn.f_c_target_hz)
        assert abs(m / self.n_over_kp - 1.0) < 1.0e-3, m / self.n_over_kp


# ─── 元件值闭式（二阶主网络精确反演恒等式）──────────────────────────────────


class TestComponentMapping:
    def test_reconstruction_identities_exact(self):
        """C1+C2=A0 / R2·C2=T2 / R2·C1C2/(C1+C2)=T1 / R3·C3=T3（1e-12）。"""
        syn = _nominal_synthesis()
        assert abs(syn.c1_f + syn.c2_f - syn.a0_f) / syn.a0_f < 1.0e-12
        assert abs(syn.r2_ohm * syn.c2_f - syn.t2_s) / syn.t2_s < 1.0e-12
        t1_back = syn.r2_ohm * syn.c1_f * syn.c2_f / (syn.c1_f + syn.c2_f)
        assert abs(t1_back - syn.t1_s) / syn.t1_s < 1.0e-12
        assert abs(syn.r3_ohm * syn.c3_f - syn.t3_s) / syn.t3_s < 1.0e-12

    def test_c3_default_frac_and_loading_ratio(self):
        """缺省 C3=c3_frac·A0 → loading ratio == c3_frac（精确）。"""
        syn = _nominal_synthesis(c3_frac=0.1)
        assert abs(syn.c3_f - 0.1 * syn.a0_f) / syn.a0_f < 1.0e-12
        assert abs(syn.c3_loading_ratio - 0.1) < 1.0e-12

    def test_r3_ohm_override_keeps_placement(self):
        """显式 R3：C3=T3/R3 精确；放置（T 参数）与 c3 面无关。"""
        base = _nominal_synthesis()
        syn = _nominal_synthesis(r3_ohm=200.0)
        assert abs(syn.c3_f - syn.t3_s / 200.0) < 1.0e-18 * 1.0e18
        assert syn.c3_f == syn.t3_s / 200.0
        assert (syn.t1_s, syn.t2_s, syn.t3_s) == (base.t1_s, base.t2_s, base.t3_s)
        assert syn.c3_loading_ratio < base.c3_loading_ratio

    def test_components_positive(self):
        syn = _nominal_synthesis()
        for name in ("c1_f", "c2_f", "r2_ohm", "c3_f", "r3_ohm", "a0_f"):
            assert getattr(syn, name) > 0.0, name


# ─── 注册键（calc_families.pll_loop_filter.pll_loop_filter_synthesize）──────


class TestRegisteredKey:
    """注册面契约：契约（ok/有限/JSON/确定性）+ 未知参/缺参/域错误 ok=False。"""

    def _run(self, overrides: dict | None = None, **kw_extra):
        params = dict(NOMINAL)
        if overrides:
            params.update(overrides)
        params.update(kw_extra)
        return run_calculator("pll_loop_filter_synthesize", params)

    def test_nominal_ok_and_contract(self):
        out = self._run()
        assert out["ok"] is True, out.get("error")
        result = out["result"]
        assert set(result) == set(EXPECTED_FIELDS)
        json.dumps(out, ensure_ascii=False, allow_nan=False)

        def _walk(value):
            if isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                assert math.isfinite(value)
            elif isinstance(value, dict):
                for v in value.values():
                    _walk(v)

        _walk(out)

    def test_deterministic_repeat(self):
        a = json.dumps(self._run(), sort_keys=True, allow_nan=False)
        b = json.dumps(self._run(), sort_keys=True, allow_nan=False)
        assert a == b

    def test_nominal_values_sane(self):
        """名义设计点量级锚（手算链：u=0.0864/v=2.669 → A0≈3.50e-8 F，
        C2 主导 ~34nF、R2 ~125Ω——带断言防量级错位，非逐位钉）。"""
        result = self._run()["result"]
        assert abs(result["f_crossover_hz"] / 1.0e5 - 1.0) < 1.0e-9
        assert abs(result["phase_margin_deg"] - 50.0) < 1.0e-9
        assert 3.0e-8 < result["a0_f"] < 4.2e-8, result["a0_f"]
        assert result["c2_f"] > result["c1_f"], "主电容应为 C2（零点近穿越）"
        assert abs(result["c3_loading_ratio"] - 0.1) < 1.0e-12
        assert 1.0 < (result["closed_loop_bw_3db_hz"]
                      / result["f_crossover_hz"]) < 5.0

    def test_unknown_kwarg_rejected(self):
        out = self._run(g15_bogus_kw=1)
        assert out["ok"] is False and out.get("error")

    @pytest.mark.parametrize("missing", [
        "f_c_hz", "phase_margin_deg", "kp_a_per_rad", "kvco_hz_per_v", "n_div",
    ])
    def test_missing_required_rejected(self, missing):
        params = dict(NOMINAL)
        params.pop(missing)
        out = run_calculator("pll_loop_filter_synthesize", params)
        assert out["ok"] is False and out.get("error")

    @pytest.mark.parametrize("overrides", [
        {"phase_margin_deg": 95.0},
        {"phase_margin_deg": 0.0},
        {"phase_margin_deg": -10.0},
        {"f_c_hz": 0.0},
        {"t3_t1_ratio": 1.0},
        {"c3_frac": 0.0},
        {"r3_ohm": 0.0},
        {"n_div": 0.5},
        {"kp_a_per_rad": 0.0},
        # 可达窗外：PM=5° 对 r=3 不可达（窗下限 ~13.8°）——诚实域守卫
        {"phase_margin_deg": 5.0},
    ])
    def test_domain_errors_rejected(self, overrides):
        out = self._run(overrides)
        assert out["ok"] is False and out.get("error"), overrides


# ─── 负例域守卫（core 直调面）───────────────────────────────────────────────


class TestNegativeDomains:
    def test_unreachable_window_message(self):
        with pytest.raises(ValueError, match="不可达"):
            synthesize_loop_filter(1.0e5, 5.0, 8.0e-4, 4.0e7, 40.0)

    def test_solve_peak_placement_r_positive_guard(self):
        with pytest.raises(ValueError, match="t3_t1_ratio"):
            solve_peak_placement(50.0, 0.0)

    @pytest.mark.parametrize("bad", [
        {"phase_margin_deg": 90.0},
        {"phase_margin_deg": True},
        {"phase_margin_deg": "50"},
        {"phase_margin_deg": float("nan")},
        {"f_c_hz": -1.0},
        {"kvco_hz_per_v": 0.0},
        {"kvco_hz_per_v": "40e6"},
        {"t3_t1_ratio": 0.5},
        {"t3_t1_ratio": float("inf")},
        {"c3_frac": 0.6},
        {"c3_frac": -0.1},
    ])
    def test_scalar_guards(self, bad):
        with pytest.raises(ValueError):
            _nominal_synthesis(**bad)

    def test_freq_array_guards(self):
        args = (8.0e-4, 4.0e7, 40.0, 3.5e-8, 1.37e-7, 4.25e-6, 4.12e-7)
        with pytest.raises(ValueError):
            open_loop_transfer(np.array([1.0e3, 0.0]), *args)
        with pytest.raises(ValueError):
            open_loop_transfer(np.array([1.0e3, -1.0]), *args)
        with pytest.raises(ValueError):
            open_loop_transfer(np.array([[1.0e3, 2.0e3]]), *args)
        with pytest.raises(ValueError):
            open_loop_transfer(np.array([1.0e3, float("nan")]), *args)
        with pytest.raises(ValueError):
            open_loop_transfer(np.array([True, False]), *args)
