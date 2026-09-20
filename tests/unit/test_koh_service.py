"""阶段 6.1：KOH discrepancy GP（首片 + D10 完整 KOH）测试（零真机、零网络）。"""

from __future__ import annotations

import json

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def samples_path(tmp_path):
    """openEMS"真采样"集：指标带已知结构，discrepancy 可检验。"""
    bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
    samples = []
    for L in (18.5, 19.5, 20.5, 21.5, 22.5):
        for w in (0.3, 0.4):
            p = {"arm_len_mm": L, "series_w_mm": w}
            samples.append({
                "params": p,
                "metrics": {"s11_db_max_in_band":
                            float(-18.0 + (L - 20.5) ** 2 + 4 * (w - 0.35) ** 2)},
            })
    data = {
        "bounds": bounds,
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "samples": samples,
    }
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestFitDiscrepancy:
    def test_constant_offset_detected(self, samples_path):
        """fake 与真采样恒差 +2dB → δ(x)=real−fake 均值应接近 −2
        （KOH 口径：正 δ=仿真器低估观测；fake 偏浅 → 负 δ）。"""
        from rfauto.service.koh_service import fit_discrepancy

        def fake_sampler(params):
            L, w = params["arm_len_mm"], params["series_w_mm"]
            return {"s11_db_max_in_band":
                    -16.0 + (L - 20.5) ** 2 + 4 * (w - 0.35) ** 2}

        r = fit_discrepancy(samples_path, fake_sampler=fake_sampler,
                            n_extra_fake=6)
        assert r["ok"], r.get("errors")
        assert r["gp_fitted"]
        d = r["delta_summary"]["s11_db_max_in_band"]
        assert d["mean"] == pytest.approx(-2.0, abs=0.5)  # real − fake = −2
        assert "real−fake" in r["note"]

    def test_missing_samples_rejected(self, tmp_path):
        from rfauto.service.koh_service import fit_discrepancy

        assert not fit_discrepancy(tmp_path / "nope.json")["ok"]

    def test_return_contract_keys_unchanged(self, samples_path):
        """D10 补强向后兼容：既有返回键与语义一个不少。"""
        from rfauto.service.koh_service import fit_discrepancy

        def fake_sampler(params):
            return {"s11_db_max_in_band": -18.0 + 2.0}

        r = fit_discrepancy(samples_path, fake_sampler=fake_sampler,
                            n_extra_fake=6)
        assert r["ok"], r.get("errors")
        for key in ("ok", "samples_path", "model", "n_pairs", "metric_keys",
                    "delta_summary", "model_kind", "gp_fitted", "note"):
            assert key in r
        assert r["model_kind"] == "smt_kriging"
        assert r["metric_keys"] == ["s11_db_max_in_band"]
        assert set(r["delta_summary"]["s11_db_max_in_band"]) == {
            "min", "max", "mean"}

    def test_delta_convention_stamp(self, samples_path):
        """P2⑩ 机器可读口径戳：real−fake + 切换时点，note 区分
        fit_discrepancy 翻转与 KOHCalibrator 恒定口径两条路径。"""
        from rfauto.service.koh_service import (
            DELTA_CONVENTION,
            DELTA_CONVENTION_SINCE,
            fit_discrepancy,
        )

        def fake_sampler(params):
            return {"s11_db_max_in_band": -18.0 + 2.0}

        r = fit_discrepancy(samples_path, fake_sampler=fake_sampler,
                            n_extra_fake=6)
        assert r["ok"], r.get("errors")
        assert r["delta_convention"] == DELTA_CONVENTION == "real_minus_fake"
        assert "2026-09-13" in r["delta_convention_since"]
        assert r["delta_convention_since"] == DELTA_CONVENTION_SINCE
        assert "fit_discrepancy" in r["note"]
        assert "KOHCalibrator" in r["note"]
        assert "反号" in r["note"]


# --------------------------------------------------------------------------- #
# D10 完整 KOH：z(x) = ρ·η(x) + δ(x) + ε
# --------------------------------------------------------------------------- #

def _eta(xv):
    return 2.0 + 3.0 * xv


def _delta_true(xv):
    return 0.5 * np.cos(2 * np.pi * xv)  # 关于 x=0.5 偶对称 → 与 η 不共线


