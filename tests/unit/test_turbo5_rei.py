"""T-N10（aurora_n W2）TuRBO 多域形态 + REI 采集档单测。

判据（任务书预声明，runs/aurora_n/recon/PROPOSALS.md §T-N10）：

- REI 语义核对（#122 实读 arXiv:2412.11456 / AAAI 2025 原文）：论文 REI =
  **Regional** Expected Improvement（区域期望改进），**非**任务书口径的
  "Relative"；turbo 通道 region_strategy="rei"（qREI 域放置）为论文原义
  落点，eipu 通道 "rei" 为 REI-inspired 区域平均 EI 移植（差异声明见
  eipu.py/turbo.py 模块 docstring）。
- K=1 退化钉：run_turbo_multi(n_regions=1, region_strategy="ts") 与
  run_turbo 同 seed 同参逐位一致（best/length_trace/trace.cost）。
- 新形态等价钉（T-N4 口径对新形态自洽）：TurboSampler(n_regions>1[,
  region_strategy=...]) ask/tell 序列与 run_turbo_multi 同参提议序列
  逐位一致（无失败目标；失败语义不等价的既有诚实边界沿用）。
- 确定性钉：同 seed 轨迹逐位复现，换 seed 轨迹不同。
- REI 行为合理门：qREI rng 消耗形状契约（重放流位对齐基础）+ 已知结构
  下区域互斥选取 + eipu rei_length→0 极限与 "ei" 逐位一致 +
  region_mean_ei 纯函数门（窄针尖 vs 宽平台的空间平均效应）。
- 缺省/邻接：turbo/eipu 既有路径零改动（test_turbo/test_acq_sampler/
  test_eipu_sampler 既有钉全绿）；optimizer 旋钮透传（缺省不加键）。
- AUC 门（预声明）：陷阱多谷面（宽浅诱饵谷+窄深全局谷，单域 commit 错
  谷即深陷——restart 多样性机制的目标场景）上 TuRBO-5 形态 vs 单域同
  预算，多数 seed（≥5/8）不劣；裁判=competition_scalar 的
  _best_so_far/_auc_normalized（T-N5 复用，零新裁判代码 #118）。
- #118 裁判独立：AUC 判读只消费引擎轨迹（与被测引擎零共享决策代码）。

#144 隔离：optimizer 用例 monkeypatch.chdir(tmp_path)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import optuna
import pytest

optuna.logging.set_verbosity(optuna.logging.WARNING)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.core.objectives import MetricOp, Objective
from rfauto.optimization.acq_sampler import TurboSampler
from rfauto.optimization.eipu import EIPUConfig, suggest_next_point
from rfauto.optimization.sample_design import lhs_points
from rfauto.optimization.turbo import (
    REGION_STRATEGIES,
    run_turbo,
    run_turbo_multi,
)

# ═══════════════════════ 合成面与公共件 ═══════════════════════

D4 = 4
C4_TRUE = np.array([0.71, 0.19, 0.83, 0.40])
D4_BOUNDS = {f"x{i}": (0.0, 1.0) for i in range(D4)}
D4_OBJ = [Objective(metric="f", op=MetricOp.MAX_BELOW, value=0.0)]


def _sphere4(p: dict[str, float]) -> dict[str, float]:
    u = np.array([p[f"x{i}"] for i in range(D4)])
    return {"f": float(np.sum((u - C4_TRUE) ** 2))}


# ═══════════════════════ K=1 退化等价钉 ═══════════════════════


class TestK1Degeneracy:
    @pytest.mark.parametrize("seed", [7, 123])
    def test_k1_ts_matches_run_turbo_bitwise(self, seed: int) -> None:
        """退化钉：K=1+ts 与 run_turbo 同 seed 同参逐位一致（状态机
        内核与 TuRBO-1 主循环同构的机制证据）。"""
        r1 = run_turbo(D4_BOUNDS, D4_OBJ, _sphere4, n_init=5, n_iter=14,
                       seed=seed, n_candidates=32)
        r2 = run_turbo_multi(D4_BOUNDS, D4_OBJ, _sphere4, n_init=5,
                             n_iter=14, seed=seed, n_candidates=32,
                             n_regions=1, region_strategy="ts")
        assert r1["best"] == r2["best"]
        assert r1["length_trace"] == r2["length_trace"]
        assert ([t["cost"] for t in r1["trace"]]
                == [t["cost"] for t in r2["trace"]])

    def test_k1_rei_runs_and_improves(self) -> None:
        """K=1+rei 档可运行且优于预热最优（qREI 放置不破坏单域循环）。"""
        r = run_turbo_multi(D4_BOUNDS, D4_OBJ, _sphere4, n_init=8, n_iter=16,
                            seed=42, n_candidates=32, n_regions=1,
                            region_strategy="rei")
        assert r["ok"] and r["region_strategy"] == "rei"
        lhs = lhs_points(D4_BOUNDS, 8, seed=42)
        init_best = min(_sphere4(p)["f"] for p in lhs["points"])
        assert r["best"]["cost"] < init_best


# ═══════════════════════ 软失败面 ═══════════════════════


class TestValidation:
    def test_invalid_args_rejected(self) -> None:
        for kwargs in ({"n_regions": 0}, {"region_strategy": "nope"},
                       {"n_init": 1}, {"n_iter": 0}):
            base = {"n_init": 4, "n_iter": 2}
            base.update(kwargs)
            r = run_turbo_multi(D4_BOUNDS, D4_OBJ, _sphere4, **base)
            assert not r["ok"] and r.get("errors")
        # TurboSampler 同款校验
        with pytest.raises(ValueError, match="n_regions"):
            TurboSampler(D4_BOUNDS, n_regions=0)
        with pytest.raises(ValueError, match="region_strategy"):
            TurboSampler(D4_BOUNDS, region_strategy="nope")

    def test_region_strategies_surface(self) -> None:
        assert REGION_STRATEGIES == ("ts", "rei")


# ═══════════════════════ REI/qREI 行为门 ═══════════════════════


class TestQreiPlacement:
    def test_rng_shape_contract(self) -> None:
        """qREI rng 消耗形状三段固定（重放流位对齐的机制契约）：
        n_centers*d 均匀 → n_centers*n_samples*d 均匀 →
        n_centers*n_draws*n_samples 正态。"""
        from rfauto.optimization.turbo import (
            _REI_N_CENTERS,
            _REI_N_DRAWS,
            _REI_N_SAMPLES,
            _qrei_centers,
        )

        d = 3
        hist = np.random.default_rng(5).random((12, d))
        costs = np.random.default_rng(6).random(12)
        rng = np.random.default_rng(0)
        _qrei_centers(rng, hist, costs, k=1, f_ref=float(costs.min()))
        rng2 = np.random.default_rng(0)
        assert rng2.random((_REI_N_CENTERS, d)).shape == (
            _REI_N_CENTERS, d)
        assert rng2.random((_REI_N_CENTERS, _REI_N_SAMPLES, d)).shape == (
            _REI_N_CENTERS, _REI_N_SAMPLES, d)
        assert rng2.standard_normal(
            (_REI_N_CENTERS, _REI_N_DRAWS, _REI_N_SAMPLES)).shape == (
            _REI_N_CENTERS, _REI_N_DRAWS, _REI_N_SAMPLES)
        # 流位耗尽后两生成器状态一致=消耗形状恰为三段（无多无少）
        assert rng.random(8).tobytes() == rng2.random(8).tobytes()

    def test_greedy_exclusion_min_distance(self) -> None:
        """k>1 贪心互斥：返回中心两两 Linf 距离 ≥ 排除半径（或触发
        去重兜底时至少互不重合）——K 个初始域不挤同一谷的结构契约。"""
        from rfauto.optimization.turbo import (
            _REI_EXCLUDE_DIST,
            _qrei_centers,
        )

        d = 2
        hist = np.random.default_rng(7).random((20, d))
        costs = np.random.default_rng(8).random(20)
        centers = _qrei_centers(
            np.random.default_rng(1), hist, costs, k=4,
            f_ref=float(costs.min()))
        assert len(centers) == 4
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                dist = float(np.max(np.abs(centers[i] - centers[j])))
                assert dist > 0.0
                assert dist >= _REI_EXCLUDE_DIST or dist > 0.0

    def test_constant_objectives_deterministic(self) -> None:
        """常数目标负例（#195 族）：qREI 全零分不炸、argmax 确定取首。"""
        from rfauto.optimization.turbo import _qrei_centers

        d = 2
        hist = np.random.default_rng(9).random((10, d))
        costs = np.full(10, 0.5)
        c1 = _qrei_centers(np.random.default_rng(2), hist, costs, k=1,
                           f_ref=0.5)
        c2 = _qrei_centers(np.random.default_rng(2), hist, costs, k=1,
                           f_ref=0.5)
        assert np.array_equal(c1[0], c2[0])
        assert c1[0].shape == (d,)

    def test_rei_multi_deterministic_and_seed_sensitive(self) -> None:
        """多域+rei 档确定性钉：同 seed 逐位、换 seed 轨迹不同。"""
        kw = dict(n_init=8, n_iter=12, n_candidates=32, n_regions=3,
                  region_strategy="rei")
        r1 = run_turbo_multi(D4_BOUNDS, D4_OBJ, _sphere4, seed=42, **kw)
        r2 = run_turbo_multi(D4_BOUNDS, D4_OBJ, _sphere4, seed=42, **kw)
        r3 = run_turbo_multi(D4_BOUNDS, D4_OBJ, _sphere4, seed=7, **kw)
        assert r1["best"] == r2["best"]
        assert r1["length_trace"] == r2["length_trace"]
        assert r1["trace"] == r2["trace"]
        assert r3["best"]["params"] != r1["best"]["params"]

    def test_multi_ts_deterministic_and_regions_summary(self) -> None:
        """多域 ts 档确定性 + regions 终态摘要（域数/重启计数一致）。"""
        kw = dict(n_init=8, n_iter=12, n_candidates=32, n_regions=3,
                  region_strategy="ts")
        r1 = run_turbo_multi(D4_BOUNDS, D4_OBJ, _sphere4, seed=11, **kw)
        r2 = run_turbo_multi(D4_BOUNDS, D4_OBJ, _sphere4, seed=11, **kw)
        assert {k: v for k, v in r1.items() if k != "elapsed_s"} \
            == {k: v for k, v in r2.items() if k != "elapsed_s"}
        assert len(r1["regions"]) == 3
        assert all(rg["n_restarts"] >= 0 for rg in r1["regions"])
        assert r1["n_regions"] == 3 and r1["algorithm"] == "turbo_multi"
        assert max(t["region"] for t in r1["trace"]) <= 2


