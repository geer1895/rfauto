"""NX-6 共形阵阵因子单测（2026-10-03）。

锚树口径（#118：结构恒等式 + 跨模块互证，不赌推导）：
- 单元退化：N=1、q=0 → AF=|w|（无遮挡正面）；背面方向 → AF=0（遮挡）。
- 平面退化锚：半径 R→∞（弧上小角度、等间距线性布点）共形阵 vs
  planar_degeneracy_af 逐点一致（q=0 无遮挡口径）。
- cos^q 加权恒等：q=1 时逐元贡献可独立复算（测试内独立书写）。
- 相位模数：与 nf_focusing_oam.phase_mode_count 跨模块互证（同式）。
- 环模分解：单一相位模激励 → DFT 单谱线（酉性）。
- 球冠：极点元（θ=0）法向=+z、位置=极点（构造性恒等）。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.conformal_array import (
    conformal_array_factor,
    cylindrical_positions,
    phase_mode_count,
    planar_degeneracy_af,
    ring_mode_decomposition,
    spherical_cap_positions,
)
from rfauto.core.nf_focusing_oam import (
    phase_mode_count as phase_mode_count_ref,
)

_F = 10e9


def test_single_element_degenerate():
    r = 0.5
    out = cylindrical_positions(r, 8, 1, 0.1, _F)
    pos = out["positions_m"][:1]
    nor = out["normals_m"][:1]
    # 沿 1 号元法向（径向）观察：q=0 → AF=|w|
    u = nor[0]
    res = conformal_array_factor(pos, nor, np.array([2.0 + 0j]), u, _F, 0.0)
    assert abs(res["af_abs"] - 2.0) <= 1e-12
    # 背面方向：遮挡 → 0
    res_back = conformal_array_factor(pos, nor, np.array([2.0 + 0j]), -u,
                                      _F, 0.0)
    assert res_back["af_abs"] == 0.0
    assert res_back["n_active"] == 0


def test_q_weighting_identity():
    """q=1：AF = Σ wₙ cosψₙ e^{jkû·rₙ}（正面元），测试内独立复算。"""
    out = cylindrical_positions(0.3, 4, 1, 0.05, _F)
    pos, nor = out["positions_m"], out["normals_m"]
    w = np.ones(4, dtype=complex)
    u = np.array([0.0, 0.0, 1.0])  # 轴向：cosψ=0 全遮挡 → AF=0
    res = conformal_array_factor(pos, nor, w, u, _F, 1.0)
    assert res["af_abs"] == 0.0
    # û=x：元 0 (φ=0) cosψ=1、元 2 (φ=π) cosψ=−1 遮挡、元 1/3 cosψ=0
    res_x = conformal_array_factor(pos, nor, w, np.array([1.0, 0.0, 0.0]),
                                   _F, 1.0)
    k = 2.0 * math.pi * _F / 299792458.0
    expect = complex(np.sum(w[:1] * 1.0 * np.exp(1j * k * (pos[:1] @ np.array([1.0, 0.0, 0.0])))))
    assert abs(res_x["af_complex"] - expect) <= 1e-14


def test_planar_degeneracy_large_radius():
    """R→∞ 平面退化：大半径小弧等距点（径向法向）沿弧心法向观察 →
    无遮挡口径下与 planar_degeneracy_af（同点集、无方向图）逐点一致。"""
    n = 8
    spacing = 0.015
    r_big = 100.0
    arc = spacing * (n - 1)
    span = arc / r_big
    out = cylindrical_positions(r_big, n, 1, 0.05, _F,
                                az_start_rad=-span / 2.0, az_span_rad=span)
    pos = out["positions_m"]
    nor = out["normals_m"]
    w = np.ones(n, dtype=complex)
    u = np.array([1.0, 0.0, 0.0])  # 弧心法向（径向 +x）
    res = conformal_array_factor(pos, nor, w, u, _F, 0.0)
    ref = planar_degeneracy_af(pos, w, u, _F)
    assert abs(res["af_complex"] - ref) <= 1e-12 * abs(ref)
    assert res["n_active"] == n
    # 近似同相（小弧）：|AF| ≈ n（小弧相位弯曲 ≤8e-3 rad，rel 1e-4）
    assert abs(res["af_abs"]) == pytest.approx(float(n), rel=1e-4)


def test_phase_mode_count_cross_module():
    """跨模块互证：conformal_array.phase_mode_count ≡ nf_focusing_oam 版。"""
    for r, f in ((0.05, 10e9), (0.15, 28e9), (0.5, 3e9)):
        a = phase_mode_count(r, f)
        b = phase_mode_count_ref(r, f)
        assert a["n_phase_modes"] == b["n_phase_modes"]


def test_ring_mode_decomposition_single_mode():
    """单一相位模激励 wₙ=e^{j2πmn/N} → DFT 在该模一条谱线（酉 DFT）。"""
    n, mode_l = 12, 3
    w = np.exp(1j * 2.0 * math.pi * mode_l * np.arange(n) / n)
    spec = ring_mode_decomposition(w)
    power = np.abs(spec) ** 2
    assert abs(power[mode_l] - 1.0) <= 1e-12
    assert float(power.sum()) <= 1.0 + 1e-12


def test_spherical_cap_pole_identity():
    """球冠极点元：位置=(0,0,R)、法向=(0,0,1)（构造性恒等）。"""
    r = 0.2
    out = spherical_cap_positions(r, math.radians(30.0), 5, 8, _F)
    pos, nor = out["positions_m"], out["normals_m"]
    assert abs(pos[0, 2] - r) <= 1e-15
    assert abs(nor[0, 2] - 1.0) <= 1e-15
    assert np.abs(pos[0, :2]).max() <= 1e-15
    # 全部元在球面上：‖rₙ‖=R
    norms = np.linalg.norm(pos, axis=1)
    assert np.allclose(norms, r, rtol=1e-12)


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        cylindrical_positions(0.0, 4, 1, 0.1, _F)
    with pytest.raises(ValueError):
        cylindrical_positions(0.5, 1, 1, 0.1, _F)
    with pytest.raises(ValueError):
        cylindrical_positions(0.5, 4, 1, 0.1, _F, az_span_rad=-1.0)
    with pytest.raises(ValueError):
        spherical_cap_positions(0.2, 0.0, 3, 8, _F)
    pos_ok = np.zeros((3, 3))
    nor_ok = np.zeros((3, 3))
    nor_ok[:, 2] = 1.0
    with pytest.raises(ValueError):
        conformal_array_factor(pos_ok, nor_ok, np.ones(2), [0, 0, 1], _F)
    with pytest.raises(ValueError):
        conformal_array_factor(pos_ok, nor_ok, np.ones(3), [0, 0, 0], _F)
    with pytest.raises(ValueError):
        conformal_array_factor(pos_ok, nor_ok, np.ones(3), [0, 0, 1], _F,
                               element_pattern_exp=-1.0)
    with pytest.raises(ValueError):
        ring_mode_decomposition(np.array([1.0 + 0j]))
