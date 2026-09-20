"""§10.3 C2 阵列族冒烟（openEMS 真机锚判据；本项只建离线判据，真跑为 openEMS 轨 followUp）。

用法（同一时刻全机只此一个 openEMS 真跑；逐模板串行单飞，NrTS=100000 分钟~小时级）：
    .venv/Scripts/python.exe scripts/smoke_array_anchor.py patch_array_1x4
    .venv/Scripts/python.exe scripts/smoke_array_anchor.py patch_array_series \
        --override link_len_mm=16.0     # 参数复核跑
    .venv/Scripts/python.exe scripts/smoke_array_anchor.py patch_array_2x2 --no-far-field

判据（openems_templates.py C2 段理论核验口径；设计式不做端效应预补偿，实测偏差
如实记录，#190 范式：引擎常数未仲裁前不进设计公式）：
- S11：谷深 ≤ −6dB（s11_db_min 语义 #195，一阶未匹配口径 fake 预期 −6.2/−2.1dB，
  真机插入馈匹配应更深）且谷位落在 f0±12% 窗（smoke_antenna2_anchor 同款窗）。
- far_field（nf2ff）：阵列面切面主瓣 |θ| ≤ 5°（侧射天顶）；HPBW 与闭式
  （patch_element_field × array_factor，core/farfield.hpbw_deg 同算法）相对偏差
  ≤ 30%；Dmax 与闭式（无限大地面上半空间积分 dmax_from_grid）线性比偏差 ≤ 30%；
  η=Prad/P_acc ∈ (0.3, 1.05]（有耗基板 tanδ=0.0037 + 数值闭合容差）。

判据函数（judge_s11 / expected_pattern / judge_far_field）纯 numpy 无求解器，
tests/unit/test_array_templates.py 离线单测覆盖。证据链：runs/array_smoke/<template>[_override]/。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.openems_templates import ARRAY_NOMINAL, ARRAY_TEMPLATES
from rfauto.core.array_synthesis import (
    array_factor_angles,
    has_grating_lobe,
    patch_element_field,
    pattern_multiplication,
    planar_array_factor,
    uniform_weights,
)
from rfauto.core.farfield import dmax_dbi, dmax_from_grid, hpbw_deg, pattern_db

F0 = 5.8
C_MM_GHZ = 299.792458
WINDOW = 0.12
S11_MIN_DEPTH_DB = -6.0
PEAK_TOL_DEG = 5.0
HPBW_TOL_FRAC = 0.30
DMAX_TOL_FRAC = 0.30
ETA_RANGE = (0.3, 1.05)

# 阵列面切面 φ（1×4 沿 x → φ=0；串馈沿 y → φ=90；2×2 两面皆判）
ARRAY_PLANE_PHI: dict[str, tuple[float, ...]] = {
    "patch_array_1x4": (0.0,),
    "patch_array_2x2": (0.0, 90.0),
    "patch_array_series": (90.0,),
}


def judge_s11(freq_ghz, s11_db, f0_ghz: float = F0, window: float = WINDOW,
              min_depth_db: float = S11_MIN_DEPTH_DB) -> dict[str, Any]:
    """S11 谷位 f0±window 窗 + 谷深门（谷深语义 s11_db_min，#195）。"""
    f = np.asarray(freq_ghz, dtype=float)
    s = np.asarray(s11_db, dtype=float)
    if f.shape != s.shape or f.size < 3:
        raise ValueError("freq/s11 形状不一致或采样不足")
    i = int(np.argmin(s))
    lo, hi = f0_ghz * (1.0 - window), f0_ghz * (1.0 + window)
    depth_ok = bool(s[i] <= min_depth_db)
    window_ok = bool(lo <= f[i] <= hi)
    return {"ok": depth_ok and window_ok, "depth_ok": depth_ok, "window_ok": window_ok,
            "f_dip_ghz": float(f[i]), "s11_min_db": float(s[i]),
            "window_ghz": [lo, hi], "min_depth_db": min_depth_db}


