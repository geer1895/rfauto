"""NGO 三期 RF 复数参数仿射 stamp 族单测（aurora_p D1 席）。

验收判据（任务书冻结口径，门值按定标实测 runs/aurora_p/d1/ 预声明）：
- A. 参数仿射双证逐位级（∂Y/∂λ≡Y_k 常数 + 独立逐边装配互证，门 ≤1e-12 相对，
     实测 ~1e-16 浮点底）；
- B. S 求解端接口径（导纳域端接系统 vs 仓内单源 reduce_to_s_matrix 互证
     ≤1e-12；随机无源无耗网络回收 |S|≤1+tol、酉性、互易）；
- C. 无源性 verdict 接单源（surrogate predict 的 passivity 字段与
     pole_residue.passivity_verdict 直调逐项一致）；
- D. OOD 对照表（凸包外结构臂误差 < 黑箱基线，倍数如实报告）；
- E. GMRES 复数路径迭代数表（预条件收益如实；左预条件——坑账 ⑫ 口径）；
- F. 新键注册消费面 + 同 config 同数据两跑 predict 逐位一致（确定性）。
单测零湖写（纯内存合成族，不触 runs/——#144 家族口径）。
"""

import itertools
import math

import numpy as np
import pytest

from rfauto.core.ngo_rf_stamp import (
    BlackBoxResponseNet,
    ComplexAffineStampFamily,
    RfStampPredictor,
    default_lambda_grid,
    gmres_iteration_table,
    ns_step,
    ood_error_table,
)
from rfauto.optimization.surrogate import NgoStampRfSurrogate, surrogate_registry
from rfauto.optimization.surrogate.pole_residue import passivity_verdict

BOUNDS = np.array([[0.0, 2.0], [0.0, 2.0]])
FREQS = np.linspace(1.6e9, 3.2e9, 8)


def _make_family(**kw) -> ComplexAffineStampFamily:
    kw.setdefault("n_grid", 4)
    kw.setdefault("n_blocks", 2)
    return ComplexAffineStampFamily(**kw)


@pytest.fixture(scope="module")
def trained():
    """模块级一次训练（全预算定标档）：predictor + OOD 表 + GMRES 表共享。"""
    fam = _make_family()
    pred = RfStampPredictor(fam, lam_bounds=BOUNDS, freq_grid_hz=FREQS)
    grid = default_lambda_grid(BOUNDS, n_per_axis=4)
    pred.fit(grid)
    ood_pts = [np.array([2.3, 0.4]), np.array([0.5, 2.4]),
               np.array([2.4, 2.4]), np.array([2.2, 1.1])]
    tab = gmres_iteration_table(fam, pred, grid[::2], 2.4e9)
    return {
        "family": fam,
        "predictor": pred,
        "grid": grid,
        "ood_pts": ood_pts,
        "ood": ood_error_table(fam, pred, grid[::2], ood_pts),
        "gmres": tab,
    }


# ─── A. 参数仿射双证 ─────────────────────────────────────────────────────────


class TestAffineDualEvidence:
    def test_stamp_affine_residual_walk_vs_combo(self):
        """独立逐边装配 vs 基矩阵线性组合互证（green_stamp stamp_affine_residual
        同款双证；门 ≤1e-12 相对，实测浮点求和序差底 ~1e-16）。"""
        fam = _make_family()
        rng = np.random.default_rng(11)
        for lam in (np.zeros(2), np.array([0.7, 1.3]), np.array([2.0, 2.0]),
                    rng.uniform(0.0, 2.0, 2)):
            for f in (1.6e9, 2.4e9, 3.2e9):
                assert fam.stamp_affine_residual(lam, 2.0 * math.pi * f) <= 1e-12

    def test_affine_segment_derivative_is_constant_basis(self):
        """∂Y/∂λ_k≡Y_k 常数逐位级：Y(λ+e_k)−Y(λ)≡Y_k(ω)（门 ≤1e-12）。"""
        fam = _make_family(n_blocks=3)
        lam = np.array([0.3, 1.1, 1.9])
        for f in (1.6e9, 2.4e9):
            assert fam.affine_segment_residual(lam, 2.0 * math.pi * f) <= 1e-12

    def test_affine_exact_at_extreme_corners(self):
        fam = _make_family()
        for lam in (np.array([0.0, 2.0]), np.array([2.0, 0.0])):
            assert fam.stamp_affine_residual(lam, 2.0 * math.pi * 2.4e9) <= 1e-12
            assert fam.affine_segment_residual(lam, 2.0 * math.pi * 2.4e9) <= 1e-12

    def test_negative_bad_lam_and_freq(self):
        fam = _make_family()
        with pytest.raises(ValueError, match="长度"):
            fam.stamp_affine_residual(np.zeros(3), 2.0 * math.pi * 2.4e9)
        with pytest.raises(ValueError, match="非有限"):
            fam.system_matrix(np.array([np.nan, 0.0]), 2.0 * math.pi * 2.4e9)
        with pytest.raises(ValueError, match="升序"):
            fam.solve_s_matrix(np.zeros(2), np.array([2.4e9, 1.6e9]))
        with pytest.raises(ValueError, match="正有限"):
            fam.solve_s_matrix(np.zeros(2), np.array([0.0, 1.6e9]))

    def test_physical_domain_flag(self):
        fam = _make_family()
        assert fam.physical_valid(np.zeros(2))
        assert fam.physical_valid(np.array([0.0, 2.0]))
        assert not fam.physical_valid(np.array([-0.1, 1.0]))

    def test_lossless_init_requires_positive_capacitance(self):
        with pytest.raises(ValueError, match=">0"):
            ComplexAffineStampFamily(n_grid=4, n_blocks=2, c_g0=0.0)


