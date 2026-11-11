"""T-Q9（aurora_q Q-W4-3）：Foam-Agent 式分段可重入 pipeline 增强测试。

三需求逐面钉（审计结论见席位报告；全合成零真机零网络，执行器全注入 fake）：
①事件账本确定性重放：dag.events.jsonl（append-only 观测面）全词表覆盖 +
  replay_dag_events 纯函数 fold——同账本两轮重放 JSON 逐字节同、重放
  status/key 与权威期刊 dag.state.json 逐键同、词表外事件跳过、尾行半写
  容错；
②断点重入端到端：中断（executor 异常=崩溃形态，期刊停 running）→ resume
  只补失败/未跑段——成功段零重算证据=执行器零调用+产物 mtime_ns/字节
  不变（键命中）；campaign 六阶段同构端到端（stage=DAG 节点映射）；
③失败分段重跑+既有语义回归钉：失败段重算/成功段零触碰、inconclusive 重入
  重判、竞态完成接受（#145）、Abort 判废重试、陈锁接管、占锁拒绝零事件
  写入。

零数值面（铁律 7）：本文件只钉编排/账本行为，零物理数字。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from rfauto.pipeline.dag_runner import (
    DAG_EVENT_KINDS,
    DAG_EVENTS_FILE,
    DAG_EVENTS_SCHEMA,
    DAG_RUN_LOCK_NAME,
    DAG_STATE_FILE,
    DagRunner,
    NodeAbortedError,
    RaceCompleted,
    acquire_lock,
    append_dag_event,
    count_dag_events,
    load_dag_events,
    release_lock,
    replay_dag_events,
    run_dag,
)

# ─── 合成计划与确定性执行器 ──────────────────────────────────────────────────

_EXT = {"render": "rendered.txt", "solve": "sparams.csv",
        "postprocess": "post.json", "judge": "report.json"}
_OUTPUT_STEM = "OUT:{node_id}:v1\n"

_CHAIN5 = [("r1", "render"), ("s1", "solve"), ("r2", "render"),
           ("s2", "solve"), ("r3", "render")]


def _plan_chain(steps: list[tuple[str, str]]) -> dict:
    nodes: list[dict] = []
    prev = ""
    for node_id, kind in steps:
        nodes.append({
            "node_id": node_id, "kind": kind,
            "depends_on": [prev] if prev else [],
            "inputs": {"files": ["inputs/design.txt"] if kind == "render"
                       else [], "params": {"w": 0.5} if kind == "render" else {}},
            "outputs": [f"{node_id}.{_EXT[kind]}"],
            "cmd": f"{kind} {node_id}",
            "budget": {"timeout_s": 10},
            "retries": 0,
        })
        prev = node_id
    return {"nodes": nodes}


def _seed_inputs(run_dir: Path) -> None:
    (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs" / "design.txt").write_text("DESIGN-v1\n",
                                                   encoding="utf-8")


def _write_output(node: dict, ctx: dict) -> str:
    rel = f"{node['node_id']}.{_EXT[node['kind']]}"
    work = Path(ctx["work_dir"])
    work.mkdir(parents=True, exist_ok=True)
    (work / rel).write_text(_OUTPUT_STEM.format(node_id=node["node_id"]),
                            encoding="utf-8")
    return rel


def _executors(calls: list[str], *, crash_at: str = "",
               fail_at: str = "", abort_once_at: str = "") -> dict:
    """确定性字节执行器四类全覆盖；可选注入崩溃/失败/Abort 形态。"""

    def _ex(node: dict, ctx: dict) -> dict:
        nid = node["node_id"]
        if crash_at and nid == crash_at:
            raise RuntimeError(f"模拟进程崩溃形态（{nid} 中断）")
        if abort_once_at and nid == abort_once_at and ctx["attempt"] == 0:
            raise NodeAbortedError("watchdog Abort 真打断（模拟）")
        calls.append(nid)
        if fail_at and nid == fail_at:
            return {"ok": False, "outputs": [], "wall_s": 0.0,
                    "message": f"{nid} 首轮失败（模拟待修复缺陷）"}
        rel = _write_output(node, ctx)
        return {"ok": True, "outputs": [rel], "wall_s": 0.01}

    return {"render": _ex, "solve": _ex, "postprocess": _ex, "judge": _ex}


def _run(run_dir: Path, executors: dict, tmp_path: Path,
         *, cache: bool = True, lock_max_wait_s: float = -1.0) -> dict:
    return run_dag(
        _plan_chain(_CHAIN5), run_dir, executors,
        cache_dir=(tmp_path / "cache") if cache else None,
        engine_version="fake-1", solve_lock_path=tmp_path / "solve.lock",
        lock_max_wait_s=lock_max_wait_s)


def _events(run_dir: Path) -> list[dict]:
    return load_dag_events(run_dir / DAG_EVENTS_FILE)


def _artifact_mtime_ns(run_dir: Path, node_id: str) -> int:
    rel = f"{node_id}.{_EXT['render' if node_id.startswith('r') else 'solve']}"
    return (run_dir / node_id / rel).stat().st_mtime_ns


@pytest.fixture(autouse=True)
def _clean_cache_env(monkeypatch):
    monkeypatch.delenv("RFAUTO_CACHE", raising=False)


# ─── ①事件账本：词表/追加/装载 ────────────────────────────────────────────────

def test_event_kinds_vocabulary_and_constants_frozen() -> None:
    """词表/文件名/schema 串冻结（消费面预声明，QW-7 同风格）。"""
    assert DAG_EVENT_KINDS == (
        "run_start", "state_reset", "node_running", "node_skip",
        "node_cache_hit", "node_exec", "node_downstream", "node_revive",
        "run_verdict")
    assert DAG_EVENTS_FILE == "dag.events.jsonl"
    assert DAG_EVENTS_SCHEMA == "rfauto-dag-events-v1"


def test_event_ledger_full_vocabulary_across_sessions(tmp_path) -> None:
    """全词表覆盖钉：失败+复活续跑+期刊损坏 CAS 恢复三会话后，账本事件词
    集合 == DAG_EVENT_KINDS 全集；每行 schema/seq/ts/event 键齐、seq 严格
    递增（append-only 迁移史）。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    calls: list[str] = []
    plan = _plan_chain([("a", "render"), ("b", "solve"), ("c", "render"),
                        ("d", "solve")])
    ex = _executors(calls, fail_at="c")

    # 会话 1：c 失败 → d aborted
    res1 = run_dag(plan, run_dir, ex, cache_dir=tmp_path / "cache",
                   engine_version="fake-1",
                   solve_lock_path=tmp_path / "solve.lock")
    assert res1["verdict"] == "ABORTED"
    # 会话 2：修复后 resume（a/b skip、c 重跑、d 复活重跑）
    ex2 = _executors(calls)
    res2 = run_dag(plan, run_dir, ex2, cache_dir=tmp_path / "cache",
                   engine_version="fake-1",
                   solve_lock_path=tmp_path / "solve.lock")
    assert res2["verdict"] == "COMPLETE"
    # 会话 3：期刊损坏 → state_reset + CAS 缓存命中恢复（零重算）
    (run_dir / DAG_STATE_FILE).write_text("{corrupt", encoding="utf-8")
    res3 = run_dag(plan, run_dir, _executors(calls),
                   cache_dir=tmp_path / "cache", engine_version="fake-1",
                   solve_lock_path=tmp_path / "solve.lock")
    assert res3["n_recompute"] == 0 and res3["n_hit"] == 4

    events = _events(run_dir)
    kinds = {str(e.get("event") or "") for e in events}
    assert kinds == set(DAG_EVENT_KINDS), kinds
    seqs = [int(e["seq"]) for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), (
        "账本 seq 非严格递增（append-only 破坏）")
    for e in events:
        assert e["schema"] == DAG_EVENTS_SCHEMA
        assert {"seq", "ts", "event", "node"} <= set(e)


