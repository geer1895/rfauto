"""三代·offset+power FDTD 时长模型（AU-1 b4 自 quota_guard.py 机械拆分；函数体逐字节未动）。

t_s = offset_s + scale_s·mesh_mm^(-mesh_power)·n_excitations^n_exc_power；
mesh_power 为物理推导固定常数（DEFAULT_MESH_POWER），从不在留出目标上拟合。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .sample import DurationSample

#: Physically-derived mesh exponent for the offset+power model. FDTD cost is
#: ~ N_cells * N_steps; in the rfauto openEMS recipe every spacing scales with
#: the base mesh, so N_cells ~ mesh^-3 while the *measured* timestep count of
#: the real runs grows like mesh^-0.8 -> total ~ mesh^-3.8. 3.5 is the round
#: midpoint of the measured 3.0-3.8 band and is the default here.
DEFAULT_MESH_POWER = 3.5


class OffsetPowerDurationPredictor:
    """Deterministic FDTD duration model with a fixed per-run overhead.

    t_s = offset_s + scale_s * mesh_mm ** (-mesh_power) * n_excitations ** n_exc_power

    Rationale: an openEMS solve pays a roughly mesh-independent overhead (process
    start, mesh construction, port post-processing) plus a volume that scales like
    cell-updates, i.e. a power of the mesh size times the number of excitations.
    offset_s/scale_s are fitted by ordinary least squares; mesh_power is a fixed,
    physically-derived constant (see DEFAULT_MESH_POWER), never fitted on the
    held-out target times.
    """

    def __init__(
        self,
        offset_s: float,
        scale_s: float,
        mesh_power: float = DEFAULT_MESH_POWER,
        n_exc_power: float = 1.0,
    ) -> None:
        self.offset_s = float(offset_s)
        self.scale_s = float(scale_s)
        self.mesh_power = float(mesh_power)
        self.n_exc_power = float(n_exc_power)

    @staticmethod
    def _work(sample: DurationSample, mesh_power: float, n_exc_power: float) -> float:
        mesh = sample.feature("mesh_mm")
        n_exc = sample.feature("n_excitations")
        return mesh ** (-mesh_power) * n_exc**n_exc_power

    @classmethod
    def fit(
        cls,
        samples: Any,
        mesh_power: float = DEFAULT_MESH_POWER,
        n_exc_power: float = 1.0,
    ) -> OffsetPowerDurationPredictor:
        """Least-squares fit of the overhead + work term; needs >= 2 samples."""
        rows = list(samples)
        if len(rows) < 2:
            raise ValueError(f"need >= 2 samples to fit offset+power, got {len(rows)}")
        design = np.array(
            [[1.0, cls._work(s, mesh_power, n_exc_power)] for s in rows]
        )
        target = np.array([float(s.solve_s) for s in rows])
        (offset, scale), *_ = np.linalg.lstsq(design, target, rcond=None)
        return cls(offset, scale, mesh_power=mesh_power, n_exc_power=n_exc_power)

    def predict_s(self, sample: DurationSample | None = None, /, **kwargs: Any) -> float:
        """Predicted solve wall-clock in seconds (strictly positive)."""
        if sample is None:
            sample = DurationSample(**kwargs)
        if not isinstance(sample, DurationSample):
            raise TypeError(f"expected DurationSample, got {type(sample).__name__}")
        work = self._work(sample, self.mesh_power, self.n_exc_power)
        return max(self.offset_s + self.scale_s * work, 1e-9)

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
        mesh_power: float = DEFAULT_MESH_POWER,
        n_exc_power: float = 1.0,
    ) -> list[float]:
        """Leave-one-out relative errors (honest holdout estimate)."""
        rows = list(samples)
        errors: list[float] = []
        for index in range(len(rows)):
            train = [s for j, s in enumerate(rows) if j != index]
            try:
                predictor = cls.fit(train, mesh_power=mesh_power, n_exc_power=n_exc_power)
            except ValueError:
                errors.append(float("inf"))
                continue
            actual = float(rows[index].solve_s)
            errors.append(abs(predictor.predict_s(rows[index]) - actual) / actual)
        return errors
