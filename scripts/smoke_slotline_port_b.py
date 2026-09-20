"""W3⑧b 路线 B 真机冒烟：openEMS LumpedPort 跨槽近似 → 均匀槽线段 β/S 参数。

流程：
  1) 真机门：确认无在跑 openEMS.exe（路线 A 子代理可能在跑；有则每 60s 轮询
     等待，上限 --busy-timeout-s）；
  2) 按 R 档渲染 slotline_lumped_template 脚本 → 分离子进程跑 FDTD（#157：
     分离+日志轮询；#242：stdout 落文件）；已有 slotline_summary.json 直接复用
     （#158 缓存口径；--no-cache 强制重跑）；
  3) R 两档：r_closed = core/slotline 闭式 Z0（110.92Ω）；r_hfss_zpv = HFSS 仲裁
     Zpv（读 runs/slotline_arbitration/hfss_arbitration.json 的 verdict/variants，
     缺则该档标 pending 跳过）；
  4) 后处理：β_B(探针相位斜率)@f0 vs 闭式 / vs HFSS（缺则 pending）；带载比值
     → `assemble_route_b_sparams`（#250）→ 50Ω 基 |S11|/|S21|；线基 |S11_raw|
     = LumpedPort 集总近似失配水平（如实）；swr_amp 诊断；
  5) 结果 JSON 落 runs/slotline_port_b/result.json（每档一节 + 门）。

设计点（与路线 A/HFSS 同）：f0=2.5GHz、εr=3.66、h=1.524mm、W=1.0mm、
L=1λ'=93.4624mm；扫描 2.25–2.75GHz（路线 A 同带）。
门（预声明）：β_B vs HFSS ≤3%；β_B vs 闭式 ≤5% 信息门；LumpedPort
适用性分级：β 可用 / S 参数可用与否按 |S11| 线基水平如实。
用法：.venv/Scripts/python.exe scripts/smoke_slotline_port_b.py [--r-modes closed,hfss]
      [--mesh-mm 0] [--nrts N] [--poll-timeout-s 14400] [--busy-timeout-s 7200] [--no-cache]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import resolve_openems_exe
from rfauto.adapters.slotline_lumped_template import (
    assemble_route_b_sparams,
    fit_z0_from_tap_s11,
    render_slotline_lumped_script,
    tap_network_sparams,
)
from rfauto.core.slotline import slotline_closed_form

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "slotline_port_b"
HFSS_JSON = ROOT / "runs" / "slotline_arbitration" / "hfss_arbitration.json"
PROGRESS = ROOT / "runs" / "slotline_arbitration" / "progress.log"

F0_GHZ = 2.5
BAND = (2.25, 2.75)
ER, H_MM, W_MM = 3.66, 1.524, 1.0
TAND = 0.0037
SECTION = dict(y_half_mm=60.0, z_bot_mm=30.0, z_top_mm=30.0)


def _progress(msg: str) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def wait_engine_free(busy_timeout_s: float) -> None:
    """路线 A 子代理优先：有 openEMS.exe 在跑则 60s 轮询等待。"""
    t0 = time.time()
    while True:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq openEMS.exe"],
                           capture_output=True, text=True)
        if "openEMS.exe" not in (r.stdout or ""):
            return
        if time.time() - t0 > busy_timeout_s:
            raise SystemExit(f"openEMS.exe 占用超 {busy_timeout_s:.0f}s，退出（他轨优先）")
        print(f"[wait] openEMS.exe 在跑，60s 后重查（已等 {time.time() - t0:.0f}s）", flush=True)
        time.sleep(60)


def load_hfss_zpv(path: Path = HFSS_JSON) -> dict | None:
    """读 HFSS 仲裁产物的主档 Zpv/β（stage=done 才采信；否则 None=pending）。"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("stage") != "done":
        return None
    prim_tag = (data.get("verdict") or {}).get("primary_variant", "wide")
    main = (data.get("variants") or {}).get(prim_tag)
    if not main or main.get("mode_evanescent_at_f0") or "zpv_ohm" not in main:
        return None
    return {"zpv_ohm": float(main["zpv_ohm"]), "zpi_ohm": float(main["zpi_ohm"]),
            "zvi_ohm": float(main["zvi_ohm"]),
            "beta_gamma_rad_m_f0": float(main["beta_gamma_rad_m_f0"]),
            "beta_s21_rad_m_f0": float(main["beta_s21_rad_m_f0"]),
            "variant": prim_tag, "source": str(path)}


