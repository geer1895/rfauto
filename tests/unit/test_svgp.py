"""SVGP 变分稀疏 GP 单测（aurora_p D3，注册键 "svgp"）。

判据（任务书预声明；容差先实测数量级后冻结，冻结实测值见各断言注记）：
- A1 已知锚（#118 数值裁判：先在已知 GP 后验上验 SVGP 正确性）：
  · 1D Z=X 退化锚（n=60，n_inducing≥n 自动取全训练点，fixed ℓ，
    noise_var=σ²/y_std²——标准化语义匹配）：标准化空间后验均值
    max|Δ| ≤ 1e-4（实测 3.7e-6，jitter 量级）、方差 max|Δ| ≤ 1e-5
    （实测 3.4e-7）——Titsias/Hensman 闭式后验在 Z=X 时恒等于精确
    GP 回归后验（R&W (2.22)-(2.24)，裁判=gp_det.gp_posterior 既有件，
    与被测实现零共享变分代码路径；核矩阵单源 se_ard_kernel 与
    rff_gp 的 ℓ 单源复用同一家法）；
  · 2D Z=X 中档（n=200）：标准化空间后验均值 max|Δ| ≤ 1e-3
    （实测 2.1e-5）；
  · ℓ 单源钉：svgp fit_info 的 ℓ 与 rff_gp（同参数同数据同 seed）逐位
    array_equal（两侧都单源调 gp_det.fit_mle）；
- B1 梯度裁判（#118 族）：mean-field 小批 ELBO 解析梯度对 m_w 与
  log_s2 的中心差分回收 max|Δ| ≤ 1e-4（实测 ~5e-7 = eps=1e-6 的
  中心差分固有量级）；
- A2 规模面（n>M 稀疏性钉，验收 C 的单测档）：n=5000、d=2、M=64
  closed 档 fit <10s（实测 1.4s）+ 200 点预测 r ≥ 0.9（实测 0.93）；
  minibatch 档 n=400/M=32/iters=150 r ≥ 0.9（实测 0.93）且 ELBO 有限；
  50k 档墙钟佐证在 runs/aurora_p/d3/BENCH.md（训练内存不随 n²）；
- A3 确定性（验收红线）：同 seed 两 fit——closed 档预测/σ/fit_info
  逐位相等；minibatch 档同 seed 逐位、异 seed 预测必异（种子确实进
  小批排列流）；FPS 诱导点选择同 seed 同结果；
- A4 负例（验收④）：n_inducing=0 / samples 空 / 缺 bounds / fixed
  ℓ≤0（标量与逐维任一负值）/ ℓ 列表长度错 / ell_mode·mode·
  inducing_init 非法 / noise_var≤0 / minibatch iters=0·batch_size=0·
  lr≤0 / 未拟合 predict——全部显式 ValueError/RuntimeError，不静默；
- A5 契约面（验收⑤零改动的存在性半边）：注册键在面 + 门面 re-export
  同一对象 + KIND="svgp" + predict_with_std 返回 (mean, std) 且 std 非
  None + σ≥0 + 远点 σ > 密集数据邻点 σ + 常数目标键 predict 常数且
  σ=0（fit_info 如实记 constant_keys）+ NaN 指标点忽略 + 有效点 <3 的
  键如实 skipped + M≥n 时 n_inducing 收敛到 n（退化档如实记录）；
  行为零改动由邻接回归定向批证明（本文件不重复）。

MLE 健康面注记（bench_surrogates 同款）：全周期病态面会把 gp_det
fit_mle 的 L-BFGS 推入非 PD Cholesky 区（共享内核既有行为，非本键
缺陷）——MLE 档用例一律用单峰半周期+σ=0.02 观测噪声的良性面。
"""

from __future__ import annotations

import time

import numpy as np
import pytest

import rfauto.optimization.surrogate as surr_pkg
from rfauto.optimization.surrogate import (
    DEFAULT_SVGP_SEED,
    SvgpSurrogate,
    farthest_point_sample,
    surrogate_registry,
    svgp_elbo_terms,
    svgp_inducing,
)
from rfauto.optimization.surrogate.gp_det import gp_posterior

