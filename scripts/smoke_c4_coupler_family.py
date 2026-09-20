"""C4 耦合器族 II 真机冒烟：cline_coupler / branchline_2sect / lange。

循 branchline 四端口先例（scripts/smoke_branchline_real_anchor.py）：
solve_smatrix_openems 进程隔离激励轮转（#208）4 次单激励真跑 → .s4p，门 G1-G5
同源；裁判=fake 同源闭式（几何 → KJ/HJ → 偶/奇模；#154 同名同语义）：
  cline_coupler → fake_adapter._cline_coupler_sparams（真非同步相速，段首口径 1：
                  名义 10dB @f0 预期残差 S41≈−23dB/S11≈−33dB，定向性≈13dB）；
  lange         → fake_adapter._lange_sparams（四线等效理想裁判，段首口径 3）；
  branchline_2sect → fake_adapter._branchline_2sect_sparams（二分频响，段首口径 2）。

预声明门（写死不调；branchline 同门数值）：
  G1 无源性 max σ_max(S) ≤ 1.01；G2 互易 max|S−Sᵀ| ≤ 0.02；
  G3/G4 @f0=2.5GHz（TEMPLATE_META 名义）：
    3dB 族（branchline_2sect/lange）：|S21|、|S31| ∈ −3±1dB；|S11|、|S41| ≤ −15dB；
    10dB 族（cline_coupler）：|S31| ∈ −10±1dB；|S21| ∈ [−1.5, 0]dB（理想 −0.458）；
                            |S11|、|S41| ≤ −15dB（meta smoke_note 预期 −33/−23 作参照）；
  G5 β 金标准（p1 port_beta，50Ω 馈线 w_feed HJ εeff）|Δ| ≤ 2%——记录项，失守不翻转判定。
  引擎实测中心 f_c（3dB 族=||S21|−|S31|| 最小点；10dB 族=|S31| 峰）复评 G3/G4：
  f0 未过而 f_c 过 → PARTIAL 并量化偏移；f_c 落带沿（持续过/欠耦合，带内无最小点）
  记 fc_at_band_edge=True，偏移量不可辨识（lange refix 实证 +20% 系带沿夹持）。
verdict：PASS=G1+G2+G3/G4@f0；PARTIAL=G1+G2 过且 G3/G4@f_c 过；FAIL=其余。

装配归一（#250 链，refix 实证）：
  缺省网格下 50Ω HJ 馈线的引擎自算 ZL≈45.7Ω（−8.6%），CalcPort(ref=50) 伪波分解
  使装配矩阵非无源（lange/cline σmax 1.0275/1.0344 虚假越门）。--line-z0 engine（缺省）
  让 solve_smatrix_openems 按各轮探针复算 ZL 走线基→50Ω 归一（原始矩阵留
  <template>_raw.s4p），G1 评归一后矩阵、原始 σmax 同记 assembly_norm；--line-z0 none
  复现旧口径。归一对耦合度只动 ~0.1dB，G3/G4 结论不受其影响。

运行（长任务分离 #157；发射前 tasklist 查同轨）：
  python scripts/smoke_c4_coupler_family.py --template cline_coupler
产物 runs/smoke_c4/<template>/{p1..p4/, <template>.s4p, _smoke_result.json}。
--root 显式给定时末段≠模板名自动追加 <template>/ 子目录（refix 现场 lange/cline 共用
root 互相覆盖 p1..p4 与 _smoke_result.json，cline 原始探针/判读 json 丢失——守卫）。
注：openems_rotation 子进程引擎 stdout 仅内存捕获（src 禁改），本脚本 stdout 落文件。
离线复判/装配诊断：scripts/judge_c4_assembly.py（复用本文件 judge_network）。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import resolve_openems_exe
from rfauto.adapters.fake_adapter import (
    _branchline_2sect_sparams,
    _cline_coupler_sparams,
    _lange_sparams,
)
from rfauto.adapters.openems_rotation import solve_smatrix_openems
from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL
from rfauto.core.synthesis import Stackup, forward_z0

FREQ_RANGE = (2.0, 3.0)
TEMPLATES = ("cline_coupler", "branchline_2sect", "lange")
THREE_DB = {"branchline_2sect", "lange"}
# 预声明门
G1_SIGMA_MAX = 1.01
G2_RECIP_MAX = 0.02
G5_BETA_PCT = 2.0
SPLIT_3DB = (-4.0, -2.0)
COUPLE_10DB = (-11.0, -9.0)
THRU_10DB = (-1.5, 0.0)
ISO_MATCH_MAX = -15.0
IDEAL_10DB_THRU_DB = 20 * np.log10(np.sqrt(1 - 10 ** (-1.0)))   # −0.458
STACKUP_NAME = "rogers4350b_h0.508"
GATE_SPEC: dict[str, Any] = {
    "G1_sigma_max": G1_SIGMA_MAX, "G2_recip_max": G2_RECIP_MAX,
    "split_3db_db": list(SPLIT_3DB), "couple_10db_db": list(COUPLE_10DB),
    "thru_10db_db": list(THRU_10DB), "ideal_10db_thru_db": float(IDEAL_10DB_THRU_DB),
    "iso_match_max_db": ISO_MATCH_MAX, "G5_beta_pct": G5_BETA_PCT,
    "source": "smoke_branchline_real_anchor.py G1-G5 同门；10dB 族按 meta smoke_note；"
              "G1 评 line_z0 归一后矩阵（#250 链），原始 σmax 记 assembly_norm",
}


def resolve_root(root_arg: str | None, template: str) -> Path:
    """产物根目录：缺省 runs/smoke_c4/<template>；显式 root 末段≠模板名则追加子目录。"""
    if root_arg is None:
        return Path(f"runs/smoke_c4/{template}")
    root = Path(root_arg)
    return root if root.name == template else root / template


def passivity_reciprocity(s: np.ndarray) -> dict[str, float]:
    sig = np.linalg.svd(s, compute_uv=False)
    return {"sigma_max": float(np.max(sig)),
            "recip_max": float(np.max(np.abs(s - np.transpose(s, (0, 2, 1)))))}


def metrics_at(f_ghz: np.ndarray, s: np.ndarray, f_eval: float) -> dict[str, float]:
    i = int(np.argmin(np.abs(f_ghz - f_eval)))
    db = 20 * np.log10(np.abs(s[i]) + 1e-12)
    return {"f_ghz": float(f_ghz[i]), "s11_db": float(db[0, 0]),
            "s21_db": float(db[1, 0]), "s31_db": float(db[2, 0]),
            "s41_db": float(db[3, 0]),
            "phase_s31_minus_s21_deg": float(np.degrees(
                np.angle(s[i, 2, 0]) - np.angle(s[i, 1, 0])))}


def measured_center(template: str, f_ghz: np.ndarray, s: np.ndarray) -> float:
    s21 = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-12)
    s31 = 20 * np.log10(np.abs(s[:, 2, 0]) + 1e-12)
    if template in THREE_DB:
        return float(f_ghz[int(np.argmin(np.abs(s21 - s31)))])
    return float(f_ghz[int(np.argmax(s31))])


def center_plateau(template: str, f_ghz: np.ndarray, s: np.ndarray,
                   tol_db: float = 0.1) -> tuple[float, float]:
    """中心判据在其最优值 tol_db 内的频率区间 [lo, hi]（f_c 可辨识度）。

    宽带 10dB 耦合器 |S31| 峰平坦（cline refix：0.1dB 内平台 2.28–2.78GHz），argmax 位置
    随微小归一化漂移 ±10%——平台宽即 f_c 偏移量的不确定度，判读须一并报告。
    """
    s21 = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-12)
    s31 = 20 * np.log10(np.abs(s[:, 2, 0]) + 1e-12)
    if template in THREE_DB:
        crit = np.abs(s21 - s31)
        sel = crit <= crit.min() + tol_db
    else:
        sel = s31 >= s31.max() - tol_db
    return float(f_ghz[sel][0]), float(f_ghz[sel][-1])


def gates_g3g4(template: str, m: dict[str, float]) -> dict[str, dict[str, object]]:
    if template in THREE_DB:
        return {
            "s21_db": {"value": m["s21_db"], "ok": SPLIT_3DB[0] <= m["s21_db"] <= SPLIT_3DB[1]},
            "s31_db": {"value": m["s31_db"], "ok": SPLIT_3DB[0] <= m["s31_db"] <= SPLIT_3DB[1]},
            "s11_db": {"value": m["s11_db"], "ok": m["s11_db"] <= ISO_MATCH_MAX},
            "s41_db": {"value": m["s41_db"], "ok": m["s41_db"] <= ISO_MATCH_MAX},
        }
    return {
        "s31_db": {"value": m["s31_db"], "ok": COUPLE_10DB[0] <= m["s31_db"] <= COUPLE_10DB[1]},
        "s21_db": {"value": m["s21_db"], "ok": THRU_10DB[0] <= m["s21_db"] <= THRU_10DB[1]},
        "s11_db": {"value": m["s11_db"], "ok": m["s11_db"] <= ISO_MATCH_MAX},
        "s41_db": {"value": m["s41_db"], "ok": m["s41_db"] <= ISO_MATCH_MAX},
    }


def circuit_judge(template: str, f_ghz: np.ndarray, params: dict[str, float],
                  f0: float) -> np.ndarray:
    st = Stackup.from_materials_yaml(STACKUP_NAME)
    common = {"f0_ghz": f0, "er": st.epsilon_r, "h_mm": st.thickness_mm, "z_ref": 50.0}
    if template == "cline_coupler":
        return _cline_coupler_sparams(f_ghz, w_mm=params["w_mm"], gap_mm=params["gap_mm"],
                                      coupled_len_mm=params["coupled_len_mm"], **common)
    if template == "lange":
        return _lange_sparams(f_ghz, w_mm=params["w_mm"], gap_mm=params["gap_mm"],
                              finger_len_mm=params["finger_len_mm"], **common)
    return _branchline_2sect_sparams(
        f_ghz, w_main_mm=params["w_main_mm"], w_out_mm=params["w_out_mm"],
        w_mid_mm=params["w_mid_mm"], sect_len_mm=params["sect_len_mm"],
        branch_len_mm=params["branch_len_mm"], **common)


def feed_eps_hj(params: dict[str, float], f0: float) -> float:
    """50Ω 馈线 HJ εeff（G5 β 金标准参照）。"""
    stackup = Stackup.from_materials_yaml(STACKUP_NAME)
    _, eps_hj = forward_z0(params["w_feed_mm"], f0, stackup)
    return float(eps_hj)


def read_beta_pct(beta_csv: Path, f0: float, eps_hj: float) -> float:
    """p1 port_beta.csv → 带内（±4% f0）中位 β 折 εeff 对 HJ 的偏差 %；缺文件 nan。"""
    if not beta_csv.exists():
        return float("nan")
    with open(beta_csv, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    bf = np.array([float(r[0]) for r in rows])
    bb = np.array([float(r[1]) for r in rows])
    sel = (bf >= 0.96 * f0 * 1e9) & (bf <= 1.04 * f0 * 1e9)
    if not sel.any():
        return float("nan")
    eps_eng = (float(np.median(bb[sel])) * 299792458.0 / (2 * np.pi * f0 * 1e9)) ** 2
    return float((eps_eng / eps_hj - 1) * 100)


def judge_network(template: str, f_ghz: np.ndarray, s: np.ndarray,
                  params: dict[str, float], f0: float, *,
                  d_beta: float, eps_hj: float) -> dict[str, Any]:
    """纯判读（离线可复用）：G1-G5 + 裁判对照 + verdict；不含 run 元信息。"""
    pr = passivity_reciprocity(s)
    m_f0 = metrics_at(f_ghz, s, f0)
    f_c = measured_center(template, f_ghz, s)
    fc_at_edge = bool(np.isclose(f_c, f_ghz[0]) or np.isclose(f_c, f_ghz[-1]))
    m_fc = metrics_at(f_ghz, s, f_c)
    g_f0 = gates_g3g4(template, m_f0)
    g_fc = gates_g3g4(template, m_fc)

    circ = circuit_judge(template, f_ghz, params, f0)
    mc_f0 = metrics_at(f_ghz, circ, f0)
    band = (f_ghz >= 0.9 * f0) & (f_ghz <= 1.1 * f0)
    em_s31 = 20 * np.log10(np.abs(s[:, 2, 0]) + 1e-12)
    ci_s31 = 20 * np.log10(np.abs(circ[:, 2, 0]) + 1e-12)
    em_s21 = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-12)
    ci_s21 = 20 * np.log10(np.abs(circ[:, 1, 0]) + 1e-12)
    d_circ = {"max_abs_ds31_db_band": float(np.max(np.abs(em_s31[band] - ci_s31[band]))),
              "max_abs_ds21_db_band": float(np.max(np.abs(em_s21[band] - ci_s21[band]))),
              "circuit_center_ghz": measured_center(template, f_ghz, circ)}

    gates = {
        "G1_passivity_sigma_max": {"value": pr["sigma_max"], "ok": pr["sigma_max"] <= G1_SIGMA_MAX},
        "G2_reciprocity_max": {"value": pr["recip_max"], "ok": pr["recip_max"] <= G2_RECIP_MAX},
        "G3_G4_at_f0_nominal": {"f_ghz": m_f0["f_ghz"], "gates": g_f0,
                                "ok": all(v["ok"] for v in g_f0.values())},
        "G3_G4_at_fc_measured": {"f_ghz": m_fc["f_ghz"], "gates": g_fc,
                                 "ok": all(v["ok"] for v in g_fc.values())},
        "G5_beta_feed_pct_recorded": {"value": d_beta, "limit": G5_BETA_PCT, "recorded": True,
                                      "ok": bool(np.isnan(d_beta) or abs(d_beta) <= G5_BETA_PCT)},
    }
    core = gates["G1_passivity_sigma_max"]["ok"] and gates["G2_reciprocity_max"]["ok"]
    if core and gates["G3_G4_at_f0_nominal"]["ok"]:
        verdict = "PASS"
    elif core and gates["G3_G4_at_fc_measured"]["ok"]:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    fc_note = None
    if fc_at_edge:
        fc_note = ("f_c 落带沿：带内无中心可辨识点（3dB 族=||S21|−|S31|| 无最小、"
                   "10dB 族=|S31| 峰在带外），偏移量不可辨识，PARTIAL 路径不适用")
    return {
        "verdict": verdict,
        "passivity_reciprocity": pr,
        "at_f0_nominal": m_f0, "at_fc_measured": m_fc,
        "fc_shift_pct": (f_c / f0 - 1) * 100,
        "fc_at_band_edge": fc_at_edge, "fc_note": fc_note,
        "fc_plateau_ghz": list(center_plateau(template, f_ghz, s)),
        "circuit_judge_at_f0": mc_f0, "em_vs_circuit": d_circ,
        "beta_feed_pct": d_beta, "eps_hj_feed": eps_hj,
        "gates": gates, "gate_spec": dict(GATE_SPEC),
    }


def print_judge(template: str, j: dict[str, Any], f0: float) -> None:
    pr, m_f0, m_fc, mc_f0, d_circ = (j["passivity_reciprocity"], j["at_f0_nominal"],
                                     j["at_fc_measured"], j["circuit_judge_at_f0"],
                                     j["em_vs_circuit"])
    print(f"G1 σmax={pr['sigma_max']:.4f} G2 recip={pr['recip_max']:.4f} "
          f"β{j['beta_feed_pct']:+.2f}%", flush=True)
    print(f"@f0={m_f0['f_ghz']:.3f}: S11={m_f0['s11_db']:.1f} S21={m_f0['s21_db']:.2f} "
          f"S31={m_f0['s31_db']:.2f} S41={m_f0['s41_db']:.1f} Δφ(31−21)={m_f0['phase_s31_minus_s21_deg']:.1f}°"
          f"（裁判 @f0：S11={mc_f0['s11_db']:.1f} S21={mc_f0['s21_db']:.2f} S31={mc_f0['s31_db']:.2f} "
          f"S41={mc_f0['s41_db']:.1f}）", flush=True)
    edge = "（带沿夹持，不可辨识）" if j["fc_at_band_edge"] else ""
    lo, hi = j["fc_plateau_ghz"]
    print(f"@f_c={m_fc['f_ghz']:.3f}: S11={m_fc['s11_db']:.1f} S21={m_fc['s21_db']:.2f} "
          f"S31={m_fc['s31_db']:.2f} S41={m_fc['s41_db']:.1f}；偏移 {j['fc_shift_pct']:+.2f}%{edge}"
          f"（判据 0.1dB 平台 {lo:.3f}–{hi:.3f}GHz）；"
          f"EM vs 裁判带内 max|ΔS31|={d_circ['max_abs_ds31_db_band']:.2f}dB "
          f"max|ΔS21|={d_circ['max_abs_ds21_db_band']:.2f}dB", flush=True)
    print(f"C4_{template.upper()}_{j['verdict']}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True, choices=TEMPLATES)
    parser.add_argument("--root", default=None)
    parser.add_argument("--mesh", type=float, default=0.0, help="0=模板缺省自动 λ_sub/50")
    parser.add_argument("--timeout", type=float, default=7200.0)
    parser.add_argument("--line-z0", choices=("engine", "none"), default="engine",
                        help="装配归一：engine=各轮探针复算 ZL 走 #250 链（缺省）；none=旧口径")
    args = parser.parse_args(argv)

    template = args.template
    root = resolve_root(args.root, template)
    f0 = float(TEMPLATE_META[template]["f0_ghz"])
    params = {k: float(v) for k, v in TEMPLATE_NOMINAL[template].items()}
    line_z0 = None if args.line_z0 == "none" else "engine"
    print(f"[{template}] f0={f0} params={params} mesh={args.mesh} root={root} "
          f"line_z0={args.line_z0}", flush=True)

    t0 = time.time()
    rot = solve_smatrix_openems(
        root, template=template, params=params, freq_range_ghz=FREQ_RANGE,
        mesh_resolution_mm=args.mesh, n_ports=4, timeout_s=int(args.timeout),
        exe_path=resolve_openems_exe(), line_z0=line_z0)
    wall = time.time() - t0
    print(f"rotation ok={rot.get('ok')} elapsed_s={rot.get('elapsed_s')} wall={wall:.0f} "
          f"msg={rot.get('message')} errors={rot.get('errors')} "
          f"reused={rot.get('resumed_rounds')}", flush=True)
    if not rot.get("ok"):
        result = {"item": f"smoke_c4/{template}", "verdict": "FAIL",
                  "reason": f"轮转失败: {rot.get('errors')}", "solve_s": round(wall, 1)}
        root.mkdir(parents=True, exist_ok=True)
        (root / "_smoke_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"C4_{template.upper()}_FAIL", flush=True)
        return 1

    import skrf

    net = skrf.Network(str(rot["s4p_path"]))
    f_ghz = net.f / 1e9
    s = net.s
    assert s.shape[1:] == (4, 4)

    eps_hj = feed_eps_hj(params, f0)
    d_beta = read_beta_pct(root / "p1" / "port_beta.csv", f0, eps_hj)
    j = judge_network(template, f_ghz, s, params, f0, d_beta=d_beta, eps_hj=eps_hj)
    print_judge(template, j, f0)

    result = {
        "item": f"smoke_c4/{template}", "verdict": j["verdict"], "root": str(root),
        "f0_ghz": f0, "params": params, "freq_range_ghz": list(FREQ_RANGE),
        "mesh_mm": args.mesh, "solve_s": round(wall, 1),
        "rotation": {k: rot.get(k) for k in ("n_runs", "n_reused", "resumed_rounds",
                                             "elapsed_s", "message", "s4p_path")},
        "assembly_norm": rot.get("assembly_norm"),
        **{k: v for k, v in j.items() if k != "verdict"},
        "meta_smoke_note": TEMPLATE_META[template].get("smoke_note"),
    }
    (root / "_smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if j["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
