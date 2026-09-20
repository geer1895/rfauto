"""B-29 编排接线单测：campaign 阶段事件 → EventBus；作业事件流 → G13 调度 + 席位账目。

全部离线确定性：license 探测注入 fake（不碰真 license server / 网络），
时刻来自离散事件仿真（接线层 clock_s），无墙钟、无随机数、无真机。
"""

from __future__ import annotations

import json

from rfauto.core.events import EventBus, EventType
from rfauto.service.job_registry import JobRegistry
from rfauto.service.orchestration_wiring import (
    OrchestrationWiring,
    adapter_solver,
)
from rfauto.service.resource_scheduler import SchedulerConfig


def _probe_available(server=None, *, timeout_s=0.0):
    return {"available": True, "server": server, "detail": "test stub available"}


def _probe_unavailable(server=None, *, timeout_s=0.0):
    return {"available": False, "server": server, "detail": "no seat"}


def _plan(*stages):
    return {"stages": list(stages)}


def _stage(name, adapter, license_gated=False):
    return {"stage": name, "adapter": adapter, "license_gated": license_gated}


class TestCampaignEventExport:
    def test_stage_events_reach_bus_with_decision_data(self):
        bus = EventBus()
        events = []
        bus.subscribe_all(events.append)
        reg = JobRegistry()
        w = OrchestrationWiring(registry=reg, event_bus=bus,
                                probe=_probe_available)
        plan = _plan(_stage("calibrate", "openems"),
                     _stage("final_verify", "hfss", license_gated=True))

        started = w.campaign_stage(plan, "calibrate", "stage_started",
                                   run_id="run_1")
        assert started["ok"] is True
        assert started["emitted_type"] == "trial_started"
        assert started["solver"] == "openems"
        assert started["decision"]["status"] == "running"
        assert started["decision"]["seats"] == ["solver:openems", "class:fdtd"]
        assert started["event_id"]

        done = w.campaign_stage(plan, "calibrate", "stage_done", run_id="run_1")
        assert done["emitted_type"] == "trial_completed"
        assert done["decision"]["released_seats"] == [
            "solver:openems", "class:fdtd"]

        assert [e.event_type for e in events] == [
            EventType.TRIAL_STARTED, EventType.TRIAL_COMPLETED]
        assert events[0].run_id == "run_1"
        assert events[0].job_id == "campaign:calibrate"
        assert events[0].data["stage"] == "calibrate"
        assert events[0].data["campaign_event"] == "stage_started"
        assert events[0].data["decision"]["solver"] == "openems"
        assert w.seat_occupancy() == {}

    def test_hfss_stage_gets_license_seat(self):
        reg = JobRegistry()
        w = OrchestrationWiring(registry=reg, event_bus=EventBus(),
                                probe=_probe_available)
        plan = _plan(_stage("final_verify", "hfss", license_gated=True))
        r = w.campaign_stage(plan, "final_verify", "stage_started", run_id="r")
        assert r["ok"] is True
        assert r["decision"]["resource_class"] == "license"
        assert r["decision"]["seats"] == ["solver:hfss"]
        assert reg.seat_occupancy() == {"solver:hfss": ["campaign:final_verify"]}
        assert w.plan is not None and w.plan["capacities"]["solver:hfss"] == 1

    def test_unknown_stage_or_event_rejected(self):
        w = OrchestrationWiring(registry=JobRegistry(), event_bus=EventBus(),
                                probe=_probe_available)
        plan = _plan(_stage("tune", "openems"))
        bad_stage = w.campaign_stage(plan, "nope", "stage_started")
        assert bad_stage["ok"] is False and bad_stage["event"] is None
        bad_event = w.campaign_stage(plan, "tune", "nope")
        assert bad_event["ok"] is False
        # 未知事件不应留下任何登记/占座副作用
        assert w.active_jobs() == [] and w.seat_occupancy() == {}


