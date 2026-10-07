"""PT-5 验收抽样确定性内核（OC 曲线 + AQL/LTPD 反查 + 属性 SPRT）。

规格书 研究扩充 round18 §四 PT-5：二项/超几何
精确 OC + AQL/LTPD 反查 + sprt 补 Bernoulli LLR 成属性序贯验收。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立来源不自证，#118）：

- **单次抽样方案 (n, c) 的 OC（operating characteristic）函数**：批次不合格
  率 p 时判收概率 P_accept = P(X ≤ c)，X = 样本不合格数。二项口径
  （无限批/大批近似）P_accept = Σ_{k=0..c} C(n,k)·p^k·(1−p)^{n−k}；
  超几何口径（有限批 N，批内不合格 D 件，不放回抽 n）：
  P_accept = Σ_{k=max(0,n−(N−D))..min(c,D)} C(D,k)·C(N−D,n−k)/C(N,n)。
  数值实现走 scipy.stats.binom.cdf / hypergeom.cdf（logcms 双精度，
  制造统计同源 core/manufacturing_stats.py 口径）。
- **AQL/LTPD 反查（抽样方案设计）**：给生产方风险 α（好批 p=AQL 被拒
  概率）与使用方风险 β（坏批 p=LTPD 被收概率），求最小 c 及对应最小 n：
  P_accept(AQL) ≥ 1−α 且 P_accept(LTPD) ≤ β。可行性由 OC 对 n 的单调
  减（固定 c、0<p<1，样本越大判收越难）保证：每档 c 二分求"满足 α 约束
  的最大 n"与"满足 β 约束的最小 n"，区间相交即可行；c 自 0 递增取首个
  可行档（确定性枚举，无随机）。
- **c=0 零接收数方案闭式**：P_accept = (1−p)^n，P_accept(LTPD) ≤ β ⟺
  n ≥ ln β / ln(1−LTPD)，取 n = ceil(·)。文献锚（数值例独立基准）：该
  恒等式直接给出 LTPD=10%、β=10% 时 n = ln0.1/ln0.9 = 21.85 → **22**，
  即零接受数抽样计划表（Squeglia《Zero Acceptance Number Sampling
  Plans》/Juran 质量手册族 LTPD 档表）中广为引用的 n=22 档——本内核数值
  由恒等式 (1−0.10)^22 = 0.0985 ≤ 0.10 自证，不依赖文献转抄。
- **属性 SPRT（序贯验收，Wald 1945 闭式）**：H0: p=p0（批合格，AQL 侧）
  vs H1: p=p1（批不合格，LTPD 侧），逐件不合格观测 x∈{0,1} 累加对数似然
  比 Λ_n = Σ[ x·ln(p1/p0) + (1−x)·ln((1−p1)/(1−p0)) ]，判界
  A = ln((1−β)/α)（≥A 判拒收）、B = ln(β/(1−α))（≤B 判接收），其间
  继续抽样。A. Wald, "Sequential Tests of Statistical Hypotheses", Annals
  of Mathematical Statistics 16(2):117-186, 1945。边界公式与
  core/sprt.py（S-3 正态均值 SPRT）同一 Wald 闭式——边界复用该模块
  wald_bounds 单源（core→core 只读 import）。
- **ASN（平均样本数）一阶近似**：Wald 恒等式 E_p[Λ_T] = E_p[T]·E_p[z]
  （z 为单件 LLR 增量），以真值 p0/p1 处停止概率 ≈ 名义 (1−α, α)/
  (β, 1−β) 代入得 ASN(p0) = ((1−α)B + αA)/E_{p0}[z]、
  ASN(p1) = (βB + (1−β)A)/E_{p1}[z]。一阶近似忽略越界过冲，系统性轻微
  低估——tests/unit/test_acceptance_sampling.py 以固定 seed 蒙特卡洛
  （独立裁判路径）钉经验 α/β 与 ASN 比值带，同 core/sprt.py 先例。

接口纪律：全部确定性（纯 scipy/numpy 定量、无随机、无网络、无 IO、无
全局状态，铁律 7）；dict 进出 JSON 可序列化；bool 显式拒收（df7+⑯）、
缺失判 is not None（#364④）、输入非法 ValueError；数值 0.0 合法。
"""

from __future__ import annotations

import math
from typing import Any

from scipy import stats

from rfauto.core.sprt import wald_bounds

