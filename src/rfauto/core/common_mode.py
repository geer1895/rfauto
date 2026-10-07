"""EM-5 共模深水件 ①③：接地拓扑频域判据 + 浮地-机壳耦合电容路径（2026-10-02）。

规格：研究扩充 round17 §四 EM-5 共模深水三件——
本模块承载其中两件：
- ① 接地拓扑频域判据（间距<λ/20）：接地点/绑接间距在关注频点小于 λ/20
  → 各接地点近似等电位（不显著抬升共模电压）；越过 λ/20 → 地结构电长化
  （驻波/谐振抬升地弹，成为共模驱动源）。
- ③ 浮地-机壳耦合电容路径接 emc_radiated I_CM 入口：浮地参考平面经寄生
  电容对机壳耦合，CM 电压源（地弹/开关噪声）经 CM 回路（路径电感 L +
  机壳耦合电容 C + 回路电阻 R）产生 I_CM，直接喂给既有
  ``emc_radiated.cm_radiated_field`` 的 ``i_cm_ua`` 入口（复用其 Ott 式
  双路径/偶极上限/限值叠加全链，不重复实现）。

第三件（磁珠模型 R//L+C）在 core/vendor_passives.py（ferrite_bead 类型扩展，
见该模块 EM-5 注记）。

公式与单位口径（逐项钉死）：

1. **接地拓扑判据**：s < λ/20，λ = c/f；临界频率 f_crit = c/(20·s)。
   判据的数学恒等面（s < λ/20 ⟺ f < f_crit，严格不等号）由单测独立钉；
   等号点（s = λ/20）按规格字面归"电长"侧（不凑容差）。
   出处等级（如实标注）：λ/20 是 Ott《Electromagnetic Compatibility
   Engineering》2009 接地章 / Paul《Introduction to EMC》的工程惯例口径
   （**页码 UNVERIFIED**，同 near_field_se 诚实登记先例）；本模块锚的是
   恒等式与边界语义，不赌文献数值。

2. **浮地-机壳耦合电容**：C = ε0·εr·A/d（平行板闭式，忽略边缘场 → 下限
   口径；d≪面尺度时成立）。ε0 取 metasurface_lut.EPS0_F_M（与既有内核
   同源常数面）。

3. **CM 回路**：V_cm（浮地-机壳间共模电压源）→ 路径电感 L（电缆/走线）
   → 机壳耦合电容 C → 回。回路阻抗 Z = R + j(ωL − 1/(ωC))，
   I = V/|Z|；路径 B（有理化恒等式）：I = V·ωC/|1 − ω²LC + jωRC|。
   两路径代数恒等（差仅浮点序 ~1e-15，#118 双路径口径，预声明 ±3 dB 工程带
   的实测值如实报告）。串联谐振 f0 = 1/(2π√(LC)) 处 I = V/R（损耗限幅）；
   f=0 → I=0 恒等（浮地：C 隔直——浮地的定义面）。

4. **辐射链**：I_CM(µA) 喂 ``emc_radiated.cm_radiated_field``（Ott 短偶极
   式 + 镜像 + 偶极上限 + 限值面全部复用既有内核）；本模块只负责"从
   浮地耦合几何到 I_CM 数值"这一段，辐射判读不重复实现。

纯函数模块（无注册表）：round17 EM-5 未要求 calculator 注册键，如实保持
纯函数（EM-1/EM-2/EM-4 同款约定）。零 IO；数值 0.0 合法（判缺失一律
``is not None``，#364④）；bool 显式拒收（df7+⑯）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from rfauto.core.emc_radiated import cm_radiated_field as _cm_radiated_field
from rfauto.core.metasurface_lut import C0_M_S, EPS0_F_M

__all__ = [
    "DUAL_PATH_BAND_DB",
    "LAMBDA20",
    "CommonModeRadiatedBudget",
    "FloatingGroundCmResult",
    "GroundSpacingCriterionResult",
    "chassis_coupling_capacitance",
    "cm_radiated_via_chassis",
    "floating_ground_cm_current",
    "ground_spacing_criteria",
    "ground_spacing_criterion",
    "grounding_critical_frequency_hz",
    "max_ground_spacing_m",
]

#: λ/20 工程惯例因子（Ott/Paul 接地拓扑口径；分母）。
LAMBDA20 = 20.0

#: 双路径一致带预声明（dB，工程带；实际代数恒等 ~1e-15，登记用上界）。
DUAL_PATH_BAND_DB = 3.0

_VERDICT_EQUIPOTENTIAL = "equipotential"
_VERDICT_ELECTRICALLY_LONG = "electrically_long"


# ── 入参守卫（emc_radiated.py 同款，bool 显式拒收）────────────────────────────


def _finite(value: object, name: str) -> float:
    """有限实数守卫（拒 bool）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _nonneg(value: object, name: str) -> float:
    """非负有限实数守卫（0 合法面：f=0→I=0、V=0→I=0 是恒等锚）。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须为非负数（负值无物理意义），实际 {value!r}")
    return out


def _positive(value: object, name: str) -> float:
    """正有限实数守卫。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正数，实际 {value!r}")
    return out


