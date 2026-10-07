"""2-port shunt-through PDN 阻抗换算：闭式回收钉（零硬件，spec 判据）。

spec 出处：月度增强方案 L162（F-B P3 前置件，
VNA 适配器加法）+ docs/audit/plan_gap_inventory_20260928.md §二 B5。

独立裁判口径（#118）：
- 经典锚点：50Ω 系统 S21=0.5（−6.0206 dB）⟺ Z=25 Ω（业界公开口径）；
- skrf 库 a2s 通用 ABCD→S 转换作独立转换路径（模块闭式 vs 库转换）；
- 直流节点分析独立推导：纯 R 并联在双 50Ω 端口间，V 分压 →
  S21 = R/(25+R)（与闭式 2R/(2R+50) 代数同构、算式异源）；
- 回收集：forward→inverse 全复数 Z 域逐位恢复。
"""

from __future__ import annotations

import cmath
import math
from pathlib import Path

import numpy as np
import pytest
import skrf

from rfauto.adapters.vna_adapter import (
    VnaAdapter,
    shunt_through_impedance_curve,
    shunt_through_s21_from_z,
    shunt_through_z_from_s21,
)

VNA_SIM_YAML = Path(__file__).resolve().parents[1] / "fixtures" / "vna_sim.yaml"
SIM_ADDR_CAL = "TCPIP0::sim-vna::10001::INSTR"


def _vna_config() -> object:
    from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType

    return EMSolverConfig(
        solver_type=EMSolverType.VNA,
        freq_range_ghz=(1.0, 3.0),
        extra_params={
            "address": SIM_ADDR_CAL,
            "model": "librevna",
            "visa_library": f"{VNA_SIM_YAML}@sim",
            "n_points": 5,
            "ifbw_hz": 1000.0,
        })


# ─── 经典锚点与闭式互逆 ────────────────────────────────────────────────────


class TestClassicAnchor:
    def test_minus6db_is_25ohm(self):
        """业界经典锚点：S21=0.5（−6.0206 dB）⟺ Z=25 Ω（50Ω 系统）。"""
        z = shunt_through_z_from_s21(0.5 + 0.0j)
        assert z.real == pytest.approx(25.0, rel=1e-14)
        assert z.imag == pytest.approx(0.0, abs=1e-14)
        s = shunt_through_s21_from_z(25.0 + 0.0j)
        assert s.real == pytest.approx(0.5, rel=1e-14)
        assert 20.0 * math.log10(abs(s)) == pytest.approx(-6.020599913279624)

    def test_other_textbook_points(self):
        """Z=50 → S21=2/3（−3.52 dB）；Z=100 → 4/5；Z=5 → 10/60。"""
        assert shunt_through_s21_from_z(50.0) == pytest.approx(2.0 / 3.0, rel=1e-14)
        assert shunt_through_s21_from_z(100.0) == pytest.approx(0.8, rel=1e-14)
        assert shunt_through_s21_from_z(5.0) == pytest.approx(10.0 / 60.0, rel=1e-14)

    def test_forward_inverse_exact_roundtrip(self):
        """全复数 Z 域 forward→inverse 逐位恢复（闭式互逆，无近似）。"""
        omega = 2.0 * math.pi * 1e6
        z_sweep = [
            25.0, 0.1, 200.0, (0.5 + 2.0j), (30.0 - 40.0j),
            1.0 / (1j * omega * 100e-6),          # 100µF @1MHz
            5.0 + 1j * omega * 10e-9,             # 5Ω + 10nH
            cmath.exp(1j * 0.7) * 12.0,
        ]
        for z in z_sweep:
            s = shunt_through_s21_from_z(z)
            z_back = shunt_through_z_from_s21(s)
            assert z_back == pytest.approx(z, rel=1e-12, abs=1e-12)

    def test_limits_short_and_open(self):
        """Z→0 → S21→0（短路全反射）；Z→∞ → S21→1⁻（开路直通）。"""
        assert shunt_through_s21_from_z(0.0 + 0.0j) == 0.0
        assert abs(shunt_through_s21_from_z(1e12)) == pytest.approx(1.0, abs=1e-9)


# ─── 独立裁判：skrf 库转换 + 直流节点分析 ─────────────────────────────────


def _shunt_network(z: complex) -> skrf.Network:
    """并联元 ABCD=[[1,0],[1/Z,1]] 经 skrf 库 a2s 转 S（独立转换路径）。"""
    abcd = np.array([[[1.0, 0.0], [1.0 / z, 1.0]]], dtype=complex)
    return skrf.Network(
        frequency=skrf.Frequency.from_f(np.array([1e9]), unit="Hz"),
        s=skrf.network.a2s(abcd, z0=50.0), z0=50.0)


