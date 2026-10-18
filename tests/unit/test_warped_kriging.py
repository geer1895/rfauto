"""EC-16 warped_kriging 单测：Kumaraswamy 扭曲 + 确定性 GP（全离线零真机）。

合成裁判验收口径（ecosystem §二 EC-16 原文"#207 合成裁判验收"）：
已知闭式真值函数 f(x)=√x（陡峭近 0，GP 在自然空间分辨率不足、√warp 后
线性可精确插值）——恒等 warp vs √warp 的 NRMSE 对照即 #118 双源（函数
闭式本身即真值源，GP 预测为被测源）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.optimization.surrogate import surrogate_registry
from rfauto.optimization.surrogate.warped_kriging import (
    WarpedKrigingSurrogate,
    kumaraswamy_warp,
    kumaraswamy_warp_inverse,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


class TestKumaraswamyWarp:
    def test_monotone_bijection_and_inverse(self):
        """单调满射 + 解析逆逐点可逆（无需求根，闭式对拍闭式）。"""
        for a, b in ((1.0, 1.0), (1.0, 0.5), (0.5, 1.0), (2.0, 3.0)):
            xs = np.linspace(0.0, 1.0, 101)
            w = kumaraswamy_warp(xs, a=a, b=b)
            assert np.all(np.diff(w) > 0), (a, b)
            assert w[0] == pytest.approx(0.0, abs=1e-14)
            assert w[-1] == pytest.approx(1.0, abs=1e-14)
            inv = kumaraswamy_warp_inverse(w, a=a, b=b)
            assert np.max(np.abs(inv - xs)) < 1e-12, (a, b)

    def test_identity_params(self):
        xs = np.linspace(0.0, 1.0, 9)
        assert np.allclose(kumaraswamy_warp(xs, 1.0, 1.0), xs)

    def test_sqrt_warp_known_values(self):
        """(a,b)=(1,0.5) ⇒ F(x)=√x（手工闭式对拍）。"""
        xs = np.array([0.04, 0.25, 0.81])
        np.testing.assert_allclose(
            kumaraswamy_warp(xs, 1.0, 0.5), np.sqrt(xs), rtol=1e-14)


class TestWarpedKrigingBenchmark:
    @staticmethod
    def _samples(n: int = 14, seed: int = 7) -> list[dict]:
        rng = np.random.default_rng(seed)
        return [{"params": {"x": float(u)},
                 "metrics": {"f": float(np.sqrt(u))}}
                for u in rng.uniform(0.001, 1.0, n)]

    @staticmethod
    def _nrmse(model) -> float:
        grid = np.linspace(0.001, 1.0, 200)
        pred = np.array([model.predict({"x": float(g)})["f"] for g in grid])
        tru = np.sqrt(grid)
        return float(np.sqrt(np.mean((pred - tru) ** 2))
                     / np.sqrt(np.mean(tru ** 2)))

    def test_registered(self):
        assert "warped_kriging" in surrogate_registry.available()

    def test_warp_improves_steep_function_recovery(self):
        """合成裁判：√warp 后 f 线性 ⇒ NRMSE 较恒等 warp 显著改善。"""
        samples = self._samples()
        m_id = WarpedKrigingSurrogate(config={"bounds": {"x": (0.0, 1.0)}})
        m_id.fit(samples)
        m_wp = WarpedKrigingSurrogate(config={
            "bounds": {"x": (0.0, 1.0)}, "warp": {"x": (1.0, 0.5)}})
        m_wp.fit(samples)
        n_id, n_wp = self._nrmse(m_id), self._nrmse(m_wp)
        assert n_wp < 1e-3  # 扭曲空间内线性面近精确回收
        assert n_wp < n_id / 5.0  # 较恒等 warp 显著优势

    def test_deterministic_and_bounds_clipped(self):
        """同数据同结果（C4）+ 域外参数按单元化口径截断。"""
        samples = self._samples()
        cfg = {"bounds": {"x": (0.0, 1.0)}, "warp": {"x": (1.0, 0.5)}}
        m1, m2 = WarpedKrigingSurrogate(config=cfg), WarpedKrigingSurrogate(
            config=cfg)
        m1.fit(samples)
        m2.fit(samples)
        p = {"x": 0.42}
        assert m1.predict(p) == m2.predict(p)
        assert m1.uncertainty(p) == m2.uncertainty(p)
        # 域外截断：-1 与 0 同测、2 与 1 同测（截断后预测逐位一致）
        assert m1.predict({"x": -1.0})["f"] == m1.predict({"x": 0.0})["f"]
        assert m1.predict({"x": 2.0})["f"] == m1.predict({"x": 1.0})["f"]

    def test_skips_sparse_metric_keys(self):
        """有效点 <3 的指标键跳过不硬拟（同 smt_kriging 约定）。"""
        samples = self._samples()
        samples[0]["metrics"]["sparse_key"] = 1.0  # 仅 1 个有效点
        m = WarpedKrigingSurrogate(config={"bounds": {"x": (0.0, 1.0)}})
        m.fit(samples)
        assert "f" in m.models
        assert "sparse_key" not in m.models
