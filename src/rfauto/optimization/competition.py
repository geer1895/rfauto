"""OP-5（round16 §六）：多目标优化器族同预算 HV 竞赛架（合成裁判，#207）。

规格原文："multiobj 加 algorithm 选择 + wp39 扩优化器族同预算 HV 竞赛"。
algorithm 选择在 multiobj_backend（"nsga2" | "rnsga3"）落地；本模块补
**竞赛面**：同一合成问题、同一评估预算（n_eval 次目标求值）、同一 seed
组下跑多引擎，判据=累计评估的约束 Pareto 前沿超体积（pareto_tools.
exact_hypervolume，最小化口径统一 ref）。

设计（基类+注册表， 硬限制 3）：
- :class:`CompetitionProblem` 纯数据问题书（目标函数/边界/ref 点/可选
  偏好参考点）；:data:`ENGINE_REGISTRY` 注册引擎 runner（名字 →
  ``run(problem, n_eval, seed) -> dict``）；:func:`run_competition`
  同预算扫描 + HV 记分。
- 内置引擎（全部确定性：seed 透传）：
  - ``nsga2_pymoo``：pymoo NSGA-II（pop=20，n_gen=n_eval//pop）；
  - ``rnsga3_pymoo``：pymoo R-NSGA-III（偏好参考点取
    problem.preference_ref_points，缺 None 显式报错——OP-4 通道）；
  - ``nsga2_optuna`` / ``nsga3_optuna``：optuna 内建 NSGAII/III 采样器
    ask/tell 逐点消费预算（optuna 5.0 内建，零新依赖）。
- MOTPE 通道：不内置。round16 规格 MOTPE 依赖第三方 motpe 包，本仓
  venv 未装且其 API 未经源码实录（#215 禁臆写 API）——扩展位即本
  注册表：装包后按其 README 实录 runner 一枚并以
  ``register_engine("motpe", runner)`` 注册即入竞赛，无需改本模块。

铁律 7 对照：本模块只编排与记分，物理/数值全部来自注入的目标函数与
pareto_tools 集合运算；判据用合成函数（#207：fake 病态不可用原话），
真机验收（wp39 扩族真跑）超本模块与 unit 门。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from rfauto.optimization.pareto_tools import (
    constrained_pareto_front,
    exact_hypervolume,
)


@dataclass(frozen=True)
class CompetitionProblem:
    """竞赛问题书（纯数据；目标函数由调用方注入）。"""

    #: 问题名（报告面展示）
    name: str
    #: 变量维数
    n_variables: int
    #: 每维边界 (lo, hi)，形状 (n_variables, 2)
    bounds: tuple[tuple[float, float], ...]
    #: 目标函数：x (n_variables,) → (n_objectives,) 元组（最小化口径）
    objective_fn: Callable[[np.ndarray], tuple[float, ...]]
    #: 目标维数
    n_objectives: int
    #: HV 参考点（最小化口径，pareto_tools.exact_hypervolume 同义）
    ref_point: tuple[float, ...]
    #: 可选偏好参考点（rnsga3 引擎消费；(n_refs, n_objectives)）
    preference_ref_points: tuple[tuple[float, ...], ...] | None = None
    #: 可选约束函数：x → (n_constraints,) 违约向量（≥0，0=可行边界）
    constraint_fn: Callable[[np.ndarray], tuple[float, ...]] | None = None
    #: 引擎扩展数据（dict，缺省空——frozen dataclass 用 field(default_factory)）
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.n_variables < 1 or self.n_objectives < 1:
            raise ValueError("n_variables/n_objectives 必须 ≥1")
        if len(self.bounds) != self.n_variables:
            raise ValueError(
                f"bounds 行数 {len(self.bounds)} 与 n_variables "
                f"{self.n_variables} 不一致")
        for lo, hi in self.bounds:
            if not (math.isfinite(float(lo)) and math.isfinite(float(hi))
                    and float(hi) > float(lo)):
                raise ValueError(f"边界须 finite 且 lo<hi：({lo}, {hi})")
        if len(self.ref_point) != self.n_objectives:
            raise ValueError(
                f"ref_point 维数 {len(self.ref_point)} 与 n_objectives "
                f"{self.n_objectives} 不一致")


@dataclass(frozen=True)
class EngineResult:
    """单引擎单 seed 运行结果（F 已收 archive；HV 由竞赛架统一记分）。"""

    engine: str
    seed: int
    X: tuple[tuple[float, ...], ...]
    F: tuple[tuple[float, ...], ...]
    n_evaluations: int


EngineFn = Callable[["CompetitionProblem", int, int], EngineResult]

ENGINE_REGISTRY: dict[str, EngineFn] = {}


def register_engine(name: str) -> Callable[[EngineFn], EngineFn]:
    """引擎注册装饰器（名字重复/空显式报错，不静默覆盖）。"""
    key = str(name).strip()
    if not key:
        raise ValueError("引擎名不得为空")

    def _wrap(fn: EngineFn) -> EngineFn:
        if key in ENGINE_REGISTRY and ENGINE_REGISTRY[key] is not fn:
            raise ValueError(f"引擎名重复注册: {key!r}")
        ENGINE_REGISTRY[key] = fn
        return fn

    return _wrap


def list_engines() -> list[str]:
    """已注册引擎名（注册序，确定性）。"""
    return list(ENGINE_REGISTRY)


def _pymoo_run(
    problem: CompetitionProblem, n_eval: int, seed: int, algorithm: str,
) -> EngineResult:
    """pymoo 引擎公共路径（nsga2 / rnsga3）。"""
    from pymoo.core.problem import Problem
    from pymoo.optimize import minimize

    pop = 20
    n_gen = max(1, int(n_eval) // pop)

    class _Problem(Problem):
        def __init__(self) -> None:
            xl = np.array([b[0] for b in problem.bounds])
            xu = np.array([b[1] for b in problem.bounds])
            extra: dict[str, Any] = {}
            if problem.constraint_fn is not None:
                extra["n_ieq_constr"] = 1  # 竞赛架约定单违约标量通道
            super().__init__(
                n_var=problem.n_variables, n_obj=problem.n_objectives,
                xl=xl, xu=xu, **extra)

        def _evaluate(self, X, out, *args, **kwargs):
            out["F"] = np.array([problem.objective_fn(x) for x in X])
            if problem.constraint_fn is not None:
                out["G"] = np.array([
                    [float(sum(max(0.0, float(g)) for g in problem.constraint_fn(x)))]
                    for x in X])

    if algorithm == "nsga2":
        from pymoo.algorithms.moo.nsga2 import NSGA2

        inst = NSGA2(pop_size=pop)
    else:
        if not problem.preference_ref_points:
            raise ValueError(
                'engine="rnsga3_pymoo" 需要 problem.preference_ref_points'
                "（R-NSGA-III 偏好参考点）")
        from pymoo.algorithms.moo.rnsga3 import RNSGA3

        inst = RNSGA3(
            ref_points=np.asarray(problem.preference_ref_points, dtype=float),
            pop_per_ref_point=max(2, pop // len(problem.preference_ref_points)),
        )
    res = minimize(_Problem(), inst, ("n_gen", n_gen), seed=int(seed),
                   verbose=False)
    F = np.atleast_2d(np.asarray(res.F, dtype=float))
    X = np.atleast_2d(np.asarray(res.X, dtype=float))
    return EngineResult(
        engine=f"{algorithm}_pymoo", seed=int(seed),
        X=tuple(tuple(float(v) for v in row) for row in X),
        F=tuple(tuple(float(v) for v in row) for row in F),
        n_evaluations=n_gen * pop,
    )


@register_engine("nsga2_pymoo")
def _nsga2_pymoo(problem: CompetitionProblem, n_eval: int, seed: int) -> EngineResult:
    return _pymoo_run(problem, n_eval, seed, "nsga2")


@register_engine("rnsga3_pymoo")
def _rnsga3_pymoo(problem: CompetitionProblem, n_eval: int, seed: int) -> EngineResult:
    return _pymoo_run(problem, n_eval, seed, "rnsga3")


def _optuna_run(
    problem: CompetitionProblem, n_eval: int, seed: int, sampler_name: str,
) -> EngineResult:
    """optuna 内建 NSGA-II/III 引擎（ask/tell 逐点消费预算，精确 n_eval）。"""
    import optuna

    if sampler_name == "nsga2":
        sampler = optuna.samplers.NSGAIISampler(seed=int(seed))
    else:
        sampler = optuna.samplers.NSGAIIISampler(seed=int(seed))
    study = optuna.create_study(
        directions=["minimize"] * problem.n_objectives, sampler=sampler)
    X_rows: list[tuple[float, ...]] = []
    F_rows: list[tuple[float, ...]] = []
    for _ in range(max(int(n_eval), 0)):
        trial = study.ask()
        x = np.array([
            trial.suggest_float(f"x{i}", float(problem.bounds[i][0]),
                                float(problem.bounds[i][1]))
            for i in range(problem.n_variables)
        ])
        f = problem.objective_fn(x)
        study.tell(trial, [float(v) for v in f])
        X_rows.append(tuple(float(v) for v in x))
        F_rows.append(tuple(float(v) for v in f))
    return EngineResult(
        engine=f"{sampler_name}_optuna", seed=int(seed),
        X=tuple(X_rows), F=tuple(F_rows), n_evaluations=len(F_rows))


@register_engine("nsga2_optuna")
def _nsga2_optuna(problem: CompetitionProblem, n_eval: int, seed: int) -> EngineResult:
    return _optuna_run(problem, n_eval, seed, "nsga2")


@register_engine("nsga3_optuna")
def _nsga3_optuna(problem: CompetitionProblem, n_eval: int, seed: int) -> EngineResult:
    return _optuna_run(problem, n_eval, seed, "nsga3")


def run_engine(
    problem: CompetitionProblem, engine: str, n_eval: int, seed: int,
) -> EngineResult:
    """按名运行已注册引擎（未知名报错并列可用项）。"""
    fn = ENGINE_REGISTRY.get(str(engine).strip())
    if fn is None:
        raise ValueError(f"未知引擎 {engine!r}；可用: {list_engines()}")
    return fn(problem, int(n_eval), int(seed))


def _archive_hv(result: EngineResult, problem: CompetitionProblem) -> float:
    """累计评估的（约束）Pareto 前沿 HV（竞赛统一判据）。"""
    F = np.asarray(result.F, dtype=float)
    if F.size == 0:
        return 0.0
    violations: list[tuple[float, ...]] | None = None
    if problem.constraint_fn is not None:
        violations = [tuple(problem.constraint_fn(np.asarray(x)))
                      for x in result.X]
    front_idx = constrained_pareto_front(F.tolist(), violations)
    pts = [tuple(float(v) for v in F[i]) for i in front_idx]
    return exact_hypervolume(pts, tuple(float(v) for v in problem.ref_point))


def run_competition(
    problem: CompetitionProblem,
    engines: Sequence[str],
    n_eval: int,
    seeds: Sequence[int],
) -> dict[str, Any]:
    """同预算 HV 竞赛（逐引擎×seed 运行 + 记分 + 排名）。

    Returns:
        {"problem", "n_eval", "seeds", "runs": [{engine, seed, hv,
        n_evaluations}...], "ranking": [{engine, hv_mean, hv_by_seed}...]
        （按 hv_mean 降序，平局按引擎名升序——确定性）}

    Raises:
        ValueError: n_eval ≤0 / engines 或 seeds 为空 / 引擎未注册。
    """
    if int(n_eval) <= 0:
        raise ValueError(f"n_eval 必须 >0，实得 {n_eval}")
    if not engines or not seeds:
        raise ValueError("engines 与 seeds 均不得为空")
    runs: list[dict[str, Any]] = []
    for engine in engines:
        for seed in seeds:
            result = run_engine(problem, engine, n_eval, seed)
            runs.append({
                "engine": result.engine,
                "seed": int(seed),
                "hv": _archive_hv(result, problem),
                "n_evaluations": result.n_evaluations,
            })
    by_engine: dict[str, list[float]] = {}
    for r in runs:
        by_engine.setdefault(r["engine"], []).append(r["hv"])
    ranking = [
        {"engine": e,
         "hv_mean": float(np.mean(vs)),
         "hv_by_seed": [float(v) for v in vs]}
        for e, vs in by_engine.items()
    ]
    ranking.sort(key=lambda e: (-e["hv_mean"], e["engine"]))
    return {
        "problem": problem.name,
        "n_eval": int(n_eval),
        "seeds": [int(s) for s in seeds],
        "runs": runs,
        "ranking": ranking,
    }
