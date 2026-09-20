"""datafactory M2 消费面线性域判据单测（纯函数面 + 合成回收 + 划分确定性）。

判据文件（先写后算）。#118 合成回收
钉：解析已知 |Γ| 函数注入同一条线性域管线，GP 回收 |ΔΓ| 须 ≤ 0.04，证明
判读管线（划分/线性头/门内核）自身无偏。GP-LOO 慢路径由驱动脚本
（scripts/factory_m2_linear_gate.py --judge）在真实判读前全跑并落 verdict。
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


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lg = _load_script("factory_m2_linear_gate")
m2 = lg.m2  # run1 模块（经 linear 模块复用链取得）

SMALL_FREQS = m2.band_freqs(0.025)  # 9 点快路径（0.025GHz 步进）


# ------------------------------------------------------- 纯函数面（内核）


def test_linear_gamma_gate_hand_built():
    pred = np.array([0.10, 0.20, 0.30])
    true = np.array([0.12, 0.19, 0.33])
    g = lg.linear_gamma_gate(pred, true, tol=0.04)
    assert g["max"] == pytest.approx(0.03)
    assert g["mean"] == pytest.approx(0.02)
    # p95 线性插值：sorted [0.01,0.02,0.03] → 0.02+0.9*0.01
    assert g["p95"] == pytest.approx(0.029)
    assert g["n"] == 3 and g["n_fit_failures"] == 0
    assert g["pass"] is True
    assert g["argmax"]["abs_diff"] == pytest.approx(0.03)
    assert g["argmax"]["flat_index"] == 2
    assert g["tol"] == 0.04


def test_linear_gamma_gate_boundary_and_fail():
    # 恰在 tol 上（≤ 含边界；用二进制精确值 0.125 避开浮点噪声）
    assert lg.linear_gamma_gate([0.25], [0.375], tol=0.125)["pass"] is True
    # tol 收窄 0.001 → FAIL（如实）
    g = lg.linear_gamma_gate([0.25], [0.375], tol=0.124)
    assert g["pass"] is False and g["max"] == pytest.approx(0.125)


def test_linear_gamma_gate_nan_pred_counted_not_silently_dropped():
    # 头拟合失败（NaN）→ 计 failures、剔出统计量、失败率超 5% 不冒充 PASS
    g = lg.linear_gamma_gate([0.10, float("nan"), 0.115],
                             [0.10, 0.12, 0.12], tol=0.04)
    assert g["n_fit_failures"] == 1
    assert g["n"] == 2
    assert g["max"] == pytest.approx(0.005)
    assert g["pass"] is False  # 失败率 1/3 > 5%
    assert g["fit_failure_rate"] == pytest.approx(1 / 3)
    # 全 NaN：无可用值 → FAIL（不凑绿）
    g2 = lg.linear_gamma_gate([float("nan"), float("nan")], [0.1, 0.1],
                              tol=0.04)
    assert g2["pass"] is False and np.isnan(g2["max"]) and g2["n"] == 0


def test_linear_gamma_gate_true_nan_raises_and_shape_guard():
    with pytest.raises(ValueError, match="真值非法"):
        lg.linear_gamma_gate([0.1], [float("nan")], tol=0.04)
    with pytest.raises(ValueError, match="形状不符"):
        lg.linear_gamma_gate([0.1, 0.2], [0.1], tol=0.04)


def test_linear_gamma_gate_no_gate_semantics():
    # tol=None = 并列量语义（pass=None，只报统计量）
    g = lg.linear_gamma_gate([0.5], [0.9], tol=None)
    assert g["pass"] is None and g["max"] == pytest.approx(0.4)


def test_to_linear_to_db_roundtrip_and_floor():
    xs = np.array([-60.0, -30.0, -6.0206, 0.0])
    assert np.allclose(lg.to_db(lg.to_linear(xs)), xs, atol=1e-9)
    assert lg.to_db(0.0) == pytest.approx(20 * np.log10(1e-12))


# -------------------------------------------------- 划分/复用链确定性


def test_split_reuse_matches_run1_rule():
    # 线性域判读复用 run1 stratified_split：规则钉死（offset=SEED%5=0）
    ws = np.linspace(0.5, 2.0, 120)
    tr, ho = m2.stratified_split(ws)
    assert len(ho) == 24 and len(tr) == 96
    order = np.argsort(ws, kind="stable")
    assert np.array_equal(ho, order[m2.SEED % 5::5])
    tr2, ho2 = m2.stratified_split(ws)
    assert np.array_equal(tr, tr2) and np.array_equal(ho, ho2)


def test_to_linear_rows_keeps_other_fields():
    rows = [{"w": 1.0, "s21_db": np.full(3, -6.0),
             "s11_db": np.full(3, -20.0), "eps_eff": 2.9, "run_id": "x"}]
    lin = lg.to_linear_rows(rows)
    assert lin[0] is not rows[0]  # 不改写原行
    assert rows[0]["s11_db"][0] == -20.0  # 原行零改写
    assert np.allclose(lin[0]["s11_db"], 0.1)
    assert np.allclose(lin[0]["s21_db"], -6.0)  # S21 头保持 dB（run1 同链）
    assert lin[0]["eps_eff"] == 2.9


# ---------------------------------------------- evaluate_linear_gates 接线


def test_evaluate_linear_gates_hand_built():
    freqs = m2.band_freqs(0.05)  # 5 点，手工算得清
    t1 = {"w": 1.0, "s21_db": np.zeros(5), "s11_db": np.full(5, 0.10),
          "eps_eff": 3.0, "run_id": "a"}
    t2 = {"w": 2.0, "s21_db": np.full(5, 20 * np.log10(0.5)),
          "s11_db": np.full(5, 0.02), "eps_eff": 2.0, "run_id": "b"}
    p1 = {f"s11_db@{f:.2f}ghz": v for f, v in
          zip(freqs, [0.12, 0.10, 0.10, 0.10, 0.10], strict=True)}
    p1.update({f"s21_db@{f:.2f}ghz": 0.1 for f in freqs})
    p1[m2.HEAD_EPS] = 3.03
    p2 = {f"s11_db@{f:.2f}ghz": 0.05 for f in freqs}
    p2.update({f"s21_db@{f:.2f}ghz": 20 * np.log10(0.5) for f in freqs})
    p2[m2.HEAD_EPS] = 2.01
    g = lg.evaluate_linear_gates([p1, p2], [t1, t2], freqs)
    # 线性域主门：diffs = [0.02]+[0]*4 + [0.03]*5 → max 0.03（PASS）
    assert g["s11_gamma_linear"]["max"] == pytest.approx(0.03)
    assert g["s11_gamma_linear"]["pass"] is True
    assert g["s11_gamma_linear"]["n"] == 10
    assert g["s11_gamma_linear"]["argmax"]["w_mm"] == 2.0
    assert g["s11_gamma_linear"]["argmax"]["freq_ghz"] == pytest.approx(2.4)
    # εeff 门：相对差各按自身真值归一 → max 1%（PASS）
    assert g["eps_eff_rel"]["max"] == pytest.approx(0.01)
    assert g["eps_eff_rel"]["pass"] is True
    # S21 线性并列量：0.1dB → |10^0.005-1|≈0.011579，不设门（pass None）
    assert g["s21_linear"]["max"] == pytest.approx(10 ** 0.005 - 1,
                                                   rel=1e-6)
    assert g["s21_linear"]["pass"] is None
    # S21 dB 复算（run1 方案门口径）：max 0.1dB（PASS）
    assert g["s21_db"]["max"] == pytest.approx(0.1)
    assert g["s21_db"]["pass"] is True
    # 线性头 dB 当量（不设门）：同一 0.03 线性误差，dB 差随真值深度放大——
    # p1（0.12 vs 0.10）≈1.58dB，p2（0.05 vs 0.02）=20log10(2.5)≈7.96dB 更大，
    # 正是深零点 dB 放大现象本身（#370②）
    assert g["s11_db_equivalent"]["max"] == pytest.approx(
        20 * np.log10(0.05) - 20 * np.log10(0.02), abs=1e-9)
    assert g["s11_db_equivalent"]["pass"] is None
    assert g["n_fit_failures"] == 0
    assert g["n_heads_total"] == 2 * (2 * 5 + 1)


def test_evaluate_linear_gates_nan_heads_counted():
    freqs = m2.band_freqs(0.05)
    t = {"w": 1.0, "s21_db": np.zeros(5), "s11_db": np.full(5, 0.10),
         "eps_eff": 3.0, "run_id": "a"}
    p = {f"s11_db@{f:.2f}ghz": float("nan") for f in freqs}  # S11 头全失败
    p.update({f"s21_db@{f:.2f}ghz": 0.0 for f in freqs})
    p[m2.HEAD_EPS] = 3.0
    g = lg.evaluate_linear_gates([p], [t], freqs)
    assert g["s11_gamma_linear"]["n_fit_failures"] == 5
    assert g["s11_gamma_linear"]["pass"] is False  # 多报不放过（#314/#316）
    assert g["n_fit_failures"] == 5 and g["n_heads_total"] == 11
    assert g["fit_failure_rate"] == pytest.approx(5 / 11)


# ------------------------------------------- 合成回收钉（#118，GP 回收）


def test_synthetic_recovery_gp_heldout_linear_within_gate():
    # 已知 |Γ| 解析函数（无耗线）线性幅值注入同一条管线 → 回收 ≤ 0.04
    rows = m2.synthetic_line_rows(48, SMALL_FREQS)
    lin_rows = lg.to_linear_rows(rows)
    res = lg.heldout_eval_linear(m2.gp_factory, lin_rows, SMALL_FREQS)
    assert res["n_holdout"] == 10 and res["n_train"] == 38
    assert res["n_fit_failures"] == 0
    g = res["s11_gamma_linear"]
    assert g["pass"] is True
    assert g["max"] <= lg.LINEAR_TOL
    assert g["max"] < 1e-4  # 平滑解析函数 GP 回收应远优于门（实测 ~1e-7 量级）
    assert res["eps_eff_rel"]["pass"] is True
    assert res["eps_eff_rel"]["max"] <= lg.EPS_TOL
