"""df6 DP-2 Q 半（单腔 Q_u 三方对拍）fixture 发射驱动（T32 草案）。

规格与判据预声明（先写后跑，#122）：runs/df6_dp2diag/q_half/launch_ready.md。
三方 ground = 规格深案 §DP-2 判据 4 +
runs/df6_dp2diag/criteria.md §5：**三方 = vf / circle / skrf.qfactor.Qfactor
（reflection），极差 ≤ 15%，不过 → FAIL 落档**。
T36（2026-09-29）：vf 腿由 q_factor_vf（q_e 输入，存档预演 admit 全败，
rms 3.5e-2~5e-2）替换为 q_factor_vf_zero（极点+零点求和口径，免 q_e；
launch_ready §6①；存档验证 vs circle 0.01%/0.19%，
vf_zero_archive_check.json），判据门与窗口（±5lw）不变。

fixture（interdigital order=1 双 tap 拓扑，零模板改动，a1 qe fixture 同族）：
  qh_g0870 = gaps=[0.87, 6.0]：主 tap 近临界（存档两点实测 Qe(gap) 幂律外推
  β≈0.9-1.1）；第二 tap 6mm 缝（Qe≫1e4，加载 <2%，三方共模）。
  预算锚 = qe_g0800 实测（mesh 0.5mm/dt=1.92e-13s/收敛 52.4 万步，
  NrTS=600k + 帽停自动展延 ×2；#323 先实测后外推、#328 dt 禁估计）。

用法（cwd=仓库根；OE solo：.oe_collect.lock + #261 命令行查双保险）：
  python -u scripts/df6_dp2_q_half_runner.py --plan       # 离线：渲染+审计+plan.json
  python -u scripts/df6_dp2_q_half_runner.py --selftest   # 离线：三方合成回收+C 钉
  python -u scripts/df6_dp2_q_half_runner.py --probe      # NrTS=10 探针：实测 dt
  python -u scripts/df6_dp2_q_half_runner.py --run        # 真机单点（锁内，帽停展延）
  python -u scripts/df6_dp2_q_half_runner.py --judge      # 三方判读（须 selftest PASS）
  python -u scripts/df6_dp2_q_half_runner.py --rehearse   # 存档 qe 两点预演（无门效力）
退出码：0=完成/门过；1=门未达/执行失败；2=参数错误。
产物根 runs/df6_dp2diag/q_half/<pt>/（simulation.py/engine.log/sparams.csv/
port_beta.csv/run_meta.json/verdict.json）。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (REPO / "src", HERE, REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rfauto.adapters.em_solver_base import resolve_openems_exe  # noqa: E402
from rfauto.adapters.openems_templates import (  # noqa: E402
    c3_coupling_j_from_gap,
    render_script,
)
from rfauto.core.calculators import q_factor_circle, q_factor_vf_zero  # noqa: E402
from rfauto.core.deembed import deembed_reference_delay  # noqa: E402
from smoke_coupled_bpf_nrts import (  # noqa: E402  只读复用（a1 同款）
    _run_engine,
    parse_engine_log,
    rewrite_nrts,
)


def _load_mod(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A1 = _load_mod("df6_a1_r4_runner", HERE / "df6_a1_r4_runner.py")
QE_EXTRACT = _load_mod("c3_resonance_q_extract",
                       HERE / "c3_resonance_q_extract.py")

# ── 预声明常量（launch_ready.md 同源；改门先改 launch_ready 再改这里）─────────
ROOT = REPO / "runs" / "df6_dp2diag" / "q_half"
F0_GHZ = 2.5
BAND_GHZ = (2.2, 2.8)
N_FREQ_PTS = 1201
W_MM = 1.1117
RES_LEN_MM = 17.0820
FEED_LEN_MM = 51.4590
S_MAIN_MM = 0.87                        # 主 tap：目标 β≈1（幂律外推，±30% 软）
S_TAP2_MM = 6.0                         # 第二 tap：Qe≫1e4，加载 <2%
MESH_MM = 0.5
NRTS = 600_000
SPREAD_GATE_PCT = 15.0                  # 主门：三方极差（criteria §5 原文）
SYN_LEG_PCT = 2.0                       # 合成回收：vf/circle 各 ≤2%（criteria §2）
SYN_SPREAD_PCT = 15.0                   # 合成三方极差 ≤15%（criteria §4）
AUX_GATE_PCT = 15.0                     # 辅助门：衰减率 Q_L vs circle（不翻主门）
VF_WINDOW_LW = 5.0                      # VF 窗=±5×3dB 线宽（criteria 输入口径下限）
SELFTEST_TOL = 0.01                     # C 钉自回收 ≤1%（a1 同制）
CONV_ENERGY_MAX_DB = -40.0              # 收敛门（a1 同值；帽停态）

sys.path.insert(0, str(REPO / "tests"))


# ── 三方提取（judge 唯一路径；rehearse 与真机同代码）──────────────────────────

def deembed_s11(run_dir: Path) -> tuple[np.ndarray, np.ndarray, float]:
    """sparams.csv S11 → #364② 口径去嵌（τ=feed_len·√εeff/c，β 读 port_beta）。"""
    import csv

    freq, s11 = [], []
    with open(run_dir / "sparams.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            freq.append(float(row["freq_hz"]) / 1e9)
            s11.append(complex(float(row["re_S11"]), float(row["im_S11"])))
    f = np.asarray(freq)
    g = np.asarray(s11)
    feed_len_m = FEED_LEN_MM * 1e-3
    inp = run_dir / "run_input.json"
    if inp.exists():
        feed_len_m = float(json.loads(inp.read_text(encoding="utf-8"))
                           ["params"]["feed_len_mm"]) * 1e-3
    betas: list[tuple[float, float]] = []
    pb = run_dir / "port_beta.csv"
    if pb.exists():
        with open(pb, newline="") as fh:
            for row in csv.DictReader(fh):
                for k, v in row.items():
                    if "beta" in k.lower():
                        try:
                            fr = float(row.get("freq_hz", 0) or 0)
                            betas.append((abs(fr / 1e9 - F0_GHZ), float(v)))
                        except (TypeError, ValueError):
                            continue
    if not betas:
        raise ValueError(f"port_beta.csv 无 β 列：{pb}")
    # β 取最靠近 f0 的行（#364② 参考面口径：去嵌 εeff 在带心标定）；
    # 首行（带缘）β 会引入 ~1% Q_u 漂移（存档预检实测），禁早退。
    beta = min(betas, key=lambda t: t[0])[1]
    c0 = 299792458.0
    eps_eff = (beta * c0 / (2 * math.pi * F0_GHZ * 1e9)) ** 2
    tau = feed_len_m * math.sqrt(eps_eff) / c0
    g, _ = deembed_reference_delay(f * 1e9, g, np.zeros_like(g), tau, tau)
    return f, g, tau


def _skrf_leg(f: np.ndarray, g: np.ndarray) -> dict:
    import skrf as skrf
    from skrf.qfactor import Qfactor

    ntwk = skrf.Network(frequency=f * 1e9, s=g.reshape(-1, 1, 1), z0=50.0)
    qf = Qfactor(ntwk, res_type="reflection")
    qf.fit()
    q_u = float(qf.Q_unloaded())
    q_l = float(qf.opt_res["Q_L"])
    f_l = float(qf.opt_res["f_L"]) / 1e9
    ok = bool(math.isfinite(q_u) and q_u > 0 and math.isfinite(q_l)
              and q_l > 0)
    return {"ok": ok, "q_unloaded": round(q_u, 4), "q_loaded": round(q_l, 4),
            "f0_ghz": round(f_l, 5), "method": "skrf_qfactor_reflection"}


def three_way(f: np.ndarray, g: np.ndarray, q_e: list[float]) -> dict:
    """三方提取 + 极差（launch_ready §判据 G1 的代码化；窗口/输入全预声明）。

    vf 腿 = q_factor_vf_zero（T36 替换：极点+零点求和口径免 q_e，存档验证
    vs circle 0.01%/0.19%）；q_e 形参保留（旧 vf 腿口径兼容，现腿不消费）。
    腿级容错：任一腿抛异常 = 该腿 admit 失败（如实落 FAIL 路径），不炸判读
    （#105 观测面/判读面不阻塞主路径同族；腿失败不豁免不改门）。
    """
    try:
        circle = q_factor_circle(list(f), list(g))
        if not circle.get("ok"):
            return {"verdict": "FAIL", "reason": "circle 腿 admit 失败",
                    "circle": circle}
    except Exception as exc:
        return {"verdict": "FAIL",
                "reason": f"circle 腿异常：{type(exc).__name__}: {exc}"}
    q_l = float(circle["q_loaded"])
    f0c = float(circle["f0_ghz"])
    lw_ghz = f0c / q_l
    m = (f >= F0_GHZ - VF_WINDOW_LW * lw_ghz) & (
        f <= F0_GHZ + VF_WINDOW_LW * lw_ghz)
    if int(m.sum()) < 16:
        return {"verdict": "FAIL", "reason": "VF ±5lw 窗点不足",
                "circle": circle}
    try:
        vf = q_factor_vf_zero(list(f[m]), list(g[m]), f0_hint_ghz=F0_GHZ)
    except Exception as exc:
        vf = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
              "method": "skrf_vector_fitting_pole_zero_sum"}
    skrf_leg = _skrf_leg(f, g)
    legs = {"vf": vf, "circle": circle, "skrf": skrf_leg}
    admit = {
        "vf": bool(vf.get("ok")) and not bool(vf.get("loss_degraded")),
        "circle": True,
        "skrf": bool(skrf_leg["ok"]),
    }
    qu = {k: (float(v["q_unloaded"]) if admit[k]
              and v.get("q_unloaded") is not None else None)
          for k, v in legs.items()}
    if any(v is None for v in qu.values()):
        bad = [k for k, v in qu.items() if v is None]
        return {"verdict": "FAIL", "reason": f"腿 admit 失败：{bad}",
                "legs": legs, "admit": admit, "q_unloaded": qu,
                "vf_window_ghz": [round(F0_GHZ - VF_WINDOW_LW * lw_ghz, 5),
                                  round(F0_GHZ + VF_WINDOW_LW * lw_ghz, 5)]}
    vals = list(qu.values())
    spread_pct = (max(vals) - min(vals)) / min(vals) * 100.0
    return {"verdict": "PASS" if spread_pct <= SPREAD_GATE_PCT else "FAIL",
            "spread_pct": round(spread_pct, 3),
            "gate_pct": SPREAD_GATE_PCT, "legs": legs, "admit": admit,
            "q_unloaded": {k: round(v, 4) for k, v in qu.items()},
            "vf_window_ghz": [round(F0_GHZ - VF_WINDOW_LW * lw_ghz, 5),
                              round(F0_GHZ + VF_WINDOW_LW * lw_ghz, 5)],
            "lw_ghz": round(lw_ghz, 5)}


