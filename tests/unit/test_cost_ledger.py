"""G14 编排成本记账与预算门单测（CostLedger / BudgetLimits / DurationPredictor）。

确定性、无网络、无真机：全部为纯 Python 记账 + 合成数据的回归。
"""

import json

import pytest

from rfauto.pipeline.quota_guard import (
    DEFAULT_MESH_POWER,
    BudgetExceededError,
    BudgetLimits,
    CostLedger,
    DurationPredictor,
    DurationSample,
    OffsetPowerDurationPredictor,
    QuotaExceededError,
    QuotaGuard,
    QuotaLimits,
)


def _ledger(**fields) -> CostLedger:
    ledger = CostLedger()
    ledger.add("batch_a", "actor_1", **fields)
    return ledger


class TestCostLedger:
    """记账累加 / 合并 / 汇总表结构。"""

    def test_add_accumulates_across_calls(self):
        ledger = CostLedger()
        ledger.add("b1", "actor_a", prompt_tokens=1000, completion_tokens=200)
        ledger.add("b1", "actor_a", prompt_tokens=500, completion_tokens=50, solve_s=3600)
        row = ledger.rollup()["b1"]["actors"]["actor_a"]
        assert row["prompt_tokens"] == 1500
        assert row["completion_tokens"] == 250
        assert row["total_tokens"] == 1750
        assert row["solve_s"] == 3600
        assert row["solve_hours"] == pytest.approx(1.0)

    def test_tokens_total_counter(self):
        """未拆分输入/输出时走 tokens 总量计数。"""
        ledger = CostLedger()
        ledger.add("b", tokens=62_400_000)
        assert ledger.totals()["total_tokens"] == 62_400_000

    def test_merge_sums_two_ledgers(self):
        left = CostLedger()
        left.add("b1", "x", tokens=100, solve_s=10)
        right = CostLedger()
        right.add("b1", "x", tokens=50, seat_hours=2.0)
        right.add("b2", "y", gpu_hours=1.5, cost=7.25)
        left.merge(right)
        totals = left.totals()
        assert totals["total_tokens"] == 150
        assert totals["solve_s"] == 10
        assert totals["seat_hours"] == 2.0
        assert totals["gpu_hours"] == 1.5
        assert totals["cost"] == 7.25
        assert left.batches() == ["b1", "b2"]
        assert left.actors("b2") == ["y"]

    def test_rollup_is_json_serialisable_per_batch_table(self):
        ledger = CostLedger()
        ledger.add("batch_x", "solver", solve_s=1800, seat_hours=0.5)
        ledger.add("batch_x", "llm", prompt_tokens=10, completion_tokens=5)
        ledger.add("batch_y", "llm", tokens=100)
        table = ledger.rollup()
        assert set(table) == {"batch_x", "batch_y"}
        row = table["batch_x"]
        assert row["solve_s"] == 1800
        assert row["solve_hours"] == pytest.approx(0.5)
        assert row["seat_hours"] == 0.5
        assert row["total_tokens"] == 15
        assert set(row["actors"]) == {"solver", "llm"}
        # 可 json.dumps（成本表落档契约）
        dumped = json.loads(json.dumps(table))
        assert dumped["batch_x"]["solve_s"] == 1800

    def test_empty_ledger(self):
        ledger = CostLedger()
        assert ledger.rollup() == {}
        assert ledger.batches() == []
        totals = ledger.totals()
        assert totals["total_tokens"] == 0.0
        assert totals["solve_s"] == 0.0
        assert totals["solve_hours"] == 0.0
        report = BudgetLimits(token_budget=1).report(ledger)
        assert report["tokens"]["used"] == 0.0
        assert report["tokens"]["exceeded"] is False

    def test_to_json_roundtrip_is_exact(self):
        ledger = CostLedger()
        ledger.add("b1", "a", prompt_tokens=7, tokens=3, solve_s=1.5, seat_hours=0.25)
        ledger.add("b2", "c", gpu_hours=2.0, cost=9.99)
        payload = ledger.to_json()
        restored = CostLedger.from_json(payload)
        assert restored.to_json() == payload
        assert restored.totals() == ledger.totals()
        assert restored.rollup() == ledger.rollup()

    def test_negative_or_nonfinite_field_rejected(self):
        ledger = CostLedger()
        with pytest.raises(ValueError):
            ledger.add("b", solve_s=-1.0)
        with pytest.raises(ValueError):
            ledger.add("b", tokens=float("nan"))


