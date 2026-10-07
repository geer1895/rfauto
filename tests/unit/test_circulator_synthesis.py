"""F-K.B 环形器综合内核单测（研究扩充 round6 §二 F-K.B）。

裁判口径（#118：独立来源/双路径，不自证）：
- Polder 全式的解析极限与共振闭式按两条代数路径离线推导（环行支分解
  μ±κ = 1+ω_m/(ω_h+jαω∓ω) 恒等式路径 vs 公式直代路径）；
- 外部锚 = Bosma 1964 原文（MTT-12(1):61-72，mtt.org 公开 PDF 已逐式
  核对）自报设计点印刷值：450 MHz、4πM=1750 G、ΔH=150 G、εr=14.2、
  v=15 mm → Hi=935 Oe、h=5.82、κ/μ=0.112、R=3.07 cm、v/R=0.48；
- J₁′ 第一零点 = scipy jvp 与 J₀−J₁/x 恒等式两条独立求根路径互证
  rel 1e-16，全精度值 1.8411837813406593 经 mpmath 40 位
  findroot 独立验证（2026-09-27），另钉 Bosma 原文 verbatim 1.84。

**判据预声明修正（如实登记）**：任务书判据草稿"共振点 ω=ω_h 时 κ 实部
=ω_m/(2ω_h)"与钉死公式不符——按钉死的含损 Polder 直代，共振点
Re(κ) = −ω_m/(ω_h(4+α²)) → −ω_m/(4ω_h)（α→0，见
test_polder_resonance_exact_forms 推导）；有限值 ω_m/(2ω_h) 属环行支
μ−κ 的共振实部（1+ω_m/(2ω_h)，环行支分解恒等式路径）。本文件按推导
值钉（#122：不凑草稿口径），解析推导过程在各测试 docstring。

UNVERIFIED 引源（任务书要求如实登记）：Wu-Rosenbaum 精确隔离度-带宽
百分比（原文未读）、Konishi 集总环形器细节（二手转述）、Bosma Eq.69
耦合角系数（原文文本层乱码）——均不进数值判据。
"""

from __future__ import annotations

import cmath
import json
import math
import sys
from itertools import pairwise
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core import circulator_synthesis as circ
from rfauto.service import circulator_synthesis_service as svc

# ─── 共用测试常数（SI） ───────────────────────────────────────────────────────
MU0 = circ.MU_0
GYRO = circ.GYRO_RAD_S_T

# Bosma 1964 原文设计点（4πMs=1750 G、Hi=935 Oe → μ0·M 单位制转 SI）
MS_BOSMA = 1750.0 * circ.GAUSS_TO_A_PER_M  # = 0.175 T / μ0
HI_BOSMA = 935.0 * 1.0e-4 / MU0  # 935 Oe → μ0·H = 93.5 mT

# 1 GHz 标称测试点：ω_h = 2π·1e9、ω_m = 0.5·ω_h
_WH_1GHZ = 2.0 * math.pi * 1.0e9
_HI_1GHZ = _WH_1GHZ / (GYRO * MU0)
_MS_HALF = _HI_1GHZ / 2.0


def _f_mult_of_wh(h_i_a_per_m: float, mult: float) -> float:
    """ω = mult·ω_h(H_i) 对应的频率（Hz）——截止带测试用（ω=2ω_h、ω_m=2ω_h）。"""
    return mult * GYRO * MU0 * h_i_a_per_m / (2.0 * math.pi)


# ─── 0. 常数双路径 ────────────────────────────────────────────────────────────


def test_constants_gyro_dual_path():
    # γ 对任务书钉值 1.760859e11（7 位"≈"级近似）锁定：现行 CODATA
    # 1.76085962784e11 与该 7 位舍入值差 3.6e-7（1.7608596… 按 7 位应
    # 入到 1.760860e11）——钉 1e-6 容差并如实注记，不虚标更紧
    assert pytest.approx(1.760859e11, rel=1e-6) == GYRO
    # γ 与 γ/2π 同源自洽（NIST 对表值 28.0249513861 GHz/T ↔ 除法逐位复核）
    gyro_from_2pi = 2.0 * math.pi * circ.GYRO_OVER_2PI_GHZ_T * 1.0e9
    assert pytest.approx(gyro_from_2pi, rel=1e-10) == GYRO
    # μ0-ε0-c 恒等式（SI 自洽）
    mu0_eps0_c2 = MU0 * circ.EPS_0 * circ.C_0**2
    assert mu0_eps0_c2 == pytest.approx(1.0, rel=1e-12)


# ─── 1. Polder 极限行为（ω→0 / ω→∞） ────────────────────────────────────────


