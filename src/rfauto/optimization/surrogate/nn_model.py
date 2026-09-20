"""物理先验 NN 代理（v2，纯 numpy 实现——零重依赖，接口对齐 torch 可换后端）。

设计要点（代理校准设计要点 + 法动比赛实战沉淀）：
- 小样本（9~30 点）场景： MLP(24,24) + bagging 集成（bootstrap K 份），
  集成 std 即不确定度（MC-Dropout 的廉价替代）。
- 物理先验 = 特征增广层（PHYSICS_AUGMENTERS 注册表）：原始参数之外补充
  领域特征（如 wilkinson 的线阻抗失配 Γ、λ/4 电长度比），让网络学残差
  而不是从零学物理。默认 polynomial_cross（二阶交叉项），可按模板注册。
- 确定性：全链路固定种子（初始化/bootstrap/训练顺序），同配置同结果。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np

from .base import SurrogateModel, surrogate_registry

# ─── 物理特征增广注册表 ──────────────────────────────────────────────────────
# 签名 fn(params: dict[str, float], bounds: dict[str, tuple]) -> dict[str, float]
# 返回"增广特征名 → 值"（与原始参数合并后进网络）。注册键 = 模板名。


def _polynomial_cross(params: dict[str, float],
                      bounds: dict[str, tuple]) -> dict[str, float]:
    """通用二阶交叉项（无领域知识时的默认增广）。"""
    keys = sorted(params)
    out: dict[str, float] = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            out[f"cross__{a}__{b}"] = float(params[a]) * float(params[b])
    return out


def _wilkinson_rf(params: dict[str, float],
                  bounds: dict[str, tuple]) -> dict[str, float]:
    """wilkinson 物理特征：线阻抗失配 Γ_s/Γ_sh 与臂电长度比（v0 口径复用）。

    全部由 core.synthesis 的物理函数计算（optimization→core 合法依赖），
    网络在物理特征之上学残差，而不是从零拟合谐振行为。
    """
    from rfauto.core.synthesis import Stackup, forward_z0

    series_w = float(params.get("series_w_mm", 0.33))
    shunt_w = float(params.get("shunt_w_mm", 1.10))
    arm_len = float(params.get("arm_len_mm", 20.5))
    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    z0 = 50.0
    zt = z0 * math.sqrt(2)
    z_s, eps_s = forward_z0(series_w, 2.4, stackup)
    z_sh, _ = forward_z0(shunt_w, 2.4, stackup)
    gamma_s = abs((z_s - zt) / (z_s + zt))
    gamma_sh = abs((z_sh - z0) / (z_sh + z0))
    lambda_quarter_mm = 0.25 * 3e8 / 2.4e9 / math.sqrt(eps_s) * 1e3
    return {
        "gamma_series": gamma_s,
        "gamma_shunt": gamma_sh,
        "arm_elec_ratio": arm_len / lambda_quarter_mm,
    }


PHYSICS_AUGMENTERS: dict[str, Callable[[dict[str, float], dict[str, tuple]],
                                       dict[str, float]]] = {
    "polynomial_cross": _polynomial_cross,
    "wilkinson_rf": _wilkinson_rf,
}


# ─── numpy 小型 MLP ──────────────────────────────────────────────────────────

class _MLP:
    """两层全连接（tanh），Adam，L2。仅覆盖小样本回归需要的最小功能面。"""

    def __init__(self, n_in: int, n_out: int, hidden: int, seed: int):
        rng = np.random.default_rng(seed)
        self.w1 = rng.normal(0, math.sqrt(2.0 / n_in), (n_in, hidden))
        self.b1 = np.zeros(hidden)
        self.w2 = rng.normal(0, math.sqrt(2.0 / hidden), (hidden, hidden))
        self.b2 = np.zeros(hidden)
        self.w3 = rng.normal(0, math.sqrt(2.0 / hidden), (hidden, n_out))
        self.b3 = np.zeros(n_out)
        self._params = [self.w1, self.b1, self.w2, self.b2, self.w3, self.b3]
        self._m = [np.zeros_like(p) for p in self._params]
        self._v = [np.zeros_like(p) for p in self._params]
        self._t = 0

    def forward(self, x: np.ndarray) -> np.ndarray:
        h1 = np.tanh(x @ self.w1 + self.b1)
        h2 = np.tanh(h1 @ self.w2 + self.b2)
        return h2 @ self.w3 + self.b3

    def _grads(self, x: np.ndarray, y: np.ndarray, wd: float):
        n = len(x)
        h1 = np.tanh(x @ self.w1 + self.b1)
        h2 = np.tanh(h1 @ self.w2 + self.b2)
        out = h2 @ self.w3 + self.b3
        d_out = 2.0 * (out - y) / n
        g = [None] * 6
        g[5] = d_out.sum(0)
        g[4] = h2.T @ d_out + wd * self.w3
        d_h2 = (d_out @ self.w3.T) * (1 - h2 ** 2)
        g[3] = d_h2.sum(0)
        g[2] = h1.T @ d_h2 + wd * self.w2
        d_h1 = (d_h2 @ self.w2.T) * (1 - h1 ** 2)
        g[1] = d_h1.sum(0)
        g[0] = x.T @ d_h1 + wd * self.w1
        return g

    def adam_step(self, x, y, wd, lr, betas=(0.9, 0.999), eps=1e-8):
        g = self._grads(x, y, wd)
        self._t += 1
        for p, gi, mi, vi in zip(self._params, g, self._m, self._v, strict=False):
            mi *= betas[0]
            mi += (1 - betas[0]) * gi
            vi *= betas[1]
            vi += (1 - betas[1]) * gi * gi
            m_hat = mi / (1 - betas[0] ** self._t)
            v_hat = vi / (1 - betas[1] ** self._t)
            p -= lr * m_hat / (np.sqrt(v_hat) + eps)


@surrogate_registry.register("nn")
class NNSurrogate(SurrogateModel):
    """物理特征增广 + bagging 集成的小样本 NN 代理（numpy 后端）。"""

    KIND = "nn"

    def __init__(self, config: dict[str, Any]):
        self.config = dict(config)
        self.bounds = {k: (float(v[0]), float(v[1]))
                       for k, v in (config.get("bounds") or {}).items()}
        self.hidden = int(config.get("hidden", 24))
        # 默认值来自 run2 真采样超参扫（LOOCV ρ 最优组合）：
        # epochs=4000 / wd=1e-3 / n_ensemble=3；增广器在 n=9 上
        # polynomial_cross(ρ=0.52) 与 wilkinson_rf(ρ=0.47) 同档——
        # 默认保 wilkinson_rf（物理先验语义），追平性能靠样本量。
        self.epochs = int(config.get("epochs", 4000))
        self.lr = float(config.get("lr", 5e-3))
        self.wd = float(config.get("weight_decay", 1e-3))
        self.n_ensemble = int(config.get("n_ensemble", 3))
        self.seed = int(config.get("seed", 42))
        augmenter = str(config.get("augmenter", "wilkinson_rf"))
        self.augmenter_name = augmenter
        self.augmenter = PHYSICS_AUGMENTERS.get(
            augmenter, _polynomial_cross)
        self._models: list[_MLP] = []
        self._xs: np.ndarray | None = None
        self._ys: np.ndarray | None = None
        self.metric_keys: list[str] = []

    # ── 特征化 ──
    def _feature_names(self, sample_params: dict[str, float]) -> list[str]:
        base = sorted(self.bounds.keys() | sample_params.keys())
        aug = sorted(self.augmenter(
            {k: float(sample_params.get(k, np.mean(self.bounds.get(k, (0, 0)))))
             for k in base}, self.bounds))
        return base + aug

    def _vectorize(self, params: dict[str, float],
                   names: list[str]) -> np.ndarray:
        full = dict(params)
        for k in self.bounds:
            full.setdefault(k, sum(self.bounds[k]) / 2.0)
        aug = self.augmenter({k: float(full.get(k, 0.0)) for k in sorted(full)},
                             self.bounds)
        full |= aug
        return np.array([float(full.get(k, 0.0)) for k in names])

    # ── SurrogateModel 契约 ──
    def fit(self, samples: list[dict[str, Any]]) -> None:
        if not samples:
            raise ValueError("NNSurrogate.fit：无样本")
        names = self._feature_names(samples[0]["params"])
        x = np.vstack([self._vectorize(s["params"], names) for s in samples])
        keys = sorted({k for s in samples
                       for k, v in s["metrics"].items()
                       if isinstance(v, (int, float))})
        y = np.array([[float(s["metrics"].get(k, np.nan)) for k in keys]
                      for s in samples])
        ok = ~np.isnan(y).any(axis=1)
        x, y = x[ok], y[ok]
        self.metric_keys = keys
        self._x_names = names
        self._x_mean, self._x_std = x.mean(0), x.std(0) + 1e-12
        self._y_mean, self._y_std = y.mean(0), y.std(0) + 1e-12
        self._xs = (x - self._x_mean) / self._x_std
        self._ys = (y - self._y_mean) / self._y_std
        n = len(x)
        self._models = []
        for k in range(self.n_ensemble):
            rng = np.random.default_rng(self.seed + k)
            idx = rng.integers(0, n, n)  # bootstrap
            net = _MLP(len(names), len(keys), self.hidden, self.seed + 1000 + k)
            for _ in range(self.epochs):
                net.adam_step(self._xs[idx], self._ys[idx], self.wd, self.lr)
            self._models.append(net)
        return self._mark_fitted(n)

    def predict(self, params: dict[str, float]) -> dict[str, float]:
        if not self._models:
            raise RuntimeError("NNSurrogate.predict：先 fit")
        x = self._vectorize(params, self._x_names)
        x = (x - self._x_mean) / self._x_std
        outs = np.vstack([m.forward(x[None, :])[0] for m in self._models])
        mean = outs.mean(0) * self._y_std + self._y_mean
        return {k: float(v) for k, v in zip(self.metric_keys, mean, strict=False)}

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        if not self._models:
            raise RuntimeError("NNSurrogate.uncertainty：先 fit")
        x = self._vectorize(params, self._x_names)
        x = (x - self._x_mean) / self._x_std
        outs = np.vstack([m.forward(x[None, :])[0] for m in self._models])
        std = outs.std(0) * self._y_std
        return {k: float(v) for k, v in zip(self.metric_keys, std, strict=False)}
