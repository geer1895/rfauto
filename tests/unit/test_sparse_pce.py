"""S-5a 稀疏 PCE（Blatman-Sudret 自适应 LARS）定向测试（round3 §3.1 S-5a）。

裁判口径
-----------------------------
- Ishigami 解析 Sobol 在测试内**独立重推导**：路径 A = V13 = 8*b^2*pi^8/225
  （ANOVA 直分解 Var(x3^4)=pi^8/9-pi^8/25），路径 B = b^2*pi^8*(1/18-1/50)
  （被测模块 ishigami_sobol_analytic 的口径）——两路径先互证再裁判；
- 与既有 optimization/sensitivity.py 的 Saltelli 实现互证（真实调用，
  rel<=5% 带，采样数差异如实：Saltelli N=32768 基样本*5 次求值 vs 稀疏
  PCE N=256 点——采样数差异是两法成本结构本身，登记不豁免）；
- 稀疏恢复对照：OLS 全基（np.linalg.lstsq 最小范数解）vs LARS 稀疏在
  N<候选基数时的验证误差对照（任务书预声明断言）。

全部确定性、固定种子、无网络、无文件 IO（sklearn 为可选依赖，缺失整文件
如实 skip，先例 test_sk_gbdt）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

pytest.importorskip("sklearn", reason="sklearn 为可选依赖（extra: gbdt）")

from rfauto.core.pce import build_design_matrix, legendre_orthonormal
from rfauto.core.sparse_pce import (
    KUCHERENKO_STATUS,
    SparsePCEModel,
    fit_sparse_pce,
    hyperbolic_indices,
    ishigami,
    ishigami_sobol_analytic,
    sample_canonical,
    sparse_pce_sobol,
)
from rfauto.optimization.sensitivity import sobol_sensitivity

# ─── 预声明判据常量（任务书钉死：N=256、rel<=10%）────────────────────────────
ISHIGAMI_N = 256
ISHIGAMI_DEGREE_MAX = 8
ISHIGAMI_REL_BAND = 0.10
A_ISH, B_ISH = 7.0, 0.1
PI4 = math.pi**4
PI8 = math.pi**8


def _ishigami_specs() -> dict[str, dict[str, float]]:
    return {
        "x1": {"low": -math.pi, "high": math.pi},
        "x2": {"low": -math.pi, "high": math.pi},
        "x3": {"low": -math.pi, "high": math.pi},
    }


def _ishigami_obj(p):
    return ishigami([p["x1"], p["x2"], p["x3"]])


# ─── 1. 多指标集（超截断）────────────────────────────────────────────────────


def test_hyperbolic_indices_total_degree_count():
    # q=1 退化为总阶截断：card(A_{p,1}) = (d+p)!/(d!p!)，独立按公式重算
    for d, p in [(1, 4), (2, 3), (3, 6), (4, 4), (3, 2)]:
        expect = math.factorial(d + p) // (math.factorial(d) * math.factorial(p))
        idx = hyperbolic_indices(d, p, q=1.0)
        assert idx.shape == (expect, d), (d, p, idx.shape)


def test_hyperbolic_indices_layout_and_zero_row():
    idx = hyperbolic_indices(3, 4, q=1.0)
    assert np.all(idx[0] == 0), "行 0 恒为全零（常数项）"
    assert int(idx.max()) <= 4
    # graded-lex：总阶非降序，组内字典序
    totals = idx.sum(axis=1)
    assert np.all(np.diff(totals) >= 0)
    for t0 in np.unique(totals):
        group = idx[totals == t0]
        orders = [tuple(row) for row in group]
        assert orders == sorted(orders)


def test_hyperbolic_indices_q_norm_membership():
    # q=0.5：手工独立枚举 A_{3,0.5}（||a||_0.5 = (sum a_i^0.5)^2 <= 3）
    expect_in = {
        (0, 0, 0),
        (1, 0, 0), (0, 1, 0), (0, 0, 1),
        (2, 0, 0), (0, 2, 0), (0, 0, 2),
        (3, 0, 0), (0, 3, 0), (0, 0, 3),  # ||(3,0,0)||_0.5 = 3 恰等（边界含）
    }
    expect_out = {(1, 1, 0), (2, 1, 0), (1, 1, 1)}
    idx = hyperbolic_indices(3, 3, q=0.5)
    rows = {tuple(int(v) for v in row) for row in idx}
    assert expect_in <= rows
    assert rows.isdisjoint(expect_out)
    # q<1 集是 q=1 集的子集（同 p）
    assert rows <= {tuple(int(v) for v in row) for row in hyperbolic_indices(3, 3, q=1.0)}
    # 恰等边界：q^q 范数带 1e-12 容差，||(3,0,0)||_0.5 == 3 必须含
    assert (3, 0, 0) in rows


def test_hyperbolic_indices_validation():
    with pytest.raises(ValueError):
        hyperbolic_indices(0, 3)
    with pytest.raises(ValueError):
        hyperbolic_indices(2, -1)
    with pytest.raises(ValueError):
        hyperbolic_indices(2, 3, q=0.0)
    with pytest.raises(ValueError):
        hyperbolic_indices(2, 3, q=1.5)


# ─── 2. 试验点采样 ───────────────────────────────────────────────────────────


def test_sample_canonical_deterministic_and_ranges():
    kinds = ["legendre", "hermite"]
    a = sample_canonical(kinds, 512, seed=42)
    b = sample_canonical(kinds, 512, seed=42)
    c = sample_canonical(kinds, 512, seed=43)
    assert np.array_equal(a, b), "同 seed 必须逐位复现"
    assert not np.array_equal(a, c)
    assert np.all(a[:, 0] >= -1.0) and np.all(a[:, 0] <= 1.0)
    # hermite 列的样本矩（N=512，LHS+逆 CDF，宽带断言）
    assert abs(float(np.mean(a[:, 1]))) < 0.15
    assert 0.8 < float(np.std(a[:, 1])) < 1.2


def test_sample_canonical_sobol_sampler():
    a = sample_canonical(["legendre"], 64, seed=1, sampler="sobol")
    b = sample_canonical(["legendre"], 64, seed=1, sampler="sobol")
    assert np.array_equal(a, b)
    assert np.all(a >= -1.0) and np.all(a <= 1.0)
    with pytest.raises(ValueError):
        sample_canonical(["legendre"], 100, sampler="sobol")  # 非 2 的幂
    with pytest.raises(ValueError):
        sample_canonical(["legendre"], 32, sampler="grid")  # 未知采样器


# ─── 3. 基复用与设计矩阵 ─────────────────────────────────────────────────────


def test_design_matrix_reuses_pce_bases():
    # 稀疏设计列必须与 core/pce 正交归一基求值逐位同源（复用契约）
    x = sample_canonical(["legendre", "legendre"], 512, seed=7)
    idx = hyperbolic_indices(2, 3, q=1.0)
    _, design = build_design_matrix(["legendre", "legendre"], x, 3, idx)
    col_10 = int(np.where(np.all(idx == np.array([1, 0]), axis=1))[0][0])
    col_21 = int(np.where(np.all(idx == np.array([2, 1]), axis=1))[0][0])
    expect_10 = legendre_orthonormal(1, x[:, 0])[1]
    expect_21 = legendre_orthonormal(2, x[:, 0])[2] * legendre_orthonormal(1, x[:, 1])[1]
    np.testing.assert_allclose(design[:, col_10], expect_10, rtol=0, atol=1e-14)
    np.testing.assert_allclose(design[:, col_21], expect_21, rtol=0, atol=1e-14)
    # 正交归一性的样本二阶矩（N=512 LHS，实测最大偏差 ~0.038，带 0.05）
    gram = design.T @ design / 512.0
    np.testing.assert_allclose(np.diag(gram), 1.0, atol=0.05)


# ─── 4. 稀疏恢复：精确支撑回收 ───────────────────────────────────────────────


def _two_var_model(p):
    return 2.0 * p["a"] - 1.0 * p["b"] + 0.3 * p["a"] * p["b"]


def test_fit_sparse_pce_recovers_exact_support():
    m = fit_sparse_pce(
        {"a": {"low": -1.0, "high": 1.0}, "b": {"low": -1.0, "high": 1.0}},
        _two_var_model,
        degree_max=4,
        n_samples=64,
        q2_target=0.999999,
    )
    # 真支撑 = {(1,0),(0,1),(1,1)}（含常数行恰 4 行），零伪项
    support = {tuple(int(v) for v in row) for row in m.indices}
    assert support == {(0, 0), (1, 0), (0, 1), (1, 1)}
    # Legendre 正交归一基解析系数：c_(1,0)=2/sqrt(3), c_(0,1)=-1/sqrt(3), c_(1,1)=0.3/3
    order = [tuple(int(v) for v in row) for row in m.indices]
    np.testing.assert_allclose(m.coeffs[order.index((0, 0))], 0.0, atol=1e-12)
    np.testing.assert_allclose(m.coeffs[order.index((1, 0))], 2.0 / math.sqrt(3.0), rtol=1e-9)
    np.testing.assert_allclose(m.coeffs[order.index((0, 1))], -1.0 / math.sqrt(3.0), rtol=1e-9)
    np.testing.assert_allclose(m.coeffs[order.index((1, 1))], 0.1, rtol=1e-9)
    assert m.q2 >= 0.999999
    assert m.stopped_by == "q2_target"
    assert len(m.history) == 1, "首阶即达标：升阶循环只走一轮"


def test_fit_sparse_pce_predict_roundtrip():
    m = fit_sparse_pce(
        {"a": {"low": -1.0, "high": 1.0}, "b": {"low": -1.0, "high": 1.0}},
        _two_var_model,
        degree_max=4,
        n_samples=64,
    )
    # 未见点精确回收（噪声自由合成例）
    assert m.predict({"a": 0.3, "b": -0.7}) == pytest.approx(
        _two_var_model({"a": 0.3, "b": -0.7}), abs=1e-10
    )
    assert m.predict([0.3, -0.7]) == pytest.approx(m.predict({"a": 0.3, "b": -0.7}), abs=0.0)
    with pytest.raises(ValueError):
        m.predict({"a": 0.3})  # 缺参
    with pytest.raises(ValueError):
        m.predict([1.0, 2.0, 3.0])  # 维数不符


# ─── 5. Sobol 闭式（子集枚举）───────────────────────────────────────────────


def test_sobol_components_closed_form():
    m = fit_sparse_pce(
        {"a": {"low": -1.0, "high": 1.0}, "b": {"low": -1.0, "high": 1.0}},
        _two_var_model,
        degree_max=3,
        n_samples=64,
        q2_target=0.999999,
    )
    # U(-1,1) 独立均匀：Var(2a)=4/3, Var(-b)=1/3, Var(0.3ab)=0.09/9=0.01
    comps = {tuple(sorted(k)): v for k, v in m.sobol_components().items()}
    np.testing.assert_allclose(comps[("a",)], 4.0 / 3.0, rtol=1e-8)
    np.testing.assert_allclose(comps[("b",)], 1.0 / 3.0, rtol=1e-8)
    np.testing.assert_allclose(comps[("a", "b")], 0.01, rtol=1e-8)
    var = m.variance
    np.testing.assert_allclose(var, 4.0 / 3.0 + 1.0 / 3.0 + 0.01, rtol=1e-8)
    s = m.sobol()
    np.testing.assert_allclose(s["a"]["S1"], (4.0 / 3.0) / var, rtol=1e-7)
    np.testing.assert_allclose(s["a"]["ST"], (4.0 / 3.0 + 0.01) / var, rtol=1e-7)
    np.testing.assert_allclose(s["b"]["S1"], (1.0 / 3.0) / var, rtol=1e-7)
    np.testing.assert_allclose(s["b"]["ST"], (1.0 / 3.0 + 0.01) / var, rtol=1e-7)


# ─── 6. Ishigami 判据（任务书预声明：N=256、rel<=10%、稀疏性）────────────────


def test_ishigami_analytic_dual_path():
    # 路径 A（测试内独立推导）vs 路径 B（被测模块口径）先互证
    v1 = (1.0 + B_ISH * PI4 / 5.0) ** 2 / 2.0
    v2 = A_ISH**2 / 8.0
    v13_a = 8.0 * B_ISH**2 * PI8 / 225.0  # Var(x3^4)=pi^8/9-pi^8/25=16pi^8/225
    v13_b = B_ISH**2 * PI8 * (1.0 / 18.0 - 1.0 / 50.0)
    np.testing.assert_allclose(v13_a, v13_b, rtol=1e-12)
    an = ishigami_sobol_analytic(A_ISH, B_ISH)
    total = v1 + v2 + v13_a
    np.testing.assert_allclose(an["V"], total, rtol=1e-12)
    np.testing.assert_allclose(an["S1"], v1 / total, rtol=1e-12)
    np.testing.assert_allclose(an["ST3"], v13_a / total, rtol=1e-12)
    # 文献四位数锚（Sobol' & Levitin 1999 经典值）
    assert an["S1"] == pytest.approx(0.3139, abs=5e-5)
    assert an["S2"] == pytest.approx(0.4424, abs=5e-5)
    assert an["ST1"] == pytest.approx(0.5576, abs=5e-5)
    assert an["ST3"] == pytest.approx(0.2437, abs=5e-5)


def test_ishigami_sparse_pce_sobol_within_predeclared_band():
    m = fit_sparse_pce(
        _ishigami_specs(),
        _ishigami_obj,
        degree_max=ISHIGAMI_DEGREE_MAX,
        n_samples=ISHIGAMI_N,
        seed=42,
    )
    an = ishigami_sobol_analytic()
    s = m.sobol()
    pairs = [("x1", "S1", 1), ("x2", "S1", 2), ("x3", "S1", 3),
             ("x1", "ST", 1), ("x2", "ST", 2), ("x3", "ST", 3)]
    for name, key, i in pairs:
        est, ref = s[name][key], an[f"S{i}" if key == "S1" else f"ST{i}"]
        if ref == 0.0:
            assert abs(est) <= 0.01, (name, key, est)
        else:
            assert abs(est - ref) / ref <= ISHIGAMI_REL_BAND, (name, key, est, ref)
    assert m.q2 >= 0.99


def test_ishigami_sparsity():
    m = fit_sparse_pce(
        _ishigami_specs(),
        _ishigami_obj,
        degree_max=ISHIGAMI_DEGREE_MAX,
        n_samples=ISHIGAMI_N,
        seed=42,
    )
    # 实测 12/165：非零项数远小于选中轮候选基数，且非退化
    assert m.n_terms >= 5
    assert m.n_terms <= 0.2 * m.n_basis_selected
    assert m.n_basis_selected > m.n_terms


def test_ishigami_vs_saltelli_crosscheck():
    # rel<=5% 带；采样数差异如实：Saltelli 32768*5 次求值 vs 稀疏 PCE 256 点
    m = fit_sparse_pce(
        _ishigami_specs(), _ishigami_obj, degree_max=ISHIGAMI_DEGREE_MAX,
        n_samples=ISHIGAMI_N, seed=42,
    )
    sp = sobol_sensitivity(_ishigami_specs(), _ishigami_obj, n_samples=32768, seed=42)
    pce = m.sobol()
    for name in ("x1", "x2", "x3"):
        for key in ("S1", "ST"):
            a, b = pce[name][key], sp["sensitivity"][name][key]
            assert abs(a - b) <= 0.05 * max(abs(b), 1e-3), (name, key, a, b)


# ─── 7. 稀疏 vs OLS 对照与截断守卫 ───────────────────────────────────────────


def test_ols_collapses_while_lars_stable_when_N_below_basis():
    kinds = ["legendre"] * 4
    specs = {f"x{i}": {"low": -1.0, "high": 1.0} for i in range(4)}

    def obj(p):
        return 2.0 * p["x0"] - 1.5 * p["x1"] + 0.8 * p["x0"] * p["x1"] * p["x3"]

    # 手工 OLS 全基对照：同 seed 同试验点（与被测采样器同源）
    xc = sample_canonical(kinds, 30, seed=11)
    y = np.array([obj(dict(zip([f"x{i}" for i in range(4)], row, strict=True))) for row in xc])
    idx = hyperbolic_indices(4, 4, q=1.0)
    assert idx.shape[0] > 30, "前提：N=30 < 候选基数 70"
    _, design = build_design_matrix(kinds, xc, 4, idx)
    xv = sample_canonical(kinds, 400, seed=12)
    yv = np.array([obj(dict(zip([f"x{i}" for i in range(4)], row, strict=True))) for row in xv])
    _, design_v = build_design_matrix(kinds, xv, 4, idx)
    c_ols, *_ = np.linalg.lstsq(design, y, rcond=None)
    rmse_ols = float(np.sqrt(np.mean((design_v @ c_ols - yv) ** 2)))

    m = fit_sparse_pce(specs, obj, degree_max=4, n_samples=30, q2_target=0.9999, seed=11)
    rmse_lars = float(np.sqrt(np.mean((m.predict_canonical(xv) - yv) ** 2)))
    assert rmse_ols > 0.5, f"OLS 全基欠定应崩（实测 {rmse_ols}）"
    assert rmse_lars < 1e-8, f"LARS 稀疏应稳（实测 {rmse_lars}）"
    assert rmse_ols > 100.0 * rmse_lars
    support = {tuple(int(v) for v in row) for row in m.indices}
    assert support == {(0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (1, 1, 0, 1)}


def test_noise_terms_removed_by_cut():
    # y = 3*u0 + sigma=0.05 噪声：截断后激活集只剩常数+线性主效应
    n = 128
    x = sample_canonical(["legendre"] * 3, n, seed=3)
    noise = np.random.default_rng(99).normal(0.0, 0.05, n)
    lut = {tuple(np.round(row, 12)): v for row, v in zip(x, 3.0 * x[:, 0] + noise, strict=True)}

    def obj(p):
        return lut[tuple(np.round([p["u0"], p["u1"], p["u2"]], 12))]

    m = fit_sparse_pce(
        {f"u{i}": {"low": -1.0, "high": 1.0} for i in range(3)},
        obj, degree_max=3, n_samples=n, seed=3,
    )
    support = {tuple(int(v) for v in row) for row in m.indices}
    assert support == {(0, 0, 0), (1, 0, 0)}
    order = [tuple(int(v) for v in row) for row in m.indices]
    # 3/sqrt(3)=sqrt(3)：线性系数在 2% 带内回收（噪声量级 0.05/sqrt(3)~3%）
    assert m.coeffs[order.index((1, 0, 0))] == pytest.approx(math.sqrt(3.0), rel=0.02)
    assert m.coeffs[order.index((0, 0, 0))] == pytest.approx(0.0, abs=0.05)


def test_overfitting_guard_stops():
    # 噪声主导：q2 平/降三轮 → 守卫停机（最小化变体：不自动加密试验设计）
    n, dim = 24, 2
    x = sample_canonical(["legendre"] * dim, n, seed=5)
    noise = np.random.default_rng(1).normal(0.0, 1.0, n)
    lut = {tuple(np.round(row, 12)): v for row, v in zip(x, 0.5 * x[:, 0] + noise, strict=True)}

    def obj(p):
        return lut[tuple(np.round([p["v0"], p["v1"]], 12))]

    m = fit_sparse_pce(
        {f"v{i}": {"low": -1.0, "high": 1.0} for i in range(dim)},
        obj, degree_max=6, degree_start=1, n_samples=n, seed=5,
    )
    assert m.stopped_by == "overfitting_guard"
    assert len(m.history) == 3
    assert isinstance(m, SparsePCEModel)


# ─── 8. 边界与校验 ───────────────────────────────────────────────────────────


def test_validation_boundaries():
    specs2 = {"a": {"low": -1.0, "high": 1.0}, "b": {"low": -1.0, "high": 1.0}}
    with pytest.raises(ValueError):  # d<1
        fit_sparse_pce({}, _two_var_model)
    with pytest.raises(ValueError):  # p<1
        fit_sparse_pce(specs2, _two_var_model, degree_start=0)
    with pytest.raises(ValueError):  # p<1
        fit_sparse_pce(specs2, _two_var_model, degree_max=0)
    with pytest.raises(ValueError):  # degree_max < degree_start
        fit_sparse_pce(specs2, _two_var_model, degree_max=1, degree_start=2)
    with pytest.raises(ValueError):  # q 域
        fit_sparse_pce(specs2, _two_var_model, q=0.0)
    with pytest.raises(ValueError):
        fit_sparse_pce(specs2, _two_var_model, q=1.2)
    with pytest.raises(ValueError):  # cut_factor 域
        fit_sparse_pce(specs2, _two_var_model, cut_factor=-1.0)
    with pytest.raises(ValueError):  # N<最低可判读自由度（dim+2）
        fit_sparse_pce(specs2, _two_var_model, n_samples=3)
    with pytest.raises(ValueError):  # 常数目标
        fit_sparse_pce(specs2, lambda p: 1.0, n_samples=16)
    with pytest.raises(ValueError):  # LARS 路径无可行候选（N-2 < 最小激活模型列数）
        fit_sparse_pce(
            {"z": {"low": -1.0, "high": 1.0}},
            lambda p: p["z"],
            degree_start=1, degree_max=1, n_samples=3,
        )


def test_to_dict_json_safe():
    m = fit_sparse_pce(
        {"a": {"low": -1.0, "high": 1.0}, "b": {"low": -1.0, "high": 1.0}},
        _two_var_model, degree_max=3, n_samples=64,
    )
    d = m.to_dict()
    # 可 JSON 序列化（numpy 标量/数组不得外泄）
    json.dumps(d)
    assert d["ok"] is True
    assert d["method"] == "sparse_pce_blatman_sudret"
    assert d["q2"] is not None and d["modified_loo_error"] is not None
    assert isinstance(d["indices"], list) and isinstance(d["indices"][0], list)
    assert isinstance(d["coeffs"], list) and all(isinstance(v, float) for v in d["coeffs"])
    assert set(d["sensitivity"]) == {"a", "b"}
    assert isinstance(d["stopped_by"], str)


def test_kucherenko_registered_as_undecided():
    # round3 S-5 原文：Kucherenko 面=SALib 新依赖裁决项；未裁决前不得声称已实现
    assert KUCHERENKO_STATUS == "awaiting_dependency_decision"


def test_sparse_pce_sobol_envelope():
    out = sparse_pce_sobol(
        {"a": {"low": -1.0, "high": 1.0}, "b": {"low": -1.0, "high": 1.0}},
        _two_var_model, degree_max=3, n_samples=64,
    )
    assert out["ok"] is True
    assert out["method"] == "sparse_pce_blatman_sudret"
    assert set(out["sensitivity"]) == {"a", "b"}
    assert out["n_terms"] >= 3
    assert isinstance(out["model"], SparsePCEModel)
