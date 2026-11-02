"""阶段 6.5：主动学习采样提议测试。"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """隔离体收编 tests/conftest.py::isolated（T5 首批单源化）。"""
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


# ─── T-N9（aurora_n W2）：EI/UCB/σ 采集族 + 注册代理消费面 ────────────────────
#
# 门预声明（探针校准记录 runs/aurora_n/w2_tn9/，budget=30/n_init=5/n_pool=128/
# seeds 0..6 配对比较，全部确定性 7/7 成立后才写入门值——#122 门不事后改）：
#   定量门（EI 收敛快）  ：EI 臂 speedup_median ≥ 1.30（探针实测 2.625）；
#   定性门（UCB 探索强） ：逐种子 max_pair(UCB) ≥ max_pair(EI)（探针 7/7），
#                          且逐种子 best_cost(UCB) > best_cost(EI)（探索换收敛）；
#   定性门（σ 填空间）   ：逐种子 nn_mean(σ) ≥ nn_mean(EI) 且 ≥ nn_mean(LCB)
#                          （探针 7/7）。

_GATES_KW = {"budget": 30, "n_init": 5, "n_pool": 128}


def _pick_dispersion(samples: list[dict]) -> tuple[float, float]:
    """选点离散度（跳过 LHS 初期 5 点）：(两两最大距离, 最近邻间距均值)，
    归一化 [0,1]² 坐标——与探针 runs/aurora_n/w2_tn9/probe_gates_paired.py 同式。"""
    pts = np.array([[(s["params"]["x"] + 2.0) / 4.0,
                     (s["params"]["y"] + 2.0) / 4.0] for s in samples[5:]])
    d = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1))
    iu = np.triu_indices(len(pts), 1)
    nn = [min(np.delete(d[i], i)) for i in range(len(pts))]
    return float(d[iu].max()), float(np.mean(nn))


class TestAcquisitionFamilies:
    def test_kind_tuple_pin(self):
        from rfauto.service.active_learning import ACQUISITION_KINDS

        assert ACQUISITION_KINDS == ("lcb", "ucb", "ei", "sigma")

    def test_unknown_acquisition_raises(self):
        from rfauto.service.active_learning import (
            ACQUISITION_KINDS,
            acquisition_scores,
            active_learning_search,
            convergence_speedup_benchmark,
            synthetic_noisy_bowl,
        )

        with pytest.raises(ValueError, match="未知采集函数"):
            acquisition_scores(np.array([0.0]), np.array([1.0]),
                               acquisition="nope")
        with pytest.raises(ValueError, match=f"{list(ACQUISITION_KINDS)}"):
            active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS,
                                   budget=6, acquisition="nope")
        with pytest.raises(ValueError, match="未知采集函数"):
            convergence_speedup_benchmark(n_seeds=1, budget=6,
                                          acquisition="nope")

    def test_default_path_equals_explicit_lcb(self):
        """缺省（不传 acquisition）与显式 "lcb" 全信封逐键相等。"""
        from rfauto.service.active_learning import (
            active_learning_search,
            synthetic_noisy_bowl,
        )

        kw = {"budget": 14, "n_init": 4, "seed": 7, "n_pool": 64}
        assert (active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS, **kw)
                == active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS,
                                          acquisition="lcb", **kw))

    def test_default_lcb_matches_legacy_algorithm(self):
        """缺省等价钉：新缺省路径 == 旧算法逐步复刻（独立于新分派器）。

        旧算法（T-N9 前）：LCB=μ−βσ 逐轮 argmin；预测直接调未改动的
        _gp_posterior_predictions（gp 来源内核），不经新 acquisition 面。
        """
        from rfauto.optimization.sample_design import lhs_points
        from rfauto.service.active_learning import (
            COST_KEY,
            _gp_posterior_predictions,
            active_learning_search,
            synthetic_noisy_bowl,
        )

        def legacy_lcb_samples(budget: int, n_init: int, seed: int,
                               n_pool: int) -> list[dict]:
            samples: list[dict] = []

            def ev(pt: dict) -> None:
                samples.append({"params": dict(pt),
                                "metrics": {COST_KEY:
                                            float(synthetic_noisy_bowl(pt))}})

            for pt in lhs_points(BOWL_BOUNDS, n_init, seed=seed)["points"]:
                ev(pt)
            rnd = 0
            while len(samples) < budget:
                rnd += 1
                pool = lhs_points(BOWL_BOUNDS, max(int(n_pool), 1),
                                  seed=seed * 1000 + rnd)["points"]
                means, sigmas = _gp_posterior_predictions(
                    samples, BOWL_BOUNDS, pool, length_scale=0.3,
                    noise=1e-6, metric_keys=[COST_KEY])
                lcb = means[:, 0] - 2.0 * sigmas[:, 0]
                ev(pool[int(np.argmin(lcb))])
            return samples

        for kw in ({"budget": 14, "n_init": 4, "seed": 7, "n_pool": 64},
                   {"budget": 20, "n_init": 5, "seed": 12, "n_pool": 96}):
            legacy = legacy_lcb_samples(**kw)
            fresh = active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS,
                                           **kw)["samples"]
            assert fresh == legacy

    def test_lcb_scores_negation_identity(self):
        """lcb 档 βσ−μ 与旧 argmin(μ−βσ) 同序（IEEE 取负恒等，含并列首下标）。"""
        from rfauto.service.active_learning import acquisition_scores

        rng = np.random.default_rng(9)
        mu = np.round(rng.uniform(-2, 2, 200), 1)      # 取整制造并列
        sigma = np.round(rng.uniform(0, 1, 200), 1)
        scores = acquisition_scores(mu, sigma, acquisition="lcb", beta=2.0)
        assert np.array_equal(scores, 2.0 * sigma - mu)
        assert int(np.argmax(scores)) == int(np.argmin(mu - 2.0 * sigma))

    def test_ei_scores_route_single_source_and_analytic_anchor(self):
        """EI 档=gp_det.expected_improvement 原样路由（单源），附解析锚点。"""
        from rfauto.optimization.surrogate.gp_det import expected_improvement
        from rfauto.service.active_learning import acquisition_scores

        rng = np.random.default_rng(4)
        mu = rng.uniform(-2, 2, 64)
        sigma = rng.uniform(0, 1, 64)
        y_best, xi = -0.5, 0.1
        scores = acquisition_scores(mu, sigma, acquisition="ei",
                                    y_best=y_best, xi=xi)
        assert np.array_equal(
            scores, expected_improvement(mu, sigma, y_best, xi=xi))
        # 解析锚（#118 独立构造）：μ=y_best → EI=σ·φ(0)=σ/√(2π)
        flat = acquisition_scores(np.array([y_best, y_best]),
                                  np.array([0.7, 1.3]), acquisition="ei",
                                  y_best=y_best)
        assert flat[1] == pytest.approx(1.3 / math.sqrt(2.0 * math.pi),
                                        rel=1e-12)
        # σ=0 且 μ<y_best → EI=y_best−μ（gp_det 确定性边界契约；
        # np.errstate 钉测试侧——σ→safe=1e-300 的中间量溢出告警非数值错误）
        with np.errstate(over="ignore"):
            edge = acquisition_scores(np.array([-1.0]), np.array([0.0]),
                                      acquisition="ei", y_best=-0.5)
        assert edge[0] == pytest.approx(0.5)

    @pytest.mark.parametrize("acq", ["ucb", "ei", "sigma"])
    def test_search_non_default_families_deterministic(self, acq):
        """确定性钉：同 seed 同配置采集序列逐位一致（新三族各档）。"""
        from rfauto.service.active_learning import (
            active_learning_search,
            synthetic_noisy_bowl,
        )

        kw = {"budget": 12, "n_init": 4, "seed": 5, "n_pool": 48,
              "acquisition": acq}
        a = active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS, **kw)
        b = active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS, **kw)
        assert a["ok"] and a["acquisition"] == acq
        assert a["samples"] == b["samples"]
        assert a["best_cost"] == b["best_cost"]

    def test_ei_benchmark_quantitative_gate(self):
        """定量门（预声明）：EI 臂 bowl 裁判 speedup_median ≥ 1.30。"""
        from rfauto.service.active_learning import convergence_speedup_benchmark

        r = convergence_speedup_benchmark(acquisition="ei", n_seeds=7,
                                          **_GATES_KW)
        assert r["ok"] and r["acquisition"] == "ei"
        assert r["speedup_median"] >= 1.30, (
            f"median={r['speedup_median']}, values={r['speedup_values']}")

    def test_ucb_explores_stronger_than_ei(self):
        """定性门（预声明，7 seed 配对）：UCB 选点离散度 ≥ EI 且收敛换探索。"""
        from rfauto.service.active_learning import (
            active_learning_search,
            synthetic_noisy_bowl,
        )

        picks = {}
        for acq in ("ucb", "ei"):
            rows = []
            for s in range(7):
                r = active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS,
                                           seed=s, **_GATES_KW,
                                           acquisition=acq)
                mp, _ = _pick_dispersion(r["samples"])
                rows.append((r["best_cost"], mp))
            picks[acq] = rows
        for (b_u, mp_u), (b_e, mp_e) in zip(picks["ucb"], picks["ei"],
                                            strict=True):
            assert mp_u >= mp_e          # UCB 探索强：空间跨度不小于 EI
            assert b_u > b_e             # 探索换收敛：同预算未及 EI 最优

    def test_sigma_fills_space(self):
        """定性门（预声明，7 seed 配对）：σ 臂选点间距 ≥ EI 与 LCB 臂。"""
        from rfauto.service.active_learning import (
            active_learning_search,
            synthetic_noisy_bowl,
        )

        nn = {}
        for acq in ("sigma", "ei", "lcb"):
            rows = []
            for s in range(7):
                r = active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS,
                                           seed=s, **_GATES_KW,
                                           acquisition=acq)
                _, nnm = _pick_dispersion(r["samples"])
                rows.append(nnm)
            nn[acq] = rows
        for sg, ei, lcb in zip(nn["sigma"], nn["ei"], nn["lcb"],
                               strict=True):
            assert sg >= ei and sg >= lcb  # 填空间：不扎堆于极小值邻域

    def test_benchmark_passthrough_and_deterministic(self):
        from rfauto.service.active_learning import convergence_speedup_benchmark

        kw = {"acquisition": "ei", "n_seeds": 2, "budget": 12, "n_pool": 64,
              "n_init": 3}
        a = convergence_speedup_benchmark(**kw)
        b = convergence_speedup_benchmark(**kw)
        assert a["ok"] and a["acquisition"] == "ei"
        assert a["speedup_values"] == b["speedup_values"]


class TestRegistrySource:
    """T-N9 AL-2：surrogate_registry 任意注册代理消费面。"""

    @staticmethod
    def _samples(n: int = 20, seed: int = 7) -> list[dict]:
        return _bowl_samples(n=n, seed=seed)

    def test_native_sigma_nn(self):
        from rfauto.service.active_learning import estimate_uncertainty

        pts = [{"x": 0.0, "y": 0.0}, {"x": -1.5, "y": 1.2}]
        r = estimate_uncertainty(self._samples(6, 5), BOWL_BOUNDS, pts,
                                 source="registry", kind="nn")
        assert r["ok"] and r["source"] == "registry" and r["kind"] == "nn"
        assert r["sigma_source"] == "native"
        assert r["metric_keys"] == ["cost"]
        for item in r["points"]:
            assert item["sigma"]["cost"] >= 0.0
            assert item["score"] == pytest.approx(item["sigma"]["cost"])

    def test_poly_ridge_conformal_fallback(self):
        """None-σ 代理（poly_ridge）经 T-N1 共形包装入环，如实标注。"""
        from rfauto.service.active_learning import estimate_uncertainty

        pts = [{"x": 0.0, "y": 0.0}, {"x": -1.5, "y": 1.2}]
        kw = {"source": "registry", "kind": "poly_ridge",
              "conformal_fallback": True}
        a = estimate_uncertainty(self._samples(), BOWL_BOUNDS, pts, **kw)
        b = estimate_uncertainty(self._samples(), BOWL_BOUNDS, pts, **kw)
        assert a["ok"] and a["sigma_source"] == "conformal_interval"
        assert a["points"] == b["points"]          # 同 seed 确定性逐位
        for item in a["points"]:
            q = item["sigma"]["cost"]
            assert q >= 0.0 and math.isfinite(q)   # n=20 撑得起 alpha=0.1

    def test_legacy_sources_envelope_unchanged(self):
        """旧来源信封无 sigma_source 键（信封零改动的钉）。"""
        from rfauto.service.active_learning import estimate_uncertainty

        r = estimate_uncertainty(self._samples(8, 5), BOWL_BOUNDS,
                                 [{"x": 0.0, "y": 0.0}], source="gp")
        assert r["ok"] and "sigma_source" not in r

    def test_unknown_kind_raises(self):
        from rfauto.service.active_learning import estimate_uncertainty

        with pytest.raises(ValueError, match="未注册的代理类型"):
            estimate_uncertainty(self._samples(6, 5), BOWL_BOUNDS,
                                 [{"x": 0.0, "y": 0.0}],
                                 source="registry", kind="nope")

    def test_missing_kind_raises(self):
        from rfauto.service.active_learning import (
            active_learning_search,
            estimate_uncertainty,
            synthetic_noisy_bowl,
        )

        with pytest.raises(ValueError, match="需要显式 kind="):
            estimate_uncertainty(self._samples(6, 5), BOWL_BOUNDS,
                                 [{"x": 0.0, "y": 0.0}], source="registry")
        with pytest.raises(ValueError, match="需要显式 kind="):
            active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS,
                                   budget=6, source="registry")

    def test_no_native_sigma_strict_mode_raises(self):
        from rfauto.service.active_learning import estimate_uncertainty

        with pytest.raises(ValueError, match="无原生不确定度"):
            estimate_uncertainty(self._samples(), BOWL_BOUNDS,
                                 [{"x": 0.0, "y": 0.0}],
                                 source="registry", kind="poly_ridge",
                                 conformal_fallback=False)

    def test_search_loop_registry_poly_ridge_ei(self):
        """registry 来源进搜索环（poly_ridge+共形回退，EI 采集）：确定性。"""
        from rfauto.service.active_learning import (
            active_learning_search,
            synthetic_noisy_bowl,
        )

        kw = {"budget": 12, "n_init": 5, "seed": 3, "n_pool": 48,
              "source": "registry", "kind": "poly_ridge",
              "conformal_fallback": True, "acquisition": "ei"}
        a = active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS, **kw)
        b = active_learning_search(synthetic_noisy_bowl, BOWL_BOUNDS, **kw)
        assert a["ok"] and a["n_evals"] == 12 and a["source"] == "registry"
        assert a["samples"] == b["samples"]

    def test_benchmark_registry_arm_runs(self):
        from rfauto.service.active_learning import convergence_speedup_benchmark

        r = convergence_speedup_benchmark(
            source="registry", kind="poly_ridge", conformal_fallback=True,
            n_seeds=2, budget=12, n_pool=64, n_init=5)
        assert r["ok"] and r["source"] == "registry"

    def test_propose_next_points_conformal_fallback(self, samples_path):
        """propose_next_points：缺省旧路径不变（None-σ → 空提议），
        conformal_fallback=True 时任意注册键可出提议。"""
        from rfauto.service.active_learning import propose_next_points

        legacy = propose_next_points(samples_path, k=3, n_candidates=200,
                                     kind="poly_ridge")
        assert legacy["ok"] and legacy["proposed"] == []   # 旧路径行为钉

        kw = {"kind": "poly_ridge", "conformal_fallback": True,
              "n_candidates": 200}
        a = propose_next_points(samples_path, k=3, **kw)
        b = propose_next_points(samples_path, k=3, **kw)
        assert a["ok"] and len(a["proposed"]) == 3
        assert a["proposed"] == b["proposed"]              # 确定性逐位
        scores = [i["uncertainty_score"] for i in a["proposed"]]
        assert scores == sorted(scores, reverse=True)
        assert all(s >= 0.0 for s in scores)

