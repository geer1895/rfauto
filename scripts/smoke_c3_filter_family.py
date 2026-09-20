"""C3 滤波器族 II 真机冒烟：interdigital / combline / sir_bpf。

循 coupled_bpf 先例（scripts/coupled_bpf_smoke.py 五门 + scripts/
smoke_coupled_bpf_nrts.py NrTS 加长与终止诊断）：三模板皆 fbw=5% 窄带高 Q，
NrTS=100000 官方口径会截断于激励脉冲进行中（pt1 探针实证），本脚本脚本级改写
NrTS→--nrts（默认 1000000，followUp 收口）并解析引擎日志给终止
诊断。零源码改动。

三处收紧（c3 PARTIAL 归因三项由假设级落地）：
- 网格：--mesh 0 不再是 λ_sub/50 缺省（NEAR 0.285mm > 外缝 0.139~0.242mm ⇒
  缝内零内部线），而是取 c3_mesh_max_mm（NEAR ≤ 缝_min/3，#266 渲染守卫上限）
  向下取整到 µm；显式 --mesh 越界由 render_script 抛错（不许静默粗网格）。
- 收敛判读门（nrts_converged）：引擎触 NrTS 上限而能量未达 EndCriteria
  （openEMS 缺省 1e-6=−60dB；旧轮 400k 触顶能量仅 −46/−29dB）= 未收敛 →
  verdict FAIL 不采信（其余门照算只作记录）。--end-criteria 可显式改写。
- 裁判补过孔电感项：peak_vs_circuit 门的电路参照 = c3_circuit_sparams(
  l_via_h=None)（Goldfarb-Pucel 1991 闭式，h=基板厚、d=2×0.15mm）；理想短路
  旧参照另记 circuit_ideal_short_peak_ghz 与预测下移 via_predicted_shift_pct。

裁判（独立来源）：
- 主裁 = c3_circuit_sparams(template, synchronous_tem=False, l_via_h=None)：几何
  KJ 回代的并联谐振 J 倒置器链 + 过孔电感端接（fake 同源通道的物理化口径，
  #154 同索引同语义）；
- 参照 = C13 coupling_matrix_response（理想切比雪夫）。

预声明门（与 coupled_bpf 完全同口径，写死不调）：
  il_min_db ∈ [−3.0, −0.2]、ripple_db ≤ 4.0、rl_band_max_db ≤ −8.0、
  峰位 vs 电路 ≤ 5%、β 馈线 ±3%（MSLPort port1，50Ω 馈段）、
  无源性 |S11|max ≤ 0 / |S21|max ≤ 0 / max(|S11|²+|S21|²) ≤ 1.02、
  激励覆盖（实际步数 ≥ 激励脉冲长度）、收敛（未触 NrTS 顶或能量 ≤ EndCriteria）。
verdict：PASS=全过；PARTIAL=无源性+激励覆盖+收敛过而五门有失；FAIL=其余
（未收敛一律 FAIL）。--q-extrap：增「Q 外推
置信门」选项——能量未达判据/无 sparams.csv 时从探针时间序列提取谐振 Q 并外推
稳态 S（内核 scripts/c3_resonance_q_extract.py），外推稳态与截断态偏差 ≤
Q_EXTRAP_DEV_DB_MAX(0.5dB) 且 holdout ≤ 5% 且 span ≥ 20dB（三面写死）则端口 S
判稳态可读，可替代能量收敛判据参与 verdict（使 c3 族合规复跑 ~4h 量级出可信
结论 vs −60dB 判据 ~10h；2h 处模型预测偏差 ~2dB，门如实判红不许提前停）。
c3 归档 107.6ns 实证：外推 S21 峰 −5.77dB vs 截断 −5.81dB（dev 0.04dB）、
holdout 0.03%、T_req(带心±5%)=52ns。

运行（>10min，Start-Process 分离 + 日志轮询 #157；发射前查 python 命令行含
_rfauto_runner/simulation.py 的同轨进程 #261）：
  python scripts/smoke_c3_filter_family.py --template interdigital
  python scripts/smoke_c3_filter_family.py --template combline --probe   # NrTS=10 探针
  python scripts/smoke_c3_filter_family.py --template sir_bpf --root runs/smoke_c3_refix
证据链 <root>/<template>/{simulation.py,engine.log,sparams.csv,
port_beta.csv,_smoke_result.json}（--root 缺省 runs/smoke_c3；合规网格复跑
落 runs/smoke_c3_refix，旧轮产物不覆盖）。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

from c3_resonance_q_extract import (
    extract_ring_modes,
    load_msl_probes,
    q_extrap_confidence,
    q_extrap_report,
    sparams_windows,
)
from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.openems_templates import (
    TEMPLATE_NOMINAL,
    c3_circuit_sparams,
    c3_mesh_max_mm,
    c3_via_inductance_h,
    combline_design_from_order,
    interdigital_design_from_order,
    sir_bpf_design_from_order,
)
from rfauto.core.calculators import coupling_matrix_response
from rfauto.core.synthesis import Stackup, forward_z0
from smoke_coupled_bpf_nrts import (
    NRTS_OLD,
    _run_engine,
    parse_engine_log,
    read_csv_cols,
    rewrite_nrts,
)

F0 = 2.5
FBW = 0.05
RL_DB = 20.0
ORDER = 3
DESIGNERS = {
    "interdigital": interdigital_design_from_order,
    "combline": combline_design_from_order,
    "sir_bpf": sir_bpf_design_from_order,
}
FEED_WIDTH_KEY = {"interdigital": "w_mm", "combline": "w_mm", "sir_bpf": "w_feed_mm"}

# 预声明门（coupled_bpf 同口径）
GATE_IL_RANGE = (-3.0, -0.2)
GATE_RIPPLE_MAX = 4.0
GATE_RL_MAX = -8.0
GATE_PEAK_PCT = 5.0
GATE_BETA_PCT = 3.0
GATE_POWER_SUM = 1.02
# openEMS 缺省 EndCriteria=1e-6（能量衰减 10·lg=−60dB；引擎告警行实录
# "before the end-criteria of -60dB"）——日志无显式判据行时按此判读
DEFAULT_END_CRITERIA_DB = -60.0
NRTS_DEFAULT = 1000000
# Q 外推置信门（谐振 Q 时域提取替代端口 S 全响应收敛判据）。
# 预声明写死，依据：
# - dev 0.5dB = 5.7% 线性：低于既有判读粒度（ripple 门 4dB、IL 区间宽 2.8dB、
#   RL 门在 −8dB），0.1dB 量级扰动不翻转任何既有门结论（#298 峰位 argmax 歧义带
#   内幅值读数稳定性同量级）；
# - holdout 5%：窗阶梯前 K−3 窗拟合预测末窗的独立检验（不参与拟合的数据面），
#   5%≈0.42dB 与 dev 门同量级；c3 归档实测 1.2%（S21 峰）/0.06%（S11 带心）；
# - span 20dB：环振包络 ln 线性回归的 α 可辨识硬地板（归档实测 ~59dB）。
# 三面齐过 → 未达 −60dB 能量判据也可提前判读（verdict 按 PARTIAL/PASS 走），
# 任一不过 → 如实 FAIL_NOT_CONFIDENT（不凑绿）。
Q_EXTRAP_DEV_DB_MAX = 0.5
Q_EXTRAP_HOLDOUT_REL_MAX = 0.05
Q_EXTRAP_SPAN_DB_MIN = 20.0


def auto_mesh_mm(template: str, params: dict[str, object]) -> float:
    """--mesh 0 的合规缺省：c3_mesh_max_mm（NEAR ≤ 缝_min/3）向下取整到 µm。"""
    return math.floor(c3_mesh_max_mm(template, dict(params)) * 1000.0) / 1000.0


def nrts_convergence(eng: dict[str, object]) -> dict[str, object]:
    """NrTS/EndCriteria 收敛判读（纯函数，离线可测）。

    规则：① 引擎告警"Max. number of timesteps was reached before the
    end-criteria"→ 未收敛；② 触 NrTS 上限（iterations_done ≥ nrts）且日志能量
    最低值 > 判据 → 未收敛；③ 未触顶（按 EndCriteria 提前停机）→ 收敛；④ 终止
    信息缺失（无 iterations_done/nrts）→ 不可证明收敛，按未收敛处置（不采信）。
    能量判据取日志显式 end_criteria_db，缺省 −60dB（openEMS EndCriteria=1e-6）。
    """
    crit_raw = eng.get("end_criteria_db")
    crit = float(crit_raw) if crit_raw is not None else DEFAULT_END_CRITERIA_DB
    e_min = eng.get("min_energy_db")
    e_min_f = float(e_min) if e_min is not None else None
    hit = eng.get("hit_nrts_limit")
    warn = bool(eng.get("nrts_limit_warning", False))
    done = eng.get("iterations_done")
    if warn:
        ok, reason = False, "引擎告警：触 NrTS 上限时能量未达 EndCriteria"
    elif hit is None and done is None:
        ok, reason = False, "终止信息缺失（无 iterations_done/nrts），无法证明收敛"
    elif bool(hit):
        ok = e_min_f is not None and e_min_f <= crit
        reason = ("触 NrTS 上限但能量已达判据" if ok
                  else f"触 NrTS 上限且能量 {e_min_f} dB 未达 {crit} dB")
    else:
        ok, reason = True, "按 EndCriteria 提前停机（未触 NrTS 上限）"
    return {"converged": bool(ok), "reason": reason, "end_criteria_db": crit,
            "min_energy_db": e_min_f, "hit_nrts_limit": hit,
            "nrts_limit_warning": warn, "iterations_done": done,
            "nrts": eng.get("nrts")}


def q_extrapolation_gate(rep: dict[str, object]) -> dict[str, object]:
    """Q 外推置信门（纯判读，阈值 Q_EXTRAP_* 预声明；内核=c3_resonance_q_extract）。

    rep 为内核 q_extrap_report 的报告 dict；构建失败形态 {"error": ...} 一律判
    不过（如实不凑绿）。value=外推 vs 截断的 S21 峰偏差 dB（与其他门同为 float）。
    """
    conf = q_extrap_confidence(rep, Q_EXTRAP_DEV_DB_MAX, Q_EXTRAP_HOLDOUT_REL_MAX,
                               Q_EXTRAP_SPAN_DB_MIN)
    keys = rep.get("keys") if isinstance(rep.get("keys"), dict) else {}
    pk = keys.get("s21_peak", {}) if isinstance(keys, dict) else {}
    value = float(pk.get("dev_db", float("nan")))
    reasons = list(conf.get("reasons", []))
    ok = bool(conf.get("ok", False))
    checks = conf.get("checks", {})
    if ok:
        reason = (f"Q 外推稳态可读（能量判据外的 S 可读性判据）：dev(S21峰)="
                  f"{value:+.3f}dB ≤ 门 {Q_EXTRAP_DEV_DB_MAX}dB，holdout ≤ "
                  f"{Q_EXTRAP_HOLDOUT_REL_MAX}，span ≥ {Q_EXTRAP_SPAN_DB_MIN}dB")
    else:
        reason = "；".join(str(r) for r in reasons) or "Q 外推报告不可判读"
    return {"value": value, "ok": ok, "reason": reason,
            "checks": checks, "modes": rep.get("modes"), "keys": keys,
            "thresholds": {"dev_db_max": Q_EXTRAP_DEV_DB_MAX,
                           "holdout_rel_max": Q_EXTRAP_HOLDOUT_REL_MAX,
                           "span_db_min": Q_EXTRAP_SPAN_DB_MIN}}


def q_extrap_report_from_probes(fdtd_dir: str, freq_hz: np.ndarray,
                                t_excite_s: float, f_design_hz: float,
                                n_windows: int = 12, z0: float = 50.0,
                                n_modes: int = 3, tol_rel: float = 0.05,
                                ) -> dict[str, object]:
    """探针目录 → Q 外推报告（薄壳；异常转 {"error": ...} 形态，判读如实不过）。"""
    try:
        probes_all = load_msl_probes(fdtd_dir)
        t = probes_all[1][0]
        probes = {k: (u, i) for k, (_tt, u, i) in probes_all.items()}
        modes = extract_ring_modes(t, probes_all[1][1], float(freq_hz[0]),
                                   float(freq_hz[-1]), t_excite_s, n_modes=n_modes)
        rep = q_extrap_report(t, probes, freq_hz, modes, t_excite_s,
                              f_design_hz=f_design_hz, n_windows=n_windows,
                              z0=z0, tol_rel=tol_rel)
        rep["fdtd_dir"] = str(fdtd_dir)
        return rep
    except Exception as exc:                       # 判读输入缺失/形态坏：如实可判不过
        return {"error": f"{type(exc).__name__}: {exc}"}


def q_extrap_truncated_s(fdtd_dir: str, freq_hz: np.ndarray, z0: float = 50.0,
                         ) -> tuple[float, np.ndarray, np.ndarray]:
    """探针目录 → 截断态 (t_end_s, S11, S21)（内核引擎同口径部分 DFT，离线判读用）。"""
    probes_all = load_msl_probes(fdtd_dir)
    t = probes_all[1][0]
    probes = {k: (u, i) for k, (_tt, u, i) in probes_all.items()}
    sw = sparams_windows(t, probes, freq_hz, [None], z0=z0)
    return float(t[-1]), sw["s11"][0], sw["s21"][0]


def _probe_dir(work: Path) -> Path | None:
    """探针目录解析：正常轮 fdtd/（引擎增量落盘）或 kill 后归档 fdtd_partial/。"""
    for cand in (work / "fdtd", work / "fdtd_partial"):
        if (cand / "port_ut_1B").exists():
            return cand
    return None


def _q_extrap_for(work: Path, eng: dict[str, object],
                  args: argparse.Namespace) -> dict[str, object] | None:
    """--q-extrap 开：从探针目录构建 Q 外推报告；输入缺失返回 {"error": ...}
    （判读如实不过），未开返回 None（judge 零行为变化）。"""
    if not getattr(args, "q_extrap", False):
        return None
    t_exc = eng.get("excitation_s")
    if t_exc is None:
        return {"error": "engine log 无 excitation_s（t_excite 只认日志，不从数据猜）"}
    pdir = _probe_dir(work)
    if pdir is None:
        return {"error": f"无探针文件（{work} 下缺 port_ut_1B）"}
    freq = np.linspace(args.flo * 1e9, args.fhi * 1e9, 401)
    return q_extrap_report_from_probes(str(pdir), freq, float(t_exc), F0 * 1e9)


def judge(f_ghz: np.ndarray, s11: np.ndarray, s21: np.ndarray,
          circ_s21_db: np.ndarray, d_feed: float, eng: dict[str, object],
          q_extrap: dict[str, object] | None = None,
          ) -> tuple[dict[str, dict[str, object]], str, dict[str, float]]:
    """五门 + 无源性 + 激励覆盖 + 收敛判读（纯 numpy，离线可测）。

    q_extrap（可选，缺省 None=零行为变化）：内核 Q 外推报告 → 增门
    q_extrap_confident；该门过=端口 S 已稳态可读，可替代能量收敛判据参与
    verdict（未达 −60dB 的截断轮提前判读）。
    """
    s11_db = 20 * np.log10(np.abs(s11) + 1e-12)
    s21_db = 20 * np.log10(np.abs(s21) + 1e-12)
    band = (f_ghz >= F0 * (1 - FBW / 2)) & (f_ghz <= F0 * (1 + FBW / 2))
    i_peak = int(np.argmax(s21_db))
    f_peak = float(f_ghz[i_peak])
    il_min = float(s21_db[band].min())
    ripple = float(s21_db[band].max() - s21_db[band].min())
    s11_band = float(s11_db[band].max())
    circ_peak = float(f_ghz[int(np.argmax(circ_s21_db))])
    peak_pct = abs(f_peak - circ_peak) / circ_peak * 100
    power = np.abs(s11) ** 2 + np.abs(s21) ** 2
    d_em_circ = float(np.max(np.abs(s21_db[band] - circ_s21_db[band])))
    conv = nrts_convergence(eng)
    gates = {
        "il_min_db": {"value": il_min,
                      "ok": GATE_IL_RANGE[0] <= il_min <= GATE_IL_RANGE[1]},
        "ripple_db": {"value": ripple, "ok": ripple <= GATE_RIPPLE_MAX},
        "rl_band_max_db": {"value": s11_band, "ok": s11_band <= GATE_RL_MAX},
        "peak_vs_circuit_pct": {"value": peak_pct, "ok": peak_pct <= GATE_PEAK_PCT},
        "beta_feed_pct": {"value": d_feed,
                          "ok": bool(np.isnan(d_feed) or abs(d_feed) <= GATE_BETA_PCT)},
        "passive_s11_max_db": {"value": float(s11_db.max()),
                               "ok": float(s11_db.max()) <= 0.0},
        "passive_s21_max_db": {"value": float(s21_db.max()),
                               "ok": float(s21_db.max()) <= 0.0},
        "power_sum_max": {"value": float(power.max()),
                          "ok": float(power.max()) <= GATE_POWER_SUM},
        "excitation_covered": {"value": eng.get("excitation_covered"),
                               "ok": bool(eng.get("excitation_covered", False))},
        "nrts_converged": {"value": conv["min_energy_db"], "ok": conv["converged"],
                           "reason": conv["reason"],
                           "end_criteria_db": conv["end_criteria_db"]},
    }
    q_ok = False
    if q_extrap is not None:
        gates["q_extrap_confident"] = q_extrapolation_gate(q_extrap)
        q_ok = bool(gates["q_extrap_confident"]["ok"])
    five_ok = all(gates[k]["ok"] for k in
                  ("il_min_db", "ripple_db", "rl_band_max_db",
                   "peak_vs_circuit_pct", "beta_feed_pct"))
    passive_ok = all(gates[k]["ok"] for k in
                     ("passive_s11_max_db", "passive_s21_max_db", "power_sum_max"))
    exc_ok = gates["excitation_covered"]["ok"]
    conv_ok = gates["nrts_converged"]["ok"] or q_ok
    if five_ok and passive_ok and exc_ok and conv_ok:
        verdict = "PASS"
    elif passive_ok and exc_ok and conv_ok:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    i_mid = int(np.argmin(np.abs(f_ghz - F0)))
    metrics = {"f_peak_ghz": f_peak, "circuit_peak_ghz": circ_peak,
               "il_min_db": il_min, "ripple_db": ripple, "rl_band_max_db": s11_band,
               "beta_feed_pct": d_feed, "em_vs_circuit_max_ds21_db": d_em_circ,
               "s21_at_f0_db": float(s21_db[i_mid]), "s11_at_f0_db": float(s11_db[i_mid]),
               "circuit_s21_at_f0_db": float(circ_s21_db[i_mid])}
    return gates, verdict, metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True, choices=sorted(DESIGNERS))
    parser.add_argument("--pt", default=None, help="工作目录名（默认=模板名）")
    parser.add_argument("--nrts", type=int, default=NRTS_DEFAULT)
    parser.add_argument("--end-criteria", type=float, default=None,
                        help="显式 EndCriteria（缺省不加=引擎默认 1e-6=−60dB）")
    parser.add_argument("--probe", action="store_true",
                        help="NrTS=10 探针：只取引擎头部（网格/dt/激励长度），不判读")
    parser.add_argument("--q-extrap", action="store_true",
                        help="Q 外推置信门：能量未达判据/无 sparams.csv 时，从探针时间"
                             "序列提取谐振 Q 并外推稳态 S，偏差过门则提前判读"
                             "（阈值 Q_EXTRAP_*）")
    parser.add_argument("--mesh", type=float, default=0.0,
                        help="0=合规缺省 c3_mesh_max_mm（NEAR≤缝/3）向下取整到 µm；"
                             "显式值越界由 render_script 守卫抛错")
    parser.add_argument("--flo", type=float, default=2.25)
    parser.add_argument("--fhi", type=float, default=2.75)
    parser.add_argument("--timeout", type=float, default=21600.0)
    parser.add_argument("--root", default="runs/smoke_c3",
                        help="工作根目录（分模板子目录 <root>/<pt>；复跑用 "
                             "runs/smoke_c3_refix，旧轮产物不覆盖）")
    args = parser.parse_args(argv)

    template = args.template
    pt = args.pt or (f"{template}_probe" if args.probe else template)
    nrts = 10 if args.probe else args.nrts
    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    design = DESIGNERS[template](ORDER, F0, FBW, RL_DB)
    params = dict(TEMPLATE_NOMINAL[template])      # 只消费不改（名义表=设计 4 位舍入）
    params["order"] = ORDER
    w_feed = float(params[FEED_WIDTH_KEY[template]])
    _, eps_hj_feed = forward_z0(w_feed, F0, stackup)
    mesh_mm = float(args.mesh) if args.mesh > 0 else auto_mesh_mm(template, params)
    mesh_max_mm = c3_mesh_max_mm(template, params)
    print(f"[{template}] mesh={mesh_mm}mm（守卫上限 {mesh_max_mm:.4f}，NEAR≤缝_min/3）",
          flush=True)

    work = Path(args.root) / pt
    exe = resolve_openems_exe()
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=exe, working_dir=str(work),
        freq_range_ghz=(args.flo, args.fhi), mesh_resolution_mm=mesh_mm,
        extra_params={"solve_timeout_s": args.timeout}))
    assert solver.connect(), "openEMS 不可用"
    assert solver.build_geometry({"template": template, "params": params})
    script_path = work / "simulation.py"
    script, n_sub = rewrite_nrts(script_path.read_text(encoding="utf-8"), nrts,
                                 end_criteria=args.end_criteria)
    assert n_sub >= 1, "渲染脚本无 NrTS=100000 可改写（模板口径漂移？）"
    script_path.write_text(script, encoding="utf-8")
    print(f"[{template}] NrTS {NRTS_OLD}→{nrts} 替换 {n_sub} 处；EndCriteria="
          f"{args.end_criteria}；params={params}", flush=True)

    t0 = time.time()
    rc = _run_engine(work, exe, args.timeout, work / "engine.log")
    wall = time.time() - t0
    log_text = (work / "engine.log").read_text(encoding="utf-8", errors="replace")
    eng = parse_engine_log(log_text)
    print(f"solve_s={wall:.0f} rc={rc} engine={json.dumps(eng)}", flush=True)
    if args.probe:
        (work / "_probe_result.json").write_text(
            json.dumps({"template": template, "nrts": nrts, "rc": rc,
                        "solve_s": round(wall, 1), "engine": eng},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"C3_{template.upper()}_PROBE_DONE", flush=True)
        return 0
    sp = work / "sparams.csv"
    if rc != 0 or not sp.exists():
        # 离线 Q 外推判读（--q-extrap）：无 sparams.csv 也可从探针截断态判读
        # （kill/预算截断轮零仿真；源如实标 partial probes）
        qrep = _q_extrap_for(work, eng, args)
        pdir = _probe_dir(work)
        if qrep is not None and "keys" in qrep and pdir is not None:
            freq_o = np.linspace(args.flo * 1e9, args.fhi * 1e9, 401)
            _t_end_o, s11_o, s21_o = q_extrap_truncated_s(str(pdir), freq_o)
            eng_off = dict(eng)
            if qrep.get("excitation_covered_by_data"):
                eng_off["excitation_covered"] = True   # 探针窗含全激励段（数据侧可证）
            h_mm_o = float(stackup.thickness_mm)
            circ_m = c3_circuit_sparams(template, freq_o / 1e9, params,
                                        synchronous_tem=False, h_mm=h_mm_o,
                                        l_via_h=c3_via_inductance_h(h_mm_o))
            circ_o = 20.0 * np.log10(np.abs(circ_m[:, 1, 0]) + 1e-12)
            gates_o, verdict_o, metrics_o = judge(freq_o / 1e9, s11_o, s21_o,
                                                  circ_o, float("nan"), eng_off,
                                                  q_extrap=qrep)
            result = {"item": f"smoke_c3/{template}", "verdict": verdict_o,
                      "pt": pt, "root": args.root,
                      "reason": (f"openEMS 真跑 rc={rc} 无 sparams.csv；"
                                 "探针离线 Q 外推判读（源=partial probes）"),
                      "solve_s": round(wall, 1), "engine": eng_off, "nrts": nrts,
                      "gates": gates_o, "metrics": metrics_o,
                      "convergence": nrts_convergence(eng), "q_extrap": qrep,
                      "data_source": "partial_probes_q_extrap"}
            (work / "_smoke_result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=1, default=str),
                encoding="utf-8")
            print("gates:", json.dumps({k: (round(v['value'], 4)
                                            if isinstance(v['value'], float)
                                            else v['value'], v['ok'])
                                        for k, v in gates_o.items()}), flush=True)
            print(f"C3_{template.upper()}_{verdict_o}（q_extrap offline）", flush=True)
            return 0 if verdict_o in ("PASS", "PARTIAL") else 1
        result = {"item": f"smoke_c3/{template}", "verdict": "FAIL",
                  "reason": f"openEMS 真跑失败 rc={rc}（见 engine.log）",
                  "solve_s": round(wall, 1), "engine": eng, "nrts": nrts}
        (work / "_smoke_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8")
        print(f"C3_{template.upper()}_FAIL", flush=True)
        return 1

    data = read_csv_cols(sp)
    f_ghz = data[:, 0] / 1e9
    s11 = data[:, 1] + 1j * data[:, 2]
    s21 = data[:, 3] + 1j * data[:, 4]

    d_feed = float("nan")
    beta_csv = work / "port_beta.csv"
    if beta_csv.exists():
        with open(beta_csv, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))[1:]
        bf = np.array([float(r[0]) for r in rows])
        bb = np.array([float(r[1]) for r in rows])
        sel = (bf >= 0.96 * F0 * 1e9) & (bf <= 1.04 * F0 * 1e9)
        eps_feed = (float(np.median(bb[sel])) * 299792458.0 / (2 * np.pi * F0 * 1e9)) ** 2
        d_feed = (eps_feed / eps_hj_feed - 1) * 100

    # 裁判：过孔电感端接（Goldfarb-Pucel 闭式，h=基板厚、d=2·r_via）进 peak 门；
    # 理想短路旧参照只作记录（预测下移 = 过孔项单独贡献）
    h_mm = float(stackup.thickness_mm)
    l_via_h = c3_via_inductance_h(h_mm)
    circuit = c3_circuit_sparams(template, f_ghz, params, synchronous_tem=False,
                                 h_mm=h_mm, l_via_h=l_via_h)
    circ_s21_db = 20.0 * np.log10(np.abs(circuit[:, 1, 0]) + 1e-12)
    circuit_ideal = c3_circuit_sparams(template, f_ghz, params, synchronous_tem=False,
                                       h_mm=h_mm, l_via_h=0.0)
    ideal_short_s21_db = 20.0 * np.log10(np.abs(circuit_ideal[:, 1, 0]) + 1e-12)
    ideal_ref = c3_circuit_sparams(template, f_ghz, params, synchronous_tem=True,
                                   design=design)
    ideal_s21_db = 20.0 * np.log10(np.abs(ideal_ref[:, 1, 0]) + 1e-12)
    c13 = coupling_matrix_response(freq_ghz=[float(v) for v in f_ghz], f0_ghz=F0,
                                   fbw=FBW, matrix=design["coupling_matrix"])
    c13_s21 = np.asarray(c13["s21_db"], dtype=float)

    qrep = None
    conv_pre = nrts_convergence(eng)
    if not conv_pre["converged"]:
        qrep = _q_extrap_for(work, eng, args)
    gates, verdict, metrics = judge(f_ghz, s11, s21, circ_s21_db, d_feed, eng,
                                    q_extrap=qrep)
    i_mid = int(np.argmin(np.abs(f_ghz - F0)))
    metrics["sync_tem_s21_at_f0_db"] = float(ideal_s21_db[i_mid])
    metrics["c13_s21_at_f0_db"] = float(c13_s21[i_mid])
    metrics["sync_tem_peak_ghz"] = float(f_ghz[int(np.argmax(ideal_s21_db))])
    metrics["circuit_ideal_short_peak_ghz"] = float(
        f_ghz[int(np.argmax(ideal_short_s21_db))])
    metrics["via_inductance_nh"] = l_via_h * 1e9
    metrics["via_predicted_shift_pct"] = (
        (metrics["circuit_peak_ghz"] / metrics["circuit_ideal_short_peak_ghz"] - 1.0)
        * 100.0)
    metrics["em_vs_ideal_short_peak_pct"] = (
        (metrics["f_peak_ghz"] / metrics["circuit_ideal_short_peak_ghz"] - 1.0)
        * 100.0)

    print(f"[{template}] @{F0}GHz |S21|={metrics['s21_at_f0_db']:.2f}dB "
          f"|S11|={metrics['s11_at_f0_db']:.1f}dB（电路 KJ+过孔 |S21|="
          f"{metrics['circuit_s21_at_f0_db']:.2f}；同步 TEM {metrics['sync_tem_s21_at_f0_db']:.2f}；"
          f"C13 {metrics['c13_s21_at_f0_db']:.3f}）", flush=True)
    print(f"峰位={metrics['f_peak_ghz']:.4f}（电路+过孔 {metrics['circuit_peak_ghz']:.4f}，"
          f"理想短路 {metrics['circuit_ideal_short_peak_ghz']:.4f}，过孔预测下移 "
          f"{metrics['via_predicted_shift_pct']:+.2f}%，同步 TEM {metrics['sync_tem_peak_ghz']:.4f}）"
          f" IL={metrics['il_min_db']:.2f} ripple={metrics['ripple_db']:.2f} "
          f"RL={metrics['rl_band_max_db']:.1f} β{d_feed:+.2f}% "
          f"EMvs电路 max|ΔS21|={metrics['em_vs_circuit_max_ds21_db']:.2f}dB",
          flush=True)
    print("收敛:", json.dumps(nrts_convergence(eng), ensure_ascii=False), flush=True)
    print("gates:", json.dumps({k: (round(v['value'], 4) if isinstance(v['value'], float)
                                    else v['value'], v['ok']) for k, v in gates.items()}),
          flush=True)
    print(f"C3_{template.upper()}_{verdict}", flush=True)

    result = {
        "item": f"smoke_c3/{template}", "verdict": verdict, "pt": pt,
        "root": args.root,
        "nrts": nrts, "nrts_old": NRTS_OLD, "n_nrts_substitutions": n_sub,
        "end_criteria": args.end_criteria,
        "mesh_mm": mesh_mm, "mesh_max_mm": mesh_max_mm,
        "mesh_source": ("explicit" if args.mesh > 0
                        else "auto c3_mesh_max_mm（NEAR≤缝_min/3，#266）"),
        "freq_range_ghz": [args.flo, args.fhi],
        "design_point": {"order": ORDER, "f0_ghz": F0, "fbw": FBW, "rl_db": RL_DB},
        "params": params, "solve_s": round(wall, 1), "rc": rc, "engine": eng,
        "convergence": nrts_convergence(eng),
        "via_inductance": {"l_via_h": l_via_h, "h_mm": h_mm,
                           "source": "Goldfarb-Pucel 1991 (μ0/2π)·h·[ln(4h/d)+1]，"
                                     "d=2×_C3_R_VIA_MM"},
        "metrics": metrics, "gates": gates,
        "gate_spec": {"il_min_db": list(GATE_IL_RANGE), "ripple_db_max": GATE_RIPPLE_MAX,
                      "rl_band_max_db": GATE_RL_MAX, "peak_pct_max": GATE_PEAK_PCT,
                      "beta_pct_max": GATE_BETA_PCT, "power_sum_max": GATE_POWER_SUM,
                      "end_criteria_db_default": DEFAULT_END_CRITERIA_DB,
                      "q_extrap": {"dev_db_max": Q_EXTRAP_DEV_DB_MAX,
                                   "holdout_rel_max": Q_EXTRAP_HOLDOUT_REL_MAX,
                                   "span_db_min": Q_EXTRAP_SPAN_DB_MIN},
                      "source": "coupled_bpf_smoke.py 五门 + smoke_coupled_bpf_nrts.py "
                                "无源性/激励覆盖 + 收敛判读门（触顶未达判据=FAIL）+ "
                                "Q 外推置信门（未达能量判据时 S 可读性提前判读）"},
        "design_notes": design.get("notes"),
    }
    if qrep is not None:
        result["q_extrap"] = qrep
    (work / "_smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
