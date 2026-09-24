"""直 SIW 线段 OE 锚冒烟驱动（siw-family 首族；2026-09-22 备妥，真机锚已落判）。

**已真跑落判**（G1 勘误 PASS/G2 PASS/G3 口径裁定/G4 PASS，
runs/siw_family/；本驱动复跑即重走同链）。预声明门与预算：
runs/siw_family/criteria.md §6（#122：判据先写
后跑，真跑后不因结果改门；#350：AGREE 需幅度差 ≤ 门限且方向一致）。

用法（真跑时）：
    .venv/Scripts/python.exe scripts/siw_anchor_smoke.py --pt pt1
    # 可选：--mesh-mm 0.4 --flo 6.0 --fhi 13.0 --nrts 100000 --timeout-s 6120

口径（criteria §6 预声明，写死不因结果改）：
  频带 (6, 13) GHz（F0=9.5GHz 宽脉冲；6.2GHz 在带内供 G2 波导性滚降门）；
  显式 mesh_resolution_mm=0.4 审计档；NrTS 上限 100000（EndCriteria 缺省
  能量判据自停）；port1 单激励、port2 R=闭式 Z_PV 端接。

预声明门：
  G1（主门，fc10 单参数拟合）  ：带 [9,11]GHz 内 S21 解缠相位对
      φ(f) = −β(f; fc)·L + φ0 做 fc 单参数拟合（φ0 线性消去，variable
      projection；β(f;fc)=(2π/c)·√(εr·f²−fc²)）。
      |fc_fit/fc_closed − 1| ≤ 3% PASS / ≤ 5% PARTIAL / 其余 FAIL；
      fc_fit − fc_closed 符号如实记录（#350 方向项）。
      ⚠ 口径=cps 同款（S21 解缠相位斜率，LumpedPort 无 β）；uf 相位含端口
      分解伪象的风险如实（#161）——G1 FAIL 时双行波拟合口径为 followUp，
      不事后改门。
  G2（波导性滚降）            ：|S21|@6.2GHz ≤ |S21|@10GHz − 15 dB
      （6.2GHz 低于闭式 fc10=6.667GHz，倏逝 α≈97.5 Np/m×63mm≈−53dB，
      15dB 门留足余量）。
  G3（物理量级地板+无源性）    ：max|S21|@[9,11]GHz ≥ −3 dB；
      max(|S11|²+|S21|²) ≤ 1.05（带内）。
  G4（口径自洽）              ：port_beta.csv 实测 plane_dist 与名义
      line_len 差 ≤ 1·BASE（端口元落格尺度，cps 契约）。

预算（#328/#329）：0.4mm 档 ≈0.91M cells（exec 实测 0.84M）；时窗
=NrTS×dt=100000×0.1936ps=19.36ns（终网格实算钉值，dt 为 as-run 引擎
日志实测，同下 v2 段与 criteria §6；单轴 CFL 估计 0.42ps→42ns 是禁用
口径——虚标余量 2.2×，round6 E-LOW 勘误）≥ 需求 ≈19ns（余量紧：
max|S11|>1 先查 NrTS 截断再疑物理，#262）；墙钟预估
≈50min ×2 余量 → timeout 缺省 6120s，solo 单飞（#246）。

互斥（#261）：起跑前命令行查 python 进程含 _rfauto_runner|simulation.py
（临时 .ps1 走 -NoProfile -ExecutionPolicy Bypass，#289）；命中即拒绝起跑
不代杀；探测失败 fail-closed。自身（驱动进程名 siw_anchor_smoke.py）不匹配
该模式——无 #261 自锁（互斥模式自排除纪律）。

端口方案 v2（2026-09-23，runs/siw_family/v2_criteria.md）：
  --port-mode v2 = 藩篱止于端口面+端面口径 LumpedPort（跨介质孔径 ±W/2，
  R=Z_PV 闭式不变）——消除 §R2 归因的端面 fixture 汇（延拓支路 4/9 分光+
  探针中间抽头耗散）后按**原 G3 门（≥−3dB）**重裁；缺省 v1（上列口径）
  渲染逐字节不变。四门与门值零改动（#122）；G1 拟合公式=§R1 勘误口径
  （beta_closed）。v2 预算：终网格最小格逐轴与 v1 实测相同（x 50µm/y 40µm/
  z 127µm，离线 exec）→ 引擎 dt=0.1936ps 同 v1、NrTS=1e5 时窗 19.36ns≥需求
  ~19ns；cells<0.84M、墙钟 ≤v1 实测 210.5s×2（timeout 缺省 6120s 不动），
  solo 单飞。wave2 执行（C14a 轨让位后）：
      .venv/Scripts/python.exe scripts/siw_anchor_smoke.py --port-mode v2 --pt pt2_v2
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.adapters.openems_templates import (  # noqa: E402
    TEMPLATE_NOMINAL,
    render_script,
)

C0 = 299792458.0
ER = 3.66
FC10_CLOSED_GHZ = 10.0 / 1.5          # 闭式 fc10=6.6667GHz（criteria §2）
LINE_LEN_MM = 63.0724                  # 名义两端口面间距（闭式链 4 位舍入）
G1_BAND_GHZ = (9.0, 11.0)
G2_F_GHZ = 6.2
G2_REF_GHZ = 10.0
G3_BAND_GHZ = (9.0, 11.0)
#: 预声明门限（#122 不因结果改门）
G1_PASS_PCT = 3.0
G1_PARTIAL_PCT = 5.0
G2_ROLLOFF_DB = 15.0
G3_S21_MIN_DB = -3.0
G3_PASSIVITY_MAX = 1.05


def oe_foreign_running() -> list[str]:
    """#261 互斥查（factory_g2_collect 同式；fail-closed）。"""
    root = REPO / "runs" / "siw_family"
    root.mkdir(parents=True, exist_ok=True)
    ps1 = root / "_oe_proc_check.ps1"
    ps1.write_text(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match '_rfauto_runner|simulation\\.py' "
        "} | ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }\n",
        encoding="ascii")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1)],
            capture_output=True, text=True, timeout=120)
    finally:
        ps1.unlink(missing_ok=True)
    if out.returncode != 0:
        raise RuntimeError(
            f"#261 进程查询失败 rc={out.returncode}: {out.stderr[:300]}")
    own = str(os.getpid())
    return [ln.strip() for ln in (out.stdout or "").splitlines()
            if ln.strip() and not ln.strip().startswith(own + "\t")]


