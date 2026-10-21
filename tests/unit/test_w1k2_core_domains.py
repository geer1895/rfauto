"""架构批 W1-K2 内核席锚树：调制/数字链路波形体制域五键 + LFM 脉冲压缩设计键。

六键：papr_ofdm_ccdf / cfr_evm_cost（PAPR/CFR 提升核，单源消费
core/papr）/ ofdm_waveform_params / ofdm_cp_design（OFDM 参数/设计对）/
spread_spectrum_gain（Pickholtz 1982 体制面）/ pulse_compression_design
（雷达设计面，ΔR 同仓双源 isac_ambiguity）。

#118 独立来源纪律：全部数值锚走**独立算术路径**（幂算术/二阶级数/
数值积分/逐位恒等式），非同一公式的两次抄写；薄包装键另钉
"wrapper 输出与 core 直调逐位一致"（helix_axial_reg 先例）。
任务书"a=0 退化 EVM=0"按物理与 core 口径勘误：a=0=削峰包络为零→
信号全毁 EVM²=1（0dB）；零代价点在 a→∞（不削）——#122 如实登记。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.calc_families.link_modulation import (
    cfr_evm_cost,
    ofdm_cp_design,
    ofdm_waveform_params,
    papr_ofdm_ccdf,
    spread_spectrum_gain,
)
from rfauto.core.calc_families.pulse_compression import (
    pulse_compression_design,
)
from rfauto.core.isac_ambiguity import C0_M_S, range_resolution_m
from rfauto.core.papr import ccdf_analytic, evm_clip_gauss_closed_form

# ───────────────── 1. papr_ofdm_ccdf（van Nee 2000 提升核）─────────────────


class TestPaprOfdmCcdf:
    def test_n64_gamma10_independent_power_arithmetic(self):
        """N=64 @γ=10dB 手算钉：独立幂算术 1−(1−e^−10)^64（γ_lin=10 处
        1−x 与 x 相距 4 个量级，naive 幂路径无灾难相消）。"""
        out = papr_ofdm_ccdf(64, 10.0)
        literal = 0.002901444115158802  # 独立算术：x=exp(-10); 1-(1-x)**64
        assert math.isclose(out["ccdf"], literal, rel_tol=1e-12)
        assert out["gamma_lin"] == 10.0
        assert out["n_eff"] == 64.0

    def test_n1_rayleigh_tail_bitwise_shortcircuit(self):
        """N_eff=1 → P=e^(−γ) Rayleigh 尾短路逐位（core 恒等式透传）。"""
        out = papr_ofdm_ccdf(1, 10.0)
        assert out["ccdf"] == math.exp(-10.0)

    def test_thin_wrapper_bitwise_core(self):
        """薄度守卫：wrapper 输出与 core 直调逐位一致（零公式复制）。"""
        for n, g, a in ((64, 10.0, 1.0), (1024, 6.0, 2.0), (53, 0.0, 1.0)):
            assert papr_ofdm_ccdf(n, g, a)["ccdf"] == ccdf_analytic(g, n, a)

    def test_large_n_asymptote_second_order_series(self):
        """大 N 渐近（独立二阶级数路径）：P = N·x·(1−(N−1)x/2+O(x²))，
        N=1024、γ=20dB（γ_lin=100，e^−100 未下溢）。"""
        out = papr_ofdm_ccdf(1024, 20.0)
        x = math.exp(-100.0)
        series = 1024.0 * x * (1.0 - 1023.0 * x / 2.0)
        assert math.isclose(out["ccdf"], series, rel_tol=1e-12)

    def test_ccdf_monotone_decreasing_in_gamma(self):
        """严格单调降（可表示域内——γ≥29dB 起双精度下溢为 0，尾部
        见下个专用钉）。"""
        prev = 1.1
        for g in range(0, 31):
            out = papr_ofdm_ccdf(64, float(g))
            if out["ccdf"] == 0.0:
                break
            assert out["ccdf"] < prev
            prev = out["ccdf"]

    def test_ccdf_db_none_in_deep_underflow_tail(self):
        """γ_lin≳745（e^(−γ) 下溢）→ ccdf≡0、ccdf_db=None（20log10(0)
        无定义不硬算，None 如实——cfr_evm_cost 同款口径）。"""
        out = papr_ofdm_ccdf(64, 30.0)
        assert out["ccdf"] == 0.0
        assert out["ccdf_db"] is None

    def test_domain_guards_explicit(self):
        with pytest.raises(ValueError):
            papr_ofdm_ccdf(0, 10.0)
        with pytest.raises(ValueError):
            papr_ofdm_ccdf(64, -1.0)
        with pytest.raises(ValueError):
            papr_ofdm_ccdf(64, 10.0, alpha=0.5)
        with pytest.raises(ValueError):
            papr_ofdm_ccdf(True, 10.0)  # bool 显式拒收


# ───────────────── 2. cfr_evm_cost（Tellado 2000 提升核）──────────────────


class TestCfrEvmCost:
    @staticmethod
    def _evm2_numeric(papr_target_db: float) -> float:
        """独立数值积分路径：EVM²=∫_A^∞(r−A)²·2r·e^(−r²)dr（Rayleigh
        幅度 p(r)=2r·e^(−r²)、E|r|²=1 归一；r≥14 尾 ~e^−196 可忽略）。"""
        a = 10.0 ** (papr_target_db / 10.0)
        amp = math.sqrt(a)
        r = np.linspace(amp, 14.0, 4_000_001)
        return float(np.trapezoid((r - amp) ** 2 * 2.0 * r * np.exp(-r * r),
                                  r))

    def test_evm_matches_numerical_integration(self):
        """闭式 vs 独立数值积分 rel≤1e-10（三个目标档）。"""
        for db in (3.0, 6.0, 12.0):
            out = cfr_evm_cost(db)
            num = self._evm2_numeric(db)
            assert math.isclose(out["evm2"], num, rel_tol=1e-10)

    def test_evm_a0_identity_via_core(self):
        """a=0 恒等式（core 单源面）：削峰包络为零→信号全毁 EVM²=1——
        任务书"EVM=0"系方向反写，按物理勘误（#122 如实，见模块 docstring）。
        a→0+ 连续趋近 1（从下方，恒非负）。"""
        assert evm_clip_gauss_closed_form(0.0) == 1.0
        small = evm_clip_gauss_closed_form(1e-8)
        assert 0.999 < small < 1.0
        # 键面声明域 (0,40]dB：域下板（目标→0+，a→1+）EVM_rms≈0.29845
        # （a 微移 δ 的响应线性 ~O(δ)，带宽 1e-4 容差钉连续性）
        floor = cfr_evm_cost(1e-6)
        assert math.isclose(floor["evm_rms"],
                            math.sqrt(evm_clip_gauss_closed_form(1.0)),
                            rel_tol=1e-4)

    def test_large_a_asymptote_and_none_db(self):
        """大 a 渐近：40dB 目标（a=1e4）双精度下溢 → EVM_rms≡0、
        evm_db=None（20log10(0) 无定义，None 如实，#364④ is-not-None 口径）。"""
        out = cfr_evm_cost(40.0)
        assert out["evm_rms"] == 0.0
        assert out["evm_db"] is None

    def test_mid_target_db_consistency(self):
        out = cfr_evm_cost(6.0)
        assert out["evm_db"] == 20.0 * math.log10(out["evm_rms"])
        assert out["a_lin"] == 10.0 ** 0.6

    def test_evm2_monotone_decreasing(self):
        prev = float("inf")
        for db in (0.5, 2.0, 5.0, 10.0, 20.0, 30.0):
            evm2 = cfr_evm_cost(db)["evm2"]
            assert evm2 < prev
            prev = evm2

    def test_domain_guards_explicit(self):
        with pytest.raises(ValueError):
            cfr_evm_cost(0.0)  # a=0 语义点在域外（削到零幅度）
        with pytest.raises(ValueError):
            cfr_evm_cost(41.0)  # 上界外双精度下溢静默欠流，域收缩
        with pytest.raises(ValueError):
            cfr_evm_cost(-3.0)
        with pytest.raises(ValueError):
            cfr_evm_cost(True)


