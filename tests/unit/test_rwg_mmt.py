"""DP-1 P1 core/rwg_mmt.py 单测：合成回收，裁判独立于实现（#118/#300）。

判据书：runs/df6_dp1mmt/criteria.md（预声明 §0-§4，先写后跑 #122）。
覆盖（规格书 §3 单测①-⑥ + criteria §2 回收锚 A1-A8）：
① 同波导无结构 |S11|<1e-12、S21=e^{−jβL}（β 对照 siw_beta_rad_m，G3/A1）；
② 阻抗台阶 Γ 闭式逐位（低层单模+全管线 εr 台阶两条路，A2）；
③ 感性膜片连续性降级门（A5，criteria §3 降级声明：Marcuvitz 互证未过，
   绝对值 UNDECIDABLE 留 P3 HFSS 仲裁）；
④ 两段级联 vs TL ABCD（闭式+skrf 独立转换双裁判，A3）；
⑤ 全模 GSM 无源/互易/单通道能量守恒（G4/A4，恒等式级）；
⑥ ×2 收敛门认证+如实拒证、比例/截断守卫负例、近截止 undetermined；
附加：A6 α_c 场积分独立数值回收；A7 renormalize vs skrf；A8 积分平凡自检。
"""

from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import siw_beta_rad_m
from rfauto.core.rwg_mmt import (
    HStepJunction,
    InductiveIris,
    ModePolicy,
    UniformSection,
    Waveguide,
    alpha_c_te10,
    alpha_d_te10,
    aperture_h_matrix,
    junction_gsm,
    mode_basis,
    overlap_1d,
    renormalize_2port,
    solve_chain,
)

C0 = 299792458.0
MU0 = 4.0e-7 * math.pi

WR90 = Waveguide(a=22.86e-3, b=10.16e-3)
F10 = 10e9


class TestOverlapClosedForms:
    """A8：一维闭式积分平凡自检+数值正交性+偏移展开。"""

    def test_full_aperture_trivial_and_orthogonality(self):
        a = 22.86e-3
        assert abs(overlap_1d("sin_sin", a, 1, a, 1, 0.0, a) - a / 2) < 1e-15
        assert abs(overlap_1d("sin_sin", a, 1, a, 3, 0.0, a)) < 1e-15
        assert abs(overlap_1d("sin_sin", a, 2, a, 5, 0.0, a)) < 1e-15

    def test_delta_zero_limit_exact(self):
        # a1=a2, m1=m2 → Δ=0：半角稳定形式极限自动精确（criteria §0 勘误式）
        a, x0, w = 20e-3, 5e-3, 8e-3
        m = 3
        got = overlap_1d("sin_sin", a, m, a, m, x0, w)
        sig = 2.0 * m * math.pi / a
        ref = 0.5 * (w - (math.sin(sig * (x0 + w)) - math.sin(sig * x0)) / sig)
        assert abs(got - ref) < 1e-15

    def test_shifted_window_against_quadrature(self):
        # 独立裁判：np.trapezoid 数值积分 vs 闭式（含四种和差化积组合）
        a1, a2 = 22.86e-3, 12e-3
        m1, m2 = 3, 2
        x0, w = 4e-3, 7e-3
        x = np.linspace(x0, x0 + w, 40001)
        pairs = {
            "sin_sin": (np.sin(m1 * math.pi * x / a1), np.sin(m2 * math.pi * x / a2)),
            "cos_cos": (np.cos(m1 * math.pi * x / a1), np.cos(m2 * math.pi * x / a2)),
            "sin_cos": (np.sin(m1 * math.pi * x / a1), np.cos(m2 * math.pi * x / a2)),
            "cos_sin": (np.cos(m1 * math.pi * x / a1), np.sin(m2 * math.pi * x / a2)),
        }
        for kind, (f, g) in pairs.items():
            ref = float(np.trapezoid(f * g, x))
            assert abs(overlap_1d(kind, a1, m1, a2, m2, x0, w) - ref) < 1e-12


