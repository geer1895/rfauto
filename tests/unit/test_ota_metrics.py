"""OTA/TRP 指标卡内核单测（QW-8，解析锚 + 网格收敛 + 守卫）。

确定性、无网络、无真机、纯 numpy。锚数值裁判（#118：小步长收敛数值 +
独立来源解析值，不赌自身推导）：
- 各向同性 0 dBi：TRP = P_tx（归一恒等式，逐位）、D = 0 dB；
- 半球模型（0 dBi / −inf）：TRP = P_tx/2 = −3.0102999566398 dBm 逐位、
  D = 3.0102999566398 dB（独立手算：∫∫G dΩ = 2π·1 → D = 4π·1/2π = 2；
  网格口径：θ 轴跳过 90° 节点，使不连续跳变落在梯形区间中点——节点落
  在跳变上时赤道界行全权归单侧，有一阶 O(h) 边界误差，另测收敛）；
- 短偶极子 sin²θ：D = 1.5（1.7609 dBi，∫₀^π sin³θ dθ = 4/3 独立闭式）；
- cos²θ 模型：D = 3.0（4.7712 dBi，∫₀^π cos²θ sinθ dθ = 2/3）；
- 半波偶极子 cos(π·cosθ/2)/sinθ：文献表值 D0 = 1.642（2.15 dBi，Balanis
  表 4.1，与 core/farfield.py 同锚）；scipy.integrate.quad 机器精度独立
  求积 = 1.640923（2.1509 dBi）——与文献表值差 0.07%，属文献舍入与机器
  精度之别，如实并记双源（不凑数）。
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.ota_metrics import (
    CDF_PERCENTILES,
    beam_efficiency,
    directivity_from_gain,
    eirp_cdf,
    ota_report_card,
    trp_from_gain,
)

_DBM_HALF = -3.0102999566398  # = 10·log10(1/2)，dBm
_DB_3 = 3.0102999566398  # = 10·log10(2)，dB


def _grid(dth: float = 0.5, dph: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """整球网格：θ 0..180 含两极，φ 开环 0..360−Δφ（周期梯形自动闭合）。"""
    theta = np.arange(0.0, 180.0 + 1e-9, dth)
    phi = np.arange(0.0, 360.0, dph)
    return theta, phi


def _hemisphere_grid(h: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """θ 轴跳过 90° 节点的整球网格（半球跳变落区间中点，见模块 docstring）。"""
    theta = np.concatenate([np.arange(0.0, 90.0, h),
                            np.arange(90.0 + h, 180.0 + 1e-9, h)])
    phi = np.arange(0.0, 360.0, 1.0)
    return theta, phi


def _hemisphere_gain(theta: np.ndarray, phi: np.ndarray) -> np.ndarray:
    """上半球 0 dBi / 下半球 −inf（线性域 0 功率）。"""
    return np.where(theta[:, None] < 90.0, 0.0, -np.inf) * np.ones(
        (1, phi.size))


def _db10(x: np.ndarray) -> np.ndarray:
    """10·log10（允许 0 → −inf，静默除零为构造意图）。"""
    with np.errstate(divide="ignore"):
        return 10.0 * np.log10(x)


class TestIsotropicAnchor:
    """各向同性锚：gain≡0 dBi → TRP=P_tx 归一恒等式、D=0 dB。"""

    def test_trp_equals_p_tx_norm_identity(self):
        th, ph = _grid()
        r = trp_from_gain(np.zeros((th.size, ph.size)), th, ph, 0.0)
        assert r["status"] == "ok"
        assert r["trp_w"] == pytest.approx(1e-3, rel=1e-12)  # 逐位级
        assert r["trp_dbm"] == pytest.approx(0.0, abs=1e-9)
        # 权重和诊断：整球归一后 Σw = 4π（原始梯形和含 sinθ 常量偏置 ~1e-5 相对）
        assert r["integral_weight_sum"] == pytest.approx(4 * np.pi, rel=1e-4)
        assert r["coverage_fraction"] == pytest.approx(1.0, abs=1e-3)

    def test_directivity_zero_db(self):
        th, ph = _grid()
        d = directivity_from_gain(np.zeros((th.size, ph.size)), th, ph, 0.0)
        assert d["d_db"] == pytest.approx(0.0, abs=1e-9)
        assert d["d_linear"] == pytest.approx(1.0, rel=1e-12)
        assert d["p_rad_w"] == pytest.approx(1e-3, rel=1e-12)
        assert d["p_max_w"] == pytest.approx(1e-3 / (4 * np.pi), rel=1e-12)

    def test_eirp_all_percentiles_equal_peak(self):
        th, ph = _grid()
        e = eirp_cdf(np.zeros((th.size, ph.size)), th, ph, 0.0)
        assert e["eirp_peak_dbm"] == 0.0  # 逐位：0 dBm + 0 dBi
        for p in CDF_PERCENTILES:
            assert e["cdf"][p] == 0.0

    def test_beam_efficiency_cap_fraction(self):
        th, ph = _grid(0.25, 1.0)
        r = beam_efficiency(np.zeros((th.size, ph.size)), th, ph,
                            cone_deg=60.0, boresight=(0.0, 0.0))
        # 各向同性球冠解析值 (1−cos α)/2（独立推导；网格边界效应 O(单元)）
        assert r["efficiency"] == pytest.approx(
            (1.0 - np.cos(np.deg2rad(60.0))) / 2.0, abs=1e-2)


class TestHemisphereAnchor:
    """半球锚：上 0 dBi / 下 −inf → TRP 减半、D = 3.0103 dB。"""

    def test_trp_halves_exact(self):
        th, ph = _hemisphere_grid()
        r = trp_from_gain(_hemisphere_gain(th, ph), th, ph, 0.0)
        assert r["trp_w"] == pytest.approx(0.5e-3, rel=1e-12)  # 逐位级
        assert r["trp_dbm"] == pytest.approx(_DBM_HALF, abs=1e-9)

    def test_directivity_3db_exact(self):
        th, ph = _hemisphere_grid()
        d = directivity_from_gain(_hemisphere_gain(th, ph), th, ph, 0.0)
        # 独立手算：U_max = P_tx/(4π)，Prad = P_tx/2 → D = 2（#118 口径）
        assert d["d_db"] == pytest.approx(_DB_3, abs=1e-9)
        assert d["d_linear"] == pytest.approx(2.0, rel=1e-12)

    def test_partition_identity_up_plus_lo_equals_iso(self):
        """互补掩码严格划分网格 → TRP_up + TRP_lo ≡ TRP_iso（归一恒等式）。"""
        th, ph = _grid()  # 含 90° 节点
        g_up = np.where(th[:, None] < 90.0, 0.0, -np.inf) * np.ones(
            (1, ph.size))
        g_lo = np.where(th[:, None] >= 90.0, 0.0, -np.inf) * np.ones(
            (1, ph.size))
        g_iso = np.zeros((th.size, ph.size))
        r_i = trp_from_gain(g_iso, th, ph, 0.0)["trp_w"]
        r_u = trp_from_gain(g_up, th, ph, 0.0)["trp_w"]
        r_l = trp_from_gain(g_lo, th, ph, 0.0)["trp_w"]
        assert (r_u + r_l) / r_i == pytest.approx(1.0, rel=1e-12)

    def test_equator_node_boundary_error_converges(self):
        """90° 节点落跳变上的一阶 O(h) 边界误差：步长减半误差减半。"""
        errs = []
        for h in (0.5, 0.25, 0.125):
            th = np.arange(0.0, 180.0 + 1e-9, h)
            ph = np.arange(0.0, 360.0, 1.0)
            g = np.where(th[:, None] <= 90.0, 0.0, -np.inf) * np.ones(
                (1, ph.size))
            r = trp_from_gain(g, th, ph, 0.0)
            errs.append(abs(r["trp_dbm"] - _DBM_HALF))
        assert errs[0] > errs[1] > errs[2]  # 单调收敛
        assert errs[2] < 0.01  # 0.125° 网格 < 0.01 dB


class TestDipoleAnchors:
    """偶极子解析锚（任务书三种口径的物理勘定，见模块 docstring）。"""

    @staticmethod
    def _d_from_pattern(theta_deg, phi_deg, gain_db_fn):
        g = gain_db_fn(np.deg2rad(theta_deg))[:, None] * np.ones(
            (1, phi_deg.size))
        return directivity_from_gain(g, theta_deg, phi_deg, 0.0)

    def test_short_dipole_sin2_d_1p5(self):
        th, ph = _grid(0.25, 1.0)
        d = self._d_from_pattern(
            th, ph, lambda t: _db10(np.sin(t) ** 2))
        # 独立闭式：∫₀^π sin³θ dθ = 4/3 → D = 4π/(2π·4/3) = 1.5
        assert d["d_linear"] == pytest.approx(1.5, rel=1e-4)
        assert d["d_db"] == pytest.approx(10.0 * np.log10(1.5), abs=1e-4)

    def test_cos2_pattern_d_3(self):
        th, ph = _grid(0.25, 1.0)
        d = self._d_from_pattern(
            th, ph, lambda t: 20.0 * np.log10(np.abs(np.cos(t))
                                               + 1e-300))
        # 独立闭式：∫₀^π cos²θ sinθ dθ = 2/3 → D = 4π/(2π·2/3) = 3.0
        assert d["d_linear"] == pytest.approx(3.0, rel=1e-4)

    def test_grid_convergence_step_halving(self):
        """sin²θ 模型步长收敛单调（#335 族口径：步长减半误差减）。"""
        errs = []
        for dth in (3.0, 1.5, 0.75, 0.375):
            th, ph = _grid(dth, 2.0)
            d = self._d_from_pattern(
                th, ph, lambda t: _db10(np.sin(t) ** 2))
            errs.append(abs(d["d_linear"] - 1.5))
        assert errs[0] > errs[1] > errs[2] > errs[3]
        assert errs[3] < 1e-4

    def test_half_wave_dipole_2p15dbi(self):
        """半波偶极子：文献表值 1.642（2.15 dBi，Balanis 表 4.1）+ quad 独立求积。"""
        from scipy.integrate import quad

        def fw(t: np.ndarray) -> np.ndarray:
            s = np.sin(t)
            with np.errstate(divide="ignore", invalid="ignore"):
                raw = np.cos(np.pi / 2.0 * np.cos(t)) / s
            return np.where(s < 1e-12, 1.0, np.nan_to_num(raw,
                                                          nan=1.0))

        val, _ = quad(lambda t: fw(np.array([t]))[0] ** 2 * np.sin(t),
                      0.0, np.pi, limit=500, epsabs=1e-12)
        d_ref = 2.0 / val  # F 归一后 D0 = 4π/(2π·I) = 2/I（独立方法）
        th = np.arange(0.0, 180.0 + 1e-9, 0.25)
        ph = np.arange(0.0, 360.0, 1.0)
        d = self._d_from_pattern(
            th, ph, lambda t: 20.0 * np.log10(np.abs(fw(t))))
        assert d["d_linear"] == pytest.approx(d_ref, rel=1e-3)  # 网格 vs quad
        assert d["d_linear"] == pytest.approx(1.642, abs=5e-3)  # 文献表值
        assert d["d_db"] == pytest.approx(2.15, abs=0.02)


