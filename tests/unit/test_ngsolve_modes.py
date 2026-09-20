"""NGSolve 二维横截面模式求解器（adapters/ngsolve_modes.py）单测。

离线面：截面描述校验、分级采样轴、模式选择器（合成本征值）、缺依赖显式报错。
真机面（skipif ngsolve 未装）：
- 硬自检（#118）：矩形波导 TE10 β 对解析 √(k²−(π/a)²)（o1 ≤0.5%、o2 ≤0.01%）；
  平行板 TEM β=k√εr（≤1e-6，A9 锚几何 W=6/H=0.6924/εr=2.1@3GHz）；
- 槽线标称点（W=1.0/h=1.524/εr=3.66@2.5GHz）：β 对 Janaswamy–Schaubert 闭式
  ≤5%（实测 −0.12%）、Z0 功率-电压定义对闭式 ≤10%（实测 −3.2%，闭式自身
  Max 2.7%）、V0=1V 规一、P=1/(2Z0)、E_y 在金属面上恒零、E_t 实部规一残差 <1e-6。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.adapters import ngsolve_modes as nm

_HAS_NGSOLVE = nm.ngsolve_installed()
C0 = 299792458.0


class TestOffline:
    def test_section_validation(self):
        with pytest.raises(ValueError):
            nm.SlotlineSection(w_mm=0.0, h_mm=1.0, er=3.0)
        with pytest.raises(ValueError):
            nm.SlotlineSection(w_mm=1.0, h_mm=1.0, er=3.0, y_half_mm=0.4)
        sec = nm.SlotlineSection(w_mm=1.0, h_mm=1.524, er=3.66)
        assert sec.y_half_mm == 60.0 and sec.z_bot_mm == 30.0

    def test_graded_axis_covers_endpoints_and_is_monotonic(self):
        ax = nm.graded_axis(-0.06, 0.06, -0.004, 0.004, 0.0001, 24)
        assert ax[0] == -0.06 and ax[-1] == 0.06
        assert np.all(np.diff(ax) > 0)
        dense = ax[(ax >= -0.004 - 1e-12) & (ax <= 0.004 + 1e-12)]
        assert len(dense) == 81
        with pytest.raises(ValueError):
            nm.graded_axis(0.0, 1.0, 0.5, 0.2, 0.01, 3)

    def test_pick_physical_mode_prefers_real_near_guess(self):
        vals = np.array([67.1 + 0j, -67.1 + 0j, 0.4 + 21.6j, 0.4 - 21.6j, 16.8 + 0j])
        vecs = np.zeros((10, 5), dtype=complex)
        for k in range(5):
            vecs[:, k] = k + 1
        beta, vec = nm._pick_physical_mode(vals, vecs, 67.2)
        assert beta == 67.1 + 0j
        assert vec.shape == (5,) and np.all(vec == 1)  # 取线性化向量前半

    def test_pick_physical_mode_rejects_when_no_candidate(self):
        vals = np.array([-5.0 + 0j, 0.1 + 30j])
        with pytest.raises(RuntimeError, match="物理模式"):
            nm._pick_physical_mode(vals, np.zeros((4, 2), complex), 67.0)

    def test_solve_pencil_rejects_bad_guess(self):
        import scipy.sparse as sp

        eye = sp.identity(3, format="csc", dtype=complex)
        with pytest.raises(ValueError):
            nm._solve_pencil_beta(eye, eye, eye, -1.0)

    def test_build_mesh_requires_ngsolve(self, monkeypatch):
        monkeypatch.setattr(nm, "ngsolve_installed", lambda: False)
        with pytest.raises(RuntimeError, match="ngsolve 未安装"):
            nm.build_slotline_mesh(nm.SlotlineSection(w_mm=1.0, h_mm=1.5, er=3.0))


@pytest.mark.skipif(not _HAS_NGSOLVE, reason="ngsolve 未安装——真机模式求解测试跳过")
class TestHardGates:
    def test_te10_order1_within_half_percent(self):
        k0 = 2 * math.pi * 10e9 / C0
        ref = math.sqrt(k0 ** 2 - (math.pi / 22.86e-3) ** 2)
        b = nm.solve_rect_waveguide_te10_beta(22.86, 10.16, 1.0, 10.0, order=1, maxh_mm=2.0)
        assert abs(b / ref - 1.0) <= 5e-3

    def test_te10_order2_essentially_exact(self):
        k0 = 2 * math.pi * 10e9 / C0
        ref = math.sqrt(k0 ** 2 - (math.pi / 22.86e-3) ** 2)
        b = nm.solve_rect_waveguide_te10_beta(22.86, 10.16, 1.0, 10.0, order=2, maxh_mm=2.0)
        assert abs(b / ref - 1.0) <= 1e-4

    def test_te10_rejects_below_cutoff(self):
        with pytest.raises(ValueError, match="截止"):
            nm.solve_rect_waveguide_te10_beta(22.86, 10.16, 1.0, 5.0)

    def test_parallel_plate_tem_anchor(self):
        b = nm.solve_parallel_plate_beta(6.0, 0.6924, 2.1, 3.0)
        ref = 2 * math.pi * 3e9 / C0 * math.sqrt(2.1)
        assert abs(b / ref - 1.0) <= 1e-6


@pytest.fixture(scope="module")
def nominal_mode():
    sec = nm.SlotlineSection(w_mm=1.0, h_mm=1.524, er=3.66, y_half_mm=60.0,
                             z_bot_mm=30.0, z_top_mm=30.0)
    return sec, nm.solve_slotline_mode(sec, 2.5, maxh_mm=4.0, slot_near_mm=0.125)


@pytest.mark.skipif(not _HAS_NGSOLVE, reason="ngsolve 未安装——真机模式求解测试跳过")
class TestSlotlineNominal:
    def test_beta_vs_closed_form(self, nominal_mode):
        from rfauto.core.slotline import slotline_closed_form

        sec, m = nominal_mode
        cf = slotline_closed_form(sec.w_mm, sec.h_mm, sec.er, 2.5)
        assert abs(m.beta_rad_m / cf.beta_rad_m - 1.0) <= 0.05  # 判据门；实测 −0.12%
        assert m.beta_rad_m > 2 * math.pi * 2.5e9 / C0  # 慢波
        assert m.imag_over_real_eig < 1e-8

    def test_z0_power_voltage_vs_closed_form(self, nominal_mode):
        from rfauto.core.slotline import slotline_closed_form

        sec, m = nominal_mode
        cf = slotline_closed_form(sec.w_mm, sec.h_mm, sec.er, 2.5)
        assert abs(m.z0_ohm / cf.z0_ohm - 1.0) <= 0.10  # 实测 −3.2%（闭式 Max 2.7%）
        assert m.v_slot == pytest.approx(1.0 + 0j)
        assert m.p_flow == pytest.approx(1.0 / (2.0 * m.z0_ohm), rel=1e-9)

    def test_field_physics(self, nominal_mode):
        sec, m = nominal_mode
        assert m.imag_residual < 1e-6
        iy0 = int(np.argmin(np.abs(m.y_grid_m)))
        jh = int(np.argmin(np.abs(m.z_grid_m - sec.h_mm * 1e-3)))
        ey_c = m.e_t[iy0, jh, 0].real
        # 槽心 E_y 主导：V0=1V/1mm 均值 1000V/m，中心 ~660V/m（边缘奇性）
        assert 400.0 < ey_c < 1000.0
        assert abs(m.e_t[iy0, jh, 1]) < 0.05 * ey_c   # 对称轴上 E_z≈0
        # 金属面上（|y|>w/2, z=h）切向 E_y 恒零
        iy_m = int(np.argmin(np.abs(m.y_grid_m - 0.030)))
        assert abs(m.e_t[iy_m, jh, 0]) < 1e-9 * ey_c
        # 场在域边界处已衰减（<2% 中心值，屏蔽框影响小）
        iy_e = int(np.argmin(np.abs(m.y_grid_m - 0.055)))
        jz_e = int(np.argmin(np.abs(m.z_grid_m - 0.028)))
        assert np.abs(m.e_t[iy_e, :, :]).max() < 0.02 * ey_c
        assert np.abs(m.e_t[:, jz_e, :]).max() < 0.02 * ey_c
        # 采样网格覆盖整个截面且单调
        assert m.y_grid_m[0] == -0.06 and m.y_grid_m[-1] == 0.06
        assert m.z_grid_m[0] == pytest.approx(-0.03) and m.z_grid_m[-1] == pytest.approx(0.03 + 1.524e-3)
        assert np.all(np.diff(m.y_grid_m) > 0) and np.all(np.diff(m.z_grid_m) > 0)
        assert m.e_t.shape == (len(m.y_grid_m), len(m.z_grid_m), 2)
