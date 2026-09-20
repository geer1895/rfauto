"""Gysel 功分器真跑冒烟（WP2.3 横向变体，#206 理论核验轮后落地；P2⑪ pt3 定案）。

拓扑（#206 定版，对照 Microwaves101 Gysel even/odd 口径）：六节 λ/4 环——
P1—70.7Ω λ/4 臂—P2/P3；P2/P3—50Ω λ/4 隔离线—Δ1/Δ2（各接 50Ω LumpedElement
端接）；Δ1—50Ω λ/2 桥带（中点开路）—Δ2。三端口对外（标准双激励 footer：
S23 第二激励 run 出输出互隔离）。

几何版本：
- pt1/pt2：矩形环（Δ 在角部，桥带继承 2·arm_len=36.324mm，+2.32% 二阶偏差）；
  pt2 基线 PASS（runs/gysel_smoke/pt2_pass.log）：β+0.94%、均分差 0.00dB、
  S32=-32.6dB、S11=-26.7dB，solve 1702s/run×双激励。
- pt3+（P2⑪ L-jog 等长变体）：Δ 节点内移到 x=±iso_len（桥带跨度
  2·iso_len=35.500mm=λ/2 精确），隔离线竖直段 YJ=iso_len−jog + 顶端横移
  jog=|arm_len−iso_len|=0.412mm 保 λ/4 电长度。电路级 @f0 S32/S11 由 -34.8dB
  → ≤-88dB（装配实测）；EM 地板由两处未切角 90° 弯折决定，估 -35~-40dB 档。

锚判据（WP2.3，对照 smoke_atten_pi_anchor 判据模式，硬门不变）：
1. β 金标准：CalcPort β → εeff 对照 skrf HJ ±2%（P1 50Ω 馈，
   mesh=0.4mm 收敛档）；
2. 均分：|S21|/|S31| @2.5GHz 各 -3±1dB，均分差 ≤0.5dB；
3. 隔离：|S32| ≤ -15dB（wilkinson 隔离电阻同门；理想 f0 数值零）；
4. 匹配：|S11| ≤ -10dB。
定案判据（P2⑪，非硬门）：对比 pt2 矩形基线的 S32/S11 改善量如实落账——
EM 弯折/网格地板吃掉理论增益时如实 PARTIAL 不凑绿（#122）。
工作目录参数化（#198 教训）。证据链 runs/gysel_smoke/。
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
from rfauto.adapters.openems_templates import _gysel_layout
from rfauto.core.synthesis import Stackup, forward_z0

parser = argparse.ArgumentParser()
parser.add_argument("--pt", default="pt1")
args = parser.parse_args()

W_ARM, W_FEED = 0.6035, 1.1134
ARM_LEN, ISO_LEN = 18.162, 17.75
H_SUB, ER, F_MID = 0.508, 3.66, 2.5
MESH = 0.4  # 收敛档（引擎基准曲线判读）

# pt2 矩形基线（runs/gysel_smoke/pt2_pass.log 原文数字，P2⑪ 定案对照）
PT2_BASELINE = {"beta_delta_pct": 0.94, "balance_db": 0.00,
                "s32_db": -32.6, "s11_db": -26.7, "solve_s": 1702}

stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
_, eps_hj_feed = forward_z0(W_FEED, F_MID, stackup)

params = {"w_arm_mm": W_ARM, "w_feed_mm": W_FEED,
          "arm_len_mm": ARM_LEN, "iso_len_mm": ISO_LEN}
lay = _gysel_layout(params)
print(f"[{args.pt}] 几何=L-jog 等长变体：jog={lay['jog']:.4f}mm YJ={lay['yj']:.4f}mm "
      f"XB=±{lay['xb']:.3f}mm 桥带跨度={2 * lay['xb']:.3f}mm（50Ω λ/2 精确；"
      f"矩形旧版 {2 * ARM_LEN:.3f}mm）", flush=True)

work = Path(f"runs/gysel_smoke/{args.pt}")
solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems", exe_path=resolve_openems_exe(),
    working_dir=str(work), freq_range_ghz=(2.25, 2.75),
    mesh_resolution_mm=MESH,
    extra_params={"solve_timeout_s": 36000}))
assert solver.connect(), "openEMS 不可用"
assert solver.build_geometry({"template": "gysel", "params": params})
t0 = time.time()
result = solver.solve()
solve_s = time.time() - t0
print(f"solve_s={solve_s:.0f} success={result.success} "
      f"msg={result.message}", flush=True)
assert result.success and result.s_params is not None

f = np.asarray(result.freq_ghz) * 1e9
s = result.s_params
i_mid = int(np.argmin(np.abs(f - F_MID * 1e9)))

# 1) β 金标准（CalcPort port1——P1 50Ω 馈）
with open(work / "port_beta.csv", encoding="utf-8") as fh:
    rows = list(csv.reader(fh))[1:]
bf = np.array([float(r[0]) for r in rows])
bb = np.array([float(r[1]) for r in rows])
sel = (bf >= 0.96 * F_MID * 1e9) & (bf <= 1.04 * F_MID * 1e9)
beta = float(np.median(bb[sel]))
eps_feed = (beta * 299792458.0 / (2 * np.pi * F_MID * 1e9)) ** 2
d_feed = (eps_feed / eps_hj_feed - 1) * 100
print(f"eps_hj(50Ω馈)={eps_hj_feed:.4f} engine(beta)={eps_feed:.4f} "
      f"delta={d_feed:+.2f}%")

# 2) 幅度域 @2.5GHz（端口：1=P1 输入、2/3=P2/P3 输出；CSV 部分矩阵
# S23=第二激励 run 的输出互隔离，写入 [1,2]/[2,1]）
s21 = 20 * np.log10(abs(s[i_mid, 1, 0]) + 1e-12)
s31 = 20 * np.log10(abs(s[i_mid, 2, 0]) + 1e-12)
s32 = 20 * np.log10(abs(s[i_mid, 2, 1]) + 1e-12)   # 输出互隔离
s11 = 20 * np.log10(abs(s[i_mid, 0, 0]) + 1e-12)
balance = abs(s21 - s31)
ph = abs(np.angle(s[i_mid, 1, 0]) - np.angle(s[i_mid, 2, 0]))
print(f"@2.5GHz: S21={s21:.2f}dB S31={s31:.2f}dB (均分差 {balance:.2f}dB) "
      f"S32(隔离)={s32:.1f}dB S11={s11:.1f}dB "
      f"输出相位差={ph:.3f}rad（应≈0）")

# 2b) 带内谷/带边（P2⑪ 归因用：隔离谷位与带边隔离，s11_db_min 语义 #195）
s32_band = 20 * np.log10(np.abs(s[:, 2, 1]) + 1e-12)
s11_band = 20 * np.log10(np.abs(s[:, 0, 0]) + 1e-12)
i_s32_min = int(np.argmin(s32_band))
i_s11_min = int(np.argmin(s11_band))
print(f"带内谷: S32_min={s32_band[i_s32_min]:.1f}dB@{f[i_s32_min] / 1e9:.3f}GHz "
      f"S11_min={s11_band[i_s11_min]:.1f}dB@{f[i_s11_min] / 1e9:.3f}GHz")
for fe in (2.3, 2.7):
    ie = int(np.argmin(np.abs(f - fe * 1e9)))
    print(f"带边 @{fe}GHz: S32={s32_band[ie]:.1f}dB S11={s11_band[ie]:.1f}dB")

ok = (abs(d_feed) <= 2.0
      and balance <= 0.5
      and abs(s21 - (-3.0)) <= 1.0 and abs(s31 - (-3.0)) <= 1.0
      and s32 <= -15.0 and s11 <= -10.0)
verdict = "PASS" if ok else "FAIL"
print(f"GYSEL_PROBE_{verdict}（判据：β±2%、|S21|/|S31| -3±1dB 差≤0.5dB、"
      f"|S32|≤-15dB、|S11|≤-10dB）")

# 3) P2⑪ 定案：对比 pt2 矩形基线的改善量（负=更深=改善），如实落账
d_s32 = s32 - PT2_BASELINE["s32_db"]
d_s11 = s11 - PT2_BASELINE["s11_db"]
print(f"GYSEL_P2_11_VS_PT2: ΔS32={d_s32:+.1f}dB（{s32:.1f} vs 基线 "
      f"{PT2_BASELINE['s32_db']}）ΔS11={d_s11:+.1f}dB（{s11:.1f} vs 基线 "
      f"{PT2_BASELINE['s11_db']}）Δβ={d_feed:+.2f}% vs {PT2_BASELINE['beta_delta_pct']:+.2f}% "
      f"solve {solve_s:.0f}s vs {PT2_BASELINE['solve_s']}s")
