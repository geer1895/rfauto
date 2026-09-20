"""hairpin 电气标定（真机 FAIL 归因轮）。

背景：pt1 冒烟（runs/hairpin_smoke/pt1/，solve_s=1235，β 金标准 PASS）响应
FAIL——@2.5GHz |S21|=-44.89dB / |S11|=+0.1dB，2.485GHz 有 -46dB 传输零点、
带内无通带。几何离线审计全绿（#212，27 测）⇒ 属电气标定缺项，非画法错误。

方法（先定位后单变量标定；每轮只动一个变量、留 runs/ 证据）：
- R0 宽带定位：2.0-3.5GHz 扫频原设计（扫频窗是定位手段、非设计变量），
  读 S21 通带形状 + S11 回损谷 + 传输零点位，区分 f0 偏移 vs 耦合/抽头问题。
  **预登记判读规则**（纪律：归因先当假设/待证，规则先于数据写死）：
  1) 有真通带（全局峰 6dB 带宽 ≥20MHz）→ f0_act=带心；|f0_act-f0|/f0>2%
     → R1 单变量 arm_len_mm 等比缩放（L∝1/f：L_new=L·f0_act/f0）。
  2) 无通带、特征（零点/谷）聚在设计 f0±5% → 耦合/抽头问题 → R1 单变量
     arm_gap_mm 1.0→3.0。预诊断（离线 #212 轮已算）：同臂耦合
     k(arm_gap=1.0)=0.060 反超设计互耦 k(gap=1.133)=0.0515，U 形自两臂
     强耦合使每谐振器偶/奇分裂、同步设计崩塌（假设③定量支撑）；
     arm_gap=3.0 → k_self=0.0115，降为互耦的 ~1/4.5。
  3) 零点落在孤立抽头 λ/4 位（f0/2τ=3.11 / f0/2(1-τ)=2.09GHz）→ 谐振器
     近孤立（互耦弱）旁证，与 2) 同向，仍先动 arm_gap。
- R1/R2 单变量修正：--arm-gap / --arm-len / --tap-frac / --gap 至多传一个，
  其余锁设计值（apply_single_override 守卫，双变量即抛错）。
- 判据（与冒烟同口径）：带内最小插损 -3~-0.2dB、纹波 ≤4dB、回损 ≤-8dB、
  峰位偏差 ≤8%、β±3%（设计窗评估）。

证据链 runs/hairpin_calib/<pt>/：sparams.csv（引擎原产）+ port_beta.csv +
calib.json（全部度量）+ response.png（引擎 vs C13 理想）。

运行（后台+日志轮询，#157；openEMS 全机串行）：
.venv/Scripts/python.exe scripts/hairpin_calib.py --pt pt0_wideband
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
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.openems_templates import hairpin_design_from_order
from rfauto.core.calculators import coupling_matrix_response
from rfauto.core.synthesis import Stackup, forward_z0

# ── 纯分析函数（离线单测面；不触引擎）──────────────────────────────────


def find_local_extrema(freq: np.ndarray, y_db: np.ndarray,
                       thresh_db: float,
                       mode: str = "min") -> list[tuple[float, float]]:
    """局部极值点列表 [(f_ghz, db)]，仅保留优于 thresh_db 的点。

    mode="min" 取谷（S21 零点/S11 回损谷），"max" 取峰。等值游程归并
    （平台不误报）；端点不取（无双侧邻游程）。
    """
    runs: list[tuple[int, int, float]] = []
    start = 0
    for k in range(1, len(y_db) + 1):
        if k == len(y_db) or y_db[k] != y_db[start]:
            runs.append((start, k - 1, float(y_db[start])))
            start = k
    out: list[tuple[float, float]] = []
    for j, (s, e, v) in enumerate(runs):
        if not 0 < j < len(runs) - 1:
            continue
        if mode == "min":
            hit = v < runs[j - 1][2] and v < runs[j + 1][2] and v < thresh_db
        else:
            hit = v > runs[j - 1][2] and v > runs[j + 1][2] and v > thresh_db
        if hit:
            out.append((float(freq[(s + e) // 2]), v))
    return out


def detect_passband(freq: np.ndarray, s21_db: np.ndarray,
                    rel_drop_db: float = 6.0,
                    min_width_ghz: float = 0.02) -> dict | None:
    """全局峰 -rel_drop_db 等高线的连续区间 = 通带候选；过窄判无通带。

    Returns:
        {"f_lo","f_hi","f_center","f_peak","peak_db","width_ghz"} 或 None。
    """
    i_pk = int(np.argmax(s21_db))
    level = s21_db[i_pk] - rel_drop_db
    lo = i_pk
    while lo > 0 and s21_db[lo - 1] >= level:
        lo -= 1
    hi = i_pk
    while hi < len(s21_db) - 1 and s21_db[hi + 1] >= level:
        hi += 1
    width = float(freq[hi] - freq[lo])
    if width < min_width_ghz:
        return None
    return {
        "f_lo": float(freq[lo]), "f_hi": float(freq[hi]),
        "f_center": float((freq[lo] + freq[hi]) / 2),
        "f_peak": float(freq[i_pk]), "peak_db": float(s21_db[i_pk]),
        "width_ghz": width,
    }


def band_metrics(freq: np.ndarray, s21_db: np.ndarray, s11_db: np.ndarray,
                 f0: float, fbw: float) -> dict:
    """设计窗 [f0(1±fbw/2)] 指标：插损/纹波/回损/峰位（与冒烟同口径）。"""
    band = (freq >= f0 * (1 - fbw / 2)) & (freq <= f0 * (1 + fbw / 2))
    if not bool(band.any()):
        return {"il_min_db": float("nan"), "ripple_db": float("nan"),
                "rl_max_db": float("nan"), "f_peak_ghz": float("nan"),
                "peak_dev_pct": float("nan")}
    i_pk = int(np.argmax(np.where(band, s21_db, -1e9)))
    return {
        "il_min_db": float(s21_db[band].min()),
        "ripple_db": float(s21_db[band].max() - s21_db[band].min()),
        "rl_max_db": float(s11_db[band].max()),
        "f_peak_ghz": float(freq[i_pk]),
        "peak_dev_pct": float((freq[i_pk] - f0) / f0 * 100),
    }


def port_health(s11: np.ndarray) -> dict:
    """端口健康（refs §6.4：被动网络 |S11|>1=端口/网格错误信号）。"""
    mag = np.abs(s11)
    return {"max_abs_s11": float(mag.max()),
            "n_above_unity": int(np.count_nonzero(mag > 1.0 + 1e-9))}


def beta_anchor(work: Path, f0_ghz: float,
                eps_hj: float) -> float | None:
    """port_beta.csv → 设计 f0±4% 中位 β → 引擎 εeff 相对 HJ 偏差 %。"""
    csv_path = work / "port_beta.csv"
    if not csv_path.exists():
        return None
    with open(csv_path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    bf = np.array([float(r[0]) for r in rows])
    bb = np.array([float(r[1]) for r in rows])
    sel = (bf >= 0.96 * f0_ghz * 1e9) & (bf <= 1.04 * f0_ghz * 1e9)
    if not bool(sel.any()):
        return None
    beta = float(np.median(bb[sel]))
    eps_eng = (beta * 299792458.0 / (2 * np.pi * f0_ghz * 1e9)) ** 2
    return (eps_eng / eps_hj - 1) * 100


def apply_single_override(design_params: dict, overrides: dict,
                          ladder: bool = False) -> dict:
    """单变量守卫：overrides 相对 design_params 至多 1 个变化。

    ladder=True 为阶梯模式逃生阀：以"上一轮配置"为基准（每轮相对上轮
    仍是单变量），允许显式多个偏离设计值的变量；evidence 的 changed 字段
    带全部 (设计值, 本轮值) 对，归因链不丢。
    """
    allowed = {"arm_len_mm", "arm_gap_mm", "gap_mm", "tap_frac"}
    unknown = set(overrides) - allowed
    if unknown:
        raise ValueError(f"非法标定变量: {sorted(unknown)}；允许 {sorted(allowed)}")
    changed = [k for k, v in overrides.items() if v is not None]
    if len(changed) > 1 and not ladder:
        raise ValueError(f"单变量纪律违规：一次改了 {changed}；只许一个"
                         f"（阶梯轮用 --ladder 显式声明）")
    if not changed:
        raise ValueError("未指定标定变量（--arm-gap/--arm-len/--tap-frac/--gap）")
    out = dict(design_params)
    out.update({k: overrides[k] for k in changed})
    return out


def verdict_of(m: dict, beta_dev_pct: float | None) -> str:
    """预声明判据 → PASS/FAIL（与冒烟同口径）。"""
    ok = (-3.0 <= m["il_min_db"] <= -0.2 and m["ripple_db"] <= 4.0
          and m["rl_max_db"] <= -8.0 and abs(m["peak_dev_pct"]) <= 8.0
          and (beta_dev_pct is None or abs(beta_dev_pct) <= 3.0))
    return "PASS" if ok else "FAIL"


# ── 真机轮 ────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pt", required=True)
    parser.add_argument("--root", default="runs/hairpin_calib",
                        help="证据根目录（缺省 runs/hairpin_calib；"
                             "hairpin_alt k(gap) 图谱复跑指 runs/hairpin_kgap_refix）")
    parser.add_argument("--template", choices=("hairpin", "hairpin_alt"),
                        default="hairpin",
                        help="hairpin_alt=交替取向变体（同设计链几何，奇数序腔翻转；"
                             "k(gap) 图谱复跑用 --order 2 --tap-frac 0.43 逐 --gap 点跑，"
                             "再 hairpin_q_extract --kgap-analyze --gate alt 判读）")
    parser.add_argument("--mesh", type=float, default=0.4)
    parser.add_argument("--order", type=int, default=3)
    parser.add_argument("--fbw", type=float, default=0.05)
    parser.add_argument("--rl", type=float, default=20.0)
    parser.add_argument("--f0", type=float, default=2.5)
    parser.add_argument("--f-lo", type=float, default=2.0)
    parser.add_argument("--f-hi", type=float, default=3.5)
    parser.add_argument("--arm-len", type=float, default=None,
                        help="单变量：展开总长 mm")
    parser.add_argument("--arm-gap", type=float, default=None,
                        help="单变量：U 内两臂缝 mm")
    parser.add_argument("--tap-frac", type=float, default=None,
                        help="单变量：抽头比例 τ")
    parser.add_argument("--gap", type=float, default=None,
                        help="单变量：相邻谐振器耦合缝 mm")
    parser.add_argument("--timeout", type=float, default=7200.0)
    parser.add_argument("--nr-ts", type=int, default=None,
                        help="FDTD 步数上限覆盖（渲染缺省 100000；实测"
                             "交替 y 网格 dt 减半触顶截断，#323 外推后 350000 起跑）")
    parser.add_argument("--ladder", action="store_true",
                        help="阶梯模式：相对上一轮配置单变量（允许多个偏离"
                             "设计值的变量；evidence.changed 记全量对）")
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    f0, fbw = args.f0, args.fbw
    design = hairpin_design_from_order(args.order, f0, fbw, args.rl)
    assert design["gap_mm"] is not None, "等缝锚口径（N=3 等 k）"
    design_params = {
        "order": design["order"],
        "w_mm": round(design["w_mm"], 4),
        "arm_len_mm": round(design["arm_len_mm"], 4),
        "arm_gap_mm": round(design["arm_gap_mm"], 4),
        "gap_mm": round(design["gap_mm"], 4),
        "tap_frac": round(design["tap_frac"], 6),
    }
    overrides = {"arm_len_mm": args.arm_len, "arm_gap_mm": args.arm_gap,
                 "tap_frac": args.tap_frac, "gap_mm": args.gap}
    params = apply_single_override(design_params, overrides,
                                   ladder=args.ladder)
    changed = {k: (design_params[k], params[k])
               for k in design_params
               if k in overrides and overrides[k] is not None}
    print("design:", design_params, flush=True)
    print("calib:", params, f"changed={changed or '{}'}", flush=True)
    _k = "[" + ", ".join(f"{v:.5f}" for v in design["k_list"]) + "]"
    print(f"k_list: {_k} Q_e={design['qe']:.4f}", flush=True)

    stackup = Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508)
    _, eps_hj = forward_z0(params["w_mm"], f0, stackup)

    work = Path(args.root) / args.pt
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work),
        freq_range_ghz=(args.f_lo, args.f_hi),
        mesh_resolution_mm=args.mesh,
        extra_params={"solve_timeout_s": args.timeout}))
    assert solver.connect(), "openEMS 不可用"
    assert solver.build_geometry({"template": args.template, "params": params})
    if args.nr_ts is not None:
        # #312 pt3_nrts 先例：改写已落盘渲染脚本的 NrTS（solve 按脚本文本缓存，
        # 改写后缓存键随之变化不串味）；主 FDTD 与 3 端口支路一并改写保持时窗一致。
        sp = work / "simulation.py"
        txt = sp.read_text(encoding="utf-8")
        n_hit = txt.count("NrTS=100000")
        assert n_hit >= 1, "渲染脚本无 NrTS=100000 可改写"
        sp.write_text(txt.replace("NrTS=100000", f"NrTS={int(args.nr_ts)}"),
                      encoding="utf-8")
        print(f"nr_ts rewrite: {n_hit} 处 100000->{args.nr_ts}", flush=True)
    t0 = time.time()
    result = solver.solve()
    solve_s = time.time() - t0
    print(f"solve_s={solve_s:.0f} success={result.success} "
          f"msg={result.message}", flush=True)
    assert result.success and result.s_params is not None, "openEMS 真跑失败"

    freq = np.asarray(result.freq_ghz, dtype=float)
    s = np.asarray(result.s_params)
    s21_db = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-12)
    s11_db = 20 * np.log10(np.abs(s[:, 0, 0]) + 1e-12)

    ideal = coupling_matrix_response(
        freq_ghz=[float(v) for v in freq], f0_ghz=f0, fbw=fbw,
        matrix=design["coupling_matrix"])

    zeros = find_local_extrema(freq, s21_db, thresh_db=-35.0, mode="min")
    dips = find_local_extrema(freq, s11_db, thresh_db=-5.0, mode="min")
    peaks21 = find_local_extrema(freq, s21_db, thresh_db=-25.0, mode="max")
    passband = detect_passband(freq, s21_db)
    metrics = band_metrics(freq, s21_db, s11_db, f0, fbw)
    health = port_health(s[:, 0, 0])
    beta_dev = beta_anchor(work, f0, eps_hj)

    print(f"窗口 {freq[0]:.3f}-{freq[-1]:.3f}GHz", flush=True)
    print(f"S21 峰: {s21_db.max():.2f}dB @ {freq[int(np.argmax(s21_db))]:.4f}GHz",
          flush=True)
    print(f"S21 零点(<-35dB): {[(round(a, 4), round(b, 1)) for a, b in zeros]}",
          flush=True)
    print(f"S11 回损谷(<-5dB): {[(round(a, 4), round(b, 1)) for a, b in dips]}",
          flush=True)
    print(f"通带(6dB 等高): {passband}", flush=True)
    print(f"设计窗指标: {metrics}", flush=True)
    print(f"端口健康: {health}", flush=True)
    print(f"β 金标准（f0±4% 中位）: HJ={eps_hj:.4f} "
          f"delta={beta_dev if beta_dev is not None else float('nan'):+.2f}%",
          flush=True)
    verdict = verdict_of(metrics, beta_dev)
    print(f"HAIRPIN_CALIB_{verdict}（pt={args.pt}）判据：带内插损 -3~-0.2dB、"
          f"纹波 ≤4dB、回损 ≤-8dB、峰位偏差 ≤8%、β±3%", flush=True)

    evidence = {
        "pt": args.pt, "template": args.template,
        "f0_ghz": f0, "fbw": fbw, "mesh_mm": args.mesh,
        "window_ghz": [float(freq[0]), float(freq[-1])],
        "design_params": design_params, "calib_params": params,
        "changed": {k: list(v) for k, v in changed.items()},
        "k_list": [float(v) for v in design["k_list"]],
        "qe": float(design["qe"]),
        "s21_zeros": zeros, "s11_dips": dips, "s21_peaks": peaks21,
        "passband": passband, "band_metrics": metrics,
        "port_health": health,
        "beta_dev_pct": beta_dev, "solve_s": solve_s,
        "nr_ts": args.nr_ts,
        "verdict": verdict,
        "ideal_band_metrics": None,
    }
    # C13 理想裁判带内指标（同轴插值窗）
    ideal_s21 = np.asarray(ideal["s21_db"], dtype=float)
    ideal_s11 = np.asarray(ideal["s11_db"], dtype=float)
    evidence["ideal_band_metrics"] = band_metrics(
        freq, ideal_s21, ideal_s11, f0, fbw)

    out_json = work / "calib.json"
    out_json.write_text(json.dumps(evidence, indent=1, ensure_ascii=False,
                                   default=str), encoding="utf-8")
    print(f"evidence: {out_json}", flush=True)

    if not args.no_plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 7))
        ax1.plot(freq, s21_db, label="engine |S21|")
        ax1.plot(freq, ideal_s21, "--", label="C13 ideal |S21|")
        for a, _b in zeros:
            ax1.axvline(a, color="gray", lw=0.5, alpha=0.6)
        ax1.set_ylabel("|S21| dB")
        ax2.plot(freq, s11_db, label="engine |S11|")
        ax2.plot(freq, ideal_s11, "--", label="C13 ideal |S11|")
        for a, _b in dips:
            ax2.axvline(a, color="gray", lw=0.5, alpha=0.6)
        ax2.axvspan(f0 * (1 - fbw / 2), f0 * (1 + fbw / 2),
                    color="orange", alpha=0.15)
        ax2.set_xlabel("freq GHz")
        ax2.set_ylabel("|S11| dB")
        for ax in (ax1, ax2):
            ax.grid(True, alpha=0.3)
            ax.legend()
        fig.suptitle(f"hairpin calib {args.pt} changed={changed or '{}'} "
                     f"verdict={verdict}")
        fig.tight_layout()
        fig.savefig(work / "response.png", dpi=130)
        plt.close(fig)


if __name__ == "__main__":
    main()
