"""Quota and orchestration-cost guard for the rfauto pipeline.

Two layers live here:

* :class:'QuotaGuard' / :class:'QuotaLimits' — the legacy P2 guard that caps
  trial count and wall-clock hours.
* Orchestration costing — :class:'CostLedger' records four cost classes
  (LLM tokens, solver machine time 'solve_s', license seat-hours, optional
  GPU hours) per batch/actor; :class:'BudgetLimits' turns those into a STOP
  gate (:class:'BudgetExceededError'); :class:'DurationPredictor' is a
  deterministic log-linear model that estimates a single openEMS solve from
  recipe-level features (mesh size / domain volume / excitations / points).
  This module adds an opt-in stop-mechanism feature plane
  (:data:`DURATION_FEATURES_V2`: declared NrTS step cap + measured stop reason
  one-hot/interaction) so energy-stop and NrTS-cap-stop solves can be
  separated — the stop-reason mixing that pinned the ratrace LOO floor at
  ~80%.

Everything here is deterministic, pure Python (numpy is used only for the
least-squares fit of DurationPredictor); no network, no solver calls, no
wall-clock reads outside the legacy QuotaGuard.check_wall_time.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class QuotaLimits:
    """Defines quota limits for a pipeline run."""
    max_trials: int = 100
    max_wall_hours: float = 24.0


class QuotaGuard:
    """Enforces quota limits on trial count and wall time.

    Usage:
        guard = QuotaGuard(QuotaLimits(max_trials=50, max_wall_hours=8.0))
        guard.check_trial(trial_count)  # raises if exceeded
        guard.check_wall_time(start_time)  # raises if exceeded
    """

    def __init__(self, limits: QuotaLimits | None = None,
                 budgets: BudgetLimits | None = None) -> None:
        self.limits = limits or QuotaLimits()
        # Optional extension: an attached cost budget gate. None keeps the
        # legacy behaviour byte-for-byte.
        self.budgets = budgets

    def check_trial(self, trial_count: int) -> None:
        """Check if trial count is within limits. Raises QuotaExceededError if not."""
        if trial_count >= self.limits.max_trials:
            raise QuotaExceededError(
                f"Trial limit reached: {trial_count}/{self.limits.max_trials}"
            )

    def check_wall_time(self, start_time: float) -> None:
        """Check if wall time is within limits. Raises QuotaExceededError if not."""
        elapsed_hours = (time.time() - start_time) / 3600.0
        if elapsed_hours >= self.limits.max_wall_hours:
            raise QuotaExceededError(
                f"Wall time limit reached: {elapsed_hours:.2f}h / {self.limits.max_wall_hours}h"
            )

    def check_budget(self, ledger: CostLedger) -> None:
        """Check the cost ledger against the attached budgets (STOP gate)."""
        if self.budgets is not None:
            self.budgets.check(ledger)

    def remaining_budget(
        self, trial_count: int = 0, start_time: float | None = None
    ) -> dict[str, Any]:
        """Return remaining budget as {trials_left, hours_left}."""
        trials_left = max(0, self.limits.max_trials - trial_count)

        if start_time is not None:
            elapsed_hours = (time.time() - start_time) / 3600.0
            hours_left = max(0.0, self.limits.max_wall_hours - elapsed_hours)
        else:
            hours_left = self.limits.max_wall_hours

        return {
            "trials_left": trials_left,
            "hours_left": round(hours_left, 2),
        }


class QuotaExceededError(Exception):
    """Raised when a quota limit is exceeded."""
    pass


# ---------------------------------------------------------------------------
# Orchestration cost ledger + budget gate
# ---------------------------------------------------------------------------

#: The four recorded cost classes (plus a unit-agnostic monetary 'cost'
#: accumulator). 'tokens' is the "total only, split unknown" counter;
#: 'prompt_tokens' / 'completion_tokens' are the explicit split.
LEDGER_FIELDS: tuple[str, ...] = (
    "prompt_tokens",
    "completion_tokens",
    "tokens",
    "solve_s",
    "seat_hours",
    "gpu_hours",
    "cost",
)


def _zero_row() -> dict[str, float]:
    return dict.fromkeys(LEDGER_FIELDS, 0.0)


def _row_with_totals(row: dict[str, float]) -> dict[str, float]:
    out = {k: float(row[k]) for k in LEDGER_FIELDS}
    out["total_tokens"] = (
        out["prompt_tokens"] + out["completion_tokens"] + out["tokens"]
    )
    out["solve_hours"] = out["solve_s"] / 3600.0
    return out


class BudgetExceededError(QuotaExceededError):
    """Raised when an orchestration budget is exceeded -> STOP.

    Subclasses QuotaExceededError so existing broad 'except QuotaExceededError'
    handlers still stop the run.
    """

    def __init__(self, kind: str, used: float, limit: float,
                 message: str | None = None) -> None:
        self.kind = kind
        self.used = float(used)
        self.limit = float(limit)
        super().__init__(
            message or f"Budget exceeded: {kind} used={self.used} > limit={self.limit}"
        )


class CostLedger:
    """Per-batch / per-actor orchestration cost ledger.

    Cost classes:

    * LLM tokens — prompt_tokens / completion_tokens explicitly, or a tokens
      total when the split is unknown;
    * solver machine time solve_s (seconds);
    * license seat-hours seat_hours;
    * optional GPU hours gpu_hours;
    * plus a unit-agnostic monetary cost accumulator.

    All operations are deterministic and side-effect free. rollup() returns a
    json.dumps-able per-batch table.
    """

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, dict[str, float]]] = {}

    # -- mutation -----------------------------------------------------------
    def add(
        self,
        batch: str,
        actor: str = "default",
        *,
        prompt_tokens: float = 0.0,
        completion_tokens: float = 0.0,
        tokens: float = 0.0,
        solve_s: float = 0.0,
        seat_hours: float = 0.0,
        gpu_hours: float = 0.0,
        cost: float = 0.0,
    ) -> CostLedger:
        """Accumulate one contribution into batch/actor."""
        values = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "tokens": tokens,
            "solve_s": solve_s,
            "seat_hours": seat_hours,
            "gpu_hours": gpu_hours,
            "cost": cost,
        }
        clean: dict[str, float] = {}
        for key, value in values.items():
            number = float(value)
            if not math.isfinite(number) or number < 0.0:
                raise ValueError(
                    f"cost ledger field {key} must be finite and >= 0, got {value!r}"
                )
            clean[key] = number
        actors = self._entries.setdefault(str(batch), {})
        row = actors.setdefault(str(actor), _zero_row())
        for key, number in clean.items():
            row[key] += number
        return self

    def merge(self, other: CostLedger) -> CostLedger:
        """Fold other into self (in place) and return self."""
        if not isinstance(other, CostLedger):
            raise TypeError(f"cannot merge {type(other).__name__} into CostLedger")
        for batch, actors in other._entries.items():
            for actor, row in actors.items():
                self.add(batch, actor, **{k: row[k] for k in LEDGER_FIELDS})
        return self

    # -- read ---------------------------------------------------------------
    def batches(self) -> list[str]:
        return sorted(self._entries)

    def actors(self, batch: str) -> list[str]:
        return sorted(self._entries.get(batch, {}))

    def rollup(self) -> dict[str, dict[str, Any]]:
        """Per-batch table: {batch: {<totals>, "actors": {actor: <totals>}}}."""
        table: dict[str, dict[str, Any]] = {}
        for batch in sorted(self._entries):
            actors = self._entries[batch]
            combined = _zero_row()
            actor_rows: dict[str, dict[str, float]] = {}
            for actor in sorted(actors):
                row = actors[actor]
                actor_rows[actor] = _row_with_totals(row)
                for key in LEDGER_FIELDS:
                    combined[key] += row[key]
            full = _row_with_totals(combined)
            full["actors"] = actor_rows
            table[batch] = full
        return table

    def totals(self) -> dict[str, float]:
        """Ledger-wide totals (same shape as one rollup row, no actors)."""
        combined = _zero_row()
        for actors in self._entries.values():
            for row in actors.values():
                for key in LEDGER_FIELDS:
                    combined[key] += row[key]
        return _row_with_totals(combined)

    def to_json(self, *, indent: int = 2) -> str:
        """Serialise the raw ledger (round-trips exactly through from_json)."""
        payload = {
            "version": 1,
            "batches": {
                batch: {
                    actor: {key: row[key] for key in LEDGER_FIELDS}
                    for actor, row in actors.items()
                }
                for batch, actors in self._entries.items()
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, data: str | bytes | dict[str, Any]) -> CostLedger:
        """Rebuild a ledger from to_json output."""
        payload = json.loads(data) if isinstance(data, (str, bytes)) else data
        ledger = cls()
        if payload.get("version") != 1:
            raise ValueError(f"unsupported cost ledger version: {payload.get('version')!r}")
        for batch, actors in payload.get("batches", {}).items():
            for actor, row in actors.items():
                ledger.add(batch, actor, **{k: float(row.get(k, 0.0)) for k in LEDGER_FIELDS})
        return ledger


@dataclass
class BudgetLimits:
    """Budget gate — any None field means "no limit".

    check() raises BudgetExceededError (STOP) on the first budget the ledger
    strictly exceeds; a value exactly equal to the limit is allowed.
    """

    token_budget: float | None = None
    wall_hours_budget: float | None = None
    seat_hours_budget: float | None = None
    cost_budget: float | None = None

    def report(self, ledger: CostLedger) -> dict[str, dict[str, Any]]:
        """Per-budget {used, limit, remaining, exceeded} snapshot."""
        totals = ledger.totals()
        specs = (
            ("tokens", totals["total_tokens"], self.token_budget),
            ("wall_hours", totals["solve_hours"], self.wall_hours_budget),
            ("seat_hours", totals["seat_hours"], self.seat_hours_budget),
            ("cost", totals["cost"], self.cost_budget),
        )
        out: dict[str, dict[str, Any]] = {}
        for kind, used, limit in specs:
            if limit is None:
                out[kind] = {
                    "used": float(used),
                    "limit": None,
                    "remaining": None,
                    "exceeded": False,
                }
            else:
                limit_f = float(limit)
                out[kind] = {
                    "used": float(used),
                    "limit": limit_f,
                    "remaining": max(0.0, limit_f - float(used)),
                    "exceeded": float(used) > limit_f,
                }
        return out

    def remaining(self, ledger: CostLedger) -> dict[str, float | None]:
        """Remaining head-room keyed tokens_left / wall_hours_left / ..."""
        return {
            f"{kind}_left": info["remaining"]
            for kind, info in self.report(ledger).items()
        }

    def check(self, ledger: CostLedger) -> None:
        """Raise BudgetExceededError on the first exceeded budget."""
        for kind, info in self.report(ledger).items():
            if info["exceeded"]:
                raise BudgetExceededError(kind, info["used"], info["limit"])

    # -- 作业级预算准入（消费分档时长预测） ------------------------------
    def admit(
        self,
        ledger: CostLedger,
        prediction: DurationPrediction,
        *,
        kind: str = "wall_hours",
    ) -> dict[str, Any]:
        """作业级预算准入门：分档预测的**保守上界**须落在剩余预算内（JSON 进出）。

        与 :meth:`check`（账面已超 → STOP）不同，本门在作业**入队前**裁决：
        ``used + upper_bound <= limit`` 放行，否则拒绝该作业（不 STOP 整个
        run）。语义刻意 fail-closed：

        * ``prediction.upper_bound_s is None``（unknown 且无任何观测可给保守
          上界）→ 拒绝并说明"不可核验"，绝不按 0 时长放行；
        * 未配置该类预算（limit None）→ 放行并如实标注"未配置"；
        * 只支持 ``kind="wall_hours"``（时长预测只能兑换机时预算；token /
          cost 预算来自账面实耗，不由时长预测推断）。
        """
        if kind != "wall_hours":
            raise ValueError(
                f"时长预测只能作 wall_hours 预算准入，实得 kind={kind!r}")
        limit = self.wall_hours_budget
        used_h = float(ledger.totals()["solve_hours"])
        base = {
            "ok": True,
            "kind": kind,
            "used_hours": used_h,
            "limit_hours": None if limit is None else float(limit),
            "remaining_hours": None,
            "predicted_s": prediction.predicted_s,
            "upper_bound_s": prediction.upper_bound_s,
            "upper_bound_hours": (
                None if prediction.upper_bound_s is None
                else float(prediction.upper_bound_s) / 3600.0
            ),
            "prediction_status": prediction.status,
            "bucket": prediction.bucket,
            "fallback": prediction.fallback,
            "reason": "",
        }
        if limit is None:
            base["reason"] = "未配置 wall_hours 预算，直接放行"
            return base
        remaining_h = max(0.0, float(limit) - used_h)
        base["remaining_hours"] = remaining_h
        if prediction.upper_bound_s is None:
            base["ok"] = False
            base["reason"] = (
                "预测 unknown 且无保守上界（无任何观测样本），预算门拒绝"
                "（fail-closed，不按零时长放行）")
            return base
        bound_h = float(prediction.upper_bound_s) / 3600.0
        if bound_h > remaining_h + 1e-12:
            base["ok"] = False
            base["reason"] = (
                f"预测保守上界 {bound_h:.4g}h（{prediction.status}"
                f"{'，回退 ' + prediction.fallback if prediction.fallback else ''}）"
                f"超剩余 wall_hours 预算 {remaining_h:.4g}h，作业拒绝")
            return base
        base["reason"] = (
            f"预测保守上界 {bound_h:.4g}h ≤ 剩余预算 {remaining_h:.4g}h，放行")
        return base


# ---------------------------------------------------------------------------
# Deterministic single-solve duration predictor (feeds scheduling)
# ---------------------------------------------------------------------------

#: Default log-linear feature set. All features are known before a solve from
#: the recipe/openEMS template and must be strictly positive.
DURATION_FEATURES: tuple[str, ...] = (
    "mesh_mm",
    "domain_volume_mm3",
    "n_excitations",
)

# -- 停机机制特征（stop-mechanism feature plane, opt-in） ----------------------
#
# 依据：能量判据停机与 NrTS 触顶停机的时长机制完全不同——
# 能量停机的步数由物理收敛决定（实测 < 声明上限），触顶停机的步数 = 声明上限
# （时长 ~ nrts_limit·dt，与收敛无关）；混池拟合是 ratrace LOO 地板 ~80% 的
# 结构性原因之一。v2 特征全部 opt-in，v1 缺省拟合（DURATION_FEATURES /
# OffsetPowerDurationPredictor）逐字节不变。

#: 实测停机原因枚举（从归档 meta/results 读）。
STOP_REASON_ENERGY = "energy"
STOP_REASON_NRTS_CAP = "nrts_cap"
STOP_REASON_TIMEOUT = "timeout"
#: stop_reason 枚举全集。空串 = 未申报（旧样本缺省，向后兼容）；其余未识别值
#: 在特征解析层按未申报处理（one-hot 全中性），不抛错（#105 装配不炸主路径）。
STOP_REASONS: tuple[str, ...] = (
    STOP_REASON_ENERGY,
    STOP_REASON_NRTS_CAP,
    STOP_REASON_TIMEOUT,
)

#: log 域 one-hot 命中电平：命中档取 e（log e = 1，拟合系数直接读作该档的
#: log 域类移位），未命中/未申报档取 1.0（log 1 = 0，零贡献）。互斥 one-hot
#: 在严格正特征约束下的声明编码，非拟合量。
STOP_ONEHOT_LEVEL = math.e

#: v2 时长特征（全部严格正、log 安全；经 :meth:`DurationSample.feature` 派生，
#: 派生名优先于同名字段）：
#:
#: * ``nrts_limit``——声明 NrTS 步数上限（字段 0=未申报 -> 特征 1.0 中性占位）；
#: * ``nrts_capped_steps``——交互项：stop_reason=="nrts_cap" 时步数由上限决定
#:   （时长 ~ nrts_limit·dt 而非能量机制），取值 = nrts_limit（触顶样本必须
#:   声明上限，否则 ValueError）；其余停机机制取 1.0（不参与）；
#: * ``stop_energy`` / ``stop_nrts_cap`` / ``stop_timeout``——互斥 one-hot
#:   （命中档 :data:`STOP_ONEHOT_LEVEL`，其余 1.0；未申报/旧样本全中性 = 零移位）。
DURATION_FEATURES_V2: tuple[str, ...] = (
    "nrts_limit",
    "nrts_capped_steps",
    "stop_energy",
    "stop_nrts_cap",
    "stop_timeout",
)


@dataclass(frozen=True)
class DurationSample:
    """One historical openEMS solve used to fit/evaluate the predictor."""

    mesh_mm: float
    #: Target observed solve wall-clock (seconds). Only required when the
    #: sample is used for fitting/evaluation; prediction skips it.
    solve_s: float = 0.0
    domain_volume_mm3: float = 1.0
    n_excitations: int = 1
    freq_points: int = 1
    solver: str = "openems"
    source: str = ""
    #: 分档维度：模板族与网格档（空串=未申报，全部落同一个"未申报"桶，
    #: 与既有样本向后兼容）。
    template: str = ""
    grid_tier: str = ""
    #: 停机机制面：声明 NrTS 步数上限（0 = 未申报/旧样本缺省）。
    nrts_limit: int = 0
    #: 实测停机原因枚举（energy/nrts_cap/timeout；"" = 未申报/旧样本缺省；
    #: 未识别值在特征解析层按未申报处理）。
    stop_reason: str = ""

    def _normalized_stop_reason(self) -> str:
        return str(self.stop_reason or "").strip().lower()

    def _v2_feature(self, name: str) -> float | None:
        """Resolve a :data:`DURATION_FEATURES_V2` name; None when not one."""
        if name == "nrts_limit":
            cap = float(self.nrts_limit)
            return cap if cap > 0.0 else 1.0  # 未申报 -> 中性占位（log 贡献 0）
        if name == "nrts_capped_steps":
            if self._normalized_stop_reason() != STOP_REASON_NRTS_CAP:
                return 1.0  # 交互项只在触顶停机档激活
            cap = float(self.nrts_limit)
            if cap <= 0.0:
                raise ValueError(
                    "stop_reason='nrts_cap' 触顶样本必须声明 nrts_limit>0，got "
                    f"{self.nrts_limit!r} (source={self.source!r})"
                )
            return cap
        if name.startswith("stop_"):
            reason = name[len("stop_"):]
            if reason in STOP_REASONS:
                hit = self._normalized_stop_reason() == reason
                return float(STOP_ONEHOT_LEVEL) if hit else 1.0
        return None

    def feature(self, name: str) -> float:
        """Return feature name as a strictly positive float.

        v2 派生名（:data:`DURATION_FEATURES_V2`，停机机制面）优先于同名字段
        解析——``nrts_limit`` 未申报（字段 0）解析为中性 1.0 而非裸字段值。
        """
        v2 = self._v2_feature(name)
        if v2 is not None:
            return v2
        try:
            value = float(getattr(self, name))
        except AttributeError as exc:  # pragma: no cover - defensive
            raise KeyError(f"unknown duration feature {name!r}") from exc
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"duration feature {name!r} must be positive and finite, got {value!r}"
            )
        return value


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


# ---------------------------------------------------------------------------
# Robust prediction with explicit fallbacks
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
    """Result of a robust duration prediction (close-out semantics).

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
    #: 分档语义：命中桶标签（"solver/template/grid_tier"）、命中桶自身
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


