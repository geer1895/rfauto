"""QW-16 锚漂移预警轻量版（Mann-Kendall 趋势 + 分布指纹，纯统计零 IO）。

分层：core leaf（零 IO、零外部依赖，同 anchors.py 纪律）；service 面
（anchors_service.anchor_drift_status）与本模块组合出报告。

数据积累期语义（规格书如实口径）：锚注册表当前每锚只落**单点**
``last_verified.residual``（knowledge/anchors.yaml），无残差**序列**数据源。
本批落统计内核 + "指纹快照 + 两次快照差分"机制——现在存快照（service 层
record_anchor_drift_snapshot），下次起有可比对的历史；等 revalidate 记录
积累出真序列后，同一报告面自动升级为完整序列趋势判读（接口不变）。

verdict 语义（组合规则，docstring 即契约）：
- ``no_data``：无任何输入（空序列/空快照表）；
- ``insufficient``：有输入但证据线不足（序列 n<4；快照数<2）；
- ``stable`` / ``warning`` / ``drifted``：按两条独立证据线组合——
  ①Mann-Kendall 趋势线（残差序列或快照均值的序列在 alpha 下显著递增/递减）；
  ②分布指纹差分线（前段 vs 后段 / 首快照 vs 末快照的均值相对漂移或
  标准差比值越限）。两线同时成立 → ``drifted``；恰一线成立 → ``warning``
  （轻量预警的本义：单线证据先告警复核，不直接判漂移）；两线皆不成立 →
  ``stable``。只有一条证据线可用时，命中该线上限 ``warning``。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "ALPHA_DEFAULT",
    "MEAN_SHIFT_REL_MAX_DEFAULT",
    "STD_RATIO_MAX_DEFAULT",
    "anchor_drift_report",
    "drift_fingerprint",
    "mann_kendall",
]

ALPHA_DEFAULT = 0.05
#: 指纹差分线阈值：均值相对漂移（以前段分布尺度 max(|mean|, std) 归一）
MEAN_SHIFT_REL_MAX_DEFAULT = 0.5
#: 指纹差分线阈值：标准差比值越限（>ratio 或 <1/ratio 记变化）
STD_RATIO_MAX_DEFAULT = 2.0

#: MK 正态近似最低点数（n<3 时 S 检验无意义，报 insufficient 上层处理）
_MK_MIN_N = 3
#: 序列模式劈半判指纹的最低点数
_SPLIT_MIN_N = 4

_TREND_UP = "increasing"
_TREND_DOWN = "decreasing"
_TREND_NONE = "no_trend"


def _as_float(value: Any, what: str) -> float:
    """数值收敛（显式拒收 bool——float(True)=1.0 静默污染统计，df7⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{what} 收到 bool（显式拒收，防 True→1.0 污染）")
    if not isinstance(value, (int, float)):
        raise ValueError(f"{what} 非数值: {value!r}")
    out = float(value)
    if math.isnan(out) or math.isinf(out):
        raise ValueError(f"{what} 非有限数值: {value!r}")
    return out


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def mann_kendall(series: Sequence[float], alpha: float = ALPHA_DEFAULT,
                 ) -> dict[str, Any]:
    """Mann-Kendall 非参数趋势检验（Mann 1945; Kendall 1975 标准口径）。

    统计量 ``S = Σ_{i<j} sign(x_j − x_i)``；方差含结（tie）校正
    ``var(S) = [n(n−1)(2n+5) − Σ_t t(t−1)(2t+5)] / 18``（t 为各组结长）；
    z 取连续性校正 ``(S−1)/√var(S)``（S>0）、``(S+1)/√var(S)``（S<0）、
    0（S=0 或 var=0）；双侧 p 值 ``p = erfc(|z|/√2) = 2(1−Φ(|z|))``。
    trend 按 ``p ≤ alpha`` 判 increasing/decreasing，否则 no_trend。

    Args:
        series: 数值序列（时间序；显式拒收 bool/非有限值）。
        alpha: 显著性水平（缺省 0.05）。

    Returns:
        {n, S, var_S, z, p, trend, alpha}；n<_MK_MIN_N 或空 → ValueError
        （调用方 report 层负责 insufficient 分支）。
    """
    values = [_as_float(v, f"series[{i}]") for i, v in enumerate(series)]
    n = len(values)
    if n < _MK_MIN_N:
        raise ValueError(
            f"mann_kendall 至少需要 {_MK_MIN_N} 个点，实际 {n}"
            "（更短序列由 anchor_drift_report 判 insufficient）")
    s_stat = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            s_stat += _sign(values[j] - values[i])
    # 结（tie）分组
    tie_term = 0.0
    counts: dict[float, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    for t in counts.values():
        if t > 1:
            tie_term += t * (t - 1) * (2 * t + 5)
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if var_s <= 0.0 or s_stat == 0:
        z = 0.0
    elif s_stat > 0:
        z = (s_stat - 1) / math.sqrt(var_s)
    else:
        z = (s_stat + 1) / math.sqrt(var_s)
    p = math.erfc(abs(z) / math.sqrt(2.0))
    trend = ((_TREND_UP if s_stat > 0 else _TREND_DOWN)
             if p <= float(alpha) else _TREND_NONE)
    return {"n": n, "S": s_stat, "var_S": var_s, "z": z, "p": p,
            "trend": trend, "alpha": float(alpha)}


def _quantile(sorted_vals: list[float], q: float) -> float:
    """线性插值分位数（与 numpy percentile 默认 'linear' 法同式，便于对拍）。"""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def drift_fingerprint(values: Sequence[float]) -> dict[str, Any]:
    """分布指纹（{n, mean, std, median, q25, q75, iqr}）。

    std 为样本标准差（ddof=1；n=1 时如实 0.0）；分位数线性插值
    （numpy 'linear' 同式）。空序列 → ValueError。
    """
    vals = sorted(_as_float(v, f"values[{i}]") for i, v in enumerate(values))
    n = len(vals)
    if n == 0:
        raise ValueError("drift_fingerprint 不接受空序列")
    mean = sum(vals) / n
    if n >= 2:
        var = sum((v - mean) ** 2 for v in vals) / (n - 1)
        std = math.sqrt(var)
    else:
        std = 0.0
    median = _quantile(vals, 0.5)
    q25 = _quantile(vals, 0.25)
    q75 = _quantile(vals, 0.75)
    return {"n": n, "mean": mean, "std": std, "median": median,
            "q25": q25, "q75": q75, "iqr": q75 - q25}


def _shift_detail(fp_first: dict[str, Any], fp_last: dict[str, Any],
                  mean_shift_rel_max: float,
                  std_ratio_max: float) -> dict[str, Any]:
    """两分布指纹的差分（均值相对漂移 + 标准差比值），附越限旗标。

    均值相对漂移以前段分布尺度 ``max(|mean|, std, tiny)`` 归一——残差均值
    可近零，纯 |mean| 归一会把噪声膨胀成假漂移（尺度感知）。
    """
    mean_a = float(fp_first["mean"])
    mean_b = float(fp_last["mean"])
    std_a = float(fp_first["std"])
    std_b = float(fp_last["std"])
    scale = max(abs(mean_a), std_a, 1e-12)
    mean_shift_rel = abs(mean_b - mean_a) / scale
    std_ratio = ((1.0 if std_b <= 0.0 else math.inf) if std_a <= 0.0
                 else std_b / std_a)
    mean_flag = mean_shift_rel > mean_shift_rel_max
    std_flag = std_ratio > std_ratio_max or std_ratio < 1.0 / std_ratio_max
    return {
        "mean_shift_rel": mean_shift_rel,
        "std_ratio": std_ratio,
        "mean_shift_flag": bool(mean_flag),
        "std_flag": bool(std_flag),
        "shift_flag": bool(mean_flag or std_flag),
        "fingerprint_first": fp_first,
        "fingerprint_last": fp_last,
        "thresholds": {"mean_shift_rel_max": mean_shift_rel_max,
                       "std_ratio_max": std_ratio_max},
    }


def _combine(lines: list[tuple[str, bool]], *,
             n_points: int, mode: str, alpha: float,
             trend: dict[str, Any] | None,
             shift: dict[str, Any] | None,
             reasons: list[str]) -> dict[str, Any]:
    """证据线组合 → verdict（两线 drifted / 一线 warning / 零线 stable）。"""
    fired = [name for name, flag in lines if flag]
    if len(fired) >= 2:
        verdict = "drifted"
        reasons.append(f"双证据线成立: {fired}")
    elif len(fired) == 1:
        verdict = "warning"
        reasons.append(f"单证据线成立（上限 warning）: {fired}")
    else:
        verdict = "stable"
        reasons.append("证据线均不成立")
    return {"ok": True, "verdict": verdict, "mode": mode, "n_points": n_points,
            "alpha": float(alpha), "trend": trend,
            "fingerprint_shift": shift, "reasons": reasons}


def _snapshot_values(snapshot: Any, idx: int) -> tuple[Any, list[float]]:
    """快照条目 → (at 标签, 残差批)；非法结构 ValueError。"""
    if not isinstance(snapshot, Mapping):
        raise ValueError(f"snapshots[{idx}] 非映射: {snapshot!r}")
    if "values" not in snapshot:
        raise ValueError(
            f"snapshots[{idx}] 缺 values 键（快照= {{at?, values: [残差批]}}）")
    batch = [_as_float(v, f"snapshots[{idx}].values[{i}]")
             for i, v in enumerate(snapshot["values"])]
    if not batch:
        raise ValueError(f"snapshots[{idx}].values 为空")
    return snapshot.get("at"), batch


def anchor_drift_report(
    series_or_snapshots: Sequence[float] | Sequence[Mapping[str, Any]],
    alpha: float = ALPHA_DEFAULT,
    *,
    mean_shift_rel_max: float = MEAN_SHIFT_REL_MAX_DEFAULT,
    std_ratio_max: float = STD_RATIO_MAX_DEFAULT,
) -> dict[str, Any]:
    """锚残差趋势 + 分布指纹组合报告（QW-16 主入口，纯函数零 IO）。

    两种输入口径（按元素类型自动判别，混搭 ValueError）：
    - **序列模式**：纯数值序列（时间序残差）。趋势线 = 全序列 MK 检验；
      指纹差分线 = 时序劈半（前半 vs 后半）指纹对照。
    - **快照模式**：映射序列，每项 ``{at?: str, values: [残差批]}``
      （指纹快照机制的存储形态）。趋势线 = 快照均值序列的 MK 检验
      （快照数 ≥ _MK_MIN_N 才可判）；指纹差分线 = 首快照 vs 末快照。

    verdict 语义见模块 docstring（no_data/insufficient/stable/warning/
    drifted 的完整组合规则）。

    Args:
        series_or_snapshots: 残差序列或快照映射序列。
        alpha: MK 显著性水平（缺省 0.05）。
        mean_shift_rel_max: 指纹差分线·均值相对漂移阈值（缺省 0.5）。
        std_ratio_max: 指纹差分线·标准差比值阈值（缺省 2.0）。

    Returns:
        {ok, verdict, mode, n_points, n_snapshots?, trend, fingerprint,
        fingerprint_shift, reasons, thresholds}；恒 ok=True（判定结果
        如实在 verdict 里，输入非法才是异常路径）。
    """
    if not series_or_snapshots:
        return {"ok": True, "verdict": "no_data", "mode": "empty",
                "n_points": 0, "trend": None, "fingerprint": None,
                "fingerprint_shift": None,
                "reasons": ["输入为空（empty_series 如实口径）"],
                "thresholds": {"alpha": float(alpha),
                               "mean_shift_rel_max": mean_shift_rel_max,
                               "std_ratio_max": std_ratio_max}}
    items = list(series_or_snapshots)
    all_numeric = all(not isinstance(x, Mapping) for x in items)
    all_mapping = all(isinstance(x, Mapping) for x in items)
    if all_numeric:
        series = [_as_float(v, f"series[{i}]") for i, v in enumerate(items)]
        fp = drift_fingerprint(series)
        if len(series) < _SPLIT_MIN_N:
            return {"ok": True, "verdict": "insufficient", "mode": "series",
                    "n_points": len(series), "trend": None,
                    "fingerprint": fp, "fingerprint_shift": None,
                    "reasons": [f"序列点数 {len(series)} < "
                                f"{_SPLIT_MIN_N}（趋势/劈半差分不可判；"
                                "指纹快照机制积累中）"],
                    "thresholds": {"alpha": float(alpha),
                                   "mean_shift_rel_max": mean_shift_rel_max,
                                   "std_ratio_max": std_ratio_max}}
        half = len(series) // 2
        fp_first = drift_fingerprint(series[:half])
        fp_last = drift_fingerprint(series[half:])
        shift = _shift_detail(fp_first, fp_last, mean_shift_rel_max,
                              std_ratio_max)
        mk = mann_kendall(series, alpha=alpha)
        trend_flag = mk["trend"] != _TREND_NONE
        reasons = [
            f"MK 趋势线: trend={mk['trend']} p={mk['p']:.4g} "
            f"z={mk['z']:.4g}（alpha={alpha}）",
            f"指纹差分线（劈半 n={half}+{len(series) - half}）: "
            f"mean_shift_rel={shift['mean_shift_rel']:.4g} "
            f"std_ratio={shift['std_ratio']:.4g}",
        ]
        out = _combine([("trend", trend_flag), ("fingerprint_shift",
                                                 shift["shift_flag"])],
                       n_points=len(series), mode="series", alpha=alpha,
                       trend=mk, shift=shift, reasons=reasons)
        out["fingerprint"] = fp
        return out
    if all_mapping:
        snaps = [_snapshot_values(x, i) for i, x in enumerate(items)]
        fp_last = drift_fingerprint(snaps[-1][1])
        if len(snaps) < 2:
            return {"ok": True, "verdict": "insufficient",
                    "mode": "snapshots", "n_points": len(snaps[0][1]),
                    "n_snapshots": 1, "trend": None, "fingerprint": fp_last,
                    "fingerprint_shift": None,
                    "reasons": ["快照数 1 < 2（两次快照差分不可判；"
                                "现在存快照，下次起可比对）"],
                    "thresholds": {"alpha": float(alpha),
                                   "mean_shift_rel_max": mean_shift_rel_max,
                                   "std_ratio_max": std_ratio_max}}
        fp_first = drift_fingerprint(snaps[0][1])
        shift = _shift_detail(fp_first, fp_last, mean_shift_rel_max,
                              std_ratio_max)
        shift["snapshot_first_at"] = snaps[0][0]
        shift["snapshot_last_at"] = snaps[-1][0]
        mk: dict[str, Any] | None = None
        trend_flag = False
        reasons = [f"指纹差分线（首末快照，n_snapshots={len(snaps)}）: "
                   f"mean_shift_rel={shift['mean_shift_rel']:.4g} "
                   f"std_ratio={shift['std_ratio']:.4g}"]
        if len(snaps) >= _MK_MIN_N:
            means = [drift_fingerprint(batch)["mean"] for _at, batch in snaps]
            mk = mann_kendall(means, alpha=alpha)
            trend_flag = mk["trend"] != _TREND_NONE
            reasons.insert(0, f"MK 趋势线（快照均值序列）: trend={mk['trend']} "
                              f"p={mk['p']:.4g} z={mk['z']:.4g} "
                              f"（alpha={alpha}）")
        else:
            reasons.append("快照数 <3，MK 趋势线不可用（仅指纹差分线）")
        out = _combine([("trend", trend_flag), ("fingerprint_shift",
                                                 shift["shift_flag"])],
                       n_points=sum(len(b) for _a, b in snaps),
                       mode="snapshots", alpha=alpha, trend=mk, shift=shift,
                       reasons=reasons)
        out["n_snapshots"] = len(snaps)
        out["fingerprint"] = fp_last
        return out
    raise ValueError("序列与快照混搭（逐元素要么全数值要么全映射），"
                     "无法判别输入口径")
