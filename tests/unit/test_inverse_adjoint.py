"""E5 逆向设计研究线单测：JAX 可微 1D FDTD + 伴随拓扑优化（离线确定性）。

裁判 = 独立来源（不得自证）：Airy 闭式解 / 转移矩阵（TMM）解析解 + 中心有限差分。
全部固定种子、小网格、无网络、无求解器；jax 缺失时整文件 skip（可选依赖 extra: jax）。
"""

from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("jax", reason="jax 为可选依赖（extra: jax）")

from rfauto.core import inverse_adjoint as ia


@pytest.fixture(scope="module")
def cfg() -> ia.FDTD1DConfig:
    return ia.FDTD1DConfig()


# ── 纯函数：投影 / 滤波 / eps 剖面 ───────────────────────────────────────────


class TestDensityParameterization:
    def test_projection_endpoints_and_midpoint(self):
        assert ia.project_density(0.0, 8.0) == pytest.approx(0.0, abs=1e-12)
        assert ia.project_density(1.0, 8.0) == pytest.approx(1.0, abs=1e-12)
        assert ia.project_density(0.5, 8.0) == pytest.approx(0.5, abs=1e-12)

    def test_projection_is_monotone_and_sharpens_with_beta(self):
        xs = np.linspace(0.0, 1.0, 21)
        low = [ia.project_density(x, 1.0) for x in xs]
        high = [ia.project_density(x, 32.0) for x in xs]
        assert all(b >= a - 1e-15 for a, b in itertools.pairwise(low))
        # 二值化：beta 增大时投影更靠近 0/1（中点保持 0.5）
        assert abs(high[5] - 0.5) >= abs(low[5] - 0.5)
        assert high[5] < 0.05 and high[-6] > 0.95

    def test_smooth_profile_preserves_constant_and_is_symmetric(self):
        assert ia.smooth_profile([2.0] * 5, 2) == pytest.approx([2.0] * 5)
        raw = [1.0, 0.0, 0.0, 0.0, 1.0]
        smoothed = ia.smooth_profile(raw, 1)
        assert smoothed == pytest.approx(list(reversed(smoothed)))
        assert smoothed[0] == pytest.approx((1.0 + 1.0 + 0.0) / 3.0)  # edge padding
        assert ia.smooth_profile(raw, 0) == raw

    def test_reference_eps_profile_places_slab_in_design_region_only(self):
        local = ia.FDTD1DConfig(n_cells=60, source_index=5, probe_index=55, design_lo=20, design_hi=40, eps_max=4.0)
        eps = ia.reference_eps_profile(np.ones(local.design_length), 32.0, local)
        assert len(eps) == local.n_cells
        assert eps[: local.design_lo] == [1.0] * local.design_lo
        assert eps[local.design_hi :] == [1.0] * (local.n_cells - local.design_hi)
        assert eps[local.design_lo : local.design_hi] == pytest.approx([4.0] * local.design_length)

    def test_binary_score_zero_for_binary_one_for_half(self):
        local = ia.FDTD1DConfig(n_cells=40, source_index=2, probe_index=38, design_lo=10, design_hi=30)
        assert ia.binary_score(np.ones(local.design_length), 32.0, local) == pytest.approx(0.0, abs=1e-12)
        assert ia.binary_score(np.zeros(local.design_length), 32.0, local) == pytest.approx(0.0, abs=1e-12)
        assert ia.binary_score(np.full(local.design_length, 0.5), 1.0, local) == pytest.approx(1.0, abs=1e-12)


class TestJaxParameterizationParity:
    def test_jax_profile_matches_python_reference(self, cfg):
        rng = np.random.default_rng(3)
        density = rng.uniform(0.1, 0.9, cfg.design_length)
        for beta in (1.0, 8.0, 32.0):
            got = ia.jax_eps_profile(density, beta, cfg)
            reference = np.array(ia.reference_eps_profile(density, beta, cfg)[cfg.design_lo : cfg.design_hi])
            assert np.max(np.abs(got - reference)) < 1e-9


# ── 解剖裁判：Airy / TMM ─────────────────────────────────────────────────────


class TestAnalyticReferences:
    def test_airy_half_wave_transmits_fully(self):
        eps_r, omega = 4.0, 2.0 * math.pi / 40.0
        thickness = math.pi / (omega * math.sqrt(eps_r))
        assert ia.airy_transmission(eps_r, thickness, omega) == pytest.approx(1.0, abs=1e-12)

    def test_airy_quarter_wave_minimum_matches_closed_form(self):
        eps_r, omega = 4.0, 2.0 * math.pi / 40.0
        n = math.sqrt(eps_r)
        thickness = math.pi / (2.0 * omega * n)
        expected = (2.0 * n / (n * n + 1.0)) ** 2
        assert ia.airy_transmission(eps_r, thickness, omega) == pytest.approx(expected, rel=1e-9)

    @pytest.mark.parametrize("eps_r,thickness", [(2.0, 30.0), (4.0, 23.0), (6.0, 13.0)])
    def test_single_layer_tmm_equals_airy(self, eps_r, thickness):
        omega = 2.0 * math.pi / 40.0
        for numerical in (False, True):
            tmm = ia.tmm_transmission([(eps_r, thickness)], omega, numerical=numerical)
            airy = ia.airy_transmission(eps_r, thickness, omega, numerical=numerical)
            assert tmm == pytest.approx(airy, rel=1e-9)

    def test_profile_to_layers_merges_adjacent_cells(self):
        layers = ia.profile_to_layers([1.0, 3.0, 3.0, 3.0, 1.0])
        assert layers == [(1.0, 1.0), (3.0, 3.0), (1.0, 1.0)]


