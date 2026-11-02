"""mo_run —— 多目标 BO 合成族环入口（aurora_n O1 接线席，2026-10-31）。

T-N13 MultiObjectiveBO（Noise-Aware EHVI 贪心）的 MCP 运行时门
（zero_wiring REGISTRY O1 登记欠账清偿）。同步执行（内置合成族秒级；
M>2 MC 路径请收 n_candidates/mc_samples 控预算）。目标函数只收内置
合成族——外部真函数不可 JSON 化（回调注册面=service 层
register_problem 仅 Python 编程入口，JSON 面只承载键名）。

规则 4：JSON 信封进出；铁律 7：数值只由确定性内核产出，本层零新数值。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def mo_run(
    kind: str = "zdt1",
    n_eval: int = 20,
    n_obj: int = 2,
    n_params: int | None = None,
    surrogate: str = "mt_gp",
    seed: int = 0,
    ref_point: str = "",
    n_init: int | None = None,
    batch_size: int = 1,
    n_candidates: int = 256,
    mc_samples: int = 128,
    fantasy: bool = True,
) -> dict[str, Any]:
    """运行内置合成族多目标 BO 环（EHVI 采集，同步返回全量信封）。

    内置合成问题：zdt1（缩配 ZDT1，恒 2 指标）| dtlz2（DTLZ2，指标数
    n_obj 可调，大于 2 走 MC 采集路径）。同 seed 同参数逐位复现（确定性
    内核）。返回超体积曲线、帕累托前沿（目标值+参数）、采集轨迹与全评估
    样本。外部真函数不走本工具（JSON 不可序列化目标函数）——真函数多目标
    优化属配方驱动通道扩展面，Python 编程入口见
    rfauto.service.mo_bo_service.register_problem。

    Args:
        kind: 内置合成问题键：zdt1（缺省）| dtlz2
        n_eval: 总评估预算（初始 LHS+迭代真评估合计，≥2；缺省 20）
        n_obj: 目标数（仅 dtlz2 消费，≥2；=1 退化标量问题显式拒绝并指引
            单目标 SBO 通道；缺省 2）
        n_params: 决策变量数（None=按问题缺省：zdt1=2/dtlz2=3）
        surrogate: 代理键：mt_gp（跨指标联合后验，缺省）| smt_kriging
            （逐指标独立）；其余代理键对多目标后验无契约保证，显式拒绝
        seed: 确定性种子（初始设计/候选池/代理/MC 子流全由它派生）
        ref_point: 超体积参考点（逗号分隔浮点，长度=指标数；空串=由初始
            前沿冻结——跨臂 HV 对比建议显式传同值）
        n_init: 初始 LHS 点数（None=按预算自动 max(2, min(10, n//3))）
        batch_size: 每轮采集批量（≥1；大于 1 贪心+plug-in fantasy）
        n_candidates: 每轮候选池规模（MC 路径大池显著变慢，缺省 256）
        mc_samples: 指标数大于 2 时逐候选 MC 样本数（缺省 128）
        fantasy: 批内是否启用目标空间 plug-in fantasy（缺省 True）

    Returns:
        dict: {ok, kind, metrics, n_obj, n_params, bounds, surrogate_kind,
        seed, n_eval_budget, n_init, n_iter, batch_size, n_evaluations,
        ref_point, ref_source, hv_curve, front, front_params, acquisitions,
        samples, info, elapsed_s}；失败 {ok: False, errors: [...]}
    """
    from rfauto.service.mo_bo_service import run_mo_bo

    kwargs: dict[str, Any] = {}
    if n_params is not None:
        kwargs["n_params"] = n_params
    if n_init is not None:
        kwargs["n_init"] = n_init
    if str(ref_point).strip():
        try:
            kwargs["ref_point"] = [
                float(v) for v in str(ref_point).split(",") if v.strip()]
        except ValueError:
            from rfauto.service.envelope import error_envelope

            return error_envelope(
                f"ref_point 必须是逗号分隔浮点，实际 {ref_point!r}")
    return run_mo_bo(
        kind, n_eval=n_eval, n_obj=n_obj, surrogate_kind=surrogate,
        seed=seed, batch_size=batch_size, n_candidates=n_candidates,
        mc_samples=mc_samples, fantasy=fantasy, **kwargs)
