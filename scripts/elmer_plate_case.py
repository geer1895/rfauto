"""A4 Elmer 1-D 均匀热源平板真机验收脚本（闭式温度分布 ≤1%）。

用途：真机跑 ElmerSolver，把平板温度剖面与独立解析解（左端 Dirichlet、
右端绝热、均匀体热源）逐点对照，打印实测偏差并判定验收口径。

用法（工作区根目录；路径用正斜杠）：
    .venv/Scripts/python.exe scripts/elmer_plate_case.py
    .venv/Scripts/python.exe scripts/elmer_plate_case.py --out runs/a4_elmer --keep
    .venv/Scripts/python.exe scripts/elmer_plate_case.py --thickness-mm 20 --q 5e4

默认在系统临时目录建工作区，跑完自动删除（--out / --keep 可保留现场）。
退出码：0=验收通过（≤1%），1=偏差超 1%，2=Elmer 不可用/连接失败，
3=建模失败，4=求解失败。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rfauto.adapters.elmer_adapter import (  # noqa: E402
    ElmerAdapter,
    normalize_slab_params,
    resolve_elmer_bin,
    slab_temperature_closed_form,
)
from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType  # noqa: E402

ACCEPTANCE_REL_TOL = 0.01  # WP4.4d：闭式温度分布 ≤1%


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Elmer 1-D 均匀热源平板闭式对照")
    parser.add_argument("--exe", default=None, help="ElmerSolver.exe 路径（默认自动解析）")
    parser.add_argument("--thickness-mm", type=float, default=None, help="平板厚度 L（mm）")
    parser.add_argument("--width-mm", type=float, default=None, help="平板宽度（mm）")
    parser.add_argument("--n-x", type=int, default=None, help="x 向网格分段数")
    parser.add_argument("--n-y", type=int, default=None, help="y 向网格分段数")
    parser.add_argument("--q", type=float, default=None, help="体热源 q（W/m³）")
    parser.add_argument("--k", type=float, default=None, help="热导率 k（W/(m·K)）")
    parser.add_argument("--t0", type=float, default=None, help="固定端温度 T0（K）")
    parser.add_argument("--timeout", type=float, default=600.0, help="求解超时（s）")
    parser.add_argument("--out", default=None, help="保留现场的输出目录（默认临时目录）")
    parser.add_argument("--keep", action="store_true", help="保留临时工作区")
    parser.add_argument("--json", action="store_true", help="额外打印 JSON 结果")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    overrides = {
        "thickness_mm": args.thickness_mm,
        "width_mm": args.width_mm,
        "n_x": args.n_x,
        "n_y": args.n_y,
        "heat_source_w_m3": args.q,
        "heat_conductivity_w_mk": args.k,
        "t0_k": args.t0,
    }
    spec = normalize_slab_params({k: v for k, v in overrides.items() if v is not None})

    solver_exe = resolve_elmer_bin(args.exe)
    if solver_exe is None:
        print("Elmer 不可用：未找到 ElmerSolver.exe（--exe / RFAUTO_ELMER_BIN / ELMER_HOME）")
        return 2
    print(f"ElmerSolver: {solver_exe}")

    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="elmer_plate_"))
    keep = bool(args.keep or args.out)
    try:
        cfg = EMSolverConfig(
            solver_type=EMSolverType.ELMER,
            exe_path=str(solver_exe),
            working_dir=str(out),
            extra_params={"solve_timeout_s": args.timeout},
        )
        adapter = ElmerAdapter(cfg)
        if not adapter.connect():
            print(f"连接失败：{adapter.last_message}")
            return 2
        if not adapter.build_geometry(spec):
            print(f"建模失败：{adapter.last_message}")
            return 3
        result = adapter.solve()
        if not result.success:
            print(f"求解失败：{result.message}")
            return 4

        x = result.field_data["x_m"]
        t_num = result.field_data["temperature_k"]
        L = spec["thickness_mm"] / 1000.0
        t_ref = slab_temperature_closed_form(
            x, L, spec["heat_source_w_m3"], spec["heat_conductivity_w_mk"], spec["t0_k"])
        rep = adapter.deviation_report()

        print("")
        print(f"网格：n_x={int(spec['n_x'])} n_y={int(spec['n_y'])}  "
              f"L={spec['thickness_mm']}mm  W={spec['width_mm']}mm  "
              f"q={spec['heat_source_w_m3']} W/m3  k={spec['heat_conductivity_w_mk']} W/(m.K)  "
              f"T0={spec['t0_k']} K")
        print(f"闭式峰值温升 qL^2/2k = {spec['heat_source_w_m3'] * L * L / (2 * spec['heat_conductivity_w_mk']):.6g} K")
        print("")
        print(f"{'x_mm':>10} {'T_elmer_K':>16} {'T_closed_K':>16} {'abs_err_K':>14}")
        step = max(1, x.size // 11)
        for i in range(0, x.size, step):
            print(f"{x[i] * 1000:>10.4f} {t_num[i]:>16.9f} {t_ref[i]:>16.9f} "
                  f"{abs(t_num[i] - t_ref[i]):>14.3e}")
        if (x.size - 1) % step:
            i = x.size - 1
            print(f"{x[i] * 1000:>10.4f} {t_num[i]:>16.9f} {t_ref[i]:>16.9f} "
                  f"{abs(t_num[i] - t_ref[i]):>14.3e}")
        print("")
        print(f"max|T_elmer - T_closed| = {rep['max_abs_deviation_k']:.6e} K")
        print(f"相对偏差（归一化到温升 {rep['reference_rise_k']:.6g} K） = "
              f"{rep['max_relative_deviation'] * 100:.6g} %")
        passed = rep["max_relative_deviation"] <= ACCEPTANCE_REL_TOL
        print(f"WP4.4d 验收（≤{ACCEPTANCE_REL_TOL * 100:.0f}%）："
              f"{'PASS' if passed else 'FAIL'}")
        print(f"求解墙钟：{result.wall_time_s:.3f} s")
        if args.json:
            print(json.dumps({
                "spec": spec,
                "max_abs_deviation_k": rep["max_abs_deviation_k"],
                "reference_rise_k": rep["reference_rise_k"],
                "max_relative_deviation": rep["max_relative_deviation"],
                "pass_1pct": passed,
                "n_points": rep["n_points"],
                "wall_time_s": result.wall_time_s,
            }, ensure_ascii=False))
        return 0 if passed else 1
    finally:
        if not keep:
            shutil.rmtree(out, ignore_errors=True)
        elif out.exists():
            print(f"现场保留：{out}")


if __name__ == "__main__":
    raise SystemExit(main())
