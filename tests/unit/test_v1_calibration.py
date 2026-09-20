"""v1 校准服务测试：采样设计 / 代理 / 端到端编排（mock 采样）。"""

from __future__ import annotations

import json

import numpy as np
import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


# ─── 采样设计 ────────────────────────────────────────────────────────────────

class TestTaguchi:
    def test_l9_three_factors(self):
        from rfauto.optimization.sample_design import taguchi_points

        bounds = {"a": (0.0, 1.0), "b": (10.0, 20.0), "c": (-1.0, 1.0)}
        d = taguchi_points(bounds, n_levels=3)
        assert len(d["points"]) == 9
        # 正交性：每因子每水平恰好 3 次（L9 性质）
        expected = {"a": [0.0] * 3 + [0.5] * 3 + [1.0] * 3,
                    "b": [10.0] * 3 + [15.0] * 3 + [20.0] * 3,
                    "c": [-1.0] * 3 + [0.0] * 3 + [1.0] * 3}
        for n in bounds:
            levels = sorted(round(p[n], 9) for p in d["points"])
            assert levels == sorted(expected[n]), n
        assert d["design"]["kind"] == "taguchi"

    def test_values_within_bounds(self):
        from rfauto.optimization.sample_design import taguchi_points

        bounds = {"a": (1.0, 2.0), "b": (0.0, 5.0), "c": (10.0, 11.0),
                  "d": (-2.0, -1.0)}
        for p in taguchi_points(bounds)["points"]:
            for n, (lo, hi) in bounds.items():
                assert lo <= p[n] <= hi

    def test_over_capacity_selects_bigger_array(self):
        from rfauto.optimization.sample_design import taguchi_points

        # 6 因子超出 L9 容量(4) → 自动升级 L27（27 行，全因子进表）
        bounds = {f"x{i}": (0.0, 1.0) for i in range(6)}
        d = taguchi_points(bounds, n_levels=3)
        assert len(d["points"]) == 27
        assert d["design"]["truncated"] == []
        for p in d["points"]:
            assert all(0.0 <= v <= 1.0 for v in p.values())

    def test_beyond_largest_table_truncates(self):
        from rfauto.optimization.sample_design import taguchi_points

        # 15 因子超出 L27 容量(13) → 截断到 13 因子进表，其余固定中位
        bounds = {f"x{i}": (0.0, 2.0) for i in range(15)}
        d = taguchi_points(bounds, n_levels=3)
        # 因子名排序为字典序：进表 x0,x1,x10..x14,x2..x7；x8/x9 落截断
        assert d["design"]["truncated"] == ["x8", "x9"]
        assert all(p["x8"] == 1.0 and p["x9"] == 1.0 for p in d["points"])


class TestLhs:
    def test_points_in_bounds_and_deterministic(self):
        from rfauto.optimization.sample_design import lhs_points

        bounds = {"a": (0.0, 1.0), "b": (5.0, 6.0)}
        d1 = lhs_points(bounds, 4, seed=7)
        d2 = lhs_points(bounds, 4, seed=7)
        assert [p["a"] for p in d1["points"]] == [p["a"] for p in d2["points"]]
        for p in d1["points"]:
            assert 0.0 <= p["a"] <= 1.0 and 5.0 <= p["b"] <= 6.0

    def test_min_dist_excludes_near_duplicates(self):
        from rfauto.optimization.sample_design import lhs_points

        bounds = {"a": (0.0, 1.0)}
        existing = [{"a": 0.5}]
        d = lhs_points(bounds, 50, seed=1, include=existing, min_dist=0.3)
        for p in d["points"]:
            assert abs(p["a"] - 0.5) >= 0.3


# ─── 多项式岭回归代理 ────────────────────────────────────────────────────────

