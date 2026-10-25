"""aurora_d W3-CORE7：制造良率/三角渐变/combline 耦合缝三域单测。

cpk_yield_convert / serial_yield_budget（calc_families/manufacturing_yield.py）/
classic_taper_response+classic_taper_synthesize 三角剖面（calc_families/
taper_classic.py 原位扩展） / combline_coupling_gap（calc_families/
interdigital_bpf.py 第三键）。

裁判口径（#118 双路径：实现路线=各键闭式；独立第二路线=本文件不同算法
重算——实现前独立复算轨迹 runs/aurora_d/_core7_verify_derivation.py，
锚值实现前写死）：

- **cpk↔良率**：Montgomery 表值单尾档逐位（Cpk=1→出界 1349.8980316e-6、
  4/3→Φ(−4)、5/3→Φ(−5)、2→Φ(−6)，scipy norm.sf 独立重算）；两尾精确
  Φ(3Cu)·Φ(3Cl) vs scipy 双侧积分恒等式；仅知 Cpk 的界单调性
  Φ(3Cpk)² ≤ yield ≤ Φ(3Cpk)；反解 roundtrip（scipy ppf 独立重算）。
- **串联良率**：乘积律（math.prod 独立）；Fréchet–Hoeffding 界包含乘积；
  等相关合并 quad vs 本文件 Gauss–Hermite（roots_hermitenorm）第二路线
  ≤1e-9；双极限：ρ=0 逐位退化乘积、ρ=0.9999 逼近 min(y) 1e-9；单工序
  退化恒等。
- **三角渐变**：闭式 Γ=(δ/2)e^{−jx}sinc²(x/2π) vs 本文件 Simpson 剖面核
  积分独立路线 ≤1e-15；首零 βL=2π 精确（exp =0）；βL→0 阶跃极限 |δ|/2；
  包络 |Γ|≤|δ|/2；Z 剖面 F(½)=½ → Z(½)=√(z1z2) 几何中点逐位；剖面反转
  |Γ| 不变；综合 roundtrip（本文件独立稠密二分求根 vs 键 brentq）；指数
  剖面回归（A8-B 原锚不动）。
- **combline 耦合缝**：k roundtrip ≤1e-12；k_exact == J·Z_r/√(1+(J·Z_r)²)
  代数互逆恒等式（scipy 独立重算第二路线）；k 电容/阻抗双表达恒等
  ≤1e-12；跨键结构锚：同 (k,Z_r,b,εr) → 与 interdigital_bpf_synthesize
  内节 (w,s) 逐位（ID_NOM 参数）；k↑ → 缝单调收窄；装载斜率 θ₀→90°
  （C→1e-9 fF）退化 π/(4Z_r) 逐位、θ₀ 与 combline_resonance 跨键同解
  （[cotθ₀+θ₀csc²θ₀]/(2Zr) 本文件独立重算）。
"""

from __future__ import annotations

import math
import sys
import typing
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calc_families.registry import C_MM_GHZ
from rfauto.service.calculator_service import run_calculator

# ─── 独立第二路线算子（实现前复算，不同算法）────────────────────────────────


def _sf3(cpk: float) -> float:
    """单尾出界率 1−Φ(3Cpk)（scipy norm.sf 独立算子）。"""
    from scipy import stats

    return float(stats.norm.sf(3.0 * cpk))


def _simpson_gamma_tri(z1: float, z2: float, x_bl: float,
                       n: int = 200001) -> complex:
    """三角剖面核 Simpson 独立路线：K(u)=(δ/2)·4u（u≤½）/4(1−u)（u≥½）。"""
    from scipy.integrate import simpson

    delta = math.log(z2 / z1)
    u = np.linspace(0.0, 1.0, n)
    kernel = np.where(u <= 0.5, 4.0 * u, 4.0 * (1.0 - u)) * (delta / 2.0)
    return complex(simpson(kernel * np.exp(-2j * x_bl * u), x=u))


