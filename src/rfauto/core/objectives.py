"""指标 DSL 与可信度校验（§7.5）。

指标 DSL 示例（Recipe 中的 objectives 字段）：
    objectives:
      - metric: s11_db
        band: [2.35, 2.45]      # GHz 区间
        op: max_below            # 该区间最大值须低于 value
        value: -15
        weight: 1.0

SpecEvaluator 两级校验：
1. 数值正确性：无源性（|S|≤1）、互易性
2. 物理合理性 sanity_check()：谐振频率、带外趋势、插损量级
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

# 避免顶层 import skrf——SpecEvaluator 方法内按需导入


class MetricOp(str, Enum):
    """指标操作符。"""
    MAX_BELOW = "max_below"          # 区间最大值 ≤ value
    MIN_ABOVE = "min_above"          # 区间最小值 ≥ value
    MEAN_WITHIN = "mean_within"      # 区间均值在 [value_low, value_high]
    BANDWIDTH = "bandwidth"          # 满足条件的带宽 ≥ value


class Objective(BaseModel):
    """单个优化目标。"""
    metric: str = Field(..., description="指标名：s11_db/s21_db/group_delay_ns/zin_re/bw_ghz/iso_s23_db/eps_eff 等")
    band: list[float] = Field(default_factory=list, description="频率区间 [f_low, f_high] GHz")
    op: MetricOp = Field(default=MetricOp.MAX_BELOW)
    value: float | list[float] = Field(default=0.0, description="阈值或区间")
    weight: float = Field(default=1.0, ge=0.0, description="权重")
    length_mm: float | None = Field(
        default=None, ge=0.0,
        description="均匀线物理长度 mm（仅 eps_eff 指标必需：εeff 由 S21 相位斜率/长度提取）",
    )


class QuotaLimits(BaseModel):
    """配额护栏（§8.6）。"""
    max_trials: int = Field(default=60, ge=1)
    max_wall_hours: float = Field(default=12.0, gt=0.0)


# 裸指标名 → compute_metrics 默认产物键（tolerance/uq 等规格推导共用）。
# s11_db 双变体并存：裸名取 max（worst-case 惯例），显式 _min/_max 后缀
# 取对应变体（#195 谷深语义）。新增指标分支时同步维护本表。
DEFAULT_METRIC_KEY: dict[str, str] = {
    "s11_db": "s11_db_max_in_band",
    "s11_db_min": "s11_db_min_in_band",
    "s11_db_max": "s11_db_max_in_band",
    "s21_db": "s21_db_mean_in_band",
    "iso_s23_db": "iso_s23_db_min_in_band",
    "eps_eff": "eps_eff_mean_in_band",
}


class SanityCheckResult(BaseModel):
    """物理合理性校验结果。"""
    resonance_near_target: bool = Field(default=True, description="谐振频率是否接近设计目标")
    oob_trend_ok: bool = Field(default=True, description="带外抑制趋势是否合理")
    insertion_loss_reasonable: bool = Field(default=True, description="插损量级是否合理")
    notes: list[str] = Field(default_factory=list, description="可疑项说明")

    @property
    def all_ok(self) -> bool:
        return self.resonance_near_target and self.oob_trend_ok and self.insertion_loss_reasonable


class SpecEvaluator:
    """指标评估器——从 skrf.Network 计算指标、做两级校验。

    所有指标计算在本地用 skrf 完成，不回 HFSS 报告取数。
    """

    @staticmethod
    def extract_band(network: Any, f_low_ghz: float, f_high_ghz: float) -> Any:
        """提取指定频段的子网络。"""
        freq = network.frequency.f * 1e-9  # Hz → GHz
        mask = (freq >= f_low_ghz) & (freq <= f_high_ghz)
        return network[mask]

    @staticmethod
    def s11_db(network: Any, f_low_ghz: float = 0.0, f_high_ghz: float = float("inf")) -> float:
        """S11 在指定频段的最大值 (dB)。"""
        sub = SpecEvaluator.extract_band(network, f_low_ghz, f_high_ghz) if f_low_ghz > 0 else network
        s11 = sub.s[:, 0, 0]
        return float(np.max(20 * np.log10(np.abs(s11) + 1e-30)))

    @staticmethod
    def s21_db(network: Any, f_low_ghz: float = 0.0, f_high_ghz: float = float("inf")) -> float:
        """S21 在指定频段的均值 (dB)。"""
        sub = SpecEvaluator.extract_band(network, f_low_ghz, f_high_ghz) if f_low_ghz > 0 else network
        s21 = sub.s[:, 1, 0] if sub.s.shape[1] > 1 else sub.s[:, 0, 0]
        return float(np.mean(20 * np.log10(np.abs(s21) + 1e-30)))

    @staticmethod
    def s_param_db(network: Any, i: int, j: int, f_low_ghz: float = 0.0, f_high_ghz: float = float("inf")) -> float:
        """Sij 在指定频段的最大 dB 值。"""
        sub = SpecEvaluator.extract_band(network, f_low_ghz, f_high_ghz) if f_low_ghz > 0 else network
        sij = sub.s[:, i, j]
        return float(np.max(20 * np.log10(np.abs(sij) + 1e-30)))

    @staticmethod
    def bandwidth_ghz(network: Any, port_i: int, port_j: int, threshold_db: float,
                      f_low_ghz: float = 0.0, f_high_ghz: float = float("inf")) -> float:
        """计算 Sij 低于 threshold_db 的带宽 (GHz)。"""
        sub = SpecEvaluator.extract_band(network, f_low_ghz, f_high_ghz) if f_low_ghz > 0 else network
        freq_ghz = sub.frequency.f * 1e-9
        sij_db = 20 * np.log10(np.abs(sub.s[:, port_i, port_j]) + 1e-30)
        mask = sij_db < threshold_db
        if not np.any(mask):
            return 0.0
        return float(freq_ghz[mask][-1] - freq_ghz[mask][0])

    #: εeff 相位斜率法的匹配前提：带内 max|S11|dB 超过该值视为驻波污染
    #: （#255 家族：|Γ|≈0.3 时线性相位斜率偏 +10.7%），如实跳过不产出。
    _EPS_EFF_MAX_S11_DB: float = -10.0

    @staticmethod
    def eps_eff_band_average(
        network: Any,
        f_low_ghz: float,
        f_high_ghz: float,
        length_mm: float | None,
    ) -> float | None:
        """均匀线 εeff 提取（S21 解缠相位斜率口径；mline/cpw 锚模板语义）。

        εeff = (τ·c/L)²，τ = -slope(unwrap∠S21 对 f 线性拟合)/(2π) 为带内
        平均群时延。**斜率口径**（而非逐频 |φ| 口径）：对端口参考面相位
        偏移与主值卷绕不敏感——带内电长度超过 π 时逐频绝对相位会差整数倍
        主值，斜率不受影响。

        前提与诚实跳过（返回 None，不产出键，与端口数不足同口径——不凑数）：
        - length_mm 缺失/非正（网络不携带几何，长度必须由 objective 显式给）；
        - 带内频点 <3（斜率不可辨识）或网络 <2 端口；
        - 带内 max|S11|dB > -10（驻波相位纹波污染斜率，#255 家族）；
        - 拟合斜率非负（穿通线相位必随频率下降，非负=数据非均匀线口径）。

        数值口径：中心化最小二乘斜率（协方差式），频率用 GHz——避免对
        Hz 量级频率直接 polyfit 的条件数劣化。
        """
        if length_mm is None or float(length_mm) <= 0.0:
            return None
        sub = SpecEvaluator.extract_band(network, f_low_ghz, f_high_ghz) if f_low_ghz > 0 else network
        if sub.s.shape[1] < 2:
            return None
        f_ghz = np.asarray(sub.frequency.f, dtype=float) / 1e9
        if len(f_ghz) < 3:
            return None
        s11_db = 20 * np.log10(np.abs(sub.s[:, 0, 0]) + 1e-30)
        if float(np.max(s11_db)) > SpecEvaluator._EPS_EFF_MAX_S11_DB:
            return None
        phase = np.unwrap(np.angle(sub.s[:, 1, 0]))
        df = f_ghz - f_ghz.mean()
        denom = float(np.sum(df * df))
        if denom <= 0.0:
            return None
        slope = float(np.sum(df * (phase - phase.mean()))) / denom  # rad/GHz
        if slope >= 0.0:
            return None
        tau_s = -slope / (2.0 * np.pi) / 1e9
        length_m = float(length_mm) * 1e-3
        return float((tau_s * 299792458.0 / length_m) ** 2)

    @staticmethod
    def compute_metrics(
        network: Any,
        objectives: list[Objective],
        far_field: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """根据目标列表计算所有指标，返回 {metric_name: value}。

        端口数不足的指标会被跳过（如 2 端口网络无法计算 iso_s23_db）。

        far_field（缺口清理：远场指标进 DSL）：objective.metric == "gain_db"
        时需传入 adapter.get_far_field() 的返回值 {theta, gain_db, ...}，
        计算 broadside 附近最大增益 (dB)；未提供时该指标跳过。
        """
        results: dict[str, float] = {}
        n_ports = network.s.shape[1]
        for obj in objectives:
            f_low = obj.band[0] if len(obj.band) > 0 else 0.0
            f_high = obj.band[1] if len(obj.band) > 1 else float("inf")

            if obj.metric == "gain_db":
                if far_field and far_field.get("gain_db"):
                    results["gain_db_max"] = float(np.max(far_field["gain_db"]))
                # 无远场数据时静默跳过（与端口数不足的处理一致）
            elif obj.metric in ("s11_db", "s11_db_min", "s11_db_max"):
                # 带内包络（max）与谷深（min）双变体恒产出（#195）：
                # 窄带谐振器件带内 max≈0dB 是常数陷阱，谷深语义必须走
                # s11_db_min_in_band（显式统计量指标名，见 metric_key_candidates）
                sub = SpecEvaluator.extract_band(network, f_low, f_high) if f_low > 0 else network
                curve = 20 * np.log10(np.abs(sub.s[:, 0, 0]) + 1e-30)
                results["s11_db_max_in_band"] = float(np.max(curve))
                results["s11_db_min_in_band"] = float(np.min(curve))
            elif obj.metric == "s21_db":
                results["s21_db_mean_in_band"] = SpecEvaluator.s21_db(network, f_low, f_high)
            elif obj.metric == "iso_s23_db":
                if n_ports >= 3:
                    # 注意：s_param_db 为 0 基索引；iso_s23 工程记号 S23(1 基) → 0 基 (1,2)
                    results["iso_s23_db_min_in_band"] = -SpecEvaluator.s_param_db(network, 1, 2, f_low, f_high)
                # 2 端口网络无隔离度指标，静默跳过
            elif obj.metric == "bw_ghz_s11_lt_-10":
                results["bw_ghz_s11_lt_-10"] = SpecEvaluator.bandwidth_ghz(network, 0, 0, -10.0, f_low, f_high)
            elif obj.metric == "eps_eff":
                # 均匀线 εeff（带内平均，相位斜率口径）：前提不满足时如实
                # 跳过不产出键（见 eps_eff_band_average），evaluate_objectives
                # 对缺失指标不惩罚——与端口数不足同口径，不凑数
                eps = SpecEvaluator.eps_eff_band_average(network, f_low, f_high, obj.length_mm)
                if eps is not None:
                    results["eps_eff_mean_in_band"] = eps
            else:
                results[obj.metric] = SpecEvaluator.s_param_db(network, 0, 0, f_low, f_high)
        return results

    @staticmethod
    def metric_key_candidates(metric: str, op: MetricOp | str) -> list[str]:
        """objective → metrics dict 候选键（按 op 排序，#195）。

        compute_metrics 产物约定：{metric}_max_in_band / {metric}_min_in_band
        / {metric}_mean_in_band。裸指标名的候选顺序由 op 决定，worst-case
        统计量优先：MAX_BELOW/BANDWIDTH → max 先（带内包络），MIN_ABOVE →
        min 先，MEAN_WITHIN → mean 先。显式统计量指标名（s11_db_min /
        s11_db_max，谷深/峰值语义）直接命中对应变体，绕过 op 猜测——
        否则 MAX_BELOW 恒取 max 会把谷深目标架空成常数陷阱（#195，
        patch v1/v2 两轮 47 点 cost 恒定）。
        """
        op_str = op.value if isinstance(op, MetricOp) else str(op)
        if metric.endswith(("_min", "_max")):
            return [f"{metric}_in_band", metric]
        order: tuple[str, ...] = ("max", "mean", "min")
        if op_str == MetricOp.MIN_ABOVE.value:
            order = ("min", "mean", "max")
        elif op_str == MetricOp.MEAN_WITHIN.value:
            order = ("mean", "max", "min")
        return [f"{metric}_{s}_in_band" for s in order] + [metric]

    @staticmethod
    def evaluate_objectives(metrics: dict[str, float], objectives: list[Objective]) -> float:
        """计算加权 cost（越小越好）。用于 Optuna 目标函数。"""
        cost = 0.0
        for obj in objectives:
            # 映射 metric 名到 metrics dict 的 key（候选按 op 排序，#195）
            val = None
            for k in SpecEvaluator.metric_key_candidates(obj.metric, obj.op):
                if k in metrics:
                    val = metrics[k]
                    break
            if val is None:
                continue

            if obj.op == MetricOp.MAX_BELOW:
                # val 应 ≤ value；超出部分按 weight 惩罚
                threshold = obj.value if isinstance(obj.value, (int, float)) else obj.value[0]
                violation = max(0.0, val - threshold)
                cost += obj.weight * violation
            elif obj.op == MetricOp.MIN_ABOVE:
                threshold = obj.value if isinstance(obj.value, (int, float)) else obj.value[0]
                violation = max(0.0, threshold - val)
                cost += obj.weight * violation
            elif obj.op == MetricOp.MEAN_WITHIN:
                if isinstance(obj.value, list) and len(obj.value) == 2:
                    low, high = obj.value
                    if val < low:
                        cost += obj.weight * (low - val)
                    elif val > high:
                        cost += obj.weight * (val - high)
            elif obj.op == MetricOp.BANDWIDTH:
                # 带宽目标：val（实测带宽）应 ≥ value（要求带宽），不足部分惩罚。
                # （历史缺陷：原先该操作符无分支，带宽目标静默不生效。）
                threshold = obj.value if isinstance(obj.value, (int, float)) else obj.value[0]
                violation = max(0.0, threshold - val)
                cost += obj.weight * violation
        return cost

    @staticmethod
    def check_passivity(network: Any) -> bool:
        """无源性校验：|S| ≤ 1（含容差）。"""
        max_s = np.max(np.abs(network.s))
        return bool(max_s <= 1.01)  # 1% 容差

    @staticmethod
    def check_reciprocity(network: Any) -> bool:
        """互易性校验：|Sij - Sji| < epsilon。"""
        if network.s.shape[1] < 2:
            return True
        diff = np.abs(network.s[:, 0, 1] - network.s[:, 1, 0])
        return bool(np.max(diff) < 0.01)

    @staticmethod
    def sanity_check(network: Any, objectives: list[Objective], f0_ghz: float | None = None) -> SanityCheckResult:
        """物理合理性校验（§7.5）——数值上自洽但物理上荒谬的结果必须被拦下。"""
        notes: list[str] = []
        result = SanityCheckResult()

        # 1. 谐振频率是否接近设计目标
        if f0_ghz is not None:
            freq_ghz = network.frequency.f * 1e-9
            s11_db = 20 * np.log10(np.abs(network.s[:, 0, 0]) + 1e-30)
            min_idx = np.argmin(s11_db)
            actual_f0 = freq_ghz[min_idx]
            deviation = abs(actual_f0 - f0_ghz) / f0_ghz
            if deviation > 0.3:
                result.resonance_near_target = False
                notes.append(f"谐振频率偏差 {deviation*100:.1f}%: 设计 {f0_ghz} GHz, 实际 {actual_f0:.3f} GHz")

        # 2. 带外抑制趋势
        freq_ghz = network.frequency.f * 1e-9
        if len(freq_ghz) > 10 and network.s.shape[1] >= 2:
            s21_db = 20 * np.log10(np.abs(network.s[:, -1, 0]) + 1e-30)
            # 带外（高频端）应有下降趋势
            tail = s21_db[-len(s21_db)//4:]
            if len(tail) > 1 and tail[-1] > tail[0] + 3.0:
                result.oob_trend_ok = False
                notes.append("高频端 S21 不降反升，可能端口/边界设置有误")

        # 3. 插损量级
        if network.s.shape[1] >= 2:
            s21_mean = float(np.mean(20 * np.log10(np.abs(network.s[:, 1, 0]) + 1e-30)))
            if s21_mean > 0.5:
                result.insertion_loss_reasonable = False
                notes.append(f"均值 S21={s21_mean:.2f} dB > 0 dB，物理上不可能（无源网络）")
            elif s21_mean < -30:
                result.insertion_loss_reasonable = False
                notes.append(f"均值 S21={s21_mean:.2f} dB，插损异常大，检查端口设置")

        result.notes = notes
        return result
