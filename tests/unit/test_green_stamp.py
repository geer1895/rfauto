"""green_stamp 参数仿射 stamp 内核 + NGO 三档/GMRES 预条件/OOD 基准单测。

判据预声明（定标证据 runs/aurora_o/to7_calib/calib_out.txt，2026-11-01
同 seed 同数据经模块真实路径实测；tune*.py 为配方扫描账）：
- G1 构造性仿射（结构恒等面）：独立逐边装配 vs 基矩阵线性组合相对残差
  ≤ 1e-12（实测 ~1e-16，浮点求和序差底）；∂F/∂λ_k=F_k 常数钉（数值导
  ≤ 1e-8 相对）；
- G2 data-free 收敛（验收①）：代数一致性残差曲线首末比 ≥4× 且末值
  ≤0.08（实测 1.325→0.0497，26.6×）；
- G3 GMRES 预条件（验收②，论文 Table 4 形态）：全 25 点 λ 网格上
  halved_fraction ≥0.7（实测 0.80）、总迭代缩减 ≥1.8×（实测 2.28×）、
  it1_max ≤9（实测 7）、max ρ(I−FÂ) ≤0.5（实测 0.086）且零 Neumann
  警告；负例=Â=−I 桩显式 UserWarning（不静默）；
- G4 OOD（验收③，论文 Table 2 精神）：宽覆盖 data-free 结构档（λ∈
  [0.1,2.2]² 免解标签）vs 窄标签黑箱（MLP / poly2 岭裸 numpy 独立实现）
  ——结构档 OOD max ≤0.15（实测 0.081）且 < 黑箱 MLP OOD max（实测
  0.585）且 < poly2 岭 OOD max（实测 31.6）；结构档退化比 <2×（实测
  0.78）< 黑箱退化比（实测 2869×）；
- G5 确定性（验收④）：同 seed 同数据两跑 predict_a_hat 逐位一致；
  异 seed 相异；data_free 档传/不传解标签逐位一致（无解标签语义）；
  GMRES 表同输入两次逐位一致；
- G6 负例/契约：λ 形状/非有限值、物理域外样本、非法 config、未 fit
  预测、data 档缺标签样本、空 λ 表——全部显式报错不静默；
- G7 零改动：surrogate 注册表零新增键（green_op 等既有键原样），
  green_op 叠加先例回归钉。

裁判纪律（#118/#300）：合成族真值=离散线性系统本身（解析构造即定义），
solve（splu）与 solve_dense（np.linalg.solve）独立互证+残差判据；黑箱
基线在测试内裸 numpy 独立实现（poly2 岭），与被测零共享代码。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.green_stamp import (
    AffineStampFamily,
    BlackBoxSolutionNet,
    StampInversePredictor,
    default_lambda_grid,
    gmres_iteration_table,
    ood_error_table,
)
from rfauto.optimization.surrogate import surrogate_registry

N_GRID = 5
BOUNDS = [(0.2, 1.0), (0.2, 1.0)]

# 预声明门（定标证据 CALIB / calib_out.txt）
GATE_AFFINE_RESID = 1e-12
GATE_DERIV = 1e-8
GATE_DF_FINAL = 0.08
GATE_DF_DESCEND = 4.0
GATE_HALVED_FRAC = 0.7
GATE_GMRES_REDUCTION = 1.8
GATE_IT1_MAX = 9
GATE_RHO_MAX = 0.5
GATE_OOD_STRUCT = 0.15
GATE_OOD_DEG_STRUCT = 2.0


@pytest.fixture(scope="module")
def family() -> AffineStampFamily:
    return AffineStampFamily(n_grid=N_GRID, n_blocks=2, kappa_bg=1.0)


@pytest.fixture(scope="module")
def grid(family: AffineStampFamily) -> list[np.ndarray]:
    return default_lambda_grid(BOUNDS, n_per_axis=5)


@pytest.fixture(scope="module")
def df_narrow(family: AffineStampFamily,
              grid: list[np.ndarray]) -> StampInversePredictor:
    """窄域 data-free 档（预声明缺省配方，GMRES 演示臂）。"""
    p = StampInversePredictor(family, lam_bounds=BOUNDS, mode="data_free")
    p.fit()
    return p


@pytest.fixture(scope="module")
def df_wide(family: AffineStampFamily) -> StampInversePredictor:
    """宽覆盖 data-free 档（免解标签→λ 覆盖零边际成本，OOD 结构臂）。"""
    p = StampInversePredictor(family, lam_bounds=[(0.1, 2.2), (0.1, 2.2)],
                              mode="data_free", grid_per_axis=6)
    p.fit()
    return p


@pytest.fixture(scope="module")
def blackbox(family: AffineStampFamily,
             grid: list[np.ndarray]) -> BlackBoxSolutionNet:
    """窄标签黑箱 ML 臂（fno_lite 形态映射：同容量 MLP λ→x 直映）。"""
    bb = BlackBoxSolutionNet(family, lam_bounds=BOUNDS, hidden=32,
                             seed=20261101, lr=2e-2, epochs=600)
    bb.fit(grid)
    return bb


# ─── G1 构造性仿射（结构恒等面） ─────────────────────────────────────────────


def test_affine_assembly_matches_linear_combination(family):
    for lam in ([0.2, 0.2], [0.6, 1.0], [1.0, 0.2], [0.35, 0.87]):
        resid = family.stamp_affine_residual(lam)
        assert resid <= GATE_AFFINE_RESID, f"λ={lam} affine resid={resid}"
    # 随机 θ 加严一组（确定性采样，无全局 RNG 依赖）
    pts = np.linspace(0.0, 1.0, 11)
    for a in pts:
        for b in (0.13, 0.55, 0.97):
            assert family.stamp_affine_residual([a, b]) <= GATE_AFFINE_RESID


def test_parameter_derivative_is_constant_basis(family):
    """∂F/∂λ_k ≡ F_k 常数钉：中心差分数值导 vs 基矩阵。"""
    basis = family.basis_matrices()
    h = 1e-6
    lam0 = np.array([0.5, 0.8])
    for k in range(family.n_params):
        lp, lm = lam0.copy(), lam0.copy()
        lp[k] += h
        lm[k] -= h
        num = (family.system_matrix(lp) - family.system_matrix(lm)) / (2 * h)
        scale = float(np.linalg.norm(basis[k + 1]))
        assert np.linalg.norm(num - basis[k + 1]) <= GATE_DERIV * scale


def test_family_spd_and_independent_solve_paths(family, grid):
    """F(λ) SPD + splu/np.linalg.solve 独立互证 + 残差判据（#118 裁判面）。"""
    for lam in (grid[0], grid[7], [0.5, 0.9]):
        m = family.system_matrix(lam)
        eig = np.linalg.eigvalsh(m)
        assert eig.min() > 0.0, f"λ={lam} 非正定 min_eig={eig.min()}"
        x_sp = family.solve(lam)
        x_dn = family.solve_dense(lam)
        assert np.linalg.norm(x_sp - x_dn) <= 1e-10
        resid = np.linalg.norm(m @ x_sp - family.rhs())
        assert resid <= 1e-10, f"λ={lam} solve resid={resid}"