def run_variant(tag: str, r_port: float, args: argparse.Namespace,
                beta_ref: float) -> dict:
    """渲染 + 分离跑 FDTD（或复用缓存）→ 返回 summary + csv 解析。"""
    work = OUT / tag
    work.mkdir(parents=True, exist_ok=True)
    summary_path = work / "slotline_summary.json"
    script_path = work / "simulation.py"
    script = render_slotline_lumped_script(
        {"w_mm": W_MM, "h_mm": H_MM, "er": ER, "line_len_mm": args.line_len_mm,
         **SECTION}, BAND, r_port_ohm=r_port,
        mesh_resolution_mm=args.mesh_mm, nrts=args.nrts, tan_d=TAND,
        beta_ref_rad_m=beta_ref)
    reuse = (summary_path.exists() and not args.no_cache and script_path.exists()
             and script_path.read_text(encoding="utf-8") == script)
    exe = resolve_openems_exe()
    exe_dir = str(Path(exe).resolve().parent)
    runner = work / "_rfauto_runner.py"
    runner_src = (
        "import os\nimport runpy\nimport sys\n"
        f"os.add_dll_directory({exe_dir!r})\n"
        f"os.environ['PATH'] = {exe_dir!r} + os.pathsep + os.environ.get('PATH', '')\n"
        "runpy.run_path(sys.argv[1], run_name='__main__')\n")
    if not reuse and args.postprocess_only and (work / "fdtd").exists():
        # 几何段未变、仅后处理改动：复用 fdtd/ 时域产物同步重跑后处理（秒级）
        script_path.write_text(script, encoding="utf-8")
        runner.write_text(runner_src, encoding="utf-8")
        env = {**os.environ, "RFAUTO_SKIP_RUN": "1"}
        t0 = time.time()
        proc = subprocess.run([sys.executable, str(runner), str(script_path)], cwd=str(work),
                              capture_output=True, text=True, timeout=900, env=env)
        if proc.returncode != 0 or not summary_path.exists():
            raise SystemExit(f"[postprocess:{tag}] rc={proc.returncode}\n{proc.stderr[-1500:]}")
        print(f"[postprocess:{tag}] 复用 fdtd/ 重跑后处理 {time.time() - t0:.0f}s", flush=True)
        reuse = True
        solve_s = None
    if not reuse:
        if summary_path.exists():
            summary_path.unlink()
        script_path.write_text(script, encoding="utf-8")
        assert Path(exe).exists(), f"openEMS.exe 不存在: {exe}"
        runner.write_text(runner_src, encoding="utf-8")
        log_path = work / "fdtd_run.log"
        detached = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        t_launch = time.time()
        with open(log_path, "ab") as logf:
            proc = subprocess.Popen(
                [sys.executable, str(runner), str(script_path)],
                cwd=str(work), stdout=logf, stderr=subprocess.STDOUT,
                creationflags=detached)
        (work / "_fdtd.pid").write_text(str(proc.pid), encoding="utf-8")
        print(f"[fdtd:{tag}] 已分离启动 pid={proc.pid} R={r_port:.2f}Ω（日志 {log_path}）", flush=True)
        _progress(f"stage3 route_b/{tag}: FDTD 分离启动 pid={proc.pid} R={r_port:.2f}")
        t0 = time.time()
        while not summary_path.exists():
            if proc.poll() is not None and not summary_path.exists():
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-1200:]
                raise SystemExit(f"[fdtd:{tag}] 子进程退出 rc={proc.returncode} 无 summary；日志尾:\n{tail}")
            if time.time() - t0 > args.poll_timeout_s:
                raise SystemExit(f"[fdtd:{tag}] 轮询超 {args.poll_timeout_s:.0f}s（pid {proc.pid}）")
            time.sleep(60)
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-160:] if log_path.exists() else ""
            print(f"[poll:{tag}] {time.time() - t0:.0f}s ... {tail!r}", flush=True)
        solve_s = round(time.time() - t_launch, 1)
    else:
        solve_s = None
        print(f"[fdtd:{tag}] 复用已有 summary（脚本逐字节一致）", flush=True)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    sp = np.loadtxt(str(work / "sparams.csv"), delimiter=",", skiprows=1, ndmin=2)
    bt = read_beta_csv(work / "slotline_beta.csv")
    return {"summary": summary, "sparams": sp, "beta": bt, "solve_s": solve_s,
            "work": str(work)}


