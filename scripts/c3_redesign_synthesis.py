"""c3 滤波器族电路级重设计闭环（budget_replan 路线 c，零仿真批，G4 第一腿）。

对三模板（interdigital/combline/sir_bpf）各执行（判据=runs/smoke_c3_redesign/
criteria.md，先于本脚本运行落盘）：
  a. 重综合：既有设计链 l_via_h=None（auto，Goldfarb-Pucel 闭式过孔补偿，
     口径 10 谐振条件精确解）重出名义几何；旧设计名义 = l_via_h=0.0
     （理想短路，逐字节复现补偿前口径 = 2026-09-20 真机 refix 几何）。
     #1c：全部名义值走仓内综合/HJ 精算路径，禁手算捷径（#252）。
  b. C-pass 门：重设计名义 c3_circuit_sparams(l_via_h=None) 在 2.0-3.0GHz
     频轴的 −3dB 带心（judge_refix.py:51 band_center_3db 口径，#298 禁
     argmax，只读 import）= 2.5GHz ±0.5% PASS / ±1% PARTIAL / 更宽 FAIL；
     实测带宽比 vs 设计 fbw=5% 偏差如实记录（±20% 内 PASS）。
  c. 裁判自证回收钉（#118/#340）：同名义 l_via_h=0.0 复算，过孔致带心下移
     须 ≈ 该名义下补偿量预测（预测全取设计 dict 闭式键；回收偏差 ≤10%
     相对 PASS；不复现 = 补偿模型有错，禁止进真机，如实 FAIL）。
  d. PRED_SHIFT 当轮重算（禁沿用 budget_replan 旧 −5.58/−6.64/−5.06，
     旧值只作对照列）：旧名义过孔下移 / 重设计带心回移量 / 重设计 vs f0
     预测峰移（路线 a G1 消费口）。

产物：runs/smoke_c3_redesign/{redesign_nominals.json, cpass_verdict.json}。
全程零电磁仿真（只有闭式电路裁判）；不跑 openEMS/HFSS；src/** 零改动。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUT = REPO / "runs" / "smoke_c3_redesign"
for _p in (REPO / "src", HERE, REPO / "runs" / "smoke_c3_refix"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from judge_refix import band_center_3db  # noqa: E402  只读 import（#298 带心口径单一事实源）
from rfauto.adapters.openems_templates import (  # noqa: E402
    TEMPLATE_NOMINAL,
    c3_circuit_sparams,
    c3_via_inductance_h,
    combline_design_from_order,
    interdigital_design_from_order,
    render_script,
    sir_bpf_design_from_order,
)
from rfauto.core.synthesis import Stackup  # noqa: E402
from smoke_c3_filter_family import auto_mesh_mm  # noqa: E402  只读 import（渲染 mesh 口径同源）

F0 = 2.5
FBW = 0.05
ORDER = 3
RL_DB = 20.0
ER = 3.66
F_LO, F_HI, N_PTS = 2.0, 3.0, 401
CENTER_PASS_PCT = 0.5
CENTER_PARTIAL_PCT = 1.0
BW_RATIO_TOL = 0.20
RECOVERY_REL_MAX = 0.10
OLD_FIXED_PRED_PCT = {"interdigital": -5.58, "combline": -6.64, "sir_bpf": -5.06}

DESIGNERS = {
    "interdigital": interdigital_design_from_order,
    "combline": combline_design_from_order,
    "sir_bpf": sir_bpf_design_from_order,
}
# 重综合名义几何键（渲染/judge 消费面；#1c 全部由设计链产出，无手算）
NOMINAL_KEYS = {
    "interdigital": ("order", "w_mm", "res_len_mm", "gaps_mm", "feed_len_mm"),
    "combline": ("order", "w_mm", "res_len_mm", "gaps_mm", "feed_len_mm",
                 "c_load_pf"),
    "sir_bpf": ("order", "w_feed_mm", "w_low_mm", "w_high_mm", "l_low_mm",
                "l_high_mm", "gaps_mm", "feed_len_mm"),
}
# 回收钉预测口径（该名义下补偿量：过孔 vs 理想短路的谐振频比闭式，键取设计 dict）。
# combline 勘误（2026-09-21，criteria.md 勘误节）：初版 f_ideal/f0=theta_r/theta_c
# 漏掉装载电容 ωC 色散（谐振点移动后电容电纳随 s 线性变），被回收钉当场抓出
# （实测下移 −7.3% vs 误预测 −11.8%）；精确闭式 = 解 s·cot(theta_r)=cot(theta_c·s)
# ——裁判自身 Y 函数零点（2.6975GHz）与该根、滤波带心（2.7000GHz）三方互证，
# 内核无错、错在预测推导（#118/#340"推导可能算错"实例）。
RECOVERY_PRED_BASIS = {
    "interdigital": "f_ideal/f0 = pi/(2*theta_c)（下移预测 = 2*theta_c/pi - 1）",
    "combline": "解 s*cot(theta_r)=cot(theta_c*s) 的 s（brentq，含 ωC 色散；"
                "f_ideal=s*f0，下移预测 = 1/s - 1）",
    "sir_bpf": "解 tan(theta*s)*tan(theta_c*s)=Z_lo/Z_hi 的 s（brentq，f_ideal=s*f0；"
               "下移预测 = 1/s - 1）",
}


def nominal_params(template: str, design: dict) -> dict:
    """设计 dict → 电路裁判/渲染消费的名义参数表（同键同语义，#154）。"""
    return {k: design[k] for k in NOMINAL_KEYS[template]}


