"""nf2ff 远场确定性内核单测（WP4.1 / D4，文献口径）。

确定性、无网络、无真机。文献锚（Balanis《Antenna Theory》表 4.1 / §4.4，
D4 验收列"文献口径"）：
- 无方向性点源 D0 = 1（0 dBi）；
- 电流元（Hertzian dipole，F=sinθ）D0 = 1.5（1.761 dBi）；
- 无耗半波偶极子（F=cos(π/2·cosθ)/sinθ）D0 ≈ 1.642（2.15 dBi）、HPBW ≈ 78°。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.farfield import (
    correct_pec_mirror,
    dmax_from_grid,
    dmax_from_pattern,
    efficiency,
    front_to_back_db,
    gain_max_db,
    hemisphere_power,
    hpbw_deg,
    parse_farfield_3d_csv,
    parse_farfield_cut_csv,
    pattern_db,
    pattern_power_from_db,
    pec_mirror_factor,
    power_budget_closure,
    summarize_cut,
    write_farfield_cut_csv,
)


def _sphere_grid(step_deg: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    theta = np.deg2rad(np.arange(0.0, 180.0 + step_deg, step_deg))
    # φ 轴闭区间覆盖 0..360°（周期端点各计半权，梯形积分不重复计数）
    phi = np.deg2rad(np.arange(0.0, 360.0 + step_deg * 4, step_deg * 4))
    return theta, phi


def _half_wave_pattern(theta_rad: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    """半波偶极子归一化场型 F(θ)=cos(π/2·cosθ)/sinθ（z 向振子）。"""
    return np.cos(np.pi / 2 * np.cos(theta_rad)) / (np.sin(theta_rad) + eps)


class TestDirectivityLiterature:
    """方向性文献锚（数值裁判：球面积分 vs 教科书闭式，#118 精神）。"""

    def test_isotropic_source_dmax_is_unity(self):
        theta, phi = _sphere_grid()
        pg = np.ones((theta.size, phi.size))
        assert dmax_from_grid(pg, theta, phi) == pytest.approx(1.0, rel=1e-4)

    def test_hertzian_dipole_d0_1_5(self):
        theta, phi = _sphere_grid()
        f2 = np.broadcast_to((np.sin(theta) ** 2)[:, None], (theta.size, phi.size)).copy()
        # D0 = 4π/∫F²dΩ = 1.5（1.761 dBi）
        assert dmax_from_grid(f2, theta, phi) == pytest.approx(1.5, rel=1e-3)

    def test_half_wave_dipole_d0_2_15dbi(self):
        theta, phi = _sphere_grid()
        f = _half_wave_pattern(theta)
        f2 = np.broadcast_to((f ** 2)[:, None], (theta.size, phi.size)).copy()
        # Balanis 表 4.1：D0 = 1.642 → 2.15 dBi
        assert dmax_from_grid(f2, theta, phi) == pytest.approx(1.642, abs=0.01)
        assert dmax_from_grid(f2, theta, phi) == pytest.approx(10 ** (2.15 / 10),
                                                              rel=0.01)

    def test_directivity_grid_shape_mismatch_raises(self):
        theta, phi = _sphere_grid(step_deg=5.0)
        with pytest.raises(ValueError, match="形状"):
            dmax_from_grid(np.ones((3, 3)), theta, phi)


class TestPatternDb:
    def test_peak_normalized_and_half_power_point(self):
        theta = np.arange(-180.0, 181.0, 1.0)
        f = _half_wave_pattern(np.deg2rad(theta))
        pdb = pattern_db(np.abs(f))
        assert pdb.max() == pytest.approx(0.0, abs=1e-9)
        # 峰在 θ=90°；HPBW≈78° → 半功率点在 90±39=51°/129°：|F(51°)|=0.707
        half = np.interp(51.0, theta, pdb)
        assert half == pytest.approx(-3.01, abs=0.1)

    def test_all_zero_field_returns_nan(self):
        pdb = pattern_db(np.zeros(5))
        assert np.all(np.isnan(pdb))


