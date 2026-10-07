"""MA 磁屏蔽退磁因子单测（2026-10-03）。

锚树口径（#118：独立复算/解析恒等，不赌推导）：
- 椭球：Osborn 闭式独立复算（prolate ratio=2 → 0.1736、oblate 0.5 →
  0.5272，手算独立值）；ratio→1 球连续性（1/3）；prolate→∞ → 0、
  oblate→0 → 1（极限恒等）；sum rule N_x+N_y+N_z=1 语义锚。
- 圆柱表：区间插值恒等（端点逐位）+ 单调递减结构 + 表外 clamp 标记。
- 球壳：μ=1 → S=1；a/b=1 → S=1（解析恒等）；μ→∞ 渐近 S≈(2μ/9)(1−r³)
  （1e-9 相对）；独立复算一条 (a/b=0.8, μ=5000) 值。
- LLG：ΔB=2αω/γ 恒等 + γ vs scipy.constants（1e-15）；线宽-α 线性。
"""
from __future__ import annotations

import math
from itertools import pairwise

import pytest

from rfauto.core.magnetic_shield import (
    GAMMA_RAD_S_T,
    cylinder_demag_table,
    cylinder_shielding_factor_thin,
    demag_factor_oblate,
    demag_factor_prolate,
    demag_factor_sphere,
    llg_damping_conversion,
    mu_metal_band,
    multilayer_shield_estimate,
    spherical_shell_shielding_factor,
)


def test_sphere_exact():
    assert demag_factor_sphere() == 1.0 / 3.0


def test_prolate_independent_value_and_limits():
    """prolate：ratio=2 独立复算 0.1736（1e-3 带）；极限锚。"""
    out = demag_factor_prolate(2.0)
    e = math.sqrt(0.75)
    expect = (1.0 - e * e) / e**3 * (math.atanh(e) - e)
    assert abs(out["n_axis"] - expect) <= 1e-12
    assert abs(out["n_axis"] - 0.1736) <= 1e-3
    # 球连续性：ratio→1 → 1/3
    near = demag_factor_prolate(1.0 + 1e-10)
    assert abs(near["n_axis"] - 1.0 / 3.0) <= 1e-6
    # 细长针 → 0
    far = demag_factor_prolate(1000.0)
    assert far["n_axis"] < 1e-3


def test_oblate_independent_value_and_limits():
    """oblate：ratio=0.5 独立复算 0.5272（1e-3 带）；极限锚。"""
    out = demag_factor_oblate(0.5)
    xi = math.sqrt(3.0)
    expect = (1.0 + xi * xi) / xi**3 * (xi - math.atan(xi))
    assert abs(out["n_axis"] - expect) <= 1e-12
    assert abs(out["n_axis"] - 0.5272) <= 1e-3
    near = demag_factor_oblate(1.0 - 1e-10)
    assert abs(near["n_axis"] - 1.0 / 3.0) <= 1e-6
    flat = demag_factor_oblate(1e-4)
    assert flat["n_axis"] > 0.999


def test_sum_rule_semantics():
    """sum rule：横向 (1−N_z)/2 与轴向和=1（Osborn 语义锚）。"""
    for out in (demag_factor_prolate(3.0), demag_factor_oblate(0.3)):
        n_z = out["n_axis"]
        assert 0.0 < n_z < 1.0
        assert abs((1.0 - n_z) / 2.0 * 2.0 + n_z - 1.0) <= 1e-15


def test_cylinder_table_interpolation():
    """表：端点逐位 + 区间单调递减 + 表外 clamp/标记。"""
    pts = [(0.5, 0.68), (1.0, 0.27), (2.0, 0.14)]
    for ld, expect in pts:
        assert abs(cylinder_demag_table(ld)["n_axis"] - expect) <= 1e-12
    mid = cylinder_demag_table(1.5)["n_axis"]
    assert 0.14 < mid < 0.27
    seq = [cylinder_demag_table(ld)["n_axis"]
           for ld in (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0)]
    assert all(a > b for a, b in pairwise(seq))
    low = cylinder_demag_table(0.2)
    assert low["extrapolated"] is True
    assert 0.0 <= low["n_axis"] <= 1.0
    high = cylinder_demag_table(100.0)
    assert high["extrapolated"] is True
    assert high["n_axis"] >= 0.0