# ---------------------------------------------------------------------------
# 分档（adapter × 模板族 × 网格档）时长预测 + 作业级预算准入
# ---------------------------------------------------------------------------

#: 分桶维度（DurationSample 字段名）。
TIER_FIELDS: tuple[str, ...] = ("solver", "template", "grid_tier")
#: 桶标签分隔符（"openems/ratrace/0p4mm"）。
TIER_LABEL_SEP = "/"
#: 回退路径取值。
FALLBACK_NONE = "none"
FALLBACK_GLOBAL = "global"


def tier_key(solver: str, template: str = "", grid_tier: str = "") -> tuple[str, str, str]:
    """收敛分桶键：小写去空格；空串保留（=未申报桶）。"""
    return (
        str(solver or "").strip().lower(),
        str(template or "").strip().lower(),
        str(grid_tier or "").strip().lower(),
    )


def tier_label(key: tuple[str, str, str]) -> str:
    """桶标签（JSON 键；空维度显示为 ``-``）。"""
    return TIER_LABEL_SEP.join(part or "-" for part in key)


def _sample_to_dict(sample: DurationSample) -> dict[str, Any]:
    return {
        "mesh_mm": float(sample.mesh_mm),
        "solve_s": float(sample.solve_s),
        "domain_volume_mm3": float(sample.domain_volume_mm3),
        "n_excitations": int(sample.n_excitations),
        "freq_points": int(sample.freq_points),
        "solver": str(sample.solver),
        "source": str(sample.source),
        "template": str(sample.template),
        "grid_tier": str(sample.grid_tier),
        "nrts_limit": int(sample.nrts_limit),
        "stop_reason": str(sample.stop_reason),
    }


