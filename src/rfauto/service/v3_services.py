"""v3 service functions (Direction 1/2/3/4b/6a/6d/7/8a/8b).

Separated from api.py to avoid write-tool truncation bug (#108).
Imported by api.py via: from rfauto.service.v3_services import *
"""

from __future__ import annotations

import json
from pathlib import Path


def compare_runs_provenance(run_ids):
  """Output a citable provenance block for a set of runs."""
  runs_data = []
  for rid in run_ids:
    mp = Path("runs") / rid / "meta.json"
    if not mp.exists():
      return {"ok": False, "errors": [f"run not found: {rid}"]}
    meta = json.loads(mp.read_text(encoding="utf-8"))
    runs_data.append({"run_id": rid, "provenance": {
      "git_sha": meta.get("git_sha", "unknown"),
      "python_version": meta.get("python_version", "unknown"),
      "os": meta.get("os", "unknown"),
      "pip_freeze_sha": meta.get("pip_freeze_sha", "unknown"),
      "solver_versions": meta.get("solver_versions", {}),
      "optuna_seed": meta.get("optuna_seed") or meta.get("seed"),
    }, "metrics": meta.get("metrics", {})})
  compare = None
  if len(run_ids) == 2:
    m0, m1 = runs_data[0].get("metrics", {}), runs_data[1].get("metrics", {})
    delta = {}
    for k in sorted(set(m0) | set(m1)):
      v0, v1 = m0.get(k), m1.get(k)
      if isinstance(v0, (int, float)) and isinstance(v1, (int, float)):
        delta[k] = {"a": v0, "b": v1, "delta": v1 - v0}
    compare = {"metrics_delta": delta}
  return {"ok": True, "runs": runs_data, "compare": compare}


def run_p0_experiment(recipe_path, *, seed=42, coarse_trials=40, fine_trials=15,
           baseline_trials=30, edge_samples=20, adapter_name="fake",
           high_adapter="fake", cross_samples=15):
  """Run P0 multi-fidelity validation experiment.

  早期审查发现：verdict 以跨保真 gate 为硬门槛——high_adapter 与 low 相同
  （默认 fake vs fake）为自比较，gate disabled，verdict=INCONCLUSIVE。
  """
  import importlib.util
  import time as _time

  from rfauto.core.state import generate_run_id
  from rfauto.infra.run_store import create_run_dir, write_meta
  path = Path(recipe_path)
  if not path.exists():
    return {"ok": False, "errors": [f"Not found: {path}"]}
  rid = generate_run_id()
  rd = create_run_dir(Path(".").resolve(), rid)
  _s = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "p0_experiment.py"
  if not _s.exists():
    return {"ok": False, "errors": ["P0 script not found"]}
  spec = importlib.util.spec_from_file_location("p0", str(_s))
  p0 = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(p0)
  t0 = _time.time()
  p0.run_single_fidelity(str(path), baseline_trials, seed, adapter_name)
  mf = p0.run_multi_fidelity(str(path), coarse_trials, fine_trials, seed, adapter_name)
  srho = None
  if mf.get("ok"):
    p1, fn = mf.get("all_trials_ranked", []), mf.get("final_trials_ranked", [])
    c = sorted(set(t["trial_number"] for t in p1) & set(t["trial_number"] for t in fn))
    if len(c) >= 3:
      from scipy import stats
      _sx = [next(t["cost"] for t in p1 if t["trial_number"] == n) for n in c]
      _sy = [next(t["cost"] for t in fn if t["trial_number"] == n) for n in c]
      import numpy as _np
      # 常数成本数组排名无信息量（校准后 fake 成本趋同）
      srho = (0.0 if _np.std(_sx) == 0 or _np.std(_sy) == 0
          else float(stats.spearmanr(_sx, _sy)[0]))
  edge = p0.edge_sampling_experiment(str(path), edge_samples, seed, adapter_name)
  cross = p0.cross_fidelity_experiment(str(path), cross_samples, seed,
                     low_adapter=adapter_name,
                     high_adapter=high_adapter)
  gate_active = cross.get("gate") == "cross_fidelity"
  if gate_active:
    crho, crec = cross.get("spearman_rho"), cross.get("top5_recall")
    verdict = ("PASS" if crho is not None and crho >= 0.8
          and crec is not None and crec >= 0.8 else "FAIL")
  else:
    verdict = "INCONCLUSIVE"
  result = {"ok": True, "run_id": rid, "verdict": verdict,
       "gate": cross.get("gate"),
       "elapsed_s": round(_time.time() - t0, 1),
       "correlation": {"spearman_rho": srho,
               "rho_pass": srho is not None and srho >= 0.8},
       "cross_fidelity": {"high_adapter": high_adapter,
                 "spearman_rho": cross.get("spearman_rho"),
                 "top5_recall": cross.get("top5_recall"),
                 "n_evaluated": cross.get("n_evaluated")},
       "edge_sampling": {"n_samples": edge.get("n_edge_samples")}}
  write_meta(rd, {"run_id": rid, "model": "p0_experiment", "adapter": adapter_name,
          "status": "done", "verdict": verdict, "gate": cross.get("gate"),
          "metrics": result["correlation"]})
  return result


