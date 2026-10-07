"""HFSS 变量 → dims.json 快照（尺寸真源）.

支持：live HFSS（pyAEDT，可选）/ 离线 dict / JSON（测试与批处理）。

审查项 R1（已修）：原型在此模块复制了一份 parse_dim_value/
snapshot_from_dict，单位正则 ``[A-Za-z]*`` 收不下 µ/μ（"5µm" 直接
cannot parse，与 core 版漂移）——本版统一 re-export core 单源。
另：PyAedtDimsPort 缺省写相对 cwd 的 dims.json（审查项 R9，#295 家族
隐患）——保留原签名但 docstring 显式警示调用方传绝对路径。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rfauto.core.fab_export.dims import parse_dim_value, snapshot_from_dict  # 单源 re-export
from rfauto.core.fab_export.schema import DimsDocument

from .artifact_io import save_dims

__all__ = [
    "DictDimsPort",
    "PyAedtDimsPort",
    "parse_dim_value",
    "snapshot_from_dict",
    "write_dims_from_hfss",
]


def write_dims_from_hfss(
    hfss: Any,
    out_path: str | Path,
    part_id: str,
    *,
    rev: str = "A",
    include: list[str] | None = None,
    roles: Mapping[str, str] | None = None,
    tol_classes: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
) -> DimsDocument:
    """从已连接的 pyAEDT Hfss 对象导出设计变量.

    hfss 变量访问：hfss.variable_manager 或 hfss["name"] / design_variables.
    out_path 一律传绝对路径（相对路径随 cwd 漂移，#295 家族）。
    """
    raw_map: dict[str, str] = {}
    vm = getattr(hfss, "variable_manager", None)
    names: list[str]
    if vm is not None and hasattr(vm, "independent_variable_names"):
        names = list(vm.independent_variable_names)
    else:
        # 回退：常见 design property
        try:
            names = list(hfss.get_all_variables())  # type: ignore[attr-defined]
        except Exception:
            names = []
    for name in names:
        if include is not None and name not in include:
            continue
        try:
            raw = hfss.get_evaluated_value(name)  # type: ignore[attr-defined]
        except Exception:
            try:
                raw = str(hfss[name])  # type: ignore[index]
            except Exception:
                continue
        raw_map[name] = str(raw)

    doc = snapshot_from_dict(
        part_id,
        raw_map,
        rev=rev,
        roles=roles,
        tol_classes=tol_classes,
        labels=labels,
        hfss_meta={
            "project": getattr(hfss, "project_name", ""),
            "design": getattr(hfss, "design_name", ""),
            "aedt_version": getattr(hfss, "aedt_version_id", ""),
        },
    )
    save_dims(out_path, doc)
    return doc


class PyAedtDimsPort:
    name = "pyaedt"

    def snapshot(self, context: Any, part_id: str) -> DimsDocument:
        # 注意：写相对 cwd 的 dims.json（原型行为保留）；生产链路请走
        # write_dims_from_hfss 显式绝对路径。
        return write_dims_from_hfss(context, Path("dims.json"), part_id)


class DictDimsPort:
    name = "dict"

    def snapshot(self, context: Any, part_id: str) -> DimsDocument:
        return snapshot_from_dict(part_id, context)