class TestSinThetaWeightingTrap:
    """sinθ 加权陷阱：极向集中方向图的朴素平均与立体角加权严重背离。

    任务书原话"半球模型朴素平均差 √2 倍"在均匀对称网格上不成立（半球
    指示图的朴素平均恰 = 0.5 = 正确值，巧合相消）——加权正确性的严格
    反例是极冠：立体角单元随 sinθ 收缩，朴素平均多算极区近 2.5 倍。
    """

    def test_polar_cap_weighting_vs_naive_mean(self):
        th = np.concatenate([np.arange(0.0, 30.0, 0.25),
                             np.arange(30.25, 180.0 + 1e-9, 0.25)])
        ph = np.arange(0.0, 360.0, 1.0)
        g = np.where(th[:, None] <= 30.0, 0.0, -np.inf) * np.ones(
            (1, ph.size))
        r = trp_from_gain(g, th, ph, 0.0)
        # 独立闭式：球冠立体角 2π(1−cos30°) → TRP/P_tx = (1−cos30°)/2
        expect = (1.0 - np.cos(np.deg2rad(30.0))) / 2.0
        assert r["trp_w"] / 1e-3 == pytest.approx(expect, rel=1e-4)
        # 朴素无权平均（网格单元等权）多算极冠 > 2 倍——反例钉住加权正确性
        g_lin = np.where(g == 0.0, 1.0, 0.0)
        naive = float(np.mean(g_lin))
        assert naive / expect > 2.0


