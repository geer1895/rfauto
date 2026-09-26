"""DP-9 P2：DAG 执行器测试（断点续跑/#145 三分类/#261 互斥，全合成零真机）。

覆盖判据 ①（#157 kill 后零重算，子进程 os._exit 实证）、②（确定性）、
③（篡改传导）、④（期刊损坏/半产物一律重算）、#145 接线（Abort 判废
重试/竞态接受/超预算 PARTIAL）、#261（solve 派发机器互斥缺省串行）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rfauto.pipeline.dag_runner import (
    DAG_RUN_LOCK_NAME,
    DAG_STATE_FILE,
    MESH_TIERS,
    SAFETY_BUDGET,
    DagRunner,
    NodeAbortedError,
    RaceCompleted,
    SolveMachineMutex,
    acquire_lock,
    escalated_budget,
    release_lock,
    run_dag,
)

_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_cache_env(monkeypatch):
    """隔离 RFAUTO_CACHE（防环境泄漏改变索引模式语义；#139 钉通道精神）。"""
    monkeypatch.delenv("RFAUTO_CACHE", raising=False)


# ─── 合成计划与确定性执行器 ──────────────────────────────────────────────────

_EXT = {"render": "rendered.txt", "solve": "sparams.csv",
        "postprocess": "post.json", "judge": "report.json"}
_OUTPUT_STEM = "OUT:{node_id}:v1\n"


def _plan_chain(steps: list[tuple[str, str]]) -> dict:
    """线性链计划（r/s 交替；render 节点带 inputs 文件与参数面）。"""
    nodes: list[dict] = []
    prev = ""
    for node_id, kind in steps:
        node = {
            "node_id": node_id, "kind": kind,
            "depends_on": [prev] if prev else [],
            "inputs": {"files": ["inputs/design.txt"] if kind == "render"
                       else [], "params": {"w": 0.5} if kind == "render" else {}},
            "outputs": [f"{node_id}.{_EXT[kind]}"],
            "cmd": f"{kind} {node_id}",
            "budget": ({"timeout_s": 10, "mesh_tier": "coarse"}
                       if kind == "render" else {"timeout_s": 10, "nrts": 100}),
            "retries": 0,
        }
        nodes.append(node)
        prev = node_id
    return {"nodes": nodes}


def _write_output(node: dict, ctx: dict) -> str:
    """确定性节点产物（同 node_id 同字节——判据 ② 的合成保证）。"""
    rel = f"{node['node_id']}.{_EXT[node['kind']]}"
    work = Path(ctx["work_dir"])
    work.mkdir(parents=True, exist_ok=True)
    (work / rel).write_text(_OUTPUT_STEM.format(node_id=node["node_id"]),
                            encoding="utf-8")
    return rel


def _chain_executors(calls: list[str], budgets: list[float] | None = None,
                     kill_at: str = "") -> dict:
    def _ex(node: dict, ctx: dict) -> dict:
        if kill_at and node["node_id"] == kill_at:
            os._exit(157)                       # #157 整树无声消失模拟
        calls.append(node["node_id"])
        if budgets is not None and node["kind"] == "render":
            budgets.append(float(ctx["budget"].get("timeout_s") or 0))
        rel = _write_output(node, ctx)
        return {"ok": True, "outputs": [rel], "wall_s": 0.01}

    return {"render": _ex, "solve": _ex,
            "postprocess": _ex, "judge": _ex}


def _seed_inputs(run_dir: Path) -> None:
    (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs" / "design.txt").write_text("DESIGN-v1\n",
                                                   encoding="utf-8")


_CHAIN = [("r1", "render"), ("s1", "solve"), ("r2", "render"),
          ("s2", "solve"), ("r3", "render"), ("s3", "solve"),
          ("r4", "render"), ("s4", "solve"), ("r5", "render"),
          ("s5", "solve")]


def _run(tmp_path: Path, run_dir: Path, executors: dict, cache_dir: Path,
         solve_lock: Path | None = None, log=None) -> dict:
    return run_dag(
        _plan_chain(_CHAIN), run_dir, executors, cache_dir=cache_dir,
        engine_version="fake-1", solve_lock_path=solve_lock,
        log=log or print)  # DBG-TEMP