def test_family_negative_cases(family):
    with pytest.raises(ValueError, match="长度"):
        family.system_matrix([0.5, 0.5, 0.5])
    with pytest.raises(ValueError, match="非有限"):
        family.system_matrix([float("nan"), 0.5])
    with pytest.raises(ValueError, match="n_grid"):
        AffineStampFamily(n_grid=1)
    with pytest.raises(ValueError, match="n_blocks"):
        AffineStampFamily(n_grid=4, n_blocks=0)
    with pytest.raises(ValueError, match="kappa_bg"):
        AffineStampFamily(n_grid=4, kappa_bg=0.0)


def test_physical_domain_flag(family):
    inside = [0.2, 0.2]
    assert family.physical_valid(inside)
    # 最小边电导含边界边（恒 κ_bg=1.0）与块内边（κ_bg+λ_k=1.2）→ min=1.0
    assert family.min_conductance(inside) == pytest.approx(1.0)
    outside = [-2.0, 0.5]
    assert not family.physical_valid(outside)
    assert family.min_conductance(outside) == pytest.approx(-1.0)


def test_default_lambda_grid_deterministic_and_validated():
    g1 = default_lambda_grid(BOUNDS, n_per_axis=5)
    g2 = default_lambda_grid(BOUNDS, n_per_axis=5)
    assert len(g1) == 25
    assert all(np.array_equal(a, b) for a, b in zip(g1, g2, strict=True))
    # 超额抽稀确定性：49 点抽到 32 且两次逐位一致
    g3 = default_lambda_grid(BOUNDS, n_per_axis=7, max_points=32)
    g4 = default_lambda_grid(BOUNDS, n_per_axis=7, max_points=32)
    assert len(g3) == 32 and len({tuple(r) for r in g3}) == 32
    assert all(np.array_equal(a, b) for a, b in zip(g3, g4, strict=True))
    with pytest.raises(ValueError, match="lam_bounds"):
        default_lambda_grid([(1.0, 0.2), (0.2, 1.0)], n_per_axis=3)
    with pytest.raises(ValueError, match="n_per_axis"):
        default_lambda_grid(BOUNDS, n_per_axis=1)