_BOUNDS = {"a": (0.0, 1.0), "b": (0.0, 1.0)}


def _make_samples(x: np.ndarray, y: np.ndarray, key: str = "s21",
                  ) -> list[dict]:
    return [{"params": {"a": float(p[0]), "b": float(p[1])},
             "metrics": {key: float(v)}}
            for p, v in zip(x, y, strict=True)]


def _benign_face(x: np.ndarray, noise: float, seed: int = 123) -> np.ndarray:
    """单峰半周期良性面（bench_surrogates 配方：MLE 景观健康）。"""
    y = (1.0 + 1.6 * np.sin(np.pi * x[:, 0]) * np.cos(np.pi * x[:, 1]))
    if noise:
        y = y + np.random.default_rng(seed).normal(0.0, noise, y.shape[0])
    return y


class TestA1KnownAnchor:
    def test_1d_zx_collapses_to_exact_gp_posterior(self):
        rng = np.random.default_rng(0)
        n = 60
        x = np.sort(rng.uniform(0.0, 1.0, (n, 1)), axis=0)
        sigma2 = 0.01
        y = np.sin(6.0 * x[:, 0]) + rng.normal(0.0, np.sqrt(sigma2), n)
        y_mean = float(y.mean())
        y_std = float(y.std(ddof=1))
        samples = [{"params": {"a": float(p[0])},
                    "metrics": {"g": float(v)}}
                   for p, v in zip(x, y, strict=True)]
        model = surrogate_registry.create("svgp", config={
            "bounds": {"a": (0.0, 1.0)}, "n_inducing": 10 ** 9,
            "ell_mode": "fixed", "ell": 0.2,
            "noise_var": sigma2 / y_std ** 2, "seed": 1})
        info = model.fit(samples)
        assert info["n_inducing"] == n  # M≥n 退化档如实记录
        xt = np.linspace(0.02, 0.98, 25)[:, None]
        ys = (y - y_mean) / y_std
        mu_e, var_e = gp_posterior(
            x, ys, xt, ell=np.array([0.2]), amp=1.0,
            nugget=sigma2 / y_std ** 2, kind="se")
        mu_m = np.array([
            (model.predict({"a": float(p[0])})["g"] - y_mean) / y_std
            for p in xt])
        var_m = np.array([
            (model.uncertainty({"a": float(p[0])})["g"] / y_std) ** 2
            for p in xt])
        assert float(np.max(np.abs(mu_m - mu_e))) <= 1e-4  # 实测 3.7e-6
        assert float(np.max(np.abs(var_m - var_e))) <= 1e-5  # 实测 3.4e-7

    def test_2d_zx_medium_collapses(self):
        rng = np.random.default_rng(42)
        n = 200
        x = rng.uniform(0.0, 1.0, (n, 2))
        y = (np.sin(3 * np.pi * x[:, 0]) * np.cos(2 * np.pi * x[:, 1])
             + 0.5 * x[:, 0])
        y_mean, y_std = float(y.mean()), float(y.std(ddof=1))
        sigma2 = 0.02
        samples = _make_samples(x, y, key="f")
        model = surrogate_registry.create("svgp", config={
            "bounds": _BOUNDS, "n_inducing": 10 ** 9,
            "ell_mode": "fixed", "ell": [0.35, 0.3],
            "noise_var": sigma2 / y_std ** 2, "seed": 11})
        model.fit(samples)
        xt = rng.uniform(0.0, 1.0, (150, 2))
        ys = (y - y_mean) / y_std
        mu_e, _ = gp_posterior(
            x, ys, xt, ell=np.array([0.35, 0.3]), amp=1.0,
            nugget=sigma2 / y_std ** 2, kind="se")
        mu_m = np.array([
            (model.predict({"a": float(p[0]), "b": float(p[1])})["f"]
             - y_mean) / y_std for p in xt])
        assert float(np.max(np.abs(mu_m - mu_e))) <= 1e-3  # 实测 2.1e-5

    def test_ell_single_source_with_rff_gp(self):
        rng = np.random.default_rng(46)
        x = rng.uniform(0.0, 1.0, (300, 2))
        samples = _make_samples(x, _benign_face(x, noise=0.02), key="f")
        cfg = {"bounds": _BOUNDS, "seed": 3}
        info_s = surrogate_registry.create("svgp", config=dict(cfg)).fit(
            samples)
        info_r = surrogate_registry.create("rff_gp", config=dict(cfg)).fit(
            samples)
        assert np.array_equal(np.asarray(info_s["ell"]["f"]),
                              np.asarray(info_r["ell"]["f"]))


