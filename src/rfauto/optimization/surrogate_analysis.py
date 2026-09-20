"""代理模型（离线分析）。

sklearn GP 离线分析先行（不进 tune 在线路径）。
设计决策：
- 离线分析：读数据湖画曲面找可疑区域
- 不进 tune 在线路径——直到一次真机对照实验证明有效
- sklearn 降回廉价预筛角色符合其单保真本性

代理质量内核 surrogate_fit_quality（ρ/残差/RMS/MAE/R²），
analyze_run_surrogate 默认
给 K 折交叉验证 out-of-fold 质量——环报告据此携带真实质量字段，而非占位。
质量数值全部来自确定性纯 numpy/GP 计算（random_state 固定），无墙钟/无网络。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: 主拟合的 GP 随机重启次数（random_state 固定 → 确定性）
GP_RESTARTS = 5
#: 交叉验证折内拟合的随机重启次数（折数多，取小值控成本）
CV_GP_RESTARTS = 1


@dataclass
class SurrogateAnalysisResult:
    """代理模型分析结果。"""
    run_id: str
    n_samples: int
    n_params: int
    best_params: dict[str, float]
    best_cost: float
    param_importance: dict[str, float]
    prediction_error: float
    #: 代理质量（见 surrogate_fit_quality；空 dict = 未计算）
    quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "n_samples": self.n_samples,
            "n_params": self.n_params,
            "best_params": self.best_params,
            "best_cost": self.best_cost,
            "param_importance": {k: round(v, 4) for k, v in self.param_importance.items()},
            "prediction_error": round(self.prediction_error, 4),
            "quality": _rounded(self.quality),
        }


def _rounded(value: Any, ndigits: int = 6) -> Any:
    """递归圆整（JSON 输出用；int/bool/None 原样保留）。"""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, ndigits)
    if isinstance(value, dict):
        return {k: _rounded(v, ndigits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v, ndigits) for v in value]
    return value


def _ranks(values: np.ndarray) -> np.ndarray:
    """平均秩（并列取平均），确定性实现（不引入 scipy 依赖）。"""
    order = np.argsort(values, kind="stable")
    ranks = np.empty(len(values), dtype=float)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def _spearman_rho(a: np.ndarray, b: np.ndarray) -> float | None:
    """Spearman 秩相关；任一序列为常数时无定义，返回 None。"""
    ra = _ranks(a)
    rb = _ranks(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denom = float(np.sqrt(np.sum(ra ** 2) * np.sum(rb ** 2)))
    if denom <= 0.0:
        return None
    return float(np.sum(ra * rb) / denom)


def surrogate_fit_quality(y_true: Any, y_pred: Any) -> dict[str, Any]:
    """代理预测质量内核（确定性纯 numpy，无随机/无网络）。

    Args:
        y_true: 实际值序列（一维）
        y_pred: 同长预测值序列

    Returns:
        {n, available, rms_error, mae, max_abs_residual, r2, spearman_rho,
         y_mean, y_std, detail}

    语义（诚实边界）：这是在给定这对样本上的残差口径质量——调用方负责
    声明它是训练残差（in-sample）还是交叉验证 out-of-fold 预测。
    spearman_rho 为秩相关（并列秩取平均）；任一序列为常数时返回 None。
    非有限值（NaN/Inf）成对剔除；全被剔除时返回 available=False（不编造）。
    """
    a = np.asarray(y_true, dtype=float).ravel()
    b = np.asarray(y_pred, dtype=float).ravel()
    if a.shape != b.shape:
        raise ValueError(f"y_true/y_pred 长度不一致: {a.shape} vs {b.shape}")
    empty: dict[str, Any] = {
        "n": 0, "available": False, "rms_error": None, "mae": None,
        "max_abs_residual": None, "r2": None, "spearman_rho": None,
        "y_mean": None, "y_std": None,
    }
    if a.size == 0:
        return {**empty, "detail": "无样本"}
    mask = np.isfinite(a) & np.isfinite(b)
    a, b = a[mask], b[mask]
    if a.size == 0:
        return {**empty, "detail": "样本全为非有限值（NaN/Inf）"}
    resid = a - b
    ss_tot = float(np.sum((a - float(np.mean(a))) ** 2))
    return {
        "n": int(a.size),
        "available": True,
        "rms_error": float(np.sqrt(np.mean(resid ** 2))),
        "mae": float(np.mean(np.abs(resid))),
        "max_abs_residual": float(np.max(np.abs(resid))),
        "r2": (float(1.0 - float(np.sum(resid ** 2)) / ss_tot)
               if ss_tot > 0 else None),
        "spearman_rho": _spearman_rho(a, b),
        "y_mean": float(np.mean(a)),
        "y_std": float(np.std(a)),
        "detail": "残差口径质量；in-sample/out-of-fold 由调用方声明",
    }


def _make_gp(n_restarts: int):
    """构造确定性 GP（random_state=0）；调用方自行 fit。"""
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel

    kernel = ConstantKernel(1.0) * RBF(length_scale=1.0)
    return GaussianProcessRegressor(
        kernel=kernel, n_restarts_optimizer=int(n_restarts), random_state=0)


def _cv_predictions(X: np.ndarray, y: np.ndarray, k: int) -> np.ndarray | None:
    """K 折交叉验证 out-of-fold 预测（按索引取模分折，确定性）。

    任一一折拟合/预测失败返回 None（调用方退回训练残差，不编造数值）。
    """
    n = len(y)
    preds = np.full(n, np.nan, dtype=float)
    for fold in range(int(k)):
        test = np.array([i for i in range(n) if i % k == fold])
        train = np.array([i for i in range(n) if i % k != fold])
        if test.size == 0 or train.size < 2:
            return None
        try:
            gp = _make_gp(CV_GP_RESTARTS)
            gp.fit(X[train], y[train])
            preds[test] = gp.predict(X[test])
        except Exception:
            return None
    if not np.all(np.isfinite(preds)):
        return None
    return preds


def _quality_report(
    X: np.ndarray, y: np.ndarray, y_pred: np.ndarray, cv_folds: int | None,
) -> dict[str, Any]:
    """质量字段：样本充足时给交叉验证 out-of-fold，否则训练残差。"""
    n = int(y.size)
    k = cv_folds
    if k is None:
        k = min(5, n) if n >= 6 else 0
    if k and int(k) >= 2 and n >= 6:
        preds = _cv_predictions(X, y, int(k))
        if preds is not None:
            quality = surrogate_fit_quality(y, preds)
            quality["kind"] = "cross_validation_out_of_fold"
            quality["cv_folds"] = int(k)
            quality["detail"] = (
                f"{int(k)} 折交叉验证 out-of-fold 预测质量"
                "（按索引取模分折，确定性；GP random_state=0）")
            return quality
    quality = surrogate_fit_quality(y, y_pred)
    quality["kind"] = "in_sample_train_residual"
    quality["cv_folds"] = 0
    quality["detail"] = (
        "训练残差口径（样本 <6 或交叉验证失败）；GP 对训练点近插值，"
        "rms 接近 0 不代表泛化质量")
    return quality


def analyze_run_surrogate(
    run_id: str,
    trials_data: list[dict[str, Any]],
    *,
    cv_folds: int | None = None,
) -> SurrogateAnalysisResult:
    """离线分析：从 trials 数据拟合 GP 代理模型。

    Args:
        run_id: 运行 ID
        trials_data: trial 数据列表 [{"params": {...}, "cost": float}, ...]
        cv_folds: 质量评估折数；None=自动（样本 ≥6 时 min(5, n)，
            否则退回训练残差口径）。≥2 且样本 ≥6 时给 out-of-fold 质量。

    Returns:
        SurrogateAnalysisResult（quality 见 surrogate_fit_quality）
    """
    if len(trials_data) < 3:
        raise ValueError(f"至少需要 3 个 trials，当前 {len(trials_data)}")

    # 提取参数和成本
    param_names = sorted(trials_data[0]["params"].keys())
    X = np.array([[t["params"][p] for p in param_names] for t in trials_data])
    y = np.array([t["cost"] for t in trials_data])

    # 找最优 trial
    best_idx = np.argmin(y)
    best_params = trials_data[best_idx]["params"]
    best_cost = float(y[best_idx])

    # 使用 sklearn GP 拟合（random_state 固定 → 可复现）
    try:
        gp = _make_gp(GP_RESTARTS)
        gp.fit(X, y)

        # 训练预测误差（in-sample 口径，保留向后兼容）
        y_pred = gp.predict(X)
        prediction_error = float(np.sqrt(np.mean((y - y_pred) ** 2)))

        # 参数重要性（基于长度尺度）
        length_scales = gp.kernel_.get_params()["k2__length_scale"]
        if np.isscalar(length_scales):
            length_scales = [length_scales] * len(param_names)
        importance = {name: 1.0 / ls for name, ls in zip(param_names, length_scales, strict=False)}
        total = sum(importance.values())
        importance = {k: v / total for k, v in importance.items()}

        quality = _quality_report(X, y, y_pred, cv_folds)

    except ImportError:
        # sklearn 不可用时的降级处理——质量字段标不可用，不填占位数值
        importance = {name: 1.0 / len(param_names) for name in param_names}
        prediction_error = float(np.std(y))
        quality = {
            "n": int(y.size),
            "available": False,
            "kind": "sklearn_unavailable",
            "rms_error": None,
            "mae": None,
            "max_abs_residual": None,
            "r2": None,
            "spearman_rho": None,
            "cv_folds": 0,
            "detail": "sklearn 不可用，GP 未拟合——质量字段不可用（不填占位数值）",
        }

    return SurrogateAnalysisResult(
        run_id=run_id,
        n_samples=len(trials_data),
        n_params=len(param_names),
        best_params=best_params,
        best_cost=best_cost,
        param_importance=importance,
        prediction_error=prediction_error,
        quality=quality,
    )