# ─── G2/G5 三档：data-free 收敛、共享表达、确定性 ────────────────────────────


def test_data_free_residual_descends(family, df_narrow):
    """验收①：代数一致性残差下降曲线（info 证据面）。"""
    curve = df_narrow._curve
    head, tail = curve[0], curve[-1]
    assert tail <= GATE_DF_FINAL, f"末残差 {tail} 超门 {GATE_DF_FINAL}"
    assert head >= GATE_DF_DESCEND * tail, \
        f"首末比 {head / tail:.2f} 不足 {GATE_DF_DESCEND}x"


def test_data_free_info_contract(family, df_narrow):
    p = StampInversePredictor(family, lam_bounds=BOUNDS, mode="data_free",
                              warm_epochs=200, distill_rounds=0,
                              record_every=100)
    info = p.fit()
    assert info["kind"] == "ngo_stamp_kernel"
    assert info["mode"] == "data_free"
    assert info["label_kind"] is None
    curve = info["consistency_residual_curve"]
    assert curve and info["consistency_residual_final"] == curve[-1]
    assert info["distill_taken"] == 0  # rounds=0 → 无蒸馏采纳


def test_data_free_ignores_labels_bitexact(family, grid, df_narrow):
    """data_free 档无解标签语义：传/不传 solution 逐位一致。"""
    p_lab = StampInversePredictor(family, lam_bounds=BOUNDS, mode="data_free")
    p_lab.fit([{"lam": lam, "solution": family.solve(lam)} for lam in grid])
    assert np.array_equal(p_lab.predict_a_hat([0.5, 0.7]),
                          df_narrow.predict_a_hat([0.5, 0.7]))


def test_supervised_tiers_label_rmse_and_semantics(family, grid):
    pm = StampInversePredictor(family, lam_bounds=BOUNDS, mode="model")
    info_m = pm.fit()
    assert info_m["label_kind"] == "a_hat"
    assert info_m["label_rmse_final"] <= 0.05
    pd_ = StampInversePredictor(family, lam_bounds=BOUNDS, mode="data")
    info_d = pd_.fit([{"lam": lam, "solution": family.solve(lam)} for lam in grid])
    assert info_d["label_kind"] == "solution"
    assert info_d["label_rmse_final"] <= 0.05
    with pytest.raises(ValueError, match="data 档须外给解标签"):
        StampInversePredictor(family, lam_bounds=BOUNDS,
                              mode="data").fit(None)
    with pytest.raises(ValueError, match="solution"):
        StampInversePredictor(family, lam_bounds=BOUNDS,
                              mode="data").fit([{"lam": [0.5, 0.5]}])


def test_three_tiers_share_expression(family, grid, df_narrow):
    """三档共享 Â 表达：同架构参数形状逐位一致 + 线性读出解估计契约。"""
    pm = StampInversePredictor(family, lam_bounds=BOUNDS, mode="model")
    pm.fit()
    pd_ = StampInversePredictor(family, lam_bounds=BOUNDS, mode="data")
    pd_.fit([{"lam": lam, "solution": family.solve(lam)} for lam in grid])
    sh = [tuple(p.shape) for p in pm._net._params]
    for other in (pd_._net, df_narrow._net):
        assert [tuple(p.shape) for p in other._params] == sh
    # 解估计 x̂=Â·b（线性读出按构造）与精确解同序（域内 sanity）
    x_true = family.solve([0.5, 0.5])
    x_est = df_narrow.solution_estimate([0.5, 0.5])
    assert np.linalg.norm(x_est - x_true) / np.linalg.norm(x_true) <= 0.2


def test_predictor_config_validation(family):
    with pytest.raises(ValueError, match="mode"):
        StampInversePredictor(family, lam_bounds=BOUNDS, mode="auto")
    with pytest.raises(ValueError, match="lam_bounds"):
        StampInversePredictor(family, lam_bounds=[(0.2, 1.0)], mode="model")
    with pytest.raises(ValueError, match="lr"):
        StampInversePredictor(family, lam_bounds=BOUNDS, lr=0.0)
    with pytest.raises(ValueError, match="hidden"):
        StampInversePredictor(family, lam_bounds=BOUNDS, hidden=0)
    p = StampInversePredictor(family, lam_bounds=BOUNDS)
    with pytest.raises(RuntimeError, match="先 fit"):
        p.predict_a_hat([0.5, 0.5])
    with pytest.raises(ValueError, match="物理域"):
        p.fit([{"lam": [-2.0, 0.5]}])


