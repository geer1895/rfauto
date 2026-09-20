"""D8 稀疏 PCE→Sobol 直读 + worst-case/设计中心化 定向测试。

裁判口径（#118）
-----------------------
- 解析 Sobol 值在测试内**独立给出**（教科书公式/闭式方差分解），不调用被测算子；
- 与既有 optimization/sensitivity.py 的 Saltelli 实现互证（真实调用，±10%）；
- PCE 拟合路径不 import sensitivity，禁止自证。

全部确定性、固定种子、无网络、无文件 I/O。
"""

from __future__ import annotations

import math
from typing import ClassVar

import numpy as np
import pytest

from rfauto.core.pce import (
    PCEModel,
    build_design_matrix,
    corner_worst_case,
    design_centering,
    fit_pce,
    hermite_orthonormal,
    legendre_orthonormal,
    multi_indices,
    omp_fit,
    orthonormal_1d,
    pce_sobol,
    tolerance_yield,
    worst_case,
)

SEED = 42
A_ISHIGAMI = 7.0
B_ISHIGAMI = 0.1


def _linear(p):
    return 3.0 * p["x"] + 0.1 * p["y"]


def _product(p):
    return p["x"] * p["y"]


def _sum_product(p):
    return p["x"] + p["y"] + p["x"] * p["y"]


def _ishigami(p):
    return (
        math.sin(p["x"])
        + A_ISHIGAMI * math.sin(p["y"]) ** 2
        + B_ISHIGAMI * p["z"] ** 4 * math.sin(p["x"])
    )


def _rel(got: float, want: float) -> float:
    return abs(got - want) / max(abs(want), 1e-12)


# ---------------------------------------------------------------------------
# 基函数
# ---------------------------------------------------------------------------


class TestBasis:
    def test_legendre_orthonormal_quadrature(self):
        # Gauss-Legendre：E[psi_m psi_n] = (1/2)∫ psi_m psi_n dx（权重和=2）
        nodes, weights = np.polynomial.legendre.leggauss(24)
        basis = legendre_orthonormal(6, nodes)
        gram = basis @ (weights[:, None] * basis.T) / 2.0
        assert np.allclose(gram, np.eye(7), atol=1e-12), np.max(np.abs(gram - np.eye(7)))

    def test_hermite_orthonormal_quadrature(self):
        # Gauss-Hermite（probabilists'）：权重含 e^{-x^2/2}，E = 积分/√(2π)
        nodes, weights = np.polynomial.hermite_e.hermegauss(40)
        basis = hermite_orthonormal(6, nodes)
        gram = basis @ (weights[:, None] * basis.T) / math.sqrt(2.0 * math.pi)
        assert np.allclose(gram, np.eye(7), atol=1e-12), np.max(np.abs(gram - np.eye(7)))

    def test_multi_indices_count_and_order(self):
        idx = multi_indices(3, 4)
        assert idx.shape == (math.comb(7, 4), 3)
        assert idx.shape[0] == 35
        assert np.all(idx[0] == 0)
        degrees = idx.sum(axis=1)
        assert np.all(np.diff(degrees) >= 0)  # graded：总阶非降
        assert set(int(d) for d in degrees) == set(range(5))

    def test_orthonormal_1d_unknown_kind(self):
        with pytest.raises(ValueError):
            orthonormal_1d("bogus", 2, np.array([0.0]))


# ---------------------------------------------------------------------------
# PCE-Sobol vs 解析
# ---------------------------------------------------------------------------


