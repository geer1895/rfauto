"""AI-1 代理保形预测包裹层（round14 :58，split-conformal，2026-10-02）。

split-conformal（Vovk/Papadopoulos 系；来源 arXiv:2408.09881 登记口径）：
在**留出校准集**上取非合规分数（这里 = |残差|）的有限样本高阶分位数

    q = sorted(|residuals|)[ ceil((n+1)(1−α)) − 1 ]

预测区间 = [ ŷ − q, ŷ + q ]。交换性假设（关键前提，docstring 显式注明）：
校准样本与待预测样本须可交换（i.i.d. 或可交换联合分布）——协变量漂移/
时序趋势会破坏覆盖保证，本模块不做任何漂移检测，调用方自行保证；
有限样本边际覆盖保证 P(Y∈C(X)) ≥ 1−α **仅在交换性成立时**成立。

纯 numpy（round14 验收口径），零网络零真机；GP 面薄适配为鸭子类型
（任何带 predict_with_std(params)->{metric:(mean,std|None)} 或
predict(params)->dict 的模型皆可包裹——core 层禁 import optimization
（分层铁律 3），故不引 SurrogateModel 基类，按契约鸭子判别）。

与 GP σ 的分工（round14 验收"区间宽度 vs GP σ 对比"）：σ 区间来自模型
自报方差（可欠覆盖），保形区间来自校准残差分位数（交换性下有硬保证）；
SurrogateConformalWrapper.predict_with_interval 同时透出 std 与保形
[lo,hi]，对比由消费方（active_learning 第 4 种 σ 源/uq_service）做。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "ConformalInterval",
    "SurrogateConformalWrapper",
    "calibrate",
    "predict_interval",
]


def calibrate(residuals: Sequence[float], alpha: float) -> float:
    """split-conformal 校准：残差 → 半宽 q。

    残差定义：residual_i = ŷ_i − y_i（模型在校准集上的预测减真值），
    非合规分数取绝对值（对称区间）。有限样本高阶分位数
    k = ceil((n+1)(1−α))：k>n（α < 1/(n+1)）时返回 +inf（校准集太小
    撑不起该置信水平，如实上溢不夹持——夹持会伪造覆盖保证）。

    交换性假设见模块 docstring。
    """
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        raise ValueError(f"alpha 必须为数值（不接受 bool），得 {alpha!r}")
    alpha = float(alpha)
    if not math.isfinite(alpha) or not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha 必须在 (0,1) 开区间，得 {alpha}")
    arr = np.asarray(residuals, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError("residuals 不能为空（至少 1 个校准残差）")
    if not np.all(np.isfinite(arr)):
        raise ValueError("residuals 含非有限值（NaN/Inf）——校准集须完整")
    scores = np.sort(np.abs(arr))
    n = scores.size
    k = math.ceil((n + 1) * (1.0 - alpha))
    if k > n:
        return math.inf
    return float(scores[k - 1])


def predict_interval(point_pred: float, q: float) -> tuple[float, float]:
    """保形预测区间：[ŷ − q, ŷ + q]（对称；q=+inf → (−inf, +inf) 合法，
    由 calibrate 如实上溢产生，本函数不二次拦截）。"""
    if isinstance(point_pred, bool) or not isinstance(point_pred,
                                                      (int, float)):
        raise ValueError(
            f"point_pred 必须为数值（不接受 bool），得 {point_pred!r}")
    y = float(point_pred)
    if not math.isfinite(y):
        raise ValueError(f"point_pred 必须为有限数，得 {y}")
    if isinstance(q, bool) or not isinstance(q, (int, float)):
        raise ValueError(f"q 必须为数值（不接受 bool），得 {q!r}")
    qf = float(q)
    if math.isnan(qf) or qf < 0.0:
        raise ValueError(f"q 必须为非负有限数或 +inf，得 {q}")
    return (y - qf, y + qf)


@dataclass(frozen=True)
class ConformalInterval:
    """校准结果载体（alpha/q/n 一并透出，q=inf 时 covered 语义如实退化）。"""

    alpha: float
    q: float
    n: int

    def interval(self, point_pred: float) -> tuple[float, float]:
        return predict_interval(point_pred, self.q)

    @property
    def width(self) -> float:
        """区间全宽 2q（q=inf → inf）。"""
        return 2.0 * self.q


def _model_mean(model: Any, params: dict[str, float], metric: str | None,
                std_out: list[dict[str, Any]]) -> dict[str, float]:
    """鸭子类型取均值面：优先 predict_with_std（连带收集 std），回退 predict。"""
    if hasattr(model, "predict_with_std"):
        out = model.predict_with_std(params)
        std_out.append(out)
        return {k: float(v) for k, (v, _s) in out.items()}
    out = model.predict(params)
    if not isinstance(out, dict):
        return {"y": float(out)}
    return {k: float(v) for k, v in out.items()}


class SurrogateConformalWrapper:
    """GP/代理模型薄适配：校准残差分位数 → (mean, [lo, hi])。

    model 契约（鸭子类型，不 import optimization）：
    - predict_with_std(params) -> {metric: (mean, std|None)}（SurrogateModel
      基类契约），或
    - predict(params) -> {metric: mean} 或标量（回退路径，metric 缺省 "y"）。

    用法：wrapper = SurrogateConformalWrapper(model, metric="f0_ghz")
    → wrapper.calibrate(params_list, y_true_list) → wrapper.
    predict_with_interval(params)。calibrate 可重复调用（重校准）。
    """

    def __init__(self, model: Any, metric: str | None = None,
                 alpha: float = 0.1) -> None:
        self.model = model
        self.metric = metric
        self._alpha = self._check_alpha(alpha)
        self.calib: ConformalInterval | None = None

    @staticmethod
    def _check_alpha(alpha: Any) -> float:
        if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
            raise ValueError(f"alpha 必须为数值（不接受 bool），得 {alpha!r}")
        a = float(alpha)
        if not math.isfinite(a) or not (0.0 < a < 1.0):
            raise ValueError(f"alpha 必须在 (0,1) 开区间，得 {alpha}")
        return a

    def _mean_for(self, params: dict[str, float],
                  std_out: list[dict[str, Any]]) -> float:
        means = _model_mean(self.model, params, self.metric, std_out)
        key = self.metric if self.metric is not None else (
            next(iter(means)) if len(means) == 1 else None)
        if key is None or key not in means:
            raise KeyError(
                f"metric={self.metric!r} 不在模型预测键 {sorted(means)} 中；"
                "构造时请显式指定单值 metric")
        return means[key]

    def calibrate(self, params_list: list[dict[str, float]],
                  y_true: Sequence[float]) -> ConformalInterval:
        """在校准集上计算残差 → q（重复调用即重校准）。"""
        if len(params_list) != len(y_true):
            raise ValueError(
                f"params_list({len(params_list)}) 与 y_true({len(y_true)})"
                "长度不一致")
        std_out: list[dict[str, Any]] = []
        residuals = [self._mean_for(p, std_out) - float(y)
                     for p, y in zip(params_list, y_true, strict=True)]
        q = calibrate(residuals, self._alpha)
        self.calib = ConformalInterval(alpha=self._alpha, q=q,
                                       n=len(residuals))
        return self.calib

    def set_alpha(self, alpha: float) -> SurrogateConformalWrapper:
        """显式重设 α（重校准前生效；链式返回 self）。"""
        self._alpha = self._check_alpha(alpha)
        return self

    def predict_with_interval(self, params: dict[str, float]) -> dict[str, Any]:
        """→ {"mean", "lo", "hi", "q", "std"}；未校准显式报错（不伪造区间）。"""
        if self.calib is None:
            raise ValueError("尚未 calibrate（先在校准集上调用 calibrate）")
        std_out: list[dict[str, Any]] = []
        mean = self._mean_for(params, std_out)
        std: float | None = None
        if std_out:
            key = self.metric if self.metric is not None else next(
                iter(std_out[0]))
            pair = std_out[0].get(key)
            if pair is not None and pair[1] is not None:
                std = float(pair[1])
        lo, hi = self.calib.interval(mean)
        return {"mean": mean, "lo": lo, "hi": hi, "q": self.calib.q,
                "std": std}
