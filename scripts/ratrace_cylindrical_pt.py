"""柱坐标 rat-race 真机 pt（§10.20 补强①；#219 根治路线）。

k=1（不做任何网格伪象补偿），Σ（port1）单激励 1 run（#208 进程隔离安全
模式，Run(cleanup=True) 销毁绑定对象——单激励单进程）；量測 hybrid 中心 =
balance 最小点 argmin||S21|dB−|S41|dB|，验收 = 回 2.5GHz ±2%（对照 HFSS
仲裁 runs/ratrace_arbitration：2.465GHz / −1.4%）；三门：均分/隔离/S11。

真机纪律（#157）：openEMS 求解走后台分离进程 + 日志文件轮询；一次只跑
一个 openEMS 任务；时间盒默认 ≤90min（跑不完/失败如实标 partial）。
产物：runs/ratrace_cylindrical/ratrace_cylindrical.json + pt1/ 下
simulation.py、sparams.csv、openems.log。

用法（pwsh）：
  .venv/Scripts/python.exe scripts/ratrace_cylindrical_pt.py --mesh-mm 0.4 --timeout-s 5400
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "runs" / "ratrace_cylindrical"
RESULT = OUT_DIR / "ratrace_cylindrical.json"
HFSS_ARB = REPO / "runs" / "ratrace_arbitration" / "hfss_arbitration.json"
RATRACE_ARB = REPO / "runs" / "ratrace_arbitration" / "ratrace_arbitration.json"

W_RING, W_FEED, R_PHYS, F0 = 0.6035, 1.1134, 17.344, 2.5
TARGET_TOL_PCT = 2.0
DEFAULT_TIMEOUT_S = 5400


def _write(patch: dict) -> None:
    data: dict = {}
    if RESULT.exists():
        data = json.loads(RESULT.read_text(encoding="utf-8"))
    data.update(patch)
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                      encoding="utf-8")


def _hfss_ref() -> dict:
    """HFSS 仲裁参考（缺失则空）。dev% 用 ratrace_arbitration.json 的
    dev_vs_2p5_balance_pct（权威口径：hfss_arbitration.json 的 center_dev_pct
    字段未更新，值为 2.5 属旧噪声）。"""
    ref: dict = {}
    if HFSS_ARB.exists():
        d = json.loads(HFSS_ARB.read_text(encoding="utf-8"))
        ref["hfss_f_center_balance_ghz"] = d.get("f_center_balance_ghz")
        ref["hfss_f_center_s11_min_ghz"] = d.get("f_center_s11_min_ghz")
        ref["hfss_at_center"] = d.get("at_center")
    if RATRACE_ARB.exists():
        h = json.loads(RATRACE_ARB.read_text(encoding="utf-8")).get(
            "hfss_arbitration", {})
        ref["hfss_f_center_balance_ghz"] = h.get(
            "f_center_balance_ghz", ref.get("hfss_f_center_balance_ghz"))
        ref["hfss_f_center_s11_min_ghz"] = h.get(
            "f_center_s11_min_ghz", ref.get("hfss_f_center_s11_min_ghz"))
        ref["hfss_dev_pct"] = h.get("dev_vs_2p5_balance_pct")
    return ref


def _analyze(f_ghz: np.ndarray, s11_db: np.ndarray, s21_db: np.ndarray,
             s31_db: np.ndarray, s41_db: np.ndarray) -> dict:
    """中心（balance 最小点 / S11 谷）+ 三门判据（@balance 中心）。"""
    bal = np.abs(s21_db - s41_db)
    i_bal = int(np.argmin(bal))
    i_s11 = int(np.argmin(s11_db))
    fc = float(f_ghz[i_bal])
    at_c = {
        "s11_db": round(float(s11_db[i_bal]), 3),
        "s21_db": round(float(s21_db[i_bal]), 3),
        "s31_db": round(float(s31_db[i_bal]), 3),
        "s41_db": round(float(s41_db[i_bal]), 3),
        "balance_db": round(float(bal[i_bal]), 3),
        "split_diff_db": round(float(abs(s21_db[i_bal] - s41_db[i_bal])), 3),
    }
    # 门（ratrace 口径，HFSS 仲裁同款）：均分 -3±1dB 且差 ≤0.5dB；
    # Δ 隔离 ≤-20dB；S11 ≤-10dB
    gates = {
        "equal_split": bool(abs(at_c["s21_db"] + 3.0) <= 1.0
                            and abs(at_c["s41_db"] + 3.0) <= 1.0
                            and at_c["split_diff_db"] <= 0.5),
        "isolation_delta": bool(at_c["s31_db"] <= -20.0),
        "s11": bool(at_c["s11_db"] <= -10.0),
    }
    dev_pct = (fc - F0) / F0 * 100.0
    # k 判定（k=1 渲染：中心 ∝ k → k_needed = F0/f_center）
    k_needed = F0 / fc if fc > 0 else None
    return {
        "f_center_balance_ghz": round(fc, 4),
        "f_center_s11_min_ghz": round(float(f_ghz[i_s11]), 4),
        "s11_min_db": round(float(s11_db[i_s11]), 2),
        "balance_min_db": at_c["balance_db"],
        "center_dev_vs_2p5_pct": round(dev_pct, 2),
        "center_in_2pct": bool(abs(dev_pct) <= TARGET_TOL_PCT),
        "k_render": 1.0,
        "k_needed_from_center": (round(k_needed, 4)
                                 if k_needed is not None else None),
        "at_center": at_c,
        "gates": gates,
        "gates_all_pass": bool(all(gates.values())),
    }


def main() -> int:
    global RESULT

    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh-mm", type=float, default=0.4)
    ap.add_argument("--excite-port", type=int, default=1)
    ap.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--r-in-mm", type=float, default=12.0)
    ap.add_argument("--r-dom-mm", type=float, default=28.0)
    ap.add_argument("--tag", default="",
                    help="非空时产物落 pt_<tag>/ 与 *_<tag>.json（收敛对照，"
                         "不覆盖主产物）")
    args = ap.parse_args()

    from rfauto.adapters.em_solver_base import resolve_openems_exe
    from rfauto.adapters.openems_templates import render_ratrace_cylindrical

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.tag:
        RESULT = OUT_DIR / f"ratrace_cylindrical_{args.tag}.json"
    work = OUT_DIR / (f"pt_{args.tag}" if args.tag else "pt1")
    work.mkdir(parents=True, exist_ok=True)
    script = work / "simulation.py"
    script.write_text(render_ratrace_cylindrical(
        {"w_ring_mm": W_RING, "w_feed_mm": W_FEED}, (2.25, 2.75),
        mesh_resolution_mm=args.mesh_mm, excite_port=args.excite_port,
        r_in_mm=args.r_in_mm, r_dom_mm=args.r_dom_mm), encoding="utf-8")
    exe_path = resolve_openems_exe()
    exe_dir = str(Path(exe_path).resolve().parent)
    runner = work / "_rfauto_runner.py"
    runner.write_text(
        "import os\nimport runpy\nimport sys\n"
        f"os.add_dll_directory({exe_dir!r})\n"
        f"os.environ['PATH'] = {exe_dir!r} + os.pathsep + "
        "os.environ.get('PATH', '')\n"
        "runpy.run_path(sys.argv[1], run_name='__main__')\n",
        encoding="utf-8")

    _write({"item": "cyl-grid", "stage": "start", "mesh_mm": args.mesh_mm,
            "excite_port": args.excite_port, "k_render": 1.0,
            "r_in_mm": args.r_in_mm, "r_dom_mm": args.r_dom_mm,
            "timeout_s": args.timeout_s, "openems_exe": exe_path})
    print(f"[cyl-pt] render ok -> {script}", flush=True)

    log_path = work / "openems.log"
    creationflags = 0
    if os.name == "nt":
        creationflags = (subprocess.DETACHED_PROCESS
                         | subprocess.CREATE_NEW_PROCESS_GROUP)
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8") as lf:
        proc = subprocess.Popen(
            [sys.executable, str(runner.resolve()), str(script.resolve())],
            cwd=str(work.resolve()), stdout=lf, stderr=subprocess.STDOUT,
            creationflags=creationflags)
    timed_out = False
    while proc.poll() is None:
        if time.time() - t0 > args.timeout_s:
            timed_out = True
            proc.kill()
            proc.wait(timeout=60)
            break
        time.sleep(15)
        el = int(time.time() - t0)
        print(f"[cyl-pt] running {el}s ...", flush=True)
    solve_s = round(time.time() - t0, 1)
    rc = proc.returncode
    tail = ""
    if log_path.exists():
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-1200:]
    print(f"[cyl-pt] done rc={rc} solve_s={solve_s} timed_out={timed_out}",
          flush=True)

    csv_path = work / "sparams.csv"
    if not csv_path.exists():
        _write({"stage": "timeout" if timed_out else "failed",
                "solve_s": solve_s, "returncode": rc,
                "stdout_tail": tail, **_hfss_ref()})
        print("NO_CSV", tail[-800:], flush=True)
        return 1

    data = np.loadtxt(str(csv_path), delimiter=",", skiprows=1)
    f = data[:, 0] / 1e9
    s11 = 20 * np.log10(np.hypot(data[:, 1], data[:, 2]) + 1e-12)
    s21 = 20 * np.log10(np.hypot(data[:, 3], data[:, 4]) + 1e-12)
    s31 = 20 * np.log10(np.hypot(data[:, 5], data[:, 6]) + 1e-12)
    s41 = 20 * np.log10(np.hypot(data[:, 7], data[:, 8]) + 1e-12)
    ana = _analyze(f, s11, s21, s31, s41)
    out = {"stage": "done", "solve_s": solve_s, "returncode": rc,
           "mesh_mm": args.mesh_mm, "excite_port": args.excite_port,
           "n_freq": len(f), **_hfss_ref(), **ana}
    _write(out)
    print(json.dumps(ana, indent=2, ensure_ascii=False), flush=True)
    verdict = ("K1_ROOT_CAUSE_CONFIRMED"
               if ana["center_in_2pct"] and ana["gates_all_pass"]
               else ("CENTER_OK_GATES_FAIL" if ana["center_in_2pct"]
                     else "CENTER_OFF"))
    print(f"RATRACE_CYLINDRICAL_{verdict}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
