"""uq_service：代理免费蒙特卡洛 UQ（阶段 6.4 首片；WP4.2 公差/良率收口）。

代理就位后，10k 点蒙特卡洛零仿真成本——产出：
- 良率（yield）：名义点公差盒内 objectives 满足概率；
- 指标分布统计（mean/std/分位数）；
- 参数扰动敏感性排序（单参数 σ 扫描对违约概率的边际影响）。

WP4.2 收口（方案 §4）：
- surrogate_yield_at：显式名义点的良率求值（良率目标函数点值形式，
  供外部优化器/中心化逐点驱动）；
- yield_design_center：良率目标函数（容差盒确定性网格上代理违约
  cost ≤ 0 比例，复用 core/pce.tolerance_yield/design_centering 内核）
  + 坐标 pattern search 设计中心化；蒙特卡洛只在中心化前后做认证
  报告——搜索不吃随机噪声；
- temperature_zone_yield：D9 环境包络（core/bands.env_to_uq_axis 温度轴）
  → σ_c 并入 t_c 维度做代理蒙特卡洛 + 温区两端确定性角点评估
  （温区良率待接收口，D9 已 ✅）。

与 tolerance 模块的差别：tolerance 每点真机求解（贵，n≤数百）；
本模块全部在代理上（免费，n≥10k），代理可信度由校准 gate 背书。
数值全部出自确定性内核。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _metric_key(metric: str) -> str:
    """objectives 指标名 → compute_metrics 产物键（与 tolerance 模块同约定）。"""
    from rfauto.core.objectives import DEFAULT_METRIC_KEY

    return DEFAULT_METRIC_KEY.get(metric, metric)


def _violates(value: float, op: Any, spec: Any) -> bool:
    from rfauto.core.objectives import MetricOp

    if op in (MetricOp.MAX_BELOW, "max_below"):
        return value > float(spec)
    if op in (MetricOp.MIN_ABOVE, "min_above"):
        return value < float(spec)
    if op in (MetricOp.MEAN_WITHIN, "mean_within") and isinstance(
            spec, (list, tuple)) and len(spec) == 2:
        return value < float(spec[0]) or value > float(spec[1])
    return False


def _numeric_pred(model: Any, params: dict[str, float]) -> dict[str, float]:
    """代理预测 → 仅数值指标字典（缺失参数按代理界内缺省处理）。"""
    pred = model.predict(params)
    return {k: float(v) for k, v in pred.items()
            if isinstance(v, (int, float))}


def _load_yield_context(
    samples_path: str | Path,
    tolerances: dict[str, float],
    *,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
) -> tuple[dict[str, Any] | None, list[str] | None]:
    """样本集装载/校验/代理拟合（surrogate_yield 族共用）。

    返回 (ctx, None) 或 (None, errors)。ctx 含 path/bounds/objs/specs/
    model/nominal_sample；名义样本 = 校准样本集中 cost 最小者（确定性）。
    tolerances 允许为空（temperature_zone_yield 的温度 σ 由包络提供）。
    """
    path = Path(samples_path)
    if not path.exists():
        return None, [f"样本集不存在: {path}"]
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = list(data.get("samples") or [])
    objectives = list(data.get("objectives") or [])
    bounds_raw = data.get("bounds") or {}
    if len(samples) < 5:
        return None, ["样本点不足（需 ≥5）以拟合代理"]
    if not objectives:
        return None, ["样本集无 objectives，无从定义良率"]
    bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds_raw.items()}
    bad_tol = [k for k in tolerances if k not in bounds]
    if bad_tol:
        return None, [f"公差参数不在搜索空间: {bad_tol}"]

    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.service.calibration_service import _make_model

    objs = [Objective(**o) for o in objectives]
    model = _make_model(kind, bounds, order=order, ridge_lambda=ridge_lambda)
    model.fit(samples)

    def cost_of(s: dict[str, Any]) -> float:
        return SpecEvaluator.evaluate_objectives(s["metrics"], objs)

    nominal_sample = min(samples, key=cost_of)
    ctx = {
        "path": path,
        "samples": samples,
        "bounds": bounds,
        "objs": objs,
        "specs": [{"metric": _metric_key(o.metric), "op": o.op,
                   "spec": o.value} for o in objs],
        "model": model,
        "nominal_sample": nominal_sample,
    }
    return ctx, None


def _mc_yield(
    ctx: dict[str, Any],
    nominal: dict[str, float],
    tolerances: dict[str, float],
    *,
    n: int,
    seed: int,
) -> dict[str, Any]:
    """名义点代理蒙特卡洛良率 + 指标分布（确定性内核，共用）。

    tolerances：{param: σ}；抽样仅覆盖公差参数，名义点其余坐标保持不动
    （与阶段 6.4 首片语义一致）。
    """
    import numpy as np

    specs = ctx["specs"]
    rng = np.random.default_rng(seed)
    base_metrics = _numeric_pred(ctx["model"], nominal)
    draws = {p: rng.normal(0.0, float(s), n)
             for p, s in tolerances.items()}
    pass_count = 0
    metric_draws: dict[str, list[float]] = {s["metric"]: [] for s in specs}
    for i in range(n):
        pt = dict(nominal)  # 从完整名义点出发（缺参会被代理按界内零点处理）
        for p in draws:
            pt[p] = float(nominal[p] + draws[p][i])
        m = _numeric_pred(ctx["model"], pt)
        ok_all = True
        for s in specs:
            v = m.get(s["metric"])
            if v is None:
                ok_all = False
                break
            metric_draws[s["metric"]].append(v)
            if _violates(v, s["op"], s["spec"]):
                ok_all = False
        if ok_all:
            pass_count += 1
    yield_rate = pass_count / n

    metric_stats = {}
    for mname, vals in metric_draws.items():
        if not vals:
            continue
        arr = np.asarray(vals)
        metric_stats[mname] = {
            "mean": float(arr.mean()), "std": float(arr.std()),
            "q05": float(np.quantile(arr, 0.05)),
            "q95": float(np.quantile(arr, 0.95)),
        }
    return {
        "nominal_metrics": base_metrics,
        "yield_rate": yield_rate,
        "metric_stats": metric_stats,
    }


def surrogate_yield(
    samples_path: str | Path,
    tolerances: dict[str, float],
    *,
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
) -> dict[str, Any]:
    """代理蒙特卡洛良率/分布/敏感性（JSON 契约）。

    tolerances：{param: σ}（与该参数同单位）。名义点 = 校准样本集中
    cost 最小的点（确定性）。
    """
    if not tolerances:
        return {"ok": False, "errors": ["缺少 tolerances（{param: σ}）"]}
    if n < 1:
        return {"ok": False, "errors": [f"n 必须 ≥1，收到: {n}"]}
    ctx, errors = _load_yield_context(
        samples_path, tolerances, kind=kind, order=order,
        ridge_lambda=ridge_lambda)
    if ctx is None:
        return {"ok": False, "errors": errors}

    nominal = {k: float(v) for k, v in ctx["nominal_sample"]["params"].items()}
    mc = _mc_yield(ctx, nominal, tolerances, n=n, seed=seed)
    base_metrics = mc["nominal_metrics"]

    # 敏感性排序：单参数 ±1σ 扰动的指标响应幅值 |Δmetric| 求和（确定性）。
    #    不用违约计数——稳健区违约恒 0 无区分度。
    specs = ctx["specs"]
    model = ctx["model"]
    base_by_metric = {s["metric"]: base_metrics.get(s["metric"])
                      for s in specs}
    sensitivity = {}
    for p, sigma in tolerances.items():
        total = 0.0
        for sign in (1.0, -1.0):
            pt = dict(nominal)
            pt[p] = float(nominal[p]) + sign * float(sigma)
            m = _numeric_pred(model, pt)
            for s in specs:
                v = m.get(s["metric"])
                b = base_by_metric.get(s["metric"])
                if v is not None and b is not None:
                    total += abs(v - b)
        sensitivity[p] = float(total)

    ranked = sorted(sensitivity, key=lambda k: sensitivity[k], reverse=True)
    return {
        "ok": True,
        "samples_path": str(ctx["path"]),
        "surrogate_kind": kind,
        "n_draws": n,
        "seed": seed,
        "nominal_params": nominal,
        "nominal_metrics": base_metrics,
        "tolerances": tolerances,
        "yield_rate": mc["yield_rate"],
        "metric_stats": mc["metric_stats"],
        "sensitivity_ranking": ranked,
        "sensitivity_violation_delta": sensitivity,
    }


def surrogate_yield_at(
    samples_path: str | Path,
    tolerances: dict[str, float],
    nominal: dict[str, float],
    *,
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
) -> dict[str, Any]:
    """显式名义点的代理蒙特卡洛良率（良率目标函数点值形式，JSON 契约）。

    与 surrogate_yield 的差别：名义点由调用方给定（优化器/中心化外部
    驱动逐点求值），不取样本集 cost 最小点。nominal 须覆盖全部公差参数。
    """
    if n < 1:
        return {"ok": False, "errors": [f"n 必须 ≥1，收到: {n}"]}
    if not nominal:
        return {"ok": False, "errors": ["名义点为空"]}
    ctx, errors = _load_yield_context(
        samples_path, tolerances, kind=kind, order=order,
        ridge_lambda=ridge_lambda)
    if ctx is None:
        return {"ok": False, "errors": errors}
    bad = [k for k in nominal if k not in ctx["bounds"]]
    if bad:
        return {"ok": False, "errors": [f"名义点参数不在搜索空间: {bad}"]}
    missing = [p for p in tolerances if p not in nominal]
    if missing:
        return {"ok": False, "errors": [f"名义点缺少公差参数: {missing}"]}

    nom = {k: float(v) for k, v in nominal.items()}
    mc = _mc_yield(ctx, nom, tolerances, n=n, seed=seed)
    return {
        "ok": True,
        "samples_path": str(ctx["path"]),
        "surrogate_kind": kind,
        "n_draws": n,
        "seed": seed,
        "nominal_params": nom,
        "nominal_metrics": mc["nominal_metrics"],
        "tolerances": tolerances,
        "yield_rate": mc["yield_rate"],
        "metric_stats": mc["metric_stats"],
    }


def yield_design_center(
    samples_path: str | Path,
    tolerances: dict[str, float],
    *,
    k_sigma: float = 3.0,
    n_levels: int = 3,
    max_iter: int = 40,
    step_frac: float = 0.25,
    shrink: float = 0.5,
    n_mc: int = 2000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
) -> dict[str, Any]:
    """良率目标函数 + 设计中心化（WP4.2 收口，JSON 契约）。

    良率目标函数：容差盒确定性网格上代理违约 cost（SpecEvaluator 加权
    violation 和）≤ 0 的比例——cost ≤ 0 ⇔ 全规格通过；网格求值与坐标
    pattern search 复用 core/pce.tolerance_yield/design_centering 内核，
    搜索不吃随机噪声。tolerances：{param: σ}；容差盒半宽 = k_sigma·σ
    （项目公差惯例，与 optimization/tolerance.py 3σ 口径一致）。
    蒙特卡洛（surrogate_yield 内核，σ 抽样）只在中心化前后做认证报告
    （initial_yield_mc / final_yield_mc）。
    """
    if k_sigma <= 0:
        return {"ok": False, "errors": [f"k_sigma 必须 >0，收到: {k_sigma}"]}
    if n_levels < 2:
        return {"ok": False, "errors": [f"n_levels 必须 ≥2，收到: {n_levels}"]}
    if n_mc < 1:
        return {"ok": False, "errors": [f"n_mc 必须 ≥1，收到: {n_mc}"]}
    ctx, errors = _load_yield_context(
        samples_path, tolerances, kind=kind, order=order,
        ridge_lambda=ridge_lambda)
    if ctx is None:
        return {"ok": False, "errors": errors}

    from rfauto.core.objectives import SpecEvaluator
    from rfauto.core.pce import design_centering

    model = ctx["model"]
    objs = ctx["objs"]
    bounds = ctx["bounds"]

    # 指标键守卫：目标指标必须落在代理预测面。evaluate_objectives 对缺失
    # 键静默跳过 → 缺指标时良率会被虚高成 1.0，必须前置显式报错。
    box_mid = {name: 0.5 * (lo + hi) for name, (lo, hi) in bounds.items()}
    pred_keys = set(_numeric_pred(model, box_mid))
    missing_metrics = [o.metric for o in objs if not any(
        k in pred_keys
        for k in SpecEvaluator.metric_key_candidates(o.metric, o.op))]
    if missing_metrics:
        return {"ok": False,
                "errors": [f"目标指标不在代理预测面: {missing_metrics}"]}

    def cost_fn(point: dict[str, float]) -> float:
        return SpecEvaluator.evaluate_objectives(model.predict(point), objs)

    half_widths = {p: float(k_sigma) * float(s) for p, s in tolerances.items()}
    param_specs = {name: {"low": lo, "high": hi}
                   for name, (lo, hi) in bounds.items()}
    grid = design_centering(
        param_specs, cost_fn, spec_max=0.0, tolerances=half_widths,
        n_levels=n_levels, max_iter=max_iter, step_frac=step_frac,
        shrink=shrink)

    mc_initial = _mc_yield(ctx, dict(grid["initial_center"]), tolerances,
                           n=n_mc, seed=seed)
    mc_final = _mc_yield(ctx, dict(grid["center"]), tolerances,
                         n=n_mc, seed=seed)
    return {
        "ok": True,
        "samples_path": str(ctx["path"]),
        "surrogate_kind": kind,
        "objective": "tolerance_box_grid_cost_violation(spec_max=0)",
        "k_sigma": float(k_sigma),
        "tolerances": tolerances,
        "box_half_widths": half_widths,
        "n_levels": n_levels,
        "initial_center": grid["initial_center"],
        "initial_yield": grid["initial_yield"],
        "initial_yield_rate": grid["initial_yield"],
        "center": grid["center"],
        "yield": grid["yield"],
        "yield_rate": grid["yield"],
        "worst_cost": grid["worst_cost"],
        "n_evaluations": grid["n_evaluations"],
        "initial_yield_mc": mc_initial["yield_rate"],
        "final_yield_mc": mc_final["yield_rate"],
        "n_mc": n_mc,
        "seed": seed,
    }


def temperature_zone_yield(
    samples_path: str | Path,
    tolerances: dict[str, float],
    env_key: str,
    *,
    t_ref_c: float | None = None,
    k_sigma: float = 3.0,
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
) -> dict[str, Any]:
    """温区良率（WP4.2 ← D9 环境包络待接收口，JSON 契约）。

    D9 环境包络（core/bands.ENVIRONMENTS）→ env_to_uq_axis 温度轴
    （名义 = t_ref_c，σ_c = 包络半宽/k_sigma），σ_c 并入 t_c 维度做代理
    蒙特卡洛；温区两端（t_min_c/t_max_c）做确定性角点评估。要求校准
    样本集含 t_c 维度（D8 温度轴校准集）；温度 σ 以包络为准（调用方若
    传 t_c 公差会被包络覆盖）。tolerances 可为空（只做温度维扰动）。
    """
    from rfauto.core.bands import env_to_delta_t, env_to_uq_axis, get_env

    if k_sigma <= 0:
        return {"ok": False, "errors": [f"k_sigma 必须 >0，收到: {k_sigma}"]}
    if n < 1:
        return {"ok": False, "errors": [f"n 必须 ≥1，收到: {n}"]}
    try:
        env = get_env(env_key)
        axis = env_to_uq_axis(env_key, t_ref_c=t_ref_c, k_sigma=k_sigma)
        delta_t = env_to_delta_t(env_key, t_ref_c=t_ref_c)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "errors": [str(exc)]}

    ctx, errors = _load_yield_context(
        samples_path, tolerances, kind=kind, order=order,
        ridge_lambda=ridge_lambda)
    if ctx is None:
        return {"ok": False, "errors": errors}
    if "t_c" not in ctx["bounds"]:
        return {"ok": False, "errors": [
            "样本集无 t_c 维度（温区良率要求 D8 温度轴校准集含 t_c 参数）"]}

    # 温度 σ 以包络为准（覆盖调用方同名入参），其余参数公差照常
    merged = {**tolerances, "t_c": float(axis["sigma_c"])}
    nominal = {k: float(v) for k, v in ctx["nominal_sample"]["params"].items()}
    nominal["t_c"] = float(axis["nominal_c"])

    mc = _mc_yield(ctx, nominal, merged, n=n, seed=seed)

    # 温区角点（确定性）：包络端点处代理指标与规格判据
    specs = ctx["specs"]
    corners: dict[str, Any] = {}
    for label, t_val in (("t_min_c", env.t_min_c), ("t_max_c", env.t_max_c)):
        pt = dict(nominal)
        pt["t_c"] = float(t_val)
        m = _numeric_pred(ctx["model"], pt)
        ok_all = True
        for s in specs:
            v = m.get(s["metric"])
            if v is None or _violates(v, s["op"], s["spec"]):
                ok_all = False
        corners[label] = {"t_c": float(t_val), "metrics": m,
                          "pass": ok_all}

    return {
        "ok": True,
        "samples_path": str(ctx["path"]),
        "surrogate_kind": kind,
        "n_draws": n,
        "seed": seed,
        "env_key": env.key,
        "env": env.to_dict(),
        "axis": axis,
        "delta_t": delta_t,
        "sigma_c": float(axis["sigma_c"]),
        "half_range_c": float(axis["half_range_c"]),
        "nominal_params": nominal,
        "nominal_metrics": mc["nominal_metrics"],
        "tolerances": merged,
        "yield_rate": mc["yield_rate"],
        "metric_stats": mc["metric_stats"],
        "corners": corners,
        "corner_pass": {"t_min_c": corners["t_min_c"]["pass"],
                        "t_max_c": corners["t_max_c"]["pass"]},
    }
