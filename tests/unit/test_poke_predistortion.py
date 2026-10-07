"""M-2.2 poke 预失真内核单测（研究扩充 M-2 判据②口径）。

裁判口径（#118 双路径/独立来源，不自证）：
- 回收恒等式：λ=0 无噪时 w 与 ``np.linalg.solve(H_true, e)`` 独立直解逐位
  （rel 1e-9）——独立代数路径，非实现自证；
- Tikhonov λ 单调性：SVD 域解析式 |w_i(λ)| = σ_i|u_i^H e|/(σ_i²+λ) 单调
  不增、残差 |r_i(λ)| 单调不减——数组断言（弱单调 + 浮点松弛 1e-9 相对）；
- SVD 谱正交恒等式 U^H U = I（rel 1e-9）+ 奇异值与 np.linalg.svd 互证；
- 病态例 Hilbert 8×8：cond ≈ 1.5e10（独立数值报告）与可矫正维数 == 7 < 8
  逐位（floor=1e-6）。
- 方向图改善判据是物理演示（确定性种子），不构成解析恒等式。
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import poke_predistortion as pp
from rfauto.core.array_synthesis import chebyshev_weights

_SEED = 20260927


def _coupled_h(n: int, eps: float, seed: int = _SEED) -> np.ndarray:
    """参数化互耦合成 H_true = I + ε·C（C 零对角复耦合，种子确定）。"""
    rng = np.random.default_rng(seed)
    c = rng.uniform(-1.0, 1.0, size=(n, n)) + 1j * rng.uniform(-1.0, 1.0, size=(n, n))
    np.fill_diagonal(c, 0.0)
    return np.eye(n, dtype=complex) + eps * c


def _hilbert(n: int) -> np.ndarray:
    idx = np.arange(n, dtype=float)
    return 1.0 / (idx[:, None] + idx[None, :] + 1.0)


# ─── 1. 合成注入回收（主判据）───────────────────────────────────────────────


def test_roundtrip_recovery_identity_lam0():
    # 判据⑤：已知 H_true + 已知目标 → w 与 solve(H_true, e) 直解逐位（rel 1e-9）
    h_true = _coupled_h(8, 0.25)
    rng = np.random.default_rng(3)
    e_target = rng.uniform(-1.0, 1.0, 8) + 1j * rng.uniform(-1.0, 1.0, 8)
    out = pp.predistortion_weights(h_true, e_target, reg_lambda=0.0)
    reference = np.linalg.solve(h_true, e_target)
    assert np.allclose(out["weights"], reference, rtol=1e-9, atol=1e-12 * np.max(np.abs(reference)))


def test_roundtrip_effective_response_matches_target():
    # 矫正后有效响应 H@w == e_target（λ=0 满秩方阵，残差在 1e-9 量级以下）
    h_true = _coupled_h(6, 0.3, seed=11)
    e_target = chebyshev_weights(6, -25.0).astype(complex)
    out = pp.predistortion_weights(h_true, e_target, reg_lambda=0.0)
    assert np.allclose(out["effective"], e_target, rtol=1e-9, atol=1e-12)
    assert out["residual_rel"] < 1e-9


def test_identity_matrix_is_fixed_point():
    # H=I（零互耦）时 w == e_target 逐位（预失真退化为恒等）
    e_target = np.array([1.0, 0.5, -0.3, 0.2j], dtype=complex)
    out = pp.predistortion_weights(np.eye(4, dtype=complex), e_target, reg_lambda=0.0)
    assert np.allclose(out["weights"], e_target, rtol=1e-12, atol=0.0)
    assert out["residual_rel"] < 1e-14


# ─── 2. Tikhonov λ 分支：公式与单调性 ───────────────────────────────────────


def test_tikhonov_matches_direct_normal_equations():
    # λ>0 公式回收：w(λ) 与直解 solve(H^H H + λI, H^H e) 独立对照
    rng = np.random.default_rng(5)
    h = rng.standard_normal((6, 6)) + 1j * rng.standard_normal((6, 6))
    e = rng.standard_normal(6) + 1j * rng.standard_normal(6)
    lam = 1e-2
    out = pp.predistortion_weights(h, e, reg_lambda=lam)
    gram = h.conj().T @ h
    reference = np.linalg.solve(gram + lam * np.eye(6), h.conj().T @ e)
    assert np.allclose(out["weights"], reference, rtol=1e-10, atol=1e-13)


def test_tikhonov_lambda_monotonicity():
    # 判据：λ↑ → ‖w‖ 单调不增 且 相对残差单调不减（SVD 域解析单调性，弱单调）
    h_true = _coupled_h(8, 0.4)
    e_target = chebyshev_weights(8, -25.0).astype(complex)
    lambdas = np.geomspace(1e-8, 1e2, 25)
    sweep = pp.tikhonov_sweep(h_true, e_target, lambdas)
    norms = sweep["weights_norm"]
    rels = sweep["residual_rel"]
    assert np.all(np.diff(norms) <= 1e-9 * norms[0])
    assert np.all(np.diff(rels) >= -1e-9 * rels[0])
    # 单调非平凡：大 λ 端权重确实被压缩
    assert norms[-1] < norms[0]


def test_tikhonov_large_lambda_kills_weights():
    # λ → ∞ 极限：w → 0、残差 → 全目标（rel → 1）
    h_true = _coupled_h(6, 0.3, seed=13)
    rng = np.random.default_rng(17)
    e_target = rng.uniform(0.2, 1.0, 6) + 1j * rng.uniform(0.2, 1.0, 6)
    out = pp.predistortion_weights(h_true, e_target, reg_lambda=1e14)
    assert out["weights_norm"] < 1e-6 * float(np.linalg.norm(e_target))
    assert abs(out["residual_rel"] - 1.0) < 1e-6


def test_tikhonov_zero_lambda_equals_pinv():
    # λ=0 分支 == SVD 最小范数伪逆（同路径定义恒等，逐位量级 1e-12）
    h_true = _coupled_h(5, 0.2, seed=19)
    rng = np.random.default_rng(23)
    e_target = rng.uniform(-1.0, 1.0, 5) + 1j * rng.uniform(-1.0, 1.0, 5)
    out = pp.predistortion_weights(h_true, e_target, reg_lambda=0.0)
    reference = np.linalg.pinv(h_true) @ e_target
    assert np.allclose(out["weights"], reference, rtol=1e-9, atol=1e-13)


def test_tikhonov_sweep_shapes_and_validation():
    h_true = _coupled_h(4, 0.2, seed=29)
    e_target = chebyshev_weights(4, -20.0).astype(complex)
    lambdas = np.array([0.0, 1e-3, 1e-1, 10.0])
    sweep = pp.tikhonov_sweep(h_true, e_target, lambdas)
    assert sweep["lambdas"].shape == (4,)
    assert np.allclose(sweep["lambdas"], lambdas)
    assert sweep["weights_norm"].shape == (4,)
    assert sweep["residual_rel"].shape == (4,)
    # 负 λ 序列 / NaN / bool 拒收
    with pytest.raises(ValueError, match="负值"):
        pp.tikhonov_sweep(h_true, e_target, np.array([1e-3, -1.0]))
    with pytest.raises(ValueError, match="NaN/Inf"):
        pp.tikhonov_sweep(h_true, e_target, np.array([1e-3, np.nan]))
    with pytest.raises(ValueError, match="bool"):
        pp.tikhonov_sweep(h_true, e_target, np.array([True, False]))


# ─── 3. SVD 谱面：正交恒等式 / dB 谱 / cond / 可矫正维数 ────────────────────


def test_svd_unitarity_and_spectrum_crosscheck():
    # 判据：U^H U = I（rel 1e-9）；谱面奇异值与 np.linalg.svd 独立互证
    rng = np.random.default_rng(7)
    h = rng.standard_normal((6, 6)) + 1j * rng.standard_normal((6, 6))
    u, s, _vh = np.linalg.svd(h)
    assert np.allclose(u.conj().T @ u, np.eye(6), rtol=1e-9, atol=1e-12)
    spec = pp.interaction_spectrum(h)
    assert np.allclose(spec.singular_values, s, rtol=1e-12, atol=0.0)
    assert spec.n_resp == 6 and spec.n_exc == 6


def test_spectrum_db_first_entry_zero_and_matches_manual():
    h_true = _coupled_h(8, 0.35, seed=31)
    spec = pp.interaction_spectrum(h_true)
    assert spec.singular_values_db[0] == 0.0  # 逐位：σ_max 归一首元恒 0
    manual = 20.0 * np.log10(spec.singular_values / spec.singular_values[0])
    assert np.allclose(spec.singular_values_db, manual, rtol=1e-12, atol=1e-12)


def test_spectrum_condition_number_diagonal_exact():
    # 对角谱：cond = σ_max/σ_min 精确回收；可矫正维数严格 > 阈值逐位
    h = np.diag([1.0, 0.1, 0.01, 0.001])
    spec = pp.interaction_spectrum(h, sigma_floor=0.05)
    assert spec.condition_number == pytest.approx(1000.0, rel=1e-12)
    assert spec.correctable_dims == 2  # σ > 0.05·σ_max：{1, 0.1} 恰 2 个
    # 缺省 floor=1e-3：σ_min=0.001 不满足严格 >，恰被排除（可矫正 = 3 维）
    spec_default = pp.interaction_spectrum(h)
    assert spec_default.correctable_dims == 3


def test_spectrum_hilbert8_ill_conditioned():
    # 判据：Hilbert 8×8 病态例——cond 报告 >1e10、可矫正维数 < 8 逐位。
    # 奇异值独立实测（numpy SVD，2026-09-27）：σ₅=5.4369e-5 > 1e-6·σ₁=1.6959e-6
    # > σ₆=1.2943e-6 → floor=1e-6 下恰 5 维（严格 >，阈值恰等不入）
    spec = pp.interaction_spectrum(_hilbert(8), sigma_floor=1e-6)
    assert spec.condition_number > 1e10
    assert spec.correctable_dims == 5
    assert spec.correctable_dims < 8  # 判据逐位：可矫正子空间不满秩
    sv = spec.singular_values
    assert sv[4] > spec.sigma_floor * sv[0] > sv[5]


def test_spectrum_cond_guard_raises():
    with pytest.raises(ValueError, match="病态"):
        pp.interaction_spectrum(_hilbert(8), cond_max=1e6)
    # 守卫不超限时不抛（宽守卫放行良态矩阵）
    pp.interaction_spectrum(_coupled_h(6, 0.2, seed=37), cond_max=1e3)
    with pytest.raises(ValueError, match="cond_max"):
        pp.interaction_spectrum(_coupled_h(4, 0.2, seed=41), cond_max=0.0)


def test_spectrum_sigma_floor_validation():
    h = _coupled_h(4, 0.2, seed=43)
    with pytest.raises(ValueError, match="sigma_floor"):
        pp.interaction_spectrum(h, sigma_floor=0.0)
    with pytest.raises(ValueError, match="sigma_floor"):
        pp.interaction_spectrum(h, sigma_floor=-0.5)
    with pytest.raises(ValueError, match="sigma_floor"):
        pp.interaction_spectrum(h, sigma_floor=1.5)
    # floor=1.0 合法：严格 > 口径下 σ_max 本身不满足 σ > 1.0·σ_max → 0 维
    #（判据口径 σ>σ_floor·σ_max 的自洽边界，如实为 0 不改成 ≥）
    spec = pp.interaction_spectrum(h, sigma_floor=1.0)
    assert spec.correctable_dims == 0


# ─── 4. 边界与拒收（非方阵 / 零矩阵 / λ<0 / NaN/Inf / bool）─────────────────


def test_nonsquare_rectangular_pseudoinverse():
    # N×M 激励/响应异维（3 响应 × 5 激励）：伪逆口径，一致目标残差 ~0
    rng = np.random.default_rng(47)
    h = rng.standard_normal((3, 5)) + 1j * rng.standard_normal((3, 5))
    x0 = rng.standard_normal(5) + 1j * rng.standard_normal(5)
    e_consistent = h @ x0
    out = pp.predistortion_weights(h, e_consistent, reg_lambda=0.0)
    assert out["weights"].shape == (5,)
    assert out["effective"].shape == (3,)
    assert out["residual_rel"] < 1e-9
    spec = pp.interaction_spectrum(h)
    assert spec.singular_values.shape == (3,)  # 经济型 SVD：min(n_resp, n_exc)
    assert spec.n_resp == 3 and spec.n_exc == 5


def test_zero_matrix_rejected_everywhere():
    zeros = np.zeros((3, 3), dtype=complex)
    e = np.ones(3, dtype=complex)
    with pytest.raises(ValueError, match="零矩阵"):
        pp.interaction_spectrum(zeros)
    with pytest.raises(ValueError, match="零矩阵"):
        pp.predistortion_weights(zeros, e)
    with pytest.raises(ValueError, match="零矩阵"):
        pp.beam_predistortion_report(zeros, e)


def test_negative_and_nonfinite_lambda_rejected():
    h = _coupled_h(4, 0.2, seed=53)
    e = chebyshev_weights(4, -20.0).astype(complex)
    with pytest.raises(ValueError, match="reg_lambda"):
        pp.predistortion_weights(h, e, reg_lambda=-1e-9)
    with pytest.raises(ValueError, match="有限"):
        pp.predistortion_weights(h, e, reg_lambda=float("inf"))
    # λ=0.0 是合法显式分支
    out = pp.predistortion_weights(h, e, reg_lambda=0.0)
    assert out["reg_lambda"] == 0.0


def test_invalid_inputs_rejected():
    h = _coupled_h(4, 0.2, seed=59)
    h_nan = h.copy()
    h_nan[1, 2] = np.nan
    with pytest.raises(ValueError, match="NaN/Inf"):
        pp.interaction_spectrum(h_nan)
    with pytest.raises(ValueError, match="bool"):
        pp.interaction_spectrum(np.eye(3, dtype=bool))
    with pytest.raises(ValueError, match="二维"):
        pp.interaction_spectrum(np.ones((2, 2, 2), dtype=complex))
    with pytest.raises(ValueError, match="NaN/Inf"):
        pp.predistortion_weights(h, np.array([1.0, np.inf, 1.0, 1.0]))
    with pytest.raises(ValueError, match="bool"):
        pp.predistortion_weights(h, np.array([True, False, True, True]))
    with pytest.raises(ValueError, match="一维"):
        pp.predistortion_weights(h, np.ones((4, 1), dtype=complex))
    with pytest.raises(ValueError, match="零向量"):
        pp.predistortion_weights(h, np.zeros(4, dtype=complex))
    with pytest.raises(ValueError, match="不一致"):
        pp.predistortion_weights(h, np.ones(5, dtype=complex))


# ─── 5. 波束验证面（判据②）：矫正前 vs 矩阵矫正后 ──────────────────────────


def _beam_case() -> tuple[np.ndarray, np.ndarray]:
    return _coupled_h(8, 0.35, seed=61), chebyshev_weights(8, -25.0).astype(complex)


def test_af_complex_helper_matches_direct_kernel():
    # 复权重旁路（van_atta 同款）：旋转拆分路径与 Σw=0 直算兜底均对同核直算
    u = np.linspace(-1.0, 1.0, 501)
    rng = np.random.default_rng(67)
    w_rand = rng.uniform(-1.0, 1.0, 6) + 1j * rng.uniform(-1.0, 1.0, 6)
    w_zerosum = np.array([1.0 + 1.0j, -1.0 - 1.0j, 0.5 - 0.5j, -0.5 + 0.5j])
    for w in (w_rand, w_zerosum):
        idx = np.arange(w.size, dtype=float)
        kernel = np.exp(1j * 2.0 * np.pi * 0.5 * np.outer(idx, u))
        direct = w @ kernel
        got = pp._af_complex(u, w, 0.5)
        assert np.allclose(got, direct, rtol=1e-10, atol=1e-12)


def test_beam_report_distortion_corrected():
    # 互耦畸变（ε=0.35）下：矫正后方向图 rms 误差 < 矫正前，峰位恢复
    h, e_target = _beam_case()
    rep = pp.beam_predistortion_report(h, e_target, reg_lambda=0.0)
    assert rep["after"]["pattern_error_rms"] < rep["before"]["pattern_error_rms"]
    assert rep["peak_direction_improved"] is True
    assert rep["psl_improved"] is True
    # 矫正后峰位回到理想峰位（网格分辨率内）
    du = 2.0 / (rep["n_points"] - 1)
    assert abs(rep["after"]["peak_u"] - rep["ideal"]["peak_u"]) <= 2 * du
    # 主判据链闭合：λ=0 满秩回收残差在噪声级
    assert rep["residual_rel"] < 1e-8


def test_beam_report_json_safe_and_keys():
    h, e_target = _beam_case()
    rep = pp.beam_predistortion_report(h, e_target)
    payload = json.dumps(rep)  # 全 JSON 可序列化（None/bool/float）
    assert '"peak_direction_improved": true' in payload
    for section in ("ideal", "before", "after"):
        assert section in rep
        assert rep[section]["peak_u"] is not None
        assert rep[section]["psl_db"] is None or math.isfinite(rep[section]["psl_db"])
    assert isinstance(rep["n_points"], int)
    assert rep["n_points"] == 4001  # 缺省网格


def test_beam_report_grid_and_spacing_validation():
    h, e_target = _beam_case()
    with pytest.raises(ValueError, match="u_grid"):
        pp.beam_predistortion_report(h, e_target, u_grid=np.ones((3, 3)))
    with pytest.raises(ValueError, match="至少 3 点"):
        pp.beam_predistortion_report(h, e_target, u_grid=np.array([0.0, 0.5]))
    with pytest.raises(ValueError, match="spacing_lambda"):
        pp.beam_predistortion_report(h, e_target, spacing_lambda=0.0)
    # 显式网格生效
    u = np.linspace(-0.5, 0.5, 201)
    rep = pp.beam_predistortion_report(h, e_target, u_grid=u)
    assert rep["n_points"] == 201


# ─── 6. dataclass 与 to_dict JSON 安全面 ────────────────────────────────────


def test_spectrum_to_dict_json_safe_with_singular_zero():
    # 对角含零奇异值：cond=∞ → dict 折 None（判缺失 is not None），JSON 可序列化
    spec = pp.interaction_spectrum(np.diag([1.0, 0.0]))
    d = spec.to_dict()
    assert d["condition_number"] is None
    assert d["singular_values_db"][-1] is None
    assert d["correctable_dims"] == 1
    assert json.dumps(d)  # 序列化无异常
    # 良态例：cond 有限、谱有限
    d_ok = pp.interaction_spectrum(_coupled_h(4, 0.2, seed=71)).to_dict()
    assert d_ok["condition_number"] is not None and d_ok["condition_number"] > 0.0
    assert json.dumps(d_ok)


def test_poke_spectrum_dataclass_frozen():
    spec = pp.interaction_spectrum(_coupled_h(3, 0.2, seed=73))
    with pytest.raises(FrozenInstanceError, match="cannot assign"):
        spec.condition_number = 1.0  # type: ignore[misc]


# ─── 7. service 薄壳信封契约（可选件，ok=False 不抛）────────────────────────


def test_service_envelope_ok_and_error_paths():
    from rfauto.service import poke_predistortion_service as svc

    h = _coupled_h(4, 0.2, seed=79)
    e = chebyshev_weights(4, -20.0).astype(complex)
    h_json = [[[c.real, c.imag] for c in row] for row in h]
    e_json = [[c.real, c.imag] for c in e]

    spec_env = svc.poke_spectrum(h_json)
    assert spec_env["ok"] is True
    assert spec_env["data"]["correctable_dims"] == 4
    assert json.dumps(spec_env)

    fit_env = svc.poke_predistort(h_json, e_json, reg_lambda=0.0)
    assert fit_env["ok"] is True
    assert len(fit_env["data"]["weights"]) == 4
    assert all(len(pair) == 2 for pair in fit_env["data"]["weights"])
    assert json.dumps(fit_env)

    beam_env = svc.poke_beam_report(h_json, e_json, n_points=201)
    assert beam_env["ok"] is True
    assert beam_env["data"]["n_points"] == 201
    assert json.dumps(beam_env)

def test_service_accepts_plain_real_matrix_and_pair_vector():
    # 歧义角（期望形状消歧契约）：2×2 纯实矩阵不被吃成 [re,im] 对向量；
    # 向量叶子按深度 1 解释（实数=虚部 0，二元对=复数）
    from rfauto.service import poke_predistortion_service as svc

    env = svc.poke_predistort([[1.0, 0.1], [0.1, 1.0]], [[1.0, 0.0], [0.5, -0.2]])
    assert env["ok"] is True, env.get("error")
    assert len(env["data"]["weights"]) == 2
    # 行长不一致如实拒绝（ok=False 不抛）
    ragged = svc.poke_spectrum([[1.0, 0.0], [0.5]])
    assert ragged["ok"] is False and "行长不一致" in ragged["error"]


    # 失败路径：零矩阵 / 零目标 → ok=False + error 字符串，绝不抛出
    zeros_json = [[[0.0, 0.0]] * 2] * 2
    bad = svc.poke_spectrum(zeros_json)
    assert bad["ok"] is False and "零矩阵" in bad["error"]
    bad2 = svc.poke_predistort([[1.0, 0.1], [0.1, 1.0]], [[0.0, 0.0], [0.0, 0.0]])
    assert bad2["ok"] is False and "零向量" in bad2["error"]
