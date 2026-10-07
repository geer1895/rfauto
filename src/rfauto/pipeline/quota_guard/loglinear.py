"""二代·log-linear 时长预测器（AU-1 b4 自 quota_guard.py 机械拆分；函数体逐字节未动）。

log(t_s) = c0 + Σ c_i·log(feature_i)，log 空间最小二乘（numpy）；
特征集缺省 = :data:`rfauto.pipeline.quota_guard.sample.DURATION_FEATURES`。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .sample import DURATION_FEATURES, DurationSample


class DurationPredictor:
    """Deterministic log-linear solve-duration model.

    log(t_s) = c0 + sum_i c_i * log(feature_i), with coefficients fitted by
    ordinary least squares in log space (numpy). The model is a pure function of
    its coefficients: same samples in, same coefficients out.
    """

    def __init__(
        self,
        coefficients: Any,
        features: tuple[str, ...] = DURATION_FEATURES,
    ) -> None:
        self.features = tuple(features)
        self.coefficients = tuple(float(c) for c in coefficients)
        if len(self.coefficients) != len(self.features) + 1:
            raise ValueError(
                "DurationPredictor needs len(features)+1 coefficients, got "
                f"{len(self.coefficients)} for {len(self.features)} features"
            )

    def _design_row(self, sample: DurationSample) -> list[float]:
        return [1.0] + [math.log(sample.feature(name)) for name in self.features]

    @classmethod
    def fit(
        cls,
        samples: Any,
        features: tuple[str, ...] = DURATION_FEATURES,
    ) -> DurationPredictor:
        """Least-squares fit in log space; needs >= len(features)+1 samples."""
        rows = list(samples)
        features = tuple(features)
        if len(rows) < len(features) + 1:
            raise ValueError(
                f"need >= {len(features) + 1} samples to fit {len(features)} features, "
                f"got {len(rows)}"
            )
        design = np.array([[1.0] + [math.log(s.feature(f)) for f in features] for s in rows])
        target = np.array([math.log(float(s.solve_s)) for s in rows])
        coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
        return cls(coefficients, features)

    def predict_s(self, sample: DurationSample | None = None, /, **kwargs: Any) -> float:
        """Predicted solve wall-clock in seconds.

        Pass a DurationSample positionally, or feature keyword values
        (mesh_mm=...) to build one on the fly.
        """
        if sample is None:
            sample = DurationSample(**kwargs)
        if not isinstance(sample, DurationSample):
            raise TypeError(f"expected DurationSample, got {type(sample).__name__}")
        row = np.array(self._design_row(sample))
        coefficients = np.array(self.coefficients)
        return float(math.exp(float(row @ coefficients)))

    def relative_errors(self, samples: Any) -> list[float]:
        """In-sample relative errors |pred-actual| / actual."""
        return [
            abs(self.predict_s(s) - float(s.solve_s)) / float(s.solve_s)
            for s in samples
        ]

    @classmethod
    def loo_relative_errors(
        cls,
        samples: Any,
        features: tuple[str, ...] = DURATION_FEATURES,
    ) -> list[float]:
        """Leave-one-out relative errors (honest holdout estimate)."""
        rows = list(samples)
        errors: list[float] = []
        for index in range(len(rows)):
            train = [s for j, s in enumerate(rows) if j != index]
            try:
                predictor = cls.fit(train, features)
            except ValueError:
                errors.append(float("inf"))
                continue
            actual = float(rows[index].solve_s)
            errors.append(abs(predictor.predict_s(rows[index]) - actual) / actual)
        return errors
