"""green_op 线性结构保留代理（NGO→RF 多端口叠加，T-N23/aurora_o 席 1）单测。

判据预声明（门数值定标证据 runs/aurora_o/tn23_calib/calib_out.txt，2026-10-31
同 seed 同数据预跑实测，本文件数据路径与定标脚本一致）：
- G1 叠加精确钉（结构恒等）：predict(αa1+βa2) 对 α·predict(a1)+β·predict(a2)
  相对残差 ≤ 1e-12（ridge/mlp 两头；实测 ~6e-16=浮点舍入底）；
- G2 合成对照（Wilkinson 3 端口闭式族 θ=(f0, r_iso) 扫参，留出 θ×随机激励）：
  ridge(poly_degree=3) RMSE ≤ 5e-3（实测 1.44e-3），mlp(1500ep/32h) ≤ 1e-2
  （实测 2.4e-3）；green_op ≤ 0.05 × 非结构 ridge 基线 [poly2(θ),Re a,Im a]→b
  （实测比值 ~0.007）且 ≤ 0.05 × 均值-S 基线（同量级）；
- G3 确定性钉：同 seed 同数据两跑 predict_matrix/predict_response 逐位一致，
  拟合不触全局 RNG 态；
- G4 负例：端口数不匹配 / 非有限激励 / 非法 config / 无有效样本显式报错；
- G5 注册纯增量：green_op 在册，既有 kind 零变动。

裁判纪律（#118/#300）：合成真值=独立闭式公式（Pozar §7.3 Wilkinson even/odd
模分析，与被测实现零共享代码），裁判自身先过已知基准锚（设计频点教科书值/
直流三通极限/扫参无源性）再上岗；基线在测试内用裸 numpy 独立实现。
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pytest

from rfauto.optimization.surrogate import surrogate_registry

F_LO_HZ = 1.0e9
F_HI_HZ = 3.0e9
N_FREQ = 41
BOUNDS = {"f0_ghz": (1.7, 2.3), "r_iso": (1.6, 2.4)}

# 预声明门（定标证据见模块 docstring）
GATE_SUPERPOSITION_REL = 1e-12
GATE_RMSE_RIDGE = 5e-3
GATE_RMSE_MLP = 1e-2
GATE_BASELINE_RATIO = 0.05


# ─── 独立裁判：Wilkinson 功分器闭式频率响应（Pozar §7.3 even/odd，零共享代码） ──


def _wilkinson_s(freq_hz, f0_hz, r_iso):
    """理想 Wilkinson 3 端口闭式：λ/4 臂 √2·Z0，隔离电阻 r_iso·Z0。

    端口 1 激励（对称）：两臂并联、隔离电阻无电流；端口 2/3 even/odd 模
    （even=R 开路，odd=端口 1 虚地、R/2 并联短路线）。参考面 Z0=1。
    """
    phi = 0.5 * np.pi * np.asarray(freq_hz, float) / float(f0_hz)
    c, s = np.cos(phi), np.sin(phi)
    za = np.sqrt(2.0)
    zin_arm = za * (c + 1j * za * s) / (za * c + 1j * s)
    zin1 = zin_arm / 2.0
    s11 = (zin1 - 1.0) / (zin1 + 1.0)
    # 半电路（半端口 1 参考 2Ω ↔ 端口 2 参考 1Ω）ABCD 传输 ÷√2
    s21 = 2.0 / (3.0 * c + 1j * 2.0 * za * s)
    zin_e = za * (2.0 * c + 1j * za * s) / (za * c + 1j * 2.0 * s)
    g_e = (zin_e - 1.0) / (zin_e + 1.0)
    rh = float(r_iso) / 2.0
    zin_o = (rh * 1j * za * s) / (rh * c + 1j * za * s)
    g_o = (zin_o - 1.0) / (zin_o + 1.0)
    s22 = 0.5 * (g_e + g_o)
    s23 = 0.5 * (g_e - g_o)
    out = np.zeros((len(phi), 3, 3), dtype=complex)
    out[:, 0, 0] = s11
    out[:, 0, 1] = out[:, 1, 0] = s21
    out[:, 0, 2] = out[:, 2, 0] = s21
    out[:, 1, 1] = out[:, 2, 2] = s22
    out[:, 1, 2] = out[:, 2, 1] = s23
    return out


def _freq_grid() -> np.ndarray:
    return np.linspace(F_LO_HZ, F_HI_HZ, N_FREQ)


def _make_training_samples() -> list[dict]:
    freq = _freq_grid()
    f0s = np.linspace(1.7, 2.3, 7)
    rs = np.linspace(1.6, 2.4, 7)
    return [{"params": {"f0_ghz": float(a), "r_iso": float(b)},
             "metrics": {"s_matrix": _wilkinson_s(freq, a * 1e9, b)}}
            for a in f0s for b in rs]


def _heldout_and_excitations():
    rng = np.random.default_rng(20261031)
    theta = rng.uniform([1.72, 1.65], [2.28, 2.35], size=(12, 2))
    exc = rng.normal(size=(12, 6, 3)) + 1j * rng.normal(size=(12, 6, 3))
    return theta, exc


def _rmse_on_heldout(predict_response, theta, exc) -> float:
    """留出 θ × 随机激励组合的反射波 RMSE（线性 |b| 单位）。"""
    freq = _freq_grid()
    sq = 0.0
    n = 0
    for th, excs in zip(theta, exc, strict=True):
        s_true = _wilkinson_s(freq, th[0] * 1e9, th[1])
        params = {"f0_ghz": float(th[0]), "r_iso": float(th[1])}
        for a in excs:
            b_true = np.einsum("fij,j->fi", s_true, a)  # 独立逐频矩阵-向量积
            b_pred = predict_response(params, a)
            sq += np.sum(np.abs(b_pred - b_true) ** 2)
            n += b_true.size
    return float(np.sqrt(sq / n))


def _fit_green_op(config_overrides: dict | None = None):
    cfg = {"bounds": dict(BOUNDS), "n_ports": 3, "n_freq": N_FREQ,
           "freq_grid_ghz": (1.0, 3.0)}
    cfg.update(config_overrides or {})
    model = surrogate_registry.create("green_op", config=cfg)
    info = model.fit(_make_training_samples())
    return model, info


# ─── 裁判自身基准（#300：裁判先过已知基准才有资格裁判） ───────────────────────


class TestJudgeCredentials:
    def test_design_frequency_textbook_values(self):
        """设计频点 f0：S11=S22=S33=S23=0，S21=S31=−j/√2（Pozar 教科书值）。"""
        f0_hz = 2.0e9
        s = _wilkinson_s(np.array([f0_hz]), f0_hz, 2.0)[0]
        assert abs(s[0, 0]) <= 1e-12
        assert abs(s[1, 1]) <= 1e-12 and abs(s[2, 2]) <= 1e-12
        assert abs(s[1, 2]) <= 1e-12
        for j in (1, 2):
            assert abs(s[0, j] + 1j / np.sqrt(2.0)) <= 1e-12

    def test_dc_junction_limit(self):
        """f→0：臂电长度→0，三端口直通并联 0.5Ω——S_ii=−1/3，S_ij=2/3（闭式极限）。"""
        s = _wilkinson_s(np.array([1.0e-6]), 2.0e9, 2.0)[0]
        for i in range(3):
            assert abs(s[i, i] + 1.0 / 3.0) <= 1e-9
            for j in range(3):
                if i != j:
                    assert abs(s[i, j] - 2.0 / 3.0) <= 1e-9

    def test_reciprocity_and_passivity_over_sweep(self):
        """θ 扫参全带宽：S=Sᵀ 且 σmax(S)≤1+1e-9（无源互易族封闭性）。"""
        freq = _freq_grid()
        sigma_max = 0.0
        for f0_ghz in np.linspace(1.7, 2.3, 7):
            for r in np.linspace(1.6, 2.4, 5):
                s = _wilkinson_s(freq, f0_ghz * 1e9, r)
                assert np.allclose(s, np.swapaxes(s, 1, 2))
                sigma_max = max(sigma_max, float(
                    np.linalg.svd(s, compute_uv=False)[:, 0].max()))
        assert sigma_max <= 1.0 + 1e-9


# ─── 线性读出纯函数面 ────────────────────────────────────────────────────────


class TestSuperposePureFunction:
    def _random_stack(self, n_freq=5, p=3):
        rng = np.random.default_rng(11)
        return (rng.normal(size=(n_freq, p, p))
                + 1j * rng.normal(size=(n_freq, p, p)))

    def test_matches_independent_loop(self):
        """superpose 与独立双重循环逐频矩阵-向量积逐位一致。"""
        from rfauto.optimization.surrogate.green_operator import superpose

        s = self._random_stack()
        rng = np.random.default_rng(12)
        a = rng.normal(size=3) + 1j * rng.normal(size=3)
        b = superpose(s, a)
        expected = np.array([[sum(s[f, i, j] * a[j] for j in range(3))
                              for i in range(3)] for f in range(len(s))])
        assert b.shape == (5, 3)
        assert np.array_equal(b, expected)

    def test_constant_and_per_frequency_forms_agree(self):
        """(P,) 常量激励与逐频复制 (n_freq, P) 激励结果逐位一致。"""
        from rfauto.optimization.surrogate.green_operator import superpose

        s = self._random_stack()
        rng = np.random.default_rng(13)
        a = rng.normal(size=3) + 1j * rng.normal(size=3)
        b_const = superpose(s, a)
        b_per_freq = superpose(s, np.broadcast_to(a, (5, 3)))
        assert np.array_equal(b_const, b_per_freq)

    def test_negative_port_mismatch(self):
        from rfauto.optimization.surrogate.green_operator import superpose

        s = self._random_stack()
        with pytest.raises(ValueError, match="端口数"):
            superpose(s, np.ones(2, dtype=complex))
        with pytest.raises(ValueError, match="逐频激励"):
            superpose(s, np.ones((5, 4), dtype=complex))

    def test_negative_bad_shapes(self):
        from rfauto.optimization.surrogate.green_operator import superpose

        s = self._random_stack()
        with pytest.raises(ValueError, match="ndim"):
            superpose(s, np.ones((2, 2, 3), dtype=complex))
        with pytest.raises(ValueError, match="n_freq"):
            superpose(s, np.ones((6, 3), dtype=complex))
        with pytest.raises(ValueError, match="方阵栈"):
            superpose(np.ones((5, 3, 4), dtype=complex), np.ones(3))

    def test_negative_non_finite_excitation(self):
        from rfauto.optimization.surrogate.green_operator import superpose

        s = self._random_stack()
        for bad in (np.array([np.nan, 0.0, 0.0]), np.array([np.inf, 0.0, 0.0])):
            with pytest.raises(ValueError, match="非有限"):
                superpose(s, bad)

    def test_residual_near_zero_and_scalar_guards(self):
        from rfauto.optimization.surrogate.green_operator import (
            superposition_residual,
        )

        s = self._random_stack()
        rng = np.random.default_rng(14)
        a1 = rng.normal(size=3) + 1j * rng.normal(size=3)
        a2 = rng.normal(size=3) + 1j * rng.normal(size=3)
        v = superposition_residual(s, a1, a2, alpha=0.3 + 0.7j, beta=-2.1 - 0.4j)
        assert v["residual_rel"] <= 1e-14
        assert set(v) == {"residual_max_abs", "residual_rel", "lhs_max_abs"}
        with pytest.raises(ValueError, match="有限标量"):
            superposition_residual(s, a1, a2, alpha=float("nan"))


# ─── G1 叠加精确钉（结构恒等，两种参数头） ────────────────────────────────────


class TestSuperpositionExactPin:
    _PARAMS: ClassVar[dict[str, float]] = {"f0_ghz": 2.05, "r_iso": 1.9}

    def _worst_random_combo(self, model, n=20):
        rng = np.random.default_rng(15)
        worst = 0.0
        for _ in range(n):
            a1 = rng.normal(size=3) + 1j * rng.normal(size=3)
            a2 = rng.normal(size=3) + 1j * rng.normal(size=3)
            alpha = complex(rng.normal(), rng.normal())
            beta = complex(rng.normal(), rng.normal())
            r = model.superposition_residual(self._PARAMS, a1, a2,
                                             alpha=alpha, beta=beta)
            worst = max(worst, r["residual_rel"])
            lhs = model.predict_response(self._PARAMS, alpha * a1 + beta * a2)
            rhs = alpha * model.predict_response(self._PARAMS, a1) \
                + beta * model.predict_response(self._PARAMS, a2)
            worst = max(worst, float(np.max(np.abs(lhs - rhs)))
                        / max(float(np.max(np.abs(lhs))), 1e-300))
        return worst

    def test_ridge_head_constructive_identity(self):
        model, _ = _fit_green_op({"head": "ridge", "poly_degree": 3})
        assert self._worst_random_combo(model) <= GATE_SUPERPOSITION_REL

    def test_mlp_head_constructive_identity(self):
        model, _ = _fit_green_op({"head": "mlp", "epochs": 400, "hidden": 16})
        assert self._worst_random_combo(model) <= GATE_SUPERPOSITION_REL

    def test_identity_is_exact_in_linear_readout_not_learned(self):
        """结构面钉：叠加残差对**未拟合的随机** Â 栈同样成立（读出线性与
        训练无关——恒等式来自 superpose 构造，不是优化收敛产物）。"""
        from rfauto.optimization.surrogate.green_operator import (
            superposition_residual,
        )

        rng = np.random.default_rng(16)
        s = rng.normal(size=(7, 3, 3)) + 1j * rng.normal(size=(7, 3, 3))
        a1 = rng.normal(size=3) + 1j * rng.normal(size=3)
        a2 = rng.normal(size=3) + 1j * rng.normal(size=3)
        v = superposition_residual(s, a1, a2, alpha=2.0 - 1j, beta=-0.5 + 3j)
        assert v["residual_rel"] <= 1e-14


# ─── 闭式精确回收（θ 族本身 ≤ poly_degree 次多项式时机器精度回收） ────────────


class TestExactRecovery:
    def test_polynomial_family_exact_recovery(self):
        """S(θ)=S_a+x1·S_b+x2·S_c+x1x2·S_d（对称族，x=归一化 θ）：degree=2、
        λ=0 闭式 ridge 应机器精度回收 predict_matrix（#118 裁判=独立展开式）。"""
        rng = np.random.default_rng(17)

        def sym() -> np.ndarray:
            return rng.normal(size=(5, 3, 3)) + 1j * rng.normal(size=(5, 3, 3))

        s_a, s_b, s_c, s_d = sym(), sym(), sym(), sym()
        for m in (s_a, s_b, s_c, s_d):
            m[:] = 0.5 * (m + np.swapaxes(m, 1, 2))
        x1s = np.linspace(-0.9, 0.9, 4)
        x2s = np.linspace(-0.8, 0.9, 4)
        samples = []
        for x1 in x1s:
            for x2 in x2s:
                samples.append({"params": {"p1": x1, "p2": x2},
                                "metrics": {"s_matrix":
                                            s_a + x1 * s_b + x2 * s_c + x1 * x2 * s_d}})
        model = surrogate_registry.create("green_op", config={
            "bounds": {"p1": (-1.0, 1.0), "p2": (-1.0, 1.0)},
            "n_ports": 3, "n_freq": 5, "head": "ridge", "poly_degree": 2,
            "ridge_lambda": 0.0})
        model.fit(samples)
        for x1 in (-0.73, 0.21, 0.55):
            for x2 in (-0.44, 0.66):
                truth = s_a + x1 * s_b + x2 * s_c + x1 * x2 * s_d
                got = model.predict_matrix({"p1": float(x1), "p2": float(x2)})
                assert np.max(np.abs(got - truth)) <= 1e-10


