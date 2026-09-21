"""Direction 1: Multi-fidelity optimization backend.

Two-phase approach:
  Phase 1: Coarse screening (fake/openEMS) -> Pareto candidates
  Phase 2: HFSS fine calculation (top-k by true exclusive Hypervolume
    contribution over the recipe objectives, explicit direction per key)
fidelity_delta.json tracks rank_flip_count as core diagnostic.
"""

from __future__ import annotations

import contextlib
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


def mf_study_names(recipe_path, *, adapter_low, adapter_high, n_phase2, seed):
    """稳定派生 mf 两阶段 study 名（#148 断点续跑：study 名去 run_id 化）。

    名字 = ``mf_p1_`` / ``mf_p2_`` + SHA-256(配方内容 + 适配器组合 + k(n_phase2)
    + seed) 前 10 位——**同配方同 adapter 同 seed 跨进程同名**：进程被杀后重跑
    挂回同一 study，已 COMPLETE 的 trial 不再重算（#148 教训：study 名含 run_id
    → 新进程起新 study → 5×HFSS 精算全部重来）。seed 会影响 TPE 轨迹（显式
    透传给 run_optimization），故纳入哈希输入——不同 seed 天然不同 study，
    名字本身即体现 seed 身份；完整哈希输入经返回 spec 记入 study user_attrs
    与 result["study_spec"]（"描述里体现"）。

    新旧语义边界（旧名 study 不迁移，历史资产零改写，新命名向前生效）：
    - 旧（2026-09-05 阶段 0.4）：仅 ``resume=True`` 时哈希命名（8 位、无 seed），
      否则 ``mf_p{1,2}_{run_id[:8]}``（每次调用隔离，续跑必然重算）；
    - 新：命名恒稳定派生（10 位、含 seed），与旧哈希输入不同故同名巧撞概率
      可忽略，旧 study 自然废弃而非被复用。
    """
    path = Path(recipe_path)
    content = path.read_bytes() if path.exists() else b""
    spec = {
        "recipe_sha256": hashlib.sha256(content).hexdigest(),
        "recipe_path": str(path),
        "adapters": f"{adapter_low}+{adapter_high}",
        "n_phase2": int(n_phase2),
        "seed": int(seed),
        "naming": "content-hash-v2 (mf resume, #148)",
    }
    h1 = hashlib.sha256(
        content + f"{adapter_low}|seed={seed}".encode()).hexdigest()[:10]
    h2 = hashlib.sha256(
        content + f"{adapter_low}+{adapter_high}+k{n_phase2}|seed={seed}".encode()
    ).hexdigest()[:10]
    return {"phase1": f"mf_p1_{h1}", "phase2": f"mf_p2_{h2}", "spec": spec}


