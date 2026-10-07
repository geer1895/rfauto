"""W4-C P10：ITU-R P.618-13 全链锚测试（雨衰/等效雨高/XPD/闪烁 Nwet）。

原文核对证据（#1c，逐式视觉核verify，2026-10-05）：
- P.618-13 官方 PDF（runs/w4_phase4/w4c/evidence/R-REC-P.618-13-201712.pdf，
  ITU dms_pubrec 免费承载；式(1)-(8) 印刷页 6-7 PNG 视觉读式 p618_p7/p8.png；
  闪烁 §2.4.1 式(40)-(46) 印刷页 17-18；XPD §4.1 式(65)-(72) 印刷页 23-24）。
- P.839-4（R-REC-P.839-4-201309.pdf）：h0 = 数字地图（数据文件，PV-011 不
  捆绑），hR = h0 + 0.36 km（recommends 2 原式）——h0 为调用方显式输入。
- P.453-13（R-REC-P.453-13-201712.pdf）：式(4) N_wet = 72e/T + 3.75e5·e/T²、
  式(8) e = H·e_s/100、式(9) e_s = EF·a·exp[(b−t/d)·t/(t+c)]（水相系数
  6.1121/18.678/257.14/234.5 与 EF_water 式，印刷页 2-3 视觉读式）。

裁判制度（#118 双源）：①结构恒等（天顶 Ls=hR−hs、Ap(0.01)≡A0.01、
a(1%)=3σ、Cτ(45°)=0、点天线 g→1、低角 Ls→√(2·Δh·Re) 视距极限）；
②独立手算点（测试内按原文式逐步重排算，非实现同代码）；
③窗锚（量级窗先于实现钉，工程量级依据写明）；④域守卫（原文声明域）。
"""

from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.itu_atmosphere import (
    EFFECTIVE_EARTH_RADIUS_KM,
    effective_rain_height_km,
    gamma_rain_db_per_km,
    rain_attenuation_ap,
    rain_attenuation_r001,
    refractivity_wet,
    saturation_vapour_pressure_hpa,
    scintillation_fade_db,
    scintillation_nwet,
    scintillation_sigma_ref_db,
    scintillation_std_db,
    slant_path_rain_km,
    vapour_pressure_hpa,
    xpd_rain_db,
)

# ─── 等效雨高（P.839-4）───────────────────────────────────────────────────────

def test_rain_height_plus_036_identity():
    """hR = h0 + 0.36 km（P.839-4 recommends 2 原式逐位）。"""
    assert effective_rain_height_km(3.0) == pytest.approx(3.36, abs=1e-15)
    with pytest.raises(ValueError, match="h0_km"):
        effective_rain_height_km(0.0)


# ─── 斜路径长（式(1)/(2)）─────────────────────────────────────────────────────

def test_slant_path_zenith_identity():
    """θ=90°：Ls = hR−hs 逐位（式(1) sin90=1）。"""
    assert slant_path_rain_km(3.36, 0.1, 90.0) == pytest.approx(3.26, abs=1e-12)


def test_slant_path_5deg_continuity():
    """式(1)/(2) 在 θ=5° 分段点连续（相对差 <5%，曲率项在 5° 已是小量）。"""
    dh = 3.0
    l1 = dh / math.sin(math.radians(5.0))
    l2 = slant_path_rain_km(dh + 0.5, 0.5, 5.0)
    assert abs(l1 - l2) / l1 < 0.05


def test_slant_path_low_angle_horizon_limit():
    """θ→0：式(2) → √(2·Δh·Re)（视距/地平极限，独立推导锚）。

    极限推导：sinθ→0 时 Ls = 2Δh/√(2Δh/Re) = √(2·Δh·Re)。
    """
    dh = 3.0
    expected = math.sqrt(2.0 * dh * EFFECTIVE_EARTH_RADIUS_KM)
    got = slant_path_rain_km(dh, 0.0, 0.01)
    assert got == pytest.approx(expected, rel=0.01)


def test_slant_path_zero_branch_and_guards():
    """hR ≤ hs → 0.0（原文零分支）；仰角域 (0,90]。"""
    assert slant_path_rain_km(2.0, 2.0, 30.0) == 0.0
    assert slant_path_rain_km(1.9, 2.0, 30.0) == 0.0
    with pytest.raises(ValueError, match="elevation_deg"):
        slant_path_rain_km(3.0, 0.0, 90.5)
    with pytest.raises(ValueError, match="elevation_deg"):
        slant_path_rain_km(3.0, 0.0, 0.0)


