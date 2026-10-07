"""fab_export 纯领域层（L0：零文件 IO、零 AEDT/ezdxf 依赖）.

HFSS → 可机加交付包的数据契约与判据内核，自 E:\\协助调研\\cad导出 原型
（fab-export 0.2.1）吸收（T43，2026-09-29）。与原型的分层差异：

- 原型 core 里的文件 IO（save_dims/load_ruleset/write_qif3/write_gcode/
  file_hashes 等）全部挪到 adapters/fab_export（artifact_io/audit_io/
  qif_io/cam_io）——本包只做纯函数与数据类；
- audit_package 的 A7（DXF 闭合）/A12（哈希）由调用方注入已采集的
  ``dxf_closed`` / ``hashes`` 映射，目录扫描在 adapters.audit_io。
"""

from .audit import (
    AUDIT_CHECKS,
    AuditResult,
    GeometrySummary,
    audit_package,
    unit_fingerprint_ok,
)
from .composite_layer import (
    COMPOSITE_LAYERS,
    CompositeLayers,
    CompositeObject,
    RemovedHole,
    classify_object,
    filter_unsupported_holes,
    group_composite_layers,
)
from .dims import parse_dim_value, snapshot_from_dict
from .dxf_compare import (
    dedup_circles,
    dedup_segments,
    match_geometry,
    normalize_y,
    shift_y,
)
from .gcode import (
    GcodeProgram,
    ToolpathOp,
    ToolSpec,
    build_wr90_program,
    contour_op,
    drill_op,
    pocket_op,
)
from .infer import infer_mapping, infer_role_and_tol, split_mapping
from .process_notes import (
    dfm_notes,
    finish_allowance,
    finish_note,
    fit_note,
    process_tag_for,
    thread_note,
)
from .qif3 import render_qif3_document
from .qif_cam import render_cam_notes, render_mbd_note, render_qif_characteristics
from .rules import RuleSet, TolClass, default_ruleset, ruleset_from_data
from .schema import (
    CSV_HEADER,
    CriticalChar,
    DimsDocument,
    Manifest,
    VariableDim,
    critical_char_to_row,
    flange_critical_chars,
)
from .standards import (
    FIT_BANDS_MM,
    FLANGES,
    KERR_RULES,
    WAVEGUIDES,
    WaveguideSpec,
    catalog_tables,
    get_flange,
    get_waveguide,
)
from .views import ViewGeometry, build_wr90_views, flange_hole_table, rect

__all__ = [
    "AUDIT_CHECKS",
    "COMPOSITE_LAYERS",
    "CSV_HEADER",
    "FIT_BANDS_MM",
    "FLANGES",
    "KERR_RULES",
    "WAVEGUIDES",
    "AuditResult",
    "CompositeLayers",
    "CompositeObject",
    "CriticalChar",
    "DimsDocument",
    "GcodeProgram",
    "GeometrySummary",
    "Manifest",
    "RemovedHole",
    "RuleSet",
    "TolClass",
    "ToolSpec",
    "ToolpathOp",
    "VariableDim",
    "ViewGeometry",
    "WaveguideSpec",
    "audit_package",
    "build_wr90_program",
    "build_wr90_views",
    "catalog_tables",
    "classify_object",
    "contour_op",
    "critical_char_to_row",
    "dedup_circles",
    "dedup_segments",
    "default_ruleset",
    "dfm_notes",
    "drill_op",
    "filter_unsupported_holes",
    "finish_allowance",
    "finish_note",
    "fit_note",
    "flange_critical_chars",
    "flange_hole_table",
    "get_flange",
    "get_waveguide",
    "group_composite_layers",
    "infer_mapping",
    "infer_role_and_tol",
    "match_geometry",
    "normalize_y",
    "parse_dim_value",
    "pocket_op",
    "process_tag_for",
    "rect",
    "render_cam_notes",
    "render_mbd_note",
    "render_qif3_document",
    "render_qif_characteristics",
    "ruleset_from_data",
    "shift_y",
    "snapshot_from_dict",
    "split_mapping",
    "thread_note",
    "unit_fingerprint_ok",
]