class TestHpbw:
    def test_half_wave_hpbw_about_78_deg(self):
        theta = np.arange(-180.0, 181.0, 1.0)
        pdb = pattern_db(np.abs(_half_wave_pattern(np.deg2rad(theta))))
        w = hpbw_deg(theta, pdb)
        assert w is not None
        assert w == pytest.approx(78.0, abs=3.0)  # Balanis 表 4.1：78°

    def test_hertzian_hpbw_90_deg(self):
        theta = np.arange(-180.0, 181.0, 1.0)
        pdb = pattern_db(np.abs(np.sin(np.deg2rad(theta))))
        assert hpbw_deg(theta, pdb) == pytest.approx(90.0, abs=1.5)

    def test_clipped_lobe_returns_none(self):
        # 主瓣贴边界且无 −3dB 交叉 → 如实 None，不虚构
        theta = np.arange(0.0, 30.0, 1.0)
        pdb = np.full(theta.size, 0.0)
        assert hpbw_deg(theta, pdb) is None

    def test_peak_wrapped_near_boundary(self):
        # 峰在 ±180 边界（cos² 型，峰在 −180/0/180）回卷后主瓣居中仍可测
        theta = np.arange(-180.0, 181.0, 1.0)
        f = np.abs(np.cos(np.deg2rad(theta)))  # 峰在 0 与 ±180
        w = hpbw_deg(theta, pattern_db(f))
        assert w is not None and 80.0 < w < 100.0  # cos² 型 HPBW=90°


class TestEfficiencyGain:
    def test_efficiency_identity(self):
        assert efficiency(0.9, 1.0) == pytest.approx(0.9)
        assert efficiency(0.81, 0.9) == pytest.approx(0.9)

    def test_efficiency_nonpositive_acceptance_is_none(self):
        assert efficiency(0.5, 0.0) is None
        assert efficiency(0.5, -1.0) is None

    def test_gain_is_directivity_plus_ten_log_eta(self):
        g = gain_max_db(2.15, 0.85)
        assert g == pytest.approx(2.15 + 10 * np.log10(0.85), abs=1e-9)
        assert gain_max_db(2.15, None) is None
        assert gain_max_db(2.15, 0.0) is None


class TestFrontToBack:
    def test_symmetric_pattern_fb_zero(self):
        theta = np.arange(-180.0, 181.0, 1.0)
        pdb = pattern_db(np.abs(_half_wave_pattern(np.deg2rad(theta))))
        assert front_to_back_db(theta, pdb) == pytest.approx(0.0, abs=0.5)

    def test_known_asymmetric_fb(self):
        theta = np.arange(-180.0, 181.0, 1.0)
        pdb = np.maximum(-20 * np.abs(theta) / 180.0, -40.0)
        # 峰 0dB @0°；背向 180° 处 = −20dB → F/B = 20dB
        assert front_to_back_db(theta, pdb) == pytest.approx(20.0, abs=0.6)


class TestPowerBudget:
    def test_closure_with_absorbed_power(self):
        # 官方 Dipole SAR 教程口径：|P_acc − Prad − P_abs|/P_acc
        assert power_budget_closure(1.0, 0.9, 0.09) == pytest.approx(0.01)
        assert power_budget_closure(1.0, 0.98) == pytest.approx(0.02)

    def test_closure_nonpositive_acceptance_is_none(self):
        assert power_budget_closure(0.0, 0.1) is None


class TestCutCsvRoundTrip:
    def _rows(self) -> list[dict[str, float]]:
        rows = []
        for phi in (0.0, 90.0):
            for th in range(-180, 181, 2):
                e = abs(float(np.sin(np.deg2rad(th)))) + 0.1
                rows.append({"phi_deg": phi, "theta_deg": float(th),
                             "re_e_theta": e, "im_e_theta": 0.0,
                             "re_e_phi": 0.0, "im_e_phi": 0.0,
                             "e_norm": e, "p_rad": e * e})
        return rows

    def test_write_parse_roundtrip_and_summarize(self, tmp_path):
        path = tmp_path / "farfield_cut.csv"
        rows = self._rows()
        write_farfield_cut_csv(path, rows)
        cuts = parse_farfield_cut_csv(path)
        assert [c["phi_deg"] for c in cuts] == [0.0, 90.0]
        c0 = cuts[0]
        assert c0["theta_deg"].size == 181
        assert c0["e_norm"][0] == pytest.approx(rows[0]["e_norm"])
        # e_theta 复原 = 复数
        assert np.allclose(c0["e_theta"], c0["e_norm"] + 0j)
        s = summarize_cut(c0["theta_deg"], c0["e_norm"])
        assert s["peak_theta_deg"] in (90.0, -90.0)
        assert s["hpbw_deg"] is not None and 80 < s["hpbw_deg"] < 140

    def test_parse_missing_file_raises(self, tmp_path):
        from rfauto.core.farfield import parse_farfield_cut_csv as parse

        with pytest.raises(FileNotFoundError):
            parse(tmp_path / "nope.csv")


