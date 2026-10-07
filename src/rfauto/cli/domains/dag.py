"""dag 子应用——DAG 执行基座两叶（VI-4/SN-1 接线，Phase2 W2-A）。

零逻辑转发 pipeline/dag_runner（规则 4 薄壳；断点续跑/CAS/watchdog/#261
互斥/failure_policy 全在执行基座，SP 席判"全仓最强执行资产不可见"）：
  rfauto dag run <plan.json> --run-dir <dir> [--json]   执行 rfauto-dag-v1 计划
  rfauto dag status <run_dir> [--json]                  读状态期刊出节点态摘要

v1 内建 subprocess 执行器（规格 VI-4）：节点 cmd 声明性命令串经 shlex 分词
subprocess.run（env 继承、cwd=节点工作目录、超时=budget.timeout_s——超时按
#145 Abort 语义判废走重试阶梯；声明产物缺失按 inconclusive_when 判，QW-7
途径②在基座）。**零数值面**（铁律 7）：本模块不产生任何物理数字，只编排。

互斥：solve 类节点过 default_solve_lock_path()（#261 家族机器互斥，基座
内建）；run 实例锁 DAG_RUN_LOCK_NAME 同 run_dir 单实例（占即拒，rc≠0，
信封 errors 含锁路径 lock 字样）。MCP 不加（规格明文：CLI 先行，agent
编排走 run_campaign 即可）。

注册=域内自注册（stats/firmware/teaching 同款：模块级 add_typer，main.py
只 re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
`dag` 域（#df6① 冲突检查 2026-10-05：全 CLI 树零撞名）。
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

dag_app = typer.Typer(help="DAG 执行基座（断点续跑/CAS/watchdog/#261 互斥；pipeline.dag_runner）")
app.add_typer(dag_app, name="dag")

#: run 实例锁占即拒的缺省等待（0=单次尝试；负数=无限等交由 --lock-wait-s 显式开）。
_DEFAULT_LOCK_WAIT_S = 0.0


# ─── v1 内建 subprocess 执行器（规格 VI-4）───────────────────────────────────

def _subprocess_executor(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """节点 cmd → shlex 分词 subprocess.run（ExecutorFn 契约）。

    - env 继承（os.environ 显式拷贝）；cwd=节点工作目录（产物相对落点）；
    - 超时=budget.timeout_s：超时抛 NodeAbortedError（#145 Abort 判废语义，
      重试/escalation 由基座 _run_node 循环承担）；
    - 返回 ok=rc==0；声明产物缺失的判定不在本执行器（基座按
      inconclusive_when 判，QW-7 途径②）——outputs 恒空、由节点声明面供给。
    """
    from rfauto.pipeline.dag_runner import NodeAbortedError

    def _kill_process_tree(proc: subprocess.Popen) -> None:
        """超时/异常路径整树终止（#157 家法：防引擎孙进程孤儿占锁）。"""
        import contextlib
        import sys
        with contextlib.suppress(Exception):
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, timeout=10)
            else:
                import os as _os
                import signal
                _os.killpg(_os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(Exception):
            proc.kill()

    cmd = str(node.get("cmd") or "")
    if not cmd.strip():
        return {"ok": False, "outputs": [], "wall_s": 0.0,
                "message": "节点无 cmd 声明（v1 subprocess 执行器要求 cmd）"}
    work_dir = Path(ctx.get("work_dir") or ".")
    work_dir.mkdir(parents=True, exist_ok=True)
    budget = ctx.get("budget") or node.get("budget") or {}
    raw_timeout = budget.get("timeout_s")
    # #364④ 家法：数值可达 0 的面禁 `or` 缺省——0.0=无超时是合法显式语义
    try:
        timeout_s = float(raw_timeout) if raw_timeout is not None else 0.0
    except (TypeError, ValueError):
        timeout_s = 0.0
    argv = shlex.split(cmd)
    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv, cwd=str(work_dir), env=os.environ.copy(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        return {"ok": False, "outputs": [], "wall_s": time.monotonic() - t0,
                "message": f"cmd 不可执行（argv 首令不在 PATH）: {argv[:1]}"}
    try:
        _out, err = proc.communicate(
            timeout=timeout_s if timeout_s > 0 else None)
    except subprocess.TimeoutExpired:
        # #157/#265 家法：树杀（run 只杀直接子进程，引擎/求解器孙进程变孤儿
        # 占锁占 license 的本仓实证痛点）——Windows taskkill /T；POSIX 走组杀。
        _kill_process_tree(proc)
        raise NodeAbortedError(
            f"超时判废（budget.timeout_s={timeout_s:g}s，#145 Abort 语义）") from None
    except BaseException:
        _kill_process_tree(proc)
        raise
    wall = time.monotonic() - t0
    tail_err = (err or "").strip().splitlines()[-2:]
    msg = f"rc={proc.returncode}"
    if tail_err:
        msg += " | " + " / ".join(seg[-200:] for seg in tail_err)
    return {"ok": proc.returncode == 0, "outputs": [], "wall_s": wall,
            "message": msg}


# ─── 服务面（JSON 进出，CLI/MCP 同源薄壳；信封走构造器）───────────────────────

def dag_run(plan_path: str, run_dir: str, *, cache_dir: str | None = None,
            solve_lock: str | None = None,
            lock_wait_s: float = _DEFAULT_LOCK_WAIT_S) -> dict[str, Any]:
    """执行 rfauto-dag-v1 计划（断点续跑内嵌；JSON 信封出）。

    互斥：run 实例锁占即拒（lock_wait_s=0；被拒信封 errors 含锁路径，
    CLI rc≠0）。solve 类节点过 #261 机器互斥（缺省 runs/.oe_collect.lock）。
    """
    from rfauto.core.compose.dag_schema import NODE_KINDS
    from rfauto.pipeline.dag_runner import (
        default_solve_lock_path,
        run_dag,
    )
    from rfauto.service.envelope import error_envelope, ok_envelope

    p = Path(plan_path)
    if not p.is_file():
        return error_envelope([f"DAG 计划不存在: {p}"])
    try:
        plan_d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return error_envelope([f"DAG 计划不可读: {exc}"])

    run_log = Path(run_dir) / "dag.log"

    def _log(msg: str) -> None:
        # 观测面 best-effort（#105）：日志写失败不阻塞执行主路径
        try:
            with open(run_log, "a", encoding="utf-8") as f:
                f.write(f"{msg}\n")
        except OSError:
            pass

    executors = {kind: _subprocess_executor for kind in NODE_KINDS}
    result = run_dag(
        plan_d, Path(run_dir), executors,
        cache_dir=cache_dir,
        solve_lock_path=(Path(solve_lock) if solve_lock
                         else default_solve_lock_path()),
        lock_max_wait_s=float(lock_wait_s),
        log=_log)
    extra = {k: v for k, v in result.items() if k not in ("ok", "errors")}
    if not result.get("ok"):
        errs = list(result.get("errors") or [])
        if not errs:
            errs = [f"DAG 执行未完成: verdict={result.get('verdict', '?')}"]
        return error_envelope(errs, **extra)
    return ok_envelope(**extra)


def dag_status(run_dir: str) -> dict[str, Any]:
    """读 run_dir 状态期刊（dag.state.json）出节点态摘要（JSON 信封出）。"""
    from rfauto.pipeline.dag_runner import DAG_STATE_FILE
    from rfauto.service.envelope import error_envelope, ok_envelope

    path = Path(run_dir) / DAG_STATE_FILE
    if not path.is_file():
        return error_envelope(
            [f"状态期刊不存在: {path}（先 dag run --run-dir {run_dir}）"])
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return error_envelope([f"状态期刊不可读: {exc}"])
    if not isinstance(state, dict) or not isinstance(state.get("nodes"), dict):
        return error_envelope([f"状态期刊形态非法（缺 nodes dict）: {path}"])
    nodes = []
    for nid, entry in state["nodes"].items():
        entry = entry if isinstance(entry, dict) else {}
        notes = [str(n) for n in (entry.get("notes") or [])]
        nodes.append({
            "node_id": str(nid),
            "status": str(entry.get("status", "")),
            "key": str(entry.get("key", "")),
            "outputs": [str(o) for o in (entry.get("outputs") or [])],
            "source": str(entry.get("source", "")),
            "has_manifest": bool(entry.get("has_manifest", False)),
            "first_note": notes[0] if notes else "",
        })
    return ok_envelope(
        run_dir=str(run_dir), state_path=str(path),
        schema=str(state.get("schema", "")),
        verdict=str(state.get("verdict", "")),
        n_hit=state.get("n_hit"), n_recompute=state.get("n_recompute"),
        inconclusive_count=state.get("inconclusive_count"),
        skipped_count=state.get("skipped_count"),
        updated_at=str(state.get("updated_at", "")),
        nodes=nodes)


# ─── CLI 薄壳两叶 ────────────────────────────────────────────────────────────

@dag_app.command("run")
def dag_run_cmd(
    plan: str = typer.Argument(..., help="rfauto-dag-v1 计划 JSON（nodes 列表）"),
    run_dir: str = typer.Option(..., "--run-dir",
                                help="运行目录（期刊/产物/锁落点）"),
    cache_dir: str = typer.Option(None, "--cache-dir",
                                  help="跨 run CAS 索引目录（零拷贝缓存）"),
    solve_lock: str = typer.Option(None, "--solve-lock",
                                   help="#261 机器互斥锁路径（缺省 runs 家族锁）"),
    lock_wait_s: float = typer.Option(
        _DEFAULT_LOCK_WAIT_S, "--lock-wait-s",
        help="run 实例锁等待秒数：0 占即拒，负数无限等"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """执行 DAG 计划（断点续跑内嵌；solve 节点过 #261 机器互斥）。"""
    result = dag_run(plan, run_dir, cache_dir=cache_dir, solve_lock=solve_lock,
                     lock_wait_s=lock_wait_s)
    _emit(result, "DAG 执行失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ DAG 完成[/green]  verdict={result.get('verdict')}"
                  f"  hit={result.get('n_hit')}"
                  f"  recompute={result.get('n_recompute')}")
    for nid, st in (result.get("statuses") or {}).items():
        color = {"done": "green", "partial": "green", "failed": "red",
                 "aborted": "red", "skipped": "dim"}.get(str(st), "yellow")
        console.print(f"  [{color}]{st:<12}[/{color}] {nid}")
    console.print(f"  期刊: {result.get('state_path')}")
    raise typer.Exit(code=0)


@dag_app.command("status")
def dag_status_cmd(
    run_dir: str = typer.Argument(..., help="运行目录（含 dag.state.json）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """状态期刊节点态摘要（与 journal 一致；done/failed/inconclusive 等）。"""
    result = dag_status(run_dir)
    _emit(result, "状态期刊读取失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[bold]{result['run_dir']}[/bold]  verdict={result.get('verdict')}"
                  f"  hit={result.get('n_hit')}"
                  f"  recompute={result.get('n_recompute')}")
    table = Table(title="DAG 节点态摘要（dag.state.json）")
    for col in ("node_id", "status", "key", "outputs", "source"):
        table.add_column(col, style="cyan" if col == "node_id" else None)
    for n in result.get("nodes") or []:
        table.add_row(n["node_id"], n["status"], n["key"][:12],
                      ",".join(n["outputs"]), n["source"])
    console.print(table)
    raise typer.Exit(code=0)
