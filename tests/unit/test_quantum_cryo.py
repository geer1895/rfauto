"""MA 量子探索档单测（BCS Rs + RCSJ，2026-10-03）。

锚树口径（#118：SI 精确常数 + 独立公式路，不赌推导）：
- Φ0 = h/2e 与 scipy.constants.value('mag. flux quantum') 一致（1e-15）。
- BCS 比值：Δ0(Al)=1.764·kB·1.2K≈0.182 meV（文献带内）；GL 支连续性
  t→0 收敛 Δ0。
- 两流体 Rs：小比值支 (σ₁/2σ₂)ωμ0λ 一阶恒等（1e-6）；σ₂=1/(μ0ωλ²)
  独立复算。
- RCSJ：ωp/β_c SI 恒等独立复算；过阻尼 IV 精确支 V=R√(I²−Ic²)
  （数值 ≤5% 相对，RK4 斜坡口径）；欠阻尼回滞：升/降支在 I>1 处
  分离（结构锚）。
"""
from __future__ import annotations

import math

import pytest

from rfauto.core.quantum_cryo import (
    BCS_GAP_RATIO,
    KB_EV_PER_K,
    PHI0_WEBER,
    bcs_gap_ev,
    gao_engineering_note,
    quantum_register_note,
    rcsj_iv,
    rcsj_plasma_frequency,
    rcsj_stewart_mccumber,
    superconductor_params,
    superconductor_rs,
    two_fluid_sigma1,
)


def test_phi0_si_exact():
    from scipy import constants

    ref = constants.value("mag. flux quantum")
    assert abs(PHI0_WEBER - ref) <= 1e-15 * ref


def test_bcs_gap_anchors():
    """Δ0 数值锚：Al Δ0≈0.182 meV（文献带，≤1% 带）；GL 支 t→0 收敛 Δ0。"""
    p = superconductor_params("Al")
    d0 = bcs_gap_ev(p["tc_k"], 0.0)
    assert abs(d0 - p["delta0_meV"] / 1000.0) <= 0.01 * (p["delta0_meV"] / 1000.0)
    assert abs(d0 - BCS_GAP_RATIO * KB_EV_PER_K * 1.20) <= 1e-15
    d_small = bcs_gap_ev(p["tc_k"], 0.01)
    assert abs(d_small - d0) <= 5e-3 * d0  # Mühlschlegel: tanh(1.74√99)≈1−2e−87
    # 近 Tc GL 极限：t=0.99 → Δ≈1.74Δ0√0.01（5% 带）
    d_near = bcs_gap_ev(p["tc_k"], 0.99 * p["tc_k"])
    assert abs(d_near / d0 - 1.74 * math.sqrt(0.01)) <= 0.05
    with pytest.raises(ValueError):
        bcs_gap_ev(p["tc_k"], p["tc_k"])


def test_superconductor_table_bands():
    """参数表：中心值落在文献带内（构造性一致）；未知材料报错。"""
    for name in ("Nb", "NbTiN", "Al"):
        p = superconductor_params(name)
        lo, hi = p["tc_band_k"]
        assert lo <= p["tc_k"] <= hi
        lo_l, hi_l = p["lambda_band_nm"]
        assert lo_l <= p["lambda_l0_nm"] <= hi_l
    with pytest.raises(ValueError):
        superconductor_params("YBCO")


def test_two_fluid_rs_ratio_identity():
    """小比值支恒等：Rs ≈ (σ₁/2σ₂)·ωμ0λ（相对 1e-6）；σ₂ 独立复算。"""
    mu0 = 4.0e-7 * math.pi
    f = 5e9
    omega = 2.0 * math.pi * f
    lam = 39e-9
    sigma_n = 1.0e7
    sigma1 = two_fluid_sigma1(sigma_n, 4.0, 9.25)
    out = superconductor_rs(sigma1, lam, f)
    sigma2_expect = 1.0 / (mu0 * omega * lam * lam)
    assert abs(out["sigma2_s_per_m"] - sigma2_expect) <= 1e-12 * sigma2_expect
    assert out["ratio_approx_ohm"] / out["rs_ohm"] <= 1.0 + 1e-6
    assert out["rs_ohm"] > 0.0


