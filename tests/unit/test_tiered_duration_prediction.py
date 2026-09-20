"""W2⑦④：G14 分档时长预测 × 预算准入门 × G13 调度器消费 单元测试。

钉死四条语义（全部合成样本、零 runs/ 依赖、零网络、零真机）：

1. 分桶命中——桶内样本 ≥4 且过 LOO 门 → 桶级 calibrated，``fallback==""``；
2. 回退——桶样本不足/缺失 → 回退全局档（``fallback=="global"``，reason 说明桶
   为何不可用）；全局亦不可信 → unknown，``predicted_s is None``，只给声明保守
   上界（不瞎猜）；
3. 预算门——``BudgetLimits.admit`` 以预测保守上界对剩余 wall_hours 预算裁决：
   超预算拒绝、在预算内放行、unknown 无上界 fail-closed 拒绝、未配预算放行；
   经 ``budget_admission_gate`` 注入调度器后超预算作业落 ``budget_rejected``
   且审计通过；
4. 调度顺序受预测影响——注入 predictor 后同到达时刻按预测时长短者优先（SJF），
   未申报时长由分档预测填充并标注来源；不注入 predictor 时排程逐字节不变
   （无新键、输入序=优先序）。
"""

from __future__ import annotations

import json

import pytest

from rfauto.pipeline.quota_guard import (
    MIN_CALIBRATION_SAMPLES,
    UNKNOWN_BOUND_MULTIPLE,
    BudgetLimits,
    CostLedger,
    DurationSample,
    TieredDurationPredictor,
    budget_admission_gate,
    tier_key,
    tier_label,
)
from rfauto.service.resource_scheduler import (
    ResourceJob,
    audit_schedule,
    schedule,
    schedule_json,
)

# --------------------------------------------------------------------------- #
# 夹具：精确 offset+power 律的合成分桶样本
# --------------------------------------------------------------------------- #

MESHES = (0.6, 0.5, 0.4, 0.3, 0.25)


def _law_small(mesh: float) -> float:
    return 20.0 + 5.0 * mesh ** (-3.5)


def _law_big(mesh: float) -> float:
    return 400.0 + 60.0 * mesh ** (-3.5)


def _bucket(template: str, grid: str, law, meshes=MESHES, *, solver: str = "openems") -> list[DurationSample]:
    return [
        DurationSample(
            mesh_mm=m, solve_s=law(m), domain_volume_mm3=1000.0, n_excitations=1,
            solver=solver, template=template, grid_tier=grid,
            source=f"synthetic/{template}/{grid}/m{m:g}",
        )
        for m in meshes
    ]


@pytest.fixture()
def tiered() -> TieredDurationPredictor:
    """两个可信桶（small/big 各 5 点，两条律）+ 一个不足桶（tiny 2 点，服从 small 律）。

    注意：small/big 两律混池令**全局档不可信**——这正是分档口径的实证依据
    （跨模板混池 281% 实证），本夹具用于桶命中/预算门用例。
    """
    samples = (
        _bucket("small", "0p4mm", _law_small)
        + _bucket("big", "0p4mm", _law_big)
        + _bucket("tiny", "0p4mm", _law_small, meshes=(0.5, 0.4))
    )
    return TieredDurationPredictor.fit(samples)


@pytest.fixture()
def tiered_same_law() -> TieredDurationPredictor:
    """同一条律的两桶（small 5 点 + tiny 2 点）→ 全局档可信，用于回退用例。"""
    samples = (
        _bucket("small", "0p4mm", _law_small)
        + _bucket("tiny", "0p4mm", _law_small, meshes=(0.5, 0.4))
    )
    return TieredDurationPredictor.fit(samples)


@pytest.fixture()
def tiered_hfss() -> TieredDurationPredictor:
    """hfss（license 容量 1）下的 small/big 两桶，用于调度顺序用例。"""
    samples = (
        _bucket("small", "0p4mm", _law_small, solver="hfss")
        + _bucket("big", "0p4mm", _law_big, solver="hfss")
    )
    return TieredDurationPredictor.fit(samples)


def _probe_ok(server: str | None = None) -> dict:
    return {"available": True, "server": server, "detail": "stub"}


