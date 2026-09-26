"""DP-9 P2：DAG 执行器（状态期刊 + 断点续跑 + #145/#261 接线）。

规格=docs/plan_deepdive_specs_20260924.md §DP-9 §4。语义：

- 状态期刊 ``<run_dir>/dag.state.json``：原子写（tmp+os.replace）+ 运行级
  文件锁（照抄 scripts/c3_fullcurve_runner.py acquire_lock/release_lock
  式样：O_CREAT|O_EXCL + pid 陈锁接管）。#157 整树无声消失后，重启按
  期刊重放；陈锁按持有者 pid 死亡自动接管（死树重启不卡锁）。
- 节点产物面：每节点独立工作目录 ``<run_dir>/<node_id>/``，其产物清单=
  ``<run_dir>/<node_id>/dag.artifact.json``（规格 §3 命名，per-node 一份，
  多节点互不覆盖）；跨 run 零拷贝引用指向该工作目录。
- 断点续跑（规格 §4 逐节点键重算）：键同+digest 过=done 跳过（n_hit）；
  键同校验败=incomplete 重跑；键变=本节点及下游**递归**重算（上游键进
  下游键载荷，传导自动发生——上游重跑产物字节级不变时下游仍零重算，
  判据 ② 的确定性保证）。
- #145 接线（adapters/hfss_adapter.solve 三分类在 DAG 层的对应物）：
  * watchdog Abort 真打断（executor 抛 NodeAbortedError）→ 判废重试，
    逐级 escalation（budget×1.5 → mesh 下一档，SAFETY_BUDGET=1.5 先例）；
  * 竞态完成（到点后 executor 仍交付）→ 接受真结果，不丢数据；
  * 超预算（wall_s > timeout_s×1.5）→ PARTIAL 入库不删数据。
- #261：solve 节点派发前过机器互斥文件锁（缺省串行；缺省锁路径=
  runs/.oe_collect.lock 家族锁，P3 真机直用，测试传 tmp 路径）。
- 零真机零网络：执行面全部经注入的 executors（kind→callable），合成
  测试用确定性字节执行器。

分层（分层铁律）：pipeline → infra/core 合法；键与 CAS 在 infra.dag_cache，
schema/拓扑在 core.compose.dag_schema。
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.core.compose.dag_schema import (
    DAG_SCHEMA,
    DagSchemaError,
    canonical,
    parse_dag,
)
from rfauto.infra.dag_cache import (
    DagCasIndex,
    compute_node_key,
    digest_of_files,
    env_fingerprint,
    file_sha256,
    node_components,
    render_components,
    sha256_text,
    solve_components,
    verify_artifacts,
    write_artifact_manifest,
)

#: 状态期刊文件与 schema 串（runs/<run>/ 增量文件，零改写既有证据面）。
DAG_STATE_FILE = "dag.state.json"
DAG_STATE_SCHEMA = "rfauto-dag-state-v1"

#: 运行级文件锁名（run_dir 内单写者，防双 runner 并发写期刊）。
DAG_RUN_LOCK_NAME = ".dag_run.lock"

#: #261 机器互斥缺省锁名（家族锁；P3 真机沿用 runs/.oe_collect.lock）。
FAMILY_SOLVE_LOCK_NAME = ".oe_collect.lock"

#: mesh 预算档递增序（escalation {"mesh_tier": "next"} 的"下一档"）。
MESH_TIERS: tuple[str, ...] = ("coarse", "mid", "fine")

#: 超预算 PARTIAL 判据 = wall_s > wall_budget_s；wall_budget_s 缺省派生
#: timeout_s × SAFETY_BUDGET（scripts/c3_fullcurve_runner.py:108 先例）。
SAFETY_BUDGET = 1.5


class NodeAbortedError(RuntimeError):
    """watchdog Abort 真打断求解（#145 判废语义）——executor 抛出，
    runner 按超时判废走重试/escalation；竞态完成不得抛本异常。"""


class RaceCompleted(RuntimeError):
    """竞态完成：截止时刻已过但工作已自行完成（#145"接受真实结果"）。

    executor 抛出并携带与正常返回同形的结果 dict（runner 原样采信，
    不丢已算完的数据——2026-09-03 真机教训）。"""

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__("竞态完成：截止后工作已自行完成，接受真实结果")
        self.result = result


# ─── 文件锁（照抄 c3_fullcurve_runner.acquire_lock/release_lock 式样）───────

def _pid_alive(pid: int) -> bool | None:
    """pid 存活探测（Windows tasklist 主路，POSIX os.kill 兜底；未知 None）。"""
    out_text = ""
    with contextlib.suppress(Exception):
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
            capture_output=True, text=True, timeout=30)
        out_text = proc.stdout or ""
    if out_text:
        return str(pid) in out_text
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def acquire_lock(task: str, lock_path: Path, *,
                 poll_s: float = 0.2,
                 max_wait_s: float = -1.0) -> int | None:
    """O_CREAT|O_EXCL 原子建锁；占用则轮询（陈锁按 pid 死亡接管）。

    max_wait_s 三分语义：<0 → 无限等（生产缺省，c3 先例）；0 → 单次尝试
    （占不到立即返回 None）；>0 → 有界等待，超时返回 None。返回持有者
    pid。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = (time.monotonic() + max_wait_s) if max_wait_s >= 0 else None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {"task": task,
                       "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "pid": os.getpid()}
            os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            os.close(fd)
            return os.getpid()
        except FileExistsError:
            holder: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                holder = json.loads(lock_path.read_text(encoding="utf-8"))
            pid = holder.get("pid")
            alive = _pid_alive(pid) if isinstance(pid, int) else None
            if alive is False:
                with contextlib.suppress(OSError):
                    lock_path.unlink()
                continue
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(poll_s)


def release_lock(owner_pid: int, lock_path: Path) -> None:
    """删锁（删前校验 pid=自身，防误删后到者锁；best-effort #105）。"""
    with contextlib.suppress(Exception):
        holder = json.loads(lock_path.read_text(encoding="utf-8"))
        if holder.get("pid") == owner_pid:
            lock_path.unlink()


# ─── 执行器协议 ──────────────────────────────────────────────────────────────

#: executor: fn(node, ctx) -> {"ok": bool, "outputs": [relpath...],
#: "wall_s": float, "message": str}；超时判废抛 NodeAbortedError，
#: 竞态完成抛 RaceCompleted(result)。outputs 为 ctx["work_dir"] 相对路径。
ExecutorFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _normalize_executor_result(raw: Any) -> dict[str, Any]:
    """executor 返回值归一化（形状非法 = 失败，不吞不猜）。"""
    if not isinstance(raw, dict) or not raw.get("ok"):
        message = (raw.get("message") if isinstance(raw, dict) else None) \
            or "executor 返回 ok=False"
        return {"ok": False, "outputs": [], "wall_s": 0.0,
                "message": str(message)}
    return {"ok": True,
            "outputs": [str(o) for o in (raw.get("outputs") or [])],
            "wall_s": float(raw.get("wall_s", 0.0) or 0.0),
            "message": str(raw.get("message", ""))}


def _next_mesh_tier(tier: Any) -> str:
    """预算档"下一档"（escalation {"mesh_tier": "next"}）；已最细则原地。"""
    cur = str(tier or MESH_TIERS[0])
    try:
        idx = MESH_TIERS.index(cur)
    except ValueError:
        return MESH_TIERS[0]
    return MESH_TIERS[min(idx + 1, len(MESH_TIERS) - 1)]


def escalated_budget(node: dict[str, Any], attempt: int) -> dict[str, Any]:
    """第 attempt 次重试的预算（escalation 阶梯，确定性）。

    步骤循环取用：{"budget_x": x} → timeout_s × x 累乘；{"mesh_tier":
    "next"} → mesh_tier 进一档（MESH_TIERS 序）。attempt=0 → 原预算。"""
    budget = dict(node.get("budget") or {})
    if attempt <= 0:
        return budget
    steps = node.get("escalation") or []
    for k in range(attempt):
        step = steps[k % len(steps)] if steps else {"budget_x": SAFETY_BUDGET}
        if "budget_x" in step:
            try:
                x = float(step["budget_x"])
            except (TypeError, ValueError):
                x = SAFETY_BUDGET
            try:
                budget["timeout_s"] = float(budget.get("timeout_s") or 0) * x
            except (TypeError, ValueError):
                budget["timeout_s"] = None
        elif step.get("mesh_tier") == "next":
            budget["mesh_tier"] = _next_mesh_tier(budget.get("mesh_tier"))
    return budget


# ─── 环境指纹（进程级缓存：pip freeze 开销只付一次，level2_design 先例）──────

_ENV_CACHE: dict[str, dict[str, str]] = {}


def cached_env_fingerprint(repo_root: Path) -> dict[str, str]:
    """env_fingerprint 的进程内缓存版（键含 repo_root，best-effort 不变语义）。"""
    key = str(repo_root)
    if key not in _ENV_CACHE:
        _ENV_CACHE[key] = env_fingerprint(repo_root)
    return _ENV_CACHE[key]


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


# ─── 节点键派生（成分来源=计划节点 + 磁盘现状；规格 §3 公式分派）─────────────

def node_work_dir(run_dir: str | Path, node_id: str) -> Path:
    """节点工作目录（产物/清单/索引引用的落点，per-node 隔离防互踩）。"""
    return Path(run_dir) / node_id


def _upstream_outputs(runner: DagRunner, node_id: str) -> list[tuple[Path, str]]:
    """上游节点的 (artifact_work_dir, relpath) 列表（拓扑序保证先算完）。"""
    out: list[tuple[Path, str]] = []
    for dep in runner.deps.get(node_id, []):
        entry = runner.state["nodes"].get(dep) or {}
        base = Path(entry.get("artifact_run_dir") or runner.run_dir)
        for rel in entry.get("outputs") or []:
            out.append((base, str(rel)))
    return out


def compute_node_effective_key(runner: DagRunner, node: dict[str, Any]) -> str:
    """节点有效键（rerun_triggers 过滤 + 上游键传导；规格 §3 键公式）。

    - render：render_script_sha（inputs.files 内容 digest+cmd）+ 注册 commit
      ts + 参数 canonical JSON + mesh 配置 + 引擎版本指纹；
    - solve：渲染产物 sha256（上游 outputs 逐文件 digest）+ 引擎版本 + 预算档；
    - postprocess/judge：输入 digest（inputs.files+上游 outputs）+参数+cmd+环境指纹。
    """
    inputs = node.get("inputs") or {}
    budget = node.get("budget") or {}
    triggers = node.get("rerun_triggers") or []
    upstream_keys = {dep: (runner.state["nodes"].get(dep) or {}).get("key", "")
                     for dep in runner.deps.get(node["node_id"], [])}

    if node["kind"] == "render":
        files = list(inputs.get("files") or [])
        code_face = digest_of_files(runner.run_dir, files) if files else ""
        if node.get("cmd"):
            code_face = sha256_text(code_face + "|" + node["cmd"])
        comps = render_components(
            render_script_sha=code_face,
            registration_commit_ts=str(
                inputs.get("registration_commit_ts", "") or ""),
            params_canonical_json=canonical(inputs.get("params") or {}),
            mesh_config={"mesh_tier": budget.get("mesh_tier", ""),
                         "mesh": budget.get("mesh", "")},
            engine_version=runner.engine_version,
        )
        return compute_node_key("render", comps, node_id=node["node_id"],
                                triggers=triggers, upstream_keys=upstream_keys)

    if node["kind"] == "solve":
        art_lines = [f"{base}::{rel}:{file_sha256(base / rel) or 'MISSING'}"
                     for base, rel in sorted(
                         _upstream_outputs(runner, node["node_id"]),
                         key=lambda p: (str(p[0]), p[1]))]
        comps = solve_components(
            render_artifact_sha256=sha256_text("\n".join(art_lines)),
            engine_version=runner.engine_version,
            budget_tier={"timeout_s": budget.get("timeout_s"),
                         "nrts": budget.get("nrts", ""),
                         "mesh_tier": budget.get("mesh_tier", "")},
        )
        return compute_node_key("solve", comps, node_id=node["node_id"],
                                triggers=triggers, upstream_keys=upstream_keys)

    files = list(inputs.get("files") or [])
    own_digest = digest_of_files(runner.run_dir, files) if files else ""
    up_lines = [f"{base}::{rel}:{file_sha256(base / rel) or 'MISSING'}"
                for base, rel in sorted(
                    _upstream_outputs(runner, node["node_id"]),
                    key=lambda p: (str(p[0]), p[1]))]
    comps = node_components(
        input_digests=sha256_text(own_digest + "|" + "\n".join(up_lines)),
        params_canonical_json=canonical(inputs.get("params") or {}),
        cmd=str(node.get("cmd", "") or ""),
        env_fingerprint_sha=runner.env_sha,
    )
    return compute_node_key("node", comps, node_id=node["node_id"],
                            triggers=triggers, upstream_keys=upstream_keys)


# ─── #261 机器互斥（家族锁）─────────────────────────────────────────────────

def default_solve_lock_path() -> Path:
    """#261 家族锁缺省路径（<repo>/runs/.oe_collect.lock；best-effort 推断）。"""
    return _default_repo_root() / "runs" / FAMILY_SOLVE_LOCK_NAME


class SolveMachineMutex:
    """solve 节点派发前的机器互斥（#261：真机求解缺省串行）。

    acquire 沿 acquire_lock 式样（O_CREAT|O_EXCL + 陈锁接管）；P3 真机把
    lock_path 指到 runs/.oe_collect.lock（家族锁复用），测试传 tmp 路径。
    鸭子协议 acquire()/release()——注入替身（NullMutex 等）即插即用。"""

    def __init__(self, lock_path: Path | None = None) -> None:
        self.lock_path = Path(lock_path) if lock_path \
            else default_solve_lock_path()
        self._owner_pid: int | None = None

    def acquire(self, *, poll_s: float = 0.2, max_wait_s: float = -1.0) -> bool:
        """持锁（max_wait_s<0 无限等=缺省串行；0 单次；>0 有界）。"""
        pid = acquire_lock("dag_solve", self.lock_path,
                           poll_s=poll_s, max_wait_s=max_wait_s)
        if pid is None:
            return False
        self._owner_pid = pid
        return True

    def release(self) -> None:
        if self._owner_pid is not None:
            release_lock(self._owner_pid, self.lock_path)
            self._owner_pid = None


# ─── DAG 执行器 ─────────────────────────────────────────────────────────────

class DagRunner:
    """DAG 执行 + 断点续跑（rfauto-dag-v1 计划 → 逐节点键重算状态机）。"""

    def __init__(
        self,
        plan: dict[str, Any],
        run_dir: str | Path,
        executors: dict[str, ExecutorFn],
        *,
        cache_dir: str | Path | None = None,
        engine_version: str = "",
        repo_root: str | Path | None = None,
        solve_lock_path: str | Path | None = None,
        lock_poll_s: float = 0.2,
        lock_max_wait_s: float = -1.0,
        log: Callable[[str], None] | None = None,
    ) -> None:
        parsed = parse_dag(plan)
        if not parsed.get("ok"):
            raise DagSchemaError("; ".join(parsed.get("errors") or ["DAG 非法"]))
        self.nodes = {n["node_id"]: n for n in parsed["nodes"]}
        self.order: list[str] = parsed["order"]
        self.deps: dict[str, list[str]] = {
            n["node_id"]: list(n["depends_on"]) for n in parsed["nodes"]}
        missing_exec = sorted(
            {n["kind"] for n in parsed["nodes"]} - set(executors))
        if missing_exec:
            raise DagSchemaError(
                f"缺少 executor: {missing_exec}（计划节点 kind 必须全覆盖）")
        self.executors = executors
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.index = DagCasIndex(cache_dir)
        self.engine_version = engine_version
        self.env = cached_env_fingerprint(Path(repo_root or _default_repo_root()))
        self.env_sha = sha256_text(canonical(self.env))
        self.solve_lock_path = (Path(solve_lock_path) if solve_lock_path
                                else default_solve_lock_path())
        self.lock_poll_s = float(lock_poll_s)
        self.lock_max_wait_s = float(lock_max_wait_s)
        self.lock_path = self.run_dir / DAG_RUN_LOCK_NAME
        self.log = log or (lambda msg: None)
        self.state = self._load_state()

    # ---- 状态期刊（原子写 + 运行级文件锁）────────────────────────────────

    def _state_path(self) -> Path:
        return self.run_dir / DAG_STATE_FILE

    def _load_state(self) -> dict[str, Any]:
        path = self._state_path()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("nodes"), dict):
                    data.setdefault("schema", DAG_STATE_SCHEMA)
                    data.setdefault("plan_schema", DAG_SCHEMA)
                    data.setdefault("n_hit", 0)
                    data.setdefault("n_recompute", 0)
                    return data
            except (OSError, json.JSONDecodeError):
                pass
            # 期刊损坏 = 不可信：状态重置（原文件留 .corrupt 痕），
            # 节点有效性随后逐个走 键+digest/CAS 复核（产物完好仍零重算），
            # 不采信任何不可判状态（判据 ④，不猜）
            with contextlib.suppress(OSError):
                path.replace(path.with_name(DAG_STATE_FILE + ".corrupt"))
        return {"schema": DAG_STATE_SCHEMA, "plan_schema": DAG_SCHEMA,
                "nodes": {}, "n_hit": 0, "n_recompute": 0}

    def _write_state(self) -> None:
        """原子写期刊（tmp + os.replace；Windows 单写者安全）。"""
        self.state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                 time.gmtime())
        tmp = self._state_path().with_name(f"{DAG_STATE_FILE}.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1,
                                  sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._state_path())

    # ---- 下游传导 ────────────────────────────────────────────────────────

    def _downstream(self, node_id: str) -> list[str]:
        """传递闭包的下游节点（拓扑序，确定性）。"""
        seen: set[str] = set()
        changed = True
        while changed:
            changed = False
            for nid in self.order:
                if nid == node_id or nid in seen:
                    continue
                if any(d == node_id or d in seen
                       for d in self.deps.get(nid, [])):
                    seen.add(nid)
                    changed = True
        return [n for n in self.order if n in seen]

    # ---- 单节点跳过/重跑判定（规格 §4）──────────────────────────────────

    def _resume_decision(self, node_id: str, key: str) -> tuple[str, str]:
        """返回 (动作, 原因)。动作 ∈ skip | rerun_incomplete | rerun_stale。

        done/partial 且键同且产物 digest 过 → skip（零重算）；
        键同 digest 败 → rerun_incomplete（半产物不采信）；
        键变 → rerun_stale（下游经键传导递归重算）。"""
        prev = self.state["nodes"].get(node_id)
        if not prev or prev.get("status") not in ("done", "partial"):
            return "rerun_stale", "无完成记录"
        if prev.get("key") != key:
            return "rerun_stale", (
                f"键已变（旧 {str(prev.get('key'))[:12]}… → 新 {key[:12]}…）")
        outputs = prev.get("outputs") or []
        if not outputs or not prev.get("has_manifest", True):
            return "skip", "键同（无产物面节点）"
        base = Path(prev.get("artifact_run_dir") or self.run_dir)
        ok, problems = verify_artifacts(base)
        if ok:
            return "skip", "键同+digest 过（断点续跑零重算）"
        return "rerun_incomplete", f"键同但产物校验败: {problems[:2]}"

    # ---- 派发与 #145 三分类 ──────────────────────────────────────────────

    def _dispatch(self, node: dict[str, Any], ctx: dict[str, Any],
                  timeout_s: float) -> tuple[dict[str, Any], str]:
        """派发执行并做 #145 分类。返回 (结果, 分类注记)。

        - NodeAbortedError → 上抛（判废重试由 _run_node 循环处理）；
        - RaceCompleted / wall 超截止但已交付 → 接受真结果（注记）。"""
        t0 = time.monotonic()
        try:
            raw = self.executors[node["kind"]](node, ctx)
        except RaceCompleted as race:
            result = _normalize_executor_result(race.result)
            result["race_accepted"] = True
            return result, ("竞态完成接受真结果（#145：截止 "
                            f"{timeout_s:.0f}s 后交付）")
        result = _normalize_executor_result(raw)
        wall = float(result.get("wall_s") or (time.monotonic() - t0))
        result["wall_s"] = wall
        note = ""
        if timeout_s > 0 and wall > timeout_s and result.get("ok"):
            result["race_accepted"] = True
            note = (f"竞态完成接受真结果（#145：wall {wall:.0f}s > 截止 "
                    f"{timeout_s:.0f}s，Abort 未打断交付）")
        return result, note

    def _run_node(self, node: dict[str, Any], key: str,
                  work_dir: Path) -> tuple[str, list[str], list[str], bool]:
        """执行单节点（重试阶梯 + #145 分类 + manifest/索引写序）。

        返回 (最终状态, outputs, notes, has_manifest)。
        最终状态 ∈ done|partial|failed。"""
        retries = int(node.get("retries", 0) or 0)
        notes: list[str] = []
        for attempt in range(retries + 1):
            budget = escalated_budget(node, attempt)
            timeout_s = float(budget.get("timeout_s") or 0)
            wall_budget = timeout_s * SAFETY_BUDGET if timeout_s > 0 else None
            ctx = {"run_dir": str(self.run_dir), "work_dir": str(work_dir),
                   "attempt": attempt, "budget": budget, "node": node,
                   "upstream": {d: dict(self.state["nodes"].get(d) or {})
                                for d in self.deps.get(node["node_id"], [])}}
            mutex = (SolveMachineMutex(self.solve_lock_path)
                     if node["kind"] == "solve" else None)
            try:
                if mutex is not None and not mutex.acquire(
                        poll_s=self.lock_poll_s):
                    return "failed", [], [
                        "#261 机器互斥获取失败（串行等待超时）"], False
                try:
                    result, note = self._dispatch(node, ctx, timeout_s)
                finally:
                    if mutex is not None:
                        mutex.release()
            except NodeAbortedError as abort:
                notes.append(f"attempt{attempt}: watchdog Abort 真打断→判废"
                             f"重试（#145: {abort}）")
                continue
            if note:
                notes.append(f"attempt{attempt}: {note}")
            if not result.get("ok"):
                notes.append(f"attempt{attempt}: executor 失败: "
                             f"{result.get('message', '')}")
                continue

            declared = [str(o) for o in (node.get("outputs") or [])]
            outputs = declared or result.get("outputs") or []
            missing = [rel for rel in outputs
                       if not (work_dir / rel).exists()]
            if outputs and missing:
                notes.append(f"attempt{attempt}: 声明产物缺失 {missing[:3]}")
                continue

            wall = float(result.get("wall_s") or 0.0)
            status = "done"
            if wall_budget is not None and wall > wall_budget:
                status = "partial"       # 超预算 PARTIAL 入库（不删数据）
                notes.append(
                    f"超预算 PARTIAL 入库（wall {wall:.0f}s > 预算帽 "
                    f"{wall_budget:.0f}s，SAFETY_BUDGET={SAFETY_BUDGET}）")
            if not outputs:
                # 无产物面节点（纯 judge）：无 manifest 可写，键同即可 skip
                return status, [], notes, False
            # 写序（规格 §3）：先产物（executor 已写）→ manifest（原子）→ 索引
            write_artifact_manifest(
                work_dir, outputs, complete=True,
                node_id=node["node_id"], key=key,
                extra={"wall_s": wall, "attempt": attempt,
                       "status": status})
            self.index.store_index(
                key, run_dir=work_dir, node_kind=node["kind"],
                extra={"node_id": node["node_id"]})
            return status, outputs, notes, True
        return "failed", [], notes, False

    def _accept_cache_hit(self, node_id: str, key: str,
                          hit: dict[str, Any]) -> dict[str, Any]:
        manifest = hit.get("manifest") or {}
        files = [f.get("path") for f in (manifest.get("files") or [])
                 if isinstance(f, dict)]
        entry = {
            "status": "done", "key": key, "outputs": files,
            "artifact_run_dir": hit.get("run_dir"),
            "has_manifest": bool(files),
            "source": "cache", "notes": ["跨 run 缓存命中（零拷贝引用原 run_dir）"],
        }
        self.state["nodes"][node_id] = entry
        self._write_state()
        self.log(f"[cache-hit] {node_id}: 复用 {hit.get('run_dir')}")
        return entry

    # ---- 主循环 ──────────────────────────────────────────────────────────

    def run(self, *, use_lock: bool = True) -> dict[str, Any]:
        """执行整图（断点续跑语义内嵌）。返回观测 dict（JSON 面出）。"""
        owner = None
        if use_lock:
            owner = acquire_lock("dag_run", self.lock_path,
                                 poll_s=self.lock_poll_s,
                                 max_wait_s=self.lock_max_wait_s)
            if owner is None:
                return {"ok": False,
                        "errors": [f"运行锁被占（{self.lock_path}）"]}
        prev_hit = int(self.state.get("n_hit") or 0)
        prev_recomp = int(self.state.get("n_recompute") or 0)
        n_hit = 0
        n_recompute = 0
        try:
            for node_id in self.order:
                prev_status = (self.state["nodes"].get(node_id) or {}).get(
                    "status", "")
                if prev_status in ("aborted", "skipped"):
                    continue              # 已判死分支不复活（campaign 同语义）
                node = self.nodes[node_id]
                key = compute_node_effective_key(self, node)
                action, reason = self._resume_decision(node_id, key)
                if action == "skip":
                    n_hit += 1
                    prev = self.state["nodes"][node_id]
                    self.state["nodes"][node_id] = {**prev, "key": key}
                    self._write_state()
                    self.log(f"[hit] {node_id}: {reason}")
                    continue
                self.log(f"[rerun] {node_id}: {reason}")
                cached = self._cache_lookup(node, key)
                if cached is not None:
                    n_hit += 1
                    self._accept_cache_hit(node_id, key, cached)
                    continue
                n_recompute += 1
                self.state["nodes"][node_id] = {
                    "status": "running", "key": key, "attempt": 0}
                self._write_state()
                work_dir = node_work_dir(self.run_dir, node_id)
                work_dir.mkdir(parents=True, exist_ok=True)
                status, outputs, notes, has_manifest = self._run_node(
                    node, key, work_dir)
                self.state["nodes"][node_id] = {
                    "status": status, "key": key, "outputs": outputs,
                    "artifact_run_dir": str(work_dir),
                    "has_manifest": has_manifest, "notes": notes}
                self._write_state()
                self.log(f"[exec] {node_id}: {status}（{reason}）")
                if status == "failed":
                    for down in self._downstream(node_id):
                        self.state["nodes"][down] = {
                            "status": "aborted", "key": "",
                            "notes": [f"上游 {node_id} failed"]}
                        self.log(f"[abort] {down}: 上游 {node_id} failed")
                    self._write_state()
        finally:
            if owner is not None:
                release_lock(owner, self.lock_path)

        statuses = {nid: (self.state["nodes"].get(nid) or {}).get("status", "")
                    for nid in self.order}
        n_done = sum(1 for s in statuses.values() if s == "done")
        n_partial = sum(1 for s in statuses.values() if s == "partial")
        n_dead = sum(1 for s in statuses.values() if s in ("failed", "aborted"))
        if n_dead:
            verdict = "ABORTED"
        elif n_partial:
            verdict = "PARTIAL"
        elif n_done == len(self.order):
            verdict = "COMPLETE"
        else:
            verdict = "RUNNING"
        total_hit = prev_hit + n_hit
        total_recomp = prev_recomp + n_recompute
        self.state["n_hit"] = total_hit
        self.state["n_recompute"] = total_recomp
        self.state["verdict"] = verdict
        self._write_state()
        self.log(f"[done] verdict={verdict} hit={n_hit} "
                 f"recompute={n_recompute}（累计 hit={total_hit} "
                 f"recompute={total_recomp}）")
        return {
            "ok": verdict in ("COMPLETE", "PARTIAL"),
            "verdict": verdict,
            "n_hit": n_hit,
            "n_recompute": n_recompute,
            "n_hit_total": total_hit,
            "n_recompute_total": total_recomp,
            "statuses": statuses,
            "state_path": str(self._state_path()),
        }

    def _cache_lookup(self, node: dict[str, Any],
                      key: str) -> dict[str, Any] | None:
        """跨 run 缓存命中（零拷贝索引 + 逐文件 digest 复核，P1 旁路面）。"""
        hit = self.index.lookup(key, node_kind=node["kind"])
        return hit if hit.get("hit") else None


