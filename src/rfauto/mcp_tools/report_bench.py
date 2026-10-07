"""warm_start_optimize/export_report_pdf/goldset_regression/agentbench_regression（报告与回归门）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope, ok_envelope

# ─── 15. warm_start_optimize (E11 stage-2 数据面) ─────────────────────────────

@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def warm_start_optimize(
    recipe_path: str,
    dataset: str,
    model: str | None = None,
    source_study: str | None = None,
    adapter: str = "fake",
    max_trials: int = 60,
) -> dict[str, Any]:
    """warm-start 优化（report_bench 域）：数据集历史样本 → 先验注入求解。

    副作用：创建 run 目录、写 Optuna study（enqueue WAITING 先验点）；
    不用于无历史数据的冷启动（相似度门拒绝时降级冷启动 warm_start_n=0，
    ok 仍 True 如实）。数据集缺失 → ok=False errors。时序：注入后回查
    WAITING 落位。

    Args:
        recipe_path: 配方文件路径（YAML 格式）
        dataset: 数据集名（datasets materialize 产物）
        model: 按模板族过滤（model 列精确匹配）；缺省不过滤
        source_study: 按来源 study 名过滤；缺省不过滤
        adapter: 适配器名称，"fake"（默认）或 "hfss"
        max_trials: 最大 trial 数

    Returns:
        dict: {ok, warm_start_data: {n_samples, n_skipped_invalid, ...},
        warm_start_n, best_params, best_cost}——相似度门拒绝时
        warm_start_n=0（降级冷启动，ok 仍为 True）。
    """
    from rfauto.service.warm_start_data import (
        run_optimization_warm_start_from_dataset as _run,
    )
    return _run(
        recipe_path, dataset, model=model, source_study=source_study,
        adapter_name=adapter, max_trials=max_trials,
    )


# ─── 16. export_report_pdf (WP4.7 报告 PDF) ──────────────────────────────────

@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def export_report_pdf(
    run_id: str,
    filename: str = "report.pdf",
    narrative: str | None = None,
) -> dict[str, Any]:
    """PDF 报告导出（report_bench 域）：run 指标 → 多页 PDF（WP4.7）。

    副作用：在 run 目录（或指定名）写入 PDF 文件；叙述文本透传不触发
    任何 LLM 调用。run 不存在/无 metrics → ok=False errors 如实。
    时序：create_run 终态后调用。

    Args:
        run_id: 运行 ID（runs/<run_id>/results/metrics.json 须存在）
        filename: 输出文件名（写入 run 目录，默认 report.pdf）
        narrative: 叙述文本（F9 位；不触发任何 LLM 调用）

    Returns:
        dict: {ok, run_id, report: str, metrics: dict}
    """
    from pathlib import Path

    from rfauto.infra.report import export_report_pdf as _export
    from rfauto.service.api import get_metrics as _get_metrics
    result = _get_metrics(run_id)
    if not result.get("ok"):
        return error_envelope(
            result.get("errors") or ["读取 run 指标失败"])
    data = result.get("data") or {}
    try:
        report_path = _export(
            Path("runs") / run_id,
            metrics=data.get("metrics", {}),
            narrative=narrative,
            filename=filename,
        )
    except Exception as e:
        return error_envelope([str(e)])
    return ok_envelope(
        run_id=run_id,
        report=str(report_path),
        metrics=data.get("metrics", {}),
    )


# ─── 21. 回归门（WP3.7/F6：goldset + AgentBench，0bs② 薄壳） ───────────────
# 两道门离线、确定性、零网络：不带轨迹/记录时用 service 离线参考回放
# （门自洽正控，绝不空跑绿），同 rfauto bench 子命令口径。

@mcp.tool
def goldset_regression(
    trajectories: list[dict[str, Any]] | None = None,
    goldset_path: str | None = None,
    runtime_tools: list[str] | None = None,
    min_tsa: float = 0.9,
    min_fca: float = 0.9,
    min_pass3: float = 0.0,
    require_full_coverage: bool = True,
) -> dict[str, Any]:
    """金标回归门（report_bench 域）：轨迹 vs 金标集 → TSA/FCA 判定。

    WP3.7/0ar（runtime/协议变更后一键回归）。无副作用（只读金标集）；
    trajectories 缺省时用离线参考回放做正控，不用于替代真实埋点评估。
    金标集缺失 → ok=False 如实。只读无时序约束。

    Args:
        trajectories: 已记录轨迹 [{"id", "trajectory": [...]}]；缺省=参考回放
        goldset_path: 金标集路径（缺省 tests/gold/agent_goldset.yaml）
        runtime_tools: 当前 runtime 工具名列表；给定时校验协议面覆盖
        min_tsa: TSA 阈值
        min_fca: FCA 阈值
        min_pass3: pass3 阈值
        require_full_coverage: 轨迹是否必须覆盖全部金标任务

    Returns:
        dict: {ok, verdict, reasons, report, ...}（run_goldset_regression 契约）
    """
    from rfauto.service.goldset_service import (
        reference_trajectory_provider,
        run_goldset_regression,
    )
    return run_goldset_regression(
        trajectories,
        goldset_path=goldset_path,
        runtime_tools=runtime_tools,
        trajectory_provider=None if trajectories else reference_trajectory_provider,
        min_tsa=min_tsa, min_fca=min_fca, min_pass3=min_pass3,
        require_full_coverage=require_full_coverage,
    )


@mcp.tool
def agentbench_regression(
    records: list[dict[str, Any]] | None = None,
    public_path: str | None = None,
    private_path: str | None = None,
    runtime_tools: list[str] | None = None,
    min_abstraction: float = 0.9,
    min_execution: float = 0.8,
    require_private: bool = False,
    require_full_coverage: bool = True,
) -> dict[str, Any]:
    """AgentBench 回归门（report_bench 域）：两轴打分+公开/私有双集防污染。

    WP3.7。无副作用（只读任务集）；records 缺省时用离线参考回放做正控，
    不用于替代真实埋点评估；私有集缺配置时按 require_private 判如实。
    任务集缺失 → ok=False 如实。只读无时序约束。

    Args:
        records: 已记录埋点 [{"id", "trajectory", "artifacts", "numeric"}]；缺省=参考回放
        public_path: 公开集路径（缺省 tests/gold/agentbench_public.yaml）
        private_path: 私有集路径（缺省读 RFAUTO_AGENTBENCH_PRIVATE_SET）
        runtime_tools: 当前 runtime 工具名列表；给定时校验协议面覆盖
        min_abstraction: 任务抽象轴阈值
        min_execution: 执行轴阈值
        require_private: 私有集未配置即 FAIL（终评口径）
        require_full_coverage: 记录是否必须覆盖全部基准任务

    Returns:
        dict: {ok, verdict, reasons, report, ...}（run_agentbench_regression 契约）
    """
    from rfauto.service.agent_bench import (
        reference_agentbench_provider,
        run_agentbench_regression,
    )
    return run_agentbench_regression(
        records,
        trajectory_provider=None if records else reference_agentbench_provider,
        public_path=public_path, private_path=private_path,
        runtime_tools=runtime_tools,
        min_abstraction=min_abstraction, min_execution=min_execution,
        require_private=require_private,
        require_full_coverage=require_full_coverage,
    )