class TestB1Gradient:
    def test_meanfield_elbo_gradient_matches_finite_difference(self):
        rng = np.random.default_rng(0)
        n, m_dim = 40, 5
        x = np.sort(rng.uniform(0.0, 1.0, (n, 1)), axis=0)
        ell = np.array([0.3])
        from rfauto.optimization.surrogate.gp_det import se_ard_kernel
        z = x[np.sort(rng.choice(n, m_dim, replace=False))]
        l_mm = np.linalg.cholesky(
            se_ard_kernel(z, z, ell, 1.0) + 1e-6 * np.eye(m_dim))
        a_mat = np.linalg.solve(l_mm, se_ard_kernel(z, x, ell, 1.0))
        ys = np.sin(6.0 * x[:, 0])
        idx = rng.choice(n, 15, replace=False)
        m_w = np.full(m_dim, 0.05)
        log_s2 = np.full(m_dim, -1.0)
        noise_var = 0.02
        eps = 1e-6
        for _ in range(2):  # m_w 与 log_s2 各抽一维，足够钉公式形态
            j = int(rng.integers(0, m_dim))
            mp, mmin = m_w.copy(), m_w.copy()
            mp[j] += eps
            mmin[j] -= eps
            e_p, _, _ = svgp_elbo_terms(a_mat[:, idx].T, ys[idx], mp,
                                        log_s2, n, noise_var)
            e_m, _, _ = svgp_elbo_terms(a_mat[:, idx].T, ys[idx], mmin,
                                        log_s2, n, noise_var)
            _, g_m, _ = svgp_elbo_terms(a_mat[:, idx].T, ys[idx], m_w,
                                        log_s2, n, noise_var)
            fd = (e_p - e_m) / (2 * eps)
            assert abs(g_m[j] - fd) <= 1e-4, (j, g_m[j], fd)
            lp, lmin = log_s2.copy(), log_s2.copy()
            lp[j] += eps
            lmin[j] -= eps
            e_p, _, _ = svgp_elbo_terms(a_mat[:, idx].T, ys[idx], m_w,
                                        lp, n, noise_var)
            e_m, _, _ = svgp_elbo_terms(a_mat[:, idx].T, ys[idx], m_w,
                                        lmin, n, noise_var)
            _, _, g_ls = svgp_elbo_terms(a_mat[:, idx].T, ys[idx], m_w,
                                         log_s2, n, noise_var)
            fd = (e_p - e_m) / (2 * eps)
            assert abs(g_ls[j] - fd) <= 1e-4, (j, g_ls[j], fd)


