"""时长样本与特征平面（AU-1 b4 自 quota_guard.py 机械拆分；函数体逐字节未动）。

二代 v1 特征集（DURATION_FEATURES）与 0-P2⑱ 停机机制特征面
（DURATION_FEATURES_V2：声明 NrTS 上限 + 实测停机原因 one-hot/交互项），
统一经 DurationSample.feature() 派生（v2 派生名优先于同名字段）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# G14 — deterministic single-solve duration predictor (feeds G13 scheduling)
# ---------------------------------------------------------------------------

#: Default log-linear feature set. All features are known before a solve from
#: the recipe/openEMS template and must be strictly positive.
DURATION_FEATURES: tuple[str, ...] = (
    "mesh_mm",
    "domain_volume_mm3",
    "n_excitations",
)

# -- 0-P2⑱ 停机机制特征（stop-mechanism feature plane, opt-in） ----------------
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
    #: 0.0（缺省）= "未申报" 哨兵——预测查询样本（predict(mesh_mm=...) 等
    #: kwargs 构造路径）合法保留；**拟合/评估消费点必须先过 solve_s>0 严格
    #: 校验**（见 RobustDurationPredictor.fit 守卫，S-1 C-02 2026-10-04：
    #: 此前 0/负值样本直穿 loo_relative_errors 的 `/solve_s` 除法=
    #: ZeroDivisionError 裸炸）。
    solve_s: float = 0.0
    domain_volume_mm3: float = 1.0
    n_excitations: int = 1
    freq_points: int = 1
    solver: str = "openems"
    source: str = ""
    #: W2⑦④ 分档维度：模板族与网格档（空串=未申报，全部落同一个"未申报"桶，
    #: 与既有样本向后兼容）。
    template: str = ""
    grid_tier: str = ""
    #: 0-P2⑱ 停机机制面：声明 NrTS 步数上限（0 = 未申报/旧样本缺省）。
    nrts_limit: int = 0
    #: 实测停机原因枚举（energy/nrts_cap/timeout；"" = 未申报/旧样本缺省；
    #: 未识别值在特征解析层按未申报处理）。
    stop_reason: str = ""

    def __post_init__(self) -> None:
        """构造期形状校验（S-1 C-02 2026-10-04）。

        solve_s 只允许两种形态：0.0（未申报哨兵，预测查询合法）或严格正
        且有限（实测值）；负值/NaN/±inf 一律 ValueError（带 source 上下文，
        不带病灶样本静默进拟合集）。严格 solve_s>0 的**拟合期**校验在
        :meth:`RobustDurationPredictor.fit`（哨兵在此层不可豁免）。
        """
        value = float(self.solve_s)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(
                f"solve_s 必须为 0（未申报哨兵）或严格正有限值，got {value!r}"
                f" (source={self.source!r})"
            )

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