# ─── B. S 求解端接口径 ───────────────────────────────────────────────────────


class TestSPortSolve:
    def test_dual_path_agreement_with_repo_single_source(self):
        """导纳域端接系统 vs 仓内单源 reduce_to_s_matrix（Z 域同一端接约束
        方程）互证——门 ≤1e-12 相对（实测 ~1.6e-15）。"""
        fam = _make_family()
        fam_ll = _make_family(lossless=True)
        rng = np.random.default_rng(13)
        cands = [np.zeros(2), np.array([0.7, 1.3]), np.array([2.0, 2.0])]
        cands += [rng.uniform(0.0, 2.0, 2) for _ in range(3)]
        worst = 0.0
        for lam in cands:
            for family in (fam, fam_ll):
                s1 = family.solve_s_matrix(lam, FREQS)
                s2 = family.solve_s_matrix_reference(lam, FREQS)
                rel = float(np.linalg.norm(s1 - s2)
                            / np.linalg.norm(s2))
                worst = max(worst, rel)
        assert worst <= 1e-12

    def test_random_lossless_passive_unitary_reciprocal(self):
        """随机无源无耗网络回收：|S|≤1+tol（逐频 σmax）、酉性 ‖SSᴴ−I‖、
        互易 S=Sᵀ（求解路径浮点底实测报数，≤1e-12；装配级 Y=Yᵀ 逐位）。"""
        rng = np.random.default_rng(17)
        fam = ComplexAffineStampFamily(
            n_grid=4, n_blocks=2, lossless=True,
            c_bg=float(rng.uniform(0.5e-12, 2e-12)),
            c_g0=float(rng.uniform(2e-13, 8e-13)),
            c_ch=float(rng.uniform(1e-12, 5e-12)),
        )
        lam = rng.uniform(0.0, 2.0, 2)
        s = fam.solve_s_matrix(lam, FREQS)
        assert s.shape == (8, 2, 2)
        sig = [float(np.linalg.svd(m, compute_uv=False)[0]) for m in s]
        assert max(sig) <= 1.0 + 1e-9          # 无源性回收（|S|≤1+tol）
        assert min(sig) >= 1.0 - 1e-9          # 无耗 ⇒ 酉（σmax≈1）
        uni = max(float(np.linalg.norm(m @ m.conj().T - np.eye(2)))
                  for m in s)
        assert uni <= 1e-9
        recip = float(np.max(np.abs(s - np.swapaxes(s, 1, 2))))
        assert recip <= 1e-12                  # 求解路径互易残差（实测 ~4e-16）
        # 装配级互易：Y=Yᵀ 逐位（同值双边累加，构造性对称）
        y = fam.system_matrix(lam, 2.0 * math.pi * 2.4e9)
        np.testing.assert_array_equal(y, y.T)

    def test_lossy_network_strictly_passive(self):
        fam = _make_family()
        s = fam.solve_s_matrix(np.array([0.7, 1.3]), FREQS)
        sig = [float(np.linalg.svd(m, compute_uv=False)[0]) for m in s]
        assert max(sig) <= 1.0 + 1e-9
        assert max(sig) < 1.0                  # 有耗 ⇒ 严格无源（σmax<1）

    def test_reference_path_non_monotone_freq_rejected(self):
        fam = _make_family()
        with pytest.raises(ValueError, match="升序"):
            fam.solve_s_matrix_reference(np.zeros(2),
                                         np.array([2.4e9, 1.6e9]))


