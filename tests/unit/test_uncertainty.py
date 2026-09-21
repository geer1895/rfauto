"""B5 不确定度终止判据单测：gp_cost_sigma 内核 + 环内 opt-in 行为。

锚点（零回归纪律）：
- tol=None（缺省）时 run_surrogate_loop 结果字典与不加参数逐字节一致——
  新代码路径零触发；
- σ 序列同 seed 逐位一致（确定性内核纪律）；
- uncertainty.py 分层 lint：optimization 禁 import service（import-linter
  layers 契约），内核是移植不是引用。
"""

from __future__ import annotations

import ast
import math
import sys
from pathlib import Path

import numpy as np
import pytest

# 确保 src 在 path 中（同 test_optimization 模式）
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.core.objectives import MetricOp, Objective
from rfauto.optimization.sample_design import lhs_points
from rfauto.optimization.surrogate_loop import run_surrogate_loop
from rfauto.optimization.uncertainty import gp_cost_sigma

BOUNDS_2D = {"x_mm": (0.0, 1.0), "y_mm": (0.0, 1.0)}
X_STAR, Y_STAR = 0.30, 0.62

OBJS_2D = [Objective(metric="s11_db_min", band=[2.3, 2.5],
                     op=MetricOp.MAX_BELOW, value=-47.0, weight=1.0)]


def bowl_metrics(params: dict[str, float]) -> dict[str, float]:
    """平滑耦合碗（同 test_surrogate_loop 裁判面，确定性零真机）。"""
    dx = params["x_mm"] - X_STAR
    dy = params["y_mm"] - Y_STAR
    depth = -46.0 + 180.0 * dx * dx + 150.0 * dy * dy - 120.0 * dx * dy
    depth += 1.5 * math.sin(3.0 * math.pi * params["x_mm"]) * \
        math.sin(3.0 * math.pi * params["y_mm"])
    return {"s11_db_min_in_band": depth}


# ─── gp_cost_sigma 内核 ──────────────────────────────────────────────────────

class TestGpCostSigma:
    def test_output_shape_and_finite(self):
        pts = lhs_points(BOUNDS_2D, 16, seed=1)["points"]
        samples = [{"params": p, "cost": float(p["x_mm"] + 0.5 * p["y_mm"])}
                   for p in lhs_points(BOUNDS_2D, 9, seed=2)["points"]]
        sig = gp_cost_sigma(samples, BOUNDS_2D, pts)
        assert sig.shape == (16,)
        assert bool(np.all(np.isfinite(sig)))
        assert bool(np.all(sig >= 0.0))

    def test_fewer_than_two_finite_costs_all_zero(self):
        pts = [{"x_mm": 0.5, "y_mm": 0.5}]
        one = [{"params": {"x_mm": 0.1, "y_mm": 0.1}, "cost": 1.0}]
        assert float(gp_cost_sigma(one, BOUNDS_2D, pts)[0]) == 0.0
        naned = [{"params": {"x_mm": 0.1, "y_mm": 0.1}, "cost": float("nan")},
                 {"params": {"x_mm": 0.2, "y_mm": 0.2}, "cost": 1.0}]
        assert float(gp_cost_sigma(naned, BOUNDS_2D, pts)[0]) == 0.0

    def test_densification_shrinks_sigma_max(self):
        """样本加密 → σ_max 收缩。

        严格逐点单调性只对后验方差成立；σ_cost 乘了 y 的 sd（z 标准化
        换算回量纲），加密中 sd 有小漂移——故取间隔足够大的确定性
        加密链断言严格收缩。
        """
        bounds = {"x": (0.0, 1.0)}

        def f(x: float) -> float:
            return float(np.sin(2.0 * np.pi * x) + 0.5 * x)

        pool = [{"x": float(v)} for v in np.linspace(0.0, 1.0, 33)]
        sigmas = []
        for n in (5, 12, 24):
            pts = lhs_points(bounds, n, seed=7)["points"]
            samples = [{"params": p, "cost": f(p["x"])} for p in pts]
            sigmas.append(float(max(gp_cost_sigma(samples, bounds, pool))))
        assert sigmas[0] > sigmas[1] > sigmas[2], sigmas

    def test_deterministic_same_inputs(self):
        pts = lhs_points(BOUNDS_2D, 8, seed=3)["points"]
        samples = [{"params": p, "cost": float(p["x_mm"] * p["y_mm"])}
                   for p in lhs_points(BOUNDS_2D, 10, seed=4)["points"]]
        a = gp_cost_sigma(samples, BOUNDS_2D, pts)
        b = gp_cost_sigma(samples, BOUNDS_2D, pts)
        assert np.array_equal(a, b)


