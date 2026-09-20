"""G13 稀缺资源调度器单测（方案 §10.7 G13 / §10.18 第 10 条）。

全部离线确定性：license 探测一律注入 fake（不碰真 license server / 网络），
时刻来自离散事件仿真（无墙钟），因此同一输入可逐字节复现。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service.resource_scheduler import (
    ResourceJob,
    SchedulerConfig,
    audit_schedule,
    format_decision_log,
    schedule,
    schedule_json,
)


def _probe_available(server: str | None = None, *, timeout_s: float = 0.0) -> dict:
    return {"available": True, "server": server, "detail": "test stub available"}


def _probe_unavailable(server: str | None = None, *, timeout_s: float = 0.0) -> dict:
    return {"available": False, "server": server, "detail": "test stub unavailable"}


def _jobs(*specs: tuple[str, str, float]) -> list[ResourceJob]:
    return [ResourceJob(job_id=jid, solver=solver, duration_s=dur) for jid, solver, dur in specs]


def _by_solver(result: dict, solver: str) -> list[dict]:
    return [a for a in result["assignments"] if a["solver"] == solver]


def _overlap(a: dict, b: dict) -> bool:
    """半开区间重叠（end == start 视为不重叠）。"""
    return min(a["end_s"], b["end_s"]) > max(a["start_s"], b["start_s"]) + 1e-9


def _mixed_jobs() -> list[ResourceJob]:
    return _jobs(
        ("hfss_1", "hfss", 100.0),
        ("hfss_2", "hfss", 50.0),
        ("comsol_1", "comsol", 80.0),
        ("oems_1", "openems", 30.0),
        ("oems_2", "openems", 30.0),
        ("oems_3", "openems", 30.0),
    )


class TestMixedResources:
    def test_hfss_serial_comsol_parallel_openems_capped(self):
        """HFSS×2 串行、COMSOL 与 HFSS 并行、openEMS×3 峰值恰为 3。"""
        result = schedule(_mixed_jobs(), probe=_probe_available)

        hfss = _by_solver(result, "hfss")
        assert len(hfss) == 2
        assert not _overlap(hfss[0], hfss[1]), "同 solver license 席位必须串行"

        comsol = _by_solver(result, "comsol")
        assert len(comsol) == 1
        assert any(_overlap(comsol[0], h) for h in hfss), "不同 solver 应可并行"

        assert result["peak_concurrency"]["by_solver"]["openems"] == 3
        assert not result["unassigned"]
        assert audit_schedule(result)["ok"]

    def test_openems_five_jobs_peak_never_exceeds_three(self):
        """openEMS×5：峰值并发 ≤3，且 5 个全部最终被调度。"""
        jobs = _jobs(*[(f"oems_{i}", "openems", 10.0) for i in range(5)])
        result = schedule(jobs, probe=_probe_available)

        assert len(result["assignments"]) == 5
        assert result["peak_concurrency"]["by_solver"]["openems"] == 3

        # 任意时刻重叠数 ≤ 3（逐对区间扫描）
        for i, a in enumerate(result["assignments"]):
            live = [b for b in result["assignments"][i + 1:] if _overlap(a, b)]
            assert len(live) <= 2, f"{a['job_id']} 时刻重叠超过容量"
        assert audit_schedule(result)["ok"]

    def test_research_serialized_default(self):
        """research 默认容量 1 → 两个 research 作业不重叠。"""
        jobs = _jobs(("r1", "research", 10.0), ("r2", "research", 10.0))
        result = schedule(jobs, probe=_probe_available)
        assert result["peak_concurrency"]["by_class"]["research"] == 1
        a, b = result["assignments"]
        assert not _overlap(a, b)
        assert b["start_s"] == pytest.approx(10.0)


class TestLicenseDiscipline:
    def test_license_unavailable_waits_not_fails(self, monkeypatch):
        """license 不可用 → 等待（waiting）而非失败/崩溃；其它作业照常跑。"""
        monkeypatch.setattr(
            "rfauto.service.resource_scheduler.probe_license", _probe_unavailable)

        jobs = _jobs(("hfss_1", "hfss", 10.0), ("oems_1", "openems", 10.0))
        result = schedule(jobs, SchedulerConfig(time_horizon_s=100.0))

        assert [a["job_id"] for a in result["assignments"]] == ["oems_1"]
        waiting = [u for u in result["unassigned"] if u["job_id"] == "hfss_1"]
        assert waiting and waiting[0]["status"] == "waiting"
        assert "license 不可用" in waiting[0]["reason"]

        waits = [e for e in result["decision_log"]
                 if e["event"] == "wait" and e["job_id"] == "hfss_1"]
        assert waits and all(e["reason"] for e in waits)
        assert result["probe_attempts"] >= 2
        assert audit_schedule(result)["ok"]

    def test_license_recovered_within_wait_budget(self):
        """探测先失败后恢复：在等待预算内作业被正常调度。"""
        calls = {"n": 0}

        def flaky(server: str | None = None) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"available": False, "server": server, "detail": "warming up"}
            return {"available": True, "server": server, "detail": "ok"}

        result = schedule(
            [ResourceJob("hfss_1", "hfss", 10.0)],
            SchedulerConfig(license_poll_s=10.0),
            probe=flaky,
        )
        assert len(result["assignments"]) == 1
        assert result["assignments"][0]["start_s"] == pytest.approx(10.0)
        assert not result["unassigned"]
        assert calls["n"] == 2

    def test_license_wait_exceeds_budget_is_deferred(self, monkeypatch):
        """超等待预算的 license 作业标记 deferred，并留 defer 审计事件。"""
        monkeypatch.setattr(
            "rfauto.service.resource_scheduler.probe_license", _probe_unavailable)
        result = schedule(
            [ResourceJob("hfss_1", "hfss", 10.0)],
            SchedulerConfig(license_poll_s=5.0, license_max_wait_s=12.0),
        )
        assert not result["assignments"]
        assert result["unassigned"][0]["status"] == "deferred"
        defers = [e for e in result["decision_log"] if e["event"] == "defer"]
        assert len(defers) == 1 and defers[0]["reason"]
        assert audit_schedule(result)["ok"]

    def test_probe_exception_is_best_effort(self):
        """探测抛异常不得成为主路径故障点（#105）：按可用处理，作业照常调度。"""
        def boom(server: str | None = None) -> dict:
            raise RuntimeError("probe exploded")

        result = schedule([ResourceJob("hfss_1", "hfss", 10.0)], probe=boom)
        assert [a["job_id"] for a in result["assignments"]] == ["hfss_1"]
        assert result["probe_attempts"] == 1
        probe_events = [e for e in result["decision_log"] if e["event"] == "probe"]
        assert probe_events and "best-effort" in probe_events[0]["detail"]


