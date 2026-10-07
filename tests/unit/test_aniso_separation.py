"""MA-6 各向异性分离测试（锚树预声明，#122 判据先行）。

每件 ≥2 独立基准（出处见 core/aniso_separation.py 模块 docstring）：

- 平行板 ε_z：① 合成回收（正算→反演逐位回收，≤1e-12）；② 手算锚
  （ε=4、A=1e-4、t=100 µm → C=ε0·4·1e-4/1e-4 F 数值核对）。
- Wiener 界（严格定理面）：① 排序恒等（调和 ≤ 算术，任意 p_z）；
  ② 各向同性退化坍缩（ε_z=ε_xy → 两界同值逐位）；③ p_z=0/1 端点
  退化为纯 ε_xy/ε_z（构造恒等）。
- 微带反演（声明式串联模型）：① round-trip 恒等（mix→separate 逐位）；
  ② 手算回收锚（ε_z=4.4、p_z=0.7、ε_eff=4.0 → ε_xy 手算值）；
  ③ 不相容声明守卫（分母≤0、ε_xy<1）。
- 各向同性等效 Design-Dk 锚（synthesis 禁改消费）：① 合成回收——
  已知各向同性板 εr=4.3 的 HJ εeff 正算 → 反演回收 4.3（≤1e-6）；
  ② 括号失败守卫。
- 各向异性报告：比值/等向性判定两态 + tol 守卫。
"""

from __future__ import annotations

import pytest

from rfauto.core.aniso_separation import (
    EPS0_F_PER_M,
    anisotropy_report,
    isotropic_equiv_from_microstrip,
    parallel_mix_eps_eff,
    parallel_plate_capacitance_f,
    parallel_plate_eps_z,
    separate_eps_xy_from_microstrip,
    series_mix_eps_eff,
    stripline_eps_xy_from_eff,
    wiener_bounds,
)

_A_M2 = 1.0e-4
_T_M = 100.0e-6


# ─── 平行板 ε_z（严格面）─────────────────────────────────────────────────────


def test_parallel_plate_roundtrip_synthetic() -> None:
    c = parallel_plate_capacitance_f(4.0, _A_M2, _T_M)
    assert c == pytest.approx(EPS0_F_PER_M * 4.0 * _A_M2 / _T_M, rel=1e-15)
    assert parallel_plate_eps_z(c, _A_M2, _T_M) == pytest.approx(4.0, rel=1e-12)


def test_stripline_sensing_identity() -> None:
    # 全嵌入带线感测映射=定义恒等（结构严格+边缘场声明）
    assert stripline_eps_xy_from_eff(4.25) == 4.25


# ─── Wiener 界（严格定理面）──────────────────────────────────────────────────


def test_wiener_bounds_ordering_and_collapse() -> None:
    for p in (0.0, 0.25, 0.5, 0.7, 1.0):
        b = wiener_bounds(4.4, 4.0, p)
        assert b["harmonic_lower"] <= b["arithmetic_upper"] + 1e-15
    # 各向同性退化：两界同值逐位
    b = wiener_bounds(4.2, 4.2, 0.37)
    assert b["harmonic_lower"] == pytest.approx(4.2, rel=1e-15)
    assert b["arithmetic_upper"] == pytest.approx(4.2, rel=1e-15)
    # 端点退化：p_z=0 → 纯 ε_xy；p_z=1 → 纯 ε_z
    assert series_mix_eps_eff(4.4, 4.0, 0.0) == pytest.approx(4.0, rel=1e-15)
    assert parallel_mix_eps_eff(4.4, 4.0, 0.0) == pytest.approx(4.0, rel=1e-15)
    assert series_mix_eps_eff(4.4, 4.0, 1.0) == pytest.approx(4.4, rel=1e-15)
    assert parallel_mix_eps_eff(4.4, 4.0, 1.0) == pytest.approx(4.4, rel=1e-15)


def test_mix_monotonic_in_eps_xy_and_guards() -> None:
    assert series_mix_eps_eff(4.4, 4.0, 0.5) < series_mix_eps_eff(4.4, 4.2, 0.5)
    assert parallel_mix_eps_eff(4.4, 4.0, 0.5) < parallel_mix_eps_eff(4.4, 4.2, 0.5)
    with pytest.raises(ValueError):
        series_mix_eps_eff(4.4, 4.0, 1.5)
    with pytest.raises(ValueError):
        parallel_mix_eps_eff(0.5, 4.0, 0.5)  # εr<1 守卫


# ─── 微带反演（声明式模型）───────────────────────────────────────────────────


def test_separate_roundtrip_and_recall() -> None:
    ez, p = 4.4, 0.7
    eff = series_mix_eps_eff(ez, 4.0, p)
    out = separate_eps_xy_from_microstrip(eff, ez, p)
    assert out["eps_xy"] == pytest.approx(4.0, rel=1e-12)
    assert out["anisotropy_ratio"] == pytest.approx(4.0 / ez, rel=1e-12)
    # 手算回收锚：1/4.0 = 0.7/4.4 + 0.3/ε_xy → ε_xy = 0.3/(0.25−0.15909)
    hand = 0.3 / (1.0 / 4.0 - 0.7 / 4.4)
    assert separate_eps_xy_from_microstrip(4.0, ez, p)["eps_xy"] == pytest.approx(
        hand, rel=1e-15)
    # 不相容声明守卫：p_z=0.9/ε_z=4.4 → p_z/ε_z=0.2045 > 1/6=0.1667
    with pytest.raises(ValueError, match="模型域外"):
        separate_eps_xy_from_microstrip(6.0, 4.4, 0.9)
    with pytest.raises(ValueError, match="非物理"):
        separate_eps_xy_from_microstrip(1.0 + 1e-6, 4.4, 0.999999)


# ─── 各向同性等效 Design-Dk 锚（synthesis 禁改消费）─────────────────────────


def test_iso_equiv_design_dk_roundtrip() -> None:
    from rfauto.core.synthesis import Stackup, forward_z0
    stackup = Stackup(name="aniso_test", epsilon_r=4.3, thickness_mm=0.2,
                      loss_tangent=0.0, rho=1.68e-8, rough_mm=0.0)
    _, eff = forward_z0(0.4, 10.0, stackup)
    out = isotropic_equiv_from_microstrip(eff, 0.4, 10.0, 0.2)
    assert out["eps_iso_equiv_design_dk"] == pytest.approx(4.3, rel=1e-6)
    # 物理向 sanity：宽线（w/h 大）εeff→εr，回收锚更贴近 4.3
    _, eff_wide = forward_z0(2.0, 10.0, stackup)
    out_wide = isotropic_equiv_from_microstrip(eff_wide, 2.0, 10.0, 0.2)
    assert out_wide["eps_iso_equiv_design_dk"] == pytest.approx(4.3, rel=1e-6)
    assert abs(eff_wide - 4.3) < abs(eff - 4.3)
    assert "not equal to eps_xy" in out["note"]


# ─── 报告面 ──────────────────────────────────────────────────────────────────


def test_anisotropy_report_verdicts() -> None:
    iso = anisotropy_report(4.3, 4.3)
    assert iso["isotropic"] is True
    assert iso["higher_axis"] is None
    an = anisotropy_report(4.6, 4.2, isotropy_tol=0.02)
    assert an["isotropic"] is False
    assert an["higher_axis"] == "z"
    assert an["ratio_xy_over_z"] == pytest.approx(4.2 / 4.6, rel=1e-15)
    with pytest.raises(ValueError):
        anisotropy_report(4.3, 4.3, isotropy_tol=-0.1)
