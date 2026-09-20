"""WP2.5 Tier 2 过渡结构真机冒烟：MSL↔CPWG 过渡 + SMA 边缘弹射（串行）。

范围：MSL↔CPW、SMA
launcher（验收靠文献曲线）；MSL↔slotline（Marchand）随 slotline 端口原语
阻塞另立项，不在本件。名义点 = 附加模板 NOMINAL（综合闭式再生，测试
test_msl_cpw/test_sma_launcher 钉）。

裁判（wstep/via 族同型，Tier 2 无谐振）：
- β 金标准（#162 口径，CalcPort port_beta.csv）：
  msl_cpw  port1→HJ εeff（微带）、port2→CPWG 共形映射闭式，|Δ|≤2%；
  sma_launcher port2→HJ，|Δ|≤2%（port1=同轴截面集总桥，LumpedPort 无 β）。
- |S11| 门 ≤-10dB（带内 max，2.25-2.75GHz）：理想级联地板≈0，引擎偏差
  即过渡/弹射寄生总量；SMA edge-launch 文献带内回损常规 15-20dB，-10dB 为
  保守地板（"验收靠文献曲线"口径）。
- 物理性门（sma 根治增设）：带内 |S11|≤0dB 无源性、带内
  min|S21|≥−3dB（pt2 FAIL 签名 +5.42dB/−375dB 即结构死亡，非精度门）。

运行（串行：同一进程内先 msl_cpw 后 sma_launcher，满足 openEMS 全机
单真跑资源轨；后台+日志轮询 #157）。证据链 runs/wp25_tier2_smoke/：
pt1_msl_cpw3 PASS（勿重跑）、pt2_sma_launcher 根治前 FAIL 留档（只读）、
pt3_sma_launcher_v1 根治后无前脸 FAIL 留档（|S11| −4.0dB）、
pt3_sma_launcher_v2 最终几何 PASS（--only pt3_sma_launcher_v2 --no-cache
--flo 1.5 --fhi 3.5：|S11|@2.5G −11.75dB、β +0.98%、|S21| −0.42dB）。
真机前离线审计（#212）先行：tests/unit/test_msl_cpw_template.py +
test_sma_launcher_template.py 全绿 + scripts/diag_sma_launcher.py 接触图
无短路/地链连通/port1 出 PML_8 即门槛。
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
from rfauto.adapters.openems_templates import (
    MSL_CPW_NOMINAL,
    SMA_LAUNCHER_NOMINAL,
)
from rfauto.core.calculators import _cpwg_ri
from rfauto.core.synthesis import Stackup, forward_z0

parser = argparse.ArgumentParser()
parser.add_argument("--mesh", type=float, default=0.4)
parser.add_argument("--timeout", type=float, default=3600.0)
parser.add_argument("--flo", type=float, default=2.25)
parser.add_argument("--fhi", type=float, default=2.75)
parser.add_argument("--only", default=None,
                    help="只跑单个 case 标签（如 pt1_msl_cpw2）")
parser.add_argument("--no-cache", action="store_true",
                    help="绕开求解器磁盘缓存（缓存不含 port_beta.csv，"
                         "β 证据链须真跑）")
args = parser.parse_args()

F0 = 2.5
BAND = (F0 * 0.9, F0 * 1.1)
S11_GATE_DB = -10.0
BETA_GATE_PCT = 2.0
# |S21| 带内最小值地板：理想级联 ≈−0.5dB（基板 tanδ 0.0037 × 45mm），−3dB 已是
# 结构性死亡（短路/悬空/PML 内激励）的 3 个量级之外——非精度门（#195 语义）
S21_FLOOR_DB = -3.0
stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
OUT = Path("runs/wp25_tier2_smoke")
OUT.mkdir(parents=True, exist_ok=True)


def eps_eff_from_beta(beta: float, f_ghz: float) -> float:
    return float((beta * 299792458.0 / (2 * np.pi * f_ghz * 1e9)) ** 2)


def beta_rows(work: Path) -> list[list[str]]:
    path = work / "port_beta.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.reader(fh))[1:]


def band_beta(rows: list[list[str]], col: int) -> float:
    arr = np.array([[float(r[0]), float(r[col])] for r in rows])
    sel = (arr[:, 0] >= 0.96 * F0 * 1e9) & (arr[:, 0] <= 1.04 * F0 * 1e9)
    return float(np.median(arr[sel, 1]))


def run_case(tag: str, template: str, params: dict,
             anchors: list[tuple[str, float]]) -> dict:
    """单模板真跑 + 双 β 门 + |S11| 门。anchors=[(名, εeff 闭式), ...]。"""
    work = OUT / tag
    extra = {"solve_timeout_s": args.timeout}
    if args.no_cache:
        extra["cache"] = False
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work), freq_range_ghz=(args.flo, args.fhi),
        mesh_resolution_mm=args.mesh,
        extra_params=extra))
    assert solver.connect(), "openEMS 不可用"
    assert solver.build_geometry({"template": template, "params": params})
    t0 = time.time()
    result = solver.solve()
    dt = time.time() - t0
    print(f"[{tag}] solve_s={dt:.0f} success={result.success} "
          f"msg={result.message}", flush=True)
    assert result.success and result.s_params is not None, \
        f"{tag} openEMS 真跑失败"

    f_ghz = np.asarray(result.freq_ghz, dtype=float)
    s = result.s_params
    s11_db = 20 * np.log10(np.abs(s[:, 0, 0]) + 1e-12)
    s21_db = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-12)
    band = (f_ghz >= BAND[0]) & (f_ghz <= BAND[1])
    s11_max = float(s11_db[band].max())
    i_mid = int(np.argmin(np.abs(f_ghz - F0)))

    print(f"[{tag}] @{F0}GHz |S11|={s11_db[i_mid]:.2f}dB "
          f"|S21|={s21_db[i_mid]:.2f}dB 带内max|S11|={s11_max:.2f}dB",
          flush=True)

    rows = beta_rows(work)
    beta_ok = bool(rows)
    beta_report = []
    for col, (name, eps_ref) in enumerate(anchors, start=1):
        if not rows:
            beta_report.append({"port": col, "anchor": name,
                                "eps_ref": eps_ref, "eps_engine": None,
                                "delta_pct": None})
            continue
        beta = band_beta(rows, col)
        eps_eng = eps_eff_from_beta(beta, F0)
        d = (eps_eng / eps_ref - 1) * 100
        beta_report.append({"port": col, "anchor": name, "eps_ref": eps_ref,
                            "eps_engine": eps_eng, "delta_pct": d})
        beta_ok = beta_ok and abs(d) <= BETA_GATE_PCT
        print(f"[{tag}] port{col} β锚 {name}: εeff闭式={eps_ref:.4f} "
              f"引擎={eps_eng:.4f} Δ={d:+.2f}%", flush=True)

    # 物理性门（sma 根治增设，pt2 FAIL 签名：|S11|=+5.42dB 非物理、
    # |S21|≈−375dB 零传输）：带内 |S11|≤0dB 无源性 + |S21| 物理量级（理想
    # 级联 ≈−0.5dB；地板 S21_FLOOR_DB 抓"短路/悬空"类结构死亡，非精度门）
    s11_max_all = float(s11_db[band].max())
    s21_min_band = float(s21_db[band].min())
    passive_ok = bool(s11_max_all <= 0.0)
    s21_ok = bool(s21_min_band >= S21_FLOOR_DB)
    print(f"[{tag}] 无源性 max|S11|={s11_max_all:.2f}dB({'OK' if passive_ok else 'FAIL'})"
          f" 带内min|S21|={s21_min_band:.2f}dB(地板 {S21_FLOOR_DB}dB "
          f"{'OK' if s21_ok else 'FAIL'})", flush=True)

    ok = bool(beta_ok and s11_max <= S11_GATE_DB and passive_ok and s21_ok)
    print(f"[{tag}] {'PASS' if ok else 'FAIL'}（β锚 |Δ|≤{BETA_GATE_PCT}%、"
          f"带内|S11|≤{S11_GATE_DB}dB 文献保守地板、无源性、|S21| 物理量级）",
          flush=True)
    return {"tag": tag, "template": template, "solve_s": round(dt, 1),
            "s11_max_band_db": s11_max, "s11_gate_db": S11_GATE_DB,
            "s11_mid_db": float(s11_db[i_mid]),
            "s21_mid_db": float(s21_db[i_mid]),
            "s21_min_band_db": s21_min_band, "s21_floor_db": S21_FLOOR_DB,
            "passive_ok": passive_ok, "s21_ok": s21_ok,
            "beta": beta_report, "pass": ok}


# ── 名义点闭式锚（确定性内核，数字非手填）──
w_msl = MSL_CPW_NOMINAL["w_msl_mm"]
_, eps_msl = forward_z0(w_msl, F0, stackup)
eps_cpw, _z_cpw = _cpwg_ri(MSL_CPW_NOMINAL["w_cpw_mm"],
                           MSL_CPW_NOMINAL["gap_cpw_mm"],
                           stackup.thickness_mm, stackup.epsilon_r)
_, eps_msl2 = forward_z0(SMA_LAUNCHER_NOMINAL["w_msl_mm"], F0, stackup)

results = []
_ran = False
if args.only in (None, "pt1_msl_cpw"):
    _ran = True
    results.append(run_case(
        "pt1_msl_cpw", "msl_cpw", dict(MSL_CPW_NOMINAL),
        [("msl_hj", eps_msl), ("cpwg_conformal", eps_cpw)]))
# sma：port1=同轴截面集总桥无 β，port_beta.csv 仅 beta2 列（MSL HJ 锚）。
# pt2_sma_launcher = 根治前几何 FAIL 留档（只读，勿重跑）；根治后真跑走 pt3_*
if args.only in (None, "pt3_sma_launcher"):
    _ran = True
    results.append(run_case(
        "pt3_sma_launcher", "sma_launcher", dict(SMA_LAUNCHER_NOMINAL),
        [("msl_hj", eps_msl2)]))
if args.only == "pt2_sma_launcher":
    _ran = True
    results.append(run_case(
        "pt2_sma_launcher", "sma_launcher", dict(SMA_LAUNCHER_NOMINAL),
        [("msl_hj", eps_msl2)]))
if not _ran:
    # 自定义标签：按前缀选模板（pt3_sma_* → sma_launcher，其余 msl_cpw 复跑；
    # 换新 work 目录绕开求解缓存取全量证据）
    if "sma" in str(args.only):
        results.append(run_case(
            args.only, "sma_launcher", dict(SMA_LAUNCHER_NOMINAL),
            [("msl_hj", eps_msl2)]))
    else:
        results.append(run_case(
            args.only, "msl_cpw", dict(MSL_CPW_NOMINAL),
            [("msl_hj", eps_msl), ("cpwg_conformal", eps_cpw)]))

summary = {"f0_ghz": F0, "band_ghz": [args.flo, args.fhi],
           "mesh_mm": args.mesh,
           "results": results,
           "all_pass": all(r["pass"] for r in results)}
# --only 单跑写 summary_<tag>.json，保留历史 summary.json（pt1_msl_cpw3 PASS 留档）
_summary_path = OUT / (f"summary_{args.only}.json" if args.only else "summary.json")
_summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                         encoding="utf-8")
verdict = "PASS" if summary["all_pass"] else "FAIL"
print(f"WP25_TIER2_SMOKE_{verdict}（证据链 {_summary_path}）", flush=True)
