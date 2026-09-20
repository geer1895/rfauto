"""d5-array 阵列综合内核单测。

裁判=独立解析/闭式：
- 均匀阵 AF 闭式 |sin(N psi/2)/(N sin(psi/2))|；
- 侧射 HPBW 渐近式 0.886 lambda/(N d)（数值二分对照）；
- 栅瓣判据 d/lambda <= 1/(1+|u0|) 的可见区边界行为；
- Dolph-Chebyshev 副瓣电平达标 + 与 scipy.signal.windows.chebwin（独立实现）
  逐权重对照；
- 方向图积定理 F_total = F_element * AF。
全部确定性、无网络、无真机。
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.array_synthesis import (
    ChebyshevDesign,
    aperture_to_n_elements,
    array_factor,
    array_factor_angles,
    binomial_weights,
    broadside_hpbw_deg,
    broadside_hpbw_rad,
    chebyshev_weights,
    direction_cosine,
    field_db,
    grating_lobe_direction_cosines,
    grating_lobe_free_max_spacing,
    half_wave_dipole_field,
    has_grating_lobe,
    patch_element_field,
    pattern_multiplication,
    peak_sidelobe_level_db,
    planar_array_factor,
    steering_direction_cosine,
    synthesize_chebyshev,
    synthesize_taylor,
    taylor_weights,
    uniform_af_closed_form,
    uniform_weights,
)


def _half_power_u(n: int, d: float) -> float:
    """二分求侧射均匀阵 -3dB 方向余弦（主瓣内 AF 单调降）。"""
    w = uniform_weights(n)
    target = 1.0 / np.sqrt(2.0)
    lo, hi = 1e-12, 1.0 / (n * d)  # hi = 第一零点
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if float(np.abs(array_factor(mid, w, spacing_lambda=d))) > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ─── 均匀阵 AF 闭式对照 ───────────────────────────────────────────────────────

def test_uniform_af_matches_closed_form_broadside():
    n, d = 8, 0.5
    u = np.linspace(-1.0, 1.0, 801)
    af = array_factor(u, uniform_weights(n), spacing_lambda=d)
    ref = uniform_af_closed_form(2.0 * np.pi * d * u, n)
    assert np.allclose(np.abs(af), ref, atol=1e-12)
    # 峰值
    assert float(np.abs(array_factor(0.0, uniform_weights(n), spacing_lambda=d))) == pytest.approx(1.0)
    # 角点 u=±1
    for corner in (-1.0, 1.0):
        expected = abs(np.sin(n * np.pi * d * corner) / (n * np.sin(np.pi * d * corner)))
        got = float(np.abs(array_factor(corner, uniform_weights(n), spacing_lambda=d)))
        assert got == pytest.approx(expected, abs=1e-12)


def test_uniform_af_matches_closed_form_scanned():
    n, d, u0 = 6, 0.45, 0.3
    u = np.linspace(-1.0, 1.0, 501)
    af = array_factor(u, uniform_weights(n), spacing_lambda=d, scan_direction_cosine=u0)
    ref = uniform_af_closed_form(2.0 * np.pi * d * (u - u0), n)
    assert np.allclose(np.abs(af), ref, atol=1e-12)
    peak = float(np.abs(array_factor(u0, uniform_weights(n), spacing_lambda=d, scan_direction_cosine=u0)))
    assert peak == pytest.approx(1.0)


def test_uniform_af_peak_null_and_symmetry():
    n, d = 8, 0.5
    w = uniform_weights(n)
    u = np.linspace(-1.0, 1.0, 20001)
    mag = np.abs(array_factor(u, w, spacing_lambda=d))
    assert float(mag.max()) == pytest.approx(1.0)
    assert u[int(np.argmax(mag))] == pytest.approx(0.0, abs=1e-4)
    # 第一零点 u = 1/(N d) = 2/N（d=lambda/2）
    assert float(np.abs(array_factor(1.0 / (n * d), w, spacing_lambda=d))) < 1e-9
    # 侧射对阵 u <-> -u
    assert np.allclose(mag, np.abs(array_factor(-u, w, spacing_lambda=d)), atol=1e-12)


# ─── 主瓣宽度闭式对照 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(("n", "d"), [(20, 0.5), (40, 0.5)])
def test_broadside_hpbw_formula_matches_numeric(n, d):
    u_half = _half_power_u(n, d)
    hpbw_angle = 2.0 * np.arcsin(u_half)
    formula = broadside_hpbw_rad(n, d)
    assert abs(hpbw_angle - formula) / formula < 0.02


# ─── 栅瓣判据边界 ─────────────────────────────────────────────────────────────

def test_grating_lobe_boundary():
    n = 10
    w = uniform_weights(n)
    assert has_grating_lobe(0.99) is False
    assert grating_lobe_direction_cosines(0.99) == ()
    lobes = grating_lobe_direction_cosines(1.01)
    assert len(lobes) == 2
    assert lobes[0] == pytest.approx(-1.0 / 1.01, abs=1e-12)
    assert lobes[1] == pytest.approx(1.0 / 1.01, abs=1e-12)
    for u_lobe in lobes:
        assert float(np.abs(array_factor(u_lobe, w, spacing_lambda=1.01))) == pytest.approx(1.0, abs=1e-6)
    # 边界 d=lambda：栅瓣恰落在 u=±1
    assert grating_lobe_direction_cosines(1.0) == (-1.0, 1.0)


def test_grating_lobe_free_max_spacing():
    assert grating_lobe_free_max_spacing(0.0) == pytest.approx(1.0)
    assert grating_lobe_free_max_spacing(0.5) == pytest.approx(1.0 / 1.5)
    assert grating_lobe_free_max_spacing(1.0) == pytest.approx(0.5)
    u0 = 0.4
    smax = grating_lobe_free_max_spacing(u0)
    assert has_grating_lobe(smax * 0.999, u0) is False
    assert has_grating_lobe(smax * 1.001, u0) is True


# ─── Chebyshev 综合副瓣达标 ───────────────────────────────────────────────────

@pytest.mark.parametrize(("n", "sll"), [(8, -30.0), (11, -20.0), (9, -40.0), (16, -35.0)])
def test_chebyshev_sidelobe_meets_target(n, sll):
    w = chebyshev_weights(n, sll)
    u = np.linspace(-1.0, 1.0, 20001)
    mag = np.abs(array_factor(u, w, spacing_lambda=0.5))
    measured = peak_sidelobe_level_db(mag, u, main_lobe_direction_cosine=0.0)
    assert abs(measured - sll) < 0.05, f"实测副瓣 {measured:.4f} dB，目标 {sll} dB"


def test_chebyshev_equal_ripple():
    n, sll = 8, -30.0
    w = chebyshev_weights(n, sll)
    u = np.linspace(-1.0, 1.0, 20001)
    mag = np.abs(array_factor(u, w, spacing_lambda=0.5))
    interior = np.nonzero((mag[1:-1] >= mag[:-2]) & (mag[1:-1] >= mag[2:]))[0] + 1
    sidelobes = interior[interior != int(np.argmax(mag))]  # 去掉主瓣峰
    sl_db = 20.0 * np.log10(mag[sidelobes])
    assert sl_db.size >= 3
    assert float(sl_db.max()) <= sll + 0.05
    assert float(sl_db.max() - sl_db.min()) < 0.05


def test_chebyshev_matches_scipy_chebwin_reference():
    """与 scipy.signal.windows.chebwin（独立 Dolph-Chebyshev 实现）逐权重对照。"""
    from scipy.signal import windows

    for n, at in [(8, 20.0), (11, 30.0), (16, 40.0)]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            reference = windows.chebwin(n, at=at)
        assert np.allclose(chebyshev_weights(n, -at), reference, atol=1e-8)


def test_chebyshev_weights_symmetric_and_normalized():
    w = chebyshev_weights(8, -25.0)
    assert np.allclose(w, w[::-1])
    assert float(np.max(np.abs(w))) == pytest.approx(1.0)
    assert np.all(w > 0.0)
    # 偶数阵中心两元相等且为最大
    assert w[3] == pytest.approx(w[4])
    assert w[3] == pytest.approx(1.0)


def test_chebyshev_invalid_inputs():
    with pytest.raises(ValueError):
        chebyshev_weights(1, -20.0)
    with pytest.raises(ValueError):
        chebyshev_weights(8, 0.0)
    with pytest.raises(ValueError):
        chebyshev_weights(8, 5.0)
    with pytest.raises(ValueError):
        chebyshev_weights(8, float("nan"))
    with pytest.raises(ValueError):
        aperture_to_n_elements(0.0)
    with pytest.raises(ValueError):
        aperture_to_n_elements(2.0, spacing_lambda=-1.0)


# ─── 二项式加权 ───────────────────────────────────────────────────────────────

def test_binomial_weights_match_coefficients_and_no_sidelobes():
    n = 5
    w = binomial_weights(n)
    assert np.allclose(w, np.array([1.0, 4.0, 6.0, 4.0, 1.0]) / 6.0)
    assert float(w.max()) == pytest.approx(1.0)
    u = np.linspace(0.0, 1.0, 4001)
    mag = np.abs(array_factor(u, w, spacing_lambda=0.5))
    assert np.all(np.diff(mag) <= 1e-12), "二项式阵（d=lambda/2）应无副瓣"
    assert float(mag[0]) == pytest.approx(1.0)


# ─── 方向图积定理 / 单元方向图 ─────────────────────────────────────────────────

def test_pattern_multiplication_theorem():
    n, d = 6, 0.5
    theta = np.linspace(1.0, 179.0, 721)
    element = half_wave_dipole_field(theta)
    af = array_factor_angles(theta, uniform_weights(n), spacing_lambda=d, scan_deg=90.0)
    total = pattern_multiplication(element, af)
    assert np.allclose(total, element * af)
    idx = int(np.argmin(np.abs(theta - 90.0)))
    assert float(np.abs(total[idx])) == pytest.approx(float(element[idx]), rel=1e-6)


def test_half_wave_dipole_endpoint_limits():
    assert float(half_wave_dipole_field(0.0)) == pytest.approx(0.0)
    assert float(half_wave_dipole_field(180.0)) == pytest.approx(0.0)
    assert float(half_wave_dipole_field(90.0)) == pytest.approx(1.0)


# ─── 方向余弦 / 扫描 / 非法输入 ────────────────────────────────────────────────

def test_direction_cosine_axes_and_invalid():
    assert float(direction_cosine(60.0, axis="z")) == pytest.approx(0.5)
    assert float(direction_cosine(90.0, 0.0, axis="x")) == pytest.approx(1.0)
    assert float(direction_cosine(90.0, 90.0, axis="y")) == pytest.approx(1.0)
    assert steering_direction_cosine(90.0) == pytest.approx(0.0, abs=1e-12)
    assert steering_direction_cosine(60.0) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        direction_cosine(0.0, axis="w")


def test_array_factor_invalid_inputs():
    with pytest.raises(ValueError):
        array_factor(0.0, np.ones((2, 2)))
    with pytest.raises(ValueError):
        array_factor(0.0, [])
    with pytest.raises(ValueError):
        array_factor(0.0, [1.0, -1.0])
    with pytest.raises(ValueError):
        array_factor(0.0, [1.0, 1.0], spacing_lambda=0.0)
    with pytest.raises(ValueError):
        array_factor(0.0, [1.0, 1.0], spacing_lambda=-0.5)
    with pytest.raises(ValueError):
        array_factor(0.0, [1.0, 1.0], scan_direction_cosine=1.5)
    with pytest.raises(ValueError):
        array_factor(0.0, [np.nan, 1.0])


def test_scan_steering_peak_at_u0():
    n, d, u0 = 10, 0.5, 0.4
    w = uniform_weights(n)
    assert float(np.abs(array_factor(u0, w, spacing_lambda=d, scan_direction_cosine=u0))) == pytest.approx(1.0)
    u = np.linspace(-1.0, 1.0, 4001)
    mag = np.abs(array_factor(u, w, spacing_lambda=d, scan_direction_cosine=u0))
    assert u[int(np.argmax(mag))] == pytest.approx(u0, abs=2e-3)


# ─── 综合接口 / 确定性 / 辅助函数 ─────────────────────────────────────────────

def test_synthesize_chebyshev_design_fields():
    design = synthesize_chebyshev(8, -25.0, spacing_lambda=0.5)
    assert isinstance(design, ChebyshevDesign)
    assert design.n_elements == 8
    assert design.aperture_lambda == pytest.approx(3.5)
    assert design.broadside_hpbw_deg == pytest.approx(broadside_hpbw_deg(8, 0.5))
    assert design.grating_lobe_free is True
    assert design.grating_lobes == ()
    assert np.allclose(design.weights, chebyshev_weights(8, -25.0))
    wide = synthesize_chebyshev(8, -25.0, spacing_lambda=1.5)
    assert wide.grating_lobe_free is False
    assert len(wide.grating_lobes) == 2


def test_results_are_deterministic():
    u = np.linspace(-1.0, 1.0, 101)
    a = array_factor(u, chebyshev_weights(8, -30.0))
    b = array_factor(u, chebyshev_weights(8, -30.0))
    assert np.array_equal(a, b)
    assert np.array_equal(chebyshev_weights(8, -30.0), chebyshev_weights(8, -30.0))
    assert np.array_equal(binomial_weights(6), binomial_weights(6))


def test_peak_sidelobe_helper_edge_cases():
    with pytest.raises(ValueError):
        peak_sidelobe_level_db(np.ones(5), np.ones(4))
    with pytest.raises(ValueError):
        peak_sidelobe_level_db(np.ones(2), np.ones(2))
    u = np.linspace(-1.0, 1.0, 1001)
    mag = np.abs(array_factor(u, uniform_weights(2), spacing_lambda=0.5))
    assert peak_sidelobe_level_db(mag, u) < -200.0


def test_field_db_normalization_and_floor():
    db = field_db(np.array([1.0, 0.5, 1e-6]), floor_db=-60.0)
    assert db[0] == pytest.approx(0.0)
    assert db[1] == pytest.approx(-6.0206, abs=1e-3)
    assert db[2] == pytest.approx(-60.0)
    with pytest.raises(ValueError):
        field_db(np.zeros(3))


# ─── Taylor n-bar 加权（P2；裁判=scipy.signal.windows.taylor 独立实现）────────

def test_taylor_matches_scipy_reference():
    """与 scipy.signal.windows.taylor（norm=False 独立实现）逐权重对照。"""
    from scipy.signal import windows

    for n, sll, nb in [(8, 30.0, 4), (11, 35.0, 4), (16, 40.0, 5)]:
        reference = windows.taylor(n, nbar=nb, sll=sll, norm=False)
        reference = reference / reference.max()
        assert np.allclose(taylor_weights(n, -sll, nbar=nb), reference,
                           atol=1e-8)


def test_taylor_symmetric_and_normalized():
    for n in (8, 11):
        w = taylor_weights(n, -30.0)
        assert np.allclose(w, w[::-1])
        assert float(np.max(np.abs(w))) == pytest.approx(1.0)
        assert np.all(np.isfinite(w)) and np.all(w > 0.0)
    # 偶数阵：中心两元相等且为最大（连续线源口径的采样对称性）
    w8 = taylor_weights(8, -30.0)
    assert w8[3] == pytest.approx(w8[4])
    assert w8[3] == pytest.approx(1.0)


def test_taylor_peak_sidelobe_near_target():
    """array_factor 实测峰值副瓣 ≈ 目标（离散采样口径，容差按实测钉 2.5dB：
    连续孔径离散化的副瓣实测偏差 1.7-2.3dB，实测值钉死防漂移）。"""
    u = np.linspace(-1.0, 1.0, 20001)
    for n, sll, nb, measured_expect in [(8, -30.0, 4, -28.3),
                                        (11, -35.0, 4, -33.2),
                                        (16, -40.0, 5, -38.9)]:
        w = taylor_weights(n, sll, nbar=nb)
        mag = np.abs(array_factor(u, w, spacing_lambda=0.5))
        measured = peak_sidelobe_level_db(mag, u)
        assert measured == pytest.approx(measured_expect, abs=0.1)
        assert measured <= sll + 2.5


def test_taylor_invalid_inputs():
    with pytest.raises(ValueError):
        taylor_weights(0, -20.0)
    with pytest.raises(ValueError):
        taylor_weights(8, -20.0, nbar=0)
    with pytest.raises(ValueError):
        taylor_weights(8, -20.0, nbar=9)  # nbar > n 拒绝
    with pytest.raises(ValueError):
        taylor_weights(8, 0.0)
    with pytest.raises(ValueError):
        taylor_weights(8, 20.0)
    with pytest.raises(ValueError):
        taylor_weights(8, float("nan"))


def test_taylor_design_and_determinism():
    d = synthesize_taylor(12, -32.0, nbar=4)
    assert d.n_elements == 12 and d.nbar == 4
    assert d.sidelobe_level_db == pytest.approx(-32.0)
    assert np.allclose(d.weights, taylor_weights(12, -32.0, nbar=4))
    assert d.aperture_lambda == pytest.approx((12 - 1) * 0.5)
    assert np.array_equal(taylor_weights(12, -32.0, nbar=4),
                          taylor_weights(12, -32.0, nbar=4))


# ─── C2 阵列族加法式 helper（2026-09-15）：贴片腔模型单元闭式 / 平面阵可分离积 ───
# 裁判=独立手算闭式（Balanis Ch.14 主平面口径）+ 线阵 array_factor 复用；
# 数字全部出自确定性内核（5.8GHz 设计点：L=12.9058/W=16.9311 mm，patch_length
# 计算器同公式），无真机。

_C2 = dict(len_mm=12.9058, width_mm=16.9311, freq_ghz=5.8, h_mm=0.508)
_K0 = 2.0 * np.pi * 5.8 / 299.792458   # rad/mm


def _sinc(x):
    x = np.asarray(x, dtype=float)
    return np.where(np.abs(x) < 1e-12, 1.0, np.sin(np.where(np.abs(x) < 1e-12, 1.0, x))
                    / np.where(np.abs(x) < 1e-12, 1.0, x))


def test_patch_element_zenith_unity_and_even_in_theta():
    for axis in ("x", "y"):
        for phi in (0.0, 37.0, 90.0, 210.0):
            assert float(patch_element_field(0.0, phi, axis=axis, **_C2)) == pytest.approx(1.0)
    th = np.linspace(-90.0, 90.0, 181)
    for axis in ("x", "y"):
        f_pos = patch_element_field(th, 30.0, axis=axis, **_C2)
        f_neg = patch_element_field(-th, 30.0, axis=axis, **_C2)
        assert np.allclose(f_pos, f_neg, atol=1e-12)


def test_patch_element_principal_planes_match_textbook_closed_forms():
    """E 面 |E| = Sh·cos((k0L/2)sinθ)；H 面 |E| = cosθ·sinc((k0W/2)sinθ)（Balanis Ch.14）。"""
    th = np.linspace(0.0, 90.0, 181)
    s = np.sin(np.radians(th))
    e_plane = patch_element_field(th, 0.0, axis="x", **_C2)
    ref_e = _sinc(0.5 * _K0 * 0.508 * s) * np.cos(0.5 * _K0 * 12.9058 * s)
    assert np.allclose(e_plane, np.abs(ref_e), atol=1e-12)
    h_plane = patch_element_field(th, 90.0, axis="x", **_C2)
    ref_h = np.cos(np.radians(th)) * _sinc(0.5 * _K0 * 16.9311 * s)
    assert np.allclose(h_plane, np.abs(ref_h), atol=1e-12)
    # 主平面单调衰减（短贴片 L≈0.25λ0：E 面地平线 cos(k0L/2)=0.7077 无零点；
    # H 面地平线 cosθ=0）
    assert bool(np.all(np.diff(e_plane) <= 1e-12)) and bool(np.all(np.diff(h_plane) <= 1e-12))
    assert float(e_plane[-1]) == pytest.approx(0.7077, abs=5e-4)
    assert float(h_plane[-1]) == pytest.approx(0.0, abs=1e-12)


def test_patch_element_axis_y_is_ninety_degree_rotation_and_components_close():
    th = np.linspace(0.0, 90.0, 46)
    for phi in (0.0, 20.0, 65.0, 90.0, 135.0):
        fx = patch_element_field(th, phi - 90.0, axis="x", **_C2)
        fy = patch_element_field(th, phi, axis="y", **_C2)
        assert np.allclose(fx, fy, atol=1e-12), phi
        et = patch_element_field(th, phi, axis="y", component="theta", **_C2)
        ep = patch_element_field(th, phi, axis="y", component="phi", **_C2)
        assert np.allclose(np.sqrt(et ** 2 + ep ** 2), fy, atol=1e-12)


def test_patch_element_invalid_inputs():
    with pytest.raises(ValueError):
        patch_element_field(0.0, 0.0, axis="z", **_C2)
    with pytest.raises(ValueError):
        patch_element_field(0.0, 0.0, component="mag", **_C2)
    with pytest.raises(ValueError):
        patch_element_field(95.0, 0.0, **_C2)          # 地面下无场
    with pytest.raises(ValueError):
        patch_element_field(0.0, 0.0, len_mm=0.0, width_mm=1.0, freq_ghz=1.0)
    with pytest.raises(ValueError):
        patch_element_field(0.0, 0.0, len_mm=1.0, width_mm=1.0, freq_ghz=float("nan"))


def test_planar_array_factor_is_separable_product_pointwise():
    """2×2 积定理逐点：AF(θ,φ) == AF_x(sinθcosφ)·AF_y(sinθsinφ)（精确相等）。"""
    th = np.linspace(0.0, 90.0, 91)[:, None]
    ph = np.linspace(0.0, 360.0, 73)[None, :]
    wx, wy = uniform_weights(2), uniform_weights(2)
    af = planar_array_factor(th, ph, wx, wy, spacing_x_lambda=0.5, spacing_y_lambda=0.5)
    assert af.shape == (91, 73)
    u = direction_cosine(th, ph, "x")
    v = direction_cosine(th, ph, "y")
    ref = array_factor(u, wx, spacing_lambda=0.5) * array_factor(v, wy, spacing_lambda=0.5)
    assert np.array_equal(af, ref)
    # 侧射峰值=1，φ=0 切面退化为 x 向线阵 AF 闭式
    assert float(np.abs(af[0, 0])) == pytest.approx(1.0)
    cut = np.abs(planar_array_factor(th.ravel(), 0.0, wx, wy))
    assert np.allclose(cut, uniform_af_closed_form(2.0 * np.pi * 0.5 * np.sin(np.radians(th.ravel())), 2),
                       atol=1e-12)


def test_planar_array_factor_degenerates_to_linear_and_scans():
    th = np.linspace(0.0, 90.0, 181)
    lin = array_factor_angles(th, uniform_weights(4), spacing_lambda=0.5, scan_deg=0.0, axis="x")
    plan = planar_array_factor(th, 0.0, uniform_weights(4), [1.0], spacing_x_lambda=0.5)
    assert np.allclose(plan, lin, atol=1e-12)
    # 扫描：峰值落在 (u0, v0)=(0.3, 0.2) → θ0=asin(√(0.09+0.04)), φ0=atan2(0.2,0.3)
    u0, v0 = 0.3, 0.2
    th0 = np.degrees(np.arcsin(np.hypot(u0, v0)))
    ph0 = np.degrees(np.arctan2(v0, u0))
    peak = planar_array_factor(th0, ph0, uniform_weights(6), uniform_weights(5),
                               scan_u_x=u0, scan_u_y=v0)
    assert float(np.abs(peak)) == pytest.approx(1.0, abs=1e-9)
    with pytest.raises(ValueError):
        planar_array_factor(0.0, 0.0, [], uniform_weights(2))


def test_c2_uniform_1x4_broadside_hpbw_grating_and_chebyshev_sidelobe():
    """C2 验收②：均匀 1×4 主瓣 0°、HPBW 对照渐近式、d=λ0/2 无栅瓣、Chebyshev 副瓣=目标。"""
    n, d = 4, 0.5
    u_half = _half_power_u(n, d)
    hpbw_exact = np.degrees(2.0 * np.arcsin(u_half))
    formula = broadside_hpbw_deg(n, d)
    # 渐近式 0.886λ/(Nd) 对 N=4 偏 3.7%（精确 26.32° vs 25.38°，实测钉死）
    assert hpbw_exact == pytest.approx(26.32, abs=0.02)
    assert abs(hpbw_exact - formula) / formula < 0.05
    th = np.linspace(-90.0, 90.0, 3601)
    af = np.abs(array_factor_angles(th, uniform_weights(n), spacing_lambda=d, scan_deg=0.0, axis="x"))
    assert th[int(np.argmax(af))] == pytest.approx(0.0, abs=0.05)
    assert has_grating_lobe(d) is False and grating_lobe_direction_cosines(d) == ()
    # 单元×阵列积定理（元件 L 沿 y、阵列沿 x=H 面）：主瓣仍在天顶
    el = patch_element_field(th, 0.0, axis="y", **_C2)
    total = np.abs(pattern_multiplication(el, af))
    assert th[int(np.argmax(total))] == pytest.approx(0.0, abs=0.05)
    assert float(total.max()) == pytest.approx(1.0)
    # Chebyshev 加权 1×4 副瓣电平实测 = 目标（−20dB）
    w = chebyshev_weights(4, -20.0)
    u = np.linspace(-1.0, 1.0, 20001)
    mag = np.abs(array_factor(u, w, spacing_lambda=d))
    assert abs(peak_sidelobe_level_db(mag, u) - (-20.0)) < 0.05
