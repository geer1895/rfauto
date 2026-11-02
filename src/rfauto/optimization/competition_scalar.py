"""T-N5（aurora_n W1-D）：单目标优化器族竞赛架（OP-5 标量推广，元裁判面 #207）。

OP-5（competition.py 多目标 HV 竞赛）推广到标量目标：TPE / GP / CMAES /
TuRBO / TuRBO-multi / EIpu / SBO 七引擎同预算同 seed 组竞赛，判据=
**最优值 AUC**（best-so-far 归一化曲线下面积，越小越好）+ **达标评估
次数**（best 首次 ≤ target 的评估序号；未达标记 None）。

**两阶段口径（预声明）**：两阶段=同一条 n_eval 评估轨迹上的两个截点
——阶段一=预算半程（horizon=max(1, n_eval//2)），阶段二=预算终点
（horizon=n_eval）；两阶段共享同一条轨迹（不重跑），各截点独立记分
与排名。"两阶段同预算"即：两阶段消费同一预算轨迹，排名分别回答
"谁收敛快"（阶段一）与"谁终值好"（阶段二）。报表两套排名并排出。

**归一化带（引擎无关，组内公平）**：每个问题以确定性探针（LHS 8 点
seed=0，judge 侧统一评估）定 band=[band_lo, band_hi]，band_lo=
known_optimum（问题书声明，None→探针最小值）、band_hi=探针最大值；
AUC 曲线=(best_so_far−band_lo)/(band_hi−band_lo) 截负。band 对全部
引擎同值——组内（problem×seed）AUC 排名不受归一化选择影响；跨问题
聚合用平均秩（Friedman 式，确定性平局按引擎名升序）。

**引擎接入（公开 API 铁律，#118 裁判与被测非共享代码路径）**：全部
走各自公开入口产出"评估序目标值轨迹"，judge 只消费轨迹做记分：
- tpe/gp/cmaes：optuna 5.0 内建采样器（TPESampler/GPSampler/
  CmaEsSampler，seed 透传）+ ask/tell 逐点消费预算；
- turbo：T-N4 TurboSampler（acq_sampler.py）+ ask/tell（LHS 启动段
  计入预算，n_init=max(2, min(16, n_eval//4))）；
- turbo_multi：T-N10 多域 TuRBO-5 接线（aurora_p E1 补榜接入）——
  TurboSampler(n_regions=DEFAULT_N_REGIONS=5, region_strategy="ts"
  既有缺省档) + ask/tell（n_init 同 turbo 引擎公式）。接线与循环版
  run_turbo_multi 共享同一状态机内核且同参提议序列逐位等价
  （tests/unit/test_turbo5_rei.py 等价钉），预算精确消费 n_eval、
  轨迹=原始值域（无平移通道）——零新旋钮，turbo.py 零改动；
- eipu：T-N4 EipuSampler（acq_sampler.py）strategy="ei" + ask/tell
  （评估次数预算口径下 EI/c 的 cost 条件化无代价结构可依——1/ĉ 项
  失义，故走 eipu 内核的 cost-blind EI 档；cost-aware 竞赛留扩展位）；
- sbo：surrogate_loop.run_surrogate_loop（n_init=max(2, min(10,
  n_eval//4))，max_real=n_eval）——其 cost 通道走
  Objective(MAX_BELOW f 0) 违约量（≥0），目标经确定性平移
  offset=1−known_optimum 进通道（平移保序；平移要求问题书声明
  known_optimum 作全局下界，运行后核验 min 原始值 ≥ known_optimum
  否则显式报错不静默；un-shift 有 ≤1 ulp 浮点回差，量级 1e-16 相对
  值、对 AUC 排名无影响，如实声明）。sbo 轨迹取 real_cost_trace，
  提前停环（tol_rounds 收敛）按惯例以终值补齐到预算 horizon（
  best-so-far 停留常数——早停不吃 AUC 便宜）。

**负例（#195 语义）**：退化常数目标拒绝开跑——judge 侧探针若
max−min≤0 或含非有限值，显式 ValueError（常数目标上"优化"无意义，
#195 常数陷阱语义）；known_optimum ≥ 探针最差值同样显式拒绝
（band 退化）。

**确定性**：引擎全链 seed 透传、探针 seed 固定 0、记分纯函数——
同 seed 组重跑报表逐位一致（tests/unit/test_competition_scalar.py
JSON 逐字节钉）。

铁律 7 对照：本模块只编排与记分（AUC/秩/达标计数），数值全部来自
注入的目标函数与各引擎公开入口；合成问题族见
runs/aurora_n/wave1_d/ 报表与 tests/unit/test_competition_scalar.py。
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "SCALAR_ENGINE_REGISTRY",
    "ScalarProblem",
    "format_report_markdown",
    "list_scalar_engines",
    "register_scalar_engine",
    "run_competition_scalar",
]

#: 确定性探针点数（band 与常数目标负例共用；seed 固定 0）
_PROBE_POINTS = 8
_PROBE_SEED = 0


@dataclass(frozen=True)
class ScalarProblem:
    """标量竞赛问题书（纯数据；目标函数由调用方注入，最小化口径）。"""

    #: 问题名（报表展示）
    name: str
    #: 参数盒 {参数名: (lo, hi)}（列序=sorted 名序，与引擎 ask/tell 同源）
    bounds: dict[str, tuple[float, float]]
    #: 目标函数：params dict → float（最小化；须确定性——同参数同值）
    objective_fn: Callable[[dict[str, float]], float]
    #: 达标阈值（best ≤ target 记达标；None=不记达标评估次数）
    target: float | None = None
    #: 全局下界声明（sbo 引擎平移通道必需；band_lo 优先用它）
    known_optimum: float | None = None
    #: 引擎扩展数据（预留）
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.bounds:
            raise ValueError("bounds 不得为空")
        for name, pair in self.bounds.items():
            lo, hi = float(pair[0]), float(pair[1])
            if not (math.isfinite(lo) and math.isfinite(hi) and hi > lo):
                raise ValueError(
                    f"边界须 finite 且 lo<hi：{name!r}=({pair[0]!r}, {pair[1]!r})")
        if self.target is not None and not math.isfinite(float(self.target)):
            raise ValueError(f"target 须有限: {self.target!r}")
        if self.known_optimum is not None and not math.isfinite(
                float(self.known_optimum)):
            raise ValueError(f"known_optimum 须有限: {self.known_optimum!r}")


#: 引擎 runner 契约：(problem, n_eval, seed) → 评估序目标值轨迹（raw 值域）
ScalarEngineFn = Callable[[ScalarProblem, int, int], list[float]]

SCALAR_ENGINE_REGISTRY: dict[str, ScalarEngineFn] = {}


def register_scalar_engine(
        name: str) -> Callable[[ScalarEngineFn], ScalarEngineFn]:
    """引擎注册装饰器（名字重复/空显式报错，不静默覆盖）。"""
    key = str(name).strip()
    if not key:
        raise ValueError("引擎名不得为空")

    def _wrap(fn: ScalarEngineFn) -> ScalarEngineFn:
        if key in SCALAR_ENGINE_REGISTRY and SCALAR_ENGINE_REGISTRY[key] is not fn:
            raise ValueError(f"引擎名重复注册: {key!r}")
        SCALAR_ENGINE_REGISTRY[key] = fn
        return fn

    return _wrap


def list_scalar_engines() -> list[str]:
    """已注册引擎名（注册序，确定性）。"""
    return list(SCALAR_ENGINE_REGISTRY)


# ─── 引擎公共路径 ─────────────────────────────────────────────────────────────

def _ask_tell_values(
    problem: ScalarProblem, n_eval: int, seed: int, sampler: Any,
) -> list[float]:
    """ask/tell 引擎公共路径（optuna 采样器逐点消费预算，精确 n_eval）。"""
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(sampler=sampler, direction="minimize")
    values: list[float] = []
    for _ in range(max(int(n_eval), 0)):
        trial = study.ask()
        params = {
            n: trial.suggest_float(n, float(problem.bounds[n][0]),
                                   float(problem.bounds[n][1]))
            for n in sorted(problem.bounds)
        }
        v = float(problem.objective_fn(params))
        study.tell(trial, v)
        values.append(v)
    return values


@register_scalar_engine("tpe")
def _engine_tpe(problem: ScalarProblem, n_eval: int, seed: int) -> list[float]:
    import optuna

    return _ask_tell_values(
        problem, n_eval, seed, optuna.samplers.TPESampler(seed=int(seed)))


@register_scalar_engine("gp")
def _engine_gp(problem: ScalarProblem, n_eval: int, seed: int) -> list[float]:
    import optuna

    return _ask_tell_values(
        problem, n_eval, seed, optuna.samplers.GPSampler(seed=int(seed)))


@register_scalar_engine("cmaes")
def _engine_cmaes(problem: ScalarProblem, n_eval: int, seed: int) -> list[float]:
    import optuna

    return _ask_tell_values(
        problem, n_eval, seed, optuna.samplers.CmaEsSampler(seed=int(seed)))


@register_scalar_engine("turbo")
def _engine_turbo(problem: ScalarProblem, n_eval: int, seed: int) -> list[float]:
    from rfauto.optimization.acq_sampler import TurboSampler

    n_init = max(2, min(16, int(n_eval) // 4))
    sampler = TurboSampler(
        dict(problem.bounds), seed=int(seed), n_init=n_init)
    return _ask_tell_values(problem, n_eval, seed, sampler)


@register_scalar_engine("eipu")
def _engine_eipu(problem: ScalarProblem, n_eval: int, seed: int) -> list[float]:
    from rfauto.optimization.acq_sampler import EipuSampler
    from rfauto.optimization.eipu import EIPUConfig

    sampler = EipuSampler(
        dict(problem.bounds),
        config=EIPUConfig(seed=int(seed)),
        strategy="ei",  # 评估次数预算口径（见模块 docstring 诚实边界）
        n_startup=3)
    return _ask_tell_values(problem, n_eval, seed, sampler)


@register_scalar_engine("sbo")
def _engine_sbo(problem: ScalarProblem, n_eval: int, seed: int) -> list[float]:
    """SBO 引擎：surrogate_loop 主环（house SBO 公开入口）。

    目标经确定性平移 offset=1−known_optimum 进 MAX_BELOW(f,0) 违约量
    通道（≥0 前提；平移保序）；运行后核验 min(原始值) ≥ known_optimum
    否则显式报错（平移下界失守=问题书声明错误，不静默截断）。
    """
    from rfauto.core.objectives import MetricOp, Objective
    from rfauto.optimization.surrogate_loop import run_surrogate_loop

    if problem.known_optimum is None:
        raise ValueError(
            f'问题 "{problem.name}" 未声明 known_optimum——sbo 引擎的'
            "MAX_BELOW 违约量通道需要全局下界作平移基准（问题书补齐或"
            "改用其他引擎）")
    offset = 1.0 - float(problem.known_optimum)
    raw_seen: list[float] = []

    def _eval(params: dict[str, float]) -> dict[str, float]:
        v = float(problem.objective_fn(params))
        raw_seen.append(v)
        return {"f": v + offset}

    n_init = max(2, min(10, int(n_eval) // 4))
    res = run_surrogate_loop(
        dict(problem.bounds),
        [Objective(metric="f", op=MetricOp.MAX_BELOW, value=0.0)],
        _eval, n_init=n_init, max_real=int(n_eval), seed=int(seed))
    if not res.get("ok"):
        raise ValueError(f"sbo 引擎运行失败: {res.get('errors')}")
    if raw_seen and min(raw_seen) < float(problem.known_optimum):
        raise ValueError(
            f'问题 "{problem.name}" 实测最小值 {min(raw_seen)} 低于声明的 '
            f"known_optimum={problem.known_optimum}——平移下界失守，"
            "目标值会被违约量通道截断失真（请修正 known_optimum 声明）")
    trace = [float(c) - offset for c in res["real_cost_trace"]]
    return trace


@register_scalar_engine("turbo_multi")
def _engine_turbo_multi(problem: ScalarProblem, n_eval: int, seed: int) -> list[float]:
    """turbo_multi 引擎：T-N10 多域 TuRBO-5（aurora_p E1 竞赛补榜接入）。

    薄适配 ScalarEngineFn 形态：走 acq_sampler.TurboSampler 多域接线
    （n_regions=DEFAULT_N_REGIONS=5 / region_strategy="ts" 既有缺省，
    零新旋钮）+ ask/tell 公共路径——与 run_turbo_multi 共享同一状态机
    内核、同参提议序列逐位等价（test_turbo5_rei.py 等价钉），预算精确
    消费 n_eval，轨迹=原始值域评估序（LHS 启动段计入预算，n_init 同
    turbo 引擎公式 max(2, min(16, n_eval//4))——turbo vs turbo_multi
    同启动段严格可比，差异面只在多域轮转段）。
    """
    from rfauto.optimization.acq_sampler import TurboSampler
    from rfauto.optimization.turbo import DEFAULT_N_REGIONS

    n_init = max(2, min(16, int(n_eval) // 4))
    sampler = TurboSampler(
        dict(problem.bounds), seed=int(seed), n_init=n_init,
        n_regions=int(DEFAULT_N_REGIONS), region_strategy="ts")
    return _ask_tell_values(problem, n_eval, seed, sampler)


def run_scalar_engine(
        problem: ScalarProblem, engine: str, n_eval: int, seed: int,
) -> list[float]:
    """按名运行已注册引擎（未知名报错并列可用项）。"""
    fn = SCALAR_ENGINE_REGISTRY.get(str(engine).strip())
    if fn is None:
        raise ValueError(
            f"未知引擎 {engine!r}；可用: {list_scalar_engines()}")
    return fn(problem, int(n_eval), int(seed))


# ─── judge 记分面（纯函数；与被测引擎零共享代码路径） ────────────────────────

def _probe_values(problem: ScalarProblem) -> list[float]:
    """确定性探针（LHS 8 点 seed=0）：band 与常数目标负例的共同来源。"""
    from rfauto.optimization.sample_design import lhs_points

    pts = lhs_points(dict(problem.bounds), _PROBE_POINTS, seed=_PROBE_SEED)
    return [float(problem.objective_fn(p)) for p in pts["points"]]


def _best_so_far(values: Sequence[float], horizon: int) -> list[float]:
    """best-so-far 曲线（不足 horizon 以终值补齐——早停不吃 AUC 便宜）。"""
    out: list[float] = []
    run_best = math.inf
    for i in range(int(horizon)):
        if i < len(values):
            run_best = min(run_best, float(values[i]))
        out.append(run_best)
    return out


def _auc_normalized(
    values: Sequence[float], horizon: int, band_lo: float, band_hi: float,
) -> float:
    """归一化 best-so-far AUC（均值口径；越小越好；截负防下穿 band）。"""
    span = band_hi - band_lo
    curve = _best_so_far(values, horizon)
    if not math.isfinite(span) or span <= 0.0:
        raise ValueError(f"band 退化（span={span!r}）——无法归一化")
    acc = 0.0
    for b in curve:
        acc += min(max((b - band_lo) / span, 0.0), 1e12)
    return acc / len(curve)


def _n_evals_to_target(
    values: Sequence[float], horizon: int, target: float | None,
) -> int | None:
    """达标评估次数（best 首次 ≤ target 的 1 基评估序号；未达标 None）。"""
    if target is None:
        return None
    curve = _best_so_far(values, horizon)
    for i, b in enumerate(curve):
        if b <= float(target):
            return i + 1
    return None


def run_competition_scalar(
    problems: Sequence[ScalarProblem],
    engines: Sequence[str],
    n_eval: int,
    seeds: Sequence[int],
) -> dict[str, Any]:
    """同预算标量竞赛（逐引擎×问题×seed 运行 + 两阶段记分 + 平均秩排名）。

    Returns:
        {"schema", "n_eval", "seeds", "engines", "stages",
        "problems": [{name, dim, target, known_optimum, band}...],
        "runs": [{problem, engine, seed, n_evals_used, best_half,
        best_final, auc_half, auc, n_evals_to_target, elapsed_s}...],
        "ranking_stage1" / "ranking_stage2" / "ranking_target":
        [{engine, mean_rank}...]（按 mean_rank 升序，平局按引擎名）}

    Raises:
        ValueError: n_eval ≤0 / engines 或 seeds 为空 / 引擎未注册 /
            探针含非有限值或退化常数目标（#195 语义）/ known_optimum
            ≥ 探针最差值（band 退化）。
    """
    if int(n_eval) <= 0:
        raise ValueError(f"n_eval 必须 >0，实得 {n_eval}")
    if not engines or not seeds:
        raise ValueError("engines 与 seeds 均不得为空")
    if not problems:
        raise ValueError("problems 不得为空")
    unknown = [e for e in engines if str(e).strip() not in SCALAR_ENGINE_REGISTRY]
    if unknown:
        raise ValueError(
            f"未知引擎 {unknown}；可用: {list_scalar_engines()}")

    horizon_half = max(1, int(n_eval) // 2)
    horizon_full = int(n_eval)

    # ── judge 侧预检：探针 band + 常数目标负例（#195） + band 退化负例 ──
    problems_meta: dict[str, dict[str, Any]] = {}
    for problem in problems:
        probe = _probe_values(problem)
        if not all(math.isfinite(v) for v in probe):
            raise ValueError(
                f'问题 "{problem.name}" 探针含非有限值——目标函数在参数盒内'
                "产出 nan/inf，竞赛拒跑")
        p_min, p_max = min(probe), max(probe)
        if p_max - p_min <= 0.0:
            raise ValueError(
                f'问题 "{problem.name}" 探针 {len(probe)} 点目标值全等'
                f"（={p_min!r}）——退化常数目标，优化无意义（#195 常数陷阱"
                "语义），竞赛拒绝开跑")
        band_lo = (float(problem.known_optimum)
                   if problem.known_optimum is not None else p_min)
        if band_lo >= p_max:
            raise ValueError(
                f'问题 "{problem.name}" known_optimum={band_lo!r} ≥ 探针'
                f"最差值 {p_max!r}——归一化 band 退化，请核对 known_optimum")
        problems_meta[problem.name] = {
            "dim": len(problem.bounds),
            "target": problem.target,
            "known_optimum": problem.known_optimum,
            "band": [band_lo, p_max],
        }

    # ── 逐引擎×问题×seed 运行 + 记分 ──
    runs: list[dict[str, Any]] = []
    for problem in problems:
        meta = problems_meta[problem.name]
        band_lo, band_hi = meta["band"]
        for engine in engines:
            for seed in seeds:
                t0 = time.time()
                values = run_scalar_engine(problem, engine, n_eval, seed)
                elapsed = time.time() - t0
                if not values:
                    raise ValueError(
                        f"引擎 {engine} 在问题 {problem.name} 上返回空轨迹")
                curve_full = _best_so_far(values, horizon_full)
                runs.append({
                    "problem": problem.name,
                    "engine": str(engine).strip(),
                    "seed": int(seed),
                    "n_evals_used": len(values),
                    "best_half": curve_full[horizon_half - 1],
                    "best_final": curve_full[-1],
                    "auc_half": _auc_normalized(
                        values, horizon_half, band_lo, band_hi),
                    "auc": _auc_normalized(
                        values, horizon_full, band_lo, band_hi),
                    "n_evals_to_target": _n_evals_to_target(
                        values, horizon_full, meta["target"]),
                    "elapsed_s": round(elapsed, 3),
                })

    result: dict[str, Any] = {
        "schema": "competition-scalar-v1",
        "n_eval": int(n_eval),
        "seeds": [int(s) for s in seeds],
        "engines": [str(e).strip() for e in engines],
        "stages": {"stage1_horizon": horizon_half,
                   "stage2_horizon": horizon_full},
        "problems": [
            {"name": p.name, **problems_meta[p.name]} for p in problems],
        "runs": runs,
    }

    # ── 排名（组内秩→平均秩；两阶段 AUC + 达标次数三套） ──
    problem_names = [p.name for p in problems]
    seed_list = [int(s) for s in seeds]
    for key, metric in (("ranking_stage1", "auc_half"),
                        ("ranking_stage2", "auc")):
        result[key] = _mean_rank_table(runs, problem_names, seed_list, metric)
    result["ranking_target"] = _mean_rank_table(
        runs, problem_names, seed_list, "n_evals_to_target",
        none_sentinel=float(horizon_full + 1))
    return result


def _mean_rank_table(
    runs: list[dict[str, Any]],
    problem_names: Sequence[str],
    seeds: Sequence[int],
    metric: str,
    none_sentinel: float | None = None,
) -> list[dict[str, Any]]:
    """组（problem×seed）内按 metric 升序排名 → 引擎平均秩（确定性平局）。"""
    by_engine: dict[str, list[float]] = {}
    for problem in problem_names:
        for seed in seeds:
            group = [r for r in runs
                     if r["problem"] == problem and r["seed"] == seed]

            def _key(r: dict[str, Any]) -> tuple[float, str]:
                v = r[metric]
                if v is None:
                    if none_sentinel is None:
                        raise ValueError(f"{metric} 出现 None（非达标类指标）")
                    return (none_sentinel, r["engine"])
                return (float(v), r["engine"])

            ordered = sorted(group, key=_key)
            for pos, r in enumerate(ordered, start=1):
                by_engine.setdefault(r["engine"], []).append(float(pos))
    table = [
        {"engine": e, "mean_rank": float(np.mean(vs)),
         "n_groups": len(vs)}
        for e, vs in by_engine.items()
    ]
    table.sort(key=lambda r: (r["mean_rank"], r["engine"]))
    return table


def format_report_markdown(result: dict[str, Any]) -> str:
    """竞赛结果 → markdown 报表（表+md 交付面；确定性输出）。"""
    lines: list[str] = []
    lines.append("# T-N5 单目标优化器族竞赛报表（标量，两阶段同预算）")
    lines.append("")
    lines.append(f"- 预算 n_eval={result['n_eval']}"
                 f"（阶段一 horizon={result['stages']['stage1_horizon']}，"
                 f"阶段二 horizon={result['stages']['stage2_horizon']}）")
    lines.append(f"- seeds={result['seeds']}，engines={result['engines']}")
    lines.append("")
    lines.append("## 问题书与归一化带（judge 侧确定性探针 seed=0）")
    lines.append("")
    lines.append("| 问题 | 维数 | target | known_optimum | band_lo | band_hi |")
    lines.append("|---|---|---|---|---|---|")
    for p in result["problems"]:
        lines.append(
            f"| {p['name']} | {p['dim']} | {p['target']} | "
            f"{p['known_optimum']} | {p['band'][0]:.6g} | {p['band'][1]:.6g} |")
    lines.append("")
    for stage_key, stage_name in (
            ("ranking_stage1", "阶段一（半程 horizon）· 最优值 AUC"),
            ("ranking_stage2", "阶段二（全程 horizon）· 最优值 AUC"),
            ("ranking_target", "达标评估次数（None 记最差档）")):
        lines.append(f"## 排名 · {stage_name}（组内秩平均，越小越好）")
        lines.append("")
        lines.append("| 排名 | 引擎 | 平均秩 | 组数 |")
        lines.append("|---|---|---|---|")
        for i, row in enumerate(result[stage_key], start=1):
            lines.append(
                f"| {i} | {row['engine']} | {row['mean_rank']:.4f} | "
                f"{row['n_groups']} |")
        lines.append("")
    lines.append("## 逐 run 明细")
    lines.append("")
    lines.append(
        "| 问题 | 引擎 | seed | 评估数 | best@半程 | best@终点 | "
        "AUC@半程 | AUC@全程 | 达标评估次数 | 耗时s |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in result["runs"]:
        lines.append(
            f"| {r['problem']} | {r['engine']} | {r['seed']} | "
            f"{r['n_evals_used']} | {r['best_half']:.6g} | "
            f"{r['best_final']:.6g} | {r['auc_half']:.6g} | {r['auc']:.6g} | "
            f"{r['n_evals_to_target'] if r['n_evals_to_target'] is not None else 'None'} | "
            f"{r['elapsed_s']} |")
    lines.append("")
    return "\n".join(lines)
