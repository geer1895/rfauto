"""warm-start —— runs/ 同族历史点 → 新优化先验迁移（负迁移防线=任务相似度门）。

设计要点：
- 分层（import-linter 契约）：本模块属 optimization 层，不 import service——
 历史点数据以 list[dict] 注入（环逻辑与数据获取分离，同
 surrogate_loop.evaluate_fn 注入先例），由调用方（service/CLI）负责
 从 dataset_service（E1）查数据后传入。
- 相似度门（负迁移防线， TL-BO 初始点视角）：单点参数键与 bounds
 键的 Jaccard 重叠率 ≥ min_similarity（同族参数空间）且数值落界率
 ≥ 0.5（同一设计工况量级）才收为候选；有效点不足即整体拒绝，
 返回 ``{"ok": False, "reason": "insufficient_similarity", ...}``，
 不凑数注入（学术诚信原则：门拒绝≠注入弱先验）。
- 排序与裁剪：有效点按 cost 升序取 top_n（历史最优先注入）；界外数值
 裁剪到界内（Optuna fixed_params 越界会使 trial 建议阶段报错）。
- #123 教训：``study.enqueue_trial`` 返回值随 optuna 版本可能是 None——
 注入后回查 study 的 WAITING trial 集合确认，不依赖返回值。optuna 4.9
 的 Study 无 ``waiting_trials()`` 方法，回查统一走
 ``get_trials(states=(TrialState.WAITING,))``。
"""

from __future__ import annotations

from typing import Any

from optuna.trial import TrialState

__all__ = ["enqueue_warm_start", "warm_start_points"]


# ─── 相似度门内核 ─────────────────────────────────────────────────────────────

def _jaccard(a: set[str], b: set[str]) -> float:
  """Jaccard 重叠率 |a∩b| / |a∪b|；双方皆空时定义为 0（拒绝）。"""
  union = a | b
  if not union:
    return 0.0
  return len(a & b) / len(union)


def _is_number(v: Any) -> bool:
  """数值判定（bool 是 int 子类，须显式排除）。"""
  return not isinstance(v, bool) and isinstance(v, (int, float))


def _in_bounds_rate(
  params: dict[str, Any],
  bounds: dict[str, dict[str, Any]],
) -> float:
  """数值落界率：params 与 bounds 交集键中值落在 [low, high] 的比例。

  交集内无数值键（checked==0）时返回 0.0——无从证明同工况，按拒绝处理。
  """
  checked = 0
  inside = 0
  for key, spec in bounds.items():
    if key not in params or not _is_number(params[key]):
      continue
    checked += 1
    low = float(spec["low"])
    high = float(spec["high"])
    if low <= float(params[key]) <= high:
      inside += 1
  if checked == 0:
    return 0.0
  return inside / checked


def _clip_to_bounds(
  params: dict[str, Any],
  bounds: dict[str, dict[str, Any]],
) -> dict[str, Any]:
  """界外数值裁剪到界内；非数值/不在 bounds 的键原样保留。"""
  out: dict[str, Any] = {}
  for key, val in params.items():
    if key in bounds and _is_number(val):
      low = float(bounds[key]["low"])
      high = float(bounds[key]["high"])
      out[key] = min(max(float(val), low), high)
    else:
      out[key] = val
  return out


def warm_start_points(
  history_points: list[dict[str, Any]],
  *,
  bounds: dict[str, dict[str, Any]],
  top_n: int = 3,
  min_similarity: float = 0.5,
) -> dict[str, Any]:
  """相似度门筛选历史点，按 cost 升序取 top_n，界外值裁剪到界内。

  Args:
    history_points: 历史点列表，每点形如
      ``{"params": {...}, "cost": float, ...}``（调用方从
      dataset_service 查得；多余键被忽略）。
    bounds: 新战役参数空间 ``{param: {"low": float, "high": float}}``
      （同 optimizer.extract_param_ranges 口径）。
    top_n: 最多注入的先验点数（默认 3）。
    min_similarity: Jaccard 键重叠率门限（默认 0.5）。

  Returns:
    门通过：``{"ok": True, "points": [{"params", "cost"}, ...],
    "n_candidates", "n_rejected"}``——points 已按 cost 升序、界外裁剪。
    有效点 <1：``{"ok": False, "reason": "insufficient_similarity",
    "n_candidates", "n_rejected"}``。
  """
  n_candidates = len(history_points)
  valid: list[tuple[float, dict[str, Any]]] = []
  n_rejected = 0
  for point in history_points:
    if not isinstance(point, dict):
      n_rejected += 1
      continue
    params = point.get("params")
    cost = point.get("cost")
    if not isinstance(params, dict) or not _is_number(cost):
      # 无可排序 cost 的点无法参与"最优先注入"，计拒绝
      n_rejected += 1
      continue
    param_keys = {str(k) for k in params}
    bound_keys = {str(k) for k in bounds}
    if _jaccard(param_keys, bound_keys) < float(min_similarity):
      n_rejected += 1
      continue
    if _in_bounds_rate(params, bounds) < 0.5:
      n_rejected += 1
      continue
    valid.append((float(cost), point))

  stats = {"n_candidates": n_candidates, "n_rejected": n_rejected}
  if not valid:
    return {"ok": False, "reason": "insufficient_similarity", **stats}

  valid.sort(key=lambda item: item[0])
  take = max(int(top_n), 0)
  points = [
    {
      "params": _clip_to_bounds(point.get("params") or {}, bounds),
      "cost": cost,
    }
    for cost, point in valid[:take]
  ]
  return {"ok": True, "points": points, **stats}


# ─── Optuna 注入（#123 回查口径） ────────────────────────────────────────────

def enqueue_warm_start(study: Any, points: list[dict[str, Any]]) -> list[int]:
  """把 warm-start 点逐个 ``study.enqueue_trial`` 注入，回查注入 trial 号。

  #123：enqueue_trial 返回值随 optuna 版本可能是 None——注入前快照既有
  WAITING 集合，注入后回查差集作为注入成功的 trial 号，不依赖返回值。
  单点注入失败不阻塞其余点（best-effort，#105）。WAITING trial 在后续
  ``study.optimize`` 中先被弹出执行=先验起点。

  Returns:
    本次注入成功的 trial 号（升序）。
  """
  before = {
    t.number
    for t in study.get_trials(deepcopy=False, states=(TrialState.WAITING,))
  }
  for point in points:
    params = point.get("params") if isinstance(point, dict) else None
    if not isinstance(params, dict):
      continue
    try:
      study.enqueue_trial(dict(params))
    except Exception: # 单点注入失败不阻塞其余先验点
      continue
  after = study.get_trials(deepcopy=False, states=(TrialState.WAITING,))
  return sorted(t.number for t in after if t.number not in before)