# ─── R0.01 全链（式(1)-(7)）──────────────────────────────────────────────────

def _chain_ref(f, r001, el, h0, hs, lat, re=EFFECTIVE_EARTH_RADIUS_KM):
    """独立重排裁判（#118 路径 B）：测试内按原文 Step1-9 逐步显式算。"""
    h_r = h0 + 0.36
    sin_t, cos_t = math.sin(math.radians(el)), math.cos(math.radians(el))
    l_s = (h_r - hs) / sin_t  # 式(1)（测试取 θ≥5° 主域）
    l_g = l_s * cos_t  # 式(3)
    gamma = gamma_rain_db_per_km(f, r001)  # 式(4)（已 Table-5 对拍面复用）
    r001_f = 1.0 / (1.0 + 0.78 * math.sqrt(l_g * gamma / f) - 0.38 * (1 - math.exp(-2 * l_g)))  # 式(5)
    zeta = math.degrees(math.atan((h_r - hs) / (l_g * r001_f)))  # Step7
    l_r = l_g * r001_f / cos_t if zeta > el else (h_r - hs) / sin_t
    chi = 36.0 - abs(lat) if abs(lat) < 36.0 else 0.0
    nu = 1.0 / (1.0 + math.sqrt(sin_t) * (
        31.0 * (1.0 - math.exp(-el / (1.0 + chi))) * math.sqrt(l_r * gamma) / f**2 - 0.45))
    l_e = l_r * nu  # 式(6)
    return h_r, l_s, l_g, gamma, r001_f, zeta, l_r, chi, nu, l_e, gamma * l_e  # 式(7)


def test_rain_chain_matches_independent_step_recompute():
    """全链 vs 测试内独立逐步重排（rel 1e-12；中间量逐项对拍）。"""
    f, r001, el, h0, hs, lat = 20.0, 30.0, 30.0, 3.0, 0.0, 45.0
    out = rain_attenuation_r001(f, r001, el, h0, hs, lat)
    (h_r, l_s, l_g, gamma, r_f, zeta, l_r, chi, nu, l_e, a001) = _chain_ref(
        f, r001, el, h0, hs, lat)
    assert out["h_r_km"] == pytest.approx(h_r, rel=1e-12)
    assert out["l_s_km"] == pytest.approx(l_s, rel=1e-12)
    assert out["l_g_km"] == pytest.approx(l_g, rel=1e-12)
    assert out["gamma_r_dbkm"] == pytest.approx(gamma, rel=1e-12)
    assert out["r001_factor"] == pytest.approx(r_f, rel=1e-12)
    assert out["zeta_deg"] == pytest.approx(zeta, rel=1e-12)
    assert out["l_r_km"] == pytest.approx(l_r, rel=1e-12)
    assert out["chi_deg"] == pytest.approx(chi, abs=1e-12)
    assert out["nu001"] == pytest.approx(nu, rel=1e-12)
    assert out["l_e_km"] == pytest.approx(l_e, rel=1e-12)
    assert out["a001_db"] == pytest.approx(a001, rel=1e-12)


def test_rain_chain_magnitude_window():
    """窗锚：20GHz/R0.01=30/el=30°/h0=3km → A0.01 ∈ [8,30] dB。

    量级依据（实现前钉）：γR(20GHz,30mm/h)≈3.3 dB/km（P.838 Table-5 对拍
    面有效域内），有效路径 4-7 km（30° 仰角、hR≈3.4 km 量级）→ 13-23 dB
    中枢，窗再放宽一档。
    """
    out = rain_attenuation_r001(20.0, 30.0, 30.0, 3.0, 0.0, 45.0)
    assert 8.0 <= out["a001_db"] <= 30.0
    # γR 与已对拍面一致（内部一致性）
    assert out["gamma_r_dbkm"] == pytest.approx(gamma_rain_db_per_km(20.0, 30.0))


def test_rain_chain_zero_branches():
    """无雨/hR≤hs → 恒 0 且带零分支注记（原文 Step2/Step4）。"""
    z = rain_attenuation_r001(20.0, 0.0, 30.0, 3.0, 0.0, 45.0)
    assert z["a001_db"] == 0.0 and "r001=0" in z["zero_reason"]
    z2 = rain_attenuation_r001(20.0, 30.0, 30.0, 1.0, 2.0, 45.0)
    assert z2["a001_db"] == 0.0 and "h_r<=hs" in z2["zero_reason"]


