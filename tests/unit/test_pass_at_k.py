"""pass_at_k 无偏估计锚树（AD-4 接线批；#118 合成裁判 + ge1⑦ 固定 rng）。

裁判预声明（core/pass_at_k.py docstring 同源）：

- 组合式恒等：pass@k = 1 − C(n−c,k)/C(n,k)——c=n 全过 →1.0；c=0 →0.0；
  手算例 pass_at_k(3,5,2)=1−C(2,2)/C(5,2)=0.9；k=1 退化为通过率 c/n；
- 独立构造交叉：逐 k 子集穷举（itertools.combinations）的"至少一过"
  频率 == 解析式（非同源推导，#118）；
- n<k ValueError（fail-closed，拒夹持）+ bool/非整数/出界负例族；
- 经验档（MC 无放回）收敛到解析：n=24,c=9,k=4 → 解析 9261/10626≈0.8715，
  40000 抽标准误 ≈0.0017，预声明容差 0.01（≥5σ）；
- 口径镜像：pass_at_k_all == agent_bench.pass_hat_k 逐位（METR pass^k，
  只读 import 对钉，不改其语义）；
- 行消费面：宏平均逐位/零覆盖/n<k/坏行如实列因（#316 多报方向）/
  输入零改写/门不空跑绿；
- CLI 端到端：``rfauto bench consistency`` 注册面可用（k 缺省 3，
  round15 AD-4「k=3 进月门」），JSON 进出门色退出码。
"""

from __future__ import annotations

import copy
import json
import math
import sys
from itertools import combinations
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.core.pass_at_k import (
    pass_at_k,
    pass_at_k_all,
    pass_at_k_empirical,
    pass_at_k_from_rows,
)

# ── 组合式无偏估计恒等 ──────────────────────────────────────────────────────


class TestPassAtKIdentity:
    def test_canonical_hand_anchor_3_of_5_k2(self):
        # 1 − C(2,2)/C(5,2) = 1 − 1/10 = 0.9（手算逐位）
        assert pass_at_k(3, 5, 2) == pytest.approx(0.9)

    def test_all_pass_is_one(self):
        for n in (1, 2, 5, 8):
            for k in range(1, n + 1):
                assert pass_at_k(n, n, k) == 1.0

    def test_zero_pass_is_zero(self):
        for n in (1, 2, 5, 8):
            for k in range(1, n + 1):
                assert pass_at_k(0, n, k) == 0.0

    def test_k1_degenerates_to_pass_rate(self):
        assert pass_at_k(3, 5, 1) == pytest.approx(3 / 5)
        assert pass_at_k(7, 10, 1) == pytest.approx(0.7)
        assert pass_at_k(0, 7, 1) == 0.0

    def test_k_equals_n(self):
        assert pass_at_k(1, 5, 5) == 1.0  # 全取必含通过
        assert pass_at_k(4, 5, 5) == 1.0
        assert pass_at_k(0, 5, 5) == 0.0

    def test_monotone_in_k(self):
        vals = [pass_at_k(4, 9, k) for k in range(1, 10)]
        assert vals == sorted(vals)
        assert all(0.0 <= v <= 1.0 for v in vals)

    def test_exact_enumeration_identity(self):
        # 独立构造：具体 0/1 语料上逐 k 子集穷举的"至少一过"频率
        # == 解析 1 − C(n−c,k)/C(n,k)（非同源推导，#118）
        mask = [1, 0, 1, 1, 0, 0, 1]  # n=7, c=4
        c, n = sum(mask), len(mask)
        for k in range(1, n + 1):
            subsets = list(combinations(range(n), k))
            any_pass = sum(1 for s in subsets if any(mask[i] for i in s))
            expected = any_pass / len(subsets)
            assert pass_at_k(c, n, k) == pytest.approx(expected)

    @pytest.mark.parametrize("args", [
        (True, 5, 2), (3.0, 5, 2), (3, 5.0, 2), (3, 5, True),
        (3, 0, 1), (3, 5, 0), (3, 5, 6), (6, 5, 2), (-1, 5, 2),
        (3, 2, 5),   # n<k → ValueError（fail-closed，规格显式要求）
    ])
    def test_invalid_inputs_raise(self, args):
        with pytest.raises(ValueError):
            pass_at_k(*args)


# ── 口径镜像：pass^k（METR）与 agent_bench.pass_hat_k 逐位同式 ─────────────


