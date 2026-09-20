r"""G16 EDA 数据格式互操作矩阵运行器。

跑 Touchstone 1.0/2.0 × MDIF × CITI 与 N=1/2/3/4 端口的所有格：每格用同源
确定性网络写出→skrf 读回，断言 max|ΔS| <= 1e-12、端口数、频点、参考阻抗
一致。结果（每格 pass/fail + 最大 |ΔS|）写入 runs/interop/ 并打印。

用法::

    .venv\Scripts\python.exe scripts/interop_matrix.py [--outdir runs/interop]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import skrf

from rfauto.adapters.interchange import (
    INTERCHANGE_FORMATS,
    export_interchange,
    max_complex_delta,
    read_interchange,
)

TOLERANCE = 1e-12
PORT_COUNTS = (1, 2, 3, 4)
EXTENSIONS = {"touchstone1": "s{}p", "touchstone2": "s{}p", "mdif": "mdf", "citi": "cti"}
DEFAULT_OUTDIR = Path("runs/interop")
REAL_ADS_MDF = Path(
    "scripts/spike_b_ads/sample_wrk27/Datalink_Basics_wrk/data/python/IMPORT_TO_ADS.mdf"
)

_METADATA_BEHAVIOUR = {
    "touchstone1": "注释保留（! 行）；参考阻抗走选项行 R（等端口阻抗）；per-port z0 需 write_z0=True",
    "touchstone2": "注释保留（! 行）；[Reference] 块保留 per-port z0（需 write_z0=True）",
    "mdif": "文件级注释保留（! 行）；只支持单一标量 R 参考阻抗，per-port z0 由 skrf 显式拒绝",
    "citi": "以 ! 行写注释、skrf Citi 可读回；CITI 规范的 COMMENT 关键字被 skrf 读取器丢弃；PortZ 块保留 per-port z0",
}


def synthesize(n_ports: int, z0: float = 50.0, n_points: int = 11) -> skrf.Network:
    """确定性合成 N 端口网络（种子 = 端口数，逐元素可复现）。"""
    freq = skrf.Frequency(1.0, 5.0, n_points, unit="GHz")
    rng = np.random.default_rng(n_ports)
    raw = rng.normal(size=(n_points, n_ports, n_ports)) + 1j * rng.normal(
        size=(n_points, n_ports, n_ports)
    )
    return skrf.Network(frequency=freq, s=raw * 0.1, z0=z0, name=f"dut_n{n_ports}")


def run_cell(fmt: str, n_ports: int, workdir: Path) -> dict:
    """跑单格往返并返回结构化结果（异常也落成 fail 而非中断矩阵）。"""
    cell = {"format": fmt, "n_ports": n_ports, "status": "fail", "max_delta_s": None}
    try:
        net = synthesize(n_ports)
        path = workdir / f"{fmt}_n{n_ports}.{EXTENSIONS[fmt].format(n_ports)}"
        export_interchange(net, path, fmt, comments=["g16 interop matrix"])
        back = read_interchange(path, fmt)[0]
        delta = max_complex_delta(net.s, back.s)
        z0_back = float(np.asarray(back.z0)[0, 0].real)
        ports_ok = back.number_of_ports == n_ports
        freq_ok = bool(np.allclose(back.f, net.f))
        z0_ok = abs(z0_back - 50.0) < 1e-9
        cell.update(
            max_delta_s=delta,
            ports_ok=ports_ok,
            freq_ok=freq_ok,
            z0_ohm=z0_back,
            z0_ok=z0_ok,
            n_points=int(net.f.size),
            status="pass" if (delta <= TOLERANCE and ports_ok and freq_ok and z0_ok) else "fail",
            error=None,
        )
    except Exception as exc:  # 矩阵运行器必须把任何单格失败落成报告行而非中断
        cell["error"] = f"{type(exc).__name__}: {exc}"
    return cell


def probe_real_ads_mdf() -> dict:
    """探测仓库内真实 ADS 侧 .mdf 的可读性（找不到就如实声明）。"""
    if not REAL_ADS_MDF.exists():
        return {"path": str(REAL_ADS_MDF), "exists": False, "note": "仓库内未找到真实 .mdf"}
    info = {"path": str(REAL_ADS_MDF), "exists": True, "source": "ADS/PathWave 数据目录内既有文件"}
    text = REAL_ADS_MDF.read_text(encoding="utf-8", errors="replace")
    info["has_touchstone_option_line"] = "#" in text
    info["comma_separated"] = "," in text
    try:
        networks = read_interchange(REAL_ADS_MDF, "mdif")
        info["readable"] = True
        info["n_networks"] = len(networks)
    except Exception as exc:  # 探测结果如实记录，不掩盖不可读事实
        info["readable"] = False
        info["error"] = f"{type(exc).__name__}: {exc}"
        info["note"] = "该文件是逗号分隔的 dB 数据块（%Freq(1) dBS21(1)），非 skrf 可解 GMDIF"
    return info


def run_matrix(outdir: Path) -> dict:
    """跑完整格式×端口数矩阵，返回报告字典。"""
    outdir = Path(outdir)
    artifacts = outdir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    cells = [run_cell(fmt, n_ports, artifacts) for fmt in INTERCHANGE_FORMATS for n_ports in PORT_COUNTS]
    passed = sum(1 for c in cells if c["status"] == "pass")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skrf_version": skrf.__version__,
        "tolerance": TOLERANCE,
        "seed_policy": "np.random.default_rng(n_ports)，每格固定种子",
        "port_counts": list(PORT_COUNTS),
        "formats": list(INTERCHANGE_FORMATS),
        "cells": cells,
        "summary": {"total": len(cells), "passed": passed, "failed": len(cells) - passed},
        "real_ads_mdf": probe_real_ads_mdf(),
        "metadata_behaviour": _METADATA_BEHAVIOUR,
    }


def _render_markdown(report: dict) -> str:
    lines = [
        "# G16 EDA 数据格式互操作矩阵",
        "",
        f"- 生成时间(UTC): {report['generated_at']}",
        f"- skrf: {report['skrf_version']}",
        f"- 容差: max|ΔS| <= {report['tolerance']:.0e}",
        f"- 种子策略: {report['seed_policy']}",
        f"- 汇总: {report['summary']['passed']}/{report['summary']['total']} pass",
        "",
        "| 格式 | 端口数 | 状态 | max|ΔS| | 端口数一致 | 频点一致 | z0(Ω) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cell in report["cells"]:
        delta = "N/A" if cell["max_delta_s"] is None else f"{cell['max_delta_s']:.3e}"
        lines.append(
            f"| {cell['format']} | {cell['n_ports']} | {cell['status']} | {delta} | "
            f"{cell.get('ports_ok')} | {cell.get('freq_ok')} | {cell.get('z0_ohm')} |"
        )
    lines += ["", "## 非数值元数据行为", ""]
    lines += [f"- {fmt}: {note}" for fmt, note in report["metadata_behaviour"].items()]
    real = report["real_ads_mdf"]
    lines += ["", "## 真实 ADS .mdf 探测", "", f"- 路径: {real['path']}", f"- 存在: {real['exists']}"]
    if real["exists"]:
        lines.append(f"- skrf 可读: {real.get('readable')} ({real.get('error', real.get('note', ''))})")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G16 互操作矩阵运行器")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR, help="报告输出目录")
    args = parser.parse_args(argv)

    report = run_matrix(args.outdir)
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "interop_matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.outdir / "interop_matrix.md").write_text(_render_markdown(report), encoding="utf-8")

    print(f"G16 interop matrix (skrf {report['skrf_version']}, tol {report['tolerance']:.0e})")
    for cell in report["cells"]:
        delta = "N/A" if cell["max_delta_s"] is None else f"{cell['max_delta_s']:.3e}"
        detail = cell.get("error") or ""
        print(f"  {cell['format']:11s} N={cell['n_ports']}  {cell['status']:4s}  max|dS|={delta} {detail}")
    summary = report["summary"]
    print(f"summary: {summary['passed']}/{summary['total']} pass, {summary['failed']} fail")
    real = report["real_ads_mdf"]
    print(f"real ADS mdf: exists={real['exists']} readable={real.get('readable')} {real.get('note', '')}")
    print(f"report -> {args.outdir / 'interop_matrix.json'}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
