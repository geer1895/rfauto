"""微带全族扩展四键锚树（架构批 W15-S2 席，R3_domain_expansion §④ A1 余量
+损耗/接地过渡族收口：十字结/线衰减率/接地过孔/开路端辐射电导）。

数值断言口径（#118 锚先独立实测再写死，锚值=开工日独立算术预算——测试
内表达式路径独立于键内实现（原始 SI 常数内联+独立 skrf media 构造+独立
公式转录，不消费模块系数常量）；#122 三态/约定档如实不凑绿；网源逐字在
内部证据目录
_w15s2_constants.h/_w15s2_sdsmt_patch.pdf/_w15s2_msant.pdf）：

- 微带十字结（microstrip_cross_parasitics）：①系数转录锚=测试内独立算术
  逐位（mscross.cpp calcCap/calcInd/手册 11.226-11.230 原文常数内联；
  等臂名义点 W/h=2 氧化铝 0.635mm@10GHz）；②εr=9.9 → 四臂修正恒 1.0
  逐位（手册式 11.231 两路调用全同=同构恒等锚）；③等臂对称 C1..C4/
  L1..L4 逐位；④f→0 电感全短接=理想四口结（50Ω 等臂 S_ii→−0.5、
  S_ij→+0.5，闭式）；⑤无耗 LC 幺正 |SᴴS−I|≤1e-9+互易 S=Sᵀ（1e-12）；
  ⑥C 拟合域越界（本臂 W/h>3、对臂平均 W/h>3）显式拒绝；⑦L5<0 标记位
  （手册明示模型固有）。
- 微带衰减率（microstrip_attenuation）：①Rs/Ki/Kr/αc/αd 全链转录锚=
  独立算术逐位（msline.cpp analyseLoss+手册 11.79-11.83 原文常数内联+
  独立 skrf HJ media）；②t=0 → αc==0/skin_depth None 逐位（qucsator
  同构）；③Δ=0 → Kr==1.0、tanδ=0 → αd==0 逐位；④t<3δ 越窗标记位
  （手册 Ki validity；qucsator WARNING 放行同构）；⑤αd 同式同仓双源
  独立转录面（thermal_iteration 同形态，公式级对拍）；⑥域守卫（εr≤1、
  tanδ<0、t<0、Δ<0 显式拒绝）。
- 接地过孔（microstrip_via_short）：①R_dc/f_δ/R(f)/L 转录锚=独立算术
  逐位（msvia.cpp calcResistance/手册 11.232-11.234 原文常数内联）；
  ②Microwaves101 工程带锚：2mil GaAs D/H=0.5 → L∈[8,12] pH（手册形态
  9.39pH 相合——qucsator 漏 2π 形态 ~59pH 出带，偏差注记的数值锤）；
  ③h≫r 渐近 L→(μ0h/2π)(ln(2h/r)−1.5)（2% 带）；④无损极限 σ→∞ →
  R→0 → |S11|²+|S21|²=1（1e-12，纯电抗串联网络幺正）；⑤s21 独立复算
  逐位；⑥validity h<0.03λ0 显式拒绝+t<r 结构守卫。
- 开路端辐射电导（microstrip_open_end_radiation）：①两极限转录锚逐位
  （窄槽 (1/90)(W/λ0)² / 宽槽 (1/120)(W/λ0)，SDSMT 讲义逐字）；
  ②分段点连续逐位（x=1、x=2 两侧同值——本键声明的工程内插约定自洽，
  #122 约定档如实）；③宽槽渐近同仓对拍：键 G 与 Balanis 单槽积分渐近
  G1=(W/120λ0)(1−(k0h)²/24) 残差 ≤(k0h)²/24·1.05（synthesis.
  patch_rin_edge_balanis 同源公式独立转录）；④损耗正切/Γ 独立复算
  逐位+|Γ|≤1；⑤域守卫（εr<1 显式拒绝）。
"""

from __future__ import annotations

import math
from typing import ClassVar

