"""A3 谐波平衡确定性内核单测（core/circuit_hb，全离线）。

钉死四类事实：
- 正交投影完备性（Q·P=I）与波形重建；
- 线性电路闭式解（分压/RC 低通/RL 低通，幅相双验）；
- 二极管 DC 工作点的独立解析恒等式（#118 纪律：裁判=独立来源）；
- S→Y 转换（1 端口闭式 + skrf 独立实现对拍）与 EM 端口等价表示。

不跑 ngspice（真机对照由 tests/real_edt 承载，与 WP4.3 同纪律）。
"""

import math

import numpy as np
import pytest
import skrf

from rfauto.core.circuit_hb import (
    VT_THERMAL,
    HBCapacitor,
    HBCircuit,
    HBDiode,
    HBEmNPort,
    HBInductor,
    HBResistor,
    HBVSource,
    hb_waveform_dense,
    pack_unpack_matrices,
    phasor_of,
    s_to_y,
    solve_harmonic_balance,
)


class TestProjection:
    def test_pack_unpack_orthogonal(self):
        """谐波完备（K<N/2）时投影往返 Q·P=I。"""
        p, q = pack_unpack_matrices(n_harmonics=7, n_samples=256)
        assert np.max(np.abs(q @ p - np.eye(15))) < 1e-12

    def test_projection_rejects_aliasing(self):
        """K ≥ N/2 时投影不完备，必须显式拒绝。"""
        with pytest.raises(ValueError, match="一半"):
            pack_unpack_matrices(n_harmonics=8, n_samples=16)

    def test_waveform_roundtrip(self):
        """任意系数下：采样→投影→重建 = 原波形（网格内逐点）。"""
        rng = np.random.default_rng(42)
        k, n = 5, 64
        coeffs = rng.normal(size=(2, 2 * k + 1))
        p, q = pack_unpack_matrices(k, n)
        samples = p @ coeffs[0]
        recovered = q @ samples
        assert np.allclose(recovered, coeffs[0], atol=1e-12)

    def test_phasor_convention(self):
        """峰值相量口径：c1=(a+jb) → 2|c1| 峰值、2∠c1 余弦参考相位。"""
        coeffs = np.zeros((2, 5))
        coeffs[1, 1] = 0.25  # Re c1
        coeffs[1, 2] = 0.25  # Im c1 → 相量 2·c1 = 0.5+0.5j
        ph = phasor_of(coeffs, 1, 1)
        assert abs(ph) == pytest.approx(math.sqrt(0.5))
        assert math.degrees(math.atan2(ph.imag, ph.real)) == pytest.approx(45.0)
        # 波形峰值 = |相量|
        w = hb_waveform_dense(coeffs, 1, 4096, 2)
        assert np.max(np.abs(w)) == pytest.approx(abs(ph), rel=1e-3)


class TestSToY:
    def test_one_port_gamma_formula(self):
        """1 端口：Y = (1/z0)(1−Γ)/(1+Γ)。"""
        gamma = 0.3 + 0.1j
        y = s_to_y(np.array([[gamma]]), 50.0)
        expect = (1 - gamma) / (1 + gamma) / 50.0
        assert y[0, 0] == pytest.approx(expect)

    def test_matches_skrf_independent_implementation(self):
        """与 skrf 独立实现对拍（随机无源网络，2×3 频点批）。"""
        rng = np.random.default_rng(7)
        s = (rng.normal(size=(3, 2, 2)) + 1j * rng.normal(size=(3, 2, 2))) * 0.2
        y = s_to_y(s, 50.0)
        net = skrf.Network(
            frequency=skrf.Frequency.from_f([1e9, 2e9, 3e9], unit="Hz"), s=s, z0=50.0,
        )
        assert np.allclose(y, net.y, atol=1e-10)

    def test_singular_reflection_raises(self):
        """S=−I（全反射）时 I+S 奇异，显式报错不外推。"""
        with pytest.raises(ValueError, match="奇异"):
            s_to_y(-np.eye(2), 50.0)


