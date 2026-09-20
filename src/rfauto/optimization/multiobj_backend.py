"""多目标优化后端（NSGA-II / Pareto 前沿）—— P5 完整实现 + E9 收口。

使用 pymoo NSGA-II 进行多目标优化：
- 双目标：带宽最大化 + 回损最小化
- Pareto 前沿提取与排序
- 与 Optuna TPE 单目标优化器并行（P2）
- E9：可选不等式约束通道（constraint_fn → pymoo G≤0 同义语义：本引擎
 违约量 ≥0 且 0=可行边界，直接作 G 即 CV=Σmax(G,0)=Σ违约量）+
 逐代精英存档超体积收敛序列 hv_convergence（best-effort，#105）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class MultiObjBackend:
  """多目标优化后端（pymoo NSGA-II）。

  用途：带宽 + 回损 双目标 Pareto 优化。
  P5 完整实现。
  """

  def __init__(
    self,
    n_objectives: int = 2,
    n_variables: int = 3,
    bounds: tuple[np.ndarray, np.ndarray] | None = None,
  ) -> None:
    """
    Args:
      n_objectives: 目标数量（默认 2：带宽 + 回损）
      n_variables: 变量数量
      bounds: 变量边界 (lower, upper)，shape (n_variables,)
    """
    self.n_objectives = n_objectives
    self.n_variables = n_variables
    self.bounds = bounds

  def optimize(
    self,
    objective_fn: Callable[[np.ndarray], np.ndarray],
    n_gen: int = 100,
    pop_size: int = 50,
    seed: int | None = None,
    constraint_fn: Callable[[np.ndarray], np.ndarray] | None = None,
    n_constraints: int = 0,
  ) -> dict[str, Any]:
    """运行 NSGA-II 优化，返回 Pareto 前沿。

    Args:
      objective_fn: 目标函数，输入 (n_variables,) 返回 (n_objectives,)
      n_gen: 迭代代数
      pop_size: 种群大小
      seed: 随机种子
      constraint_fn: E9 可选约束函数，输入 (n_variables,) 返回
        (n_constraints,) 违约向量（各分量 ≥0，0=可行边界；直接作
        pymoo G，G≤0 即可行——两套语义同义，无需符号翻转）。
        None（缺省）时不建约束，路径与旧实现一致。
      n_constraints: constraint_fn 返回向量长度（>0 时才生效）。

    Returns:
      dict with keys: pareto_front, pareto_variables, n_evaluations；
      有约束时补 pareto_constraints（前沿逐点违约向量）；
      hv_convergence（逐代精英存档超体积，pymoo history 可取时）。
    """
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.problem import Problem
    from pymoo.optimize import minimize

    use_constraints = constraint_fn is not None and int(n_constraints) > 0

    # 定义 pymoo Problem
    class RFAutoProblem(Problem):
      def __init__(self, obj_fn, n_var, n_obj, bounds, con_fn, n_con):
        xl = bounds[0] if bounds is not None else np.zeros(n_var)
        xu = bounds[1] if bounds is not None else np.ones(n_var)
        extra: dict[str, Any] = {}
        if con_fn is not None and n_con > 0:
          extra["n_ieq_constr"] = int(n_con)
        super().__init__(n_var=n_var, n_obj=n_obj, xl=xl, xu=xu, **extra)
        self.obj_fn = obj_fn
        self.con_fn = con_fn

      def _evaluate(self, X, out, *args, **kwargs):
        # X shape: (pop_size, n_var)
        F = np.array([self.obj_fn(x) for x in X])
        out["F"] = F
        if self.con_fn is not None:
          out["G"] = np.array([self.con_fn(x) for x in X])

    problem = RFAutoProblem(
      objective_fn, self.n_variables, self.n_objectives, self.bounds,
      constraint_fn if use_constraints else None,
      int(n_constraints) if use_constraints else 0,
    )

    # NSGA-II 算法
    algorithm = NSGA2(pop_size=pop_size)

    # 运行优化（save_history：逐代精英存档供 E9 超体积收敛序列；不改 RNG）
    res = minimize(
      problem,
      algorithm,
      ("n_gen", n_gen),
      seed=seed,
      verbose=False,
      save_history=True,
    )

    # 提取 Pareto 前沿
    pareto_front = res.F # shape (n_pareto, n_objectives)
    pareto_variables = res.X # shape (n_pareto, n_variables)
    pareto_constraints = None
    if use_constraints:
      pareto_constraints = getattr(res, "G", None)

    # 按第一个目标排序（带宽）
    sort_idx = np.argsort(pareto_front[:, 0])
    pareto_front = pareto_front[sort_idx]
    pareto_variables = pareto_variables[sort_idx]
    if pareto_constraints is not None:
      pareto_constraints = np.asarray(pareto_constraints)[sort_idx]

    logger.info(
      "NSGA-II 完成: %d 代, %d 次评估, Pareto 前沿 %d 个解",
      n_gen, res.algorithm.evaluator.n_eval, len(pareto_front),
    )

    result: dict[str, Any] = {
      "ok": True,
      "pareto_front": pareto_front.tolist(),
      "pareto_variables": pareto_variables.tolist(),
      "n_pareto": len(pareto_front),
      "n_evaluations": res.algorithm.evaluator.n_eval,
      "n_generations": n_gen,
    }
    if pareto_constraints is not None:
      result["pareto_constraints"] = np.asarray(pareto_constraints).tolist()
    hv_trace = _hv_convergence_from_history(res, pareto_front)
    if hv_trace is not None:
      result["hv_convergence"] = hv_trace
    return result

  @staticmethod
  def extract_pareto_metrics(
    pareto_front: list[list[float]],
    metric_names: list[str],
  ) -> list[dict[str, float]]:
    """将 Pareto 前沿转换为指标字典列表。

    Args:
      pareto_front: [[obj1, obj2, ...], ...]
      metric_names: ["bw_ghz", "s11_db", ...]

    Returns:
      [{metric_name: value, ...}, ...]
    """
    results = []
    for point in pareto_front:
      metrics = {}
      for i, name in enumerate(metric_names):
        if i < len(point):
          metrics[name] = point[i]
      results.append(metrics)
    return results


def _hv_convergence_from_history(res: Any, final_front: np.ndarray) -> list[float] | None:
  """E9 逐代精英存档超体积（best-effort，#105：取不到如实缺省 None）。

  口径：第 g 代前沿 = 前 g 代**全部已评估可行点**的累计非支配集（精英
  存档），统一 ref = 最终前沿各维最差值 + max(1, 0.1·|最差值|)
  （pareto_tools.default_reference_point 惯例）。累计存档保证序列弱单调
  不减（「hypervolume 单调」），而 pymoo 逐代 opt 因拥挤度截断在
  理论上不保证单调。有约束问题只累计 CV≤0 的点（不可行点不进 HV）。
  """
  try:
    from rfauto.optimization.pareto_tools import (
      default_reference_point,
      hv_convergence,
      nondominated_indices,
    )

    history = getattr(res, "history", None)
    if not history:
      return None
    front = np.asarray(final_front, dtype=float)
    if front.ndim != 2 or front.shape[0] == 0:
      return None
    ref = default_reference_point(front.tolist())
    archive: list[list[float]] = []
    fronts: list[list[list[float]]] = []
    for entry in history:
      pop = getattr(entry, "pop", None)
      if pop is None:
        return None
      f_gen = np.asarray(pop.get("F"), dtype=float)
      if f_gen.ndim != 2:
        return None
      cv = pop.get("CV")
      if cv is not None:
        cv_arr = np.asarray(cv, dtype=float).reshape(len(f_gen), -1)
        feasible = cv_arr.max(axis=1) <= 0.0
        f_gen = f_gen[feasible]
      archive.extend(f_gen.tolist())
      if archive:
        nd = nondominated_indices(archive)
        archive = [archive[i] for i in nd]
      fronts.append([list(p) for p in archive])
    return [float(v) for v in hv_convergence(fronts, ref)]
  except Exception as exc: # 观测性 best-effort（#105）
    logger.debug("hv_convergence 不可用: %s", exc)
    return None
