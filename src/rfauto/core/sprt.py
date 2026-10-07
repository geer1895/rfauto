"""S-3 SPRT 早停内核：Wald 1945 序贯概率比检验 + mSPRT always-valid 混合检验。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立路径，不自证，#118）：

- Abraham Wald (1945). "Sequential Tests of Statistical Hypotheses",
  Annals of Mathematical Statistics 16(2):117-186。对简单假设
  H0: μ=μ0 vs H1: μ=μ1，逐观测累加对数似然比
  Λ_n = Σᵢ ln f₁(xᵢ)/f₀(xᵢ)，上下界 A = ln((1−β)/α)、
  B = ln(β/(1−α))（B<0）：Λ_n ≥ A 拒 H0（判 H1），Λ_n ≤ B 接受 H0，
  其间继续采样。α=P_H0(误判 H1)、β=P_H1(误判 H0)。
- ASN（期望样本数）一阶近似：Wald 恒等式 E_μ[Λ_T] = E_μ[T]·E_μ[z]
  （z 为单观测 LLR 增量），以边界处停止概率 ≈ 名义 α/β 代入得闭式
  ASN(μ0) = (αA + (1−α)B)/E_{μ0}[z]、ASN(μ1) = (βB + (1−β)A)/E_{μ1}[z]。
  正态已知 σ 口径 E_{μ0}[z] = −δ²/(2σ²)、E_{μ1}[z] = +δ²/(2σ²)
  （δ=μ1−μ0）。一阶近似忽略越界过冲（overshoot），系统性轻微低估——
  实测 δ≤0.4σ 时 MC 停止样本数/理论 ∈ [1.01, 1.15]（±20% 判据带内，
  tests/unit/test_sprt.py 固定 seed 钉）。
- mSPRT（mixture SPRT，always-valid）：R. Johari, L. Pekelis, D. Walsh,
  "Always Valid Inference: Continuous Monitoring of A/B Tests"（KDD 2017）；
  round3 文档 [25] 并引 arXiv:1906.06612。将未知效应 θ 以先验 N(0,τ²)
  混合积分解析积分得闭式统计量
  Λ_n = (1+nτ²/σ²)^(−1/2)·exp( τ²(Σxᵢ)² / (2σ²(σ²+nτ²)) )，
  在 H0 下是非负鞅（E_H0[Λ_n]=1），Ville 不等式给出
  P_H0(sup_n Λ_n ≥ 1/α) ≤ α——任意频繁偷看不膨胀第一类错误
  （always-valid），适配 Optuna 逐 step 剪枝场景。
- 任务书缩写 LNSPRT 系自造、无公开来源，已证伪弃用（round3 §3.1 S-3
  行注记）——本模块只做正牌 Wald SPRT + mSPRT，不实现 LNSPRT。
- Optuna 剪枝语义（调用方约定）：H0 =「试验无改进」→ prune=True；
  Λ ≤ B 即剪。本模块只出内核纯函数，不动 optimization/ 接线
  （接线后批，round3 口径）。

接口：全部函数/数据类返回 JSON 可序列化 float/str/bool/list/dict；
数值 0.0 合法（判缺失一律 is not None，#364④）；纯算法零 IO；无第三方
依赖（numpy 都不进，stdlib math 足够，MC 裁判在测试侧用 numpy）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "ASNWald",
    "MSPRTDecision",
    "SPRTBounds",
    "SPRTDecision",
    "SPRTTrace",
    "asn_wald",
    "msprt_decide",
    "msprt_log_statistic",
    "msprt_pvalue",
    "msprt_run",
    "normal_drift",
    "normal_llr_increment",
    "optuna_prune_decision",
    "sprt_decide",
    "sprt_run",
    "wald_bounds",
]


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    """把入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _unit_interval(value: float, name: str) -> float:
    """把入参收敛为 (0,1) 开区间内有限 float，非法即显式报错。"""
    out = _finite(value, name)
    if not 0.0 < out < 1.0:
        raise ValueError(f"{name} 必须落在开区间 (0,1) 内（α/β=0 或 1 无序贯意义）")
    return out


