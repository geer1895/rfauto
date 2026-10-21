"""测量系统漂移建模族（架构批 W2-S7，R2_core_tier3 §③ D6）：参考对
线性漂移率估计+置信带+漂移校正 GUM 预算 / 测量链漂移 SPC 监控。

两键：measurement_drift_estimate（等间隔参考测量的 OLS 线性漂移率估计
——斜率/截距/标准误/置信带/漂移判据/去趋势校正序列+逐点不确定度 GUM
合成）/ measurement_drift_monitor（测量链 EWMA+CUSUM 控制图监控——
**复用 core/anchor_drift_spc 统计内核**（同仓双源）+控制限恒等式自检+
线性趋势告警三证据组合）。

与既有面的边界（#222 triple-grep 证据，2026-10-18 实测）
--------------------------------------------------------
- core/anchor_drift.py / anchor_drift_spc.py=**锚面漂移**（knowledge/
  anchors.yaml 标定锚值序列的漂移统计）；core/filter_temp_drift.py=
  器件温漂（温度系数口径）；本族=**测量系统漂移**（测量链读数序列：
  漂移率估计/校正预算/控制图告警）——语义迁移清晰（R2 §④ 排名 8：
  "anchor_drift_spc EWMA/CUSUM 机器直接复用"），SPC 统计内核组合复用
  不替代（组合不替代纪律，anchor_drift_spc 模块 docstring 同款）。
- grep "measurement.*drift|drift.*correct|reference.compress" 全仓零
  命中（R2 零命中判据，本席开工 #222 复核一致）。

物理口径（docstring 写死，#1c/#300 出处纪律；#118 锚树见
tests/unit/test_w2s7_ruthroff_gd_drift.py）
--------------------------------------------------------
- **线性漂移率估计**（等间隔索引 t=0..n−1 的 OLS）：斜率
  β̂=Σ(t−t̄)(y−ȳ)/Σ(t−t̄)²、截距 ȳ−β̂·t̄；斜率标准误
  se(β̂)=σ/√Sxx（σ 为**调用方显式声明**的测量标准差——声明时走正态
  z 带）或 s/√Sxx（s=残差标准差，df=n−2，t 带惰性 scipy 分位）。
  漂移判据：|β̂|>z/t 临界×se → drift_detected。校正序列
  y_corr,i = y_i − β̂·(i−t̄)（去线性趋势、均值保持）；逐点不确定度
  u_i=√(σ²+se²·(i−t̄)²)（GUM 独立贡献平方合成：测量散布+校正杠杆臂
  两项）。R²=1−RSS/TSS。
- **SPC 控制图**（复用 anchor_drift_spc 机器）：EWMA
  z_i=λx_i+(1−λ)z_{i−1}、控制限 z̄±L·σ·√(λ/(2−λ)·(1−(1−λ)^{2i}))、
  CUSUM C±=max(0,C±±z∓k) 越 h 报警；σ 必须显式声明（短序列不内估，
  #118 家族纪律同 anchor_drift_spc 铁律）。控制限恒等式自检：
  UCL_i−μ₀ 与独立重算 L·σ·√factor_i 的最大偏差逐字段回报（≤1e-12
  构造级锚）。三证据组合判定：EWMA/CUSUM/线性趋势三线，≥2 →
  drifted、恰 1 → warning、0 → stable（anchor_drift_spc 组合规则同构；
  线有效性下限随线自报，不硬算）。
- 零漂假设→假阳率钉与合成漂移注入→斜率回收（#340 回收钉范式）为
  族锚（测试侧实现）。

数值锚（#118 独立路线，测试侧实现）
- 合成线性漂移（无噪声）→ 斜率逐位回收、校正序列恒定 ≤1e-12。
- 已知 σ 档 se(β̂)=σ/√Sxx 恒等（独立重算）；控制限恒等式 ≤1e-12。
- 稳定序列（零漂）→ drift_detected=False 且三线不告警（假阳钉）。
- 复用钉：monitor 内嵌 EWMA/CUSUM 与直接调用 anchor_drift_spc 同参
  逐字段一致（同仓双源）。

守卫：values 非空且 ≥3（斜率 df）；confidence∈(0,1)；monitor 的
sigma 必填 >0；ewma λ∈(0,1]、L>0、cusum k>0、h>0；数值拒收
bool/非有限值（anchor_drift_spc._as_floats 同纪律）。数值 0.0 合法
（判缺失 is not None，#364④）；无 ``__all__``（公开 API 快照口径）。

接口：纯函数零 IO；math/statistics 本征闭式+scipy t 分位惰性
（anchor_drift_spc 同款惰性导入）；返回 JSON 可序列化结构。

出处（同仓 SPC 内核复用+经典控制图口径）：
- measurement_drift_estimate/measurement_drift_monitor：EWMA/CUSUM
  控制图统计内核=core/anchor_drift_spc 机器直接复用（同仓双源，复用钉
  在测试）；线性趋势=OLS 合成（统计教科书口径；控制限恒等式自检在档）。
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from .registry import register_calculator
from .thermal import _finite

_MIN_N_SLOPE = 3      #: 线性漂移率估计最低点数（df=n−2≥1）
_MAX_N = 100000       #: 防滥用上限
_CONF_DEFAULT = 0.95


def _as_floats_strict(values: Any, tag: str) -> list[float]:
    """数值收敛（显式拒收 bool/非有限值——anchor_drift_spc._as_floats
    同纪律）。"""
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{tag}: values 须为列表，得到 {type(values)!r}")
    if not values:
        raise ValueError(f"{tag}: values 不能为空")
    if len(values) > _MAX_N:
        raise ValueError(
            f"{tag}: values 点数 {len(values)} 超上限 {_MAX_N}（防滥用）")
    out: list[float] = []
    for i, v in enumerate(values):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{tag}.values[{i}] 非数值: {v!r}")
        f = float(v)
        if not math.isfinite(f):
            raise ValueError(f"{tag}.values[{i}] 非有限数值: {v!r}")
        out.append(f)
    return out


def _ols_linear(x: list[float], y: list[float]) -> tuple[float, float,
                                                         float, float]:
    """OLS 线性回归：返回 (slope, intercept, sxx, rss)。"""
    n = len(x)
    xbar = sum(x) / n
    ybar = sum(y) / n
    sxx = sum((v - xbar) ** 2 for v in x)
    sxy = sum((x[i] - xbar) * (y[i] - ybar) for i in range(n))
    slope = sxy / sxx
    intercept = ybar - slope * xbar
    rss = sum((y[i] - (intercept + slope * x[i])) ** 2 for i in range(n))
    return slope, intercept, sxx, rss


def _t_ppf_local(p: float, df: int) -> float:
    """Student-t 分位（scipy 惰性；anchor_drift_spc._t_ppf 同款模式）。"""
    try:
        from scipy.stats import t as _t_dist
    except ImportError as exc:  # pragma: no cover — scipy 为仓内既有依赖
        raise RuntimeError(
            "残差 t 置信带需要 scipy（t 分布分位）；环境缺 scipy 时如实"
            "报错，不以正态近似冒充精确临界值（显式声明 σ 可走正态带）"
        ) from exc
    return float(_t_dist.ppf(p, df))


@register_calculator(
    "measurement_drift_estimate",
    "测量漂移估计：等间隔参考测量序列的 OLS 线性漂移率估计——斜率/截距"
    "/标准误/置信带（σ 显式声明走 z 带，否则残差 s 走 t 带）/漂移判据/"
    "去趋势校正序列+逐点 GUM 合成不确定度（测量散布+校正杠杆臂）/R²；"
    "合成漂移斜率回收与零漂假阳钉为族锚",
    (("values", "array 测量读数序列（等间隔索引序，≥3 点）"),
     ("sigma", "float 测量标准差（可选；声明则斜率带走已知 σ 正态口径）"),
     ("confidence", "float 置信水平（0<confidence<1，缺省 0.95）")),
    required=("values",),
)
def measurement_drift_estimate(values: list, sigma: float | None = None,
                               confidence: float = _CONF_DEFAULT
                               ) -> dict[str, Any]:
    tag = "measurement_drift_estimate"
    y = _as_floats_strict(values, tag)
    n = len(y)
    if n < _MIN_N_SLOPE:
        raise ValueError(
            f"{tag}: 点数 n={n} < 最低 {_MIN_N_SLOPE}（斜率自由度 "
            "df=n−2≥1 不满足，显式拒绝不硬算）")
    conf = _finite(confidence, f"{tag}.confidence")
    if not 0.0 < conf < 1.0:
        raise ValueError(
            f"{tag}: confidence 必须 ∈(0,1)，得到 {confidence!r}")
    sigma_declared: float | None = None
    if sigma is not None:
        s_val = _finite(sigma, f"{tag}.sigma")
        if s_val <= 0.0:
            raise ValueError(f"{tag}: sigma 必须 >0，得到 {sigma!r}")
        sigma_declared = s_val

    t_idx = [float(i) for i in range(n)]
    tbar = sum(t_idx) / n
    slope, intercept, sxx, rss = _ols_linear(t_idx, y)
    resid_std = math.sqrt(rss / (n - 2))
    tss = sum((v - sum(y) / n) ** 2 for v in y)
    r2 = 1.0 - rss / tss if tss > 0.0 else 1.0

    if sigma_declared is not None:
        se = sigma_declared / math.sqrt(sxx)
        crit = NormalDist().inv_cdf(0.5 + conf / 2.0)
        sigma_source = "caller_declared"
        dist = "normal_z"
    else:
        se = resid_std / math.sqrt(sxx)
        crit = _t_ppf_local(0.5 + conf / 2.0, n - 2)
        sigma_source = "residual_t"
        dist = f"student_t_df{n - 2}"
    stat = slope / se if se > 0.0 else (
        0.0 if slope == 0.0 else math.copysign(math.inf, slope))
    ci_low = slope - crit * se
    ci_high = slope + crit * se
    drift_detected = abs(stat) > crit

    corrected = [y[i] - slope * (t_idx[i] - tbar) for i in range(n)]
    u_corr = [math.sqrt(
        (sigma_declared if sigma_declared is not None else resid_std) ** 2
        + (se * (t_idx[i] - tbar)) ** 2) for i in range(n)]
    return {
        "n": n,
        "confidence": conf,
        "slope_per_step": round(slope, 15),
        "intercept": round(intercept, 15),
        "slope_stderr": round(se, 15),
        "ci_low": round(ci_low, 15),
        "ci_high": round(ci_high, 15),
        "critical_value": round(crit, 15),
        "statistic": (round(stat, 15) if math.isfinite(stat)
                      else ("inf" if stat > 0 else "-inf")),
        "drift_detected": drift_detected,
        "sigma_source": sigma_source,
        "distribution": dist,
        "residual_std": round(resid_std, 15),
        "r_squared": round(r2, 15),
        "corrected_values": [round(v, 15) for v in corrected],
        "corrected_uncertainty": [round(v, 15) for v in u_corr],
        "note": (
            "OLS 线性漂移率：β̂=Σ(t−t̄)(y−ȳ)/Σ(t−t̄)²、se(β̂)=σ/√Sxx"
            "（σ 调用方显式声明→正态 z 带）或 s/√Sxx（残差 s→t 带，"
            "df=n−2）；校正序列 y_corr=y−β̂·(t−t̄)（均值保持）；逐点不"
            "确定度 u=√(σ²+se²·(t−t̄)²)（GUM 独立贡献平方合成）；漂移判"
            "据 |stat|>临界值（双侧）。零漂序列的假阳率由 confidence 直"
            "接控制（族锚测试侧钉）"),
        "source": (
            "GUM（测量不确定度表示指南）平方合成口径；OLS/Student-t 教科"
            "书口径；SPC 序贯面见 measurement_drift_monitor（EWMA/CUSUM"
            " 复用 anchor_drift_spc）；R2_core_tier3 D6 立项口径"),
    }


@register_calculator(
    "measurement_drift_monitor",
    "测量漂移监控：测量链读数序列的 EWMA+CUSUM 控制图（复用 "
    "anchor_drift_spc 统计内核，σ 必须显式声明——短序列不内估）+线性趋"
    "势告警三证据组合（≥2 drifted/1 warning/0 stable）；控制限恒等式"
    "（UCL−μ₀=L·σ·√(λ/(2−λ)·(1−(1−λ)^{2i}))）独立重算自检逐字段回报",
    (("values", "array 测量读数序列（时序，EWMA/CUSUM 需 ≥8 点）"),
     ("sigma", "float 测量标准差（必填 >0，确定性外部源——不从同一序列"
               "内估 σ）"),
     ("target", "float 中心线目标值（可选；缺省=序列均值并如实标注）"),
     ("ewma_lambda", "float EWMA 平滑系数（0<λ≤1，缺省 0.3）"),
     ("ewma_L", "float EWMA 控制限倍数（缺省 2.7，ARL₀≈370 口径）"),
     ("cusum_k", "float CUSUM 容许量 σ 单位（缺省 0.5）"),
     ("cusum_h", "float CUSUM 判警限（缺省 4.0，ARL₀≈168 口径）")),
    required=("values", "sigma"),
)
def measurement_drift_monitor(values: list, sigma: float,
                              target: float | None = None,
                              ewma_lambda: float = 0.3,
                              ewma_L: float = 2.7,
                              cusum_k: float = 0.5,
                              cusum_h: float = 4.0) -> dict[str, Any]:
    tag = "measurement_drift_monitor"
    # 统计内核复用（同仓双源）：anchor_drift_spc 的 EWMA/CUSUM 纯内核
    from rfauto.core.anchor_drift_spc import cusum_test, ewma_control

    x = _as_floats_strict(values, tag)
    n = len(x)
    s_val = _finite(sigma, f"{tag}.sigma")
    if s_val <= 0.0:
        raise ValueError(f"{tag}: sigma 必须 >0，得到 {sigma!r}")
    lam = _finite(ewma_lambda, f"{tag}.ewma_lambda")
    if not 0.0 < lam <= 1.0:
        raise ValueError(
            f"{tag}: ewma_lambda 必须 ∈(0,1]，得到 {ewma_lambda!r}")
    big_l = _finite(ewma_L, f"{tag}.ewma_L")
    if big_l <= 0.0:
        raise ValueError(f"{tag}: ewma_L 必须 >0，得到 {ewma_L!r}")
    k = _finite(cusum_k, f"{tag}.cusum_k")
    if k <= 0.0:
        raise ValueError(f"{tag}: cusum_k 必须 >0，得到 {cusum_k!r}")
    hh = _finite(cusum_h, f"{tag}.cusum_h")
    if hh <= 0.0:
        raise ValueError(f"{tag}: cusum_h 必须 >0，得到 {cusum_h!r}")
    tgt = _finite(target, f"{tag}.target") if target is not None else None

    ewma = ewma_control(x, sigma=s_val, target=tgt, lam=lam, L=big_l)
    cusum = cusum_test(x, sigma=s_val, target=tgt, k=k, h=hh)

    # 控制限恒等式独立重算自检（构造级锚，≤1e-12）
    mu0 = float(ewma["target"])
    limit_dev = 0.0
    if ewma.get("eligible"):
        for i, ucl in enumerate(ewma["ucl"], start=1):
            factor = (lam / (2.0 - lam)) * (1.0 - (1.0 - lam) ** (2 * i))
            limit_dev = max(limit_dev,
                            abs(ucl - mu0 - big_l * s_val * math.sqrt(factor)))

    # 线性趋势线（df 需 n≥3；n<3 如实 skipped）
    if n >= _MIN_N_SLOPE:
        trend = _ols_linear([float(i) for i in range(n)], x)
        slope_est, sxx = trend[0], trend[2]
        se = s_val / math.sqrt(sxx)
        z_crit = NormalDist().inv_cdf(0.975)
        trend_alarm = abs(slope_est) > z_crit * se
        trend_stat = slope_est / se if se > 0.0 else 0.0
        trend_info: dict[str, Any] = {
            "eligible": True,
            "slope_per_step": round(slope_est, 15),
            "slope_stderr": round(se, 15),
            "statistic": round(trend_stat, 15),
            "alarm": trend_alarm,
        }
    else:
        trend_alarm = False
        trend_info = {"eligible": False, "n": n,
                      "reason": f"n={n} < {_MIN_N_SLOPE}（趋势线不硬算）"}

    fired: list[str] = []
    computed = 0
    reasons: list[str] = []
    for name, rep, sig in (("ewma", ewma, ewma.get("signal")),
                           ("cusum", cusum, cusum.get("signal")),
                           ("trend", trend_info,
                            trend_info.get("alarm") is True)):
        if rep.get("eligible"):
            computed += 1
            if sig:
                fired.append(name)
        else:
            reasons.append(f"{name}: {rep.get('reason')}")
    if computed == 0:
        verdict = "insufficient"
        reasons.append("无可用证据线——insufficient 如实")
    elif len(fired) >= 2:
        verdict = "drifted"
        reasons.append(f"≥2 证据线成立: {fired}")
    elif len(fired) == 1:
        verdict = "warning"
        reasons.append(f"单证据线成立（上限 warning）: {fired}")
    else:
        verdict = "stable"
        reasons.append("已算证据线均不成立")
    return {
        "ok": True,
        "n": n,
        "sigma": s_val,
        "sigma_source": "caller_declared",
        "target": mu0,
        "target_source": ("caller_declared" if tgt is not None
                          else "series_mean"),
        "ewma_alarm": bool(ewma.get("signal")),
        "cusum_alarm": bool(cusum.get("signal")),
        "cusum_breach_at": cusum.get("breach_at"),
        "cusum_breach_side": cusum.get("breach_side"),
        "trend": trend_info,
        "verdict": verdict,
        "fired_lines": fired,
        "n_lines_computed": computed,
        "control_limit_identity_max_dev": round(limit_dev, 18),
        "ewma": ewma,
        "cusum": cusum,
        "reasons": reasons,
        "note": (
            "三证据组合（anchor_drift_spc 组合规则同构）：EWMA/CUSUM 复用"
            "锚面统计内核（同仓双源，组合不替代）；线性趋势=已知 σ 的 z "
            "检验（95% 双侧）；σ 必须显式声明（短序列不内估，#118 家族纪"
            "律）；控制限恒等式 UCL−μ₀=L·σ·√(λ/(2−λ)·(1−(1−λ)^{2i})) "
            "独立重算偏差逐字段回报（≤1e-12 构造级锚）；EWMA/CUSUM 有效"
            "域 n≥8（暖机期，随线如实 skipped）"),
        "source": (
            "NIST/SEMATECH e-Handbook §6.3.2.2 EWMA、Montgomery SQC §9 "
            "CUSUM（ARL 口径表转引）；统计内核复用 core/anchor_drift_spc"
            "（QM-8）；R2_core_tier3 D6 立项口径"),
    }
