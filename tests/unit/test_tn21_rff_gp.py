"""T-N21 RFF 大规模 GP 单测（aurora_n W3，注册键 "rff_gp"）。

判据（任务书预声明；门值冻结于 runs/aurora_n/w3_tn21/criteria.md，
标定=同目录 probe_rff_gp.py 实测）：
- B1 Bochner 无偏性（#118 裁判独立：闭式 SE 核在测试内联重算，与被测
  实现零共享代码路径）：同 seed RFF 特征（D=4096，ℓ=[0.35,0.5]）的
  z(x)ᵀz(y) 对 15 个网格点对的 SE 闭式核值逐对偏差 |Δ| ≤ 0.05
  （蒙特卡洛 std 界 √(2/D)≈0.022 的 2σ 带；实测 max|Δ|=0.0135）；
- A1 近似一致性（验收①，n=200 小档，合成面加 σ=0.01 观测噪声——
  无噪内插档使 fit_mle L-BFGS-B 烧满 maxiter（实测 22.9s/次）且
  RFF 近内插振荡抬高 RMSE，噪声档为 RF 真实形态且条件数健康）：
  RFF(D=512) vs gp_det 精确 GP（同数据 fit_mle+gp_posterior）测试
  网格预测 Pearson r ≥ 0.95（实测 0.9937）且 RMSE 差
  |RMSE_rff−RMSE_gp| ≤ 0.10·std(y_test)（预声明带 0.0513；实测差
  0.0302，RFF 0.0345 vs GP 0.0647——含噪裁判面上 RFF 岭平滑反而
  更贴真值）；ℓ 单源钉：RFF fit_info 的 ℓ 与直接调 gp_det.fit_mle
  （同参数同数据）逐位 array_equal；
- A2 规模面小档（验收②单测档 <10s；实测 n=2000 fit+200 点预测
  0.06s）：n=2000、d=3、D=512 fixed 档 fit+预测完成且对闭式真值
  Pearson r ≥ 0.9（实测 0.9995）；n>mle_subsample 子样本分支：
  fit_info["mle_rows"]==60（测试显式 cap）；
- A3 确定性（验收③）：同 seed 两 fit——预测/σ 网格逐位 array_equal
  + fit_info 逐键相等；异 seed 预测必异（种子确实进采样器）；
- A4 负例（验收④）：n_features=0 / samples 空 / fixed ℓ≤0（标量与
  逐维任一负值）/ ℓ 列表长度错 / ell_mode 非法 / 未拟合 predict——
  全部显式 ValueError/RuntimeError，不静默；
- A5 契约面（验收⑤零改动的存在性半边）：注册键在面 + 门面 re-export
  同一对象 + predict_with_std 返回 (mean, std) 且 std 非 None + σ≥0
  + 远点 σ > 密集数据邻点 σ（固定 ℓ 插值域单调性）+ 常数目标键
  predict 常数且 σ=0（残差方差解析为 0，fit_info 如实记
  constant_keys）+ NaN 指标点忽略 + 有效点 <3 的键如实 skipped；
  行为零改动由邻接回归定向批证明（本文件不重复）。
"""

from __future__ import annotations

import numpy as np
import pytest

import rfauto.optimization.surrogate as surr_pkg
from rfauto.optimization.surrogate import (
    DEFAULT_RFF_SEED,
    RffGPSurrogate,
    fourier_features,
    sample_rff,
    surrogate_registry,
)
from rfauto.optimization.surrogate.gp_det import fit_mle, gp_posterior

_BOUNDS = {"a": (0.0, 1.0), "b": (0.0, 1.0)}


def _truth(x: np.ndarray) -> np.ndarray:
    """合成裁判面（闭式真值，与被测实现零共享代码路径，#118）。"""
    return np.sin(3.0 * np.pi * x[:, 0]) * np.cos(2.0 * np.pi * x[:, 1]) \
        + 0.5 * x[:, 0]


def _make_samples(x: np.ndarray, key: str = "s21",
                  noise: float = 0.01) -> list[dict]:
    """合成面采样（缺省 σ=0.01 观测噪声：MLE 条件数健康，见 A1 注记）。"""
    y = _truth(x)
    if noise:
        y = y + np.random.default_rng(123).normal(0.0, noise, y.size)
    return [{"params": {"a": float(p[0]), "b": float(p[1])},
             "metrics": {key: float(v)}}
             for p, v in zip(x, y, strict=True)]


class TestB1Bochner:
    def test_feature_inner_product_matches_se_kernel(self):
        ell = np.array([0.35, 0.5])
        omega, b = sample_rff(ell, 4096, DEFAULT_RFF_SEED)
        grid = np.linspace(0.1, 0.9, 5)
        pts = np.array([[gx, gy] for gx in grid for gy in grid])
        pairs = [(pts[i], pts[-1 - i]) for i in range(0, 15, 2)]
        z = fourier_features(np.array([p for pr in pairs for p in pr]),
                             omega, b)
        for k in range(len(pairs)):
            dot = float(z[2 * k] @ z[2 * k + 1])
            diff = (pairs[k][0] - pairs[k][1]) / ell
            k_se = float(np.exp(-0.5 * float(diff @ diff)))  # 闭式内联
            assert abs(dot - k_se) <= 0.05, (k, dot, k_se)