def _db_amplitude(ratio: float) -> float:
    """幅度 dB = 20·log10(ratio)（ratio≥0；0 → −inf 如实返回）。"""
    if ratio == 0.0:
        return -math.inf
    return 20.0 * math.log10(ratio)


# ── 件①：接地拓扑频域判据（间距<λ/20）───────────────────────────────────────


def max_ground_spacing_m(f_mhz: float) -> float:
    """给定频点的最大接地点间距 λ/20（m）＝c/(20·f)。

    Args:
        f_mhz: 频率 MHz（>0；DC 域判据无定义——直流地恒等电位是平凡域）。

    Returns:
        λ/20（m）。
    """
    f = _positive(f_mhz, "f_mhz")
    return C0_M_S / (LAMBDA20 * f * 1e6)


def grounding_critical_frequency_hz(spacing_m: float) -> float:
    """给定间距的判据临界频率 f_crit = c/(20·s)（Hz）。

    f < f_crit ⟺ s < λ/20（严格不等号恒等式，单测独立钉）。
    """
    s = _positive(spacing_m, "spacing_m")
    return C0_M_S / (LAMBDA20 * s)


@dataclass(frozen=True)
class GroundSpacingCriterionResult:
    """接地间距频域判据结果（JSON 可序列化，to_dict 面供 service/CLI）。"""

    spacing_m: float
    f_mhz: float
    wavelength_m: float
    lambda20_m: float  # 该频点最大允许间距 λ/20
    spacing_over_lambda20: float  # s/(λ/20)；<1 合规
    critical_f_mhz: float  # f_crit = c/(20·s)
    verdict: str  # "equipotential" | "electrically_long"
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {
            "model": "ground_spacing_lambda20",
            "spacing_m": self.spacing_m,
            "f_mhz": self.f_mhz,
            "wavelength_m": self.wavelength_m,
            "lambda20_m": self.lambda20_m,
            "spacing_over_lambda20": self.spacing_over_lambda20,
            "critical_f_mhz": self.critical_f_mhz,
            "verdict": self.verdict,
            "lambda20_factor": LAMBDA20,
            "notes": list(self.notes),
        }


