"""四代a·g14-close 稳健预测（三门显式回退）（AU-1 b4 机械拆分；函数体逐字节未动）。

最小样本数 / LOO 信度 / 越界三门全显式构造参数；unknown 态只给声明保守
上界（multiple × max(观测)），绝不瞎猜点估计。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .offset_power import (
    DEFAULT_MESH_POWER,
    OffsetPowerDurationPredictor,
)
from .sample import DurationSample

# ---------------------------------------------------------------------------
# G14 close-out (g14-close) — robust prediction with explicit fallbacks
# ---------------------------------------------------------------------------

#: Minimum calibration samples for a trusted prediction. Below this the LOO
#: spread is not meaningful (a 2-3 sample fit has at most 0-1 honest holdout
#: folds) and the predictor must fall back to "unknown".
MIN_CALIBRATION_SAMPLES = 4
#: Maximum trusted leave-one-out relative error. Above this the model mispredicts
#: by >=100% on at least one honest holdout — an explicitly untrusted regime.
MAX_TRUSTED_LOO_ERROR = 1.0
#: Conservative upper-bound multiple for the "unknown" fallback: the bound is
#: this multiple of the largest observed solve time. Declared constant, never
#: fitted, so the fallback is deterministic and auditable.
UNKNOWN_BOUND_MULTIPLE = 4.0

#: Prediction status values.
STATUS_CALIBRATED = "calibrated"
STATUS_EXTRAPOLATED = "extrapolated"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class DurationPrediction:
    """Result of a robust duration prediction (G14 close-out semantics).

    * ``status == "calibrated"``: the request is inside the calibration range
      and the model passed its LOO trust gate; ``predicted_s`` is the point
      estimate and ``upper_bound_s = predicted_s * (1 + loo_max)``.
    * ``status == "extrapolated"``: same numbers, but the query lies outside
      the calibration feature range — treat the bound as low-confidence.
    * ``status == "unknown"``: too few samples or an untrusted model
      (LOO max error above the gate). ``predicted_s`` is **None** — the caller
      gets no number rather than a bad number — and ``upper_bound_s`` is the
      declared conservative bound ``unknown_bound_multiple * max(observed)``
      (``None`` only when there is no observed data at all).
    """

    status: str
    predicted_s: float | None
    upper_bound_s: float | None
    n_samples: int
    loo_mean_rel_error: float | None = None
    loo_max_rel_error: float | None = None
    reason: str = ""
    #: W2⑦④ 分档语义：命中桶标签（"solver/template/grid_tier"）、命中桶自身
    #: 状态、以及回退路径（""=桶级直接命中；"global"=桶不可用回退全局档；
    #: "none"=全局亦不可用，声明 unknown）。旧调用路径三值取缺省，行为不变。
    bucket: str | None = None
    bucket_status: str | None = None
    fallback: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-able snapshot (deterministic key order)."""
        return {
            "status": self.status,
            "predicted_s": self.predicted_s,
            "upper_bound_s": self.upper_bound_s,
            "n_samples": self.n_samples,
            "loo_mean_rel_error": self.loo_mean_rel_error,
            "loo_max_rel_error": self.loo_max_rel_error,
            "reason": self.reason,
            "bucket": self.bucket,
            "bucket_status": self.bucket_status,
            "fallback": self.fallback,
        }


