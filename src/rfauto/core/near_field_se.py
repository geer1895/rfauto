"""EM-1 近场屏蔽效能（电/磁偶极源波阻抗修正闭式族）（2026-10-02，round17 EM-1）。

规格：研究扩充 round17 §四 EM-1——磁场源
Z_w=η0·2πr/λ、电场源 Z_w=η0·λ/(2πr)（Ott §6.4/Paul Ch.10）；验收=
Ott 铜箔 0.1mm@1MHz 典型带。

与 QW-11 的关系（rfauto/core/calc_families/shield.py 的
``shielding_effectiveness``，Schelkunoff 平面波三段）：QW-11 是远场
平面波 SE（Z_w=η0，近场源显式拒绝）；本模块把入射波阻抗 Z_w 从 η0
推广到近场源波阻抗（电偶极高阻场 / 磁偶极低阻场），三段机制
（A 吸收 / R 反射 / B 多次反射修正，Schelkunoff TL 类比）与 QW-11
同构。二者公共退化点 = r≥λ/2π（kr≥1）：近场口径在该域显式取
Z_w=η0，SE 逐式与 QW-11 相等（跨模块互证锚
tests/unit/test_near_field_se.py::test_far_field_degeneracy_vs_qw11）。

出处等级（如实标注）：
- 公式结构：Ott《Electromagnetic Compatibility Engineering》2009 §6.4
  近场波阻抗**幅值口径**（|Z_we|=η0·λ/(2πr)≈60λ/r 电场源高阻场、
  |Z_wh|=η0·2πr/λ=ω·μ0·r 磁场源低阻场，有效域 kr<1；kr≥1 即远场取
  η0——Ott dB 简化式同口径）。**页码 UNVERIFIED**（离线环境未核对
  纸面页码；三条 dB 简化式 R_p≈168−10lg(f·μr/σr)、
  R_h≈14.6+10lg(f·r²·σr/μr)、R_e≈322+10lg(σr/(μr·f³·r²)) 与本实现
  全复数式在各自有效域的数值一致性由单测独立钉住）。
- 三段分解：Schelkunoff TL 类比与 QW-11 同构（A 与源无关；R/B 把
  Γ=(Z_s−Z_w)/(Z_s+Z_w) 与嵌入阻抗取广义 Z_w）。A+R+B ≡
  −20lg|S21_ABCD| 恒等式在广义 Z_w 下仍精确成立，由本模块测试的
  ABCD 独立裁判路（Z_w 参数化推广 test_qw10_qw11._se_abcd_independent）
  复钉（|Δ|≤1e-8 dB）。
- 相位口径限制：近场波阻抗取 Ott **幅值**（实数），近场场阻抗的
  ±j 相位未建模——与 Ott dB 简化式同口径；r→λ/2π 时平滑过渡到严格
  平面波口径。深近场（kr≪1）下该近似的误差未量化，如实声明。

纯函数模块（无注册表）：round17 EM-1 未要求 calculator 注册键，
如实保持纯函数（消费面后续需要时再走基类+注册表模式补注册）。
"""

from __future__ import annotations

import cmath
import math
from collections.abc import Sequence
from typing import Any

from rfauto.core.calc_families.rfid import _rfid_num
from rfauto.core.calc_families.shield import _SHIELD_MATERIALS
from rfauto.core.metasurface_lut import C0_M_S, ETA0_OHM, MU0_H_M

__all__ = [
    "SOURCE_ELECTRIC_DIPOLE",
    "SOURCE_MAGNETIC_DIPOLE",
    "SOURCE_PLANE_WAVE",
    "SUPPORTED_SOURCES",
    "absorption_loss_db",
    "multiple_reflection_db",
    "near_field_se",
    "reflection_loss_db",
    "skin_depth_m",
    "source_wave_impedance_ohm",
]

#: 源口径键（与 QW-11 的 source="plane_wave" 键对齐，便于互证）
SOURCE_PLANE_WAVE = "plane_wave"
SOURCE_ELECTRIC_DIPOLE = "electric_dipole"
SOURCE_MAGNETIC_DIPOLE = "magnetic_dipole"
SUPPORTED_SOURCES = (
    SOURCE_PLANE_WAVE,
    SOURCE_ELECTRIC_DIPOLE,
    SOURCE_MAGNETIC_DIPOLE,
)

_D20_LN10 = 20.0 / math.log(10.0)  # 8.685889638…（Np→dB）