class TestPCESobolAnalytic:
    def test_linear_superposition_analytic(self):
        # f=3x+0.1y，x,y~U(-1,1)，Var(x)=1/3 -> S1_x = 9/(9.01)
        ranges = {"x": {"low": -1.0, "high": 1.0}, "y": {"low": -1.0, "high": 1.0}}
        result = pce_sobol(ranges, _linear, degree=1, n_samples=128, seed=SEED)
        s = result["sensitivity"]
        assert _rel(s["x"]["S1"], 9.0 / 9.01) <= 0.01, s
        assert _rel(s["y"]["S1"], 0.01 / 9.01) <= 0.05, s
        assert abs(s["x"]["ST"] - s["x"]["S1"]) < 1e-9  # 无交互 => ST = S1
        assert result["r2"] > 0.999999

    def test_product_interaction_analytic(self):
        # f=x*y on [0,1]^2：解析 S1=3/7, ST=4/7（真交互）
        ranges = {"x": {"low": 0.0, "high": 1.0}, "y": {"low": 0.0, "high": 1.0}}
        result = pce_sobol(ranges, _product, degree=2, n_samples=256, seed=SEED)
        s = result["sensitivity"]
        for name in ("x", "y"):
            assert _rel(s[name]["S1"], 3.0 / 7.0) <= 0.10, (name, s)
            assert _rel(s[name]["ST"], 4.0 / 7.0) <= 0.10, (name, s)
            assert s[name]["ST"] - s[name]["S1"] > 0.05  # 交互抬高总阶
        assert result["r2"] > 0.999999

    def test_ishigami_analytic(self):
        # Ishigami：x,y,z~U(-pi,pi)，闭式方差分解（Sobol 1993/2007 口径）
        a, b = A_ISHIGAMI, B_ISHIGAMI
        v = a * a / 8.0 + b * math.pi**4 / 5.0 + b * b * math.pi**8 / 18.0 + 0.5
        s1x = (0.5 + b * math.pi**4 / 5.0 + b * b * math.pi**8 / 50.0) / v
        s1y = (a * a / 8.0) / v
        s1z = 0.0
        sxz = b * b * math.pi**8 * (1.0 / 18.0 - 1.0 / 50.0) / v
        stx = s1x + sxz
        stz = sxz
        ranges = {
            "x": {"low": -math.pi, "high": math.pi},
            "y": {"low": -math.pi, "high": math.pi},
            "z": {"low": -math.pi, "high": math.pi},
        }
        result = pce_sobol(ranges, _ishigami, degree=10, n_samples=2000, seed=3, max_terms=30)
        s = result["sensitivity"]
        assert _rel(s["x"]["S1"], s1x) <= 0.10, s
        assert _rel(s["y"]["S1"], s1y) <= 0.10, s
        # S1_z 解析值恰为 0：用绝对近零判据（相对判据在分母 0 处无意义）
        assert abs(s["z"]["S1"] - s1z) <= 0.01, s
        assert _rel(s["x"]["ST"], stx) <= 0.10, s
        assert _rel(s["z"]["ST"], stz) <= 0.10, s
        assert result["r2"] > 0.99

    def test_normal_hermite_exact(self):
        # x~N(0,1)，x^2-1 = He_2 = sqrt(2)*psi_2 -> S1=ST=1
        specs = {"x": {"mean": 0.0, "std": 1.0}}
        result = pce_sobol(specs, lambda p: p["x"] ** 2 - 1.0, degree=2, n_samples=256, seed=SEED)
        s = result["sensitivity"]
        assert _rel(s["x"]["S1"], 1.0) <= 0.02, s
        assert _rel(s["x"]["ST"], 1.0) <= 0.02, s
        assert result["r2"] > 0.999

    def test_constant_function_zero_indices(self):
        ranges = {"x": {"low": 0.0, "high": 1.0}, "y": {"low": 0.0, "high": 1.0}}
        result = pce_sobol(ranges, lambda p: 5.0, degree=2, n_samples=64, seed=SEED)
        assert result["variance"] == 0.0
        for name in ("x", "y"):
            assert result["sensitivity"][name] == {"S1": 0.0, "ST": 0.0}


# ---------------------------------------------------------------------------
# PCE-Sobol vs 既有 Saltelli（独立裁判，真实调用）
# ---------------------------------------------------------------------------


