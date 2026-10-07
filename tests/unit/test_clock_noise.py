"""F-E 件 2 相噪→抖动积分内核单测（研究扩充 round3 F-E 表件 2 判据）。

裁判口径（#118）：全部解析常量由**独立代数路径**在测试内推导（不抄内核
表达式）——
- 白噪声：σ_φ² = 2·10^(L/10)·(f2−f1)（MT-008 定义式直接展开）；
- 1/f² 段：∫f⁻²df = (1/f1−1/f2)；1/f 段：∫f⁻¹df = ln(f2/f1)；
- 合成幂律谱：三区逐区独立写出 L_lin(f)=A·f^n 闭式再求和（与内核
  l_ref/f_ref 锚定表示法不同源的第三路径）；
- 数值路径：分均匀段高密度梯形求积（dB 线性口径 rel 1e-6、幂律口径
  rel 1e-6，双路径钉）。
退化分支（b→0）判据：与常数段**逐位**一致（==，非 approx）。

ADC SNR 限值公式（件 5 转发口径）已由 F-E 件 1
`core/adc_budget.snr_jitter_db` 承载——本件**不重复实现**（防同式双
实现分叉，#112 家族），测试钉"clock_noise 无 SNR 函数 + 件 1 公式
独立数值回收"。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import adc_budget
from rfauto.core import clock_noise as cn
from rfauto.service import clock_noise_service as cns


def _trapz(y: np.ndarray, x: np.ndarray) -> float:
    """梯形求积（numpy 2.x 无 np.trapz，手写两行，无版本歧义）。"""
    return float(np.sum(0.5 * (y[1:] + y[:-1]) * np.diff(x)))


# ─── 1. 白噪声解析回收（判据①：σ_φ²=2·L0_lin·(f2−f1) rel 1e-12）──────────────


def test_white_const_analytic_exact():
    r = cn.phase_jitter_from_l([1e3, 1e6], [-100.0], interp=cn.INTERP_CONST)
    expected = 2.0 * 10.0 ** (-10.0) * (1e6 - 1e3)
    assert r.sigma_phi2_rad2 == pytest.approx(expected, rel=1e-12)
    assert r.sigma_phi_rad == pytest.approx(math.sqrt(expected), rel=1e-12)
    assert r.n_segments == 1


def test_white_power_law_segment_analytic_exact():
    # 同一白噪声判据走幂律路径（斜率 0 段）——与 test_white_const 互为独立代码路径
    segs = [
        {"f_lo": 1e3, "f_hi": 1e6, "slope": 0.0, "l_ref_dbc": -100.0, "f_ref": 1e4}
    ]
    assert cn.power_law_sigma_phi2(segs, 1e3, 1e6) == pytest.approx(
        2.0 * 10.0 ** (-10.0) * (1e6 - 1e3), rel=1e-12
    )


# ─── 2. dB 线性段与退化分支（判据④：b→0 与常数段逐位一致）─────────────────────


def test_db_linear_flat_matches_const_bitwise():
    r_lin = cn.phase_jitter_from_l([1e3, 1e6], [-100.0, -100.0], interp=cn.INTERP_DB_LINEAR)
    r_cst = cn.phase_jitter_from_l([1e3, 1e6], [-100.0], interp=cn.INTERP_CONST)
    assert r_lin.sigma_phi2_rad2 == r_cst.sigma_phi2_rad2


def test_db_linear_degenerate_branch_bitwise_const():
    # |u| = 1e-13·ln10/10 ≈ 2.3e-14 < 1e-12 → 退化分支，与常数段(l1)逐位一致
    r = cn.phase_jitter_from_l([1e3, 1e6], [-100.0, -100.0 + 1e-13])
    expected = 2.0 * 10.0 ** (-10.0) * (1e6 - 1e3)
    assert r.sigma_phi2_rad2 == pytest.approx(expected, rel=1e-13)
    r_cst = cn.phase_jitter_from_l([1e3, 1e6], [-100.0], interp=cn.INTERP_CONST)
    assert r.sigma_phi2_rad2 == r_cst.sigma_phi2_rad2


def test_multiband_const_analytic_exact():
    # 多段常数谱逐段解析和（独立路径：直接展开 MT-008 定义式）
    r = cn.phase_jitter_from_l(
        [1e3, 1e4, 1e5], [-90.0, -110.0], interp=cn.INTERP_CONST
    )
    expected = 2.0 * (10.0 ** (-9.0) * (1e4 - 1e3) + 10.0 ** (-11.0) * (1e5 - 1e4))
    assert r.sigma_phi2_rad2 == pytest.approx(expected, rel=1e-12)
    assert r.n_segments == 2


def test_db_linear_multiband_vs_numeric_trapz():
    # 判据③双路径：dB 线性解析积分 vs 高密度梯形（rel 1e-6）
    edges = np.array([1e3, 1e4, 1e5, 1e6])
    l_vals = np.array([-70.0, -95.0, -110.0, -120.0])
    grid = np.unique(
        np.concatenate([np.linspace(edges[k], edges[k + 1], 120001) for k in range(3)])
    )
    y = 10.0 ** (np.interp(grid, edges, l_vals) / 10.0)
    i_num = _trapz(y, grid)
    r = cn.phase_jitter_from_l(edges, l_vals)
    assert r.sigma_phi2_rad2 == pytest.approx(2.0 * i_num, rel=1e-6)


def test_positive_l_unconstrained():
    # 诚实边界③：正 dBc/Hz 照算（符号不做约束）
    r = cn.phase_jitter_from_l([1e3, 1e6], [10.0], interp=cn.INTERP_CONST)
    assert r.sigma_phi2_rad2 == pytest.approx(2.0 * 10.0 * (1e6 - 1e3), rel=1e-12)


# ─── 3. 换算与守卫 ────────────────────────────────────────────────────────────


def test_conversions_deg_jitter_and_none_carrier():
    sigma2 = 2.0 * 10.0 ** (-10.0) * (1e6 - 1e3)
    sigma = math.sqrt(sigma2)
    r = cn.phase_jitter_from_l(
        [1e3, 1e6], [-100.0], interp=cn.INTERP_CONST, f_carrier=1e9
    )
    assert r.sigma_phi_deg == pytest.approx(math.degrees(sigma), rel=1e-12)
    assert r.jitter_s == pytest.approx(sigma / (2.0 * math.pi * 1e9), rel=1e-12)
    assert r.f_carrier_hz == 1e9
    # rms_jitter_s 独立调用恒等式
    assert cn.rms_jitter_s(sigma, 1e9) == pytest.approx(sigma / (2.0 * math.pi * 1e9), rel=1e-15)
    # 无载波 → jitter_s None（is not None 判缺，#364④）
    r_nc = cn.phase_jitter_from_l([1e3, 1e6], [-100.0], interp=cn.INTERP_CONST)
    assert r_nc.jitter_s is None and r_nc.f_carrier_hz is None


def test_phase_jitter_input_guards():
    with pytest.raises(ValueError):
        cn.phase_jitter_from_l([1e3, 1e6], [-100.0], interp="linear")  # 未知口径
    with pytest.raises(ValueError):
        cn.phase_jitter_from_l([1e3, 1e4, 1e6], [-100.0, -110.0])  # l 长度 ≠ 边界数
    with pytest.raises(ValueError):
        cn.phase_jitter_from_l([1e3, 1e6], [-100.0, float("nan")])  # 非有限 L
    with pytest.raises(ValueError):
        cn.phase_jitter_from_l([1e3, 1e6], [-100.0], f_carrier=True)  # bool 拒收
    with pytest.raises(ValueError):
        cn.phase_jitter_from_l([1e3, 1e6], [-100.0], f_carrier=0.0)  # 载波须 >0
    with pytest.raises(ValueError):
        cn.phase_jitter_from_l([1e3, 1e4, 1e6], [True, False, True])  # 布尔数组拒收


def test_freq_edges_guards():
    for bad in (
        [1e6, 1e3],  # 递减
        [1e3, 1e3],  # 相等（f1=f2 是标量接口的合法输入，边界数组必须严格递增）
        [1e3],  # 单点
        [0.0, 1e6],  # 含 0（偏移频率口径 >0）
        [-1.0, 1e6],  # 负频率
        [1e3, float("nan")],  # 非有限
    ):
        with pytest.raises(ValueError):
            cn.phase_jitter_from_l(bad, [-100.0, -110.0])


# ─── 4. 幂律段解析回收（判据②：1/f²、1/f 闭式 rel 1e-12）─────────────────────


def test_inv_f2_segment_analytic():
    segs = [
        {"f_lo": 100.0, "f_hi": 1e5, "slope": -2.0, "l_ref_dbc": -90.0, "f_ref": 1e4}
    ]
    # 独立路径：L_lin = 10^(−9)·(f/1e4)^−2 = 0.1·f^−2 → ∫ = 0.1·(1/f1−1/f2)
    expected = 2.0 * 0.1 * (1.0 / 100.0 - 1.0 / 1e5)
    assert cn.power_law_sigma_phi2(segs, 100.0, 1e5) == pytest.approx(expected, rel=1e-12)


def test_inv_f_segment_ln_analytic():
    segs = [
        {"f_lo": 10.0, "f_hi": 1e4, "slope": -1.0, "l_ref_dbc": -80.0, "f_ref": 1e3}
    ]
    # 独立路径：L_lin = 10^(−8)·(f/1e3)^−1 = 1e−5·f^−1 → ∫ = 1e−5·ln(f2/f1)
    expected = 2.0 * 1e-5 * math.log(1e4 / 10.0)
    assert cn.power_law_sigma_phi2(segs, 10.0, 1e4) == pytest.approx(expected, rel=1e-12)


# ─── 5. 合成幂律谱（判据主路径：拐角族合成 + 解析对照）─────────────────────────

_SEG_SHAPES = dict(l_floor_dbc=-110.0, corners=[(1e3, -3.0), (1e5, -1.0)], f_min=10.0, f_max=1e7)


def test_power_law_partition_conservation():
    segs = cn.build_power_law_segments(**_SEG_SHAPES)
    whole = cn.power_law_sigma_phi2(segs, 10.0, 1e7)
    parts = (
        cn.power_law_sigma_phi2(segs, 10.0, 1e3)
        + cn.power_law_sigma_phi2(segs, 1e3, 1e5)
        + cn.power_law_sigma_phi2(segs, 1e5, 1e7)
    )
    assert whole == pytest.approx(parts, rel=1e-12)


def test_power_law_composite_independent_closed_form():
    # 判据主路径：三区独立闭式（L_lin=A·f^n 直接推导）vs 内核锚定表示法
    segs = cn.build_power_law_segments(**_SEG_SHAPES)
    i_low = (100.0 ** (-2.0) - 1e3 ** (-2.0)) / 2.0  # 1/f³ 区：A=1（L(1e3)=−90）
    i_mid = 1e-6 * math.log(1e5 / 1e3)  # 1/f 区：A=1e−6（L(1e5)=−110）
    i_white = 1e-11 * (1e6 - 1e5)  # 白区：10^(−11)
    expected = 2.0 * (i_low + i_mid + i_white)
    assert cn.power_law_sigma_phi2(segs, 100.0, 1e6) == pytest.approx(expected, rel=1e-12)


def test_power_law_composite_vs_numeric_trapz():
    segs = cn.build_power_law_segments(**_SEG_SHAPES)
    grid = np.unique(
        np.concatenate(
            [
                np.logspace(math.log10(10.0), math.log10(1e7), 200001),
                np.array([1e3, 1e5]),
            ]
        )
    )
    y = 10.0 ** (np.asarray(cn.power_law_l_dbc(grid, segs)) / 10.0)
    i_num = _trapz(y, grid)
    assert cn.power_law_sigma_phi2(segs, 10.0, 1e7) == pytest.approx(2.0 * i_num, rel=1e-6)


def test_power_law_corner_continuity_and_ref_exact():
    segs = cn.build_power_law_segments(**_SEG_SHAPES)
    # 角点连续：f=1e3 处下探段（−3 斜率锚）与其上 1/f 段给出同值 −90
    assert cn.power_law_l_dbc(1e3, segs) == pytest.approx(-90.0, rel=1e-12)
    # f_ref 处逐位精确：白地板锚 f_ref=1e5 → L=−110（边界点归前段，两侧同值）
    assert cn.power_law_l_dbc(1e5, segs) == -110.0
    # 标量/数组两形态
    arr = cn.power_law_l_dbc(np.array([1e3, 1e5]), segs)
    assert arr[0] == pytest.approx(-90.0, rel=1e-12) and arr[1] == -110.0


def test_build_power_law_guards():
    with pytest.raises(ValueError):
        cn.build_power_law_segments(-110.0, [(1e3, -4.0)], 10.0, 1e7)  # 斜率不在族内
    with pytest.raises(ValueError):
        cn.build_power_law_segments(-110.0, [(1e3, 0.0)], 10.0, 1e7)  # 0 斜率角无意义
    with pytest.raises(ValueError):
        cn.build_power_law_segments(-110.0, [(1e5, -1.0), (1e3, -3.0)], 10.0, 1e7)  # 非递增
    with pytest.raises(ValueError):
        cn.build_power_law_segments(-110.0, [(1e3, -3.0)], 10.0, 1e3)  # f_max ≤ 末拐角
    with pytest.raises(ValueError):
        cn.build_power_law_segments(-110.0, [(1e3, -3.0)], 1e3, 1e7)  # f_min ≥ 首拐角
    with pytest.raises(ValueError):
        cn.build_power_law_segments(-110.0, [], 10.0, 1e7)  # 空 corners
    with pytest.raises(ValueError):
        cn.build_power_law_segments(-110.0, [(1e3, -3.0, 1)], 10.0, 1e7)  # 非二元组


def test_power_law_sigma_phi2_guards():
    segs = cn.build_power_law_segments(**_SEG_SHAPES)
    assert cn.power_law_sigma_phi2(segs, 1e4, 1e4) == 0.0  # f1=f2 → 逐位 0
    with pytest.raises(ValueError):
        cn.power_law_sigma_phi2(segs, 1e6, 1e3)  # f2<f1
    with pytest.raises(ValueError):
        cn.power_law_sigma_phi2(segs, 10.0, 1e8)  # 超出覆盖（不外推）
    with pytest.raises(ValueError):
        cn.power_law_sigma_phi2(segs, 1.0, 1e6)  # f1 低于覆盖下界
    with pytest.raises(ValueError):
        cn.power_law_sigma_phi2([], 1e3, 1e6)  # 空段链
    gapped = [
        {"f_lo": 1e3, "f_hi": 1e4, "slope": 0.0, "l_ref_dbc": -100.0, "f_ref": 1e3},
        {"f_lo": 2e4, "f_hi": 1e5, "slope": 0.0, "l_ref_dbc": -100.0, "f_ref": 2e4},
    ]
    with pytest.raises(ValueError):
        cn.power_law_sigma_phi2(gapped, 1e3, 1e5)  # 缝隙
    overlap = [
        {"f_lo": 1e3, "f_hi": 1e4, "slope": 0.0, "l_ref_dbc": -100.0, "f_ref": 1e3},
        {"f_lo": 9e3, "f_hi": 1e5, "slope": 0.0, "l_ref_dbc": -100.0, "f_ref": 9e3},
    ]
    with pytest.raises(ValueError):
        cn.power_law_sigma_phi2(overlap, 1e3, 1e5)  # 重叠
    bad_slope = [
        {"f_lo": 1e3, "f_hi": 1e5, "slope": -2.5, "l_ref_dbc": -100.0, "f_ref": 1e3}
    ]
    with pytest.raises(ValueError):
        cn.power_law_sigma_phi2(bad_slope, 1e3, 1e5)  # 斜率不在族内
    missing = [{"f_lo": 1e3, "f_hi": 1e5, "slope": 0.0, "f_ref": 1e3}]
    with pytest.raises(ValueError):
        cn.power_law_sigma_phi2(missing, 1e3, 1e5)  # 缺 l_ref_dbc
    with pytest.raises(ValueError):
        cn.power_law_l_dbc(1e9, segs)  # 求值越覆盖


# ─── 6. PLL 带内/带外拼接 ─────────────────────────────────────────────────────

_PLL_FLAT = dict(f1=100.0, f2=1e7, f_loop_bw=1e4, in_band={"mode": "flat", "l_dbc": -80.0})


def test_pll_flat_inband_closed_form():
    r = cn.pll_integrate(**_PLL_FLAT)
    l_lin = 10.0 ** (-8.0)
    in_expected = 2.0 * l_lin * (1e4 - 100.0)
    out_expected = 2.0 * l_lin * (1e4**2) * (1.0 / 1e4 - 1.0 / 1e7)  # n=−2 段闭式
    assert r.in_band_rad2 == pytest.approx(in_expected, rel=1e-12)
    assert r.out_band_rad2 == pytest.approx(out_expected, rel=1e-12)
    assert r.total_rad2 == pytest.approx(in_expected + out_expected, rel=1e-12)
    assert r.l_at_loop_bw_dbc == -80.0


def test_pll_stitch_conservation_both_modes():
    r_flat = cn.pll_integrate(**_PLL_FLAT)
    assert r_flat.in_band_rad2 + r_flat.out_band_rad2 == pytest.approx(
        r_flat.total_rad2, rel=1e-12
    )
    segs = cn.build_power_law_segments(l_floor_dbc=-100.0, corners=[(1e3, -2.0)], f_min=10.0, f_max=1e5)
    pl = {"mode": "power_law", "segments": segs}
    r_pl = cn.pll_integrate(50.0, 1e4, 5e3, pl)
    assert r_pl.in_band_rad2 + r_pl.out_band_rad2 == pytest.approx(
        r_pl.total_rad2, rel=1e-12
    )
    # −30 dB/dec（n=−3）滚降同样守恒
    r_30 = cn.pll_integrate(100.0, 1e7, 1e4, {"mode": "flat", "l_dbc": -80.0}, rolloff_db_per_dec=-30.0)
    assert r_30.in_band_rad2 + r_30.out_band_rad2 == pytest.approx(
        r_30.total_rad2, rel=1e-12
    )


def test_pll_powerlaw_inband_matches_kernel():
    # 跨函数恒等：带内贡献 == 幂律内核对同一区间的直接积分（拼接只分区不改谱）
    segs = cn.build_power_law_segments(l_floor_dbc=-100.0, corners=[(1e3, -2.0)], f_min=10.0, f_max=1e5)
    r = cn.pll_integrate(50.0, 1e4, 1e4, {"mode": "power_law", "segments": segs})
    assert r.in_band_rad2 == pytest.approx(
        cn.power_law_sigma_phi2(segs, 50.0, 1e4), rel=1e-12
    )
    assert r.out_band_rad2 == 0.0  # fbw=f2 → 带外零宽


def test_pll_input_guards():
    with pytest.raises(ValueError):
        cn.pll_integrate(1e4, 100.0, 1e3, {"mode": "flat", "l_dbc": -80.0})  # f2<f1
    with pytest.raises(ValueError):
        cn.pll_integrate(100.0, 1e7, 50.0, {"mode": "flat", "l_dbc": -80.0})  # bw<f1
    with pytest.raises(ValueError):
        cn.pll_integrate(100.0, 1e7, 1e8, {"mode": "flat", "l_dbc": -80.0})  # bw>f2
    with pytest.raises(ValueError):
        cn.pll_integrate(100.0, 1e7, 1e4, {"mode": "const", "l_dbc": -80.0})  # 未支持形态
    with pytest.raises(ValueError):
        cn.pll_integrate(100.0, 1e7, 1e4, {"mode": "flat"})  # 缺 l_dbc
    segs = cn.build_power_law_segments(l_floor_dbc=-100.0, corners=[(1e3, -2.0)], f_min=500.0, f_max=1e4)
    with pytest.raises(ValueError):
        cn.pll_integrate(100.0, 1e7, 2e3, {"mode": "power_law", "segments": segs})  # 带内链不盖 f1=100
    with pytest.raises(ValueError):
        cn.pll_integrate(  # −40 dB/dec → n=−4 不在幂律族
            100.0, 1e7, 1e4, {"mode": "flat", "l_dbc": -80.0}, rolloff_db_per_dec=-40.0
        )
    with pytest.raises(ValueError):
        cn.pll_integrate(True, 1e7, 1e4, {"mode": "flat", "l_dbc": -80.0})  # bool 拒收
    with pytest.raises(ValueError):
        cn.pll_integrate(100.0, 1e7, 1e4, "flat")  # in_band 非 dict


def test_pll_zero_and_edge_widths():
    r = cn.pll_integrate(1e4, 1e4, 1e4, {"mode": "flat", "l_dbc": -80.0}, f_carrier=1e9)
    assert r.total_rad2 == 0.0 and r.in_band_rad2 == 0.0 and r.out_band_rad2 == 0.0
    assert r.jitter_s == 0.0
    with pytest.raises(ValueError):
        cn.pll_integrate(1e4, 1e4, 1e5, {"mode": "flat", "l_dbc": -80.0})  # f1=f2 但 bw 不等
    r_bw_lo = cn.pll_integrate(100.0, 1e7, 100.0, {"mode": "flat", "l_dbc": -80.0})
    assert r_bw_lo.in_band_rad2 == 0.0 and r_bw_lo.total_rad2 == pytest.approx(
        r_bw_lo.out_band_rad2, rel=1e-15
    )
    r_bw_hi = cn.pll_integrate(100.0, 1e7, 1e7, {"mode": "flat", "l_dbc": -80.0})
    assert r_bw_hi.out_band_rad2 == 0.0 and r_bw_hi.total_rad2 == pytest.approx(
        r_bw_hi.in_band_rad2, rel=1e-15
    )


# ─── 7. SNR 限值归口与 JSON 面 ────────────────────────────────────────────────


def test_snr_jitter_reference_is_adc_budget_monopoly():
    # 件 5 口径：SNR 限值公式归口件 1（防同式双实现），本模块无 SNR 函数
    assert not hasattr(cn, "snr_limit_db_from_jitter")
    # 件 1 公式独立数值回收：SNR = −20·log10(2π·f_in·σ_j)
    snr = adc_budget.snr_jitter_db(1e9, 1e-13)
    assert snr == pytest.approx(-20.0 * math.log10(2.0 * math.pi * 1e9 * 1e-13), rel=1e-12)


def test_to_dict_json_roundtrip():
    r = cn.phase_jitter_from_l([1e3, 1e6], [-100.0, -100.0], f_carrier=1e9)
    d = json.loads(json.dumps(r.to_dict()))
    assert d["sigma_phi2_rad2"] == pytest.approx(r.sigma_phi2_rad2, rel=1e-15)
    assert d["interp"] == "db_linear" and d["n_segments"] == 1
    pl = cn.pll_integrate(**_PLL_FLAT, f_carrier=1e9)
    dp = json.loads(json.dumps(pl.to_dict()))
    assert dp["in_band_mode"] == "flat" and dp["rolloff_db_per_dec"] == -20.0
    assert dp["total_rad2"] == pytest.approx(pl.total_rad2, rel=1e-15)
    assert dp["jitter_s"] == pytest.approx(pl.jitter_s, rel=1e-15)


# ─── 8. service 薄面（JSON 信封 ok=False 不抛）────────────────────────────────


def test_service_piecewise_envelope():
    payload = {
        "f_edges": [1e3, 1e4, 1e5, 1e6],
        "l_dbc": [-70.0, -95.0, -110.0, -120.0],
        "f_carrier": 1e9,
    }
    out = cns.clock_noise_jitter(payload)
    assert out["ok"] is True and out["model"] == "piecewise"
    core = cn.phase_jitter_from_l(payload["f_edges"], payload["l_dbc"], f_carrier=1e9)
    assert out["result"] == core.to_dict()


def test_service_error_envelopes_no_raise():
    assert cns.clock_noise_jitter({})["ok"] is False  # 全缺
    assert cns.clock_noise_jitter(None)["ok"] is False  # 非 dict
    assert cns.clock_noise_jitter({"model": "bogus"})["ok"] is False
    out = cns.clock_noise_jitter({"f_edges": [1e3, 1e4], "l_dbc": [-90.0], "interp": "nope"})
    assert out["ok"] is False and out["errors"]
    out = cns.clock_noise_jitter({"f_edges": [True, False], "l_dbc": [-90.0]})
    assert out["ok"] is False and out["errors"]  # bool 元素拒收
    out = cns.clock_noise_jitter({"model": "power_law", "l_floor_dbc": -110.0, "f_min": 10.0, "f_max": 1e7})
    assert out["ok"] is False and "corners" in "".join(out["errors"])
    out = cns.clock_noise_jitter({"model": "pll", "f1": 100.0, "f2": 1e7})
    assert out["ok"] is False and out["errors"]  # 缺 f_loop_bw/in_band
    # 数值 0.0 合法性：L=0 dBc/Hz 合法（非缺失），应 ok=True
    out = cns.clock_noise_jitter({"f_edges": [1e3, 1e4], "l_dbc": [0.0], "interp": "const"})
    assert out["ok"] is True and out["result"]["sigma_phi2_rad2"] > 0.0


def test_service_power_law_and_pll_envelopes():
    out = cns.clock_noise_jitter(
        {
            "model": "power_law",
            "l_floor_dbc": -110.0,
            "corners": [[1e3, -3.0], [1e5, -1.0]],
            "f_min": 10.0,
            "f_max": 1e7,
            "f1": 100.0,
            "f2": 1e6,
            "f_carrier": 1e9,
        }
    )
    assert out["ok"] is True
    segs = cn.build_power_law_segments(-110.0, [(1e3, -3.0), (1e5, -1.0)], 10.0, 1e7)
    assert out["result"]["sigma_phi2_rad2"] == pytest.approx(
        cn.power_law_sigma_phi2(segs, 100.0, 1e6), rel=1e-15
    )
    assert out["result"]["jitter_s"] == pytest.approx(
        cn.rms_jitter_s(math.sqrt(out["result"]["sigma_phi2_rad2"]), 1e9), rel=1e-15
    )
    out_pll = cns.clock_noise_jitter(
        {
            "model": "pll",
            "f1": 100.0,
            "f2": 1e7,
            "f_loop_bw": 1e4,
            "in_band": {"mode": "flat", "l_dbc": -80.0},
            "rolloff_db_per_dec": -20.0,
        }
    )
    assert out_pll["ok"] is True
    assert out_pll["result"] == cn.pll_integrate(
        100.0, 1e7, 1e4, {"mode": "flat", "l_dbc": -80.0}, rolloff_db_per_dec=-20.0
    ).to_dict()
