"""MAPES 解析像素代理——E3 surrogate_registry 的"解析代理档"（A8 stage-3）。

定位（A8 stage-3 / 方案"MAPES 是潜在的第二档加速层"）：
- 包装 :class:`rfauto.core.mapes.MapesModel`（Z_ALL 分块 + Schur 补闭式，
 确定性内核，铁律 7 兼容）——**零训练**：fit 不学习，只做装配校验与契约
 记账（解析代理语义，区别于 poly_ridge 等数据驱动档）。
- 保真档位（stage-3 对照实测存档，全波=基准，
 预声明筛选档门 G1/G2/G3，raw 消费口径 PASS；sym 口径 G1 2.016dB 未达）：
 s11_db_min 逐案 |Δ| ≤ 1.997dB（7 案 worst=checker）、|S21|@fc 线性
 |Δ| ≤ 8e-5、排序 Spearman ρ = 1.0。矩阵级 max|ΔS| ≈ 0.43 受 stage-2
 FDTD 残模伪影主导（S22 对角、图案无关）——**只作粗筛/虚拟寻优档，
 精算永远走真机通道**（base 契约原话）。

连续参数兼容（WP3.2 环 Optuna [0,1] 连续建议）：
- occ/via 参数按 ≥0.5 判 1（缺席=开路），缺键补 0——闭式代理与真跑
 evaluate_fn 消费同一 snapping 规则，环内语义一致；
- topology_key 在 params 中出现且与布局不符时显式报错（stage-1 语义）。

注册即生效（基类+注册表模式，规则 3）：``surrogate_registry.create(
"mapes_pixel_analytic", config={...})``；纯增量键，既有 kind 消费面
（surrogate_loop/trust_region/calibration_service）不受影响。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.errors import ConfigError
from rfauto.core.mapes import MapesModel, PixelLayout
from rfauto.optimization.surrogate.base import (
  SurrogateModel,
  surrogate_registry,
)

__all__ = ["MapesAnalyticSurrogate"]


@surrogate_registry.register("mapes_pixel_analytic")
class MapesAnalyticSurrogate(SurrogateModel):
  """MAPES 闭式像素代理（解析档；config 见 :meth:`_build`）。

  config:
    z_all_npz: Z_ALL 数据路径（npz，含 ``freq_hz``/``z_all``；必填）。
    layout: 像素布局 dict（n_rows/n_cols/n_layers/n_io_ports/via_slots；
      缺省 = stage-2 6×6 双 via_ground 拓扑）。
    reference_impedance: 参考阻抗（缺省 50Ω）。
    symmetrize: 消费口径——True 时先取 (Z+Zᵀ)/2。
      缺省 False（stage-3 达标门 PASS 的 raw 口径）。
    alpha: 频率缩放校准因子（stage-4 #190 范式，MapesModel keyword-only；
      缺省 1.0=不缩放；数值来源与是否 HFSS 背书由调用方标注）。
  """

  KIND = "mapes_pixel_analytic"

  def __init__(self, config: dict[str, Any] | None = None) -> None:
    super().__init__(config)
    self._model: MapesModel | None = None

  # ------------------------------------------------------------------ #
  # 装配（懒构造；npz 只读一次）
  # ------------------------------------------------------------------ #
  def _layout(self) -> PixelLayout:
    cfg = self.config.get("layout") or {}
    via_slots = tuple(
      (int(r), int(c), str(kind))
      for r, c, kind in cfg.get("via_slots", ()))
    return PixelLayout(
      n_rows=int(cfg.get("n_rows", 6)),
      n_cols=int(cfg.get("n_cols", 6)),
      n_layers=int(cfg.get("n_layers", 1)),
      n_io_ports=int(cfg.get("n_io_ports", 2)),
      via_slots=via_slots,
    )

  def _build(self) -> MapesModel:
    if self._model is not None:
      return self._model
    cfg = self.config
    raw_path = cfg.get("z_all_npz")
    if not raw_path:
      raise ConfigError("config 缺少 z_all_npz（Z_ALL npz 路径）")
    npz_path = Path(str(raw_path))
    if not npz_path.exists():
      raise ConfigError(f"z_all_npz 不存在：{npz_path}")
    layout = self._layout()
    with np.load(npz_path) as data:
      for key in ("freq_hz", "z_all"):
        if key not in data:
          raise ConfigError(f"z_all_npz 缺少数组 {key!r}：{npz_path}")
      freq_hz = np.asarray(data["freq_hz"], dtype=float)
      z_all = np.asarray(data["z_all"], dtype=complex)
    if bool(cfg.get("symmetrize", False)):
      z_all = 0.5 * (z_all + np.swapaxes(z_all, -1, -2))
    self._model = MapesModel(
      layout, z_all, freq_hz,
      reference_impedance=float(cfg.get("reference_impedance", 50.0)),
      alpha=float(cfg.get("alpha", 1.0)))
    return self._model

  def _snap_params(self, params: dict[str, Any]) -> dict[str, float]:
    """连续/缺键 params → 布局完整 0/1 展平 dict（≥0.5 判 1，确定性）。"""
    model = self._build()
    layout: PixelLayout = model.layout
    given_key = params.get("topology_key")
    if (given_key is not None
        and str(given_key) != layout.topology_key):
      raise ConfigError(
        f"topology_key 不匹配：params={given_key!r}，"
        f"布局={layout.topology_key!r}")

    def bit(value: Any, name: str) -> float:
      try:
        return 1.0 if float(value) >= 0.5 else 0.0
      except (TypeError, ValueError) as exc:
        raise ConfigError(
          f"参数 {name!r} 不可解析为数值：{value!r}") from exc

    snapped: dict[str, float] = {"topology_key": layout.topology_key}
    for r in range(layout.n_rows):
      for c in range(layout.n_cols):
        name = f"occ{r}_{c}"
        snapped[name] = bit(params.get(name, 0.0), name)
    for k in range(len(layout.via_slots)):
      name = f"via{k}"
      snapped[name] = bit(params.get(name, 0.0), name)
    return snapped

  # ------------------------------------------------------------------ #
  # SurrogateModel 契约
  # ------------------------------------------------------------------ #
  def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
    """解析代理不训练：只做装配校验 + 契约记账（缺 metrics 条目忽略）。"""
    self._build()
    n_valid = sum(1 for s in samples if isinstance(s, dict))
    return self._mark_fitted(n_valid)

  def predict(self, params: dict[str, float]) -> dict[str, float]:
    if not self._fitted:
      raise RuntimeError("代理未拟合，先调用 fit()")
    model = self._build()
    return model.predict(self._snap_params(params))

  def uncertainty(self, params: dict[str, float]) -> None:
    """解析闭式无不确定性估计（契约占位，同 MapesModel.uncertainty）。"""
    del params
    return None
