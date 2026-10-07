"""四代b·分档时长预测 + 作业级预算准入（AU-1 b4 机械拆分；函数体逐字节未动）。

W2⑦④：按 (adapter × 模板族 × 网格档) 分桶各自拟合四代a 稳健预测器，
另拟合全局档作回退；budget_admission_gate 构造调度器可消费的准入门。
"""

from __future__ import annotations

import json
import statistics
from typing import TYPE_CHECKING, Any

from .offset_power import DEFAULT_MESH_POWER
from .robust import (
    MAX_TRUSTED_LOO_ERROR,
    MIN_CALIBRATION_SAMPLES,
    STATUS_UNKNOWN,
    UNKNOWN_BOUND_MULTIPLE,
    DurationPrediction,
    RobustDurationPredictor,
)
from .sample import DURATION_FEATURES, DurationSample

if TYPE_CHECKING:  # 仅 budget_admission_gate 注解引用（惰性求值）
    from .ledger import BudgetLimits, CostLedger


# ---------------------------------------------------------------------------
# W2⑦④ — 分档（adapter × 模板族 × 网格档）时长预测 + 作业级预算准入
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
        # 0-P2⑱ 增量字段：旧 payload 缺键按缺省装载（0=未申报 / ""=未申报），
        # 显式 null 同样落缺省（`or 0`/`or ""` 只做缺省回填，非 #117 容器陷阱）。
        nrts_limit=int(row.get("nrts_limit") or 0),
        stop_reason=str(row.get("stop_reason") or ""),
    )


class TieredDurationPredictor:
    """按 (adapter × 模板族 × 网格档) 分桶的稳健时长预测器（W2⑦④）。

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

        0-P2⑱ 增量样本字段（nrts_limit/stop_reason）additive 兼容：旧 payload
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