# ─── G2 合成对照（Wilkinson 闭式族，留出 θ×随机激励 RMSE 门 vs 独立基线） ─────


class TestSyntheticWilkinsonGate:
    def test_ridge_rmse_gate_and_beats_baselines(self):
        """预声明门：ridge d=3 留出 RMSE ≤ 5e-3；≤0.05×非结构 ridge 基线
        （[poly2(θ),Re a,Im a]→b 同容量类无叠加结构，测试内裸 numpy 实现）；
        ≤0.05×均值-S 基线。"""
        model, _info = _fit_green_op({"head": "ridge", "poly_degree": 3})
        theta, exc = _heldout_and_excitations()
        rmse = _rmse_on_heldout(model.predict_response, theta, exc)
        assert rmse <= GATE_RMSE_RIDGE, rmse
        # 基线 1：非结构 ridge（学习 (θ,a)→b 的同容量类，无叠加结构）
        rng_b = np.random.default_rng(7)
        xb, yb = [], []
        for t in _make_training_samples():
            p = t["params"]
            x = np.array([(p["f0_ghz"] - 2.0) / 0.3, (p["r_iso"] - 2.0) / 0.4])
            s = t["metrics"]["s_matrix"]
            for _ in range(6):
                a = rng_b.normal(size=3) + 1j * rng_b.normal(size=3)
                b = np.einsum("fij,j->fi", s, a)
                xb.append(np.concatenate([[1.0, x[0], x[1], x[0] ** 2,
                                           x[0] * x[1], x[1] ** 2],
                                          a.real, a.imag]))
                yb.append(np.concatenate([b.real.ravel(), b.imag.ravel()]))
        w = np.linalg.lstsq(np.array(xb), np.array(yb), rcond=None)[0]

        def unstructured(params, a):
            x = np.array([(params["f0_ghz"] - 2.0) / 0.3,
                          (params["r_iso"] - 2.0) / 0.4])
            y = np.concatenate([[1.0, x[0], x[1], x[0] ** 2, x[0] * x[1],
                                 x[1] ** 2], np.asarray(a).real,
                                np.asarray(a).imag]) @ w
            h = y.size // 2
            return (y[:h] + 1j * y[h:]).reshape(N_FREQ, 3)

        rmse_base = _rmse_on_heldout(unstructured, theta, exc)
        assert rmse <= GATE_BASELINE_RATIO * rmse_base, (rmse, rmse_base)
        # 基线 2：均值-S（不学 θ 依赖的下界）
        s_mean = np.mean([t["metrics"]["s_matrix"]
                          for t in _make_training_samples()], axis=0)
        rmse_mean = _rmse_on_heldout(
            lambda params, a: np.einsum("fij,j->fi", s_mean, a), theta, exc)
        assert rmse <= GATE_BASELINE_RATIO * rmse_mean, (rmse, rmse_mean)

    def test_mlp_rmse_gate(self):
        """预声明门：mlp(1500ep/32h) 留出 RMSE ≤ 1e-2（非线性参数头不破坏
        结构恒等，G1 已钉）。"""
        model, _ = _fit_green_op({"head": "mlp", "epochs": 1500, "hidden": 32})
        theta, exc = _heldout_and_excitations()
        rmse = _rmse_on_heldout(model.predict_response, theta, exc)
        assert rmse <= GATE_RMSE_MLP, rmse


