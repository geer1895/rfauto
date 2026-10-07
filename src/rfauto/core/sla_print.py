"""SLA 打印微波件工艺约束检查（P5 闭式面，纯函数内核）。

P5 规格（池十五 P5 / 月计划 carry-over §二.2）：SLA 打印微波件（喇叭/
透镜族）——镀金属 SLA 性能接近机加工（池 P3/P5 检索在档）；"先测 εr
再设计"流程。本件=SLA **工艺约束检查闭式内核**：几何可打印性（最小
特征/层厚步数/纵横比/最小壁厚/中空排液孔）+ 镀层导电有效性（趋肤深度
闭式）+ 材料先验门（实测 εr 必须在档——"先测再设计"的守卫面）。

闭式与出处（#118/#300：公式自含、基准双锚、机器参数不凭记忆）：
- 趋肤深度 δ = √(2/(ω μ σ))——良导体标准定义式（由 ∇²E 在导体内
  解的指数衰减常数直接推得；如 Pozar《Microwave Engineering》良导体
  表面电阻推导章节；等效代数形 δ = 1/√(π f μ σ)，本件两形互证）。
- 电流份额闭式：导体内 |J(z)| ∝ e^(−z/δ)，厚度 t 内承载电流份额 =
  1 − e^(−t/δ)（对指数衰减直接积分；精确交流电阻含 tanh((1+j)t/δ)
  相位项，本件只做份额口径并如实注明）。份额 ≥ 0.95 ⇔ t ≥ ln(20)·δ
  ≈ 3.0δ（"3δ 惯例"的闭式来源）。
- 打印机机器参数（光斑/层厚/纵横比等）是**机型相关事实**，缺省档
  DEFAULT_PROFILE 只是保守占位（UNVERIFIED_machine_specific，#122：
  使用前必须以目标打印机规格书核对后显式传 profile）。

验证范式（≥2 独立基准）：
1. 两代数形互证：√(2/(ωμσ)) 与 1/√(πfμσ) 全频段逐位一致；
2. 电流份额闭式 vs 数值积分 ∫e^(−z/δ)dz 归一（梯形法独立实现）；
3. #340 埋点回收：薄特征/薄壁/中空无排液孔/镀层不足/未测 εr 全部拦下。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "DEFAULT_PROFILE",
    "SLAPrinterProfile",
    "check_printability",
    "current_fraction_in_thickness",
    "material_prior_gate",
    "plating_check",
    "skin_depth",
]

_MU0 = 4e-7 * np.pi  # 真空磁导率（SI 定义值）


def skin_depth(freq_hz: float, sigma_s_m: float) -> float:
    """良导体趋肤深度 δ = √(2/(ω μ σ))（米）。

    Args:
        freq_hz: 频率（Hz，>0）。
        sigma_s_m: 电导率（S/m，>0，如退火铜 5.8e7——常量级事实，
            数值由调用方给）。

    Raises:
        ValueError: 频率或电导率非正。
    """
    if freq_hz <= 0:
        raise ValueError(f"freq_hz 必须为正，收到 {freq_hz!r}")
    if sigma_s_m <= 0:
        raise ValueError(f"sigma_s_m 必须为正，收到 {sigma_s_m!r}")
    omega = 2.0 * np.pi * float(freq_hz)
    return float(np.sqrt(2.0 / (omega * _MU0 * float(sigma_s_m))))


def current_fraction_in_thickness(t_m: float, delta_m: float) -> float:
    """厚度 t 内承载的电流份额 = 1 − e^(−t/δ)（份额口径，见模块 docstring）。

    Raises:
        ValueError: t 或 δ 非正。
    """
    if t_m <= 0 or delta_m <= 0:
        raise ValueError(f"t/δ 必须为正，收到 t={t_m!r}, δ={delta_m!r}")
    return float(1.0 - np.exp(-float(t_m) / float(delta_m)))


def plating_check(
    freq_hz: float,
    sigma_s_m: float,
    t_plating_m: float,
    *,
    min_fraction: float = 0.95,
) -> dict[str, Any]:
    """镀层导电有效性检查：份额口径（t ≥ ln(1/(1−min_fraction))·δ）。

    份额 ≥ 0.95 ⇔ t ≥ 3.00·δ（"3δ 惯例"闭式来源，见模块 docstring）。
    返回 dict（非 envelope——core 纯函数面）：{ok, delta_m, fraction,
    min_t_m, t_plating_m, shortfall_m}。
    """
    delta = skin_depth(freq_hz, sigma_s_m)
    fraction = current_fraction_in_thickness(t_plating_m, delta)
    min_t = -float(np.log(1.0 - float(min_fraction))) * delta
    return {
        "ok": bool(t_plating_m >= min_t),
        "delta_m": delta,
        "fraction": fraction,
        "min_fraction": float(min_fraction),
        "min_t_m": min_t,
        "t_plating_m": float(t_plating_m),
        "shortfall_m": max(0.0, min_t - float(t_plating_m)),
    }


@dataclass(frozen=True)
class SLAPrinterProfile:
    """SLA 打印机工艺档（机型相关事实，数值必须以规格书核对）。

    Attributes:
        name: 档名。
        laser_spot_mm: 光斑直径（最小特征的下界来源）。
        layer_mm: 层厚（z 向分辨率）。
        min_wall_mm: 最小可打印壁厚（工艺经验值，规格书核对）。
        max_aspect_ratio: 最大纵横比（悬臂/薄壁高宽比上限）。
        tolerance_mm: 尺寸公差带（±，配合后处理）。
        drain_hole_min_mm: 中空件排液孔最小直径（树脂滞留防堵）。
        notes: 机型备注。
    """

    name: str
    laser_spot_mm: float
    layer_mm: float
    min_wall_mm: float
    max_aspect_ratio: float
    tolerance_mm: float
    drain_hole_min_mm: float
    notes: str = field(default="")


#: 保守占位缺省档——UNVERIFIED_machine_specific（#122）：数值是"常见
#: 桌面级光固化机的量级占位"，不是任何具体机型的事实；生产使用必须
#: 以目标打印机规格书核对后显式传 profile 覆盖。
DEFAULT_PROFILE = SLAPrinterProfile(
    name="generic_desktop_placeholder",
    laser_spot_mm=0.10,
    layer_mm=0.05,
    min_wall_mm=1.0,
    max_aspect_ratio=8.0,
    tolerance_mm=0.10,
    drain_hole_min_mm=2.0,
    notes="UNVERIFIED_machine_specific 占位档；使用前以规格书核对",
)


def check_printability(
    geom: dict[str, Any],
    profile: SLAPrinterProfile | None = None,
) -> dict[str, Any]:
    """几何可打印性约束检查（逐约束 PASS/FAIL + 缺项如实 UNKNOWN）。

    Args:
        geom: 几何描述（毫米制，键均可选——缺项只记 unknown 不判 FAIL）：
            min_feature_mm（最小特征尺寸）、height_mm（z 向总高，算层数）、
            aspect_ratio（设计纵横比）、min_wall_mm（最薄壁）、
            is_hollow（bool，中空件）、drain_hole_mm（排液孔直径）。
        profile: 打印机工艺档（None=DEFAULT_PROFILE 占位档，UNVERIFIED）。

    Returns:
        dict：{ok, all_pass, constraints: [{name, required, actual,
        status: pass|fail|unknown, detail}], profile, profile_unverified}。
        ok = all_pass 且无 fail（unknown 不 fail 但透出）。
    """
    prof = profile if profile is not None else DEFAULT_PROFILE
    constraints: list[dict[str, Any]] = []

    def _add(name: str, required: float | None, actual: Any,
             status: str, detail: str) -> None:
        constraints.append({"name": name, "required": required,
                            "actual": actual, "status": status,
                            "detail": detail})

    def _num(key: str) -> float | None:
        val = geom.get(key)
        if val is None:
            return None
        try:
            out = float(val)
        except (TypeError, ValueError):
            return None
        return out if out == out else None  # NaN→缺项

    feature = _num("min_feature_mm")
    if feature is None:
        _add("min_feature", prof.laser_spot_mm, None, "unknown",
             "缺 min_feature_mm")
    elif feature >= prof.laser_spot_mm:
        _add("min_feature", prof.laser_spot_mm, feature, "pass",
             "≥ 光斑直径")
    else:
        _add("min_feature", prof.laser_spot_mm, feature, "fail",
             f"小于光斑直径 {prof.laser_spot_mm}mm，特征不可分辨")

    height = _num("height_mm")
    if height is None:
        _add("layer_count", prof.layer_mm, None, "unknown", "缺 height_mm")
    else:
        n_layers = math.ceil(height / prof.layer_mm)
        _add("layer_count", prof.layer_mm, n_layers, "pass",
             f"{height}mm ÷ {prof.layer_mm}mm 层厚 → {n_layers} 层")

    aspect = _num("aspect_ratio")
    if aspect is None:
        _add("aspect_ratio", prof.max_aspect_ratio, None, "unknown",
             "缺 aspect_ratio")
    elif aspect <= prof.max_aspect_ratio:
        _add("aspect_ratio", prof.max_aspect_ratio, aspect, "pass",
             "≤ 机型纵横比上限")
    else:
        _add("aspect_ratio", prof.max_aspect_ratio, aspect, "fail",
             f"超机型上限 {prof.max_aspect_ratio}（悬臂/薄壁塌陷风险）")

    wall = _num("min_wall_mm")
    if wall is None:
        _add("min_wall", prof.min_wall_mm, None, "unknown", "缺 min_wall_mm")
    elif wall >= prof.min_wall_mm:
        _add("min_wall", prof.min_wall_mm, wall, "pass", "≥ 最小壁厚")
    else:
        _add("min_wall", prof.min_wall_mm, wall, "fail",
             f"薄于最小壁厚 {prof.min_wall_mm}mm（渗漏/脆断风险）")

    is_hollow = bool(geom.get("is_hollow", False))
    if not is_hollow:
        _add("drain_hole", prof.drain_hole_min_mm, None, "pass",
             "实心件无需排液孔")
    else:
        drain = _num("drain_hole_mm")
        if drain is None:
            _add("drain_hole", prof.drain_hole_min_mm, None, "fail",
                 "中空件未声明排液孔（树脂滞留→固化胀裂，必须开孔）")
        elif drain >= prof.drain_hole_min_mm:
            _add("drain_hole", prof.drain_hole_min_mm, drain, "pass",
                 "≥ 最小孔径")
        else:
            _add("drain_hole", prof.drain_hole_min_mm, drain, "fail",
                 f"小于最小孔径 {prof.drain_hole_min_mm}mm（树脂滞留风险）")

    n_fail = sum(1 for c in constraints if c["status"] == "fail")
    return {
        "ok": n_fail == 0,
        "all_pass": n_fail == 0,
        "constraints": constraints,
        "profile": prof.name,
        "profile_unverified": prof.name == DEFAULT_PROFILE.name,
    }


def material_prior_gate(
    eps_r_measured: float | None,
    tan_d_measured: float | None = None,
    *,
    plausibility_window: tuple[float, float] = (1.0, 12.0),
) -> dict[str, Any]:
    """材料先验门（"先测 εr 再设计"守卫）：实测值必须在档且落在先验窗。

    聚合物树脂先验窗缺省 (1, 12]（量级先验窗，非机型事实；SLA 树脂
    εr 典型低个位数——窗只拦越界噪声/单位错，不替代实测）。
    返回 {ok, gate: pass|fail, reason, eps_r_measured, tan_d_measured}。
    """
    if eps_r_measured is None:
        return {
            "ok": False, "gate": "fail",
            "reason": "实测 εr 未提供——'先测 εr 再设计'（P5 流程守卫），"
                      "凭目录标称值设计前必须实测",
            "eps_r_measured": None, "tan_d_measured": tan_d_measured,
        }
    val = float(eps_r_measured)
    lo, hi = plausibility_window
    if val != val:
        return {
            "ok": False, "gate": "fail",
            "reason": f"实测 εr={val!r} 非有限值（NaN）——测量链复核",
            "eps_r_measured": val, "tan_d_measured": tan_d_measured,
        }
    if not (lo < val <= hi):
        return {
            "ok": False, "gate": "fail",
            "reason": f"实测 εr={val!r} 越出先验窗 ({lo}, {hi}]——"
                      "疑测量/单位错，复核后重测",
            "eps_r_measured": val, "tan_d_measured": tan_d_measured,
        }
    return {
        "ok": True, "gate": "pass",
        "reason": "实测 εr 在档且在先验窗内",
        "eps_r_measured": val, "tan_d_measured": tan_d_measured,
    }
