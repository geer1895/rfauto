"""EC-18 TuRBO-1 式信任域贝叶斯优化（trust_region 旁的 batch-GP 路径）。

池 P3 圈定件（aurora_e W5-S22；ecosystem §二 EC-18）。法源：
- TuRBO（D. Eriksson, M. Pearce, J. Gardner, R. Turner, M. Poloczek,
  "Scalable Global Optimization via Local Bayesian Optimization",
  NeurIPS 2019）：TuRBO-1 = 单信任域循环——域内局部 GP + Thompson
  采样提议 + 按连续成功/失败计数伸缩信任域边长（×2 / ×0.5），域塌缩
  后以 incumbent 为中心重开；
  成功/失败计数伸缩信任域边长（×2 / ×0.5），域塌缩后以 incumbent 为
  中心重开；
- **官方计数器对称性核对结论（aurora_f W2-S8，W6-P3-1 清偿；review_w6
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

T-N10（aurora_n W2）新增多臂/多重启形态与 REI 采集档（本节为增量，
TuRBO-1 路径 :func:`run_turbo` 零改动成缺省档）：

- **多域形态选型声明**：:func:`run_turbo_multi` 为**真多域**（K 个信任
  域并发维护 + 轮转提议 + 塌缩域关闭重启），非"单域内重启循环"——理由：
  ①run_turbo 塌缩重启本就以 incumbent 为中心重开（单域重启循环与既有
  行为无实质差异，AUC 对照门失去被测面）；②TuRBO-5 原义即 m 个并发
  信任域；③任务书预声明"多信任域并发+失败域关闭+成功率驱动加长"。
  "并发"的诚实边界：evaluate_fn 为逐点接口，多域并发指**状态并发**
  （K 套域状态机轮转消费同一评估预算），非并行批量评估（原论文 batch
  并行在逐点接口下不可表达，如实声明）。
- **TuRBO-5 简化与原论文差异（empirical 档如实标注）**：域内提议沿用
  本仓 Thompson 采样（未加 TuRBO-mm 的多臂 scorer/GP-LCB 组合打分器）；
  成功/失败语义用**区域局部 incumbent 改进**（每域对自身最优改进才算
  成功——TuRBO-m 家族各 state 独立计成功的最小形态；与单域 TuRBO-1
  的全局 incumbent 口径在 K=1 时重合，K>1 时防止非全局谷区域被饿死）；
  域塌缩（length≤length_min）即关闭并以新中心重启（"ts"档=全局
  incumbent；"rei"档=qREI 选点）；初始中心 "ts"档=LHS 预热按代价升序
  前 K 点（原论文 TuRBO-5 baseline 为随机放置，本仓取确定性等价面）。
  K=1 + "ts" 时 :func:`run_turbo_multi` 与 :func:`run_turbo` 逐位等价
  （tests/unit/test_turbo5_rei.py 退化钉）。
- **REI 语义核对结论（#122 实读 arXiv:2412.11456 / AAAI 2025 原文）**：
  论文 REI = **Regional** Expected Improvement（区域期望改进，
  Namura & Takemori），**非**任务书口径的"Relative（对当前最优的相对
  改进）"——REI(x) = (1/V_TR)∫_TR EI(x̂)dx̂（论文式(3)，无闭式，Monte
  Carlo 近似；实用变体 qREI 式(4) = GP 后验 Thompson 抽样的
  max(f_ref−TS,0) 区域均值），用途是**选信任域中心**（初始化/重启时
  c=argmax qREI，替换 TuRBO 的随机放置）。本仓落点按论文原义：
  strategy="rei" 域放置档（初始 K 中心贪心 qREI+互斥距离选取——原论文
  TuRBO-5 初始 m 中心为 q=m 联合选取，本仓降为贪心逐个+排除半径的
  最小形态，如实声明；重启 q=1 与论文一致）；f_ref=全局 incumbent。
  依赖面核对：论文 GP 后验只要求 (μ,σ̂)（Thompson 抽样=μ+σ̂·ε），本仓
  gp_det 后验恰为该形态，**无 batch GP 后验依赖**，语义匹配可承论文名
  （差异点仅初始选取联合性）。eipu 通道的 REI 档为**启发式移植**
  （区域平均 EI 作点级采集打分，见 eipu.py docstring——论文未做此用途，
  不冒充论文原义）。
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from rfauto.core.objectives import Objective, SpecEvaluator
from rfauto.optimization.surrogate.gp_det import DetGaussianProcess, fit_mle

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_LENGTH_INIT",
    "DEFAULT_LENGTH_MIN",
    "DEFAULT_N_REGIONS",
    "REGION_STRATEGIES",
    "run_turbo",
    "run_turbo_multi",
]

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


# ═══ T-N10（aurora_n W2）：多域 TuRBO-5 形态 + qREI 域放置 ══════════════════
#
# 本节为 run_turbo 之上的增量（TuRBO-1 路径零改动）。状态机内核
# （_RegionState/_region_branch/_propose_in_region/_fold_region/_qrei_centers）
# 由 :func:`run_turbo_multi` 与 acq_sampler.TurboSampler 的 storage 重放
# **共享同一实现**（T-N4 等价钉口径对新形态自洽的机制基础：重放与正向
# 走同一段状态更新代码，等价钉只需钉 rng 流位对齐与分支次序）。

#: 多域形态缺省并发信任域数（TuRBO-5 原义 m=5）
DEFAULT_N_REGIONS = 5

#: 域放置策略档："ts"=incumbent/LHS 最优点放置（缺省）| "rei"=qREI 选点
REGION_STRATEGIES = ("ts", "rei")

#: qREI Monte Carlo 缺省规模（论文 N_x=128 Sobol×N_f=256 后验抽样；本仓
#: 减量为单元测试预算口径，旋钮全量外露，诚实声明非论文规模）
_REI_N_CENTERS = 64
_REI_N_SAMPLES = 32
_REI_N_DRAWS = 16

#: qREI 初始 K 中心贪心选取的互斥半径（Linf，单元空间；域半边长量级，
#: 防止 K 个初始域中心挤同一谷）
_REI_EXCLUDE_DIST = DEFAULT_LENGTH_INIT

#: qREI 全局 GP 拟合下限（全域观测少于此数时 rei 档显式回退 ts 放置，
#: 与 run_turbo 区域分支的 _MIN_REGION_POINTS 同源口径）
_REI_MIN_GLOBAL_POINTS = _MIN_REGION_POINTS


class _RegionState:
    """单信任域状态机（多域形态的最小并发单元；forward/重放共享）。"""

    __slots__ = ("center", "incumbent_cost", "incumbent_u", "length",
                 "n_fail", "n_restarts", "n_success")

    def __init__(
        self, center: np.ndarray, length: float,
        incumbent_u: np.ndarray, incumbent_cost: float,
    ) -> None:
        self.center = np.array(center, dtype=float)
        self.length = float(length)
        self.incumbent_u = np.array(incumbent_u, dtype=float)
        self.incumbent_cost = float(incumbent_cost)
        self.n_success = 0
        self.n_fail = 0
        self.n_restarts = 0


def _clamp_length(length_init: float, length_min: float) -> float:
    """信任域边长合法化（run_turbo 同款：≥2·length_min 且 ≤1.0）。"""
    return float(min(max(length_init, 2.0 * length_min), 1.0))


def _init_regions_ts(
    init_units: np.ndarray, init_costs: np.ndarray,
    n_regions: int, length: float,
) -> list[_RegionState]:
    """ts 档初始中心：LHS 预热按代价升序前 K 点（超出预热数循环复用）。"""
    order = np.argsort(init_costs, kind="stable")
    regions: list[_RegionState] = []
    for k in range(int(n_regions)):
        idx = int(order[k % len(order)])
        regions.append(_RegionState(
            init_units[idx].copy(), length,
            init_units[idx].copy(), float(init_costs[idx])))
    return regions


def _region_branch(
    region: _RegionState, hist_units: np.ndarray,
    min_region_points: int,
) -> str:
    """提议分支判定（"region"=域内 Thompson | "sparse"=域内均匀）。

    分支只看该提议时点之前的历史（hist_units 不含本次提议点）——
    forward 与重放共享同一判定（等价钉的分支对齐基础）。
    """
    if len(hist_units) == 0:
        return "sparse"
    in_region = np.max(np.abs(hist_units - region.center), axis=1) <= region.length
    return ("region" if int(in_region.sum()) >= int(min_region_points)
            else "sparse")


def _consume_proposal_draws(
    rng: np.random.Generator, branch: str, n_candidates: int, d: int,
) -> None:
    """Thompson 流位对齐消费（重放步专用：同形取数、值弃置）。"""
    if branch == "region":
        rng.random((int(n_candidates), d))
        rng.standard_normal(int(n_candidates))
    else:
        rng.random(d)


def _fit_mle_guarded(x: np.ndarray, y: np.ndarray, *, kind: str = "se"):
    """fit_mle + 近重复数值奇异守卫（T-N10 多域内核专用；run_turbo 零改动）。

    边界裁剪把 Thompson 候选整面映射到同一角点，重复/近重复提案入史后
    K 矩阵最小特征值 ~nugget(1e-6) 落到 amp²(~e8~e10) 的浮点舍入噪声带
    （eps·amp²~1e-7），Cholesky 报 "Matrix is not positive definite"——
    既有 run_turbo 在长预算/平台盖帽面上实测可触发（2026-10-29 面 C
    n_eval=130 复现，属既有潜在缺陷，本席不改动 run_turbo 只在新内核
    加守卫）。重试=确定性加大 nugget（1e-3·max(var,1)）重拟合一次：
    特征值地板抬到 ≫ 舍入带，且只在原实现必崩的轨迹上生效——非退化
    轨迹逐位等价（K=1 退化钉与既有 TurboSampler↔run_turbo 等价钉不受
    影响，严口径保持）。
    """
    try:
        return fit_mle(x, y, kind=kind)
    except np.linalg.LinAlgError:
        nug = max(float(np.var(y)), 1.0) * 1e-3 + 1e-10
        return fit_mle(x, y, kind=kind, init={"nugget": nug})


def _propose_in_region(
    rng: np.random.Generator, region: _RegionState,
    hist_units: np.ndarray, hist_costs: np.ndarray,
    *, n_candidates: int, min_region_points: int,
) -> np.ndarray:
    """域内实时提议（run_turbo 迭代体同款：Thompson/稀疏均匀两分支）。"""
    d = region.center.shape[0]
    branch = _region_branch(region, hist_units, min_region_points)
    if branch == "region":
        in_region = (np.max(np.abs(hist_units - region.center), axis=1)
                     <= region.length)
        reg_x = hist_units[in_region]
        reg_y = hist_costs[in_region]
        params = _fit_mle_guarded(reg_x, reg_y, kind="se")
        gp = DetGaussianProcess(reg_x, reg_y, params, "se")
        cand = np.clip(region.center + region.length * (
            2.0 * rng.random((int(n_candidates), d)) - 1.0), 0.0, 1.0)
        mean, var = gp.predict(cand)
        std = np.sqrt(np.maximum(var, 0.0))
        draws = mean + std * rng.standard_normal(len(cand))
        return cand[int(np.argmin(draws))]
    return np.clip(region.center + region.length * (
        2.0 * rng.random(d) - 1.0), 0.0, 1.0)


def _fold_region(
    region: _RegionState, u: np.ndarray, cost: float | None, *,
    success_tolerance: int, fail_tol: int,
    length_init: float, length_min: float,
) -> bool:
    """一次观测折叠进域状态机（forward/重放共享；返回是否塌缩待重启）。

    成功判据=区域局部 incumbent 改进（K=1 时与 run_turbo 全局口径重合，
    退化钉钉死）；改进同时跟随新中心（run_turbo 同款 center=proposed）。
    """
    improved = cost is not None and cost < region.incumbent_cost
    if improved:
        region.incumbent_cost = float(cost)
        region.incumbent_u = np.array(u, dtype=float).copy()
        region.center = np.array(u, dtype=float).copy()
        region.n_success += 1
        region.n_fail = 0
    else:
        region.n_fail += 1
        region.n_success = 0
    if region.n_success >= int(success_tolerance):
        region.length = min(_GAMMA * region.length, 1.0)
        region.n_success = 0
    elif region.n_fail >= int(fail_tol):
        region.length = _GAMMA_DOWN * region.length
        region.n_fail = 0
        if region.length <= length_min:
            return True
    return False


def _restart_region(
    region: _RegionState, global_best_u: np.ndarray,
    global_best_cost: float, length: float, *,
    strategy: str, rng: np.random.Generator | None = None,
    hist_units: np.ndarray | None = None, hist_costs: np.ndarray | None = None,
    rei_n_centers: int = _REI_N_CENTERS, rei_n_samples: int = _REI_N_SAMPLES,
    rei_n_draws: int = _REI_N_DRAWS,
) -> None:
    """塌缩域关闭重启（"ts"=全局 incumbent | "rei"=qREI 选点 q=1）。

    rei 档全域观测不足 :data:`_REI_MIN_GLOBAL_POINTS` 时显式回退 ts 放置
    （GP 拟合下限，不静默编造模型）。重启域 incumbent：ts 档=全局最优
    （中心点代价已知）；rei 档中心为未评估候选点，incumbent=+inf（首个
    有限代价观测即区域改进，容忍语义如实声明）。
    """
    placed = False
    if strategy == "rei" and rng is not None and hist_units is not None \
            and hist_costs is not None \
            and len(hist_costs) >= _REI_MIN_GLOBAL_POINTS:
        (center,) = _qrei_centers(
            rng, hist_units, hist_costs, k=1, f_ref=float(global_best_cost),
            n_centers=rei_n_centers, n_samples=rei_n_samples,
            n_draws=rei_n_draws)
        region.center = center.copy()
        region.incumbent_u = center.copy()
        region.incumbent_cost = math.inf
        placed = True
    if not placed:
        region.center = np.array(global_best_u, dtype=float).copy()
        region.incumbent_u = np.array(global_best_u, dtype=float).copy()
        region.incumbent_cost = float(global_best_cost)
    region.length = float(length)
    region.n_success = 0
    region.n_fail = 0
    region.n_restarts += 1


def _qrei_centers(
    rng: np.random.Generator, hist_units: np.ndarray, hist_costs: np.ndarray,
    *, k: int, f_ref: float,
    n_centers: int = _REI_N_CENTERS, n_samples: int = _REI_N_SAMPLES,
    n_draws: int = _REI_N_DRAWS,
) -> list[np.ndarray]:
    """qREI 域中心选取（REI 论文式(4) 的 Monte Carlo 直译；forward/重放共享）。

    rng 消耗形状固定三段（重放流位对齐的契约）：
    ①候选中心池 ``n_centers*d`` 均匀 → ②区域样本
    ``n_centers*n_samples*d`` 均匀 → ③Thompson 抽样
    ``n_centers*n_draws*n_samples`` 正态；GP 拟合/预测零 rng（确定性）。

    qREI(c) = mean_{j,k} max(f_ref − TS_k(x̂_j), 0)，x̂_j 为以 c 为中心、
    length_init 为半边长的区域内均匀样本，TS_k = μ+σ̂·ε_k 为 GP 后验
    Thompson 抽样（本仓 gp_det 后验恰为 (μ,σ̂) 形态，无 batch 后验依赖）。

    选取：k=1（重启档，论文 restart q=1）取 argmax；k>1（初始 K 中心）
    贪心按 qREI 降序取互斥（Linf 距离 ≥ _REI_EXCLUDE_DIST）候选，不足
    K 个时按同序去重补齐（原论文 TuRBO-5 初始为 q=m 联合选取，本仓降为
    贪心+互斥的最小形态，模块 docstring 已声明）。
    """
    d = hist_units.shape[1]
    cand = rng.random((int(n_centers), d))
    samples = rng.random((int(n_centers), int(n_samples), d))
    gp_params = _fit_mle_guarded(hist_units, hist_costs, kind="se")
    gp = DetGaussianProcess(hist_units, hist_costs, gp_params, "se")
    mean, var = gp.predict(samples.reshape(-1, d))
    mu = mean.reshape(int(n_centers), int(n_samples))
    std = np.sqrt(np.maximum(var, 0.0)).reshape(int(n_centers), int(n_samples))
    eps = rng.standard_normal((int(n_centers), int(n_draws), int(n_samples)))
    ts = mu[:, None, :] + std[:, None, :] * eps
    q = np.maximum(float(f_ref) - ts, 0.0).mean(axis=(1, 2))
    if int(k) <= 1:
        return [cand[int(np.argmax(q))].copy()]
    order = np.argsort(-q, kind="stable")
    taken: list[np.ndarray] = []
    for idx in order:
        c = cand[idx]
        if all(float(np.max(np.abs(c - t))) >= _REI_EXCLUDE_DIST
               for t in taken):
            taken.append(c.copy())
            if len(taken) == int(k):
                return taken
    for idx in order:  # 互斥候选不足 K：同序去重补齐（确定性兜底）
        c = cand[idx]
        if all(float(np.max(np.abs(c - t))) > 0.0 for t in taken):
            taken.append(c.copy())
            if len(taken) == int(k):
                break
    return taken


def run_turbo_multi(
    bounds: dict[str, tuple[float, float]],
    objectives: list[Objective],
    evaluate_fn: Callable[[dict[str, float]], dict[str, float]],
    *,
    n_init: int = 16,
    n_iter: int = 40,
    seed: int = 42,
    n_regions: int = DEFAULT_N_REGIONS,
    region_strategy: str = "ts",
    length_init: float = DEFAULT_LENGTH_INIT,
    length_min: float = DEFAULT_LENGTH_MIN,
    success_tolerance: int = _SUCCESS_TOLERANCE,
    failure_tolerance: int | None = None,
    n_candidates: int = _N_CANDIDATES,
    rei_n_centers: int = _REI_N_CENTERS,
    rei_n_samples: int = _REI_N_SAMPLES,
    rei_n_draws: int = _REI_N_DRAWS,
) -> dict[str, Any]:
    """多域 TuRBO（TuRBO-5 形态）：K 个信任域轮转提议+塌缩关闭重启。

    预算口径：n_init 个 LHS 全域预热（共用）→ n_iter 次模型迭代按
    ``r = it % n_regions`` 轮转分派给 K 个域（同预算与单域 TuRBO-1
    严格可比——AUC 对照门的公平性基础）。每域独立状态机（中心/边长/
    成功失败计数/局部 incumbent），评估后按 :func:`_fold_region` 折叠；
    塌缩域关闭并按 region_strategy 重启（"ts"=全局 incumbent，"rei"=
    qREI 选点）。

    Returns:
        {ok, algorithm:"turbo_multi", n_regions, region_strategy, best,
        n_real_used, n_attempts, trace, length_trace（逐迭代作用域的
        更新后边长）, regions（终态各域摘要）, failures, note, elapsed_s}。

    Raises/软失败：n_init<2 / n_iter<1 / n_regions<1 / region_strategy
    未知 → {"ok": False, "errors": [...]}（同 run_turbo 软失败面）。
    """
    t0 = time.time()
    errors: list[str] = []
    if n_init < 2 or n_iter < 1:
        errors.append("n_init≥2 且 n_iter≥1 才构成 TuRBO 循环")
    if int(n_regions) < 1:
        errors.append(f"n_regions≥1 才构成多域形态，得到 {n_regions!r}")
    if region_strategy not in REGION_STRATEGIES:
        errors.append(
            f"未知 region_strategy: {region_strategy!r}"
            f"（可选 {' | '.join(REGION_STRATEGIES)}）")
    if errors:
        return {"ok": False, "errors": errors}
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
    failures: list[dict[str, Any]] = []
    phase = ["init", -1, -1]

    def _evaluate(u: np.ndarray) -> float | None:
        params = {n: float(lower[i] + u[i] * span[i])
                  for i, n in enumerate(names)}
        try:
            metrics = evaluate_fn(params)
        except Exception as exc:  # 真机通道失败诚实计数（不中断）
            logger.warning("turbo_multi evaluate_fn 失败: %s", exc)
            failures.append({"phase": phase[0], "index": phase[1],
                             "region": phase[2]})
            return None
        cost = SpecEvaluator.evaluate_objectives(metrics, objectives)
        unit_hist.append(np.array(u, dtype=float))
        cost_hist.append(float(cost))
        return float(cost)

    # ---- LHS 预热（全域共用；run_turbo 同源同 seed 同设计）---- #
    init = lhs_points(bounds, n_init, seed=seed)
    for i_pt, pt in enumerate(init["points"]):
        phase[0], phase[1], phase[2] = "init", i_pt, -1
        _evaluate(np.array([(pt[n] - lower[i]) / span[i]
                            for i, n in enumerate(names)]))
    init_units = np.array(unit_hist) if unit_hist else np.zeros((0, d))
    init_costs = np.array(cost_hist) if cost_hist else np.zeros(0)
    best_i = int(np.argmin(init_costs)) if len(init_costs) else -1
    global_best_cost = float(init_costs[best_i]) if best_i >= 0 else math.inf
    global_best_u = (init_units[best_i].copy() if best_i >= 0
                     else rng.random(d))
    length0 = _clamp_length(length_init, length_min)

    # ---- 域初始化（rei 档全域观测不足时显式回退 ts，不编造模型）---- #
    if region_strategy == "rei" and len(init_costs) >= _REI_MIN_GLOBAL_POINTS:
        centers = _qrei_centers(
            rng, init_units, init_costs, k=int(n_regions),
            f_ref=global_best_cost, n_centers=rei_n_centers,
            n_samples=rei_n_samples, n_draws=rei_n_draws)
        regions = [_RegionState(c, length0, c.copy(), math.inf)
                   for c in centers]
    else:
        regions = _init_regions_ts(init_units, init_costs,
                                   int(n_regions), length0)

    trace: list[dict[str, Any]] = []
    length_trace: list[float] = []
    n_attempts = len(init["points"])  # 预热全部计入 attempts（成功与否）

    for it in range(int(n_iter)):
        r = it % int(n_regions)
        region = regions[r]
        phase[0], phase[1], phase[2] = "iter", it, r
        pts = np.array(unit_hist) if unit_hist else np.zeros((0, d))
        costs = np.array(cost_hist) if cost_hist else np.zeros(0)
        proposed = _propose_in_region(
            rng, region, pts, costs,
            n_candidates=n_candidates, min_region_points=_MIN_REGION_POINTS)
        n_attempts += 1
        cost = _evaluate(proposed)
        improved_global = cost is not None and cost < global_best_cost
        improved_region = cost is not None and cost < region.incumbent_cost
        if improved_global:
            global_best_cost = float(cost)
            global_best_u = proposed.copy()
        collapsed = _fold_region(
            region, proposed, cost, success_tolerance=success_tolerance,
            fail_tol=fail_tol, length_init=length_init,
            length_min=length_min)
        restart = False
        if collapsed:
            restart = True
            # 塌缩重启的历史含本次评估点（_evaluate 已 append）——与
            # acq_sampler 重放侧 units[:n_init+j+1] 同一对齐口径
            _restart_region(
                region, global_best_u, global_best_cost, length0,
                strategy=region_strategy, rng=rng,
                hist_units=np.array(unit_hist),
                hist_costs=np.array(cost_hist),
                rei_n_centers=rei_n_centers,
                rei_n_samples=rei_n_samples, rei_n_draws=rei_n_draws)
        length_trace.append(float(region.length))
        trace.append({
            "iter": it,
            "region": r,
            "cost": (float(cost) if cost is not None else None),
            "best_cost": float(global_best_cost),
            "improved": bool(improved_global),
            "improved_region": bool(improved_region),
            "length": float(region.length),
            "restart": restart,
        })

    best_params = {n: float(lower[i] + global_best_u[i] * span[i])
                   for i, n in enumerate(names)}
    return {
        "ok": bool(cost_hist),
        "algorithm": "turbo_multi",
        "n_regions": int(n_regions),
        "region_strategy": region_strategy,
        "best": {"params": best_params, "cost": float(global_best_cost)},
        "n_real_used": len(unit_hist),
        "n_attempts": n_attempts,
        "trace": trace,
        "length_trace": length_trace,
        "regions": [
            {"index": i,
             "center": {n: float(lower[j] + rg.center[j] * span[j])
                        for j, n in enumerate(names)},
             "length": float(rg.length),
             "incumbent_cost": (float(rg.incumbent_cost)
                                if math.isfinite(rg.incumbent_cost)
                                else None),
             "n_restarts": int(rg.n_restarts)}
            for i, rg in enumerate(regions)],
        "failures": failures,
        "note": ("TuRBO-5 简化档：真多域轮转（状态并发，评估逐点）+"
                 "区域局部 incumbent 成功判据+塌缩关闭重启；rei 档=qREI "
                 "域放置（Regional EI，AAAI 2025，非 Relative）"),
        "elapsed_s": round(time.time() - t0, 3),
    }
