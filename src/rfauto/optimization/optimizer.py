"""Optuna 外环优化器（P2-D2）—— TPE 采样 + SQLite 持久化 + 保守剪枝 + 断点续跑。

设计决策：
- 剪枝保守化（ADR-0004 D1）：仅 solve 失败即剪，不做激进 MedianPruner
- SQLite storage 天然支持断点续跑（load_if_exists=True）
- 适配器连接一次，每个 trial 只更新变量 + solve（避免重复 connect/build）
- 所有 trial 结果存入 run_dir/trials/ 便于事后审计
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import optuna
import yaml

from rfauto.core.objectives import DEFAULT_METRIC_KEY, MetricOp, Objective, SpecEvaluator
from rfauto.core.parameters import ParameterSystem, ParamValue

logger = logging.getLogger(__name__)

_C = 3.0e8  # 光速 m/s

# 单目标外环采样器固定种子（TPE/CMA-ES 同源；也作为缓存 manifest 的 seed
# provenance——#158：seed 不进缓存键，只记来源）
SAMPLER_SEED = 42

# Y3 批次 BO（DP-13）：批内归一化最小距离门（[0,1]^d 欧氏）。低于该门视为
# 扎堆点（constant_liar 未拉开），弃批重 ask 一次，再犯如实降级串行。
# 门值预声明 runs/df6_dp13/criteria.md §Y3。
BATCH_MIN_DIST = 0.01


# ─── Y3 批 ask/tell 内核 ─────────────────────────────────────────────────────

def _batch_min_distance(
    params_list: list[dict[str, float]],
    names: list[str],
    low: list[float],
    high: list[float],
) -> float:
    """批内最小成对距离（归一化 [0,1]^d 欧氏）。单点批返回 inf。"""
    import numpy as np

    if len(params_list) < 2:
        return float("inf")
    span = np.asarray([
        max(float(high[i]) - float(low[i]), 1e-12)
        for i in range(len(names))])
    pts = np.asarray([
        [(float(p[n]) - float(low[i])) / span[i] for i, n in enumerate(names)]
        for p in params_list])
    diffs = pts[:, None, :] - pts[None, :, :]
    dmat = np.sqrt((diffs ** 2).sum(-1))
    iu = np.triu_indices(len(pts), k=1)
    return float(dmat[iu].min())


def _ask_batch(
    study: optuna.Study,
    param_ranges: dict[str, dict[str, Any]],
    k: int,
) -> list[tuple[optuna.Trial, dict[str, float]]]:
    """ask k 点（ask+suggest 交错：先 ask 的 RUNNING 带参供 constant_liar 惩罚）。"""
    batch: list[tuple[optuna.Trial, dict[str, float]]] = []
    for _ in range(k):
        trial = study.ask()
        batch.append((trial, _suggest_params(trial, param_ranges)))
    return batch


def _discard_batch(
    study: optuna.Study,
    batch: list[tuple[optuna.Trial, dict[str, float]]],
    reason: str,
) -> None:
    """弃批：未评估的 ask'd trial 如实记 FAIL（带原因 attr），不占预算。"""
    for trial, _params in batch:
        trial.set_user_attr("batch_discarded", reason)
        study.tell(trial, state=optuna.trial.TrialState.FAIL)


def _run_batched(
    study: optuna.Study,
    objective_fn: Callable[[optuna.Trial], float],
    param_ranges: dict[str, dict[str, Any]],
    *,
    batch_size: int,
    eff_max_trials: int,
    eff_max_wall_s: float | None,
    start_time: float,
    min_dist: float = BATCH_MIN_DIST,
) -> dict[str, Any]:
    """批 ask/tell 优化循环（Y3）：ask k 点全 RUNNING → 串行逐个 tell。

    - 批内归一化最小距离低于 min_dist：弃批重 ask 一次；再犯如实降级串行
      （k=1 继续至预算完）；
    - 弃批 trial 记 FAIL（batch_discarded attr）不计预算（未消耗求解）；
    - 超时/预算与 study.optimize(timeout, n_trials) 同语义；
    - 异常语义镜像 study.optimize：TrialPruned→PRUNED，其余异常→FAIL 后
      原样上抛。
    """
    names = sorted(param_ranges.keys())
    low = [float(param_ranges[n]["low"]) for n in names]
    high = [float(param_ranges[n]["high"]) for n in names]

    def timed_out() -> bool:
        return eff_max_wall_s is not None and (
            time.time() - start_time) >= eff_max_wall_s

    notes: dict[str, Any] = {
        "batch_size": int(batch_size), "gate": float(min_dist),
        "n_batches": 0, "re_ask": 0, "degraded_serial": False,
        "discarded_by_gate": 0, "min_batch_distance": None,
    }
    remaining = int(eff_max_trials)
    while remaining > 0 and not timed_out():
        k = min(1 if notes["degraded_serial"] else batch_size, remaining)
        batch = _ask_batch(study, param_ranges, k)
        notes["n_batches"] += 1
        dist = _batch_min_distance(
            [p for _, p in batch], names, low, high)
        if k >= 2 and (notes["min_batch_distance"] is None
                       or dist < notes["min_batch_distance"]):
            notes["min_batch_distance"] = dist
        if k >= 2 and dist < min_dist:
            if notes["re_ask"] < 1:
                # 首犯：弃批重 ask 一次
                notes["re_ask"] += 1
                notes["discarded_by_gate"] += k
                _discard_batch(study, batch, "min_dist_violation_re_ask")
                continue
            # 再犯：如实降级串行
            notes["degraded_serial"] = True
            notes["discarded_by_gate"] += k
            _discard_batch(study, batch, "min_dist_violation_degrade_serial")
            continue
        for trial, _params in batch:
            if timed_out():
                _discard_batch(study, [(trial, _params)], "wall_timeout")
                continue
            try:
                value = objective_fn(trial)
            except optuna.TrialPruned:
                study.tell(trial, state=optuna.trial.TrialState.PRUNED)
            except Exception:
                study.tell(trial, state=optuna.trial.TrialState.FAIL)
                raise
            else:
                study.tell(trial, value)
            remaining -= 1
    return notes


# ─── 参数范围提取 ─────────────────────────────────────────────────────────────

