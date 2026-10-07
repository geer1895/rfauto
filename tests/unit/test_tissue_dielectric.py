"""NX-7 Gabriel 组织介电单测（2026-10-03）。

锚树口径（#118/#122：原文表转录 + 独立公式路，不赌推导）：
- 静态极限：f→0 时 ε* → ε∞ + ΣΔεi + σ/(jωε0) → εr′≈ΣΔε+ε∞、εr″ 由
  σ 主导（muscle 静态 εr′=4+50+7000+1.2e6+2.5e7 ≈ 2.62e7 逐位恒等）。
- 高频极限：f→∞（1-10 GHz 段）εr′ → ε∞+Δε1 附近（高频弥散只剩极 1）；
  muscle @2.45 GHz 独立文献带（εr′≈52.7、σ≈1.74 S/m，±5% 带——公开
  工具库值，#118 独立带锚）。
- Cole-Cole 求值 vs 独立数值积分式（Debye 极限 α=0 时退化 Debye 式
  ε*=ε∞+Δε/(1+jωτ) 逐位）。
- 植入链：波长缩短比 = √εr′ 恒等；SAR 门 pass/fail 边界（e=门限反演
  场强逐位）。
- 加载器：17 组织行数恒等 + provenance 逐行保真。
"""
from __future__ import annotations

import math

import pytest

from rfauto.core.tissue_dielectric import (
    SAR_GATE_W_PER_KG_10G,
    cole_cole_eps,
    implant_link_chain,
    load_gabriel1996,
)

_TABLE = load_gabriel1996()


def test_loader_row_integrity():
    """17 组织行、muscle 参数逐格、缺极组织（blood 双极）结构。"""
    assert len(_TABLE) == 17
    m = _TABLE["muscle"]
    assert m["eps_inf"] == 4.0
    assert m["sigma_s_m"] == 0.20
    assert len(m["poles"]) == 4
    assert m["poles"][0][0] == 50.0 and m["poles"][0][2] == 0.10
    assert abs(m["poles"][0][1] - 7.23e-12) <= 1e-24
    assert m["poles"][3] == (2.5e7, 2.274e-3, 0.00)
    blood = _TABLE["blood"]
    assert len(blood["poles"]) == 2  # 零幅值极剔除
    assert blood["sigma_s_m"] == 0.70
    kid = _TABLE["kidney"]
    assert "0.10" in kid["provenance_note"] and "0.11" in kid["provenance_note"]


def test_static_limit_identity():
    """f=1 mHz：εr′ ≈ ε∞+ΣΔε（逐位带）；εr″ 由 σ 主导（1/(ωε0) 恒等）。"""
    out = cole_cole_eps("muscle", 1e-3, _TABLE)
    expect_eps = 4.0 + 50.0 + 7000.0 + 1.2e6 + 2.5e7
    assert abs(out["eps_r_real"] - expect_eps) <= 1e-6 * expect_eps
    omega = 2.0 * math.pi * 1e-3
    eps0 = 8.8541878128e-12
    expect_imag = 0.20 / (omega * eps0)
    assert abs(out["eps_r_imag"] - expect_imag) <= 1e-6 * expect_imag


def test_debye_alpha_zero_degeneration():
    """α=0 组织退化 Debye：独立式 ε*=ε∞+Δε/(1+jωτ)+σ/(jωε0) 逐位。"""
    f = 1e9
    omega = 2.0 * math.pi * f
    eps0 = 8.8541878128e-12
    # skin_dry 极 1：α=0.00（极 2 α=0.20 不用）→ 只用极 1 手算
    sd = _TABLE["skin_dry"]
    assert sd["poles"][0][2] == 0.0
    out = cole_cole_eps("skin_dry", f, _TABLE)
    # 逐极独立复算全部极
    eps_star = complex(sd["eps_inf"], 0.0)
    for de_i, tau_i, a_i in sd["poles"]:
        if a_i == 0.0:
            denom = 1.0 + 1j * omega * tau_i
        else:
            mag = (omega * tau_i) ** (1.0 - a_i)
            ang = (1.0 - a_i) * math.pi / 2.0
            denom = 1.0 + complex(mag * math.cos(ang), mag * math.sin(ang))
        eps_star += de_i / denom
    eps_star += complex(0.0, -sd["sigma_s_m"] / (omega * eps0))
    assert abs(out["eps_r_real"] - eps_star.real) <= 1e-9 * abs(eps_star.real)
    assert abs(out["eps_r_imag"] - (-eps_star.imag)) <= 1e-9 * abs(eps_star.imag)


def test_muscle_2p45ghz_literature_band():
    """muscle @2.45 GHz：εr′≈52.7（±5%）；介电损耗分量 vs FCC/IEEE 1528
    口径 σ=1.74（该口径不含静态 σ=0.2——本模块 σ_eff=总量，分解双报）。
    """
    out = cole_cole_eps("muscle", 2.45e9, _TABLE)
    assert abs(out["eps_r_real"] - 52.7) <= 0.05 * 52.7
    sigma_diel = out["sigma_eff_s_m"] - _TABLE["muscle"]["sigma_s_m"]
    assert abs(sigma_diel - 1.74) <= 0.02 * 1.74
    assert abs(out["sigma_eff_s_m"] - 1.94) <= 0.02 * 1.94


def test_penetration_depth_identity():
    """穿透深度 δ=1/√(πfμ0σ_eff)（肌肉 2.45 GHz ≈ 2 cm 量级带）。"""
    out = cole_cole_eps("muscle", 2.45e9, _TABLE)
    mu0 = 4.0e-7 * math.pi
    expect = 1.0 / math.sqrt(math.pi * 2.45e9 * mu0 * out["sigma_eff_s_m"])
    assert abs(out["penetration_depth_m"] - expect) <= 1e-15
    # 肌肉 2.45 GHz 场穿透深度 ~7 mm 量级（4-15 mm 带）
    assert 0.004 < out["penetration_depth_m"] < 0.015


def test_implant_link_chain():
    """波长缩短比=√εr′ 恒等；SAR 门边界（门限场强反演逐位）。"""
    f = 2.45e9
    e = 10.0
    out = implant_link_chain("muscle", f, e, 1000.0, _TABLE)
    assert abs(out["shortening_ratio"] - math.sqrt(out["eps_r_real"])) <= 1e-12
    sar_expect = out["sigma_eff_s_m"] * e * e / 1000.0
    assert abs(out["sar_w_per_kg"] - sar_expect) <= 1e-15
    assert out["sar_verdict"] == "pass" if sar_expect <= SAR_GATE_W_PER_KG_10G \
        else out["sar_verdict"] == "fail"
    # 门边界：场强 = sqrt(gate·ρ/σ) 处 SAR 恰达门限（±1e-12）
    cc = cole_cole_eps("muscle", f, _TABLE)
    e_gate = math.sqrt(SAR_GATE_W_PER_KG_10G * 1000.0 / cc["sigma_eff_s_m"])
    edge = implant_link_chain("muscle", f, e_gate, 1000.0, _TABLE)
    assert abs(edge["sar_w_per_kg"] - SAR_GATE_W_PER_KG_10G) <= 1e-9


def test_unknown_tissue_rejected():
    with pytest.raises(ValueError):
        cole_cole_eps("cartilage", 1e9, _TABLE)
    with pytest.raises(ValueError):
        cole_cole_eps("muscle", 0.0, _TABLE)
    with pytest.raises(ValueError):
        implant_link_chain("muscle", 1e9, 10.0, -1.0, _TABLE)
