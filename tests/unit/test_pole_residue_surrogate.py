"""pole_residue 极点-留数头 + 无源性后验判据（W4-3 最小骨架）单测。

裁判纪律（#118）：合成对照全部用与被测实现无共享代码路径的独立闭式公式
构造地面真相；无源性判据带正例（解析无源网络/恰无源边界）+负例（违例
必红）+容差语义钉；复现性=同配置两跑逐位一致（AGENTS 7 确定性红线）。
"""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """隔离体收编 tests/conftest.py::isolated（T5 三批单源化）。"""
    yield


F_LO_HZ = 1.0e9
F_HI_HZ = 5.0e9
N_FREQ = 81


def _freq_grid() -> np.ndarray:
    return np.linspace(F_LO_HZ, F_HI_HZ, N_FREQ)


def _raw_pole_response(freq_hz: np.ndarray, pole: complex,
                       residue: complex) -> np.ndarray:
    """独立公式：单极点项 r/(s-p)，不经被测实现（#118 无共享代码路径）。"""
    s = 2.0j * np.pi * np.asarray(freq_hz, dtype=float)
    return residue / (s - pole)


# ─── 极点-留数头：合成回收（解析可验证） ──────────────────────────────────────


class TestPoleResidueHead:
    def test_recovers_synthetic_exact(self):
        """已知极点-留数合成响应 → 固定基 LS 读出逐系数回收（机器精度带）。"""
        from rfauto.optimization.surrogate.pole_residue import default_pole_basis, fit_residues

        basis = default_pole_basis(F_LO_HZ, F_HI_HZ, 2, 2)
        freq = _freq_grid()
        # 真值：基内 1 个实极点 + 1 对共轭复极点（共轭对称留数）+ 实 d + 实 e
        truth = {0: 3.0e8 + 0.0j, 2: 1.0e8 + 5.0e7j, 3: 1.0e8 - 5.0e7j}
        d_true, e_true = 0.25, 2.0e-11
        s_curve = sum(_raw_pole_response(freq, basis[k], r)
                      for k, r in truth.items())
        s = 2.0j * np.pi * freq
        s_curve = s_curve + d_true + e_true * s

        model = fit_residues(freq, s_curve, basis)
        assert model["rms"] <= 1e-12
        residues = model["residues"]
        for k, r_true in truth.items():
            assert residues[k] == pytest.approx(r_true, rel=1e-6, abs=1e-3)
        # 共轭对称性独立核对（复数对逐位关系，非与实现比对）——门=1e-8，
        # 共轭对列近共线使系数层噪声底 ~3e-10 相对（响应层仍 ≤1e-10）
        assert residues[2] == pytest.approx(np.conj(residues[3]), rel=1e-8)
        assert complex(model["d"]) == pytest.approx(d_true, abs=1e-9)
        assert complex(model["e"]) == pytest.approx(e_true, rel=1e-6)
        # 基内其余极点的伪留数：系数层病态（共轭对列近共线）允许 ~O(1)
        # 泄漏，但相对 3e8 信号衰减 ≥8 个量级；裁判口径落在响应层——
        # 回收模型的频响对独立公式 ≤1e-10（物理上才有意义的精度）
        for k in (1, 4, 5):
            assert abs(residues[k]) <= 1.0
        from rfauto.optimization.surrogate.pole_residue import evaluate_pole_residue

        got = evaluate_pole_residue(freq, basis, residues, model["d"],
                                    model["e"])
        assert np.max(np.abs(got - s_curve)) <= 1e-10

    def test_evaluate_matches_independent_formula(self):
        """evaluate_pole_residue 与独立逐项公式一致（前向面解析对照）。"""
        from rfauto.optimization.surrogate.pole_residue import default_pole_basis, evaluate_pole_residue

        basis = default_pole_basis(F_LO_HZ, F_HI_HZ, 1, 1)
        freq = _freq_grid()
        residues = np.array([2.0e8, 5.0e7 + 3.0e7j, 5.0e7 - 3.0e7j])
        d, e = 0.1 + 0.02j, 1.0e-11 - 4.0e-12j
        got = evaluate_pole_residue(freq, basis, residues, d, e)
        want = sum(_raw_pole_response(freq, basis[k], residues[k])
                   for k in range(len(basis)))
        s = 2.0j * np.pi * freq
        want = want + d + e * s
        assert np.max(np.abs(got - want)) <= 1e-15 * max(
            1.0, float(np.max(np.abs(want))))

    def test_fit_residues_guards(self):
        from rfauto.optimization.surrogate.pole_residue import default_pole_basis, fit_residues

        basis = default_pole_basis(F_LO_HZ, F_HI_HZ, 3, 0)
        with pytest.raises(ValueError, match="等长"):
            fit_residues(_freq_grid(), np.ones(10, dtype=complex), basis)
        with pytest.raises(ValueError, match="频点数"):
            fit_residues(np.linspace(F_LO_HZ, F_HI_HZ, 6),
                         np.ones(6, dtype=complex), basis)
        with pytest.raises(ValueError, match="f_lo_hz"):
            default_pole_basis(0.0, F_HI_HZ, 1, 0)
        with pytest.raises(ValueError, match="zeta"):
            default_pole_basis(F_LO_HZ, F_HI_HZ, 1, 0, zeta=1.5)