def test_append_dag_event_auto_seq_and_explicit_seq(tmp_path) -> None:
    """seq=None 按行数自增（外部调用形态）；显式 seq 透传；detail 键原样。"""
    rd = tmp_path / "run"
    assert append_dag_event(rd, "run_start") == 1
    assert append_dag_event(rd, "node_exec", node="a",
                            status="done") == 2
    assert append_dag_event(rd, "node_exec", node="a", seq=99,
                            status="failed") == 99
    events = load_dag_events(rd / DAG_EVENTS_FILE)
    assert [(e["event"], e["node"]) for e in events] == [
        ("run_start", ""), ("node_exec", "a"), ("node_exec", "a")]
    assert events[1]["detail"] == {"status": "done"}
    assert events[2]["seq"] == 99


def test_append_dag_event_best_effort_on_failure(tmp_path) -> None:
    """#105 best-effort：落盘失败返回 None 不抛（观测面不阻塞主路径）。"""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("I am a file", encoding="utf-8")
    assert append_dag_event(blocker, "run_start") is None
    assert count_dag_events(blocker / DAG_EVENTS_FILE) == 0


def test_load_dag_events_tolerates_partial_tail_and_missing(tmp_path) -> None:
    """尾行半写（崩溃中断残留）跳过不炸；账本缺席=空列表。"""
    rd = tmp_path / "run"
    assert load_dag_events(rd / DAG_EVENTS_FILE) == []
    append_dag_event(rd, "run_start")
    append_dag_event(rd, "node_exec", node="a", status="done")
    path = rd / DAG_EVENTS_FILE
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"event": "node_ex')          # 半写尾行（无换行）
    events = load_dag_events(path)
    assert [e["event"] for e in events] == ["run_start", "node_exec"]
    assert count_dag_events(path) >= 2


