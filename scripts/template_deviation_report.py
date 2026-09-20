#!/usr/bin/env python3
"""方向 2 验收：每模板 fake vs openEMS 标称点偏差报告（≤3dB 冒烟级一致）。

对给定模板在标称设计点分别用 fake 与 openEMS 求值，输出带内 |ΔS11| dB
统计到 runs/template_deviation/。用法：
    python scripts/template_deviation_report.py wilkinson patch [--mesh 1.0]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np


def fake_cost_curve(recipe_data: dict) -> tuple[np.ndarray, np.ndarray]:
    """fake 档求 |S11| dB 曲线。"""
    from rfauto.adapters.fake_adapter import FakeAdapter
    from rfauto.models.registry import get as get_plugin

    plugin_cls = get_plugin(recipe_data["model"])
    adapter = FakeAdapter(
        freq_ghz=(*tuple(recipe_data["setup"]["freq_range_ghz"]), recipe_data["setup"]["points"]),
        n_ports=plugin_cls.n_ports,
        model_type=plugin_cls.fake_model_type,
    )
    adapter.connect({})
    try:
        plugin = plugin_cls()
        plugin.build(adapter, plugin.params_model(**recipe_data["params_nominal"]))
        report = adapter.solve("main_setup")
        if not report.success:
            raise RuntimeError("fake solve failed")
        net = adapter.get_sparams()
        return np.asarray(net.f), 20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12)
    finally:
        adapter.close()


def openems_curve(recipe_data: dict, mesh: float, out_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """openEMS 真跑 |S11| dB 曲线（子进程 + 绑定，同 openems_solver 模式）。"""
    from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
    from rfauto.adapters.openems_solver import OpenEMSSolver

    cfg = EMSolverConfig(
        solver_type="openems",
        exe_path=resolve_openems_exe(),
        working_dir=str(out_dir),
        freq_range_ghz=tuple(recipe_data["setup"]["freq_range_ghz"]),
        mesh_resolution_mm=mesh,
        # 真实谐振结构（高 Q）跑满衰减远超默认 2.78h 上限，参考曲线一次性放开
        extra_params={"solve_timeout_s": 8 * 3600},
    )
    solver = OpenEMSSolver(cfg)
    if not solver.connect():
        raise RuntimeError("openEMS connect failed（exe/绑定不可用）")
    if not solver.build_geometry({
        "template": recipe_data["template"],
        "params": recipe_data["params_nominal"],
    }):
        raise RuntimeError("openEMS build_geometry failed")
    result = solver.solve()
    if not result.success:
        raise RuntimeError(f"openEMS solve failed: {result.message}")
    return np.asarray(result.freq_ghz), 20 * np.log10(np.abs(result.s_params[:, 0, 0]) + 1e-12)


def compare(template: str, mesh: float, base_dir: Path, reuse_reference: bool = False) -> dict:
    from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL

    meta = TEMPLATE_META[template]
    f0 = meta["f0_ghz"]
    recipe_data = {
        "template": template,
        "model": {"wilkinson": "wilkinson_power_divider", "patch": "patch_antenna",
                  "branchline": "branchline_coupler"}.get(template, template),
        "setup": {"freq_range_ghz": [f0 - 0.5, f0 + 0.5], "points": 101},
        "params_nominal": TEMPLATE_NOMINAL[template],
    }
    run_dir = base_dir / template
    run_dir.mkdir(parents=True, exist_ok=True)
    ref_csv = Path("knowledge") / "reference" / "openems_nominal" / f"{template}_s11.csv"

    t0 = time.time()
    f_fake, db_fake = fake_cost_curve(recipe_data)
    if reuse_reference:
        # 离线模式：复用已入库参考曲线（校准迭代验证不重跑 openEMS）
        if not ref_csv.exists():
            return {"template": template, "error": f"参考曲线不存在: {ref_csv}", "pass": False}
        with open(ref_csv, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))[1:]
        data = np.array([[float(x) for x in r] for r in rows])
        f_ems, db_ems = data[:, 0], data[:, 1]
    else:
        f_ems, db_ems = openems_curve(recipe_data, mesh, run_dir / "fdtd")
        # openEMS 参考曲线入库（联合校准数据源；多模态审计后的正确拓扑曲线）
        ref_dir = ref_csv.parent
        ref_dir.mkdir(parents=True, exist_ok=True)
        with open(ref_csv, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["freq_ghz", "s11_db"])
            for fi, di in zip(f_ems, db_ems, strict=True):
                w.writerow([f"{fi:.6f}", f"{di:.4f}"])
    # FakeAdapter 走 skrf Network（f 单位 Hz）；openEMS 求解器返回 GHz——统一到 GHz
    f_fake = np.asarray(f_fake, dtype=float) / 1e9
    f_ems = np.asarray(f_ems, dtype=float)

    # 带内偏差（f0±5%）在公共频率网格上插值对齐（双方采样率不同的正确比较方式）
    # 无源器件 |S11|≤1：openEMS 带缘激励衰减 -20dB 处的除法伪差（|S11|>1，
    # 实测 +31dB 尖峰）为无效样本，剔除后再插值（保留它们会污染偏差统计）
    db_fake = np.minimum(db_fake, 0.0)
    valid = db_ems <= 0.0
    f_ems, db_ems = f_ems[valid], db_ems[valid]
    lo, hi = f0 * 0.95, f0 * 1.05
    grid = np.linspace(max(lo, f_ems.min(), f_fake.min()),
                       min(hi, f_ems.max(), f_fake.max()), 101)
    fake_i = np.interp(grid, f_fake, db_fake)
    ems_i = np.interp(grid, f_ems, db_ems)
    dev = np.abs(fake_i - ems_i)
    entry = {
        "template": template,
        "f0_ghz": f0,
        "band_ghz": [lo, hi],
        "mesh_resolution_mm": mesh,
        "reference_mode": "reuse" if reuse_reference else "fresh_openems",
        "fake_min_s11_db": round(float(db_fake.min()), 2),
        "openems_min_s11_db": round(float(db_ems.min()), 2),
        "max_abs_delta_db": round(float(dev.max()), 2) if dev.size else None,
        "mean_abs_delta_db": round(float(dev.mean()), 2) if dev.size else None,
        "threshold_db": 3.0,
        "pass": bool(dev.size and dev.max() <= 3.0),
        "elapsed_s": round(time.time() - t0, 1),
    }
    (run_dir / "deviation.json").write_text(
        json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description="Direction 2 fake vs openEMS deviation report")
    parser.add_argument("templates", nargs="+", choices=["wilkinson", "patch", "branchline", "dipole", "stepped_impedance", "coupled_line"])
    parser.add_argument("--mesh", type=float, default=1.0)
    parser.add_argument("--out", default="runs/template_deviation")
    parser.add_argument("--reuse-reference", action="store_true",
                        help="离线模式：复用 knowledge/reference 曲线，不重跑 openEMS")
    args = parser.parse_args()

    base_dir = Path(args.out)
    base_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for t in args.templates:
        print(f"=== {t} ===", flush=True)
        try:
            entry = compare(t, args.mesh, base_dir, reuse_reference=args.reuse_reference)
        except Exception as e:
            entry = {"template": t, "error": str(e), "pass": False}
            print(f"  ERROR: {e}", flush=True)
        entries.append(entry)
        print(f"  {json.dumps(entry, ensure_ascii=False)}", flush=True)

    report = ["# 模板 fake vs openEMS 偏差报告（方向 2 验收）", "",
              "| 模板 | f0 (GHz) | fake min S11 | openEMS min S11 | max |Δ| dB | mean |Δ| dB | 阈值 | 结论 |",
              "|---|---|---|---|---|---|---|---|"]
    for e in entries:
        if "error" in e:
            report.append(f"| {e['template']} | - | - | - | - | - | 3.0 | ERROR: {e['error'][:60]} |")
        else:
            report.append(
                f"| {e['template']} | {e['f0_ghz']} | {e['fake_min_s11_db']} | "
                f"{e['openems_min_s11_db']} | {e['max_abs_delta_db']} | "
                f"{e['mean_abs_delta_db']} | 3.0 | {'PASS' if e['pass'] else 'FAIL'} |")
    (base_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    (base_dir / "report.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = all(e.get("pass") for e in entries)
    print(f"\nreport → {base_dir}/report.md  overall: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