def test_predictor_determinism_reduced_budget(family, grid):
    """验收④：同 seed 逐位一致 / 异 seed 相异（小预算档，不触全局 RNG）。"""
    def make(seed):
        p = StampInversePredictor(family, lam_bounds=BOUNDS,
                                  mode="data_free", hidden=24, seed=seed,
                                  warm_epochs=600, distill_rounds=0,
                                  record_every=200)
        p.fit()
        return p

    a, b = make(123), make(123)
    assert np.array_equal(a.predict_a_hat([0.5, 0.7]),
                          b.predict_a_hat([0.5, 0.7]))
    c = make(456)
    assert not np.array_equal(a.predict_a_hat([0.5, 0.7]),
                              c.predict_a_hat([0.5, 0.7]))


# ─── G3 GMRES 预条件（论文 Table 4 形态） ────────────────────────────────────


def test_gmres_iteration_table_gate(family, df_narrow, grid):
    """验收②：无预条件 vs Â 右预条件——多数 λ 迭代减半（预声明门）。"""
    tab = gmres_iteration_table(family, df_narrow, grid, rtol=1e-8)
    sm = tab["summary"]
    assert sm["n_converged_both"] == sm["n_cases"] == 25
    assert sm["halved_fraction"] >= GATE_HALVED_FRAC, \
        f"减半占比 {sm['halved_fraction']} 超门 {GATE_HALVED_FRAC}"
    it0 = [r["iterations_unprecond"] for r in tab["rows"]]
    it1 = [r["iterations_precond"] for r in tab["rows"]]
    reduction = sum(it0) / sum(it1)
    assert reduction >= GATE_GMRES_REDUCTION, f"总缩减 {reduction:.2f}x"
    assert max(it1) <= GATE_IT1_MAX
    assert sm["max_spectral_radius"] <= GATE_RHO_MAX
    assert sm["warnings"] == []  # 健康档零 Neumann 警告


def test_gmres_precond_solution_accuracy(family, df_narrow, grid):
    tab = gmres_iteration_table(family, df_narrow, grid[:5], rtol=1e-8)
    for r in tab["rows"]:
        assert r["converged_precond"]
        assert r["residual_rel_precond"] <= 2e-8
        assert r["converged_unprecond"]


def test_gmres_table_deterministic(family, df_narrow, grid):
    t1 = gmres_iteration_table(family, df_narrow, grid[:5], rtol=1e-8)
    t2 = gmres_iteration_table(family, df_narrow, grid[:5], rtol=1e-8)
    for r1, r2 in zip(t1["rows"], t2["rows"], strict=True):
        assert r1["iterations_precond"] == r2["iterations_precond"]
        assert r1["iterations_unprecond"] == r2["iterations_unprecond"]
        assert r1["spectral_radius"] == r2["spectral_radius"]
        assert r1["residual_rel_precond"] == r2["residual_rel_precond"]


def test_spectral_radius_warning_negative_case(family):
    """验收⑤负例：Â=−I 桩 ρ(I−FÂ)=1+μ_max>1 → 显式 warning 不静默。"""

    class BadPredictor:
        def predict_a_hat(self, lam):
            return -np.eye(family.n)

    with pytest.warns(UserWarning, match="Neumann"):
        tab = gmres_iteration_table(family, BadPredictor(),
                                    [[0.5, 0.5], [0.3, 0.9]])
    assert tab["summary"]["warnings"]
    assert tab["summary"]["max_spectral_radius"] > 1.0
    with pytest.raises(ValueError, match="lam_list"):
        gmres_iteration_table(family, BadPredictor(), [])


def test_precond_operator_matches_a_hat(family, df_narrow):
    lam = [0.4, 0.8]
    mop = df_narrow.precond_operator(lam)
    v = np.linspace(-1.0, 1.0, family.n)
    assert np.allclose(mop @ v, df_narrow.predict_a_hat(lam) @ v, rtol=0,
                       atol=0)
    rho = df_narrow.neumann_spectral_radius(lam)
    assert 0.0 <= rho <= GATE_RHO_MAX