def study_inject(study_name, params, *, source="human"):
  """Inject human parameters into an Optuna study (方向 6a/4d).

  早期审查修复：曾用私有 API trial._suggest + ask 不 tell，注入的 trial
  永远停在 RUNNING——不进完成集、TPE 忽略、人工参数实际不影响后续采样。
  现改为 Optuna 人机协同官方模式 enqueue_trial（WAITING + fixed_params）：
  下一次 study.optimize 消费注入点，参数真实参与评估并影响 TPE 后验。
  越界参数按计划 4d"边界映射策略"裁切入库并标记（不静默丢弃）。
  """
  import optuna

  from rfauto.optimization.optimizer import get_storage_path
  from rfauto.service.agent_safety import append_audit_log
  try:
    study = optuna.load_study(study_name=study_name, storage=get_storage_path())
  except Exception as e:
    return {"ok": False, "errors": [f"Failed: {e}"]}

  # 边界映射：从历史 trial 的分布推断各参数范围；未知参数拒绝（不能凭空造分布）
  clipped_from: dict[str, dict] = {}
  clipped_params: dict[str, float] = {}
  rejected: list[str] = []
  past = study.get_trials(deepcopy=False)
  for name, value in params.items():
    dist = None
    for t in past:
      if name in t.distributions:
        dist = t.distributions[name]
        break
    if dist is None:
      rejected.append(name)
      continue
    if isinstance(dist, optuna.distributions.FloatDistribution):
      v = float(value)
      low, high = dist.low, dist.high
      if v < low or v > high:
        clipped_from[name] = {"requested": v, "clipped_to": min(max(v, low), high)}
        v = min(max(v, low), high)
      clipped_params[name] = v
    else:
      clipped_params[name] = value

  if not clipped_params:
    return {"ok": False,
        "errors": [f"无可注入参数（未知参数: {rejected}）——注入参数必须已在 study 中出现过"]}

  study.enqueue_trial(
    clipped_params,
    user_attrs={"trial_source": source, "injected": True,
          "clipped_from": clipped_from},
    skip_if_exists=False,
  )
  # enqueue_trial 在部分 Optuna 版本返回 None——回查刚建的 WAITING trial 号
  trial_number = max(
    (t.number for t in study.get_trials(deepcopy=False)
     if t.user_attrs.get("injected")),
    default=None,
  )
  append_audit_log({"event": "study_inject", "ok": True, "study_name": study_name,
           "params": params, "clipped": clipped_from, "rejected": rejected,
           "source": source, "trial_number": trial_number})
  return {"ok": True, "trial_number": trial_number, "study_name": study_name,
      "source": source, "params": clipped_params,
      "clipped_from": clipped_from, "rejected": rejected}


