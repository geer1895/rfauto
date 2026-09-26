"""fab 能力剖面加载 + 纯几何 DFM 门（DP-7 P1/P3）。

定位（docs/plan_deepdive_specs_20260924.md DP-7）：制造现实接进设计链——
fab 能力剖面 YAML（knowledge/fab_profiles/{jlcpcb,huaqiu}.yaml）→ 渲染后
几何 DFM 门（本模块，**纯几何零仿真**：无网络、无求解器、无文件 I/O 依赖
于校验调用点——唯一 I/O 是 load_profile 读剖面）。

判据式（预声明 runs/df6_dp7fab/criteria.md C2）：
- 线宽下限：``名义 × (1 − trace_tol_pct/100) ≥ min_trace_mm``（按铜厚档）；
- 缝宽：``gap_mm ≥ min_gap_mm``（规格原文无容差折扣）；
- 铜厚档存在：copper_oz ∈ 剖面 copper_rules；
- 板材 ∈ 支持清单（规范化小写后 token 全等/前缀匹配，如
  ``rogers4350b_h0.508`` ↔ ``rogers4350b``）；
- 附加面：最小孔径 / 过孔环宽 / 板厚范围 / 表面处理枚举。
违规输出逐项清单（code/field/value/limit/detail），聚合为 DFMReport。

分层：本模块属 core 叶（不 import 上层）；adapters/kicad_pcell.py 导出前
经 :func:`best_effort_dfm_for_design` 接线（best-effort，#105——不阻塞
导出，失败留痕）；service/fab_service.py 提供 JSON 进出门面与模板面。
P2（公差→良率单源注入 uq_service）延后：良率对照判据的实现放
service/fab_service.py::fab_profile_yield，本模块不做任何统计抽样。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "VIOLATION_CODES",
    "CopperRule",
    "DFMReport",
    "FabProfile",
    "FabProfileError",
    "best_effort_dfm_for_design",
    "check_board_thickness",
    "check_copper",
    "check_drill",
    "check_gaps",
    "check_geometry",
    "check_material",
    "check_surface_finish",
    "check_trace_widths",
    "load_profile",
]

VIOLATION_CODES = (
    "TRACE_BELOW_MIN",
    "GAP_BELOW_MIN",
    "COPPER_UNSUPPORTED",
    "MATERIAL_UNSUPPORTED",
    "DRILL_BELOW_MIN",
    "VIA_ANNULAR_RING_BELOW_MIN",
    "BOARD_THICKNESS_OUT_OF_RANGE",
    "SURFACE_FINISH_UNSUPPORTED",
    "INVALID_GEOMETRY",
)

#: 支持板材 token 匹配口径：material 归一化小写后 == token 或以 token 为前缀
# （materials.yaml 键如 ``rogers4350b_h0.508`` / ``fr4_h1.6`` 均可命中）。


class FabProfileError(ValueError):
    """fab 剖面缺失/字段非法（schema 钉测试与本门共用）。"""


def _profiles_dir() -> Path:
    # 与 core/vendor_passives.py 同源：workspace 根 = src/rfauto/core/..×3
    return Path(__file__).resolve().parents[3] / "knowledge" / "fab_profiles"


def _positive(value: Any, where: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise FabProfileError(f"{where}: 数值非法 {value!r}") from exc
    if not v > 0.0:
        raise FabProfileError(f"{where}: 必须 >0，收到 {v!r}")
    return v


@dataclass(frozen=True)
class CopperRule:
    """单铜厚档最小线宽/缝宽（mm）。"""

    copper_oz: float
    min_trace_mm: float
    min_gap_mm: float


@dataclass(frozen=True)
class FabProfile:
    """fab 能力剖面（校验后的不可变视图；raw 保留原文供 provenance）。"""

    name: str
    profile_version: str
    source_url: str
    retrieved_date: str
    trace_tol_pct: float
    impedance_tol_pct: float
    copper_rules: dict[float, CopperRule]
    board_thickness_min_mm: float
    board_thickness_max_mm: float
    min_drill_mm: float
    min_via_pad_mm: float
    min_via_annular_ring_mm: float
    min_annular_ring_mm: float
    min_solder_mask_dam_mm: float
    surface_finishes: tuple[str, ...]
    supported_materials: tuple[str, ...]
    path: str
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise FabProfileError(f"{where}: 缺必填字段 {key}")
    return mapping[key]


def _parse_copper_rules(raw_rules: Any) -> dict[float, CopperRule]:
    if not isinstance(raw_rules, dict) or not raw_rules:
        raise FabProfileError("copper_rules: 必须为非空映射")
    rules: dict[float, CopperRule] = {}
    for key, entry in raw_rules.items():
        try:
            oz = float(key)
        except (TypeError, ValueError) as exc:
            raise FabProfileError(f"copper_rules 键 {key!r}: 不是铜厚档数字") from exc
        if not oz > 0.0:
            raise FabProfileError(f"copper_rules 键 {key!r}: 铜厚必须 >0")
        if not isinstance(entry, dict):
            raise FabProfileError(f"copper_rules[{key}]: 档位必须为映射")
        rules[oz] = CopperRule(
            copper_oz=oz,
            min_trace_mm=_positive(
                _require(entry, "min_trace_mm", f"copper_rules[{key}]"),
                f"copper_rules[{key}].min_trace_mm"),
            min_gap_mm=_positive(
                _require(entry, "min_gap_mm", f"copper_rules[{key}]"),
                f"copper_rules[{key}].min_gap_mm"),
        )
    return rules


def load_profile(
    name: str = "jlcpcb",
    *,
    profiles_dir: str | Path | None = None,
) -> FabProfile:
    """加载并校验 fab 能力剖面 YAML（name 不带扩展名或给完整路径）。

    校验失败抛 :class:`FabProfileError`（字段级消息，字段一致性钉测试
    断言消息与字段名）。板材 token 统一小写去重。
    """
    import yaml

    path = Path(name)
    if not path.exists():
        base = Path(profiles_dir) if profiles_dir else _profiles_dir()
        path = base / (name if name.endswith(".yaml") else f"{name}.yaml")
    if not path.exists():
        raise FabProfileError(f"fab 剖面不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FabProfileError(f"{path}: 顶层必须为映射")
    if int(_require(data, "schema_version", str(path))) != 1:
        raise FabProfileError(f"{path}: 不支持的 schema_version")

    prof = _require(data, "profile", str(path))
    trace = _require(data, "trace", str(path))
    impedance = _require(data, "impedance", str(path))
    thickness = _require(data, "board_thickness", str(path))
    materials = _require(data, "supported_materials", str(path))
    tokens = sorted({
        str(m.get("token") if isinstance(m, dict) else m).strip().lower()
        for m in materials
    })
    if not tokens or "" in tokens:
        raise FabProfileError("supported_materials: token 清单为空/含空项")
    finishes = tuple(
        str(f).strip().lower()
        for f in _require(data, "surface_finishes", str(path)))
    if not finishes or "" in finishes:
        raise FabProfileError("surface_finishes: 清单为空/含空项")

    return FabProfile(
        name=str(_require(prof, "name", "profile")),
        profile_version=str(_require(prof, "profile_version", "profile")),
        source_url=str(_require(prof, "source_url", "profile")),
        retrieved_date=str(_require(prof, "retrieved_date", "profile")),
        trace_tol_pct=_positive(
            _require(trace, "tolerance_pct", "trace"), "trace.tolerance_pct"),
        impedance_tol_pct=_positive(
            _require(impedance, "tolerance_pct", "impedance"),
            "impedance.tolerance_pct"),
        copper_rules=_parse_copper_rules(_require(data, "copper_rules", str(path))),
        board_thickness_min_mm=float(_require(thickness, "min_mm",
                                              "board_thickness")),
        board_thickness_max_mm=float(_require(thickness, "max_mm",
                                              "board_thickness")),
        min_drill_mm=_positive(_require(data, "min_drill_mm", str(path)),
                               "min_drill_mm"),
        min_via_pad_mm=_positive(_require(data, "min_via_pad_mm", str(path)),
                                 "min_via_pad_mm"),
        min_via_annular_ring_mm=_positive(
            _require(data, "min_via_annular_ring_mm", str(path)),
            "min_via_annular_ring_mm"),
        min_annular_ring_mm=_positive(
            _require(data, "min_annular_ring_mm", str(path)),
            "min_annular_ring_mm"),
        min_solder_mask_dam_mm=_positive(
            _require(data, "min_solder_mask_dam_mm", str(path)),
            "min_solder_mask_dam_mm"),
        surface_finishes=finishes,
        supported_materials=tuple(tokens),
        path=str(path),
        raw=data,
    )


def _violation(code: str, fld: str, value: float, limit: float,
               detail: str) -> dict[str, Any]:
    return {"code": code, "field": fld, "value": round(float(value), 9),
            "limit": round(float(limit), 9), "detail": detail}


def _material_supported(material: str, profile: FabProfile) -> bool:
    m = material.strip().lower()
    return any(m == t or m.startswith(t) for t in profile.supported_materials)


def check_copper(copper_oz: float, profile: FabProfile) -> list[dict[str, Any]]:
    """铜厚档存在性（copper_rules 键集）。"""
    oz = float(copper_oz)
    if oz in profile.copper_rules:
        return []
    supported = ", ".join(
        f"{oz_}g" for oz_ in sorted(profile.copper_rules))
    return [_violation(
        "COPPER_UNSUPPORTED", "copper_oz", oz, float("nan"),
        f"剖面 {profile.name} 铜厚档 {oz}oz 未登记（支持: {supported}）")]


def check_trace_widths(
    widths_mm: list[float],
    profile: FabProfile,
    *,
    copper_oz: float,
    trace_tol_pct: float | None = None,
) -> list[dict[str, Any]]:
    """线宽下限：名义 × (1 − tol) ≥ min_trace（按铜厚档；tol 缺省取剖面）。"""
    tol = profile.trace_tol_pct if trace_tol_pct is None else float(trace_tol_pct)
    rule = profile.copper_rules.get(float(copper_oz))
    if rule is None:
        return check_copper(copper_oz, profile)
    out: list[dict[str, Any]] = []
    for i, w in enumerate(widths_mm):
        w = float(w)
        if not w > 0.0:
            out.append(_violation("INVALID_GEOMETRY", f"traces[{i}].width_mm",
                                  w, rule.min_trace_mm, "线宽必须 >0"))
            continue
        lower = w * (1.0 - tol / 100.0)
        if lower < rule.min_trace_mm:
            out.append(_violation(
                "TRACE_BELOW_MIN", f"traces[{i}].width_mm", w,
                rule.min_trace_mm,
                f"线宽下限 名义{w}mm×(1−{tol:g}%)={lower:.4f}mm < "
                f"min_trace {rule.min_trace_mm}mm（{copper_oz}oz 档）"))
    return out


def check_gaps(
    gaps_mm: list[float],
    profile: FabProfile,
    *,
    copper_oz: float,
) -> list[dict[str, Any]]:
    """缝宽：gap ≥ min_gap（规格原文无容差折扣）。"""
    rule = profile.copper_rules.get(float(copper_oz))
    if rule is None:
        return check_copper(copper_oz, profile)
    out: list[dict[str, Any]] = []
    for i, g in enumerate(gaps_mm):
        g = float(g)
        if not g > 0.0:
            out.append(_violation("INVALID_GEOMETRY", f"gaps[{i}].gap_mm",
                                  g, rule.min_gap_mm, "缝宽必须 >0"))
        elif g < rule.min_gap_mm:
            out.append(_violation(
                "GAP_BELOW_MIN", f"gaps[{i}].gap_mm", g, rule.min_gap_mm,
                f"缝宽 {g}mm < min_gap {rule.min_gap_mm}mm（{copper_oz}oz 档）"))
    return out


def check_material(material: str,
                   profile: FabProfile) -> list[dict[str, Any]]:
    """板材 ∈ 支持清单（规范化 token 全等/前缀匹配）。"""
    if _material_supported(material, profile):
        return []
    detail = (f"板材 {material!r} 不在剖面 {profile.name} 支持清单 "
              f"({', '.join(profile.supported_materials)})")
    if not material.strip():
        detail = "板材名为空"
    return [_violation("MATERIAL_UNSUPPORTED", "material", float("nan"),
                       float("nan"), detail)]


def check_drill(
    drills_mm: list[float],
    pad_diams_mm: list[float] | None,
    profile: FabProfile,
) -> list[dict[str, Any]]:
    """最小孔径 + 过孔环宽（环宽=(pad−drill)/2，过孔口径）。"""
    out: list[dict[str, Any]] = []
    pads = pad_diams_mm if pad_diams_mm is not None else []
    for i, d in enumerate(drills_mm):
        d = float(d)
        if not d > 0.0:
            out.append(_violation("INVALID_GEOMETRY", f"vias[{i}].drill_mm",
                                  d, profile.min_drill_mm, "孔径必须 >0"))
            continue
        if d < profile.min_drill_mm:
            out.append(_violation(
                "DRILL_BELOW_MIN", f"vias[{i}].drill_mm", d,
                profile.min_drill_mm,
                f"孔径 {d}mm < 最小孔径 {profile.min_drill_mm}mm"))
        if i < len(pads):
            ring = (float(pads[i]) - d) / 2.0
            if ring < profile.min_via_annular_ring_mm:
                out.append(_violation(
                    "VIA_ANNULAR_RING_BELOW_MIN", f"vias[{i}].ring_mm", ring,
                    profile.min_via_annular_ring_mm,
                    f"环宽 (pad {pads[i]}−drill {d})/2={ring:.4f}mm < "
                    f"{profile.min_via_annular_ring_mm}mm"))
    return out


def check_board_thickness(
    thickness_mm: float, profile: FabProfile
) -> list[dict[str, Any]]:
    """板厚范围（[min_mm, max_mm] 闭区间）。"""
    t = float(thickness_mm)
    if profile.board_thickness_min_mm <= t <= profile.board_thickness_max_mm:
        return []
    return [_violation(
        "BOARD_THICKNESS_OUT_OF_RANGE", "board_thickness_mm", t,
        profile.board_thickness_min_mm,
        f"板厚 {t}mm 超出剖面 {profile.name} 范围 "
        f"[{profile.board_thickness_min_mm}, "
        f"{profile.board_thickness_max_mm}]mm")]


def check_surface_finish(
    finish: str, profile: FabProfile
) -> list[dict[str, Any]]:
    """表面处理 ∈ 枚举档。"""
    f = finish.strip().lower()
    if f in profile.surface_finishes:
        return []
    return [_violation(
        "SURFACE_FINISH_UNSUPPORTED", "surface_finish", float("nan"),
        float("nan"),
        f"表面处理 {finish!r} 不在剖面 {profile.name} 档位 "
        f"({', '.join(profile.surface_finishes)})")]


@dataclass(frozen=True)
class DFMReport:
    """DFM 门报告（ok=无违规；violations 逐项清单；checked 记录面）。"""

    ok: bool
    profile: str
    profile_version: str
    violations: list[dict[str, Any]]
    checked: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "profile": self.profile,
            "profile_version": self.profile_version,
            "violations": self.violations,
            "checked": self.checked,
        }


def check_geometry(
    profile: FabProfile,
    *,
    traces_mm: list[float] | None = None,
    gaps_mm: list[float] | None = None,
    copper_oz: float = 1.0,
    material: str | None = None,
    drills_mm: list[float] | None = None,
    pad_diams_mm: list[float] | None = None,
    board_thickness_mm: float | None = None,
    surface_finish: str | None = None,
) -> DFMReport:
    """聚合校验：给定面全查，未给面跳过（checked 记录跳过事实）。

    铜厚档存在性独立于线宽/缝宽面——即便未给 traces/gaps，缺档也逐项
    列出（不静默放过）；缺档时线宽/缝宽不再重复报缺档。
    """
    violations: list[dict[str, Any]] = []
    checked: dict[str, Any] = {"profile": profile.name,
                               "copper_oz": float(copper_oz)}
    copper_ok = float(copper_oz) in profile.copper_rules
    if not copper_ok:
        violations += check_copper(copper_oz, profile)
    if traces_mm is not None:
        if copper_ok:
            v = check_trace_widths(traces_mm, profile, copper_oz=copper_oz)
            violations += v
        checked["n_traces"] = len(traces_mm)
    else:
        checked["n_traces"] = None
    if gaps_mm is not None:
        if copper_ok:
            violations += check_gaps(gaps_mm, profile, copper_oz=copper_oz)
        checked["n_gaps"] = len(gaps_mm)
    if material is not None:
        violations += check_material(material, profile)
        checked["material"] = material
    if drills_mm:
        violations += check_drill(drills_mm, pad_diams_mm, profile)
        checked["n_vias"] = len(drills_mm)
    if board_thickness_mm is not None:
        violations += check_board_thickness(board_thickness_mm, profile)
        checked["board_thickness_mm"] = float(board_thickness_mm)
    if surface_finish is not None:
        violations += check_surface_finish(surface_finish, profile)
        checked["surface_finish"] = surface_finish
    return DFMReport(
        ok=not violations,
        profile=profile.name,
        profile_version=profile.profile_version,
        violations=violations,
        checked=checked,
    )


def best_effort_dfm_for_design(
    design: dict[str, Any],
    *,
    profile_name: str = "jlcpcb",
) -> dict[str, Any]:
    """KiCad 导出前 DFM 门（best-effort，#105）——**永不抛异常**。

    入参形状 = ``adapters/kicad_pcell.PCBDesign.to_dict()``（traces[].width、
    vias[].drill/pad，mm）+ 可选 material/board_thickness_mm/surface_finish。
    任何失败（剖面缺失/形状非法）返回 ``{"ran": False, ...}`` 留痕，
    调用方（导出主路径）不得因此中断。
    """
    try:
        profile = load_profile(profile_name)
        traces = [float(t["width"]) for t in design.get("traces") or []
                  if t.get("width") is not None]
        vias = design.get("vias") or []
        drills = [float(v["drill"]) for v in vias
                  if v.get("drill") is not None]
        pads = [float(v["pad"]) for v in vias if v.get("pad") is not None]
        report = check_geometry(
            profile,
            traces_mm=traces,
            drills_mm=drills,
            pad_diams_mm=pads or None,
            copper_oz=float(design.get("copper_oz") or 1.0),
            material=design.get("material"),
            board_thickness_mm=design.get("board_thickness_mm"),
            surface_finish=design.get("surface_finish"),
        )
        out = report.to_dict()
        out["ran"] = True
        return out
    except Exception as exc:
        return {"ran": False, "ok": None, "reason": f"{type(exc).__name__}: {exc}"}