def test_polder_low_frequency_limit():
    """ω→0：μ→1+ω_m/ω_h（rel 1e-12）、κ→ω_m·ω/ω_h²（线性趋零）。"""
    p = circ.polder_permeability(1.0e9 * 1.0e-7, _MS_HALF, _HI_1GHZ)  # ω=1e-7·ω_h
    om_h, om = p.omega_h_rad_s, p.omega_m_rad_s
    assert p.mu == pytest.approx(1.0 + om / om_h, rel=1e-12)
    assert p.kappa == pytest.approx(om * p.omega_rad_s / om_h**2, rel=1e-12)


def test_polder_high_frequency_limit():
    """ω→∞：μ→1、κ→0（解析尾界 (ω_m/ω_h)·(ω_h/ω) 量级）。"""
    om_ratio = _MS_HALF / _HI_1GHZ  # = ω_m/ω_h = 0.5
    p = circ.polder_permeability(1.0e9 * 1.0e6, _MS_HALF, _HI_1GHZ)  # ω=1e6·ω_h
    assert abs(p.mu - 1.0) <= 1.001e-12 * om_ratio
    assert abs(p.kappa) <= 1.001e-6 * om_ratio


def test_polder_circular_decomposition_identity():
    """环行支分解恒等式（双路径裁判）：μ±κ = 1+ω_m/(ω_h+jαω∓ω)。

    推导：D=(ω_h+jαω)²−ω²=(ω_h+jαω−ω)(ω_h+jαω+ω)，分子相加/相减恰好
    约去一个因子——精确恒等式，非近似。
    """
    for f_mult in (0.3, 0.7, 1.3, 2.5):
        p = circ.polder_permeability(1.0e9 * f_mult, _MS_HALF, _HI_1GHZ, alpha=0.05)
        w = p.omega_rad_s
        wh = p.omega_h_rad_s
        assert (p.mu + p.kappa) == pytest.approx(1.0 + p.omega_m_rad_s / (wh + 1j * 0.05 * w - w), rel=1e-12)
        assert (p.mu - p.kappa) == pytest.approx(1.0 + p.omega_m_rad_s / (wh + 1j * 0.05 * w + w), rel=1e-12)


# ─── 2. 共振点闭式（任务书判据修正的推导落点） ────────────────────────────────


def test_polder_resonance_exact_forms():
    """ω=ω_h（含损 α）四条共振闭式（双路径：手推闭式 vs 公式直代）。

    推导（ω=ω_h 记 a=α）：分母 = ω_h²α(2j−a)，
    κ = (ω_m/ω_h)/(a(2j−a)) = −(ω_m/ω_h)·(1+2j/a)/(4+a²) →
      Re κ = −ω_m/(ω_h(4+a²))，Im κ = −2ω_m/(a·ω_h(4+a²))；
    μ−1 = (ω_m/ω_h)·(a−j(2+a²))/(a(4+a²)) →
      Re μ = 1+ω_m/(ω_h(4+a²))；Re(μ−κ) = 1+2ω_m/(ω_h(4+a²))。
    """
    p = circ.polder_permeability(1.0e9, _MS_HALF, _HI_1GHZ, alpha=0.05)
    assert p.omega_rad_s == pytest.approx(p.omega_h_rad_s, rel=1e-15)  # 确在共振点
    a2 = 0.05**2
    om_h, om = p.omega_h_rad_s, p.omega_m_rad_s
    assert p.kappa.real == pytest.approx(-om / (om_h * (4.0 + a2)), rel=1e-12)
    assert p.kappa.imag == pytest.approx(-2.0 * om / (0.05 * om_h * (4.0 + a2)), rel=1e-12)
    assert p.mu.real == pytest.approx(1.0 + om / (om_h * (4.0 + a2)), rel=1e-12)
    assert (p.mu - p.kappa).real == pytest.approx(1.0 + 2.0 * om / (om_h * (4.0 + a2)), rel=1e-12)


def test_polder_resonance_kappa_real_part_honest_pin():
    """如实钉共振点 Re(κ) 极限 = −ω_m/(4ω_h)（α→0）。

    **判据修正登记**：任务书草稿"Re κ = +ω_m/(2ω_h)"与钉死公式不符
    （见文件 docstring）；α→0 时 Re κ → −ω_m/(4ω_h)。
    **精度边界（如实登记，#118 族）**：α 取 1e-2——更小的 α 下共振点
    的 ~ulp 级 ω/ω_h 失配（ω²−ω_h² ~ 4e-16·ωh²）与 α² 项可比，断言
    rel 无法优于 ~1e-4；α=1e-2 时主误差 = α²/4 = 2.5e-5（exact-form
    路径已在 test_polder_resonance_exact_forms 以 rel 1e-12 钉死）。
    """
    p = circ.polder_permeability(1.0e9, _MS_HALF, _HI_1GHZ, alpha=1.0e-2)
    limit = -p.omega_m_rad_s / (4.0 * p.omega_h_rad_s)
    assert p.kappa.real == pytest.approx(limit, rel=1e-4)


