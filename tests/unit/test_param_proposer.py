"""E12 参数域提议器单测：注册表契约/确定性/trace 结构/σ 日程/收敛烟测。

覆盖面（B4 交付门）：
- 注册表：两档注册、未知名/重名/空名显式报错（不静默覆盖）、同类幂等；
- 确定性：同 seed 同评判器逐位一致（random.Random 注入 + sorted 枚举序）；
- trace：字段结构、步数/步号、评估计数（起点 1 次 + 每候选 1 次）；
- σ_t 日程：线性单调不增、端点值；
- 诚实边界：score_fn=None 纯噪声游走、恒分数不接受（起点保持）；
- 收敛烟测：合成球面函数秒级收敛（确定性种子）。
"""

from __future__ import annotations

import random
import sys
from itertools import pairwise
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rfauto.core.errors import ConfigError
from rfauto.optimization.param_proposer import (
    PROPOSER_PARAM_REGISTRY,
    ParamAnnealedProposer,
    ParamProposer,
    create_param_proposer,
    list_param_proposers,
    register_proposer_param,
)


def _sphere_w(pt: dict[str, float]) -> float:
    return (pt["w"] - 1.1) ** 2


class TestRegistry:
    def test_param_annealed_registered(self):
        assert "param_annealed" in PROPOSER_PARAM_REGISTRY
        assert "param_annealed" in list_param_proposers()
        assert PROPOSER_PARAM_REGISTRY["param_annealed"] is \
            ParamAnnealedProposer

    def test_duplicate_name_rejected(self):
        class Dup(ParamProposer):
            name = "param_annealed"

        with pytest.raises(ConfigError, match="重复"):
            register_proposer_param(Dup)

    def test_empty_name_rejected(self):
        class NoName(ParamProposer):
            name = ""

        with pytest.raises(ConfigError, match="未声明非空 name"):
            register_proposer_param(NoName)

    def test_same_class_reregister_idempotent(self):
        register_proposer_param(ParamAnnealedProposer)
        assert PROPOSER_PARAM_REGISTRY["param_annealed"] is \
            ParamAnnealedProposer

    def test_probe_class_cleanup(self):
        class Probe(ParamProposer):
            name = "_probe_param_proposer"

        register_proposer_param(Probe)
        try:
            assert create_param_proposer("_probe_param_proposer") is not None
            assert "_probe_param_proposer" in list_param_proposers()
        finally:
            PROPOSER_PARAM_REGISTRY.pop("_probe_param_proposer", None)

    def test_unknown_name_lists_available(self):
        with pytest.raises(ConfigError, match="未知参数域提议器"):
            create_param_proposer("does_not_exist")


class TestValidation:
    def test_invalid_constructor_params(self):
        with pytest.raises(ConfigError, match="n_steps"):
            ParamAnnealedProposer(n_steps=0)
        with pytest.raises(ConfigError, match="sigma"):
            ParamAnnealedProposer(sigma_min=0.5, sigma_max=0.2)
        with pytest.raises(ConfigError, match="sigma"):
            ParamAnnealedProposer(sigma_max=0.0)

    def test_empty_bounds_rejected(self):
        p = ParamAnnealedProposer()
        with pytest.raises(ConfigError, match="bounds 为空"):
            p.propose({}, random.Random(0), score_fn=_sphere_w)

    def test_bad_bounds_rejected(self):
        p = ParamAnnealedProposer()
        with pytest.raises(ConfigError, match="非法"):
            p.propose({"w": (1.0, 1.0)}, random.Random(0), score_fn=_sphere_w)

    def test_x_start_key_mismatch_rejected(self):
        p = ParamAnnealedProposer()
        with pytest.raises(ConfigError, match="x_start"):
            p.propose({"w": (0.0, 1.0)}, random.Random(0),
                      x_start={"u": 0.5}, score_fn=_sphere_w)

    def test_describe(self):
        d = ParamAnnealedProposer(n_steps=5).describe()
        assert d["name"] == "param_annealed"
        assert d["n_steps"] == 5
        assert "非扩散模型" in d["kind"]


class TestSigmaSchedule:
    def test_linear_monotone_non_increasing(self):
        p = ParamAnnealedProposer(n_steps=10, sigma_max=0.4, sigma_min=0.05)
        s = p.sigma_schedule()
        assert len(s) == 10
        assert s[0] == pytest.approx(0.4)
        assert s[-1] == pytest.approx(0.05)
        assert all(a >= b for a, b in pairwise(s))

    def test_single_step_takes_sigma_max(self):
        p = ParamAnnealedProposer(n_steps=1, sigma_max=0.3, sigma_min=0.02)
        assert p.sigma_schedule() == [0.3]


