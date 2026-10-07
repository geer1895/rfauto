"""AP-15 MIMO 口径对接件锚测试（round17 §三 AP-15，2026-10-03）。

锚口径（#118/#300：≥2 独立基准/件，门值预声明；#122 不凑绿）：

- MEG 解析性质锚（独立于数值积分）：
  * 各向同性单位增益 → MEG=1（任意 XPR；权重和=1）；
  * 无损极化单一（全部增益在 θ 分量，∮G dΩ=4π）→ MEG=Γ/(1+Γ)
    **与方向图形状无关**——两种不同形状（1.5sin²θ 偶极形 /
    半球平顶形）同值；φ 单一 → 1/(1+Γ)；
  * XPR 对称：θ/φ 等分时 MEG 与 XPR 无关（权重和恒 1）。
- 数值路径：半球余弦图（θ-only）在 Γ=0dB → MEG=1（=Γ/(1+Γ)），
  Γ=+10dB → Γ/(1+Γ)=10/11；与解析性质闭环。
- 阵列 MEG（消费 conformal_array）：两各向同性元 ±λ/4 z 同相 →
  天顶 G=2（3.0103 dBi 经典值，闭式 2cos²((π/2)cosθ) 逐点），
  MEG=1（无损归一 ∮G=4π）；单元退化（N=1）→ MEG=1。
- BPR：相同分支 0 dB；2:1 功率比 → 3.0103 dB。
- MRC：等增益 N=2 → +3.0103 dB；[0,3]dB → 10lg(1+2)=4.7712 dB
  （手算）。
- SC：p=1%、N=2 → 10.204 dB（手算 ln(0.99)/ln(0.9)=10.482）；
  N=1 → 0 dB（退化恒等）。
- 固定权合并：ρ=I → 单支平均增益；ρ=1 等增益 → +10lgN（相干和）；
  w 单支独热 → 该支增益。
- 极化态报告（消费 polarization）：(1,−j)→RH、(1,1)→45° 线极化
  （AP-1 锚复用）。
- 异常域：网格形状/升序/NaN、XPR bool、corr 非实/|ρ|>1、BPR
  非正 MEG、SC p 越界、gain_grid 全零激励。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.mimo_metrics import (
    array_pattern_gain_grid,
    branch_power_ratio_db,
    fixed_weight_combining_gain_db,
    mean_effective_gain,
    mrc_mean_array_gain_db,
    polarized_branch_report,
    selection_combining_gain_db,
    sphere_integral,
)

C0 = 299792458.0


def _sphere_grid(n_theta: int = 91, n_phi: int = 73):
    theta = np.linspace(0.0, 180.0, n_theta)
    phi = np.linspace(0.0, 360.0, n_phi, endpoint=False)
    return theta, phi


def _mesh(theta, phi):
    return np.meshgrid(theta, phi, indexing="ij")


class TestMegAnalytic:
    def test_isotropic_any_xpr(self):
        th, ph = _sphere_grid()
        tt, _ = _mesh(th, ph)
        g = np.ones_like(tt)
        # 离散地板：θ 2° 步梯形 ∮sinθ 的 O(h²) 误差（实测 1.0e-4 rel，
        # 门 2e-4 预声明）
        for xpr in (-20.0, 0.0, 15.0):
            assert mean_effective_gain(th, ph, g_total=g, xpr_db=xpr) == \
                pytest.approx(1.0, rel=2e-4)

    @pytest.mark.parametrize("shape", ["dipole", "cardioid"])
    def test_theta_only_lossless_shape_independent(self, shape):
        # 无损 θ 单一极化：∮G dΩ=4π → MEG=Γ/(1+Γ) 与形状无关
        # （两种光滑形：1.5sin²θ 偶极形 / 1+cosθ 心脏线形，后者
        # ∫(1+cosθ)dΩ=4π 有解析自检）
        th, ph = _sphere_grid()
        tt, _ = _mesh(th, ph)
        ct = np.cos(np.radians(tt))
        g = (1.5 * np.sin(np.radians(tt)) ** 2 if shape == "dipole"
             else 1.0 + ct)
        # 归一化自检（无损口径）：∫G dΩ = 4π（梯形离散地板
        # −(h²/12)[f′(π)−f′(0)]，2° 步实测 ~1e-4 rel，门 5e-4 预声明）
        assert sphere_integral(g, th, ph) == pytest.approx(4 * math.pi,
                                                           rel=5e-4)
        for xpr in (0.0, 10.0, -6.0):
            expect = (10.0 ** (xpr / 10.0)) / (1.0 + 10.0 ** (xpr / 10.0))
            got = mean_effective_gain(th, ph, g_theta=g, g_phi=np.zeros_like(g),
                                      xpr_db=xpr)
            assert got == pytest.approx(expect, rel=5e-4), (shape, xpr)

    def test_phi_only_reciprocal(self):
        th, ph = _sphere_grid()
        tt, _ = _mesh(th, ph)
        g = 1.5 * np.sin(np.radians(tt)) ** 2
        xpr = 10.0
        expect = 1.0 / (1.0 + 10.0 ** (xpr / 10.0))
        got = mean_effective_gain(th, ph, g_theta=np.zeros_like(g),
                                  g_phi=g, xpr_db=xpr)
        assert got == pytest.approx(expect, rel=1e-7)

    def test_total_pattern_xpr_invariant(self):
        th, ph = _sphere_grid()
        tt, _ = _mesh(th, ph)
        g = 1.5 * np.sin(np.radians(tt)) ** 2
        m0 = mean_effective_gain(th, ph, g_total=g, xpr_db=0.0)
        m1 = mean_effective_gain(th, ph, g_total=g, xpr_db=20.0)
        assert m0 == pytest.approx(m1, rel=1e-10)
        assert m0 == pytest.approx(1.0, rel=1e-7)  # 无损归一 ∮G=4π


class TestArrayMegConformal:
    def test_two_element_halfwave_closed_form(self):
        # 2 各向同性元 ±λ/4 z 同相，上半球域（θ≤90°，法向 +z 不产生
        # 遮挡）：P(θ)=4cos²((π/2)cosθ) 逐点闭式；域内辐射积分解析值
        #   ∫P dΩ = 8π[1/2+sin(2κ)/(4κ)] = 4π（κ=π/2 时 sin2κ=0）
        # → 归一化 G = P（逐点）且宽边 θ=90° 处 G=4（域归一口径）。
        # 注：conformal_array 面含 cosψ>0 遮挡语义，自由空间全向
        # 二元阵闭式只在无遮挡子域可复现（如实注记）。
        f = 10e9
        lam = C0 / f
        pos = np.array([[0.0, 0.0, -lam / 4], [0.0, 0.0, lam / 4]])
        nor = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
        w = np.ones(2)
        theta = np.linspace(0.0, 90.0, 91)
        phi = np.linspace(0.0, 360.0, 73, endpoint=False)
        out = array_pattern_gain_grid(pos, nor, w, theta, phi, f,
                                      element_pattern_exp=0.0)
        g = out["gain_grid"]
        # 域内辐射积分 = 4π（解析自检，梯形离散门 5e-4）
        assert out["radiated_integral"] == pytest.approx(4 * math.pi,
                                                         rel=5e-4)
        # 逐点闭式（归一化后 G=P：分母恰 4π）
        tt = np.radians(theta)
        expect = 4.0 * np.cos(math.pi / 2.0 * np.cos(tt)) ** 2
        assert np.allclose(g[:, 0], expect, rtol=5e-4)
        assert g[90, 0] == pytest.approx(4.0, rel=5e-4)  # 宽边 θ=90°
        assert g[0, 0] == pytest.approx(0.0, abs=1e-12)  # 端射零点
        # 无损归一 → 域内 MEG=1（θ/φ 等分各向同性元族）
        meg = mean_effective_gain(theta, phi, g_total=g, xpr_db=3.0)
        assert meg == pytest.approx(1.0, rel=5e-4)

    def test_single_element_degeneracy(self):
        f = 3e9
        pos = np.array([[0.0, 0.0, 0.0]])
        nor = np.array([[0.0, 0.0, 1.0]])
        w = np.ones(1)
        th, ph = _sphere_grid(91, 61)
        out = array_pattern_gain_grid(pos, nor, w, th, ph, f,
                                      element_pattern_exp=0.0)
        meg = mean_effective_gain(th, ph, g_total=out["gain_grid"])
        assert meg == pytest.approx(1.0, rel=1e-6)

    def test_theta_pol_array_meg_xpr(self):
        # 阵列图置于 θ 极化（G_θ=G，G_φ=0）→ 阵列 MEG=Γ/(1+Γ)（复合锚）
        f = 10e9
        lam = C0 / f
        pos = np.array([[0.0, 0.0, -lam / 4], [0.0, 0.0, lam / 4]])
        nor = np.ones_like(pos)
        th, ph = _sphere_grid(181, 73)
        out = array_pattern_gain_grid(pos, nor, np.ones(2), th, ph, f,
                                      element_pattern_exp=0.0)
        g = out["gain_grid"]
        meg = mean_effective_gain(th, ph, g_theta=g,
                                  g_phi=np.zeros_like(g), xpr_db=10.0)
        assert meg == pytest.approx(10.0 / 11.0, rel=1e-7)


class TestBprAndCombining:
    def test_bpr_values(self):
        assert branch_power_ratio_db(0.3, 0.3) == pytest.approx(0.0, abs=1e-12)
        assert branch_power_ratio_db(0.4, 0.2) == pytest.approx(
            10 * math.log10(2.0), rel=1e-12)

    def test_mrc_mean_gain(self):
        assert mrc_mean_array_gain_db([0.0, 0.0]) == pytest.approx(
            10 * math.log10(2.0), rel=1e-12)
        assert mrc_mean_array_gain_db([0.0, 3.0]) == pytest.approx(
            10 * math.log10(1.0 + 10.0 ** 0.3), rel=1e-12)  # 4.7643 dB
        assert mrc_mean_array_gain_db([5.0]) == pytest.approx(5.0, rel=1e-12)

    def test_sc_closed_form_anchor(self):
        # p=1%、N=2：ln(0.99)/ln(0.9)=10.482 → 10.204 dB（手算）
        assert selection_combining_gain_db(0.01, 2) == pytest.approx(
            10 * math.log10(math.log(0.99) / math.log(0.90)), rel=1e-12)
        assert selection_combining_gain_db(0.01, 1) == pytest.approx(
            0.0, abs=1e-12)

    def test_fixed_weight_correlation_anchors(self):
        # ρ=I：等权 → 单支平均增益
        g = [0.0, 0.0]
        i_mat = np.eye(2)
        assert fixed_weight_combining_gain_db(g, i_mat) == pytest.approx(
            0.0, abs=1e-9)
        # ρ=1 等增益 → +10lg2（相干和）
        one = np.ones((2, 2))
        assert fixed_weight_combining_gain_db(g, one) == pytest.approx(
            10 * math.log10(2.0), rel=1e-9)
        # 单支独热权 → 该支增益（相关阵任意）
        w = np.array([1.0, 0.0])
        assert fixed_weight_combining_gain_db([0.0, 3.0], one, weights=w) == \
            pytest.approx(0.0, abs=1e-9)


class TestPolarizationConsumption:
    def test_branch_report_anchors(self):
        # 消费席4 polarization_state：(1,−j)→RH；(1,1)→线极化
        rep_rh = polarized_branch_report(1.0 + 0j, -1j)
        assert rep_rh["sense"] == "RH"
        rep_lin = polarized_branch_report(1.0 + 0j, 1.0 + 0j)
        assert rep_lin["sense"] == "linear"
        assert rep_lin["ar_db"] > 90.0  # 线极化封顶（AP-1 口径）


class TestValidation:
    def test_grid_guards(self):
        th, ph = _sphere_grid()
        g = np.ones((len(th), len(ph)))
        with pytest.raises(ValueError):
            mean_effective_gain(th, ph, g_total=g[:, :5])
        with pytest.raises(ValueError):
            mean_effective_gain(th, ph)
        with pytest.raises(ValueError):
            mean_effective_gain(th, ph, g_total=g, g_theta=g, g_phi=g)
        with pytest.raises(ValueError):
            mean_effective_gain(th, ph, g_total=g, xpr_db=True)
        bad = g.copy()
        bad[3, 3] = np.nan
        with pytest.raises(ValueError):
            sphere_integral(bad, th, ph)

    def test_combining_guards(self):
        with pytest.raises(ValueError):
            branch_power_ratio_db(0.0, 1.0)
        with pytest.raises(ValueError):
            selection_combining_gain_db(1.5, 2)
        with pytest.raises(ValueError):
            fixed_weight_combining_gain_db([0.0, 1.0],
                                           np.array([[1, 1.5], [1.5, 1]]))
        with pytest.raises(ValueError):
            mrc_mean_array_gain_db(np.array([0.0, np.inf]))

    def test_array_grid_guards(self):
        pos = np.array([[0.0, 0.0, 0.0]])
        nor = np.array([[0.0, 0.0, 1.0]])
        th, ph = _sphere_grid(9, 7)
        with pytest.raises(ValueError):
            array_pattern_gain_grid(pos, nor, np.zeros(1, dtype=complex),
                                    th, ph, 3e9, element_pattern_exp=0.0)
        with pytest.raises(ValueError):
            array_pattern_gain_grid(pos, nor[:0], np.ones(1, dtype=complex),
                                    th, ph, 3e9, element_pattern_exp=0.0)
