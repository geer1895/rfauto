"""T-N7 GP 批量采集单测（aurora_n W1-C，surrogate_loop batch_acquisition 旋钮）。

判据（任务书预声明，runs/aurora_n/recon/PROPOSALS.md §T-N7；口径在本文件
冻结后不得移动，#122）：
- **AUC 门（批量 vs 逐点 EI，同预算）**：合成 GP 样本路径面（提案"合成
  GP 面"字面口径；真值=独立手写 RBF 插值，不走 gp_det——#118 裁判独立
  构造）×20 seed，预算 24 评估/n_init 8/两臂严格等评估数（末批截断），
  K=2（=环内 top_k−1 缺省形态）。冻结探针实测（runs/aurora_n/wave1_c/
  probe 谱系）：批量臂 wins 13/20（≥60% 门）+ 中位 AUC 比 0.9748（聚合
  不劣门 ≤1.0）。两门同时判。工程语义（如实）：单峰解析面上批量臂与逐
  点 EI 每-评估效率打平（探针 median ratio≈1.00）——批量档的价值=每轮
  1 次拟合/求解往返换 K 个设计（真机墙钟收益），AUC 门保证的是"批量机
  制不毁每-评估效率"；
- **负例**：σ≡0 退化（amp=0）显式 degenerate 上报、order 空；环级退化/
  GP 拟合失败显式回退逐点路径并在 round_entry["batch_acquisition"]
  ["fallback"] 记原因（trace 与缺省路径逐位一致=回退真实发生，不静默）；
- **确定性钉**：同输入采集序逐位复现（helper 级）+ 同 seed 环两次运行
  real_cost_trace 逐位一致（环级）；
- **缺省等价钉**：batch_acquisition 缺省 None 时结果体与 round entry
  键面零新增（T-N7 代码路径零触发）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.core.objectives import MetricOp, Objective
from rfauto.optimization.surrogate import gp_det
from rfauto.optimization.surrogate_loop import (
    BATCH_ACQUISITION_MODES,
    run_surrogate_loop,
)

OBJS = [Objective(metric="s11_db_min", band=[2.3, 2.5],
                  op=MetricOp.MAX_BELOW, value=-47.0, weight=1.0)]
BOUNDS = {"x_mm": (0.0, 1.0), "y_mm": (0.0, 1.0)}


def _bowl(params: dict[str, float]) -> dict[str, float]:
    """既有环内裁判面（光滑碗+纹波；环级冒烟用，AUC 门不用它）。"""
    dx = params["x_mm"] - 0.30
    dy = params["y_mm"] - 0.62
    depth = -46.0 + 180.0 * dx * dx + 150.0 * dy * dy - 120.0 * dx * dy
    depth += 1.5 * math.sin(3.0 * math.pi * params["x_mm"]) * \
        math.sin(3.0 * math.pi * params["y_mm"])
    return {"s11_db_min_in_band": depth}


def _run_loop(**kw):
    base = dict(bounds=dict(BOUNDS), objectives=list(OBJS),
                evaluate_fn=_bowl, n_init=8, top_k=3, virtual_trials=400,
                max_real=24, seed=42)
    base.update(kw)
    return run_surrogate_loop(**base)


# ── gp_det 内核：EI 与 KB 批量 ─────────────────────────────────────────

class TestExpectedImprovement:
    def test_hand_computed_values(self):
        """μ=σ=y_best=0：EI=σ·φ(0)（手算 0.3989）；改进为正加线性项。"""
        ei = gp_det.expected_improvement(
            np.array([0.0]), np.array([1.0]), 0.0)
        assert ei[0] == pytest.approx(0.3989422804014327, rel=1e-12)
        # improve=0.5（μ=-0.5,σ=1,y_best=0）：z=0.5 → 0.5·Φ(.5)+φ(.5)
        ei2 = gp_det.expected_improvement(
            np.array([-0.5]), np.array([1.0]), 0.0)
        phi = math.exp(-0.125) / math.sqrt(2.0 * math.pi)
        cdf = 0.5 * (1.0 + math.erf(0.5 / math.sqrt(2.0)))
        assert ei2[0] == pytest.approx(0.5 * cdf + phi, rel=1e-12)

    def test_sigma_zero_convention_no_fake_exploration(self):
        """σ=0 约定：EI=max(y_best−μ, 0)——无 σ 项，不伪造探索信号。"""
        ei = gp_det.expected_improvement(
            np.array([-1.0, 0.5]), np.array([0.0, 0.0]), 0.0)
        assert ei[0] == pytest.approx(1.0)
        assert ei[1] == 0.0


class TestKrigingBelieverBatch:
    def _setup(self):
        rng = np.random.default_rng(7)
        x_train = rng.uniform(0.0, 1.0, (10, 2))
        y_train = 1.0 - x_train[:, 0] - 0.5 * x_train[:, 1]
        pool = np.random.default_rng(8).uniform(0.0, 1.0, (64, 2))
        params = gp_det.fit_mle(x_train, y_train)
        return x_train, y_train, pool, params

    def test_deterministic_sequence_bit_identical(self):
        """确定性钉：同输入两次批量采集序逐位一致。"""
        x, y, pool, params = self._setup()
        kw = dict(ell=params["ell"], amp=params["amp"],
                  nugget=params["nugget"], k=4)
        r1 = gp_det.kriging_believer_ei_batch(x, y, pool, **kw)
        r2 = gp_det.kriging_believer_ei_batch(x, y, pool, **kw)
        assert r1["order"] == r2["order"]
        assert r1["ei"] == r2["ei"]  # 逐位（无量化容差）
        assert r1["sigma_max"] == r2["sigma_max"]

    def test_first_pick_matches_pointwise_ei_argmax(self):
        """首席=逐点 EI argmax（批量机制是逐点的条件化延伸，构造一致性）。"""
        x, y, pool, params = self._setup()
        res = gp_det.kriging_believer_ei_batch(
            x, y, pool, ell=params["ell"], amp=params["amp"],
            nugget=params["nugget"], k=3)
        mu, var = gp_det.gp_posterior(
            x, y, pool, ell=params["ell"], amp=params["amp"],
            nugget=params["nugget"])
        ei0 = gp_det.expected_improvement(
            mu, np.sqrt(np.maximum(var, 0.0)), float(y.min()))
        assert res["order"][0] == int(np.argmax(ei0))

    def test_batch_spreads_picks(self):
        """KB 条件化自带分散性：任两席间归一化距离 ≥0.1（伪观测压 σ）。"""
        x, y, pool, params = self._setup()
        res = gp_det.kriging_believer_ei_batch(
            x, y, pool, ell=params["ell"], amp=params["amp"],
            nugget=params["nugget"], k=4)
        pts = pool[res["order"]]
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                d = float(np.linalg.norm(pts[i] - pts[j]))
                assert d >= 0.1, f"批量第 {i},{j} 席距离 {d:.3f} 聚类"

    def test_sigma_zero_degenerate_explicit(self):
        """负例（σ≡0 退化）：amp=0 → degenerate=True + order 空（不伪造）。"""
        x = np.linspace(0.0, 1.0, 6).reshape(-1, 1)
        y = x.ravel().copy()
        pool = np.random.default_rng(3).uniform(0.0, 1.0, (16, 1))
        res = gp_det.kriging_believer_ei_batch(
            x, y, pool, ell=np.array([0.3]), amp=0.0, nugget=1e-10, k=3)
        assert res["degenerate"] is True
        assert res["order"] == []
        assert res["sigma_max"] == 0.0

    def test_k_exceeds_pool_partial_order(self):
        """k>池规模：止步于池规模，序不重复（不崩溃、不伪造）。"""
        x = np.random.default_rng(5).uniform(0.0, 1.0, (8, 2))
        y = x[:, 0] + 0.3 * x[:, 1]
        pool = np.random.default_rng(6).uniform(0.0, 1.0, (3, 2))
        params = gp_det.fit_mle(x, y)
        res = gp_det.kriging_believer_ei_batch(
            x, y, pool, ell=params["ell"], amp=params["amp"],
            nugget=params["nugget"], k=8)
        assert len(res["order"]) == 3
        assert len(set(res["order"])) == 3


# ── 环级：旋钮接线/负例回退/确定性/缺省等价 ───────────────────────────

class TestLoopKnobWiring:
    def test_default_path_key_surface_unchanged(self):
        """缺省等价钉：None 档结果体与全部 round entry 无 T-N7 新键。"""
        r = _run_loop()
        assert r["ok"] is True
        assert "batch_acquisition" not in r
        for entry in r["rounds"]:
            assert "batch_acquisition" not in entry

    def test_knob_on_diagnostic_and_determinism(self):
        """KB 档：顶层+逐轮诊断键在位（无回退）；同 seed 两次 trace 逐位一致。"""
        r1 = _run_loop(batch_acquisition="kriging_believer")
        r2 = _run_loop(batch_acquisition="kriging_believer")
        assert r1["batch_acquisition"] == "kriging_believer"
        round_entries = [e for e in r1["rounds"]
                         if e.get("phase") != "lhs_init"]
        assert round_entries
        for entry in round_entries:
            diag = entry["batch_acquisition"]
            assert diag["mode"] == "kriging_believer"
            assert diag["fallback"] is None
            assert diag["n_selected"] == 2  # top_k-1=2 个 KB 席位
        assert r1["real_cost_trace"] == r2["real_cost_trace"]

    def test_diversity_alias_is_old_path(self):
        """"diversity" 显式档=旧路径语义（trace 同 None；无逐轮 KB 诊断键）。"""
        r_none = _run_loop()
        r_div = _run_loop(batch_acquisition="diversity")
        assert r_div["batch_acquisition"] == "diversity"
        for entry in r_div["rounds"]:
            assert "batch_acquisition" not in entry  # 逐轮诊断仅 KB 档有
        assert r_none["real_cost_trace"] == r_div["real_cost_trace"]

    def test_invalid_knob_rejected(self):
        bad = _run_loop(batch_acquisition="bogus")
        assert bad["ok"] is False
        assert any("batch_acquisition" in e for e in bad["errors"])
        assert set(BATCH_ACQUISITION_MODES) == {"diversity",
                                                "kriging_believer"}

    def test_sigma_degenerate_falls_back_to_pointwise(self, monkeypatch):
        """负例（σ≡0）：显式回退逐点并标注——trace 与缺省路径逐位一致。"""
        def _degenerate(*_a, **_kw):
            return {"order": [], "ei": [], "sigma_max": 0.0,
                    "degenerate": True}
        monkeypatch.setattr(
            "rfauto.optimization.surrogate.gp_det.kriging_believer_ei_batch",
            _degenerate)
        r_default = _run_loop()
        r_kb = _run_loop(batch_acquisition="kriging_believer")
        assert r_kb["real_cost_trace"] == r_default["real_cost_trace"]
        entries = [e for e in r_kb["rounds"]
                   if e.get("phase") != "lhs_init"]
        assert entries
        for entry in entries:
            assert entry["batch_acquisition"]["fallback"] == \
                "sigma_degenerate"

    def test_gp_fit_failed_falls_back_and_annotated(self, monkeypatch):
        """GP 拟合失败：回退逐点 + fallback=gp_fit_failed（环不炸）。"""
        def _boom(*_a, **_kw):
            raise np.linalg.LinAlgError("singular matrix")
        monkeypatch.setattr(
            "rfauto.optimization.surrogate.gp_det.fit_mle", _boom)
        r = _run_loop(batch_acquisition="kriging_believer")
        assert r["ok"] is True
        entries = [e for e in r["rounds"] if e.get("phase") != "lhs_init"]
        assert entries
        assert all(e["batch_acquisition"]["fallback"] == "gp_fit_failed"
                   for e in entries)

    def test_mf_mode_smoke(self):
        """多保真模式冒烟：KB 档不炸环、诊断在位（语义=全已评样本同池）。"""
        def low(_params):
            return _bowl({"x_mm": 0.5, "y_mm": 0.5})
        r = _run_loop(batch_acquisition="kriging_believer",
                      evaluate_low_fn=low, max_real=16)
        assert r["ok"] is True
        assert r.get("fidelity") == "multi"


# ── AUC 门：批量 KB-EI vs 逐点 EI（同预算，合成 GP 样本路径面） ─────────

class TestBatchAucGate:
    #: 冻结口径（探针 runs/aurora_n/wave1_c/probe_tn7_*：13/20 + 0.9748）
    SEEDS = tuple(range(101, 121))
    BUDGET = 24
    N_INIT = 8
    K = 2           # = 环内 top_k-1 缺省形态
    POOL_N = 2048
    SURFACE_ELL = 0.35
    SURFACE_GRID = 7
    WIN_MIN = 0.60  # ≥60%（任务书预声明）
    AUC_TOL = 1e-9

    @staticmethod
    def _gp_path_surface(seed: int):
        """独立真值面：固定 seed 的 GP 先验样本路径（手写 RBF 插值，
        不经 gp_det——#118 裁判独立构造）。"""
        g = np.linspace(0.0, 1.0, TestBatchAucGate.SURFACE_GRID)
        gx, gy = np.meshgrid(g, g)
        pts = np.column_stack([gx.ravel(), gy.ravel()])
        z = np.random.default_rng(seed).normal(0.0, 1.0, len(pts))
        ell = TestBatchAucGate.SURFACE_ELL
        d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
        k_mat = np.exp(-d2 / (2.0 * ell * ell))
        k_mat[np.diag_indices(len(pts))] += 1e-8
        w = np.linalg.solve(k_mat, z)

        def f(x: float, y: float) -> float:
            p = np.array([x, y])
            k = np.exp(-((pts - p) ** 2).sum(-1) / (2.0 * ell * ell))
            return float(k @ w)

        return f

    @classmethod
    def _lhs(cls, n: int, seed: int) -> np.ndarray:
        from rfauto.optimization.sample_design import lhs_points
        pts = lhs_points(BOUNDS, n, seed=seed)["points"]
        return np.array([[p["x_mm"], p["y_mm"]] for p in pts])

    @classmethod
    def _run_arm(cls, surface, seed: int, batch_k: int | None) -> float:
        """单臂寻优（minimization）：返回 best-so-far 均值（AUC，独立记账）。

        两臂评估数严格相等（末批按剩余预算截断）——探针 v1 曾因 24 不整
        除 K=3 让批量臂多评 2 点的记账bug（已修，见 probe_tn7 谱系）。
        """
        x = cls._lhs(cls.N_INIT, seed)
        y = np.array([surface(*p) for p in x])
        n = cls.N_INIT
        while n < cls.BUDGET:
            params = gp_det.fit_mle(x, y)
            pool = cls._lhs(cls.POOL_N, seed + 7777 + n)
            if batch_k is None:
                mu, var = gp_det.gp_posterior(
                    x, y, pool, ell=params["ell"], amp=params["amp"],
                    nugget=params["nugget"])
                ei = gp_det.expected_improvement(
                    mu, np.sqrt(np.maximum(var, 0.0)), float(y.min()))
                pick = pool[int(np.argmax(ei))][None, :]
            else:
                res = gp_det.kriging_believer_ei_batch(
                    x, y, pool, ell=params["ell"], amp=params["amp"],
                    nugget=params["nugget"],
                    k=min(batch_k, cls.BUDGET - n))
                pick = pool[res["order"]]
            y = np.concatenate([y, [surface(*p) for p in pick]])
            x = np.vstack([x, pick])
            n += len(pick)
        assert n == cls.BUDGET
        return float(np.minimum.accumulate(y).mean())

    def test_batch_auc_not_worse_than_pointwise_majority_seeds(self):
        """批量臂 AUC 不劣于逐点 EI：wins ≥60% 且中位 AUC 比 ≤1.0（冻结）。"""
        ratios: list[float] = []
        for seed in self.SEEDS:
            surface = self._gp_path_surface(seed + 555)
            auc_pt = self._run_arm(surface, seed, None)
            auc_kb = self._run_arm(surface, seed, self.K)
            ratios.append(auc_kb / auc_pt)
        r = np.asarray(ratios)
        wins = int((r <= 1.0 + self.AUC_TOL).sum())
        median_ratio = float(np.median(r))
        # 失败时打印全序比（诊断面），门本身按冻结口径判
        detail = " ".join(f"{v:.4f}" for v in r)
        assert wins >= math.ceil(self.WIN_MIN * len(self.SEEDS)), (
            f"批量臂 wins={wins}/{len(r)} < 60% 门（冻结口径）；"
            f"ratios=[{detail}]")
        assert median_ratio <= 1.0, (
            f"中位 AUC 比 {median_ratio:.4f} > 1.0（聚合不劣门）；"
            f"ratios=[{detail}]")
