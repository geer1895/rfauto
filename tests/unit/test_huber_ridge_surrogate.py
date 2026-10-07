"""OP-12 HuberRidgeSurrogate 单测：双基准自证 + 注册表 + 契约（全离线确定性）。

双基准（#118/#300）：
1. 闭式极限——无离群且 δ→∞ 时 Huber→平方损失，系数与 poly_ridge 岭闭式
   一致（机器精度级）；
2. 鲁棒性（Huber 1964 已知性质）——单点 gross outlier 下 Huber 系数恢复
   真值而 OLS（poly_ridge）被拖偏数个量级。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.optimization.surrogate import surrogate_registry
from rfauto.optimization.surrogate.huber_ridge import HuberRidgeSurrogate
from rfauto.optimization.surrogate.poly_ridge import PolyRidgeSurrogate

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

BOUNDS = {"x": (0.0, 1.0)}


def _linear_samples(n: int = 13, *, outlier: int | None = None,
                    outlier_value: float = 100.0) -> list[dict]:
    """y = 2 + 3x 的确定性网格样本；outlier 指定格点索引注 gross 值。

    outlier 放在 x=1 端点（杠杆点）——OLS 斜率被显著拖偏，鲁棒性对照
    才有区分度（放在 x=0.5 中心点则斜率几乎不动，判据退化）。
    """
    samples = []
    for i in range(n):
        x = i / (n - 1)
        y = 2.0 + 3.0 * x
        if outlier is not None and i == outlier:
            y = outlier_value
        samples.append({"params": {"x": x}, "metrics": {"y": y}})
    return samples


# ---------------------------------------------------------------------------
# 基准 1：闭式极限（δ→∞ ⇒ Huber≡平方损失 ≡ poly_ridge 岭闭式）
# ---------------------------------------------------------------------------

def test_no_outlier_delta_inf_matches_poly_ridge():
    samples = _linear_samples()
    cfg = {"bounds": BOUNDS, "order": 1, "ridge_lambda": 0.1}
    hub = HuberRidgeSurrogate(config={**cfg, "delta": 1e9})
    ref = PolyRidgeSurrogate(config=cfg)
    hub.fit(samples)
    ref.fit(samples)
    for x in (0.0, 0.25, 0.5, 0.77, 1.0):
        assert hub.predict({"x": x})["y"] == pytest.approx(
            ref.predict({"x": x})["y"], abs=1e-9)


def test_clean_data_auto_delta_still_accurate():
    """无离群 + auto δ：近零 λ 下精度达机器级（干净数据不受伤）。

    注意 λ 取近零：ridge_lambda=0.1 缺省档对斜率有 ~5% 收缩偏置
    （岭回归本性，poly_ridge 同）——真值恢复断言必须排除该偏置。
    """
    samples = _linear_samples()
    hub = HuberRidgeSurrogate(
        config={"bounds": BOUNDS, "order": 1, "ridge_lambda": 1e-8})
    hub.fit(samples)
    for x in (0.0, 0.5, 1.0):
        expect = 2.0 + 3.0 * x
        assert hub.predict({"x": x})["y"] == pytest.approx(expect, rel=1e-5)


# ---------------------------------------------------------------------------
# 基准 2：鲁棒性——gross outlier 下 Huber 恢复真值、OLS 被拖偏
# ---------------------------------------------------------------------------

def test_gross_outlier_huber_recovers_ols_dragged():
    samples = _linear_samples(outlier=12, outlier_value=100.0)  # x=1 处 +100
    lam = {"ridge_lambda": 1e-8}  # 近零 λ：断言鲁棒恢复而非岭收缩
    hub = HuberRidgeSurrogate(config={"bounds": BOUNDS, "order": 1, **lam})
    ref = PolyRidgeSurrogate(config={"bounds": BOUNDS, "order": 1, **lam})
    hub.fit(samples)
    ref.fit(samples)
    # OLS（poly_ridge）在杠杆离群点下斜率显著偏离 3
    ols_coef = ref.models["y"]
    hub_coef = hub.models["y"]
    assert abs(ols_coef[1] - 3.0) > 10.0  # 拖偏数个量级（实测 >> 10）
    # Huber 恢复线性真值（IRLS 实效剔除离群点）
    assert abs(hub_coef[1] - 3.0) < 1e-4 * 3.0
    assert abs(hub_coef[0] - 2.0) < 1e-4 * 2.0
    # 预测面同判：Huber 误差 ≪ OLS 误差。测试点取 x̄ 之外（0.0/0.5）——
    # OLS 斜率误差在 x̄ 附近贡献趋零（x=0.3 实测仅 0.21，判据退化）。
    for x_test in ({"x": 0.0}, {"x": 0.5}):
        truth = 2.0 + 3.0 * x_test["x"]
        err_h = abs(hub.predict(x_test)["y"] - truth)
        err_o = abs(ref.predict(x_test)["y"] - truth)
        assert err_h < 1e-3
        assert err_o > 1.0
        assert err_h * 100 < err_o


def test_huber_info_records_delta_and_convergence():
    samples = _linear_samples(outlier=12, outlier_value=100.0)
    hub = HuberRidgeSurrogate(config={"bounds": BOUNDS, "order": 1,
                                      "max_iter": 50, "tol": 1e-10})
    hub.fit(samples)
    info = hub.fit_info["y"]
    assert info["converged"] is True
    assert info["n_iter"] >= 1
    assert info["delta"] > 0.0


def test_huber_irls_deterministic():
    """同输入两次拟合预测逐位一致（C4 确定性红线）。"""
    samples = _linear_samples(outlier=5, outlier_value=-50.0)
    p1 = HuberRidgeSurrogate(config={"bounds": BOUNDS, "order": 1})
    p2 = HuberRidgeSurrogate(config={"bounds": BOUNDS, "order": 1})
    p1.fit(samples)
    p2.fit(samples)
    assert p1.predict({"x": 0.42}) == p2.predict({"x": 0.42})


# ---------------------------------------------------------------------------
# 注册表与基类契约
# ---------------------------------------------------------------------------

def test_registry_contains_huber_ridge():
    assert "huber_ridge" in surrogate_registry.available()
    model = surrogate_registry.create("huber_ridge",
                                      config={"bounds": BOUNDS, "order": 1})
    assert isinstance(model, HuberRidgeSurrogate)
    assert model.KIND == "huber_ridge"


def test_predict_before_fit_raises():
    model = HuberRidgeSurrogate(config={"bounds": BOUNDS, "order": 1})
    with pytest.raises(RuntimeError, match="未拟合"):
        model.predict({"x": 0.5})


def test_nan_metric_key_skipped_like_poly_ridge():
    samples = _linear_samples()
    for s in samples:
        s["metrics"]["broken"] = float("nan")
    hub = HuberRidgeSurrogate(config={"bounds": BOUNDS, "order": 1})
    hub.fit(samples)
    assert "y" in hub.models
    assert "broken" not in hub.models  # 全 NaN 键跳过不硬拟（同 poly_ridge）


def test_small_sample_downgrades_order_like_poly_ridge():
    """样本数不足二阶特征数+1 时自动降一阶（同 poly_ridge 防奇异语义）。"""
    samples = _linear_samples(4)[:3]
    hub = HuberRidgeSurrogate(config={"bounds": BOUNDS, "order": 2})
    hub.fit(samples)
    assert hub.effective_order == 1


def test_multi_metric_modeling():
    samples = []
    for i in range(8):
        x = i / 7.0
        samples.append({"params": {"x": x},
                        "metrics": {"y1": 1.0 + x, "y2": 5.0 - 2.0 * x}})
    hub = HuberRidgeSurrogate(
        config={"bounds": BOUNDS, "order": 1, "ridge_lambda": 1e-8})
    hub.fit(samples)
    pred = hub.predict({"x": 0.5})
    assert pred["y1"] == pytest.approx(1.5, rel=1e-5)
    assert pred["y2"] == pytest.approx(4.0, rel=1e-5)


def test_numpy_independence_of_fits():
    """两个指标共享设计阵但系数独立——互相不串扰（回归面）。"""
    samples = _linear_samples()
    for s in samples:
        s["metrics"]["other"] = 7.0
    hub = HuberRidgeSurrogate(
        config={"bounds": BOUNDS, "order": 1, "ridge_lambda": 1e-8})
    hub.fit(samples)
    pred = hub.predict({"x": 0.25})
    assert pred["other"] == pytest.approx(7.0, rel=1e-6)
    assert pred["y"] == pytest.approx(2.75, rel=1e-5)
    assert isinstance(pred["y"], float)
    assert np.isfinite(pred["y"])
