"""SAR 合规后处理单测（DP-18 C10c）。

确定性、零仿真：平面波闭式解析回收 + 固定质量立方平均解析回收 + 截断
质量守恒手算例 + 峰值定位 + Virtual Family 资产边界拒绝。

判据口径注记（预声明"逐位"经实测修正，#122 如实）：均匀场立方平均经
SAT 求和/除法路径为机器精度（实测 ≤1e-15 相对）而非浮点逐位——求和
路径依赖；平面波闭式链含复相位 cos²+sin² 的浮点噪声（≤1e-15 相对）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.sar import (
    VIRTUAL_FAMILY_SUPPORTED,
    LayeredPhantom,
    UniformPhantom,
    build_phantom,
    cube_side_m,
    phantom_props_grid,
    sar_average_map,
    sar_cube_average,
    sar_pointwise,
    sar_report,
)


class TestPointwiseClosedForm:
    def test_uniform_plane_wave_bitwise(self):
        """均匀场（α=0）：SAR 核 == 解析式 σ|E₀|²/(2ρ)，同一浮点路径逐位。"""
        sigma, rho, e0 = 0.65, 1100.0, 30.0
        grid = np.full((4, 4, 4), e0 + 0j)
        sar = sar_pointwise(sigma, grid, rho)
        assert np.array_equal(sar, np.full((4, 4, 4), sigma * e0**2
                                           / (2.0 * rho)))

    def test_attenuated_plane_wave_closed_form(self):
        """有耗媒质平面波 E(z)=E₀e^{−(α+jβ)z} → SAR vs 闭式 ≤1e-12 相对。"""
        f = 2.4e9
        eps0, mu0 = 8.854187817e-12, 4.0e-7 * np.pi
        er, sigma, rho = 50.0, 0.65, 1100.0
        w = 2.0 * np.pi * f
        td = sigma / (w * eps0 * er)
        alpha = w * np.sqrt(mu0 * eps0 * er / 2.0) \
            * np.sqrt(np.sqrt(1.0 + td * td) - 1.0)
        z = np.linspace(0.0, 20e-3, 11)
        e_amp = 10.0 * np.exp(-alpha * z)
        e_field = e_amp * np.exp(-1j * 120.0 * z)  # 相位支路任意
        sar = sar_pointwise(sigma, e_field, rho)
        closed = sigma * (10.0**2) * np.exp(-2.0 * alpha * z) / (2.0 * rho)
        assert np.max(np.abs(sar / closed - 1.0)) <= 1e-12


class TestCubeAverage:
    def test_uniform_field_machine_exact(self):
        """判据 c2：均匀场下 1g/10g 平均 == 点值（机器精度 ≤1e-15 相对）。"""
        ph = UniformPhantom(sigma=1.2, rho=1000.0)
        sig, rho = phantom_props_grid(ph, (12, 12, 10))
        sar = sar_pointwise(sig, np.full((12, 12, 10), 30.0 + 4j), rho)
        for mass in (1e-3, 1e-2):
            m = sar_average_map(sar, rho, 1e-3, mass)
            assert np.max(np.abs(m["avg"] / sar - 1.0)) <= 1e-15
        # 1g 立方（10 体素）在最远角 (11,11,9) 的中心包含窗被三轴各截到
        # 6 体素 → coverage_min = 216·1e-6 kg / 1e-3 kg（手算逐位）
        assert sar_average_map(sar, rho, 1e-3, 1e-3)["coverage_min"]             == pytest.approx(216e-6 / 1e-3, rel=1e-12)
        # 网格中心体素的 1g 立方完整包含 → coverage == 1.0
        c = sar_cube_average(sar, rho, 1e-3, (5, 5, 5), 1e-3)
        assert c["coverage"] == pytest.approx(1.0, rel=1e-12)

    def test_cube_side_lengths(self):
        """判据 c2：棱长 1g→10mm、10g→21.544mm（ρ=1000）。"""
        assert cube_side_m(1e-3, 1000.0) == pytest.approx(0.010, rel=1e-15)
        assert cube_side_m(1e-2, 1000.0) \
            == pytest.approx((1e-5) ** (1.0 / 3.0), rel=1e-15)

    def test_sat_path_matches_brute_force(self):
        """积分图路径 vs 单点切片路径互证（同窗口规则）。"""
        rng = np.random.default_rng(7)
        sar = rng.uniform(0.0, 5.0, (7, 6, 5))
        rho = np.full((7, 6, 5), 1000.0)
        voxel = (1e-3, 2e-3, 5e-4)
        m = sar_average_map(sar, rho, voxel, 1e-3)
        for i in (0, 3, 6):
            for j in (0, 2, 5):
                for k in (0, 4):
                    ref = sar_cube_average(sar, rho, voxel, (i, j, k), 1e-3)
                    assert ref["avg"] == pytest.approx(m["avg"][i, j, k],
                                                       rel=1e-12)

    def test_truncated_cube_mass_conservation(self):
        """判据 c4：截断立方按纳入质量加权 + coverage 手算例逐位回收。"""
        # 台阶分布：i<3 → SAR=2，i≥3 → SAR=10（ρ=1000，体素 1mm³）
        sar = np.where(np.arange(8)[:, None, None] < 3, 2.0, 10.0) \
            * np.ones((8, 6, 6))
        rho = np.full((8, 6, 6), 1000.0)
        voxel = 1e-3
        # 质量 8 mg → 棱长 (8e-6/1000)^{1/3}·... = (8e-9)^{1/3}=2mm → 2 体素
        mass = 1000.0 * (2e-3) ** 3
        center = (3, 2, 2)
        out = sar_cube_average(sar, rho, voxel, center, mass)
        # 立方体素 i∈{2,3}×j∈{1,2}×k∈{1,2}：SAR=2 与 SAR=10 各 4 体素
        # → avg=(4·2+4·10)/8=6.0；纳入质量=8 体素·1e-9 m³·1000=8e-6 kg
        assert out["avg"] == pytest.approx(6.0, rel=1e-12)
        assert out["n_voxels"] == (2, 2, 2)
        assert out["included_mass_kg"] == pytest.approx(8e-6, rel=1e-12)
        assert out["coverage"] == pytest.approx(1.0, rel=1e-12)
        # 出体：中心 (0,2,2) → i 方向截到 [0,2)：2 个体素全 SAR=2 → avg=2
        out2 = sar_cube_average(sar, rho, voxel, (0, 2, 2), mass)
        assert out2["avg"] == pytest.approx(2.0, rel=1e-12)
        assert out2["coverage"] == pytest.approx(1.0, rel=1e-12)
        # 目标 1g（棱长 10mm → 10 体素）网格只有 8 → 纳入质量 < 目标
        out3 = sar_cube_average(sar, rho, voxel, (3, 2, 2), 1e-3)
        # 全网格 288 体素（108×SAR=2 + 180×SAR=10）→ avg=7.0
        assert out3["avg"] == pytest.approx(7.0, rel=1e-12)
        assert out3["coverage"] == pytest.approx(288e-6 / 1e-3, rel=1e-12)


class TestPeakLocalization:
    def test_gaussian_hotspot(self):
        """判据 c3：Gauss 热点（宽度≥3 体素）→ max_avg ≤ max_point、
        1g 峰偏移 ≤1 体素、分位数单调。"""
        x = np.arange(24) * 1e-3
        xx, yy, zz = np.meshgrid(x, x, x, indexing="ij")
        peak = 100.0 * np.exp(-((xx - 12e-3) ** 2 + (yy - 12e-3) ** 2
                                + (zz - 12e-3) ** 2) / (2.0 * (3e-3) ** 2))
        rho = np.full_like(peak, 1000.0)
        sig = np.full_like(peak, 1.0)
        sar = sar_pointwise(sig, np.sqrt(peak) + 0j, rho)
        rep = sar_report(sar, rho, 1e-3, (1e-3, 1e-2))
        p_max = rep["pointwise"]["max"]
        assert rep["pointwise"]["location_voxel"] == [12, 12, 12]
        m1 = rep["masses"][0]
        assert m1["sar_max_avg"] <= p_max
        assert m1["mass_kg"] == 1e-3
        offset = max(abs(a - b) for a, b
                     in zip(m1["location_voxel"], [12, 12, 12],
                            strict=True))
        assert offset <= 1, f"1g 峰偏移 {offset} 体素"
        d = rep["distribution"]
        assert d["p50"] <= d["p95"] <= d["p99"] <= d["max"]


class TestPhantom:
    def test_uniform_and_layered_props(self):
        sig, rho = phantom_props_grid(UniformPhantom(1.0, 1000.0), (3, 3, 5))
        assert (sig == 1.0).all() and (rho == 1000.0).all()
        lay = LayeredPhantom(layers=((0.0, 5e-3, 1.0, 1000.0, "skin"),
                                     (5e-3, 15e-3, 2.0, 1050.0, "fat")))
        z_axis = np.linspace(0.0, 14e-3, 15)
        sig3, rho3 = phantom_props_grid(lay, (4, 4, 15), z_axis)
        assert sig3[0, 0, 0] == 1.0 and sig3[0, 0, 5] == 2.0
        assert sig3[0, 0, 14] == 2.0 and rho3[0, 0, 2] == 1000.0

    def test_layer_gap_and_missing_axis_rejected(self):
        lay = LayeredPhantom(layers=((0.0, 5e-3, 1.0, 1000.0, "a"),
                                     (6e-3, 10e-3, 2.0, 1000.0, "b")))
        with pytest.raises(ValueError, match="覆盖"):
            phantom_props_grid(lay, (2, 2, 10), np.linspace(0, 9e-3, 10))
        with pytest.raises(ValueError, match="z_axis_m"):
            phantom_props_grid(lay, (2, 2, 10))
        with pytest.raises(ValueError, match="升序"):
            phantom_props_grid(lay, (2, 2, 10), np.linspace(9e-3, 0.0, 10))

    def test_virtual_family_boundary(self):
        """判据 c5：Virtual Family 资产边界显式不支持（常量+拒绝路径）。"""
        assert VIRTUAL_FAMILY_SUPPORTED is False
        with pytest.raises(ValueError, match="IT'IS"):
            build_phantom({"kind": "virtual_family"})
        with pytest.raises(ValueError, match="kind"):
            build_phantom({"kind": "voxel_human"})


class TestServiceEnvelope:
    def test_sar_service_json(self):
        from rfauto.service.sar_service import sar_analytic_plane_wave, sar_phantom_spec, sar_report_from_grid

        out = sar_analytic_plane_wave(2.4e9, 10.0, 0.65, 50.0, 1100.0,
                                      [0.0, 5e-3, 10e-3])
        assert out["ok"] is True
        assert out["sar_w_per_kg"][0] > out["sar_w_per_kg"][-1]
        spec = sar_phantom_spec("layered", layers=[
            {"z_lo": 0.0, "z_hi": 5e-3, "sigma": 1.0, "rho": 1000.0,
             "name": "skin"}])
        assert spec["ok"] is True
        bad = sar_phantom_spec("virtual_family")
        assert bad["ok"] is False and "IT'IS" in bad["error"]
        n = 8
        e = [[[10.0 + 0j for _ in range(n)] for _ in range(n)]
             for _ in range(n)]
        rep = sar_report_from_grid(
            [[[(v.real) for v in row] for row in plane] for plane in e],
            [[[(v.imag) for v in row] for row in plane] for plane in e],
            1.0, 1000.0, 1e-3, phantom_spec={"kind": "uniform",
                                             "sigma": 1.0, "rho": 1000.0})
        assert rep["ok"] is True
        err = sar_report_from_grid([[1.0]], [[0.0]], 1.0, 1000.0, 1e-3)
        assert err["ok"] is False and "3D" in err["error"]