def run_multifidelity(recipe_path, *, adapter_low="fake", adapter_high="fake",
                      n_phase1=40, n_phase2=5, seed=42, resume=False):
    """两阶段多保真优化（Phase1 粗筛 → HV 选点 → Phase2 精算）。

    断点续跑（C18，#148）：study 名稳定派生（:func:`mf_study_names`），Phase1
    按"累计目标"补差（已有 p1_done 个 COMPLETE 只跑 ``n_phase1 - p1_done`` 个
    新 trial），Phase2 消费 enqueue 前回查同名 study 已 COMPLETE trial（params
    指纹比对），已评估点跳过不再真算、复用 trial 值——跳过/复用计数见
    ``p2_skipped_reused`` / ``p2_reused``（同值，兼容保留）、新算数
    ``p2_recalculated``、入队数 ``p2_enqueued``。

    ``resume`` 参数保留兼容（阶段 0.4 语义），新命名下续跑恒开——传 True/False
    行为一致，仅 ``result["resume"]`` 回显。
    """
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

    # study 名去 run_id 化（#148）：无条件稳定派生（配方内容+适配器组合+
    # k(n_phase2)+seed 哈希）——同配方同 seed 跨进程同名，进程被杀后重跑挂回
    # 同一 study，已 COMPLETE 的 trial 不再重算。
    names = mf_study_names(path, adapter_low=adapter_low, adapter_high=adapter_high,
                           n_phase2=n_phase2, seed=seed)
    p1_study_name = names["phase1"]
    p2_study_name = names["phase2"]
    study_spec = names["spec"]
    storage = get_storage_path()
    try:
        _pre = optuna.load_study(study_name=p1_study_name, storage=storage)
        p1_done = len([t for t in _pre.get_trials(deepcopy=False)
                       if t.state == optuna.trial.TrialState.COMPLETE])
    except (KeyError, ValueError):
        p1_done = 0
    # Phase1 top-up：n_phase1 语义=累计目标——已有 p1_done 个 COMPLETE 时只补
    # 差额（断点续跑不重算粗筛）；首跑 p1_done=0，行为与旧实现一致。
    eff_n1 = max(0, n_phase1 - p1_done)

    logger.info("Phase 1: %d new trials (existing %d complete, stable study=%s), adapter=%s",
                eff_n1, p1_done, p1_study_name, adapter_low)
    phase1 = run_optimization(str(path), adapter_name=adapter_low, max_trials=eff_n1,
                              study_name=p1_study_name, sampler="tpe", seed=seed)
    if not phase1.get("ok"):
        return {"ok": False, "errors": ["Phase 1 failed", *phase1.get("errors", [])]}

    study = optuna.load_study(study_name=phase1["study_name"], storage=phase1["storage"])
    with contextlib.suppress(Exception):  # study 身份审计（哈希输入落档，best-effort #105）
        study.set_user_attr("mf_resume_spec", study_spec)
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
    # enqueue 前回查（C18，#148）：候选参数已有 COMPLETE trial 的直接复用
    # （params 指纹=排序 JSON），不再 enqueue 重算——无条件生效，不依赖
    # resume 旗标。optuna 4.9 无 waiting_trials()，此处只查 COMPLETE
    # （get_trials 按状态过滤，#123 口径），WAITING/RUNNING 不视为已评估。
    p2_study = optuna.create_study(study_name=p2_study_name, storage=phase1["storage"],
                                   direction="minimize", load_if_exists=True)
    with contextlib.suppress(Exception):
        p2_study.set_user_attr("mf_resume_spec", study_spec)
    p2_done = {json.dumps(dict(t.params), sort_keys=True): t
               for t in p2_study.get_trials(deepcopy=False)
               if t.state == optuna.trial.TrialState.COMPLETE}
    pending: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    for cand in top_k:
        key = json.dumps(dict(cand.get("params", {})), sort_keys=True)
        t = p2_done.get(key)
        if t is not None:
            reused.append({"params": cand.get("params", {}), "cost": t.value,
                           "metrics": t.user_attrs.get("metrics", {})})
        else:
            pending.append(cand)
    for cand in pending:
        p2_study.enqueue_trial(dict(cand.get("params", {})))

    logger.info("Phase 2: %d enqueued + %d skipped/reused (already COMPLETE), adapter=%s",
                len(pending), len(reused), adapter_high)
    p2 = {"ok": True}
    p2_new: list[dict[str, Any]] = []
    if pending:
        p2 = run_optimization(str(path), adapter_name=adapter_high, max_trials=len(pending),
                              study_name=p2_study_name, sampler="tpe", seed=seed)
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
              "p2_skipped_reused": len(reused), "p2_enqueued": len(pending),
              "p1_existing_complete": p1_done, "p1_new_trials": eff_n1,
              "study_names": {"phase1": p1_study_name, "phase2": p2_study_name},
              "study_spec": study_spec,
              "phase2_selection": phase2_selection}
    if warnings_note is not None:
        result["warnings"] = [warnings_note]
    write_meta(run_dir, {"run_id": run_id, "model": recipe_data.get("model", ""), "status": "done",
                         "adapter": f"mf:{adapter_low}+{adapter_high}", "algorithm": "multifidelity", "metrics": delta})
    record_run(record={"run_id": run_id, "model": recipe_data.get("model", ""),
               "adapter": f"mf:{adapter_low}+{adapter_high}", "status": "done",
               "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "metrics": {"hfss_count": len(p2_results)}})
    return result
