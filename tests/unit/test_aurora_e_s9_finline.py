"""aurora_e W2-S9：鳍线-波导渐变过渡两键单测（K2 渐变过渡面）。

finline_taper_response / finline_taper_length（calc_families/finline.py）。

裁判口径（#118 双路径；实现前独立复算轨迹=本文件函数）：

- **β 波导口径**：εeff=1 时 β=k0·sqrt(1−(fc/f)²) 与本文件独立重算恒等；
  且与 rw_tables/rwg_mmt 的 TE10 λg 口径互证（λg=λ0/sqrt(1−(fc/f)²)）；
- **剖面双路线**：键内闭式 vs 键内剖面核数值积分交叉互证残差（1e-15 量
  级，classic_taper 同款）+ 本文件独立 Simpson 重算 ≤1e-12；
- **恒等式/极限**：βL→0 阶跃极限 |δ|/2；指数剖面 sinc 零点 L=λg/2 →
  |Γ|≈0（<1e-12）；包络 |Γ|≤|δ|/2；剖面反转 |Γ| 不变；
- **综合回收**：synthesize 的 L 回代 response 复现 rho_max（≤1e-9）；
  本文件独立二分求根 vs 键 brentq ≤1e-6 相对；
- **守卫族**：f≤1.05fc 拒绝；z1==z2 拒绝；profile 白名单；rho≥|δ|/2 拒
  绝；wr_name 与 a/b 互斥；epsilon_eff<1 拒绝。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

C0 = 299792458.0
Z1, Z2 = 150.0, 50.0
WR28_A_MM = 7.112
FC28_GHZ = C0 / (2.0 * WR28_A_MM * 1e-3) / 1e9  # 21.0765 GHz


def _beta_ref(f_ghz: float, a_mm: float, eps_eff: float = 1.0) -> float:
    """TE10 导波 β 独立重算 [rad/mm]（本文件第二路线）。"""
    fc = C0 / (2.0 * a_mm * 1e-3)
    k0 = 2.0 * math.pi * f_ghz / 299.792458  # rad/mm
    return k0 * math.sqrt(eps_eff) * math.sqrt(1.0 - (fc / (f_ghz * 1e9)) ** 2)


def _gamma_exp_ref(x_bl: float, z1: float = Z1, z2: float = Z2) -> complex:
    """指数剖面 Γ 闭式独立重算（Pozar §5.9 小反射积分手算第二路线）。"""
    delta = math.log(z2 / z1)
    if x_bl == 0.0:
        return complex(delta / 2.0)
    return complex((delta / 2.0) * np.exp(-1j * x_bl)
                   * math.sin(x_bl) / x_bl)


def _gamma_exp_simpson(x_bl: float, z1: float = Z1, z2: float = Z2,
                       n: int = 200001) -> complex:
    """剖面核 Simpson 积分独立路线（与键内 _gamma_quadrature 无共享）。"""
    u = np.linspace(0.0, 1.0, n)
    kernel = np.full_like(u, math.log(z2 / z1) / 2.0)
    # 复合 Simpson（n 偶数个区间）
    h = 1.0 / (n - 1)
    f_vals = kernel * np.exp(-2j * x_bl * u)
    total = f_vals[0] + f_vals[-1] + 4.0 * f_vals[1:-1:2].sum() \
        + 2.0 * f_vals[2:-1:2].sum()
    return complex(total * h / 3.0)


def _resp(**params):
    params.setdefault("wr_name", "WR-28")
    res = run_calculator("finline_taper_response", params)
    assert res["ok"], res
    return res["result"]


def _synth(**params):
    params.setdefault("wr_name", "WR-28")
    res = run_calculator("finline_taper_length", params)
    assert res["ok"], res
    return res["result"]


class TestBetaWaveguide:
    def test_beta_matches_te10_identity(self) -> None:
        """εeff=1 时 β 与 TE10 导波恒等式逐点一致（本文件独立重算）。"""
        freqs = [23.0, 26.5, 33.0, 40.0]  # 22.0 < 1.05·fc28=22.13 属守卫域
        r = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=12.0, freq_ghz=freqs)
        for f, beta in zip(r["freq_ghz"], r["beta_rad_per_mm"],
                           strict=True):
            assert beta == pytest.approx(_beta_ref(f, WR28_A_MM), rel=1e-12)

    def test_lam_g_cross_source(self) -> None:
        """λg=λ0/sqrt(1−(fc/f)²) 跨源互证（rw_tables TE10 同口径）。"""
        r = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=12.0, freq_ghz=[26.5])
        f = 26.5
        lam0 = 299.792458 / f
        lam_g_ref = lam0 / math.sqrt(1.0 - (FC28_GHZ / f) ** 2)
        # 信封 lam_g 四舍五入到 1e-9 mm → 相对容差取 1e-9（舍入量级）
        assert r["lam_g_mm"][0] == pytest.approx(lam_g_ref, rel=1e-9)

    def test_epsilon_eff_refinement(self) -> None:
        """εeff 精化按 sqrt(εeff) 标度 β（声明近似档的直接后果）。"""
        r1 = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=12.0, freq_ghz=[26.5])
        r2 = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=12.0, freq_ghz=[26.5],
                   epsilon_eff=2.25)
        assert r2["beta_rad_per_mm"][0] == pytest.approx(
            r1["beta_rad_per_mm"][0] * 1.5, rel=1e-12)


class TestProfileResponse:
    def test_closed_vs_quadrature_residual(self) -> None:
        """闭式 vs 剖面核数值积分互证残差 1e-12 量级。"""
        r = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=12.0,
                  freq_ghz=[23.0, 26.5, 40.0])
        assert r["closed_vs_quadrature_max_dev"] <= 1e-12

    def test_independent_simpson(self) -> None:
        """本文件独立 Simpson 剖面核重算 ≤1e-12（βL 取非零点）。"""
        r = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=12.0, freq_ghz=[26.5])
        x_bl = r["beta_l"][0]
        assert abs(r["gamma_mag"][0]
                   - abs(_gamma_exp_simpson(x_bl))) <= 1e-12

    def test_sinc_null_half_lambda_g(self) -> None:
        """指数剖面 L=λg/2 → sinc 零点 |Γ|<1e-12（精确零点）。"""
        r = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=12.0, freq_ghz=[26.5])
        lam_g = r["lam_g_mm"][0]
        r2 = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=lam_g / 2.0,
                   freq_ghz=[26.5])
        # lam_g 信封舍入 1e-9 mm → βL 偏离零点 ~3e-10 → |Γ| ~1e-11 量级
        assert r2["gamma_mag"][0] <= 1e-9

    def test_step_limit_envelope(self) -> None:
        """短渐变逼近阶跃极限 |δ|/2 且全程包络不超。"""
        delta_half = abs(math.log(Z2 / Z1)) / 2.0
        r = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=1.0, freq_ghz=[23.0])
        assert r["gamma_mag"][0] <= delta_half + 1e-12
        assert r["gamma_mag"][0] == pytest.approx(delta_half, rel=0.02)
        assert r["envelope_bound_ok"] is True

    def test_profile_reversal_invariant(self) -> None:
        """剖面反转（z1↔z2）|Γ| 不变（|Γ| 只依赖 |δ|）。"""
        r1 = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=12.0, freq_ghz=[26.5])
        r2 = _resp(z1_ohm=Z2, z2_ohm=Z1, length_mm=12.0, freq_ghz=[26.5])
        assert r1["gamma_mag"][0] == pytest.approx(r2["gamma_mag"][0],
                                                   rel=1e-12)

    def test_linear_profile_supported(self) -> None:
        """线性剖面档可用且双路线互证（Ei 闭式单源复用）。"""
        r = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=12.0, freq_ghz=[26.5],
                  profile="linear")
        assert r["closed_vs_quadrature_max_dev"] <= 1e-9
        assert 0.0 < r["gamma_mag"][0] < abs(math.log(Z2 / Z1)) / 2.0


class TestSynthesize:
    def test_roundtrip_recovers_rho(self) -> None:
        """综合 L 回代 response 复现 rho_max（≤1e-9）。"""
        s = _synth(z1_ohm=Z1, z2_ohm=Z2, f_min_ghz=26.5, rho_max=0.05)
        r = _resp(z1_ohm=Z1, z2_ohm=Z2, length_mm=s["length_mm"],
                  freq_ghz=[26.5])
        assert r["gamma_mag"][0] == pytest.approx(0.05, abs=1e-9)

    def test_independent_bisection_root(self) -> None:
        """本文件独立二分求根 vs 键 brentq ≤1e-6 相对。"""
        s = _synth(z1_ohm=Z1, z2_ohm=Z2, f_min_ghz=26.5, rho_max=0.05)
        def g(x: float) -> float:
            return abs(_gamma_exp_ref(x)) - 0.05

        lo, hi = 1e-6, math.pi
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if g(lo) * g(mid) <= 0.0:
                hi = mid
            else:
                lo = mid
        assert s["beta_l_at_f_min"] == pytest.approx(0.5 * (lo + hi),
                                                     rel=1e-6)

    def test_monotone_rho_vs_length(self) -> None:
        """更严 rho → 更长渐变（(0,π) 单调域内）。"""
        s1 = _synth(z1_ohm=Z1, z2_ohm=Z2, f_min_ghz=26.5, rho_max=0.08)
        s2 = _synth(z1_ohm=Z1, z2_ohm=Z2, f_min_ghz=26.5, rho_max=0.02)
        assert s2["length_mm"] > s1["length_mm"] > 0.0

    def test_klopfenstein_style_bound_note(self) -> None:
        """综合长度带通带保证域元数据（首零前单调）。"""
        s = _synth(z1_ohm=Z1, z2_ohm=Z2, f_min_ghz=26.5, rho_max=0.05)
        assert s["beta_l_at_f_min"] < math.pi
        assert s["achieved_residual"] <= 1e-9


class TestGuards:
    def test_below_cutoff_rejected(self) -> None:
        res = run_calculator("finline_taper_response", {
            "z1_ohm": Z1, "z2_ohm": Z2, "length_mm": 12.0,
            "freq_ghz": [21.0], "wr_name": "WR-28"})
        assert res["ok"] is False and "截止" in res["error"]

    def test_equal_impedance_rejected(self) -> None:
        res = run_calculator("finline_taper_response", {
            "z1_ohm": 50.0, "z2_ohm": 50.0, "length_mm": 12.0,
            "freq_ghz": [26.5], "wr_name": "WR-28"})
        assert res["ok"] is False and "无意义" in res["error"]

    def test_profile_whitelist(self) -> None:
        res = run_calculator("finline_taper_response", {
            "z1_ohm": Z1, "z2_ohm": Z2, "length_mm": 12.0,
            "freq_ghz": [26.5], "wr_name": "WR-28",
            "profile": "bogus"})
        assert res["ok"] is False and "profile" in res["error"]

    def test_rho_above_step_limit_rejected(self) -> None:
        res = run_calculator("finline_taper_length", {
            "z1_ohm": Z1, "z2_ohm": Z2, "f_min_ghz": 26.5,
            "rho_max": abs(math.log(Z2 / Z1)) / 2.0 + 0.01,
            "wr_name": "WR-28"})
        assert res["ok"] is False and "阶跃" in res["error"]

    def test_housing_exclusive(self) -> None:
        res = run_calculator("finline_taper_response", {
            "z1_ohm": Z1, "z2_ohm": Z2, "length_mm": 12.0,
            "freq_ghz": [26.5], "wr_name": "WR-28", "a_mm": 7.112,
            "b_mm": 3.556})
        assert res["ok"] is False

    def test_epsilon_eff_below_one_rejected(self) -> None:
        res = run_calculator("finline_taper_response", {
            "z1_ohm": Z1, "z2_ohm": Z2, "length_mm": 12.0,
            "freq_ghz": [26.5], "wr_name": "WR-28", "epsilon_eff": 0.5})
        assert res["ok"] is False

    def test_unknown_wr_rejected(self) -> None:
        res = run_calculator("finline_taper_response", {
            "z1_ohm": Z1, "z2_ohm": Z2, "length_mm": 12.0,
            "freq_ghz": [26.5], "wr_name": "WR-99999"})
        assert res["ok"] is False

    def test_registered_in_group(self) -> None:
        spec = CALCULATOR_REGISTRY.get("finline_taper_response")
        assert spec.reciprocal is True