def s21_db_of(template: str, f_ghz: np.ndarray, params: dict, h_mm: float,
              l_via_h: float | None) -> np.ndarray:
    s = c3_circuit_sparams(template, f_ghz, params, synchronous_tem=False,
                           f0_ghz=F0, er=ER, h_mm=h_mm, l_via_h=l_via_h)
    return 20.0 * np.log10(np.abs(s[:, 1, 0]) + 1e-12)


def recovery_pred_ratio(template: str, design: dict) -> float:
    """该（重设计）名义下补偿量闭式预测：f_via/f_ideal 比（<1，键全取设计 dict）。"""
    from scipy.optimize import brentq

    theta_c = float(design["theta_c_rad"])
    if template == "interdigital":
        return 2.0 * theta_c / math.pi
    if template == "combline":
        # 理想短路谐振（精确闭式，含 ωC 色散）：s·cot(θr)=cot(θc·s)。
        # ω0·C·Zr = cot(θr)（设计谐振条件），s=f/f0；g(1)<0、g(π/(2θc)·0.999)>0。
        tr = float(design["theta_r"])

        def _g(s: float) -> float:
            return s / math.tan(tr) - 1.0 / math.tan(theta_c * s)

        hi = 0.999 * (math.pi / 2.0) / theta_c
        return 1.0 / float(brentq(_g, 1.0 + 1e-12, hi, xtol=1e-12))
    # sir_bpf：理想短路谐振 tan(theta*s)*tan(theta_c*s) = Z_lo/Z_hi 解 s>1
    theta = float(design["theta"])
    target = float(design["z_lo_ohm"]) / float(design["z_hi_ohm"])

    def _g(s: float) -> float:
        return math.tan(theta * s) * math.tan(theta_c * s) - target

    hi = 0.999 * (math.pi / 2.0) / max(theta, theta_c)   # 首个 tan 极点前
    return 1.0 / float(brentq(_g, 1.0 + 1e-12, hi, xtol=1e-12))


def refix_run_params(template: str) -> dict | None:
    """真机 refix 几何对照（best-effort 观测性，#105：缺失不阻塞）。"""
    p = REPO / "runs" / "smoke_c3_refix" / template / "_smoke_result.json"
    try:
        return (json.loads(p.read_text(encoding="utf-8")) or {}).get("params")
    except Exception:
        return None


# ── R2 出处纪律（防 no-op 复发/陈旧档误读，criteria.md §四）─────────

