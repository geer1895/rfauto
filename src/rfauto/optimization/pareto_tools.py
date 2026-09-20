"""E9 Pareto/超体积确定性内核（纯 numpy，无 pymoo 依赖）。

三件套（方案 #23「hypervolume 单调」+ E9 约束 Pareto 口径）：

- exact_hypervolume：最小化口径精确超体积——实现自 mf_backend._hv_exact_min
 迁入公开化（mf_backend 改 import，hypervolume_contribution 语义逐字节不变）；
- constrained_pareto_front：Deb 可行优先支配（Deb 2000 constraint-domination）
 ——可行支配不可行、可行间标准 Pareto 支配、不可行间总违约量小者优
 （总违约相等时退回标准支配）；违约量口径与 optimizer._single_objective_cost /
 surrogate_loop.constraint_violations 同源（≥0，0=可行边界）；
- hv_convergence：逐代前沿的超体积序列（统一 ref，供弱单调断言）。

铁律：本模块只做集合运算，不产生任何物理数值（数值铁律）；无 pymoo
——多目标后端（multiobj_backend）与 UI 服务层（ui_service.pareto_view）
共享同一内核，避免两套支配定义分叉。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

Point = tuple[float, ...]


def exact_hypervolume(pts: Sequence[Sequence[float]], ref: Sequence[float]) -> float:
  """最小化口径的精确超体积：按末维切片 + 低维递归（无新依赖）。

  面向 Phase-2 选点/前沿收敛诊断规模（目标维 k≤3、点数 n≤10²）：d=1
  闭式；d≥2 时按末维唯一坐标切条，条体积 = 条厚 × 活跃点在低维投影的
  超体积。任一维 ≥ ref 的点体积贡献为 0，先剔除。

  与原 mf_backend._hv_exact_min 算法逐字节同源（迁入公开化，E9）。
  """
  ref_t: Point = tuple(float(v) for v in ref)
  d = len(ref_t)
  live: list[Point] = [
    tuple(float(v) for v in p) for p in pts
    if len(p) == d and all(float(p[j]) < ref_t[j] for j in range(d))
  ]
  if not live:
    return 0.0
  if d == 1:
    return max(0.0, ref_t[0] - min(p[0] for p in live))
  cuts = sorted({p[-1] for p in live})
  total = 0.0
  for i, lo in enumerate(cuts):
    hi = cuts[i + 1] if i + 1 < len(cuts) else ref_t[-1]
    if hi <= lo:
      continue
    active = [p[:-1] for p in live if p[-1] <= lo]
    total += (hi - lo) * exact_hypervolume(active, ref_t[:-1])
  return total


def _dominates(a: np.ndarray, b: np.ndarray) -> bool:
  """标准 Pareto 支配（最小化）：全部 ≤ 且至少一维 <。"""
  return bool(np.all(a <= b) and np.any(a < b))


def nondominated_indices(objectives: Sequence[Sequence[float]]) -> list[int]:
  """标准（无约束）非支配集索引，保持输入顺序；重复点互不支配、同留。"""
  if len(objectives) == 0:
    return []
  f = np.asarray(objectives, dtype=float)
  if f.ndim != 2:
    raise ValueError("objectives 须为二维数组 (n_points, n_objectives)")
  n = f.shape[0]
  keep: list[int] = []
  for i in range(n):
    dominated = False
    for j in range(n):
      if i != j and _dominates(f[j], f[i]):
        dominated = True
        break
    if not dominated:
      keep.append(i)
  return keep


def constraint_dominates(
  fa: np.ndarray, va: float, fb: np.ndarray, vb: float,
) -> bool:
  """Deb 可行优先支配：a 是否支配 b。

  va/vb 为总违约量（≥0，0=可行）：
  - a 可行、b 不可行 → a 支配；
  - 两者可行 → 标准 Pareto 支配；
  - 两者不可行 → 违约量小者支配；相等时退回标准支配。
  """
  a_feas, b_feas = va <= 0.0, vb <= 0.0
  if a_feas and not b_feas:
    return True
  if not a_feas and b_feas:
    return False
  if a_feas and b_feas:
    return _dominates(fa, fb)
  if va < vb:
    return True
  if va > vb:
    return False
  return _dominates(fa, fb)


def constrained_pareto_front(
  objectives: Sequence[Sequence[float]],
  violations: Sequence[Sequence[float]] | None = None,
) -> list[int]:
  """约束 Pareto 前沿索引（Deb 可行优先支配；最小化口径）。

  violations 每点一条违约向量（各分量 ≥0，0=可行边界）；None 或全空
  → 退化为标准非支配集（与 nondominated_indices 同）。总违约量取
  分量和（与 pymoo CV 同义：Σmax(G,0)）。返回索引按输入顺序。
  """
  if len(objectives) == 0:
    return []
  f = np.asarray(objectives, dtype=float)
  if f.ndim != 2:
    raise ValueError("objectives 须为二维数组 (n_points, n_objectives)")
  n = f.shape[0]
  if violations is None or all(len(v) == 0 for v in violations):
    return nondominated_indices(objectives)
  if len(violations) != n:
    raise ValueError(
      f"violations 行数 {len(violations)} 与 objectives 行数 {n} 不符")
  total = np.array([float(sum(max(0.0, float(x)) for x in v))
           for v in violations])
  keep: list[int] = []
  for i in range(n):
    dominated = False
    for j in range(n):
      if i != j and constraint_dominates(f[j], total[j], f[i], total[i]):
        dominated = True
        break
    if not dominated:
      keep.append(i)
  return keep


def default_reference_point(objectives: Sequence[Sequence[float]]) -> list[float]:
  """缺省超体积参考点：各维最差值 + max(1.0, 0.1·|最差值|)。

  与 mf_backend.hypervolume_contribution 的缺省 ref 惯例同源（旧 max·1.1
  对 dB 类负值指标会把参考点收进支配域）。
  """
  f = np.asarray(objectives, dtype=float)
  if f.ndim != 2 or f.shape[0] == 0:
    raise ValueError("objectives 须为非空二维数组")
  out: list[float] = []
  for c in range(f.shape[1]):
    worst = float(np.max(f[:, c]))
    out.append(worst + max(1.0, 0.1 * abs(worst)))
  return out


def hv_convergence(
  fronts: Sequence[Sequence[Sequence[float]]],
  ref: Sequence[float],
) -> list[float]:
  """逐代前沿超体积序列（统一 ref）。

  fronts[g] 为第 g 代的非支配集（或任意点集：内部先取非支配集再算
  HV，被支配点贡献恒 0，取不取结果相同）。空前沿记 0.0。弱单调性
  （「hypervolume 单调」）由调用方对精英存档前沿断言；本函数
  不做断言、只算数。
  """
  ref_t = tuple(float(v) for v in ref)
  out: list[float] = []
  for front in fronts:
    pts = [tuple(float(v) for v in p) for p in front]
    out.append(exact_hypervolume(pts, ref_t) if pts else 0.0)
  return out


def is_weakly_monotone(values: Sequence[float], tol: float = 1e-12) -> bool:
  """序列是否弱单调不减（允许 tol 级浮点回退）。"""
  return all(values[i + 1] >= values[i] - tol for i in range(len(values) - 1))
