"""active_learning：主动学习采样提议（阶段 6.5 首片 + 增肉扩充）。

基于 NN bagging 集成的预测 std（不确定度）在搜索空间内提议下一批
真机采样点：候选网格上预测不确定度最大、且与既有样本保持最小距离。
纯确定性内核——agent/UI 只消费提议结果。

加性增肉：
- 不确定性来源扩到三种，统一 JSON 契约（estimate_uncertainty）：
  * "nn"    —— 既有 SurrogateModel.uncertainty（NN bagging，走注册表）；
  * "bootstrap" —— 对任意注册代理做确定性 bootstrap 重采样集成的方差；
  * "gp"    —— RBF 核 GP 后验方差（纯 numpy 闭式，固定超参、确定性）。
- 探索槽接口（score_exploration_candidates / maximin_exploration_point）：
 供 WP3.2 maxi-min 探索槽调用的纯函数打分——本模块不 import 也不改
 surrogate_loop.py，只提供可被其调用的确定性接口。
- 同预算加速裁判（convergence_speedup_benchmark，#207 裁判面选型）：
 合成带噪耦合碗上 active_learning 引导 vs i.i.d. 随机搜索的收敛加速；
 用合成函数而非 fake 原生模型（后者病态不可用），多固定种子取中位数
 防种子彩票。

契约（estimate_uncertainty 返回值）::

  {
   "ok": True,
   "source": "gp" | "bootstrap" | "nn",
   "kind": <代理注册键或 None>,
   "n_samples": int,
   "metric_keys": [...],
   "points": [
    {"params": {...},
     "mean": {metric: float},
     "sigma": {metric: float >= 0},
     "score": float}     # score = Σ sigma（与既有 propose_next_points 同口径）
   ],
  }
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

#: 支持的不确定度来源（estimate_uncertainty(source=...)）。
UNCERTAINTY_SOURCES = ("nn", "bootstrap", "gp")

#: 主动学习裁判用的单一合成指标键。
COST_KEY = "cost"


def propose_next_points(
  samples_path: str | Path,
  k: int = 5,
  *,
  kind: str = "nn",
  n_candidates: int = 500,
  min_dist: float = 0.12,
  seed: int = 42,
) -> dict[str, Any]:
  """提议下一批采样点：不确定度 × 距离双重准则。

  1. 从 samples.json 训练代理（需 kind 支持 uncertainty，如 nn bagging）；
  2. LHS 撒 n_candidates 候选点；
  3. 过滤与既有样本归一化距离 < min_dist 者；
  4. 按预测 std 之和降序取前 k 个。
  """

  from rfauto.optimization.sample_design import lhs_points, np_rel
  from rfauto.service.calibration_service import _make_model

  path = Path(samples_path)
  if not path.exists():
    return {"ok": False, "errors": [f"样本集不存在: {path}"]}
  data = json.loads(path.read_text(encoding="utf-8"))
  samples = list(data.get("samples") or [])
  bounds_raw = data.get("bounds") or {}
  if len(samples) < 5:
    return {"ok": False, "errors": ["样本点不足（需 ≥5）"]}
  bounds = {kk: (float(v[0]), float(v[1])) for kk, v in bounds_raw.items()}

  model = _make_model(kind, bounds, order=2, ridge_lambda=0.1)
  model.fit(samples)
  if not hasattr(model, "uncertainty"):
    return {"ok": False, "errors": [f"代理 {kind} 不支持 uncertainty()"]}

  names = sorted(bounds)
  lower = [bounds[n][0] for n in names]
  span = [max(bounds[n][1] - bounds[n][0], 1e-12) for n in names]
  include = [np_rel(s["params"], names, lower, span) for s in samples]

  cand = lhs_points(bounds, n_candidates, seed=seed)["points"]
  scored = []
  for pt in cand:
    pn = np_rel(pt, names, lower, span)
    d_existing = min(
      (sum((pn[n] - q.get(n, pn[n])) ** 2 for n in names) ** 0.5
       for q in include), default=float("inf"))
    if d_existing < min_dist:
      continue
    try:
      unc = model.uncertainty(pt)
    except Exception:
      unc = None
    if unc is None:
      continue
    score = sum(float(v) for v in unc.values() if isinstance(v, (int, float)))
    scored.append((score, pt))
  scored.sort(key=lambda t: t[0], reverse=True)
  proposed = [{"params": pt, "uncertainty_score": round(s, 6)}
        for s, pt in scored[:k]]
  return {
    "ok": True,
    "samples_path": str(path),
    "surrogate_kind": kind,
    "n_existing": len(samples),
    "n_candidates": n_candidates,
    "proposed": proposed,
    "note": "提议点需真机复验后方可并入样本集（置信度由校准 gate 背书）",
  }


# ─── 内部工具（归一化 / 指标键 / 数值护栏） ───────────────────────────────────


def _bounds_arrays(
  bounds: dict[str, tuple[float, float]] | dict[str, list[float]],
) -> tuple[list[str], list[float], list[float]]:
  """(names, lower, span)——span 保底 1e-12，防零宽域除零。"""
  names = sorted(bounds)
  lower = [float(bounds[n][0]) for n in names]
  span = [max(float(bounds[n][1]) - float(bounds[n][0]), 1e-12) for n in names]
  return names, lower, span


def _normalize_points(
  points: list[dict[str, float]],
  names: list[str],
  lower: list[float],
  span: list[float],
) -> np.ndarray:
  """点集 → 归一化矩阵（缺失键回落到下界，同 WP3.2 _normalize 口径）。

  非数值参数显式抛 ValueError（非法输入报错，不静默当 0）。
  """
  if not points:
    return np.zeros((0, len(names)), dtype=float)
  rows = []
  for pt in points:
    if not isinstance(pt, dict):
      raise ValueError(f"点必须是参数字典: {pt!r}")
    row = []
    for i, n in enumerate(names):
      try:
        row.append((float(pt.get(n, lower[i])) - lower[i]) / span[i])
      except (TypeError, ValueError) as exc:
        raise ValueError(f"参数 {n} 非数值: {pt.get(n)!r}") from exc
    rows.append(row)
  return np.array(rows, dtype=float)


def _numeric_metric_keys(samples: list[dict[str, Any]]) -> list[str]:
  """样本集中出现过的有限数值指标键（与既有代理口径一致）。"""
  keys: set[str] = set()
  for s in samples:
    for k, v in (s.get("metrics") or {}).items():
      if isinstance(v, (int, float)) and math.isfinite(float(v)):
        keys.add(k)
  return sorted(keys)


# ─── 不确定性来源 ①：bootstrap 重采样集成方差 ────────────────────────────────


def _bootstrap_ensemble_predictions(
  samples: list[dict[str, Any]],
  bounds: dict[str, tuple[float, float]],
  points: list[dict[str, float]],
  *,
  kind: str,
  n_ensemble: int,
  seed: int,
  order: int,
  ridge_lambda: float,
  metric_keys: list[str],
) -> tuple[np.ndarray, np.ndarray]:
  """对样本做 K 次有放回重采样 → 拟合 K 个同族代理 → 集成 mean/std。

  确定性：rng 固定种子、代理拟合确定性（同配置同结果）。
  返回 (means, sigmas)，形状 (n_points, n_metrics)。
  """
  from rfauto.service.calibration_service import _make_model

  n = len(samples)
  rng = np.random.default_rng(seed)
  members: list[np.ndarray] = []
  for _ in range(max(int(n_ensemble), 1)):
    idx = rng.integers(0, n, n)
    subset = [samples[i] for i in idx]
    try:
      model = _make_model(kind, bounds, order=order,
                ridge_lambda=ridge_lambda)
      model.fit(subset)
    except Exception:
      continue # 单个重采样拟合失败不炸整条不确定度通道
    rows = []
    for pt in points:
      try:
        pred = model.predict(pt)
      except Exception:
        pred = {}
      rows.append([float(pred.get(k, np.nan)) for k in metric_keys])
    members.append(np.array(rows, dtype=float))
  if not members:
    return (np.zeros((len(points), len(metric_keys))),
        np.zeros((len(points), len(metric_keys))))
  stack = np.stack(members) # (K, P, M)
  finite = np.isfinite(stack)
  count = finite.sum(axis=0)
  denom = np.maximum(count, 1)
  safe = np.where(finite, stack, 0.0)
  means = np.where(count > 0, safe.sum(axis=0) / denom, 0.0)
  sq = np.where(finite, stack ** 2, 0.0).sum(axis=0)
  var = np.where(count > 1, np.maximum(sq / denom - means ** 2, 0.0), 0.0)
  return means, np.sqrt(var)


# ─── 不确定性来源 ②：GP 后验方差（RBF 核，纯 numpy 闭式） ────────────────────


def _gp_posterior_predictions(
  samples: list[dict[str, Any]],
  bounds: dict[str, tuple[float, float]],
  points: list[dict[str, float]],
  *,
  length_scale: float,
  noise: float,
  metric_keys: list[str],
) -> tuple[np.ndarray, np.ndarray]:
  """RBF 核 GP 后验 mean/std（超参固定 → 无优化迭代 → 确定且快）。

  单位空间 RBF 核 k(a,b)=exp(-‖a-b‖²/(2ℓ²))，噪声 nugget 稳定求逆；
  后验方差 var(x*)=k(x*,x*) - k*ᵀ(K+σ²I)⁻¹k*，std 换算回原量纲。
  有效样本 <2 的指标记 σ=0（不硬拟，不编造不确定度）。
  """
  names, lower, span = _bounds_arrays(bounds)
  X = _normalize_points([s.get("params") or {} for s in samples],
             names, lower, span)
  P = _normalize_points(points, names, lower, span)
  n_out = len(points)
  means = np.zeros((n_out, len(metric_keys)))
  sigmas = np.zeros((n_out, len(metric_keys)))
  l2 = max(float(length_scale), 1e-9) ** 2
  for j, key in enumerate(metric_keys):
    y = np.array([float((s.get("metrics") or {}).get(key, np.nan))
           for s in samples], dtype=float)
    mask = np.isfinite(y)
    if int(mask.sum()) < 2:
      continue
    xm, ym = X[mask], y[mask]
    mu = float(ym.mean())
    sd = float(ym.std()) + 1e-12
    z = (ym - mu) / sd
    d2 = ((xm[:, None, :] - xm[None, :, :]) ** 2).sum(-1)
    k_mat = np.exp(-d2 / (2.0 * l2)) + max(float(noise), 0.0) * np.eye(len(xm))
    try:
      k_inv = np.linalg.inv(k_mat)
    except np.linalg.LinAlgError:
      k_inv = np.linalg.pinv(k_mat)
    d2p = ((P[:, None, :] - xm[None, :, :]) ** 2).sum(-1)
    k_star = np.exp(-d2p / (2.0 * l2)) # (P, n)
    means[:, j] = (k_star @ k_inv @ z) * sd + mu
    var = 1.0 - np.einsum("pn,nm,pm->p", k_star, k_inv, k_star)
    sigmas[:, j] = np.sqrt(np.clip(var, 0.0, None)) * sd
  return means, sigmas


# ─── 不确定性来源 ③：既有注册代理的 uncertainty()（nn bagging 等） ───────────


def _surrogate_uncertainty_predictions(
  samples: list[dict[str, Any]],
  bounds: dict[str, tuple[float, float]],
  points: list[dict[str, float]],
  *,
  kind: str,
  order: int,
  ridge_lambda: float,
) -> tuple[np.ndarray, np.ndarray]:
  """走 surrogate_registry 的 uncertainty() 通道（nn bagging 既有实现）。"""
  from rfauto.service.calibration_service import _make_model

  model = _make_model(kind, bounds, order=order, ridge_lambda=ridge_lambda)
  model.fit(samples)
  if not hasattr(model, "uncertainty"):
    raise ValueError(f"代理 {kind} 不支持 uncertainty()")
  means, sigmas = [], []
  for pt in points:
    pred = model.predict(pt)
    unc = model.uncertainty(pt)
    means.append([float(pred.get(COST_KEY, 0.0))])
    sigmas.append([float((unc or {}).get(COST_KEY, 0.0))])
  return np.array(means, dtype=float), np.array(sigmas, dtype=float)


def _predict_mean_sigma(
  samples: list[dict[str, Any]],
  bounds: dict[str, tuple[float, float]],
  points: list[dict[str, float]],
  *,
  source: str,
  metric_keys: list[str],
  seed: int = 42,
  n_ensemble: int = 8,
  kind: str | None = None,
  order: int = 2,
  ridge_lambda: float = 0.1,
  length_scale: float = 0.3,
  noise: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray]:
  """统一分派：source → (means, sigmas)。"""
  if source == "gp":
    return _gp_posterior_predictions(
      samples, bounds, points, length_scale=length_scale, noise=noise,
      metric_keys=metric_keys)
  if source == "bootstrap":
    return _bootstrap_ensemble_predictions(
      samples, bounds, points, kind=kind or "poly_ridge",
      n_ensemble=n_ensemble, seed=seed, order=order,
      ridge_lambda=ridge_lambda, metric_keys=metric_keys)
  if source == "nn":
    return _surrogate_uncertainty_predictions(
      samples, bounds, points, kind=kind or "nn", order=order,
      ridge_lambda=ridge_lambda)
  raise ValueError(f"未知不确定度来源: {source}（可用: {list(UNCERTAINTY_SOURCES)}）")


# ─── 统一契约入口 ────────────────────────────────────────────────────────────


def estimate_uncertainty(
  samples: list[dict[str, Any]],
  bounds: dict[str, tuple[float, float]],
  points: list[dict[str, float]],
  *,
  source: str = "gp",
  metric_keys: list[str] | None = None,
  seed: int = 42,
  n_ensemble: int = 8,
  kind: str | None = None,
  order: int = 2,
  ridge_lambda: float = 0.1,
  length_scale: float = 0.3,
  noise: float = 1e-6,
) -> dict[str, Any]:
  """统一不确定性契约：任意来源 → 同构 JSON（mean/sigma/score）。

  非法输入：source 未注册 / 点参数非数值 → raise ValueError；
  退化输入（空 bounds / 空样本 / 空候选点）→ ok=False 或空列表，不崩。
  """
  if source not in UNCERTAINTY_SOURCES:
    raise ValueError(
      f"未知不确定度来源: {source}（可用: {list(UNCERTAINTY_SOURCES)}）")
  if not bounds:
    return {"ok": False, "source": source,
        "errors": ["搜索空间为空（bounds 缺失）"]}
  samples = list(samples or [])
  points = list(points or [])
  if not samples:
    return {"ok": False, "source": source,
        "errors": ["样本为空，无法估计不确定度"]}
  keys = list(metric_keys) if metric_keys else _numeric_metric_keys(samples)
  if not keys:
    return {"ok": False, "source": source,
        "errors": ["样本 metrics 里没有可用数值指标"]}
  if not points:
    return {"ok": True, "source": source, "kind": kind,
        "n_samples": len(samples), "metric_keys": keys,
        "points": [], "note": "候选点为空"}

  means, sigmas = _predict_mean_sigma(
    samples, bounds, points, source=source, metric_keys=keys, seed=seed,
    n_ensemble=n_ensemble, kind=kind, order=order,
    ridge_lambda=ridge_lambda, length_scale=length_scale, noise=noise)

  out = []
  for i, pt in enumerate(points):
    mean_d = {k: float(means[i, j]) for j, k in enumerate(keys)}
    sigma_d = {k: float(max(sigmas[i, j], 0.0))
          for j, k in enumerate(keys)}
    out.append({"params": dict(pt), "mean": mean_d, "sigma": sigma_d,
          "score": float(sum(sigma_d.values()))})
  return {"ok": True, "source": source, "kind": kind,
      "n_samples": len(samples), "metric_keys": keys, "points": out,
      "note": "σ 仅由确定性内核产出（#7），agent/UI 只消费"}


def bootstrap_uncertainty(
  samples: list[dict[str, Any]],
  bounds: dict[str, tuple[float, float]],
  points: list[dict[str, float]],
  *,
  kind: str = "poly_ridge",
  n_ensemble: int = 8,
  seed: int = 42,
  order: int = 2,
  ridge_lambda: float = 0.1,
) -> dict[str, Any]:
  """bootstrap 不确定度来源的便捷入口（契约同 estimate_uncertainty）。"""
  return estimate_uncertainty(
    samples, bounds, points, source="bootstrap", kind=kind,
    n_ensemble=n_ensemble, seed=seed, order=order,
    ridge_lambda=ridge_lambda)


def gp_posterior_uncertainty(
  samples: list[dict[str, Any]],
  bounds: dict[str, tuple[float, float]],
  points: list[dict[str, float]],
  *,
  length_scale: float = 0.3,
  noise: float = 1e-6,
) -> dict[str, Any]:
  """GP 后验方差来源的便捷入口（契约同 estimate_uncertainty）。"""
  return estimate_uncertainty(
    samples, bounds, points, source="gp",
    length_scale=length_scale, noise=noise)


# ─── 探索槽接口（供 WP3.2 maxi-min 探索槽调用，纯函数、确定性） ──────────────


def score_exploration_candidates(
  bounds: dict[str, tuple[float, float]],
  candidates: list[dict[str, float]],
  exclude: list[dict[str, float]] | None = None,
  *,
  min_dist: float | None = None,
) -> dict[str, Any]:
  """maxi-min 探索槽打分（纯函数、确定性）：候选到 exclude 的最小归一化距离。

  与 WP3.2 _exploration_point 同语义：exclude 为空时 score=1.0（其
  default=1.0 口径）；distance 用归一化欧氏距离。返回按 score 降序，
  并列时按参数元组字典序定序（跨进程可复现）。min_dist 只做标注
  （eligible 字段），不删候选——调用方自行决定是否过滤。
  """
  if not bounds:
    return {"ok": False, "errors": ["搜索空间为空（bounds 缺失）"]}
  names, lower, span = _bounds_arrays(bounds)
  excl = list(exclude or [])
  excl_norm = (_normalize_points(excl, names, lower, span)
         if excl else np.zeros((0, len(names))))
  scored = []
  for pt in list(candidates or []):
    if not isinstance(pt, dict):
      raise ValueError(f"候选点必须是参数字典: {pt!r}")
    pn = _normalize_points([pt], names, lower, span)[0]
    dist = 1.0 if len(excl_norm) == 0 else float(
      np.min(np.sqrt(((excl_norm - pn) ** 2).sum(axis=1))))
    scored.append({
      "params": dict(pt),
      "exploration_score": dist,
      "eligible": bool(min_dist is None or dist >= float(min_dist)),
    })
  scored.sort(key=lambda r: (-r["exploration_score"],
                tuple(sorted(r["params"].items()))))
  return {"ok": True, "names": names, "n_candidates": len(scored),
      "n_exclude": len(excl), "scored": scored,
      "best": scored[0] if scored else None,
      "note": "score=到已评估点的最小归一化欧氏距离（越大越该探索）"}


def maximin_exploration_point(
  bounds: dict[str, tuple[float, float]],
  exclude: list[dict[str, float]] | None = None,
  *,
  n_pool: int = 64,
  seed: int = 42,
) -> dict[str, float] | None:
  """WP3.2 探索槽的确定性便捷入口：LHS 池中 maxi-min 点。

  池点全部与已评估点重合（best score ≤1e-9）时返回 None（同其契约）。
  """
  from rfauto.optimization.sample_design import lhs_points

  if not bounds:
    return None
  pool = lhs_points(bounds, max(int(n_pool), 1), seed=seed)["points"]
  if not pool:
    return None
  ranked = score_exploration_candidates(bounds, pool, exclude)
  if not ranked["ok"] or not ranked["scored"]:
    return None
  best = ranked["scored"][0]
  return best["params"] if best["exploration_score"] > 1e-9 else None


# ─── 采集驱动（不确定性引导的下一采样点，供加速裁判/环复用） ─────────────────


def active_learning_search(
  evaluate_fn: Callable[[dict[str, float]], float],
  bounds: dict[str, tuple[float, float]],
  *,
  budget: int = 40,
  n_init: int = 5,
  seed: int = 42,
  source: str = "gp",
  beta: float = 2.0,
  n_pool: int = 256,
  length_scale: float = 0.3,
  noise: float = 1e-6,
  n_ensemble: int = 8,
) -> dict[str, Any]:
  """不确定性引导采样：LCB α(x)=μ(x) − β·σ(x) 取最小（确定性）。

  evaluate_fn: params → 标量 cost（合成函数或真机包装，纯确定性）。
  初始 n_init 点 LHS，随后每轮按 LCB 从 LHS 候选池选 1 点评估，
  至 budget 次评估用完。返回 JSON 契约（best_cost/best_params/history）。
  """
  from rfauto.optimization.sample_design import lhs_points

  if not bounds:
    return {"ok": False, "errors": ["搜索空间为空（bounds 缺失）"]}
  if not callable(evaluate_fn):
    raise TypeError("evaluate_fn 必须可调用（params → cost）")
  if int(budget) < 1:
    raise ValueError("budget 必须 ≥1")
  if source not in UNCERTAINTY_SOURCES and source != "nn":
    raise ValueError(f"未知不确定度来源: {source}")

  budget = int(budget)
  n_init = max(1, min(int(n_init), budget))
  samples: list[dict[str, Any]] = []

  def _eval(pt: dict[str, float]) -> None:
    cost = float(evaluate_fn(dict(pt)))
    samples.append({"params": dict(pt),
            "metrics": {COST_KEY: cost}})

  for pt in lhs_points(bounds, n_init, seed=seed)["points"]:
    _eval(pt)
  history = [{"round": 0, "phase": "lhs_init", "n_evals": len(samples),
        "best_cost": min(s["metrics"][COST_KEY] for s in samples)}]

  rnd = 0
  while len(samples) < budget:
    rnd += 1
    pool = lhs_points(bounds, max(int(n_pool), 1),
             seed=seed * 1000 + rnd)["points"]
    if not pool:
      break
    means, sigmas = _predict_mean_sigma(
      samples, bounds, pool, source=source, metric_keys=[COST_KEY],
      seed=seed + rnd, n_ensemble=n_ensemble,
      length_scale=length_scale, noise=noise)
    lcb = means[:, 0] - float(beta) * sigmas[:, 0]
    pick = int(np.argmin(lcb))
    _eval(pool[pick])
    history.append({"round": rnd, "n_evals": len(samples),
            "best_cost": min(s["metrics"][COST_KEY]
                     for s in samples)})
  best = min(samples, key=lambda s: s["metrics"][COST_KEY])
  return {"ok": True, "source": source, "beta": float(beta), "seed": seed,
      "budget": budget, "n_evals": len(samples),
      "best_cost": float(best["metrics"][COST_KEY]),
      "best_params": dict(best["params"]),
      "samples": samples, "history": history,
      "note": "LCB 采集（μ−βσ）确定性；σ 来自 estimate_uncertainty 通道"}


# ─── ⑦ 验收裁判：合成函数上 AL vs 随机搜索的收敛加速 ──────────────────

#: 裁判合成函数定义域（已知、闭式，与 fake 原生模型无关——#207）。
BOWL_BOUNDS: dict[str, tuple[float, float]] = {"x": (-2.0, 2.0),
                       "y": (-2.0, 2.0)}


def synthetic_noisy_bowl(params: dict[str, float]) -> float:
  """裁判合成函数：带噪耦合碗（解析式，强凸二次 + 高频耦合纹波）。

  f(x,y) = u² + v² + 0.8·u·v + 0.05·sin(9x)·sin(11y)，u=x−0.3，v=y+0.4。
  定义域 x,y∈[−2,2]；全局最小由密网格确定（见 synthetic_bowl_range）。
  """
  x = float(params["x"])
  y = float(params["y"])
  u = x - 0.3
  v = y + 0.4
  return u * u + v * v + 0.8 * u * v + 0.05 * math.sin(9.0 * x) * math.sin(11.0 * y)


def synthetic_bowl_range(n_grid: int = 201) -> tuple[float, float]:
  """密网格求合成碗的 (min, max)——目标阈值必须高于 min（#207 防种子彩票）。"""
  n = max(int(n_grid), 2)
  xs = np.linspace(BOWL_BOUNDS["x"][0], BOWL_BOUNDS["x"][1], n)
  ys = np.linspace(BOWL_BOUNDS["y"][0], BOWL_BOUNDS["y"][1], n)
  xx, yy = np.meshgrid(xs, ys)
  u = xx - 0.3
  v = yy + 0.4
  vals = u * u + v * v + 0.8 * u * v + 0.05 * np.sin(9.0 * xx) * np.sin(11.0 * yy)
  return float(vals.min()), float(vals.max())


