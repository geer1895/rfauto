"""aurora_j W4-S13 天线口径效率分解域三键锚树（B 批，候选定稿 §1.4）。

裁判口径（AGENTS 铁律 5/#118：锚先独立实测再写死——测试内表达式路径
独立于键内实现：原始 SI 常数内联、scipy Fresnel 第三方法、core 公开
路径几何互证、#122 近似式如实）：

- polarization_loss_factor（薄注册）：①经典锚逐位（对齐线 1/正交 0→
  −300 地板/45° 交叉 0.5=−3.0103 dB/圆×线 0.5）；②薄度守卫=wrapper
  与 core 直调逐位一致（test_polarization_reg 同款主判据）；③反向圆
  浮点近零一致地板截断；④非法输入显式拒绝。
- aperture_efficiency_components（提升核）：①Ruze 曲线锚（σ/λ=0→1、
  σ/λ=1/32→exp(−(π/8)²) 独立常数算术、单调递减）；②能量守恒乘积
  恒等 + η_s·η_i=core.aperture_efficiency 直调（η_ap=η_s·η_i 恒等钉）
  + core 手积闭式锚透传（q=2、θ₀=60°→0.811419）；③uniform 档各向
  同性馈 η_s=1−cosθ₀ 解析恒等；④方向性独立复算 10log10(η_ap)+
  20log10(πD/λ)（C0 内联裁判）；⑤η_p 线性透传恰半+q 覆盖档等价。
- horn_aperture_efficiency（提升核）：①最优常数带（δ_H=3λ/8、δ_E=λ/4
  → η_ap∈[0.50,0.53]=0.51 文献口径带）；②G 恒等式与 HPBW 恒等式
  （54λ/b_p、78λ/a_p 逐位）；③Fresnel 口径积分第三方法（测试内独立
  数值实现，scipy.special.fresnel）HPBW 对照 ≤1.5%（近似式数值互证，
  模块 docstring 引文核记录的落地）；④与 core.horn_gain_direct 公开
  路径同几何互证（σ/η/G 逐位）；⑤偏离最优 near_optimum 判定翻转。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import reflector_antenna as _refl_mod
from rfauto.core.calc_families.antenna_aperture import (
    aperture_efficiency_components,
    horn_aperture_efficiency,
)
from rfauto.core.calc_families.polarization_reg import polarization_loss_factor
from rfauto.core.horn_synthesis import horn_gain_direct
from rfauto.core.polarization import (
    polarization_loss_factor as _core_plf,
)

#: λ=10 mm 标定频率（f=c/λ，C0 内联 SI 定义值——不消费模块常量，#118）。
_C0 = 299792458.0
_F_LAMBDA10MM_GHZ = _C0 / 0.010 / 1e9  # =29.9792458 GHz

#: θ₀=60° 的焦径比（cot(θ₀/2)=4F/D → F/D=1/(4·tan30°)）。
_FOD_THETA60 = 1.0 / (4.0 * math.tan(math.radians(30.0)))


# ─── polarization_loss_factor（薄注册）───────────────────────────────────────

class TestPolarizationLossFactor:
    def test_classic_anchors_exact(self):
        """对齐线 1/正交 0/45° 交叉 0.5/圆×线 0.5（Balanis §4.4.3 经典锚）。"""
        assert polarization_loss_factor(1, 0, 0, 1, 0, 0)["plf_linear"] == 1.0
        assert polarization_loss_factor(1, 0, 0, 1, 0, 0)["plf_db"] == 0.0
        orth = polarization_loss_factor(1, 0, 0, 0, 1, 0)
        assert orth["plf_linear"] == 0.0
        assert orth["plf_db"] == -300.0  # 地板截断（真值 −∞）
        x45 = polarization_loss_factor(1, 0, 0, 1, 1, 0)
        assert x45["plf_linear"] == pytest.approx(0.5, rel=1e-12)
        assert x45["plf_db"] == pytest.approx(-3.0102999566398, rel=1e-12)
        cpx = polarization_loss_factor(1, 1, -90, 1, 0, 0)
        assert cpx["plf_linear"] == pytest.approx(0.5, rel=1e-12)
        assert cpx["plf_db"] == pytest.approx(-3.0102999566398, rel=1e-12)

    def test_cp_sense_anchors(self):
        """同向圆 1/反向圆≈0（IEEE 145 旋向；浮点近零一致地板截断）。"""
        same = polarization_loss_factor(1, 1, -90, 1, 1, -90)
        assert same["plf_linear"] == 1.0
        opp = polarization_loss_factor(1, 1, -90, 1, 1, 90)
        assert opp["plf_linear"] == pytest.approx(0.0, abs=1e-30)
        # 反向圆 plf 为浮点近零残留（非恰 0）——地板语义一致截断到 −300
        assert opp["plf_db"] == -300.0

    def test_thinness_guard_bitwise(self):
        """薄度守卫：wrapper 与 core 直调逐位一致（== 原子比较）。"""
        args = (0.6, 1.0, -123.0, 0.8, 0.5, 37.0)
        out = polarization_loss_factor(*args)
        d_rx = math.radians(args[2])
        d_tx = math.radians(args[5])
        assert out["plf_linear"] == _core_plf(
            args[0], args[1], d_rx, args[3], args[4], d_tx)
        assert out["plf_db"] == 10.0 * math.log10(out["plf_linear"])

    def test_invalid_inputs(self):
        """幅度负值/全零/bool（core 守卫透传 + 本族 deg 换算面自守）。"""
        with pytest.raises(ValueError, match="幅度非法"):
            polarization_loss_factor(-1, 0, 0, 1, 0, 0)
        with pytest.raises(ValueError, match="幅度非法"):
            polarization_loss_factor(0, 0, 0, 1, 0, 0)
        with pytest.raises(ValueError, match="不接受 bool"):
            polarization_loss_factor(1, 0, True, 1, 0, 0)


# ─── aperture_efficiency_components（提升核）─────────────────────────────────

class TestApertureEfficiencyComponents:
    def test_ruze_curve_anchor(self):
        """σ/λ=0→1、σ/λ=1/32→exp(−(π/8)²)（独立常数算术）+单调递减。"""
        base = dict(profile="cos2", f_over_d=0.45, f_ghz=10.0, diameter_m=2.0)
        r0 = aperture_efficiency_components(**base)
        assert r0["eta_ruze"] == 1.0
        r32 = aperture_efficiency_components(**base, sigma_over_lambda=1 / 32)
        expect = math.exp(-((4.0 * math.pi / 32.0) ** 2))
        assert r32["eta_ruze"] == pytest.approx(expect, rel=1e-12)
        r16 = aperture_efficiency_components(**base, sigma_over_lambda=1 / 16)
        assert r16["eta_ruze"] < r32["eta_ruze"] < 1.0

    def test_product_identity_and_core_hand_anchor(self):
        """乘积恒等 + η_s·η_i=core 直调 + 手积闭式锚透传（q=2,θ₀=60°）。"""
        r = aperture_efficiency_components(
            profile="cos2", f_over_d=_FOD_THETA60, f_ghz=10.0, diameter_m=2.0)
        assert r["theta_rim_deg"] == pytest.approx(60.0, rel=1e-12)
        # core 手积闭式锚（reflector_antenna docstring：η_ap=0.811419）
        assert r["eta_spillover"] * r["eta_illumination"] == pytest.approx(
            0.811419, rel=1e-5)
        assert r["eta_ap"] == pytest.approx(
            r["eta_spillover"] * r["eta_illumination"], rel=1e-12)
        # 与 core 角域积分路径直调互证（η_ap=η_s·η_i 恒等钉）
        theta0 = math.radians(60.0)
        assert r["eta_spillover"] * r["eta_illumination"] == pytest.approx(
            _refl_mod.aperture_efficiency(theta0, 2.0), rel=1e-12)

    def test_uniform_isotropic_spillover_closed_form(self):
        """uniform 档（q=0）η_s=1−cosθ₀ 解析恒等（各向同性馈锚）。"""
        r = aperture_efficiency_components(
            profile="uniform", f_over_d=0.45, f_ghz=10.0, diameter_m=2.0)
        theta0 = math.radians(r["theta_rim_deg"])
        assert r["q_power"] == 0.0
        assert r["eta_spillover"] == pytest.approx(
            1.0 - math.cos(theta0), rel=1e-12)
        assert 0.0 < r["eta_illumination"] < 1.0

    def test_gain_independent_recompute(self):
        """方向性独立复算 10log10(η_ap)+20log10(πD/λ)（C0 内联裁判）。"""
        r = aperture_efficiency_components(
            profile="cos2", f_over_d=0.45, f_ghz=10.0, diameter_m=2.0)
        lam = _C0 / 10.0e9
        expect = 10.0 * math.log10(r["eta_ap"]) + 20.0 * math.log10(
            math.pi * 2.0 / lam)
        assert r["gain_dbi"] == pytest.approx(expect, rel=1e-12)

    def test_eta_p_linear_and_q_override(self):
        """η_p=0.5 → η_ap 恰半（线性透传）+q_power 覆盖档与 cos2 档等价。"""
        kw = dict(profile="cos2", f_over_d=0.45, f_ghz=10.0, diameter_m=2.0)
        full = aperture_efficiency_components(**kw)
        half = aperture_efficiency_components(**kw, eta_polarization=0.5)
        assert half["eta_ap"] == pytest.approx(
            0.5 * full["eta_ap"], rel=1e-12)
        by_q = aperture_efficiency_components(
            profile="uniform", f_over_d=0.45, f_ghz=10.0, diameter_m=2.0,
            q_power=2.0)
        assert by_q["eta_ap"] == pytest.approx(full["eta_ap"], rel=1e-12)
        assert by_q["q_power"] == 2.0

    def test_guards(self):
        """f/D<0.25/η_p>1/σ<0/profile 越档/q<0 显式拒绝。"""
        with pytest.raises(ValueError, match=r"≥0\.25"):
            aperture_efficiency_components(
                profile="cos2", f_over_d=0.1, f_ghz=10.0, diameter_m=2.0)
        with pytest.raises(ValueError, match=r"\(0,1\]"):
            aperture_efficiency_components(
                profile="cos2", f_over_d=0.45, f_ghz=10.0, diameter_m=2.0,
                eta_polarization=1.5)
        with pytest.raises(ValueError, match="≥0"):
            aperture_efficiency_components(
                profile="cos2", f_over_d=0.45, f_ghz=10.0, diameter_m=2.0,
                sigma_over_lambda=-0.01)
        with pytest.raises(ValueError, match="profile"):
            aperture_efficiency_components(
                profile="bogus", f_over_d=0.45, f_ghz=10.0, diameter_m=2.0)
        with pytest.raises(ValueError, match="q_power"):
            aperture_efficiency_components(
                profile="cos2", f_over_d=0.45, f_ghz=10.0, diameter_m=2.0,
                q_power=-1.0)


# ─── horn_aperture_efficiency（提升核）───────────────────────────────────────

def _hpbw_numeric(kind: str, size_m: float, rho_m: float, lam_m: float,
                  n_theta: int = 40001) -> float:
    """Fresnel 口径积分独立数值 HPBW（deg；测试内第三方法，非键内路径）。

    kind="e"：均匀幅+二次相位（E 面扇形口径，δ_E=λ/4 档）；
    kind="h"：cos(πx/A) 幅+二次相位（H 面扇形口径，δ_H=3λ/8 档）。
    """
    k = 2.0 * math.pi / lam_m
    import numpy as np
    n = 20000
    xs = np.linspace(-size_m / 2.0, size_m / 2.0, n + 1)
    amp = (np.ones_like(xs) if kind == "e"
           else np.cos(math.pi * xs / size_m))
    ph = np.exp(-1j * k * xs**2 / (2.0 * rho_m))
    th = np.linspace(-0.6, 0.6, n_theta)
    s = np.sin(th)
    ker = np.exp(1j * k * np.outer(s, xs))
    pat = np.abs(ker @ (amp * ph * (xs[1] - xs[0])))
    idx = np.where(pat >= pat.max() / math.sqrt(2.0))[0]
    return float(math.degrees(th[idx[-1]] - th[idx[0]]))


class TestHornApertureEfficiency:
    def test_optimum_constant_band_and_deltas(self):
        """最优几何（δ_H=3λ/8、δ_E=λ/4）→ η_ap∈[0.50,0.53]（0.51 带）。"""
        # 4λ×2λ 口径：ρ₁=a²/(3λ)、ρ₂=b²/(2λ)（Balanis 最优厚度条件反解）
        h = horn_aperture_efficiency(
            a_p_mm=40.0, b_p_mm=20.0, l_h_mm=160.0 / 3.0, l_e_mm=20.0,
            f_ghz=_F_LAMBDA10MM_GHZ)
        assert h["lambda_mm"] == pytest.approx(10.0, rel=1e-12)
        assert h["delta_h_over_lambda"] == pytest.approx(0.375, abs=1e-12)
        assert h["delta_e_over_lambda"] == pytest.approx(0.25, abs=1e-12)
        assert h["near_optimum"] is True
        assert 0.50 <= h["eta_ap"] <= 0.53
        assert h["sigma_h"] == pytest.approx(math.sqrt(1.5), rel=1e-12)
        assert h["sigma_e"] == pytest.approx(1.0, rel=1e-12)

    def test_gain_and_hpbw_identities(self):
        """G=η_ap·(4π/λ²)·a_p·b_p 恒等 + HPBW=54λ/b_p、78λ/a_p 逐位。"""
        h = horn_aperture_efficiency(
            a_p_mm=40.0, b_p_mm=20.0, l_h_mm=160.0 / 3.0, l_e_mm=20.0,
            f_ghz=_F_LAMBDA10MM_GHZ)
        lam = 0.010
        expect_g = h["eta_ap"] * (4.0 * math.pi / lam**2) * 0.040 * 0.020
        assert h["gain_linear"] == pytest.approx(expect_g, rel=1e-12)
        assert h["gain_dbi"] == pytest.approx(
            10.0 * math.log10(expect_g), rel=1e-12)
        assert h["hpbw_e_deg"] == pytest.approx(54.0 * 10.0 / 20.0, rel=1e-12)
        assert h["hpbw_h_deg"] == pytest.approx(78.0 * 10.0 / 40.0, rel=1e-12)

    def test_hpbw_fresnel_numeric_crosscheck(self):
        """Fresnel 口径积分第三方法（测试内独立实现）HPBW 对照 ≤1.5%。"""
        h = horn_aperture_efficiency(
            a_p_mm=40.0, b_p_mm=20.0, l_h_mm=160.0 / 3.0, l_e_mm=20.0,
            f_ghz=_F_LAMBDA10MM_GHZ)
        lam = 0.010
        hpbw_e_num = _hpbw_numeric("e", 0.020, 0.020, lam)  # ρ₂=b²/(2λ)=20mm
        hpbw_h_num = _hpbw_numeric(
            "h", 0.040, 0.040**2 / (3.0 * lam), lam)  # ρ₁=a²/(3λ)=53.33mm
        assert hpbw_e_num == pytest.approx(h["hpbw_e_deg"], rel=0.015)
        assert hpbw_h_num == pytest.approx(h["hpbw_h_deg"], rel=0.015)

    def test_cross_path_horn_gain_direct(self):
        """与 core.horn_gain_direct 公开路径同几何互证（σ/η/G 逐位）。"""
        a1, b1 = 0.040, 0.020
        rho1, rho2 = a1**2 / (3.0 * 0.010), b1**2 / (2.0 * 0.010)
        a = 0.7 * a1
        ax_len = rho1 * (a1 - a) / a1
        b = b1 * (1.0 - ax_len / rho2)
        assert 0.0 < b < b1 and 0.0 < ax_len < rho1
        direct = horn_gain_direct(a * 1e3, b * 1e3, a1 * 1e3, b1 * 1e3,
                                  ax_len * 1e3, _F_LAMBDA10MM_GHZ)
        key = horn_aperture_efficiency(
            a_p_mm=a1 * 1e3, b_p_mm=b1 * 1e3, l_h_mm=rho1 * 1e3,
            l_e_mm=rho2 * 1e3, f_ghz=_F_LAMBDA10MM_GHZ)
        assert key["sigma_h"] == pytest.approx(direct["sigma_h"], rel=1e-12)
        assert key["sigma_e"] == pytest.approx(direct["sigma_e"], rel=1e-12)
        assert key["eta_ap"] == pytest.approx(direct["eff_ap"], rel=1e-12)
        assert key["gain_dbi"] == pytest.approx(direct["gain_db"], rel=1e-12)

    def test_off_optimum_flag_flips(self):
        """偏离最优（ρ₂ 加倍 → δ_E=λ/8）near_optimum 翻转+效率变化如实。"""
        h_opt = horn_aperture_efficiency(
            a_p_mm=40.0, b_p_mm=20.0, l_h_mm=160.0 / 3.0, l_e_mm=20.0,
            f_ghz=_F_LAMBDA10MM_GHZ)
        h_off = horn_aperture_efficiency(
            a_p_mm=40.0, b_p_mm=20.0, l_h_mm=160.0 / 3.0, l_e_mm=40.0,
            f_ghz=_F_LAMBDA10MM_GHZ)
        assert h_off["near_optimum"] is False
        assert h_off["delta_e_over_lambda"] == pytest.approx(0.125, abs=1e-12)
        assert h_off["eta_ap"] != pytest.approx(h_opt["eta_ap"], rel=1e-9)

    def test_guards(self):
        """尺寸负值+σ 低于 core 下限（口径/波长过小病态域）显式拒绝。"""
        with pytest.raises(ValueError, match="a_p_mm"):
            horn_aperture_efficiency(
                a_p_mm=-1.0, b_p_mm=20.0, l_h_mm=53.3, l_e_mm=20.0,
                f_ghz=_F_LAMBDA10MM_GHZ)
        with pytest.raises(ValueError, match="病态域"):
            horn_aperture_efficiency(
                a_p_mm=1.0, b_p_mm=0.5, l_h_mm=10.0, l_e_mm=10.0,
                f_ghz=_F_LAMBDA10MM_GHZ)