def decay_ql(run_dir: Path) -> dict:
    """辅助门：port_ut_1B 环振段主模 Q_L（c3_resonance_q_extract 家法）。"""
    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    t_exc = float(meta["engine"]["excitation_s"])
    t, u = QE_EXTRACT.read_probe_series(run_dir / "fdtd" / "port_ut_1B")
    modes = QE_EXTRACT.extract_ring_modes(t, u, 2.4e9, 2.6e9, t_exc, n_modes=2)
    pick = min(modes, key=lambda d: abs(d["f0_hz"] / 1e9 - F0_GHZ))
    return {"q_loaded": round(float(pick["q_loaded"]), 3),
            "f0_ghz": round(float(pick["f0_hz"]) / 1e9, 5),
            "alpha_per_s": float(pick["alpha_per_s"]),
            "span_db": round(float(pick["span_db"]), 2),
            "method": "c3_resonance_q_extract.variable_projection"}


# ── C 钉（点位确切 tap 配置合成回收；钉不过 judge 拒吃真机，#118/#300）────────

def qe_pin() -> dict:
    b = A1.slope_b()
    z_r, ere = A1._zr_ere()
    j1, _ = c3_coupling_j_from_gap(W_MM, S_MAIN_MM, F0_GHZ, 3.66, 0.508)
    j2, _ = c3_coupling_j_from_gap(W_MM, S_TAP2_MM, F0_GHZ, 3.66, 0.508)
    qe1_true = A1.qe_from_j(j1, b)
    qe2_kj = A1.qe_from_j(j2, b)
    f = np.linspace(BAND_GHZ[0], BAND_GHZ[1], 801) * 1e9
    s = A1.synthetic_schain([j1, j2], RES_LEN_MM, z_r, ere, f, FEED_LEN_MM)
    s11 = np.asarray(s["s11"] if isinstance(s, dict) else s)
    if s11.ndim == 3:
        s11 = s11[:, 0, 0]
    raw = A1.extract_qe_point(f, s11, c_cfg=1.0)
    c_pin = raw["qe_s11"] / qe1_true
    back = A1.extract_qe_point(f, s11, c_cfg=c_pin)
    rel = abs(back["qe_s11"] - qe1_true) / qe1_true
    return {"c_pin": round(c_pin, 9), "qe1_true": round(qe1_true, 4),
            "qe2_kj": round(qe2_kj, 1), "j1_s": float(j1), "j2_s": float(j2),
            "self_recovery_rel": float(rel), "ok": bool(rel <= SELFTEST_TOL)}


