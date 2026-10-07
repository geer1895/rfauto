"""F-ME.28 TMA 时间调制阵列内核单测（round3 方案 F-F 表件 3 判据）。

裁判口径（#118 双路径，全部预声明，#122 不凑绿）：

- **主判据 A（连续闭式 vs 时域 DFT）**：矩形开关波形按 bin 平均采样
  （一阶保持采样，边界 bin 记精确覆盖分数）2^14 点 FFT 取谱，再除以
  采样核 sinc(m/N)·e^{jπm/N}（bin 平均卷积的频域核，与系数公式无关的
  采样方案属性）反卷积。可达精度受周期混叠限制：混叠项
  c_{m+qN}·sinc(q+m/N)·(−1)^q 对 |c_m| 的相对量级 ~1e-5（|m|≤64、
  τ=0.1 最坏）——**任务书草案 "rel 1e-9" 对连续闭式 vs 2^14-FFT 不可达**
  （网格参考相位 πm/N 即 ~4e-3 @m=64），按 #122 如实降钉：
  归一化误差 |deconv−c|/max(|c|,1e-3·max|c|) ≤ 1e-3（实测最坏 4.9e-5，
  开发冒烟 2026-09-27）。
- **主判据 B（离散对齐恒等式，1e-9 级）**：τ=0.5 网格对齐（K=N/2 整数、
  窗缘落采样点）硬 0/1 序列的 FFT vs 测试内独立几何级数推导的离散
  Dirichlet 闭式——两路径均离散同 N，混叠消失，rel ≤ 1e-9
  （实测 4.3e-12）：钉时域 DFT 机器本身无系统差。
- **收敛裁判 C**：N 翻倍误差必须下降（2^12 → 2^14 实测 6.6e-4 → 1.0e-5），
  #118 "小步长收敛数值" 精神。
- Parseval：Σ_{|m|≤M'}|c_nm|²→τ_n，尾部 ≤ 2/(π²(M'+1))（|c_m|² ≤ 1/(πm)²
  积分界）→ M'=4e6 时 rel ≤ 5.1e-7（τ=0.1 最坏），预声明 rel 1e-6
  （实测 2.5e-7）。
- 基波=静态阵恒等式 vs array_synthesis.array_factor(normalize=False)
  （交叉面只读复用，err/|ref|max ≤ 1e-12 预声明，实测 ~2e-16——
  归一化度量避开 AF 深零点的除小数放大）。
- 能量守恒：d=λ/2 正交性闭式 ∫_{-1}^{1}|S_m|²du = 2·Σ_n|w_n c_nm|²
  （两独立路径：u 网格梯形积分 vs 单元代数）。

`reliability` 类外部裁判不适用（TMA 文献无数值表可逐位回收）；闭式法源
见 core/tma_array.py docstring（Shanks-Bickmore 1959 / Kummer 1963 /
Tennant-Chambers 2004）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import tma_array
from rfauto.core.array_synthesis import array_factor

# ─── 预声明容差（上表来源，改动须同步文件头推导）─────────────────────────────
TOL_DFT_NORM = 1e-3  # 主判据 A（实测最坏 4.9e-5）
TOL_DISCRETE = 1e-9  # 主判据 B（实测 4.3e-12）
TOL_PARSEVAL = 1e-6  # M'=4e6 截断（实测 2.5e-7）
TOL_STATIC = 1e-12  # 基波恒等式（实测 ~2e-16）
PARSEVAL_MAX_ORDER = 4_000_000

TAU_GRID = (0.1, 0.3, 0.5, 0.9)
CENTER_GRID = (0.0, 0.25)

# 8 元 λ/2 阵共用几何
N_EL = 8
SPACING = 0.5
POSITIONS = np.arange(N_EL) * SPACING
WEIGHTS = np.array([0.4, 0.7, 1.0, 0.9, 0.9, 1.0, 0.7, 0.4])
U_GRID = np.linspace(-1.0, 1.0, 1801)


# ─── 开关序列采样器（bin 平均 = 一阶保持，测试侧独立实现）────────────────────


def bin_average_samples(center: float, tau: float, n_fft: int) -> np.ndarray:
    """连续矩形窗（中心 center、占空比 τ，归一化周期坐标，可回绕）按 bin
    平均采样：第 k 样本 = N·(bin k 与导通窗的圆区间重叠长度) ∈ [0,1]。"""
    edges = np.arange(n_fft + 1) / n_fft
    start = (center - tau / 2.0) % 1.0
    end = start + tau
    lo, hi = start, min(end, 1.0)
    overlap = np.clip(np.minimum(edges[1:], hi) - np.maximum(edges[:-1], lo), 0.0, None)
    if end > 1.0:
        overlap = overlap + np.clip(
            np.minimum(edges[1:], end - 1.0) - np.maximum(edges[:-1], 0.0), 0.0, None
        )
    return overlap * n_fft


def dft_coefficients(samples: np.ndarray, orders: np.ndarray) -> np.ndarray:
    """实序列 FFT → 复 Fourier 系数（负阶取共轭，Hermitian）。"""
    spec = np.fft.fft(samples) / samples.size
    return np.array(
        [spec[m] if m >= 0 else np.conj(spec[-m]) for m in orders], dtype=complex
    )


# ─── 1. 系数基本恒等式 ────────────────────────────────────────────────────────


def test_coefficients_fundamental_and_zero_tau_exact():
    orders = np.arange(-5, 6)
    for tau_val in TAU_GRID:
        c = tma_array.switch_fourier_coefficients(tau_val, orders, 0.25)
        assert c[orders == 0][0] == tau_val  # 逐位（非 sinc 极限）
    # τ=0：全行逐位 0（元常闭）
    c0 = tma_array.switch_fourier_coefficients(0.0, orders, 0.0)
    assert np.all(c0 == 0.0)
    # 标量入参 → shape (M,)；数组入参 → (N, M)
    assert tma_array.switch_fourier_coefficients(0.3, orders).shape == (11,)
    mat = tma_array.switch_fourier_coefficients([0.1, 0.2], orders)
    assert mat.shape == (2, 11)
    # win_center 缺省 = τ/2（窗起点 0 口径）
    c_def = tma_array.switch_fourier_coefficients(0.4, orders)
    c_exp = tma_array.switch_fourier_coefficients(0.4, orders, 0.2)
    assert np.array_equal(c_def, c_exp)


def test_coefficients_tau1_sidebands_bitwise_zero():
    # τ=1 恒等：全部边带阶系数逐位 0（sinc(整数) 的 ~1e-16 浮点噪声不接见）
    orders = np.arange(-32, 33)
    c = tma_array.switch_fourier_coefficients(1.0, orders, 0.37)
    assert c[orders == 0][0] == 1.0
    assert np.all(c[orders != 0] == 0.0)
    # 数组混合 τ：τ=1 行归零、他行不受牵连
    c_mix = tma_array.switch_fourier_coefficients(
        np.array([1.0, 0.5]), orders, np.array([0.1, 0.25])
    )
    assert np.all(c_mix[0, orders != 0] == 0.0)
    assert np.any(c_mix[1, orders != 0] != 0.0)


def test_coefficients_hermitian_symmetry():
    # U_n(t) 实 ⇒ c_{−m} = conj(c_m）：全 (τ×center) 网格（2-D 数组路径）
    orders = np.arange(-32, 33)
    for tau_val in TAU_GRID:
        for center in CENTER_GRID:
            c = tma_array.switch_fourier_coefficients(
                np.full(2, tau_val), orders, np.full(2, center)
            )
            pos = c[:, orders > 0]
            neg_conj = np.conj(c[:, orders < 0][:, ::-1])
            assert np.allclose(pos, neg_conj, rtol=0, atol=1e-15)


def test_coefficients_window_start_form_equivalence():
    # 两种代数路径（#118）：中心形式（win_center=τ/2）vs 窗起点式
    # c_m = (1 − e^{−j2πmτ})/(j2πm)——同量独立推导；mτ 整数处 |c|~1e-16
    # （sinc 零点），两路径 fp 噪声互除无意义 ⇒ 带地板归一化误差 ≤ 1e-9
    orders = np.arange(-40, 41)
    orders_nz = orders[orders != 0].astype(float)
    for tau_val in (0.13, 0.37, 0.62, 0.85):
        c_center = tma_array.switch_fourier_coefficients(tau_val, orders_nz, tau_val / 2.0)
        c_start = (1.0 - np.exp(-2j * np.pi * orders_nz * tau_val)) / (2j * np.pi * orders_nz)
        err = np.abs(c_center - c_start) / np.maximum(
            np.abs(c_start), 1e-3 * np.abs(c_start).max()
        )
        assert err.max() < 1e-9


def test_coefficients_translation_identity():
    # win_center 平移 δ ⇒ c_m 乘 e^{−j2πmδ}，模不变（相位中心偏移口径的自洽）
    orders = np.arange(-20, 21)
    delta = 0.1
    c_a = tma_array.switch_fourier_coefficients(0.4, orders, 0.25)
    c_b = tma_array.switch_fourier_coefficients(0.4, orders, (0.25 + delta) % 1.0)
    factor = np.exp(-2j * np.pi * orders.astype(float) * delta)
    assert np.allclose(c_b, c_a * factor, rtol=1e-14, atol=1e-16)
    assert np.allclose(np.abs(c_b), np.abs(c_a), rtol=1e-14)


# ─── 2. 主判据 A/B/C：时域 DFT 双路径裁判 ─────────────────────────────────────


def _dft_referee(tau_val: float, center: float, m_max: int, n_fft: int) -> float:
    """归一化误差 |deconv−c|/max(|c|, floor)，floor=1e-3·max|c|。"""
    orders = np.arange(-m_max, m_max + 1)
    c = tma_array.switch_fourier_coefficients(tau_val, orders, center)
    samples = bin_average_samples(center, tau_val, n_fft)
    est = dft_coefficients(samples, orders)
    # bin 平均采样的频域核（采样方案属性，非系数公式）：sinc(m/N)·e^{jπm/N}
    deconv = est / (np.sinc(orders / n_fft) * np.exp(1j * np.pi * orders / n_fft))
    err = np.abs(deconv - c)
    scale = np.maximum(np.abs(c), 1e-3 * np.abs(c).max())
    return float((err / scale).max())


@pytest.mark.parametrize("tau_val", TAU_GRID)
@pytest.mark.parametrize("center", CENTER_GRID)
def test_coefficients_vs_dft_dual_path(tau_val, center):
    # 主判据 A：连续闭式 vs 2^14 bin 平均 FFT（容差预声明，见文件头）
    assert _dft_referee(tau_val, center, 64, 1 << 14) < TOL_DFT_NORM


def test_coefficients_dft_convergence_referee():
    # 裁判 C：N 翻倍误差必须下降（τ=0.1 最坏点；#118 小步长收敛精神）
    err_12 = _dft_referee(0.1, 0.0, 64, 1 << 12)
    err_14 = _dft_referee(0.1, 0.0, 64, 1 << 14)
    assert err_14 < err_12


@pytest.mark.parametrize("center", CENTER_GRID)
def test_coefficients_vs_discrete_dirichlet_aligned(center):
    # 主判据 B（1e-9 级）：τ=0.5 网格对齐硬采样，FFT vs 测试内独立几何级数
    # 推导的离散 Dirichlet 闭式（同 N 离散双路径，混叠消失）
    n_fft = 1 << 14
    tau_val = 0.5
    samples = bin_average_samples(center, tau_val, n_fft)
    assert np.all((samples == 0.0) | (samples == 1.0))  # 窗缘落采样点 ⇒ 硬 0/1
    orders = np.arange(-64, 65)
    est = dft_coefficients(samples, orders)
    start = round(((center - tau_val / 2.0) % 1.0) * n_fft) % n_fft
    k_on = round(tau_val * n_fft)
    on_idx = np.arange(start, start + k_on) % n_fft
    ref = np.array(
        [
            (k_on / n_fft) * np.mean(np.exp(-2j * np.pi * m * on_idx / n_fft))
            if m != 0
            else tau_val
            for m in orders
        ],
        dtype=complex,
    )
    rel = np.abs(est - ref) / np.maximum(np.abs(ref), 1e-4 * np.abs(ref).max())
    assert rel.max() < TOL_DISCRETE


# ─── 3. Parseval 恒等式 ───────────────────────────────────────────────────────


@pytest.mark.parametrize("tau_val", TAU_GRID)
def test_parseval_identity_large_truncation(tau_val):
    # Σ_{|m|≤M'}|c_m|² → τ（尾部 ≤ 2/(π²(M'+1)) = 5.07e-7 abs，rel@τ=0.1
    # 5.1e-7；预声明 rel 1e-6，实测 ~2.5e-7）
    res = tma_array.parseval_residual(np.array([tau_val]), max_order=PARSEVAL_MAX_ORDER)
    assert res[0] < TOL_PARSEVAL


def test_parseval_residual_center_agnostic_and_zero_tau():
    # Parseval 右端 τ_n 与 win_center 无关（时域 |U|²=U 的占空比平均）
    res_a = tma_array.parseval_residual(
        np.array([0.3, 0.8]), win_center=np.array([0.0, 0.6]),
        max_order=200_000,
    )
    res_b = tma_array.parseval_residual(np.array([0.3, 0.8]), max_order=200_000)
    assert np.allclose(res_a, res_b, rtol=1e-12, atol=0.0)
    assert res_b.max() < 1e-3  # M'=2e5 尾部 ~1/(π²·2e5)≈5e-7 rel@0.3
    # τ=0 元残差恒 0（绝对差定义自然给出）
    res0 = tma_array.parseval_residual(np.array([0.0, 0.5]), max_order=100)
    assert res0[0] == 0.0


# ─── 4. 谐波方向图：基波恒等式 / Hermitian / 频比 ─────────────────────────────


@pytest.mark.parametrize("tau_val", [1.0, 0.7])
def test_harmonic_fundamental_equals_static_af(tau_val):
    # 基波 = 静态锥削阵 AF（τ_n 直接乘权重）：与交叉面 array_factor 对照
    # （normalize=False；err/|ref|max 度量避开 AF 深零点）
    result = tma_array.harmonic_patterns(
        U_GRID, POSITIONS, WEIGHTS, np.full(N_EL, tau_val),
        max_order=0, scan_direction_cosine=0.13,
    )
    ref = array_factor(
        U_GRID, WEIGHTS, spacing_lambda=SPACING,
        scan_direction_cosine=0.13, normalize=False,
    ) * tau_val
    assert result.orders == (0,)
    err = np.abs(result.patterns[0] - ref) / np.abs(ref).max()
    assert err.max() < TOL_STATIC


def test_harmonic_sideband_hermitian_pattern():
    # ratio=0（窄带）+ 实权重实位置：|S_{−m}(u)| = |S_m(u)|（复值恒等式带
    # u→−u：S_{−m}(u) = conj(S_m(−u))，模相等口径断言）
    result = tma_array.harmonic_patterns(
        U_GRID, POSITIONS, WEIGHTS, np.full(N_EL, 0.6), max_order=3
    )
    i_p = result.orders.index(2)
    i_m = result.orders.index(-2)
    assert np.allclose(
        np.abs(result.patterns[i_m]), np.abs(result.patterns[i_p]),
        rtol=1e-10, atol=1e-12,
    )
    # 复值镜像：S_{−m}(u) == conj(S_m(−u))（逐位级）
    assert np.allclose(
        result.patterns[i_m], np.conj(result.patterns[i_p][::-1]), atol=1e-14
    )
    # ratio>0 时边带波数 k_m≠k_{−m}，模恒等破缺（显式区分）
    result_wb = tma_array.harmonic_patterns(
        U_GRID, POSITIONS, WEIGHTS, np.full(N_EL, 0.6), max_order=3, freq_ratio_fp_f0=0.4
    )
    assert not np.allclose(
        np.abs(result_wb.patterns[result_wb.orders.index(-2)]),
        np.abs(result_wb.patterns[result_wb.orders.index(2)]),
        atol=1e-3,
    )


def test_harmonic_freq_ratio_wavenumber_consistency():
    # S_m(u; ratio=r) ≡ S_m(u; ratio=0, positions×(1+m·r))（边带波数折算的
    # 唯一入口是空间相位）；基波（m=0，k 因子恒 1）对 ratio 逐位不变
    ratio = 0.5
    r_mod = tma_array.harmonic_patterns(
        U_GRID, POSITIONS, WEIGHTS, np.full(N_EL, 0.6), max_order=2, freq_ratio_fp_f0=ratio
    )
    r_ref = tma_array.harmonic_patterns(
        U_GRID, POSITIONS * (1.0 + 1.0 * ratio), WEIGHTS, np.full(N_EL, 0.6), max_order=2
    )
    i = r_mod.orders.index(1)
    err = np.abs(r_mod.patterns[i] - r_ref.patterns[i]) / np.abs(r_ref.patterns[i]).max()
    assert err.max() < 1e-12
    # m=0 不随 ratio 变（逐位）
    r_base = tma_array.harmonic_patterns(
        U_GRID, POSITIONS, WEIGHTS, np.full(N_EL, 0.6), max_order=2
    )
    i0 = r_mod.orders.index(0)
    assert np.array_equal(r_mod.patterns[i0], r_base.patterns[i0])


def test_harmonic_single_element_magnitude():
    # 单元阵：S_m(u) = c_m·e^{j相位} ⇒ |S_m(u)| ≡ |c_m|（相位核模 1）
    tau_val = 0.3
    orders = np.array([-2, -1, 0, 1, 2])
    c = tma_array.switch_fourier_coefficients(tau_val, orders, 0.25)
    result = tma_array.harmonic_patterns(
        U_GRID, np.array([0.25]), np.array([1.0]), np.array([tau_val]),
        win_center=np.array([0.25]), max_order=2,
    )
    for i, _m in enumerate(orders):
        assert np.allclose(np.abs(result.patterns[i]), abs(c[i]), rtol=1e-14, atol=1e-300)


# ─── 5. 边带电平面 / 能量守恒 ─────────────────────────────────────────────────


def test_sll_metrics_consistency_and_guards():
    result = tma_array.harmonic_patterns(
        U_GRID, POSITIONS, WEIGHTS, np.full(N_EL, 0.6), max_order=3
    )
    metrics = tma_array.sll_metrics(result.patterns, result.orders, U_GRID)
    fund_peak = float(np.abs(result.patterns[result.orders.index(0)]).max())
    side_peaks = [
        float(np.abs(result.patterns[i]).max())
        for i, m in enumerate(result.orders)
        if m != 0
    ]
    assert metrics["fundamental_peak_abs"] == pytest.approx(fund_peak, rel=1e-15)
    assert metrics["max_sideband_peak_abs"] == pytest.approx(max(side_peaks), rel=1e-15)
    assert metrics["fundamental_to_max_sideband_db"] == pytest.approx(
        20.0 * np.log10(fund_peak / max(side_peaks)), rel=1e-12
    )
    assert sum(metrics["order_power_fraction"].values()) == pytest.approx(1.0, rel=1e-12)
    # 无边带阶（max_order=0）→ 比值 inf（如实不判 0）
    m0 = tma_array.sll_metrics(
        result.patterns[result.orders.index(0)][np.newaxis, :], [0], U_GRID
    )
    assert m0["fundamental_to_max_sideband_db"] == float("inf")
    # orders 缺基波 → ValueError
    with pytest.raises(ValueError, match="基波"):
        tma_array.sll_metrics(result.patterns[:2], [-1, 1], U_GRID)


def test_energy_conservation_parseval_power():
    # 能量守恒（双路径 #118）：d=λ/2 正交性闭式 ∫|S_m|²du = 2Σ_n|w_n c_nm|²
    # ⇒ Σ_m ∫|S_m|²du = 2Σ_n|w_n|²·(同截断 Σ_m|c_nm|²)；对照 sll_metrics 的
    # u 网格梯形积分（截断一致的核系数——全 Parseval→τ 恒等式另测）
    tau_arr = np.full(N_EL, 0.6)
    result = tma_array.harmonic_patterns(
        U_GRID, POSITIONS, WEIGHTS, tau_arr, max_order=6
    )
    metrics = tma_array.sll_metrics(result.patterns, result.orders, U_GRID)
    power_grid = sum(metrics["order_power_abs"].values())
    coeffs = tma_array.switch_fourier_coefficients(
        tau_arr, np.asarray(result.orders), tau_arr / 2.0
    )
    power_closed = 2.0 * float(
        np.sum(np.abs(WEIGHTS) ** 2 * np.sum(np.abs(coeffs) ** 2, axis=-1))
    )
    assert power_grid == pytest.approx(power_closed, rel=1e-9)


# ─── 6. 波束捷变演示面（和/差口径）────────────────────────────────────────────


def _sum_diff_switchings(tau_val: float = 0.7):
    """和口径（缺省计时）vs 差口径（右半阵列 win_center 平移半周期）。"""
    tau_arr = np.full(N_EL, tau_val)
    wc_sum = tau_arr / 2.0
    wc_diff = np.where(
        np.arange(N_EL) < N_EL // 2, tau_arr / 2.0, (tau_arr / 2.0 + 0.5) % 1.0
    )
    return tau_arr, wc_sum, wc_diff


def test_beam_agility_fundamental_immobile():
    # 基波对计时免疫（TMA 基本恒等式）：两套开关序列基波峰均钉在侧射，
    # 偏移=0（数组进出，不做优化）
    tau_arr, wc_sum, wc_diff = _sum_diff_switchings()
    ba = tma_array.beam_agility_compare(
        U_GRID, POSITIONS, np.ones(N_EL), tau_arr, wc_sum, tau_arr, wc_diff, order=1
    )
    assert ba.fundamental_peak_u_sum == pytest.approx(0.0, abs=1e-12)
    assert ba.fundamental_peak_u_diff == pytest.approx(0.0, abs=1e-12)
    assert ba.fundamental_peak_offset_u == 0.0
    # 两套基波方向图逐位一致（计时在 m=0 无自由度）
    assert np.array_equal(ba.fundamental_pattern_sum, ba.fundamental_pattern_diff)


def test_beam_agility_sideband_difference_null():
    # 差口径第一边带在侧射精确消零（成对抵消：右半 c_{n1} = −左半 c_{n1}），
    # 和口径第一边带峰在侧射——差方向图只出现在边带（Tennant-Chambers 2004）
    tau_arr, wc_sum, wc_diff = _sum_diff_switchings()
    ba = tma_array.beam_agility_compare(
        U_GRID, POSITIONS, np.ones(N_EL), tau_arr, wc_sum, tau_arr, wc_diff, order=1
    )
    peak_diff = float(np.abs(ba.sideband_pattern_diff).max())
    assert ba.sideband_broadside_abs_diff < 1e-12 * peak_diff
    # 和口径边带：峰在侧射（模值=边带图案自身峰值）
    peak_sum = float(np.abs(ba.sideband_pattern_sum).max())
    assert ba.sideband_broadside_abs_sum == pytest.approx(peak_sum, rel=1e-12)
    # 和口径边带峰钉侧射；差口径边带峰离侧射（|u_peak| 落 λ/2 差波束典型带）
    assert ba.sideband_peak_u_sum == pytest.approx(0.0, abs=1e-12)
    assert 0.1 < abs(ba.sideband_peak_u_diff) < 0.7


def test_beam_agility_sideband_symmetric_magnitude():
    # 实有效权重+实位置 ⇒ |S(−u)| = |S(u)|（两边带图案）；差口径峰对 ±u_d 镜像
    tau_arr, wc_sum, wc_diff = _sum_diff_switchings()
    ba = tma_array.beam_agility_compare(
        U_GRID, POSITIONS, np.ones(N_EL), tau_arr, wc_sum, tau_arr, wc_diff, order=1
    )
    for pattern in (ba.sideband_pattern_sum, ba.sideband_pattern_diff):
        mag = np.abs(pattern)
        assert np.allclose(mag[::-1], mag, rtol=1e-12, atol=1e-14)
    step = float(U_GRID[1] - U_GRID[0])
    assert abs(abs(ba.sideband_peak_u_diff) - abs(-ba.sideband_peak_u_diff)) <= step


def test_beam_agility_order_guard():
    tau_arr, wc_sum, wc_diff = _sum_diff_switchings()
    with pytest.raises(ValueError, match="边带阶"):
        tma_array.beam_agility_compare(
            U_GRID, POSITIONS, np.ones(N_EL), tau_arr, wc_sum, tau_arr, wc_diff, order=0
        )


# ─── 7. 输入守卫与 to_dict ────────────────────────────────────────────────────


def test_input_guards():
    good = np.full(3, 0.5)
    # τ 越界 / 非有限 / bool（df7+⑯）
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        tma_array.switch_fourier_coefficients(1.5, np.array([0]))
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        tma_array.switch_fourier_coefficients(-0.1, np.array([0]))
    with pytest.raises(ValueError, match="tau"):
        tma_array.switch_fourier_coefficients(float("nan"), np.array([0]))
    with pytest.raises(ValueError, match="bool"):
        tma_array.switch_fourier_coefficients(True, np.array([0]))
    with pytest.raises(ValueError, match="bool"):
        tma_array.harmonic_patterns(
            np.array([0.0]), np.array([0.0]), np.array([1.0]), np.array([True])
        )
    # win_center ∈ [0,1)
    with pytest.raises(ValueError, match="win_center"):
        tma_array.switch_fourier_coefficients(0.5, np.array([1]), 1.0)
    with pytest.raises(ValueError, match="win_center"):
        tma_array.switch_fourier_coefficients(0.5, np.array([1]), -0.25)
    # 负位置（沿阵轴坐标非负口径）
    with pytest.raises(ValueError, match="positions_lambda"):
        tma_array.harmonic_patterns(
            np.array([0.0]), np.array([-0.5]), np.array([1.0]), np.array([0.5])
        )
    # max_order：负 / 非整数 / bool
    with pytest.raises(ValueError, match="max_order"):
        tma_array.harmonic_patterns(
            np.array([0.0]), np.array([0.0]), np.array([1.0]), np.array([0.5]), max_order=-1
        )
    with pytest.raises(ValueError, match="max_order"):
        tma_array.harmonic_patterns(
            np.array([0.0]), np.array([0.0]), np.array([1.0]), np.array([0.5]), max_order=1.5
        )
    with pytest.raises(ValueError, match="bool"):
        tma_array.harmonic_patterns(
            np.array([0.0]), np.array([0.0]), np.array([1.0]), np.array([0.5]), max_order=True
        )
    # 长度失配 / 非有限权重 / 非有限 u 网格
    with pytest.raises(ValueError, match="tau"):
        tma_array.harmonic_patterns(
            np.array([0.0, 0.5]), POSITIONS[:2], WEIGHTS[:2], good
        )
    with pytest.raises(ValueError, match="weights"):
        tma_array.harmonic_patterns(
            np.array([0.0]), np.array([0.0]), np.array([np.inf]), np.array([0.5])
        )
    with pytest.raises(ValueError, match="direction_cosines"):
        tma_array.harmonic_patterns(
            np.array([np.nan]), np.array([0.0]), np.array([1.0]), np.array([0.5])
        )


def test_result_to_dict_json_roundtrip():
    result = tma_array.harmonic_patterns(
        U_GRID[:16], POSITIONS[:4], WEIGHTS[:4], np.full(4, 0.5), max_order=2
    )
    payload = result.to_dict()
    assert json.dumps(payload)  # JSON 可序列化
    assert payload["orders"] == [-2, -1, 0, 1, 2]
    assert payload["patterns_shape"] == [5, 16]
    re_im = payload["patterns_re_im"][2][0]
    assert re_im == pytest.approx(
        [result.patterns[2, 0].real, result.patterns[2, 0].imag], abs=1e-15
    )
    # include_patterns=False → 遥测载荷（矩阵置 None）
    slim = result.to_dict(include_patterns=False)
    assert slim["patterns_re_im"] is None
    assert slim["direction_cosines"] is None
    # BeamAgilityResult.to_dict 同过 json.dumps
    tau_arr, wc_sum, wc_diff = _sum_diff_switchings()
    ba = tma_array.beam_agility_compare(
        U_GRID[:16], POSITIONS[:4], np.ones(4), tau_arr[:4], wc_sum[:4],
        tau_arr[:4], wc_diff[:4], order=1,
    )
    assert json.dumps(ba.to_dict())


# ─── 8. service 薄服务（JSON 信封，ok=False 不抛）─────────────────────────────


def test_service_pattern_envelope():
    from rfauto.service.tma_array_service import TMA_SERVICE_SCHEMA_VERSION, tma_pattern_service

    resp = tma_pattern_service(
        {
            "n_elements": 4,
            "spacing_lambda": 0.5,
            "tau": 0.6,
            "max_order": 2,
            "u_grid": {"start": -1.0, "stop": 1.0, "step": 0.5},
        }
    )
    assert resp["ok"] is True
    assert resp["schema_version"] == TMA_SERVICE_SCHEMA_VERSION
    assert resp["result"]["orders"] == [-2, -1, 0, 1, 2]
    assert len(resp["result"]["patterns_re_im"]) == 5
    assert json.dumps(resp)  # 全信封 JSON 可序列化
    # 与内核直调一致（服务零物理公式，规则 7）
    core = tma_array.harmonic_patterns(
        np.array([-1.0, -0.5, 0.0, 0.5, 1.0]),
        np.arange(4) * 0.5,
        np.ones(4),
        np.full(4, 0.6),
        max_order=2,
    )
    srv_raw = np.array(resp["result"]["patterns_re_im"], dtype=float)
    srv = srv_raw[..., 0] + 1j * srv_raw[..., 1]
    assert np.allclose(srv, core.patterns, rtol=0, atol=1e-12)


def test_service_error_envelope_no_raise():
    from rfauto.service.tma_array_service import tma_pattern_service

    bad_inputs = [
        {"n_elements": 4, "tau": 1.5},  # τ 越界
        {"positions_lambda": [0.0, -1.0], "tau": 0.5},  # 负位置
        {"n_elements": 4},  # 缺 tau
        "not-a-dict",
    ]
    for bad in bad_inputs:
        resp = tma_pattern_service(bad)
        assert resp["ok"] is False
        assert isinstance(resp["error"], str) and resp["error"]


def test_service_beam_agility_envelope():
    from rfauto.service.tma_array_service import tma_beam_agility_service

    resp = tma_beam_agility_service(
        {
            "n_elements": 8,
            "tau_sum": 0.7,
            "tau_diff": 0.7,
            "diff_half_period_shift": True,
            "order": 1,
            "u_grid": {"start": -1.0, "stop": 1.0, "step": 0.001},
        }
    )
    assert resp["ok"] is True
    assert resp["result"]["fundamental_peak_offset_u"] == pytest.approx(0.0, abs=1e-12)
    assert resp["result"]["sideband_broadside_abs_diff"] < 1e-9
    assert json.dumps(resp)
    # 错误入参 → ok=False 不抛
    assert tma_beam_agility_service({"n_elements": 4, "order": 0})["ok"] is False
