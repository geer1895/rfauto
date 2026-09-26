"""DP-6 并行日常门运行器（pytest-xdist）。

规格：docs/plan_deepdive_specs_20260924.md §DP-6。日常=并行、终门=串行
双轨制——本运行器只服务"日常并行门 + 串行对照"，不替代终门口径
（runs/wf_gate_full-*.log，#355 glob 口径不受影响）。

用法（仓根执行）：
    .venv/Scripts/python.exe scripts/gate_parallel.py            # 并行全量
    .venv/Scripts/python.exe scripts/gate_parallel.py --serial   # 串行对照
    .venv/Scripts/python.exe scripts/gate_parallel.py -- --k-subset  # 冒烟附加参数

产物：
    runs/wf_gate_parallel_<ts>.log / runs/wf_gate_serial_<ts>.log（pytest
    全量 stdout 落文件——超 256KB cap 截断是硬约束，禁止 stdout 直读）；
    runs/gate_logs/parallel_<ts>.xml / serial_<ts>.xml（junitxml，供
    scripts/gate_diff_results.py 守卫比对）。

守卫：
    OPENBLAS_NUM_THREADS=1 在子进程 env 构造期钉死（#258：worker×BLAS
    线程超订实测慢 85×）；日志头回写 env 证据。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="pytest-xdist 并行日常门运行器（DP-6）")
    parser.add_argument("--serial", action="store_true",
                        help="串行对照模式（-n0 + serial_<ts>.xml）")
    parser.add_argument("--workers", default="auto",
                        help="xdist worker 数（缺省 auto；Windows spawn）")
    parser.add_argument("extra", nargs="*",
                        help="附加 pytest 参数（冒烟/取证用，日常勿传）")
    parser.add_argument("--pytest-root", default=None,
                        help="pytest 运行根目录（冻结快照/工作树隔离用；"
                             "缺省=本仓根。日志与 junitxml 仍落本仓 runs/）")
    args = parser.parse_args(argv)

    pytest_root = Path(args.pytest_root).resolve() if args.pytest_root else REPO_ROOT

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "serial" if args.serial else "parallel"
    log_path = REPO_ROOT / "runs" / f"wf_gate_{mode}_{ts}.log"
    xml_dir = REPO_ROOT / "runs" / "gate_logs"
    xml_dir.mkdir(parents=True, exist_ok=True)
    xml_path = xml_dir / f"{mode}_{ts}.xml"

    dist_args = (["-n0"] if args.serial
                 else ["-n", args.workers, "--dist=loadfile"])

    # #258 超订守卫：必须在 pytest/numpy import 之前生效——子进程 env 构造
    # 期注入，本进程（父）只 import stdlib，不会提前加载 numpy。
    env = os.environ.copy()
    env["OPENBLAS_NUM_THREADS"] = "1"

    cmd = [
        sys.executable, "-m", "pytest", "tests/unit", "-q",
        *dist_args, f"--junitxml={xml_path}", *args.extra,
    ]

    header = (
        f"# DP-6 gate runner mode={mode}\n"
        f"# cmd: {' '.join(cmd)}\n"
        f"# pytest_root: {pytest_root}\n"
        f"# OPENBLAS_NUM_THREADS={env['OPENBLAS_NUM_THREADS']} (forced)\n"
        f"# junitxml: {xml_path}\n"
        f"# started: {datetime.now().isoformat()}\n\n"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    # pytest 全量输出直接落文件（二进制句柄，不做 stdout 中转）
    with open(log_path, "wb") as log:
        log.write(header.encode("utf-8"))
        log.flush()
        proc = subprocess.run(
            cmd, cwd=pytest_root, env=env,
            stdout=log, stderr=subprocess.STDOUT)
    wall_s = time.monotonic() - start

    trailer = (
        f"\n# finished: {datetime.now().isoformat()}\n"
        f"# wall_clock_s: {wall_s:.1f} ({wall_s / 60:.1f} min)\n"
        f"# pytest_rc: {proc.returncode}\n"
        f"# junitxml: {xml_path}\n"
    )
    with open(log_path, "ab") as log:
        log.write(trailer.encode("utf-8"))

    print(f"mode={mode} rc={proc.returncode} wall={wall_s:.1f}s")
    print(f"log: {log_path}")
    print(f"xml: {xml_path}")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