# ───────────────── 3. ofdm_waveform_params（参数面）───────────────────────


class TestOfdmWaveformParams:
    def test_lte_nominal_chain_bitwise(self):
        """LTE 档 N=1024/Δf=15kHz/TCP=5µs/τ=1µs：互逆恒等式逐位。"""
        out = ofdm_waveform_params(1024, 15000.0, 5e-6, 1e-6)
        assert out["t_useful_s"] == 1.0 / 15000.0
        assert out["fs_hz"] == 1024 * 15000.0
        assert out["t_symbol_s"] == out["t_useful_s"] + 5e-6
        assert out["cp_overhead_frac"] == 5e-6 / out["t_symbol_s"]
        assert out["cp_ok"] is True
        assert out["cp_margin_s"] == 5e-6 - 1e-6
        assert out["samples_per_symbol"] == 1024.0 + 5e-6 * 15360000.0

    def test_cp_shortfall_flagged(self):
        """CP 不足：tcp=0.5µs < τ=1µs → cp_ok=False、负余量如实。"""
        out = ofdm_waveform_params(1024, 15000.0, 0.5e-6, 1e-6)
        assert out["cp_ok"] is False
        assert out["cp_margin_s"] < 0.0

    def test_overhead_monotone_in_cp(self):
        prev = -1.0
        for tcp in (0.0, 2e-6, 5e-6, 1e-5):
            eta = ofdm_waveform_params(1024, 15000.0, tcp)["cp_overhead_frac"]
            assert eta > prev
            prev = eta

    def test_domain_guards_explicit(self):
        with pytest.raises(ValueError):
            ofdm_waveform_params(1024, -15000.0, 5e-6)
        with pytest.raises(ValueError):
            ofdm_waveform_params(1024, 15000.0, -1.0)
        with pytest.raises(ValueError):
            ofdm_waveform_params(True, 15000.0, 5e-6)


