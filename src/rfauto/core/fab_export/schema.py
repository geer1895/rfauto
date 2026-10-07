"""数据契约：dims / critical_chars / manifest（L0 纯数据，无 IO）.

单位强制 mm。变量 raw 字符串必须保留（尺寸真源）。
文件读写（dims.json/manifest.json/critical_chars.csv）在
rfauto.adapters.fab_export.artifact_io。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

CSV_HEADER = [
    "char_id",
    "feature",
    "nominal",
    "tol_plus",
    "tol_minus",
    "datum",
    "source_var",
    "meas_method",
    "inspect_pct",
]

_DEFAULT_WCS: dict[str, Any] = {
    "origin": [0, 0, 0],
    "x": [1, 0, 0],
    "y": [0, 1, 0],
    "z": [0, 0, 1],
}


@dataclass
class VariableDim:
    name: str
    raw: str
    value: float
    role: str = "free"  # rf_critical | assembly | free
    tol_class: str = "FREE"
    drawing_label: str = ""
    standard_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VariableDim:
        return cls(
            name=str(d["name"]),
            raw=str(d["raw"]),
            value=float(d["value"]),
            role=str(d.get("role", "free")),
            tol_class=str(d.get("tol_class", "FREE")),
            drawing_label=str(d.get("drawing_label", "")),
            standard_ref=d.get("standard_ref"),
        )


@dataclass
class DimsDocument:
    part_id: str
    rev: str = "A"
    units: str = "mm"
    source: str = "hfss"
    variables: list[VariableDim] = field(default_factory=list)
    derived: list[dict[str, Any]] = field(default_factory=list)
    hfss: dict[str, Any] = field(default_factory=dict)
    wcs: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_WCS))
    schema: str = "fab-dims-1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": self.schema,
            "part_id": self.part_id,
            "rev": self.rev,
            "units": self.units,
            "source": self.source,
            "hfss": self.hfss,
            "wcs": self.wcs,
            "variables": [v.to_dict() for v in self.variables],
            "derived": self.derived,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DimsDocument:
        if str(d.get("units", "mm")).lower() != "mm":
            raise ValueError(f"units must be mm, got {d.get('units')!r}")
        return cls(
            part_id=str(d["part_id"]),
            rev=str(d.get("rev", "A")),
            units="mm",
            source=str(d.get("source", "hfss")),
            variables=[VariableDim.from_dict(x) for x in d.get("variables", [])],
            derived=list(d.get("derived", [])),
            hfss=dict(d.get("hfss", {})),
            wcs=dict(d.get("wcs") or dict(_DEFAULT_WCS)),
        )

    def by_role(self, role: str) -> list[VariableDim]:
        return [v for v in self.variables if v.role == role]


@dataclass
class CriticalChar:
    char_id: str
    feature: str
    nominal: float | None
    tol_plus: float
    tol_minus: float
    datum: str = ""
    source_var: str = ""
    meas_method: str = ""
    inspect_pct: int = 100

    def to_row(self) -> list[str]:
        return [
            self.char_id,
            self.feature,
            "" if self.nominal is None else str(self.nominal),
            str(self.tol_plus),
            str(self.tol_minus),
            self.datum,
            self.source_var,
            self.meas_method,
            str(self.inspect_pct),
        ]


def critical_char_to_row(c: CriticalChar) -> list[str]:
    """行序列化（CSV 写出在 adapters.artifact_io，本函数保持纯）。"""
    return c.to_row()


def flange_critical_chars(flange_name: str = "FBP100") -> list[CriticalChar]:
    """法兰族检验特性（细则 §1.1c CMM 清单的可数据化子集，§1.3 CH-004 模板）.

    平面度/垂直度无名义值（nominal=None，CSV 空列），只带公差与检验方法——
    与细则金样 critical_chars.csv 示例 CH-004 同形态。销孔 H7 取
    Ø1.6–3 段 H7 公差带（ES=+0.010，EI=0，GB/T 1800.1）。
    """
    from .standards import get_flange  # 局部 import 防环（standards 不依赖 schema）

    fl = get_flange(flange_name)
    return [
        CriticalChar(
            char_id="CH-F01",
            feature=f"法兰贴合面平面度（{fl.name}）",
            nominal=None,
            tol_plus=fl.flatness,
            tol_minus=0.0,
            datum="A",
            source_var=f"std:{fl.name}",
            meas_method="刀口尺/平晶/CMM",
            inspect_pct=50,
        ),
        CriticalChar(
            char_id="CH-F02",
            feature="法兰对轴线垂直度（mm/100mm）",
            nominal=None,
            tol_plus=fl.perpendicularity,
            tol_minus=0.0,
            datum="A",
            source_var=f"std:{fl.name}",
            meas_method="CMM",
            inspect_pct=50,
        ),
        CriticalChar(
            char_id="CH-F03",
            feature=f"螺栓孔位置度（{fl.bolt_count}xØ{fl.bolt_dia:g}）",
            nominal=None,
            tol_plus=0.05,
            tol_minus=0.05,
            datum="A",
            source_var=f"std:{fl.name}",
            meas_method="CMM/位置度规",
            inspect_pct=100,
        ),
        CriticalChar(
            char_id="CH-F04",
            feature=f"销孔 Ø{fl.pin_dia:g} H7（{fl.pin_count}x）",
            nominal=fl.pin_dia,
            tol_plus=0.010,
            tol_minus=0.0,
            datum="A",
            source_var=f"std:{fl.name}",
            meas_method="塞规/CMM",
            inspect_pct=100,
        ),
    ]


@dataclass
class Manifest:
    part_id: str
    rev: str
    units: str = "mm"
    formats: list[str] = field(default_factory=lambda: [".x_t", ".step"])
    wcs: dict[str, Any] = field(default_factory=dict)
    export_tool: str = "fab_export"
    heal_log: list[dict[str, Any]] = field(default_factory=list)
    audit_gate: dict[str, Any] = field(default_factory=dict)
    hashes: dict[str, str] = field(default_factory=dict)
    objects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Manifest:
        if str(d.get("units", "mm")).lower() != "mm":
            raise ValueError("manifest.units must be mm")
        return cls(
            part_id=str(d["part_id"]),
            rev=str(d.get("rev", "A")),
            units="mm",
            formats=list(d.get("formats", [".x_t", ".step"])),
            wcs=dict(d.get("wcs") or {}),
            export_tool=str(d.get("export_tool", "fab_export")),
            heal_log=list(d.get("heal_log") or []),
            audit_gate=dict(d.get("audit_gate") or {}),
            hashes=dict(d.get("hashes") or {}),
            objects=list(d.get("objects") or []),
        )
