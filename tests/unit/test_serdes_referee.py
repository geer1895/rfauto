"""DR-2/DR-3 裁判核测试：ILD/ERL 数学性质锚 + TDR 双路互证与解析锚。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.serdes_referee import (
    effective_return_loss,
    insertion_loss_deviation,
    tdr_impedance_profile,
    tdr_two_route_disagreement,
)

_F = np.linspace(0.0, 20e9, 513)


def test_ild_zero_for_pure_linear_channel() -> None:
    """纯线性 IL 信道 → ILD≡0（fit 恒等，机器精度）。"""
    s21 = 10 ** (-(0.5 + 0.02 * _F / 1e9) / 20.0)
    out = insertion_loss_deviation(s21, _F)
    assert out["ild_max_db"] <= 1e-10
    assert out["ild_rms_db"] <= 1e-10


def test_ild_recovers_bump_exactly_for_meanzero_perturbation() -> None:
    """均零微扰（加性 bump 与拟合线正交）→ ILD 逐点精确回收 bump。"""
    base = 0.5 + 0.02 * _F / 1e9
    bump = 0.3 * np.exp(-((_F - 10e9) / 2e9) ** 2)
    # 去掉 bump 的线性投影（加权最小二乘正交化 → fit 不吸走 bump）
    design = np.vstack([np.ones_like(_F), _F]).T
    coef, *_ = np.linalg.lstsq(design, bump, rcond=None)
    bump_orth = bump - design @ coef
    s21 = 10 ** (-(base + bump_orth) / 20.0)
    out = insertion_loss_deviation(s21, _F)
    expect = bump_orth  # IL = base+bump_orth（IL 为正损耗）→ ILD = +bump_orth
    np.testing.assert_allclose(out["ild_db"], expect, atol=1e-9)
    assert out["ild_max_db"] > 0 and out["ild_min_db"] < 0
    assert out["n_band_points"] == _F.size
    band_out = insertion_loss_deviation(s21, _F, band=(0.0, 10e9))
    assert band_out["n_band_points"] == int(np.sum(_F <= 10e9))


def test_erl_constant_reflection_equals_rl() -> None:
    """恒定 |r| 信道：权重不改变相对权重 → ERL=RL（解析恒等）。"""
    rl_db = 15.0
    r = 10 ** (-rl_db / 20.0) * np.exp(1j * 0.3 * _F / 1e9)
    t = np.sqrt(np.maximum(1.0 - r**2, 0.0)) + 0j
    out = effective_return_loss(r, t, _F)
    assert out["erl_db"] == pytest.approx(rl_db, abs=0.01)


def test_erl_weighting_dominates_low_loss_band() -> None:
    """通带加权性质：低损带 |r| 小占高权 → ERL 优于全带平均 RL（单调方向钉）。"""
    f = _F
    # 分带：前半 |r|=-60dB 低损（w≈1）、后半 |r|=-1dB 高损（w≈0.37）
    r = np.where(f < 10e9, 10 ** (-60 / 20.0), 10 ** (-1 / 20.0))
    t = np.sqrt(np.maximum(1.0 - r**2, 0.0))
    out = effective_return_loss(r, t, f)
    # 无权 RL（功率平均）≈ −3 dB；加权以 |t|² 偏向前半低损带 → ERL 应
    # 优于（大于）无权值（方向性钉；加权本质温和，量级 ≥1 dB）
    assert out["erl_db"] > out["unweighted_rl_db"] + 1.0


def test_erl_input_guards() -> None:
    """形状不一致/全深谷权重 → 显式拒绝。"""
    with pytest.raises(ValueError, match="形状须一致"):
        effective_return_loss(np.ones(4), np.ones(5), np.arange(4.0))
    with pytest.raises(ValueError, match="权重地板"):
        effective_return_loss(np.ones(4, complex), np.zeros(4, complex),
                              np.arange(4.0))


def test_tdr_two_section_step_at_delay() -> None:
    """解析锚（单界面二段线）：50Ω 线→75Ω 匹配延展，TDR 阶跃在到达时刻
    50→Z0(1+Γ)/(1−Γ)=75（Γ=0.2，无重反射闭式）。"""
    gamma = 0.2          # (75-50)/(75+50)
    tau = 0.5e-9         # 源→界面单程延迟
    s11 = gamma * np.exp(-1j * 4.0 * math.pi * _F * tau)  # 往返相位
    # none 窗：纯延迟谱无截断伪象（实测逐位 50→75）；平滑窗在频域卷积
    # 使延迟阶跃沿时间摊开（kaiser/hann 实测 50.3-50.4），不适合作解析锚
    prof = tdr_impedance_profile((_F, s11), window="none")
    z = prof["z_fft_ohm"]
    dt = prof["dt_s"]
    idx_after = int(2.0 * tau / dt) + 4  # 往返 2τ 后阶跃到 75
    before = z[max(idx_after - 20, 0):idx_after - 4]
    after = z[idx_after:idx_after + 20]
    assert float(np.median(before)) == pytest.approx(50.0, abs=0.5)
    assert float(np.median(after)) == pytest.approx(75.0, abs=0.5)
    assert tdr_two_route_disagreement(
        prof["z_fft_ohm"], prof["z_csum_ohm"]) <= 1e-6


def test_tdr_matched_line_flat_and_routes_agree() -> None:
    """匹配线（S11=0 含 DC）：全剖面 Z=Z0；双路分歧 ≤1e-9。"""
    s11 = np.zeros_like(_F, dtype=complex)
    prof = tdr_impedance_profile((_F, s11), window="none")
    mid = slice(prof["z_fft_ohm"].size // 4, 3 * prof["z_fft_ohm"].size // 4)
    np.testing.assert_allclose(prof["z_fft_ohm"][mid], 50.0, rtol=1e-9)
    assert tdr_two_route_disagreement(
        prof["z_fft_ohm"], prof["z_csum_ohm"]) <= 1e-9
    assert prof["n_rho_valid"] == _F.size


def test_tdr_termination_final_value_exact() -> None:
    """解析锚：短路馈电无损线 S11(0)=−1 → r(∞)=−1 → Z(∞)=0（DC 点入参）。"""
    # 半波长谐振馈线末端短路的最简 anchor：S11 全频段 = −1（λ/4 短路桩族）
    s11 = -np.ones_like(_F, dtype=complex)
    prof = tdr_impedance_profile((_F, s11), window="none")
    assert prof["z_final_ohm"] == pytest.approx(0.0, abs=0.5)


def test_tdr_input_guards() -> None:
    """守卫：形状不一致 / 点数不足 / 频率非升序显式拒绝。"""
    with pytest.raises(ValueError, match="形状须一致"):
        tdr_impedance_profile((np.arange(4.0), np.ones(5, complex)))
    with pytest.raises(ValueError, match="至少 4 点"):
        tdr_impedance_profile((np.arange(2.0), np.ones(2, complex)))
    with pytest.raises(ValueError, match="升序"):
        tdr_impedance_profile((np.array([3.0, 1.0, 2.0, 4.0]),
                               np.ones(4, complex)))
    with pytest.raises(ValueError, match="形状须一致"):
        tdr_two_route_disagreement(np.ones(4), np.ones(5))