class TestEIRPCdf:
    """EIRP 峰值 + 立体角加权覆盖 CDF 分位表。"""

    def test_two_level_pattern_percentiles(self):
        th = np.concatenate([np.arange(0.0, 60.0, 0.5),
                             np.arange(60.5, 180.0 + 1e-9, 0.5)])
        ph = np.arange(0.0, 360.0, 1.0)
        g = np.where(th[:, None] <= 60.0, 10.0, -20.0) * np.ones(
            (1, ph.size))
        e = eirp_cdf(g, th, ph, 0.0)
        assert e["status"] == "ok"
        assert e["eirp_peak_dbm"] == 10.0  # 逐位
        # 球冠覆盖 = (1−cos60°)/2 = 25% → 50% 分位落 −20 dBi 块内
        assert e["cdf"][50] == -20.0
        # 95/99% 分位落 10 dBi 块内
        assert e["cdf"][95] == 10.0
        assert e["cdf"][99] == 10.0

    def test_eirp_hemisphere_upper_percentiles(self):
        th, ph = _hemisphere_grid()
        e = eirp_cdf(_hemisphere_gain(th, ph), th, ph, 0.0)
        assert e["eirp_peak_dbm"] == 0.0
        # 上半球占 50% 立体角 → 75/95/99% 分位均为 0 dBm（50% 落界不钉）
        for p in (75, 95, 99):
            assert e["cdf"][p] == 0.0