# ─── PEC 地镜像修正（W2⑥a，openEMS nf2ff 单镜像面 Prad 双计）───────────────

class TestPecMirrorCorrection:
    """判据锚：runs/patch_field_smoke 真机数（源码 nf2ff_calc.cpp AddPlane +
    真机 farfield_3d.h5 下/上半球比 1.0000 双证）。"""

    PATCH_META: ClassVar[dict] = {
        "ok": True, "template": "patch", "f_res_ghz": 2.212,
        "prad_w": 1.4047655921302781e-25,
        "p_acc_w": 1.1301579524440128e-25,
        "dmax_linear": 1.7837598913888713,
        "dmax_dbi": 2.5133639439947677,
        "efficiency": 1.242981646142838,
        "gain_max_dbi": 3.4580111029957967,
        "power_budget_closure": 0.2429816461428379,
        "nf2ff_box_start_m": [-0.082305, -0.082305, 0.0],
        "nf2ff_box_stop_m": [0.082305, 0.082305, 0.022813],
    }

    def test_factor_detection_by_box_geometry(self):
        assert pec_mirror_factor(self.PATCH_META) == 2.0
        dipole = dict(self.PATCH_META,
                      nf2ff_box_start_m=[-0.0793, -0.0793, -0.0193])
        assert pec_mirror_factor(dipole) == 1.0
        assert pec_mirror_factor({"template": "patch"}) == 1.0  # 缺盒坐标不猜

    def test_patch_smoke_numbers(self):
        out = correct_pec_mirror(self.PATCH_META)
        assert out["pec_mirror_factor"] == 2.0
        # η 1.243 → 0.6215（<1，RO4350B h=0.508 薄基板腔模型区间）
        assert out["efficiency"] == pytest.approx(0.6215, abs=1e-3)
        assert out["prad_w"] == pytest.approx(
            self.PATCH_META["prad_w"] / 2, rel=1e-12)
        assert out["dmax_linear"] == pytest.approx(3.5675, abs=1e-3)
        assert out["dmax_dbi"] == pytest.approx(5.524, abs=1e-2)
        # 不变量：G = 4πU_max/P_acc 与镜像因子无关 → 增益修正前后不变
        assert out["gain_max_dbi"] == pytest.approx(
            self.PATCH_META["gain_max_dbi"], abs=1e-6)
        assert out["power_budget_closure"] == pytest.approx(0.3785, abs=1e-3)
        # 修正前原值留痕（不凑绿：1.24 的病值保存在 raw）
        assert out["raw"]["efficiency"] == pytest.approx(1.242981646, rel=1e-9)

    def test_synthetic_known_eta_closed_form(self):
        # 合成已知 η：真 η=0.8 的镜像件 → 引擎报 Prad=2×0.8、Dmax=½·4.0
        meta = {
            "prad_w": 1.6, "p_acc_w": 1.0, "dmax_linear": 2.0,
            "dmax_dbi": 10 * np.log10(2.0), "efficiency": 1.6,
            "gain_max_dbi": 10 * np.log10(3.2),
            "power_budget_closure": 0.6,
            "nf2ff_box_start_m": [0.0, 0.0, 0.0],
        }
        out = correct_pec_mirror(meta)
        assert out["efficiency"] == pytest.approx(0.8)
        assert out["dmax_linear"] == pytest.approx(4.0)
        assert out["gain_max_dbi"] == pytest.approx(10 * np.log10(3.2))
        assert out["power_budget_closure"] == pytest.approx(0.2)

    def test_free_space_untouched(self):
        meta = {"prad_w": 3.4e-27, "p_acc_w": 3.5e-27,
                "efficiency": 3.4 / 3.5, "template": "dipole",
                "nf2ff_box_start_m": [0, 0, -0.0193]}
        out = correct_pec_mirror(meta)
        assert out["pec_mirror_factor"] == 1.0
        assert "raw" not in out
        assert out["efficiency"] == pytest.approx(3.4 / 3.5)
        assert out["prad_w"] == meta["prad_w"]

    def test_input_dict_not_mutated(self):
        import copy

        before = copy.deepcopy(self.PATCH_META)
        correct_pec_mirror(self.PATCH_META)
        assert before == self.PATCH_META