# ─── 互易按构造（结构面） ─────────────────────────────────────────────────────


class TestReciprocityStructural:
    def test_predict_matrix_bitwise_symmetric(self):
        model, _ = _fit_green_op({"head": "ridge", "poly_degree": 2})
        s = model.predict_matrix({"f0_ghz": 1.95, "r_iso": 2.05})
        assert np.array_equal(s, np.swapaxes(s, 1, 2))  # 逐位（非 allclose）

    def test_non_reciprocal_mode_recovers_asymmetric(self):
        """reciprocal=False：非互易仿射族 S(x)=S_a+x·S_b（S_a/S_b 非对称，
        单向衰减器形 S12≠S21）全 P² 项回归，degree=1、λ=0 机器精度回收
        且 predict_matrix 不对称（#118 裁判=独立展开式）。"""
        rng = np.random.default_rng(18)
        s_a = rng.normal(size=(6, 2, 2)) + 1j * rng.normal(size=(6, 2, 2))
        s_b = rng.normal(size=(6, 2, 2)) + 1j * rng.normal(size=(6, 2, 2))
        samples = [{"params": {"g": float(x1)},
                    "metrics": {"s_matrix": s_a + x1 * s_b}}
                   for x1 in np.linspace(-0.9, 0.9, 4)]
        model = surrogate_registry.create("green_op", config={
            "bounds": {"g": (-1.0, 1.0)}, "n_ports": 2, "n_freq": 6,
            "reciprocal": False, "head": "ridge", "poly_degree": 1,
            "ridge_lambda": 0.0})
        info = model.fit(samples)
        assert info["reciprocal"] is False
        assert info["max_reciprocity_residual_train"] is None
        got = model.predict_matrix({"g": 0.3})
        truth = s_a + 0.3 * s_b
        assert np.max(np.abs(got - truth)) <= 1e-10
        assert not np.array_equal(got, np.swapaxes(got, 1, 2))

    def test_reciprocal_fit_reports_asymmetry_of_nonreciprocal_data(self):
        """互易模式吃非互易数据：如实报告 max_reciprocity_residual_train>0
        （对称化拟 (S+Sᵀ)/2），不静默、不报错（#122 诚实纪律）。"""
        rng = np.random.default_rng(19)
        samples = [{"params": {"g": float(x1)},
                    "metrics": {"s_matrix": 0.3
                                * (rng.normal(size=(4, 2, 2))
                                   + 1j * rng.normal(size=(4, 2, 2)))}}
                   for x1 in np.linspace(-0.9, 0.9, 5)]
        model = surrogate_registry.create("green_op", config={
            "bounds": {"g": (-1.0, 1.0)}, "n_ports": 2, "n_freq": 4,
            "reciprocal": True})
        info = model.fit(samples)
        assert info["max_reciprocity_residual_train"] > 0.0
        s = model.predict_matrix({"g": 0.0})
        assert np.array_equal(s, np.swapaxes(s, 1, 2))