class TestPolyRidge:
    def _make(self, order=2, lam=1e-6):
        from rfauto.optimization.surrogate import PolyRidgeSurrogate

        return PolyRidgeSurrogate(config={
            "bounds": {"x": (0.0, 1.0), "y": (0.0, 1.0)},
            "order": order, "ridge_lambda": lam,
            "metrics": ["f", "g"]})

    def test_exact_quadratic_recovery(self):
        model = self._make()
        samples = []
        for x in np.linspace(0, 1, 5):
            for y in np.linspace(0, 1, 5):
                samples.append({
                    "params": {"x": float(x), "y": float(y)},
                    "metrics": {"f": 2.0 * x + 3.0 * y * y - x * y,
                                "g": 1.0}})
        info = model.fit(samples)
        assert info["n_samples"] == 25 and model.fitted
        pred = model.predict({"x": 0.3, "y": 0.7})
        assert pred["f"] == pytest.approx(2 * 0.3 + 3 * 0.49 - 0.21, abs=1e-6)

    def test_predict_before_fit_rejected(self):
        with pytest.raises(RuntimeError, match="未拟合"):
            self._make().predict({"x": 0.5, "y": 0.5})

    def test_loocv_rho_high_on_smooth_function(self):
        from rfauto.optimization.surrogate import loocv_rho

        rng = np.random.default_rng(1)
        samples = []
        for _ in range(9):
            x, y = rng.uniform(0, 1, 2)
            samples.append({"params": {"x": float(x), "y": float(y)},
                            "metrics": {"f": float(2 * x + y)}})
        result = loocv_rho(
            samples,
            cost_fn=lambda s: s["metrics"]["f"],
            surrogate_factory=self._make)
        assert result["ok"] and result["rho"] > 0.8, result

    def test_loocv_insufficient_samples(self):
        from rfauto.optimization.surrogate import loocv_rho

        samples = [{"params": {"x": 0.1}, "metrics": {"f": 1.0}}]
        result = loocv_rho(samples, cost_fn=lambda s: 1.0,
                           surrogate_factory=self._make)
        assert not result["ok"]

    def test_registry_default_registration(self):
        from rfauto.optimization.surrogate import surrogate_registry

        assert "poly_ridge" in surrogate_registry.available()


# ─── 端到端编排（fake 采样器，无需真机）────────────────────────────────────

def _recipe(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5}},
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 41},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "optimization": {"params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
            "shunt_w_mm": {"low": 0.90, "high": 1.30},
        }},
    }
    path = tmp_path / "cal_recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestCalibrateSurrogate:
    def test_end_to_end_fake_sampler_pass(self, tmp_path):
        from rfauto.service.calibration_service import calibrate_surrogate

        result = calibrate_surrogate(
            _recipe(tmp_path), sampler="fake", n_levels=3, n_validation=2)
        assert result["ok"], result.get("errors")
        assert result["verdict"] in ("PASS", "FAIL")
        assert result["n_samples"] == 9
        assert result["n_validation"] == 2
        # 产物齐全
        calib = tmp_path / "runs" / result["run_id"] / "calibration"
        for name in ("samples.json", "gate.json", "surrogate.json",
                     "report.md"):
            assert (calib / name).exists(), name
        samples = json.loads((calib / "samples.json").read_text(encoding="utf-8"))
        assert len(samples["samples"]) == 9
        gate = json.loads((calib / "gate.json").read_text(encoding="utf-8"))
        assert gate["verdict"] == result["verdict"]

    def test_missing_recipe_rejected(self, tmp_path):
        from rfauto.service.calibration_service import calibrate_surrogate

        r = calibrate_surrogate(tmp_path / "nope.yaml", sampler="fake")
        assert not r["ok"]

    def test_no_bounds_rejected(self, tmp_path):
        from rfauto.service.calibration_service import calibrate_surrogate

        path = tmp_path / "r.yaml"
        path.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "max_below", "value": -15}],
        }), encoding="utf-8")
        r = calibrate_surrogate(path, sampler="fake")
        assert not r["ok"]