def structured_sweep(recipe_path, sweep_spec, *, adapter_name="fake"):
  """Run a structured parameter sweep."""
  import itertools

  import numpy as np
  import yaml

  from rfauto.core.objectives import Objective, SpecEvaluator
  from rfauto.models.registry import get as get_plugin
  from rfauto.optimization.optimizer import _prepare_env
  path = Path(recipe_path)
  if not path.exists():
    return {"ok": False, "errors": [f"Not found: {path}"]}
  with open(path, encoding="utf-8") as f:
    rd = yaml.safe_load(f)
  try:
    pc = get_plugin(rd.get("model", ""))
  except KeyError:
    return {"ok": False, "errors": ["Unknown model"]}
  obj = [Objective(**o) for o in rd.get("objectives", [])]
  if not obj:
    return {"ok": False, "errors": ["No objectives"]}
  pn = sorted(sweep_spec.keys())
  grids = []
  for n in pn:
    sp = sweep_spec[n]
    if sp.get("scale") == "log":
      g = list(np.geomspace(max(float(sp.get("start", 0)), 1e-10),
                 float(sp.get("stop", 1)), int(sp.get("steps", 5))))
    else:
      g = list(np.linspace(float(sp.get("start", 0)),
                 float(sp.get("stop", 1)), int(sp.get("steps", 5))))
    grids.append(g)
  combos = list(itertools.product(*grids))
  if len(combos) > 200:
    return {"ok": False, "errors": [f"Too many combos ({len(combos)})"]}
  bp = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in rd.get("params", {}).items()}
  results, best = [], None
  adapter, _, _pc2, _ps, sn, _ = _prepare_env(rd, adapter_name=adapter_name, adapter_kwargs=None)
  if adapter is None:
    return {"ok": False, "errors": ["Adapter failed"]}
  try:
    for combo in combos:
      p = dict(bp)
      for i, n in enumerate(pn):
        p[n] = float(combo[i])
      try:
        pl = pc()
        pl.build(adapter, pl.params_model(**p))
        r = adapter.solve(sn)
        if r.success:
          net = adapter.get_sparams()
          m = SpecEvaluator.compute_metrics(net, obj)
          c = SpecEvaluator.evaluate_objectives(m, obj)
          e = {"params": p, "metrics": m, "cost": c}
          results.append(e)
          if best is None or c < best["cost"]:
            best = e
      except Exception as ex:
        results.append({"params": p, "error": str(ex)})
  finally:
    adapter.close()
  results.sort(key=lambda r: r.get("cost", float("inf")))
  return {"ok": True, "sweep_spec": sweep_spec, "n_combinations": len(combos),
      "results": results, "best": best}


def run_multifidelity_tune(recipe_path, *, adapter_low="fake", adapter_high="fake",
              n_phase1=40, n_phase2=5, seed=42):
  from rfauto.optimization.mf_backend import run_multifidelity
  return run_multifidelity(recipe_path, adapter_low=adapter_low, adapter_high=adapter_high,
               n_phase1=n_phase1, n_phase2=n_phase2, seed=seed)