def extract_param_ranges(recipe_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """从配方提取可优化参数的搜索范围。

    优先级：
    1. recipe.optimization.params（显式定义）
    2. recipe.params.<name>.bounds（ParamValue.bounds）
    3. 跳过（无可优化参数）

    Returns:
        {param_name: {"low": float, "high": float, "log"?: bool}}
    """
    ranges: dict[str, dict[str, Any]] = {}

    # 来源 1：optimization 段
    opt_section = recipe_data.get("optimization", {})
    if "params" in opt_section:
        for name, spec in opt_section["params"].items():
            if isinstance(spec, dict) and "low" in spec and "high" in spec:
                ranges[name] = {
                    "low": float(spec["low"]),
                    "high": float(spec["high"]),
                    "log": bool(spec.get("log", False)),
                }
            elif isinstance(spec, (list, tuple)) and len(spec) == 2:
                ranges[name] = {"low": float(spec[0]), "high": float(spec[1])}

    # 来源 2：params 段的 bounds（仅对数值参数）
    params_section = recipe_data.get("params", {})
    for name, val in params_section.items():
        if name in ranges:
            continue
        if isinstance(val, dict):
            bounds = val.get("bounds")
            value = val.get("value")
            if (
                bounds
                and isinstance(bounds, (list, tuple))
                and len(bounds) == 2
                and isinstance(value, (int, float))
            ):
                ranges[name] = {"low": float(bounds[0]), "high": float(bounds[1])}

    return ranges


def make_study_name(recipe_path: str | Path) -> str:
    """从配方路径 + 内容生成确定性 study 名称。"""
    path = Path(recipe_path)
    if path.exists():
        content = path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()[:8]
    else:
        content_hash = "unknown"
    name = f"tune_{path.stem}_{content_hash}"
    return name[:80]


def get_storage_path() -> str:
    """返回 Optuna SQLite storage 路径。"""
    db_dir = Path("runs") / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(db_dir / 'optuna.db').as_posix()}"


# ─── 目标函数构建 ─────────────────────────────────────────────────────────────

def _suggest_params(
    trial: optuna.Trial,
    param_ranges: dict[str, dict[str, Any]],
) -> dict[str, float]:
    """在 trial 中建议参数值。"""
    params: dict[str, float] = {}
    for name, spec in sorted(param_ranges.items()):
        low = float(spec["low"])
        high = float(spec["high"])
        log = bool(spec.get("log", False))
        step = spec.get("step")
        if step:
            params[name] = trial.suggest_float(name, low, high, step=float(step), log=log)
        else:
            params[name] = trial.suggest_float(name, low, high, log=log)
    return params


def trial_constraint_values(trial: Any) -> list[float]:
    """Optuna constraints_func（E10）：从 trial user_attrs 读约束违约量。

    Optuna 软约束语义（官方 FAQ / issue #4265）：返回值 ≤0 视为可行。
    本引擎的违约量恒 ≥0 且 0=可行边界，直接透传即满足该语义；旧 study
    断点续跑的 trial 无 constraint_values 记录，视为可行 [0.0]。
    """
    vals = trial.user_attrs.get("constraint_values")
    if not vals:
        return [0.0]
    return [float(v) for v in vals]


def _trial_is_feasible(trial: Any) -> bool:
    """结果汇总用的可行性判定（E10）：constraint_values 全部 ≤0=可行。

    无 constraint_values 记录的旧 trial 与 constraints_func 口径一致，
    视为可行（缺失视为可行，兼容旧 study 断点续跑）。
    """
    vals = trial.user_attrs.get("constraint_values")
    if vals is None:
        return True
    return all(float(v) <= 0.0 for v in vals)


def _record_constraints(
    trial: optuna.Trial,
    metrics: dict[str, float],
    constraints: list[Objective] | None,
) -> list[float]:
    """逐 trial 约束评估（E10）：违约量写 user_attrs，供 TPE 软约束与结果汇总。

    每条约束用 SpecEvaluator.evaluate_objectives(metrics, [约束]) 算违约量
    （>0=违约，0=可行边界）；写入 constraint_values 与 feasible 两个 attr。
    无约束时返回空列表、不写 attr（行为与既有完全一致）。
    """
    if not constraints:
        return []
    cvals = [SpecEvaluator.evaluate_objectives(metrics, [c]) for c in constraints]
    trial.set_user_attr("constraint_values", cvals)
    trial.set_user_attr("feasible", all(v <= 0.0 for v in cvals))
    return cvals