def test_polder_resonance_finite_branch_wm_over_2wh_limit():
    """环行支 μ−κ 共振实部 → 1+ω_m/(2ω_h)（任务书草稿数值的真实落点）。

    μ−κ = 1+ω_m/(ω_h+ω+jαω)（精确恒等式，见环行支分解），ω=ω_h 时
    Re = 1+2ω_m/(ω_h(4+α²)) → 1+ω_m/(2ω_h)。
    """
    p = circ.polder_permeability(1.0e9, _MS_HALF, _HI_1GHZ, alpha=1.0e-7)
    limit = 1.0 + p.omega_m_rad_s / (2.0 * p.omega_h_rad_s)
    assert (p.mu - p.kappa).real == pytest.approx(limit, rel=1e-9)


def test_polder_lossless_resonance_singularity_guard():
    """无损 α=0 且 ω=ω_h：Polder 发散，显式 ValueError（不裸 ZeroDivision）。"""
    with pytest.raises(ValueError, match="共振奇点"):
        circ.polder_permeability(1.0e9, _MS_HALF, _HI_1GHZ)  # ω=ω_h 构造


# ─── 3. 损耗通道 ──────────────────────────────────────────────────────────────


def test_polder_delta_h_alpha_channel():
    """ΔH 通道：α = γμ0ΔH/ω 恒等式；ΔH 增大 → |Im μ| 单调增大。"""
    f = 0.5e9
    dh = 50.0
    alpha_expected = GYRO * MU0 * dh / (2.0 * math.pi * f)
    assert circ.alpha_from_linewidth(dh, f) == pytest.approx(alpha_expected, rel=1e-12)
    p1 = circ.polder_permeability(f, _MS_HALF, _HI_1GHZ, delta_h_a_per_m=dh)
    p2 = circ.polder_permeability(f, _MS_HALF, _HI_1GHZ, alpha=alpha_expected)
    assert p1.mu == p2.mu and p1.kappa == p2.kappa  # 两通道同参逐位同结果
    assert p1.alpha == pytest.approx(alpha_expected, rel=1e-12)
    p3 = circ.polder_permeability(f, _MS_HALF, _HI_1GHZ, delta_h_a_per_m=10.0 * dh)
    assert abs(p3.mu.imag) > abs(p1.mu.imag) > 0.0  # 损耗单调（e^{+jωt} 口径 Im<0）


def test_polder_loss_channels_exclusive():
    """ΔH 与 α 同给 → 显式报错（通道歧义）；都不给 → 无损 α=0。"""
    with pytest.raises(ValueError, match="二选一"):
        circ.polder_permeability(1.0e9, _MS_HALF, _HI_1GHZ, delta_h_a_per_m=50.0, alpha=0.01)
    p = circ.polder_permeability(0.5e9, _MS_HALF, _HI_1GHZ)
    assert p.alpha == 0.0 and p.mu.imag == 0.0 and p.kappa.imag == 0.0


def test_polder_cgs_conversion_identity():
    """SI/CGS 换算注记实现载体：ω_m = γ·μ0·Ms[SI] = γ·(4πMs[G]×1e-4 T)。

    双路径：Ms[A/m] = 4πMs[G]·GAUSS_TO_A_PER_M vs 4πMs 印刷值换 Tesla。
    另钉 Oe→A/m：935 Oe 走 cgs 常数 10³/(4π) vs μ0 单位制换算（CODATA μ0
    与定义值 4πe-7 差 ~5.4e-10 相对，容 1e-8）。
    """
    ms_si = 1750.0 * circ.GAUSS_TO_A_PER_M
    p = circ.polder_permeability(450.0e6, ms_si, HI_BOSMA)
    assert p.omega_m_rad_s == pytest.approx(GYRO * 1750.0 * 1.0e-4, rel=1e-12)  # Tesla 路径
    assert p.omega_m_rad_s == pytest.approx(GYRO * MU0 * ms_si, rel=1e-12)  # SI 直代路径
    hi_cgs = 935.0 * 1000.0 / (4.0 * math.pi)  # Oe→A/m（精确定义值口径）
    hi_expected = HI_BOSMA
    assert hi_expected == pytest.approx(hi_cgs, rel=1e-8)