class RobustDurationPredictor:
    """Wrap :class:`OffsetPowerDurationPredictor` with explicit trust gates.

    Deterministic pure wrapper (no IO, no wall-clock): given calibration
    samples it either produces a calibrated point estimate plus a conservative
    upper bound covering the worst honest holdout error, or refuses with
    ``status="unknown"`` and a declared conservative bound. The three gates
    (minimum sample count, LOO trust threshold, out-of-range query) are all
    explicit constructor arguments with module-level defaults.
    """

    def __init__(
        self,
        samples: Any,
        *,
        base: OffsetPowerDurationPredictor | None,
        loo_errors: list[float],
        min_samples: int = MIN_CALIBRATION_SAMPLES,
        max_trusted_loo_error: float = MAX_TRUSTED_LOO_ERROR,
        unknown_bound_multiple: float = UNKNOWN_BOUND_MULTIPLE,
    ) -> None:
        self.samples = list(samples)
        self.base = base
        self.loo_errors = list(loo_errors)
        self.min_samples = int(min_samples)
        self.max_trusted_loo_error = float(max_trusted_loo_error)
        self.unknown_bound_multiple = float(unknown_bound_multiple)
        self.n_samples = len(self.samples)
        self.loo_max: float | None = (
            max(self.loo_errors) if self.loo_errors else None
        )
        self.loo_mean: float | None = (
            sum(self.loo_errors) / len(self.loo_errors) if self.loo_errors else None
        )
        self._observed_max_s: float | None = (
            max(float(s.solve_s) for s in self.samples) if self.samples else None
        )

    # -- construction --------------------------------------------------------
    @classmethod
    def fit(
        cls,
        samples: Any,
        mesh_power: float = DEFAULT_MESH_POWER,
        n_exc_power: float = 1.0,
        *,
        min_samples: int = MIN_CALIBRATION_SAMPLES,
        max_trusted_loo_error: float = MAX_TRUSTED_LOO_ERROR,
        unknown_bound_multiple: float = UNKNOWN_BOUND_MULTIPLE,
    ) -> RobustDurationPredictor:
        """Fit on ``samples`` and evaluate the trust gates (deterministic)."""
        rows = list(samples)
        # S-1 C-02 2026-10-04：fit 样本严格 solve_s>0 预校验——solve_s=0
        # （未申报哨兵）/负值样本此前直穿 loo_relative_errors 的
        # `/float(solve_s)` 除法，以 ZeroDivisionError 裸炸且不带来源；
        # 这里显式 ValueError 列出全部病灶样本 source（哨兵层语义：
        # 预测查询样本合法 0，拟合样本不允许）。
        bad = [s for s in rows
               if not (math.isfinite(float(s.solve_s)) and float(s.solve_s) > 0.0)]
        if bad:
            detail = ", ".join(
                f"solve_s={float(s.solve_s)!r} (source={s.source!r})"
                for s in bad[:5])
            raise ValueError(
                f"fit 样本必须带实测 solve_s>0（0=未申报哨兵/负值/非有限"
                f"均拒绝），{len(bad)}/{len(rows)} 条不合规: {detail}")
        if len(rows) < int(min_samples):
            return cls(
                rows,
                base=None,
                loo_errors=[],
                min_samples=min_samples,
                max_trusted_loo_error=max_trusted_loo_error,
                unknown_bound_multiple=unknown_bound_multiple,
            )
        base = OffsetPowerDurationPredictor.fit(
            rows, mesh_power=mesh_power, n_exc_power=n_exc_power
        )
        loo = OffsetPowerDurationPredictor.loo_relative_errors(
            rows, mesh_power=mesh_power, n_exc_power=n_exc_power
        )
        return cls(
            rows,
            base=base,
            loo_errors=loo,
            min_samples=min_samples,
            max_trusted_loo_error=max_trusted_loo_error,
            unknown_bound_multiple=unknown_bound_multiple,
        )

    # -- gates ----------------------------------------------------------------
    @property
    def status(self) -> str:
        """Overall trust status of the fitted predictor."""
        if self.base is None:
            return STATUS_UNKNOWN
        if self.loo_max is None or not (self.loo_max <= self.max_trusted_loo_error):
            return STATUS_UNKNOWN
        return STATUS_CALIBRATED

    def conservative_unknown_bound_s(self) -> float | None:
        """Declared fallback bound: ``multiple * max(observed solve_s)``."""
        if self._observed_max_s is None:
            return None
        return self.unknown_bound_multiple * self._observed_max_s

    # -- prediction ------------------------------------------------------------
    def _outside_calibration_range(self, sample: DurationSample) -> str | None:
        """Return which feature of ``sample`` is outside the calibration range."""
        meshes = [float(s.feature("mesh_mm")) for s in self.samples]
        excites = [float(s.feature("n_excitations")) for s in self.samples]
        mesh = float(sample.feature("mesh_mm"))
        n_exc = float(sample.feature("n_excitations"))
        if not (min(meshes) <= mesh <= max(meshes)):
            return f"mesh_mm={mesh:g} outside calibrated range " \
                   f"[{min(meshes):g}, {max(meshes):g}]"
        if not (min(excites) <= n_exc <= max(excites)):
            return f"n_excitations={n_exc:g} outside calibrated range " \
                   f"[{min(excites):g}, {max(excites):g}]"
        return None

    def predict(self, sample: DurationSample | None = None, /, **kwargs: Any) -> DurationPrediction:
        """Predict with explicit fallback semantics (see DurationPrediction)."""
        if sample is None:
            sample = DurationSample(**kwargs)
        if not isinstance(sample, DurationSample):
            raise TypeError(f"expected DurationSample, got {type(sample).__name__}")

        loo_mean = self.loo_mean
        loo_max = self.loo_max
        if self.status == STATUS_UNKNOWN:
            if self.base is None:
                reason = (
                    f"insufficient samples: n={self.n_samples} < "
                    f"min_samples={self.min_samples}"
                )
            else:
                reason = (
                    f"model untrusted: LOO max rel error {loo_max!r} > "
                    f"max_trusted_loo_error={self.max_trusted_loo_error:g}"
                )
            return DurationPrediction(
                status=STATUS_UNKNOWN,
                predicted_s=None,
                upper_bound_s=self.conservative_unknown_bound_s(),
                n_samples=self.n_samples,
                loo_mean_rel_error=loo_mean,
                loo_max_rel_error=loo_max,
                reason=reason,
            )

        outside = self._outside_calibration_range(sample)
        predicted = self.base.predict_s(sample)  # type: ignore[union-attr]
        bound = float(predicted) * (1.0 + float(self.loo_max))  # type: ignore[arg-type]
        if outside is not None:
            return DurationPrediction(
                status=STATUS_EXTRAPOLATED,
                predicted_s=float(predicted),
                upper_bound_s=bound,
                n_samples=self.n_samples,
                loo_mean_rel_error=loo_mean,
                loo_max_rel_error=loo_max,
                reason=f"query outside calibration range: {outside}",
            )
        return DurationPrediction(
            status=STATUS_CALIBRATED,
            predicted_s=float(predicted),
            upper_bound_s=bound,
            n_samples=self.n_samples,
            loo_mean_rel_error=loo_mean,
            loo_max_rel_error=loo_max,
            reason="within calibration range and LOO trust gate",
        )

    # -- coverage ----------------------------------------------------------------
    def coverage_ratio(self) -> float | None:
        """Fraction of calibration samples covered by the deployed bound rule.

        For each sample the predictor is re-fit on the others (honest holdout)
        and the sample counts as covered when
        ``actual <= pred_fold * (1 + loo_max_full)`` — i.e. the same bound
        rule the deployed predictor uses, evaluated on historical actuals.
        ``None`` when there is no usable fold (fewer than 3 samples or the
        predictor is in the unknown regime).
        """
        if self.base is None or self.loo_max is None:
            return None
        bound_factor = 1.0 + float(self.loo_max)
        rows = self.samples
        covered = 0
        evaluated = 0
        for index in range(len(rows)):
            train = [s for j, s in enumerate(rows) if j != index]
            if len(train) < 2:
                continue
            try:
                fold = OffsetPowerDurationPredictor.fit(train)
            except ValueError:
                continue
            evaluated += 1
            predicted = fold.predict_s(rows[index])
            if float(rows[index].solve_s) <= predicted * bound_factor:
                covered += 1
        if evaluated == 0:
            return None
        return covered / evaluated

    def summary(self) -> dict[str, Any]:
        """JSON-able calibration summary (status, gates, coverage)."""
        return {
            "status": self.status,
            "n_samples": self.n_samples,
            "min_samples": self.min_samples,
            "max_trusted_loo_error": self.max_trusted_loo_error,
            "loo_mean_rel_error": self.loo_mean,
            "loo_max_rel_error": self.loo_max,
            "coverage_ratio": self.coverage_ratio(),
            "unknown_bound_multiple": self.unknown_bound_multiple,
            "conservative_unknown_bound_s": self.conservative_unknown_bound_s(),
            "observed_max_solve_s": self._observed_max_s,
        }