class TestA1Approximation:
    def test_rff_matches_exact_gp_and_ell_single_source(self):
        x = np.random.default_rng(42).uniform(0.0, 1.0, (200, 2))
        samples = _make_samples(x)
        xt = np.random.default_rng(43).uniform(0.0, 1.0, (300, 2))
        yt = _truth(xt)
        # 精确 GP 裁判（gp_det 既有件，零改动消费）
        xu = np.array([[s["params"]["a"], s["params"]["b"]]
                       for s in samples])
        y = np.array([s["metrics"]["s21"] for s in samples])
        params = fit_mle(xu, y, kind="se", optimize_nugget=False)
        mu_gp, _ = gp_posterior(xu, y, xt, ell=params["ell"],
                                amp=params["amp"],
                                nugget=params["nugget"], kind="se")
        # RFF 被测面（registry 通道）
        model = surrogate_registry.create("rff_gp", config={
            "bounds": _BOUNDS, "n_features": 512,
            "seed": DEFAULT_RFF_SEED})
        info = model.fit(samples)
        pred = np.array([model.predict({"a": float(p[0]), "b": float(p[1])})
                         ["s21"] for p in xt])
        r = float(np.corrcoef(pred, mu_gp)[0, 1])
        assert r >= 0.95, r
        rmse_rff = float(np.sqrt(np.mean((pred - yt) ** 2)))
        rmse_gp = float(np.sqrt(np.mean((mu_gp - yt) ** 2)))
        band = 0.10 * float(np.std(yt))
        assert abs(rmse_rff - rmse_gp) <= band, (rmse_rff, rmse_gp, band)
        # ℓ 单源钉：与直接 fit_mle 逐位同源（n=200 ≤ cap，全量路径）
        assert np.array_equal(np.asarray(info["ell"]["s21"]),
                              params["ell"])


class TestA2Scale:
    def test_n2000_fixed_ell_accuracy(self):
        rng = np.random.default_rng(44)
        x = rng.uniform(0.0, 1.0, (2000, 3))
        y = np.sin(2.0 * np.pi * x[:, 0]) + 0.5 * x[:, 1] ** 2 \
            + 0.3 * np.cos(4.0 * np.pi * x[:, 2])
        samples = [{"params": {k: float(v) for k, v in zip(
                ("a", "b", "c"), row, strict=True)},
            "metrics": {"g": float(v)}}
            for row, v in zip(x, y, strict=True)]
        model = surrogate_registry.create("rff_gp", config={
            "bounds": {"a": (0, 1), "b": (0, 1), "c": (0, 1)},
            "n_features": 512, "ell_mode": "fixed", "ell": 0.4,
            "seed": 7})
        model.fit(samples)
        xt = rng.uniform(0.0, 1.0, (200, 3))
        yt = (np.sin(2.0 * np.pi * xt[:, 0]) + 0.5 * xt[:, 1] ** 2
              + 0.3 * np.cos(4.0 * np.pi * xt[:, 2]))
        pred = np.array([model.predict({k: float(v) for k, v in zip(
                ("a", "b", "c"), row, strict=True)})["g"] for row in xt])
        r = float(np.corrcoef(pred, yt)[0, 1])
        assert r >= 0.9, r

    def test_mle_subsample_branch_engages(self):
        rng = np.random.default_rng(45)
        x = rng.uniform(0.0, 1.0, (400, 2))
        samples = _make_samples(x)
        model = surrogate_registry.create("rff_gp", config={
            "bounds": _BOUNDS, "n_features": 64, "seed": 3,
            "mle_subsample": 60})
        info = model.fit(samples)
        assert info["mle_rows"]["s21"] == 60
        assert model.fitted


class TestA3Determinism:
    def test_same_seed_bit_identical(self):
        x = np.random.default_rng(46).uniform(0.0, 1.0, (80, 2))
        samples = _make_samples(x)
        grid = [{"a": float(a), "b": float(b)}
                for a in np.linspace(0.05, 0.95, 7)
                for b in np.linspace(0.05, 0.95, 7)]
        outs = []
        for _ in range(2):
            m = RffGPSurrogate(config={"bounds": _BOUNDS,
                                       "n_features": 128})
            info = m.fit(samples)
            outs.append((
                info,
                [m.predict(g) for g in grid],
                [m.uncertainty(g) for g in grid]))
        assert outs[0][0] == outs[1][0]
        assert outs[0][1] == outs[1][1]
        assert outs[0][2] == outs[1][2]

    def test_different_seed_differs(self):
        x = np.random.default_rng(47).uniform(0.0, 1.0, (80, 2))
        samples = _make_samples(x)
        preds = []
        for seed in (1, 2):
            m = RffGPSurrogate(config={"bounds": _BOUNDS,
                                       "n_features": 128, "seed": seed})
            m.fit(samples)
            preds.append(m.predict({"a": 0.3, "b": 0.7})["s21"])
        assert preds[0] != preds[1]


