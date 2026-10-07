"""MT-3 MTL 模分解/串扰产侧锚树（core/mtl_modes.py，round17 :29）。

裁判面（#118：每面 ≥2 独立基准）：
- 模分解 vs even/odd 闭式：对称双线 γ_m=jω√(L_eC_e)/jω√(L_oC_o)、
  T 列 ∥ [1,1]/[1,−1]、Z_c 模特征值=Z_e/Z_o 闭式（1e-10）；
- 独立精确链解：scipy.linalg.expm 矩阵指数传播子+边界条件 4x4 线性
  系统（与弱耦闭式完全不同的数值路径）→ 弱耦域 NEXT/FEXT 对拍；
- 均匀介质恒等式：L·C=μεI 残差 ~1e-14 + FEXT=0（精确链解 1e-12 级
  + 闭式 fext_cancelled）；
- mixed_mode_metrics 对拍（service 直调，验收口径）：匹配耦合线 4 端
  口 → sdd21/scc21=0dB（模速对拍）、scd21/sdc21=−inf（对称零转换）；
- skew 指标 + 域守卫负例。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.linalg import expm

from rfauto.core.mtl_modes import (
    mtl_crosstalk_coeffs,
    mtl_homogeneous_residual,
    mtl_modal_decomposition,
    mtl_mode_skew,
    symmetric_pair_even_odd,
    symmetric_pair_pul,
)

FREQ_HZ = 2.0e9
L_S = 400e-9
L_M = 40e-9
C_G = 80e-12
C_M = 6e-12
Z0 = 50.0
# 串扰基准线长：电短判据 βℓ≈0.074≪1（50mm 在 2GHz 为 0.59λ，电短闭式
# 不适用——首轮基准实测踩此坑，弱耦闭式只在电短域对拍）
LENGTH = 1e-3


def _pul():
    return symmetric_pair_pul(L_S, L_M, C_G, C_M)


def _exact_chain_solution(freq_hz: float, l_mat: np.ndarray,
                          c_mat: np.ndarray, z0: float,
                          length_m: float) -> dict[str, complex]:
    """独立精确解：[V;I](ℓ)=exp(−Aℓ)·[V;I](0)，A=[[0,Z],[Y,0]]。

    边界：z=0 线 1 Thevenin V₁+Z₀I₁=V_S、线 2 V₂+Z₀I₂=0；
    z=ℓ 双线负载 V−Z₀I=0。4x4 线性系统解 (V(0),I(0)) →
    {vne=V₂(0), vfe=V₂(ℓ)}。零近似（无弱耦/电短假设）。
    """
    w = 2.0 * math.pi * freq_hz
    z_mat = 1j * w * l_mat
    y_mat = 1j * w * c_mat
    a_mat = np.block([[np.zeros((2, 2)), z_mat], [y_mat, np.zeros((2, 2))]])
    prop = expm(-a_mat * length_m)
    # 未知 x=[V1(0),V2(0),I1(0),I2(0)]
    am = np.zeros((4, 4), dtype=complex)
    bm = np.zeros(4, dtype=complex)
    # z=0：V1+Z0·I1=V_S；V2+Z0·I2=0
    am[0, 0] = 1.0
    am[0, 2] = z0
    bm[0] = 1.0  # V_S=1
    am[1, 1] = 1.0
    am[1, 3] = z0
    # z=ℓ：prop·x 给 [V(ℓ);I(ℓ)]；V_k(ℓ)−Z0·I_k(ℓ)=0
    pvh = prop[:2, :]
    pih = prop[2:, :]
    am[2, :] = pvh[0, :] - z0 * pih[0, :]
    am[3, :] = pvh[1, :] - z0 * pih[1, :]
    x = np.linalg.solve(am, bm)
    v_end = pvh @ x
    return {"vne": complex(x[1]), "vfe": complex(v_end[1])}


class TestModalDecomposition:
    def test_gamma_matches_even_odd_closed(self):
        l_mat, c_mat = _pul()
        eo = symmetric_pair_even_odd(L_S, L_M, C_G, C_M)
        rep = mtl_modal_decomposition(l_mat, c_mat, FREQ_HZ)
        beta = np.sort(rep["beta"])
        w = 2.0 * math.pi * FREQ_HZ
        expect = np.sort([w * eo["beta_over_omega_even"],
                          w * eo["beta_over_omega_odd"]])
        assert np.allclose(beta, expect, rtol=1e-10)
        assert np.allclose(rep["gamma"].real, 0.0, atol=1e-12)

    def test_mode_vectors_even_odd(self):
        l_mat, c_mat = _pul()
        rep = mtl_modal_decomposition(l_mat, c_mat, FREQ_HZ)
        t = rep["t_v"]
        even = np.array([1.0, 1.0])
        odd = np.array([1.0, -1.0])
        for col in range(2):
            v = t[:, col]
            cos_e = abs(v @ even) / (np.linalg.norm(v) * math.sqrt(2.0))
            cos_o = abs(v @ odd) / (np.linalg.norm(v) * math.sqrt(2.0))
            assert max(cos_e, cos_o) == pytest.approx(1.0, abs=1e-12)

    def test_zc_mode_impedances_closed(self):
        l_mat, c_mat = _pul()
        eo = symmetric_pair_even_odd(L_S, L_M, C_G, C_M)
        rep = mtl_modal_decomposition(l_mat, c_mat, FREQ_HZ)
        mode_z = np.sort(rep["mode_impedances"])
        expect = np.sort([eo["z_even_ohm"], eo["z_odd_ohm"]])
        assert np.allclose(mode_z, expect, rtol=1e-10)

    def test_zy_eigenvalues_consistency(self):
        l_mat, c_mat = _pul()
        rep = mtl_modal_decomposition(l_mat, c_mat, FREQ_HZ)
        w = 2.0 * math.pi * FREQ_HZ
        # γ²=−ω²·λ(LC)
        lam_lc = np.sort(np.linalg.eigvals(l_mat @ c_mat).real)
        got = np.sort(rep["zy_eigenvalues"].real)
        assert np.allclose(got, np.sort(-w * w * lam_lc), rtol=1e-10)

    def test_guard_bad_inputs(self):
        l_mat, c_mat = _pul()
        with pytest.raises(ValueError):
            mtl_modal_decomposition(l_mat, c_mat, -1.0)
        with pytest.raises(ValueError):
            mtl_modal_decomposition(np.eye(3), c_mat, FREQ_HZ)


class TestEvenOddClosed:
    def test_capacitance_convention(self):
        # even：无间隙场 → C_e=C_g（Maxwell 对角 C_g+C_m、非对角 −C_m）
        eo = symmetric_pair_even_odd(L_S, L_M, C_G, C_M)
        assert eo["c_even_f"] == pytest.approx(C_G, rel=1e-15)
        assert eo["c_odd_f"] == pytest.approx(C_G + 2.0 * C_M, rel=1e-15)
        assert eo["l_even_h"] == pytest.approx(L_S + L_M, rel=1e-15)
        assert eo["l_odd_h"] == pytest.approx(L_S - L_M, rel=1e-15)

    def test_guard_indefinite_l(self):
        with pytest.raises(ValueError):
            symmetric_pair_pul(1e-9, 2e-9, 80e-12, 6e-12)


class TestHomogeneousIdentity:
    def test_residual_near_zero(self):
        # 均匀介质构造：L=μ0ε0εr·C⁻¹ → L·C=μ0ε0εr·I 精确
        eps_r = 4.4
        mu0 = 4e-7 * math.pi
        eps0 = 8.854187817e-12
        c_mat, _ = _pul()
        c_mat = c_mat[::-1, ::-1] * 1.0  # 保持原矩阵（防呆，不改变值）
        l_mat = mu0 * eps0 * eps_r * np.linalg.inv(c_mat)
        rep = mtl_homogeneous_residual(l_mat, c_mat, eps_r)
        assert rep["residual_max_rel"] <= 1e-12
        assert rep["residual_offdiag_rel"] <= 1e-12

    def test_residual_flagged_for_inhomogeneous(self):
        l_mat, c_mat = _pul()
        rep = mtl_homogeneous_residual(l_mat, c_mat, 4.4)
        assert rep["residual_max_rel"] > 1e-3  # 非均匀构造如实报告大残差


class TestCrosstalk:
    def test_weak_coupling_vs_exact_chain(self):
        """独立精确链解（expm+边界条件）对拍弱耦闭式（电短+弱耦域）。

        终接取耦合器惯例 Z₀=√(Z_eZ_o)（弱耦下≈单线阻抗）；闭式 V_S
        语义=激励线**行波幅**=源电压一半（匹配分压），故 exact(V_S=
        1V Thevenin) 对拍 closed/2。线长取 0.1mm（βℓ≈0.0074）：电短
        展开首截断项 −jβℓ（实测 ℓ=1mm 时 7% 实部）压到 0.75% 以内。
        """
        c_m_weak = 0.3e-12  # ≈0.4% C_g：弱耦域
        length = 1e-4
        l_mat, c_mat = symmetric_pair_pul(L_S, L_M, C_G, c_m_weak)
        eo = symmetric_pair_even_odd(L_S, L_M, C_G, c_m_weak)
        z0_pair = math.sqrt(eo["z_even_ohm"] * eo["z_odd_ohm"])
        exact = _exact_chain_solution(FREQ_HZ, l_mat, c_mat, z0_pair, length)
        closed = mtl_crosstalk_coeffs(L_M, c_m_weak, z0_pair, FREQ_HZ,
                                      length)
        assert closed["vne_over_vs"] / 2.0 == pytest.approx(
            exact["vne"], rel=0.02)
        assert closed["vfe_over_vs"] / 2.0 == pytest.approx(
            exact["vfe"], rel=0.02)

    def test_fext_zero_homogeneous_exact(self):
        """均匀介质 FEXT=0：三阻抗代数恒等 + 精确链解机器零。

        均匀介质 L=με C⁻¹ 下：√(L_m/C_m)=√(με/det C)=√(Z_eZ_o) 三式
        逐位恒等（解析恒等式的数值验证）；终接取该值 → 精确链解
        |V_FE|/|V_NE|≈2e-17（机器零）+ 闭式 fext_cancelled 恒真。
        """
        eps_r = 4.4
        mu0 = 4e-7 * math.pi
        eps0 = 8.854187817e-12
        _, c_mat = _pul()
        l_mat = mu0 * eps0 * eps_r * np.linalg.inv(c_mat)
        l_m_h = float(l_mat[0, 1])
        c_m_f = float(-c_mat[0, 1])
        eo = symmetric_pair_even_odd(float(l_mat[0, 0]), l_m_h,
                                     float(c_mat[0, 0] + c_mat[0, 1]),
                                     c_m_f)
        z_pair = math.sqrt(eo["z_even_ohm"] * eo["z_odd_ohm"])
        # 三式恒等（#118：代数恒等式数值验证）
        assert math.sqrt(l_m_h / c_m_f) == pytest.approx(z_pair, rel=1e-12)
        det = float(np.linalg.det(c_mat))
        assert math.sqrt(mu0 * eps0 * eps_r / det) == pytest.approx(
            z_pair, rel=1e-12)
        exact = _exact_chain_solution(FREQ_HZ, l_mat, c_mat, z_pair, LENGTH)
        assert abs(exact["vfe"]) <= 1e-12 * abs(exact["vne"])
        closed = mtl_crosstalk_coeffs(l_m_h, c_m_f, z_pair, FREQ_HZ, LENGTH)
        assert closed["fext_cancelled"] is True
        # 浮点残差 ~1e-19（闭式分子 Z₀C_m−L_m/Z₀ 非逐位零，量级守卫）
        assert abs(closed["vfe_over_vs"]) <= 1e-15

    def test_fext_single_line_z0_residual_boundary(self):
        """边界如实：单线阻抗终接下 FEXT 残差 O(弱耦) ~2e-3（不凑零）。"""
        eps_r = 4.4
        mu0 = 4e-7 * math.pi
        eps0 = 8.854187817e-12
        c_m_weak = 0.3e-12
        _, c_mat = symmetric_pair_pul(L_S, L_M, C_G, c_m_weak)
        l_mat = mu0 * eps0 * eps_r * np.linalg.inv(c_mat)
        c11 = float(c_mat[0, 0])
        c_m_f = float(-c_mat[0, 1])
        z0_single = math.sqrt(float(l_mat[0, 0]) / (c11 - c_m_f))
        exact = _exact_chain_solution(FREQ_HZ, l_mat, c_mat, z0_single,
                                      LENGTH)
        ratio = abs(exact["vfe"]) / abs(exact["vne"])
        assert 1e-4 < ratio < 1e-2

    def test_next_grows_with_freq_and_length(self):
        c1 = mtl_crosstalk_coeffs(L_M, C_M, Z0, 1e9, LENGTH)
        c2 = mtl_crosstalk_coeffs(L_M, C_M, Z0, 2e9, LENGTH)
        assert abs(c2["vne_over_vs"]) == pytest.approx(
            2.0 * abs(c1["vne_over_vs"]), rel=1e-12)
        c3 = mtl_crosstalk_coeffs(L_M, C_M, Z0, 1e9, 2.0 * LENGTH)
        assert abs(c3["vne_over_vs"]) == pytest.approx(
            2.0 * abs(c1["vne_over_vs"]), rel=1e-12)

    def test_guard_bad_inputs(self):
        with pytest.raises(ValueError):
            mtl_crosstalk_coeffs(0.0, C_M, Z0, FREQ_HZ, LENGTH)
        with pytest.raises(ValueError):
            mtl_mode_skew(-1.0, 1e-12, 1e-9, 1e-12, 0.1)


class TestModeSkew:
    def test_skew_symmetric_pair(self):
        eo = symmetric_pair_even_odd(L_S, L_M, C_G, C_M)
        rep = mtl_mode_skew(eo["l_even_h"], eo["c_even_f"],
                            eo["l_odd_h"], eo["c_odd_f"], LENGTH)
        assert rep["z_even_ohm"] == pytest.approx(eo["z_even_ohm"], rel=1e-15)
        assert rep["tau_skew_s"] == pytest.approx(
            rep["tau_even_s"] - rep["tau_odd_s"], rel=1e-15)
        assert rep["f_skew_hz"] == pytest.approx(
            1.0 / (2.0 * abs(rep["tau_skew_s"])), rel=1e-15)


class TestMixedModeCrossCheck:
    def test_symmetric_pair_zero_conversion(self):
        """验收口径：对称双线混合模 S——零差共模转换+模速对拍。

        匹配耦合线 4 端口（Z₀=√(Z_eZ_o) 设计口径，Pozar §7 耦合线
        耦合器闭式）：S_through=(S_e+S_o)/2、S_couple=(S_e−S_o)/2、
        S_isolated=0。混合模：sdd21=|S_o|=1（0dB，差模=奇模速）、
        scc21=|S_e|=1（0dB）、scd21/sdc21=−inf（对称零转换）。
        """
        from rfauto.service.si_channel_service import mixed_mode_metrics

        eo = symmetric_pair_even_odd(L_S, L_M, C_G, C_M)
        w = 2.0 * math.pi * FREQ_HZ
        length = 0.02
        se = np.exp(-1j * w * eo["beta_over_omega_even"] * length)
        so = np.exp(-1j * w * eo["beta_over_omega_odd"] * length)
        s_thr = (se + so) / 2.0
        s_cpl = (se - so) / 2.0
        s = np.zeros((1, 4, 4), dtype=complex)
        s[0, 0, 1] = s[0, 1, 0] = s_thr
        s[0, 2, 3] = s[0, 3, 2] = s_thr
        s[0, 0, 3] = s[0, 3, 0] = s_cpl
        s[0, 1, 2] = s[0, 2, 1] = s_cpl
        rep = mixed_mode_metrics(freq_hz=np.array([FREQ_HZ]), s=s,
                                 ports_pair=(1, 3))
        assert rep["ok"] is True
        m = rep["metrics"]
        assert m["sdd21_db"][0] == pytest.approx(0.0, abs=1e-9)
        assert m["scc21_db"][0] == pytest.approx(0.0, abs=1e-9)
        assert m["scd21_db"][0] < -240.0
        assert m["sdc21_db"][0] < -240.0