def synthetic_selftest() -> dict:
    """三方合成回收（criteria §2 fixture 子集 + §4 极差门）。"""
    cases = []
    for qu in (500.0, 2000.0):
        for beta in (0.5, 1.0, 2.0):
            lw = F0_GHZ / qu
            f = np.linspace(F0_GHZ - 10 * lw, F0_GHZ + 10 * lw, 801)
            x = f / F0_GHZ - F0_GHZ / f
            gam = (beta - 1 - 1j * qu * x) / (beta + 1 + 1j * qu * x)
            res = three_way(f, gam, [qu / beta])
            cases.append({"q_u": qu, "beta": beta,
                          "spread_pct": res.get("spread_pct"),
                          "q_unloaded": res.get("q_unloaded"),
                          "verdict": res.get("verdict"),
                          "reason": res.get("reason")})
    leg_ok = all(c["verdict"] == "PASS" for c in cases)
    return {"cases": cases, "ok": bool(leg_ok),
            "gates": {"leg_syn_pct": SYN_LEG_PCT,
                      "spread_pct": SYN_SPREAD_PCT}}


# ── 渲染/审计/运行（a1 同制）────────────────────────────────────────────────

PT_PARAMS = {"order": 1, "w_mm": W_MM, "res_len_mm": RES_LEN_MM,
             "feed_len_mm": FEED_LEN_MM, "gaps_mm": [S_MAIN_MM, S_TAP2_MM]}