class TestUniformStraight:
    """单测①+G3：同波导无结构 + WR-90 β 互洽锚（A1）。"""

    def test_s11_zero_s21_phase_and_beta_anchor(self):
        length = 0.03
        freqs = np.linspace(8e9, 12e9, 21)
        res = solve_chain([UniformSection(WR90, length)], freqs)
        assert not res.undetermined.any()
        assert res.converged
        s = res.s2x2
        assert float(np.max(np.abs(s[:, 0, 0]))) < 1e-12
        assert float(np.max(np.abs(s[:, 1, 1]))) < 1e-12
        for i in range(freqs.size):
            expect = np.exp(-1j * res.beta_te10_ports[i, 0] * length)
            assert abs(s[i, 0, 1] - expect) < 1e-12
            assert abs(s[i, 1, 0] - expect) < 1e-12
        # G3/A1：β 对照 core/calculators.siw_beta_rad_m（WR-90 fc10=6.5571GHz 既有钉）
        beta_ref, fc10_ghz = siw_beta_rad_m(22.86, 1.0, 10.0)
        assert abs(fc10_ghz - 6.5571) < 5e-5
        beta_me = res.beta_te10_ports[freqs.size // 2, 0].real
        assert abs(beta_me - beta_ref) / beta_ref <= 1e-6
        for i, f in enumerate(freqs):
            b_ref, _ = siw_beta_rad_m(22.86, 1.0, float(f) / 1e9)
            b_me = res.beta_te10_ports[i, 0].real
            assert abs(b_me - b_ref) / b_ref <= 1e-6
        # Z_PV=2b/a·Z^TE 同步输出（siw_analysis 同形口径）
        assert abs(res.z_pv_ports[freqs.size // 2, 0]
                   - 2 * WR90.b / WR90.a * res.z_te_ports[freqs.size // 2, 0]) < 1e-9


class TestImpedanceStep:
    """单测②+A2：阻抗台阶 Γ 闭式（裁判=传输线教科书式）。"""

    def test_lowlevel_single_mode_matches_closed_form(self):
        z1, z2 = 400.0, 250.0
        g = junction_gsm(np.array([[1.0 + 0j]]), np.array([z1 + 0j]),
                         np.array([z2 + 0j]))
        gamma = (z2 - z1) / (z1 + z2)
        t_coef = 2 * math.sqrt(z1 * z2) / (z1 + z2)
        assert abs(g.s11[0, 0] - gamma) < 1e-12
        assert abs(g.s22[0, 0] + gamma) < 1e-12
        assert abs(g.s21[0, 0] - t_coef) < 1e-12
        assert abs(g.s12[0, 0] - t_coef) < 1e-12

    def test_pipeline_eps_step_matches_closed_form(self):
        wg2 = Waveguide(a=22.86e-3, b=10.16e-3, eps_r=2.04)
        res = solve_chain(
            [HStepJunction(WR90, wg2, x0_m=0.0, aperture_m=22.86e-3)],
            np.array([F10]),
            ModePolicy(n_modes_ref=1, n_doublings_max=0))
        b1 = mode_basis(WR90, 1, F10)
        b2 = mode_basis(wg2, 1, F10)
        z1, z2 = b1.z_te[0].real, b2.z_te[0].real
        gamma = (z2 - z1) / (z1 + z2)
        assert abs(res.s2x2[0, 0, 0] - gamma) < 1e-12


class TestIrisContinuity:
    """单测③（降级门，criteria §3）：感性膜片连续性+单调性+感性符号。

    Marcuvitz 互证未过（criteria §3），绝对值 UNDECIDABLE 留 P3 HFSS。
    """

    @staticmethod
    def _iris_s(d_m):
        res = solve_chain([InductiveIris(WR90, d_m, 0.0)], np.array([F10]),
                          ModePolicy(n_modes_ref=15, n_doublings_max=0))
        return res.s2x2[0]

    def test_near_open_iris_vanishes_and_conserves(self):
        s = self._iris_s(22.86e-3 - 0.5e-3)
        assert abs(s[0, 0]) < 0.05
        assert abs(abs(s[0, 0]) ** 2 + abs(s[1, 0]) ** 2 - 1) < 1e-4

    def test_near_closed_iris_full_reflection(self):
        s = self._iris_s(0.2e-3)
        assert abs(s[0, 0]) > 0.99

    def test_reflection_magnitude_monotone_in_aperture(self):
        mags = []
        for frac in (0.85, 0.7, 0.5, 0.3, 0.15):
            s = self._iris_s(frac * 22.86e-3)
            mags.append(abs(s[0, 0]))
        assert all(b2 >= b1 for b1, b2 in itertools.pairwise(mags))
        assert mags[-1] > 0.9

    def test_mid_aperture_inductive_quadrant(self):
        # 感性并联族：S11=−y/(2+y), y=jB, B<0 → Im(S11)>0 且 Re(S11)<0
        s = self._iris_s(0.7 * 22.86e-3)
        assert s[0, 0].imag > 0.0
        assert s[0, 0].real < 0.0

    def test_deep_cutoff_subguide_not_flagged(self):
        # 膜片子波导深截止（a/2@10GHz，|f−fc|/fc=0.24 远离病态带）不标
        res = solve_chain([InductiveIris(WR90, 11.43e-3, 0.0)], np.array([F10]),
                          ModePolicy(n_modes_ref=8, n_doublings_max=0))
        assert not res.undetermined[0]


class TestCascadeVsTL:
    """单测④+A3：级联 vs 传输线 ABCD（闭式+skrf 双裁判）。"""

    @staticmethod
    def _reference():
        wg2 = Waveguide(a=22.86e-3, b=10.16e-3, eps_r=2.04)
        length1, length2 = 0.012, 0.018

        def beta_z(wg):
            k0 = 2 * np.pi * F10 / C0
            k = k0 * math.sqrt(wg.eps_r)
            kc = math.pi / wg.a
            beta = math.sqrt(k * k - kc * kc)
            return beta, 2 * np.pi * F10 * MU0 / beta

        b1, z1 = beta_z(WR90)
        b2, z2 = beta_z(wg2)

        def tl(beta, z, length):
            return np.array([[np.cos(beta * length), 1j * z * np.sin(beta * length)],
                             [1j * np.sin(beta * length) / z, np.cos(beta * length)]])

        return wg2, length1, length2, tl(b1, z1, length1) @ tl(b2, z2, length2), z1, z2

    def test_cascade_matches_abcd_closed_form_and_skrf(self):
        import skrf

        wg2, length1, length2, abcd, z1, z2 = self._reference()
        res = solve_chain(
            [UniformSection(WR90, length1),
             HStepJunction(WR90, wg2, x0_m=0.0, aperture_m=22.86e-3),
             UniformSection(wg2, length2)],
            np.array([F10]),
            ModePolicy(n_modes_ref=1, n_doublings_max=0))
        # 裁判一：闭式 ABCD→S（z0 逐端口）
        a_b, b_c, c_d, d_d = abcd[0, 0], abcd[0, 1], abcd[1, 0], abcd[1, 1]
        den = a_b * z2 + b_c + c_d * z1 * z2 + d_d * z1
        s_ref = np.array([
            [(a_b * z2 + b_c - c_d * z1 * z2 - d_d * z1) / den,
             2 * math.sqrt(z1 * z2) / den],
            [2 * math.sqrt(z1 * z2) / den,
             (-a_b * z2 + b_c - c_d * z1 * z2 + d_d * z1) / den],
        ])
        assert float(np.max(np.abs(res.s2x2[0] - s_ref))) <= 1e-9
        # 裁判二：skrf abcd→s 独立实现
        nw = skrf.Network(frequency=skrf.Frequency(10, 10, unit="GHz", npoints=1),
                          z0=[z1, z2])
        nw.a = abcd[None, :, :]
        assert float(np.max(np.abs(res.s2x2[0] - nw.s[0]))) <= 1e-9


class TestPhysicsGates:
    """单测⑤+G4：无源/互易/单通道能量守恒（恒等式级）。"""

    def test_all_propagating_full_unitary_and_reciprocal(self):
        wgn = Waveguide(a=19.05e-3, b=10.16e-3)
        f = 40e9
        b1 = mode_basis(wgn, 3, f)
        b2 = mode_basis(WR90, 4, f)
        assert bool(np.all(b1.beta.imag == 0.0)) and bool(np.all(b2.beta.imag == 0.0))
        x0 = (22.86e-3 - 19.05e-3) / 2
        h = aperture_h_matrix(b1, b2, x0, 19.05e-3, offset1=x0, offset2=0.0)
        g = junction_gsm(h, b1.z_te, b2.z_te)
        s_full = np.block([[g.s11, g.s12], [g.s21, g.s22]])
        assert float(np.max(np.abs(s_full - s_full.T))) < 1e-10
        sv = np.linalg.svd(s_full, compute_uv=False)
        assert float(sv[0]) <= 1.0 + 1e-9

    def test_evanescent_case_reciprocal_and_contractive(self):
        wgn = Waveguide(a=19.05e-3, b=10.16e-3)
        b1 = mode_basis(wgn, 5, F10)
        b2 = mode_basis(WR90, 6, F10)
        assert bool(np.any(b1.beta.imag != 0.0)) and bool(np.any(b2.beta.imag != 0.0))
        x0 = (22.86e-3 - 19.05e-3) / 2
        h = aperture_h_matrix(b1, b2, x0, 19.05e-3, offset1=x0, offset2=0.0)
        g = junction_gsm(h, b1.z_te, b2.z_te)
        s_full = np.block([[g.s11, g.s12], [g.s21, g.s22]])
        assert float(np.max(np.abs(s_full - s_full.T))) < 1e-10
        n1 = 5
        t_sub = s_full[np.ix_([0, n1], [0, n1])]
        assert float(np.linalg.svd(t_sub, compute_uv=False)[0]) <= 1.0 + 1e-9
        # 单传播通道能量守恒：|S11|²+|S21|²=1（criteria 实测 0.0，门 1e-12）
        assert abs(abs(t_sub[0, 0]) ** 2 + abs(t_sub[1, 0]) ** 2 - 1) < 1e-12

    def test_thick_iris_chain_passive_reciprocal(self):
        # 厚膜片三件级联：互易/无源/对称恒等式成立（df7_dp1fix 缺陷②修复后：
        # σmax=1.0 12 位、镜像对称 |S11−S22|~1e-16——修前无源性残差 +1.7%/+6.2%
        # 与对称破坏同根，criteria §3.3 归因在档）。
        res = solve_chain([InductiveIris(WR90, 10e-3, 2e-3)], np.array([F10]),
                          ModePolicy(n_modes_ref=8))
        s = res.s2x2[0]
        assert float(np.max(np.abs(s - s.T))) < 1e-10
        assert abs(abs(s[0, 0]) ** 2 + abs(s[1, 0]) ** 2) <= 1.0 + 1e-9
        assert abs(s[0, 0] - s[1, 1]) <= 1e-9
        assert res.converged  # 修后该链真收敛（修前拒证=缺陷②层级漂移，见上）
        # 拒证语义钉（#122 不凑门）：严 tol+短梯（×2 上限 1 级）下触顶如实拒证
        res_refuse = solve_chain([InductiveIris(WR90, 10e-3, 2e-3)],
                                 np.array([F10]),
                                 ModePolicy(n_modes_ref=8, convergence_tol=1e-6,
                                            n_doublings_max=1))
        assert not res_refuse.converged


class TestConvergenceAndGuards:
    """单测⑥+G2：×2 收敛门认证/拒证 + 守卫负例 + 近截止标记。"""

    @staticmethod
    def _mild_step_chain():
        wg_s = Waveguide(a=15e-3, b=10.16e-3)
        wg_w = Waveguide(a=22.86e-3, b=10.16e-3)
        return [UniformSection(wg_s, 0.010),
                HStepJunction.centered_step(wg_s, wg_w),
                UniformSection(wg_w, 0.008)]

    def test_gate_certifies_converged_case(self):
        res = solve_chain(self._mild_step_chain(), np.array([12e9]),
                          ModePolicy(n_modes_ref=12))
        assert res.converged
        # 比例法则保持：模式数比 vs 口径宽比在容差内（ModePolicy.ratio_tolerance）
        ratio_mode = res.n_modes[0] / res.n_modes[1]
        ratio_width = 15.0 / 22.86
        assert abs(ratio_mode - ratio_width) <= 0.25 * ratio_width

    def test_strong_step_deltas_monotone_and_honest_refusal(self):
        wg_s = Waveguide(a=15e-3, b=10.16e-3)
        wg_w = Waveguide(a=45e-3, b=10.16e-3)
        chain = [UniformSection(wg_s, 0.010),
                 HStepJunction.centered_step(wg_s, wg_w),
                 UniformSection(wg_w, 0.008)]
        deltas = []
        prev = None
        for n in (6, 12, 24, 48):
            res = solve_chain(chain, np.array([12e9]),
                              ModePolicy(n_modes_ref=n, n_doublings_max=0))
            s = res.s2x2[0]
            if prev is not None:
                deltas.append(float(np.max(np.abs(s - prev))))
            prev = s
        assert deltas[-1] < deltas[0]
        assert all(b <= a for a, b in itertools.pairwise(deltas))
        res = solve_chain(chain, np.array([12e9]), ModePolicy(n_modes_ref=6))
        assert res.converged  # 修后该链真收敛（修前拒证=缺陷②层级漂移，df7_dp1fix）
        # 拒证语义钉（#122 不凑门）：严 tol+短梯下触顶如实拒证
        res = solve_chain(chain, np.array([12e9]),
                          ModePolicy(n_modes_ref=6, convergence_tol=1e-6,
                                     n_doublings_max=1))
        assert not res.converged

    def test_ratio_guard_negative(self):
        pol = ModePolicy(n_modes_ref=6, n_modes_override={0: 6, 1: 6})
        with pytest.raises(ValueError, match="失衡"):
            solve_chain([HStepJunction(Waveguide(a=15e-3, b=10.16e-3),
                                       Waveguide(a=45e-3, b=10.16e-3))],
                        np.array([12e9]), pol)

    def test_truncation_guard_negative_and_optout(self):
        chain = [UniformSection(WR90, 0.5e-3)]
        with pytest.raises(ValueError, match="截断充分性守卫"):
            solve_chain(chain, np.array([F10]),
                        ModePolicy(n_modes_ref=15, n_doublings_max=0))
        res = solve_chain(chain, np.array([F10]),
                          ModePolicy(n_modes_ref=15, n_doublings_max=0,
                                     strict_truncation_guard=False))
        assert res.warnings

    def test_near_cutoff_undetermined_not_extrapolated(self):
        freqs = np.array([6.6e9, 7.2e9, 6.0e9])
        res = solve_chain([UniformSection(WR90, 0.03)], freqs,
                          ModePolicy(n_modes_ref=5, n_doublings_max=0))
        assert bool(res.undetermined[0]) and not res.undetermined[1]
        assert bool(res.undetermined[2])  # 端口截止以下 2×2 契约失效
        assert bool(np.isnan(res.s2x2[0]).all())
        assert bool(np.isfinite(res.s2x2[1]).all())


class TestLossModels:
    """A6：α_c 场积分独立数值回收 + α_d 段衰减。"""

    def test_alpha_c_matches_independent_wall_integral(self):
        wg = Waveguide(a=22.86e-3, b=10.16e-3, sigma=5.8e7)
        a_closed = alpha_c_te10(wg, F10)
        basis = mode_basis(wg, 1, F10)
        beta = float(basis.beta[0].real)
        kc = float(basis.kc[0])
        omega = 2 * np.pi * F10
        x = np.linspace(0, WR90.a, 4001)
        ey = np.sin(kc * x)
        hx = -beta / (omega * MU0) * ey
        hz = 1j * kc / (omega * MU0) * np.cos(kc * x)
        z_te = omega * MU0 / beta
        power = 0.5 * np.trapezoid(np.abs(ey) ** 2, x) * WR90.b / z_te
        rs = math.sqrt(math.pi * F10 * MU0 / wg.sigma)
        p_loss = 0.5 * rs * (2 * np.trapezoid(np.abs(hx) ** 2 + np.abs(hz) ** 2, x)
                             + 2 * WR90.b * abs(hz[0]) ** 2)
        a_num = p_loss / (2 * power)
        assert abs(a_num - a_closed) / a_closed < 1e-3

    def test_alpha_d_section_attenuation(self):
        wg = Waveguide(a=22.86e-3, b=10.16e-3, tan_d=1e-3)
        length = 0.05
        res = solve_chain([UniformSection(wg, length)], np.array([F10]),
                          ModePolicy(n_modes_ref=1, n_doublings_max=0))
        a_d = alpha_d_te10(wg, F10)
        assert abs(abs(res.s2x2[0, 1, 0]) - math.exp(-a_d * length)) < 1e-12


class TestRenormalize:
    """A7：renormalize_2port vs skrf 独立实现。"""

    def test_matches_skrf(self):
        import skrf

        res = solve_chain([InductiveIris(WR90, 10e-3, 0.0)], np.array([F10]),
                          ModePolicy(n_modes_ref=15, n_doublings_max=0))
        s = res.s2x2[0]
        z0 = [float(res.z_te_ports[0, 0].real)] * 2
        mine = renormalize_2port(s, z0, [50.0, 50.0])
        nw = skrf.Network(frequency=skrf.Frequency(10, 10, unit="GHz", npoints=1),
                          s=s[None, :, :], z0=z0)
        nw.renormalize([50.0, 50.0])
        assert float(np.max(np.abs(mine - nw.s[0]))) <= 1e-9

    def test_rejects_nonpositive_reference(self):
        with pytest.raises(ValueError, match="正实数"):
            renormalize_2port(np.zeros((2, 2)), [50.0, -50.0], [50.0, 50.0])


class TestGuideValueSemantics:
    """guide 表值语义单源（P1 缺陷根治钉，DP-1 P2 交付面）。

    缺陷背景：_guide_list 按**值相等**去重 guide 表，而 solve_at_counts 曾按
    ``id()`` 反查——链中"值相等但实例不同"的 Waveguide（JSON 段表逐段新造、
    用户分开构造皆可触发）去重后其 id 不在表内 → KeyError。既有测试复用
    模块级常量实例（WR90 同一对象）故未暴露。根治=值哈希反查（frozen
    dataclass 值语义），适配器侧 canonicalize_chain 权宜随之删除。
    """

    FREQS = np.array([10e9, 12e9])

    def test_uniform_chain_distinct_equal_instances_bit_identical(self):
        """两段同规格均匀段分开构造（值相等、实例不同）与共享实例逐位一致。"""
        wg_shared = Waveguide(a=22.86e-3, b=10.16e-3)
        shared = [UniformSection(wg_shared, 0.01), UniformSection(wg_shared, 0.02)]
        a1 = Waveguide(a=22.86e-3, b=10.16e-3)
        a2 = Waveguide(a=22.86e-3, b=10.16e-3)
        assert a1 == a2 and a1 is not a2  # 值相等、实例不同（缺陷触发前提）
        distinct = [UniformSection(a1, 0.01), UniformSection(a2, 0.02)]
        res_a = solve_chain(shared, self.FREQS)
        res_b = solve_chain(distinct, self.FREQS)  # P1 缺陷：此处 KeyError
        assert res_b.undetermined.shape == self.FREQS.shape
        assert not res_b.undetermined.any()
        assert np.array_equal(res_a.s2x2, res_b.s2x2)
        assert np.array_equal(res_a.z_te_ports, res_b.z_te_ports)
        assert res_a.n_modes == res_b.n_modes

    def test_iris_chain_distinct_equal_instances_bit_identical(self):
        """SIW 滤波器式链：主波导三处独立构造 + 膜片子波导，与共享实例一致。"""
        wg_shared = Waveguide(a=22.86e-3, b=10.16e-3)
        shared = [UniformSection(wg_shared, 0.01),
                  InductiveIris(wg_shared, 16e-3, 2e-3),
                  UniformSection(wg_shared, 0.01)]
        distinct = [UniformSection(Waveguide(a=22.86e-3, b=10.16e-3), 0.01),
                    InductiveIris(Waveguide(a=22.86e-3, b=10.16e-3), 16e-3, 2e-3),
                    UniformSection(Waveguide(a=22.86e-3, b=10.16e-3), 0.01)]
        freqs = np.array([10e9])  # 避开膜片子波导近截止带 [8.90, 9.84] GHz
        res_a = solve_chain(shared, freqs)
        res_b = solve_chain(distinct, freqs)  # P1 缺陷：此处 KeyError
        assert not res_b.undetermined.any()
        assert np.array_equal(res_a.s2x2, res_b.s2x2)
