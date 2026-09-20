"""临时冒烟：过孔过渡基元真跑（双层板，50Ω 馈线，反焊盘同轴 ≈52.5Ω）。

锚判据（WP2.2 收官，成型模式）：
1. β 金标准：CalcPort 双端口 β → εeff 对照 skrf HJ ±2%
   （mesh=0.4mm 收敛档）；
2. |S11| 绝对门 <-10dB（设计良好过孔量级；理想级联完全匹配，
   引擎唯一反射源=过孔柱+反焊盘寄生）；
3. |S21| 幅度均值 ≥ 0.90（过孔过渡额外损耗容差宽于均匀线）；
4. 互易性：|S11| vs |S22| ≤0.5dB。
工作目录参数化（#198 教训）。证据链 runs/via_smoke/。
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
from rfauto.core.synthesis import Stackup, forward_z0

parser = argparse.ArgumentParser()
parser.add_argument("--pt", default="pt1")
args = parser.parse_args()

W, AP, RV = 1.1134, 0.8, 0.15
H_SUB, ER, F_MID = 0.508, 3.66, 2.5
MESH = 0.4  # 收敛档（引擎基准曲线判读）

stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
_, eps_hj = forward_z0(W, F_MID, stackup)

work = Path(f"runs/via_smoke/{args.pt}")
solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems", exe_path=resolve_openems_exe(),
    working_dir=str(work), freq_range_ghz=(2.25, 2.75),
    mesh_resolution_mm=MESH,
    extra_params={"solve_timeout_s": 36000}))
assert solver.connect(), "openEMS 不可用"
assert solver.build_geometry({"template": "via",
                              "params": {"w_mm": W, "antipad_mm": AP,
                                         "r_via_mm": RV}})
t0 = time.time()
result = solver.solve()
print(f"solve_s={time.time() - t0:.0f} success={result.success} "
      f"msg={result.message}", flush=True)
assert result.success and result.s_params is not None

f = np.asarray(result.freq_ghz) * 1e9
s = result.s_params

# 1) β 金标准（CalcPort 双端口）
with open(work / "port_beta.csv", encoding="utf-8") as fh:
    rows = list(csv.reader(fh))
bf = np.array([float(r[0]) for r in rows[1:]])
sel = (bf >= 0.96 * F_MID * 1e9) & (bf <= 1.04 * F_MID * 1e9)
betas = []
for col in (1, 2):
    beta = float(np.median(np.array([float(rows[k][col])
                                     for k in range(1, len(rows))])[sel]))
    eps = (beta * 299792458.0 / (2 * np.pi * F_MID * 1e9)) ** 2
    betas.append((beta, (eps / eps_hj - 1) * 100))
print(f"eps_hj={eps_hj:.4f}  engine β 锚: p1={betas[0][1]:+.2f}% "
      f"p2(诊断,倒置馈提取污染)={betas[1][1]:+.2f}%")

# 2) |S11| 绝对门 + 4) 互易性
m11 = 20 * np.log10(np.abs(s[:, 0, 0]) + 1e-12)
m22 = 20 * np.log10(np.abs(s[:, 1, 1]) + 1e-12)
s11_max = float(m11.max())
recip = abs(float(m11.mean()) - float(m22.mean()))

# 3) |S21| 幅度
mag_mean = float(np.mean(np.abs(s[:, 0, 1])))

print(f"s11_max={s11_max:.1f}dB (绝对门 <-10dB)  "
      f"s21_mag_mean={mag_mean:.4f} (门 ≥0.90)")
print(f"互易性 |mean S11 - mean S22| = {recip:.3f}dB (门 ≤0.5)")
ok = (abs(betas[0][1]) <= 2.0 and s11_max < -10.0
      and mag_mean >= 0.90 and recip <= 0.5)
verdict = "PASS" if ok else "FAIL"
print(f"VIA_PROBE_{verdict}（判据：β1 顶馈 |Δεeff|≤2% HJ——"
      f"εeff2 由镜像对称≡εeff1 传递、|S11|max<-10dB、|S21|≥0.90、"
      f"互易 ≤0.5dB；β2 原始读数仅诊断不判）")
