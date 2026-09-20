"""§10.3 C1 天线族 II 冒烟（antenna2 六模板真机锚判据，openEMS 真跑）。

用法（同一时刻全机只此一个 openEMS 真跑，COMMON 纪律；逐模板串行）：
    .venv/Scripts/python.exe scripts/smoke_antenna2_anchor.py monopole
    .venv/Scripts/python.exe scripts/smoke_antenna2_anchor.py slot \
        --override slot_l_mm=46.036   # 引擎拟合 k_slot 复核跑（→ slot_override/）
    .venv/Scripts/python.exe scripts/smoke_antenna2_anchor.py loop --tag v2
        # 自由空间改造复跑（→ runs/antenna2_smoke/loop_v2/，旧产物不覆盖）
    .venv/Scripts/python.exe scripts/smoke_antenna2_anchor.py helix \
        --band 1.5,4.5 --tag wide   # 扩带定电抗过零 f_x（→ helix_wide/）

判据（段首理论核验口径；设计式不做端效应预补偿，实测偏差如实记录，
#190 范式：引擎常数未仲裁前不进设计公式）：
- monopole / pifa / ifa：|S11| 谷深 ≤ −8dB 且谷位于 f0±12% 窗（λ0/4 像理论
  设计点，细带端效应使谷位偏低，dipole 58mm 同族口径）。
- slot：S21 辐射凹 ≤ 判读窗底直通 −6dB 且凹位在 f0±12% 窗（过缝辐射负载：
  S11 全带平坦、功率经缝辐射不反射——S11 谷判据不适用，首跑实证）。
- loop（自由空间改造）：Zin=Z0(1+S11)/(1−S11) 电抗过零点位于
  f0±12% 窗且过零处 R ≥ 20Ω（对照旧贴地口径 R=0.56Ω 镜像抵消）；S11 ≤ −5dB
  只作次级（一周长环馈阻抗文献 ≈100-200Ω，对 50Ω 固有失配，谷深不是谐振
  判据——antenna2 坑②：判谐振看电抗过零/并联 R 峰）。
- helix：电抗过零 f_x（容性→感性首个上穿）报告值；S11 深度门不适用（R≈2-6Ω
  电小失配）。f_x 落在扫频带内即 FOUND（供 HFSS 同几何仲裁
  scripts/hfss_helix_arbitration.py 对照，k_helix 不在本脚本进设计式）。

判读窗（slot Σ|S|² 排查收口）：评估带 = SetGaussExcite(F0,FC) 激励
带，其 −20dB 带边 uf_inc 归一化分母趋零放大数值噪声（slot 实测 Σ|S|²
1.9GHz=1.212 / 2.9GHz=1.128，>1.02 全在两侧 ≤0.18GHz 内，f0±12% 窗内 ≤1.008）
——全模板判读只取激励带内 80%（默认 ±0.5GHz 带 → f0±0.4GHz）且剔除
Σ|S|²>1.02 的点；全局 FC 不动（f_max 进 base_m 网格预算，改激励带会漂全部
模板网格锚）。

证据链：runs/antenna2_smoke/<template>[_override|_<tag>]/（sparams.csv +
verdict.json）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.openems_templates import ANTENNA2_NOMINAL

F0 = 2.4                 # 设计点（判据窗 f0±12% 的中心；扩带时不随 --band 移动）
Z0 = 50.0
INNER_FRAC = 0.8         # 判读窗 = 激励带内 80%（高斯 −20dB 带边归一化伪象剔除）
POWER_MAX = 1.02         # Σ|S|² 超此值的点视为带边归一化噪声剔除
DEPTH_GATE = {"loop": -5.0}     # 谷深门（dB）；缺省 −8
R_MIN_LOOP = 20.0        # loop 电抗过零处 R 下限（Ω，对照旧 0.56Ω）


def _parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("template", choices=sorted(ANTENNA2_NOMINAL))
    ap.add_argument("--override", default=None,
                    help="key=value（单参数覆盖，产物落 <template>_override/）")
    ap.add_argument("--band", default=None,
                    help="lo,hi GHz（扩带扫频；缺省 f0±0.5）")
    ap.add_argument("--tag", default=None,
                    help="产物子目录后缀 <template>_<tag>/（新跑不覆盖既有产物）")
    ap.add_argument("--mesh", type=float, default=0.0,
                    help="网格 base 覆盖（mm）；0=自动 λ_sub/50（缺省行为不变；"
                         "helix HFSS 仲裁网格无关性复跑用）")
    return ap.parse_args(argv)


def _reactance_crossings(f: np.ndarray, zin: np.ndarray,
                         ) -> list[dict[str, float | str]]:
    """Zin 电抗过零点（线性插值，双向），返回 [{f_ghz, r_ohm, direction}]。

    direction=up（容性→感性，串联型谐振）/down（感性→容性，并联型 R 峰，
    ifa/pifa 首跑语义）。区间端点恰零（x[i] 或 x[i+1]==0）也算过零。
    """
    x = np.imag(zin)
    r = np.real(zin)
    out: list[dict[str, float | str]] = []
    ends_zero = False   # 上一区间终点恰零（本次过零已记账，防下一区间重复）
    for i in range(len(f) - 1):
        if x[i] == 0.0 and x[i + 1] == 0.0:
            ends_zero = True               # 平坦零（退化，跳过防重复）
            continue
        product = x[i] * x[i + 1]
        if x[i] == 0.0 and ends_zero:
            ends_zero = x[i + 1] == 0.0    # 过零已在上一区间右端点记账
            continue
        ends_zero = False
        if not (product < 0.0 or x[i] == 0.0 or x[i + 1] == 0.0):
            continue
        t = (0.0 - x[i]) / (x[i + 1] - x[i])
        out.append({
            "f_ghz": float(f[i] + t * (f[i + 1] - f[i])),
            "r_ohm": float(r[i] + t * (r[i + 1] - r[i])),
            "direction": "up" if x[i + 1] > x[i] else "down",
        })
        ends_zero = x[i + 1] == 0.0
    return out


def _judge(f_all: np.ndarray, s_all: np.ndarray, template: str,
           params: dict, band: tuple[float, float], solve_s: float,
           work: Path) -> int:
    """判读（真跑与 CSV 复判共用路径）：判读窗 + 判据 + verdict.json 落盘。"""
    fc_ = 0.5 * (band[1] - band[0])
    f_mid = 0.5 * (band[0] + band[1])
    # Σ|S|² = |S11|²+|S21|²（首列；1 端口恒等 |S11|²——不取行以免碰到单端口
    # fallback 填充 S12=S11 的双计，loop_v2 首跑实证 160 点误剔）
    power = (np.abs(s_all[:, 0, 0]) ** 2
             + (np.abs(s_all[:, 1, 0]) ** 2
                if s_all.shape[1] > 1 else 0.0))
    mask = ((np.abs(f_all - f_mid) <= INNER_FRAC * fc_)
            & (power <= POWER_MAX))
    n_win = int(np.sum(np.abs(f_all - f_mid) <= INNER_FRAC * fc_))
    print(f"判读窗 {f_mid - INNER_FRAC * fc_:.3f}-{f_mid + INNER_FRAC * fc_:.3f}GHz："
          f"{int(mask.sum())}/{n_win} 点（Σ|S|² 全带 max={power.max():.4f}，"
          f"窗内剔除 {n_win - int(mask.sum())} 点 >{POWER_MAX}）")
    f = f_all[mask]
    s = s_all[mask]
    s11c = s[:, 0, 0]
    s11 = 20 * np.log10(np.abs(s11c) + 1e-12)
    # 1 端口 (n,1,1) 无 S21 列——打印口复用 S11（真跑时求解器 fallback 填充
    # 同值，口径不变）
    s21 = 20 * np.log10(np.abs(s[:, 0, 1] if s.shape[1] > 1 else s11c) + 1e-12)
    i11 = int(np.argmin(s11))
    i21max = int(np.argmax(s21))
    i21min = int(np.argmin(s21))
    print(f"S11 min: {s11[i11]:.2f} dB @ {f[i11]:.4f} GHz")
    print(f"S21 max: {s21[i21max]:.2f} dB @ {f[i21max]:.4f} GHz")
    print(f"S21 min: {s21[i21min]:.2f} dB @ {f[i21min]:.4f} GHz")
    zin = Z0 * (1.0 + s11c) / (1.0 - s11c)
    crossings = _reactance_crossings(f, zin)
    for c in crossings:
        print(f"  Zin 电抗过零 {c['direction']:>4} @ {c['f_ghz']:.4f} GHz "
              f"R={c['r_ohm']:.2f} Ω")
    lo, hi = F0 * 0.88, F0 * 1.12
    summary: dict[str, object] = {
        "template": template, "params": params, "band_ghz": list(band),
        "solve_s": round(solve_s, 1), "window_points": int(mask.sum()),
        "power_max_all": round(float(power.max()), 4),
        "s11_min_db": round(float(s11[i11]), 3), "f_s11_min_ghz": round(float(f[i11]), 4),
        "s21_min_db": round(float(s21[i21min]), 3), "f_s21_min_ghz": round(float(f[i21min]), 4),
        "reactance_crossings": [{k: (round(v, 4) if isinstance(v, float) else v)
                                 for k, v in c.items()} for c in crossings],
        "gate_window_ghz": [round(lo, 4), round(hi, 4)],
    }
    if template == "slot":
        # 微带跨缝二端口、缝=辐射负载（首跑实证：S11 全带平坦 −0.5~-1.3dB，
        # 功率经缝辐射不反射）：锚签名=S21 凹（辐射耦合峰）位置 + 深度。
        through = s21[0]   # 判读窗底近直通电平
        ok = (s21[i21min] <= through - 6.0 and lo <= f[i21min] <= hi)
        crit = (f"判据：S21 辐射凹 ≤直通−6dB @ {lo:.2f}-{hi:.2f}GHz"
                f"（λ0/2 Booker 对偶缝谐振窗 ±12%）")
    elif template == "loop":
        # 自由空间环：电抗过零在窗内且 R≥20Ω（旧贴地 0.56Ω 镜像抵消）；
        # 过零候选取窗内 R 最大者（并联 R 峰/谐振语义），S11 −5dB 次级报告
        in_win = [c for c in crossings if lo <= float(c["f_ghz"]) <= hi]
        best = max(in_win, key=lambda c: float(c["r_ohm"])) if in_win else None
        ok = best is not None and float(best["r_ohm"]) >= R_MIN_LOOP
        sec = s11[i11] <= DEPTH_GATE["loop"] and lo <= f[i11] <= hi
        summary["best_crossing"] = best
        summary["secondary_s11_gate"] = bool(sec)
        crit = (f"判据：Zin 电抗过零 ∈ {lo:.2f}-{hi:.2f}GHz 且 R≥{R_MIN_LOOP:.0f}Ω"
                f"（得 {best}）；次级 S11≤{DEPTH_GATE['loop']:.0f}dB 窗内："
                f"{'过' if sec else '未过'}")
    elif template == "helix":
        # 电小螺旋：S11 深度门不适用；报告首个容性→感性上穿 f_x（带内即 FOUND）
        ups = [c for c in crossings if c["direction"] == "up"]
        fx = ups[0] if ups else None
        ok = fx is not None
        summary["f_x"] = fx
        crit = (f"判据：电抗过零 f_x（容性→感性首个上穿）落在扫频带 "
                f"{band[0]:.2f}-{band[1]:.2f}GHz 内（得 {fx}；设计点 {F0}GHz，"
                f"k_helix=f_x/{F0} 须经 HFSS 仲裁才进设计式）")
    else:
        depth_gate = DEPTH_GATE.get(template, -8.0)
        ok = s11[i11] <= depth_gate and lo <= f[i11] <= hi
        crit = (f"判据：谷深≤{depth_gate:.0f}dB @ {lo:.2f}-{hi:.2f}GHz"
                f"（闭式谐振窗 ±12% 端效应/口径容差）")
    verdict = ("PASS" if ok else "FAIL") if template != "helix" else \
        ("FOUND" if ok else "NOT_FOUND")
    summary["verdict"] = verdict
    summary["criterion"] = crit
    (work / "verdict.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"ANTENNA2_{template.upper()}_{verdict}（{crit}）")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    template = args.template
    params = dict(ANTENNA2_NOMINAL[template])
    suffix = ""
    if args.override:
        key, val = args.override.split("=")
        params[key] = float(val)
        print(f"override: {key}={params[key]}")
        suffix = "_override"
    if args.tag:
        suffix += f"_{args.tag}"
    if args.band:
        lo_s, hi_s = args.band.split(",")
        band = (float(lo_s), float(hi_s))
    else:
        # 频带 ±0.5GHz：谷位含细带端效应下移（首跑 ±0.25 谷触下带沿=截断
        # 伪象，无法区分真谷与扫频边界），判据窗另按 f0±12% 收口
        band = (F0 - 0.5, F0 + 0.5)
    work = Path(f"runs/antenna2_smoke/{template}{suffix}")
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work), freq_range_ghz=band,
        mesh_resolution_mm=float(args.mesh),
        extra_params={"solve_timeout_s": 36000}))
    assert solver.connect(), "openEMS 不可用"
    assert solver.build_geometry({"template": template, "params": params})
    t0 = time.time()
    result = solver.solve()
    solve_s = time.time() - t0
    print(f"solve_s={solve_s:.0f} success={result.success} "
          f"msg={result.message}", flush=True)
    assert result.success and result.s_params is not None
    return _judge(np.asarray(result.freq_ghz), np.asarray(result.s_params),
                  template, params, band, solve_s, work)


if __name__ == "__main__":
    raise SystemExit(main())