def _gamma_tri_closed(z1: float, z2: float, x_bl: float) -> complex:
    """闭式 Γ=(δ/2)e^{−jx}sinc²(x/2π)（本文件独立实现，纯 math）。"""
    delta = math.log(z2 / z1)
    y = x_bl / (2.0 * math.pi)
    s = math.sin(math.pi * y) / (math.pi * y) if y != 0.0 else 1.0
    return (delta / 2.0) * complex(math.cos(-x_bl), math.sin(-x_bl)) * s * s


def _joint_equicorr_gh(yields: list, rho: float,
                       n_nodes: int = 240) -> float:
    """等相关联合良率 Gauss–Hermite 第二路线（vs 键内 scipy.quad）。"""
    from scipy.special import roots_hermitenorm
    from scipy.stats import norm

    ts = norm.ppf(np.asarray(yields, dtype=float))
    xg, wg = roots_hermitenorm(n_nodes)
    arg = (ts[None, :] - math.sqrt(rho) * xg[:, None]) / math.sqrt(1.0 - rho)
    vals = np.exp(np.sum(norm.logcdf(arg), axis=1) + np.log(wg))
    return float(np.sum(vals)) / math.sqrt(2.0 * math.pi)


def _run(name: str, **params: object) -> dict:
    out = run_calculator(name, params)
    assert out["ok"], f"{name} 失败: {out.get('error')!r}"
    return out["result"]


def _fail(name: str, **params: object) -> None:
    out = run_calculator(name, params)
    assert out["ok"] is False and out.get("error"), (
        f"{name}({params}) 应显式拒绝，得到 ok={out.get('ok')!r}")


# ─── cpk_yield_convert ────────────────────────────────────────────────────────


class TestCpkYieldConvert:
    def test_montgomery_table_one_tail(self):
        """Montgomery 表值单尾档：Cpk=1/4:3/5:3/2 → scipy sf 独立重算逐位。"""
        r1 = _run("cpk_yield_convert", cpk=1.0)
        assert r1["defect_frac_one_tail"] == pytest.approx(_sf3(1.0),
                                                           rel=1e-12)
        assert r1["defect_frac_one_tail"] == pytest.approx(1.3498980316300933e-3,
                                                           rel=1e-9)
        assert r1["yield_frac"] == pytest.approx(1.0 - _sf3(1.0), rel=1e-15)
        r2 = _run("cpk_yield_convert", cpk=4.0 / 3.0)
        assert r2["defect_frac_one_tail"] == pytest.approx(_sf3(4.0 / 3.0),
                                                           rel=1e-12)
        r3 = _run("cpk_yield_convert", cpk=5.0 / 3.0)
        assert r3["defect_frac_one_tail"] == pytest.approx(_sf3(5.0 / 3.0),
                                                           rel=1e-12)
        r4 = _run("cpk_yield_convert", cpk=2.0)
        assert r4["defect_frac_one_tail"] == pytest.approx(_sf3(2.0),
                                                           rel=1e-12)
        assert r4["margin_z"] == pytest.approx(6.0, rel=1e-15)

    def test_exact_two_tail_independence_identity(self):
        """两尾精确 Φ(3Cu)·Φ(3Cl) vs scipy 逐尾独立重算；口径不一致拒绝。"""
        cu, cl = 1.5, 1.2
        r = _run("cpk_yield_convert", cpk=min(cu, cl),
                 cpk_upper=cu, cpk_lower=cl)
        expect = (1.0 - _sf3(cu)) * (1.0 - _sf3(cl))
        assert r["yield_frac_exact_two_tail"] == pytest.approx(expect,
                                                               rel=1e-12)
        _fail("cpk_yield_convert", cpk=1.0, cpk_upper=1.5, cpk_lower=1.2)

    def test_bounds_when_only_cpk(self):
        """仅知 Cpk：Φ(3Cpk)² ≤ Y ≤ Φ(3Cpk) 界单调性（本仓推导恒等式）。"""
        r = _run("cpk_yield_convert", cpk=1.0)
        y = r["yield_frac"]
        assert r["yield_frac_lower_bound"] == pytest.approx(y * y, rel=1e-12)
        assert r["yield_frac_lower_bound"] <= y <= r["yield_frac_upper_bound"]

    def test_inverse_roundtrip(self):
        """良率→Cpk 反解 roundtrip（scipy ppf 独立重算，双档）。"""
        y0 = 1.0 - _sf3(1.33)
        r = _run("cpk_yield_convert", yield_frac=y0)
        assert r["cpk"] == pytest.approx(1.33, rel=1e-9)
        from scipy.stats import norm

        y1 = 0.997300203936739
        r2 = _run("cpk_yield_convert", yield_frac=y1,
                  spec_side="two_sided_centered")
        assert r2["cpk"] == pytest.approx(
            float(norm.ppf((1.0 + y1) / 2.0)) / 3.0, rel=1e-12)

    def test_domain_rejects(self):
        _fail("cpk_yield_convert", cpk=1.0, yield_frac=0.99)  # route 同给
        _fail("cpk_yield_convert")  # 全缺
        _fail("cpk_yield_convert", cpk=-0.5)  # 负 Cpk
        _fail("cpk_yield_convert", yield_frac=1.0)  # 开区间上界
        _fail("cpk_yield_convert", yield_frac=0.99, spec_side="median")


