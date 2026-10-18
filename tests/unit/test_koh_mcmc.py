"""XD-12 KOHMCMCPosterior 单测：固定 seed MH 后验（全离线零真机）。

合成基准（已知真值回收，#118 双源）：η、δ、ρ 均为闭式构造——
ρ 后验覆盖真值、u95 区间覆盖真 z（后验混合 predictive）、链逐位可复现
（C4）+ seed 敏感。KOHCalibrator 既有契约回归由 test_koh_service.py
原样覆盖（本文件零改动其断言面）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.service.koh_service import KOHCalibrator, KOHMCMCPosterior

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

RHO_TRUE = 1.4


def _eta(x: float) -> float:
    return 2.0 + 3.0 * x


def _eta_fn(params: dict[str, float]) -> float:
    return _eta(params["x"])


def _delta(x: float) -> float:
    return 0.5 * np.cos(2 * np.pi * x)  # 关于 x=0.5 偶对称 → 与 η 不共线


def _observations(n: int = 22, seed: int = 3) -> list[dict]:
    rng = np.random.default_rng(seed)
    xs = np.sort(rng.uniform(0.0, 1.0, n))
    return [{"params": {"x": float(x)},
             "eta": _eta(x),
             "y": RHO_TRUE * _eta(x) + _delta(x)}
            for x in xs]


@pytest.fixture()
def model() -> KOHMCMCPosterior:
    m = KOHMCMCPosterior(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_fn,
                         n_samples=300, burn=200, thin=2)
    r = m.fit(_observations())
    assert r["ok"], r.get("errors")
    return m


class TestKohMcmc:
    def test_rho_posterior_covers_truth(self, model):
        """ρ 后验均值贴近真值且 95% 区间覆盖真值（全贝叶斯核心语义）。"""
        s = model.samples_[:, 0]
        assert abs(float(s.mean()) - RHO_TRUE) < 0.15
        lo, hi = np.percentile(s, 2.5), np.percentile(s, 97.5)
        assert lo <= RHO_TRUE <= hi

    def test_u95_coverage_on_heldout(self, model):
        """u95 区间覆盖真 z：留出 5 点全中（噪声less 插值域内）。"""
        for x in (0.12, 0.38, 0.55, 0.77, 0.93):
            z_true = RHO_TRUE * _eta(x) + _delta(x)
            p = model.predict({"x": x})
            assert p["lo95"] <= z_true <= p["hi95"]
            assert abs(p["mean"] - z_true) < 0.05  # 点估计亦准

    def test_deterministic_seed_sensitivity(self):
        """同 seed 链逐位相同（C4）；不同 seed 链不同。"""
        obs = _observations()
        m1 = KOHMCMCPosterior(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_fn,
                              n_samples=150, burn=100, thin=2)
        m2 = KOHMCMCPosterior(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_fn,
                              n_samples=150, burn=100, thin=2)
        m1.fit(obs)
        m2.fit(obs)
        assert np.array_equal(m1.samples_, m2.samples_)
        m3 = KOHMCMCPosterior(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_fn,
                              n_samples=150, burn=100, thin=2, seed=99)
        m3.fit(obs)
        assert not np.array_equal(m1.samples_, m3.samples_)

    def test_contract_and_empirical_stamp(self, model):
        """返回契约键 + empirical 戳 + 预测 u95 消费面键。"""
        r = model.fit(_observations())
        for key in ("ok", "kind", "n_obs", "seed", "n_samples", "burn",
                    "thin", "accept_rate", "rho", "empirical", "note"):
            assert key in r
        assert r["kind"] == "koh_mcmc"
        assert r["empirical"] is True  # MCMC=经验近似档，如实标注
        assert 0.0 < r["accept_rate"] < 1.0
        p = model.predict({"x": 0.5})
        for key in ("mean", "lo95", "hi95", "sigma", "u95", "eta", "delta",
                    "rho"):
            assert key in p
        assert p["u95"] == [p["lo95"], p["hi95"]]
        assert p["lo95"] < p["mean"] < p["hi95"]

    def test_rejects_insufficient_observations(self):
        m = KOHMCMCPosterior(bounds={"x": (0.0, 1.0)})
        assert not m.fit([{"params": {"x": 0.5}, "eta": 1.0,
                           "y": 1.0}])["ok"]

    def test_koh_calibrator_untouched_surface(self):
        """既有 KOHCalibrator 构造/预测面原样可用（零破坏旁证；全量回归
        由 test_koh_service.py 原样承担）。"""
        cal = KOHCalibrator(bounds={"x": (0.0, 1.0)}, eta_fn=_eta_fn)
        r = cal.fit(_observations())
        assert r["ok"] and cal.fitted
        p = cal.predict({"x": 0.5})
        assert {"mean", "lo95", "hi95", "sigma"} <= set(p)
