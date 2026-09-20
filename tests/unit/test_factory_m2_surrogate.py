"""datafactory M2 判读管线单测（纯函数面：加载/划分/门计算/合成回收）。

#118 合成回收钉：解析已知真值注入同一条判读管线，GP 预测回收须在门内，
证明判读管线（划分/逐频头/门统计量）自身无偏。GP-LOO 慢路径由驱动脚本
（scripts/factory_m2_surrogate.py --judge）在真实判读前全跑并落 verdict。
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

import skrf as rf

from rfauto.optimization.surrogate import (  # noqa: F401  注册副作用
    poly_ridge,
    smt_kriging,
    surrogate_registry,
)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m2 = _load_script("factory_m2_surrogate")

SMALL_FREQS = m2.band_freqs(0.025)  # 9 点快路径（0.025GHz 步进）


# ------------------------------------------------------------- 纯函数面


def test_band_freqs_grid():
    f = m2.band_freqs(0.01)
    assert len(f) == 21
    assert f[0] == 2.4 and f[-1] == 2.6
    assert np.allclose(np.diff(f), 0.01)


def test_make_sample_head_keys_roundtrip():
    freqs = m2.band_freqs(0.01)
    row = {"w": 1.0,
           "s21_db": np.arange(len(freqs), dtype=float),
           "s11_db": -np.arange(len(freqs), dtype=float),
           "eps_eff": 2.9, "run_id": "x"}
    s = m2.make_sample(row["w"], row["s21_db"], row["s11_db"],
                       row["eps_eff"], freqs)
    assert set(s["metrics"]) == set(m2.head_keys(freqs))
    assert s["metrics"]["s21_db@2.40ghz"] == 0.0
    assert s["metrics"][m2.HEAD_EPS] == 2.9


def test_stratified_split_deterministic_and_counts():
    ws = np.linspace(0.5, 2.0, 120)
    tr, ho = m2.stratified_split(ws)
    assert len(ho) == 24 and len(tr) == 96
    assert set(ho.tolist()) & set(tr.tolist()) == set()
    tr2, ho2 = m2.stratified_split(ws)
    assert np.array_equal(tr, tr2) and np.array_equal(ho, ho2)
    # 分层：held-out 覆盖全域（min/max 跨度 ≥ 90% 域宽）
    span = ws[ho].max() - ws[ho].min()
    assert span >= 0.9 * (ws.max() - ws.min())
    # offset = SEED % 5 规则钉死
    order = np.argsort(ws, kind="stable")
    assert np.array_equal(ho, order[m2.SEED % 5::5])


def test_gate_metrics_hand_built():
    freqs = m2.band_freqs(0.05)  # 5 点，手工算得清
    t1 = {"w": 1.0, "s21_db": np.zeros(5), "s11_db": np.full(5, -10.0),
          "eps_eff": 3.0, "run_id": "a"}
    p1 = {f"s21_db@{f:.2f}ghz": 0.1 for f in freqs}
    p1.update({f"s11_db@{f:.2f}ghz": -10.4 for f in freqs})
    p1[m2.HEAD_EPS] = 3.03
    t2 = {"w": 2.0, "s21_db": np.zeros(5), "s11_db": np.full(5, -20.0),
          "eps_eff": 2.0, "run_id": "b"}
    p2 = {f"s21_db@{f:.2f}ghz": -0.2 for f in freqs}
    p2.update({f"s11_db@{f:.2f}ghz": -19.5 for f in freqs})
    p2[m2.HEAD_EPS] = 2.01
    g = m2.evaluate_gates([p1, p2], [t1, t2], freqs)
    assert g["s21_db"]["max"] == pytest.approx(0.2)
    assert g["s21_db"]["mean"] == pytest.approx(0.15)
    assert g["s11_db"]["max"] == pytest.approx(0.5)
    assert g["eps_eff_rel"]["max"] == pytest.approx(0.01)
    # 相对差各按自身真值归一：(0.03/3.0 + 0.01/2.0)/2 = 0.0075
    assert g["eps_eff_rel"]["mean"] == pytest.approx(0.0075)
    assert g["pass"] == {"s21_db": True, "s11_db": True,
                         "eps_eff_rel": True}
    assert g["n_fit_failures"] == 0
    # argmax 落点可追（#175：不赌个别点，但要能定位）
    assert g["argmax"]["s21_db"]["w_mm"] == 2.0
    assert g["argmax"]["s21_db"]["abs_diff"] == pytest.approx(0.2)


def test_gate_metrics_nan_counted_not_silently_dropped():
    freqs = m2.band_freqs(0.05)
    t = {"w": 1.0, "s21_db": np.zeros(5), "s11_db": np.full(5, -10.0),
         "eps_eff": 3.0, "run_id": "a"}
    p = {f"s21_db@{f:.2f}ghz": 0.1 for f in freqs}
    p.update({f"s11_db@{f:.2f}ghz": float("nan") for f in freqs})  # 头失败
    p[m2.HEAD_EPS] = 3.0
    g = m2.evaluate_gates([p], [t], freqs)
    assert g["n_fit_failures"] == 5  # 多报不放过（#314/#316）
    assert np.isnan(g["s11_db"]["max"])  # 该门无可用值
    assert g["pass"]["s11_db"] is False  # 不冒充 PASS


def test_read_touchstone_band_and_grid_guard(tmp_path):
    f_full = np.linspace(2.0, 3.0, 401)
    s = np.zeros((401, 2, 2), dtype=complex)
    s[:, 1, 0] = 0.9 * np.exp(-1j * 2 * np.pi * f_full * 0.1)
    s[:, 0, 0] = 0.1 * np.exp(1j * 0.3)
    s[:, 0, 1] = s[:, 1, 0]
    s[:, 1, 1] = s[:, 0, 0]
    nw = rf.Network(frequency=f_full * 1e9, s=s, z0=50.0)
    p = tmp_path / "params.s2p"
    nw.write_touchstone(str(p))
    freqs = m2.band_freqs(0.01)
    s21_db, s11_db = m2.read_touchstone_band(p, freqs)
    assert len(s21_db) == 21
    assert np.allclose(s21_db, 20 * np.log10(0.9), atol=1e-9)
    assert np.allclose(s11_db, 20 * np.log10(0.1), atol=1e-9)
    # 栅格未对齐必须报错而非静默插值（#121 同源；2.406 非 2.5MHz 步倍数）
    with pytest.raises(ValueError, match="命中"):
        m2.read_touchstone_band(p, np.array([2.406, 2.41]))


def test_synthetic_line_unitarity():
    # 无耗线能量守恒：|S11|²+|S21|²=1（合成真值自身的健全性）
    freqs = m2.band_freqs(0.01)
    s11, s21 = m2.line_s_complex(72.5, 2.9, freqs)
    assert np.allclose(np.abs(s11) ** 2 + np.abs(s21) ** 2, 1.0, atol=1e-12)
    rows = m2.synthetic_line_rows(8, freqs)
    assert [r["w"] for r in rows] == pytest.approx(
        list(np.linspace(0.5, 2.0, 8)))
    assert all(np.all(np.isfinite(r["s11_db"])) for r in rows)


# ------------------------------------------------- 合成回收钉（GP 回收）


def test_synthetic_recovery_gp_heldout_within_gates():
    # GP（快栅格 9 点）held-out 回收 ≤ 真实门阈值 → 管线无偏（#118）
    rows = m2.synthetic_line_rows(48, SMALL_FREQS)
    res = m2.heldout_eval(m2.gp_factory, rows, SMALL_FREQS)
    assert res["n_holdout"] == 10 and res["n_train"] == 38
    assert res["n_fit_failures"] == 0
    assert res["s21_db"]["max"] <= m2.GATE_THRESHOLDS["s21_db"]
    assert res["s11_db"]["max"] <= m2.GATE_THRESHOLDS["s11_db"]
    assert res["eps_eff_rel"]["max"] <= m2.GATE_THRESHOLDS["eps_eff_rel"]


def test_synthetic_recovery_poly_ridge_loo_within_gates():
    # poly_ridge 全链路 LOO（秒级）钉 LOO 循环/门计算逻辑的机械正确性：
    # 零折失败、有限预测、s21/sanity 界内。合成 S11(w) 带波纹，二阶多项式
    # 容量受限（LOO 实测 max≈1.9dB）——门内回收钉由 GP held-out 测试承载，
    # poly 是对照组，不按 M2 真实门断言。
    rows = m2.synthetic_line_rows(48, SMALL_FREQS)
    res = m2.loo_eval(m2.poly_ridge_factory, rows, SMALL_FREQS,
                      log=lambda _: None)
    assert res["n_folds"] == 48 and res["n_fold_failures"] == 0
    assert res["n_fit_failures"] == 0
    assert res["s21_db"]["max"] <= m2.GATE_THRESHOLDS["s21_db"]
    assert res["s11_db"]["max"] <= 2.5
    assert res["eps_eff_rel"]["max"] <= 0.02


def test_registry_kinds_present():
    assert "smt_kriging" in surrogate_registry.available()
    assert "poly_ridge" in surrogate_registry.available()
