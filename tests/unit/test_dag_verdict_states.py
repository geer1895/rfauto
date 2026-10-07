"""QW-7：DAG 节点 verdict 三态（inconclusive）+ 失败策略（abort/continue/skip）。

零行为变化红线：无新字段的既有 DAG 声明走原路径——abort 缺省语义、
run 级 verdict 映射、归一化节点键集逐字节不变；inconclusive 与失败策略
只在显式声明 failure_policy/inconclusive_when（或 executor 显式返回
inconclusive 标志）时生效。全合成回调零真机零网络。

映射口径（预声明于 pipeline.dag_runner 模块注释，此处逐条钉住）：
- 途径① executor ok=True + inconclusive 标志 → 终态不重试；
- 途径② inconclusive_when.outputs_missing_any：重试穷尽后缺失集 ⊆ 软
  产物集 → inconclusive（不判 failed）；含软产物之外的缺失 → 照旧 failed；
- 途径③ inconclusive_when.message_contains：成功完成的 message 命中 →
  inconclusive（覆盖 done/partial，注记并存）；
- failure_policy：continue=下游照常执行+归因注记；skip=下游标 skipped
  （不算失败，续跑不复活）；run 级不引入新 verdict 态，有 inconclusive
  且无 fail/aborted → PARTIAL（COMPLETE 收紧）+ state inconclusive_count。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.core.compose.dag_schema import (
    DEFAULT_FAILURE_POLICY,
    FAILURE_POLICIES,
    NODE_STATUSES,
    DagSchemaError,
    normalize_node,
    parse_dag,
)
from rfauto.pipeline.dag_runner import DAG_STATE_FILE, run_dag


@pytest.fixture(autouse=True)
def _clean_cache_env(monkeypatch):
    """隔离 RFAUTO_CACHE（防环境泄漏改变索引模式语义；#139 钉通道精神）。"""
    monkeypatch.delenv("RFAUTO_CACHE", raising=False)


# ─── 合成计划与确定性执行器 ──────────────────────────────────────────────────

def _two_node_plan(a_kw: dict | None = None,
                   b_kw: dict | None = None) -> dict:
    """两节点线性链 a(render)→b(solve)；a_kw/b_kw 逐键并进节点声明。"""
    base = [
        {"node_id": "a", "kind": "render", "depends_on": [],
         "inputs": {"files": [], "params": {}},
         "outputs": ["a.rendered.txt"], "cmd": "render a",
         "budget": {"timeout_s": 10}, "retries": 0},
        {"node_id": "b", "kind": "solve", "depends_on": ["a"],
         "inputs": {"files": [], "params": {}},
         "outputs": ["b.sparams.csv"], "cmd": "solve b",
         "budget": {"timeout_s": 10, "nrts": 100}, "retries": 0},
    ]
    for kw, node in ((a_kw, base[0]), (b_kw, base[1])):
        if kw:
            node.update(kw)
    return {"nodes": base}


def _judge_plan(kw: dict | None = None) -> dict:
    """单 judge 节点（无产物面，message 判据途径的主场景）。"""
    node = {"node_id": "j", "kind": "judge", "depends_on": [],
            "inputs": {"files": [], "params": {}}, "outputs": [],
            "cmd": "judge", "budget": {"timeout_s": 10}, "retries": 0}
    if kw:
        node.update(kw)
    return {"nodes": [node]}


def _exec_registry(calls: list, *, fail: tuple = (), inconclusive: tuple = (),
                   wall_s: float = 0.01, message: str = "",
                   skip_outputs: tuple = ()) -> dict:
    """确定性执行器注册表：fail=强制执行失败；inconclusive=声明证据不可判；
    skip_outputs=声明产物故意不落盘（缺软产物模拟）。"""
    def _ex(node: dict, ctx: dict) -> dict:
        nid = node["node_id"]
        calls.append(nid)
        if nid in fail:
            return {"ok": False, "outputs": [], "wall_s": 0.01,
                    "message": f"boom {nid}"}
        work = Path(ctx["work_dir"])
        work.mkdir(parents=True, exist_ok=True)
        produced = []
        for rel in (node.get("outputs") or []):
            if rel in skip_outputs:
                continue
            p = work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"OUT:{nid}:{rel}\n", encoding="utf-8")
            produced.append(rel)
        if nid in inconclusive:
            return {"ok": True, "outputs": produced, "wall_s": wall_s,
                    "message": message, "inconclusive": True,
                    "inconclusive_reason": "产物在但校验门未过且未抛错（模拟）"}
        return {"ok": True, "outputs": produced, "wall_s": wall_s,
                "message": message}

    return {k: _ex for k in ("render", "solve", "postprocess", "judge")}


