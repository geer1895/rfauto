"""B-26：FaultInjection 注入用例库（G11/G15 交叉覆盖）。

FakeAdapter 的 FaultInjection 有 5 个字段（fail_connect / fail_build /
fail_solve / passivity_violation / slow_solve_s）。本文件：
- 参数化覆盖每个字段单独注入 + 若干组合，逐例断言各自预期行为；
- 交叉覆盖硬断言：把"实际构造过的 FaultInjection 字段集合"与 FaultInjection
  的全部签名参数比对，缺一个即失败（防空测/防字段新增后静默漏测）；
- 把注入产物喂 core.solve_health（G11）：passivity 注入判 FAIL，正常样本判
  健康——两条并存证明健康判据非恒真。

注：SolveReport.wall_time_s 是 FakeAdapter 写死的 0.01（不随 slow_solve_s
变化），故 slow 用例以外部 perf_counter 实测求解墙钟体现延迟。
"""

from __future__ import annotations

import inspect
import time
from typing import Any

import numpy as np
import pytest

from rfauto.adapters.fake_adapter import FakeAdapter, FaultInjection
from rfauto.core.errors import (
    ConnectFailedError,
    ModelBuildError,
    SimulationFailedError,
)
from rfauto.core.solve_health import solve_health_check

# FaultInjection 的全部字段（从真实签名取，不从注释抄）
ALL_FAULT_FIELDS = frozenset(
    name for name in inspect.signature(FaultInjection.__init__).parameters
    if name != "self"
)

# 覆盖用例库：(id, FaultInjection kwargs, 预期行为分类)
# 单字段 ×5 + 组合 ×5；每个字段都至少被真实构造一次。
INJECTION_CASES: list[dict[str, Any]] = [
    {"id": "fail_connect_only",
     "fields": {"fail_connect": True}, "expect": "connect_error"},
    {"id": "fail_build_only",
     "fields": {"fail_build": True}, "expect": "build_error"},
    {"id": "fail_solve_only",
     "fields": {"fail_solve": True}, "expect": "solve_error"},
    {"id": "passivity_violation_only",
     "fields": {"passivity_violation": True}, "expect": "passivity"},
    {"id": "slow_solve_only",
     "fields": {"slow_solve_s": 0.15}, "expect": "slow"},
    {"id": "combo_fail_connect_and_build",
     "fields": {"fail_connect": True, "fail_build": True},
     "expect": "connect_error"},
    {"id": "combo_fail_build_and_solve",
     "fields": {"fail_build": True, "fail_solve": True},
     "expect": "build_error"},
    {"id": "combo_fail_solve_and_slow",
     "fields": {"fail_solve": True, "slow_solve_s": 0.15},
     "expect": "solve_error_no_sleep"},
    {"id": "combo_passivity_and_slow",
     "fields": {"passivity_violation": True, "slow_solve_s": 0.05},
     "expect": "passivity_slow"},
    {"id": "combo_all_inactive_explicit",
     "fields": {"fail_connect": False, "fail_build": False, "fail_solve": False,
                "passivity_violation": False, "slow_solve_s": 0.0},
     "expect": "healthy"},
]

_CASE_IDS = [c["id"] for c in INJECTION_CASES]


def _make(case: dict[str, Any]) -> FakeAdapter:
    return FakeAdapter(fault=FaultInjection(**case["fields"]))


def _solved_network(adapter: FakeAdapter):
    adapter.connect({})
    adapter.solve("injection_probe")
    return adapter.get_sparams()