def _validate_sigma_mu_r(
    conductivity_s_per_m: float | None,
    mu_r: float,
    material: str | None,
) -> tuple[float, float, str | None]:
    """σ/μr 收敛：直给 σ 优先，材料表次之（与 QW-11 shield.py 同规则）。"""
    mu_r_v = _rfid_num(mu_r, "mu_r")
    if mu_r_v <= 0.0:
        raise ValueError("mu_r 必须 >0")
    if conductivity_s_per_m is not None:
        sigma = _rfid_num(conductivity_s_per_m, "conductivity_s_per_m")
        if sigma <= 0.0:
            raise ValueError("conductivity_s_per_m 必须 >0（σ=0 显式拒绝）")
        return sigma, mu_r_v, None
    if material is not None:
        key = str(material).lower()
        if key not in _SHIELD_MATERIALS:
            raise ValueError(
                f"未知屏蔽材料 {material!r}（可用: {sorted(_SHIELD_MATERIALS)}）")
        sigma_tab, mu_tab = _SHIELD_MATERIALS[key]
        return sigma_tab, mu_tab, key
    raise ValueError("conductivity_s_per_m 与 material 须二选一（都缺显式拒绝）")


def skin_depth_m(frequency_hz: float, conductivity_s_per_m: float,
                 mu_r: float = 1.0) -> float:
    """趋肤深度 δ=√(2/(ωμσ))（良导体口径，与 QW-11 逐式同源）。"""
    f = _rfid_num(frequency_hz, "frequency_hz")
    if f <= 0.0:
        raise ValueError(f"频率必须 >0（f=0 显式拒绝），got {frequency_hz!r}")
    sigma = _rfid_num(conductivity_s_per_m, "conductivity_s_per_m")
    if sigma <= 0.0:
        raise ValueError("conductivity_s_per_m 必须 >0（σ=0 显式拒绝）")
    mu_r_v = _rfid_num(mu_r, "mu_r")
    if mu_r_v <= 0.0:
        raise ValueError("mu_r 必须 >0")
    return math.sqrt(2.0 / (2.0 * math.pi * f * MU0_H_M * mu_r_v * sigma))


def source_wave_impedance_ohm(frequency_hz: float, source: str,
                              distance_m: float | None = None) -> float:
    """源波阻抗幅值 |Z_w|（Ott 幅值口径，实数）。

    - plane_wave：η0（distance 不参与，可省）；
    - electric_dipole（电偶极高阻场）：η0·λ/(2πr)，有效域 kr<1；
    - magnetic_dipole（磁偶极低阻场）：η0·2πr/λ = ω·μ0·r，有效域 kr<1；
    - kr≥1（r≥λ/2π）一律取 η0（远场平面波，近场公式出域即钳位，
      两支在 r=λ/2π 处都精确等于 η0，拼接连续）。
    """
    f = _rfid_num(frequency_hz, "frequency_hz")
    if f <= 0.0:
        raise ValueError(f"频率必须 >0（f=0 显式拒绝），got {frequency_hz!r}")
    key = str(source)
    if key not in SUPPORTED_SOURCES:
        raise ValueError(
            f"未知源口径 {source!r}（可用: {list(SUPPORTED_SOURCES)}）")
    if key == SOURCE_PLANE_WAVE:
        if distance_m is not None:
            r = _rfid_num(distance_m, "distance_m")
            if r <= 0.0:
                raise ValueError("distance_m 必须 >0（提供时显式校验）")
        return ETA0_OHM
    if distance_m is None:
        raise ValueError(
            f"source={key!r} 为近场源，distance_m 必读（源-屏距离，>0）")
    r = _rfid_num(distance_m, "distance_m")
    if r <= 0.0:
        raise ValueError("distance_m 必须 >0（r=0 源点无场阻抗定义）")
    wavelength = C0_M_S / f
    kr = 2.0 * math.pi * r / wavelength
    if kr >= 1.0:
        return ETA0_OHM
    if key == SOURCE_ELECTRIC_DIPOLE:
        return ETA0_OHM * wavelength / (2.0 * math.pi * r)
    return ETA0_OHM * 2.0 * math.pi * r / wavelength


def absorption_loss_db(frequency_hz: float, thickness_m: float,
                       conductivity_s_per_m: float,
                       mu_r: float = 1.0) -> float:
    """吸收损耗 A=(20/ln10)·t/δ（与源口径无关；t=0 精确返回 0.0）。

    允许 t=0（物理恒等 A(t=0)=0，锚测试用）；t<0 显式拒绝。
    """
    t = _rfid_num(thickness_m, "thickness_m")
    if t < 0.0:
        raise ValueError("thickness_m 必须 ≥0（负厚度无物理意义）")
    if t == 0.0:
        return 0.0
    delta = skin_depth_m(frequency_hz, conductivity_s_per_m, mu_r)
    return _D20_LN10 * t / delta


