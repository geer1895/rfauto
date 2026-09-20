"""代理寻优环（WP3.2，SBO：Surrogate-Based Optimization）。

环结构（Level 1 步骤 1）：
  LHS 初始采样 N0 → 代理拟合（surrogate_registry 既有内核）→
  代理目标上 Optuna TPE 大规模虚拟寻优（零成本）→ top-K 多样性筛选
  （预测最优 + 最小归一化距离约束，防重复采样）→ K 点批量真跑 →
  refit → 收敛判据（连续 tol_rounds 轮最优改善 < tol_abs 或达真跑预算）。

铁律落地：
- 数值只在确定性内核（数值铁律）：代理预测与 cost 计算全部出自
 surrogate_registry + SpecEvaluator 确定性闭式，LLM 不入环；
- 谷深语义（#195/#197）：目标评估走 SpecEvaluator.evaluate_objectives，
 metric_key_candidates 的 op 序映射保证 s11_db_min 类目标不退化成
 带内 max 常数陷阱；
- 代理从注册表取（规则 3），本模块不内联任何拟合/预测实现；
- 真跑执行与环逻辑分离：evaluate_fn 注入（params→metrics，失败抛异常
 由环记为 failure sample，不炸整环）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from rfauto.core.objectives import Objective, SpecEvaluator
from rfauto.optimization.surrogate_analysis import (
  analyze_run_surrogate,
  surrogate_fit_quality,
)

# 单轮虚拟寻优试验数默认值（方案口径 2000+；2-3 参数 poly_ridge 毫秒级
# 预测下秒级完成，留余量给慢代理）
DEFAULT_VIRTUAL_TRIALS = 2000

# 软约束罚权（无量纲算法常数，非物理量）：违约量与 cost 同量纲（指标
# 域加权 dB/带宽差），1e3 保证任意正违约在虚拟寻优排序中支配任意可行 cost
# 差异（词典序可行性语义，与 optimizer.py E10 的 Optuna constraints_func
# 软约束通道"≤0=可行"同向）。预测失败的 1e12 大罚值仍保持支配地位。
CONSTRAINT_PENALTY_WEIGHT = 1e3


def _normalize(
  params: dict[str, float],
  names: list[str],
  bounds: dict[str, tuple[float, float]],
) -> list[float]:
  out = []
  for n in names:
    lo, hi = bounds[n]
    out.append((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12))
  return out


def _distance(a: list[float], b: list[float]) -> float:
  return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def select_topk(
  candidates: list[tuple[float, dict[str, float]]],
  k: int,
  bounds: dict[str, tuple[float, float]],
  exclude: list[dict[str, float]],
  min_dist: float,
) -> list[tuple[float, dict[str, float]]]:
  """从按预测 cost 升序的候选中选 top-K，带最小归一化距离约束。

  贪心：依次取当前最优，与（已选 ∪ exclude=已真跑点）距离均 ≥ min_dist
  才入选。候选耗尽仍不足 K 时返回已选——调用方据此放宽或停环。
  """
  names = sorted(bounds)
  ref = [_normalize(p, names, bounds) for p in exclude]
  selected: list[tuple[float, dict[str, float]]] = []
  for cost, params in candidates:
    if len(selected) >= k:
      break
    p_norm = _normalize(params, names, bounds)
    if all(_distance(p_norm, r) >= min_dist for r in ref):
      selected.append((cost, params))
      ref.append(p_norm)
  return selected


def constraint_violations(
  metrics: dict[str, float],
  constraints: list[Objective] | None,
) -> list[float]:
  """逐条约束违约量（与 optimizer.py `_record_constraints` 同口径）。

  每条约束单独走 SpecEvaluator.evaluate_objectives(metrics, [c])：返回值
  恒 ≥0，0=可行边界；全部 ≤0 即可行。无约束时返回空列表。
  """
  if not constraints:
    return []
  return [float(SpecEvaluator.evaluate_objectives(metrics, [c]))
      for c in constraints]


def _virtual_search(
  model: Any,
  objectives: list[Objective],
  bounds: dict[str, tuple[float, float]],
  n_trials: int,
  seed: int,
  constraints: list[Objective] | None = None,
) -> list[tuple[float, dict[str, float]]]:
  """代理目标上的 TPE 大规模虚拟寻优（零真跑成本）。

  返回按预测 cost 升序的 (cost, params) 候选列表；内存 study，
  与持久化 Optuna storage（optimizer.get_storage_path）互不干扰。

  constraints 非空时，虚拟目标 = 预测 cost +
  CONSTRAINT_PENALTY_WEIGHT × Σ 预测违约量（soft penalty）——候选排序
  先可行后 cost；无约束时目标逐字节不变。
  """
  import optuna

  names = sorted(bounds)

  def virtual_objective(vt: optuna.Trial) -> float:
    params = {
      n: vt.suggest_float(n, float(bounds[n][0]), float(bounds[n][1]))
      for n in names
    }
    try:
      predicted = model.predict(params)
      value = SpecEvaluator.evaluate_objectives(predicted, objectives)
      if constraints:
        value += CONSTRAINT_PENALTY_WEIGHT * sum(
          constraint_violations(predicted, constraints))
      return value
    except Exception:
      # 代理预测失败按大罚值处理——不让单点异常炸掉整轮虚拟寻优
      # （审查 P2-9：evaluate_fn 的"失败不入环"承诺延伸到虚拟侧）
      return 1e12

  # 2000 级虚拟试验逐条 INFO 会淹没日志——create/optimize 全程临时降噪
  prev_verbosity = optuna.logging.get_verbosity()
  optuna.logging.set_verbosity(optuna.logging.WARNING)
  try:
    study = optuna.create_study(
      sampler=optuna.samplers.TPESampler(seed=seed),
      direction="minimize")
    study.optimize(virtual_objective, n_trials=n_trials)
  finally:
    optuna.logging.set_verbosity(prev_verbosity)
  ranked = sorted(
    ((t.value, dict(t.params))
     for t in study.get_trials(deepcopy=False)
     if t.state == optuna.trial.TrialState.COMPLETE),
    key=lambda cv: cv[0])
  return ranked


def _exploration_point(
  bounds: dict[str, tuple[float, float]],
  exclude: list[dict[str, float]],
  seed: int,
  n_pool: int = 64,
) -> dict[str, float] | None:
  """探索补点：LHS 池中选"距已评估点最近距离最大"者（maxi-min）。

  SBO 标准信息填充惯例：抵消纯贪心 top-K 在代理偏差下的聚类采样，
  给 refit 持续注入全局信息。池点全部与已评估重合时返回 None。
  """
  from rfauto.optimization.sample_design import lhs_points

  pool = lhs_points(bounds, n_pool, seed=seed)["points"]
  names = sorted(bounds)
  excl_norm = [_normalize(p, names, bounds) for p in exclude]
  best_pt: dict[str, float] | None = None
  best_d = -1.0
  for pt in pool:
    p_norm = _normalize(pt, names, bounds)
    d = (min((_distance(p_norm, e) for e in excl_norm), default=1.0))
    if d > best_d:
      best_d = d
      best_pt = pt
  return best_pt if best_d > 1e-9 else None


def run_surrogate_loop(
  bounds: dict[str, tuple[float, float]],
  objectives: list[Objective],
  evaluate_fn: Callable[[dict[str, float]], dict[str, float]],
  *,
  n_init: int = 10,
  top_k: int = 3,
  virtual_trials: int = DEFAULT_VIRTUAL_TRIALS,
  max_real: int = 30,
  min_dist: float = 0.08,
  tol_abs: float = 1e-3,
  tol_rounds: int = 2,
  surrogate_kind: str = "poly_ridge",
  surrogate_config: dict[str, Any] | None = None,
  seed: int = 42,
  constraints: list[Objective] | None = None,
  evaluate_low_fn: Callable[[dict[str, float]], dict[str, float]] | None = None,
  fine_top_k: int = 1,
  fine_budget: int | None = None,
  min_high_samples: int = 3,
) -> dict[str, Any]:
  """代理寻优主环：返回 JSON 契约（服务层直接透传）。

  evaluate_fn: params → metrics dict（与 SpecEvaluator.compute_metrics
  同构）；抛异常 = 该点真跑失败，记 failure 不入样本。

  surrogate_config 透传给注册表工厂（规则 3）；默认把 poly_ridge 的
  ridge_lambda 降到 0.01——环内 10 点 vs 6 特征本就良态，默认 0.1 的
  收缩偏置会把拟合面压平、最优点逐轮拉向样本重心（实测收敛轮数 7→2）。

  constraints（E10 同语义的 sbo 软约束通道；缺省 None=行为逐字节
  不变）：每个真跑样本逐条算违约量存 sample["constraint_values"]（≥0）
  与 sample["feasible"]（全部 ≤0）；虚拟寻优目标对预测违约加罚
  （CONSTRAINT_PENALTY_WEIGHT）；best 语义收敛为"最优可行样本"，返回体补
  n_feasible / best_feasible / all_infeasible（镜像 optimizer.py
  run_optimization 的 E10 结果语义：全不可行如实报告，不凑绿 #122）。
  evaluate_fn 产出的 metrics 须覆盖约束指标键（服务层按 objectives+
  constraints 并集取指标，缺键的约束违约量按 0 计——与 evaluate_objectives
  "缺键跳过"口径一致）。

  E7 多保真接环（#23：接 WP3.2 环与方向 1 粗筛/精算两级保真；
  evaluate_low_fn 缺省 None 时本节全部参数不生效，单保真路径行为逐字节
  不变——既有回归为证）：
  - evaluate_low_fn：低保真评估通道（params → metrics，同构 evaluate_fn，
   如 fake/openEMS 粗筛）；evaluate_fn 升义为细保真（HFSS 级）通道。
   预算语义随之分层：max_real 只计**低保真**尝试（粗筛几乎免费），
   细保真复核由 fine_budget 单独计（两者都按"成功+失败"尝试次数烧）。
  - 轮次采样全走低保真（初始 LHS 批 + 每轮 top-K 批 + 探索点）；每轮对
   虚拟寻优的预测最优候选（picked 升序取前 fine_top_k 个未细评者）做
   细保真复核并入样本；best 只由**细保真**样本更新（最终质量以细保真
   为准，低保真只筛选不背书）。细评候选天然 ⊆ 已低评点集（低保真选点、
   同点复核），符合 co-kriging 嵌套 DoE 惯例。
  - 拟合前细保真种子不足 min_high_samples（默认 3：SMT MFK 高保真层
   OLS 需 n > p+q=2，实测 n=2 抛"undetermined"；注册表 fit 契约的保守
   下限）时，按已评低保真 cost 升序补细评至下限（细预算尽仍不足则降级
   为全样本混拟，smt_mfk 无混拟通道时如实 surrogate_fit_failed 停环）。
  - surrogate_kind == "smt_mfk"（AR1 co-kriging，注册表既有件）时，环
   自动把全部已评低保真样本注入 config.low_fi_samples、fit 只吃细保真
   样本——环拥有评估策略，非注册表契约泄漏（smt_mfk.fit(high) 契约
   不变）；其余种类全样本（低+细）混拟。
  - 返回体补 n_low_used / n_high_used / fine_budget / fidelity /
   fidelity_delta（复用 mf_backend.compute_fidelity_delta，rank_flip_count
   为核心保真差诊断，#195 谷深语义指标同源）。
  """
  from rfauto.optimization.sample_design import lhs_points
  from rfauto.optimization.surrogate import surrogate_registry

  mf_mode = evaluate_low_fn is not None
  fine_top_k = max(1, int(fine_top_k))
  fine_budget_eff = (None if fine_budget is None
            else max(0, int(fine_budget)))

  # poly_ridge 专属默认（环内 10 点 6 特征良态，默认 0.1 收缩偏置会
  # 把拟合面压平、最优点逐轮拉向样本重心，实测收敛 7 轮→2 轮）；
  # 其余种类不注入 poly_ridge 语义（审查 P2-12：注册表契约不泄环默认）
  model_config: dict[str, Any] = {}
  if surrogate_kind == "poly_ridge":
    model_config["ridge_lambda"] = 0.01
  model_config.update(surrogate_config or {})

  if not bounds:
    return {"ok": False, "errors": ["搜索空间为空（bounds 缺失）"]}
  if not objectives:
    return {"ok": False, "errors": ["objectives 为空，无从评估 cost"]}
  # 预算契约：初始批不得突破真跑预算（审查 P1-4）
  n_init = max(1, min(int(n_init), int(max_real)))
  constraints = list(constraints) if constraints else None

  samples: list[dict[str, Any]] = []
  failures: list[dict[str, Any]] = []
  low_samples: list[dict[str, Any]] = []
  high_samples: list[dict[str, Any]] = []
  low_failures: list[dict[str, Any]] = []
  high_failures: list[dict[str, Any]] = []
  high_keys: set[str] = set()
  low_keys: set[str] = set()

  def _pkey(params: dict[str, float]) -> str:
    import json as _json
    return _json.dumps(dict(params), sort_keys=True)

  def cost_of(metrics: dict[str, float]) -> float:
    return SpecEvaluator.evaluate_objectives(metrics, objectives)

  def evaluate_real(params: dict[str, float], phase: str,
           fidelity: str = "high") -> float | None:
    is_low = mf_mode and fidelity == "low"
    fn = evaluate_low_fn if is_low else evaluate_fn
    try:
      metrics = fn(dict(params))
    except Exception as exc:
      rec = {"params": dict(params), "phase": phase, "error": str(exc)}
      if mf_mode:
        rec["fidelity"] = fidelity
        (low_failures if is_low else high_failures).append(rec)
      failures.append(rec)
      return None
    cost = cost_of(metrics)
    sample: dict[str, Any] = {"params": dict(params), "metrics": metrics,
                 "cost": cost}
    if mf_mode:
      sample["fidelity"] = fidelity
    if constraints:
      cvals = constraint_violations(metrics, constraints)
      sample["constraint_values"] = cvals
      sample["feasible"] = all(v <= 0.0 for v in cvals)
    samples.append(sample)
    if mf_mode:
      (low_samples if is_low else high_samples).append(sample)
      (low_keys if is_low else high_keys).add(_pkey(params))
    nonlocal best
    if mf_mode and is_low:
      pass # 低保真样本不进 best（E7：best 只由细保真背书）
    elif constraints and not sample["feasible"]:
      pass # 不可行样本不进 best（E10：best=最优可行）
    elif best is None or cost < best["cost"]:
      best = {"params": dict(params), "metrics": metrics,
          "cost": cost}
    return cost

  def fine_budget_left() -> bool:
    return (fine_budget_eff is None
        or len(high_samples) + len(high_failures) < fine_budget_eff)

  best: dict[str, Any] | None = None
  model: Any = None # 最近一次拟合的环内代理（质量报告用）
  t0 = time.time()

  # ── ① LHS 初始采样 + 批量真跑 ────────────────────────────────────────
  init = lhs_points(bounds, n_init, seed=seed)
  for pt in init["points"]:
    evaluate_real(pt, "init", fidelity="low" if mf_mode else "high")
  # E7：细保真种子补齐（按已评低保真 cost 升序，LHS 序稳定同名次序）
  if mf_mode:
    seed_order = sorted(
      (s for s in low_samples if _pkey(s["params"]) not in high_keys),
      key=lambda s: s["cost"])
    for s in seed_order:
      if len(high_samples) >= max(1, int(min_high_samples)):
        break
      if not fine_budget_left():
        break
      evaluate_real(s["params"], "init_fine", fidelity="high")
  # 预算按尝试次数计（成功+失败）——系统性求解失败时 n_real 不前进
  # 会让 while 永转；每次尝试都烧真机 wall-clock，同计预算。
  # E7：max_real 只计低保真通道（细保真由 fine_budget 单独计）
  attempts = (len(low_samples) + len(low_failures) if mf_mode
        else len(samples) + len(failures))
  history: list[dict[str, Any]] = [{
    "round": 0, "phase": "lhs_init",
    "n_evaluated": len(samples),
    "best_cost": best["cost"] if best else None,
  }]

  # ── ② 迭代：代理拟合 → 虚拟寻优 → top-K → 批量真跑 → refit ──────────
  stagnation = 0
  stop_reason = ""
  rnd = 0
  while attempts < max_real:
    rnd += 1
    # E7：smt_mfk 由环注入低保真样本（评估策略归环，非注册表契约）；
    # 细保真种子足额时 fit 只吃细保真点，否则降级全样本混拟
    round_config: dict[str, Any] = {
      "bounds": {k: tuple(v) for k, v in bounds.items()},
      **model_config}
    fit_set = samples
    if (mf_mode and surrogate_kind == "smt_mfk"
        and len(high_samples) >= max(1, int(min_high_samples))):
      round_config["low_fi_samples"] = [
        {"params": dict(s["params"]), "metrics": dict(s["metrics"])}
        for s in low_samples]
      fit_set = high_samples
    model = surrogate_registry.create(surrogate_kind, config=round_config)
    # 全部初始点真跑失败时样本为空——先守卫再 fit（审查 P1-1：
    # poly_ridge 对空样本 IndexError 直接炸环，守卫永远到不了）
    if not samples or (mf_mode and not fit_set):
      stop_reason = "surrogate_fit_failed"
      break
    if mf_mode:
      try:
        model.fit(fit_set)
      except Exception:
        # 多保真拟合失败（如 co-kriging 对病态样本集）按环停处理，
        # 不炸已收样本的结果（#105 同源：观测/拟合不阻断主路径）
        stop_reason = "surrogate_fit_failed"
        break
    else:
      model.fit(samples)
    if not model.fitted:
      stop_reason = "surrogate_fit_failed"
      break

    candidates = _virtual_search(model, objectives, bounds,
                   virtual_trials, seed + rnd,
                   constraints=constraints)
    # top-(K-1) 按预测 cost 贪心（最小归一化距离约束），最后 1 个
    # 名额留给探索补点（maxi-min）——代理偏差时防聚类采错。
    # 排除集含**失败点**（审查 P1-3）：系统性失败区若不排除，代理
    # 会持续预测其为优、每轮重选烧真跑预算
    evaluated = [s["params"] for s in samples]
    evaluated.extend(f["params"] for f in failures)
    picked = select_topk(candidates, max(top_k - 1, 1), bounds,
               evaluated, min_dist)
    relaxed = False
    if not picked:
      picked = select_topk(candidates, max(top_k - 1, 1), bounds,
                 evaluated, min_dist / 2)
      relaxed = True
    explore = _exploration_point(
      bounds, evaluated + [p for _c, p in picked], seed + 97 * rnd)
    batch = [p for _c, p in picked]
    if explore is not None:
      batch.append(explore)
    if not batch:
      stop_reason = "no_new_points"
      break

    best_before = best["cost"] if best else None
    n_fine_round = 0
    for params in batch:
      if attempts >= max_real:
        break
      evaluate_real(params, f"round{rnd}",
             fidelity="low" if mf_mode else "high")
      attempts = (len(low_samples) + len(low_failures) if mf_mode
            else len(samples) + len(failures))

    # E7：每轮细保真复核——虚拟寻优预测最优候选（picked 已按预测 cost
    # 升序）取前 fine_top_k 个未细评者，细预算尽即止；同点不重复细评；
    # 只细评本轮已低评成功的点（低选点、同点复核 → 细评集 ⊆ 低评集，
    # co-kriging 嵌套 DoE；低预算中途耗尽未低评的候选不细评）
    if mf_mode:
      for _cost_pred, cand in picked:
        if n_fine_round >= fine_top_k or not fine_budget_left():
          break
        key = _pkey(cand)
        if key in high_keys or key not in low_keys:
          continue
        evaluate_real(cand, f"round{rnd}_fine", fidelity="high")
        n_fine_round += 1

    best_after = best["cost"] if best else None
    improved = (
      None if (best_before is None or best_after is None)
      else best_before - best_after)
    round_entry: dict[str, Any] = {
      "round": rnd,
      "n_evaluated": len(batch),
      "n_explore": 1 if explore is not None else 0,
      "min_dist_relaxed": relaxed,
      "best_cost_before": best_before,
      "best_cost_after": best_after,
      "improvement": improved,
      "best_params": best["params"] if best else None,
    }
    if mf_mode:
      round_entry["n_fine"] = n_fine_round
      round_entry["n_high_total"] = len(high_samples)
    history.append(round_entry)
    if improved is not None and improved < tol_abs:
      stagnation += 1
      if stagnation >= tol_rounds:
        stop_reason = "stagnation"
        break
    else:
      stagnation = 0

  if not stop_reason:
    stop_reason = "budget"

  # 约束路径 best 收敛为"最优可行"（与 evaluate_real 的可行门一致），
  # 全不可行时如实置 best=None + all_infeasible=True（不凑绿，#122；
  # 镜像 optimizer.py run_optimization E10 结果语义）。"全不可行"只在
  # 确有已评估样本时成立——零样本（全初始失败）是"没评上"。
  # E7：多保真模式下可行性裁决只看细保真样本（best 只由细保真背书）。
  best_feasible: dict[str, Any] | None = None
  if constraints:
    feas_pool = high_samples if mf_mode else samples
    feasible_samples = [s for s in feas_pool if s.get("feasible")]
    if feasible_samples:
      best_s = min(feasible_samples, key=lambda s: s["cost"])
      best = {"params": dict(best_s["params"]),
          "metrics": best_s["metrics"], "cost": best_s["cost"]}
      best_feasible = dict(best)
    else:
      best = None

  # 环报告携带真实代理质量（GP 交叉验证分析 + 环内实际代理拟合残差）
  # E7：多保真模式只对细保真样本评质量（低保真 cost 与代理预测的细保真
  # 面不同源，混评无意义）
  quality_report = _surrogate_quality_report(
    high_samples if mf_mode else samples, model, surrogate_kind, objectives)

  result = {
    "ok": True,
    "algorithm": "surrogate_loop",
    "surrogate_kind": surrogate_kind,
    "surrogate_quality": quality_report["analysis"],
    "in_loop_surrogate_quality": quality_report["in_loop"],
    "best": best,
    "n_real_used": len(samples),
    "n_attempts": attempts,
    "n_init": len(init["points"]),
    "n_failures": len(failures),
    "rounds": history,
    "stop_reason": stop_reason,
    "virtual_trials": virtual_trials,
    "failures": failures,
    # 逐次真跑 cost（评估序）——收敛曲线/MVP 基准与缩减率
    # 裁判都从这里读，调用方无需自行插桩
    "real_cost_trace": [s["cost"] for s in samples],
    "elapsed_s": round(time.time() - t0, 2),
  }
  if mf_mode:
    # E7 多保真返回体（单保真模式不加键，行为逐字节不变）
    result["fidelity"] = "multi"
    result["n_low_used"] = len(low_samples)
    result["n_high_used"] = len(high_samples)
    result["fine_budget"] = fine_budget_eff
    from rfauto.optimization.mf_backend import compute_fidelity_delta

    result["fidelity_delta"] = compute_fidelity_delta(
      [{"params": s["params"], "cost": s["cost"], "metrics": s["metrics"]}
       for s in low_samples],
      [{"params": s["params"], "cost": s["cost"], "metrics": s["metrics"]}
       for s in high_samples],
      seed=seed)
  if constraints:
    # E10 同语义三键（无约束时不加键，路径行为逐字节不变）
    feas_pool = high_samples if mf_mode else samples
    result["n_feasible"] = len([s for s in feas_pool if s.get("feasible")])
    result["best_feasible"] = best_feasible
    if feas_pool and best_feasible is None:
      result["all_infeasible"] = True
  return result


def best_so_far_trace(costs: list[float]) -> list[float]:
  """逐次真跑的 best-so-far 轨迹（MVP 基准/单测对照用确定性工具）。"""
  out: list[float] = []
  cur = float("inf")
  for c in costs:
    cur = min(cur, float(c))
    out.append(cur)
  return out


def _surrogate_quality_report(
  samples: list[dict[str, Any]],
  model: Any,
  surrogate_kind: str,
  objectives: list[Objective],
) -> dict[str, Any]:
  """环报告代理质量：GP 参考分析 + 环内实际代理拟合质量。

  - analysis：对已评估样本调用 analyze_run_surrogate 的真实输出
   （样本 ≥6 时为 K 折交叉验证 out-of-fold，ρ/残差/RMS/MAE/R²）；
  - in_loop：环内实际代理（surrogate_kind，默认 poly_ridge）对全部
   已评估样本的预测 cost 残差——反映环真正使用的代理面。
  两者均为 best-effort（#105）：观测失败只标 available=False + detail，
  绝不炸掉已经跑完的寻优环，也绝不填占位数值。
  """
  analysis: dict[str, Any] = {
    "source": "analyze_run_surrogate",
    "available": False,
    "n_samples": len(samples),
    "detail": "样本不足 3，代理质量不可测",
  }
  if len(samples) >= 3:
    try:
      trials = [{"params": dict(s["params"]), "cost": float(s["cost"])}
           for s in samples]
      res = analyze_run_surrogate("surrogate_loop", trials)
      analysis = {
        "source": "analyze_run_surrogate",
        "available": True,
        "n_samples": len(samples),
        **res.to_dict()["quality"],
        "prediction_error": round(float(res.prediction_error), 6),
        "param_importance": {k: round(float(v), 6)
                   for k, v in res.param_importance.items()},
      }
    except Exception as exc: # 观测性 best-effort（#105）
      analysis = {
        "source": "analyze_run_surrogate",
        "available": False,
        "n_samples": len(samples),
        "detail": f"代理质量分析失败（best-effort #105）: {exc}",
      }
  in_loop: dict[str, Any] = {
    "source": f"surrogate_loop:{surrogate_kind}",
    "available": False,
    "n_samples": len(samples),
    "detail": "无已拟合的环内代理模型",
  }
  if model is not None and getattr(model, "fitted", False) and samples:
    try:
      y_true = [float(s["cost"]) for s in samples]
      y_pred = [
        float(SpecEvaluator.evaluate_objectives(
          model.predict(s["params"]), objectives))
        for s in samples
      ]
      quality = surrogate_fit_quality(y_true, y_pred)
      in_loop = {
        "source": f"surrogate_loop:{surrogate_kind}",
        "available": True,
        "kind": "in_sample_train_residual",
        "n_samples": len(samples),
        **{k: v for k, v in quality.items() if k != "detail"},
        "detail": ("环内实际代理（非 GP 参考）对全部已评估样本的"
              "预测 cost 残差；最后一个拟合模型，可能包含其后新采样本"),
      }
    except Exception as exc: # 观测性 best-effort（#105）
      in_loop = {
        "source": f"surrogate_loop:{surrogate_kind}",
        "available": False,
        "n_samples": len(samples),
        "detail": f"环内代理质量计算失败（best-effort #105）: {exc}",
      }
  return {"analysis": analysis, "in_loop": in_loop}

