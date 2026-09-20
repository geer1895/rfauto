"""响应面代理（P6 原实现移植）。

历史：P6 批次的 GP/RBF 响应面预筛器（原 optimization/surrogate.py，
单模块形态）。v0 接口化后并入 surrogate 包，类名改为 ResponseSurfaceModel
——`SurrogateModel` 名字让给 base.py 的第三方接入契约（ABC）。
该实现面向"X/y 数组响应面"语义，与 base 的"params/metrics 字典"契约
不同；适配到新契约的封装在 v1 校准服务中提供。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ResponseSurfaceModel:
    """响应面代理：用少量样本构建 RBF/GP 响应面，预筛参数组合。"""

    def __init__(self, backend: str = "rbf") -> None:
        self.backend = backend
        self.X_train: np.ndarray | None = None
        self.y_train: np.ndarray | None = None
        self.model: Any = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """拟合代理模型。"""
        self.X_train = np.array(X)
        self.y_train = np.array(y)

        if self.backend == "rbf":
            self._fit_rbf()
        elif self.backend == "gp":
            self._fit_gp()
        else:
            raise ValueError(f"未知后端: {self.backend}")

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """预测 (mean, std)。"""
        if self.model is None:
            raise RuntimeError("模型未拟合")
        X = np.array(X)
        if self.backend == "rbf":
            return self._predict_rbf(X)
        elif self.backend == "gp":
            return self._predict_gp(X)
        else:
            raise ValueError(f"未知后端: {self.backend}")

    def _fit_rbf(self) -> None:
        from scipy.interpolate import RBFInterpolator
        self.model = RBFInterpolator(
            self.X_train, self.y_train,
            kernel="thin_plate_spline", smoothing=0.1,
        )
        logger.info("RBF 代理模型拟合完成: %d 样本", len(self.X_train))

    def _fit_gp(self) -> None:
        try:
            from sklearn.gaussian_process import GaussianProcessRegressor
            from sklearn.gaussian_process.kernels import RBF, WhiteKernel
            kernel = RBF(length_scale=1.0) + WhiteKernel(noise_level=0.1)
            self.model = GaussianProcessRegressor(
                kernel=kernel, alpha=1e-6, normalize_y=True, n_restarts_optimizer=5,
            )
            self.model.fit(self.X_train, self.y_train)
            logger.info("GP 代理模型拟合完成: %d 样本", len(self.X_train))
        except ImportError:
            logger.warning("sklearn 未安装，回退到 RBF")
            self.backend = "rbf"
            self._fit_rbf()

    def _predict_rbf(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mean = self.model(X)
        std = np.zeros_like(mean)
        return mean, std

    def _predict_gp(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mean, std = self.model.predict(X, return_std=True)
        return mean, std


class SurrogatePrescreener:
    """代理模型预筛器。"""

    def __init__(self, n_initial: int = 20, n_prescreen: int = 100,
                 threshold: float = 0.5) -> None:
        self.n_initial = n_initial
        self.n_prescreen = n_prescreen
        self.threshold = threshold
        self.surrogate = ResponseSurfaceModel(backend="rbf")

    def prescreen(
        self,
        objective_fn: Callable[[np.ndarray], float],
        bounds: tuple[np.ndarray, np.ndarray],
        n_features: int,
    ) -> dict[str, Any]:
        """预筛流程。"""
        X_lhs = self._lhs_sample(bounds, self.n_initial)
        y_lhs = np.array([objective_fn(x) for x in X_lhs])

        self.surrogate.fit(X_lhs, y_lhs)

        X_candidates = self._lhs_sample(bounds, self.n_prescreen)
        y_pred, _ = self.surrogate.predict(X_candidates)

        best_so_far = np.min(y_lhs)
        threshold_value = best_so_far * (1 + self.threshold)
        mask = y_pred < threshold_value

        X_selected = X_candidates[mask]
        n_prescreened = len(X_candidates) - len(X_selected)

        logger.info("预筛完成: LHS %d, 候选 %d, 预筛掉 %d, 保留 %d",
                    self.n_initial, self.n_prescreen, n_prescreened,
                    len(X_selected))

        return {
            "ok": True,
            "X_initial": X_lhs.tolist(),
            "y_initial": y_lhs.tolist(),
            "X_selected": X_selected.tolist(),
            "n_evaluations": self.n_initial,
            "n_prescreened": n_prescreened,
            "n_selected": len(X_selected),
            "best_so_far": float(best_so_far),
        }

    def _lhs_sample(self, bounds: tuple[np.ndarray, np.ndarray],
                    n_samples: int) -> np.ndarray:
        from scipy.stats import qmc
        lower, upper = bounds
        n_features = len(lower)
        sampler = qmc.LatinHypercube(d=n_features, seed=42)
        X_unit = sampler.random(n=n_samples)
        X = qmc.scale(X_unit, lower, upper)
        return X