def ground_spacing_criterion(spacing_m: float, f_mhz: float) -> GroundSpacingCriterionResult:
    """接地拓扑频域判据：接地点/绑接间距 s 是否满足 s < λ/20（Ott/Paul 口径）。

    verdict 严格判（规格字面"间距<λ/20"）：s < λ/20 → "equipotential"
    （等电位，接地点间无显著 CM 电压）；s ≥ λ/20（含等号点）→
    "electrically_long"（地结构电长化——驻波/谐振抬升地弹，成为 CM 驱动源；
    此时按件③路径评估 CM 电流与辐射预算）。

    Args:
        spacing_m: 接地点间距 m（>0）。
        f_mhz: 关注频率 MHz（>0）。

    Returns:
        GroundSpacingCriterionResult（to_dict 面 JSON 可序列化）。
    """
    s = _positive(spacing_m, "spacing_m")
    f = _positive(f_mhz, "f_mhz")
    wavelength = C0_M_S / (f * 1e6)
    lambda20 = wavelength / LAMBDA20
    notes = (
        "λ/20 工程惯例口径（Ott EMC Engineering 2009 接地章/Paul Intro to EMC；"
        "页码 UNVERIFIED，恒等面 s<λ/20 ⟺ f<c/(20s) 由单测独立钉）",
        "等号点 s=λ/20 归 electrically_long（严格不等号，不凑容差）",
        "electrically_long 判定后按 cm_radiated_via_chassis 评估 CM 电流与辐射预算",
    )
    return GroundSpacingCriterionResult(
        spacing_m=s,
        f_mhz=f,
        wavelength_m=wavelength,
        lambda20_m=lambda20,
        spacing_over_lambda20=s / lambda20,
        critical_f_mhz=grounding_critical_frequency_hz(s) / 1e6,
        verdict=_VERDICT_EQUIPOTENTIAL if s < lambda20 else _VERDICT_ELECTRICALLY_LONG,
        notes=notes,
    )


# ── 件③：浮地-机壳耦合电容路径 → I_CM 入口 ──────────────────────────────────


def chassis_coupling_capacitance(
    area_m2: float,
    distance_m: float,
    er: float = 1.0,
) -> float:
    """浮地平面-机壳寄生电容（平行板闭式下限口径）：C = ε0·εr·A/d（F）。

    忽略边缘场 → 实际电容 ≥ 本值（下限口径）；d≪面尺度时近似成立。

    Args:
        area_m2: 浮地平面与机壳正对面积 m²（>0）。
        distance_m: 间距 m（>0）。
        er: 相对介电常数（>=1；空气 1.0、FR4 ~4.4）。

    Returns:
        C（F）。
    """
    a = _positive(area_m2, "area_m2")
    d = _positive(distance_m, "distance_m")
    er_v = _finite(er, "er")
    if er_v < 1.0:
        raise ValueError(f"er 必须 >=1（非负相对介电常数物理下限），实际 {er!r}")
    return EPS0_F_M * er_v * a / d


@dataclass(frozen=True)
class FloatingGroundCmResult:
    """浮地-机壳 CM 回路结果（JSON 可序列化）。"""

    f_mhz: float
    v_cm_v: float
    c_f: float
    l_path_h: float
    r_path_ohm: float
    z_path_abs_ohm: float
    i_cm_ua: float
    i_cm_a_path_b: float  # 路径 B（有理化恒等式）独立复算值（A）
    dual_path_diff_db: float
    resonance_f_mhz: float | None  # 串联谐振 f0=1/(2π√(LC))；l=0 → None
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {
            "model": "floating_ground_cm_loop",
            "f_mhz": self.f_mhz,
            "v_cm_v": self.v_cm_v,
            "c_f": self.c_f,
            "l_path_h": self.l_path_h,
            "r_path_ohm": self.r_path_ohm,
            "z_path_abs_ohm": self.z_path_abs_ohm,
            "i_cm_ua": self.i_cm_ua,
            "i_cm_a_path_b": self.i_cm_a_path_b,
            "dual_path_diff_db": self.dual_path_diff_db,
            "dual_path_band_db": DUAL_PATH_BAND_DB,
            "resonance_f_mhz": self.resonance_f_mhz,
            "notes": list(self.notes),
        }