# ─── 无源性后验判据：正例 / 负例 / 容差语义 ───────────────────────────────────


def _series_rl_s(freq_hz: np.ndarray) -> np.ndarray:
    """独立公式：串联 R-L 单端口反射 S=(Z-Z0)/(Z+Z0)（正实 Z → 无源）。"""
    r_val, l_val, z0 = 10.0, 2.0e-9, 50.0
    z = r_val + 2.0j * np.pi * freq_hz * l_val
    return (z - z0) / (z + z0)


class TestPassivityVerdict:
    def test_positive_series_rl_network(self):
        from rfauto.optimization.surrogate.pole_residue import passivity_verdict

        verdict = passivity_verdict(_series_rl_s(_freq_grid()))
        assert verdict["passive"] is True
        assert verdict["sigma_max_in_band"] < 1.0
        assert verdict["lambda_min_i_minus_ssh"] >= 0.0

    def test_positive_matched_terminus(self):
        from rfauto.optimization.surrogate.pole_residue import passivity_verdict

        verdict = passivity_verdict(np.zeros(N_FREQ, dtype=complex))
        assert verdict["passive"] is True
        assert verdict["sigma_max_in_band"] == 0.0
        assert verdict["lambda_min_i_minus_ssh"] == pytest.approx(1.0)

    def test_positive_lossless_boundary_no_flake(self):
        """恰无源（无损单位阵，σmax=1 至浮点误差）不误红——eps 数值零位。"""
        from rfauto.optimization.surrogate.pole_residue import passivity_verdict

        freq = _freq_grid()
        theta = 0.3 + 0.1 * freq / F_HI_HZ
        c, s_ = np.cos(theta), np.sin(theta)
        stack = np.stack([np.array([[c[k], 1.0j * s_[k]],
                                    [1.0j * s_[k], c[k]]])
                          for k in range(len(freq))])
        verdict = passivity_verdict(stack)
        assert verdict["passive"] is True
        assert verdict["sigma_max_in_band"] <= 1.0 + 1e-12
        assert verdict["lambda_min_i_minus_ssh"] >= -1e-12
        assert verdict["lambda_min_i_minus_ssh"] >= -verdict["defect_eps"]

    def test_negative_scaled_curve_must_fail(self):
        """负例：无源曲线整体放大 1.5 → 判据必红，缺陷量给出负证据。"""
        from rfauto.optimization.surrogate.pole_residue import passivity_verdict

        verdict = passivity_verdict(_series_rl_s(_freq_grid()) * 1.5)
        assert verdict["passive"] is False
        assert verdict["sigma_max_in_band"] > 1.0
        assert verdict["lambda_min_i_minus_ssh"] < -0.1

    def test_negative_single_point_spike_must_fail(self):
        """负例：带内单频点 |S|=1+1e-3 尖峰 → 必红（逐频点判据不放行）。"""
        from rfauto.optimization.surrogate.pole_residue import passivity_verdict

        s = _series_rl_s(_freq_grid()).copy()
        k = 40
        s[k] = s[k] * (1.001 / abs(s[k]))
        verdict = passivity_verdict(s)
        assert verdict["passive"] is False
        assert verdict["sigma_max_in_band"] == pytest.approx(1.001, abs=1e-9)

    def test_tolerance_semantics_pinned(self):
        """容差语义：σmax=1+5e-7 在 PASSIVITY_TOL=1e-6 内放行；1+1e-3 必红。"""
        from rfauto.core.macromodel import PASSIVITY_TOL
        from rfauto.optimization.surrogate.pole_residue import passivity_verdict

        assert PASSIVITY_TOL == 1e-6
        inside = passivity_verdict(
            np.full(N_FREQ, 1.0 + 5e-7, dtype=complex))
        assert inside["passive"] is True
        outside = passivity_verdict(
            np.full(N_FREQ, 1.0 + 1e-3, dtype=complex))
        assert outside["passive"] is False

    def test_multidiagonal_2port_negative(self):
        """2×2 负例：一个通道超 1 → 全矩阵判据必红（σmax 是矩阵量）。"""
        from rfauto.optimization.surrogate.pole_residue import passivity_verdict

        freq = _freq_grid()
        stack = np.stack([np.diag([0.5, 1.2 * (0.5 + 0.5 * f / F_HI_HZ)])
                          for f in freq])
        verdict = passivity_verdict(stack)
        assert verdict["passive"] is False

    def test_shape_and_tol_guards(self):
        from rfauto.optimization.surrogate.pole_residue import passivity_verdict

        with pytest.raises(ValueError, match="方阵"):
            passivity_verdict(np.ones((4, 2, 3), dtype=complex))
        with pytest.raises(ValueError, match="shape"):
            passivity_verdict(np.ones((2, 3, 4, 5), dtype=complex))
        with pytest.raises(ValueError, match="tol"):
            passivity_verdict(np.zeros(4, dtype=complex), tol=0.0)

    def test_batch_of_one_port_curves(self):
        """(n_model, n_freq) 1-port 批：任一成员违例 → 整批判非无源。"""
        from rfauto.optimization.surrogate.pole_residue import passivity_verdict

        good = _series_rl_s(_freq_grid())
        scale = 1.3  # max|good|≈0.858 → ×1.3 ≈ 1.116 > 1（真违例）
        batch = np.vstack([good, good * 0.9, good[None, :] * scale])
        verdict = passivity_verdict(batch)
        assert verdict["passive"] is False
        assert verdict["n_freq"] == N_FREQ
        assert verdict["sigma_max_in_band"] == pytest.approx(
            float(np.max(np.abs(good))) * scale, rel=1e-9)


