"""临时冒烟：CPW 锚单点真跑（50Ω CPWG 线，综合 w=0.849mm gap=0.2 L=40mm）。

判据（同 mline 锚，#189）：S21 相位斜率→εeff 对照 CPWG 共形映射闭式
±2%（β 金标准口径，#161/#162；参照系=CPWG——openEMS 官方口径
z-min=PEC 强制地，#193 参照系错位教训/#198 闭式收口）；
|S11| 判废线（50Ω 匹配线）。证据链 runs/cpw_smoke/；脚本保留为引擎基准件。
"""
import csv
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.core.calculators import _cpwg_ri
from rfauto.core.synthesis import synthesize_cpw_model

GAP, L = 0.2, 40.0
W = synthesize_cpw_model(gap_mm=GAP, line_len_mm=L).params["w_mm"]
eps_ref, z0_ref = _cpwg_ri(W, GAP, 0.508, 3.66)
print(f"CPWG 综合: w={W}mm gap={GAP}mm  闭式 Z0=50Ω εeff={eps_ref:.4f}")

work = Path("runs/cpw_smoke/pt4")  # pt1-3 历史证据链见 #198
solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems", exe_path=resolve_openems_exe(),
    working_dir=str(work), freq_range_ghz=(2.25, 2.75), mesh_resolution_mm=0,
    extra_params={"solve_timeout_s": 36000}))
assert solver.connect(), "openEMS 不可用"
assert solver.build_geometry({"template": "cpw",
                              "params": {"w_mm": W, "gap_mm": GAP,
                                         "line_len_mm": L}})
t0 = time.time()
result = solver.solve()
print(f"solve_s={time.time() - t0:.0f} success={result.success} "
      f"msg={result.message}", flush=True)
assert result.success and result.s_params is not None

f = np.asarray(result.freq_ghz)
s21 = result.s_params[:, 0, 1]
s11 = result.s_params[:, 0, 0]
m11 = 20 * np.log10(np.abs(s11) + 1e-12)

# β 金标准（#162/#189 同法）：读 CalcPort 自算 β——不用 uf_ref 相位
# （#161：相位含端口分解伪象，测量面间路径含馈线段有歧义）。
with open(work / "port_beta.csv", encoding="utf-8") as fh:
    _rows = list(csv.reader(fh))[1:]
bf = np.array([float(r[0]) for r in _rows])
bbeta = np.array([float(r[1]) for r in _rows])
sel = (bf >= 2.4e9) & (bf <= 2.6e9)
beta_med = float(np.median(bbeta[sel]))
f_med = float(np.median(bf[sel]))
eps_engine = (beta_med * 299792458.0 / (2 * np.pi * f_med)) ** 2
delta = (eps_engine / eps_ref - 1) * 100

print(f"eps_ref(CPWG 闭式)={eps_ref:.4f} "
      f"eps_engine(beta)={eps_engine:.4f} delta={delta:+.2f}%")
print(f"s11_max_db={m11.max():.1f} s21_mag_mean={np.mean(np.abs(s21)):.4f}")
verdict = "PASS" if (m11.max() < -10 and abs(delta) <= 2.0) else "FAIL"
print(f"CPW_PROBE_{verdict}（判据：匹配线 |S11|max<-10dB，"
      f"|Δεeff|≤2% β 金标准口径）")