import pytest

from rfauto.core.calc_families.microstrip_extra import (
    _open_end_radiation_s,
    microstrip_attenuation,
    microstrip_cross_parasitics,
    microstrip_open_end_radiation,
    microstrip_via_short,
)

# 测试内独立物理常数（原始 SI，不消费模块常量——#118）
_C0 = 299792458.0
_MU0 = 4.0e-7 * math.pi
_ETA0 = 376.73031346958504364963


def _hj_media(w_mm: float, h_mm: float, er: float, f_ghz: float):
    """独立 skrf HJ media 构造（不消费键内 helper——#118 路径分离）。"""
    import skrf

    return skrf.media.MLine(
        frequency=skrf.Frequency(f_ghz, f_ghz, 1, unit="GHz"),
        w=w_mm * 1e-3, h=h_mm * 1e-3, ep_r=er, tand=0.0,
        model="hammerstadjensen",
    )


# ─── 微带十字结 ─────────────────────────────────────────────────────────────

def _cross_expected(w_mm: float, h_mm: float) -> tuple[float, float, float]:
    """mscross.cpp calcCap/calcInd/手册 11.226-11.230 独立转录（等臂名义点）。

    本函数只服务等臂名义点（W1h=W2h=w/h）——非对称参数化路径走 qucsator
    对臂平均语义，由键内实现自证（测试不重抄装配面，#118 独立路径原则）。"""
    w_m = w_mm * 1e-3
    h_m = h_mm * 1e-3
    w1h = w_mm / h_mm
    w2h = w1h                      # 等臂：对臂平均==本臂
    x = (math.log10(w1h) * (86.6 * w2h - 30.9 * math.sqrt(w2h) + 367.0)
         + w2h ** 3 + 74.0 * w2h + 130.0)
    cap = 1e-12 * w_m * (0.25 * x * w1h ** (-1.0 / 3.0) - 60.0
                         + 0.5 / w2h - 0.375 * w1h * (1.0 - w2h))
    y = 165.6 * w2h + 31.2 * math.sqrt(w2h) - 11.8 * w2h ** 2
    ind = 1e-9 * h_m * (y * w1h - 32.0 * w2h + 3.0) * w1h ** (-1.5)
    l5 = 1e-9 * h_m * (5.0 * w2h * math.cos(math.pi / 2.0 * (1.5 - w1h))
                       - (1.0 + 7.0 / w1h) / w2h - 337.5) * 0.8
    return cap, ind, l5


