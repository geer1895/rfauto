"""rm-oe-c3 判读器（criteria.md G0–G4 确定性判读，写死不调；铁律 7 数值只出内核/判读器）。

公开仓落位：scripts/judge_refix.py（内部 runs/smoke_c3_refix 归档同文移植）——
band_center_3db（#298 −3dB 带心口径）单一事实源，scripts/c3_fullcurve_runner.py
判读复用；本文件 CLI 入口面向 runs/smoke_c3_refix 归档布局。

输入：runs/smoke_c3_refix/<template>/{_smoke_result.json, sparams.csv, fdtd/}。
输出：runs/smoke_c3_refix/<template>/judge_refix.json。

G0 收敛门 = 脚本 nrts_convergence（触 NrTS 顶且能量未达 EndCriteria / 引擎告警 / 终止信息
   缺失 ⇒ FAIL，数据不采信，其余门只记录）。
G1 峰位 = S21 全局峰邻域连续 −3dB 带中心（#298，不用 argmax）相对设计 f0=2.5GHz 的偏差
   vs 过孔电感裁判预测下移（写死 −5.58/−6.64/−5.06%）：|实测−预测| ≤1.5pt PASS / ≤3pt
   PARTIAL / 否则 FAIL。同频轴复算裁判（c3_circuit_sparams l_via_h=None vs 0.0）交叉核。
G2 通带峰 ≥ −3dB 且 −3dB 带内 max|S11| ≤ −10dB：两过 PASS / 一过 PARTIAL / 全失 FAIL。
G3 引擎 ZL（engine_msl_line_z0，f0±2% 中位）vs 50Ω 只记录（#280）。
G4 互易 N/A（单激励）——替代记录无源性 power_sum_max ≤1.02。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent if HERE.name == "scripts" else HERE.parents[1]
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rfauto.adapters.openems_rotation import engine_msl_line_z0  # noqa: E402
from rfauto.adapters.openems_templates import (  # noqa: E402
    TEMPLATE_NOMINAL,
    c3_circuit_sparams,
    c3_via_inductance_h,
)
from rfauto.core.synthesis import Stackup, forward_z0  # noqa: E402
from smoke_c3_filter_family import FEED_WIDTH_KEY, nrts_convergence  # noqa: E402

F0 = 2.5
FBW = 0.05
ORDER = 3
PRED_SHIFT_PCT = {"interdigital": -5.58, "combline": -6.64, "sir_bpf": -5.06}
G1_PASS_PT = 1.5
G1_PARTIAL_PT = 3.0
G2_PEAK_MIN_DB = -3.0
G2_RL_MAX_DB = -10.0
G3_BAND = 0.02
POWER_SUM_MAX = 1.02


def band_center_3db(f: np.ndarray, s_db: np.ndarray) -> dict:
    """全局峰邻域连续 −3dB 带（含峰的最大连通段）→ 中心/边沿/带宽；另记包络口径。"""
    i = int(np.argmax(s_db))
    pk = float(s_db[i])
    m = s_db >= pk - 3.0
    lo = i
    while lo > 0 and m[lo - 1]:
        lo -= 1
    hi = i
    while hi < f.size - 1 and m[hi + 1]:
        hi += 1
    fc = 0.5 * (float(f[lo]) + float(f[hi]))
    idx = np.where(m)[0]
    env_lo, env_hi = float(f[idx[0]]), float(f[idx[-1]])
    return {"peak_db": pk, "f_peak_argmax_ghz": float(f[i]),
            "f_lo_ghz": float(f[lo]), "f_hi_ghz": float(f[hi]),
            "f_center_3db_ghz": fc, "bw_3db_pct": (float(f[hi]) - float(f[lo])) / fc * 100.0,
            "touches_sweep_edge": bool(lo == 0 or hi == f.size - 1),
            "envelope_lo_ghz": env_lo, "envelope_hi_ghz": env_hi,
            "envelope_center_ghz": 0.5 * (env_lo + env_hi),
            "n_points_in_band": int(hi - lo + 1)}


def judge(template: str, work: Path | None = None) -> dict:
    work = HERE / template if work is None else Path(work)
    res = json.loads((work / "_smoke_result.json").read_text(encoding="utf-8"))
    # 数据源：完整 sparams.csv；预算点 kill 后走 extract_partial.py 的 sparams_partial.csv
    partial_meta: dict = {}
    if (work / "sparams.csv").exists():
        csv_path, data_source, fdtd_dir = work / "sparams.csv", "complete", work / "fdtd"
    else:
        csv_path, data_source = work / "sparams_partial.csv", "partial_budget_kill"
        fdtd_dir = work / "fdtd_partial"
        pm = work / "partial_meta.json"
        if pm.exists():
            partial_meta = json.loads(pm.read_text(encoding="utf-8"))
    d = np.loadtxt(csv_path, delimiter=",", skiprows=1)
    f = d[:, 0] / 1e9
    s11 = d[:, 1] + 1j * d[:, 2]
    s21 = d[:, 3] + 1j * d[:, 4]
    s11_db = 20 * np.log10(np.abs(s11) + 1e-12)
    s21_db = 20 * np.log10(np.abs(s21) + 1e-12)
    metrics = res.get("metrics") or {}
    gates = res.get("gates") or {}
    beta_feed_pct = metrics.get("beta_feed_pct")
    if beta_feed_pct is None and (work / "port_beta_partial.csv").exists():
        # 预算 kill 路径：与脚本同式（f0±4% 中位 β → εeff vs HJ 馈线 εeff）
        bd = np.loadtxt(work / "port_beta_partial.csv", delimiter=",", skiprows=1)
        selb = (bd[:, 0] >= 0.96 * F0 * 1e9) & (bd[:, 0] <= 1.04 * F0 * 1e9)
        eps_feed = (float(np.median(bd[selb, 1])) * 299792458.0 / (2 * np.pi * F0 * 1e9)) ** 2
        stk = Stackup.from_materials_yaml("rogers4350b_h0.508")
        w_feed = float(TEMPLATE_NOMINAL[template][FEED_WIDTH_KEY[template]])
        _, eps_hj = forward_z0(w_feed, F0, stk)
        beta_feed_pct = (eps_feed / eps_hj - 1.0) * 100.0

    # G0（旧轮结果无 convergence 键时按同一纯函数从 engine 段复算——干跑对照用；
    # 预算 kill 路径无终止信息 ⇒ 规则④"终止信息缺失不采信"FAIL）
    conv = res.get("convergence") or nrts_convergence(res["engine"])
    g0 = {"ok": bool(conv["converged"]), "reason": conv["reason"],
          "min_energy_db": conv["min_energy_db"], "end_criteria_db": conv["end_criteria_db"],
          "iterations_done": conv["iterations_done"], "nrts": conv["nrts"],
          "hit_nrts_limit": conv["hit_nrts_limit"]}

    # G1
    em = band_center_3db(f, s21_db)
    shift_meas = (em["f_center_3db_ghz"] / F0 - 1.0) * 100.0
    pred = PRED_SHIFT_PCT[template]
    dev = abs(shift_meas - pred)
    g1_status = "PASS" if dev <= G1_PASS_PT else ("PARTIAL" if dev <= G1_PARTIAL_PT else "FAIL")
    # 同频轴复算裁判（−3dB 带心口径）交叉核
    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    h_mm = float(stackup.thickness_mm)
    params = dict(TEMPLATE_NOMINAL[template])
    params["order"] = ORDER
    l_via = c3_via_inductance_h(h_mm)
    c_via = c3_circuit_sparams(template, f, params, synchronous_tem=False, h_mm=h_mm,
                               l_via_h=l_via)
    c_ideal = c3_circuit_sparams(template, f, params, synchronous_tem=False, h_mm=h_mm,
                                 l_via_h=0.0)
    bc_via = band_center_3db(f, 20 * np.log10(np.abs(c_via[:, 1, 0]) + 1e-12))
    bc_ideal = band_center_3db(f, 20 * np.log10(np.abs(c_ideal[:, 1, 0]) + 1e-12))
    pred_on_grid = (bc_via["f_center_3db_ghz"] / bc_ideal["f_center_3db_ghz"] - 1.0) * 100.0
    g1 = {"status": g1_status, "shift_measured_pct": shift_meas, "shift_predicted_pct": pred,
          "abs_dev_pt": dev, "thresholds_pt": [G1_PASS_PT, G1_PARTIAL_PT],
          "em_band": em,
          "shift_vs_ideal_circuit_center_pct": (
              em["f_center_3db_ghz"] / bc_ideal["f_center_3db_ghz"] - 1.0) * 100.0,
          "em_vs_via_circuit_center_pct": (
              em["f_center_3db_ghz"] / bc_via["f_center_3db_ghz"] - 1.0) * 100.0,
          "circuit_via_center_ghz": bc_via["f_center_3db_ghz"],
          "circuit_ideal_center_ghz": bc_ideal["f_center_3db_ghz"],
          "circuit_via_bw_pct": bc_via["bw_3db_pct"],
          "pred_shift_on_grid_pct": pred_on_grid,
          "pred_on_grid_vs_fixed_pt": pred_on_grid - pred,
          "via_inductance_nh": l_via * 1e9,
          "script_argmax_f_peak_ghz": metrics.get("f_peak_ghz"),
          "script_via_predicted_shift_pct": metrics.get("via_predicted_shift_pct")}

    # G2
    band = (f >= em["f_lo_ghz"]) & (f <= em["f_hi_ghz"])
    dband = (f >= F0 * (1 - FBW / 2)) & (f <= F0 * (1 + FBW / 2))
    peak = float(s21_db.max())
    rl_in = float(s11_db[band].max())
    ok_peak = peak >= G2_PEAK_MIN_DB
    ok_rl = rl_in <= G2_RL_MAX_DB
    g2_status = "PASS" if (ok_peak and ok_rl) else ("PARTIAL" if (ok_peak or ok_rl) else "FAIL")
    g2 = {"status": g2_status, "peak_s21_db": peak, "peak_ok": ok_peak,
          "rl_in_3db_band_max_db": rl_in, "rl_ok": ok_rl,
          "thresholds": {"peak_min_db": G2_PEAK_MIN_DB, "rl_max_db": G2_RL_MAX_DB},
          "design_band_s21_max_db": float(s21_db[dband].max()),
          "design_band_s21_min_db": float(s21_db[dband].min()),
          "design_band_s11_max_db": float(s11_db[dband].max()),
          "bw_3db_pct": em["bw_3db_pct"], "design_fbw_pct": FBW * 100,
          "bw_ratio_vs_design": em["bw_3db_pct"] / (FBW * 100),
          "s21_at_center_db": float(s21_db[int(np.argmin(np.abs(f - em["f_center_3db_ghz"])))]),
          "s11_min_db": float(s11_db.min()),
          "f_s11_min_ghz": float(f[int(np.argmin(s11_db))])}

    # G3
    g3 = {"note": "只记录不进门（#280）", "z0_ref_used_in_calcport": 50.0}
    fsel = (f >= F0 * (1 - G3_BAND)) & (f <= F0 * (1 + G3_BAND))
    for p in (1, 2):
        try:
            zl = engine_msl_line_z0(fdtd_dir, p, f * 1e9)
        except Exception as exc:  # 观测性 best-effort（#105），不阻塞判读
            zl = None
            g3[f"port{p}_error"] = repr(exc)
        if zl is None:
            g3[f"port{p}_zl_ohm"] = None
        else:
            zr = float(np.median(np.real(np.asarray(zl)[fsel])))
            g3[f"port{p}_zl_ohm"] = zr
            g3[f"port{p}_dev_pct"] = (zr / 50.0 - 1.0) * 100.0

    # G4
    power = np.abs(s11) ** 2 + np.abs(s21) ** 2
    g4 = {"status": "N/A", "note": "单激励（port1 excite=1）仅 S11/S21，x 镜像对称 ⇒ "
                                  "S12=S21/S22=S11 由构造保证；数值互易需第二激励整跑",
          "passivity_power_sum_max": float(power.max()),
          "passivity_ok": bool(power.max() <= POWER_SUM_MAX),
          "s11_max_db": float(s11_db.max()), "s21_max_db": float(s21_db.max())}

    if not g0["ok"]:
        verdict = "FAIL_NOT_CONVERGED"
    elif g1_status == "PASS" and g2_status == "PASS":
        verdict = "PASS"
    elif g1_status == "FAIL" or g2_status == "FAIL":
        verdict = "FAIL"
    else:
        verdict = "PARTIAL"
    return {"template": template, "verdict": verdict, "criteria": "runs/smoke_c3_refix/criteria.md",
            "data_source": data_source, "partial_meta": partial_meta,
            "run": {"mesh_mm": res.get("mesh_mm"), "mesh_max_mm": res.get("mesh_max_mm"),
                    "nrts": res.get("nrts"), "solve_s": res.get("solve_s"), "rc": res.get("rc"),
                    "n_freq": int(f.size), "freq_range_ghz": res.get("freq_range_ghz"),
                    "engine": res["engine"], "script_verdict": res.get("verdict"),
                    "script_reason": res.get("reason"),
                    "script_gates": {k: (v["value"], v["ok"]) for k, v in gates.items()},
                    "beta_feed_pct": beta_feed_pct},
            "G0_converged": g0, "G1_peak_shift": g1, "G2_il_rl": g2,
            "G3_engine_zl": g3, "G4_reciprocity": g4}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("template")
    ap.add_argument("--work", default=None,
                    help="干跑对照：指向旧轮目录（如 runs/smoke_c3/interdigital），"
                         "输出落 dryrun_old_<template>_judge.json 不污染旧轮")
    args = ap.parse_args(argv)
    if args.work:
        out = judge(args.template, Path(args.work))
        out["dryrun_work"] = args.work
        dest = HERE / f"dryrun_old_{args.template}_judge.json"
    else:
        out = judge(args.template)
        dest = HERE / args.template / "judge_refix.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                    encoding="utf-8")
    g1, g2 = out["G1_peak_shift"], out["G2_il_rl"]
    print(f"[{args.template}] verdict={out['verdict']} G0={out['G0_converged']['ok']} "
          f"({out['G0_converged']['min_energy_db']}dB) | G1 {g1['status']}: 带心 "
          f"{g1['em_band']['f_center_3db_ghz']:.4f}GHz shift {g1['shift_measured_pct']:+.2f}% "
          f"vs pred {g1['shift_predicted_pct']:+.2f}% (dev {g1['abs_dev_pt']:.2f}pt; on-grid pred "
          f"{g1['pred_shift_on_grid_pct']:+.2f}%) | G2 {g2['status']}: peak {g2['peak_s21_db']:.2f}dB "
          f"RL {g2['rl_in_3db_band_max_db']:.1f}dB bw {g2['bw_3db_pct']:.2f}% | G3 ZL "
          f"{out['G3_engine_zl'].get('port1_zl_ohm')} | passivity {g4_str(out)}")
    return 0


def g4_str(out: dict) -> str:
    g4 = out["G4_reciprocity"]
    return f"{g4['passivity_power_sum_max']:.4f} ({'ok' if g4['passivity_ok'] else 'VIOLATED'})"


if __name__ == "__main__":
    sys.exit(main())
