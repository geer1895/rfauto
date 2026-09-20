"""§10.5 E3：POD-ROM 降阶代理测试（确定性、固定种子、无网络、无真机）。

覆盖：POD 基与直接 SVD 对照、满模态/截断重构误差界、能量选模、小样本退化、
注册表可见、fit/predict/metric_keys/uncertainty 接口契约、非法输入报错、
可复现性，以及既有锚数据集上 ρ 不劣于 poly_ridge 的同口径 A/B。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.optimization.surrogate import (
    PODROMSurrogate,
    PolyRidgeSurrogate,
    loocv_rho,
    pod_basis,
    surrogate_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ANCHOR_RUNS = {
    "patch": REPO_ROOT / "runs" / "20260908_122552_01847f02" / "calibration" / "samples.json",
    "wilkinson": REPO_ROOT / "runs" / "20260905_032407_e643d139" / "calibration" / "samples.json",
}


# ---- 合成语料（固定种子，全确定性） --------------------------------------
def _quadratic_scalar_samples(n: int = 18, seed: int = 11):
    """2 参数二次标量语料（无噪声，闭式可核对）。"""
    rng = np.random.default_rng(seed)
    bounds = {"x": (0.0, 1.0), "y": (0.0, 1.0)}
    samples = []
    for _ in range(n):
        x = float(rng.uniform(0.0, 1.0))
        y = float(rng.uniform(0.0, 1.0))
        samples.append({
            "params": {"x": x, "y": y},
            "metrics": {"f": float(2.0 * x + 3.0 * y * y - x * y)},
        })
    return bounds, samples


def _rank2_field_matrix(n: int = 15, length: int = 32, seed: int = 3):
    """精确秩 2 的 (n, length) 场矩阵（构造式，非随机满秩）。"""
    grid = np.linspace(0.0, 1.0, length)
    u0 = np.exp(-((grid - 0.3) / 0.1) ** 2)
    u1 = np.exp(-((grid - 0.7) / 0.12) ** 2)
    t = np.linspace(0.0, 1.0, n)
    a = np.cos(2 * np.pi * t)
    b = np.sin(2 * np.pi * t)
    a = a - a.mean()
    b = b - b.mean()
    base = 0.5 * (u0 + u1)
    return base[None, :] + a[:, None] * u0[None, :] + b[:, None] * u1[None, :]


def _curve_samples(n: int = 15, length: int = 48):
    """曲线语料：形状为参数的二次函数（order=2 回归可无损拟合）。"""
    grid = np.linspace(2.0, 3.0, length)
    c0 = np.exp(-((grid - 2.3) / 0.1) ** 2)
    c1 = np.exp(-((grid - 2.6) / 0.12) ** 2)
    samples = []
    for x in np.linspace(0.0, 1.0, n):
        coeff0 = (1.0 - x) ** 2
        coeff1 = 2.0 * x - x ** 2
        samples.append({
            "params": {"x": float(x)},
            "metrics": {"s11_curve_db": (coeff0 * c0 + coeff1 * c1).tolist()},
        })
    return {"x": (0.0, 1.0)}, samples, grid, c0, c1


# ---- 注册表 / 接口契约 ----------------------------------------------------
class TestRegistryAndInterface:
    def test_registered_and_kind(self):
        assert "pod_rom" in surrogate_registry.available()
        assert PODROMSurrogate.KIND == "pod_rom"
        model = surrogate_registry.create("pod_rom", config={"bounds": {"x": (0.0, 1.0)}})
        assert isinstance(model, PODROMSurrogate)

    def test_fit_predict_contract(self):
        bounds, samples = _quadratic_scalar_samples()
        model = PODROMSurrogate(config={"bounds": bounds})
        info = model.fit(samples)
        assert model.fitted
        assert info["n_samples"] == len(samples)
        assert info["kind"] == "pod_rom"
        assert model.metric_keys == ["f"]
        pred = model.predict({"x": 0.3, "y": 0.7})
        assert set(pred) == set(model.metric_keys)
        assert pred["f"] == pytest.approx(2 * 0.3 + 3 * 0.7 ** 2 - 0.3 * 0.7, abs=0.05)

    def test_predict_deterministic(self):
        bounds, samples = _quadratic_scalar_samples()
        m1 = PODROMSurrogate(config={"bounds": bounds})
        m2 = PODROMSurrogate(config={"bounds": bounds})
        m1.fit(samples)
        m2.fit(samples)
        p1 = m1.predict({"x": 0.61, "y": 0.19})
        p2 = m2.predict({"x": 0.61, "y": 0.19})
        assert p1 == p2  # 精确一致（同参数同输出）

    def test_uncertainty_nonnegative_and_finite(self):
        bounds, samples = _quadratic_scalar_samples()
        model = PODROMSurrogate(config={"bounds": bounds})
        model.fit(samples)
        unc = model.uncertainty({"x": 0.5, "y": 0.5})
        assert set(unc) == set(model.metric_keys)
        assert all(np.isfinite(v) and v >= 0.0 for v in unc.values())

    def test_predict_before_fit_raises(self):
        model = PODROMSurrogate(config={"bounds": {"x": (0.0, 1.0)}})
        with pytest.raises(RuntimeError, match="未拟合"):
            model.predict({"x": 0.5})

    def test_fit_empty_raises(self):
        model = PODROMSurrogate(config={"bounds": {"x": (0.0, 1.0)}})
        with pytest.raises(ValueError, match="非空"):
            model.fit([])

    def test_fit_without_bounds_raises(self):
        model = PODROMSurrogate(config={})
        with pytest.raises(ValueError, match="bounds"):
            model.fit([{"params": {"x": 0.5}, "metrics": {"f": 1.0}}])

    def test_invalid_modes_and_energy_raise(self):
        bounds, samples = _quadratic_scalar_samples()
        with pytest.raises(ValueError, match="n_modes"):
            PODROMSurrogate(config={"bounds": bounds, "n_modes": 0}).fit(samples)
        with pytest.raises(ValueError, match="energy"):
            PODROMSurrogate(config={"bounds": bounds, "energy": 0.0}).fit(samples)
        with pytest.raises(ValueError, match="energy"):
            PODROMSurrogate(config={"bounds": bounds, "energy": 1.5}).fit(samples)


# ---- POD 基 ---------------------------------------------------------------
class TestPodBasis:
    def test_full_reconstruction_machine_precision(self):
        matrix = _rank2_field_matrix()
        result = pod_basis(matrix)
        assert result["rank"] == 2
        assert result["n_modes"] == 2
        assert result["reconstruction_rmse"] < 1e-10

    def test_matches_direct_svd(self):
        matrix = _rank2_field_matrix(seed=5)
        result = pod_basis(matrix)
        centered = matrix - matrix.mean(axis=0)
        direct = np.linalg.svd(centered, full_matrices=False, compute_uv=False)
        assert np.allclose(result["singular_values"], direct[:result["n_modes"]])
        modes = result["modes"]
        assert np.allclose(modes.T @ modes, np.eye(result["n_modes"]), atol=1e-12)
        # 系数 @ 基ᵀ + 均值 与直接 SVD 重构逐元素一致
        recon = result["mean"] + result["coeffs"] @ modes.T
        assert np.allclose(recon, result["reconstruction"], atol=1e-12)

    def test_truncation_error_bound(self):
        matrix = _rank2_field_matrix()
        full = pod_basis(matrix)
        truncated = pod_basis(matrix, n_modes=1)
        assert truncated["n_modes"] == 1
        assert truncated["reconstruction_rmse"] > 0.0
        # 截断误差 = 丢弃模态的能量（第二奇异值 / sqrt(n·L)）
        expected = full["all_singular_values"][1] / np.sqrt(matrix.size)
        assert truncated["reconstruction_rmse"] == pytest.approx(expected, rel=1e-9)
        assert truncated["reconstruction_rmse"] > full["reconstruction_rmse"]

    def test_energy_selection_monotone(self):
        matrix = _rank2_field_matrix()
        rank = pod_basis(matrix)["n_modes"]
        low = pod_basis(matrix, energy=0.5)
        high = pod_basis(matrix, energy=0.999999)
        assert low["n_modes"] <= high["n_modes"] <= rank
        assert float(np.sum(high["explained_variance"])) >= 0.999999 - 1e-9

    def test_input_validation(self):
        with pytest.raises(ValueError, match="二维"):
            pod_basis([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="非空"):
            pod_basis(np.empty((0, 3)))
        with pytest.raises(ValueError, match="非有限"):
            pod_basis([[1.0, np.nan], [2.0, 3.0]])
        with pytest.raises(ValueError, match="n_modes"):
            pod_basis(_rank2_field_matrix(), n_modes=0)
        with pytest.raises(ValueError, match="energy"):
            pod_basis(_rank2_field_matrix(), energy=0.0)


# ---- 场/曲线本体 ----------------------------------------------------------
class TestFieldModel:
    def test_curve_field_prediction_recovers_truth(self):
        bounds, samples, grid, c0, c1 = _curve_samples()
        model = PODROMSurrogate(config={"bounds": bounds, "ridge_lambda": 0.0})
        info = model.fit(samples)
        assert info["field_keys"] == ["s11_curve_db"]
        assert info["reconstruction_rmse"]["s11_curve_db"] < 1e-9
        assert model.metric_keys == []  # 纯曲线语料无标量键
        assert model.predict({"x": 0.5}) == {}

        x = 0.7
        out = model.predict_field("s11_curve_db", {"x": x})
        truth = ((1 - x) ** 2) * c0 + (2 * x - x ** 2) * c1
        assert len(out["values"]) == len(grid)
        assert np.allclose(out["values"], truth, atol=1e-6)

    def test_small_sample_degenerates_to_mean_field(self):
        _, samples, _, _, _ = _curve_samples(n=1)
        model = PODROMSurrogate(config={"bounds": {"x": (0.0, 1.0)}})
        info = model.fit(samples)
        assert info["n_modes"]["s11_curve_db"] == 0
        out = model.predict_field("s11_curve_db", {"x": 0.42})
        assert np.allclose(out["values"], samples[0]["metrics"]["s11_curve_db"], atol=1e-12)

    def test_explicit_missing_or_ragged_field_raises(self):
        bounds, samples, _, _, _ = _curve_samples()
        with pytest.raises(ValueError, match="field_metrics"):
            PODROMSurrogate(config={"bounds": bounds, "field_metrics": ["nope"]}).fit(samples)
        ragged = json.loads(json.dumps(samples))
        ragged[1]["metrics"]["s11_curve_db"] = ragged[1]["metrics"]["s11_curve_db"][:-1]
        with pytest.raises(ValueError, match="长度不一致"):
            PODROMSurrogate(config={"bounds": bounds,
                                    "field_metrics": ["s11_curve_db"]}).fit(ragged)

    def test_unknown_field_key_raises(self):
        bounds, samples, _, _, _ = _curve_samples()
        model = PODROMSurrogate(config={"bounds": bounds})
        model.fit(samples)
        with pytest.raises(KeyError, match="未建模"):
            model.predict_field("no_such_field", {"x": 0.5})


# ---- 同接口 A/B：标量退化等价 + 锚数据集 ρ --------------------------------
class TestABAgainstPolyRidge:
    def test_scalar_path_equals_poly_ridge(self):
        bounds, samples = _quadratic_scalar_samples(seed=21)
        ridge = PolyRidgeSurrogate(config={"bounds": bounds, "order": 2, "ridge_lambda": 0.1})
        pod = PODROMSurrogate(config={"bounds": bounds, "order": 2, "ridge_lambda": 0.1})
        ridge.fit(samples)
        pod.fit(samples)
        for s in samples[:5]:
            r = ridge.predict(s["params"])
            p = pod.predict(s["params"])
            assert p["f"] == pytest.approx(r["f"], abs=1e-12)

    def test_compare_surrogates_same_interface(self, tmp_path):
        from rfauto.service.calibration_service import compare_surrogates

        bounds = {"x": (0.0, 1.0), "y": (0.0, 1.0)}
        samples = []
        for i in range(16):
            x = i / 15.0
            y = ((i * 7) % 16) / 15.0
            samples.append({
                "params": {"x": x, "y": y},
                "metrics": {"s11_db_max_in_band": float(-20.0 + 8.0 * x + 3.0 * y)},
            })
        data = {
            "bounds": bounds,
            "objectives": [{"metric": "s11_db", "band": [1.0, 2.0],
                            "op": "max_below", "value": -12.0}],
            "samples": samples,
        }
        path = tmp_path / "samples.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = compare_surrogates(path, kinds=("poly_ridge", "pod_rom"))
        assert result["ok"], result
        rows = {r["kind"]: r for r in result["results"]}
        assert rows["pod_rom"]["ok"] and rows["poly_ridge"]["ok"]
        assert rows["pod_rom"]["rho"] == pytest.approx(rows["poly_ridge"]["rho"], abs=1e-9)
        assert "pod_rom" in result["ranking"]

    @pytest.mark.parametrize("name", sorted(ANCHOR_RUNS))
    def test_anchor_rho_not_worse_than_poly_ridge(self, name):
        path = ANCHOR_RUNS[name]
        if not path.exists():
            pytest.skip(f"锚数据集不可得: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        samples = data["samples"]
        bounds = {k: (float(v[0]), float(v[1])) for k, v in data["bounds"].items()}
        objectives = data["objectives"]

        from rfauto.core.objectives import Objective, SpecEvaluator

        objs = [Objective(**o) for o in objectives]

        def cost(sample):
            return SpecEvaluator.evaluate_objectives(sample["metrics"], objs)

        r_ridge = loocv_rho(samples, cost, lambda: PolyRidgeSurrogate(
            config={"bounds": bounds, "order": 2, "ridge_lambda": 0.1}))
        r_pod = loocv_rho(samples, cost, lambda: PODROMSurrogate(
            config={"bounds": bounds, "order": 2, "ridge_lambda": 0.1}))
        assert r_ridge["ok"], r_ridge
        assert r_pod["ok"], r_pod
        assert r_pod["rho"] >= r_ridge["rho"] - 1e-9, (r_ridge, r_pod)
