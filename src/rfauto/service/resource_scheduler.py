"""G13 稀缺资源调度器 —— 确定性资源仲裁内核 + 可审计决策日志。

背景（稀缺资源确定性仲裁，多轨并发复盘沉淀）：
多轨并发此前靠人工"轨内串行"约定避免抢 license / 抢 CPU，
本模块把该约定固化为确定性内核。

资源模型（默认容量，全部可配置）
- license 类：hfss/comsol/ads/aedt 各 1 席位（同 solver 串行，异 solver 并行）
- FDTD 类：openems 并发 ≤3（class:fdtd 与 solver:openems 双重上限）
- CPU 类：pure ≤2、research ≤1
- GPU 默认禁用（class:gpu 容量 0）

设计约束
- 确定性：给定相同输入（顺序敏感的作业列表 + 配置），输出逐字节一致；
  不使用墙钟时间/随机数/集合迭代顺序，时刻全部来自离散事件仿真。
- 可审计：每个决策（assign/wait/release/probe/defer/budget_reject）都写入
  decision_log，等待事件必带 reason 与占用者，audit_schedule() 可离线校验。
- best-effort（#105）：license 探测异常绝不抛出主路径——异常按"假设可用"
  处理（观测性代码不得阻塞真机求解），探测报告不可用只让作业等待。

消费 G14 分档时长预测（pipeline/quota_guard.TieredDurationPredictor）：
- ``predictor`` 注入后，``duration_s<=0``（未申报）的作业按其
  (solver, template, grid_tier) 分档预测填充时长（预测 unknown 则不编造，
  按申报值处理并标注 ``duration_source="unknown_fallback_declared"``）；
- 同到达时刻的作业改为**预测时长短者优先**（SJF，输入序作平局），即调度
  顺序受预测影响；未注入 predictor 时排程逐字节不变（输入序=优先序）。
- ``budget_gate`` 注入后（quota_guard.budget_admission_gate 构造），作业
  获得资源前先过预算准入门，拒绝者落 ``unassigned`` status=``budget_rejected``
  并留 ``budget_reject`` 审计事件（带 reason）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from rfauto.infra.license_probe import probe_license
from rfauto.pipeline.quota_guard import TieredDurationPredictor

logger = logging.getLogger(__name__)

_EPS = 1e-9

#: 需要 license 席位的求解器（同 solver 串行、异 solver 并行）
LICENSE_SOLVERS = ("hfss", "comsol", "ads", "aedt")
#: FDTD 类求解器（类级并发上限）
FDTD_SOLVERS = ("openems",)
#: 以"资源类"直接命名的求解器（pure/research/gpu）
CLASS_SOLVERS = ("pure", "research", "gpu")

DEFAULT_SOLVER_CAPACITY: dict[str, int] = {
    "hfss": 1,
    "comsol": 1,
    "ads": 1,
    "aedt": 1,
    "openems": 3,
}
DEFAULT_CLASS_CAPACITY: dict[str, int] = {
    "fdtd": 3,
    "pure": 2,
    "research": 1,
    "gpu": 0,  # GPU 默认禁用
}

DEFAULT_LICENSE_POLL_S = 30.0
DEFAULT_LICENSE_MAX_WAIT_S = 600.0


@dataclass(frozen=True)
class ResourceJob:
    """一个待调度作业：资源声明 + 预估耗时 + 到达时刻（+ 可选分档维度）。

    ``template`` / ``grid_tier`` 为分档预测维度（空串=未申报）；
    ``duration_s<=0`` 表示"时长未申报"，注入 predictor 时由分档预测填充。
    """

    job_id: str
    solver: str
    duration_s: float = 60.0
    arrival_s: float = 0.0
    template: str = ""
    grid_tier: str = ""

    def normalized(self) -> ResourceJob:
        """收敛入参：solver 小写去空格、耗时不小于 0、到达不早于 0（#140）。"""
        return ResourceJob(
            job_id=str(self.job_id),
            solver=str(self.solver).strip().lower(),
            duration_s=max(0.0, float(self.duration_s)),
            arrival_s=max(0.0, float(self.arrival_s)),
            template=str(self.template or "").strip(),
            grid_tier=str(self.grid_tier or "").strip(),
        )