# ─── ①确定性重放钉（验收：重放=重算 逐字节/逐键同）────────────────────────────

def test_replay_matches_journal_keys_and_statuses(tmp_path) -> None:
    """全量跑完后：replay(events) 节点 status/key 与权威期刊逐键同，
    run 级 verdict/累计计数同源。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    res = _run(run_dir, _executors([]), tmp_path)
    assert res["verdict"] == "COMPLETE"
    journal = json.loads((run_dir / DAG_STATE_FILE).read_text(
        encoding="utf-8"))
    replayed = replay_dag_events(_events(run_dir))
    assert replayed["verdict"] == journal["verdict"]
    assert replayed["n_hit_total"] == journal["n_hit"]
    assert replayed["n_recompute_total"] == journal["n_recompute"]
    for nid, entry in journal["nodes"].items():
        rp = replayed["nodes"].get(nid)
        assert rp is not None, f"重放缺节点 {nid}"
        assert rp["status"] == entry["status"], nid
        assert rp["key"] == entry["key"], nid


def test_replay_deterministic_byte_identical(tmp_path) -> None:
    """同事件序列两轮重放 → JSON 逐字节同（确定性 fold，零时钟/零随机）。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    _run(run_dir, _executors([]), tmp_path)
    events = _events(run_dir)
    a = json.dumps(replay_dag_events(events), ensure_ascii=False,
                   sort_keys=True)
    b = json.dumps(replay_dag_events(list(events)), ensure_ascii=False,
                   sort_keys=True)
    assert a == b


def test_replay_multi_session_kill_resume(tmp_path) -> None:
    """跨会话重放：中断（c 崩溃停 running）→ resume 收敛后，全账本（两会话）
    重放与终态期刊逐键同；崩溃节点终态由第二会话 node_exec 覆盖 running。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    with pytest.raises(RuntimeError, match="模拟进程崩溃形态"):
        _run(run_dir, _executors([], crash_at="r2"), tmp_path)
    journal_mid = json.loads((run_dir / DAG_STATE_FILE).read_text(
        encoding="utf-8"))
    assert journal_mid["nodes"]["r2"]["status"] == "running"

    res = _run(run_dir, _executors([]), tmp_path)
    assert res["verdict"] == "COMPLETE"
    journal = json.loads((run_dir / DAG_STATE_FILE).read_text(
        encoding="utf-8"))
    replayed = replay_dag_events(_events(run_dir))
    for nid, entry in journal["nodes"].items():
        assert replayed["nodes"][nid]["status"] == entry["status"], nid
        assert replayed["nodes"][nid]["key"] == entry["key"], nid
    # 中间态留痕：账本含 r2 的 node_running（会话 1）与 node_exec done（会话 2）
    r2_events = [e for e in _events(run_dir) if e.get("node") == "r2"]
    kinds = [e["event"] for e in r2_events]
    assert "node_running" in kinds and kinds[-1] == "node_exec"
    assert r2_events[-1]["detail"]["status"] == "done"


def test_replay_state_reset_then_cache_recovery(tmp_path) -> None:
    """期刊损坏会话：账本含 state_reset + node_cache_hit 序列，重放与恢复后
    期刊逐键同（节点 source=cache 溯源进重放面）。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    _run(run_dir, _executors([]), tmp_path)
    (run_dir / DAG_STATE_FILE).write_text("{corrupt", encoding="utf-8")
    calls: list[str] = []
    res = _run(run_dir, _executors(calls), tmp_path)
    assert res["n_hit"] == 5 and res["n_recompute"] == 0
    assert calls == [], "CAS 恢复不得触发真实执行"
    events = _events(run_dir)
    kinds = [e["event"] for e in events]
    assert "state_reset" in kinds
    assert kinds.count("node_cache_hit") == 5
    journal = json.loads((run_dir / DAG_STATE_FILE).read_text(
        encoding="utf-8"))
    replayed = replay_dag_events(events)
    for nid, entry in journal["nodes"].items():
        assert replayed["nodes"][nid]["status"] == entry["status"] == "done"
        assert replayed["nodes"][nid]["key"] == entry["key"]
        assert replayed["nodes"][nid]["source"] == "cache"


