"""rat-race k(BASE) 定版真机核验（ratrace-k-finalize 子项 B）：openEMS Σ 单激励
进程隔离 run，按网格档施加 ratrace_ring_mesh_k(BASE) 复跑并判读 hybrid 中心。

口径（openems_convergence.json 两点标度的定版回验）：
- 同 pt9/convergence 渲染（render_script("ratrace")，band 2.25–2.75GHz），
  excite_port=1（Σ）单激励单进程（#208 安全模式）；--excite-port 3 可选加跑 Δ 口；
- 产物 sparams.csv 9 列（S11/S21/S31/S41 相对激励口），单列判读中心：
  balance 最小点 argmin(||S21|dB−|S41|dB|) 与 S11 谷（s11_db_min 语义，#195）；
- 判据：balance 中心 2.5GHz±2%（HFSS 仲裁 2.465GHz 为对齐基准）且 pt9 门不劣化
  （bal≤0.5dB、S11≤−20dB、S31≤−20dB、S21/S41=−3.2±0.5dB，均取 balance 点）；
- 有效 k：k_eff = k_applied × F0 / f_center_avg（一阶：中心 ∝ k；与
  openems_convergence.json 的 k_needed 同约定）；两点 df/dk 修正（B1 第二轮）
  用 --k-override 施加（monkeypatch 模块级 ratrace_ring_mesh_k，几何段与近场线
  同 k）。
- run 子命令：单次真跑落 runs/ratrace_arbitration/k_finalize/<label>/
  （simulation.py/sparams.csv/result.json）并追加 summary.json；
  finalize 子命令：汇总有效 k、与函数锚比对（>1% 提示回写）、向
  ratrace_arbitration.json / openems_convergence.json **只追加** k_finalize 段，
  hfss_arbitration.json 在 ok=True 前提下把 run2 陈旧 error 键改名 stale_error_run2。

真机纪律：本轨同时刻单求解进程；长任务分离进程+日志轮询（#157）；HFSS 不重跑。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
ARB_DIR = REPO / "runs" / "ratrace_arbitration"
OUT_DIR = ARB_DIR / "k_finalize"
SUMMARY = OUT_DIR / "summary.json"

W_RING, W_FEED, R_PHYS, F0 = 0.6035, 1.1134, 17.344, 2.5
BAND = (2.25, 2.75)
HFSS_CENTER_GHZ = 2.465          # 仲裁权威锚（ratrace_arbitration.json）
K_PT8 = 1.0975                   # 归档锚（openems_convergence.json k_current）
F_AVG_0P4_AT_K_PT8 = 2.3544      # 0.4mm f_center_avg @k=1.0975（pt9 复算）
F_AVG_0P2_AT_K_PT8 = 2.5225      # 0.2mm f_center_avg @k=1.0975（convergence run）

GATES = {"center_tol_pct": 2.0, "bal_max_db": 0.5, "s11_max_db": -20.0,
         "s31_max_db": -20.0, "s21_target_db": -3.2, "s21_tol_db": 0.5}


def _db(re_col: np.ndarray, im_col: np.ndarray) -> np.ndarray:
    return 20 * np.log10(np.hypot(re_col, im_col) + 1e-12)


def _center_from_columns(f_ghz: np.ndarray, s11_db: np.ndarray, s21_db: np.ndarray,
                         s31_db: np.ndarray, s41_db: np.ndarray) -> dict:
    """convergence 同式（balance argmin + S11 谷）+ balance 点全列读数。"""
    bal = np.abs(s21_db - s41_db)
    i_bal = int(np.argmin(bal))
    i_s11 = int(np.argmin(s11_db))
    f_bal = float(f_ghz[i_bal])
    f_s11 = float(f_ghz[i_s11])
    return {"f_center_balance_ghz": round(f_bal, 4),
            "f_center_s11_min_ghz": round(f_s11, 4),
            "f_center_avg_ghz": round(0.5 * (f_bal + f_s11), 4),
            "balance_min_db": round(float(bal[i_bal]), 3),
            "s11_min_db": round(float(s11_db[i_s11]), 2),
            "s11_db_at_bal": round(float(s11_db[i_bal]), 2),
            "s21_db_at_bal": round(float(s21_db[i_bal]), 2),
            "s31_db_at_bal": round(float(s31_db[i_bal]), 2),
            "s41_db_at_bal": round(float(s41_db[i_bal]), 2),
            "s31_max_db_inband_pm5pct": round(float(np.max(
                s31_db[(f_ghz >= 0.95 * F0) & (f_ghz <= 1.05 * F0)])), 2)}


def _gates(c: dict, excite_port: int) -> dict:
    """B1/B2 判据（Σ 激励口径）；Δ 口（excite_port=3）只记读数不判 Σ 门。"""
    dev = 100.0 * (c["f_center_balance_ghz"] - F0) / F0
    g = {"center_dev_pct": round(dev, 2),
         "center_in_2pct": abs(dev) <= GATES["center_tol_pct"],
         "dev_vs_hfss_pct": round(100.0 * (c["f_center_balance_ghz"] - HFSS_CENTER_GHZ)
                                  / HFSS_CENTER_GHZ, 2)}
    if excite_port == 1:
        g.update({
            "bal_ok": c["balance_min_db"] <= GATES["bal_max_db"],
            "s11_ok": c["s11_db_at_bal"] <= GATES["s11_max_db"],
            "s31_ok": c["s31_db_at_bal"] <= GATES["s31_max_db"],
            "s21_ok": abs(c["s21_db_at_bal"] - GATES["s21_target_db"]) <= GATES["s21_tol_db"],
            "s41_ok": abs(c["s41_db_at_bal"] - GATES["s21_target_db"]) <= GATES["s21_tol_db"],
        })
        g["all_pass"] = bool(g["center_in_2pct"] and g["bal_ok"] and g["s11_ok"]
                             and g["s31_ok"] and g["s21_ok"] and g["s41_ok"])
    else:
        g["all_pass"] = None
    return g


def _render(mesh_mm: float, excite_port: int, k_override: float | None):
    import re

    import rfauto.adapters.openems_templates as ot

    if k_override is not None:
        k_applied = float(k_override)
        # 定标轮 k 施加：模块级函数替换，_near_points 与 _ratrace_lines 在调用时
        # 解析同一全局名 → 几何段与近场线同 k（与生产路径同构）
        ot.ratrace_ring_mesh_k = lambda _b, _k=k_applied: _k
    text = ot.render_script("ratrace", {"w_ring_mm": W_RING, "w_feed_mm": W_FEED},
                            BAND, mesh_resolution_mm=mesh_mm, excite_port=excite_port)
    base_mm = float(re.search(r"BASE = ([0-9.eE+-]+)", text).group(1)) * 1e3
    m = re.search(r"R_RING = [0-9.]+ \* 1e-3 / ([0-9.]+)", text)
    k_in_script = float(m.group(1))
    if k_override is None:
        k_applied = k_in_script
    assert abs(k_in_script - k_applied) < 1e-9, (k_in_script, k_applied)
    return text, k_applied, base_mm


def _run_openems(work: Path, text: str, timeout_s: int) -> tuple[float, Path | None, str]:
    from rfauto.adapters.em_solver_base import resolve_openems_exe

    work.mkdir(parents=True, exist_ok=True)
    script = work / "simulation.py"
    script.write_text(text, encoding="utf-8")
    exe_dir = str(Path(resolve_openems_exe()).resolve().parent)
    runner = work / "_rfauto_runner.py"
    runner.write_text(
        "import os\nimport runpy\nimport sys\n"
        f"os.add_dll_directory({exe_dir!r})\n"
        f"os.environ['PATH'] = {exe_dir!r} + os.pathsep + "
        "os.environ.get('PATH', '')\n"
        "runpy.run_path(sys.argv[1], run_name='__main__')\n",
        encoding="utf-8")
    t0 = time.time()
    proc = subprocess.run([sys.executable, str(runner.resolve()), str(script.resolve())],
                          capture_output=True, text=True, timeout=timeout_s,
                          cwd=str(work.resolve()))
    solve_s = round(time.time() - t0, 1)
    (work / "stdout_tail.txt").write_text((proc.stdout or "")[-4000:], encoding="utf-8")
    (work / "stderr_tail.txt").write_text((proc.stderr or "")[-4000:], encoding="utf-8")
    csv_path = work / "sparams.csv"
    return solve_s, (csv_path if csv_path.exists() else None), (proc.stderr or "")[-800:]


def _append_summary(rec: dict) -> None:
    data = {"runs": []}
    if SUMMARY.exists():
        data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    data["runs"] = [r for r in data.get("runs", []) if r.get("label") != rec["label"]]
    data["runs"].append(rec)
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    SUMMARY.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_run(args: argparse.Namespace) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    work = OUT_DIR / args.label
    text, k_applied, base_mm = _render(args.mesh, args.excite_port, args.k_override)
    rec = {"label": args.label, "stage": "running", "mesh_mm": args.mesh,
           "base_mm": round(base_mm, 4), "k_applied": round(k_applied, 6),
           "k_override": args.k_override, "excite_port": args.excite_port,
           "band_ghz": list(BAND), "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _append_summary(rec)
    print(f"[{args.label}] mesh={args.mesh} BASE={base_mm:.4f}mm k={k_applied:.6f} "
          f"excite_port={args.excite_port} timeout={args.timeout}s", flush=True)
    solve_s, csv_path, err_tail = _run_openems(work, text, args.timeout)
    rec["solve_s"] = solve_s
    if csv_path is None:
        rec.update({"stage": "failed", "stderr_tail": err_tail})
        _append_summary(rec)
        print(f"[{args.label}] NO_CSV solve_s={solve_s}\n{err_tail}", flush=True)
        return 1
    data = np.loadtxt(str(csv_path), delimiter=",", skiprows=1)
    f = data[:, 0] / 1e9
    c = _center_from_columns(f, _db(data[:, 1], data[:, 2]), _db(data[:, 3], data[:, 4]),
                             _db(data[:, 5], data[:, 6]), _db(data[:, 7], data[:, 8]))
    g = _gates(c, args.excite_port)
    k_eff_avg = k_applied * F0 / c["f_center_avg_ghz"]
    k_eff_bal = k_applied * F0 / c["f_center_balance_ghz"]
    rec.update({"stage": "done", "center": c, "gates": g,
                "k_eff_avg": round(k_eff_avg, 4), "k_eff_balance": round(k_eff_bal, 4),
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    if args.excite_port == 3:
        # Δ 口：S23/S43 反相 + S13（Δ→Σ 隔离）读数（相位取 balance 点）
        i_bal = int(np.argmin(np.abs(_db(data[:, 3], data[:, 4]) - _db(data[:, 7], data[:, 8]))))
        ph2 = float(np.angle(data[i_bal, 3] + 1j * data[i_bal, 4]))
        ph4 = float(np.angle(data[i_bal, 7] + 1j * data[i_bal, 8]))
        dphi = abs((ph2 - ph4 + np.pi) % (2 * np.pi) - np.pi)
        rec["delta_port"] = {"f_bal_ghz": round(float(f[i_bal]), 4),
                             "antiphase_dev_rad": round(abs(dphi - np.pi), 4),
                             "s13_db_at_bal": round(float(_db(data[:, 1], data[:, 2])[i_bal]), 2)}
    (work / "result.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    _append_summary(rec)
    print(json.dumps(rec, indent=2, ensure_ascii=False), flush=True)
    print(f"RATRACE_K_FINALIZE_RUN_{'PASS' if g.get('all_pass') else 'RECORDED'}", flush=True)
    return 0


def _propose_round2_k(f_avg_new: float, k_new: float, f_avg_old: float, k_old: float) -> dict:
    """两点线性 df/dk 拟合 → 把 f_center_avg 拉到 F0 的 k（敏感度<1/R 情形）。"""
    dfdk = (f_avg_new - f_avg_old) / (k_new - k_old)
    k2 = k_new + (F0 - f_avg_new) / dfdk if abs(dfdk) > 1e-9 else None
    return {"df_dk_ghz_per_k": round(dfdk, 4), "k_round2": (round(k2, 4) if k2 else None),
            "points": [[k_old, f_avg_old], [k_new, f_avg_new]]}


def cmd_finalize(args: argparse.Namespace) -> int:
    from rfauto.adapters.openems_templates import (
        _RATRACE_K_ANCHOR_HI,
        _RATRACE_K_ANCHOR_LO,
        ratrace_ring_mesh_k,
    )

    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    runs = [r for r in data["runs"] if r.get("stage") == "done"]
    by_mesh: dict[float, list[dict]] = {}
    for r in runs:
        by_mesh.setdefault(float(r["mesh_mm"]), []).append(r)
    out = {"date": time.strftime("%Y-%m-%d"), "method": "Σ 单激励进程隔离复跑，"
           "k(BASE)=ratrace_ring_mesh_k 施加；k_eff=k_applied×F0/f_center_avg（一阶）",
           "anchors_in_code": {"k_0p2mm": _RATRACE_K_ANCHOR_LO, "k_0p4mm": _RATRACE_K_ANCHOR_HI},
           "hfss_anchor_ghz": HFSS_CENTER_GHZ, "runs": {}}
    for mesh, rs in sorted(by_mesh.items()):
        rs = sorted(rs, key=lambda r: r.get("finished_at", ""))
        last = [r for r in rs if r["excite_port"] == 1][-1] if any(
            r["excite_port"] == 1 for r in rs) else rs[-1]
        anchor = ratrace_ring_mesh_k(mesh)
        out["runs"][f"mesh_{mesh}"] = {
            "labels": [r["label"] for r in rs], "final_label": last["label"],
            "k_applied": last["k_applied"], "k_eff_avg": last["k_eff_avg"],
            "k_eff_balance": last["k_eff_balance"], "center": last["center"],
            "gates": last["gates"], "solve_s": last["solve_s"],
            "anchor_k_in_code": round(anchor, 6),
            "k_eff_vs_anchor_pct": round(100.0 * (last["k_eff_avg"] - anchor) / anchor, 2),
            "rewrite_anchor_needed": abs(last["k_eff_avg"] - anchor) / anchor > 0.01}
    out["note"] = ("与函数锚差 >1% 的档需回写 _RATRACE_K_ANCHOR_*（并重算 α、更新测试钉值与 "
                   "docs）；≤1% 保留初始锚（回验闭合）")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "k_finalize_verdict.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    # 只追加 k_finalize 段（既有键不覆写）
    for target in (ARB_DIR / "ratrace_arbitration.json", ARB_DIR / "openems_convergence.json"):
        if not target.exists():
            continue
        d = json.loads(target.read_text(encoding="utf-8"))
        d["k_finalize"] = out
        target.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    # hfss_arbitration.json：ok=True 前提下把 run2 陈旧 error/verdict 键改名（本地数据卫生，
    # runs/ 不入 git；权威数据=ratrace_arbitration.json）
    hfss = ARB_DIR / "hfss_arbitration.json"
    if hfss.exists():
        d = json.loads(hfss.read_text(encoding="utf-8"))
        renamed = []
        if d.get("ok") is True:
            for old, new in (("error", "stale_error_run2"), ("verdict", "stale_verdict_run2")):
                if old in d and new not in d:
                    d[new] = d.pop(old)
                    renamed.append(f"{old}→{new}")
        if renamed:
            d["stale_note"] = ("run2 陈旧残留（attempt 3/3 FAIL 内部辐射边界 / DESIGN_ERROR）与 "
                               "ok=True/attempt=1/solve_s=63 并存；权威数据=ratrace_arbitration.json；"
                               f"改名于 {time.strftime('%Y-%m-%d')} ratrace-k 定版：{', '.join(renamed)}")
            hfss.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"hfss_arbitration.json: {', '.join(renamed)}", flush=True)
    print(json.dumps(out, indent=2, ensure_ascii=False), flush=True)
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    f_old = F_AVG_0P4_AT_K_PT8 if args.mesh == 0.4 else F_AVG_0P2_AT_K_PT8
    print(json.dumps(_propose_round2_k(args.f_avg_new, args.k_new, f_old, K_PT8),
                     indent=2), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="单次 openEMS 真跑")
    r.add_argument("--mesh", type=float, required=True, help="mesh_resolution_mm（0=自动档）")
    r.add_argument("--label", required=True)
    r.add_argument("--excite-port", type=int, default=1)
    r.add_argument("--k-override", type=float, default=None,
                   help="定标轮 k 覆盖（默认按 ratrace_ring_mesh_k(BASE)）")
    r.add_argument("--timeout", type=int, default=36000)
    r.set_defaults(fn=cmd_run)
    p = sub.add_parser("propose", help="两点 df/dk 提议第二轮 k")
    p.add_argument("--mesh", type=float, required=True)
    p.add_argument("--k-new", type=float, required=True)
    p.add_argument("--f-avg-new", type=float, required=True)
    p.set_defaults(fn=cmd_propose)
    f = sub.add_parser("finalize", help="汇总有效 k、追加归档段")
    f.set_defaults(fn=cmd_finalize)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
