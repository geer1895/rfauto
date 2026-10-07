"""MM-2 编码超表面方向图内核测试（规格 规格深案 §A-5，全离线零仿真）。

锚（预声明，实现与判据同 commit）：
- A1 全 0 码 → 均匀阵 2D sinc² 闭式逐格互证（uniform_af_closed_form 可分离积，
  含 pad 网格全部单元，容差 1e-12——两法独立求值仅浮点残差）；
- A2 同一 w=e^{jφ} 面两法对拍 ≤0.5dB（规格锚）：零填充 DFT vs
  array_synthesis 复权孪生 series_feed_array_factor（:818，array_factor:299
  的复指数核同式）+ array_factor(:299) 本体经线性分解
  AF(w)=AF(Re w)+j·AF(Im w)（normalize=False）同核钉（其实化守卫的复数
  契约——复权面不可直入，见被测模块 docstring）+ 2D 面对暴力双和逐格
  （精确网格点，非邻近点）；
- A3 量化损失实测 vs sinc²(1/2^b) 理论 ≤0.05dB（规格锚，合成理想阵）：
  1/2/3-bit 双报；理论与 metasurface_lut.quantization_loss_db 既有单源
  逐位互证 + 3.9224/0.9121/0.2244 数字锚（规格书 −3.92/−0.91 承接）；
- A4 梯度码指向偏差 ≤ 束宽 5%（构造已知指向码例，HPBW≈0.886/(N·d/λ)
  Balanis 大阵渐近——array_synthesis 模块同口径）；
- A5 守卫负例：bits≤0 / 码值负·越界·非整数 / 非二维·空矩阵 /
  period·f0 非正非有限 / pad<1 / 不可见区指向；
- A6 metasurface_lut.quantize_phase_deg 复用一致性：梯度码与度域直接量化
  逐位同栅格；A7 同参确定性（两次调用逐位一致）。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.array_synthesis import array_factor
from rfauto.core.coding_metasurface import (
    code_phases_rad,
    coding_scattering_pattern,
    coding_weights,
    crosscheck_array_factor_1d,
    gradient_code_matrix,
    pattern_db,
    quantization_loss_measured_db,
    uniform_code_closed_form,
    validate_code_matrix,
)
from rfauto.core.metasurface_lut import quantization_loss_db, quantize_phase_deg

PERIOD_M = 299792458.0 / (2 * 10.0e9)  # 10 GHz 半波长周期：d/λ = 0.5（可见区恰好全覆盖）
F0_GHZ = 10.0


# ─── A1 全 0 码 → 2D sinc² 闭式（逐格）──────────────────────────────────────────


def test_a1_all_zero_code_matches_sinc2_closed_form_per_cell():
    codes = np.zeros((16, 12), dtype=int)
    result = coding_scattering_pattern(codes, bits=2, period_m=PERIOD_M, f0_ghz=F0_GHZ, pad=4, normalize=False)
    closed = uniform_code_closed_form(result.u, result.v, 16, 12, result.spacing_lambda)
    magnitude = np.abs(result.pattern) / np.abs(result.pattern).max()
    # 两法独立（DFT vs 可分离闭式）：仅浮点残差
    assert np.abs(magnitude - closed).max() < 1e-12
    # 峰值语义：全 0 码 |AF|_max = M·N
    assert abs(np.abs(result.pattern).max() - 16 * 12) < 1e-9
    # pad=1（无零填充）与闭式亦逐格一致（u 轴含负频，grating 区不越可见区）
    r1 = coding_scattering_pattern(codes, bits=2, period_m=PERIOD_M, f0_ghz=F0_GHZ, pad=1, normalize=False)
    closed1 = uniform_code_closed_form(r1.u, r1.v, 16, 12, r1.spacing_lambda)
    assert np.abs(np.abs(r1.pattern) / np.abs(r1.pattern).max() - closed1).max() < 1e-12


def test_a1_normalized_pattern_peak_is_unity():
    codes = np.zeros((8, 8), dtype=int)
    result = coding_scattering_pattern(codes, bits=2, period_m=PERIOD_M, f0_ghz=F0_GHZ, pad=4, normalize=True)
    assert abs(np.abs(result.pattern).max() - 1.0) < 1e-12
    db = pattern_db(result)
    assert abs(db.max()) < 1e-9  # 峰值 0 dB


# ─── A2 同一 w 面、两法对拍 ≤0.5dB（规格锚）──────────────────────────────────────


def test_a2_dft_vs_array_factor_complex_twin_under_half_db():
    rng = np.random.default_rng(20261002)
    for bits in (1, 2, 3):
        row = rng.integers(0, 2 ** bits, size=(1, 17))
        report = crosscheck_array_factor_1d(row, bits, PERIOD_M, F0_GHZ, pad=4)
        assert report["max_abs_db"] < 0.5
        # 复权核为同式求值，实际残差应远小于门（数值一致性）
        assert report["max_abs_db"] < 1e-9


def test_a2_array_factor_299_same_kernel_via_linearity_decomposition():
    """array_factor(:299) 实化复数契约下的同核钉：AF(w)=AF(Re w)+j·AF(Im w)。

    normalize=False（其归一化分母按实化后各自计，不可复用）；码例选
    Re/Im 权和非退化（|Σw|=√2），否则触发 array_factor 的归一化守卫。
    权面与 crosscheck 同形：(1, N) 行转置 (N, 1)（单元沿 m 轴、v 简并），
    对拍点取 DFT u 网格的可见区抽样（同 u 直接重算，无插值）。
    """
    from rfauto.core.coding_metasurface import _af_grid  # 测试取内部网格工具对齐同一 u 采样

    row = np.array([[0, 1, 2, 2, 3, 0, 1, 2]])  # Σcos=−1、Σsin=+1，均非零
    weights_col = coding_weights(row, bits=2).T  # (N, 1)
    assert abs(weights_col[:, 0].real.sum()) > 0 and abs(weights_col[:, 0].imag.sum()) > 0
    spacing = PERIOD_M * (F0_GHZ * 1e9) / 299792458.0
    pattern, u_grid, _ = _af_grid(weights_col, spacing, 4)
    visible = np.nonzero(np.abs(u_grid) <= 0.9)[0]
    u_pts = u_grid[visible[::11]]
    dft_pts = pattern[visible[::11], 0]
    af_lin = array_factor(u_pts, weights_col[:, 0].real, spacing_lambda=spacing, normalize=False) + 1j * array_factor(
        u_pts, weights_col[:, 0].imag, spacing_lambda=spacing, normalize=False
    )
    scale = float(np.abs(af_lin).max())
    assert np.abs(dft_pts - af_lin).max() / scale < 1e-9
    # 复权孪生与 :299 线性分解在同点互证（同核两路由）
    from rfauto.core.array_synthesis import series_feed_array_factor

    af_twin = series_feed_array_factor(
        u_pts, weights_col[:, 0], element_pitch=PERIOD_M, k0=2.0 * np.pi * F0_GHZ * 1e9 / 299792458.0
    )
    assert np.abs(af_twin - af_lin).max() / scale < 1e-12


def test_a2_2d_face_matches_brute_force_double_sum_on_grid():
    rng = np.random.default_rng(7)
    codes = rng.integers(0, 4, size=(12, 10))
    result = coding_scattering_pattern(codes, bits=2, period_m=PERIOD_M, f0_ghz=F0_GHZ, pad=4, normalize=False)
    m_idx = np.arange(12, dtype=float)[:, np.newaxis]
    n_idx = np.arange(10, dtype=float)[np.newaxis, :]
    weights = coding_weights(codes, 2)
    worst = 0.0
    for i in range(0, result.u.size, 7):
        for j in range(0, result.v.size, 5):
            ref = np.sum(weights * np.exp(1j * 2.0 * np.pi * result.spacing_lambda * (m_idx * result.u[i] + n_idx * result.v[j])))
            worst = max(worst, abs(result.pattern[i, j] - ref) / np.abs(ref))
    assert worst < 1e-9


# ─── A3 量化损失：实测 vs sinc² 理论 ≤0.05dB（理论 + 实测双报）───────────────────


@pytest.mark.parametrize("bits,expected_theory_db", [(1, 3.9224), (2, 0.9121), (3, 0.2244)])
def test_a3_quantization_loss_measured_matches_sinc2_theory(bits: int, expected_theory_db: float):
    theory = quantization_loss_db(bits)  # 既有单源（metasurface_lut）
    assert abs(theory - expected_theory_db) < 5e-4  # 数字锚：3.9224/0.9121/0.2244
    measured = quantization_loss_measured_db(
        n_elements=64, bits=bits, u_beam=0.317, v_beam=0.211,
        period_m=PERIOD_M, f0_ghz=F0_GHZ, pad=8,
    )
    # 规格锚：实测 vs sinc² 理论 ≤0.05dB（大阵 + 非驻点指向，O(1/n) 相消）
    assert abs(measured - theory) < 0.05


def test_a3_quantization_loss_zero_for_broadside_grid_aligned_scan():
    """侧射（u0=v0=0）：量化前即全 0 码，无量化误差 → 零损失。"""
    measured = quantization_loss_measured_db(
        n_elements=16, bits=2, u_beam=0.0, v_beam=0.0,
        period_m=PERIOD_M, f0_ghz=F0_GHZ, pad=4,
    )
    assert abs(measured) < 1e-12


# ─── A4 梯度码指向偏差 ≤ 束宽 5%（构造已知指向码例）──────────────────────────────


def _beam_direction(result) -> tuple[float, float]:
    """峰值定位：网格 argmax + log 域三点抛物线亚格插值（pad=32 网格够细）。"""
    power = np.abs(result.pattern)
    i, j = np.unravel_index(int(power.argmax()), power.shape)
    du = 1.0 / (result.u.size * result.spacing_lambda)
    dv = 1.0 / (result.v.size * result.spacing_lambda)

    def quad_offset(a: float, b: float, c: float) -> float:
        den = a - 2.0 * b + c
        return float(0.5 * (a - c) / den) if abs(den) > 1e-30 else 0.0

    u_off = quad_offset(float(np.log(power[i - 1, j])), float(np.log(power[i, j])), float(np.log(power[i + 1, j])))
    v_off = quad_offset(float(np.log(power[i, j - 1])), float(np.log(power[i, j])), float(np.log(power[i, j + 1])))
    return float(result.u[i] + u_off * du), float(result.v[j] + v_off * dv)


@pytest.mark.parametrize(
    "bits,n,u0,v0",
    [
        (2, 16, 0.30, 0.20),
        (2, 16, 0.25, -0.10),
        (2, 32, 0.15, 0.00),  # 2-bit 小扫描角：大阵（N=32）平均量化斜率后方进 5%
        (3, 16, 0.30, 0.20),
        (3, 16, 0.25, -0.10),
    ],
)
def test_a4_gradient_code_points_within_5pct_of_beamwidth(bits: int, n: int, u0: float, v0: float):
    codes = gradient_code_matrix((n, n), bits, u0, v0, PERIOD_M, F0_GHZ)
    result = coding_scattering_pattern(codes, bits, PERIOD_M, F0_GHZ, pad=32)
    u_peak, v_peak = _beam_direction(result)
    hpbw = 0.886 / (n * result.spacing_lambda)  # Balanis 大阵渐近（模块 docstring 同口径）
    deviation = float(np.hypot(u_peak - u0, v_peak - v0))
    assert deviation <= 0.05 * hpbw, f"bits={bits} ({u0},{v0}): dev={deviation:.5f} > 5%×HPBW={0.05 * hpbw:.5f}"


def test_a4_gradient_code_matches_quantize_phase_deg_grid():
    """A6 复用一致性：梯度码与 quantize_phase_deg 度域直接量化同栅格（逐位）。

    metasurface_lut.quantize_phase_deg 为标量 API（内置 round 不收数组），
    被测模块向量化实现同规则——等价性以标量逐元循环钉住。
    """
    codes = gradient_code_matrix((8, 8), 2, 0.3, -0.2, PERIOD_M, F0_GHZ)
    m_idx = np.arange(8, dtype=float)[:, np.newaxis]
    n_idx = np.arange(8, dtype=float)[np.newaxis, :]
    spacing = PERIOD_M * (F0_GHZ * 1e9) / 299792458.0
    phase_deg = np.degrees(-2.0 * np.pi * spacing * (m_idx * 0.3 + n_idx * (-0.2)))
    step_deg = 360.0 / 4
    expected = np.zeros_like(codes)
    for mi in range(8):
        for ni in range(8):
            expected[mi, ni] = round(quantize_phase_deg(float(phase_deg[mi, ni]), 2) / step_deg) % 4
    assert np.array_equal(codes, expected)
    # 码 → 相位往返：φ = code·2π/2^bits 落在量化栅格上
    phases = code_phases_rad(codes, 2)
    step = 2.0 * np.pi / 4
    assert np.abs(phases / step - np.rint(phases / step)).max() < 1e-12


# ─── A5 守卫负例 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bits", [0, -1, -7])
def test_a5_nonpositive_bits_rejected(bits: int):
    with pytest.raises(ValueError, match="bits"):
        validate_code_matrix(np.zeros((2, 2), dtype=int), bits)
    with pytest.raises(ValueError, match="bits"):
        coding_scattering_pattern(np.zeros((2, 2), dtype=int), bits, PERIOD_M, F0_GHZ)


def test_a5_code_out_of_range_rejected():
    with pytest.raises(ValueError, match="越界"):
        validate_code_matrix(np.array([[0, 1], [2, 4]]), 2)  # 4 ≥ 2^2
    with pytest.raises(ValueError, match="越界"):
        validate_code_matrix(np.array([[0, -1]]), 2)  # 负码
    with pytest.raises(ValueError, match="非整数"):
        validate_code_matrix(np.array([[0.5, 1.0]]), 2)


def test_a5_shape_and_physical_guards():
    with pytest.raises(ValueError, match="二维"):
        validate_code_matrix(np.zeros(4, dtype=int), 2)
    with pytest.raises(ValueError, match="非空"):
        validate_code_matrix(np.zeros((0, 3), dtype=int), 2)
    with pytest.raises(ValueError, match="period_m"):
        coding_scattering_pattern(np.zeros((2, 2), dtype=int), 2, 0.0, F0_GHZ)
    with pytest.raises(ValueError, match="f0_ghz"):
        coding_scattering_pattern(np.zeros((2, 2), dtype=int), 2, PERIOD_M, -1.0)
    with pytest.raises(ValueError, match="pad"):
        coding_scattering_pattern(np.zeros((2, 2), dtype=int), 2, PERIOD_M, F0_GHZ, pad=0)
    with pytest.raises(ValueError, match="可见区"):
        gradient_code_matrix((4, 4), 2, 1.5, 0.0, PERIOD_M, F0_GHZ)
    with pytest.raises(ValueError, match="行向量"):
        crosscheck_array_factor_1d(np.zeros((2, 2), dtype=int), 2, PERIOD_M, F0_GHZ)


# ─── A7 确定性 ──────────────────────────────────────────────────────────────────


def test_a7_deterministic_repeat_calls_bitwise_identical():
    rng = np.random.default_rng(42)
    codes = rng.integers(0, 4, size=(8, 8))
    r1 = coding_scattering_pattern(codes, 2, PERIOD_M, F0_GHZ, pad=4)
    r2 = coding_scattering_pattern(codes, 2, PERIOD_M, F0_GHZ, pad=4)
    assert np.array_equal(r1.pattern, r2.pattern)
    assert np.array_equal(r1.u, r2.u)
    assert np.array_equal(r1.weights, r2.weights)
    assert np.array_equal(
        gradient_code_matrix((8, 8), 2, 0.3, -0.2, PERIOD_M, F0_GHZ),
        gradient_code_matrix((8, 8), 2, 0.3, -0.2, PERIOD_M, F0_GHZ),
    )
