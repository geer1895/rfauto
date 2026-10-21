"""EC-18 TuRBO-1 式信任域贝叶斯优化（trust_region 旁的 batch-GP 路径）。

池 P3 圈定件（架构批 W5-S22；ecosystem §二 EC-18）。法源：
- TuRBO（D. Eriksson, M. Pearce, J. Gardner, R. Turner, M. Poloczek,
  "Scalable Global Optimization via Local Bayesian Optimization",
  NeurIPS 2019）：TuRBO-1 = 单信任域循环——域内局部 GP + Thompson
  采样提议 + 按连续成功/失败计数伸缩信任域边长（×2 / ×0.5），域塌缩
  后以 incumbent 为中心重开；
  成功/失败计数伸缩信任域边长（×2 / ×0.5），域塌缩后以 incumbent 为
  中心重开；
- **官方计数器对称性核对结论（架构批 W2-S8，W6-P3-1 清偿；review_w6
  曾凭记忆记"官方非对称=成功不清零"系误记，按 #122 以官方源为准）**：
  官方仓 uber-research/TuRBO（NeurIPS 2019 配套代码，master 分支
  turbo/turbo_1.py ``_adjust_length``，2026-10-18 原文取回逐行核对）——
  成功分支 ``succcount += 1; failcount = 0``、失败分支
  ``succcount = 0; failcount += 1``：**双方互清零=官方即对称口径**，
  与本实现一致；触发判据官方 ``==`` 容差且触发即清零 vs 本实现 ``>=``
  且触发即清零（计数每步至多达容差，两写法等价）；官方成功判据含小幅
  松弛 ``f < fmin − 1e-3·|fmin|``（噪声免费设定下的数值防抖）vs 本实现
  严格 ``cost < best``（无松弛，如实声明差异）；failtol 官方
  ``ceil(max(4/batch, d/batch))``、batch=1 时=max(4, d) 与本实现缺省
  一致；succtol=3、length_min=0.5**7、扩边 ×2 封顶、缩边 ÷2 全一致；
- 与既有 optimization/trust_region.py 的关系：那件是 TR-ARS+ Bandler
  输出空间映射（代理校正语义，surrogate_registry 全局模型 + TPE 虚拟
  寻优）；本模块是 TuRBO-1 原义（局部 GP + Thompson 采样，无输出映射
  校正档）——**平行新模块，trust_region.py 零改动**（消费接口零破坏
  铁律；两档语义差异见各自 docstring，调用方按场景选）。

简化与诚实边界（empirical 档如实标注）：
- 接受判据用 incumbent 改进（success = 本点 cost < 现 incumbent），
  未实现原论文的多臂 scorer/GP-LCB 组合打分器（TuRBO-5/TuRBO 彩票池
  更不在本档）；
- length_max=1.0（单元立方全域；论文 1.6 经域裁剪后等效）；
- 局部 GP = gp_det MLE 档（固定初值确定性优化），域内点 <4 时直接在
  域内均匀补点（原论文同况走 sobol 均匀，语义等价—— 都是模型外探索）。

评估失败（evaluate_fn 抛异常）逐次计数入 attempts 并按失败迭代处理，
不中断循环（真机通道诚实契约，同 surrogate_loop 家族口径）。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from rfauto.core.objectives import Objective, SpecEvaluator
from rfauto.optimization.surrogate.gp_det import DetGaussianProcess, fit_mle

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_LENGTH_INIT", "DEFAULT_LENGTH_MIN", "run_turbo"]

#: 初始信任域半边长（单元空间；TuRBO-1 论文口径 0.4）
DEFAULT_LENGTH_INIT = 0.4

#: 塌缩下限（论文 0.5^7；达到即以 incumbent 为中心重开）
DEFAULT_LENGTH_MIN = 0.5 ** 7

#: 信任域连续成功扩边阈值（论文 success_tolerance=3）
_SUCCESS_TOLERANCE = 3

_GAMMA = 2.0
_GAMMA_DOWN = 0.5

#: 域内点少于此数时本轮直接域内均匀补点（模型外探索）
_MIN_REGION_POINTS = 4

#: Thompson 采样候选数（域内均匀撒点后按后验样本取 argmin）
_N_CANDIDATES = 128


def run_turbo(
    bounds: dict[str, tuple[float, float]],
    objectives: list[Objective],
    evaluate_fn: Callable[[dict[str, float]], dict[str, float]],
    *,
    n_init: int = 16,
    n_iter: int = 40,
    seed: int = 42,
    length_init: float = DEFAULT_LENGTH_INIT,
    length_min: float = DEFAULT_LENGTH_MIN,
    success_tolerance: int = _SUCCESS_TOLERANCE,
    failure_tolerance: int | None = None,
    n_candidates: int = _N_CANDIDATES,
) -> dict[str, Any]:
    """TuRBO-1 循环（evaluate_fn 注入，零真机可验证；返回 JSON 友好契约）。

    n_init 个 LHS 全域点预热 → 逐迭代：局部 GP（信任域内样本）→ 域内
    Thompson 采样提议 → 真评 → incumbent 更新 → 域伸缩。返回
    {ok, algorithm:"turbo1", best, n_real_used, n_attempts, trace,
    length_trace, failures, elapsed_s}。
    """
    t0 = time.time()
    if n_init < 2 or n_iter < 1:
        return {"ok": False,
                "errors": ["n_init≥2 且 n_iter≥1 才构成 TuRBO-1 循环"]}
    names = sorted(bounds)
    d = len(names)
    lower = np.array([bounds[n][0] for n in names])
    span = np.array([max(bounds[n][1] - bounds[n][0], 1e-12)
                     for n in names])
    fail_tol = int(failure_tolerance if failure_tolerance is not None
                   else max(4, d))

    rng = np.random.default_rng(seed)
    from rfauto.optimization.sample_design import lhs_points

    unit_hist: list[np.ndarray] = []
    cost_hist: list[float] = []
    failures: list[dict[str, int]] = []
    phase = ["init", -1]

    def _evaluate(u: np.ndarray) -> float | None:
        params = {n: float(lower[i] + u[i] * span[i])
                  for i, n in enumerate(names)}
        try:
            metrics = evaluate_fn(params)
        except Exception as exc:  # 真机通道失败诚实计数（不中断）
            logger.warning("turbo evaluate_fn 失败: %s", exc)
            failures.append({"phase": phase[0], "index": phase[1]})
            return None
        cost = SpecEvaluator.evaluate_objectives(metrics, objectives)
        unit_hist.append(np.array(u, dtype=float))
        cost_hist.append(float(cost))
        return float(cost)

    # ---- LHS 预热（全域；sample_design 同源 LHS，seed 同源确定性）---- #
    init = lhs_points(bounds, n_init, seed=seed)
    for i_pt, pt in enumerate(init["points"]):
        phase[0], phase[1] = "init", i_pt
        _evaluate(np.array([(pt[n] - lower[i]) / span[i]
                            for i, n in enumerate(names)]))
    best_i = int(np.argmin(cost_hist)) if cost_hist else -1
    best_cost = float(cost_hist[best_i]) if best_i >= 0 else np.inf
    best_u = unit_hist[best_i].copy() if best_i >= 0 else rng.random(d)

    length = float(min(max(length_init, 2.0 * length_min), 1.0))
    center = best_u.copy()
    n_success = 0
    n_fail = 0
    trace: list[dict[str, Any]] = []
    length_trace: list[float] = []
    n_attempts = len(init["points"])  # 预热全部计入 attempts（成功与否）

    for it in range(int(n_iter)):
        phase[0], phase[1] = "iter", it
        pts = np.array(unit_hist) if unit_hist else np.zeros((0, d))
        costs = np.array(cost_hist) if cost_hist else np.zeros(0)
        in_region = (np.max(np.abs(pts - center), axis=1) <= length) \
            if len(pts) else np.zeros(0, dtype=bool)
        reg_x = pts[in_region]
        reg_y = costs[in_region]
        proposed: np.ndarray | None = None
        if len(reg_x) >= _MIN_REGION_POINTS:
            params = fit_mle(reg_x, reg_y, kind="se")
            gp = DetGaussianProcess(reg_x, reg_y, params, "se")
            cand = np.clip(center + length * (2.0 * rng.random(
                (int(n_candidates), d)) - 1.0), 0.0, 1.0)
            mean, var = gp.predict(cand)
            std = np.sqrt(np.maximum(var, 0.0))
            draws = mean + std * rng.standard_normal(len(cand))
            proposed = cand[int(np.argmin(draws))]
        else:
            proposed = np.clip(center + length * (2.0 * rng.random(d) - 1.0),
                               0.0, 1.0)
        n_attempts += 1
        cost = _evaluate(proposed)
        improved = cost is not None and cost < best_cost
        if improved:
            best_cost = float(cost)
            best_u = proposed.copy()
            center = proposed.copy()
            n_success += 1
            n_fail = 0
        else:
            n_fail += 1
            n_success = 0
        if n_success >= int(success_tolerance):
            length = min(_GAMMA * length, 1.0)
            n_success = 0
        elif n_fail >= fail_tol:
            length = _GAMMA_DOWN * length
            n_fail = 0
            if length <= length_min:
                # 塌缩重开：中心回 incumbent、边长回初值（TuRBO-1 语义）
                center = best_u.copy()
                length = float(min(max(length_init, 2.0 * length_min), 1.0))
                n_success = 0
                n_fail = 0
        length_trace.append(float(length))
        trace.append({
            "iter": it,
            "cost": (float(cost) if cost is not None else None),
            "best_cost": float(best_cost),
            "improved": bool(improved),
            "length": float(length),
        })

    best_params = {n: float(lower[i] + best_u[i] * span[i])
                   for i, n in enumerate(names)}
    return {
        "ok": bool(cost_hist),
        "algorithm": "turbo1",
        "best": {"params": best_params, "cost": float(best_cost)},
        "n_real_used": len(unit_hist),
        "n_attempts": n_attempts,
        "trace": trace,
        "length_trace": length_trace,
        "failures": failures,
        "note": ("TuRBO-1 简化档：incumbent 改进接受判据+单域循环；"
                 "length_max=1.0（全域裁剪后与论文 1.6 等效）"),
        "elapsed_s": round(time.time() - t0, 3),
    }
