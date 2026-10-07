"""材料表征三法单元测试（MA-1/MA-2/MA-3，round17 §六，先写后跑 #122）。

预声明判据（round17 规格）：
- MA-1 分裂圆柱：合成回收 ≤0.5%（εr 与 tanδ 两面）。
- MA-3 自由空间：合成回收 ≤1%。
- MA-2 Courtney/扰动：闭式精确（confined 模型内自洽），回收 ≤0.5% 同带。

数值裁判纪律（#118：不信单源推导）：
- ℓ→0 极限：分裂圆柱特征方程退化为全填充 TE011，f0 必须回收 Courtney
  闭式，且误差按 2ℓ/d 线性收敛（收敛律本身是独立锚，不赌单个 ℓ 值）。
- 空腔极限：εr=1 时 f0 逐位等于空腔 TE011 闭式（独立解析式）。
- 能量恒等式：特征方程+幅值连续的场解在谐振点满足
  k0²(εr·I_s+I_a) = k_r²(I_s+I_a)+β_s²J_s+β_a²J_a（W_e=W_m）——对
  E_φ/H_r 常数组与闭式积分的独立自洽钉（曾抓出 A² 重复计数，见 ）。
- 扰动 ξ 对拍：闭式 πR²J₀²/2 vs 数值积分 ∫J₁²(k_r r)r dr（scipy 正交，
  独立来源）。
- MA-3 正向消费既有 tem_slab_sparams（其自身已对 skrf 独立验证）；
  LRR 级联代数由"构造夹具→级联→去嵌→逐位回收"往返钉。

文献点回放的诚实边界（#122/#300）：[E5] 分裂圆柱原文扫描件的 (f0, εr)
实测数对**不在档**（SPDR 精度数字单源待证）——本测试不伪造文献数字，
以双独立解析极限锚（空腔闭式+Courtney 闭式）承载"文献点回放"验收；
原文实测对回放留待 PDF 到档后补钉。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.dielectric_extract import C0, nrw_extract, tem_slab_sparams
from rfauto.core.material_characterization import (
    _s_to_t,
    _sc_empty_f0,
    _slab_symmetric_matrix,
    _t_to_s,
    cavity_perturbation_extract,
    courtney_er_from_f0,
    courtney_extract,
    courtney_f0_of_er,
    courtney_tand_from_q,
    free_space_extract,
    free_space_extract_network,
    lateral_coverage_guard,
    lrr_deembed,
    spdr_extract,
    split_cylinder_er_from_f0,
    split_cylinder_extract,
    split_cylinder_f0_of_er,
    split_cylinder_tand_from_q,
    te01p_sample_filling_factor,
    thickness_resonance_guard,
)

# ─── 公共合成样品/夹具 ────────────────────────────────────────────────────────

ER_TRUE = 4.4
TAND_TRUE = 0.02
SC_R_M = 0.05        # 分裂圆柱半径
SC_ELL_M = 0.004     # 半腔长
SC_D_M = 0.001       # 样品厚
CT_R_M = 0.005       # Courtney 棒半径
CT_L_M = 0.006       # 棒高（=板距）
X01 = 3.8317059702075125  # J₁ 第一零点（测试侧独立查表值，M. Abramowitz 手册）


def _sc_f0(er: float = ER_TRUE) -> float:
    return split_cylinder_f0_of_er(er, SC_R_M, SC_ELL_M, SC_D_M)


# ═══ MA-1：分裂圆柱 ══════════════════════════════════════════════════════════


class TestSplitCylinderMA1:
    def test_round_trip_er(self) -> None:
        """正向 εr→f0 →反演回收（合成回收主口径）。"""
        for er in (2.08, 4.4, 9.8):
            f0 = split_cylinder_f0_of_er(er, SC_R_M, SC_ELL_M, SC_D_M)
            er_back = split_cylinder_er_from_f0(f0, SC_R_M, SC_ELL_M, SC_D_M)
            assert abs(er_back - er) / er <= 1e-10

    def test_f0_monotone_decreasing_in_er(self) -> None:
        """介质只降频：εr 增大 → f0 单调下降（物理语义）。"""
        f_prev = _sc_empty_f0(SC_R_M, SC_ELL_M, SC_D_M)
        for er in (1.05, 2.0, 4.4, 9.8):
            f0 = split_cylinder_f0_of_er(er, SC_R_M, SC_ELL_M, SC_D_M)
            assert f0 < f_prev
            f_prev = f0

    def test_empty_cavity_limit_exact(self) -> None:
        """空腔极限：εr=1 时 f0 逐位等于独立空腔闭式。"""
        assert split_cylinder_f0_of_er(1.0, SC_R_M, SC_ELL_M, SC_D_M) == _sc_empty_f0(
            SC_R_M, SC_ELL_M, SC_D_M
        )
        # 反演面语义：f0=空腔解 → 无物理根，显式拒绝（介质必降频）
        with pytest.raises(ValueError, match="模式误指"):
            split_cylinder_er_from_f0(
                _sc_empty_f0(SC_R_M, SC_ELL_M, SC_D_M), SC_R_M, SC_ELL_M, SC_D_M
            )

    def test_ell_to_zero_recovers_courtney_with_linear_convergence(self) -> None:
        """ℓ→0 极限：回收 Courtney 全填充闭式，误差按 2ℓ/d 线性收敛。

        收敛律是独立锚：若特征方程/闭式任一侧有误，比值不会是 1/2。
        """
        d = SC_D_M
        f_court = courtney_f0_of_er(ER_TRUE, SC_R_M, d)
        err1 = abs(split_cylinder_f0_of_er(ER_TRUE, SC_R_M, 1e-7, d) - f_court) / f_court
        err2 = abs(split_cylinder_f0_of_er(ER_TRUE, SC_R_M, 5e-8, d) - f_court) / f_court
        assert err1 <= 5.0e-4  # ≈2ℓ/d=2e-4 量级
        assert 0.4 <= err2 / err1 <= 0.6  # 线性收敛（实测 0.50005）

    def test_energy_identity_at_resonance(self) -> None:
        """谐振点 W_e=W_m 恒等式（场常数组独立自洽钉）。"""
        from rfauto.core.material_characterization import _sc_solution

        for er in (2.08, 4.4, 9.8):
            f0 = _sc_f0(er)
            sol = _sc_solution(f0, er, SC_R_M, SC_ELL_M, SC_D_M)
            k0 = 2.0 * math.pi * f0 / C0
            lhs = k0**2 * (er * sol.i_s + sol.i_a)
            rhs = (
                sol.k_r**2 * (sol.i_s + sol.i_a)
                + sol.beta_s**2 * sol.j_s
                + sol.beta_a**2 * sol.j_a
            )
            assert abs(lhs - rhs) / lhs <= 1e-12

    def test_tand_recovery_within_spec(self) -> None:
        """MA-1 验收：tanδ 合成回收 ≤0.5%（无导体修正口径）。"""
        f0 = _sc_f0()
        sol_p_e = split_cylinder_tand_from_q(f0, 1.0, SC_R_M, SC_ELL_M, SC_D_M).p_e
        qu = 1.0 / (sol_p_e * TAND_TRUE)
        res = split_cylinder_extract(f0, qu, SC_R_M, SC_ELL_M, SC_D_M)
        assert abs(res.er - ER_TRUE) / ER_TRUE <= 5.0e-4
        assert abs(res.tan_d - TAND_TRUE) / TAND_TRUE <= 5.0e-3  # 0.5%

    def test_tand_recovery_with_conductor_injection(self) -> None:
        """导体修正两面：q_c 直采回收精确；无修正时偏差方向=高估（少扣 1/Q_c）。"""
        f0 = _sc_f0()
        loss = split_cylinder_tand_from_q(f0, 1.0, SC_R_M, SC_ELL_M, SC_D_M)
        qc = 8000.0
        qu = 1.0 / (loss.p_e * TAND_TRUE + 1.0 / qc)
        res = split_cylinder_extract(f0, qu, SC_R_M, SC_ELL_M, SC_D_M, q_c=qc)
        assert abs(res.tan_d - TAND_TRUE) / TAND_TRUE <= 1e-10
        assert res.q_c == qc
        res_nc = split_cylinder_extract(f0, qu, SC_R_M, SC_ELL_M, SC_D_M)
        assert res_nc.tan_d > TAND_TRUE  # 漏扣导体损耗 → 高估 tanδ（方向钉）

    def test_surface_resistance_path_self_consistent(self) -> None:
        """Rs 闭式路径：正向按同一场解构造 Qu → 回收精确（模型内自洽口径）。"""
        from rfauto.core.material_characterization import _sc_solution

        rs = 2.0
        f0 = _sc_f0()
        sol = _sc_solution(f0, ER_TRUE, SC_R_M, SC_ELL_M, SC_D_M)
        w_norm = (sol.i_s + sol.i_a) + (
            sol.beta_s**2 * sol.j_s + sol.beta_a**2 * sol.j_a
        ) / sol.k_r**2
        p_norm = 2.0 * (sol.amp_a * sol.beta_a / sol.k_r) ** 2 + 2.0 * (
            sol.i_s + sol.i_a
        ) / SC_R_M
        inv_qc = (rs / 2.0) * p_norm / (2.0 * math.pi * f0 * w_norm)
        qu = 1.0 / (sol.p_e * TAND_TRUE + inv_qc)
        res = split_cylinder_extract(
            f0, qu, SC_R_M, SC_ELL_M, SC_D_M, surface_resistance_ohm=rs
        )
        assert abs(res.tan_d - TAND_TRUE) / TAND_TRUE <= 1e-9
        # 双修正口径显式拒绝
        with pytest.raises(ValueError, match="只能给一个"):
            split_cylinder_tand_from_q(
                f0, qu, SC_R_M, SC_ELL_M, SC_D_M, q_c=8000.0, surface_resistance_ohm=rs
            )

    def test_qu_below_conductor_limit_raises(self) -> None:
        f0 = _sc_f0()
        with pytest.raises(ValueError, match="不自洽"):
            split_cylinder_tand_from_q(f0, 100.0, SC_R_M, SC_ELL_M, SC_D_M, q_c=50.0)

    def test_f0_above_empty_raises(self) -> None:
        f_empty = _sc_empty_f0(SC_R_M, SC_ELL_M, SC_D_M)
        with pytest.raises(ValueError, match="模式误指"):
            split_cylinder_er_from_f0(f_empty * 1.01, SC_R_M, SC_ELL_M, SC_D_M)

    def test_below_radial_cutoff_raises(self) -> None:
        """f0 低于空气半腔径向截止 → β_a 虚数，显式拒绝。"""
        f_cut = C0 * X01 / (2.0 * math.pi * SC_R_M)
        with pytest.raises(ValueError, match=r"截止|虚数"):
            split_cylinder_er_from_f0(f_cut * 0.5, SC_R_M, SC_ELL_M, SC_D_M)

    def test_spdr_registered_boundary(self) -> None:
        """SPDR 按 round17 边界只登记不实现（Krupka 2001 需标定曲线）。"""
        with pytest.raises(NotImplementedError, match="SPDR"):
            spdr_extract(1.0)


# ═══ MA-2：Courtney + 扰动 ═══════════════════════════════════════════════════


class TestCourtneyMA2:
    def test_round_trip_exact(self) -> None:
        """Courtney 闭式正反演互逆（代数恒等，≤1e-12）。"""
        for n, p in ((1, 1), (2, 1), (1, 2)):
            f0 = courtney_f0_of_er(ER_TRUE, CT_R_M, CT_L_M, n_radial=n, p_axial=p)
            er = courtney_er_from_f0(f0, CT_R_M, CT_L_M, n_radial=n, p_axial=p)
            assert abs(er - ER_TRUE) / ER_TRUE <= 1e-12

    def test_te011_hand_value(self) -> None:
        """教科书口径手算值：εr = ((x01/R)²+(π/L)²)/k0² 逐步复算。"""
        f0 = 10e9
        k0 = 2.0 * math.pi * f0 / C0
        expect = ((X01 / CT_R_M) ** 2 + (math.pi / CT_L_M) ** 2) / k0**2
        assert abs(courtney_er_from_f0(f0, CT_R_M, CT_L_M) - expect) <= 1e-12 * expect

    def test_extract_recovery_within_spec(self) -> None:
        """MA-2 验收带：er/tanδ 回收 ≤0.5%；q_c 注入路径精确。"""
        f0 = courtney_f0_of_er(ER_TRUE, CT_R_M, CT_L_M)
        qc = 5000.0
        qu = 1.0 / (TAND_TRUE + 1.0 / qc)
        res = courtney_extract(f0, qu, CT_R_M, CT_L_M, q_c=qc, er_prior=ER_TRUE)
        assert abs(res.er - ER_TRUE) / ER_TRUE <= 5.0e-3
        assert abs(res.tan_d - TAND_TRUE) / TAND_TRUE <= 5.0e-3
        assert "mode_misassignment_warning" not in res.metadata

    def test_mode_misassignment_warning(self) -> None:
        """模式误指 sanity 面：TE021 谐振当 TE011 反演 → εr 系统性偏低+警告。

        方向推导：TE021 频率 f∝x02 > x01，按基模公式反演 k0 偏大 →
        εr=const/k0² 偏低（x01 项占比被高估的反面）。
        """
        f0_te021 = courtney_f0_of_er(ER_TRUE, CT_R_M, CT_L_M, n_radial=2)
        res = courtney_extract(f0_te021, 5000.0, CT_R_M, CT_L_M, er_prior=ER_TRUE)
        assert res.er < ER_TRUE
        assert "mode_misassignment_warning" in res.metadata

    def test_tand_guards(self) -> None:
        with pytest.raises(ValueError, match="不自洽"):
            courtney_tand_from_q(100.0, q_c=50.0)
        with pytest.raises(ValueError, match=r"p_e"):
            courtney_tand_from_q(5000.0, p_e=1.5)


class TestPerturbationMA2:
    XI = 3.0e-3

    def _forward(self, er: float, tand: float) -> tuple[float, float, float]:
        f0e, q0e = 10e9, 5000.0
        fs = f0e * (1.0 - (er - 1.0) * self.XI / 2.0)
        qs = 1.0 / (1.0 / q0e + er * tand * self.XI)
        return f0e, fs, qs

    def test_round_trip_within_spec(self) -> None:
        f0e, fs, qs = self._forward(ER_TRUE, TAND_TRUE)
        res = cavity_perturbation_extract(f0e, 5000.0, fs, qs, self.XI)
        assert abs(res.er - ER_TRUE) / ER_TRUE <= 5.0e-3
        assert abs(res.tan_d - TAND_TRUE) / TAND_TRUE <= 5.0e-3

    def test_e_node_position_rejected(self) -> None:
        """样品在 E 节面（p=1 时 z0=L/2）→ ξ 名义非零而场为零 → 频移不可测。"""
        xi_node = te01p_sample_filling_factor(0.05, 0.02, 1e-8, 0.027)  # z0 缺省 L/2
        with pytest.raises(ValueError, match=r"E 节面|降频"):
            cavity_perturbation_extract(10e9, 5000.0, 10e9, 5000.0, xi_node)

    def test_fs_above_f0_raises(self) -> None:
        with pytest.raises(ValueError, match="降频"):
            cavity_perturbation_extract(10e9, 5000.0, 10.001e9, 4900.0, self.XI)

    def test_q_not_increased_raises(self) -> None:
        f0e, fs, _ = self._forward(ER_TRUE, TAND_TRUE)
        with pytest.raises(ValueError, match="加损"):
            cavity_perturbation_extract(f0e, 5000.0, fs, 6000.0, self.XI)

    def test_xi_out_of_band_raises(self) -> None:
        with pytest.raises(ValueError, match="微扰"):
            cavity_perturbation_extract(10e9, 5000.0, 9.9e9, 4900.0, 0.5)
        with pytest.raises(ValueError, match=r"微扰|样品体积"):
            te01p_sample_filling_factor(0.05, 0.02, 0.01, 0.027)

    def test_mu_mixing_warning(self) -> None:
        f0e, fs, qs = self._forward(ER_TRUE, TAND_TRUE)
        res = cavity_perturbation_extract(f0e, 5000.0, fs, qs, self.XI, mu_sample_rel=1.5)
        assert "mu_mixing_warning" in res.metadata

    def test_xi_closed_form_vs_quadrature(self) -> None:
        """ξ 积分核对：径向闭式 (R²/2)J₀² vs 数值积分（独立来源，#118）。

        闭式径向积分 ∫J₁²(k_r r)r dr = (R²/2)J₀²(x0n)（J₁(x0n)=0、
        J₂=−J₀）；ξ 分母的 πR²LJ₀²/2 = 2π·(R²/2)J₀²·(L/2)（方位×轴向）。
        """
        from scipy import integrate
        from scipy.special import j0, j1

        r_m, l_m = 0.05, 0.02
        x01 = X01
        k_r = x01 / r_m
        num = integrate.quad(lambda r: float(j1(k_r * r)) ** 2 * r, 0.0, r_m)[0]
        radial_closed = r_m**2 * float(j0(x01)) ** 2 / 2.0
        assert abs(num - radial_closed) / radial_closed <= 1e-9
        xi = te01p_sample_filling_factor(r_m, l_m, 1e-8, 0.027, z0_m=0.0005)
        full_denom = math.pi * r_m**2 * l_m * float(j0(x01)) ** 2 / 2.0
        expect = (
            float(j1(k_r * 0.027)) ** 2
            * 1e-8
            * math.cos(math.pi * 0.0005 / l_m) ** 2
            / full_denom
        )
        assert abs(xi - expect) / expect <= 1e-12


# ═══ MA-3：自由空间 ══════════════════════════════════════════════════════════


def _fixture_s(seed: int = 7) -> np.ndarray:
    """无源小失配对称夹具（合成 LRR 用）。"""
    return np.array(
        [[0.05 + 0.02j, 0.9 - 0.01j], [0.9 - 0.01j, 0.03 + 0.01j]], dtype=complex
    )


class TestFreeSpaceMA3:
    def test_synthetic_recovery_within_spec(self) -> None:
        """MA-3 验收：tem_slab 正向 → 提取回收 ≤1%（多频点多损耗）。"""
        for tand in (0.0, 0.02):
            for f_ghz in (10.0, 26.0):
                s11, s21 = tem_slab_sparams(
                    complex(ER_TRUE), tand, 0.002, f_ghz * 1e9
                )
                res = free_space_extract(s11, s21, 0.002, f_ghz * 1e9, er_guess=4.0)
                assert abs(res.er.real - ER_TRUE) / ER_TRUE <= 1e-2
                assert res.tan_d == pytest.approx(tand, abs=1e-2)

    def test_matches_nrw_direct(self) -> None:
        """复用口径：free_space_extract 与 nrw_extract 直调逐位一致。"""
        s11, s21 = tem_slab_sparams(complex(ER_TRUE), 0.02, 0.002, 10e9)
        res = free_space_extract(s11, s21, 0.002, 10e9, er_guess=4.0)
        nrw = nrw_extract(s11, s21, 0.002, 10e9, er_guess=4.0)
        assert res.er == nrw.er
        assert res.branch_n == nrw.branch_n
        assert res.deembedded is False

    def test_lrr_deembed_recovers_slab(self) -> None:
        """LRR 口径：夹具级联 → 对称 Thru 平方根去嵌 → NRW 逐位回收。"""
        s_f = _fixture_s()
        t_f = _s_to_t(s_f)
        s11, s21 = tem_slab_sparams(complex(ER_TRUE), 0.02, 0.002, 10e9)
        s_meas = _t_to_s(t_f @ _s_to_t(_slab_symmetric_matrix(s11, s21)) @ t_f)
        s_thru = _t_to_s(t_f @ t_f)
        lrr = lrr_deembed(s_meas, s_thru)
        assert abs(lrr.s11 - s11) <= 1e-12
        assert abs(lrr.s21 - s21) <= 1e-12
        # 单向测量口径（仅 S11/S21）经平板对称补全：夹具 S11_F≠S22_F 的非对称
        # 残余留在去嵌里（~1e-3 级），仍落在 MA-3 ≤1% 验收带；全矩阵精确口径
        # 由上行 lrr_deembed 直调逐位钉（1e-12）。
        res = free_space_extract(
            complex(s_meas[0, 0]), complex(s_meas[1, 0]), 0.002, 10e9,
            er_guess=4.0, s_thru=s_thru,
        )
        assert res.deembedded is True
        assert abs(res.er.real - ER_TRUE) / ER_TRUE <= 2e-3
        assert abs(res.tan_d - 0.02) <= 5e-2

    def test_lrr_refl_plate_verification(self) -> None:
        """Reflect 标准：与夹具模型自洽的金属板 → |Γ|≈1、refl_ok=True。"""
        s_f = _fixture_s()
        e00, e11 = s_f[0, 0], s_f[1, 1]
        e_tr = s_f[1, 0] * s_f[0, 1]
        gamma_plate = -1.0 + 0j  # PEC 板在参考面
        m = e00 + e_tr * gamma_plate / (1.0 - e11 * gamma_plate)
        s_refl = np.array([[m, 0.0], [0.0, m]], dtype=complex)
        t_f = _s_to_t(s_f)
        s_thru = _t_to_s(t_f @ t_f)
        lrr = lrr_deembed(
            _slab_symmetric_matrix(0.3, 0.8), s_thru, s_refl1=s_refl, s_refl2=s_refl,
            f_hz=10e9,
        )
        assert lrr.refl_ok is True
        assert abs(lrr.refl1_gamma + 1.0) <= 1e-12  # 反演出 PEC 板 Γ=−1
        # 偏离无源口径的"板"（|Γ|=0.7）→ refl_ok=False
        m_bad = e00 + e_tr * 0.7 / (1.0 - e11 * 0.7)
        lrr_bad = lrr_deembed(
            _slab_symmetric_matrix(0.3, 0.8), s_thru,
            s_refl1=np.array([[m_bad, 0.0], [0.0, m_bad]]), f_hz=10e9,
        )
        assert lrr_bad.refl_ok is False

    def test_thickness_resonance_guard(self) -> None:
        """厚度谐振负例：d=λg/2 拒绝；偏 10% 通过并报最近阶。"""
        er_g, d_g = 4.4, 0.002
        f_res = C0 / (2.0 * math.sqrt(er_g) * d_g)  # k0√εr·d=π
        with pytest.raises(ValueError, match="厚度谐振"):
            free_space_extract(
                *tem_slab_sparams(complex(er_g), 0.0, d_g, f_res), d_g, f_res,
                er_guess=er_g,
            )
        n = thickness_resonance_guard(d_g, f_res * 1.10, er_g, tol_rad=0.15)
        assert n == 1
        with pytest.raises(ValueError, match="厚度谐振"):
            thickness_resonance_guard(d_g, f_res, er_g, tol_rad=0.15)

    def test_lateral_coverage_guard(self) -> None:
        lateral_coverage_guard(0.30, 0.20)  # 覆盖 → 通过
        with pytest.raises(ValueError, match="平面波"):
            lateral_coverage_guard(0.10, 0.20)
        # 只给样品尺寸不给光斑 → 不阻断，metadata 如实声明
        s11, s21 = tem_slab_sparams(complex(ER_TRUE), 0.02, 0.002, 10e9)
        res = free_space_extract(s11, s21, 0.002, 10e9, er_guess=4.0, lateral_m=0.1)
        assert "holder_note" in res.metadata

    def test_network_gating_clean_multipath(self) -> None:
        """时域门衔接（time_gating 541 行）：多径污染 → 门控后提取恢复。

        工况=同域已验证口径（test_time_gating 窄带+远延迟回波+boxcar 门）：
        2–3 GHz 带内 5mm 板（厚谐振 14.3 GHz 带外，分支 0），天线多径回波
        120 ns 延迟（幅值 20%/15%）。实测行为（2026-10-02，本机）：
        - 未门控：S11/S21 与单板模型失洽使 NRW 约半带违反无源性 → 幸存率门
          拒绝（这恰是实测流程"先门控再 NRW"的原因，如实断言拒绝）；
        - 门控后：仅 17/801 带缘剔点（全量留痕），中位 εr 误差 3e-5、
          tanδ 回收 0.01999。
        """
        import skrf

        from rfauto.core.time_gating import TimeGate

        d = 0.005
        td = 120e-9
        f = np.linspace(2e9, 3e9, 801)
        n = f.size
        s = np.zeros((n, 2, 2), dtype=complex)
        for i, fv in enumerate(f):
            a, b = tem_slab_sparams(complex(ER_TRUE), TAND_TRUE, d, float(fv))
            s[i, 0, 0] = a * (1.0 + 0.20 * np.exp(-2j * np.pi * fv * td))
            s[i, 1, 0] = b * (1.0 + 0.15 * np.exp(-2j * np.pi * fv * td))
        net = skrf.Network(frequency=skrf.Frequency.from_f(f, unit="hz"), s=s)
        gate = TimeGate.from_center_span(0.0, 40.0, unit="ns", window="boxcar")
        # 未门控：大面积提取失败 → 显式拒绝（NRW 对多径失真不可用的诚实面）
        with pytest.raises(ValueError, match="不足一半"):
            free_space_extract_network(net, d, er_guess=4.4)
        gated = free_space_extract_network(net, d, er_guess=4.4, gate=gate)
        assert gated.metadata["gated"] is True
        assert len(gated.metadata["skipped_points"]) <= 50
        assert abs(gated.er.real - ER_TRUE) / ER_TRUE <= 1e-3
        assert abs(gated.tan_d - TAND_TRUE) / TAND_TRUE <= 1e-2

    def test_network_requires_2port(self) -> None:
        import skrf

        net = skrf.Network(
            frequency=skrf.Frequency(10, 10, 2, unit="GHz"),
            s=np.zeros((2, 1, 1), dtype=complex),
        )
        with pytest.raises(ValueError, match="2 端口"):
            free_space_extract_network(net, 0.001)


# ═══ 三法交叉对拍（同合成样品）═══════════════════════════════════════════════


class TestThreeMethodCrossCheck:
    def test_same_sample_recovery_all_methods(self) -> None:
        """同一 (εr, tanδ) 合成样品走三法，全部落在各自验收带内。"""
        # MA-1 分裂圆柱
        f0 = _sc_f0()
        p_e = split_cylinder_tand_from_q(f0, 1.0, SC_R_M, SC_ELL_M, SC_D_M).p_e
        ma1 = split_cylinder_extract(f0, 1.0 / (p_e * TAND_TRUE), SC_R_M, SC_ELL_M, SC_D_M)
        # MA-2 Courtney
        fc = courtney_f0_of_er(ER_TRUE, CT_R_M, CT_L_M)
        qc = 5000.0
        ma2 = courtney_extract(fc, 1.0 / (TAND_TRUE + 1.0 / qc), CT_R_M, CT_L_M, q_c=qc)
        # MA-3 自由空间
        s11, s21 = tem_slab_sparams(complex(ER_TRUE), TAND_TRUE, 0.002, 10e9)
        ma3 = free_space_extract(s11, s21, 0.002, 10e9, er_guess=4.0)
        assert abs(ma1.er - ER_TRUE) / ER_TRUE <= 5.0e-3
        assert abs(ma1.tan_d - TAND_TRUE) / TAND_TRUE <= 5.0e-3
        assert abs(ma2.er - ER_TRUE) / ER_TRUE <= 5.0e-3
        assert abs(ma2.tan_d - TAND_TRUE) / TAND_TRUE <= 5.0e-3
        assert abs(ma3.er.real - ER_TRUE) / ER_TRUE <= 1e-2
        assert ma3.tan_d == pytest.approx(TAND_TRUE, abs=1e-2)

    def test_split_cylinder_meets_courtney_in_full_fill_limit(self) -> None:
        """交叉对拍主锚：ℓ→0 时分裂圆柱 f0 回收 Courtney 闭式（≤0.05%）。"""
        for er in (2.08, 4.4, 9.8):
            f_sc = split_cylinder_f0_of_er(er, SC_R_M, 1e-8, SC_D_M)
            f_ct = courtney_f0_of_er(er, SC_R_M, SC_D_M)
            assert abs(f_sc - f_ct) / f_ct <= 5.0e-4


# ═══ 常数与约定钉 ════════════════════════════════════════════════════════════


def test_x01_constant_matches_scipy() -> None:
    """测试侧手查的 J₁ 第一零点与 scipy 一致（防手抄漂移）。"""
    from scipy.special import jn_zeros

    assert abs(X01 - float(jn_zeros(1, 1)[0])) <= 1e-12


def test_x01_is_j1_root() -> None:
    from scipy.special import j1

    assert abs(float(j1(X01))) <= 1e-12
