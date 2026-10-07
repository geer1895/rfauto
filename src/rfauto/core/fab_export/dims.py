"""纯函数：变量解析与 DimsDocument 构建（无 AEDT、无 IO）.

吸收注记（T43 审查项 R1）：原型在 adapters/hfss_dims.py 里复制了一份
parse_dim_value/snapshot_from_dict，且其单位正则 ``[A-Za-z]*`` 收不下
µ/μ，``"5µm"`` 直接抛 cannot parse（core 版可解析）——双源漂移。本包
只保留 core 单源，adapters/fab_export/hfss_dims.py 改为 re-export。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .schema import DimsDocument, VariableDim

# µ/μ（U+00B5/U+03BC）显式进单位段——HFSS 变量回读常见微米写法（R1 修复点）
_UNIT_RE = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-zµμ]*)\s*$"
)

_UNIT_SCALE = {
    "mm": 1.0,
    "millimeter": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "um": 1e-3,
    "mil": 0.0254,
    "in": 25.4,
    "inch": 25.4,
    "": 1.0,
}


def parse_dim_value(raw: str, default_unit: str = "mm") -> float:
    """解析 '2.3mm' / '100um' / '5µm' / '2.54cm' / 裸数字 → mm。"""
    m = _UNIT_RE.match(str(raw))
    if not m:
        raise ValueError(f"cannot parse dimension raw={raw!r}")
    num = float(m.group(1))
    unit = (m.group(2) or default_unit).lower().replace("µ", "u").replace("μ", "u")
    scale = _UNIT_SCALE.get(unit)
    if scale is None:
        raise ValueError(f"unknown unit {unit!r} in {raw!r}")
    return num * scale


def snapshot_from_dict(
    part_id: str,
    variables: Mapping[str, Any],
    *,
    rev: str = "A",
    roles: Mapping[str, str] | None = None,
    tol_classes: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
    standards: Mapping[str, str] | None = None,
    hfss_meta: Mapping[str, Any] | None = None,
    derived: list[dict[str, Any]] | None = None,
) -> DimsDocument:
    """从 {name: raw_or_number} 构建 DimsDocument（raw 字符串保真）."""
    roles = dict(roles or {})
    tol_classes = dict(tol_classes or {})
    labels = dict(labels or {})
    standards = dict(standards or {})
    dims_vars: list[VariableDim] = []
    for name, raw in variables.items():
        raw_s = raw if isinstance(raw, str) else f"{parse_dim_value(repr(raw))}mm"
        val = parse_dim_value(raw_s)
        dims_vars.append(
            VariableDim(
                name=name,
                raw=raw_s,
                value=val,
                role=roles.get(name, "rf_critical" if name in tol_classes else "free"),
                tol_class=tol_classes.get(name, "FREE"),
                drawing_label=labels.get(name, name),
                standard_ref=standards.get(name),
            )
        )
    return DimsDocument(
        part_id=part_id,
        rev=rev,
        units="mm",
        source="hfss",
        variables=dims_vars,
        derived=list(derived or []),
        hfss=dict(hfss_meta or {}),
    )
