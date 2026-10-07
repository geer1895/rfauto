"""A3 pass^k × 成本双轴回收钉（月计划 I 流 B2；#118 合成裁判 + ge1⑦ 固定 rng）。

裁判预声明（service/agent_bench.py 模块 docstring + 函数 docstring 同源）：
- 估计量逐位回收：pass_hat_k(3,5,2)=C(3,2)/C(5,2)=0.3；k=1 退化为 p/n；
  p<k→0.0；
- 统计回收（固定 rng，确定性）：Bernoulli(p=0.6) × n=400，k=4 → 估计量
  距 0.6⁴=0.1296 的偏差 ≤0.06（预声明容差 ≈3σ，σ 由 p̂ 抽样波动经
  δ(pass^k)≈4p³·σ_p̂≈0.02 量级定）；
- 端到端回收：合成任务集 5 trial 3 过 → pass^2=0.3；成本轴线性外推
  cost_at_k=k·cost_mean 逐位；
- fail-closed：零覆盖任务/未知 id/非法 cost/k 出界 全部 gate=FAIL 或
  ValueError，绝不空跑绿。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service.agent_bench import (
    evaluate_agentbench_consistency,
    pass_hat_k,
)

# ── 估计量逐位回收 ──────────────────────────────────────────────────────────

class TestPassHatKExact:
    def test_canonical_pin_3_of_5_k2(self):
        assert pass_hat_k(3, 5, 2) == pytest.approx(3 / 10)

    def test_k1_degenerates_to_pass_rate(self):
        assert pass_hat_k(2, 5, 1) == pytest.approx(0.4)
        assert pass_hat_k(0, 7, 1) == 0.0

    def test_all_pass_k_n_is_one(self):
        assert pass_hat_k(5, 5, 5) == 1.0
        assert pass_hat_k(4, 4, 2) == pytest.approx(1.0)

    def test_pass_below_k_is_zero(self):
        assert pass_hat_k(2, 5, 3) == 0.0

    def test_monotone_in_passes(self):
        vals = [pass_hat_k(p, 8, 3) for p in range(0, 9)]
        assert vals == sorted(vals)

    @pytest.mark.parametrize("args", [
        (True, 5, 2), (3.0, 5, 2), (3, 5.0, 2), (3, 5, True),
        (3, 0, 1), (3, 5, 0), (3, 5, 6), (6, 5, 2), (-1, 5, 2),
    ])
    def test_invalid_inputs_raise(self, args):
        with pytest.raises(ValueError):
            pass_hat_k(*args)


# ── 统计回收（固定 rng，ge1⑦ 确定性） ──────────────────────────────────────

class TestStatisticalRecovery:
    def test_bernoulli_p06_k4_n400(self):
        rng = np.random.default_rng(20260928)
        n, p_true, k = 400, 0.6, 4
        passes = int((rng.random(n) < p_true).sum())
        est = pass_hat_k(passes, n, k)
        assert abs(est - p_true ** k) <= 0.06  # 预声明容差（≈3σ）
        # 同种子确定性：重放逐位一致
        rng2 = np.random.default_rng(20260928)
        passes2 = int((rng2.random(n) < p_true).sum())
        assert pass_hat_k(passes2, n, k) == est

    def test_extreme_cases_exact(self):
        rng = np.random.default_rng(7)
        n = 50
        assert pass_hat_k(n, n, 3) == 1.0
        assert pass_hat_k(0, n, 3) == 0.0
        single = int((rng.random(n) < 0.9).sum())
        assert pass_hat_k(single, n, 1) == pytest.approx(single / n)


# ── 端到端（合成任务集 × score_agent_task 判定） ────────────────────────────

def _task(tid: str, artifact: str) -> dict:
    return {"id": tid, "family": "template_render", "level": 1,
            "prompt": f"任务 {tid}",
            "expected": {"calls": [{"tool": "list_solvers", "args": {}}],
                         "artifacts": [artifact]}}


def _write_set(tmp_path: Path, tasks: list[dict]) -> Path:
    p = tmp_path / "bench.yaml"
    p.write_text(yaml.safe_dump({"version": 1, "tasks": tasks},
                                allow_unicode=True), encoding="utf-8")
    return p


def _trial(tid: str, *, ok: bool, cost: float | None = None) -> dict:
    rec: dict = {"id": tid,
                 "trajectory": [{"tool": "list_solvers", "args": {}}],
                 "artifacts": ["s_params"] if ok else []}
    if cost is not None:
        rec["cost"] = cost
    return rec


class TestEvaluateConsistencyEndToEnd:
    def test_canonical_set_recovery(self, tmp_path):
        set_path = _write_set(tmp_path, [_task("t1", "s_params")])
        trials = [_trial("t1", ok=True, cost=1.0),
                  _trial("t1", ok=True, cost=2.0),
                  _trial("t1", ok=False, cost=1.5),
                  _trial("t1", ok=True, cost=1.0),
                  _trial("t1", ok=False, cost=2.5)]
        rep = evaluate_agentbench_consistency(trials, k=2, public_path=set_path)
        assert rep["ok"], rep["reasons"]
        row = rep["results"][0]
        assert row["n_trials"] == 5 and row["n_pass"] == 3
        assert row["pass_hat_k"] == pytest.approx(0.3)  # C(3,2)/C(5,2)
        assert row["cost_mean"] == pytest.approx(1.6)
        assert row["cost_at_k"] == pytest.approx(3.2)   # 线性外推 k·mean
        assert row["efficiency"] == pytest.approx(0.3 / 3.2)
        assert rep["pass_hat_k_macro"] == pytest.approx(0.3)

    def test_pass_threshold_relaxed_counts_partial(self, tmp_path):
        set_path = _write_set(tmp_path, [_task("t1", "s_params")])
        partial = {"id": "t1", "trajectory": [], "artifacts": []}  # execution 0
        rep = evaluate_agentbench_consistency(
            [_trial("t1", ok=True), partial], k=1, public_path=set_path,
            pass_threshold=0.5)
        # execution 0 < 0.5 仍不算过；换 1.0 阈值下的 1 过 1 不过=0.5
        assert rep["results"][0]["n_pass"] == 1
        rep2 = evaluate_agentbench_consistency(
            [_trial("t1", ok=True), partial], k=1, public_path=set_path)
        assert rep2["results"][0]["pass_hat_k"] == pytest.approx(0.5)

    def test_cost_axis_all_missing_is_none_not_zero(self, tmp_path):
        set_path = _write_set(tmp_path, [_task("t1", "s_params")])
        rep = evaluate_agentbench_consistency(
            [_trial("t1", ok=True)] * 3, k=2, public_path=set_path)
        assert rep["ok"]
        assert rep["results"][0]["cost_mean"] is None
        assert rep["results"][0]["cost_at_k"] is None
        assert rep["cost_mean_macro"] is None

    def test_invalid_cost_recorded_not_silent(self, tmp_path):
        set_path = _write_set(tmp_path, [_task("t1", "s_params")])
        bad = _trial("t1", ok=True, cost=-1.0)
        good = _trial("t1", ok=True, cost=2.0)
        rep = evaluate_agentbench_consistency([bad, good], k=1,
                                              public_path=set_path)
        row = rep["results"][0]
        assert row["cost_n"] == 1 and row["cost_mean"] == pytest.approx(2.0)
        assert row["cost_errors"] and "-1.0" in row["cost_errors"][0]

    def test_bool_cost_rejected(self, tmp_path):
        set_path = _write_set(tmp_path, [_task("t1", "s_params")])
        rec = _trial("t1", ok=True)
        rec["cost"] = True
        rep = evaluate_agentbench_consistency([rec], k=1, public_path=set_path)
        assert rep["results"][0]["cost_errors"]

    def test_unknown_trial_id_fails_closed(self, tmp_path):
        set_path = _write_set(tmp_path, [_task("t1", "s_params")])
        rep = evaluate_agentbench_consistency(
            [_trial("t1", ok=True), _trial("ghost", ok=True)], k=1,
            public_path=set_path)
        assert rep["gate"] == "FAIL"
        assert "ghost" in rep["unknown_trial_ids"]
        assert any("未知任务 id" in r for r in rep["reasons"])

    def test_zero_coverage_task_fails_closed(self, tmp_path):
        set_path = _write_set(tmp_path, [_task("t1", "s_params"),
                                         _task("t2", "board")])
        rep = evaluate_agentbench_consistency([_trial("t1", ok=True)], k=1,
                                              public_path=set_path)
        assert rep["gate"] == "FAIL"
        assert any("t2" in str(r) for r in rep["reasons"])

    def test_min_pass_hat_k_gate(self, tmp_path):
        set_path = _write_set(tmp_path, [_task("t1", "s_params")])
        trials = [_trial("t1", ok=True), _trial("t1", ok=False),
                  _trial("t1", ok=False)]
        below = evaluate_agentbench_consistency(trials, k=2,
                                                public_path=set_path,
                                                min_pass_hat_k=0.5)
        assert below["gate"] == "FAIL" and below["pass_hat_k_macro"] == 0.0
        above = evaluate_agentbench_consistency(trials, k=1,
                                                public_path=set_path,
                                                min_pass_hat_k=0.3)
        assert above["gate"] == "PASS"

    def test_broken_set_path_fails_closed(self, tmp_path):
        rep = evaluate_agentbench_consistency(
            [_trial("t1", ok=True)], k=1,
            public_path=tmp_path / "missing.yaml")
        assert rep["ok"] is False and rep["gate"] == "FAIL"

    def test_invalid_k_raises(self):
        with pytest.raises(ValueError):
            evaluate_agentbench_consistency([], k=0)
        with pytest.raises(ValueError):
            evaluate_agentbench_consistency([], k=True)

    def test_report_json_friendly(self, tmp_path):
        import json

        set_path = _write_set(tmp_path, [_task("t1", "s_params")])
        rep = evaluate_agentbench_consistency(
            [_trial("t1", ok=True, cost=1.0)], k=1, public_path=set_path)
        json.dumps(rep, ensure_ascii=False)  # 不抛即过

    def test_two_task_macro_is_mean(self, tmp_path):
        set_path = _write_set(tmp_path, [_task("a", "s_params"),
                                         _task("b", "board")])
        trials = ([_trial("a", ok=True)] * 4 + [_trial("a", ok=False)]
                  + [_trial("b", ok=True)] + [_trial("b", ok=False)] * 3)
        rep = evaluate_agentbench_consistency(trials, k=2, public_path=set_path)
        rows = {r["id"]: r for r in rep["results"]}
        # a: C(4,2)/C(5,2)=6/10；b: C(1,2)=0
        assert rows["a"]["pass_hat_k"] == pytest.approx(0.6)
        assert rows["b"]["pass_hat_k"] == 0.0
        assert rep["pass_hat_k_macro"] == pytest.approx(0.3)
