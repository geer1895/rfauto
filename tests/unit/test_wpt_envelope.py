"""NX-11 WPT 效率包络单测（2026-10-03）。

锚树口径（#118：闭式 vs 全电路数值最大化双路互证，不赌推导）：
- η_max 闭式 vs link_efficiency_vs_load（2×2 全电路解）在 R_L,opt 处
  一致（谐振调谐网格上，相对 ≤1e-6）；数值扫描效率 ≤ η_max（上限
  语义）。
- 极限锚：χ→0 → η≈χ/4（1e-9）；χ→∞ → η→1（χ=1e6 → η>0.998）。
- R_L,opt 闭式独立复算。
- Friis：频率平方反比 + 距离平方反比结构锚 + 1 m/1 GHz/0 dBi 各向
  同性解析值（λ/4π)²=7.14e-5 独立复算）。
- rectifier 曲线：p→0 η→0；膝区上升；p→∞ 饱和退化（结构锚）。
- Qi 登记面：15/25 W 常量 + UNVERIFIED 声明在案。
"""
from __future__ import annotations

import math

import pytest

from rfauto.core.wpt_envelope import (
    C0_M_S,
    QI2_POWER_REGISTER,
    friis_received_power,
    link_efficiency_vs_load,
    link_max_efficiency,
    optimal_load,
    qi_power_envelope,
    rectenna_dc_budget,
    rectifier_efficiency_curve,
)


def test_eta_max_limits():
    """极限锚：χ→0 → η≈χ/4；χ 大 → η→1。"""
    out0 = link_max_efficiency(0.01, 100.0, 100.0)
    chi0 = 0.01 ** 2 * 1e4  # = 1
    assert abs(out0["chi"] - chi0) <= 1e-12
    out_small = link_max_efficiency(0.001, 10.0, 10.0)
    chi = 1e-4
    assert abs(out_small["eta_max"] - chi / 4.0) <= 2e-9  # O(χ²) 修正 1.25e-9
    out_big = link_max_efficiency(0.5, 1000.0, 1000.0)
    assert out_big["eta_max"] > 0.996  # χ=2.5e5 → η≈1−2/√χ=0.9960
    out_huge = link_max_efficiency(0.5, 4000.0, 4000.0)
    assert out_huge["eta_max"] > 0.998  # χ=4e6


def test_closed_form_vs_full_circuit_at_optimal_load():
    """闭式 vs 全电路数值：谐振调谐下 R_L,opt 处效率逐点一致（1e-6）。"""
    f = 200e3
    omega = 2.0 * math.pi * f
    l1 = l2 = 10e-6
    q1 = q2 = 80.0
    r1 = omega * l1 / q1
    r2 = omega * l2 / q2
    c1 = 1.0 / (omega ** 2 * l1)
    c2 = 1.0 / (omega ** 2 * l2)
    k = 0.15
    m = k * math.sqrt(l1 * l2)
    out_opt = optimal_load(omega, l2, q2, k, q1)
    r_opt = out_opt["r_load_opt_ohm"]
    circuit = link_efficiency_vs_load(
        1.0, 0.05, l1, c1, r1, l2, c2, r2, m, r_opt, f)
    closed = link_max_efficiency(k, q1, q2)
    assert abs(circuit["eta"] - closed["eta_max"]) <= 1e-6 * closed["eta_max"]
    # 上限语义：偏置负载效率 ≤ η_max
    for frac in (0.3, 3.0):
        circ = link_efficiency_vs_load(
            1.0, 0.05, l1, c1, r1, l2, c2, r2, m, r_opt * frac, f)
        assert circ["eta"] <= closed["eta_max"] + 1e-12


def test_optimal_load_identity():
    """R_L,opt 独立复算恒等。"""
    omega, l2, q2, k, q1 = 1.257e6, 5e-6, 60.0, 0.2, 50.0
    out = optimal_load(omega, l2, q2, k, q1)
    chi = k * k * q1 * q2
    expect = omega * l2 * math.sqrt(1.0 + chi) / q2
    assert abs(out["r_load_opt_ohm"] - expect) <= 1e-15 * expect


def test_friis_structure_anchors():
    """Friis：各向同性 1 GHz 1 m → (λ/4π)² 独立复算；f²/d² 反比锚。"""
    out = friis_received_power(1.0, 1.0, 1.0, 1e9, 1.0)
    lam = C0_M_S / 1e9
    expect = (lam / (4.0 * math.pi)) ** 2
    assert abs(out["p_rx_w"] - expect) <= 1e-18
    out_f2 = friis_received_power(1.0, 1.0, 1.0, 2e9, 1.0)
    assert abs(out_f2["p_rx_w"] / out["p_rx_w"] - 0.25) <= 1e-12
    out_d2 = friis_received_power(1.0, 1.0, 1.0, 1e9, 2.0)
    assert abs(out_d2["p_rx_w"] / out["p_rx_w"] - 0.25) <= 1e-12


def test_rectifier_curve_shape():
    """整流曲线：p→0 η→0；单峰结构（膝升、饱和退化）；上限 ≤ η_pk。"""
    lo = rectifier_efficiency_curve(1e-8)["eta_rf_dc"]
    mid = rectifier_efficiency_curve(1e-4)["eta_rf_dc"]
    hi = rectifier_efficiency_curve(10.0)["eta_rf_dc"]
    assert lo < mid
    assert hi < mid  # 高功率饱和退化
    assert mid <= 0.80 + 1e-12
    with pytest.raises(ValueError):
        rectifier_efficiency_curve(1e-4, eta_peak=1.5)


def test_rectenna_budget_chain():
    """链预算：p_dc = p_rx·η_rf_dc（恒等）；note 声明在案。"""
    out = rectenna_dc_budget(1.0, 4.0, 4.0, 2.45e9, 5.0)
    assert abs(out["p_dc_w"] - out["p_rx_w"] * out["eta_rf_dc"]) <= 1e-18
    assert "single_source" in out["note"]


def test_qi_register_face():
    """Qi 登记面：15/25 W + UNVERIFIED 声明。"""
    assert QI2_POWER_REGISTER["Qi2_BPP_MPP_baseline_w"] == 15.0
    assert QI2_POWER_REGISTER["Qi2_2_extended_w"] == 25.0
    assert "UNVERIFIED" in QI2_POWER_REGISTER["source"]
    env = qi_power_envelope(0.3, 60.0)
    assert env["Qi2_BPP_MPP_baseline_w"] == 15.0
    assert 0.0 < env["eta_max_link"] <= 1.0


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        link_max_efficiency(1.5, 50.0, 50.0)
    with pytest.raises(ValueError):
        link_max_efficiency(0.1, 0.5, 50.0)  # Q<1
    with pytest.raises(ValueError):
        link_efficiency_vs_load(
            1.0, 0.05, 10e-6, 1e-9, 0.05, 10e-6, 1e-9, 0.05,
            2.0e-5, 50.0, 200e3)  # k=M/√(L1L2)=2>1 非物理
    with pytest.raises(ValueError):
        friis_received_power(1.0, 1.0, 1.0, 1e9, 1.0, pol_mismatch=1.5)