class TestLinearClosedForm:
    def _solve(self, circuit):
        return solve_harmonic_balance(circuit)

    def test_resistive_divider_exact(self):
        c = HBCircuit(n_nodes=3, f0_hz=1e6, n_harmonics=3)
        c.add(HBVSource(1, 0, 0.0, 1.0, phase_deg=-90.0))
        c.add(HBResistor(1, 2, 50.0))
        c.add(HBResistor(2, 0, 50.0))
        sol = self._solve(c)
        assert sol.node_dc(2) == pytest.approx(0.0, abs=1e-14)
        assert sol.node_amplitude(2, 1) == pytest.approx(0.5, rel=1e-12)
        assert sol.node_amplitude(2, 2) == pytest.approx(0.0, abs=1e-14)

    def test_rc_lowpass_amplitude_and_phase(self):
        """H(jω)=1/(1+jωRC)：f=fc → 幅 1/√2、相位 −45°（源相位 −90° → −135°）。"""
        c = HBCircuit(n_nodes=3, f0_hz=1e6, n_harmonics=4)
        c.add(HBVSource(1, 0, 0.0, 1.0, phase_deg=-90.0))
        c.add(HBResistor(1, 2, 1000.0))
        c.add(HBCapacitor(2, 0, 159.155e-12))  # fc ≈ 1 MHz
        sol = self._solve(c)
        ph = sol.node_phasor(2, 1)
        assert abs(ph) == pytest.approx(1 / math.sqrt(2), rel=1e-6)
        assert math.degrees(np.angle(ph)) == pytest.approx(-135.0, abs=1e-3)

    def test_series_rl_lowpass_with_inductor_branch(self):
        """MNA 支路（串联 L）：H=R2/(R1+R2+jωL) 闭式对拍。"""
        f0, r1, r2, lh = 10e6, 50.0, 50.0, 796e-9
        c = HBCircuit(n_nodes=4, f0_hz=f0, n_harmonics=3)
        c.add(HBVSource(1, 0, 0.0, 2.0, phase_deg=0.0))
        c.add(HBResistor(1, 2, r1))
        c.add(HBInductor(2, 3, lh))
        c.add(HBResistor(3, 0, r2))
        sol = self._solve(c)
        w = 2 * math.pi * f0
        h = r2 / (r1 + r2 + 1j * w * lh)
        ph = sol.node_phasor(3, 1)
        assert abs(ph) == pytest.approx(2.0 * abs(h), rel=1e-9)
        assert np.angle(ph) == pytest.approx(np.angle(h), abs=1e-9)

    def test_em_port_series_r_equivalence(self):
        """EM 端口 Y=g[[1,−1],[−1,1]] ≡ 节点间物理电阻 R=1/g（两种表示同解）。"""
        r_val = 25.0
        g = 1.0 / r_val
        y_series = g * np.array([[1.0, -1.0], [-1.0, 1.0]])

        def build(with_em: bool) -> HBCircuit:
            c = HBCircuit(n_nodes=4, f0_hz=1e6, n_harmonics=3)
            c.add(HBVSource(1, 0, 0.5, 1.0, phase_deg=30.0))
            c.add(HBResistor(1, 2, 50.0))
            if with_em:
                c.add(HBEmNPort((2, 3), y_series[None, ...].repeat(3, axis=0), y_dc=y_series))
            else:
                c.add(HBResistor(2, 3, r_val))
            c.add(HBResistor(3, 0, 100.0))
            return c

        sol_em = self._solve(build(True))
        sol_r = self._solve(build(False))
        assert sol_em.node_dc(3) == pytest.approx(sol_r.node_dc(3), rel=1e-12)
        assert sol_em.node_amplitude(3, 1) == pytest.approx(sol_r.node_amplitude(3, 1), rel=1e-12)

    def test_em_port_dc_open_flag(self):
        """y_dc=None → 按直流开路求解并在解里诚实标注 em_dc_open。"""
        y = 1e-3 * np.array([[1.0, -1.0], [-1.0, 1.0]])
        c = HBCircuit(n_nodes=4, f0_hz=1e6, n_harmonics=2)
        c.add(HBVSource(1, 0, 1.0, 0.1, phase_deg=-90.0))
        c.add(HBResistor(1, 2, 50.0))
        c.add(HBEmNPort((2, 3), y[None, ...].repeat(2, axis=0), y_dc=None))
        c.add(HBResistor(3, 0, 100.0))
        sol = self._solve(c)
        assert sol.em_dc_open is True
        # DC 开路 → 直流回路断：无直流电流，v2=源 DC 全值、v3=0（物理正确）
        assert sol.node_dc(3) == pytest.approx(0.0, abs=1e-12)
        assert sol.node_dc(2) == pytest.approx(1.0, rel=1e-12)


