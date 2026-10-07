"""精度审计门禁 A1–A12（FAIL 禁止发图）——L0 纯判据.

几何对比优先布尔体积 / bbox；不以网格距离作为验收。

与原型的 IO 边界差异（T43 吸收）：A7（DXF 闭合）与 A12（文件哈希）不再
在内核里扫目录/读文件——由调用方注入 ``dxf_closed``（{文件名: 是否闭合}）
与 ``hashes``（{相对路径: sha256}）；目录采集在
rfauto.adapters.fab_export.audit_io。``None`` = 该项不判（如实 UNKNOWN，
#314 家法：无对不凑 PASS 也不冒充 FAIL）。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .rules import RuleSet, default_ruleset
from .schema import DimsDocument

AUDIT_CHECKS = [
    "A1_variable_closure",
    "A2_bbox",
    "A3_volume_com",
    "A4_boolean_cut",
    "A5_brep_valid",
    "A6_critical_dims",
    "A7_dxf_closed",
    "A8_snap_log",
    "A9_unit_fingerprint",
    "A10_label_consistency",
    "A11_no_nonpart",
    "A12_hashes",
]


@dataclass
class GeometrySummary:
    """轻量几何摘要（可由 OCCT/pyAEDT 填充；测试可用合成值）."""

    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    volume: float
    com: tuple[float, float, float] = (0.0, 0.0, 0.0)
    valid: bool = True
    solid_count: int = 1
    object_names: list[str] = field(default_factory=list)

    def bbox_size(self) -> tuple[float, float, float]:
        return tuple(self.bbox_max[i] - self.bbox_min[i] for i in range(3))  # type: ignore


@dataclass
class AuditResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def raise_if_failed(self) -> None:
        if not self.passed:
            raise RuntimeError("audit FAIL: " + "; ".join(self.errors))


def _rel(a: float, b: float) -> float:
    denom = max(abs(a), abs(b), 1e-30)
    return abs(a - b) / denom


def audit_package(
    dims: DimsDocument,
    geom_hfss: GeometrySummary,
    geom_export: GeometrySummary,
    *,
    snaps: Iterable[float] | None = None,
    label_map: dict[str, float] | None = None,
    rules: RuleSet | None = None,
    cut_volume: float | None = None,
    dxf_closed: Mapping[str, bool] | None = None,
    hashes: Mapping[str, str] | None = None,
) -> AuditResult:
    """执行 A1–A12 纯判据.

    - geom_hfss / geom_export: 两侧 bbox/体积/COM
    - snaps: 自动接缝位移列表（None=不判 A8）
    - label_map: 图纸标注值 {name: value}，与 dims 对拍
    - cut_volume: 可选布尔 A−B 体积（OCCT）；缺省用体积差代理
    - dxf_closed: {文件名: 是否闭合}（A7；None=不判）
    - hashes: {相对路径: sha256}（A12；None=不判，{}=告警无哈希）
    """
    rs = rules or default_ruleset()
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}

    # A1 变量闭合：raw 解析值 vs value
    for v in dims.variables:
        try:
            parsed = _parse_raw_mm(v.raw)
        except Exception as e:
            errors.append(f"A1 {v.name}: raw unparsable ({e})")
            continue
        if parsed is not None and abs(parsed - v.value) > 1e-9:
            errors.append(f"A1 {v.name}: raw={parsed} != value={v.value}")

    # A2 bbox
    for i in range(3):
        dmin = abs(geom_hfss.bbox_min[i] - geom_export.bbox_min[i])
        dmax = abs(geom_hfss.bbox_max[i] - geom_export.bbox_max[i])
        if dmin > rs.bbox_abs_mm or dmax > rs.bbox_abs_mm:
            errors.append(f"A2 bbox axis{i}: Δmin={dmin} Δmax={dmax} > {rs.bbox_abs_mm}")
            break
    details["bbox_delta"] = [
        abs(geom_hfss.bbox_size()[i] - geom_export.bbox_size()[i]) for i in range(3)
    ]

    # A3 volume / COM
    if _rel(geom_hfss.volume, geom_export.volume) > rs.volume_rel:
        errors.append(
            f"A3 volume: hfss={geom_hfss.volume} export={geom_export.volume} rel>{rs.volume_rel}"
        )
    for i in range(3):
        if abs(geom_hfss.com[i] - geom_export.com[i]) > rs.bbox_abs_mm * 10:
            warnings.append(f"A3 COM axis{i} drift")
            break

    # A4 boolean cut
    cv = cut_volume if cut_volume is not None else abs(geom_hfss.volume - geom_export.volume)
    if cv > max(1e-6, rs.volume_rel * max(abs(geom_hfss.volume), 1.0)):
        errors.append(f"A4 cut_volume={cv}")

    # A5 validity
    if not geom_export.valid:
        errors.append("A5 export BRep invalid")
    if not geom_hfss.valid:
        warnings.append("A5 hfss side invalid (check source)")

    # A6 critical dims = 0 err（相对 value 的绝对阈值 1e-6 mm）
    for v in dims.by_role("rf_critical"):
        if label_map and v.name in label_map and abs(label_map[v.name] - v.value) > 1e-6:
            errors.append(f"A6 {v.name}: label={label_map[v.name]} != {v.value}")

    # A7 DXF 闭合（注入式；审查项 R4：原型内核直读文件且启发式回退分支
    # 布尔优先级含混，见 adapters/audit_io 的采集端说明）
    if dxf_closed is not None:
        open_loops = sorted(name for name, ok in dxf_closed.items() if not ok)
        details["dxf_open_loops"] = open_loops
        for name in open_loops:
            errors.append(f"A7 open loop suspected: {name}")

    # A8 snaps
    if snaps is not None:
        mx = max((abs(float(s)) for s in snaps), default=0.0)
        details["max_snap"] = mx
        if mx > rs.snap_max_mm:
            errors.append(f"A8 snap {mx} > {rs.snap_max_mm}")

    # A9 unit fingerprint
    if dims.units.lower() != "mm":
        errors.append(f"A9 units={dims.units}")
    else:
        diag = math.sqrt(sum((geom_export.bbox_size()[i] ** 2) for i in range(3)))
        if not unit_fingerprint_ok(diag):
            errors.append(f"A9 unit fingerprint: bbox_diag={diag:.6g} mm 量级异常")
        details["bbox_diag_mm"] = diag

    # A10 labels
    if label_map is not None:
        for name, val in label_map.items():
            matched = next((v for v in dims.variables if v.name == name), None)
            if matched is None:
                warnings.append(f"A10 label {name} not in dims")
            elif abs(matched.value - val) > 1e-6:
                errors.append(f"A10 {name} label mismatch")

    # A11 non-part names
    for name in geom_export.object_names:
        low = name.lower()
        if any(k in low for k in ("region", "airbox", "pml", "vacuum")):
            errors.append(f"A11 non-part object: {name}")

    # A12 hashes（注入式：None=不判；空 dict=告警）
    if hashes is not None:
        details["hashes"] = dict(hashes)
        if not hashes:
            warnings.append("A12 no files hashed")

    return AuditResult(
        passed=not errors,
        errors=errors,
        warnings=warnings,
        details=details,
    )


def _parse_raw_mm(raw: str) -> float | None:
    s = raw.strip().lower().replace(" ", "")
    if not s:
        return None
    for unit, scale in (("mm", 1.0), ("cm", 10.0), ("um", 1e-3), ("mil", 0.0254), ("in", 25.4)):
        if s.endswith(unit):
            return float(s[: -len(unit)]) * scale
    return float(s)


def unit_fingerprint_ok(bbox_diag_mm: float) -> bool:
    """数量级指纹：零件对角线应落在 1e-2 ~ 1e4 mm（防 inch/µm 滑码）."""
    return 1e-2 <= abs(bbox_diag_mm) <= 1e4