class TestAllVariantMirror:
    def test_matches_agent_bench_pass_hat_k_grid(self):
        from rfauto.service.agent_bench import pass_hat_k

        for n in (1, 3, 5, 8):
            for c in range(0, n + 1):
                for k in range(1, n + 1):
                    assert pass_at_k_all(c, n, k) == pass_hat_k(c, n, k)

    def test_all_variant_rejects_same_family(self):
        with pytest.raises(ValueError):
            pass_at_k_all(3, 2, 5)  # n<k
        with pytest.raises(ValueError):
            pass_at_k_all(True, 5, 2)


# ── 经验档（MC 无放回） vs 解析交叉 ────────────────────────────────────────


class TestEmpirical:
    def test_mc_crosses_analytic(self):
        # 解析：1 − C(15,4)/C(24,4) = 9261/10626 ≈ 0.871542；
        # σ ≈ sqrt(q(1−q)/40000) ≈ 0.0017 → 容差 0.01（≥5σ，预声明）
        n, c, k = 24, 9, 4
        analytic = 1.0 - math.comb(n - c, k) / math.comb(n, k)
        corpus = [1] * c + [0] * (n - c)
        est = pass_at_k_empirical(corpus, k, n_draws=40_000, seed=20261002)
        assert abs(est - analytic) <= 0.01

    def test_extremes_exact(self):
        assert pass_at_k_empirical([1, 1, 1, 1], 2, n_draws=500) == 1.0
        assert pass_at_k_empirical([0, 0, 0, 0], 2, n_draws=500) == 0.0
        # k=n：唯一子集=全集
        assert pass_at_k_empirical([0, 0, 1, 0], 4, n_draws=500) == 1.0

    def test_deterministic_same_seed(self):
        corpus = [1, 0, 1, 1, 0, 0, 1, 0]
        a = pass_at_k_empirical(corpus, 3, n_draws=2000, seed=7)
        b = pass_at_k_empirical(corpus, 3, n_draws=2000, seed=7)
        assert a == b

    @pytest.mark.parametrize("kw", [
        {"k": 0}, {"k": 9},          # 出界 [1, n]
        {"n_draws": 0}, {"n_draws": -1},
    ])
    def test_invalid_draw_params_raise(self, kw):
        params = {"k": 2, "n_draws": 10, **kw}
        with pytest.raises(ValueError):
            pass_at_k_empirical([1, 0, 1], seed=0, **params)

    def test_invalid_corpus_raises(self):
        with pytest.raises(ValueError):
            pass_at_k_empirical([], 1)                       # 空
        with pytest.raises(ValueError):
            pass_at_k_empirical([1, 2, 0], 1)                # 非 0/1
        with pytest.raises(ValueError):
            pass_at_k_empirical([1, 0.5, 0], 1)              # 拒 float
        with pytest.raises(ValueError):
            pass_at_k_empirical([1, "1", 0], 1)              # 拒 str


# ── 行消费面（只读，evaluate_agentbench_consistency results 形态） ─────────


