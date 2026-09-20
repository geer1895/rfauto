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
