"""NX-2 ISAC 模糊函数/分辨率闭式单测（Woodward 口径，2026-10-03）。

锚树口径（#118：双路互证，不赌推导）：
- 分辨率/不模糊指标：独立闭式直算恒等 + 维度一致性（c/B、1/T、λ/2T、
  c/2·PRF、λ·PRF/4 全部测试内独立书写）。
- LFM 解析式 vs numeric_ambiguity 数值积分路对拍（同一定义两实现），
  门 ≤0.02（Riemann 截断+有限脉冲沿），峰值/斜脊/零多普勒三角逐性质钉。
- 矩形脉冲零多普勒切 = 三角窗（解析 1−|τ|/T 恒等）；零延迟切 = sinc。
- Barker-13 峰值旁瓣比 = 13（0 多普勒自相关旁瓣恒等，整数定义）。
- Woodward 体积不变性：LFM 网格积分残差按截断量级给容差（相对 ≤0.05）。
- 共轭对称 χ(−τ,ν)=χ*(τ,−ν) 恒等式（定义级）。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.isac_ambiguity import (
    C0_M_S,
    chip_code_ambiguity,
    doppler_resolution_hz,
    lfm_ambiguity,
    numeric_ambiguity,
    pulse_ambiguity,
    range_resolution_m,
    sinc_norm,
    unambiguous_range_m,
    unambiguous_velocity_m_s,
    velocity_resolution_m_s,
    woodward_volume_invariant,
)


# ─── 指标闭式（独立直算恒等）─────────────────────────────────────────────────
@pytest.mark.parametrize("bw", [1e6, 10e6, 400e6])
def test_range_resolution_identity(bw):
    assert abs(range_resolution_m(bw) - C0_M_S / (2.0 * bw)) <= 1e-15 * C0_M_S / bw


@pytest.mark.parametrize("t", [1e-3, 5e-3, 0.1])
def test_doppler_velocity_identity(t):
    lam = 0.03
    assert abs(doppler_resolution_hz(t) - 1.0 / t) <= 1e-15
    assert abs(velocity_resolution_m_s(lam, t) - lam / (2.0 * t)) <= 1e-18


def test_unambiguous_identities():
    prf = 2000.0
    lam = 0.03
    assert abs(unambiguous_range_m(prf) - C0_M_S / (2.0 * prf)) <= 1e-12
    assert abs(unambiguous_velocity_m_s(lam, prf) - lam * prf / 4.0) <= 1e-15


def test_sinc_norm_anchor():
    """sinc(0)=1、sinc(整数)=0、sinc(0.5)=2/π。"""
    assert sinc_norm(0.0) == 1.0
    assert abs(sinc_norm(1.0)) < 1e-15
    assert abs(sinc_norm(0.5) - 2.0 / math.pi) <= 1e-15


# ─── LFM 解析式 vs 数值积分双路对拍 ──────────────────────────────────────────
def _lfm_pulse(t_pulse: float, bw: float, fs: float):
    n = round(t_pulse * fs)
    t = np.arange(n) / fs
    mu = bw / t_pulse
    s = np.exp(1j * np.pi * mu * (t - t_pulse / 2.0) ** 2) / math.sqrt(t_pulse)
    return s


def test_lfm_analytic_vs_numeric():
    """LFM：解析式与数值积分路逐点对拍（相对门 0.02，Riemann 截断量级）。"""
    t_p, bw, fs = 10e-6, 2e6, 20e6
    s = _lfm_pulse(t_p, bw, fs)
    taus = np.array([-8e-6, -4e-6, -2e-6, 0.0, 2e-6, 4e-6, 8e-6])
    nus = np.array([-1.2e5, -6e4, 0.0, 6e4, 1.2e5])
    num = numeric_ambiguity(s, fs, taus, nus)
    ana = lfm_ambiguity(taus[:, None], nus[None, :], t_p, bw)
    assert ana.shape == num.shape
    assert np.max(np.abs(ana - num)) <= 0.02 * float(np.max(num))


def test_lfm_ridge_structure():
    """LFM 斜脊：沿 ν=μτ 脊 |χ| = 三角包络 1−|τ|/T（sinc 脊恒 1）；原点峰值。"""
    t_p, bw = 20e-6, 5e6
    mu = bw / t_p
    for tau in (0.0, 4e-6, -8e-6):
        val = lfm_ambiguity(tau, mu * tau, t_p, bw)
        expect = 1.0 - abs(tau) / t_p
        assert abs(val - expect) <= 1e-9
    assert lfm_ambiguity(0.0, 0.0, t_p, bw) == 1.0
    # 脊外旁瓣：横向离开脊 1/(T−|τ|) 量级即进 sinc 零点→显著低于包络
    tau = 4e-6
    off = lfm_ambiguity(tau, mu * tau + 1.0 / (t_p - tau), t_p, bw)
    assert off <= 1e-9


def test_pulse_ambiguity_cuts():
    """矩形脉冲：零多普勒切=三角窗恒等；零延迟切=sinc(νT) 恒等。"""
    t_p = 8e-6
    for frac in (0.0, 0.2, 0.5, 0.8):
        tau = frac * t_p
        assert abs(pulse_ambiguity(tau, 0.0, t_p) - (1.0 - frac)) <= 1e-12
    for nu in (0.0, 0.3 / t_p, 1.0 / t_p, 2.5 / t_p):
        expect = (1.0) * abs(math.sin(math.pi * nu * t_p) / (math.pi * nu * t_p)) \
            if nu > 0 else 1.0
        assert abs(pulse_ambiguity(0.0, nu, t_p) - expect) <= 1e-12
    assert pulse_ambiguity(2.0 * t_p, 0.0, t_p) == 0.0


def test_chip_code_barker13_sidelobe():
    """Barker-13 零多普勒自相关：峰值 1、旁瓣 ∈{0,±1/13}、最大旁瓣=1/13。

    Barker 序列定义性质：旁瓣幅值 ≤1（码片归一后 ≤1/13）；lag-1 和=0
    与 lag-2=1 独立手算钉（序列 [1,1,1,1,1,−1,−1,1,1,−1,1,−1,1]：
    R(1)=Σc_k·c_{k+1}=0、R(2)=+1）。
    """
    b13 = np.array([1, 1, 1, 1, 1, -1, -1, 1, 1, -1, 1, -1, 1], dtype=complex)
    tc = 1e-6
    peak = abs(chip_code_ambiguity(0.0, 0.0, b13, tc))
    assert abs(peak - 1.0) <= 1e-12
    sidelobes = [
        abs(chip_code_ambiguity(m * tc, 0.0, b13, tc)) for m in range(1, 13)
    ]
    assert max(sidelobes) <= 1.0 / 13.0 + 1e-12
    assert abs(sidelobes[0] - 0.0) <= 1e-12
    assert abs(sidelobes[1] - 1.0 / 13.0) <= 1e-12


def test_chip_code_conjugate_symmetry():
    """χ(−τ,ν)=χ*(τ,−ν) 恒等式（定义级推论，双点对拍）。"""
    chips = np.exp(1j * np.array([0.0, 0.0, np.pi, 0.0, np.pi]))
    tc = 2e-6
    tau, nu = 3.7 * tc, 1.1e5
    a = chip_code_ambiguity(-tau, nu, chips, tc)
    b = np.conj(chip_code_ambiguity(tau, -nu, chips, tc))
    assert abs(a - b) <= 1e-12 * max(1e-12, abs(b))


def test_woodward_volume_invariant_lfm():
    """体积不变性：LFM 数值积分 ∫∫|χ|² ≈ 1（截断容差相对 ≤0.05）。"""
    t_p, bw, fs = 5e-6, 1e6, 40e6
    s = _lfm_pulse(t_p, bw, fs)
    out = woodward_volume_invariant(
        s, fs, tau_max_s=1.2 * t_p, nu_max_hz=1.2 * bw, n_tau=241, n_nu=241)
    assert out["relative_residual"] <= 0.05
    assert out["chi00_sq"] == pytest.approx(1.0, rel=1e-9)


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        range_resolution_m(0.0)
    with pytest.raises(ValueError):
        doppler_resolution_hz(-1.0)
    with pytest.raises(ValueError):
        chip_code_ambiguity(0.0, 0.0, np.array([], dtype=complex), 1e-6)
    with pytest.raises(ValueError):
        chip_code_ambiguity(float("nan"), 0.0,
                            np.array([1.0, 1.0], dtype=complex), 1e-6)
