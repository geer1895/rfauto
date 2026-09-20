"""阶段 4.3：采样 worker 池测试。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def _double(pt):
    return {"v": pt["x"] * 2}


def _maybe_fail(pt):
    if pt["x"] < 0:
        raise ValueError(f"负数: {pt['x']}")
    return {"v": pt["x"] * 2}


class TestSamplingPool:
    def test_serial_preserves_order_and_results(self):
        from rfauto.optimization.sampler_pool import run_sampling_pool

        pts = [{"x": 1.0}, {"x": 2.0}, {"x": 3.0}]
        r = run_sampling_pool(pts, _double, max_workers=1)
        assert r["ok"] and not r["failures"]
        assert [item["result"]["v"] for item in r["results"]] == [2.0, 4.0, 6.0]
        assert [item["index"] for item in r["results"]] == [0, 1, 2]

    def test_process_pool_parallel(self):
        from rfauto.optimization.sampler_pool import run_sampling_pool

        pts = [{"x": float(i)} for i in range(8)]
        r = run_sampling_pool(pts, _double, max_workers=4)
        assert r["ok"] and len(r["results"]) == 8 and not r["failures"]
        assert {item["result"]["v"] for item in r["results"]} == {0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0}

    def test_single_failure_isolated(self):
        from rfauto.optimization.sampler_pool import run_sampling_pool

        pts = [{"x": -1.0}, {"x": 2.0}]
        r = run_sampling_pool(pts, _maybe_fail, max_workers=1)
        assert r["ok"]
        assert len(r["results"]) == 1 and len(r["failures"]) == 1
        assert "负数" in r["failures"][0]["error"]