def floating_ground_cm_current(
    f_mhz: float,
    v_cm_v: float,
    c_f: float,
    l_path_h: float = 0.0,
    r_path_ohm: float = 0.0,
) -> FloatingGroundCmResult:
    """浮地-机壳耦合电容路径的 CM 电流（串联回路闭式）。

    回路：V_cm（浮地-机壳间 CM 电压源，地弹/开关噪声）→ 路径电感 L →
    机壳耦合电容 C → 回。回路阻抗 Z = R + j(ωL − 1/(ωC))。

    - 路径 A：I = V/|Z|；
    - 路径 B（有理化恒等式）：I = V·ωC/|1 − ω²LC + jωRC|（#118 双路径，
      代数恒等，实测差 ~1e-15 dB）。
    - f=0 → I=0 恒等（浮地 C 隔直——定义面）。
    - 串联谐振 f0=1/(2π√(LC))（L>0 时报告）：I = V/R（损耗限幅）；
      R=0 且恰在谐振 → |Z|=0 非物理 → ValueError（谐振电流须有有限损耗界定）。

    Args:
        f_mhz: 频率 MHz（>=0；0 → I=0）。
        v_cm_v: CM 电压源幅值 V（>=0；0 → I=0）。
        c_f: 浮地-机壳耦合电容 F（>0；可由 chassis_coupling_capacitance 估）。
        l_path_h: CM 回路路径电感 H（>=0；电缆/走线，缺省 0=纯容性）。
        r_path_ohm: CM 回路电阻 Ω（>=0；谐振点必须有非零 R）。

    Returns:
        FloatingGroundCmResult（i_cm_ua 可直接喂 emc_radiated.cm_radiated_field）。
    """
    f = _nonneg(f_mhz, "f_mhz")
    v = _nonneg(v_cm_v, "v_cm_v")
    c = _positive(c_f, "c_f")
    l_ser = _nonneg(l_path_h, "l_path_h")
    r = _nonneg(r_path_ohm, "r_path_ohm")

    if f == 0.0:
        # 浮地定义面：C 隔直 → I=0（两路径同值，无谐振参考面意义）
        notes = (
            "f=0 → C 隔直 → I=0（浮地定义面恒等锚）",
            "路径 A=V/|R+j(ωL−1/ωC)|、路径 B=V·ωC/|1−ω²LC+jωRC|（#118 双路径）",
        )
        return FloatingGroundCmResult(
            f_mhz=0.0, v_cm_v=v, c_f=c, l_path_h=l_ser, r_path_ohm=r,
            z_path_abs_ohm=math.inf, i_cm_ua=0.0, i_cm_a_path_b=0.0,
            dual_path_diff_db=0.0, resonance_f_mhz=None, notes=notes,
        )

    f_hz = f * 1e6
    omega = 2.0 * math.pi * f_hz
    z_react = omega * l_ser - 1.0 / (omega * c)
    z_abs = math.hypot(r, z_react)
    if z_abs == 0.0:
        raise ValueError(
            f"CM 回路阻抗为 0（R=0 且恰在串联谐振 f0={1.0 / (2.0 * math.pi * math.sqrt(l_ser * c)) / 1e6:.6g} MHz）"
            "——谐振电流非物理无界，须给有限 r_path_ohm"
        )
    i_a = v / z_abs
    # 路径 B：有理化恒等式（独立代数形态，非同式逐字复制）
    i_path_b = v * omega * c / math.hypot(1.0 - omega * omega * l_ser * c, omega * r * c)
    dual_diff = abs(_db_amplitude(i_a / i_path_b))
    resonance = (
        1.0 / (2.0 * math.pi * math.sqrt(l_ser * c)) / 1e6 if l_ser > 0.0 else None
    )
    notes = (
        "路径 A=V/|R+j(ωL−1/ωC)|、路径 B=V·ωC/|1−ω²LC+jωRC|（#118 双路径，"
        f"预声明一致带 ±{DUAL_PATH_BAND_DB} dB）",
        "串联谐振 f0=1/(2π√(LC)) 处 I=V/R（损耗限幅）；C=ε0·εr·A/d 平行板下限口径",
        "i_cm_ua 直喂 emc_radiated.cm_radiated_field(i_cm_ua=)（Ott 短偶极辐射链）",
    )
    return FloatingGroundCmResult(
        f_mhz=f, v_cm_v=v, c_f=c, l_path_h=l_ser, r_path_ohm=r,
        z_path_abs_ohm=z_abs, i_cm_ua=i_a * 1e6, i_cm_a_path_b=i_path_b,
        dual_path_diff_db=dual_diff, resonance_f_mhz=resonance, notes=notes,
    )