def build_objective(
    adapter: Any,
    param_system: ParameterSystem,
    param_ranges: dict[str, dict[str, Any]],
    objectives: list[Objective],
    setup_name: str,
    trial_dir: Path | None = None,
    name_map: dict[str, str] | None = None,
    result_cache: Any | None = None,
    cache_scope: dict[str, Any] | None = None,
    constraints: list[Objective] | None = None,
) -> Callable[[optuna.Trial], float]:
    """构建 Optuna 目标函数。

    每个 trial：
    1. 建议参数值
    2. 更新 param_system → 按 name_map（配方参数名→设计变量名）写入 adapter
    3. solve → 获取 S 参数（ResultCache 命中时跳过求解，同参数秒回——阶段 0.4）
    4. 计算指标 + cost
    5. 保守剪枝：仅 solve 失败即剪
    6. E10：有 constraints 时逐 trial 评估违约量并写 user_attrs
       （constraint_values / feasible，≤0=可行）；cost 仍只含 objectives
       贡献，约束通过 Optuna 软约束通道（constraints_func）生效。
       指标计算按 objectives+constraints 并集取，保证约束指标恒有产物。

    cache_scope（内容寻址）：``{"study": str, "seed": str, "components":
    dict}``——components 为 ResultCache.components_for_run 派生的固定成分
    （params_canonical_json 逐 trial 由 param_system **全参**规范 JSON 填充，
    非仅调谐参数：两配方固定参数不同、调谐参数相同时旧键会串台）；
    study/seed 只作 provenance（#158，不进键）。
    """
    # 指标计算口径：objectives + constraints 并集（无约束时即 objectives，
    # 行为逐字节不变）。cost 只由 objectives 决定。
    eval_specs: list[Objective] = objectives + list(constraints or [])

    def objective(trial: optuna.Trial) -> float:
        # 1. 建议参数
        params = _suggest_params(trial, param_ranges)

        # 2. 更新参数系统（按插件映射写设计变量，缺映射=调常数空转）
        param_system.update(params)
        param_system.write_to_adapter(adapter, name_map=name_map)

        # ResultCache：同参数重评估直接复用 Touchstone（HFSS 级秒回，#148）。
        # compute_content_key（13 成分分列）+ lookup 带 provenance；
        # 同几何异 study 命中同一条目（cross_study=True）。热循环里不传
        # components 给 lookup（why_miss 需扫全部条目 manifest，逐 trial 做
        # 是 O(N) 观测开销），why_miss 走 run_once / dry_run 单次路径。
        # 键计算/查询层异常降级真算（C18，#105：缓存不做主路径故障点）——
        # cache_hit_error 记入 trial user_attrs 供审计，真算路径零感知。
        cache_key = None
        cache_components: dict[str, str] | None = None
        cache_study = ""
        cache_seed = ""
        found: dict[str, Any] | None = None
        if result_cache is not None and cache_scope:
            cache_study = str(cache_scope.get("study", "") or "")
            cache_seed = str(cache_scope.get("seed", "") or "")
            cache_components = dict(cache_scope.get("components") or {})
            try:
                cache_components["params_canonical_json"] = param_system.to_canonical_json()
                cache_key = result_cache.compute_content_key(**cache_components)
                found = result_cache.lookup(cache_key, study=cache_study, seed=cache_seed)
            except Exception as exc:  # 缓存层故障 → 直接真算，不 raise（#105）
                trial.set_user_attr("cache_hit_error", str(exc))
                found = None
            cached_dir = (found or {}).get("path")
            if cached_dir is not None:
                try:
                    import skrf

                    snp_files = sorted(Path(cached_dir).glob("params.s*p"))
                    network = skrf.Network(str(snp_files[0]))
                    metrics = SpecEvaluator.compute_metrics(
                        network, eval_specs)
                    cost = SpecEvaluator.evaluate_objectives(
                        metrics, objectives)
                    cvals = _record_constraints(trial, metrics, constraints)
                    trial.set_user_attr("metrics", metrics)
                    trial.set_user_attr("cost", cost)
                    trial.set_user_attr("cache_hit", True)
                    trial.set_user_attr("cache_provenance", found["provenance"])
                    trial.set_user_attr("cache_cross_study", bool(found["cross_study"]))
                    trial.set_user_attr("cache_origin_study", found["origin_study"])
                    if trial_dir is not None:
                        trial_dir.mkdir(parents=True, exist_ok=True)
                        payload: dict[str, Any] = {
                            "trial_number": trial.number,
                            "params": params, "metrics": metrics,
                            "cost": cost, "cache_hit": True,
                            "cache_provenance": found["provenance"],
                            "cache_cross_study": bool(found["cross_study"]),
                            "cache_origin_study": found["origin_study"],
                        }
                        if constraints:
                            payload["constraint_values"] = cvals
                        (trial_dir / f"trial_{trial.number}.json").write_text(
                            json.dumps(payload, indent=2, ensure_ascii=False),
                            encoding="utf-8")
                    return cost
                except Exception as exc:  # 缓存损坏按 miss 处理（#105 降级）
                    trial.set_user_attr("cache_hit_error", str(exc))

        # 3. solve（R5 自愈：掉线时 ensure_connected 后重试一次）
        from rfauto.pipeline.self_heal import solve_with_self_heal
        try:
            report = solve_with_self_heal(adapter, setup_name)
        except Exception as e:
            trial.set_user_attr("error", str(e))
            raise optuna.TrialPruned() from e

        if not report.success:
            trial.set_user_attr("solve_message", report.message)
            raise optuna.TrialPruned()

        # 4. 获取 S 参数 + 计算指标（gain_db 目标时取远场——远场指标进 DSL）
        #    提取/解析类异常（如扩展名 rank 不符）按失败剪枝，不炸整个 study
        try:
            network = adapter.get_sparams()
            far_field = None
            if any(o.metric == "gain_db" for o in eval_specs):
                try:
                    far_field = adapter.get_far_field(setup_name)
                except Exception:
                    far_field = None
            metrics = SpecEvaluator.compute_metrics(network, eval_specs, far_field=far_field)
        except Exception as e:
            trial.set_user_attr("error", f"指标提取失败: {e}")
            raise optuna.TrialPruned() from e
        cost = SpecEvaluator.evaluate_objectives(metrics, objectives)

        # 结果入缓存（best-effort：失败不影响主路径，#105）。components/study/
        # seed 记入 manifest（why_miss 比对 + 跨 study provenance），均不参与键。
        if result_cache is not None and cache_key and cache_components is not None:
            try:
                import tempfile

                with tempfile.TemporaryDirectory() as _td:
                    n_ports = network.s.shape[1]
                    snp = Path(_td) / f"params.s{n_ports}p"
                    network.write_touchstone(str(snp))
                    result_cache.store(
                        cache_key, _td,
                        model_name=cache_components.get("model_name", ""),
                        study=cache_study, seed=cache_seed,
                        components=cache_components,
                    )
                trial.set_user_attr("cache_stored", True)
            except Exception:
                pass

        # 记录 trial 信息
        cvals = _record_constraints(trial, metrics, constraints)
        trial.set_user_attr("metrics", metrics)
        trial.set_user_attr("cost", cost)

        # 写入 trial 审计文件
        if trial_dir is not None:
            trial_dir.mkdir(parents=True, exist_ok=True)
            trial_file = trial_dir / f"trial_{trial.number}.json"
            trial_data: dict[str, Any] = {
                "trial_number": trial.number,
                "params": params,
                "metrics": metrics,
                "cost": cost,
            }
            if constraints:
                trial_data["constraint_values"] = cvals
            trial_file.write_text(
                json.dumps(trial_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        return cost

    return objective


# ─── 配方环境准备（单/多目标共用） ────────────────────────────────────────────

def _prepare_env(
    recipe_data: dict[str, Any],
    *,
    adapter_name: str,
    adapter_kwargs: dict[str, Any] | None,
):
    """创建适配器 + 插件构建 + 参数系统（单/多目标优化共用）。

    Returns:
        (adapter, aedt_version, plugin_cls, param_system, setup_name, error)
        失败时 adapter 为 None，error 为错误信息。
    """
    adapter, aedt_version = _create_adapter(adapter_name, adapter_kwargs, recipe_data)
    if adapter is None:
        return None, "", None, None, "main_setup", f"适配器创建失败: {adapter_name}"

    model_name = recipe_data.get("model", "")
    try:
        from rfauto.models.registry import get as get_plugin_cls
        plugin_cls = get_plugin_cls(model_name)
    except KeyError:
        adapter.close()
        return None, "", None, None, "main_setup", f"未知模型: {model_name}"

    params_data = recipe_data.get("params", {})
    param_values: dict[str, ParamValue] = {}
    for k, v in params_data.items():
        if isinstance(v, dict):
            param_values[k] = ParamValue(
                name=k,
                value=v.get("value", 0),
                unit=v.get("unit", "mm"),
                bounds=tuple(v["bounds"]) if v.get("bounds") else None,
            )
        else:
            param_values[k] = ParamValue(name=k, value=v)

    param_system = ParameterSystem(param_values)

    try:
        plugin = plugin_cls()
        from rfauto.pipeline.self_heal import build_with_self_heal

        build_with_self_heal(lambda: plugin.build(
            adapter,
            plugin.params_model(**{
                k: (v["value"] if isinstance(v, dict) else v) for k, v in params_data.items()
            }),
        ))
        param_system.write_to_adapter(adapter, name_map=getattr(plugin_cls, "hfss_var_map", {}))
    except Exception as e:
        adapter.close()
        return None, "", None, None, "main_setup", f"模型构建失败: {e}"

    # setup 通道（C4 修复）：HFSS 模式按配方 setup 段创建 Setup + Sweep 并用
    # 返回名求解。FakeAdapter 忽略 setup 名，行为不变。
    setup_name = "main_setup"
    if adapter_name == "hfss":
        setup_name = adapter.configure_setup(recipe_data.get("setup", {}))

    return adapter, aedt_version, plugin_cls, param_system, setup_name, ""


# ─── 多目标优化（NSGA-II / Pareto 前沿）—— 计划内缺口 2 ──────────────────────

def run_multi_optimization(
    recipe_path: str | Path,
    *,
    adapter_name: str = "fake",
    n_gen: int = 20,
    pop_size: int = 12,
    seed: int = 42,
    adapter_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运行 NSGA-II 多目标优化，产出 Pareto 前沿（P5 验收："双目标出 Pareto 前沿"）。

    目标向量定义：每个 objective 的"违约量"（violation，越小越好）——
    与单目标 cost 的逐项贡献一致，多目标即把逐项贡献拆成向量分别最小化。
    求解失败的 trial 返回大罚向量（1e3），不进入前沿。

    E9 约束 Pareto：配方 optimization.constraints（元素结构同 objectives，
    与单目标 TPE 路径同一段）非空时，逐点违约向量作 pymoo G（引擎口径
    ≥0、0=可行边界，直接映射 G≤0=可行，同义无需翻转），前沿逐点回记
    constraint_values/feasible；无约束配方不建 G、不添约束键，行为与
    旧实现一致。前沿另落 results/pareto_front.json（机器可读产物，此前
    只有 PNG）。
    """
    import numpy as np

    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir, record_run, snapshot_recipe, write_meta
    from rfauto.optimization.multiobj_backend import MultiObjBackend

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方文件不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    param_ranges = extract_param_ranges(recipe_data)
    if not param_ranges:
        return {"ok": False, "errors": ["无可选优化参数"]}

    objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
    if len(objectives) < 2:
        return {"ok": False, "errors": ["多目标优化需要至少 2 个 objectives"]}

    # E9 约束段：optimization.constraints（与 run_optimization 同一段、同结构）
    constraints: list[Objective] = []
    for c in (recipe_data.get("optimization") or {}).get("constraints") or []:
        if not isinstance(c, dict):
            return {"ok": False, "errors": [f"constraints 元素须为 dict: {c!r}"]}
        constraints.append(Objective(**c))
    use_constraints = bool(constraints)

    run_id = generate_run_id()
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    snapshot_recipe(run_dir, recipe_data)

    adapter, aedt_version, _plugin_cls, param_system, setup_name, err = _prepare_env(
        recipe_data, adapter_name=adapter_name, adapter_kwargs=adapter_kwargs,
    )
    if adapter is None:
        return {"ok": False, "errors": [err]}
    model_name = recipe_data.get("model", "")

    names = sorted(param_ranges.keys())
    low = np.array([param_ranges[n]["low"] for n in names])
    high = np.array([param_ranges[n]["high"] for n in names])
    start_time = time.time()

    eval_specs = objectives + constraints
    # E9：x → 违约向量缓存（前沿点的 X 即已评估的精英个体，浮点逐位一致；
    # 12 位舍入防哈希边界。未命中如实记 None，不重解、不编造）。
    viol_cache: dict[tuple, list[float]] = {}

    def evaluate(x: np.ndarray) -> np.ndarray:
        params = {n: float(low[i] + x[i] * (high[i] - low[i])) for i, n in enumerate(names)}
        param_system.update(params)
        param_system.write_to_adapter(adapter, name_map=getattr(_plugin_cls, "hfss_var_map", {}))
        try:
            report = adapter.solve(setup_name)
            if not report.success:
                return np.full(len(objectives), 1e3)
            network = adapter.get_sparams()
        except Exception:
            return np.full(len(objectives), 1e3)
        # 指标按 objectives+constraints 并集取（约束指标键恒有产物，
        # 镜像 build_objective 的 eval_specs 口径）；cost 向量仍只由
        # objectives 决定。
        metrics = SpecEvaluator.compute_metrics(network, eval_specs)
        vec = []
        for obj in objectives:
            vec.append(_single_objective_cost(metrics, obj))
        if use_constraints:
            viol = [_single_objective_cost(metrics, c) for c in constraints]
            viol_cache[tuple(np.round(np.asarray(x, dtype=float), 12))] = viol
        return np.array(vec)

    def constraint_vec(x: np.ndarray) -> np.ndarray:
        key = tuple(np.round(np.asarray(x, dtype=float), 12))
        cached = viol_cache.get(key)
        if cached is None:
            # 未命中（理论不发生：G 只在 _evaluate 内同步调用）——
            # 保守按可行边界处理并留告警，不抛异常炸进化
            logger.warning("约束缓存未命中 x=%r（应为 _evaluate 同步调用）", x)
            cached = [0.0] * len(constraints)
            viol_cache[key] = cached
        return np.array(cached)

    backend = MultiObjBackend(
        n_objectives=len(objectives),
        n_variables=len(names),
        bounds=(np.zeros(len(names)), np.ones(len(names))),
    )
    try:
        result_multi = backend.optimize(
            evaluate, n_gen=n_gen, pop_size=pop_size, seed=seed,
            constraint_fn=constraint_vec if use_constraints else None,
            n_constraints=len(constraints),
        )
    finally:
        adapter.close()

    obj_names = [o.metric for o in objectives]
    pareto_points = []
    missing_constraint_points = 0
    for vars_x, objs in zip(
        result_multi.get("pareto_variables", []), result_multi.get("pareto_front", []),
        strict=False,
    ):
        point: dict[str, Any] = {
            "params": {n: float(low[i] + vars_x[i] * (high[i] - low[i])) for i, n in enumerate(names)},
            "objectives": {obj_names[i]: float(objs[i]) for i in range(len(obj_names))},
        }
        if use_constraints:
            key = tuple(np.round(np.asarray(vars_x, dtype=float), 12))
            viol = viol_cache.get(key)
            if viol is None:
                missing_constraint_points += 1
                point["constraint_values"] = None
                point["feasible"] = None
            else:
                point["constraint_values"] = [float(v) for v in viol]
                point["feasible"] = all(float(v) <= 0.0 for v in viol)
        pareto_points.append(point)

    elapsed = time.time() - start_time
    result: dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "algorithm": "nsga2",
        "objective_names": obj_names,
        "param_names": names,
        "n_gen": n_gen,
        "pop_size": pop_size,
        "n_pareto": result_multi.get("n_pareto", len(pareto_points)),
        "n_evaluations": result_multi.get("n_evaluations", 0),
        "elapsed_s": round(elapsed, 1),
        "pareto_points": pareto_points,
    }
    if use_constraints:
        result["n_constraints"] = len(constraints)
        if missing_constraint_points:
            result.setdefault("warnings", []).append(
                f"{missing_constraint_points} 个前沿点约束缓存未命中，"
                "constraint_values 如实记 null（#105）")
    hv_trace = result_multi.get("hv_convergence")
    if hv_trace is not None:
        result["hv_convergence"] = hv_trace

    # E9：前沿机器可读产物（此前只有 PNG；ui_service.pareto_view 双源直读）
    results_dir = run_dir / "results"
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        front_doc: dict[str, Any] = {
            "run_id": run_id,
            "algorithm": "nsga2",
            "objective_names": obj_names,
            "param_names": names,
            "n_pareto": result["n_pareto"],
            "n_evaluations": result["n_evaluations"],
            "pareto_points": pareto_points,
            "hv_convergence": hv_trace,
        }
        if use_constraints:
            front_doc["constraint_names"] = [c.metric for c in constraints]
        (results_dir / "pareto_front.json").write_text(
            json.dumps(front_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # 观测性落盘 best-effort（#105）
        result.setdefault("warnings", []).append(
            f"pareto_front.json 落盘失败（best-effort）: {exc}")

    # Pareto 前沿图（双目标时）
    if result_multi.get("pareto_front"):
        import matplotlib  # noqa: F401  (Agg 后端在 report 导入时统一设置)

        from rfauto.infra.report import plot_pareto_front
        figs_dir = run_dir / "results" / "figs"
        figs_dir.mkdir(parents=True, exist_ok=True)
        plot_pareto_front(result_multi["pareto_front"], obj_names, figs_dir)

    write_meta(run_dir, {
        "run_id": run_id,
        "model": model_name,
        "adapter": adapter_name,
        "aedt_version": aedt_version,
        "status": "done",
        "algorithm": "nsga2",
        "n_pareto": result["n_pareto"],
    })
    record_run(record={
        "run_id": run_id,
        "model": model_name,
        "adapter": adapter_name,
        "status": "done",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": {"n_pareto": result["n_pareto"]},
    })
    return result


# ─── 公差分析编排（孤岛接线：optimization/tolerance.py 原无生产入口） ─────────

def run_tolerance_analysis(
    recipe_path: str | Path,
    *,
    adapter_name: str = "fake",
    n_samples: int = 200,
    tolerances: dict[str, float] | None = None,
    adapter_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`rfauto tolerance <recipe>`——以 objectives 为规格做 Monte Carlo 良率分析。

    recipe.tolerance.tolerances（或显式参数）给各参数公差；规格由
    objectives 推导：max_below → {"max": value}，min_above → {"min": value}。
    """
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir, record_run, snapshot_recipe, write_meta
    from rfauto.optimization.tolerance import ToleranceAnalyzer

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方文件不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    tol_section = recipe_data.get("tolerance", {})
    tolerances = tolerances or tol_section.get("tolerances", {})
    if not tolerances:
        return {"ok": False, "errors": [
            "缺少公差定义：请在配方添加 tolerance.tolerances 段（如 {arm_len_mm: 0.1}）"
        ]}
    n_samples = int(tol_section.get("n_samples", n_samples))

    nominal = {
        k: (v.get("value") if isinstance(v, dict) else v)
        for k, v in recipe_data.get("params", {}).items()
        if isinstance(v.get("value") if isinstance(v, dict) else v, (int, float))
    }
    missing = [t for t in tolerances if t not in nominal]
    if missing:
        return {"ok": False, "errors": [f"公差参数不在配方 params 中: {missing}"]}

    objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]

    def _metric_key(metric: str) -> str:
        # 规格键必须对齐 SpecEvaluator.compute_metrics 的产物键名
        return DEFAULT_METRIC_KEY.get(metric, metric)

    specs: dict[str, dict[str, Any]] = {}
    for obj in objectives:
        if obj.op == MetricOp.MAX_BELOW and isinstance(obj.value, (int, float)):
            specs[_metric_key(obj.metric)] = {"max": obj.value}
        elif obj.op == MetricOp.MIN_ABOVE and isinstance(obj.value, (int, float)):
            specs[_metric_key(obj.metric)] = {"min": obj.value}
    if not specs:
        return {"ok": False, "errors": ["objectives 中无可推导规格（需 max_below/min_above）"]}

    run_id = generate_run_id()
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    snapshot_recipe(run_dir, recipe_data)

    adapter, aedt_version, _plugin_cls, param_system, setup_name, err = _prepare_env(
        recipe_data, adapter_name=adapter_name, adapter_kwargs=adapter_kwargs,
    )
    if adapter is None:
        return {"ok": False, "errors": [err]}
    var_map = getattr(_plugin_cls, "hfss_var_map", {})

    def objective_fn(params: dict[str, float]) -> dict[str, float]:
        param_system.update(params)
        param_system.write_to_adapter(adapter, name_map=var_map)
        report = adapter.solve(setup_name)
        if not report.success:
            raise RuntimeError(f"求解失败: {report.message}")
        network = adapter.get_sparams()
        return SpecEvaluator.compute_metrics(network, objectives)

    try:
        analyzer = ToleranceAnalyzer(n_samples=n_samples)
        result = analyzer.analyze(nominal, tolerances, objective_fn, specs)
    finally:
        adapter.close()

    result.update({
        "run_id": run_id,
        "run_dir": str(run_dir),
        "nominal_params": nominal,
        "tolerances": tolerances,
        "specs": specs,
    })
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "results" / "tolerance.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8",
    )
    write_meta(run_dir, {
        "run_id": run_id,
        "model": recipe_data.get("model", ""),
        "adapter": adapter_name,
        "aedt_version": aedt_version,
        "status": "done",
        "analysis": "tolerance",
        "metrics": {"yield_rate": result["yield_rate"]},
    })
    record_run(record={
        "run_id": run_id,
        "model": recipe_data.get("model", ""),
        "adapter": adapter_name,
        "status": "done",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": {"yield_rate": result["yield_rate"]},
    })
    return result


def _single_objective_cost(metrics: dict[str, float], obj: Objective) -> float:
    """单个 objective 的违约量（与 SpecEvaluator.evaluate_objectives 逐项一致）。"""
    val = None
    for k in SpecEvaluator.metric_key_candidates(obj.metric, obj.op):
        if k in metrics:
            val = metrics[k]
            break
    if val is None:
        return 0.0
    if obj.op in (MetricOp.MAX_BELOW, MetricOp.BANDWIDTH):
        threshold = obj.value if isinstance(obj.value, (int, float)) else obj.value[0]
        return obj.weight * max(0.0, val - threshold)
    if obj.op == MetricOp.MIN_ABOVE:
        threshold = obj.value if isinstance(obj.value, (int, float)) else obj.value[0]
        return obj.weight * max(0.0, threshold - val)
    if obj.op == MetricOp.MEAN_WITHIN and isinstance(obj.value, list) and len(obj.value) == 2:
        low_v, high_v = obj.value
        if val < low_v:
            return obj.weight * (low_v - val)
        if val > high_v:
            return obj.weight * (val - high_v)
    return 0.0


# ─── 主入口 ───────────────────────────────────────────────────────────────────



def run_optimization(
    recipe_path: str | Path,
    *,
    adapter_name: str = "fake",
    max_trials: int = 60,
    study_name: str | None = None,
    max_wall_s: float | None = None,
    adapter_kwargs: dict[str, Any] | None = None,
    sampler: str = "tpe",
    warm_start: list[dict[str, Any]] | None = None,
    seed: int = SAMPLER_SEED,
    cache: bool | None = None,
    batch_size: int = 1,
) -> dict[str, Any]:
    """运行 Optuna 优化外环（sampler: "tpe" | "cmaes"，计划内缺口 5）。

    seed（参数化）：采样器随机种子，缺省沿用模块常量 SAMPLER_SEED=42
    （行为不变）；显式给不同 seed 即换搜索轨迹（配对实验/新轨迹 #158，
    同 seed+同 study 复用缓存秒回属合法配对）。seed 同时写入缓存 provenance。

    cache（C18 三态开关，plan §2.3 双关语义）：``None``（缺省，行为不变）由
    ``RFAUTO_CACHE`` 环境变量裁决（off/readonly/readwrite）；``False`` 硬旁路
    ——env=readwrite 也不查不写（显式关，对拍验收用）；``True`` 仍由 env
    裁决（env=off 时维持旁路——环境关是最高优先级）。生效与否回显
    ``result["cache_enabled"]``。

    E10 约束优化：配方 optimization.constraints（元素结构同 objectives）时走
    Optuna 软约束语义（trial user_attrs 存违约量，≤0=可行；TPE
    constraints_func），结果 best 语义为"最优可行 trial"，全不可行时
    all_infeasible=True 如实报告。缺省无约束，行为不变。

    warm-start：warm_start 为非空历史点列表（每点
    ``{"params": {...}, "cost": float}``，由调用方从 dataset_service 查得）
    时，先过相似度门（warm_start.warm_start_points，负迁移防线）再 enqueue
    ——WAITING trial 在 optimize 中先被弹出执行=先验起点，结果带
    "warm_start_n"（实际注入数，门拒绝时为 0）。None=行为不变。

    Y3 批次 BO（DP-13）：``batch_size`` 缺省 1=旧路径逐字节等价
    （study.optimize 原样）；>1 走批 ask/tell（ask k 点全 RUNNING → 串行
    逐个 tell），TPE 显式 ``constant_liar=True`` 惩罚 RUNNING 防扎堆
    （Optuna 4.9 缺省 False，须显式开启）；批内归一化最小距离低于
    BATCH_MIN_DIST 弃批重 ask 一次，再犯如实降级串行；cmaes 不支持批模式
    显式报错不静默。批记账（n_batches/re_ask/degraded_serial/
    min_batch_distance/discarded_by_gate）只进 batch_size>1 的
    ``result["batch_mode"]``，缺省路径输出键集不变。
    """
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir, record_run, snapshot_recipe, write_meta

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方文件不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    param_ranges = extract_param_ranges(recipe_data)
    if not param_ranges:
        return {
            "ok": False,
            "errors": [
                "无可选优化参数。请在配方中添加 optimization.params 段或 params.<name>.bounds。"
            ],
        }

    objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
    if not objectives:
        return {"ok": False, "errors": ["缺少 objectives 段"]}

    # Y3 批次 BO：batch_size 旋钮校验（缺省 1=旧路径；<1 显式报错不静默）
    batch_size = int(batch_size)
    if batch_size < 1:
        return {"ok": False, "errors": [
            f"batch_size 必须 ≥1，收到: {batch_size}"]}

    # ─── E10 约束段：optimization.constraints（元素结构同 objectives） ────
    # 缺省=无约束，全流程行为不变。约束走 Optuna 软约束通道（≤0=可行），
    # 不并入 cost。CmaEsSampler 无约束支持：显式报错，不静默降级。
    constraints_raw: list[dict[str, Any]] = []
    constraints: list[Objective] = []
    for c in (recipe_data.get("optimization") or {}).get("constraints") or []:
        if not isinstance(c, dict):
            return {"ok": False, "errors": [f"constraints 元素须为 dict: {c!r}"]}
        constraints_raw.append(dict(c))
        constraints.append(Objective(**c))
    if constraints and sampler == "cmaes":
        return {"ok": False, "errors": [
            "sampler='cmaes' 不支持约束优化（optimization.constraints 非空）；"
            "请改用 sampler='tpe'（TPE 软约束语义，≤0=可行）或移除约束段。"
        ]}

    # ─── quota_guard：recipe.limits 配额强制（P2-D4） ─────────────────────
    # 优先级：显式参数 max_trials/max_wall_s 与 recipe.limits 取更严格者。
    from rfauto.pipeline.quota_guard import QuotaExceededError, QuotaGuard
    from rfauto.pipeline.quota_guard import QuotaLimits as GuardLimits
    recipe_limits = recipe_data.get("limits", {})
    # 有效 max_trials：min(参数, recipe.limits.max_trials)
    eff_max_trials = max_trials
    if recipe_limits.get("max_trials"):
        eff_max_trials = min(max_trials, int(recipe_limits["max_trials"]))
    # 有效墙钟（秒）：min(参数 max_wall_s, recipe.limits.max_wall_hours*3600)
    eff_max_wall_s = max_wall_s
    if recipe_limits.get("max_wall_hours"):
        eff_max_wall_s = min(
            eff_max_wall_s if eff_max_wall_s is not None else float("inf"),
            float(recipe_limits["max_wall_hours"]) * 3600.0,
        )
        if eff_max_wall_s == float("inf"):
            eff_max_wall_s = None
    guard = QuotaGuard(GuardLimits(max_trials=eff_max_trials, max_wall_hours=24.0))

    run_id = generate_run_id()
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    snapshot_recipe(run_dir, recipe_data)
    trial_dir = run_dir / "trials"

    adapter, aedt_version, _plugin_cls, param_system, setup_name, prep_err = _prepare_env(
        recipe_data, adapter_name=adapter_name, adapter_kwargs=adapter_kwargs,
    )
    if adapter is None:
        return {"ok": False, "errors": [prep_err]}

    model_name = recipe_data.get("model", "")

    if study_name is None:
        study_name = make_study_name(recipe_path)
    storage = get_storage_path()

    if sampler == "cmaes":
        if batch_size > 1:
            # Y3：CMA-ES 无 constant_liar 口径，批模式显式拒绝不静默降级
            adapter.close()
            return {"ok": False, "errors": [
                "sampler='cmaes' 不支持 batch_size>1（无 constant_liar 口径）；"
                "请改用 sampler='tpe' 或 batch_size=1。"]}
        # CMA-ES（缺口 5）：对连续低维参数空间通常优于 TPE；
        # 需要相对均匀的搜索空间，会对离散/log 参数回退随机采样（optuna 内建）
        opt_sampler = optuna.samplers.CmaEsSampler(seed=seed)
    elif sampler == "tpe":
        if batch_size > 1:
            # Y3 批模式：constant_liar 显式开启（Optuna 4.9 缺省 False），
            # RUNNING trial 以失败"谎言"惩罚防批内扎堆；约束语义照常兼容。
            opt_sampler = optuna.samplers.TPESampler(
                seed=seed, constant_liar=True,
                constraints_func=trial_constraint_values if constraints else None)
        elif constraints:
            # E10 TPE 软约束：constraints_func 从 trial user_attrs 读违约量
            # （≤0=可行，optuna 官方语义 issue #4265；缺失视为可行 [0.0]，
            # 兼容旧 study 断点续跑）
            opt_sampler = optuna.samplers.TPESampler(
                seed=seed, constraints_func=trial_constraint_values)
        else:
            opt_sampler = optuna.samplers.TPESampler(seed=seed)
    else:
        adapter.close()
        return {"ok": False, "errors": [f"未知 sampler: {sampler}（可选 tpe | cmaes）"]}
    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        sampler=opt_sampler,
        direction="minimize",
        load_if_exists=True,
    )

    existing_trials = len(study.get_trials(deepcopy=False))
    if existing_trials > 0:
        logger.info(f"恢复已有 study: {existing_trials} 个已完成 trial")

    # ResultCache 接线（内容寻址）：同几何重评估秒回；
    # RFAUTO_CACHE=off 旁路。固定成分由 components_for_run 一处派生（与
    # service.run_once 同源，#106 recipe_version/schema_version 分列）；
    # params_canonical_json 逐 trial 填充；study/seed 只作 provenance（#158）。
    # objectives 不进键——Touchstone 与目标无关，异目标 study 合法复用。
    result_cache = None
    cache_scope = None
    if cache is not False:  # 显式 cache=False=双关硬旁路（env 也打不开）
        try:
            from rfauto.infra.result_cache import ResultCache

            _rc = ResultCache()
            if _rc.enabled:
                result_cache = _rc
                cache_scope = {
                    "study": str(study_name or ""),
                    "seed": str(seed),
                    "components": _rc.components_for_run(
                        model_name=model_name,
                        recipe_data=recipe_data,
                        params_canonical_json="",  # 逐 trial 由 param_system 全参填充
                        plugin_version=f"schema{getattr(_plugin_cls, 'schema_version', '')}",
                        plugin_schema_version=getattr(_plugin_cls, "schema_version", ""),
                        adapter_version=adapter_name,
                        aedt_version=aedt_version,
                    ),
                }
        except Exception:  # 缓存不可用不影响优化主路径（#105）
            result_cache = None
            cache_scope = None

    objective_fn = build_objective(
        adapter, param_system, param_ranges, objectives,
        setup_name, trial_dir,
        name_map=getattr(_plugin_cls, "hfss_var_map", {}),
        result_cache=result_cache,
        cache_scope=cache_scope,
        constraints=constraints,
    )

    # ─── warm-start：历史先验点注入（相似度门=负迁移防线） ────────────
    # 数据获取与本环分离（分层契约）：历史点由调用方从 dataset_service 查得
    # 后以 list[dict] 注入。门通过→enqueue（WAITING trial 先跑=先验起点）；
    # 门拒绝→如实降级冷启动，不凑数注入。warm_start=None 时本段整体跳过。
    warm_start_n = 0
    if warm_start:
        from rfauto.optimization.warm_start import enqueue_warm_start, warm_start_points

        ws_gate = warm_start_points(warm_start, bounds=param_ranges)
        if ws_gate.get("ok"):
            warm_start_n = len(enqueue_warm_start(study, ws_gate["points"]))
            logger.info(f"warm-start 注入 {warm_start_n} 个历史先验点")
        else:
            logger.info(
                f"warm-start 被相似度门拒绝（{ws_gate.get('reason')}），按冷启动继续")

    start_time = time.time()
    batch_notes: dict[str, Any] | None = None
    try:
        # quota_guard 强制：eff_max_trials / eff_max_wall_s 作为硬上限
        guard.check_trial(0)
        if batch_size > 1:
            # Y3 批 ask/tell 循环（缺省 1=study.optimize 原样，逐字节等价）
            batch_notes = _run_batched(
                study, objective_fn, param_ranges,
                batch_size=batch_size, eff_max_trials=eff_max_trials,
                eff_max_wall_s=eff_max_wall_s, start_time=start_time)
        else:
            study.optimize(objective_fn, n_trials=eff_max_trials, timeout=eff_max_wall_s)
    except QuotaExceededError:
        logger.warning("达到配额上限，提前结束优化")
    except KeyboardInterrupt:
        logger.info("优化被用户中断，保留已完成结果")
    finally:
        adapter.close()

    elapsed = time.time() - start_time

    all_trials = study.get_trials(deepcopy=False)
    completed = [t for t in all_trials if t.state == optuna.trial.TrialState.COMPLETE]
    pruned = [t for t in all_trials if t.state == optuna.trial.TrialState.PRUNED]

    # study.best_trial 在零个 COMPLETE trial 时抛 ValueError（如全部被剪枝），
    # 须显式捕获后按"无最优解"处理，而不是让整个优化流程崩溃。
    try:
        best_trial = study.best_trial
    except ValueError:
        best_trial = None

    result: dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "study_name": study_name,
        "sampler": sampler,
        "storage": storage,
        "cache_enabled": result_cache is not None,
        "elapsed_s": round(elapsed, 1),
        "max_trials": max_trials,
        "trials_total": len(all_trials),
        "trials_completed": len(completed),
        "trials_pruned": len(pruned),
        "existing_trials": existing_trials,
        "max_trials_effective": eff_max_trials,
        "quota": guard.remaining_budget(len(all_trials), start_time),
        "best_params": {},
        "best_cost": None,
        "best_metrics": {},
    }

    # 显式传入 warm_start 参数时回显实际注入数（None=不加键，行为不变）
    if warm_start is not None:
        result["warm_start_n"] = warm_start_n

    # Y3：批记账只进 batch_size>1（缺省路径输出键集不变）
    if batch_size > 1 and batch_notes is not None:
        result["batch_mode"] = batch_notes

    if constraints:
        # ─── E10 引擎侧可行域修复：best 语义收敛为"最优可行 trial" ─────
        # COMPLETE 且全部违约 ≤0 中取 cost 最小者；全部不可行时如实报告
        # （best_* 置空 + all_infeasible=True），不凑绿。
        result["constraints"] = constraints_raw
        feasible_completed = [t for t in completed if _trial_is_feasible(t)]
        result["n_feasible"] = len(feasible_completed)
        best_feasible = (
            min(feasible_completed, key=lambda t: t.value)
            if feasible_completed else None
        )
        if best_feasible is not None:
            result["best_feasible"] = {
                "params": dict(best_feasible.params),
                "cost": best_feasible.value,
                "metrics": best_feasible.user_attrs.get("metrics", {}),
            }
            result["best_params"] = dict(best_feasible.params)
            result["best_cost"] = best_feasible.value
            result["best_metrics"] = best_feasible.user_attrs.get("metrics", {})
        else:
            result["best_feasible"] = None
            # "全不可行"只在确有已完成 trial 时成立——零 COMPLETE（全部
            # 求解失败被剪）是"没评上"而非"评了都不可行"（审查 P2-7：
            # 两种失败不得混同）
            if completed:
                result["all_infeasible"] = True
    elif best_trial is not None:
        result["best_params"] = dict(best_trial.params)
        result["best_cost"] = best_trial.value
        result["best_metrics"] = best_trial.user_attrs.get("metrics", {})

    # E10：有约束时 meta 的 metrics 带 feasible 标记（无可行=False）
    meta_metrics = dict(result["best_metrics"])
    if constraints:
        meta_metrics["feasible"] = bool(result.get("best_feasible"))
    write_meta(run_dir, {
        "run_id": run_id,
        "model": model_name,
        "adapter": adapter_name,
        "aedt_version": aedt_version,
        "status": "done",
        "study_name": study_name,
        "metrics": meta_metrics,
    })
    record_run(record={
        "run_id": run_id,
        "model": model_name,
        "adapter": adapter_name,
        "status": "done",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": result["best_metrics"],
    })

    return result