def _sample_from_dict(row: dict[str, Any]) -> DurationSample:
    return DurationSample(
        mesh_mm=float(row["mesh_mm"]),
        solve_s=float(row.get("solve_s", 0.0)),
        domain_volume_mm3=float(row.get("domain_volume_mm3", 1.0)),
        n_excitations=int(row.get("n_excitations", 1)),
        freq_points=int(row.get("freq_points", 1)),
        solver=str(row.get("solver", "openems")),
        source=str(row.get("source", "")),
        template=str(row.get("template", "")),
        grid_tier=str(row.get("grid_tier", "")),
        # 增量字段：旧 payload 缺键按缺省装载（0=未申报 / ""=未申报），
        # 显式 null 同样落缺省（`or 0`/`or ""` 只做缺省回填，非 #117 容器陷阱）。
        nrts_limit=int(row.get("nrts_limit") or 0),
        stop_reason=str(row.get("stop_reason") or ""),
    )


class TieredDurationPredictor:
    """按 (adapter × 模板族 × 网格档) 分桶的稳健时长预测器。

    每个桶独立拟合 :class:`RobustDurationPredictor`（同一套三门：最小样本数 /
    LOO 信度 / 越界），另拟合一个全局档作回退。预测语义（诚实分级）：

    * 桶命中且桶可信 → 桶级 ``calibrated``/``extrapolated``（``fallback=""``）；
    * 桶缺失或桶不可信（样本不足 / LOO 不过门）→ 回退全局档
      （``fallback="global"``，reason 说明桶为何不可用）；
    * 全局档亦不可信 → ``unknown``：``predicted_s=None``，只给声明保守上界
      （桶的 ``multiple × max(观测)``，桶无观测则取全局的），**绝不瞎猜**。

    纯确定性（同样本同输出）、无 IO；JSON 进出见 :meth:`to_json` /
    :meth:`from_json`（序列化样本+门参数，反序列化重拟合——lstsq 对同输入逐位
    一致，因此不必序列化系数）。
    """

    def __init__(
        self,
        buckets: dict[tuple[str, str, str], RobustDurationPredictor],
        global_predictor: RobustDurationPredictor,
        *,
        mesh_power: float = DEFAULT_MESH_POWER,
        n_exc_power: float = 1.0,
        min_samples: int = MIN_CALIBRATION_SAMPLES,
        max_trusted_loo_error: float = MAX_TRUSTED_LOO_ERROR,
        unknown_bound_multiple: float = UNKNOWN_BOUND_MULTIPLE,
    ) -> None:
        self.buckets = dict(buckets)
        self.global_predictor = global_predictor
        self.mesh_power = float(mesh_power)
        self.n_exc_power = float(n_exc_power)
        self.min_samples = int(min_samples)
        self.max_trusted_loo_error = float(max_trusted_loo_error)
        self.unknown_bound_multiple = float(unknown_bound_multiple)

    # -- construction ------------------------------------------------------
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
    ) -> TieredDurationPredictor:
        """按桶分组拟合 + 全局档拟合（桶顺序=首次出现序，确定性）。"""
        rows = list(samples)
        grouped: dict[tuple[str, str, str], list[DurationSample]] = {}
        for sample in rows:
            if not isinstance(sample, DurationSample):
                raise TypeError(
                    f"expected DurationSample, got {type(sample).__name__}")
            key = tier_key(sample.solver, sample.template, sample.grid_tier)
            grouped.setdefault(key, []).append(sample)
        gates = {
            "min_samples": min_samples,
            "max_trusted_loo_error": max_trusted_loo_error,
            "unknown_bound_multiple": unknown_bound_multiple,
        }
        buckets = {
            key: RobustDurationPredictor.fit(
                members, mesh_power, n_exc_power, **gates)
            for key, members in grouped.items()
        }
        global_predictor = RobustDurationPredictor.fit(
            rows, mesh_power, n_exc_power, **gates)
        return cls(
            buckets, global_predictor, mesh_power=mesh_power,
            n_exc_power=n_exc_power, **gates)

    # -- read ----------------------------------------------------------------
    @property
    def n_samples(self) -> int:
        return self.global_predictor.n_samples

    def bucket_labels(self) -> list[str]:
        """全部桶标签（首次出现序）。"""
        return [tier_label(key) for key in self.buckets]

    def bucket_for(self, solver: str, template: str = "", grid_tier: str = "") -> RobustDurationPredictor | None:
        return self.buckets.get(tier_key(solver, template, grid_tier))

    # -- prediction -----------------------------------------------------------
    def predict(self, sample: DurationSample | None = None, /, **kwargs: Any) -> DurationPrediction:
        """分档预测（桶命中 → 回退全局 → unknown，见类 docstring）。"""
        if sample is None:
            sample = DurationSample(**kwargs)
        if not isinstance(sample, DurationSample):
            raise TypeError(f"expected DurationSample, got {type(sample).__name__}")
        key = tier_key(sample.solver, sample.template, sample.grid_tier)
        label = tier_label(key)
        bucket = self.buckets.get(key)

        if bucket is not None and bucket.status != STATUS_UNKNOWN:
            hit = bucket.predict(sample)
            return DurationPrediction(
                status=hit.status,
                predicted_s=hit.predicted_s,
                upper_bound_s=hit.upper_bound_s,
                n_samples=hit.n_samples,
                loo_mean_rel_error=hit.loo_mean_rel_error,
                loo_max_rel_error=hit.loo_max_rel_error,
                reason=f"桶 {label} 命中：{hit.reason}",
                bucket=label,
                bucket_status=hit.status,
                fallback="",
            )

        if bucket is None:
            bucket_status = "missing"
            head = f"桶 {label} 无样本；"
        else:
            bucket_status = STATUS_UNKNOWN
            head = (
                f"桶 {label} 不可信（n={bucket.n_samples} < min_samples="
                f"{bucket.min_samples}）；"
                if bucket.base is None
                else f"桶 {label} 不可信（LOO max {bucket.loo_max!r} > "
                     f"{bucket.max_trusted_loo_error:g}）；"
            )

        global_predictor = self.global_predictor
        if global_predictor.status != STATUS_UNKNOWN:
            hit = global_predictor.predict(sample)
            return DurationPrediction(
                status=hit.status,
                predicted_s=hit.predicted_s,
                upper_bound_s=hit.upper_bound_s,
                n_samples=hit.n_samples,
                loo_mean_rel_error=hit.loo_mean_rel_error,
                loo_max_rel_error=hit.loo_max_rel_error,
                reason=f"{head}回退全局档：{hit.reason}",
                bucket=label,
                bucket_status=bucket_status,
                fallback=FALLBACK_GLOBAL,
            )

        bound = bucket.conservative_unknown_bound_s() if bucket is not None else None
        if bound is None:
            bound = global_predictor.conservative_unknown_bound_s()
        n_samples = bucket.n_samples if bucket is not None else global_predictor.n_samples
        loo_mean = bucket.loo_mean if bucket is not None else global_predictor.loo_mean
        loo_max = bucket.loo_max if bucket is not None else global_predictor.loo_max
        return DurationPrediction(
            status=STATUS_UNKNOWN,
            predicted_s=None,
            upper_bound_s=bound,
            n_samples=n_samples,
            loo_mean_rel_error=loo_mean,
            loo_max_rel_error=loo_max,
            reason=(
                f"{head}全局档亦不可信（n={global_predictor.n_samples}）；"
                "声明 unknown，不给点估计"
                + ("" if bound is None else f"，保守上界 {bound:g}s")
            ),
            bucket=label,
            bucket_status=bucket_status,
            fallback=FALLBACK_NONE,
        )

    def _feature_pool(self, key: tuple[str, str, str]) -> list[DurationSample]:
        bucket = self.buckets.get(key)
        if bucket is not None and bucket.samples:
            return list(bucket.samples)
        return list(self.global_predictor.samples)

    def predict_for_tier(
        self,
        solver: str,
        template: str = "",
        grid_tier: str = "",
        *,
        features: dict[str, float] | None = None,
    ) -> DurationPrediction:
        """只知道分档（不知几何特征）的作业预测——调度器消费入口。

        缺失的特征取**桶内样本逐特征中位数**（桶无样本则取全局样本；
        全无样本时取 1.0 占位，此时 status 必为 unknown）；显式给出的
        ``features`` 优先。声明规则，确定性、可审计。
        """
        key = tier_key(solver, template, grid_tier)
        pool = self._feature_pool(key)
        given = dict(features or {})
        values: dict[str, float] = {}
        for name in DURATION_FEATURES:
            if name in given:
                values[name] = float(given[name])
            elif pool:
                values[name] = float(statistics.median(
                    float(s.feature(name)) for s in pool))
            else:
                values[name] = 1.0
        sample = DurationSample(
            mesh_mm=values["mesh_mm"],
            domain_volume_mm3=values["domain_volume_mm3"],
            n_excitations=max(1, round(values["n_excitations"])),
            solver=str(solver),
            template=str(template),
            grid_tier=str(grid_tier),
        )
        return self.predict(sample)

    # -- summary / JSON ---------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        """JSON-able：每桶 status/n/LOO + 全局档 + 门参数。"""
        return {
            "n_samples": self.n_samples,
            "n_buckets": len(self.buckets),
            "gates": {
                "min_samples": self.min_samples,
                "max_trusted_loo_error": self.max_trusted_loo_error,
                "unknown_bound_multiple": self.unknown_bound_multiple,
                "mesh_power": self.mesh_power,
                "n_exc_power": self.n_exc_power,
            },
            "buckets": {
                tier_label(key): predictor.summary()
                for key, predictor in self.buckets.items()
            },
            "global": self.global_predictor.summary(),
        }

    def to_json(self, *, indent: int = 2) -> str:
        """序列化样本 + 门参数（反序列化重拟合，逐位一致）。"""
        payload = {
            "version": 1,
            "mesh_power": self.mesh_power,
            "n_exc_power": self.n_exc_power,
            "min_samples": self.min_samples,
            "max_trusted_loo_error": self.max_trusted_loo_error,
            "unknown_bound_multiple": self.unknown_bound_multiple,
            "samples": [_sample_to_dict(s) for s in self.global_predictor.samples],
        }
        return json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, data: str | bytes | dict[str, Any]) -> TieredDurationPredictor:
        """Rebuild from :meth:`to_json` output（重拟合逐位一致）。

        增量样本字段（nrts_limit/stop_reason）additive 兼容：旧 payload
        缺键按缺省装载、新 payload 的键被旧读取方忽略，version 保持 1。
        """
        payload = json.loads(data) if isinstance(data, (str, bytes)) else data
        if payload.get("version") != 1:
            raise ValueError(
                f"unsupported tiered predictor version: {payload.get('version')!r}")
        samples = [_sample_from_dict(row) for row in payload.get("samples", [])]
        return cls.fit(
            samples,
            float(payload.get("mesh_power", DEFAULT_MESH_POWER)),
            float(payload.get("n_exc_power", 1.0)),
            min_samples=int(payload.get("min_samples", MIN_CALIBRATION_SAMPLES)),
            max_trusted_loo_error=float(
                payload.get("max_trusted_loo_error", MAX_TRUSTED_LOO_ERROR)),
            unknown_bound_multiple=float(
                payload.get("unknown_bound_multiple", UNKNOWN_BOUND_MULTIPLE)),
        )


def budget_admission_gate(
    budgets: BudgetLimits,
    ledger: CostLedger,
    predictor: TieredDurationPredictor,
    *,
    kind: str = "wall_hours",
) -> Any:
    """构造调度器可消费的预算准入门：``gate(job_doc) -> 决策 dict``。

    ``job_doc`` 需含 ``solver``，可选 ``template`` / ``grid_tier`` /
    ``features``（几何特征字典，缺省走桶内中位数）。返回
    :meth:`BudgetLimits.admit` 的 JSON 决策并附 ``prediction`` 快照。
    纯函数闭包：账本快照在每次调用时读取（作业陆续入账后剩余预算随之收紧）。
    """

    def gate(job_doc: dict[str, Any]) -> dict[str, Any]:
        prediction = predictor.predict_for_tier(
            str(job_doc.get("solver", "")),
            str(job_doc.get("template", "")),
            str(job_doc.get("grid_tier", "")),
            features=job_doc.get("features"),
        )
        decision = budgets.admit(ledger, prediction, kind=kind)
        decision["prediction"] = prediction.to_dict()
        decision["job_id"] = job_doc.get("job_id")
        return decision

    return gate

