"""F-J.2 蚀刻梯形等效闭式链单测（任务书 §判据）。

裁判口径（#118）：几何恒等式（w_b 恒等式、EF 表往返、双 w_eq 口径自洽
括界）为解析钉；ΔZ 方向恒等式用两条独立裁判——合成单调闭式（Wheeler
宽线形，测试内独立实现）与 skrf HJ 真链（importorskip 如实 skip）——
扫 θ 数组断言单调。UNVERIFIED 面（EF 典型带/bias 带/等效宽度精度口径）
只钉常量存在性与量级，不虚构精度。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import etch_trapezoid as et

# ─── 1. 几何恒等式 ───────────────────────────────────────────────────────────


def test_bottom_width_identity_exact():
    # w_b = w_t + 2·t·tanθ：与手写同式逐位一致（同一浮点运算序）
    for theta in (0.0, 8.13, 26.565, 45.0, 60.0):
        got = et.bottom_width_mm(0.3, 0.035, theta)
        expect = 0.3 + 2.0 * 0.035 * math.tan(math.radians(theta))
        assert got == expect
    # θ=0 ⟹ 矩形：w_b == w_t 逐位
    assert et.bottom_width_mm(0.3, 0.035, 0.0) == 0.3


def test_angle_widths_round_trip():
    # 反演 θ = atan2(w_b−w_t, 2t)：bottom_width → angle 往返回原 θ
    for theta in (1.0, 15.0, 33.69, 45.0, 70.0, 89.0):
        w_b = et.bottom_width_mm(0.25, 0.0175, theta)
        assert et.etch_angle_deg_from_widths(0.25, w_b, 0.0175) == pytest.approx(theta, rel=1e-12)


def test_ef_undercut_round_trip():
    # EF 表往返：undercut = t/EF、EF = t/undercut
    for ef in (1.5, 2.0, 3.0, 4.7):
        u = et.undercut_from_etch_factor(0.035, ef)
        assert et.etch_factor_from_undercut(0.035, u) == pytest.approx(ef, rel=1e-12)
    # 手算钉：35µm 铜、EF=2 ⟹ 单侧咬蚀 17.5µm
    assert et.undercut_from_etch_factor(0.035, 2.0) == pytest.approx(0.0175, rel=1e-15)


def test_ef_angle_identity():
    # tanθ = 1/EF ⟹ θ = atan(1/EF)；EF=1 ⟹ 45°（解析钉）；往返自洽
    assert et.etch_angle_deg_from_etch_factor(1.0) == pytest.approx(45.0, rel=1e-12)
    for ef in (1.5, 2.0, 3.0):
        theta = et.etch_angle_deg_from_etch_factor(ef)
        assert 1.0 / math.tan(math.radians(theta)) == pytest.approx(ef, rel=1e-12)


def test_ef_typical_band_constants():
    # 业界典型带常量（UNVERIFIED 二手口径——只钉存在性与量级，不虚构精度）
    assert et.ETCH_FACTOR_TYPICAL == (1.5, 3.0)
    assert et.ETCH_FACTOR_TYPICAL[0] < et.ETCH_FACTOR_TYPICAL[1]
    # EF 典型带对应的 θ 域（1.5→33.7°、3→18.4°，均在 [0,90) 内）
    for ef in et.ETCH_FACTOR_TYPICAL:
        assert 0.0 < et.etch_angle_deg_from_etch_factor(ef) < 90.0


# ─── 2. 等效宽度双口径 ───────────────────────────────────────────────────────


def test_equivalent_widths_area_mean_identity():
    # 等面积口径 w_eq = A/t ≡ (w_t+w_b)/2（对梯形与均值恒等，逐位）
    for theta in (0.0, 20.0, 45.0, 80.0):
        w_b = et.bottom_width_mm(0.2, 0.035, theta)
        widths = et.equivalent_widths(0.2, w_b, 0.035)
        assert widths.w_eq_area_mm == 0.5 * (0.2 + w_b)
        # A = w_eq·t（等面积定义恒等式）
        area = 0.5 * (0.2 + w_b) * 0.035
        assert widths.w_eq_area_mm * 0.035 == pytest.approx(area, rel=1e-15)


def test_equivalent_widths_perimeter_closed_form():
    # 等周长口径独立推导：2(w+t) = w_t+w_b+2·(t/cosθ) ⟹ w = mean + t/cosθ − t
    theta = 45.0
    w_t, t = 0.2, 0.035
    w_b = et.bottom_width_mm(w_t, t, theta)
    s = t / math.cos(math.radians(theta))
    expect = 0.5 * (w_t + w_b) + s - t
    widths = et.equivalent_widths(w_t, w_b, t)
    assert widths.w_eq_perimeter_mm == pytest.approx(expect, rel=1e-12)
    # θ=0（矩形）⟹ 双口径重合（逐位）
    rect = et.equivalent_widths(0.3, 0.3, 0.035)
    assert rect.w_eq_perimeter_mm == rect.w_eq_area_mm


def test_equivalent_widths_bracket():
    # 双口径均落 [min(w_t,w_b), max(w_t,w_b)]（几何恒等式，θ 扫描）
    for theta in (1.0, 10.0, 30.0, 45.0, 60.0, 85.0):
        w_b = et.bottom_width_mm(0.2, 0.035, theta)
        widths = et.equivalent_widths(0.2, w_b, 0.035)
        assert 0.2 < widths.w_eq_area_mm < w_b
        assert 0.2 < widths.w_eq_perimeter_mm < w_b
    # 翻转梯形（负蚀刻形态，w_t > w_b）同样括界
    flipped = et.equivalent_widths(0.4, 0.2, 0.035)
    assert 0.2 < flipped.w_eq_area_mm < 0.4
    assert 0.2 < flipped.w_eq_perimeter_mm < 0.4


# ─── 3. 输入守卫 ─────────────────────────────────────────────────────────────


def test_input_guards_valueerror():
    # 负厚度/θ∉[0,90)/w≤0/NaN/bool → ValueError（bool 显式拒收 df7+⑯）
    with pytest.raises(ValueError):
        et.bottom_width_mm(0.3, -0.035, 30.0)
    with pytest.raises(ValueError):
        et.bottom_width_mm(0.3, 0.0, 30.0)
    with pytest.raises(ValueError):
        et.bottom_width_mm(-0.3, 0.035, 30.0)
    with pytest.raises(ValueError):
        et.bottom_width_mm(0.3, 0.035, -0.1)
    with pytest.raises(ValueError):
        et.bottom_width_mm(0.3, 0.035, 90.0)  # 开区间上界
    with pytest.raises(ValueError):
        et.bottom_width_mm(0.3, 0.035, float("nan"))
    with pytest.raises(ValueError):
        et.bottom_width_mm(True, 0.035, 30.0)
    with pytest.raises(ValueError):
        et.equivalent_widths(0.0, 0.3, 0.035)
    with pytest.raises(ValueError):
        et.etch_angle_deg_from_widths(0.3, 0.2, 0.035)  # 顶宽底窄不在几何域
    with pytest.raises(ValueError):
        et.undercut_from_etch_factor(0.035, 0.0)
    with pytest.raises(ValueError):
        et.etch_factor_from_undercut(0.035, True)


# ─── 4. 名义宽→梯形装配 ──────────────────────────────────────────────────────


def test_trapezoid_from_nominal():
    # 底宽=名义（抗蚀开口）、顶宽=名义−2u；θ = atan(u/t) 手算钉
    spec = et.trapezoid_from_nominal(0.3, 0.035, 0.005)
    assert spec.w_bottom_mm == 0.3
    assert spec.w_top_mm == 0.3 - 2.0 * 0.005
    assert spec.etch_angle_deg == pytest.approx(math.degrees(math.atan(0.005 / 0.035)), rel=1e-12)
    # u=0 ⟹ 矩形（θ=0 逐位）
    assert et.trapezoid_from_nominal(0.3, 0.035, 0.0).etch_angle_deg == 0.0
    # 守卫：u ≥ w/2（顶宽归零）与负 undercut → ValueError
    with pytest.raises(ValueError):
        et.trapezoid_from_nominal(0.3, 0.035, 0.15)
    with pytest.raises(ValueError):
        et.trapezoid_from_nominal(0.3, 0.035, -0.001)


def test_spec_validate_and_to_dict():
    # EtchTrapezoidSpec 域守卫 + JSON 面
    spec = et.EtchTrapezoidSpec(0.29, 0.3, 0.035).validate()
    assert spec.to_dict()["etch_angle_deg"] == pytest.approx(spec.etch_angle_deg, rel=1e-15)
    with pytest.raises(ValueError):
        et.EtchTrapezoidSpec(0.31, 0.3, 0.035).validate()  # 顶宽底窄（正蚀刻域外）
    with pytest.raises(ValueError):
        et.EtchTrapezoidSpec(0.0, 0.3, 0.035).validate()
    payload = json.dumps(spec.to_dict())  # JSON 可序列化
    assert "w_top_mm" in payload


# ─── 5. ΔZ 方向恒等式（双裁判扫描 θ）─────────────────────────────────────────


def _wheeler_wide_z0(w_mm: float) -> float:
    """测试内独立实现的合成单调裁判（Wheeler 宽线分支，u→宽线域）。"""
    h = 0.254
    u = w_mm / h
    return 120.0 * math.pi / (u + 1.393 + 0.667 * math.log(u + 1.444))


def test_delta_z_direction_monotone_synthetic():
    # 方向恒等式：θ>0（顶窄）⟹ dz>0 且对 θ 严格单调升（合成裁判）。
    # 扫描域限物理域：u = t·tanθ < w/2（θ=80° 时 u=0.199>w/2 顶宽塌陷，
    # 属显式 ValueError 域，见文件尾守卫钉）。
    prev = -1.0
    for theta in (5.0, 10.0, 20.0, 30.0, 45.0, 60.0):
        res = et.delta_z_estimate(0.3, 0.035, theta, _wheeler_wide_z0)
        assert res.dz_area_ohm > 0.0
        assert res.dz_perimeter_ohm > 0.0
        assert res.direction == "up"
        assert res.dz_area_ohm > prev
        prev = res.dz_area_ohm
    # θ=0 ⟹ dz == 0 逐位（w_eq == w_nominal）
    zero = et.delta_z_estimate(0.3, 0.035, 0.0, _wheeler_wide_z0)
    assert zero.dz_area_ohm == 0.0
    assert zero.dz_perimeter_ohm == 0.0
    assert zero.direction == "zero"
    # z0_nominal 与裁判直代一致（链路装配核对）
    assert zero.z0_nominal_ohm == pytest.approx(_wheeler_wide_z0(0.3), rel=1e-15)
    # 顶宽塌陷域（u = t·tanθ ≥ w/2）显式 ValueError
    with pytest.raises(ValueError):
        et.delta_z_estimate(0.3, 0.035, 80.0, _wheeler_wide_z0)


def test_delta_z_negative_etch_down():
    # 负蚀刻（电镀增宽）⟹ dz<0、direction="down"；u=0 ⟹ 矩形零差
    res = et.delta_z_signed_undercut(0.3, 0.035, -0.005, _wheeler_wide_z0)
    assert res.dz_area_ohm < 0.0
    assert res.direction == "down"
    assert res.w_eq.w_top_mm == 0.3 + 2.0 * 0.005  # 顶宽=名义+2|u|
    pos = et.delta_z_signed_undercut(0.3, 0.035, 0.005, _wheeler_wide_z0)
    assert pos.dz_area_ohm > 0.0 and pos.undercut_mm == 0.005
    zero = et.delta_z_signed_undercut(0.3, 0.035, 0.0, _wheeler_wide_z0)
    assert zero.dz_area_ohm == 0.0
    with pytest.raises(ValueError):
        et.delta_z_signed_undercut(0.3, 0.035, 0.15, _wheeler_wide_z0)  # u ≥ w/2


def test_delta_z_default_chain_skrf():
    # 缺省链 = 既有 core/synthesis.forward_z0（skrf HJ，只读复用）
    pytest.importorskip("skrf")
    res = et.delta_z_estimate(0.3, 0.035, 30.0, None, h_sub_mm=0.254, er_sub=4.4)
    assert res.dz_area_ohm > 0.0 and res.direction == "up"
    assert res.dz_perimeter_ohm > 0.0
    # 方向对 θ 严格单调升（真链裁判）
    prev = -1.0
    for theta in (10.0, 30.0, 60.0):
        dz = et.delta_z_estimate(0.3, 0.035, theta, None, h_sub_mm=0.254, er_sub=4.4).dz_area_ohm
        assert dz > prev
        prev = dz


def test_delta_z_default_chain_missing_params():
    # 判缺失一律 is not None（#364④）：z0_of=None 且层叠参数缺 → ValueError
    with pytest.raises(ValueError):
        et.delta_z_estimate(0.3, 0.035, 30.0, None)
    with pytest.raises(ValueError):
        et.delta_z_estimate(0.3, 0.035, 30.0, None, h_sub_mm=0.254)  # er_sub 缺
    with pytest.raises(ValueError):
        et.delta_z_estimate(0.3, 0.035, 30.0, None, er_sub=4.4)  # h_sub_mm 缺


# ─── 6. ΔZ 结果 JSON 面 ──────────────────────────────────────────────────────


def test_delta_z_result_to_dict_json():
    res = et.delta_z_estimate(0.3, 0.035, 20.0, _wheeler_wide_z0)
    payload = res.to_dict()
    assert json.loads(json.dumps(payload)) == json.loads(json.dumps(payload))
    assert payload["direction"] == "up"
    assert payload["undercut_mm"] == pytest.approx(0.035 * math.tan(math.radians(20.0)), rel=1e-15)
    assert payload["w_eq"]["w_eq_area_mm"] == pytest.approx(payload["w_eq"]["w_eq_area_mm"], 1e-15)


# ─── 7. 版图 etch bias 补偿 ──────────────────────────────────────────────────


def test_etch_bias_compensation():
    # 预补偿闭式：w_design = w_target − bias；往返恒等式
    design = et.etch_bias_compensation(0.300, 0.010)
    assert design == pytest.approx(0.290, rel=1e-15)
    assert design + 0.010 == pytest.approx(0.300, rel=1e-12)
    # 负 bias（咬蚀收窄）⟹ 设计预放宽
    assert et.etch_bias_compensation(0.300, -0.008) == pytest.approx(0.308, rel=1e-15)
    with pytest.raises(ValueError):
        et.etch_bias_compensation(0.0, 0.01)
    with pytest.raises(ValueError):
        et.etch_bias_compensation(0.3, float("inf"))


def test_etch_bias_typical_band_constants():
    # 0.5-1 mil 表（UNVERIFIED 二手口径——只钉常量与 mil→mm 换算）
    assert et.ETCH_BIAS_TYPICAL_MIL == (0.5, 1.0)
    assert et.MIL_TO_MM == 0.0254
    half_mil_mm = 0.5 * et.MIL_TO_MM
    one_mil_mm = 1.0 * et.MIL_TO_MM
    assert half_mil_mm == pytest.approx(0.0127, rel=1e-15)
    assert one_mil_mm == pytest.approx(0.0254, rel=1e-15)
