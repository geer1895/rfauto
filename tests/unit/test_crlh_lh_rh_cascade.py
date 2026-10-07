"""MM-4/MM-5 CRLH 翻案完成件：LH+RH 异质级联锚树（core/crlh.py §7）。

裁判面（#118：每面 ≥2 独立基准；翻案验收口径 ≤0.1dB/1° 同 MM-4 主件）：
- 纯 LH/RH Bloch 阻抗频不变恒等：Z_Bloch=√(L/C) 双频点逐位同值
  （Caloz-Itoh 经典结果）+ β 符号带向（LH<0/RH>0）+ RH 低通截止
  阻带如实 NaN；
- 连续极限收敛：|βd|≪1 域 β→∓1/(ω√(LC)d)（Caloz-Itoh Table 1.1）；
- 级联双路对拍：闭式 ABCD 矩阵幂 vs skrf.Network 级联（独立实现）
  ≤0.1dB/1°（传播域）；
- 相位补偿：精确级联 S21 相位过零（数值求根）vs 连续极限闭式
  ω₀=√(n_LH/n_RH)(L_LC_LL_RC_R)^(−1/4) 收敛对拍 + 该频点零相移
  功能验证；
- 无源性 |S21|≤1 与域守卫负例。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.crlh import (
    crlh_lh_rh_cascade_s21,
    crlh_lh_rh_skrf_cascade_s21,
    lh_rh_balance_frequency_hz,
    pure_lh_bloch,
    pure_rh_bloch,
)

# 小单元口径：L=1nH、C=0.25pF → √(LC)=5e-11 s；f=10GHz 时 ω√(LC)=0.314
# （|βd|≈3.2 连续域偏差大）、f=200GHz 时 ω√(LC)=6.3（|βd|=0.16 连续近似域）
L_L = 1e-9
C_L = 0.25e-12
L_R = 1e-9
C_R = 0.25e-12
D_CELL = 1e-3
Z_TERM = 50.0


class TestPureLineBloch:
    def test_z_bloch_frequency_independent(self):
        for fun, ll, cl in ((pure_lh_bloch, L_L, C_L),
                            (pure_rh_bloch, L_R, C_R)):
            lo = fun(2 * math.pi * 10e9, ll, cl, D_CELL)
            hi = fun(2 * math.pi * 60e9, ll, cl, D_CELL)
            expect = math.sqrt(ll / cl)
            assert lo["z_bloch_ohm"] == pytest.approx(expect, rel=1e-15)
            assert hi["z_bloch_ohm"] == pytest.approx(expect, rel=1e-15)

    def test_beta_sign_and_exact_dispersion(self):
        w = 2 * math.pi * 10e9
        lh = pure_lh_bloch(w, L_L, C_L, D_CELL)
        rh = pure_rh_bloch(w, L_R, C_R, D_CELL)
        assert float(lh["beta_rad_per_m"]) < 0.0
        assert float(rh["beta_rad_per_m"]) > 0.0
        # 精确集总色散：cos(βd)=1−1/(2ω²L_LC_L) / =1−ω²L_RC_R/2
        bd_lh = -float(lh["beta_rad_per_m"]) * D_CELL
        assert math.cos(bd_lh) == pytest.approx(
            1.0 - 1.0 / (2 * w * w * L_L * C_L), rel=1e-12)
        bd_rh = float(rh["beta_rad_per_m"]) * D_CELL
        assert math.cos(bd_rh) == pytest.approx(
            1.0 - w * w * L_R * C_R / 2.0, rel=1e-12)

    def test_rh_stopband_nan(self):
        w_cut = 2.0 / math.sqrt(L_R * C_R)
        rep = pure_rh_bloch(np.array([0.5 * w_cut, 1.5 * w_cut]),
                            L_R, C_R, D_CELL)
        assert np.isfinite(rep["beta_rad_per_m"][0])
        assert math.isnan(rep["beta_rad_per_m"][1])
        assert rep["cutoff_omega_rad_s"] == pytest.approx(w_cut, rel=1e-15)

    def test_continuous_limit_convergence(self):
        # LH：目标 |βd|=1/(ω√LC)=0.16；RH：目标 βd=ω√LC=0.2（同一 LC
        # 积下二者互倒，连续域频点必然不同——分开取）
        w_lh = 6.3 / math.sqrt(L_L * C_L)
        lh = pure_lh_bloch(w_lh, L_L, C_L, D_CELL)
        assert float(lh["beta_rad_per_m"]) == pytest.approx(
            lh["beta_times_omega_continuous"] / w_lh, rel=3e-3)
        w_rh = 0.2 / math.sqrt(L_R * C_R)
        rh = pure_rh_bloch(w_rh, L_R, C_R, D_CELL)
        expect = w_rh * math.sqrt(L_R * C_R) / D_CELL
        assert float(rh["beta_rad_per_m"]) == pytest.approx(
            expect, rel=6e-3)


class TestCascadeDualPath:
    F_GRID = np.linspace(1e9, 30e9, 61)

    def test_closed_vs_skrf_passband(self):
        """翻案验收口径：闭式 ABCD vs skrf 级联 ≤0.1dB/1°（传播域）。

        RH 低通截止 f_c=(1/2π)·2/√(L_RC_R)≈318GHz ≫ 频栅——全栅传播。
        """
        cf = crlh_lh_rh_cascade_s21(self.F_GRID, L_L, C_L, L_R, C_R,
                                    6, 6, Z_TERM)
        sf = crlh_lh_rh_skrf_cascade_s21(self.F_GRID, L_L, C_L, L_R, C_R,
                                         6, 6, Z_TERM)
        mag_dev = np.abs(20 * np.log10(np.abs(sf["s21"])
                                       / np.abs(cf["s21"])))
        ph_dev = np.abs(np.angle(sf["s21"] / cf["s21"], deg=True))
        assert np.max(mag_dev) <= 0.1
        assert np.max(np.abs(ph_dev)) <= 1.0

    def test_passivity_and_magnitude(self):
        rep = crlh_lh_rh_cascade_s21(self.F_GRID, L_L, C_L, L_R, C_R,
                                     4, 8, Z_TERM)
        assert np.all(np.abs(rep["s21"]) <= 1.0 + 1e-12)
        assert np.all(np.abs(rep["s11"]) <= 1.0 + 1e-12)

    def test_lh_section_phase_lead(self):
        """纯 LH 段相位超前（β<0 的网络级表现）：S21 相位 >0（同频下
        纯 RH 段相位 <0）。单元数取 2：10GHz 处 |βd|≈1.04，2 单元
        2.1 rad<π 不卷绕（6 单元 6.2 rad 卷过 −2π 会翻正号）。"""
        f = np.array([10e9])
        lh = crlh_lh_rh_cascade_s21(f, L_L, C_L, L_R, C_R, 2, 0, Z_TERM)
        rh = crlh_lh_rh_cascade_s21(f, L_L, C_L, L_R, C_R, 0, 2, Z_TERM)
        ph_lh = np.angle(lh["s21"][0], deg=True)
        ph_rh = np.angle(rh["s21"][0], deg=True)
        assert ph_lh > 0.0
        assert ph_rh < 0.0


class TestPhaseCompensation:
    def test_balance_frequency_root_vs_closed(self):
        """零相移频率：精确级联相位求根 vs 连续极限闭式（收敛对拍）。

        设计前提（Caloz-Itoh 复合线匹配口径）：两段同特征阻抗
        √(L/C)=50Ω=Z_term——首轮基准用失配设计（12.6Ω/628Ω）实测平
        衡点相位偏 22.8°，反射破坏零相移条件（闭式前提显式化）。
        单元相位 |βd|=0.1 于 f₀（连续极限偏差 ~1%，门 2%）。
        """
        # √(L_L/C_L)=√(L_R/C_R)=50Ω；√(L_LC_L)=4e-11、√(L_RC_R)=4e-13
        # → f₀=1/(2π·√(ab))≈39.8GHz（n_LH=n_RH=1）
        l_lh, c_lh = 2e-9, 0.8e-12
        l_rh, c_rh = 1e-11, 4e-15
        n_lh, n_rh = 1, 1
        # 匹配前提自检
        assert math.sqrt(l_lh / c_lh) == pytest.approx(50.0, rel=1e-9)
        assert math.sqrt(l_rh / c_rh) == pytest.approx(50.0, rel=1e-9)
        f_bal = lh_rh_balance_frequency_hz(l_lh, c_lh, l_rh, c_rh,
                                           n_lh, n_rh)
        rep = crlh_lh_rh_cascade_s21(f_bal, l_lh, c_lh, l_rh, c_rh,
                                     n_lh, n_rh, Z_TERM)
        phase = float(np.angle(rep["s21"][0], deg=True))
        assert abs(phase) <= 5.0

        # 数值求根（精确集总单元的零相移点）
        def _phase(f: float) -> float:
            r = crlh_lh_rh_cascade_s21(np.array([f]), l_lh, c_lh, l_rh,
                                       c_rh, n_lh, n_rh, Z_TERM)
            return float(np.unwrap(np.angle(r["s21"]))[0])

        lo, hi = 0.3 * f_bal, 3.0 * f_bal
        f_lo, f_hi = lo, hi
        p_lo, p_hi = _phase(f_lo), _phase(f_hi)
        assert p_lo * p_hi < 0.0
        for _ in range(80):
            mid = 0.5 * (f_lo + f_hi)
            if _phase(mid) * p_lo < 0.0:
                f_hi, p_hi = mid, _phase(mid)
            else:
                f_lo, p_lo = mid, _phase(mid)
        f_root = 0.5 * (f_lo + f_hi)
        assert f_root == pytest.approx(f_bal, rel=0.02)

    def test_balance_guard(self):
        with pytest.raises(ValueError):
            lh_rh_balance_frequency_hz(L_L, C_L, L_R, C_R, 0, 2)


class TestGuards:
    def test_bad_counts(self):
        with pytest.raises(ValueError):
            crlh_lh_rh_cascade_s21(np.array([1e9]), L_L, C_L, L_R, C_R,
                                   0, 0, Z_TERM)
        with pytest.raises(ValueError):
            crlh_lh_rh_skrf_cascade_s21(np.array([1e9]), L_L, C_L, L_R,
                                        C_R, -1, 2, Z_TERM)

    def test_bad_frequency(self):
        with pytest.raises(ValueError):
            crlh_lh_rh_cascade_s21(np.array([0.0]), L_L, C_L, L_R, C_R,
                                   1, 1, Z_TERM)
