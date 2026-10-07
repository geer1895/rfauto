"""一代·P2 配额守卫（AU-1 b4 自 quota_guard.py 机械拆分；函数体逐字节未动）。

QuotaGuard/QuotaLimits 为最早一代配额面（trial 数 + 墙钟小时硬上限）；
时长预测能力已按代演进至本包 loglinear（二代）/offset_power（三代）/
robust+tiered（四代）子模块。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅注解引用（future annotations 惰性求值，零运行时依赖）
    from .ledger import BudgetLimits, CostLedger


@dataclass
class QuotaLimits:
    """Defines quota limits for a pipeline run."""
    max_trials: int = 100
    max_wall_hours: float = 24.0


class QuotaGuard:
    """Enforces quota limits on trial count and wall time.

    .. deprecated::
        一代配额守卫（AU-1 b4 注记）：时长预测能力已按代演进至本包
        loglinear（二代）/offset_power（三代）/robust+tiered（四代）；
        新代码时长/预算裁决用 ``TieredDurationPredictor`` 与
        ``budget_admission_gate``。本类仅承担 trial 数/墙钟配额强制，
        行为零变化、无弃用警告。

    Usage:
        guard = QuotaGuard(QuotaLimits(max_trials=50, max_wall_hours=8.0))
        guard.check_trial(trial_count)  # raises if exceeded
        guard.check_wall_time(start_time)  # raises if exceeded
    """

    def __init__(self, limits: QuotaLimits | None = None,
                 budgets: BudgetLimits | None = None) -> None:
        self.limits = limits or QuotaLimits()
        # G14 optional extension: an attached cost budget gate. None keeps the
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
        """Check the G14 cost ledger against the attached budgets (STOP gate)."""
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
