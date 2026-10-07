"""E8c 链路预算引擎（扩展方案 §E8c）。

Friis 噪声级联自实现（<50行；skrf 无内置且其 NF 分析与 ADS 不符，issue #538）。
对拍基准为 Friis 手算（可复现零 license），非 ADS GUI。

用法：
    from rfauto.core.budget import LinkBudget
    budget = LinkBudget()
    budget.add_stage("LNA", gain_db=20, nf_db=0.8)
    budget.add_stage("Filter", gain_db=-2, nf_db=2)
    budget.add_stage("Mixer", gain_db=-7, nf_db=7)
    result = budget.compute()
    print(result.cascade_nf_db, result.cascade_gain_db)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class StageResult:
    """单级结果。"""
    name: str
    gain_db: float
    nf_db: float
    cumulative_gain_db: float
    cumulative_nf_db: float
    p1db_dbm: float | None = None
    # P2 IP3 级联（逐级；无 oip3 级为 None）
    oip3_dbm: float | None = None
    cumulative_iip3_dbm: float | None = None
    cumulative_oip3_dbm: float | None = None
    # B5 IIP2 损伤预算统一面（逐级；无 IP2 级为 None）
    iip2_dbm: float | None = None
    oip2_dbm: float | None = None
    cumulative_iip2_dbm: float | None = None
    cumulative_oip2_dbm: float | None = None


@dataclass
class BudgetResult:
    """链路预算结果。"""
    stages: list[StageResult]
    cascade_gain_db: float
    cascade_nf_db: float
    cascade_p1db_dbm: float | None
    cascade_iip3_dbm: float | None = None
    cascade_oip3_dbm: float | None = None
    # B5 IIP2 损伤预算统一面（盘点依据：docs/audit/plan_gap_inventory_20260928.md
    # §二 B5「IIP2 损伤预算统一面（budget.py 现无 iip2 键）」）
    cascade_iip2_dbm: float | None = None
    cascade_oip2_dbm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": [
                {
                    "name": s.name,
                    "gain_db": round(s.gain_db, 2),
                    "nf_db": round(s.nf_db, 2),
                    "cumulative_gain_db": round(s.cumulative_gain_db, 2),
                    "cumulative_nf_db": round(s.cumulative_nf_db, 2),
                    "p1db_dbm": round(s.p1db_dbm, 2) if s.p1db_dbm is not None else None,
                    "oip3_dbm": round(s.oip3_dbm, 2) if s.oip3_dbm is not None else None,
                    "cumulative_iip3_dbm": (round(s.cumulative_iip3_dbm, 2)
                                            if s.cumulative_iip3_dbm is not None else None),
                    "cumulative_oip3_dbm": (round(s.cumulative_oip3_dbm, 2)
                                            if s.cumulative_oip3_dbm is not None else None),
                    "iip2_dbm": round(s.iip2_dbm, 2) if s.iip2_dbm is not None else None,
                    "oip2_dbm": round(s.oip2_dbm, 2) if s.oip2_dbm is not None else None,
                    "cumulative_iip2_dbm": (round(s.cumulative_iip2_dbm, 2)
                                            if s.cumulative_iip2_dbm is not None else None),
                    "cumulative_oip2_dbm": (round(s.cumulative_oip2_dbm, 2)
                                            if s.cumulative_oip2_dbm is not None else None),
                }
                for s in self.stages
            ],
            "cascade_gain_db": round(self.cascade_gain_db, 2),
            "cascade_nf_db": round(self.cascade_nf_db, 2),
            "cascade_p1db_dbm": round(self.cascade_p1db_dbm, 2) if self.cascade_p1db_dbm is not None else None,
            "cascade_iip3_dbm": round(self.cascade_iip3_dbm, 2) if self.cascade_iip3_dbm is not None else None,
            "cascade_oip3_dbm": round(self.cascade_oip3_dbm, 2) if self.cascade_oip3_dbm is not None else None,
            "cascade_iip2_dbm": (round(self.cascade_iip2_dbm, 2)
                                 if self.cascade_iip2_dbm is not None else None),
            "cascade_oip2_dbm": (round(self.cascade_oip2_dbm, 2)
                                 if self.cascade_oip2_dbm is not None else None),
        }


class LinkBudget:
    """链路预算计算器。

    Friis 噪声级联公式：
    F_total = F1 + (F2-1)/G1 + (F3-1)/(G1*G2) + ...
    其中 F = 10^(NF_dB/10), G = 10^(Gain_dB/10)

    三阶截点级联（P2，功率相加形式；口径：Pozar, Microwave Engineering,
    4th ed., Ch.10 非线性/三阶截点级联一节——本地无纸本可核式号，只引
    章节级不编式号）：

        1/IIP3_tot = Σ_i (Π_{j<i} G_j) / IIP3_i    （线性功率域）

    其中 IIP3_i = OIP3_i − G_i（dBm 域，线性功率差），Π_{j<i} G_j 为
    该级之前全部级的线性功率增益之积；级间无增益时前级损耗同式计入。
    无 oip3 级视为理想透明（IIP3→∞，不进求和）；全链无 oip3 → 级联
    IP3 为 None（不硬造）。OIP3_tot = IIP3_tot + G_tot（恒等式）。

    二阶截点级联（B5 IIP2 损伤预算统一面；盘点依据 docs/audit/
    plan_gap_inventory_20260928.md §二 B5）：同一功率和式取 order=2，

        1/IIP2_tot = Σ_i (Π_{j<i} G_j) / IIP2_i

    iip2_dbm 直接给（混频器/零中频接收机惯例）或 oip2_dbm 给后按
    IIP2_i = OIP2_i − G_i 折算，二选一（双给显式 ValueError）。
    诚实边界：功率和式为**非相干功率和口径**（与 core/cascade.py
    cascade_ipn_merge(order=2) 同口径，交叉一致性钉在
    tests/unit/test_budget_iip2.py）——不建模偶次产物跨级再混频、
    平衡（差分）拓扑的 IM2 抵消（实际 IIP2 可高于此值）。**注意它不是
    经典"最坏情形"**：二阶电压相干相加的最坏上限是 1/√IIP2=Σ√(G/IIP2)
    （review_slice2 P2），恒比本式更保守——做 IM2 最坏情形预算时须
    自行换算，勿直接采信本值。
    """

    def __init__(self) -> None:
        self._stages: list[dict[str, Any]] = []

    def add_stage(
        self,
        name: str,
        gain_db: float,
        nf_db: float,
        p1db_dbm: float | None = None,
        oip3_dbm: float | None = None,
        iip2_dbm: float | None = None,
        oip2_dbm: float | None = None,
    ) -> None:
        """添加级。

        Args:
            name: 级名
            gain_db: 增益 (dB)，负值=损耗
            nf_db: 噪声系数 (dB)
            p1db_dbm: 1dB 压缩点 (dBm)，可选
            oip3_dbm: 输出三阶截点 (dBm)，可选；缺省=理想透明级（不参与
                IP3 级联）
            iip2_dbm: 输入二阶截点 (dBm)，可选（与 oip2_dbm 二选一；
                B5 IIP2 损伤预算统一面——混频器/检波器惯例常给输入参考）
            oip2_dbm: 输出二阶截点 (dBm)，可选（与 iip2_dbm 二选一；
                IIP2_i = OIP2_i − G_i 折算，与 IP3 同口径）
        """
        if oip3_dbm is not None:
            oip3_dbm = float(oip3_dbm)
            if not math.isfinite(oip3_dbm):
                raise ValueError(f"oip3_dbm 必须为有限实数，收到 {oip3_dbm!r}")
        if iip2_dbm is not None and oip2_dbm is not None:
            raise ValueError(
                "iip2_dbm 与 oip2_dbm 只能二选一（另一量由 OIP2=IIP2+G 恒等换算，"
                "双给即歧义）")
        for key, val in (("iip2_dbm", iip2_dbm), ("oip2_dbm", oip2_dbm)):
            if val is not None:
                val = float(val)
                if not math.isfinite(val):
                    raise ValueError(f"{key} 必须为有限实数，收到 {val!r}")
                if key == "iip2_dbm":
                    iip2_dbm = val
                else:
                    oip2_dbm = val
        self._stages.append({
            "name": name,
            "gain_db": gain_db,
            "nf_db": nf_db,
            "p1db_dbm": p1db_dbm,
            "oip3_dbm": oip3_dbm,
            "iip2_dbm": iip2_dbm,
            "oip2_dbm": oip2_dbm,
        })

    def compute(self) -> BudgetResult:
        """计算链路预算。"""
        if not self._stages:
            return BudgetResult(stages=[], cascade_gain_db=0, cascade_nf_db=0,
                                cascade_p1db_dbm=None, cascade_iip3_dbm=None,
                                cascade_oip3_dbm=None)

        stages: list[StageResult] = []
        cumulative_gain_linear = 1.0
        cumulative_noise_factor = 0.0  # Friis: F_total = F1 + (F2-1)/G1 + ...
        # P2 IP3 级联：Σ (Π_{j<i} G_j) / IIP3_i [1/mW]；无 oip3 级跳过
        iip3_inv_sum = 0.0
        has_ip3 = False
        # B5 IIP2 损伤预算：同一幂和式（order=2；与 cascade.cascade_ipn_merge
        # order=2 同口径，交叉一致性见 tests/unit/test_budget_iip2.py）
        iip2_inv_sum = 0.0
        has_ip2 = False

        for i, stage in enumerate(self._stages):
            gain_db = stage["gain_db"]
            nf_db = stage["nf_db"]
            p1db_dbm = stage.get("p1db_dbm")
            oip3_dbm = stage.get("oip3_dbm")
            iip2_dbm = stage.get("iip2_dbm")
            oip2_dbm = stage.get("oip2_dbm")

            # 转换为线性
            gain_linear = 10 ** (gain_db / 10)
            noise_factor = 10 ** (nf_db / 10)

            # Friis 级联
            if i == 0:
                cumulative_noise_factor = noise_factor
            else:
                cumulative_noise_factor += (noise_factor - 1) / cumulative_gain_linear

            # 本级之前的累积增益（IP3 折算到链路输入用）
            gain_before_linear = cumulative_gain_linear
            cumulative_gain_linear *= gain_linear
            cumulative_gain_db = 10 * math.log10(cumulative_gain_linear)
            cumulative_nf_db = 10 * math.log10(cumulative_noise_factor)

            # IP3 级联：本级 IIP3（输入折算）= OIP3 − G；1/IIP3_tot 累加
            cumulative_iip3_dbm: float | None = None
            cumulative_oip3_dbm: float | None = None
            if oip3_dbm is not None:
                iip3_in_mw = 10.0 ** ((oip3_dbm - gain_db) / 10.0)
                iip3_inv_sum += gain_before_linear / iip3_in_mw
                has_ip3 = True
            if has_ip3:
                cumulative_iip3_dbm = 10.0 * math.log10(1.0 / iip3_inv_sum)
                cumulative_oip3_dbm = cumulative_iip3_dbm + cumulative_gain_db

            # B5 IP2 级联：与 IP3 同一功率和式（iip2 直接给/由 oip2 折算二选一）
            cumulative_iip2_dbm: float | None = None
            cumulative_oip2_dbm: float | None = None
            if iip2_dbm is not None or oip2_dbm is not None:
                iip2_in_mw = (10.0 ** (iip2_dbm / 10.0)
                              if iip2_dbm is not None
                              else 10.0 ** ((oip2_dbm - gain_db) / 10.0))
                iip2_inv_sum += gain_before_linear / iip2_in_mw
                has_ip2 = True
            if has_ip2:
                cumulative_iip2_dbm = 10.0 * math.log10(1.0 / iip2_inv_sum)
                cumulative_oip2_dbm = cumulative_iip2_dbm + cumulative_gain_db

            # P1dB 级联（简化：逐级回推）
            cascade_p1db = p1db_dbm
            if p1db_dbm is not None and i > 0:
                # 回推到输入：P1dB_in = P1dB_out - G_pre
                cascade_p1db = p1db_dbm - cumulative_gain_db + gain_db

            stages.append(StageResult(
                name=stage["name"],
                gain_db=gain_db,
                nf_db=nf_db,
                cumulative_gain_db=cumulative_gain_db,
                cumulative_nf_db=cumulative_nf_db,
                p1db_dbm=cascade_p1db,
                oip3_dbm=oip3_dbm,
                cumulative_iip3_dbm=cumulative_iip3_dbm,
                cumulative_oip3_dbm=cumulative_oip3_dbm,
                iip2_dbm=iip2_dbm,
                oip2_dbm=oip2_dbm,
                cumulative_iip2_dbm=cumulative_iip2_dbm,
                cumulative_oip2_dbm=cumulative_oip2_dbm,
            ))

        # 最终 P1dB：取所有级中最小的输入 P1dB
        p1db_values = [s.p1db_dbm for s in stages if s.p1db_dbm is not None]
        final_p1db = min(p1db_values) if p1db_values else None

        # 链路级联 IP3（全链无 oip3 级时如实 None，不硬造）
        cascade_iip3_dbm = (
            10.0 * math.log10(1.0 / iip3_inv_sum) if has_ip3 else None)
        cascade_oip3_dbm = (
            cascade_iip3_dbm + 10.0 * math.log10(cumulative_gain_linear)
            if has_ip3 else None)

        # B5 链路级联 IP2（同一幂和式 order=2；全链无 IP2 级如实 None）
        cascade_iip2_dbm = (
            10.0 * math.log10(1.0 / iip2_inv_sum) if has_ip2 else None)
        cascade_oip2_dbm = (
            cascade_iip2_dbm + 10.0 * math.log10(cumulative_gain_linear)
            if has_ip2 else None)

        return BudgetResult(
            stages=stages,
            cascade_gain_db=10 * math.log10(cumulative_gain_linear),
            cascade_nf_db=10 * math.log10(cumulative_noise_factor),
            cascade_p1db_dbm=final_p1db,
            cascade_iip3_dbm=cascade_iip3_dbm,
            cascade_oip3_dbm=cascade_oip3_dbm,
            cascade_iip2_dbm=cascade_iip2_dbm,
            cascade_oip2_dbm=cascade_oip2_dbm,
        )

# ─── C16 收尾：Bode-Fano 匹配带宽极限 + 有载/无载 Q 提取（§10.3 C16）────────────
#
# 课本闭合判据（Bode 1945 / Fano 1950；Pozar《Microwave Engineering》Bode-Fano 节；
# Steer《Microwave and RF Design III》§7.2 "Fano-Bode Limits"）：
#
#   并联 RC 负载：∫₀^∞ ln(1/|Γ(ω)|) dω ≤ π/(RC)
#   串联 RL 负载：∫₀^∞ ln(1/|Γ(ω)|) dω ≤ πR/L
#   统一写法：∫₀^∞ ln(1/|Γ(ω)|) dω ≤ π/τ，τ 为负载惰性元件的时常数
#             （电容负载 τ=RC；电感负载 τ=L/R）。串联 RC / 并联 RL 同理。
#
# 直角（矩形）近似——设带宽 Δf 内 |Γ|≤Γmax、带外 |Γ|=1（ln1=0），
#   Δω·ln(1/Γmax) ≤ π/τ  ⇒  Δf_max = 1 / (2·τ·ln(1/Γmax))
# 其中 Γmax = 10^(-RL_dB/20)，RL_dB 为回波损耗门限。
#   经典算例：R=50Ω、C=1pF、VSWR≤2（|Γ|≤1/3，RL≈9.542dB）
#   ⇒ Δf_max = 1/(2·50ps·ln3) ≈ 9.10 GHz（独立来源同口径，
#   https://rfessentials.com/resources/rf-glossary/bode-fano-limit）。
#
# 常数出处（V1 席 P0 裁决 2026-10-04 逐字核对；errata:
# runs/review_ge8e/v1_bode_fano/ERRATA_C1.md）：π/τ 与
# Δf_max=1/(2τ·ln(1/Γmax)) 为并联 RC/串联 RL 行——Fano 1948 MIT RLE
# TR-41 §1 Eqs.(3)(4)（矩形带 ω·ln(1/|ρ|max) ≤ π/(RC)，ω=rad/s 全带宽）
# + p.16 "parallel RC ⇒ A₁=2/RC"（×π/2 积分恰=π/(RC)）；Kerr NRAO
# EDM-295 §II 同式；Steer《Microwave and RF Design III》§7.2 eq.(1)(3)
# 同口径；rfessentials 词条原文即上方算例。防再犯注记：串联 RC/并联 RL
# （|Γ(∞)|≠1 的对偶拓扑）与 Hz 口径（Δω=2πΔf）各差一个 2 因子，勿混
# ——C1-1 "π/(2RC)" 即此类混读误报（复核不成立，不改常数）。
#
# 合流注记（followup-ground 2026-09-28）：Γm 直接进出 + 复阻抗拟合路径的
# 可行性门在 core/bounds.py（bode_fano_rc/BodeFanoVerdict，F-K.A 谱系）；
# 两面闭式同源（π/τ 与 Δω·ln(1/Γm)），数值一致性由
# tests/unit/test_bounds.py::test_bode_fano_cross_budget_consistency 交叉钉
# 守卫；API/内核各自保持不动（不重写、不 re-export——public_api 金快照面）。
#
# 数值稳健性：ln(1/Γmax) = RL_dB·ln(10)/20 直接由 dB 计算——避免 Γmax 在高回波
# 损耗下下溢为 0 再取 ln(1/0) 的除零/溢出。

_BODE_FANO_RC_KINDS = frozenset({"parallel_rc", "series_rc"})
_BODE_FANO_RL_KINDS = frozenset({"series_rl", "parallel_rl"})
_BODE_FANO_KINDS = _BODE_FANO_RC_KINDS | _BODE_FANO_RL_KINDS


def _require_positive_finite(value: float, name: str) -> float:
    """收敛入参为 >0 的有限实数，否则 ValueError（纯数值守卫，不臆造）。"""
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是实数，收到 {value!r}") from exc
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须 >0 且有限，收到 {value!r}")
    return out


def _log_gamma_area(return_loss_db: float) -> float:
    """ln(1/|Γmax|) = RL_dB·ln(10)/20（高回波损耗下不下溢）。"""
    try:
        rl = float(return_loss_db)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"return_loss_db 必须是实数，收到 {return_loss_db!r}") from exc
    if not math.isfinite(rl) or rl <= 0.0:
        raise ValueError(f"return_loss_db 必须 >0 且有限，收到 {return_loss_db!r}")
    return rl * math.log(10.0) / 20.0


def _normalize_load_kind(load_kind: str) -> str:
    if load_kind not in _BODE_FANO_KINDS:
        raise ValueError(f"未知 load_kind={load_kind!r}；可选 {sorted(_BODE_FANO_KINDS)}")
    return load_kind


def gamma_from_return_loss(return_loss_db: float) -> float:
    """回波损耗门限 → 反射系数幅值 |Γ| = 10^(-RL_dB/20)。"""
    return math.exp(-_log_gamma_area(return_loss_db))


def bode_fano_integral_bound(tau_s: float) -> float:
    """Bode-Fano 积分上界 π/τ [rad/s]（τ=RC 或 L/R）。"""
    tau = _require_positive_finite(tau_s, "tau_s")
    return math.pi / tau


def bode_fano_time_constant(
    load_kind: str,
    resistance_ohm: float,
    *,
    capacitance_f: float | None = None,
    inductance_h: float | None = None,
) -> float:
    """负载惰性元件时常数 τ：电容负载 τ=RC；电感负载 τ=L/R。"""
    kind = _normalize_load_kind(load_kind)
    r = _require_positive_finite(resistance_ohm, "resistance_ohm")
    if kind in _BODE_FANO_RC_KINDS:
        if capacitance_f is None:
            raise ValueError(f"load_kind={kind!r} 需要 capacitance_f")
        if inductance_h is not None:
            raise ValueError(f"load_kind={kind!r} 不接受 inductance_h")
        return r * _require_positive_finite(capacitance_f, "capacitance_f")
    if inductance_h is None:
        raise ValueError(f"load_kind={kind!r} 需要 inductance_h")
    if capacitance_f is not None:
        raise ValueError(f"load_kind={kind!r} 不接受 capacitance_f")
    return _require_positive_finite(inductance_h, "inductance_h") / r


def bode_fano_max_bandwidth(tau_s: float, return_loss_db: float) -> float:
    """矩形近似下可达匹配带宽上限 Δf_max = 1/(2·τ·ln(1/|Γmax|)) [Hz]。"""
    tau = _require_positive_finite(tau_s, "tau_s")
    return 1.0 / (2.0 * tau * _log_gamma_area(return_loss_db))


@dataclass(frozen=True)
class MatchBandwidthVerdict:
    """目标带宽 vs Bode-Fano 上限的判定结果。"""

    target_bandwidth_hz: float
    max_bandwidth_hz: float

    @property
    def within_limit(self) -> bool:
        """目标带宽是否不超极限（边界取 ≤，达标即 allowed）。"""
        return self.target_bandwidth_hz <= self.max_bandwidth_hz

    @property
    def margin_hz(self) -> float:
        """剩余裕量（负值=超出量）。"""
        return self.max_bandwidth_hz - self.target_bandwidth_hz

    @property
    def usage_ratio(self) -> float:
        """目标带宽占极限的比例（>1 即超限）。"""
        return self.target_bandwidth_hz / self.max_bandwidth_hz

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_bandwidth_hz": self.target_bandwidth_hz,
            "max_bandwidth_hz": self.max_bandwidth_hz,
            "within_limit": self.within_limit,
            "margin_hz": self.margin_hz,
            "usage_ratio": self.usage_ratio,
        }


@dataclass(frozen=True)
class BodeFanoLimit:
    """负载的 Bode-Fano 匹配带宽极限（矩形近似，见模块内 C16 判据注释）。"""

    load_kind: str
    resistance_ohm: float
    reactance_value: float
    tau_s: float
    return_loss_db: float
    gamma_max: float
    max_bandwidth_hz: float

    @property
    def integral_bound_rad_s(self) -> float:
        """∫₀^∞ ln(1/|Γ|) dω 的上界 π/τ [rad/s]。"""
        return math.pi / self.tau_s

    def verdict(self, target_bandwidth_hz: float) -> MatchBandwidthVerdict:
        """对目标带宽做极限判定（目标须 ≥0 且有限）。"""
        try:
            target = float(target_bandwidth_hz)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"target_bandwidth_hz 必须是实数，收到 {target_bandwidth_hz!r}") from exc
        if not math.isfinite(target) or target < 0.0:
            raise ValueError(f"target_bandwidth_hz 必须 ≥0 且有限，收到 {target_bandwidth_hz!r}")
        return MatchBandwidthVerdict(target, self.max_bandwidth_hz)

    def within_limit(self, target_bandwidth_hz: float) -> bool:
        """目标带宽是否可达（≤ 极限）。"""
        return self.verdict(target_bandwidth_hz).within_limit

    def fractional_bandwidth(self, center_freq_hz: float) -> float:
        """最大带宽相对中心频率的分数带宽（展示口径，不参与判据）。"""
        f0 = _require_positive_finite(center_freq_hz, "center_freq_hz")
        return self.max_bandwidth_hz / f0

    def to_dict(self) -> dict[str, Any]:
        return {
            "load_kind": self.load_kind,
            "resistance_ohm": self.resistance_ohm,
            "reactance_value": self.reactance_value,
            "tau_s": self.tau_s,
            "return_loss_db": self.return_loss_db,
            "gamma_max": self.gamma_max,
            "max_bandwidth_hz": self.max_bandwidth_hz,
            "integral_bound_rad_s": self.integral_bound_rad_s,
        }


def bode_fano_limit(
    load_kind: str,
    resistance_ohm: float,
    return_loss_db: float,
    *,
    capacitance_f: float | None = None,
    inductance_h: float | None = None,
) -> BodeFanoLimit:
    """构造负载的 Bode-Fano 匹配带宽极限。

    Args:
        load_kind: "parallel_rc" / "series_rc" / "series_rl" / "parallel_rl"
        resistance_ohm: 负载电阻 R（>0）
        return_loss_db: 回波损耗门限 RL_dB（>0）
        capacitance_f: RC 负载电容 C（F，>0）
        inductance_h: RL 负载电感 L（H，>0）
    """
    kind = _normalize_load_kind(load_kind)
    tau = bode_fano_time_constant(
        kind, resistance_ohm, capacitance_f=capacitance_f, inductance_h=inductance_h
    )
    if kind in _BODE_FANO_RC_KINDS:
        reactance_value = _require_positive_finite(capacitance_f, "capacitance_f")
    else:
        reactance_value = _require_positive_finite(inductance_h, "inductance_h")
    return BodeFanoLimit(
        load_kind=kind,
        resistance_ohm=float(resistance_ohm),
        reactance_value=reactance_value,
        tau_s=tau,
        return_loss_db=float(return_loss_db),
        gamma_max=gamma_from_return_loss(return_loss_db),
        max_bandwidth_hz=bode_fano_max_bandwidth(tau, return_loss_db),
    )


# ─── 有载/无载 Q 提取（C16 同源确定性计算器；不改 calculators.py）──────────────
# 定义：Q_L = f0 / Δf_3dB（-3dB 带宽）。
# 对称耦合双端口谐振器在谐振点的传输幅度（线性）满足
#   |S21(f0)| = 2β/(1+2β)，Q_L = Q_u/(1+2β)
# ⇒ Q_u = Q_L / (1 - |S21(f0)|)，|S21(f0)| = 10^(-IL_dB/20)（IL_dB = 谐振点插损）。
# 假设对称耦合（β1=β2）；非对称端口需各端口 β 修正——本口径不外推到非对称。


def loaded_q(f0_hz: float, bandwidth_3db_hz: float) -> float:
    """有载品质因数 Q_L = f0 / Δf_3dB。"""
    f0 = _require_positive_finite(f0_hz, "f0_hz")
    bw = _require_positive_finite(bandwidth_3db_hz, "bandwidth_3db_hz")
    return f0 / bw


def _insertion_loss_db(insertion_loss_db: float) -> float:
    try:
        il = float(insertion_loss_db)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"insertion_loss_db 必须是实数，收到 {insertion_loss_db!r}") from exc
    if not math.isfinite(il) or il < 0.0:
        raise ValueError(f"insertion_loss_db 必须 ≥0 且有限，收到 {insertion_loss_db!r}")
    return il


def unloaded_q_from_transmission(
    f0_hz: float, bandwidth_3db_hz: float, insertion_loss_db: float
) -> float:
    """由谐振点插损与 -3dB 带宽提无载 Q（对称双端口口径）。

    Q_u = Q_L / (1 - 10^(-IL_dB/20))；IL_dB=0（无损）时 Q_u=+inf。
    """
    q_l = loaded_q(f0_hz, bandwidth_3db_hz)
    il = _insertion_loss_db(insertion_loss_db)
    if il == 0.0:
        return math.inf
    s21 = math.exp(-il * math.log(10.0) / 20.0)
    return q_l / (1.0 - s21)


def coupling_coefficient_from_q(q_loaded: float, q_unloaded: float) -> float:
    """总耦合系数 β_tot = Q_u/Q_L − 1（对称双端口时 β_tot=2β）。"""
    ql = _require_positive_finite(q_loaded, "q_loaded")
    qu = _require_positive_finite(q_unloaded, "q_unloaded")
    if qu < ql:
        raise ValueError(
            f"无载 Q 不可能低于有载 Q（收到 Q_u={q_unloaded!r} < Q_L={q_loaded!r}）"
        )
    return qu / ql - 1.0

