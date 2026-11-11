"""T-N14 鲁棒 BO 单测（aurora_n W2，surrogate_loop robust_lambda/op_chance 旋钮）。

判据（预声明 runs/aurora_n/w2_tn14/CRITERIA.md；冻结常量来自
probe_robust_tradeoff.py 实测 2026-10-29，冻结后不得移动，#122）：

- **μ-σ 权衡门（合成含噪平台问题，声明式异方差代理）**：最优解附近存在
  方差梯度（μ 凹坑 x=0.40 处 σ 大、x≈0.61 处 σ 小）——鲁棒档（λ=4.0，
  闭式交叉点 λ*=2.4162 的 1.65 倍）采集选点 σ 显著更低、μ 代价有限、
  真实 best 不塌：G1 σ 比 ≤0.70（实测 0.389）/ G2 μ 增幅 ≤+0.30（实测
  +0.161）/ G3 真实 best 比 ≤1.05（实测 1.0000）；3 seed 全表
  （0.341/0.389/0.489）留档 runs/aurora_n/w2_tn14/probe_robust_tradeoff.json；
- **确定性钉**：同 seed robust 档两次运行结果逐位（剔除 elapsed_s 墙钟）；
  op_chance 档 z=Φ⁻¹(0.9)=1.2815515655446004 双精度锚（rdo 单源闭式）；
- **负例（全部显式报错不静默降级）**：λ<0 / p 出 (0,1) / 两旋钮同给 /
  非有限数 → 入口拒绝 {"ok":False,"errors":[...]} 零真跑；σ 缺席
  （poly_ridge 契约 std=None，及 NaN/inf/负 σ）→ 首个采集轮硬停
  stop_reason="robust_sigma_unavailable" + robust.error 原文（不按均值档
  假装继续、不按 1e12 罚值伪造排序）；
- **缺省等价钉**：缺省双 None 结果体零新增键（"robust" 仅旋钮开启时
  存在）+ 缺省 real_cost_trace 冻结字面量（改前金样 golden_default.json
  逐字节比对另行留档 runs/aurora_n/w2_tn14/verify_default_equivalence.py
  输出，四 case 含约束/批量/多保真）；
- **组合性（红线 3）**：robust_lambda + batch_acquisition="kriging_believer"
  同开不炸、双键齐备、同 seed 序列确定；
- 风险数学单源：μ±λσ 组合/分位数全部经 rdo.robust_objective /
  rdo.chance_constraint_bound（helper 不重写任何闭式），hinge 单源
  SpecEvaluator.evaluate_objectives（逐目标单键调用）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.core.objectives import MetricOp, Objective
from rfauto.optimization.rdo import (
    chance_constraint_bound,
    gaussian_quantile,
    robust_objective,
)
from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)
from rfauto.optimization.surrogate_loop import (
    ROBUST_SIGMA_STOP_REASON,
    RobustSigmaUnavailableError,
    _robust_objective_cost,
    run_surrogate_loop,
)

OBJ_MB = Objective(metric="s11_db_min", band=[2.3, 2.5],
                   op=MetricOp.MAX_BELOW, value=-47.0, weight=1.0)
OBJ_MA = Objective(metric="s11_db_min", band=[2.3, 2.5],
                   op=MetricOp.MIN_ABOVE, value=-46.5, weight=1.0)
OBJ_MW = Objective(metric="s11_db_min", band=[2.3, 2.5],
                   op=MetricOp.MEAN_WITHIN, value=[-46.2, -45.8], weight=1.0)
BOUNDS = {"x_mm": (0.0, 1.0), "y_mm": (0.0, 1.0)}
BOUNDS_1D = {"x_mm": (0.0, 1.0)}
X_BUMP = 0.40
LAM_FROZEN = 4.0
# Φ⁻¹(0.9) 独立来源锚（scipy.stats.norm.ppf 口径）；rdo 内核走 stdlib
# statistics.NormalDist（末位 1 ulp 差=实现差异，身份钉用内核闭式本身）
Z_P90_INDEP = 1.2815515655446004


def m_true(x: float) -> float:
    return -46.0 + 2.0 * (x - 0.5) ** 2


def mu_face(x: float) -> float:
    return m_true(x) - 0.50 * math.exp(-(((x - X_BUMP) / 0.10) ** 2))


def sigma_face(x: float) -> float:
    return 0.02 + 0.20 * math.exp(-(((x - X_BUMP) / 0.10) ** 2))


class Tn14HeteroPlateau(SurrogateModel):
    """声明式异方差合成代理（fit 不学数据——受控 μ/σ 面，T-N7 先例）。

    注册治理（aurora_p 遗留 2）：本类不再模块级 @register（进程级持久
    写入=xdist 同 worker 污染源，D5/G3 双席撞实录）——由下方 autouse
    fixture 惰性注册+teardown 还原。
    """

    KIND = "tn14_hetero_plateau"

    def fit(self, samples):
        return self._mark_fitted(len(samples))

    def predict(self, params):
        return {"s11_db_min_in_band": mu_face(float(params["x_mm"]))}

    def uncertainty(self, params):
        return {"s11_db_min_in_band": sigma_face(float(params["x_mm"]))}


@pytest.fixture(autouse=True)
def _tn14_hetero_plateau_registered():
    """Tn14HeteroPlateau fixture 作用域注册+teardown 快照还原。

    模块级 @surrogate_registry.register 是进程级持久写入：import 即落表，
    xdist 同 worker 此后运行的一切测试都看得见该键（test_onnx_numpy_export
    覆盖面"注册表⊆表"反向断言被污染实录，D5/G3 双席撞）。治理=每测试
    setup 缺则注册、teardown 仅还原本席写入（#362 reg 快照还原语义的
    键级最小形态；surrogate 注册表 allow_overwrite=True，重名注入静默
    覆盖不炸，还原仍须 faithful——不吞他席既有键）。
    """
    kind = "tn14_hetero_plateau"
    preexisting = kind in surrogate_registry.available()
    if not preexisting:
        surrogate_registry.register(kind, Tn14HeteroPlateau)
    yield Tn14HeteroPlateau
    if not preexisting and kind in surrogate_registry.available():
        surrogate_registry.unregister(kind)


def _bowl(params: dict[str, float]) -> dict[str, float]:
    """既有环内裁判面（缺省等价/负例入口用）。"""
    dx = params["x_mm"] - 0.30
    dy = params["y_mm"] - 0.62
    depth = -46.0 + 180.0 * dx * dx + 150.0 * dy * dy - 120.0 * dx * dy
    depth += 1.5 * math.sin(3.0 * math.pi * params["x_mm"]) * \
        math.sin(3.0 * math.pi * params["y_mm"])
    return {"s11_db_min_in_band": depth}


def _plateau_metrics(params: dict[str, float]) -> dict[str, float]:
    return {"s11_db_min_in_band": m_true(float(params["x_mm"]))}


def _run_bowl(**kw):
    base = dict(bounds=dict(BOUNDS), objectives=[OBJ_MB], evaluate_fn=_bowl,
                n_init=6, top_k=3, virtual_trials=200, max_real=12, seed=42)
    base.update(kw)
    return run_surrogate_loop(**base)


def _run_plateau(**kw):
    seen: list[float] = []

    def eval_fn(params: dict[str, float]) -> dict[str, float]:
        seen.append(float(params["x_mm"]))
        return _plateau_metrics(params)

    base = dict(bounds=dict(BOUNDS_1D), objectives=[OBJ_MB],
                evaluate_fn=eval_fn,
                n_init=6, top_k=4, virtual_trials=400, max_real=14,
                tol_abs=0.0, min_dist=0.04, seed=42,
                surrogate_kind="tn14_hetero_plateau")
    base.update(kw)
    res = run_surrogate_loop(**base)
    return res, seen


# ── helper 级：逐 op 风险侧映射（#118 手算独立锚） ────────────────────────

class TestRobustObjectiveCost:
    def test_max_below_upper_bound(self):
        """MAX_BELOW 取 μ+λσ 上界式（cost 随指标递增）——手算锚。"""
        # μ=-46.33, σ=0.16, λ=2 → val_up=-46.01 → cost=val_up+47=0.99
        pw = {"s11_db_min_in_band": (-46.33, 0.16)}
        got = _robust_objective_cost(pw, [OBJ_MB],
                                     robust_fn=robust_objective, param=2.0)
        assert got == pytest.approx(0.99, rel=1e-12)

    def test_min_above_lower_bound_lcb(self):
        """MIN_ABOVE 取 μ−λσ 下界式（worst-case LCB）——负号经
        −robust_fn(−μ,σ,param) 复用同一闭式，手算锚。"""
        # μ=-46.8, σ=0.1, λ=2 → val_lo=-47.0 → 违约=max(0,-46.5-(-47.0))=0.5
        pw = {"s11_db_min_in_band": (-46.8, 0.1)}
        got = _robust_objective_cost(pw, [OBJ_MA],
                                     robust_fn=robust_objective, param=2.0)
        assert got == pytest.approx(0.5, rel=1e-12)
        # 对照：无违约侧（μ 高、σ 小）→ 0
        pw2 = {"s11_db_min_in_band": (-46.0, 0.1)}
        assert _robust_objective_cost(
            pw2, [OBJ_MA], robust_fn=robust_objective,
            param=2.0) == pytest.approx(0.0)

    def test_mean_within_two_sided_worst_case(self):
        """MEAN_WITHIN 凸 hinge 两端点取 max（精确 worst-case）——手算锚。"""
        # μ=-46.0, σ=0.1, λ=2 → 端点 -46.2/-45.8 恰在带缘 → 违约 0
        pw = {"s11_db_min_in_band": (-46.0, 0.1)}
        assert _robust_objective_cost(
            pw, [OBJ_MW], robust_fn=robust_objective,
            param=2.0) == pytest.approx(0.0)
        # μ=-46.1 → 端点 -46.3/-45.9 → worst=低侧违约 0.1
        pw2 = {"s11_db_min_in_band": (-46.1, 0.1)}
        got = _robust_objective_cost(pw2, [OBJ_MW],
                                     robust_fn=robust_objective, param=2.0)
        assert got == pytest.approx(0.1, rel=1e-12)

    def test_op_chance_bound_single_source(self):
        """op_chance 档经 chance_constraint_bound(μ,σ,1−p)=μ+Φ⁻¹(p)σ
        （rdo 单源）——z 锚逐位。"""
        pw = {"s11_db_min_in_band": (-46.0, 0.1)}
        got = _robust_objective_cost(pw, [OBJ_MB],
                                     robust_fn=chance_constraint_bound,
                                     param=1.0 - 0.9)
        assert got == pytest.approx((-46.0 + Z_P90_INDEP * 0.1) + 47.0,
                                    rel=1e-12)

    def test_sigma_missing_explicit_error(self):
        """σ 缺席/非有限/负值 → RobustSigmaUnavailableError（不静默）。"""
        for bad in (None, float("nan"), float("inf"), -0.1):
            pw = {"s11_db_min_in_band": (-46.0, bad)}
            with pytest.raises(RobustSigmaUnavailableError):
                _robust_objective_cost(pw, [OBJ_MB],
                                       robust_fn=robust_objective, param=2.0)

    def test_missing_metric_key_skips(self):
        """指标键缺席按 evaluate_objectives 既有口径贡献 0（不报错）。"""
        pw = {"other_metric": (-46.0, 0.1)}
        got = _robust_objective_cost(pw, [OBJ_MB],
                                     robust_fn=robust_objective, param=2.0)
        assert got == 0.0


# ── 入口负例（零真跑侧效应） ─────────────────────────────────────────────

class TestEntryValidation:
    @pytest.mark.parametrize("kw", [
        {"robust_lambda": -0.5},
        {"robust_lambda": float("nan")},
        {"robust_lambda": float("inf")},
        {"op_chance": 0.0},
        {"op_chance": 1.0},
        {"op_chance": 1.5},
        {"op_chance": -0.1},
        {"op_chance": float("nan")},
    ])
    def test_invalid_params_rejected(self, kw):
        calls = []

        def spy(params):
            calls.append(params)
            return _bowl(params)

        res = _run_bowl(evaluate_fn=spy, **kw)
        assert res["ok"] is False
        assert res["errors"]
        assert calls == []  # 零真跑

    def test_both_knobs_rejected(self):
        res = _run_bowl(robust_lambda=2.0, op_chance=0.9)
        assert res["ok"] is False
        assert any("互斥" in e for e in res["errors"])


# ── σ 缺席硬停（不静默降级） ─────────────────────────────────────────────

class TestSigmaMissingHardStop:
    @pytest.mark.parametrize("kw", [
        {"robust_lambda": 2.0},
        {"op_chance": 0.9},
    ])
    def test_poly_ridge_no_sigma_hard_stops(self, kw):
        """poly_ridge（base 契约 std=None）开 robust 档 → 首个采集轮硬停。"""
        res = _run_bowl(**kw)
        assert res["ok"] is True
        assert res["stop_reason"] == ROBUST_SIGMA_STOP_REASON
        assert res["robust"]["error"]  # 原文原因外显
        assert res["robust"]["n_robust_rounds"] == 0
        # 零 robust 影响的选点发生：只有 LHS 初始批（round0）
        assert len(res["rounds"]) == 1
        assert res["rounds"][0]["phase"] == "lhs_init"
        assert res["n_real_used"] == 6


# ── 确定性钉 ─────────────────────────────────────────────────────────────

def _strip_elapsed(obj):
    if isinstance(obj, dict):
        return {k: _strip_elapsed(v) for k, v in obj.items()
                if k != "elapsed_s"}
    if isinstance(obj, list):
        return [_strip_elapsed(v) for v in obj]
    return obj


class TestDeterminism:
    def test_same_seed_bit_identical(self):
        r1, seen1 = _run_plateau(robust_lambda=LAM_FROZEN)
        r2, seen2 = _run_plateau(robust_lambda=LAM_FROZEN)
        assert seen1 == seen2
        assert json.dumps(_strip_elapsed(r1), sort_keys=True) == \
            json.dumps(_strip_elapsed(r2), sort_keys=True)

    def test_z_anchor_lambda_mode(self):
        res, _ = _run_plateau(robust_lambda=LAM_FROZEN)
        assert res["robust"]["z"] == LAM_FROZEN
        assert res["robust"]["mode"] == "robust_lambda"
        assert res["robust"]["error"] is None

    def test_z_anchor_op_chance_mode(self):
        res, _ = _run_plateau(op_chance=0.9)
        # 身份钉：z=Φ⁻¹(0.9) 逐位（rdo.gaussian_quantile 内核闭式本身）
        assert res["robust"]["z"] == gaussian_quantile(0.9)
        # 独立来源锚（scipy 口径）±1 ulp 内（NormalDist vs scipy 实现差）
        assert res["robust"]["z"] == pytest.approx(Z_P90_INDEP, rel=1e-12)
        assert res["robust"]["mode"] == "op_chance"
        assert res["robust"]["op_chance"] == 0.9


# ── 验收①：μ-σ 权衡门（冻结常数，CRITERIA §6） ──────────────────────────

class TestMuSigmaTradeoff:
    def test_robust_arm_lower_sigma_bounded_mu_cost(self):
        mean_res, mean_seen = _run_plateau()
        rob_res, rob_seen = _run_plateau(robust_lambda=LAM_FROZEN)
        assert mean_res["stop_reason"] == "budget"
        assert rob_res["stop_reason"] == "budget"
        m_pts, r_pts = mean_seen[6:], rob_seen[6:]
        m_sigma = sum(sigma_face(x) for x in m_pts) / len(m_pts)
        r_sigma = sum(sigma_face(x) for x in r_pts) / len(r_pts)
        m_mu = sum(mu_face(x) for x in m_pts) / len(m_pts)
        r_mu = sum(mu_face(x) for x in r_pts) / len(r_pts)
        # G1：鲁棒档选点 σ 显著更低（实测 0.389，门 0.70；探针 3 seed
        # 最坏 0.489）
        assert r_sigma / m_sigma <= 0.70
        # G2：give-up μ 有界（实测 +0.161，门 +0.30=表观凹坑收益 0.5 的 60%）
        assert r_mu - m_mu <= 0.30
        # G3：真实 best 不塌（实测 1.0000）
        assert rob_res["best"]["cost"] / mean_res["best"]["cost"] <= 1.05
        # 机理抽查：均值档首选区落 μ 凹坑高 σ 区，鲁棒档落低 σ 区
        assert sigma_face(m_pts[0]) > 0.10
        assert sigma_face(r_pts[0]) < 0.05

    def test_lambda_below_crossover_stays_near_mean(self):
        """剂量响应：λ=2 < λ*=2.4162 → 选点区仍近均值档（语义如式）。"""
        _, mean_seen = _run_plateau()
        _, lam2_seen = _run_plateau(robust_lambda=2.0)
        m_sigma = sum(sigma_face(x) for x in mean_seen[6:]) / 8
        l2_sigma = sum(sigma_face(x) for x in lam2_seen[6:]) / 8
        assert l2_sigma / m_sigma <= 1.0 + 1e-9


# ── 验收④：缺省等价钉 ───────────────────────────────────────────────────

class TestDefaultEquivalence:
    def test_no_new_keys_when_knobs_off(self):
        res = _run_bowl()
        assert res["ok"] is True
        assert "robust" not in res
        for entry in res["rounds"]:
            assert "robust" not in entry

    def test_default_trace_frozen(self):
        """缺省路径 real_cost_trace 冻结字面量（改前金样 case A 实测，
        golden_default.json 逐字节比对另行留档 runs/）。"""
        res = _run_bowl(n_init=8, virtual_trials=400, max_real=24)
        assert res["real_cost_trace"] == [
            101.84660753464644, 6.486047781826748, 125.13327011721749,
            13.493993862150994, 5.762523013359548, 118.96151569852918,
            3.9488861133654467, 4.534056569868866, 11.001098664536094,
            14.134016050869768, 44.62324216137311, 3.960107100131559,
            6.026283962428437, 77.67732598343017]


# ── 组合性：robust + batch_acquisition 同开（红线 3） ────────────────────

class TestRobustPlusBatch:
    def test_composition_runs_deterministic(self):
        kw = dict(robust_lambda=LAM_FROZEN,
                  batch_acquisition="kriging_believer")
        r1, seen1 = _run_plateau(**kw)
        r2, seen2 = _run_plateau(**kw)
        assert seen1 == seen2
        assert json.dumps(_strip_elapsed(r1), sort_keys=True) == \
            json.dumps(_strip_elapsed(r2), sort_keys=True)
        assert r1["robust"]["mode"] == "robust_lambda"
        assert r1["batch_acquisition"] == "kriging_believer"
        for entry in r1["rounds"][1:]:
            assert "batch_acquisition" in entry  # T-N7 键面（旋钮开启时）
            assert entry["batch_acquisition"]["mode"] == "kriging_believer"
