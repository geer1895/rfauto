"""output_sm_service 单测：DP-14 N8 三钉（合成回收/信任域/确定性）+ 契约。

判据预声明见 runs/df6_dp14n8/criteria.md（钉 a：affine 回收 ≤1e-6；
插值 ≤1e-7；钉 c：超 τ 回退+告警；钉 d：双跑逐位一致）。全部离线合成，
零网络零真机。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

smt = pytest.importorskip("smt", reason="SMT 为可选依赖（extra: smt）")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfauto.service.output_sm_service import (
    OutputSpaceMapper,
    find_exact_low_row,
)

FREQS = np.array([2.4, 2.5, 2.6])
W_TRAIN = [0.5, 0.745, 1.113, 1.4833, 2.0]
W_HELD = [0.9946, 1.5119]
# affine 真值系数（δ = a + b·u，逐头）
AFF = {"gamma_lin": (0.01, 0.3), "s21_db": (0.02, -0.1), "eps_eff": (0.05, 0.02)}


def _base_heads(w: float) -> tuple[np.ndarray, np.ndarray, float]:
    """合成低保真三头基面（确定性、u 逐频可分）。"""
    g = 0.05 + 0.03 * np.arange(len(FREQS)) + 0.04 * np.sin(2.0 * w)
    s21 = -(0.2 + 0.05 * np.arange(len(FREQS)) + 0.1 * (w - 0.5))
    eps = 2.5 + 0.4 * (w - 0.5)
    return g, s21, float(eps)


def _high_delta(head: str, u: np.ndarray | float) -> np.ndarray | float:
    a, b = AFF[head]
    if isinstance(u, np.ndarray):
        return a + b * u
    return a + b * float(u)


def _mk_low_row(w: float) -> dict:
    g, s21, eps = _base_heads(w)
    return {"w": float(w), "s11_db": 20.0 * np.log10(g), "s21_db": s21,
            "eps_eff": eps, "run_id": f"lo_w{w:.4f}", "point_id": None,
            "group": None}


def _mk_high_row(w: float, *, sine_resid: float = 0.0) -> dict:
    """高保真行：δ = affine(u)（+ 可选 u 的正弦非 affine 残差）。"""
    g, s21, eps = _base_heads(w)
    d11 = _high_delta("gamma_lin", g)
    if sine_resid:
        d11 = d11 + sine_resid * np.sin(3.0 * g)
    g_hi = np.clip(g + d11, 0.0, 0.95)
    d21 = _high_delta("s21_db", s21)
    if sine_resid:
        d21 = d21 + sine_resid * np.sin(3.0 * s21)
    d_eps = _high_delta("eps_eff", eps)
    if sine_resid:
        d_eps = float(d_eps) + sine_resid * np.sin(3.0 * eps)
    return {"w": float(w), "s11_db": 20.0 * np.log10(g_hi),
            "s21_db": s21 + d21, "eps_eff": eps + float(d_eps),
            "run_id": f"hi_w{w:.4f}", "point_id": f"syn_w{w:.4f}",
            "group": "train" if w in W_TRAIN else "heldout"}


def _world() -> tuple[list[dict], list[dict], list[dict]]:
    low = [_mk_low_row(w) for w in sorted(W_TRAIN + W_HELD)]
    train = [_mk_high_row(w) for w in W_TRAIN]
    held = [_mk_high_row(w) for w in W_HELD]
    return low, train, held


# ---------------------------------------------------------------- 钉 a


def test_affine_recovery_held_within_1e_6():
    """合成回收钉 a：affine 真值 → held 点修正回收 ≤1e-6（零残差守卫路径）。"""
    low, train, held = _world()
    mapper = OutputSpaceMapper()
    summary = mapper.fit(train, low, FREQS)
    # 零残差守卫：affine 真值下 GP 全部跳过（如实计数）
    assert sum(summary["n_gp_fitted"].values()) == 0
    assert sum(summary["n_affine_only"].values()) == 2 * len(FREQS) + 1
    res = mapper.evaluate(low, held, FREQS)
    assert res["n_fit_failures"] == 0
    assert res["gamma_lin"]["max"] <= 1e-6
    assert res["s21_db"]["max"] <= 1e-6
    assert res["eps_eff_rel"]["max"] <= 1e-6
    assert res["n_trust_region_fallbacks"] == 0


def test_nonaffine_interpolation_at_train_anchors_within_1e_7():
    """非 affine 残差语料：GP 激活，train 锚插值语义 ≤1e-7（钉 a 第二支）。"""
    low = [_mk_low_row(w) for w in sorted(W_TRAIN + W_HELD)]
    train = [_mk_high_row(w, sine_resid=0.05) for w in W_TRAIN]
    mapper = OutputSpaceMapper()
    summary = mapper.fit(train, low, FREQS)
    assert sum(summary["n_gp_fitted"].values()) > 0
    res = mapper.evaluate(low, train, FREQS)
    assert res["gamma_lin"]["max"] <= 1e-7
    assert res["s21_db"]["max"] <= 1e-7
    assert res["eps_eff_rel"]["max"] <= 1e-7


# ---------------------------------------------------------------- 钉 c


def test_trust_region_fallback_and_warning():
    """信任域钉 c：超 τ 修正回退原始 OE + warnings 非空 + 计数 ≥1。"""
    low, train, _held = _world()
    mapper = OutputSpaceMapper(tau_pct=1.0)  # 注入超 τ：1% 域必裁剪真修正
    mapper.fit(train, low, FREQS)
    row = find_exact_low_row(low, W_HELD[0])
    pred = mapper.predict_row(row, FREQS)
    total = sum(pred["trust_region_fallbacks"].values())
    assert total >= 1
    assert len(pred["warnings"]) == total
    # 回退条目 = 原始 OE 值（δ=0）：整行全部回退时三头逐位回到 OE
    g_raw, _s21_raw, eps_raw = _base_heads(W_HELD[0])
    if pred["trust_region_fallbacks"]["gamma_lin"] == len(FREQS):
        assert np.allclose(10.0 ** (pred["s11_db"] / 20.0), g_raw, atol=1e-12)
    if pred["trust_region_fallbacks"]["eps_eff"] == 1:
        assert abs(pred["eps_eff"] - eps_raw) <= 1e-12
    # τ=100% 预声明缺省下同语料零回退（trust 域不误伤）
    default_mapper = OutputSpaceMapper()
    default_mapper.fit(train, low, FREQS)
    pred_default = default_mapper.predict_row(row, FREQS)
    assert sum(pred_default["trust_region_fallbacks"].values()) == 0


def test_nonfinite_delta_falls_back_not_propagates():
    """非有限 δ → 回退 + 告警，不传播 NaN（#314 多报不放过）。"""
    low, train, _held = _world()
    mapper = OutputSpaceMapper()
    mapper.fit(train, low, FREQS)
    mapper.branches[("gamma_lin", 0)].gp = None
    # 直接污染 affine 系数制造 NaN 预测（结构化注入，不经随机）
    mapper.branches[("gamma_lin", 0)].a = float("nan")
    row = find_exact_low_row(low, W_HELD[0])
    pred = mapper.predict_row(row, FREQS)
    assert pred["trust_region_fallbacks"]["gamma_lin"] >= 1
    assert np.all(np.isfinite(pred["s11_db"]))
    assert any("gamma_lin[0]" in wmsg for wmsg in pred["warnings"])


