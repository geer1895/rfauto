"""api.tuning —— 调优作业链（start_tune·multi·async/run_once_async/poll_job）。

自 api.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体逐字节搬迁。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.core.state import generate_job_id
from rfauto.service.envelope import ok_envelope

from .run_core import run_once


def start_tune(recipe_path: str | Path, *, adapter_name: str = "fake",
               max_trials: int = 60, study_name: str | None = None,
               max_wall_s: float | None = None,
               adapter_kwargs: dict[str, Any] | None = None,
               sampler: str = "tpe",
               seed: int | None = None,
               pruner: str = "none",
               on_trial: Any = None,
               warm_start_registry: bool | None = None) -> dict[str, Any]:
    """启动优化外环（Optuna，SQLite 持久化，断点续跑）。

    同步运行优化循环，返回最佳结果。
    若同一 study_name 已有历史 trial，自动从已有结果继续采样。

    Args:
        recipe_path: 配方文件路径
        adapter_name: "fake" | "hfss"
        max_trials: 最大试验次数
        study_name: 自定义 study 名称（默认从配方生成）
        max_wall_s: 总超时（秒）
        adapter_kwargs: 额外适配器构造参数（如 n_ports=3）
        sampler: "tpe"（默认）| "cmaes" | "gp"（ME-12 起 GPSampler 转正，Optuna 5.0）
        seed: 采样器随机种子（P2⑦；None=沿用 optimizer.SAMPLER_SEED 缺省）
        pruner: 多保真裁剪器（ME-13）："none"（默认，行为不变）| "asha" |
            "hyperband"——Phase1 低保真差配方早停，语义见 optimizer.run_optimization
        on_trial: 逐 trial 完成回调 ``f(study, trial)``（SN-9，--watch 播报挂点；
            None=不加键行为不变，条件透传 #df6③）
        warm_start_registry: 代理模型注册表 warm-start 三态开关（RB-ML-1，
            #277 bool|None 形态；None=env/配置裁决，缺省关=行为不变）。开时
            经 surrogate_registry_champion_points 解析 champion 近优点并入
            warm_start 通道（零内核侵入）；结果带 registry_warm_start 键。
    """
    from rfauto.optimization.optimizer import run_optimization
    from rfauto.service.surrogate_registry_service import (
        resolve_warm_start_registry_flag,
    )

    seed_kw: dict[str, Any] = {} if seed is None else {"seed": int(seed)}
    cb_kw: dict[str, Any] = {"callbacks": [on_trial]} if on_trial else {}
    reg_on = resolve_warm_start_registry_flag(warm_start_registry)
    if reg_on:
        # RB-ML-1 消费面①：champion 近优点在战役启动期解析并入 warm_start
        # 通道（study 建好后、首 trial 前 enqueue——既有 stage-1 语义），
        # 解析失败/stale/blob 损坏 best-effort 降级冷启动不阻塞（#105）。
        from rfauto.service.surrogate_registry_service import (
            run_optimization_with_registry_warm_start,
        )

        result = run_optimization_with_registry_warm_start(
            recipe_path,
            adapter_name=adapter_name,
            max_trials=max_trials,
            study_name=study_name,
            max_wall_s=max_wall_s,
            adapter_kwargs=adapter_kwargs,
            sampler=sampler,
            seed=seed,
            warm_start_registry=True,
            pruner=pruner,
            callbacks=on_trial,
        )
    else:
        result = run_optimization(
            recipe_path,
            adapter_name=adapter_name,
            max_trials=max_trials,
            study_name=study_name,
            max_wall_s=max_wall_s,
            adapter_kwargs=adapter_kwargs,
            sampler=sampler,
            pruner=pruner,
            **seed_kw,
            **cb_kw,
        )
    if not result.get("ok"):
        return result
    envelope = ok_envelope(
        job_id=result.get("run_id", ""),
        run_id=result.get("run_id", ""),
        study_name=result.get("study_name", ""),
        best_params=result.get("best_params", {}),
        best_cost=result.get("best_cost"),
        best_metrics=result.get("best_metrics", {}),
        trials_completed=result.get("trials_completed", 0),
        trials_pruned=result.get("trials_pruned", 0),
        trials_total=result.get("trials_total", 0),
        elapsed_s=result.get("elapsed_s", 0),
        existing_trials=result.get("existing_trials", 0),
    )
    if result.get("registry_warm_start") is not None:
        # RB-ML-1：注册表 warm-start 解析回执透出（开关开时才有键，
        # 缺省信封键集不变）
        envelope["registry_warm_start"] = result["registry_warm_start"]
    return envelope




def start_tune_multi(
    recipe_path: str | Path,
    *,
    adapter_name: str = "fake",
    n_gen: int = 20,
    pop_size: int = 12,
    seed: int = 42,
) -> dict[str, Any]:
    """多目标优化（NSGA-II，Pareto 前沿）——计划内缺口 2 的服务入口。

    验收口径："双目标出 Pareto 前沿"。目标向量取每个 objective 的违约量。
    """
    from rfauto.optimization.optimizer import run_multi_optimization
    return run_multi_optimization(
        recipe_path,
        adapter_name=adapter_name,
        n_gen=n_gen,
        pop_size=pop_size,
        seed=seed,
    )




def run_once_async(recipe_path: str | Path, *, adapter_name: str = "fake") -> dict[str, Any]:
    """异步单次仿真——立即返回 job_id，后台执行。

    与 run_once 相同逻辑，后台线程执行；适用于 HFSS 等长时间仿真。
    job_id（job_ 前缀）由进程内 JobRegistry 关联到后台任务的真实 run_id，
    poll_job 优先查注册表、未命中回落磁盘 meta.json。

    线程为非 daemon：进程退出前会等待当前 run 结束，避免带着 AEDT 会话
    被强杀（代价是异常卡死的 run 会阻塞进程退出，可接受）。

    Args:
        recipe_path: 配方文件路径
        adapter_name: "fake" 或 "hfss"

    Returns:
        dict with keys: ok, job_id, state
    """
    import threading

    from rfauto.service.job_registry import get_job_registry, get_write_lock

    registry = get_job_registry()
    write_lock = get_write_lock()
    job_id = generate_job_id()

    def _run_in_background():
        import traceback
        try:
            # 单写锁（缺口 1）：并发 hfss job 在此排队，避免同时开多个
            # AEDT 会话抢 license。无限等待（求解本身可达小时级）。
            if not write_lock.acquire(job_id):
                registry.fail(job_id, error="未获得执行锁（单写互斥）")
                return
            try:
                # jobs cancel 语义：获锁后（真正开始执行前）检查取消——
                # 排队中的 job 在 cancel() 时已置 cancelled 终态，这里直接跳过
                if not registry.mark_started(job_id):
                    return
                # SN-10：run_once 阶段播报直写注册表（poll_job 消费）
                result = run_once(
                    recipe_path, adapter_name=adapter_name,
                    progress_cb=lambda pct, stage: registry.set_progress(
                        job_id, pct, stage))
            finally:
                write_lock.release(job_id)
            run_id = result.get("run_id", "")
            if registry.is_cancelled(job_id):
                # 执行中收到取消：AEDT 求解不可安全中断，跑完后按取消丢弃结果
                registry.mark_cancelled(job_id, run_id=run_id)
                return
            if result.get("ok"):
                registry.finish(job_id, run_id=run_id, result=result)
            else:
                registry.fail(job_id, run_id=run_id, result=result)
        except Exception as e:
            # 后台线程的异常无处抛出，必须带堆栈完整落进注册表供排查
            write_lock.release(job_id)
            registry.fail(job_id, error=f"{e}\n{traceback.format_exc()}")

    thread = threading.Thread(target=_run_in_background, daemon=False, name=f"rfauto-job-{job_id}")
    registry.create(job_id, thread=thread)
    thread.start()

    return ok_envelope(
        job_id=job_id,
        state="running",
        message="仿真已在后台启动，使用 poll_job 查询状态",
    )


def start_tune_async(recipe_path: str | Path, *, adapter_name: str = "fake",
                     max_trials: int = 60, study_name: str | None = None,
                     max_wall_s: float | None = None,
                     sampler: str = "tpe", seed: int | None = None,
                     pruner: str = "none") -> dict[str, Any]:
    """异步优化外环（SN-9，2026-10-05 W1-D）——立即返回 job_id，后台执行 start_tune。

    与 run_once_async 同一进程内 JobRegistry + 单写锁范式（run_once_async:931
    范式复用裁决=可复用，故实装而非改 docstring）：job_id 经 poll_job/jobs
    status 轮询，终态 done 时 result 收 start_tune 全量信封（best_params/
    best_cost/best_metrics/trials_*）。单写锁覆盖整个优化循环（与 run_once
    的 AEDT 会话互斥同源：优化含真机求解序列，两个优化并发会争抢同一
    license/互斥面）。

    线程为非 daemon：进程退出前等待当前优化结束（同 run_once_async 语义）。
    仅单目标路径（start_tune）；多目标/多保真/代理寻优后台化另立。
    """
    import threading

    from rfauto.service.job_registry import get_job_registry, get_write_lock

    registry = get_job_registry()
    write_lock = get_write_lock()
    job_id = generate_job_id()

    def _run_in_background():
        import traceback
        try:
            if not write_lock.acquire(job_id):
                registry.fail(job_id, error="未获得执行锁（单写互斥）")
                return
            try:
                # jobs cancel 语义：获锁后（真正开始执行前）检查取消
                if not registry.mark_started(job_id):
                    return

                # SN-10：trial 级真实进度（完成 trial 数/max_trials 线性映射到
                # 15..95）。on_trial 即 optuna study callback，签名 (study, trial)；
                # 包装后不影响 start_tune 主路径（SN-9 --watch 同挂点语义）。
                def _tune_progress(study: Any, trial: Any) -> None:
                    done = getattr(_tune_progress, "n", 0) + 1
                    _tune_progress.n = done
                    pct = (15.0 + 80.0 * min(1.0, done / float(max_trials))
                           if max_trials > 0 else 95.0)
                    registry.set_progress(job_id, pct, f"trial {done}/{max_trials}")

                registry.set_progress(job_id, 10.0, "compose")
                result = start_tune(
                    recipe_path, adapter_name=adapter_name,
                    max_trials=max_trials, study_name=study_name,
                    max_wall_s=max_wall_s, sampler=sampler,
                    seed=seed, pruner=pruner, on_trial=_tune_progress)
            finally:
                write_lock.release(job_id)
            run_id = result.get("run_id", "")
            if registry.is_cancelled(job_id):
                # 执行中收到取消（run_once_async:984 同款）：优化循环已整体跑完
                # 不可回退，按取消语义丢弃结果落账（不以 done 假终态收尾）
                registry.mark_cancelled(job_id, run_id=run_id)
                return
            if result.get("ok"):
                registry.finish(job_id, run_id=run_id, result=result)
            else:
                registry.fail(job_id, run_id=run_id, result=result)
        except Exception as e:
            # 后台线程的异常无处抛出，必须带堆栈完整落进注册表供排查
            write_lock.release(job_id)
            registry.fail(job_id, error=f"{e}\n{traceback.format_exc()}")

    thread = threading.Thread(target=_run_in_background, daemon=False,
                              name=f"rfauto-job-{job_id}")
    registry.create(job_id, thread=thread)
    thread.start()

    return ok_envelope(
        job_id=job_id,
        state="running",
        message="优化已在后台启动，使用 poll_job 查询状态",
    )


def poll_job(job_id: str) -> dict[str, Any]:
    """轮询任务状态。

    查询顺序：
    1. 进程内 JobRegistry（run_once_async 发放的 job_id，状态实时）
    2. 磁盘 runs/<job_id>/meta.json（直接以 run_id 查询历史 run，含跨进程）
    均未命中时返回 state=unknown（ok 仍为 True，与历史行为兼容）。
    """
    from rfauto.service.job_registry import get_job_registry

    job = get_job_registry().get(job_id)
    if job is not None:
        state = job["state"]
        result = job.get("result") or {}
        terminal = state in ("done", "failed", "cancelled")
        message = {
            "failed": job.get("error", ""),
            "cancelled": "任务已取消",
        }.get(state, f"job 状态: {state}")
        # SN-10（W6-A）：注册表带阶段进度时透传真实值；终态=100；无进度
        # 信息（旧路径/未播报）保持 0/100 二值缺省，不臆造
        pct = job.get("progress_pct") or 0.0
        stage = job.get("stage") or ""
        if terminal:
            pct = 100.0
        elif pct <= 0.0:
            pct = 0.0
        return ok_envelope(
            job_id=job_id,
            run_id=job.get("run_id", ""),
            state=state,
            progress_pct=float(pct),
            stage=stage,
            message=message,
            metrics=result.get("metrics", {}),
        )

    meta_path = Path("runs") / job_id / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return ok_envelope(
            job_id=job_id,
            state=meta.get("status", "unknown"),
            progress_pct=100.0 if meta.get("status") == "done" else 0.0,
            message=f"优化完成 ({meta.get('study_name', '')})",
            metrics=meta.get("metrics", {}),
        )
    return ok_envelope(
        job_id=job_id,
        state="unknown",
        progress_pct=0.0,
        message=f"未找到 run: {job_id}",
    )