# --------------------------------------------------------------------------- #
# 1. 分桶命中
# --------------------------------------------------------------------------- #

def test_tier_key_normalises_and_label_renders_blank() -> None:
    assert tier_key(" OpenEMS ", "Ratrace", "0P4MM") == ("openems", "ratrace", "0p4mm")
    assert tier_label(tier_key("openems", "", "")) == "openems/-/-"


def test_bucket_hit_is_calibrated_with_bucket_law(tiered: TieredDurationPredictor) -> None:
    assert set(tiered.bucket_labels()) == {
        "openems/small/0p4mm", "openems/big/0p4mm", "openems/tiny/0p4mm"}
    small = tiered.predict(mesh_mm=0.45, domain_volume_mm3=1000.0,
                           solver="openems", template="small", grid_tier="0p4mm")
    big = tiered.predict(mesh_mm=0.45, domain_volume_mm3=1000.0,
                         solver="openems", template="big", grid_tier="0p4mm")
    assert small.status == "calibrated" and small.fallback == ""
    assert small.bucket == "openems/small/0p4mm" and small.bucket_status == "calibrated"
    assert small.predicted_s == pytest.approx(_law_small(0.45), rel=0.05)
    assert big.status == "calibrated" and big.fallback == ""
    assert big.predicted_s == pytest.approx(_law_big(0.45), rel=0.05)
    assert big.predicted_s > small.predicted_s, "不同桶必须给出各自律的数字（混池会抹平）"
    assert small.n_samples == 5 and big.n_samples == 5
    assert "命中" in small.reason


def test_bucket_hit_outside_range_is_extrapolated(tiered: TieredDurationPredictor) -> None:
    pred = tiered.predict(mesh_mm=2.0, solver="openems", template="small", grid_tier="0p4mm")
    assert pred.status == "extrapolated"
    assert pred.fallback == "" and pred.bucket_status == "extrapolated"
    assert pred.predicted_s is not None and pred.upper_bound_s is not None


# --------------------------------------------------------------------------- #
# 2. 回退：桶不足 → 全局；全局亦不可信 → unknown 不瞎猜
# --------------------------------------------------------------------------- #

def test_insufficient_bucket_falls_back_to_global(tiered_same_law: TieredDurationPredictor) -> None:
    pred = tiered_same_law.predict(mesh_mm=0.45, domain_volume_mm3=1000.0,
                                   solver="openems", template="tiny", grid_tier="0p4mm")
    assert pred.fallback == "global"
    assert pred.bucket == "openems/tiny/0p4mm"
    assert pred.bucket_status == "unknown"
    assert pred.status in {"calibrated", "extrapolated"}
    assert pred.predicted_s == pytest.approx(_law_small(0.45), rel=0.05)
    assert pred.n_samples == 7, "回退全局档：样本数=全部样本"
    assert "不可信" in pred.reason and "回退全局档" in pred.reason
    assert f"min_samples={MIN_CALIBRATION_SAMPLES}" in pred.reason


def test_missing_bucket_falls_back_to_global(tiered_same_law: TieredDurationPredictor) -> None:
    pred = tiered_same_law.predict(mesh_mm=0.45, solver="hfss", template="never_seen", grid_tier="x")
    assert pred.fallback == "global"
    assert pred.bucket_status == "missing"
    assert "无样本" in pred.reason


def test_mixed_law_global_is_untrusted_so_insufficient_bucket_is_unknown(tiered: TieredDurationPredictor) -> None:
    """两律混池：全局档 LOO 不过门 → 不足桶既不能命中也不能回退 → 如实 unknown。"""
    assert tiered.global_predictor.status == "unknown"
    pred = tiered.predict(mesh_mm=0.45, solver="openems", template="tiny", grid_tier="0p4mm")
    assert pred.status == "unknown" and pred.fallback == "none"
    assert pred.predicted_s is None
    assert pred.upper_bound_s == pytest.approx(UNKNOWN_BOUND_MULTIPLE * _law_small(0.4))


