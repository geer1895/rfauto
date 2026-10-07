"""F-ME 器件族批 1：压缩感知 / ℓ1 重加权稀疏阵内核单测（round3 方案 F-F 表件 8 判据）。

裁判口径（#118 双路径/独立来源，全部预声明，#122 不凑绿）：

- **主判据（合成回收，复场口径）**：真稀疏阵 K=5（候选 λ/2 栅格 N=13，
  真位置间距 ≥ λ/2 的预声明相干条件）→ 复目标场 b = A·w_true →
  IRWL1（K=5 约束）恢复。预声明：位置命中 ≥ 4/5（栅格对齐容差 1 格内
  精确命中；本配置栅格对齐应 5/5）、命中格权重幅值 rel ≤ 1e-6、
  相干度 μ < 0.05、包络残差 ≤ −200 dB。开发冒烟实测（2026-09-27）：
  命中 5/5、rel 4.9e-16、μ=0.0025、残差 −309.7 dB。
- **软阈值恒等式**：|x| ≤ t → 0；|x| > t → x − t·sign(x)（实轴逐位）；
  复数：|out| = max(0,|z|−t)、相位保持、z=0 无 nan 路径。
- **全阵退化**：K = N_grid → BPDN→最小二乘 → 残差 ≤ −40 dB（预声明，
  实测 −307 dB）。
- **ISTA 裁判**：λ=0 退化为梯度下降 → 与 np.linalg.lstsq 独立路径对拍
  rel ≤ 1e-9（实测 3e-15）；步长 1/L（L=σ_max²）保证目标函数单调非增
  （Beck-Teboulle 2009，实测逐迭代非增）。
- **PSLL 面一致性**：内核 PSLL 与 array_synthesis.peak_sidelobe_level_db
  直调逐位同值（交叉面只读复用的恒等式，实测 diff=0.0）。
- **密度锥削对照**：固定 seed 可复现（同 seed 同索引）；预声明带
  irwl1_psll ≤ taper_psll + 2 dB（不保证更优，如实实测——包络设计例
  实测 −17.0 vs −8.0 dB，带内且更优 9 dB）。
- **包络口径残差地板（预声明）**：实值目标经复 LS 拟合存在符号折叠
  地板（理想场 = ±包络时，w_true 对 |AF| 目标残差非零，见内核 docstring
  诚实边界）——chebyshev −30 dB 包络、K=20/33 冒烟实测残差 −6.17 dB，
  预声明 ≤ −3 dB（含 3 dB 余量），**不做**权重回收承诺（相位检索超出
  BPDN 口径）。

θ→u 映射与 PSLL 均复用 array_synthesis（只读交叉面恒等式钉法同
test_tma_array）。外部裁判不适用（CS 阵列文献无数值表可逐位回收）；
闭式/算法法源见 core/sparse_array_cs.py docstring（Candès-Wakin-Boyd
2008 / Chen-Donoho-Saunders 2001 / Beck-Teboulle 2009）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import sparse_array_cs as sacs
from rfauto.core.array_synthesis import (
    array_factor,
    chebyshev_weights,
    direction_cosine,
    peak_sidelobe_level_db,
)
from rfauto.service import sparse_array_cs_service as svc

# ─── 共享夹具：合成回收场景（主判据）─────────────────────────────────────────

P_GRID = np.arange(13) * 0.5  # 候选位置 0..6λ，λ/2 栅格
TRUE_IDX = np.array([1, 3, 6, 9, 12])  # 真位置间距 1.0/1.5/1.5/1.5λ ≥ λ/2（预声明）
W_TRUE = np.array([1.0, 0.8 + 0.3j, 1.2 - 0.5j, 0.9 + 0.6j, 0.7 - 0.2j])
U_GRID = np.linspace(-1.0, 1.0, 401)


def _recovery_target():
    """复目标场 b = A·w_true（未归一）与其归一化期望权重。"""
    a_true = sacs.forward_matrix(P_GRID, U_GRID)[:, TRUE_IDX]
    b_raw = a_true @ W_TRUE
    scale = float(np.max(np.abs(b_raw)))
    return b_raw, W_TRUE / scale


def _run_recovery(**kwargs):
    b_raw, _ = _recovery_target()
    base = dict(u_values=U_GRID, lambda_reg=1e-2)
    base.update(kwargs)
    return sacs.synthesize_sparse_array(P_GRID, b_raw, 5, **base)


# ─── 1. 软阈值算子：任务书恒等式逐位钉 ────────────────────────────────────────


def test_soft_threshold_real_axis_identities():
    x = np.array([-3.0, -1.5, -0.5, 0.0, 0.5, 1.5, 3.0])
    t = 1.0
    out = sacs.soft_threshold(x, t)
    # |x| ≤ t → 0（逐位）
    assert np.all(out[np.abs(x) <= t] == 0.0)
    # |x| > t → x − t·sign(x)（逐位）
    expected = x[np.abs(x) > t] - t * np.sign(x[np.abs(x) > t])
    assert np.array_equal(out[np.abs(x) > t], expected)


def test_soft_threshold_complex_magnitude_phase():
    z = np.array([3.0 + 4.0j, 0.5 - 0.5j, -2.0 + 0.0j, 0.0 + 0.0j])
    t = 1.2
    out = sacs.soft_threshold(z, t)
    mag = np.abs(z)
    # |out| = max(0, |z| − t)（逐位，含 z=0 → 0 无 nan）
    assert np.allclose(np.abs(out), np.maximum(0.0, mag - t), rtol=0, atol=1e-15)
    # 相位保持（非零元）
    live = mag > t
    assert np.allclose(out[live] / np.abs(out[live]), z[live] / mag[live], atol=1e-15)
    assert out[~live & (mag <= t)].tolist() == [0j, 0j]


def test_soft_threshold_zero_threshold_identity_and_guards():
    z = np.array([0.0, 1.0 + 1.0j, -2.0])
    # t=0 → 逐位恒等（含 z=0）
    assert np.array_equal(sacs.soft_threshold(z, 0.0), z.astype(complex))
    # 逐元阈值数组广播：全 0 阈值 = 恒等
    assert np.array_equal(sacs.soft_threshold(z, np.zeros(3)), z.astype(complex))
    with pytest.raises(ValueError):
        sacs.soft_threshold(z, -0.1)
    with pytest.raises(ValueError):
        sacs.soft_threshold(z, np.nan)
    with pytest.raises(ValueError):
        sacs.soft_threshold(np.array([True, False]), 1.0)


# ─── 2. 前向算子：与 array_synthesis 同口径恒等式 ─────────────────────────────


def test_forward_matrix_matches_array_factor_identity():
    """等间距 p=n·d 时与 array_factor(normalize=False) 逐位同构（含扫描）。

    权重取实数：array_synthesis._validate_weights 收敛 float（复输入丢虚
    部，见 core/tma_array.py docstring 同款登记）——恒等式钉的是相位核，
    实权即足。
    """
    n, d = 8, 0.5
    p = np.arange(n) * d
    w = np.array([0.3, 1.0, 0.7, 0.2, 0.9, 0.4, 0.6, 0.1])
    u = np.linspace(-1.0, 1.0, 81)
    for u0 in (0.0, 0.3):
        a_mat = sacs.forward_matrix(p, u, scan_direction_cosine=u0)
        ref = array_factor(u, w, spacing_lambda=d, scan_direction_cosine=u0, normalize=False)
        assert np.allclose(a_mat @ w, ref, rtol=0, atol=1e-12)


def test_forward_matrix_unit_modulus_and_conjugate_rows():
    p = np.array([0.0, 0.5, 1.5, 3.0])
    u = np.linspace(-1.0, 1.0, 201)
    a_mat = sacs.forward_matrix(p, u)
    # 导向矢量模恒 1（纯相位字典）
    assert np.allclose(np.abs(a_mat), 1.0)
    # u 网格关于 u0=0 对称 → 行共轭配对：A[-m] == conj(A[m])
    assert np.allclose(a_mat[::-1], np.conj(a_mat), atol=1e-15)


def test_forward_matrix_input_guards():
    u = np.linspace(-1.0, 1.0, 21)
    with pytest.raises(ValueError):
        sacs.forward_matrix(np.array([0.5]), u)  # 候选 <2
    with pytest.raises(ValueError):
        sacs.forward_matrix(np.array([0.0, 0.5, 0.5]), u)  # 重复
    with pytest.raises(ValueError):
        sacs.forward_matrix(np.array([0.0, np.nan]), u)
    with pytest.raises(ValueError):
        sacs.forward_matrix(np.zeros((2, 2)), u)  # 非 1-D
    with pytest.raises(ValueError):
        sacs.forward_matrix(np.array([0.0, 0.5]), np.linspace(-1.5, 1.0, 5))  # u 超可见区
    with pytest.raises(ValueError):
        sacs.forward_matrix(np.array([0.0, 0.5]), u, scan_direction_cosine=1.5)


def test_u_values_from_theta_matches_direction_cosine():
    theta = np.linspace(0.0, 180.0, 19)
    u = sacs.u_values_from_theta(theta)
    assert np.allclose(u, direction_cosine(theta), atol=0.0)  # 只读复用的逐位恒等
    assert u[0] == pytest.approx(1.0) and u[-1] == pytest.approx(-1.0)  # z 轴 u=cosθ
    with pytest.raises(ValueError):
        sacs.u_values_from_theta(np.array([0.0, 90.0]))  # <3 点


def test_mutual_coherence_predeclared_condition():
    """预声明相干条件：λ/2 整数倍间距在均匀 u 网格上近正交（μ≈0）；过密 μ→1。"""
    u = np.linspace(-1.0, 1.0, 401)
    good = sacs.mutual_coherence(sacs.forward_matrix(P_GRID, u))
    dense = sacs.mutual_coherence(
        sacs.forward_matrix(np.arange(13) * 0.05, u)  # λ/20 栅格：栏相干
    )
    assert good < 0.05  # 实测 0.0025（间距 ≥λ/2 预声明条件的可观测面）
    assert dense > 0.9  # 实测 ~0.997（sinc(π/20) 量级）


# ─── 3. 加权 LASSO（ISTA）：独立路径对拍 + 目标单调 ────────────────────────────


def _dense_problem():
    rng = np.random.default_rng(7)
    p = np.arange(6) * 0.5
    u = np.linspace(-1.0, 1.0, 121)
    a_mat = sacs.forward_matrix(p, u)
    w_ls = rng.normal(size=6) + 1j * rng.normal(size=6)
    return a_mat, a_mat @ w_ls


def test_weighted_lasso_zero_lambda_matches_lstsq():
    """λ=0 退化纯最小二乘：ISTA（迭代路径）vs lstsq（直接求解）独立对拍。"""
    a_mat, b = _dense_problem()
    sol = sacs.weighted_lasso_ista(a_mat, b, np.ones(6), 0.0, max_iter=2000, tol=1e-12)
    ref = np.linalg.lstsq(a_mat, b, rcond=None)[0]
    rel = float(np.linalg.norm(sol["weights"] - ref) / np.linalg.norm(ref))
    assert rel <= 1e-9  # 实测 3e-15
    assert sol["converged"] is True


def test_weighted_lasso_objective_monotone_nonincreasing():
    """步长 1/L 的 ISTA 目标函数单调非增（Beck-Teboulle 2009 定理面）。"""
    a_mat, b = _dense_problem()
    for lam in (0.0, 1e-2, 0.5):
        sol = sacs.weighted_lasso_ista(a_mat, b, np.ones(6), lam, max_iter=300, tol=1e-14)
        hist = np.asarray(sol["objective_history"])
        slack = 1e-12 * max(1.0, abs(float(hist[0])))
        assert np.all(np.diff(hist) <= slack), f"λ={lam} 目标非单调"


def test_weighted_lasso_penalty_sparsifies_monotonic_direction():
    """正则越强非零越少（方向性）。

    字典先按列模归一（合法用例：A/√n_u 与 b/√n_u 同解）——未归一时
    L=σ_max²~1e4 量级，step·λ 阈值过小不产生稀疏化，λ 的可比性失真。
    """
    a_mat, b = _dense_problem()
    scale = np.sqrt(a_mat.shape[0])
    a_n, b_n = a_mat / scale, b / scale
    small = sacs.weighted_lasso_ista(a_n, b_n, np.ones(6), 1e-3, max_iter=5000, tol=1e-12)
    big = sacs.weighted_lasso_ista(a_n, b_n, np.ones(6), 0.5, max_iter=5000, tol=1e-12)
    nz_small = int(np.sum(np.abs(small["weights"]) > 1e-6))
    nz_big = int(np.sum(np.abs(big["weights"]) > 1e-6))
    assert nz_big < nz_small  # 正则越强非零越少（方向性）


def test_weighted_lasso_input_guards():
    a_mat, b = _dense_problem()
    with pytest.raises(ValueError):
        sacs.weighted_lasso_ista(a_mat, b, np.ones(5), 0.1)  # 权重长度不符
    with pytest.raises(ValueError):
        sacs.weighted_lasso_ista(a_mat, b, -np.ones(6), 0.1)  # 负罚权重
    with pytest.raises(ValueError):
        sacs.weighted_lasso_ista(a_mat, b, np.ones(6), -0.1)  # λ<0
    with pytest.raises(ValueError):
        sacs.weighted_lasso_ista(a_mat, b, np.ones(6), 0.1, tol=0.0)


# ─── 4. 主判据：合成回收（K=5）───────────────────────────────────────────────


def test_irwl1_synthetic_recovery_main_criterion():
    """主判据：命中 ≥4/5（实测 5/5）、权重幅值 rel ≤1e-6（实测 4.9e-16）。"""
    res = _run_recovery()
    hits = sum(1 for i in res.selected_indices if i in set(TRUE_IDX.tolist()))
    assert hits >= 4  # 任务书预声明下限
    assert hits == 5  # 本配置栅格对齐实测全命中
    # 权重回代：lstsq 去收缩后与归一化真值比对（命中格幅值 rel）
    assert list(res.selected_indices) == TRUE_IDX.tolist()
    _, expected = _recovery_target()
    rel = float(np.max(np.abs(res.weights - expected)) / np.max(np.abs(expected)))
    assert rel <= 1e-6  # 任务书预声明（实测 4.9e-16）
    assert res.mutual_coherence < 0.05  # 预声明相干条件实测面
    assert res.residual_db <= -200.0  # 实测 -309.7（复场精确回收）
    assert res.target_was_real is False  # 复场口径留痕


def test_irwl1_sparsity_trajectory_shape_and_direction():
    res = _run_recovery()
    traj = res.sparsity_trajectory
    assert len(traj) == res.outer_iterations
    assert all(isinstance(v, int) and v >= 0 for v in traj)
    assert traj[-1] <= traj[0]  # 重加权稀疏化方向
    assert traj[-1] <= 5  # 收敛支撑 ≯ K（实测 (5,5,5)）


def test_irwl1_convergence_flags():
    fast = _run_recovery(max_reweight_iter=1)
    assert fast.outer_iterations == 1
    assert fast.outer_converged is False  # 单轮无前轮可比
    # 收紧 tol：不动点（w 逐位相同 → rel=0）前不得提前收敛，
    # 迭代数不少于宽松 tol（固定输入下确定性内核单调成立）
    default = _run_recovery()
    tight = _run_recovery(tol=1e-12)
    assert tight.outer_iterations >= default.outer_iterations
    assert default.outer_converged is True
    assert default.outer_iterations < 15
    assert tight.outer_converged is True


def test_irwl1_epsilon_guards_and_effect():
    with pytest.raises(ValueError):
        _run_recovery(epsilon=0.0)
    with pytest.raises(ValueError):
        _run_recovery(epsilon=float("nan"))
    b_raw, _ = _recovery_target()
    sol = sacs.irwl1_reweight(
        sacs.forward_matrix(P_GRID, U_GRID), b_raw / np.max(np.abs(b_raw)),
        lambda_reg=1e-2, epsilon=1e-3,
    )
    assert set(sol) == {"weights", "sparsity_trajectory", "outer_iterations", "outer_converged"}
    assert np.all(np.isfinite(sol["weights"]))


# ─── 5. 全阵退化与度量恒等式 ──────────────────────────────────────────────────


def test_full_array_degenerate_residual_below_floor():
    """K=N_grid → BPDN→最小二乘 → 残差 ≤ −40 dB（预声明；实测 −307）。"""
    a_mat = sacs.forward_matrix(P_GRID, U_GRID)
    w_full = np.asarray(chebyshev_weights(13, -25.0), dtype=complex)
    b_full = a_mat @ w_full
    res = sacs.synthesize_sparse_array(P_GRID, b_full, 13, u_values=U_GRID)
    assert res.residual_db <= -40.0
    assert res.selected_indices == tuple(range(13))
    assert len(res.weights) == 13


def test_residual_db_metric_identity():
    """残差度量独立复算：20log10(‖|AF|−|b|‖₂/‖b‖₂) 与内核返回逐位同值。"""
    res = _run_recovery()
    recon = res.pattern_reconstructed
    tgt = res.pattern_target
    expected = 20.0 * np.log10(
        float(np.linalg.norm(np.abs(recon) - np.abs(tgt))) / float(np.linalg.norm(np.abs(tgt)))
    )
    assert res.residual_db == pytest.approx(expected, rel=1e-12)


def test_psll_consistency_with_array_synthesis():
    """内核 PSLL 与 array_synthesis.peak_sidelobe_level_db 直调逐位同值。"""
    res = _run_recovery()
    ref = peak_sidelobe_level_db(
        np.abs(res.pattern_reconstructed), res.u_values, main_lobe_direction_cosine=0.0
    )
    assert res.psll_db == float(ref)


# ─── 6. 包络口径 + 密度锥削对照面 ────────────────────────────────────────────

P33 = np.arange(33) * 0.5
U401 = np.linspace(-1.0, 1.0, 401)


def _envelope_design():
    """chebyshev −30 dB 全阵包络目标、K=20/33 的包络口径设计（固定输入）。"""
    taper = np.asarray(chebyshev_weights(33, -30.0), dtype=float)
    a_mat = sacs.forward_matrix(P33, U401)
    envelope = np.abs(a_mat @ taper)
    return sacs.synthesize_sparse_array(P33, envelope, 20, u_values=U401, lambda_reg=1e-2)


def test_envelope_design_psll_and_target_reference():
    res = _envelope_design()
    assert res.target_was_real is True  # 实值目标 → 包络口径留痕
    assert res.target_psll_db == pytest.approx(-30.0, abs=1e-3)  # chebyshev 等副瓣
    assert np.isfinite(res.psll_db) and res.psll_db < 0.0  # 实测 −17.0
    assert res.residual_db <= -3.0  # 实测 −6.17（符号折叠地板内，见文件头预声明）


def test_envelope_design_taper_band_verdict():
    """预声明带：irwl1_psll ≤ taper_psll + 2 dB（不保证更优，如实实测）。"""
    res = _envelope_design()
    taper = res.taper
    assert len(taper.taper_indices) == 20
    assert taper.band_db == sacs.PSLL_BAND_DB == 2.0
    # 本例实测：irwl1 −17.0 dB vs 锥削参考 −8.0 dB → 带内且更优 ~9 dB
    assert taper.within_band is True
    assert taper.within_band == (taper.irwl1_psll_db <= taper.taper_psll_db + taper.band_db)


def test_density_taper_reference_deterministic():
    i1 = sacs.density_taper_indices(33, 20, seed=20260927)
    i2 = sacs.density_taper_indices(33, 20, seed=20260927)
    i3 = sacs.density_taper_indices(33, 20, seed=42)
    assert np.array_equal(i1, i2)  # 固定 seed 可复现
    assert not np.array_equal(i1, i3)  # 换 seed 换抽稀实现
    assert np.array_equal(i1, np.sort(i1))  # 保序
    assert sacs.density_taper_indices(10, 4, seed=0).size == 4  # seed=0 合法
    with pytest.raises(ValueError):
        sacs.density_taper_indices(10, 11)  # k>n
    with pytest.raises(ValueError):
        sacs.density_taper_indices(10, 4, seed=-1)


# ─── 7. 顶层入参守卫与 to_dict ───────────────────────────────────────────────


def test_top_level_input_guards():
    b_raw, _ = _recovery_target()
    good_u = dict(u_values=U_GRID)
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(P_GRID, b_raw, 0, **good_u)  # K<1
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(P_GRID, b_raw, 14, **good_u)  # K>N_grid
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(P_GRID, b_raw, True, **good_u)  # bool 拒收
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(P_GRID, b_raw, 5, lambda_reg=-1e-3, **good_u)
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(P_GRID, b_raw, 5, lambda_reg=True, **good_u)
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(P_GRID, np.array([]), 5, **good_u)  # 空目标
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(P_GRID, np.zeros(U_GRID.size), 5, **good_u)  # 全零目标
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(P_GRID, b_raw[:-1], 5, **good_u)  # 长度不符
    bad = b_raw.astype(complex)
    bad[7] = np.nan
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(P_GRID, bad, 5, **good_u)  # 非有限目标
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(  # u 与 θ 同给
            P_GRID, b_raw, 5, u_values=U_GRID, theta_deg=np.linspace(0, 180, 19)
        )
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(P_GRID, b_raw, 5)  # 都不给
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(np.array([0.0, 0.5, 0.25, 0.5]), b_raw[:4], 2, u_values=U_GRID[:4])  # 重复位置


def test_theta_path_and_scan_steer():
    """θ 网格路径 + 扫描 u0=0.3：同一几何下目标随前向算子平移仍可回收。"""
    theta = np.linspace(0.0, 180.0, 181)
    u0 = 0.3
    p = P_GRID
    a_mat = sacs.forward_matrix(p, sacs.u_values_from_theta(theta), scan_direction_cosine=u0)
    b_raw = a_mat[:, TRUE_IDX] @ W_TRUE
    res = sacs.synthesize_sparse_array(
        p, b_raw, 5, theta_deg=theta, scan_direction_cosine=u0, lambda_reg=1e-2
    )
    hits = sum(1 for i in res.selected_indices if i in set(TRUE_IDX.tolist()))
    assert hits == 5
    assert res.scan_direction_cosine == pytest.approx(0.3)
    with pytest.raises(ValueError):
        sacs.synthesize_sparse_array(p, b_raw, 5, theta_deg=theta, scan_direction_cosine=2.0)


def test_to_dict_json_roundtrip():
    res = _envelope_design()
    payload = res.to_dict()
    text = json.dumps(payload)  # 复数→[re,im]、非有限→None 后必须可序列化
    back = json.loads(text)
    assert back["k_sparse"] == 20 and back["n_grid"] == 33
    assert len(back["selected_indices"]) == 20
    assert len(back["weights"]) == 20 and all(len(w) == 2 for w in back["weights"])
    assert all(isinstance(v, int) for v in back["sparsity_trajectory"])
    assert back["taper"]["within_band"] is True
    assert isinstance(back["outer_converged"], bool)
    # 完美回收路径的 −inf 残差在 JSON 面转 None（0.0 合法，判缺失 is not None）
    res_exact = _run_recovery()
    d_exact = res_exact.to_dict()
    json.dumps(d_exact)
    assert d_exact["residual_db"] is None or isinstance(d_exact["residual_db"], float)


# ─── 8. service 薄面（JSON 信封，硬限 4）──────────────────────────────────────


def test_service_ok_chebyshev_envelope():
    req = {
        "n_grid": 33,
        "spacing_lambda": 0.5,
        "k_sparse": 20,
        "u_grid": {"start": -1.0, "stop": 1.0, "step": 0.005},
        "target": {"kind": "chebyshev", "sidelobe_level_db": -30.0},
    }
    out = svc.sparse_array_cs_service(req)
    assert out["ok"] is True
    assert out["schema_version"] == svc.SPARSE_ARRAY_CS_SERVICE_SCHEMA_VERSION
    result = out["result"]
    assert result["k_sparse"] == 20 and len(result["selected_indices"]) == 20
    assert result["taper"]["within_band"] is True
    json.dumps(out)  # 信封可序列化


def test_service_ok_explicit_complex_target():
    b_raw, _ = _recovery_target()
    req = {
        "positions_lambda": P_GRID.tolist(),
        "k_sparse": 5,
        "u_grid": {"values": U_GRID.tolist()},
        "target": {"kind": "explicit", "values": [[float(v.real), float(v.imag)] for v in b_raw]},
        "lambda_reg": 1e-2,
    }
    out = svc.sparse_array_cs_service(req)
    assert out["ok"] is True
    assert out["result"]["selected_indices"] == TRUE_IDX.tolist()


def test_service_error_envelope_no_raise():
    out = svc.sparse_array_cs_service({"n_grid": 13, "k_sparse": 99})  # k>n → ok=False
    assert out["ok"] is False
    assert isinstance(out["error"], str) and out["error"]
    assert svc.sparse_array_cs_service("not-a-dict")["ok"] is False
    assert svc.sparse_array_cs_service({"n_grid": 13, "k_sparse": 5})["ok"] is False  # 缺 target
