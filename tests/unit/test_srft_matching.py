"""MT-2 SRFT 综合器锚树（core/srft_matching.py，round17 :26）。

裁判面（#118：每面 ≥2 独立基准；#122 如实）：
- 增益参数化：Butterworth 特例闭式（ε=1、P=p₀、n=k →
  T=1/(1+(ω/ω_c)^{2k})，ω_c=p₀^{1/(2k)}）逐点对拍 + T(0)=1/T(∞)=0
  渐近 + 守卫负例；
- 谱分解：Feldtkeller 无耗恒等式 |g|²−|f|²=ω^{2k}P²（≤1e-10）+
  |S21(λ)|² 回代 T（≤1e-10）+ g 最小相位（Re 根<0）；
- 1-port Cauer 提取器独立验证：解析 L 型匹配网络（Pozar §5.1 闭式
  X_p=R_L/Q、X_s=Q·R_S）的输入阻抗 → 提取回收 [并 C, 串 L] + 残余
  R_L（元件值 ≤1e-9）——提取器正确性不依赖 SRFT 链；
- SRFT 全链闭环：拟合→多项式→z_in→提取→ABCD 重仿真 |S21| 对拍
  模型 |S21|（完成域）；
- Bode-Fano 一致性（round17 验收）：拟合增益带的 |Γ| 积分不越
  π/(RC) 界（bounds.bode_fano_rc 同源 limit）；
- 边界如实：不完成域（残余≠负载）status=incomplete_extraction。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.srft_matching import (
    srft_extract_ladder,
    srft_fit_flat_gain,
    srft_gain_response,
    srft_network_response,
    srft_polynomials,
    srft_synthesize,
)

R0 = 50.0
F_LO, F_HI = 0.2e9, 2.0e9
W_BAND = 2 * np.pi * np.linspace(F_LO, F_HI, 25)


class TestGainResponse:
    def test_butterworth_special_case(self):
        """ε=1、P=p₀、k=n=1：T=ω²p0²/(ω⁴+ω²p0²)=p0²/(ω²+p0²)
        =1/(1+(ω/p0)²)（半功率点 ω=p0）闭式对拍。"""
        p0 = (2 * math.pi * 1e9) ** 2
        w = np.linspace(0.1 * p0, 3.0 * p0, 50)
        t = srft_gain_response(w, [p0], k=1, n=1, eps=1.0)
        expect = 1.0 / (1.0 + (w / p0) ** 2)
        assert np.allclose(t, expect, rtol=1e-12)

    def test_asymptotes(self):
        p0 = (2 * math.pi * 1e9) ** 2
        t0 = srft_gain_response(np.array([0.0]), [p0], k=1, n=1, eps=1.0)
        assert t0[0] == pytest.approx(1.0, rel=1e-15)
        # 半功率点闭式点：T(p0)=1/2（ω=p0 处）；高频滚降 −2 阶
        t_half = srft_gain_response(np.array([p0]), [p0], k=1, n=1,
                                    eps=1.0)
        assert t_half[0] == pytest.approx(0.5, rel=1e-12)
        t_hi = srft_gain_response(np.array([10.0 * p0]), [p0], k=1, n=1,
                                  eps=1.0)
        assert t_hi[0] == pytest.approx(1.0 / 101.0, rel=1e-12)

    def test_guards(self):
        with pytest.raises(ValueError):
            srft_gain_response(np.array([1.0]), [0.0], k=1, n=1, eps=1.0)
        with pytest.raises(ValueError):
            srft_gain_response(np.array([-1.0]), [1.0], k=1, n=1, eps=1.0)
        with pytest.raises(ValueError):
            srft_fit_flat_gain(W_BAND, target_t0=1.0)

    def test_fit_entry_domain_precheck(self):
        """A-08（W7 #12 接线前置件）：入口域预检——k/n 须 ≥1 整数且
        (k,n)≠(1,1)。k=n=1 时谱分解 g 的偶部与 f=ε·λ² 恒同式 →
        Darlington 阻抗矩阵分母 g_e−f_e≡0（结构退化，实测此前深层
        srft_impedance_matrix 才报 "g_e−f_e=0（Darlington 退化域）"），
        入口显式 ValueError；域内 (1,2) 照常。"""
        with pytest.raises(ValueError, match="须为 ≥1 整数"):
            srft_fit_flat_gain(W_BAND, k=0, n=2)
        with pytest.raises(ValueError, match="须为 ≥1 整数"):
            srft_fit_flat_gain(W_BAND, k=1, n=0)
        with pytest.raises(ValueError, match="k=n=1 结构退化域"):
            srft_fit_flat_gain(W_BAND, k=1, n=1)
        with pytest.raises(ValueError, match="k=n=1 结构退化域"):
            srft_synthesize(W_BAND, k=1, n=1)  # 综合入口经 fit 同款拒绝
        # 深层失败实锤（绕过 fit 入口直击 :266 原报错点，退化机理锚）
        polys = srft_polynomials([(2 * math.pi * 1e9) ** 2], 1, 1, 1.0)
        from rfauto.core.srft_matching import srft_impedance_matrix

        with pytest.raises(ValueError, match="Darlington 退化域"):
            srft_impedance_matrix(polys)
        # 域内缺省/常用 (1,2) 照常
        fit = srft_fit_flat_gain(W_BAND, k=1, n=2, target_t0=0.5)
        assert fit["k"] == 1 and fit["n"] == 2


class TestSpectralFactorization:
    def test_feldtkeller_and_reconstruction(self):
        fit = srft_fit_flat_gain(W_BAND, k=1, n=2, eps=1.0, n_p=1,
                                 target_t0=0.5)
        polys = srft_polynomials(fit["p_coeffs"], 1, 2, 1.0)
        w = W_BAND
        lam = 1j * w
        lhs = (np.abs(np.polyval(polys["g"], lam)) ** 2
               - np.abs(np.polyval(polys["f"], lam)) ** 2)
        rhs = (w ** 2) * np.polyval(polys["p21"], -(w ** 2)) ** 2
        assert np.max(np.abs(lhs - rhs)) <= 1e-10 * np.max(rhs)
        s21_model = (np.polyval(polys["p21"], -(w ** 2)) * lam
                     / np.polyval(polys["g"], lam))
        assert np.max(np.abs(np.abs(s21_model) ** 2 - fit["t_band"])) \
            <= 1e-10

    def test_minimum_phase_g(self):
        polys = srft_polynomials([(2 * math.pi * 1e9) ** 2], 1, 2, 1.0)
        roots = np.roots(polys["g"])
        assert np.all(np.real(roots) <= 1e-6 * np.max(np.abs(roots)))
        # 归一 |lead(g)|=ε
        assert abs(polys["g"][0]) == pytest.approx(1.0, rel=1e-12)

    def test_polynomial_construction_deterministic(self):
        p = [(2 * math.pi * 1e9) ** 2]
        a = srft_polynomials(p, 1, 2, 1.0)
        b = srft_polynomials(p, 1, 2, 1.0)
        assert np.array_equal(a["g"], b["g"])
        assert np.array_equal(a["f"], b["f"])


class TestCauerExtractor:
    def test_l_section_recovery(self):
        """独立验证：解析 L 型匹配（Pozar §5.1 闭式）归一输入阻抗 → 提取。

        R_S=25 源/50 载、f₀=1GHz：Q=√(R_L/R_S−1)=1、X_p=R_L/Q=50
        （并 C）、X_s=Q·R_S=25（串 L）。归一域（1Ω、λ_n=λ/ω₀）：
        L_n=ω₀L/50=0.5、C_n=ω₀C·50=1、负载 1Ω。Zin=λ_n·0.5+
        (1/(λ_n·1))∥1 → 提取回收 [串 L_n=0.5, 并 C_n=1] + 残余 1Ω。
        """
        lam = np.poly1d([1.0, 0.0])
        l_n, c_n = 0.5, 1.0
        # Zin = λ_n·L_n + (1/(λ_n C_n))∥1 = [λ_n L_n (1+λ_n C_n)+1] /
        # (1+λ_n C_n)
        zc_den = lam * c_n + np.poly1d([1.0])
        z_num = lam * l_n * zc_den + np.poly1d([1.0])
        rep = srft_extract_ladder((z_num, zc_den), expect_load_ohm=1.0)
        assert rep["status"] == "complete"
        assert rep["remainder_ohm"] == pytest.approx(1.0, rel=1e-9)
        assert rep["load_verdict"] == "matched"
        kinds = [(el["kind"], el["port"]) for el in rep["elements"]]
        assert kinds == [("series_l", 1), ("shunt_c", 1)]
        assert rep["elements"][0]["value_h"] == pytest.approx(
            l_n, rel=1e-9)
        assert rep["elements"][1]["value_f"] == pytest.approx(
            c_n, rel=1e-9)

    def test_negative_value_honest_fail(self):
        # 非正实函数（右半平面极点）→ 负元件如实失败，不伪造
        z_num = np.poly1d([-1.0, 0.0])   # −λ
        z_den = np.poly1d([1.0])
        rep = srft_extract_ladder((z_num, z_den))
        assert rep["status"] == "incomplete_extraction"
        assert rep["remainder_ohm"] is None


class TestSRFTFullChain:
    def test_roundtrip_closure(self):
        """全链闭环：拟合→多项式→z_in→提取→ABCD 重仿真对拍模型。

        完成域内（本设计点提取完整），|S21| 逐点 ≤1e-6。模型在归一域
        （Ω=ω/ω_mid），重仿真在物理域（元素值已反归一）——两者逐点
        等价（归一不变量）。
        """
        rep = srft_synthesize(W_BAND, k=1, n=2, eps=1.0, n_p=1,
                              r_load_ohm=R0)
        assert rep["fit"]["converged"] is True
        ladder = rep["ladder"]
        assert ladder["status"] == "complete"
        assert ladder["load_verdict"] == "matched"
        polys = rep["polynomials"]
        omega_mid = rep["omega_mid_rad_s"]
        wn = W_BAND / omega_mid
        lam = 1j * wn
        s21_model = (np.polyval(polys["p21"], -(wn ** 2)) * lam
                     / np.polyval(polys["g"], lam))
        net = srft_network_response(ladder["elements"],
                                    ladder["remainder_ohm"],
                                    W_BAND / (2 * math.pi), R0)
        assert np.max(np.abs(np.abs(net["s21"]) - np.abs(s21_model))) \
            <= 1e-6
        # 提取网络无损恒等式
        assert np.max(np.abs(np.abs(net["s11"]) ** 2
                             + np.abs(net["s21"]) ** 2 - 1.0)) <= 1e-9

    def test_fit_flatness_improves_over_shape(self):
        fit = srft_fit_flat_gain(W_BAND, k=1, n=2, eps=1.0, n_p=1,
                                 target_t0=0.5)
        t = fit["t_band"]
        # 拟合确实向目标靠拢（带内均值接近 T0，非平凡解）
        assert abs(float(np.mean(t)) - fit["t0"]) < 0.25
        assert float(np.max(t)) <= 1.0 + 1e-12
        assert fit["converged"] is True


class TestBodeFanoConsistency:
    def test_gamma_integral_within_bound(self):
        """round17 验收：综合网络终接并联 RC 负载的 |Γ| 积分 ≤ π/(RC)。

        Bode 1945/Fano 1950 界对**任何**无耗匹配面成立：SRFT 综合的
        梯形网络终接 50∥C，源侧反射 ln(1/|Γ|) 的截断积分（≤全带积
        分）不得越 π/(RC)。limit 与 bounds.bode_fano_rc 同式互证。
        """
        from rfauto.core.bounds import bode_fano_rc

        c_load = 5e-12
        rep = srft_synthesize(W_BAND, k=1, n=2, eps=1.0, n_p=1,
                              r_load_ohm=R0)
        ladder = rep["ladder"]
        assert ladder["status"] == "complete"
        # 宽带 Γ 采样：梯形 ABCD 终接 RC 负载
        f = np.linspace(1e6, 20e9, 4000)
        w = 2 * math.pi * f
        gamma = np.empty(f.size)
        for i, wi in enumerate(w):
            abcd = np.eye(2, dtype=complex)
            for el in ladder["elements"]:
                if el["kind"] == "series_l":
                    abcd = abcd @ np.array(
                        [[1, 1j * wi * el["value_h"]], [0, 1]])
                elif el["kind"] == "shunt_c":
                    abcd = abcd @ np.array(
                        [[1, 0], [1j * wi * el["value_f"], 1]])
            y_load = 1.0 / R0 + 1j * wi * c_load
            z_load = 1.0 / y_load
            zin = ((abcd[0, 0] * z_load + abcd[0, 1])
                   / (abcd[1, 0] * z_load + abcd[1, 1]))
            gamma[i] = abs((zin - R0) / (zin + R0))
        integral = float(np.trapezoid(np.log(1.0 / gamma), w))
        verdict = bode_fano_rc((R0, c_load), None, gamma_target=0.5,
                               bandwidth=1e9)
        assert verdict.limit_value == pytest.approx(
            math.pi / (R0 * c_load), rel=1e-9)
        assert integral <= verdict.limit_value