def read_beta_csv(path: Path) -> dict[str, np.ndarray]:
    """slotline_beta.csv → 列名字典（按表头取列，不按位置；beta_ref 列可空）。"""
    with open(path, encoding="utf-8") as fh:
        header = fh.readline().strip().split(",")
    raw = np.genfromtxt(str(path), delimiter=",", skip_header=1, filling_values=np.nan,
                        ndmin=2)
    return {name: raw[:, k] for k, name in enumerate(header)}


def analyze_variant(tag: str, r_port: float, raw: dict, cf_beta: float,
                    hfss: dict | None, line_len_m: float = 93.4624e-3) -> dict:
    """纯函数：summary/csv → β 对拍 + 50Ω 基 S（离线测试可对合成数据调用）。"""
    sp, bt, summary = raw["sparams"], raw["beta"], raw["summary"]
    f = sp[:, 0]
    s11_raw = sp[:, 1] + 1j * sp[:, 2]
    s21_raw = sp[:, 3] + 1j * sp[:, 4]
    i0 = int(np.argmin(np.abs(f - F0_GHZ * 1e9)))
    s50 = assemble_route_b_sparams(s11_raw, s21_raw, r_port, 50.0)
    beta_f = np.asarray(bt["beta_probe_rad_m"], dtype=float)      # 主口径：双行波拟合
    beta_slope = np.asarray(bt.get("beta_slope_rad_m", beta_f), dtype=float)
    gamma_load = np.asarray(bt.get("gamma_load_mag", np.full_like(beta_f, np.nan)), dtype=float)
    swr = np.asarray(bt.get("swr_amp", np.full_like(beta_f, np.nan)), dtype=float)
    beta_f0 = float(beta_f[i0])

    def _db(x: complex) -> float:
        return float(20 * math.log10(abs(x) + 1e-300))

    out = {
        "tag": tag, "r_port_ohm": r_port, "solve_s": raw["solve_s"],
        "work": raw["work"],
        "beta_probe_rad_m_f0": beta_f0,
        "beta_slope_rad_m_f0": float(beta_slope[i0]),
        "beta_slope_vs_two_wave_pct": (float(beta_slope[i0]) / beta_f0 - 1) * 100,
        "gamma_load_mag_f0": float(gamma_load[i0]),
        "beta_vs_cf_pct": (beta_f0 / cf_beta - 1) * 100,
        "beta_vs_hfss_pct": ((beta_f0 / hfss["beta_gamma_rad_m_f0"] - 1) * 100
                             if hfss else None),
        "eps_eff_probe_f0": (beta_f0 / (2 * math.pi * F0_GHZ * 1e9 / 299792458.0)) ** 2,
        "s11_db_f0_line_basis": _db(s11_raw[i0]),
        "s21_db_f0_line_basis": _db(s21_raw[i0]),
        "s21_resid_db_f0": _db(complex(*summary["s21_resid_at_f0"])),
        "s21_convention": summary.get("s21_convention"),
        "s11_db_f0_50ohm": _db(s50[i0, 0, 0]),
        "s21_db_f0_50ohm": _db(s50[i0, 1, 0]),
        "band_max_s11_db_line_basis": float(np.max(20 * np.log10(np.abs(s11_raw) + 1e-300))),
        "band_min_s21_db_line_basis": float(np.min(20 * np.log10(np.abs(s21_raw) + 1e-300))),
        "passivity_max_line_basis": float(np.max(np.abs(s11_raw) ** 2 + np.abs(s21_raw) ** 2)),
        "swr_amp_f0": float(swr[i0]),
        "beta_band_rows": [
            {"f_ghz": float(f[k] / 1e9), "beta_probe": float(beta_f[k]),
             "beta_cf": slotline_closed_form(W_MM, H_MM, ER, float(f[k] / 1e9)).beta_rad_m}
            for k in range(0, len(f), max(1, len(f) // 8))],
        "mesh_lines": summary.get("mesh_lines"),
    }
    # 抽头网络解析模型（PML 匹配线 + 两处并联 LumpedPort）：① 若线 Z0=R，模型预期
    # 的原始 S（1λ' 处 S11=−1/2、S21=+1/2）——原始 |S11|/|S21| ≈ −6dB 是拓扑必然而非
    # "失配差"；② 由实测 S11_raw 逐频反演 Z0_tap（无寄生电抗/辐射项，resid 记质量）
    gam = 1j * beta_f
    s11_m, s21_m = tap_network_sparams(r_port, r_port, gam, line_len_m)
    z0_tap, z0_res = fit_z0_from_tap_s11(s11_raw, r_port, gam, line_len_m)
    out["tap_model"] = {
        "expected_if_z0_eq_r": {"s11_db_f0": _db(s11_m[i0]), "s21_db_f0": _db(s21_m[i0])},
        "z0_tap_fit_f0_ohm": float(z0_tap[i0]),
        "z0_tap_fit_resid_f0": float(z0_res[i0]),
        "z0_tap_fit_band_median_ohm": float(np.median(z0_tap)),
        "note": ("Z0_tap=抽头视在线阻抗（模型忽略端口盒寄生电抗与辐射负载，resid 为复 Γ "
                 "失配量）；仅作 HFSS Zpv/闭式 Z0 的第三方旁证，不作生产口径"),
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--r-modes", default="closed,hfss",
                    help="逗号分隔 R 档：closed（闭式 Z0）/hfss（HFSS Zpv，缺则 pending）")
    ap.add_argument("--mesh-mm", type=float, default=0.0, help="网格 base 覆盖（0=自动 λ_sub/50）")
    ap.add_argument("--nrts", type=int, default=100000)
    ap.add_argument("--line-len-mm", type=float, default=93.4624)
    ap.add_argument("--poll-timeout-s", type=float, default=4 * 3600)
    ap.add_argument("--busy-timeout-s", type=float, default=2 * 3600)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--postprocess-only", action="store_true",
                    help="脚本文本变了但几何段未变：复用 fdtd/ 时域产物只重跑后处理")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    cf = slotline_closed_form(W_MM, H_MM, ER, F0_GHZ)
    hfss = load_hfss_zpv()
    hfss_txt = (f"Zpv={hfss['zpv_ohm']:.2f} beta={hfss['beta_gamma_rad_m_f0']:.3f}"
                if hfss else "pending")
    print(f"[design] closed form: Z0={cf.z0_ohm:.2f}Ω eps_eff={cf.eps_eff:.4f} "
          f"beta={cf.beta_rad_m:.3f}rad/m L={args.line_len_mm}mm; HFSS={hfss_txt}",
          flush=True)

    modes = [m.strip() for m in args.r_modes.split(",") if m.strip()]
    variants: dict[str, dict] = {}
    pending: list[str] = []
    for mode in modes:
        if mode == "closed":
            tag, r_port = "r_closed", cf.z0_ohm
        elif mode == "hfss":
            if not hfss:
                pending.append("r_hfss_zpv（HFSS 仲裁尚无 stage=done 产物）")
                continue
            tag, r_port = "r_hfss_zpv", hfss["zpv_ohm"]
        else:
            raise SystemExit(f"未知 R 档 {mode!r}")
        wait_engine_free(args.busy_timeout_s)
        raw = run_variant(tag, r_port, args, cf.beta_rad_m)
        ana = analyze_variant(tag, r_port, raw, cf.beta_rad_m, hfss,
                              line_len_m=args.line_len_mm * 1e-3)
        variants[tag] = ana
        print(f"[{tag}] beta_B={ana['beta_probe_rad_m_f0']:.3f} ({ana['beta_vs_cf_pct']:+.2f}% vs cf"
              + (f", {ana['beta_vs_hfss_pct']:+.2f}% vs HFSS" if hfss else "")
              + f") slope_bias={ana['beta_slope_vs_two_wave_pct']:+.2f}% |Γload|={ana['gamma_load_mag_f0']:.3f} "
              f"|S11|line={ana['s11_db_f0_line_basis']:.1f}dB |S21|line={ana['s21_db_f0_line_basis']:.2f}dB "
              f"|S11|50={ana['s11_db_f0_50ohm']:.1f}dB conv={ana['s21_convention']} "
              f"swr={ana['swr_amp_f0']:.2f} Z0_tap={ana['tap_model']['z0_tap_fit_f0_ohm']:.1f}Ω "
              f"(resid {ana['tap_model']['z0_tap_fit_resid_f0']:.3f}) solve={ana['solve_s']}s", flush=True)
        _progress(f"stage3 route_b/{tag}: done beta_B={ana['beta_probe_rad_m_f0']:.3f} "
                  f"({ana['beta_vs_cf_pct']:+.2f}% vs cf) |S11|line={ana['s11_db_f0_line_basis']:.1f}dB")

    # 门与适用性分级（如实，不凑绿 #122）
    primary = variants.get("r_hfss_zpv") or variants.get("r_closed")
    gates = {}
    grading = {}
    if primary:
        gates["beta_vs_hfss_le_3pct"] = (abs(primary["beta_vs_hfss_pct"]) <= 3.0
                                         if primary["beta_vs_hfss_pct"] is not None else None)
        gates["beta_vs_cf_le_5pct_info"] = abs(primary["beta_vs_cf_pct"]) <= 5.0
        gates["passivity_le_1p02"] = primary["passivity_max_line_basis"] <= 1.02
        s11 = primary["s11_db_f0_line_basis"]
        grading = {
            "beta_usable": bool(gates["beta_vs_cf_le_5pct_info"] and gates["passivity_le_1p02"]),
            "sparams_usable": bool(s11 <= -15.0),
            "sparams_grade": ("A(|S11|≤-20dB 近匹配)" if s11 <= -20 else
                              "B(-20<|S11|≤-15dB 可用)" if s11 <= -15 else
                              "C(-15<|S11|≤-10dB 仅定性)" if s11 <= -10 else
                              "D(|S11|>-10dB 集总近似失配主导，S 参数不可作生产口径)"),
            "note": ("LumpedPort 跨槽=集总近似：β 由探针相位斜率独立提取（不依赖端口），"
                     "S 参数受集总-模场失配影响，分级按线基 |S11|@f0"),
        }
    results = {
        "route": "B (openEMS LumpedPort across slot, R=line Z0 tiers)",
        "design": {"f0_ghz": F0_GHZ, "band_ghz": list(BAND), "w_mm": W_MM, "h_mm": H_MM,
                   "er": ER, "tan_d": TAND, "line_len_mm": args.line_len_mm,
                   "section": SECTION, "mesh_mm": args.mesh_mm, "nrts": args.nrts,
                   "closed_form": {"z0_ohm": cf.z0_ohm, "eps_eff": cf.eps_eff,
                                   "beta_rad_m": cf.beta_rad_m}},
        "hfss_reference": hfss or {"status": "pending"},
        "variants": variants,
        "pending": pending,
        "primary_variant": primary["tag"] if primary else None,
        "gates": gates,
        "lumped_port_grading": grading,
        "assumptions": [
            "两口全同+互易 → 单激励对称装配 S=[[S11,S21],[S21,S11]]（#250：R=线Z0 档端接=匹配，带载比值=线基波比值，再 renorm 到 50Ω）",
            "S21 取被动口 uf_ref/uf_inc 幅值大者（匹配端接下一者≡0），约定记于 s21_convention",
            "β_B 探针跨度 λ'/2 整周期，端口 2 残余失配相位涟漪整周期平均",
        ],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out_json = OUT / "result.json"
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[out] {out_json}", flush=True)
    print(f"[gates] {gates} pending={pending}", flush=True)
    ok = primary is not None and all(v for v in gates.values() if v is not None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