def _run(plan: dict, run_dir: Path, executors: dict, tmp_path: Path,
         cache_name: str = "cache") -> dict:
    return run_dag(plan, run_dir, executors,
                   cache_dir=tmp_path / cache_name,
                   engine_version="fake-1",
                   solve_lock_path=tmp_path / "solve.lock",
                   log=lambda msg: None)


def _state(run_dir: Path) -> dict:
    return json.loads((run_dir / DAG_STATE_FILE).read_text(encoding="utf-8"))


# ─── 零行为变化钉（无新字段 → 原语义/原路径）────────────────────────────────

def test_zero_behavior_legacy_plan_abort_semantics_unchanged(tmp_path) -> None:
    """无新字段的计划：A fail→B 不执行标 aborted（缺省 abort 现行为），
    下游注记与 run 级 verdict 逐字节同旧语义。"""
    calls: list = []
    res = _run(_two_node_plan(), tmp_path / "run1",
               _exec_registry(calls, fail=("a",)), tmp_path)
    assert res["ok"] is False and res["verdict"] == "ABORTED"
    assert res["statuses"] == {"a": "failed", "b": "aborted"}
    assert res["inconclusive_count"] == 0
    assert calls == ["a"], "abort 缺省语义：下游不得执行"
    state = _state(tmp_path / "run1")
    assert state["nodes"]["b"]["notes"] == ["上游 a failed"]
    assert state["inconclusive_count"] == 0


def test_zero_behavior_verdict_mapping_unchanged(tmp_path) -> None:
    """无新字段：全 pass→COMPLETE；超预算→PARTIAL（原映射不变）。"""
    calls: list = []
    res = _run(_two_node_plan(), tmp_path / "run_ok",
               _exec_registry(calls), tmp_path)
    assert res["verdict"] == "COMPLETE" and res["ok"] is True
    calls2: list = []
    res2 = _run(_two_node_plan(), tmp_path / "run_slow",
                _exec_registry(calls2, wall_s=100.0), tmp_path,
                cache_name="cache_slow")   # 换缓存防跨 run 零拷贝命中 done
    assert res2["verdict"] == "PARTIAL" and res2["ok"] is True
    assert res2["inconclusive_count"] == 0


def test_zero_behavior_schema_legacy_node_keyset_unchanged() -> None:
    """旧声明 dict 经 schema 校验零报错，归一化输出键集与 QW-7 前逐键同
    （failure_policy/inconclusive_when 零字段=不含键，向后兼容硬门）。"""
    raw = {"node_id": "r1", "kind": "render", "depends_on": ["x"],
           "inputs": {"files": ["x.txt"], "params": {"w": 0.5}},
           "outputs": ["o.txt"], "cmd": "render",
           "budget": {"timeout_s": 5}, "retries": 1,
           "escalation": [{"budget_x": 2.0}], "rerun_triggers": ["code"],
           "stage_extra": {"shadow_points": {"n": 3}}}
    node = normalize_node(raw)
    assert set(node) == {"node_id", "kind", "depends_on", "inputs",
                         "outputs", "cmd", "budget", "retries", "escalation",
                         "rerun_triggers", "stage_extra"}
    assert "failure_policy" not in node
    assert "inconclusive_when" not in node
    assert node["escalation"] == [{"budget_x": 2.0}]
    assert node["rerun_triggers"] == ["code"]
    assert node["stage_extra"] == {"shadow_points": {"n": 3}}
    parsed = parse_dag({"nodes": [raw, {"node_id": "x", "kind": "render"}]})
    assert parsed["ok"] is True


# ─── failure_policy=continue（记录失败继续后续节点）─────────────────────────

def test_continue_policy_downstream_executes_and_succeeds(tmp_path) -> None:
    """A fail（continue）→ B 照常执行且成功；A 仍记 failed（run ABORTED），
    B 注记带归因说明（归因策略而非上游）。"""
    calls: list = []
    plan = _two_node_plan(a_kw={"failure_policy": "continue"})
    res = _run(plan, tmp_path / "run1", _exec_registry(calls, fail=("a",)),
               tmp_path)
    assert res["statuses"] == {"a": "failed", "b": "done"}
    assert calls == ["a", "b"]
    assert res["verdict"] == "ABORTED"       # a 本身仍是真失败
    state = _state(tmp_path / "run1")
    notes = " ".join(state["nodes"]["b"]["notes"])
    assert "failure_policy=continue" in notes
    assert "归因策略而非上游" in notes