# ─── 4. Bosma 1964 原文设计点外部锚 ──────────────────────────────────────────


def test_polder_bosma_design_point_anchor():
    """Bosma 原文自报设计点复现（外部印刷值锚，容差按其近似精度预声明）。

    原文：h=5.82、κ/μ=0.112（其 (77)/(78) 远共振闭式+舍入）；全式
    Polder 预期偏差 ~1% 级（原文自身含 s=ΔH/H₀ 修正与两位舍入）。
    """
    p = circ.polder_permeability(450.0e6, MS_BOSMA, HI_BOSMA)  # 无损实部口径
    h = p.omega_h_rad_s / p.omega_rad_s
    assert h == pytest.approx(5.82, rel=0.005)
    kappa_over_mu = p.kappa.real / p.mu.real
    assert kappa_over_mu == pytest.approx(0.112, rel=0.03)


def test_polder_far_above_resonance_cross_check():
    """Bosma Eq.77/78 远共振闭式（独立路径）vs 全式 Polder vs 原文 0.112。

    闭式 κ/μ_eff = m/(h(h+m)) 与原文印刷值 0.112 差 <0.1%（同源近似）；
    全式 μ_eff 与闭式 μ_eff=(h+m)/h 差 ~0.7%（高阶项，预声明容 2%）。
    """
    fa = circ.bosma_far_above_resonance(450.0e6, MS_BOSMA, HI_BOSMA)
    assert fa["h"] == pytest.approx(5.82, rel=0.005)
    assert fa["kappa_over_mu_eff"] == pytest.approx(0.112, rel=0.01)
    p = circ.polder_permeability(450.0e6, MS_BOSMA, HI_BOSMA)
    mue = circ.mu_effective(p.mu, p.kappa)
    assert mue.real == pytest.approx(fa["mu_eff_approx"], rel=0.02)
    # κ 幅值：全式 vs 闭式 κ ≈ m/h²
    assert abs(p.kappa) == pytest.approx(fa["kappa_approx"], rel=0.05)


# ─── 5. 入参守卫 ──────────────────────────────────────────────────────────────


def test_polder_input_guards():
    """Ms≤0 / H_i≤0 / f0≤0 / 非有限 / bool / 未饱和 → ValueError。"""
    for args in (
        (0.0, _MS_HALF, _HI_1GHZ),  # f0≤0
        (-1.0, _MS_HALF, _HI_1GHZ),
        (1.0e9, 0.0, _HI_1GHZ),  # Ms≤0
        (1.0e9, -5.0, _HI_1GHZ),
        (1.0e9, _MS_HALF, 0.0),  # H_i≤0
        (1.0e9, _MS_HALF, -1.0),
        (float("nan"), _MS_HALF, _HI_1GHZ),  # 非有限
        (1.0e9, float("inf"), _HI_1GHZ),
        (True, _MS_HALF, _HI_1GHZ),  # bool 显式拒收（df7+⑯）
    ):
        with pytest.raises(ValueError):
            circ.polder_permeability(*args)
    with pytest.raises(ValueError, match="未饱和"):
        circ.polder_permeability(1.0e9, _MS_HALF, _HI_1GHZ, h_sat_a_per_m=_HI_1GHZ * 1.1)
    # h_sat 判据恰等 → 通过（非严格小于；离共振点评估避开无损奇点）
    p = circ.polder_permeability(0.5e9, _MS_HALF, _HI_1GHZ, h_sat_a_per_m=_HI_1GHZ)
    assert p.mu is not None
    with pytest.raises(ValueError):
        circ.polder_permeability(1.0e9, _MS_HALF, _HI_1GHZ, alpha=-0.1)
    with pytest.raises(ValueError):
        circ.polder_permeability(1.0e9, _MS_HALF, _HI_1GHZ, delta_h_a_per_m=-1.0)


# ─── 6. μ_eff 与截止带 ───────────────────────────────────────────────────────


def test_mu_effective_cutoff_band_exact():
    """截止带解析回收：ω=2ω_h、ω_m=2ω_h → μ=1/3、κ=−4/3、μ_eff=−5。

    推导（无损）：μ_eff = ((ω_h+ω_m)²−ω²)/(ω_h(ω_h+ω_m)−ω²)，分子
    9−4=5、分母 3−4=−1 → −5；负值合法返回（截止带）。
    """
    f = _f_mult_of_wh(3.0e4, 2.0)  # ω = 2ω_h（H_i=3e4 A/m 口径）
    p = circ.polder_permeability(f, 2.0 * 3.0e4, 3.0e4)  # ω_m=2ω_h
    assert p.mu == pytest.approx(1.0 / 3.0, rel=1e-12)
    assert p.kappa == pytest.approx(-4.0 / 3.0, rel=1e-12)
    mue = circ.mu_effective(p.mu, p.kappa)
    assert mue == pytest.approx(-5.0, rel=1e-12)
    with pytest.raises(ValueError):
        circ.mu_effective(0j, p.kappa)  # μ=0 非物理输入