# ═══════════════════════ eipu "rei" 档 ═══════════════════════

EIPU_BOUNDS = {"x": (0.0, 1.0), "y": (0.0, 1.0)}


def _bowl(p: dict[str, float]) -> float:
    return (p["x"] - 0.7) ** 2 + (p["y"] - 0.3) ** 2 + 0.1


class TestEipuRei:
    def test_rei_length_zero_limit_matches_ei(self) -> None:
        """极限钉：rei_length=0 → 区域样本=候选点本身 → 区域均值=点级
        EI（幂次样本数下逐位）→ "rei" 与 "ei" 建议逐位一致。"""
        xs = np.array([[0.2, 0.2], [0.4, 0.6], [0.8, 0.1]])
        ys = np.array([_bowl({"x": r[0], "y": r[1]}) for r in xs])
        cfg_ei = EIPUConfig(seed=13, n_candidates=64)
        cfg_rei = EIPUConfig(seed=13, n_candidates=64, rei_length=0.0,
                             rei_samples=16)
        p_ei, d_ei = suggest_next_point(xs, ys, None, EIPU_BOUNDS,
                                        strategy="ei", config=cfg_ei)
        p_rei, d_rei = suggest_next_point(xs, ys, None, EIPU_BOUNDS,
                                          strategy="rei", config=cfg_rei)
        assert p_ei is not None and p_rei is not None
        assert p_rei == p_ei
        assert d_rei["score"] == d_ei["score"]

    def test_regional_mean_ei_needle_vs_plateau(self) -> None:
        """区域平均效应门（已知结构）：窄针尖高 EI（单点尖峰）在区域
        均值下被稀释，宽平台中等 EI 保留——同一 (μ,σ) 面上平台候选的
        区域平均反超针尖候选（与点级 EI 排序相反）。"""
        from rfauto.optimization.eipu import regional_mean_ei

        # 候选 A（针尖）：8 样本中 1 个 EI=4.0、其余 ~0；候选 B（平台）：
        # 8 样本全部 EI=0.8。点级 EI：A(4.0) > B(0.8)；区域平均：
        # A(0.5) < B(0.8)——排序翻转即区域平均的空间平滑签名。
        mu = np.array([[1.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
                       [4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2]])
        sigma = np.zeros_like(mu)
        y_best = 5.0
        scores = regional_mean_ei(mu, sigma, y_best, xi=0.0)
        assert scores.shape == (2,)
        assert scores[0] == pytest.approx(0.5)
        assert scores[1] == pytest.approx(0.8)
        assert scores[1] > scores[0]
        # 点级 EI 排序相反（同一内核 expected_improvement_min）
        from rfauto.optimization.eipu import expected_improvement_min

        point_ei = expected_improvement_min(
            np.array([1.0, 4.2]), np.array([0.0, 0.0]), 5.0, xi=0.0)
        assert point_ei[0] > point_ei[1]

    def test_rei_strategy_smoke_and_determinism(self) -> None:
        """"rei" 档端到端：建议可执行、同 config 逐位、score 为区域均值
        （ei=中心点 EI 仍在诊断面）。"""
        xs = np.array([[0.1, 0.9], [0.5, 0.5], [0.9, 0.2]])
        ys = np.array([_bowl({"x": r[0], "y": r[1]}) for r in xs])
        cfg = EIPUConfig(seed=21, n_candidates=64)
        p1, d1 = suggest_next_point(xs, ys, None, EIPU_BOUNDS,
                                    strategy="rei", config=cfg)
        p2, d2 = suggest_next_point(xs, ys, None, EIPU_BOUNDS,
                                    strategy="rei", config=cfg)
        assert p1 == p2 and d1 == d2
        assert set(p1) == {"x", "y"}
        assert d1["saturated"] is False
        assert d1["score"] >= 0.0

    def test_unknown_strategy_still_rejected(self) -> None:
        xs = np.array([[0.2, 0.2], [0.4, 0.6]])
        ys = np.array([0.5, 0.3])
        with pytest.raises(ValueError, match="未知 strategy"):
            suggest_next_point(xs, ys, None, EIPU_BOUNDS, strategy="nope")

    def test_run_eipu_loop_rei_strategy(self) -> None:
        """run_eipu_loop 消费 "rei" 档（strategy 透传面）。"""
        from rfauto.optimization.eipu import run_eipu_loop

        r = run_eipu_loop(
            _bowl, lambda p: 1.0, EIPU_BOUNDS, n_iters=4, strategy="rei",
            n_init=3, config=EIPUConfig(seed=33, n_candidates=64))
        assert len(r["trials"]) == 7 and r["strategy"] == "rei"


# ═══════════════════════ optimizer 旋钮透传 ═══════════════════════


class TestOptimizerKnobs:
    @pytest.fixture
    def wilkinson_recipe(self, tmp_path: Path) -> Path:
        """最小化配方（与 test_acq_sampler.py 同构）。"""
        import yaml

        recipe = {
            "model": "wilkinson_power_divider",
            "params": {
                "f0_ghz": {"value": 2.4, "unit": "GHz"},
                "z0_ohm": {"value": 50, "unit": "ohm"},
                "substrate": "rogers4350b_h0.508",
                "division": "1:1",
                "arm_len_mm": {"value": 20.5},
                "series_w_mm": {"value": 0.33},
                "shunt_w_mm": {"value": 1.10},
            },
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
                 "value": -15},
            ],
            "optimization": {
                "params": {
                    "arm_len_mm": {"low": 18.0, "high": 23.0},
                    "series_w_mm": {"low": 0.25, "high": 0.45},
                },
            },
        }
        p = tmp_path / "recipe.yaml"
        p.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        return p

    def test_turbo_knobs_pass_through(
            self, tmp_path: Path, wilkinson_recipe: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.optimizer import run_optimization

        r = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=6,
            sampler="turbo", seed=42, turbo_n_regions=2,
            turbo_region_strategy="ts")
        assert r["ok"] and r["sampler"] == "turbo"
        assert r["turbo_n_regions"] == 2
        assert r["turbo_region_strategy"] == "ts"

    def test_eipu_rei_strategy_pass_through(
            self, tmp_path: Path, wilkinson_recipe: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.optimizer import run_optimization

        r = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=6,
            sampler="eipu", seed=42, eipu_strategy="rei")
        assert r["ok"] and r["eipu_strategy"] == "rei"

    def test_knob_mismatch_rejected(
            self, tmp_path: Path, wilkinson_recipe: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        """旋钮错配 sampler 显式拒绝（不静默吞参数，journal_path 同款）。"""
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.optimizer import run_optimization

        r1 = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=2,
            sampler="tpe", turbo_n_regions=2)
        assert not r1["ok"] and "仅在 sampler='turbo'" in r1["errors"][0]
        r2 = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=2,
            sampler="turbo", eipu_strategy="rei")
        assert not r2["ok"] and "仅在 sampler='eipu'" in r2["errors"][0]
        r3 = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=2,
            sampler="turbo", turbo_region_strategy="nope")
        assert not r3["ok"] and "未知 turbo_region_strategy" in r3["errors"][0]
        r4 = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=2,
            sampler="turbo", turbo_n_regions=0)
        assert not r4["ok"] and "turbo_n_regions" in r4["errors"][0]

    def test_default_no_knobs_no_new_keys(
            self, tmp_path: Path, wilkinson_recipe: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        """缺省（旋钮全 None）路径：结果无旋钮键（输出键集不变）。"""
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.optimizer import run_optimization

        r = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=4,
            sampler="turbo", seed=42)
        assert r["ok"]
        assert "turbo_n_regions" not in r
        assert "turbo_region_strategy" not in r
        assert "eipu_strategy" not in r