# ─── 分层 lint：optimization 禁 import service ───────────────────────────────

class TestLayering:
    def test_uncertainty_module_does_not_import_service(self):
        src = Path(src_dir / "rfauto" / "optimization" / "uncertainty.py")
        tree = ast.parse(src.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not [m for m in imported if m.startswith("rfauto.service")], (
            f"optimization 层禁止 import service 层: {imported}")


# ─── 环内 opt-in 行为 ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


class TestLoopUncertaintyTermination:
    @staticmethod
    def _strip_elapsed(res: dict) -> dict:
        return {k: v for k, v in res.items() if k != "elapsed_s"}

    def test_tol_none_result_byte_identical_to_default(self):
        """tol=None 显式传入与不传参数：结果字典逐字节一致（elapsed_s 除外——
        墙钟计时固有不可复现），且任何 round 条目不带 sigma_cost_max 键。"""
        kw = dict(n_init=6, top_k=2, max_real=12, virtual_trials=120, seed=42)
        res_default = run_surrogate_loop(BOUNDS_2D, OBJS_2D, bowl_metrics, **kw)
        res_none = run_surrogate_loop(BOUNDS_2D, OBJS_2D, bowl_metrics,
                                      uncertainty_tol=None, **kw)
        assert self._strip_elapsed(res_default) == \
            self._strip_elapsed(res_none)
        for r in res_none["rounds"]:
            assert "sigma_cost_max" not in r

    def test_wide_tol_stops_saturated(self):
        """平滑合成面 + 宽 tol：首轮 σ 即达标 → uncertainty_saturated 停，
        触发轮条目 n_evaluated=0 且恒含 sigma_cost_max。"""
        bounds = {"x_mm": (0.0, 1.0)}
        objs = [Objective(metric="s11_db_min", band=[2.3, 2.5],
                          op=MetricOp.MAX_BELOW, value=-47.0, weight=1.0)]

        def valley(params):
            depth = -46.0 + 80.0 * (params["x_mm"] - 0.4) ** 2
            return {"s11_db_min_in_band": depth}

        res = run_surrogate_loop(bounds, objs, valley,
                                 n_init=5, top_k=2, max_real=15,
                                 virtual_trials=100, seed=42,
                                 uncertainty_tol=1e9, uncertainty_pool=64)
        assert res["ok"]
        assert res["stop_reason"] == "uncertainty_saturated"
        assert res["n_real_used"] == 5  # 触发轮批前停：只花初始批
        last = res["rounds"][-1]
        assert last["n_evaluated"] == 0
        assert "sigma_cost_max" in last
        assert last["sigma_cost_max"] is not None
        assert res["best"] is not None

    def test_sigma_sequence_bitwise_reproducible(self):
        """同 seed 两跑：σ 序列逐位一致（tol=0.0 永不触发 → 全程记录）。"""
        kw = dict(n_init=6, top_k=2, max_real=14, virtual_trials=120, seed=7,
                  uncertainty_tol=0.0, uncertainty_pool=64)
        res_a = run_surrogate_loop(BOUNDS_2D, OBJS_2D, bowl_metrics, **kw)
        res_b = run_surrogate_loop(BOUNDS_2D, OBJS_2D, bowl_metrics, **kw)
        assert res_a["stop_reason"] != "uncertainty_saturated"
        sig_a = [r["sigma_cost_max"] for r in res_a["rounds"]
                 if "sigma_cost_max" in r]
        sig_b = [r["sigma_cost_max"] for r in res_b["rounds"]
                 if "sigma_cost_max" in r]
        assert sig_a and sig_a == sig_b  # 逐位（float == float，无 approx）

    def test_sigma_max_recorded_every_round_when_enabled(self):
        """判据开启时每轮恒记录 sigma_cost_max（含 None 兜底语义字段存在）。"""
        res = run_surrogate_loop(BOUNDS_2D, OBJS_2D, bowl_metrics,
                                 n_init=6, top_k=2, max_real=12,
                                 virtual_trials=120, seed=42,
                                 uncertainty_tol=1e-12, uncertainty_pool=64)
        assert res["ok"]
        entries = [r for r in res["rounds"] if "sigma_cost_max" in r]
        assert len(entries) == len(res["rounds"]) - 1  # round-0 相位条目除外
        assert all(r["sigma_cost_max"] is None
                   or r["sigma_cost_max"] >= 0.0 for r in entries)
