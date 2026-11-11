"""T-Q21 通道 2+3 单测：代理梯度桥（adjoint_surrogate_bridge）+ 优化环梯度桥（adjoint_optimizer_link）。

覆盖：梯度范数采样准则/组合示例（零改 active_learning 既有准则——含
ACQUISITION_KINDS 未扩动守卫）、grad callable 适配器契约（形状/有限/类型）、
Rosenbrock 端到端（jax.grad 内核 → 适配器 → 一致性门 → 下降环）与负例。
零网络零真引擎；jax 缺席时逐测试 skip（extra: jax）。
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service import adjoint_surrogate_bridge as bridge
from rfauto.service.adjoint_optimizer_link import (
    gradient_descent_consume,
    make_grad_callable,
    optimizer_preflight,
    rosenbrock_demo,
    rosenbrock_gradient,
    rosenbrock_objective,
)
from rfauto.service.gradient_consistency_service import finite_difference_gradient

BOUNDS = {"x": (-2.0, 2.0), "y": (-2.0, 2.0)}


# ── 通道 2：梯度范数采样准则 ─────────────────────────────────────────────────


def _quad_grad(params: dict[str, float]) -> dict[str, float]:
    """f = (x-0.5)² + (y+0.3)² 的解析梯度（注入缝演示内核）。"""
    return {"x": 2.0 * (params["x"] - 0.5), "y": 2.0 * (params["y"] + 0.3)}


class TestGradientNormPriorities:
    def test_farther_from_optimum_ranks_first(self):
        cands = [{"x": 0.5, "y": -0.3}, {"x": 1.5, "y": 0.7}, {"x": 0.8, "y": -0.3}]
        result = bridge.gradient_norm_priorities(BOUNDS, cands, _quad_grad)
        assert result["ok"] is True
        assert result["criterion"] == "gradient_norm"
        ranked = result["ranked"]
        # (1.5, 0.7)：|∇| = hypot(2.0, 2.0) ≈ 2.83 唯一最大；(0.5, -0.3) 是极小点 → 范数 0
        assert ranked[0]["params"] == {"x": 1.5, "y": 0.7}
        assert ranked[0]["gradient_norm"] == pytest.approx(np.hypot(2.0, 2.0))
        assert ranked[-1]["params"] == {"x": 0.5, "y": -0.3}
        assert ranked[-1]["gradient_norm"] == pytest.approx(0.0)

    def test_deterministic_tiebreak_by_param_tuple(self):
        # 构造性等范数（kernel 恒返 [1,0]）→ 排序纯由参数元组字典序决定，与输入序无关
        cands = [{"x": 2.0, "y": 2.0}, {"x": 0.1, "y": -1.5}]
        a = bridge.gradient_norm_priorities(BOUNDS, cands, lambda _p: {"x": 1.0, "y": 0.0})
        b = bridge.gradient_norm_priorities(
            BOUNDS, list(reversed(cands)), lambda _p: {"x": 1.0, "y": 0.0})
        assert a["ranked"] == b["ranked"]
        assert a["ranked"][0]["params"]["x"] == 0.1  # 字典序 (x=0.1) < (x=2.0)
        assert a["ranked"][0]["gradient_norm"] == pytest.approx(1.0)

    def test_sequence_gradient_form_aligned_with_sorted_bounds(self):
        # 注入缝第二形态：序列梯度（与 sorted(bounds)=["x","y"] 对齐）
        result = bridge.gradient_norm_priorities(
            BOUNDS, [{"x": 1.0, "y": 1.0}],
            lambda p: np.array([2.0 * (p["x"] - 0.5), 2.0 * (p["y"] + 0.3)]))
        assert result["ok"] is True
        assert result["ranked"][0]["gradient_norm"] == pytest.approx(np.hypot(1.0, 2.6))

    def test_missing_gradient_key_is_error(self):
        result = bridge.gradient_norm_priorities(
            BOUNDS, [{"x": 1.0, "y": 1.0}], lambda _p: {"x": 1.0})
        assert result["ok"] is False
        assert "缺参数键" in result["errors"][0]

    def test_nonfinite_gradient_is_error(self):
        result = bridge.gradient_norm_priorities(
            BOUNDS, [{"x": 1.0, "y": 1.0}],
            lambda _p: {"x": float("inf"), "y": 0.0})
        assert result["ok"] is False
        assert "非有限" in result["errors"][0]

    def test_empty_candidates_is_ok_empty(self):
        result = bridge.gradient_norm_priorities(BOUNDS, [], _quad_grad)
        assert result["ok"] is True
        assert result["ranked"] == []

    def test_top_k_truncates(self):
        cands = [{"x": v, "y": 0.0} for v in (0.6, 1.2, 1.8)]
        result = bridge.gradient_norm_priorities(BOUNDS, cands, _quad_grad, top_k=2)
        assert len(result["ranked"]) == 2
        assert result["ranked"][0]["params"]["x"] == 1.8


class TestGradientInformedSampling:
    def _sigma_points(self) -> list[dict]:
        return [
            {"params": {"x": 0.9, "y": -0.3}, "mean": {"cost": 1.0},
             "sigma": {"cost": 0.9}, "score": 0.9},
            {"params": {"x": 0.55, "y": -0.3}, "mean": {"cost": 0.5},
             "sigma": {"cost": 0.1}, "score": 0.1},
        ]

    def test_grad_weight_dominates_ordering(self):
        # σ 与梯度范数信号相反：weight_grad=1 时按梯度范数排
        result = bridge.gradient_informed_sampling(
            BOUNDS, self._sigma_points(), _quad_grad,
            weight_sigma=0.0, weight_grad=1.0)
        assert result["ok"] is True
        ranked = result["ranked"]
        assert ranked[0]["params"]["x"] == 0.9  # 离最优点远 → |∇| 大

    def test_sigma_weight_dominates_ordering(self):
        result = bridge.gradient_informed_sampling(
            BOUNDS, self._sigma_points(), _quad_grad,
            weight_sigma=1.0, weight_grad=0.0)
        assert result["ok"] is True
        assert result["ranked"][0]["sigma_sum"] == pytest.approx(0.9)

    def test_combined_score_is_deterministic_and_bounded(self):
        result = bridge.gradient_informed_sampling(
            BOUNDS, self._sigma_points(), _quad_grad)
        scores = [r["combined_score"] for r in result["ranked"]]
        assert scores == sorted(scores, reverse=True)
        assert all(0.0 <= s <= 1.0 + 1e-12 for s in scores)

    def test_negative_weight_is_error(self):
        result = bridge.gradient_informed_sampling(
            BOUNDS, self._sigma_points(), _quad_grad, weight_sigma=-0.5)
        assert result["ok"] is False
        assert "非负" in result["errors"][0]

    def test_empty_points_is_ok_empty(self):
        result = bridge.gradient_informed_sampling(BOUNDS, [], _quad_grad)
        assert result["ok"] is True
        assert result["ranked"] == []

    def test_existing_acquisition_kinds_untouched(self):
        # 侦察结论守卫：active_learning 既有准则零改（T-Q21 只增不改）
        from rfauto.service.active_learning import ACQUISITION_KINDS
        assert ACQUISITION_KINDS == ("lcb", "ucb", "ei", "sigma")


# ── 通道 3：grad callable 适配器契约 ─────────────────────────────────────────


class TestMakeGradCallable:
    def test_valid_kernel_passthrough(self):
        grad = make_grad_callable(rosenbrock_gradient)
        x = np.array([-0.4, 0.6])
        assert np.asarray(grad(x)).shape == x.shape
        assert np.allclose(grad(x), rosenbrock_gradient(x))

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError, match="形状错配"):
            make_grad_callable(lambda x: np.zeros(len(x) + 1))(np.array([1.0, 2.0]))

    def test_nonfinite_output_raises(self):
        with pytest.raises(ValueError, match="非有限"):
            make_grad_callable(
                lambda x: np.where(np.arange(len(x)) == 0, np.nan, x))(np.array([1.0, 2.0]))

    def test_non_callable_raises_typeerror(self):
        with pytest.raises(TypeError, match="可调用"):
            make_grad_callable("not-a-function")

    def test_bound_kwargs_forwarding(self):
        # 预绑定形态：内核梯度函数的其余参数经 kwargs 绑定（inverse_adjoint 接线点）
        calls: list[dict] = []

        def _kernel(x, beta=None, cfg=None):
            calls.append({"beta": beta, "cfg": cfg})
            return np.asarray(x) * float(beta)

        grad = make_grad_callable(_kernel, beta=2.0, cfg="CFG")
        assert np.allclose(grad(np.array([1.0, 2.0])), [2.0, 4.0])
        assert calls == [{"beta": 2.0, "cfg": "CFG"}]


class TestRosenbrockBasics:
    def test_analytic_gradient_matches_finite_difference(self):
        x = np.array([-0.4, 0.6])
        ref = finite_difference_gradient(rosenbrock_objective, x, h=1e-5)
        assert np.allclose(rosenbrock_gradient(x), ref, rtol=1e-6, atol=1e-8)

    def test_wrong_dimension_raises(self):
        with pytest.raises(ValueError, match="2 维"):
            rosenbrock_objective(np.array([1.0, 2.0, 3.0]))


class TestOptimizerPreflight:
    def test_preflight_pass_with_correct_grad(self):
        result = optimizer_preflight(rosenbrock_objective, make_grad_callable(rosenbrock_gradient),
                                     np.array([-0.4, 0.6]), seed=1)
        assert result["ok"] is True
        assert result["stage"] == "optimizer_preflight"
        assert result["verdict"] == "PASS"

    def test_preflight_fail_with_permuted_grad(self):
        grad = make_grad_callable(lambda x: rosenbrock_gradient(x)[::-1])
        result = optimizer_preflight(rosenbrock_objective, grad, np.array([-0.4, 0.6]), seed=1)
        assert result["ok"] is True  # 门判读成立
        assert result["verdict"] == "FAIL"  # 梯度错位 → FAIL（不凑绿）

    def test_preflight_contract_violation_is_error(self):
        def _boom(_x):
            raise ValueError("bad kernel")

        result = optimizer_preflight(rosenbrock_objective, make_grad_callable(_boom),
                                     np.array([-0.4, 0.6]))
        assert result["ok"] is False


class TestGradientDescentConsume:
    def test_descent_decreases_quadratic(self):
        result = gradient_descent_consume(
            lambda x: float(np.sum((np.asarray(x) - 1.0) ** 2)),
            make_grad_callable(lambda x: 2.0 * (np.asarray(x) - 1.0)),
            np.array([-1.0, 2.0]), iterations=60, step=0.2)
        assert result["ok"] is True
        assert result["decreased"] is True
        assert result["final_objective"] < result["initial_objective"]
        assert result["best_objective"] <= result["final_objective"] + 1e-15

    def test_descent_monotone_history(self):
        result = gradient_descent_consume(
            rosenbrock_objective, make_grad_callable(rosenbrock_gradient),
            np.array([-0.4, 0.6]), iterations=40, step=0.05)
        hist = result["objective_history"]
        assert all(b <= a + 1e-12 for a, b in itertools.pairwise(hist))

    def test_descent_rejects_bad_inputs(self):
        ok_grad = make_grad_callable(rosenbrock_gradient)
        assert gradient_descent_consume(rosenbrock_objective, ok_grad, []).get("ok") is False
        assert gradient_descent_consume(
            rosenbrock_objective, ok_grad, np.array([0.0, 0.0]),
            iterations=0).get("ok") is False
        assert gradient_descent_consume(
            rosenbrock_objective, ok_grad, np.array([0.0, 0.0]),
            step=-1.0).get("ok") is False


class TestRosenbrockDemo:
    def test_end_to_end_pass_with_jax(self):
        pytest.importorskip("jax", reason="jax 为可选依赖（extra: jax）")
        result = rosenbrock_demo()
        assert result["ok"] is True
        assert result["gate_pass"] is True
        assert result["decreased"] is True
        assert result["end_to_end"] is True
        assert result["gate"]["verdict"] == "PASS"
        assert result["descent"]["final_objective"] < result["descent"]["initial_objective"]

    def test_demo_skips_honestly_without_jax(self, monkeypatch):
        # jax 缺席 → skipped 信封如实声明（不伪造、不引入依赖）
        import sys
        monkeypatch.setitem(sys.modules, "jax", None)
        monkeypatch.setitem(sys.modules, "jax.numpy", None)
        result = rosenbrock_demo()
        assert result.get("skipped") is True
        assert result.get("ok") is True
        assert "reason" in result
