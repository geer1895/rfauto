"""fab_export 适配器层（HFSS→可机加交付包；可替换插件 + 文件 IO）.

自 E:\\协助调研\\cad导出 原型吸收（T43，2026-09-29）。重依赖纪律：
pyaedt / ezdxf / matplotlib / OCP 全部惰性 import（函数体内），
import 本包不需要任何可选依赖。
"""

from .artifact_io import (
    load_critical_chars,
    load_dims,
    load_manifest,
    load_ruleset,
    save_critical_chars,
    save_dims,
    save_manifest,
)
from .audit_io import audit_package_with_dir, dxf_closed_map, file_hashes
from .base import (
    DimsPort,
    DrawPort,
    ExportRequest,
    ExportResult,
    FabPortRegistry,
    GeometryExportPort,
    GeometryReadPort,
    PackPort,
    PluginInfo,
    ensure_builtin_plugins,
    get_registry,
    load_entry_point_plugins,
    register_builtin_plugins,
)
from .composite_dxf import read_composite_dxf, write_composite_dxf
from .dxf_truth import compare_dxf_to_truth

__all__ = [
    "DimsPort",
    "DrawPort",
    "ExportRequest",
    "ExportResult",
    "FabPortRegistry",
    "GeometryExportPort",
    "GeometryReadPort",
    "PackPort",
    "PluginInfo",
    "audit_package_with_dir",
    "compare_dxf_to_truth",
    "dxf_closed_map",
    "ensure_builtin_plugins",
    "file_hashes",
    "get_registry",
    "load_critical_chars",
    "load_dims",
    "load_entry_point_plugins",
    "load_manifest",
    "load_ruleset",
    "read_composite_dxf",
    "register_builtin_plugins",
    "save_critical_chars",
    "save_dims",
    "save_manifest",
    "write_composite_dxf",
]