def test_rain_chain_zenith_else_branch():
    """天顶角：ζ=θ 恰等须走 else 分支（#347 余量）→ LR=hR−hs、A>0。

    浮点陷阱：cos90°≈6e-17 使 ζ 可落在 90±ulp；实现按 ζ>θ+1e-9 判分支，
    本钉防"恰等翻分支 → LR=0/0→0 → A001=0"回归。
    """
    out = rain_attenuation_r001(20.0, 30.0, 90.0, 3.0, 0.0, 45.0)
    assert out["a001_db"] > 0.0
    assert out["l_r_km"] == pytest.approx(out["h_r_km"], rel=1e-9)


# ─── 时间百分数换算（式(8)）───────────────────────────────────────────────────

def test_ap_at_001_identity():
    """Ap(0.01) ≡ A0.01（(0.01/0.01)^k = 1 结构恒等，逐位）。"""
    a001 = rain_attenuation_r001(20.0, 30.0, 30.0, 3.0, 0.0, 45.0)["a001_db"]
    assert rain_attenuation_ap(a001, 0.01, 45.0, 30.0) == pytest.approx(a001, rel=1e-15)


def test_ap_monotone_in_p_and_beta_branches():
    """p 越小 A 越大（CCDF 单调）；p≥1% 或 |φ|≥36° → β=0 分支单调自洽。"""
    a001 = rain_attenuation_r001(20.0, 30.0, 30.0, 3.0, 0.0, 45.0)["a001_db"]
    seq = [rain_attenuation_ap(a001, p, 45.0, 30.0)
           for p in (5.0, 1.0, 0.3, 0.1, 0.03, 0.01, 0.003, 0.001)]
    assert all(x < y for x, y in pairwise(seq))
    # p=5 与 p=1 同在 β=0 分支（|φ|=45 <36° 不触发；p≥1% → β=0）
    assert seq[0] < seq[1]
    # 高纬 |φ|≥36° → β=0：p=0.1 处与显式 β=0 手算一致
    p, lat, el = 0.1, 40.0, 30.0
    got = rain_attenuation_ap(a001, p, lat, el)
    expo = -(0.655 + 0.033 * math.log(p) - 0.045 * math.log(a001))
    assert got == pytest.approx(a001 * (p / 0.01) ** expo, rel=1e-12)


def test_ap_domain_guards():
    a001 = 17.0
    with pytest.raises(ValueError, match="p_percent"):
        rain_attenuation_ap(a001, 0.0009, 45.0, 30.0)
    with pytest.raises(ValueError, match="p_percent"):
        rain_attenuation_ap(a001, 5.1, 45.0, 30.0)
    with pytest.raises(ValueError, match="a001_db"):
        rain_attenuation_ap(-1.0, 0.1, 45.0, 30.0)


# ─── P.453-13 承接（e_s/e/N_wet）─────────────────────────────────────────────

def test_saturation_vapour_pressure_reference_points():
    """e_s 参考点窗锚：20°C→[22.5,24.5] hPa（标准气象值 23.4）；0°C→[5.9,6.4]。

    标准值出处：常见气象手册 20°C 饱和水汽压 23.39 hPa / 0°C 6.112 hPa
    （Magnus 族通值；ITU 式为其高精度形态，窗 ±0.6 hPa）。
    """
    assert saturation_vapour_pressure_hpa(20.0) == pytest.approx(23.4, abs=1.1)
    assert saturation_vapour_pressure_hpa(0.0) == pytest.approx(6.11, abs=0.3)


def test_es_ice_water_consistency_near_zero():
    """0°C 水相/冰相 e_s 连续（相变点一致性，相对差 <0.5%）。"""
    w = saturation_vapour_pressure_hpa(0.0, medium="water")
    i = saturation_vapour_pressure_hpa(0.0, medium="ice")
    assert abs(w - i) / w < 0.005


