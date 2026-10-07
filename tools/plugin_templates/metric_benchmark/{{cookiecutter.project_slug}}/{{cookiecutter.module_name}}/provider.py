"""离线参考提供器（benchmark 面；run_agentbench_regression 注入点）。

语义与 ``service/agent_bench.reference_agentbench_provider`` 同构：回放
任务期望（轨迹+工件+声明 ground truth 数值），仅作回归门自身的正控
（证明任务集与两轴打分器自洽、门能跑通），**不构成对真实 agent 质量
的判据**。确定性、无网络、无 LLM。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["reference_provider"]


def reference_provider(task: Mapping[str, Any]) -> dict[str, Any]:
    """任务期望回放（records 契约三键：trajectory/artifacts/numeric）。"""
    expected = task.get("expected") or {}
    numeric = {str(n.get("metric")): n.get("value")
               for n in expected.get("numeric") or [] if n.get("metric")}
    return {
        "trajectory": [{"tool": str(c.get("tool") or ""),
                        "args": dict(c.get("args") or {})}
                       for c in expected.get("calls") or []],
        "artifacts": list(expected.get("artifacts") or []),
        "numeric": numeric,
    }