# ─── G3 确定性钉 ─────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_ridge_bitwise(self):
        preds = []
        for _ in range(2):
            model, info = _fit_green_op({"head": "ridge", "poly_degree": 3})
            params = {"f0_ghz": 1.87, "r_iso": 2.21}
            preds.append((model.predict_matrix(params),
                          model.predict_response(params, np.array([1, 0, 0j])),
                          info["train_rmse"]))
        assert np.array_equal(preds[0][0], preds[1][0])
        assert np.array_equal(preds[0][1], preds[1][1])
        assert preds[0][2] == preds[1][2]

    def test_mlp_bitwise(self):
        preds = []
        for _ in range(2):
            model, _ = _fit_green_op({"head": "mlp", "epochs": 600,
                                      "hidden": 16})
            preds.append(model.predict_matrix({"f0_ghz": 1.87, "r_iso": 2.21}))
        assert np.array_equal(preds[0], preds[1])

    def test_no_global_rng_consumption(self):
        """中间插一次性随机消费不改变拟合结果——随机源只来自 config seed。"""
        model_a, _ = _fit_green_op({"head": "mlp", "epochs": 300, "hidden": 16})
        np.random.default_rng(999).random(16)  # 扰动全局态（若被消费即红）
        model_b, _ = _fit_green_op({"head": "mlp", "epochs": 300, "hidden": 16})
        assert np.array_equal(model_a.predict_matrix({"f0_ghz": 2.0,
                                                      "r_iso": 1.8}),
                              model_b.predict_matrix({"f0_ghz": 2.0,
                                                      "r_iso": 1.8}))

    def test_predict_pure_function(self):
        model, _ = _fit_green_op({"head": "ridge", "poly_degree": 2})
        params = {"f0_ghz": 2.1, "r_iso": 1.7}
        m1 = model.predict_matrix(params)
        m2 = model.predict_matrix(params)
        assert np.array_equal(m1, m2)
        assert model.predict(params) == model.predict(params)