# ---------------------------------------------------------------- 钉 d


def test_deterministic_double_run_bit_identical():
    """确定性钉 d：两次全新拟合链预测逐位一致（无随机源等价落实）。"""
    low, train, _held = _world()
    nonaffine = [_mk_high_row(w, sine_resid=0.05) for w in W_TRAIN]
    for world_train in (train, nonaffine):
        m1 = OutputSpaceMapper()
        m1.fit(world_train, low, FREQS)
        m2 = OutputSpaceMapper()
        m2.fit(world_train, low, FREQS)
        for row in low:
            p1 = m1.predict_row(row, FREQS)
            p2 = m2.predict_row(row, FREQS)
            assert np.array_equal(p1["s11_db"], p2["s11_db"])
            assert np.array_equal(p1["s21_db"], p2["s21_db"])
            assert p1["eps_eff"] == p2["eps_eff"]
            assert p1["trust_region_fallbacks"] == p2["trust_region_fallbacks"]


# ---------------------------------------------------------------- 契约


def test_evaluate_stats_semantics_hand_computed():
    """evaluate 统计语义与 arm_stats 同构：手工小例逐值核对。"""
    freqs = np.array([2.5])
    lo = {"w": 1.0, "s11_db": np.array([20.0 * np.log10(0.12)]),
          "s21_db": np.array([-0.4]), "eps_eff": 2.9, "run_id": "lo",
          "point_id": None, "group": None}
    truth = {"w": 1.0, "s11_db": np.array([20.0 * np.log10(0.1)]),
             "s21_db": np.array([-0.3]), "eps_eff": 3.0, "run_id": "hi",
             "point_id": "t1", "group": "heldout"}
    # 恒等修正支：δ≡0（三锚 u 各异、δ 全 0 → affine a=0,b=0，残差守卫跳过 GP）
    def _lo_at(w: float) -> dict:
        return dict(lo, w=w, run_id=f"lo{w}")
    lo_rows = [_lo_at(w) for w in (0.5, 1.0, 2.0)]
    train = [_lo_at(0.5), _lo_at(2.0)]
    truth = dict(truth)  # 与 lo_rows 独立（真值头不同）
    mapper = OutputSpaceMapper()
    mapper.fit(train, lo_rows, freqs)
    res = mapper.evaluate(lo_rows, [truth], freqs)
    assert abs(res["gamma_lin"]["max"] - 0.02) <= 1e-12
    assert abs(res["s21_db"]["max"] - 0.1) <= 1e-12
    assert abs(res["eps_eff_rel"]["max"] - (1.0 / 30.0)) <= 1e-12
    assert res["n_fit_failures"] == 0


