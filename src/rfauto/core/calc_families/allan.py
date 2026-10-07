"""Allan 稳定度族（MS-5，内核在 core/allan_variance.py，本模块只做注册壳）。

round15 :212 规格「重叠 Allan 三 coef 公式（IEEE 1139）与 clock_noise
幂律谱互检」；round16 §二 :49 与 clock_noise Leeson 接回合并（与 DR-8
CDR 抖动传函互补）。单键 allan_deviation（时序进、ADEV 序列出）；
mdev/classify_joint/adev_slope/avar_from_h/h_from_l_points 为 core 纯
函数不注册（分析面走 core 直调；三 coef 闭式与 L(f) 桥是
clock_noise 幂律谱互检的桥，保持零状态纯函数语义）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "allan_deviation",
    "MS-5 Allan 偏差（时钟稳定度，IEEE 1139/952 口径）：分数频率 y 序列"
    "（kind='freq'）或相位时间误差 x 序列秒（kind='phase'，y=Δx/τ0）"
    "→ 重叠（缺省）/非重叠 Allan 偏差序列 {tau_s, adev, adev_error, "
    "n_terms}（tau 缺省倍频程网格；越界 tau 裁剪）。label=全段 log-log "
    "斜率按 IEEE 1139 Table 1 分类（pm/white_fm/flicker_fm/"
    "random_walk_fm/linear_drift/unknown；白相与闪相同斜率 −1 不可分辨，"
    "分辨走 core classify_joint 用 MDEV −3/2 vs −1，或频域 S_phi 斜率走 "
    "clock_noise 互检）。斜率分类是全段摘要启发式（≥2 个正 ADEV 点才给"
    "出，否则 'insufficient'）；误差棒=独立差分近似 EDF（Greenhall-Howe "
    "修正未实现，UNVERIFIED，只作量级参考）。短序列/非有限值/非等间隔"
    "时间戳显式拒绝",
    (("samples", "list[float] 分数频率偏差 y_k 或相位时间误差 x_k（秒）序列"
      "（≥3 点等间隔）"),
     ("rate_hz", "float Hz 采样率（>0，τ0=1/rate_hz）"),
     ("kind", "str 'freq'|'phase'（默认 'freq'）"),
     ("estimator", "str 'overlapping'|'nonoverlap'（默认 'overlapping'）"),
     ("taus", "list[float] 可选取样时间数组秒（全正；缺省倍频程网格）")),
    required=("samples", "rate_hz"),
)
def allan_deviation(
    samples: list,
    rate_hz: float,
    kind: str = "freq",
    estimator: str = "overlapping",
    taus: list | None = None,
) -> dict:
    from rfauto.core.allan_variance import (
        adev,
        classify_adev_slope,
        fit_loglog_slope,
    )

    r = adev(samples, rate_hz, taus=taus, kind=kind, estimator=estimator)
    slope: float | None = None
    r2: float | None = None
    label = "insufficient"
    positives = sum(1 for v in r["adev"] if v > 0.0)
    if positives >= 2:
        slope, _, r2 = fit_loglog_slope(r["tau"], r["adev"])
        label = classify_adev_slope(slope)["label"]
    return {
        "tau_s": r["tau"].tolist(),
        "adev": r["adev"].tolist(),
        "adev_error": r["adev_error"].tolist(),
        "n_terms": r["n_terms"].tolist(),
        "tau0_s": float(r["tau0"]),
        "n_samples": int(r["n_samples"]),
        "kind": str(r["kind"]),
        "estimator": str(r["estimator"]),
        "slope_loglog": slope,
        "slope_r2": r2,
        "label": label,
        "time_base": "时域稳定度统计（IEEE 1139 Table 1 斜率口径）",
    }
