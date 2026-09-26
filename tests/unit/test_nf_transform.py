"""近场测量变换 + .ffs reader 单测（DP-18 C10a）。

确定性、零仿真、零网络：
- 主判据：z 向 Hertzian 偶极子近场闭式（独立参考实现，Balanis 全项含准静态
  1/r³ 项）合成于 z=d 平面 → 加窗 FFT 变换 → 远场 vs 闭式 sinθ ≤0.5 dB；
- .ffs reader：合成最小样例逐位回读 + 结构缺损显式失败 + 真实 HFSS 样例
  回归（样例在 pyaedt-main vendor 目录，存在才跑，缺失 skip 不硬依赖）；
- SWE 接口：契约占位显式 NotImplementedError。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.nf_transform import (
    C0,
    NearFieldGrid,
    planar_nf_to_farfield,
    read_ffs,
    spherical_wave_expansion,
)

_REAL_FFS = (Path(__file__).resolve().parents[2]
             / "pyaedt-main" / "tests" / "system" / "general"
             / "example_models" / "ff_test" / "test.ffs")


# ─── 独立参考实现：Hertzian 偶极子近场闭式（Balanis，e^{jωt}）───────────────

def _hertzian_dipole_plane_field(f_hz: float, dipole_il: float,
                                 x_m: np.ndarray, y_m: np.ndarray,
                                 z0_m: float) -> tuple[np.ndarray,
                                                       np.ndarray]:
    """z 向无穷小偶极子 @ 原点，在 z=z0 平面网格上的 (Ex, Ey) 复场。"""
    eta0 = 119.9169832 * np.pi  # 自由空间波阻抗（≈376.73 Ω）
    k = 2.0 * np.pi * f_hz / C0
    xx, yy = np.meshgrid(x_m, y_m, indexing="ij")
    r = np.sqrt(xx**2 + yy**2 + z0_m**2)
    rho_xy = np.sqrt(xx**2 + yy**2)
    sin_t = np.divide(rho_xy, r, out=np.zeros_like(r), where=r > 0)
    cos_t = np.divide(z0_m, r, out=np.ones_like(r), where=r > 0)
    cos_ph = np.divide(xx, rho_xy, out=np.ones_like(r), where=rho_xy > 0)
    sin_ph = np.divide(yy, rho_xy, out=np.zeros_like(r), where=rho_xy > 0)
    phase = np.exp(-1j * k * r)
    e_r = eta0 * dipole_il * cos_t / (2.0 * np.pi * r**2) \
        * (1.0 + 1.0 / (1j * k * r)) * phase
    e_t = (1j * eta0 * k * dipole_il * sin_t / (4.0 * np.pi * r)
           * (1.0 + 1.0 / (1j * k * r) - 1.0 / (k * r)**2) * phase)
    ex = (e_r * sin_t + e_t * cos_t) * cos_ph
    ey = (e_r * sin_t + e_t * cos_t) * sin_ph
    return ex, ey


class TestHertzianDipoleRecovery:
    """判据 a1-a3：偶极子近场 → 变换 → 远场 vs 闭式。"""

    def test_pattern_vs_closed_form(self):
        f_hz = 2.4e9
        d = 0.005  # 源-面距 5 mm（变换验证几何：近场项截断尾 ~2.5e-4）
        x = np.arange(-200e-3, 200.1e-3, 5e-3)
        y = np.arange(-200e-3, 200.1e-3, 5e-3)
        ex, ey = _hertzian_dipole_plane_field(f_hz, 1e-3, x, y, d)
        grid = NearFieldGrid(x_m=x, y_m=y, freq_hz=f_hz, ex=ex, ey=ey,
                             z0_m=d)
        out = planar_nf_to_farfield(grid, window="none",
                                    theta_deg=np.arange(5.0, 76.0, 5.0),
                                    phi_deg=np.array([0.0]))
        th = out["theta_deg"]
        e_theta = np.abs(out["e_theta"][:, 0])
        # 闭式参考：sinθ，归一到变换图峰值（幅度图形状比对）
        ref = np.sin(np.deg2rad(th))
        db = 20.0 * np.log10(e_theta / e_theta.max() + 1e-300)
        ref_db = 20.0 * np.log10(ref / ref.max() + 1e-300)
        mask = (th >= 10.0) & (th <= 70.0)
        dev = np.abs(db[mask] - ref_db[mask])
        assert dev.max() <= 0.5, f"max dev {dev.max():.3f} dB at " \
            f"θ={th[mask][np.argmax(dev)]:.0f}°"

    def test_mainlobe_monotone_and_e_phi_floor(self):
        f_hz = 2.4e9
        d = 0.005
        x = np.arange(-200e-3, 200.1e-3, 5e-3)
        y = np.arange(-200e-3, 200.1e-3, 5e-3)
        ex, ey = _hertzian_dipole_plane_field(f_hz, 1e-3, x, y, d)
        grid = NearFieldGrid(x_m=x, y_m=y, freq_hz=f_hz, ex=ex, ey=ey,
                             z0_m=d)
        out = planar_nf_to_farfield(grid, window="none",
                                    theta_deg=np.arange(10.0, 71.0, 5.0),
                                    phi_deg=np.array([0.0]))
        amp = np.abs(out["e_theta"][:, 0])
        assert (np.diff(amp) > 0).all(), "E_θ 应随 θ 单调升（趋向宽边主瓣）"
        e_phi_db = 20.0 * np.log10(
            np.abs(out["e_phi"][:, 0]) / amp.max() + 1e-300)
        assert e_phi_db.max() <= -25.0, (
            f"E_φ 地板 {e_phi_db.max():.1f} dB（偶极子 E_φ≡0）")

    def test_window_family_peak_stable(self):
        f_hz = 2.4e9
        d = 0.005
        x = np.arange(-200e-3, 200.1e-3, 5e-3)
        y = np.arange(-200e-3, 200.1e-3, 5e-3)
        ex, ey = _hertzian_dipole_plane_field(f_hz, 1e-3, x, y, d)
        peaks = []
        for win, beta in (("none", 0.0), ("kaiser", 1.0), ("kaiser", 2.0),
                          ("hann", 0.0)):
            grid = NearFieldGrid(x_m=x, y_m=y, freq_hz=f_hz, ex=ex, ey=ey,
                                 z0_m=d)
            out = planar_nf_to_farfield(
                grid, window=win, kaiser_beta=beta,
                theta_deg=np.array([45.0]), phi_deg=np.array([0.0]))
            peaks.append(float(np.abs(out["e_theta"][0, 0])))
        spread_db = 20.0 * np.log10(max(peaks) / min(peaks))
        assert spread_db <= 0.3, f"窗族峰值互差 {spread_db:.3f} dB"

    def test_validity_guard_and_bad_args(self):
        f_hz = 2.4e9
        x = np.arange(-40e-3, 40.1e-3, 10e-3)
        ex = np.ones((x.size, x.size), dtype=complex)
        grid = NearFieldGrid(x_m=x, y_m=x, freq_hz=f_hz, ex=ex, ey=ex)
        with pytest.raises(ValueError, match="越出有效域"):
            planar_nf_to_farfield(grid, theta_deg=np.array([90.0]))
        with pytest.raises(ValueError, match="window"):
            planar_nf_to_farfield(grid, window="hamming3d")
        tiny = NearFieldGrid(x_m=x[:3], y_m=x[:3],
                             freq_hz=f_hz, ex=ex[:3, :3], ey=ex[:3, :3])
        with pytest.raises(ValueError, match="4 个采样点"):
            planar_nf_to_farfield(tiny)


# ─── .ffs reader：合成最小样例 + 结构缺损 + 真实样例回归 ─────────────────────

def _write_min_ffs(path: Path) -> None:
    """两频块最小 .ffs（审计口径：phi 外层 0/180、theta 内层 0/90）。"""
    lines = ["// #Frequencies", "2", "",
             "// Radiated/Accepted/Stimulated Power , Frequency ",
             "1.0", "1.0", "1.0", "1.0e9", "",
             "0.5", "0.6", "0.7", "2.0e9", ""]
    for _amp_tag, amp in ((1.0, 2.0), (2.0, 3.0)):
        lines += ["// >> Total #phi samples, total #theta samples",
                  "2 2",
                  "// >> Phi, Theta, Re(E_Theta), Im(E_Theta), Re(E_Phi), "
                  "Im(E_Phi): "]
        for phi in (0.0, 180.0):
            for theta, val in ((0.0, amp), (90.0, amp / 2)):
                lines.append(f"{phi:7.3f}{theta:7.3f}  {val:.8e}  0.00000000e+00"
                             f"  0.00000000e+00  {val:.8e}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="ascii")


class TestFfsReader:
    def test_synthetic_roundtrip(self, tmp_path):
        p = tmp_path / "min.ffs"
        _write_min_ffs(p)
        out = read_ffs(p)
        assert out["ok"] is True
        assert out["n_freq"] == 2
        assert out["frequencies_hz"] == [1.0e9, 2.0e9]
        assert out["power_radiated_accepted_stimulated"] == [[1.0, 1.0, 1.0],
                                                             [0.5, 0.6, 0.7]]
        assert np.allclose(out["phi_deg"], [0.0, 180.0])
        assert np.allclose(out["theta_deg"], [0.0, 90.0])
        # 逐位回读（含行序：phi 外层 / theta 内层）
        assert out["e_theta"][0, 0, 0] == complex(2.0, 0.0)
        assert out["e_theta"][0, 0, 1] == complex(1.0, 0.0)
        assert out["e_theta"][0, 1, 0] == complex(2.0, 0.0)
        assert out["e_theta"][1, 1, 1] == complex(1.5, 0.0)
        assert out["e_phi"][0, 0, 1] == complex(0.0, 1.0)
        # 单频块读取
        one = read_ffs(p, freq_index=1)
        assert one["e_theta"].shape == (2, 2)
        assert one["frequencies_hz"] == [1.0e9, 2.0e9]
        assert one["e_theta"][0, 0] == complex(3.0, 0.0)

    def test_structural_damage_fails_loud(self, tmp_path):
        p = tmp_path / "bad.ffs"
        _write_min_ffs(p)
        text = p.read_text(encoding="ascii")
        # 数据行缺一行 → 结构损坏显式失败（不静默吞）
        lines = text.splitlines()
        data_idx = [i for i, ln in enumerate(lines)
                    if ln.strip().startswith("0.000") and "e+00" in ln]
        assert data_idx, "测试夹具缺数据行"
        del lines[data_idx[0]]
        p.write_text("\n".join(lines), encoding="ascii")
        with pytest.raises(ValueError):
            read_ffs(p)
        # 非法 freq_index 显式失败
        p2 = tmp_path / "min2.ffs"
        _write_min_ffs(p2)
        with pytest.raises(ValueError, match="越界"):
            read_ffs(p2, freq_index=5)

    @pytest.mark.skipif(not _REAL_FFS.is_file(), reason="真实 .ffs 样例缺失")
    def test_real_hfss_sample(self):
        out = read_ffs(_REAL_FFS)
        assert out["n_freq"] == 3
        assert out["frequencies_hz"] == [76.0e9, 76.5e9, 77.0e9]
        assert out["power_radiated_accepted_stimulated"][0] == [1.0, 1.0, 1.0]
        assert out["power_radiated_accepted_stimulated"][1] == [0.1, 0.1, 0.1]
        assert out["phi_deg"].size == 361 and out["theta_deg"].size == 181
        assert out["phi_deg"][0] == 0.0 and out["phi_deg"][-1] == 360.0
        assert out["theta_deg"][0] == 0.0 and out["theta_deg"][-1] == 180.0
        # 审计字面量（2026-09-24 逐段 dump，#331）
        assert out["e_theta"][0, 0, 0] == complex(-0.0135909073,
                                                  0.0741441492)
        assert out["e_phi"][0, 0, 0] == complex(0.149240261, 0.505023316)
        assert out["e_theta"][2, -1, -1] == complex(-0.199513528,
                                                    -0.0975185757)


class TestSweInterface:
    def test_contract_placeholder(self):
        with pytest.raises(NotImplementedError, match="SWE"):
            spherical_wave_expansion(
                np.ones((3, 4), dtype=complex), np.ones((3, 4), dtype=complex),
                np.array([0.0, 45.0, 90.0]), np.arange(4.0), l_max=4)


class TestServiceEnvelope:
    def test_nf_to_farfield_and_ffs(self, tmp_path):
        from rfauto.service.nf_measurement_service import ffs_info, nf_to_farfield

        x = list(np.arange(-50e-3, 50.1e-3, 10e-3))
        ex, ey = _hertzian_dipole_plane_field(2.4e9, 1e-3,
                                              np.asarray(x), np.asarray(x),
                                              0.005)
        out = nf_to_farfield(
            x, x, 2.4e9, ex.real.tolist(), ex.imag.tolist(),
            ey.real.tolist(), ey.imag.tolist(), window="none",
            theta_deg=[10.0, 30.0, 50.0], phi_deg=[0.0])
        assert out["ok"] is True
        amp = [v for v in out["e_theta_amp"]]
        assert amp[0][0] < amp[1][0] < amp[2][0]  # 单调升
        bad = nf_to_farfield(x[:3], x[:3], 2.4e9, [[1, 1, 1]] * 3,
                             [[0] * 3] * 3, [[0] * 3] * 3, [[0] * 3] * 3)
        assert bad["ok"] is False and "采样点" in bad["error"]

        _write_min_ffs(tmp_path / "m.ffs")
        info = ffs_info(str(tmp_path / "m.ffs"))
        assert info["ok"] is True and info["n_freq"] == 2
        assert info["frequencies_hz"] == [1.0e9, 2.0e9]
        miss = ffs_info(str(tmp_path / "nope.ffs"))
        assert miss["ok"] is False and "不存在" in miss["error"]