def test_replay_skips_unknown_event_words() -> None:
    """词表外事件跳过不炸（向后兼容：新事件词不炸旧重放）；空账本=空状态。"""
    empty = replay_dag_events([])
    assert empty == {"schema": DAG_EVENTS_SCHEMA, "nodes": {}}
    state = replay_dag_events([
        {"event": "future_kind_from_newer_schema", "node": "x"},
        {"event": "node_exec", "node": "a",
         "detail": {"status": "done", "key": "k1"}},
    ])
    assert state["nodes"] == {"a": {"status": "done", "key": "k1"}}
    assert "x" not in state["nodes"]


# ─── ②断点重入端到端（验收：成功段零重算有证据）───────────────────────────────

def test_interrupt_resume_failed_segment_only_mtime_evidence(tmp_path) -> None:
    """断点重入端到端：5 节点链第 3 节点崩溃中断 → resume 只补未跑段——
    成功段（r1/s1）零重算证据=执行器零调用+产物 mtime_ns 与字节逐位不变
    （键命中）；未跑段（r2/s2/r3）重算收敛。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    calls: list[str] = []
    with pytest.raises(RuntimeError, match="模拟进程崩溃形态"):
        _run(run_dir, _executors(calls, crash_at="r2"), tmp_path)
    assert calls == ["r1", "s1"], calls
    mt_before = {nid: _artifact_mtime_ns(run_dir, nid)
                 for nid in ("r1", "s1")}
    bytes_before = {
        nid: (run_dir / nid / (
            f"{nid}.{_EXT['render' if nid.startswith('r') else 'solve']}"))
        .read_bytes() for nid in ("r1", "s1")}

    res = _run(run_dir, _executors(calls), tmp_path)
    assert res["verdict"] == "COMPLETE"
    assert res["n_hit"] == 2 and res["n_recompute"] == 3
    # 成功段零重算证据 ①执行器零调用 ②产物 mtime_ns 不变 ③字节不变
    assert not ({"r1", "s1"} & set(calls[2:])), calls
    assert Counter(calls) == {"r1": 1, "s1": 1, "r2": 1, "s2": 1, "r3": 1}
    for nid in ("r1", "s1"):
        assert _artifact_mtime_ns(run_dir, nid) == mt_before[nid], nid
        cur = (run_dir / nid / (
            f"{nid}.{_EXT['render' if nid.startswith('r') else 'solve']}"))
        assert cur.read_bytes() == bytes_before[nid], nid


def test_interrupt_resume_journal_running_then_done(tmp_path) -> None:
    """重入语义钉：中断现场崩溃节点停 running（半态不采信）；resume 后
    _resume_decision 判 rerun_stale 重执行转 done——running 不是终态。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    with pytest.raises(RuntimeError, match="模拟进程崩溃形态"):
        _run(run_dir, _executors([], crash_at="s1"), tmp_path)
    mid = json.loads((run_dir / DAG_STATE_FILE).read_text(
        encoding="utf-8"))
    assert mid["nodes"]["s1"]["status"] == "running"
    assert mid["nodes"]["r1"]["status"] == "done"

    calls: list[str] = []
    res = _run(run_dir, _executors(calls), tmp_path)
    assert res["verdict"] == "COMPLETE"
    assert res["statuses"]["s1"] == "done"
    assert calls == ["s1", "r2", "s2", "r3"], calls  # r1 命中不重跑