# ── FDTD 物理正确性 vs Airy 闭式解 ───────────────────────────────────────────


class TestFdtdValidation:
    @pytest.mark.parametrize("eps_r,thickness", [(2.0, 14), (1.5, 35), (2.0, 30), (4.0, 40), (6.0, 20)])
    def test_homogeneous_slab_matches_airy(self, cfg, eps_r, thickness):
        report = ia.homogeneous_slab_report(eps_r, thickness, cfg)
        assert np.isfinite(report["transmission_fdtd"])
        assert report["rel_error_physical"] is not None
        assert report["rel_error_physical"] <= 0.05
        assert report["rel_error_numerical"] <= 0.05

    def test_transmission_is_one_for_vacuum(self, cfg):
        local = ia.FDTD1DConfig(eps_max=1.0, **{k: v for k, v in cfg.__dict__.items() if k != "eps_max"})
        assert ia.transmission(np.ones(local.design_length), 1.0, local) == pytest.approx(1.0, rel=1e-9)

    def test_simulation_is_stable_and_finite(self, cfg):
        sim = ia.simulate(np.ones(cfg.design_length), 32.0, cfg)
        assert sim["finite"] is True
        assert sim["max_abs_ez"] < 10.0


# ── 梯度：jax.grad（伴随/反向）vs 中心有限差分 ───────────────────────────────


class TestGradient:
    @pytest.mark.parametrize("beta,seed", [(1.0, 0), (4.0, 1)])
    def test_adjoint_gradient_matches_finite_difference(self, cfg, beta, seed):
        check = ia.gradient_check(cfg, beta=beta, seed=seed, components=4)
        assert check["x64"] is True
        assert check["max_relative_error"] is not None
        assert check["max_relative_error"] <= ia.GRAD_REL_TOL
        for rel in check["relative_errors"]:
            assert rel is not None and rel <= ia.GRAD_REL_TOL

    def test_relative_error_helper_rejects_degenerate_inputs(self):
        assert ia.relative_error(1.01, 1.0) == pytest.approx(0.01)
        assert ia.relative_error(1.0, 0.0) is None
        assert ia.relative_error(float("nan"), 1.0) is None


# ── 逆设计：梯度下降 + beta 退火 + 二值化 ────────────────────────────────────


class TestOptimization:
    def test_design_is_deterministic(self, cfg):
        opt = ia.OptimizeConfig(iterations=20, beta_end=16.0, seed=2)
        first = ia.optimize_density(cfg, opt)
        second = ia.optimize_density(cfg, opt)
        assert first["objective_history"] == second["objective_history"]
        assert first["density"] == second["density"]

    def test_optimizer_suppresses_transmission_monotonically(self, cfg):
        result = ia.optimize_density(
            cfg, ia.OptimizeConfig(iterations=60, beta_end=32.0, sense="min", seed=0)
        )
        best_history = result["objective_history_best"]
        assert all(b <= a for a, b in itertools.pairwise(best_history))
        assert result["strict_improvements"] >= 10
        # 同一末代 beta 下的公平对照（初值本身随 beta 变化）
        assert result["final_objective"] < 0.05 * result["initial_objective_final_beta"]
        assert result["binary_score"] < 0.25
        assert result["tmm_transmission_numerical"] < 0.05
        assert result["tmm_transmission_physical"] < 0.05

    def test_gradient_descent_beats_random_search(self, cfg):
        result = ia.optimize_density(
            cfg, ia.OptimizeConfig(iterations=60, beta_end=32.0, sense="min", seed=0)
        )
        rng = np.random.default_rng(123)
        best_random = min(
            ia.transmission(rng.uniform(0.0, 1.0, cfg.design_length), 32.0, cfg) for _ in range(64)
        )
        assert result["final_objective"] < 0.01 * best_random

    def test_bad_sense_raises(self, cfg):
        with pytest.raises(ValueError):
            ia.optimize_density(cfg, ia.OptimizeConfig(iterations=1, sense="sideways"))


# ── 独立算法交叉验证：同一分层剖面 FDTD vs TMM ──────────────────────────────


class TestCrossValidation:
    @pytest.mark.parametrize("beta", [4.0, 32.0])
    def test_tmm_matches_fdtd_on_disordered_profile(self, cfg, beta):
        rng = np.random.default_rng(0)
        density = np.clip(0.5 + rng.normal(0.0, 0.15, cfg.design_length), 0.0, 1.0)
        check = ia.tmm_fdtd_cross_check(density, beta, cfg)
        assert check["transmission_fdtd"] > 0.02  # T 量级足以让相对误差可解释
        assert check["rel_error_numerical"] <= 0.05
        assert check["rel_error_physical"] <= 0.05


# ── 离线/契约 ────────────────────────────────────────────────────────────────


class TestOfflineContract:
    def test_module_does_not_bind_jax_at_import(self):
        assert not hasattr(ia, "jax")

    def test_compiled_kernels_are_cached_per_config(self, cfg):
        assert ia._compiled(cfg) is ia._compiled(cfg)

    def test_invalid_index_layout_raises(self):
        bad = ia.FDTD1DConfig(source_index=200, design_lo=140)
        with pytest.raises(ValueError):
            ia.transmission(np.ones(bad.design_length), 1.0, bad)

    def test_density_length_mismatch_raises(self, cfg):
        with pytest.raises(ValueError):
            ia.transmission(np.ones(cfg.design_length + 1), 1.0, cfg)

    def test_literature_notes_are_present_and_honest(self):
        text = " ".join(ia.LITERATURE_NOTES)
        assert "Airy" in text and "TMM" in text
        assert "未实现" in text

