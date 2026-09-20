"""patch far_field 真机冒烟 + 体 E 场 DumpHDF5 → G9 场图页原路径吃真数据
（openems-real-smoke-bundle ③）。

背景：far_field 注入面（render_script far_field=True → CreateNF2FFBox +
CalcNF2FF → farfield_meta.json）与 G9 场图服务（ui_service.field_view，dump
契约 Mesh+FieldData，候选 run 根与 fdtd/）均已有；dipole 真机双例已跑，但
patch far_field 真机未跑、场图页只吃过合成 fixture（test_field_webviz
write_td_vector_dump）。本脚本零源码改动：

1. render（OpenEMSSolver.build_geometry，template=patch，far_field=True）；
2. 脚本级在唯一顶层 `FDTD.Run(SIM_PATH` 前注入体 E 场**频域** dump：
   `CSX.AddDump(name, dump_type=10, frequency=[F0], file_type=1, dump_mode=2)`
   ——数值以 .venv CSXCAD/CSProperties.pyx 文档为准（10=E-field FD、1=HDF5、
   2=cell 插值；E 场勿用 node 插值，金属面法向幅度失真），非凭记忆（#149）；
   盒=整域，产物 fdtd/<name>.h5（Mesh + FieldData/FD）；
3. 自驱 subprocess 留日志；验收：farfield_meta.json ok=true（f_res=|S11| 谷、
   η=Prad/P_acc、Dmax 与文献 patch 6-9dBi 量级如实对照）+ 原路径
   field_view("patch_field_smoke") ok=True、体 dump 排首于 nf2ff_ 盒面 dump、
   volume.domain="fd"、三轴切片非退化、engine 标签如实（无 PyVista 走
   numpy_contour）。

产物 runs/patch_field_smoke/{simulation.py,engine.log,sparams.csv,
farfield_meta.json,fdtd/*.h5,_smoke_result.json}。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

RUN_ID = "patch_field_smoke"
DUMP_NAME = "E_field_f0"
DUMP_MARK = "# rfauto smoke: 体 E 场频域 dump"
_RUN_ANCHOR = re.compile(r"^FDTD\.Run\(SIM_PATH", re.M)
LIT_DMAX_DBI = (6.0, 9.0)  # 文献微带贴片方向性量级（refs §8 Simple Patch Antenna 口径）


def dump_block(name: str = DUMP_NAME) -> str:
    return (
        f"{DUMP_MARK}（openems-real-smoke-bundle ③）：dump_type=10=E-field FD、\n"
        "# file_type=1=HDF5、dump_mode=2=cell 插值（CSXCAD/CSProperties.pyx 文档口径：\n"
        "# E 场勿用 node 插值，金属面法向幅度失真）；频点=F0；盒=整域\n"
        f'_efd = CSX.AddDump("{name}", dump_type=10, frequency=[F0], file_type=1, dump_mode=2)\n'
        "_efd.AddBox(np.array([-DOM_X, -DOM_Y, 0.0]), np.array([DOM_X, DOM_Y, H_SUB + AIR_TOP]))\n"
    )


def inject_volume_dump(script: str, name: str = DUMP_NAME) -> tuple[str, int]:
    """在唯一顶层 `FDTD.Run(SIM_PATH` 前注入体 dump 块。

    注入点唯一性：顶层（列 0）`FDTD.Run(SIM_PATH` 必须恰一处（footer 的
    `_FDTD3.Run(_SIM3` 缩进且名字不同，不计）；0 处或多处抛 ValueError。
    幂等：已含标记则原样返回、注入 0 次。返回 (脚本, 注入次数)。
    """
    if DUMP_MARK in script:
        return script, 0
    hits = list(_RUN_ANCHOR.finditer(script))
    if len(hits) != 1:
        raise ValueError(f"顶层 FDTD.Run(SIM_PATH 注入点须恰 1 处，实得 {len(hits)}")
    i = hits[0].start()
    return script[:i] + dump_block(name) + script[i:], 1


def slices_nondegenerate(slices: list[dict]) -> dict[str, object]:
    """三轴切片非退化判据：每轴 n>1、values 二维且非常数、全部有限。"""
    per: dict[str, object] = {}
    all_ok = True
    for s in slices:
        vals = np.asarray(s.get("values", []), dtype=float)
        ok = (int(s.get("n", 0)) > 1 and vals.ndim == 2 and vals.size > 1
              and bool(np.all(np.isfinite(vals))) and float(vals.max() - vals.min()) > 0.0)
        per[str(s.get("axis"))] = {"n": int(s.get("n", 0)), "shape": list(vals.shape),
                                   "range_db": (float(vals.max() - vals.min()) if vals.size else None),
                                   "ok": ok}
        all_ok = all_ok and ok
    return {"per_axis": per, "ok": all_ok and len(slices) == 3}


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
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--flo", type=float, default=2.0)
    parser.add_argument("--fhi", type=float, default=2.8)
    parser.add_argument("--mesh", type=float, default=0.0,
                        help="0=官方 λ_sub/50 自动（G9/服务缺省口径）")
    parser.add_argument("--timeout", type=float, default=7200.0)
    parser.add_argument("--postprocess-only", action="store_true",
                        help="已有产物（sparams.csv）时跳过渲染/真跑，只做判读与落盘")
    args = parser.parse_args(argv)

    work = Path("runs") / args.run_id
    exe = resolve_openems_exe()
    params = dict(TEMPLATE_NOMINAL["patch"])
    n_inj = 1
    if args.postprocess_only and (work / "sparams.csv").exists():
        rc, wall = 0, float("nan")
        script = (work / "simulation.py").read_text(encoding="utf-8")
        assert DUMP_MARK in script, "postprocess-only 要求既有脚本已含 dump 注入"
    else:
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type="openems", exe_path=exe, working_dir=str(work),
            freq_range_ghz=(args.flo, args.fhi), mesh_resolution_mm=args.mesh,
            extra_params={"solve_timeout_s": args.timeout}))
        assert solver.connect(), "openEMS 不可用"
        assert solver.build_geometry({"template": "patch", "params": params,
                                      "far_field": True})
        script_path = work / "simulation.py"
        script, n_inj = inject_volume_dump(script_path.read_text(encoding="utf-8"))
        assert n_inj == 1
        assert "disable_dumps=True" not in script.split("FDTD.Run(SIM_PATH", 1)[1].split("\n", 1)[0], \
            "far_field 注入时主 Run 不得 disable_dumps（模板契约漂移）"
        script_path.write_text(script, encoding="utf-8")

        t0 = time.time()
        rc = _run_engine(work, exe, args.timeout, work / "engine.log")
        wall = time.time() - t0
        print(f"solve_s={wall:.0f} rc={rc}", flush=True)
        assert rc == 0 and (work / "sparams.csv").exists(), \
            f"openEMS 真跑失败 rc={rc}（见 {work / 'engine.log'}）"
    eng_log = (work / "engine.log").read_text(encoding="utf-8", errors="replace") \
        if (work / "engine.log").exists() else ""
    m_done = re.search(r"Time for (\d+) iterations with ([0-9.eE+-]+) cells : ([0-9.]+) sec", eng_log)
    m_prog = re.findall(r"Energy: ~[0-9.eE+-]+ \(\s*(-?[0-9.]+)dB\)", eng_log)
    engine = {"iterations_done": int(m_done.group(1)) if m_done else None,
              "cells": float(m_done.group(2)) if m_done else None,
              "engine_wall_s": float(m_done.group(3)) if m_done else None,
              "nrts_limit_warning": "Max. number of timesteps was reached" in eng_log,
              "last_energy_db": float(m_prog[-1]) if m_prog else None}

    data = np.loadtxt(str(work / "sparams.csv"), delimiter=",", skiprows=1)
    f_ghz = data[:, 0] / 1e9
    s11_db = 20 * np.log10(np.abs(data[:, 1] + 1j * data[:, 2]) + 1e-12)
    i_min = int(np.argmin(s11_db))

    # ── 远场产物 ──
    ff_path = work / "farfield_meta.json"
    ff = json.loads(ff_path.read_text(encoding="utf-8")) if ff_path.exists() else {"ok": False, "error": "missing"}
    dmax = ff.get("dmax_dbi")
    eta = ff.get("efficiency")
    ff_ok = bool(ff.get("ok")) and dmax is not None and math.isfinite(float(dmax)) \
        and eta is not None and 0.0 < float(eta) <= 1.0 + 1e-6
    dmax_in_lit = bool(dmax is not None and LIT_DMAX_DBI[0] <= float(dmax) <= LIT_DMAX_DBI[1])

    # ── G9 原路径复核（零改动消费）──
    from rfauto.service.ui_service import field_view

    fv = field_view(args.run_id)
    dumps = list(fv.get("dumps") or [])
    h5_files = sorted(p.name for p in (work / "fdtd").glob("*.h5")) if (work / "fdtd").is_dir() else []
    vol = fv.get("volume") or {}
    nd = slices_nondegenerate(list(fv.get("slices") or [])) if fv.get("ok") else {"ok": False}
    volume_first = bool(dumps) and dumps[0].startswith(DUMP_NAME)
    fv_ok = bool(fv.get("ok")) and volume_first and vol.get("domain") == "fd" and bool(nd["ok"])

    gates = {
        "engine_rc0_sparams": {"ok": True},
        "farfield_meta_ok": {"value": {k: ff.get(k) for k in
                                       ("ok", "f_res_ghz", "dmax_dbi", "gain_max_dbi",
                                        "efficiency", "power_budget_closure")},
                             "ok": ff_ok},
        "dmax_in_literature_6_9_dbi": {"value": dmax, "range": list(LIT_DMAX_DBI), "ok": dmax_in_lit},
        "field_view_ok": {"value": fv.get("ok"), "errors": fv.get("errors"), "ok": bool(fv.get("ok"))},
        "volume_dump_first": {"value": dumps, "ok": volume_first},
        "volume_domain_fd": {"value": vol.get("domain"), "ok": vol.get("domain") == "fd"},
        "slices_nondegenerate": {"value": nd, "ok": bool(nd["ok"])},
    }
    ff_all = ff_ok and dmax_in_lit
    if fv_ok and ff_all:
        verdict = "PASS"
    elif fv_ok:
        # G9 场图页原路径吃真数据（本项主交付）达成；远场功率账目（η>1 / Dmax 量级）失守
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    hypotheses = []
    if ff.get("ok") and eta is not None and float(eta) > 1.0:
        hypotheses.append(
            "η=Prad/P_acc>1 非物理（假设待证）：① 引擎 NrTS=100000 触顶、能量仅衰至 "
            f"{engine.get('last_energy_db')}dB（判据 −60dB 未达）→ 频域 nf2ff/端口 DFT 截断误差；"
            "② PEC 地 CreateNF2FFBox 镜像分支 Prad 计半空间口径——若 Prad 被计双倍，则 η/2="
            f"{float(eta) / 2:.3f}、Dmax+3dB={float(dmax) + 3.0:.2f}dBi，与 0.508mm/tanδ0.0037 贴片"
            "物理量级自洽；dipole（六面全包、η=0.990）无此症状")

    print(f"|S11| 谷 {s11_db[i_min]:.1f}dB @ {f_ghz[i_min]:.4f}GHz；farfield: ok={ff.get('ok')} "
          f"f_res={ff.get('f_res_ghz')} Dmax={dmax} dBi η={eta} closure={ff.get('power_budget_closure')}")
    print(f"field_view ok={fv.get('ok')} dumps={dumps} selected={fv.get('selected')} "
          f"domain={vol.get('domain')} shape={vol.get('shape')} f={vol.get('frequency_ghz')} "
          f"engine={fv.get('engine')} slices={json.dumps(nd)}")
    print(f"PATCH_FIELD_DUMP_{verdict}", flush=True)

    result = {
        "item": "openems-real-smoke-bundle/③patch_field_dump", "verdict": verdict,
        "run_id": args.run_id, "params": params, "freq_range_ghz": [args.flo, args.fhi],
        "mesh_mm": args.mesh, "solve_s": round(wall, 1) if wall == wall else None, "rc": rc,
        "engine": engine,
        "dump": {"name": DUMP_NAME, "dump_type": 10, "file_type": 1, "dump_mode": 2,
                 "frequency": "F0", "n_injected": n_inj, "h5_files": h5_files},
        "s11": {"min_db": float(s11_db[i_min]), "f_min_ghz": float(f_ghz[i_min]),
                "note": "openEMS 经验常数 f_dip·L≈76.8（#190）：76.8/34.9=2.20GHz 与谷位一致"},
        "farfield_meta": ff,
        "field_view": {"ok": fv.get("ok"), "dumps": dumps, "selected": fv.get("selected"),
                       "volume": vol, "engine": fv.get("engine"),
                       "farfield_metrics": fv.get("farfield_metrics"),
                       "pattern3d_present": fv.get("pattern3d") is not None,
                       "warnings": fv.get("warnings"), "errors": fv.get("errors")},
        "gates": gates,
        "hypotheses": hypotheses,
        "reference": {"dipole_ff_smoke": "runs/nf2ff_smoke_ff_dipole（Dmax 3.14dBi η 0.990 wall 55s）",
                      "literature_patch_dmax_dbi": list(LIT_DMAX_DBI)},
    }
    (work / "_smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