def audit_plan() -> dict:
    text = render_script("interdigital", dict(PT_PARAMS), BAND_GHZ,
                         mesh_resolution_mm=MESH_MM)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(ROOT / "_audit_sim.py")}
    exec(compile(head, "qhalf_audit", "exec"), scope)
    from tests.unit import _geometry_audit_helpers as gh
    prims = gh.extract_primitives(scope["CSX"])
    n_metal = sum(1 for p in prims if p.kind == "Metal")
    gaps_m = [v * 1e-3 for v in PT_PARAMS["gaps_mm"]]
    near = MESH_MM / 4 * 1e-3
    gap_ok = all(g / 3 >= near for g in gaps_m)
    return {"primitives": len(prims), "metal_prims": n_metal,
            "gap_over_ne3": gap_ok, "mesh_mm": MESH_MM,
            "sha_render": hashlib.sha256(
                text.encode("utf-8")).hexdigest()[:16]}


def _engine_once(pt: str, nrts: int, timeout_s: float, exe: str | None) -> dict:
    work = ROOT / pt
    work.mkdir(parents=True, exist_ok=True)
    script = render_script("interdigital", dict(PT_PARAMS), BAND_GHZ,
                           mesh_resolution_mm=MESH_MM)
    sha_plain = hashlib.sha256(script.encode("utf-8")).hexdigest()
    script, n_nrts = rewrite_nrts(script, nrts)
    assert n_nrts >= 1, "NrTS 改写未命中（渲染口径漂移）"
    (work / "simulation.py").write_text(script, encoding="utf-8")
    sha_final = hashlib.sha256(script.encode("utf-8")).hexdigest()
    (work / "run_input.json").write_text(json.dumps(
        {"pt": pt, "nrts": nrts, "freq_pts": N_FREQ_PTS,
         "sha_render_plain": sha_plain, "sha_final": sha_final,
         "params": PT_PARAMS, "mesh_mm": MESH_MM, "ts": A1.utc_now()},
        ensure_ascii=False, indent=1), encoding="utf-8")
    t0 = time.monotonic()
    rc, timed_out = 0, False
    try:
        rc = _run_engine(work, exe, timeout_s, work / "engine.log")
    except subprocess.TimeoutExpired:
        rc, timed_out = 124, True
    wall = time.monotonic() - t0
    log = (work / "engine.log").read_text(encoding="utf-8", errors="replace")
    eng = parse_engine_log(log)
    eng["timed_out"] = timed_out
    return {"rc": int(rc), "wall_s": round(wall, 1), "engine": eng,
            "nrts": int(nrts), "sha_final": sha_final,
            "sha_render_plain": sha_plain}


