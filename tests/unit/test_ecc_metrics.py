"""ME-21 ECC 双路径（方向图积分 × S 参数式）单测：解析锚 + 互证双态 + 守卫。

解析锚（#118 独立来源：闭式为手推积分，不经过被测实现）：
- 两元共线 cosθ 偶极（位置相位 e^{±j(x/2)cosθ}，x=kd，参考阵列原点）：
  ρ(x) = 3·[(x²−2)·sin x + 2x·cos x]/x³（∫₋₁¹u²e^{jxu}du/(2/3) 的闭式；
  小 x 展开 ρ = 1 − 3x²/10 + … 与逐项级数互核）；
  每端口积分模长² = 4π/3（∫∫cos²θ dΩ 手算值）。
- 半波偶极（cos(πcosθ/2)/sinθ 元子方向图）：积分模长² = 4π/D0，
  D0 = 1.642（Balanis 表 4.1 文献锚——第三方常数，独立于被测积分）。
- 无限耦合极限：同方向图 E2=E1 → corr=1；间距 → ∞：corr → 0（振荡
  相位消相干，Riemann-Lebesgue），闭式 x=50π 时 |ρ| ≈ 18/x² = 7.3e-4。

互证双态假设域（测试按双态钉，docstring 存档）：两物理口径假设不同
（方向图路径只认场叠加；S 路径假设无损互易+每口单模+共轭匹配端接），
故互证只承诺"弱耦合同量级、强耦合如实分歧"：
- 弱耦（t=0.1，现象学 S 模型 Γ=0.5 实同相；间距 λ）：cosθ 模型
  ecc_p = 9/(4π⁴) ≈ 0.02310 vs ecc_s = 4Γ²t²/(1−Γ²−t²)² ≈ 0.01826，
  diff ≈ 0.0048 → AGREE（tol=0.05 松界）；
- 强耦（t=0.5，间距 λ/2）：ecc_p = 36/π⁴ ≈ 0.3695 vs ecc_s = 1.0，
  diff ≈ 0.63 → DISAGREE 如实（不得凑绿，#122）。

S 式自检锚：两端口理想匹配无耦（S=0）→ ECC=0；完全反射对
（S11=S22=S12=S21=1/√2 同相，列功率和=1 → 辐射效率 0，公式 0/0 退化）
→ 按完全相关界截为 ECC=1 + degenerate 标志（#364④：0 值判据显式处理，
不靠 or 兜底）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.ecc_metrics import ecc_crosscheck, ecc_from_patterns, ecc_from_sparams

# ─── 构造器与独立手推闭式（#118：不 import 被测实现） ─────────────────────────


def _rho_closed_form(x: float) -> float:
    """两元共线 cosθ 偶极的解析相关系数（手推独立锚，见模块 docstring）。"""
    return 3.0 * ((x * x - 2.0) * np.sin(x) + 2.0 * x * np.cos(x)) / x**3


def _collinear_cos_fields(
    x: float, n_theta: int = 1801, n_phi: int = 72, closed_phi: bool = True
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """两元共线 cosθ 偶极复场：E1 = cosθ·e^{+j(x/2)cosθ}，E2 = 共轭相位。"""
    th = np.linspace(0.0, 180.0, n_theta)
    # 重复端点闭合环（closed）或 endpoint=False 满环（周期梯形分支）
    ph = np.linspace(0.0, 360.0, n_phi + 1) if closed_phi else np.linspace(
        0.0, 360.0, n_phi, endpoint=False
    )
    u = np.cos(np.deg2rad(th))
    env = u[:, None]
    pe = np.exp(1j * 0.5 * x * u)[:, None]
    e = np.empty((2, n_theta, ph.size), dtype=complex)
    e[0] = env * pe
    e[1] = env * np.conj(pe)
    return e, th, ph


def _halfwave_fields(
    x: float, n_theta: int = 1801, n_phi: int = 72
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """两元共线半波偶极复场：F(θ) = cos(πcosθ/2)/sinθ（极点取极限 0）。"""
    th = np.linspace(0.0, 180.0, n_theta)
    ph = np.linspace(0.0, 360.0, n_phi + 1)
    st = np.sin(np.deg2rad(th))
    u = np.cos(np.deg2rad(th))
    env = (np.cos(np.pi / 2.0 * u) / np.maximum(st, 1e-12))[:, None]
    pe = np.exp(1j * 0.5 * x * u)[:, None]
    e = np.empty((2, n_theta, ph.size), dtype=complex)
    e[0] = env * pe
    e[1] = env * np.conj(pe)
    return e, th, ph


def _s_model(gamma: float, t: float) -> np.ndarray:
    """现象学两端口 S 模型：S = [[Γ, t], [t, Γ]]（实同相，无损域 |Γ|²+|t|²<1）。"""
    return np.array([[gamma, t], [t, gamma]], dtype=complex)


# ─── 方向图路径：解析锚 ───────────────────────────────────────────────────────


@pytest.mark.parametrize("x", [2.0 * np.pi, 3.0 * np.pi, 5.5, 0.75])
def test_pattern_closed_form_correlation(x: float) -> None:
    """共线 cosθ 偶极：复相关系数逐点对拍手推闭式（观测残差 ~7e-7，梯形地板）。"""
    e, th, ph = _collinear_cos_fields(x)
    out = ecc_from_patterns(e, th, ph)
    corr = out["corr_matrix"][0, 1]
    assert abs(corr - _rho_closed_form(x)) < 1e-5
    assert out["ecc_matrix"][0, 1] == pytest.approx(abs(_rho_closed_form(x)) ** 2, abs=2e-5)


def test_pattern_integral_norm_hand_value() -> None:
    """归一诊断量：cosθ 模型积分模长² = 4π/3（手算值，独立于被测实现）。"""
    e, th, ph = _collinear_cos_fields(2.0 * np.pi)
    out = ecc_from_patterns(e, th, ph)
    assert out["integral_norms"][0] == pytest.approx(np.sqrt(4.0 * np.pi / 3.0), abs=1e-5)
    assert out["integral_norms"][1] == pytest.approx(np.sqrt(4.0 * np.pi / 3.0), abs=1e-5)


def test_pattern_open_phi_grid_same_anchor() -> None:
    """φ 轴 endpoint=False 满环采样（周期梯形分支）与重复端点闭合环同锚。"""
    e, th, ph = _collinear_cos_fields(2.0 * np.pi, closed_phi=False)
    out = ecc_from_patterns(e, th, ph)
    assert abs(out["corr_matrix"][0, 1] - _rho_closed_form(2.0 * np.pi)) < 1e-5


def test_pattern_far_spacing_ecc_near_zero() -> None:
    """共线远距（x=50π，"间距无限远"实用极限）：corr → 闭式 18/x² ≈ 7.3e-4，
    ECC ≈ 5.3e-7 → 实测 < 1e-6（任务锚 ECC_pattern → 0）。"""
    x = 50.0 * np.pi
    e, th, ph = _collinear_cos_fields(x, n_theta=8001, n_phi=36)
    out = ecc_from_patterns(e, th, ph)
    assert out["ecc_matrix"][0, 1] < 1e-6
    assert abs(out["corr_matrix"][0, 1] - _rho_closed_form(x)) < 1e-6


def test_pattern_identical_patterns_fully_correlated() -> None:
    """无限耦合极限：E2=E1（同方向图同相位参考）→ corr=1、ECC=1（1e-12 钉）。"""
    e, th, ph = _collinear_cos_fields(np.pi, n_theta=201, n_phi=36)
    e[1] = e[0]
    out = ecc_from_patterns(e, th, ph)
    assert abs(out["corr_matrix"][0, 1] - 1.0) <= 1e-12
    assert out["ecc_matrix"][0, 1] >= 1.0 - 1e-12


def test_pattern_diagonal_identity_and_bounds() -> None:
    """自相关对角恒等 1（rtol 1e-12 钉）+ ECC ∈ [0,1] + Hermitian 对称（逐位）。"""
    rng = np.random.default_rng(20260926)
    n_th, n_ph = 37, 61
    e = rng.normal(size=(5, n_th, n_ph)) + 1j * rng.normal(size=(5, n_th, n_ph))
    th = np.linspace(0.0, 180.0, n_th)
    ph = np.linspace(0.0, 360.0, n_ph, endpoint=False)
    out = ecc_from_patterns(e, th, ph)
    ecc = out["ecc_matrix"]
    assert np.abs(np.diag(out["corr_matrix"]) - 1.0).max() <= 1e-12
    assert np.array_equal(np.diag(ecc), np.ones(5))  # 裁剪后对角逐位 1
    assert np.array_equal(ecc, ecc.T)  # 实对称逐位
    assert bool(np.all(ecc >= 0.0)) and bool(np.all(ecc <= 1.0))


def test_pattern_dg_identity_exact() -> None:
    """DG = 10·log10(1−ECC) 逐位一致（同式重构）；ECC=1 → −3000 dB 哨兵。"""
    rng = np.random.default_rng(42)
    e = rng.normal(size=(3, 21, 25)) + 1j * rng.normal(size=(3, 21, 25))
    th = np.linspace(0.0, 180.0, 21)
    ph = np.linspace(0.0, 360.0, 25, endpoint=False)
    out = ecc_from_patterns(e, th, ph)
    expect_dg = 10.0 * np.log10(np.maximum(1.0 - out["ecc_matrix"], 1e-300))
    assert np.array_equal(out["dg_matrix"], expect_dg)
    e2, th2, ph2 = _collinear_cos_fields(np.pi, n_theta=201, n_phi=36)
    e2[1] = e2[0]
    out2 = ecc_from_patterns(e2, th2, ph2)
    assert out2["dg_matrix"][0, 1] < -2000.0  # 哨兵域（10·log10(1e-300) = −3000）


# ─── S 参数路径：自检锚 ───────────────────────────────────────────────────────


def test_sparams_matched_uncoupled_ecc_zero() -> None:
    """两端口理想匹配无耦合（S=0）→ ECC=0、DG=0、辐射效率损失=0。"""
    out = ecc_from_sparams(np.zeros((2, 2), dtype=complex))
    assert out["ecc"] == 0.0
    assert out["dg"] == 0.0
    assert np.array_equal(out["loss_budget"], np.ones(2))
    assert out["degenerate"] is False


def test_sparams_full_reflection_degenerate_ecc_one() -> None:
    """完全反射对（全元 1/√2 同相，列功率和=1 → 零辐射）：公式 0/0 退化，
    按完全相关界截为 ECC=1 + degenerate 标志 + 警告（判读走 loss_budget）。"""
    with pytest.warns(UserWarning, match="退化"):
        out = ecc_from_sparams(np.full((2, 2), 1.0 / np.sqrt(2.0), dtype=complex))
    assert out["ecc"] == 1.0
    assert out["degenerate"] is True
    assert bool(np.all(np.abs(out["loss_budget"]) <= 1e-12))
    assert out["dg"] < -2000.0  # 哨兵域


def test_sparams_two_port_scalar_matches_matrix() -> None:
    """n=2 标量便捷键 ecc/dg 与矩阵 [0,1] 元逐位一致。"""
    out = ecc_from_sparams(_s_model(0.5, 0.1))
    assert out["ecc"] == float(out["ecc_matrix"][0, 1])
    assert out["dg"] == float(out["dg_matrix"][0, 1])
    # Γ=0.5, t=0.1 手算：4Γ²t²/(1−Γ²−t²)² = 0.01/0.5476
    assert out["ecc"] == pytest.approx(4.0 * 0.25 * 0.01 / (1.0 - 0.25 - 0.01) ** 2, rel=1e-12)


def test_sparams_diagonal_identity_and_symmetry() -> None:
    """S 路径对角恒等 1（逐位）+ ECC 实对称（逐位）——互易对称 S。"""
    rng = np.random.default_rng(7)
    a = rng.normal(size=(4, 4)) + 1j * rng.normal(size=(4, 4))
    s = 0.1 * (a + a.T)  # 对称（互易）复 S，列功率 <1
    out = ecc_from_sparams(s)
    assert np.array_equal(np.diag(out["ecc_matrix"]), np.ones(4))
    assert np.array_equal(out["ecc_matrix"], out["ecc_matrix"].T)


def test_sparams_blanch_formula_hand_value() -> None:
    """Blanch 双端口印刷式手算值核对（Γ=0.3, t=0.2 实同相）。"""
    gamma, t = 0.3, 0.2
    s = _s_model(gamma, t)
    num = abs(np.conj(s[0, 0]) * s[0, 1] + np.conj(s[1, 0]) * s[1, 1]) ** 2
    den = (1.0 - abs(s[0, 0]) ** 2 - abs(s[1, 0]) ** 2) * (
        1.0 - abs(s[1, 1]) ** 2 - abs(s[0, 1]) ** 2
    )
    out = ecc_from_sparams(s)
    assert out["ecc"] == pytest.approx(num / den, rel=1e-12)


# ─── 互证双态（AGREE / DISAGREE） ─────────────────────────────────────────────


def test_crosscheck_two_state_weak_agree_strong_disagree() -> None:
    """互证双态（假设域存档见模块 docstring）：弱耦（t=0.1, 间距 λ）
    diff≈0.0048 → AGREE；强耦（t=0.5, 间距 λ/2）diff≈0.63 → DISAGREE 如实。"""
    # 弱耦：cosθ 方图路径 x=2π（d=λ）
    e, th, ph = _collinear_cos_fields(2.0 * np.pi)
    ecc_p_weak = float(ecc_from_patterns(e, th, ph)["ecc_matrix"][0, 1])
    ecc_s_weak = float(ecc_from_sparams(_s_model(0.5, 0.1))["ecc"])
    assert ecc_p_weak == pytest.approx(9.0 / (4.0 * np.pi**4), abs=2e-5)
    cc = ecc_crosscheck(ecc_p_weak, ecc_s_weak)
    assert cc["verdict"] == "AGREE"
    assert cc["abs_diff"] <= 0.01
    # 强耦：x=π（d=λ/2）
    e, th, ph = _collinear_cos_fields(np.pi)
    ecc_p_strong = float(ecc_from_patterns(e, th, ph)["ecc_matrix"][0, 1])
    ecc_s_strong = float(ecc_from_sparams(_s_model(0.5, 0.5))["ecc"])
    assert ecc_p_strong == pytest.approx(36.0 / np.pi**4, abs=2e-5)
    assert ecc_s_strong == pytest.approx(1.0, abs=1e-12)
    cc2 = ecc_crosscheck(ecc_p_strong, ecc_s_strong)
    assert cc2["verdict"] == "DISAGREE"


def test_crosscheck_halfwave_agree_with_norm_anchor() -> None:
    """半波偶极阵（任务互证锚形态）：norm² = 4π/D0（D0=1.642 文献锚，
    观测 rel 3.3e-4）；弱耦（t=0.1，间距 λ）AGREE（观测 diff 0.0151）；
    λ/2 强耦 DISAGREE 如实。"""
    d0 = 1.642
    e, th, ph = _halfwave_fields(2.0 * np.pi)
    out = ecc_from_patterns(e, th, ph)
    assert out["integral_norms"][0] == pytest.approx(
        np.sqrt(4.0 * np.pi / d0), rel=2e-3
    )
    ecc_p = float(out["ecc_matrix"][0, 1])
    ecc_s = float(ecc_from_sparams(_s_model(0.5, 0.1))["ecc"])
    cc = ecc_crosscheck(ecc_p, ecc_s)
    assert cc["verdict"] == "AGREE"
    assert cc["abs_diff"] <= 0.03
    e2, th2, ph2 = _halfwave_fields(np.pi)
    ecc_p2 = float(ecc_from_patterns(e2, th2, ph2)["ecc_matrix"][0, 1])
    cc2 = ecc_crosscheck(ecc_p2, float(ecc_from_sparams(_s_model(0.5, 0.5))["ecc"]))
    assert cc2["verdict"] == "DISAGREE"


def test_crosscheck_identity_and_echo() -> None:
    """同值互证 AGREE、diff=0、tol/输入回显。"""
    cc = ecc_crosscheck(0.3, 0.3, tol=0.01)
    assert cc["verdict"] == "AGREE"
    assert cc["abs_diff"] == 0.0
    assert cc["tol"] == 0.01
    assert cc["ecc_pattern"] == 0.3 and cc["ecc_sparams"] == 0.3


# ─── 守卫 ─────────────────────────────────────────────────────────────────────


def test_nonreciprocal_sparams_warns_but_computes() -> None:
    """非互易 S（|S12|=0.3 vs |S21|=0.1，相对偏差 67%）：警告注记不阻断。"""
    s = np.array([[0.0, 0.3], [0.1, 0.0]], dtype=complex)
    with pytest.warns(UserWarning, match="互易"):
        out = ecc_from_sparams(s)
    assert 0.0 <= out["ecc"] <= 1.0


def test_pattern_guards() -> None:
    """方向图路径守卫：n<2 / 维度 / NaN / bool / 零方向图 / 角度轴非法。"""
    th = np.linspace(0.0, 180.0, 11)
    ph = np.linspace(0.0, 360.0, 13, endpoint=False)
    with pytest.raises(ValueError, match="≥2 个端口"):
        ecc_from_patterns(np.ones((1, 11, 13), dtype=complex), th, ph)
    with pytest.raises(ValueError, match="三维"):
        ecc_from_patterns(np.ones((2, 11), dtype=complex), th, ph)
    bad = np.ones((2, 11, 13), dtype=complex)
    bad[0, 3, 4] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        ecc_from_patterns(bad, th, ph)
    with pytest.raises(ValueError, match="bool"):
        ecc_from_patterns(np.zeros((2, 11, 13), dtype=bool), th, ph)
    zero = np.ones((2, 11, 13), dtype=complex)
    zero[1] = 0.0
    with pytest.raises(ValueError, match="零方向图"):
        ecc_from_patterns(zero, th, ph)
    e = np.ones((2, 11, 13), dtype=complex)
    with pytest.raises(ValueError, match="形状"):
        ecc_from_patterns(e, th, np.linspace(0.0, 360.0, 9, endpoint=False))
    with pytest.raises(ValueError, match="升序"):
        ecc_from_patterns(e, np.linspace(180.0, 0.0, 11), ph)
    with pytest.raises(ValueError, match="NaN"):
        ecc_from_patterns(e, np.full(11, np.nan), ph)
    with pytest.raises(ValueError, match="180"):
        ecc_from_patterns(e, np.linspace(-10.0, 190.0, 11), ph)
    with pytest.raises(ValueError, match="2 个采样点"):
        ecc_from_patterns(np.ones((2, 1, 13), dtype=complex), np.array([0.0]), ph)


def test_sparams_guards() -> None:
    """S 路径守卫：n<2 / 非方阵 / NaN / bool / 列功率>1（非无损域）。"""
    with pytest.raises(ValueError, match="≥2 个端口"):
        ecc_from_sparams(np.array([[0.5]], dtype=complex))
    with pytest.raises(ValueError, match="方阵"):
        ecc_from_sparams(np.ones((2, 3), dtype=complex))
    with pytest.raises(ValueError, match="NaN"):
        ecc_from_sparams(np.array([[0.0, np.nan], [0.0, 0.0]], dtype=complex))
    with pytest.raises(ValueError, match="bool"):
        ecc_from_sparams(np.eye(2, dtype=bool))
    with pytest.raises(ValueError, match="无损"):
        ecc_from_sparams(np.array([[1.2, 0.0], [0.0, 0.0]], dtype=complex))


def test_crosscheck_guards() -> None:
    """互证守卫：bool / 非数值 / NaN / 越界 / 非正 tol。"""
    with pytest.raises(ValueError, match="bool"):
        ecc_crosscheck(True, 0.3)
    with pytest.raises(ValueError, match="数值标量"):
        ecc_crosscheck("0.3", 0.3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="非有限"):
        ecc_crosscheck(float("nan"), 0.3)
    with pytest.raises(ValueError, match="超出"):
        ecc_crosscheck(1.5, 0.3)
    with pytest.raises(ValueError, match="tol"):
        ecc_crosscheck(0.3, 0.3, tol=0.0)
    with pytest.raises(ValueError, match="tol"):
        ecc_crosscheck(0.3, 0.3, tol=-0.1)