def beta_closed(f_hz: np.ndarray, fc10_ghz: float, er: float = ER) -> np.ndarray:
    """等效 RWG TE10 闭式 β(f; fc)：(2π/c)·√(εr·(f²−fc²))；f<fc 为 NaN。

    fc10=介质填充实际截止 c/(2·w_eff·√εr)，f 与 fc 同单位 Hz。
    §2 钉值互洽校验：β(f0=10GHz, fc10=6.6667, εr=3.66)≈298.8 rad/m
    （λg≈21.02mm）。不得写成 √(εr·f²−fc²)——那是空波导截止口径，与
    fc10 的实际截止定义不自洽（f=fc 时 β≠0 非物理，pt1 as-run 判读
    假 FAIL 根因之一，2026-09-23 勘误）。
    """
    f = np.asarray(f_hz, dtype=float)
    fc = fc10_ghz * 1e9
    k0 = 2.0 * np.pi * f / C0
    val = er * (f**2 - fc**2)
    out = np.where(val > 0.0,
                   k0 * np.sqrt(np.maximum(val, 0.0)) / f, np.nan)
    return out


def fit_fc10(f_hz: np.ndarray, s21: np.ndarray, plane_dist_m: float,
             fc_lo_ghz: float = 5.0, fc_hi_ghz: float = 8.5) -> dict:
    """G1：S21 解缠相位对 φ(f)=−β(f;fc)·L+φ0 做 fc 单参数拟合（φ0 线性消去）。

    返回 {fc_fit_ghz, dev_pct, sign, rms_rad}；fc_closed=闭式 6.6667GHz。
    """
    from scipy.optimize import minimize_scalar

    sel = ((f_hz >= G1_BAND_GHZ[0] * 1e9) & (f_hz <= G1_BAND_GHZ[1] * 1e9))
    f_sel = f_hz[sel]
    phase = np.unwrap(np.angle(s21[sel]))

    def err(fc_ghz: float) -> float:
        beta = beta_closed(f_sel, fc_ghz)
        if np.any(~np.isfinite(beta)):
            return float("inf")
        resid = phase + beta * plane_dist_m        # = φ0 + 噪声
        return float(np.sum((resid - resid.mean()) ** 2))

    res = minimize_scalar(err, bounds=(fc_lo_ghz, fc_hi_ghz),
                          method="bounded",
                          options={"xatol": 1e-5})
    fc_fit = float(res.x)
    dev_pct = (fc_fit - FC10_CLOSED_GHZ) / FC10_CLOSED_GHZ * 100.0
    beta_fit = beta_closed(f_sel, fc_fit)
    resid = phase + beta_fit * plane_dist_m
    return {"fc_fit_ghz": round(fc_fit, 5),
            "fc_closed_ghz": round(FC10_CLOSED_GHZ, 5),
            "dev_pct": round(dev_pct, 4),
            "sign": "+" if fc_fit > FC10_CLOSED_GHZ else "-",
            "rms_rad": round(float(np.sqrt(np.mean((resid - resid.mean()) ** 2))),
                             5)}