def _nonneg_int(value: int, name: str) -> int:
    """把入参收敛为非负 int，非法即显式报错（bool 拒收）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    if not isinstance(value, (int,)) and not (isinstance(value, float) and float(value).is_integer()):
        raise ValueError(f"{name} 必须为整数")
    out = int(value)
    if out < 0:
        raise ValueError(f"{name} 必须 >=0")
    return out


# ─── Wald 1945 SPRT：边界 / LLR / 判定 ───────────────────────────────────────


@dataclass(frozen=True)
class SPRTBounds:
    """Wald SPRT 对数似然比上下界（A>0 / B<0）。"""

    alpha: float
    beta: float
    log_upper: float  # A = ln((1−β)/α)：Λ≥A 拒 H0
    log_lower: float  # B = ln(β/(1−α))：Λ≤B 接受 H0

    def to_dict(self) -> dict:
        return {
            "alpha": self.alpha,
            "beta": self.beta,
            "log_upper_A": self.log_upper,
            "log_lower_B": self.log_lower,
        }


def wald_bounds(alpha: float, beta: float) -> SPRTBounds:
    """Wald 1945 边界 A = ln((1−β)/α)、B = ln(β/(1−α))。

    α/β ∈ (0,1) 开区间（=0 或 1 时某一侧边界无穷，序贯检验退化，拒绝）。
    α=β 时 |A| = |B| = ln((1−α)/α) 对称。
    """
    a_ = _unit_interval(alpha, "alpha")
    b_ = _unit_interval(beta, "beta")
    return SPRTBounds(
        alpha=a_,
        beta=b_,
        log_upper=math.log((1.0 - b_) / a_),
        log_lower=math.log(b_ / (1.0 - a_)),
    )


def normal_llr_increment(x: float, mu0: float, mu1: float, sigma: float) -> float:
    """正态已知 σ 的单观测 LLR 增量 z = (μ1−μ0)(x − (μ0+μ1)/2)/σ²。

    由 ln N(x;μ1,σ²) − ln N(x;μ0,σ²) 配方化简（Wald 1945 正态特例）。
    """
    m0 = _finite(mu0, "mu0")
    m1 = _finite(mu1, "mu1")
    s = _positive(sigma, "sigma")
    xv = _finite(x, "x")
    return (m1 - m0) * (xv - 0.5 * (m0 + m1)) / (s * s)


def normal_drift(mu: float, mu0: float, mu1: float, sigma: float) -> float:
    """真均值 μ 下 LLR 随机游走的每步漂移 E_μ[z] = (μ1−μ0)(μ − (μ0+μ1)/2)/σ²。

    μ=μ0 → −δ²/(2σ²)；μ=μ1 → +δ²/(2σ²)；μ=(μ0+μ1)/2 → 0（ASN → ∞，
    中点最难判，ASN 理论曲线的单调分界）。
    """
    m0 = _finite(mu0, "mu0")
    m1 = _finite(mu1, "mu1")
    s = _positive(sigma, "sigma")
    return (m1 - m0) * (_finite(mu, "mu") - 0.5 * (m0 + m1)) / (s * s)


@dataclass(frozen=True)
class SPRTDecision:
    """单步判定：decision ∈ {continue, reject_h0, accept_h0}；prune 供 Optuna 回调。"""

    decision: str
    llr: float
    prune: bool  # accept_h0（H0=「无改进」语义）→ 剪枝

    def to_dict(self) -> dict:
        return {"decision": self.decision, "llr": self.llr, "prune": self.prune}


def sprt_decide(llr: float, bounds: SPRTBounds) -> SPRTDecision:
    """LLR → 三值判定（边界含等号：Λ≥A 拒 H0；Λ≤B 接受 H0，Wald 口径）。"""
    lv = _finite(llr, "llr")
    if not isinstance(bounds, SPRTBounds):
        raise ValueError("bounds 必须为 SPRTBounds（wald_bounds 产出）")
    if lv >= bounds.log_upper:
        return SPRTDecision(decision="reject_h0", llr=lv, prune=False)
    if lv <= bounds.log_lower:
        return SPRTDecision(decision="accept_h0", llr=lv, prune=True)
    return SPRTDecision(decision="continue", llr=lv, prune=False)


@dataclass(frozen=True)
class SPRTTrace:
    """一次序贯运行轨迹（JSON 可序列化 via to_dict）。"""

    n_stopped: int
    llr: float
    decision: str  # reject_h0 / accept_h0 / inconclusive
    bound_crossed: str | None  # "upper" / "lower" / None
    stopped_by: str  # "bound" / "max_n" / "exhausted"
    llr_path: list[float]

    def to_dict(self) -> dict:
        return {
            "n_stopped": self.n_stopped,
            "llr": self.llr,
            "decision": self.decision,
            "bound_crossed": self.bound_crossed,
            "stopped_by": self.stopped_by,
            "llr_path": list(self.llr_path),
        }


def sprt_run(
    samples: list[float],
    mu0: float,
    mu1: float,
    sigma: float,
    alpha: float,
    beta: float,
    max_n: int | None = None,
) -> SPRTTrace:
    """逐观测累加 LLR，首次越界即停（早停语义）。

    samples：按观测序的标量样本；max_n：可选截断（达到即停，判
    inconclusive 不凑结论）。空样本 → ValueError。
    返回 SPRTTrace：n_stopped/llr/decision/bound_crossed/stopped_by/llr_path
    （llr_path 为停止时刻为止的完整路径，len == n_stopped）。
    """
    if not samples:
        raise ValueError("samples 不能为空")
    bounds = wald_bounds(alpha, beta)
    delta = _finite(mu1, "mu1") - _finite(mu0, "mu0")
    if delta == 0.0:
        raise ValueError("mu0 与 mu1 不得相等（LLR 恒 0，检验退化）")
    s = _positive(sigma, "sigma")
    cap = len(samples) if max_n is None else min(_nonneg_int(max_n, "max_n"), len(samples))
    path: list[float] = []
    llr = 0.0
    for i in range(cap):
        llr += normal_llr_increment(samples[i], mu0, mu1, s)
        path.append(llr)
        if llr >= bounds.log_upper:
            return SPRTTrace(i + 1, llr, "reject_h0", "upper", "bound", path)
        if llr <= bounds.log_lower:
            return SPRTTrace(i + 1, llr, "accept_h0", "lower", "bound", path)
    stopped_by = "max_n" if max_n is not None and cap < len(samples) else "exhausted"
    return SPRTTrace(cap, llr, "inconclusive", None, stopped_by, path)


# ─── ASN（期望样本数）Wald 一阶闭式 ──────────────────────────────────────────


@dataclass(frozen=True)
class ASNWald:
    """Wald 一阶 ASN 近似（μ0/μ1 两锚点；中间 μ 需功效函数，无闭式）。"""

    alpha: float
    beta: float
    delta: float  # μ1 − μ0
    log_upper: float  # A
    log_lower: float  # B
    drift_h0: float  # E_{μ0}[z] = −δ²/(2σ²)
    drift_h1: float  # E_{μ1}[z] = +δ²/(2σ²)
    asn_h0: float
    asn_h1: float

    def to_dict(self) -> dict:
        return {
            "alpha": self.alpha,
            "beta": self.beta,
            "delta": self.delta,
            "log_upper_A": self.log_upper,
            "log_lower_B": self.log_lower,
            "drift_h0": self.drift_h0,
            "drift_h1": self.drift_h1,
            "asn_h0": self.asn_h0,
            "asn_h1": self.asn_h1,
        }


def asn_wald(mu0: float, mu1: float, sigma: float, alpha: float, beta: float) -> ASNWald:
    """Wald 一阶 ASN 闭式（正态已知 σ）。

    ASN(μ0) = (αA + (1−α)B)/E_{μ0}[z]、ASN(μ1) = (βB + (1−β)A)/E_{μ1}[z]。
    一阶近似忽略越界过冲 → 系统性轻微低估（实测 δ≤0.4σ 时 MC/理论
    ≤1.15，±20% 判据带内）；μ0==μ1 拒绝（δ=0 漂移恒 0，ASN 无意义）。
    α=β 对称时 asn_h0 == asn_h1（逐位，单测钉）。
    """
    m0 = _finite(mu0, "mu0")
    m1 = _finite(mu1, "mu1")
    delta = m1 - m0
    if delta == 0.0:
        raise ValueError("mu0 与 mu1 不得相等（δ=0 漂移恒 0，ASN 无定义）")
    s = _positive(sigma, "sigma")
    b_ = wald_bounds(alpha, beta)
    z0 = -delta * delta / (2.0 * s * s)
    z1 = -z0
    asn0 = (b_.alpha * b_.log_upper + (1.0 - b_.alpha) * b_.log_lower) / z0
    asn1 = (b_.beta * b_.log_lower + (1.0 - b_.beta) * b_.log_upper) / z1
    return ASNWald(
        alpha=b_.alpha,
        beta=b_.beta,
        delta=delta,
        log_upper=b_.log_upper,
        log_lower=b_.log_lower,
        drift_h0=z0,
        drift_h1=z1,
        asn_h0=asn0,
        asn_h1=asn1,
    )


# ─── mSPRT（Johari KDD'17）：混合统计量 / p 值 / always-valid 停止 ────────────


def msprt_log_statistic(sum_x: float, n: int, sigma: float, tau: float) -> float:
    """mSPRT 对数统计量 ln Λ_n（先验 θ~N(0,τ²) 对高斯似然解析积分）。

    ln Λ_n = −½·ln(1 + nτ²/σ²) + τ²(Σx)² / (2σ²(σ² + nτ²))。
    n=0 → 0.0（Λ=1，无证据，逐位）。对数域进出防下溢
    （Λ_n 可以极小/极大）。tau 必须 >0（τ=0 混合退化为点质量 H0=H1，
    Λ≡1 永不拒绝——静默 no-op 不可接受，显式拒绝）。
    """
    s = _positive(sigma, "sigma")
    t = _positive(tau, "tau")
    nn = _nonneg_int(n, "n")
    sv = _finite(sum_x, "sum_x")
    if nn == 0:
        return 0.0
    s2 = s * s
    t2 = t * t
    denom = 2.0 * s2 * (s2 + nn * t2)
    return -0.5 * math.log1p(nn * t2 / s2) + t2 * sv * sv / denom


def msprt_pvalue(sum_x: float, n: int, sigma: float, tau: float) -> float:
    """mSPRT always-valid p 值 p_n = min(1, 1/Λ_n)（Johari 口径）。"""
    log_llr = msprt_log_statistic(sum_x, n, sigma, tau)
    return min(1.0, math.exp(-log_llr))


@dataclass(frozen=True)
class MSPRTDecision:
    """mSPRT 单步判定：Λ_n ≥ 1/α ⇔ ln Λ_n ≥ −ln α 拒 H0（always-valid）。"""

    reject_h0: bool
    log_llr: float
    log_threshold: float  # −ln α
    pvalue: float

    def to_dict(self) -> dict:
        return {
            "reject_h0": self.reject_h0,
            "log_llr": self.log_llr,
            "log_threshold": self.log_threshold,
            "pvalue": self.pvalue,
        }


def msprt_decide(log_llr: float, alpha: float) -> MSPRTDecision:
    """ln Λ_n → always-valid 判定（阈值 −ln α；Ville 不等式保证 H0 冒出 ≤α）。"""
    lv = _finite(log_llr, "log_llr")
    a_ = _unit_interval(alpha, "alpha")
    thr = -math.log(a_)
    p = min(1.0, math.exp(-lv))
    return MSPRTDecision(reject_h0=lv >= thr, log_llr=lv, log_threshold=thr, pvalue=p)


def msprt_run(
    samples: list[float],
    sigma: float,
    tau: float,
    alpha: float,
    max_n: int | None = None,
) -> dict:
    """逐前缀累加 mSPRT 统计量，记录运行上确界 sup_n ln Λ_n（always-valid
    停止判定作用于 sup，不是当前值）。

    返回（JSON 可序列化）：{"n_stopped", "log_llr", "log_llr_max"（sup）,
    "reject_h0", "stopped_by"（"bound"/"max_n"/"exhausted"）,
    "log_llr_path"}。H0 冒出率 P(sup ≥ −ln α) ≤ α 对任意偷看频率成立
    （Ville，tests MC 钉 ≤1.5α）。
    """
    if not samples:
        raise ValueError("samples 不能为空")
    s = _positive(sigma, "sigma")
    a_ = _unit_interval(alpha, "alpha")
    thr = -math.log(a_)
    cap = len(samples) if max_n is None else min(_nonneg_int(max_n, "max_n"), len(samples))
    total = 0.0
    path: list[float] = []
    sup = -math.inf
    stopped_by = "exhausted"
    n_stopped = cap
    for i in range(cap):
        total += _finite(samples[i], f"samples[{i}]")
        log_llr = msprt_log_statistic(total, i + 1, s, tau)
        path.append(log_llr)
        sup = max(sup, log_llr)
        if log_llr >= thr:
            stopped_by = "bound"
            n_stopped = i + 1
            break
    if stopped_by == "exhausted" and max_n is not None and cap < len(samples):
        stopped_by = "max_n"
    return {
        "n_stopped": n_stopped,
        "log_llr": path[-1] if path else 0.0,
        "log_llr_max": (sup if path else 0.0),
        "reject_h0": bool(path) and stopped_by == "bound",
        "stopped_by": stopped_by,
        "log_llr_path": path,
    }


# ─── Optuna 剪枝决策（纯函数信封；接线在 optimization/，后批） ────────────────


def optuna_prune_decision(llr: float, alpha: float, beta: float) -> dict:
    """供 Optuna 回调调用的剪枝决策信封（纯函数，JSON 可序列化）。

    H0=「试验无改进」语义：Λ_n ≤ B（接受 H0）→ prune=True；
    Λ_n ≥ A（拒 H0，改进显著）→ prune=False 继续；
    之间 → continue。ok 字段恒 True（本函数只做判定，不抛业务异常；
    入参非法由 _finite/wald_bounds 显式 ValueError）。
    """
    bounds = wald_bounds(alpha, beta)
    dec = sprt_decide(llr, bounds)
    return {
        "ok": True,
        "prune": dec.prune,
        "decision": dec.decision,
        "llr": dec.llr,
        "bounds": bounds.to_dict(),
        "rule": "H0=无改进(剪枝)；Λ≥A 判 H1 继续；Λ≤B 判 H0 剪枝（Wald 1945）",
    }
