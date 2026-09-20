"""稀缺资源调度器演示。

跑三组验收场景并打印可审计决策日志，结果落 runs/scheduler/demo.json：

1. mixed_stress   HFSS×2 + COMSOL×1 + openEMS×3（license 串行 / 异 solver 并行 / FDTD ≤3）
2. openems_five   openEMS×5（FDTD 并发上限 3，排队释放）
3. license_wait   license 探测不可用 → 等待而非失败（best-effort #105）

全部时刻来自确定性离散事件仿真：场景内 license 探测注入 stub，保证演示
可复现；真机探测只作 best-effort 快照打印，不参与调度决策。

运行：.venv/Scripts/python.exe scripts/scheduler_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from rfauto.service.resource_scheduler import (  # noqa: E402
    ResourceJob,
    SchedulerConfig,
    audit_schedule,
    format_decision_log,
    schedule,
)

OUT_PATH = ROOT / "runs" / "scheduler" / "demo.json"


def _probe_available(server: str | None = None, *, timeout_s: float = 0.0) -> dict:
    return {"available": True, "server": server, "detail": "demo stub: available"}


def _probe_unavailable(server: str | None = None, *, timeout_s: float = 0.0) -> dict:
    return {"available": False, "server": server, "detail": "demo stub: license server unreachable"}


def _jobs(*specs: tuple[str, str, float]) -> list[ResourceJob]:
    return [ResourceJob(job_id=jid, solver=solver, duration_s=dur) for jid, solver, dur in specs]


def _job_specs(jobs: list[ResourceJob]) -> list[dict]:
    return [
        {"job_id": j.job_id, "solver": j.solver, "duration_s": j.duration_s, "arrival_s": j.arrival_s}
        for j in jobs
    ]


def _scenarios() -> list[dict]:
    mixed = _jobs(
        ("hfss_1", "hfss", 300.0),
        ("hfss_2", "hfss", 180.0),
        ("comsol_1", "comsol", 240.0),
        ("oems_1", "openems", 120.0),
        ("oems_2", "openems", 120.0),
        ("oems_3", "openems", 120.0),
    )
    openems_five = _jobs(*[(f"oems_{i + 1}", "openems", 100.0) for i in range(5)])
    license_wait = _jobs(("hfss_1", "hfss", 300.0), ("oems_1", "openems", 60.0))
    return [
        {
            "name": "mixed_stress",
            "description": "HFSS×2 + COMSOL×1 + openEMS×3：license 串行、异 solver 并行、FDTD ≤3",
            "jobs": mixed,
            "config": SchedulerConfig(),
            "probe": _probe_available,
        },
        {
            "name": "openems_five",
            "description": "openEMS×5：FDTD 并发上限 3，其余排队",
            "jobs": openems_five,
            "config": SchedulerConfig(),
            "probe": _probe_available,
        },
        {
            "name": "license_wait",
            "description": "license 不可用：HFSS 等待（不失败），openEMS 照常调度",
            "jobs": license_wait,
            "config": SchedulerConfig(time_horizon_s=120.0),
            "probe": _probe_unavailable,
        },
    ]


def main() -> int:
    payload = {"generated_by": "scripts/scheduler_demo.py", "deterministic": True, "scenarios": []}
    total_events = 0

    for i, scenario in enumerate(_scenarios(), start=1):
        result = schedule(scenario["jobs"], scenario["config"], probe=scenario["probe"])
        audit = audit_schedule(result)
        lines = format_decision_log(result)
        total_events += len(lines)

        print(f"=== [{i}/{len(_scenarios())}] {scenario['name']} ===")
        print(f"  {scenario['description']}")
        print(f"  jobs: {', '.join(j.job_id for j in scenario['jobs'])}")
        print("  --- decision log ---")
        for line in lines:
            print("   " + line)
        peak = result["peak_concurrency"]
        print(f"  --- peak concurrency --- overall={peak['overall']} "
              f"by_solver={peak['by_solver']} by_class={peak['by_class']}")
        assigned = [a["job_id"] for a in result["assignments"]]
        waiting = [(u["job_id"], u["status"]) for u in result["unassigned"]]
        print(f"  --- assigned={assigned} unassigned={waiting}")
        print(f"  --- audit ok={audit['ok']} issues={audit['issues']} events={audit['n_events']}")
        print()

        payload["scenarios"].append({
            "name": scenario["name"],
            "description": scenario["description"],
            "jobs": _job_specs(scenario["jobs"]),
            "config": result["config"],
            "assignments": result["assignments"],
            "unassigned": result["unassigned"],
            "peak_concurrency": peak,
            "audit": audit,
            "decision_log": result["decision_log"],
            "decision_log_lines": lines,
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT_PATH} ({total_events} decision-log events)")

    # 真机探测快照：best-effort，仅供参考，不参与上面任何调度决策（#105）。
    try:
        from rfauto.infra.license_probe import probe_license

        live = probe_license(timeout_s=1.0)
    except Exception as exc:  # 演示脚本 best-effort
        live = {"available": None, "detail": f"probe failed (best-effort): {exc}"}
    print(f"license_probe (live, informational only): {live}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
