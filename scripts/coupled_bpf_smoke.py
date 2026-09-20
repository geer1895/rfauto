"""平行耦合（边缘耦合）BPF 真机冒烟（WP2.3 Tier1，电路裁判+C13 闭式对照）。

理论口径见 rfauto/adapters/openems_templates.py 文末 WP2.3 平行耦合 BPF 段：
J 倒置器综合（Pozar §8.6）→ (Z0e,Z0o) → KJ 1984 二维反解 (w,s) → 等长阶梯
阵列。设计点 coupled_bpf_design_from_order(3, 2.5, 0.05, 20)。

裁判（独立来源，两级）：
- 主裁 = coupled_bpf_circuit_sparams（准静态真偶/奇模相速电路模型——与 EM
  同一几何的解析预测，含微带非均匀介质二阶退化）；
- 参照 = C13 耦合矩阵理想频响 coupling_matrix_response（理想切比雪夫）。

判据从宽（首次真跑；已知未建模：宽度台阶、开路端边缘导纳残差、KJ 准静态
色散、0.4mm 网格对 0.13mm 端缝的分辨率）：带内最小插损 ≤3dB、带内纹波
≤4dB、带内回损 ≤−8dB（电路模型预测 ≈−13dB）、峰位偏差 ≤5%（直阶梯无折叠，
严于 hairpin 的 8%）、β 金标准 ±3%（馈线段=50Ω）。EM vs 电路模型带内
max|ΔS21| 只报告不作门（其量级即"未建模效应总量"的实测）。

运行（后台+日志轮询，#157）：证据链 runs/coupled_bpf_smoke/<pt>/。
真机前离线审计（#212：渲染→exec 几何段→CSXCAD 原语实测）必须先过——
tests/unit/test_coupled_bpf_template.py 27 测全绿即门槛。
"""
import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.openems_templates import (
    COUPLED_BPF_NOMINAL,
    coupled_bpf_circuit_sparams,
    coupled_bpf_design_from_order,
)
from rfauto.core.calculators import coupling_matrix_response
from rfauto.core.synthesis import Stackup, forward_z0

parser = argparse.ArgumentParser()
parser.add_argument("--pt", default="pt1")
parser.add_argument("--mesh", type=float, default=0.4)
parser.add_argument("--order", type=int, default=3)
parser.add_argument("--fbw", type=float, default=0.05)
parser.add_argument("--rl", type=float, default=20.0)
parser.add_argument("--timeout", type=float, default=3600.0)
parser.add_argument("--flo", type=float, default=2.25)
parser.add_argument("--fhi", type=float, default=2.75)
args = parser.parse_args()

F0 = 2.5
stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")

design = coupled_bpf_design_from_order(args.order, F0, args.fbw, args.rl)
params = dict(COUPLED_BPF_NOMINAL)          # 4 位舍入名义表 = design 再生
params["order"] = args.order
print("design:", {k: params[k] for k in
                  ("w_feed_mm", "res_len_mm", "feed_len_mm",
                   "widths_mm", "gaps_mm")}, flush=True)
print("J/Z0=" + "[" + ", ".join(f"{v:.5f}" for v in design["j_norm"]) + "]",
      flush=True)

_, eps_hj_feed = forward_z0(params["w_feed_mm"], F0, stackup)

work = Path(f"runs/coupled_bpf_smoke/{args.pt}")
solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems", exe_path=resolve_openems_exe(),
    working_dir=str(work), freq_range_ghz=(args.flo, args.fhi),
    mesh_resolution_mm=args.mesh,
    extra_params={"solve_timeout_s": args.timeout}))
assert solver.connect(), "openEMS 不可用"
assert solver.build_geometry({"template": "coupled_bpf", "params": params})
t0 = time.time()
result = solver.solve()
print(f"solve_s={time.time() - t0:.0f} success={result.success} "
      f"msg={result.message}", flush=True)
assert result.success and result.s_params is not None, "openEMS 真跑失败"

f_ghz = np.asarray(result.freq_ghz, dtype=float)
s = result.s_params