def test_all_unknown_gives_no_point_estimate_but_conservative_bound() -> None:
    samples = _bucket("tiny", "0p4mm", _law_small, meshes=(0.5, 0.4))
    tiered = TieredDurationPredictor.fit(samples)
    pred = tiered.predict(mesh_mm=0.45, solver="openems", template="tiny", grid_tier="0p4mm")
    assert pred.status == "unknown"
    assert pred.predicted_s is None, "unknown 绝不给点估计"
    assert pred.fallback == "none"
    assert pred.upper_bound_s == pytest.approx(UNKNOWN_BOUND_MULTIPLE * _law_small(0.4))
    assert "不给点估计" in pred.reason
    empty = TieredDurationPredictor.fit([])
    nothing = empty.predict(mesh_mm=0.4, solver="openems")
    assert nothing.status == "unknown" and nothing.predicted_s is None
    assert nothing.upper_bound_s is None and nothing.bucket_status == "missing"


def test_predict_for_tier_uses_bucket_median_features(tiered: TieredDurationPredictor) -> None:
    """只知分档不知几何：特征取桶内中位数（mesh 中位=0.4），显式 features 优先。"""
    by_tier = tiered.predict_for_tier("openems", "small", "0p4mm")
    explicit = tiered.predict(mesh_mm=0.4, domain_volume_mm3=1000.0,
                              solver="openems", template="small", grid_tier="0p4mm")
    assert by_tier.predicted_s == pytest.approx(explicit.predicted_s)
    override = tiered.predict_for_tier("openems", "small", "0p4mm", features={"mesh_mm": 0.25})
    assert override.predicted_s == pytest.approx(_law_small(0.25), rel=0.05)
    assert override.predicted_s > by_tier.predicted_s


def test_json_round_trip_and_summary_deterministic(tiered: TieredDurationPredictor) -> None:
    again = TieredDurationPredictor.from_json(tiered.to_json())
    q = dict(mesh_mm=0.45, domain_volume_mm3=1000.0, solver="openems",
             template="small", grid_tier="0p4mm")
    assert again.predict(**q).to_dict() == tiered.predict(**q).to_dict()
    summary = tiered.summary()
    json.dumps(summary)
    assert summary["n_buckets"] == 3 and summary["n_samples"] == 12
    assert summary["buckets"]["openems/tiny/0p4mm"]["status"] == "unknown"
    assert summary["buckets"]["openems/small/0p4mm"]["status"] == "calibrated"
    assert json.dumps(again.summary(), sort_keys=True) == json.dumps(summary, sort_keys=True)
    with pytest.raises(ValueError, match="version"):
        TieredDurationPredictor.from_json({"version": 99})


def test_fit_rejects_non_samples() -> None:
    with pytest.raises(TypeError):
        TieredDurationPredictor.fit([{"mesh_mm": 0.4}])


# --------------------------------------------------------------------------- #
# 3. 预算门
# --------------------------------------------------------------------------- #

def _ledger_with_hours(hours: float) -> CostLedger:
    ledger = CostLedger()
    ledger.add("b1", "solver", solve_s=hours * 3600.0)
    return ledger


def test_admit_rejects_job_whose_bound_exceeds_remaining(tiered: TieredDurationPredictor) -> None:
    pred = tiered.predict_for_tier("openems", "big", "0p4mm")   # ≈400+60·0.4^-3.5 ≈ 1883 s
    assert pred.upper_bound_s is not None and pred.upper_bound_s > 1800.0
    budgets = BudgetLimits(wall_hours_budget=1.0)
    decision = budgets.admit(_ledger_with_hours(0.8), pred)      # 剩余 0.2h=720s < 上界
    assert decision["ok"] is False
    assert decision["kind"] == "wall_hours"
    assert decision["remaining_hours"] == pytest.approx(0.2)
    assert decision["upper_bound_hours"] == pytest.approx(pred.upper_bound_s / 3600.0)
    assert "超剩余" in decision["reason"] and "拒绝" in decision["reason"]
    json.dumps(decision)


def test_admit_passes_job_within_budget_and_without_limit(tiered: TieredDurationPredictor) -> None:
    pred = tiered.predict_for_tier("openems", "small", "0p4mm")  # ≈ 143.6 s
    ok = BudgetLimits(wall_hours_budget=1.0).admit(_ledger_with_hours(0.5), pred)
    assert ok["ok"] is True and "放行" in ok["reason"]
    assert ok["prediction_status"] == "calibrated" and ok["bucket"] == "openems/small/0p4mm"
    free = BudgetLimits().admit(_ledger_with_hours(100.0), pred)
    assert free["ok"] is True and free["limit_hours"] is None
    assert "未配置" in free["reason"]