class TestBeamEfficiency:
    """波束效率：锥角扫描单调 + boresight 自动/显式对拍。"""

    @staticmethod
    def _gaussian_lobe(theta_deg, phi_deg, sigma_deg=3.0):
        """以 (0,0) 为轴的高斯瓣（线性域 exp(−α²/2σ²)）→ dBi。"""
        th = np.deg2rad(theta_deg)[:, None]
        # boresight=(0,0)：cosα = cosθ·1 + sinθ·0·cos(φ−0) = cosθ
        alpha = np.arccos(np.clip(np.cos(th), -1.0, 1.0))
        g_lin = np.exp(-alpha ** 2 / (2.0 * np.deg2rad(sigma_deg) ** 2))
        return _db10(g_lin) * np.ones((1, phi_deg.size))

    def test_gaussian_cone_sweep_monotone(self):
        th, ph = _grid(0.25, 1.0)
        g = self._gaussian_lobe(th, ph)
        assert g.shape == (th.size, ph.size)
        effs = [beam_efficiency(g, th, ph, cone_deg=c,
                                boresight=(0.0, 0.0))["efficiency"]
                for c in (2.0, 4.0, 6.0, 8.0, 10.0)]
        assert all(a < b for a, b in itertools.pairwise(effs))

    def test_auto_boresight_matches_explicit(self):
        th, ph = _grid(0.25, 1.0)
        g = self._gaussian_lobe(th, ph)
        auto = beam_efficiency(g, th, ph, cone_deg=6.0, boresight=None)
        explicit = beam_efficiency(g, th, ph, cone_deg=6.0,
                                   boresight=(0.0, 0.0))
        assert auto["boresight_source"] == "auto_peak"
        assert auto["boresight_deg"] == pytest.approx([0.0, 0.0], abs=1e-9)
        assert auto["efficiency"] == pytest.approx(explicit["efficiency"],
                                                   rel=1e-12)
        assert explicit["boresight_source"] == "explicit"

    def test_no_power_pattern_reports_degenerate(self):
        th, ph = _grid()
        g = np.full((th.size, ph.size), -np.inf)
        r = beam_efficiency(g, th, ph, cone_deg=30.0)
        assert r["status"] == "no_power"
        assert r["efficiency"] is None
        assert r["integrated_in"] == 0.0


