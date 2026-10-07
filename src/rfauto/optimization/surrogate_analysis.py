"""E3 代理模型（扩展方案 §E3）。

sklearn GP 离线分析先行（不进 tune 在线路径）。
设计决策：
- 离线分析：读数据湖画曲面找可疑区域
- 不进 tune 在线路径——直到一次真机对照实验证明有效
- sklearn 降回廉价预筛角色符合其单保真本性

B-33（续跑计划 §10.23 补强第三批）：新增代理质量内核
surrogate_fit_quality（ρ/残差/RMS/MAE/R²），analyze_run_surrogate 默认
给 K 折交叉验证 out-of-fold 质量——环报告据此携带真实质量字段，而非占位。
质量数值全部来自确定性纯 numpy/GP 计算（random_state 固定），无墙钟/无网络。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from rfauto.core.metric_transform import (
    is_explicit_statistic_name,
    select_metric_domain,
)

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
    #: 逐参数重要性（D1-1 修复 2026-10-04 起：缺省全 None=不可辨识降级，
    #: 见 param_importance_note；值域 float 仅保留给未来可辨识估计器）
    param_importance: dict[str, float | None]
    prediction_error: float
    #: B-33 代理质量（见 surrogate_fit_quality；空 dict = 未计算）
    quality: dict[str, Any] = field(default_factory=dict)
    #: DP-15 C1：回归目标表示域（缺省 "dB"=既有隐式口径，向后兼容）
    metric_domain: str = "dB"
    #: DP-15 C1：逐域 LOO-LML 选择表（auto_domain=False 或显式统计量
    #: 指标名豁免时为 None——不选择，只报告）
    domain_selection: dict[str, Any] | None = None
    #: D1-1：param_importance 降级/可用性说明（空串=历史口径无说明）
    param_importance_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "n_samples": self.n_samples,
            "n_params": self.n_params,
            "best_params": self.best_params,
            "best_cost": self.best_cost,
            "param_importance": {
                k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in self.param_importance.items()},
            "prediction_error": round(self.prediction_error, 4),
            "param_importance_note": self.param_importance_note,
            "quality": _rounded(self.quality),
            "metric_domain": self.metric_domain,
            "domain_selection": (
                _rounded(self.domain_selection)
                if self.domain_selection is not None else None),
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
    """代理预测质量内核（B-33，确定性纯 numpy，无随机/无网络）。

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


def _make_gp(n_restarts: int, alpha: np.ndarray | None = None):
    """构造确定性 GP（random_state=0）；调用方自行 fit。

    alpha（ME-14）：None=缺省（既有路径构造逐字节不变）；数组=逐点噪声
    方差（sklearn GPR 加在核矩阵对角线），异方差逐点噪声直接入代理。
    """
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel

    kernel = ConstantKernel(1.0) * RBF(length_scale=1.0)
    if alpha is None:
        return GaussianProcessRegressor(
            kernel=kernel, n_restarts_optimizer=int(n_restarts), random_state=0)
    return GaussianProcessRegressor(
        kernel=kernel, alpha=alpha,
        n_restarts_optimizer=int(n_restarts), random_state=0)


def _cv_predictions(
    X: np.ndarray, y: np.ndarray, k: int,
    alpha: np.ndarray | None = None,
) -> np.ndarray | None:
    """K 折交叉验证 out-of-fold 预测（按索引取模分折，确定性）。

    任一一折拟合/预测失败返回 None（调用方退回训练残差，不编造数值）。
    alpha（ME-14）：逐点噪声方差，折内训练用 ``alpha[train]``——与主拟合
    同一异方差口径；None=无逐点噪声（既有行为不变）。
    """
    n = len(y)
    preds = np.full(n, np.nan, dtype=float)
    for fold in range(int(k)):
        test = np.array([i for i in range(n) if i % k == fold])
        train = np.array([i for i in range(n) if i % k != fold])
        if test.size == 0 or train.size < 2:
            return None
        try:
            gp = _make_gp(
                CV_GP_RESTARTS,
                None if alpha is None else np.asarray(alpha)[train])
            gp.fit(X[train], y[train])
            preds[test] = gp.predict(X[test])
        except Exception:
            return None
    if not np.all(np.isfinite(preds)):
        return None
    return preds


