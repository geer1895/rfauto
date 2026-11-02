"""T-N17（aurora_n W2）：BoTorch EI 对照臂——竞赛架 optional extra 引擎。

一句话：``pip install rfauto[botorch]`` 后经
``ensure_botorch_engine_registered()`` opt-in 注册 ``"botorch_ei"`` 引擎
（BoTorch 最小 API：SingleTaskGP + LogExpectedImprovement（单点 qEI，log
数值稳定档——BoTorch 对 legacy ``ExpectedImprovement`` 的官方替换名，
同 API 同语义）+ optimize_acqf），进 T-N5 标量竞赛架与既有七引擎同台
（judge 只消费评估序目标值轨迹，#118 裁判/被测非共享代码路径不变）。

**依赖纪律（重依赖 optional extra）**：BoTorch/GPyTorch/torch 是重依赖——
本模块**顶层零 torch/botorch import**（无依赖环境、公开 API 快照、
import-linter 均可安全 import 本模块），全部引擎路径内惰性 import。
未安装 botorch 时：
- 注册面缺席——``"botorch_ei"`` 不在 ``SCALAR_ENGINE_REGISTRY``，竞赛架
  按未知引擎显式报错并列可用项（不裸崩 ModuleNotFoundError）；
- ``ensure_botorch_engine_registered()`` 显式 ImportError 带安装指引
  （指路 ``rfauto[botorch]`` extra），不静默降级。

**注册语义（opt-in，既有路径零改动）**：注册不发生在 import 期，只由
调用方显式 opt-in；未装=少一臂，已装但不 opt-in 也=少一臂——既有竞赛
路径（tpe/gp/cmaes/turbo/turbo_multi/eipu/sbo 七引擎注册序与排名）零影响。
幂等：已注册时重复调用返回注册名不重复注册。

**确定性（同 seed 逐位，本机内）**：启动段走仓内
``sample_design.lhs_points``（seed 透传，引擎无关）；BO 迭代全链
``torch.manual_seed(seed)`` + ``torch.use_deterministic_algorithms(True)``
（退出恢复既有 torch 确定性开关，不污染全局状态）+ 固定
num_restarts/raw_samples + float64 GP。**注记**：torch 数值跨平台受
BLAS 实现影响——同 seed 轨迹逐位保证只在本机内（同 torch wheel）成立，
跨机/跨平台仅容差可比（如实在此声明，不预声明跨机逐位）。

**预算口径**：精确消费 n_eval（LHS 启动段 n_init=max(2, min(10, n_eval//4))
计入预算，与 sbo/turbo 同族口径）；目标启动段全等（退化常数，#195 语义）
显式拒绝开跑。

铁律 7 对照：本模块只编排（GP 拟合/采集优化是 BoTorch 公开 API 的确定性
调用），物理数字全部来自注入的目标函数与 BoTorch 引擎，LLM/本模块零
数值产出。许可证：BoTorch/GPyTorch/linear_operator 均 MIT（调研席已核，
PROPOSALS.md T-N17）。
"""

from __future__ import annotations

from typing import Any

from rfauto.optimization.competition_scalar import (
    ScalarProblem,
    register_scalar_engine,
)

__all__ = [
    "BOTORCH_ENGINE_NAME",
    "ensure_botorch_engine_registered",
    "is_botorch_available",
]

#: 竞赛架注册名（第二榜对照臂）
BOTORCH_ENGINE_NAME = "botorch_ei"

#: 采集优化固定档（确定性钉的一部分：重排数/原始采样数与问题无关）
_NUM_RESTARTS = 5
_RAW_SAMPLES = 32


def is_botorch_available() -> bool:
    """BoTorch 栈可 import 性探针（惰性真实 import；缺席=False 不抛错）。"""
    try:
        import botorch  # noqa: F401  botorch import 即含 gpytorch/torch 全栈
    except ImportError:
        return False
    return True