class TestCrossValidation:
    def test_pce_sobol_vs_saltelli_product(self):
        from rfauto.optimization.sensitivity import sobol_sensitivity

        ranges = {"x": {"low": 0.0, "high": 1.0}, "y": {"low": 0.0, "high": 1.0}}
        saltelli = sobol_sensitivity(ranges, _product, n_samples=16384, seed=SEED)
        pce = pce_sobol(ranges, _product, degree=2, n_samples=256, seed=7)
        for name in ("x", "y"):
            for stat in ("S1", "ST"):
                ref = saltelli["sensitivity"][name][stat]
                got = pce["sensitivity"][name][stat]
                assert abs(ref - got) / max(abs(ref), abs(got), 1e-9) <= 0.10, (name, stat, ref, got)

    def test_pce_sobol_vs_saltelli_sum_product(self):
        from rfauto.optimization.sensitivity import sobol_sensitivity

        ranges = {"x": {"low": 0.0, "high": 1.0}, "y": {"low": 0.0, "high": 1.0}}
        saltelli = sobol_sensitivity(ranges, _sum_product, n_samples=16384, seed=SEED)
        pce = pce_sobol(ranges, _sum_product, degree=2, n_samples=256, seed=7)
        for name in ("x", "y"):
            for stat in ("S1", "ST"):
                ref = saltelli["sensitivity"][name][stat]
                got = pce["sensitivity"][name][stat]
                assert abs(ref - got) / max(abs(ref), abs(got), 1e-9) <= 0.10, (name, stat, ref, got)


class TestPatchToleranceCrossValidation:
    """§10.4 D8 验收：patch 公差问题 PCE-Sobol vs 既有 Saltelli 互证 ±10%。

    诚实说明（runs/ 无现成 patch 公差数据）
    --------------------------------------
    runs/ 下检索无公差/良率采样数据（无 *toleran* 文件），故用 core/symbolic_fit.py
    的 **Hammerstad 贴片基模闭式**（独立解析裁判）作公差模型：L/W/er/h 各取 ±2%
    均匀公差，考察谐振频率 f0 的参数敏感度。

    既有 Saltelli 一阶估计量的适用边界（0az/#234 已收口）
    ------------------------------------------------
    f0 均值 ~4.48GHz、公差带内标准差 ~0.5%，E[f] >> std(f)；未居中的
    一阶估计量（mean(y_A*(y_C-y_B))/V）会因两项大数相减而失效——实测未居中
    S1_l=0.0139（真值 ~0.81）。**sobol_sensitivity 现已内置常数居中**（Sobol
    指数对加性常数不变，居中是估计量数值条件化，不改变敏感度结构，见
    optimization/sensitivity.py #234），本测试的显式居中成为无害冗余
    （双重居中幂等），保留以显式声明裁判口径。
    """

    RANGES: ClassVar[dict[str, dict[str, float]]] = {
        "l_mm": {"low": 19.6, "high": 20.4},
        "w_mm": {"low": 24.5, "high": 25.5},
        "er": {"low": 2.16, "high": 2.24},
        "h_mm": {"low": 1.568, "high": 1.632},
    }
    F0_NOMINAL: ClassVar[float] = 4.483304627212334  # patch_resonance_hj_ghz(20.0, 25.0, 2.2, 1.6)

    @staticmethod
    def _objective(p):
        from rfauto.core.symbolic_fit import patch_resonance_hj_ghz

        return patch_resonance_hj_ghz(p["l_mm"], p["w_mm"], p["er"], p["h_mm"]) - TestPatchToleranceCrossValidation.F0_NOMINAL

    def test_patch_tolerance_pce_sobol_vs_saltelli(self):
        from rfauto.optimization.sensitivity import sobol_sensitivity

        saltelli = sobol_sensitivity(self.RANGES, self._objective, n_samples=16384, seed=SEED)
        pce = pce_sobol(self.RANGES, self._objective, degree=3, n_samples=1200, seed=7, max_terms=40)
        for name in self.RANGES:
            for stat in ("S1", "ST"):
                ref = saltelli["sensitivity"][name][stat]
                got = pce["sensitivity"][name][stat]
                # 显著指数（>=0.01）走 ±10% 相对判据；可忽略指数（w_mm ~8e-4）
                # 的相对判据无意义，改用绝对近零判据（诚实边界）
                if max(ref, got) >= 0.01:
                    assert abs(ref - got) / max(abs(ref), abs(got)) <= 0.10, (name, stat, ref, got)
                else:
                    assert max(abs(ref), abs(got)) < 0.01, (name, stat, ref, got)
        # l_mm 是主敏感参数、er 次之（物理预期），且代理精度足以支撑直读
        s = pce["sensitivity"]
        assert s["l_mm"]["S1"] > s["er"]["S1"] > s["h_mm"]["S1"] > s["w_mm"]["S1"]
        assert pce["r2"] > 0.999

    def test_saltelli_total_order_is_mean_invariant(self):
        # 数值边界佐证：Jansen 总阶估计量对加性常数不变，一阶需居中。
        from rfauto.optimization.sensitivity import sobol_sensitivity

        ranges = {n: {"low": -1.0, "high": 1.0} for n in ("a", "b", "c", "d")}

        def raw(p):
            return 100.0 + 10.0 * p["a"] + 3.0 * p["b"] + 2.0 * p["c"] + p["d"]

        def centered(p):
            return 10.0 * p["a"] + 3.0 * p["b"] + 2.0 * p["c"] + p["d"]

        raw_s = sobol_sensitivity(ranges, raw, n_samples=16384, seed=SEED)["sensitivity"]
        cen_s = sobol_sensitivity(ranges, centered, n_samples=16384, seed=SEED)["sensitivity"]
        weights = {"a": 100.0 / 114.0, "b": 9.0 / 114.0, "c": 4.0 / 114.0, "d": 1.0 / 114.0}
        for name, want in weights.items():
            assert raw_s[name]["ST"] == pytest.approx(cen_s[name]["ST"], abs=1e-9), name
            assert _rel(cen_s[name]["S1"], want) <= 0.10, (name, cen_s[name], want)