def test_missing_exact_low_row_rejected_and_counted():
    """锚 w 无精确 OE 行：fit 拒绝（ValueError）；evaluate 计入失败不硬造。"""
    low = [_mk_low_row(w) for w in sorted(W_TRAIN)]
    train = [_mk_high_row(w) for w in W_TRAIN]
    mapper = OutputSpaceMapper()
    with pytest.raises(ValueError, match="嵌套 DoE"):
        mapper.fit([*train, _mk_high_row(9.999)], low, FREQS)
    mapper2 = OutputSpaceMapper()
    mapper2.fit(train, low, FREQS)
    res = mapper2.evaluate(low, [_mk_high_row(W_HELD[0])], FREQS)
    assert res["n_fit_failures"] == 2 * len(FREQS) + 1
    assert res["per_point"][0]["gamma_lin_max"] is None


def test_leave_one_anchor_out_runs_and_deterministic():
    """LOO 面契约：逐折全新拟合，聚合=fold-max 的 max/mean，双跑一致。"""
    low = [_mk_low_row(w) for w in sorted(W_TRAIN + W_HELD)]
    anchors = [_mk_high_row(w, sine_resid=0.05)
               for w in sorted(W_TRAIN + W_HELD)]
    mapper = OutputSpaceMapper()
    loo1 = mapper.leave_one_anchor_out(anchors, low, FREQS)
    assert loo1["n_folds"] == len(anchors)
    assert all(f["n_fit_failures"] == 0 for f in loo1["folds"])
    loo2 = OutputSpaceMapper().leave_one_anchor_out(anchors, low, FREQS)
    assert np.array_equal(
        [f["gamma_lin_max"] for f in loo1["folds"]],
        [f["gamma_lin_max"] for f in loo2["folds"]])
    assert (loo1["aggregate_of_fold_max"]["gamma_lin"]["max"]
            == max(f["gamma_lin_max"] for f in loo1["folds"]))


def test_predict_before_fit_raises():
    mapper = OutputSpaceMapper()
    with pytest.raises(RuntimeError, match="未拟合"):
        mapper.predict_row(_mk_low_row(1.0), FREQS)
