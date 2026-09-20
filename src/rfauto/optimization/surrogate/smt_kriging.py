"""SMT 2.x Kriging 代理（阶段 1.2：成熟开源库接入，不自研重造）。

SMT（ONERA）KRG 高斯过程：单元归一化输入，逐指标独立训练；predict 返回
各指标预测，uncertainty 返回 KRG 自带方差 σ（6.1/6.2/6.5 的接入基础）。
依赖为可选 extra（smt）：未安装时 fit/predict 抛 RuntimeError（显式报错，
不走静默降级），不污染核心零重依赖现状。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import SurrogateModel, surrogate_registry


def _numeric_keys(samples: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for s in samples:
        keys |= {k for k, v in s.get("metrics", {}).items()
                 if isinstance(v, (int, float))}
    return keys


@surrogate_registry.register("smt_kriging")
class SMTKrigingSurrogate(SurrogateModel):
    """高斯过程代理（SMT KRG，逐指标独立训练）。

    config:
        bounds: {param: (low, high)}（必填，单元归一化基准）
        theta0: KRG 初始长度尺度（默认 1e-2）
        metrics: 要建模的指标键列表（缺省 = fit 样本里全部数值键的并集）
    """

    KIND = "smt_kriging"

    def _ensure_smt(self):
        try:
            from smt.surrogate_models import KRG
            return KRG
        except ImportError as exc:  # 可选依赖缺失：显式报错
            raise RuntimeError(
                "smt_kriging 需要 SMT 2.x：pip install rfauto[smt] 或 "
                "pip install smt") from exc

    def _unit_row(self, params: dict[str, float]) -> np.ndarray:
        return np.array([
            np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12),
                    0.0, 1.0)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)])

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        KRG = self._ensure_smt()
        cfg = self.config
        self.bounds = {k: tuple(v) for k, v in cfg["bounds"].items()}
        self.names = sorted(self.bounds)
        theta0 = float(cfg.get("theta0", 1e-2))
        keys = cfg.get("metrics") or _numeric_keys(samples)
        self.metric_keys = sorted(keys)

        X = np.array([self._unit_row(s["params"]) for s in samples])
        theta0 = [theta0] * len(self.names)  # SMT theta0 按维数给数组
        self.models: dict[str, Any] = {}
        for key in self.metric_keys:
            y = np.array([float(s["metrics"].get(key, np.nan))
                          for s in samples])
            mask = np.isfinite(y)
            if mask.sum() < 3:
                continue  # 键不存在/全 NaN——跳过不硬拟（与 poly_ridge 同约定）
            krg = KRG(theta0=theta0, print_global=False)
            krg.set_training_values(X[mask], y[mask])
            krg.train()
            self.models[key] = krg
        return self._mark_fitted(len(samples))

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        self._check_fitted()
        x = np.atleast_2d(self._unit_row(params))
        return {key: float(krg.predict_values(x)[0, 0])
                for key, krg in self.models.items()}

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        """KRG 自带方差（逐指标 σ），主动学习/贝叶斯校准的接入基础。"""
        self._check_fitted()
        x = np.atleast_2d(self._unit_row(params))
        out: dict[str, float] = {}
        for key, krg in self.models.items():
            var = float(krg.predict_variances(x)[0, 0])
            out[key] = float(np.sqrt(max(var, 0.0)))
        return out
