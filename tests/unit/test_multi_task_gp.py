"""T-N12 多输出 GP（ICM 共区域化核）单测：合成裁判 + 负例 + 确定性钉。

验收门预声明账本：runs/aurora_n/w2_tn12/CRITERIA.md（本文件测试编号
G1-G6 与之一一对应，门红如实 FAIL 不调门，#122）。裁判口径（#118 双
源）：真值源 = 闭式生成函数 g(x)=0.8·sin(2πx1)·cos(πx2)+0.3·x1 本身；
独立 GP 基线 = 同底座 gp_det 的 ℓ 网格 profile-MLE（单起点 L-BFGS-B 在
12 点 2 维合成问题上从一切初值塌入 δ 核劣盆地——诊断与修订预声明见
CRITERIA §2，以最强独立 GP 为基线才是公平裁判）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import minimize_scalar
from scipy.stats import qmc

from rfauto.optimization.surrogate import surrogate_registry
from rfauto.optimization.surrogate.gp_det import (
    DetGaussianProcess,
    gp_nll,
)
from rfauto.optimization.surrogate.multi_task_gp import (
    DEFAULT_MT_SEED,
    MultiTaskGPSurrogate,
    validate_coregionalization_matrix,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

BOUNDS = {"x0": (0.0, 1.0), "x1": (0.0, 1.0)}

#: 独立基线臂的 ℓ 网格（profile-MLE；覆盖塌缩盆地以外的平滑解带）
_PROFILE_ELL_GRID = (0.05, 0.1, 0.15, 0.2, 0.3, 0.45, 0.7, 1.0, 1.5, 2.5)


def _g(x: np.ndarray) -> np.ndarray:
    """闭式真值函数（#118 真值源：生成函数本身）。"""
    return 0.8 * np.sin(2.0 * np.pi * x[:, 0]) * np.cos(np.pi * x[:, 1]) \
        + 0.3 * x[:, 0]


def _make_samples(sign: float) -> list[dict]:
    """异位两指标确定性样本：y1 全观测、y2 偶数号观测。

    y2 = sign·y1 + 0.05·x1（任务书"y2=y1+ε 结构"的确定性 ε 取法——
    仓内 gp_det 消费面为确定性仿真指标的插值口径，CRITERIA §2 修订
    预声明①）。
    """
    X = qmc.LatinHypercube(d=2, seed=11).random(24)
    y1 = _g(X)
    y2 = sign * y1 + 0.05 * X[:, 0]
    samples: list[dict] = []
    for i in range(X.shape[0]):
        metrics: dict[str, float] = {"y1": float(y1[i])}
        if i % 2 == 0:
            metrics["y2"] = float(y2[i])
        samples.append({"params": {"x0": float(X[i, 0]),
                                   "x1": float(X[i, 1])},
                        "metrics": metrics})
    return samples


def _test_grid() -> np.ndarray:
    return qmc.LatinHypercube(d=2, seed=13).random(60)


def _fit_mt(samples: list[dict], **cfg) -> MultiTaskGPSurrogate:
    config = {"bounds": BOUNDS, "seed": DEFAULT_MT_SEED, **cfg}
    model = surrogate_registry.create("mt_gp", config=config)
    info = model.fit(samples)
    assert info["converged"]
    assert info["n_obs_per_metric"] == [24, 12]
    assert info["skipped_metrics"] == []
    return model