# ─── serial_yield_budget ──────────────────────────────────────────────────────


class TestSerialYieldBudget:
    YIELDS: typing.ClassVar[list[float]] = [0.99, 0.98, 0.975]

    def test_product_law_and_frechet(self):
        """乘积律（math.prod 独立）+乘积恒在 Fréchet–Hoeffding 界内。"""
        r = _run("serial_yield_budget", yields=self.YIELDS)
        assert r["yield_independent"] == pytest.approx(
            math.prod(self.YIELDS), rel=1e-15)
        assert r["frechet_lower"] == pytest.approx(
            max(0.0, sum(self.YIELDS) - 2.0), rel=1e-15)
        assert r["frechet_upper"] == pytest.approx(min(self.YIELDS),
                                                   rel=1e-15)
        assert r["frechet_lower"] <= r["yield_independent"] <= r["frechet_upper"]

    def test_equicorrelated_second_route(self):
        """等相关合并 quad vs 本文件 Gauss–Hermite 第二路线 ≤1e-9。"""
        for rho in (0.2, 0.5, 0.8):
            r = _run("serial_yield_budget", yields=self.YIELDS, rho=rho)
            gh = _joint_equicorr_gh(self.YIELDS, rho)
            assert r["yield_correlated"] == pytest.approx(gh, abs=1e-9)
            assert r["frechet_lower"] <= r["yield_correlated"] <= r["frechet_upper"]

    def test_dual_limits_rho(self):
        """双极限：ρ=0 逐位退化乘积；ρ→1⁻ 逼近 min(y)。"""
        r0 = _run("serial_yield_budget", yields=self.YIELDS, rho=0.0)
        assert r0["yield_independent"] == pytest.approx(
            math.prod(self.YIELDS), rel=1e-15)
        assert not hasattr(r0, "yield_correlated") and "yield_correlated" not in r0
        r9 = _run("serial_yield_budget", yields=self.YIELDS, rho=0.9999)
        assert r9["yield_correlated"] == pytest.approx(min(self.YIELDS),
                                                       abs=1e-9)

    def test_single_stage_degenerate(self):
        """单工序退化：乘积/界同值 =y_1。"""
        r = _run("serial_yield_budget", yields=[0.87])
        assert r["yield_independent"] == pytest.approx(0.87, rel=1e-15)
        assert r["frechet_lower"] == pytest.approx(0.87, rel=1e-15)
        assert r["frechet_upper"] == pytest.approx(0.87, rel=1e-15)

    def test_domain_rejects(self):
        _fail("serial_yield_budget", yields=[])
        _fail("serial_yield_budget", yields=[0.99, 1.5])
        _fail("serial_yield_budget", yields=[0.99, 0.0])
        _fail("serial_yield_budget", yields=[0.5] * 65)
        _fail("serial_yield_budget", yields=[0.99], rho=1.0)
        _fail("serial_yield_budget", yields=[0.99], rho=-0.1)