class TestAugmentCalibration:
    def _seed(self, tmp_path):
        from rfauto.service.calibration_service import calibrate_surrogate

        result = calibrate_surrogate(
            _recipe(tmp_path), sampler="fake", n_levels=3, n_validation=1)
        assert result["ok"]
        seed = tmp_path / "runs" / result["run_id"] / "calibration" / "samples.json"
        return result, seed

    def test_end_to_end_fake_augment(self, tmp_path):
        from rfauto.service.calibration_service import augment_calibration

        _, seed_path = self._seed(tmp_path)
        result = augment_calibration(
            _recipe(tmp_path), seed_path, sampler="fake", n_new=4,
            n_validation=1)
        assert result["ok"], result.get("errors")
        assert result["n_seed_samples"] == 9
        assert result["n_new_points"] == 4
        assert result["n_samples"] == 13
        assert result["verdict"] in ("PASS", "FAIL")
        assert str(seed_path) == result["augmented_from"]
        calib = tmp_path / "runs" / result["run_id"] / "calibration"
        for name in ("samples.json", "gate.json", "surrogate.json",
                     "report.md"):
            assert (calib / name).exists(), name
        merged = json.loads(
            (calib / "samples.json").read_text(encoding="utf-8"))
        assert len(merged["samples"]) == 13
        assert merged["seed_sample_count"] == 9
        gate = json.loads((calib / "gate.json").read_text(encoding="utf-8"))
        assert gate["verdict"] == result["verdict"]

    def test_augment_points_far_from_seed(self, tmp_path):
        from rfauto.optimization.sample_design import np_rel
        from rfauto.service.calibration_service import _lhs_augment_points

        bounds = {"a": (18.0, 23.0), "b": (0.25, 0.45), "c": (0.9, 1.3)}
        existing = [{"a": 18.0, "b": 0.25, "c": 0.9}]
        pts = _lhs_augment_points(bounds, existing, 5, seed=3, min_dist=0.2)
        assert len(pts) == 5
        # 归一化空间最近距离 ≥ min_dist
        names = sorted(bounds)
        lo = [bounds[n][0] for n in names]
        span = [bounds[n][1] - bounds[n][0] for n in names]
        e0 = np_rel(existing[0], names, lo, span)
        for p in pts:
            pn = np_rel(p, names, lo, span)
            d = sum((pn[n] - e0[n]) ** 2 for n in names) ** 0.5
            assert d >= 0.2

    def test_missing_seed_rejected(self, tmp_path):
        from rfauto.service.calibration_service import augment_calibration

        r = augment_calibration(_recipe(tmp_path), tmp_path / "nope.json",
                                sampler="fake")
        assert not r["ok"]

    def test_bounds_mismatch_rejected(self, tmp_path):
        from rfauto.service.calibration_service import augment_calibration

        _, seed_path = self._seed(tmp_path)
        recipe = _recipe(tmp_path)
        data = yaml.safe_load(recipe.read_text(encoding="utf-8"))
        data["optimization"]["params"]["arm_len_mm"] = {"low": 10.0, "high": 30.0}
        recipe.write_text(yaml.safe_dump(data), encoding="utf-8")
        r = augment_calibration(recipe, seed_path, sampler="fake")
        assert not r["ok"]
        assert "不一致" in r["errors"][0]


class TestCompareSurrogates:
    def test_offline_ranking_on_seed_samples(self, tmp_path):
        from rfauto.service.calibration_service import calibrate_surrogate, compare_surrogates

        seed = calibrate_surrogate(
            _recipe(tmp_path), sampler="fake", n_levels=3, n_validation=0)
        assert seed["ok"]
        samples = tmp_path / "runs" / seed["run_id"] / "calibration" / "samples.json"
        r = compare_surrogates(samples)
        assert r["ok"], r.get("errors")
        assert set(r["ranking"]) <= {"poly_ridge", "nn"}
        assert r["best"] == r["ranking"][0]
        for row in r["results"]:
            assert row["n_samples"] == 9
            assert row["gate"] in ("PASS", "FAIL")

    def test_missing_samples_rejected(self, tmp_path):
        from rfauto.service.calibration_service import compare_surrogates

        assert not compare_surrogates(tmp_path / "nope.json")["ok"]