@dataclass(frozen=True)
class CommonModeRadiatedBudget:
    """浮地耦合 CM 辐射预算（件③全链：耦合电容 → I_CM → emc_radiated 辐射面）。"""

    floating_ground: FloatingGroundCmResult
    radiated: object  # emc_radiated.CmRadiatedResult（避免私有类型复制）

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {
            "floating_ground": self.floating_ground.to_dict(),
            "radiated": self.radiated.to_dict(),
        }


def cm_radiated_via_chassis(
    f_mhz: float,
    length_m: float,
    distance_m: float,
    v_cm_v: float,
    c_f: float | None = None,
    l_path_h: float = 0.0,
    r_path_ohm: float = 0.0,
    *,
    coupling_area_m2: float | None = None,
    coupling_distance_m: float | None = None,
    er: float = 1.0,
    with_ground_image: bool = True,
) -> CommonModeRadiatedBudget:
    """浮地-机壳耦合电容路径的 CM 辐射预算：V_cm → I_CM → Ott 辐射场。

    电容来源二选一：c_f 直给（实测/厂商值），或 coupling_area_m2 +
    coupling_distance_m（+er）走平行板闭式估计；两者同给 → ValueError
    （单一事实来源）。

    I_CM 喂 ``emc_radiated.cm_radiated_field`` 的 i_cm_ua 入口（复用其
    Ott 式双路径/偶极上限/镜像/限值叠加全链）。

    Args:
        f_mhz: 频率 MHz（>=0）。
        length_m: CM 电缆长度 m（>0，Ott 式入参）。
        distance_m: 测量距离 m（>0）。
        v_cm_v: 浮地-机壳 CM 电压源 V（>=0）。
        c_f: 耦合电容 F（与 area/distance 二选一）。
        l_path_h: CM 回路路径电感 H（>=0）。
        r_path_ohm: CM 回路电阻 Ω（>=0）。
        coupling_area_m2: 平行板估计用正对面积 m²（与 c_f 二选一）。
        coupling_distance_m: 平行板估计用间距 m（与 c_f 二选一）。
        er: 平行板估计用相对介电常数（>=1）。
        with_ground_image: 理想地平面镜像 ×2（透传 emc_radiated）。

    Returns:
        CommonModeRadiatedBudget（floating_ground + radiated 两段，均可 to_dict）。
    """
    given = [
        (name, value)
        for name, value in (("c_f", c_f), ("coupling_area_m2", coupling_area_m2))
        if value is not None
    ]
    if len(given) != 1:
        raise ValueError(
            f"c_f 与 coupling_area_m2(+coupling_distance_m) 必须二选一，实际 {[n for n, _ in given]}"
        )
    if coupling_area_m2 is not None and coupling_distance_m is None:
        raise ValueError("coupling_area_m2 须配 coupling_distance_m（平行板闭式两要素）")
    cap = (
        chassis_coupling_capacitance(coupling_area_m2, coupling_distance_m, er)
        if c_f is None
        else _positive(c_f, "c_f")
    )
    loop = floating_ground_cm_current(f_mhz, v_cm_v, cap, l_path_h, r_path_ohm)
    radiated = _cm_radiated_field(
        f_mhz, length_m, loop.i_cm_ua, distance_m, with_ground_image=with_ground_image
    )
    return CommonModeRadiatedBudget(floating_ground=loop, radiated=radiated)


# ── 序列化便捷面（Sequence 入参批量判据）────────────────────────────────────


def ground_spacing_criteria(
    spacing_m: float,
    f_mhz: float | Sequence[float] | np.ndarray,
) -> list[GroundSpacingCriterionResult]:
    """多频点批量判据（同一间距 vs 一组频点；频点须升序不限）。"""
    freqs = (
        [f_mhz]
        if isinstance(f_mhz, (int, float)) and not isinstance(f_mhz, bool)
        else [float(x) for x in np.atleast_1d(np.asarray(f_mhz, dtype=float))]
    )
    return [ground_spacing_criterion(spacing_m, f) for f in freqs]
