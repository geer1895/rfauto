"""sklearn GBDT 代理（B3，#253③ 缺口补齐：sklearn 已在 src 使用但零声明）。

GradientBoostingRegressor（逐步加树，小表格样本上的强基线）；结构照
smt_mfk 可选依赖模式：惰性 import，未安装显式报错（注册表可见、
fit/predict 才炸）→ pip install rfauto[gbdt]。

契约（同 base）：
    model = GBDTSurrogate(config={"bounds": {...}, ...超参可覆盖})
    model.fit(samples)             # [{"params": {...}, "metrics": {...}}]
    pred = model.predict(params)   # 逐指标 dict

确定性：缺省 subsample=1.0（无随机子采样）+ random_state=42 → 同 seed
同数据逐位可复现（C4 纯函数语义红线）。

uncertainty() 不覆盖（基类默认返 None）：GBDT 无原生逐点 σ，不确定度
走 active_learning bootstrap 通道（optimization.uncertainty 的
gp_cost_sigma 与其同源闭式，B5 终止判据同数据面）。
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from rfauto.optimization.surrogate.base import SurrogateModel, surrogate_registry


def _numeric_keys(samples: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for s in samples:
        keys |= {k for k, v in s.get("metrics", {}).items()
                 if isinstance(v, (int, float))}
    return keys


@surrogate_registry.register("gbdt")
class GBDTSurrogate(SurrogateModel):
    """逐指标 sklearn GBDT 代理（params→metrics 字典契约，见 base）。

    config:
        bounds: {param: (low, high)}（必填，归一化基准）
        metrics: 要建模的指标键列表（缺省 = fit 样本里全部数值键的并集）
        n_estimators / learning_rate / max_depth / subsample /
        min_samples_leaf / loss / random_state：GradientBoostingRegressor
        同名超参（缺省 200 / 0.05 / 2 / 1.0 / 5 / "squared_error" / 42）
    """

    KIND = "gbdt"

    #: 超参缺省（subsample=1.0 保证缺省确定性——<1.0 走随机子采样）
    DEFAULT_HP: ClassVar[dict[str, Any]] = {
        "n_estimators": 200,
        "learning_rate": 0.05,
        "max_depth": 2,
        "subsample": 1.0,
        "min_samples_leaf": 5,
        "loss": "squared_error",
        "random_state": 42,
    }

    def _ensure_sklearn(self):
        try:
            from sklearn.ensemble import GradientBoostingRegressor
        except ImportError as exc:
            raise RuntimeError(
                "gbdt 代理需要 scikit-learn>=1.3,<3："
                "pip install rfauto[gbdt] 或 pip install scikit-learn"
            ) from exc
        return GradientBoostingRegressor

    def _unit_row(self, params: dict[str, float]) -> np.ndarray:
        """参数 → bounds 归一化 [0,1] 行（同 poly_ridge._unit 口径，外推有界）。"""
        return np.array([
            np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12),
                    0.0, 1.0)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)])

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        GBR = self._ensure_sklearn()
        cfg = self.config
        self.bounds = {k: tuple(v) for k, v in cfg["bounds"].items()}
        self.names = sorted(self.bounds)
        keys = cfg.get("metrics") or _numeric_keys(samples)
        self.metric_keys = sorted(keys)

        X = np.array([self._unit_row(s["params"]) for s in samples])
        hp = {k: cfg.get(k, v) for k, v in self.DEFAULT_HP.items()}
        self.models: dict[str, Any] = {}
        for key in self.metric_keys:
            y = np.array([float(s["metrics"].get(key, np.nan))
                          for s in samples])
            mask = np.isfinite(y)
            if mask.sum() < 2:
                continue  # 键全 NaN/缺失（如真机失败 trial）——跳过不硬拟
            m = GBR(**hp)
            m.fit(X[mask], y[mask])
            self.models[key] = m
        return self._mark_fitted(len(samples))

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")
        x = np.atleast_2d(self._unit_row(params))
        return {key: float(m.predict(x)[0])
                for key, m in self.models.items()}
