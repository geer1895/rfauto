"""NX-3 近场 beamfocusing + OAM 单测（2026-10-03）。

锚树口径（#118：解析恒等式 + 双路互证，不赌推导）：
- 聚焦相位：焦点处 Green 场图峰值=N 元同相叠加；离焦点衰减。
- 远场极限：聚焦相位与远场指向相位差 ∝ 1/d（一阶展开系数锚
  k·r_perp²/(2d)，first_order_prod → 常数带 [0.9,1.1]）。
- OAM 轴上场：l≢0 (mod N) 等比求和解析零（逐位）；l≡0 → √N·g。
- 模式纯度：纯 OAM 场 → purity=1（逐位级）；正交性 DFT 酉性。
- 相位模数：floor(2kR)+1 恒等 + kR 单调。
- fraunhofer：2D²/λ 独立直算恒等。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.nf_focusing_oam import (
    C0_M_S,
    farfield_tilt_phases,
    focal_field_map,
    focusing_farfield_limit_check,
    focusing_phases,
    fraunhofer_distance_m,
    oam_axis_field,
    oam_mode_purity,
    oam_ring_excitation,
    phase_mode_count,
)

_F = 28e9  # 28 GHz
_LAM = C0_M_S / _F


def _ring(n: int, radius: float) -> np.ndarray:
    phi = 2.0 * math.pi * np.arange(n) / n
    return np.stack([radius * np.cos(phi), radius * np.sin(phi),
                     np.zeros(n)], axis=1)


def test_fraunhofer_identity():
    d = 0.2
    out = fraunhofer_distance_m(d, _F)
    assert abs(out["fraunhofer_distance_m"] - 2.0 * d * d / _LAM) <= 1e-15
    assert abs(out["wavelength_m"] - _LAM) <= 1e-15


def test_focusing_peak_transverse():
    """聚焦：焦深横截面峰值在轴心；焦点场强 = Σ1/(4πRₙ) 相干恒等（逐位级）。

    轴向扫描峰值可被 1/R 包络拉向阵面（合法物理）——聚焦性判据取焦深
    横截面（标准 beamfocusing 口径）。
    """
    n = 10
    pos = np.stack([np.linspace(-0.1, 0.1, n), np.zeros(n), np.zeros(n)],
                   axis=1)
    p = np.array([0.0, 0.0, 0.4])
    w = focusing_phases(pos, p, _F)
    x_scan = np.linspace(-0.1, 0.1, 21)
    pts = np.stack([x_scan, np.zeros(21), np.full(21, 0.4)], axis=1)
    field = focal_field_map(pos, w, pts, _F)
    assert int(np.argmax(np.abs(field))) == 10  # 轴心=格点 10
    # 焦点场相干恒等：E(p) = Σₙ 1/(4πRₙ)（各元同相实正）
    dist = np.linalg.norm(pos - p[None, :], axis=1)
    expect = float(np.sum(1.0 / (4.0 * math.pi * dist)))
    fp = focal_field_map(pos, w, p[None, :], _F)[0]
    assert abs(abs(fp) - expect) <= 1e-12 * expect
    # 焦点处相位 = 全局参考补偿相位 −k·|r_ref−p|（相对相位全同相的构造性结果；
    # 大数值相位按 2π 折wrap后比较）
    ref = pos.mean(axis=0)
    expected_phase = -2.0 * math.pi / _LAM * float(np.linalg.norm(ref - p))
    delta = float(np.angle(np.exp(1j * (float(np.angle(fp)) - expected_phase))))
    assert abs(delta) <= 1e-9


def test_farfield_limit_first_order_prod():
    """极限一致：max|Δφ|·2d/(k·r_perp²) → 1（一阶展开锚，带 [0.9,1.1]）。

    线阵（x 向）+ 轴向远场：聚焦相对相位 = k·xₙ²/(2d) + O(kx⁴/d³)，
    外沿元取最大 → prod = 1 − O((r_perp/d)²)。环阵+轴向为简并态
    （全元等距、相对相位恒零），不用于本锚。
    """
    n = 8
    pos = np.stack([np.linspace(-0.05, 0.05, n), np.zeros(n), np.zeros(n)],
                   axis=1)
    u = np.array([0.0, 0.0, 1.0])
    ds = [1.0, 2.0, 5.0, 10.0]
    out = focusing_farfield_limit_check(pos, _F, u, ds)
    for prod in out["first_order_prod"]:
        assert 0.9 <= prod <= 1.1
    # 单调收敛：距离越远相位差越小
    diffs = out["max_phase_diff_rad"]
    assert diffs[0] > diffs[-1]


def test_oam_axis_field_exact_zero():
    """轴上场等比求和：l=1..N−1 解析零（逐位）；l=N 恒等 √N·g。"""
    n, r_ring = 8, 0.03
    z = 0.2
    for mode in range(1, n):
        out = oam_axis_field(n, mode, r_ring, _F, z)
        assert out["field"] == 0.0 + 0.0j
        assert out["sum_excitation"] == 0.0 + 0.0j
    out0 = oam_axis_field(n, 0, r_ring, _F, z)
    r_n = math.sqrt(r_ring**2 + z**2)
    g_expect = complex(math.cos(-2.0 * math.pi * r_n / _LAM),
                       math.sin(-2.0 * math.pi * r_n / _LAM)) / (4.0 * math.pi * r_n)
    assert abs(out0["field"] - math.sqrt(n) * g_expect) <= 1e-12 * abs(g_expect)


def test_oam_mode_purity_pure_mode():
    """纯模式场 → purity=1（DFT 单谱线）；混合场 → 已知配比。"""
    n = 16
    for mode in (0, 1, 5, 7):
        w = oam_ring_excitation(n, mode)
        out = oam_mode_purity(w * math.sqrt(n), mode)
        assert abs(out["purity"] - 1.0) <= 1e-12
    # 混合：0.6·l1 + 0.8·l3 → purity(1)=0.36
    phi = 2.0 * math.pi * np.arange(n) / n
    mix = 0.6 * np.exp(1j * 1 * phi) + 0.8 * np.exp(1j * 3 * phi)
    assert abs(oam_mode_purity(mix, 1)["purity"] - 0.36) <= 1e-12
    assert abs(oam_mode_purity(mix, 3)["purity"] - 0.64) <= 1e-12


def test_oam_excitation_normalization():
    w = oam_ring_excitation(12, 3)
    assert abs(float(np.vdot(w, w).real) - 1.0) <= 1e-15


def test_phase_mode_count_identity():
    out = phase_mode_count(0.05, _F)
    k = 2.0 * math.pi / _LAM
    assert out["n_phase_modes"] == math.floor(2.0 * k * 0.05) + 1
    out2 = phase_mode_count(0.10, _F)
    assert out2["n_phase_modes"] > out["n_phase_modes"]


def test_invalid_inputs_rejected():
    pos_ok = _ring(4, 0.01)
    with pytest.raises(ValueError):
        fraunhofer_distance_m(0.0, _F)
    with pytest.raises(ValueError):
        focusing_phases(pos_ok, np.array([0.0, 0.0]), _F)
    with pytest.raises(ValueError):
        farfield_tilt_phases(pos_ok, np.array([0.0, 0.0, 0.0]), _F)
    with pytest.raises(ValueError):
        focal_field_map(pos_ok, np.ones(4), pos_ok, _F)  # 评点=阵元（奇异）
    with pytest.raises(ValueError):
        oam_ring_excitation(1, 0)
    with pytest.raises(ValueError):
        oam_mode_purity(np.array([1.0 + 0j]), 0)
    with pytest.raises(ValueError):
        phase_mode_count(-0.1, _F)
