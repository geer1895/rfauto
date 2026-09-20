"""多项式岭回归代理（v1 默认校准代理）。

设计取舍：
- 小样本友好：Taguchi 9 点 + 3 维参数下，2 阶特征 10 个系数用岭回归闭式解
  稳定；λ 可配（默认 0.1，标准化特征尺度）。
- 纯 numpy 闭式解，零新增依赖（GP→sklearn、NN→torch 都是 v2 的可选项）。
- 参数按 bounds 归一化到 [0,1]（外推有界）；特征 = [1, xi, xi², xi·xj]。
- gate 验收配套 loocv_rho：留一交叉验证的预测 cost 与实际 cost 的
  Spearman ρ（P0 gate 口径）。
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import combinations
from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)


def _features(unit: dict[str, float], names: list[str],
              order: int) -> list[float]:
    """标准化参数 → 特征向量（含偏置；order=2 加平方项与交叉项）。"""
    x = [unit[n] for n in names]
    feats = [1.0, *x]
    if order >= 2:
        feats += [xi * xi for xi in x]
        feats += [x[i] * x[j] for i, j in combinations(range(len(x)), 2)]
    return feats


class PolyRidgeSurrogate(SurrogateModel):
    """逐指标多项式岭回归代理（params→metrics 字典契约，见 base）。

    config:
        bounds: {param: (low, high)}（必填，归一化基准）
        order: 1|2（默认 2）
        ridge_lambda: 默认 0.1
        metrics: 要建模的指标键列表（缺省 = fit 样本里全部数值键的并集）
    """

    KIND = "poly_ridge"

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        cfg = self.config
        self.bounds: dict[str, tuple[float, float]] = {
            k: tuple(v) for k, v in cfg["bounds"].items()}
        self.names: list[str] = sorted(self.bounds)
        self.order: int = int(cfg.get("order", 2))
        lam = float(cfg.get("ridge_lambda", 0.1))
        metric_keys = cfg.get("metrics") or self._numeric_metrics(samples)
        self.metric_keys: list[str] = sorted(metric_keys)

        # 折内样本数可能少于高阶特征数（LOOCV 每折留 1）：
        # 特征数 > n_samples-1 时自动降为一阶（主效应优先，防奇异）
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
        # 岭回归闭式解：(XᵀX + λ·diag(1))⁻¹Xᵀy（偏置不惩罚）；
        # λ=0 且仍奇异（极端共线）时退 pinv 最小范数解
        penalty = np.eye(n_feat) * lam
        penalty[0, 0] = 0.0
        self.models: dict[str, np.ndarray] = {}
        for key in self.metric_keys:
            y = np.array([float(s["metrics"].get(key, np.nan)) for s in samples])
            mask = np.isfinite(y)
            if mask.sum() < 3:
                continue  # 键在样本里不存在/全 NaN（如键名错配）——跳过不硬拟
            xtx = X[mask].T @ X[mask] + penalty
            xty = X[mask].T @ y[mask]
            try:
                self.models[key] = np.linalg.solve(xtx, xty)
            except np.linalg.LinAlgError:
                self.models[key] = np.linalg.pinv(xtx) @ xty
        return self._mark_fitted(len(samples))

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

    def _numeric_metrics(self, samples: list[dict[str, Any]]) -> set[str]:
        keys: set[str] = set()
        for s in samples:
            keys |= {k for k, v in s.get("metrics", {}).items()
                     if isinstance(v, (int, float))}
        return keys


def loocv_rho(
    samples: list[dict[str, Any]],
    cost_fn: Callable[[dict[str, Any]], float],
    surrogate_factory: Callable[[], SurrogateModel],
) -> dict[str, Any]:
    """留一交叉验证：每折留出 1 个样本做预测，其余拟合。

    返回预测 cost 与实际 cost 的 Spearman ρ（P0 gate 口径 ≥0.8）。
    样本数 <4 时结果不稳定，直接返回 ok=False。
    """
    n = len(samples)
    if n < 4:
        return {"ok": False, "error": f"样本数 {n} < 4，LOOCV 无意义"}
    predicted: list[float] = []
    actual: list[float] = []
    skipped = 0
    for i in range(n):
        hold = samples[i]
        rest = [s for j, s in enumerate(samples) if j != i]
        model = surrogate_factory()
        model.fit(rest)
        try:
            pred = model.predict(hold["params"])
        except Exception:
            skipped += 1
            continue
        # 预测 cost：用折内模型预测的指标交给 cost_fn（同 objectives 口径）
        try:
            predicted.append(float(cost_fn({"metrics": pred})))
            actual.append(float(cost_fn(hold)))
        except Exception:
            skipped += 1
    if len(predicted) < 3:
        return {"ok": False, "error": f"有效折数 {len(predicted)} < 3",
                "skipped": skipped}
    rho = _spearman(predicted, actual)
    return {"ok": True, "rho": rho, "n_folds": len(predicted),
            "skipped": skipped}


def _spearman(a: list[float], b: list[float]) -> float:
    """Spearman ρ（秩相关；并列秩取平均）。"""
    def ranks(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        rk = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk

    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = math_sqrt(sum((ra[i] - ma) ** 2 for i in range(n)))
    db = math_sqrt(sum((rb[i] - mb) ** 2 for i in range(n)))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def math_sqrt(x: float) -> float:
    return x ** 0.5


# 默认注册（第三方代理按 base 模块 docstring 的方式自行注册）
surrogate_registry.register("poly_ridge")(PolyRidgeSurrogate)
