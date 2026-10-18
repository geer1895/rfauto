"""概率纸坐标变换与 Weibull 作图回归（XD-15，aurora_e W8-S37 池件批 3）。

W6-S29 放弃件复活（原放弃理由="低优先+matplotlib 面"）：本模块把概率纸
面**纯函数化**——只做坐标变换闭式 + 回归线/残差面，**零绘图零 PNG**
（matplotlib 中文豆腐块坑 AGENTS ⑩ 随绘图面一起剥离；前端/CLI 想画图时
消费本模块输出的坐标点自渲染）。

物理/统计口径（出处纪律 #1c/#300）
----------------------------------
- Weibull 概率纸线性化：2 参 Weibull CDF F(t)=1−exp(−(t/η)^β) →
  t=η·(−ln(1−p))^{1/β} → 取 y=ln(−ln(1−p))、x=ln t 得

      y = β·(x − ln η)          [斜率=形状参数 β、截距=−β·ln η]

  （W. Weibull 1951；Meeker & Escobar *Statistical Methods for
  Reliability Data* §3.6 概率作图口径；NIST/SEMATECH e-Handbook §8.2.2.3）
  ——恒等式锚：对精确 Weibull 分位数点作最小二乘，斜率回收 β、
  η=exp(−截距/斜率) 回收特征寿命（机器精度级，测试钉）。
- 作图位（plotting position）：Benard 中位秩 p_i=(i−0.3)/(n+0.4)
  （Benard & Bos-Levenbach 1953；NIST e-Handbook §8.2.2.3 "median
  ranks"）——对称恒等式 p_i+p_{n+1−i}=1（测试钉）；p∈(0,1) 恒成立。
- 正态概率纸：纵坐标=probit(p)=Φ⁻¹(p)（标准正态分位数，
  scipy.special.ndtri 精确有理近似）；p=0.5→0、Φ⁻¹(0.84134…)→1（1σ
  点）、对称恒等式 Φ⁻¹(1−p)=−Φ⁻¹(p)（测试钉）。横坐标 t 或 ln t
  （log_x=True，对数正态纸）。
- 回归=闭式普通最小二乘（y 对 x）：slope=S_xy/S_xx、intercept=ȳ−slope·
  x̄、r²=1−SS_res/SS_tot；S_xx=0（全部 t 相同）显式拒绝。

删失口径（如实边界，不冒充）
----------------------------
本模块作图回归只吃**完全样本/失效样本时间**（n 个观测全失效）；右删失
数据的合法估计走 alt_planning.fit_loglinear_weibull（MLE，删失似然），
两路线的跨检（同数据 β/η 一致性）在锚树 tests/unit/test_probability_
paper.py 以统计容差互证。

numpy ndarray 进出（同 core/aging Weibull 统计节先例）；标量入→标量出。
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.special import ndtri

__all__ = [
    "benard_median_ranks",
    "fit_weibull_paper",
    "normal_paper_xy",
    "weibull_paper_xy",
]

_SOURCES = {
    "weibull": ("Weibull 1951；Meeker & Escobar §3.6 概率作图；"
                "NIST/SEMATECH e-Handbook §8.2.2.3"),
    "benard": "Benard & Bos-Levenbach 1953 中位秩；NIST e-Handbook §8.2.2.3",
    "normal": "probit=Φ⁻¹（scipy.special.ndtri 精确有理近似）",
}


def _as_1d(values: Any, name: str) -> np.ndarray:
    """序列/标量 → 1D float ndarray（标量入→(1,)；空/含非有限显式拒绝）。"""
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 0:
        arr = arr.reshape(1)
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError(
            f"probability_paper: {name} 须为一维非空序列，得到 shape="
            f"{np.asarray(values).shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(
            f"probability_paper: {name} 含非有限值，显式拒绝")
    return arr


def _as_prob(values: Any, name: str) -> np.ndarray:
    """概率序列：0<p<1 开区间（0/1 使 ln(−ln(1−p))/probit 发散，显式拒绝）。"""
    arr = _as_1d(values, name)
    if bool(np.any(arr <= 0.0) or np.any(arr >= 1.0)):
        raise ValueError(
            f"probability_paper: {name} 须在开区间 (0,1)（作图位由 "
            f"benard_median_ranks 生成保证），得到越界值")
    return arr


def benard_median_ranks(n: int) -> np.ndarray:
    """Benard 中位秩作图位 p_i=(i−0.3)/(n+0.4)，i=1..n（n≥1）。

    对称恒等式 p_i+p_{n+1−i}=1；p 恒落开区间 (0,1)（n=1 时 p=0.5）。
    出处：Benard & Bos-Levenbach 1953；NIST e-Handbook §8.2.2.3。
    """
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError(
            f"probability_paper: n 须为正整数，得到 {n!r}")
    i = np.arange(1, n + 1, dtype=float)
    return (i - 0.3) / (n + 0.4)


def weibull_paper_xy(t: Any, p: Any) -> tuple[Any, Any]:
    """Weibull 概率纸坐标：x=ln(t)、y=ln(−ln(1−p))（双对数线性化）。

    恒等式：精确 Weibull 分位点 t=η·(−ln(1−p))^{1/β} 的坐标满足
    y=β·(x−ln η)——线性回归斜率=形状参数（锚树钉）。t>0、p∈(0,1)；
    标量入→标量出，数组入→逐元素数组。
    """
    t_arr = _as_1d(t, "t")
    p_arr = _as_prob(p, "p")
    if t_arr.size != p_arr.size:
        raise ValueError(
            f"probability_paper: t 与 p 长度须一致，得到 {t_arr.size} vs "
            f"{p_arr.size}")
    if bool(np.any(t_arr <= 0.0)):
        raise ValueError(
            "probability_paper: t 必须 >0，得到非正值")
    x = np.log(t_arr)
    y = np.log(-np.log(1.0 - p_arr))
    if np.isscalar(t) and np.isscalar(p):
        return float(x[0]), float(y[0])
    return x, y


def normal_paper_xy(t: Any, p: Any, *, log_x: bool = False) -> tuple[Any, Any]:
    """正态概率纸坐标：x=t（或 log_x=True 时 x=ln t，对数正态纸）、
    y=probit(p)=Φ⁻¹(p)。

    锚：p=0.5→y=0；Φ⁻¹(0.8413447460685429)=1.0（1σ 点）；对称恒等式
    Φ⁻¹(1−p)=−Φ⁻¹(p)。t>0（log_x 时）且 p∈(0,1)；标量入→标量出。
    """
    t_arr = _as_1d(t, "t")
    p_arr = _as_prob(p, "p")
    if t_arr.size != p_arr.size:
        raise ValueError(
            f"probability_paper: t 与 p 长度须一致，得到 {t_arr.size} vs "
            f"{p_arr.size}")
    if log_x and bool(np.any(t_arr <= 0.0)):
        raise ValueError(
            "probability_paper: log_x=True 时 t 必须 >0（对数正态纸）")
    x = np.log(t_arr) if log_x else t_arr
    y = ndtri(p_arr)
    if np.isscalar(t) and np.isscalar(p):
        return float(x[0]), float(y[0])
    return x, y


def fit_weibull_paper(t: Any) -> dict[str, Any]:
    """Weibull 概率纸作图回归：Benard 中位秩 + 闭式 OLS → β/η/残差面。

    输入：t=失效时间序列（完全样本口径；右删失走
    alt_planning.fit_loglinear_weibull MLE，见模块 docstring）。**按升序
    排序后配 Benard 秩**（作图位对应第 i 个次序统计量的工程约定；乱序
    输入自动排序，排序结果经 plotting_x 落盘可复核）。
    输出：slope_beta（斜率=形状参数 β̂）、intercept（=−β̂·ln η）、
    eta_hat=exp(−intercept/slope)、residuals/residual_rms/
    residual_max_abs/r_squared、作图坐标（benard_p/plotting_x/plotting_y）。
    恒等式锚：精确 Weibull 分位数样本 β̂/η̂ 机器精度回收（残差≈0）。
    """
    t_arr = np.sort(_as_1d(t, "t"))
    n = int(t_arr.size)
    if n < 2:
        raise ValueError(
            f"probability_paper: 作图回归须 n≥2 个失效时间，得到 {n}")
    if bool(np.any(t_arr <= 0.0)):
        raise ValueError("probability_paper: t 必须 >0，得到非正值")
    p = benard_median_ranks(n)
    x = np.log(t_arr)
    y = np.log(-np.log(1.0 - p))
    x_bar = float(np.mean(x))
    y_bar = float(np.mean(y))
    s_xx = float(np.sum((x - x_bar) ** 2))
    if s_xx <= 0.0:
        raise ValueError(
            "probability_paper: 全部 t 相同（S_xx=0），回归退化，显式拒绝")
    s_xy = float(np.sum((x - x_bar) * (y - y_bar)))
    slope = s_xy / s_xx
    if slope <= 0.0:
        # 升序 t×升序 p 的切比雪夫不等式保证 slope>0——防御性守卫
        raise ValueError(
            f"probability_paper: 回归斜率非正（{slope!r}），数据与 Weibull "
            f"作图口径矛盾，显式拒绝")
    intercept = y_bar - slope * x_bar
    residuals = y - (slope * x + intercept)
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y - y_bar) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 1.0
    eta_log = -intercept / slope
    eta_hat = float(np.exp(eta_log))
    if not bool(np.isfinite(eta_hat)):
        raise ValueError(
            f"probability_paper: eta_hat=exp({eta_log:.6g}) 非有限，显式拒绝")
    return {
        "n": n,
        "slope_beta": round(slope, 12),
        "intercept": round(intercept, 12),
        "eta_hat": round(eta_hat, 12),
        "residuals": residuals,
        "residual_rms": round(float(np.sqrt(np.mean(residuals ** 2))), 15),
        "residual_max_abs": round(float(np.max(np.abs(residuals))), 15),
        "r_squared": round(r_squared, 15),
        "benard_p": p,
        "plotting_x": x,
        "plotting_y": y,
        "note": (
            "Weibull 概率纸作图回归（Benard 中位秩+闭式 OLS）：斜率=形状"
            "参数 β̂、η̂=exp(−intercept/slope)；完全样本口径（右删失走 "
            "alt_planning.fit_loglinear_weibull MLE）；纯坐标面零绘图"),
        "source": _SOURCES["weibull"] + "；" + _SOURCES["benard"],
    }
