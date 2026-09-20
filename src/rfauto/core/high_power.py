r"""高功率效应预筛确定性内核。

确定性纯函数、零 IO、JSON 可序列化；数值全部落在本内核，LLM/agent 只解释。

四项预筛
--------
1) 峰值 |E| 场 dump → 击穿裕量（本模块）
        margin_ratio = E_bd / |E|_peak
        margin_db    = 20*log10(margin_ratio)
   平行板 E = V/d 为经典闭式（Jackson, Classical Electrodynamics 3rd ed.
   §1.3；Pozar, Microwave Engineering 4th ed. 同口径）。空气 E_bd = 3 MV/m
   与 PTFE 等材料表直接复用 core/calculators.py 的
   'parallel_plate_breakdown_margin'（该表来源见 calculators.py 内注释；
   本模块不改 calculators.py）。
   基材扩展表 SUBSTRATE_DIELECTRIC_STRENGTH_MV_PER_M（逐条附来源 URL）：
     - alumina 16.7 MV/m：Accuratus "Alumox"（99.5% Al2O3）数据表
       Dielectric Strength 16.7 ac-kV/mm（418 V/mil）
       https://accuratus.com/alumox.html （2026-09 取）
     - fused_silica 50.0 MV/m：Insaco 经 AZoOptics 公布 1270 ac V/mil
       = 1270/0.0254 = 50000 V/mm = 50.0 MV/m
       https://www.azooptics.com/Article.aspx?ArticleID=161 （2026-09 取）
   FR-4 / RO4003C 等层压板击穿强度随厚度与分档差异大（数倍量级），本表
   不编造数字；请用 'material_strength_mv_per_m' 按厂商数据表直接注入。

2) 平均功率 → 温升（本模块薄封装，口径 100% 走 calculators）
   复用 calculators.thermal_resistance_stack（1-D 串联/并联热阻网络，
   Tj = Ta + P*theta_tot；教科书电阻类比）。

3) ECSS-E-ST-20-01C 多载流子 f·d 判据（本模块薄封装，口径走 calculators）
   复用 calculators.ecss_multipactor_fd（ECSS-E-ST-20-01C (15 June 2020)
   Table 5-1 的 Al/Cu/Ag/Au 最低击穿电压边界，对数横轴插值）。单载波峰值
   电压口径 V_peak = sqrt(2*P*Z0)；多载波 ECSS 口径 Pavg = sum(Pi)。

4) PIM 确定性设计规则表（本模块）
   三条规则（来源见 PIM_RULES[*].source）：
     - ferromagnetic_material：RF 电流路径禁铁磁材料（mu_r > 1）。铁磁材料
       在 RF 大电流下非线性磁化是公认 PIM 源。来源：RF Cafe "Passive
       Intermodulation"（https://rfcafe.com/references/electrical/pim.htm）；
       IEEE "Modeling of Passive Intermodulation in Connectors With Coating
       Material and Iron Content in Base Brass"。
     - contact_current_path：RF 电流路径不得依赖机械接触面（可分离连接器/
       螺栓/压接/铆接/未焊搭接），并避免异种金属/氧化结面。来源同上
       （"dissimilar metals, dirty interconnects ... loose connections"）。
     - current_density：导体电流密度 J = I/A 不得超过上限。
       **上线是工程预筛策略，不是标准限值**：默认阈值取铜互连电迁移临界
       电流密度量级 1e5 A/cm^2 (= 100 A/mm^2) 的 1/10 降额 = 10 A/mm^2，
       用于在高功率下为局部焦耳热点/热失配留余量；可用
       'max_current_density_a_per_mm2' 覆盖。默认值不是被测物理常数。

设计约束：core 叶子层（仅 import numpy 与同层 calculators），非法输入显式
ValueError，不静默兜底。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from rfauto.core.calculators import (
    _DIELECTRIC_STRENGTH_MV_PER_M,
    ecss_multipactor_fd,
    parallel_plate_breakdown_margin,
    thermal_resistance_stack,
)

__all__ = [
    "AIR_BREAKDOWN_MV_PER_M",
    "CONTACT_JUNCTION_KINDS",
    "CONTINUOUS_JUNCTION_KINDS",
    "DEFAULT_AMBIENT_C",
    "DEFAULT_MAX_CURRENT_DENSITY_A_PER_MM2",
    "DEFAULT_MULTIPACTOR_MARGIN_DB",
    "DEFAULT_Z0_OHM",
    "FERROMAGNETIC_MATERIALS",
    "PIM_RULES",
    "SUBSTRATE_DIELECTRIC_STRENGTH_MV_PER_M",
    "PimRule",
    "breakdown_from_field_peak",
    "field_peak_mv_per_m",
    "multipactor_fd_check",
    "pim_rule_check",
    "power_capacity_report",
    "predict",
    "prescreen",
    "resolve_dielectric_strength",
    "thermal_from_average_power",
]

# ---------------------------------------------------------------------------
# 常量与阈值口径
# ---------------------------------------------------------------------------

# 空气击穿强度：直接取自 calculators 表（3 MV/m）
AIR_BREAKDOWN_MV_PER_M = float(_DIELECTRIC_STRENGTH_MV_PER_M["air"])

DEFAULT_AMBIENT_C = 25.0
DEFAULT_Z0_OHM = 50.0
DEFAULT_MULTIPACTOR_MARGIN_DB = 6.0

# 见模块 docstring 4)：工程预筛策略，非标准限值
DEFAULT_MAX_CURRENT_DENSITY_A_PER_MM2 = 10.0

# 基材扩展表（来源 URL 见模块 docstring；不编造层压板数字）
SUBSTRATE_DIELECTRIC_STRENGTH_MV_PER_M: dict[str, float] = {
    "alumina": 16.7,
    "fused_silica": 50.0,
}

_E_FIELD_UNIT_TO_V_PER_M = {
    "v_per_m": 1.0,
    "v/m": 1.0,
    "kv_per_m": 1.0e3,
    "kv/m": 1.0e3,
    "mv_per_m": 1.0e6,
    "mv/m": 1.0e6,
}

_MATERIAL_ALIASES: dict[str, str] = {
    "air": "air",
    "alumina": "alumina",
    "al2o3": "alumina",
    "aluminium_oxide": "alumina",
    "aluminum_oxide": "alumina",
    "fused_silica": "fused_silica",
    "fused_quartz": "fused_silica",
    "silica": "fused_silica",
    "quartz": "fused_silica",
    "ptfe": "ptfe",
    "teflon": "ptfe",
    "polyethylene": "polyethylene",
    "pe": "polyethylene",
    "pvc": "pvc",
    "mica": "mica",
}

FERROMAGNETIC_MATERIALS = frozenset({
    "iron", "fe", "nickel", "ni", "cobalt", "co",
    "steel", "carbon_steel", "stainless_steel", "ss304", "ss316",
    "mumetal", "permalloy", "kovar", "ferrite", "nickel_plated_brass",
})

CONTACT_JUNCTION_KINDS = frozenset({
    "mechanical", "mechanical_contact", "contact", "connector",
    "connector_interface", "bolted", "bolt", "press_fit", "crimp",
    "rivet", "spring", "spring_contact", "unsoldered_lap", "lap", "clamp",
})

CONTINUOUS_JUNCTION_KINDS = frozenset({
    "soldered", "solder", "welded", "weld", "brazed", "monolithic",
    "plated_monolithic", "molecular_bond", "diffusion_bond",
})


# ---------------------------------------------------------------------------
# 输入收敛助手（非法输入显式 ValueError）
# ---------------------------------------------------------------------------

def _finite(value: Any, name: str) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


def _finite_pos(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，收到 {value!r}")
    return out


def _finite_nonneg(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0，收到 {value!r}")
    return out


def _normalize_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_material(material: Any) -> str:
    key = _normalize_key(material)
    canonical = _MATERIAL_ALIASES.get(key, key)
    if canonical not in _DIELECTRIC_STRENGTH_MV_PER_M and canonical not in SUBSTRATE_DIELECTRIC_STRENGTH_MV_PER_M:
        raise ValueError(
            f"未知介质材料 {material!r}（可用: "
            f"{sorted(set(_MATERIAL_ALIASES) | set(_DIELECTRIC_STRENGTH_MV_PER_M) | set(SUBSTRATE_DIELECTRIC_STRENGTH_MV_PER_M))}）"
        )
    return canonical


# ---------------------------------------------------------------------------
# 1) 峰值 |E| → 击穿裕量
# ---------------------------------------------------------------------------

def field_peak_mv_per_m(e_field: Any, *, unit: str = "v_per_m") -> float:
    """场 dump 的峰值 |E| [MV/m]（复相量取模，实场取绝对值）。

    Args:
        e_field: 场 dump，任意形状的实/复数组（V/m 或 unit 指定的单位）。
        unit: 输入单位，见 _E_FIELD_UNIT_TO_V_PER_M（默认 "v_per_m"）。

    Returns:
        峰值 |E| [MV/m]（非负有限 float）。

    Raises:
        ValueError: 单位未知；数组为空；含 NaN/Inf。
    """
    key = _normalize_key(unit)
    if key not in _E_FIELD_UNIT_TO_V_PER_M:
        raise ValueError(f"未知场单位 {unit!r}（可用: {sorted(_E_FIELD_UNIT_TO_V_PER_M)}）")
    arr = np.asarray(e_field)
    if arr.size == 0:
        raise ValueError("e_field 不能为空")
    mag = np.abs(arr.astype(complex)) if np.iscomplexobj(arr) else np.abs(arr.astype(float))
    if not bool(np.all(np.isfinite(mag))):
        raise ValueError("e_field 含 NaN/Inf")
    return float(np.max(mag)) * _E_FIELD_UNIT_TO_V_PER_M[key] / 1.0e6


def resolve_dielectric_strength(
    material: Any,
    *,
    override_mv_per_m: float | None = None,
) -> tuple[float, str]:
    """解析材料击穿强度 [MV/m] 及其来源标记。

    Returns:
        (strength_mv_per_m, source)，source ∈ {"override", "calculators_table",
        "substrate_table"}。

    Raises:
        ValueError: 覆盖值非正；材料未知且未给覆盖值。
    """
    if override_mv_per_m is not None:
        return _finite_pos(override_mv_per_m, "material_strength_mv_per_m"), "override"
    key = _normalize_material(material)
    if key in _DIELECTRIC_STRENGTH_MV_PER_M:
        return float(_DIELECTRIC_STRENGTH_MV_PER_M[key]), "calculators_table"
    return float(SUBSTRATE_DIELECTRIC_STRENGTH_MV_PER_M[key]), "substrate_table"


def breakdown_from_field_peak(
    field_peak_mv_per_m: float,
    material: Any = "air",
    *,
    safety_factor: float = 1.0,
    material_strength_mv_per_m: float | None = None,
    required_margin_db: float = 0.0,
) -> dict[str, Any]:
    """峰值 |E| → 击穿裕量 dB 与 pass/fail。

    口径：margin_ratio = E_bd/|E|_peak，margin_db = 20*log10(margin_ratio)。
    material 命中 calculators 材料表且未给覆盖强度时，直接委托
    calculators.parallel_plate_breakdown_margin（保证与 calculators 既有口径逐位
    一致）；否则按同一闭式本地计算（含 override / 基材扩展表）。

    Args:
        field_peak_mv_per_m: 峰值 |E| [MV/m]，>=0。
        material: 材料键（air/alumina/fused_silica/ptfe/...）。
        safety_factor: 要求安全系数（E*sf <= E_bd 判过），>0。
        material_strength_mv_per_m: 显式击穿强度覆盖（厂商数据表口径），>0。
        required_margin_db: 要求裕量 dB（默认 0，即仅看安全系数）。

    Returns:
        JSON 可序列化 dict（含 pass / safety_pass / margin_ok / strength_source）。

    Raises:
        ValueError: 峰值/安全系数非法；材料未知且无覆盖值。
    """
    peak = _finite_nonneg(field_peak_mv_per_m, "field_peak_mv_per_m")
    sf = _finite_pos(safety_factor, "safety_factor")
    required = _finite(required_margin_db, "required_margin_db")

    if material_strength_mv_per_m is None:
        key = _normalize_material(material)
        use_calculator = key in _DIELECTRIC_STRENGTH_MV_PER_M
    else:
        key = _normalize_key(material)
        use_calculator = False

    if use_calculator:
        # gap 取 1 mm、voltage = peak*1e3 V ⇒ 计算器内部 E = V/d 精确回 peak
        base = parallel_plate_breakdown_margin(
            voltage_v=peak * 1.0e3, gap_mm=1.0, material=key, safety_factor=sf)
        threshold = float(base["breakdown_mv_per_m"])
        margin_ratio = base["margin_ratio"]
        margin_db = base["margin_db"]
        safety_pass = bool(base["pass"])
        source = "calculators.parallel_plate_breakdown_margin"
    else:
        threshold, source = resolve_dielectric_strength(
            material, override_mv_per_m=material_strength_mv_per_m)
        if peak > 0.0:
            margin_ratio = threshold / peak
            margin_db = 20.0 * math.log10(margin_ratio)
        else:
            margin_ratio = None
            margin_db = None
        safety_pass = bool(peak * sf <= threshold)

    margin_ok = True if margin_db is None else bool(margin_db >= required)
    return {
        "field_peak_mv_per_m": round(peak, 12),
        "breakdown_mv_per_m": threshold,
        "material": key,
        "strength_source": source,
        "margin_ratio": None if margin_ratio is None else round(float(margin_ratio), 12),
        "margin_db": None if margin_db is None else round(float(margin_db), 9),
        "safety_factor": sf,
        "required_margin_db": required,
        "safety_pass": safety_pass,
        "margin_ok": margin_ok,
        "pass": bool(safety_pass and margin_ok),
    }


# ---------------------------------------------------------------------------
# 2) 平均功率 → 温升（薄封装，口径走 calculators）
# ---------------------------------------------------------------------------

def thermal_from_average_power(
    power_w: float,
    *,
    theta_jc_c_per_w: float,
    ambient_c: float = DEFAULT_AMBIENT_C,
    theta_cs_c_per_w: float = 0.0,
    theta_sa_c_per_w: float = 0.0,
    parallel_paths_c_per_w: Sequence[float] | None = None,
    max_junction_c: float | None = None,
) -> dict[str, Any]:
    """平均耗散功率 → 结温（1-D 热阻网络，复用 calculators.thermal_resistance_stack）。

    Tj = Ta + P*theta_tot；theta_tot 为串联链与并联支路的组合热阻。
    max_junction_c 给定时附 pass 判定（Tj <= 上限）。

    Raises:
        ValueError: 参数非法（由 calculators 抛出的同口径错误）。
    """
    out = dict(thermal_resistance_stack(
        power_w=power_w, ambient_c=ambient_c, theta_jc_c_per_w=theta_jc_c_per_w,
        theta_cs_c_per_w=theta_cs_c_per_w, theta_sa_c_per_w=theta_sa_c_per_w,
        parallel_paths_c_per_w=None if parallel_paths_c_per_w is None else list(parallel_paths_c_per_w)))
    out["power_w"] = float(power_w)
    out["max_junction_c"] = None if max_junction_c is None else _finite(max_junction_c, "max_junction_c")
    out["pass"] = (
        None if max_junction_c is None
        else bool(out["junction_temp_c"] <= float(max_junction_c))
    )
    return out


# ---------------------------------------------------------------------------
# 3) ECSS-E-ST-20-01C 多载流子 f·d 判据（薄封装，口径走 calculators）
# ---------------------------------------------------------------------------

def multipactor_fd_check(
    freq_ghz: float,
    gap_mm: float,
    *,
    material: str = "silver",
    voltage_v: float | None = None,
    power_w: float | None = None,
    z0_ohm: float = DEFAULT_Z0_OHM,
    carrier_powers_w: Sequence[float] | None = None,
    required_margin_db: float = DEFAULT_MULTIPACTOR_MARGIN_DB,
) -> dict[str, Any]:
    """ECSS 多载流子 f·d 判据（委托 calculators.ecss_multipactor_fd）。

    f×d [GHz·mm] 查 ECSS-E-ST-20-01C Table 5-1 边界（Al/Cu/Ag/Au，对数插值），
    与施加峰值电压比给出 margin_db / pass。电压来源三选一：voltage_v、
    power_w（V=sqrt(2PZ0)）、carrier_powers_w（V=sqrt(2·ΣPi·Z0)）。
    """
    out = dict(ecss_multipactor_fd(
        freq_ghz=freq_ghz, gap_mm=gap_mm, material=material,
        voltage_v=voltage_v, power_w=power_w, z0_ohm=z0_ohm,
        carrier_powers_w=None if carrier_powers_w is None else list(carrier_powers_w),
        required_margin_db=required_margin_db))
    out["standard"] = "ECSS-E-ST-20-01C (15 June 2020) Table 5-1"
    return out


# ---------------------------------------------------------------------------
# 4) PIM 确定性设计规则表
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PimRule:
    """一条 PIM 预筛规则的自描述条目。"""

    key: str
    description: str
    source: str


PIM_RULES: tuple[PimRule, ...] = (
    PimRule(
        key="ferromagnetic_material",
        description="RF 电流路径不得含铁磁材料（mu_r > 1：铁/镍/钴/不锈钢/铁氧体等）",
        source="RF Cafe \"Passive Intermodulation\" https://rfcafe.com/references/electrical/pim.htm；"
               "IEEE \"Modeling of Passive Intermodulation in Connectors With Coating Material "
               "and Iron Content in Base Brass\"",
    ),
    PimRule(
        key="contact_current_path",
        description="RF 电流路径不得依赖机械接触面导电（可分离连接器/螺栓/压接/铆接/未焊搭接），"
                    "并避免异种金属与氧化/污染结面",
        source="RF Cafe \"Passive Intermodulation\"：dissimilar metals / dirty interconnects / "
               "loose connections 为 PIM 源 https://rfcafe.com/references/electrical/pim.htm",
    ),
    PimRule(
        key="current_density",
        description="导体电流密度 J = I/A 不得超过上限（默认 10 A/mm^2，工程预筛降额）",
        source="工程预筛策略：铜互连电迁移临界电流密度量级 1e5 A/cm^2 的 1/10 降额；"
               "非标准限值，可用 max_current_density_a_per_mm2 覆盖",
    ),
)


def _rule_metadata() -> list[dict[str, str]]:
    return [{"key": r.key, "description": r.description, "source": r.source} for r in PIM_RULES]


def _in_rf_path(entry: Mapping[str, Any]) -> bool:
    """缺省视为位于 RF 电流路径（保守口径）。"""
    return bool(entry.get("in_rf_path", True))


def _is_ferromagnetic(entry: Mapping[str, Any]) -> bool:
    if bool(entry.get("ferromagnetic", False)):
        return True
    mu = entry.get("mu_r")
    if mu is not None and _finite(mu, "mu_r") > 1.0 + 1e-9:
        return True
    return _normalize_key(entry.get("name", "")) in FERROMAGNETIC_MATERIALS


def _check_materials(materials: Any, violations: list[dict[str, Any]]) -> int:
    if not isinstance(materials, Sequence) or isinstance(materials, (str, bytes)):
        raise ValueError("design['materials'] 必须是列表")
    for index, raw in enumerate(materials):
        if not isinstance(raw, Mapping):
            raise ValueError(f"design['materials'][{index}] 必须是映射")
        if not _in_rf_path(raw):
            continue
        if _is_ferromagnetic(raw):
            name = _normalize_key(raw.get("name", ""))
            violations.append({
                "rule": "ferromagnetic_material",
                "severity": "error",
                "detail": f"材料 {name!r} 位于 RF 电流路径且为铁磁（mu_r>1）；"
                          "非线性磁化在 RF 大电流下产生 PIM",
                "context": {"index": index, "name": name, "mu_r": raw.get("mu_r")},
            })
    return len(materials)


def _check_junctions(junctions: Any, violations: list[dict[str, Any]]) -> int:
    if not isinstance(junctions, Sequence) or isinstance(junctions, (str, bytes)):
        raise ValueError("design['junctions'] 必须是列表")
    for index, raw in enumerate(junctions):
        if not isinstance(raw, Mapping):
            raise ValueError(f"design['junctions'][{index}] 必须是映射")
        kind = _normalize_key(raw.get("kind", ""))
        if kind not in CONTACT_JUNCTION_KINDS and kind not in CONTINUOUS_JUNCTION_KINDS:
            raise ValueError(
                f"未知结面类型 {kind!r}（接触类: {sorted(CONTACT_JUNCTION_KINDS)}；"
                f"连续类: {sorted(CONTINUOUS_JUNCTION_KINDS)}）")
        if not _in_rf_path(raw):
            continue
        reasons: list[str] = []
        if kind in CONTACT_JUNCTION_KINDS:
            reasons.append("机械接触面导电")
        if raw.get("dissimilar_metals"):
            reasons.append("异种金属结面")
        if bool(raw.get("oxidized", False)) or bool(raw.get("dirty", False)):
            reasons.append("氧化/污染结面")
        if reasons:
            name = _normalize_key(raw.get("name", "")) or kind
            violations.append({
                "rule": "contact_current_path",
                "severity": "error",
                "detail": f"结面 {name!r} 位于 RF 电流路径且" + "、".join(reasons),
                "context": {"index": index, "name": name, "kind": kind, "reasons": reasons},
            })
    return len(junctions)


def _check_conductors(
    conductors: Any,
    violations: list[dict[str, Any]],
    limit: float,
) -> int:
    if not isinstance(conductors, Sequence) or isinstance(conductors, (str, bytes)):
        raise ValueError("design['conductors'] 必须是列表")
    for index, raw in enumerate(conductors):
        if not isinstance(raw, Mapping):
            raise ValueError(f"design['conductors'][{index}] 必须是映射")
        if not _in_rf_path(raw):
            continue
        name = _normalize_key(raw.get("name", "")) or f"#{index}"
        if raw.get("current_density_a_per_mm2") is not None:
            density = _finite_nonneg(raw["current_density_a_per_mm2"], "current_density_a_per_mm2")
        else:
            current = raw.get("current_a")
            area = raw.get("cross_section_mm2")
            if current is None or area is None:
                raise ValueError(
                    f"导体 {name!r} 需给 current_a + cross_section_mm2 "
                    "或直接给 current_density_a_per_mm2")
            density = _finite_nonneg(current, "current_a") / _finite_pos(area, "cross_section_mm2")
        if density > limit:
            violations.append({
                "rule": "current_density",
                "severity": "error",
                "detail": f"导体 {name!r} 电流密度 {density:.6g} A/mm^2 超过上限 {limit:.6g} A/mm^2",
                "context": {"index": index, "name": name,
                            "current_density_a_per_mm2": round(density, 12),
                            "limit_a_per_mm2": limit},
            })
    return len(conductors)


def pim_rule_check(
    design: Any,
    *,
    max_current_density_a_per_mm2: float = DEFAULT_MAX_CURRENT_DENSITY_A_PER_MM2,
) -> dict[str, Any]:
    """PIM 确定性设计规则检查器，返回违规清单。

    design（None 表示未提供设计，返回 checked=False 的空结果）::

        {
          "materials":   [{"name": "copper", "mu_r": 1.0, "in_rf_path": true,
                           "ferromagnetic": false}, ...],
          "junctions":   [{"name": "SMA", "kind": "connector"|"soldered", ...,
                           "dissimilar_metals": [...], "oxidized": false,
                           "dirty": false}, ...],
          "conductors":  [{"name": "ring", "current_a": 5.0,
                           "cross_section_mm2": 1.0,
                           "current_density_a_per_mm2": null}, ...],
        }

    in_rf_path 缺省为 True（保守）。非 RF 路径元素跳过。

    Returns:
        {"checked", "rules", "violations", "violation_count", "pass", "counts"}。

    Raises:
        ValueError: design 非映射；元素非映射；结面类型未知；导体缺
            current_a/cross_section_mm2 与 current_density 两者；阈值非正。
    """
    if design is None:
        return {"checked": False, "rules": _rule_metadata(), "violations": [],
                "violation_count": 0, "pass": True,
                "counts": {"materials": 0, "junctions": 0, "conductors": 0}}
    if not isinstance(design, Mapping):
        raise ValueError("design 必须是映射（dict）")
    limit = _finite_pos(max_current_density_a_per_mm2, "max_current_density_a_per_mm2")
    violations: list[dict[str, Any]] = []
    counts = {
        "materials": _check_materials(design.get("materials") or [], violations),
        "junctions": _check_junctions(design.get("junctions") or [], violations),
        "conductors": _check_conductors(design.get("conductors") or [], violations, limit),
    }
    return {"checked": True, "rules": _rule_metadata(), "violations": violations,
            "violation_count": len(violations), "pass": not violations, "counts": counts}


# ---------------------------------------------------------------------------
# 功率容量报告（合成/记录数据，不触发真机）
# ---------------------------------------------------------------------------

def power_capacity_report(
    power_levels_w: Sequence[float],
    *,
    reference_power_w: float,
    reference_field_peak_mv_per_m: float,
    material: Any = "air",
    safety_factor: float = 1.0,
    material_strength_mv_per_m: float | None = None,
    required_margin_db: float = 0.0,
    source: str = "recorded",
) -> dict[str, Any]:
    """多功率档位容量报告：由参考功率的场峰值按 E ∝ sqrt(P) 外推逐档判击穿。

    线性（匹配）结构中场幅正比于 sqrt(P)，故 level 档峰值
    = E_ref * sqrt(P/P_ref)。reference_* 为合成或实测记录值（本函数不真跑
    求解器）；source 标注数据来源。

    Returns:
        含 reference / entries / all_pass / max_passing_power_w /
        first_failing_power_w 的 JSON dict。

    Raises:
        ValueError: 功率档位为空或非正；参考值非法。
    """
    ref_power = _finite_pos(reference_power_w, "reference_power_w")
    ref_field = _finite_nonneg(reference_field_peak_mv_per_m, "reference_field_peak_mv_per_m")
    levels = [_finite_pos(p, "power_levels_w[]") for p in power_levels_w]
    if not levels:
        raise ValueError("power_levels_w 不能为空")
    entries: list[dict[str, Any]] = []
    for level in levels:
        field = ref_field * math.sqrt(level / ref_power)
        breakdown = breakdown_from_field_peak(
            field, material, safety_factor=safety_factor,
            material_strength_mv_per_m=material_strength_mv_per_m,
            required_margin_db=required_margin_db)
        entries.append({"power_w": level,
                        "field_peak_mv_per_m": round(field, 12),
                        "scaling": "E ∝ sqrt(P)（线性匹配结构口径）",
                        "breakdown": breakdown, "pass": breakdown["pass"]})
    passing = [e["power_w"] for e in entries if e["pass"]]
    failing = [e["power_w"] for e in entries if not e["pass"]]
    return {
        "reference": {"power_w": ref_power,
                      "field_peak_mv_per_m": ref_field,
                      "material": _normalize_key(material),
                      "source": source},
        "entries": entries,
        "all_pass": not failing,
        "max_passing_power_w": max(passing) if passing else None,
        "first_failing_power_w": min(failing) if failing else None,
    }


# ---------------------------------------------------------------------------
# predict / prescreen 接口
# ---------------------------------------------------------------------------

def _resolve_field_peak(params: Mapping[str, Any]) -> float | None:
    if params.get("field_peak_mv_per_m") is not None:
        return _finite_nonneg(params["field_peak_mv_per_m"], "field_peak_mv_per_m")
    if params.get("e_field") is not None:
        return field_peak_mv_per_m(params["e_field"], unit=params.get("e_field_unit", "v_per_m"))
    voltage = params.get("voltage_v")
    gap = params.get("gap_mm")
    if voltage is not None and gap is not None:
        # 平行板闭式 E = V/d（Jackson §1.3）；与材料无关
        return _finite_nonneg(voltage, "voltage_v") / (_finite_pos(gap, "gap_mm") * 1.0e-3) / 1.0e6
    return None


def prescreen(params: Mapping[str, Any]) -> dict[str, Any]:
    """高功率预筛完整报告（击穿/多载流子/温升/PIM 规则）。

    params 键（全部可选，按提供情况计算对应分项）::

        e_field / field_peak_mv_per_m / (voltage_v + gap_mm)  —— 峰值场来源
        e_field_unit            场单位（默认 "v_per_m"）
        material                介质材料（默认 "air"）
        material_strength_mv_per_m  基材强度覆盖（厂商数据表）
        safety_factor           击穿安全系数（默认 1.0）
        breakdown_required_margin_db  击穿要求裕量 dB（默认 0）
        freq_ghz + gap_mm + (voltage_v|power_w|carrier_powers_w)  —— 多载流子
        metal                   ECSS 金属（默认 "silver"）
        z0_ohm                  系统阻抗（默认 50）
        multipactor_required_margin_db  多载流子要求裕量 dB（默认 6）
        power_w + theta_jc_c_per_w (+ theta_cs/theta_sa/parallel_paths)
        ambient_c               环境温度（默认 25）
        max_junction_c          结温上限（给定时判定温升 pass）
        design                  PIM 设计描述（见 pim_rule_check）
        pim_max_current_density_a_per_mm2  PIM 电流密度上限

    Returns:
        JSON 可序列化报告；pass 为所有已计算分项的合取。
    """
    if not isinstance(params, Mapping):
        raise ValueError("params 必须是映射（dict）")
    p = dict(params)
    material = p.get("material", "air")

    field_peak = _resolve_field_peak(p)
    breakdown = None
    if field_peak is not None:
        breakdown = breakdown_from_field_peak(
            field_peak, material,
            safety_factor=p.get("safety_factor", 1.0),
            material_strength_mv_per_m=p.get("material_strength_mv_per_m"),
            required_margin_db=p.get("breakdown_required_margin_db", 0.0))

    multipactor = None
    if (p.get("freq_ghz") is not None and p.get("gap_mm") is not None
            and (p.get("voltage_v") is not None or p.get("power_w") is not None
                 or p.get("carrier_powers_w") is not None)):
        multipactor = multipactor_fd_check(
            p["freq_ghz"], p["gap_mm"],
            material=p.get("metal", "silver"),
            voltage_v=p.get("voltage_v"), power_w=p.get("power_w"),
            z0_ohm=p.get("z0_ohm", DEFAULT_Z0_OHM),
            carrier_powers_w=p.get("carrier_powers_w"),
            required_margin_db=p.get("multipactor_required_margin_db",
                                     DEFAULT_MULTIPACTOR_MARGIN_DB))

    thermal = None
    if p.get("power_w") is not None and p.get("theta_jc_c_per_w") is not None:
        thermal = thermal_from_average_power(
            p["power_w"], theta_jc_c_per_w=p["theta_jc_c_per_w"],
            ambient_c=p.get("ambient_c", DEFAULT_AMBIENT_C),
            theta_cs_c_per_w=p.get("theta_cs_c_per_w", 0.0),
            theta_sa_c_per_w=p.get("theta_sa_c_per_w", 0.0),
            parallel_paths_c_per_w=p.get("parallel_paths_c_per_w"),
            max_junction_c=p.get("max_junction_c"))

    pim_kwargs: dict[str, Any] = {}
    if p.get("pim_max_current_density_a_per_mm2") is not None:
        pim_kwargs["max_current_density_a_per_mm2"] = p["pim_max_current_density_a_per_mm2"]
    pim = pim_rule_check(p.get("design"), **pim_kwargs)

    components_pass: list[bool] = [breakdown["pass"]] if breakdown is not None else []
    if multipactor is not None:
        components_pass.append(bool(multipactor["pass"]))
    if thermal is not None and thermal["pass"] is not None:
        components_pass.append(bool(thermal["pass"]))
    if pim["checked"]:
        components_pass.append(bool(pim["pass"]))

    return {"field_peak_mv_per_m": None if field_peak is None else round(field_peak, 12),
            "material": _normalize_key(material),
            "breakdown": breakdown,
            "multipactor": multipactor,
            "thermal": thermal,
            "pim": pim,
            "pass": all(components_pass)}


def predict(params: Mapping[str, Any]) -> dict[str, float]:
    """SurrogateModel 契约风格：平铺 params → 平铺数值 metrics（同参数同输出）。

    布尔以 1.0/0.0 表示；未计算的分项不出现在 metrics 中。
    """
    report = prescreen(params)
    metrics: dict[str, float] = {}
    if report["field_peak_mv_per_m"] is not None:
        metrics["field_peak_mv_per_m"] = float(report["field_peak_mv_per_m"])
    breakdown = report["breakdown"]
    if breakdown is not None:
        if breakdown["margin_db"] is not None:
            metrics["breakdown_margin_db"] = float(breakdown["margin_db"])
        metrics["breakdown_threshold_mv_per_m"] = float(breakdown["breakdown_mv_per_m"])
        metrics["breakdown_safety_pass"] = float(bool(breakdown["safety_pass"]))
        metrics["breakdown_pass"] = float(bool(breakdown["pass"]))
    multipactor = report["multipactor"]
    if multipactor is not None:
        metrics["multipactor_fxd_ghz_mm"] = float(multipactor["fxd_ghz_mm"])
        metrics["multipactor_threshold_v"] = float(multipactor["threshold_v"])
        metrics["multipactor_applied_voltage_v"] = float(multipactor["applied_voltage_v"])
        metrics["multipactor_margin_db"] = float(multipactor["margin_db"])
        metrics["multipactor_pass"] = float(bool(multipactor["pass"]))
    thermal = report["thermal"]
    if thermal is not None:
        metrics["thermal_delta_t_c"] = float(thermal["delta_t_c"])
        metrics["thermal_junction_temp_c"] = float(thermal["junction_temp_c"])
        if thermal["pass"] is not None:
            metrics["thermal_pass"] = float(bool(thermal["pass"]))
    pim = report["pim"]
    if pim["checked"]:
        metrics["pim_violation_count"] = float(pim["violation_count"])
        metrics["pim_pass"] = float(bool(pim["pass"]))
    metrics["overall_pass"] = float(bool(report["pass"]))
    return metrics
