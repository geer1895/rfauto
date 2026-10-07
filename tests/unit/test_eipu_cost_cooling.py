"""OP-3（round16 §六）：EIpu cost-cooling β 退火 单元测试。

零真机零网络；判据预声明（#207 合成裁判 + #118 独立锚）：

1. **日程数学**（解析锚，不赌 GP）：线性 β(p)=1−p、指数
   β(p)=(1−p)²（start=1,end=0）；端点 β(0)=1 / β(1)=0 逐位；越界/
   未知 mode/beta_start<beta_end 显式 ValueError；
2. **采集机制**（score_candidates 审计面，确定型）：两观测+两候选的
   机制级排序翻转——β=1（progress=0）与 strategy="eipu" 逐位一致；
   progress=1 时 score 与纯 EI 逐位一致（β=0 → 除数 1^0=1）；构造
   "略差但便宜 vs 更好但贵"双候选，cost-aware 排序与冷却后排序翻转；
3. **循环接线**：run_eipu_loop eipu_cooled 档确定性（同 seed 两次
   逐 trial 一致）；缺 cost 的 eipu/eipu_cooled 显式 ValueError；
4. **缺省路径不变**：strategy="ei"/"eipu" 不消费新 config 字段
   （progress 任意值不影响 ei/eipu 的 score——eipu β 恒 1）。

铁律 7 对照：全部数字来自解析日程与 sklearn GP 确定性拟合
（random_state 钉死），无 LLM、无随机炼丹。
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from rfauto.optimization.eipu import (
    EIPUConfig,
    cost_cooling_beta,
    run_eipu_loop,
    score_candidates,
    suggest_next_point,
)

BOUNDS = {"x": (0.0, 1.0)}


class TestCoolingSchedule:
    def test_linear_endpoints_and_monotone(self):
        assert cost_cooling_beta(0.0) == 1.0
        assert cost_cooling_beta(1.0) == 0.0
        for k in range(5):
            assert cost_cooling_beta(k / 4) == pytest.approx(1.0 - k / 4)
        vals = [cost_cooling_beta(p / 20) for p in range(21)]
        assert all(a >= b for a, b in itertools.pairwise(vals))

    def test_exponential_is_quadratic_decay(self):
        # β(p) = end + (start−end)·(1−p)² = (1−p)²
        for k in range(5):
            assert cost_cooling_beta(k / 4, mode="exponential") == \
                pytest.approx((1.0 - k / 4) ** 2)

    def test_custom_bounds(self):
        assert cost_cooling_beta(0.5, beta_start=0.8, beta_end=0.2) == \
            pytest.approx(0.5)
        assert cost_cooling_beta(0.5, beta_start=0.9, beta_end=0.9) == \
            pytest.approx(0.9)

    def test_validation_fail_closed(self):
        with pytest.raises(ValueError, match="progress"):
            cost_cooling_beta(-0.1)
        with pytest.raises(ValueError, match="progress"):
            cost_cooling_beta(1.5)
        with pytest.raises(ValueError, match="mode"):
            cost_cooling_beta(0.5, mode="cosine")
        with pytest.raises(ValueError, match="只降不升"):
            cost_cooling_beta(0.5, beta_start=0.2, beta_end=0.8)
        with pytest.raises(ValueError, match=r"\[0,1\]"):
            cost_cooling_beta(0.5, beta_start=1.5)


def _two_point_state():
    """两观测（好而贵 @0.8 / 略差而便宜 @0.2，cost 比 1000×）+ 两对称
    候选（0.6/0.4——与观测等距，EI 由 y* 侧不对称决定，ĉ 由 cost GP
    外插决定）；冻结 state（2026-10-03，本机 sklearn 实测翻转）。"""
    X = np.array([[0.8], [0.2]])
    y = np.array([-0.90, -0.70])
    cost = np.array([1000.0, 1.0])
    points = [{"x": 0.6}, {"x": 0.4}]  # A=贵侧 / B=廉侧
    return X, y, cost, points


class TestAcquisitionMechanism:
    def test_progress0_matches_pure_eipu(self):
        X, y, cost, points = _two_point_state()
        cfg = EIPUConfig(seed=17, n_candidates=64, cooling_progress=0.0)
        cooled = score_candidates(X, y, cost, points, BOUNDS,
                                  strategy="eipu_cooled", config=cfg)
        plain = score_candidates(X, y, cost, points, BOUNDS,
                                 strategy="eipu", config=cfg)
        assert cooled[0]["beta"] == 1.0
        for c, p in zip(cooled, plain, strict=True):
            assert c["score"] == pytest.approx(p["score"], rel=1e-12)

    def test_progress1_matches_pure_ei(self):
        X, y, cost, points = _two_point_state()
        cfg = EIPUConfig(seed=17, n_candidates=64, cooling_progress=1.0)
        cooled = score_candidates(X, y, cost, points, BOUNDS,
                                  strategy="eipu_cooled", config=cfg)
        ei = score_candidates(X, y, cost, points, BOUNDS,
                              strategy="ei", config=EIPUConfig(seed=17))
        assert cooled[0]["beta"] == 0.0
        for c, e in zip(cooled, ei, strict=True):
            assert c["score"] == pytest.approx(e["score"], rel=1e-12)

    def test_ranking_flips_as_cost_penalty_cools(self):
        X, y, cost, points = _two_point_state()
        cfg_hot = EIPUConfig(seed=17, cooling_progress=0.0)
        cfg_cold = EIPUConfig(seed=17, cooling_progress=1.0)
        hot = score_candidates(X, y, cost, points, BOUNDS,
                               strategy="eipu_cooled", config=cfg_hot)
        cold = score_candidates(X, y, cost, points, BOUNDS,
                                strategy="eipu_cooled", config=cfg_cold)
        best_hot = max(range(2), key=lambda i: hot[i]["score"])
        best_cold = max(range(2), key=lambda i: cold[i]["score"])
        # 机制级判据：全额 cost 惩罚时偏好廉价候选；冷却到底后排序翻转
        assert best_hot == 1
        assert best_cold == 0

    def test_ei_eipu_ignore_progress_field(self):
        X, y, cost, points = _two_point_state()
        for strategy in ("ei", "eipu"):
            base = score_candidates(
                X, y, cost, points, BOUNDS, strategy=strategy,
                config=EIPUConfig(seed=17))
            moved = score_candidates(
                X, y, cost, points, BOUNDS, strategy=strategy,
                config=EIPUConfig(seed=17, cooling_progress=0.73))
            for a, b in zip(base, moved, strict=True):
                assert a["score"] == b["score"]

    def test_unknown_strategy_rejected(self):
        X, y, cost, points = _two_point_state()
        with pytest.raises(ValueError, match="未知 strategy"):
            score_candidates(X, y, cost, points, BOUNDS, strategy="ucb")
        with pytest.raises(ValueError, match="未知 strategy"):
            suggest_next_point(X, y, None, BOUNDS, strategy="eipu_cool")


class TestLoopWiring:
    @staticmethod
    def _problem():
        def f(p):
            x = p["x"]
            return float(0.9 - np.exp(-((x - 0.90) / 0.06) ** 2)
                         - 0.72 * np.exp(-((x - 0.18) / 0.07) ** 2))

        def cost(p):
            x = p["x"]
            return float(1.0 + 400.0 * max(0.0, x - 0.5))

        return f, cost

    def test_cooled_loop_is_deterministic(self):
        f, cost = self._problem()
        runs = []
        for _ in range(2):
            out = run_eipu_loop(
                f, cost, BOUNDS, n_iters=6, strategy="eipu_cooled",
                n_init=3, config=EIPUConfig(seed=5, n_candidates=128))
            runs.append([(t["params"]["x"], t["y"], t["cost"])
                         for t in out["trials"]])
        assert runs[0] == runs[1]
        assert all(math.isfinite(t[1]) for t in runs[0])

    def test_cooled_loop_requires_cost_at_suggest_level(self):
        # 循环层 cost 由 cost_fn 恒供；缺 cost 守卫钉在 suggest 层
        with pytest.raises(ValueError, match="cost 观测"):
            suggest_next_point(
                np.array([[0.1], [0.9]]), np.array([1.0, 0.5]), None,
                BOUNDS, strategy="eipu_cooled")

    def test_eipu_path_unchanged_by_cooling_fields(self):
        f, cost = self._problem()
        a = run_eipu_loop(f, cost, BOUNDS, n_iters=4, strategy="eipu",
                          n_init=2, config=EIPUConfig(seed=9, n_candidates=128))
        b = run_eipu_loop(
            f, cost, BOUNDS, n_iters=4, strategy="eipu", n_init=2,
            config=EIPUConfig(seed=9, n_candidates=128, cooling_progress=0.9,
                              cooling_mode="exponential"))
        ta = [(t["params"]["x"], t["y"]) for t in a["trials"]]
        tb = [(t["params"]["x"], t["y"]) for t in b["trials"]]
        assert ta == tb
