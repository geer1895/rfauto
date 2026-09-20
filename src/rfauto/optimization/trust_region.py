"""stage-2 精修环：TR-ARS 式信任域 + Bandler 输出空间映射（WP3.2 步骤 b）。

方案口径（cjors.2025184 综述锚）：
- Bandler ASM：粗模型（代理/解析快档，毫秒级）× 细模型（真跑）分层；
  最简输出空间映射 `Rs ≈ Rc + Δ(x)`——细跑残差修正粗模型 bias；
- Koziel TR-ARS：信任域内用"校正后的粗模型"寻优 → 细模型验证 →
  按实际改善/预测改善之比 ρ 接受/拒绝并伸缩信任域半径。

本模块把两者合成 stage-2 精修环（stage-1 = surrogate_loop.run_surrogate_loop
零改动，本模块只消费其输出契约 best.params + 全量已评估样本）：

    u0 = stage-1 best → 信任域内补点（区域内样本不足 min_region_points 时
    LHS 真跑补齐）→ 粗模型 Rc = surrogate_registry 全局代理（全部已评估
    样本）→ 输出映射 Δ(u) = 线性（截距+一次项）拟合"区域内细跑 cost 残差"
    → 校正模型 m_s = Rc + Δ 上 TPE 虚拟寻优（限制在信任域盒内）→ 细跑
    验证候选 → ρ 接受/拒绝 + 半径伸缩 → 收敛（半径塌缩 / 停摆 / 预算）。

铁律落地（同 stage-1）：
- 数值只在确定性内核（数值铁律）：粗模型出自 surrogate_registry，
  映射为闭式 lstsq，cost 出自 SpecEvaluator.evaluate_objectives，LLM 不入环；
- 零真机验证路径：evaluate_fn 注入（单测用合成解析裁判面，§4 口径）；
- 本模块不改 surrogate_loop.py 任何行为——run_two_stage 用 evaluate_fn
  包装器旁路捕获 stage-1 样本，不依赖其内部结构。

诚实边界：Δ(u) 是**标量 cost 层**的加性输出映射（Bandler 原文映射的是
响应向量；单标量目标是其退化形式）；扩散/神经映射类输入空间映射不在
本模块（stage-2 仅做 TR-ARS + 加性输出映射这一档）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np

from rfauto.core.objectives import Objective, SpecEvaluator

__all__ = ["refine_trust_region", "run_two_stage"]

#: 预测改善被模型"忠实"兑现的 ρ 阈值（≥ 时信任域扩张）
DEFAULT_RHO_EXPAND = 0.75
GAMMA_UP = 2.0
GAMMA_DOWN = 0.5


def _to_unit(
    params: dict[str, float],
    bounds: dict[str, tuple[float, float]],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for n, (lo, hi) in bounds.items():
        span = max(hi - lo, 1e-12)
        out[n] = float(np.clip((float(params.get(n, lo)) - lo) / span, 0.0, 1.0))
    return out


def _from_unit(
    unit: dict[str, float],
    bounds: dict[str, tuple[float, float]],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for n, (lo, hi) in bounds.items():
        out[n] = lo + float(unit.get(n, 0.0)) * (hi - lo)
    return out


def _linf(a: dict[str, float], b: dict[str, float]) -> float:
    return max((abs(a[n] - b[n]) for n in a if n in b), default=0.0)


def _region_box(
    u0: dict[str, float],
    delta: float,
    bounds: dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    box: dict[str, tuple[float, float]] = {}
    for n, (lo, hi) in bounds.items():
        c = u0.get(n, 0.0)
        lo_u = float(np.clip(c - delta, 0.0, 1.0))
        hi_u = float(np.clip(c + delta, 0.0, 1.0))
        box[n] = (lo + lo_u * (hi - lo), lo + hi_u * (hi - lo))
    return box


class _AdditiveOutputMapping:
    """标量 cost 层加性输出映射 Δ(u) = b + a·u（闭式 lstsq，拟合失败退 Δ=0）。"""

    def __init__(self, dim: int) -> None:
        self.dim = int(dim)
        self.coef: np.ndarray | None = None

    def fit(
        self,
        unit_points: list[dict[str, float]],
        residuals: list[float],
    ) -> None:
        if len(unit_points) < max(2, self.dim + 1):
            self.coef = None
            return
        names = sorted(unit_points[0])
        x = np.array([[1.0, *[p[n] for n in names]] for p in unit_points])
        y = np.array([float(r) for r in residuals])
        try:
            sol, *_ = np.linalg.lstsq(x, y, rcond=None)
        except np.linalg.LinAlgError:
            self.coef = None
            return
        self.coef = sol if np.all(np.isfinite(sol)) else None

    def delta(self, unit: dict[str, float]) -> float:
        if self.coef is None:
            return 0.0
        names = sorted(unit)
        row = np.array([1.0, *[unit[n] for n in names]])
        return float(row @ self.coef)


def _region_virtual_search(
    model_cost: Callable[[dict[str, float]], float],
    region_bounds: dict[str, tuple[float, float]],
    n_trials: int,
    seed: int,
) -> list[tuple[float, dict[str, float]]]:
    """校正模型上限制在信任域盒内的 TPE 虚拟寻优（零真跑，内存 study）。"""
    import optuna

    names = sorted(region_bounds)

    def virtual_objective(t: optuna.Trial) -> float:
        params = {
            n: t.suggest_float(n, float(region_bounds[n][0]),
                               float(region_bounds[n][1]))
            for n in names
        }
        return model_cost(params)

    prev_verbosity = optuna.logging.get_verbosity()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    try:
        study = optuna.create_study(
            sampler=optuna.samplers.TPESampler(seed=seed),
            direction="minimize")
        study.optimize(virtual_objective, n_trials=max(1, int(n_trials)))
    finally:
        optuna.logging.set_verbosity(prev_verbosity)
    ranked = sorted(
        ((t.value, dict(t.params))
         for t in study.get_trials(deepcopy=False)
         if t.state == optuna.trial.TrialState.COMPLETE),
        key=lambda cv: cv[0])
    return ranked


def _pick_candidate(
    ranked: list[tuple[float, dict[str, float]]],
    evaluated_units: list[dict[str, float]],
    bounds: dict[str, tuple[float, float]],
    min_dist: float,
) -> dict[str, float] | None:
    """按预测 cost 升序取第一个距全部已评估点 L∞ ≥ min_dist 的候选。"""
    for _cost, params in ranked:
        u = _to_unit(params, bounds)
        if all(_linf(u, e) >= min_dist for e in evaluated_units):
            return params
    return None


def predicted_cost(
    model: Any,
    params: dict[str, float],
    mapping: _AdditiveOutputMapping | None,
    objectives: list[Objective],
    bounds: dict[str, tuple[float, float]],
) -> float:
    """校正模型 cost：代理指标→SpecEvaluator cost（+ 加性映射 Δ）。

    单点预测异常按大罚值处理（与 stage-1 P2-9 同款：不炸环）。
    """
    try:
        value = SpecEvaluator.evaluate_objectives(model.predict(params),
                                                  objectives)
        if mapping is not None:
            value += mapping.delta(_to_unit(params, bounds))
        return value
    except Exception:
        return 1e12


def _make_model_cost(
    model: Any,
    mapping: _AdditiveOutputMapping | None,
    objectives: list[Objective],
    bounds: dict[str, tuple[float, float]],
) -> Callable[[dict[str, float]], float]:
    def model_cost(params: dict[str, float]) -> float:
        return predicted_cost(model, params, mapping, objectives, bounds)

    return model_cost


def refine_trust_region(
    bounds: dict[str, tuple[float, float]],
    objectives: list[Objective],
    evaluate_fn: Callable[[dict[str, float]], dict[str, float]],
    *,
    start_params: dict[str, float],
    warm_samples: list[dict[str, Any]] | None = None,
    max_real: int = 12,
    delta_init: float = 0.3,
    delta_min: float = 0.03,
    delta_max: float = 1.0,
    rho_expand: float = DEFAULT_RHO_EXPAND,
    gamma_up: float = GAMMA_UP,
    gamma_down: float = GAMMA_DOWN,
    virtual_trials: int = 400,
    min_region_points: int = 5,
    mapping_kind: str = "output",
    surrogate_kind: str = "poly_ridge",
    surrogate_config: dict[str, Any] | None = None,
    min_dist: float = 0.02,
    tol_abs: float = 1e-4,
    tol_rounds: int = 2,
    seed: int = 42,
) -> dict[str, Any]:
    """信任域精修主环（stage-2）：从 stage-1 best 出发的局部二阶段。

    evaluate_fn: params → metrics dict（细模型真跑通道；单测注入合成解析
    裁判实现零真机验证）。抛异常 = 该点失败，记 failure 不入样本，按拒绝
    处理（缩信任域）。

    warm_samples: stage-1 已评估样本 [{"params", "metrics"}]（cost 由本环
    按同口径重算，不信任外来 cost 字段）。warm 点不消耗 stage-2 预算——
    stage-1 的真跑成本已在 stage-1 记账。

    起点处理：start_params 与 warm 中某点完全相同时直接复用其 cost
    （省 1 次真跑）；否则先真跑一次锚定中心。

    mapping_kind:
    - "output"（默认）：全局粗代理 Rc（全部样本拟合）+ 区域内线性残差
      映射 Δ（Bandler 加性输出映射的标量 cost 形式）；
    - "local"：信任域内直接重拟合局部代理（无粗模型，对照档）。
    """
    t0 = time.time()
    if not bounds:
        return {"ok": False, "errors": ["搜索空间为空（bounds 缺失）"]}
    if not objectives:
        return {"ok": False, "errors": ["objectives 为空，无从评估 cost"]}
    if not isinstance(start_params, dict) or not start_params:
        return {"ok": False,
                "errors": ["缺少 start_params（stage-1 best 或设计起点）"]}
    if mapping_kind not in ("output", "local"):
        return {"ok": False, "errors": [
            f"未知 mapping_kind {mapping_kind!r}（可用 output/local）"]}
    max_real = max(1, int(max_real))
    delta_init = float(np.clip(delta_init, delta_min, delta_max))

    def cost_of(metrics: dict[str, float]) -> float:
        return SpecEvaluator.evaluate_objectives(metrics, objectives)

    samples: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    attempts = 0
    trace: list[float] = []

    def evaluate_real(params: dict[str, float], phase: str) -> dict[str, Any] | None:
        nonlocal attempts
        try:
            metrics = evaluate_fn(dict(params))
        except Exception as exc:
            failures.append({"params": dict(params), "phase": phase,
                             "error": str(exc)})
            attempts += 1
            return None
        rec = {"params": dict(params), "metrics": dict(metrics),
               "cost": cost_of(metrics)}
        samples.append(rec)
        attempts += 1
        trace.append(rec["cost"])
        return rec

    n_warm = 0
    for rec in (warm_samples or []):
        p, m = rec.get("params"), rec.get("metrics")
        if not isinstance(p, dict) or not isinstance(m, dict):
            continue
        samples.append({"params": dict(p), "metrics": dict(m),
                        "cost": cost_of(m)})
        n_warm += 1

    u0 = _to_unit(start_params, bounds)
    center_params = dict(start_params)
    exact = next(
        (s for s in samples if dict(s["params"]) == dict(start_params)), None)
    center_rec = (exact if exact is not None
                  else evaluate_real(start_params, "tr_start"))
    if center_rec is None:
        return {
            "ok": True,
            "algorithm": "trust_region_stage2",
            "best": None,
            "start_cost": None,
            "n_real_used": len(trace),
            "n_attempts": attempts,
            "n_warm_imported": n_warm,
            "n_failures": len(failures),
            "iterations": [],
            "stop_reason": "start_eval_failed",
            "delta_final": delta_init,
            "failures": failures,
            "real_cost_trace": trace,
            "elapsed_s": round(time.time() - t0, 2),
        }
    center_cost = float(center_rec["cost"])
    start_cost = center_cost
    best = dict(center_rec)
    delta = delta_init

    from rfauto.optimization.sample_design import lhs_points
    from rfauto.optimization.surrogate import surrogate_registry

    model_config: dict[str, Any] = {}
    if surrogate_kind == "poly_ridge":
        # 与 stage-1 同默认：环内样本少、特征本就良态，0.1 收缩会把局部
        # 面压平（surrogate_loop 同款实测结论）
        model_config["ridge_lambda"] = 0.01
    model_config.update(surrogate_config or {})

    def fit_surrogate(fit_samples: list[dict[str, Any]],
                      fit_bounds: dict[str, tuple[float, float]]) -> Any:
        model = surrogate_registry.create(surrogate_kind, config={
            "bounds": {k: tuple(v) for k, v in fit_bounds.items()},
            **model_config})
        model.fit(fit_samples)
        return model

    def evaluated_units() -> list[dict[str, float]]:
        units = [_to_unit(s["params"], bounds) for s in samples]
        units.extend(_to_unit(f["params"], bounds) for f in failures)
        return units

    stop_reason = ""
    history: list[dict[str, Any]] = []
    stagnation = 0
    rnd = 0
    while attempts < max_real:
        rnd += 1
        region = [s for s in samples
                  if _linf(_to_unit(s["params"], bounds), u0)
                  <= delta + 1e-12]
        n_fill = 0
        fill_seed = seed + 131 * rnd
        while len(region) < min_region_points and attempts < max_real:
            region_bounds = _region_box(u0, delta, bounds)
            pool = lhs_points(region_bounds,
                              min_region_points - len(region) + 2,
                              seed=fill_seed)["points"]
            fill_seed += 1
            added = False
            for pt in pool:
                if len(region) >= min_region_points or attempts >= max_real:
                    break
                u_pt = _to_unit(pt, bounds)
                if _linf(u_pt, u0) < min_dist:
                    continue
                if all(_linf(u_pt, _to_unit(s["params"], bounds)) >= min_dist
                       for s in samples):
                    rec = evaluate_real(pt, f"tr{rnd}_fill")
                    if rec is not None:
                        region.append(rec)
                        n_fill += 1
                        added = True
            if not added:
                break
        if len(region) < max(3, min(4, min_region_points)):
            stop_reason = "insufficient_region_samples"
            break

        if mapping_kind == "output":
            coarse = fit_surrogate(samples, bounds)
            if not coarse.fitted:
                stop_reason = "surrogate_fit_failed"
                break
            mapping = _AdditiveOutputMapping(len(bounds))
            pts: list[dict[str, float]] = []
            res: list[float] = []
            for s in region:
                try:
                    base = SpecEvaluator.evaluate_objectives(
                        coarse.predict(s["params"]), objectives)
                except Exception:
                    continue
                pts.append(_to_unit(s["params"], bounds))
                res.append(float(s["cost"]) - base)
            mapping.fit(pts, res)
            model_cost = _make_model_cost(coarse, mapping, objectives, bounds)
        else:
            region_bounds = _region_box(u0, delta, bounds)
            local_model = fit_surrogate(region, region_bounds)
            if not local_model.fitted:
                stop_reason = "surrogate_fit_failed"
                break
            model_cost = _make_model_cost(local_model, None, objectives, bounds)

        ranked = _region_virtual_search(
            model_cost, _region_box(u0, delta, bounds),
            virtual_trials, seed + 17 * rnd)
        cand = _pick_candidate(ranked, evaluated_units(), bounds, min_dist)
        relaxed = False
        if cand is None:
            cand = _pick_candidate(ranked, evaluated_units(), bounds,
                                   min_dist / 2)
            relaxed = True
        if cand is None:
            stop_reason = "no_new_points"
            break
        if attempts >= max_real:
            # 候选真跑同样受预算约束（补点可能已耗尽余量）
            stop_reason = "budget"
            break

        rec = evaluate_real(cand, f"tr{rnd}")
        center_cost_before = center_cost
        pred = model_cost(center_params) - model_cost(cand)
        improved = center_cost - (float(rec["cost"]) if rec is not None
                                  else center_cost)
        accepted = rec is not None and float(rec["cost"]) < center_cost
        rho: float | None = None
        if accepted:
            center_cost = float(rec["cost"])
            center_params = dict(cand)
            u0 = _to_unit(cand, bounds)
            if rec["cost"] < best["cost"]:
                best = dict(rec)
            if pred > 1e-12:
                rho = improved / pred
                if rho >= rho_expand:
                    delta = min(delta_max, delta * gamma_up)
        else:
            delta = delta * gamma_down
        history.append({
            "iter": rnd,
            "delta": round(delta, 6),
            "n_region": len(region),
            "n_fill": n_fill,
            "candidate": dict(cand),
            "fine_cost": None if rec is None else float(rec["cost"]),
            "center_cost_before": center_cost_before,
            "center_cost": center_cost,
            "predicted_improvement": round(pred, 9),
            "rho": None if rho is None else round(rho, 6),
            "accepted": accepted,
            "min_dist_relaxed": relaxed,
        })
        if improved >= tol_abs:
            stagnation = 0
        else:
            stagnation += 1
            if stagnation >= tol_rounds:
                stop_reason = "stagnation"
                break
        if delta < delta_min:
            stop_reason = "trust_region_min"
            break

    if not stop_reason:
        stop_reason = "budget"

    return {
        "ok": True,
        "algorithm": "trust_region_stage2",
        "mapping_kind": mapping_kind,
        "surrogate_kind": surrogate_kind,
        "start_cost": start_cost,
        "start_params": dict(start_params),
        "best": best,
        "n_real_used": len(trace),
        "n_attempts": attempts,
        "n_warm_imported": n_warm,
        "n_failures": len(failures),
        "iterations": history,
        "stop_reason": stop_reason,
        "delta_final": round(delta, 6),
        "virtual_trials": virtual_trials,
        "failures": failures,
        "real_cost_trace": trace,
        "elapsed_s": round(time.time() - t0, 2),
    }


def run_two_stage(
    bounds: dict[str, tuple[float, float]],
    objectives: list[Objective],
    evaluate_fn: Callable[[dict[str, float]], dict[str, float]],
    *,
    stage1: dict[str, Any] | None = None,
    stage2: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """stage-1 代理环（surrogate_loop 原样）→ stage-2 信任域精修 串联。

    stage1/stage2 为各自函数的 kwargs dict。evaluate_fn 用包装器旁路捕获
    stage-1 全部成功样本喂给 stage-2 作 warm 起点——surrogate_loop.py
    零改动。返回合并契约：stage1/stage2 子报告 + 总 best + 总真跑数。
    """
    from rfauto.optimization.surrogate_loop import run_surrogate_loop

    captured: list[dict[str, Any]] = []

    def wrapped(params: dict[str, float]) -> dict[str, float]:
        metrics = evaluate_fn(dict(params))
        captured.append({"params": dict(params), "metrics": dict(metrics)})
        return metrics

    s1 = run_surrogate_loop(bounds, objectives, wrapped, **(stage1 or {}))
    warm = [
        {"params": rec["params"], "metrics": rec["metrics"],
         "cost": SpecEvaluator.evaluate_objectives(rec["metrics"], objectives)}
        for rec in captured
    ]
    merged: dict[str, Any] = {
        "ok": bool(s1.get("ok")),
        "algorithm": "two_stage_sbo_trust_region",
        "stage1": s1,
        "stage2": None,
        "best": s1.get("best"),
        "n_real_used_total": int(s1.get("n_real_used", 0)),
        "n_attempts_total": int(s1.get("n_attempts", 0)),
    }
    if not merged["ok"] or s1.get("best") is None:
        return merged
    s2 = refine_trust_region(
        bounds, objectives, wrapped,
        start_params=dict(s1["best"]["params"]),
        warm_samples=warm,
        **(stage2 or {}))
    merged["stage2"] = s2
    merged["n_real_used_total"] += int(s2.get("n_real_used", 0))
    merged["n_attempts_total"] += int(s2.get("n_attempts", 0))
    if s2.get("best") is not None and (
            merged["best"] is None
            or s2["best"]["cost"] < merged["best"]["cost"]):
        merged["best"] = s2["best"]
    return merged
