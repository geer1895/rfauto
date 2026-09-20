"""阶段 2.2：工具调用层基准 gold set 测试。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestGoldsetStructure:
    def test_loads_with_30_plus_tasks(self):
        from rfauto.service.goldset_service import load_goldset

        gold = load_goldset()
        assert gold["ok"], gold.get("errors")
        assert gold["n_tasks"] >= 30, "验收口径 30-45 任务"
        levels = {t["level"] for t in gold["tasks"]}
        assert levels >= {1, 2, 3}

    def test_ids_unique_and_fields_complete(self):
        from rfauto.service.goldset_service import load_goldset

        gold = load_goldset()
        assert gold["ok"]
        ids = [t["id"] for t in gold["tasks"]]
        assert len(ids) == len(set(ids))


class TestScoring:
    def test_perfect_trajectory_full_score(self):
        from rfauto.service.goldset_service import load_goldset, score_trajectory

        gold = load_goldset()
        task = next(t for t in gold["tasks"] if t["id"] == "g001_validate_recipe")
        traj = [{"tool": "validate", "args": {"recipe": "recipes/wilkinson_pd_v1.yaml"}}]
        r = score_trajectory(task, traj)
        assert r == {"id": "g001_validate_recipe", "tsa": 1, "fca": 1, "pass3": 1}

    def test_wrong_tool_zero_tsa(self):
        from rfauto.service.goldset_service import load_goldset, score_trajectory

        gold = load_goldset()
        task = next(t for t in gold["tasks"] if t["id"] == "g005_autotune")
        traj = [{"tool": "tune", "args": {"recipe": "x"}}]
        r = score_trajectory(task, traj)
        assert r["tsa"] == 0 and r["fca"] == 0

    def test_readonly_interleaving_tolerated(self):
        from rfauto.service.goldset_service import load_goldset, score_trajectory

        gold = load_goldset()
        task = next(t for t in gold["tasks"] if t["id"] == "g102_validate_before_run")
        traj = [
            {"tool": "doctor", "args": {}},                       # 只读穿插
            {"tool": "validate", "args": {"recipe": "r.yaml"}},
            {"tool": "run", "args": {"recipe": "r.yaml", "dry_run": True}},
        ]
        r = score_trajectory(task, traj)
        assert r["tsa"] == 1 and r["fca"] == 1 and r["pass3"] == 1

    def test_placeholder_arg_requires_presence(self):
        from rfauto.service.goldset_service import load_goldset, score_trajectory

        gold = load_goldset()
        task = next(t for t in gold["tasks"] if t["id"] == "g008_runs_compare")
        missing = [{"tool": "runs compare", "args": {}}]
        present = [{"tool": "runs compare",
                    "args": {"run_id_a": "20260905_aa", "run_id_b": "20260905_bb"}}]
        assert score_trajectory(task, missing)["fca"] == 0
        assert score_trajectory(task, present)["fca"] == 1

    def test_aggregate_gate(self):
        from rfauto.service.goldset_service import evaluate_trajectory_set, load_goldset

        gold = load_goldset()
        perfect = [{"id": t["id"],
                    "trajectory": [{"tool": c["tool"], "args": c.get("args") or {}}
                                   for c in t["expected"]["calls"]]}
                   for t in gold["tasks"]]
        r = evaluate_trajectory_set(perfect)
        assert r["ok"]
        assert r["tsa"] == 1.0 and r["gate_tsa"] == "PASS"


# ---------------------------------------------------------------------------
# §10.20 补强⑬：金标回归门（runtime/协议变更后一键回归；确定性、无网络）
# ---------------------------------------------------------------------------


def _perfect_trajectories(gold):
    return [
        {"id": t["id"],
         "trajectory": [{"tool": c["tool"], "args": dict(c.get("args") or {})}
                        for c in t["expected"]["calls"]]}
        for t in gold["tasks"]
    ]


def _small_goldset(tmp_path, n=5):
    import yaml

    tasks = [{"id": f"t{i}", "level": 1, "prompt": f"跑第 {i} 次",
              "expected": {"calls": [{"tool": "run", "args": {}}]}}
             for i in range(n)]
    path = tmp_path / "small_goldset.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "tasks": tasks},
                                   allow_unicode=True), encoding="utf-8")
    return path, tasks


class TestGoldsetRegressionGate:
    def test_gate_green_on_current_runtime(self):
        from rfauto.service.goldset_service import goldset_expected_tools, load_goldset, run_goldset_regression

        gold = load_goldset()
        surface = goldset_expected_tools(gold)
        r = run_goldset_regression(_perfect_trajectories(gold),
                                   runtime_tools=surface)
        assert r["ok"] and r["gate"] == "PASS"
        assert r["n_scored"] == gold["n_tasks"]
        assert r["report"]["tsa"] == 1.0 and r["report"]["fca"] == 1.0
        assert r["missing_tools"] == []
        assert (r["expected_protocol"]["sha256"]
                == r["runtime_protocol"]["sha256"])

    def test_gate_red_on_protocol_drift(self):
        from rfauto.service.goldset_service import goldset_expected_tools, load_goldset, run_goldset_regression

        gold = load_goldset()
        surface = [t for t in goldset_expected_tools(gold) if t != "validate"]
        r = run_goldset_regression(_perfect_trajectories(gold),
                                   runtime_tools=surface)
        assert not r["ok"] and r["gate"] == "FAIL"
        assert "validate" in r["missing_tools"]
        assert "协议面回归" in r["reasons"][0]

    def test_gate_red_on_trajectory_drift(self):
        from rfauto.service.goldset_service import goldset_expected_tools, load_goldset, run_goldset_regression

        gold = load_goldset()
        trajs = _perfect_trajectories(gold)
        for item in trajs[:5]:
            item["trajectory"] = [{"tool": "renamed_tool_v2", "args": {}}]
        r = run_goldset_regression(trajs,
                                   runtime_tools=goldset_expected_tools(gold))
        assert not r["ok"] and r["gate"] == "FAIL"
        assert r["report"]["tsa"] < 0.9
        assert any("TSA" in reason for reason in r["reasons"])

    def test_gate_red_on_partial_coverage(self):
        from rfauto.service.goldset_service import goldset_expected_tools, load_goldset, run_goldset_regression

        gold = load_goldset()
        r = run_goldset_regression(_perfect_trajectories(gold)[:3],
                                   runtime_tools=goldset_expected_tools(gold))
        assert not r["ok"] and r["n_scored"] == 3
        assert "未覆盖全部金标任务" in r["reasons"][0]

    def test_gate_refuses_vacuous_run(self):
        from rfauto.service.goldset_service import run_goldset_regression

        no_input = run_goldset_regression()
        assert not no_input["ok"] and "防空转" in no_input["reasons"][0]
        empty = run_goldset_regression(trajectories=[])
        assert not empty["ok"] and "防空转" in empty["reasons"][0]

    def test_gate_reference_provider_one_click(self):
        from rfauto.service.goldset_service import (
            goldset_expected_tools,
            load_goldset,
            reference_trajectory_provider,
            run_goldset_regression,
        )

        gold = load_goldset()
        r = run_goldset_regression(
            trajectory_provider=reference_trajectory_provider,
            runtime_tools=goldset_expected_tools(gold))
        assert r["ok"] and r["gate"] == "PASS"

    def test_provider_channel_pinned_offline(self, monkeypatch):
        import socket

        from rfauto.service.goldset_service import load_goldset, reference_trajectory_provider, run_goldset_regression

        def _boom(*_args, **_kwargs):
            raise AssertionError("金标门不得触网（#139）")

        monkeypatch.setattr(socket.socket, "connect", _boom)
        monkeypatch.setattr(socket, "create_connection", _boom)

        calls = []

        def provider(task):
            calls.append(task["id"])
            return reference_trajectory_provider(task)

        r = run_goldset_regression(trajectory_provider=provider)
        assert r["ok"] and r["gate"] == "PASS"
        assert len(calls) == load_goldset()["n_tasks"]

    def test_threshold_boundary(self, tmp_path):
        from rfauto.service.goldset_service import run_goldset_regression

        path, tasks = _small_goldset(tmp_path, n=5)
        trajs = [{"id": t["id"],
                  "trajectory": [{"tool": "run", "args": {}}]}
                 for t in tasks]
        trajs[-1]["trajectory"] = [{"tool": "nope", "args": {}}]  # 4/5 = 0.8
        at = run_goldset_regression(trajs, goldset_path=path,
                                    min_tsa=0.8, min_fca=0.8)
        below = run_goldset_regression(trajs, goldset_path=path,
                                       min_tsa=0.81, min_fca=0.8)
        assert at["ok"] and at["report"]["tsa"] == 0.8
        assert not below["ok"] and "TSA" in below["reasons"][0]

    def test_empty_goldset_rejected(self, tmp_path):
        from rfauto.service.goldset_service import run_goldset_regression

        path, _ = _small_goldset(tmp_path, n=0)
        r = run_goldset_regression(trajectories=[], goldset_path=path)
        assert not r["ok"] and "金标集为空" in r["reasons"][0]

    def test_missing_goldset_file_rejected(self, tmp_path):
        from rfauto.service.goldset_service import run_goldset_regression

        r = run_goldset_regression(trajectories=[],
                                   goldset_path=tmp_path / "nope.yaml")
        assert not r["ok"] and "不存在" in r["errors"][0]

    def test_invalid_inputs_rejected(self, tmp_path):
        from rfauto.service.goldset_service import run_goldset_regression

        assert not run_goldset_regression(trajectories="not-a-list")["ok"]
        assert not run_goldset_regression(trajectories=[42])["ok"]
        path, _ = _small_goldset(tmp_path, n=2)
        assert not run_goldset_regression(
            trajectories=[{"id": "ghost", "trajectory": []}],
            goldset_path=path)["ok"]
        assert not run_goldset_regression(
            trajectories=[], goldset_path=path, runtime_tools="validate")["ok"]

    def test_gate_deterministic_same_input(self):
        import json

        from rfauto.service.goldset_service import goldset_expected_tools, load_goldset, run_goldset_regression

        gold = load_goldset()
        trajs = _perfect_trajectories(gold)
        surface = goldset_expected_tools(gold)
        first = run_goldset_regression(trajs, runtime_tools=surface)
        second = run_goldset_regression(trajs, runtime_tools=surface)
        assert (json.dumps(first, sort_keys=True, ensure_ascii=False)
                == json.dumps(second, sort_keys=True, ensure_ascii=False))

    def test_protocol_surface_sorted_dedup_stable(self):
        from rfauto.service.goldset_service import protocol_surface

        a = protocol_surface(["b", "a", "b", " a ", ""])
        assert a["tools"] == ["a", "b"] and a["n_tools"] == 2
        assert a["sha256"] == protocol_surface(["a", "b"])["sha256"]
        assert a["sha256"] != protocol_surface(["a", "c"])["sha256"]