# ─── C. 无源性 verdict 接单源 ────────────────────────────────────────────────


class TestPassivityVerdictSingleSource:
    def test_surrogate_passivity_field_equals_direct_call(self):
        """predict 的 passivity 字段与 pole_residue.passivity_verdict 直调
        逐项一致（单源消费，不复制公式——验收 C）。"""
        model = self._fit_small()
        params = {"w1": 0.8, "w2": 1.2}
        out = model.predict(params)
        s = model.predict_matrix(params)
        assert out["passivity"] == passivity_verdict(s)
        assert out["passivity"]["passive"] is True

    @staticmethod
    def _fit_small(**kw) -> NgoStampRfSurrogate:
        config = {
            "bounds": {"w1": (0.0, 2.0), "w2": (0.0, 2.0)},
            "freq_grid_ghz": (1.6, 3.2),
            "n_freq": 8,
            "epochs_inv": 200,
            "epochs_coef": 100,
        }
        config.update(kw)
        model = NgoStampRfSurrogate(config=config)
        model.fit([
            {"params": {"w1": 0.5, "w2": 1.5}},
            {"params": {"w1": 1.5, "w2": 0.3}},
            {"params": {"w1": 1.0, "w2": 1.0}},
            {"params": {"w1": 0.2, "w2": 1.8}},
            {"params": {"w1": 1.8, "w2": 0.6}},
            {"params": {"w1": 0.9, "w2": 0.4}},
        ])
        return model


# ─── D. OOD 对照表 ───────────────────────────────────────────────────────────


class TestOodTable:
    def test_structure_beats_blackbox_out_of_hull(self, trained):
        """凸包外结构臂误差 < 黑箱基线（倍数写进报告；门：结构 OOD max
        ≤0.05 且 < 黑箱 OOD max——定标实测 0.018 vs 0.188）。"""
        su = trained["ood"]["summary"]
        st_ood = su["structure"]["ood"]["max"]
        bb_ood = su["blackbox"]["ood"]["max"]
        assert st_ood <= 0.05
        assert st_ood < bb_ood

    def test_table_shape_and_in_hull_rows(self, trained):
        su = trained["ood"]["summary"]
        assert su["structure"]["in"]["max"] <= 0.02
        rows = trained["ood"]["rows"]
        assert {r["region"] for r in rows} == {"in", "ood"}
        for r in rows:
            assert len(r["lam"]) == 2
            assert len(r["lam_hat_structure"]) == 2
            assert r["rel_err_structure"] >= 0.0
            assert r["rel_err_blackbox"] >= 0.0

    def test_predictor_unfit_raises(self):
        fam = _make_family()
        pred = RfStampPredictor(fam, lam_bounds=BOUNDS, freq_grid_hz=FREQS)
        with pytest.raises(RuntimeError, match="先 fit"):
            ood_error_table(fam, pred, [np.zeros(2)], [np.ones(2)])


# ─── E. GMRES 复数路径迭代数表 ───────────────────────────────────────────────


class TestGmresTable:
    def test_preconditioner_beats_unpreconditioned(self, trained):
        """预条件收益如实落表（定标实测 16→5 量级、halved_fraction=1.0；
        门：双方收敛 + halved_fraction ≥0.5 + 预条件残差达标）。"""
        tab = trained["gmres"]
        su = tab["summary"]
        assert su["n_cases"] >= 4
        assert su["n_converged_both"] == su["n_cases"]
        assert su["halved_fraction"] >= 0.5
        assert su["max_spectral_radius"] < 1.0
        assert su["warnings"] == []
        for r in tab["rows"]:
            assert r["converged_precond"]
            assert r["residual_rel_precond"] <= 1e-8 * (1.0 + 1e-6)
            assert r["iterations_precond"] <= r["iterations_unprecond"]

    def test_table_bitwise_deterministic(self, trained):
        tab2 = gmres_iteration_table(trained["family"], trained["predictor"],
                                     trained["grid"][::2], 2.4e9)
        assert tab2["rows"] == trained["gmres"]["rows"]
        assert tab2["summary"]["halved_fraction"] \
            == trained["gmres"]["summary"]["halved_fraction"]

    def test_bad_args(self, trained):
        with pytest.raises(ValueError, match="非空"):
            gmres_iteration_table(trained["family"], trained["predictor"], [],
                                  2.4e9)
        with pytest.raises(ValueError, match="≥1"):
            gmres_iteration_table(trained["family"], trained["predictor"],
                                  trained["grid"][:2], 2.4e9, max_cycles=0)