def test_continue_policy_downstream_natural_failure_attributed(tmp_path):
    """A fail（continue）→ B 依赖其产物自然失败：B 记自身 failed，
    注记如实归因到策略而非上游（上游条目仍是自身失败注记）。"""
    calls: list = []
    plan = _two_node_plan(a_kw={"failure_policy": "continue"})
    res = _run(plan, tmp_path / "run1",
               _exec_registry(calls, fail=("a", "b")), tmp_path)
    assert res["statuses"] == {"a": "failed", "b": "failed"}
    assert calls == ["a", "b"], "continue 策略下游必须真的执行过"
    state = _state(tmp_path / "run1")
    assert state["nodes"]["a"]["notes"] == ["attempt0: executor 失败: boom a"]
    notes = " ".join(state["nodes"]["b"]["notes"])
    assert "failure_policy=continue" in notes
    assert "归因策略而非上游" in notes
    assert "boom b" in notes                 # 自身失败原因如实保留


# ─── failure_policy=skip（下游跳过，不算失败）────────────────────────────────

def test_skip_policy_downstream_skipped_not_fail(tmp_path) -> None:
    """A fail（skip）→ B 标 skipped：不执行、不算失败；A 本身仍 failed
    （run 级 ABORTED 由 a 的真失败驱动，B 不参与计死）。"""
    calls: list = []
    plan = _two_node_plan(a_kw={"failure_policy": "skip"})
    res = _run(plan, tmp_path / "run1", _exec_registry(calls, fail=("a",)),
               tmp_path)
    assert res["statuses"] == {"a": "failed", "b": "skipped"}
    assert calls == ["a"], "skip 策略下游不得执行"
    assert res["verdict"] == "ABORTED"
    state = _state(tmp_path / "run1")
    assert state["nodes"]["b"]["notes"] == [
        "上游 a failed（failure_policy=skip：跳过，不算失败）"]
    # 续跑：skipped 分支不复活（与 aborted 同不复活语义），a 仍失败重跑
    calls2: list = []
    res2 = _run(plan, tmp_path / "run1", _exec_registry(calls2, fail=("a",)),
                tmp_path)
    assert res2["statuses"] == {"a": "failed", "b": "skipped"}
    assert "b" not in calls2


def test_skip_wart_resume_fixed_upstream_skipped_tail_partials(tmp_path) -> None:
    """skip wart 修复钉（2026-09-26）：续跑终局"上游已修复 + 下游按 skip
    策略留 skipped"→ PARTIAL（修复前落入 RUNNING 空隙：skipped 不计 done
    也不计 dead，循环结束 verdict 永远 RUNNING/ok=False 的计数缺口）；
    state skipped_count 与 verdict 同源（按当前期刊重算，非跨 run 累计）。"""
    plan = _two_node_plan(a_kw={"failure_policy": "skip"})
    calls: list = []
    res1 = _run(plan, tmp_path / "run1", _exec_registry(calls, fail=("a",)),
                tmp_path)
    assert res1["verdict"] == "ABORTED"       # 首跑：a 真失败驱动
    # 续跑：a 修复成功，b 仍按 skip 策略留 skipped（不复活）
    calls2: list = []
    res2 = _run(plan, tmp_path / "run1", _exec_registry(calls2), tmp_path)
    assert res2["statuses"] == {"a": "done", "b": "skipped"}
    assert "b" not in calls2
    assert res2["verdict"] == "PARTIAL" and res2["ok"] is True
    assert res2["skipped_count"] == 1
    state = _state(tmp_path / "run1")
    assert state["skipped_count"] == 1
    # 全 done 计划不受影响（无 skipped → COMPLETE 语义零变化）
    calls3: list = []
    res3 = _run(_two_node_plan(), tmp_path / "run2", _exec_registry(calls3),
                tmp_path)
    assert res3["verdict"] == "COMPLETE" and res3["skipped_count"] == 0


# ─── inconclusive：executor 显式声明（途径①，终态不重试）───────────────────