class TestCrossParasitics:
    KW: ClassVar[dict] = dict(w1_mm=1.27, w2_mm=1.27, w3_mm=1.27, w4_mm=1.27,
              h_mm=0.635, epsilon_r=9.9, freq_ghz=10.0)

    def test_transcription_anchor(self):
        cap, ind, l5 = _cross_expected(1.27, 0.635)
        r = microstrip_cross_parasitics(**self.KW)
        assert r["c_arm1_f"] == pytest.approx(cap, rel=1e-12)
        assert r["l_arm1_h"] == pytest.approx(ind, rel=1e-12)
        assert r["l5_center_h"] == pytest.approx(l5, rel=1e-12)

    def test_epsr_9_9_correction_is_exact_one(self):
        r = microstrip_cross_parasitics(**self.KW)
        for k in ("cap_correction_1", "cap_correction_2",
                  "cap_correction_3", "cap_correction_4"):
            assert r[k] == 1.0

    def test_equal_arm_symmetry_exact(self):
        r = microstrip_cross_parasitics(**self.KW)
        assert r["c_arm1_f"] == r["c_arm2_f"] == r["c_arm3_f"] == r["c_arm4_f"]
        assert r["l_arm1_h"] == r["l_arm2_h"] == r["l_arm3_h"] \
            == r["l_arm4_h"]

    def test_s_matrix_shape_reciprocal_unitary(self):
        r = microstrip_cross_parasitics(**self.KW)
        s = r["s_matrix"]
        assert len(s) == 4 and all(len(row) == 4 for row in s)
        assert all(len(z) == 2 for row in s for z in row)
        import numpy as np

        m = np.array([[complex(z[0], z[1]) for z in row] for row in s])
        assert np.max(np.abs(m - m.T)) <= 1e-12          # 互易（Y 对称）
        eye = np.eye(4)
        assert np.max(np.abs(m.conj().T @ m - eye)) <= 1e-9  # 无耗幺正

    def test_dc_limit_ideal_fourway_junction(self):
        r = microstrip_cross_parasitics(
            **{**self.KW, "freq_ghz": 1e-4})
        s = r["s_matrix"]
        for i in range(4):
            assert abs(s[i][i][0] + 0.5) <= 1e-6
            # 虚部=O(ωL/Z0) 趋零（f=1e-4GHz 实测 ~9e-7）
            assert abs(s[i][i][1]) <= 1e-5
        for i in range(4):
            for j in range(4):
                if i != j:
                    assert abs(s[i][j][0] - 0.5) <= 1e-6
                    assert abs(s[i][j][1]) <= 1e-5

    def test_center_inductance_negative_flag(self):
        r = microstrip_cross_parasitics(**self.KW)
        assert r["center_inductance_negative"] is True
        assert r["l5_center_h"] < 0.0

    def test_cap_domain_guards(self):
        with pytest.raises(ValueError, match="拟合域"):
            microstrip_cross_parasitics(
                **{**self.KW, "w1_mm": 4.0})          # 本臂 W/h=6.3>3
        with pytest.raises(ValueError, match="拟合域"):
            microstrip_cross_parasitics(
                **{**self.KW, "w2_mm": 6.0, "w4_mm": 6.0})  # 对臂平均>3

    def test_deterministic(self):
        assert (microstrip_cross_parasitics(**self.KW)
                == microstrip_cross_parasitics(**self.KW))


# ─── 微带衰减率 ─────────────────────────────────────────────────────────────