# ─── 7. J₁′ 第一零点与盘半径 ─────────────────────────────────────────────────


def test_j1_prime_first_root_dual_path_and_published():
    """J₁′ 第一零点：jvp 求根 vs J₀−J₁/x 恒等式求根（独立路径互证）。

    全精度锚 1.8411837813406593 = mpmath 40 位 findroot（besselj 导数，
    2026-09-27 独立验证）；Bosma 原文 verbatim 1.84 差 0.064%。
    """
    x_kernel = circ.j1_prime_first_root()
    from scipy.optimize import brentq
    from scipy.special import jv

    x_identity = brentq(lambda x: float(jv(0, x) - jv(1, x) / x), 1.5, 2.5, xtol=1e-14)
    assert x_kernel == pytest.approx(x_identity, rel=1e-10)
    assert x_kernel == pytest.approx(1.8411837813406593, rel=1e-12)
    assert x_kernel == pytest.approx(circ.KR_CLASSIC_1P84, rel=1.0e-3)  # Bosma 1.84


def test_disk_radius_roundtrip_and_units():
    """R 初值往返：k·R = x₁,₁（rel 1e-12）+ 单位链（mm/m 换算）自洽。"""
    d = circ.disk_design(450.0e6, 14.2, MS_BOSMA, HI_BOSMA)
    assert not d.cutoff and d.r_mm is not None and d.k_rad_per_m is not None
    kr = d.k_rad_per_m * (d.r_mm * 1.0e-3)
    assert kr == pytest.approx(d.kr_target, rel=1e-12)
    # k = ω√(μ0 ε0 εr Re μ_eff) 独立重算
    k_hand = 2.0 * math.pi * 450.0e6 * math.sqrt(MU0 * circ.EPS_0 * 14.2 * d.mu_eff.real)
    assert d.k_rad_per_m == pytest.approx(k_hand, rel=1e-12)


def test_disk_radius_bosma_and_xband_order():
    """设计量级：Bosma 点 R=30.5 mm（原文 30.7 cm 级，容 2%）；X 波段
    YIG 类设计落 mm 量级（0.5-5 mm 松界——量级 sanity，非文献钉值）。"""
    d = circ.disk_design(450.0e6, 14.2, MS_BOSMA, HI_BOSMA)
    assert d.r_mm == pytest.approx(30.7, rel=0.02)
    ms_yig = 1780.0 * circ.GAUSS_TO_A_PER_M  # 4πMs=1780 G
    h0_10g = 2.0 * math.pi * 10.0e9 / (GYRO * MU0)
    d10 = circ.disk_design(10.0e9, 15.0, ms_yig, 3.0 * h0_10g)
    assert not d10.cutoff
    assert 0.5 <= d10.r_mm <= 5.0


def test_disk_radius_cutoff_flag():
    """截止带：cutoff=True、r_mm/k 如实 None、μ_eff 负值保留不钳位。"""
    d = circ.disk_design(_f_mult_of_wh(3.0e4, 2.0), 10.0, 2.0 * 3.0e4, 3.0e4)
    assert d.cutoff
    assert d.r_mm is None and d.k_rad_per_m is None
    assert d.mu_eff.real == pytest.approx(-5.0, rel=1e-12)
    with pytest.raises(ValueError):
        circ.disk_design(-1.0, 10.0, _MS_HALF, _HI_1GHZ)  # f0≤0
    with pytest.raises(ValueError):
        circ.disk_design(1.0e9, 0.0, _MS_HALF, _HI_1GHZ)  # εr≤0


# ─── 8. 理想 / 准理想 S 矩阵 ─────────────────────────────────────────────────


