"""branchline 四端口真机源 → .s4p → 场路协同锚链（openems-real-smoke-bundle ④）。

背景：solve_smatrix_openems 通用轮转→.s{N}p、锚链吃任意 snp_path（field_circuit
_anchor.py:161-162 契约『真机 .s4p 放同一路径位，下游零改动』）、闭式
branchline_smatrix / macromodel_bridge 均已有；真缺口=branchline 模板只 3 端口
（port4 PML 端接）产不出真 4×4。本轮模板面已升级四端口（openems_templates
`_branchline_lines` port4 真 MSLPort + `_excite_port` 四态 + 入
_FOUR_PORT_ROTATION_TEMPLATES，#212 离线审计九判据先过），本脚本做真机段：

1. solve_smatrix_openems(template="branchline", n_ports=4, mesh 0.4) → 4 次
   单激励进程隔离真跑（#208）→ runs/<root>/branchline.s4p；
2. 门（预声明口径；#122 不凑绿）：
   G1 无源性 max σ_max(S) ≤ 1+1%；G2 互易 max|S−Sᵀ| ≤ 0.02；
   G3 f0=2.4GHz（TEMPLATE_META 名义）处 |S21|、|S31| ∈ −3±1dB；
   G4 f0 处 |S11|、|S41| ≤ −15dB；另测 G5 β 金标准（p1 port_beta，50Ω 馈线 HJ
   εeff）|Δ|≤2%——β 不在预声明门内，失守只记录为模板面异象不翻转判定。
   并在引擎实测均分中心 f_c（||S21|−|S31|| 最小点）复评 G3/G4：2.4GHz 未过
   而 f_c 过 → PARTIAL 并量化偏移（HJ synthesize_branchline 参照；不改名义参数）。
3. 报告项：闭式 branchline_smatrix 对拍 D12 FSV 等级（f0 名义与 f_c 两口径；
   相位护栏仅记录，引擎相位含端口分解伪象 #161）、SpecEvaluator.sanity_check、
   macromodel_bridge(真 .s4p) RMS/等级/无源、run_field_circuit_anchor(snp_path=
   真 .s4p) 全链（ADS 段许可阻塞维持 skip-not-fail，0bn PARTIAL 同源）。

产物 runs/branchline_real_anchor/{p1..p4/, branchline.s4p, anchor/anchor_report.json,
_smoke_result.json}。
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

from rfauto.adapters.em_solver_base import resolve_openems_exe
from rfauto.adapters.openems_rotation import solve_smatrix_openems
from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL
from rfauto.core.synthesis import Stackup, forward_z0

F0_NOMINAL_GHZ = float(TEMPLATE_META["branchline"]["f0_ghz"])
FREQ_RANGE = (1.6, 3.2)   # field_circuit_anchor.DEFAULT_FREQ_BAND_HZ 同口径


def passivity_reciprocity(s: np.ndarray) -> dict[str, float]:
    """确定性无源/互易量：max σ_max(S)、max|S−Sᵀ|（纯 numpy，离线可测）。"""
    sig = np.linalg.svd(s, compute_uv=False)
    return {"sigma_max": float(np.max(sig)),
            "recip_max": float(np.max(np.abs(s - np.transpose(s, (0, 2, 1)))))}


def split_metrics(f_ghz: np.ndarray, s: np.ndarray, f_eval_ghz: float) -> dict[str, float]:
    """f_eval 处 |S11|/|S21|/|S31|/|S41| dB（最近频点）。"""
    i = int(np.argmin(np.abs(f_ghz - f_eval_ghz)))
    db = 20 * np.log10(np.abs(s[i]) + 1e-12)
    return {"f_ghz": float(f_ghz[i]), "s11_db": float(db[0, 0]), "s21_db": float(db[1, 0]),
            "s31_db": float(db[2, 0]), "s41_db": float(db[3, 0])}


def equal_split_center(f_ghz: np.ndarray, s: np.ndarray,
                       window_ghz: tuple[float, float] | None = None) -> float:
    """引擎实测均分中心：||S21|−|S31|| dB 最小点（可选窗内）。"""
    d = np.abs(20 * np.log10(np.abs(s[:, 1, 0]) + 1e-12) - 20 * np.log10(np.abs(s[:, 2, 0]) + 1e-12))
    mask = np.ones_like(f_ghz, dtype=bool)
    if window_ghz:
        mask = (f_ghz >= window_ghz[0]) & (f_ghz <= window_ghz[1])
    idx = np.where(mask)[0]
    return float(f_ghz[idx[int(np.argmin(d[idx]))]])


def split_gates(m: dict[str, float]) -> dict[str, object]:
    return {
        "s21_db": {"value": m["s21_db"], "ok": -4.0 <= m["s21_db"] <= -2.0},
        "s31_db": {"value": m["s31_db"], "ok": -4.0 <= m["s31_db"] <= -2.0},
        "s11_db": {"value": m["s11_db"], "ok": m["s11_db"] <= -15.0},
        "s41_db": {"value": m["s41_db"], "ok": m["s41_db"] <= -15.0},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="runs/branchline_real_anchor")
    parser.add_argument("--mesh", type=float, default=0.4)
    parser.add_argument("--timeout", type=float, default=7200.0)
    args = parser.parse_args(argv)

    root = Path(args.root)
    params = dict(TEMPLATE_NOMINAL["branchline"])
    t0 = time.time()
    rot = solve_smatrix_openems(
        root, template="branchline", params=params, freq_range_ghz=FREQ_RANGE,
        mesh_resolution_mm=args.mesh, n_ports=4, timeout_s=int(args.timeout),
        exe_path=resolve_openems_exe())
    wall = time.time() - t0
    print(f"rotation ok={rot.get('ok')} elapsed_s={rot.get('elapsed_s')} wall={wall:.0f} "
          f"msg={rot.get('message')} errors={rot.get('errors')}", flush=True)
    assert rot.get("ok"), f"轮转失败: {rot.get('errors')}"
    s4p = Path(rot["s4p_path"])
    assert s4p.exists() and s4p.suffix == ".s4p"

    import skrf

    net = skrf.Network(str(s4p))
    f_ghz = net.f / 1e9
    s = net.s
    assert s.shape[1:] == (4, 4)

    pr = passivity_reciprocity(s)
    m_f0 = split_metrics(f_ghz, s, F0_NOMINAL_GHZ)
    f_c = equal_split_center(f_ghz, s)
    m_fc = split_metrics(f_ghz, s, f_c)
    g_f0 = split_gates(m_f0)
    g_fc = split_gates(m_fc)

    # HJ 综合参照（core.synthesis.synthesize_branchline，确定性内核）：名义 arm_len 对应的
    # 期望中心 vs 引擎实测 f_c——量化"名义参数与声明 f0 不一致"的偏移来源
    from rfauto.core.synthesis import synthesize_branchline

    hj_f0 = synthesize_branchline(f0_ghz=F0_NOMINAL_GHZ, z0_ohm=50.0,
                                  stackup_name="rogers4350b_h0.508").params
    hj_fc = synthesize_branchline(f0_ghz=f_c, z0_ohm=50.0,
                                  stackup_name="rogers4350b_h0.508").params
    hj = {"arm_len_mm_hj_at_f0_nominal": float(hj_f0["arm_len_mm"]),
          "arm_len_mm_hj_at_fc_measured": float(hj_fc["arm_len_mm"]),
          "arm_len_mm_nominal": float(params["arm_len_mm"]),
          "expected_f0_for_nominal_arm_ghz": F0_NOMINAL_GHZ * float(hj_f0["arm_len_mm"]) / float(params["arm_len_mm"]),
          "shunt_w_mm_hj": float(hj_f0["shunt_w_mm"]), "series_w_mm_hj": float(hj_f0["series_w_mm"])}

    # G5 β 金标准（p1 的 port_beta.csv，50Ω 馈线 shunt_w）
    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    _, eps_hj = forward_z0(float(params["shunt_w_mm"]), F0_NOMINAL_GHZ, stackup)
    d_beta = float("nan")
    beta_csv = root / "p1" / "port_beta.csv"
    if beta_csv.exists():
        with open(beta_csv, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))[1:]
        bf = np.array([float(r[0]) for r in rows])
        bb = np.array([float(r[1]) for r in rows])
        sel = (bf >= 0.96 * F0_NOMINAL_GHZ * 1e9) & (bf <= 1.04 * F0_NOMINAL_GHZ * 1e9)
        eps_eng = (float(np.median(bb[sel])) * 299792458.0 / (2 * np.pi * F0_NOMINAL_GHZ * 1e9)) ** 2
        d_beta = (eps_eng / eps_hj - 1) * 100

    # ── 报告项：闭式对拍 FSV（两口径）、sanity_check、宏模型桥、锚链全程 ──
    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.linkage.field_circuit_anchor import (
        branchline_smatrix,
        fsv_cascade_report,
        macromodel_bridge,
        run_field_circuit_anchor,
    )

    def _fsv_at(f0_ghz: float) -> dict:
        s_cf = branchline_smatrix(net.f, f0_hz=f0_ghz * 1e9)
        net_cf = skrf.Network(frequency=net.frequency, s=s_cf, z0=50.0)
        rep = fsv_cascade_report(net, net_cf, params=("S11", "S21", "S31", "S41"),
                                 phase_params=("S21", "S31"))
        rep["note"] = "相位护栏仅记录（引擎 uf_ref/uf_inc 相位含端口分解伪象 #161），门只看 gdm 等级"
        return rep

    fsv_f0 = _fsv_at(F0_NOMINAL_GHZ)
    fsv_fc = _fsv_at(f_c)
    sanity = SpecEvaluator.sanity_check(
        net, [Objective(metric="s11_db", band=(2.3, 2.5), op="max_below", value=-15.0)],
        f0_ghz=F0_NOMINAL_GHZ)

    mm: dict[str, object]
    try:
        fit = macromodel_bridge(s4p)
        mm = {"ok": bool(fit["ok"]), "rms_db_final": fit["fit"]["rms_db_final"],
              "worst_gdm_grade": fit["fsv"]["worst_gdm_grade"],
              "passive_in_band": fit["passivity"]["after"]["passive_in_band"],
              "reconstruction_verified": fit["reconstruction_verified"],
              "n_poles_total": fit["order"]["n_poles_total"]}
    except Exception as exc:  # 观测性 best-effort（#105）
        mm = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    anchor = run_field_circuit_anchor(s4p, root / "anchor", f0_hz=F0_NOMINAL_GHZ * 1e9)
    ads_status = (anchor.get("ads") or {}).get("status")
    ads_blocked = ads_status == "error"

    gates = {
        "G1_passivity_sigma_max": {"value": pr["sigma_max"], "ok": pr["sigma_max"] <= 1.01},
        "G2_reciprocity_max": {"value": pr["recip_max"], "ok": pr["recip_max"] <= 0.02},
        "G3_G4_at_f0_nominal": {"f_ghz": m_f0["f_ghz"], "gates": g_f0,
                                "ok": all(v["ok"] for v in g_f0.values())},
        "G3_G4_at_fc_measured": {"f_ghz": m_fc["f_ghz"], "gates": g_fc,
                                 "ok": all(v["ok"] for v in g_fc.values())},
        # β 不在预声明门内（本项新增测量）：+11.5% 失守如实记录为模板面新异象，
        # 独立三探针复算与引擎 β 逐位一致 → 非提取 bug（见 hypothesis_beta）
        "G5_beta_feed_pct_recorded": {"value": d_beta, "limit": 2.0,
                                      "recorded": True,
                                      "ok": bool(np.isnan(d_beta) or abs(d_beta) <= 2.0)},
    }
    core = gates["G1_passivity_sigma_max"]["ok"] and gates["G2_reciprocity_max"]["ok"]
    if core and gates["G3_G4_at_f0_nominal"]["ok"] and gates["G5_beta_feed_pct_recorded"]["ok"]:
        verdict = "PASS"
    elif core and gates["G3_G4_at_fc_measured"]["ok"]:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    hypothesis_beta = (
        "β 异象（假设待证）：port1 馈线 β 对应 εeff=3.182 全带平坦，HJ 闭式 2.853（w=1.11mm）"
        "偏 +11.5%；独立三探针 cosβd 复算与 MSLPort.beta 逐位一致（提取链无 bug）；"
        "wstep 同宽线同网格 +0.87%、ratrace/gysel β 门 ±2% 全过 → branchline 特有。"
        "候选解释：环角/结点激励的介质内平行板模（εeff≈εr=3.66）混入馈线探针平面——"
        "与实测 3.182 介于线模 2.88 与平板模 3.66 之间自洽。后续：探针移近板边/介质盒"
        "边界实验、或按 ratrace 范式加地过孔墙后再判读")

    print(f"σmax={pr['sigma_max']:.4f} recip={pr['recip_max']:.4f} β{d_beta:+.2f}% | @2.4: {m_f0} | "
          f"f_c={f_c:.4f}: {m_fc}")
    print(f"FSV@f0 worst={fsv_f0['worst_gdm_grade']} FSV@fc worst={fsv_fc['worst_gdm_grade']} "
          f"sanity={sanity.model_dump()} macromodel={mm} ads={ads_status} anchor_ok={anchor.get('ok')}")
    print(f"BRANCHLINE_REAL_ANCHOR_{verdict}", flush=True)

    result = {
        "item": "openems-real-smoke-bundle/④branchline_real_anchor", "verdict": verdict,
        "root": str(root), "s4p_path": str(s4p), "params": params, "mesh_mm": args.mesh,
        "freq_range_ghz": list(FREQ_RANGE), "n_runs": rot.get("n_runs"),
        "n_reused": rot.get("n_reused"), "rotation_elapsed_s": rot.get("elapsed_s"),
        "wall_s": round(wall, 1), "f0_nominal_ghz": F0_NOMINAL_GHZ, "f_c_measured_ghz": f_c,
        "f_c_shift_pct": (f_c / F0_NOMINAL_GHZ - 1) * 100,
        "hj_synthesis_reference": hj,
        "passivity_reciprocity": pr, "metrics_at_f0": m_f0, "metrics_at_fc": m_fc,
        "beta": {"eps_hj_feed": eps_hj, "delta_pct": d_beta},
        "hypothesis_beta": hypothesis_beta,
        "gates": gates,
        "closed_form_fsv": {"at_f0_nominal": fsv_f0, "at_fc_measured": fsv_fc},
        "sanity_check": sanity.model_dump(),
        "macromodel_bridge": mm,
        "anchor_chain": {"ok": anchor.get("ok"), "ads": anchor.get("ads"),
                         "fsv": (anchor.get("fsv") or {}).get("status", "present"),
                         "macromodel": anchor.get("macromodel"),
                         "back_annotation": (anchor.get("back_annotation") or {}).get("consistent"),
                         "report": str(root / "anchor" / "anchor_report.json"),
                         "ads_blocked_user_side": ads_blocked,
                         "policy": "ADS 许可阻塞 skip-not-fail（0bn PARTIAL 同源），不计入本项门"},
    }
    (root / "_smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