class TestFromRows:
    def test_macro_and_gate_pass(self):
        rows = [{"id": "a", "n_trials": 5, "n_pass": 3},
                {"id": "b", "n_trials": 2, "n_pass": 2}]
        rep = pass_at_k_from_rows(rows, k=2)
        assert rep["gate"] == "PASS" and rep["ok"]
        ra, rb = rep["results"]
        assert ra["pass_at_k"] == pytest.approx(0.9)   # 1 − C(2,2)/C(5,2)
        assert rb["pass_at_k"] == pytest.approx(1.0)   # 1 − C(0,2)/C(2,2)
        assert rep["pass_at_k_macro"] == pytest.approx(0.95)

    def test_fail_closed_reasons(self):
        rows = [{"id": "a", "n_trials": 2, "n_pass": 2},   # n<k
                {"id": "b", "n_trials": 0, "n_pass": 0},   # 零覆盖
                {"id": "c"},                                # 缺键
                "not-a-mapping",                            # 坏行
                {"id": "d", "n_trials": 3, "n_pass": 9}]    # n_pass 出界
        rep = pass_at_k_from_rows(rows, k=3)
        assert rep["gate"] == "FAIL" and not rep["ok"]
        assert rep["pass_at_k_macro"] is None
        assert any("<k=3" in r for r in rep["reasons"])
        assert any("零 trial 覆盖" in r for r in rep["reasons"])
        assert any("c" in r for r in rep["reasons"])

    def test_row_n_ge_k_scores(self):
        rep = pass_at_k_from_rows([{"id": "a", "n_trials": 5, "n_pass": 3}],
                                  k=3)
        assert rep["gate"] == "PASS" and rep["ok"]
        assert rep["results"][0]["pass_at_k"] == pytest.approx(1.0)

    def test_min_threshold_gate(self):
        rows = [{"id": "a", "n_trials": 5, "n_pass": 3}]  # pass@2=0.9
        assert pass_at_k_from_rows(
            rows, k=2, min_pass_at_k=0.8)["gate"] == "PASS"
        below = pass_at_k_from_rows(rows, k=2, min_pass_at_k=0.95)
        assert below["gate"] == "FAIL"
        assert any("阈值" in r for r in below["reasons"])

    def test_readonly_input(self):
        rows = [{"id": "a", "n_trials": 5, "n_pass": 3, "pass_hat_k": 0.3}]
        snapshot = copy.deepcopy(rows)
        pass_at_k_from_rows(rows, k=2)
        assert rows == snapshot

    def test_invalid_params_raise(self):
        rows: list = [{"id": "a", "n_trials": 5, "n_pass": 3}]
        with pytest.raises(ValueError):
            pass_at_k_from_rows(rows, k=0)
        with pytest.raises(ValueError):
            pass_at_k_from_rows(rows, k=True)
        with pytest.raises(ValueError):
            pass_at_k_from_rows(rows, k=2, min_pass_at_k=float("nan"))


# ── CLI 端到端（bench consistency 注册面；k 缺省 3 进月门口径） ─────────────


def _task(tid: str, artifact: str) -> dict:
    return {"id": tid, "family": "template_render", "level": 1,
            "prompt": f"任务 {tid}",
            "expected": {"calls": [{"tool": "list_solvers", "args": {}}],
                         "artifacts": [artifact]}}


def _trial(tid: str, *, ok: bool, cost: float | None = None) -> dict:
    rec: dict = {"id": tid,
                 "trajectory": [{"tool": "list_solvers", "args": {}}],
                 "artifacts": ["s_params"] if ok else []}
    if cost is not None:
        rec["cost"] = cost
    return rec


class TestCliConsistency:
    def _run(self, tmp_path: Path, args: list[str]):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        set_path = tmp_path / "bench.yaml"
        set_path.write_text(
            yaml.safe_dump({"version": 1, "tasks": [_task("t1", "s_params")]},
                           allow_unicode=True), encoding="utf-8")
        trials_path = tmp_path / "trials.json"
        trials_path.write_text(json.dumps([
            _trial("t1", ok=True, cost=1.0),
            _trial("t1", ok=True, cost=2.0),
            _trial("t1", ok=False, cost=1.5),
            _trial("t1", ok=True, cost=1.0),
            _trial("t1", ok=False, cost=2.5),
        ]), encoding="utf-8")
        base = ["bench", "consistency", "--trials", str(trials_path),
                "--public-set", str(set_path)]
        result = CliRunner().invoke(app, base + args)
        return result

    def test_cli_pass_exit0_json(self, tmp_path):
        result = self._run(tmp_path, ["--k", "2"])
        assert result.exit_code == 0, result.output
        rep = json.loads(result.output)
        assert rep["ok"] and rep["gate"] == "PASS"
        assert rep["k"] == 2
        row = rep["results"][0]
        assert row["n_trials"] == 5 and row["n_pass"] == 3
        assert row["pass_hat_k"] == pytest.approx(0.3)      # C(3,2)/C(5,2)
        assert row["cost_at_k"] == pytest.approx(3.2)       # k·mean=2·1.6

    def test_cli_default_k_is_3(self, tmp_path):
        # round15 AD-4「k=3 进月门」：缺省 k=3
        result = self._run(tmp_path, [])
        assert result.exit_code == 0, result.output
        rep = json.loads(result.output)
        assert rep["k"] == 3
        assert rep["results"][0]["pass_hat_k"] == pytest.approx(
            1 / 10)  # C(3,3)/C(5,3)

    def test_cli_threshold_fail_exit1(self, tmp_path):
        result = self._run(tmp_path, ["--k", "2", "--min-pass-hat-k", "0.9"])
        assert result.exit_code == 1, result.output
        rep = json.loads(result.output)
        assert rep["gate"] == "FAIL"
        assert rep["pass_hat_k_macro"] == pytest.approx(0.3)