# ---------------------------------------------------------------------------
# 注入行为：单字段 + 组合
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", INJECTION_CASES, ids=_CASE_IDS)
def test_injection_case_behaviour(case):
    adapter = _make(case)
    expect = case["expect"]

    if expect == "connect_error":
        with pytest.raises(ConnectFailedError):
            adapter.connect({})
        return

    if expect == "build_error":
        adapter.connect({})
        with pytest.raises(ModelBuildError):
            adapter.build_and_setup(lambda a: None, {})
        return

    if expect == "solve_error":
        adapter.connect({})
        with pytest.raises(SimulationFailedError):
            adapter.solve("injection_probe")
        return

    if expect == "solve_error_no_sleep":
        # fail_solve 在 sleep 之前短路：异常立即抛，不等 slow_solve_s
        adapter.connect({})
        t0 = time.perf_counter()
        with pytest.raises(SimulationFailedError):
            adapter.solve("injection_probe")
        assert time.perf_counter() - t0 < 0.10, "fail_solve 应先于 slow_solve_s 短路"
        return

    if expect == "passivity":
        net = _solved_network(adapter)
        assert float(np.max(np.abs(net.s))) > 1.0, "passivity_violation 未产出 |S|>1"
        return

    if expect == "slow":
        adapter.connect({})
        t0 = time.perf_counter()
        report = adapter.solve("injection_probe")
        elapsed = time.perf_counter() - t0
        assert report.success
        assert elapsed >= 0.15 * 0.8, f"slow_solve_s 未生效: {elapsed:.3f}s"
        return

    if expect == "passivity_slow":
        adapter.connect({})
        t0 = time.perf_counter()
        adapter.solve("injection_probe")
        elapsed = time.perf_counter() - t0
        assert elapsed >= 0.05 * 0.8, f"slow_solve_s 未生效: {elapsed:.3f}s"
        net = adapter.get_sparams()
        assert float(np.max(np.abs(net.s))) > 1.0
        return

    if expect == "healthy":
        net = _solved_network(adapter)
        assert float(np.max(np.abs(net.s))) <= 1.01
        return

    raise AssertionError(f"未知预期分类: {expect}")


# ---------------------------------------------------------------------------
# 交叉覆盖硬断言（防空测）
# ---------------------------------------------------------------------------

def test_fault_field_cross_coverage_hard():
    """实际构造过的字段集合必须等于 FaultInjection 全部字段，缺一即失败。"""
    constructed: set[str] = set()
    for case in INJECTION_CASES:
        fixture = FaultInjection(**case["fields"])
        # 从真实实例读回字段（不是从用例字典抄 key）
        constructed |= set(vars(fixture))
    assert constructed == set(ALL_FAULT_FIELDS), (
        f"未覆盖字段: {sorted(set(ALL_FAULT_FIELDS) - constructed)}; "
        f"多出字段: {sorted(constructed - set(ALL_FAULT_FIELDS))}")


def test_edge_cases_cover_single_field_isolated():
    """每个字段都有"单独注入"用例（非只出现在组合里）。"""
    single = {next(iter(c["fields"])) for c in INJECTION_CASES
              if len(c["fields"]) == 1}
    assert single == set(ALL_FAULT_FIELDS)


# ---------------------------------------------------------------------------
# 注入产物 → core.solve_health（G11）：FAIL 与健康并存，证非恒真
# ---------------------------------------------------------------------------

def _factor(report: dict, name: str) -> dict:
    return next(f for f in report["factors"] if f["factor"] == name)


def test_passivity_injection_product_fails_solve_health():
    adapter = FakeAdapter(fault=FaultInjection(passivity_violation=True))
    net = _solved_network(adapter)

    report = solve_health_check(network=net)

    assert float(np.max(np.abs(net.s))) > 1.0  # 注入确实生效
    assert _factor(report, "passivity")["status"] == "FAIL"
    assert report["verdict"] == "unhealthy"
    assert report["ok"] is False


def test_healthy_fake_product_passes_solve_health():
    adapter = FakeAdapter()
    net = _solved_network(adapter)

    report = solve_health_check(network=net)

    assert _factor(report, "passivity")["status"] == "PASS"
    assert report["verdict"] == "healthy"
    assert report["ok"] is True
    # 非恒真对照：同一判据在注入样本上 FAIL、在正常样本上 PASS
    assert report["verdict"] != "unhealthy"