# ─── 曲线代理端到端：解析参数族 → 回收 ────────────────────────────────────────


def _parametric_curves(params_list: list[dict[str, float]]) -> list[np.ndarray]:
    """独立公式构造无源参数族：G(s;p)=Σ a_k(p)·ω_k/(s+ω_k)。

    ω_k 取自极点基实极点（留数 r_k=a_k·ω_k 落基内 → LS 读出精确）；
    a_k(p)≥0 且 Σa_k≤0.81 → |G(jω)|≤0.81 ∀ω（三角不等式），族内全部
    无源——解析可验证的"参数→无源曲线"地面真相。
    """
    from rfauto.optimization.surrogate.pole_residue import default_pole_basis

    basis = default_pole_basis(F_LO_HZ, F_HI_HZ, 3, 0)
    omegas = np.array([-p.real for p in basis])
    freq = _freq_grid()
    s = 2.0j * np.pi * freq
    curves = []
    for params in params_list:
        x = {k: 2.0 * v - 1.0 for k, v in params.items()}
        a1 = 0.30 + 0.08 * x["p1"]
        a2 = 0.22 + 0.05 * x["p2"]
        a3 = 0.12 - 0.02 * x["p1"] + 0.02 * x["p3"]
        curve = sum((a * w) / (s + w) for a, w in zip((a1, a2, a3), omegas,
                                                      strict=False))
        curves.append(np.asarray(curve, dtype=complex))
    return curves


def _grid_samples() -> list[dict]:
    samples = []
    for v1 in (0.0, 0.5, 1.0):
        for v2 in (0.0, 0.5, 1.0):
            for v3 in (0.0, 0.5, 1.0):
                samples.append({"params": {"p1": v1, "p2": v2, "p3": v3},
                                "metrics": {}})
    curves = _parametric_curves([s["params"] for s in samples])
    for s, c in zip(samples, curves, strict=False):
        s["metrics"]["s11_curve"] = c
    return samples


