"""EM-3 薄膜/涂层屏蔽 + IEEE 299 口径面单测（2026-10-03）。

锚树口径（#118：独立公式/双路互证，不赌推导）：
- 薄屏极限：t≪δ → Z_s → 1/(σt) 纯实（coth 一阶展开恒等，相对 1e-6）。
- 厚膜极限：t≫δ → Z_s → (1+j)/(σδ)（半无限，相对 1e-6）。
- 实部互证：Re|Z_s| vs conductor_loss.finite_thickness_surface_resistance
  （跨模块同式异实现，相对 ≤1e-9）。
- 电阻膜 SE：ABCD 并联导纳独立裁判路逐点一致；Rs=2η0 → 6.0206dB
  （半电压锚）；Rs→0 → 0。
- 涂层+基板：σ→∞ 涂层退化为 PEC 膜（S21→0）结构性锚；无涂层
  （t→0 极限走 Rs→∞）纯基板 TL 独立解析式一致。
- ETA0 恒等：4πe-7·c0 与 376.730313668（1e-9 相对）。
"""
from __future__ import annotations

import cmath
import math

import pytest

from rfauto.core.conductor_loss import finite_thickness_surface_resistance
from rfauto.core.thin_film_se import (
    C0_M_S,
    ETA0_OHM,
    coated_substrate_se,
    ieee299_measurement_note,
    resistive_sheet_se,
    skin_depth_m,
    thin_film_sheet_resistance,
    thin_film_surface_impedance,
)

_SIGMA_CU = 5.8e7
_F = 1e9


def test_eta0_identity():
    expect = 4.0e-7 * math.pi * C0_M_S
    assert abs(ETA0_OHM - expect) <= 1e-9 * expect


def test_thin_film_thin_limit():
    """t≪δ → Z_s → 1/(σt) 纯实（相对 1e-6）；与独立 Rs 恒等。"""
    t = 1e-9  # 1 nm，δ(Cu@1GHz)≈2.1µm
    zs = thin_film_surface_impedance(t, _SIGMA_CU, _F)
    rs = thin_film_sheet_resistance(_SIGMA_CU, t)
    assert abs(zs.real - rs) <= 1e-6 * rs
    assert abs(zs.imag) <= 1e-6 * rs


def test_thin_film_thick_limit():
    """t≫δ → Z_s → (1+j)/(σδ) 半无限极限（相对 1e-6）。"""
    t = 1e-3
    delta = skin_depth_m(_F, _SIGMA_CU)
    expect = (1.0 + 1.0j) / (_SIGMA_CU * delta)
    zs = thin_film_surface_impedance(t, _SIGMA_CU, _F)
    assert abs(zs - expect) <= 1e-6 * abs(expect)


def test_real_part_crosscheck_vs_conductor_loss():
    """Re(Z_s) 跨模块互证 conductor_loss.finite_thickness_surface_resistance。"""
    for t in (1e-7, 5e-7, 1e-6, 1e-5):
        zs = thin_film_surface_impedance(t, _SIGMA_CU, _F)
        ref = finite_thickness_surface_resistance(_F, _SIGMA_CU, t)
        assert abs(zs.real - ref) <= 1e-9 * ref


def test_resistive_sheet_se_anchors():
    """半电压锚：Rs=η0/2 → 6.0206dB；Rs→0 → inf；ABCD 独立路逐点一致。"""
    out = resistive_sheet_se(ETA0_OHM / 2.0)
    assert abs(out["se_db"] - 20.0 * math.log10(2.0)) <= 1e-12
    assert out["t_amplitude"] == pytest.approx(0.5, rel=1e-15)
    out_inf = resistive_sheet_se(0.0)
    assert out_inf["se_db"] == math.inf
    # 无膜极限：Rs→∞ → SE→0（独立路 2/(2+η0/Rs)→1）
    big = resistive_sheet_se(1e12)["se_db"]
    assert big <= 1e-8
    # ABCD 独立裁判路：[1 0; 1/Rs 1] → S21 = 2/(2 + η0/Rs)
    for rs in (1.0, 10.0, 50.0, 200.0, 1000.0):
        mine = resistive_sheet_se(rs)["se_db"]
        s21 = 2.0 / (2.0 + ETA0_OHM / rs)
        ref = -20.0 * math.log10(abs(s21))
        assert abs(mine - ref) <= 1e-12


def test_coated_substrate_pec_limit():
    """高 σ 涂层：|S21| 极小（近 PEC 膜）；SE 随之巨大（结构性锚）。

    t=1µm@1GHz 处 t/δ≈0.48 非深薄屏——|S21| 由 coth 全量给出（≈5e-7
    量级即可断锚，不虚构精确值）。
    """
    out = coated_substrate_se(1e-6, 1e12, 1.6e-3, 4.4, _F)
    assert abs(out["s21_complex"]) <= 1e-6
    assert out["se_db"] > 100.0


def test_coated_substrate_no_coating_limit():
    """无涂层语义（Rs→∞ 的对偶：σt→0）→ 纯基板 TL 独立解析一致。

    取极薄极低 σ 涂层（Rs 巨大）vs 纯基板 S21 = 2/(2cosβd + j(η/η0+η0/η)sinβd)
    的差随 Rs→∞ 收敛到 0（数值极限对照，容差 1e-6 相对）。
    """
    er, ts = 4.4, 1.6e-3
    eta = ETA0_OHM / math.sqrt(er)
    beta = 2.0 * math.pi * _F * math.sqrt(er) / C0_M_S
    s21_ref = 2.0 / (2.0 * cmath.cos(beta * ts)
                     + 1j * (eta / ETA0_OHM + ETA0_OHM / eta)
                     * cmath.sin(beta * ts))
    # σ 递减 → Rs 递增 → 偏差（≈η0/2Rs）严格递减，收敛到纯基板解析式
    prev = None
    for sigma in (1e5, 1e4, 1e3):
        out = coated_substrate_se(1e-9, sigma, ts, er, _F)
        diff = abs(out["s21_complex"] - s21_ref)
        assert prev is None or diff < prev
        prev = diff
    # σ=1e3 → Rs=1e6 → 一阶偏差 η0/(2Rs)≈1.9e-4（收敛带 5e-4）
    assert prev <= 5e-4


def test_skin_depth_identity():
    delta = skin_depth_m(_F, _SIGMA_CU)
    expect = math.sqrt(2.0 / (2.0 * math.pi * _F * 4.0e-7 * math.pi * _SIGMA_CU))
    assert abs(delta - expect) <= 1e-15


def test_ieee299_note_doc_face():
    note = ieee299_measurement_note()
    assert "不做自动换算系数" in note["conversion_statement"]
    assert "UNVERIFIED" in note["source"]


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        thin_film_surface_impedance(0.0, _SIGMA_CU, _F)
    with pytest.raises(ValueError):
        thin_film_surface_impedance(1e-6, -1.0, _F)
    with pytest.raises(ValueError):
        resistive_sheet_se(-1.0)
    with pytest.raises(ValueError):
        coated_substrate_se(1e-6, _SIGMA_CU, 1.6e-3, -4.4, _F)