class TestHemispherePower:
    """半球积分闭式锚：U=cos²θ 镜像对称图（PEC 地理想偶极子图像）。"""

    def _grid(self, step_deg=1.0, phi_full=True):
        th = np.deg2rad(np.arange(0.0, 180.0 + 1e-9, step_deg))
        # 开区间网格（0..358）或四个半平面：二者积分应一致（自动补 2π 闭合）
        ph = (np.deg2rad(np.arange(0.0, 360.0, 2.0)) if phi_full
              else np.deg2rad(np.array([0.0, 90.0, 180.0, 270.0])))
        u = np.broadcast_to((np.cos(th) ** 2)[:, None], (th.size, ph.size))
        return u.copy(), th, ph

    def test_mirrored_cos2_closed_form(self):
        # ∫upper = 2π∫₀^π/2 cos²θ sinθ dθ = 2π/3；full = 2×upper；lower/upper=1
        u, th, ph = self._grid()
        hp = hemisphere_power(u, th, ph)
        assert hp["upper"] == pytest.approx(2 * np.pi / 3, rel=1e-3)
        assert hp["lower"] == pytest.approx(2 * np.pi / 3, rel=1e-3)
        assert hp["lower"] / hp["upper"] == pytest.approx(1.0, abs=1e-6)
        # D_upper = 4π·1/(2π/3) = 6；D_full = 3
        assert dmax_from_pattern(u, th, ph, "upper") == pytest.approx(6.0,
                                                                      rel=1e-3)
        assert dmax_from_pattern(u, th, ph, "full") == pytest.approx(3.0,
                                                                     rel=1e-3)

    def test_open_phi_grid_auto_closes(self):
        u1, th1, ph1 = self._grid(phi_full=False)
        u2, th2, ph2 = self._grid()
        assert (hemisphere_power(u1, th1, ph1)["full"]
                == pytest.approx(hemisphere_power(u2, th2, ph2)["full"],
                                 rel=1e-6))

    def test_two_plane_phi_raises(self):
        th = np.deg2rad(np.arange(0.0, 181.0, 1.0))
        ph = np.deg2rad(np.array([0.0, 90.0]))
        u = np.ones((th.size, 2))
        with pytest.raises(ValueError, match="3 点"):
            hemisphere_power(u, th, ph)

    def test_pattern_power_from_db(self):
        out = pattern_power_from_db(np.array([0.0, -3.0103, -10.0, np.nan]))
        assert out[:3] == pytest.approx([1.0, 0.5, 0.1], rel=1e-4)
        assert out[3] == 0.0


class TestFarfield3dCsv:
    def test_roundtrip_and_pattern_dmax(self, tmp_path):
        path = tmp_path / "farfield3d.csv"
        th_deg = np.arange(0.0, 181.0, 5.0)
        ph_deg = np.arange(0.0, 360.0, 5.0)
        lines = ["theta_deg,phi_deg,e_norm_db"]
        for t in th_deg:
            for p in ph_deg:
                v = np.sin(np.deg2rad(t))  # Hertzian 场型 F=sinθ
                db = 20 * np.log10(max(v, 1e-300))
                lines.append(f"{t},{p},{db}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        th, ph, grid = parse_farfield_3d_csv(path)
        assert grid.shape == (th.size, ph.size) == (37, 72)
        assert grid[0, 0] == pytest.approx(-6000.0, abs=1e3)  # 谷底大负值
        assert grid[int(np.argmax(th == 90.0)), 5] == pytest.approx(0.0,
                                                                    abs=1e-9)
        u = pattern_power_from_db(grid)
        # D = 4π/∫sin²θ dΩ = 1.5（1.761 dBi）
        assert dmax_from_pattern(u, np.deg2rad(th), np.deg2rad(ph)) \
            == pytest.approx(1.5, rel=5e-3)