class TestAttenuation:
    KW: ClassVar[dict] = dict(width_mm=1.27, h_mm=0.635, epsilon_r=9.9, freq_ghz=10.0,
              tan_delta=0.001, thickness_um=17.5, roughness_rms_um=1.0)

    def test_full_chain_transcription_anchor(self):
        media = _hj_media(1.27, 0.635, 9.9, 10.0)
        z0 = float(abs(complex(media.z0[0])))
        eeff = float(complex(media.ep_reff[0]).real)
        f = 10.0e9
        rho = 1.0 / 5.8e7
        rs = math.sqrt(math.pi * f * _MU0 * rho)               # 11.81
        delta = math.sqrt(rho / (math.pi * f * _MU0))
        ki = math.exp(-1.2 * (z0 / _ETA0) ** 0.7)              # 11.82
        kr = 1.0 + (2.0 / math.pi) * math.atan(1.4 * (1e-6 / delta) ** 2)
        ac = rs / (z0 * 1.27e-3) * ki * kr                     # 11.80
        ad = (math.pi * f / _C0) * (9.9 / math.sqrt(eeff)) \
            * ((eeff - 1.0) / (9.9 - 1.0)) * 0.001             # 11.79
        # δ 同式异形 float 噪声注记：键内消费 conductor_loss.skin_depth
        # （√(2/(ωμσ)) 形态），本测试独立转录 √(ρ/(πfμ)) 形态——数学恒等、
        # float 路径差 ~2.7e-10，经 Kr(δ) 传入 αc，故 αc/Kr/δ 带放至 1e-8
        # （z0/εeff/ki/αd 不经 δ，保持 1e-12）
        r = microstrip_attenuation(**self.KW)
        assert r["z0_ohm"] == pytest.approx(z0, rel=1e-12)
        assert r["eps_eff"] == pytest.approx(eeff, rel=1e-12)
        assert r["alpha_conductor_np_per_m"] == pytest.approx(ac, rel=1e-8)
        assert r["alpha_dielectric_np_per_m"] == pytest.approx(ad, rel=1e-12)
        assert r["alpha_total_np_per_m"] == pytest.approx(ac + ad, rel=1e-9)
        assert r["ki_current_factor"] == pytest.approx(ki, rel=1e-12)
        assert r["kr_roughness_factor"] == pytest.approx(kr, rel=1e-8)
        assert r["skin_depth_m"] == pytest.approx(delta, rel=1e-8)

    def test_zero_thickness_no_conductor_loss(self):
        r = microstrip_attenuation(
            width_mm=1.27, h_mm=0.635, epsilon_r=9.9, freq_ghz=10.0)
        assert r["alpha_conductor_np_per_m"] == 0.0
        assert r["skin_depth_m"] is None
        assert r["ki_current_factor"] is None
        assert r["thickness_below_3_skin_depths"] is None

    def test_zero_roughness_zero_tand_exact(self):
        r = microstrip_attenuation(
            width_mm=1.27, h_mm=0.635, epsilon_r=9.9, freq_ghz=10.0,
            thickness_um=17.5)
        assert r["kr_roughness_factor"] == 1.0
        assert r["alpha_dielectric_np_per_m"] == 0.0
        assert r["alpha_total_np_per_m"] == r["alpha_conductor_np_per_m"]

    def test_below_3_skin_depth_flag(self):
        # t=1µm < 3δ≈1.98µm @10GHz 铜 → 标记位 True（qucsator WARNING 同构）
        r = microstrip_attenuation(
            width_mm=1.27, h_mm=0.635, epsilon_r=9.9, freq_ghz=10.0,
            thickness_um=1.0)
        assert r["thickness_below_3_skin_depths"] is True
        r2 = microstrip_attenuation(**self.KW)   # t=17.5µm ≫ 3δ
        assert r2["thickness_below_3_skin_depths"] is False

    @pytest.mark.parametrize("kw", [
        {"epsilon_r": 1.0}, {"tan_delta": -0.1},
        {"thickness_um": -1.0}, {"roughness_rms_um": -0.5},
    ])
    def test_domain_guards(self, kw):
        base = dict(width_mm=1.27, h_mm=0.635, epsilon_r=9.9, freq_ghz=10.0)
        base.update(kw)
        with pytest.raises(ValueError):
            microstrip_attenuation(**base)

    def test_deterministic(self):
        assert (microstrip_attenuation(**self.KW)
                == microstrip_attenuation(**self.KW))


# ─── 接地过孔 ───────────────────────────────────────────────────────────────