# ---------------------------------------------------------------------------
# worst-case
# ---------------------------------------------------------------------------


class TestWorstCase:
    def test_corner_worst_case_exact(self):
        specs = {"x": {"low": 0.0, "high": 1.0}, "y": {"low": 0.0, "high": 1.0}}
        f = lambda p: p["x"] + p["y"]  # noqa: E731
        hi = corner_worst_case(specs, f, maximize=True)
        lo = corner_worst_case(specs, f, maximize=False)
        assert hi["value"] == pytest.approx(2.0)
        assert hi["params"] == {"x": 1.0, "y": 1.0}
        assert lo["value"] == pytest.approx(0.0)
        assert lo["params"] == {"x": 0.0, "y": 0.0}
        assert hi["n_evaluations"] == 4

    def test_pce_worst_case_interior_maximum(self):
        specs = {"x": {"low": 0.0, "high": 1.0}, "y": {"low": 0.0, "high": 1.0}}
        f = lambda p: 1.0 - (p["x"] - 0.3) ** 2 - (p["y"] - 0.7) ** 2  # noqa: E731
        model = fit_pce(specs, f, degree=2, n_samples=128, seed=1, method="ls")
        res = worst_case(model, maximize=True)
        assert res["value"] == pytest.approx(1.0, abs=1e-6)
        assert res["params"]["x"] == pytest.approx(0.3, abs=1e-3)
        assert res["params"]["y"] == pytest.approx(0.7, abs=1e-3)

    def test_pce_worst_case_corner_and_interior_min(self):
        specs = {"x": {"low": 0.0, "high": 2.0}, "y": {"low": 0.0, "high": 2.0}}
        f = lambda p: (p["x"] - 1.0) ** 2 + (p["y"] - 1.0) ** 2  # noqa: E731
        model = fit_pce(specs, f, degree=2, n_samples=64, seed=1, method="ls")
        hi = worst_case(model, maximize=True)
        assert hi["value"] == pytest.approx(2.0, abs=1e-6)  # 角点极值
        assert abs(hi["params"]["x"] - 1.0) == pytest.approx(1.0, abs=1e-3)
        lo = worst_case(model, maximize=False)
        assert lo["value"] == pytest.approx(0.0, abs=1e-6)  # 内部极小
        assert lo["params"]["x"] == pytest.approx(1.0, abs=1e-3)