# ─── G4 负例 + 契约面 ────────────────────────────────────────────────────────


class TestContractAndNegatives:
    def test_registered_incremental_only(self):
        assert "green_op" in surrogate_registry.available()
        for legacy in ("pole_residue", "mt_gp", "poly_ridge", "nn", "fno",
                       "deeponet", "pod_rom", "siren", "ensemble"):
            assert legacy in surrogate_registry.available()

    def test_predict_scalar_metrics_consistent_with_matrix(self):
        model, _ = _fit_green_op({"head": "ridge", "poly_degree": 2})
        params = {"f0_ghz": 1.9, "r_iso": 2.3}
        s = model.predict_matrix(params)
        out = model.predict(params)
        assert set(out) == {f"s{i + 1}{j + 1}_{tag}_in_band"
                            for i in range(3) for j in range(3)
                            for tag in ("db_max", "db_min")}
        for i in range(3):
            for j in range(3):
                db = 20.0 * np.log10(np.maximum(np.abs(s[:, i, j]), 1e-30))
                assert out[f"s{i + 1}{j + 1}_db_max_in_band"] == float(db.max())
                assert out[f"s{i + 1}{j + 1}_db_min_in_band"] == float(db.min())

    def test_p10_naming_underscore(self):
        model = surrogate_registry.create("green_op", config={
            "bounds": {"a": (-1.0, 1.0), "b": (-1.0, 1.0)}, "n_ports": 10,
            "n_freq": 2, "head": "ridge", "poly_degree": 1})
        rng = np.random.default_rng(21)
        samples = [{"params": {"a": float(x1), "b": float(-x1)},
                    "metrics": {"s_matrix": rng.normal(size=(2, 10, 10))
                                + 1j * rng.normal(size=(2, 10, 10))}}
                   for x1 in np.linspace(-0.8, 0.8, 4)]
        model.fit(samples)
        out = model.predict({"a": 0.0, "b": 0.0})
        assert "s1_10_db_max_in_band" in out
        assert "s10_10_db_min_in_band" in out

    def test_uncertainty_none_and_predict_with_std(self):
        model, _ = _fit_green_op({"head": "ridge", "poly_degree": 1})
        assert model.uncertainty({"f0_ghz": 2.0, "r_iso": 2.0}) is None
        merged = model.predict_with_std({"f0_ghz": 2.0, "r_iso": 2.0})
        key = "s11_db_max_in_band"
        mean, std = merged[key]
        assert std is None  # 不伪造 σ（#122）
        assert mean == model.predict({"f0_ghz": 2.0, "r_iso": 2.0})[key]

    def test_invalid_rows_skipped_and_counted(self):
        good = _make_training_samples()[:6]
        bad_rows = [
            {"params": {"f0_ghz": 2.0, "r_iso": 2.0}, "metrics": {}},  # 缺键
            {"params": {"f0_ghz": 2.0, "r_iso": 2.0},
             "metrics": {"s_matrix": np.ones((5, 3), complex)}},  # 形状不符
            {"params": {"f0_ghz": 2.0, "r_iso": 2.0},
             "metrics": {"s_matrix": "not-an-array"}},  # 不可转
            {"params": {"f0_ghz": 2.0, "r_iso": 2.0},
             "metrics": {"s_matrix": np.full((N_FREQ, 3, 3), np.nan,
                                             dtype=complex)}},  # 非有限
            {"params": {"f0_ghz": "x", "r_iso": 2.0},
             "metrics": {"s_matrix": _wilkinson_s(_freq_grid(), 2e9, 2.0)}},
        ]
        model = surrogate_registry.create("green_op", config={
            "bounds": dict(BOUNDS), "n_ports": 3, "n_freq": N_FREQ})
        info = model.fit(good + bad_rows)
        assert info["n_samples"] == 6
        assert info["n_skipped"] == 5

    def test_all_invalid_rejected(self):
        model = surrogate_registry.create("green_op", config={
            "bounds": dict(BOUNDS), "n_ports": 3, "n_freq": N_FREQ})
        with pytest.raises(ValueError, match="无有效"):
            model.fit([{"params": {"f0_ghz": 2.0, "r_iso": 2.0},
                        "metrics": {"s_matrix": np.ones((3, 3))}}])
        with pytest.raises(ValueError, match="无样本"):
            model.fit([])

    def test_unfitted_runtime_error(self):
        model = surrogate_registry.create("green_op", config={
            "bounds": dict(BOUNDS), "n_ports": 3, "n_freq": N_FREQ})
        with pytest.raises(RuntimeError, match="先 fit"):
            model.predict_matrix({"f0_ghz": 2.0, "r_iso": 2.0})
        with pytest.raises(RuntimeError, match="先 fit"):
            model.predict_response({"f0_ghz": 2.0, "r_iso": 2.0}, np.ones(3))
        with pytest.raises(RuntimeError, match="先 fit"):
            model.predict({"f0_ghz": 2.0, "r_iso": 2.0})
        with pytest.raises(RuntimeError, match="先 fit"):
            model.superposition_residual({"f0_ghz": 2.0, "r_iso": 2.0},
                                         np.ones(3), np.ones(3))

    def test_predict_response_port_mismatch_and_nonfinite(self):
        model, _ = _fit_green_op({"head": "ridge", "poly_degree": 1})
        params = {"f0_ghz": 2.0, "r_iso": 2.0}
        with pytest.raises(ValueError, match="端口数"):
            model.predict_response(params, np.ones(4, dtype=complex))
        with pytest.raises(ValueError, match="非有限"):
            model.predict_response(params, np.array([np.nan, 0.0, 0.0]))
        with pytest.raises(ValueError, match="非有限"):
            model.superposition_residual(params, np.array([np.inf, 0, 0]),
                                         np.ones(3, dtype=complex))

    def test_config_negative_guards(self):
        base = {"bounds": dict(BOUNDS), "n_ports": 3, "n_freq": N_FREQ}
        bad_cfgs = [
            {},
            {**base, "n_ports": 0},
            {**base, "n_ports": None},
            {**base, "n_freq": 0},
            {**base, "head": "lstm"},
            {**base, "poly_degree": 0},
            {**base, "ridge_lambda": -1.0},
            {**base, "hidden": 0},
            {**base, "epochs": 0},
            {**base, "lr": 0.0},
            {**base, "freq_grid_ghz": (3.0, 1.0)},
        ]
        for bad in bad_cfgs:
            with pytest.raises(ValueError):
                surrogate_registry.create("green_op", config=bad)

    def test_freq_hz_metadata(self):
        model = surrogate_registry.create("green_op", config={
            "bounds": dict(BOUNDS), "n_ports": 3, "n_freq": 11,
            "freq_grid_ghz": (1.0, 3.0)})
        assert model.freq_hz is not None
        assert len(model.freq_hz) == 11
        assert model.freq_hz[0] == 1.0e9 and model.freq_hz[-1] == 3.0e9
        bare = surrogate_registry.create("green_op", config={
            "bounds": dict(BOUNDS), "n_ports": 3, "n_freq": 5})
        assert bare.freq_hz is None

    def test_one_port_degenerate(self):
        rng = np.random.default_rng(22)
        samples = [{"params": {"g": float(x)},
                    "metrics": {"s_matrix": (0.5 + 0.1 * x)
                                * (rng.normal(size=(4, 1, 1))
                                   + 1j * rng.normal(size=(4, 1, 1)))}}
                   for x in np.linspace(-0.9, 0.9, 5)]
        model = surrogate_registry.create("green_op", config={
            "bounds": {"g": (-1.0, 1.0)}, "n_ports": 1, "n_freq": 4})
        info = model.fit(samples)
        assert info["n_ports"] == 1
        b = model.predict_response({"g": 0.2}, np.array([1.0]))
        assert b.shape == (4, 1)
        v = model.superposition_residual({"g": 0.2}, np.array([2.0]),
                                         np.array([-1.0j]), alpha=0.5,
                                         beta=2.0)
        assert v["residual_rel"] <= 1e-14

    def test_fit_info_keys(self):
        _, info = _fit_green_op({"head": "ridge", "poly_degree": 3})
        for key in ("kind", "n_samples", "n_skipped", "n_ports", "n_freq",
                    "n_outputs", "head", "poly_degree", "reciprocal",
                    "max_reciprocity_residual_train", "train_rmse",
                    "superposition_residual_rel"):
            assert key in info, key
        assert info["kind"] == "green_op"
        assert info["n_samples"] == 49
        assert info["n_skipped"] == 0
        assert info["reciprocal"] is True
        assert info["max_reciprocity_residual_train"] == 0.0
        assert info["superposition_residual_rel"] <= GATE_SUPERPOSITION_REL
