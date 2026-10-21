"""EC-17 SAAS 精神稀疏 ARD 高维先验（确定性 MAP 点估计，无 MCMC）。

池 P3 圈定件（架构批 W5-S22；ecosystem §二 EC-17，条件件"≥15 维战役"
驱动——本档为离线内核+合成基准验证，真机放量等条件触发）。法源：
- SAASBO（Eriksson & Jankowiak, "High-Dimensional Bayesian Optimization
  with Sparse Axis-Aligned Subspaces", UAI 2021；botorch SAASBO）：
  log(ℓ_i) ~ N(0, τ²)（τ²=100）的超稀疏长度尺度先验——τ² 大 ⇒ 绝大多数
  维度被先验压向巨大 ℓ（轴向"关闭"），只有数据强支持的少数维度保留
  小 ℓ（"开启"），天然实现高维 ARD 稀疏化；
- 核：Matérn 5/2 ARD（SAASBO 缺省核）。

确定性降档诚实边界（empirical 档如实标注）：
- SAASBO 原版对 ℓ 做 **NUTS 全贝叶斯后验采样**；本档为 **MAP 点估计**
  （ecosystem 表格原文"确定性 MAP 点估计"）——没有后验分布，稀疏性
  来自先验罚项下的最优解，不是后验中位/样本；维度"活跃"判据是 ℓ 阈值
  （建模选择，非后验概率），消费方按点估计口径消费；
- nugget 固定不参与优化（先验语义集中在长度尺度；见 gp_det.fit_map 注）；
- 零新依赖：底座 optimization.surrogate.gp_det（numpy/scipy）。

注册即生效（基类+注册表模式，规则 3）：``surrogate_registry.create(
"saas_gp", config={...})``；纯增量键，既有 kind 消费面零改动。

合成基准（已知真值回收）：15 维仅 2 维活跃的平滑函数，MAP 后活跃集
回收 + 非活跃维度 ℓ 全部 >> 活跃维度 ℓ；见 tests/unit/test_saas_gp.py。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)
from rfauto.optimization.surrogate.gp_det import DetGaussianProcess, fit_map

__all__ = ["DEFAULT_ACTIVE_THRESHOLD", "DEFAULT_TAU_SQ", "SaasArdSurrogate"]

#: SAAS 先验 log(ℓ) 方差（原论文 τ²=100 口径）
DEFAULT_TAU_SQ = 100.0

#: 活跃维度阈值（单元立方：ℓ < 阈值视为"开启"；建模选择，如实标注）
DEFAULT_ACTIVE_THRESHOLD = 2.0


def _numeric_keys(samples: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for s in samples:
        keys |= {k for k, v in s.get("metrics", {}).items()
                 if isinstance(v, (int, float))}
    return keys


@surrogate_registry.register("saas_gp")
class SaasArdSurrogate(SurrogateModel):
    """SAAS 稀疏 ARD GP（EC-17，opt-in 新键；MAP 点估计档）。

    config:
        bounds: {param: (low, high)}（必填，单元归一化基准）。
        tau_sq: log(ℓ) 先验方差（缺省 100 = SAASBO 口径；调小→更稀疏）。
        log_ell_mean: log(ℓ) 先验均值（缺省 0，SAASBO 口径）。
        active_threshold: 活跃维度 ℓ 阈值（缺省 2.0）。
        metrics: 指标键列表（缺省全部数值键；有效点 <3 跳过，同约定）。

    fit 后透出（合成基准/高维诊断消费面）：
        lengthscales_: {metric: {param: ℓ}} MAP 点估计；
        active_dims_: {metric: [param,...]}（ℓ < active_threshold）。
    """

    KIND = "saas_gp"

    def _unit_row(self, params: dict[str, float]) -> np.ndarray:
        return np.array([
            np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12),
                    0.0, 1.0)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)])

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        self.bounds = {k: tuple(v) for k, v in self.config["bounds"].items()}
        self.names = sorted(self.bounds)
        keys = (self.config.get("metrics")
                or sorted(_numeric_keys(samples)))
        tau_sq = float(self.config.get("tau_sq", DEFAULT_TAU_SQ))
        prior = {"log_ell_mean": float(self.config.get("log_ell_mean", 0.0)),
                 "log_ell_var": tau_sq}
        thr = float(self.config.get("active_threshold",
                                    DEFAULT_ACTIVE_THRESHOLD))
        x = np.array([self._unit_row(s["params"]) for s in samples])
        self.models: dict[str, DetGaussianProcess] = {}
        self.lengthscales_: dict[str, dict[str, float]] = {}
        self.active_dims_: dict[str, list[str]] = {}
        for key in keys:
            y = np.array([float(s["metrics"].get(key, np.nan))
                          for s in samples])
            mask = np.isfinite(y)
            if mask.sum() < 3:
                continue
            params = fit_map(x[mask], y[mask], kind="matern52",
                             prior=prior)
            self.models[key] = DetGaussianProcess(x[mask], y[mask],
                                                  params, "matern52")
            self.lengthscales_[key] = {
                n: float(v) for n, v in zip(self.names, params["ell"],
                                            strict=True)}
            self.active_dims_[key] = [
                n for n, v in self.lengthscales_[key].items() if v < thr]
        return self._mark_fitted(len(samples))

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        self._check_fitted()
        x = self._unit_row(params)[None, :]
        return {key: float(gp.predict(x)[0][0])
                for key, gp in self.models.items()}

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        self._check_fitted()
        x = self._unit_row(params)[None, :]
        return {key: float(np.sqrt(max(gp.predict(x)[1][0], 0.0)))
                for key, gp in self.models.items()}