class TestViaShort:
    KW: ClassVar[dict] = dict(h_mm=0.254, diameter_mm=0.3, freq_ghz=10.0, thickness_um=35.0)

    def test_transcription_anchor(self):
        h = 0.254e-3
        r_m = 0.15e-3
        t = 35e-6
        f = 10.0e9
        rho = 1.0 / 5.8e7
        r_dc = rho * h / (math.pi * (r_m ** 2 - (r_m - t) ** 2))
        f_delta = rho / (math.pi * _MU0 * t * t)
        r_ac = r_dc * math.sqrt(1.0 + f / f_delta)
        a = math.hypot(r_m, h)
        ind = (_MU0 / (2.0 * math.pi)) * (h * math.log((h + a) / r_m)
                                          + 1.5 * (r_m - a))
        r = microstrip_via_short(**self.KW, sigma_s_per_m=5.8e7)
        assert r["r_dc_ohm"] == pytest.approx(r_dc, rel=1e-12)
        assert r["f_delta_hz"] == pytest.approx(f_delta, rel=1e-12)
        assert r["r_ac_ohm"] == pytest.approx(r_ac, rel=1e-12)
        assert r["l_inductance_h"] == pytest.approx(ind, rel=1e-12)
        s11 = (complex(r_ac, 2 * math.pi * f * ind) / 50.0) / (
            complex(r_ac, 2 * math.pi * f * ind) / 50.0 + 2.0)
        assert r["s11_re"] == pytest.approx(s11.real, rel=1e-12, abs=1e-15)
        assert r["s11_im"] == pytest.approx(s11.imag, rel=1e-12, abs=1e-15)

    def test_microwaves101_band_2mil_gaas(self):
        # 2mil GaAs（h=50.8µm）D/H=0.5 → Microwaves101 "roughly 10 pH"
        # 手册形态独立转录 9.39pH；qucsator 漏 2π 形态 ~59pH 出带（偏差锤）
        h = 50.8e-6
        r_m = 12.7e-6
        a = math.hypot(r_m, h)
        ind = (_MU0 / (2.0 * math.pi)) * (h * math.log((h + a) / r_m)
                                          + 1.5 * (r_m - a))
        assert 8e-12 <= ind <= 12e-12
        r = microstrip_via_short(h_mm=0.0508, diameter_mm=0.0254,
                                 freq_ghz=10.0, thickness_um=5.0)
        assert r["l_inductance_h"] == pytest.approx(ind, rel=1e-12)

    def test_high_aspect_ratio_asymptote(self):
        # h/r=200：L → (μ0h/2π)(ln(2h/r)−1.5)（细长渐近，2% 带）
        h = 4.0e-3
        r_m = 2.0e-5
        r = microstrip_via_short(h_mm=4.0, diameter_mm=0.04, freq_ghz=1.0,
                                 thickness_um=5.0)
        approx = (_MU0 * h / (2.0 * math.pi)) * (math.log(2.0 * h / r_m) - 1.5)
        assert r["l_inductance_h"] == pytest.approx(approx, rel=0.02)

    def test_lossless_limit_passivity(self):
        # σ→∞ → R→0（纯电抗）→ |S11|²+|S21|²→1（幺正；有限 σ 残差
        # O(R/z0)，σ=1e15 给 ~4e-8，容差 1e-6；无源性方向 ≤1 严格）
        r = microstrip_via_short(h_mm=0.254, diameter_mm=0.3, freq_ghz=10.0,
                                 thickness_um=35.0, sigma_s_per_m=1e15)
        power = abs(r["s11_mag"]) ** 2 + abs(r["s21_mag"]) ** 2
        assert power <= 1.0 + 1e-9
        assert power == pytest.approx(1.0, abs=1e-6)

    def test_validity_and_structural_guards(self):
        with pytest.raises(ValueError, match=r"0\.03"):
            microstrip_via_short(h_mm=1.6, diameter_mm=0.3, freq_ghz=10.0)
        with pytest.raises(ValueError, match="t<r"):
            microstrip_via_short(h_mm=0.254, diameter_mm=0.3, freq_ghz=10.0,
                                 thickness_um=200.0)

    def test_fit_window_flag(self):
        # h=254µm 在 [100,631]µm 拟合窗内；h=50.8µm（2mil）出窗→flag
        in_win = microstrip_via_short(**self.KW)
        assert in_win["via_fit_window_flag"] is False
        out_win = microstrip_via_short(h_mm=0.0508, diameter_mm=0.0254,
                                       freq_ghz=10.0, thickness_um=5.0)
        assert out_win["via_fit_window_flag"] is True

    def test_deterministic(self):
        assert (microstrip_via_short(**self.KW)
                == microstrip_via_short(**self.KW))


# ─── 开路端辐射电导 ─────────────────────────────────────────────────────────