def _closed_form_total(template: str, params: dict[str, Any], f0_ghz: float,
                       theta_deg, phi_deg) -> np.ndarray:
    """闭式总方向图 |F_elem·AF|（单元 L 沿 y；1×4 沿 x、串馈沿 y、2×2 可分离积）。"""
    lam0 = C_MM_GHZ / f0_ghz
    elem = patch_element_field(theta_deg, phi_deg, len_mm=float(params["elem_len_mm"]),
                               width_mm=float(params["elem_w_mm"]), freq_ghz=f0_ghz,
                               axis="y")
    if template == "patch_array_1x4":
        af = array_factor_angles(theta_deg, uniform_weights(4), phi_deg=phi_deg,
                                 spacing_lambda=float(params["spacing_mm"]) / lam0,
                                 scan_deg=0.0, axis="x")
    elif template == "patch_array_series":
        pitch = float(params["elem_len_mm"]) + float(params["link_len_mm"])
        af = array_factor_angles(theta_deg, uniform_weights(3), phi_deg=phi_deg,
                                 spacing_lambda=pitch / lam0, scan_deg=0.0, axis="y")
    else:
        af = planar_array_factor(theta_deg, phi_deg, uniform_weights(2), uniform_weights(2),
                                 spacing_x_lambda=float(params["spacing_x_mm"]) / lam0,
                                 spacing_y_lambda=float(params["spacing_y_mm"]) / lam0)
    return np.abs(pattern_multiplication(elem, af))


def expected_pattern(template: str, params: dict[str, Any] | None = None,
                     f0_ghz: float = F0) -> dict[str, Any]:
    """闭式期望（确定性内核，零仿真）：主瓣天顶、各阵列面 HPBW、Dmax、栅瓣判据。

    Dmax 以无限大 PEC 地面口径（下半空间零场）在 θ 0..180/φ 0..360 网格上
    球面积分（core/farfield.dmax_from_grid）；真机有限基板/域截断使实测偏低，
    容差 30% 线性比。
    """
    if template not in ARRAY_TEMPLATES:
        raise KeyError(f"非 C2 阵列模板: {template}")
    p = dict(ARRAY_NOMINAL[template]) if params is None else dict(params)
    lam0 = C_MM_GHZ / f0_ghz
    if template == "patch_array_1x4":
        spacing = [float(p["spacing_mm"]) / lam0]
    elif template == "patch_array_series":
        spacing = [(float(p["elem_len_mm"]) + float(p["link_len_mm"])) / lam0]
    else:
        spacing = [float(p["spacing_x_mm"]) / lam0, float(p["spacing_y_mm"]) / lam0]
    theta = np.arange(-90.0, 90.0 + 0.5, 0.5)
    hpbw: dict[str, float | None] = {}
    for phi in ARRAY_PLANE_PHI[template]:
        cut = _closed_form_total(template, p, f0_ghz, theta, phi)
        hpbw[f"phi_{int(phi)}"] = hpbw_deg(theta, pattern_db(cut))
    th3 = np.radians(np.arange(0.0, 180.0 + 1e-9, 2.0))
    ph3 = np.radians(np.arange(0.0, 360.0 + 1e-9, 2.0))
    upper = th3 <= np.pi / 2 + 1e-12
    grid = np.zeros((th3.size, ph3.size))
    tt, pp = np.meshgrid(np.degrees(th3[upper]), np.degrees(ph3), indexing="ij")
    grid[upper, :] = _closed_form_total(template, p, f0_ghz, tt, pp) ** 2
    dmax_lin = dmax_from_grid(grid, th3, ph3)
    return {"template": template, "f0_ghz": f0_ghz, "main_lobe_theta_deg": 0.0,
            "spacing_lambda": spacing,
            "grating_lobe_free": all(not has_grating_lobe(s) for s in spacing),
            "hpbw_deg": hpbw, "dmax_linear": dmax_lin, "dmax_dbi": dmax_dbi(dmax_lin)}


