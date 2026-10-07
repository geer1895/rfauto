"""start_tune_async_mcp/run_sweep_mcp —— tune/sweep 主优化入口（SN-16，W6-A 2026-10-06）。

MCP 缺口收口（SN 席维度 6 实测）：主优化环此前仅 warm_start 变体与单点
sampler 可达，agent 无法驱动主 tune/sweep。本模块补两个主入口：
- ``start_tune``：复用 service/api.start_tune_async（SN-9 job 协议），立即
  返回 job_id，经既有 poll_job/wait_job 轮询——**不阻塞 MCP 会话**；
- ``run_sweep``：复用 optimization/sweep_backend.run_sweep（同步，参数扫描
  预算以组合数硬上限约束）。

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
def start_tune(
    recipe_path: str,
    adapter: str = "fake",
    max_trials: int = 60,
    study_name: str = "",
    sampler: str = "tpe",
    seed: int = 0,
) -> dict[str, Any]:
    """提交主优化任务（异步），立即返回 job_id。

    复用 CLI ``rfauto tune`` 同源的 start_tune_async（单目标路径，Optuna
    storage 持久化，断点自动恢复）。经 poll_job/wait_job 轮询进度与终态
    （终态 result 收 best_params/best_cost/best_metrics/trials 摘要）。

    Args:
        recipe_path: 配方文件路径（YAML，含 optimization.params/objectives 段）
        adapter: 适配器名称，"fake"（默认）或 "hfss"
        max_trials: 最大试验次数（缺省 60）
        study_name: Optuna study 名（空串=由配方自动派生）
        sampler: 采样器 "tpe"（缺省）
        seed: 随机种子（缺省交由内核固定缺省 SAMPLER_SEED=42；显式传 0 走内核缺省语义）

    Returns:
        dict: {ok: bool, job_id: str, state: str, message: str}
    """
    from rfauto.service.api import start_tune_async

    return start_tune_async(
        recipe_path,
        adapter_name=adapter,
        max_trials=max_trials,
        study_name=study_name or None,
        sampler=sampler,
        seed=seed if seed else None,
    )


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def run_sweep(
    recipe_path: str,
    adapter: str = "fake",
    method: str = "auto",
    coarse_samples: int = 15,
    max_combos: int = 60,
    resume_run_id: str = "",
) -> dict[str, Any]:
    """运行参数扫描（粗扫→精调，同步返回全量信封）。

    复用 CLI ``rfauto sweep`` 同源的 run_sweep；组合数受 max_combos 硬上限
    约束（fake 通道秒级，hfss 通道请先估预算）。resume_run_id 给定时从该
    run 的 sweep checkpoint 续扫（SN-11：命中组合不重跑，携带原结果）。

    Args:
        recipe_path: 配方文件路径（YAML，含 params.bounds/objectives 段）
        adapter: 适配器名称，"fake"（默认）或 "hfss"
        method: "auto"（粗扫+精调）| "grid" | "random" | "lhs" | "fine_only"
        coarse_samples: 粗扫采样数（缺省 15）
        max_combos: 最大组合数安全上限（缺省 60）
        resume_run_id: 断点续扫源 run_id（空串=新开扫描）

    Returns:
        dict: {ok, run_id, run_dir, method, total_combos, coarse_combos,
        fine_combos, resumed_combos, results(前 20), best}
    """
    from rfauto.optimization.sweep_backend import run_sweep as _run_sweep

    return _run_sweep(
        recipe_path,
        adapter_name=adapter,
        method=method,
        coarse_samples=coarse_samples,
        max_combos=max_combos,
        resume_run_id=resume_run_id or None,
    )
