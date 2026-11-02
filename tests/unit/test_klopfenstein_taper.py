"""DP-15 C2 件3：klopfenstein_taper 计算器判据（runs/df6_dp15c2/criteria.md §3）。

文献例 = Pozar §5.9 参数化（50→100Ω、ρ0=0.05）；独立来源交叉验证 = 剖面喂
TEM 级联仿真对拍通带纹波（[0.9, 1.25]×ρ0，下界防恒零退化通过）；端部台阶
实现恒等式与宽度剖面 MLine 同源自洽。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

import skrf

from rfauto.service.calculator_service import run_calculator

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

C0 = 299_792_458.0


def _run(**params):
    out = run_calculator("klopfenstein_taper", {
        "z1_ohm": 50.0, "z2_ohm": 100.0, "length_mm": 100.0,
        "epsilon_r": 3.66, "h_mm": 0.508, "freq_ghz": 2.5, **params})
    assert out["ok"], out
    return out["result"]


def test_pozar_parameterization_identity_and_rl():
    """Pozar 例：Γ0=½ln2、ρ0=0.05 → rmax=0.14427、A 两参数化恒等、RL=26.02dB。"""
    gamma0 = math.log(2.0) / 2.0
    rho0 = 0.05
    rmax = rho0 / gamma0
    out = _run(rmax=rmax)
    assert out["gamma0_step_reflection"] == pytest.approx(gamma0, rel=1e-9)
    assert out["A"] == pytest.approx(math.acosh(gamma0 / rho0), abs=1e-9)
    assert out["A"] == pytest.approx(math.acosh(1.0 / rmax), abs=1e-9)
    assert out["rl_passband_db"] == pytest.approx(
        -20.0 * math.log10(rho0), abs=5e-4)
    assert out["passband_ripple_rho0"] == pytest.approx(rho0, rel=1e-9)


def test_profile_monotonic_and_end_values():
    """剖面单调；末值==z2；端部台阶恒等 z[0]/z1 = exp(Γ0·rmax)。"""
    gamma0 = math.log(2.0) / 2.0
    rmax = 0.05 / gamma0
    out = _run(rmax=rmax, n_sections=81)
    z = np.asarray(out["z_profile_ohm"], dtype=float)
    assert np.all(np.diff(z) > 0), "剖面须单调递增"
    assert z[-1] == 100.0, "末值须精确等于 z2"
    expected_start = 50.0 * math.exp(gamma0 * rmax)
    assert abs(z[0] - expected_start) / expected_start <= 1e-6
    assert out["monotonic"] is True


def test_passband_ripple_simulation_cross_check():
    """独立来源交叉验证：剖面 TEM 级联（DefinedGammaZ0 gamma=ω/c + 匹配
    馈线）在 βL≥A 频段的 max|S11| ∈ [0.9, 1.25]×ρ0（实测触达比 0.9992）。"""
    gamma0 = math.log(2.0) / 2.0
    rho0 = 0.05
    rmax = rho0 / gamma0
    A = math.acosh(1.0 / rmax)
    out = _run(rmax=rmax, n_sections=201, length_mm=200.0)
    z = np.asarray(out["z_profile_ohm"], dtype=float)
    n = z.size
    length_m = 0.2
    freq = skrf.Frequency(0.1, 100.0, 991, "GHz")
    gamma = 1j * 2.0 * np.pi * freq.f / C0

    def media(z0_val: float) -> skrf.media.DefinedGammaZ0:
        return skrf.media.DefinedGammaZ0(
            frequency=freq, z0=z0_val, gamma=gamma)

    net = media(50.0).line(5e-3, unit="m")
    for zk in z:
        # 坑：Media.line 缺省 unit='deg'——不显式传 'm' 会得到零长段级联
        # （实测退化成裸台阶，触达比=6.67），与 skrf.taper.section_at 同款
        net = net ** media(float(zk)).line(length_m / n, unit="m")
    net = net ** media(100.0).line(5e-3, unit="m")
    s11 = np.abs(net.s[:, 0, 0])
    beta_l = 2.0 * np.pi * freq.f * length_m / C0
    mask = beta_l >= A
    assert mask.any()
    ratio = float(s11[mask].max()) / rho0
    assert 0.9 <= ratio <= 1.25, f"通带纹波触达比越界: {ratio:.4f}"


def test_width_profile_mline_self_consistency():
    """宽度剖面回代：MLine(w_k).z0 vs 剖面值 相对差 ≤1e-4（criteria §3）。"""
    out = _run(rmax=0.1, n_sections=41)
    z = np.asarray(out["z_profile_ohm"], dtype=float)
    w_mm = np.asarray(out["width_profile_mm"], dtype=float)
    assert out["z0_width_check_max_rel"] <= 1e-6
    from rfauto.core.calculators import _mline_z0_of_width

    worst = 0.0
    for zk, wk in zip(z, w_mm, strict=True):
        z_back = _mline_z0_of_width(wk * 1e-3, 2.5, 3.66, 0.508, 0.0)
        worst = max(worst, abs(z_back - zk) / zk)
    assert worst <= 1e-4, f"宽度回代偏差 {worst:.2e}"


def test_monotonic_regression_pin_rmax_high():
    """回归钉：rmax=0.9（A<Γ0 区）剖面仍单调（criteria §3 实测两档之一）。"""
    out = _run(z1_ohm=30.0, z2_ohm=90.0, rmax=0.9, n_sections=41,
               length_mm=20.0)
    z = np.asarray(out["z_profile_ohm"], dtype=float)
    assert np.all(np.diff(z) > 0)
    assert out["monotonic"] is True


def test_passband_condition_fields():
    """βL 条件核验字段存在且自洽：passband_ok ⇔ beta_l_design ≥ A。"""
    out = _run(rmax=0.1442697616924321, n_sections=25)
    assert out["passband_ok"] == (
        out["beta_l_design"] >= out["A"])
    short = _run(rmax=0.1442697616924321, n_sections=25, length_mm=1.0)
    assert short["passband_ok"] is False, "1mm 渐变段在 2.5GHz 应落通带外"
    assert short["f_passband_min_ghz_estimate"] > 2.5


def test_domain_errors_are_explicit():
    """显式报错路径：Γ0=0 / rmax 越域 / 超可达域 / 段数下界（G15 同款）。"""
    base = {"z1_ohm": 50.0, "z2_ohm": 90.0, "length_mm": 20.0,
            "epsilon_r": 3.66, "h_mm": 0.508, "freq_ghz": 2.5}
    cases = [
        {"z2_ohm": 50.0},                      # Γ0=0 → RL 无穷
        {"rmax": 1.5},                         # rmax 越域
        {"z2_ohm": 1000.0},                    # 超 MLine 可达域
        {"n_sections": 2},                     # 段数下界
    ]
    for extra in cases:
        out = run_calculator("klopfenstein_taper", {**base, **extra})
        assert out["ok"] is False, f"{extra} 未报错: {out!r}"
        assert out.get("error"), f"{extra} 报错缺 error 字段"
