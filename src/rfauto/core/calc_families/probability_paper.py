"""Weibull 概率纸作图回归一键（aurora_h W3-K 池件批，R2_core_tier5
§⑤-3 提升核——池件 XD-15 同笔清偿）。

提升核：消费 core/probability_paper.py 三函数全套（benard_median_ranks/
weibull_paper_xy/fit_weibull_paper；aurora_e W8-S37 池件批 3 落地物，
纯坐标面零绘图）——该内核 docstring 自证作图回归/删失口径/出处链已
钉死，本文件即其 CALC 注册面（唯一缺的键面）。

公式（单源不复制，出处与互证路径见 core/probability_paper.py）
----------------------------------------------------------------
- 2 参 Weibull CDF F(t)=1−exp(−(t/η)^β) 线性化：y=ln(−ln(1−p))、
  x=ln t → y=β·(x−ln η)（斜率=形状参数 β、截距=−β·ln η；
  Weibull 1951；Meeker & Escobar §3.6；NIST/SEMATECH e-Handbook
  §8.2.2.3）。
- 作图位：Benard 中位秩 p_i=(i−0.3)/(n+0.4)（Benard & Bos-Levenbach
  1953；对称恒等式 p_i+p_{n+1−i}=1）。
- 回归=闭式 OLS：slope=S_xy/S_xx、intercept=ȳ−slope·x̄、
  η̂=exp(−intercept/slope)、r²=1−SS_res/SS_tot。

适用域与边界
------------
- 完全样本口径（n 个观测全失效）；右删失数据的合法估计走
  alt_planning.fit_loglinear_weibull（MLE，删失似然）——两路线跨检
  已在内核锚树钉（tests/unit/test_probability_paper.py）。
- n≥2、t>0、全同 t（S_xx=0 回归退化）显式拒绝（内核守卫透传）。
- boundary：weibull_clutter_model（雷达杂波幅度分布——同名异域，
  registry 归组雷达/本键归热·功率·可靠性，边界注记已在彼处）、
  aging（Weibull 统计/MLE 域）、alt_planning（删失 MLE 面）、
  cpk_yield_convert/serial_yield_budget（正态能力指数面）。

锚（#118 独立算术，tests/unit/test_w3k_pool_domains.py）：①精确
Weibull 分位样本（β=2.5/η=800/n=8）→ β̂/η̂ 机器精度回收（残差≈0、
r²=1）；②n=2 两点手算逐位（OLS 过两点：slope=(y₂−y₁)/(x₂−x₁) 独立
算术路径）；③Benard 对称恒等式 p_i+p_{n+1−i}=1；④乱序输入与升序
输入同结果（排序守卫）；⑤β=1 指数退化锚。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator


def _finite_list(values: Any, name: str) -> list[float]:
    """序列档守卫：一维非空、全有限（bool 显式拒收；标量拒收）。"""
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise ValueError(f"{name} 须为数值序列，实际 {type(values).__name__}")
    out: list[float] = []
    for k, v in enumerate(values):
        if isinstance(v, bool):
            raise ValueError(f"{name}[{k}] 必须为数值（不接受 bool）")
        f = float(v)
        if not math.isfinite(f):
            raise ValueError(f"{name}[{k}] 必须为有限数，实际 {v!r}")
        out.append(f)
    if len(out) == 0:
        raise ValueError(f"{name} 须为非空序列")
    return out


@register_calculator(
    "weibull_paper_fit",
    "Weibull 概率纸作图回归（完全样本）：Benard 中位秩 p=(i−0.3)/(n+0.4)"
    "+双对数线性化 ln(−ln(1−p))~ln t +闭式 OLS → 斜率=形状参数 β̂、"
    "η̂=exp(−intercept/slope)、残差面/R²/GoF 全套坐标输出（前端可自"
    "渲染概率纸）；右删失数据走 alt_planning MLE 路线（本键显式拒绝"
    "边界外推）。单源 core/probability_paper（提升核注册面）",
    (("t_fail", "list[float] 失效时间序列（完全样本口径，h 或任意"
                "一致单位；乱序自动排序；≥2 个且须含不同值）"),),
    required=("t_fail",),
)
def weibull_paper_fit(t_fail: list[float]) -> dict[str, Any]:
    from rfauto.core.probability_paper import fit_weibull_paper

    times = _finite_list(t_fail, "t_fail")
    fit = fit_weibull_paper(times)
    return {
        "n": fit["n"],
        "slope_beta": fit["slope_beta"],
        "intercept": fit["intercept"],
        "eta_hat": fit["eta_hat"],
        "residual_rms": fit["residual_rms"],
        "residual_max_abs": fit["residual_max_abs"],
        "r_squared": fit["r_squared"],
        "benard_p": [float(v) for v in fit["benard_p"]],
        "plotting_x": [float(v) for v in fit["plotting_x"]],
        "plotting_y": [float(v) for v in fit["plotting_y"]],
        "residuals": [float(v) for v in fit["residuals"]],
        "note": fit["note"],
        "source": fit["source"],
    }
