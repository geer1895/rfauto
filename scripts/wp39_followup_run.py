r"""WP3.9 MVP followUps 运行器（followUps①-⑤）。

基线轮（runs/wp39_mvp/，0/3 如实 FAIL）已证：同 HFSS 求解器口径下
wall≤1/2 被算术锁死（#224）——本脚本补测 §10.0 两档基线与判据缺口：

- probe         openEMS mline 数据工厂校准探针（网格选型+地貌奇偶校验
                +线长不变性，①档前置，④"问题定义前先标定"纪律）；
- factory       ①档 openEMS 数据工厂 sbo 环（run_surrogate_loop 同内核，
                预算 25，smt_kriging，与 wp39 战役 sbo 臂同配置）；
- replay        工厂最优参数回代 HFSS 评估器判 cost（"回代
                同一评估器"口径）+ judge_problem_pair 对既有基线判定；
- ratrace_null  ③ 深零点判据对照：归档 ratrace .s4p 上单频谷深 vs
                深零点邻域/带宽积分指标的网格敏感性对照（零真机）；
- native        ⑤ HFSS Optimetrics 原生 setup 补测（PyAEDT
                optimizations.add 建 Optimetrics 原生优化，Pattern
                Search，MaxNumIteration=预算锚点，无法硬帽评估数——
                实际评估数按提取梯次如实记录）；
- patch_calib   ④ openEMS patch 单点扫频谷位标定（f_dip·L 常数，
                对照归档 HFSS 99.8 与 openEMS 76.8，漂移比值定标）；
- optislang_probe  ② optiSLang MOP 超额线可用性探测（license/链路）；
- judge         汇总 outdir 全部 followup JSON → summary。

换判据档（wp39-factory-verdict-next；一律 -outdir
runs/wp39_factory_verdict_next，禁写既有归档 #122）：
- probe_eps     网格 1.2/2.0/3.0 × w 三点 β→εeff 地貌 → service 健康门
                （副锚 ≤3% ∧ 单调）取最快网格，名义点 εeff 即工厂 target（④）；
- factory_eps   openEMS 工厂 sbo 环，目标 |εeff−target|，缓存关闭+断言；
- replay_eps    工厂最优 w 回代 HFSS mline_eps（同 sweep、同 S21 相位抽取、
                同基线 target）→ judge 对 mline_eps__pattern_search 新基线；
- summary_next  汇总：mline_eps_factory + ratrace_null 判定；native vs
                scripted 与 optiSLang NOT_RUN 作决策输入 → summary.json。

真机纪律：openEMS 全机单跑串行（probe→factory→patch_calib 不得并行）；
HFSS 项（replay/native）串行；墙钟测量要求机器独占。长任务按 #157
Start-Process 分离+日志轮询：
  powershell Start-Process -FilePath .venv\Scripts\python.exe `
    -ArgumentList "scripts/wp39_followup_run.py -tier factory" `
    -RedirectStandardOutput runs/wp39_mvp_followup/factory.log `
    -RedirectStandardError runs/wp39_mvp_followup/factory.err.log -Wait

产出：runs/wp39_mvp_followup/{tier}.json（schema wp39_followup_*_v1）。
数值纪律：只出确定性内核/真机求解器；观测性失败 best-effort 不阻塞
主路径（#105）；任何"提取不到"的字段如实 null，绝不填猜测值。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, "src")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from rfauto.service.wp39_benchmark import (  # noqa: E402
    band_power_avg_db,
    deep_null_neighborhood_db,
    dip_constant,
    eps_eff_error_metric,
    eps_eff_from_beta,
    judge_problem_pair,
    locate_dip_ghz,
    merge_factory_with_replay,
    mline_landscape_health_gate,
    recenter_length_for_target,
    sbo_objectives,
    summarize_judgment,
)

DEFAULT_OUTDIR = REPO / "runs" / "wp39_mvp_followup"
BASELINE_DIR = REPO / "runs" / "wp39_mvp"
#: 换判据战役新目录（wp39-factory-verdict-next；不覆盖既有 FAIL 归档 #122）
NEXT_OUTDIR = REPO / "runs" / "wp39_factory_verdict_next"
MLINE_F0_GHZ = 2.5
FACTORY_BAND_GHZ = (2.4, 2.6)
MLINE_NOMINAL_W = 1.113
#: HJ 闭式副锚 stackup（与 scripts/engine_benchmark_mline.py 同源）
MLINE_STACKUP = "rogers4350b_h0.508"
#: probe_eps 候选网格：含比 1.2mm 更粗的 2.0/3.0（εeff 对网格弱敏感 →
#: 可能换来墙钟）；w 三点与旧探针同
PROBE_EPS_MESHES = [1.2, 2.0, 3.0]
PROBE_W_LIST = [0.85, 1.113, 1.4]
# ④ 标定参考常数（GHz·mm）：HFSS=归档 probe.s1p 离线复核值；
# openEMS=#190 23 点战役定标值。
# DP-3 第二批改道（锚消费接线）：单源=knowledge/anchors.yaml
# （patch.f_dip_l.hfss-v1 / .openems-v1），消费点经 _resolve_patch_constant
# 按引擎对选锚解析；下列字面值降级为解析失败时的回退值（锚值与字面值
# 逐位相等——test_anchors_store_service a2 正则钉本字面行，零行为变化）。
HFSS_PATCH_CONSTANT_REF = 99.8
OPENEMS_PATCH_CONSTANT_DOC = 76.8
RATRACE_NULL_SEARCH = (2.3, 2.7)


def _resolve_patch_constant(anchor_id: str, fallback: float) -> float:
    """按引擎对选锚解析 patch f_dip·L 标定常数（DP-3 第二批改道）。

    锚单源=knowledge/anchors.yaml（patch.f_dip_l.openems-v1=76.8 /
    patch.f_dip_l.hfss-v1=99.8）；解析失败（注册表缺/坏/stale/任何异常）
    回退字面参考值——锚值与字面值逐位相等（test_anchor_wire_df7 钉），
    零行为变化，#105 best-effort（锚系统故障不阻塞证据脚本）。"""
    try:
        from rfauto.infra.anchors_store import load_anchors

        got = load_anchors().resolve_anchor(anchor_id)
        value = got.get("value")
        if (got.get("hit") and got.get("source") == "anchor"
                and not got.get("stale")
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))):
            return float(value)
    except Exception:
        pass
    return float(fallback)

SCHEMA = "wp39_followup"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                               default=str), encoding="utf-8")
    print(f"WROTE {path}", flush=True)


def _s_db_at(freqs_ghz: Any, s_complex: Any, f0_ghz: float) -> float:
    """复 S 参数在 f0 处的 dB（实/虚部各自线性插值后取模——比最近邻
    栅格点更稳，扫频不含 f0 时如实在插值口径取值）。"""
    f = np.asarray(freqs_ghz, dtype=float)
    s = np.asarray(s_complex)
    re_i = float(np.interp(f0_ghz, f, s.real))
    im_i = float(np.interp(f0_ghz, f, s.imag))
    return float(20.0 * np.log10(math.hypot(re_i, im_i) + 1e-12))


# ── openEMS mline 数据工厂 evaluator（①/探针共用）────────────────────────────


def make_openems_mline_evaluator(
    *,
    mesh_mm: float,
    work_root: Path,
    freq_range: tuple[float, float] = FACTORY_BAND_GHZ,
    line_len_mm: float = 40.0,
    log: list[dict[str, Any]] | None = None,
) -> Callable[[dict[str, float]], dict[str, float]]:
    """构造 openEMS mline 单点评估器：params→{s11_f0_db}。

    每参数点独立工作目录（防陈旧 .s?p 产物被误解析，#208 家族）；
    结果记 per-point 墙钟与缓存命中位进 log（工厂墙钟审计用）。
    """
    def evaluate(params: dict[str, float]) -> dict[str, float]:
        from rfauto.adapters.em_solver_base import (
            EMSolverConfig,
            resolve_openems_exe,
        )
        from rfauto.adapters.openems_solver import OpenEMSSolver

        w = float(params["w_mm"])
        tag = f"w{w:.4f}_L{line_len_mm:.1f}"
        work = work_root / tag
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type="openems", exe_path=resolve_openems_exe(),
            working_dir=str(work), freq_range_ghz=tuple(freq_range),
            mesh_resolution_mm=float(mesh_mm),
            extra_params={"solve_timeout_s": 3600}))
        if not solver.connect():
            raise RuntimeError("openEMS 不可用（resolve_openems_exe）")
        ok = solver.build_geometry({
            "template": "mline",
            "params": {"w_mm": w, "line_len_mm": float(line_len_mm)}})
        if not ok:
            raise RuntimeError("openEMS 构建几何失败")
        t0 = time.time()
        result = solver.solve()
        wall = time.time() - t0
        if not result.success:
            raise RuntimeError(f"openEMS 求解失败: {result.message}")
        cached = "缓存复用" in (result.message or "")
        s11 = _s_db_at(result.freq_ghz, result.s_params[:, 0, 0],
                       MLINE_F0_GHZ)
        if log is not None:
            log.append({"params": {"w_mm": w},
                        "line_len_mm": line_len_mm,
                        "s11_f0_db": round(s11, 4),
                        "solve_s": round(wall, 2), "cached": cached})
        print(f"[factory-eval] w={w:.4f} L={line_len_mm:.1f} "
              f"s11@2.5={s11:.2f}dB solve={wall:.1f}s cached={cached}",
              flush=True)
        return {"s11_f0_db": s11}

    return evaluate