class TestJobEventStream:
    def test_hfss_seats_serialized_and_queryable(self):
        reg = JobRegistry()
        w = OrchestrationWiring(registry=reg, event_bus=EventBus(),
                                probe=_probe_available)
        first = w.job_arrived("job_a", "hfss", duration_s=100.0)
        second = w.job_arrived("job_b", "hfss", duration_s=50.0)

        assert first["status"] == "running"
        assert first["seats"] == ["solver:hfss"]
        assert second["status"] == "assigned"
        assert second["seats"] == []
        assert second["planned_seats"] == ["solver:hfss"]
        assert second["start_s"] == 100.0

        # 席位占用可查（注册表口径 + 接线器口径一致）
        assert reg.seat_occupancy() == {"solver:hfss": ["job_a"]}
        assert w.seat_occupancy() == {"solver:hfss": ["job_a"]}
        assert reg.seats_of("job_a") == ("solver:hfss",)
        assert reg.seats_of("job_b") == ()
        assert reg.get("job_a")["seats"] == ["solver:hfss"]
        assert w.holders_at() == {"solver:hfss": ["job_a"]}

        released = w.job_released("job_a")
        assert released["ok"] is True
        assert released["released_seats"] == ["solver:hfss"]
        assert reg.seats_of("job_a") == ()
        assert reg.seats_of("job_b") == ("solver:hfss",)
        assert w.seat_occupancy() == {"solver:hfss": ["job_b"]}
        assert w.active_jobs() == ["job_b"]
        assert w.releases()[-1]["job_id"] == "job_a"

    def test_openems_class_capacity_three_of_four(self):
        reg = JobRegistry()
        w = OrchestrationWiring(registry=reg, event_bus=EventBus(),
                                probe=_probe_available)
        decisions = [w.job_arrived(f"o{i}", "openems", duration_s=30.0,
                                   emit=False) for i in range(4)]
        assert [d["status"] for d in decisions] == [
            "running", "running", "running", "assigned"]
        occ = w.seat_occupancy()
        assert occ["solver:openems"] == ["o0", "o1", "o2"]
        assert occ["class:fdtd"] == ["o0", "o1", "o2"]
        assert all(len(v) <= 3 for v in occ.values())
        assert reg.seat_occupancy() == occ

    def test_license_unavailable_waits_and_emits_license_wait(self):
        bus = EventBus()
        events = []
        bus.subscribe_all(events.append)
        w = OrchestrationWiring(
            registry=JobRegistry(), event_bus=bus, probe=_probe_unavailable,
            config=SchedulerConfig(time_horizon_s=100.0))
        decision = w.job_arrived("h1", "hfss", duration_s=10.0)
        assert decision["status"] == "waiting"
        assert "license" in decision["reason"]
        assert decision["seats"] == []
        assert events and events[-1].event_type == EventType.LICENSE_WAIT
        assert w.seat_occupancy() == {}

    def test_release_unknown_is_idempotent(self):
        w = OrchestrationWiring(registry=JobRegistry(), event_bus=EventBus(),
                                probe=_probe_available)
        result = w.job_released("ghost")
        assert result["ok"] is False
        assert result["status"] == "unknown"
        assert result["released_seats"] == []
        assert w.active_jobs() == []

    def test_duplicate_arrival_rejected(self):
        w = OrchestrationWiring(registry=JobRegistry(), event_bus=EventBus(),
                                probe=_probe_available)
        w.job_arrived("dup", "hfss", duration_s=10.0, emit=False)
        try:
            w.job_arrived("dup", "hfss", duration_s=10.0, emit=False)
        except ValueError as exc:
            assert "已登记" in str(exc)
        else:  # pragma: no cover - 明确失败分支
            raise AssertionError("重复到达应抛 ValueError")

    def test_event_stream_is_deterministic(self):
        def run():
            w = OrchestrationWiring(registry=JobRegistry(), event_bus=EventBus(),
                                    probe=_probe_available)
            out = [w.job_arrived("a", "hfss", duration_s=40.0, emit=False),
                   w.job_arrived("b", "openems", duration_s=10.0, emit=False),
                   w.job_arrived("c", "hfss", duration_s=5.0, emit=False)]
            out.append(w.job_released("a", emit=False))
            out.append(w.seat_occupancy())
            return out

        first = json.dumps(run(), sort_keys=True, ensure_ascii=False)
        second = json.dumps(run(), sort_keys=True, ensure_ascii=False)
        assert first == second


class TestSeatLedgerRegistry:
    def test_registry_seat_accounting_roundtrip(self):
        reg = JobRegistry()
        reg.create("job_x")
        assert reg.seats_of("job_x") == ()
        assert reg.assign_seats("job_x", ["solver:hfss", "class:fdtd"]) is True
        assert reg.seats_of("job_x") == ("solver:hfss", "class:fdtd")
        assert reg.seat_occupancy() == {
            "solver:hfss": ["job_x"], "class:fdtd": ["job_x"]}
        assert reg.get("job_x")["seats"] == ["solver:hfss", "class:fdtd"]
        assert reg.release_seats("job_x") == ("solver:hfss", "class:fdtd")
        assert reg.seat_occupancy() == {}
        assert reg.assign_seats("ghost", ["solver:hfss"]) is False
        assert reg.release_seats("ghost") == ()


class TestAdapterSolverMapping:
    def test_free_channels_fall_back_to_pure(self):
        assert adapter_solver("hfss") == "hfss"
        assert adapter_solver("OpenEMS") == "openems"
        assert adapter_solver("comsol") == "comsol"
        assert adapter_solver("surrogate") == "pure"
        assert adapter_solver("local") == "pure"
        assert adapter_solver("fake") == "pure"
        assert adapter_solver(None) == "pure"