__all__ = [
    "asn_attribute",
    "bernoulli_llr",
    "binomial_oc",
    "c0_plan",
    "design_plan",
    "hypergeometric_oc",
    "oc_curve",
    "sprt_attribute_run",
]

#: AQL/LTPD 反查的单档 c 枚举上限（每档 n 二分 O(log N)；c 更大时
#: 方案指标饱和，如实报不可行而非死循环）
_C_MAX = 200
#: 反查的 n 搜索上限（验收抽样方案工程量级远低于此；触顶如实报）
_N_MAX = 100_000


# ─── 入参守卫（manufacturing_stats.py 口径同源）──────────────────────────────


def _prob(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染概率）")
    out = float(value)
    if not math.isfinite(out) or not 0.0 <= out <= 1.0:
        raise ValueError(f"{name} 必须为 [0,1] 内有限概率")
    return out


def _risk(value: Any, name: str) -> float:
    out = _prob(value, name)
    if out <= 0.0 or out >= 1.0:
        raise ValueError(f"{name} 必须为 (0,1) 开区间风险值")
    return out


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = value if isinstance(value, int) else int(value)
    if out != value or out < 0:
        raise ValueError(f"{name} 必须为非负整数")
    return out


# ─── OC 曲线（二项/超几何精确）───────────────────────────────────────────────


def binomial_oc(p: float, n: int, c: int) -> float:
    """二项精确 OC：P_accept(p | n, c) = P(X ≤ c)，X~Bin(n, p)。

    p=0 恒判收（1.0）、c ≥ n 恒判收；p=1 且 c<n 恒判拒（0.0）。
    """
    p = _prob(p, "p")
    n = _count(n, "n")
    c = _count(c, "c")
    if c >= n:
        return 1.0
    return float(stats.binom.cdf(c, n, p))


def hypergeometric_oc(defects: int, lot_size: int, sample_n: int, c: int) -> float:
    """超几何精确 OC：有限批 N 件含 D 件不合格，不放回抽 n 件判收概率。

    defects=D、lot_size=N、sample_n=n、c=接收数；X~Hypergeom(N, D, n)。
    """
    d = _count(defects, "defects")
    lot = _count(lot_size, "lot_size")
    n = _count(sample_n, "sample_n")
    c = _count(c, "c")
    if d > lot:
        raise ValueError("defects 不得超过 lot_size")
    if n > lot:
        raise ValueError("sample_n 不得超过 lot_size")
    if c >= n:
        return 1.0
    return float(stats.hypergeom.cdf(c, lot, d, n))


def oc_curve(
    p_grid: Any,
    n: int,
    c: int,
    *,
    lot_size: int | None = None,
) -> dict[str, Any]:
    """OC 曲线批量求值（JSON 可序列化）。

    - 二项口径：lot_size=None，逐点 binomial_oc(p, n, c)。
    - 超几何口径：lot_size 给定时逐点把批不合格率换算成批内不合格件数
      D = round(p·N)（换算规则显式披露在返回 meta，浮点批不合格率非
      整数件时四舍五入；要精确整件语义请直接用 hypergeometric_oc）。
    """
    n = _count(n, "n")
    c = _count(c, "c")
    pts = [float(x) for x in p_grid]
    if not pts:
        raise ValueError("p_grid 不能为空")
    ps: list[float] = []
    for x in pts:
        if not math.isfinite(x) or x < 0.0:
            raise ValueError("p_grid 每点必须为非负有限数")
        ps.append(min(x, 1.0))
    if lot_size is None:
        pas = [binomial_oc(p, n, c) for p in ps]
        return {
            "kind": "binomial",
            "n": n,
            "c": c,
            "p": ps,
            "p_accept": pas,
        }
    lot = _count(lot_size, "lot_size")
    pas = []
    for p in ps:
        d = round(p * lot)
        pas.append(hypergeometric_oc(d, lot, n, c))
    return {
        "kind": "hypergeometric",
        "n": n,
        "c": c,
        "lot_size": lot,
        "defect_rule": "D = round(p * lot_size)",
        "p": ps,
        "p_accept": pas,
    }


# ─── AQL/LTPD 反查（抽样方案设计）───────────────────────────────────────────


def _pa_binom(c: int, n: int, p: float) -> float:
    if c >= n:
        return 1.0
    return float(stats.binom.cdf(c, n, p))


def _max_n_for_alpha(c: int, p_aql: float, threshold: float) -> int | None:
    """满足 P_accept(p_aql) ≥ threshold 的最大 n（OC 对 n 单调减二分）。

    无解（n=1 已违约）返回 None；n=c+1 起跳（c≥n 恒判收不在约束内）。
    """
    if _pa_binom(c, c + 1, p_aql) < threshold:
        return None
    lo, hi = c + 1, _N_MAX
    if _pa_binom(c, hi, p_aql) >= threshold:
        return hi
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _pa_binom(c, mid, p_aql) >= threshold:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _min_n_for_beta(c: int, p_ltpd: float, threshold: float) -> int | None:
    """满足 P_accept(p_ltpd) ≤ threshold 的最小 n（单调减二分）。"""
    if _pa_binom(c, _N_MAX, p_ltpd) > threshold:
        return None
    lo, hi = c + 1, _N_MAX
    if _pa_binom(c, lo, p_ltpd) <= threshold:
        return lo
    while lo < hi:
        mid = (lo + hi) // 2
        if _pa_binom(c, mid, p_ltpd) <= threshold:
            hi = mid
        else:
            lo = mid + 1
    return lo


def design_plan(aql: float, ltpd: float, alpha: float, beta: float) -> dict[str, Any]:
    """AQL/LTPD 反查：最小接收数 c 及对应最小样本量 n 的单次抽样方案。

    约束：P_accept(AQL) ≥ 1−α（生产方风险）且 P_accept(LTPD) ≤ β（使用方
    风险）；c 自 0 递增取首个可行档、n 取该档满足 β 约束的最小值（同时
    落在 α 约束窗内）。返回实际风险（点值）随行披露；触枚举上限如实报
    infeasible 不凑数（#122）。
    """
    paql = _prob(aql, "aql")
    pltpd = _prob(ltpd, "ltpd")
    if not paql < pltpd:
        raise ValueError("aql 必须 < ltpd（好批不合格率低于坏批）")
    arisk = _risk(alpha, "alpha")
    brisk = _risk(beta, "beta")
    want_pa = 1.0 - arisk
    for c in range(0, _C_MAX + 1):
        n_hi = _max_n_for_alpha(c, paql, want_pa)
        if n_hi is None:
            continue
        n_lo = _min_n_for_beta(c, pltpd, brisk)
        if n_lo is not None and n_lo <= n_hi:
            pa_a = _pa_binom(c, n_lo, paql)
            pa_b = _pa_binom(c, n_lo, pltpd)
            return {
                "n": n_lo,
                "c": c,
                "aql": paql,
                "ltpd": pltpd,
                "alpha_target": arisk,
                "beta_target": brisk,
                "p_accept_at_aql": pa_a,
                "p_accept_at_ltpd": pa_b,
                "alpha_actual": 1.0 - pa_a,
                "beta_actual": pa_b,
            }
    return {
        "n": None,
        "c": None,
        "aql": paql,
        "ltpd": pltpd,
        "alpha_target": arisk,
        "beta_target": brisk,
        "infeasible": True,
        "reason": f"c 触枚举上限 {_C_MAX}（或 n 触 {_N_MAX}）仍无方案",
    }


def c0_plan(ltpd: float, beta: float) -> dict[str, Any]:
    """c=0 零接收数方案闭式：n = ceil(ln β / ln(1−LTPD))。

    恒等式 P_accept = (1−LTPD)^n ≤ β 直接反解；文献锚=LTPD 10%/β 10%
    档 n=22（零接受数抽样计划表标准档，数值由恒等式自证，见模块头注）。
    """
    pltpd = _prob(ltpd, "ltpd")
    brisk = _risk(beta, "beta")
    if pltpd >= 1.0:
        raise ValueError("ltpd=1 时 ln(1−ltpd) 无定义（全不合格批无检验意义）")
    n = math.ceil(math.log(brisk) / math.log(1.0 - pltpd))
    n = max(n, 1)
    pa = (1.0 - pltpd) ** n
    return {
        "n": n,
        "c": 0,
        "ltpd": pltpd,
        "beta_target": brisk,
        "p_accept_at_ltpd": pa,
        "beta_actual": pa,
        "identity": "P_accept = (1-ltpd)^n <= beta",
    }


# ─── 属性 SPRT（Wald 1945 Bernoulli LLR 序贯验收）───────────────────────────


def bernoulli_llr(x: Any, p0: float, p1: float) -> float:
    """单件 Bernoulli 对数似然比增量 ln f1(x)/f0(x)。

    x=1（不合格件）：ln(p1/p0)；x=0（合格件）：ln((1−p1)/(1−p0))。
    """
    q0 = _prob(p0, "p0")
    q1 = _prob(p1, "p1")
    if isinstance(x, bool) or x not in (0, 1):
        raise ValueError("x 必须为 0（合格件）或 1（不合格件）")
    if q0 in (0.0, 1.0) or q1 in (0.0, 1.0):
        raise ValueError("p0/p1 必须为开区间 (0,1) 内概率（退化 Bernoulli 无 LLR）")
    if int(x) == 1:
        return math.log(q1 / q0)
    return math.log((1.0 - q1) / (1.0 - q0))


def sprt_attribute_run(
    observations: Any,
    p0: float,
    p1: float,
    alpha: float,
    beta: float,
) -> dict[str, Any]:
    """属性序贯验收：逐件累加 Bernoulli LLR，触 Wald 界即停。

    decision 语义：``reject_lot``（Λ≥A，判 p=p1 拒收）、``accept_lot``
    （Λ≤B，判 p=p0 接收）、``continue``（序列耗尽未触界——如实报未决，
    不冒充已判，#122）。返回逐点轨迹（llr_trace）供判读留痕。
    """
    q0 = _prob(p0, "p0")
    q1 = _prob(p1, "p1")
    if not q0 < q1:
        raise ValueError("p0 必须 < p1（合格侧不合格率低于拒收侧）")
    arisk = _risk(alpha, "alpha")
    brisk = _risk(beta, "beta")
    bounds = wald_bounds(arisk, brisk)
    seq: list[int] = []
    for raw in observations:
        if isinstance(raw, bool) or raw not in (0, 1):
            raise ValueError("observations 必须只含 0（合格件）/1（不合格件）")
        seq.append(int(raw))
    llr = 0.0
    trace: list[float] = []
    decision = "continue"
    stopped_at = None
    for i, x in enumerate(seq):
        llr += bernoulli_llr(x, q0, q1)
        trace.append(llr)
        if llr >= bounds.log_upper:
            decision = "reject_lot"
            stopped_at = i + 1
            break
        if llr <= bounds.log_lower:
            decision = "accept_lot"
            stopped_at = i + 1
            break
    return {
        "decision": decision,
        "llr": llr,
        "a": bounds.log_upper,
        "b": bounds.log_lower,
        "n_used": stopped_at if stopped_at is not None else len(seq),
        "n_total": len(seq),
        "llr_trace": trace,
        "p0": q0,
        "p1": q1,
        "alpha": arisk,
        "beta": brisk,
    }


def asn_attribute(p: float, p0: float, p1: float, alpha: float, beta: float) -> dict[str, Any]:
    """ASN 一阶近似（Wald 恒等式，见模块头注）：仅在真值 p=p0 / p=p1
    两个锚点有效（停止概率≈名义风险代入）；其他 p 值如实 ValueError
    （一阶近似在中间 p 需 OC 函数 L(p)，本内核不实现以免引入不可核公式）。
    """
    q = _prob(p, "p")
    q0 = _prob(p0, "p0")
    q1 = _prob(p1, "p1")
    if not q0 < q1:
        raise ValueError("p0 必须 < p1")
    arisk = _risk(alpha, "alpha")
    brisk = _risk(beta, "beta")
    if q not in (q0, q1):
        raise ValueError("asn 一阶近似只定义在 p=p0 或 p=p1 锚点（中间 p 需 OC 函数，未实现）")
    bounds = wald_bounds(arisk, brisk)
    ez = q * bernoulli_llr(1, q0, q1) + (1.0 - q) * bernoulli_llr(0, q0, q1)
    if q == q0:
        numerator = (1.0 - arisk) * bounds.log_lower + arisk * bounds.log_upper
    else:
        numerator = brisk * bounds.log_lower + (1.0 - brisk) * bounds.log_upper
    asn = numerator / ez
    return {
        "p": q,
        "asn": asn,
        "e_z": ez,
        "note": "Wald 一阶近似（忽略越界过冲，系统性轻微低估；MC 带钉在测试侧）",
    }
