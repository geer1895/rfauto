"""多目标 BO 服务包装（aurora_n O1 接线席，2026-10-31）：合成族进 → JSON 出。

消费 :class:`rfauto.optimization.mo_bo.MultiObjectiveBO`（T-N13 内核，
715 行此前全仓零运行时消费者——zero_wiring REGISTRY O1 登记欠账本席清偿）。
规则 4（服务层 JSON 进出）+ 铁律 7（数值只由确定性内核产出——本层零新
数值，HV/前沿/采集轨迹全部来自 mo_bo 内核）。

目标函数口径：**本面只收内置合成族**（ZDT1 缩配 / DTLZ2）——外部真函数
不可 JSON 化（真函数通道=配方驱动 `rfauto tune --sampler sbo` 单目标环与
`service.surrogate_optimize_service`，MO 面外部函数走 Python 编程入口
:func:`register_problem` 注册后经 ``kind=<注册名>`` 消费；该回调注册面
**仅 Python 编程层**，CLI/MCP JSON 面只承载内置键）。

代理口径：``mt_gp``（缺省，T-N12 跨指标联合后验 ``predict_joint`` 消费
面）/ ``smt_kriging``（逐指标独立 GP）。其余注册键（poly_ridge/nn 等）
对多目标后验（全指标覆盖 + 逐点 σ）无契约保证，本面显式拒绝而非静默
放行（负例=代理不支持多输出显式报错）。

预算口径：``n_eval`` 为总评估预算（初始 LHS + 迭代轮真评估合计）——
``n_init`` 显式缺省 = min(n_eval, max(3, min(10, n_eval//3)))（下限 3=
代理首拟合最少完整观测数，内核 <3 拒空拟），``n_iter`` =
max(0, (n_eval − n_init) // batch_size)；实际评估数 n_init + n_iter×
batch_size ≥ 预算 − batch_size + 1（整批语义，如实回显不虚报）。

确定性：同 seed 同参数两次调用 hv_curve/front/acquisitions 逐位一致
（内核 G4 钉：初始设计/候选池 lhs 固定 seed、2 维解析路径零随机、
MC 路径逐候选派生子 seed；mt_gp 因子初值由 config.seed 固定）。
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "MO_PROBLEM_REGISTRY",
    "MO_SURROGATE_KINDS",
    "MultiObjectiveProblem",
    "register_problem",
    "run_mo_bo",
]


class MultiObjectiveProblem:
    """内置/注册合成问题描述（目标函数 + 指标键 + 维数契约，纯容器）。

    Attributes:
        name: 注册键（run_mo_bo ``kind`` 消费）。
        objective: {参数} → {指标数值}（最小化口径，同 mo_bo 内核契约）。
        metrics: 指标键列表（≥2；=1 退化标量问题本面显式拒绝）。
        default_n_params: 缺省决策变量数（调用方未给 n_params 时）。
        min_n_params: 决策变量数下限。
        default_n_obj: 缺省指标数（None=指标数由问题本身固定，如 zdt1）。
        n_obj_consumed: True 时消费调用方 ``n_obj``（dtlz2 形态）；
            False 时 ``n_obj`` 给了与问题指标数不一致的值即显式拒绝。
    """

    __slots__ = (
        "default_n_obj",
        "default_n_params",
        "metrics",
        "min_n_params",
        "n_obj_consumed",
        "name",
        "objective",
    )

    def __init__(
        self,
        name: str,
        objective: Callable[[dict[str, float]], dict[str, float]],
        metrics: Sequence[str],
        *,
        default_n_params: int = 2,
        min_n_params: int = 2,
        default_n_obj: int | None = None,
        n_obj_consumed: bool = False,
    ) -> None:
        self.name = str(name)
        self.objective = objective
        self.metrics = [str(k) for k in metrics]
        self.default_n_params = int(default_n_params)
        self.min_n_params = int(min_n_params)
        self.default_n_obj = (
            int(default_n_obj) if default_n_obj is not None else None)
        self.n_obj_consumed = bool(n_obj_consumed)


#: 参数名约定：x0..x{n-1}（内置合成族单一命名面；lhs_points/mt_gp bounds
#: 全部按该键集进出，零映射表）。
def _param_names(n_params: int) -> list[str]:
    return [f"x{i}" for i in range(int(n_params))]


def _make_bounds(
    n_params: int, bounds: dict[str, Sequence[float]] | None,
) -> dict[str, tuple[float, float]]:
    """bounds 归一：缺省单位盒；显式给定须覆盖全参数键集（显式报错）。"""
    names = _param_names(n_params)
    if bounds is None:
        return {n: (0.0, 1.0) for n in names}
    out: dict[str, tuple[float, float]] = {}
    for n in names:
        if n not in bounds:
            raise ValueError(
                f"bounds 缺参数 {n!r}（键集须为 {names}，内置合成族固定命名）")
        lo, hi = float(bounds[n][0]), float(bounds[n][1])
        if not (math.isfinite(lo) and math.isfinite(hi)) or not lo < hi:
            raise ValueError(f"bounds[{n}] 非法：须有限且 low<high，收到 {(lo, hi)}")
        out[n] = (lo, hi)
    extra = set(map(str, bounds)) - set(names)
    if extra:
        raise ValueError(
            f"bounds 含未知参数 {sorted(extra)}（键集须为 {names}）")
    return out


# ── 内置合成族（ZDT1 缩配 / DTLZ2）───────────────────────────────────────

def _zdt1(n_params: int) -> Callable[[dict[str, float]], dict[str, float]]:
    """缩配 ZDT1（最小化；f1=x0、g=1+9·mean(x1:)、f2=g(1−√(f1/g))）。

    n_params=2 时与 test_mo_bo 的 G 系列口径一致；n_params>2 为自然推广
    （g 取余维均值）。解析 Pareto 前沿 f2=1−√f1（x1:=0）。
    """
    def objective(x: dict[str, float]) -> dict[str, float]:
        f1 = float(x["x0"])
        rest = [float(x[f"x{i}"]) for i in range(1, n_params)]
        g = 1.0 + 9.0 * (sum(rest) / len(rest))
        ratio = min(max(f1 / g, 0.0), 1.0)
        return {"f1": f1, "f2": float(g * (1.0 - math.sqrt(ratio)))}

    return objective


def _dtlz2(n_obj: int, n_params: int
           ) -> Callable[[dict[str, float]], dict[str, float]]:
    """DTLZ2（最小化，M=n_obj 指标；解析前沿=单位超球面第一卦象）。

    g 取末 k=n_params−M+1 维 (x−0.5)²；f_i=(1+g)·∏cos·[sin]（Deb 2005
    标准式）。M>2 走 mo_bo MC 采集路径（mc_samples 旋钮消费）。
    """
    m = int(n_obj)

    def objective(x: dict[str, float]) -> dict[str, float]:
        xs = [float(x[f"x{i}"]) for i in range(n_params)]
        k = n_params - m + 1
        g = sum((v - 0.5) ** 2 for v in xs[m - 1:])
        out: dict[str, float] = {}
        for i in range(1, m + 1):
            v = 1.0 + g
            for j in range(0, m - i):
                v *= math.cos(math.pi / 2.0 * xs[j])
            if i > 1:
                v *= math.sin(math.pi / 2.0 * xs[m - i])
            out[f"f{i}"] = v
        del k  # 语义自检位：n_params ≥ m 由 run_mo_bo 预校验（k≥1）
        return out

    return objective


#: 内置合成问题注册表（模块级单源；``register_problem`` 追加，测试/编程
#: 扩展面）。内置键: zdt1（缩配 ZDT1，恒 2 指标）| dtlz2（DTLZ2，指标数
#: 可调 ≥2——M>2 消费 mo_bo MC 采集路径）。
MO_PROBLEM_REGISTRY: dict[str, MultiObjectiveProblem] = {
    "zdt1": MultiObjectiveProblem(
        "zdt1", _zdt1(2), ["f1", "f2"],
        default_n_params=2, min_n_params=2),
    "dtlz2": MultiObjectiveProblem(
        "dtlz2", _dtlz2(2, 3), ["f1", "f2"],
        default_n_params=3, min_n_params=3, default_n_obj=2,
        n_obj_consumed=True),
}


def register_problem(problem: MultiObjectiveProblem) -> None:
    """回调注册面（Python 编程层，不上 CLI/MCP JSON 面）：追加合成问题。

    用途=外部真函数的**确定性代理通道**（调用方自持 objective 闭包时，
    注册后即可经 ``run_mo_bo(kind=<name>)`` 全链消费 mo_bo 内核——JSON
    面仍只承载键名，函数本体不 JSON 化）。重名静默覆盖（registry_kit
    家法同款）；指标数 <2 的问题注册时即显式拒绝（构造面负例单源）。
    """
    if len(problem.metrics) < 2:
        raise ValueError(
            f"问题 {problem.name!r} 指标数 {len(problem.metrics)} <2：MO 档"
            "要求 ≥2 指标，单指标请走 SBO 通道（surrogate_loop）")
    MO_PROBLEM_REGISTRY[str(problem.name)] = problem


#: 多目标后验有契约保证的代理键（mo_bo docstring 消费面两族）。其余
#: surrogate_registry 键不进本面白名单——逐指标掩码/联合协方差契约缺
#: 保证，显式拒绝（负例=代理不支持多输出显式报错）。
MO_SURROGATE_KINDS = ("mt_gp", "smt_kriging")


def _make_surrogate(kind: str, bounds: dict[str, tuple[float, float]],
                    metrics: list[str], seed: int) -> Any:
    """代理构造（mt_gp 缺省联合口 / smt_kriging 逐指标独立口）。

    mt_gp config.seed 固定因子初值（同 seed 同数据逐位复现，T-N12 C4）；
    metrics 钉键序（B/factor 按指标键排序序对齐——不依赖样本到达序）。
    """
    from rfauto.optimization.surrogate import surrogate_registry

    if kind == "mt_gp":
        return surrogate_registry.create("mt_gp", config={
            "bounds": dict(bounds), "metrics": list(metrics),
            "seed": int(seed)})
    if kind == "smt_kriging":
        return surrogate_registry.create("smt_kriging", config={
            "bounds": dict(bounds), "metrics": list(metrics)})
    raise ValueError(
        f"代理 kind {kind!r} 不在多目标支持面 {list(MO_SURROGATE_KINDS)} 内："
        "其余代理键对多目标后验（全指标覆盖+逐点 σ/联合协方差）无契约保证，"
        "拒绝静默放行")


def run_mo_bo(
    kind: str = "zdt1",
    *,
    n_eval: int = 20,
    n_params: int | None = None,
    n_obj: int | None = None,
    surrogate_kind: str = "mt_gp",
    seed: int = 0,
    ref_point: Sequence[float] | None = None,
    n_init: int | None = None,
    batch_size: int = 1,
    n_candidates: int = 256,
    mc_samples: int = 128,
    fantasy: bool = True,
    noise_variances: dict[str, float] | None = None,
    bounds: dict[str, Sequence[float]] | None = None,
    include_samples: bool = True,
) -> dict[str, Any]:
    """运行内置合成族多目标 BO 环（规则 4：JSON 信封进出）。

    Args:
        kind: 内置合成问题键（``MO_PROBLEM_REGISTRY``；zdt1 缺省）。
        n_eval: 总评估预算（初始设计+迭代真评估合计，≥2）。
        n_params: 决策变量数（None=问题缺省；须 ≥ 问题下限）。
        n_obj: 指标数（仅 dtlz2 类 ``n_obj_consumed`` 问题消费，≥2；
            指标 1=退化标量问题显式拒绝并指引 SBO 通道）。
        surrogate_kind: 代理键（mt_gp 缺省 | smt_kriging；其余显式拒绝）。
        seed: 确定性种子（初始设计/候选池/mt_gp 因子初值/MC 子流全派生）。
        ref_point: 超体积参考点（长度=指标数；None=初始前沿冻结——
            跨臂 HV 对比建议显式传同值）。
        n_init: 初始 LHS 点数（None=按预算自动 min(n, max(3, min(10, n//3)))；
            显式值须 ≥3——代理首拟合最少 3 个完整观测）。
        batch_size: 每轮采集批量（≥1；q>1 贪心+plug-in fantasy）。
        n_candidates: 每轮候选池规模（≥batch_size）。
        mc_samples: 指标数>2 时逐候选 MC 样本数（2 维解析路径不消费）。
        fantasy: q>1 时是否启用目标空间 plug-in fantasy。
        noise_variances: {指标: 观测噪声方差}（noise-aware 对角，透传内核）。
        bounds: 显式 bounds（缺省单位盒；键集须为 x0..x{n-1}）。
        include_samples: 信封是否携带全评估 samples（大预算可关）。

    Returns:
        dict: 成功 ``{"ok": True, kind/metrics/n_obj/n_params/bounds/
        surrogate_kind/seed/n_eval_budget/n_init/n_iter/batch_size/
        n_evaluations/ref_point/ref_source/hv_curve/front/front_params/
        acquisitions/samples/info/elapsed_s}``；失败
        ``{"ok": False, "errors": [...]}``（入参校验与内核异常均信封化，
        不抛裸 traceback）。
    """
    t0 = time.time()

    # ── 入参校验（显式报错单源；全部走 error_envelope 不抛裸异常）────────
    if not isinstance(kind, str) or kind not in MO_PROBLEM_REGISTRY:
        return error_envelope(
            f"未知合成问题 kind {kind!r}，可用: {sorted(MO_PROBLEM_REGISTRY)}"
            "（外部函数请走 register_problem Python 注册面）")
    problem = MO_PROBLEM_REGISTRY[kind]
    if int(n_eval) < 2:
        return error_envelope(
            f"n_eval 必须 ≥2（初始设计最少 2 点），收到 {n_eval}")
    if int(batch_size) < 1:
        return error_envelope(f"batch_size 必须 ≥1，收到 {batch_size}")
    if int(n_candidates) < int(batch_size):
        return error_envelope(
            f"n_candidates ({n_candidates}) 不得小于 batch_size ({batch_size})")
    if surrogate_kind not in MO_SURROGATE_KINDS:
        return error_envelope(
            f"代理 kind {surrogate_kind!r} 不在多目标支持面 "
            f"{list(MO_SURROGATE_KINDS)} 内：其余代理键对多目标后验（全指标"
            "覆盖+逐点 σ/联合协方差）无契约保证，拒绝静默放行")

    n_params_eff = (problem.default_n_params if n_params is None
                    else int(n_params))
    if n_params_eff < problem.min_n_params:
        return error_envelope(
            f"n_params 必须 ≥{problem.min_n_params}（问题 {kind} 契约），"
            f"收到 {n_params_eff}")

    if problem.n_obj_consumed:
        n_obj_eff = problem.default_n_obj if n_obj is None else int(n_obj)
        if n_obj_eff < 2:
            return error_envelope(
                f"指标数 1（收到 n_obj={n_obj_eff}）为退化标量问题：MO 档"
                "（EHVI/超体积判据）要求 ≥2 指标，请走单目标 SBO 通道"
                "（rfauto tune --sampler sbo / run_surrogate_loop）")
        if n_obj_eff > n_params_eff:
            return error_envelope(
                f"n_obj ({n_obj_eff}) 不得大于 n_params ({n_params_eff})"
                "（DTLZ2 契约 k=n−M+1 ≥1）")
        problem = MultiObjectiveProblem(
            problem.name, _dtlz2(n_obj_eff, n_params_eff),
            [f"f{i}" for i in range(1, n_obj_eff + 1)],
            default_n_params=n_params_eff, min_n_params=problem.min_n_params,
            default_n_obj=n_obj_eff, n_obj_consumed=True)
    else:
        if n_obj is not None and int(n_obj) != len(problem.metrics):
            return error_envelope(
                f"问题 {kind} 指标数固定为 {len(problem.metrics)}"
                f"（{problem.metrics}），不消费 n_obj="
                f"{n_obj}——指标数可调请用 dtlz2")
        n_obj_eff = len(problem.metrics)

    try:
        bounds_eff = _make_bounds(n_params_eff, bounds)
    except ValueError as exc:
        return error_envelope(str(exc))

    metrics = list(problem.metrics)
    if len(metrics) < 2:
        # 注册面兜底（register_problem 已拒；防御直改注册表的路径）
        return error_envelope(
            f"问题 {kind} 指标数 {len(metrics)} <2：MO 档要求 ≥2 指标，"
            "请走单目标 SBO 通道（run_surrogate_loop）")
    if ref_point is not None:
        ref_list = [float(v) for v in ref_point]
        if len(ref_list) != len(metrics):
            return error_envelope(
                f"ref_point 长度 {len(ref_list)} 与指标数 {len(metrics)} "
                "不一致（逐指标超体积参考点）")
    else:
        ref_list = None

    n_init_eff = (min(int(n_eval), max(3, min(10, int(n_eval) // 3)))
                  if n_init is None else int(n_init))
    # 3 = mt_gp/smt_kriging 首拟合最少完整观测数（内核 <3 拒空拟，G4a）；
    # n_iter=0（n_init≥n_eval）纯初始设计面无拟合适用，故一并按 3 收底
    if n_init_eff < 3:
        return error_envelope(
            f"n_init 必须 ≥3（mt_gp/smt_kriging 首拟合最少 3 个完整观测，"
            f"内核 <3 拒绝空拟），收到 {n_init_eff}；纯初始设计请令 "
            "n_init=n_eval（n_iter=0 不拟合）")
    n_iter_eff = max(0, (int(n_eval) - n_init_eff) // int(batch_size))

    # ── 构造内核并环跑（异常信封化；数值全部来自 mo_bo 内核，铁律 7）────
    from rfauto.optimization.mo_bo import MultiObjectiveBO

    try:
        surrogate = _make_surrogate(
            surrogate_kind, bounds_eff, metrics, seed)
        mo = MultiObjectiveBO(
            bounds_eff, metrics, surrogate,
            ref_point=ref_list,
            n_init=n_init_eff,
            n_iter=n_iter_eff,
            batch_size=int(batch_size),
            n_candidates=int(n_candidates),
            seed=int(seed),
            noise_variances=noise_variances,
            mc_samples=int(mc_samples),
            fantasy=bool(fantasy))
        result = mo.run(problem.objective)
    except (ValueError, RuntimeError) as exc:
        return error_envelope(f"MO-BO 环失败: {exc}")

    elapsed = time.time() - t0
    envelope = ok_envelope(
        kind=kind,
        metrics=metrics,
        n_obj=n_obj_eff,
        n_params=n_params_eff,
        bounds={k: [lo, hi] for k, (lo, hi) in bounds_eff.items()},
        surrogate_kind=surrogate_kind,
        seed=int(seed),
        n_eval_budget=int(n_eval),
        n_init=n_init_eff,
        n_iter=n_iter_eff,
        batch_size=int(batch_size),
        n_candidates=int(n_candidates),
        mc_samples=int(mc_samples),
        fantasy=bool(fantasy),
        n_evaluations=result["n_evaluations"],
        ref_point=result["ref_point"],
        ref_source="explicit" if ref_list is not None else "frozen",
        hv_curve=result["hv_curve"],
        front=result["front"],
        front_params=result["front_params"],
        acquisitions=result["acquisitions"],
        info=result["info"],
        elapsed_s=round(elapsed, 3),
    )
    if include_samples:
        envelope["samples"] = [
            {"params": {k: float(v) for k, v in s["params"].items()},
             "metrics": {k: float(v) for k, v in s["metrics"].items()}}
            for s in result["samples"]]
    return envelope