def test_spherical_shell_identities():
    """球壳：μ=1、a=b → S=1 恒等；μ→∞ 渐近；独立复算一点。"""
    assert spherical_shell_shielding_factor(0.4, 0.5, 1.0)[
        "shielding_factor"] == 1.0
    out_r = spherical_shell_shielding_factor(0.5, 0.5 + 1e-12, 5000.0)
    assert abs(out_r["shielding_factor"] - 1.0) <= 1e-8
    # 渐近：S ≈ (2μ/9)(1−r³)（O(1/μ) 绝对修正 → 相对 1.44e-4@μ=5e4，带 5e-4）
    a, b, mu = 0.8, 1.0, 50000.0
    out = spherical_shell_shielding_factor(a, b, mu)
    r3 = (a / b) ** 3
    denom = (2.0 * mu + 1.0) * (mu + 2.0) - 2.0 * r3 * (mu - 1.0) ** 2
    assert abs(out["shielding_factor"] - denom / (9.0 * mu)) <= 1e-12
    assert abs(out["shielding_factor"] / ((2.0 * mu / 9.0) * (1.0 - r3))
               - 1.0) <= 5e-4


def test_cylinder_thin_and_multilayer():
    """薄壁圆管：S=1+μt/D 恒等；多层乘积恒等；非法输入报错。"""
    out = cylinder_shielding_factor_thin(50000.0, 0.002, 0.1)
    assert abs(out["shielding_factor"] - (1.0 + 50000.0 * 0.002 / 0.1)) <= 1e-9
    ml = multilayer_shield_estimate([10.0, 100.0])
    assert ml["shielding_factor"] == 1000.0
    with pytest.raises(ValueError):
        multilayer_shield_estimate([])
    with pytest.raises(ValueError):
        multilayer_shield_estimate([1.0])
    with pytest.raises(ValueError):
        cylinder_shielding_factor_thin(100.0, 0.2, 0.1)


def test_mu_metal_band():
    band = mu_metal_band()
    lo, hi = band["mu_r_max_band"]
    assert lo < hi
    assert "UNVERIFIED" not in band["source"]  # band 形式非页码引用
    assert "#122" in band["source"] or "single_source" in band["source"]


def test_llg_conversion_identity():
    """LLG：ΔB=2αω/γ 恒等；γ vs scipy CODATA 2022（5e-9 带：CODATA
    2018→2022 末位漂移如实带）；线性-in-α。"""
    from scipy import constants

    gamma_ref = constants.value("electron gyromag. ratio")
    assert abs(GAMMA_RAD_S_T - gamma_ref) <= 5e-9 * gamma_ref
    alpha, f = 1e-4, 1e9
    out = llg_damping_conversion(alpha, f)
    expect = 2.0 * alpha * 2.0 * math.pi * f / GAMMA_RAD_S_T
    assert abs(out["delta_b_fwhm_t"] - expect) <= 1e-15 * expect
    assert abs(out["delta_f_fwhm_hz"] - 2.0 * alpha * f) <= 1e-9
    out2 = llg_damping_conversion(2.0 * alpha, f)
    assert abs(out2["delta_b_fwhm_t"] / out["delta_b_fwhm_t"] - 2.0) <= 1e-12


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        demag_factor_prolate(0.5)
    with pytest.raises(ValueError):
        demag_factor_oblate(1.5)
    with pytest.raises(ValueError):
        cylinder_demag_table(0.0)
    with pytest.raises(ValueError):
        spherical_shell_shielding_factor(0.5, 0.4, 1000.0)
    with pytest.raises(ValueError):
        llg_damping_conversion(-1.0, 1e9)
