"""阶段 1.2：SMT Kriging 代理注册表接入测试（smt 缺失时跳过）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

smt = pytest.importorskip("smt", reason="SMT 为可选依赖（extra: smt）")

from rfauto.optimization.surrogate import (
    SMTKrigingSurrogate,
    surrogate_registry,
)


def _quadratic_samples(n: int = 20, seed: int = 5):
    rng = np.random.default_rng(seed)
    bounds = {"x": (0.0, 1.0), "y": (0.0, 1.0)}
    samples = []
    for _ in range(n):
        p = {"x": float(rng.uniform(0, 1)), "y": float(rng.uniform(0, 1))}
        samples.append({
            "params": p,
            "metrics": {"f": float(2 * p["x"] + 3 * p["y"] ** 2 - p["x"] * p["y"])},
        })
    return bounds, samples


class TestSMTKriging:
    def test_registered(self):
        assert "smt_kriging" in surrogate_registry.available()

    def test_fit_predict_accuracy(self):
        bounds, samples = _quadratic_samples()
        model = SMTKrigingSurrogate(config={"bounds": bounds})
        info = model.fit(samples)
        assert info["n_samples"] == 20 and model.fitted
        pred = model.predict({"x": 0.3, "y": 0.7})
        assert pred["f"] == pytest.approx(
            2 * 0.3 + 3 * 0.7 ** 2 - 0.3 * 0.7, abs=0.05)

    def test_uncertainty_positive(self):
        bounds, samples = _quadratic_samples()
        model = SMTKrigingSurrogate(config={"bounds": bounds})
        model.fit(samples)
        unc = model.uncertainty({"x": 0.5, "y": 0.5})
        assert unc["f"] >= 0.0
        # 训练点附近的不确定度应很小（GP 插值性质）
        near = samples[0]["params"]
        unc_near = model.uncertainty(near)
        assert unc_near["f"] <= unc["f"] + 1e-6

    def test_loocv_integration(self):
        from rfauto.optimization.surrogate import loocv_rho

        bounds, samples = _quadratic_samples(12)
        result = loocv_rho(
            samples,
            cost_fn=lambda s: s["metrics"]["f"],
            surrogate_factory=lambda: SMTKrigingSurrogate(
                config={"bounds": bounds}))
        assert result["ok"] and result["rho"] > 0.8, result

    def test_compare_surrogates_includes_kriging(self, tmp_path):
        from rfauto.service.calibration_service import compare_surrogates

        bounds, samples = _quadratic_samples(12)
        data = {"bounds": bounds, "objectives": [], "samples": samples}
        path = tmp_path / "samples.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        r = compare_surrogates(
            path, kinds=("poly_ridge", "nn", "smt_kriging"))
        assert r["ok"]
        krig_row = next(row for row in r["results"]
                        if row["kind"] == "smt_kriging")
        assert krig_row["ok"], krig_row
        assert "smt_kriging" in r["ranking"]