# ───────────────── 4. ofdm_cp_design（设计反演面）─────────────────────────


class TestOfdmCpDesign:
    def test_lte_cp_design_exact_fraction(self):
        """τ=1µs、N=1024、Δf=15kHz → fs=15.36MHz、n_cp=⌈15.36⌉=16、
        T_CP=16/15.36MHz（逐位分数）、余量∈[0,1/fs)。"""
        out = ofdm_cp_design(1e-6, 15000.0, 1024)
        assert out["fs_hz"] == 15360000.0
        assert out["n_cp_samples"] == 16
        assert out["cp_duration_s"] == 16.0 / 15360000.0
        assert out["cp_margin_s"] == 16.0 / 15360000.0 - 1e-6
        assert 0.0 <= out["cp_margin_s"] < 1.0 / 15360000.0
        assert out["cp_overhead_frac"] == out["cp_duration_s"] / (
            out["t_useful_s"] + out["cp_duration_s"])

    def test_exact_integer_tau_zero_margin(self):
        """τ·fs 恰为整数（τ=16/15.36MHz）：ceil 不进位 → 余量恒 0。"""
        tau = 16.0 / 15360000.0
        out = ofdm_cp_design(tau, 15000.0, 1024)
        assert out["n_cp_samples"] == 16
        assert out["cp_margin_s"] == 0.0

    def test_design_pair_roundtrip(self):
        """成对键闭环：design 的 T_CP 回灌 params → cp_ok 恒 True。"""
        d = ofdm_cp_design(1e-6, 15000.0, 1024)
        p = ofdm_waveform_params(1024, 15000.0, d["cp_duration_s"], 1e-6)
        assert p["cp_ok"] is True

    def test_n_cp_nondecreasing_in_tau(self):
        last = 0
        for tau in (0.5e-6, 1e-6, 2e-6, 5e-6):
            n = ofdm_cp_design(tau, 15000.0, 1024)["n_cp_samples"]
            assert n >= last
            last = n

    def test_domain_guards_explicit(self):
        with pytest.raises(ValueError):
            ofdm_cp_design(0.0, 15000.0, 1024)
        with pytest.raises(ValueError):
            ofdm_cp_design(1e-6, 0.0, 1024)


# ───────────────── 5. spread_spectrum_gain（Pickholtz 1982）───────────────


