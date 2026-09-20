"""内存守望战役启动器（阶段 1.3 patch 战役的纪律化发射）。

内存门槛背景：真机求解前自查可用内存（calibration_campaign.py 内置
--min-free-kb 门）。本启动器在内存不足时不压门槛，而是周期探测、
门开即射：
- 默认目标 workers=2（需 4GB+1.5GB/worker ≈ 5.5GB 可用）；
- --fallback-hours 后（默认 6h）降级为串行门（4GB）；
- --max-wait-hours（默认 24h）超时未达标则退出（exit 2），交还人。
门开后直接 exec calibration_campaign.py（其内部自带同款门，双保险）。

用法：
  .venv\\Scripts\\python.exe scripts\\campaign_wait_launch.py ^
      --recipe recipes/patch_antenna_v1.yaml --mesh 0 --n-new 16
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE_GATE_KB = 4 * 1024 * 1024
PER_WORKER_KB = 1500 * 1024


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
    ap = argparse.ArgumentParser(description="内存门开后发射校准战役")
    ap.add_argument("--recipe", default="recipes/patch_antenna_v1.yaml")
    ap.add_argument("--mesh", type=float, default=0.0)
    ap.add_argument("--n-new", type=int, default=16)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--poll-s", type=int, default=600)
    ap.add_argument("--fallback-hours", type=float, default=6.0)
    ap.add_argument("--max-wait-hours", type=float, default=24.0)
    args = ap.parse_args()

    started = time.time()
    while True:
        waited_h = (time.time() - started) / 3600.0
        if waited_h >= args.max_wait_hours:
            print(f"WAIT_TIMEOUT: {waited_h:.1f}h 未达内存门——交还人",
                  flush=True)
            return 2
        workers = args.workers
        need = BASE_GATE_KB + (workers - 1) * PER_WORKER_KB
        free = free_physical_memory_kb()
        if free < need and waited_h >= args.fallback_hours and args.workers > 1:
            workers = 1
            need = BASE_GATE_KB
        if free >= need:
            print(f"LAUNCH: 可用 {free / 1e6:.2f}GB ≥ 门 "
                  f"{need / 1e6:.2f}GB，workers={workers}，"
                  f"等待 {waited_h:.1f}h 后发射", flush=True)
            cmd = [str(REPO / ".venv" / "Scripts" / "python.exe"),
                   str(REPO / "scripts" / "calibration_campaign.py"),
                   "--recipe", args.recipe, "--mesh", str(args.mesh),
                   "--n-new", str(args.n_new), "--n-workers", str(workers)]
            return subprocess.call(cmd)
        print(f"[wait {waited_h:.1f}h] 可用 {free / 1e6:.2f}GB < "
              f"{need / 1e6:.2f}GB（workers={workers}）——"
              f"{args.poll_s}s 后复测", flush=True)
        time.sleep(args.poll_s)


if __name__ == "__main__":
    sys.exit(main())