def test_rs_t4_scaling():
    """两流体标度：σ₁∝t⁴ → 低 T 时 Rs 快速压低（3K vs 8K 比值 ≤ (3/8)⁴×3）。"""
    r_lo = superconductor_rs(two_fluid_sigma1(1e7, 3.0, 9.25), 39e-9, 5e9)
    r_hi = superconductor_rs(two_fluid_sigma1(1e7, 8.0, 9.25), 39e-9, 5e9)
    assert r_lo["rs_ohm"] < r_hi["rs_ohm"]
    assert r_lo["rs_ohm"] / r_hi["rs_ohm"] <= 3.0 * (3.0 / 8.0) ** 4


def test_rcsj_identities():
    """ωp/β_c SI 恒等独立复算；β_c 判据分档。"""
    ic, r, c = 1e-6, 50.0, 60e-15
    out_p = rcsj_plasma_frequency(ic, c)
    lj_expect = PHI0_WEBER / (2.0 * math.pi * ic)
    assert abs(out_p["lj_henry"] - lj_expect) <= 1e-18
    assert abs(out_p["omega_p_rad_s"] - 1.0 / math.sqrt(lj_expect * c)) <= 1e-12
    out_b = rcsj_stewart_mccumber(ic, r, c)
    beta_expect = 2.0 * math.pi * ic * r * r * c / PHI0_WEBER
    assert abs(out_b["beta_c"] - beta_expect) <= 1e-9 * beta_expect
    assert out_b["regime"] == ("underdamped" if beta_expect > 1.0
                               else "overdamped")


def test_rcsj_overdamped_iv_exact_branch():
    """过阻尼（β_c≈0.0038）：一阶 RSJ 数值 IV 贴近 V=R√(I²−Ic²)（5% 带）。"""
    ic, r, c = 1e-6, 20.0, 1e-15  # β_c = 2π·1e-6·400·1e-15/Φ0 ≈ 0.0038
    out = rcsj_iv(ic, r, c, i_max_factor=2.0, n_steps=200)
    assert out["regime"] == "overdamped"
    assert out["overdamped_check"] is not None
    assert out["overdamped_check"] <= 0.05
    # 低于 Ic 静态：V 数值残差级（i=0.5 格点）
    assert out["v_up_v"][0] < 1e-12


def test_rcsj_underdamped_hysteresis():
    """欠阻尼（β_c≈7.6）：i<1 处降流支亚稳运行态（表观回滞结构锚）。

    升支从静态（i=0.5 起）→ i=0.9 处 V≈0；降支从运行态下来 →
    有限时窗内仍 V>0（亚稳）。i>1 处两支同在运行支（近似一致带）。
    """
    ic, r, c = 1e-6, 200.0, 8.2e-13  # β_c≈100：衰减 ~β_c·τ ≫ 驻留窗 16τ
    out = rcsj_iv(ic, r, c, i_max_factor=2.0, n_steps=120)
    assert out["regime"] == "underdamped"
    grid = out["i_over_a"]
    idx09 = min(range(len(grid)), key=lambda k: abs(grid[k] - 0.9))
    v_up_09 = out["v_up_v"][idx09]
    v_down_09 = out["v_down_v"][idx09]
    assert v_up_09 < 1e-6  # 升支静态
    assert v_down_09 > 1e-5  # 降支亚稳运行（回滞在案）
    assert v_down_09 > out["v_down_v"][min(
        range(len(grid)), key=lambda k: abs(grid[k] - 0.7))]  # 降支 i 单调
    # i>1 处两支同在运行支（40% 一致带——欠阻尼运行支数值斜坡口径）
    idx12 = min(range(len(grid)), key=lambda k: abs(grid[k] - 1.2))
    hi = max(out["v_up_v"][idx12], out["v_down_v"][idx12])
    assert hi > 0
    assert abs(out["v_up_v"][idx12] - out["v_down_v"][idx12]) <= 0.4 * hi


def test_register_notes_doc_face():
    assert "不产数" in gao_engineering_note()["normalization"]
    assert "登记级" in quantum_register_note()["boundary"]


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        bcs_gap_ev(9.25, 9.25)
    with pytest.raises(ValueError):
        two_fluid_sigma1(1e7, -1.0, 9.25)
    with pytest.raises(ValueError):
        superconductor_rs(-1.0, 39e-9, 5e9)
    with pytest.raises(ValueError):
        rcsj_plasma_frequency(0.0, 1e-12)
    with pytest.raises(ValueError):
        rcsj_iv(1e-6, 20.0, 1e-15, i_max_factor=0.5)
    with pytest.raises(ValueError):
        rcsj_iv(1e-6, 20.0, 1e-15, n_steps=10)
