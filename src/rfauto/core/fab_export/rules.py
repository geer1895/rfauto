"""工艺公差规则库（西夏 RF v0 + 可覆盖）——纯数据与 dict 装载.

文件读取（yaml → dict）在 adapters/fab_export/artifact_io.load_ruleset；
本模块只收已解析的 data dict（L0 零 IO）。原型里 pyyaml 缺席时的
``_minimal_yaml_tolerant`` 手写解析器不吸收：PyYAML 在本仓随 omegaconf
传递可得且 extras 已显式声明（审查项 R13）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TolClass:
    name: str
    plus: float = 0.05
    minus: float = 0.05
    ra: float | None = None
    fit: str | None = None
    note: str = ""


@dataclass
class RuleSet:
    name: str = "xixia_rf_v0"
    units: str = "mm"
    tol_classes: dict[str, TolClass] = field(default_factory=dict)
    finish: dict[str, Any] = field(default_factory=dict)
    chamfer_inside: str = "≤0.1x45"
    snap_max_mm: float = 1e-4
    volume_rel: float = 1e-9
    bbox_abs_mm: float = 1e-6
    kerr_linear_pct: float = 0.5
    kerr_r_max_frac_of_a: float = 0.10

    def tol_for(self, class_name: str) -> TolClass:
        return self.tol_classes.get(class_name) or self.tol_classes.get("FREE") or TolClass("FREE")


def default_ruleset() -> RuleSet:
    return RuleSet(
        name="xixia_rf_v0",
        tol_classes={
            "IRIS": TolClass("IRIS", 0.02, 0.02, ra=0.8, note="耦合窗/iris"),
            "WG_AB": TolClass("WG_AB", 0.03, 0.03, ra=0.8, note="波导内腔 a,b；可收严 ±0.02"),
            "CAV_H": TolClass("CAV_H", 0.03, 0.03, ra=0.8),
            "PIN_H7": TolClass("PIN_H7", 0.0, 0.0, fit="H7", note="销孔"),
            "FLAT_FLANGE": TolClass("FLAT_FLANGE", 0.03, 0.03, note="法兰平面度 0.02~0.03"),
            "THD": TolClass("THD", 0.0, 0.0, fit="6H", note="有效牙深+底孔(牙深+3~5P)"),
            "FREE": TolClass("FREE", 0.05, 0.05, note="GB/T 1804-m"),
            "THz": TolClass("THz", 0.01, 0.01, ra=0.4, note="再收紧 30~50%"),
        },
        finish={
            "aluminum": "导电氧化 或 外漆+内酸洗",
            "copper_silver_um": 5,
            "copper_silver_q_high_um": "5-8",
        },
    )


def ruleset_from_data(data: dict[str, Any] | None) -> RuleSet:
    """从已解析的规则 dict 覆盖缺省规则库（未知键忽略，类型不协从宽）."""
    base = default_ruleset()
    if not isinstance(data, dict):
        return base
    base.name = str(data.get("ruleset", base.name))
    tcs = data.get("tol_classes") or {}
    if isinstance(tcs, dict):
        for name, spec in tcs.items():
            if not isinstance(spec, dict):
                continue
            old = base.tol_classes.get(name) or TolClass(name)
            base.tol_classes[name] = TolClass(
                name=name,
                plus=float(spec.get("plus", old.plus)),
                minus=float(spec.get("minus", old.minus)),
                ra=spec.get("ra", old.ra),
                fit=spec.get("fit", old.fit),
                note=str(spec.get("note", old.note)),
            )
    audit = data.get("audit") or {}
    if isinstance(audit, dict):
        base.snap_max_mm = float(audit.get("snap_max_mm", base.snap_max_mm))
        base.volume_rel = float(audit.get("volume_rel", base.volume_rel))
        base.bbox_abs_mm = float(audit.get("bbox_abs_mm", base.bbox_abs_mm))
    if "finish" in data and isinstance(data["finish"], dict):
        base.finish.update(data["finish"])
    return base
