"""阶段 6.3：FNO-lite 曲线算子原型测试（torch 缺失时跳过）。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

torch = pytest.importorskip("torch", reason="torch 为可选依赖（extra: torch）")

from rfauto.optimization.surrogate import (
    FNOLiteSurrogate,
    surrogate_registry,
)


def _curve(x: float, f_ghz: np.ndarray) -> np.ndarray:
    """合成谐振曲线：谷位随 x 从 2.5GHz 线性移动，深度固定。"""
    f0 = 2.0 + 1.0 * x
    return (-30.0 / (1.0 + ((f_ghz - f0) / 0.08) ** 2)).astype(float)


@pytest.fixture
def samples():
    bounds = {"x": (0.0, 1.0)}
    f = np.linspace(1.5, 3.5, 201)
    samples = []
    for x in np.linspace(0.0, 1.0, 15):
        samples.append({
            "params": {"x": float(x)},
            "metrics": {"s11_curve_db": _curve(x, f).tolist()},
        })
    return bounds, samples


class TestFNOLite:
    def test_registered(self):
        assert "fno_lite" in surrogate_registry.available()

    def test_predicts_full_curve(self, samples):
        bounds, s = samples
        model = FNOLiteSurrogate(config={
            "bounds": bounds, "freq_grid": [1.5, 3.5],
            "hidden": 64, "epochs": 2000, "seed": 42})
        info = model.fit(s)
        assert info["n_curves"] == 15 and model.fitted

        out = model.predict_curve({"x": 0.7}, n_points=101)
        f = np.asarray(out["freq_ghz"])
        pred = np.asarray(out["s11_db"])
        assert len(f) == 101 and len(pred) == 101
        # 谷位恢复：真实谷在 2.7GHz，预测谷位应接近（±0.05GHz）
        assert abs(f[int(np.argmin(pred))] - 2.7) < 0.05
        # 谷深恢复：真实 -30dB，预测应显著深于 -20dB
        assert pred.min() < -20.0

    def test_scalar_compat_predict(self, samples):
        bounds, s = samples
        model = FNOLiteSurrogate(config={"bounds": bounds,
                                         "freq_grid": [1.5, 3.5],
                                         "hidden": 32, "epochs": 300})
        model.fit(s)
        r = model.predict({"x": 0.5})
        assert r["s11_curve_max_in_band"] < 0.0

    def test_requires_curve_samples(self):
        bounds = {"x": (0.0, 1.0)}
        model = FNOLiteSurrogate(config={"bounds": bounds,
                                         "freq_grid": [1.5, 3.5]})
        with pytest.raises(ValueError, match="曲线样本不足"):
            model.fit([{"params": {"x": 0.5}, "metrics": {"f": 1.0}}])