def _fit_independent_profile(
    samples: list[dict], key: str,
) -> DetGaussianProcess:
    """独立 GP 强基线：ℓ 网格 profile-MLE（gp_det gp_nll 底座）。

    单起点 L-BFGS-B 在本 12 点 2 维合成问题上从一切 ℓ0 初值塌入 δ 核
    劣盆地（fitted NLL 7.52 vs 平滑全局解 3.72，CRITERIA §2 修订预
    声明②）——逐 ℓ 网格点内优 log amp 取最小 NLL，取最强独立拟合。
    """
    rows = np.array([[s["params"]["x0"], s["params"]["x1"]] for s in samples])
    y_all = np.array([float(s["metrics"].get(key, np.nan))
                      for s in samples])
    mask = np.isfinite(y_all)
    rows_o, y_o = rows[mask], y_all[mask]
    nugget = max(float(np.var(y_o)), 1.0) * 1e-6 + 1e-10
    best: tuple[float, np.ndarray, float] | None = None
    for ell in _PROFILE_ELL_GRID:
        res = minimize_scalar(
            lambda la, el=ell: gp_nll(
                np.array([np.log(el)] * rows_o.shape[1] + [la]),
                rows_o, y_o, "se", nugget=nugget),
            bounds=(-10.0, 3.0), method="bounded",
            options={"xatol": 1e-10})
        cand = (float(res.fun), np.full(rows_o.shape[1], ell),
                float(np.exp(res.x)))
        if best is None or cand[0] < best[0]:
            best = cand
    assert best is not None
    params = {"ell": best[1], "amp": best[2], "nugget": nugget,
              "nll": best[0], "converged": True}
    return DetGaussianProcess(rows_o, y_o, params, "se")


def _rmse(pred: np.ndarray, truth: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(pred) - truth) ** 2)))


class TestG1G2G3Synthetic:
    """CRITERIA §2：合成对照三门（σ 收缩 / RMSE 不劣 / B 符号回收）。"""

    @staticmethod
    def _eval(sign: float) -> tuple[MultiTaskGPSurrogate, dict[str, float]]:
        samples = _make_samples(sign=sign)
        model = _fit_mt(samples)
        grid = _test_grid()
        truth = {"y1": _g(grid),
                 "y2": sign * _g(grid) + 0.05 * grid[:, 0]}
        out: dict[str, float] = {}
        for key in ("y1", "y2"):
            ind = _fit_independent_profile(samples, key)
            ind_mean, ind_var = ind.predict(grid)
            mt_mean = np.array([
                model.predict({"x0": float(p[0]), "x1": float(p[1])})[key]
                for p in grid])
            mt_sigma = np.array([
                model.uncertainty({"x0": float(p[0]), "x1": float(p[1])})[key]
                for p in grid])
            out[f"rmse_mt_{key}"] = _rmse(mt_mean, truth[key])
            out[f"rmse_ind_{key}"] = _rmse(ind_mean, truth[key])
            out[f"sigma_mean_mt_{key}"] = float(np.mean(mt_sigma))
            out[f"sigma_mean_ind_{key}"] = float(np.mean(
                np.sqrt(np.maximum(ind_var, 0.0))))
        # G1 专用口径：y2 缺测训练位置上的 σ 收缩
        miss = np.array([
            [s["params"]["x0"], s["params"]["x1"]] for s in samples
            if "y2" not in s["metrics"]])
        ind2 = _fit_independent_profile(samples, "y2")
        _m, ind_var_miss = ind2.predict(miss)
        mt_sigma_miss = np.array([
            model.uncertainty({"x0": float(p[0]), "x1": float(p[1])})["y2"]
            for p in miss])
        out["sigma_miss_mt_y2"] = float(np.mean(mt_sigma_miss))
        out["sigma_miss_ind_y2"] = float(
            np.mean(np.sqrt(np.maximum(ind_var_miss, 0.0))))
        return model, out

    def test_g1_sigma_shrinkage_heterotopic(self):
        """G1：异位设计下 y2 缺测位置 mt σ 严格小于强基线独立 GP σ。"""
        _model, out = self._eval(sign=1.0)
        assert out["sigma_miss_mt_y2"] < out["sigma_miss_ind_y2"], out

    def test_g2_rmse_not_worse_with_predeclared_band(self):
        """G2：RMSE_mt ≤ RMSE_ind×1.02（y2）/ ×1.05（y1），带预声明。"""
        _model, out = self._eval(sign=1.0)
        assert out["rmse_mt_y2"] <= out["rmse_ind_y2"] * 1.02, out
        assert out["rmse_mt_y1"] <= out["rmse_ind_y1"] * 1.05, out

    def test_g3_positive_correlation_recovered(self):
        """G3a：y2=y1+ε 结构 → corr̂ = B12/√(B11·B22) > +0.7。"""
        model, _out = self._eval(sign=1.0)
        assert model.corr_[0, 1] > 0.7, model.corr_

    def test_g3_negative_correlation_sign_recovered(self):
        """G3b：y2=−y1+ε 结构 → corr̂ < −0.7（负相关符号被 B 回收）。"""
        model, out = self._eval(sign=-1.0)
        assert model.corr_[0, 1] < -0.7, model.corr_
        # 诚实透出（不进门，CRITERIA §2 G3）：负相关臂预测面病态数值
        assert np.isfinite(out["rmse_mt_y2"])