def run_multifidelity_sbo_tune(recipe_path, *, adapter_low="fake", adapter_high="fake",
                n_init=8, top_k=3, max_real=30, fine_budget=8,
                virtual_trials=None, surrogate_kind="smt_mfk",
                seed=42, adapter_kwargs=None):
  """E7 多保真代理寻优环服务入口（#23：WP3.2 环 × 方向 1 两级保真）。

  与 run_multifidelity_tune（两阶段 TPE 粗筛+HV 选点精算）互补：本入口
  把 run_surrogate_loop 的采样-代理-虚拟寻优环接上双保真——轮次采样全走
  adapter_low（粗筛几乎免费），每轮预测最优候选走 adapter_high 细保真复核，
  surrogate_kind="smt_mfk"（AR1 co-kriging）时低保真样本自动注入融合。
  recipe objectives/constraints（optimization.constraints）与 sbo 单保真
  服务同解析口径；数值只在确定性内核（环 + SpecEvaluator），LLM 不入环。
  """
  import time as _time

  import yaml

  from rfauto.core.objectives import Objective, SpecEvaluator
  from rfauto.core.state import generate_run_id
  from rfauto.infra.run_store import create_run_dir, record_run, snapshot_recipe, write_meta
  from rfauto.optimization.optimizer import _prepare_env, extract_param_ranges
  from rfauto.optimization.surrogate_loop import DEFAULT_VIRTUAL_TRIALS, run_surrogate_loop

  path = Path(recipe_path)
  if not path.exists():
    return {"ok": False, "errors": [f"配方文件不存在: {path}"]}
  with open(path, encoding="utf-8") as f:
    recipe_data = yaml.safe_load(f)
  param_ranges = extract_param_ranges(recipe_data)
  if not param_ranges:
    return {"ok": False, "errors": [
      "无可选优化参数。请在配方中添加 optimization.params 段或 params.<name>.bounds。"]}
  objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
  if not objectives:
    return {"ok": False, "errors": ["缺少 objectives 段"]}
  if any(o.metric == "gain_db" for o in objectives):
    return {"ok": False, "errors": [
      "多保真 sbo 路径暂不支持 gain_db 目标（远场指标未接入 evaluate_fn）"]}
  constraints = []
  for c in (recipe_data.get("optimization") or {}).get("constraints") or []:
    if not isinstance(c, dict):
      return {"ok": False, "errors": [f"constraints 元素须为 dict: {c!r}"]}
    constraints.append(Objective(**c))
  recipe_limits = recipe_data.get("limits") or {}
  if recipe_limits.get("max_trials"):
    max_real = min(max_real, int(recipe_limits["max_trials"]))

  run_id = generate_run_id()
  run_dir = create_run_dir(Path(".").resolve(), run_id)
  snapshot_recipe(run_dir, recipe_data)

  eval_specs = objectives + constraints

  def _make_eval(adapter, param_system, setup_name, plugin_cls):
    from rfauto.pipeline.self_heal import solve_with_self_heal

    def evaluate(params):
      param_system.update(params)
      param_system.write_to_adapter(
        adapter, name_map=getattr(plugin_cls, "hfss_var_map", {}))
      report = solve_with_self_heal(adapter, setup_name)
      if not report.success:
        raise RuntimeError(f"求解失败: {report.message}")
      network = adapter.get_sparams()
      return SpecEvaluator.compute_metrics(network, eval_specs)

    return evaluate

  bounds = {k: (float(v["low"]), float(v["high"]))
       for k, v in param_ranges.items()}
  env_low = _prepare_env(recipe_data, adapter_name=adapter_low,
              adapter_kwargs=adapter_kwargs)
  if env_low[0] is None:
    return {"ok": False, "errors": [f"低保真适配器失败: {env_low[5]}"]}
  env_high = _prepare_env(recipe_data, adapter_name=adapter_high,
              adapter_kwargs=adapter_kwargs)
  if env_high[0] is None:
    env_low[0].close()
    return {"ok": False, "errors": [f"细保真适配器失败: {env_high[5]}"]}
  adapter_low_env, _, _pl_low, ps_low, setup_low, _ = env_low
  adapter_high_env, aedt_version, plugin_high, ps_high, setup_high, _ = env_high
  evaluate_low_fn = _make_eval(adapter_low_env, ps_low, setup_low, plugin_high)
  evaluate_fn = _make_eval(adapter_high_env, ps_high, setup_high, plugin_high)

  t0 = _time.time()
  try:
    result = run_surrogate_loop(
      bounds, objectives, evaluate_fn,
      evaluate_low_fn=evaluate_low_fn,
      n_init=n_init, top_k=top_k,
      virtual_trials=(DEFAULT_VIRTUAL_TRIALS if virtual_trials is None
              else int(virtual_trials)),
      max_real=max_real, fine_budget=fine_budget,
      surrogate_kind=surrogate_kind, seed=seed,
      constraints=constraints or None)
  finally:
    adapter_low_env.close()
    adapter_high_env.close()
  elapsed = _time.time() - t0

  result.update({
    "run_id": run_id,
    "run_dir": str(run_dir),
    "adapter": f"mf_sbo:{adapter_low}+{adapter_high}",
    "aedt_version": aedt_version,
    "model": recipe_data.get("model", ""),
    "bounds": {k: list(v) for k, v in bounds.items()},
    "max_real": max_real,
    "elapsed_s": round(elapsed, 2),
  })
  (run_dir / "surrogate_loop.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=1, default=str),
    encoding="utf-8")
  best = result.get("best") or {}
  run_status = "done" if best else "failed"
  meta_metrics = {
    "best_cost": best.get("cost"),
    "n_low_used": result.get("n_low_used"),
    "n_high_used": result.get("n_high_used"),
    "stop_reason": result.get("stop_reason"),
  }
  if constraints:
    meta_metrics["feasible"] = bool(result.get("best_feasible"))
  write_meta(run_dir, {
    "run_id": run_id,
    "model": recipe_data.get("model", ""),
    "adapter": f"mf_sbo:{adapter_low}+{adapter_high}",
    "aedt_version": aedt_version,
    "status": run_status,
    "algorithm": "multifidelity_surrogate_loop",
    "metrics": meta_metrics,
  })
  record_run(record={
    "run_id": run_id,
    "model": recipe_data.get("model", ""),
    "adapter": f"mf_sbo:{adapter_low}+{adapter_high}",
    "status": run_status,
    "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
    "metrics": {"best_cost": best.get("cost"),
          "n_high_used": result.get("n_high_used")},
  })
  return result