def reflection_loss_db(frequency_hz: float, source: str,
                       distance_m: float | None = None,
                       conductivity_s_per_m: float | None = None,
                       mu_r: float = 1.0,
                       material: str | None = None) -> float:
    """反射损耗 R=20lg|(Z_w+Z_s)²/(4·Z_w·Z_s)|（广义 Z_w 的全复数式）。"""
    sigma, mu_use, _ = _validate_sigma_mu_r(
        conductivity_s_per_m, mu_r, material)
    f = _rfid_num(frequency_hz, "frequency_hz")
    if f <= 0.0:
        raise ValueError(f"频率必须 >0（f=0 显式拒绝），got {frequency_hz!r}")
    z_w = source_wave_impedance_ohm(f, source, distance_m)
    omega = 2.0 * math.pi * f
    z_s = cmath.sqrt(1j * omega * MU0_H_M * mu_use / sigma)
    return 20.0 * math.log10(abs(
        (z_w + z_s) ** 2 / (4.0 * z_w * z_s)))


def multiple_reflection_db(frequency_hz: float, thickness_m: float,
                           source: str, distance_m: float | None = None,
                           conductivity_s_per_m: float | None = None,
                           mu_r: float = 1.0,
                           material: str | None = None) -> float:
    """多次反射修正 B=20lg|1−Γ²e^{−2γt}|（Γ 取广义 Z_w，与 QW-11 同构）。

    允许 t=0（返回 20lg|1−Γ²|，与 R 精确相消使 SE(t=0)→0，物理恒等
    由测试钉住）；t<0 显式拒绝。
    """
    t = _rfid_num(thickness_m, "thickness_m")
    if t < 0.0:
        raise ValueError("thickness_m 必须 ≥0（负厚度无物理意义）")
    sigma, mu_use, _ = _validate_sigma_mu_r(
        conductivity_s_per_m, mu_r, material)
    f = _rfid_num(frequency_hz, "frequency_hz")
    if f <= 0.0:
        raise ValueError(f"频率必须 >0（f=0 显式拒绝），got {frequency_hz!r}")
    z_w = source_wave_impedance_ohm(f, source, distance_m)
    omega = 2.0 * math.pi * f
    delta = math.sqrt(2.0 / (omega * MU0_H_M * mu_use * sigma))
    gamma = (1.0 + 1j) / delta
    z_s = cmath.sqrt(1j * omega * MU0_H_M * mu_use / sigma)
    refl = (z_s - z_w) / (z_s + z_w)
    return 20.0 * math.log10(abs(
        1.0 - refl ** 2 * cmath.exp(-2.0 * gamma * t)))


def _se_point(f: float, t_m: float, sigma: float, mu_r: float,
              source: str, distance_m: float | None) -> dict[str, float]:
    """单频点三段分解（A/R/B 与广义 Z_w；恒等式由 ABCD 裁判路钉住）。"""
    omega = 2.0 * math.pi * f
    delta = math.sqrt(2.0 / (omega * MU0_H_M * mu_r * sigma))
    gamma = (1.0 + 1j) / delta
    z_s = cmath.sqrt(1j * omega * MU0_H_M * mu_r / sigma)
    z_w = source_wave_impedance_ohm(f, source, distance_m)
    se_a = _D20_LN10 * t_m / delta
    se_r = 20.0 * math.log10(abs((z_w + z_s) ** 2 / (4.0 * z_w * z_s)))
    refl = (z_s - z_w) / (z_s + z_w)
    se_b = 20.0 * math.log10(abs(
        1.0 - refl ** 2 * cmath.exp(-2.0 * gamma * t_m)))
    return {
        "skin_depth_m": delta,
        "wave_impedance_ohm": z_w,
        "se_absorption_db": se_a,
        "se_reflection_db": se_r,
        "se_multiple_db": se_b,
        "se_total_db": se_a + se_r + se_b,
    }


