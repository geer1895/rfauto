"""QM-8 锚漂移统计线补强（round16 QM-8；P2/S）：广义 ESD + EWMA + CUSUM
三证据组合（SPC 纯统计内核，零 IO，与 core/anchor_drift 同层同纪律）。

与 QW-16 既有面（core/anchor_drift：Mann-Kendall + 分布指纹差分）的关系：
**组合不替代**——本模块是三条新增证据线的纯内核；既有 anchor_drift_report
零改动（已合流面），两报告面可在调用方并读（本模块 zero import 对方）。

方法口径（NIST/SPC 标准过程）：
- **广义 ESD**（Rosner 1983；NIST SEMATECH §1.3.5.17）：逐轮剔除
  ``R_i = max|x_j−x̄|/s`` 最大的点，临界值
  ``λ_i = (n−i)·t_{p_i,n−i−1} / sqrt((n−i−1+t²)(n−i−2+i))``、
  ``p_i = 1−α/(2(n−i+1))``；离群数 = 满足 ``R_i>λ_i`` 的最大 i。t 分位由
  scipy.stats 惰性提供（core 已有 scipy 先例：alt_planning/aaa）。
- **EWMA 控制图**（NIST §6.3.2.2 / Montgomery §9）：``z_i = λx_i+(1−λ)z_{i−1}``，
  控制限 ``z̄_i ± L·σ·sqrt(λ/(2−λ)·(1−(1−λ)^{2i}))``。
- **CUSUM 叠加和**（Montgomery §9标准表格式）：标准化后
  ``C⁺ = max(0, C⁺+z−k)``、``C⁻ = max(0, C⁻−z−k)``，越 h 报警
  （缺省 k=0.5/h=4，ARL₀≈168 口径）。

σ 来源纪律（铁律 7：数值只在确定性内核；短序列不内估）：EWMA/CUSUM 需要
σ，**必须由调用方显式声明**（锚的注册表 uncertainty、历史批次长期 σ 等
确定性外部源）——缺声明时该两线如实 skipped（reason 留痕），**不从同一
短序列内估 σ 虚构精度**（#118 家族：估计量裁判自己算自己）。广义 ESD 自
标准化（s 由序列本身算）不需要外部 σ，但点数下限独立生效。

时序长度支撑性（#122 如实口径，任务书预判）：
- ESD 有效域 n≥10（NIST 实践下限；Rosner 表定 n≥25 更稳——证据档位随
  n 如实降级注记）；
- EWMA/CUSUM 有效域 n≥8（暖机期小于此长度的信号被初始化支配）；
- 全序列 n < 8 → verdict=``insufficient``，三线**一律不算**（不硬算），
  reasons 记录各线可用性。

verdict 组合（与 anchor_drift 两线规则同构）：已算证据线命中 ≥2 →
``drifted``；恰 1 → ``warning``；0 → ``stable``；n<8 → ``insufficient``。
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

__all__ = [
    "ALPHA_DEFAULT",
    "CUSUM_H_DEFAULT",
    "CUSUM_K_DEFAULT",
    "CUSUM_MIN_N",
    "ESD_MIN_N",
    "EWMA_LAMBDA_DEFAULT",
    "EWMA_L_DEFAULT",
    "EWMA_MIN_N",
    "SERIES_MIN_N",
    "anchor_drift_spc_report",
    "cusum_test",
    "ewma_control",
    "generalized_esd_test",
]

ALPHA_DEFAULT = 0.05
ESD_MIN_N = 10          #: 广义 ESD 有效域下限（NIST 实践口径）
EWMA_MIN_N = 8          #: EWMA 暖机有效域下限
CUSUM_MIN_N = 8         #: CUSUM 稳态有效域下限
SERIES_MIN_N = 8        #: 报告整体最低点数（不足=insufficient，不算）
EWMA_LAMBDA_DEFAULT = 0.3
EWMA_L_DEFAULT = 2.7    #: λ=0.3 常配 L=2.7（Montgomery 表，ARL₀≈370）
CUSUM_K_DEFAULT = 0.5   #: 容许量（σ 单位；1σ 偏移最优检出）
CUSUM_H_DEFAULT = 4.0   #: 判警限（k=0.5 配 h=4，ARL₀≈168 口径）


def _as_floats(values: Sequence[float]) -> list[float]:
    """数值收敛（显式拒收 bool/非有限值——anchor_drift._as_float 同纪律）。"""
    out: list[float] = []
    for i, v in enumerate(values):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"values[{i}] 非数值: {v!r}")
        f = float(v)
        if not math.isfinite(f):
            raise ValueError(f"values[{i}] 非有限数值: {v!r}")
        out.append(f)
    return out


def _t_ppf(p: float, df: int) -> float:
    """Student-t 分位（scipy 惰性；core 既有 scipy 先例同款惰性导入）。"""
    try:
        from scipy.stats import t as _t_dist
    except ImportError as exc:  # pragma: no cover — scipy 为仓内既有依赖
        raise RuntimeError(
            "广义 ESD 需要 scipy（t 分布分位）；环境缺 scipy 时如实报错，"
            "不以正态近似冒充精确临界值") from exc
    return float(_t_dist.ppf(p, df))


def generalized_esd_test(values: Sequence[float], *,
                         max_outliers: int | None = None,
                         alpha: float = ALPHA_DEFAULT) -> dict[str, Any]:
    """广义 ESD 极值离群检验（Rosner 1983 / NIST SEMATECH §1.3.5.17）。

    Args:
        values: 数值序列（显式拒收 bool/非有限值）。
        max_outliers: 检验上限 R（缺省 min(10, n//2)）。
        alpha: 显著性水平（缺省 0.05）。

    Returns:
        {n, eligible, alpha, max_outliers_tested, n_outliers,
         outlier_indices, statistics, critical_values, note}；
        ``eligible=False`` = n < ESD_MIN_N（三线不硬算纪律，空表+reason）。
        序列全等（s=0）→ n_outliers=0 + honest note（无常散布可判）。
    """
    x = _as_floats(values)
    n = len(x)
    if n < ESD_MIN_N:
        return {"eligible": False, "n": n,
                "reason": f"n={n} < ESD 有效域下限 {ESD_MIN_N}（不硬算）"}
    work: list[tuple[float, int]] = [(v, j) for j, v in enumerate(x)]
    r_max = int(max_outliers) if max_outliers is not None else min(10, n // 2)
    r_max = max(1, min(r_max, n - 2))
    stats_: list[float] = []
    crits: list[float] = []
    removed_orig_idx: list[int] = []
    for i in range(1, r_max + 1):
        m = len(work)
        mean = sum(v for v, _j in work) / m
        var = sum((v - mean) ** 2 for v, _j in work) / (m - 1)
        s = math.sqrt(var)
        if s <= 0.0:
            break  # 剩余点全等：无常散布，继续检验=除零虚构
        j_max = max(range(m), key=lambda j: (abs(work[j][0] - mean), -j))
        r_i = abs(work[j_max][0] - mean) / s
        p_i = 1.0 - float(alpha) / (2.0 * (n - i + 1))
        df = n - i - 1
        t_i = _t_ppf(p_i, df)
        lam_i = (n - i) * t_i / math.sqrt(
            (n - i - 1 + t_i * t_i) * (n - i - 2 + i))
        stats_.append(r_i)
        crits.append(lam_i)
        removed_orig_idx.append(work.pop(j_max)[1])
    n_out = 0
    for i in range(len(stats_)):
        if stats_[i] > crits[i]:
            n_out = i + 1
    return {
        "eligible": True, "n": n, "alpha": float(alpha),
        "max_outliers_tested": len(stats_),
        "n_outliers": n_out,
        "outlier_indices": sorted(removed_orig_idx[:n_out]),
        "statistics": stats_, "critical_values": crits,
        "note": (f"n={n} 在 NIST 实践下限 {ESD_MIN_N}（Rosner 表 n≥25 更稳），"
                 if n < 25 else "") + "广义 ESD（Rosner 1983）",
    }


def ewma_control(values: Sequence[float], *, sigma: float | None,
                 target: float | None = None,
                 lam: float = EWMA_LAMBDA_DEFAULT,
                 L: float = EWMA_L_DEFAULT) -> dict[str, Any]:
    """EWMA 控制图（NIST §6.3.2.2）：返回 ewma 序列/逐点控制限/越限步。

    σ 必须显式声明（锚注册表 uncertainty 等确定性外部源）；缺声明如实
    skipped（不从同序列内估 σ，#118 家族纪律）。n < EWMA_MIN_N →
    eligible=False 不硬算。
    """
    x = _as_floats(values)
    n = len(x)
    if n < EWMA_MIN_N:
        return {"eligible": False, "n": n,
                "reason": f"n={n} < EWMA 有效域下限 {EWMA_MIN_N}（不硬算）"}
    if sigma is None or not (float(sigma) > 0.0):
        return {"eligible": False, "n": n,
                "reason": "σ 未显式声明（EWMA/CUSUM 不从同一短序列内估 σ——"
                          "声明锚 uncertainty 等确定性外部源后可判）"}
    s = float(sigma)
    mu0 = float(target) if target is not None else sum(x) / n
    z = mu0
    ewma_series: list[float] = []
    ucl: list[float] = []
    lcl: list[float] = []
    breach_at: int | None = None
    for i in range(1, n + 1):
        z = float(lam) * x[i - 1] + (1.0 - float(lam)) * z
        factor = (float(lam) / (2.0 - float(lam))) \
            * (1.0 - (1.0 - float(lam)) ** (2 * i))
        limit = float(L) * s * math.sqrt(factor)
        ewma_series.append(z)
        ucl.append(mu0 + limit)
        lcl.append(mu0 - limit)
        if breach_at is None and not (mu0 - limit <= z <= mu0 + limit):
            breach_at = i
    return {"eligible": True, "n": n, "sigma": s,
            "sigma_source": "caller_declared", "target": mu0,
            "lambda": float(lam), "L": float(L),
            "ewma": ewma_series, "ucl": ucl, "lcl": lcl,
            "breach_at": breach_at,
            "signal": breach_at is not None}


def cusum_test(values: Sequence[float], *, sigma: float | None,
               target: float | None = None,
               k: float = CUSUM_K_DEFAULT,
               h: float = CUSUM_H_DEFAULT) -> dict[str, Any]:
    """双侧标准化 CUSUM（Montgomery §9 表格式）：C⁺/C⁻ 越 h 报警。

    σ/target 语义与 :func:`ewma_control` 同（σ 显式声明、短序列不内估；
    target 缺省=序列均值并如实标注）。n < CUSUM_MIN_N → eligible=False。
    """
    x = _as_floats(values)
    n = len(x)
    if n < CUSUM_MIN_N:
        return {"eligible": False, "n": n,
                "reason": f"n={n} < CUSUM 有效域下限 {CUSUM_MIN_N}（不硬算）"}
    if sigma is None or not (float(sigma) > 0.0):
        return {"eligible": False, "n": n,
                "reason": "σ 未显式声明（EWMA/CUSUM 不从同一短序列内估 σ——"
                          "声明锚 uncertainty 等确定性外部源后可判）"}
    s = float(sigma)
    mu0 = float(target) if target is not None else sum(x) / n
    c_pos = c_neg = 0.0
    c_pos_series: list[float] = []
    c_neg_series: list[float] = []
    breach_at: int | None = None
    breach_side: str | None = None
    for i, v in enumerate(x, start=1):
        z = (v - mu0) / s
        c_pos = max(0.0, c_pos + z - float(k))
        c_neg = max(0.0, c_neg - z - float(k))
        c_pos_series.append(c_pos)
        c_neg_series.append(c_neg)
        if breach_at is None:
            if c_pos > float(h):
                breach_at, breach_side = i, "high"
            elif c_neg > float(h):
                breach_at, breach_side = i, "low"
    return {"eligible": True, "n": n, "sigma": s,
            "sigma_source": "caller_declared",
            "target": mu0,
            "target_source": ("caller_declared" if target is not None
                              else "series_mean"),
            "k": float(k), "h": float(h),
            "c_plus": c_pos_series, "c_minus": c_neg_series,
            "breach_at": breach_at, "breach_side": breach_side,
            "signal": breach_at is not None}


def anchor_drift_spc_report(values: Sequence[float], *,
                            sigma: float | None = None,
                            target: float | None = None,
                            alpha: float = ALPHA_DEFAULT,
                            ewma_lambda: float = EWMA_LAMBDA_DEFAULT,
                            ewma_L: float = EWMA_L_DEFAULT,
                            cusum_k: float = CUSUM_K_DEFAULT,
                            cusum_h: float = CUSUM_H_DEFAULT,
                            ) -> dict[str, Any]:
    """QM-8 三证据组合报告（广义 ESD + EWMA + CUSUM；核心入口）。

    语义（docstring 即契约，与 core/anchor_drift 组合规则同构）：
    - ``insufficient``：n < SERIES_MIN_N（=8）——三线一律不算（不硬算），
      reasons 记录各线可用性与缺 σ 情况；
    - ``drifted``/``warning``/``stable``：按已算出的证据线命中数
      （≥2 / 1 / 0）；skipped 线不计入命中，也不计入"两线"所需基数——
      单线命中且另一线 skipped 时上限同为 warning（保守不升级）。

    Returns:
        {ok, verdict, n, n_lines_computed, fired_lines, esd, ewma, cusum,
         reasons}；JSON 友好。
    """
    x = _as_floats(values)
    n = len(x)
    reasons: list[str] = []
    if n < SERIES_MIN_N:
        reasons.append(
            f"n={n} < 报告最低点数 {SERIES_MIN_N}：三证据线一律不算"
            "（锚时序积累前如实 insufficient，不硬算不凑数，#122）")
        if n < ESD_MIN_N:
            reasons.append(f"广义 ESD 需 n≥{ESD_MIN_N}")
        if n < EWMA_MIN_N:
            reasons.append(f"EWMA 需 n≥{EWMA_MIN_N}")
        if n < CUSUM_MIN_N:
            reasons.append(f"CUSUM 需 n≥{CUSUM_MIN_N}")
        if sigma is None:
            reasons.append("σ 未声明（EWMA/CUSUM 另需确定性外部 σ 源）")
        return {"ok": True, "verdict": "insufficient", "n": n,
                "n_lines_computed": 0, "fired_lines": [],
                "esd": None, "ewma": None, "cusum": None,
                "reasons": reasons}

    esd = generalized_esd_test(x, alpha=alpha)
    ewma = ewma_control(x, sigma=sigma, target=target,
                        lam=ewma_lambda, L=ewma_L)
    cusum = cusum_test(x, sigma=sigma, target=target,
                       k=cusum_k, h=cusum_h)

    fired: list[str] = []
    computed = 0
    if esd.get("eligible"):
        computed += 1
        if esd["n_outliers"] > 0:
            fired.append("esd")
    else:
        reasons.append(f"esd: {esd.get('reason')}")
    for name, rep in (("ewma", ewma), ("cusum", cusum)):
        if rep.get("eligible"):
            computed += 1
            if rep.get("signal"):
                fired.append(name)
        else:
            reasons.append(f"{name}: {rep.get('reason')}")

    if computed == 0:
        verdict = "insufficient"
        reasons.append("无可用证据线（点数/σ 声明不足）——insufficient 如实")
    elif len(fired) >= 2:
        verdict = "drifted"
        reasons.append(f"≥2 证据线成立: {fired}")
    elif len(fired) == 1:
        verdict = "warning"
        reasons.append(f"单证据线成立（上限 warning）: {fired}")
    else:
        verdict = "stable"
        reasons.append("已算证据线均不成立")
    return {"ok": True, "verdict": verdict, "n": n,
            "n_lines_computed": computed, "fired_lines": fired,
            "esd": esd, "ewma": ewma, "cusum": cusum,
            "reasons": reasons}