def test_inconclusive_executor_flag_terminal_no_retry(tmp_path) -> None:
    """executor 返回 ok=True+inconclusive → 节点态 inconclusive：终态
    不重试（retries=2 只派发一次）；产物留盘、不写 manifest；run 级
    PARTIAL（不引入新 verdict 态）+ inconclusive_count=1。"""
    calls: list = []
    plan = _two_node_plan(a_kw={"retries": 2},
                          b_kw={"depends_on": []})   # b 独立不依赖 a
    res = _run(plan, tmp_path / "run1",
               _exec_registry(calls, inconclusive=("a",)), tmp_path)
    assert calls == ["a", "b"], "途径①终态不重试（retries=2 只派发一次）"
    assert res["statuses"]["a"] == "inconclusive"
    assert res["statuses"]["b"] == "done"
    assert res["verdict"] == "PARTIAL" and res["ok"] is True
    assert res["inconclusive_count"] == 1
    state = _state(tmp_path / "run1")
    assert state["inconclusive_count"] == 1
    assert (tmp_path / "run1" / "a" / "a.rendered.txt").is_file(), \
        "产物留盘供人工检视"
    assert not (tmp_path / "run1" / "a" / "dag.artifact.json").exists(), \
        "inconclusive 不写 manifest（不采信为可复用产物）"
    notes = " ".join(state["nodes"]["a"]["notes"])
    assert "inconclusive" in notes and "校验门未过" in notes
    # 续跑：inconclusive 不采信为完成 → 重执行（再给一次判定机会）
    calls2: list = []
    res2 = _run(plan, tmp_path / "run1",
                _exec_registry(calls2, inconclusive=("a",)), tmp_path)
    assert calls2.count("a") == 1 and res2["n_hit"] == 1  # b 键同 digest 过
    assert res2["statuses"]["a"] == "inconclusive"


def test_inconclusive_node_does_not_block_downstream(tmp_path) -> None:
    """inconclusive 不是执行失败：缺省（无 failure_policy）下不判死下游，
    下游照常执行（abort 传播只由 failed 驱动）。"""
    calls: list = []
    res = _run(_two_node_plan(a_kw={"retries": 1}),
               tmp_path / "run1",
               _exec_registry(calls, inconclusive=("a",)), tmp_path)
    assert calls == ["a", "b"]
    assert res["statuses"] == {"a": "inconclusive", "b": "done"}
    assert res["verdict"] == "PARTIAL"       # 无 fail/aborted + inconclusive


# ─── inconclusive_when.outputs_missing_any（途径②，重试穷尽后判）───────────

def test_inconclusive_when_soft_missing_after_retries(tmp_path) -> None:
    """声明软产物缺失：先走重试阶梯（retries=1 派发两次），最后一次仍缺
    且缺失 ⊆ 软产物集 → inconclusive；已存在产物如实记录、无 manifest。"""
    calls: list = []
    plan = _two_node_plan(a_kw={
        "retries": 1,
        "outputs": ["a.rendered.txt", "evidence/gate.csv"],
        "inconclusive_when": {"outputs_missing_any": ["evidence/gate.csv"]},
    })
    res = _run(plan, tmp_path / "run1",
               _exec_registry(calls, skip_outputs=("evidence/gate.csv",)),
               tmp_path)
    assert calls.count("a") == 2, "软产物缺失在非末次尝试必须先走重试"
    assert calls.count("b") == 1, "inconclusive 不判死下游（b 照常执行）"
    assert res["statuses"]["a"] == "inconclusive"
    assert res["verdict"] == "PARTIAL" and res["inconclusive_count"] == 1
    state = _state(tmp_path / "run1")
    assert state["nodes"]["a"]["outputs"] == ["a.rendered.txt"]
    assert not (tmp_path / "run1" / "a" / "dag.artifact.json").exists()
    notes = " ".join(state["nodes"]["a"]["notes"])
    assert "outputs_missing_any" in notes
    assert not (tmp_path / "run1" / "a" / "evidence" / "gate.csv").exists()


def test_inconclusive_when_hard_missing_still_failed(tmp_path) -> None:
    """缺失集含软产物之外的声明产物 → 照旧 failed（执行失败族不借道
    inconclusive 洗白；#225 两族分离）。"""
    calls: list = []
    plan = _two_node_plan(a_kw={
        "outputs": ["a.rendered.txt", "evidence/gate.csv"],
        "inconclusive_when": {"outputs_missing_any": ["evidence/gate.csv"]},
    })
    res = _run(plan, tmp_path / "run1",
               _exec_registry(calls,
                              skip_outputs=("evidence/gate.csv",
                                            "a.rendered.txt")),
               tmp_path)
    assert res["statuses"]["a"] == "failed"
    assert res["statuses"]["b"] == "aborted"
    assert res["verdict"] == "ABORTED"
    assert res["inconclusive_count"] == 0