# ── 探针档（①前置：网格选型 + 地貌奇偶 + 线长不变性）────────────────────────


def run_probe_tier(outdir: Path, meshes: list[float],
                   w_list: list[float],
                   freq_range: tuple[float, float]) -> Path:
    """openEMS mline 工厂校准探针：候选网格 × 3 点 w 地貌 + 线长对。

    网格入选门（④"问题定义前先标定"纪律）：① 名义点 w=1.113 是该
    网格 3 点地貌的极小（|S11| 最低）；② 名义点 |S11| < −15dB
    （匹配方向正确，锚模板口径 |S11| 显著非零=判废信号）。入选网格
    取通过两门者中单点墙钟最短者。线长不变性：同一网格 w=1.113 下
    L=40 vs L=80 的 |S11|@2.5 差（无损线一阶 |Γ| 与线长无关——
    差异大则工厂地貌与 HFSS 80mm 基线不同源，如实记录）。
    """
    outdir.mkdir(parents=True, exist_ok=True)
    work_root = outdir / "_work_probe"
    eval_log: list[dict[str, Any]] = []
    configs: list[dict[str, Any]] = []
    for mesh in meshes:
        evaluate = make_openems_mline_evaluator(
            mesh_mm=mesh, work_root=work_root / f"m{mesh}",
            freq_range=freq_range, line_len_mm=40.0, log=eval_log)
        pts = []
        for w in w_list:
            t0 = time.time()
            metrics = evaluate({"w_mm": w})
            pts.append({"w_mm": w, "s11_f0_db": metrics["s11_f0_db"],
                        "wall_s": round(time.time() - t0, 2)})
        nominal = next(p for p in pts if abs(p["w_mm"] - 1.113) < 1e-9)
        is_argmin = nominal["s11_f0_db"] == min(p["s11_f0_db"] for p in pts)
        sane = nominal["s11_f0_db"] < -15.0
        configs.append({
            "mesh_mm": mesh, "points": pts,
            "nominal_is_argmin": is_argmin, "nominal_sane": sane,
            "median_wall_s": sorted(p["wall_s"] for p in pts)[len(pts) // 2],
        })
        print(f"[probe] mesh={mesh} argmin={is_argmin} sane={sane} "
              f"median_wall={configs[-1]['median_wall_s']}s", flush=True)
    passing = [c for c in configs
               if c["nominal_is_argmin"] and c["nominal_sane"]]
    chosen: dict[str, Any] | None = None
    length_pair: dict[str, Any] | None = None
    if passing:
        best = min(passing, key=lambda c: c["median_wall_s"])
        chosen = {"mesh_mm": best["mesh_mm"],
                  "rationale": "过奇偶/健康两门中单点墙钟最短"}
        evaluate = make_openems_mline_evaluator(
            mesh_mm=best["mesh_mm"], work_root=work_root / "lenpair",
            freq_range=freq_range, line_len_mm=80.0, log=eval_log)
        t0 = time.time()
        s11_l80 = evaluate({"w_mm": 1.113})["s11_f0_db"]
        l40 = next(p for c in configs if c["mesh_mm"] == best["mesh_mm"]
                   for p in c["points"] if abs(p["w_mm"] - 1.113) < 1e-9)
        length_pair = {
            "line_len_mm": [40.0, 80.0],
            "s11_l40_db": l40["s11_f0_db"], "s11_l80_db": s11_l80,
            "delta_db": round(s11_l80 - l40["s11_f0_db"], 3),
            "l80_wall_s": round(time.time() - t0, 2),
            "note": "无损线一阶 |Γ| 与线长无关；|Δ| 大于 1.5dB 说明"
                    "两引擎地貌不同源，须改用 L=80 工厂口径",
        }
    payload = {
        "schema": f"{SCHEMA}_probe_v1", "generated_at": _now(),
        "tier": "probe", "freq_range_ghz": list(freq_range),
        "w_list": w_list, "meshes": meshes, "configs": configs,
        "eval_log": eval_log, "chosen": chosen,
        "length_pair": length_pair,
        "verdict": "PASS" if chosen else "FAIL（无网格通过奇偶/健康门）",
    }
    out = outdir / "probe.json"
    _write_json(out, payload)
    print(f"WP39_PROBE_{payload['verdict']}", flush=True)
    return out


# ── ①档 openEMS 数据工厂（sbo 环，与 wp39 战役 sbo 臂同内核同配置）───────────


def run_factory_tier(outdir: Path, mesh_mm: float, budget: int, seed: int,
                     freq_range: tuple[float, float]) -> Path:
    import wp39_benchmark_run as runner
    from rfauto.optimization.surrogate_loop import run_surrogate_loop

    problem = runner.PROBLEMS["mline"]
    outdir.mkdir(parents=True, exist_ok=True)
    # 前置探针结论自动折入（④ 纪律：问题定义前先标定——奇偶 FAIL 时
    # 工厂结果按"探针已判废地貌"口径解读，判据归因有据）
    probe_note: dict[str, Any] = {"probe_json": None}
    probe_path = outdir / "probe.json"
    if probe_path.exists():
        probe = json.loads(probe_path.read_text(encoding="utf-8"))
        probe_note = {"probe_json": str(probe_path),
                      "probe_verdict": probe.get("verdict"),
                      "probe_chosen": probe.get("chosen")}
    eval_log: list[dict[str, Any]] = []
    evaluate = make_openems_mline_evaluator(
        mesh_mm=mesh_mm, work_root=outdir / "_work_factory",
        freq_range=freq_range, line_len_mm=40.0, log=eval_log)
    t0 = time.time()
    kernel = run_surrogate_loop(
        problem.bounds, sbo_objectives(problem.metric_name), evaluate,
        n_init=problem.n_init, top_k=runner.SBO_TOP_K,
        virtual_trials=runner.SBO_VIRTUAL_TRIALS, max_real=budget,
        tol_abs=runner.SBO_TOL_ABS_DB, tol_rounds=runner.SBO_TOL_ROUNDS,
        surrogate_kind="smt_kriging", seed=seed)
    elapsed = time.time() - t0
    payload = {
        "schema": f"{SCHEMA}_factory_v1", "generated_at": _now(),
        "tier": "factory", "problem": problem.name,
        "engine_impl": ("①档 openEMS 数据工厂：run_surrogate_loop 同内核"
                        "（smt_kriging GP + 2000 虚拟寻优 top-K 真跑），"
                        "evaluator=openEMS mline 模板单点真跑"),
        "budget": budget, "seed": seed,
        "metric_name": problem.metric_name,
        "evaluator_meta": {
            "template": "mline", "line_len_mm": 40.0,
            "freq_range_ghz": list(freq_range), "mesh_mm": mesh_mm,
            "substrate": "rfauto_m366 (er=3.66 h=0.508 tan_d=0.0037)",
            "note": "openEMS 全机单跑纪律：评估严格串行",
            "probe_context": probe_note},
        "best": {"params": kernel["best"]["params"],
                 "metrics": kernel["best"]["metrics"],
                 "cost": kernel["best"]["cost"]},
        "n_evals": kernel["n_attempts"], "n_failures": kernel["n_failures"],
        "stop_reason": kernel["stop_reason"],
        "real_cost_trace": kernel["real_cost_trace"],
        "rounds": kernel["rounds"],
        "eval_log": eval_log,
        "wall_s": {"optimization_s": round(elapsed, 2)},
        "elapsed_s": round(elapsed, 2),
        "params_meta": {"bounds": {k: list(v)
                                   for k, v in problem.bounds.items()}},
    }
    out = outdir / "factory.json"
    _write_json(out, payload)
    print(f"WP39_FACTORY_DONE best={payload['best']} "
          f"n_evals={payload['n_evals']} wall={elapsed:.1f}s "
          f"stop={kernel['stop_reason']}", flush=True)
    return out


# ── 回代档（①：HFSS 评估器判 cost + 对既有基线判定）──────────────────────────


def run_replay_tier(outdir: Path, factory_json: Path,
                    baseline_json: Path) -> Path:
    """工厂最优 w 回代 HFSS 评估器（同 wp39 HfssEvaluator 导出链）。

    回代评估独立记账（仲裁步，不计入工厂预算——"回代同一
    评估器"口径）；判定对既有 pattern_search 基线战役（wall≤1/2 且劣化
    ≤5% 门，judge_problem_pair 唯一裁判）。
    """
    import wp39_benchmark_run as runner

    factory = json.loads(factory_json.read_text(encoding="utf-8"))
    best_params = factory["best"]["params"]
    problem = runner.PROBLEMS[factory.get("problem", "mline")]
    outdir.mkdir(parents=True, exist_ok=True)
    workdir = outdir / f"_work_{problem.name}__hfss_replay"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    runner._kill_desktops()
    evaluator = runner.HfssEvaluator(problem, workdir)
    replay: dict[str, Any] = {}
    try:
        evaluator.launch_and_build()
        t0 = time.time()
        metrics = evaluator.evaluate(
            {k: float(v) for k, v in best_params.items()})
        replay = {
            "params": best_params, "metrics": metrics, "n_evals": 1,
            "wall_s": {"eval_s": round(time.time() - t0, 2),
                       "launch_s": round(evaluator.launch_s, 2),
                       "build_s": round(evaluator.build_s, 2)},
        }
        print(f"[replay] HFSS 回代 {best_params} -> "
              f"{metrics}", flush=True)
    finally:
        evaluator.close()
    merged = merge_factory_with_replay(
        factory, replay, metric_name=problem.metric_name)
    baseline = json.loads(baseline_json.read_text(encoding="utf-8"))
    verdict = judge_problem_pair(baseline, merged)
    payload = {
        "schema": f"{SCHEMA}_replay_v1", "generated_at": _now(),
        "tier": "replay", "factory_json": str(factory_json),
        "baseline_json": str(baseline_json), "replay": replay,
        "merged_candidate": merged, "verdict": verdict,
    }
    out = outdir / "replay.json"
    _write_json(out, payload)
    print(f"WP39_FACTORY_VERDICT {verdict['verdict']} "
          f"ratio={verdict['wallclock_ratio']} "
          f"deg%={verdict['degradation_pct']} "
          f"reasons={verdict['reasons']}", flush=True)
    return out


# ── ③ 深零点判据对照（零真机：归档 .s4p 回放）────────────────────────────────


def analyze_null_file(path: Path, f0_list: list[float],
                      search_band: tuple[float, float],
                      half_windows: list[float]) -> dict[str, Any]:
    """单 .sNp 的深零点判据对照（③）：单频谷深 vs 邻域/带宽积分。"""
    import skrf

    net = skrf.Network(str(path))
    f = net.f / 1e9
    s31 = net.s[:, 2, 0]
    s31_db = 20.0 * np.log10(np.abs(s31) + 1e-12)
    f_dip, meta = locate_dip_ghz(f, s31_db)
    entry: dict[str, Any] = {
        "file": str(path),
        "freq_range_ghz": [round(float(f.min()), 4),
                           round(float(f.max()), 4)],
        "n_points": int(f.size),
        "null": {"f_null_ghz": round(f_dip, 5),
                 "dip_db": round(meta["dip_db"], 2),
                 "refined": meta["refined"]},
        "s31_single_freq_db": {
            str(f0): round(_s_db_at(f, s31, f0), 2) for f0 in f0_list},
        "deep_null_neighborhood_db": {
            f"hw{hw * 1000:.0f}MHz": round(deep_null_neighborhood_db(
                f, s31_db, *search_band, hw), 2) for hw in half_windows},
        "band_power_avg_db": {
            f"pm{hw * 1000:.0f}MHz_around_f_null": round(
                band_power_avg_db(f, s31_db,
                                  f_dip - hw, f_dip + hw), 2)
            for hw in half_windows},
    }
    return entry


def run_ratrace_null_tier(outdir: Path,
                          files: dict[str, tuple[str, Any]],
                          f0_anchor: float = 2.465) -> Path:
    """③ 归档双引擎 ratrace 数据的判据对照（零真机）。

    files: 引擎名 → (归档 .s4p 路径, f0 候选表)。跨引擎对照以
    f0_anchor（HFSS 仲裁中心 2.465GHz）为锚：单频判读差（两引擎在同一
    固定频点的 |S31| 差，零点频率网格漂移直接进读数——wp39 基线
    ratrace +11.01% 劣化的敏感性来源）vs 邻域/带宽积分判读差（判读
    不随零点在带内漂移而变化）。收窄比=数字如实记录，不预设结论。
    """
    f0_list = sorted({2.45, 2.465, 2.5, float(f0_anchor)})
    half_windows = [0.01, 0.025, 0.05]
    entries = {name: analyze_null_file(Path(p), f0_list,
                                       RATRACE_NULL_SEARCH, half_windows)
               for name, (p, _f0) in files.items()}
    cross: dict[str, Any] = {}
    if len(entries) == 2:
        (_n1, e1), (_n2, e2) = list(entries.items())
        anchor_key = f"{float(f0_anchor):g}"
        s1 = e1["s31_single_freq_db"].get(anchor_key)
        s2 = e2["s31_single_freq_db"].get(anchor_key)
        if s1 is not None and s2 is not None:
            cross["fixed_f0_ghz"] = float(f0_anchor)
            cross["fixed_f0_delta_db"] = round(abs(float(s1) - float(s2)), 2)
        hw = "hw25MHz"
        cross[f"neighborhood_{hw}_delta_db"] = round(abs(
            e1["deep_null_neighborhood_db"][hw]
            - e2["deep_null_neighborhood_db"][hw]), 2)
        cross["null_freq_delta_mhz"] = round(abs(
            e1["null"]["f_null_ghz"] - e2["null"]["f_null_ghz"]) * 1000, 2)
        cross["robustness_ratio"] = (
            None
            if not cross.get("fixed_f0_delta_db")
            else round(cross["fixed_f0_delta_db"]
                       / max(cross[f"neighborhood_{hw}_delta_db"], 0.05),
                       1))
        cross["robustness_note"] = ("比值分母 0.05dB 下限（邻域差四舍五入"
                                    "到 0 时取下限，比值为下界）")
        cross["note"] = ("判据语义：fixed_f0 单频读数差 >> 邻域读数差 = "
                         "该指标对零点频率网格漂移的鲁棒性"
                         "（③ 立项动机的定量证据）")
    payload = {
        "schema": f"{SCHEMA}_ratrace_null_v1", "generated_at": _now(),
        "tier": "ratrace_null", "search_band_ghz": list(RATRACE_NULL_SEARCH),
        "f0_anchor_ghz": float(f0_anchor),
        "entries": entries, "cross_engine": cross,
        "context": "wp39 基线 ratrace sbo 劣化 +11.01%（单频谷深判据，"
                   "−40~−52dB 深零点对网格自适应敏感）——本对照为判据"
                   "替代档的归档数据证据（runs/ratrace_arbitration 与 "
                   "runs/ratrace_smoke/pt9）",
    }
    out = outdir / "ratrace_null.json"
    _write_json(out, payload)
    print(f"WP39_RATRACE_NULL_DONE cross={cross}", flush=True)
    return out


# ── ⑤ HFSS Optimetrics 原生 setup 补测 ───────────────────────────────────────

_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def count_eval_rows(csv_text: str) -> int | None:
    """保守计数 Optimetrics 导出 CSV 的评估行数（⑤ 提取梯次之一）。

    契约：首行表头 + 数据行，各数据行字段数一致且 ≥2 才计数；解析
    不出一致结构返回 None（绝不猜）。"""
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    widths = {len(ln.split(",")) for ln in lines[1:]}
    if len(widths) != 1:
        return None
    width = widths.pop()
    if width < 2 or len(lines[0].split(",")) != width:
        return None
    return len(lines) - 1


_PROFILE_ROW_RE = re.compile(
    r"\n\tp\(([-\d.e+]+), ([-\d.e+]+), '', '([^']*)', ([-\d.e+]+)\)")


def parse_optimetrics_profile(path: Path) -> dict[str, Any]:
    """解析 Optimetrics 求解 profile（``opti*.profile``）的评估轨迹（⑤
    实际评估数的权威来源——COM 导出在 gRPC 桌面下不可用，真机实证）。

    每行 ``p(<t0>, <t1>, '', '<machine>', <W 内部 SI 值>)`` 计一次评估；
    返回 n_evals/变量轨迹（mm）/每评估间隔（原始 timestamp 单位，AEDT
    内部时基，不做单位换算假设）。"""
    txt = path.read_text(encoding="utf-8", errors="replace")
    rows = _PROFILE_ROW_RE.findall(txt)
    if not rows:
        return {"n_evals": None, "note": f"无 p() 评估行: {path}"}
    return {
        "n_evals": len(rows),
        "w_trajectory_mm": [round(float(r[3]) * 1000.0, 5) for r in rows],
        "per_eval_dt_raw": [round(float(r[1]) - float(r[0]), 1)
                            for r in rows],
        "profile": str(path),
    }


def _extract_native_results(h: Any, setup_name: str, workdir: Path,
                            outdir: Path) -> dict[str, Any]:
    """评估数提取梯次（⑤，best-effort #105）：Optimetrics 求解 profile
    （权威，零 COM）→ 子对象树 → COM 导出 → 全部失败如实 null。"""
    ladder: dict[str, Any] = {"source": None, "n_evals": None, "attempts": []}

    def try_step(name: str, fn: Callable[[], Any]) -> Any:
        try:
            value = fn()
            ladder["attempts"].append({"step": name, "ok": True})
            return value
        except Exception as exc:
            ladder["attempts"].append({"step": name, "ok": False,
                                       "error": repr(exc)[:300]})
            return None

    # 梯次 1：Optimetrics 求解 profile（gRPC 桌面下 COM 导出不可用的
    # 真机实证替代——profile 落盘于 .aedtresults，零桌面可解析）
    profiles = sorted((workdir / "mline.aedtresults").glob("opti*.profile")) \
        if (workdir / "mline.aedtresults").exists() else []
    if profiles:
        parsed = try_step("opti_profile",
                          lambda: parse_optimetrics_profile(profiles[0]))
        if parsed and parsed.get("n_evals"):
            ladder.update(parsed)
            ladder["source"] = "opti_profile"
            return ladder

    # 梯次 2：Optimetrics setup 子对象树属性（含 evaluation/iteration 字样）
    def walk_child_props() -> dict[str, Any] | None:
        co = h.odesign.GetChildObject("Optimetrics")
        if setup_name not in (co.GetChildNames() or []):
            return None
        child = co.GetChildObject(setup_name)
        found: dict[str, Any] = {}
        for run in (child.GetChildNames() or []):
            sub = child.GetChildObject(run)
            for prop in (sub.GetPropNames() or []):
                lname = str(prop).lower()
                if any(k in lname for k in
                       ("evaluat", "iteration", "simulation")):
                    found[f"{run}.{prop}"] = str(sub.GetPropValue(prop))
        return found or None

    props = try_step("child_object_props", walk_child_props)
    if props:
        ladder["child_props"] = props
        for key, val in props.items():
            m = _NUM_RE.search(str(val))
            if m and ladder["n_evals"] is None:
                ladder["n_evals"] = int(float(m.group()))
                ladder["source"] = f"child_props:{key}"

    # 梯次 3：COM 导出 CSV → count_eval_rows（gRPC 桌面实测不可用）
    csv_path = outdir / "native_optimetrics_export.csv"
    if ladder["n_evals"] is None:
        def export_csv() -> bool:
            return bool(h.ooptimetrics.ExportOptimetricsResults(
                setup_name, str(csv_path)))

        if try_step("export_optimetrics_csv", export_csv) and \
                csv_path.exists():
            text = csv_path.read_text(encoding="utf-8", errors="replace")
            ladder["export_csv_head"] = text[:2000]
            n = try_step("count_eval_rows", lambda: count_eval_rows(text))
            if n:
                ladder["n_evals"] = n
                ladder["source"] = "export_csv_rows"
    return ladder


def run_native_tier(outdir: Path, budget_anchor: int,
                    goal_db: float) -> Path:
    """⑤ 原生 Optimetrics setup（PyAEDT optimizations.add）补测。

    口径：Pattern Search 原生优化器 + 目标 dB(S11)≤goal_db（不可达深
    阈——同 sbo_objectives 的"无平台"语义，逼真搜索不早停）+
    MaxNumIteration=budget_anchor（无法硬帽评估数——迭代锚点，实际
    评估数按提取梯次如实记录）。结束design 变量停在最优点
    （UpdateDesignWhenDone 默认 True）→ 回代同一 HfssEvaluator 导出
    链取指标（仲裁评估，独立记账）。
    """
    import wp39_benchmark_run as runner

    problem = runner.PROBLEMS["mline"]
    outdir.mkdir(parents=True, exist_ok=True)
    workdir = outdir / f"_work_{problem.name}__native"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    runner._kill_desktops()
    evaluator = runner.HfssEvaluator(problem, workdir)
    calc = "dB(S(P1sheetP,P1sheetP))"
    payload: dict[str, Any] = {
        "schema": f"{SCHEMA}_native_v1", "generated_at": _now(),
        "tier": "native", "problem": problem.name,
        "budget_anchor_iterations": budget_anchor,
        "goal_db": goal_db, "calculation": calc,
        "note": "⑤ 口径：原生 Optimetrics 无法硬帽评估数（followUp⑤"
                "原话）——MaxNumIteration 为迭代锚点，实际评估数如实提取",
    }
    try:
        evaluator.launch_and_build()
        h = evaluator.h
        opt = h.optimizations.add(
            calculation=calc, ranges={"Freq": "2.5GHz"}, variables=["W"],
            optimization_type="Optimization", condition="<=",
            goal_value=goal_db)
        if opt in (None, False):
            raise RuntimeError("optimizations.add 失败（见 HFSS 日志）")
        setup_name = opt.name
        # 变量 W 定义带 mm 量纲（#218 ③）——范围属性必须同单位串，
        # 裸浮点会被 AEDT 拒：'w' attributes unit type cannot be
        # different from the variable's definition（真机实证）
        h.activate_variable_optimization("W", "0.5mm", "2.0mm")
        opt.props["Optimizer"] = "Pattern Search"
        stop = opt.props.setdefault("AnalysisStopOptions", {})
        stop.update({
            "StopForNumIteration": True,
            "MaxNumIteration": int(budget_anchor),
            "StopForElapsTime": False,
            "StopForSlowImprovement": False,
            "StopForGrdTolerance": False,
        })
        opt.update()
        # 原生口径实证：从 design_properties 回读实际生效的优化器与停机项
        # （键匹配不可靠——PyAEDT 生成名与桌面内部名大小写/后缀可漂移，
        # 按 SetupType=OptiOptimization 扫描；真机实证）
        rb: dict[str, Any] = {}
        try:
            setups = h.design_properties["Optimetrics"]["OptimetricsSetups"]
            for key, data in setups.items():
                if isinstance(data, dict) \
                        and data.get("SetupType") == "OptiOptimization":
                    rb = {"setup_key": key,
                          "optimizer": data.get("Optimizer"),
                          "stop_options": data.get("AnalysisStopOptions"),
                          "variables": data.get("Variables"),
                          "goals": (data.get("Goals") or {}).get("Goal")}
                    break
            if not rb:
                rb = {"note": "无 OptiOptimization 节点",
                      "keys": list(setups.keys())[:10]}
        except Exception as exc:  # best-effort #105
            rb = {"error": repr(exc)[:300]}
        payload["props_readback"] = rb
        t0 = time.time()
        ok = bool(opt.analyze())
        payload["analyze_ok"] = ok
        payload["wall_s"] = {"optimization_s": round(time.time() - t0, 2)}
        w_star_raw = h["W"]
        m = _NUM_RE.search(str(w_star_raw) or "")
        w_star = float(m.group()) if m else None
        payload["best_var"] = {"raw": str(w_star_raw), "w_mm": w_star}
        if w_star is not None:
            t1 = time.time()
            metrics = evaluator.evaluate({"w_mm": w_star})
            payload["replay"] = {
                "params": {"w_mm": w_star}, "metrics": metrics,
                "wall_s": {"eval_s": round(time.time() - t1, 2)},
                "note": "回代同一 HfssEvaluator 导出链（仲裁评估，"
                        "独立记账，不在 Optimetrics 评估数内）"}
        payload["eval_count"] = _extract_native_results(
            h, setup_name, workdir, outdir)
    except Exception as exc:
        payload["error"] = repr(exc)
        payload["stage"] = "attempt_failed"
    finally:
        evaluator.close()
    out = outdir / "native.json"
    _write_json(out, payload)
    print(f"WP39_NATIVE_DONE "
          f"{'ok' if payload.get('analyze_ok') else 'FAILED'} "
          f"best_var={payload.get('best_var')} "
          f"replay={payload.get('replay', {}).get('metrics')} "
          f"n_evals={payload.get('eval_count', {}).get('n_evals')} "
          f"(source={payload.get('eval_count', {}).get('source')})",
          flush=True)
    return out


def run_native_extract_tier(outdir: Path) -> Path:
    """对既有 native 战役重提取（零重解）：profile 解析 + 诊断回读折入。

    用途：提取梯次修复后对已跑完的战役补提取评估数/原生口径实证——
    不重求解（结果目录与 .aedt 不动），更新 native.json 并注明来源。
    """
    native_path = outdir / "native.json"
    payload = json.loads(native_path.read_text(encoding="utf-8"))
    workdir = outdir / "_work_mline__native"
    probe_out = REPO / "_tmp_native_probe_out.json"
    ec = payload.get("eval_count") or {}
    profiles = sorted(
        (workdir / "mline.aedtresults").glob("opti*.profile")) \
        if (workdir / "mline.aedtresults").exists() else []
    if profiles:
        parsed = parse_optimetrics_profile(profiles[0])
        if parsed.get("n_evals"):
            parsed["source"] = "opti_profile"
            parsed["reextracted_at"] = _now()
            payload["eval_count"] = parsed
            ec = parsed
    if probe_out.exists():
        diag = json.loads(probe_out.read_text(encoding="utf-8"))
        setup_key = next((k.split(".")[1] for k in diag
                          if k.startswith("dp.") and k.endswith(".SetupType")),
                         None)
        rb = {"optimizer": diag.get(f"dp.{setup_key}.Optimizer"),
              "stop_options": diag.get(f"dp.{setup_key}.stop"),
              "setup_key": setup_key,
              "source": "diagnostic desktop readback "
                        "(_tmp_native_probe_out.json，本 tier 只读折入)"}
        if rb.get("optimizer"):
            payload["props_readback"] = rb
    _write_json(native_path, payload)
    print(f"WP39_NATIVE_EXTRACT n_evals={ec.get('n_evals')} "
          f"source={ec.get('source')} "
          f"optimizer={(payload.get('props_readback') or {}).get('optimizer')}",
          flush=True)
    return native_path


# ── ④ openEMS patch 单点扫频谷位标定 ─────────────────────────────────────────


def run_patch_calib_tier(outdir: Path,
                         freq_range: tuple[float, float],
                         hfss_probe_path: Path) -> Path:
    """④ 标定：openEMS patch 名义尺寸单点扫频 → f_dip·L 常数。

    对照参考：HFSS 归档 probe.s1p 离线复核（99.8）与 #190
    23 点战役定标值（76.8）；漂移比值 = 常数(HFSS)/常数(openEMS)——
    问题定义（f0/尺寸）必须按本引擎常数定标，否则目标落空（wp39
    首轮 patch 2.0GHz 目标盒内无谷的根因）。
    """
    import wp39_benchmark_run as runner
    from rfauto.adapters.em_solver_base import (
        EMSolverConfig,
        resolve_openems_exe,
    )
    from rfauto.adapters.openems_solver import OpenEMSSolver

    patch = runner.PROBLEMS["patch"]
    nominal = {"patch_len_mm": 40.0, "patch_w_mm": 45.0}
    if "feed_offset_mm" in patch.extra:
        nominal["feed_offset_mm"] = float(patch.extra["feed_offset_mm"])
    dim_mm = nominal["patch_len_mm"]
    workdir = outdir / "_work_patch_calib"
    workdir.mkdir(parents=True, exist_ok=True)
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(workdir), freq_range_ghz=tuple(freq_range),
        mesh_resolution_mm=0.0,
        extra_params={"solve_timeout_s": 7200}))
    if not solver.connect():
        raise RuntimeError("openEMS 不可用")
    ok = solver.build_geometry({"template": "patch", "params": nominal})
    if not ok:
        raise RuntimeError("openEMS patch 构建失败")
    t0 = time.time()
    result = solver.solve()
    wall = time.time() - t0
    if not result.success:
        raise RuntimeError(f"openEMS patch 求解失败: {result.message}")
    s11_db = 20.0 * np.log10(np.abs(result.s_params[:, 0, 0]) + 1e-12)
    f_dip, meta = locate_dip_ghz(result.freq_ghz, s11_db)
    const = dip_constant(f_dip, dim_mm)
    hfss_entry: dict[str, Any] = {"path": str(hfss_probe_path),
                                  "available": hfss_probe_path.exists()}
    if hfss_entry["available"]:
        import skrf

        net = skrf.Network(str(hfss_probe_path))
        hf_f = net.f / 1e9
        hf_db = 20.0 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12)
        hf_dip, hf_meta = locate_dip_ghz(hf_f, hf_db)
        hfss_entry.update({
            "f_dip_ghz": round(hf_dip, 5),
            "constant": round(dip_constant(hf_dip, dim_mm), 2),
            "dip_db": round(hf_meta["dip_db"], 2),
            "source": "归档真机数据离线复核"})
    hfss_const = hfss_entry.get("constant")
    # DP-3 第二批改道：参考常数改经锚注册表按引擎对解析（失败回退字面值，
    # 值逐位同——单源换锚后报告/漂移口径自动跟随注册表，无需改脚本）。
    doc_const = _resolve_patch_constant(
        "patch.f_dip_l.openems-v1", OPENEMS_PATCH_CONSTANT_DOC)
    hfss_ref_const = _resolve_patch_constant(
        "patch.f_dip_l.hfss-v1", HFSS_PATCH_CONSTANT_REF)
    payload = {
        "schema": f"{SCHEMA}_patch_calib_v1", "generated_at": _now(),
        "tier": "patch_calib",
        "nominal_params": nominal,
        "freq_range_ghz": list(freq_range),
        "openems": {"f_dip_ghz": round(f_dip, 5),
                    "constant": round(const, 2),
                    "dip_db": round(meta["dip_db"], 2),
                    "refined": meta["refined"],
                    "n_points": meta["n_points"],
                    "wall_s": round(wall, 1),
                    "freq_span_ghz": [round(float(result.freq_ghz.min()), 3),
                                      round(float(result.freq_ghz.max()), 3)]},
        "hfss": hfss_entry,
        "references": {
            "openems_doc_constant": doc_const,
            "openems_doc_source": "#190 23 点战役定标",
            "hfss_ref_constant": hfss_ref_const},
        "drift": {
            "hfss_over_openems": (
                None if not hfss_const
                else round(float(hfss_const) / const, 4)),
            "fresh_vs_doc_pct": round(
                (const - doc_const)
                / doc_const * 100, 2),
            "recenter_example": {
                "target_ghz": 2.45,
                "L_star_mm": round(
                    recenter_length_for_target(2.45, const), 3),
                "note": "按本引擎常数定标 2.45GHz 目标所需 patch_len"}},
    }
    out = outdir / "patch_calib.json"
    _write_json(out, payload)
    print(f"WP39_PATCH_CALIB_DONE const={const:.2f}GHz·mm "
          f"(doc {doc_const}, hfss {hfss_ref_const}) "
          f"drift={payload['drift']['recenter_example']['L_star_mm']}mm@2.45",
          flush=True)
    return out