def run_point(pt: str = "qh_g0870", extend: bool = True) -> dict:
    foreign = A1.oe_foreign_running()
    if foreign:
        return {"pt": pt, "started": False, "rc": None,
                "reason": f"#261 互斥命中（他轨 OE 在跑，不代杀）：{foreign}"}
    lock = A1.lock_acquire("df6_dp2_q_half")
    if not lock["acquired"]:
        return {"pt": pt, "started": False, "rc": None,
                "reason": f".oe_collect.lock 忙（owner={lock['owner']}）"}
    try:
        exe = resolve_openems_exe()
        rec = _engine_once(pt, NRTS, A1._timeout_for(NRTS, MESH_MM), exe)
        rec["extended"] = False
        eng = rec["engine"]
        done = int(eng.get("iterations_done", 0) or 0)
        cap_hit = bool(eng.get("nrts_limit_warning")) or (
            0 < done >= int(rec["nrts"]))
        last_e = eng.get("last_energy_db")
        if (extend and cap_hit and rec["rc"] == 0
                and isinstance(last_e, (int, float))
                and last_e > A1.EXTEND_ENERGY_MAX_DB):
            nrts2 = int(rec["nrts"]) * A1.EXTEND_FACTOR
            rec2 = _engine_once(pt, nrts2, A1._timeout_for(nrts2, MESH_MM),
                                exe)
            rec2["extended"] = True
            rec2["first_attempt"] = {k: rec[k] for k in ("rc", "wall_s",
                                                         "nrts")}
            rec = rec2
        rec["pt"] = pt
        (ROOT / pt / "run_meta.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8")
        return rec
    finally:
        A1.lock_release()


# ── 判读 ─────────────────────────────────────────────────────────────────────