class TestBudgetGate:
    """四类预算各有边界：恰好等于不触发，超一点触发 STOP。"""

    def test_token_budget_boundary(self):
        ledger = _ledger(tokens=1_000_000)
        BudgetLimits(token_budget=1_000_000).check(ledger)  # 恰好等于 -> 不抛
        with pytest.raises(BudgetExceededError) as excinfo:
            BudgetLimits(token_budget=999_999).check(ledger)
        assert excinfo.value.kind == "tokens"
        assert excinfo.value.used == 1_000_000
        assert excinfo.value.limit == 999_999

    def test_wall_hours_budget_boundary(self):
        ledger = _ledger(solve_s=7200.0)  # 2.0 h
        BudgetLimits(wall_hours_budget=2.0).check(ledger)
        with pytest.raises(BudgetExceededError) as excinfo:
            BudgetLimits(wall_hours_budget=1.999).check(ledger)
        assert excinfo.value.kind == "wall_hours"

    def test_seat_hours_budget_boundary(self):
        ledger = _ledger(seat_hours=5.0)
        BudgetLimits(seat_hours_budget=5.0).check(ledger)
        with pytest.raises(BudgetExceededError) as excinfo:
            BudgetLimits(seat_hours_budget=4.5).check(ledger)
        assert excinfo.value.kind == "seat_hours"

    def test_cost_budget_boundary(self):
        ledger = _ledger(cost=100.0)
        BudgetLimits(cost_budget=100.0).check(ledger)
        with pytest.raises(BudgetExceededError) as excinfo:
            BudgetLimits(cost_budget=99.5).check(ledger)
        assert excinfo.value.kind == "cost"

    def test_exactly_equal_limit_never_triggers_any_budget(self):
        ledger = _ledger(tokens=10, solve_s=3600.0, seat_hours=1.0, cost=2.0)
        limits = BudgetLimits(
            token_budget=10,
            wall_hours_budget=1.0,
            seat_hours_budget=1.0,
            cost_budget=2.0,
        )
        limits.check(ledger)  # 全边界等值 -> 全不抛
        report = limits.report(ledger)
        assert all(not info["exceeded"] for info in report.values())

    def test_unlimited_budgets_never_trigger(self):
        ledger = _ledger(tokens=10**9, solve_s=10**9, seat_hours=10**6, cost=10**6)
        limits = BudgetLimits()
        limits.check(ledger)
        report = limits.report(ledger)
        assert all(info["limit"] is None for info in report.values())
        assert all(info["remaining"] is None for info in report.values())

    def test_remaining_reports_headroom(self):
        ledger = _ledger(tokens=400, solve_s=1800.0, seat_hours=1.0, cost=5.0)
        limits = BudgetLimits(
            token_budget=1000,
            wall_hours_budget=2.0,
            seat_hours_budget=4.0,
            cost_budget=20.0,
        )
        remaining = limits.remaining(ledger)
        assert remaining["tokens_left"] == 600
        assert remaining["wall_hours_left"] == pytest.approx(1.5)
        assert remaining["seat_hours_left"] == pytest.approx(3.0)
        assert remaining["cost_left"] == pytest.approx(15.0)

    def test_remaining_clamps_at_zero_when_exceeded(self):
        ledger = _ledger(tokens=400)
        limits = BudgetLimits(token_budget=100)
        assert limits.remaining(ledger)["tokens_left"] == 0.0
        assert limits.report(ledger)["tokens"]["exceeded"] is True

    def test_budget_error_is_quota_error_and_guard_wires_it(self):
        assert issubclass(BudgetExceededError, QuotaExceededError)
        ledger = _ledger(tokens=11)
        guard = QuotaGuard(QuotaLimits(), budgets=BudgetLimits(token_budget=10))
        with pytest.raises(QuotaExceededError):
            guard.check_budget(ledger)
        # 未挂预算的旧守卫仍是 no-op（向后兼容）
        QuotaGuard(QuotaLimits()).check_budget(ledger)


def _synthetic_samples() -> list[DurationSample]:
    """精确幂律合成数据：t = 12 * mesh_mm^-1.5 * n_excitations。"""
    rows = []
    for mesh in (0.25, 0.4, 0.6, 1.0, 1.5):
        for n_exc in (1, 2):
            solve_s = 12.0 * mesh**-1.5 * n_exc
            rows.append(
                DurationSample(
                    mesh_mm=mesh,
                    solve_s=solve_s,
                    n_excitations=n_exc,
                    source="synthetic",
                )
            )
    return rows


