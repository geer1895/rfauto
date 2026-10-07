"""Quota and orchestration-cost guard for the rfauto pipeline.

Two layers live here:

* :class:'QuotaGuard' / :class:'QuotaLimits' — the legacy P2 guard that caps
  trial count and wall-clock hours.
* G14 orchestration costing — :class:'CostLedger' records four cost classes
  (LLM tokens, solver machine time 'solve_s', license seat-hours, optional
  GPU hours) per batch/actor; :class:'BudgetLimits' turns those into a STOP
  gate (:class:'BudgetExceededError'); :class:'DurationPredictor' is a
  deterministic log-linear model that estimates a single openEMS solve from
  recipe-level features (mesh size / domain volume / excitations / points).
  0-P2⑱ adds an opt-in stop-mechanism feature plane
  (:data:`DURATION_FEATURES_V2`: declared NrTS step cap + measured stop reason
  one-hot/interaction) so energy-stop and NrTS-cap-stop solves can be
  separated — the stop-reason mixing that pinned the ratrace LOO floor at
  ~80% .

Everything here is deterministic, pure Python (numpy is used only for the
least-squares fit of DurationPredictor); no network, no solver calls, no
wall-clock reads outside the legacy QuotaGuard.check_wall_time.
"""

# ══ AU-1 巨石拆分·批4 facade（2026-09-30）═══════════════════════
# 本文件原为 1327 行巨石，实现拆分至 pipeline/quota_guard/ 包（legacy/
# ledger/sample/loglinear/offset_power/robust/tiered，四代预测器按代拆）。
# 此处逐名显式 re-export 全部模块级名（公开面快照钉：拆分前后 dir()
# 逐名相等；redundant-alias=PEP 484 显式 re-export 惯例）。
#
# 一代 QuotaGuard 已标 deprecated（docstring 注记，行为零变化）；时长
# 预测新代码用四代 TieredDurationPredictor / budget_admission_gate。

from __future__ import annotations

import json as json  # facade：保持原模块公开面（快照钉）
import math as math
import statistics as statistics
import time as time
from dataclasses import dataclass as dataclass
from typing import Any as Any

import numpy as np  # noqa: F401  # 实名 alias 非 re-export 形态

from .ledger import (
    LEDGER_FIELDS as LEDGER_FIELDS,
)
from .ledger import (
    BudgetExceededError as BudgetExceededError,
)
from .ledger import (
    BudgetLimits as BudgetLimits,
)
from .ledger import (
    CostLedger as CostLedger,
)
from .ledger import (
    _row_with_totals as _row_with_totals,
)
from .ledger import (
    _zero_row as _zero_row,
)
from .legacy import (
    QuotaExceededError as QuotaExceededError,
)
from .legacy import (
    QuotaGuard as QuotaGuard,
)
from .legacy import (
    QuotaLimits as QuotaLimits,
)
from .loglinear import (
    DurationPredictor as DurationPredictor,
)
from .offset_power import (
    DEFAULT_MESH_POWER as DEFAULT_MESH_POWER,
)
from .offset_power import (
    OffsetPowerDurationPredictor as OffsetPowerDurationPredictor,
)
from .robust import (
    MAX_TRUSTED_LOO_ERROR as MAX_TRUSTED_LOO_ERROR,
)
from .robust import (
    MIN_CALIBRATION_SAMPLES as MIN_CALIBRATION_SAMPLES,
)
from .robust import (
    STATUS_CALIBRATED as STATUS_CALIBRATED,
)
from .robust import (
    STATUS_EXTRAPOLATED as STATUS_EXTRAPOLATED,
)
from .robust import (
    STATUS_UNKNOWN as STATUS_UNKNOWN,
)
from .robust import (
    UNKNOWN_BOUND_MULTIPLE as UNKNOWN_BOUND_MULTIPLE,
)
from .robust import (
    DurationPrediction as DurationPrediction,
)
from .robust import (
    RobustDurationPredictor as RobustDurationPredictor,
)
from .sample import (
    DURATION_FEATURES as DURATION_FEATURES,
)
from .sample import (
    DURATION_FEATURES_V2 as DURATION_FEATURES_V2,
)
from .sample import (
    STOP_ONEHOT_LEVEL as STOP_ONEHOT_LEVEL,
)
from .sample import (
    STOP_REASON_ENERGY as STOP_REASON_ENERGY,
)
from .sample import (
    STOP_REASON_NRTS_CAP as STOP_REASON_NRTS_CAP,
)
from .sample import (
    STOP_REASON_TIMEOUT as STOP_REASON_TIMEOUT,
)
from .sample import (
    STOP_REASONS as STOP_REASONS,
)
from .sample import (
    DurationSample as DurationSample,
)
from .tiered import (
    FALLBACK_GLOBAL as FALLBACK_GLOBAL,
)
from .tiered import (
    FALLBACK_NONE as FALLBACK_NONE,
)
from .tiered import (
    TIER_FIELDS as TIER_FIELDS,
)
from .tiered import (
    TIER_LABEL_SEP as TIER_LABEL_SEP,
)
from .tiered import (
    TieredDurationPredictor as TieredDurationPredictor,
)
from .tiered import (
    _sample_from_dict as _sample_from_dict,
)
from .tiered import (
    _sample_to_dict as _sample_to_dict,
)
from .tiered import (
    budget_admission_gate as budget_admission_gate,
)
from .tiered import (
    tier_key as tier_key,
)
from .tiered import (
    tier_label as tier_label,
)