def run_refine(
    source_run_id: str,
    recipe_path: str | Path,
    *,
    max_trials: int = 30,
    adapter_name: str = "fake",
    study_name: str | None = None,
) -> dict[str, Any]:
    """热启动续调：以上轮 best 为起点，继续优化。"""
    run_dir = Path("runs") / source_run_id
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return {"ok": False, "errors": [f"未找到 run: {source_run_id}"]}

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    stored_study_name = meta.get("study_name")

    if study_name is None and stored_study_name:
        study_name = stored_study_name
    elif study_name is None:
        study_name = make_study_name(recipe_path)

    return run_optimization(
        recipe_path,
        adapter_name=adapter_name,
        max_trials=max_trials,
        study_name=study_name,
    )


# ─── 适配器工厂 ───────────────────────────────────────────────────────────────

def _create_adapter(
    adapter_name: str,
    adapter_kwargs: dict[str, Any] | None,
    recipe_data: dict[str, Any],
) -> tuple[Any | None, str]:
    """创建并连接适配器，返回 (adapter, aedt_version)。"""
    kwargs = adapter_kwargs or {}
    setup_cfg = recipe_data.get("setup", {})
    freq_range = setup_cfg.get("freq_range_ghz", [1.5, 3.5])
    freq_points = setup_cfg.get("points", 201)

    if adapter_name == "fake":
        from rfauto.adapters.fake_adapter import FakeAdapter
        kwargs = dict(adapter_kwargs or {})
        freq_ghz = (freq_range[0], freq_range[1], freq_points)
        n_ports = kwargs.pop("n_ports", None)
        model_type = kwargs.pop("model_type", None)
        # 未显式指定时从插件元数据推导（C4：branchline 4 端口 / patch 2 端口）
        if n_ports is None or model_type is None:
            try:
                from rfauto.models.registry import get as _get_plugin
                plugin_cls = _get_plugin(recipe_data.get("model", ""))
                n_ports = n_ports if n_ports is not None else plugin_cls.n_ports
                model_type = model_type if model_type is not None else plugin_cls.fake_model_type
            except KeyError:
                pass
        adapter = FakeAdapter(
            freq_ghz=freq_ghz,
            n_ports=n_ports if n_ports is not None else 3,
            model_type=model_type or "wilkinson",
            **kwargs,
        )
        adapter.connect({})
        return adapter, "fake"

    elif adapter_name == "hfss":
        import os

        from rfauto.adapters.hfss_adapter import HfssAdapter
        from rfauto.infra.version_probe import resolve_aedt_install

        aedt_path = os.environ.get("RFAUTO_AEDT_PATH", "")
        if aedt_path and not Path(aedt_path).exists():
            return None, ""
        # 项目 B：版本探测收敛（显式路径优先，否则自动探测本机安装）
        install = resolve_aedt_install(aedt_path or None)
        if install is None:
            return None, ""
        aedt_version = install["aedt_version"]
        adapter = HfssAdapter()
        adapter.connect({"desktop_version": aedt_version, "non_graphical": True})
        return adapter, aedt_version

    elif adapter_name == "openems":
        # openEMS 真评估优化通道（产物化自真机战役层补丁）：
        # OpenEMSOptAdapter 逐评估整脚本重渲染 + OpenEMSSolver 子进程求解，
        # 与 fake/hfss 分支同构消费优化回路（set_variables/solve/get_sparams/close）。
        from rfauto.adapters.openems_optimizer_adapter import (
            OpenEMSOptAdapter,
            template_for_model,
        )

        kwargs = dict(adapter_kwargs or {})
        try:
            # 模板解析：显式 adapter_kwargs.template > 插件 openems_template
            # ClassVar > 子串映射（与 service._template_hint 同口径）
            template = str(kwargs.pop("template", "") or "")
            if not template:
                try:
                    from rfauto.models.registry import get as _get_plugin
                    plugin_cls = _get_plugin(str(recipe_data.get("model", "")))
                    template = str(getattr(plugin_cls, "openems_template", "") or "")
                except KeyError:
                    template = ""
            if not template:
                template = template_for_model(str(recipe_data.get("model", "")))
            adapter = OpenEMSOptAdapter(
                (float(freq_range[0]), float(freq_range[1])),
                template=template, **kwargs)
            if not adapter.connect({}):
                return None, ""
            return adapter, "openems"
        except Exception as e:
            logger.warning("openems 适配器创建失败: %s", e)
            return None, ""

    return None, ""
