"""发夹线（hairpin）带通滤波器真机冒烟（WP2.3 Tier1，C13 闭式裁判对照）。

理论核验轮口径见 rfauto/adapters/openems_templates.py 文末 WP2.3 hairpin 段
（#206）：λg/2 谐振器 + 平行耦合（k=(Z0e−Z0o)/(Z0e+Z0o)，KJ 1984 闭式）+
抽头外部 Q（Q_e=(π/2)(Z0/Z_r)sec²(πτ)）。设计点由 C13 耦合矩阵综合给出
（synthesize_bpf_model → k=FBW·|M|、Q_e=1/(FBW·|M0,1|²)），几何映射在
openems_templates.hairpin_design_from_order。

裁判（独立来源）=C13 矩阵理想频响 coupling_matrix_response：
- f0 处 |S21|≈0dB、|S11| 深零；
- 带边 f0(1±FBW/2) 回损≈−RL、|S21|≈纹波电平；
- 带外抑制。

本冒烟只报实测 vs 闭式，判据从宽（首次真跑；U 形折叠/同臂耦合/T 抽头
不连续性均未校准，#206 假设清单）：带内最小插损 ≤3dB、带内纹波 ≤4dB、
带内回损 ≤−8dB、峰位偏差 ≤8%；β 金标准 ±3%（馈线段=50Ω）。

运行（后台+日志轮询，#157）：证据链 runs/hairpin_smoke/<pt>/。
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
    hairpin_design_from_order,
)
from rfauto.core.calculators import coupling_matrix_response
from rfauto.core.synthesis import Stackup, forward_z0

F0, H_SUB, ER = 2.5, 0.508, 3.66


def dump_point_params(work: Path, params: dict, mesh_mm: float, f0_ghz: float,
                      fbw: float, rl_db: float) -> Path:
    """点目录 params.json 落盘（import_workdir_runs 键路径契约 params；
    字段=该点实跑几何（hairpin_design_from_order 圆整值）+设计输入/网格档，
    #320）。单曲线点目录（pt/sparams.csv）读取端按单曲线目录认无引用 JSON。
    """
    from rfauto.service.dataset_service import write_workdir_params_json

    return write_workdir_params_json(work, {**params, "f0_ghz": f0_ghz,
                                            "fbw": fbw, "rl_db": rl_db,
                                            "mesh_mm": mesh_mm})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pt", default="pt1")
    parser.add_argument("--mesh", type=float, default=0.4)
    parser.add_argument("--order", type=int, default=3)
    parser.add_argument("--fbw", type=float, default=0.05)
    parser.add_argument("--rl", type=float, default=20.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    args = parser.parse_args(argv)

    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")

    design = hairpin_design_from_order(args.order, F0, args.fbw, args.rl)
    assert design["gap_mm"] is not None, (
        "本冒烟只支持等缝锚（N=3 等 k）；非等 k 变体走 gaps_mm 列表")
    params = {
        "order": design["order"],
        "w_mm": round(design["w_mm"], 4),
        "arm_len_mm": round(design["arm_len_mm"], 4),
        "arm_gap_mm": round(design["arm_gap_mm"], 4),
        "gap_mm": round(design["gap_mm"], 4),
        "tap_frac": round(design["tap_frac"], 6),
    }
    print("design:", {k: params[k] for k in params}, flush=True)
    _k_str = "[" + ", ".join(f"{v:.5f}" for v in design["k_list"]) + "]"
    print(f"k_list: {_k_str} Q_e={design['qe']:.4f}", flush=True)

    _, eps_hj_feed = forward_z0(params["w_mm"], F0, stackup)

    work = Path(f"runs/hairpin_smoke/{args.pt}")
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work), freq_range_ghz=(F0 - 0.25, F0 + 0.25),
        mesh_resolution_mm=args.mesh,
        extra_params={"solve_timeout_s": args.timeout}))
    assert solver.connect(), "openEMS 不可用"
    assert solver.build_geometry({"template": "hairpin", "params": params})
    dump_point_params(work, params, args.mesh, F0, args.fbw, args.rl)
    t0 = time.time()
    result = solver.solve()
    print(f"solve_s={time.time() - t0:.0f} success={result.success} "
          f"msg={result.message}", flush=True)
    assert result.success and result.s_params is not None, "开EMS 真跑失败"

    f_hz = np.asarray(result.freq_ghz) * 1e9
    s = result.s_params
    f_ghz = f_hz / 1e9

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

    # ── C13 闭式裁判（同频轴）──
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
    # 带外（>1.5×带边）抑制
    band_lo, band_hi = F0 * (1 - args.fbw / 2), F0 * (1 + args.fbw / 2)
    stop = (f_ghz < band_lo - 1.5 * (band_hi - band_lo)) | \
           (f_ghz > band_hi + 1.5 * (band_hi - band_lo))
    rej = float(s21_db[stop].min()) if bool(stop.any()) else float("nan")

    i_mid = int(np.argmin(np.abs(f_ghz - F0)))
    print(f"@2.5GHz: |S21|={s21_db[i_mid]:.2f}dB |S11|={s11_db[i_mid]:.1f}dB"
          f"（C13 理想 |S21|={ideal_s21[i_mid]:.3f} |S11|={ideal_s11[i_mid]:.1f}）",
          flush=True)
    print(f"实测：峰位={f_peak:.4f}GHz 带内最小插损={il_min:.2f}dB "
          f"带内纹波={ripple:.2f}dB 带内回损={s11_band:.1f}dB "
          f"带外抑制={rej:.1f}dB", flush=True)
    _ideal_ripple = float(ideal_s21[band].max() - ideal_s21[band].min())
    _ideal_rl = float(ideal_s11[band].max())
    print(f"C13 理想：带内纹波={_ideal_ripple:.3f}dB 带边回损={_ideal_rl:.1f}dB",
          flush=True)

    ok = (il_min <= -0.2 and il_min >= -3.0 and ripple <= 4.0
          and s11_band <= -8.0 and abs(f_peak - F0) / F0 <= 0.08
          and (np.isnan(d_feed) or abs(d_feed) <= 3.0))
    verdict = "PASS" if ok else "FAIL"
    print(f"HAIRPIN_PROBE_{verdict}（判据：带内最小插损 -3~-0.2dB、带内纹波 "
          f"≤4dB、带内回损 ≤-8dB、峰位偏差 ≤8%、β±3%）", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
