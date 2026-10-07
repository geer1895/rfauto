"""create_run/create_run_async/poll_job/cancel_job/wait_job/get_metrics（任务注册表单写约束族）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import _silence_pyaedt_screen_logs as _silence_pyaedt_screen_logs
from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import ok_envelope

# ─── 4. create_run ─────────────────────────────────────────────────────────

@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def create_run(
    recipe_path: str,
    adapter: str = "fake",
) -> dict[str, Any]:
    """提交仿真任务（jobs 域）：配方+适配器 → 同步求解并返回 run_id。

    副作用：创建 run 目录、写入 meta.json、登记 SQLite 索引并求解一点；
    长仿真用 create_run_async（本工具阻塞至终态）。配方缺失/adapter
    未知 → ok=False errors 如实。时序：终态后可 get_metrics 消费。

    Args:
        recipe_path: 配方文件路径（YAML 格式）
        adapter: 适配器名称，"fake"（默认）或 "hfss"

    Returns:
        dict: {ok: bool, run_id: str, run_dir: str, metrics: dict, cost: float}
    """
    _silence_pyaedt_screen_logs()
    from rfauto.service.api import run_once
    result = run_once(recipe_path, adapter_name=adapter)
    return result


# ─── 5. create_run_async ────────────────────────────────────────────────────

@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def create_run_async(
    recipe_path: str,
    adapter: str = "fake",
) -> dict[str, Any]:
    """异步提交仿真任务（jobs 域）：配方+适配器 → 立即返回 job_id。

    副作用：后台线程执行 create_run 的全部动作（创建 run 目录、写
    meta.json、登记 SQLite 索引）；适用于 HFSS 等长仿真，同步阻塞面走
    create_run。提交失败 → ok=False errors 如实。时序：提交后用
    poll_job(job_id) 轮询、wait_job 阻塞等终态。

    Args:
        recipe_path: 配方文件路径（YAML 格式）
        adapter: 适配器名称，"fake"（默认）或 "hfss"

    Returns:
        dict: {ok: bool, job_id: str, state: str}
    """
    _silence_pyaedt_screen_logs()
    from rfauto.service.api import run_once_async
    return run_once_async(recipe_path, adapter_name=adapter)


# ─── 6. poll_job ───────────────────────────────────────────────────────────

@mcp.tool
def poll_job(job_id: str) -> dict[str, Any]:
    """任务状态轮询（jobs 域）：job_id → state/进度/指标快照（只读）。

    无副作用，可安全调用；与 CLI rfauto jobs status 读同一份持久化状态，
    不用于提交任务（走 create_run_async）。未知 job_id → ok=False 如实。
    只读无时序约束。

    Args:
        job_id: 任务 ID（即 run_id）

    Returns:
        dict: {ok: bool, job_id: str, state: str, progress_pct: float, message: str, metrics: dict}
    """
    from rfauto.service.api import poll_job as _poll_job
    return _poll_job(job_id)

@mcp.tool
def cancel_job(job_id: str) -> dict[str, Any]:
    """协作取消长任务（jobs 域）：job_id → 置 cancelled 协作检查点退出。

    DP-14 A1 透传 JobRegistry.cancel；硬杀求解进程不支持——运行中的仿真
    在下一个协作检查点退出，cancel 后 poll_job 终态=cancelled。未知
    job_id → ok=False 如实。时序：取消后勿复用同 job_id。

    Args:
        job_id: create_run_async 返回的任务 id

    Returns:
        dict: {ok, job_id, status, ...}
    """
    from rfauto.service.job_registry import get_job_registry
    reg = get_job_registry()
    out = reg.cancel(job_id)
    if out is None:
        return {"ok": False, "error": f"未知 job_id: {job_id}"}
    return ok_envelope(**out)


@mcp.tool
def wait_job(job_id: str, timeout_s: float = 600.0,
             poll_interval_s: float = 5.0) -> dict[str, Any]:
    """阻塞等待长任务终态并流式回报进度（DP-14 A1：progressToken 语义）。

    fastmcp 以 progress 通知回报 0..1 进度（客户端收通知即重置超时时钟，
    2025-06 规范语义）；终态前每 poll_interval_s 轮询一次，超 timeout_s
    返回 ok=False+最后已知状态（不抛异常）。无副作用（只读轮询）。

    Args:
        job_id: create_run_async 返回的任务 id
        timeout_s: 最长等待秒数（缺省 600）
        poll_interval_s: 轮询间隔秒数（缺省 5）

    Returns:
        dict: {ok, job_id, status, progress, ...}（终态或超时快照）
    """
    import time as _time

    from rfauto.service.api import poll_job as _poll_job

    deadline = _time.monotonic() + float(timeout_s)
    last: dict[str, Any] = {}
    while True:
        last = _poll_job(job_id)
        status = str(last.get("status", ""))
        if status in ("completed", "failed", "cancelled"):
            return {**last, "ok": True, "wait": "terminal"}
        if _time.monotonic() >= deadline:
            return {"ok": False, "job_id": job_id, "status": status or "unknown",
                    "wait": "timeout", "error": f"wait_job 超时 {timeout_s}s"}
        _time.sleep(float(poll_interval_s))



# ─── 7. get_metrics ─────────────────────────────────────────────────────────

@mcp.tool
def get_metrics(run_id: str) -> dict[str, Any]:
    """读取 run 指标（runs 域）：run_id → 指标/成本/诊断信封。

    无副作用，可安全调用；不用于修改 run 状态。run 不存在 → ok=False
    如实报错不猜测。只读无时序约束。

    Args:
        run_id: 运行 ID（runs/ 目录名）

    Returns:
        dict: {ok: bool, data: {run_id, metrics, cost, ...}}；run 不存在
        → ok=False
    """
    from rfauto.service.api import get_metrics as _get_metrics
    return _get_metrics(run_id)
