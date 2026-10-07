"""rf_propose_params/rf_run_sampler/rf_critique_point/rf_spec_cost/multi_agent_run/autotune_self_verify（agent 原语与自验证环）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import _silence_pyaedt_screen_logs as _silence_pyaedt_screen_logs
from rfauto.mcp_tools._core import mcp as mcp

# ─── 22. 多 Agent 编排三层栈（WP3.8，0bt① 薄壳：4 内核工具 + 端到端） ────────
# 铁律 7：rf_run_sampler 是唯一产数环节（引擎采样器），其余三个只做
# typed 提议/评判/加权 cost；multi_agent_run 缺省真机 openEMS 采样器（串行）。

@mcp.tool
def rf_propose_params(
    bounds: dict[str, list[float]],
    current_params: dict[str, float] | None = None,
    fixes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """调优提议内核（agent 域）：bounds/fixes → 初值落参+探测候选展开。

    无副作用，可安全调用；typed 提议面不产物理数字（铁律 7），不用于真机
    求值（走 rf_run_sampler）。入参非法 → {ok: False, errors} 信封不抛。
    只读无时序约束。

    Args:
        bounds: 参数界 {name: [low, high]}
        current_params: 当前参数点；缺省=界中点初值
        fixes: critique 给出的 typed fixes（op=scale|coord_probe）

    Returns:
        dict: {ok, tool, result: {params, candidates, applied_kinds}}
    """
    from rfauto.service.multi_agent_service import call_kernel_tool
    return call_kernel_tool("rf_propose_params", {
        "bounds": bounds, "current_params": current_params, "fixes": fixes or []})


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def rf_run_sampler(
    recipe_path: str,
    params: dict[str, float],
    mesh_resolution_mm: float = 0.0,
) -> dict[str, Any]:
    """验证采样内核（agent 域）：params → metrics/valley（唯一产数环节）。

    副作用：按配方构造 openEMS 快验证采样器并求解一点
    （runs/multi_agent_work_*）；不用于批量优化（走 campaign 面或
    multi_agent_run）。采样器缺席/求解失败 → {ok: False, errors} 如实。
    时序：调用前配方须就绪；长任务改走 create_run_async。

    Args:
        recipe_path: 配方文件路径（取 model/setup/objectives）
        params: 待评估参数点
        mesh_resolution_mm: openEMS 网格 base 覆盖 mm（0=自动）

    Returns:
        dict: {ok, tool, result: {metrics, valley_ghz}} 或 {ok: False, errors}
    """
    _silence_pyaedt_screen_logs()
    from rfauto.service.multi_agent_service import call_kernel_tool
    return call_kernel_tool(
        "rf_run_sampler", {"params": params},
        recipe_path=recipe_path, mesh_resolution_mm=mesh_resolution_mm)


@mcp.tool
def rf_critique_point(
    metrics: dict[str, float],
    objectives: list[dict[str, Any]],
    valley_ghz: float | None = None,
    bounds: dict[str, list[float]] | None = None,
    current_params: dict[str, float] | None = None,
) -> dict[str, Any]:
    """评审内核（agent 域）：metrics+objectives → verdict/issues/typed fixes。

    无副作用，可安全调用；确定性评判（铁律 7），不产出优化建议之外的新
    参数点（提议走 rf_propose_params）。非法输入 → {ok: False, errors}
    信封不抛。只读无时序约束。

    Args:
        metrics: 指标字典（如 s11_db_max_in_band）
        objectives: 配方 objectives 列表
        valley_ghz: |S11| 谷位 GHz（缺省不做频率尺度规则）
        bounds: 参数界 {name: [low, high]}（给定才产 typed fixes）
        current_params: 当前参数点

    Returns:
        dict: {ok, tool, result: {verdict, issues, fixes, violations}}
    """
    from rfauto.service.multi_agent_service import call_kernel_tool
    return call_kernel_tool("rf_critique_point", {
        "metrics": metrics, "objectives": objectives, "valley_ghz": valley_ghz,
        "bounds": bounds or {}, "current_params": current_params})


@mcp.tool
def rf_spec_cost(
    metrics: dict[str, float],
    objectives: list[dict[str, Any]],
) -> dict[str, Any]:
    """SpecEvaluator cost 内核（agent 域）：metrics+objectives → 加权 cost。

    无副作用，可安全调用；cost≥0 越小越好（0=全满足），不用于 verdict
    判定（走 rf_critique_point）。非法输入 → {ok: False, errors} 信封不抛。
    只读无时序约束。

    Args:
        metrics: 指标字典
        objectives: 配方 objectives 列表

    Returns:
        dict: {ok, tool, result: {cost}}
    """
    from rfauto.service.multi_agent_service import call_kernel_tool
    return call_kernel_tool("rf_spec_cost",
                            {"metrics": metrics, "objectives": objectives})


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def multi_agent_run(
    recipe_path: str,
    max_rounds: int = 4,
    mesh_resolution_mm: float = 0.0,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
) -> dict[str, Any]:
    """评审/调优/验证三角色端到端（LangGraph 式图 + MCP 工具层 + A2A，WP3.8）。

    副作用：真机 openEMS 采样（串行纪律），工作目录 runs/multi_agent_work_*。
    FAIL 如实上报不凑绿；采样器异常=ERROR 与评审 FAIL 语义分立。

    Args:
        recipe_path: 配方文件路径（optimization.params 为搜索空间）
        max_rounds: 评审面轮次预算
        mesh_resolution_mm: openEMS 网格 base 覆盖 mm（0=自动）
        f0_tolerance: 谷位/带中心容差
        rl_floor_db: 回损地板 dB
        max_step_pct: 单轮修正步长上限（比例）

    Returns:
        dict: {ok, verdict, rounds, params, metrics, cost, history, graph, a2a, mcp}
    """
    _silence_pyaedt_screen_logs()
    from rfauto.service.multi_agent_service import multi_agent_run as _run
    return _run(
        recipe_path, max_rounds=max_rounds, mesh_resolution_mm=mesh_resolution_mm,
        f0_tolerance=f0_tolerance, rl_floor_db=rl_floor_db,
        max_step_pct=max_step_pct)


# ─── 23. 自验证环（WP3.5 收口，0bq① 薄壳） ────────────────────────────────────

@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def autotune_self_verify(
    recipe_path: str,
    budget_coarse: int = 3,
    mesh_coarse_mm: float = 1.0,
    mesh_fine_mm: float = 0.5,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
    fine_epsilon: float = 0.2,
    sandbox: bool = True,
    board: bool = True,
) -> dict[str, Any]:
    """自验证环（agent 域）：propose→verify→fix 闭环+里程碑分解+执行看板。

    副作用：真机 openEMS 粗→细双采样器求解（串行），产物 runs/<run_id>/
    autotune.json、看板 runs/loop_boards/<board_id>.json、沙箱草稿（M5）；
    不用于无配方冒烟（先 plan/合成面备配方）。verdict PASS|FAIL|TAKEN_OVER
    如实；失败走返回体 ok=False 不抛出。时序：调用前配方就绪；跑批期间
    看板可暂停/接管。

    Args:
        recipe_path: 配方文件路径
        budget_coarse: 粗网格轮数预算
        mesh_coarse_mm: 粗网格 base mm
        mesh_fine_mm: 细网格 base mm（0 或与粗相同=关闭 M4 复验）
        f0_tolerance: 谷位/带中心容差
        rl_floor_db: 回损地板 dB
        max_step_pct: 单轮修正步长上限（比例）
        fine_epsilon: M4 细网格 cost 容许劣化比例
        sandbox: 是否把 best 落沙箱草稿（M5）
        board: 是否创建执行看板（UI 可暂停/接管）

    Returns:
        dict: SelfVerifyPayload 契约 + contract_check；失败 → ok=False 如实
    """
    _silence_pyaedt_screen_logs()
    from rfauto.service.autotune_service import self_verify_loop
    from rfauto.service.contracts import annotate_contract
    result = self_verify_loop(
        recipe_path, budget_coarse=budget_coarse, mesh_coarse_mm=mesh_coarse_mm,
        mesh_fine_mm=mesh_fine_mm, f0_tolerance=f0_tolerance,
        rl_floor_db=rl_floor_db, max_step_pct=max_step_pct,
        fine_epsilon=fine_epsilon, sandbox=sandbox, board=board)
    if not result.get("ok"):
        return result
    return annotate_contract("self_verify", result)