# ---------------------------------------------------------------------------
# 稀疏性
# ---------------------------------------------------------------------------


class TestSparsity:
    def test_sparse_omp_under_noise_selects_only_active_term(self):
        rng = np.random.default_rng(0)
        specs = {f"x{i}": {"low": -1.0, "high": 1.0} for i in range(5)}

        def noisy(p):
            return 2.0 * p["x1"] + 0.02 * rng.normal()

        model = fit_pce(specs, noisy, degree=4, n_samples=400, seed=11, max_terms=20, tol=0.6)
        non_constant = [t for t in model.active_terms() if any(t)]
        assert non_constant == [(0, 1, 0, 0, 0)]
        pos = [tuple(int(v) for v in row) for row in model.indices].index((0, 1, 0, 0, 0))
        # psi_1 = sqrt(3)*x -> 系数 = 2/sqrt(3)
        assert model.coeffs[pos] == pytest.approx(2.0 / math.sqrt(3.0), rel=0.05)
        assert model.r2 > 0.99

    def test_omp_fit_respects_max_terms(self):
        x = np.linspace(-1.0, 1.0, 64)
        _, design = build_design_matrix(["legendre"], x.reshape(-1, 1), 3)
        y = 1.0 + 2.0 * design[:, 1] + 0.5 * design[:, 2]
        fit = omp_fit(design, y, max_terms=1, tol=0.0)
        assert fit["n_terms"] == 1
        assert fit["selected"] == [1]
        assert fit["residual_norm"] > 0.0  # 截断留下残差

    def test_omp_fit_zero_terms_is_mean_only(self):
        x = np.linspace(-1.0, 1.0, 32)
        _, design = build_design_matrix(["legendre"], x.reshape(-1, 1), 2)
        y = np.full(32, 3.0)
        fit = omp_fit(design, y, max_terms=0, tol=0.0)
        assert fit["n_terms"] == 0
        assert fit["coeffs"][0] == pytest.approx(3.0)
        assert fit["residual_norm"] == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# 设计中心化
# ---------------------------------------------------------------------------


class TestDesignCentering:
    def test_design_centering_improves_yield(self):
        specs = {"x": {"low": 0.0, "high": 1.0}}
        cost = lambda p: (p["x"] - 0.8) ** 2  # noqa: E731
        result = design_centering(specs, cost, spec_max=0.04, tolerances={"x": 0.05}, n_levels=3)
        assert result["initial_yield"] == 0.0
        assert result["yield"] == 1.0
        assert result["center"]["x"] == pytest.approx(0.8, abs=0.05)
        assert result["yield"] >= result["initial_yield"]

    def test_tolerance_yield_grid_is_deterministic(self):
        cost = lambda p: (p["x"] - 0.5) ** 2  # noqa: E731
        r1 = tolerance_yield({"x": 0.5}, cost, tolerances={"x": 0.1}, spec_max=0.005, n_levels=3)
        r2 = tolerance_yield({"x": 0.5}, cost, tolerances={"x": 0.1}, spec_max=0.005, n_levels=3)
        assert r1 == r2
        assert r1["n_samples"] == 3
        assert r1["yield"] == pytest.approx(1.0 / 3.0)
        assert r1["worst_cost"] == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# 确定性与预测
# ---------------------------------------------------------------------------


class TestDeterminismAndPrediction:
    def test_two_fits_same_seed_identical(self):
        ranges = {"x": {"low": -2.0, "high": 2.0}, "y": {"low": -1.0, "high": 1.0}}
        m1 = fit_pce(ranges, _sum_product, degree=3, n_samples=200, seed=SEED)
        m2 = fit_pce(ranges, _sum_product, degree=3, n_samples=200, seed=SEED)
        assert np.array_equal(m1.coeffs, m2.coeffs)
        assert np.array_equal(m1.active, m2.active)
        assert m1.sobol() == m2.sobol()
        assert m1.active_terms() == m2.active_terms()

    def test_predict_matches_objective_on_holdout(self):
        ranges = {"x": {"low": -1.0, "high": 1.0}, "y": {"low": -1.0, "high": 1.0}}
        model = fit_pce(ranges, _linear, degree=1, n_samples=64, seed=SEED)
        points = [{"x": 0.3, "y": -0.7}, {"x": -0.9, "y": 0.2}, {"x": 0.0, "y": 0.0}]
        for p in points:
            assert model.predict(p) == pytest.approx(_linear(p), abs=1e-9)
        preds = model.predict_many(points)
        assert preds.shape == (3,)
        assert isinstance(model, PCEModel)
        assert model.dim == 2