# ─── Newton-Schulz 复数 einsum 路径 ─────────────────────────────────────────


class TestNewtonSchulz:
    def test_ns_identity_algebra(self):
        """I−Â⁺M=(I−ÂM)² 恒等式（随机复矩阵，门 ≤1e-10）。"""
        rng = np.random.default_rng(19)
        a = rng.normal(size=(5, 5)) + 1j * rng.normal(size=(5, 5))
        m = rng.normal(size=(5, 5)) + 1j * rng.normal(size=(5, 5))
        lhs = np.eye(5, dtype=complex) - ns_step(a, m) @ m
        rhs = np.linalg.matrix_power(np.eye(5, dtype=complex) - a @ m, 2)
        assert float(np.linalg.norm(lhs - rhs)) <= 1e-10

    def test_batched_ns_step(self):
        rng = np.random.default_rng(23)
        a = rng.normal(size=(3, 4, 4)) + 1j * rng.normal(size=(3, 4, 4))
        m = rng.normal(size=(4, 4)) + 1j * rng.normal(size=(4, 4))
        got = ns_step(a, m)
        for k in range(3):
            np.testing.assert_allclose(got[k], ns_step(a[k], m), rtol=1e-12)

    def test_refine_monotone_guard_quadratic(self, trained):
        """受保精修：残差迹单调不退化且平方收敛（定标实测
        0.078→1.8e-3→1.5e-6→1.4e-12）。"""
        pred = trained["predictor"]
        lam = trained["grid"][5]
        ns = pred.newton_schulz_refine(lam, 2.4e9, rounds=3)
        trace = ns["residual_trace"]
        assert ns["rounds_taken"] >= 1
        assert all(b < a for a, b in itertools.pairwise(trace))
        assert trace[-1] < 1e-8


# ─── F. 注册消费面 + 确定性 + 系数头回收 ─────────────────────────────────────