# ─── classic_taper 三角剖面（原位扩展）───────────────────────────────────────


class TestTriangularTaper:
    Z1, Z2, LENGTH = 50.0, 100.0, 30.0

    def test_closed_vs_independent_simpson(self):
        """闭式 sinc² vs 本文件 Simpson 剖面核第二路线 ≤1e-15（多电长度）。"""
        freqs = [1.0, 2.0, 3.3, 7.7]
        r = _run("classic_taper_response", z1_ohm=self.Z1, z2_ohm=self.Z2,
                 length_mm=self.LENGTH, freq_ghz=freqs,
                 profile="triangular")
        assert r["closed_vs_quadrature_max_dev"] < 1e-14
        for f, g_mag in zip(freqs, r["gamma_mag"], strict=True):
            x_bl = 2.0 * math.pi * f * self.LENGTH / C_MM_GHZ
            g_ref = _gamma_tri_closed(self.Z1, self.Z2, x_bl)
            assert g_mag == pytest.approx(abs(g_ref), rel=1e-12)
            g_simp = _simpson_gamma_tri(self.Z1, self.Z2, x_bl)
            assert abs(g_ref - g_simp) < 1e-15

    def test_first_null_at_2pi_and_step_limit(self):
        """首零 βL=2π 精确（f=c/L）与 βL→0 阶跃极限 |δ|/2。"""
        f_null = C_MM_GHZ / self.LENGTH  # βL=2π ⇔ f·L/c=1
        r = _run("classic_taper_response", z1_ohm=self.Z1, z2_ohm=self.Z2,
                 length_mm=self.LENGTH, freq_ghz=[f_null],
                 profile="triangular")
        assert r["gamma_mag"][0] < 1e-18
        r_lo = _run("classic_taper_response", z1_ohm=self.Z1, z2_ohm=self.Z2,
                    length_mm=self.LENGTH,
                    freq_ghz=[0.005 * C_MM_GHZ / self.LENGTH],
                    profile="triangular")
        step = abs(math.log(self.Z2 / self.Z1)) / 2.0
        assert r_lo["gamma_mag"][0] == pytest.approx(step, rel=2e-3)
        assert r_lo["gamma_mag"][0] <= step * (1.0 + 1e-12)
        assert r_lo["envelope_bound_ok"] is True

    def test_z_profile_geometric_midpoint(self):
        """剖面 F(½)=½ → Z(½)=√(z1z2) 几何中点逐位（本仓闭式推导锚）。"""
        r = _run("classic_taper_response", z1_ohm=self.Z1, z2_ohm=self.Z2,
                 length_mm=self.LENGTH, freq_ghz=[1.0],
                 profile="triangular", n_profile=65)
        assert r["z_profile_ohm"][0] == pytest.approx(self.Z1, rel=1e-12)
        assert r["z_profile_ohm"][-1] == pytest.approx(self.Z2, rel=1e-12)
        mid = r["z_profile_ohm"][32]  # 65 点的第 32 索引恰为 u=0.5
        assert mid == pytest.approx(math.sqrt(self.Z1 * self.Z2), rel=1e-9)

    def test_profile_reversal_symmetry(self):
        """剖面反转（z1↔z2）|Γ| 不变（|Γ| 只依赖 |δ|）。"""
        f = [1.0, 3.0, 7.0]
        r1 = _run("classic_taper_response", z1_ohm=self.Z1, z2_ohm=self.Z2,
                  length_mm=self.LENGTH, freq_ghz=f, profile="triangular")
        r2 = _run("classic_taper_response", z1_ohm=self.Z2, z2_ohm=self.Z1,
                  length_mm=self.LENGTH, freq_ghz=f, profile="triangular")
        assert r1["gamma_mag"] == pytest.approx(r2["gamma_mag"], rel=1e-12)

    def test_synthesize_roundtrip_and_monotonic_band(self):
        """综合 roundtrip：键 brentq 根 vs 本文件独立稠密扫描求根；通带内
        |Γ| 单调 ≤ρ（βL∈[x*,2π)）。"""
        rho = 0.05
        s = _run("classic_taper_synthesize", z1_ohm=self.Z1, z2_ohm=self.Z2,
                 f_min_ghz=2.0, rho_max=rho, profile="triangular")
        assert s["achieved_residual"] < 1e-12
        # 独立第二路线：sinc² 标量方程稠密网格首个变号
        step = abs(math.log(self.Z2 / self.Z1)) / 2.0
        xs = np.linspace(1e-9, 2.0 * math.pi, 200001)
        gs = np.array([abs(_gamma_tri_closed(self.Z1, self.Z2, float(x)))
                       - rho for x in xs])
        idx = int(np.argmax(gs <= 0.0))
        from scipy.optimize import brentq as _bq
        x_ref = float(_bq(
            lambda x_: abs(_gamma_tri_closed(self.Z1, self.Z2, float(x_)))
            - rho, float(xs[idx - 1]), float(xs[idx]), xtol=1e-12))
        assert s["beta_l_at_f_min"] == pytest.approx(x_ref, abs=1e-9)
        # 通带保证域内 |Γ| 单调不超 ρ
        for frac in (1.2, 1.7, 1.999):
            g = abs(_gamma_tri_closed(self.Z1, self.Z2,
                                      s["beta_l_at_f_min"] * frac))
            assert g <= rho * (1.0 + 1e-9)
        assert step > rho

    def test_exponential_regression_unchanged(self):
        """A8-B 指数剖面原锚回归（扩展不破坏既有档）。"""
        r = _run("classic_taper_response", z1_ohm=self.Z1, z2_ohm=self.Z2,
                 length_mm=self.LENGTH, freq_ghz=[2.0],
                 profile="exponential")
        assert r["closed_vs_quadrature_max_dev"] < 1e-14
        assert r["gamma_mag"][0] > 0.0
        _fail("classic_taper_response", z1_ohm=self.Z1, z2_ohm=self.Z2,
              length_mm=self.LENGTH, freq_ghz=[1.0], profile="bogus")


