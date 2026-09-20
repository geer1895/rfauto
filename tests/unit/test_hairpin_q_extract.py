"""hairpin_q_extract 纯函数离线单测（WP2.3 收口 B1；#212 先离线后真机，零真机）。

裁判 = 合成 Lorentz 曲线的闭式回代（#118 独立来源：由 (Q_u, Q_e) 正向构造
单极点对称二端口 |S21(f)|，反提 Q_L/Q_u/β_tot/Q_e 须回到构造值 ≤1%）：
  1/Q_L = 1/Q_u + 2/Q_e、|S21(f0)| = 2β/(1+2β)（β=Q_u/Q_e）、
  |S21(f)| = S0/√(1+(2Q_L δ)²)，δ=(f−f0)/f0。
网格取引擎同款（渲染脚本固定 401 点，2.0-3.2GHz → 3MHz 步）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_hairpin_q_extract",
    str(Path(__file__).resolve().parents[2] / "scripts" / "hairpin_q_extract.py"))
assert _SPEC is not None and _SPEC.loader is not None
qx = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(qx)

F0_HZ = 2.59e9                                   # 真机量级（+3.6% 于设计 2.5）
GRID = np.linspace(2.0e9, 3.2e9, 401)            # 引擎同款 401 点


def _two_port_curve(q_u: float, q_e: float, f0_hz: float = F0_HZ,
                    freq: np.ndarray = GRID) -> tuple[np.ndarray, float, float]:
    """(Q_u, Q_e) → |S21(f)| 合成曲线 + (Q_L, S0) 闭式（对称双端口）。"""
    beta = q_u / q_e
    q_l = 1.0 / (1.0 / q_u + 2.0 / q_e)
    s0 = 2.0 * beta / (1.0 + 2.0 * beta)
    return qx.synthesize_lorentz(freq, f0_hz, q_l, s0), q_l, s0


@pytest.mark.parametrize("q_l,s0", [(2.5, 0.99), (12.0, 0.95), (30.0, 0.8),
                                    (100.0, 0.3)])
def test_lorentz_inverse_fit_recovers_parameters(q_l, s0):
    mag = qx.synthesize_lorentz(GRID, F0_HZ, q_l, s0)
    fit = qx.lorentz_inverse_fit(GRID, mag)
    assert fit["q_loaded"] == pytest.approx(q_l, rel=1e-2)
    assert fit["f0_hz"] == pytest.approx(F0_HZ, rel=1e-3)
    assert fit["s21_peak"] == pytest.approx(s0, rel=1e-2)
    assert fit["n_points"] >= 5
    # 精确单极点 ⇒ |S21|⁻² 恰为抛物线：线性最小二乘应到机器精度量级
    assert fit["q_loaded"] == pytest.approx(q_l, rel=1e-8)


def test_halfpower_bandwidth_matches_fit_when_inside_window():
    mag, q_l, _ = _two_port_curve(270.0, 33.0)     # Q_L≈15.6，Δf≈166MHz 落窗内
    hp = qx.bandwidth_3db(GRID, mag)
    assert hp["bw_hz"] is not None
    assert F0_HZ / hp["bw_hz"] == pytest.approx(q_l, rel=1e-2)
    assert hp["f0_hz"] == pytest.approx(F0_HZ, abs=1.5 * (GRID[1] - GRID[0]))
    # 窗被截断（Q_e=2.5：Q_L≈1.24，Δf≈2.1GHz 超出 1.2GHz 窗）：半功率法如实 None，
    # Lorentz 反演（窗内抛物线）仍成立
    mag_wide, q_l_wide, _ = _two_port_curve(270.0, 2.5)
    hp_wide = qx.bandwidth_3db(GRID, mag_wide)
    assert hp_wide["bw_hz"] is None
    assert qx.lorentz_inverse_fit(GRID, mag_wide)["q_loaded"] == pytest.approx(
        q_l_wide, rel=1e-2)
    # τ=0.30 量级（Q_e=4.55：Δf≈1.15GHz，半功率点 2.02/3.16GHz 恰在窗内）：两法一致
    mag_30, q_l_30, _ = _two_port_curve(270.0, 4.55)
    hp_30 = qx.bandwidth_3db(GRID, mag_30)
    assert hp_30["bw_hz"] is not None
    assert F0_HZ / hp_30["bw_hz"] == pytest.approx(q_l_30, rel=1e-2)


@pytest.mark.parametrize("q_e", [4.55, 8.67, 16.45, 33.0])   # τ∈{0.30,0.36,0.40,0.43} 闭式量级
def test_q_metrics_closed_form_backsubstitution(q_e):
    """(Q_u=270, Q_e) 正向构造 → 反提 Q_u/Q_e/β_tot 回代 ≤1%（介质限 1/tanδ 量级）。"""
    q_u = 270.0
    mag, q_l, s0 = _two_port_curve(q_u, q_e)
    qm = qx.q_metrics(GRID, mag)
    assert qm["q_loaded"] == pytest.approx(q_l, rel=1e-2)
    assert qm["s21_peak"] == pytest.approx(s0, rel=1e-2)
    assert qm["q_unloaded"] == pytest.approx(q_u, rel=1e-2)
    assert qm["qe_per_port"] == pytest.approx(q_e, rel=1e-2)
    assert qm["beta_tot"] == pytest.approx(2.0 * q_u / q_e, rel=1e-2)
    assert qm["f0_ghz"] == pytest.approx(F0_HZ / 1e9, rel=1e-3)
    assert qm["method"] == "curvature_0.5dB"
    assert qm["curvature_window_rel_diff"] <= 1e-6        # 精确单极点：两窗曲率一致
    if qm["q_loaded_halfpower"] is not None:
        assert qm["q_loaded_halfpower"] == pytest.approx(q_l, rel=1e-2)


def test_q_metrics_low_q_unloaded_regime():
    """真机四轮量级（复合 Q≈22-36）：Q_u=30 的合成曲线同样回代 ≤1%。"""
    mag, _, _ = _two_port_curve(30.0, 16.45)
    qm = qx.q_metrics(GRID, mag)
    assert qm["q_unloaded"] == pytest.approx(30.0, rel=1e-2)
    assert qm["qe_per_port"] == pytest.approx(16.45, rel=1e-2)


def test_lorentz_fit_rejects_nonresonant_shape():
    with pytest.raises(ValueError):
        qx.lorentz_inverse_fit(GRID, np.full(GRID.size, 0.5))       # 平台：开口 0
    with pytest.raises(ValueError):
        qx.lorentz_inverse_fit(GRID[:3], np.array([0.1, 0.5, 0.1]))  # <5 点


def test_qe_correction_fit_and_tau_solve():
    """c(τ) 线性拟合 + brentq 重解 τ*：闭式回代到 1e-8；c≡1 时 τ* 回到闭式 τ。"""
    from rfauto.core.coupled_microstrip import (
        hairpin_qe_from_tap_frac,
        hairpin_tap_frac_from_qe,
    )

    taus = [0.30, 0.36, 0.40, 0.43]
    qe_cl = [hairpin_qe_from_tap_frac(t) for t in taus]
    c0, c1 = 1.10, -0.20
    qe_em = [(c0 + c1 * t) * q for t, q in zip(taus, qe_cl, strict=True)]
    fit = qx.qe_correction_fit(taus, qe_em, qe_cl)
    assert fit["c0"] == pytest.approx(c0, abs=1e-9)
    assert fit["c1"] == pytest.approx(c1, abs=1e-9)
    assert fit["max_abs_resid"] <= 1e-9
    target = 17.068949210832677                    # C13 N=3/RL20/FBW0.05 Q_e 量级
    tau_star = qx.solve_tap_frac_for_qe(target, fit["c0"], fit["c1"])
    assert (c0 + c1 * tau_star) * hairpin_qe_from_tap_frac(tau_star) == \
        pytest.approx(target, rel=1e-8)
    assert 0.05 < tau_star < 0.44
    # 无修正（c≡1）退化为闭式反解
    tau_id = qx.solve_tap_frac_for_qe(target, 1.0, 0.0)
    assert tau_id == pytest.approx(hairpin_tap_frac_from_qe(target), abs=1e-7)
    # 单点退化：常数修正
    one = qx.qe_correction_fit([0.40], [qe_cl[2] * 1.05], [qe_cl[2]])
    assert one["c0"] == pytest.approx(1.05, rel=1e-12) and one["c1"] == 0.0


def test_peak_refine_recovers_between_grid_peak():
    """S0 只信局部：峰落在两格之间时 3 点抛物线补回量化（Q_u=Q_L/(1−S0) 对 S0 极敏感）。"""
    f0 = F0_HZ + 1.3e6                              # 3MHz 步网格的格间峰
    mag = qx.synthesize_lorentz(GRID, f0, 30.0, 0.8)
    fp, mp = qx.peak_refine(GRID, mag)
    assert fp == pytest.approx(f0, abs=0.2e6)
    assert mp == pytest.approx(0.8, rel=1e-4)
    assert mp >= mag.max()                           # 精化峰不低于网格峰
    # 端点峰（无双侧邻点）退化为网格值
    fe, me = qx.peak_refine(GRID[:5], np.array([0.9, 0.8, 0.7, 0.6, 0.5]))
    assert fe == GRID[0] and me == 0.9


def test_point_quality_gate():
    """c(τ) 入选门：两窗曲率 Q_L 稳定（≤10%）且 FWHM ≤ 扫频窗之半；强过耦合排除。"""
    mag_ok, _, _ = _two_port_curve(270.0, 33.0)          # Q_L≈15.6，FWHM≈166MHz
    qm_ok = qx.q_metrics(GRID, mag_ok)
    assert qx.point_quality_ok(qm_ok, window_ghz=(2.0, 3.2))
    mag_wide, _, _ = _two_port_curve(270.0, 2.5)         # Q_L≈1.24，FWHM≈2.1GHz > 0.6
    qm_wide = qx.q_metrics(GRID, mag_wide)
    assert not qx.point_quality_ok(qm_wide, window_ghz=(2.0, 3.2))
    assert qx.point_quality_ok(qm_wide)                  # 不给窗则仅看曲率稳定/点数
    assert not qx.point_quality_ok({"curvature_window_rel_diff": 0.3, "fit_points": 40,
                                    "bw3db_ghz": 0.1}, window_ghz=(2.0, 3.2))
    assert not qx.point_quality_ok({"curvature_window_rel_diff": 0.0, "fit_points": 5,
                                    "bw3db_ghz": 0.1}, window_ghz=(2.0, 3.2))


def test_lossy_coupled_model_gauge_invariant_and_fit_recovers():
    """有耗 N 极耦合模型：① 复对角损耗项保持规范不变（fbw_g 0.05/0.10 ≤1e-6dB）；
    ② 合成 N=3 响应（f0/k/Q_e/Q_u 已知）全形状拟合回代 ≤1%（B2 反提 k_EM/Q_e_EM 口径）。"""
    f = np.linspace(2.2e9, 3.0e9, 401)
    f0, k, qe, qu = 2.59e9, 0.045, 19.0, 220.0
    a = qx.coupled_model_s21_db(f, f0, k, qe, 3, qu, fbw_g=0.05)
    b = qx.coupled_model_s21_db(f, f0, k, qe, 3, qu, fbw_g=0.10)
    assert float(np.max(np.abs(a - b))) <= 1e-6                 # dB 6 位量化底
    assert a.max() < 0.0                                       # 有耗：峰 <0dB
    lossless = qx.coupled_model_s21_db(f, f0, k, qe, 3, float("inf"))
    assert lossless.max() > a.max()
    mag = 10.0 ** (a / 20.0)
    _, a11 = qx.coupled_model_s_db(f, f0, k, qe, 3, qu)
    fit = qx.fit_coupled_model(f, mag, order=3, q_u=qu, k0=0.0515, qe0=17.07,
                               s11_mag=10.0 ** (a11 / 20.0))
    assert fit["uses_s11"]
    assert fit["f0_hz"] == pytest.approx(f0, rel=1e-4)
    assert fit["k"] == pytest.approx(k, rel=1e-2)
    assert fit["qe"] == pytest.approx(qe, rel=1e-2)
    assert fit["rms_db"] <= 1e-3
    assert fit["k_ratio_vs_init"] == pytest.approx(k / 0.0515, rel=1e-2)


def test_pole_background_fit_recovers_pole_with_coherent_background():
    """复 S21 = A/(1+2jQ_Lδ) + B 的极点+背景分离（诊断口径）：极点 f0/Q_L 与 |A|/|B|
    回代 ≤1%（直通路径相干背景使 |S21| 峰偏离极点，宽窗幅值法失效的场景）。"""
    q_l, f0 = 9.0, F0_HZ
    a = 0.9 * np.exp(1j * 0.7)
    b = 0.35 * np.exp(-1j * 2.1)
    s21 = a / (1.0 + 2j * q_l * (GRID - f0) / f0) + b
    pb = qx.pole_background_fit(GRID, s21)
    assert pb["f0_hz"] == pytest.approx(f0, rel=1e-3)
    assert pb["q_loaded"] == pytest.approx(q_l, rel=1e-2)
    assert pb["a_mag"] == pytest.approx(abs(a), rel=1e-2)
    assert pb["b_mag"] == pytest.approx(abs(b), rel=1e-2)
    assert pb["rel_residual"] <= 1e-6
    qm = qx.q_metrics(GRID, np.abs(s21), s21_complex=s21)
    assert qm["pole_background"]["q_loaded"] == pytest.approx(q_l, rel=1e-2)
    assert qm["method"] == "curvature_0.5dB"


def test_synthesize_lorentz_halfpower_definition():
    """合成曲线自洽：f0±f0/(2Q_L) 处恰为峰的 1/√2（Δf_3dB=f0/Q_L 定义）。"""
    q_l = 12.0
    mag = qx.synthesize_lorentz(
        np.array([F0_HZ, F0_HZ * (1 + 0.5 / q_l), F0_HZ * (1 - 0.5 / q_l)]),
        F0_HZ, q_l, 0.9)
    assert mag[0] == pytest.approx(0.9, rel=1e-12)
    assert mag[1] == pytest.approx(0.9 / np.sqrt(2.0), rel=1e-12)
    assert mag[2] == pytest.approx(0.9 / np.sqrt(2.0), rel=1e-12)