class TestIndependentReferees:
    @pytest.mark.parametrize("z", [25.0, 5.0, 60.0, 0.5 + 2.0j, 30.0 - 40.0j])
    def test_skrf_library_conversion_matches_closed_form(self, z):
        """模块闭式 S21 == skrf 库 ABCD→S 通用转换（异路径逐位）。"""
        net = _shunt_network(complex(z))
        assert net.s[0, 1, 0] == pytest.approx(
            complex(shunt_through_s21_from_z(z)), rel=1e-12, abs=1e-14)

    @pytest.mark.parametrize("z", [25.0, 5.0, 60.0, 0.5 + 2.0j, 30.0 - 40.0j])
    def test_recovery_through_library_conversion(self, z):
        """库转换网络 S21 → 模块逆换算 → Z 回收（合成回收钉）。"""
        net = _shunt_network(complex(z))
        z_back = shunt_through_z_from_s21(net.s[0, 1, 0])
        assert z_back == pytest.approx(complex(z), rel=1e-12, abs=1e-14)

    @pytest.mark.parametrize("r", [1.0, 10.0, 25.0, 100.0])
    def test_dc_nodal_analysis_referee(self, r):
        """直流节点分析：V=Vs·R/(2(25+R)) → S21=R/(25+R)（异源推导）。"""
        s_expect = r / (r + 25.0)
        assert complex(shunt_through_s21_from_z(r)) == pytest.approx(
            s_expect, rel=1e-13)


# ─── 守卫（非物理/非法入参显式拒绝）────────────────────────────────────────


class TestGuards:
    def test_s21_at_or_above_unit_rejected(self):
        with pytest.raises(ValueError, match="非物理"):
            shunt_through_z_from_s21(1.0 + 0.0j)
        with pytest.raises(ValueError, match="非物理"):
            shunt_through_z_from_s21(1.0e-16 + 1.0j)
        with pytest.raises(ValueError, match="非物理"):
            shunt_through_z_from_s21(-1.2)

    def test_bool_and_nonnumeric_rejected(self):
        with pytest.raises(ValueError, match="complex"):
            shunt_through_z_from_s21(True)
        with pytest.raises(ValueError, match="complex"):
            shunt_through_s21_from_z("25")
        with pytest.raises(ValueError, match="z0_ohm"):
            shunt_through_s21_from_z(25.0, z0_ohm=True)
        with pytest.raises(ValueError, match="z0_ohm"):
            shunt_through_s21_from_z(25.0, z0_ohm=-50.0)

    def test_curve_shape_mismatch(self):
        with pytest.raises(ValueError, match="同形"):
            shunt_through_impedance_curve(np.array([1e9, 2e9]), np.array([0.5]))


class TestCurve:
    def test_curve_matches_scalar(self):
        f = np.linspace(1e3, 1e8, 5)
        c = 47e-6
        s21 = np.array([shunt_through_s21_from_z(1.0 / (2j * math.pi * fi * c))
                        for fi in f])
        freq, z = shunt_through_impedance_curve(f, s21)
        assert np.array_equal(freq, f)
        for i, fi in enumerate(f):
            assert z[i] == pytest.approx(1.0 / (2j * math.pi * fi * c), rel=1e-12)


# ─── 适配器面：pyvisa-sim 全链零硬件（solve → 阻抗谱）──────────────────────


class TestAdapterAccessor:
    @pytest.fixture()
    def adapter(self):
        import rfauto.adapters  # noqa: F401 — 注册副作用

        ad = VnaAdapter(_vna_config())
        yield ad
        ad.close()

    def test_accessor_after_solve(self, adapter):
        result = adapter.solve()
        assert result.success is True
        freq_hz, z = adapter.get_shunt_through_impedance()
        assert freq_hz.shape == (5,)
        assert z.shape == (5,)
        # 与 S 参数直接换算逐位一致
        for i in range(5):
            z_direct = shunt_through_z_from_s21(result.s_params[i, 1, 0])
            assert z[i] == z_direct
        # sim fixture |S21|=0.9 → Z 有限且模长有界（(Z0/2)·0.9/0.1=225 档）
        assert np.all(np.abs(z) < 300.0)

    def test_accessor_lazy_solve(self, adapter):
        """未显式 solve 时 accessor 自触发（与 get_sparams 同契约）。"""
        _, z = adapter.get_shunt_through_impedance()
        assert z.shape == (5,)