# ─── inconclusive_when.message_contains（途径③，覆盖 done/partial）─────────

def test_inconclusive_when_message_contains_judge(tmp_path) -> None:
    """judge 节点（无产物面）message 命中声明子串 → inconclusive；
    同执行器不命中 → done COMPLETE（阴性对照，钉住非过 matcher）。"""
    calls: list = []
    plan = _judge_plan({"inconclusive_when": {"message_contains":
                                              "UNDECIDABLE"}})
    res = _run(plan, tmp_path / "run1",
               _exec_registry(calls, message="gate UNDECIDABLE: nsnp"),
               tmp_path)
    assert res["statuses"] == {"j": "inconclusive"}
    assert res["verdict"] == "PARTIAL" and res["inconclusive_count"] == 1
    calls2: list = []
    res2 = _run(_judge_plan({"inconclusive_when": {"message_contains":
                                                   "UNDECIDABLE"}}),
                tmp_path / "run2",
                _exec_registry(calls2, message="all gates PASS"), tmp_path)
    assert res2["statuses"] == {"j": "done"}
    assert res2["verdict"] == "COMPLETE"


def test_inconclusive_overrides_over_budget_partial_notes_kept(tmp_path):
    """超预算 partial 与 message 判据同时命中 → inconclusive 优先（证据
    不可判优先于 partial 的"可用"语义），两类注记并存如实保留。"""
    calls: list = []
    plan = _judge_plan({"inconclusive_when": {"message_contains":
                                              "UNDECIDABLE"}})
    res = _run(plan, tmp_path / "run1",
               _exec_registry(calls, wall_s=100.0,
                              message="gate UNDECIDABLE"), tmp_path)
    assert res["statuses"] == {"j": "inconclusive"}
    state = _state(tmp_path / "run1")
    notes = " ".join(state["nodes"]["j"]["notes"])
    assert "超预算 PARTIAL 入库" in notes
    assert "message_contains 命中" in notes


# ─── schema：新字段校验与归一化形态 ──────────────────────────────────────────

def test_node_statuses_and_failure_policy_constants() -> None:
    assert "inconclusive" in NODE_STATUSES
    assert FAILURE_POLICIES == ("abort", "continue", "skip")
    assert DEFAULT_FAILURE_POLICY == "abort"


def test_schema_new_fields_normalized_shape() -> None:
    node = normalize_node({"node_id": "n", "kind": "solve",
                           "failure_policy": "continue",
                           "inconclusive_when": {
                               "message_contains": "UNDECIDABLE",
                               "outputs_missing_any": ["e/gate.csv"]}})
    assert node["failure_policy"] == "continue"
    assert node["inconclusive_when"] == {
        "message_contains": "UNDECIDABLE",
        "outputs_missing_any": ["e/gate.csv"]}
    node2 = normalize_node({"node_id": "n", "kind": "solve",
                            "failure_policy": "abort"})
    assert node2["failure_policy"] == "abort"   # 显式声明原样保留
    node3 = normalize_node({"node_id": "n", "kind": "solve",
                            "inconclusive_when": {}})   # 空判据=未声明
    assert "inconclusive_when" not in node3
    assert "failure_policy" not in node3


def test_schema_rejects_invalid_new_fields() -> None:
    with pytest.raises(DagSchemaError, match="failure_policy"):
        normalize_node({"node_id": "n", "kind": "solve",
                        "failure_policy": "restart"})
    with pytest.raises(DagSchemaError, match="inconclusive_when"):
        normalize_node({"node_id": "n", "kind": "solve",
                        "inconclusive_when": "UNDECIDABLE"})
    with pytest.raises(DagSchemaError, match="未知判据键"):
        normalize_node({"node_id": "n", "kind": "solve",
                        "inconclusive_when": {"message_contins": "x"}})
    with pytest.raises(DagSchemaError, match="空判据"):
        normalize_node({"node_id": "n", "kind": "solve",
                        "inconclusive_when": {"message_contains": None}})
    with pytest.raises(DagSchemaError, match="outputs_missing_any"):
        normalize_node({"node_id": "n", "kind": "solve",
                        "inconclusive_when": {"outputs_missing_any": [1]}})
    with pytest.raises(DagSchemaError, match="message_contains"):
        normalize_node({"node_id": "n", "kind": "solve",
                        "inconclusive_when": {"message_contains": ""}})