def run_dag(
    plan: dict[str, Any],
    run_dir: str | Path,
    executors: dict[str, ExecutorFn],
    *,
    cache_dir: str | Path | None = None,
    engine_version: str = "",
    solve_lock_path: str | Path | None = None,
    lock_max_wait_s: float = -1.0,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """DAG 执行入口（service JSON 面口径：plan/schema 非法 → ok=False+errors）。

    P1"run_once 旁路"的单节点形态 = 只含一个节点（如单个 solve）的 plan
    ——键命中+digest 过 → 零执行引用原 run_dir（与 api.run_once 的缓存
    旁路同语义，但不改 run_once 本体，规格 §1 范围约束）。"""
    try:
        runner = DagRunner(plan, run_dir, executors, cache_dir=cache_dir,
                           engine_version=engine_version,
                           solve_lock_path=solve_lock_path,
                           lock_max_wait_s=lock_max_wait_s, log=log)
    except DagSchemaError as exc:
        return {"ok": False, "errors": [str(exc)]}
    return runner.run()


__all__ = [
    "DAG_RUN_LOCK_NAME",
    "DAG_STATE_FILE",
    "DAG_STATE_SCHEMA",
    "FAMILY_SOLVE_LOCK_NAME",
    "MESH_TIERS",
    "SAFETY_BUDGET",
    "DagRunner",
    "NodeAbortedError",
    "RaceCompleted",
    "SolveMachineMutex",
    "acquire_lock",
    "cached_env_fingerprint",
    "compute_node_effective_key",
    "default_solve_lock_path",
    "escalated_budget",
    "node_work_dir",
    "release_lock",
    "run_dag",
]