# ── ② optiSLang MOP 可用性探测 ───────────────────────────────────────────────


def probe_optislang(scan_roots: list[str] | None = None) -> dict[str, Any]:
    """② 超额线基线（optiSLang MOP）可用性探测（零真机，只读）。

    检查面：python 桥 ansys-optislang-core、PATH 上的 optislang 可执行、
    常见 Ansys 安装根下的 optiSLang 目录。全不可用 → available=False，
    MOP 对照档如实记 NOT_RUN（不占冒名数字）。
    """
    roots = scan_roots or [
        r"E:\ANSYSINC", r"C:\Program Files\ANSYS Inc",
        r"E:\Program Files\ANSYS Inc",
    ]
    checks: dict[str, Any] = {}

    try:
        import ansys.optislang.core  # noqa: F401

        checks["python_bridge"] = {
            "available": True, "pkg": "ansys-optislang-core"}
    except Exception as exc:
        checks["python_bridge"] = {"available": False,
                                   "error": repr(exc)[:200]}
    exe = shutil.which("optislang") or shutil.which("optiSLang")
    checks["path_exe"] = {"available": bool(exe), "path": exe}
    dirs: list[str] = []
    for root in roots:
        rp = Path(root)
        if not rp.exists():
            continue
        try:
            for child in rp.iterdir():
                if "optislang" in child.name.lower():
                    dirs.append(str(child))
                if child.is_dir():
                    for sub in child.iterdir():
                        if "optislang" in sub.name.lower():
                            dirs.append(str(sub))
        except Exception as exc:
            checks.setdefault("scan_errors", []).append(
                f"{root}: {exc!r}"[:200])
    checks["install_dirs"] = {"available": bool(dirs), "dirs": dirs[:10]}
    available = (checks["python_bridge"]["available"]
                 or checks["path_exe"]["available"]
                 or checks["install_dirs"]["available"])
    return {
        "schema": f"{SCHEMA}_optislang_probe_v1",
        "generated_at": _now(), "tier": "optislang_probe",
        "available": available, "checks": checks,
        "code_fact": "PyAEDT OptimizationSetups 支持 optimization_type="
                     "'optiSLang'（design_xploration.py SetupType 白名单），"
                     "但创建/运行需要本机 optiSLang 求解器与 license",
        "conclusion": (
            "超额线可补测：需另立增量接 MOP study"
            if available else
            "optiSLang 本机不可用（license/链路未接，与 followUp② "
            "预判一致）——MOP 对照档如实 NOT_RUN，不占冒名数字"),
    }