def judge_far_field(cuts: list[dict[str, Any]], meta: dict[str, Any],
                    expected: dict[str, Any], *, peak_tol_deg: float = PEAK_TOL_DEG,
                    hpbw_tol_frac: float = HPBW_TOL_FRAC,
                    dmax_tol_frac: float = DMAX_TOL_FRAC) -> dict[str, Any]:
    """nf2ff 产物（OpenEMSSolver._parse_farfield 契约：cuts[{phi_deg, peak_theta_deg,
    hpbw_deg}] + meta{dmax_linear, efficiency}）对照闭式期望。"""
    checks: dict[str, Any] = {}
    ok = True
    by_phi = {float(c["phi_deg"]): c for c in cuts}
    for key, exp_hpbw in expected["hpbw_deg"].items():
        phi = float(key.split("_")[1])
        cut = by_phi.get(phi)
        if cut is None or cut.get("peak_theta_deg") is None:
            checks[key] = {"ok": False, "reason": "缺切面/峰值不可判读"}
            ok = False
            continue
        peak = float(cut["peak_theta_deg"])
        peak_ok = abs(((peak + 180.0) % 360.0) - 180.0) <= peak_tol_deg
        got = cut.get("hpbw_deg")
        if exp_hpbw is None or got is None:
            hpbw_ok, rel = False, None
        else:
            rel = abs(float(got) - float(exp_hpbw)) / float(exp_hpbw)
            hpbw_ok = rel <= hpbw_tol_frac
        checks[key] = {"ok": peak_ok and hpbw_ok, "peak_theta_deg": peak,
                       "hpbw_deg": got, "hpbw_expected_deg": exp_hpbw, "hpbw_rel": rel}
        ok = ok and peak_ok and hpbw_ok
    dmax = meta.get("dmax_linear")
    if dmax is None or not float(dmax) > 0.0:
        checks["dmax"] = {"ok": False, "reason": "Dmax 缺失"}
        ok = False
    else:
        ratio = float(dmax) / float(expected["dmax_linear"])
        dmax_ok = abs(ratio - 1.0) <= dmax_tol_frac
        checks["dmax"] = {"ok": dmax_ok, "dmax_dbi": dmax_dbi(float(dmax)),
                          "expected_dbi": expected["dmax_dbi"], "ratio": ratio}
        ok = ok and dmax_ok
    eta = meta.get("efficiency")
    eta_ok = eta is not None and ETA_RANGE[0] < float(eta) <= ETA_RANGE[1]
    checks["efficiency"] = {"ok": bool(eta_ok), "eta": eta, "range": list(ETA_RANGE)}
    ok = ok and bool(eta_ok)
    return {"ok": ok, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("template", choices=list(ARRAY_TEMPLATES))
    ap.add_argument("--override", action="append", default=[],
                    help="key=value 参数覆盖（可多次）")
    ap.add_argument("--no-far-field", action="store_true",
                    help="不注入 nf2ff（只判 S11，省时）")
    args = ap.parse_args(argv)
    params = dict(ARRAY_NOMINAL[args.template])
    for item in args.override:
        key, val = item.split("=")
        params[key] = float(val)
        print(f"override: {key}={params[key]}")
    work = Path(f"runs/array_smoke/{args.template}"
                + ("_override" if args.override else ""))

    from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
    from rfauto.adapters.openems_solver import OpenEMSSolver

    # 频带 ±0.5GHz（antenna2 冒烟同款：谷位含端效应偏移，窗另按 f0±12% 收口）
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work), freq_range_ghz=(F0 - 0.5, F0 + 0.5),
        mesh_resolution_mm=0,
        extra_params={"solve_timeout_s": 36000}))
    assert solver.connect(), "openEMS 不可用"
    assert solver.build_geometry({"template": args.template, "params": params,
                                  "far_field": not args.no_far_field})
    t0 = time.time()
    result = solver.solve()
    print(f"solve_s={time.time() - t0:.0f} success={result.success} "
          f"msg={result.message}", flush=True)
    assert result.success and result.s_params is not None

    f = np.asarray(result.freq_ghz)
    s11_db = 20 * np.log10(np.abs(result.s_params[:, 0, 0]) + 1e-12)
    verdict_s11 = judge_s11(f, s11_db)
    print(f"S11 min: {verdict_s11['s11_min_db']:.2f} dB @ {verdict_s11['f_dip_ghz']:.4f} GHz "
          f"（窗 {verdict_s11['window_ghz'][0]:.2f}-{verdict_s11['window_ghz'][1]:.2f}）"
          f" → {'PASS' if verdict_s11['ok'] else 'FAIL'}")
    ok = verdict_s11["ok"]
    if not args.no_far_field:
        ff = solver.get_nf2ff()
        if not ff.get("ok"):
            print(f"nf2ff 不可判读: {ff.get('error')}")
            ok = False
        else:
            expected = expected_pattern(args.template, params)
            verdict_ff = judge_far_field(ff["cuts"], ff["meta"], expected)
            for key, chk in verdict_ff["checks"].items():
                print(f"  far_field {key}: {chk}")
            ok = ok and verdict_ff["ok"]
    print(f"ARRAY_{args.template.upper()}_{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
