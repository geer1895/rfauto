"""阶段 6.5：主动学习采样提议测试。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def samples_path(tmp_path):
    """25 点样本集：metrics 带真实结构，nn bagging 才有非零不确定度。"""
    rng = np.random.default_rng(3)
    bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
    samples = []
    for _ in range(25):
        p = {"arm_len_mm": float(rng.uniform(*bounds["arm_len_mm"])),
             "series_w_mm": float(rng.uniform(*bounds["series_w_mm"]))}
        s11 = -20.0 + 5.0 * (p["arm_len_mm"] - 20.0) ** 2 + 10.0 * (
            p["series_w_mm"] - 0.35) ** 2
        samples.append({"params": p,
                        "metrics": {"s11_db_max_in_band": float(s11)}})
    data = {"bounds": bounds, "objectives": [], "samples": samples}
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestProposeNextPoints:
    def test_proposes_k_points_in_bounds(self, samples_path):
        from rfauto.service.active_learning import propose_next_points

        r = propose_next_points(samples_path, k=4, n_candidates=300)
        assert r["ok"], r.get("errors")
        assert len(r["proposed"]) == 4
        for item in r["proposed"]:
            p = item["params"]
            assert 18.0 <= p["arm_len_mm"] <= 23.0
            assert 0.25 <= p["series_w_mm"] <= 0.45
            assert item["uncertainty_score"] >= 0.0
        # 不确定度降序
        scores = [i["uncertainty_score"] for i in r["proposed"]]
        assert scores == sorted(scores, reverse=True)

    def test_respects_min_dist(self, samples_path):
        from rfauto.optimization.sample_design import np_rel
        from rfauto.service.active_learning import propose_next_points

        r = propose_next_points(samples_path, k=3, n_candidates=200,
                                min_dist=0.3)
        names = ["arm_len_mm", "series_w_mm"]
        lo = [18.0, 0.25]
        span = [5.0, 0.2]
        for item in r["proposed"]:
            pn = np_rel(item["params"], names, lo, span)
            for s in json.loads(Path(samples_path).read_text(
                    encoding="utf-8"))["samples"]:
                q = np_rel(s["params"], names, lo, span)
                d = sum((pn[n] - q[n]) ** 2 for n in names) ** 0.5
                assert d >= 0.3

    def test_insufficient_samples_rejected(self, tmp_path):
        from rfauto.service.active_learning import propose_next_points

        data = {"bounds": {"a": [0, 1]}, "samples": [
            {"params": {"a": 0.5}, "metrics": {"f": 1.0}}]}
        path = tmp_path / "small.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert not propose_next_points(path)["ok"]

# ─── §10.20 ⑦ active_learning 增肉：不确定性来源 / 探索槽 / 加速裁判 ──────────

BOWL_BOUNDS = {"x": (-2.0, 2.0), "y": (-2.0, 2.0)}


def _bowl_samples(n: int = 8, seed: int = 5) -> list[dict]:
    """合成带噪耦合碗上的小样本集（metrics 键固定为 cost）。"""
    from rfauto.optimization.sample_design import lhs_points
    from rfauto.service.active_learning import synthetic_noisy_bowl

    pts = lhs_points(BOWL_BOUNDS, n, seed=seed)["points"]
    return [{"params": p, "metrics": {"cost": synthetic_noisy_bowl(p)}}
            for p in pts]


class TestUncertaintySources:
    def test_gp_posterior_deterministic(self):
        from rfauto.service.active_learning import gp_posterior_uncertainty

        samples = _bowl_samples()
        pts = [{"x": 0.0, "y": 0.0}, {"x": -1.5, "y": 1.2}]
        a = gp_posterior_uncertainty(samples, BOWL_BOUNDS, pts)
        b = gp_posterior_uncertainty(samples, BOWL_BOUNDS, pts)
        assert a["ok"] and b["ok"]
        assert a["source"] == "gp"
        assert a["points"] == b["points"]          # 两次调用逐位一致
        assert len(a["points"]) == 2

    def test_bootstrap_ensemble_deterministic(self):
        from rfauto.service.active_learning import bootstrap_uncertainty

        samples = _bowl_samples()
        pts = [{"x": 0.3, "y": -0.4}, {"x": 1.0, "y": 1.0}]
        a = bootstrap_uncertainty(samples, BOWL_BOUNDS, pts, n_ensemble=6)
        b = bootstrap_uncertainty(samples, BOWL_BOUNDS, pts, n_ensemble=6)
        assert a["ok"] and a["source"] == "bootstrap"
        assert a["points"] == b["points"]          # bootstrap 重采样固定种子
        assert len(a["points"]) == 2

    def test_gp_sigma_shrinks_at_training_point(self):
        from rfauto.service.active_learning import gp_posterior_uncertainty

        samples = _bowl_samples()
        known = samples[0]["params"]
        far = {"x": -2.0, "y": 2.0}
        r = gp_posterior_uncertainty(samples, BOWL_BOUNDS, [known, far])
        sigma_known = r["points"][0]["sigma"]["cost"]
        sigma_far = r["points"][1]["sigma"]["cost"]
        assert sigma_far > 0.0
        assert sigma_known < sigma_far             # 后验方差在观测点收缩

    def test_uncertainty_contract_fields(self):
        from rfauto.service.active_learning import estimate_uncertainty

        samples = _bowl_samples()
        pts = [{"x": 0.1, "y": 0.2}, {"x": -0.7, "y": 1.1}]
        for source in ("gp", "bootstrap"):
            r = estimate_uncertainty(samples, BOWL_BOUNDS, pts, source=source)
            assert r["ok"] and r["source"] == source
            assert r["metric_keys"] == ["cost"]
            assert r["n_samples"] == len(samples)
            for item in r["points"]:
                assert set(item["sigma"]) == {"cost"}
                assert set(item["mean"]) == {"cost"}
                assert item["sigma"]["cost"] >= 0.0
                assert item["score"] == pytest.approx(sum(item["sigma"].values()))

    def test_nn_source_contract(self):
        """第三种来源（既有注册代理 uncertainty 通道）也走同一契约。"""
        from rfauto.service.active_learning import estimate_uncertainty

        samples = _bowl_samples(n=6)
        r = estimate_uncertainty(samples, BOWL_BOUNDS, [{"x": 0.0, "y": 0.0}],
                                 source="nn", kind="nn")
        assert r["ok"] and r["source"] == "nn"
        assert r["metric_keys"] == ["cost"]
        assert r["points"][0]["sigma"]["cost"] >= 0.0

    def test_unknown_source_raises(self):
        from rfauto.service.active_learning import estimate_uncertainty

        with pytest.raises(ValueError):
            estimate_uncertainty(_bowl_samples(), BOWL_BOUNDS,
                                 [{"x": 0.0, "y": 0.0}], source="nope")

    def test_illegal_point_raises(self):
        from rfauto.service.active_learning import gp_posterior_uncertainty

        with pytest.raises(ValueError):
            gp_posterior_uncertainty(_bowl_samples(), BOWL_BOUNDS,
                                     [{"x": "bad", "y": 0.0}])

    def test_degenerate_inputs_do_not_crash(self):
        from rfauto.service.active_learning import estimate_uncertainty

        samples = _bowl_samples()
        # 空搜索空间 → 显式失败（不崩）
        assert not estimate_uncertainty(samples, {}, [{"x": 0.0, "y": 0.0}])["ok"]
        # 空样本 → 显式失败
        assert not estimate_uncertainty([], BOWL_BOUNDS,
                                        [{"x": 0.0, "y": 0.0}])["ok"]
        # 空候选点 → ok 且空列表
        empty = estimate_uncertainty(samples, BOWL_BOUNDS, [])
        assert empty["ok"] and empty["points"] == []
        # 零宽域（span 保底）→ 不除零、不崩
        deg = estimate_uncertainty(samples, {"x": (1.0, 1.0), "y": (0.0, 1.0)},
                                   [{"x": 1.0, "y": 0.5}], source="gp")
        assert deg["ok"]


class TestExplorationSlot:
    def test_scores_match_manual_min_distance(self):
        from rfauto.service.active_learning import score_exploration_candidates

        exclude = [{"x": 0.0, "y": 0.0}]
        cand = [{"x": 2.0, "y": 0.0}, {"x": 0.0, "y": 0.0}]
        r = score_exploration_candidates(BOWL_BOUNDS, cand, exclude)
        assert r["ok"] and r["names"] == ["x", "y"]
        # 归一化空间 span=4：x=2→1.0，x=0→0.5，距离 = 0.5
        assert r["scored"][0]["exploration_score"] == pytest.approx(0.5)
        assert r["scored"][1]["exploration_score"] == pytest.approx(0.0)

    def test_sorted_desc_and_eligible_flag(self):
        from rfauto.service.active_learning import score_exploration_candidates

        cand = [{"x": 0.0, "y": 0.0}, {"x": 2.0, "y": 2.0},
                {"x": 1.0, "y": 0.5}]
        r = score_exploration_candidates(BOWL_BOUNDS, cand,
                                         [{"x": 0.0, "y": 0.0}],
                                         min_dist=0.5)
        scores = [c["exploration_score"] for c in r["scored"]]
        assert scores == sorted(scores, reverse=True)
        assert r["scored"][0]["eligible"] is True
        assert r["scored"][-1]["eligible"] is False
        assert r["n_candidates"] == 3

    def test_empty_exclude_gives_unit_score(self):
        from rfauto.service.active_learning import score_exploration_candidates

        r = score_exploration_candidates(BOWL_BOUNDS, [{"x": 0.4, "y": -0.4}], [])
        assert r["scored"][0]["exploration_score"] == pytest.approx(1.0)

    def test_illegal_candidate_raises(self):
        from rfauto.service.active_learning import score_exploration_candidates

        with pytest.raises(ValueError):
            score_exploration_candidates(BOWL_BOUNDS, [{"x": "bad", "y": 0.0}])
        with pytest.raises(ValueError):
            score_exploration_candidates(BOWL_BOUNDS, ["not-a-dict"])

    def test_maximin_matches_pool_argmax(self):
        from rfauto.optimization.sample_design import lhs_points
        from rfauto.service.active_learning import (
            maximin_exploration_point,
            score_exploration_candidates,
        )

        exclude = [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": -1.0}]
        pool = lhs_points(BOWL_BOUNDS, 16, seed=11)["points"]
        best = maximin_exploration_point(BOWL_BOUNDS, exclude,
                                         n_pool=16, seed=11)
        ranked = score_exploration_candidates(BOWL_BOUNDS, pool, exclude)
        assert best == ranked["scored"][0]["params"]

    def test_maximin_all_overlap_returns_none(self):
        from rfauto.optimization.sample_design import lhs_points
        from rfauto.service.active_learning import maximin_exploration_point

        pool = lhs_points(BOWL_BOUNDS, 6, seed=3)["points"]
        assert maximin_exploration_point(BOWL_BOUNDS, pool,
                                         n_pool=6, seed=3) is None


class TestActiveLearningSearch:
    def test_search_deterministic_and_budgeted(self):
        from rfauto.service.active_learning import (
            active_learning_search,
            synthetic_noisy_bowl,
        )

        kw = {"budget": 14, "n_init": 4, "seed": 7, "n_pool": 64}
        a = active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS, **kw)
        b = active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS, **kw)
        assert a["ok"] and a["n_evals"] == 14
        assert a["best_cost"] == b["best_cost"]
        assert a["samples"] == b["samples"]        # 同种子逐点一致
        assert a["best_cost"] <= a["history"][0]["best_cost"]

    def test_bootstrap_source_search_runs(self):
        from rfauto.service.active_learning import (
            active_learning_search,
            synthetic_noisy_bowl,
        )

        r = active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS,
                                   budget=8, n_init=3, seed=2,
                                   source="bootstrap", n_pool=48)
        assert r["ok"] and r["n_evals"] == 8 and r["source"] == "bootstrap"

    def test_benchmark_target_above_minimum(self):
        from rfauto.service.active_learning import (
            convergence_speedup_benchmark,
            synthetic_bowl_range,
        )

        r = convergence_speedup_benchmark(budget=20, n_init=4, n_seeds=4,
                                          n_pool=96)
        f_min, f_max = synthetic_bowl_range()
        assert r["target"] > f_min                 # #207：阈值不可低于极值
        assert r["target"] < f_max
        assert r["budget"] == 20

    def test_benchmark_deterministic(self):
        from rfauto.service.active_learning import convergence_speedup_benchmark

        a = convergence_speedup_benchmark(seed0=3)
        b = convergence_speedup_benchmark(seed0=3)
        assert a["speedup_values"] == b["speedup_values"]
        assert a["speedup_median"] == b["speedup_median"]

    def test_speedup_median_at_least_30pct(self):
        """§10.20 ⑦ 验收：同预算下 AL 引导 vs 随机搜索收敛加速 ≥30%。"""
        from rfauto.service.active_learning import convergence_speedup_benchmark

        r = convergence_speedup_benchmark()       # 15 固定种子，取中位数
        assert r["ok"]
        assert r["speedup_median"] >= 1.30, (
            f"median={r['speedup_median']}, values={r['speedup_values']}")
        # 真实达成值远高于阈值（记录在案，防"刚好过线"质疑）
        assert r["al_best_cost_median"] < r["random_best_cost_median"]