# ─── 基本执行与判据 ②（确定性）───────────────────────────────────────────────

def test_run_complete_and_deterministic_outputs(tmp_path) -> None:
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    calls: list[str] = []
    res = _run(tmp_path, run_dir, _chain_executors(calls), tmp_path / "cache",
               solve_lock=tmp_path / "solve.lock")
    assert res["ok"] is True and res["verdict"] == "COMPLETE"
    assert res["n_hit"] == 0 and res["n_recompute"] == 10
    assert calls == [nid for nid, _ in _CHAIN]
    # 节点工作目录 + 产物清单（per-node dag.artifact.json）
    manifest = run_dir / "r1" / "dag.artifact.json"
    assert manifest.is_file()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["complete"] is True
    assert data["files"][0]["path"] == "r1.rendered.txt"
    # 判据 ②：同参数第二份执行产物逐位同（独立 run_dir）
    run_dir2 = tmp_path / "run2"
    _seed_inputs(run_dir2)
    calls2: list[str] = []
    _run(tmp_path, run_dir2, _chain_executors(calls2), tmp_path / "cache2",
         solve_lock=tmp_path / "solve.lock")
    a = (run_dir / "r1" / "r1.rendered.txt").read_bytes()
    b = (run_dir2 / "r1" / "r1.rendered.txt").read_bytes()
    assert a == b


def test_rerun_completed_nodes_zero_recompute(tmp_path) -> None:
    """判据 ①（进程内版）：第二次 run 已完成节点零重算（N hit/0 recompute）。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    calls: list[str] = []
    _run(tmp_path, run_dir, _chain_executors(calls), tmp_path / "cache",
         solve_lock=tmp_path / "solve.lock")
    n_first = len(calls)
    res2 = _run(tmp_path, run_dir, _chain_executors(calls),
                tmp_path / "cache", solve_lock=tmp_path / "solve.lock")
    assert res2["verdict"] == "COMPLETE"
    assert res2["n_hit"] == 10
    assert res2["n_recompute"] == 0, "已完成节点被重算（断点续跑语义破坏）"
    assert len(calls) == n_first, "执行器被重复调用（零重算破坏）"


# ─── 判据 ①：#157 子进程 kill → 重启零重算 ──────────────────────────────────

_CHILD_TEMPLATE = '''# -*- coding: utf-8 -*-
"""DP-9 kill 子进程：跑到 {kill} 时 os._exit(157)（#157 整树无声消失模拟）。"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, {src!r})
from rfauto.pipeline.dag_runner import run_dag

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
run_dir = Path(sys.argv[2])
cache_dir = Path(sys.argv[3])
solve_lock = Path(sys.argv[4])
KILL = {kill!r}
EXT = {ext!r}


def _write_output(node, ctx):
    rel = node["node_id"] + "." + EXT[node["kind"]]
    wd = Path(ctx["work_dir"])
    wd.mkdir(parents=True, exist_ok=True)
    (wd / rel).write_text({stem!r}.format(node_id=node["node_id"]),
                          encoding="utf-8")
    return rel


def _ex(node, ctx):
    if node["node_id"] == KILL:
        sys.stdout.flush()
        os._exit(157)
    rel = _write_output(node, ctx)
    return {{"ok": True, "outputs": [rel], "wall_s": 0.01}}


executors = {{k: _ex for k in ("render", "solve", "postprocess", "judge")}}
res = run_dag(plan, run_dir, executors, cache_dir=cache_dir,
              engine_version="fake-1", solve_lock_path=solve_lock)
