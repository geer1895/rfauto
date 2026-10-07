"""pyAEDT 清洗 + 双格式导出（x_t + step）.

本模块在无 AEDT 环境下可 import（pyaedt 零顶层 import，调用 live API
时才需要）；所有 heal 参数走「RF 保守预设」。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import ExportRequest

NON_PART_KEYWORDS = (
    "region",
    "air",
    "vacuum",
    "pml",
    "port",
    "sheet",
    "lumped",
    "rad",
    "febi",
)

EXPORT_FORMATS = (".x_t", ".step")


@dataclass
class ExportReport:
    ok: bool
    formats: list[str] = field(default_factory=list)
    exported_objects: list[str] = field(default_factory=list)
    skipped_objects: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    heal_log: list[dict[str, Any]] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)


def is_non_part(name: str, extra_keywords: Sequence[str] = ()) -> bool:
    low = name.lower()
    keys = tuple(NON_PART_KEYWORDS) + tuple(extra_keywords)
    return any(k in low for k in keys)


def filter_export_objects(
    names: Iterable[str],
    *,
    keep: Iterable[str] | None = None,
    drop: Iterable[str] | None = None,
    extra_non_part: Sequence[str] = (),
) -> tuple[list[str], list[str]]:
    """返回 (export_list, skipped)."""
    keep_set = set(keep) if keep is not None else None
    drop_set = set(drop or ())
    exported: list[str] = []
    skipped: list[str] = []
    for n in names:
        if n in drop_set or is_non_part(n, extra_non_part):
            skipped.append(n)
            continue
        if keep_set is not None and n not in keep_set:
            skipped.append(n)
            continue
        exported.append(n)
    return exported, skipped


def conservative_heal_kwargs() -> dict[str, Any]:
    """RF 制造保守 heal 预设（细则 §10.3 表逐参数对齐，禁止吃掉 iris/孔/倒角）.

    对 pyaedt 1.x ``Modeler3D.heal_objects`` 实测签名逐参数核对（2026-09-29，
    pyaedt 1.4.0）：官方缺省 ``geometry_simplification_tolerance=1``（mm！
    细则明示「1mm 会吃掉 iris」）与 ``allowable_volume_change=5``（%）均须
    收紧；孔/倒角/圆角移除全关。simplify_geometry=False 与简化容差双保险
    （防未来标志翻转时缺省容差回归）。
    """
    return dict(
        auto_heal=False,
        tolerant_stitch=True,
        simplify_geometry=False,
        geometry_simplification_tolerance=0.001,
        tighten_gaps=True,
        heal_to_solid=False,
        max_stitch_tolerance=0.001,
        explode_and_stitch=True,
        tighten_gaps_width=1e-5,
        remove_silver_faces=True,
        remove_small_edges=True,
        remove_small_faces=True,
        remove_holes=False,
        remove_chamfers=False,
        remove_blends=False,
        allowable_surface_area_change=0.01,
        allowable_volume_change=0.01,
    )


def conservative_import_kwargs() -> dict[str, Any]:
    """import_3d_cad 生产钉法（细则 §10.2，pyaedt 1.4.0 签名核对）.

    禁 Auto 单位（input_file_unit 缺省 Auto 是文档明示陷阱）；先不 heal；
    reduce_stl 以签名为准（细则：文档正文写 True 系笔误）。
    """
    return dict(
        healing=False,
        point_coincidence_tolerance=1e-6,
        merge_planar_faces=True,
        merge_angle=0.02,
        input_file_unit="mm",
        reduce_stl=False,
    )


def _object_volume(modeler: Any, assignment: str) -> float | None:
    """对象体积 best-effort 读取（heal_log 前后体积用；失败返回 None 不阻塞）."""
    objects = getattr(modeler, "objects", None)
    try:
        if isinstance(objects, dict) and assignment in objects:
            return float(objects[assignment].volume)
    except Exception:
        return None
    return None


def heal_for_fab(hfss: Any, assignment: str) -> dict[str, Any]:
    """执行保守 heal 并返回 heal_log 项.

    heal_log 记 参数+前后体积（细则 §10.3「每次 heal 必须写 heal_log
    （参数+前后体积）」；体积 best-effort——拿不到记 None 不阻塞主路径，
    #105 家法）。
    """
    kwargs = conservative_heal_kwargs()
    modeler = getattr(hfss, "modeler", hfss)
    volume_before = _object_volume(modeler, assignment)
    ok = modeler.heal_objects(assignment=assignment, **kwargs)
    volume_after = _object_volume(modeler, assignment)
    return {
        "assignment": assignment,
        "ok": bool(ok),
        "params": kwargs,
        "volume_before": volume_before,
        "volume_after": volume_after,
    }


def import_for_fab(hfss: Any, path: str | Path) -> dict[str, Any]:
    """按保守预设导入 STEP/x_t（细则 §10.2；live 面，无 AEDT 时不调用）."""
    modeler = getattr(hfss, "modeler", hfss)
    kwargs = conservative_import_kwargs()
    ok = modeler.import_3d_cad(str(path), **kwargs)
    return {"path": str(path), "ok": bool(ok), "params": kwargs}


def export_fab_geometry(
    hfss: Any,
    out_dir: str | Path,
    *,
    part_name: str = "part",
    keep: Iterable[str] | None = None,
    drop: Iterable[str] | None = None,
    formats: Sequence[str] = EXPORT_FORMATS,
    do_heal: bool = False,
    extra_non_part: Sequence[str] = (),
) -> ExportReport:
    """清洗后导出多格式实体.

    - 显式 assignment_to_export 白名单
    - 双格式 .x_t + .step（生产默认）
    - 可选 conservative heal
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = ExportReport(ok=True)

    modeler = getattr(hfss, "modeler", hfss)
    try:
        all_names = list(getattr(modeler, "object_names", []) or [])
    except Exception as e:
        report.ok = False
        report.errors.append(f"list objects failed: {e}")
        return report

    export_list, skipped = filter_export_objects(
        all_names, keep=keep, drop=drop, extra_non_part=extra_non_part
    )
    report.exported_objects = export_list
    report.skipped_objects = skipped
    if not export_list:
        report.ok = False
        report.errors.append("no exportable solids after filter")
        return report

    if do_heal:
        for name in export_list:
            try:
                report.heal_log.append(heal_for_fab(hfss, name))
            except Exception as e:
                report.heal_log.append({"assignment": name, "ok": False, "error": str(e)})

    for fmt in formats:
        path = out / (part_name + fmt)
        try:
            ok = modeler.export_3d_model(
                file_name=part_name,
                file_path=str(out),
                file_format=fmt,
                assignment_to_export=export_list,
                assignment_to_remove=["Region"],
            )
            report.paths[fmt] = str(path)
            if not ok:
                report.ok = False
                report.errors.append(f"export failed: {fmt}")
        except Exception as e:
            report.ok = False
            report.errors.append(f"export {fmt} exception: {e}")
            report.paths[fmt] = str(path)

    report.formats = list(formats)
    return report


def write_heal_log(path: str | Path, log: Sequence[dict[str, Any]]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(list(log), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ─── 插件端口实现 ─────────────────────────────────────────────


class PyAedtGeometryExporter:
    name = "pyaedt"

    def export(self, context: Any, req: ExportRequest) -> ExportReport:
        return export_fab_geometry(
            context,
            req.out_dir,
            part_name=req.part_name,
            keep=req.keep,
            drop=req.drop,
            formats=req.formats,
            do_heal=req.do_heal,
            extra_non_part=req.extra_non_part,
        )


class MockGeometryExporter:
    """无 AEDT 时占位：不产出实体，供联调."""

    name = "mock"

    def export(self, context: Any, req: ExportRequest) -> ExportReport:
        return ExportReport(ok=True, formats=list(req.formats), errors=[])
