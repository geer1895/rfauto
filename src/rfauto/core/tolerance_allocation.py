"""M-7 cost-aware 公差分配优化器（tolerance allocation）确定性内核。

法源与口径（round1 原文 研究扩充 M-7 节；
铁律 5 来源写 docstring；裁判=独立来源不自证，#118）：

- round1 规格：输入 = 敏感度（∂y/∂xᵢ，代理面 Sobol S1 或数值差分）×
  每参数成本曲线（原文"缺省指数"；制造工程成本-公差曲线惯例）+ 目标
  （良率/方差/预算）；方法 = "拉格朗日/序列二次规划分配（凸近似）"；
  输出 = 逐参数公差建议表 + Cpk 重算 + WCD 腿复核。

优化形式（本内核钉死的两方向，互为对偶同族）：
  A（任务书主口径）min Σ(Sᵢδᵢ)²   s.t. Σ cᵢ(δᵢ) ≤ C_budget   [allocate_cost_budget]
  B（round1 主口径）min Σ cᵢ(δᵢ)  s.t. Σ(Sᵢδᵢ)² ≤ V_max      [allocate_min_cost]
  线性预算特例（Σδᵢ ≤ T，任务书预算模式）：闭式 δᵢ = T·Sᵢ⁻²/ΣⱼSⱼ⁻²
  [allocate_budget_t]。RSS 口径：输出标准差代理 σ_y = √(Σ(Sᵢδᵢ)²)。

成本模型（公差 δᵢ 越紧越贵，c 随 δ 单调不增）：
  inverse_power（缺省，闭式可解）：cᵢ(δ) = aᵢ·δ^(−p)，p ≥ 1 缺省 1；
  exponential（round1 缺省成本型）：cᵢ(δ) = aᵢ·exp(−δ/δ_c)。

拉格朗日闭式（inverse_power；KKT 推导，单测以独立数值裁判复核）：
  L = ΣSᵢ²δᵢ² + λ(Σaᵢδᵢ^(−p) − C) → ∂/∂δᵢ = 0 →
  2Sᵢ²δᵢ − λp·aᵢδᵢ^(−p−1) = 0 → δᵢ = (λ·p·aᵢ/(2Sᵢ²))^(1/(p+2))。
  p=1 时外乘子亦闭式：由 Σaᵢ/δᵢ = C 解得 λ = 2·(Σ(aᵢSᵢ)^(2/3)/C)³。
  方向性：贵（aᵢ 大→紧公差代价高）参数分配**更松**、敏感（Sᵢ 大）参数
  **更紧**——等边际成本原则（Chase & Greenwood 制造公差分配的幂律成本
  版，教科书结论）。任务书提示形态"δᵢ∝1/√(cᵢ·|Sᵢ|)"为同族经验式
  （敏感度×成本反比家族）；指数随成本模型与预算口径变化，本内核以 KKT
  推导为准，配独立数值裁判（随机可行扰动/粗网格复核）而非推导自证。
  exponential 的 FOC 为超越方程（δ·e^(δ/δc) = λa/(2δc·S²)）——按原文
  "拉格朗日/序列二次规划"走数值：外层对 λ 一维单调二分，内层逐参数 FOC
  单调二分；两模型同一外壳（箱约束 [tol_min, tol_max] 经 clip 保 KKT
  可分离结构，cost(λ)/var(λ) 仍单调，二分严格有效）。

对照法（判据要求）：greedy（边际方差/边际成本贪心）与 proportional
（等公差基线等比例缩放——round1 判据"Σcost < 等公差基线"的基线臂）。

Cpk 重算与良率换算：公差按 ±3σ 惯例（δᵢ = 3σᵢ）→ σ_y = RSS/3；
  Cpk = min(USL−μ, μ−LSL)/(3σ_y)。良率↔σ（单边正态）：Y = Φ(m/σ) →
  σ = m/Φ⁻¹(Y)（statistics.NormalDist().inv_cdf，stdlib 确定性）。

接口纪律：纯函数零 IO；dict 进出 JSON 可序列化；单位 SI 钉在参数名；
数值 0.0 合法（判缺失一律 is not None，#364④）；bool 显式拒收
（df7+⑯）；敏感度 S=0 的参数不进紧分配、显式落 tol_max（A 模式成本为
零参数落 tol_min）并带 flag，全零敏感度不崩溃。优化不可行 → 结果
feasible=False + note（不抛；输入非法才 ValueError，aging 守卫口径）。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

COST_INVERSE_POWER = "inverse_power"
COST_EXPONENTIAL = "exponential"
_COST_MODELS = (COST_INVERSE_POWER, COST_EXPONENTIAL)

#: 缺省成本幂指数（inverse_power 模型 c=a·δ^−p 的 p）
DEFAULT_COST_POWER = 1.0

METHOD_BUDGET_T = "lagrangian_budget_t"
METHOD_COST_BUDGET = "lagrangian_cost_budget"
METHOD_MIN_COST = "lagrangian_min_cost"
METHOD_GREEDY = "greedy_marginal"
METHOD_PROPORTIONAL = "proportional_equal_tol"


# ─── 入参守卫 ────────────────────────────────────────────────────────────────


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _nonneg(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0")
    return out


def _sens_map(sensitivities: dict[str, Any], name: str = "sensitivities") -> dict[str, float]:
    """敏感度表收敛：非空 dict[str, 有限 float]；S 可为负（平方进 RSS）、可为 0。"""
    if not isinstance(sensitivities, dict) or not sensitivities:
        raise ValueError(f"{name} 必须是非空 dict[str, float]")
    return {str(k): _finite(v, f"{name}[{k!r}]") for k, v in sensitivities.items()}


def _coeff_map(
    cost_coeffs: dict[str, Any], sens: dict[str, float], name: str = "cost_coeffs"
) -> dict[str, float]:
    """成本系数表收敛：须覆盖敏感度全部键，且 >0（a=0 走免费参数分支）。"""
    if not isinstance(cost_coeffs, dict):
        raise ValueError(f"{name} 必须是 dict[str, float]")
    missing = [k for k in sens if k not in cost_coeffs or cost_coeffs[k] is None]
    if missing:
        raise ValueError(f"{name} 缺键: {missing}")
    return {str(k): _finite(cost_coeffs[k], f"{name}[{k!r}]") for k in sens}


# ─── 结果面 ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToleranceAllocation:
    """分配结果（JSON 面 via to_dict；feasible=False 时 tols={}）。"""

    keys: tuple[str, ...]
    tols: dict[str, float]
    sensitivities: dict[str, float]
    costs: dict[str, float]
    cost_model: str
    total_cost: float
    rss: float  # √(Σ(Sᵢδᵢ)²)
    worst_case: float  # Σ|Sᵢ|δᵢ（WCD 腿复核，round1 口径）
    method: str
    feasible: bool = True
    note: str = ""
    clamped: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "keys": list(self.keys),
            "tols": dict(self.tols),
            "sensitivities": dict(self.sensitivities),
            "costs": dict(self.costs),
            "cost_model": self.cost_model,
            "total_cost": self.total_cost,
            "rss": self.rss,
            "worst_case": self.worst_case,
            "method": self.method,
            "feasible": self.feasible,
            "note": self.note,
            "clamped": list(self.clamped),
        }


def rss_of(sensitivities: dict[str, float], tols: dict[str, float]) -> float:
    """RSS 输出标准差代理 √(Σ(Sᵢδᵢ)²)。"""
    sens = _sens_map(sensitivities)
    total = 0.0
    for key, s_val in sens.items():
        if tols.get(key) is None:
            raise ValueError(f"tols 缺键: {key!r}")
        d = _nonneg(tols[key], f"tols[{key!r}]")
        total += (s_val * d) ** 2
    return math.sqrt(total)


def worst_case_of(sensitivities: dict[str, float], tols: dict[str, float]) -> float:
    """最坏情况腿（WCD）Σ|Sᵢ|δᵢ（线性叠加口径，round1"+WCD 腿复核"）。"""
    sens = _sens_map(sensitivities)
    total = 0.0
    for key, s_val in sens.items():
        if tols.get(key) is None:
            raise ValueError(f"tols 缺键: {key!r}")
        d = _nonneg(tols[key], f"tols[{key!r}]")
        total += abs(s_val) * d
    return total


def cpk_from_tols(
    sensitivities: dict[str, float],
    tols: dict[str, float],
    usl: float,
    lsl: float | None = None,
    mean: float = 0.0,
    sigmas_per_tol: float = 3.0,
) -> dict[str, Any]:
    """Cpk 重算（round1 输出面）：σ_y = RSS/sigmas_per_tol（±3σ 公差惯例缺省）。

    Cpk = min(USL−μ, μ−LSL)/(3σ_y)；lsl 缺省 None 只算上侧；σ_y=0 →
    cpk=+inf（JSON 由调用方处理，内核如实返回 float("inf")）。
    """
    sens = _sens_map(sensitivities)
    usl_v = _finite(usl, "usl")
    mean_v = _finite(mean, "mean")
    spt = _positive(sigmas_per_tol, "sigmas_per_tol")
    rss = rss_of(sens, tols)
    sigma_y = rss / spt
    margin_up = usl_v - mean_v
    if lsl is None:
        margin = margin_up
    else:
        lsl_v = _finite(lsl, "lsl")
        margin = min(margin_up, mean_v - lsl_v)
    cpk = math.inf if sigma_y == 0.0 else margin / (3.0 * sigma_y)
    return {
        "cpk": cpk,
        "sigma_y": sigma_y,
        "rss": rss,
        "margin": margin,
        "sigmas_per_tol": spt,
    }


def yield_to_output_sigma(spec_margin: float, yield_target: float) -> float:
    """单边正态良率换算：Y = Φ(m/σ) → σ = m/Φ⁻¹(Y)（stdlib NormalDist）。

    spec_margin：单侧规范裕量 m = USL−μ（≥0）；yield_target ∈ (0,1)。
    m=0 → σ=0（逐位，零裕量零容差）。
    """
    m = _nonneg(spec_margin, "spec_margin")
    y = _finite(yield_target, "yield_target")
    if not 0.0 < y < 1.0:
        raise ValueError(f"yield_target 必须 ∈ (0,1)，实际 {yield_target!r}")
    if m == 0.0:
        return 0.0
    z = NormalDist().inv_cdf(y)
    return m / z


def sensitivities_from_callable(
    response: Callable[[dict[str, float]], float],
    x0: dict[str, float],
    keys: list[str] | tuple[str, ...] | None = None,
    rel_step: float = 1e-6,
) -> dict[str, float]:
    """数值差分敏感度（任务书"callable 入参显式"口径）：中央差分
    Sᵢ = (y(x+h·eᵢ) − y(x−h·eᵢ))/(2h)，h = rel_step·max(1, |xᵢ|)。

    response 必须吃完整参数 dict 返回标量；对线性/二次响应中央差分逐位
    精确（单测钉）。keys 缺省 = x0 键序。
    """
    if not callable(response):
        raise ValueError("response 必须是 callable[[dict], float]")
    base = {str(k): _finite(v, f"x0[{k!r}]") for k, v in x0.items()}
    if not base:
        raise ValueError("x0 不能为空")
    step = _positive(rel_step, "rel_step")
    keys_v = [str(k) for k in (keys if keys is not None else base)]
    missing = [k for k in keys_v if k not in base]
    if missing:
        raise ValueError(f"keys 含 x0 之外的键: {missing}")
    out: dict[str, float] = {}
    for key in keys_v:
        h = step * max(1.0, abs(base[key]))
        up = dict(base)
        dn = dict(base)
        up[key] = base[key] + h
        dn[key] = base[key] - h
        y_up = float(response(up))
        y_dn = float(response(dn))
        if not (math.isfinite(y_up) and math.isfinite(y_dn)):
            raise ValueError(f"response 在 {key!r} 扰动处返回非有限值")
        out[key] = (y_up - y_dn) / (2.0 * h)
    return out


# ─── 成本模型 ────────────────────────────────────────────────────────────────


def _cost_params(
    cost_model: str, cost_power: float, exp_scale: float | None
) -> tuple[float, float]:
    """模型参数收敛：inverse_power 校验 p>0（exp_scale 不消费）；exponential
    校验 exp_scale>0（缺省 None → 显式报错，不静默取值）。"""
    if cost_model not in _COST_MODELS:
        raise ValueError(f"cost_model 必须是 {_COST_MODELS} 之一，实际 {cost_model!r}")
    if cost_model == COST_INVERSE_POWER:
        return _positive(cost_power, "cost_power"), 1.0
    return (
        float(cost_power),
        _positive(exp_scale if exp_scale is not None else 0.0, "exp_scale"),
    )


def cost_of(
    tols: dict[str, float],
    cost_coeffs: dict[str, float],
    cost_model: str = COST_INVERSE_POWER,
    cost_power: float = DEFAULT_COST_POWER,
    exp_scale: float | None = None,
) -> dict[str, float]:
    """逐参数成本 cᵢ(δᵢ)（模型见模块 docstring；返回逐键 dict）。"""
    p, scale = _cost_params(cost_model, cost_power, exp_scale)
    out: dict[str, float] = {}
    for key, coeff in cost_coeffs.items():
        a = _nonneg(coeff, f"cost_coeffs[{key!r}]")
        d = _nonneg(tols[key], f"tols[{key!r}]")
        if cost_model == COST_INVERSE_POWER:
            if a == 0.0:
                out[key] = 0.0
            elif d == 0.0:
                out[key] = math.inf  # δ→0⁺ 时 c=a·δ⁻ᵖ→∞（数学如实，不凑 0）
            else:
                out[key] = a * d ** (-p)
        else:
            out[key] = a * math.exp(-d / scale) if a > 0.0 else 0.0
    return out


# ─── 分配内核 ────────────────────────────────────────────────────────────────


def _budget_t_alloc(
    sens: dict[str, float], total_t: float, tol_max: float | None
) -> ToleranceAllocation:
    """预算模式闭式：min Σ(Sδ)² s.t. Σδ=T → δᵢ ∝ Sᵢ⁻²（FOC 等边际方差）。"""
    live = {k: v for k, v in sens.items() if v != 0.0}
    dead = [k for k, v in sens.items() if v == 0.0]
    tols: dict[str, float] = {}
    clamped: list[str] = []
    notes: list[str] = []
    if not live:
        # 全零敏感度：方差与分配无关 → 全部给到上限（或均分）
        if tol_max is not None:
            tols = {k: tol_max for k in sens}
            notes.append("全零敏感度：全部取 tol_max（方差与分配无关）")
        else:
            share = total_t / len(sens)
            tols = {k: share for k in sens}
            notes.append("全零敏感度：等分预算（方差与分配无关）")
    else:
        inv = {k: 1.0 / (v * v) for k, v in live.items()}
        free = dict(inv)
        budget_left = total_t
        fixed_sum = 0.0
        while True:
            denom = sum(free.values())
            alloc = {k: budget_left * v / denom for k, v in free.items()}
            if tol_max is None:
                tols = {**{k: v for k, v in alloc.items()}, **tols}
                break
            over = [k for k, v in alloc.items() if v > tol_max]
            if not over:
                tols = {**alloc, **tols}
                break
            for k in over:
                tols[k] = tol_max
                fixed_sum += tol_max
                clamped.append(k)
                del free[k]
            if not free:
                return ToleranceAllocation(
                    keys=tuple(sens),
                    tols={},
                    sensitivities=sens,
                    costs={},
                    cost_model="budget_linear",
                    total_cost=0.0,
                    rss=0.0,
                    worst_case=0.0,
                    method=METHOD_BUDGET_T,
                    feasible=False,
                    note=f"预算不足以覆盖 {len(clamped)} 个上限钳位参数（Σδ 上限 ≥ T）",
                    clamped=tuple(clamped),
                )
            budget_left = total_t - fixed_sum
        for k in dead:
            tols[k] = 0.0
        if dead:
            notes.append(f"S=0 参数不进紧分配（记 0，预算让给敏感参数）: {dead}")
    total = sum(tols.values())
    if abs(total - total_t) > 1e-9 * max(1.0, total_t):
        notes.append(f"Σδ={total:.12g} ≠ T（钳位吸收）")
    return ToleranceAllocation(
        keys=tuple(sens),
        tols=tols,
        sensitivities=sens,
        costs={k: tols[k] for k in tols},
        cost_model="budget_linear",
        total_cost=total,
        rss=rss_of(sens, tols),
        worst_case=worst_case_of(sens, tols),
        method=METHOD_BUDGET_T,
        feasible=True,
        note="; ".join(notes),
        clamped=tuple(clamped),
    )


def allocate_budget_t(
    sensitivities: dict[str, float],
    total_tol_t: float,
    tol_max: float | None = None,
) -> ToleranceAllocation:
    """预算模式（任务书 Σ|δᵢ| ≤ T 口径）：min Σ(Sᵢδᵢ)² s.t. Σδᵢ = T。

    闭式 δᵢ = T·Sᵢ⁻²/ΣⱼSⱼ⁻²（S≠0 子集；S=0 参数不进紧分配，有上限时落
    tol_max 并带 flag）。tol_max 给定时做钳位-重分配瀑布。线性预算口径下
    成本面=公差本身（total_cost 记 Σδ 供对账）。
    """
    sens = _sens_map(sensitivities)
    t = _positive(total_tol_t, "total_tol_t")
    if tol_max is not None:
        tol_max = _positive(tol_max, "tol_max")
    return _budget_t_alloc(sens, t, tol_max)


def _delta_foc(
    lam: float,
    sens: dict[str, float],
    coeffs: dict[str, float],
    cost_model: str,
    cost_power: float,
    exp_scale: float,
    lo: float,
    hi: float,
) -> dict[str, float]:
    """给定外乘子 λ 的逐参数 FOC 解（含箱约束 clip；可分离 ⇒ clip 即 KKT）。

    inverse_power: δᵢ = (λ·p·aᵢ/(2Sᵢ²))^(1/(p+2))；
    exponential: 2Sᵢ²δ = λ(aᵢ/δc)·e^(−δ/δc)（对 δ 单调增，内层二分）。
    """
    tols: dict[str, float] = {}
    for key, s_val in sens.items():
        if s_val == 0.0:
            tols[key] = hi  # 方向性口径：零敏感参数不消耗紧公差
            continue
        a_val = coeffs[key]
        s2 = s_val * s_val
        if cost_model == COST_INVERSE_POWER:
            raw = (lam * cost_power * a_val / (2.0 * s2)) ** (1.0 / (cost_power + 2.0))
            tols[key] = min(max(raw, lo), hi)
        else:
            target = lam * a_val / exp_scale
            g_hi = 2.0 * s2 * hi - target * math.exp(-hi / exp_scale)
            if g_hi <= 0.0:
                tols[key] = hi
                continue
            d_lo_val, d_hi_val = 0.0, hi
            for _ in range(200):
                mid = 0.5 * (d_lo_val + d_hi_val)
                g_mid = 2.0 * s2 * mid - target * math.exp(-mid / exp_scale)
                if g_mid > 0.0:
                    d_hi_val = mid
                else:
                    d_lo_val = mid
            tols[key] = min(max(0.5 * (d_lo_val + d_hi_val), lo), hi)
    return tols


def _scalar_of(
    tols: dict[str, float],
    sens: dict[str, float],
    coeffs: dict[str, float],
    cost_model: str,
    cost_power: float,
    exp_scale: float,
    want: str,
) -> float:
    """want="cost" → Σcᵢ(δᵢ)；want="var" → Σ(Sᵢδᵢ)²（二分目标标量）。"""
    if want == "cost":
        if cost_model == COST_INVERSE_POWER:
            return sum(
                (0.0 if coeffs[k] == 0.0 else coeffs[k] * tols[k] ** (-cost_power))
                for k in tols
            )
        return sum(
            (0.0 if coeffs[k] == 0.0 else coeffs[k] * math.exp(-tols[k] / exp_scale))
            for k in tols
        )
    return sum((sens[k] * tols[k]) ** 2 for k in tols)


def _lagrangian_kernel(
    sens: dict[str, float],
    coeffs: dict[str, float],
    cost_model: str,
    cost_power: float,
    exp_scale_v: float,
    tol_min: float,
    tol_max: float,
    target: float,
    want: str,
    method: str,
) -> ToleranceAllocation:
    """外层 λ 二分内核：want="cost" 解 cost(λ)=target（A 模式，cost 随 λ 减）；
    want="var" 解 var(λ)=target（B 模式，var 随 λ 增）。箱约束 clip 后单调性
    保持，二分严格有效（docstring 口径）；λ 上界按倍增扩域至标量过目标。"""
    tols_lo = _delta_foc(0.0, sens, coeffs, cost_model, cost_power, exp_scale_v, tol_min, tol_max)

    def scale_of(tols: dict[str, float]) -> float:
        return _scalar_of(tols, sens, coeffs, cost_model, cost_power, exp_scale_v, want)

    def alloc_of(
        tols: dict[str, float], ok_note: str, feasible: bool = True,
        clamped: tuple[str, ...] = (),
    ) -> ToleranceAllocation:
        var_val = _scalar_of(tols, sens, coeffs, cost_model, cost_power, exp_scale_v, "var")
        return ToleranceAllocation(
            keys=tuple(sens),
            tols=tols,
            sensitivities=sens,
            costs=cost_of(tols, coeffs, cost_model, cost_power, exp_scale_v),
            cost_model=cost_model,
            total_cost=_scalar_of(
                tols, sens, coeffs, cost_model, cost_power, exp_scale_v, "cost"
            ),
            rss=math.sqrt(var_val),
            worst_case=worst_case_of(sens, tols),
            method=method,
            feasible=feasible,
            note=ok_note,
            clamped=clamped,
        )

    def infeasible(note: str) -> ToleranceAllocation:
        return ToleranceAllocation(
            keys=tuple(sens),
            tols={},
            sensitivities=sens,
            costs={},
            cost_model=cost_model,
            total_cost=0.0,
            rss=0.0,
            worst_case=0.0,
            method=method,
            feasible=False,
            note=note,
        )

    val_lo = scale_of(tols_lo)
    # λ 上界倍增扩域：直到 want 标量过目标（clip 后仍单调，必达全上限端点）
    lam_hi = 1.0
    tols_hi = tols_lo
    for _ in range(400):
        tols_hi = _delta_foc(
            lam_hi, sens, coeffs, cost_model, cost_power, exp_scale_v, tol_min, tol_max
        )
        if want == "cost":
            if scale_of(tols_hi) <= target:
                break
        else:
            if scale_of(tols_hi) >= target:
                break
        lam_hi *= 2.0
    else:
        val_hi = scale_of(tols_hi)
        if want == "cost":
            return infeasible(
                f"预算不可行：全上限（最松=最便宜）成本 {val_hi:.6g} 仍 > 预算 {target:.6g}"
            )
        # var 模式扩域耗尽 = 全上限（最便宜端）方差仍低于目标 → 约束松弛，
        # 最优解即全上限（成本最小臂），feasible 如实为 True
        return alloc_of(
            tols_hi, "方差目标松弛：全上限即达标（约束不激活，成本最小臂）"
        )

    if want == "cost":
        if val_lo <= target:
            return alloc_of(tols_lo, "预算松弛：最紧解已低于预算（约束不激活）")
    else:
        if val_lo >= target:
            return infeasible(
                f"方差目标不可达：全下限（最紧）RSS² {val_lo:.6g} 已 ≥ 目标 {target:.6g}"
            )

    lam_lo = 0.0
    for _ in range(200):
        lam_mid = 0.5 * (lam_lo + lam_hi)
        tols_mid = _delta_foc(
            lam_mid, sens, coeffs, cost_model, cost_power, exp_scale_v, tol_min, tol_max
        )
        val_mid = scale_of(tols_mid)
        if want == "cost":
            if val_mid > target:
                lam_lo = lam_mid
            else:
                lam_hi = lam_mid
        else:
            if val_mid < target:
                lam_lo = lam_mid
            else:
                lam_hi = lam_mid
        if lam_hi - lam_lo <= 1e-14 * max(1.0, lam_hi):
            break
    lam_star = 0.5 * (lam_lo + lam_hi)
    tols = _delta_foc(lam_star, sens, coeffs, cost_model, cost_power, exp_scale_v, tol_min, tol_max)
    clamped = tuple(k for k, v in tols.items() if v in (tol_min, tol_max))
    return alloc_of(tols, "约束激活（等边际成本 KKT 解）", clamped=clamped)


def allocate_cost_budget(
    sensitivities: dict[str, float],
    cost_coeffs: dict[str, float],
    budget_c: float,
    cost_model: str = COST_INVERSE_POWER,
    cost_power: float = DEFAULT_COST_POWER,
    exp_scale: float | None = None,
    tol_min: float = 1e-6,
    tol_max: float = 1.0,
) -> ToleranceAllocation:
    """A 模式（任务书主口径）：min Σ(Sᵢδᵢ)² s.t. Σcᵢ(δᵢ) ≤ C。

    inverse_power p=1 有全闭式（docstring：δᵢ=(λaᵢ/(2Sᵢ²))^(1/3)、
    λ=2(Σ(aᵢSᵢ)^(2/3)/C)³），内核统一走 λ 二分（同一解），闭式由单测
    独立回收。exponential 需显式 exp_scale（δ_c>0）。
    """
    sens = _sens_map(sensitivities)
    coeffs = _coeff_map(cost_coeffs, sens)
    budget = _positive(budget_c, "budget_c")
    lo = _positive(tol_min, "tol_min")
    hi = _positive(tol_max, "tol_max")
    if hi <= lo:
        raise ValueError(f"tol_max({hi}) 必须 > tol_min({lo})")
    p, scale = _cost_params(cost_model, cost_power, exp_scale)
    return _lagrangian_kernel(
        sens, coeffs, cost_model, p, scale, lo, hi, budget, "cost", METHOD_COST_BUDGET
    )


def allocate_min_cost(
    sensitivities: dict[str, float],
    cost_coeffs: dict[str, float],
    rss_max: float,
    cost_model: str = COST_INVERSE_POWER,
    cost_power: float = DEFAULT_COST_POWER,
    exp_scale: float | None = None,
    tol_min: float = 1e-6,
    tol_max: float = 1.0,
) -> ToleranceAllocation:
    """B 模式（round1 主口径，良率目标经 yield_to_output_sigma 折 RSS²）：
    min Σcᵢ(δᵢ) s.t. Σ(Sᵢδᵢ)² ≤ V_max。与 A 模式同族对偶（docstring）。"""
    sens = _sens_map(sensitivities)
    coeffs = _coeff_map(cost_coeffs, sens)
    var_target = _positive(rss_max, "rss_max") ** 2
    lo = _positive(tol_min, "tol_min")
    hi = _positive(tol_max, "tol_max")
    if hi <= lo:
        raise ValueError(f"tol_max({hi}) 必须 > tol_min({lo})")
    p, scale = _cost_params(cost_model, cost_power, exp_scale)
    return _lagrangian_kernel(
        sens, coeffs, cost_model, p, scale, lo, hi, var_target, "var", METHOD_MIN_COST
    )


# ─── 对照法 ──────────────────────────────────────────────────────────────────


def allocate_greedy_cost(
    sensitivities: dict[str, float],
    cost_coeffs: dict[str, float],
    budget_c: float,
    cost_model: str = COST_INVERSE_POWER,
    cost_power: float = DEFAULT_COST_POWER,
    exp_scale: float | None = None,
    tol_min: float = 1e-6,
    tol_max: float = 1.0,
    n_steps: int = 400,
) -> ToleranceAllocation:
    """贪心对照法：从全上限（最松）起步，每步把剩余预算花在
    边际方差收益/边际成本最大的参数上（乘性收紧步 ε=0.05）。

    判据角色：同预算下 RSS(greedy) ≥ RSS(lagrangian)（离散化 gap 有界，
    单测钉）。
    """
    sens = _sens_map(sensitivities)
    coeffs = _coeff_map(cost_coeffs, sens)
    budget = _positive(budget_c, "budget_c")
    lo = _positive(tol_min, "tol_min")
    hi = _positive(tol_max, "tol_max")
    if hi <= lo:
        raise ValueError(f"tol_max({hi}) 必须 > tol_min({lo})")
    p, scale = _cost_params(cost_model, cost_power, exp_scale)
    steps = int(n_steps)
    if steps < 1:
        raise ValueError("n_steps 必须 >=1")

    def unit_cost(key: str, d: float) -> float:
        if coeffs[key] == 0.0:
            return 0.0
        if cost_model == COST_INVERSE_POWER:
            return coeffs[key] * d ** (-p)
        return coeffs[key] * math.exp(-d / scale)

    tols = {k: hi for k in sens}
    spent = sum(unit_cost(k, d) for k, d in tols.items())
    remaining = budget - spent
    if remaining < 0.0:
        return ToleranceAllocation(
            keys=tuple(sens),
            tols={},
            sensitivities=sens,
            costs={},
            cost_model=cost_model,
            total_cost=0.0,
            rss=0.0,
            worst_case=0.0,
            method=METHOD_GREEDY,
            feasible=False,
            note=f"预算不可行：全上限成本 {spent:.6g} > 预算 {budget:.6g}",
        )
    eps = 0.05
    for _ in range(steps):
        if remaining <= 0.0:
            break
        best_key: str | None = None
        best_ratio = 0.0
        best_cost = 0.0
        best_new = 0.0
        for key, s_val in sens.items():
            if s_val == 0.0:
                continue
            d_now = tols[key]
            d_new = max(lo, d_now * (1.0 - eps))
            if d_new >= d_now:
                continue
            dc = unit_cost(key, d_new) - unit_cost(key, d_now)
            if dc <= 0.0 or dc > remaining:
                continue
            dv = s_val * s_val * (d_now * d_now - d_new * d_new)
            ratio = dv / dc
            if ratio > best_ratio:
                best_ratio = ratio
                best_key = key
                best_cost = dc
                best_new = d_new
        if best_key is None:
            break
        tols[best_key] = best_new
        remaining -= best_cost
    spent = sum(unit_cost(k, d) for k, d in tols.items())
    return ToleranceAllocation(
        keys=tuple(sens),
        tols=tols,
        sensitivities=sens,
        costs={k: unit_cost(k, d) for k, d in tols.items()},
        cost_model=cost_model,
        total_cost=spent,
        rss=rss_of(sens, tols),
        worst_case=worst_case_of(sens, tols),
        method=METHOD_GREEDY,
        feasible=True,
        note=f"贪心对照（{steps} 步离散，剩余预算 {remaining:.6g}）",
    )


def allocate_proportional_cost(
    sensitivities: dict[str, float],
    cost_coeffs: dict[str, float],
    budget_c: float,
    cost_model: str = COST_INVERSE_POWER,
    cost_power: float = DEFAULT_COST_POWER,
    exp_scale: float | None = None,
    tol_min: float = 1e-6,
    tol_max: float = 1.0,
) -> ToleranceAllocation:
    """等公差基线对照法（round1 判据基线臂）：所有参数同公差 t，
    二分解 cost(t)=C（t 随成本单调减）。判据角色：同预算下
    RSS(proportional) ≥ RSS(lagrangian)。"""
    sens = _sens_map(sensitivities)
    coeffs = _coeff_map(cost_coeffs, sens)
    budget = _positive(budget_c, "budget_c")
    lo = _positive(tol_min, "tol_min")
    hi = _positive(tol_max, "tol_max")
    if hi <= lo:
        raise ValueError(f"tol_max({hi}) 必须 > tol_min({lo})")
    p, scale = _cost_params(cost_model, cost_power, exp_scale)

    def cost_at(t_val: float) -> float:
        total = 0.0
        for key in sens:
            if coeffs[key] == 0.0:
                continue
            if cost_model == COST_INVERSE_POWER:
                total += coeffs[key] * t_val ** (-p)
            else:
                total += coeffs[key] * math.exp(-t_val / scale)
        return total

    if cost_at(hi) > budget:
        return ToleranceAllocation(
            keys=tuple(sens),
            tols={},
            sensitivities=sens,
            costs={},
            cost_model=cost_model,
            total_cost=0.0,
            rss=0.0,
            worst_case=0.0,
            method=METHOD_PROPORTIONAL,
            feasible=False,
            note=f"预算不可行：等公差全上限成本 {cost_at(hi):.6g} > 预算 {budget:.6g}",
        )
    t_lo, t_hi = lo, hi
    if cost_at(lo) <= budget:
        t_star = lo
    else:
        for _ in range(200):
            mid = 0.5 * (t_lo + t_hi)
            if cost_at(mid) > budget:
                t_lo = mid
            else:
                t_hi = mid
            if t_hi - t_lo <= 1e-14 * max(1.0, t_hi):
                break
        t_star = 0.5 * (t_lo + t_hi)
    tols = {k: t_star for k in sens}
    spent = cost_at(t_star)
    return ToleranceAllocation(
        keys=tuple(sens),
        tols=tols,
        sensitivities=sens,
        costs={k: (0.0 if coeffs[k] == 0.0 else spent / len(sens)) for k in sens},
        cost_model=cost_model,
        total_cost=spent,
        rss=rss_of(sens, tols),
        worst_case=worst_case_of(sens, tols),
        method=METHOD_PROPORTIONAL,
        feasible=True,
        note="等公差基线（t* 二分自 cost(t)=C）",
    )