class TestA2Scale:
    def test_n5000_m64_closed_sparse_fit(self):
        rng = np.random.default_rng(44)
        n = 5000
        x = rng.uniform(0.0, 1.0, (n, 2))
        y = (np.sin(2 * np.pi * x[:, 0]) + 0.5 * x[:, 1] ** 2
             + rng.normal(0.0, 0.01, n))
        samples = _make_samples(x, y, key="g")
        model = surrogate_registry.create("svgp", config={
            "bounds": _BOUNDS, "n_inducing": 64, "seed": 7})
        t0 = time.perf_counter()
        # aurora_p H1 P1-1 根治：BLAS 线程自守（#258 家族——16 线程下同
        # 计算 62s，1 线程 1.97s；threadpoolctl 与 sklearn 同源既有树）。
        # 阈值 10s 本身零放松：钉的是"n>M 稀疏性不随 n²"的设计断言。
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=1):
            info = model.fit(samples)
        wall = time.perf_counter() - t0
        assert wall < 10.0, wall  # 实测 1.4s（n>M 稀疏性：内存/墙钟不随 n²）
        assert info["n_inducing"] == 64
        xt = rng.uniform(0.0, 1.0, (200, 2))
        yt = np.sin(2 * np.pi * xt[:, 0]) + 0.5 * xt[:, 1] ** 2
        pred = np.array([model.predict(
            {"a": float(p[0]), "b": float(p[1])})["g"] for p in xt])
        r = float(np.corrcoef(pred, yt)[0, 1])
        assert r >= 0.9, r  # 实测 0.93

    def test_minibatch_mode_converges(self):
        rng = np.random.default_rng(45)
        n = 400
        x = rng.uniform(0.0, 1.0, (n, 2))
        y = (np.sin(3 * np.pi * x[:, 0]) * np.cos(2 * np.pi * x[:, 1])
             + 0.5 * x[:, 0] + rng.normal(0.0, 0.01, n))
        samples = _make_samples(x, y)
        model = surrogate_registry.create("svgp", config={
            "bounds": _BOUNDS, "seed": 5, "mode": "minibatch",
            "iters": 150, "n_inducing": 32,
            "ell_mode": "fixed", "ell": 0.3})
        info = model.fit(samples)
        assert np.isfinite(info["elbo"]["s21"])
        xt = rng.uniform(0.0, 1.0, (150, 2))
        yt = (np.sin(3 * np.pi * xt[:, 0]) * np.cos(2 * np.pi * xt[:, 1])
              + 0.5 * xt[:, 0])
        pred = np.array([model.predict(
            {"a": float(p[0]), "b": float(p[1])})["s21"] for p in xt])
        r = float(np.corrcoef(pred, yt)[0, 1])
        assert r >= 0.9, r  # 实测 0.93


class TestA3Determinism:
    def test_closed_same_seed_bit_identical(self):
        rng = np.random.default_rng(46)
        x = rng.uniform(0.0, 1.0, (80, 2))
        samples = _make_samples(x, _benign_face(x, noise=0.01))
        grid = [{"a": float(a), "b": float(b)}
                for a in np.linspace(0.05, 0.95, 7)
                for b in np.linspace(0.05, 0.95, 7)]
        outs = []
        for _ in range(2):
            m = SvgpSurrogate(config={"bounds": _BOUNDS,
                                      "n_inducing": 32})
            info = m.fit(samples)
            outs.append((
                info,
                [m.predict(g) for g in grid],
                [m.uncertainty(g) for g in grid]))
        assert outs[0][0] == outs[1][0]
        assert outs[0][1] == outs[1][1]
        assert outs[0][2] == outs[1][2]

    def test_minibatch_seed_controls_trajectory(self):
        rng = np.random.default_rng(47)
        x = rng.uniform(0.0, 1.0, (80, 2))
        samples = _make_samples(x, _benign_face(x, noise=0.01))
        preds = []
        for seed in (1, 1, 2):
            m = SvgpSurrogate(config={"bounds": _BOUNDS,
                                      "mode": "minibatch",
                                      "iters": 30, "n_inducing": 16,
                                      "ell_mode": "fixed", "ell": 0.3,
                                      "seed": seed})
            m.fit(samples)
            preds.append((m.predict({"a": 0.3, "b": 0.7})["s21"],
                          m.uncertainty({"a": 0.3, "b": 0.7})["s21"]))
        assert preds[0] == preds[1]  # 同 seed 逐位
        assert preds[0] != preds[2]  # 异 seed 小批排列必异

    def test_fps_deterministic(self):
        rng = np.random.default_rng(48)
        x = rng.uniform(0.0, 1.0, (100, 2))
        i1 = farthest_point_sample(x, 16, 9)
        i2 = farthest_point_sample(x, 16, 9)
        assert np.array_equal(i1, i2)
        assert i1.size == 16
        z_spread = svgp_inducing(x, 16, 9, "spread")
        z_random = svgp_inducing(x, 16, 9, "random")
        assert z_spread.shape == (16, 2)
        assert not np.array_equal(z_spread, z_random)