# ── 换判据档（wp39-factory-verdict-next）─────────────────────────
#
# 归因（子项 A，NEXT_OUTDIR/attribution_mline_s11_pseudofloor.md）：mline
# |S11| 地貌被 MSLPort 端口级伪底主导（加密网格不消），β→εeff 地貌物理
# 且随 w 单调——工厂换"引擎一致指标" |εeff−target|（openEMS β 抽取；
# HFSS 侧 S21 相位斜率抽取，同 setup 同抽取），judge_problem_pair 唯一裁判。


def _guard_next_outdir(outdir: Path) -> None:
    """换判据档只写新目录：禁止覆盖既有 FAIL 归档（#122）。"""
    for protected in (DEFAULT_OUTDIR, BASELINE_DIR):
        if outdir.resolve() == protected.resolve():
            raise RuntimeError(
                f"换判据档禁止写入既有归档 {protected}——请用 -outdir "
                f"{NEXT_OUTDIR}")


def hj_closed_form(w_mm: float) -> tuple[float, float]:
    """HJ 准静态闭式 (Z0, εeff)@2.5GHz（core/synthesis.forward_z0，副锚源）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup.from_materials_yaml(MLINE_STACKUP)
    z0, eps = forward_z0(float(w_mm), MLINE_F0_GHZ, stackup)
    return float(z0), float(eps)


def read_port_beta_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """模板 port_beta.csv（freq_hz, beta_rad_per_m）→ 两列数组。"""
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    if not rows:
        raise ValueError(f"port_beta.csv 空: {path}")
    bf = np.array([float(r[0]) for r in rows])
    bb = np.array([float(r[1]) for r in rows])
    return bf, bb


def make_openems_mline_eps_evaluator(
    *,
    mesh_mm: float,
    work_root: Path,
    freq_range: tuple[float, float] = FACTORY_BAND_GHZ,
    line_len_mm: float = 40.0,
    eps_target: float | None,
    log: list[dict[str, Any]] | None = None,
) -> Callable[[dict[str, float]], dict[str, float]]:
    """openEMS mline 换判据评估器：params→{eps_eff, s11_f0_db[, eps_eff_abs_err]}。

    εeff 由模板 CalcPort β（port_beta.csv）经 eps_eff_from_beta 抽取（金标准
    口径）；eps_target 给定时同时出 |εeff−target|（工厂目标）。**缓存显式
    关闭**（extra_params cache=False，#158 缓存秒回会伪造墙钟），并把
    cached 位写入 log 供档级断言。每参数点独立工作目录（#208 家族）。
    """
    def evaluate(params: dict[str, float]) -> dict[str, float]:
        from rfauto.adapters.em_solver_base import (
            EMSolverConfig,
            resolve_openems_exe,
        )
        from rfauto.adapters.openems_solver import OpenEMSSolver

        w = float(params["w_mm"])
        tag = f"w{w:.4f}_L{line_len_mm:.1f}"
        work = work_root / tag
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type="openems", exe_path=resolve_openems_exe(),
            working_dir=str(work), freq_range_ghz=tuple(freq_range),
            mesh_resolution_mm=float(mesh_mm),
            extra_params={"solve_timeout_s": 3600, "cache": False}))
        if not solver.connect():
            raise RuntimeError("openEMS 不可用（resolve_openems_exe）")
        ok = solver.build_geometry({
            "template": "mline",
            "params": {"w_mm": w, "line_len_mm": float(line_len_mm)}})
        if not ok:
            raise RuntimeError("openEMS 构建几何失败")
        t0 = time.time()
        result = solver.solve()
        wall = time.time() - t0
        if not result.success:
            raise RuntimeError(f"openEMS 求解失败: {result.message}")
        cached = "缓存复用" in (result.message or "")
        bf, bb = read_port_beta_csv(work / "port_beta.csv")
        eps, f_med = eps_eff_from_beta(bf, bb, MLINE_F0_GHZ * 1e9)
        s11 = _s_db_at(result.freq_ghz, result.s_params[:, 0, 0],
                       MLINE_F0_GHZ)
        metrics: dict[str, float] = {"eps_eff": float(eps),
                                     "s11_f0_db": float(s11)}
        if eps_target is not None:
            metrics["eps_eff_abs_err"] = eps_eff_error_metric(eps, eps_target)
        if log is not None:
            log.append({"params": {"w_mm": w}, "mesh_mm": mesh_mm,
                        "line_len_mm": line_len_mm,
                        "eps_eff": round(float(eps), 6),
                        "beta_f_med_ghz": round(f_med / 1e9, 5),
                        "eps_eff_abs_err": (None if eps_target is None
                                            else round(metrics["eps_eff_abs_err"], 6)),
                        "s11_f0_db": round(float(s11), 4),
                        "solve_s": round(wall, 2), "cached": cached})
        print(f"[factory-eps-eval] mesh={mesh_mm} w={w:.4f} eps={eps:.5f} "
              f"err={metrics.get('eps_eff_abs_err')} s11@2.5={s11:.2f}dB "
              f"solve={wall:.1f}s cached={cached}", flush=True)
        return metrics

    return evaluate


def run_probe_eps_tier(outdir: Path, meshes: list[float],
                       w_list: list[float],
                       freq_range: tuple[float, float]) -> Path:
    """probe_eps：候选网格 × 3 点 w 的 εeff 地貌 → 健康门 → 取最快网格。

    门=service mline_landscape_health_gate（副锚：名义点对 HJ |Δ|≤3% ∧
    εeff 随 w 单调），替代旧 |S11| 内联门；入选网格的名义点 εeff 即
    工厂 target（④ 纪律：问题定义前先在本引擎标定）。某网格任一点求解
    失败 → 该网格 ok=False 如实记录、不参与选型。
    """
    _guard_next_outdir(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    work_root = outdir / "_work_probe_eps"
    _, eps_hj_nom = hj_closed_form(MLINE_NOMINAL_W)
    hj_table = {w: hj_closed_form(w) for w in w_list}
    eval_log: list[dict[str, Any]] = []
    configs: list[dict[str, Any]] = []
    for mesh in meshes:
        evaluate = make_openems_mline_eps_evaluator(
            mesh_mm=mesh, work_root=work_root / f"m{mesh}",
            freq_range=freq_range, eps_target=None, log=eval_log)
        pts: list[dict[str, Any]] = []
        failed: dict[str, Any] | None = None
        for w in w_list:
            t0 = time.time()
            try:
                m = evaluate({"w_mm": w})
            except Exception as exc:
                failed = {"w_mm": w, "error": repr(exc)[:400]}
                print(f"[probe-eps] mesh={mesh} w={w} FAIL {exc!r}",
                      flush=True)
                break
            z0_hj, eps_hj = hj_table[w]
            pts.append({"w_mm": w, "eps_eff": round(m["eps_eff"], 6),
                        "eps_hj": round(eps_hj, 6), "z0_hj_ohm": round(z0_hj, 3),
                        "delta_hj_pct": round((m["eps_eff"] / eps_hj - 1) * 100, 4),
                        "s11_f0_db": round(m["s11_f0_db"], 4),
                        "wall_s": round(time.time() - t0, 2)})
        cfg: dict[str, Any] = {"mesh_mm": mesh, "points": pts,
                               "ok": failed is None, "failed": failed}
        if failed is None:
            gate = mline_landscape_health_gate(
                [p["w_mm"] for p in pts], [p["eps_eff"] for p in pts],
                nominal_w=MLINE_NOMINAL_W, eps_hj=eps_hj_nom)
            cfg["gate"] = gate
            cfg["median_wall_s"] = sorted(p["wall_s"] for p in pts)[len(pts) // 2]
            cfg["eps_eff_nominal"] = gate["eps_eff_nominal"]
            print(f"[probe-eps] mesh={mesh} gate={gate['verdict']} "
                  f"Δnom={gate['nominal_delta_hj_pct']:+.3f}% "
                  f"median_wall={cfg['median_wall_s']}s", flush=True)
        configs.append(cfg)
    passing = [c for c in configs
               if c["ok"] and c["gate"]["verdict"] == "PASS"]
    chosen: dict[str, Any] | None = None
    if passing:
        best = min(passing, key=lambda c: c["median_wall_s"])
        chosen = {"mesh_mm": best["mesh_mm"],
                  "eps_eff_target": best["eps_eff_nominal"],
                  "median_wall_s": best["median_wall_s"],
                  "rationale": "过 εeff 地貌健康门（副锚 ≤3% ∧ 单调）中单点"
                               "墙钟最短；target=该网格名义点 εeff（④ 纪律）"}
    cached_any = any(bool(e.get("cached")) for e in eval_log)
    payload = {
        "schema": f"{SCHEMA}_probe_eps_v1", "generated_at": _now(),
        "tier": "probe_eps", "freq_range_ghz": list(freq_range),
        "w_list": w_list, "meshes": meshes, "nominal_w": MLINE_NOMINAL_W,
        "eps_hj_nominal": round(eps_hj_nom, 6), "stackup": MLINE_STACKUP,
        "gate_criteria": {"sub_anchor_abs_pct_le": 3.0,
                          "monotonic": "increasing",
                          "kernel": "service/wp39_benchmark."
                                    "mline_landscape_health_gate"},
        "configs": configs, "eval_log": eval_log, "chosen": chosen,
        "cache_disabled": True, "cached_any": cached_any,
        "attribution": str(outdir / "attribution_mline_s11_pseudofloor.md"),
        "verdict": "PASS" if chosen else "FAIL（无网格通过 εeff 地貌健康门）",
    }
    out = outdir / "probe_eps.json"
    _write_json(out, payload)
    print(f"WP39_PROBE_EPS_{payload['verdict']} chosen={chosen}", flush=True)
    return out


def run_factory_eps_tier(outdir: Path, budget: int, seed: int,
                         freq_range: tuple[float, float],
                         mesh_override: float | None = None) -> Path:
    """factory_eps：openEMS 工厂 sbo 环（run_surrogate_loop 同内核同配置），
    目标 |εeff−target|，target/网格取自 probe_eps.json（④ 纪律）。

    stagnation 容差随指标量纲（runner.sbo_tol_abs：εeff 误差 0.003 而非
    0.25dB——套 dB 容差会首轮判停）。缓存显式关闭 + 档级断言 eval_log
    cached 全 False（#158），否则本档判废不落 best。
    """
    _guard_next_outdir(outdir)
    import wp39_benchmark_run as runner
    from rfauto.optimization.surrogate_loop import run_surrogate_loop

    problem = runner.PROBLEMS["mline_eps"]
    probe_path = outdir / "probe_eps.json"
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    chosen = probe.get("chosen")
    if not chosen:
        raise RuntimeError("probe_eps 无入选网格（地貌门 FAIL）——工厂不开跑"
                           "（④ 纪律：问题定义前先标定）")
    mesh = float(mesh_override) if mesh_override else float(chosen["mesh_mm"])
    cfg = next((c for c in probe["configs"]
                if abs(float(c["mesh_mm"]) - mesh) < 1e-9 and c.get("ok")), None)
    if cfg is None or "eps_eff_nominal" not in cfg:
        raise RuntimeError(f"probe_eps 无网格 {mesh} 的名义点 εeff，无法定 target")
    eps_target = float(cfg["eps_eff_nominal"])
    eval_log: list[dict[str, Any]] = []
    evaluate = make_openems_mline_eps_evaluator(
        mesh_mm=mesh, work_root=outdir / "_work_factory_eps",
        freq_range=freq_range, eps_target=eps_target, log=eval_log)
    t0 = time.time()
    kernel = run_surrogate_loop(
        problem.bounds, sbo_objectives(problem.metric_name), evaluate,
        n_init=problem.n_init, top_k=runner.SBO_TOP_K,
        virtual_trials=runner.SBO_VIRTUAL_TRIALS, max_real=budget,
        tol_abs=runner.sbo_tol_abs(problem), tol_rounds=runner.SBO_TOL_ROUNDS,
        surrogate_kind="smt_kriging", seed=seed)
    elapsed = time.time() - t0
    cached_any = any(bool(e.get("cached")) for e in eval_log)
    best = kernel.get("best")
    payload = {
        "schema": f"{SCHEMA}_factory_eps_v1", "generated_at": _now(),
        "tier": "factory_eps", "problem": problem.name,
        "engine_impl": ("openEMS 数据工厂换判据：run_surrogate_loop 同内核"
                        "（smt_kriging GP + 2000 虚拟寻优 top-K 真跑），"
                        "evaluator=openEMS mline 模板 β→εeff"),
        "budget": budget, "seed": seed,
        "metric_name": problem.metric_name,
        "metric_semantics": problem.metric_desc + problem.metric_semantics_note,
        "eps_eff_target": eps_target,
        "eps_target_source": f"probe_eps.json mesh={mesh} 名义点 εeff（④）",
        "evaluator_meta": {
            "template": "mline", "line_len_mm": 40.0,
            "freq_range_ghz": list(freq_range), "mesh_mm": mesh,
            "beta_window_frac": 0.04,
            "substrate": "rfauto_m366 (er=3.66 h=0.508 tan_d=0.0037)",
            "sbo_tol_abs": runner.sbo_tol_abs(problem),
            "note": "openEMS 全机单跑纪律：评估严格串行；缓存关闭"},
        "best": None if best is None else {
            "params": best["params"], "metrics": best["metrics"],
            "cost": best["cost"]},
        "n_evals": kernel["n_attempts"], "n_failures": kernel["n_failures"],
        "stop_reason": kernel["stop_reason"],
        "real_cost_trace": kernel["real_cost_trace"],
        "rounds": kernel["rounds"], "eval_log": eval_log,
        "wall_s": {"optimization_s": round(elapsed, 2)},
        "elapsed_s": round(elapsed, 2),
        "cache_disabled": True, "cached_any": cached_any,
        "params_meta": {"bounds": {k: list(v)
                                   for k, v in problem.bounds.items()}},
    }
    if cached_any:
        # #158：缓存秒回伪造墙钟——本档判废，best 不得进入判定
        payload["best"] = None
        payload["invalidated"] = "eval_log 出现 cached=True，墙钟无效，判废"
    out = outdir / "factory_eps.json"
    _write_json(out, payload)
    print(f"WP39_FACTORY_EPS_DONE best={payload['best']} "
          f"n_evals={payload['n_evals']} wall={elapsed:.1f}s "
          f"stop={kernel['stop_reason']} cached_any={cached_any}", flush=True)
    return out


def run_replay_eps_tier(outdir: Path, factory_json: Path,
                        baseline_json: Path) -> Path:
    """replay_eps：工厂最优 w 回代 HFSS mline_eps 评估器（同 sweep setup、同
    S21 相位抽取），target 取基线战役 JSON 的 calibration（保证基线臂与回代
    同一 HFSS target）；基线无 calibration 时自标定并如实标注降级。判定对
    mline_eps__pattern_search 新基线（judge_problem_pair 唯一裁判）。
    """
    _guard_next_outdir(outdir)
    import wp39_benchmark_run as runner

    factory = json.loads(factory_json.read_text(encoding="utf-8"))
    if not factory.get("best"):
        raise RuntimeError("工厂战役无 best（判废或全评估失败），不回代")
    best_params = factory["best"]["params"]
    baseline = json.loads(baseline_json.read_text(encoding="utf-8"))
    problem = runner.PROBLEMS["mline_eps"]
    target = (baseline.get("calibration") or {}).get("eps_eff_target")
    target_source = "baseline_calibration（与基线臂同一 HFSS target）"
    outdir.mkdir(parents=True, exist_ok=True)
    workdir = outdir / f"_work_{problem.name}__hfss_replay"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    runner._kill_desktops()
    evaluator = runner.HfssEvaluator(problem, workdir)
    replay: dict[str, Any] = {}
    try:
        evaluator.launch_and_build()
        if target is None:
            cal = evaluator.calibrate()
            target = cal["eps_eff_target"]
            target_source = ("replay_self_calibration（基线 JSON 无 "
                             "calibration，如实降级：两臂 target 非同一次解）")
        else:
            runner.EPS_TARGET[problem.name] = float(target)
        t0 = time.time()
        metrics = evaluator.evaluate(
            {k: float(v) for k, v in best_params.items()})
        replay = {
            "params": best_params, "metrics": metrics, "n_evals": 1,
            "eps_eff_target_hfss": float(target),
            "eps_target_source": target_source,
            "wall_s": {"eval_s": round(time.time() - t0, 2),
                       "launch_s": round(evaluator.launch_s, 2),
                       "build_s": round(evaluator.build_s, 2)},
        }
        print(f"[replay-eps] HFSS 回代 {best_params} -> {metrics} "
              f"(target {target:.5f})", flush=True)
    finally:
        evaluator.close()
    merged = merge_factory_with_replay(
        factory, replay, metric_name=problem.metric_name)
    verdict = judge_problem_pair(baseline, merged)
    payload = {
        "schema": f"{SCHEMA}_replay_eps_v1", "generated_at": _now(),
        "tier": "replay_eps", "factory_json": str(factory_json),
        "baseline_json": str(baseline_json), "replay": replay,
        "merged_candidate": merged, "verdict": verdict,
        "metric_semantics": problem.metric_desc + problem.metric_semantics_note,
    }
    out = outdir / "replay_eps.json"
    _write_json(out, payload)
    print(f"WP39_FACTORY_EPS_VERDICT {verdict['verdict']} "
          f"ratio={verdict['wallclock_ratio']} "
          f"deg%={verdict['degradation_pct']} "
          f"reasons={verdict['reasons']}", flush=True)
    return out


def native_campaign_view(native: dict[str, Any]) -> dict[str, Any]:
    """native.json（⑤ 原生 Optimetrics）→ judge_problem_pair candidate 形状。

    best.metric 取回代同一 HfssEvaluator 的 s11_f0_db；n_evals 取提取梯次
    的 n_evals（提取不到如实 None，judge 记账按 0——同时在 view 里标
    n_evals_extracted=None 供读表）；wall 取 Optimetrics analyze 墙钟。
    """
    bv = native.get("best_var") or {}
    rp = (native.get("replay") or {}).get("metrics") or {}
    metric = rp.get("s11_f0_db")
    n_evals = (native.get("eval_count") or {}).get("n_evals")
    return {
        "problem": "mline", "engine": "native_optimetrics",
        "best": None if metric is None else {
            "params": {"w_mm": bv.get("w_mm")},
            "metric": float(metric), "cost": None},
        "n_evals": n_evals, "n_evals_extracted": n_evals,
        "n_evals_source": (native.get("eval_count") or {}).get("source"),
        "wall_s": {"optimization_s": float(
            (native.get("wall_s") or {}).get("optimization_s") or 0.0)},
        "optimizer_readback": (native.get("props_readback") or {}).get(
            "optimizer"),
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    return (json.loads(path.read_text(encoding="utf-8"))
            if path.exists() else None)


def run_summary_next_tier(outdir: Path,
                          followup_dir: Path = DEFAULT_OUTDIR,
                          baseline_dir: Path = BASELINE_DIR) -> Path:
    """summary_next：换判据战役汇总（子项 E）。

    判定项（本战役 overall 口径）：mline_eps_factory（replay_eps.json 的
    judge）与 ratrace_null（两臂同 sweep 战役 judge_problem_pair）。
    决策输入（不进 overall，④ 口径决策归主控）：native_vs_scripted_mline
    —— ⑤ 原生 Optimetrics native.json 对 scripted pattern_search 基线的
    judge。② optiSLang MOP 维持 NOT_RUN（optislang_probe available=False）。
    """
    _guard_next_outdir(outdir)
    verdicts: dict[str, dict[str, Any]] = {}
    details: dict[str, Any] = {}

    rp = _load_json(outdir / "replay_eps.json")
    mline_base = _load_json(outdir / "mline_eps__pattern_search.json")
    if rp and rp.get("merged_candidate") and mline_base:
        # 汇总层从内核重判（基线 JSON × 回代合并 candidate），不抄 replay 档文本
        verdicts["mline_eps_factory"] = judge_problem_pair(
            mline_base, rp["merged_candidate"])
        details["mline_eps_factory"] = {
            "replay": rp.get("replay"),
            "merged_candidate": rp.get("merged_candidate"),
            "replay_tier_verdict": (rp.get("verdict") or {}).get("verdict")}
    elif rp and rp.get("verdict"):
        verdicts["mline_eps_factory"] = rp["verdict"]
        details["mline_eps_factory"] = {
            "replay": rp.get("replay"),
            "merged_candidate": rp.get("merged_candidate")}
    else:
        verdicts["mline_eps_factory"] = {
            "problem": "mline_eps", "verdict": "FAIL",
            "reasons": ["缺 replay_eps.json（工厂/回代未完成）"]}

    b = _load_json(outdir / "ratrace_null__pattern_search.json")
    c = _load_json(outdir / "ratrace_null__sbo.json")
    if b and c:
        verdicts["ratrace_null"] = judge_problem_pair(b, c)
        details["ratrace_null"] = {
            "baseline": {k: b.get(k) for k in ("best", "n_evals", "wall_s",
                                                "stop_reason")},
            "candidate": {k: c.get(k) for k in ("best", "n_evals", "wall_s",
                                                 "stop_reason")},
            "sweep": (b.get("hfss") or {}).get("setup")}
    else:
        verdicts["ratrace_null"] = {
            "problem": "ratrace_null", "verdict": "FAIL",
            "reasons": ["缺 ratrace_null 两臂战役 JSON"]}

    decision_inputs: dict[str, Any] = {}
    nb = _load_json(baseline_dir / "mline__pattern_search.json")
    nn = _load_json(followup_dir / "native.json")
    if nb and nn:
        view = native_campaign_view(nn)
        decision_inputs["native_vs_scripted_mline"] = {
            "verdict": judge_problem_pair(nb, view),
            "native_view": view,
            "scripted_baseline": {k: nb.get(k) for k in
                                  ("best", "n_evals", "wall_s")},
            "note": "④ 口径决策输入：原生 Optimetrics（同单频 setup、"
                    "|S11|@2.5 指标）对 scripted Pattern Search 基线的 "
                    "judge；决策归主控"}
    else:
        decision_inputs["native_vs_scripted_mline"] = {
            "verdict": None, "note": "缺 native.json 或 scripted 基线 JSON"}
    op = _load_json(followup_dir / "optislang_probe.json")
    decision_inputs["optislang_mop"] = {
        "status": "NOT_RUN",
        "available": None if op is None else op.get("available"),
        "note": "② 超额线：本机无 optiSLang/license（optislang_probe），"
                "如实 NOT_RUN 不占冒名数字"}

    probe = _load_json(outdir / "probe_eps.json")
    factory = _load_json(outdir / "factory_eps.json")
    summary = summarize_judgment(verdicts)
    payload = {
        "schema": f"{SCHEMA}_verdict_next_summary_v1",
        "generated_at": _now(), "outdir": str(outdir),
        "criteria": {"budget": 25, "wallclock_max_ratio": 0.5,
                     "cost_max_degradation_pct": 5.0,
                     "judge": "service/wp39_benchmark.judge_problem_pair"},
        "problems": verdicts, "summary": summary, "details": details,
        "decision_inputs": decision_inputs,
        "probe_eps": None if probe is None else {
            "verdict": probe.get("verdict"), "chosen": probe.get("chosen"),
            "eps_hj_nominal": probe.get("eps_hj_nominal"),
            "configs": [{"mesh_mm": cg.get("mesh_mm"), "ok": cg.get("ok"),
                         "gate": (cg.get("gate") or {}).get("verdict"),
                         "nominal_delta_hj_pct": (cg.get("gate") or {}).get(
                             "nominal_delta_hj_pct"),
                         "eps_eff": [p.get("eps_eff") for p in cg.get("points", [])],
                         "median_wall_s": cg.get("median_wall_s")}
                        for cg in probe.get("configs", [])]},
        "factory_eps": None if factory is None else {
            k: factory.get(k) for k in
            ("best", "n_evals", "n_failures", "stop_reason", "wall_s",
             "eps_eff_target", "cache_disabled", "cached_any", "invalidated")},
        "mline_eps_baseline": None if mline_base is None else {
            k: mline_base.get(k) for k in
            ("best", "n_evals", "wall_s", "stop_reason", "calibration",
             "stage")},
        "attribution": {
            "path": str(outdir / "attribution_mline_s11_pseudofloor.md"),
            "conclusion": "mline |S11| 地貌=MSLPort 端口级伪底（加密网格不消），"
                          "β→εeff 地貌物理且随 w 单调——工厂换引擎一致指标 "
                          "|εeff−target|"},
        "note": "overall 只计本战役两判定项；native_vs_scripted 与 "
                "optiSLang 为决策输入（④ 口径决策归主控）",
    }
    out = outdir / "summary.json"
    _write_json(out, payload)
    print(f"WP39_VERDICT_NEXT_{summary['overall']} "
          f"per_problem={summary['per_problem']}", flush=True)
    return out


# ── 汇总判定 ─────────────────────────────────────────────────────────────────


def run_judge_tier(outdir: Path) -> Path:
    tiers: dict[str, Any] = {}
    for name in ("probe", "factory", "replay", "ratrace_null", "native",
                 "patch_calib", "optislang_probe"):
        p = outdir / f"{name}.json"
        if not p.exists():
            tiers[name] = {"available": False}
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        entry: dict[str, Any] = {"available": True,
                                 "schema": data.get("schema")}
        if name == "replay":
            entry["factory_verdict"] = data.get("verdict")
        if name == "native":
            ec = data.get("eval_count") or {}
            entry["n_evals_extracted"] = ec.get("n_evals")
            entry["n_evals_source"] = ec.get("source")
            entry["best_var"] = data.get("best_var")
            entry["replay_metrics"] = (data.get("replay") or {}).get(
                "metrics")
        if name == "patch_calib":
            entry["openems_constant"] = data.get("openems", {}).get(
                "constant")
            entry["hfss_constant"] = data.get("hfss", {}).get("constant")
        if name == "probe":
            entry["chosen"] = data.get("chosen")
        tiers[name] = entry
    replay = tiers.get("replay") or {}
    factory_verdict = (replay.get("factory_verdict") or {}).get("verdict") \
        if replay.get("available") else None
    payload = {
        "schema": f"{SCHEMA}_summary_v1", "generated_at": _now(),
        "tiers": tiers,
        "factory_tier_verdict": factory_verdict,
        "note": "①档判定以 replay.json 的 judge_problem_pair 为准（唯一"
                "裁判内核 service/wp39_benchmark.judge_problem_pair）",
    }
    out = outdir / "followup_summary.json"
    _write_json(out, payload)
    print(f"WP39_FOLLOWUP_SUMMARY factory_verdict={factory_verdict}",
          flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-tier", required=True,
                    choices=["probe", "factory", "replay", "ratrace_null",
                             "native", "native_extract", "patch_calib",
                             "optislang_probe", "judge",
                             "probe_eps", "factory_eps", "replay_eps",
                             "summary_next"])
    ap.add_argument("-outdir", default=str(DEFAULT_OUTDIR))
    ap.add_argument("-mesh", type=float, default=None,
                    help="factory/probe 覆盖网格（默认 probe 选型/1.0）")
    ap.add_argument("-meshes", default=None,
                    help="probe_eps 候选网格逗号表（默认 1.2,2.0,3.0）")
    ap.add_argument("-budget", type=int, default=25)
    ap.add_argument("-seed", type=int, default=42)
    ap.add_argument("-anchor", type=int, default=25,
                    help="native MaxNumIteration 预算锚点")
    ap.add_argument("-goal-db", type=float, default=-80.0,
                    help="native 目标（不可达深阈，无平台语义）")
    ap.add_argument("-baseline", default=str(
        BASELINE_DIR / "mline__pattern_search.json"))
    ap.add_argument("-factory-json", default=None)
    # 绝对路径：HFSS 档的 Hfss(project=...) 相对路径会让 AEDT Rename 挂起（#140）
    outdir = Path(ap.parse_args().outdir).resolve()
    args = ap.parse_args()
    outdir.mkdir(parents=True, exist_ok=True)
    if args.tier == "probe":
        run_probe_tier(outdir, [1.2, 0.8], [0.85, 1.113, 1.4],
                       FACTORY_BAND_GHZ)
    elif args.tier == "factory":
        run_factory_tier(outdir, args.mesh or 1.0, args.budget, args.seed,
                         FACTORY_BAND_GHZ)
    elif args.tier == "replay":
        fj = (Path(args.factory_json) if args.factory_json
              else outdir / "factory.json")
        run_replay_tier(outdir, fj, Path(args.baseline))
    elif args.tier == "probe_eps":
        meshes = ([float(m) for m in args.meshes.split(",")]
                  if args.meshes else list(PROBE_EPS_MESHES))
        run_probe_eps_tier(outdir, meshes, list(PROBE_W_LIST),
                           FACTORY_BAND_GHZ)
    elif args.tier == "factory_eps":
        run_factory_eps_tier(outdir, args.budget, args.seed,
                             FACTORY_BAND_GHZ, mesh_override=args.mesh)
    elif args.tier == "replay_eps":
        fj = (Path(args.factory_json) if args.factory_json
              else outdir / "factory_eps.json")
        base = (Path(args.baseline)
                if args.baseline != str(BASELINE_DIR / "mline__pattern_search.json")
                else outdir / "mline_eps__pattern_search.json")
        run_replay_eps_tier(outdir, fj, base)
    elif args.tier == "summary_next":
        run_summary_next_tier(outdir)
    elif args.tier == "ratrace_null":
        run_ratrace_null_tier(outdir, {
            "hfss_arbitration": (
                str(REPO / "runs" / "ratrace_arbitration"
                    / "hfss_ratrace.s4p"), 2.465),
            "openems_pt9": (
                str(REPO / "runs" / "ratrace_smoke" / "pt9"
                    / "ratrace.s4p"), 2.5),
        })
    elif args.tier == "native":
        run_native_tier(outdir, args.anchor, args.goal_db)
    elif args.tier == "native_extract":
        run_native_extract_tier(outdir)
    elif args.tier == "patch_calib":
        run_patch_calib_tier(
            outdir, (1.5, 2.5),
            REPO / "runs" / "patch_hfss_probe" / "probe.s1p")
    elif args.tier == "optislang_probe":
        payload = probe_optislang()
        _write_json(outdir / "optislang_probe.json", payload)
        print(f"WP39_OPTISLANG_AVAILABLE={payload['available']}\n"
              f"{payload['conclusion']}", flush=True)
    elif args.tier == "judge":
        run_judge_tier(outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