def test_ideal_s_circulation_and_unitarity():
    """理想口径：|S21|=|S32|=|S13|=1 其余 0；酉性 S·S†=I；能量=3。"""
    s = circ.ideal_junction_s_matrix()
    expect = {(1, 0), (2, 1), (0, 2)}  # (row, col) of S21/S32/S13
    for i in range(3):
        for j in range(3):
            v = s.matrix[i][j]
            if (i, j) in expect:
                assert abs(v) == pytest.approx(1.0, rel=1e-12)
            else:
                assert abs(v) == pytest.approx(0.0, abs=1e-15)
    mat = [[complex(v) for v in row] for row in s.matrix]
    prod = [[sum(mat[i][k] * mat[j][k].conjugate() for k in range(3)) for j in range(3)] for i in range(3)]
    for i in range(3):
        for j in range(3):
            expect_ij = 1.0 if i == j else 0.0
            assert prod[i][j].real == pytest.approx(expect_ij, rel=1e-12, abs=1e-12)
            assert prod[i][j].imag == pytest.approx(0.0, abs=1e-12)
    assert s.total_energy == pytest.approx(3.0, rel=1e-12)


def test_ideal_s_sense_and_phase_parameterization():
    """反向 sense 环行序翻转；全体系相位 e^{jφ} 旋量参数化。"""
    s_rev = circ.ideal_junction_s_matrix(sense=-1)
    assert abs(s_rev.matrix[0][1]) == pytest.approx(1.0)  # S12（1→3→2→1）
    assert abs(s_rev.matrix[1][2]) == pytest.approx(1.0)
    assert abs(s_rev.matrix[2][0]) == pytest.approx(1.0)
    phi = math.pi / 7.0
    s_ph = circ.ideal_junction_s_matrix(phase_rad=phi)
    rot = cmath.exp(1j * phi)
    assert s_ph.matrix[1][0] == pytest.approx(rot, rel=1e-12)
    assert s_ph.total_energy == pytest.approx(3.0, rel=1e-12)


def test_ideal_s_eigenvalues_120deg_phase_order():
    """本征值 = {1, e^{±j2π/3}}：120° 相位序（含回绕 gap 全等）。"""
    s = circ.ideal_junction_s_matrix()
    ev = circ.junction_eigenvalues(s)
    phases = [cmath.phase(e) for e in ev]
    gaps = [
        phases[1] - phases[0],
        phases[2] - phases[1],
        phases[0] + 2.0 * math.pi - phases[2],
    ]
    for g in gaps:
        assert g == pytest.approx(2.0 * math.pi / 3.0, rel=1e-9)
    assert abs(ev[1] - 1.0) == pytest.approx(0.0, abs=1e-9)  # 单位模


def test_cyclic_permutation_similarity():
    """120° 旋转对称：S = P·S·P⁻¹（理想与准理想环行 S 恒成立）。"""
    s = circ.ideal_junction_s_matrix()
    assert circ.cyclic_permutation_similarity(s)
    s_lossy = circ.quasi_ideal_lossy_s_matrix(0.25)
    assert circ.cyclic_permutation_similarity(s_lossy)


def test_quasi_ideal_lossy_energy_monotone():
    """耗散口径：|S 环行项|=√(1−ℓ)、能量 3(1−ℓ) 单调递减。"""
    energies = []
    for lf in (0.0, 0.1, 0.25, 0.5, 0.9):
        s = circ.quasi_ideal_lossy_s_matrix(lf)
        assert abs(s.matrix[1][0]) == pytest.approx(math.sqrt(1.0 - lf), rel=1e-12)
        assert s.total_energy == pytest.approx(3.0 * (1.0 - lf), rel=1e-12)
        energies.append(s.total_energy)
    assert energies == sorted(energies, reverse=True)
    assert all(e1 < e0 for e0, e1 in pairwise(energies))


def test_loss_fraction_from_polder_monotone_in_linewidth():
    """ΔH → 磁损耗分数：单调、非负、ΔH→0 时 →0（逐位 0.0）。"""
    p1 = circ.polder_permeability(1.0e9, _MS_HALF, _HI_1GHZ, delta_h_a_per_m=100.0)
    p2 = circ.polder_permeability(1.0e9, _MS_HALF, _HI_1GHZ, delta_h_a_per_m=1000.0)
    l1 = circ.magnetic_loss_fraction(p1)
    l2 = circ.magnetic_loss_fraction(p2)
    assert 0.0 < l1 < l2 < 1.0
    p0 = circ.polder_permeability(0.5e9, _MS_HALF, _HI_1GHZ)  # 离共振点（无损无奇点）
    assert circ.magnetic_loss_fraction(p0) == 0.0
    # 截止带 → loss 口径不适用（显式报错，不硬造）
    p_cut = circ.polder_permeability(_f_mult_of_wh(3.0e4, 2.0), 2.0 * 3.0e4, 3.0e4)
    with pytest.raises(ValueError, match="截止带"):
        circ.magnetic_loss_fraction(p_cut)


