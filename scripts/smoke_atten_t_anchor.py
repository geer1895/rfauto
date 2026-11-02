"""临时冒烟：T 型电阻衰减器真跑（10dB/50Ω，两臂各串 25.975Ω + 中点对地 35.136Ω）。

锚判据（WP2.3 横向变体，沿用 atten_pi 成型模式）：
1. β 金标准：CalcPort β → εeff 对照 skrf HJ ±2%（mesh=0.4mm 收敛档）；
2. 衰减平坦：|S21| @2.5GHz 对照目标 -10dB ±0.5dB（ABCD 电阻网络
   确定性裁判同源）；
3. 匹配：|S11|max <-12dB（商用 lumped 模块回损规格地板）。
工作目录参数化（#198 教训）。证据链 runs/atten_t_smoke/。
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

ATTEN_DB = 10.0
W = 1.1134
H_SUB, ER, F_MID = 0.508, 3.66, 2.5
MESH = 0.4  # 收敛档（引擎基准曲线判读）

stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
_, eps_hj = forward_z0(W, F_MID, stackup)

work = Path(f"runs/atten_t_smoke/{args.pt}")
solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems", exe_path=resolve_openems_exe(),
    working_dir=str(work), freq_range_ghz=(2.25, 2.75),
    mesh_resolution_mm=MESH,
    extra_params={"solve_timeout_s": 36000}))
assert solver.connect(), "openEMS 不可用"
assert solver.build_geometry({"template": "atten_t",
                              "params": {"atten_db": ATTEN_DB, "w_mm": W,
                                         "shunt_off_mm": 6.0,
                                         "r_series_arm_ohm": 25.975,
                                         "r_shunt_mid_ohm": 35.136}})
t0 = time.time()
result = solver.solve()
print(f"solve_s={time.time() - t0:.0f} success={result.success} "
      f"msg={result.message}", flush=True)
assert result.success and result.s_params is not None

f = np.asarray(result.freq_ghz) * 1e9
s11 = result.s_params[:, 0, 0]
s21 = result.s_params[:, 0, 1]

# 1) β 金标准（CalcPort port1）
with open(work / "port_beta.csv", encoding="utf-8") as fh:
    rows = list(csv.reader(fh))[1:]
bf = np.array([float(r[0]) for r in rows])
bb = np.array([float(r[1]) for r in rows])
sel = (bf >= 0.96 * F_MID * 1e9) & (bf <= 1.04 * F_MID * 1e9)
beta = float(np.median(bb[sel]))
eps = (beta * 299792458.0 / (2 * np.pi * F_MID * 1e9)) ** 2
delta = (eps / eps_hj - 1) * 100

# 2) 衰减平坦 @2.5GHz
i_mid = int(np.argmin(np.abs(f - F_MID * 1e9)))
s21_db = 20 * np.log10(np.abs(s21[i_mid]) + 1e-12)
atten_dev = abs(s21_db - (-ATTEN_DB))

# 3) 匹配
s11_max = float(np.max(20 * np.log10(np.abs(s11) + 1e-12)))

print(f"eps_hj={eps_hj:.4f} engine(beta)={eps:.4f} delta={delta:+.2f}%")
print(f"@2.5GHz: |S21|={s21_db:.2f}dB (目标 {-(ATTEN_DB)}dB, "
      f"dev={atten_dev:.2f}dB)  |S11|max={s11_max:.1f}dB")
ok = (atten_dev <= 0.5 and s11_max < -12.0 and abs(delta) <= 2.0)
verdict = "PASS" if ok else "FAIL"
print(f"ATTEN_T_PROBE_{verdict}（判据：|Δεeff|≤2% HJ、"
      f"|S21| vs 目标 ±0.5dB、|S11|max<-12dB 商用 lumped 地板）")