BOUNDS = {"p1": (0.0, 1.0), "p2": (0.0, 1.0), "p3": (0.0, 1.0)}
PROBES = [{"p1": 0.2, "p2": 0.7, "p3": 0.4},
          {"p1": 0.9, "p2": 0.1, "p3": 0.6},
          {"p1": 0.5, "p2": 0.5, "p3": 0.5}]


def _config(**over):
    cfg = {"bounds": BOUNDS, "freq_grid_ghz": (1.0, 5.0), "n_freq": N_FREQ,
           "n_real_poles": 3, "n_cmplx_pairs": 0}
    cfg.update(over)
    return cfg


class TestPoleResidueSurrogate:
    def test_registered(self):
        from rfauto.optimization.surrogate import surrogate_registry

        assert "pole_residue" in surrogate_registry.available()

    def test_ridge_end_to_end_recovery(self):
        """仿射无源参数族 → ridge 头回收：曲线对独立公式误差 ≤1e-6。"""
        from rfauto.optimization.surrogate import PoleResidueSurrogate

        model = PoleResidueSurrogate(config=_config())
        info = model.fit(_grid_samples())
        assert info["n_samples"] == 27
        assert info["n_curves"] == 27
        assert info["passivity"]["passive"] is True
        assert info["max_fit_rms"] <= 1e-12

        probes = PROBES
        want = _parametric_curves(probes)
        for p, w in zip(probes, want, strict=False):
            got = model.predict_curve(p)
            assert np.max(np.abs(got - w)) <= 1e-6

    def test_predict_curve_analytic_continuation_off_grid(self):
        """带内非训练栅格频点（解析延拓面）同样对独立公式 ≤1e-6。"""
        from rfauto.optimization.surrogate import PoleResidueSurrogate

        model = PoleResidueSurrogate(config=_config())
        model.fit(_grid_samples())
        freq_ghz = np.linspace(1.2, 4.8, 33)
        p = PROBES[1]
        got = model.predict_curve(p, freq_ghz=freq_ghz)
        # 独立公式按指定频点重算（非训练栅格）
        from rfauto.optimization.surrogate.pole_residue import default_pole_basis
        basis = default_pole_basis(F_LO_HZ, F_HI_HZ, 3, 0)
        omegas = np.array([-q.real for q in basis])
        s = 2.0j * np.pi * freq_ghz * 1e9
        x = {k: 2.0 * v - 1.0 for k, v in p.items()}
        a1 = 0.30 + 0.08 * x["p1"]
        a2 = 0.22 + 0.05 * x["p2"]
        a3 = 0.12 - 0.02 * x["p1"] + 0.02 * x["p3"]
        want = sum((a * w) / (s + w)
                   for a, w in zip((a1, a2, a3), omegas, strict=False))
        assert np.max(np.abs(got - want)) <= 1e-6

    def test_predict_band_metrics_consistent_with_curve(self):
        from rfauto.optimization.surrogate import PoleResidueSurrogate

        model = PoleResidueSurrogate(config=_config())
        model.fit(_grid_samples())
        metrics = model.predict(PROBES[0])
        curve = model.predict_curve(PROBES[0])
        db = 20.0 * np.log10(np.maximum(np.abs(curve), 1e-30))
        assert metrics["s11_db_max_in_band"] == pytest.approx(
            float(db.max()), abs=1e-9)
        assert metrics["s11_db_min_in_band"] == pytest.approx(
            float(db.min()), abs=1e-9)
        assert metrics["s11_db_max_in_band"] < 0.0  # 无源族 |S|≤0.81 → dB<0

    def test_passivity_verdict_through_surrogate(self):
        from rfauto.optimization.surrogate import PoleResidueSurrogate

        model = PoleResidueSurrogate(config=_config())
        model.fit(_grid_samples())
        verdict = model.passivity_verdict(PROBES[0])
        assert verdict["passive"] is True
        assert verdict["sigma_max_in_band"] <= 0.9

    def test_passivity_negative_through_surrogate_fit_info(self):
        """脏数据负例：一条非无源训练曲线 → fit info 判据如实红（不静默）。

        samples[26]=(1,1,1) → Σa_k=0.81（全族带内 |S| 上界），×1.5 →
        上界 1.215 > 1，真违例（×小系数造不出 |S|>1，不算负例）。
        """
        from rfauto.optimization.surrogate import PoleResidueSurrogate

        samples = _grid_samples()
        samples[26]["metrics"]["s11_curve"] = (
            samples[26]["metrics"]["s11_curve"] * 1.5)
        info = PoleResidueSurrogate(config=_config()).fit(samples)
        assert info["passivity"]["passive"] is False
        assert info["passivity"]["sigma_max_in_band"] > 1.0

    def test_deterministic_ridge_bitwise(self):
        from rfauto.optimization.surrogate import PoleResidueSurrogate

        m1 = PoleResidueSurrogate(config=_config())
        m1.fit(_grid_samples())
        m2 = PoleResidueSurrogate(config=_config())
        m2.fit(_grid_samples())
        for p in PROBES:
            assert np.array_equal(m1.predict_curve(p), m2.predict_curve(p))

    def test_mlp_head_deterministic_bitwise_and_close(self):
        from rfauto.optimization.surrogate import PoleResidueSurrogate

        cfg = _config(head="mlp", epochs=3000, hidden=24)
        m1 = PoleResidueSurrogate(config=cfg)
        m1.fit(_grid_samples())
        m2 = PoleResidueSurrogate(config=cfg)
        m2.fit(_grid_samples())
        want = _parametric_curves(PROBES)
        for p, w in zip(PROBES, want, strict=False):
            g1, g2 = m1.predict_curve(p), m2.predict_curve(p)
            assert np.array_equal(g1, g2)  # 同种子逐位复现
            assert np.max(np.abs(g1 - w)) <= 0.05  # 骨架精度门（MLP 近似）

    def test_invalid_rows_skipped_and_virtual_sample_ready(self):
        """契约：无效行忽略；W4-4 虚拟样本=同构样本字典直接并入可拟合。"""
        from rfauto.optimization.surrogate import PoleResidueSurrogate

        samples = _grid_samples()
        samples.append({"params": {"p1": 0.3, "p2": 0.3, "p3": 0.3},
                        "metrics": {}})  # 缺曲线键 → 忽略
        samples.append({"params": {"p1": 0.4, "p2": 0.4, "p3": 0.4},
                        "metrics": {"s11_curve": np.ones(5, dtype=complex)}})
        samples.append({"params": {"p1": 0.4, "p2": 0.4, "p3": 0.4},
                        "metrics": {"s11_curve": "not-a-curve"}})
        # W4-4 形态：锚点间插值生成的同构虚拟样本（此处直接给一条合法插值
        # 样本验证接口接纳性；插值生成器本体属 W4-4，不越界实现）
        virtual_params = {"p1": 0.25, "p2": 0.75, "p3": 0.35}
        virtual = {"params": virtual_params,
                   "metrics": {"s11_curve": _parametric_curves(
                       [virtual_params])[0]}}
        samples.append(virtual)
        info = PoleResidueSurrogate(config=_config()).fit(samples)
        assert info["n_curves"] == 28

    def test_uncertainty_is_none_and_guards(self):
        from rfauto.optimization.surrogate import PoleResidueSurrogate

        model = PoleResidueSurrogate(config=_config())
        assert model.uncertainty(PROBES[0]) is None
        with pytest.raises(RuntimeError, match="先 fit"):
            model.predict(PROBES[0])
        with pytest.raises(RuntimeError, match="先 fit"):
            model.passivity_verdict(PROBES[0])
        with pytest.raises(ValueError, match="无样本"):
            model.fit([])
        with pytest.raises(ValueError, match="head"):
            PoleResidueSurrogate(config=_config(head="lstm"))
        with pytest.raises(ValueError, match="bounds"):
            PoleResidueSurrogate(config={"freq_grid_ghz": (1.0, 5.0)})
        with pytest.raises(ValueError, match="freq_grid_ghz"):
            PoleResidueSurrogate(config={"bounds": BOUNDS,
                                         "freq_grid_ghz": (5.0, 1.0)})
        with pytest.raises(ValueError, match="n_freq"):
            PoleResidueSurrogate(config=_config(n_freq=5))

    def test_all_invalid_curves_rejected(self):
        from rfauto.optimization.surrogate import PoleResidueSurrogate

        samples = [{"params": {"p1": 0.5, "p2": 0.5, "p3": 0.5},
                    "metrics": {}}]
        with pytest.raises(ValueError, match="无有效"):
            PoleResidueSurrogate(config=_config()).fit(samples)