def test_admit_fail_closed_on_unknown_without_bound() -> None:
    pred = TieredDurationPredictor.fit([]).predict(mesh_mm=0.4, solver="openems")
    assert pred.upper_bound_s is None
    decision = BudgetLimits(wall_hours_budget=10.0).admit(CostLedger(), pred)
    assert decision["ok"] is False
    assert "fail-closed" in decision["reason"]


def test_admit_unknown_with_conservative_bound_uses_the_bound() -> None:
    samples = _bucket("tiny", "0p4mm", _law_small, meshes=(0.5, 0.4))
    pred = TieredDurationPredictor.fit(samples).predict_for_tier("openems", "tiny", "0p4mm")
    assert pred.status == "unknown" and pred.upper_bound_s is not None
    bound_h = pred.upper_bound_s / 3600.0
    tight = BudgetLimits(wall_hours_budget=bound_h * 0.5).admit(CostLedger(), pred)
    loose = BudgetLimits(wall_hours_budget=bound_h * 2.0).admit(CostLedger(), pred)
    assert tight["ok"] is False and loose["ok"] is True


def test_admit_only_supports_wall_hours(tiered: TieredDurationPredictor) -> None:
    pred = tiered.predict_for_tier("openems", "small", "0p4mm")
    with pytest.raises(ValueError, match="wall_hours"):
        BudgetLimits(token_budget=1.0).admit(CostLedger(), pred, kind="tokens")


def test_gate_in_scheduler_rejects_over_budget_job_and_audits(tiered: TieredDurationPredictor) -> None:
    budgets = BudgetLimits(wall_hours_budget=1.0)
    gate = budget_admission_gate(budgets, _ledger_with_hours(0.8), tiered)
    jobs = [
        ResourceJob("cheap", "openems", 0.0, template="small", grid_tier="0p4mm"),
        ResourceJob("expensive", "openems", 0.0, template="big", grid_tier="0p4mm"),
    ]
    result = schedule(jobs, probe=_probe_ok, predictor=tiered, budget_gate=gate)
    assert [a["job_id"] for a in result["assignments"]] == ["cheap"]
    rejected = result["unassigned"]
    assert len(rejected) == 1 and rejected[0]["job_id"] == "expensive"
    assert rejected[0]["status"] == "budget_rejected"
    assert "超剩余" in rejected[0]["reason"]
    assert rejected[0]["budget"]["ok"] is False
    assert rejected[0]["budget"]["prediction"]["bucket"] == "openems/big/0p4mm"
    events = [e for e in result["decision_log"] if e["event"] == "budget_reject"]
    assert len(events) == 1 and events[0]["reason"] and events[0]["job_id"] == "expensive"
    audit = audit_schedule(result)
    assert audit["ok"], audit["issues"]


def test_gate_direct_call_returns_json_decision(tiered: TieredDurationPredictor) -> None:
    gate = budget_admission_gate(BudgetLimits(wall_hours_budget=5.0), CostLedger(), tiered)
    decision = gate({"job_id": "j", "solver": "openems", "template": "small", "grid_tier": "0p4mm"})
    assert decision["ok"] is True and decision["job_id"] == "j"
    assert decision["prediction"]["status"] == "calibrated"
    json.dumps(decision)


# --------------------------------------------------------------------------- #
# 4. 调度顺序受预测影响
# --------------------------------------------------------------------------- #