@dataclass
class SchedulerConfig:
    """调度器容量与等待纪律（全部可配置）。"""

    solver_capacity: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_SOLVER_CAPACITY))
    class_capacity: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_CLASS_CAPACITY))
    license_poll_s: float = DEFAULT_LICENSE_POLL_S
    license_max_wait_s: float = DEFAULT_LICENSE_MAX_WAIT_S
    license_server: str | None = None
    probe_timeout_s: float = 3.0
    time_horizon_s: float | None = None


@dataclass(frozen=True)
class _Running:
    job: ResourceJob
    cls: str
    keys: tuple[str, ...]
    start_s: float
    end_s: float


def solver_class(solver: str) -> str:
    """求解器 → 资源类（license/fdtd/pure/research/gpu/generic）。"""
    s = str(solver).strip().lower()
    if s in LICENSE_SOLVERS:
        return "license"
    if s in FDTD_SOLVERS:
        return "fdtd"
    if s in CLASS_SOLVERS:
        return s
    return "generic"


def required_resources(job: ResourceJob, config: SchedulerConfig | None = None) -> list[tuple[str, int]]:
    """返回作业需要占用的 (资源键, 容量) 列表——审计/展示共用同一口径。"""
    cfg = config or SchedulerConfig()
    s = job.solver
    cls = solver_class(s)
    if cls == "license":
        return [(f"solver:{s}", int(cfg.solver_capacity.get(s, 1)))]
    if cls == "fdtd":
        solver_cap = int(cfg.solver_capacity.get(s, DEFAULT_SOLVER_CAPACITY.get(s, 1)))
        class_cap = int(cfg.class_capacity.get("fdtd", DEFAULT_CLASS_CAPACITY["fdtd"]))
        return [(f"solver:{s}", solver_cap), ("class:fdtd", class_cap)]
    if cls in CLASS_SOLVERS:
        return [(f"class:{cls}", int(cfg.class_capacity.get(cls, DEFAULT_CLASS_CAPACITY.get(cls, 1))))]
    return [(f"solver:{s}", int(cfg.solver_capacity.get(s, 1)))]


def _coerce_job(job: ResourceJob | dict[str, Any]) -> ResourceJob:
    if isinstance(job, ResourceJob):
        return job.normalized()
    if isinstance(job, dict):
        return ResourceJob(
            job_id=str(job.get("job_id", job.get("id", ""))),
            solver=str(job.get("solver", "pure")),
            duration_s=float(job.get("duration_s", 60.0)),
            arrival_s=float(job.get("arrival_s", 0.0)),
            template=str(job.get("template", "") or ""),
            grid_tier=str(job.get("grid_tier", "") or ""),
        ).normalized()
    raise TypeError(f"unsupported job type: {type(job)!r}")


def _config_snapshot(cfg: SchedulerConfig) -> dict[str, Any]:
    return {
        "solver_capacity": {k: int(cfg.solver_capacity[k]) for k in sorted(cfg.solver_capacity)},
        "class_capacity": {k: int(cfg.class_capacity[k]) for k in sorted(cfg.class_capacity)},
        "license_poll_s": float(cfg.license_poll_s),
        "license_max_wait_s": float(cfg.license_max_wait_s),
        "license_server": cfg.license_server,
        "probe_timeout_s": float(cfg.probe_timeout_s),
        "time_horizon_s": None if cfg.time_horizon_s is None else float(cfg.time_horizon_s),
    }


def _holders(running: list[_Running], key: str) -> list[str]:
    """当前占用某资源键的 job_id（按开始顺序，确定性）。"""
    return [r.job.job_id for r in running if key in r.keys]