def _quality_report(
    X: np.ndarray, y: np.ndarray, y_pred: np.ndarray,
    cv_folds: int | None, alpha: np.ndarray | None = None,
) -> dict[str, Any]:
    """质量字段：样本充足时给交叉验证 out-of-fold，否则训练残差。

    alpha（ME-14）：逐点噪声方差，透传给折内拟合（与主拟合同口径）。
    """
    n = int(y.size)
    k = cv_folds
    if k is None:
        k = min(5, n) if n >= 6 else 0
    if k and int(k) >= 2 and n >= 6:
        preds = _cv_predictions(X, y, int(k), alpha)
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
    metric_name: str | None = None,
    values_domain: str = "dB",
    auto_domain: bool = False,
    y_sigma: Any | None = None,
) -> SurrogateAnalysisResult:
    """离线分析：从 trials 数据拟合 GP 代理模型。

    Args:
        run_id: 运行 ID
        trials_data: trial 数据列表 [{"params": {...}, "cost": float}, ...]
        cv_folds: B-33 质量评估折数；None=自动（样本 ≥6 时 min(5, n)，
            否则退回训练残差口径）。≥2 且样本 ≥6 时给 out-of-fold 质量。
        metric_name: 回归目标对应的指标名（DP-15 C1 豁免判据输入）；
            以 _min/_max 结尾的显式统计量指标名（s11_db_min 等）豁免
            自动选择——表示域固定为 values_domain，不被覆盖。
        values_domain: cost/回归目标的声明表示域（'dB'/'gamma_linear'/
            'magnitude'；缺省 "dB"=项目现口径）。调用方如实声明——
            cost 是 violation 加权和时声明 'dB' 即表示"按现口径处理"。
        auto_domain: DP-15 C1 变换域自动选择开关；缺省 False=行为与
            既有路径一致（fit meta 只新增 metric_domain="dB" 键）。
            True 且非豁免时对目标值跑逐域 LOO-LML（core/metric_transform），
            选择结果写入 domain_selection 表（best-effort #105：选择
            失败不炸分析主路径，错误如实入表）。
        y_sigma: ME-14 逐点噪声（异方差）——每行目标的观测标准差 σ
            （y±σ 校准数据，如 CharImp 三定义 2.5% 分散、锚
            arbitration_interval）。给定时时透传 GPR(alpha=σ²)（逐点
            加在核矩阵对角线，σ 不再被丢弃），CV 折内用 alpha[train]
            同口径；None=现行为逐字节不变。长度须与 trials_data 一致、
            非负有限。σ 全零=退化无异方差信息：不带 alpha kwarg，与
            y_sigma=None 路径逐位一致（d-stream-batch1 口径）。完整
            数据面接线（dataset σ 列自动提取）留后续。

    Returns:
        SurrogateAnalysisResult（quality 见 surrogate_fit_quality；
        metric_domain / domain_selection 见 DP-15 C1；y_sigma 给定时
        quality 附 pointwise_noise 观测块）
    """
    if len(trials_data) < 3:
        raise ValueError(f"至少需要 3 个 trials，当前 {len(trials_data)}")

    # 提取参数和成本（B-6/S3）：键集取全 trials 并集——只取首 trial 键集会
    # 静默丢弃后到 trial 的参数列；有 trial 缺并集键则显式报错（GP 需要完整
    # 设计矩阵，静默跳行=样本缩水且无痕；显式 ValueError 与 <3 trials 同风格）。
    param_names = sorted(set().union(
        *(t["params"].keys() for t in trials_data)))
    for idx, t in enumerate(trials_data):
        missing = [p for p in param_names if p not in t["params"]]
        if missing:
            raise ValueError(
                f"trials_data[{idx}] 缺参数键 {missing}"
                f"（键集按全 trials 并集 {param_names} 收敛）")
    X = np.array([[t["params"][p] for p in param_names] for t in trials_data])
    y = np.array([t["cost"] for t in trials_data])

    # ME-14：逐点噪声校验 + σ→alpha（方差）换算。None=行为不变。
    alpha: np.ndarray | None = None
    all_zero_sigma = False
    if y_sigma is not None:
        sigma = np.asarray(y_sigma, dtype=float).ravel()
        if sigma.shape[0] != len(trials_data):
            raise ValueError(
                f"y_sigma 长度 {sigma.shape[0]} 与 trials 数 {len(trials_data)} 不一致")
        if not np.all(np.isfinite(sigma)) or np.any(sigma < 0):
            raise ValueError("y_sigma 须为非负有限值（逐点观测标准差 σ）")
        # ME-14 退化口径（d-stream-batch1）：σ 全零=无异方差信息，不带
        # alpha kwarg——与 y_sigma=None 旧路径逐位一致（sklearn 缺省
        # alpha=1e-10 语义原样）；部分零仍走数组（零方差点=精确观测，
        # 异方差语义内自洽）。
        all_zero_sigma = bool(sigma.size > 0 and not np.any(sigma > 0.0))
        if not all_zero_sigma:
            alpha = sigma ** 2

    # 找最优 trial
    best_idx = np.argmin(y)
    best_params = trials_data[best_idx]["params"]
    best_cost = float(y[best_idx])

    # 使用 sklearn GP 拟合（random_state 固定 → 可复现）
    try:
        gp = _make_gp(GP_RESTARTS, alpha)
        gp.fit(X, y)

        # 训练预测误差（in-sample 口径，保留向后兼容）
        y_pred = gp.predict(X)
        prediction_error = float(np.sqrt(np.mean((y - y_pred) ** 2)))

        # 参数重要性（D1-1 修复 2026-10-04，runs/review_ge8e/d1_opt_linkage/
        # REPORT.md D1-1）：isotropic RBF（RBF(length_scale=1.0) 标量形态）
        # 拟合出的是单标量 length_scale，旧径把它复制到每参数再归一化 →
        # 重要性恒等 1/n 假排行，消费面 CLI 还渲染成排行条形图。ARD
        # per-length-scale 支路实证否决：GML 拟合的 length_scale 在平滑小
        # 样本域不可辨识（单参数依赖用例标准化+nugget 后仍 0.43/0.57 反向
        # 均匀，两参数同依赖亦然——复现脚本见审查报告）——按审查口径显式
        # 降级：全 None + 原因，不造排行；敏感性排序走 core/sensitivity
        # （Morris/Sobol，其回归钉见 test_sensitivity）。
        importance = {name: None for name in param_names}
        importance_note = (
            "isotropic RBF 内核下逐参数重要性不可辨识（旧 1/n 归一化=假排行"
            "已撤，D1-1）；替代口径=core/sensitivity Morris/Sobol")

        quality = _quality_report(X, y, y_pred, cv_folds, alpha)

    except ImportError:
        # sklearn 不可用时的降级处理——质量字段标不可用，不填占位数值
        importance = {name: None for name in param_names}
        importance_note = "sklearn 不可用，GP 未拟合——重要性不可用（不填占位）"
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

    # DP-15 C1：变换域自动选择（best-effort，#105——观测/选择失败不炸
    # 分析主路径）。显式统计量指标名豁免（交付 4）：s11_db_min 等
    # _min/_max 后缀名的表示语义已由目标定义钉死，自动选择不得覆盖。
    metric_domain = values_domain
    domain_selection: dict[str, Any] | None = None
    if auto_domain:
        if is_explicit_statistic_name(metric_name):
            domain_selection = {
                "selected": values_domain,
                "loo_loglik": None,
                "excluded": {},
                "delta_lml_vs_db": None,
                "exempt": (
                    f"显式统计量指标名 {metric_name} 豁免自动选择——"
                    "表示域固定为声明来源域，不被覆盖"),
            }
        else:
            try:
                domain_selection = select_metric_domain(
                    X, y, values_domain=values_domain)
                metric_domain = str(domain_selection["selected"])
            except Exception as exc:
                domain_selection = {
                    "selected": values_domain,
                    "loo_loglik": None,
                    "excluded": {},
                    "error": f"域选择失败（best-effort #105）: {exc}",
                }

    # ME-14：逐点噪声使用观测（仅 y_sigma 给定时新增键；缺省路径输出不变）
    if y_sigma is not None:
        sigma = np.asarray(y_sigma, dtype=float).ravel()
        quality["pointwise_noise"] = {
            "used": not all_zero_sigma,
            "n": int(sigma.size),
            "sigma_min": float(np.min(sigma)),
            "sigma_max": float(np.max(sigma)),
            "detail": ("σ 全零退化：无异方差信息，GPR 不带 alpha kwarg"
                       "（与 y_sigma=None 逐位一致）"
                       if all_zero_sigma else
                       "GPR alpha=σ² 逐点异方差噪声（σ 由调用方提供，非估计值）"),
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
        metric_domain=metric_domain,
        domain_selection=domain_selection,
        param_importance_note=importance_note,
    )
