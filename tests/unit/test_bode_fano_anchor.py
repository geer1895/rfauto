"""A-17：Bode-Fano 并联 RC 积分界的文献锚测试（合成回收，#118 纪律）。

把 V1 裁决席（P0，2026-10-04）核验的文献常数固化为 pytest 锚：

    ∫₀^∞ ln(1/|Γ(ω)|) dω ≤ π/(RC)          （并联 RC，ω 为 rad/s 全带宽）

出处（多源逐字对照见 runs/review_ge8e/v1_bode_fano/REPORT.md §1）：

- **Fano 1948** MIT RLE Technical Report No. 41《Theoretical Limitations
  on the Broadband Matching of Arbitrary Impedances》§1 p.3 Eqs.(3)(4)
  （矩形带 ω·ln(1/|ρ|max) ≤ π/(RC)，ω in rad. per sec.）；p.16
  "parallel RC ⇒ A₁ = 2/RC"（Fano Eq.(21) 的 (π/2)A₁ 代入即 π/(RC)）；
- Pozar《Microwave Engineering》Table 5.2 并联 RC 行（3rd ed. §5.9）；
- Steer《Microwave and RF Design III》§7.2 Fano-Bode Limits；
- Kerr（NRAO EDM-295）§II 同式。

防再犯注记（C1-1 误报，V1 裁决不成立）：并联 RC 行常数是 **π/τ**
（τ=RC）；π/(2RC) 系对偶拓扑行（串联 RC/并联 RL）与 Hz 口径各差一个
2 因子的混读——本锚同时钉死数值积分恰为 π/(2RC) 的 **2 倍**。

方法（解析可复算的合成回收，不依赖任何拟合）：已知 R/C 合成并联 RC
负载对参考 Z0 的 Γ(jω)，数值积分其 ln(1/|Γ|) 面积（以 |Γ| 极点尺度
β 自适应展开的 log 网格 + 端部解析修正），与闭式 π/(RC)（R=Z0）及
π/(C·max(R,Z0))（一般 R）对拍。零求解器调用、无网络。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.bounds import bode_fano_rc


def _gamma_parallel_rc(omega: np.ndarray, r: float, c: float,
                       z0: float) -> np.ndarray:
    """并联 RC 负载对参考 z0 的反射系数（解析，逐点）。"""
    z = r / (1.0 + 1j * omega * r * c)
    return (z - z0) / (z + z0)


def _integrate_log_inv_gamma(r: float, c: float, z0: float,
                             n: int = 400_001) -> float:
    """数值积分 ∫₀^∞ ln(1/|Γ(ω)|) dω（log 网格 + 端部解析修正）。

    |Γ| 的频率尺度由极点参数 β=(R+Z0)/(R·Z0·C) 设定（|Γ|²=(ω²+α²)/
    (ω²+β²)，α=(R−Z0)/(R·Z0·C)，R=Z0 时 α=0），网格取 β·[1e-8, 1e8]：
    两个端点均深入渐近域，端部修正可用解析式且相对贡献 ~1e-8：

    - 头部 [0, ω_lo]：R=Z0 时被积函数 0.5·ln(4/(ωRC)²) 对 lnω 线性，
      闭式 x·(ln(2/x)+1)（x=ωRC）；R≠Z0 时趋于有限常数 0.5·ln(β²/α²)；
    - 尾部 [ω_hi, ∞)：0.5·(β²−α²)/ω² 渐近（ω_hi≫β 处 ln(1+u)≈u 精确）。
    """
    beta = (r + z0) / (r * z0 * c)
    omega = np.logspace(math.log10(beta) - 8.0, math.log10(beta) + 8.0, n)
    integrand = np.log(1.0 / np.abs(_gamma_parallel_rc(omega, r, c, z0)))
    area = float(np.trapezoid(integrand, omega))
    omega_lo, omega_hi = float(omega[0]), float(omega[-1])
    if math.isclose(r, z0, rel_tol=0.0, abs_tol=1e-12 * max(r, z0)):
        x = omega_lo * r * c
        area += x * (math.log(2.0 / x) + 1.0)
    else:
        area += float(integrand[0]) * omega_lo
    alpha = abs(r - z0) / (r * z0 * c)
    area += 0.5 * (beta ** 2 - alpha ** 2) / omega_hi
    return area


class TestBodeFanoParallelRcAnchor:
    """数值积分 ↔ π/(RC) 文献锚（并联 RC、rad/s 全带宽口径）。"""

    @pytest.mark.parametrize(("r_ohm", "c_farad"), [
        (50.0, 2e-12),    # V1 数值验证案（REPORT.md §2 同参）
        (75.0, 1e-12),
        (50.0, 5e-12),
    ])
    def test_matched_reference_area_is_pi_over_tau(self, r_ohm, c_farad):
        """R=Z0：∫ ln(1/|Γ|)dω = π/(RC)（与 Z0 数值无关的严格等式）。"""
        area = _integrate_log_inv_gamma(r_ohm, c_farad, r_ohm)
        tau = r_ohm * c_farad
        expected = math.pi / tau
        assert area == pytest.approx(expected, rel=2e-5), (
            f"R=Z0={r_ohm}Ω C={c_farad}F: 数值面积 {area:.6e} vs "
            f"π/τ {expected:.6e}（rel={abs(area / expected - 1):.2e}）")

    @pytest.mark.parametrize(("r_ohm", "z0", "c_farad"), [
        (25.0, 50.0, 2e-12),    # R<Z0：面积 = π/(C·Z0)
        (100.0, 50.0, 2e-12),   # R>Z0：面积 = π/(C·R)
    ])
    def test_general_r_area_is_pi_over_c_max(self, r_ohm, z0, c_farad):
        """一般 R：∫ ln(1/|Γ|)dω = π/(C·max(R,Z0))（V1 §2 的
        |Γ|²=(ω²+α²)/(ω²+β²) 标准积分式，本测试独立数值回收）。"""
        area = _integrate_log_inv_gamma(r_ohm, c_farad, z0)
        expected = math.pi / (c_farad * max(r_ohm, z0))
        assert area == pytest.approx(expected, rel=5e-4), (
            f"R={r_ohm}Ω Z0={z0}Ω C={c_farad}F: 数值面积 {area:.6e} vs "
            f"π/(C·max) {expected:.6e}（rel={abs(area / expected - 1):.2e}）")

    def test_area_is_exactly_twice_the_ci1_claim(self):
        """C1-1 防再犯锚：数值面积 / (π/(2RC)) ≈ 2.0——"π/(2RC)" 恰差
        整一倍（V1 REPORT §2：对 π/(2τ) 的相对误差=1.000）。"""
        r, c = 50.0, 2e-12
        area = _integrate_log_inv_gamma(r, c, r)
        assert area / (math.pi / (2.0 * r * c)) == pytest.approx(
            2.0, rel=1e-4)

    def test_bounds_implementation_limit_matches_literature_anchor(self):
        """交叉钉：core/bounds.bode_fano_rc 的 limit_value（π/τ）与文献锚
        数值积分一致——常数若被改成 π/(2τ)（C1-1 提案）此锚即红。"""
        r, c = 50.0, 2e-12
        verdict = bode_fano_rc((r, c), None, gamma_target=0.1, bandwidth=1e9)
        assert verdict.limit_value == pytest.approx(math.pi / (r * c))
        area = _integrate_log_inv_gamma(r, c, r)
        assert verdict.limit_value == pytest.approx(area, rel=2e-5)