class TestG4Negative:
    """CRITERIA §3 负例：显式报错，不修复不静默。"""

    def test_g4a_zero_numeric_metrics(self):
        samples = [{"params": {"x0": 0.1, "x1": 0.2},
                    "metrics": {"y1": "not-a-number"}}]
        model = surrogate_registry.create(
            "mt_gp", config={"bounds": BOUNDS})
        with pytest.raises(ValueError, match="指标数 0"):
            model.fit(samples)

    def test_g4a_all_metrics_below_min_points(self):
        samples = [{"params": {"x0": float(i) / 10.0, "x1": 0.5},
                    "metrics": {"y1": float(i)}} for i in range(2)]
        model = surrogate_registry.create(
            "mt_gp", config={"bounds": BOUNDS})
        with pytest.raises(ValueError, match="有效指标数 0"):
            model.fit(samples)

    def test_g4b_fixed_b_indefinite(self):
        samples = _make_samples(sign=1.0)
        model = surrogate_registry.create("mt_gp", config={
            "bounds": BOUNDS, "fixed_B": [[1.0, 2.0], [2.0, 1.0]]})
        with pytest.raises(ValueError, match="非半正定"):
            model.fit(samples)

    def test_g4b_fixed_b_asymmetric(self):
        samples = _make_samples(sign=1.0)
        model = surrogate_registry.create("mt_gp", config={
            "bounds": BOUNDS, "fixed_B": [[1.0, 0.0], [0.5, 1.0]]})
        with pytest.raises(ValueError, match="非对称"):
            model.fit(samples)

    def test_g4b_validator_direct(self):
        with pytest.raises(ValueError):
            validate_coregionalization_matrix([[1.0, 3.0], [0.0, 1.0]])
        with pytest.raises(ValueError):
            validate_coregionalization_matrix([[1.0, 2.0], [2.0, 1.0]])
        # 合法 PSD（含秩亏）通过且对称化原样返回
        ok = validate_coregionalization_matrix([[1.0, 1.0], [1.0, 1.0]])
        assert ok.shape == (2, 2)

    def test_g4c_rank_out_of_range(self):
        samples = _make_samples(sign=1.0)
        for rank in (0, 3):
            model = surrogate_registry.create(
                "mt_gp", config={"bounds": BOUNDS, "rank": rank})
            with pytest.raises(ValueError, match="rank"):
                model.fit(samples)

    def test_unknown_kernel(self):
        samples = _make_samples(sign=1.0)
        model = surrogate_registry.create(
            "mt_gp", config={"bounds": BOUNDS, "kernel": "rq"})
        with pytest.raises(ValueError, match="未知核种类"):
            model.fit(samples)


