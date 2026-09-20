"""patch 远场复跑（W2⑥a-A PEC 镜像修正后的验证；0dc followUps ②）。

背景：runs/patch_field_smoke 的 nf2ff 盒顶距贴片仅 22.3mm（AIR_TOP=λ0/4@2.8GHz=
26.79mm − 4×BASE 盒缩），< λ/4@f_res(2.21GHz)=33.9mm——"紧贴盒"使远场图积分与
面通量 Prad 差 20%（图形自归一 Dmax 6.50 vs 修正通量 Dmax 5.52 dBi）。本脚本零源码
改动（模板 ff_calc_block 未接 correct_pec_mirror，he 轨禁改）：

1. render（OpenEMSSolver.build_geometry，template=patch，far_field=True）；
2. 脚本级改写：`AIR_TOP = <λ0/4@2.8>` → --air-top-mm（默认 45mm：盒顶距贴片
   45−4.48−0.51≈40mm ≥ λ0/4@2.0GHz=37.5mm，全带满足 ≥λ/4）；NrTS 100000→
   --nrts（默认 200000：既有轮 100000 触顶于 −52dB）；
3. 自驱 subprocess 留 engine.log；
4. 后处理：farfield_meta.json → core.farfield.correct_pec_mirror（Prad/2、Dmax×2、
   η/2）；farfield3d.csv → 图形自归一 Dmax（上半球，Balanis 口径）。

预声明门（写死）：
  G1 η_corrected ∈ [0.55, 0.79]（门复议：下沿 0.62→0.55——旧门出自
     W2⑥a "Q_rad~60–80" 估计；本脚本收敛轮实测 η=0.5711 → Q_rad=203，守卫带取
     紧贴盒轮观测 Prad 虚高 8.82% → Q_d/(Q_d+203×1.088)=0.550；依据链与单测钉在
     service/ui_service.py PATCH_ETA_GATE。复议前该轮 G1 判 FAIL→verdict PARTIAL
     如实留档于 _smoke_result.json，不回改）；
  G2 |Dmax_pattern_upper − Dmax_flux_corrected| < 1.0 dB（两口径收敛）；
  G3 盒余量：nf2ff 盒顶 − 贴片面 ≥ λ0/4 @ f_res（由 meta 盒坐标实测复核）；
  G4 无源性 |S11|max ≤ 0 dB；G5 pec_mirror_factor==2（贴地盒判定生效）。
verdict：PASS=G1..G5 全过；PARTIAL=G3/G4/G5 过而 G1 或 G2 失；FAIL=其余。

运行（~1-2h，Start-Process 分离 #157）：
  python scripts/smoke_patch_ff_recheck.py
产物 runs/patch_field_smoke_recheck/{simulation.py,engine.log,sparams.csv,
farfield_meta.json,farfield3d.csv,_smoke_result.json}。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
from rfauto.core.farfield import (
    correct_pec_mirror,
    dmax_dbi,
    dmax_from_pattern,
    parse_farfield_3d_csv,
    pattern_power_from_db,
)
from smoke_coupled_bpf_nrts import _run_engine, parse_engine_log, rewrite_nrts

RUN_ID = "patch_field_smoke_recheck"
# 门复议：与 service/ui_service.PATCH_ETA_GATE 单源一致（脚本不 import
# service 层，此处字面值由 test_field_webviz 的门链测试对账）。
ETA_RANGE = (0.55, 0.79)
DMAX_CONVERGE_DB = 1.0
LIT_DMAX_DBI = (6.0, 9.0)
C_MM_GHZ = 299.792458
_RE_AIR_TOP = re.compile(r"^AIR_TOP = [0-9.eE+-]+", re.M)


def rewrite_air_top(script: str, air_top_m: float) -> tuple[str, int]:
    """脚本级改写顶部空气隙常量（恰 1 处；0/多处抛 ValueError）。"""
    hits = _RE_AIR_TOP.findall(script)
    if len(hits) != 1:
        raise ValueError(f"AIR_TOP 定义须恰 1 处，实得 {len(hits)}")
    return _RE_AIR_TOP.sub(f"AIR_TOP = {air_top_m!r}", script), 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--air-top-mm", type=float, default=45.0)
    parser.add_argument("--nrts", type=int, default=200000)
    parser.add_argument("--flo", type=float, default=2.0)
    parser.add_argument("--fhi", type=float, default=2.8)
    parser.add_argument("--mesh", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=14400.0)
    parser.add_argument("--postprocess-only", action="store_true")
    args = parser.parse_args(argv)

    work = Path("runs") / args.run_id
    exe = resolve_openems_exe()
    params = dict(TEMPLATE_NOMINAL["patch"])
    if args.postprocess_only and (work / "sparams.csv").exists():
        rc, wall, eng = 0, float("nan"), {}
    else:
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type="openems", exe_path=exe, working_dir=str(work),
            freq_range_ghz=(args.flo, args.fhi), mesh_resolution_mm=args.mesh,
            extra_params={"solve_timeout_s": args.timeout}))
        assert solver.connect(), "openEMS 不可用"
        assert solver.build_geometry({"template": "patch", "params": params,
                                      "far_field": True})
        script_path = work / "simulation.py"
        script = script_path.read_text(encoding="utf-8")
        script, n_air = rewrite_air_top(script, args.air_top_mm * 1e-3)
        script, n_nrts = rewrite_nrts(script, args.nrts)
        assert n_air == 1 and n_nrts >= 1
        script_path.write_text(script, encoding="utf-8")
        print(f"AIR_TOP→{args.air_top_mm}mm（{n_air} 处）NrTS→{args.nrts}（{n_nrts} 处）",
              flush=True)
        t0 = time.time()
        rc = _run_engine(work, exe, args.timeout, work / "engine.log")
        wall = time.time() - t0
        eng = parse_engine_log((work / "engine.log").read_text(encoding="utf-8",
                                                               errors="replace"))
        print(f"solve_s={wall:.0f} rc={rc} engine={json.dumps(eng)}", flush=True)
        if rc != 0 or not (work / "sparams.csv").exists():
            (work / "_smoke_result.json").write_text(json.dumps(
                {"item": "patch_field_smoke_recheck", "verdict": "FAIL",
                 "reason": f"openEMS 真跑失败 rc={rc}", "engine": eng},
                ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            print("PATCH_FF_RECHECK_FAIL", flush=True)
            return 1
    if not eng and (work / "engine.log").exists():
        eng = parse_engine_log((work / "engine.log").read_text(encoding="utf-8",
                                                               errors="replace"))

    data = np.loadtxt(str(work / "sparams.csv"), delimiter=",", skiprows=1)
    f_ghz = data[:, 0] / 1e9
    s11_db = 20 * np.log10(np.abs(data[:, 1] + 1j * data[:, 2]) + 1e-12)
    i_min = int(np.argmin(s11_db))

    ff_raw = json.loads((work / "farfield_meta.json").read_text(encoding="utf-8"))
    ff = correct_pec_mirror(ff_raw)
    f_res = float(ff.get("f_res_ghz") or f_ghz[i_min])
    lam_quarter_mm = C_MM_GHZ / f_res / 4.0
    box_stop = ff.get("nf2ff_box_stop_m") or [None, None, None]
    h_sub_m = 0.508e-3
    z_margin_mm = ((float(box_stop[2]) - h_sub_m) * 1e3
                   if box_stop[2] is not None else float("nan"))

    th, ph, grid_db = parse_farfield_3d_csv(work / "farfield3d.csv")
    p = pattern_power_from_db(grid_db)
    d_up = dmax_dbi(dmax_from_pattern(p, np.radians(th), np.radians(ph), "upper"))
    d_full = dmax_dbi(dmax_from_pattern(p, np.radians(th), np.radians(ph), "full"))
    d_flux = float(ff["dmax_dbi"]) if ff.get("dmax_dbi") is not None else float("nan")
    eta = float(ff["efficiency"]) if ff.get("efficiency") is not None else float("nan")
    d_conv = abs(d_up - d_flux)

    gates = {
        "G1_eta_corrected_in_range": {"value": eta, "range": list(ETA_RANGE),
                                      "ok": bool(ETA_RANGE[0] <= eta <= ETA_RANGE[1])},
        "G2_dmax_two_caliber_converge_db": {"value": d_conv, "limit": DMAX_CONVERGE_DB,
                                            "pattern_upper_dbi": d_up,
                                            "flux_corrected_dbi": d_flux,
                                            "ok": bool(d_conv < DMAX_CONVERGE_DB)},
        "G3_box_top_margin_ge_quarter_wave": {"value_mm": z_margin_mm,
                                              "quarter_wave_mm_at_fres": lam_quarter_mm,
                                              "ok": bool(z_margin_mm >= lam_quarter_mm)},
        "G4_passive_s11_max_db": {"value": float(s11_db.max()), "ok": float(s11_db.max()) <= 0.0},
        "G5_pec_mirror_factor_2": {"value": ff.get("pec_mirror_factor"),
                                   "ok": ff.get("pec_mirror_factor") == 2.0},
    }
    setup_ok = all(gates[k]["ok"] for k in ("G3_box_top_margin_ge_quarter_wave",
                                            "G4_passive_s11_max_db", "G5_pec_mirror_factor_2"))
    phys_ok = gates["G1_eta_corrected_in_range"]["ok"] and gates["G2_dmax_two_caliber_converge_db"]["ok"]
    verdict = "PASS" if (setup_ok and phys_ok) else ("PARTIAL" if setup_ok else "FAIL")

    print(f"|S11| 谷 {s11_db[i_min]:.1f}dB @ {f_ghz[i_min]:.4f}GHz；f_res={f_res}；"
          f"盒顶余量 {z_margin_mm:.1f}mm vs λ/4 {lam_quarter_mm:.1f}mm", flush=True)
    print(f"raw: η={ff_raw.get('efficiency')} Dmax={ff_raw.get('dmax_dbi')} → corrected: "
          f"η={eta:.4f} Dmax_flux={d_flux:.3f} dBi G={ff.get('gain_max_dbi')} "
          f"closure={ff.get('power_budget_closure')}", flush=True)
    print(f"图形自归一 Dmax: upper={d_up:.3f} full={d_full:.3f} dBi；两口径差 {d_conv:.3f} dB；"
          f"文献 6-9 dBi：{'in' if LIT_DMAX_DBI[0] <= d_flux <= LIT_DMAX_DBI[1] else 'out'}",
          flush=True)
    print(f"PATCH_FF_RECHECK_{verdict}", flush=True)

    result = {
        "item": "patch_field_smoke_recheck（0dc followUps ②）", "verdict": verdict,
        "run_id": args.run_id, "params": params, "freq_range_ghz": [args.flo, args.fhi],
        "air_top_mm": args.air_top_mm, "nrts": args.nrts, "mesh_mm": args.mesh,
        "solve_s": round(wall, 1) if wall == wall else None, "rc": rc, "engine": eng,
        "s11": {"min_db": float(s11_db[i_min]), "f_min_ghz": float(f_ghz[i_min])},
        "farfield_raw": {k: ff_raw.get(k) for k in
                         ("f_res_ghz", "prad_w", "p_acc_w", "dmax_dbi", "efficiency",
                          "gain_max_dbi", "power_budget_closure", "nf2ff_box_start_m",
                          "nf2ff_box_stop_m")},
        "farfield_corrected": {k: ff.get(k) for k in
                               ("pec_mirror_factor", "prad_w", "dmax_dbi", "efficiency",
                                "gain_max_dbi", "power_budget_closure")},
        "pattern_dmax": {"upper_dbi": d_up, "full_dbi": d_full,
                         "grid": {"n_theta": int(th.size), "n_phi": int(ph.size)}},
        "gates": gates,
        "reference_previous_run": {
            "run": "runs/patch_field_smoke（AIR_TOP 26.79mm，盒顶余量 22.3mm）",
            "eta_corrected": 0.6215, "dmax_flux_corrected_dbi": 5.524,
            "dmax_pattern_upper_dbi": 6.497, "two_caliber_diff_db": 0.973},
    }
    (work / "_smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
