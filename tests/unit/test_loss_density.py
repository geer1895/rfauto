"""D3-1 损耗图提取内核单测（core/loss_density.py）。

裁判 = 独立来源闭式（教科书，非本模块自身推导，#118）：
- 时均欧姆损耗密度 0.5*sigma*|E|^2（Jackson §6.9）
- 介电损耗密度 0.5*omega*eps0*eps_r*tan_delta*|E|^2（Pozar §1.6）
- 趋肤深度指数衰减场积分 0.25*sigma*A*delta*|E0|^2*(1-exp(-2t/delta))
  （delta = sqrt(2/(omega*mu*sigma))，Pozar §1.7.1）

全部确定性：无网络、无真机、无文件 IO。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.loss_density import (
    DEFAULT_CLOSURE_TOLERANCE,
    EPS0,
    MU0,
    LossMaterial,
    integrate_loss_density,
    loss_density,
    power_conservation_check,
    resample_regular,
    resolve_omega,
    uniform_cell_measure,
)

# 教科书铜电导率（Pozar 4th ed. §1.7 用的量级）
SIGMA_CU = 5.8e7


# ---------------------------------------------------------------------------
# 合成算例助手
# ---------------------------------------------------------------------------

def _skin_depth(freq_hz: float, sigma: float) -> float:
    """趋肤深度闭式 delta = sqrt(2/(omega*mu0*sigma))。"""
    return math.sqrt(2.0 / (2.0 * math.pi * freq_hz * MU0 * sigma))


def _uniform_block(
    shape: tuple[int, int, int] = (6, 7, 4),
    spacing: tuple[float, float, float] = (1e-3, 1e-3, 2e-3),
    e0: float = 40.0,
    sigma: float = 0.02,
) -> tuple[np.ndarray, float, float]:
    """均匀场方块：返回 (q, dV, 解析损耗功率)。"""
    q = loss_density(np.full(shape, e0, dtype=complex), material=LossMaterial(sigma=sigma))
    d_v = uniform_cell_measure(spacing)
    analytic = 0.5 * sigma * e0**2 * (int(np.prod(shape)) * d_v)
    return q, d_v, analytic


def _self_consistent_s_row(field_power_w: float, incident_power_w: float, n_ports: int = 1):
    """由目标耗散功率反解出无源 S 行（1 端口时 |S11|^2 = 1 - P_diss/P_in）。"""
    reflected = 1.0 - field_power_w / incident_power_w
    assert reflected >= 0.0
    if n_ports == 1:
        return [complex(math.sqrt(reflected))]
    rest = reflected / (n_ports - 1)
    return [complex(math.sqrt(rest))] * n_ports


# ---------------------------------------------------------------------------
# 1. 损耗密度公式：解析闭式对照
# ---------------------------------------------------------------------------

class TestLossDensityFormula:
    def test_sigma_only_matches_jackson_closed_form(self):
        """均匀场 + 纯导体：q = 0.5*sigma*|E|^2（Jackson §6.9）。"""
        e0 = 50.0
        q = loss_density(np.full((3, 4), e0, dtype=complex), material=LossMaterial(sigma=0.02))
        assert q.shape == (3, 4)
        np.testing.assert_allclose(q, 0.5 * 0.02 * e0**2, rtol=1e-15)

    def test_dielectric_only_matches_pozar_closed_form(self):
        """均匀场 + 纯介质：q = 0.5*omega*eps0*eps_r*tan_delta*|E|^2（Pozar §1.6）。"""
        freq = 2.45e9
        mat = LossMaterial(eps_r=2.2, tan_delta=1e-3)
        q = loss_density(np.ones(3, dtype=complex), freq_hz=freq, material=mat)
        expected = 0.5 * (2.0 * math.pi * freq) * EPS0 * 2.2 * 1e-3
        np.testing.assert_allclose(q, expected, rtol=1e-14)

    def test_two_terms_are_additive(self):
        """导电项 + 介电项线性叠加（两项独立可加）。"""
        e0, freq = 7.0, 1e9
        sigma, eps_r, tan_d = 0.5, 3.0, 2e-3
        q_both = loss_density(np.full(5, e0, dtype=complex), freq_hz=freq,
                              material=LossMaterial(sigma=sigma, eps_r=eps_r, tan_delta=tan_d))
        q_cond = loss_density(np.full(5, e0, dtype=complex), material=LossMaterial(sigma=sigma))
        q_diel = loss_density(np.full(5, e0, dtype=complex), freq_hz=freq,
                              material=LossMaterial(eps_r=eps_r, tan_delta=tan_d))
        np.testing.assert_allclose(q_both, q_cond + q_diel, rtol=1e-14)

    def test_rms_convention_drops_half_factor(self):
        """RMS 相量口径无 1/2 因子（峰值相量的 2 倍）。"""
        e_rms = 3.0
        mat = LossMaterial(sigma=0.1)
        q_peak = loss_density(np.full(4, e_rms, dtype=complex), material=mat)
        q_rms = loss_density(np.full(4, e_rms, dtype=complex), material=mat, rms=True)
        np.testing.assert_allclose(q_rms, 2.0 * q_peak, rtol=1e-15)

    def test_phase_of_field_is_irrelevant(self):
        """q 只依赖 |E|：相位/复数辐角不影响损耗密度。"""
        mag = 4.0
        q = loss_density(np.array([mag, mag * 1j, -mag, mag * np.exp(1.3j)]),
                         material=LossMaterial(sigma=0.2))
        np.testing.assert_allclose(q, 0.5 * 0.2 * mag**2, rtol=1e-15)

    def test_lossless_material_gives_zero(self):
        q = loss_density(np.full((2, 2), 1e6, dtype=complex), material=LossMaterial())
        np.testing.assert_allclose(q, 0.0, atol=0.0)


# ---------------------------------------------------------------------------
# 2. 网格积分：体/面测度与解析闭式
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_uniform_volume_integral_matches_closed_form(self):
        """均匀场体网格：integral q dV = q*V（V = N*dV）。"""
        q, d_v, analytic = _uniform_block()
        numeric = integrate_loss_density(q, cell_measure=d_v)
        assert analytic == pytest.approx(0.5 * 0.02 * 40.0**2 * 6 * 7 * 4 * 2e-9)
        assert numeric == pytest.approx(analytic, rel=1e-14)

    def test_skin_depth_exponential_field_integral(self):
        """趋肤深度指数衰减场：对 0.25*sigma*A*delta*|E0|^2*(1-exp(-2t/delta)) 闭式。

        E(z) = E0*exp(-z/delta)，中点矩形积分 -> 相对误差应 << 1e-3。
        """
        sigma, freq, e0 = SIGMA_CU, 1e9, 10.0
        delta = _skin_depth(freq, sigma)
        thickness = 8.0 * delta
        n_cells = 4000
        h = thickness / n_cells
        z_mid = (np.arange(n_cells) + 0.5) * h
        e_field = e0 * np.exp(-z_mid / delta)
        q = loss_density(e_field, material=LossMaterial(sigma=sigma))
        area = 2.5e-5
        numeric = integrate_loss_density(q, cell_measure=area * h)
        analytic = 0.25 * sigma * area * delta * e0**2 * (1.0 - math.exp(-2.0 * thickness / delta))
        assert abs(numeric - analytic) / analytic < 1e-3

    def test_surface_measure_integral(self):
        """面网格：dA = dx*dy，integral q dA = q*N*dA。"""
        shape = (5, 9)
        q = loss_density(np.full(shape, 2.0, dtype=complex), material=LossMaterial(sigma=1.0))
        d_a = uniform_cell_measure((1e-3, 2e-3))
        assert d_a == pytest.approx(2e-6)
        assert integrate_loss_density(q, cell_measure=d_a) == pytest.approx(
            0.5 * 1.0 * 4.0 * 45 * 2e-6)

    def test_per_point_cell_measure_array(self):
        """逐点测度数组（非均匀网格）与标量测度在均匀时一致。"""
        q = np.full((4, 5), 3.0)
        d_v = 7e-10
        assert integrate_loss_density(q, cell_measure=np.full((4, 5), d_v)) == pytest.approx(
            integrate_loss_density(q, cell_measure=d_v))

    def test_uniform_cell_measure_scalar_and_sequence(self):
        assert uniform_cell_measure(0.5) == pytest.approx(0.5)
        assert uniform_cell_measure((1e-3, 2e-3, 5e-3)) == pytest.approx(1e-8)
        assert uniform_cell_measure(np.array([2.0, 3.0])) == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# 3. 功率守恒闭合（含非恒真反例）
# ---------------------------------------------------------------------------

class TestPowerConservation:
    def test_self_consistent_case_closes(self):
        """自洽构造：场功率由 S 参数反解出 P_in -> 闭合误差为数值零。"""
        q, d_v, field_power = _uniform_block()
        p_in = field_power / 0.85
        bal = power_conservation_check(q, cell_measure=d_v, incident_power_w=p_in,
                                       s_row=_self_consistent_s_row(field_power, p_in))
        assert bal.closed is True
        assert bal.rel_error <= DEFAULT_CLOSURE_TOLERANCE
        assert bal.sparams_power_w == pytest.approx(field_power, rel=1e-12)
        assert bal.reflected_fraction == pytest.approx(0.15, rel=1e-12)

    def test_mismatch_is_detected_not_tautological(self):
        """反例：场功率放大 2 倍（=4x）后必须判不闭合——检查非恒真。"""
        q, d_v, field_power = _uniform_block()
        p_in = field_power / 0.85
        s_row = _self_consistent_s_row(field_power, p_in)
        bad = power_conservation_check(q * 4.0, cell_measure=d_v, incident_power_w=p_in,
                                       s_row=s_row)
        assert bad.closed is False
        assert bad.rel_error == pytest.approx(0.75, rel=1e-12)

    def test_closure_tolerance_boundary(self):
        """3% 门边界：场放大 1.01 倍（+2.0%）闭合，放大 1.02 倍（+3.9%）不闭合。"""
        q, d_v, field_power = _uniform_block()
        p_in = field_power / 0.85
        s_row = _self_consistent_s_row(field_power, p_in)
        ok = power_conservation_check(q * 1.01**2, cell_measure=d_v,
                                      incident_power_w=p_in, s_row=s_row)
        bad = power_conservation_check(q * 1.02**2, cell_measure=d_v,
                                       incident_power_w=p_in, s_row=s_row)
        assert ok.rel_error < 0.03 <= bad.rel_error
        assert ok.closed is True
        assert bad.closed is False

    def test_multiport_row_uses_sum_of_squares(self):
        """多端口：耗散 = P_in*(1 - sum_j |S_ij|^2)，含反射与传输端口。"""
        q, d_v, field_power = _uniform_block()
        s_row = [0.1 + 0.0j, 0.5 + 0.0j, 0.2 + 0.0j]  # sum|S|^2 = 0.30
        p_in = field_power / 0.70
        bal = power_conservation_check(q, cell_measure=d_v, incident_power_w=p_in, s_row=s_row)
        assert bal.reflected_fraction == pytest.approx(0.30, rel=1e-12)
        assert bal.closed is True

    def test_tolerance_is_configurable(self):
        """同一算例：3.9% 失配在 tol=0.05 下闭合、在默认 tol=0.03 下不闭合。"""
        q, d_v, field_power = _uniform_block()
        p_in = field_power / 0.85
        s_row = _self_consistent_s_row(field_power, p_in)
        loose = power_conservation_check(q * 1.04, cell_measure=d_v,
                                         incident_power_w=p_in, s_row=s_row, tolerance=0.05)
        tight = power_conservation_check(q * 1.04, cell_measure=d_v,
                                         incident_power_w=p_in, s_row=s_row, tolerance=0.03)
        assert loose.closed is True
        assert tight.closed is False

    def test_non_passive_row_flagged_and_never_closed(self):
        """非无源 S 行（sum|S|^2 > 1）-> non_passive=True 且永判不闭合。"""
        q, d_v, _field_power = _uniform_block()
        bal = power_conservation_check(np.zeros_like(q), cell_measure=d_v,
                                       incident_power_w=1.0, s_row=[1.2 + 0.0j])
        assert bal.non_passive is True
        assert bal.sparams_power_w < 0.0
        assert bal.closed is False

    def test_to_dict_is_json_friendly(self):
        q, d_v, field_power = _uniform_block()
        p_in = field_power / 0.85
        bal = power_conservation_check(q, cell_measure=d_v, incident_power_w=p_in,
                                       s_row=_self_consistent_s_row(field_power, p_in))
        d = bal.to_dict()
        assert set(d) == {"field_power_w", "sparams_power_w", "rel_error", "tolerance",
                          "closed", "non_passive", "reflected_fraction"}
        assert d["closed"] is True


# ---------------------------------------------------------------------------
# 4. 重采样保真
# ---------------------------------------------------------------------------

class TestResample:
    def test_linear_field_is_reproduced_exactly(self):
        """线性场在线性插值下精确复现（2D，端点坐标重合）。"""
        n1, n2 = 11, 9
        x = np.linspace(0.0, 1.0, n1)[:, None]
        y = np.linspace(0.0, 1.0, n2)[None, :]
        field = 2.0 * x + 3.0 * y + 1.0
        out = resample_regular(field, (23, 17))
        xt = np.linspace(0.0, 1.0, 23)[:, None]
        yt = np.linspace(0.0, 1.0, 17)[None, :]
        np.testing.assert_allclose(out, 2.0 * xt + 3.0 * yt + 1.0, atol=1e-12)

    def test_upsample_error_respects_linear_interpolation_bound(self):
        """二次场上采样误差 <= h^2/8 * max|f''|（标准线性插值误差界）。"""
        n, m = 9, 33
        field = np.linspace(0.0, 1.0, n) ** 2
        out = resample_regular(field, (m,))
        target = np.linspace(0.0, 1.0, m) ** 2
        h = 1.0 / (n - 1)
        bound = h**2 / 8.0 * 2.0  # max|f''| = 2
        assert float(np.max(np.abs(out - target))) <= bound + 1e-12

    def test_nearest_selects_nearest_sample(self):
        """最近邻取整：u=[0, 2/3, 4/3, 2] -> 索引 [0, 1, 1, 2]。"""
        src = np.array([0.0, 1.0, 0.0])
        np.testing.assert_allclose(resample_regular(src, (4,), method="nearest"),
                                   [0.0, 1.0, 1.0, 0.0])
        # 线性同输入给出中间值（与最近邻可区分，证方法未串线）
        lin = resample_regular(src, (4,))
        assert lin[1] == pytest.approx(2.0 / 3.0)
        assert lin[2] == pytest.approx(2.0 / 3.0)

    def test_complex_field_resampled_consistently(self):
        """复场：实部精确、虚部满足同一误差界，dtype=complex128。"""
        n = 9
        base = np.linspace(0.0, 1.0, n)
        field = base + 1j * base**2
        out = resample_regular(field, (33,))
        assert out.dtype == np.complex128
        np.testing.assert_allclose(out.real, np.linspace(0.0, 1.0, 33), atol=1e-12)
        bound = (1.0 / 8.0) ** 2 / 8.0 * 2.0
        assert float(np.max(np.abs(out.imag - np.linspace(0.0, 1.0, 33) ** 2))) <= bound + 1e-12

    def test_same_shape_is_identity(self):
        rng = np.random.default_rng(20260912)
        field = rng.normal(size=(4, 5, 3))
        np.testing.assert_array_equal(resample_regular(field, (4, 5, 3)), field)

    def test_degenerate_single_sample_axis_is_constant(self):
        """源轴长 1（物理区间为零）-> 目标轴常数延拓，不抛异常。"""
        field = np.array([[1.0, 2.0, 3.0]])
        out = resample_regular(field, (5, 3))
        np.testing.assert_allclose(out, np.tile([1.0, 2.0, 3.0], (5, 1)))

    def test_deterministic_across_calls(self):
        rng = np.random.default_rng(7)
        field = rng.normal(size=(6, 6))
        a = resample_regular(field, (13, 4))
        b = resample_regular(field, (13, 4))
        np.testing.assert_array_equal(a, b)


# ---------------------------------------------------------------------------
# 5. 非法输入显式报错
# ---------------------------------------------------------------------------

class TestInvalidInputs:
    @pytest.mark.parametrize("kwargs", [
        {"sigma": -1.0},
        {"eps_r": 0.0},
        {"eps_r": -2.0},
        {"tan_delta": -1e-3},
        {"sigma": float("nan")},
        {"tan_delta": float("inf")},
    ])
    def test_material_rejects_invalid_params(self, kwargs):
        with pytest.raises(ValueError):
            LossMaterial(**kwargs)

    def test_nonfinite_field_rejected(self):
        with pytest.raises(ValueError):
            loss_density(np.array([1.0, np.nan]), material=LossMaterial(sigma=1.0))
        with pytest.raises(ValueError):
            loss_density(np.array([1.0 + 1j, np.inf + 0j]), material=LossMaterial(sigma=1.0))

    def test_empty_field_rejected(self):
        with pytest.raises(ValueError):
            loss_density(np.array([]), material=LossMaterial(sigma=1.0))

    def test_dielectric_loss_without_frequency_rejected(self):
        with pytest.raises(ValueError, match="tan_delta"):
            loss_density(np.ones(3), material=LossMaterial(eps_r=2.0, tan_delta=1e-3))

    def test_omega_and_freq_hz_are_mutually_exclusive(self):
        with pytest.raises(ValueError):
            resolve_omega(omega=1e9, freq_hz=1e9)
        with pytest.raises(ValueError):
            resolve_omega(freq_hz=-1.0)

    def test_resolve_omega_none_and_value(self):
        assert resolve_omega() is None
        assert resolve_omega(freq_hz=1e9) == pytest.approx(2.0 * math.pi * 1e9)

    def test_integrate_rejects_bad_q(self):
        with pytest.raises(ValueError):
            integrate_loss_density(np.array([1.0 + 1j]), cell_measure=1.0)
        with pytest.raises(ValueError):
            integrate_loss_density(np.array([1.0, np.nan]), cell_measure=1.0)
        with pytest.raises(ValueError):
            integrate_loss_density(np.array([]), cell_measure=1.0)

    def test_integrate_rejects_bad_measure(self):
        with pytest.raises(ValueError):
            integrate_loss_density(np.ones(3), cell_measure=0.0)
        with pytest.raises(ValueError):
            integrate_loss_density(np.ones(3), cell_measure=-1e-9)
        with pytest.raises(ValueError):
            integrate_loss_density(np.ones((3, 4)), cell_measure=np.ones((4, 3)))
        with pytest.raises(ValueError):
            integrate_loss_density(np.ones(3), cell_measure=np.array([1.0, 0.0, 1.0]))

    def test_uniform_cell_measure_rejects_nonpositive(self):
        with pytest.raises(ValueError):
            uniform_cell_measure(0.0)
        with pytest.raises(ValueError):
            uniform_cell_measure((1e-3, -1e-3))
        with pytest.raises(ValueError):
            uniform_cell_measure(())

    def test_power_check_rejects_bad_scalars(self):
        q = np.ones(4)
        with pytest.raises(ValueError):
            power_conservation_check(q, cell_measure=1.0, incident_power_w=0.0, s_row=[0.1])
        with pytest.raises(ValueError):
            power_conservation_check(q, cell_measure=1.0, incident_power_w=-1.0, s_row=[0.1])
        with pytest.raises(ValueError):
            power_conservation_check(q, cell_measure=1.0, incident_power_w=1.0,
                                     s_row=[0.1], tolerance=0.0)
        with pytest.raises(ValueError):
            power_conservation_check(q, cell_measure=1.0, incident_power_w=1.0,
                                     s_row=[0.1], tolerance=1.5)

    def test_power_check_rejects_bad_s_row(self):
        q = np.ones(4)
        with pytest.raises(ValueError):
            power_conservation_check(q, cell_measure=1.0, incident_power_w=1.0, s_row=[])
        with pytest.raises(ValueError):
            power_conservation_check(q, cell_measure=1.0, incident_power_w=1.0,
                                     s_row=[complex(np.nan, 0.0)])

    def test_resample_rejects_invalid_requests(self):
        field = np.ones((4, 5))
        with pytest.raises(ValueError, match="method"):
            resample_regular(field, (6, 7), method="cubic")
        with pytest.raises(ValueError):
            resample_regular(field, (6,))
        with pytest.raises(ValueError):
            resample_regular(field, (6, 0))
        with pytest.raises(ValueError):
            resample_regular(field, (6, 7, 1))
        with pytest.raises(ValueError):
            resample_regular(np.array([]), (2,))
        with pytest.raises(ValueError):
            resample_regular(np.array([1.0, np.nan]), (3,))