# ─── G4 OOD 基准（论文 Table 2 精神） ────────────────────────────────────────


def _poly2_ridge_ood(family, grid, ood_lams):
    """poly2 岭闭式黑箱基线（poly_ridge 形态；裸 numpy 独立实现——#118）。"""
    def z_of(lams):
        z = (np.asarray(lams) - np.array([0.6, 0.6])) / np.array([0.4, 0.4])
        return np.stack([np.concatenate([z_i, z_i * z_i, [z_i[0] * z_i[1]]])
                         for z_i in np.atleast_2d(z)])

    y = np.stack([family.solve(lam) for lam in grid])
    ztr = z_of(grid)
    w = np.linalg.solve(ztr.T @ ztr + 1e-6 * np.eye(ztr.shape[1]),
                        ztr.T @ y)
    errs = []
    for lam in ood_lams:
        xt = family.solve(lam)
        errs.append(float(np.linalg.norm((z_of(np.asarray([lam])) @ w)[0] - xt)
                          / np.linalg.norm(xt)))
    return max(errs)


def test_ood_gate_structure_beats_blackbox(family, df_wide, blackbox, grid):
    """验收③：结构先验分布外价值（宽覆盖 data-free vs 窄标签黑箱）。"""
    lam_in = grid[:5]
    lam_ood = [np.array([1.5, 1.5]), np.array([1.8, 0.6]),
               np.array([0.6, 1.8]), np.array([2.2, 2.2]),
               np.array([1.6, 2.4]), np.array([2.4, 1.6])]
    assert all(family.physical_valid(lam) for lam in lam_ood)
    tab = ood_error_table(family, df_wide, lam_in, lam_ood, blackbox=blackbox)
    sm = tab["summary"]
    st_ood = sm["structure"]["ood"]["max"]
    bb_ood = sm["blackbox"]["ood"]["max"]
    ridge_ood = _poly2_ridge_ood(family, grid, lam_ood)
    assert st_ood <= GATE_OOD_STRUCT, f"结构档 OOD {st_ood:.3f}"
    assert st_ood < bb_ood, f"结构 OOD {st_ood:.3f} 未胜黑箱 MLP {bb_ood:.3f}"
    assert st_ood < ridge_ood, \
        f"结构 OOD {st_ood:.3f} 未胜 poly2 岭 {ridge_ood:.3f}"
    st_deg = sm["structure"]["degradation_ood_over_in"]
    bb_deg = sm["blackbox"]["degradation_ood_over_in"]
    assert st_deg < GATE_OOD_DEG_STRUCT < bb_deg
    # 域内两面都收敛到合理精度（诚实面：黑箱域内更准，分布外才见结构价值）
    assert sm["blackbox"]["in"]["max"] <= 0.01
    assert sm["structure"]["in"]["max"] <= 0.3


def test_ood_table_validation(family, grid):
    p = StampInversePredictor(family, lam_bounds=BOUNDS, mode="model")
    with pytest.raises(RuntimeError, match="先 fit"):
        ood_error_table(family, p, grid[:2], grid[2:4])
    p.fit()
    with pytest.raises(ValueError, match="lam_in/lam_ood"):
        ood_error_table(family, p, [], grid[:2])


# ─── G7 零改动：注册表与 green_op 先例回归 ───────────────────────────────────


def test_surrogate_registry_untouched_and_green_op_intact(family, grid):
    """既有路径零改动：本模块不注册代理键；green_op 叠加先例回归钉。"""
    before = sorted(surrogate_registry.available())
    assert "green_op" in before and "green_stamp" not in before
    AffineStampFamily(n_grid=4)
    StampInversePredictor(family, lam_bounds=BOUNDS, mode="data_free")
    assert sorted(surrogate_registry.available()) == before
    # green_op 叠加先例回归钉（T-N23 契约零改动）
    from rfauto.optimization.surrogate.green_operator import (
        superpose,
        superposition_residual,
    )

    s = np.zeros((2, 2, 2), dtype=complex)
    s[:, 0, 0] = 0.5
    s[:, 1, 0] = 0.3
    s[:, 0, 1] = 0.3
    s[:, 1, 1] = -0.2
    a1 = np.array([1.0, -0.5])
    a2 = np.array([0.3, 0.8])
    lhs = superpose(s, a1 + a2)
    rhs = superpose(s, a1) + superpose(s, a2)
    assert np.allclose(lhs, rhs, atol=1e-15)
    assert superposition_residual(s, a1, a2)["residual_rel"] <= 1e-12
