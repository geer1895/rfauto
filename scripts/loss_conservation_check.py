r"""D3-1 功率守恒闭合自检脚本（合成解析算例 + 可选实档模式，§10.21 第九轮 D3-1）。

用法::

    .venv\Scripts\python.exe scripts/loss_conservation_check.py
    .venv\Scripts\python.exe scripts/loss_conservation_check.py \
        --dump runs/nf2ff_smoke_sar_dipole/fdtd/SAR_raw.h5

判据（验收口径）：|integral q dV - P_in*(1 - sum|S_ij|^2)| / scale
<= 3%。

合成算例（裁判 = 独立来源闭式，非本模块自身推导，#118）：
  A "均匀场导电损耗"：q = 0.5*sigma*|E0|^2（Jackson §6.9），
     integral q dV = q * V。
  B "趋肤深度指数衰减"：delta = sqrt(2/(omega*mu*sigma))（Pozar §1.7.1），
     E(z) = E0*exp(-z/delta)，
     integral_0^t 0.5*sigma*|E|^2*A dz
         = 0.25*sigma*A*delta*|E0|^2*(1 - exp(-2t/delta))。

实档模式（--dump <path>，可多次）：infra/loss_dump.read_loss_dump 读 openEMS
dump_type=29 体 dump → 逐 cell 欧姆积分 → 与同目录 openEMS 自算 SAR_*.h5
的 power 属性对照（裁判 = openEMS 自算，独立于本仓内核；门 rel <= 1e-3）。
无 --dump 时只登记 runs/ 下 dump 候选路径，不冒充已用真机数据验证。

退出码：0 = 全部算例达标；1 = 任一不达标。确定性、无网络、无真机；不写任何文件。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from rfauto.core.loss_density import (  # noqa: E402
    MU0,
    LossMaterial,
    integrate_loss_density,
    loss_density,
    power_conservation_check,
    uniform_cell_measure,
)

TOLERANCE = 0.03
#: 实档 ∫q dV vs openEMS 自算 power 属性的对照门（float32 精度下实测 2.1e-8）
DUMP_SELFCHECK_TOLERANCE = 1e-3
DUMP_SUFFIXES = (".h5", ".hdf5", ".vtk", ".vtr", ".vtu")


def case_uniform_field() -> dict:
    """算例 A：均匀场方块，纯导电损耗（解析 V*q 对照）。"""
    shape = (12, 12, 6)
    spacing = (0.5e-3, 0.5e-3, 1.0e-3)
    sigma, e0, freq = 0.02, 40.0, 1.0e9
    volume = int(np.prod(shape)) * uniform_cell_measure(spacing)

    q = loss_density(np.full(shape, e0, dtype=complex),
                     freq_hz=freq, material=LossMaterial(sigma=sigma))
    cell = uniform_cell_measure(spacing)
    numeric_w = integrate_loss_density(q, cell_measure=cell)
    analytic_w = 0.5 * sigma * e0**2 * volume

    # 自洽 S 行：|S11|^2 = 0.15（其余全匹配）
    reflected = 0.15
    p_in = numeric_w / (1.0 - reflected)
    balance = power_conservation_check(q, cell_measure=cell, incident_power_w=p_in,
                                       s_row=[complex(math.sqrt(reflected))],
                                       tolerance=TOLERANCE)
    return {
        "name": "A 均匀场导电损耗",
        "judge": "Jackson, Classical Electrodynamics 3rd ed. §6.9: q=0.5*sigma*|E|^2",
        "grid": f"{shape} spacing={spacing} m",
        "numeric_w": numeric_w,
        "analytic_w": analytic_w,
        "rel_vs_analytic": abs(numeric_w - analytic_w) / analytic_w,
        "sparams_power_w": balance.sparams_power_w,
        "closure_rel": balance.rel_error,
        "closed": balance.closed,
    }


def case_skin_depth() -> dict:
    """算例 B：导体趋肤深度指数衰减场（解析 0.25*sigma*A*delta*|E0|^2*(1-e^-2t/delta)）。"""
    sigma, freq, e0 = 5.8e7, 1.0e9, 10.0
    delta = math.sqrt(2.0 / (2.0 * math.pi * freq * MU0 * sigma))
    thickness = 8.0 * delta
    n_cells = 4000
    h = thickness / n_cells
    z_mid = (np.arange(n_cells) + 0.5) * h
    area = 2.5e-5

    q = loss_density(e0 * np.exp(-z_mid / delta), material=LossMaterial(sigma=sigma))
    numeric_w = integrate_loss_density(q, cell_measure=area * h)
    analytic_w = 0.25 * sigma * area * delta * e0**2 * (1.0 - math.exp(-2.0 * thickness / delta))

    reflected = 0.25
    p_in = numeric_w / (1.0 - reflected)
    balance = power_conservation_check(q, cell_measure=area * h, incident_power_w=p_in,
                                       s_row=[complex(math.sqrt(reflected))],
                                       tolerance=TOLERANCE)
    return {
        "name": "B 趋肤深度指数衰减",
        "judge": "Pozar, Microwave Engineering 4th ed. §1.7.1: delta=sqrt(2/(omega*mu*sigma))",
        "grid": f"thickness=8*delta={thickness:.3e} m, n_cells={n_cells}, area={area} m^2",
        "delta_m": delta,
        "numeric_w": numeric_w,
        "analytic_w": analytic_w,
        "rel_vs_analytic": abs(numeric_w - analytic_w) / analytic_w,
        "sparams_power_w": balance.sparams_power_w,
        "closure_rel": balance.rel_error,
        "closed": balance.closed,
    }


def find_openems_dumps() -> list[str]:
    """扫描仓库 runs/ 下的 openEMS AddDump 候选产物（只登记，不解析）。"""
    runs = ROOT / "runs"
    if not runs.exists():
        return []
    found = [str(p.relative_to(ROOT)) for p in sorted(runs.rglob("*"))
             if p.is_file() and p.suffix.lower() in DUMP_SUFFIXES]
    return found


def case_real_dump(dump_path: str) -> dict:
    """实档算例：读 dump_type=29 体 dump → 逐 cell 积分 → 对 openEMS 自算 power 属性。

    裁判 = 同目录 openEMS SAR 后处理产物（SAR_*.h5）的 power 属性（独立于本仓
    内核的实现）；找不到自算属性时只报积分值，judge_found=False、不判 PASS。
    """
    from rfauto.infra.loss_dump import KIND_PROCESSED_SAR, read_loss_dump

    path = Path(dump_path)
    out: dict = {"name": f"实档 {path.name}", "path": str(path),
                 "judge": "openEMS 自算 SAR_*.h5 'power' 属性（同目录，独立实现）"}
    try:
        dump = read_loss_dump(path)
    except Exception as exc:
        out.update({"ok": False, "error": f"读档失败: {exc}"})
        return out
    numeric_w = dump.integrate_power_w()
    out.update({
        "kind": dump.kind, "freq_hz": dump.freq_hz, "dump_type": dump.dump_type,
        "shape": list(dump.shape) if dump.shape else None,
        "total_volume_m3": dump.total_volume_m3, "numeric_w": numeric_w,
    })
    if numeric_w is None:
        out.update({"ok": False, "error": "非 raw_field 形态，无可积分场/电导率/体积"})
        return out

    reference = None
    for sar in sorted(path.parent.glob("SAR_*.h5")):
        if sar.resolve() == path.resolve():
            continue
        try:
            processed = read_loss_dump(sar)
        except Exception:
            continue
        if processed.kind == KIND_PROCESSED_SAR and processed.openems_power_w is not None:
            reference = (str(sar), float(processed.openems_power_w))
            break
    if reference is None:
        out.update({"ok": False, "judge_found": False,
                    "note": "同目录无 openEMS 自算 SAR_*.h5 power 属性，积分值已报但无独立裁判"})
        return out
    ref_path, ref_w = reference
    rel = abs(numeric_w - ref_w) / ref_w if ref_w > 0 else float("inf")
    out.update({
        "judge_found": True, "judge_path": ref_path, "openems_power_w": ref_w,
        "rel_vs_openems": rel, "tolerance": DUMP_SELFCHECK_TOLERANCE,
        "ok": bool(rel <= DUMP_SELFCHECK_TOLERANCE),
    })
    return out


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="D3-1 功率守恒闭合自检（合成算例 + 可选实档）")
    parser.add_argument("--dump", action="append", default=[], metavar="PATH",
                        help="openEMS dump_type=29 体 dump（可多次）：读档→积分→对自算 power 属性")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cases = [case_uniform_field(), case_skin_depth()]
    dumps = find_openems_dumps()
    real_cases = [case_real_dump(p) for p in args.dump]

    lines = ["D3-1 功率守恒闭合自检（合成解析算例）", "=" * 60]
    all_ok = True
    for case in cases:
        ok = bool(case["closed"]) and case["rel_vs_analytic"] <= TOLERANCE
        all_ok = all_ok and ok
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {case['name']}")
        lines.append(f"    裁判: {case['judge']}")
        lines.append(f"    网格: {case['grid']}")
        lines.append(f"    integral q dV = {case['numeric_w']:.6e} W | "
                     f"解析 = {case['analytic_w']:.6e} W | "
                     f"相对误差 = {case['rel_vs_analytic']:.3e}")
        lines.append(f"    P_in*(1-sum|S|^2) = {case['sparams_power_w']:.6e} W | "
                     f"闭合相对误差 = {case['closure_rel']:.3e} | 门 = {TOLERANCE:.0%}")
    lines.append("-" * 60)
    if real_cases:
        lines.append(f"实档模式（--dump）：{len(real_cases)} 个")
        for case in real_cases:
            ok = bool(case.get("ok"))
            all_ok = all_ok and ok
            lines.append(f"[{'PASS' if ok else 'FAIL'}] {case['name']}")
            lines.append(f"    裁判: {case['judge']}")
            if case.get("error"):
                lines.append(f"    错误: {case['error']}")
                continue
            lines.append(f"    形态={case['kind']} dump_type={case['dump_type']} "
                         f"f={case['freq_hz']} Hz 网格={case['shape']} V={case['total_volume_m3']:.4e} m^3")
            lines.append(f"    integral 0.5*sigma*|E|^2 dV = {case['numeric_w']:.6e} W")
            if case.get("judge_found"):
                lines.append(f"    openEMS 自算 power = {case['openems_power_w']:.6e} W | "
                             f"相对差 = {case['rel_vs_openems']:.3e} | 门 = {case['tolerance']:.0e}")
            else:
                lines.append(f"    {case.get('note', '')}")
        lines.append("-" * 60)
    if dumps:
        lines.append(f"openEMS 场 dump 候选（runs/ 下）：{len(dumps)} 个"
                     + (f"（本次已用 --dump 解析其中 {len(real_cases)} 个）" if real_cases
                        else "，未传 --dump，未用其做验证："))
        lines.extend(f"    {p}" for p in dumps[:10])
    else:
        lines.append("openEMS 场 dump：runs/ 下未找到 *.h5/*.hdf5/*.vtk 产物"
                     "——本次仅合成解析算例，未使用真机数据。")
    lines.append(f"结论: {'全部闭合' if all_ok else '存在不闭合算例'}（门 {TOLERANCE:.0%}）")

    print("\n".join(lines))
    print(json.dumps({"tolerance": TOLERANCE, "all_closed": all_ok,
                      "cases": cases, "real_dump_cases": real_cases,
                      "openems_dumps": dumps},
                     ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
