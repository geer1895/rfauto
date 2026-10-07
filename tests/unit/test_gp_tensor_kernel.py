"""PB-3（round5 插⑤）GP 张量输入核单测。

判据锚（预声明，任务书钉）：
- 标量极限退化：1 维+单位权重与手写经典 RBF 逐位一致；
- 权重恒等式：加权距离 ≡ √w 缩放坐标后标准 RBF（逐位，实现序）+
  独立口径 Σw(a−b)²（容差级，防同序自证）；
- 张量-展平等价：核/距离/fit/predict 两路径逐位一致；
- 合成回收：sin 真函数张量输入 held-out 误差显著小于均值基线；
- nugget：全同值病态 y → std 有限不爆（df6⑨ 回归钉）；
- shape/值域守卫：显式 ValueError。
全组纯 numpy 快路径（<5s）。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.gp_tensor_kernel import (
    DEFAULT_MAX_POINTS,
    RELATIVE_NUGGET,
    fit_weights_loocv,
    generalized_distance,
    regression_predict,
    tensor_rbf_kernel,
)

_NUGGET_FLOOR = 1e-10  # 与模块 _NUGGET_ABS_FLOOR 同值（var(y)=0 地板）


def test_scalar_limit_matches_classic_rbf_bitwise() -> None:
    """标量极限：1 维+单位权重/None 权重 ≡ 手写经典 RBF（逐位）。"""
    rng = np.random.default_rng(0)
    a = rng.normal(size=(6,))
    b = rng.normal(size=(5,))
    ell, sf = 0.7, 1.3
    for weights in (None, np.ones(()), np.ones((1,))):
        k = tensor_rbf_kernel(a, b, ell, weights=weights, sigma_f=sf)
        d = a[:, None] - b[None, :]
        q_ref = d * d
        k_ref = (sf * sf) * np.exp(-q_ref / (2.0 * ell * ell))
        assert k.shape == (6, 5)
        assert np.array_equal(k, k_ref)
    dist = generalized_distance(a, b)
    assert np.array_equal(dist, np.abs(a[:, None] - b[None, :]))
    # 核对角恒 σ_f²（q(x,x)=0 逐位精确）
    a7 = rng.normal(size=(7, 3))
    k_full = tensor_rbf_kernel(a7, a7, ell, sigma_f=sf)
    assert np.array_equal(k_full.diagonal(), np.full(7, sf * sf))


def test_weights_identity_scaled_coordinates_bitwise() -> None:
    """权重恒等式：加权距离 ≡ √w 缩放坐标后标准 RBF（逐位）+独立口径。"""
    rng = np.random.default_rng(1)
    a = rng.normal(size=(7, 3))
    b = rng.normal(size=(4, 3))
    w = np.array([0.5, 2.0, 1.25])
    ell = 0.9
    # 实现序同款手写：√w 缩放坐标 → 作差 → 平方 → 求和 → 标准 RBF
    s = np.sqrt(w)
    as_ = a * s
    bs = b * s
    d = as_[:, None, :] - bs[None, :, :]
    q_ref = (d * d).sum(axis=-1)
    k = tensor_rbf_kernel(a, b, ell, weights=w, sigma_f=1.0)
    assert np.array_equal(k, np.exp(-q_ref / (2.0 * ell * ell)))
    assert np.array_equal(
        generalized_distance(a, b, weights=w), np.sqrt(q_ref)
    )
    # 独立口径（Σ w_e(a_e−b_e)²，不同求和序）——容差级数学恒等，防同序自证
    t = a[:, None, :] - b[None, :, :]
    q_ind = (w[None, None, :] * (t * t)).sum(axis=-1)
    assert np.allclose(
        k, np.exp(-q_ind / (2.0 * ell * ell)), rtol=1e-12, atol=1e-14
    )
    # ARD 语义：某维权重=0 ⇒ 该维差异不影响距离
    w0 = np.array([1.0, 0.0, 1.0])
    a2 = a.copy()
    a2[:, 1] += 100.0  # 被零权维上大扰动
    assert np.array_equal(
        generalized_distance(a2, b, weights=w0),
        generalized_distance(a, b, weights=w0),
    )


def test_tensor_flatten_equivalence_bitwise() -> None:
    """张量 (n,2,2) 与展平 (n,4) 两路径：核/距离/fit/predict 逐位一致。"""
    rng = np.random.default_rng(2)
    x2 = rng.normal(size=(10, 4))
    xt = x2.reshape(10, 2, 2)
    b2 = rng.normal(size=(6, 4))
    bt = b2.reshape(6, 2, 2)
    w2 = rng.uniform(0.5, 2.0, size=4)
    wt = w2.reshape(2, 2)
    ell = 0.8
    assert np.array_equal(
        tensor_rbf_kernel(xt, bt, ell, weights=wt),
        tensor_rbf_kernel(x2, b2, ell, weights=w2),
    )
    assert np.array_equal(
        generalized_distance(xt, bt, weights=wt),
        generalized_distance(x2, b2, weights=w2),
    )
    y = np.sin(x2).sum(axis=1)
    fit_t = fit_weights_loocv(xt, y, [0.3, 1.0, 2.0], [wt, None])
    fit_f = fit_weights_loocv(x2, y, [0.3, 1.0, 2.0], [w2, None])
    assert fit_t["lengthscale"] == fit_f["lengthscale"]
    assert fit_t["loocv_mse"] == fit_f["loocv_mse"]
    assert fit_t["weights"] is not None and fit_f["weights"] is not None
    pred_t = regression_predict(
        xt, y, bt, lengthscale=ell, weights=wt
    )
    pred_f = regression_predict(
        x2, y, b2, lengthscale=ell, weights=w2
    )
    assert np.array_equal(pred_t["mean"], pred_f["mean"])
    assert np.array_equal(pred_t["std"], pred_f["std"])


def test_synthetic_recovery_beats_mean_baseline() -> None:
    """合成回收：sin 真函数张量输入 fit+predict，held-out 误差 ≪ 均值基线。"""
    rng = np.random.default_rng(42)
    n = 40
    x = rng.uniform(-1.0, 1.0, size=(n, 2))
    y = np.sin(3.0 * x[:, 0]) + 0.5 * np.cos(2.0 * x[:, 1])
    xt = x.reshape(n, 2, 1)
    w = np.ones((2, 1))
    perm = rng.permutation(n)
    tr, te = perm[:30], perm[30:]
    fit = fit_weights_loocv(
        xt[tr], y[tr], [0.2, 0.5, 1.0, 2.0], [w], sigma_f=1.0
    )
    assert fit["weights"] is not None
    assert np.isfinite(fit["loocv_mse"]) and fit["loocv_mse"] >= 0.0
    # LOO 自身须打赢均值基线（回归钉：mu 必须消费 y_train——
    # "mu=k*ᵀ(K+λI)⁻¹k* 漏乘 y"类错误会让 LOO-MSE 恰≈var(y)）
    assert fit["loocv_mse"] < float(np.var(y[tr]))
    assert fit["n_candidates"] == 4
    assert len(fit["table"]) == 4
    pred = regression_predict(
        xt[tr], y[tr], xt[te],
        lengthscale=fit["lengthscale"], weights=fit["weights"],
    )
    assert np.isfinite(pred["mean"]).all()
    assert np.isfinite(pred["std"]).all() and (pred["std"] > 0.0).all()
    mse_gp = float(np.mean((pred["mean"] - y[te]) ** 2))
    baseline = float(np.mean((float(np.mean(y[tr])) - y[te]) ** 2))
    assert baseline > 0.0
    assert mse_gp < 0.05 * baseline


def test_nugget_degenerate_constant_y() -> None:
    """df6⑨ 回归钉：全同值 y（var=0）→ std 有限不爆，λ 落绝对地板。"""
    rng = np.random.default_rng(3)
    a = rng.normal(size=(8, 3))
    y = np.full(8, 2.5)
    pred = regression_predict(a, y, a, lengthscale=1.0)
    assert np.isfinite(pred["mean"]).all()
    assert np.isfinite(pred["std"]).all()
    assert (pred["std"] >= 0.0).all()
    assert pred["nugget"] == pytest.approx(_NUGGET_FLOOR)
    fit = fit_weights_loocv(a, y, [0.5, 1.0])
    assert np.isfinite(fit["loocv_mse"])
    assert np.isfinite(fit["loocv_mean_logpdf"])
    assert fit["nugget"] == pytest.approx(_NUGGET_FLOOR)
    assert fit["weights"] is None  # 缺省权重网格=单位权重候选
    assert RELATIVE_NUGGET == 1e-8  # df6⑨ metric_transform 同值口径


def test_shape_and_value_guards() -> None:
    """shape/值域守卫：显式 ValueError（不静默吞）。"""
    rng = np.random.default_rng(4)
    a32 = rng.normal(size=(3, 2, 2))
    a33 = rng.normal(size=(4, 3))
    with pytest.raises(ValueError, match="单样本形不一致"):
        tensor_rbf_kernel(a32, a33, 1.0)
    with pytest.raises(ValueError, match="weights 形状"):
        generalized_distance(
            np.zeros((3, 4)), np.zeros((2, 4)), weights=np.ones(5)
        )
    with pytest.raises(ValueError, match="行数不一致"):
        regression_predict(
            rng.normal(size=(6, 3)), np.zeros(5), rng.normal(size=(2, 3)),
            lengthscale=1.0,
        )
    with pytest.raises(ValueError, match="bool"):
        tensor_rbf_kernel(
            np.ones((3, 2), dtype=bool), np.ones((2, 2)), 1.0
        )
    with pytest.raises(ValueError, match="bool"):
        generalized_distance(
            np.zeros((2, 2)), np.zeros((2, 2)),
            weights=np.ones(2, dtype=bool),
        )
    a_nan = np.ones((3, 2))
    a_nan[0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN/Inf"):
        generalized_distance(a_nan, np.zeros((2, 2)))
    with pytest.raises(ValueError, match="NaN/Inf"):
        regression_predict(
            np.ones((4, 2)), np.array([1.0, np.inf, 0.0, 1.0]),
            np.ones((2, 2)), lengthscale=1.0,
        )
    with pytest.raises(ValueError, match="必须为正"):
        tensor_rbf_kernel(np.ones((3, 2)), np.ones((2, 2)), 0.0)
    with pytest.raises(ValueError, match="必须为正"):
        tensor_rbf_kernel(np.ones((3, 2)), np.ones((2, 2)), 1.0, sigma_f=-1.0)
    with pytest.raises(ValueError, match="NaN/Inf"):
        tensor_rbf_kernel(np.ones((3, 2)), np.ones((2, 2)), np.nan)
    with pytest.raises(ValueError, match="至少需要 3 个样本"):
        fit_weights_loocv(np.zeros((2, 2)), np.zeros(2), [1.0])
    assert DEFAULT_MAX_POINTS == 200
    with pytest.raises(ValueError, match="超出小规模"):
        fit_weights_loocv(
            np.arange(10.0).reshape(5, 2), np.arange(5.0), [1.0],
            max_points=4,
        )
    with pytest.raises(ValueError, match="不能为空"):
        fit_weights_loocv(np.zeros((4, 2)), np.zeros(4), [])