def test_s_matrix_guards():
    """loss∈[0,1) 边界与 sense 枚举守卫。"""
    with pytest.raises(ValueError):
        circ.quasi_ideal_lossy_s_matrix(1.0)
    with pytest.raises(ValueError):
        circ.quasi_ideal_lossy_s_matrix(-0.1)
    with pytest.raises(ValueError):
        circ.ideal_junction_s_matrix(sense=0)
    with pytest.raises(ValueError):
        circ.quasi_ideal_lossy_s_matrix(True)  # bool 拒收（df7+⑯）


# ─── 9. 匹配与耦合角 ─────────────────────────────────────────────────────────


def test_quarter_wave_transformer():
    """λ/4 变换段 Z_T=√(Z_j·Z0)：回收 + 恒等（Z_T²=Z_j·Z0）+ 守卫。"""
    zt = circ.quarter_wave_transformer_impedance(100.0, 50.0)
    assert zt == pytest.approx(math.sqrt(5000.0), rel=1e-12)
    assert zt * zt == pytest.approx(100.0 * 50.0, rel=1e-12)
    assert circ.quarter_wave_transformer_impedance(50.0, 50.0) == pytest.approx(50.0, rel=1e-12)
    with pytest.raises(ValueError):
        circ.quarter_wave_transformer_impedance(0.0, 50.0)
    with pytest.raises(ValueError):
        circ.quarter_wave_transformer_impedance(-5.0, 50.0)


def test_coupling_angle_geometry_roundtrip():
    """Bosma Eq.8 几何：ψ=arcsin(v/2R) 往返逐位级 + 原文 v/R=0.48 锚。"""
    psi = circ.coupling_angle_from_stripline_width(30.7, 15.0)
    assert psi == pytest.approx(math.asin(15.0 / (2.0 * 30.7)), rel=1e-12)
    v_back = circ.stripline_width_from_coupling_angle(30.7, psi)
    assert v_back == pytest.approx(15.0, rel=1e-12)
    # 原文 v/R=0.48 → ψ=arcsin(0.24)
    assert circ.coupling_angle_from_stripline_width(1.0, 0.48) == pytest.approx(math.asin(0.24), rel=1e-12)
    with pytest.raises(ValueError):
        circ.coupling_angle_from_stripline_width(1.0, 2.1)  # v>2R 非物理
    with pytest.raises(ValueError):
        circ.stripline_width_from_coupling_angle(1.0, 0.0)  # ψ∉(0,π/2]
    with pytest.raises(ValueError):
        circ.stripline_width_from_coupling_angle(1.0, math.pi)


def test_bosma_coupling_angle_estimate_unverified_flag():
    """Eq.69 估计式：UNVERIFIED 登记随结果透传 + 对原文点偏差 ~20% 如实钉。

    ψ_est≈0.197 rad vs 原文几何 ψ=arcsin(0.24)≈0.2424 rad → 偏低 ~19%
    （量级正确；系数位置文本层乱码未逐位核对，#122：不进判定）。
    """
    p = circ.polder_permeability(450.0e6, MS_BOSMA, HI_BOSMA)
    km = p.kappa.real / p.mu.real
    mue = circ.mu_effective(p.mu, p.kappa)
    est = circ.bosma_coupling_angle_estimate(km, mue.real, 14.2)
    assert est["unverified"], "UNVERIFIED 清单必须随结果透传"
    psi_actual = math.asin(0.24)
    assert est["psi_rad"] == pytest.approx(psi_actual, rel=0.25)  # 偏差带宽预声明 ±25%


# ─── 10. Wu-Rosenbaum 带宽登记（不臆造数字） ─────────────────────────────────


def test_wu_rosenbaum_reference_no_fabrication():
    """倍频程算术恒等式 + 出处/UNVERIFIED 登记 + Bosma 第一手实验锚。"""
    ref = circ.wu_rosenbaum_bandwidth_reference(3.0e9)
    assert ref["f_high_hz"] == pytest.approx(6.0e9, rel=1e-15)
    assert ref["f_center_geo_hz"] == pytest.approx(math.sqrt(3.0e9 * 6.0e9), rel=1e-12)
    assert ref["fbw_arith"] == pytest.approx(2.0 / 3.0, rel=1e-12)
    assert ref["fbw_geo"] == pytest.approx(1.0 / math.sqrt(2.0), rel=1e-12)
    assert "MTT-22" in ref["claim_source"] and "1974" in ref["claim_source"]
    assert ref["unverified"], "精确隔离度-带宽百分比必须保持 UNVERIFIED 显式登记"
    anchor = ref["bosma_experiment_anchor"]
    assert anchor["band_mhz"] == [310.0, 420.0]
    assert anchor["bandwidth_frac"] == pytest.approx(1.0 / 3.0, rel=1e-12)
    with pytest.raises(ValueError):
        circ.wu_rosenbaum_bandwidth_reference(0.0)