class TestDiodeNonlinear:
    def test_dc_operating_point_analytic_identity(self):
        """DC 点满足独立恒等式 V_s = I·R + n·Vt·ln(1+I/Is)（非自身推导）。"""
        vs, r, is_sat = 1.0, 1000.0, 1e-14
        c = HBCircuit(n_nodes=3, f0_hz=1e6, n_harmonics=2)
        c.add(HBVSource(1, 0, vs, 0.0, phase_deg=-90.0))
        c.add(HBResistor(1, 2, r))
        c.add(HBDiode(2, 0, is_sat=is_sat, emission_n=1.0))
        sol = solve_harmonic_balance(c)
        vd = sol.node_dc(2)
        current = (vs - vd) / r
        identity = vd - VT_THERMAL * math.log(1.0 + current / is_sat)
        assert abs(identity) < 1e-10
        assert 0.0 < vd < 0.8  # 物理合理窗（硅结量级）
        assert sol.residual_inf < 1e-9

    def test_half_wave_rectifier_harmonics(self):
        """纯弦源+二极管+RC：输出含直流与奇/偶谐波（非线性谱展宽存在）。"""
        c = HBCircuit(n_nodes=4, f0_hz=1e6, n_harmonics=6, n_samples=128)
        c.add(HBVSource(1, 0, 0.0, 2.0, phase_deg=-90.0))
        c.add(HBResistor(1, 2, 50.0))
        c.add(HBDiode(2, 3, is_sat=1e-14))
        c.add(HBResistor(3, 0, 1000.0))
        c.add(HBCapacitor(3, 0, 500e-12))
        sol = solve_harmonic_balance(c)
        assert sol.node_dc(3) > 0.3  # 检波出直流
        assert sol.node_amplitude(3, 1) > 0.0
        assert sol.node_amplitude(3, 2) > 0.0  # 半波整流含偶次

    def test_k_refinement_convergence(self):
        """K 加密（7→9）解漂移小（投影截断收敛性；强激励二极管检波器）。"""
        def solve(k_use):
            c = HBCircuit(n_nodes=4, f0_hz=1e6, n_harmonics=k_use, n_samples=128)
            c.add(HBVSource(1, 0, 0.0, 2.0, phase_deg=-90.0))
            c.add(HBResistor(1, 2, 50.0))
            c.add(HBDiode(2, 3, is_sat=1e-14))
            c.add(HBResistor(3, 0, 1000.0))
            c.add(HBCapacitor(3, 0, 500e-12))
            return solve_harmonic_balance(c)

        a, b = solve(7), solve(9)
        assert abs(a.node_dc(3) - b.node_dc(3)) / b.node_dc(3) < 0.01


class TestSolverRobustness:
    def test_determinism_bitwise(self):
        """同输入两次求解逐位一致（确定性内核要求）。"""
        def build():
            c = HBCircuit(n_nodes=3, f0_hz=1e6, n_harmonics=3)
            c.add(HBVSource(1, 0, 0.0, 1.0, phase_deg=-90.0))
            c.add(HBResistor(1, 2, 50.0))
            c.add(HBDiode(2, 0, is_sat=1e-14))
            return c

        s1, s2 = solve_harmonic_balance(build()), solve_harmonic_balance(build())
        assert np.array_equal(s1.x, s2.x)

    def test_unknown_element_type_raises(self):
        c = HBCircuit(n_nodes=2, f0_hz=1e6)
        c.elements.append(object())
        with pytest.raises(TypeError, match="未知 HB 元件"):
            solve_harmonic_balance(c)

    def test_solution_accessors(self):
        c = HBCircuit(n_nodes=3, f0_hz=1e6, n_harmonics=3)
        c.add(HBVSource(1, 0, 0.0, 1.0, phase_deg=-90.0))
        c.add(HBResistor(1, 2, 50.0))
        c.add(HBResistor(2, 0, 50.0))
        sol = solve_harmonic_balance(c)
        assert sol.converged is True
        assert sol.node_phasor(2, 0) == pytest.approx(0.0, abs=1e-14)
        w = sol.waveform(2, 512)
        assert w.shape == (512,)
        assert np.max(w) == pytest.approx(0.5, rel=1e-3)