def render_input_sha256(template: str, params: dict, mesh_mm: float | None = None
                        ) -> str:
    """渲染输入指纹：render_script(名义) 产物 sha256（自描述出处，写进
    redesign_nominals.json——run 几何出处以渲染字面量为准，SC 主根因教训）。"""
    mesh = float(mesh_mm) if mesh_mm is not None else auto_mesh_mm(template, params)
    text = render_script(template, dict(params), (F_LO, F_HI),
                         mesh_resolution_mm=mesh)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _geometry_section(text: str, template: str) -> str | None:
    """渲染文本的几何段（`<tpl> = CSX.AddMetal(` 起至末个 SetPriority(10) 止；
    频轴/mesh 无关——跨 run 字面量比对的稳定粒度）。

    标记缺失（畸形/异模板归档）返回 None——调用方如实记 not-ok，不让
    StopIteration 裸穿透炸整跑（E-M2，#105 观测面故障不阻塞主路径）。
    """
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines)
              if f"{template} = CSX.AddMetal(" in ln]
    ends = [i for i, ln in enumerate(lines) if "SetPriority(10)" in ln]
    if not starts or not ends or max(ends) < starts[0]:
        return None
    return "\n".join(lines[starts[0]:max(ends) + 1]) + "\n"


def crosscheck_run_literal(template: str, params: dict,
                           simulation_py: str | Path) -> dict:
    """归档 run 的 simulation.py 几何段 vs 现渲染（同名义）逐字节比对。

    R2：SC 主根因 (a') 的复发守卫——归档 run 的几何出处以渲染字面量为裁决
    （不认 metadata 自述）；不一致=该 run 渲染的不是本名义。缺失档案与
    存在但畸形（几何段标记缺失）的档案均如实 ok=False（不臆造，#122；
    畸形含归档路径与描述由调用方决策，E-M2）。
    """
    p = Path(simulation_py)
    if not p.exists():
        return {"ok": False, "checked": False,
                "reasons": [f"归档 simulation.py 不存在：{p}"]}
    mesh = auto_mesh_mm(template, params)
    fresh = render_script(template, dict(params), (F_LO, F_HI),
                          mesh_resolution_mm=mesh)
    fresh_section = _geometry_section(fresh, template)
    if fresh_section is None:  # 本仓渲染器产物缺标记=内部不变量破坏，fail-closed
        raise RuntimeError(
            f"现渲染文本缺几何段标记（renderer 内部错误，模板={template}）")
    want = fresh_section.splitlines()
    got_text = _geometry_section(
        p.read_text(encoding="utf-8", errors="replace"), template)
    if got_text is None:
        return {"ok": False, "checked": False,
                "reasons": [f"归档 simulation.py 畸形（几何段标记缺失：无 "
                            f"'{template} = CSX.AddMetal(' 起始或无 "
                            f"'SetPriority(10)' 终止）：{p}"]}

    got = got_text.splitlines()
    if want == got:
        return {"ok": True, "checked": True, "n_lines": len(want),
                "reasons": []}
    diffs = [i for i, (a, b) in enumerate(zip(want, got, strict=False))
             if a != b]
    len_diff = abs(len(want) - len(got))
    reasons = [f"几何段差异 {len(diffs)} 行（长度差 {len_diff}），前 3 条："]
    for i in diffs[:3]:
        reasons.append(f"  L{i} 期望: {want[i].strip()[:88] if i < len(want) else '<缺>'}")
        reasons.append(f"  L{i} 归档: {got[i].strip()[:88] if i < len(got) else '<缺>'}")
    return {"ok": False, "checked": True, "n_diff_lines": len(diffs),
            "reasons": reasons}


def registration_freshness(file_ts: float | None,
                           nominal_commit_ts: float | None) -> bool | None:
    """陈旧档守卫：归档 run 文件 mtime ≥ 名义注册 commit 时戳（SC 误读
    _smoke_result 09-18 旧档实例）。任一时戳缺失 → None（不可判，不阻塞）。"""
    if file_ts is None or nominal_commit_ts is None:
        return None
    return float(file_ts) >= float(nominal_commit_ts)


def _refix_crosscheck(template: str, params: dict) -> dict:
    """refix 归档 run 的出处三面（best-effort #105）：
    params=历史 metadata 自述（只对照）；literal=渲染字面量裁决（R2 主判）；
    freshness=归档文件 mtime vs 名义注册 commit（陈旧档守卫）。"""
    out: dict = {"params": refix_run_params(template)}
    sim = REPO / "runs" / "smoke_c3_refix" / template / "simulation.py"
    out["literal_crosscheck"] = crosscheck_run_literal(template, params, sim)
    try:
        file_ts = sim.stat().st_mtime if sim.exists() else None
    except Exception:
        file_ts = None
    out["registration_freshness"] = registration_freshness(file_ts,
                                                            nominal_commit_ts())
    out["note"] = ("几何出处以渲染字面量裁决（R2）；metadata 自述仅对照。"
                   "freshness=None=时戳缺失不可判（不阻塞）")
    return out


