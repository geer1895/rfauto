"""WP3.7 AgentBench 智能体基准测试：公开/私有双集 + 两轴打分 + 回归门 + CLI 薄壳。

全部离线（#139：monkeypatch 钉住 socket 通道）、确定性、零真机。
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

runner = CliRunner()

#: 评测任务集（tests/gold/agentbench_public.yaml）不随本仓分发（规划中的后续
#: 公开项，见 README 路线图）；缺集时依赖它的测试整体 skip，打分/CLI 逻辑
#: 测试用合成任务集照常运行。
PUBLIC_SET = (Path(__file__).resolve().parents[1] / "gold"
              / "agentbench_public.yaml")
requires_public_set = pytest.mark.skipif(
    not PUBLIC_SET.exists(),
    reason="agentbench public task set not distributed in this repo "
           "(see README roadmap)")


# ---------------------------------------------------------------------------
# 工厂：任务集与埋点记录
# ---------------------------------------------------------------------------

def _task(tid, calls, *, artifacts=None, numerics=None, family="template_render",
          level=1):
    expected = {"calls": calls}
    if artifacts is not None:
        expected["artifacts"] = artifacts
    if numerics is not None:
        expected["numeric"] = numerics
    return {"id": tid, "family": family, "level": level, "prompt": f"任务 {tid}",
            "expected": expected}


def _write_set(tmp_path, name, tasks):
    p = tmp_path / name
    p.write_text(yaml.safe_dump({"version": 1, "tasks": tasks},
                                allow_unicode=True), encoding="utf-8")
    return p


def _call(tool, **args):
    return {"tool": tool, "args": args}


# ---------------------------------------------------------------------------
# 公开集结构（E11 四族 + ground truth 可溯）
# ---------------------------------------------------------------------------

@requires_public_set
class TestPublicSetStructure:
    def test_public_set_loads_with_e11_families(self):
        from rfauto.service.agent_bench import load_bench_set

        bench = load_bench_set()
        assert bench["ok"], bench.get("errors")
        assert bench["n_tasks"] >= 10
        families = {t["family"] for t in bench["tasks"]}
        assert {"template_render", "fail_diagnosis", "port_fix",
                "campaign"} <= families, families
        levels = {t["level"] for t in bench["tasks"]}
        assert levels >= {1, 2, 3}

    def test_every_ground_truth_numeric_has_provenance(self):
        from rfauto.service.agent_bench import load_bench_set

        bench = load_bench_set()
        assert bench["ok"]
        n_numeric = 0
        for t in bench["tasks"]:
            for item in (t.get("expected") or {}).get("numeric") or []:
                n_numeric += 1
                assert str(item.get("source") or "").strip(), \
                    f"{t['id']} 数值判据缺 provenance source"
        assert n_numeric >= 3, "公开集应有 ≥3 条 ground truth 数值判据"

    def test_expected_tools_within_goldset_vocabulary(self):
        """AgentBench 与 goldset 共用同一 typed 调用词汇（同一 runtime 协议面）。"""
        from rfauto.service.agent_bench import load_bench_set
        from rfauto.service.goldset_service import (
            goldset_expected_tools,
            load_goldset,
        )

        bench_tools = set(goldset_expected_tools(load_bench_set()))
        gold_tools = set(goldset_expected_tools(load_goldset()))
        unknown = bench_tools - gold_tools
        assert not unknown, f"超出既有协议词汇的工具: {sorted(unknown)}"


# ---------------------------------------------------------------------------
# 两轴打分
# ---------------------------------------------------------------------------

class TestTwoAxisScoring:
    def _task(self):
        return _task(
            "t1", [_call("validate", recipe="r.yaml"), _call("run", dry_run=True)],
            artifacts=["gate_report", "s_params"],
            numerics=[{"metric": "f_res_ghz", "value": 2.16, "tol_pct": 5.0,
                       "source": "closed-form"}])

    def test_perfect_record_full_score(self):
        from rfauto.service.agent_bench import score_agent_task

        r = score_agent_task(self._task(), {
            "trajectory": [_call("validate", recipe="r.yaml"),
                           _call("run", dry_run=True)],
            "artifacts": ["gate_report", "s_params"],
            "numeric": {"f_res_ghz": 2.16},
        })
        assert r["tsa"] == 1 and r["fca"] == 1
        assert r["abstraction"] == 1.0 and r["execution"] == 1.0

    def test_wrong_tool_zeroes_abstraction(self):
        from rfauto.service.agent_bench import score_agent_task

        r = score_agent_task(self._task(), {
            "trajectory": [_call("tune", recipe="r.yaml")],
            "artifacts": ["gate_report", "s_params"],
            "numeric": {"f_res_ghz": 2.16},
        })
        assert r["tsa"] == 0 and r["fca"] == 0 and r["abstraction"] == 0.0
        assert r["execution"] == 1.0, "执行轴与抽象轴独立"

    def test_right_tool_wrong_args_partial_abstraction(self):
        from rfauto.service.agent_bench import score_agent_task

        r = score_agent_task(self._task(), {
            "trajectory": [_call("validate", recipe="r.yaml"), _call("run")],
            "artifacts": [], "numeric": {},
        })
        assert r["tsa"] == 1 and r["fca"] == 0
        assert r["abstraction"] == 0.5
        # dry_run 缺失 → FCA=0；工件/数值全缺 → 执行轴 0
        assert r["execution"] == 0.0

    def test_numeric_tolerance_semantics(self):
        from rfauto.service.agent_bench import score_agent_task

        task = _task("t2", [_call("run")], numerics=[
            {"metric": "s21_db", "value": -3.4, "tol_pct": 15.0,
             "source": "ref"}])
        # 容差 ±0.51dB：半容差内过、倍容差外不过（#175：不赌浮点精确边界）
        within = score_agent_task(task, {
            "trajectory": [_call("run")],
            "numeric": {"s21_db": -3.4 + 0.15 * 3.4 * 0.5}})
        beyond = score_agent_task(task, {
            "trajectory": [_call("run")],
            "numeric": {"s21_db": -3.4 - 0.15 * 3.4 * 2.0}})
        assert within["numeric"] == 1.0
        assert beyond["numeric"] == 0.0

    def test_non_numeric_produced_value_fails(self):
        from rfauto.service.agent_bench import score_agent_task

        task = _task("t3", [_call("run")], numerics=[
            {"metric": "f0_ghz", "value": 2.4, "tol_pct": 1.0, "source": "x"}])
        for bad in ("2.4GHz 文本", None, True, [2.4]):
            r = score_agent_task(task, {"trajectory": [_call("run")],
                                        "numeric": {"f0_ghz": bad}})
            assert r["numeric"] == 0.0, bad
            assert r["numeric_failed"] == ["f0_ghz"]

    def test_execution_axis_averages_declared_facets_only(self):
        from rfauto.service.agent_bench import score_agent_task

        half_artifacts = _task("t4", [_call("run")],
                               artifacts=["a1", "a2"])
        r = score_agent_task(half_artifacts, {
            "trajectory": [_call("run")], "artifacts": ["a1"]})
        assert r["artifact"] == 0.5 and r["execution"] == 0.5
        # 无工件声明 → 只考数值维度
        only_numeric = _task("t5", [_call("run")], numerics=[
            {"metric": "m", "value": 1.0, "tol_pct": 1.0, "source": "x"}])
        r = score_agent_task(only_numeric, {
            "trajectory": [_call("run")], "numeric": {"m": 1.0}})
        assert r["artifact"] == 1.0 and r["execution"] == 1.0
        # 两维度都声明 → 宏平均
        both = _task("t6", [_call("run")], artifacts=["a1"], numerics=[
            {"metric": "m", "value": 1.0, "tol_pct": 1.0, "source": "x"}])
        r = score_agent_task(both, {"trajectory": [_call("run")],
                                    "artifacts": [], "numeric": {"m": 1.0}})
        assert r["execution"] == 0.5

    def test_undeclared_facets_execution_full(self):
        from rfauto.service.agent_bench import score_agent_task

        bare = _task("t7", [_call("doctor")])
        r = score_agent_task(bare, {"trajectory": [_call("doctor")], "artifacts": []})
        assert r["execution"] == 1.0

    def test_readonly_interleaving_tolerated(self):
        from rfauto.service.agent_bench import score_agent_task

        r = score_agent_task(self._task(), {
            "trajectory": [_call("doctor"), _call("validate", recipe="r.yaml"),
                           _call("run", dry_run=True)],
            "artifacts": ["gate_report", "s_params"],
            "numeric": {"f_res_ghz": 2.16},
        })
        assert r["abstraction"] == 1.0

    @requires_public_set
    def test_malformed_trajectory_reported_not_raised(self):
        from rfauto.service.agent_bench import _score_one_set, load_bench_sets

        sets = load_bench_sets()
        bench = sets["public"]
        report = _score_one_set(bench, [{"id": bench["tasks"][0]["id"],
                                         "trajectory": [42]}])
        assert report["results"][0].get("error") == "trajectory 项必须是映射"


# ---------------------------------------------------------------------------
# 公开/私有双集（防污染）
# ---------------------------------------------------------------------------

@requires_public_set
class TestDualSets:
    def test_default_public_only_not_configured(self):
        from rfauto.service.agent_bench import load_bench_sets

        sets = load_bench_sets()
        assert sets["ok"] and sets["private"] is None
        assert sets["private_status"] == "not_configured"

    def test_private_via_env(self, tmp_path, monkeypatch):
        from rfauto.service.agent_bench import PRIVATE_SET_ENV, load_bench_sets

        p = _write_set(tmp_path, "private.yaml", [
            _task("p1", [_call("run")], artifacts=["x"])])
        monkeypatch.setenv(PRIVATE_SET_ENV, str(p))
        sets = load_bench_sets()
        assert sets["ok"] and sets["private_status"] == "loaded"
        assert sets["private"]["n_tasks"] == 1

    def test_private_missing_file_is_hard_error(self, tmp_path):
        from rfauto.service.agent_bench import load_bench_sets

        sets = load_bench_sets(private_path=tmp_path / "nope.yaml")
        assert not sets["ok"]
        assert sets["private_status"] == "missing"
        assert any("不存在" in e for e in sets["errors"])

    def test_private_invalid_structure_is_hard_error(self, tmp_path):
        from rfauto.service.agent_bench import load_bench_sets

        p = _write_set(tmp_path, "bad.yaml", [
            {"id": "x", "level": 1, "prompt": "p",
             "expected": {"calls": [_call("run")]}}])  # 缺 family
        sets = load_bench_sets(private_path=p)
        assert not sets["ok"] and sets["private_status"] == "invalid"
        assert any("family" in e for e in sets["errors"])

    def test_id_overlap_is_contamination(self, tmp_path):
        from rfauto.service.agent_bench import load_bench_sets

        p = _write_set(tmp_path, "leak.yaml", [
            _task("ab001_render_wilkinson_fake", [_call("run")])])
        sets = load_bench_sets(private_path=p)
        assert not sets["ok"]
        assert sets["overlap_ids"] == ["ab001_render_wilkinson_fake"]
        assert any("污染" in e for e in sets["errors"])

    @requires_public_set
    def test_evaluate_partition_mixed_records(self, tmp_path):
        from rfauto.service.agent_bench import evaluate_agentbench, load_bench_set

        p = _write_set(tmp_path, "private.yaml", [
            _task("p1", [_call("run")], artifacts=["x"])])
        pub = load_bench_set()["tasks"][0]
        records = [
            {"id": pub["id"], "trajectory": [_call(c["tool"], **(c.get("args") or {}))
                                             for c in pub["expected"]["calls"]],
             "artifacts": (pub["expected"].get("artifacts") or []),
             "numeric": {n["metric"]: n["value"]
                         for n in pub["expected"].get("numeric") or []}},
            {"id": "p1", "trajectory": [_call("run")], "artifacts": ["x"]},
            {"id": "ghost", "trajectory": []},
        ]
        r = evaluate_agentbench(records, private_path=p)
        assert r["ok"]
        assert r["sets"]["public"]["n_scored"] == 1
        assert r["sets"]["private"]["n_scored"] == 1
        assert r["unknown_ids"] == ["ghost"]
        assert r["contamination"]["overlap_ids"] == []


# ---------------------------------------------------------------------------
# 回归门
# ---------------------------------------------------------------------------

@requires_public_set
class TestAgentbenchGate:
    def test_gate_green_with_reference_provider(self):
        from rfauto.service.agent_bench import (
            reference_agentbench_provider,
            run_agentbench_regression,
        )

        r = run_agentbench_regression(trajectory_provider=reference_agentbench_provider)
        assert r["ok"] and r["gate"] == "PASS"
        assert r["n_scored"] == r["n_tasks"]
        assert r["report"]["combined"]["abstraction"] == 1.0
        assert r["report"]["combined"]["execution"] == 1.0

    def test_gate_red_below_execution_threshold(self):
        from rfauto.service.agent_bench import load_bench_set, run_agentbench_regression

        tasks = load_bench_set()["tasks"]
        records = [{"id": t["id"], "trajectory": [], "artifacts": [],
                    "numeric": {}} for t in tasks]
        r = run_agentbench_regression(records)
        assert not r["ok"] and r["gate"] == "FAIL"
        assert any("任务抽象轴" in x for x in r["reasons"])
        assert any("执行轴" in x for x in r["reasons"])

    def test_gate_protocol_drift(self):
        from rfauto.service.agent_bench import (
            load_bench_set,
            reference_agentbench_provider,
            run_agentbench_regression,
        )
        from rfauto.service.goldset_service import goldset_expected_tools

        tools = [t for t in goldset_expected_tools(load_bench_set())
                 if t != "p0"]
        r = run_agentbench_regression(
            trajectory_provider=reference_agentbench_provider,
            runtime_tools=tools)
        assert not r["ok"] and "p0" in r["missing_tools"]
        assert "协议面回归" in r["reasons"][0]

    def test_gate_rejects_bad_inputs(self):
        from rfauto.service.agent_bench import run_agentbench_regression

        assert not run_agentbench_regression()["ok"]
        assert not run_agentbench_regression(records=[])["ok"]
        assert not run_agentbench_regression(records="x")["ok"]
        assert not run_agentbench_regression(records=[42])["ok"]
        assert not run_agentbench_regression(
            records=[{"id": "ghost", "trajectory": []}])["ok"]
        assert not run_agentbench_regression(
            trajectory_provider=lambda _t: [],
            runtime_tools="validate")["ok"]

    def test_gate_partial_coverage_and_lenient(self, tmp_path):
        from rfauto.service.agent_bench import run_agentbench_regression

        p = _write_set(tmp_path, "s.yaml", [
            _task("a", [_call("run")]), _task("b", [_call("validate")])])
        partial = [{"id": "a", "trajectory": [_call("run")]}]
        strict = run_agentbench_regression(partial, public_path=p)
        assert not strict["ok"] and "未覆盖全部基准任务" in strict["reasons"][0]
        lenient = run_agentbench_regression(partial, public_path=p,
                                            require_full_coverage=False)
        assert lenient["ok"]

    def test_gate_require_private(self, tmp_path):
        from rfauto.service.agent_bench import (
            reference_agentbench_provider,
            run_agentbench_regression,
        )

        red = run_agentbench_regression(
            trajectory_provider=reference_agentbench_provider,
            require_private=True)
        assert not red["ok"] and "私有集" in red["reasons"][0]
        p = _write_set(tmp_path, "priv.yaml", [
            _task("p1", [_call("kicad")], artifacts=["board"])])
        green = run_agentbench_regression(
            trajectory_provider=reference_agentbench_provider,
            private_path=p, require_private=True)
        assert green["ok"] and green["n_tasks"] == 12

    def test_provider_channel_pinned_offline(self, monkeypatch):
        from rfauto.service.agent_bench import (
            reference_agentbench_provider,
            run_agentbench_regression,
        )

        def _boom(*_a, **_k):
            raise AssertionError("基准门不得触网（#139）")

        monkeypatch.setattr(socket.socket, "connect", _boom)
        monkeypatch.setattr(socket, "create_connection", _boom)
        calls = []

        def provider(task):
            calls.append(task["id"])
            return reference_agentbench_provider(task)

        r = run_agentbench_regression(trajectory_provider=provider)
        assert r["ok"] and len(calls) == r["n_tasks"]

    def test_provider_exception_and_bad_return_red(self):
        from rfauto.service.agent_bench import run_agentbench_regression

        def _raise(_task):
            raise RuntimeError("llm 通道断")

        r = run_agentbench_regression(trajectory_provider=_raise)
        assert not r["ok"] and "提供器异常" in r["reasons"][0]
        r = run_agentbench_regression(trajectory_provider=lambda _t: 42)
        assert not r["ok"] and "返回类型非法" in r["reasons"][0]

    def test_provider_plain_list_treated_as_trajectory(self, tmp_path):
        from rfauto.service.agent_bench import run_agentbench_regression

        p = _write_set(tmp_path, "s.yaml", [
            _task("a", [_call("run")], artifacts=["x"])])
        r = run_agentbench_regression(
            trajectory_provider=lambda _t: [_call("run")],
            public_path=p, min_execution=1.0)
        # 仅回放轨迹、不产工件 → 执行轴 0（声明了工件维度）
        assert not r["ok"] and any("执行轴" in x for x in r["reasons"])

    def test_gate_deterministic_same_input(self):
        from rfauto.service.agent_bench import (
            reference_agentbench_provider,
            run_agentbench_regression,
        )

        first = run_agentbench_regression(
            trajectory_provider=reference_agentbench_provider)
        second = run_agentbench_regression(
            trajectory_provider=reference_agentbench_provider)
        assert (json.dumps(first, sort_keys=True, ensure_ascii=False)
                == json.dumps(second, sort_keys=True, ensure_ascii=False))

    def test_threshold_boundary_small_set(self, tmp_path):
        from rfauto.service.agent_bench import run_agentbench_regression

        p = _write_set(tmp_path, "s.yaml", [
            _task("a", [_call("run")]),
            _task("b", [_call("validate")])])
        records = [{"id": "a", "trajectory": [_call("run")]},
                   {"id": "b", "trajectory": [_call("nope")]}]
        at = run_agentbench_regression(records, public_path=p,
                                       min_abstraction=0.5, min_execution=1.0)
        below = run_agentbench_regression(records, public_path=p,
                                          min_abstraction=0.51,
                                          min_execution=1.0)
        assert at["ok"] and at["report"]["combined"]["abstraction"] == 0.5
        assert not below["ok"] and "任务抽象轴" in below["reasons"][0]


# ---------------------------------------------------------------------------
# CLI 薄壳（typer CliRunner 直接驱动 bench_app；main.py 注册一行后行为一致）
# ---------------------------------------------------------------------------

@requires_public_set
class TestCliBenchApp:
    def test_help_lists_both_gates(self):
        from rfauto.cli.bench_app import bench_app

        result = runner.invoke(bench_app, ["--help"])
        assert result.exit_code == 0
        assert "goldset" in result.output and "agentbench" in result.output

    def test_goldset_default_reference_green(self):
        from rfauto.cli.bench_app import bench_app

        result = runner.invoke(bench_app, ["goldset"])
        assert result.exit_code == 0, result.output
        assert '"gate": "PASS"' in result.output

    def test_goldset_drifted_trajectories_red(self, tmp_path):
        from rfauto.cli.bench_app import bench_app
        from rfauto.service.goldset_service import load_goldset

        gold = load_goldset()
        trajs = [{"id": t["id"], "trajectory": [_call("renamed_tool_v2")]}
                 for t in gold["tasks"]]
        p = tmp_path / "traj.json"
        p.write_text(json.dumps(trajs), encoding="utf-8")
        result = runner.invoke(bench_app, ["goldset", "--trajectories", str(p)])
        assert result.exit_code == 1
        assert '"gate": "FAIL"' in result.output and "TSA" in result.output

    def test_goldset_runtime_tools_auto_is_protocol_drift(self):
        """agent 聊天通道工具面 ≠ CLI 金标面——门应当面抓出协议漂移。"""
        from rfauto.cli.bench_app import bench_app

        result = runner.invoke(bench_app, ["goldset", "--runtime-tools", "auto"])
        assert result.exit_code == 1
        assert "协议面回归" in result.output

    def test_goldset_missing_trajectories_file_exit2(self, tmp_path):
        from rfauto.cli.bench_app import bench_app

        result = runner.invoke(
            bench_app, ["goldset", "--trajectories", str(tmp_path / "no.json")])
        assert result.exit_code == 2

    def test_agentbench_default_reference_green(self):
        from rfauto.cli.bench_app import bench_app

        result = runner.invoke(bench_app, ["agentbench"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["gate"] == "PASS"
        assert payload["report"]["combined"]["execution"] == 1.0

    def test_agentbench_numeric_drift_records_red(self, tmp_path):
        from rfauto.cli.bench_app import bench_app
        from rfauto.service.agent_bench import load_bench_set

        tasks = load_bench_set()["tasks"]
        records = []
        for t in tasks:
            numeric = {n["metric"]: n["value"] * 3.0
                       for n in (t["expected"].get("numeric") or [])}
            records.append({
                "id": t["id"],
                "trajectory": [_call(c["tool"], **(c.get("args") or {}))
                               for c in t["expected"]["calls"]],
                "artifacts": list(t["expected"].get("artifacts") or []),
                "numeric": numeric})
        p = tmp_path / "records.json"
        p.write_text(json.dumps(records), encoding="utf-8")
        # 数值全漂 3 倍：执行轴宏平均被两个数值任务拉低，收紧阈值后门红
        result = runner.invoke(
            bench_app, ["agentbench", "--records", str(p),
                        "--min-execution", "0.95"])
        assert result.exit_code == 1
        assert '"gate": "FAIL"' in result.output and "执行轴" in result.output

    def test_agentbench_private_set_flags(self, tmp_path):
        from rfauto.cli.bench_app import bench_app

        result = runner.invoke(
            bench_app, ["agentbench", "--require-private"])
        assert result.exit_code == 1 and "私有集" in result.output

        p = _write_set(tmp_path, "priv.yaml", [
            _task("p1", [_call("kicad")], artifacts=["board"])])
        result = runner.invoke(
            bench_app, ["agentbench", "--private-set", str(p),
                        "--require-private"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["private_status"] == "loaded"