def test_nwet_independent_hand_compute():
    """Nwet 独立手算点：t=20°C、H=50%、P=1013.25 hPa。

    手算（原文式逐步，EF 全式入算不预舍入）：
    EF = 1+1e-4·[7.2+1013.25·(0.0320+5.9e-6·400)]；
    e_s = EF·6.1121·exp[(18.678−20/234.5)·20/277.14]；e = e_s/2；
    N_wet = 72·e/293.15 + 3.75e5·e/293.15²。
    """
    ef = 1.0 + 1e-4 * (7.2 + 1013.25 * (0.0320 + 5.9e-6 * 20.0**2))
    es = ef * 6.1121 * math.exp((18.678 - 20.0 / 234.5) * 20.0 / (20.0 + 257.14))
    e = 50.0 * es / 100.0
    t = 293.15
    expect = 72.0 * e / t + 3.75e5 * e / (t * t)
    assert scintillation_nwet(20.0, 50.0) == pytest.approx(expect, rel=1e-12)
    # 承接链分件同口径
    assert vapour_pressure_hpa(20.0, 50.0) == pytest.approx(e, rel=1e-12)
    assert refractivity_wet(t, e) == pytest.approx(expect, rel=1e-12)


# ─── 闪烁链（式(40)-(46)）────────────────────────────────────────────────────

def test_sigma_ref_identity():
    """σ_ref = 3.6e-3 + 1e-4·Nwet 逐位恒等（式(40)）。"""
    assert scintillation_sigma_ref_db(54.0) == pytest.approx(3.6e-3 + 1e-4 * 54.0, abs=1e-15)
    with pytest.raises(ValueError, match="nwet"):
        scintillation_sigma_ref_db(-1.0)


def test_scintillation_fade_at_1pct_is_3sigma():
    """a(1%)=3.0 恒等（log10(1)=0 使三次式只剩常数项）→ A(1%)=3σ 逐位。"""
    sigma = scintillation_std_db(12.0, 30.0, 54.0, 1.2)
    assert scintillation_fade_db(1.0, sigma) == pytest.approx(3.0 * sigma, rel=1e-12)


def test_scintillation_point_antenna_limit():
    """点天线极限：D→0 时 x→0、g(x)→1（根号内 →3.86·sin(11π/12)=0.999…）。"""
    sigma = scintillation_std_db(12.0, 30.0, 54.0, 0.01)
    sigma_ref = scintillation_sigma_ref_db(54.0)
    s30 = math.sin(math.radians(30.0))
    expect = sigma_ref * 12.0 ** (7.0 / 12.0) * 1.0 / s30**1.2
    assert sigma == pytest.approx(expect, rel=1e-3)


def test_scintillation_monotonicity():
    """σ 随 f 升（f^{7/12} 主项）、随 θ 升降（(sinθ)^1.2 衰减）、随天线直径降
    （孔径平均）；A(p) 随 p 降单调加深。"""
    sig_f = [scintillation_std_db(f, 30.0, 54.0, 1.2) for f in (4.0, 8.0, 12.0, 20.0)]
    assert all(x < y for x, y in pairwise(sig_f))
    sig_el = [scintillation_std_db(12.0, th, 54.0, 1.2) for th in (5.0, 15.0, 45.0, 90.0)]
    assert all(x > y for x, y in pairwise(sig_el))
    sig_d = [scintillation_std_db(12.0, 30.0, 54.0, d) for d in (0.3, 1.2, 3.0, 7.0)]
    assert all(x > y for x, y in pairwise(sig_d))
    sig = sig_d[1]
    fades = [scintillation_fade_db(p, sig) for p in (50.0, 10.0, 1.0, 0.1, 0.02)]
    assert all(x < y for x, y in pairwise(fades))


def test_scintillation_x_ge7_zero_branch():
    """g(x) 根号内 <0（x≥7）→ 0.0（原文零分支；天顶+大口径构造）。"""
    assert scintillation_std_db(20.0, 90.0, 54.0, 45.0, eta=0.5) == 0.0


def test_scintillation_domain_guards():
    with pytest.raises(ValueError, match=r"f_ghz 有效域"):
        scintillation_std_db(3.9, 30.0, 54.0, 1.2)
    with pytest.raises(ValueError, match="theta_deg"):
        scintillation_std_db(12.0, 4.9, 54.0, 1.2)
    with pytest.raises(ValueError, match="p_percent"):
        scintillation_fade_db(0.01, 0.1)
    with pytest.raises(ValueError, match="p_percent"):
        scintillation_fade_db(50.1, 0.1)


# ─── XPD（式(65)-(72)）────────────────────────────────────────────────────────

