"""OP-6（round16 §六）：全局-局部自动切换（trust-constr 代理精修）单元测试。

判据预声明（#207 合成函数；真目标=六峰驼类 2D 多峰解析函数，全局最优
≈ −1.0316）：

1. 单调护栏（语义钉）：采纳点真目标 ≤ 全局相位真最优；无采纳点时
   best 退回全局相位最优且 improved=False（不虚构改善）；
2. 合成判据（冻结 seed）：GP 代理 + 40 随机全局点 + trust-constr
   top-k 精修 → improved=True 且 best_true < global_best_true −0.05
   （本机实测 −0.9162→−1.0309，2026-10-03 冻结）；精修点落在盒内；
3. 确定性：同输入两次结果逐字段一致（trust-constr+FD 零随机）；
4. 代理面纪律：metric 缺失显式 ValueError；predict 缺键/非有限值
   RuntimeError（NaN 不静默带偏 trust-constr）；x0/bounds 键集不一致
   显式拒绝；起点越界自动截断入盒。
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel

from rfauto.optimization.global_local import (
    global_local_switch,
    local_refine_surrogate,
    surrogate_scalar_fn,
)

BOUNDS = {"x": (-2.0, 2.0), "y": (-1.0, 1.0)}


def sixhump(p: dict[str, float]) -> float:
    x, y = p["x"], p["y"]
    return float((4 - 2.1 * x**2 + x**4 / 3) * x**2 + x * y
                 + (4 * y**2 - 4) * y**2)


def _make_surrogate(seed: int = 0, n: int = 40):
    rng = np.random.default_rng(3)
    pts = [dict(zip(("x", "y"), rng.uniform([-2, -1], [2, 1]).tolist(),
                    strict=True)) for _ in range(n)]
    X = np.array([[p["x"], p["y"]] for p in pts])
    Y = np.array([sixhump(p) for p in pts])
    gp = GaussianProcessRegressor(
        kernel=ConstantKernel(1.0, (1e-3, 1e3))
        * RBF(length_scale=1.0, length_scale_bounds=(0.1, 3.0)),
        n_restarts_optimizer=2, random_state=seed, normalize_y=True,
    ).fit(X, Y)

    def predict_fn(p):
        v = np.asarray(gp.predict(np.array([[p["x"], p["y"]]]))).ravel()[0]
        return {"f": float(v)}

    return pts, predict_fn


class TestMonotoneGuard:
    def test_no_adoption_falls_back_honestly(self):
        # 真目标与代理反向（代理面低处=真目标高处）→ 采纳被护栏全部拒绝
        pts = [{"x": 0.5, "y": 0.0}, {"x": -0.5, "y": 0.0}]
        out = global_local_switch(
            global_points=pts,
            predict_fn=lambda p: {"f": -sixhump(p)},  # 反向代理
            true_objective=sixhump,
            bounds=BOUNDS, metric="f", top_k=2)
        assert out["improved"] is False
        assert out["best_params"] == out["global_best_params"]
        assert out["best_true"] == out["global_best_true"]
        assert all(r["adopted"] is False for r in out["refined"])

    def test_adopted_points_respect_guard(self):
        pts, predict_fn = _make_surrogate()
        out = global_local_switch(
            global_points=pts, predict_fn=predict_fn,
            true_objective=sixhump, bounds=BOUNDS, metric="f", top_k=3)
        for r in out["refined"]:
            if r["adopted"]:
                assert r["true_value"] <= out["global_best_true"] + 1e-12
            for key, lo_hi in BOUNDS.items():
                lo, hi = lo_hi
                assert lo - 1e-9 <= r["params"][key] <= hi + 1e-9


class TestSyntheticJudge:
    def test_improvement_on_sixhump(self):
        pts, predict_fn = _make_surrogate()
        out = global_local_switch(
            global_points=pts, predict_fn=predict_fn,
            true_objective=sixhump, bounds=BOUNDS, metric="f", top_k=3)
        assert out["improved"] is True
        assert out["best_true"] < out["global_best_true"] - 0.05
        assert out["best_true"] == pytest.approx(-1.0316, abs=0.01)

    def test_deterministic(self):
        pts, predict_fn = _make_surrogate()
        a = global_local_switch(global_points=pts, predict_fn=predict_fn,
                                true_objective=sixhump, bounds=BOUNDS,
                                metric="f", top_k=2)
        b = global_local_switch(global_points=pts, predict_fn=predict_fn,
                                true_objective=sixhump, bounds=BOUNDS,
                                metric="f", top_k=2)
        assert a == b

    def test_empty_global_points_rejected(self):
        with pytest.raises(ValueError, match="不得为空"):
            global_local_switch(global_points=[], predict_fn=lambda p: {"f": 0.0},
                                true_objective=sixhump, bounds=BOUNDS,
                                metric="f")


class TestSurrogateDiscipline:
    def test_metric_required(self):
        with pytest.raises(ValueError, match="显式给出"):
            surrogate_scalar_fn(lambda p: {"f": 1.0}, ["x"], "")

    def test_predict_missing_key_raises(self):
        fn = surrogate_scalar_fn(lambda p: {"other": 1.0}, ["x"], "f")
        with pytest.raises(RuntimeError, match="缺指标键"):
            fn(np.array([0.5]))

    def test_predict_nonfinite_raises(self):
        fn = surrogate_scalar_fn(lambda p: {"f": float("nan")}, ["x"], "f")
        with pytest.raises(RuntimeError, match="非有限"):
            fn(np.array([0.5]))

    def test_refine_keyset_mismatch_rejected(self):
        with pytest.raises(ValueError, match="键集"):
            local_refine_surrogate(
                lambda p: {"f": 0.0}, {"x": 0.0, "z": 1.0}, BOUNDS,
                metric="f")

    def test_refine_clips_out_of_box_start(self):
        out = local_refine_surrogate(
            lambda p: {"f": p["x"] ** 2 + p["y"] ** 2},
            {"x": 50.0, "y": -50.0}, BOUNDS, metric="f", maxiter=50)
        assert -2.0 <= out["x"]["x"] <= 2.0
        assert -1.0 <= out["x"]["y"] <= 1.0
