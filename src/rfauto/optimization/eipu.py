"""M3 EIpu 成本感知 BO（cost GP + EI/c）+ R9 敏感度先承诺排序件。

月计划（月度增强方案 §D 流 M3 行）：
acquisition = EI(x) / ĉ(x)，ĉ = 第二支独立 GP 学仿真代价（openEMS 秒级/
HFSS 分钟级天然多档；log-cost 域拟合稳定）——预算约束下性价比驱动采样。

设计（d-stream-batch1 批）：
- 纯函数内核零 IO（service JSON 面留后续接线；本批 core+tests 交付，
  CLI/MCP 不加——任务书约定避五钉清单联动）；
- 采样器形态=**独立 suggest 循环**（仓内无自定义 optuna BaseSampler
  先例，接地实证：optimizer.py 的 tpe/cmaes/gp 全是 optuna 内建实例——
  自研 acquisition 挂 study 留给后续优化器接线批，本模块只出
  suggest_next_point/run_eipu_loop 确定性内核）；
- GP 走 sklearn GaussianProcessRegressor（仓内 surrogate_analysis 同源
  口径：ConstantKernel×RBF、random_state 钉死确定性）；sklearn 缺席时
  显式 ImportError（#122 不降级不编造）；
- EI 为最小化口径：EI(x) = (y*−ξ−μ)·Φ(z) + σ·φ(z)，z=(y*−ξ−μ)/σ；
  σ→0 退化 max(0, y*−ξ−μ)；
- cost GP 在 log 域拟合（ĉ=exp(pred)>0 恒成立），EIpu 分数
  = EI/(ĉ+ε)，ε=EIPUConfig.cost_epsilon 防 1/c 爆项。诚实边界（#122）：
  ĉ=exp(E[log c]) 是 lognormal 均值 E[c]=exp(μ+σ²/2) 的**下偏估计**
  （偏置 exp(σ²/2)−1，GP 后验 σ=0.3 时 ~4.6%），σ 大的外推域系统性
  低估代价；log 域拟合是 cost-aware BO 标准做法、对采集排序影响有限，
  该偏置如实记录不做修正项。

R9 排序承诺件（方案池:225「按 Sobol S1/闭式
可解析度排序模板参数，高敏感者先钉死」）：仓内已有 sensitivity.py 的
sobol_sensitivity/morris_screening 产分数，本模块补**排序承诺**纯函数
commitment_order（分数→高敏感先钉死的确定性排序，同名稳定平局）。

确定性（可复现红线）：全部随机经 np.random.default_rng(config.seed)；
GP random_state 钉死；同输入同建议（C4 纯函数语义）。

合成裁判（tests/unit/test_eipu_sampler.py，判据预声明在该文件
docstring）：已知 cost 结构 c(x)=1+9x² + 已知双谷 f——全局谷在昂贵区
（吸附纯 EI）、近优谷在廉价区；预算内逐点比较命中累计代价与 best-f
AUC，EIpu 须在多数 seed 上优于纯 EI。

OP-3 cost-cooling（round16 §六；修 CArBO 指出的"便宜但差"偏置，
arXiv:2003.10870 一族 cost-aware BO 的退火处方）：strategy="eipu_cooled"
把 cost 惩罚指数按预算消耗自 β=1（=纯 EIpu，全程 cost-aware）退火到
β=0（=纯 EI，只看目标）——score = EI/(ĉ+ε)^β_t。动机：EIpu 的 1/ĉ
项会永久偏好便宜区域（廉价区近优谷吸附），预算充足时错过昂贵区的
全局谷；冷却让前期省钱探查、后期按目标收尾。β_t 由
:func:`cost_cooling_beta` 按 cooling_progress∈[0,1] 产出（线性/指数
两档日程，缺省线性）；run_eipu_loop 在 eipu_cooled 档逐迭代以
dataclasses.replace 注入 progress=已用迭代/总迭代（纯函数无状态）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

#: 模块缺省随机种子（20260928=批次日；显式 seed 参数可换轨迹）
EIPU_SEED = 20260928
#: EI 的 σ 地板（防除零；低于此视作确定性预测）
EI_SIGMA_FLOOR = 1e-12
#: 候选点与已观测点的最小归一化距离（去重守卫；同 surrogate_loop
#: BATCH_MIN_DIST 精神——重复观测零信息）
MIN_CANDIDATE_DIST = 1e-6

#: cost-cooling 支持的日程模式（OP-3）：线性 / 指数（β 前期衰减慢、
#: 后期加速归零，保守探索段更长）
COOLING_MODES = ("linear", "exponential")


@dataclass(frozen=True)
class EIPUConfig:
    """EIpu/EI suggest 内核配置（dataclass 冻结，同参同输出）。"""

    #: EI 探索参数 ξ（最小化口径下从 y* 里扣，压低已知好点的 EI）
    xi: float = 0.01
    #: EIpu 分母防爆项 ε（cost 单位与 ĉ 同量纲）
    cost_epsilon: float = 1e-6
    #: 每次 suggest 的候选池大小（均匀随机，seed 派生）
    n_candidates: int = 512
    #: 随机种子（候选池 + GP 重启随机性全走它）
    seed: int = EIPU_SEED
    #: cost GP 在 log 域拟合（默认 True；ĉ=exp(pred) 恒正）
    log_cost: bool = True
    #: sklearn GPR 重启次数（f 与 cost GP 同参）
    gp_restarts: int = 2
    #: OP-3 cost-cooling 进度 ∈[0,1]（仅 strategy="eipu_cooled" 消费）：
    #: 0=预算起点（β=beta_start，全 cost-aware）→ 1=预算耗尽（β=beta_end，
    #: 纯 EI）。由 run_eipu_loop 逐迭代 replace 注入；直接调
    #: suggest_next_point/score_candidates 时由调用方负责设置。
    cooling_progress: float = 0.0
    #: cost 惩罚指数日程起点/终点（β 界 [0,1]；1=EIpu，0=EI）
    cooling_beta_start: float = 1.0
    cooling_beta_end: float = 0.0
    #: 日程模式："linear" | "exponential"（见 COOLING_MODES）
    cooling_mode: str = "linear"


def cost_cooling_beta(
    progress: float,
    *,
    beta_start: float = 1.0,
    beta_end: float = 0.0,
    mode: str = "linear",
) -> float:
    """OP-3 cost-cooling 惩罚指数 β_t（纯函数）。

    progress ∈ [0,1] 为预算消耗进度；β=1 时采集退化为纯 EIpu
    （cost 惩罚全额），β=0 时退化为纯 EI（cost-blind）。线性日程
    β = start + (end−start)·progress；指数日程以 (1−progress) 为时间
    轴（前期衰减慢→保守探索段更长）：β = end + (start−end)·(1−p)^2。

    Raises:
        ValueError: progress 越界 / β 界出 [0,1] / start<end（退火只降
            不升）/ mode 未知。
    """
    p = float(progress)
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        raise ValueError(f"cooling progress 必须落在 [0,1]，得到 {progress!r}")
    s, e = float(beta_start), float(beta_end)
    if not (0.0 <= e <= 1.0 and 0.0 <= s <= 1.0):
        raise ValueError(f"β 界必须落在 [0,1]：start={s}, end={e}")
    if s < e:
        raise ValueError("退火只降不升：beta_start 不得小于 beta_end")
    if mode not in COOLING_MODES:
        raise ValueError(f"未知 cooling mode: {mode}（可选 {' | '.join(COOLING_MODES)}）")
    if mode == "linear":
        return s + (e - s) * p
    return e + (s - e) * (1.0 - p) ** 2


def expected_improvement_min(
    mu: np.ndarray, sigma: np.ndarray, y_best: float, xi: float = 0.01,
) -> np.ndarray:
    """最小化口径 Expected Improvement（纯函数）。

    EI(x) = E[max(y* − ξ − f(x), 0)] = (y*−ξ−μ)·Φ(z) + σ·φ(z)，
    z = (y*−ξ−μ)/σ；σ≤地板时退化 max(0, y*−ξ−μ)。
    """
    mu = np.asarray(mu, dtype=float).ravel()
    sigma = np.asarray(sigma, dtype=float).ravel()
    if mu.shape != sigma.shape:
        raise ValueError(f"mu/sigma 形状不一致: {mu.shape} vs {sigma.shape}")
    if not np.all(np.isfinite(mu)) or not np.all(np.isfinite(sigma)):
        raise ValueError("mu/sigma 含非有限值")
    if np.any(sigma < 0.0):
        raise ValueError("sigma 须非负")
    improvement = float(y_best) - float(xi) - mu
    out = np.empty_like(improvement)
    tiny = sigma <= EI_SIGMA_FLOOR
    # 确定性分支：σ 地板以下直接截断（无 Φ/φ 数值噪声）
    out[tiny] = np.maximum(improvement[tiny], 0.0)
    s = sigma[~tiny]
    with np.errstate(divide="ignore", invalid="ignore"):
        z = improvement[~tiny] / s
    phi = np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    Phi = 0.5 * (1.0 + _erf(z / math.sqrt(2.0)))
    out[~tiny] = improvement[~tiny] * Phi + s * phi
    return out


def _erf(x: np.ndarray) -> np.ndarray:
    """math.erf 的逐元素包装（零 scipy 依赖）。"""
    return np.vectorize(math.erf, otypes=[float])(x)


def _fit_predict_gp(
    X_train: np.ndarray, y_train: np.ndarray, X_cand: np.ndarray,
    restarts: int, seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """拟合并预测（μ, σ）；sklearn 缺席显式 ImportError 不降级。

    输入须已归一化到单位立方体（suggest_next_point 负责换算）。
    采集内核的三项稳定化（原型实证，2 点初始化即触发退化）：
    - RBF length_scale 界 (0.1, 3.0)：无下界的 ML-II 在 n<4 时偏好
      微小 ls（两点零矛盾可完美插值）→ σ 全域塌零、EI/ĉ 梯度尽失；
      ls<0.1（归一化单位）意味着点间零信息共享，对采集无意义；
    - normalize_y=True：先验均值=训练均值——cost GP 外推域返回
      平均代价量级而非 exp(0)=1（后者=全域"免费"伪象，会主动鼓励
      跑到未观测远端）；
    - 幅值 ConstantKernel 界 (1e-3, 1e3) 防幅度退化。
    """
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel

    gp = GaussianProcessRegressor(
        kernel=ConstantKernel(1.0, (1e-3, 1e3))
        * RBF(length_scale=1.0, length_scale_bounds=(0.1, 3.0)),
        n_restarts_optimizer=int(restarts), random_state=int(seed),
        normalize_y=True)
    gp.fit(X_train, y_train)
    mu, sigma = gp.predict(X_cand, return_std=True)
    return (np.asarray(mu, dtype=float).ravel(),
            np.asarray(sigma, dtype=float).ravel())


def _candidate_pool(
    bounds: Mapping[str, tuple[float, float]], n: int, seed: int,
) -> tuple[list[str], np.ndarray]:
    """确定性均匀候选池（names 排序序=列序，与 surrogate_analysis 同约定）。"""
    names = sorted(bounds)
    rng = np.random.default_rng(seed)
    cols = [rng.uniform(float(bounds[k][0]), float(bounds[k][1]), size=int(n))
            for k in names]
    return names, np.column_stack(cols)


def _row_to_params(names: list[str], row: np.ndarray) -> dict[str, float]:
    return {k: float(v) for k, v in zip(names, row, strict=True)}


def _strategy_cost_aware(strategy: str) -> bool:
    """strategy 是否消费 cost 观测（eipu / eipu_cooled）。"""
    if strategy not in ("eipu", "ei", "eipu_cooled"):
        raise ValueError(
            f"未知 strategy: {strategy}（可选 eipu | ei | eipu_cooled）")
    return strategy in ("eipu", "eipu_cooled")


def score_candidates(
    X: np.ndarray, y: np.ndarray, cost: np.ndarray | None,
    points: list[dict[str, float]],
    bounds: Mapping[str, tuple[float, float]], *,
    strategy: str = "eipu",
    config: EIPUConfig | None = None,
) -> list[dict[str, Any]]:
    """在给定点上评估采集分数（审计/裁判面：逐点 EI、ĉ、score）。

    与 suggest_next_point 同一 GP/同一口径——差异只在打分点是调用方
    指定的（不取 argmax）。用途：acquisition 排序的机制级审计（如
    cost 条件化翻转排序的合成裁判），与调参面候选对比。
    strategy="eipu_cooled"（OP-3）时 score = EI/(ĉ+ε)^β_t，β_t 由
    config.cooling_progress 经 :func:`cost_cooling_beta` 产出，并在
    逐点记录里附 ``beta``。
    """
    cfg = config or EIPUConfig()
    cost_aware = _strategy_cost_aware(strategy)
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float).ravel()
    if X.ndim != 2 or X.shape[0] != y.size or y.size < 2:
        raise ValueError("X (n,d)/y (n,) 形状不一致或样本 <2")
    names = sorted(bounds)
    if X.shape[1] != len(names):
        raise ValueError(
            f"X 列数 {X.shape[1]} 与 bounds 维数 {len(names)} 不一致")
    lo = np.array([float(bounds[k][0]) for k in names])
    hi = np.array([float(bounds[k][1]) for k in names])
    span = np.maximum(hi - lo, 1e-12)
    Xn = (X - lo) / span
    rows = np.array([[float(p[k]) for k in names] for p in points])
    rowsn = (rows - lo) / span
    mu, sigma = _fit_predict_gp(Xn, y, rowsn, cfg.gp_restarts, cfg.seed)
    ei = expected_improvement_min(mu, sigma, float(np.min(y)), cfg.xi)
    beta = 1.0
    c_hat = np.ones_like(ei)
    if cost_aware:
        if cost is None:
            raise ValueError(f'strategy="{strategy}" 需要 cost 观测（每点 >0 有限值）')
        c = np.asarray(cost, dtype=float).ravel()
        if c.shape != y.shape or not np.all(np.isfinite(c)) or np.any(c <= 0):
            raise ValueError("cost 须与 y 等长且逐点 >0 有限")
        c_target = np.log(c) if cfg.log_cost else c
        cmu, _ = _fit_predict_gp(Xn, c_target, rowsn, cfg.gp_restarts,
                                 cfg.seed)
        c_hat = np.exp(cmu) if cfg.log_cost else np.maximum(cmu, 1e-12)
        beta = (cost_cooling_beta(
            cfg.cooling_progress,
            beta_start=cfg.cooling_beta_start,
            beta_end=cfg.cooling_beta_end,
            mode=cfg.cooling_mode,
        ) if strategy == "eipu_cooled" else 1.0)
        score = ei / (c_hat + float(cfg.cost_epsilon)) ** beta
    else:
        score = ei  # 旧路径逐字节不变（ei 不除 (1+ε)）
    return [
        {"point": dict(p), "mu": float(mu[i]), "sigma": float(sigma[i]),
         "ei": float(ei[i]), "c_hat": float(c_hat[i]),
         "beta": float(beta), "score": float(score[i])}
        for i, p in enumerate(points)
    ]


def suggest_next_point(
    X: np.ndarray, y: np.ndarray, cost: np.ndarray | None,
    bounds: Mapping[str, tuple[float, float]], *,
    strategy: str = "eipu",
    config: EIPUConfig | None = None,
) -> tuple[dict[str, float] | None, dict[str, Any]]:
    """EIpu/EI 采集函数建议下一观测点（确定性纯函数）。

    Args:
        X: (n, d) 已观测参数矩阵（列序=sorted(bounds)）
        y: (n,) 目标值（最小化）
        cost: (n,) 每点观测代价（>0 有限）；strategy="eipu"/"eipu_cooled"
            必填，"ei" 忽略（可为 None）
        bounds: {参数名: (lo, hi)} 参数盒
        strategy: "eipu"（EI/(ĉ+ε)，cost-aware）| "ei"（纯 EI，cost-blind）
            | "eipu_cooled"（OP-3：EI/(ĉ+ε)^β_t，β_t 随预算消耗退火）
        config: EIPUConfig（None=缺省；eipu_cooled 档消费
            cooling_progress/cooling_beta_start/cooling_beta_end/cooling_mode）

    Returns:
        (params dict, diagnostics)；diagnostics 含候选池上的
        {mu, sigma, ei, c_hat, score} 最优点取值与 strategy/配置回显
        （eipu_cooled 附生效 beta）。
        观测空间饱和（候选池全被已评估点去重）时 params=None 且
        diagnostics 带 ``saturated=True``（不静默建议重复观测点）；
        正常路径 diagnostics 显式带 ``saturated=False``。

    Raises:
        ValueError: 形状不一致 / cost 非正非有限 / strategy 未知 /
            样本数 <2（GP 无法拟合）。
    """
    cfg = config or EIPUConfig()
    cost_aware = _strategy_cost_aware(strategy)
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float).ravel()
    if X.ndim != 2 or X.shape[0] != y.size:
        raise ValueError(f"X/y 形状不一致: X{X.shape} vs y{y.shape}")
    if y.size < 2:
        raise ValueError("至少需要 2 个已观测点（GP 拟合下限）")
    names, cand = _candidate_pool(bounds, cfg.n_candidates, cfg.seed)
    if X.shape[1] != len(names):
        raise ValueError(
            f"X 列数 {X.shape[1]} 与 bounds 维数 {len(names)} 不一致")
    # 归一化到单位立方体（GP 拟合稳定性的前提，见 _fit_predict_gp 说明）
    lo = np.array([float(bounds[k][0]) for k in names])
    hi = np.array([float(bounds[k][1]) for k in names])
    span = np.maximum(hi - lo, 1e-12)
    Xn = (X - lo) / span
    candn = (cand - lo) / span
    mu, sigma = _fit_predict_gp(Xn, y, candn, cfg.gp_restarts, cfg.seed)
    ei = expected_improvement_min(mu, sigma, float(np.min(y)), cfg.xi)
    beta = 1.0
    c_hat = np.ones_like(ei)
    if cost_aware:
        if cost is None:
            raise ValueError(f'strategy="{strategy}" 需要 cost 观测（每点 >0 有限值）')
        c = np.asarray(cost, dtype=float).ravel()
        if c.shape != y.shape or not np.all(np.isfinite(c)) or np.any(c <= 0):
            raise ValueError("cost 须与 y 等长且逐点 >0 有限")
        # log 域拟合：ĉ=exp(pred) 恒正（log_cost=False 直拟原域）
        c_target = np.log(c) if cfg.log_cost else c
        cmu, _ = _fit_predict_gp(Xn, c_target, candn, cfg.gp_restarts,
                                 cfg.seed)
        c_hat = np.exp(cmu) if cfg.log_cost else np.maximum(cmu, 1e-12)
        beta = (cost_cooling_beta(
            cfg.cooling_progress,
            beta_start=cfg.cooling_beta_start,
            beta_end=cfg.cooling_beta_end,
            mode=cfg.cooling_mode,
        ) if strategy == "eipu_cooled" else 1.0)
        score = ei / (c_hat + float(cfg.cost_epsilon)) ** beta
    else:
        score = ei  # 旧路径逐字节不变
    # 去重守卫：与已观测点归一化距离过近的候选不重复建议（零信息）
    Xd = Xn
    Cd = candn
    dist = np.min(
        np.sqrt(((Cd[:, None, :] - Xd[None, :, :]) ** 2).sum(axis=2)),
        axis=1) if X.shape[0] else np.full(len(cand), np.inf)
    deduped = dist < MIN_CANDIDATE_DIST
    n_deduped = int(np.sum(deduped))
    if n_deduped == len(cand):
        # 全候选与已评估点距离 < MIN_CANDIDATE_DIST：观测空间在该分辨率下
        # 饱和。argmax 对全 -inf 静默返回索引 0（重复观测点，零信息）——
        # 改为显式信号（params=None + saturated），由 caller 决定停环/换窗。
        return None, {
            "strategy": strategy,
            "xi": cfg.xi,
            "n_candidates": int(cfg.n_candidates),
            "y_best": float(np.min(y)),
            "beta": float(beta),
            "saturated": True,
            "n_deduped": n_deduped,
        }
    score = np.where(deduped, -np.inf, score)
    best = int(np.argmax(score))
    diag: dict[str, Any] = {
        "strategy": strategy,
        "xi": cfg.xi,
        "n_candidates": int(cfg.n_candidates),
        "y_best": float(np.min(y)),
        "mu": float(mu[best]),
        "sigma": float(sigma[best]),
        "ei": float(ei[best]),
        "c_hat": float(c_hat[best]),
        "beta": float(beta),
        "score": float(score[best]),
        "saturated": False,
        "n_deduped": n_deduped,
    }
    return _row_to_params(names, cand[best]), diag


def run_eipu_loop(
    objective: Callable[[dict[str, float]], float],
    cost_fn: Callable[[dict[str, float]], float],
    bounds: Mapping[str, tuple[float, float]], *,
    n_iters: int,
    strategy: str = "eipu",
    n_init: int = 3,
    config: EIPUConfig | None = None,
    init_points: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """确定性 BO 循环（suggest 内核驱动；零 IO 零并发）。

    初始 DOE 优先取 ``init_points``（调用方给定的分层/先验起点，逐点
    求值）；否则用 config.seed 均匀采样 n_init 点。两臂 A/B 传同
    config + 同 init_points 即同起点同候选（公平对照——把初始化彩票
    从裁判里剥离，只考采集函数的 cost 条件化）。

    Returns:
        {"trials": [{"params", "y", "cost"}...], "cum_cost": [每步后累计
        代价], "best_f_history": [每步后 best f], "strategy", "budget_used",
        "saturated": 观测空间饱和提前停环标记（False=跑满 n_iters）}
    """
    cfg = config or EIPUConfig()
    names = sorted(bounds)
    rng = np.random.default_rng(cfg.seed)
    trials: list[dict[str, Any]] = []
    X_rows: list[list[float]] = []
    ys: list[float] = []
    cs: list[float] = []

    def _eval_point(params: dict[str, float]) -> None:
        yv = float(objective(params))
        cv = float(cost_fn(params))
        trials.append({"params": dict(params), "y": yv, "cost": cv})
        X_rows.append([float(params[k]) for k in names])
        ys.append(yv)
        cs.append(cv)

    # 初始 DOE：显式 init_points 优先（A/B 分层对照），否则同种子均匀采样
    if init_points:
        for p in init_points:
            missing = [k for k in names if k not in p]
            if missing:
                raise ValueError(f"init_points 缺参数: {missing}")
            _eval_point({k: float(p[k]) for k in names})
    else:
        for _ in range(max(int(n_init), 1)):
            row = [float(rng.uniform(float(bounds[k][0]), float(bounds[k][1])))
                   for k in names]
            _eval_point(dict(zip(names, row, strict=True)))
    # BO 循环（观测空间饱和 → suggest 返回 None → 提前停：继续迭代只会
    # 重复评估已观测点，零信息；saturated 标记如实透出停环原因）。
    # OP-3：strategy="eipu_cooled" 时逐迭代以 replace 注入预算进度
    # progress=(i+1)/n_iters（0 次迭代不进循环，无除零面）。
    saturated = False
    for i in range(max(int(n_iters), 0)):
        iter_cfg = cfg
        if strategy == "eipu_cooled" and int(n_iters) > 0:
            iter_cfg = replace(cfg, cooling_progress=(i + 1) / int(n_iters))
        params, _diag = suggest_next_point(
            np.array(X_rows), np.array(ys), np.array(cs), bounds,
            strategy=strategy, config=iter_cfg)
        if params is None:
            saturated = True
            break
        _eval_point(params)
    cum: list[float] = []
    best_hist: list[float] = []
    run_best = math.inf
    total = 0.0
    for t in trials:
        total += float(t["cost"])
        run_best = min(run_best, float(t["y"]))
        cum.append(total)
        best_hist.append(run_best)
    return {
        "trials": trials,
        "cum_cost": cum,
        "best_f_history": best_hist,
        "strategy": strategy,
        "budget_used": total,
        "saturated": saturated,
    }


def commitment_order(scores: Mapping[str, float]) -> list[dict[str, Any]]:
    """R9 最受限先承诺参数排序（分数 → 高敏感先钉死的确定性序列）。

    语义（方案池:225）：按敏感度分数（Sobol S1/
    闭式可解析度，调用方产）降序排序——高敏感者先钉死，其余参数域随后
    收缩。平局按参数名升序（稳定、可复现）。

    Returns:
        [{"rank": 1, "param": str, "score": float}, ...]

    Raises:
        ValueError: 空 scores / 任一分数非有限或 <0 / 键非 str / 值为
            bool 或 str（bool/str 数字显式拒收——``float("0.9")`` 会静默
            接受字符串数字，fail-closed 缺口；df7+⑯ 同口径）。
    """
    clean: dict[str, float] = {}
    for key, value in scores.items():
        if not isinstance(key, str) or isinstance(key, bool):
            raise ValueError(f"参数名须为 str: {key!r}")
        if isinstance(value, (bool, str)) or not math.isfinite(float(value)):
            raise ValueError(
                f"敏感度分数须为有限数值（bool/str 数字显式拒收）: "
                f"{key}={value!r}")
        if float(value) < 0.0:
            raise ValueError(f"敏感度分数须 ≥0: {key}={value}")
        clean[key] = float(value)
    if not clean:
        raise ValueError("scores 为空（无可排序参数）")
    ordered = sorted(clean.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"rank": i + 1, "param": k, "score": v}
            for i, (k, v) in enumerate(ordered)]