def schedule(
    jobs: list[ResourceJob | dict[str, Any]],
    config: SchedulerConfig | None = None,
    *,
    probe: Callable[[str | None], dict[str, Any]] | None = None,
    predictor: TieredDurationPredictor | None = None,
    budget_gate: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """确定性调度入口。

    Args:
        jobs: 作业列表；其顺序是同等条件下的优先序（先到先得）。
        config: 容量/等待纪律；None 用默认（license 各 1、openems ≤3、pure ≤2、
            research ≤1、GPU 禁用）。
        probe: license 探测函数（可注入以离线测试）；None 时调用
            infra.license_probe.probe_license（best-effort，#105）。
        predictor: G14 分档时长预测器；注入后 ``duration_s<=0`` 的作业
            按分档预测填充时长，且同到达时刻按预测时长短者优先（SJF）。
            None 时排程逐字节不变。
        budget_gate: 预算准入门 ``gate(job_doc) -> {"ok", "reason", ...}``
            （quota_guard.budget_admission_gate 构造）；作业获得资源前裁决，
            拒绝者落 unassigned status=budget_rejected。None 时不设门。

    Returns:
        {
          "assignments": [job_id/solver/resource_class/start_s/end_s/resources/index
                          (+duration_source 仅注入 predictor 时)],
          "unassigned": [job_id/solver/status(waiting|deferred|budget_rejected)/reason/index],
          "decision_log": [t_s/event/job_id/solver/resource_class/reason/detail/...],
          "peak_concurrency": {overall/by_solver/by_class/by_resource},
          "capacities": {resource_key: capacity},
          "config": {...}, "probe_attempts": int,
          (+"duration_predictions": {job_id: {...}} 仅注入 predictor 时)
        }
    """
    cfg = config or SchedulerConfig()
    indexed = [(i, _coerce_job(j)) for i, j in enumerate(jobs)]
    seen: set[str] = set()
    for _i, job in indexed:
        if not job.job_id:
            raise ValueError("job_id 不能为空")
        if job.job_id in seen:
            raise ValueError(f"job_id 重复: {job.job_id}")
        seen.add(job.job_id)

    # ── 分档预测填充未申报时长（不编造：unknown 按申报值处理） ──
    duration_source: dict[str, str] = {}
    duration_predictions: dict[str, dict[str, Any]] = {}
    if predictor is not None:
        filled: list[tuple[int, ResourceJob]] = []
        for i, job in indexed:
            if job.duration_s > 0.0:
                duration_source[job.job_id] = "declared"
                filled.append((i, job))
                continue
            prediction = predictor.predict_for_tier(
                job.solver, job.template, job.grid_tier)
            duration_predictions[job.job_id] = prediction.to_dict()
            if prediction.predicted_s is not None and prediction.predicted_s > 0.0:
                duration_source[job.job_id] = "predicted"
                filled.append((i, replace(job, duration_s=float(prediction.predicted_s))))
            else:
                duration_source[job.job_id] = "unknown_fallback_declared"
                filled.append((i, job))
        indexed = filled

    capacities: dict[str, int] = {}
    for _i, job in indexed:
        for key, cap in required_resources(job, cfg):
            capacities.setdefault(key, cap)

    empty_peak = {"overall": 0, "by_solver": {}, "by_class": {}, "by_resource": {}}
    if not indexed:
        empty: dict[str, Any] = {
            "assignments": [],
            "unassigned": [],
            "decision_log": [],
            "peak_concurrency": empty_peak,
            "capacities": {},
            "config": _config_snapshot(cfg),
            "probe_attempts": 0,
        }
        if predictor is not None:
            empty["duration_predictions"] = {}
        return empty

    if predictor is not None:
        # SJF：同到达时刻预测/申报时长短者优先，输入序作平局（确定性）。
        indexed.sort(key=lambda pair: (pair[1].arrival_s, pair[1].duration_s, pair[0]))
    else:
        indexed.sort(key=lambda pair: (pair[1].arrival_s, pair[0]))
    pending: list[tuple[int, ResourceJob]] = list(indexed)

    running: list[_Running] = []
    used_key: dict[str, int] = {}
    used_solver: dict[str, int] = {}
    used_class: dict[str, int] = {}
    peak_key: dict[str, int] = {}
    peak_solver: dict[str, int] = {}
    peak_class: dict[str, int] = {}
    overall_peak = 0

    decision_log: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    unassigned: list[dict[str, Any]] = []

    t = min(job.arrival_s for _i, job in indexed)
    license_state: dict[str, Any] | None = None
    wait_since: dict[str, float] = {}
    last_wait_reason: dict[str, str] = {}
    probe_attempts = 0

    def probe_license_now(now: float) -> None:
        nonlocal license_state, probe_attempts
        probe_attempts += 1
        try:
            if probe is not None:
                res = probe(cfg.license_server)
            else:
                res = probe_license(cfg.license_server, timeout_s=cfg.probe_timeout_s)
            available = bool(res.get("available", True))
            detail = str(res.get("detail", "") or "")
        except Exception as exc:  # 观测性代码 best-effort（#105）
            available = True
            detail = f"license 探测异常，假设可用（best-effort #105）: {exc}"
            logger.warning("license probe failed (best-effort, assuming available): %s", exc)
        license_state = {
            "available": available,
            "detail": detail,
            "next_probe_s": now + float(cfg.license_poll_s),
        }
        decision_log.append({
            "t_s": now,
            "event": "probe",
            "job_id": None,
            "solver": None,
            "resource_class": "license",
            "reason": "",
            "detail": detail,
            "available": available,
            "resources": [],
            "blocking": {},
        })

    def release_at(now: float) -> None:
        nonlocal running
        keep: list[_Running] = []
        for r in running:
            if r.end_s > now + _EPS:
                keep.append(r)
                continue
            for key in r.keys:
                used_key[key] = used_key.get(key, 0) - 1
            used_solver[r.job.solver] = used_solver.get(r.job.solver, 0) - 1
            used_class[r.cls] = used_class.get(r.cls, 0) - 1
            decision_log.append({
                "t_s": now,
                "event": "release",
                "job_id": r.job.job_id,
                "solver": r.job.solver,
                "resource_class": r.cls,
                "reason": "",
                "detail": f"释放资源 {'/'.join(r.keys)}",
                "resources": list(r.keys),
                "blocking": {},
            })
        running = keep

    def start_job(now: float, index: int, job: ResourceJob, keys: list[str]) -> None:
        nonlocal overall_peak
        cls = solver_class(job.solver)
        end = now + job.duration_s
        running.append(_Running(job=job, cls=cls, keys=tuple(keys), start_s=now, end_s=end))
        for key in keys:
            used_key[key] = used_key.get(key, 0) + 1
            peak_key[key] = max(peak_key.get(key, 0), used_key[key])
        used_solver[job.solver] = used_solver.get(job.solver, 0) + 1
        peak_solver[job.solver] = max(peak_solver.get(job.solver, 0), used_solver[job.solver])
        used_class[cls] = used_class.get(cls, 0) + 1
        peak_class[cls] = max(peak_class.get(cls, 0), used_class[cls])
        overall_peak = max(overall_peak, len(running))
        entry: dict[str, Any] = {
            "job_id": job.job_id,
            "solver": job.solver,
            "resource_class": cls,
            "start_s": now,
            "end_s": end,
            "duration_s": job.duration_s,
            "resources": list(keys),
            "index": index,
        }
        if predictor is not None:
            entry["duration_source"] = duration_source.get(job.job_id, "declared")
        assignments.append(entry)
        decision_log.append({
            "t_s": now,
            "event": "assign",
            "job_id": job.job_id,
            "solver": job.solver,
            "resource_class": cls,
            "reason": "",
            "detail": f"获得资源 {'/'.join(keys)}，预计 {job.duration_s:g}s",
            "resources": list(keys),
            "blocking": {},
        })

    while True:
        release_at(t)

        progress = False
        for index, job in list(pending):
            if job.arrival_s > t + _EPS:
                continue
            reqs = required_resources(job, cfg)
            blockers = {key: _holders(running, key) for key, cap in reqs if used_key.get(key, 0) >= cap}
            if blockers:
                text = "; ".join(f"{key} {used_key.get(key, 0)}/{cap}" for key, cap in reqs)
                reason = f"容量已满（{text}），占用者: " + ", ".join(
                    f"{k}<-{','.join(v)}" for k, v in blockers.items())
                last_wait_reason[job.job_id] = reason
                decision_log.append({
                    "t_s": t,
                    "event": "wait",
                    "job_id": job.job_id,
                    "solver": job.solver,
                    "resource_class": solver_class(job.solver),
                    "reason": reason,
                    "detail": "",
                    "resources": [k for k, _c in reqs],
                    "blocking": blockers,
                })
                continue

            if solver_class(job.solver) == "license":
                need_probe = license_state is None or (
                    not license_state["available"] and t + _EPS >= license_state["next_probe_s"]
                )
                if need_probe:
                    probe_license_now(t)
                if not license_state["available"]:
                    wait_since.setdefault(job.job_id, t)
                    reason = f"license 不可用（{license_state['detail']}）"
                    if t - wait_since[job.job_id] > float(cfg.license_max_wait_s):
                        pending.remove((index, job))
                        unassigned.append({
                            "job_id": job.job_id,
                            "solver": job.solver,
                            "resource_class": solver_class(job.solver),
                            "status": "deferred",
                            "reason": f"{reason}；等待 {t - wait_since[job.job_id]:g}s 超预算 "
                                      f"{cfg.license_max_wait_s:g}s",
                            "index": index,
                        })
                        decision_log.append({
                            "t_s": t,
                            "event": "defer",
                            "job_id": job.job_id,
                            "solver": job.solver,
                            "resource_class": "license",
                            "reason": unassigned[-1]["reason"],
                            "detail": "",
                            "resources": [],
                            "blocking": {},
                        })
                        progress = True
                        continue
                    last_wait_reason[job.job_id] = reason
                    decision_log.append({
                        "t_s": t,
                        "event": "wait",
                        "job_id": job.job_id,
                        "solver": job.solver,
                        "resource_class": "license",
                        "reason": reason,
                        "detail": f"下次探测 {license_state['next_probe_s']:g}s",
                        "resources": [],
                        "blocking": {},
                    })
                    continue
                wait_since.pop(job.job_id, None)

            if budget_gate is not None:
                verdict = budget_gate({
                    "job_id": job.job_id,
                    "solver": job.solver,
                    "template": job.template,
                    "grid_tier": job.grid_tier,
                    "duration_s": job.duration_s,
                    "duration_source": duration_source.get(job.job_id, "declared"),
                })
                if not bool(verdict.get("ok", False)):
                    reason = str(verdict.get("reason") or "预算门拒绝（门未给原因）")
                    pending.remove((index, job))
                    unassigned.append({
                        "job_id": job.job_id,
                        "solver": job.solver,
                        "resource_class": solver_class(job.solver),
                        "status": "budget_rejected",
                        "reason": reason,
                        "index": index,
                        "budget": dict(verdict),
                    })
                    decision_log.append({
                        "t_s": t,
                        "event": "budget_reject",
                        "job_id": job.job_id,
                        "solver": job.solver,
                        "resource_class": solver_class(job.solver),
                        "reason": reason,
                        "detail": "",
                        "resources": [],
                        "blocking": {},
                    })
                    progress = True
                    continue

            start_job(t, index, job, [k for k, _c in reqs])
            pending.remove((index, job))
            progress = True

        next_times = [r.end_s for r in running]
        if license_state is not None and not license_state["available"] and any(
                solver_class(j.solver) == "license" for _i, j in pending):
            next_times.append(float(license_state["next_probe_s"]))
        future_arrivals = [j.arrival_s for _i, j in pending if j.arrival_s > t + _EPS]
        if future_arrivals:
            next_times.append(min(future_arrivals))

        if not next_times:
            break
        nxt = min(next_times)
        if cfg.time_horizon_s is not None and nxt > float(cfg.time_horizon_s) + _EPS:
            break
        if nxt <= t + _EPS:
            if not progress:
                break
            nxt = t + _EPS
        t = nxt

    for index, job in pending:
        unassigned.append({
            "job_id": job.job_id,
            "solver": job.solver,
            "resource_class": solver_class(job.solver),
            "status": "waiting",
            "reason": last_wait_reason.get(job.job_id, "调度视界内未获资源"),
            "index": index,
        })

    peak_concurrency = {
        "overall": overall_peak,
        "by_solver": {k: peak_solver[k] for k in sorted(peak_solver)},
        "by_class": {k: peak_class[k] for k in sorted(peak_class)},
        "by_resource": {k: peak_key[k] for k in sorted(peak_key)},
    }

    result: dict[str, Any] = {
        "assignments": assignments,
        "unassigned": unassigned,
        "decision_log": decision_log,
        "peak_concurrency": peak_concurrency,
        "capacities": capacities,
        "config": _config_snapshot(cfg),
        "probe_attempts": probe_attempts,
    }
    if predictor is not None:
        result["duration_predictions"] = duration_predictions
    return result


def schedule_json(
    jobs: list[ResourceJob | dict[str, Any]],
    config: SchedulerConfig | None = None,
    *,
    probe: Callable[[str | None], dict[str, Any]] | None = None,
    predictor: TieredDurationPredictor | None = None,
    budget_gate: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> str:
    """调度结果的规范化 JSON（sort_keys，用于逐字节一致的确定性校验/落盘）。"""
    return json.dumps(
        schedule(jobs, config, probe=probe, predictor=predictor, budget_gate=budget_gate),
        sort_keys=True, ensure_ascii=False)


def _max_overlap(assignments: list[dict[str, Any]], key: str) -> int:
    events: list[tuple[float, int]] = []
    for a in assignments:
        if key in (a.get("resources") or []):
            events.append((float(a["start_s"]), 1))
            events.append((float(a["end_s"]), -1))
    events.sort(key=lambda e: (e[0], e[1]))  # 同刻先释放后占用
    cur = 0
    peak = 0
    for _t, delta in events:
        cur += delta
        peak = max(peak, cur)
    return peak


def audit_schedule(result: dict[str, Any]) -> dict[str, Any]:
    """离线审计：日志完整性 + 等待原因齐备 + 容量不被突破。

    返回 {"ok": bool, "issues": [...], "n_events", "n_assignments", "n_unassigned"}。
    """
    issues: list[str] = []
    log = result.get("decision_log") or []
    assignments = result.get("assignments") or []
    unassigned = result.get("unassigned") or []
    capacities = result.get("capacities") or {}

    for i, event in enumerate(log):
        if "t_s" not in event or "event" not in event:
            issues.append(f"decision_log[{i}] 缺少 t_s/event 字段")
        if event.get("event") in ("wait", "defer", "budget_reject") and not str(event.get("reason", "")).strip():
            issues.append(f"decision_log[{i}] {event.get('event')} 事件无 reason（不可审计）")
        if event.get("event") in ("assign", "release") and not event.get("resources"):
            issues.append(f"decision_log[{i}] {event.get('event')} 事件未记录资源")

    logged_ids = {event.get("job_id") for event in log if event.get("job_id")}
    for a in assignments:
        if float(a.get("end_s", 0.0)) < float(a.get("start_s", 0.0)) - _EPS:
            issues.append(f"{a.get('job_id')} start_s > end_s")
        if a.get("job_id") not in logged_ids:
            issues.append(f"{a.get('job_id')} 已分配但决策日志无记录")

    for u in unassigned:
        waits = [e for e in log if e.get("job_id") == u.get("job_id")
                 and e.get("event") in ("wait", "defer", "budget_reject")]
        if not waits:
            issues.append(f"{u.get('job_id')} 未分配但无 wait/defer/budget_reject 记录")

    for key, cap in capacities.items():
        peak = _max_overlap(assignments, key)
        if peak > int(cap):
            issues.append(f"{key} 峰值并发 {peak} 超过容量 {cap}")

    return {
        "ok": not issues,
        "issues": issues,
        "n_events": len(log),
        "n_assignments": len(assignments),
        "n_unassigned": len(unassigned),
    }


def format_decision_log(result: dict[str, Any]) -> list[str]:
    """把决策日志渲染成可读行（CLI/演示用，纯展示不改数值）。"""
    lines: list[str] = []
    for event in result.get("decision_log") or []:
        t = float(event.get("t_s", 0.0))
        job = event.get("job_id") or "-"
        parts = [f"[t={t:>8.1f}s] {event.get('event')!s:<7} {job}"]
        if event.get("resources"):
            parts.append("res=" + ",".join(event["resources"]))
        if event.get("reason"):
            parts.append("reason=" + str(event["reason"]))
        elif event.get("detail"):
            parts.append(str(event["detail"]))
        lines.append("  ".join(parts))
    return lines