def nominal_commit_ts() -> float | None:
    """名义注册 commit 时戳（openems_templates.py 末次 commit，best-effort
    观测性 #105；runs/ 内调用零 git 依赖由调用方 try 兜底）。"""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--",
             "src/rfauto/adapters/openems_templates.py"],
            cwd=str(REPO), capture_output=True, text=True, timeout=30)
        txt = (out.stdout or "").strip()
        return float(txt) if out.returncode == 0 and txt else None
    except Exception:
        return None


def run_template(template: str, f: np.ndarray, h_mm: float) -> tuple[dict, dict]:
    designer = DESIGNERS[template]
    d_old = designer(ORDER, F0, FBW, RL_DB, er=ER, h_mm=h_mm, l_via_h=0.0)
    d_new = designer(ORDER, F0, FBW, RL_DB, er=ER, h_mm=h_mm, l_via_h=None)
    p_old, p_new = nominal_params(template, d_old), nominal_params(template, d_new)

    # 每键新旧值（对照）
    per_key: dict[str, dict] = {}
    for k in NOMINAL_KEYS[template]:
        o, n = p_old[k], p_new[k]
        if isinstance(o, list):
            per_key[k] = {"old": o, "new": n,
                          "delta": [round(b - a, 6) for a, b in zip(o, n, strict=True)]}
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            per_key[k] = {"old": o, "new": n, "delta": round(n - o, 6)}
        else:
            per_key[k] = {"old": o, "new": n}
    # 重设计名义 4 位舍入 vs 仓内 TEMPLATE_NOMINAL（只记录，不一致=机制面缺口）
    reg = TEMPLATE_NOMINAL[template]
    nom_checks = {}
    for k in NOMINAL_KEYS[template]:
        n, r = p_new[k], reg.get(k)
        if isinstance(n, list):
            nom_checks[k] = [round(v, 4) for v in n] == list(r)
        elif isinstance(n, float):
            nom_checks[k] = round(n, 4) == r
        else:
            nom_checks[k] = n == r
    matches_registered = all(nom_checks.values())

    # 四个带心（同频轴）：新/旧名义 × 过孔 auto/理想短路 0.0
    bc = {}
    for tag, params, lv in (("new_auto", p_new, None), ("new_ideal", p_new, 0.0),
                            ("old_auto", p_old, None), ("old_ideal", p_old, 0.0)):
        s_db = s21_db_of(template, f, params, h_mm, lv)
        bc[tag] = band_center_3db(f, s_db)
    # 无源性健全性（只记录）：重设计名义 + 过孔口径
    s_new = c3_circuit_sparams(template, f, p_new, synchronous_tem=False,
                               f0_ghz=F0, er=ER, h_mm=h_mm, l_via_h=None)
    power_max = float((np.abs(s_new[:, 0, 0]) ** 2 + np.abs(s_new[:, 1, 0]) ** 2).max())

    # b. C-pass 带心门
    fc_new = bc["new_auto"]["f_center_3db_ghz"]
    dev_pct = (fc_new / F0 - 1.0) * 100.0
    if abs(dev_pct) <= CENTER_PASS_PCT:
        cpass = "PASS"
    elif abs(dev_pct) <= CENTER_PARTIAL_PCT:
        cpass = "PARTIAL"
    else:
        cpass = "FAIL"
    bw_ratio = bc["new_auto"]["bw_3db_pct"] / (FBW * 100.0)
    bw_ok = abs(bw_ratio - 1.0) <= BW_RATIO_TOL

    # c. 回收钉：该名义下过孔致带心下移，实测 vs 闭式预测
    pred_ratio = recovery_pred_ratio(template, d_new)
    pred_shift_pct = (pred_ratio - 1.0) * 100.0
    meas_shift_pct = (bc["new_auto"]["f_center_3db_ghz"]
                      / bc["new_ideal"]["f_center_3db_ghz"] - 1.0) * 100.0
    rec_dev = abs(meas_shift_pct - pred_shift_pct) / abs(pred_shift_pct)
    rec_ok = rec_dev <= RECOVERY_REL_MAX

    # d. PRED_SHIFT 当轮重算
    pred_via_old_pct = (bc["old_auto"]["f_center_3db_ghz"]
                        / bc["old_ideal"]["f_center_3db_ghz"] - 1.0) * 100.0
    pred_lift_pct = (bc["new_auto"]["f_center_3db_ghz"]
                     / bc["old_auto"]["f_center_3db_ghz"] - 1.0) * 100.0

    # verdict（criteria.md 门 5）
    verdict = "PASS"
    reasons: list[str] = []
    if not rec_ok:
        verdict = "FAIL"
        reasons.append("回收钉不复现（补偿模型有错，禁止进真机）")
    if cpass == "FAIL":
        verdict = "FAIL"
        reasons.append("C-pass 带心越 ±1%")
    if verdict != "FAIL" and (cpass == "PARTIAL" or not bw_ok):
        verdict = "PARTIAL"
        if cpass == "PARTIAL":
            reasons.append("C-pass 带心越 ±0.5%（±1% 内）")
        if not bw_ok:
            reasons.append("带宽比越 1±20%")

    nominal_block = {
        "old_nominal": p_old, "new_nominal": p_new,
        "per_key_old_new": per_key,
        "via_compensation_new": {k: d_new[k] for k in
                                 ("l_via_h", "theta_c_rad", "via_delta_mm")},
        "matches_registered_nominal": matches_registered,
        "nominal_4dp_checks": nom_checks,
        # R2 出处纪律：渲染输入指纹 + 归档 refix run 字面量/陈旧档 crosscheck
        # （best-effort #105：缺失不阻塞，防 no-op 复发与陈旧 metadata 误读）
        "render_input_sha256": render_input_sha256(template, p_new),
        "refix_run_geometry_crosscheck": dict(
            _refix_crosscheck(template, p_new)),
        "notes_new": list(d_new["notes"]),
    }
    verdict_block = {
        "C_pass": {"status": cpass,
                   "band_center_ghz": fc_new,
                   "dev_vs_f0_pct": dev_pct,
                   "thresholds_pct": [CENTER_PASS_PCT, CENTER_PARTIAL_PCT],
                   "bw_3db_pct": bc["new_auto"]["bw_3db_pct"],
                   "bw_ratio_vs_design_fbw": bw_ratio,
                   "bw_ratio_tol": BW_RATIO_TOL,
                   "bw_ok": bw_ok,
                   "touches_sweep_edge": bc["new_auto"]["touches_sweep_edge"],
                   "peak_db": bc["new_auto"]["peak_db"],
                   "passivity_power_sum_max": power_max},
        "recovery_pin": {"ok": rec_ok,
                         "pred_basis": RECOVERY_PRED_BASIS[template],
                         "pred_f_via_over_f_ideal": pred_ratio,
                         "pred_f_ideal_ghz": bc["new_auto"]["f_center_3db_ghz"]
                                             / pred_ratio,
                         "predicted_downshift_pct": pred_shift_pct,
                         "measured_downshift_pct": meas_shift_pct,
                         "recovery_dev_rel": rec_dev,
                         "threshold_rel": RECOVERY_REL_MAX},
        "pred_shift": {"pred_via_shift_old_pct": pred_via_old_pct,
                       "old_fixed_reference_pct": OLD_FIXED_PRED_PCT[template],
                       "old_fixed_vs_recomputed_pt": pred_via_old_pct
                                                     - OLD_FIXED_PRED_PCT[template],
                       "pred_lift_redesign_pct": pred_lift_pct,
                       "pred_shift_new_vs_f0_pct": dev_pct,
                       "band_centers_ghz": {
                           t: bc[t]["f_center_3db_ghz"] for t in bc},
                       "bw_3db_pct": {t: bc[t]["bw_3db_pct"] for t in bc}},
        "verdict": verdict, "reasons": reasons,
    }
    return nominal_block, verdict_block


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(OUT), help="产物根目录")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    h_mm = float(Stackup.from_materials_yaml("rogers4350b_h0.508").thickness_mm)
    l_via_nh = c3_via_inductance_h(h_mm) * 1e9
    f = np.linspace(F_LO, F_HI, N_PTS)
    print(f"[c3-redesign] 零仿真电路级闭环：h_mm={h_mm} l_via(auto)={l_via_nh:.5f}nH "
          f"axis={F_LO}-{F_HI}GHz/{N_PTS}pts 判据={out / 'criteria.md'}")

    nominals: dict[str, dict] = {}
    verdicts: dict[str, dict] = {}
    for tpl in DESIGNERS:
        nb, vb = run_template(tpl, f, h_mm)
        nominals[tpl], verdicts[tpl] = nb, vb
        cp, rp, ps = vb["C_pass"], vb["recovery_pin"], vb["pred_shift"]
        print(f"[{tpl}] verdict={vb['verdict']} | C-pass {cp['status']}: 带心 "
              f"{cp['band_center_ghz']:.4f}GHz ({cp['dev_vs_f0_pct']:+.3f}%) 带宽 "
              f"{cp['bw_3db_pct']:.2f}% (ratio {cp['bw_ratio_vs_design_fbw']:.3f}"
              f"{'' if cp['bw_ok'] else ' OOB'}) | 回收钉 "
              f"{'ok' if rp['ok'] else 'FAIL'}: 实测下移 {rp['measured_downshift_pct']:+.3f}% "
              f"vs 预测 {rp['predicted_downshift_pct']:+.3f}% (dev "
              f"{rp['recovery_dev_rel'] * 100:.2f}%rel) | PRED_SHIFT: 旧名义过孔下移 "
              f"{ps['pred_via_shift_old_pct']:+.2f}% (旧固定值 "
              f"{ps['old_fixed_reference_pct']:+.2f}, 差 "
              f"{ps['old_fixed_vs_recomputed_pt']:+.2f}pt) 重设计回移 "
              f"{ps['pred_lift_redesign_pct']:+.2f}% | NOMINAL 一致 "
              f"{nb['matches_registered_nominal']}")

    statuses = [v["verdict"] for v in verdicts.values()]
    overall = ("PASS" if all(s == "PASS" for s in statuses)
               else "FAIL" if "FAIL" in statuses else "PARTIAL")

    nom_doc = {"batch": "smoke_c3_redesign", "route": "c 电路级重设计闭环（零仿真）",
               "criteria": "runs/smoke_c3_redesign/criteria.md",
               "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "design_basis": {
                   "via_model": "Goldfarb-Pucel 1991（openems_templates §C3 口径 8/10）",
                   "synthesis": "仓内设计链 *_design_from_order + skrf HJ（#1c，禁手算 #252）",
                   "old_nominal_def": "设计链 l_via_h=0.0（理想短路，逐字节复现补偿前口径"
                                      " = 2026-09-20 真机 refix 几何）",
                   "new_nominal_def": "设计链 l_via_h=None（auto 几何值，谐振条件精确解补偿）"},
               "h_mm": h_mm, "l_via_auto_nh": l_via_nh,
               "f0_ghz": F0, "fbw": FBW, "order": ORDER, "rl_db": RL_DB, "er": ER,
               "freq_axis_ghz": [F_LO, F_HI, N_PTS],
               "templates": nominals}
    (out / "redesign_nominals.json").write_text(
        json.dumps(nom_doc, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")

    ver_doc = {"batch": "smoke_c3_redesign",
               "criteria": "runs/smoke_c3_redesign/criteria.md",
               "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "thresholds": {"center_pass_pct": CENTER_PASS_PCT,
                              "center_partial_pct": CENTER_PARTIAL_PCT,
                              "bw_ratio_tol": BW_RATIO_TOL,
                              "recovery_rel_max": RECOVERY_REL_MAX},
               "band_center_source": "judge_refix.py:51 band_center_3db（只读 import，"
                                     "#298 禁 argmax）",
               "templates": verdicts, "overall": overall,
               "wall_s": round(time.time() - t0, 1),
               "em_simulations": 0}
    (out / "cpass_verdict.json").write_text(
        json.dumps(ver_doc, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    print(f"[c3-redesign] overall={overall} 产物=redesign_nominals.json "
          f"cpass_verdict.json（{ver_doc['wall_s']}s，零电磁仿真）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