def test_xpd_hand_computed_point():
    """手算点：f=20/Ap=10/p=0.01%/τ=45°/θ=30° → XPD_p=17.4378 dB。

    独立算（原文式逐步）：Cf=26log10(20)+4.1=37.9287；CA=22.6·log10(10)=22.6；
    Cτ=0（45° 恒等）；Cθ=−40log10(cos30)=2.4994；Cσ=0.0053·10²=0.53；
    XPD_rain=18.3581；C_ice=18.3581·(0.3+0.1·log10(0.01))/2=0.9179；
    XPD_p=17.4402 前四位（实现 rel 1e-12 对齐）。
    """
    c_f = 26.0 * math.log10(20.0) + 4.1
    c_a = 22.6 * math.log10(10.0)
    c_tau = 0.0
    c_theta = -40.0 * math.log10(math.cos(math.radians(30.0)))
    c_sigma = 0.0053 * 10.0**2
    xpd_rain = c_f - c_a + c_tau + c_theta + c_sigma
    c_ice = xpd_rain * (0.3 + 0.1 * math.log10(0.01)) / 2.0
    expect = xpd_rain - c_ice
    got = xpd_rain_db(20.0, 10.0, 0.01, 45.0, elevation_deg=30.0)
    assert got == pytest.approx(expect, rel=1e-12)


def test_xpd_tau45_zero_and_tau0_max_improvement():
    """Cτ(45°)=0 与 Cτ(0°)=−10log10(0.032)（两极点恒等）。"""
    base = xpd_rain_db(20.0, 10.0, 0.01, 45.0, elevation_deg=30.0)
    tau0 = xpd_rain_db(20.0, 10.0, 0.01, 0.0, elevation_deg=30.0)
    # p=0.01% 的冰晶因子缩放：(0.3+0.1·log10(0.01))/2 = 0.05 → XPD_p=0.95·XPD_rain，
    # 差值也按同因子缩放（C_ice ∝ XPD_rain）
    scale = 1.0 - (0.3 + 0.1 * math.log10(0.01)) / 2.0
    assert scale == pytest.approx(0.95, abs=1e-12)
    assert tau0 - base == pytest.approx(scale * (-10.0 * math.log10(1.0 - 0.968)), rel=1e-12)
    tau90 = xpd_rain_db(20.0, 10.0, 0.01, 90.0, elevation_deg=30.0)
    assert tau90 - base == pytest.approx(scale * (-10.0 * math.log10(1.0 - 0.968)), rel=1e-12)


def test_xpd_canting_table_and_monotone():
    """倾角 σ 四档（1/0.1/0.01/0.001% → 0/5/10/15°）与 Ap 单调（雨越大 XPD 越差）。"""
    # p=0.1% → σ=5 → Cσ=0.0053·25=0.1325（显式手算对拍）
    x_01 = xpd_rain_db(20.0, 10.0, 0.1, 45.0, elevation_deg=30.0)
    x_1 = xpd_rain_db(20.0, 10.0, 1.0, 45.0, elevation_deg=30.0)
    # 两点差 = Cσ 差 + C_ice 差，独立展开：
    def _ref(p, sigma):
        c_f = 26.0 * math.log10(20.0) + 4.1
        xr = c_f - 22.6 + (-40.0 * math.log10(math.cos(math.radians(30.0)))) + 0.0053 * sigma**2
        return xr - xr * (0.3 + 0.1 * math.log10(p)) / 2.0
    assert x_01 == pytest.approx(_ref(0.1, 5.0), rel=1e-12)
    assert x_1 == pytest.approx(_ref(1.0, 0.0), rel=1e-12)
    seq = [xpd_rain_db(20.0, ap, 0.01, 45.0, elevation_deg=30.0) for ap in (1.0, 3.0, 10.0, 30.0)]
    assert all(x > y for x, y in pairwise(seq))


def test_xpd_domain_guards():
    with pytest.raises(ValueError, match=r"f_ghz 有效域"):
        xpd_rain_db(5.9, 10.0, 0.01, elevation_deg=30.0)
    with pytest.raises(ValueError, match=r"f_ghz 有效域"):
        xpd_rain_db(55.1, 10.0, 0.01, elevation_deg=30.0)
    with pytest.raises(ValueError, match="elevation_deg"):
        xpd_rain_db(20.0, 10.0, 0.01, elevation_deg=60.5)
    with pytest.raises(ValueError, match="ap_db"):
        xpd_rain_db(20.0, 0.0, 0.01, elevation_deg=30.0)
    with pytest.raises(ValueError, match=r"p_percent 须为"):
        xpd_rain_db(20.0, 10.0, 0.05, elevation_deg=30.0)
