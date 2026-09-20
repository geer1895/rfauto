"""阶段 6.2：SMT MFK 双保真 co-kriging 测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

smt = pytest.importorskip("smt", reason="SMT 为可选依赖（extra: smt）")

from rfauto.optimization.surrogate import (
    SMTMultiFidelitySurrogate,
    surrogate_registry,
)


def _high_fn(x: float) -> float:
    return (6.0 * x - 2.0) ** 2 * np.sin(12.0 * x - 4.0)  # Forrester


def _low_fn(x: float) -> float:
    return 0.5 * _high_fn(x) + 4.0 * (x - 0.5) - 1.0  # 经典低保真变体


def _datasets():
    bounds = {"x": (0.0, 1.0)}
    low = [{"params": {"x": float(v)},
            "metrics": {"f": float(_low_fn(v))}}
           for v in np.linspace(0.0, 1.0, 21)]
    high = [{"params": {"x": float(v)},
             "metrics": {"f": float(_high_fn(v))}}
            for v in (0.0, 0.4, 0.6, 1.0)]
    return bounds, low, high


class TestSMTMultiFidelity:
    def test_registered(self):
        assert "smt_mfk" in surrogate_registry.available()

    def test_fusion_tracks_high_fidelity(self):
        bounds, low, high = _datasets()
        model = SMTMultiFidelitySurrogate(config={"bounds": bounds,
                                                  "low_fi_samples": low})
        info = model.fit(high)
        assert info["n_samples"] == 4 and model.fitted
        # 高保真测试点（非训练点）误差应显著小于纯低保真
        errs = []
        for x in (0.2, 0.5, 0.8):
            pred = model.predict({"x": x})["f"]
            errs.append(abs(pred - _high_fn(x)))
        assert max(errs) < 1.0, errs

    def test_uncertainty_available(self):
        bounds, low, high = _datasets()
        model = SMTMultiFidelitySurrogate(config={"bounds": bounds,
                                                  "low_fi_samples": low})
        model.fit(high)
        unc = model.uncertainty({"x": 0.5})
        assert unc["f"] >= 0.0

    def test_requires_low_fi(self):
        bounds, _low, high = _datasets()
        model = SMTMultiFidelitySurrogate(config={"bounds": bounds})
        with pytest.raises(ValueError, match="low_fi_samples"):
            model.fit(high)

    def test_predict_before_fit_rejected(self):
        bounds, low, _high = _datasets()
        model = SMTMultiFidelitySurrogate(config={"bounds": bounds,
                                                  "low_fi_samples": low})
        with pytest.raises(RuntimeError, match="未拟合"):
            model.predict({"x": 0.5})