def _eta_params(params):
    return _eta(params["x"])


def _observations(rho_true=1.5, n=13, lo=0.1, hi=0.9, noise=0.0, seed=7):
    rng = np.random.default_rng(seed)
    obs = []
    for xv in np.linspace(lo, hi, n):
        y = rho_true * _eta(xv) + _delta_true(xv)
        if noise:
            y += float(rng.normal(0.0, noise))
        obs.append({"params": {"x": float(xv)}, "eta": float(_eta(xv)),
                    "y": float(y)})
    return obs


def _truth(xv, rho_true=1.5):
    return rho_true * _eta(xv) + _delta_true(xv)


class TestEstimateRho:
    def test_ols_slope_recovers_known_rho(self):
        from rfauto.service.koh_service import estimate_rho

        x = np.linspace(0.1, 0.9, 17)
        assert estimate_rho(_eta(x), 1.5 * _eta(x) + _delta_true(x)) ==             pytest.approx(1.5, abs=1e-6)

    def test_constant_eta_falls_back_to_mean_ratio(self):
        from rfauto.service.koh_service import estimate_rho

        assert estimate_rho([4.0] * 5, [10.0, 10.1, 10.2, 10.3, 10.4]) ==             pytest.approx(2.55, abs=1e-9)

    def test_too_few_points_is_neutral(self):
        from rfauto.service.koh_service import estimate_rho

        assert estimate_rho([1.0], [9.0]) == 1.0


