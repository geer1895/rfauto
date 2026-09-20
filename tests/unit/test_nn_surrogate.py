"""v2 物理先验 NN 代理（NNSurrogate）单测。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


def _samples():
    """合成 smooth 响应面：cost 对 arm_len 单调、对宽度交叉。"""
    pts = []
    for arm in (18.0, 20.5, 23.0):
        for sw in (0.25, 0.35, 0.45):
            for hw in (0.9, 1.1, 1.3):
                s11 = -2.0 - 0.8 * (arm - 18.0) - 30.0 * (sw - 0.25)
                s21 = -9.0 + 2.0 * (hw - 0.9)
                pts.append({"params": {"arm_len_mm": arm, "series_w_mm": sw,
                                       "shunt_w_mm": hw},
                            "metrics": {"s11_db_max_in_band": s11,
                                        "s21_db_mean_in_band": s21}})
    return pts


BOUNDS = {"arm_len_mm": (18.0, 23.0), "series_w_mm": (0.25, 0.45),
          "shunt_w_mm": (0.9, 1.3)}


class TestNNSurrogate:
    def test_registered(self):
        from rfauto.optimization.surrogate import surrogate_registry

        assert "nn" in surrogate_registry.available()

    def test_fit_predict_close_on_train_grid(self):
        from rfauto.optimization.surrogate import NNSurrogate

        samples = _samples()
        model = NNSurrogate(config={"bounds": BOUNDS, "epochs": 2500,
                                    "augmenter": "polynomial_cross"})
        info = model.fit(samples)
        assert info["n_samples"] == len(samples)
        pred = model.predict({"arm_len_mm": 20.5, "series_w_mm": 0.35,
                              "shunt_w_mm": 1.1})
        assert pred["s21_db_mean_in_band"] == pytest.approx(-8.0, abs=1.5)

    def test_deterministic_same_seed(self):
        from rfauto.optimization.surrogate import NNSurrogate

        samples = _samples()
        p = {"arm_len_mm": 21.0, "series_w_mm": 0.4, "shunt_w_mm": 1.0}
        r1 = NNSurrogate(config={"bounds": BOUNDS})
        r1.fit(samples)
        r2 = NNSurrogate(config={"bounds": BOUNDS})
        r2.fit(samples)
        assert r1.predict(p) == r2.predict(p)

    def test_uncertainty_positive(self):
        from rfauto.optimization.surrogate import NNSurrogate

        model = NNSurrogate(config={"bounds": BOUNDS})
        model.fit(_samples())
        u = model.uncertainty({"arm_len_mm": 20.0, "series_w_mm": 0.3,
                               "shunt_w_mm": 1.0})
        assert set(u) == {"s11_db_max_in_band", "s21_db_mean_in_band"}
        assert all(v >= 0 for v in u.values())

    def test_wilkinson_augmenter_sane(self):
        from rfauto.optimization.surrogate.nn_model import _wilkinson_rf

        feats = _wilkinson_rf({"series_w_mm": 0.33, "shunt_w_mm": 1.10,
                               "arm_len_mm": 20.5}, BOUNDS)
        # 50Ω 线（1.10mm）对 z0 的失配应接近 0；0.33mm 线对 zt≈76Ω（skrf
        # 精算值非理想 70.7），Γ≈0.13 属正常
        assert feats["gamma_shunt"] < 0.1
        assert feats["gamma_series"] < 0.2
        assert 0.8 < feats["arm_elec_ratio"] < 1.2

    def test_loocv_rho_runs(self):
        from rfauto.optimization.surrogate import NNSurrogate, loocv_rho

        def cost(s):
            return abs(s["metrics"]["s11_db_max_in_band"]) * 0.3 + \
                abs(s["metrics"]["s21_db_mean_in_band"] + 8.0)

        def make():
            return NNSurrogate(config={"bounds": BOUNDS, "epochs": 800,
                                       "n_ensemble": 3})

        result = loocv_rho(_samples(), cost, make)
        assert result["ok"]
        assert -1.0 <= result["rho"] <= 1.0

    def test_nan_metrics_rows_skipped(self):
        from rfauto.optimization.surrogate import NNSurrogate

        samples = _samples()
        samples.append({"params": {"arm_len_mm": 19.0, "series_w_mm": 0.3,
                                   "shunt_w_mm": 1.0},
                        "metrics": {"s11_db_max_in_band": float("nan"),
                                    "s21_db_mean_in_band": -8.0}})
        model = NNSurrogate(config={"bounds": BOUNDS})
        info = model.fit(samples)
        assert info["n_samples"] == len(samples) - 1