class TestDurationPredictor:
    """时长预测器：精确合成数据上应还原幂律；带噪数据上 LOO 有界。"""

    def test_recovers_exact_power_law(self):
        samples = _synthetic_samples()
        predictor = DurationPredictor.fit(samples, features=("mesh_mm", "n_excitations"))
        assert max(predictor.relative_errors(samples)) < 1e-8
        predicted = predictor.predict_s(mesh_mm=0.5, n_excitations=3)
        assert predicted == pytest.approx(12.0 * 0.5**-1.5 * 3.0, rel=1e-8)

    def test_fit_is_deterministic(self):
        samples = _synthetic_samples()
        first = DurationPredictor.fit(samples, features=("mesh_mm",))
        second = DurationPredictor.fit(samples, features=("mesh_mm",))
        assert first.coefficients == second.coefficients

    def test_loo_on_noisy_synthetic_is_bounded(self):
        """±5% 确定性乘性噪声下，LOO 相对误差仍 < 30%（合成已知真值）。"""
        jitter = (1.0, 0.95, 1.05, 0.97, 1.04, 1.02, 0.96, 1.03, 0.98, 1.01)
        samples = [
            DurationSample(
                mesh_mm=s.mesh_mm,
                solve_s=s.solve_s * jitter[i],
                n_excitations=s.n_excitations,
            )
            for i, s in enumerate(_synthetic_samples())
        ]
        errors = DurationPredictor.loo_relative_errors(
            samples, features=("mesh_mm", "n_excitations")
        )
        assert len(errors) == len(samples)
        assert max(errors) < 0.30

    def test_invalid_feature_rejected(self):
        with pytest.raises(ValueError):
            DurationSample(mesh_mm=0.0, solve_s=1.0).feature("mesh_mm")
        with pytest.raises(ValueError):
            DurationPredictor.fit(
                [DurationSample(mesh_mm=-1.0, solve_s=1.0),
                 DurationSample(mesh_mm=0.5, solve_s=2.0)]
            )

    def test_fit_needs_enough_samples(self):
        with pytest.raises(ValueError):
            DurationPredictor.fit(
                [DurationSample(mesh_mm=0.5, solve_s=1.0)],
                features=("mesh_mm",),
            )


def _offset_power_samples() -> list[DurationSample]:
    """精确 offset+power 合成数据：t = 30 + 5 * mesh_mm^-3.5 * n_exc。"""
    rows = []
    for mesh in (0.2, 0.3, 0.45, 0.7, 1.0):
        for n_exc in (1, 4):
            solve_s = 30.0 + 5.0 * mesh**-DEFAULT_MESH_POWER * n_exc
            rows.append(DurationSample(mesh_mm=mesh, solve_s=solve_s, n_excitations=n_exc))
    return rows


class TestOffsetPowerPredictor:
    """带固定开销的 FDTD 时长模型（物理形态：overhead + cells*steps）。"""

    def test_recovers_exact_offset_power(self):
        samples = _offset_power_samples()
        predictor = OffsetPowerDurationPredictor.fit(samples)
        assert max(predictor.relative_errors(samples)) < 1e-8
        predicted = predictor.predict_s(mesh_mm=0.5, n_excitations=1)
        assert predicted == pytest.approx(30.0 + 5.0 * 0.5**-DEFAULT_MESH_POWER, rel=1e-8)

    def test_loo_on_noisy_offset_power_is_bounded(self):
        """±3% 乘性噪声 + 端点外推下的 LOO 上界（实测 max ~0.51）。"""
        jitter = (1.0, 0.97, 1.03, 1.01, 0.99, 1.02, 0.98, 1.04, 0.96, 1.0)
        samples = [
            DurationSample(
                mesh_mm=s.mesh_mm,
                solve_s=s.solve_s * jitter[i],
                n_excitations=s.n_excitations,
            )
            for i, s in enumerate(_offset_power_samples())
        ]
        errors = OffsetPowerDurationPredictor.loo_relative_errors(samples)
        assert len(errors) == len(samples)
        assert max(errors) < 0.60

    def test_needs_two_samples(self):
        with pytest.raises(ValueError):
            OffsetPowerDurationPredictor.fit([DurationSample(mesh_mm=0.5, solve_s=1.0)])