print("UNREACHABLE", res)
'''


def test_kill_parent_then_resume_zero_recompute(tmp_path) -> None:
    """判据 ①（#157 实证版）：子进程跑到 s2 时整树硬死；重启后已完成 3 节点
    零重算（3 hit / 7 recompute），陈锁自动接管。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    cache_dir = tmp_path / "cache"
    solve_lock = tmp_path / "solve.lock"
    child = tmp_path / "kill_child.py"
    child.write_text(_CHILD_TEMPLATE.format(
        kill="s2", src=str(_REPO / "src"), ext=_EXT,
        stem=_OUTPUT_STEM), encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan_chain(_CHAIN)), encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO / "src") + os.pathsep + env.get(
        "PYTHONPATH", "")
    env.pop("RFAUTO_CACHE", None)
    proc = subprocess.run(
        [sys.executable, str(child), str(plan_path), str(run_dir),
         str(cache_dir), str(solve_lock)],
        capture_output=True, text=True, timeout=300, env=env)
    assert proc.returncode == 157, (
        f"子进程未按预期硬死 rc={proc.returncode} stderr={proc.stderr[-500:]}")

    # 死树现场：3 节点已落期刊 done（期刊 JSON sort_keys 落盘，集合比对），
    # 运行锁残留（持有者已死）
    state = json.loads((run_dir / DAG_STATE_FILE).read_text(encoding="utf-8"))
    assert {nid for nid, e in state["nodes"].items()
            if e["status"] == "done"} == {"r1", "s1", "r2"}
    assert (run_dir / DAG_RUN_LOCK_NAME).is_file()

    calls: list[str] = []
    res = _run(tmp_path, run_dir, _chain_executors(calls), cache_dir,
               solve_lock=solve_lock)
    assert res["verdict"] == "COMPLETE"
    assert res["n_hit"] == 3, f"已完成节点未跳过: {res}"
    assert res["n_recompute"] == 7
    # 已完成节点零重算：r1/s1/r2 不再进执行器
    assert not ({"r1", "s1", "r2"} & set(calls)), calls
    assert set(calls) == {"s2", "r3", "s3", "r4", "s4", "r5", "s5"}
    # 陈锁接管：运行结束后锁不在盘上
    assert not (run_dir / DAG_RUN_LOCK_NAME).exists()


# ─── #145 接线：Abort 判废重试 / 竞态接受 / 超预算 PARTIAL ───────────────────

def test_abort_discard_then_retry_with_budget_escalation(tmp_path) -> None:
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    budgets: list[float] = []
    calls: list[str] = []

    def ex(node: dict, ctx: dict) -> dict:
        calls.append(node["node_id"])
        if node["node_id"] == "r1" and ctx["attempt"] == 0:
            raise NodeAbortedError("watchdog Abort 真打断（模拟）")
        if node["kind"] == "render":
            budgets.append(float(ctx["budget"]["timeout_s"]))
        return {"ok": True, "outputs": [_write_output(node, ctx)],
                "wall_s": 0.01}

    plan = _plan_chain([("r1", "render"), ("s1", "solve")])
    plan["nodes"][0]["retries"] = 1          # 缺省 escalation=budget×1.5
    res = run_dag(plan, run_dir, {"render": ex, "solve": ex,
                                  "postprocess": ex, "judge": ex},
                  cache_dir=tmp_path / "cache", engine_version="fake-1",
                  solve_lock_path=tmp_path / "solve.lock")
    assert res["verdict"] == "COMPLETE"
    assert budgets == [15.0], budgets        # 10s × SAFETY_BUDGET=1.5 档
    state = json.loads((run_dir / DAG_STATE_FILE).read_text(encoding="utf-8"))
    notes = " ".join(state["nodes"]["r1"]["notes"])
    assert "Abort 真打断" in notes


def test_abort_exhausted_fails_and_downstream_aborted(tmp_path) -> None:
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    solve_calls: list[str] = []

    def ex(node: dict, ctx: dict) -> dict:
        if node["kind"] == "solve":
            solve_calls.append(node["node_id"])
            raise NodeAbortedError("Abort 真打断")
        return {"ok": True, "outputs": [_write_output(node, ctx)],
                "wall_s": 0.01}

    plan = _plan_chain([("r1", "render"), ("s1", "solve")])
    plan["nodes"][1]["retries"] = 1
    res = run_dag(plan, run_dir, {"render": ex, "solve": ex,
                                  "postprocess": ex, "judge": ex},
                  cache_dir=tmp_path / "cache", engine_version="fake-1",
                  solve_lock_path=tmp_path / "solve.lock")
    assert res["verdict"] == "ABORTED"
    assert res["statuses"]["s1"] == "failed"
    # failed→aborted 递归传播（campaign 状态机同语义）；重试=1+1 次派发
    assert solve_calls.count("s1") == 2


def test_race_completed_accepts_real_result(tmp_path) -> None:
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)

    def ex(node: dict, ctx: dict) -> dict:
        rel = _write_output(node, ctx)       # 产物先落盘（竞态=工作已完成）
        # wall 12s：超截止(10s)但未超预算帽(15s)——接受真结果且判 done
        raise RaceCompleted({"ok": True, "outputs": [rel], "wall_s": 12.0})

    res = run_dag(_plan_chain([("r1", "render")]), run_dir,
                  {"render": ex, "solve": ex, "postprocess": ex, "judge": ex},
                  cache_dir=tmp_path / "cache", engine_version="fake-1",
                  solve_lock_path=tmp_path / "solve.lock")
    assert res["verdict"] == "COMPLETE"      # 不丢已算完的数据
    state = json.loads((run_dir / DAG_STATE_FILE).read_text(encoding="utf-8"))
    entry = state["nodes"]["r1"]
    assert entry["status"] == "done"
    notes = " ".join(entry["notes"])
    assert "竞态完成接受真结果" in notes


def test_over_budget_wall_partial_keeps_data_and_downstream_runs(tmp_path):
    """超预算（wall > timeout×1.5）→ PARTIAL 入库不删数据；下游照常执行。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)

    def ex(node: dict, ctx: dict) -> dict:
        return {"ok": True, "outputs": [_write_output(node, ctx)],
                "wall_s": 100.0}                 # ≫ 10×1.5 预算帽

    res = run_dag(_plan_chain([("r1", "render"), ("s1", "solve")]), run_dir,
                  {"render": ex, "solve": ex, "postprocess": ex, "judge": ex},
                  cache_dir=tmp_path / "cache", engine_version="fake-1",
                  solve_lock_path=tmp_path / "solve.lock")
    assert res["verdict"] == "PARTIAL"
    assert res["statuses"] == {"r1": "partial", "s1": "partial"}
    # 数据在库：产物与 manifest 未删
    assert (run_dir / "r1" / "r1.rendered.txt").is_file()
    assert (run_dir / "r1" / "dag.artifact.json").is_file()


def test_escalation_mesh_tier_steps_to_next(tmp_path) -> None:
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    tiers: list[str] = []

    def ex(node: dict, ctx: dict) -> dict:
        if ctx["attempt"] == 0:
            raise NodeAbortedError("Abort 真打断")
        if node["kind"] == "render":
            tiers.append(str(ctx["budget"].get("mesh_tier")))
        return {"ok": True, "outputs": [_write_output(node, ctx)],
                "wall_s": 0.01}

    plan = _plan_chain([("r1", "render")])
    plan["nodes"][0]["retries"] = 1
    plan["nodes"][0]["escalation"] = [{"mesh_tier": "next"}]
    run_dag(plan, run_dir, {"render": ex, "solve": ex, "postprocess": ex,
                            "judge": ex},
            cache_dir=tmp_path / "cache", engine_version="fake-1",
            solve_lock_path=tmp_path / "solve.lock")
    assert tiers == ["mid"]                   # coarse → 下一档 mid
    assert escalated_budget(plan["nodes"][0], 3)["mesh_tier"] == MESH_TIERS[-1]


# ─── 判据 ③：篡改传导 / ④：期刊损坏与半产物 ─────────────────────────────────

def test_tamper_input_file_changes_keys_recursively(tmp_path) -> None:
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    calls: list[str] = []
    _run(tmp_path, run_dir, _chain_executors(calls), tmp_path / "cache",
         solve_lock=tmp_path / "solve.lock")
    n0 = len(calls)
    # 篡改 inputs（render 脚本面字节）→ render 键变 → solve 键经上游键传导变
    design = run_dir / "inputs" / "design.txt"
    design.write_text("DESIGN-v2-TAMPERED\n", encoding="utf-8")
    res = _run(tmp_path, run_dir, _chain_executors(calls),
               tmp_path / "cache", solve_lock=tmp_path / "solve.lock")
    assert res["n_hit"] == 0
    assert res["n_recompute"] == 10, "下游键未随输入篡改传导重算"
    assert len(calls) == n0 + 10


def test_tamper_artifact_recompute_upstream_only(tmp_path) -> None:
    """篡改节点产物字节（键同 digest 败）→ 本节点 incomplete 重跑；
    重跑产物字节级不变 → 下游键不变 → 下游仍零重算（判据 ② 联动）。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    calls: list[str] = []
    _run(tmp_path, run_dir, _chain_executors(calls), tmp_path / "cache",
         solve_lock=tmp_path / "solve.lock")
    n0 = len(calls)
    (run_dir / "r1" / "r1.rendered.txt").write_text("TAMPERED\n",
                                                    encoding="utf-8")
    res = _run(tmp_path, run_dir, _chain_executors(calls),
               tmp_path / "cache", solve_lock=tmp_path / "solve.lock")
    assert res["n_recompute"] == 1            # 仅 r1 incomplete 重跑
    assert res["n_hit"] == 9                  # s1 起下游键同+digest 过 → 跳过
    assert calls.count("r1") == 1 + 1
    assert len(calls) == n0 + 1


def test_corrupt_state_journal_resets_and_recomputes(tmp_path) -> None:
    """判据 ④（期刊面）：期刊损坏=不可信 → 状态重置（.corrupt 留痕），
    逐节点改由 键+digest/CAS 复核——产物面完好时经零拷贝索引恢复（零重算），
    不采信任何不可判状态（不猜）。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    calls: list[str] = []
    _run(tmp_path, run_dir, _chain_executors(calls), tmp_path / "cache",
         solve_lock=tmp_path / "solve.lock")
    assert len(calls) == 10
    (run_dir / DAG_STATE_FILE).write_text("{corrupt", encoding="utf-8")
    res = _run(tmp_path, run_dir, _chain_executors(calls),
               tmp_path / "cache", solve_lock=tmp_path / "solve.lock")
    assert (run_dir / (DAG_STATE_FILE + ".corrupt")).is_file()
    # 期刊不可判但产物面完好：CAS 索引零拷贝恢复，零重算
    assert res["n_hit"] == 10 and res["n_recompute"] == 0
    assert len(calls) == 10, "期刊损坏不得触发真实重算（产物面仍可校验）"


# ─── 跨 run 零拷贝缓存复用 ───────────────────────────────────────────────────

def test_cross_run_cache_hit_zero_copy(tmp_path) -> None:
    run1 = tmp_path / "run1"
    _seed_inputs(run1)
    calls: list[str] = []
    _run(tmp_path, run1, _chain_executors(calls), tmp_path / "cache",
         solve_lock=tmp_path / "solve.lock")
    # 新 run_dir、同计划+同引擎+同输入 → 全链命中，执行器零调用
    run2 = tmp_path / "run2"
    _seed_inputs(run2)
    calls2: list[str] = []
    res = _run(tmp_path, run2, _chain_executors(calls2), tmp_path / "cache",
               solve_lock=tmp_path / "solve.lock")
    assert res["n_hit"] == 10 and res["n_recompute"] == 0
    assert calls2 == [], "缓存命中节点不应执行"
    state = json.loads((run2 / DAG_STATE_FILE).read_text(encoding="utf-8"))
    assert state["nodes"]["r1"]["source"] == "cache"
    # 零拷贝：产物留在原 run1，run2 只存引用
    assert state["nodes"]["r1"]["artifact_run_dir"] == str(run1 / "r1")
    assert not (run2 / "r1" / "r1.rendered.txt").exists()


# ─── #261：solve 派发机器互斥缺省串行 ────────────────────────────────────────

def test_solve_mutex_held_during_dispatch_and_released(tmp_path) -> None:
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    solve_lock = tmp_path / "dag_solve.lock"
    seen: dict[str, bool] = {}

    def ex(node: dict, ctx: dict) -> dict:
        if node["kind"] == "solve":
            seen["locked"] = solve_lock.exists()   # 派发期间互斥锁在盘
        return {"ok": True, "outputs": [_write_output(node, ctx)],
                "wall_s": 0.01}

    res = run_dag(_plan_chain([("r1", "render"), ("s1", "solve")]), run_dir,
                  {"render": ex, "solve": ex, "postprocess": ex, "judge": ex},
                  cache_dir=tmp_path / "cache", engine_version="fake-1",
                  solve_lock_path=solve_lock)
    assert res["verdict"] == "COMPLETE"
    assert seen["locked"] is True, "solve 派发期间未持机器互斥锁"
    assert not solve_lock.exists(), "派发结束后互斥锁未释放"


def test_solve_mutex_second_writer_blocked(tmp_path) -> None:
    lock = tmp_path / "dag_solve.lock"
    m1 = SolveMachineMutex(lock)
    assert m1.acquire(max_wait_s=0.0) is True
    m2 = SolveMachineMutex(lock)
    assert m2.acquire(max_wait_s=0.3) is False   # 缺省串行：后到者等待/拒绝
    m1.release()
    assert m2.acquire(max_wait_s=0.0) is True    # 释放后可入（串行推进）
    m2.release()
    assert not lock.exists()


def test_lock_stale_takeover_after_dead_holder(tmp_path, monkeypatch) -> None:
    from rfauto.pipeline import dag_runner as dr

    lock = tmp_path / "l.lock"
    lock.write_text(json.dumps({"task": "t", "pid": 999999999}),
                    encoding="utf-8")
    monkeypatch.setattr(dr, "_pid_alive", lambda pid: False)
    assert dr.acquire_lock("t", lock, max_wait_s=0.5) == os.getpid()
    dr.release_lock(os.getpid(), lock)
    assert not lock.exists()
    monkeypatch.setattr(dr, "_pid_alive", lambda pid: True)
    lock.write_text(json.dumps({"task": "t", "pid": 999999999}),
                    encoding="utf-8")
    assert dr.acquire_lock("t", lock, max_wait_s=0.2) is None  # 活锁不抢


def test_release_lock_never_removes_other_owner(tmp_path) -> None:
    lock = tmp_path / "l.lock"
    owner = acquire_lock("t", lock, max_wait_s=0.0)
    release_lock(owner + 1, lock)                 # 他人 pid → 不误删
    assert lock.exists()
    release_lock(owner, lock)
    assert not lock.exists()


# ─── 入口健壮性 ──────────────────────────────────────────────────────────────

def test_run_dag_rejects_invalid_plan(tmp_path) -> None:
    res = run_dag({"nodes": [{"node_id": "a", "kind": "magic"}]},
                  tmp_path / "run", {}, cache_dir=tmp_path / "cache")
    assert res["ok"] is False and res["errors"]


def test_run_lock_contention_returns_error(tmp_path) -> None:
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    holder = acquire_lock("other", run_dir / DAG_RUN_LOCK_NAME, max_wait_s=0.0)
    try:
        runner = DagRunner(_plan_chain([("r1", "render")]), run_dir,
                           _chain_executors([]), cache_dir=tmp_path / "cache",
                           engine_version="fake-1",
                           solve_lock_path=tmp_path / "solve.lock",
                           lock_max_wait_s=0.0)
        res = runner.run(use_lock=True)
        assert res["ok"] is False and "运行锁被占" in res["errors"][0]
    finally:
        release_lock(holder, run_dir / DAG_RUN_LOCK_NAME)

def test_safety_budget_constant_matches_c3_precedent() -> None:
    assert SAFETY_BUDGET == 1.5    # c3_fullcurve_runner SAFETY_BUDGET 先例