def db(x: np.ndarray | float) -> np.ndarray:
    v = np.abs(np.asarray(x))
    return 20.0 * np.log10(np.maximum(v, 1e-300))


def main() -> int:
    ap = argparse.ArgumentParser(description="直 SIW 线段 OE 锚冒烟（预声明门）")
    ap.add_argument("--pt", default="pt1")
    ap.add_argument("--mesh-mm", type=float, default=0.4)
    ap.add_argument("--flo", type=float, default=6.0)
    ap.add_argument("--fhi", type=float, default=13.0)
    ap.add_argument("--nrts", type=int, default=100000)
    ap.add_argument("--timeout-s", type=float, default=6120.0)
    ap.add_argument("--port-mode", choices=("v1", "v2"), default="v1",
                    help="端口方案：v1=z 桥（缺省口径，缺省）；v2=藩篱止于"
                         "端口面+端面口径（v2_criteria.md，按原门重裁 G3）")
    ap.add_argument("--skip-mutex", action="store_true",
                    help="跳过 #261 互斥查询（仅调试用；仍会真跑 OE）")
    args = ap.parse_args()

    out_dir = REPO / "runs" / "siw_family" / args.pt
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_mutex:
        foreign = oe_foreign_running()
        if foreign:
            print("[siw-anchor] #261 互斥命中（他轨 OE 在跑，拒绝起跑，不代杀）：")
            for ln in foreign[:10]:
                print("   ", ln)
            return 2
        print("[siw-anchor] #261 命令行查：无他轨 OE 进程，起跑")

    # ── 渲染（显式审计档 + NrTS 旋钮；criteria §6 运行口径）─────────────────
    band = (args.flo, args.fhi)
    params = {**TEMPLATE_NOMINAL["siw"], "_nrts": args.nrts}
    if args.port_mode == "v2":
        params["_port_mode"] = "v2"
    text = render_script("siw", params, band, mesh_resolution_mm=args.mesh_mm)
    sim_path = out_dir / "simulation.py"
    sim_path.write_text(text, encoding="utf-8")

    t0 = time.time()
    py = str(REPO / ".venv" / "Scripts" / "python.exe")
    proc = subprocess.run(
        [py, "-u", str(sim_path)],
        cwd=str(out_dir), capture_output=True, text=True,
        timeout=args.timeout_s)
    solve_wall = time.time() - t0
    (out_dir / "run_stdout.log").write_text(
        f"rc={proc.returncode}\n\n{proc.stdout}\n\n{proc.stderr}",
        encoding="utf-8")
    if proc.returncode != 0:
        print(f"[siw-anchor] 求解失败 rc={proc.returncode}（详见 "
              f"{out_dir / 'run_stdout.log'}）")
        (out_dir / "summary.json").write_text(json.dumps({
            "ok": False, "stage": "solve",
            "rc": proc.returncode, "wall_s": round(solve_wall, 1),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return 1

    # ── 判读（预声明门 criteria §6）─────────────────────────────────────────
    with open(out_dir / "sparams.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    head = rows[0]
    i_f = head.index("freq_hz")
    i_s11 = (head.index("re_S11"), head.index("im_S11"))
    i_s21 = (head.index("re_S21"), head.index("im_S21"))
    arr = np.asarray([[float(r[i]) for i in range(len(head))] for r in rows[1:]])
    f_hz = arr[:, i_f]
    s11 = arr[:, i_s11[0]] + 1j * arr[:, i_s11[1]]
    s21 = arr[:, i_s21[0]] + 1j * arr[:, i_s21[1]]
    with open(out_dir / "port_beta.csv", newline="") as fh:
        beta_rows = list(csv.DictReader(fh))
    plane_dist = float(beta_rows[0]["plane_dist_m"])
    port_y1 = float(beta_rows[0]["port_y1_m"])
    port_y2 = float(beta_rows[0]["port_y2_m"])

    base = args.mesh_mm * 1e-3  # BASE（显式档；自动档时≈λ_sub/50，仅作 G4 尺度）
    line_len_m = LINE_LEN_MM * 1e-3

    g1 = fit_fc10(f_hz, s21, plane_dist)
    g1_verdict = ("PASS" if abs(g1["dev_pct"]) <= G1_PASS_PCT
                  else "PARTIAL" if abs(g1["dev_pct"]) <= G1_PARTIAL_PCT
                  else "FAIL")

    def s21_db_at(f_ghz: float) -> float:
        j = int(np.argmin(np.abs(f_hz - f_ghz * 1e9)))
        return float(db(s21[j]))

    g2 = {"s21_db_at_6g2": round(s21_db_at(G2_F_GHZ), 3),
          "s21_db_at_10g": round(s21_db_at(G2_REF_GHZ), 3)}
    g2["rolloff_db"] = round(g2["s21_db_at_10g"] - g2["s21_db_at_6g2"], 3)
    g2_verdict = "PASS" if g2["rolloff_db"] >= G2_ROLLOFF_DB else "FAIL"

    sel3 = (f_hz >= G3_BAND_GHZ[0] * 1e9) & (f_hz <= G3_BAND_GHZ[1] * 1e9)
    g3 = {"s21_max_db_in_band": round(float(np.max(db(s21[sel3]))), 3),
          "passivity_max": round(float(np.max(np.abs(s11[sel3]) ** 2
                                              + np.abs(s21[sel3]) ** 2)), 4)}
    g3_verdict = ("PASS" if (g3["s21_max_db_in_band"] >= G3_S21_MIN_DB
                             and g3["passivity_max"] <= G3_PASSIVITY_MAX)
                  else "FAIL")

    g4 = {"plane_dist_m": plane_dist, "port_y1_m": port_y1, "port_y2_m": port_y2,
          "nominal_line_len_m": line_len_m,
          "diff_cells": round(abs(plane_dist - line_len_m) / base, 3)}
    g4_verdict = "PASS" if g4["diff_cells"] <= 1.0 else "FAIL"

    verdicts = {"G1_fc_fit": g1_verdict, "G2_rolloff": g2_verdict,
                "G3_floor_passivity": g3_verdict, "G4_plane_dist": g4_verdict}
    verdict = ("PASS" if all(v == "PASS" for v in verdicts.values())
               else "PARTIAL" if (verdicts["G1_fc_fit"] == "PARTIAL"
                                  and all(v in ("PASS", "PARTIAL")
                                          for v in verdicts.values()))
               else "FAIL")

    summary = {
        "ok": True,
        "template": "siw",
        "pt": args.pt,
        "port_mode": args.port_mode,
        "band_ghz": list(band),
        "mesh_resolution_mm": args.mesh_mm,
        "nrts": args.nrts,
        "solve_wall_s": round(solve_wall, 1),
        "ts": datetime.now(timezone.utc).isoformat(),
        "gates": {"G1": g1, "G2": g2, "G3": g3, "G4": g4},
        "verdicts": verdicts,
        "verdict": verdict,
        "criteria": ("runs/siw_family/v2_criteria.md §4（v2 预声明 #122）"
                     if args.port_mode == "v2" else
                     "runs/siw_family/criteria.md §6（预声明 #122）"),
    }
    (out_dir / "summary.json").write_text(json.dumps(
        summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"[siw-anchor] {args.pt} port_mode={args.port_mode} "
          f"verdict={verdict} "
          f"(G1 {g1_verdict} dev={g1['dev_pct']:+.2f}% sign={g1['sign']}, "
          f"G2 {g2_verdict}, G3 {g3_verdict}, G4 {g4_verdict})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