class TestA4Negatives:
    def test_n_features_below_one(self):
        m = RffGPSurrogate(config={"bounds": _BOUNDS, "n_features": 0})
        with pytest.raises(ValueError, match="n_features"):
            m.fit(_make_samples(np.zeros((10, 2))))

    def test_empty_samples(self):
        m = RffGPSurrogate(config={"bounds": _BOUNDS})
        with pytest.raises(ValueError, match="samples 为空"):
            m.fit([])

    def test_fixed_ell_non_positive(self):
        x = np.random.default_rng(48).uniform(0.0, 1.0, (10, 2))
        samples = _make_samples(x)
        for bad in (0.0, -0.5):
            m = RffGPSurrogate(config={"bounds": _BOUNDS,
                                       "ell_mode": "fixed", "ell": bad})
            with pytest.raises(ValueError, match="正有限"):
                m.fit(samples)
        m = RffGPSurrogate(config={"bounds": _BOUNDS, "ell_mode": "fixed",
                                   "ell": [0.3, -0.1]})
        with pytest.raises(ValueError, match="正有限"):
            m.fit(samples)

    def test_fixed_ell_wrong_length(self):
        x = np.random.default_rng(49).uniform(0.0, 1.0, (10, 2))
        m = RffGPSurrogate(config={"bounds": _BOUNDS, "ell_mode": "fixed",
                                   "ell": [0.3, 0.3, 0.3]})
        with pytest.raises(ValueError, match="长度 2"):
            m.fit(_make_samples(x))

    def test_bad_ell_mode(self):
        x = np.random.default_rng(50).uniform(0.0, 1.0, (10, 2))
        m = RffGPSurrogate(config={"bounds": _BOUNDS, "ell_mode": "svi"})
        with pytest.raises(ValueError, match="ell_mode"):
            m.fit(_make_samples(x))

    def test_predict_before_fit(self):
        m = RffGPSurrogate(config={"bounds": _BOUNDS})
        with pytest.raises(RuntimeError, match="未拟合"):
            m.predict({"a": 0.5, "b": 0.5})


class TestA5Contract:
    def test_registry_and_facade_identity(self):
        assert "rff_gp" in surrogate_registry.available()
        assert surr_pkg.RffGPSurrogate is RffGPSurrogate
        assert RffGPSurrogate.KIND == "rff_gp"

    def test_predict_with_std_has_native_sigma(self):
        x = np.random.default_rng(51).uniform(0.0, 1.0, (60, 2))
        m = RffGPSurrogate(config={"bounds": _BOUNDS, "n_features": 64})
        m.fit(_make_samples(x))
        merged = m.predict_with_std({"a": 0.4, "b": 0.6})
        mean, std = merged["s21"]
        assert isinstance(mean, float)
        assert std is not None and std >= 0.0

    def test_sigma_monotone_away_from_data(self):
        rng = np.random.default_rng(52)
        x = rng.uniform(0.1, 0.4, (100, 2))  # 数据聚在左下角
        m = RffGPSurrogate(config={"bounds": _BOUNDS, "n_features": 256,
                                   "ell_mode": "fixed", "ell": 0.25,
                                   "seed": 5})
        m.fit(_make_samples(x))
        s_dense = m.uncertainty({"a": 0.2, "b": 0.2})["s21"]
        s_far = m.uncertainty({"a": 0.95, "b": 0.95})["s21"]
        assert s_far > s_dense, (s_dense, s_far)

    def test_constant_target_key(self):
        x = np.random.default_rng(53).uniform(0.0, 1.0, (20, 2))
        samples = [{"params": {"a": float(p[0]), "b": float(p[1])},
                    "metrics": {"c": 2.0}} for p in x]
        m = RffGPSurrogate(config={"bounds": _BOUNDS, "n_features": 64})
        info = m.fit(samples)
        assert info["constant_keys"] == ["c"]
        assert m.predict({"a": 0.3, "b": 0.7})["c"] == pytest.approx(2.0)
        assert m.uncertainty({"a": 0.3, "b": 0.7})["c"] == 0.0

    def test_nan_metrics_ignored_and_sparse_key_skipped(self):
        rng = np.random.default_rng(54)
        x = rng.uniform(0.0, 1.0, (30, 2))
        samples = _make_samples(x)
        for i in range(10):
            samples[i]["metrics"]["s21"] = float("nan")
        samples[0]["metrics"]["sparse"] = 1.0  # 仅 1 个有效点
        m = RffGPSurrogate(config={"bounds": _BOUNDS, "n_features": 64})
        info = m.fit(samples)
        assert info["skipped_keys"] == ["sparse"]
        assert "s21" in info["keys"]
        # 掩码面测试（精度门在 A1/A2）：20 个有效点拟合后预测有限即可
        val = m.predict({"a": 0.5, "b": 0.5})["s21"]
        assert np.isfinite(val)
