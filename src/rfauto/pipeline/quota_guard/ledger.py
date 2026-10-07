"""G14 编排成本账本 + 预算门（AU-1 b4 自 quota_guard.py 机械拆分；函数体逐字节未动）。

CostLedger 四类成本（LLM tokens/solve_s/seat_hours/gpu_hours + 货币 cost）
按 batch/actor 记账；BudgetLimits 兑成 STOP 门与作业级准入 admit()。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .legacy import QuotaExceededError

if TYPE_CHECKING:  # 仅 admit() 注解引用（惰性求值，零运行时依赖）
    from .robust import DurationPrediction


# ---------------------------------------------------------------------------
# G14 — orchestration cost ledger + budget gate
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
    """Raised when a G14 orchestration budget is exceeded -> STOP.

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
    """Per-batch / per-actor orchestration cost ledger (G14).

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
    """G14 budget gate — any None field means "no limit".

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

    # -- W2⑦④ 作业级预算准入（消费分档时长预测） ------------------------------
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