class TestOpenEndRadiation:
    KW: ClassVar[dict] = dict(width_mm=1.27, h_mm=0.635, epsilon_r=9.9, freq_ghz=10.0)

    def test_extremes_transcription_exact(self):
        assert _open_end_radiation_s(0.5) == pytest.approx(0.25 / 90.0,
                                                           rel=1e-15)
        assert _open_end_radiation_s(3.0) == pytest.approx(3.0 / 120.0,
                                                           rel=1e-15)

    def test_piecewise_continuity_at_knots(self):
        for knot in (1.0, 2.0):
            eps = 1e-12
            lo = _open_end_radiation_s(knot - eps)
            hi = _open_end_radiation_s(knot + eps)
            mid = _open_end_radiation_s(knot)
            assert lo == pytest.approx(hi, rel=1e-9)
            assert mid == pytest.approx((lo + hi) / 2.0, rel=1e-6)

    def test_narrow_regime_key_face(self):
        r = microstrip_open_end_radiation(**self.KW)
        x = r["w_over_lambda0"]
        assert x < 1.0
        assert r["g_radiation_s"] == pytest.approx(x * x / 90.0, rel=1e-12)
        assert r["radiation_regime"] == "narrow"

    def test_wide_regime_matches_patch_rin_edge_asymptote(self):
        # 同仓对拍：键 G vs Balanis 单槽电导渐近 G1=(W/120λ0)(1−(k0h)²/24)
        # （synthesis.patch_rin_edge_balanis 同源公式独立转录；本键无
        # k0h 修正 → 残差 ≤(k0h)²/24·1.05）
        w_mm, h_mm, er, f_ghz = 60.0, 0.635, 9.9, 10.0
        r = microstrip_open_end_radiation(width_mm=w_mm, h_mm=h_mm,
                                          epsilon_r=er, freq_ghz=f_ghz)
        k0h = 2.0 * math.pi * f_ghz * 1e9 * h_mm * 1e-3 / _C0
        w_over_l0 = w_mm * 1e-3 / (_C0 / (f_ghz * 1e9))
        g1_int = (w_over_l0 / 120.0) * (1.0 - k0h ** 2 / 24.0)
        assert w_over_l0 >= 2.0
        assert r["radiation_regime"] == "wide"
        resid = abs(r["g_radiation_s"] - g1_int) / g1_int
        assert resid <= (k0h ** 2 / 24.0) * 1.05

    def test_loss_tangent_and_gamma_recompute(self):
        # C_end 自身（HB 0.412 Δl→C 恒等式）的单源锚由 W11-S4 锚树
        # （test_w11s4_core_domains microstrip_open_end_parasitics）已钉；
        # 本树只做键内一致性双路径：损耗正切与 Γ 由键输出独立复算逐位。
        r = microstrip_open_end_radiation(**self.KW)
        z0 = r["z0_ohm"]
        c_end = r["c_end_f"]
        omega = 2.0 * math.pi * 10.0e9
        y_l = complex(r["g_radiation_s"], omega * c_end)
        gamma = (1.0 / z0 - y_l) / (1.0 / z0 + y_l)
        assert r["open_end_loss_tangent"] == pytest.approx(
            r["g_radiation_s"] / (omega * c_end), rel=1e-12)
        assert r["gamma_re"] == pytest.approx(gamma.real, rel=1e-12)
        assert r["gamma_im"] == pytest.approx(gamma.imag, rel=1e-12)
        assert r["gamma_mag"] == pytest.approx(abs(gamma), rel=1e-12)
        assert r["gamma_mag"] <= 1.0

    def test_wider_line_radiates_more_gamma_drops(self):
        small = microstrip_open_end_radiation(width_mm=0.5, h_mm=0.635,
                                              epsilon_r=9.9, freq_ghz=10.0)
        big = microstrip_open_end_radiation(width_mm=2.0, h_mm=0.635,
                                            epsilon_r=9.9, freq_ghz=10.0)
        assert big["g_radiation_s"] > small["g_radiation_s"]
        assert big["gamma_mag"] < small["gamma_mag"] < 1.0

    def test_er_guard(self):
        with pytest.raises(ValueError):
            microstrip_open_end_radiation(width_mm=1.27, h_mm=0.635,
                                          epsilon_r=0.9, freq_ghz=10.0)

    def test_deterministic(self):
        assert (microstrip_open_end_radiation(**self.KW)
                == microstrip_open_end_radiation(**self.KW))
