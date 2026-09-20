"""引擎健康度基准：mline 锚网格收敛 harness（openEMS 侧）。

物理裁判：openEMS 升级/换机/模板迁移后重跑本脚本——mline 均匀线
多点网格求解，β→εeff（金标准判据 #162），结果入库
runs/benchmark/mline_mesh_convergence.json。

判据显式决策（内核=
core/anchor_verdict.mline_benchmark_verdict，与 HFSS 探针
scripts/hfss_mline_probe.py 同一事实源）：
1. 收敛性：最细两档 εeff 相对移动 <1%（不变）；
2. 主锚（金标准）：最细档 εeff 对 openEMS β 金标准 2.886 |Δ|≤2%——
   本锚 εeff 由 openEMS CalcPort β 推导，"对金标准"门= #189 收敛值族
   （2.8813~2.8884）在升级/换机/模板迁移后复跑的复现一致性；
3. 副锚（解析哨兵）：最细档 εeff 对 HJ 闭式 |Δ|≤3%（放宽口径，替代旧
   ±2% HJ 单锚——钉死几何/频点实测系统偏移全谱 openEMS +1.18%/HFSS
   +2.36%/+2.53%，旧单门对该锚偏严；HJ 为独立来源解析
   锚（#118），完全降级会失去哨兵；移出准静态有效域须显式重标定两锚）；
4. 健康：每档 |S11|max<-10dB（50Ω 匹配线）。
历史回放不误杀：#189 最细档 2.8813 → 对金标准 −0.16%/对 HJ +1.01%，
双锚均在门内。工作目录参数化（#198 教训）。
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.core.anchor_verdict import EPS_EFF_MLINE_GOLD, mline_benchmark_verdict

parser = argparse.ArgumentParser()
parser.add_argument("--meshes", default="0,0.6,0.4,0.25",
                    help="逗号分隔网格分辨率 mm；0=自动 λ_sub/50（官方口径）")
parser.add_argument("--freq", default="2.5", help="对照频率 GHz")
args = parser.parse_args()

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "runs" / "benchmark"
W, LINE_LEN = 1.113, 40.0  # 50Ω mline 锚标称点（权威口径表 §1）
F_TARGET = float(args.freq) * 1e9


def _beta_eps(work: Path) -> tuple[float, float]:
    """读 CalcPort β→εeff（金标准），返回 (eps_eff, f_med_hz)。"""
    with open(work / "port_beta.csv", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    bf = np.array([float(r[0]) for r in rows])
    bb = np.array([float(r[1]) for r in rows])
    sel = (bf >= 0.96 * F_TARGET) & (bf <= 1.04 * F_TARGET)
    beta = float(np.median(bb[sel]))
    f_med = float(np.median(bf[sel]))
    return (beta * 299792458.0 / (2 * np.pi * f_med)) ** 2, f_med


def main() -> int:
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    _, eps_hj = forward_z0(W, float(args.freq), stackup)

    meshes = [float(m) for m in args.meshes.split(",")]
    entries = []
    for mesh in meshes:
        tag = "auto" if mesh == 0 else f"{mesh}"
        work = OUT_DIR / f"mline_m{tag}"
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type="openems", exe_path=resolve_openems_exe(),
            working_dir=str(work), freq_range_ghz=(2.25, 2.75),
            mesh_resolution_mm=mesh,
            extra_params={"solve_timeout_s": 36000}))
        assert solver.connect(), "openEMS 不可用"
        t0 = time.time()
        ok = solver.build_geometry({"template": "mline",
                                    "params": {"w_mm": W,
                                               "line_len_mm": LINE_LEN}})
        assert ok, f"mesh={tag} build 失败"
        result = solver.solve()
        wall = time.time() - t0
        if not (result.success and result.s_params is not None):
            entries.append({"mesh_mm": mesh, "ok": False,
                            "message": result.message})
            print(f"mesh={tag}: FAIL {result.message}", flush=True)
            continue
        s11 = result.s_params[:, 0, 0]
        m11_max = float(np.max(20 * np.log10(np.abs(s11) + 1e-12)))
        eps_eff, _ = _beta_eps(work)
        delta = (eps_eff / eps_hj - 1) * 100
        delta_gold = (eps_eff / EPS_EFF_MLINE_GOLD - 1) * 100
        entries.append({"mesh_mm": mesh, "ok": True, "wall_s": round(wall),
                        "s11_max_db": round(m11_max, 2),
                        "eps_eff": round(eps_eff, 5),
                        "delta_vs_hj_pct": round(delta, 3),
                        "delta_vs_gold_pct": round(delta_gold, 3)})
        print(f"mesh={tag}: eps_eff={eps_eff:.4f} Δ_HJ={delta:+.2f}% "
              f"Δ_gold={delta_gold:+.2f}% "
              f"|S11|max={m11_max:.1f}dB wall={wall:.0f}s", flush=True)

    # 收敛性：最细两档相对移动；健康：ok 档全带最差 |S11|max
    ok_entries = [e for e in entries if e.get("ok")]
    convergence = None
    if len(ok_entries) >= 2:
        a, b = ok_entries[-2]["eps_eff"], ok_entries[-1]["eps_eff"]
        convergence = round(abs(b - a) / b * 100, 4)
    eps_finest = ok_entries[-1]["eps_eff"] if ok_entries else None
    s11_worst = max((e["s11_max_db"] for e in ok_entries), default=None)
    bench = mline_benchmark_verdict(eps_finest, convergence, s11_worst,
                                    eps_gold=EPS_EFF_MLINE_GOLD,
                                    eps_hj=eps_hj)
    verdict = str(bench["verdict"])

    out = {"anchor": "mline", "w_mm": W, "line_len_mm": LINE_LEN,
           "eps_hj_closed_form": round(eps_hj, 5),
           "eps_gold_standard": EPS_EFF_MLINE_GOLD,
           "judge_freq_ghz": float(args.freq),
           "entries": entries,
           "convergence_finest2_pct": convergence,
           "delta_vs_gold_pct": (round(float(bench["delta_gold_pct"]), 3)
                                 if bench["delta_gold_pct"] is not None
                                 else None),
           "delta_vs_hj_pct": (round(float(bench["delta_hj_pct"]), 3)
                               if bench["delta_hj_pct"] is not None
                               else None),
           "verdict": verdict,
           "criteria": {"convergence_pct_lt": 1.0,
                        "delta_vs_gold_pct_abs_le": 2.0,
                        "delta_vs_hj_pct_abs_le": 3.0,
                        "s11_max_db_lt": -10}}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "mline_mesh_convergence.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"ENGINE_BENCHMARK_MLINE_{verdict}（判据：收敛<1%、最细档对金标准"
          f"≤2%/对 HJ ≤3% 双锚、|S11|max<-10dB）"
          + (f" reason: {bench['reason']}" if bench["reason"] else "")
          + f" → {OUT_DIR / 'mline_mesh_convergence.json'}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
