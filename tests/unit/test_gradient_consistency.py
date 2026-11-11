"""T-Q21 通道 1 单测：梯度一致性门（service/gradient_consistency_service.py）。

判据预声明（开工冻结，测试钉死不放松）：cosine ≥0.999 / rel err ≤0.05。
numpy 自证形态（合成解析函数对照）全环境跑；JAX 接线测试（inverse_adjoint
1D FDTD 伴随 vs 中心差分）jax 缺席时逐测试 skip（可选依赖 extra: jax，
skip 形态与 test_inverse_adjoint.py 同族、零扩大）。零网络零真引擎。
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service.gradient_consistency_service import (
    DEFAULT_COSINE_THRESHOLD,
    DEFAULT_REL_ERR_THRESHOLD,
    cosine_similarity,
    finite_difference_gradient,
    gate_with_finite_difference,
    gradient_consistency_gate,
)

# ── cosine_similarity 纯函数 ─────────────────────────────────────────────────


class TestCosineSimilarity:
    def test_parallel_vectors_give_one(self):
        assert cosine_similarity([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)

    def test_anti_parallel_give_minus_one(self):
        assert cosine_similarity([1.0, 2.0], [-3.0, -6.0]) == pytest.approx(-1.0)

    def test_orthogonal_give_zero(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 5.0]) == pytest.approx(0.0)

    def test_zero_vector_returns_none_not_zero(self):
        # 单侧零向量：方向不可解释 → None（不静默当 0，#316 多报不放过）
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) is None

    def test_nonfinite_returns_none(self):
        assert cosine_similarity([float("nan"), 1.0], [1.0, 1.0]) is None

    def test_dimension_mismatch_raises(self):
        with pytest.raises(ValueError, match="维度不匹配"):
            cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


# ── finite_difference_gradient（numpy 参考 provider） ────────────────────────


class TestFiniteDifferenceGradient:
    def test_matches_analytic_on_quadratic(self):
        grad = finite_difference_gradient(lambda x: float(np.sum(x**2)), [0.3, -1.2, 2.0])
        assert grad == pytest.approx([0.6, -2.4, 4.0], rel=1e-6)

    def test_nonpositive_step_raises(self):
        with pytest.raises(ValueError, match="步长"):
            finite_difference_gradient(lambda x: float(np.sum(x)), [1.0], h=0.0)


# ── 梯度一致性门：合成解析函数全链 ───────────────────────────────────────────


def _analytic_quad_grad(x: np.ndarray) -> np.ndarray:
    """f(x)=Σx² 的解析梯度 2x（被检方演示内核）。"""
    return 2.0 * np.asarray(x, dtype=float)


class TestGradientConsistencyGate:
    def test_gate_pass_on_analytic_vs_finite_difference(self):
        result = gate_with_finite_difference(
            lambda x: float(np.sum(np.asarray(x) ** 2)), _analytic_quad_grad,
            x0=[0.4, -0.7, 1.1], n_probes=4)
        assert result["ok"] is True
        assert result["verdict"] == "PASS"
        assert result["n_fail"] == 0
        assert result["worst_cosine"] >= DEFAULT_COSINE_THRESHOLD
        assert result["worst_rel_error"] <= DEFAULT_REL_ERR_THRESHOLD

    def test_gate_fail_on_permuted_gradient(self):
        # 负例：梯度分量错位（转置/乱序）——cosine 崩 → 门 FAIL（#122 如实）
        result = gate_with_finite_difference(
            lambda x: float(np.sum(np.asarray(x) ** 2)),
            lambda x: _analytic_quad_grad(x)[::-1],
            x0=[0.4, -0.7, 1.1], n_probes=3)
        assert result["ok"] is True
        assert result["verdict"] == "FAIL"
        assert result["n_fail"] >= 1

    def test_gate_fail_on_sign_flipped_gradient(self):
        result = gate_with_finite_difference(
            lambda x: float(np.sum(np.asarray(x) ** 2)),
            lambda x: -_analytic_quad_grad(x),
            x0=[0.4, -0.7], n_probes=3)
        assert result["verdict"] == "FAIL"
        assert result["worst_cosine"] is not None and result["worst_cosine"] < 0.0

    def test_gate_fail_on_nonfinite_gradient(self):
        def _bad(_x):
            return np.array([float("nan"), 1.0])

        result = gradient_consistency_gate(_bad, _analytic_quad_grad,
                                           [np.array([0.5, 0.5])])
        assert result["ok"] is True
        assert result["verdict"] == "FAIL"
        assert result["details"][0]["status"] == "nonfinite"

    def test_gate_single_zero_gradient_fails_and_both_zero_passes(self):
        x = np.array([0.3, 0.4])
        single = gradient_consistency_gate(lambda _x: np.zeros(2), _analytic_quad_grad, [x])
        assert single["verdict"] == "FAIL"
        assert single["details"][0]["status"] == "zero_gradient"
        pair = gradient_consistency_gate(lambda _x: np.zeros(2), lambda _x: np.zeros(2), [x])
        assert pair["verdict"] == "PASS"
        assert pair["details"][0]["status"] == "both_zero"

    def test_gate_provider_crash_is_error_not_fail_verdict(self):
        def _boom(_x):
            raise RuntimeError("kernel exploded")

        result = gradient_consistency_gate(_boom, _analytic_quad_grad, [np.array([0.1, 0.2])])
        assert result["ok"] is False
        assert "kernel exploded" in result["errors"][0]

    def test_gate_shape_mismatch_is_error(self):
        result = gradient_consistency_gate(
            lambda x: np.zeros(len(x) + 1), _analytic_quad_grad, [np.array([0.1, 0.2])])
        assert result["ok"] is False
        assert "形状错配" in result["errors"][0]

    def test_gate_empty_probes_is_error(self):
        result = gradient_consistency_gate(_analytic_quad_grad, _analytic_quad_grad, [])
        assert result["ok"] is False

    def test_gate_echoes_predeclared_thresholds(self):
        result = gradient_consistency_gate(_analytic_quad_grad, _analytic_quad_grad,
                                           [np.array([1.0, 2.0])])
        assert result["cosine_threshold"] == DEFAULT_COSINE_THRESHOLD == 0.999
        assert result["rel_err_threshold"] == DEFAULT_REL_ERR_THRESHOLD == 0.05

    def test_gate_invalid_thresholds_raise(self):
        x = [np.array([1.0])]
        with pytest.raises(ValueError, match="cosine"):
            gradient_consistency_gate(_analytic_quad_grad, _analytic_quad_grad, x,
                                      cosine_threshold=0.0)
        with pytest.raises(ValueError, match="rel err"):
            gradient_consistency_gate(_analytic_quad_grad, _analytic_quad_grad, x,
                                      rel_err_threshold=-1.0)

    def test_gate_with_finite_difference_deterministic_same_seed(self):
        kwargs = dict(n_probes=4, seed=7)
        a = gate_with_finite_difference(
            lambda x: float(np.sum(np.asarray(x) ** 2)), _analytic_quad_grad,
            x0=[0.2, 0.5], **kwargs)
        b = gate_with_finite_difference(
            lambda x: float(np.sum(np.asarray(x) ** 2)), _analytic_quad_grad,
            x0=[0.2, 0.5], **kwargs)
        assert a["details"] == b["details"]
        assert a["verdict"] == b["verdict"] == "PASS"


# ── JAX 接线：inverse_adjoint 1D FDTD 伴随 vs 中心差分（真资产端到端） ────────


SMALL_CFG = None  # 模块级惰性构造（jax 在场才 import 内核，缺席环境零成本）


def _small_cfg():
    global SMALL_CFG
    if SMALL_CFG is None:
        from rfauto.core.inverse_adjoint import FDTD1DConfig
        SMALL_CFG = FDTD1DConfig(
            n_cells=100, n_steps=300, source_index=12, probe_index=88,
            design_lo=38, design_hi=68)
    return SMALL_CFG


class TestInverseAdjointWiring:
    def test_adjoint_gradient_passes_gate_against_finite_difference(self):
        pytest.importorskip("jax", reason="jax 为可选依赖（extra: jax）")
        from rfauto.core.inverse_adjoint import adjoint_gradient, transmission

        cfg = _small_cfg()
        rng = np.random.default_rng(0)
        x0 = rng.uniform(0.3, 0.7, cfg.design_length)
        result = gate_with_finite_difference(
            partial(transmission, beta=1.0, cfg=cfg),
            partial(adjoint_gradient, beta=1.0, cfg=cfg),
            x0=x0, n_probes=3, fd_step=1e-4, seed=0)
        assert result["ok"] is True
        assert result["verdict"] == "PASS"
        assert result["worst_rel_error"] <= DEFAULT_REL_ERR_THRESHOLD

    def test_adjoint_gradient_gate_catches_permuted_kernel(self):
        pytest.importorskip("jax", reason="jax 为可选依赖（extra: jax）")
        from rfauto.core.inverse_adjoint import adjoint_gradient, transmission

        cfg = _small_cfg()
        rng = np.random.default_rng(0)
        x0 = rng.uniform(0.3, 0.7, cfg.design_length)

        def _permuted(density, **kw):
            return adjoint_gradient(density, **kw)[::-1]

        result = gate_with_finite_difference(
            partial(transmission, beta=1.0, cfg=cfg),
            partial(_permuted, beta=1.0, cfg=cfg),
            x0=x0, n_probes=2, fd_step=1e-4, seed=0)
        assert result["verdict"] == "FAIL"