class TestA4Negatives:
    def _samples(self) -> list[dict]:
        rng = np.random.default_rng(49)
        x = rng.uniform(0.0, 1.0, (10, 2))
        return _make_samples(x, _benign_face(x, noise=0.01))

    def test_n_inducing_below_one(self):
        m = SvgpSurrogate(config={"bounds": _BOUNDS, "n_inducing": 0})
        with pytest.raises(ValueError, match="n_inducing"):
            m.fit(self._samples())

    def test_empty_samples(self):
        m = SvgpSurrogate(config={"bounds": _BOUNDS})
        with pytest.raises(ValueError, match="samples 为空"):
            m.fit([])

    def test_missing_bounds(self):
        m = SvgpSurrogate(config={})
        with pytest.raises(ValueError, match="bounds"):
            m.fit(self._samples())

    def test_fixed_ell_non_positive(self):
        for bad in (0.0, -0.5):
            m = SvgpSurrogate(config={"bounds": _BOUNDS,
                                      "ell_mode": "fixed", "ell": bad})
            with pytest.raises(ValueError, match="正有限"):
                m.fit(self._samples())
        m = SvgpSurrogate(config={"bounds": _BOUNDS, "ell_mode": "fixed",
                                  "ell": [0.3, -0.1]})
        with pytest.raises(ValueError, match="正有限"):
            m.fit(self._samples())

    def test_fixed_ell_wrong_length(self):
        m = SvgpSurrogate(config={"bounds": _BOUNDS, "ell_mode": "fixed",
                                  "ell": [0.3, 0.3, 0.3]})
        with pytest.raises(ValueError, match="长度 2"):
            m.fit(self._samples())

    def test_bad_enum_values(self):
        samples = self._samples()
        for field, bad, match in (
                ("ell_mode", "svi", "ell_mode"),
                ("mode", "svi", "mode"),
                ("inducing_init", "kmeans", "inducing_init")):
            m = SvgpSurrogate(config={"bounds": _BOUNDS, field: bad})
            with pytest.raises(ValueError, match=match):
                m.fit(samples)

    def test_noise_var_non_positive(self):
        for bad in (0.0, -1.0):
            m = SvgpSurrogate(config={"bounds": _BOUNDS, "noise_var": bad})
            with pytest.raises(ValueError, match="noise_var"):
                m.fit(self._samples())

    def test_minibatch_bad_hyperparams(self):
        samples = self._samples()
        base = {"bounds": _BOUNDS, "mode": "minibatch",
                "ell_mode": "fixed", "ell": 0.3}
        m = SvgpSurrogate(config={**base, "iters": 0})
        with pytest.raises(ValueError, match="iters"):
            m.fit(samples)
        m = SvgpSurrogate(config={**base, "batch_size": 0})
        with pytest.raises(ValueError, match="batch_size"):
            m.fit(samples)
        m = SvgpSurrogate(config={**base, "lr": -0.1})
        with pytest.raises(ValueError, match="lr"):
            m.fit(samples)

    def test_predict_before_fit(self):
        m = SvgpSurrogate(config={"bounds": _BOUNDS})
        with pytest.raises(RuntimeError, match="未拟合"):
            m.predict({"a": 0.5, "b": 0.5})
        with pytest.raises(RuntimeError, match="未拟合"):
            m.uncertainty({"a": 0.5, "b": 0.5})


