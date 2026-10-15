"""openEMS 槽线 WaveguidePort 桥（adapters/openems_slotline_port.py）单测。

离线面（无 NGSolve/无引擎）：模式文件格式（/x /y /Vx /Vy + Version 属性、行主序
nx×ny、非均匀轴合法、非单调轴拒绝）、轴映射 (nPy+1)%3/(nPy+2)%3（上游
CSPropExcitation.cpp 逐字口径）、kc 反解（慢波纯虚）与 β_port(f) 重构、H 文件
同幅归一（Z_mode·H）、端口盒 start/stop 语义。
CSXCAD 面（绑定可导入时）：WaveguidePort 文件模式真构造——激励属性带
WeightFile + PropagationDir=(1,0,0)、U/I 探针 p_type 10/11 带 ModeFile。
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from rfauto.adapters import openems_slotline_port as osp

C0 = 299792458.0


def _fake_mode(ny: int = 9, nz: int = 7, z0: float = 110.0, beta: float = 67.2,
               f_ghz: float = 2.5) -> SimpleNamespace:
    """构造一个合成 TransverseMode 替身：E_y 高斯、E_z 反对称、H 由 Z 归一给出。"""
    y = np.concatenate([np.linspace(-0.06, -0.004, 3, endpoint=False),
                        np.linspace(-0.004, 0.004, ny - 6),
                        np.linspace(0.004, 0.06, 4)[1:]])
    z = np.linspace(-0.03, 0.03, nz)
    yy, zz = np.meshgrid(y, z, indexing="ij")
    ey = np.exp(-(yy / 0.002) ** 2 - ((zz - 0.0015) / 0.003) ** 2)
    ez = 0.3 * yy / 0.002 * ey
    e_t = np.stack([ey, ez], axis=-1).astype(complex)
    h_t = np.stack([-ez / z0, ey / z0], axis=-1).astype(complex)
    return SimpleNamespace(freq_ghz=f_ghz, beta_rad_m=beta, z0_ohm=z0, e_t=e_t, h_t=h_t,
                           y_grid_m=y, z_grid_m=z, imag_residual=1e-9)


class TestAxesAndKc:
    def test_axes_mapping_matches_upstream_cyclic_rule(self):
        assert osp.mode_file_axes_for_prop_dir("x") == (1, 2)
        assert osp.mode_file_axes_for_prop_dir("y") == (2, 0)
        assert osp.mode_file_axes_for_prop_dir(2) == (0, 1)
        with pytest.raises(ValueError):
            osp.mode_file_axes_for_prop_dir("w")

    def test_kc_slow_wave_is_imaginary_and_roundtrips_beta(self):
        f0 = 2.5e9
        k0 = 2 * math.pi * f0 / C0
        beta0 = 1.283 * k0
        kc = osp.slotline_port_kc(beta0, f0)
        assert kc.real == pytest.approx(0.0, abs=1e-12)
        assert kc.imag == pytest.approx(math.sqrt(beta0 ** 2 - k0 ** 2), rel=1e-12)
        # openEMS CalcPort 口径 β=√(k²−kc²) 在 f0 精确回到 β0
        assert float(osp.port_beta_from_kc(f0, kc)[0]) == pytest.approx(beta0, rel=1e-12)

    def test_kc_fast_wave_is_real(self):
        f0 = 10e9
        k0 = 2 * math.pi * f0 / C0
        kc = osp.slotline_port_kc(0.75 * k0, f0)
        assert kc.imag == pytest.approx(0.0, abs=1e-12)
        assert kc.real == pytest.approx(k0 * math.sqrt(1 - 0.75 ** 2), rel=1e-12)

    def test_port_beta_dispersion_assumption_shape(self):
        """kc 假设下 β_port(f)=√(k²+|kc|²)：斜率随 f 上升趋近 k（非 TEM 线性）。"""
        f0 = 2.5e9
        k0 = 2 * math.pi * f0 / C0
        kc = osp.slotline_port_kc(1.3 * k0, f0)
        f = np.array([2.0e9, 2.5e9, 3.0e9])
        b = osp.port_beta_from_kc(f, kc)
        assert b[1] == pytest.approx(1.3 * k0, rel=1e-12)
        # 等效 εeff_port(f)=(β/k)² 随 f 单调下降（kc 假设的固有色散形态）
        eps = (b / (2 * math.pi * f / C0)) ** 2
        assert eps[0] > eps[1] > eps[2]

    def test_kc_rejects_bad_beta(self):
        with pytest.raises(ValueError):
            osp.slotline_port_kc(0.0, 2.5e9)
        with pytest.raises(ValueError):
            osp.slotline_port_kc(float("nan"), 2.5e9)


class TestModeFiles:
    def test_write_and_read_roundtrip_format(self, tmp_path):
        mode = _fake_mode()
        pair = osp.write_slotline_mode_files(mode, tmp_path, stem="t")
        e = osp.read_mode_h5(pair.e_path)
        h = osp.read_mode_h5(pair.h_path)
        assert e["Version"] == 1.0 and h["Version"] == 1.0
        assert e["Vx"].shape == (len(mode.y_grid_m), len(mode.z_grid_m))
        assert e["Vx"].dtype == np.float64
        np.testing.assert_allclose(e["x"], mode.y_grid_m)
        np.testing.assert_allclose(e["y"], mode.z_grid_m)
        # 行主序 data[i,j] @ (x[i], y[j])：E 文件 Vx=E_y、Vy=E_z
        np.testing.assert_allclose(e["Vx"], mode.e_t[:, :, 0].real)
        np.testing.assert_allclose(e["Vy"], mode.e_t[:, :, 1].real)
        # H 文件同幅归一：Z_mode·H
        np.testing.assert_allclose(h["Vx"], (mode.z0_ohm * mode.h_t[:, :, 0]).real)
        np.testing.assert_allclose(h["Vy"], (mode.z0_ohm * mode.h_t[:, :, 1]).real)
        # 同幅归一后 ∫|H_file|² ≈ ∫|E|²（合成模里 H=rot(E)/Z 精确）
        assert np.sum(np.abs(h["Vx"]) ** 2 + np.abs(h["Vy"]) ** 2) == pytest.approx(
            np.sum(np.abs(e["Vx"]) ** 2 + np.abs(e["Vy"]) ** 2), rel=1e-9)
        assert pair.grid_shape == e["Vx"].shape
        assert pair.z_mode_ohm == 110.0
        assert pair.kc.imag > 0

    def test_meta_json_written(self, tmp_path):
        import json

        pair = osp.write_slotline_mode_files(_fake_mode(), tmp_path, stem="m")
        meta = json.loads(Path(pair.meta_path).read_text(encoding="utf-8"))
        assert meta["file_axes_global"] == {"x": "y_global_m", "y": "z_global_m"}
        assert meta["e_components"] == ["E_y", "E_z"]
        assert meta["kc_im"] == pytest.approx(pair.kc.imag)

    def test_rejects_non_monotonic_axis(self, tmp_path):
        mode = _fake_mode()
        mode.y_grid_m = mode.y_grid_m.copy()
        mode.y_grid_m[3], mode.y_grid_m[4] = mode.y_grid_m[4], mode.y_grid_m[3]
        with pytest.raises(ValueError, match="单调"):
            osp.write_slotline_mode_files(mode, tmp_path)

    def test_rejects_bad_impedance(self, tmp_path):
        mode = _fake_mode()
        mode.z0_ohm = float("nan")
        with pytest.raises(ValueError, match="模阻抗"):
            osp.write_slotline_mode_files(mode, tmp_path)

    def test_only_x_propagation_supported(self, tmp_path):
        with pytest.raises(ValueError, match="exc_dir"):
            osp.write_slotline_mode_files(_fake_mode(), tmp_path, exc_dir="y")


class TestPortBoxes:
    def test_start_stop_semantics(self):
        start, stop = osp.slotline_port_boxes(-0.05, -0.045, 0.06, -0.03, 0.0315)
        np.testing.assert_allclose(start, [-0.05, -0.06, -0.03])
        np.testing.assert_allclose(stop, [-0.045, 0.06, 0.0315])
        assert np.sign(stop[0] - start[0]) == 1
        # 端口 2：激励面靠边界、测量面在内 → direction −1
        s2, e2 = osp.slotline_port_boxes(0.05, 0.045, 0.06, -0.03, 0.0315)
        assert np.sign(e2[0] - s2[0]) == -1

    def test_zero_length_rejected(self):
        with pytest.raises(ValueError):
            osp.slotline_port_boxes(0.0, 0.0, 0.06, -0.03, 0.03)


def _csxcad_available() -> bool:
    try:
        import CSXCAD  # noqa: F401
        import openEMS.ports  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _csxcad_available(), reason="CSXCAD/openEMS 绑定不可导入")
class TestWaveguidePortConstruction:
    def test_file_mode_port_properties(self, tmp_path):
        from CSXCAD import ContinuousStructure

        pair = osp.write_slotline_mode_files(_fake_mode(), tmp_path, stem="p")
        csx = ContinuousStructure()
        p1 = osp.add_slotline_wg_port(csx, 1, -0.05, -0.045, 0.06, -0.03, 0.0315, pair,
                                      excite=1.0)
        p2 = osp.add_slotline_wg_port(csx, 2, 0.05, 0.045, 0.06, -0.03, 0.0315, pair,
                                      excite=0.0)
        assert p1.kc == pair.kc and p2.direction == -1 and p1.direction == 1
        types = {}
        for i in range(csx.GetQtyProperties()):
            pr = csx.GetProperty(i)
            types.setdefault(str(pr.GetTypeString()), []).append(pr)
        # 激励：仅 port1 一份，带权重文件与 x 向传播方向（文件模式必需）
        exc = types["Excitation"]
        assert len(exc) == 1
        assert exc[0].GetWeightFile() == pair.e_path
        np.testing.assert_allclose(exc[0].GetPropagationDir(), [1, 0, 0])
        np.testing.assert_allclose(exc[0].GetExcitation(), [0, 1, 1])  # 横向两分量加权
        # 探针：两端口各 U(10)+I(11)，模式文件分别为 E/H
        probes = types["ProbeBox"]
        ptypes = sorted(pr.GetProbeType() for pr in probes)
        assert ptypes == [10, 10, 11, 11]
        for pr in probes:
            f = pr.GetModeFile()
            assert f == (pair.e_path if pr.GetProbeType() == 10 else pair.h_path)
