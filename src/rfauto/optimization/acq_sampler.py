"""T-N4（aurora_n W1-D）：自研采集包成 ``optuna.samplers.BaseSampler`` 挂 study。

把 eipu.py（EI/c cost-aware，:func:`rfauto.optimization.eipu.suggest_next_point`
内核）与 turbo.py（TuRBO-1，:func:`rfauto.optimization.turbo.run_turbo` 循环）
的自研采集接进 Optuna study 通道——与持久化/resume/warm-start 生态并轨
（eipu.py docstring :10-13 明文预留的"后续优化器接线批"，本模块即其落地）。

**Optuna 5.0.0 BaseSampler API（2026-10-29 venv 源码实读，非臆写）**：
``.venv/Lib/site-packages/optuna/samplers/_base.py``——三个抽象方法
``infer_relative_search_space(study, trial)`` / ``sample_relative(study,
trial, search_space)`` / ``sample_independent(study, trial, param_name,
param_distribution)``；可选钩子 ``before_trial``（trial 实例化时、
infer 之前调用）/ ``after_trial`` / ``reseed_rng``；多目标守护
``_raise_error_if_multi_objective(study)``。调用时序（study.py ask /
trial/_trial.py 实读）：ask() 先建 RUNNING trial → ``before_trial`` →
首个 ``suggest_float`` 时惰性调 ``infer_relative_search_space`` +
``sample_relative``（相对参数命中则直接采用、逐参写 storage）；未命中
的参数走 ``sample_independent``；tell 时调 ``after_trial``。

**设计（storage 派生无状态重放）**：两个采样器都不维护跨 trial 的内存
状态机——每次 ``sample_relative`` 从 study storage 读 COMPLETE trials
重建采集决策的全部输入（eipu：X/y/cost 纯函数内核直调；turbo：信任域
状态机对观测历史逐点重放折叠 + Thompson rng 按同形取数对齐回放）。收益：
- resume 语义免费（JournalStorage 落盘重启后新实例从 storage 重建同
  轨迹——确定性钉见 tests/unit/test_acq_sampler.py）；
- 进程内对象与 storage 永不分叉（CMA-ES pickle 系统属性那类状态同步
  问题在本设计下不存在）。
代价：turbo 每次提议重放全历史（合成基准 <60 点，毫秒级，真机通道
评估本身秒-分钟级，重放开销可忽略）。

**等价口径（预声明：严口径）**：接线版与独立循环版同 seed 同建议序列
逐位一致——依据：eipu 的 ``suggest_next_point`` 是纯函数（候选池/GP
random_state 每次 fresh 自同一种子）、turbo 的提议链对无失败历史是
确定性折叠；启动段（eipu 均匀 DOE / turbo LHS）按独立循环同款取数
序列复刻。允许降级为"最优值收敛带一致"的宽口径仅在浮点重放漂移实测
出现时启用并如实登记（当前实现严口径成立）。

**诚实边界（#122）**：
- FAIL/PRUNED trials 不进模型（Optuna 内建采样器同约定：failed trials
  are regarded as deleted）——run_turbo 对 evaluate_fn 异常的"计失败
  折叠信任域"语义在接线版不成立（失败 trial 无值，重放只见 COMPLETE
  序列）；等价钉用不失败目标。eipu 的 cost 通道走 trial user_attr
  （optimizer.build_objective 本就写 ``cost`` attr）。
- eipu 观测空间饱和（``saturated=True``）→ RuntimeError 显性终止该
  ask（接线版没有独立循环的"提前停环"面，继续 ask 只会重复观测）。
- 并发 ask 竞态显式拒绝（``before_trial`` 门：存在**带参数的**其他
  RUNNING trial 即 raise——无参数 husk（如被拒 ask 留下的空 trial）
  不阻塞，自愈不锁死）。因此 batch_size>1 / n_jobs>1 均不适用
  （optimizer.py 层同 cmaes 先例显式拒绝）。
- 参数盒契约：构造 ``bounds`` 须与 objective 的 suggest 分布同名同界
  同 log 档（optimizer.py 同源 param_ranges 保证；偏离时 log 档由
  optuna 兼容性检查显式报错，界漂移由重放侧显式校验报错）。
- turbo 启动段 LHS 与 run_turbo 同源（sample_design.lhs_points 同
  seed 同设计）；Thompson 回放按"区域分支=``n_candidates*d`` 均匀 +
  ``n_candidates`` 正态、稀疏分支=``d`` 均匀"同形取数对齐流位。

**T-N10（aurora_n W2）多域形态扩展**：TurboSampler 增 ``n_regions``
（并发信任域数，缺省 1=TuRBO-1 既有路径零改动）与 ``region_strategy``
（"ts"|"rei"，qREI=Regional EI 论文原义域放置档）两旋钮；多域重放与
run_turbo_multi **共享同一状态机内核**（turbo.py 私有面导入，forward/
重放同源），rei 域放置的重放侧同参复算（产出后续状态所需域中心），
rng 消耗形状三段固定（候选池/区域样本/Thompson 抽样）对齐流位。
新形态等价钉（TurboSampler(n_regions>1[, region_strategy="rei"]) ≡
run_turbo_multi 同参提议序列逐位）在 tests/unit/test_turbo5_rei.py；
缺省形态既有等价钉（本文件）不变仍绿。EipuSampler 经 strategy 透传
消费 eipu.py 的 "rei" 档（区域平均 EI，REI-inspired 移植——差异声明
见 eipu.py 模块 docstring；cost-blind，无 cost_attr 要求）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import numpy as np
import optuna
from optuna._warnings import optuna_warn
from optuna.distributions import FloatDistribution
from optuna.samplers import BaseSampler
from optuna.trial import TrialState

from rfauto.optimization import turbo as turbo_mod
from rfauto.optimization.eipu import EIPUConfig, suggest_next_point

# T-N10（aurora_n W2）：多域信任域状态机内核与 run_turbo_multi 共享
# （forward/重放同源是等价钉口径对新形态自洽的机制基础；私有面由
# tests/unit/test_turbo5_rei.py 的循环版↔接线版逐位等价钉守护）
from rfauto.optimization.turbo import (
    _REI_MIN_GLOBAL_POINTS,
    _clamp_length,
    _consume_proposal_draws,
    _fold_region,
    _init_regions_ts,
    _propose_in_region,
    _qrei_centers,
    _region_branch,
    _RegionState,
    _restart_region,
)

__all__ = ["EipuSampler", "TurboSampler"]

#: eipu GP 内核的最小已观测点数（suggest_next_point 拟合下限）
_EIPU_MIN_OBSERVED = 2


def _validate_bounds(
    bounds: Mapping[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """参数盒校验（非空/finite/lo<hi；显式报错不静默）。"""
    if not bounds:
        raise ValueError("bounds 不得为空（至少一个参数）")
    out: dict[str, tuple[float, float]] = {}
    for name, pair in bounds.items():
        lo, hi = float(pair[0]), float(pair[1])
        if not (math.isfinite(lo) and math.isfinite(hi) and hi > lo):
            raise ValueError(
                f"边界须 finite 且 lo<hi：{name!r}=({pair[0]!r}, {pair[1]!r})")
        out[str(name)] = (lo, hi)
    return out


class _BoxAcqSampler(BaseSampler):
    """盒约束自研采集采样器公共骨架（storage 派生无状态重放）。

    子类只实现 :meth:`_propose`（启动段之后的模型提议）；启动段与
    相对空间/独立回退/并发门由本骨架统一承载。
    """

    def __init__(
        self,
        bounds: Mapping[str, tuple[float, float]],
        *,
        seed: int,
        n_startup: int,
        warn_independent_sampling: bool = True,
    ) -> None:
        self._bounds = _validate_bounds(bounds)
        self._names = sorted(self._bounds)
        self._seed = int(seed)
        self._n_startup = int(n_startup)
        if self._n_startup < 2:
            raise ValueError(
                f"n_startup 必须 ≥2（GP 内核拟合下限），得到 {n_startup}")
        self._warn_independent = bool(warn_independent_sampling)
        self._independent = optuna.samplers.RandomSampler(seed=self._seed)

    # ─── 子类钩子 ────────────────────────────────────────────────────────

    def _propose(
        self, study: optuna.Study,
        observed: list[tuple[dict[str, float], float]],
    ) -> dict[str, float]:
        """启动段完成后的模型提议（observed=按 trial 号序的 (params, value)）。"""
        raise NotImplementedError

    # ─── 观测重建（COMPLETE trials → 有序 (params, value) 序列） ─────────

    def _observed(
        self, study: optuna.Study,
    ) -> list[tuple[dict[str, float], float]]:
        trials = study.get_trials(deepcopy=False, states=(TrialState.COMPLETE,))
        ordered = sorted(trials, key=lambda t: t.number)
        observed: list[tuple[dict[str, float], float]] = []
        for t in ordered:
            missing = [n for n in self._names if n not in t.params]
            if missing:
                raise ValueError(
                    f"trial #{t.number} 缺参数盒内参数 {missing}——本采样器"
                    "要求 objective 对 bounds 全参数 suggest_float（参数盒契约）")
            if t.value is None:
                raise ValueError(f"trial #{t.number} 无 value（状态不一致）")
            observed.append(
                ({n: float(t.params[n]) for n in self._names}, float(t.value)))
            # 参数盒契约校验：观测分布与构造 bounds 同界（界漂移显式报错；
            # log 档错配由 optuna check_distribution_compatibility 显式报错）
            for n in self._names:
                dist = t.distributions.get(n)
                if isinstance(dist, FloatDistribution):
                    lo, hi = self._bounds[n]
                    if dist.low != lo or dist.high != hi:
                        raise ValueError(
                            f"trial #{t.number} 参数 {n!r} 分布界 "
                            f"({dist.low}, {dist.high}) 与采样器 bounds "
                            f"({lo}, {hi}) 不一致（参数盒契约）")
        return observed

    # ─── BaseSampler 契约 ────────────────────────────────────────────────

    def infer_relative_search_space(
        self, study: optuna.Study, trial: optuna.trial.FrozenTrial,
    ) -> dict[str, FloatDistribution]:
        self._raise_error_if_multi_objective(study)
        return {
            n: FloatDistribution(low=lo, high=hi)
            for n, (lo, hi) in sorted(self._bounds.items())
        }

    def sample_relative(
        self, study: optuna.Study, trial: optuna.trial.FrozenTrial,
        search_space: dict[str, FloatDistribution],
    ) -> dict[str, Any]:
        self._raise_error_if_multi_objective(study)
        if not search_space:
            return {}
        observed = self._observed(study)
        if len(observed) < self._n_startup:
            return self._startup_point(len(observed))
        return self._propose(study, observed)

    def sample_independent(
        self, study: optuna.Study, trial: optuna.trial.FrozenTrial,
        param_name: str, param_distribution: optuna.distributions.BaseDistribution,
    ) -> Any:
        if self._warn_independent:
            # CMA-ES 同款一次性告警（相对空间外参数回退均匀随机）
            optuna_warn(
                f"`{self.__class__.__name__}` 仅建模参数盒 "
                f"{self._names}；参数 {param_name!r} 回退独立均匀采样"
                "（本告警只出现一次）。")
            self._warn_independent = False
        return self._independent.sample_independent(
            study, trial, param_name, param_distribution)

    def before_trial(
        self, study: optuna.Study, trial: optuna.trial.FrozenTrial,
    ) -> None:
        # 并发 ask 竞态门：存在带参数的其他 RUNNING trial = 上一个 ask 的
        # 采集决策已固定而未 tell——此时新 ask 会基于同一观测状态提出
        # 同一建议（候选池/GP 全确定性），零信息且破坏序列语义 → 显式
        # 拒绝。无参数 RUNNING（如被拒 ask 留下的空 trial）不阻塞（自愈）。
        running = study.get_trials(deepcopy=False, states=(TrialState.RUNNING,))
        for t in running:
            if t._trial_id == trial._trial_id:
                continue
            if t.params:
                raise ValueError(
                    f"并发 ask 竞态拒绝：trial #{t.number}（{sorted(t.params)}）"
                    "仍处 RUNNING 且已带参数——eipu/turbo 采集决策对观测历史"
                    "确定性，未 tell 前再 ask 会重复同一建议。请先 study.tell"
                    " 未决 trial（或改用单 ask 串行流程；本采样器不支持 "
                    "batch_size>1 / n_jobs>1）。")

    def reseed_rng(self) -> None:
        # 盒内核提议是 storage 派生（无进程内 rng 状态），只回退面需要重播种
        self._independent.reseed_rng()


class EipuSampler(_BoxAcqSampler):
    """eipu.py EI/c 采集的 BaseSampler 接线（strategy="eipu"|"ei"|
    "eipu_cooled"|"rei"；T-N10 起 "rei"=区域平均 EI 档透传，cost-blind
    无 cost_attr 要求——语义与论文差异声明见 eipu.py 模块 docstring）。

    Args:
        bounds: 参数盒 {名: (lo, hi)}——须与 objective suggest 分布同源
            （optimizer.py 传 param_ranges 同款）。
        config: :class:`rfauto.optimization.eipu.EIPUConfig`（None=缺省）。
            seed 缺省取 config.seed；显式 ``seed`` 时以 replace 注入覆盖
            （单一真相源：同 seed 同轨迹）。
        strategy: 透传 :func:`suggest_next_point`（缺省 "eipu"）。
        seed: 覆盖 config.seed（None=不覆盖）。
        n_startup: 启动段点数（缺省 2=内核拟合下限）。启动段复刻
            ``run_eipu_loop`` 的 init DOE 取数序列（default_rng(seed)
            逐行 d 个 uniform，行序=names 序）——n_startup 与独立循环
            ``n_init`` 取同值即同起点。
        cost_attr: 逐点代价的 trial user_attr 键（缺省 "cost"，与
            optimizer.build_objective 写面同名）；strategy="eipu"/
            "eipu_cooled" 要求每个 COMPLETE trial 均携带（缺失显式
            ValueError，不静默降级）。"ei" 忽略代价。
        total_iterations: 仅 strategy="eipu_cooled" 消费——OP-3 冷却进度
            分母（镜像 run_eipu_loop 的 ``progress=(i+1)/n_iters``，
            i=本次 ask 前的模型迭代数）。None 时用 config.cooling_progress
            原样（调用方自管）。

    等价钉（严口径）：同 config 同 n_startup=独立循环 n_init 时，
    ``study.ask→suggest→tell`` 序列与 ``run_eipu_loop`` 的 trials.params
    逐位一致（tests/unit/test_acq_sampler.py）。
    """

    def __init__(
        self,
        bounds: Mapping[str, tuple[float, float]],
        *,
        config: EIPUConfig | None = None,
        strategy: str = "eipu",
        seed: int | None = None,
        n_startup: int = _EIPU_MIN_OBSERVED,
        cost_attr: str = "cost",
        total_iterations: int | None = None,
        warn_independent_sampling: bool = True,
    ) -> None:
        cfg = config or EIPUConfig()
        if seed is not None and int(seed) != int(cfg.seed):
            cfg = replace(cfg, seed=int(seed))
        eff_seed = int(cfg.seed)
        super().__init__(
            bounds, seed=eff_seed, n_startup=n_startup,
            warn_independent_sampling=warn_independent_sampling)
        self._config = cfg
        self._strategy = str(strategy)
        self._cost_attr = str(cost_attr)
        self._total_iterations = (
            int(total_iterations) if total_iterations is not None else None)

    def _startup_point(self, index: int) -> dict[str, float]:
        """复刻 run_eipu_loop 的 init DOE（default_rng(config.seed) 逐行取数）。"""
        rng = np.random.default_rng(self._config.seed)
        row: list[float] | None = None
        for _ in range(index + 1):
            row = [float(rng.uniform(float(self._bounds[k][0]),
                                     float(self._bounds[k][1])))
                   for k in self._names]
        assert row is not None  # index ≥ 0 时循环至少执行一次
        return dict(zip(self._names, row, strict=True))

    def _propose(
        self, study: optuna.Study,
        observed: list[tuple[dict[str, float], float]],
    ) -> dict[str, float]:
        cfg = self._config
        if self._strategy == "eipu_cooled" and self._total_iterations is not None:
            # 镜像 run_eipu_loop：模型迭代 i（0 基）的 progress=(i+1)/n_iters，
            # i = 本次 ask 前已观测的模型点数 = len(observed) - n_startup
            i = len(observed) - self._n_startup
            cfg = replace(
                cfg,
                cooling_progress=(i + 1) / float(self._total_iterations))
        xs = np.array([[p[n] for n in self._names] for p, _ in observed])
        ys = np.array([v for _, v in observed], dtype=float)
        cost: np.ndarray | None = None
        if self._strategy in ("eipu", "eipu_cooled"):
            # cost 通道：COMPLETE trials 的 user_attr（与 _observed 同序，
            # get_trials 按 trial 号序返回）
            trials = sorted(
                study.get_trials(deepcopy=False, states=(TrialState.COMPLETE,)),
                key=lambda t: t.number)
            missing = [
                t.number for t in trials if self._cost_attr not in t.user_attrs]
            if missing:
                raise ValueError(
                    f'strategy="{self._strategy}" 需要 cost 观测：trial '
                    f"#{missing[:3]}{'...' if len(missing) > 3 else ''} 缺 "
                    f"user_attr[{self._cost_attr!r}]（请在 tell 前 "
                    f"trial.set_user_attr({self._cost_attr!r}, c)，或与 "
                    "optimizer.build_objective 的写面对齐）")
            cost = np.array(
                [float(t.user_attrs[self._cost_attr]) for t in trials],
                dtype=float)
        params, diag = suggest_next_point(
            xs, ys, cost, self._bounds,
            strategy=self._strategy, config=cfg)
        if params is None:
            # 观测空间饱和（候选池全被去重）——接线版无"提前停环"面，
            # 继续建议只会重复观测：显性终止该 ask（诊断透出在异常文本）。
            raise RuntimeError(
                "EipuSampler 观测空间饱和（suggest_next_point 返回 "
                f"saturated=True，y_best={diag['y_best']!r}，"
                f"n_deduped={diag['n_deduped']!r}）——继续 ask 只会重复观测，"
                "请终止本 study 或扩大参数盒。")
        return params


class TurboSampler(_BoxAcqSampler):
    """turbo.py 信任域采集的 BaseSampler 接线（状态机对观测历史重放）。

    T-N10（aurora_n W2）扩为多域形态：``n_regions``=并发信任域数
    （缺省 1=TuRBO-1 既有路径，重放语义与 W1-D 逐位一致），
    ``region_strategy``="ts"|"rei"（"rei"=qREI 域放置档，REI 论文原义
    ——Regional EI 选中心，非 Relative；语义核对见 turbo.py 模块
    docstring）。多域重放与 :func:`run_turbo_multi` **共享同一状态机
    内核**（turbo.py 的 _RegionState/_region_branch/_fold_region/
    _restart_region/_qrei_centers——forward/重放同源，等价钉只需钉
    rng 流位对齐与分支次序）。

    Args:
        bounds: 参数盒（同 run_turbo/run_turbo_multi 的 bounds 口径）。
        seed: 全链种子（LHS 启动 + Thompson 候选/采样 + qREI 域放置，
            同循环版）。
        n_init: 启动段 LHS 点数（同 run_turbo n_init，≥2）。
        n_regions: 并发信任域数（≥1；缺省 1=TuRBO-1 既有路径）。
        region_strategy: 域放置策略 "ts"（缺省，incumbent/LHS 最优点
            放置）| "rei"（qREI 选点；全域观测 <4 时显式回退 ts，与
            run_turbo_multi 同守卫）。
        length_init/length_min/success_tolerance/failure_tolerance/
        n_candidates: 同 :func:`run_turbo` 同名参数缺省（信任域语义一致）。
        rei_n_centers/rei_n_samples/rei_n_draws: qREI Monte Carlo 规模
            （同 run_turbo_multi 同名参数；rng 消耗形状三段固定，重放
            流位对齐契约见 turbo._qrei_centers docstring）。

    重放语义（等价钉的机制基础）：每次提议对 COMPLETE 观测序列折叠出
    当前各域状态（K 套 center/length/成功失败计数/局部 incumbent +
    全局 incumbent），并按 run_turbo_multi 的取数形态对 rng 做"同形取
    数对齐"（区域分支每步消耗 ``n_candidates*d`` 均匀 +
    ``n_candidates`` 正态、稀疏分支 ``d`` 均匀、rei 域放置三段固定
    形状——只推进流位；qREI 放置因产出后续状态所需的域中心，重放侧
    同参复算而非弃值）。轮转位=模型点序号模 K（与循环版
    ``r = it % n_regions`` 同一确定性分派）。同 seed 同无失败历史下与
    ``run_turbo_multi`` 提议序列逐位一致（严口径预声明，
    tests/unit/test_turbo5_rei.py 实钉；n_regions=1 缺省形态的既有
    等价钉 tests/unit/test_acq_sampler.py 不变仍绿）。

    诚实边界：run_turbo/run_turbo_multi 对 evaluate_fn 异常按失败计数
    折叠信任域；接线版 FAIL/PRUNED trial 无值、不进重放（内建采样器
    同约定）——失败语义不等价（等价钉用不失败目标）。
    """

    _MIN_REGION_POINTS = 4

    def __init__(
        self,
        bounds: Mapping[str, tuple[float, float]],
        *,
        seed: int = 42,
        n_init: int = 16,
        n_regions: int = 1,
        region_strategy: str = "ts",
        length_init: float = 0.4,
        length_min: float = 0.5 ** 7,
        success_tolerance: int = 3,
        failure_tolerance: int | None = None,
        n_candidates: int = 128,
        rei_n_centers: int = 64,
        rei_n_samples: int = 32,
        rei_n_draws: int = 16,
        warn_independent_sampling: bool = True,
    ) -> None:
        if int(n_init) < 2:
            raise ValueError(
                f"n_init≥2 才构成 TuRBO 启动段（run_turbo 同款校验），得到 {n_init}")
        if int(n_regions) < 1:
            raise ValueError(
                f"n_regions≥1 才构成多域形态，得到 {n_regions!r}")
        if region_strategy not in turbo_mod.REGION_STRATEGIES:
            raise ValueError(
                f"未知 region_strategy: {region_strategy!r}（可选 "
                f"{' | '.join(turbo_mod.REGION_STRATEGIES)}）")
        super().__init__(
            bounds, seed=int(seed), n_startup=int(n_init),
            warn_independent_sampling=warn_independent_sampling)
        self._n_init = int(n_init)
        self._n_regions = int(n_regions)
        self._region_strategy = str(region_strategy)
        self._length_init = float(length_init)
        self._length_min = float(length_min)
        self._success_tolerance = int(success_tolerance)
        self._fail_tol = int(
            failure_tolerance if failure_tolerance is not None
            else max(4, len(self._names)))
        self._n_candidates = int(n_candidates)
        self._rei_n_centers = int(rei_n_centers)
        self._rei_n_samples = int(rei_n_samples)
        self._rei_n_draws = int(rei_n_draws)

    # ─── 内部工具 ────────────────────────────────────────────────────────

    def _to_unit(self, params: Mapping[str, float]) -> np.ndarray:
        return np.array([
            (float(params[n]) - self._bounds[n][0])
            / max(self._bounds[n][1] - self._bounds[n][0], 1e-12)
            for n in self._names])

    def _from_unit(self, u: np.ndarray) -> dict[str, float]:
        return {
            n: float(self._bounds[n][0] + u[i] * (
                self._bounds[n][1] - self._bounds[n][0]))
            for i, n in enumerate(self._names)}

    def _startup_point(self, index: int) -> dict[str, float]:
        """LHS 启动段（sample_design.lhs_points 同源同 seed=run_turbo 启动）。"""
        from rfauto.optimization.sample_design import lhs_points

        pts = lhs_points(self._bounds, self._n_init, seed=self._seed)["points"]
        return {n: float(v) for n, v in pts[index].items()}

    # ─── 模型提议（重放折叠 + Thompson；多域状态机内核与循环版共享） ──────

    def _propose(
        self, study: optuna.Study,
        observed: list[tuple[dict[str, float], float]],
    ) -> dict[str, float]:
        d = len(self._names)
        units = [self._to_unit(p) for p, _ in observed]
        costs = [float(v) for _, v in observed]

        # ---- 启动段状态（run_turbo_multi LHS 预热后同款） ----
        init_units = np.array(units[: self._n_init])
        init_costs = np.array(costs[: self._n_init])
        best_i = int(np.argmin(init_costs))
        global_best_cost = float(init_costs[best_i])
        global_best_u = init_units[best_i].copy()
        length0 = _clamp_length(self._length_init, self._length_min)

        rng = np.random.default_rng(self._seed)
        if (self._region_strategy == "rei"
                and len(init_costs) >= _REI_MIN_GLOBAL_POINTS):
            regions = [
                _RegionState(c, length0, c.copy(), math.inf)
                for c in _qrei_centers(
                    rng, init_units, init_costs, k=self._n_regions,
                    f_ref=global_best_cost, n_centers=self._rei_n_centers,
                    n_samples=self._rei_n_samples,
                    n_draws=self._rei_n_draws)]
        else:
            regions = _init_regions_ts(init_units, init_costs,
                                       self._n_regions, length0)

        # ---- 逐模型点重放折叠（run_turbo_multi 主循环同款状态更新） ----
        for j, (u_k, c_k) in enumerate(zip(
                units[self._n_init:], costs[self._n_init:], strict=True)):
            r = j % self._n_regions
            region = regions[r]
            # 分支判定只看该提议时点之前的历史（init + 前 j 个模型点）——
            # run_turbo_multi 的 pts 在迭代体顶部恰含这些点
            pts = np.array(units[: self._n_init + j])
            branch = _region_branch(region, pts, self._MIN_REGION_POINTS)
            _consume_proposal_draws(rng, branch, self._n_candidates, d)
            if c_k < global_best_cost:
                global_best_cost = float(c_k)
                global_best_u = u_k.copy()
            collapsed = _fold_region(
                region, u_k, c_k,
                success_tolerance=self._success_tolerance,
                fail_tol=self._fail_tol,
                length_init=self._length_init,
                length_min=self._length_min)
            if collapsed:
                # 塌缩重启（forward 在评估后折叠——重放历史含本次观测点）
                _restart_region(
                    region, global_best_u, global_best_cost, length0,
                    strategy=self._region_strategy, rng=rng,
                    hist_units=np.array(units[: self._n_init + j + 1]),
                    hist_costs=np.array(costs[: self._n_init + j + 1]),
                    rei_n_centers=self._rei_n_centers,
                    rei_n_samples=self._rei_n_samples,
                    rei_n_draws=self._rei_n_draws)

        # ---- 当前提议（轮转位=模型点数模 K；run_turbo_multi 迭代体同款） ----
        r = len(units[self._n_init:]) % self._n_regions
        region = regions[r]
        proposed = _propose_in_region(
            rng, region, np.array(units), np.array(costs),
            n_candidates=self._n_candidates,
            min_region_points=self._MIN_REGION_POINTS)
        return self._from_unit(np.clip(proposed, 0.0, 1.0))