class TestKOHCalibrator:
    def test_rho_recovered_from_synthetic(self):
        """合成已知 ρ=1.5（η 随 x 变、δ 与 η 正交）→ ρ 可恢复。"""
        from rfauto.service.koh_service import KOHCalibrator

        model = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params)
        info = model.fit(_observations())
        assert info["ok"], info.get("errors")
        assert info["gp_fitted"] is True       # ≥3 点走 SMT KRG 路径
        assert info["rho"] == pytest.approx(1.5, abs=0.05)

    def test_interval_ordered_and_contains_truth(self):
        from rfauto.service.koh_service import KOHCalibrator

        model = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params)
        model.fit(_observations())
        pred = model.predict({"x": 0.42})       # 非训练点
        assert pred["lo95"] <= pred["mean"] <= pred["hi95"]
        assert pred["lo95"] <= _truth(0.42) <= pred["hi95"]
        assert pred["sigma"] > 0.0

    def test_interval_widens_away_from_training(self):
        from rfauto.service.koh_service import KOHCalibrator

        model = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params)
        model.fit(_observations(n=5, lo=0.4, hi=0.6))
        w_near = (lambda p: p["hi95"] - p["lo95"])(model.predict({"x": 0.5}))
        w_far = (lambda p: p["hi95"] - p["lo95"])(model.predict({"x": 0.0}))
        assert w_far > w_near
        assert w_far > 0.0

    def test_coverage_reasonable_and_contains_truth(self):
        """无噪声合成 δ：全带 95% 区间应覆盖真值；带噪声版本覆盖率合理。"""
        from rfauto.service.koh_service import KOHCalibrator

        grid = np.linspace(0.0, 1.0, 101)
        points = [{"params": {"x": float(xv)}, "y": float(_truth(xv))}
                  for xv in grid]

        clean = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params)
        clean.fit(_observations())
        cov_clean = clean.interval_coverage(points)
        assert cov_clean["n"] == 101
        assert cov_clean["coverage"] >= 0.95   # 确定性 δ：真值必须落在区间内

        noisy = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params,
                              noise_var=0.05 ** 2)
        noisy.fit(_observations(n=25, noise=0.05))
        cov_noisy = noisy.interval_coverage(points)
        assert cov_noisy["n"] == 101
        assert 0.8 <= cov_noisy["coverage"] <= 1.0  # 固定种子实测 ≈0.90

    def test_noise_var_widens_interval(self):
        from rfauto.service.koh_service import KOHCalibrator

        obs = _observations()
        plain = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params)
        plain.fit(obs)
        noisy = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params,
                              noise_var=0.25)
        noisy.fit(obs)
        w0 = plain.predict({"x": 0.42})
        w1 = noisy.predict({"x": 0.42})
        assert (w1["hi95"] - w1["lo95"]) > (w0["hi95"] - w0["lo95"])

    def test_two_points_use_documented_fallback(self):
        """ratrace 场景（仅 2 个网格档）：不假装有 GP，区间由先验宽度主导。"""
        from rfauto.service.koh_service import KOHCalibrator

        obs = [
            {"params": {"mesh_mm": 0.4}, "eta": 1.0975, "y": 1.14943},
            {"params": {"mesh_mm": 0.2}, "eta": 1.0975, "y": 1.05992},
        ]
        model = KOHCalibrator(bounds={"mesh_mm": (0.1, 0.5)},
                              eta_fn=lambda p: 1.0975)
        info = model.fit(obs)
        assert info["ok"], info.get("errors")
        assert info["gp_fitted"] is False       # 2 点 < min_gp_points
        pred = model.predict({"mesh_mm": 0.4})
        assert pred["lo95"] <= pred["mean"] <= pred["hi95"]
        assert pred["hi95"] - pred["lo95"] > 0.1  # 先验主导 → 宽区间
        assert pred["mean"] == pytest.approx(1.14943, abs=1e-6)

    def test_predict_before_fit_raises(self):
        from rfauto.service.koh_service import KOHCalibrator

        model = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params)
        with pytest.raises(RuntimeError):
            model.predict({"x": 0.5})

    def test_missing_eta_source_raises(self):
        from rfauto.service.koh_service import KOHCalibrator

        model = KOHCalibrator(bounds={"x": (0.0, 1.0)})
        model.fit(_observations())
        with pytest.raises(ValueError):
            model.predict({"x": 0.5})
        assert model.predict({"x": 0.5}, eta=0.0)["eta"] == 0.0

    def test_fit_rejects_insufficient_or_nonfinite(self):
        from rfauto.service.koh_service import KOHCalibrator

        model = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params)
        assert model.fit([])["ok"] is False
        obs = [
            *_observations()[:4],
            {"params": {"x": 0.95}, "eta": float("nan"), "y": 1.0},
            {"params": {"x": 0.96}, "eta": 1.0, "y": float("inf")},
        ]
        info = model.fit(obs)
        assert info["ok"] is True
        assert info["n_obs"] == 4               # NaN/inf 条目被忽略

    def test_empty_bounds_rejected(self):
        from rfauto.service.koh_service import KOHCalibrator

        with pytest.raises(ValueError):
            KOHCalibrator(bounds={})

    def test_coverage_ignores_invalid_points(self):
        from rfauto.service.koh_service import KOHCalibrator

        model = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params)
        model.fit(_observations())
        report = model.interval_coverage([
            {"params": {"x": 0.5}, "y": _truth(0.5)},
            {"params": {"x": 0.6}},                  # 缺 y → 跳过
            {"params": {"x": 0.7}, "y": float("nan")},
            "not-a-dict",
        ])
        assert report["n"] == 1 and report["covered"] == 1
        assert model.interval_coverage([])["coverage"] is None

    def test_coverage_skips_missing_eta_points_and_counts(self):
        """缺 eta 且无 eta_fn 的点：逐点跳过并计数 n_skipped_no_eta，
        不炸穿整批统计（其余点照常计入 n/covered）。"""
        from rfauto.service.koh_service import KOHCalibrator

        model = KOHCalibrator(bounds={"x": (0.0, 1.0)})   # 无 eta_fn
        model.fit(_observations())
        report = model.interval_coverage([
            {"params": {"x": 0.5}, "y": _truth(0.5), "eta": _eta(0.5)},
            {"params": {"x": 0.6}, "y": _truth(0.6)},          # 缺 eta → 跳过计数
            {"params": {"x": 0.7}, "y": _truth(0.7)},          # 缺 eta → 跳过计数
        ])
        assert report["n"] == 1 and report["covered"] == 1
        assert report["n_skipped_no_eta"] == 2
        # eta 缺省但构造时有 eta_fn：不受影响（eta_fn 补齐）
        model_fn = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_params)
        model_fn.fit(_observations())
        report_fn = model_fn.interval_coverage([
            {"params": {"x": 0.5}, "y": _truth(0.5)},
        ])
        assert report_fn["n"] == 1 and report_fn["n_skipped_no_eta"] == 0
