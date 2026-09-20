"""mline MSLPort |S11| 伪底探针：H1/H2 离线验证 + 真机最小集 + 聚合裁决。

背景（工厂数据归因 + #250 新证据）：
- wp39 mline 工厂地貌 |S11|@2.5GHz 反物理：CalcPort ref_impedance=50、均匀线两端入
  PML 无远端失配 ⇒ 物理 |S11| ≡ |Γ(Z_line, 50)|；实测 w=0.85（HJ 58.75Ω 应 −21.89dB）
  −32.41、w=1.113（HJ 50.01Ω 应 −79）−24.47、w=1.4（HJ 43.15Ω 应 −22.68）−18.84 ⇒
  "端口级伪底"主导地貌；网格 auto→0.25mm 只换 8dB。
- 新证据：openEMS 引擎自算线阻抗 ZL（MSLPort.ReadUIData 三探针 sqrt(Et·dEt/(Ht·dHt))，
  被 CalcPort(ref=50) 覆盖）对 HJ 系统性偏低（wstep 50Ω 线 47.64Ω −4.7%、35Ω 线 −3.7%）。
  **H1**：伪底 = |Γ(ZL_engine, 50)| 的真实失配反射（FDTD 阶梯化线阻抗偏差在 50Ω 参考下
  的物理反射，非端口算法残差）；**H2**（旧假设）：端口面 V/I 行波分解残差。
- 分离手段：把 50Ω 基 r11 按 loaded_ratios_to_line_basis 对角式换到引擎 ZL 基——匹配线在
  自身基下应 → 0，剩余量 = H2 残差的真实量级；两端口（激励端/非激励端）ZL 一致性是端口
  算法自洽性的独立检验。内核见 rfauto.service.wp39_benchmark（mline_port_match_health /
  judge_pseudofloor_hypothesis，纯函数零真机）。

子命令：
  check  --run-dir D [--run-dir D ...] --out h1_check.json [--f-ghz 2.5]
         逐档：ZL 来源自动选择——port_beta.csv 含 re_zl1_ohm 列（新模板 β 块落盘）直接读；
         否则**归档重放**：截取 simulation.py 到 FDTD.Run 之前（几何/网格/端口定义原文
         exec，零真机、不写归档目录），MSLPort.ReadUIData(fdtd/, f) 重读引擎 ZL/β。
         对照 sparams.csv 实测 |S11| → 逐档 health + 聚合 H1/H2 裁决。
  solve  --mesh 1.2 --w 0.85 --w 1.113 --w 1.4 --outdir runs/mline_pseudofloor/m1.2
         真机最小集：OpenEMSSolver mline 模板（新 β 块落盘 ZL），每点独立目录，默认关闭
         全局缓存（同脚本哈希会命中旧缓存秒回不落 CSV，#158）；stdout 由调用方落文件。

产物：runs/mline_pseudofloor/**（runs/ 不入库；关键数字随单测入库）。
纪律：#212 归档重放前先 grep 断言 Run 行唯一；#142 无临时脚本；#1b 先验模型——
ZL 由引擎原实现（ports.py）算出，本脚本不自研公式。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, "src")

from rfauto.core.synthesis import Stackup, forward_z0
from rfauto.service.dataset_service import write_workdir_params_json
from rfauto.service.wp39_benchmark import (
    eps_eff_from_beta,
    interp_complex_at,
    judge_pseudofloor_hypothesis,
    median_in_window,
    mline_port_match_health,
)

STACKUP_NAME = "rogers4350b_h0.508"
F0_GHZ_DEFAULT = 2.5
FACTORY_BAND_GHZ = (2.4, 2.6)      # 与 scripts/wp39_followup_run.FACTORY_BAND_GHZ 同口径
LINE_LEN_MM_DEFAULT = 40.0
_RUN_LINE_RE = re.compile(r"^\s*FDTD\.Run\(.*\)\s*$", re.MULTILINE)


def _log_progress(root: Path, msg: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(root / "progress.log", "a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {msg}\n")


def read_sparams_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """sparams.csv → (f_hz, S11, S21)（模板 footer 契约：freq_hz,re_S11,im_S11,re_S21,im_S21）。"""
    data = np.loadtxt(path, delimiter=",", skiprows=1)
    return (data[:, 0], data[:, 1] + 1j * data[:, 2], data[:, 3] + 1j * data[:, 4])


def read_port_beta_csv(path: Path) -> dict[str, np.ndarray]:
    """port_beta.csv（header 驱动）：f_hz + beta{,1,2} + 可选 zl1/zl2 复数列。"""
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} 为空")
    out: dict[str, np.ndarray] = {
        "f_hz": np.array([float(r["freq_hz"]) for r in rows])}
    for key in ("beta_rad_per_m", "beta1_rad_per_m", "beta2_rad_per_m"):
        if key in rows[0]:
            out[key] = np.array([float(r[key]) for r in rows])
    for k in ("1", "2"):
        if f"re_zl{k}_ohm" in rows[0]:
            out[f"zl{k}"] = np.array(
                [float(r[f"re_zl{k}_ohm"]) + 1j * float(r[f"im_zl{k}_ohm"])
                 for r in rows])
    return out


def _ensure_openems_env() -> str:
    """把 openEMS bin 目录写进 RFAUTO_OPENEMS_BIN/PATH（归档脚本头部据此 add_dll_directory）。"""
    from rfauto.adapters.em_solver_base import resolve_openems_exe

    bin_dir = os.path.dirname(resolve_openems_exe())
    if not os.path.isdir(bin_dir):
        raise FileNotFoundError(f"openEMS bin 目录不存在: {bin_dir}")
    os.environ["RFAUTO_OPENEMS_BIN"] = bin_dir
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(bin_dir)
    return bin_dir


def replay_engine_zl(run_dir: Path, f_hz: np.ndarray) -> dict[str, Any]:
    """归档重放：exec simulation.py 的 Run 前段重建 CSX/MSLPort，ReadUIData 重读 ZL/β。

    只读：不调用 FDTD.Run/CalcPort、不写 CSV；UI 文件取归档 run_dir/fdtd/。
    返回 {"zl1","zl2","beta1","beta2"(复数/实数组), "w_mm","mesh_mm","line_len_mm"}。
    """
    script = run_dir / "simulation.py"
    text = script.read_text(encoding="utf-8")
    hits = _RUN_LINE_RE.findall(text)
    if len(hits) != 1:
        raise RuntimeError(f"{script}: FDTD.Run 行应唯一，实得 {len(hits)}（#212 审计）")
    head = text[: _RUN_LINE_RE.search(text).start()]  # type: ignore[union-attr]
    # 只匹配真实调用/写文件语句（注释里的 "CalcPort" 字样不算）
    if re.search(r"^\s*[^#\n]*\.CalcPort\(", head, re.MULTILINE) or \
            re.search(r"^\s*[^#\n]*open\(CSV_PATH", head, re.MULTILINE):
        raise RuntimeError(f"{script}: Run 前段含 CalcPort/CSV 写——拒绝重放")
    _ensure_openems_env()
    sim_path = run_dir / "fdtd"
    if not (sim_path / "port_ut_1A").exists():
        raise FileNotFoundError(f"{sim_path} 缺 port_ut_1A（UI 数据）")
    ns: dict[str, Any] = {"__name__": "_mline_pseudofloor_replay",
                          "__file__": str(script)}
    cwd = os.getcwd()
    try:
        os.chdir(run_dir)          # 脚本内 abspath("fdtd") 依赖 cwd（未使用，但保原语义）
        exec(compile(head, str(script), "exec"), ns)
    finally:
        os.chdir(cwd)
    p1, p2 = ns["_port1"], ns["_port2"]
    p1.ReadUIData(str(sim_path), f_hz)
    p2.ReadUIData(str(sim_path), f_hz)
    return {
        "zl1": np.asarray(p1.Z_ref, dtype=complex),
        "zl2": np.asarray(p2.Z_ref, dtype=complex),
        "beta1": np.real(np.asarray(p1.beta)),
        "beta2": np.real(np.asarray(p2.beta)),
        "w_mm": float(ns["W"]) * 1e3,
        "mesh_mm": float(ns["BASE"]) * 1e3,
        "line_len_mm": float(ns["L"]) * 1e3,
    }


def _mesh_from_dir(run_dir: Path) -> float | None:
    m = re.search(r"[\\/]m(\d+(?:\.\d+)?)[\\/]", str(run_dir) + os.sep)
    return float(m.group(1)) if m else None


def _w_from_dir(run_dir: Path) -> float | None:
    m = re.search(r"w(\d+(?:\.\d+)?)_L", run_dir.name)
    return float(m.group(1)) if m else None


def check_point(run_dir: Path, f0_ghz: float, stackup: Stackup) -> dict[str, Any]:
    """单档：ZL（新模板列或归档重放）× sparams.csv 实测 → health 行。"""
    f_hz, s11, s21 = read_sparams_csv(run_dir / "sparams.csv")
    f0_hz = f0_ghz * 1e9
    pb_path = run_dir / "port_beta.csv"
    pb = read_port_beta_csv(pb_path) if pb_path.exists() else {}
    if "zl1" in pb:
        zl_source = "port_beta_csv"
        zl1, zl2 = pb["zl1"], pb.get("zl2")
        beta1 = pb.get("beta1_rad_per_m", pb.get("beta_rad_per_m"))
        beta2 = pb.get("beta2_rad_per_m")
        f_zl = pb["f_hz"]
        w_mm = _w_from_dir(run_dir)
        mesh_mm = _mesh_from_dir(run_dir)
        line_len_mm = LINE_LEN_MM_DEFAULT
    else:
        zl_source = "readuidata_replay"
        rep = replay_engine_zl(run_dir, f_hz)
        zl1, zl2, beta1, beta2 = rep["zl1"], rep["zl2"], rep["beta1"], rep["beta2"]
        f_zl = f_hz
        w_mm, mesh_mm, line_len_mm = rep["w_mm"], rep["mesh_mm"], rep["line_len_mm"]
    if w_mm is None:
        raise ValueError(f"{run_dir}: 无法确定 w_mm")
    z0_hj, eps_hj = forward_z0(float(w_mm), f0_ghz, stackup)
    zl1_f0 = median_in_window(f_zl, zl1, f0_hz)
    r11_f0 = interp_complex_at(f_hz, s11, f0_hz)
    health = mline_port_match_health(
        w_mm=float(w_mm), z0_hj_ohm=z0_hj, zl_engine_ohm=zl1_f0, s11_raw_50=r11_f0)
    row: dict[str, Any] = {
        "run_dir": str(run_dir), "zl_source": zl_source,
        "mesh_mm": mesh_mm, "line_len_mm": line_len_mm, "f0_ghz": f0_ghz,
        "eps_hj": eps_hj,
        "zl1_band_re_min": float(np.min(zl1.real)), "zl1_band_re_max": float(np.max(zl1.real)),
        "zl1_band_im_absmax": float(np.max(np.abs(zl1.imag))),
        "s21_mag_f0": abs(interp_complex_at(f_hz, s21, f0_hz)),
    }
    if beta1 is not None:
        eps1, _ = eps_eff_from_beta(f_zl, beta1, f0_hz)
        row["eps_eff_beta1"] = eps1
        row["eps_eff_beta1_delta_hj_pct"] = (eps1 / eps_hj - 1.0) * 100.0
    if zl2 is not None:
        zl2_f0 = median_in_window(f_zl, zl2, f0_hz)
        row["zl2_engine_re_ohm"] = zl2_f0.real
        row["zl2_engine_im_ohm"] = zl2_f0.imag
        # H2 独立检验：激励端 vs 非激励端 ZL 一致性（同一均匀线两端应同值）
        row["zl_port_mismatch_pct"] = (zl2_f0.real / zl1_f0.real - 1.0) * 100.0
        if beta2 is not None:
            eps2, _ = eps_eff_from_beta(f_zl, beta2, f0_hz)
            row["eps_eff_beta2"] = eps2
    row.update(health)
    return row


def cmd_check(args: argparse.Namespace) -> int:
    stackup = Stackup.from_materials_yaml(STACKUP_NAME)
    out = Path(args.out)
    root = out.parent
    rows: list[dict[str, Any]] = []
    for d in args.run_dir:
        run_dir = Path(d)
        t0 = time.time()
        row = check_point(run_dir, args.f_ghz, stackup)
        rows.append(row)
        print(f"[check] w={row['w_mm']:.4f} mesh={row['mesh_mm']} src={row['zl_source']} "
              f"ZL1={row['zl_engine_re_ohm']:.2f}{row['zl_engine_im_ohm']:+.3f}j Ω "
              f"HJ={row['z0_hj_ohm']:.2f} dev={row['z0_dev_pct']:+.2f}% | "
              f"|S11|50 meas={row['s11_meas_50_db']:.2f} pred={row['s11_pred_50_db']:.2f} "
              f"resid={row['h1_residual_db']:+.2f} | line-basis={row['s11_line_basis_db']:.2f}dB "
              f"gain={row['basis_gain_db']:+.2f} h1={row['h1_dominant']} "
              f"({time.time() - t0:.1f}s)", flush=True)
        _log_progress(root, f"check {run_dir.name} mesh={row['mesh_mm']} "
                            f"ZL1={row['zl_engine_re_ohm']:.3f} dev={row['z0_dev_pct']:+.3f}% "
                            f"meas={row['s11_meas_50_db']:.2f} pred={row['s11_pred_50_db']:.2f} "
                            f"line={row['s11_line_basis_db']:.2f} h1={row['h1_dominant']}")
    verdict = judge_pseudofloor_hypothesis(rows)
    payload = {
        "task": "W3② mline MSLPort |S11| 伪底 H1/H2 检验",
        "stackup": STACKUP_NAME, "f0_ghz": args.f_ghz,
        "kernel": "rfauto.service.wp39_benchmark.mline_port_match_health/judge_pseudofloor_hypothesis",
        "rows": rows, "judgement": verdict,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[check] verdict={verdict['verdict']} n_h1={verdict['n_h1_dominant']}/{verdict['n_rows']} "
          f"z0_dev mean={verdict['z0_dev_pct_mean']:+.3f}% "
          f"[{verdict['z0_dev_pct_min']:+.3f},{verdict['z0_dev_pct_max']:+.3f}] → {out}")
    _log_progress(root, f"check done verdict={verdict['verdict']} → {out.name}")
    return 0


def dump_point_params(work: Path, w_mm: float, mesh_mm: float,
                      line_len_mm: float = LINE_LEN_MM_DEFAULT) -> Path:
    """点目录 params.json 落盘（import_workdir_runs 键路径契约 params）。

    字段=该点实跑几何（w/线长）+ 实跑网格档（#320：语义=实跑值）；单曲线
    点目录（w{w}_L{L}/sparams.csv）读取端按单曲线目录认无引用 JSON。
    """
    return write_workdir_params_json(work, {
        "w_mm": float(w_mm), "line_len_mm": float(line_len_mm),
        "mesh_mm": float(mesh_mm)})


def cmd_solve(args: argparse.Namespace) -> int:
    """真机最小集：mline 模板（新 β 块落盘 ZL），每宽度独立目录，缓存默认关闭。"""
    from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
    from rfauto.adapters.openems_solver import OpenEMSSolver

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    root = outdir.parent if outdir.name.startswith("m") else outdir
    results = []
    for w in args.w:
        tag = f"w{float(w):.4f}_L{LINE_LEN_MM_DEFAULT:.1f}"
        work = outdir / tag
        extra: dict[str, Any] = {"solve_timeout_s": int(args.timeout_s)}
        if not args.use_cache:
            extra["cache"] = False
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type="openems", exe_path=resolve_openems_exe(),
            working_dir=str(work), freq_range_ghz=FACTORY_BAND_GHZ,
            mesh_resolution_mm=float(args.mesh), extra_params=extra))
        if not solver.connect():
            raise RuntimeError("openEMS 不可用（resolve_openems_exe）")
        if not solver.build_geometry({"template": "mline",
                                      "params": {"w_mm": float(w),
                                                 "line_len_mm": LINE_LEN_MM_DEFAULT}}):
            raise RuntimeError("openEMS 构建几何失败")
        _log_progress(root, f"solve start mesh={args.mesh} {tag}")
        t0 = time.time()
        result = solver.solve()
        wall = time.time() - t0
        cached = "缓存复用" in (result.message or "")
        print(f"[solve] mesh={args.mesh} {tag} success={result.success} wall={wall:.1f}s "
              f"cached={cached} msg={(result.message or '')[:160]}", flush=True)
        _log_progress(root, f"solve done mesh={args.mesh} {tag} success={result.success} "
                            f"wall={wall:.1f}s cached={cached}")
        if not result.success:
            raise RuntimeError(f"openEMS 求解失败: {result.message}")
        has_zl = False
        pb = work / "port_beta.csv"
        if pb.exists():
            has_zl = "zl1" in read_port_beta_csv(pb)
        params_json = dump_point_params(work, float(w), float(args.mesh))
        results.append({"w_mm": float(w), "mesh_mm": float(args.mesh), "work": str(work),
                        "wall_s": round(wall, 2), "cached": cached, "port_beta_has_zl": has_zl,
                        "params_json": str(params_json)})
    (outdir / "_solve_summary.json").write_text(
        json.dumps({"mesh_mm": float(args.mesh), "points": results,
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("check", help="逐档 ZL/|Γ| 对照 + H1/H2 聚合裁决")
    pc.add_argument("--run-dir", action="append", required=True)
    pc.add_argument("--out", required=True)
    pc.add_argument("--f-ghz", type=float, default=F0_GHZ_DEFAULT)
    pc.set_defaults(func=cmd_check)
    ps = sub.add_parser("solve", help="真机最小集（openEMS mline，新 β 块落盘 ZL）")
    ps.add_argument("--mesh", type=float, required=True, help="网格 base（mm）")
    ps.add_argument("--w", action="append", type=float, required=True)
    ps.add_argument("--outdir", required=True)
    ps.add_argument("--timeout-s", type=int, default=7200)
    ps.add_argument("--use-cache", action="store_true")
    ps.set_defaults(func=cmd_solve)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
