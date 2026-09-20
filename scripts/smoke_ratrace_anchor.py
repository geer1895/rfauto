"""rat-race 冒烟 pt5（#208 理论核验轮后）：规范角位 + 进程隔离激励轮转全 S 矩阵。

pt1（runs/ratrace_smoke/pt1）= 旧均匀 90° 端口布局的判废证据（全 ~-33dB）；
pt2/pt3/pt4 = 进程内轮转三连败证据链（wrapped-deleted/CSX is not set，
Run(cleanup=True) 销毁绑定对象——#208）；
pt5 = excite_port=1..4 渲染 4 份单激励脚本、进程隔离各跑一次（全库已
验证的单激励安全模式 ×4），适配器层装配 4×4 → ratrace.s4p。

锚判据（WP2.3，#208 定版；端口标签与模板/fake 裁判三方一致）：
1. β 金标准：CalcPort β → εeff 对照 skrf HJ ±2%（Σ 馈，mesh=0.4mm 收敛档）；
2. 均分：|S21|(out1)/|S41|(out2) 各 -3±1dB，均分差 ≤0.5dB；
3. 隔离：|S31|(Δ) ≤ -20dB（锚口径）；|S24|(out1↔out2) ≤ -15dB；
4. 匹配：|S11|max ≤ -10dB；
5. 互易：max ||Sij|-|Sji|| ≤ 0.02（线性幅值）。
工作目录参数化（#198 教训）。证据链 runs/ratrace_smoke/pt5/。
"""
import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import resolve_openems_exe
from rfauto.adapters.openems_rotation import solve_smatrix_openems
from rfauto.core.synthesis import Stackup, forward_z0

parser = argparse.ArgumentParser()
parser.add_argument("--pt", default="pt5")
args = parser.parse_args()

W_RING = 0.6035
H_SUB, ER, F_MID = 0.508, 3.66, 2.5
MESH = 0.4  # 收敛档（引擎基准曲线判读）

stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
_, eps_hj_feed = forward_z0(1.1134, F_MID, stackup)

work = Path(f"runs/ratrace_smoke/{args.pt}")
t0 = time.time()
result = solve_smatrix_openems(
    work, template="ratrace",
    params={"w_ring_mm": W_RING, "w_feed_mm": 1.1134},
    freq_range_ghz=(2.25, 2.75), mesh_resolution_mm=MESH,
    n_ports=4, timeout_s=36000, exe_path=resolve_openems_exe())
print(f"solve_s={time.time() - t0:.0f} ok={result['ok']} "
      f"errs={result.get('errors') or []}", flush=True)
assert result["ok"] and result.get("s_params") is not None
assert result["s_params"].shape[1] == 4, \
    f"期望 4 端口全矩阵，得 {result['s_params'].shape}"
print(f"s4p: {result['s4p_path']}")

f = np.asarray(result["freq_ghz"]) * 1e9
s = result["s_params"]
i_mid = int(np.argmin(np.abs(f - F_MID * 1e9)))

# 1) β 金标准（CalcPort port1——Σ 馈）
with open(work / "p1" / "port_beta.csv", encoding="utf-8") as fh:
    rows = list(csv.reader(fh))[1:]
bf = np.array([float(r[0]) for r in rows])
bb = np.array([float(r[1]) for r in rows])
sel = (bf >= 0.96 * F_MID * 1e9) & (bf <= 1.04 * F_MID * 1e9)
beta = float(np.median(bb[sel]))
eps_feed = (beta * 299792458.0 / (2 * np.pi * F_MID * 1e9)) ** 2
d_feed = (eps_feed / eps_hj_feed - 1) * 100
print(f"eps_hj(50Ω馈)={eps_hj_feed:.4f} engine(beta)={eps_feed:.4f} "
      f"delta={d_feed:+.2f}%")

# 2) 幅度域 @2.5GHz（端口标签：1=Σ、2=out1、3=Δ、4=out2，#208）
s21 = 20 * np.log10(abs(s[i_mid, 1, 0]) + 1e-12)
s41 = 20 * np.log10(abs(s[i_mid, 3, 0]) + 1e-12)
s31 = 20 * np.log10(abs(s[i_mid, 2, 0]) + 1e-12)   # Δ 隔离
s24 = 20 * np.log10(abs(s[i_mid, 3, 1]) + 1e-12)   # out1↔out2 隔离
s11 = 20 * np.log10(abs(s[i_mid, 0, 0]) + 1e-12)
balance = abs(s21 - s41)
# 相位：Σ 激励输出同相；Δ 激励输出反相（0-基 [1,2] vs [3,2]）
ph_sum = abs(np.angle(s[i_mid, 1, 0]) - np.angle(s[i_mid, 3, 0]))
ph_del = abs(abs(np.angle(s[i_mid, 1, 2]) - np.angle(s[i_mid, 3, 2])) - np.pi)
print(f"@2.5GHz: S21={s21:.2f}dB S41={s41:.2f}dB (均分差 {balance:.2f}dB) "
      f"S31(Δ隔离)={s31:.1f}dB S24={s24:.1f}dB S11={s11:.1f}dB")
print(f"相位: Σ激励输出差={ph_sum:.3f}rad（应≈0） "
      f"Δ激励输出反相差偏={ph_del:.3f}rad（应≈0）")
s_mid = s[i_mid]
recip = max(abs(s_mid[i, j]) - abs(s_mid[j, i])
            for i in range(4) for j in range(4))
print(f"互易 max||Sij|-|Sji||={recip:.4f}（线性）")

ok = (abs(d_feed) <= 2.0
      and balance <= 0.5
      and abs(s21 - (-3.0)) <= 1.0 and abs(s41 - (-3.0)) <= 1.0
      and s31 <= -20.0 and s24 <= -15.0 and s11 <= -10.0
      and recip <= 0.02)
verdict = "PASS" if ok else "FAIL"
print(f"RATRACE_PROBE_{verdict}（判据：β±2%、|S21|/|S41| -3±1dB 差≤0.5dB、"
      f"|S31|≤-20dB、|S24|≤-15dB、|S11|≤-10dB、互易≤0.02）")