# ─── 11. 集总 LC 环形器（简化面） ─────────────────────────────────────────────


def test_lumped_lc_f0_recycle_and_inversion():
    """f₀=1/(2π√(LC)) 恒等式逐位回收 + 反演（C 由 L,f0）回代一致。"""
    lc = circ.lumped_lc_circulator(10.0e-9, 5.0e-12)
    f0_hand = 1.0 / (2.0 * math.pi * math.sqrt(10.0e-9 * 5.0e-12))
    assert lc.f0_hz == pytest.approx(f0_hand, rel=1e-12)
    # 反演：C = 1/((2πf0)²·L) → 回代 f0 一致
    c_inv = 1.0 / ((2.0 * math.pi * f0_hand) ** 2 * 10.0e-9)
    assert c_inv == pytest.approx(5.0e-12, rel=1e-12)
    lc2 = circ.lumped_lc_circulator(10.0e-9, c_inv)
    assert lc2.f0_hz == pytest.approx(f0_hand, rel=1e-12)


def test_lumped_lc_symmetry_and_guards():
    """集总版理想 S：120° 对称 + 本征值相位序 + sense/入参守卫。"""
    lc = circ.lumped_lc_circulator(10.0e-9, 5.0e-12)
    assert circ.cyclic_permutation_similarity(lc.s_matrix)
    ev = circ.junction_eigenvalues(lc.s_matrix)
    phases = [cmath.phase(e) for e in ev]
    gaps = [phases[1] - phases[0], phases[2] - phases[1], phases[0] + 2.0 * math.pi - phases[2]]
    for g in gaps:
        assert g == pytest.approx(2.0 * math.pi / 3.0, rel=1e-9)
    with pytest.raises(ValueError):
        circ.lumped_lc_circulator(0.0, 5.0e-12)
    with pytest.raises(ValueError):
        circ.lumped_lc_circulator(10.0e-9, -1.0)


# ─── 12. service 面（JSON 信封） ──────────────────────────────────────────────


def test_service_envelope_ok_json():
    """ok=True 信封：数据键齐全、整包 JSON 可序列化（含复数拆分）。"""
    env = svc.circulator_disk_design(
        10.0e9, 15.0, 1780.0 * circ.GAUSS_TO_A_PER_M,
        3.0 * 2.0 * math.pi * 10.0e9 / (GYRO * MU0),
        delta_h_a_per_m=500.0, z_junction_ohm=120.0,
    )
    assert env["ok"] is True and env["schema_version"] == "1.0"
    assert set(env["data"]) == {"polder", "mu_eff", "disk", "s_matrix", "quarter_wave", "provenance"}
    assert env["data"]["quarter_wave"]["z_t_ohm"] == pytest.approx(math.sqrt(120.0 * 50.0), rel=1e-12)
    payload = json.dumps(env)  # 不抛即通过（无 NaN/complex 泄漏）
    assert "NaN" not in payload and "Infinity" not in payload


def test_service_envelope_error_no_raise():
    """非法入参 → ok=False 显式错误信封（不抛、无部分产出）。"""
    env = svc.circulator_disk_design(10.0e9, 15.0, -1.0, 100.0)
    assert env["ok"] is False and "ms_a_per_m" in env["error"]
    assert env["error_type"] == "ValueError"
    env2 = svc.circulator_disk_design(10.0e9, 15.0, _MS_HALF, _HI_1GHZ, h_sat_a_per_m=1e12)
    assert env2["ok"] is False and "未饱和" in env2["error"]
    json.dumps(env)  # 错误信封同样 JSON 可序列化


def test_service_lumped_and_bandwidth_envelopes():
    """集总 LC 与带宽登记信封：ok=True + UNVERIFIED 透传。"""
    env = svc.circulator_lumped_lc(10.0e-9, 5.0e-12, sense=-1)
    assert env["ok"] is True
    assert env["data"]["lumped_lc"]["sense"] == -1
    assert env["data"]["lumped_lc"]["s_matrix"]["total_energy"] == pytest.approx(3.0, rel=1e-12)
    env_bad = svc.circulator_lumped_lc(0.0, 5.0e-12)
    assert env_bad["ok"] is False
    bw = svc.circulator_bandwidth_reference(3.0e9)
    assert bw["ok"] is True and bw["data"]["bandwidth_reference"]["unverified"]
    json.dumps([env, bw])
