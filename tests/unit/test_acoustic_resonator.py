"""声学谐振器 mBVD 内核单元测试（PK-1 锚树，规格深案 §A-1）。

锚树预声明（先写后跑，#122；规格 §A-1 D）：
- A1 合成回收：无损无噪 L0=0 档五参数+fs/fa 回收相对误差 ≤1e-9（正向模型
  与提取模型同构，least_squares 精车应达机器精度量级）；加性复高斯噪声
  （σ=1e-3）档 ≤1%。
- A2 Larson 2000 例量级锚：**页内数值 UNVERIFIED，不编数**（规格 §A-1 D
  如实标注）——改用典型 FBAR 量级自检：fs~2GHz、C0~pF、Cm~fF 级、
  Qs~1000+、keff² 千分之几，提取结果须全部落在量级带内。
- A3 keff² 两式对比（诚实口径，落地复核发现见模块 docstring）：弱耦合
  ≤0.1% 钉在真实成立的事实上——(fa²−fs²)/fa²=Cm/(Cm+C0) vs Cm/C0
  （Cm/C0=1e-3 时 0.0999%）与"精确式"vs 前导项 (π³/16)·Cm/C0；强耦合
  （Cm/C0=0.2）两式相对偏差 >40% 钉"精确式必要性"，且绝对偏差随耦合
  单调增长、相对偏差恒在 (40%,50%) 带内（两式弱耦合极限仍差 π³/16，
  非同一量的两级近似——如实记录不凑绿，#122）。
- A4 温漂合成回收：多项式恒等式机器精度 + fs(T0+ΔT) 合成 S11 全链提取
  fs 回收 ≤1e-6。
- A5 守卫负例：max|Γ|≤0.1、Im(Y)=0 交越不足两根、Cm/C0>0.3、fs≥fa
  （keff2/bvd 直入参）四类 ValueError。

数值裁判纪律（#118）：正向模型（mbvd_impedance）与提取
（extract_mbvd_from_s1p）独立成链，回收判据走「正向生成→反向提取」往返；
闭式锚（fs/fa/keff² 恒等式）为独立来源解析值。蒙特卡洛类用固定种子。
"""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
import pytest

from rfauto.core.acoustic_resonator import (
    MbvdFit,
    bvd_resonances,
    extract_mbvd_from_s1p,
    fs_of_temperature,
    keff2,
    mbvd_admittance,
    mbvd_impedance,
)

Z0 = 50.0
F_LO = 1.8e9
F_HI = 2.2e9
N_FREQ = 801


def _true_params() -> dict[str, float]:
    """典型 FBAR 合成夹具（量级锚口径）：fs=2GHz、C0=1pF、Cm=8fF、Qs=1000。"""
    fs = 2.0e9
    c0 = 1.0e-12
    cm = 8e-15
    lm = 1.0 / ((2.0 * math.pi * fs) ** 2 * cm)
    rm = 1.0 / (2.0 * math.pi * fs * cm * 1000.0)
    return {
        "fs": fs,
        "fa": fs * math.sqrt(1.0 + cm / c0),
        "c0": c0,
        "r0": 1.5,
        "lm": lm,
        "cm": cm,
        "rm": rm,
    }


def _freq_grid(lo: float = F_LO, hi: float = F_HI,
               n: int = N_FREQ) -> np.ndarray:
    return np.linspace(lo, hi, n)


def _synth_s11(f_hz: np.ndarray, p: dict[str, float],
               l0: float = 0.0) -> np.ndarray:
    """已知 mBVD 正向生成单端口 S11（Γ=(Z−Z0)/(Z+Z0)）。"""
    z = mbvd_impedance(f_hz, p["c0"], p["r0"], p["lm"], p["cm"], p["rm"], l0)
    return (z - Z0) / (z + Z0)


def _rel_err(got: float, want: float) -> float:
    return abs(got - want) / abs(want)


# ─── 正向模型（六元件 mBVD）──────────────────────────────────────────────────