# ── β 金标准（CalcPort port1；馈线段 50Ω，#162）──
beta_csv = work / "port_beta.csv"
d_feed = float("nan")
if beta_csv.exists():
    with open(beta_csv, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    bf = np.array([float(r[0]) for r in rows])
    bb = np.array([float(r[1]) for r in rows])
    sel = (bf >= 0.96 * F0 * 1e9) & (bf <= 1.04 * F0 * 1e9)
    beta = float(np.median(bb[sel]))
    eps_feed = (beta * 299792458.0 / (2 * np.pi * F0 * 1e9)) ** 2
    d_feed = (eps_feed / eps_hj_feed - 1) * 100
    print(f"eps_hj(50Ω馈)={eps_hj_feed:.4f} engine(beta)={eps_feed:.4f} "
          f"delta={d_feed:+.2f}%", flush=True)

# ── 主裁：准静态电路模型（同一几何解析预测）──
circuit = coupled_bpf_circuit_sparams(f_ghz, design)
circ_s21 = 20.0 * np.log10(np.abs(circuit[:, 1, 0]) + 1e-12)
# ── 参照：C13 理想频响 ──
ideal = coupling_matrix_response(
    freq_ghz=[float(v) for v in f_ghz], f0_ghz=F0, fbw=args.fbw,
    matrix=design["coupling_matrix"])
ideal_s21 = np.asarray(ideal["s21_db"], dtype=float)
ideal_s11 = np.asarray(ideal["s11_db"], dtype=float)

s21_db = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-12)
s11_db = 20 * np.log10(np.abs(s[:, 0, 0]) + 1e-12)
band = (f_ghz >= F0 * (1 - args.fbw / 2)) & (f_ghz <= F0 * (1 + args.fbw / 2))

i_peak = int(np.argmax(s21_db))
f_peak = float(f_ghz[i_peak])
il_min = float(s21_db[band].min())
ripple = float(s21_db[band].max() - s21_db[band].min())
s11_band = float(s11_db[band].max())
band_lo, band_hi = F0 * (1 - args.fbw / 2), F0 * (1 + args.fbw / 2)
stop = (f_ghz < band_lo - 1.5 * (band_hi - band_lo)) | \
       (f_ghz > band_hi + 1.5 * (band_hi - band_lo))
rej = float(s21_db[stop].min()) if bool(stop.any()) else float("nan")
# 电路模型峰位（EM 峰位偏差的对照基准）
circ_peak = float(f_ghz[int(np.argmax(circ_s21))])
d_em_circ = float(np.max(np.abs(s21_db[band] - circ_s21[band])))

i_mid = int(np.argmin(np.abs(f_ghz - F0)))
print(f"@{F0}GHz: |S21|={s21_db[i_mid]:.2f}dB |S11|={s11_db[i_mid]:.1f}dB"
      f"（C13 理想 |S21|={ideal_s21[i_mid]:.3f} |S11|={ideal_s11[i_mid]:.1f}；"
      f"电路预测 |S21|={circ_s21[i_mid]:.2f}）", flush=True)
print(f"实测：峰位={f_peak:.4f}GHz（电路模型峰 {circ_peak:.4f}）"
      f" 带内最小插损={il_min:.2f}dB 带内纹波={ripple:.2f}dB "
      f"带内回损={s11_band:.1f}dB 带外抑制={rej:.1f}dB", flush=True)
print(f"EM vs 电路模型带内 max|ΔS21|={d_em_circ:.2f}dB"
      f"（未建模效应总量实测：宽度台阶/开路端残差/准静态色散/网格）", flush=True)
_ideal_ripple = float(ideal_s21[band].max() - ideal_s21[band].min())
_ideal_rl = float(ideal_s11[band].max())
print(f"C13 理想：带内纹波={_ideal_ripple:.3f}dB 带边回损={_ideal_rl:.1f}dB",
      flush=True)

ok = (il_min <= -0.2 and il_min >= -3.0 and ripple <= 4.0
      and s11_band <= -8.0 and abs(f_peak - circ_peak) / circ_peak <= 0.05
      and (np.isnan(d_feed) or abs(d_feed) <= 3.0))
verdict = "PASS" if ok else "FAIL"
print(f"COUPLED_BPF_PROBE_{verdict}（判据：带内最小插损 -3~-0.2dB、带内纹波 "
      f"≤4dB、带内回损 ≤-8dB、峰位 vs 电路模型 ≤5%、β±3%）", flush=True)
