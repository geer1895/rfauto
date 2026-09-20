"""核心域模型单元测试。"""

import json

import pytest

from rfauto.core.errors import (
    AdapterError,
    ConfigError,
    ConnectFailedError,
    ContractViolationError,
    LicenseError,
    ModelBuildError,
    OptimizationDivergedError,
    RFAutoError,
    SimulationFailedError,
)
from rfauto.core.events import Event, EventBus, EventType
from rfauto.core.objectives import MetricOp, Objective, QuotaLimits
from rfauto.core.parameters import ParameterSystem, ParamValue
from rfauto.core.state import (
    JobRecord,
    JobState,
    can_transition,
    generate_job_id,
    generate_run_id,
)

# ── Errors ────────────────────────────────────────────────────────────────────

class TestErrors:
    def test_hierarchy(self):
        assert issubclass(ConfigError, RFAutoError)
        assert issubclass(ContractViolationError, RFAutoError)
        assert issubclass(AdapterError, RFAutoError)
        assert issubclass(ConnectFailedError, AdapterError)
        assert issubclass(ModelBuildError, AdapterError)
        assert issubclass(SimulationFailedError, AdapterError)
        assert issubclass(LicenseError, RFAutoError)
        assert issubclass(OptimizationDivergedError, RFAutoError)

    def test_to_dict(self):
        err = ModelBuildError("几何无效", details={"object": "Box1"})
        d = err.to_dict()
        assert d["error_type"] == "ModelBuildError"
        assert "几何无效" in d["message"]
        assert d["details"]["object"] == "Box1"


# ── Parameters ────────────────────────────────────────────────────────────────

class TestParamValue:
    def test_to_hfss_expr(self):
        p = ParamValue(name="arm_len", value=20.5, unit="mm")
        assert p.to_hfss_expr() == "20.5mm"

    def test_to_hfss_expr_string(self):
        p = ParamValue(name="substrate", value="rogers4350b")
        assert p.to_hfss_expr() == "rogers4350b"

    def test_to_setup_dict(self):
        p = ParamValue(name="arm_len", value=20.5, unit="mm")
        assert p.to_setup_dict() == {"arm_len": "20.5mm"}


class TestParameterSystem:
    def test_update(self):
        params = {
            "arm_len": ParamValue(name="arm_len", value=20.5, unit="mm"),
            "width": ParamValue(name="width", value=1.0, unit="mm"),
        }
        ps = ParameterSystem(params)
        ps.update({"arm_len": 21.0})
        assert ps.params["arm_len"].value == 21.0
        assert "arm_len" in ps.dirty

    def test_update_unknown_raises(self):
        ps = ParameterSystem({"arm_len": ParamValue(name="arm_len", value=20.5)})
        with pytest.raises(KeyError, match="未知参数"):
            ps.update({"nonexistent": 1.0})

    def test_canonical_json(self):
        ps = ParameterSystem({
            "b": ParamValue(name="b", value=2.0),
            "a": ParamValue(name="a", value=1.0),
        })
        j = ps.to_canonical_json()
        data = json.loads(j)
        assert list(data.keys()) == ["a", "b"]  # sorted


# ── State ─────────────────────────────────────────────────────────────────────

class TestJobState:
    def test_valid_transitions(self):
        assert can_transition(JobState.QUEUED, JobState.PREPARING)
        assert can_transition(JobState.SOLVING, JobState.POSTPROCESSING)
        assert can_transition(JobState.SOLVING, JobState.TIMEOUT)

    def test_invalid_transitions(self):
        assert not can_transition(JobState.DONE, JobState.SOLVING)
        assert not can_transition(JobState.FAILED, JobState.QUEUED)
        assert not can_transition(JobState.CANCELLED, JobState.PREPARING)

    def test_job_record_transition(self):
        rec = JobRecord(job_id="j1", run_id="r1")
        rec.transition_to(JobState.PREPARING)
        assert rec.state == JobState.PREPARING

    def test_job_record_invalid_transition_raises(self):
        rec = JobRecord(job_id="j1", run_id="r1", state=JobState.DONE)
        with pytest.raises(ValueError, match="非法状态迁移"):
            rec.transition_to(JobState.SOLVING)

    def test_generate_ids(self):
        run_id = generate_run_id()
        assert len(run_id) > 10
        job_id = generate_job_id()
        assert job_id.startswith("job_")


# ── Events ────────────────────────────────────────────────────────────────────

class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.subscribe(EventType.TRIAL_COMPLETED, lambda e: received.append(e))
        bus.emit(Event(event_type=EventType.TRIAL_COMPLETED, run_id="r1", message="done"))
        assert len(received) == 1
        assert received[0].run_id == "r1"

    def test_global_subscribe(self):
        bus = EventBus()
        received = []
        bus.subscribe_all(lambda e: received.append(e))
        bus.emit(Event(event_type=EventType.ERROR, message="err"))
        bus.emit(Event(event_type=EventType.WARNING, message="warn"))
        assert len(received) == 2

    def test_jsonl_output(self, tmp_path):
        bus = EventBus()
        bus.set_jsonl_sink(tmp_path / "events.jsonl")
        bus.emit(Event(event_type=EventType.RUN_CREATED, run_id="r1"))
        content = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
        data = json.loads(content.strip())
        assert data["event_type"] == "run_created"
        assert data["run_id"] == "r1"


# ── Objectives ────────────────────────────────────────────────────────────────

class TestObjectives:
    def test_quota_limits(self):
        ql = QuotaLimits(max_trials=100, max_wall_hours=24)
        assert ql.max_trials == 100

    def test_objective_model(self):
        obj = Objective(metric="s11_db", band=[2.3, 2.5], op=MetricOp.MAX_BELOW, value=-15)
        assert obj.weight == 1.0
