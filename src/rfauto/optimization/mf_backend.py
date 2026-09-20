"""Direction 1: Multi-fidelity optimization backend.

Two-phase approach:
  Phase 1: Coarse screening (fake/openEMS) -> Pareto candidates
  Phase 2: HFSS fine calculation (top-k by true exclusive Hypervolume
    contribution over the recipe objectives, explicit direction per key)
fidelity_delta.json tracks rank_flip_count as core diagnostic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.optimization.pareto_tools import exact_hypervolume

logger = logging.getLogger(__name__)

# objective op → 超体积方向（P1 修复：参与指标显式"键名+方向"，不再把
# metrics 全部数值键无方向当最小化）。MEAN_WITHIN 无单调方向语义，不支持。
_HV_OP_DIRECTION: dict[str, str] = {
    "max_below": "minimize",  # 带内统计量 ≤ 阈值：越小（越负）越好
    "min_above": "maximize",  # 带内统计量 ≥ 阈值：越大越好
    "bandwidth": "maximize",  # 达标带宽：越宽越好
}


def _hv_exact_min(pts: list[tuple[float, ...]], ref: tuple[float, ...]) -> float:
    """最小化口径的精确超体积（E9 迁入 pareto_tools.exact_hypervolume 公开化）。

    保留私有名作为兼容别名：hypervolume_contribution / select_top_k_by_hv
    的 31 测语义逐字节不变；新代码直接用 pareto_tools.exact_hypervolume。
    """
    return exact_hypervolume(pts, ref)


def hypervolume_contribution(
    points: list[dict[str, float]],
    objectives: dict[str, str],
    ref: dict[str, float] | None = None,
) -> list[float]:
    """真独占超体积贡献：contrib_i = HV(S) − HV(S∖{i})（k 小，精确可算）。

    口径（P1 修复：旧实现算的是单点盒体积 prod(ref−val)，被支配点也获得
    正份额）：objectives 显式给出参与指标与方向（{键名: "maximize"|
    "minimize"}）；内部统一转最小化（maximize 取负）后用 _hv_exact_min
    精确算全集与去点超体积。返回份额 = 独占贡献 / Σ独占贡献（和为 1；
    全 0——如全同点——时返回全 0）。被支配点的独占贡献恒 0。
    ref 缺省取各维（转换后）最差值 + max(1.0, 0.1·|最差值|)——旧
    max·1.1 对 dB 类负值指标会把参考点收进支配域、错误剔点。
    """
    if not points:
        return []
    if not objectives:
        raise ValueError("objectives 不能为空：须显式给出 {指标键: maximize|minimize}")
    for key, direction in objectives.items():
        if direction not in ("maximize", "minimize"):
            raise ValueError(f"方向仅支持 maximize/minimize: {key}={direction!r}")
    keys = list(objectives.keys())
    mat: list[list[float]] = []
    for p in points:
        missing = [k for k in keys if k not in p]
        if missing:
            raise ValueError(f"点缺指标键: {missing}")
        mat.append([float(p[k]) if objectives[k] == "minimize" else -float(p[k])
                    for k in keys])
    dim = len(keys)
    if ref is not None:
        missing = [k for k in keys if k not in ref]
        if missing:
            raise ValueError(f"ref 缺指标键: {missing}")
        ref_vec = [float(ref[k]) if objectives[k] == "minimize" else -float(ref[k])
                   for k in keys]
    else:
        ref_vec = []
        for c in range(dim):
            worst = max(row[c] for row in mat)
            ref_vec.append(worst + max(1.0, 0.1 * abs(worst)))
    tuples = [tuple(row) for row in mat]
    total_hv = _hv_exact_min(tuples, tuple(ref_vec))
    contribs = [
        max(0.0, total_hv - _hv_exact_min(tuples[:i] + tuples[i + 1:], tuple(ref_vec)))
        for i in range(len(tuples))
    ]
    s = sum(contribs)
    if s > 0:
        contribs = [c / s for c in contribs]
    return contribs


def select_top_k_by_hv(
    trials: list[dict[str, Any]],
    k: int = 5,
    *,
    objectives: dict[str, str] | None,
) -> list[dict[str, Any]]:
    """按真独占 HV 贡献选 Phase-2 精算候选（贡献并列保持原序，稳定排序）。

    objectives: {trial["metrics"] 键名: "maximize"|"minimize"}——显式传入；
    旧实现把 metrics 全部数值键无方向当最小化，诊断类指标会混入选点面、
    方向相反的指标会被选反。缺任一目标键（或非数值）的 trial 跳过。
    objectives=None（配方目标无可单调方向语义时的回退，#105）→ 旧口径按
    trial cost 升序取前 k。
    """
    if not trials:
        return []
    if not objectives:
        costed = [t for t in trials if isinstance(t.get("cost"), (int, float))
                  and not isinstance(t.get("cost"), bool)]
        costed.sort(key=lambda t: t["cost"])
        return costed[:k]
    scored = []
    for t in trials:
        metrics = t.get("metrics", {})
        objs: dict[str, float] = {}
        for mk in objectives:
            mv = metrics.get(mk)
            if not isinstance(mv, (int, float)) or isinstance(mv, bool):
                break
            objs[mk] = mv
        else:
            scored.append({**t, "_objectives": objs})
    if not scored:
        return []
    contributions = hypervolume_contribution(
        [s["_objectives"] for s in scored], objectives)
    for i, s in enumerate(scored):
        s["_hv_contribution"] = contributions[i]
    scored.sort(key=lambda x: x["_hv_contribution"], reverse=True)
    return scored[:k]


def _hv_objectives_from_recipe(recipe_data: dict[str, Any],
                               trials: list[dict[str, Any]]) -> dict[str, str]:
    """配方 objectives → select_top_k_by_hv 的 {指标键: 方向} 映射。

    指标键按 SpecEvaluator.metric_key_candidates 的 worst-case 优先序对
    trial metrics 实测解析（#195 口径）；op 无单调方向语义（MEAN_WITHIN）
    或产物键不在 metrics 中时抛 ValueError（调用方转 errors 如实上报）。
    """
    from rfauto.core.objectives import SpecEvaluator

    metric_keys: set[str] = set()
    for t in trials:
        for mk, mv in (t.get("metrics") or {}).items():
            if isinstance(mv, (int, float)) and not isinstance(mv, bool):
                metric_keys.add(mk)
    out: dict[str, str] = {}
    for obj in recipe_data.get("objectives") or []:
        metric = str(obj.get("metric", ""))
        raw_op = obj.get("op", "max_below")
        op = str(getattr(raw_op, "value", raw_op))
        direction = _HV_OP_DIRECTION.get(op)
        if direction is None:
            raise ValueError(
                f"objective op={op} 无单调超体积方向语义"
                f"（支持 max_below/min_above/bandwidth）")
        for key in SpecEvaluator.metric_key_candidates(metric, op):
            if key in metric_keys:
                out[key] = direction
                break
        else:
            raise ValueError(
                f"objective metric={metric} 的产物键不在 trial metrics 中"
                f"（实测键: {sorted(metric_keys)}）")
    if not out:
        raise ValueError("配方无 objectives，无法按超体积贡献选点")
    return out


def compute_fidelity_delta(low_trials, high_trials, freq_ghz=None, seed=42, solver_versions=None):
    low_map = {}
    for t in low_trials:
        low_map[json.dumps(t.get("params", {}), sort_keys=True)] = t
    matched = []
    for t in high_trials:
        k = json.dumps(t.get("params", {}), sort_keys=True)
        if k in low_map:
            matched.append((low_map[k], t))
    rank_flip = 0
    if len(matched) >= 2:
        lc = [p[0].get("cost", 0.0) for p in matched]
        hc = [p[1].get("cost", 0.0) for p in matched]
        for i in range(len(matched)):
            for j in range(i + 1, len(matched)):
                if (lc[i] < lc[j]) != (hc[i] < hc[j]):
                    rank_flip += 1
    deltas = []
    s11_low, s11_high = [], []
    for lt, ht in matched:
        sl = lt.get("metrics", {}).get("s11_db_max_in_band")
        sh = ht.get("metrics", {}).get("s11_db_max_in_band")
        if sl is not None and sh is not None:
            deltas.append(abs(sh - sl))
            s11_low.append(sl)
            s11_high.append(sh)
    # schema 对齐多保真通道：fidelity_delta.json 含 S11_low/S11_high
    return {"freq_ghz": freq_ghz or [], "s11_low": s11_low, "s11_high": s11_high,
            "abs_delta_db": deltas,
            "mean_abs_delta_db": float(np.mean(deltas)) if deltas else None,
            "rank_flip_count": rank_flip, "n_matched_pairs": len(matched),
            "seed": seed, "solver_versions": solver_versions or {}}


def run_multifidelity(recipe_path, *, adapter_low="fake", adapter_high="fake",
                      n_phase1=40, n_phase2=5, seed=42, resume=False):
    import optuna
    import yaml

    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir, load_solver_versions, record_run, snapshot_recipe, write_meta
    from rfauto.optimization.optimizer import get_storage_path, run_optimization

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"Recipe not found: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)
    run_id = generate_run_id()
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    snapshot_recipe(run_dir, recipe_data)
    t0 = time.time()

    # study 名：resume 模式下去 run_id 化（配方内容+适配器组合哈希）——
    # 同配方重跑挂同一个 study，已 COMPLETE 的 trial 不再重算（#148 教训：
    # 进程被杀 = 5×HFSS 精算全部重来）。非 resume 保持 run_id 名（隔离）。
    if resume:
        content = path.read_bytes()
        h1 = hashlib.sha256(content + adapter_low.encode()).hexdigest()[:8]
        h2 = hashlib.sha256(
            content + f"{adapter_low}+{adapter_high}+k{n_phase2}".encode()
        ).hexdigest()[:8]
        p1_study_name = f"mf_p1_{h1}"
        p2_study_name = f"mf_p2_{h2}"
        storage = get_storage_path()
        try:
            _pre = optuna.load_study(study_name=p1_study_name, storage=storage)
            p1_done = len([t for t in _pre.get_trials(deepcopy=False)
                           if t.state == optuna.trial.TrialState.COMPLETE])
        except (KeyError, ValueError):
            p1_done = 0
        eff_n1 = max(0, n_phase1 - p1_done)
    else:
        p1_study_name = f"mf_p1_{run_id[:8]}"
        p2_study_name = f"mf_p2_{run_id[:8]}"
        eff_n1 = n_phase1

    logger.info("Phase 1: %d trials (resume=%s), adapter=%s",
                eff_n1, resume, adapter_low)
    phase1 = run_optimization(str(path), adapter_name=adapter_low, max_trials=eff_n1,
                              study_name=p1_study_name, sampler="tpe")
    if not phase1.get("ok"):
        return {"ok": False, "errors": ["Phase 1 failed", *phase1.get("errors", [])]}

    study = optuna.load_study(study_name=phase1["study_name"], storage=phase1["storage"])
    all_trials = [{"params": dict(t.params), "cost": t.value, "metrics": t.user_attrs.get("metrics", {})}
                  for t in study.get_trials(deepcopy=False) if t.state == optuna.trial.TrialState.COMPLETE]
    try:
        hv_objectives = _hv_objectives_from_recipe(recipe_data, all_trials)
    except ValueError as exc:
        # 回退旧口径（按 cost 升序选点）：配方的 objectives 含无单调方向语义
        # 的 op（MEAN_WITHIN 等）或产物键缺失时，HV 选点不可用——降级不阻断
        # （#105：选点策略不可用≠战役不可跑；审查 P1 修复时的过严拒绝会打死
        # 标准配方如 wilkinson 的 mf 路径）。
        hv_objectives = None
        warnings_note = f"Phase 2 超体积选点目标解析失败，回退按 cost 升序选点: {exc}"
        print(f"[mf] {warnings_note}")
    else:
        warnings_note = None
    top_k = select_top_k_by_hv(all_trials, k=n_phase2, objectives=hv_objectives)
    # 选点策略审计（best-effort 落盘，#105）：HV 目标解析结果此前只喂
    # select_top_k_by_hv、降级仅留 result["warnings"]——fidelity_delta.json /
    # meta.metrics / 返回体三处均无"按什么策略、哪些键、哪个方向选的点"，
    # 选点不可复现。此处显式登记，三处同源写入。
    phase2_selection: dict[str, Any] = {
        "strategy": "hypervolume" if hv_objectives else "cost_ascending_fallback",
        "hv_objectives": dict(hv_objectives) if hv_objectives else None,
        "fallback_reason": warnings_note,
        "k": int(n_phase2),
    }

    # Phase 2 用 enqueue_trial 固定候选参数（早期审查修复——曾直接
    # run_optimization(max_trials=1) 不带候选参数，跑的是 TPE 新建议点，
    # 结果却挂候选名，fidelity_delta 配对失真）。enqueue 的固定参数由
    # study.optimize 消费，Phase 2 精算的就是 Phase 1 选出的那批点。
    # resume：候选参数已有 COMPLETE trial 的直接复用，不再 enqueue 重算。
    p2_study = optuna.create_study(study_name=p2_study_name, storage=phase1["storage"],
                                   direction="minimize", load_if_exists=True)
    p2_done = {json.dumps(dict(t.params), sort_keys=True): t
               for t in p2_study.get_trials(deepcopy=False)
               if t.state == optuna.trial.TrialState.COMPLETE}
    pending: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    for cand in top_k:
        key = json.dumps(dict(cand.get("params", {})), sort_keys=True)
        t = p2_done.get(key)
        if resume and t is not None:
            reused.append({"params": cand.get("params", {}), "cost": t.value,
                           "metrics": t.user_attrs.get("metrics", {})})
        else:
            pending.append(cand)
    for cand in pending:
        p2_study.enqueue_trial(dict(cand.get("params", {})))

    logger.info("Phase 2: %d candidates (enqueued) + %d reused, adapter=%s",
                len(pending), len(reused), adapter_high)
    p2 = {"ok": True}
    p2_new: list[dict[str, Any]] = []
    if pending:
        p2 = run_optimization(str(path), adapter_name=adapter_high, max_trials=len(pending),
                              study_name=p2_study_name, sampler="tpe")
        if p2.get("ok"):
            p2_study = optuna.load_study(study_name=p2_study_name, storage=phase1["storage"])
            p2_by_params = {json.dumps(dict(t.params), sort_keys=True): t
                            for t in p2_study.get_trials(deepcopy=False)
                            if t.state == optuna.trial.TrialState.COMPLETE}
            for cand in pending:
                key = json.dumps(dict(cand.get("params", {})), sort_keys=True)
                t = p2_by_params.get(key)
                if t is not None:
                    p2_new.append({"params": cand.get("params", {}), "cost": t.value,
                                   "metrics": t.user_attrs.get("metrics", {})})
    p2_results = reused + p2_new

    freq_r = recipe_data.get("setup", {}).get("freq_range_ghz", [1.5, 3.5])
    freq_ghz = list(np.linspace(freq_r[0], freq_r[1], 50))
    delta = compute_fidelity_delta(all_trials, p2_results, freq_ghz=freq_ghz, seed=seed,
                                   solver_versions=load_solver_versions())
    elapsed = time.time() - t0
    delta["phase2_selection"] = phase2_selection
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "results" / "fidelity_delta.json").write_text(json.dumps(delta, indent=2, default=str), encoding="utf-8")

    result = {"ok": True, "run_id": run_id, "run_dir": str(run_dir), "phase1": phase1,
              "phase2_results": p2_results, "fidelity_delta": delta, "hfss_count": len(p2_results),
              "hfss_count_pass": len(p2_results) <= max(15, n_phase1 * 0.3), "elapsed_s": round(elapsed, 1),
              "resume": bool(resume), "p2_reused": len(reused), "p2_recalculated": len(p2_new),
              "study_names": {"phase1": p1_study_name, "phase2": p2_study_name},
              "phase2_selection": phase2_selection}
    if warnings_note is not None:
        result["warnings"] = [warnings_note]
    write_meta(run_dir, {"run_id": run_id, "model": recipe_data.get("model", ""), "status": "done",
                         "adapter": f"mf:{adapter_low}+{adapter_high}", "algorithm": "multifidelity", "metrics": delta})
    record_run(Path("runs") / "index.db", {"run_id": run_id, "model": recipe_data.get("model", ""),
               "adapter": f"mf:{adapter_low}+{adapter_high}", "status": "done",
               "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "metrics": {"hfss_count": len(p2_results)}})
    return result