class TestA5Contract:
    def test_registry_and_facade_identity(self):
        assert "svgp" in surrogate_registry.available()
        assert surr_pkg.SvgpSurrogate is SvgpSurrogate
        assert surr_pkg.DEFAULT_SVGP_SEED == DEFAULT_SVGP_SEED
        assert SvgpSurrogate.KIND == "svgp"

    def test_predict_with_std_has_native_sigma(self):
        rng = np.random.default_rng(51)
        x = rng.uniform(0.0, 1.0, (60, 2))
        m = SvgpSurrogate(config={"bounds": _BOUNDS, "n_inducing": 24,
                                  "ell_mode": "fixed", "ell": 0.3})
        m.fit(_make_samples(x, _benign_face(x, noise=0.01)))
        merged = m.predict_with_std({"a": 0.4, "b": 0.6})
        mean, std = merged["s21"]
        assert isinstance(mean, float)
        assert std is not None and std >= 0.0

    def test_sigma_monotone_away_from_data(self):
        rng = np.random.default_rng(52)
        x = rng.uniform(0.1, 0.4, (100, 2))  # 数据聚在左下角
        m = SvgpSurrogate(config={"bounds": _BOUNDS, "n_inducing": 32,
                                  "ell_mode": "fixed", "ell": 0.25,
                                  "seed": 5})
        m.fit(_make_samples(x, _benign_face(x, noise=0.01)))
        s_dense = m.uncertainty({"a": 0.2, "b": 0.2})["s21"]
        s_far = m.uncertainty({"a": 0.95, "b": 0.95})["s21"]
        assert s_far > s_dense, (s_dense, s_far)

    def test_constant_target_key(self):
        rng = np.random.default_rng(53)
        x = rng.uniform(0.0, 1.0, (20, 2))
        samples = [{"params": {"a": float(p[0]), "b": float(p[1])},
                    "metrics": {"c": 2.0}} for p in x]
        m = SvgpSurrogate(config={"bounds": _BOUNDS, "n_inducing": 8,
                                  "ell_mode": "fixed", "ell": 0.3})
        info = m.fit(samples)
        assert info["constant_keys"] == ["c"]
        assert m.predict({"a": 0.3, "b": 0.7})["c"] == pytest.approx(2.0)
        assert m.uncertainty({"a": 0.3, "b": 0.7})["c"] == 0.0

    def test_nan_metrics_ignored_and_sparse_key_skipped(self):
        rng = np.random.default_rng(54)
        x = rng.uniform(0.0, 1.0, (30, 2))
        samples = _make_samples(x, _benign_face(x, noise=0.01))
        for i in range(10):
            samples[i]["metrics"]["s21"] = float("nan")
        samples[0]["metrics"]["sparse"] = 1.0  # 仅 1 个有效点
        m = SvgpSurrogate(config={"bounds": _BOUNDS, "n_inducing": 12,
                                  "ell_mode": "fixed", "ell": 0.3})
        info = m.fit(samples)
        assert info["skipped_keys"] == ["sparse"]
        assert "s21" in info["keys"]
        val = m.predict({"a": 0.5, "b": 0.5})["s21"]
        assert np.isfinite(val)

    def test_min_fit_points_guard_skips_key(self):
        rng = np.random.default_rng(55)
        x = rng.uniform(0.0, 1.0, (20, 2))
        samples = _make_samples(x, _benign_face(x, noise=0.01))
        samples[5]["metrics"]["s21"] = float("nan")
        # 19 有效 ≥3 仍拟合
        m = SvgpSurrogate(config={"bounds": _BOUNDS, "n_inducing": 8,
                                  "ell_mode": "fixed", "ell": 0.3})
        info = m.fit(samples)
        assert "s21" in info["keys"]
        # 再打掉 2..19 → 剩 2 有效（0,1）<3 如实跳过
        for i in range(2, 20):
            samples[i]["metrics"]["s21"] = float("nan")
        m2 = SvgpSurrogate(config={"bounds": _BOUNDS, "n_inducing": 8,
                                   "ell_mode": "fixed", "ell": 0.3})
        info2 = m2.fit(samples)
        assert info2["skipped_keys"] == ["s21"]
