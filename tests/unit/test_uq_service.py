"""阶段 6.4：代理免费蒙特卡洛 UQ 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def samples_path(tmp_path):
    """合成数据集：s11 指标 = -20 + 5*(L-20)^2 + 10*(w-0.35)^2（二次可拟合）。

    最优点在 L=20, w=0.35，指标 -20dB（远优于 -15 规格）→ 良率应接近 1。
    """
    rng = np.random.default_rng(7)
    bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
    samples = []
    for _ in range(25):
        L = float(rng.uniform(*bounds["arm_len_mm"]))
        w = float(rng.uniform(*bounds["series_w_mm"]))
        s11 = -20.0 + 5.0 * (L - 20.0) ** 2 + 10.0 * (w - 0.35) ** 2
        samples.append({
            "params": {"arm_len_mm": L, "series_w_mm": w},
            "metrics": {"s11_db_max_in_band": float(s11),
                        "s21_db_mean_in_band": -3.3},
        })
    # 保证最优点在数据集里（名义点附近）
    samples[0]["params"] = {"arm_len_mm": 20.0, "series_w_mm": 0.35}
    samples[0]["metrics"] = {"s11_db_max_in_band": -20.0,
                             "s21_db_mean_in_band": -3.3}
    data = {
        "bounds": bounds,
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "samples": samples,
    }
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestSurrogateYield:
    def test_high_yield_near_optimum(self, samples_path):
        from rfauto.service.uq_service import surrogate_yield

        r = surrogate_yield(samples_path, {"arm_len_mm": 0.1, "series_w_mm": 0.02},
                            n=2000, seed=1)
        assert r["ok"], r.get("errors")
        assert r["nominal_params"]["arm_len_mm"] == pytest.approx(20.0)
        assert r["yield_rate"] > 0.90  # 最优点余量大 → 良率高

    def test_worse_nominal_lower_yield(self, samples_path):
        """把名义点指标调差 → 良率应下降（方向性验证）。"""
        from rfauto.service.uq_service import surrogate_yield

        data = json.loads(Path(samples_path).read_text(encoding="utf-8"))
        data["objectives"][0]["value"] = -19.9  # 收紧到 σ 扰动会踩线的程度
        tight = Path(samples_path).parent / "tight.json"
        tight.write_text(json.dumps(data), encoding="utf-8")
        kw = {"ridge_lambda": 1e-6}  # 近无正则：二次面精确复现
        r_loose = surrogate_yield(samples_path, {"arm_len_mm": 0.1}, n=2000,
                                  seed=1, **kw)
        r_tight = surrogate_yield(tight, {"arm_len_mm": 0.1}, n=2000,
                                  seed=1, **kw)
        assert r_tight["yield_rate"] < r_loose["yield_rate"]

    def test_sensitivity_ranks_active_param_first(self, samples_path):
        from rfauto.service.uq_service import surrogate_yield

        # 数据模型里 w 的曲率是 L 的 2 倍 → 同 σ 下 w 更敏感
        r = surrogate_yield(samples_path, {"arm_len_mm": 0.05, "series_w_mm": 0.05},
                            n=1000, seed=2)
        assert r["ok"]
        assert r["sensitivity_ranking"][0] == "series_w_mm"
        assert r["metric_stats"]["s11_db_max_in_band"]["std"] > 0

    def test_bad_tolerances_rejected(self, samples_path):
        from rfauto.service.uq_service import surrogate_yield

        r = surrogate_yield(samples_path, {"nope_mm": 0.1})
        assert not r["ok"]
        r2 = surrogate_yield(samples_path, {})
        assert not r2["ok"]


class TestSpreadSkill:
    """DP-13 R1：spread-skill 总闸（σ-|误差| 秩相关门 ρ≥0.5，预声明）。

    裁判先过已知基准（#118）：σ∝|噪声| 合成 → 过门；随机 σ → 不过门。
    """

    def test_synthetic_recovery_sigma_proportional_passes(self):
        from rfauto.service.uq_service import spread_skill

        rng = np.random.default_rng(11)
        eps = rng.normal(0.0, 1.0, 30)
        pairs = [(0.1 + 0.5 * abs(e), abs(e)) for e in eps]
        r = spread_skill(pairs)
        assert r["status"] == "quantitative"
        assert r["spearman_rho"] >= 0.999
        assert r["ok"] is True and r["n_pairs"] == 30

    def test_random_sigma_fails_gate(self):
        from rfauto.service.uq_service import SPREAD_SKILL_GATE, spread_skill

        rng = np.random.default_rng(3)
        eps = rng.normal(0.0, 1.0, 40)
        sigma = rng.uniform(0.1, 1.0, 40)  # 与误差独立
        r = spread_skill(list(zip(sigma.tolist(), np.abs(eps).tolist(),
                                  strict=True)))
        assert r["status"] == "qualitative"
        assert r["ok"] is False and r["spearman_rho"] < SPREAD_SKILL_GATE
        # 数据不删：对数如实保留
        assert r["n_pairs"] == 40

    def test_degenerate_cases_honest_qualitative(self):
        from rfauto.service.uq_service import spread_skill

        r2 = spread_skill([(0.5, 0.1), (0.3, 0.2)])
        assert r2["status"] == "qualitative" and r2["ok"] is False
        assert r2["spearman_rho"] is None and r2["n_pairs"] == 2
        const_sigma = [(0.5, float(e)) for e in (0.1, 0.4, 0.9, 0.2)]
        rc = spread_skill(const_sigma)
        assert rc["status"] == "qualitative" and "离散度" in rc["reason"]
        # 退化输入与门无关：恒 σ 时 ρ 不存在，gate=-1 也如实 qualitative
        assert spread_skill(const_sigma, gate=-1.0)["status"] == "qualitative"
        # gate 参数化（非退化对）：ρ 严格介于 (−1,1) 时门上下调决定状态
        rng2 = np.random.default_rng(5)
        eps2 = rng2.normal(0.0, 1.0, 40)
        mixed = [(abs(e) + 0.3 * rng2.normal(), abs(e)) for e in eps2]
        rho = spread_skill(mixed)["spearman_rho"]
        assert -1.0 < rho < 1.0
        assert spread_skill(mixed, gate=2.0)["status"] == "qualitative"
        assert spread_skill(mixed, gate=-1.0)["status"] == "quantitative"

    def test_uq_output_carries_status_qualitative_without_sigma(
            self, samples_path):
        """poly_ridge（uncertainty→None）→ qualitative 降级标注，数据不删。"""
        from rfauto.service.uq_service import surrogate_yield

        r = surrogate_yield(samples_path, {"arm_len_mm": 0.1}, n=500, seed=1)
        assert r["ok"]
        st = r["uncertainty_status"]
        assert st["status"] == "qualitative" and st["ok"] is False
        assert st["spearman_rho"] is None
        assert "uncertainty" in st["reason"]
        # 数据不删：良率/统计等既有键原样在
        assert "yield_rate" in r and "metric_stats" in r

    def test_uq_output_quantitative_with_sigma_model(
            self, samples_path, monkeypatch):
        """代理提供真 σ 且 σ∝|误差| → quantitative（合成回收全链路）。"""

        class _SigmaStub:
            KIND = "sigma_stub"

            def __init__(self, **kw):
                pass

            @staticmethod
            def _truth(params):
                return -20.0 + 5.0 * (float(params["arm_len_mm"]) - 20.0) ** 2 \
                    + 10.0 * (float(params["series_w_mm"]) - 0.35) ** 2

            @staticmethod
            def _err(params):
                return 0.1 * (float(params["arm_len_mm"]) - 20.0)

            def fit(self, samples):
                return {"n_samples": len(samples)}

            def predict(self, params):
                return {"s11_db_max_in_band": self._truth(params)
                        + self._err(params),
                        "s21_db_mean_in_band": -3.3}

            def uncertainty(self, params):
                return {"s11_db_max_in_band": abs(self._err(params))}

        monkeypatch.setattr(
            "rfauto.service.calibration_service._make_model",
            lambda kind, bounds, **kw: _SigmaStub())
        from rfauto.service.uq_service import surrogate_yield

        r = surrogate_yield(samples_path, {"arm_len_mm": 0.1}, n=500, seed=1)
        assert r["ok"]
        st = r["uncertainty_status"]
        assert st["status"] == "quantitative"
        assert st["spearman_rho"] >= 0.999
        assert "yield_rate" in r  # 数据不删
