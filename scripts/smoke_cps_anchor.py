"""CPS 共面带锚冒烟（C9 传输线族 II）+ 预声明判读门（w2f-c9-refs 改写，2026-09-18）。

真机：标称几何 w=2.95mm gap=0.5 L=40mm 保持（真机配对 #158：pt1 与复跑同几何；
docs meta 同源）。口径修订（refs §11.1）：`_cps_ri` 经 FD 定标（有效厚度
γ(εr)=1+0.9014·εr^−0.6361）后该几何 Z0=116.17Ω/εeff=1.6765（旧裸映射 120Ω/1.5712
撤）；真值锚=core/quasistatic_fd.py 裁判现算（标称 εeff_FD≈1.667，收尾批临时 FD
≈1.68 同口径）。LumpedPort R=闭式 Z0（render 期同源 _cps_ri），CalcPort 同参考。

判据（预声明，#122 不因结果改门）：
  G1 带内 |S11|max < −15 dB（R=定标 Z0 匹配线；±10% 阻抗偏差对应 −26 dB，门留余量）；
  G2 εeff(S21 解缠相位斜率, L=line_len) vs εeff_FD：≤3% PASS / ≤7% PARTIAL / 其余
     FAIL——LumpedPort 无 β 属性（sma_launcher 同坑），相位法含端口元落格 ±1 BASE
     的线长口径不确定度（±1.14mm/40mm → εeff ±5.7%，pt1 postmortem），PARTIAL 档
     即此口径地板；**w2f 后续定标批 ②**：模板渲染段落盘 port_beta.csv（端口元
     y 坐标/实测差分线长 plane_dist_m，同 SSL beta 块先例），本判读器优先用实测
     线长替代标称 L（line_len_source=port_beta_csv），地板压到 ~±1%；无该文件时
     回退标称 L（line_len_source=nominal，旧 pt 兼容）。
  INFO 定标闭式 vs FD（应 ≤1.2%，闭式漂移即报警，不设门）。
pt1 基线：|S11|max −23.9 dB 过；εeff 1.8909 vs FD 1.667 +13.4% → FAIL（旧口径
vs 裸闭式 +20.35%）；引擎侧候选（MUR 非 PML、基板 4 格、端口线长）由复跑分离。
工作目录参数化（#198 教训）。证据链 runs/cps_smoke/<pt>/。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.core.calculators import _cps_ri

BAND_HZ = (2.4e9, 2.6e9)
C0 = 299792458.0
#: 预声明门
GATES = {
    "s11_max_db": -15.0,        # G1
    "eps_pass_pct": 3.0,        # G2 PASS
    "eps_partial_pct": 7.0,     # G2 PARTIAL 上限（端口元落格线长口径地板 ±5.7%）
    "closed_vs_fd_info_pct": 1.2,
}
#: plane_dist_m 合法性守卫（C4 followUp 2026-09-21）：实测差分线长相对标称 L
#: 的物理偏差上界=端口元落格 ±1 格（粗网格 ±1.14mm/40mm≈±2.85%，εeff 口径
#: ±5.7%）；超界（或非有限/非正）视为坏数据——**多报不放过**（#316）：拒用该
#: 值、回退标称 L 并显式记 line_len_source=nominal_invalid_plane_dist，
#: 不静默消费（否则坏线长可直接翻转 G2 判向）。
PLANE_DIST_MAX_REL_DEV = 0.05
#: 标称线长口径的 εeff 地板（±1 格 → εeff ±2·BASE/L；缺省档 BASE=1.14/L=40）
NOMINAL_LEN_FLOOR_PCT = 5.7


def plane_dist_usable(plane_m: float, nominal_m: float,
                      max_rel_dev: float = PLANE_DIST_MAX_REL_DEV) -> bool:
    """纯函数守卫：port_beta.csv 实测线长是否可用（有限/正/对标称偏差 ≤5%）。"""
    if not (math.isfinite(plane_m) and plane_m > 0.0 and nominal_m > 0.0):
        return False
    return abs(plane_m / nominal_m - 1.0) <= max_rel_dev


def eps_from_s21_slope(f_hz: np.ndarray, s21: np.ndarray, length_m: float) -> float:
    sel = (f_hz >= BAND_HZ[0]) & (f_hz <= BAND_HZ[1])
    phase = np.unwrap(np.angle(s21[sel]))
    slope = np.polyfit(f_hz[sel], phase, 1)[0]          # dφ/df = −2π√εeff·L/c
    return float((-slope * C0 / (2 * np.pi * length_m)) ** 2)


def fd_anchor(w_mm: float, gap_mm: float, h_mm: float, eps_r: float) -> dict:
    """真值锚：core/quasistatic_fd.py 裁判现算（20·b 域，Richardson）。"""
    from rfauto.core.quasistatic_fd import cps_quasistatic

    fd = cps_quasistatic(w_mm, gap_mm, h_mm, eps_r)
    eps_cl, z0_cl = _cps_ri(w_mm, gap_mm, h_mm, eps_r)
    return {"eps_eff": fd.eps_eff, "z0_ohm": fd.z0_ohm, "z0_air_ohm": fd.z0_air_ohm,
            "eps_eff_closed": eps_cl, "z0_closed_ohm": z0_cl,
            "closed_vs_fd_pct": (eps_cl / fd.eps_eff - 1) * 100,
            "eps_eff_coarse": fd.eps_eff_coarse, "eps_eff_fine": fd.eps_eff_fine}


def judge_cps(f_hz: np.ndarray, s11: np.ndarray, s21: np.ndarray,
              line_len_m: float, anchor: dict,
              base_cell_m: float | None = None,
              line_len_source: str = "nominal",
              line_len_floor_pct: float | None = None) -> dict:
    """纯函数判读（预声明门 GATES；锚=FD 裁判 anchor）。base_cell_m 给定时附
    端口元落格 ±1 格的 εeff 敏感度（口径地板说明，不进门）。line_len_source=
    "port_beta_csv" 时 line_len_m 为模板落盘的实测差分线长（w2f 定标批 ②）；
    "nominal_invalid_plane_dist"=实测线长未过守卫被拒（C4 followUp），回退
    标称口径。line_len_floor_pct 给定时（main 按 ±1 格折算）在 G2 块附
    line_len_floor_pct 信息项（该线长源下 εeff 判读的口径地板，门值不动
    #122）——nominal 源时地板 ±5.7% 意味着 ≤3% PASS 判据本身落在此噪声内，
    判读须连读 floor 项。"""
    sel = (f_hz >= BAND_HZ[0]) & (f_hz <= BAND_HZ[1])
    s11_max_db = float(20 * np.log10(np.abs(s11[sel]).max() + 1e-12))
    eps_engine = eps_from_s21_slope(f_hz, s21, line_len_m)
    eps_fd = anchor["eps_eff"]
    g2 = abs(eps_engine / eps_fd - 1.0) * 100
    info = abs(anchor["closed_vs_fd_pct"])
    checks = {
        "G1_s11_max_db": {"gates": f"<{GATES['s11_max_db']}dB",
                          "value_db": round(s11_max_db, 2),
                          "pass": s11_max_db < GATES["s11_max_db"]},
        "G2_eps_vs_fd": {"gates": (f"≤{GATES['eps_pass_pct']}% PASS/"
                                   f"≤{GATES['eps_partial_pct']}% PARTIAL"),
                         "value_pct": round(g2, 2),
                         "pass": g2 <= GATES["eps_pass_pct"],
                         "partial": g2 <= GATES["eps_partial_pct"]},
        "INFO_closed_vs_fd": {"gates": f"≤{GATES['closed_vs_fd_info_pct']}%（信息项）",
                              "value_pct": round(info, 2),
                              "pass": info <= GATES["closed_vs_fd_info_pct"]},
    }
    if line_len_floor_pct is not None:
        checks["G2_eps_vs_fd"]["line_len_floor_pct"] = round(
            line_len_floor_pct, 2)
    numbers = {"eps_engine_s21_slope": round(eps_engine, 4),
               "eps_fd": round(eps_fd, 4), "eps_closed": round(anchor["eps_eff_closed"], 4),
               "s11_max_db": round(s11_max_db, 2), "line_len_m": round(line_len_m, 6),
               "line_len_source": line_len_source}
    if line_len_floor_pct is not None:
        numbers["line_len_floor_pct"] = round(line_len_floor_pct, 2)
    if base_cell_m:
        lo = eps_from_s21_slope(f_hz, s21, line_len_m + base_cell_m)
        hi = eps_from_s21_slope(f_hz, s21, line_len_m - base_cell_m)
        numbers["eps_engine_len_pm_1cell"] = [round(lo, 4), round(hi, 4)]
    if checks["G1_s11_max_db"]["pass"] and checks["G2_eps_vs_fd"]["pass"]:
        verdict = "PASS"
    elif checks["G1_s11_max_db"]["pass"] and checks["G2_eps_vs_fd"]["partial"]:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    notes = ["εeff 口径=S21 解缠相位斜率（LumpedPort 无 β）。线长源="
             f"{line_len_source}（port_beta_csv=模板落盘实测差分线长，w2f 定标"
             "批 ②；nominal=标称 L，含端口元落格 ±1 BASE → εeff ±5.7% 口径地板；"
             "nominal_invalid_plane_dist=实测线长未过守卫拒用回退标称，C4）；"
             "真值锚=FD 裁判现算。",
             "定标闭式与 FD 的差为信息项（≤1.2% 预期）；引擎偏差归引擎侧候选"
             "（MUR/基板格数/端口线长）由复跑分离。"]
    return {"verdict": verdict, "gates": checks, "numbers": numbers,
            "anchor": {k: round(v, 5) if isinstance(v, float) else v
                       for k, v in anchor.items()}, "notes": notes}


def main(argv: list[str] | None = None) -> dict:
    from rfauto.adapters.openems_solver import OpenEMSSolver

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pt", default="pt2")
    parser.add_argument("--mesh-mm", type=float, default=0.0,
                        help="网格 base 覆盖（0=官方 λ_sub/50 自动）")
    parser.add_argument("--w-mm", type=float, default=2.95,
                        help="带宽（缺省=TEMPLATE_NOMINAL 标称几何 2.95，配对 pt1）")
    parser.add_argument("--gap-mm", type=float, default=0.5)
    parser.add_argument("--h-mm", type=float, default=0.508)
    parser.add_argument("--er", type=float, default=3.66)
    parser.add_argument("--line-len-mm", type=float, default=40.0)
    parser.add_argument("--work-root", default="runs/cps_smoke",
                        help="证据链根目录（#198 工作目录参数化；pt 子目录）")
    parser.add_argument("--sub-cells", type=int, default=0,
                        help="基板 z 格数旋钮（0=缺省 4；复跑 8，w2f blocked 候选 c）")
    parser.add_argument("--nrts", type=int, default=0,
                        help="FDTD NrTS 上限（0=缺省 100000；细网格 150000）")
    parser.add_argument("--base-cell-mm", type=float, default=0.0,
                        help="端口元落格 ±1 格 εeff 敏感度括弧的格长（0=仅 "
                             "--mesh-mm>0 时给）")
    parser.add_argument("--boundary", default="",
                        help="六元边界覆盖（逗号分隔 x0,x1,y0,y1,bot,top；空="
                             "模板映射；MUR→PML_8 单变量对照跑用，criteria §4）")
    args = parser.parse_args(argv)

    w, gap, h, er, ll = args.w_mm, args.gap_mm, args.h_mm, args.er, args.line_len_mm
    anchor = fd_anchor(w, gap, h, er)
    print(f"CPS: w={w}mm gap={gap}mm  定标闭式 Z0={anchor['z0_closed_ohm']:.2f}Ω "
          f"εeff={anchor['eps_eff_closed']:.4f}  FD 锚 εeff={anchor['eps_eff']:.4f} "
          f"(闭式 vs FD {anchor['closed_vs_fd_pct']:+.2f}%)")

    work = Path(args.work_root) / args.pt
    work.mkdir(parents=True, exist_ok=True)
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work), freq_range_ghz=(2.25, 2.75),
        mesh_resolution_mm=args.mesh_mm,
        extra_params={"solve_timeout_s": 36000}))
    assert solver.connect(), "openEMS 不可用"
    params = {"w_mm": w, "gap_mm": gap, "line_len_mm": ll}
    if args.sub_cells > 0:
        params["_sub_cells"] = args.sub_cells
    if args.nrts > 0:
        params["_nrts"] = args.nrts
    if args.boundary:
        params["_boundary"] = [v.strip() for v in args.boundary.split(",")]
    print(f"mesh knobs: sub_cells={args.sub_cells or 4} nrts={args.nrts or 100000} "
          f"boundary={args.boundary or 'template-default'} work={work}")
    assert solver.build_geometry({"template": "cps", "params": params})
    t0 = time.time()
    result = solver.solve()
    print(f"solve_s={time.time() - t0:.0f} success={result.success} "
          f"msg={result.message}", flush=True)
    assert result.success and result.s_params is not None

    f_hz = np.asarray(result.freq_ghz) * 1e9
    s11 = result.s_params[:, 0, 0]
    s21 = result.s_params[:, 0, 1]
    base_cell = (args.base_cell_mm * 1e-3 if args.base_cell_mm > 0
                 else (args.mesh_mm * 1e-3 if args.mesh_mm > 0 else None))
    line_len_m, len_source = ll * 1e-3, "nominal"
    plane, plane_status = _read_port_plane_dist(work, ll * 1e-3)
    if plane_status == "ok":                     # w2f 定标批 ②：实测差分线长
        line_len_m, len_source = plane, "port_beta_csv"
        print(f"line_len: 实测(plane_dist_m)={plane:.6f} m vs 标称 {ll * 1e-3:.6f} m"
              f"（Δ {(plane / (ll * 1e-3) - 1) * 100:+.2f}%）")
    elif plane_status == "invalid":              # C4 守卫：坏数据拒用回退标称
        len_source = "nominal_invalid_plane_dist"
        print(f"line_len: plane_dist_m 未过守卫（非有限/非正/对标称偏差>"
              f"{PLANE_DIST_MAX_REL_DEV:.0%}）→ 拒用，回退标称 L 口径")
    # 口径地板（信息项，门值不动）：±1 落格 → εeff ±2·格/L；无格长信息且
    # 标称口径时用预声明缺省档 5.7%（BASE=1.14mm/L=40mm，pt1 实测档）
    floor_pct = (200.0 * base_cell / line_len_m if base_cell
                 else (NOMINAL_LEN_FLOOR_PCT if len_source != "port_beta_csv"
                       else None))
    verdict = judge_cps(f_hz, s11, s21, line_len_m, anchor, base_cell_m=base_cell,
                        line_len_source=len_source,
                        line_len_floor_pct=floor_pct)
    out = work / "_verdict.json"
    out.write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(verdict["gates"], ensure_ascii=False, indent=1))
    print(json.dumps(verdict["numbers"], ensure_ascii=False))
    print(f"CPS_PROBE_{verdict['verdict']}（判据={json.dumps(GATES)}；证据 {out}）")
    return verdict


def _read_port_plane_dist(work: Path,
                          nominal_m: float) -> tuple[float | None, str]:
    """读 port_beta.csv 的 plane_dist_m（w2f 定标批 ② 新契约）+ 合法性守卫
    （C4 followUp，plane_dist_usable）。返回 (值, 状态)：
      ("missing"→缺文件/缺列, "invalid"→在但未过守卫, "ok"→可用)；前两态由
    main 回退标称线长并如实记 line_len_source。"""
    import csv as _csv

    path = work / "port_beta.csv"
    if not path.exists():
        return None, "missing"
    with open(path, encoding="utf-8") as fh:
        rows = list(_csv.reader(fh))
    if not rows or "plane_dist_m" not in rows[0] or len(rows) < 2:
        return None, "missing"
    col = rows[0].index("plane_dist_m")
    try:
        plane = float(rows[1][col])
    except ValueError:
        return None, "invalid"
    if not plane_dist_usable(plane, nominal_m):
        return None, "invalid"
    return plane, "ok"


if __name__ == "__main__":
    main()