def test_stale_lock_takeover_in_reentry_flow(tmp_path, monkeypatch) -> None:
    """陈锁接管在重入流内：死持有者锁残留 → resume 自动接管收官
    （#157 死树重启不卡锁；接管后账本续写）。"""
    from rfauto.pipeline import dag_runner as dr

    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    with pytest.raises(RuntimeError, match="模拟进程崩溃形态"):
        _run(run_dir, _executors([], crash_at="s1"), tmp_path)
    # 伪造死持有者陈锁（pid 不存在探测=False）
    lock = run_dir / DAG_RUN_LOCK_NAME
    lock.write_text(json.dumps({"task": "ghost", "pid": 999999999}),
                    encoding="utf-8")
    monkeypatch.setattr(dr, "_pid_alive", lambda pid: False)
    n_events_before = count_dag_events(run_dir / DAG_EVENTS_FILE)
    res = _run(run_dir, _executors([]), tmp_path)
    assert res["verdict"] == "COMPLETE"
    assert not lock.exists(), "陈锁接管后未清理"
    assert count_dag_events(run_dir / DAG_EVENTS_FILE) > n_events_before


def test_run_lock_rejection_writes_no_events(tmp_path) -> None:
    """占锁拒绝会话零事件写入（run_start 在锁成功后才落账——被拒会话不在
    迁移史里留痕）。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    _run(run_dir, _executors([]), tmp_path)
    n_before = count_dag_events(run_dir / DAG_EVENTS_FILE)
    holder = acquire_lock("other", run_dir / DAG_RUN_LOCK_NAME,
                          max_wait_s=0.0)
    try:
        runner = DagRunner(_plan_chain(_CHAIN5), run_dir, _executors([]),
                           cache_dir=tmp_path / "cache",
                           engine_version="fake-1",
                           solve_lock_path=tmp_path / "solve.lock",
                           lock_max_wait_s=0.0)
        res = runner.run(use_lock=True)
        assert res["ok"] is False and "运行锁被占" in res["errors"][0]
        assert count_dag_events(run_dir / DAG_EVENTS_FILE) == n_before
    finally:
        release_lock(holder, run_dir / DAG_RUN_LOCK_NAME)


# ─── ③失败分段重跑（失败段重算+成功段零触碰）─────────────────────────────────

def test_failed_segment_rerun_upstream_untouched_mtime(tmp_path) -> None:
    """失败分段重跑：ok=False 失败（非崩溃）→ 下游 aborted；修复后 resume
    ——失败段+复活下游重算，上游 done 段零触碰（mtime 证据）；账本记录
    node_downstream（判死）与 node_revive（复活）迁移史。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    calls: list[str] = []
    res1 = _run(run_dir, _executors(calls, fail_at="s1"), tmp_path)
    assert res1["verdict"] == "ABORTED"
    assert res1["statuses"]["s1"] == "failed"
    assert res1["statuses"]["r2"] == "aborted"
    mt_r1 = _artifact_mtime_ns(run_dir, "r1")

    res2 = _run(run_dir, _executors(calls), tmp_path)
    assert res2["verdict"] == "COMPLETE"
    assert Counter(calls) == {"r1": 1, "s1": 2, "r2": 1, "s2": 1, "r3": 1}
    assert _artifact_mtime_ns(run_dir, "r1") == mt_r1, (
        "上游 done 段产物被重触碰（成功段零触碰破坏）")
    kinds = [e["event"] for e in _events(run_dir)]
    assert "node_downstream" in kinds and "node_revive" in kinds