class TestMbvdImpedance:
    def test_series_resonance_zero_impedance_lossless(self):
        """fs 处（无损、L0=0）动态臂串联谐振 → Z→0（浮点相消级）。"""
        p = _true_params()
        z = mbvd_impedance(p["fs"], p["c0"], 0.0, p["lm"], p["cm"], 0.0, 0.0)
        assert abs(z) < 1e-6

    def test_antiresonance_sign_flip_lossless(self):
        """无损闭式 fa 两侧 Im(Y) 变号（−→+），fa 处 |Y| 远小于 ωC0。"""
        p = _true_params()
        kw = (p["c0"], 0.0, p["lm"], p["cm"], 0.0, 0.0)
        y_lo = mbvd_admittance(p["fa"] * 0.999, *kw)
        y_hi = mbvd_admittance(p["fa"] * 1.001, *kw)
        assert np.imag(y_lo) < 0.0 < np.imag(y_hi)
        y_at = mbvd_admittance(p["fa"], *kw)
        assert abs(y_at) < 1e-3 * (2.0 * math.pi * p["fa"] * p["c0"])

    def test_high_frequency_static_arm_asymptote(self):
        """f≫fa 时 Z→R0+1/(jωC0)（静态臂渐近，动态臂修正 ∝1/ω² 可略）。"""
        p = _true_params()
        f = 100.0 * p["fa"]  # 修正项 ~1/(ω²LmC0)，此档 <1e-6 相对
        z = mbvd_impedance(f, p["c0"], p["r0"], p["lm"], p["cm"], p["rm"], 0.0)
        w = 2.0 * math.pi * f
        z_static = p["r0"] + 1.0 / (1j * w * p["c0"])
        assert abs(z - z_static) < 1e-5 * abs(z_static)  # 实测修正项 ~1.7e-6 相对

    def test_admittance_is_reciprocal_of_impedance(self):
        p = _true_params()
        f = np.array([1.9e9, 2.0e9, 2.05e9, 2.15e9])
        z = mbvd_impedance(f, p["c0"], p["r0"], p["lm"], p["cm"], p["rm"], 0.0)
        y = mbvd_admittance(f, p["c0"], p["r0"], p["lm"], p["cm"], p["rm"], 0.0)
        assert np.allclose(np.asarray(y) * np.asarray(z), 1.0, rtol=1e-12)

    def test_scalar_and_array_duality(self):
        p = _true_params()
        kw = (p["c0"], p["r0"], p["lm"], p["cm"], p["rm"], 0.0)
        z1 = mbvd_impedance(2.05e9, *kw)
        assert isinstance(z1, complex)
        za = mbvd_impedance(np.array([2.05e9]), *kw)
        assert isinstance(za, np.ndarray) and za.shape == (1,)
        # numpy 标量/数组循环的复数乘法末位 ulp 可异（SIMD 路径），1e-12 相对一致即可
        assert np.allclose(complex(za[0]), z1, rtol=1e-12, atol=0.0)

    def test_l0_series_shifts_nothing_at_dc_side(self):
        """L0 串联只在动臂外附加 jωL0：高频档 |Z| 随 L0 增量可预测。"""
        p = _true_params()
        f = 2.05e9
        kw = (p["c0"], p["r0"], p["lm"], p["cm"], p["rm"])
        z_no = mbvd_impedance(f, *kw, 0.0)
        z_l0 = mbvd_impedance(f, *kw, 5e-9)
        assert abs(abs(z_l0) - abs(z_no)) <= 2.0 * math.pi * f * 5e-9 + 1e-9

    def test_guard_negative_or_zero_params(self):
        p = _true_params()
        with pytest.raises(ValueError, match="须 >0"):
            mbvd_impedance(2e9, 0.0, p["r0"], p["lm"], p["cm"], p["rm"])
        with pytest.raises(ValueError, match="须 >0"):
            mbvd_impedance(2e9, p["c0"], p["r0"], p["lm"], 0.0, p["rm"])
        with pytest.raises(ValueError, match="须 ≥0"):
            mbvd_impedance(2e9, p["c0"], p["r0"], p["lm"], p["cm"], -1.0)
        with pytest.raises(ValueError, match="全 >0"):
            mbvd_impedance(0.0, p["c0"], p["r0"], p["lm"], p["cm"], p["rm"])


# ─── 闭式谐振与 keff²（锚 A3）────────────────────────────────────────────────


