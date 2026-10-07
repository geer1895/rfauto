"""OP-12：Huber 鲁棒岭回归代理档（round16:213，P3/S）。

动机：真机/采集样本里混有离群 trial（仿真未收敛、判读坏点），poly_ridge
的平方损失被单点 gross outlier 拖偏；Huber 损失在 |r|≤δ 段二次、以外线性，
对小残差保 OLS 效率、对大残差只线性惩罚（鲁棒档）。

文献出处（2026-10-03 web 多源核对，非凭记忆复写）：
- Huber, P. J. (1964), "Robust Estimation of a Location Parameter",
  Ann. Math. Statist. 35(1):73–101——Huber 损失原始定义；
- 调优常数 k=1.345：正态误差下 95% 渐近相对效率（Huber 提出，R MASS::rlm
  缺省同值；MDPI Mathematics 14(7):1138、Wang et al. 2021 JSTOR 等多源确认）；
- MAD 尺度：σ̂ = MAD/0.6745（0.6745=Φ⁻¹(3/4)，稳健统计标准归一）。

实现：IRLS（迭代重加权最小二乘）——Huber 损失 M 估计的等价不动点迭代，
每步为加权岭回归闭式解（纯 numpy 零新依赖，同 poly_ridge 家族约定）：
    w_i = 1                       (|r_i| ≤ δ)
    w_i = δ/|r_i|                 (|r_i| > δ)
    coef = (Xᵀ W X + λP)⁻¹ Xᵀ W y
迭代固定上限+系数收敛容差，全程确定性（同输入同输出，C4 红线）。

双基准自证（tests/unit/test_huber_ridge_surrogate.py）：
1. 闭式极限：无离群且 δ→∞ 时 Huber→平方损失，解 ≍ poly_ridge 岭回归闭式；
2. 鲁棒性（文献已知性质）：含 gross outlier 时 Huber 系数误差 ≪ OLS。
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)
from rfauto.optimization.surrogate.poly_ridge import _features

__all__ = ["HuberRidgeSurrogate"]

_MAD_TO_SIGMA = 0.6745  # Φ⁻¹(3/4)：MAD→σ 的标准归一常数（见模块 docstring）


def _robust_scale(residuals: np.ndarray) -> float:
    """MAD 稳健尺度 σ̂ = median|r−median(r)|/0.6745（退化兜底 1e-12）。"""
    med = float(np.median(residuals))
    mad = float(np.median(np.abs(residuals - med)))
    sigma = mad / _MAD_TO_SIGMA
    return sigma if sigma > 1e-12 else 1e-12


@surrogate_registry.register("huber_ridge")
class HuberRidgeSurrogate(SurrogateModel):
    """逐指标 Huber 鲁棒岭回归代理（params→metrics 契约同 poly_ridge/base）。

    config:
        bounds: {param: (low, high)}（必填，归一化基准，同 poly_ridge）
        order: 1|2（默认 2；样本不足自动降 1，同 poly_ridge 语义）
        ridge_lambda: 默认 0.1（偏置不惩罚）
        delta: Huber 阈值；缺省 "auto" = 1.345·σ̂(MAD)（95% 效率口径）
        max_iter: IRLS 上限（默认 50）
        tol: 系数收敛容差（默认 1e-10，‖Δcoef‖∞）
        metrics: 要建模的指标键列表（缺省 = fit 样本全部数值键并集）
    """

    KIND = "huber_ridge"

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        cfg = self.config
        self.bounds: dict[str, tuple[float, float]] = {
            k: tuple(v) for k, v in cfg["bounds"].items()}
        self.names: list[str] = sorted(self.bounds)
        self.order: int = int(cfg.get("order", 2))
        lam = float(cfg.get("ridge_lambda", 0.1))
        self.max_iter = int(cfg.get("max_iter", 50))
        self.tol = float(cfg.get("tol", 1e-10))
        self.delta_cfg = cfg.get("delta", "auto")
        metric_keys = cfg.get("metrics")
        if not metric_keys:
            keys: set[str] = set()
            for s in samples:
                keys |= {k for k, v in s.get("metrics", {}).items()
                         if isinstance(v, (int, float))}
            metric_keys = keys
        self.metric_keys: list[str] = sorted(metric_keys)

        # 小样本高阶特征防奇异：同 poly_ridge 折内降阶语义
        n_feat_2 = 1 + 2 * len(self.names) + len(
            list(combinations(range(len(self.names)), 2)))
        order = self.order
        if order >= 2 and len(samples) < n_feat_2 + 1:
            order = 1
        self.effective_order = order

        X = np.array([
            _features(self._unit(s["params"]), self.names, order)
            for s in samples
        ])
        n_feat = X.shape[1]
        penalty = np.eye(n_feat) * lam
        penalty[0, 0] = 0.0  # 偏置不惩罚（同 poly_ridge）

        self.models: dict[str, np.ndarray] = {}
        self.fit_info: dict[str, dict[str, Any]] = {}
        for key in self.metric_keys:
            y = np.array([float(s["metrics"].get(key, np.nan)) for s in samples])
            mask = np.isfinite(y)
            if mask.sum() < 3:
                continue  # 键缺失/全 NaN：跳过不硬拟（同 poly_ridge）
            Xk, yk = X[mask], y[mask]
            coef, info = self._irls(Xk, yk, penalty)
            self.models[key] = coef
            self.fit_info[key] = info
        return self._mark_fitted(len(samples))

    def _irls(
        self, X: np.ndarray, y: np.ndarray, penalty: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Huber M 估计的 IRLS 不动点迭代（确定性：固定上限+收敛容差）。"""
        n = X.shape[0]
        # 起步 = 平方损失岭闭式解（δ=auto 需先有残差才能估稳健尺度）
        try:
            coef = np.linalg.solve(X.T @ X + penalty, X.T @ y)
        except np.linalg.LinAlgError:
            coef = np.linalg.pinv(X.T @ X + penalty) @ X.T @ y
        delta = self.delta_cfg
        auto = not isinstance(delta, (int, float))
        n_iter = 0
        converged = False
        for it in range(1, self.max_iter + 1):
            r = y - X @ coef
            scale = _robust_scale(r)
            d = (1.345 * scale) if auto else float(delta)
            w = np.ones(n)
            big = np.abs(r) > d
            w[big] = d / np.maximum(np.abs(r[big]), 1e-300)
            sw = np.sqrt(w)
            xtwx = (X * sw[:, None]).T @ (X * sw[:, None]) + penalty
            xtwy = (X * sw[:, None]).T @ (sw * y)
            try:
                new_coef = np.linalg.solve(xtwx, xtwy)
            except np.linalg.LinAlgError:
                new_coef = np.linalg.pinv(xtwx) @ xtwy
            n_iter = it
            if float(np.max(np.abs(new_coef - coef))) < self.tol:
                coef = new_coef
                converged = True
                break
            coef = new_coef
        info = {"delta": (1.345 * _robust_scale(y - X @ coef)) if auto
                else float(self.delta_cfg),
                "n_iter": n_iter, "converged": converged}
        return coef, info

    def _unit(self, params: dict[str, float]) -> dict[str, float]:
        unit = {}
        for n in self.names:
            lo, hi = self.bounds[n]
            span = max(hi - lo, 1e-12)
            unit[n] = float(np.clip((float(params.get(n, lo)) - lo) / span, 0.0, 1.0))
        return unit

    def predict(self, params: dict[str, float]) -> dict[str, float]:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")
        feats = np.array(
            _features(self._unit(params), self.names,
                      getattr(self, "effective_order", self.order)))
        return {key: float(feats @ coef) for key, coef in self.models.items()}