class TestDeterminism:
    def test_same_seed_bitwise_identical(self):
        bounds = {"w": (0.5, 2.0)}
        p = ParamAnnealedProposer(n_steps=25)
        b1, t1 = p.propose_with_trace(bounds, random.Random(123),
                                      score_fn=_sphere_w)
        b2, t2 = p.propose_with_trace(bounds, random.Random(123),
                                      score_fn=_sphere_w)
        assert repr((b1, t1)) == repr((b2, t2))

    def test_different_seed_differs(self):
        bounds = {"w": (0.5, 2.0)}
        p = ParamAnnealedProposer(n_steps=25)
        _b1, t1 = p.propose_with_trace(bounds, random.Random(1),
                                       score_fn=_sphere_w)
        _b2, t2 = p.propose_with_trace(bounds, random.Random(2),
                                       score_fn=_sphere_w)
        assert [r["score_cand"] for r in t1] != \
            [r["score_cand"] for r in t2]

    def test_scoreless_walk_still_deterministic(self):
        p = ParamAnnealedProposer(n_steps=10)
        b1, t1 = p.propose_with_trace({"w": (0.0, 1.0)}, random.Random(9))
        b2, t2 = p.propose_with_trace({"w": (0.0, 1.0)}, random.Random(9))
        assert b1 == b2 and t1 == t2


class TestTraceAndSemantics:
    def test_trace_structure_and_eval_count(self):
        p = ParamAnnealedProposer(n_steps=7)
        calls: list[int] = []

        def score(pt: dict[str, float]) -> float:
            calls.append(1)
            return (pt["w"] - 0.8) ** 2

        best, trace = p.propose_with_trace(
            {"w": (0.0, 1.0)}, random.Random(7), x_start={"w": 0.5},
            score_fn=score)
        assert len(trace) == 7
        assert [r["step"] for r in trace] == list(range(1, 8))
        for rec in trace:
            assert set(rec) == {"step", "sigma", "score_cand", "score_best",
                                "accepted"}
            assert rec["score_cand"] is not None
            assert rec["sigma"] == pytest.approx(
                p.sigma_schedule()[rec["step"] - 1])
        # 评估预算 = 起点 1 次 + 每候选 1 次（贪心不接受也花预算）
        assert len(calls) == 8
        assert trace[0]["score_best"] == pytest.approx((0.5 - 0.8) ** 2)
        assert 0.0 <= best["w"] <= 1.0

    def test_constant_score_never_accepts_keeps_start(self):
        p = ParamAnnealedProposer(n_steps=12)
        best, trace = p.propose_with_trace(
            {"w": (0.0, 1.0)}, random.Random(11), x_start={"w": 0.3},
            score_fn=lambda _pt: 1.0)
        assert best == {"w": 0.3}
        assert all(not r["accepted"] for r in trace)
        assert all(r["score_best"] == 1.0 for r in trace)

    def test_scoreless_pure_walk(self):
        p = ParamAnnealedProposer(n_steps=10)
        best, trace = p.propose_with_trace({"w": (0.0, 1.0)},
                                           random.Random(5))
        assert all(r["score_cand"] is None for r in trace)
        assert all(r["accepted"] is False for r in trace)
        assert 0.0 <= best["w"] <= 1.0

    def test_candidates_clipped_to_bounds(self):
        p = ParamAnnealedProposer(n_steps=40, sigma_max=5.0, sigma_min=5.0)
        best, _trace = p.propose_with_trace(
            {"w": (0.4, 0.6)}, random.Random(3), score_fn=_sphere_w)
        assert 0.4 <= best["w"] <= 0.6


class TestConvergenceSmoke:
    def test_sphere_converges_deterministically(self):
        p = ParamAnnealedProposer(n_steps=200, sigma_max=0.4, sigma_min=0.005)
        best, trace = p.propose_with_trace(
            {"w": (0.0, 3.0)}, random.Random(42),
            score_fn=lambda pt: (pt["w"] - 1.234) ** 2)
        finals = [r["score_best"] for r in trace]
        # 最优分数轨迹单调不增（贪心语义）
        assert all(a >= b for a, b in pairwise(finals))
        assert finals[-1] < 1e-4
        assert abs(best["w"] - 1.234) < 1e-2