class TestBvdResonances:
    def test_closed_forms_consistent_with_cm_ratio(self):
        cm, c0 = 8e-15, 1.0e-12
        lm = 1.0 / ((2.0 * math.pi * 2.0e9) ** 2 * cm)
        r = bvd_resonances(lm, cm, c0)
        assert r["fa_hz"] ** 2 / r["fs_hz"] ** 2 == pytest.approx(
            1.0 + cm / c0, rel=1e-12)
        assert r["fs_hz"] < r["fa_hz"]

    def test_guard_nonpositive_args(self):
        with pytest.raises(ValueError, match="须 >0"):
            bvd_resonances(0.0, 8e-15, 1e-12)
        with pytest.raises(ValueError, match="须 >0"):
            bvd_resonances(1e-7, -8e-15, 1e-12)


class TestKeff2:
    def test_approx_is_exact_circuit_identity(self):
        """近似式 (fa²−fs²)/fa² 对 mBVD 电路是精确恒等式 Cm/(Cm+C0)。"""
        p = _true_params()
        got = keff2(p["fs"], p["fa"], exact=False)
        rho = p["cm"] / p["c0"]
        assert got == pytest.approx(rho / (1.0 + rho), rel=1e-12)

    def test_weak_coupling_within_0p1pct_of_static_ratio(self):
        """弱耦合 ≤0.1% 锚（真实事实）：Cm/C0=1e-3 时 1−(fs/fa)² vs Cm/C0。"""
        rho = 1e-3
        fs = 1.0
        fa = fs * math.sqrt(1.0 + rho)
        got = keff2(fs, fa, exact=False)
        assert abs(got - rho) / rho <= 1e-3  # 实测 0.0999%

    def test_exact_converges_to_leading_term_weak_limit(self):
        """弱耦合 ≤0.1% 锚（第二事实）：精确式 vs 前导项 (π³/16)·Cm/C0。"""
        rho = 1e-4
        fs = 1.0
        fa = fs * math.sqrt(1.0 + rho)
        got = keff2(fs, fa, exact=True)
        leading = math.pi**3 / 16.0 * rho
        assert abs(got - leading) / leading <= 1e-3  # 实测 1.25e-5

    def test_strong_coupling_exact_form_necessary(self):
        """精确式必要性锚：强耦合两式相对偏差 >40%，绝对偏差随耦合单调增长。"""
        rhos = np.array([1e-4, 1e-3, 1e-2, 0.05, 0.1, 0.2, 0.3])
        abs_dev = []
        rel_dev = []
        for rho in rhos:
            fs = 1.0
            fa = fs * math.sqrt(1.0 + rho)
            e = keff2(fs, fa, exact=True)
            a = keff2(fs, fa, exact=False)
            abs_dev.append(abs(e - a))
            rel_dev.append(abs(e - a) / e)
        assert all(b > a for a, b in pairwise(abs_dev))  # 单调增长
        for rd in rel_dev:
            assert 0.4 < rd < 0.5  # 恒差 ~48%：两式不同定义，非近似关系
        assert rel_dev[list(rhos).index(0.2)] > 0.4  # 强耦合（ScAlN 量级）必要性

    def test_guard_fs_ge_fa(self):
        with pytest.raises(ValueError, match="fs_hz < fa_hz"):
            keff2(2.0e9, 2.0e9)
        with pytest.raises(ValueError, match="fs_hz < fa_hz"):
            keff2(2.1e9, 2.0e9)
        with pytest.raises(ValueError, match="须 >0"):
            keff2(0.0, 1.0)


# ─── 锚 A1：合成回收 ─────────────────────────────────────────────────────────