# ─── combline_coupling_gap ────────────────────────────────────────────────────

_ID_NOM = dict(order=3, f0_ghz=2.5, fbw=0.08, ripple_db=0.5, b_mm=2.0,
               epsilon_r=2.2)


class TestComblineCouplingGap:
    def test_roundtrip_and_algebraic_identity(self):
        """k roundtrip ≤1e-12；k_exact==J·Z_r/√(1+(J·Z_r)²) 代数互逆第二路线。"""
        for k_in in (0.005, 0.02, 0.05, 0.1):
            r = _run("combline_coupling_gap", k_coupling=k_in, z_r_ohm=70.0,
                     b_mm=6.0, epsilon_r=2.2)
            assert r["k_roundtrip_abs_dev"] < 1e-12
            jz = r["j_realized_s"] * 70.0
            expect = jz / math.sqrt(1.0 + jz * jz)
            assert r["k_exact_phys"] == pytest.approx(expect, rel=1e-10)
            assert r["k_impedance_identity_dev"] < 1e-12

    def test_cross_key_structural_anchor(self):
        """跨键结构锚：同 (k,Z_r,b,εr) 内节对 → 与 interdigital_bpf_
        synthesize 对应节 (w,s) 逐位（截面同源，ID_NOM 参数）。"""
        full = _run("interdigital_bpf_synthesize", **_ID_NOM)
        k1 = full["k_interior_norm"][0]
        pair = _run("combline_coupling_gap", k_coupling=k1, z_r_ohm=50.0,
                    b_mm=2.0, epsilon_r=2.2)
        assert pair["w_mm"] == pytest.approx(full["w_mm"][1], abs=5e-7)
        assert pair["gap_mm"] == pytest.approx(full["s_mm"][1], abs=5e-7)
        assert pair["j_target_s"] == pytest.approx(full["j_targets_s"][1],
                                                   rel=1e-9)

    def test_monotonic_gap_vs_k(self):
        """k↑ → 缝单调收窄（同 Z_r/b/εr）。"""
        gaps = [_run("combline_coupling_gap", k_coupling=k, z_r_ohm=70.0,
                     b_mm=6.0, epsilon_r=2.2)["gap_mm"]
                for k in (0.01, 0.03, 0.08)]
        assert gaps[0] > gaps[1] > gaps[2]

    def test_loaded_slope_limit_and_cross_key_theta0(self):
        """装载斜率：θ₀→90°（C→1e-9 fF）退化 π/(4Z_r) 逐位；θ₀ 与
        combline_resonance 跨键同解（斜率式本文件独立重算）。"""
        r_lo = _run("combline_coupling_gap", k_coupling=0.05, z_r_ohm=80.0,
                    b_mm=6.0, epsilon_r=1.0, cap_ff=1e-9, f0_ghz=2.0)
        r_un = _run("combline_coupling_gap", k_coupling=0.05, z_r_ohm=80.0,
                    b_mm=6.0, epsilon_r=1.0)
        assert r_lo["slope_mode"] == "loaded_combline"
        assert r_un["b_slope_per_ohm"] == pytest.approx(
            math.pi / (4.0 * 80.0), rel=1e-15)
        assert r_lo["b_slope_per_ohm"] == pytest.approx(
            r_un["b_slope_per_ohm"], rel=1e-6)
        # 跨键：combline_resonance 的 θ₀ 同解（同 C=1 fF）
        cr = _run("combline_resonance", zr_ohm=80.0, cap_ff=1.0, f0_ghz=2.0,
                  epsilon_r=1.0)
        theta0 = math.radians(cr["theta_deg"])
        slope_ref = (1.0 / math.tan(theta0)
                     + theta0 / math.sin(theta0) ** 2) / (2.0 * 80.0)
        r_ld = _run("combline_coupling_gap", k_coupling=0.05, z_r_ohm=80.0,
                    b_mm=6.0, epsilon_r=1.0, cap_ff=1.0, f0_ghz=2.0)
        assert r_ld["theta0_deg"] == pytest.approx(cr["theta_deg"],
                                                   rel=1e-9)
        assert r_ld["b_slope_per_ohm"] == pytest.approx(slope_ref, rel=1e-12)
        # 杆长与 θ₀ 同源自洽：l=θ₀·c0/(2π f0 √εr)（键输出 6 位小数舍入）
        rod_ref = theta0 * C_MM_GHZ / (2.0 * math.pi * 2.0)
        assert r_ld["rod_len_mm"] == pytest.approx(rod_ref, abs=1e-6)

    def test_domain_rejects(self):
        _fail("combline_coupling_gap", k_coupling=0.0, z_r_ohm=70.0,
              b_mm=6.0, epsilon_r=2.2)
        _fail("combline_coupling_gap", k_coupling=1.0, z_r_ohm=70.0,
              b_mm=6.0, epsilon_r=2.2)
        _fail("combline_coupling_gap", k_coupling=0.05, z_r_ohm=0.5,
              b_mm=6.0, epsilon_r=2.2)  # Z_r 过低 → C_e 目标超几何可达上界
        _fail("combline_coupling_gap", k_coupling=0.05, z_r_ohm=70.0,
              b_mm=6.0, epsilon_r=2.2, cap_ff=1000.0)  # cap 单给
        _fail("combline_coupling_gap", k_coupling=0.05, z_r_ohm=70.0,
              b_mm=6.0, epsilon_r=2.2, f0_ghz=2.0)  # f0 单给

    def test_ultra_weak_coupling_still_in_domain(self):
        """极弱耦合（k≤1e-6）在 12b 缝上限内仍可解（所需 ΔC 高于 tanh 饱
        和阈分辨率）——如实可解非越域；弱侧真越域由参数组合触发（h_a 判据
        在档）。"""
        r = _run("combline_coupling_gap", k_coupling=1e-6, z_r_ohm=70.0,
                 b_mm=6.0, epsilon_r=2.2)
        assert r["gap_mm"] <= 12.0 * 6.0
        assert r["k_roundtrip_abs_dev"] < 1e-9