class TestSpreadSpectrumGain:
    def test_n1_identity_zero_gain(self):
        """N=1 → PG=0dB 恒等；余量=−(L_sys+SNR_min) 恒等。"""
        out = spread_spectrum_gain("dsss", 1, 3.0, 10.0)
        assert out["processing_gain_db"] == 0.0
        assert out["jamming_margin_db"] == -(3.0 + 10.0)
        assert out["budget_identity_ok"] is True

    def test_gps_ca_like_pin(self):
        """N=1023（GPS C/A 码量级）→ PG=10lg1023（独立算术逐位）；分解
        恒等式 L_sys+SNR_min+M_J=PG 逐位。"""
        out = spread_spectrum_gain("dsss", 1023, 3.0, 10.0)
        assert out["processing_gain_db"] == 10.0 * math.log10(1023.0)
        assert out["budget_identity_ok"] is True
        assert (out["l_sys_db"] + out["snr_min_db"]
                + out["jamming_margin_db"]) == out["processing_gain_db"]

    def test_power_of_ten_slope_identity(self):
        """10log10 斜率恒等：N=100 → 20dB、N=1000 → 30dB（逐位）。"""
        assert spread_spectrum_gain("dsss", 100)["processing_gain_db"] == 20.0
        assert spread_spectrum_gain("dsss", 1000)[
            "processing_gain_db"] == 30.0

    def test_fhss_mode_same_formula(self):
        """FHSS 档：PG=10lg(N_freq) 同式（语义注记不同）。"""
        out = spread_spectrum_gain("fhss", 64)
        assert out["processing_gain_db"] == 10.0 * math.log10(64.0)

    def test_js_max_equals_margin(self):
        out = spread_spectrum_gain("dsss", 1023, 3.0, 10.0)
        assert out["js_max_db"] == out["jamming_margin_db"]

    def test_domain_guards_explicit(self):
        with pytest.raises(ValueError):
            spread_spectrum_gain("dsss", 0)
        with pytest.raises(ValueError):
            spread_spectrum_gain("ofdm", 64)
        with pytest.raises(ValueError):
            spread_spectrum_gain("dsss", 64, l_sys_db=-1.0)
        with pytest.raises(ValueError):
            spread_spectrum_gain("dsss", True)


# ───────────────── 6. pulse_compression_design（雷达设计面）───────────────


class TestPulseCompressionDesign:
    def test_tb_and_gain_bitwise(self):
        """B=1MHz/T=50µs → TB=50 逐位、G=10lg50 独立算术逐位、N_min=50。"""
        out = pulse_compression_design(1e6, 50e-6)
        assert out["tb_product"] == 50.0
        assert out["pc_gain_db"] == 10.0 * math.log10(50.0)
        assert out["n_samples_min"] == 50

    def test_range_resolution_dual_source_consistency(self):
        """ΔR 同仓双源三路一致：键输出==isac_ambiguity 直调（同源逐位）
        ==独立 c/(2B) 算术（逐位）。"""
        out = pulse_compression_design(1e6, 50e-6)
        assert out["range_resolution_m"] == range_resolution_m(1e6)
        assert out["range_resolution_m"] == 299792458.0 / (2.0 * 1e6)
        assert out["range_resolution_m"] == 149.896229

    def test_tb_gain_roundtrip_inverse(self):
        """反演回收：TB=10^(G_pc/10)（dB roundtrip 双精度 ~1ulp，isclose
        1e-15；多档）。"""
        for b, t in ((1e6, 50e-6), (10e6, 10e-6), (2.5e5, 200e-6)):
            out = pulse_compression_design(b, t)
            assert math.isclose(out["tb_product"],
                                10.0 ** (out["pc_gain_db"] / 10.0),
                                rel_tol=1e-15)

    def test_doppler_coupling_identity_and_zero(self):
        """耦合恒等式（独立一步算术 isclose 1e-12）+f_d=0 → 0 逐位。"""
        out = pulse_compression_design(1e6, 50e-6, 1000.0)
        oneshot = C0_M_S * 1000.0 * 50e-6 / (2.0 * 1e6)
        assert math.isclose(out["doppler_coupling_m"], oneshot, rel_tol=1e-12)
        assert out["doppler_coupling_abs_m"] == abs(out["doppler_coupling_m"])
        zero = pulse_compression_design(1e6, 50e-6, 0.0)
        assert zero["doppler_coupling_m"] == 0.0

    def test_coupling_linear_in_pulse_width(self):
        """耦合随 T 线性：T×2 → ΔR_fd×2（乘 2 浮点精确，逐位）。"""
        t1 = pulse_compression_design(1e6, 50e-6, 1000.0)["doppler_coupling_m"]
        t2 = pulse_compression_design(1e6, 100e-6, 1000.0)["doppler_coupling_m"]
        assert t2 == 2.0 * t1

    def test_coupling_scales_inverse_bandwidth(self):
        """耦合随 B 反比：B×10 → ΔR_fd/10（同式双档 isclose）。"""
        b1 = pulse_compression_design(1e6, 50e-6, 1000.0)["doppler_coupling_m"]
        b2 = pulse_compression_design(1e7, 50e-6, 1000.0)["doppler_coupling_m"]
        assert math.isclose(b2, b1 / 10.0, rel_tol=1e-15)

    def test_domain_guards_explicit(self):
        with pytest.raises(ValueError):
            pulse_compression_design(0.0, 50e-6)
        with pytest.raises(ValueError):
            pulse_compression_design(1e6, 0.0)
        with pytest.raises(ValueError):
            pulse_compression_design(1e6, 50e-6, float("nan"))
