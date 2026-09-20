"""sampler_pool：采样 worker 池（阶段 4.3）。

openEMS 单核求解 × N 并行——L25 增广从 6h 压到 ~1h（4 核）。
内存纪律：每个 openEMS worker 占 1-2GB，
max_workers 必须按可用内存设置（默认 1=串行，与既有纪律一致）。

接口：run_sampling_pool(points, worker_fn, max_workers)。
- max_workers=1：进程内串行（零开销，失败不阻塞，与既有单点容错一致）
- max_workers>1：进程池（worker_fn 必须可 pickle——模块级函数）；
  单点异常被捕获为 failure，不拖垮整批。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import Any


def run_sampling_pool(
    points: list[dict[str, float]],
    worker_fn: Callable[[dict[str, float]], Any],
    *,
    max_workers: int = 1,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """并行/串行执行采样，返回 {"results", "failures", "elapsed_s"}。

    results: [{"index": i, "params": pt, "result": worker_fn(pt)}]
    failures: [{"index": i, "params": pt, "error": str}]
    worker_fn 异常即该点失败，不阻塞其余点（校准服务既有容错语义）。
    """
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    t0 = time.time()
    max_workers = max(1, int(max_workers))

    if max_workers == 1:
        for i, pt in enumerate(points):
            try:
                results.append({"index": i, "params": pt,
                                "result": worker_fn(pt)})
            except Exception as exc:
                failures.append({"index": i, "params": pt, "error": str(exc)})
    else:
        # worker_fn 必须可 pickle（模块级函数）；进程内异常回传为 failure
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            futures = [(i, pt, pool.submit(worker_fn, pt))
                       for i, pt in enumerate(points)]
            for i, pt, fut in futures:
                try:
                    res = fut.result(timeout=timeout_s)
                    results.append({"index": i, "params": pt, "result": res})
                except Exception as exc:
                    failures.append({"index": i, "params": pt,
                                     "error": str(exc)[:500]})

    return {"ok": True, "results": results, "failures": failures,
            "n_points": len(points), "max_workers": max_workers,
            "elapsed_s": round(time.time() - t0, 1)}
