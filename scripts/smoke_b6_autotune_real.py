"""B6 autotune 真机一轮薄驱动（openems-real-smoke-bundle ⑤）。

等价 `rfauto autotune runs/kicad_b6_stage2/b6_autotune_recipe.yaml --budget 2
--json`：直调 service.autotune_service.autotune_loop（缺省通道
=_make_openems_sampler 真机，autotune_service.py:273），零源码改动。

验收（如实）：verdict 原样；首轮名义点 w_mm=0.849（配方 params 优先，:286-290）
复现 stage-2 锚 runs/kicad_b6_stage2/stage2_summary.json（|S11|max≈−22.5dB；
εeff −1.95% 需 port_beta.csv——仅活跑产出，缓存回放时如实标注不可再导出）；
每轮 typed fix 步长 ≤ max_step_pct 且落 bounds。缓存回放检测：采样器工作目录
runs/autotune_work_<id>/pt_*/fdtd/ 是否存在（solve() 全局缓存
runs/openems_cache 按脚本内容命中时引擎不启动）。

产物 runs/<run_id>/autotune.json（服务落盘）+ runs/b6_autotune_real/_smoke_result.json。
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
import time
from itertools import pairwise
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.service.autotune_service import autotune_loop

RECIPE = "runs/kicad_b6_stage2/b6_autotune_recipe.yaml"
STAGE2 = "runs/kicad_b6_stage2/stage2_summary.json"
OUT = Path("runs/b6_autotune_real")
F0 = 2.5


def step_within_bounds(history: list[dict], bounds: dict[str, tuple[float, float]],
                       max_step_pct: float) -> dict[str, object]:
    """逐轮参数修正：|Δ|/|prev| ≤ max_step_pct 且落 bounds（纯数学，离线可测）。"""
    checks: list[dict[str, object]] = []
    ok = True
    for a, b in pairwise(history):
        pa, pb = a.get("params") or {}, b.get("params") or {}
        for k, (lo, hi) in bounds.items():
            if k not in pa or k not in pb:
                continue
            prev, cur = float(pa[k]), float(pb[k])
            rel = abs(cur - prev) / max(abs(prev), 1e-12)
            in_b = lo - 1e-12 <= cur <= hi + 1e-12
            c_ok = rel <= max_step_pct + 1e-9 and in_b
            checks.append({"round": b.get("round"), "param": k, "prev": prev, "cur": cur,
                           "rel_step": rel, "in_bounds": in_b, "ok": c_ok})
            ok = ok and c_ok
    return {"checks": checks, "ok": ok}


def eps_eff_from_port_beta(path: Path, f0_ghz: float = F0) -> float:
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    bf = np.array([float(r[0]) for r in rows])
    bb = np.array([float(r[1]) for r in rows])
    sel = (bf >= 0.96 * f0_ghz * 1e9) & (bf <= 1.04 * f0_ghz * 1e9)
    beta = float(np.median(bb[sel]))
    return (beta * 299792458.0 / (2 * np.pi * f0_ghz * 1e9)) ** 2


def make_live_sampler(model: str, freq_range: tuple[float, float],
                      objectives: list[dict], *, mesh_resolution_mm: float,
                      work_root: Path):
    """`autotune_service._make_openems_sampler` 的逐行同构副本，仅多
    `extra_params={"cache": False}`：绕开 runs/openems_cache 全局缓存（脚本逐字节
    相同即命中，引擎不启动），保证本冒烟至少一次**活跑**并产出 port_beta.csv。
    经 autotune_loop(sampler_fn=...) 设计好的注入点接入，内核零改动。"""
    import skrf

    from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
    from rfauto.adapters.openems_solver import OpenEMSSolver
    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.service.autotune_service import _s11_valley_ghz
    from rfauto.service.calibration_service import _template_for

    template = _template_for(model)
    objs = [Objective(**o) for o in objectives]

    def run(params: dict[str, float]) -> dict:
        work = work_root / f"pt_{int(time.time() * 1000) % 10**10}"
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type="openems", exe_path=resolve_openems_exe(),
            working_dir=str(work), freq_range_ghz=tuple(freq_range),
            mesh_resolution_mm=mesh_resolution_mm,
            extra_params={"cache": False, "solve_timeout_s": 3600}))
        if not solver.connect():
            raise RuntimeError("openEMS 不可用（exe 未找到）")
        if not solver.build_geometry({"template": template, "params": params}):
            raise RuntimeError("openEMS 几何构建失败")
        result = solver.solve()
        if not result.success or result.s_params is None:
            raise RuntimeError(f"openEMS 求解失败: {result.message}")
        network = skrf.Network(
            frequency=skrf.Frequency(result.freq_ghz[0], result.freq_ghz[-1],
                                     len(result.freq_ghz), unit="ghz"),
            s=result.s_params, z0=50.0)
        return {"metrics": SpecEvaluator.compute_metrics(network, objs),
                "valley_ghz": _s11_valley_ghz(network)}

    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", default=RECIPE)
    parser.add_argument("--budget", type=int, default=2)
    parser.add_argument("--mesh", type=float, default=0.0)
    parser.add_argument("--max-step", type=float, default=0.2)
    parser.add_argument("--force-live", action="store_true", default=True,
                        help="缺省通道命中缓存时追加一轮 cache=False 活跑（缺省开）")
    parser.add_argument("--no-force-live", dest="force_live", action="store_false")
    args = parser.parse_args(argv)

    import yaml

    recipe = yaml.safe_load(Path(args.recipe).read_text(encoding="utf-8"))
    bounds = {k: (float(v["low"]), float(v["high"]))
              for k, v in (recipe.get("optimization", {}).get("params") or {}).items()}
    stage2 = json.loads(Path(STAGE2).read_text(encoding="utf-8"))
    before = set(glob.glob("runs/autotune_work_*"))

    t0 = time.time()
    res = autotune_loop(args.recipe, budget=args.budget,
                        mesh_resolution_mm=args.mesh, max_step_pct=args.max_step)
    wall = time.time() - t0
    assert res.get("ok"), res.get("errors")
    history = list(res.get("history") or [])
    work_dirs = sorted(set(glob.glob("runs/autotune_work_*")) - before)
    pt_dirs = sorted(p for w in work_dirs for p in glob.glob(f"{w}/pt_*"))
    live = [p for p in pt_dirs if Path(p, "fdtd").is_dir()]
    default_channel = {"run_id": res.get("run_id"), "verdict": res.get("verdict"),
                       "rounds_used": res.get("rounds_used"), "wall_s": round(wall, 1),
                       "live_engine_pt_dirs": list(live), "cache_replay": not live}

    res_live = None
    if args.force_live and not live:
        from rfauto.core.state import generate_run_id

        work_root = Path("runs") / f"autotune_work_{generate_run_id()}_live"
        sampler = make_live_sampler(str(recipe.get("model", "")),
                                    tuple(recipe["setup"]["freq_range_ghz"]),
                                    list(recipe["objectives"]),
                                    mesh_resolution_mm=args.mesh, work_root=work_root)
        t1 = time.time()
        res_live = autotune_loop(args.recipe, sampler_fn=sampler, budget=args.budget,
                                 mesh_resolution_mm=args.mesh, max_step_pct=args.max_step)
        wall = time.time() - t1
        assert res_live.get("ok"), res_live.get("errors")
        history = list(res_live.get("history") or [])
        work_dirs = [str(work_root)]
        pt_dirs = sorted(glob.glob(f"{work_root}/pt_*"))
        live = [p for p in pt_dirs if Path(p, "fdtd").is_dir()]
        res = res_live

    r1 = history[0] if history else {}
    w1 = float((r1.get("params") or {}).get("w_mm", float("nan")))
    m1 = r1.get("metrics") or {}
    s11_max = m1.get("s11_db_max_in_band", m1.get("s11_db"))
    s2_s11 = float(stage2["em_anchor"]["s11_max_db"])
    s2_eps = float(stage2["em_anchor"]["eps_engine"])
    s2_ref = float(stage2["em_anchor"]["eps_ref"])

    eps_engine = None
    beta_paths = [p for p in pt_dirs if Path(p, "port_beta.csv").exists()]
    if beta_paths:
        eps_engine = eps_eff_from_port_beta(Path(beta_paths[0]) / "port_beta.csv")
    d_eps_pct = (eps_engine / s2_ref - 1) * 100 if eps_engine is not None else None

    steps = step_within_bounds(history, bounds, args.max_step)
    eps_ok: bool | None = None
    if live:
        eps_ok = eps_engine is not None and abs(eps_engine - s2_eps) / s2_eps <= 0.01
    gates = {
        "verdict": {"value": res.get("verdict"), "ok": res.get("verdict") in ("PASS", "FAIL")},
        "round1_nominal_w": {"value": w1, "ok": abs(w1 - 0.849) < 1e-9},
        "round1_s11_max_vs_stage2": {"value": s11_max, "stage2": s2_s11,
                                     "ok": s11_max is not None and abs(float(s11_max) - s2_s11) <= 1.0},
        "eps_eff_vs_stage2": {"value": eps_engine, "delta_pct_vs_hj": d_eps_pct,
                              "stage2_eps_engine": s2_eps, "stage2_delta_pct": stage2["em_anchor"]["delta_pct"],
                              "ok": eps_ok,
                              "note": None if live else "缓存回放：引擎未启动，无 port_beta.csv，εeff 不可再导出"},
        "fix_steps_bounded": steps,
    }
    hard_ok = all([gates["verdict"]["ok"], gates["round1_nominal_w"]["ok"],
                   gates["round1_s11_max_vs_stage2"]["ok"], steps["ok"]])
    if not hard_ok:
        verdict = "FAIL"
    elif not live:
        verdict = "PARTIAL"  # 判据全过但为缓存回放（引擎未活跑），如实降级
    else:
        verdict = "PASS" if eps_ok else "FAIL"

    print(f"autotune verdict={res.get('verdict')} rounds={res.get('rounds_used')} run_id={res.get('run_id')} "
          f"wall={wall:.0f}s live_engine_runs={len(live)}/{len(pt_dirs)}")
    print(f"round1 w={w1} s11_max={s11_max} (stage2 {s2_s11}) eps_engine={eps_engine} (stage2 {s2_eps}) "
          f"steps={json.dumps(steps)}")
    print(f"B6_AUTOTUNE_REAL_{verdict}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    result = {
        "item": "openems-real-smoke-bundle/⑤b6_autotune_real", "verdict": verdict,
        "equivalent_cli": f"rfauto autotune {args.recipe} --budget {args.budget} --json",
        "default_channel": default_channel,
        "live_channel": {"used": res_live is not None,
                         "how": "autotune_loop(sampler_fn=make_live_sampler(cache=False))：内核缺省采样器逐行同构副本，仅关全局缓存"},
        "autotune": {k: res.get(k) for k in ("run_id", "run_dir", "verdict", "budget", "rounds_used",
                                             "best", "final_params", "elapsed_s")},
        "history": history, "wall_s": round(wall, 1),
        "work_dirs": work_dirs, "live_engine_pt_dirs": live, "all_pt_dirs": pt_dirs,
        "stage2_reference": stage2["em_anchor"], "gates": gates,
    }
    (OUT / "_smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