class TestRegistryAndDeterminism:
    def test_registry_membership_and_create(self):
        assert "ngo_stamp_rf" in surrogate_registry.available()
        model = surrogate_registry.create(
            "ngo_stamp_rf",
            config={"bounds": {"w1": (0.0, 1.0), "w2": (0.0, 1.0)},
                    "freq_grid_ghz": (1.6, 3.2), "n_freq": 4})
        assert model.KIND == "ngo_stamp_rf"
        assert model.n_params == 2

    def test_two_runs_bitwise_identical(self):
        samples = [
            {"params": {"w1": 0.5, "w2": 1.5}},
            {"params": {"w1": 1.5, "w2": 0.3}},
            {"params": {"w1": 1.0, "w2": 1.0}},
            {"params": {"w1": 0.2, "w2": 1.8}},
        ]
        config = {
            "bounds": {"w1": (0.0, 2.0), "w2": (0.0, 2.0)},
            "freq_grid_ghz": (1.6, 3.2), "n_freq": 8,
            "epochs_inv": 120, "epochs_coef": 60,
        }
        outs = []
        mats = []
        for _ in range(2):
            model = NgoStampRfSurrogate(config=dict(config))
            model.fit(samples)
            outs.append(model.predict({"w1": 0.8, "w2": 1.2}))
            mats.append(model.predict_matrix({"w1": 0.8, "w2": 1.2}).tobytes())
        assert outs[0] == outs[1]
        assert mats[0] == mats[1]

    def test_contract_and_info(self):
        model = TestPassivityVerdictSingleSource._fit_small()
        assert model.fitted
        assert model.uncertainty({"w1": 1.0, "w2": 1.0}) is None
        out = model.predict({"w1": 1.0, "w2": 1.0})
        for key in ("s11_db_max_in_band", "s11_db_min_in_band",
                    "s21_db_max_in_band", "s21_db_min_in_band",
                    "s12_db_max_in_band", "s22_db_min_in_band"):
            assert key in out
        assert set(out["stamp_coefficients"]) == {"w1", "w2"}
        s = model.predict_matrix({"w1": 1.0, "w2": 1.0})
        assert s.shape == (8, 2, 2) and np.all(np.isfinite(s))
        with pytest.raises(RuntimeError, match="先 fit"):
            NgoStampRfSurrogate(config={
                "bounds": {"w1": (0.0, 1.0), "w2": (0.0, 1.0)},
                "freq_grid_ghz": (1.6, 3.2)}).predict_matrix({})

    def test_fit_skips_and_validation(self):
        config = {"bounds": {"w1": (0.0, 2.0), "w2": (0.0, 2.0)},
                  "freq_grid_ghz": (1.6, 3.2), "n_freq": 4,
                  "epochs_inv": 20, "epochs_coef": 20}
        model = NgoStampRfSurrogate(config=config)
        with pytest.raises(ValueError, match="无样本"):
            model.fit([])
        info = model.fit([
            {"params": {"w1": 0.5, "w2": 1.5}},
            {"params": {}},                     # 缺键 → 界中点（合法）
            {"params": {"w1": "bad", "w2": 1.0}},   # 不可转 float → 跳过
            {"params": {"w1": float("nan"), "w2": 1.0}},  # 非有限 → 跳过
            "not-a-dict",                       # 非法行 → 跳过
        ])
        assert info["n_samples"] == 2
        assert info["n_skipped"] == 3
        assert info["kind"] == "ngo_stamp_rf"
        with pytest.raises(ValueError, match="≥0"):
            NgoStampRfSurrogate(config={
                "bounds": {"w1": (-0.5, 1.0), "w2": (0.0, 1.0)},
                "freq_grid_ghz": (1.6, 3.2)})
        with pytest.raises(ValueError, match="lo<hi"):
            NgoStampRfSurrogate(config={
                "bounds": {"w1": (1.0, 1.0), "w2": (0.0, 1.0)},
                "freq_grid_ghz": (1.6, 3.2)})

    def test_coefficient_head_recovery_in_hull(self, trained):
        """系数头域内回收（恒等目标）：绝对误差门 ≤0.05（原始单位，
        定标实测 RMSE 0.0017 归一化 ≈ 0.0034 原始）。"""
        pred = trained["predictor"]
        for lam in trained["grid"]:
            lam_hat = pred.predict_coefficients(lam)
            assert float(np.max(np.abs(lam_hat - lam))) <= 0.05

    def test_predictor_rejects_out_of_domain(self):
        fam = _make_family()
        pred = RfStampPredictor(fam, lam_bounds=BOUNDS, freq_grid_hz=FREQS)
        with pytest.raises(ValueError, match="无源物理域"):
            pred.fit([np.array([-0.5, 1.0])])
        with pytest.raises(ValueError, match="非空列表"):
            pred.fit([])
        pred2 = RfStampPredictor(fam, lam_bounds=BOUNDS, freq_grid_hz=FREQS)
        with pytest.raises(RuntimeError, match="先 fit"):
            pred2.predict_coefficients(np.zeros(2))
        with pytest.raises(RuntimeError, match="先 fit"):
            pred2.predict_a_hat(np.zeros(2), 2.4e9)


# ─── 黑箱对照臂 ──────────────────────────────────────────────────────────────


class TestBlackBoxArm:
    def test_blackbox_fit_predict_and_determinism(self):
        fam = _make_family()
        grid = default_lambda_grid(BOUNDS, n_per_axis=3)
        outs = []
        for _ in range(2):
            bb = BlackBoxResponseNet(fam, lam_bounds=BOUNDS,
                                     freq_grid_hz=FREQS, epochs=80)
            bb.fit(grid)
            outs.append(bb.predict(grid[1]).tobytes())
        assert outs[0] == outs[1]
        bb = BlackBoxResponseNet(fam, lam_bounds=BOUNDS, freq_grid_hz=FREQS,
                                 epochs=80)
        info = bb.fit(grid)
        assert info["kind"] == "ngo_rf_stamp_blackbox"
        assert info["n_samples"] == len(grid)
        s = bb.predict(grid[2])
        assert s.shape == (8, 2, 2) and np.all(np.isfinite(s))
        with pytest.raises(ValueError, match="无源物理域"):
            BlackBoxResponseNet(fam, lam_bounds=BOUNDS,
                                freq_grid_hz=FREQS).fit([np.array([-1.0, 0.0])])
        with pytest.raises(RuntimeError, match="先 fit"):
            BlackBoxResponseNet(fam, lam_bounds=BOUNDS,
                                freq_grid_hz=FREQS).predict(grid[0])

    def test_default_grid_reused_from_green_stamp(self):
        """green_stamp.default_lambda_grid 消费复用（零复制——K 维泛化面）。"""
        grid = default_lambda_grid(BOUNDS, n_per_axis=3)
        assert len(grid) == 9
        assert all(row.shape == (2,) for row in grid)
        with pytest.raises(ValueError, match="lo<hi"):
            default_lambda_grid(np.array([[2.0, 0.0], [0.0, 2.0]]))