def test_inconclusive_node_reruns_on_resume(tmp_path) -> None:
    """inconclusive 重入重判钉：证据不可判节点续跑重执行（_resume_decision
    只认 done/partial——给判定再机会），二轮转 done 后键命中跳过。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    calls: list[str] = []
    plan = _plan_chain([("r1", "render")])
    plan["nodes"][0]["inconclusive_when"] = {"outputs_missing_any":
                                             ["r1.rendered.txt"]}

    def ex_first_incomplete(node: dict, ctx: dict) -> dict:
        calls.append(node["node_id"])
        return {"ok": True, "outputs": [], "wall_s": 0.01,
                "message": "产物缺席（证据不可判形态）"}

    executors = {"render": ex_first_incomplete, "solve": ex_first_incomplete,
                 "postprocess": ex_first_incomplete,
                 "judge": ex_first_incomplete}
    res1 = run_dag(plan, run_dir, executors, cache_dir=tmp_path / "cache",
                   engine_version="fake-1",
                   solve_lock_path=tmp_path / "solve.lock")
    assert res1["verdict"] == "PARTIAL"           # inconclusive → PARTIAL
    assert res1["statuses"]["r1"] == "inconclusive"

    res2 = run_dag(plan, run_dir, _executors(calls),
                   cache_dir=tmp_path / "cache", engine_version="fake-1",
                   solve_lock_path=tmp_path / "solve.lock")
    assert res2["verdict"] == "COMPLETE"
    assert calls == ["r1", "r1"], "inconclusive 节点未重入重判"
    assert res2["n_hit"] == 0 and res2["n_recompute"] == 1
    res3 = run_dag(plan, run_dir, _executors(calls),
                   cache_dir=tmp_path / "cache", engine_version="fake-1",
                   solve_lock_path=tmp_path / "solve.lock")
    assert res3["n_recompute"] == 0 and res3["n_hit"] == 1


# ─── ③既有语义回归钉（#145/竞态完成/Abort 判废——账本视角）───────────────────

def test_race_completed_accepted_and_ledger_pin(tmp_path) -> None:
    """#145 竞态完成接受真结果（既有语义）：节点 done 不丢数据；账本
    node_exec status=done 与期刊一致（重放逐键同）。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)

    def ex(node: dict, ctx: dict) -> dict:
        rel = _write_output(node, ctx)
        raise RaceCompleted({"ok": True, "outputs": [rel], "wall_s": 12.0})

    res = _run(run_dir, {"render": ex, "solve": ex, "postprocess": ex,
                         "judge": ex}, tmp_path)
    assert res["verdict"] == "COMPLETE"
    journal = json.loads((run_dir / DAG_STATE_FILE).read_text(
        encoding="utf-8"))
    assert journal["nodes"]["r1"]["status"] == "done"
    assert any("竞态完成接受真结果" in n
               for n in journal["nodes"]["r1"]["notes"])
    replayed = replay_dag_events(_events(run_dir))
    assert replayed["nodes"]["r1"]["status"] == "done"