class TestExtractSyntheticRecovery:
    def test_noiseless_l0_zero_recovery_le_1e9(self):
        """A1 主档：无损无噪 L0=0 → 五参数+fs/fa 回收 ≤1e-9（预声明）。"""
        p = _true_params()
        f = _freq_grid()
        fit = extract_mbvd_from_s1p(f, _synth_s11(f, p), z0_ohm=Z0)
        assert isinstance(fit, MbvdFit)
        assert fit.converged
        for got, want in (
            (fit.c0_f, p["c0"]), (fit.r0_ohm, p["r0"]),
            (fit.lm_h, p["lm"]), (fit.cm_f, p["cm"]),
            (fit.rm_ohm, p["rm"]), (fit.fs_hz, p["fs"]),
            (fit.fa_hz, p["fa"]),
        ):
            assert _rel_err(got, want) <= 1e-9, (got, want)

    def test_noisy_recovery_le_1pct(self):
        """A1 噪声档：σ=1e-3 复高斯加在 Γ 上 → 参数回收 ≤1%、fs/fa ≤0.1%。"""
        p = _true_params()
        f = _freq_grid()
        rng = np.random.default_rng(20261002)
        g = _synth_s11(f, p) + 1e-3 * (
            rng.standard_normal(f.size) + 1j * rng.standard_normal(f.size))
        fit = extract_mbvd_from_s1p(f, g, z0_ohm=Z0)
        assert fit.converged
        for got, want in (
            (fit.c0_f, p["c0"]), (fit.r0_ohm, p["r0"]),
            (fit.lm_h, p["lm"]), (fit.cm_f, p["cm"]), (fit.rm_ohm, p["rm"]),
        ):
            assert _rel_err(got, want) <= 0.01, (got, want)
        assert _rel_err(fit.fs_hz, p["fs"]) <= 1e-3
        assert _rel_err(fit.fa_hz, p["fa"]) <= 1e-3

    def test_derived_metrics_consistent(self):
        """Qs/FOM/keff² 导出量与五参数自洽（独立闭式复算，#118 双路径）。"""
        p = _true_params()
        f = _freq_grid()
        fit = extract_mbvd_from_s1p(f, _synth_s11(f, p), z0_ohm=Z0)
        q_ref = 1.0 / (2.0 * math.pi * fit.fs_hz * fit.cm_f * fit.rm_ohm)
        assert fit.q_s == pytest.approx(q_ref, rel=1e-12)
        assert fit.keff_squared == pytest.approx(
            1.0 - (fit.fs_hz / fit.fa_hz) ** 2, rel=1e-12)
        assert fit.fom == pytest.approx(fit.q_s * fit.keff_squared, rel=1e-12)


# ─── 锚 A2：典型 FBAR 量级（Larson 2000 页内数值 UNVERIFIED，不编数）──────────


class TestTypicalFbarMagnitude:
    def test_extracted_params_in_typical_fbar_bands(self):
        """量级自检锚：fs~2GHz、C0~pF、Cm~fF、Qs~1000+、keff²~千分之几。"""
        p = _true_params()
        f = _freq_grid()
        fit = extract_mbvd_from_s1p(f, _synth_s11(f, p), z0_ohm=Z0)
        assert 1.9e9 <= fit.fs_hz <= 2.1e9
        assert 0.5e-12 <= fit.c0_f <= 2.0e-12
        assert 1e-15 <= fit.cm_f <= 2e-14
        assert 500.0 <= fit.q_s <= 2000.0
        assert 0.002 <= fit.keff_squared <= 0.02

    def test_bandwidth_matches_closed_form_split(self):
        """fa−fs 与 Cm/C0 闭式自洽（量级带内二次核对）。"""
        p = _true_params()
        f = _freq_grid()
        fit = extract_mbvd_from_s1p(f, _synth_s11(f, p), z0_ohm=Z0)
        assert (fit.fa_hz - fit.fs_hz) / fit.fs_hz == pytest.approx(
            math.sqrt(1.0 + p["cm"] / p["c0"]) - 1.0, rel=1e-6)


# ─── 锚 A4：温漂 ─────────────────────────────────────────────────────────────


