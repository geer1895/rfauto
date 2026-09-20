"""0.2/1.3 校准采样战役驱动（真机，串行或 worker 池并行）。

流程：官方方法学 9 点 Taguchi 种子 → 16 点 LHS 增广（样本资产复用）→
代理离线对比 → 产物落 runs/<rid>/calibration/。

用法：
  .venv\\Scripts\\python.exe scripts/calibration_campaign.py \\
      --recipe recipes/wilkinson_pd_v1.yaml --mesh 0.45 --n-new 16 [--n-workers 2]

内存门槛纪律：启动前查可用内存，<4GB 不开跑
（0.45mm base ≈ 1M cells ≈ 1-1.5GB/求解）；n_workers>1 时每 worker
占 1-1.5GB，按可用内存折算（2 worker 建议门槛 5.5GB）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _parse_free_kb(out: str) -> int:
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("FreePhysicalMemory="):
            return int(line.split("=", 1)[1].strip())
        if line.isdigit():
            return int(line)
    return 0


def free_physical_memory_kb() -> int:
    # wmic 在 Win11 24H2+ 已移除，回退 PowerShell CIM
    for cmd in (
        ["wmic", "OS", "get", "FreePhysicalMemory", "/Value"],
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
    ):
        try:
            kb = _parse_free_kb(subprocess.check_output(
                cmd, text=True, stderr=subprocess.DEVNULL))
        except (OSError, subprocess.CalledProcessError):
            continue
        if kb:
            return kb
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="openEMS 校准采样战役")
    ap.add_argument("--recipe", default="recipes/wilkinson_pd_v1.yaml")
    ap.add_argument("--mesh", type=float, default=0.45,
                    help="网格 base 覆盖 mm（0=自动 λ_sub/50；0.45≈λ_sub/100）")
    ap.add_argument("--n-new", type=int, default=16)
    ap.add_argument("--min-free-kb", type=int, default=4 * 1024 * 1024,
                    help="可用内存门槛 KB（默认 4GB；n_workers>1 时按"
                         "worker 数上调）")
    ap.add_argument("--n-workers", type=int, default=1,
                    help="采样并行 worker 数（默认 1=串行；>1 需内存余量，"
                         "openEMS 每 worker 1-1.5GB）")
    ap.add_argument("--kinds", default="poly_ridge,nn,smt_kriging",
                    help="离线对比的代理类型（逗号分隔）")
    ap.add_argument("--seed-run-id", default=None,
                    help="断点续跑：已完成种子的 run_id（跳过阶段 1，"
                         "直接从其 samples.json 增广——种子是资产不重烧）")
    args = ap.parse_args()

    workers = max(1, args.n_workers)
    # 内存门槛随 worker 数上调（每 worker 1-1.5GB）
    need_kb = args.min_free_kb + (workers - 1) * 1500 * 1024
    free = free_physical_memory_kb()
    if free < need_kb:
        print(f"MEMORY_GATE_STOP: 可用 {free / 1e6:.2f}GB < "
              f"{need_kb / 1e6:.2f}GB（workers={workers}）——"
              f"按纪律推迟（内存好转队列）")
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from rfauto.service.calibration_service import augment_calibration, calibrate_surrogate, compare_surrogates

    kinds = tuple(k.strip() for k in args.kinds.split(",") if k.strip())

    if args.seed_run_id:
        seed_dir = Path("runs") / args.seed_run_id / "calibration"
        gate_p = seed_dir / "gate.json"
        if not gate_p.exists():
            print(f"RESUME_FAIL: 种子 gate 不存在 {gate_p}")
            return 1
        prev = json.loads(gate_p.read_text(encoding="utf-8"))
        seed = {"run_id": args.seed_run_id,
                "run_dir": str(Path("runs") / args.seed_run_id),
                "verdict": prev.get("verdict", "RESUMED"),
                "loocv": {"rho": prev.get("rho")}}
        print(f"[1/3] 跳过（断点续跑种子 {args.seed_run_id}，"
              f"verdict={seed['verdict']}）…", flush=True)
    else:
        print(f"[1/3] 种子校准（9 点 Taguchi, openems, base={args.mesh}mm, "
              f"workers={workers}）…", flush=True)
        seed = calibrate_surrogate(args.recipe, sampler="openems",
                                   mesh_resolution_mm=args.mesh,
                                   n_validation=2, n_workers=workers)
        if not seed.get("ok"):
            print(json.dumps(seed, ensure_ascii=False, indent=1))
            return 1
        print(f"  seed run={seed['run_id']} verdict={seed['verdict']} "
              f"rho={seed['loocv'].get('rho')}", flush=True)

    print(f"[2/3] LHS 增广 {args.n_new} 点（复用种子样本）…", flush=True)
    seed_samples = Path(seed["run_dir"]) / "calibration" / "samples.json"
    aug = augment_calibration(args.recipe, seed_samples, sampler="openems",
                              mesh_resolution_mm=args.mesh,
                              n_new=args.n_new, n_workers=workers)
    if not aug.get("ok"):
        print(json.dumps(aug, ensure_ascii=False, indent=1))
        return 1
    print(f"  augment run={aug['run_id']} verdict={aug['verdict']} "
          f"rho={aug['loocv'].get('rho')} n={aug['n_samples']}", flush=True)

    print(f"[3/3] 代理离线对比（{' vs '.join(kinds)}）…", flush=True)
    merged = Path(aug["run_dir"]) / "calibration" / "samples.json"
    cmp_result = compare_surrogates(merged, kinds=kinds)
    print(json.dumps(cmp_result.get("ranking"), ensure_ascii=False), flush=True)

    campaign = {
        "recipe": args.recipe, "mesh_base_mm": args.mesh,
        "n_workers": workers,
        "seed_run_id": seed["run_id"], "seed_verdict": seed["verdict"],
        "augment_run_id": aug["run_id"], "augment_verdict": aug["verdict"],
        "augment_rho": aug["loocv"].get("rho"),
        "n_samples": aug["n_samples"],
        "surrogate_ranking": cmp_result.get("ranking"),
        "best_surrogate": cmp_result.get("best"),
    }
    out = Path(aug["run_dir"]) / "calibration" / "campaign.json"
    out.write_text(json.dumps(campaign, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"CAMPAIGN_DONE {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
