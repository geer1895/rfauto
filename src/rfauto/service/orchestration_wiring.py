"""编排接线：campaign 阶段事件 ↔ core.events 总线 ↔ 资源席位。

背景：
service/campaign_manager 已能确定性拆解"校准→粗筛→精算→公差→报告"
阶段队列，service/resource_scheduler（G13）已能对稀缺资源（license /
FDTD / CPU）做确定性仲裁，但两者之间没有接线：战役阶段推进不会广播事件，
作业到达/释放也不会进入调度器，更没有"哪类资源被哪个作业占用"的可查询账目。

本模块只做三类接线，不产生任何新的物理/数值决策（数值铁律）：
1. **事件出口**：campaign 阶段事件经既有 core.events.EventBus 发布
   （复用 EventType，不改 core/events.py 与 core/state.py）；
2. **调度入口**：作业到达/释放信号转发给 resource_scheduler.schedule
   确定性内核，接线层只转录内核给出的 assign/wait 决策与原因；
3. **席位账目**：把"当前时刻谁占着哪些席位"落到 JobRegistry 的加性
   seat 字段（assign_seats / release_seats / seat_occupancy），可查询、可审计。

语义边界（诚实说明）：
- 时刻来自离散事件仿真（clock_s = 已见的最大作业到达时刻），不用墙钟，
  因此同一事件流逐字节可复现；
- 席位账目 = 调度计划中区间覆盖 clock_s 的占用（半开区间 [start, end)），
  不是"作业被受理即占座"——排在后面的作业（queued）不占席位；
- license 探测若调用方注入 probe 则按其结果走；不注入时沿用
  resource_scheduler 的 best-effort 探测（#105），接线层不吞异常、不编造。

补强（G13 调度接进生产路径）：接线器消费注入接口——
``predictor``（TieredDurationPredictor 分档时长预测：未申报作业按
(solver, template, grid_tier) 填充 + 同刻 SJF）与 ``budget_gate``
（budget_admission_gate 预算准入门：拒绝者落 unassigned）在重排时
透传 schedule()；新增批量入口 :func:`schedule_campaign_jobs`
（campaign_manager.plan_campaign 派发前调用，生产接线点）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rfauto.core.events import Event, EventBus, EventType, get_event_bus
from rfauto.pipeline.quota_guard import TieredDurationPredictor
from rfauto.service.job_registry import JobRegistry, get_job_registry
from rfauto.service.resource_scheduler import (
    ResourceJob,
    SchedulerConfig,
    audit_schedule,
    schedule,
)

_EPS = 1e-9

#: 阶段作业缺省申报时长（秒）——与 ResourceJob/wiring 既有默认一致；
#: 未注入 predictor 时 SJF 退化为输入序，该值只影响 DES 时刻不改变顺序。
DEFAULT_STAGE_DURATION_S = 60.0

#: campaign 阶段生命周期事件 → 事件总线类型（集中映射，可审计）。
#: 事件名与 campaign_manager.apply_event 对齐（stage_done/stage_failed/skip），
#: 另加表达"阶段开始"的 stage_started。
CAMPAIGN_EVENT_TYPES: dict[str, EventType] = {
    "stage_started": EventType.TRIAL_STARTED,
    "stage_done": EventType.TRIAL_COMPLETED,
    "stage_failed": EventType.TRIAL_FAILED,
    "skip": EventType.WARNING,
}
#: 结束类阶段事件（触发作业释放信号）；其余视为到达信号。
CAMPAIGN_RELEASE_EVENTS = ("stage_done", "stage_failed", "skip")

#: campaign adapter → G13 solver 名。未知/免费通道（surrogate/local/fake）
#: 统一落 pure（CPU 类），避免虚构不存在的 license 席位。
ADAPTER_SOLVERS: dict[str, str] = {
    "hfss": "hfss",
    "aedt": "aedt",
    "comsol": "comsol",
    "ads": "ads",
    "openems": "openems",
    "research": "research",
    "gpu": "gpu",
}


def adapter_solver(adapter: str | None) -> str:
    """campaign 阶段 adapter → G13 solver 名（免费通道统一落 pure）。"""
    return ADAPTER_SOLVERS.get(str(adapter or "").strip().lower(), "pure")


class OrchestrationWiring:
    """战役/作业事件流 ↔ 事件总线 ↔ G13 资源席位的接线器（确定性）。

    典型用法::

        wiring = OrchestrationWiring(registry=get_job_registry())
        wiring.campaign_stage(plan, "final_verify", "stage_started", run_id=r)
        wiring.campaign_stage(plan, "final_verify", "stage_done", run_id=r)
        wiring.seat_occupancy()   # 可查询的席位占用表
    """

    def __init__(
        self,
        *,
        registry: JobRegistry | None = None,
        config: SchedulerConfig | None = None,
        event_bus: EventBus | None = None,
        probe: Callable[[str | None], dict[str, Any]] | None = None,
        predictor: TieredDurationPredictor | None = None,
        budget_gate: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        use_global_registry: bool = True,
    ) -> None:
        self._registry = registry
        if self._registry is None and use_global_registry:
            self._registry = get_job_registry()
        self._config = config
        self._bus = event_bus if event_bus is not None else get_event_bus()
        self._probe = probe
        # 注入面：分档时长预测器（未申报填充 + SJF）与预算准入门。
        self._predictor = predictor
        self._budget_gate = budget_gate
        self._jobs: dict[str, ResourceJob] = {}
        self._held: dict[str, tuple[str, ...]] = {}
        self._clock_s = 0.0
        self._plan: dict[str, Any] | None = None
        self._transcript: list[Event] = []
        self._released: list[dict[str, Any]] = []

    # ── 查询面 ────────────────────────────────────────────────────────────
    @property
    def clock_s(self) -> float:
        """离散事件仿真时钟（已见的最大作业到达时刻）。"""
        return self._clock_s

    @property
    def event_bus(self) -> EventBus:
        return self._bus

    @property
    def plan(self) -> dict[str, Any] | None:
        """最近一次 resource_scheduler.schedule 的原始结果（可审计）。"""
        return self._plan

    def active_jobs(self) -> list[str]:
        """已登记未释放的作业 id（登记序=到达序，确定性）。"""
        return list(self._jobs)

    def releases(self) -> list[dict[str, Any]]:
        """作业释放记录（释放序，审计用）。"""
        return list(self._released)

    def transcript(self) -> list[dict[str, Any]]:
        """本接线器发出的事件转录（与总线同源，JSON 安全）。"""
        out: list[dict[str, Any]] = []
        for event in self._transcript:
            doc = event.to_dict()
            doc["event_type"] = event.event_type.value
            out.append(doc)
        return out

    def _plan_holders(self, at_s: float) -> dict[str, list[str]]:
        """作业 → 该时刻占用席位列表（半开区间 [start, end)）。"""
        out: dict[str, list[str]] = {}
        for a in (self._plan or {}).get("assignments") or []:
            if float(a["start_s"]) <= at_s + _EPS < float(a["end_s"]):
                out[str(a["job_id"])] = [str(s) for s in a["resources"]]
        return out

    def holders_at(self, t_s: float | None = None) -> dict[str, list[str]]:
        """t 时刻席位 → 占用作业（默认 clock_s；可查询表）。"""
        at = self._clock_s if t_s is None else float(t_s)
        table: dict[str, list[str]] = {}
        for job_id, seats in self._plan_holders(at).items():
            for seat in seats:
                table.setdefault(seat, []).append(job_id)
        return table

    def seat_occupancy(self) -> dict[str, list[str]]:
        """席位占用账目：seat → [job_id]（查询接口）。

        绑定 JobRegistry 时取注册表口径（与 registry.seat_occupancy 一致）；
        未绑定时用当前调度计划在 clock_s 的占用重建。
        """
        if self._registry is not None:
            return self._registry.seat_occupancy()
        return self.holders_at()

    def decision_for(self, job_id: str) -> dict[str, Any]:
        """查询某作业在当前调度计划中的决策快照。

        status 语义：
        - running：已获席位且区间覆盖 clock_s（当前占用）
        - assigned：已排定但尚未到计划开始时刻（未来执行）
        - elapsed：计划区间已在 clock_s 之前结束但尚未收到释放信号
        - waiting / deferred：调度内核判定未能在视界内获得资源
        """
        jid = str(job_id)
        plan = self._plan or {}
        held = self._plan_holders(self._clock_s)
        for a in plan.get("assignments") or []:
            if str(a["job_id"]) != jid:
                continue
            admitted = float(a["start_s"]) <= self._clock_s + _EPS
            if jid in held:
                status = "running"
            elif admitted:
                status = "elapsed"
            else:
                status = "assigned"
            return {
                "ok": True,
                "job_id": jid,
                "solver": a["solver"],
                "resource_class": a["resource_class"],
                "status": status,
                "admitted": admitted,
                "seats": held.get(jid, []),
                "planned_seats": [str(s) for s in a["resources"]],
                "start_s": float(a["start_s"]),
                "end_s": float(a["end_s"]),
                "reason": "" if admitted else (
                    f"资源未就绪，计划 {float(a['start_s']):g}s 起执行"),
                "index": a.get("index"),
            }
        for u in plan.get("unassigned") or []:
            if str(u["job_id"]) != jid:
                continue
            return {
                "ok": True,
                "job_id": jid,
                "solver": u["solver"],
                "resource_class": u["resource_class"],
                "status": str(u["status"]),
                "admitted": False,
                "seats": [],
                "planned_seats": [],
                "start_s": None,
                "end_s": None,
                "reason": str(u["reason"]),
                "index": u.get("index"),
            }
        return {
            "ok": False,
            "job_id": jid,
            "status": "unknown",
            "admitted": False,
            "seats": [],
            "planned_seats": [],
            "start_s": None,
            "end_s": None,
            "reason": "作业未出现在调度结果中",
        }

    # ── 事件流 → 调度桥 ───────────────────────────────────────────────────
    def job_arrived(
        self,
        job_id: str,
        solver: str,
        *,
        duration_s: float = 60.0,
        arrival_s: float | None = None,
        run_id: str = "",
        emit: bool = True,
        template: str = "",
        grid_tier: str = "",
    ) -> dict[str, Any]:
        """作业到达信号：登记 → 交给 G13 内核重排 → 返回决策并同步席位。

        ``template`` / ``grid_tier`` 为分档预测维度（空串=未申报），
        predictor 注入时供 (solver, template, grid_tier) 分档填充时长。
        """
        jid = str(job_id)
        if not jid:
            raise ValueError("job_id 不能为空")
        if jid in self._jobs:
            raise ValueError(f"job_id 已登记且未释放: {jid}")
        at = self._clock_s if arrival_s is None else max(0.0, float(arrival_s))
        self._clock_s = max(self._clock_s, at)
        self._jobs[jid] = ResourceJob(
            job_id=jid, solver=str(solver), duration_s=duration_s,
            arrival_s=at, template=str(template or ""),
            grid_tier=str(grid_tier or "")).normalized()
        self._ensure_registry_entry(jid)
        self._reschedule()
        decision = self.decision_for(jid)
        if emit:
            self._emit_job_event(jid, decision, run_id=run_id)
        return decision

    def job_released(
        self,
        job_id: str,
        *,
        at_s: float | None = None,
        run_id: str = "",
        emit: bool = True,
    ) -> dict[str, Any]:
        """作业释放信号：注销 → 重排 → 归还席位；未知作业幂等空操作。"""
        jid = str(job_id)
        if at_s is not None:
            self._clock_s = max(self._clock_s, max(0.0, float(at_s)))
        job = self._jobs.pop(jid, None)
        if job is None:
            return {
                "ok": False,
                "job_id": jid,
                "status": "unknown",
                "released_seats": [],
                "at_s": self._clock_s,
                "reason": "未登记或已释放（幂等空操作）",
                "occupancy": self.seat_occupancy(),
            }
        released_seats = list(self._held.get(jid, ()))
        self._reschedule()
        record = {
            "job_id": jid,
            "solver": job.solver,
            "released_seats": released_seats,
            "at_s": self._clock_s,
        }
        self._released.append(record)
        if emit:
            self.emit_event(
                EventType.SOLVE_COMPLETED, run_id=run_id, job_id=jid,
                message=f"作业 {jid} 释放资源 {released_seats or '(无)'}",
                data=record)
        return {
            "ok": True,
            "job_id": jid,
            "status": "released",
            "released_seats": released_seats,
            "at_s": self._clock_s,
            "occupancy": self.seat_occupancy(),
        }

    # ── campaign 阶段 → 事件总线 + 调度信号 ──────────────────────────────
    def campaign_stage(
        self,
        plan: dict[str, Any],
        stage: str,
        event: str,
        *,
        run_id: str = "",
        detail: str = "",
        job_id: str | None = None,
        duration_s: float = 60.0,
        solver: str | None = None,
        emit: bool = True,
    ) -> dict[str, Any]:
        """战役阶段事件 → EventBus，并桥接作业到达/释放信号。

        plan/stage/event 与 campaign_manager 同构；本函数只做接线，
        **不修改 plan**（状态机推进仍由 campaign_manager.apply_event 负责）。
        """
        stages = {str(s.get("stage")): s for s in plan.get("stages") or []}
        if stage not in stages:
            return {"ok": False, "errors": [f"未知阶段: {stage}"], "event": None}
        if event not in CAMPAIGN_EVENT_TYPES:
            return {"ok": False, "errors": [f"未知阶段事件: {event}"], "event": None}
        stage_doc = stages[stage]
        jid = job_id or f"campaign:{stage}"
        slv = solver or adapter_solver(stage_doc.get("adapter"))
        if event in CAMPAIGN_RELEASE_EVENTS:
            decision = self.job_released(jid, run_id=run_id, emit=False)
        else:
            decision = self.job_arrived(
                jid, slv, duration_s=duration_s, run_id=run_id, emit=False)
        data = {
            "stage": stage,
            "campaign_event": event,
            "adapter": stage_doc.get("adapter"),
            "solver": slv,
            "license_gated": bool(stage_doc.get("license_gated", False)),
            "decision": decision,
            "detail": str(detail),
        }
        message = (f"campaign 阶段 {stage} {event}"
                   f"（solver={slv}，status={decision.get('status')}）")
        emitted = None
        if emit:
            emitted = self.emit_event(
                CAMPAIGN_EVENT_TYPES[event], run_id=run_id, job_id=jid,
                message=message, data=data)
        return {
            "ok": True,
            "stage": stage,
            "campaign_event": event,
            "solver": slv,
            "job_id": jid,
            "decision": decision,
            "emitted_type": CAMPAIGN_EVENT_TYPES[event].value,
            "event_id": emitted.event_id if emitted is not None else None,
        }

    # ── 内部 ─────────────────────────────────────────────────────────────
    def emit_event(
        self,
        event_type: EventType,
        *,
        run_id: str = "",
        job_id: str = "",
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> Event:
        """构造并发布事件（同时留内部转录，便于离线审计/测试）。"""
        event = Event(
            event_type=event_type,
            run_id=str(run_id),
            job_id=str(job_id),
            message=str(message),
            data=dict(data or {}),
        )
        self._bus.emit(event)
        self._transcript.append(event)
        return event

    def _ensure_registry_entry(self, job_id: str) -> None:
        if self._registry is None or self._registry.get(job_id) is not None:
            return
        self._registry.create(job_id)

    def _reschedule(self) -> None:
        """对全部已登记作业重跑确定性调度内核，并同步席位账目。"""
        self._plan = schedule(
            list(self._jobs.values()), self._config,
            probe=self._probe,
            predictor=self._predictor, budget_gate=self._budget_gate)
        self._sync_seats()

    def _sync_seats(self) -> None:
        """把 clock_s 时刻的占用增量落到 JobRegistry（delta 记账）。"""
        desired = self._plan_holders(self._clock_s)
        if self._registry is None:
            self._held = {jid: tuple(seats) for jid, seats in desired.items()}
            return
        for jid in list(self._held):
            if jid not in desired:
                self._registry.release_seats(jid)
                self._held.pop(jid, None)
        for jid, seats in desired.items():
            if self._held.get(jid) != tuple(seats):
                self._registry.assign_seats(jid, seats)
                self._held[jid] = tuple(seats)

    def _emit_job_event(
        self, job_id: str, decision: dict[str, Any], *, run_id: str,
    ) -> Event:
        status = str(decision.get("status", ""))
        seats = decision.get("seats") or decision.get("planned_seats") or []
        if status in ("running", "assigned"):
            event_type = EventType.SOLVE_STARTED
            message = f"作业 {job_id} 获得席位 {seats}"
        elif status in ("waiting", "deferred") and decision.get("resource_class") == "license":
            event_type = EventType.LICENSE_WAIT
            message = f"作业 {job_id} 等待 license：{decision.get('reason')}"
        elif status in ("waiting", "deferred"):
            event_type = EventType.PROGRESS
            message = f"作业 {job_id} 排队等待资源：{decision.get('reason')}"
        elif status == "elapsed":
            event_type = EventType.SOLVE_COMPLETED
            message = f"作业 {job_id} 计划区间已结束"
        else:
            event_type = EventType.PROGRESS
            message = f"作业 {job_id} 状态 {status}"
        return self.emit_event(event_type, run_id=run_id, job_id=job_id,
                               message=message, data=decision)


# ── 批量入口：战役计划 → G13 调度前置步（生产接线点） ─────────────────────
CAMPAIGN_SCHEDULE_SCHEMA = "rfauto-campaign-schedule-v1"


def plan_time_probe(server: str | None) -> dict[str, Any]:
    """计划期 license 探测替身：零网络、确定性（#139）。

    战役发起/排程时尚未真机派发，license 席位按"假设可用"建计划；真机派发
    时由调度内核/配额守卫按实测裁决（#105：真探测异常也按可用处理，不阻塞）。
    """
    return {
        "available": True,
        "server": server,
        "detail": "计划期不探测 license（真机派发时按实测走）",
    }


def _stage_of(job_id: str) -> str:
    return job_id[len("campaign:"):] if job_id.startswith("campaign:") else job_id


def schedule_campaign_jobs(
    plan: dict[str, Any],
    *,
    campaign_id: str = "",
    predictor: TieredDurationPredictor | None = None,
    budget_gate: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    config: SchedulerConfig | None = None,
    registry: JobRegistry | None = None,
    probe: Callable[[str | None], dict[str, Any]] | None = None,
    stage_durations: dict[str, float] | None = None,
) -> dict[str, Any]:
    """战役计划的批量调度前置步：阶段作业列表 → G13 schedule()。

    生产接线入口（campaign_manager.plan_campaign 派发前调用）：把计划里每个
    阶段构造成 ResourceJob（job_id=``campaign:<stage>``、solver 由 adapter
    映射、template=计划 model、grid_tier 取阶段元数据），经 OrchestrationWiring
    逐个到达信号进 G13 确定性内核——含 predictor 分档预测填充 + 同刻 SJF、
    budget_gate 预算准入——产出可审计的派发顺序（``dispatch``）与拒绝清单
    （``rejected``，budget_rejected 作业记 unassigned + decision_log 审计事件，
    不静默丢）。

    语义边界（诚实说明）：
    - 计划期零副作用：作业不进全局 JobRegistry（不传 registry 时用独立账本，
      席位记账仍走 assign/release 路径并回带 ``seat_occupancy``）、不向
      事件总线广播（emit=False；审计事件 = 内核 decision_log）；
    - license 探测默认 :func:`plan_time_probe`（零网络 #139），可注入替身；
    - 时长申报：predictor 注入时默认 0（未申报，由分档预测填充；
      ``stage_durations`` 按阶段名覆盖）；未注入时默认
      DEFAULT_STAGE_DURATION_S 申报，SJF 退化为输入序（排程逐字节稳定）。

    Returns:
        {ok, schema, campaign_id, model, n_jobs, predictor_used,
         budget_gate_used, dispatch, assignments, unassigned, rejected,
         decision_log, peak_concurrency, capacities, audit, seat_occupancy,
         clock_s[, duration_predictions]}；计划无阶段时 ok=False + errors。
    """
    stages = [s for s in plan.get("stages") or []
              if isinstance(s, dict) and str(s.get("stage", "") or "").strip()]
    if not stages:
        return {"ok": False, "schema": CAMPAIGN_SCHEDULE_SCHEMA,
                "campaign_id": str(campaign_id),
                "errors": ["计划无可用阶段，未产生调度"]}
    ledger = registry if registry is not None else JobRegistry()
    wiring = OrchestrationWiring(
        registry=ledger, config=config,
        probe=probe if probe is not None else plan_time_probe,
        predictor=predictor, budget_gate=budget_gate,
        use_global_registry=False,
    )
    declared = dict(stage_durations or {})
    model = str(plan.get("model", "") or "")
    job_ids: list[str] = []
    for stage_doc in stages:
        name = str(stage_doc.get("stage")).strip()
        jid = f"campaign:{name}"
        job_ids.append(jid)
        if declared.get(name) is not None:
            duration_s = float(declared[name])
        else:
            duration_s = 0.0 if predictor is not None else DEFAULT_STAGE_DURATION_S
        wiring.job_arrived(
            jid, adapter_solver(stage_doc.get("adapter")),
            duration_s=duration_s, template=model,
            grid_tier=str(stage_doc.get("grid_tier", "") or ""),
            emit=False)

    raw = wiring.plan or {}
    assignments = list(raw.get("assignments") or [])
    unassigned = list(raw.get("unassigned") or [])
    duration_source = {str(a.get("job_id")): str(a.get("duration_source", "declared"))
                       for a in assignments}
    dispatch: list[dict[str, Any]] = []
    for a in assignments:  # 内核 assign 序 = 派发序（DES 开始时刻单调）
        jid = str(a["job_id"])
        decision = wiring.decision_for(jid)
        dispatch.append({
            "order": len(dispatch),
            "stage": _stage_of(jid),
            "job_id": jid,
            "solver": decision.get("solver"),
            "resource_class": decision.get("resource_class"),
            "status": decision.get("status"),
            "admitted": True,
            "start_s": decision.get("start_s"),
            "end_s": decision.get("end_s"),
            "seats": list(decision.get("seats") or []),
            "planned_seats": list(decision.get("planned_seats") or []),
            "duration_source": duration_source.get(jid, "declared"),
            "reason": str(decision.get("reason", "") or ""),
        })
    rejected: list[dict[str, Any]] = []
    for u in unassigned:  # 未获资源者排尾：waiting/deferred/budget_rejected
        jid = str(u.get("job_id"))
        entry = {
            "order": len(dispatch),
            "stage": _stage_of(jid),
            "job_id": jid,
            "solver": u.get("solver"),
            "resource_class": u.get("resource_class"),
            "status": str(u.get("status")),
            "admitted": False,
            "start_s": None,
            "end_s": None,
            "seats": [],
            "planned_seats": [],
            "duration_source": duration_source.get(jid, "declared"),
            "reason": str(u.get("reason", "") or ""),
        }
        if entry["status"] == "budget_rejected":
            entry["budget"] = dict(u.get("budget") or {})
            rejected.append({"stage": entry["stage"], **{k: v for k, v in u.items()}})
        dispatch.append(entry)

    result: dict[str, Any] = {
        "ok": True,
        "schema": CAMPAIGN_SCHEDULE_SCHEMA,
        "campaign_id": str(campaign_id),
        "model": model,
        "n_jobs": len(job_ids),
        "job_ids": job_ids,
        "predictor_used": predictor is not None,
        "budget_gate_used": budget_gate is not None,
        "dispatch": dispatch,
        "assignments": assignments,
        "unassigned": unassigned,
        "rejected": rejected,
        "decision_log": list(raw.get("decision_log") or []),
        "peak_concurrency": dict(raw.get("peak_concurrency") or {}),
        "capacities": dict(raw.get("capacities") or {}),
        "probe_attempts": int(raw.get("probe_attempts", 0) or 0),
        "audit": audit_schedule(raw),
        "seat_occupancy": ledger.seat_occupancy(),
        "clock_s": wiring.clock_s,
    }
    if predictor is not None:
        result["duration_predictions"] = dict(raw.get("duration_predictions") or {})
    return result