def judge_point(pt: str = "qh_g0870") -> dict:
    run_dir = ROOT / pt
    pin = json.loads((ROOT / "selftest_result.json").read_text(
        encoding="utf-8")) if (ROOT / "selftest_result.json").exists() else {}
    if not pin.get("ok"):
        return {"pt": pt, "verdict": "FAIL",
                "reason": "selftest 缺失或未 PASS（钉不过 judge 拒吃真机）"}
    meta_p = run_dir / "run_meta.json"
    if not meta_p.exists():
        return {"pt": pt, "verdict": "FAIL", "reason": "run_meta 缺失（未跑）"}
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    eng = meta.get("engine", {})
    last_e = eng.get("last_energy_db")
    converged = bool(eng.get("endcriteria_reached")) or (
        isinstance(last_e, (int, float)) and last_e <= CONV_ENERGY_MAX_DB)
    if not converged:
        return {"pt": pt, "verdict": "FAIL",
                "reason": f"引擎未收敛（last={last_e}dB，门 ≤{CONV_ENERGY_MAX_DB}"
                          "；帽停展延后仍不达=如实 FAIL）",
                "convergence": {"last_energy_db": last_e,
                                "iterations_done": eng.get("iterations_done")}}
    f, g, _tau = deembed_s11(run_dir)
    # Qe 输入 = [Qe1 群时延(C 钉), Qe2 KJ]；Qe1 由同 run **原始（未去嵌）**S11
    # extract_qe_point 自标定——群时延 C 钉在原参考面自洽（钉电路同口径），
    # 去嵌面只服务三方圆提取（launch_ready §Qe 输入预声明，不得事后换源）。
    qe1 = A1.extract_qe_point(f * 1e9, _read_raw_s11(run_dir),
                              c_cfg=pin["qe_pin"]["c_pin"])
    res2 = three_way(f, g, [abs(qe1["qe_s11"]), pin["qe_pin"]["qe2_kj"]])
    res2["qe_input"] = {"qe1_s11": round(qe1["qe_s11"], 3),
                        "qe1_sign": qe1["sign"],
                        "qe2_kj": pin["qe_pin"]["qe2_kj"]}
    res2["convergence"] = {"last_energy_db": last_e,
                           "iterations_done": eng.get("iterations_done"),
                           "wall_s": meta.get("wall_s"),
                           "extended": meta.get("extended")}
    try:
        dec = decay_ql(run_dir)
        q_l_circle = float(res2["legs"]["circle"]["q_loaded"])
        dec["vs_circle_rel_pct"] = round(
            abs(dec["q_loaded"] - q_l_circle) / q_l_circle * 100.0, 2)
        dec["gate_pct"] = AUX_GATE_PCT
        dec["verdict"] = ("PASS" if dec["vs_circle_rel_pct"] <= AUX_GATE_PCT
                          else "FAIL")
        res2["decay_aux"] = dec
        res2["aux_note"] = ("辅助门失败不翻主门 verdict，如实落档归因"
                            "（launch_ready §判据 G2 预声明）")
    except Exception as exc:
        res2["decay_aux"] = {"verdict": "UNDECIDABLE",
                             "reason": f"{type(exc).__name__}: {exc}"}
    res2["pt"] = pt
    res2["ts"] = A1.utc_now()
    (run_dir / "verdict.json").write_text(
        json.dumps(res2, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    return res2


def _read_raw_s11(run_dir: Path) -> np.ndarray:
    import csv

    out = []
    with open(run_dir / "sparams.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            out.append(complex(float(row["re_S11"]), float(row["im_S11"])))
    return np.asarray(out)


def rehearse() -> dict:
    """存档 qe 两点预演（判读链演练；无门效力，标签如实）。"""
    a1_root = REPO / "runs" / "df6_a1_r4"
    out: dict = {}
    for pt in ("qe_g0800", "qe_g02263"):
        rd = a1_root / pt
        if not (rd / "sparams.csv").exists():
            out[pt] = {"skip": "存档缺失"}
            continue
        f, g, tau = deembed_s11(rd)
        vd = json.loads((rd / "verdict.json").read_text(encoding="utf-8"))
        c_pin = float(vd["extract"]["c_cfg"])
        qe1 = A1.extract_qe_point(f * 1e9, _read_raw_s11(rd), c_cfg=c_pin)
        b = A1.slope_b()
        j2, _ = c3_coupling_j_from_gap(W_MM, 2.0, F0_GHZ, 3.66, 0.508)
        qe2_kj = A1.qe_from_j(j2, b)
        res = three_way(f, g, [abs(qe1["qe_s11"]), qe2_kj])
        res["rehearsal"] = True
        res["gate_effect"] = "无门效力（存档预演，launch_ready §存档预检）"
        res["tau_deembed_ns"] = round(tau * 1e9, 4)
        out[pt] = res
    (ROOT / "rehearse_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--rehearse", action="store_true")
    args = ap.parse_args(argv)
    n_act = sum((args.plan, args.selftest, args.probe, args.run, args.judge,
                 args.rehearse))
    if n_act != 1:
        ap.error("须择一 action：--plan/--selftest/--probe/--run/--judge/"
                 "--rehearse")
        return 2
    ROOT.mkdir(parents=True, exist_ok=True)
    if args.plan:
        out = {"pt": "qh_g0870", "params": PT_PARAMS, "mesh_mm": MESH_MM,
               "nrts": NRTS, "band_ghz": BAND_GHZ,
               "freq_pts": N_FREQ_PTS, "audit": audit_plan(),
               "ts": A1.utc_now()}
        (ROOT / "plan.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    if args.selftest:
        pin = qe_pin()
        syn = synthetic_selftest()
        out = {"qe_pin": pin, "synthetic": syn,
               "ok": bool(pin["ok"] and syn["ok"]), "ts": A1.utc_now()}
        (ROOT / "selftest_result.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if out["ok"] else 1
    if args.probe:
        foreign = A1.oe_foreign_running()
        if foreign:
            print(json.dumps({"started": False, "reason": f"#261 命中：{foreign}"},
                             ensure_ascii=False))
            return 1
        A1.lock_acquire("df6_dp2_q_half_probe")
        try:
            rec = _engine_once("probe", 10, 900.0, resolve_openems_exe())
        finally:
            A1.lock_release()
        eng = rec["engine"]
        print(json.dumps({"dt_s": eng.get("dt_s"), "cells": eng.get("cells"),
                          "rc": rec["rc"]}, ensure_ascii=False))
        return 0 if rec["rc"] == 0 else 1
    if args.run:
        rec = run_point()
        print(json.dumps({k: rec.get(k) for k in
                          ("pt", "started", "rc", "wall_s", "nrts",
                           "extended", "reason")},
                         ensure_ascii=False, default=str))
        eng = rec.get("engine", {})
        return 0 if rec.get("rc") == 0 and not eng.get("timed_out") else 1
    if args.judge:
        res = judge_point()
        keep = ("pt", "verdict", "spread_pct", "gate_pct", "q_unloaded",
                "qe_input", "decay_aux", "reason")
        print(json.dumps({k: res.get(k) for k in keep},
                         ensure_ascii=False, default=str))
        return 0 if res.get("verdict") == "PASS" else 1
    out = rehearse()
    for pt, res in out.items():
        print(pt, json.dumps({k: res.get(k) for k in
                              ("verdict", "spread_pct", "q_unloaded",
                               "reason")},
                             ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