def ensure_botorch_engine_registered() -> str:
    """opt-in 注册 ``"botorch_ei"`` 进竞赛架（幂等；缺席显式 ImportError）。

    Returns:
        引擎注册名（``BOTORCH_ENGINE_NAME``）。

    Raises:
        ImportError: botorch 未安装——带 ``pip install rfauto[botorch]``
            安装指引（不裸崩 ModuleNotFoundError；未装环境竞赛架少一臂，
            其余引擎不受影响）。
    """
    from rfauto.optimization.competition_scalar import SCALAR_ENGINE_REGISTRY

    if BOTORCH_ENGINE_NAME in SCALAR_ENGINE_REGISTRY:
        return BOTORCH_ENGINE_NAME
    if not is_botorch_available():
        raise ImportError(
            f"botorch 未安装——{BOTORCH_ENGINE_NAME} 对照臂不可用。安装："
            "pip install rfauto[botorch]（botorch/GPyTorch/linear_operator "
            "均 MIT，纯 python 包；torch>=2.4 由 botorch 传递依赖或 "
            "rfauto[torch] extra 提供）。未安装环境竞赛架少一臂，"
            "既有引擎与路径零影响。")
    register_scalar_engine(BOTORCH_ENGINE_NAME)(_engine_botorch_ei)
    return BOTORCH_ENGINE_NAME


def _engine_botorch_ei(
        problem: ScalarProblem, n_eval: int, seed: int) -> list[float]:
    """BoTorch EI 引擎 runner：(problem, n_eval, seed) → 评估序目标值轨迹。

    LHS 启动段（seed 透传）+ SingleTaskGP/LogExpectedImprovement/
    optimize_acqf 逐点消费预算到 n_eval（精确预算，无早停）。参数空间
    归一化到单位盒优化（GP 拟合与采集优化同域，数值稳定）。
    """
    import torch
    from botorch.acquisition import LogExpectedImprovement
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms.outcome import Standardize
    from botorch.optim import optimize_acqf
    from gpytorch.mlls import ExactMarginalLogLikelihood

    from rfauto.optimization.sample_design import lhs_points

    n_eval_i = int(n_eval)
    if n_eval_i <= 0:
        return []
    names = sorted(problem.bounds)
    lower = [float(problem.bounds[n][0]) for n in names]
    span = [float(problem.bounds[n][1]) - lo for n, lo in zip(names, lower,
                                                              strict=True)]
    n_init = max(2, min(10, n_eval_i // 4))

    def _to_params(unit_row: list[float]) -> dict[str, float]:
        return {
            n: lo + u * s
            for n, u, lo, s in zip(names, unit_row, lower, span, strict=True)
        }

    pts: list[dict[str, Any]] = lhs_points(
        dict(problem.bounds), n_init, seed=int(seed))["points"]
    values = [float(problem.objective_fn(p)) for p in pts]
    xs = [[(float(p[n]) - lo) / s
           for n, lo, s in zip(names, lower, span, strict=True)] for p in pts]

    prev_deterministic = torch.are_deterministic_algorithms_enabled()
    torch.manual_seed(int(seed))
    torch.use_deterministic_algorithms(True)
    try:
        dim = len(names)
        unit_bounds = torch.stack([
            torch.zeros(dim, dtype=torch.float64),
            torch.ones(dim, dtype=torch.float64),
        ])
        while len(values) < n_eval_i:
            if max(values) - min(values) <= 0.0:
                raise ValueError(
                    f'问题 "{problem.name}" 已评估目标值全等（启动段退化常数'
                    "）——GP 方差归零（#195 常数陷阱语义），BoTorch EI 臂"
                    "拒绝继续")
            x_t = torch.tensor(xs, dtype=torch.float64)
            y_t = torch.tensor([[v] for v in values], dtype=torch.float64)
            gp = SingleTaskGP(x_t, y_t, outcome_transform=Standardize(m=1))
            mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
            fit_gpytorch_mll(mll)
            acqf = LogExpectedImprovement(
                gp, best_f=min(values), maximize=False)
            cand, _ = optimize_acqf(
                acqf, bounds=unit_bounds, q=1,
                num_restarts=_NUM_RESTARTS, raw_samples=_RAW_SAMPLES)
            row = [min(max(float(c), 0.0), 1.0)
                   for c in cand.squeeze(0).tolist()]
            xs.append(row)
            values.append(float(problem.objective_fn(_to_params(row))))
    finally:
        torch.use_deterministic_algorithms(prev_deterministic)
    return values
