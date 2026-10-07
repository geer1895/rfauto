"""OP-9（round16 §六）：RDO 双目标（μ+λσ）+ 机会约束闭式 单元测试。

判据预声明（解析锚，#118 独立来源——标准正态分位数表 + 约束几何）：

1. 闭式数学：gaussian_quantile(0.95)≈1.6448536269514722（双精度锚）；
   chance_constraint_bound = μ + Φ⁻¹(1−α)·σ 逐位式；
2. SLSQP 一致性（KKT 解析）：min −x（盒 [0,1]）+ 机会约束
   μ_g=x−0.7、σ_g=0.05x、α=0.05 → 界 1.08224x−0.7 ≤ 0 → x*=0.7/1.08224
   ≈ 0.646814——解收敛该值 ±5e-3；
3. λ 权衡语义：同一 (μ,σ) 面 λ 增大 → 最优点向低方差侧移动
   （μ(x)=x, σ(x)=x(1−x) 在 [0,1]：λ=0 → x*=1；λ=2 → 内点）；
4. fail-closed：p 出 (0,1)、σ<0、λ<0、alpha 出 (0,1)、bounds 非法、
   x0 键集不配显式 ValueError。

铁律 7 对照：μ/σ 由调用方注入（本测试=解析函数），本模块只做组合
与判定数学。
"""

from __future__ import annotations

import pytest

from rfauto.optimization.rdo import (
    chance_constraint_bound,
    gaussian_quantile,
    robust_design_optimization,
    robust_objective,
)


class TestClosedForms:
    def test_gaussian_quantile_anchor(self):
        assert gaussian_quantile(0.95) == pytest.approx(1.6448536269514722)
        assert gaussian_quantile(0.5) == pytest.approx(0.0)
        assert gaussian_quantile(0.975) == pytest.approx(1.959963984540054)

    def test_quantile_rejects_degenerate_p(self):
        for bad in (0.0, 1.0, -0.5, 1.5, float("nan")):
            with pytest.raises(ValueError):
                gaussian_quantile(bad)

    def test_chance_bound_formula(self):
        z95 = gaussian_quantile(0.95)
        assert chance_constraint_bound(0.1, 0.2, 0.05) == \
            pytest.approx(0.1 + z95 * 0.2)
        # α>0.5 → 负 z → 界收紧方向反转（语义如式）
        assert chance_constraint_bound(0.0, 1.0, 0.9) < 0.0

    def test_chance_bound_validation(self):
        with pytest.raises(ValueError, match="std"):
            chance_constraint_bound(0.0, -0.1, 0.05)
        with pytest.raises(ValueError):
            chance_constraint_bound(float("inf"), 0.1, 0.05)

    def test_robust_objective(self):
        assert robust_objective(1.0, 2.0, 3.0) == pytest.approx(7.0)
        assert robust_objective(1.0, 0.0, 5.0) == pytest.approx(1.0)
        with pytest.raises(ValueError, match="λ"):
            robust_objective(1.0, 0.1, -1.0)


class TestSLSQPConsistency:
    def test_chance_constrained_optimum_matches_closed_form(self):
        x_star = 0.7 / (1.0 + gaussian_quantile(0.95) * 0.05)

        def mean(x):
            return -float(x[0])          # min −x → 推向约束边界

        def std_g(x):
            return 0.05 * float(x[0])

        out = robust_design_optimization(
            mean_fn=mean, std_fn=None, bounds={"x": (0.0, 1.0)}, lam=0.0,
            chance_constraints=[{"mean_fn": lambda x: float(x[0]) - 0.7,
                                 "std_fn": std_g, "alpha": 0.05}],
            maxiter=200)
        assert out["success"] is True
        assert out["x"]["x"] == pytest.approx(x_star, abs=5e-3)
        assert out["constraint_margins"][0] == pytest.approx(0.0, abs=1e-4)

    def test_lambda_sweeps_toward_low_variance(self):
        # μ(x)=(x−0.9)², σ(x)=0.5x：λ=0 → x*=0.9；λ=2 → KKT：
        # 2(x−0.9)+1=0 → x*=0.4（内点，向低方差侧移动）
        def mean(x):
            return (float(x[0]) - 0.9) ** 2

        def std(x):
            return 0.5 * float(x[0])

        out0 = robust_design_optimization(
            mean_fn=mean, std_fn=std, bounds={"x": (0.0, 1.0)}, lam=0.0)
        assert out0["x"]["x"] == pytest.approx(0.9, abs=1e-3)
        out_big = robust_design_optimization(
            mean_fn=mean, std_fn=std, bounds={"x": (0.0, 1.0)}, lam=2.0)
        assert out_big["x"]["x"] == pytest.approx(0.4, abs=5e-3)
        assert out_big["objective"] == pytest.approx(
            robust_objective(out_big["mean"], out_big["std"], 2.0))

    def test_x0_override_and_keys(self):
        out = robust_design_optimization(
            mean_fn=lambda x: float(x[0] ** 2), std_fn=None,
            bounds={"x": (-1.0, 1.0)}, lam=0.0, x0={"x": 0.8})
        assert out["x"]["x"] == pytest.approx(0.0, abs=1e-3)
        with pytest.raises(ValueError, match="键集"):
            robust_design_optimization(
                mean_fn=lambda x: 0.0, std_fn=None,
                bounds={"x": (0, 1)}, lam=0.0, x0={"y": 0.5})

    def test_validation_fail_closed(self):
        with pytest.raises(ValueError, match="bounds 不得为空"):
            robust_design_optimization(mean_fn=lambda x: 0.0, std_fn=None,
                                       bounds={}, lam=0.0)
        with pytest.raises(ValueError, match="hi > lo"):
            robust_design_optimization(mean_fn=lambda x: 0.0, std_fn=None,
                                       bounds={"x": (1.0, 0.0)}, lam=0.0)
        with pytest.raises(ValueError, match="alpha"):
            robust_design_optimization(
                mean_fn=lambda x: 0.0, std_fn=None, bounds={"x": (0, 1)},
                lam=0.0, chance_constraints=[{"mean_fn": lambda x: 0.0,
                                              "alpha": 1.5}])
