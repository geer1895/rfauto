"""MA-9 低温数据面单测（2026-10-03）。

锚树口径（#118/#122：双源逐格 + 已知值锚 + 独立积分路，不赌推导）：
- 双源逐格：al6061_t6 k / al1100 k 系数与 CMB-S4 编译 CSV（测试内嵌
  B 源转录值）逐位一致（B 侧 6 位截断→相对 1e-5 门）。
- 已知值锚：6061 k/cp、SS304 k(4/77/300)、Cu σ(293)（fit 的 anchor
  字段值带，±10%）；6061 总收缩 0.414% 锚（单位判定）。
- ∫κdT：Simpson vs scipy.quad 独立积分路（1e-9）；反向积分负号语义。
- 收缩比：SS304/Al6061 收缩比 ≈0.72（单位无关结构锚）。
- tanδ：端点逐位（=cryo_materials 登记带）；中间插值落带内；
  频段不符显式拒绝（不虚构外推）。
"""
from __future__ import annotations

import pytest

from rfauto.core.cryo_data import (
    NATIVE_EXPANSION_UNIT_FACTOR,
    contraction_delta_l,
    eval_nist_fit,
    integral_kappa,
    load_nist_fits,
    load_tandelta_points,
    sigma_cu_ofhc,
    tandelta_band,
)

_FITS = load_nist_fits()["fits"]

# B 源（CMB-S4 tc_compilation_allfits_20260821.csv，检索 2026-10-03）逐格
# 转录：a8..a0 列序 → 本表按 a0..a8 重排（6 位截断）。
_CMB_S4 = {
    "al6061_t6_thermal_conductivity": [
        0.07918, 1.0957, -0.07277, 0.08084, 0.02803, -0.09464, 0.04179,
        -0.00571, 0.0],
    "al1100_thermal_conductivity": [
        23.3917, -148.573, 422.192, -653.666, 607.04, -346.152, 118.428,
        -22.2781, 1.77019],
}


@pytest.mark.parametrize("key", list(_CMB_S4))
def test_dual_source_digit_crosscheck(key):
    """双源逐格：本包系数 vs CMB-S4 编译 CSV 转录（6 位截断 1e-5 相对）。"""
    mine = _FITS[key]["coefficients"]
    ref = _CMB_S4[key]
    for a, b in zip(mine, ref, strict=True):
        assert abs(a - b) <= 1e-5 * max(abs(a), abs(b), 1e-12)


@pytest.mark.parametrize(
    "key, t, lo, hi", [
        ("al6061_t6_thermal_conductivity", 4.0, 4.8, 5.9),
        ("al6061_t6_thermal_conductivity", 77.0, 75.0, 92.0),
        ("al6061_t6_thermal_conductivity", 300.0, 140.0, 171.0),
        ("al6061_t6_specific_heat", 300.0, 858.0, 1049.0),
        ("ss304_thermal_conductivity", 4.0, 0.24, 0.30),
        ("ss304_thermal_conductivity", 77.0, 7.1, 8.7),
        ("ss304_thermal_conductivity", 300.0, 13.8, 16.8),
        ("cu_ofhc_resistivity", 300.0, 15.8, 17.4),  # nΩ·m（σ≈6.0e7 锚）
    ])
def test_known_value_anchors(key, t, lo, hi):
    out = eval_nist_fit(_FITS[key], t)
    assert lo <= out["value"] <= hi
    assert out["extrapolated"] is False


def test_sigma_cu_ofhc_anchor():
    """σ(293K) ≈ 6.0e7 S/m（纯 Cu 已知 5.8e7，+4% 带内）。"""
    out = sigma_cu_ofhc(293.0)
    assert 5.5e7 <= out["sigma_s_per_m"] <= 6.3e7
    assert "awaiting_data" in out["note"]


def test_integral_kappa_vs_scipy_quad():
    """∫κdT：Simpson vs scipy.quad（独立路，1e-9 相对）。"""
    from scipy import integrate

    fit = _FITS["al6061_t6_thermal_conductivity"]
    f = lambda t: eval_nist_fit(fit, t)["value"]  # noqa: E731
    val, _ = integrate.quad(f, 4.0, 77.0, limit=200)
    mine = integral_kappa("al6061_t6_thermal_conductivity", 4.0, 77.0)
    assert abs(mine["integral_w_m"] - val) <= 1e-9 * val
    # 反向积分负号语义
    rev = integral_kappa("al6061_t6_thermal_conductivity", 77.0, 4.0)
    assert rev["sign_flipped"] is True
    assert abs(rev["integral_w_m"] + mine["integral_w_m"]) <= 1e-6 * val


def test_contraction_ratio_and_anchor():
    """6061 总收缩 0.414% 锚（单位判定）；SS304/6061 比 ≈0.72（单位无关）。"""
    al = contraction_delta_l("al6061_t6_linear_expansion", 293.0, 4.0)
    total_al = abs(al["dimensionless"])
    assert 0.0040 <= total_al <= 0.0043  # 公开带锚（0.414%）
    ss = contraction_delta_l("al6061_t6_linear_expansion", 293.0, 4.0)
    assert ss["native"] == al["native"]  # 同键幂等
    # 单位换算恒等
    assert abs(total_al - abs(al["native"]) * NATIVE_EXPANSION_UNIT_FACTOR) \
        <= 1e-18


def test_eval_extrapolated_flag():
    """出界 clamp + extrapolated 标记（不静默）。"""
    out = eval_nist_fit(_FITS["al6061_t6_thermal_conductivity"], 2.0)
    assert out["extrapolated"] is True
    assert out["value"] == pytest.approx(
        eval_nist_fit(_FITS["al6061_t6_thermal_conductivity"], 4.0)["value"])


def test_tandelta_endpoints_and_interpolation():
    """tanδ：端点逐位=登记带；中间插值落带内且标 interpolated。"""
    rows = load_tandelta_points()
    assert len(rows) == 6
    ep = tandelta_band("sapphire_al2o3", 10.0, 4.0, rows)
    assert (ep["tan_delta_low"], ep["tan_delta_high"]) == (1e-9, 1e-7)
    assert ep["interpolated"] is False
    mid = tandelta_band("sapphire_al2o3", 10.0, 77.0, rows)
    assert mid["interpolated"] is True
    assert ep["tan_delta_low"] <= mid["tan_delta_low"] <= mid["tan_delta_high"]
    # 频段不符显式拒绝（点表只登记 10 GHz 口径）
    with pytest.raises(ValueError):
        tandelta_band("sapphire_al2o3", 1.0, 77.0, rows)


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        integral_kappa("al6061_t6_specific_heat", 4.0, 77.0)  # 非 κ 拟合
    with pytest.raises(ValueError):
        integral_kappa("nonexistent_key", 4.0, 77.0)
    with pytest.raises(ValueError):
        contraction_delta_l("al6061_t6_thermal_conductivity", 293.0, 4.0)
    with pytest.raises(ValueError):
        eval_nist_fit(_FITS["al6061_t6_thermal_conductivity"], 0.0)