class TestFsOfTemperature:
    def test_first_order_polynomial_identity(self):
        fs0, dt, tcf = 2.0e9, 30.0, -25.0
        got = fs_of_temperature(fs0, dt, tcf)
        assert (got / fs0 - 1.0) == pytest.approx(tcf * 1e-6 * dt, rel=1e-12)

    def test_second_order_term(self):
        fs0, dt, tcf2 = 2.0e9, 50.0, 10.0
        got = fs_of_temperature(fs0, dt, 0.0, tcf2)
        assert (got / fs0 - 1.0) == pytest.approx(tcf2 * 1e-6 * dt * dt,
                                                  rel=1e-12)

    def test_zero_shift_is_identity(self):
        assert fs_of_temperature(2.0e9, 0.0, -25.0) == 2.0e9

    def test_negative_tcf_lowers_frequency(self):
        assert fs_of_temperature(2.0e9, 40.0, -25.0) < 2.0e9

    def test_guard_nonpositive_fs0(self):
        with pytest.raises(ValueError, match="须 >0"):
            fs_of_temperature(0.0, 10.0, -25.0)

    def test_temperature_shifted_synthesis_recovery(self):
        """温漂合成回收：fs(T0+ΔT) 正向生成→全链提取→fs 回收 ≤1e-6。"""
        p = _true_params()
        fs_t = fs_of_temperature(p["fs"], 40.0, -25.0)
        p_t = dict(p)
        p_t["fs"] = fs_t
        p_t["lm"] = 1.0 / ((2.0 * math.pi * fs_t) ** 2 * p["cm"])
        f = _freq_grid(F_LO * fs_t / p["fs"], F_HI * fs_t / p["fs"])
        fit = extract_mbvd_from_s1p(f, _synth_s11(f, p_t), z0_ohm=Z0)
        assert _rel_err(fit.fs_hz, fs_t) <= 1e-6


# ─── 锚 A5：守卫负例（四类 ValueError）───────────────────────────────────────


class TestExtractGuards:
    def test_flat_small_gamma_insufficient(self):
        """|Γ|<0.1：带内平坦小反射 → ValueError 谐振信息不足。"""
        f = _freq_grid()
        with pytest.raises(ValueError, match="谐振信息不足"):
            extract_mbvd_from_s1p(f, np.full(f.size, 0.05 + 0.0j), z0_ohm=Z0)

    def test_single_resonance_missing_two_roots(self):
        """仅动态臂（串联 RLC）：Im(Y)=0 单交越 → ValueError 谐振信息不足。"""
        p = _true_params()
        f = _freq_grid()
        w = 2.0 * math.pi * f
        y = 1.0 / (p["rm"] + 1j * (w * p["lm"] - 1.0 / (w * p["cm"])))
        g = (1.0 / Z0 - y) / (1.0 / Z0 + y)
        assert np.max(np.abs(g)) > 0.1  # 前置守卫可过，双根守卫必触发
        with pytest.raises(ValueError, match="谐振信息不足"):
            extract_mbvd_from_s1p(f, g, z0_ohm=Z0)

    def test_overwide_split_cm_ratio_above_0p3(self):
        """Cm/C0=0.5>0.3（双根分离过宽）→ ValueError Cm/C0 守卫。"""
        fs = 2.0e9
        c0 = 1.0e-12
        cm = 0.5e-12
        p = {
            "fs": fs,
            "fa": fs * math.sqrt(1.0 + cm / c0),
            "c0": c0,
            "r0": 1.5,
            "lm": 1.0 / ((2.0 * math.pi * fs) ** 2 * cm),
            "cm": cm,
            "rm": 1.0 / (2.0 * math.pi * fs * cm * 1000.0),
        }
        f = _freq_grid(1.5e9, 2.8e9)
        with pytest.raises(ValueError, match="Cm/C0"):
            extract_mbvd_from_s1p(f, _synth_s11(f, p), z0_ohm=Z0)

    def test_input_validation_errors(self):
        p = _true_params()
        f = _freq_grid(n=32)
        g = _synth_s11(f, p)
        with pytest.raises(ValueError, match="同形"):
            extract_mbvd_from_s1p(f[:-1], g, z0_ohm=Z0)
        with pytest.raises(ValueError, match="严格递增"):
            extract_mbvd_from_s1p(f[::-1].copy(), g[::-1].copy(), z0_ohm=Z0)
        with pytest.raises(ValueError, match="频点过少"):
            extract_mbvd_from_s1p(f[:8], g[:8], z0_ohm=Z0)
        with pytest.raises(ValueError, match="z0_ohm"):
            extract_mbvd_from_s1p(f, g, z0_ohm=0.0)
