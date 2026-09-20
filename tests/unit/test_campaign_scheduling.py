"""F2⑤ G13 调度接进战役生产路径的单测（零网络、零真机、确定性，#139）。

生产发起点 = service.campaign_manager.plan_campaign（CLI ``campaign plan`` 与
MCP ``plan_campaign`` 薄壳均直调它）：阶段队列成形后、派发前经
orchestration_wiring.schedule_campaign_jobs → resource_scheduler.schedule()。

覆盖：
- 默认路径（predictor/budget_gate 均 None）：plan_campaign 附带 scheduling，
  派发序=输入序、零拒绝、逐字节确定；阶段队列本体不变；计划期不真探 license；
- 注入 stub predictor：未申报作业按 (solver, template, grid_tier) 分档预测填充，
  同刻 SJF 重排派发序；预测 unknown 不编造时长；
- 注入 stub budget_gate：拒绝作业落 rejected / unassigned(budget_rejected) +
  decision_log budget_reject 审计事件，派发清单排尾不静默丢；
- 调度器抛异常：战役照常（ok=True、阶段完整）+ scheduling.warning（#105）；
- save_plan 同步落 <out_dir>/schedule.json（sort_keys 规范化）；无 scheduling 不落；
- 席位记账走 B-29 JobRegistry assign/release 路径（注入账本可查）。
"""

from __future__ import annotations

import json

import pytest
import yaml

from rfauto.service.campaign_manager import (
    SCHEDULE_FILE_NAME,
    plan_campaign,
    save_plan,
    schedule_plan_jobs,
)
from rfauto.service.job_registry import JobRegistry
from rfauto.service.orchestration_wiring import (
    OrchestrationWiring,
    plan_time_probe,
    schedule_campaign_jobs,
)

#: plan_campaign 缺省阶段队列（final_verify 由 high_adapter=hfss 压轴追加）。
STAGE_ORDER = ["calibrate", "prefilter", "tune", "tolerance", "report", "final_verify"]
#: 缺省容量下的内核派发序：pure 容量 2 → report 让位到 60s（排最后）。
DISPATCH_ORDER = ["calibrate", "prefilter", "tune", "tolerance", "final_verify", "report"]


