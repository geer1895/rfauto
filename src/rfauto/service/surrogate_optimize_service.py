"""代理寻优服务（WP3.2）：配方进 → JSON 结果出（规则 4）。

组装：extract_param_ranges（配方搜索空间）+ _prepare_env（适配器/插件/
参数系统，与 run_optimization 同源）+ surrogate_loop（确定性内核）。
真跑 evaluate_fn 走 solve_with_self_heal + SpecEvaluator，与 Optuna 直优
化同一求解/指标口径——两种环的差异只在采样策略，保证对照实验同基线。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.optimization.surrogate_loop import DEFAULT_VIRTUAL_TRIALS


def _make_evaluate_fn(
    adapter: Any,
    param_system: Any,
    setup_name: str,
    name_map: dict[str, str],
    objectives: list[Any],
    constraints: list[Any] | None = None,
) -> Callable[[dict[str, float]], dict[str, float]]:
    """params → metrics（真跑口径，与 build_objective 一致）。

    constraints 非空时指标按 objectives+constraints 并集取（镜像
    optimizer.build_objective 的 eval_specs：cost 仍只由 objectives 决定，
    但约束指标键恒有产物，违约量评估不缺键）。
    """
    from rfauto.core.objectives import SpecEvaluator
    from rfauto.pipeline.self_heal import solve_with_self_heal

    eval_specs = list(objectives) + list(constraints or [])

    def evaluate(params: dict[str, float]) -> dict[str, float]:
        param_system.update(params)
        param_system.write_to_adapter(adapter, name_map=name_map)
        report = solve_with_self_heal(adapter, setup_name)
        if not report.success:
            raise RuntimeError(f"求解失败: {report.message}")
        network = adapter.get_sparams()
        return SpecEvaluator.compute_metrics(network, eval_specs)

    return evaluate


def surrogate_optimize(
    recipe_path: str | Path,
    *,
    adapter_name: str = "fake",
    n_init: int = 8,
    top_k: int = 3,
    virtual_trials: int = DEFAULT_VIRTUAL_TRIALS,
    max_real: int = 24,
    min_dist: float = 0.08,
    tol_abs: float = 1e-3,
    tol_rounds: int = 2,
    surrogate_kind: str = "poly_ridge",
    seed: int = 42,
    adapter_kwargs: dict[str, Any] | None = None,
    uncertainty_tol: float | None = None,
    uncertainty_rounds: int = 1,
    uncertainty_pool: int = 128,
) -> dict[str, Any]:
    """代理寻优环服务入口：`rfauto tune --sampler sbo` 的后端。

    B5 不确定度终止判据透传（uncertainty_tol/rounds/pool 同名同义，见
    surrogate_loop.run_surrogate_loop）：仅服务层可编程入口暴露，
    CLI/MCP 不暴露；tol=None（缺省）时行为逐字节不变。
    """
    import yaml

    from rfauto.core.objectives import Objective
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir, record_run, snapshot_recipe, write_meta
    from rfauto.optimization.optimizer import _prepare_env, extract_param_ranges
    from rfauto.optimization.surrogate_loop import run_surrogate_loop

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
    # gain_db 依赖 far_field（build_objective 有远场分支，本服务环的
    # evaluate_fn 未接远场）——显式拒绝而非静默跳过（审查 P1-2：缺失
    # 键会被 evaluate_objectives 计 0 → cost 恒 0 → 环假收敛）
    if any(o.metric == "gain_db" for o in objectives):
        return {"ok": False, "errors": [
            "sbo 路径暂不支持 gain_db 目标（远场指标未接入代理环 evaluate_fn）"]}
    # E10 约束段：optimization.constraints（元素结构同 objectives）
    # 解析后透传给代理环软约束通道——此前显式拒绝（"sbo 路径无软约束通道"），
    # 现 run_surrogate_loop 已补齐（违约量 ≥0/≤0 可行 + 最优可行 best 语义，
    # 镜像 optimizer.py tpe 路径）。元素须为 dict（同 optimizer.py:731 口径），
    # 非法元素早失败、不建 run 目录。
    constraints: list[Any] = []
    for c in (recipe_data.get("optimization") or {}).get("constraints") or []:
        if not isinstance(c, dict):
            return {"ok": False, "errors": [f"constraints 元素须为 dict: {c!r}"]}
        constraints.append(Objective(**c))
    # quota_guard 口径对齐 optimizer.py：显式参数与 recipe.limits 取更严者
    # （P2：sbo 路径此前不读 recipe.limits，配方配额对代理环不生效）
    recipe_limits = recipe_data.get("limits") or {}
    if recipe_limits.get("max_trials"):
        max_real = min(max_real, int(recipe_limits["max_trials"]))

    run_id = generate_run_id()
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    snapshot_recipe(run_dir, recipe_data)

    adapter, aedt_version, plugin_cls, param_system, setup_name, prep_err = (
        _prepare_env(recipe_data, adapter_name=adapter_name,
                     adapter_kwargs=adapter_kwargs))
    if adapter is None:
        return {"ok": False, "errors": [prep_err]}

    bounds = {k: (float(v["low"]), float(v["high"]))
              for k, v in param_ranges.items()}
    evaluate_fn = _make_evaluate_fn(
        adapter, param_system, setup_name,
        getattr(plugin_cls, "hfss_var_map", {}), objectives,
        constraints=constraints or None)

    t0 = time.time()
    try:
        result = run_surrogate_loop(
            bounds, objectives, evaluate_fn,
            n_init=n_init, top_k=top_k, virtual_trials=virtual_trials,
            max_real=max_real, min_dist=min_dist, tol_abs=tol_abs,
            tol_rounds=tol_rounds, surrogate_kind=surrogate_kind, seed=seed,
            constraints=constraints or None,
            uncertainty_tol=uncertainty_tol,
            uncertainty_rounds=uncertainty_rounds,
            uncertainty_pool=uncertainty_pool)
    finally:
        adapter.close()
    elapsed = time.time() - t0

    result.update({
        "run_id": run_id,
        "run_dir": str(run_dir),
        "adapter": adapter_name,
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
    # best 为 None（如 surrogate_fit_failed / 全初始失败 / 全不可行）时如实
    # 标 failed——best_cost=None 的"成功 run"会污染下游统计（审查 P2-14）
    run_status = "done" if best else "failed"
    meta_metrics = {
        "best_cost": best.get("cost"),
        "n_real_used": result.get("n_real_used"),
        "stop_reason": result.get("stop_reason"),
    }
    if constraints:
        # E10 同语义：meta.metrics 带 feasible 标记（镜像 optimizer.py:947-950）
        meta_metrics["feasible"] = bool(result.get("best_feasible"))
    write_meta(run_dir, {
        "run_id": run_id,
        "model": recipe_data.get("model", ""),
        "adapter": adapter_name,
        "aedt_version": aedt_version,
        "status": run_status,
        "algorithm": "surrogate_loop",
        "metrics": meta_metrics,
    })
    record_run(record={
        "run_id": run_id,
        "model": recipe_data.get("model", ""),
        "adapter": adapter_name,
        "status": run_status,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": {"best_cost": best.get("cost"),
                    "n_real_used": result.get("n_real_used")},
    })
    return result
