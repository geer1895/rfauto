"""平行耦合 BPF 真机加长复跑：NrTS 截断假设裁决（openems-real-smoke-bundle ②）。

背景：前两轮真机（runs/coupled_bpf_smoke/pt1 与
pt2_wide）同频 |S21| 互差 13dB、带缘 |S11|=+0.4dB 非物理，归因『NrTS=100000
截断高 Q 储能』为假设待证。本脚本：

1. 探针实证（本轮开工前已用 pt1 原脚本做 NrTS=10 十步探针 + NrTS=1e6 头部
   读取）：pt1 网格 379×1203×19=8.66M 元、dt=7.169e-14 s、Nyquist 2536 步、
   **激励脉冲自然长度 159840 步=11.46ns**；pt1 port_ut t_end=7.136ns → 约
   99.5k 步 ≈ NrTS=100000 ⇒ **pt1 被 NrTS 截断于激励脉冲进行中（62.6%）**，
   储能环节根本没跑到——假设成立且比原表述更强。
2. 复跑：build_geometry 后对 simulation.py 做脚本级 `NrTS=100000→NrTS=N`
   改写（先例 scripts/audit_forensic_mesh.py:49；可选显式 EndCriteria），
   自驱 subprocess 留全程日志（引擎头部 dt/激励长度/NrTS 倍数 + 逐 4s 进度
   Energy dB + 末尾实际迭代数 → 终止原因可判），零源码改动。
3. 判读：coupled_bpf_smoke.py 五门（插损/纹波/回损/峰位/β）+ 无源性门
   （带内 |S11|,|S21| ≤0dB、|S11|²+|S21|² ≤1+2%）+ 终止诊断（实际步数 ≥
   激励长度、是否触 NrTS 上限）+ 与 pt1/pt2_wide 同频 |S21| 互差（报告项）。
   不收敛则如实 FAIL；COUPLED_BPF_NOMINAL / 逐端 Δl / w_feed 一律不碰（#11
   属地，#122 不凑绿）。

运行（>10min，Start-Process 分离 + 日志轮询，#157）：
  python scripts/smoke_coupled_bpf_nrts.py --pt pt3_nrts --nrts 400000
证据链 runs/coupled_bpf_smoke/<pt>/{simulation.py,engine.log,sparams.csv,
port_beta.csv,_smoke_result.json}。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.openems_templates import (
    COUPLED_BPF_NOMINAL,
    coupled_bpf_circuit_sparams,
    coupled_bpf_design_from_order,
)
from rfauto.core.calculators import coupling_matrix_response
from rfauto.core.synthesis import Stackup, forward_z0

NRTS_OLD = 100000
F0 = 2.5

_RE_DT = re.compile(r"FDTD timestep is: ([0-9.eE+-]+) s; Nyquist rate: (\d+) timesteps @([0-9.eE+-]+) Hz")
_RE_EXC = re.compile(r"Excitation signal length is: (\d+) timesteps \(([0-9.eE+-]+)s\)")
_RE_MAX = re.compile(r"Max\. number of timesteps: (\d+) \( --> ([0-9.eE+-]+) \* Excitation signal length\)")
_RE_SIZE = re.compile(r"FDTD simulation size: (\d+)x(\d+)x(\d+) --> ([0-9.eE+-]+) FDTD cells")
_RE_DONE = re.compile(r"Time for (\d+) iterations with ([0-9.eE+-]+) cells : ([0-9.]+) sec")
_RE_PROG = re.compile(r"Timestep:\s+(\d+) \|\|.*?Energy: ~([0-9.eE+-]+) \(\s*(-?[0-9.]+)dB\)")
_RE_NRTS_WARN = re.compile(
    r"Max\. number of timesteps was reached before the end-criteria of (-?[0-9.]+)dB")

# pt1（runs/coupled_bpf_smoke/pt1/simulation.py 原脚本）探针实证（
# NrTS=10 十步 + NrTS=1e6 头部读取后 kill；日志留档 pt3_nrts/_probe_nrts10/）：
# 旧轮终止诊断必须用旧脚本自身的 dt——模板此后有漂移（本轮渲染 377×1203×19、
# dt=7.58e-14s），拿新 dt 反推旧步数会误判。
PT1_PROBE: dict[str, float | int] = {
    "dt_s": 7.16917e-14, "nyquist_steps": 2536, "cells": 8.6628e6,
    "excitation_steps": 159840, "excitation_s": 1.14592e-8,
}


def rewrite_nrts(script: str, new_nrts: int, old_nrts: int = NRTS_OLD,
                 end_criteria: float | None = None) -> tuple[str, int]:
    """脚本级改写 `NrTS=<old>` → `NrTS=<new>`（全部出现处：主 FDTD 与 _FDTD3 副本）。

    幂等：已改写脚本再调用替换 0 次且内容不变；end_criteria 只补到
    `openEMS(NrTS=<new>)` 裸调用（已带 EndCriteria 的不重复追加）。
    返回 (脚本, 本次 NrTS 替换次数)。
    """
    pat = re.compile(rf"NrTS={old_nrts}\b")
    n = len(pat.findall(script))
    out = pat.sub(f"NrTS={new_nrts}", script)
    if end_criteria is not None:
        out = out.replace(f"openEMS(NrTS={new_nrts})",
                          f"openEMS(NrTS={new_nrts}, EndCriteria={float(end_criteria)!r})")
    return out, n


def parse_engine_log(text: str) -> dict[str, object]:
    """openEMS 引擎 stdout → 头部/进度/终止诊断（纯解析，离线可测）。"""
    info: dict[str, object] = {}
    if (m := _RE_SIZE.search(text)):
        info["grid"] = [int(m.group(1)), int(m.group(2)), int(m.group(3))]
        info["cells"] = float(m.group(4))
    if (m := _RE_DT.search(text)):
        info["dt_s"] = float(m.group(1))
        info["nyquist_steps"] = int(m.group(2))
        info["f_max_hz"] = float(m.group(3))
    if (m := _RE_EXC.search(text)):
        info["excitation_steps"] = int(m.group(1))
        info["excitation_s"] = float(m.group(2))
    if (m := _RE_MAX.search(text)):
        info["nrts"] = int(m.group(1))
        info["nrts_over_excitation"] = float(m.group(2))
    if (m := _RE_DONE.search(text)):
        info["iterations_done"] = int(m.group(1))
        info["engine_wall_s"] = float(m.group(3))
    if (m := _RE_NRTS_WARN.search(text)):
        info["nrts_limit_warning"] = True
        info["end_criteria_db"] = float(m.group(1))
    elif "iterations_done" in info:
        info["nrts_limit_warning"] = False
    prog = _RE_PROG.findall(text)
    if prog:
        info["last_progress_step"] = int(prog[-1][0])
        info["last_energy_db"] = float(prog[-1][2])
        info["min_energy_db"] = float(min(float(p[2]) for p in prog))
    if "iterations_done" in info and "nrts" in info:
        done = int(info["iterations_done"])
        info["hit_nrts_limit"] = done >= int(info["nrts"])
        if "excitation_steps" in info:
            info["excitation_covered"] = done >= int(info["excitation_steps"])
    return info


def diagnose_old_run(port_ut_path: Path, dt_s: float,
                     nrts_old: int = NRTS_OLD) -> dict[str, object]:
    """旧轮终止诊断：port_ut 末采样时刻 / dt → 估计实际步数（Nyquist/4 抽样，
    末点 ≤ 真步数 < 末点+采样间隔），≥0.98·NrTS 判为 NrTS 截断。"""
    t = np.loadtxt(str(port_ut_path), comments="%")[:, 0]
    t_end = float(t[-1])
    steps = t_end / dt_s
    return {"port_ut": str(port_ut_path), "t_end_s": t_end,
            "steps_est": steps, "nrts_old": nrts_old,
            "nrts_limited": bool(steps >= 0.98 * nrts_old)}


def read_csv_cols(path: Path) -> np.ndarray:
    return np.loadtxt(str(path), delimiter=",", skiprows=1)


def _run_engine(work: Path, exe_path: str | None, timeout_s: float,
                log_path: Path) -> int:
    runner = work / "_rfauto_runner.py"
    if exe_path:
        exe_dir = str(Path(exe_path).resolve().parent)
        runner.write_text(
            "import os\nimport runpy\nimport sys\n"
            f"os.add_dll_directory({exe_dir!r})\n"
            f"os.environ['PATH'] = {exe_dir!r} + os.pathsep + os.environ.get('PATH', '')\n"
            "runpy.run_path(sys.argv[1], run_name='__main__')\n",
            encoding="utf-8")
    cmd = [sys.executable] + ([str(runner.resolve())] if runner.exists() else []) + \
        [str((work / "simulation.py").resolve())]
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.run(cmd, cwd=str(work.resolve()), stdout=log,
                              stderr=subprocess.STDOUT, timeout=timeout_s)
    return int(proc.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pt", default="pt3_nrts")
    parser.add_argument("--nrts", type=int, default=400000)
    parser.add_argument("--end-criteria", type=float, default=None,
                        help="显式 EndCriteria（缺省不加=官方口径，引擎默认 1e-5）")
    parser.add_argument("--mesh", type=float, default=0.4)
    parser.add_argument("--order", type=int, default=3)
    parser.add_argument("--fbw", type=float, default=0.05)
    parser.add_argument("--rl", type=float, default=20.0)
    parser.add_argument("--flo", type=float, default=2.25)
    parser.add_argument("--fhi", type=float, default=2.75)
    parser.add_argument("--timeout", type=float, default=21600.0)
    parser.add_argument("--old-run", default="runs/coupled_bpf_smoke/pt1")
    parser.add_argument("--old-run-wide", default="runs/coupled_bpf_smoke/pt2_wide")
    args = parser.parse_args(argv)

    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    design = coupled_bpf_design_from_order(args.order, F0, args.fbw, args.rl)
    params = dict(COUPLED_BPF_NOMINAL)   # 只消费不改（#11 属地）
    params["order"] = args.order
    _, eps_hj_feed = forward_z0(params["w_feed_mm"], F0, stackup)

    work = Path(f"runs/coupled_bpf_smoke/{args.pt}")
    exe = resolve_openems_exe()
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=exe, working_dir=str(work),
        freq_range_ghz=(args.flo, args.fhi), mesh_resolution_mm=args.mesh,
        extra_params={"solve_timeout_s": args.timeout}))
    assert solver.connect(), "openEMS 不可用"
    assert solver.build_geometry({"template": "coupled_bpf", "params": params})
    script_path = work / "simulation.py"
    script, n_sub = rewrite_nrts(script_path.read_text(encoding="utf-8"),
                                 args.nrts, end_criteria=args.end_criteria)
    assert n_sub >= 1, "渲染脚本无 NrTS=100000 可改写（模板口径漂移？）"
    script_path.write_text(script, encoding="utf-8")
    print(f"NrTS {NRTS_OLD}→{args.nrts} 替换 {n_sub} 处；EndCriteria="
          f"{args.end_criteria}", flush=True)

    t0 = time.time()
    rc = _run_engine(work, exe, args.timeout, work / "engine.log")
    wall = time.time() - t0
    log_text = (work / "engine.log").read_text(encoding="utf-8", errors="replace")
    eng = parse_engine_log(log_text)
    print(f"solve_s={wall:.0f} rc={rc} engine={json.dumps(eng)}", flush=True)
    sp = work / "sparams.csv"
    assert rc == 0 and sp.exists(), f"openEMS 真跑失败 rc={rc}（见 {work / 'engine.log'}）"

    # 旧轮终止诊断：pt1 用其自身探针 dt（PT1_PROBE）；pt2_wide 频段/dt 不同仅记 t_end
    old: dict[str, object] = {}
    p1 = Path(args.old_run) / "fdtd" / "port_ut_1A"
    if p1.exists():
        old["pt1"] = diagnose_old_run(p1, float(PT1_PROBE["dt_s"]))
        old["pt1"]["dt_source"] = "PT1_PROBE（pt1 原脚本 NrTS=10 探针实测）"
        old["pt1"]["excitation_steps_natural"] = int(PT1_PROBE["excitation_steps"])
        old["pt1"]["truncated_inside_excitation"] = bool(
            float(old["pt1"]["steps_est"]) < float(PT1_PROBE["excitation_steps"]))
    p2 = Path(args.old_run_wide) / "fdtd" / "port_ut_1A"
    if p2.exists():
        t2 = np.loadtxt(str(p2), comments="%")[:, 0]
        old["pt2_wide"] = {"port_ut": str(p2), "t_end_s": float(t2[-1]),
                           "note": "频段 (2.0,3.0) 与 pt1 不同 → dt 未探针，不反推步数"}

    # ── S 参数与裁判（coupled_bpf_smoke.py 同口径）──
    data = read_csv_cols(sp)
    f_ghz = data[:, 0] / 1e9
    s11 = data[:, 1] + 1j * data[:, 2]
    s21 = data[:, 3] + 1j * data[:, 4]
    s11_db = 20 * np.log10(np.abs(s11) + 1e-12)
    s21_db = 20 * np.log10(np.abs(s21) + 1e-12)

    d_feed = float("nan")
    beta_csv = work / "port_beta.csv"
    if beta_csv.exists():
        with open(beta_csv, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))[1:]
        bf = np.array([float(r[0]) for r in rows])
        bb = np.array([float(r[1]) for r in rows])
        sel = (bf >= 0.96 * F0 * 1e9) & (bf <= 1.04 * F0 * 1e9)
        eps_feed = (float(np.median(bb[sel])) * 299792458.0 / (2 * np.pi * F0 * 1e9)) ** 2
        d_feed = (eps_feed / eps_hj_feed - 1) * 100

    circuit = coupled_bpf_circuit_sparams(f_ghz, design)
    circ_s21 = 20.0 * np.log10(np.abs(circuit[:, 1, 0]) + 1e-12)
    ideal = coupling_matrix_response(
        freq_ghz=[float(v) for v in f_ghz], f0_ghz=F0, fbw=args.fbw,
        matrix=design["coupling_matrix"])
    ideal_s21 = np.asarray(ideal["s21_db"], dtype=float)
    band = (f_ghz >= F0 * (1 - args.fbw / 2)) & (f_ghz <= F0 * (1 + args.fbw / 2))
    i_peak = int(np.argmax(s21_db))
    f_peak = float(f_ghz[i_peak])
    il_min = float(s21_db[band].min())
    ripple = float(s21_db[band].max() - s21_db[band].min())
    s11_band = float(s11_db[band].max())
    circ_peak = float(f_ghz[int(np.argmax(circ_s21))])
    d_em_circ = float(np.max(np.abs(s21_db[band] - circ_s21[band])))
    power = np.abs(s11) ** 2 + np.abs(s21) ** 2

    # 与旧轮同频 |S21| 互差（报告项）
    cmp_old: dict[str, object] = {}
    for tag, d in (("pt1", Path(args.old_run)), ("pt2_wide", Path(args.old_run_wide))):
        p = d / "sparams.csv"
        if not p.exists():
            continue
        od = read_csv_cols(p)
        of = od[:, 0] / 1e9
        o21 = 20 * np.log10(np.abs(od[:, 3] + 1j * od[:, 4]) + 1e-12)
        o11 = 20 * np.log10(np.abs(od[:, 1] + 1j * od[:, 2]) + 1e-12)
        lo, hi = max(f_ghz[0], of[0]), min(f_ghz[-1], of[-1])
        grid = np.linspace(lo, hi, 101)
        d21 = np.interp(grid, f_ghz, s21_db) - np.interp(grid, of, o21)
        cmp_old[tag] = {"common_band_ghz": [float(lo), float(hi)],
                        "max_abs_ds21_db": float(np.max(np.abs(d21))),
                        "mean_abs_ds21_db": float(np.mean(np.abs(d21))),
                        "old_s11_max_db": float(o11.max()),
                        "old_s21_max_db": float(o21.max())}

    gates = {
        "il_min_db": {"value": il_min, "ok": -3.0 <= il_min <= -0.2},
        "ripple_db": {"value": ripple, "ok": ripple <= 4.0},
        "rl_band_max_db": {"value": s11_band, "ok": s11_band <= -8.0},
        "peak_vs_circuit_pct": {"value": abs(f_peak - circ_peak) / circ_peak * 100,
                                "ok": abs(f_peak - circ_peak) / circ_peak <= 0.05},
        "beta_feed_pct": {"value": d_feed,
                          "ok": bool(np.isnan(d_feed) or abs(d_feed) <= 3.0)},
        "passive_s11_max_db": {"value": float(s11_db.max()), "ok": float(s11_db.max()) <= 0.0},
        "passive_s21_max_db": {"value": float(s21_db.max()), "ok": float(s21_db.max()) <= 0.0},
        "power_sum_max": {"value": float(power.max()), "ok": float(power.max()) <= 1.02},
        "excitation_covered": {"value": eng.get("excitation_covered"),
                               "ok": bool(eng.get("excitation_covered", False))},
    }
    five_ok = all(gates[k]["ok"] for k in
                  ("il_min_db", "ripple_db", "rl_band_max_db", "peak_vs_circuit_pct", "beta_feed_pct"))
    passive_ok = all(gates[k]["ok"] for k in
                     ("passive_s11_max_db", "passive_s21_max_db", "power_sum_max"))
    ok = five_ok and passive_ok and gates["excitation_covered"]["ok"]
    verdict = "PASS" if ok else ("PARTIAL" if passive_ok else "FAIL")

    i_mid = int(np.argmin(np.abs(f_ghz - F0)))
    print(f"@{F0}GHz |S21|={s21_db[i_mid]:.2f}dB |S11|={s11_db[i_mid]:.1f}dB（电路预测 "
          f"|S21|={circ_s21[i_mid]:.2f}）；峰位={f_peak:.4f}（电路 {circ_peak:.4f}）"
          f" IL={il_min:.2f} ripple={ripple:.2f} RL={s11_band:.1f} β{d_feed:+.2f}%")
    print(f"无源性：max|S11|={s11_db.max():+.2f}dB max|S21|={s21_db.max():+.2f}dB "
          f"max(|S11|²+|S21|²)={power.max():.4f}；EM vs 电路带内 max|ΔS21|={d_em_circ:.2f}dB")
    print("旧轮诊断:", json.dumps(old), "| 同频互差:", json.dumps(cmp_old), flush=True)
    print(f"COUPLED_BPF_NRTS_{verdict}", flush=True)

    result = {
        "item": "openems-real-smoke-bundle/②coupled_bpf_nrts", "verdict": verdict,
        "pt": args.pt, "nrts": args.nrts, "nrts_old": NRTS_OLD,
        "end_criteria": args.end_criteria, "n_nrts_substitutions": n_sub,
        "mesh_mm": args.mesh, "freq_range_ghz": [args.flo, args.fhi],
        "design": {k: params[k] for k in ("w_feed_mm", "res_len_mm", "feed_len_mm",
                                           "widths_mm", "gaps_mm")},
        "solve_s": round(wall, 1), "rc": rc, "engine": eng,
        "old_run_termination": old,
        "metrics": {"f_peak_ghz": f_peak, "circuit_peak_ghz": circ_peak,
                    "il_min_db": il_min, "ripple_db": ripple, "rl_band_max_db": s11_band,
                    "beta_feed_pct": d_feed, "em_vs_circuit_max_ds21_db": d_em_circ,
                    "s21_at_f0_db": float(s21_db[i_mid]), "s11_at_f0_db": float(s11_db[i_mid]),
                    "ideal_s21_at_f0_db": float(ideal_s21[i_mid])},
        "gates": gates, "five_gate_ok": five_ok, "passivity_ok": passive_ok,
        "compare_old_runs": cmp_old,
        "hypothesis": "NrTS=100000 截断：pt1 dt=7.169e-14s，激励脉冲 159840 步=11.46ns，"
                      "pt1 port_ut t_end=7.136ns≈99.5k 步 → 截断于脉冲进行中（探针实证）",
    }
    (work / "_smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