def test_abort_discard_retry_converges_ledger_pin(tmp_path) -> None:
    """#145 Abort 真打断判废重试（既有语义）：escalation ×1.5 后收敛；
    账本按节点终态记 node_exec（attempt 级不重复落账——迁移史粒度=状态机
    迁移非尝试史）。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    calls: list[str] = []
    plan = _plan_chain([("r1", "render")])
    plan["nodes"][0]["retries"] = 1
    ex = _executors(calls, abort_once_at="r1")
    res = run_dag(plan, run_dir, ex, cache_dir=tmp_path / "cache",
                  engine_version="fake-1",
                  solve_lock_path=tmp_path / "solve.lock")
    assert res["verdict"] == "COMPLETE"
    assert calls == ["r1"]                        # 判废重试同节点收敛
    exec_events = [e for e in _events(run_dir) if e["event"] == "node_exec"]
    assert len(exec_events) == 1
    assert exec_events[0]["detail"]["status"] == "done"
    journal = json.loads((run_dir / DAG_STATE_FILE).read_text(
        encoding="utf-8"))
    assert any("Abort 真打断" in n
               for n in journal["nodes"]["r1"]["notes"])


def test_event_ledger_append_only_across_reruns(tmp_path) -> None:
    """append-only 钉：同 run_dir 三次 run（含重跑）账本只增不改——旧行
    字节逐位保留，新会话事件追加在尾。"""
    run_dir = tmp_path / "run1"
    _seed_inputs(run_dir)
    _run(run_dir, _executors([]), tmp_path)
    path = run_dir / DAG_EVENTS_FILE
    first_snapshot = path.read_bytes()
    _run(run_dir, _executors([]), tmp_path)       # 全命中会话（node_skip）
    second_snapshot = path.read_bytes()
    assert second_snapshot.startswith(first_snapshot), (
        "账本旧行被改写（append-only 破坏）")
    kinds = [e["event"] for e in load_dag_events(path)]
    assert kinds.count("node_skip") == 5          # 全命中会话逐节点 skip
    _run(run_dir, _executors([]), tmp_path)
    assert path.read_bytes().startswith(second_snapshot)


# ─── ②campaign 六阶段断点可重入端到端（审计 b 探针+账本覆盖）──────────────────

def test_campaign_stage_reentrancy_end_to_end(tmp_path) -> None:
    """campaign 级断点重入：六阶段（stages=DAG 节点 1:1 映射）tune 首轮
    ok=False → ABORTED+视图 failed/aborted；修复后 resume——成功段执行器
    零重调用、失败段+复活段重算收敛 COMPLETE；事件账本落战役 run 目录且
    重放与权威期刊逐键同（基座账本自动覆盖 campaign 阶段面——零新账本）。"""
    from rfauto.service.campaign_executor import (
        CAMPAIGN_KINDS,
        STAGE_RESULT_FILE,
        run_campaign,
    )
    from rfauto.service.campaign_manager import plan_campaign, save_plan

    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        "model: mline\nobjectives:\n  - metric: s11_db\n"
        "    op: max_below\n    value: -10.0\nlimits:\n  max_trials: 30\n",
        encoding="utf-8")
    plan = plan_campaign(recipe)
    assert plan["ok"] is True
    camp_dir = tmp_path / "camp"
    camp_dir.mkdir(parents=True, exist_ok=True)
    save_plan(plan, camp_dir)

    ledger: Counter = Counter()
    tune_fixed = [False]

    def _make(kind: str):
        def _exec(node: dict, ctx: dict) -> dict:
            ledger[str(node.get("node_id"))] += 1
            work = Path(ctx.get("work_dir") or ".")
            work.mkdir(parents=True, exist_ok=True)
            (work / STAGE_RESULT_FILE).write_text(
                json.dumps({"ok": True, "stage": node.get("node_id")},
                           ensure_ascii=False), encoding="utf-8")
            if kind == "tune" and not tune_fixed[0]:
                return {"ok": False, "outputs": [], "wall_s": 0.0,
                        "message": "tune 首轮失败（模拟待修复缺陷）"}
            return {"ok": True, "outputs": [STAGE_RESULT_FILE],
                    "wall_s": 0.0, "message": f"{kind} ok"}
        return _exec

    table = {k: _make(k) for k in CAMPAIGN_KINDS}
    solve_lock = tmp_path / "solve.lock"
    res1 = run_campaign(str(camp_dir), executors=table,
                        solve_lock_path=str(solve_lock),
                        cache_dir=str(tmp_path / "cache"))
    assert res1["ok"] is False and res1["verdict"] == "ABORTED"
    assert ledger["calibrate"] == 1 and ledger["prefilter"] == 1
    assert ledger["tune"] == 1
    plan_view = json.loads(
        (camp_dir / "campaign.plan.json").read_text(encoding="utf-8"))
    view = {s["stage"]: s["status"] for s in plan_view["stages"]}
    assert view["tune"] == "failed"
    assert view["tolerance"] == "aborted"

    tune_fixed[0] = True
    res2 = run_campaign(str(camp_dir), executors=table, resume=True,
                        solve_lock_path=str(solve_lock),
                        cache_dir=str(tmp_path / "cache"))
    assert res2["ok"] is True and res2["verdict"] == "COMPLETE"
    assert res2["n_hit"] == 2 and res2["n_recompute"] == 4, res2
    # 成功段零重执行：calibrate/prefilter 仍 1 次；失败段 tune=2
    assert ledger["calibrate"] == 1 and ledger["prefilter"] == 1
    assert ledger["tune"] == 2
    assert ledger["tolerance"] == 1 and ledger["report"] == 1
    assert ledger["final_verify"] == 1
    plan_view = json.loads(
        (camp_dir / "campaign.plan.json").read_text(encoding="utf-8"))
    assert all(s["status"] == "done" for s in plan_view["stages"])

    # 基座事件账本覆盖 campaign 阶段面：重放与权威期刊逐键同
    events = _events(camp_dir)
    assert events, "战役 run 目录缺事件账本"
    journal = json.loads((camp_dir / DAG_STATE_FILE).read_text(
        encoding="utf-8"))
    replayed = replay_dag_events(events)
    for nid, entry in journal["nodes"].items():
        assert replayed["nodes"][nid]["status"] == entry["status"], nid
        assert replayed["nodes"][nid]["key"] == entry["key"], nid
    kinds = [e["event"] for e in events]
    assert "node_downstream" in kinds and "node_revive" in kinds
