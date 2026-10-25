"""天线近/远场区界键（aurora_h W1-K1，R2_core_tier5 §③ 8 提升核）。

提升核：消费 core/near_field_regions.py 全套闭式（Balanis《Antenna
Theory》3rd ed ch.2 p.34 引文实测核对在案；π/8 相位判据几何互证、区界
排序代数域守卫、10D²/λ 测量惯例档 UNVERIFIED 如实标注均已在内核钉死）
——该内核 docstring 自证"service 挂接是后续项"，本键即其 CALC 注册面。

公式（出处与互证路径见 core/near_field_regions.py 模块 docstring，单源
不复制）：反应近场外界（大天线）0.62·√(D³/λ) /（电小天线惯例）λ/(2π)；
辐射近场（Fresnel）窗口 (0.62√(D³/λ), 2D²/λ)；远场（Fraunhofer）下界
d_F = 2·D²/λ（D=天线最大口径尺寸）；π/8 相位判据 Δφ=2π·D²/(8λR)=π/8
⇔ R=2D²/λ（判据的独立几何出处，双路径互证已在内核）；测量惯例
10D²/λ（round17 AP-3 规格点名、独立原始文献 UNVERIFIED——按 #122 如实
标注透传）。

适用域与边界：D=天线最大口径整体尺寸（阵列=全阵口径，非单元）；区界
排序成立域 D ≥ λ/10.406（代数解，域外显式 ValueError——电小天线走
λ/2π 惯例档）；远场球面判据不作近场 SAR/MPE 合规依据（衔接
core/exposure_limits far_field_note 口径）；boundary：exposure_limits
（合规面）、ris_cascade（远场适用性注记消费点）、polarization_reg
（极化度量面）。

锚（#118 独立算术，平移内核锚 + 独立路径，tests/unit/
test_w1k1_core_domains.py）：D=0.5m@10GHz → d_F=16.6782m（Balanis 数值
锚）；λ/2π @1GHz = 0.0477465m；π/8 相位判据 R=πD²/(4λ·π/8) 与 2D²/λ
独立几何换算逐位互证。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator


def _num(value: Any, name: str) -> float:
    """有限数守卫（bool 显式拒收——bool 污染面 df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


@register_calculator(
    "far_field_region",
    "天线远场区界：Fraunhofer 下界 d_F=2D²/λ（Balanis ch.2）+反应近场外界"
    "（大天线 0.62√(D³/λ) / 电小天线 λ/2π 惯例档两口径并显）+Fresnel 区窗"
    "+π/8 相位判据几何互证+测量距离惯例（2D²/λ 与 10D²/λ 档，后者 UNVERIFIED "
    "如实标注）；给 r_m 时附场区分类；D<λ/10.406 区界排序失效域显式拒绝。"
    "单源 core/near_field_regions（提升核注册面）",
    (("d_m", "float m 天线最大口径尺寸 D（>0；阵列=全阵口径）"),
     ("f_hz", "float Hz 工作频率（>0）"),
     ("r_m", "float m 待分类的观察距离（≥0，可选；给定时附 region 分类）")),
    required=("d_m", "f_hz"),
)
def far_field_region(d_m: float, f_hz: float,
                     r_m: float | None = None) -> dict[str, Any]:
    from rfauto.core.near_field_regions import (
        C0_M_S,
        fresnel_region_m,
        measurement_range_m,
        reactive_near_field_small_antenna_m,
    )

    dd = _num(d_m, "d_m")
    if dd <= 0.0:
        raise ValueError(f"far_field_region: d_m 必须 >0，得 {dd}")
    freq = _num(f_hz, "f_hz")
    if freq <= 0.0:
        raise ValueError(f"far_field_region: f_hz 必须 >0，得 {freq}")
    r_val: float | None = None
    if r_m is not None:
        r_val = _num(r_m, "r_m")
        if r_val < 0.0:
            raise ValueError(f"far_field_region: r_m 必须 ≥0，得 {r_val}")

    # 区界排序守卫（D<λ/10.406 显式 ValueError）随 fresnel_region_m 透传
    window = fresnel_region_m(dd, freq)
    lam = C0_M_S / freq
    range_pi8, rule_pi8 = measurement_range_m(dd, freq, rule="pi_8")
    range_ten, rule_ten = measurement_range_m(dd, freq, rule="ten_d2")

    out: dict[str, Any] = {
        "d_m": dd,
        "f_hz": freq,
        "wavelength_m": lam,
        "d_over_lambda": round(dd / lam, 15),
        "fraunhofer_m": window["outer_m"],
        "reactive_large_antenna_m": window["inner_m"],
        "reactive_small_antenna_m": reactive_near_field_small_antenna_m(freq),
        "fresnel_inner_m": window["inner_m"],
        "fresnel_outer_m": window["outer_m"],
        "measurement_range_pi8_m": range_pi8,
        "measurement_range_pi8_rule": rule_pi8,
        "measurement_range_ten_d2_m": range_ten,
        "measurement_range_ten_d2_rule": rule_ten,
        "region": None,
        "criteria_note": (
            "三区判据：r≤0.62√(D³/λ) 反应近场（大天线口径；电小天线用 "
            "λ/2π 惯例档，两口径不静默互切）；0.62√(D³/λ)<r<2D²/λ 辐射"
            "近场（Fresnel）；r≥2D²/λ 远场（Fraunhofer，π/8 相位判据的"
            "几何等价）。附带条件 d_F≫D、d_F≫λ 由调用方自检（Balanis "
            "同源口径）。远场球面判据不作近场 SAR/MPE 合规依据"),
    }
    if r_val is not None:
        from rfauto.core.near_field_regions import classify_region

        out["region"] = classify_region(r_val, dd, freq)
        out["r_m"] = r_val
    return out
