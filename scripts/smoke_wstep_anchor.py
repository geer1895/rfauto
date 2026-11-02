"""临时冒烟：微带宽度阶跃基元真跑（50Ω→35Ω，w1=1.1134 w2=1.897 L=40mm）。

锚判据（WP2.2）：
1. 分段 β 金标准（#162 同法）：CalcPort 双端口 β → εeff1/εeff2 对照
   skrf HJ 闭式 ±2%（mesh=0.4mm 收敛档——基准曲线 auto 档 +2.30% 未
   收敛，见 runs/benchmark/mline_mesh_convergence.json）；
2. |S11| 单侧门：引擎 max 不得比 skrf 级联理想裁判差 3dB 以上
   （理想地板=两段阻抗失配；阶梯寄生只允许小幅恶化）；
3. |S21| 幅度：引擎 ≥ 理想 −0.05（额外损耗判废）。
   相位门撤下：MSLPort 测量面 de-embedding 使裸 S21 相位不含全长
   （pt1 实证 82° 偏差=测量面间 13.4mm 而非 40mm，#161 同源）——
   分段 β 金标准即为此设计的替代锚。
工作目录参数化（#198 教训）。证据链 runs/wstep_smoke/。
"""
import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np
import skrf

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver

parser = argparse.ArgumentParser()
parser.add_argument("--pt", default="pt2")
args = parser.parse_args()

W1, W2, L = 1.1134, 1.897, 40.0
H_SUB, ER, F_MID = 0.508, 3.66, 2.5
MESH = 0.4  # 收敛档（引擎基准曲线判读）

from rfauto.core.synthesis import Stackup, forward_z0  # noqa: E402

stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
_, eps_hj1 = forward_z0(W1, F_MID, stackup)
_, eps_hj2 = forward_z0(W2, F_MID, stackup)

# ── 确定性裁判（幅度域）：skrf 级联 HJ 闭式 ──
freq = skrf.Frequency(1.5, 3.5, 201, unit="GHz")
m1 = skrf.media.MLine(frequency=freq, w=W1 * 1e-3, h=H_SUB * 1e-3, ep_r=ER)
m2 = skrf.media.MLine(frequency=freq, w=W2 * 1e-3, h=H_SUB * 1e-3, ep_r=ER)
ideal = m1.line(L / 2, unit="mm") ** m2.line(L / 2, unit="mm")
ideal.renormalize([50.0, 50.0])

work = Path(f"runs/wstep_smoke/{args.pt}")
solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems", exe_path=resolve_openems_exe(),
    working_dir=str(work), freq_range_ghz=(1.5, 3.5),
    mesh_resolution_mm=MESH,
    extra_params={"solve_timeout_s": 36000}))
assert solver.connect(), "openEMS 不可用"
assert solver.build_geometry({"template": "wstep",
                              "params": {"w1_mm": W1, "w2_mm": W2,
                                         "line_len_mm": L}})
t0 = time.time()
result = solver.solve()
print(f"solve_s={time.time() - t0:.0f} success={result.success} "
      f"msg={result.message}", flush=True)
assert result.success and result.s_params is not None

f = np.asarray(result.freq_ghz) * 1e9  # Hz
s11 = result.s_params[:, 0, 0]
s21 = result.s_params[:, 0, 1]

# 1) 分段 β 金标准（CalcPort）
with open(work / "port_beta.csv", encoding="utf-8") as fh:
    rows = list(csv.reader(fh))
has_b2 = "beta2_rad_per_m" in rows[0]
sel_cols = ([1, 2] if has_b2 else [1])
bf = np.array([float(r[0]) for r in rows[1:]])
sel = (bf >= 0.96 * F_MID * 1e9) & (bf <= 1.04 * F_MID * 1e9)
eps = {}
for name, col in (("eps_eff1", sel_cols[0]),
                  ("eps_eff2", sel_cols[1] if has_b2 else sel_cols[0])):
    beta = float(np.median(np.array([float(rows[k][col]) for k in
                                     range(1, len(rows))])[sel]))
    eps[name] = (beta * 299792458.0 / (2 * np.pi * F_MID * 1e9)) ** 2
d1 = (eps["eps_eff1"] / eps_hj1 - 1) * 100
d2 = (eps["eps_eff2"] / eps_hj2 - 1) * 100
print(f"eps_hj: seg1={eps_hj1:.4f} seg2={eps_hj2:.4f}")
print(f"engine(beta): seg1={eps['eps_eff1']:.4f} ({d1:+.2f}%) "
      f"seg2={eps['eps_eff2']:.4f} ({d2:+.2f}%)")

# 2) |S11| 单侧门
m11_eng = 20 * np.log10(np.abs(s11) + 1e-12)
m11_ideal = 20 * np.log10(np.abs(ideal.s[:, 0, 0]) + 1e-12)
s11_gap = float(np.max(m11_eng) - np.max(m11_ideal))

# 3) |S21| 幅度
mag_eng = float(np.mean(np.abs(s21)))
mag_ideal = float(np.mean(np.abs(ideal.s[:, 0, 1])))

print(f"ideal_s11_max={np.max(m11_ideal):.1f}dB "
      f"engine_s11_max={np.max(m11_eng):.1f}dB gap={s11_gap:+.1f}dB "
      f"(单侧门 ≤+3dB)")
print(f"s21_mag_mean: eng={mag_eng:.4f} ideal={mag_ideal:.4f}")
ok = (abs(d1) <= 2.0 and abs(d2) <= 2.0 and s11_gap <= 3.0
      and mag_eng >= mag_ideal - 0.05)
verdict = "PASS" if ok else "FAIL"
print(f"WSTEP_PROBE_{verdict}（判据：双段 |Δεeff|≤2% HJ、"
      f"|S11| 单侧 ≤+3dB、|S21| 额外损耗≤0.05）")
