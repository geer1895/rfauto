"""悬置带线锚冒烟（C9 传输线族 II）+ 预声明判读门（后续定标批更新缺省几何）。

真机：50Ω 设计线 w=0.9058mm b=1.016 H_SUB=0.508 对称居中 L=40mm（SSL 闭式
FD 重定标后的 50Ω 设计点；pt1/pt2 历史配对 #158 为旧 q 式口径 w=0.731，
复放用 --w-mm 0.731 --pt <历史pt>）。判读口径审定案（refs §11.2）：
  · **端口 β 口径合法**：StripLinePort β=√(−dU·dI/(U·I))（三点电报员差分）与
    S21 相位斜率（测量面间距）及 S21 绝对相位 mod 2π 三重自洽（pt1 实测
    74.42/74.46 rad/m，0.05%）——pt1 postmortem 的"三点差分在非对称介质下有偏"
    假设被否证；引擎 εeff≈2.02 是该网格下的真实传播常数。
  · **"S11 隐含 εeff≈2.64"推理撤**：其假设引擎 L'=Cohn 精确值，实测引擎
    L'=Z·β/ω 比 Cohn 低 12%（粗网格有效带宽化）；引擎自洽口径 √εeff=
    Z0_air,eng/Z=71.5/50.2=1.42 → εeff≈2.03 ≈ β 口径。
  · 真值锚=core/quasistatic_fd.py 裁判（过 HJ 微带 ±0.3%/Cohn/半空间极限基准，
    标称 εeff_FD≈2.092、Z0≈56.1Ω @w=0.731）；旧 refs 3.02 与 2.36 两份
    临时 FD 撤。
  · **SSL 闭式已重定标**（后续定标批，softmin 修正族）：旧 q 式 2.641
    中段 +26% 高估撤；重定标闭式在旧标称 −0.58%、验证族 ≤1.94%（信息项，
    不设门）。

预声明门（复跑判据，写死在此处不因结果改门，#122）：
  G0 β 口径自洽：|εeff(β)/εeff(S21 斜率)−1| ≤ 2.5%（超限=端口 β 不可判读）；
  G1 带内 |S11|max < −10 dB；
  G2 |εeff(β)/εeff_FD − 1| ≤ 3% PASS / ≤5% PARTIAL / 其余 FAIL；
  G3 |ZL/Z_FD − 1| ≤ 5%（ZL 优先 port_beta.csv 的 re_zl1_ohm，缺列时由 S11@f0
     反演 ZL=50(1+S11)/(1−S11)——H1 定案：|S11| ≡ |Γ(ZL,50)|，测量面见纯线模）。
粗网格 pt1 基线（旧标称 w=0.731）：G2 −3.6%（PARTIAL 档）、G3 −10.6%——复跑按
按预声明做 z 网格（基板 ≥8 格）与 NEAR（≤w/6）加密，预期两者同向收敛到 FD。
工作目录参数化（#198 教训）。证据链 runs/suspended_stripline_smoke/<pt>/。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.core.calculators import _stripline_z0, _suspended_stripline_ri

BAND_HZ = (2.4e9, 2.6e9)
BOARD_M = 60e-3          # 模板共享字面量（端口面=域 y 边界）
C0 = 299792458.0
#: 预声明门（#122：不因结果改门）
GATES = {
    "beta_consistency_pct": 2.5,     # G0：β vs S21 斜率（含网格吸附余量）
    "s11_max_db": -10.0,             # G1
    "eps_pass_pct": 3.0,             # G2 PASS
    "eps_partial_pct": 5.0,          # G2 PARTIAL 上限
    "zl_pass_pct": 5.0,              # G3
}


def eps_from_beta(beta_rad_m: float, f_hz: float) -> float:
    return (beta_rad_m * C0 / (2 * np.pi * f_hz)) ** 2


def eps_from_s21_slope(f_hz: np.ndarray, s21: np.ndarray, length_m: float) -> float:
    sel = (f_hz >= BAND_HZ[0]) & (f_hz <= BAND_HZ[1])
    phase = np.unwrap(np.angle(s21[sel]))
    slope = np.polyfit(f_hz[sel], phase, 1)[0]
    return float((-slope * C0 / (2 * np.pi * length_m)) ** 2)


def zl_from_s11(s11: complex | np.ndarray, z_ref: float = 50.0) -> float:
    """匹配长线 S11 ≡ Γ(ZL, z_ref)（H1 定案）：ZL = z_ref·(1+S11)/(1−S11)；给数组
    时取实部中位数（|Γ|≈2e-3 时相位噪声对应 ±0.2Ω 抖动）。"""
    zl = z_ref * (1.0 + np.asarray(s11)) / (1.0 - np.asarray(s11))
    return float(np.median(np.real(zl)))


def nominal_plane_dist_m(board_m: float = BOARD_M, line_len_m: float = 40e-3) -> float:
    """模板两端口测量面名义间距（4·BOARD/3 + L/3；精确值见 port_beta.csv
    plane_dist_m 列，新契约模板落盘）。"""
    return 4.0 * board_m / 3.0 + line_len_m / 3.0


def fd_anchor(w_mm: float, b_mm: float, h_mm: float, eps_r: float) -> dict:
    """真值锚：core/quasistatic_fd.py 裁判现算（几何参数化，零硬编码）。"""
    from rfauto.core.quasistatic_fd import suspended_stripline_quasistatic

    fd = suspended_stripline_quasistatic(w_mm, b_mm, h_mm, eps_r)
    cohn = _stripline_z0(w_mm, b_mm, 1.0)
    return {"eps_eff": fd.eps_eff, "z0_ohm": fd.z0_ohm, "z0_air_ohm": fd.z0_air_ohm,
            "z0_air_cohn_ohm": cohn,
            "z0_air_vs_cohn_pct": (fd.z0_air_ohm / cohn - 1) * 100,
            "eps_eff_coarse": fd.eps_eff_coarse, "eps_eff_fine": fd.eps_eff_fine}


def judge_suspended_stripline(f_hz: np.ndarray, s11: np.ndarray, s21: np.ndarray,
                              beta: np.ndarray, plane_dist_m: float,
                              anchor: dict, zl_ohm: float | None = None,
                              z_ref: float = 50.0) -> dict:
    """纯函数判读（预声明门 GATES；锚=FD 裁判现算结果 anchor）。"""
    sel = (f_hz >= BAND_HZ[0]) & (f_hz <= BAND_HZ[1])
    beta_med = float(np.median(beta[sel]))
    f_med = float(np.median(f_hz[sel]))
    eps_beta = eps_from_beta(beta_med, f_med)
    eps_s21 = eps_from_s21_slope(f_hz, s21, plane_dist_m)
    s11_max_db = float(20 * np.log10(np.abs(s11[sel]).max() + 1e-12))
    zl = (float(np.median(np.asarray(zl_ohm)[sel])) if zl_ohm is not None
          else zl_from_s11(s11[sel], z_ref))
    eps_fd = anchor["eps_eff"]
    z_fd = anchor["z0_ohm"]

    g0 = abs(eps_beta / eps_s21 - 1.0) * 100
    g2 = abs(eps_beta / eps_fd - 1.0) * 100
    g3 = abs(zl / z_fd - 1.0) * 100
    checks = {
        "G0_beta_consistency": {"gates": f"≤{GATES['beta_consistency_pct']}%",
                                "value_pct": round(g0, 3),
                                "pass": g0 <= GATES["beta_consistency_pct"]},
        "G1_s11_max_db": {"gates": f"<{GATES['s11_max_db']}dB",
                          "value_db": round(s11_max_db, 2),
                          "pass": s11_max_db < GATES["s11_max_db"]},
        "G2_eps_vs_fd": {"gates": (f"≤{GATES['eps_pass_pct']}% PASS/"
                                   f"≤{GATES['eps_partial_pct']}% PARTIAL"),
                         "value_pct": round(g2, 2),
                         "pass": g2 <= GATES["eps_pass_pct"],
                         "partial": g2 <= GATES["eps_partial_pct"]},
        "G3_zl_vs_fd": {"gates": f"≤{GATES['zl_pass_pct']}%",
                        "value_pct": round(g3, 2), "pass": g3 <= GATES["zl_pass_pct"]},
    }
    numbers = {"eps_beta": round(eps_beta, 4), "eps_s21_slope": round(eps_s21, 4),
               "eps_fd": round(eps_fd, 4), "beta_med_rad_m": round(beta_med, 3),
               "zl_ohm": round(zl, 2), "z_fd_ohm": round(z_fd, 2),
               "s11_max_db": round(s11_max_db, 2),
               "plane_dist_m": round(plane_dist_m, 5),
               "zl_source": "port_beta_csv" if zl_ohm is not None else "s11_inversion"}
    if not checks["G0_beta_consistency"]["pass"]:
        verdict = "UNDECIDABLE"      # 端口 β 不可判读 → 门失语（#122 如实）
    elif all(checks[k]["pass"] for k in ("G1_s11_max_db", "G2_eps_vs_fd",
                                         "G3_zl_vs_fd")):
        verdict = "PASS"
    elif (checks["G1_s11_max_db"]["pass"]
          and checks["G2_eps_vs_fd"].get("partial", False)):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    notes = [
        "β 口径已审定（refs §11.2）：三点差分 β 与 S21 斜率/绝对相位三重自洽，"
        "探针有偏假设否证；S11 隐含 εeff 旧推理（假设引擎 L'=Cohn）撤。",
        "SSL 闭式已 FD 重定标（softmin 修正族，后续定标批）：验证族 "
        "max|err| 1.94%（信息项，不设门）；旧 q 式 +26% 高估撤。",
    ]
    return {"verdict": verdict, "gates": checks, "numbers": numbers,
            "anchor": {k: round(v, 5) if isinstance(v, float) else v
                       for k, v in anchor.items()}, "notes": notes}


def main(argv: list[str] | None = None) -> dict:
    from rfauto.adapters.openems_solver import OpenEMSSolver

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pt", default="pt2")
    parser.add_argument("--mesh-mm", type=float, default=0.0,
                        help="网格 base 覆盖（0=官方 λ_sub/50 自动）")
    parser.add_argument("--w-mm", type=float, default=0.9058,
                        help="带宽（缺省=重定标后 50Ω 设计点 0.9058；"
                             "pt1/pt2 历史配对 #158 口径用 0.731）")
    parser.add_argument("--b-mm", type=float, default=1.016)
    parser.add_argument("--h-mm", type=float, default=0.508)
    parser.add_argument("--er", type=float, default=3.66)
    parser.add_argument("--line-len-mm", type=float, default=40.0)
    parser.add_argument("--work-root", default="runs/suspended_stripline_smoke",
                        help="证据链根目录（#198 工作目录参数化；pt 子目录）")
    parser.add_argument("--near-ratio", type=float, default=0.0,
                        help="NEAR=base/near_ratio 旋钮（0=官方 base/4；"
                             "合规复跑 10 → 0.114mm ≤ w/6）")
    parser.add_argument("--sub-cells", type=int, default=0,
                        help="基板 z 格数旋钮（0=缺省 4；合规复跑 8）")
    parser.add_argument("--nrts", type=int, default=0,
                        help="FDTD NrTS 上限（0=缺省 100000；细网格 150000）")
    args = parser.parse_args(argv)

    w, b, h, er, ll = (args.w_mm, args.b_mm, args.h_mm, args.er,
                       args.line_len_mm)
    eps_ref, z0_ref = _suspended_stripline_ri(w, b, h, er)
    anchor = fd_anchor(w, b, h, er)
    print(f"悬置带线: w={w}mm b={b} h={h} 重定标闭式 Z0={z0_ref:.2f}Ω "
          f"εeff={eps_ref:.4f}（softmin 修正族；旧 q 式 +26% 已撤）")
    print(f"FD 锚（quasistatic_fd 裁判）: εeff={anchor['eps_eff']:.4f} "
          f"Z0={anchor['z0_ohm']:.2f}Ω  Z0_air={anchor['z0_air_ohm']:.2f} "
          f"vs Cohn {anchor['z0_air_cohn_ohm']:.2f} "
          f"({anchor['z0_air_vs_cohn_pct']:+.2f}%)")

    work = Path(args.work_root) / args.pt
    work.mkdir(parents=True, exist_ok=True)
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work), freq_range_ghz=(2.25, 2.75),
        mesh_resolution_mm=args.mesh_mm,
        extra_params={"solve_timeout_s": 36000}))
    assert solver.connect(), "openEMS 不可用"
    params = {"w_mm": w, "b_mm": b, "line_len_mm": ll}
    if args.near_ratio > 0:
        params["_near_ratio"] = args.near_ratio
    if args.sub_cells > 0:
        params["_sub_cells"] = args.sub_cells
    if args.nrts > 0:
        params["_nrts"] = args.nrts
    print(f"mesh knobs: near_ratio={args.near_ratio or 4} "
          f"sub_cells={args.sub_cells or 4} nrts={args.nrts or 100000} "
          f"work={work}")
    assert solver.build_geometry({"template": "suspended_stripline",
                                  "params": params})
    t0 = time.time()
    result = solver.solve()
    print(f"solve_s={time.time() - t0:.0f} success={result.success} "
          f"msg={result.message}", flush=True)
    assert result.success and result.s_params is not None

    f_hz = np.asarray(result.freq_ghz) * 1e9
    s11 = result.s_params[:, 0, 0]
    s21 = result.s_params[:, 0, 1]
    beta, zl, plane_dist = _read_port_beta(work)
    verdict = judge_suspended_stripline(f_hz, s11, s21, beta, plane_dist, anchor,
                                        zl_ohm=zl)
    out = work / "_verdict.json"
    out.write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(verdict["gates"], ensure_ascii=False, indent=1))
    print(json.dumps(verdict["numbers"], ensure_ascii=False))
    print(f"SUSPENDED_STRIPLINE_PROBE_{verdict['verdict']}（判据={json.dumps(GATES)}；"
          f"证据 {out}）")
    return verdict


def _read_port_beta(work: Path) -> tuple[np.ndarray, np.ndarray | None, float]:
    """读 port_beta.csv：兼容旧两列契约与新八列（β2/ZL/plane_dist_m）。"""
    with open(work / "port_beta.csv", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    cols = {name: i for i, name in enumerate(header)}
    arr = np.array([[float(v) for v in r] for r in rows[1:]])
    beta = arr[:, cols["beta_rad_per_m"]]
    zl = (arr[:, cols["re_zl1_ohm"]] if "re_zl1_ohm" in cols else None)
    plane = float(arr[0, cols["plane_dist_m"]]) if "plane_dist_m" in cols \
        else nominal_plane_dist_m()
    return beta, zl, plane


if __name__ == "__main__":
    main()