def run_sensitivity(recipe_path, *, method="sobol", n_samples=100, seed=42, adapter_name="fake"):
  """Run sensitivity analysis (Direction 8b)."""
  import yaml

  from rfauto.core.objectives import Objective, SpecEvaluator
  from rfauto.optimization.optimizer import _prepare_env, extract_param_ranges
  path = Path(recipe_path)
  if not path.exists():
    return {"ok": False, "errors": [f"Not found: {path}"]}
  with open(path, encoding="utf-8") as f:
    recipe_data = yaml.safe_load(f)
  param_ranges = extract_param_ranges(recipe_data)
  if not param_ranges:
    return {"ok": False, "errors": ["No optimizable parameters"]}
  objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
  adapter, _, plugin_cls, param_system, setup_name, err = _prepare_env(
    recipe_data, adapter_name=adapter_name, adapter_kwargs=None)
  if adapter is None:
    return {"ok": False, "errors": [err]}

  def objective_fn(params):
    param_system.update(params)
    param_system.write_to_adapter(adapter, name_map=getattr(plugin_cls, "hfss_var_map", {}))
    report = adapter.solve(setup_name)
    if not report.success:
      return 1e3
    network = adapter.get_sparams()
    metrics = SpecEvaluator.compute_metrics(network, objectives)
    return SpecEvaluator.evaluate_objectives(metrics, objectives)

  try:
    from rfauto.optimization.sensitivity import morris_screening, sobol_sensitivity
    if method == "morris":
      result = morris_screening(param_ranges, objective_fn,
                   n_trajectories=max(5, n_samples // max(len(param_ranges), 1)), seed=seed)
    else:
      result = sobol_sensitivity(param_ranges, objective_fn, n_samples=n_samples, seed=seed)
  finally:
    adapter.close()
  return {"ok": True, "recipe": str(path), **result}


def _load_run_trials(run_dir: Path) -> list[dict]:
  """读取 run 的 trials/*.json 审计文件（按 trial_number 排序）。"""
  tdir = run_dir / "trials"
  if not tdir.exists():
    return []
  trials = []
  for f in sorted(tdir.glob("trial_*.json")):
    try:
      trials.append(json.loads(f.read_text(encoding="utf-8")))
    except Exception:
      continue
  trials.sort(key=lambda t: t.get("trial_number", 0))
  return trials


def _convergence_lines(trials: list[dict]) -> list[str]:
  """五要素①收敛曲线：best-so-far 表 + ASCII 走势。"""
  rows = [(t.get("trial_number", i), t.get("cost")) for i, t in enumerate(trials)
      if isinstance(t.get("cost"), (int, float))]
  if not rows:
    return ["- 无 trial 数据，收敛曲线不可用"]
  lines = ["| trial | cost | best_so_far |", "|---|---|---|"]
  best = float("inf")
  curve: list[float] = []
  for n, c in rows:
    best = min(best, float(c))
    curve.append(best)
    lines.append(f"| {n} | {float(c):.4f} | {best:.4f} |")
  lo, hi = min(curve), max(curve)
  span = (hi - lo) or 1.0
  blocks = "▁▂▃▄▅▆▇█"
  spark = "".join(blocks[min(int((b - lo) / span * 7.999), 7)] for b in curve)
  lines.append(f"- best-so-far 走势: `{spark}`")
  return lines


def _pareto_lines(trials: list[dict]) -> list[str]:
  """五要素②Pareto 前沿：指标级非支配集（默认 S11 vs 代价次轴退化标注）。"""
  pts = []
  for t in trials:
    m = t.get("metrics", {})
    c = t.get("cost")
    if isinstance(c, (int, float)) and isinstance(m.get("s11_db_max_in_band"), (int, float)):
      pts.append((t.get("trial_number", 0), float(c), float(m["s11_db_max_in_band"])))
  if len(pts) < 2:
    return ["- 单目标且指标不足：前沿退化为 best-so-far（见收敛曲线）"]
  # 非支配（最小化 cost 与 |S11|）
  front = []
  for n, c, s in pts:
    if not any((c2 <= c and s2 <= s) and (c2 < c or s2 < s) for n2, c2, s2 in pts if n2 != n):
      front.append((n, c, s))
  front.sort(key=lambda p: p[1])
  lines = ["| trial | cost | s11_db_max_in_band |", "|---|---|---|"]
  for n, c, s in front:
    lines.append(f"| {n} | {c:.4f} | {s:.2f} |")
  return lines


def _top3_sparam_lines(run_id: str, run_dir: Path, trials: list[dict]) -> list[str]:
  """五要素③top-3 S 参数叠加：复算 top-3 参数的 |S11| dB 频率表。"""
  scored = [t for t in trials if isinstance(t.get("cost"), (int, float))]
  if not scored:
    return ["- 无 trial 数据，S 参数叠加不可用"]
  top3 = sorted(scored, key=lambda t: t["cost"])[:3]
  recipe_path = run_dir / "recipe.snapshot.yaml"
  if not recipe_path.exists():
    return ["- 无配方快照，S 参数叠加不可用"]
  try:
    import yaml as _yaml
    rd = _yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    from rfauto.core.objectives import SpecEvaluator  # noqa: F401 (对称引用)
    from rfauto.optimization.optimizer import _prepare_env
    adapter, _ver, plugin_cls, _ps, setup, err = _prepare_env(rd, adapter_name="fake", adapter_kwargs=None)
    if adapter is None:
      return [f"- 适配器不可用：{err}"]
    import numpy as _np
    freqs: list[float] | None = None
    curves: list[tuple[int, list[float]]] = []
    try:
      for t in top3:
        pl = plugin_cls()
        pl.build(adapter, pl.params_model(**t.get("params", {})))
        r = adapter.solve(setup)
        if not r.success:
          continue
        net = adapter.get_sparams()
        s11 = _np.abs(net.s[:, 0, 0])
        db = 20 * _np.log10(s11 + 1e-10)
        idx = _np.linspace(0, len(db) - 1, min(9, len(db))).astype(int)
        if freqs is None:
          freqs = [round(float(x), 3) for x in _np.array(net.f)[idx] / 1e9]
        curves.append((t.get("trial_number", 0), [round(float(db[i]), 2) for i in idx]))
    finally:
      adapter.close()
  except Exception as e:
    return [f"- 复算失败：{e}"]
  if not curves:
    return ["- top-3 复算无成功解"]
  lines = ["| freq_GHz | " + " | ".join(f"trial {n} |S11| dB" for n, _ in curves) + " |",
       "|---" * (len(curves) + 1) + "|"]
  for k, fg in enumerate(freqs or []):
    lines.append(f"| {fg} | " + " | ".join(f"{cv[k]}" for _, cv in curves) + " |")
  return lines


def _baseline_lines(run_dir: Path, metrics: dict) -> list[str]:
  """五要素④基线偏差摘要：对照 tests/golden 基线（模型匹配时）。"""
  golden_path = Path("tests") / "golden" / "wilkinson_fake_baseline.json"
  if not golden_path.exists():
    return ["- 无 golden 基线文件，基线偏差摘要不可用"]
  try:
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
  except Exception:
    return ["- golden 基线解析失败"]
  base_metrics = golden.get("metrics", golden)
  lines = ["| metric | baseline | this_run | delta |", "|---|---|---|---|"]
  hit = False
  for k, bv in base_metrics.items():
    if not isinstance(bv, (int, float)):
      continue
    rv = metrics.get(k)
    if not isinstance(rv, (int, float)):
      continue
    hit = True
    lines.append(f"| {k} | {float(bv):.4f} | {float(rv):.4f} | {float(rv) - float(bv):+.4f} |")
  if not hit:
    return ["- golden 基线与本 run 无公共指标"]
  return lines


def agent_quality_summary(limit: int = 500):
  """4b 提议质量指标（历史审查补强）：接受率/改进率/否决原因分类，源自 audit.jsonl。

  Plan §3 方向 4b 验收："提议质量指标（接受率/改进率/否决原因分类）落 audit"。
  """
  audit_path = Path("runs") / "agent_proposals" / "audit.jsonl"
  if not audit_path.exists():
    return {"ok": True, "total_proposes": 0, "accepted": 0, "accept_rate": None,
        "rejections": {}, "avg_improvement": None}
  entries = []
  for line in audit_path.read_text(encoding="utf-8").strip().split("\n"):
    if not line.strip():
      continue
    try:
      entries.append(json.loads(line))
    except json.JSONDecodeError:
      continue
  entries = entries[-limit:]

  proposes = [e for e in entries if e.get("event") == "propose"]
  apply_ok = [e for e in entries if e.get("event") in ("apply", "approve") and e.get("ok")]
  rejections: dict[str, int] = {}
  for e in proposes:
    if not e.get("ok"):
      stage = str(e.get("stage", e.get("reason", "unknown")))
      rejections[stage] = rejections.get(stage, 0) + 1
  # propose 失败可能在 L1/L2 就被 api 层记录 ok=False；stage 字段兼容两种来源
  for e in entries:
    if e.get("event") == "propose" and not e.get("ok") and e.get("stage") is None:
      rejections["gate"] = rejections.get("gate", 0) + 1
  improvements = [e.get("quality", {}).get("improvement")
          for e in entries
          if e.get("event") == "apply" and e.get("ok")
          and isinstance(e.get("quality", {}).get("improvement"), (int, float))]
  total = len(proposes)
  accepted = min(len(apply_ok), total) # 同 token 重复计数防御
  avg_imp = round(sum(improvements) / len(improvements), 4) if improvements else None
  return {"ok": True, "total_proposes": total, "accepted": accepted,
      "accept_rate": round(accepted / total, 4) if total else None,
      "rejections": rejections, "avg_improvement": avg_imp,
      "n_improvement_samples": len(improvements)}


def generate_enhanced_report(run_id, *, output=None):
  """Generate enhanced tuning report (Direction 8c, 五要素全量).

  五要素（Plan §3 方向 8c 验收口径）：①收敛曲线 ②Pareto 前沿 ③top-3 方案
  S 参数叠加 ④基线偏差摘要 ⑤诊断标注。早期审查修复——旧实现只有摘要
  +指标+诊断，五要素缺四。
  """
  run_dir = Path("runs") / run_id
  metrics_path = run_dir / "results" / "metrics.json"
  if not metrics_path.exists():
    return {"ok": False, "errors": [f"Run not found: {run_id}"]}
  metrics_data = json.loads(metrics_path.read_text(encoding="utf-8"))
  metrics = metrics_data.get("metrics", {})
  diagnosis = metrics_data.get("diagnosis", {})
  params = metrics_data.get("params", {})
  cost = metrics_data.get("cost", 0.0)
  trials = _load_run_trials(run_dir)

  lines = [f"# Tuning Report: {run_id}", "", "## 1. Summary",
       f"- Cost: {cost:.4f}", f"- Parameters: {params}", "", "## 2. Metrics"]
  for k, v in sorted(metrics.items()):
    if isinstance(v, (int, float)):
      lines.append(f"- {k}: {v:.4f}")
  lines.extend(["", "## 3. Convergence（要素①收敛曲线）"])
  lines.extend(_convergence_lines(trials))
  lines.extend(["", "## 4. Pareto Front（要素②前沿）"])
  lines.extend(_pareto_lines(trials))
  lines.extend(["", "## 5. Top-3 S-Parameters（要素③叠加）"])
  lines.extend(_top3_sparam_lines(run_id, run_dir, trials))
  lines.extend(["", "## 6. Baseline Deviation（要素④基线偏差）"])
  lines.extend(_baseline_lines(run_dir, metrics))
  lines.extend(["", "## 7. Diagnosis（要素⑤诊断标注）"])
  if diagnosis and diagnosis.get("diagnoses"):
    for d in diagnosis["diagnoses"]:
      lines.append(f"- [{d.get('severity','?')}] {d.get('rule_id','?')}: {d.get('description','')}")
  else:
    lines.append("- No diagnosis triggers (all rules passed)")
  lines.extend(["", "## 8. Reproducibility", f"- Run ID: {run_id}",
         f"- Git SHA: {metrics_data.get('git_sha', 'unknown')}", ""])
  report_text = "\n".join(lines)
  if output:
    Path(output).write_text(report_text, encoding="utf-8")
    return {"ok": True, "report": str(output), "run_id": run_id}
  return {"ok": True, "report_text": report_text, "run_id": run_id}


def hfss_import_recipe(project_path, design_name=None, *, version="2026.1",
            non_graphical=True, out=None):
  """HFSS 工程导入器：读取 .aedt 的设计变量 /
  Optimetrics 扫参范围 / Setup-Sweep / 端口，生成配方草稿（hfss_var_map +
  参数范围），供 UI 展示与 agent 提案-审批链路继续调优。"""
  from rfauto.adapters.hfss_import import import_project_spec, spec_to_recipe_draft
  from rfauto.infra.recipe_guard import write_recipe_yaml

  spec = import_project_spec(project_path, design_name, version=version,
                non_graphical=non_graphical)
  draft = spec_to_recipe_draft(spec)
  result = {"ok": bool(spec.get("ok")), "spec": spec, "recipe": draft.get("recipe")}
  if not spec.get("ok"):
    result["error"] = spec.get("error")
    return result
  if out:
    # out 由用户显式指定（--out），属显式保存入口；写出经守卫统一出口
    written = write_recipe_yaml(out, result["recipe"], explicit=True)
    result["recipe_path"] = str(written)
    if getattr(written, "overwritten", False):
      # R2-D-03：explicit 覆盖受保护 recipes/ 既有原件时如实标注
      result["overwritten"] = True
  return result