class TestAuditabilityAndDeterminism:
    def test_decision_log_records_wait_reason_and_holders(self):
        result = schedule(_mixed_jobs(), probe=_probe_available)
        waits = [e for e in result["decision_log"] if e["event"] == "wait"]
        assert waits, "混合场景应存在等待事件"
        assert all(e["reason"].strip() for e in waits)

        hfss_wait = next(e for e in waits if e["job_id"] == "hfss_2")
        assert "容量已满" in hfss_wait["reason"]
        assert hfss_wait["blocking"]["solver:hfss"] == ["hfss_1"]

        releases = [e for e in result["decision_log"] if e["event"] == "release"]
        assert releases and all(e["resources"] for e in releases)
        assert format_decision_log(result)
        assert audit_schedule(result)["ok"]

    def test_audit_flags_missing_wait_reason(self):
        """审计器本身必须能抓出被篡改的日志（防止审计形同虚设）。"""
        result = schedule(_mixed_jobs(), probe=_probe_available)
        for event in result["decision_log"]:
            if event["event"] == "wait":
                event["reason"] = ""
                break
        audit = audit_schedule(result)
        assert not audit["ok"]
        assert any("无 reason" in issue for issue in audit["issues"])

    def test_same_input_is_byte_identical(self):
        """同一输入两次调度结果逐字节一致。"""
        jobs = _mixed_jobs()
        first = schedule(jobs, probe=_probe_available)
        second = schedule(jobs, probe=_probe_available)
        assert json.dumps(first, sort_keys=True, ensure_ascii=False) == json.dumps(
            second, sort_keys=True, ensure_ascii=False)
        assert schedule_json(jobs, probe=_probe_available) == schedule_json(
            jobs, probe=_probe_available)
        assert schedule_json(jobs, probe=_probe_available) == json.dumps(
            first, sort_keys=True, ensure_ascii=False)

    def test_input_order_is_priority(self):
        """同等到达时刻下，输入顺序即优先序（确定性仲裁）。"""
        jobs = [
            ResourceJob("second", "hfss", 10.0),
            ResourceJob("first", "hfss", 10.0),
        ]
        result = schedule(jobs, probe=_probe_available)
        assert [a["job_id"] for a in result["assignments"]] == ["second", "first"]


class TestCapacityConfig:
    def test_pure_capacity_configurable(self):
        jobs = _jobs(("p1", "pure", 10.0), ("p2", "pure", 10.0))

        default_result = schedule(jobs, probe=_probe_available)
        assert default_result["peak_concurrency"]["by_class"]["pure"] == 2

        cfg = SchedulerConfig(class_capacity={"fdtd": 3, "pure": 1, "research": 1, "gpu": 0})
        tight = schedule(jobs, cfg, probe=_probe_available)
        assert tight["peak_concurrency"]["by_class"]["pure"] == 1
        a, b = tight["assignments"]
        assert not _overlap(a, b)

    def test_gpu_disabled_by_default(self):
        """GPU 默认禁用（容量 0）→ 作业等待，其它资源不受影响。"""
        jobs = _jobs(("gpu_1", "gpu", 10.0), ("pure_1", "pure", 10.0))
        result = schedule(jobs, probe=_probe_available)

        assert "gpu_1" not in [a["job_id"] for a in result["assignments"]]
        assert "pure_1" in [a["job_id"] for a in result["assignments"]]
        gpu = next(u for u in result["unassigned"] if u["job_id"] == "gpu_1")
        assert gpu["status"] == "waiting"
        assert "class:gpu 0/0" in gpu["reason"]

    def test_empty_input_and_duplicate_ids(self):
        empty = schedule([], probe=_probe_available)
        assert empty["assignments"] == [] and empty["decision_log"] == []
        assert empty["peak_concurrency"]["overall"] == 0

        with pytest.raises(ValueError, match="重复"):
            schedule(_jobs(("dup", "hfss", 1.0), ("dup", "comsol", 1.0)),
                     probe=_probe_available)
