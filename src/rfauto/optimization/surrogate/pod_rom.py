"""POD-ROM 降阶代理（E3：经典 EM 代理标准件，纯 numpy）。

设计（同 base.SurrogateModel 契约，与 poly_ridge / smt_kriging 同接口）：

- **场/曲线指标**（值是定长序列，如 `s11_curve_db`）：把训练样本堆成
 `(n_samples, n_field)` 矩阵 → 去均值 → SVD 得 POD 基（左奇异向量系数
 `U·S`、右奇异向量基 `Vᵀ`）→ 参数（多项式特征）→ POD 系数岭回归。
 `predict_field` 由“预测系数 @ 基 + 均值”重构整条场/曲线；拟合信息里给出
 重构误差与各键保留模态数。
- **标量指标**（值是数值，如 `s11_db_max_in_band`）：视为退化的 1 点场
 （mean=0、单一模 [1]、系数=样本值），参数→系数回归与 poly_ridge 使用
 同一闭式岭解——保证在只有标量指标的锚数据集上口径一致、ρ 可比
 （见 e3-surrogate 锚 A/B 测试）。
- 纯 numpy、无随机、无网络；同参数同输出（C4 可复现红线）。

config：
  bounds: {param: (low, high)}（必填，参数归一化基准）
  order: 1|2（多项式阶，默认 2；样本不足时自动降一阶，规则同 poly_ridge）
  ridge_lambda: 岭正则（默认 0.1，偏置不惩罚）
  metrics: 显式标量指标键列表（缺省 = 样本里全部数值键）
  field_metrics: 显式场/曲线指标键列表（缺省 = 自动探测序列值键）
  n_modes: 保留 POD 模态数（缺省 = 全部非零奇异值模态）
  energy: 累积能量阈值 (0,1]，按能量选模态（与 n_modes 二选一）
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import SurrogateModel, surrogate_registry
from rfauto.optimization.surrogate.poly_ridge import _features

__all__ = ["PODROMSurrogate", "pod_basis"]


def _as_finite_vector(value: Any) -> np.ndarray | None:
  """序列 → 一维有限浮点数组；非序列 / 含非有限值返回 None。"""
  if not isinstance(value, (list, tuple, np.ndarray)):
    return None
  try:
    arr = np.asarray(value, dtype=float).ravel()
  except (TypeError, ValueError):
    return None
  if arr.size == 0 or not np.all(np.isfinite(arr)):
    return None
  return arr


def pod_basis(
  matrix: Any,
  n_modes: int | None = None,
  energy: float | None = None,
  rel_tol: float = 1e-12,
) -> dict[str, Any]:
  """对 (n_samples, n_field) 矩阵做去均值 POD（SVD）。

  返回 dict：mean / modes (L,r) / coeffs (n,r) / singular_values /
  explained_variance / n_modes / rank / reconstruction /
  reconstruction_rmse。模态按奇异值降序，满模态重构误差为机器精度量级。
  """
  F = np.asarray(matrix, dtype=float)
  if F.ndim != 2:
    raise ValueError("pod_basis 需要二维 (n_samples, n_field) 矩阵")
  n, n_field = F.shape
  if n == 0 or n_field == 0:
    raise ValueError("pod_basis 需要非空矩阵")
  if not np.all(np.isfinite(F)):
    raise ValueError("pod_basis 输入含非有限值")
  if n_modes is not None and int(n_modes) < 1:
    raise ValueError("n_modes 必须 >= 1")
  if energy is not None and not 0.0 < float(energy) <= 1.0:
    raise ValueError("energy 必须落在 (0, 1]")

  mean = F.mean(axis=0)
  centered = F - mean
  u, singular, vt = np.linalg.svd(centered, full_matrices=False)
  s0 = float(singular[0]) if singular.size else 0.0
  rank = int(np.sum(singular > s0 * rel_tol)) if s0 > 0.0 else 0
  total = float(np.sum(singular[:rank] ** 2))

  if n_modes is not None:
    r = min(int(n_modes), rank)
  elif energy is not None and rank > 0:
    cumulative = np.cumsum(singular[:rank] ** 2) / total
    r = int(np.searchsorted(cumulative, float(energy) - 1e-12)) + 1
    r = min(r, rank)
  else:
    r = rank

  modes = vt[:r].T.copy()
  coeffs = (u[:, :r] * singular[:r]).reshape(n, r)
  reconstruction = mean + coeffs @ modes.T
  return {
    "mean": mean,
    "modes": modes,
    "coeffs": coeffs,
    "singular_values": singular[:r].copy(),
    "all_singular_values": singular.copy(),
    "explained_variance": (singular[:r] ** 2 / total) if total > 0 else np.zeros(r),
    "n_modes": r,
    "rank": rank,
    "n_samples": n,
    "n_field": n_field,
    "reconstruction": reconstruction,
    "reconstruction_rmse": float(np.sqrt(np.mean((F - reconstruction) ** 2))),
  }


@surrogate_registry.register("pod_rom")
class PODROMSurrogate(SurrogateModel):
  """POD-ROM 降阶代理（场/曲线走真 POD，标量走退化 1 点场）。

  与 poly_ridge / smt_kriging 同接口：fit / predict / metric_keys /
  uncertainty / fitted。额外提供 predict_field 重构整条场/曲线。
  """

  KIND = "pod_rom"

  def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
      raise ValueError("POD-ROM 拟合需要非空 samples")
    cfg = self.config
    if "bounds" not in cfg:
      raise ValueError("POD-ROM 需要 config['bounds']（参数归一化基准）")
    self.bounds = {k: (float(v[0]), float(v[1])) for k, v in cfg["bounds"].items()}
    self.names = sorted(self.bounds)
    self.order = int(cfg.get("order", 2))
    self.ridge_lambda = float(cfg.get("ridge_lambda", 0.1))
    self.n_modes_cfg = None if cfg.get("n_modes") is None else int(cfg["n_modes"])
    self.energy = None if cfg.get("energy") is None else float(cfg["energy"])
    if self.n_modes_cfg is not None and self.n_modes_cfg < 1:
      raise ValueError("n_modes 必须 >= 1")
    if self.energy is not None and not 0.0 < self.energy <= 1.0:
      raise ValueError("energy 必须落在 (0, 1]")

    # 有效阶数：与 poly_ridge 同规则（2 阶特征数 > n-1 时降一阶防奇异）
    n_feat_2 = 1 + 2 * len(self.names) + len(
      list(combinations(range(len(self.names)), 2)))
    order = self.order
    if order >= 2 and len(samples) < n_feat_2 + 1:
      order = 1
    self.effective_order = order
    x_all = np.array([
      _features(self._unit(s["params"]), self.names, order) for s in samples
    ])

    explicit_fields = set(cfg.get("field_metrics") or [])
    detected = self._detect_field_keys(samples)
    requested_fields = list(dict.fromkeys(cfg["field_metrics"])) if (
      cfg.get("field_metrics") is not None) else sorted(detected)
    if cfg.get("metrics") is not None:
      self.metric_keys = [k for k in dict.fromkeys(cfg["metrics"])
                if k not in requested_fields]
    else:
      self.metric_keys = sorted(self._numeric_metrics(samples)
                   - set(requested_fields))

    self.models: dict[str, dict[str, Any]] = {}
    self.field_models: dict[str, dict[str, Any]] = {}
    self.field_keys: list[str] = []
    self.reconstruction_rmse: dict[str, float] = {}
    self.explained_variance: dict[str, float] = {}
    self.n_modes_used: dict[str, int] = {}
    skipped_metrics: list[str] = []
    skipped_fields: list[str] = []

    for key in self.metric_keys:
      y = np.array([float(s["metrics"].get(key, np.nan)) for s in samples])
      mask = np.isfinite(y)
      if mask.sum() < 3: # 与 poly_ridge 同约定：键缺失/全 NaN 不硬拟
        skipped_metrics.append(key)
        continue
      self._fit_scalar(key, x_all[mask], y[mask])
    self.metric_keys = [k for k in self.metric_keys
              if k in self.models]

    for key in requested_fields:
      F, idx = self._field_matrix(samples, key, explicit=key in explicit_fields)
      if F is None:
        if key in explicit_fields:
          raise ValueError(
            f"field_metrics 的 {key!r} 在样本里缺失/非有限/长度不一致")
        skipped_fields.append(key)
        continue
      self.field_keys.append(key)
      self._fit_field(key, x_all[idx], F)

    info = self._mark_fitted(len(samples))
    info.update({
      "order": self.effective_order,
      "metric_keys": list(self.metric_keys),
      "field_keys": list(self.field_keys),
      "n_modes": dict(self.n_modes_used),
      "reconstruction_rmse": dict(self.reconstruction_rmse),
      "explained_variance": dict(self.explained_variance),
      "skipped_metrics": skipped_metrics,
      "skipped_fields": skipped_fields,
    })
    return info

  # ---- 拟合内部 -------------------------------------------------
  def _fit_scalar(self, key: str, x: np.ndarray, y: np.ndarray) -> None:
    """标量指标 = 退化 1 点场（mean=0、单模 [1]），回归即 poly_ridge 闭式解。"""
    beta, xtx_inv, resid_var = self._ridge(x, y.reshape(-1, 1))
    self.models[key] = {
      "mean": 0.0, "modes": np.ones((1, 1)), "beta": beta,
      "xtx_inv": xtx_inv, "resid_var": resid_var,
    }
    self.reconstruction_rmse[key] = 0.0
    self.explained_variance[key] = 1.0
    self.n_modes_used[key] = 1

  def _fit_field(self, key: str, x: np.ndarray, field: np.ndarray) -> None:
    basis = pod_basis(field, n_modes=self.n_modes_cfg, energy=self.energy)
    beta, xtx_inv, resid_var = self._ridge(x, np.asarray(basis["coeffs"]))
    self.field_models[key] = {
      "mean": basis["mean"], "modes": basis["modes"], "beta": beta,
      "xtx_inv": xtx_inv, "resid_var": resid_var,
    }
    self.reconstruction_rmse[key] = float(basis["reconstruction_rmse"])
    ev = basis["explained_variance"]
    self.explained_variance[key] = float(np.sum(ev)) if ev.size else 0.0
    self.n_modes_used[key] = int(basis["n_modes"])

  def _ridge(self, x: np.ndarray, y: np.ndarray
        ) -> tuple[np.ndarray, np.ndarray, float]:
    """岭回归闭式解（偏置不惩罚）+ 系数协方差因子 + 残差方差。"""
    n_feat = x.shape[1]
    penalty = np.eye(n_feat) * self.ridge_lambda
    penalty[0, 0] = 0.0
    xtx = x.T @ x + penalty
    try:
      beta = np.linalg.solve(xtx, x.T @ y)
      xtx_inv = np.linalg.solve(xtx, np.eye(n_feat))
    except np.linalg.LinAlgError:
      beta = np.linalg.pinv(xtx) @ (x.T @ y)
      xtx_inv = np.linalg.pinv(xtx)
    resid = y - x @ beta
    dof = max(x.shape[0] - n_feat, 1)
    return beta, xtx_inv, float(np.sum(resid ** 2) / dof)

  def _field_matrix(self, samples: list[dict[str, Any]], key: str,
           explicit: bool) -> tuple[np.ndarray | None, list[int]]:
    rows: list[np.ndarray] = []
    idx: list[int] = []
    length: int | None = None
    for i, s in enumerate(samples):
      arr = _as_finite_vector(s.get("metrics", {}).get(key))
      if arr is None:
        if explicit:
          raise ValueError(
            f"field_metrics 的 {key!r} 在样本 {i} 缺失/非有限向量")
        continue
      if length is None:
        length = int(arr.size)
      elif arr.size != length:
        if explicit:
          raise ValueError(f"field_metrics 的 {key!r} 各样本长度不一致")
        return None, []
      rows.append(arr)
      idx.append(i)
    if not rows:
      return None, []
    return np.vstack(rows), idx

  # ---- 接口 -----------------------------------------------------
  def _unit(self, params: dict[str, float]) -> dict[str, float]:
    unit = {}
    for n in self.names:
      lo, hi = self.bounds[n]
      span = max(hi - lo, 1e-12)
      unit[n] = float(np.clip((float(params.get(n, lo)) - lo) / span,
                  0.0, 1.0))
    return unit

  def _feature_row(self, params: dict[str, float]) -> np.ndarray:
    return np.array(_features(self._unit(params), self.names,
                 self.effective_order))

  def _check_fitted(self) -> None:
    if not self.fitted:
      raise RuntimeError("代理未拟合，先调用 fit()")

  def predict(self, params: dict[str, float]) -> dict[str, float]:
    """预测标量指标（key 同 fit 样本；不含场/曲线键）。"""
    self._check_fitted()
    x = self._feature_row(params)
    return {key: float(((x @ m["beta"]) @ m["modes"].T + m["mean"])[0])
        for key, m in self.models.items()}

  def predict_field(self, key: str, params: dict[str, float]) -> dict[str, Any]:
    """重构整条场/曲线（POD 基线性组合）——场内键不参与 predict。"""
    self._check_fitted()
    if key not in self.field_models:
      raise KeyError(f"未建模的场/曲线键: {key}，可用: {sorted(self.field_models)}")
    x = self._feature_row(params)
    model = self.field_models[key]
    values = (x @ model["beta"]) @ model["modes"].T + model["mean"]
    return {"metric": key, "values": values.tolist()}

  def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
    """岭回归后验方差 sqrt(xᵀ(XᵀX+λI)⁻¹x · σ²)（逐标量指标）。"""
    self._check_fitted()
    x = self._feature_row(params)
    out = {}
    for key, m in self.models.items():
      var = float(x @ m["xtx_inv"] @ x) * m["resid_var"]
      out[key] = float(np.sqrt(max(var, 0.0)))
    return out

  # ---- 工具 -----------------------------------------------------
  def _detect_field_keys(self, samples: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for s in samples:
      for k, v in s.get("metrics", {}).items():
        if _as_finite_vector(v) is not None:
          keys.add(k)
    return keys

  def _numeric_metrics(self, samples: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for s in samples:
      keys |= {k for k, v in s.get("metrics", {}).items()
           if isinstance(v, (int, float))}
    return keys