class TestG5Determinism:
    """CRITERIA §4 确定性钉：同 seed 同数据逐位复现（C4）。"""

    def test_g5_bitwise_refit_and_predict(self):
        samples = _make_samples(sign=1.0)
        grid = _test_grid()
        params_pts = [{"x0": float(p[0]), "x1": float(p[1])} for p in grid[:8]]
        infos = []
        preds = []
        stds = []
        for _ in range(2):
            model = _fit_mt(samples)
            infos.append(model.info_)
            preds.append(np.array([
                model.predict(p)["y2"] for p in params_pts]))
            stds.append(np.array([
                model.uncertainty(p)["y2"] for p in params_pts]))
        assert np.array_equal(infos[0]["ell"], infos[1]["ell"])
        assert np.array_equal(infos[0]["B"], infos[1]["B"])
        assert infos[0]["nll"] == infos[1]["nll"]
        assert np.array_equal(preds[0], preds[1])
        assert np.array_equal(stds[0], stds[1])

    def test_g5_no_hidden_global_rng_state(self):
        """同 config 重建实例（中间插一次性随机消费）结果不变——拟合
        随机源只来自 config seed 的独立 Generator，无全局态泄漏。"""
        samples = _make_samples(sign=1.0)
        np.random.default_rng(999).random(16)  # 扰动全局态（若被消费即红）
        model_a = _fit_mt(samples)
        np.random.default_rng(1234).random(16)
        model_b = _fit_mt(samples)
        assert np.array_equal(model_a.corr_, model_b.corr_)
        assert model_a.info_["nll"] == model_b.info_["nll"]


class TestG6DefaultSurface:
    """CRITERIA §5：纯增量键 + 单指标退化 + 消费面契约。"""

    def test_g6_registry_incremental_only(self):
        assert "mt_gp" in surrogate_registry.available()
        for legacy in ("poly_ridge", "smt_kriging", "warped_kriging",
                       "saas_gp", "smt_mfk", "gbdt", "conformal"):
            assert legacy in surrogate_registry.available()

    def test_g6_single_metric_degenerate(self):
        samples = [{"params": {"x0": u, "x1": 1.0 - u},
                    "metrics": {"f": float(np.sin(2.0 * np.pi * u))}}
                   for u in np.linspace(0.02, 0.98, 12)]
        model = surrogate_registry.create(
            "mt_gp", config={"bounds": BOUNDS})
        info = model.fit(samples)
        assert info["metrics"] == ["f"]
        assert model.corr_.shape == (1, 1)
        mean, cov = model.predict_joint({"x0": 0.3, "x1": 0.7})
        assert set(mean) == {"f"}
        assert cov.shape == (1, 1)
        assert cov[0, 0] >= 0.0

    def test_predict_joint_matches_marginals_and_sign(self):
        """predict_joint 对角=σ² 一致面 + 非对角符号与 corr 同号
        （跨指标协方差消费面自洽，T-N13 预留）。"""
        samples = _make_samples(sign=1.0)
        model = _fit_mt(samples)
        pt = {"x0": 0.42, "x1": 0.61}
        mean, cov = model.predict_joint(pt)
        std = model.uncertainty(pt)
        cov = 0.5 * (cov + cov.T)
        for j, key in enumerate(("y1", "y2")):
            assert cov[j, j] == pytest.approx(std[key] ** 2, rel=1e-10)
        assert np.sign(cov[0, 1]) == np.sign(model.corr_[0, 1])
        assert set(mean) == {"y1", "y2"}

    def test_predict_joint_rejects_batch(self):
        samples = _make_samples(sign=1.0)
        model = _fit_mt(samples)
        with pytest.raises(ValueError, match="单点"):
            model.model.predict_joint(np.zeros((2, 2)))

    def test_predict_pure_function_bitwise(self):
        samples = _make_samples(sign=1.0)
        model = _fit_mt(samples)
        pt = {"x0": 0.33, "x1": 0.77}
        m1, s1 = model.predict(pt), model.uncertainty(pt)
        m2, s2 = model.predict(pt), model.uncertainty(pt)
        assert m1 == m2
        assert s1 == s2

    def test_missing_bound_config_rejected(self):
        model = surrogate_registry.create("mt_gp", config={})
        with pytest.raises(ValueError, match="bounds"):
            model.fit([])
