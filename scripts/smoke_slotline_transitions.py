"""W4⑧c openEMS 真机冒烟：MSL↔slotline 过渡 + Marchand 双槽臂巴伦。

流程（#157 长任务分离 + #242 stdout 落文件；路线 B 同款纪律）：
  1) 真机门：openEMS.exe 在跑则 60s 轮询等待（上限 --busy-timeout-s）；
  2) 三档单激励渲染（#208 进程隔离）：trans（P1 微带激励）、balun_ep1（P1）、
     balun_ep2（P2 抽头作源，S23 隔离）；已有 summary.json 且脚本文本逐字节
     一致则复用（#158 缓存口径；--no-cache 强制重跑）；
  3) 后处理：core/slotline_transitions 判据（transition_metrics/balun_metrics，
     门=预声明）+ 双行波 β vs 闭式 + 微带 β vs HJ 锚；抽头原始读数与
     基线修正值并列如实记录（#250 口径，不凑绿）；
  4) 结果落 runs/slotline_transitions/openems_result.json，progress.log 全程。

判据（预声明）：过渡段带内 max|S11|≤−10dB、S21 超额损耗≤1dB@f0（对
抽头基线）；巴伦幅度不平衡≤1dB、P1 回损≤−10dB、隔离 |S23|≤−15dB、带内
|S21|≥−3.5dB（均为抽头修正口径）；β 信息门 vs 闭式 ≤5%。
用法：.venv/Scripts/python.exe scripts/smoke_slotline_transitions.py [--mesh-mm 0]
      [--nrts N] [--poll-timeout-s 14400] [--busy-timeout-s 7200] [--no-cache]
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

from rfauto.adapters.em_solver_base import resolve_openems_exe
from rfauto.adapters.slotline_transitions_template import (
    balun_ideal_baselines_db,
    marchand_balun_layout,
    msl_slot_transition_layout,
    render_marchand_balun,
    render_msl_slot_transition,
)
from rfauto.core.slotline import slotline_closed_form
from rfauto.core.slotline_transitions import (
    balun_metrics,
    transition_metrics,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "slotline_transitions"
PROGRESS = OUT / "progress.log"

F0_GHZ = 2.5
BAND = (2.25, 2.75)
ER, H_MM, W_MM, TAND = 3.66, 1.524, 1.0, 0.0037


def _progress(msg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def wait_engine_free(busy_timeout_s: float) -> None:
    """他轨优先：openEMS.exe 在跑则 60s 轮询等待。"""
    t0 = time.time()
    while True:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq openEMS.exe"],
                           capture_output=True, text=True)
        if "openEMS.exe" not in (r.stdout or ""):
            return
        if time.time() - t0 > busy_timeout_s:
            raise SystemExit(f"openEMS.exe 占用超 {busy_timeout_s:.0f}s，退出（他轨优先）")
        print(f"[wait] openEMS.exe 在跑，60s 后重查（已等 {time.time() - t0:.0f}s）",
              flush=True)
        time.sleep(60)


def run_variant(tag: str, script: str, args: argparse.Namespace) -> dict:
    """渲染 + FDTD 子进程（日志落文件）→ 缓存复用或真跑。"""
    work = OUT / tag
    work.mkdir(parents=True, exist_ok=True)
    script_path = work / "simulation.py"
    summary_path = work / "summary.json"
    reuse = (summary_path.exists() and not args.no_cache and script_path.exists()
             and script_path.read_text(encoding="utf-8") == script)
    if reuse:
        print(f"[{tag}] 复用已有 summary（脚本逐字节一致）", flush=True)
        return {"work": str(work), "solve_s": None}
    script_path.write_text(script, encoding="utf-8")
    exe = resolve_openems_exe()
    assert Path(exe).exists(), f"openEMS.exe 不存在: {exe}"
    exe_dir = str(Path(exe).resolve().parent)
    runner = work / "_rfauto_runner.py"
    runner.write_text(
        "import os\nimport runpy\nimport sys\n"
        f"os.add_dll_directory({exe_dir!r})\n"
        f"os.environ['PATH'] = {exe_dir!r} + os.pathsep + os.environ.get('PATH', '')\n"
        "runpy.run_path(sys.argv[1], run_name='__main__')\n", encoding="utf-8")
    log_path = work / "fdtd_run.log"
    if summary_path.exists():
        summary_path.unlink()
    t0 = time.time()
    with open(log_path, "ab") as logf:
        proc = subprocess.run([sys.executable, str(runner), str(script_path)],
                              cwd=str(work), stdout=logf,
                              stderr=subprocess.STDOUT,
                              timeout=args.poll_timeout_s)
    if proc.returncode != 0 or not summary_path.exists():
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
        raise SystemExit(f"[{tag}] FDTD rc={proc.returncode} 无 summary；日志尾:\n{tail}")
    solve_s = round(time.time() - t0, 1)
    _progress(f"stage3 {tag}: FDTD done solve={solve_s}s")
    print(f"[{tag}] solve={solve_s}s", flush=True)
    return {"work": str(work), "solve_s": solve_s}


def _read_csv(path: Path) -> dict[str, np.ndarray]:
    with open(path, encoding="utf-8") as fh:
        header = fh.readline().strip().split(",")
    raw = np.genfromtxt(str(path), delimiter=",", skip_header=1,
                        filling_values=np.nan, ndmin=2)
    return {name: raw[:, k] for k, name in enumerate(header)}


def analyze_trans(args: argparse.Namespace) -> dict:
    """过渡段后处理：判据 + β 对拍（core 纯函数，可离线复算）。"""
    work = OUT / "trans"
    sp = _read_csv(work / "sparams.csv")
    bt = _read_csv(work / "slotline_beta.csv")
    summary = json.loads((work / "summary.json").read_text(encoding="utf-8"))
    f = sp["freq_hz"]
    s11 = sp["re_S11"] + 1j * sp["im_S11"]
    s21 = sp["re_S21"] + 1j * sp["im_S21"]
    i0 = int(np.argmin(np.abs(f - F0_GHZ * 1e9)))
    cf = slotline_closed_form(W_MM, H_MM, ER, F0_GHZ)
    m = transition_metrics(
        f, s11, s21, BAND,
        s21_ideal_db_f0=summary["rx_baseline_db"],
        beta_probe_f0=float(bt["beta_slot_rad_m"][i0]),
        beta_closed_f0=cf.beta_rad_m)
    m.update({
        "beta_msl_f0_rad_m": float(bt["beta_msl_rad_m"][i0]),
        "beta_msl_hj_f0_rad_m": summary["beta_msl_hj_f0"],
        "beta_msl_vs_hj_pct": (float(bt["beta_msl_rad_m"][i0])
                               / summary["beta_msl_hj_f0"] - 1) * 100,
        "gamma_load_mag_f0": float(bt["gamma_load_mag"][i0]),
        "s21_convention": summary["s21_convention"],
        "mesh_lines": summary["mesh_lines"],
    })
    return m


def analyze_balun(ep: int, args: argparse.Namespace) -> dict:
    """巴伦后处理：抽头基线修正后的 S 门 + 双臂 β + 相位差（极性约定注明）。"""
    tag = f"balun_ep{ep}"
    work = OUT / tag
    sp = _read_csv(work / "sparams.csv")
    bt = _read_csv(work / "slotline_beta.csv")
    summary = json.loads((work / "summary.json").read_text(encoding="utf-8"))
    f = sp["freq_hz"]
    base = balun_ideal_baselines_db(summary["r_slot_ohm"], summary["r_slot_ohm"])
    i0 = int(np.argmin(np.abs(f - F0_GHZ * 1e9)))
    out: dict = {"excite_port": ep, "baselines_db": base,
                 "work": str(work), "solve_s": summary.get("nrts")}
    cf = slotline_closed_form(W_MM, H_MM, ER, F0_GHZ)

    def _cx(re: str, im: str) -> np.ndarray:
        return sp[re] + 1j * sp[im]

    if ep == 1:
        corr = 10.0 ** (-base["s21_s31_baseline_db"] / 20.0)  # 1/|1+Γ|≈1.5
        s11 = _cx("re_S11", "im_S11")
        s21 = _cx("re_S21", "im_S21") * corr
        s31 = _cx("re_S31", "im_S31") * corr
        m = balun_metrics(f, s11, s21, s31, s23=None, band_ghz=BAND)
        m["s21_raw_db_f0"] = float(20 * np.log10(abs(_cx("re_S21", "im_S21")[i0])
                                                 + 1e-300))
        m["s31_raw_db_f0"] = float(20 * np.log10(abs(_cx("re_S31", "im_S31")[i0])
                                                 + 1e-300))
        m["note_polarity"] = ("两口 start/stop 均 y 递增（槽1 跨[中条→外地]、槽2 跨"
                              "[外地→中条]）：phase_diff≈0° ⇒ 推挽平衡；≈180° ⇒ 同相分配")
        out["metrics"] = m
    else:
        s23_raw = _cx("re_S23", "im_S23")
        corr = 10.0 ** (-base["s23_baseline_db"] / 20.0)
        s23_corr = s23_raw * corr
        out["isolation"] = {
            "s23_raw_db_f0": float(20 * np.log10(abs(s23_raw[i0]) + 1e-300)),
            "s23_corr_db_f0": float(20 * np.log10(abs(s23_corr[i0]) + 1e-300)),
            "band_max_s23_corr_db": float(np.max(
                20 * np.log10(np.abs(s23_corr) + 1e-300)[
                    (f >= BAND[0] * 1e9) & (f <= BAND[1] * 1e9)])),
            "gate_isolation_le_minus15db": bool(np.max(
                20 * np.log10(np.abs(s23_corr) + 1e-300)[
                    (f >= BAND[0] * 1e9) & (f <= BAND[1] * 1e9)]) <= -15.0),
            "convention": "抽头源+抽头收双基线修正（SRC+RX=−7.04dB）",
        }
        # 互易信息项：S12/S13（抽头源→MSL 收，单基线 SRC 修正）
        if ep == 2:
            s12 = _cx("re_S12", "im_S12") * 10.0 ** (
                -base["s12_s13_baseline_db"] / 20.0)
            out["reciprocity_s12_db_f0"] = float(
                20 * np.log10(abs(s12[i0]) + 1e-300))
    out["beta"] = {
        "beta_a_f0": float(bt["beta_a_rad_m"][i0]),
        "beta_b_f0": float(bt["beta_b_rad_m"][i0]),
        "beta_cf_f0": cf.beta_rad_m,
        "beta_a_vs_cf_pct": (float(bt["beta_a_rad_m"][i0]) / cf.beta_rad_m - 1) * 100,
        "beta_b_vs_cf_pct": (float(bt["beta_b_rad_m"][i0]) / cf.beta_rad_m - 1) * 100,
        "beta_msl_f0": float(summary["beta_msl_f0"]),
        "beta_msl_vs_hj_pct": (float(summary["beta_msl_f0"])
                               / summary["beta_msl_hj_f0"] - 1) * 100,
        "gamma_load_a_f0": float(bt["gamma_a_mag"][i0]),
        "gamma_load_b_f0": float(bt["gamma_b_mag"][i0]),
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh-mm", type=float, default=0.0)
    ap.add_argument("--nrts", type=int, default=100000)
    ap.add_argument("--poll-timeout-s", type=float, default=4 * 3600)
    ap.add_argument("--busy-timeout-s", type=float, default=2 * 3600)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--analyze-only", action="store_true",
                    help="跳过求解只重跑后处理（复用既有 summary/csv）")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    params = {"w_slot_mm": W_MM, "h_mm": H_MM, "er": ER, "tan_d": TAND,
              "mesh": args.mesh_mm}
    lay_t = msl_slot_transition_layout(params, BAND, args.mesh_mm)
    lay_b = marchand_balun_layout(params, BAND, args.mesh_mm)
    variants = [
        ("trans", render_msl_slot_transition(params, BAND, args.mesh_mm,
                                             nrts=args.nrts)),
        ("balun_ep1", render_marchand_balun(params, BAND, args.mesh_mm,
                                            nrts=args.nrts, excite_port=1)),
        ("balun_ep2", render_marchand_balun(params, BAND, args.mesh_mm,
                                            nrts=args.nrts, excite_port=2)),
    ]
    _progress(f"stage3 start: 3 variants mesh_mm={args.mesh_mm} nrts={args.nrts} "
              f"no_cache={args.no_cache} dom_x={lay_t.dom_x_m * 1e3:.1f}mm")
    if not args.analyze_only:
        wait_engine_free(args.busy_timeout_s)
        for tag, script in variants:
            _progress(f"stage3 {tag}: launch")
            run_variant(tag, script, args)

    runs = {"trans": analyze_trans(args), "balun_ep1": analyze_balun(1, args),
            "balun_ep2": analyze_balun(2, args)}
    gates = {}
    gates.update({f"trans_{k}": v for k, v in runs["trans"]["gates"].items()})
    gates["trans_beta_info_le_5pct"] = abs(runs["trans"]["beta_vs_closed_pct"]) <= 5.0
    gates.update({f"balun_{k}": v
                  for k, v in runs["balun_ep1"]["metrics"]["gates"].items()})
    gates["balun_isolation_le_minus15db"] = runs["balun_ep2"]["isolation"][
        "gate_isolation_le_minus15db"]
    for k in ("beta_a_vs_cf_pct", "beta_b_vs_cf_pct"):
        gates[f"balun_{k}_info_le_5pct"] = abs(
            runs["balun_ep1"]["beta"][k]) <= 5.0
    result = {
        "design": {"f0_ghz": F0_GHZ, "band_ghz": list(BAND),
                   "w_slot_mm": W_MM, "h_mm": H_MM, "er": ER, "tan_d": TAND,
                   "x_sh_mm": lay_t.l_short_m * 1e3, "l_stub_mm": lay_t.l_stub_m * 1e3,
                   "w_msl_mm": lay_t.w_msl_m * 1e3, "d_center_mm": lay_b.d_center_m * 1e3,
                   "dom_x_mm": lay_t.dom_x_m * 1e3, "dom_y_mm": lay_t.dom_y_m * 1e3,
                   "r_slot_ohm": lay_t.r_slot_ohm,
                   "beta_slot_f0": lay_t.beta_slot_f0,
                   "beta_msl_hj_f0": lay_t.beta_msl_f0},
        "runs": runs, "gates": gates,
        "conventions": [
            "P1 微带 MSLPort 线基；P2/P3 LumpedPort 跨槽=并联抽头拓扑（#250），"
            "门按基线修正口径，原始值并列",
            "巴伦相位约定：两口 y 递增极性下 phase_diff≈0°=推挽平衡",
            "S23 由 balun_ep2 单激励（#208 进程隔离）装配",
        ],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out_json = OUT / "openems_result.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"[out] {out_json}", flush=True)
    print(f"[gates] {gates}", flush=True)
    _progress(f"stage3 done: gates={gates}")
    hard = [v for k, v in gates.items() if "info" not in k]
    return 0 if all(hard) else 1


if __name__ == "__main__":
    raise SystemExit(main())