class TestGuards:
    """守卫：非单调轴 / bool 拒收 / φ 超跨度 / 大片缺采样不硬算。"""

    def test_non_monotonic_theta_raises(self):
        with pytest.raises(ValueError, match="严格升序"):
            trp_from_gain(np.zeros((4, 4)), [0.0, 50.0, 40.0, 180.0],
                          [0.0, 90.0, 180.0, 270.0])

    def test_duplicate_axis_raises(self):
        with pytest.raises(ValueError, match="严格升序"):
            trp_from_gain(np.zeros((4, 4)), [0.0, 90.0, 90.0, 180.0],
                          [0.0, 90.0, 180.0, 270.0])

    @pytest.mark.parametrize("which", ["gain", "theta", "p_tx"])
    def test_bool_inputs_rejected(self, which):
        th, ph = _grid(1.0, 2.0)
        g = np.zeros((th.size, ph.size))
        kw = {"gain": {"gain_dbi": g.astype(bool)}, "theta": {"theta_deg":
              th.astype(bool)}, "p_tx": {"p_tx_dbm": True}}[which]
        with pytest.raises(ValueError, match="bool"):
            trp_from_gain(kw.get("gain_dbi", g),
                          kw.get("theta_deg", th), ph,
                          kw.get("p_tx_dbm", 0.0))

    def test_bool_cone_rejected(self):
        th, ph = _grid()
        with pytest.raises(ValueError, match="bool"):
            beam_efficiency(np.zeros((th.size, ph.size)), th, ph, cone_deg=True)

    def test_phi_overspan_raises(self):
        th, _ = _grid()
        with pytest.raises(ValueError, match="超过"):
            trp_from_gain(np.zeros((th.size, 38)), th,
                          np.arange(0.0, 380.0, 10.0))  # 跨度 370° > 360°

    def test_insufficient_coverage_refuses_hard_compute(self):
        th, ph = _grid()
        g = np.zeros((th.size, ph.size))
        g[th > 45.0, :] = np.nan  # 有效域 = 45° 球冠 ≈ 14.6% 立体角
        r = trp_from_gain(g, th, ph, 0.0)
        assert r["status"] == "insufficient_coverage"
        assert r["coverage_fraction"] == pytest.approx(
            (1.0 - np.cos(np.deg2rad(45.0))) / 2.0, abs=0.01)
        assert "trp_w" not in r
        d = directivity_from_gain(g, th, ph, 0.0)
        assert d["status"] == "insufficient_coverage"
        e = eirp_cdf(g, th, ph, 0.0)
        assert e["status"] == "insufficient_coverage"

    def test_nan_band_computed_with_annotation(self):
        th, ph = _grid()
        g = np.zeros((th.size, ph.size))
        g[th > 90.0, :] = np.nan  # 缺下半球（覆盖 50%，不触发拒算）
        r = trp_from_gain(g, th, ph, 0.0)
        assert r["status"] == "ok"
        assert r["trp_w"] / 1e-3 == pytest.approx(0.5, rel=1e-2)  # 下界口径
        q = r["grid_quality"]
        assert q["coverage_fraction"] == pytest.approx(0.5, abs=0.01)
        assert len(q["missing_theta_bands_deg"]) == 1
        assert q["missing_theta_bands_deg"][0]["theta_start_deg"] == \
            pytest.approx(90.5, abs=0.3)
        assert q["nan_cell_fraction"] == pytest.approx(
            float((th > 90.0).mean()), rel=1e-9)
        assert any("NaN" in w for w in q["warnings"])

    def test_phi_partial_coverage_annotated(self):
        th = np.arange(0.0, 180.0 + 1e-9, 1.0)
        ph = np.arange(0.0, 195.0, 5.0)
        r = trp_from_gain(np.zeros((th.size, ph.size)), th, ph, 0.0)
        assert r["status"] == "ok"  # 覆盖 ~54% ≥ 50% 门
        assert r["grid_quality"]["phi_ring_closed"] is False
        assert r["coverage_fraction"] == pytest.approx(195.0 / 360.0,
                                                       abs=0.02)


class TestReportCard:
    """报告卡组装与网格质量注记。"""

    def test_card_assembly_and_quality(self):
        th, ph = _grid()
        card = ota_report_card(np.zeros((th.size, ph.size)), th, ph,
                               p_tx_dbm=30.0, cone_deg=45.0)
        for key in ("trp", "directivity", "eirp", "beam_efficiency"):
            assert card[key]["status"] == "ok"
        assert card["p_tx_dbm"] == 30.0
        assert card["trp"]["trp_dbm"] == pytest.approx(30.0, abs=1e-9)
        q = card["grid_quality"]
        assert q["d_theta_deg"] == pytest.approx(0.5)
        assert q["d_phi_deg"] == pytest.approx(1.0)
        assert q["full_sphere"] is True
        assert q["weight_normalization_applied"] is True
        assert q["integral_weight_sum"] == pytest.approx(4 * np.pi, rel=1e-4)
        assert q["missing_theta_bands_deg"] == []
        assert card["beam_efficiency"]["cone_deg"] == 45.0

    def test_card_flags_insufficient_coverage(self):
        th, ph = _grid()
        g = np.zeros((th.size, ph.size))
        g[th > 20.0, :] = np.nan
        card = ota_report_card(g, th, ph, p_tx_dbm=0.0)
        assert card["trp"]["status"] == "insufficient_coverage"
        assert card["grid_quality"]["coverage_fraction"] < 0.5