def test_predicted_duration_fills_unknown_and_orders_shortest_first(tiered_hfss: TieredDurationPredictor) -> None:
    """license 容量 1：预测短者先跑；未申报时长由分档预测填充并标注来源。"""
    jobs = [
        ResourceJob("long", "hfss", 0.0, template="big", grid_tier="0p4mm"),
        ResourceJob("short", "hfss", 0.0, template="small", grid_tier="0p4mm"),
    ]
    with_pred = schedule(jobs, probe=_probe_ok, predictor=tiered_hfss)
    order = [a["job_id"] for a in with_pred["assignments"]]
    assert order == ["short", "long"], "同到达时刻预测时长短者优先"
    short, long_ = with_pred["assignments"]
    assert short["duration_source"] == "predicted" and long_["duration_source"] == "predicted"
    assert short["duration_s"] == pytest.approx(_law_small(0.4), rel=0.05)
    assert long_["duration_s"] == pytest.approx(_law_big(0.4), rel=0.05)
    assert short["start_s"] == 0.0
    assert long_["start_s"] == pytest.approx(short["end_s"])
    assert set(with_pred["duration_predictions"]) == {"long", "short"}
    assert with_pred["duration_predictions"]["short"]["bucket"] == "hfss/small/0p4mm"
    assert with_pred["duration_predictions"]["short"]["fallback"] == ""
    assert audit_schedule(with_pred)["ok"]

    without = schedule(jobs, probe=_probe_ok)
    assert [a["job_id"] for a in without["assignments"]] == ["long", "short"], "无预测器：输入序=优先序"
    assert "duration_predictions" not in without
    assert all("duration_source" not in a for a in without["assignments"])


def test_solver_mismatch_never_hits_another_adapters_bucket(tiered: TieredDurationPredictor) -> None:
    """分桶键含 adapter：hfss 作业不得命中 openems 桶（同名模板跨适配器语义可反，#154）。"""
    pred = tiered.predict_for_tier("hfss", "small", "0p4mm")
    assert pred.bucket == "hfss/small/0p4mm" and pred.bucket_status == "missing"
    assert pred.fallback in {"global", "none"}


def test_declared_duration_wins_and_sjf_applies_to_declared(tiered: TieredDurationPredictor) -> None:
    jobs = [ResourceJob("a", "hfss", 100.0), ResourceJob("b", "hfss", 10.0)]
    with_pred = schedule(jobs, probe=_probe_ok, predictor=tiered)
    assert [a["job_id"] for a in with_pred["assignments"]] == ["b", "a"]
    assert all(a["duration_source"] == "declared" for a in with_pred["assignments"])
    assert with_pred["assignments"][0]["duration_s"] == 10.0
    assert with_pred["duration_predictions"] == {}
    without = schedule(jobs, probe=_probe_ok)
    assert [a["job_id"] for a in without["assignments"]] == ["a", "b"]


def test_unknown_prediction_does_not_invent_duration() -> None:
    empty = TieredDurationPredictor.fit([])
    jobs = [ResourceJob("u", "openems", 0.0, template="x", grid_tier="y")]
    result = schedule(jobs, probe=_probe_ok, predictor=empty)
    a = result["assignments"][0]
    assert a["duration_source"] == "unknown_fallback_declared"
    assert a["duration_s"] == 0.0, "unknown 不编造时长，按申报值处理"
    assert result["duration_predictions"]["u"]["status"] == "unknown"
    assert result["duration_predictions"]["u"]["predicted_s"] is None


def test_default_path_unchanged_and_predictor_path_deterministic(tiered: TieredDurationPredictor) -> None:
    jobs = [
        {"job_id": "o1", "solver": "openems", "duration_s": 0, "template": "big", "grid_tier": "0p4mm"},
        {"job_id": "o2", "solver": "openems", "duration_s": 0, "template": "small", "grid_tier": "0p4mm"},
        {"job_id": "h1", "solver": "hfss", "duration_s": 30},
    ]
    first = schedule_json(jobs, probe=_probe_ok, predictor=tiered)
    second = schedule_json(jobs, probe=_probe_ok, predictor=tiered)
    assert first == second
    plain = schedule(jobs, probe=_probe_ok)
    assert "duration_predictions" not in plain
    assert [a["job_id"] for a in plain["assignments"]] == ["o1", "o2", "h1"]
    for a in plain["assignments"]:
        assert set(a) == {"job_id", "solver", "resource_class", "start_s", "end_s",
                          "duration_s", "resources", "index"}
    empty_with_pred = schedule([], probe=_probe_ok, predictor=tiered)
    assert empty_with_pred["duration_predictions"] == {}
    assert "duration_predictions" not in schedule([], probe=_probe_ok)