@pytest.fixture
def recipe_path(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "limits": {"max_trials": 12},
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")
    return path


class _Prediction:
    def __init__(self, predicted_s):
        self.predicted_s = predicted_s

    def to_dict(self):
        return {"predicted_s": self.predicted_s, "status": "stub",
                "source": "stub_predictor"}


class _StubPredictor:
    """分档时长预测替身：按 (solver, template, grid_tier) 查表，缺键→unknown（None）。"""

    def __init__(self, table):
        self.table = dict(table)
        self.calls: list[tuple[str, str, str]] = []

    def predict_for_tier(self, solver, template="", grid_tier="", *, features=None):
        self.calls.append((solver, template, grid_tier))
        return _Prediction(self.table.get((solver, template, grid_tier)))


def _reject_license_gate(job_doc):
    if job_doc.get("solver") == "hfss":
        return {"ok": False, "reason": "wall_hours 预算耗尽（stub）", "kind": "wall_hours"}
    return {"ok": True, "reason": "预算内（stub）", "kind": "wall_hours"}


def _exploding_gate(job_doc):
    raise RuntimeError("预算门炸了（stub）")


# ── 默认路径：无预算配置、无时长样本 ──────────────────────────────────────────

class TestDefaultPath:
    def test_plan_campaign_attaches_input_order_schedule(self, recipe_path):
        plan = plan_campaign(recipe_path)
        assert plan["ok"] is True
        # 阶段队列本体（状态机输入）不因调度前置步改变
        assert [s["stage"] for s in plan["stages"]] == STAGE_ORDER
        assert all(s["status"] == "pending" for s in plan["stages"])

        s = plan["scheduling"]
        assert s["ok"] is True and s["schema"] == "rfauto-campaign-schedule-v1"
        assert s["predictor_used"] is False and s["budget_gate_used"] is False
        assert s["rejected"] == [] and s["unassigned"] == []
        assert s["n_jobs"] == 6 and s["audit"]["ok"] is True
        assert s["job_ids"] == [f"campaign:{n}" for n in STAGE_ORDER]
        assert [d["stage"] for d in s["dispatch"]] == DISPATCH_ORDER
        assert all(d["admitted"] for d in s["dispatch"])

        by_stage = {d["stage"]: d for d in s["dispatch"]}
        for name in ("calibrate", "prefilter", "tune", "tolerance", "final_verify"):
            assert by_stage[name]["start_s"] == 0.0 and by_stage[name]["status"] == "running"
        assert by_stage["report"]["start_s"] == 60.0 and by_stage["report"]["status"] == "assigned"
        assert by_stage["final_verify"]["solver"] == "hfss"
        assert by_stage["final_verify"]["planned_seats"] == ["solver:hfss"]
        assert by_stage["calibrate"]["seats"] == ["solver:openems", "class:fdtd"]
        # 未注入 predictor：时长只能是申报值，不存在预测来源
        assert {d["duration_source"] for d in s["dispatch"]} == {"declared"}
        assert "duration_predictions" not in s

    def test_default_schedule_is_byte_deterministic(self, recipe_path):
        first = json.dumps(plan_campaign(recipe_path)["scheduling"],
                           sort_keys=True, ensure_ascii=False)
        second = json.dumps(plan_campaign(recipe_path)["scheduling"],
                            sort_keys=True, ensure_ascii=False)
        assert first == second

    def test_plan_time_never_probes_real_license(self, recipe_path, monkeypatch):
        """计划期必须走 plan_time_probe 替身——真探测在测试里会炸（#139 零网络）。"""
        import rfauto.service.resource_scheduler as rs

        def _boom(*_a, **_k):
            raise AssertionError("计划期不得真探 license server")

        monkeypatch.setattr(rs, "probe_license", _boom)
        s = plan_campaign(recipe_path)["scheduling"]
        assert s["ok"] is True and s["probe_attempts"] == 1
        probe_events = [e for e in s["decision_log"] if e["event"] == "probe"]
        assert probe_events and "计划期不探测" in probe_events[0]["detail"]
        assert plan_time_probe("srv")["available"] is True

    def test_high_adapter_none_has_no_license_job(self, recipe_path):
        s = plan_campaign(recipe_path, high_adapter="none")["scheduling"]
        assert s["n_jobs"] == 5
        assert "solver:hfss" not in s["capacities"]
        assert s["probe_attempts"] == 0

    def test_empty_plan_reports_error_without_raise(self):
        s = schedule_plan_jobs({"stages": []})
        assert s["ok"] is False and s["errors"]
        assert schedule_campaign_jobs({"model": "m"})["ok"] is False


# ── predictor 注入：分档预测填充 + SJF ────────────────────────────────────────

class TestPredictorInjection:
    def test_sjf_reorders_by_predicted_duration(self):
        plan = {"model": "patch_antenna", "stages": [
            {"stage": "a", "adapter": "local", "grid_tier": "coarse"},
            {"stage": "b", "adapter": "local", "grid_tier": "fine"},
            {"stage": "c", "adapter": "local", "grid_tier": "coarse"},
            {"stage": "d", "adapter": "local", "grid_tier": "fine"},
        ]}
        pred = _StubPredictor({("pure", "patch_antenna", "coarse"): 3000.0,
                               ("pure", "patch_antenna", "fine"): 10.0})
        s = schedule_plan_jobs(plan, predictor=pred)
        assert s["ok"] is True and s["predictor_used"] is True
        # SJF：fine(10s) 先派、coarse(3000s) 后派；同长按输入序
        assert [d["stage"] for d in s["dispatch"]] == ["b", "d", "a", "c"]
        by = {d["stage"]: d for d in s["dispatch"]}
        assert by["b"]["start_s"] == 0.0 and by["d"]["start_s"] == 0.0
        assert by["a"]["start_s"] == 10.0 and by["c"]["start_s"] == 10.0  # pure 容量 2
        assert by["a"]["end_s"] == 3010.0
        assert {d["duration_source"] for d in s["dispatch"]} == {"predicted"}
        assert set(s["duration_predictions"]) == {f"campaign:{n}" for n in "abcd"}
        assert s["duration_predictions"]["campaign:a"]["predicted_s"] == 3000.0
        # 分档维度（solver/template/grid_tier）确实传到了预测器
        assert ("pure", "patch_antenna", "fine") in pred.calls
        assert s["audit"]["ok"] is True

    def test_declared_duration_wins_and_unknown_is_not_fabricated(self):
        plan = {"model": "m", "stages": [{"stage": "x", "adapter": "local"}]}
        declared = schedule_plan_jobs(plan, predictor=_StubPredictor({}),
                                      stage_durations={"x": 42.0})
        d = declared["dispatch"][0]
        assert d["duration_source"] == "declared" and d["end_s"] == 42.0

        unknown = schedule_plan_jobs(plan, predictor=_StubPredictor({}))
        u = unknown["dispatch"][0]
        assert u["duration_source"] == "unknown_fallback_declared"
        assert u["end_s"] == 0.0  # 未申报且预测 unknown：按申报 0 处理，不编造
        assert unknown["duration_predictions"]["campaign:x"]["predicted_s"] is None

    def test_without_predictor_default_declared_duration_is_60s(self):
        plan = {"model": "m", "stages": [{"stage": "x", "adapter": "openems"}]}
        s = schedule_plan_jobs(plan)
        assert s["dispatch"][0]["end_s"] == 60.0
        assert s["dispatch"][0]["seats"] == ["solver:openems", "class:fdtd"]


# ── budget_gate 注入：拒绝记账不静默丢 ────────────────────────────────────────

class TestBudgetGateInjection:
    def test_rejected_job_recorded_not_dropped(self, recipe_path):
        plan = plan_campaign(recipe_path)
        s = schedule_plan_jobs(plan, budget_gate=_reject_license_gate, campaign_id="camp_x")
        assert s["ok"] is True and s["budget_gate_used"] is True
        assert s["campaign_id"] == "camp_x"

        assert [r["stage"] for r in s["rejected"]] == ["final_verify"]
        rej = s["rejected"][0]
        assert rej["job_id"] == "campaign:final_verify"
        assert rej["status"] == "budget_rejected" and "预算" in rej["reason"]
        assert rej["budget"]["ok"] is False
        assert [u["status"] for u in s["unassigned"]] == ["budget_rejected"]

        # 派发清单里仍有该阶段（排尾、admitted=False），不静默丢
        tail = s["dispatch"][-1]
        assert tail["stage"] == "final_verify" and tail["admitted"] is False
        assert tail["status"] == "budget_rejected" and tail["budget"]["ok"] is False
        assert tail["order"] == 5

        # 内核审计事件齐备、离线审计通过
        events = [e for e in s["decision_log"] if e["event"] == "budget_reject"]
        assert len(events) == 1 and events[0]["job_id"] == "campaign:final_verify"
        assert events[0]["reason"]
        assert s["audit"]["ok"] is True

        # 其余 5 个阶段照常获席位；hfss 席位未被占
        assert sum(1 for d in s["dispatch"] if d["admitted"]) == 5
        assert "solver:hfss" not in s["seat_occupancy"]

    def test_gate_sees_tier_fields_for_every_job(self, recipe_path):
        seen: list[dict] = []

        def gate(doc):
            seen.append(dict(doc))
            return {"ok": True, "reason": "ok"}

        schedule_plan_jobs(plan_campaign(recipe_path), budget_gate=gate)
        assert {d["job_id"] for d in seen} == {f"campaign:{n}" for n in STAGE_ORDER}
        assert {d["template"] for d in seen} == {"wilkinson_power_divider"}
        required = {"job_id", "solver", "template", "grid_tier", "duration_s", "duration_source"}
        assert all(required <= set(d) for d in seen)

    def test_gate_rejection_persists_to_schedule_json(self, recipe_path, tmp_path):
        plan = plan_campaign(recipe_path)
        plan["scheduling"] = schedule_plan_jobs(plan, budget_gate=_reject_license_gate)
        save_plan(plan, tmp_path / "camp")
        data = json.loads((tmp_path / "camp" / SCHEDULE_FILE_NAME).read_text(encoding="utf-8"))
        assert [r["stage"] for r in data["rejected"]] == ["final_verify"]
        assert data["budget_gate_used"] is True


# ── best-effort（#105）：调度器异常不阻塞战役 ─────────────────────────────────

class TestBestEffort:
    def test_gate_exception_does_not_block_campaign(self, recipe_path):
        plan = plan_campaign(recipe_path)
        s = schedule_plan_jobs(plan, budget_gate=_exploding_gate)
        assert s["ok"] is False
        assert "#105" in s["warning"] and "炸" in s["warning"]
        assert s["dispatch"] == [] and s["rejected"] == [] and s["n_jobs"] == 6
        assert s["audit"]["ok"] is False and s["budget_gate_used"] is True
        # 计划本体不受影响
        assert plan["ok"] is True
        assert [x["stage"] for x in plan["stages"]] == STAGE_ORDER

    def test_plan_campaign_survives_wiring_failure(self, recipe_path, monkeypatch):
        import rfauto.service.orchestration_wiring as ow

        def _boom(*_a, **_k):
            raise RuntimeError("wiring down")

        monkeypatch.setattr(ow, "schedule_campaign_jobs", _boom)
        plan = plan_campaign(recipe_path)
        assert plan["ok"] is True
        assert plan["scheduling"]["ok"] is False
        assert "wiring down" in plan["scheduling"]["warning"]
        assert [x["stage"] for x in plan["stages"]] == STAGE_ORDER

    def test_failed_scheduling_still_persists_for_audit(self, recipe_path, tmp_path):
        plan = plan_campaign(recipe_path)
        plan["scheduling"] = schedule_plan_jobs(plan, budget_gate=_exploding_gate)
        save_plan(plan, tmp_path / "camp")
        data = json.loads((tmp_path / "camp" / SCHEDULE_FILE_NAME).read_text(encoding="utf-8"))
        assert data["ok"] is False and "#105" in data["warning"]


# ── 落盘：runs/<campaign>/schedule.json ───────────────────────────────────────

class TestPersistence:
    def test_save_plan_writes_schedule_json(self, recipe_path, tmp_path):
        plan = plan_campaign(recipe_path)
        out = save_plan(plan, tmp_path / "runs" / "camp_001")
        assert out.name == "campaign.plan.json"
        sj = out.parent / SCHEDULE_FILE_NAME
        assert sj.exists()
        data = json.loads(sj.read_text(encoding="utf-8"))
        assert data["schema"] == "rfauto-campaign-schedule-v1"
        assert [d["stage"] for d in data["dispatch"]] == DISPATCH_ORDER
        assert data["rejected"] == [] and data["audit"]["ok"] is True
        assert data["decision_log"] and data["capacities"]["solver:hfss"] == 1
        # 规范化（sort_keys）：逐字节可复现
        expected = json.dumps(plan["scheduling"], ensure_ascii=False, indent=1,
                              sort_keys=True, default=str)
        assert sj.read_text(encoding="utf-8") == expected
        # 计划文件本体也携带同一份 scheduling（状态查询口可见）
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert saved["scheduling"]["dispatch"] == plan["scheduling"]["dispatch"]

    def test_save_plan_without_scheduling_writes_no_schedule(self, recipe_path, tmp_path):
        plan = plan_campaign(recipe_path)
        plan.pop("scheduling")
        out = save_plan(plan, tmp_path / "legacy")
        assert out.exists()
        assert not (out.parent / SCHEDULE_FILE_NAME).exists()

    def test_resave_after_event_is_idempotent(self, recipe_path, tmp_path):
        from rfauto.service.campaign_manager import apply_event, load_plan

        plan = plan_campaign(recipe_path)
        out_dir = tmp_path / "camp"
        save_plan(plan, out_dir)
        before = (out_dir / SCHEDULE_FILE_NAME).read_text(encoding="utf-8")
        loaded = load_plan(out_dir)["plan"]
        apply_event(loaded, "calibrate", "stage_done")
        save_plan(loaded, out_dir)
        assert (out_dir / SCHEDULE_FILE_NAME).read_text(encoding="utf-8") == before


# ── 席位记账：B-29 JobRegistry 路径 ───────────────────────────────────────────

class TestSeatLedger:
    def test_seats_land_in_injected_registry(self, recipe_path):
        reg = JobRegistry()
        s = schedule_campaign_jobs(plan_campaign(recipe_path), registry=reg)
        occ = reg.seat_occupancy()
        assert occ["solver:hfss"] == ["campaign:final_verify"]
        assert occ["class:pure"] == ["campaign:prefilter", "campaign:tolerance"]
        assert occ["solver:openems"] == ["campaign:calibrate", "campaign:tune"]
        assert s["seat_occupancy"] == occ
        # report 已登记但未到计划时刻，不占座
        assert reg.get("campaign:report") is not None
        assert reg.seats_of("campaign:report") == ()

    def test_wiring_passes_predictor_and_gate_to_kernel(self):
        pred = _StubPredictor({("pure", "", ""): 5.0})
        w = OrchestrationWiring(registry=JobRegistry(), probe=plan_time_probe,
                                predictor=pred, budget_gate=_reject_license_gate,
                                use_global_registry=False)
        d = w.job_arrived("j1", "pure", duration_s=0.0, emit=False)
        assert d["status"] == "running" and d["end_s"] == 5.0
        assert w.plan["assignments"][0]["duration_source"] == "predicted"
        rejected = w.job_arrived("h1", "hfss", duration_s=10.0, emit=False)
        assert rejected["status"] == "budget_rejected"
        assert w.seat_occupancy() == {"class:pure": ["j1"]}