# ---------------------------------------------------------------------------
# 非法输入
# ---------------------------------------------------------------------------


def _zero(_p):
    return 0.0


_INVALID_CALLS = [
    pytest.param(lambda: fit_pce({}, _zero), id="empty-specs"),
    pytest.param(lambda: fit_pce({"x": {"low": 1.0, "high": 0.0}}, _zero), id="low-ge-high"),
    pytest.param(lambda: fit_pce({"x": {"low": 0.0}}, _zero), id="missing-high"),
    pytest.param(lambda: fit_pce({"x": {"mean": 0.0, "std": 0.0}}, _zero), id="std-zero"),
    pytest.param(
        lambda: fit_pce({"x": {"low": 0.0, "high": 1.0, "mean": 0.0}}, _zero), id="mixed-keys"
    ),
    pytest.param(lambda: fit_pce({"x": None}, _zero), id="spec-not-mapping"),
    pytest.param(lambda: fit_pce({"x": {"low": 0.0, "high": 1.0}}, _zero, degree=-1), id="degree-neg"),
    pytest.param(
        lambda: fit_pce({"x": {"low": 0.0, "high": 1.0}}, _zero, method="bogus"), id="method-bogus"
    ),
    pytest.param(
        lambda: fit_pce({"x": {"low": 0.0, "high": 1.0}}, _zero, n_samples=0), id="samples-zero"
    ),
    pytest.param(
        lambda: fit_pce({"x": {"low": 0.0, "high": 1.0}}, _zero, max_terms=-1), id="max-terms-neg"
    ),
    pytest.param(lambda: orthonormal_1d("bogus", 2, np.array([0.0])), id="kind-bogus"),
    pytest.param(lambda: legendre_orthonormal(-1, np.array([0.0])), id="legendre-neg"),
    pytest.param(lambda: multi_indices(0, 2), id="dim-zero"),
    pytest.param(lambda: multi_indices(2, -1), id="degree-neg-mi"),
    pytest.param(
        lambda: build_design_matrix(["legendre"], np.zeros((3, 2)), 1), id="kinds-mismatch"
    ),
    pytest.param(
        lambda: corner_worst_case({"x": {"low": 0.0, "high": 1.0}}, _zero, sigma_scale=0.0),
        id="sigma-zero",
    ),
    pytest.param(
        lambda: tolerance_yield({"x": 0.5}, _zero, tolerances={"x": 0.1}, spec_max=1.0, n_levels=1),
        id="levels-one",
    ),
    pytest.param(
        lambda: design_centering(
            {"x": {"low": 0.0, "high": 1.0}}, _zero, spec_max=1.0, tolerances={"x": 0.1}, shrink=1.0
        ),
        id="shrink-one",
    ),
    pytest.param(lambda: worst_case("not-a-model"), id="worst-case-type"),
    pytest.param(
        lambda: worst_case(
            fit_pce({"x": {"low": 0.0, "high": 1.0}}, _zero, degree=1, n_samples=16, seed=1),
            max_iter=0,
        ),
        id="max-iter-zero",
    ),
    pytest.param(
        lambda: fit_pce({"x": {"low": 0.0, "high": 1.0}}, _zero, degree=1, n_samples=16, seed=1).predict(
            {"zzz": 1.0}
        ),
        id="predict-missing-param",
    ),
]


@pytest.mark.parametrize("call", _INVALID_CALLS)
def test_invalid_inputs_raise(call):
    with pytest.raises((ValueError, TypeError)):
        call()