def _random_search_costs(
  evaluate_fn: Callable[[dict[str, float]], float],
  bounds: dict[str, tuple[float, float]],
  budget: int,
  seed: int,
) -> list[float]:
  """i.i.d. 均匀随机搜索基线（非 LHS——LHS 是空间填充设计，不算随机搜索）。"""
  rng = np.random.default_rng(seed)
  names = sorted(bounds)
  costs = []
  for _ in range(int(budget)):
    pt = {n: float(rng.uniform(float(bounds[n][0]), float(bounds[n][1])))
       for n in names}
    costs.append(float(evaluate_fn(pt)))
  return costs


def _evals_to_target(costs: list[float], target: float) -> int | None:
  for i, c in enumerate(costs):
    if c <= target:
      return i + 1
  return None


def convergence_speedup_benchmark(
  *,
  budget: int = 40,
  n_init: int = 5,
  n_seeds: int = 15,
  seed0: int = 0,
  source: str = "gp",
  beta: float = 2.0,
  n_pool: int = 256,
  length_scale: float = 0.3,
  target_fraction: float = 0.02,
) -> dict[str, Any]:
  """ ⑦ 验收：同预算下 active_learning 引导 vs 随机搜索的收敛加速。

  合成函数（带噪耦合碗，定义域已知）上等预算比"首次达到目标阈值的
  评估次数"；目标阈值 = f_min + fraction·(f_max−f_min)，**高于极值下限**
  （#207：阈值不可低于极值，否则随机搜索有种子彩票）。未达标按预算截尾
  （对 active_learning 保守）。多固定种子各跑一对（配对同种子），
  取加速比中位数（防种子彩票）。speedup = 随机评估次数 / AL 评估次数。
  """
  if source not in UNCERTAINTY_SOURCES:
    raise ValueError(f"未知不确定度来源: {source}")
  budget = int(budget)
  if budget < 2:
    raise ValueError("budget 必须 ≥2")
  n_seeds = max(int(n_seeds), 1)
  f_min, f_max = synthetic_bowl_range()
  target = f_min + float(target_fraction) * (f_max - f_min)
  if target <= f_min:
    raise ValueError("目标阈值低于极值下限（#207 禁止）")

  speedups: list[float] = []
  al_best: list[float] = []
  rd_best: list[float] = []
  al_evals: list[int] = []
  rd_evals: list[int] = []
  for s in range(n_seeds):
    seed = seed0 + s
    al = active_learning_search(
      synthetic_noisy_bowl, BOWL_BOUNDS, budget=budget, n_init=n_init,
      seed=seed, source=source, beta=beta, n_pool=n_pool,
      length_scale=length_scale)
    rd_costs = _random_search_costs(
      synthetic_noisy_bowl, BOWL_BOUNDS, budget, seed + 7919)
    al_costs = [x["metrics"][COST_KEY] for x in al["samples"]]
    n_al = _evals_to_target(al_costs, target) or budget
    n_rd = _evals_to_target(rd_costs, target) or budget
    al_evals.append(n_al)
    rd_evals.append(n_rd)
    speedups.append(n_rd / n_al)
    al_best.append(min(al_costs))
    rd_best.append(min(rd_costs))

  median_speedup = float(np.median(speedups))
  return {
    "ok": True,
    "function": "synthetic_noisy_bowl",
    "bounds": {k: list(v) for k, v in BOWL_BOUNDS.items()},
    "function_min": f_min,
    "function_max": f_max,
    "target": target,
    "target_fraction": float(target_fraction),
    "budget": budget,
    "n_init": int(n_init),
    "n_seeds": n_seeds,
    "source": source,
    "beta": float(beta),
    "speedup_median": median_speedup,
    "speedup_min": float(np.min(speedups)),
    "speedup_max": float(np.max(speedups)),
    "speedup_values": [float(v) for v in speedups],
    "al_evals_to_target": al_evals,
    "random_evals_to_target": rd_evals,
    "al_best_cost_median": float(np.median(al_best)),
    "random_best_cost_median": float(np.median(rd_best)),
    "passes_30pct": bool(median_speedup >= 1.30),
    "note": "speedup=随机评估次数/AL 评估次数；未达标按预算截尾（对 AL 保守）",
  }
