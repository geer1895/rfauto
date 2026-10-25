"""数据工厂二期 B 批 cpw 2D 双口径复判驱动单测（纯函数面 + 合成回收 + 划分确定性）。

判据：内部证据档 §2（先写后算）。
#118 合成回收钉：cpw 闭式真值（Z0/εeff 逐点出自 _cpwg_ri，L=40mm 常量）注入
同一条判读管线，GP 回收须过主口径，证明判读管线（联合分层划分/双参逐频头/
门内核接线）自身无偏。GP-LOO 慢路径由驱动脚本（--judge）在真实判读前全跑并
落 verdict。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rfauto.optimization.surrogate import (  # noqa: F401  注册副作用
    poly_ridge,
    smt_kriging,
    surrogate_registry,
)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


g2j = _load_script("factory_g2_judge_2d")
m2j = g2j.m2j  # a2d 判读驱动（键名无关件复用源）
m2 = g2j.m2    # 门内核（经复用链取得）
lin = g2j.lin

SMALL_FREQS = m2.band_freqs(0.025)  # 9 点快路径（0.025GHz 步进）


# ------------------------------------------------------------- 契约/纯函数面


def test_kernel_reuse_and_threshold_contract():
    # 门内核薄复用（不重实现）：阈值与 a2d/1D 链同源；seed/bounds 为 cpw 域
    assert g2j.S21_DB_TOL == m2.GATE_THRESHOLDS["s21_db"] == 0.5
    assert g2j.EPS_TOL == m2.GATE_THRESHOLDS["eps_eff_rel"] == 0.01
    assert g2j.S11_DB_TOL == m2.GATE_THRESHOLDS["s11_db"] == 1.0
    assert g2j.lin.LINEAR_TOL == 0.04
    assert g2j.SEED == 20260922
    assert g2j.BOUNDS_2D == {"w_mm": (0.5, 1.6), "gap_mm": (0.15, 0.5)}
    assert g2j.LINE_LEN_MM == 40.0
    assert g2j.N_LOO_FOLDS == 30


def test_make_sample_2d_double_key_w_gap():
    freqs = m2.band_freqs(0.05)
    row = {"w": 0.8, "g": 0.3,
           "s21_db": np.zeros(5), "s11_db": np.full(5, -10.0),
           "eps_eff": 2.6, "run_id": "x"}
    s = g2j.make_sample_2d(row["w"], row["g"], row["s21_db"], row["s11_db"],
                           row["eps_eff"], freqs)
    assert s["params"] == {"w_mm": 0.8, "gap_mm": 0.3}
    assert set(s["metrics"]) == set(m2.head_keys(freqs))
    assert s["metrics"][m2.HEAD_EPS] == 2.6


def test_composite_key_known_values():
    assert g2j.composite_key(0.5, 0.15) == pytest.approx(0.0)
    assert g2j.composite_key(1.6, 0.5) == pytest.approx(2.0)
    # 反对角两角同键（tie-break 由 (w,g) 承担，不影响确定性）
    assert g2j.composite_key(0.5, 0.5) == pytest.approx(1.0)
    assert g2j.composite_key(1.6, 0.15) == pytest.approx(1.0)


def test_loo_fold_indices_reuse_with_cpw_seed():
    # 复用面（criteria §4）：loo_fold_indices 复用 a2d 判读链同一函数，
    # 但 seed 必须显式传本批 20260922（缺省会落到 a2d 的 20260921）
    import inspect

    assert "seed" in inspect.signature(g2j.m2j.loo_fold_indices).parameters
    a = g2j.m2j.loo_fold_indices(120, 30, seed=g2j.SEED)
    b = g2j.m2j.loo_fold_indices(120, 30, seed=g2j.SEED)
    assert np.array_equal(a, b)
    assert len(a) == 30 and len(set(a.tolist())) == 30
    assert all(0 <= int(i) < 120 for i in a)
    # n < folds 时如实收缩（min 语义）
    assert len(g2j.m2j.loo_fold_indices(10, 30, seed=g2j.SEED)) == 10
    # 与 a2d 缺省 seed 的折集不同（跨批协议隔离）
    assert not np.array_equal(a, g2j.m2j.loo_fold_indices(120, 30))


# ------------------------------------------------------------- 划分确定性


def test_split_2d_deterministic_counts_and_offset_rule():
    ws = np.linspace(0.5, 1.6, 120)
    gs = np.linspace(0.15, 0.5, 120)
    tr, ho = g2j.stratified_split_2d(ws, gs)
    assert len(ho) == 24 and len(tr) == 96  # held-out 20%=24/120
    assert set(ho.tolist()) & set(tr.tolist()) == set()
    tr2, ho2 = g2j.stratified_split_2d(ws, gs)
    assert np.array_equal(tr, tr2) and np.array_equal(ho, ho2)  # 无 RNG
    # 协议钉死：复合键排序后 [offset::5]
    keys = [g2j.composite_key(w, gap)
            for w, gap in zip(ws, gs, strict=True)]
    order = np.array(sorted(range(120),
                            key=lambda i: (keys[i], float(ws[i]), float(gs[i]))),
                     dtype=int)
    assert np.array_equal(ho, order[g2j.SEED % 5::5])


def test_split_2d_joint_coverage_on_lhs_plan():
    # 用真实 cpw 采样计划做划分：held-out 须覆盖 w 与 gap 两轴全域
    # （单轴分层泄漏另一轴——criteria §1 联合分层动机）
    g2c = _load_script("factory_g2_collect")
    plan = g2c.build_g2_plan()
    ws = np.array([p["w_mm"] for p in plan["points"]])
    gs = np.array([p["gap_mm"] for p in plan["points"]])
    _tr, ho = g2j.stratified_split_2d(ws, gs)
    assert len(ho) == 24
    w_span = ws[ho].max() - ws[ho].min()
    g_span = gs[ho].max() - gs[ho].min()
    assert w_span >= 0.9 * (ws.max() - ws.min())
    assert g_span >= 0.9 * (gs.max() - gs.min())


# --------------------------------------------------- 合成回收钉（#118，cpw）


def test_synthetic_cpw_corpus_structure_and_closed_form_truth():
    from rfauto.core.calculators import _cpwg_ri

    rows = g2j.synthetic_cpw_rows(SMALL_FREQS)
    assert len(rows) == 48  # 8 w × 6 gap
    assert all({"w", "g", "s21_db", "s11_db", "eps_eff"} <= set(r) for r in rows)
    for r in rows:
        eps_cf, z0_cf = _cpwg_ri(r["w"], r["g"], 0.508, 3.66)
        assert r["eps_eff"] == pytest.approx(eps_cf, rel=1e-12)
        s11, s21 = g2j.m2j.line_s_complex_2d(z0_cf, eps_cf, SMALL_FREQS,
                                             g2j.LINE_LEN_MM)
        # 无耗线能量守恒：|S11|²+|S21|²=1（合成真值自身的健全性）
        assert np.allclose(np.abs(s11) ** 2 + np.abs(s21) ** 2, 1.0, atol=1e-12)
        assert np.allclose(r["s11_db"], 20 * np.log10(np.abs(s11)), atol=1e-9)
    # gap 轴逐点参数化：同 w 不同 gap 的 εeff 单调（共形映射物理）且 Z0 随
    # gap 增大而增大（50Ω 名义附近两侧同向）
    g_lo = next(r for r in rows if r["w"] == 0.5 and r["g"] == 0.15)
    g_hi = next(r for r in rows if r["w"] == 0.5 and r["g"] == 0.5)
    assert g_hi["eps_eff"] > g_lo["eps_eff"]
    # 50Ω 脊穿过域内（criteria §0）：网格最匹配点的带内 |S11| 峰深谷（−25dB 级）
    best_matched = min(r["s11_db"].max() for r in rows)
    assert best_matched < -25.0


def test_synthetic_recovery_gp_heldout_2d_within_gates():
    # GP（快栅格 9 点）双链回收 ≤ 主口径门 → 管线无偏（#118）。
    # cpw 真值含 50Ω 脊（|Γ|→0）与带缘 θ=π 零点：S11-dB 在零点 dB 放大
    # （#371 机制内生）如实 FAIL 只列账；主口径三项（S21/εeff/|ΔΓ|）回收过门。
    rows = g2j.synthetic_cpw_rows(SMALL_FREQS)
    lin_rows = g2j.m2j.to_linear_rows_2d(rows)
    res = g2j.heldout_eval_2d(g2j.gp_factory_2d, rows, lin_rows, SMALL_FREQS)
    assert res["db"]["n_holdout"] == 10 and res["db"]["n_train"] == 38
    assert res["db"]["n_fit_failures"] == 0
    assert res["linear"]["n_fit_failures"] == 0
    db, linear = res["db"], res["linear"]
    assert db["pass"]["s21_db"] is True
    assert db["pass"]["eps_eff_rel"] is True
    assert db["eps_eff_rel"]["max"] < 1e-4  # εeff 头闭式面近恒等回收（比 1% 门
    #   低 2 个量级；真值非线性强于 a2d 线性语料，1e-6 钉不适用——测试标定非门）
    assert db["s21_db"]["max"] < 0.05  # 平滑面 S21 回收远优于 0.5dB 门
    g = linear["s11_gamma_linear"]
    assert g["pass"] is True
    assert g["max"] <= lin.LINEAR_TOL  # 线性域主门（消费口径）
    # 带缘深谷/50Ω 脊上 dB 门如实 FAIL（列账语义，不阻断主口径）——#371 端到端
    assert db["pass"]["s11_db"] is False
    g4 = g2j.m2j.overall_g4(db, linear)
    assert g4["pass"] is True and g4["overall"] == "PASS"
    assert g4["s11_db_listed_only"]["pass"] is False
    # 三元定位可用（argmax 三元 (w,gap,freq) 列账，字段名与 cpw 参数面对应）
    tri = db["argmax_triple"]["s11_db"]
    assert tri is not None
    assert {"w_mm", "gap_mm", "freq_ghz"} <= set(tri)
    assert 0.5 <= tri["w_mm"] <= 1.6 and 0.15 <= tri["gap_mm"] <= 0.5


@pytest.mark.slow  # 终门 DURATIONS top-20 慢件（28.6s，GP 确定性双跑逐位对账）
def test_determinism_double_run_bit_identical():
    # G4-回归锚：同数据集同划分判读链双跑逐位一致（bit-identical）
    rows = g2j.synthetic_cpw_rows(SMALL_FREQS)
    lin_rows = g2j.m2j.to_linear_rows_2d(rows)
    ws = np.array([r["w"] for r in rows])
    gs = np.array([r["g"] for r in rows])
    split = g2j.stratified_split_2d(ws, gs)
    h1 = g2j.heldout_eval_2d(g2j.gp_factory_2d, rows, lin_rows, SMALL_FREQS,
                             split)
    h2 = g2j.heldout_eval_2d(g2j.gp_factory_2d, rows, lin_rows, SMALL_FREQS,
                             split)
    det = g2j.m2j.determinism_check(h1, h2)
    assert det["bit_identical"] is True
    assert det["compared"] == ["heldout_db", "heldout_linear"]


# ------------------------------------------------------------- 门判定语义


def _hand_rows_and_preds(s11_db_true: float, s11_db_pred: float,
                         eps_true: float = 2.6, eps_pred: float = 2.6,
                         n_f: int = 5):
    freqs = m2.band_freqs(0.05)
    targets = [{"w": 0.8, "g": 0.2, "s21_db": np.zeros(n_f),
                "s11_db": np.full(n_f, s11_db_true), "eps_eff": eps_true,
                "run_id": "a"}]
    preds = [{f"s21_db@{f:.2f}ghz": 0.0 for f in freqs}]
    preds[0].update({f"s11_db@{f:.2f}ghz": s11_db_pred for f in freqs})
    preds[0][m2.HEAD_EPS] = eps_pred
    return freqs, targets, preds


def test_overall_g4_s11_db_listed_only_not_gating():
    # S11-dB 差 3dB（超 1dB 门槛）但主口径三项（S21/εeff/|ΔΓ|）全过 →
    # overall 仍 PASS，S11-dB 只列账（G4-并列 #371）
    freqs, targets, preds = _hand_rows_and_preds(-10.0, -13.0)
    db = g2j.evaluate_db_face(preds, targets, freqs)
    assert db["pass"]["s11_db"] is False
    lin_rows = g2j.m2j.to_linear_rows_2d(targets)
    preds_lin = [{f"s11_db@{f:.2f}ghz": 10 ** (v / 20.0)
                  for f, v in zip(freqs, [-10.0] * len(freqs), strict=True)}]
    preds_lin[0].update({f"s21_db@{f:.2f}ghz": 0.0 for f in freqs})
    preds_lin[0][m2.HEAD_EPS] = 2.6
    linear = g2j.evaluate_linear_face(preds_lin, lin_rows, freqs)
    g4 = g2j.m2j.overall_g4(db, linear)
    assert g4["s21_db_pass"] is True
    assert g4["eps_eff_pass"] is True
    assert g4["s11_gamma_linear_pass"] is True
    assert g4["s11_db_listed_only"]["pass"] is False
    assert g4["pass"] is True and g4["overall"] == "PASS"


def test_overall_g4_fails_when_main_criteria_violated():
    # |ΔΓ| 线性域超 0.04 → 主口径 FAIL（S11-dB 列账不影响判定方向）
    freqs, targets, preds = _hand_rows_and_preds(-20.0, -20.05)
    db = g2j.evaluate_db_face(preds, targets, freqs)
    lin_rows = g2j.m2j.to_linear_rows_2d(targets)
    preds_lin = [{f"s11_db@{f:.2f}ghz": 10 ** (-20.0 / 20.0) + 0.05
                  for f in freqs}]
    preds_lin[0].update({f"s21_db@{f:.2f}ghz": 0.0 for f in freqs})
    preds_lin[0][m2.HEAD_EPS] = 2.6
    linear = g2j.evaluate_linear_face(preds_lin, lin_rows, freqs)
    assert linear["s11_gamma_linear"]["max"] == pytest.approx(0.05)
    assert linear["s11_gamma_linear"]["pass"] is False
    g4 = g2j.m2j.overall_g4(db, linear)
    assert g4["pass"] is False and g4["overall"] == "FAIL"


def test_overall_g4_failure_blocker():
    # 头拟合失败率 >5% 阻断（多报不放过 #314/#316，不冒充 PASS）
    db = {"pass": {"s21_db": True, "s11_db": True, "eps_eff_rel": True},
          "fit_failure_rate": 0.5, "n_fit_failures": 5}
    linear = {"s11_gamma_linear": {"pass": True, "max": 0.0},
              "fit_failure_rate": 0.0, "n_fit_failures": 0}
    g4 = g2j.m2j.overall_g4(db, linear)
    assert g4["failure_blocker"] is True
    assert g4["pass"] is False and g4["overall"] == "FAIL"


def test_evaluate_faces_argmax_triple_and_nan_mask():
    # 三元定位 + GP 头失败掩码语义（内核经 cpw 2D 包装不丢语义）
    freqs, targets, preds = _hand_rows_and_preds(-10.0, -10.4, eps_true=2.6,
                                                 eps_pred=2.626)
    db = g2j.evaluate_db_face(preds, targets, freqs)
    assert db["s11_db"]["max"] == pytest.approx(0.4)
    assert db["eps_eff_rel"]["max"] == pytest.approx(0.01)
    tri = db["argmax_triple"]["s11_db"]
    assert tri["w_mm"] == 0.8 and tri["gap_mm"] == 0.2
    assert tri["freq_ghz"] == pytest.approx(2.4)
    assert tri["abs_diff"] == pytest.approx(0.4)
    # NaN 头：计 failures、剔出统计量、不冒充 PASS
    preds_nan = [{f"s11_db@{f:.2f}ghz": float("nan") for f in freqs}]
    preds_nan[0].update({f"s21_db@{f:.2f}ghz": 0.0 for f in freqs})
    preds_nan[0][m2.HEAD_EPS] = 2.6
    db_nan = g2j.evaluate_db_face(preds_nan, targets, freqs)
    assert db_nan["n_fit_failures"] == len(freqs)
    assert db_nan["pass"]["s11_db"] is False
    assert db_nan["argmax_triple"]["s11_db"] is None  # 无可用值不硬定位
    # 线性链 NaN 同语义
    lin_rows = g2j.m2j.to_linear_rows_2d(targets)
    linear = g2j.evaluate_linear_face(preds_nan, lin_rows, freqs)
    assert linear["s11_gamma_linear"]["n_fit_failures"] == len(freqs)
    assert linear["s11_gamma_linear"]["pass"] is False


def test_build_comparison_lists_s11_db_without_gating():
    # 复用面（criteria §4）：build_comparison 直接复用 a2j 链同一函数
    freqs, targets, preds = _hand_rows_and_preds(-10.0, -13.0)
    db = g2j.evaluate_db_face(preds, targets, freqs)
    lin_rows = g2j.m2j.to_linear_rows_2d(targets)
    preds_lin = [{f"s11_db@{f:.2f}ghz": 10 ** (-10.0 / 20.0) for f in freqs}]
    preds_lin[0].update({f"s21_db@{f:.2f}ghz": 0.0 for f in freqs})
    preds_lin[0][m2.HEAD_EPS] = 2.6
    linear = g2j.evaluate_linear_face(preds_lin, lin_rows, freqs)
    comp = g2j.m2j.build_comparison(db, linear)
    assert "只列账" in comp["note"]
    held = comp["heldout"]
    assert held["s11_db_listed_only"]["pass_listed_only"] is False
    assert held["s11_gamma_linear_main"]["pass"] is True
    assert held["s11_gamma_linear_main"]["tol"] == 0.04
    assert held["s21_db"]["threshold_db"] == 0.5
    assert held["eps_eff_rel"]["threshold"] == 0.01


def test_registry_kinds_present_cpw_factories():
    assert "smt_kriging" in surrogate_registry.available()
    assert "poly_ridge" in surrogate_registry.available()
    # 2D 工厂可实例化且 bounds 双键（w+gap）进入模型
    model = g2j.gp_factory_2d()
    assert set(model.config["bounds"]) == {"w_mm", "gap_mm"}
    poly = g2j.poly_ridge_factory_2d()
    assert set(poly.config["bounds"]) == {"w_mm", "gap_mm"}
