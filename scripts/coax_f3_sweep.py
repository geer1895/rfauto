"""coax_waveguide_transition F3 pin_len 五点扫掠驱动（T18 实现席）。

预声明：runs/coax_f3_sweep/launch_ready.md（判据先行，跑后不改 #122）。
审计锚：docs/audit/oe3_coax_fail_audit_20260929.md §5 F3 +
runs/oe_phase3/coax_waveguide_transition/verdict_offline_fix.json
（修后格局：s21 门 −0.883dB PASS；S11 三门 −7.85/−8.80/−7.77 vs
−10/−10/−8 边缘 FAIL=调参级）。模板 S21 公式已修（T2 commit b24a0c2，
uf_inc 透射通道）——本驱动渲染的 sparams.csv 直接可判读。

扫掠点（加长=感性方向，调容性 −j46Ω→0；launch_ready §2）：
  p1=名义 5.588（0.55·b 基线复现锚）/ p2=6.1 / p3=6.6 / p4=7.1 / p5=7.6 mm
判据（三期 criteria.json 同源未动）：s11_f0 ≤−10、band_min ≤−10、
core_max ≤−8、s21_f0 ≥−1.5、passive ≤1.05、finite、must_converge。
停机规则（预声明）：五点全扫后取最优（最优=三门 S11 最差裕量最大者，
须 finite+passive+收敛+s21 门 PASS 才有资格）。

子命令：
  dryrender  五点渲染+几何段 exec 零仿真审计 → dryrender.json
  oe         五点串行真机（solo 单飞 #246/#261）→ p1..p5/oe_result.json
  judge      跑后判读（零求解）→ sweep_verdict.json + sweep_verdict.md

第二轮收针（T24 预备席；预声明 runs/coax_f3_sweep_round2/launch_ready.md，
判据/选择/停机规则以该档为准，r2 段只做机制实现；T18 三子命令零行为钉）：
  r2dryrender  Stage A 渲染审计+机制彩排+T18 p2 哈希钉 → dryrender.json
  r2oe         两旋钮正交化串行真机（A→b*→B→条件细化）→ sweep_verdict.*
  r2judge      零求解幂等复判 → sweep_verdict.json + sweep_verdict.md

用法（发射形态 #157/#245：python -u 后台分离 + 日志轮询）：
  .venv/Scripts/python.exe -u scripts/coax_f3_sweep.py dryrender
  .venv/Scripts/python.exe -u scripts/coax_f3_sweep.py oe --timeout 900
  .venv/Scripts/python.exe -u scripts/coax_f3_sweep.py judge
  .venv/Scripts/python.exe -u scripts/coax_f3_sweep.py r2dryrender
  .venv/Scripts/python.exe -u scripts/coax_f3_sweep.py r2oe --timeout 900
  .venv/Scripts/python.exe -u scripts/coax_f3_sweep.py r2judge
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from itertools import pairwise
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

# openEMS DLL 面（几何段 exec / CalcPort 进程内消费；_verdict_offline_fix 同法）
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN",
                         "D:/rf_workspace/vendor/openEMS/install/bin")
if os.path.isdir(_OE_BIN):
    with contextlib.suppress(OSError):
        os.add_dll_directory(_OE_BIN)
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")

T = "coax_waveguide_transition"
BAND = (8.0, 12.0)
MESH_MM = 1.0                        # 三期 coax 席位同档（criteria.json）
WINDOW_NS = 6.0                      # 三期冒烟档同窗（launch_ready §3）
PINS: tuple[float | None, ...] = (None, 6.1, 6.6, 7.1, 7.6)  # None=名义基线
GATES = {
    "f0_ghz": 10.0,
    "band_ghz": (8.0, 12.0),
    "band_min_max_db": -10.0,
    "s11_f0_max_db": -10.0,
    "s21_f0_min_db": -1.5,
    "core_ghz": (9.0, 11.0),
    "core_max_db": -8.0,
    "passive_max": 1.05,
}
# p1 基线旁证锚（verdict_offline_fix.json scalars；非门，偏差大即停查）
BASELINE_ANCHOR_DB = {
    "s11_f0_db": -7.851238306739663,
    "band_min_db": -8.796394093647509,
    "core_max_db": -7.765904412892026,
    "s21_f0_db": -0.8826662536759131,
}
GRID_MIN_SPACING_M = 10e-6           # #349 起跑守卫
OUT_DEFAULT = Path("runs") / "coax_f3_sweep"
DEFAULT_TIMEOUT_S = 900.0
_SOLVE_MARK = "# ── 求解 ──"


def nominal_params() -> dict:
    from rfauto.adapters.openems_templates import COAX_WG_NOMINAL

    return dict(COAX_WG_NOMINAL)


def point_params(pin: float | None) -> dict:
    p = nominal_params()
    if pin is not None:
        p["pin_len_mm"] = float(pin)
    return p


def point_dir(out_root: Path, k: int) -> Path:
    return out_root / f"p{k}"


def _db(x) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(np.abs(np.asarray(x)), 1e-300))


def _read_sparams5(path: Path):
    """本模板单激励 5 列 sparams.csv → (freqs_hz, s11, s21)；列头行跳过。"""
    rows: list[list[float]] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith(("%", "#")):
                continue
            parts = s.split(",")
            if len(parts) < 5:
                continue
            with contextlib.suppress(ValueError):
                rows.append([float(x) for x in parts[:5]])
    if not rows:
        return None
    arr = np.asarray(rows, dtype=float)
    return arr[:, 0], arr[:, 1] + 1j * arr[:, 2], arr[:, 3] + 1j * arr[:, 4]


# ── dryrender：五点渲染+几何段 exec 零仿真审计（秒级）───────────────────────

def _plan_nrts(text: str) -> dict:
    """exec 渲染几何段（截求解标记）→ 网格/dt/NrTS 计划（oe_phase3 preflight 同法）。"""
    from rfauto.adapters.openems_templates import cfl_dt_s, nrts_from_max_time_ns

    cut = text.find(_SOLVE_MARK)
    cut = cut if cut >= 0 else text.index("FDTD.Run(")
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_coax_f3_dryrender_sim.py")}
    exec(compile(text[:cut], "coax_f3_dryrender", "exec"), scope)
    lines: dict[str, int] = {}
    dmin: dict[str, float] = {}
    for ax in ("x", "y", "z"):
        ls = np.asarray(scope["mesh"].GetLines(ax), dtype=float)
        lines[ax] = int(ls.size)
        dmin[ax] = float(np.min(np.diff(ls)))
    dt = float(cfl_dt_s(dmin["x"], dmin["y"], dmin["z"]))
    nrts = int(nrts_from_max_time_ns(WINDOW_NS, dt))
    cells = lines["x"] * lines["y"] * lines["z"]
    f0_hz = float(scope["F0"])
    with contextlib.suppress(KeyError):
        del scope["CSX"], scope["FDTD"], scope["mesh"]
        del scope["_port1"], scope["_port2"]
    return {"mesh_lines": lines, "cells": cells,
            "dmin_mm": {k: round(v * 1e3, 4) for k, v in dmin.items()},
            "dt_s": dt, "nrts_plan": nrts, "f0_hz": f0_hz,
            "grid_min_spacing_ok": bool(min(dmin.values()) >= GRID_MIN_SPACING_M)}


def cmd_dryrender(out_root: Path) -> int:
    from rfauto.adapters.openems_templates import render_script

    out: dict = {"template": T, "band_ghz": list(BAND), "mesh_mm": MESH_MM,
                 "window_ns": WINDOW_NS, "points": {}}
    ok = True
    hashes: dict[str, str] = {}
    for k, pin in enumerate(PINS, 1):
        row: dict = {"pin_sweep_mm": pin}
        try:
            params = point_params(pin)
            text = render_script(T, params, BAND, mesh_resolution_mm=MESH_MM)
            row["pin_literal_in_text"] = (
                f'pin_len_mm={params["pin_len_mm"]!r}' in text)
            row.update(_plan_nrts(text))
            # 与发射同参重渲染（_nrts 旋钮显式传，campaign preflight 同法）
            lit = render_script(T, dict(params, _nrts=row["nrts_plan"]), BAND,
                                mesh_resolution_mm=MESH_MM)
            m = re.search(r"NRTS\s*=\s*(\d+)", lit)
            row["nrts_literal"] = int(m.group(1)) if m else None
            row["nrts_literal_ok"] = row["nrts_literal"] == row["nrts_plan"]
            row["render_sha256"] = hashlib.sha256(lit.encode()).hexdigest()
            hashes[f"p{k}"] = row["render_sha256"]
            row["ok"] = bool(row["pin_literal_in_text"] and row["nrts_literal_ok"]
                             and row["grid_min_spacing_ok"]
                             and abs(row["f0_hz"] - GATES["f0_ghz"] * 1e9) < 1.0)
        except Exception as exc:   # 审计失败=发射面红，如实（#122）
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["ok"] = False
        ok = ok and bool(row.get("ok"))
        out["points"][f"p{k}"] = row
        print(f"[dryrender] p{k} pin={pin}: ok={row.get('ok')} "
              f"nrts={row.get('nrts_plan')} dt={row.get('dt_s')} "
              f"err={row.get('error')}", flush=True)
    out["hashes_distinct"] = len(set(hashes.values())) == len(hashes)
    out["ok"] = bool(ok and out["hashes_distinct"])
    (out_root / "dryrender.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[dryrender] verdict ok={out['ok']} "
          f"hashes_distinct={out['hashes_distinct']}", flush=True)
    return 0 if out["ok"] else 1


# ── oe：五点串行真机（solo 单飞）────────────────────────────────────────────

def _write_runner(run_dir: Path) -> Path:
    from rfauto.adapters.em_solver_base import resolve_openems_exe

    exe = resolve_openems_exe()
    runner = run_dir / "_rfauto_runner.py"
    exe_dir = (str(Path(exe).resolve().parent) if exe
               else "D:/rf_workspace/vendor/openEMS/install/bin")
    runner.write_text(
        "import os\nimport runpy\nimport sys\n"
        f"os.add_dll_directory({exe_dir!r})\n"
        "os.environ['PATH'] = " + repr(exe_dir)
        + " + os.pathsep + os.environ.get('PATH', '')\n"
        "runpy.run_path(sys.argv[1], run_name='__main__')\n",
        encoding="utf-8")
    return runner


def _gate_scalars(freqs: np.ndarray, s11, s21) -> dict:
    win = GATES
    i0 = int(np.argmin(np.abs(freqs - win["f0_ghz"] * 1e9)))
    band = ((freqs >= win["band_ghz"][0] * 1e9)
            & (freqs <= win["band_ghz"][1] * 1e9))
    core = ((freqs >= win["core_ghz"][0] * 1e9)
            & (freqs <= win["core_ghz"][1] * 1e9))
    s11_db, s21_db = _db(s11), _db(s21)
    zin = complex(50.0 * (1 + s11[i0]) / (1 - s11[i0]))
    i_band = int(np.argmin(s11_db[band]))
    band_min_f_ghz = (float(freqs[band][i_band] / 1e9)
                      if bool(band.any()) else None)
    return {
        "f0_ghz": float(freqs[i0] / 1e9),
        "s11_f0_db": float(s11_db[i0]),
        "band_min_db": float(s11_db[band].min()),
        "band_min_f_ghz": band_min_f_ghz,
        "core_max_db": float(s11_db[core].max()),
        "s21_f0_db": float(s21_db[i0]),
        "max_abs_s": float(max(np.abs(s11).max(), np.abs(s21).max())),
        "finite": bool(np.isfinite(s11).all() and np.isfinite(s21).all()),
        "z_in_f0_ohm": [float(zin.real), float(zin.imag)],
        "n_freqs": int(freqs.size),
    }


def _gate_checks(sc: dict, converged: bool | None, conv_reason: str) -> list:
    win = GATES
    return [
        {"name": "finite", "ok": bool(sc["finite"]),
         "detail": "ok" if sc["finite"] else "S 参数含非有限值"},
        {"name": "passive", "ok": sc["max_abs_s"] <= win["passive_max"],
         "detail": f"max|S|={sc['max_abs_s']:.4f}"
                   f"（门 ≤{win['passive_max']}）"},
        {"name": "converged", "ok": converged is True,
         "detail": conv_reason if converged is not True else "EndCriteria 停机"},
        {"name": "s11_f0",
         "ok": sc["s11_f0_db"] <= win["s11_f0_max_db"],
         "detail": (f"S11@{win['f0_ghz']}GHz={sc['s11_f0_db']:.2f}dB"
                    f"（门 ≤{win['s11_f0_max_db']}dB，首跑定标）")},
        {"name": "band_min",
         "ok": sc["band_min_db"] <= win["band_min_max_db"],
         "detail": (f"band-min S11={sc['band_min_db']:.2f}dB"
                    f"（门 ≤{win['band_min_max_db']}dB）")},
        {"name": "core_max",
         "ok": sc["core_max_db"] <= win["core_max_db"],
         "detail": (f"core max S11={sc['core_max_db']:.2f}dB"
                    f"（门 ≤{win['core_max_db']}dB）")},
        {"name": "s21_f0",
         "ok": sc["s21_f0_db"] >= win["s21_f0_min_db"],
         "detail": (f"S21@{win['f0_ghz']}GHz={sc['s21_f0_db']:.3f}dB"
                    f"（门 ≥{win['s21_f0_min_db']}dB）——uf_inc 透射通道")},
    ]


def cmd_oe(out_root: Path, only: list[int], timeout_s: float) -> int:
    from rfauto.adapters.openems_templates import render_script

    dry_path = out_root / "dryrender.json"
    dry = (json.loads(dry_path.read_text(encoding="utf-8"))
           if dry_path.is_file() else {"points": {}})
    rc = 0
    for k, pin in enumerate(PINS, 1):
        if only and k not in only:
            continue
        run_dir = point_dir(out_root, k)
        run_dir.mkdir(parents=True, exist_ok=True)
        pre = dry.get("points", {}).get(f"p{k}", {})
        nrts = pre.get("nrts_plan")
        params = point_params(pin)
        if nrts:
            params["_nrts"] = int(nrts)
        row: dict = {"point": f"p{k}", "pin_sweep_mm": pin,
                     "pin_len_mm": params["pin_len_mm"],
                     "nrts_plan": nrts,
                     "started": time.strftime("%F %T")}
        print(f"[oe] p{k} pin={pin} start", flush=True)
        t0 = time.time()
        try:
            text = render_script(T, params, BAND, mesh_resolution_mm=MESH_MM)
            (run_dir / "simulation.py").write_text(text, encoding="utf-8")
            row["render_sha256"] = hashlib.sha256(text.encode()).hexdigest()
            runner = _write_runner(run_dir)
            cmd = [sys.executable, str(runner.resolve()),
                   str((run_dir / "simulation.py").resolve())]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=float(timeout_s), cwd=str(run_dir.resolve()))
                rcode, so, se = (proc.returncode, proc.stdout or "",
                                 proc.stderr or "")
            except subprocess.TimeoutExpired:
                rcode, so, se = None, "", f"TimeoutExpired after {timeout_s}s"
            with contextlib.suppress(OSError):   # #105 best-effort 落盘
                (run_dir / "_last_stdout.log").write_text(so, encoding="utf-8")
                (run_dir / "_last_stderr.log").write_text(se, encoding="utf-8")
            row["rc"] = rcode
            row["wall_s"] = round(time.time() - t0, 1)
            row["solve_success"] = bool(rcode == 0
                                        and (run_dir / "sparams.csv").is_file())
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["solve_success"] = False
            row["wall_s"] = round(time.time() - t0, 1)
        # 收敛判读（#266 口径；must_converge）
        converged: bool | None = None
        conv_reason = "求解未完成（sparams.csv 缺或 rc!=0）"
        try:
            from fd_oe_campaign import nrts_convergence, parse_engine_log

            log = run_dir / "_last_stdout.log"
            if log.is_file():
                eng = parse_engine_log(
                    log.read_text(encoding="utf-8", errors="replace"))
                row["engine"] = eng
                conv = nrts_convergence(eng)
                converged = conv["converged"]
                conv_reason = conv["reason"]
        except Exception as exc:   # best-effort（#105）
            conv_reason = f"gate error: {exc}"
        row["converged"] = converged
        row["converged_reason"] = conv_reason
        # 判据门
        try:
            sp = _read_sparams5(run_dir / "sparams.csv")
            if sp is None:
                raise ValueError("sparams.csv 不可读/空")
            freqs, s11, s21 = sp
            sc = _gate_scalars(freqs, s11, s21)
            row["scalars"] = sc
            checks = _gate_checks(sc, converged, conv_reason)
            if not row.get("solve_success"):
                checks.append({"name": "solve", "ok": False,
                               "detail": f"rc={row.get('rc')}（引擎未正常结束）"})
            row["checks"] = checks
            row["status"] = "PASS" if all(c["ok"] for c in checks) else "FAIL"
            row["reasons"] = [c["detail"] for c in checks if not c["ok"]]
        except Exception as exc:
            row["status"] = "FAIL"
            row["reasons"] = [f"S 参数判读失败: {exc}"]
        if row["status"] != "PASS":
            rc = 1
        (run_dir / "oe_result.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        sc = row.get("scalars") or {}
        print(f"[oe] p{k} pin={pin}: {row['status']} wall={row['wall_s']}s "
              f"s11_f0={sc.get('s11_f0_db')} band_min={sc.get('band_min_db')} "
              f"core_max={sc.get('core_max_db')} s21_f0={sc.get('s21_f0_db')} "
              f"conv={converged}", flush=True)
    return rc


# ── judge：跑后判读（零求解）───────────────────────────────────────────────

def _margins(sc: dict) -> dict:
    """三门 S11 裕量（门限−实测，正=过）与最差裕量。"""
    win = GATES
    mg = {
        "s11_f0": win["s11_f0_max_db"] - sc["s11_f0_db"],
        "band_min": win["band_min_max_db"] - sc["band_min_db"],
        "core_max": win["core_max_db"] - sc["core_max_db"],
    }
    return {**mg, "worst": min(mg.values())}


def _eligible(row: dict) -> bool:
    """最优候选资格（预声明 §4）：finite+passive+收敛+s21 门 PASS。"""
    ch = {c["name"]: bool(c["ok"]) for c in row.get("checks", [])}
    return bool(ch.get("finite") and ch.get("passive") and ch.get("converged")
                and ch.get("s21_f0")) and row.get("scalars") is not None


def cmd_judge(out_root: Path) -> int:
    points: dict[str, dict] = {}
    for k, pin in enumerate(PINS, 1):
        p = point_dir(out_root, k) / "oe_result.json"
        row = (json.loads(p.read_text(encoding="utf-8"))
               if p.is_file()
               else {"status": "MISSING", "point": f"p{k}",
                     "pin_sweep_mm": pin, "pin_len_mm": pin,
                     "reasons": ["oe_result.json 缺"]})
        # scalars 由 sparams.csv 现算（judge 自足幂等；oe_result 里的
        # scalars 是跑时快照，字段演进后以现算为准）
        run_dir = point_dir(out_root, k)
        if (run_dir / "sparams.csv").is_file():
            with contextlib.suppress(Exception):
                freqs, s11, s21 = _read_sparams5(run_dir / "sparams.csv")
                row["scalars"] = _gate_scalars(freqs, s11, s21)
        row["pin_len_mm"] = row.get("pin_len_mm") or row.get("pin_sweep_mm")
        points[f"p{k}"] = row
    best_key, best_worst = None, -1e99
    for key, row in points.items():
        sc = row.get("scalars")
        if _eligible(row) and sc is not None:
            row["margins"] = _margins(sc)
            if row["margins"]["worst"] > best_worst:
                best_key, best_worst = key, row["margins"]["worst"]
    opt = points.get(best_key or "", {})
    opt_sc = opt.get("scalars") or {}
    opt_mg = opt.get("margins") or {}
    in_window = bool(opt_mg) and all(opt_mg[k] >= 0
                                     for k in ("s11_f0", "band_min",
                                               "core_max"))
    # 物理读数（Z_in 轨迹，事实性；主代理决策输入）
    zs = [(r.get("pin_sweep_mm"), (r.get("scalars") or {}).get("z_in_f0_ohm"))
          for r in points.values()]
    zs = [(p, z) for p, z in zs if z is not None]
    physics_read = None
    if len(zs) >= 2:
        im = [(abs(z[1]), p) for p, z in zs]
        re_min = min(z[0] for _, z in zs)
        re_max = max(z[0] for _, z in zs)
        physics_read = {
            "z_in_re_range_ohm": [round(re_min, 1), round(re_max, 1)],
            "z_in_im_range_ohm": [round(min(z[1] for _, z in zs), 1),
                                  round(max(z[1] for _, z in zs), 1)],
            "im_min_pin_mm": min(im)[1],
            "finding": (
                "加长 pin 主要推高 Re(Z_in)（"
                f"{re_min:.0f}→{re_max:.0f}Ω），Im(Z_in) 在 "
                f"{min(z[1] for _, z in zs):.0f}~"
                f"{max(z[1] for _, z in zs):.0f}Ω 容性区近乎平坦"
                f"（最小 |Im| 在 pin={min(im)[1]}mm）——"
                "f0 残余失配以容抗为主且 pin_len 单旋钮在本区间不可消，"
                "s11_f0 门（≤−10dB）未被任何点命中"),
        }
    verdict = {
        "template": T,
        "mode": "f3_pin_len_sweep",
        "finished": time.strftime("%F %T"),
        "provenance": (
            "预声明 runs/coax_f3_sweep/launch_ready.md（判据先行）；"
            "审计锚 docs/audit/oe3_coax_fail_audit_20260929.md §5 F3；"
            "判据窗=三期 criteria.json 同源未动；S21=修后 uf_inc 通道"
            "（T2 commit b24a0c2）。停机规则=五点全扫后取最优。"),
        "criteria": GATES,
        "stop_rule": "full_scan_then_best",
        "points": {k: {
            "pin_len_mm": r.get("pin_len_mm"),
            "status": r.get("status"),
            "scalars": r.get("scalars"),
            "margins": r.get("margins"),
            "converged": r.get("converged"),
            "wall_s": r.get("wall_s"),
            "reasons": r.get("reasons"),
            "z_in_f0_ohm": (r.get("scalars") or {}).get("z_in_f0_ohm"),
        } for k, r in points.items()},
        "optimal": {
            "point": best_key,
            "pin_len_mm": opt.get("pin_len_mm"),
            "scalars": opt_sc if opt_mg else None,
            "worst_margin_db": best_worst if opt_mg else None,
            "in_window": in_window if opt_mg else False,
        },
        "physics_read": physics_read,
        "status": "PASS" if in_window else "FAIL",
        "honest_notes": [
            "最优定义=三门 S11 最差裕量最大（finite+passive+收敛+s21 PASS "
            "资格内）；若最优 worst_margin<0 则如实报未进窗",
            "p1 与三期基线同参（确定性引擎），偏差为复现旁证锚（非门）",
        ],
    }
    # p1 基线旁证锚对差
    p1 = points.get("p1", {})
    p1_sc = p1.get("scalars")
    if p1_sc is not None:
        verdict["baseline_anchor_delta_db"] = {
            k: round(p1_sc[k] - v, 6) for k, v in BASELINE_ANCHOR_DB.items()}
    (out_root / "sweep_verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")

    def _m(ok):
        return "PASS" if ok else "FAIL"

    md = [
        f"# coax_waveguide_transition F3 pin_len 五点扫掠判读"
        f"（{verdict['finished']}）",
        "",
        f"**总判：{verdict['status']}**（最优点"
        f" {best_key} pin_len={opt.get('pin_len_mm')}mm，"
        f"三门进窗={in_window}；预声明 launch_ready.md §3/§4）",
        "",
        "| 点 | pin_len mm | S11@10 dB（≤−10） | band-min dB（≤−10） "
        "| core-max dB（≤−8） | S21@10 dB（≥−1.5） | Z_in@f0 Ω | 收敛 "
        "| wall s | 状态 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, r in points.items():
        sc = r.get("scalars") or {}
        zin = sc.get("z_in_f0_ohm")
        pin_v = r.get("pin_len_mm")
        pin_s = f"{pin_v:.4g}" if isinstance(pin_v, (int, float)) else pin_v
        md.append(
            f"| {key} | {pin_s} "
            f"| {sc.get('s11_f0_db', float('nan')):.2f} "
            f"| {sc.get('band_min_db', float('nan')):.2f} "
            f"| {sc.get('core_max_db', float('nan')):.2f} "
            f"| {sc.get('s21_f0_db', float('nan')):.3f} "
            f"| {f'{zin[0]:.1f}{zin[1]:+.1f}j' if zin else 'n/a'} "
            f"| {r.get('converged')} | {r.get('wall_s', 'n/a')} "
            f"| {r.get('status')} |")
    if opt_mg:
        md += [
            "",
            "## 最优点裕量（门限−实测，正=过）",
            "",
            f"- {best_key} pin_len={opt.get('pin_len_mm')}mm："
            f"s11_f0 裕量 {opt_mg.get('s11_f0'):+.2f}dB、"
            f"band_min 裕量 {opt_mg.get('band_min'):+.2f}dB、"
            f"core_max 裕量 {opt_mg.get('core_max'):+.2f}dB、"
            f"最差 {opt_mg.get('worst'):+.2f}dB",
        ]
    if physics_read:
        md += [
            "",
            "## 物理读数（Z_in@f0 轨迹，事实性）",
            "",
            f"- Re(Z_in)：{physics_read['z_in_re_range_ohm'][0]}→"
            f"{physics_read['z_in_re_range_ohm'][1]}Ω（加长单调推高）；"
            f"Im(Z_in)：{physics_read['z_in_im_range_ohm'][0]}~"
            f"{physics_read['z_in_im_range_ohm'][1]}Ω 容性区近乎平坦"
            f"（|Im| 最小在 pin={physics_read['im_min_pin_mm']}mm）",
            f"- 判读：{physics_read['finding']}",
            "- 后续方向候选（主代理决策）：背短路微调（±旋转 Smith 轨迹，"
            "审计 §5 预案）/ 桥区几何（port_h/pin_r）/ 更细 pin 档；"
            "或先 HFSS Ph3 仲裁交叉核对匹配地形",
        ]
    if "baseline_anchor_delta_db" in verdict:
        md += ["", "## p1 基线复现旁证锚（vs verdict_offline_fix，非门）", ""]
        for k, v in verdict["baseline_anchor_delta_db"].items():
            md.append(f"- {k}: Δ={v:+.3f} dB")
    md += [
        "",
        "## 归因与后续",
        "",
        "- 判读面：sparams.csv 直读（渲染脚本内修后公式 S21=uf_inc 通道，"
        "T2 commit b24a0c2）；收敛=引擎日志 #266 口径（EndCriteria 缺省）。",
        "- 后续决策（主代理）：最优 pin_len 是否重注册模板名义；是否发起 "
        "HFSS Ph3 仲裁（−0.88dB 插损口径独立裁决，#307 端口语义注意项）。",
        "",
        "判读器：scripts/coax_f3_sweep.py judge（零求解幂等复跑；"
        "sweep_verdict.json 同目录）",
    ]
    (out_root / "sweep_verdict.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"[judge] status={verdict['status']} optimal={best_key} "
          f"pin={opt.get('pin_len_mm')} in_window={in_window}", flush=True)
    return 0 if in_window else 1


# ── 第二轮收针（T24 预备席 2026-09-29；预声明 runs/coax_f3_sweep_round2/
#    launch_ready.md——判据/选择/停机规则全部以该档为准，本段只做机制实现）──
# T18 定案：pin_len 单旋钮到顶（Re 54→91Ω 单调 / Im 容性平坦 −52~−43Ω），最优
# p2=6.1mm（Z=64.0−j43.2）未进窗。第二轮两旋钮正交化（Smith 直觉）：
#   Stage A（Im 旋钮=背短路位置 backshort_mm）：pin=6.1 定值，bs=名义+Δ；
#   Stage B（Re 旋钮=pin_len）：b*=argmin|Im(Z_in@f0)| 处 3 新点 pin 扫
#   （6.1@b* 复用 Stage A 同参点，不重解；条件细化 ≤1 点）。
# 旋钮参数化现状（src 零改动钉）：backshort_mm/port_h_mm/pin_r_mm 在模板
# §ME-6 均已参数化，本段只经 params 透传。

R2_OUT_DEFAULT = Path("runs") / "coax_f3_sweep_round2"
R2_PIN_A_MM = 6.1                       # T18 最优 pin（Re 臂定值）
R2_BS_DELTAS_MM: tuple[float, ...] = (-3.0, -2.0, -1.0, 0.5, 1.0)
R2_STAGE_B_PINS_MM: tuple[float, ...] = (5.6, 6.6, 7.1)  # 6.1@b* 复用 A 点
R2_IM_IMPROVE_MIN_OHM = 10.0            # 弱旋钮阈值（launch_ready §4.3）
R2_REFINE_MAX_POINTS = 1                # 条件细化点上限（§4.5）
R2_HALT_AFTER_FAILS = 2                 # 预算保护停机（§4.6）
R2_ANCHOR_ZIN_OHM = (64.0, -43.2)       # T18 p2（sweep_verdict.md 表）
R2_T18_P2_NRTS = 34271                  # T18 dryrender.json p2 零行为钉
R2_T18_P2_SHA256 = ("d2204c0eaf5bbbb722952f2284a20bb4a7d3019eac60ba5b2925"
                    "2c0771f3129b")


def r2_stage_a_points() -> list[dict]:
    """Stage A 点集：pin=6.1 定值，backshort=名义+Δ（round 4 位；§2 表）。"""
    nom_bs = float(nominal_params()["backshort_mm"])
    pts: list[dict] = []
    for i, d in enumerate(R2_BS_DELTAS_MM, 1):
        p = nominal_params()
        p["pin_len_mm"] = R2_PIN_A_MM
        p["backshort_mm"] = round(nom_bs + d, 4)
        pts.append({"tag": f"a{i}", "params": p,
                    "row": {"pin_len_mm": R2_PIN_A_MM,
                            "backshort_mm": p["backshort_mm"],
                            "bs_delta_mm": d}})
    return pts


def r2_stage_b_points(bs_star: float) -> list[dict]:
    """Stage B 新解点集（b1=5.6/b3=6.6/b4=7.1 @b*；b2=复用不在此列）。"""
    pts: list[dict] = []
    for tag, pin in (("b1", 5.6), ("b3", 6.6), ("b4", 7.1)):
        p = nominal_params()
        p["pin_len_mm"] = float(pin)
        p["backshort_mm"] = float(bs_star)
        pts.append({"tag": tag, "params": p,
                    "row": {"pin_len_mm": float(pin),
                            "backshort_mm": float(bs_star)}})
    return pts


def _r2_label(row: dict) -> str:
    return f"pin={row.get('pin_len_mm')} bs={row.get('backshort_mm')}"


def _r2_render_audit(pt: dict, literal_keys: list[str]) -> dict:
    """单点渲染+几何段 exec 零仿真审计（cmd_dryrender 同法，多旋钮字面量）。"""
    from rfauto.adapters.openems_templates import render_script

    row: dict = {"pin_len_mm": pt["row"].get("pin_len_mm"),
                 "backshort_mm": pt["row"].get("backshort_mm")}
    try:
        params = pt["params"]
        text = render_script(T, params, BAND, mesh_resolution_mm=MESH_MM)
        for key in literal_keys:
            row[f"{key}_literal_in_text"] = f'{key}={params[key]!r}' in text
        row.update(_plan_nrts(text))
        lit = render_script(T, dict(params, _nrts=row["nrts_plan"]), BAND,
                            mesh_resolution_mm=MESH_MM)
        m = re.search(r"NRTS\s*=\s*(\d+)", lit)
        row["nrts_literal"] = int(m.group(1)) if m else None
        row["nrts_literal_ok"] = row["nrts_literal"] == row["nrts_plan"]
        row["render_sha256"] = hashlib.sha256(lit.encode()).hexdigest()
        row["ok"] = bool(all(row[f"{k}_literal_in_text"] for k in literal_keys)
                         and row["nrts_literal_ok"]
                         and row["grid_min_spacing_ok"]
                         and abs(row["f0_hz"] - GATES["f0_ghz"] * 1e9) < 1.0)
    except Exception as exc:   # 审计失败=发射面红，如实（#122）
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["ok"] = False
    return row


def _r2_nrts_for(params: dict) -> int:
    """数据驱动点（Stage B/细化）的 NRTS 即时 plan（dry 彩排同法）。"""
    from rfauto.adapters.openems_templates import render_script

    text = render_script(T, params, BAND, mesh_resolution_mm=MESH_MM)
    return int(_plan_nrts(text)["nrts_plan"])


def cmd_r2dryrender(out_root: Path) -> int:
    """Stage A 渲染审计+T18 p2 零行为钉+Stage B 机制彩排（零仿真，秒级）。"""
    from rfauto.adapters.openems_templates import COAX_WG_NOMINAL, render_script

    out: dict = {"template": T, "mode": "round2_two_knob",
                 "band_ghz": list(BAND), "mesh_mm": MESH_MM,
                 "window_ns": WINDOW_NS,
                 "plan": {"pin_a_mm": R2_PIN_A_MM,
                          "bs_deltas_mm": list(R2_BS_DELTAS_MM),
                          "stage_b_pins_mm": list(R2_STAGE_B_PINS_MM),
                          "im_improve_min_ohm": R2_IM_IMPROVE_MIN_OHM,
                          "refine_max_points": R2_REFINE_MAX_POINTS,
                          "halt_after_fails": R2_HALT_AFTER_FAILS,
                          "anchor_zin_ohm": list(R2_ANCHOR_ZIN_OHM),
                          "predeclaration": "launch_ready.md（判据先行 #122）"},
                 "points": {}}
    ok = True
    hashes: dict[str, str] = {}
    for pt in r2_stage_a_points():
        row = _r2_render_audit(pt, ["pin_len_mm", "backshort_mm"])
        if row.get("render_sha256"):
            hashes[pt["tag"]] = row["render_sha256"]
        out["points"][pt["tag"]] = row
        ok = ok and bool(row.get("ok"))
        print(f"[r2dryrender] {pt['tag']} bs={pt['row']['backshort_mm']}: "
              f"ok={row.get('ok')} nrts={row.get('nrts_plan')} "
              f"err={row.get('error')}", flush=True)
    # T18 p2 渲染零行为钉（launch_ready §0：nominal+pin6.1+_nrts=34271）
    p = nominal_params()
    p["pin_len_mm"] = R2_PIN_A_MM
    p["_nrts"] = R2_T18_P2_NRTS
    lit = render_script(T, p, BAND, mesh_resolution_mm=MESH_MM)
    sha = hashlib.sha256(lit.encode()).hexdigest()
    out["t18_p2_hash_pin"] = {"expected": R2_T18_P2_SHA256, "actual": sha,
                              "ok": sha == R2_T18_P2_SHA256}
    ok = ok and sha == R2_T18_P2_SHA256
    print(f"[r2dryrender] t18_p2_hash_pin ok={sha == R2_T18_P2_SHA256}",
          flush=True)
    # Stage B 机制彩排（假想 b*=名义−0.5；验证旋钮透传机制，非发射点值）
    rep_bs = round(float(COAX_WG_NOMINAL["backshort_mm"]) - 0.5, 4)
    pt = {"tag": "rehearsal_bstar",
          "params": dict(nominal_params(), pin_len_mm=6.6,
                         backshort_mm=rep_bs),
          "row": {"pin_len_mm": 6.6, "backshort_mm": rep_bs}}
    row = _r2_render_audit(pt, ["pin_len_mm", "backshort_mm"])
    row["machinery_only"] = True   # b* 跑时数据驱动，彩排值非发射点值
    out["points"]["rehearsal_bstar"] = row
    ok = ok and bool(row.get("ok"))
    print(f"[r2dryrender] rehearsal_bstar bs={rep_bs}: ok={row.get('ok')} "
          f"err={row.get('error')}", flush=True)
    out["hashes_distinct"] = len(set(hashes.values())) == len(hashes)
    out["ok"] = bool(ok and out["hashes_distinct"])
    (out_root / "dryrender.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[r2dryrender] verdict ok={out['ok']} "
          f"hashes_distinct={out['hashes_distinct']}", flush=True)
    return 0 if out["ok"] else 1


def _r2_solve_point(out_root: Path, pt: dict, nrts: int | None,
                    timeout_s: float) -> dict:
    """单点求解+判读（cmd_oe 单点体同构复制；r2 行含 backshort 列）。

    T18 三子命令零行为钉：cmd_oe 未动，此处复制其单点操作序（render→
    runner→子进程→日志→收敛→判据门→oe_result.json；#157/#245 发射形态）。
    """
    from rfauto.adapters.openems_templates import render_script

    run_dir = out_root / pt["tag"]
    run_dir.mkdir(parents=True, exist_ok=True)
    params = dict(pt["params"])
    if nrts:
        params["_nrts"] = int(nrts)
    row: dict = {"point": pt["tag"], **pt["row"], "nrts_plan": nrts,
                 "started": time.strftime("%F %T")}
    print(f"[r2oe] {pt['tag']} {_r2_label(pt['row'])} start", flush=True)
    t0 = time.time()
    try:
        text = render_script(T, params, BAND, mesh_resolution_mm=MESH_MM)
        (run_dir / "simulation.py").write_text(text, encoding="utf-8")
        row["render_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        runner = _write_runner(run_dir)
        cmd = [sys.executable, str(runner.resolve()),
               str((run_dir / "simulation.py").resolve())]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=float(timeout_s), cwd=str(run_dir.resolve()))
            rcode, so, se = (proc.returncode, proc.stdout or "",
                             proc.stderr or "")
        except subprocess.TimeoutExpired:
            rcode, so, se = None, "", f"TimeoutExpired after {timeout_s}s"
        with contextlib.suppress(OSError):   # #105 best-effort 落盘
            (run_dir / "_last_stdout.log").write_text(so, encoding="utf-8")
            (run_dir / "_last_stderr.log").write_text(se, encoding="utf-8")
        row["rc"] = rcode
        row["wall_s"] = round(time.time() - t0, 1)
        row["solve_success"] = bool(rcode == 0
                                    and (run_dir / "sparams.csv").is_file())
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["solve_success"] = False
        row["wall_s"] = round(time.time() - t0, 1)
    # 收敛判读（#266 口径；must_converge）
    converged: bool | None = None
    conv_reason = "求解未完成（sparams.csv 缺或 rc!=0）"
    try:
        from fd_oe_campaign import nrts_convergence, parse_engine_log

        log = run_dir / "_last_stdout.log"
        if log.is_file():
            eng = parse_engine_log(
                log.read_text(encoding="utf-8", errors="replace"))
            row["engine"] = eng
            conv = nrts_convergence(eng)
            converged = conv["converged"]
            conv_reason = conv["reason"]
    except Exception as exc:   # best-effort（#105）
        conv_reason = f"gate error: {exc}"
    row["converged"] = converged
    row["converged_reason"] = conv_reason
    try:
        sp = _read_sparams5(run_dir / "sparams.csv")
        if sp is None:
            raise ValueError("sparams.csv 不可读/空")
        freqs, s11, s21 = sp
        sc = _gate_scalars(freqs, s11, s21)
        row["scalars"] = sc
        checks = _gate_checks(sc, converged, conv_reason)
        if not row.get("solve_success"):
            checks.append({"name": "solve", "ok": False,
                           "detail": f"rc={row.get('rc')}（引擎未正常结束）"})
        row["checks"] = checks
        row["status"] = "PASS" if all(c["ok"] for c in checks) else "FAIL"
        row["reasons"] = [c["detail"] for c in checks if not c["ok"]]
    except Exception as exc:
        row["status"] = "FAIL"
        row["reasons"] = [f"S 参数判读失败: {exc}"]
    (run_dir / "oe_result.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    sc = row.get("scalars") or {}
    print(f"[r2oe] {pt['tag']} {_r2_label(pt['row'])}: {row['status']} "
          f"wall={row['wall_s']}s s11_f0={sc.get('s11_f0_db')} "
          f"zin={sc.get('z_in_f0_ohm')} conv={converged}", flush=True)
    return row


def _r2_load_row(out_root: Path, tag: str) -> dict | None:
    """读点结果（oe_result.json + sparams.csv 现算 scalars，judge 自足幂等）。"""
    if not (out_root / tag / "oe_result.json").is_file():
        return None
    with contextlib.suppress(Exception):
        row = json.loads(
            (out_root / tag / "oe_result.json").read_text(encoding="utf-8"))
        if (out_root / tag / "sparams.csv").is_file():
            with contextlib.suppress(Exception):
                freqs, s11, s21 = _read_sparams5(
                    out_root / tag / "sparams.csv")
                row["scalars"] = _gate_scalars(freqs, s11, s21)
        return row
    return None


def _r2_zin_im(row: dict) -> float | None:
    z = (row.get("scalars") or {}).get("z_in_f0_ohm")
    return float(z[1]) if z else None


def _r2_best_of(rows: dict[str, dict]) -> dict | None:
    """三门 S11 最差裕量最大者（资格内；同 T18 判读）。"""
    best, best_worst = None, -1e99
    for row in rows.values():
        if _eligible(row):
            row["margins"] = _margins(row["scalars"])
            if row["margins"]["worst"] > best_worst:
                best, best_worst = row, row["margins"]["worst"]
    return best


def _r2_refine_plan(stage_b: dict[str, dict], bs_star: float) -> dict | None:
    """条件细化计划（§4.5）：相邻资格 b 点 (Re−50) 变号 → 中点 1 点。"""
    elig = sorted(((tag, row) for tag, row in stage_b.items() if _eligible(row)),
                  key=lambda kv: kv[1]["scalars"]["z_in_f0_ohm"][0])
    for (t1, row1), (t2, row2) in pairwise(elig):
        d1 = row1["scalars"]["z_in_f0_ohm"][0] - 50.0
        d2 = row2["scalars"]["z_in_f0_ohm"][0] - 50.0
        if d1 != 0 and d1 * d2 < 0:
            return {"recommended": True,
                    "pin_len_mm": round((row1["pin_len_mm"]
                                         + row2["pin_len_mm"]) / 2.0, 3),
                    "backshort_mm": bs_star, "bracket": [t1, t2]}
    return None


def _r2_judge_and_write(out_root: Path) -> tuple[dict, list[str]]:
    """预声明判读核心（零求解幂等；选择/停机规则=launch_ready §4；落档）。"""
    anchor_im = R2_ANCHOR_ZIN_OHM[1]
    anchor_bs = round(float(nominal_params()["backshort_mm"]), 4)
    stage_a: dict[str, dict] = {}
    b_star, b_star_im, b_star_bs = None, None, None
    for pt in r2_stage_a_points():
        row = _r2_load_row(out_root, pt["tag"])
        stage_a[pt["tag"]] = row if row is not None else {
            "point": pt["tag"], **pt["row"], "status": "MISSING"}
        if row is not None and row.get("status") == "PASS":
            im = _r2_zin_im(row)
            if im is not None and (b_star_im is None
                                   or abs(im) < abs(b_star_im)):
                b_star, b_star_im = pt["tag"], im
                b_star_bs = row.get("backshort_mm")
    if b_star_im is None:
        armed, weak_note = False, "Stage A 无 PASS 点（未完成或全败）"
    else:
        improve = abs(anchor_im) - abs(b_star_im)
        armed = improve >= R2_IM_IMPROVE_MIN_OHM
        weak_note = (f"|Im| 改善 {improve:.1f}Ω（阈值 "
                     f"{R2_IM_IMPROVE_MIN_OHM}Ω）——"
                     + ("武装 Stage B" if armed else
                        "背短路 Im 旋钮弱，第三轮转候选② port_h/pin_r"))
    stage_b: dict[str, dict] = {}
    best, refine = None, None
    if armed:
        reuse = stage_a[b_star]
        stage_b["b2"] = {**reuse, "point": "b2", "reused_from": b_star}
        for tag, pin in (("b1", 5.6), ("b3", 6.6), ("b4", 7.1)):
            row = _r2_load_row(out_root, tag)
            stage_b[tag] = row if row is not None else {
                "point": tag, "pin_len_mm": float(pin),
                "backshort_mm": b_star_bs, "status": "MISSING"}
        best = _r2_best_of(stage_b)
        if best is not None and best["margins"]["worst"] < 0:
            refine = _r2_refine_plan(stage_b, b_star_bs)
            if refine is not None and "r1" not in stage_b:
                row_r1 = _r2_load_row(out_root, "r1")
                if row_r1 is not None:
                    stage_b["r1"] = row_r1
                    best = _r2_best_of(stage_b) or best
    in_window = bool(best) and all(best["margins"][k] >= 0
                                   for k in ("s11_f0", "band_min", "core_max"))
    verdict: dict = {
        "template": T,
        "mode": "round2_two_knob_backshort_then_pin",
        "finished": time.strftime("%F %T"),
        "provenance": (
            "预声明 runs/coax_f3_sweep_round2/launch_ready.md（判据先行"
            " #122）；上游=runs/coax_f3_sweep/sweep_verdict.md（T18）；"
            "判据窗=三期 criteria.json 同源零改动。"),
        "criteria": GATES,
        "anchor": {"point": "T18-p2", "pin_len_mm": R2_PIN_A_MM,
                   "backshort_mm": anchor_bs,
                   "z_in_f0_ohm": list(R2_ANCHOR_ZIN_OHM)},
        "stage_a": {tag: {k: row.get(k) for k in
                          ("point", "pin_len_mm", "backshort_mm",
                           "bs_delta_mm", "status", "scalars", "wall_s",
                           "reasons")} for tag, row in stage_a.items()},
        "b_star": {"point": b_star, "backshort_mm": b_star_bs,
                   "z_in_im_ohm": b_star_im,
                   "im_improvement_ohm": (round(abs(anchor_im) - abs(b_star_im), 2)
                                          if b_star_im is not None else None),
                   "stage_b_armed": armed, "note": weak_note},
        "stage_b": {tag: {k: row.get(k) for k in
                          ("point", "pin_len_mm", "backshort_mm", "status",
                           "reused_from", "scalars", "margins", "wall_s",
                           "reasons")} for tag, row in stage_b.items()},
        "optimal": ({"point": best.get("point"),
                     "pin_len_mm": best.get("pin_len_mm"),
                     "backshort_mm": best.get("backshort_mm"),
                     "scalars": best.get("scalars"),
                     "margins": best.get("margins")} if best else None),
        "refinement": refine,
        "stop_rule": ("stage_a_then_best（弱旋钮阈值 "
                      f"{R2_IM_IMPROVE_MIN_OHM}Ω；细化上限 "
                      f"{R2_REFINE_MAX_POINTS}；halt_after_fails="
                      f"{R2_HALT_AFTER_FAILS}）"),
        "status": "PASS" if in_window else "FAIL",
        "honest_notes": [
            "b*=argmin|Im(Z_in@f0)|（资格点内）；Im→0 后即便 Re∈[40,80] 亦过 "
            "s11_f0 门（−12.7~−19.1dB）——f0 门本质是 Im 问题（launch_ready §1）",
            "s21 门为硬资格门：背短路偏移降低前向耦合时如实淘汰，不凑绿",
            "6.1@b* 复用 Stage A 同参点（零重解）；anchor=T18 p2 复用不重解",
        ],
    }
    (out_root / "sweep_verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")

    def _cell(row: dict, key: str, fmt: str = ".2f") -> str:
        v = (row.get("scalars") or {}).get(key)
        return f"{v:{fmt}}" if isinstance(v, (int, float)) else "n/a"

    def _zcell(row: dict) -> str:
        z = (row.get("scalars") or {}).get("z_in_f0_ohm")
        return f"{z[0]:.1f}{z[1]:+.1f}j" if z else "n/a"

    md = [
        f"# coax_waveguide_transition 第二轮收针判读（{verdict['finished']}）",
        "",
        f"**总判：{verdict['status']}**（b*={b_star} "
        f"bs={b_star_bs}，Stage B 武装={armed}；"
        f"{weak_note}；预声明 launch_ready.md §4）",
        "",
        "## Stage A（Im 旋钮=背短路位置，pin=6.1 定值）",
        "",
        "| 点 | bs mm（Δ） | S11@10 dB（≤−10） | band-min dB（≤−10） "
        "| core-max dB（≤−8） | S21@10 dB（≥−1.5） | Z_in@f0 Ω | 收敛 "
        "| wall s | 状态 |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| anchor(T18-p2) | {anchor_bs}（0） | -8.58 | -11.08 | -8.55 "
        f"| -0.748 | 64.0-43.2j | True | (T18) | 复用 |",
    ]
    for tag, row in stage_a.items():
        bs_v = row.get("backshort_mm")
        md.append(
            f"| {tag} | {bs_v}（{row.get('bs_delta_mm', 'n/a')}） "
            f"| {_cell(row, 's11_f0_db')} | {_cell(row, 'band_min_db')} "
            f"| {_cell(row, 'core_max_db')} | {_cell(row, 's21_f0_db', '.3f')} "
            f"| {_zcell(row)} | {row.get('converged')} "
            f"| {row.get('wall_s', 'n/a')} | {row.get('status')} |")
    md += ["", "## b* 判定", "",
           f"- {weak_note}",
           f"- b*={b_star}（bs={b_star_bs}，Im={b_star_im}Ω）"]
    if armed:
        md += ["", "## Stage B（Re 旋钮=pin_len，bs=b* 定值）", "",
               "| 点 | pin mm | bs mm | S11@10 dB（≤−10） | band-min dB（≤−10） "
               "| core-max dB（≤−8） | S21@10 dB（≥−1.5） | Z_in@f0 Ω "
               "| 资格 | 状态 |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        for tag, row in stage_b.items():
            el = _eligible(row)
            md.append(
                f"| {tag}{'（复用 ' + row['reused_from'] + '）' if row.get('reused_from') else ''} "
                f"| {row.get('pin_len_mm')} | {row.get('backshort_mm')} "
                f"| {_cell(row, 's11_f0_db')} | {_cell(row, 'band_min_db')} "
                f"| {_cell(row, 'core_max_db')} | {_cell(row, 's21_f0_db', '.3f')} "
                f"| {_zcell(row)} | {el} | {row.get('status')} |")
        if refine:
            md += ["", f"- 细化计划（§4.5）：{refine}"]
    if best:
        mg = best["margins"]
        md += ["", "## 最优点裕量（门限−实测，正=过）", "",
               f"- {best.get('point')} pin={best.get('pin_len_mm')}mm "
               f"bs={best.get('backshort_mm')}mm："
               f"s11_f0 {mg['s11_f0']:+.2f}dB、band_min {mg['band_min']:+.2f}dB、"
               f"core_max {mg['core_max']:+.2f}dB、最差 {mg['worst']:+.2f}dB"]
    md += ["", "## 归因与后续", "",
           "- 判读面：sparams.csv 直读（修后 uf_inc 透射通道，T2 b24a0c2）；"
           "收敛=引擎日志 #266 口径。",
           "- 弱旋钮分支（如触发）：第三轮转候选② 桥区几何（port_h/pin_r，"
           "容抗残留疑点）；候选③（6.0-6.7 窄扫）已被本轮 Stage B 覆盖。",
           "",
           "判读器：scripts/coax_f3_sweep.py r2judge（零求解幂等复跑）"]
    (out_root / "sweep_verdict.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"[r2judge] status={verdict['status']} b_star={b_star} "
          f"armed={armed} optimal={(best or {}).get('point')} "
          f"in_window={in_window}", flush=True)
    return verdict, md


def cmd_r2oe(out_root: Path, only: list[str], timeout_s: float) -> int:
    """两旋钮正交化串行真机（Stage A→b*→Stage B→条件细化；solo 单飞）。"""
    dry_path = out_root / "dryrender.json"
    if not dry_path.is_file():
        print("[r2oe] dryrender.json 缺——先跑 r2dryrender（§4.7 前置门）",
              flush=True)
        return 2
    dry = json.loads(dry_path.read_text(encoding="utf-8"))
    if not dry.get("ok"):
        print("[r2oe] dryrender ok=False——发射前置门未过（§4.7）", flush=True)
        return 2
    nrts_of = {tag: (row or {}).get("nrts_plan")
               for tag, row in dry.get("points", {}).items()}
    only_set = set(only)

    def _solve(pt: dict) -> None:
        nrts = nrts_of.get(pt["tag"])
        if nrts is None:   # 数据驱动点（Stage B/细化）即时 plan
            nrts = _r2_nrts_for(pt["params"])
        _r2_solve_point(out_root, pt, nrts, timeout_s)

    a_pts = [pt for pt in r2_stage_a_points()
             if not only_set or pt["tag"] in only_set]
    for i, pt in enumerate(a_pts, 1):
        _solve(pt)
        if i == R2_HALT_AFTER_FAILS:   # §4.6 预算保护停机（前 2 解点均未过）
            heads = [(_r2_load_row(out_root, p["tag"]) or {})
                     for p in a_pts[:R2_HALT_AFTER_FAILS]]
            if heads and all(r.get("status") != "PASS" for r in heads):
                print(f"[r2oe] 前 {R2_HALT_AFTER_FAILS} 解点均未过——停机"
                      "（§4.6）", flush=True)
                _r2_judge_and_write(out_root)
                return 1
    _r2_judge_and_write(out_root)
    core = json.loads((out_root / "sweep_verdict.json").read_text(
        encoding="utf-8"))
    if not core["b_star"]["stage_b_armed"]:
        return 0 if core["status"] == "PASS" else 1
    bs_star = core["b_star"]["backshort_mm"]
    for pt in r2_stage_b_points(bs_star):
        if not only_set or pt["tag"] in only_set:
            _solve(pt)
    _r2_judge_and_write(out_root)
    core = json.loads((out_root / "sweep_verdict.json").read_text(
        encoding="utf-8"))
    refine = core.get("refinement")
    if (refine and refine.get("recommended") and "r1" not in core["stage_b"]
            and R2_REFINE_MAX_POINTS >= 1):
        pt = {"tag": "r1",
              "params": dict(nominal_params(),
                             pin_len_mm=float(refine["pin_len_mm"]),
                             backshort_mm=float(refine["backshort_mm"])),
              "row": {"pin_len_mm": refine["pin_len_mm"],
                      "backshort_mm": refine["backshort_mm"],
                      "bs_delta_mm": None,
                      "bracket": refine["bracket"]}}
        _solve(pt)
    _r2_judge_and_write(out_root)
    core = json.loads((out_root / "sweep_verdict.json").read_text(
        encoding="utf-8"))
    return 0 if core["status"] == "PASS" else 1


def cmd_r2judge(out_root: Path) -> int:
    verdict, _md = _r2_judge_and_write(out_root)
    return 0 if verdict["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["dryrender", "oe", "judge",
                                         "r2dryrender", "r2oe", "r2judge"])
    parser.add_argument("--out-root", default="",
                        help="缺省=runs/coax_f3_sweep（T18）或 "
                             "runs/coax_f3_sweep_round2（r2*）")
    parser.add_argument("--point", default="",
                        help="逗号分隔点子集（oe=点号；r2oe=tag 如 a1,b3）")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()
    # r2* 缺省落第二轮目录；T18 三子命令缺省不变（零行为钉）
    out_root = (Path(args.out_root) if args.out_root
                else (R2_OUT_DEFAULT if args.mode.startswith("r2")
                      else OUT_DEFAULT))
    out_root.mkdir(parents=True, exist_ok=True)
    if args.mode == "dryrender":
        return cmd_dryrender(out_root)
    if args.mode == "oe":
        only = [int(x) for x in args.point.split(",") if x.strip()]
        return cmd_oe(out_root, only, args.timeout)
    if args.mode == "judge":
        return cmd_judge(out_root)
    if args.mode == "r2dryrender":
        return cmd_r2dryrender(out_root)
    if args.mode == "r2oe":
        only = [x.strip() for x in args.point.split(",") if x.strip()]
        return cmd_r2oe(out_root, only, args.timeout)
    return cmd_r2judge(out_root)


if __name__ == "__main__":
    raise SystemExit(main())
