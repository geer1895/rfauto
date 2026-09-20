r"""via β2 收口：镜像前提裁决 + openEMS 单激励可复现数据路径。

用法（工作区根目录）：
    .venv\Scripts\python.exe scripts\via_beta2_derivation.py            # 离线推导（秒级，读归档）
    .venv\Scripts\python.exe scripts\via_beta2_derivation.py --run      # 真机小例（openEMS 空闲时，分钟级）

背景（上轮 PARTIAL 尾巴）
----------------------------------------------------
上轮把 via β2 案例的 4.91% 当"探针尺度常数"去嵌（εeff2'≈εeff1 ≤1% 达标），
但第一性推导未达成。本轮新增 core/deembed.beta_from_voltage_trio：由同一端口
**等距三点电压探针**直接解波动方程 β²=−U″/U——对任意驻波比精确、与电流链
及 CalcPort 的 −dEt·dHt/(Ht·Et) 公式无关。它作用在归档**原始探针场数据**
（runs/via_smoke/pt3/fdtd/port_ut_*）上的结论是：

    β2/β1 = 1.04662±0.00033（带内平坦 0.031%）→ **镜像前提（εeff2≡εeff1）
    被原始场数据否证**；1.0491 ≈ 1.04662(真实模态比) × 1.00232(探针链路
    驻波采样残差)。上轮"去嵌后 ≤1%"在 s=mean(β2/β1) 相除下是代数近恒等
    （自证），不构成物理结论；真正的推导结论=偏移主要是真实模态差异
    （εeff2/εeff1 ≈ 1.095）。

--run 模式给出**可复现的仿真数据路径**：渲染同一结构配方的缩小版
（BOARD 60→24mm，单激励 port1，同一 MSLPort/网格/边界配方，探针场落盘），
重跑 openEMS 后对新探针数据重复同一推导——独立复核裁决是否随网格/域尺寸
稳健。模态差异的**几何成因**（为何底层馈线慢 4.7%）仍开放，见 followUps。
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.core.deembed import derive_via_mirror_verdict  # noqa: E402

ARCHIVE = REPO / "runs" / "via_smoke" / "pt3"
RUN_DIR = REPO / "runs" / "via_mirror_check"
F_TARGET = 2.5e9
SEL_HALF = 200e6  # GaussExcite 1σ 带内（fc=250MHz），避开 DFT 边缘信噪比下降


def _read_td(path: Path) -> tuple[np.ndarray, np.ndarray]:
    t: list[float] = []
    v: list[float] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("%") or line.startswith("t/"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            t.append(float(parts[0]))
            v.append(float(parts[1]))
    if len(t) < 8:
        raise ValueError(f"{path} 时间序列过短（{len(t)} 点）")
    return np.array(t), np.array(v)


def _dft_band(t: np.ndarray, v: np.ndarray, freq: np.ndarray) -> np.ndarray:
    dt = t[1] - t[0]
    return np.array([np.sum(v * np.exp(-2j * np.pi * f * t)) * dt for f in freq])


def _probe_y(path: Path) -> float:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if "start-coordinates" in line:
                seg = line.split("(")[1].split(")")[0]
                return float(seg.split(",")[1])
    raise ValueError(f"{path.name} 无 start-coordinates")


def _load_beta_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    b1 = np.array([float(r["beta1_rad_per_m"]) for r in rows])
    b2 = np.array([float(r["beta2_rad_per_m"]) for r in rows])
    return freq, b1, b2


def derive_from_case(fdtd_dir: Path, beta_csv: Path) -> dict:
    """归档/新跑通用的推导入口：原始探针场 + 链路 β → 镜像前提裁决报告。"""
    freq, b1, b2 = _load_beta_csv(beta_csv)
    trios: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    spacings: dict[int, float] = {}
    for p in (1, 2):
        ys = [_probe_y(fdtd_dir / f"port_ut_{p}{n}") for n in "ABC"]
        delta = abs(ys[1] - ys[0])
        if abs(abs(ys[2] - ys[1]) - delta) > 1e-12:
            raise ValueError(f"port{p} 探针三重奏不等距：{ys}")
        tds = [_read_td(fdtd_dir / f"port_ut_{p}{n}") for n in "ABC"]
        trios[p] = tuple(_dft_band(t, v, freq) for t, v in tds)
        spacings[p] = delta
    sel = np.abs(freq - F_TARGET) <= SEL_HALF
    return derive_via_mirror_verdict(
        freq[sel], b1[sel], b2[sel],
        tuple(x[sel] for x in trios[1]), tuple(x[sel] for x in trios[2]),
        spacings[1], spacings[2],
    )


def _print_report(report: dict, source: str) -> None:
    print(f"=== via β2 镜像前提裁决（{source}）===")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print("\n=== 关键误差数字 ===")
    print(f"trio(原始场) β2/β1 = {report['trio_ratio_mean']:.6f}"
          f" ± {report['trio_ratio_std']:.6f}"
          f"（带内平坦 {report['trio_ratio_flatness'] * 100:.3f}%）")
    print(f"chain(CalcPort) β2/β1 = {report['chain_ratio_mean']:.6f}"
          f"（#205 定版 1.0491±0.0011 复现：{report['chain_reproduces_documented']}）")
    print(f"分解：{report['chain_ratio_mean']:.6f} = {report['trio_ratio_mean']:.6f}"
          f"(真实模态) × {report['artifact_factor']:.6f}(链路残差)")
    print(f"trio εeff1 = {report['eps_eff1_trio_mean']:.6f}，"
          f"εeff2 = {report['eps_eff2_trio_mean']:.6f}"
          f"（比 {report['eps_eff_trio_ratio']:.6f}）")
    print("\n=== 诚实结论 ===")
    if report["verdict"] == "real_modal_difference":
        print(f"镜像前提被原始场数据否证：偏移主要是真实模态差异，探针链路残差仅 "
              f"{abs(report['artifact_factor'] - 1) * 100:.2f}%（带符号 "
              f"{(report['artifact_factor'] - 1) * 100:+.2f}%，随网格/探针布置漂移=伪象特征）。")
        print("上轮'去嵌后 εeff2≈εeff1 ≤1%'在 s=mean(β2/β1) 相除下是代数近恒等"
              "（自证），不构成物理结论。")
        print("模态差异的几何成因仍开放——用 --run 复核稳健性；归因待专门批次"
              "（对照镜像线对/方向翻转小例）。")
    elif report["verdict"] == "chain_artifact":
        print("镜像前提成立：偏移是探针链路伪象，乘性去嵌（analyze_via_port_scale）正当。")
    else:
        print("镜像前提成立且链路比值≈1：无需去嵌。")


# 缩小版 via 复制品：与 runs/via_smoke/pt3/simulation.py 同一结构配方
# （官方 MSL_NotchFilter 网格方法学 + MSLPort + 抗焊盘/金孔/barrel），
# 仅 BOARD 60→24mm、单激励 port1、只写 port_beta.csv/sparams.csv。
_SIM_TEMPLATE = r'''#!/usr/env/python3
"""openEMS script (via mirror-check replica, single excitation, small board)."""
import csv
import os

_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", "")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import MSLPort

F0 = 2500000000.0
FC = 250000000.0
ER = 3.66
H_SUB = 0.000508
TAND = 0.0037
BASE = 0.0004
NEAR = 0.0001
BOARD = 0.024
AIR_TOP = 0.005

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "port_beta.csv")
SP_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sparams.csv")
SIM_PATH = os.path.abspath("fdtd")

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=100000)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
FDTD.SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "MUR", "MUR"])

mesh = CSX.GetGrid()

def _axis(ax, near_pts, dom_lo, dom_hi):
    for p in near_pts:
        mesh.AddLine(ax, p)
    mesh.SmoothMeshLines(ax, NEAR)
    mesh.AddLine(ax, np.array([dom_lo, dom_hi]))
    mesh.SmoothMeshLines(ax, BASE)

_axis("x", [-0.0008, -0.0005567, 0.0, 0.0005567, 0.0008], -BOARD, BOARD)
_axis("y", [-0.0008, 0.0, 0.0008], -BOARD, BOARD)
mesh.AddLine("z", -AIR_TOP)
mesh.AddLine("z", np.linspace(0, 2 * H_SUB, 9))
mesh.AddLine("z", 2 * H_SUB + AIR_TOP)
mesh.SmoothMeshLines("z", BASE)
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, 2 * H_SUB), priority=0)
W = 1.1134e-3
AP = 0.8e-3
RV = 0.15e-3
H_MID = H_SUB
H_TOP = 2 * H_SUB
via_gnd = CSX.AddMetal("via_gnd")
via_gnd.AddBox((-BOARD, -BOARD, H_MID), (-AP, AP, H_MID), priority=10)
via_gnd.AddBox((AP, -BOARD, H_MID), (BOARD, AP, H_MID), priority=10)
via_gnd.AddBox((-AP, -BOARD, H_MID), (AP, -AP, H_MID), priority=10)
via_gnd.AddBox((-AP, AP, H_MID), (AP, BOARD, H_MID), priority=10)
via_strip = CSX.AddMetal("via_strip")
via_strip.AddBox((-W / 2, -BOARD, H_TOP), (W / 2, 0.0, H_TOP), priority=10)
via_strip.AddBox((-W / 2, 0.0, 0.0), (W / 2, BOARD, 0.0), priority=10)
via_barrel = CSX.AddMetal("via_barrel")
via_barrel.AddCylinder([0.0, 0.0, 0.0], [0.0, 0.0, H_TOP], radius=RV, priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=via_strip,
                 start=np.array([W / 2, -BOARD, H_TOP]),
                 stop=np.array([-W / 2, 0.0, H_MID]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=via_strip,
                 start=np.array([-W / 2, BOARD, 0.0]),
                 stop=np.array([W / 2, 0.0, H_MID]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)

FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

f = np.linspace(F0 - FC, F0 + FC, 401)
_port1.CalcPort(SIM_PATH, f, ref_impedance=50)
_port2.CalcPort(SIM_PATH, f, ref_impedance=50)
S11 = _port1.uf_ref / _port1.uf_inc
S21 = _port2.uf_ref / _port1.uf_inc
with open(CSV_PATH, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["freq_hz", "beta1_rad_per_m", "beta2_rad_per_m"])
    for i, fi in enumerate(f):
        w.writerow([fi, float(np.real(_port1.beta[i])), float(np.real(_port2.beta[i]))])
with open(SP_CSV_PATH, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"])
    for i, fi in enumerate(f):
        w.writerow([fi, S11[i].real, S11[i].imag, S21[i].real, S21[i].imag])
print("via mirror-check simulation done")
'''


def run_fresh_case() -> dict:
    """渲染缩小版 via 复制品 → openEMS 单激励真跑 → 对新探针数据重复推导。"""
    if not RUN_DIR.exists():
        RUN_DIR.mkdir(parents=True)
    sim_path = RUN_DIR / "simulation.py"
    sim_path.write_text(_SIM_TEMPLATE, encoding="utf-8")
    (RUN_DIR / "fdtd").mkdir(exist_ok=True)
    print(f"[run] openEMS 单激励小例：{sim_path}")
    print("[run] 域 48x48mm、~0.6M cells，预期 1-5 分钟（前台直跑，超时 10min）")
    proc = subprocess.run(
        [sys.executable, str(sim_path)],
        cwd=RUN_DIR, capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout[-2000:] + "\n" + proc.stderr[-2000:])
        raise SystemExit(f"openEMS 小例失败：exit {proc.returncode}")
    print(f"[run] {proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ''}")
    return derive_from_case(RUN_DIR / "fdtd", RUN_DIR / "port_beta.csv")


def main() -> int:
    parser = argparse.ArgumentParser(description="via β2 镜像前提裁决（离线/真机小例）")
    parser.add_argument("--run", action="store_true", help="渲染并真跑缩小版 via 小例后推导")
    args = parser.parse_args()
    if args.run:
        report = run_fresh_case()
        _print_report(report, f"新跑小例 {RUN_DIR.name}（独立复核）")
        return 0
    beta_csv = ARCHIVE / "port_beta.csv"
    if not beta_csv.exists():
        raise SystemExit(f"归档缺失: {beta_csv}（离线推导不可用；可用 --run 生成新数据）")
    report = derive_from_case(ARCHIVE / "fdtd", beta_csv)
    _print_report(report, f"归档 {ARCHIVE.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