def near_field_se(
    frequency_hz: float | None = None,
    f_axis_hz: Sequence[float] | None = None,
    thickness_m: float | None = None,
    source: str = SOURCE_MAGNETIC_DIPOLE,
    distance_m: float | None = None,
    conductivity_s_per_m: float | None = None,
    mu_r: float = 1.0,
    material: str | None = None,
) -> dict[str, Any]:
    """近场源（电/磁偶极）经屏蔽体的 SE 三段闭式（JSON 可序列化 dict）。

    Args:
        frequency_hz: 单点频率 Hz（与 f_axis_hz 二选一，同给显式拒绝）。
        f_axis_hz: 频率轴 Hz 列表（逐点 >0；与 frequency_hz 二选一）。
        thickness_m: 屏蔽体厚度 m（>0；t=0 无屏蔽体）。
        source: 源口径（magnetic_dipole 默认=磁场源最恶劣口径；
            electric_dipole；plane_wave 退化为 QW-11 平面波口径）。
        distance_m: 源-屏距离 m（近场源必读 >0；plane_wave 可省，
            提供 >0 即可，不参与计算）。r≥λ/2π 时近场口径钳位到 η0。
        conductivity_s_per_m: 电导率 S/m（>0；与 material 二选一，直给优先）。
        mu_r: 相对磁导率（>0，默认 1.0；material 命中表时取表值）。
        material: 材料键（copper/aluminum/brass/steel_low_carbon，
            复用 QW-11 _SHIELD_MATERIALS 单源表）。

    Returns:
        dict：{f_hz, source, distance_m, skin_depth_m, wave_impedance_ohm,
        se_absorption_db, se_reflection_db, se_multiple_db, se_total_db
        （均逐频列表）, conductivity_s_per_m, mu_r, material, note}。

    Raises:
        ValueError: 域守卫（f≤0/t≤0/σ≤0/μr≤0/r≤0/源键未知/二选一违例/
            近场源缺 distance_m）全部显式拒绝。
    """
    if str(source) not in SUPPORTED_SOURCES:
        raise ValueError(
            f"未知源口径 {source!r}（可用: {list(SUPPORTED_SOURCES)}）")
    if (frequency_hz is None) == (f_axis_hz is None):
        raise ValueError("frequency_hz 与 f_axis_hz 须二选一（同给/都缺显式拒绝）")
    t_m = _rfid_num(thickness_m, "thickness_m")
    if t_m <= 0.0:
        raise ValueError("thickness_m 必须 >0（t=0 无屏蔽体）")
    sigma, mu_use, material_key = _validate_sigma_mu_r(
        conductivity_s_per_m, mu_r, material)
    if frequency_hz is not None:
        f_list = [_rfid_num(frequency_hz, "frequency_hz")]
    else:
        f_axis = list(f_axis_hz)  # type: ignore[arg-type]
        if not f_axis:
            raise ValueError("f_axis_hz 不能为空")
        f_list = [_rfid_num(v, f"f_axis_hz[{i}]") for i, v in enumerate(f_axis)]
    for i, f_v in enumerate(f_list):
        if f_v <= 0.0:
            raise ValueError(
                f"频率必须 >0（f=0 显式拒绝），f_axis_hz[{i}]={f_v}")
    if source != SOURCE_PLANE_WAVE and distance_m is None:
        raise ValueError(
            f"source={source!r} 为近场源，distance_m 必读（源-屏距离，>0）")
    if distance_m is not None:
        r_v = _rfid_num(distance_m, "distance_m")
        if r_v <= 0.0:
            raise ValueError("distance_m 必须 >0")

    points = [
        _se_point(f_v, t_m, sigma, mu_use, str(source), distance_m)
        for f_v in f_list
    ]
    return {
        "f_hz": [round(float(v), 6) for v in f_list],
        "source": str(source),
        "distance_m": (round(float(distance_m), 12)
                       if distance_m is not None else None),
        "skin_depth_m": [round(float(p["skin_depth_m"]), 15) for p in points],
        "wave_impedance_ohm": [round(float(p["wave_impedance_ohm"]), 9)
                               for p in points],
        "se_absorption_db": [round(float(p["se_absorption_db"]), 9)
                             for p in points],
        "se_reflection_db": [round(float(p["se_reflection_db"]), 9)
                             for p in points],
        "se_multiple_db": [round(float(p["se_multiple_db"]), 9)
                           for p in points],
        "se_total_db": [round(float(p["se_total_db"]), 9) for p in points],
        "conductivity_s_per_m": round(float(sigma), 12),
        "mu_r": round(float(mu_use), 12),
        "material": material_key,
        "note": "EM-1 近场 SE（Ott §6.4 幅值口径：电场源 η0·λ/(2πr)、"
                "磁场源 η0·2πr/λ，kr≥1 钳位 η0；页码 UNVERIFIED）；"
                "三段机制与 QW-11 Schelkunoff 平面波同构，远场退化"
                "一致性由跨模块锚钉住；近场波阻抗相位未建模（幅值口径）",
    }
