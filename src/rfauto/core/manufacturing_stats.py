"""PT-1/2/3 量产三件套确定性内核（规格书 规格深案 §B-5）。

三件口径（铁律 5 来源写 docstring；裁判=独立来源不自证，#118）：

- **PT-1 guardband_limits** 判定规则与保护带（ILAC-G8 Table 1 结构）：
  接受限 AL = TU − w（上侧）/ AL = TL + w（下侧），保护带 w = m·U，
  m = z_{1−PFA}/k（缺省 k=1.96，PFA = 1 − Φ(k·m) 恒等式精确成立）。
  m=1（w=U）在 ILAC-G8 的 k=2 口径下 PFA=1−Φ(2)≈2.27%≈2%，即规格注记
  "w=U→PFA≈2% 已核"。U 消费 en_report.gum_combined_uncertainty 口径
  （预算表分量→U=k·u_c 的展开不确定度，可直接作 u95 传入；en_report 缺省
  k=2 与本内核 k=1.96 差 2% 量级，须精确一致时传 k=2）。
  双侧 both：Bonferroni（每侧分摊 PFA/2，并集界 ≤ 目标）vs 多元正态联合
  （每侧保全额目标、按接受区间积分精确算联合 PFA，含对侧尾修正）双口径。
- **PT-2 cpk_ci** 过程能力指数置信区间：
  σ̂ = s/c4(n)（c4(n)=√(2/(n−1))·Γ(n/2)/Γ((n−1)/2) 无偏化因子）；
  Cp̂ = (USL−LSL)/(6σ̂)；Cp CI = Cp̂·√(χ²_{α/2,n−1}/((n−1)c4²)) ～
  Cp̂·√(χ²_{1−α/2,n−1}/((n−1)c4²))（χ² pivot 反演；代入 σ̂=s/c4 后 c4
  消去，即 Montgomery 教材式）；Cpk CI = Bissell 1990 正态近似
  Cpk ± z·√(1/(9n)+Cpk²/(2(n−1)))（适用域 n≥30 且 Cpk∈[0.5,3]，域外
  如实降级标注不冒充精确）；Ppk+百分位法（Clements 1989：σ_p=(X_99.865−
  X_0.135)/6，Ppk=min 距 3σ_p）带 normal/lognormal 两档——dB 域数据
  （已是对数域）走 normal 档，线性幅度呈对数正态的量走 lognormal 档。
  与 core/tolerance_allocation.cpk_from_tols（公差→Cpk 点估计重算）互补
  不替换：那件是"公差分配后重算"，本件是"样本→CI"。
- **PT-3 weibull_mle** 2 参数 Weibull 右删失 MLE：
  scipy.stats.CensoredData.right_censored → weibull_min.fit(floc=0)
  （scipy≥1.11 已钉；1.18 起 CensoredData 构造签名改为
  (uncensored, *, right=...)，内核带新旧双签名兼容垫片）。
  区间双口径：观测 Fisher 信息（解析 nll 数值 Hessian）正态近似 +
  剖面似然比（2ΔlnL ≤ χ²_{1−α,1} 轮廓，brentq 求根）；B10 =
  η·(−ln 0.9)^{1/β} 置信下限同双口径（delta 法单侧下界 / LR 下根）。
  闭式互证锚：aging.weibull_life/weibull_p_of_failure/n50_from_weibull
  （消费方测试对拍，内核不 import aging 免环）。

全部确定性：纯 numpy/scipy 定量，无随机、无网络、无全局状态（数值只在
确定性内核，铁律 7）；dict 进出 JSON 可序列化；接口纪律同
tolerance_allocation.py（bool 显式拒收 df7+⑯、缺失判 is not None
#364④、输入非法 ValueError、无 IO）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import optimize, stats
from scipy.special import gammaln

#: Bissell 1990 正态近似的适用域（规格书 §B-5 钉值）
BISSELL_MIN_N = 30
BISSELL_CPK_LO = 0.5
BISSELL_CPK_HI = 3.0

#: Clements 百分位法三锚点
_PCT_LO = 0.00135
_PCT_MID = 0.5
_PCT_HI = 0.99865

#: guardband 双侧口径方法名
_METHOD_BONFERRONI = "bonferroni"
_METHOD_JOINT = "joint_mvnormal"


# ─── 入参守卫（tolerance_allocation.py 口径同源）──────────────────────────


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


def _prob(value: Any, name: str) -> float:
    out = _finite(value, name)
    if not 0.0 < out < 1.0:
        raise ValueError(f"{name} 必须在 (0,1) 内")
    return out


def _sample_vector(samples: Any, name: str, *, positive: bool = False) -> np.ndarray:
    if isinstance(samples, (str, bytes, bool)):
        raise ValueError(f"{name} 必须是数值序列（不接受标量/字符串）")
    if isinstance(samples, (list, tuple)) and any(
        isinstance(v, bool) for v in samples
    ):
        # 混合 [1.0, True] 序列 asarray 后 dtype=float64，dtype 检查抓不到——
        # 元素级补查（float(True)=1.0 静默污染统计，df7+⑯ 同族）
        raise ValueError(f"{name} 不接受 bool 元素（float(True)=1.0 静默污染统计）")
    raw = np.asarray(samples)
    if raw.dtype == bool:
        raise ValueError(f"{name} 不接受 bool 序列（float(True)=1.0 静默污染统计）")
    arr = raw.astype(float).ravel()
    if arr.size == 0:
        raise ValueError(f"{name} 不能为空")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 必须全为有限数")
    if positive and float(np.min(arr)) <= 0.0:
        raise ValueError(f"{name} 必须全 >0（lognormal 档要求）")
    return arr


# ─── 共享闭式：c4(n) 无偏化因子 ─────────────────────────────────────────────


def c4(n: int) -> float:
    """样本标准差无偏化因子 c4(n) = √(2/(n−1))·Γ(n/2)/Γ((n−1)/2)。

    n≥2 整数；表值（SQC 手算表，测试钉 n=2..10）：
    0.7979 / 0.8862 / 0.9213 / 0.9400 / 0.9515 / 0.9594 / 0.9650 /
    0.9693 / 0.9727。
    """
    n_int = int(n)
    if n_int != n or n_int < 2:
        raise ValueError(f"n 必须为 >=2 的整数，得 {n!r}")
    return math.sqrt(2.0 / (n_int - 1)) * math.exp(
        gammaln(n_int / 2.0) - gammaln((n_int - 1) / 2.0)
    )


# ═══ PT-1：判定规则与保护带（ILAC-G8）══════════════════════════════════════


def guardband_limits(
    value: float,
    u95: float,
    spec: Any,
    pfa_target: float = 0.02,
    side: str = "upper",
    *,
    k: float = 1.96,
) -> dict[str, Any]:
    """保护带接受限与判定（PT-1，ILAC-G8 Table 1 结构）。

    Args:
        value: 被测量值（与 spec 同单位，如 dB）。
        u95: 95% 展开不确定度 U（正消费 en_report.gum_combined_uncertainty
            产出的 U；标准不确定度按 u = U/k 折算）。
        spec: 规格限。upper→TU（float）；lower→TL（float）；both→
            (TL, TU) 二元组或 {"lower": TL, "upper": TU}。
        pfa_target: 误接受概率目标 PFA（(0,1)，缺省 0.02）。
        side: "upper" | "lower" | "both"。
        k: U 的包含因子（缺省 1.96=正态 95% 精确分位；消费 en_report
            U(k=2) 且要求口径精确一致时传 k=2。m = z_{1−PFA}/k 使
            PFA = 1 − Φ(k·m) 恒等）。

    Returns:
        {ok, side, value, u95, k, u_std, pfa_target, m, w, spec{tl,tu},
        al_lower, al_upper, method, decision, spec_conformity,
        pfa_at_limit, joint_pfa (both 且 joint 口径), notes[]}
        —— pfa_at_limit 为单侧最坏点（真值恰在规格限）PFA 闭式值
        Φ(−w/u)，数值积分回收由锚树独立 quad 复核（≤1e-4）。

    Raises:
        ValueError: 入参非法（side 不识、spec 缺、pfa/k 越域等）。
    """
    v = _finite(value, "value")
    u95_v = _positive(u95, "u95")
    pfa = _prob(pfa_target, "pfa_target")
    k_v = _positive(k, "k")
    if side not in ("upper", "lower", "both"):
        raise ValueError(f"side 必须是 upper|lower|both，得 {side!r}")
    u_std = u95_v / k_v
    z = float(stats.norm.ppf(1.0 - pfa))
    m = z / k_v
    w = m * u95_v

    notes: list[str] = []
    tu: float | None = None
    tl: float | None = None
    if side == "upper":
        tu = _finite(spec, "spec(TU)")
    elif side == "lower":
        tl = _finite(spec, "spec(TL)")
    else:
        if isinstance(spec, dict):
            raw_tu = spec.get("upper")
            raw_tl = spec.get("lower")
            if raw_tu is None or raw_tl is None:
                raise ValueError("both 侧 spec dict 须含 lower 与 upper 两键")
            tl = _finite(raw_tl, "spec.lower(TL)")
            tu = _finite(raw_tu, "spec.upper(TU)")
        else:
            try:
                tl_raw, tu_raw = spec  # type: ignore[misc]
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "both 侧 spec 须为 (TL, TU) 二元组或 {lower,upper} dict"
                ) from exc
            tl = _finite(tl_raw, "spec(TL)")
            tu = _finite(tu_raw, "spec(TU)")
        if tl >= tu:
            raise ValueError(f"both 侧须 TL < TU，得 TL={tl} >= TU={tu}")

    method = "single_sided"
    joint_pfa: float | None = None
    if side == "both":
        # 双口径（规格书 §B-5）：Bonferroni 每侧分摊 PFA/2（并集界 ≤ 目标，
        # 每侧带更宽）vs 多元正态联合（每侧保全额、按接受区间精确积分）。
        z_half = float(stats.norm.ppf(1.0 - pfa / 2.0))
        m_half = z_half / k_v
        w_bonf = m_half * u95_v
        al_up_bonf = tu - w_bonf
        al_lo_bonf = tl + w_bonf
        # 联合口径（每侧保全额 m/w）：
        al_up_joint = tu - w
        al_lo_joint = tl + w
        # 真值恰在 TU 时接受概率 = P(AL_lo ≤ x ≤ AL_up)，x~N(TU, u)——
        # 精确联合积分（对侧尾修正使联合 PFA 严格 ≤ 单侧值）：
        p_acc_tu = float(
            stats.norm.cdf((al_up_joint - tu) / u_std)
            - stats.norm.cdf((al_lo_joint - tu) / u_std)
        )
        p_acc_tl = float(
            stats.norm.cdf((al_up_joint - tl) / u_std)
            - stats.norm.cdf((al_lo_joint - tl) / u_std)
        )
        joint_pfa = max(p_acc_tu, p_acc_tl)
        method = _METHOD_JOINT
        pfa_at_limit = p_acc_tu if p_acc_tu >= p_acc_tl else p_acc_tl
        notes.append(
            f"bonferroni 对照：每侧分摊 PFA/2={pfa / 2:.4g} → "
            f"m={m_half:.4f}, w={w_bonf:.6g}, AL_up={al_up_bonf:.6g}, "
            f"AL_lo={al_lo_bonf:.6g}（并集界 ≤ 目标）"
        )
        notes.append(
            f"joint_mvnormal：每侧 m={m:.4f}, AL_up={al_up_joint:.6g}, "
            f"AL_lo={al_lo_joint:.6g}；精确联合 PFA={joint_pfa:.6g} "
            f"(≤ 目标 {pfa:.4g}，对侧尾修正已含)"
        )
        al_upper, al_lower = al_up_joint, al_lo_joint
    else:
        pfa_at_limit = float(stats.norm.cdf(-w / u_std))  # = 1 − Φ(k·m) = pfa
        joint_pfa = None
        al_upper = tu - w if side == "upper" else None
        al_lower = tl + w if side == "lower" else None

    # 判定：guardbanded 规则（接受当且仅当落入接受限内）
    if side == "upper":
        decision = "accept" if v <= al_upper else "reject"
    elif side == "lower":
        decision = "accept" if v >= al_lower else "reject"
    else:
        decision = (
            "accept" if al_lower <= v <= al_upper else "reject"
        )
    # 裸规格符合性（不带保护带的对照，如实并列）
    if side == "upper":
        spec_conformity = "pass" if v <= tu else "fail"
    elif side == "lower":
        spec_conformity = "pass" if v >= tl else "fail"
    else:
        spec_conformity = "pass" if tl <= v <= tu else "fail"
    if decision == "accept" and spec_conformity == "fail":
        notes.append("guardbanded 判 accept 而裸规格 fail——不应发生，请检查口径")

    out: dict[str, Any] = {
        "ok": True,
        "side": side,
        "value": v,
        "u95": u95_v,
        "k": k_v,
        "u_std": u_std,
        "pfa_target": pfa,
        "m": m,
        "w": w,
        "spec": {"lower": tl, "upper": tu},
        "al_lower": al_lower,
        "al_upper": al_upper,
        "method": method,
        "decision": decision,
        "spec_conformity": spec_conformity,
        "pfa_at_limit": pfa_at_limit,
        "joint_pfa": joint_pfa,
        "notes": notes,
    }
    return out


# ═══ PT-2：过程能力指数置信区间 ═════════════════════════════════════════════


def cpk_ci(
    samples: Any,
    lsl: float | None,
    usl: float | None,
    confidence: float = 0.95,
    *,
    ppk_method: str = "normal",
) -> dict[str, Any]:
    """过程能力指数点估计+置信区间（PT-2，Bissell 1990 / Montgomery 口径）。

    - σ̂ = s/c4(n)（无偏）；Cp̂ = (USL−LSL)/(6σ̂)（双侧限才可算）；
    - Cp CI = Cp̂·√(χ²_{α/2,ν}/((n−1)c4²)) ～ Cp̂·√(χ²_{1−α/2,ν}/
      ((n−1)c4²))，ν=n−1（χ² pivot 反演恒等式由锚树回收）；
    - Cpk 点估计 = min((USL−x̄)/(3σ̂), (x̄−LSL)/(3σ̂))（双侧取近限，单侧
      用有极限）；
    - Cpk CI = Bissell 1990 正态近似 Cpk ± z_{1−α/2}·
      √(1/(9n)+Cpk²/(2(n−1)))——适用域 n≥30 且 Cpk∈[0.5,3]，域外降级
      标注（bissell_applicable=false + degraded=true + note，不冒充精确）；
    - Ppk（组内 s 同 σ̂ 源，Overall 口径）与百分位法（Clements 1989）
      normal/lognormal 双档——dB 域（已是对数域）走 normal，线性幅度
      呈对数正态走 lognormal。

    与 tolerance_allocation.cpk_from_tols（公差→Cpk 点估计重算）互补。

    Returns:
        {ok, n, mean, s, sigma_hat, c4, cp, cp_ci{lower,upper,method},
        cpk, cpk_ci{...}, ppk, ppk_percentile{...}, bissell_applicable,
        degraded, notes[]}
    """
    x = _sample_vector(samples, "samples")
    n = int(x.size)
    if n < 2:
        raise ValueError("samples 至少 2 个（s 与 c4 需要）")
    conf = _prob(confidence, "confidence")
    if lsl is None and usl is None:
        raise ValueError("lsl/usl 至少提供一个")
    lsl_v = _finite(lsl, "lsl") if lsl is not None else None
    usl_v = _finite(usl, "usl") if usl is not None else None
    if lsl_v is not None and usl_v is not None and lsl_v >= usl_v:
        raise ValueError(f"须 LSL < USL，得 LSL={lsl_v} >= USL={usl_v}")
    if ppk_method not in ("normal", "lognormal"):
        raise ValueError(f"ppk_method 须 normal|lognormal，得 {ppk_method!r}")

    mean = float(np.mean(x))
    s = float(np.std(x, ddof=1))
    if s <= 0.0:
        raise ValueError("样本标准差 s=0（常数序列）——能力指数不可定义")
    c4_n = c4(n)
    sigma_hat = s / c4_n
    alpha = 1.0 - conf
    nu = n - 1

    notes: list[str] = []
    cp: float | None = None
    cp_ci: dict[str, Any] | None = None
    if lsl_v is not None and usl_v is not None:
        cp = (usl_v - lsl_v) / (6.0 * sigma_hat)
        # χ² pivot 反演（σ̂=s/c4 代入后 c4 消去；保留规格书书写形）：
        lo = cp * math.sqrt(
            float(stats.chi2.ppf(alpha / 2.0, nu)) / (nu * c4_n**2)
        )
        hi = cp * math.sqrt(
            float(stats.chi2.ppf(1.0 - alpha / 2.0, nu)) / (nu * c4_n**2)
        )
        cp_ci = {"lower": lo, "upper": hi, "method": "chi2_pivot_exact"}

    margins: list[float] = []
    if usl_v is not None:
        margins.append((usl_v - mean) / (3.0 * sigma_hat))
    if lsl_v is not None:
        margins.append((mean - lsl_v) / (3.0 * sigma_hat))
    cpk = min(margins)

    se = math.sqrt(1.0 / (9.0 * n) + cpk**2 / (2.0 * nu))
    z = float(stats.norm.ppf(1.0 - alpha / 2.0))
    applicable = n >= BISSELL_MIN_N and BISSELL_CPK_LO <= cpk <= BISSELL_CPK_HI
    if not applicable:
        why: list[str] = []
        if n < BISSELL_MIN_N:
            why.append(f"n={n}<{BISSELL_MIN_N}")
        if not BISSELL_CPK_LO <= cpk <= BISSELL_CPK_HI:
            why.append(f"Cpk={cpk:.3g}∉[{BISSELL_CPK_LO},{BISSELL_CPK_HI}]")
        notes.append(
            "Bissell 正态近似域外降级（" + "、".join(why)
            + "）——区间按近似值如实给出，可靠性无保障"
        )
    cpk_ci_out = {
        "lower": cpk - z * se,
        "upper": cpk + z * se,
        "method": "bissell_normal_approx",
        "se": se,
    }

    margins_ppk: list[float] = []
    if usl_v is not None:
        margins_ppk.append((usl_v - mean) / (3.0 * s))
    if lsl_v is not None:
        margins_ppk.append((mean - lsl_v) / (3.0 * s))
    ppk = min(margins_ppk)
    ppk_pct = _ppk_percentile(x, lsl_v, usl_v, ppk_method)

    return {
        "ok": True,
        "n": n,
        "mean": mean,
        "s": s,
        "c4": c4_n,
        "sigma_hat": sigma_hat,
        "confidence": conf,
        "cp": cp,
        "cp_ci": cp_ci,
        "cpk": cpk,
        "cpk_ci": cpk_ci_out,
        "ppk": ppk,
        "ppk_percentile": ppk_pct,
        "bissell_applicable": applicable,
        "degraded": not applicable,
        "notes": notes,
    }


def _ppk_percentile(
    x: np.ndarray, lsl: float | None, usl: float | None, method: str
) -> dict[str, Any]:
    """百分位法 Ppk（Clements 1989）：σ_p=(X_99.865−X_0.135)/6，
    Ppk=min 距 / (3σ_p)。normal 档参数正态分位；lognormal 档 ln x 正态拟合。"""
    if method == "lognormal":
        ln_x = np.log(x)
        mu = float(np.mean(ln_x))
        sig = float(np.std(ln_x, ddof=1))
        dist_desc = "lognormal(ln 拟合)"
    else:
        mu = float(np.mean(x))
        sig = float(np.std(x, ddof=1))
        dist_desc = "normal(参数分位)"

    def q(p: float) -> float:
        return float(
            math.exp(mu + sig * float(stats.norm.ppf(p)))
            if method == "lognormal"
            else mu + sig * float(stats.norm.ppf(p))
        )

    x_lo, x_mid, x_hi = q(_PCT_LO), q(_PCT_MID), q(_PCT_HI)
    sigma_p = (x_hi - x_lo) / 6.0
    if sigma_p <= 0.0:
        raise ValueError("百分位退化为 0（分布过窄）——Ppk 不可定义")
    ests: list[float] = []
    if usl is not None:
        ests.append((usl - x_mid) / (3.0 * sigma_p))
    if lsl is not None:
        ests.append((x_mid - lsl) / (3.0 * sigma_p))
    return {
        "method": method,
        "distribution": dist_desc,
        "x_0.135pct": x_lo,
        "x_50pct": x_mid,
        "x_99.865pct": x_hi,
        "sigma_p": sigma_p,
        "ppk": min(ests),
    }


# ═══ PT-3：2 参数 Weibull 右删失 MLE ═══════════════════════════════════════


def _weibull_nll(beta: float, eta: float, xf: np.ndarray, xc: np.ndarray) -> float:
    """2 参数 Weibull 负对数似然（右删失；解析式，loc=0 钉死）。

    ln L = Σ_f [ln(β/η) + (β−1)(ln x_f − ln η) − (x_f/η)^β] − Σ_c (x_c/η)^β
    """
    t1 = np.log(beta / eta) + (beta - 1.0) * (np.log(xf) - math.log(eta)) - (
        (xf / eta) ** beta
    )
    t2 = -((xc / eta) ** beta) if xc.size else np.zeros(1)
    return -float(t1.sum() + t2.sum())


def _censored_data(xf: np.ndarray, xc: np.ndarray) -> Any:
    """构造 CensoredData（scipy 1.18 新签名优先，1.11–1.17 旧签名回退）。"""
    if xc.size:
        try:
            # scipy >= 1.18: CensoredData(uncensored, *, right=...)
            return stats.CensoredData(xf, right=xc)
        except TypeError:
            # scipy 1.11–1.17: CensoredData(values, censored=mask)
            values = np.concatenate([xf, xc])
            mask = np.concatenate(
                [np.zeros(xf.size, dtype=int), np.ones(xc.size, dtype=int)]
            )
            return stats.CensoredData(values, censored=mask)
    return stats.CensoredData(xf)


def _numeric_hessian(
    f_vec: Any, p: tuple[float, float], h: tuple[float, float]
) -> np.ndarray:
    """2×2 中心差分 Hessian（观测 Fisher 信息的无偏数值路径）。

    ``f_vec(vec) -> float``（vec=(beta, eta) 二元向量）；扰动按轴组装，
    禁止把轴分量错配到标量参数位（首版踩坑：ei[0]/ej[1] 硬索引把非对角
    扰动打错轴 → Hessian 退化为奇异矩阵）。
    """
    p_arr = np.asarray(p, dtype=float)
    hess = np.zeros((2, 2))
    for i in range(2):
        for j in range(2):
            ei = np.zeros(2)
            ei[i] = h[i]
            ej = np.zeros(2)
            ej[j] = h[j]
            hess[i, j] = (
                f_vec(p_arr + ei + ej)
                - f_vec(p_arr + ei - ej)
                - f_vec(p_arr - ei + ej)
                + f_vec(p_arr - ei - ej)
            ) / (4.0 * h[i] * h[j])
    return hess


def weibull_mle(
    failures: Any,
    censored: Any = None,
    *,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """2 参数 Weibull 右删失 MLE 与区间（PT-3）。

    Args:
        failures: 失效时间序列（>0，loc=0 钉死）。
        censored: 右删失时间序列（>0，删失侧观察时长；可 None/空）。
        confidence: 置信水平（(0,1)，缺省 0.95）。

    Returns:
        {ok, n_failures, n_censored, beta, eta, loglik, nll_min,
        se_beta, se_eta, cov{beta_beta,...}, ci_beta{fisher,lr},
        ci_eta{fisher,lr}, b10, b10_ci{fisher_lower, lr{lower,upper}},
        n50, notes[]}
        —— Fisher 口径为观测信息数值 Hessian 逆的正态近似；LR 口径为
        剖面似然比 2ΔlnL ≤ χ²_{1−α,1} 的 brentq 求根带。B10 置信下限：
        Fisher=delta 法单侧下界、LR=剖面下根双口径并列。

    Raises:
        ValueError: 入参非法或拟合不收敛（fit 返回非有限）。
    """
    xf = _sample_vector(failures, "failures", positive=True)
    xc = (
        _sample_vector(censored, "censored", positive=True)
        if censored is not None
        else np.zeros(0)
    )
    conf = _prob(confidence, "confidence")
    alpha = 1.0 - conf
    z_two = float(stats.norm.ppf(1.0 - alpha / 2.0))
    z_one = float(stats.norm.ppf(conf))

    data = _censored_data(xf, xc)
    beta, loc, eta = stats.weibull_min.fit(data, floc=0)
    if loc != 0.0 or not (math.isfinite(beta) and math.isfinite(eta)) or beta <= 0 or eta <= 0:
        raise ValueError(
            f"weibull_min.fit 不收敛或 loc≠0：beta={beta!r}, loc={loc!r}, eta={eta!r}"
        )

    nll_min = _weibull_nll(beta, eta, xf, xc)
    # 观测 Fisher 信息（数值 Hessian）；步长按参数尺度 1e-4（中心差分
    # 二阶导的平衡点，实测对步长 1e-3..1e-5 稳定）
    hess = _numeric_hessian(
        lambda vec: _weibull_nll(float(vec[0]), float(vec[1]), xf, xc),
        (beta, eta),
        (1e-4 * beta, 1e-4 * eta),
    )
    cov = np.linalg.inv(hess)
    cov = 0.5 * (cov + cov.T)  # 对称化（数值噪声）
    se_beta = math.sqrt(float(cov[0, 0]))
    se_eta = math.sqrt(float(cov[1, 1]))

    def _lr_root(
        prof: Any, lo_guess: float, hi_guess: float, bracket: tuple[float, float]
    ) -> tuple[float, float]:
        """剖面似然比双根：2(nll_prof(θ)−nll_min)=χ²_{1−α,1}。"""
        cut = float(stats.chi2.ppf(1.0 - alpha, 1)) / 2.0

        def g(t: float) -> float:
            return prof(t) - nll_min - cut

        lo = float(optimize.brentq(g, bracket[0], lo_guess, rtol=1e-10))
        hi = float(optimize.brentq(g, hi_guess, bracket[1], rtol=1e-10))
        return lo, hi

    def _prof_beta(b: float) -> float:
        if b <= 0:
            return math.inf
        r = optimize.minimize_scalar(
            lambda e: _weibull_nll(b, e, xf, xc),
            bounds=(eta * 0.05, eta * 20.0),
            method="bounded",
        )
        return float(r.fun)

    def _prof_eta(e: float) -> float:
        if e <= 0:
            return math.inf
        r = optimize.minimize_scalar(
            lambda b: _weibull_nll(b, e, xf, xc),
            bounds=(beta * 0.05, beta * 20.0),
            method="bounded",
        )
        return float(r.fun)

    ci_beta_lr = _lr_root(_prof_beta, beta, beta, (beta * 0.05, beta * 20.0))
    ci_eta_lr = _lr_root(_prof_eta, eta, eta, (eta * 0.05, eta * 20.0))

    # B10 = η·(−ln 0.9)^{1/β}；delta 法方差（∇g·Cov·∇g）
    kk = -math.log(0.9)
    b10 = eta * kk ** (1.0 / beta)
    grad = np.array(
        [-b10 * math.log(kk) / beta**2, b10 / eta]
    )
    var_b10 = float(grad @ cov @ grad)
    b10_fisher_lower = b10 - z_one * math.sqrt(var_b10)

    def _prof_b10(b10v: float) -> float:
        r = optimize.minimize_scalar(
            lambda b: _weibull_nll(b, b10v / kk ** (1.0 / b), xf, xc),
            bounds=(beta * 0.05, beta * 20.0),
            method="bounded",
        )
        return float(r.fun)

    b10_lr_lo, b10_lr_hi = _lr_root(
        _prof_b10, b10, b10, (b10 * 0.05, b10 * 5.0)
    )

    return {
        "ok": True,
        "n_failures": int(xf.size),
        "n_censored": int(xc.size),
        "beta": float(beta),
        "eta": float(eta),
        "loglik": -nll_min,
        "se_beta": se_beta,
        "se_eta": se_eta,
        "cov": {
            "beta_beta": float(cov[0, 0]),
            "beta_eta": float(cov[0, 1]),
            "eta_eta": float(cov[1, 1]),
        },
        "confidence": conf,
        "ci_beta": {
            "fisher": [float(beta - z_two * se_beta), float(beta + z_two * se_beta)],
            "lr": list(ci_beta_lr),
        },
        "ci_eta": {
            "fisher": [float(eta - z_two * se_eta), float(eta + z_two * se_eta)],
            "lr": list(ci_eta_lr),
        },
        "b10": b10,
        "b10_ci": {
            "fisher_lower": float(b10_fisher_lower),
            "lr": [b10_lr_lo, b10_lr_hi],
        },
        "n50": eta * math.log(2.0) ** (1.0 / beta),
        "notes": [],
    }
