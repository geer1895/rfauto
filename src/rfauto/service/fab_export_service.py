"""fab_export service——HFSS → 可机加交付包编排（JSON 进出信封）.

自 E:\\协助调研\\cad导出 原型 service/go_service.py + cli.py 业务段吸收
（T43，2026-09-29）。家法对齐：

- service 层 JSON 进出：全部公开函数返回 dict 信封（ok/errors/...），
  CLI/MCP 是薄壳；
- 原型 cmd_snapshot/cmd_draw/cmd_audit/cmd_pack/cmd_pipeline 等约 300 行
  业务逻辑内联在 argparse CLI 里，本版全部下沉 service；
- 审查项 R3（已修）：原型 go_service 同时 import core.dims 与
  adapters.hfss_dims 的同名 snapshot_from_dict（后者遮蔽前者，双源漂移
  隐患）——本版只 import core 单源。

JobHandle 评估（任务书问句）：离线链（vars→包）实测秒级（DXF+PDF+gcode
渲染），不需 JobHandle；``go_from_hfss`` 真机 AEDT 导出面可能超 10min，
接 hfss_session 真机通道时应转 JobHandle——本批零引擎仿真，该项留
followUp（真机接线时评估）。
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rfauto.adapters.fab_export.artifact_io import (
    load_dims,
    load_ruleset,
    save_critical_chars,
    save_dims,
)
from rfauto.adapters.fab_export.audit_io import audit_package_with_dir, geometry_summary_from_dict
from rfauto.adapters.fab_export.cam_io import write_cam_report, write_gcode
from rfauto.adapters.fab_export.composite_dxf import read_composite_dxf, write_composite_dxf
from rfauto.adapters.fab_export.dxf_truth import compare_dxf_to_truth
from rfauto.adapters.fab_export.ezdxf_draw import (
    DrawingConfig,
    default_notes,
    export_dxf_pdf,
    render_drawing,
)
from rfauto.adapters.fab_export.face_dxf import rect_loop, wr90_inner_loop, wr90_outer_loop, write_face_dxf
from rfauto.adapters.fab_export.multisheet import render_two_sheet
from rfauto.adapters.fab_export.pack_store import (
    pack_deliverable,
    rfq_checklist,
    write_btp_cover,
    write_capability_table,
)
from rfauto.adapters.fab_export.pcb_notes import write_pcb_checklist
from rfauto.adapters.fab_export.qif_io import (
    write_cam_notes,
    write_mbd_note,
    write_qif3_document,
    write_qif_characteristics,
)
from rfauto.core.fab_export.audit import GeometrySummary
from rfauto.core.fab_export.composite_layer import (
    CompositeObject,
    filter_unsupported_holes,
    group_composite_layers,
)
from rfauto.core.fab_export.dims import snapshot_from_dict
from rfauto.core.fab_export.gcode import build_wr90_program
from rfauto.core.fab_export.infer import split_mapping
from rfauto.core.fab_export.process_notes import process_tag_for
from rfauto.core.fab_export.rules import RuleSet, default_ruleset
from rfauto.core.fab_export.schema import CriticalChar, DimsDocument, flange_critical_chars
from rfauto.core.fab_export.standards import catalog_tables
from rfauto.service.envelope import error_envelope, ok_envelope

#: 离线几何包络估计的标称板厚（F-4/S3：1.27mm=50mil FR4 标称，
#: 0.050in×25.4——STEP 缺席/读取失败时的 A·L·t 体积与重心 z=t/2 估计值，
#: 非真实几何；geometry_source=envelope_estimate 已在产物标注）。
_BOARD_THICKNESS_MM = 1.27
#: 同上，重心 z=半板厚。
_BOARD_MID_Z_MM = _BOARD_THICKNESS_MM / 2


@dataclass
class GoResult:
    ok: bool
    package_dir: Path
    audit_passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    message: str = ""
    #: 几何溯源（R3-2）："step"=真实 STEP/HFSS 几何，
    #: "envelope_estimate"=STEP 读失败后的变量包络估计。
    geometry_source: str = "step"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "package_ready": self.audit_passed and self.ok,
            "package_dir": str(self.package_dir),
            "audit_passed": self.audit_passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "files": self.files,
            "message": self.message,
            "geometry_source": self.geometry_source,
        }


# ─── 一键编排（go） ──────────────────────────────────────────────────


def go_from_vars(
    vars_path: str | Path,
    out_dir: str | Path | None = None,
    *,
    rules_path: str | Path | None = None,
    work_dir: str | Path | None = None,
    material: str = "AL6061-T6",
    open_folder: bool = False,
) -> GoResult:
    """离线/预生成：变量 JSON → 全套交付（自动审计+PDF+轮廓+清单）."""
    vars_path = Path(vars_path)
    rules = load_ruleset(rules_path)
    data = json.loads(vars_path.read_text(encoding="utf-8"))
    part_id = str(data.get("part_id") or vars_path.stem)
    rev = str(data.get("rev", "A"))
    raw_vars: dict[str, Any] = dict(data.get("variables") or {
        k: v for k, v in data.items() if k not in {
            "part_id", "rev", "roles", "tol_classes", "labels", "standards", "derived", "hfss",
        }
    })

    roles, tols = split_mapping(raw_vars.keys())
    roles.update(data.get("roles") or {})
    tols.update(data.get("tol_classes") or {})

    dims = snapshot_from_dict(
        part_id,
        raw_vars,
        rev=rev,
        roles=roles,
        tol_classes=tols,
        labels=data.get("labels"),
        standards=data.get("standards"),
        hfss_meta=data.get("hfss"),
        derived=data.get("derived"),
    )
    return _finish_package(
        dims,
        out_dir=out_dir,
        work_dir=work_dir,
        rules=rules,
        material=material,
        open_folder=open_folder,
        geom=None,
        extra_files={},
    )


def go_from_hfss(
    project: str | Path | None,
    design: str | None,
    out_dir: str | Path,
    *,
    part_name: str = "part",
    rules_path: str | Path | None = None,
    material: str = "AL6061-T6",
    keep: Sequence[str] | None = None,
    drop: Sequence[str] | None = None,
    do_heal: bool = False,
    open_folder: bool = False,
    hfss: Any = None,
) -> GoResult:
    """真 HFSS：导出 x_t/step + 变量快照 + 出图 + 自动审计 + 打包.

    hfss: 可注入已连接的 pyAEDT 对象；否则按 project/design 连接（需 AEDT）。
    """
    rules = load_ruleset(rules_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    # 1) 连接 / 使用注入的 hfss
    own = False
    if hfss is None:
        try:
            from ansys.aedt.core import Hfss  # type: ignore
        except Exception as e:
            return GoResult(False, out, False, [f"pyAEDT/AEDT 不可用: {e}"], [],
                            message="请在装有 AEDT 的机器上运行，或改用 go --vars")
        try:
            hfss = Hfss(project=str(project) if project else None,
                        design=design,
                        non_graphical=True,
                        new_desktop=False)
            own = True
        except Exception as e:
            return GoResult(False, out, False, [f"HFSS 连接失败: {e}"], [],
                            message="检查 .aedt 路径/design 名称")

    try:
        # 2) 清洗导出
        from rfauto.adapters.fab_export.hfss_export import export_fab_geometry

        report = export_fab_geometry(
            hfss,
            out,
            part_name=part_name,
            keep=keep,
            drop=drop,
            do_heal=do_heal,
        )
        errors.extend(report.errors)

        # 3) 变量快照 + 自动推断
        names: list[str] = []
        vm = getattr(hfss, "variable_manager", None)
        if vm is not None and hasattr(vm, "independent_variable_names"):
            names = list(vm.independent_variable_names)
        raw_map: dict[str, str] = {}
        for n in names:
            try:
                raw_map[n] = str(hfss.get_evaluated_value(n))
            except Exception:
                try:
                    raw_map[n] = str(hfss[n])
                except Exception:
                    continue
        roles, tols = split_mapping(raw_map.keys())
        dims = snapshot_from_dict(
            part_name,
            raw_map,
            roles=roles,
            tol_classes=tols,
            hfss_meta={
                "project": getattr(hfss, "project_name", ""),
                "design": getattr(hfss, "design_name", ""),
                "aedt_version": getattr(hfss, "aedt_version_id", ""),
            },
        )
        save_dims(out / "dims.json", dims)

        # 4) 几何摘要（若能从 modeler 取 bbox）
        geom = _geometry_from_hfss(hfss, report.exported_objects)

        extra: dict[str, str] = {}
        for fmt, p in report.paths.items():
            key = "xt" if fmt in (".x_t", ".x_b") else ("step" if "step" in fmt or "stp" in fmt else fmt)
            extra[key] = p

        return _finish_package(
            dims,
            out_dir=out,
            work_dir=out,
            rules=rules,
            material=material,
            open_folder=open_folder,
            geom=geom,
            extra_files=extra,
            heal_log=report.heal_log,
            pre_errors=errors,
            objects=report.exported_objects,
        )
    except Exception as e:
        return GoResult(False, out, False, [*errors, str(e)], [], message="异常退出")
    finally:
        if own and hfss is not None:
            with contextlib.suppress(Exception):
                hfss.release_desktop(close_projects=False, close_desktop=False)


def _geometry_from_hfss(hfss: Any, objects: Sequence[str]) -> GeometrySummary | None:
    try:
        modeler = getattr(hfss, "modeler", hfss)
        boxes = []
        for name in objects[:32]:
            bb = None
            for meth in ("get_object_bounding_box", "getBoundingBox"):
                if hasattr(modeler, meth):
                    try:
                        bb = getattr(modeler, meth)(name)
                        break
                    except Exception:
                        continue
            if bb and len(bb) >= 6:
                boxes.append([float(x) for x in bb[:6]])
        if not boxes:
            return None
        arr = [[b[0], b[1], b[2], b[3], b[4], b[5]] for b in boxes]
        bmin = [min(row[i] for row in arr) for i in range(3)]
        bmax = [max(row[i] for row in arr) for i in range(3)]
        vol = float(max(bmax[0] - bmin[0], 0.0) * max(bmax[1] - bmin[1], 0.0) * max(bmax[2] - bmin[2], 0.0))
        return GeometrySummary(
            bbox_min=(bmin[0], bmin[1], bmin[2]),  # type: ignore[arg-type]
            bbox_max=(bmax[0], bmax[1], bmax[2]),  # type: ignore[arg-type]
            volume=vol,
            com=((bmin[0] + bmax[0]) / 2, (bmin[1] + bmax[1]) / 2, (bmin[2] + bmax[2]) / 2),
            valid=True,
            solid_count=max(1, len(objects)),
            object_names=list(objects),
        )
    except Exception:
        return None


def _finish_package(
    dims: DimsDocument,
    *,
    out_dir: str | Path | None,
    work_dir: str | Path | None,
    rules: RuleSet,
    material: str,
    open_folder: bool,
    geom: GeometrySummary | None,
    extra_files: dict[str, str | Path],
    heal_log: Sequence[dict[str, Any]] = (),
    pre_errors: Sequence[str] = (),
    objects: Sequence[str] | None = None,
) -> GoResult:
    part_id, rev = dims.part_id, dims.rev
    work = Path(work_dir or (Path(out_dir) if out_dir else Path.cwd() / "fab_out") / "_work")
    if out_dir:
        pkg = Path(out_dir)
    else:
        # 主方案 §5.1 目录口径 fab_<part>_<rev>_<date>（显式 out_dir 时不改写）
        from datetime import date as _date

        pkg = work.parent / f"fab_{part_id}_{rev}_{_date.today():%Y%m%d}"
    work.mkdir(parents=True, exist_ok=True)
    pkg.mkdir(parents=True, exist_ok=True)

    # critical chars（无 rf_critical 时全变量兜底——原型行为保留）
    # + 法兰族检验特性（细则 §1.1c CMM 清单：平面度/垂直度/孔位/销孔 H7）
    chars = []
    for i, v in enumerate(dims.by_role("rf_critical") or dims.variables, 1):
        tol = rules.tol_for(v.tol_class)
        chars.append(
            CriticalChar(
                char_id=f"CH-{i:03d}",
                feature=v.drawing_label or v.name,
                nominal=v.value,
                tol_plus=tol.plus,
                tol_minus=tol.minus,
                datum="A",
                source_var=v.name,
                meas_method="三坐标/影像",
                inspect_pct=100 if v.role == "rf_critical" else 50,
            )
        )
    with contextlib.suppress(Exception):
        chars.extend(flange_critical_chars())
    chars_path = work / "critical_chars.csv"
    save_critical_chars(chars_path, chars)
    qif_path = write_qif_characteristics(work / "qif_characteristics.xml", chars, part_id=part_id)
    qif3_path = write_qif3_document(work / "qif3_document.xml", dims, chars)
    cam_path = write_cam_notes(work / "cam_notes.md", dims)
    mbd_path = write_mbd_note(work / "mbd_note.md", part_id)
    # CAM 刀路 + G 代码
    try:
        prog = build_wr90_program()
        gcode_path = write_gcode(work / "cam_ops.nc", prog)
        camrep_path = write_cam_report(work / "cam_ops_report.md", prog)
    except Exception:
        gcode_path = camrep_path = None
    # 3D 文档包
    try:
        from rfauto.adapters.fab_export.doc3d import write_3d_pdf, write_gltf_from_dims, write_html_viewer

        gltf_path = write_gltf_from_dims(work / "model.gltf", dims)
        html3d_path = write_html_viewer(work / "model_3d.html", dims, gltf_rel="model.gltf")
        pdf3d_path = write_3d_pdf(work / "model_3d.pdf", dims)
    except Exception:
        gltf_path = html3d_path = pdf3d_path = None
    # SpaceClaim 脚本（解耦，无 SC 也生成）
    try:
        from rfauto.adapters.fab_export.spaceclaim import HealRequest, SpaceClaimScriptHealer

        sc = SpaceClaimScriptHealer().heal(
            HealRequest(
                input_step=work / "part.step",
                output_step=work / "part.healed.step",
                log_path=work / "spaceclaim_heal.log",
            )
        )
        sc_script = Path(sc.script_path) if sc.script_path else None
    except Exception:
        sc_script = None
    dims_path = work / "dims.json"
    save_dims(dims_path, dims)

    # 2.5D 轮廓：有 a 变量则 WR 类，否则外接矩形
    L = next((v.value for v in dims.variables if v.name.lower() in ("l", "length", "total_len")), None)
    A = next((v.value for v in dims.variables if v.name in ("A_outer", "A", "w", "width")), None)
    a = next((v.value for v in dims.variables if v.name == "a"), None)
    if L is None:
        L = 60.0
    if A is None:
        A = (a + 2 * _BOARD_THICKNESS_MM) if a else 25.4
    face_path = work / "faces_top.dxf"
    loops = [("OUT", wr90_outer_loop(L) if a else rect_loop(0, 0, A, L))]
    if a:
        loops.append(("POCKET", wr90_inner_loop(L, a=a)))
    else:
        loops.append(("POCKET", rect_loop(2, 2, max(A - 4, 1), max(L - 4, 1))))
    write_face_dxf(face_path, loops, circles=[("HOLE", (A / 2, min(5.0, L / 4)), 1.6)])

    # 图纸 + PDF（含工艺标注；默认图注含 DFM 行——dims 传入后深窄槽穿丝/
    # 型腔基准/薄壁警示自动追加；表处/螺纹通式在默认图注 5/6 条内，
    # 此处只补 per-variable 工艺标签聚合行，行数受控防图面碰撞）
    notes = default_notes(rules, dims)
    tags: list[str] = []
    for v in dims.variables:
        tag = process_tag_for(v.name)
        if v.role == "rf_critical" and f"{v.drawing_label or v.name}: {tag}" not in tags:
            tags.append(f"{v.drawing_label or v.name}: {tag}")
    if tags:
        notes.append(f"{len(notes) + 1}. 工艺: " + "；".join(tags))
    drawing_path = work / "drawing.dxf"
    try:
        render_two_sheet(drawing_path, dims, chars, rules=rules)
    except Exception:
        render_drawing(
            drawing_path,
            dims,
            config=DrawingConfig(
                part_id=dims.part_id,
                rev=dims.rev,
                part_name=part_id,
                material=material,
                notes=notes,
            ),
            rules=rules,
        )
    pdf_path = export_dxf_pdf(drawing_path, work / "drawing.pdf")

    # 几何：优先读 STEP（OCP），缺省用变量包络。
    # 溯源（R3-2，runs/review_ge8e/f3_fix/REPORT.md）：STEP 读失败/缺失的
    # 静默回退不再无痕——geometry_source 落进 go_result（"step" |
    # "envelope_estimate"），回退分支同时追加 warning，发厂包两种几何
    # 来源可辨（诚实分级面）。
    geometry_source = "step"
    geometry_warnings: list[str] = []
    geom_real = None
    for cand in (pkg / "part.step", work / "part.step"):
        if cand.exists():
            try:
                from rfauto.adapters.fab_export.geometry_io import geometry_from_brep_file

                geom_real = geometry_from_brep_file(cand)
                if geom_real:
                    break
            except Exception:
                pass
    if geom_real is not None:
        geom = geom_real
    elif geom is None:
        geometry_source = "envelope_estimate"
        geometry_warnings.append(
            "几何来源: STEP 读取失败/缺失，体积/重心为变量包络估计"
            f"（A·L·{_BOARD_THICKNESS_MM}），非真实几何"
            "（geometry_source=envelope_estimate）")
        vol = A * L * _BOARD_THICKNESS_MM
        geom = GeometrySummary(
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(float(A), float(L), _BOARD_THICKNESS_MM),
            volume=float(vol),
            com=(A / 2, L / 2, _BOARD_MID_Z_MM),
            valid=True,
            solid_count=1,
            object_names=list(objects or [part_id]),
        )

    res = audit_package_with_dir(
        dims,
        geom,
        geom,
        package_dir=work,
        snaps=[0.0],
        rules=rules,
        cut_volume=0.0,
    )

    files: dict[str, str | Path] = {
        "dims": dims_path,
        "chars": chars_path,
        "drawing_dxf": drawing_path,
        "face_top": face_path,
        "qif": qif_path,
        "qif3": qif3_path,
        "cam_notes": cam_path,
        "mbd_note": mbd_path,
    }
    if gcode_path:
        files["gcode"] = gcode_path
    if camrep_path:
        files["cam_report"] = camrep_path
    if gltf_path:
        files["gltf"] = gltf_path
    if html3d_path:
        files["html3d"] = html3d_path
    if pdf3d_path:
        files["pdf3d"] = pdf3d_path
    if sc_script:
        files["spaceclaim_script"] = sc_script
    if pdf_path:
        files["drawing_pdf"] = pdf_path
    files.update(extra_files)

    idx = pack_deliverable(
        pkg,
        dims=dims,
        files=files,
        audit_passed=res.passed,
        audit_errors=list(pre_errors) + res.errors,
        heal_log=heal_log,
        objects=list(objects or [v.name for v in dims.variables]),
        write_notes=default_notes(rules),
    )

    (pkg / "rfq_checklist.md").write_text(
        "\n".join(
            rfq_checklist(
                [v.name for v in dims.variables],
                [v.name for v in dims.by_role("rf_critical")],
            )
        )
        + "\n",
        encoding="utf-8",
    )
    # Build-to-print 封面（§13A.4 #5）+ 能力表附件（#6，optional）
    with contextlib.suppress(Exception):
        write_btp_cover(pkg, dims, material=material)
    with contextlib.suppress(Exception):
        write_capability_table(pkg)
    with contextlib.suppress(Exception):
        write_pcb_checklist(pkg / "optional")
    # 友好结果文件
    result = GoResult(
        ok=res.passed,
        package_dir=pkg,
        audit_passed=res.passed,
        errors=list(pre_errors) + res.errors,
        warnings=[*res.warnings, *geometry_warnings],
        files=idx.files,
        geometry_source=geometry_source,
        message=("交付包已就绪，可直接发厂" if res.passed else "审计未通过，禁止发厂；见 audit_report.md"),
    )
    (pkg / "go_result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if open_folder and pkg.exists():
        try:
            import os
            import subprocess

            if os.name == "nt":
                subprocess.Popen(["explorer", str(pkg)])
        except Exception:
            pass

    return result


# ─── JSON 信封门面（CLI/MCP 薄壳消费） ───────────────────────────────


def fab_go_from_vars(
    vars_path: str | Path,
    out_dir: str | Path | None = None,
    *,
    rules_path: str | Path | None = None,
    work_dir: str | Path | None = None,
    material: str = "AL6061-T6",
    open_folder: bool = False,
) -> dict[str, Any]:
    return go_from_vars(
        vars_path, out_dir,
        rules_path=rules_path, work_dir=work_dir,
        material=material, open_folder=open_folder,
    ).to_dict()


def fab_go_from_hfss(
    project: str | Path | None,
    design: str | None,
    out_dir: str | Path,
    *,
    part_name: str = "part",
    rules_path: str | Path | None = None,
    material: str = "AL6061-T6",
    keep: Sequence[str] | None = None,
    drop: Sequence[str] | None = None,
    do_heal: bool = False,
    open_folder: bool = False,
    hfss: Any = None,
) -> dict[str, Any]:
    return go_from_hfss(
        project, design, out_dir,
        part_name=part_name, rules_path=rules_path, material=material,
        keep=keep, drop=drop, do_heal=do_heal,
        open_folder=open_folder, hfss=hfss,
    ).to_dict()


def fab_pipeline(
    vars_path: str | Path,
    work_dir: str | Path,
    out_dir: str | Path | None = None,
    *,
    rules_path: str | Path | None = None,
) -> dict[str, Any]:
    """离线端到端轻量链（原型 cmd_pipeline 下沉）：vars → dims → 轮廓 DXF
    + 图纸 → 审计 → 打包 + RFQ 清单（不带 gcode/3D/PDF 重件）."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    rules = load_ruleset(rules_path)

    data = json.loads(Path(vars_path).read_text(encoding="utf-8"))
    part_id = str(data.get("part_id", "part"))
    variables = data.get("variables") or data
    if not isinstance(variables, dict):
        return error_envelope(["vars JSON must be object or {variables:{name:raw}}"])
    dims = snapshot_from_dict(
        part_id,
        variables,
        rev=str(data.get("rev", "A")),
        roles=data.get("roles"),
        tol_classes=data.get("tol_classes"),
        labels=data.get("labels"),
        hfss_meta=data.get("hfss"),
        derived=data.get("derived"),
    )
    dims_path = save_dims(work / "dims.json", dims)

    chars = []
    for i, v in enumerate(dims.by_role("rf_critical"), 1):
        tol = rules.tol_for(v.tol_class)
        chars.append(
            CriticalChar(
                char_id=f"CH-{i:03d}",
                feature=v.drawing_label or v.name,
                nominal=v.value,
                tol_plus=tol.plus,
                tol_minus=tol.minus,
                datum="A",
                source_var=v.name,
                meas_method="三坐标/影像",
                inspect_pct=100,
            )
        )
    with contextlib.suppress(Exception):
        chars.extend(flange_critical_chars())
    chars_path = save_critical_chars(work / "critical_chars.csv", chars)

    L = next((v.value for v in dims.variables if v.name.lower() in ("l", "length")), 60.0)
    A = next((v.value for v in dims.variables if v.name in ("A_outer", "A")), 25.4)
    face_path = work / "faces_top.dxf"
    write_face_dxf(
        face_path,
        [
            ("OUT", rect_loop(0, 0, A, L)),
            (
                "POCKET",
                wr90_inner_loop(L) if any(v.name == "a" for v in dims.variables)
                else rect_loop(2, 2, max(A - 4, 1), max(L - 4, 1)),
            ),
        ],
        circles=[("HOLE", (A / 2, 5), 1.6)],
    )

    drawing_path = render_drawing(
        work / "drawing.dxf",
        dims,
        config=DrawingConfig(part_id=dims.part_id, rev=dims.rev, part_name=part_id),
        rules=rules,
    )

    # 几何摘要：离线用「变量导出外廓」合成（真实应用由 OCCT/pyAEDT 填写）
    vol = A * L * _BOARD_THICKNESS_MM
    geom = GeometrySummary(
        (0, 0, 0), (A, L, _BOARD_THICKNESS_MM), vol,
        (A / 2, L / 2, _BOARD_MID_Z_MM), True, 1, [part_id])
    res = audit_package_with_dir(
        dims,
        geom,
        geom,
        package_dir=work,
        snaps=[0.0],
        rules=rules,
        cut_volume=0.0,
    )

    out = Path(out_dir or (work / f"fab_{part_id}_{dims.rev}"))
    idx = pack_deliverable(
        out,
        dims=dims,
        files={
            "dims": dims_path,
            "chars": chars_path,
            "drawing_dxf": drawing_path,
            "face_top": face_path,
        },
        audit_passed=res.passed,
        audit_errors=res.errors,
        write_notes=default_notes(rules),
        objects=[v.name for v in dims.variables],
    )
    (out / "rfq_checklist.md").write_text(
        "\n".join(
            rfq_checklist(
                [v.name for v in dims.variables],
                [v.name for v in dims.by_role("rf_critical")],
            )
        )
        + "\n",
        encoding="utf-8",
    )
    with contextlib.suppress(Exception):
        write_btp_cover(out, dims)
    return {
        "ok": bool(res.passed),
        "audit_passed": bool(res.passed),
        "audit_errors": res.errors,
        "audit_warnings": res.warnings,
        "package_dir": str(out),
        "files": idx.files,
    }


def fab_snapshot(
    vars_path: str | Path,
    out_path: str | Path,
    *,
    part_id: str | None = None,
) -> dict[str, Any]:
    """vars JSON → dims.json（尺寸真源快照）."""
    data = json.loads(Path(vars_path).read_text(encoding="utf-8"))
    pid = str(data.get("part_id") or part_id or Path(vars_path).stem)
    variables = data.get("variables") or data
    if not isinstance(variables, dict):
        return error_envelope(["vars JSON must be object or {variables:{name:raw}}"])
    doc = snapshot_from_dict(
        pid,
        variables,
        rev=str(data.get("rev", "A")),
        roles=data.get("roles"),
        tol_classes=data.get("tol_classes"),
        labels=data.get("labels"),
        standards=data.get("standards"),
        hfss_meta=data.get("hfss"),
        derived=data.get("derived"),
    )
    out = save_dims(out_path, doc)
    return ok_envelope(dims_path=str(out), n_vars=len(doc.variables), part_id=pid)


def fab_draw(
    dims_path: str | Path,
    out_path: str | Path,
    *,
    rules_path: str | Path | None = None,
    part_name: str | None = None,
    material: str = "AL6061-T6",
    with_pdf: bool = False,
) -> dict[str, Any]:
    """dims.json → DXF 图纸（可选 PDF）."""
    doc = load_dims(dims_path)
    rules = load_ruleset(rules_path)
    cfg = DrawingConfig(
        part_name=part_name or doc.part_id,
        part_id=doc.part_id,
        rev=doc.rev,
        material=material,
        notes=default_notes(rules, doc),
    )
    out = render_drawing(out_path, doc, config=cfg, rules=rules)
    pdf: str | None = None
    if with_pdf:
        p = export_dxf_pdf(out)
        pdf = str(p) if p else None
    return ok_envelope(dxf_path=str(out), pdf_path=pdf, pdf_skipped=bool(with_pdf and pdf is None))


def fab_audit(
    package_dir: str | Path,
    *,
    rules_path: str | Path | None = None,
) -> dict[str, Any]:
    """对交付目录跑审计（A1–A12；缺 geometry_summary.json 时几何项合成）."""
    pkg = Path(package_dir)
    if not (pkg / "dims.json").exists():
        return error_envelope([f"dims.json not found in {pkg}"])
    dims = load_dims(pkg / "dims.json")
    rules = load_ruleset(rules_path)
    gpath = pkg / "geometry_summary.json"
    cut: float | None = 0.0
    if gpath.exists():
        gj = json.loads(gpath.read_text(encoding="utf-8"))
        gh = geometry_summary_from_dict(gj["hfss"])
        ge = geometry_summary_from_dict(gj["export"])
        cut = gj.get("cut_volume")
    else:
        # 缺几何时只跑可离线项（几何合成占位，如实告警）
        gh = ge = GeometrySummary((0, 0, 0), (1, 1, 1), 1.0)
        cut = 0.0
    snaps: list[float] = []
    sp = pkg / "snap_log.json"
    if sp.exists():
        snaps = json.loads(sp.read_text(encoding="utf-8"))
    res = audit_package_with_dir(
        dims,
        gh,
        ge,
        package_dir=pkg,
        snaps=snaps,
        rules=rules,
        cut_volume=cut,
    )
    return {
        "ok": bool(res.passed),
        "passed": bool(res.passed),
        "errors": res.errors,
        "warnings": res.warnings,
        "details": res.details,
        "geometry_synthetic": not gpath.exists(),
    }


def fab_pack(
    dims_path: str | Path,
    out_dir: str | Path,
    *,
    step: str | Path | None = None,
    xt: str | Path | None = None,
    drawing: str | Path | None = None,
    chars: str | Path | None = None,
    rules_path: str | Path | None = None,
    with_notes: bool = False,
    force_fail: bool = False,
) -> dict[str, Any]:
    """组装交付目录（audit_passed 由审计或 force_fail 决定）."""
    dims = load_dims(dims_path)
    files: dict[str, str | Path] = {}
    if step:
        files["step"] = step
    if xt:
        files["xt"] = xt
    if drawing:
        files["drawing_dxf"] = drawing
    if chars:
        files["chars"] = chars
    audit_passed = not force_fail
    audit_errors: list[str] = ["forced fail"] if force_fail else []
    idx = pack_deliverable(
        out_dir,
        dims=dims,
        files=files,
        audit_passed=audit_passed,
        audit_errors=audit_errors,
        write_notes=default_notes(load_ruleset(rules_path)) if with_notes else (),
        objects=[v.name for v in dims.variables],
    )
    env = idx.to_dict()
    env["ok"] = idx.audit_passed
    return env


def fab_rules(rules_path: str | Path | None = None) -> dict[str, Any]:
    """规则库摘要（JSON 信封）."""
    rs = load_ruleset(rules_path)
    return ok_envelope(
        name=rs.name,
        units=rs.units,
        snap_max_mm=rs.snap_max_mm,
        volume_rel=rs.volume_rel,
        bbox_abs_mm=rs.bbox_abs_mm,
        tol_classes={
            k: {"plus": v.plus, "minus": v.minus, "ra": v.ra, "fit": v.fit, "note": v.note}
            for k, v in rs.tol_classes.items()
        },
    )


def fab_catalog() -> dict[str, Any]:
    """波导/法兰/配合/表处标准库目录."""
    return ok_envelope(catalog=catalog_tables(), default_ruleset=default_ruleset().name)


def fab_export_geometry(
    out_dir: str | Path,
    *,
    project: str | Path | None = None,
    design: str | None = None,
    part_name: str = "part",
    do_heal: bool = False,
    keep: Sequence[str] | None = None,
    drop: Sequence[str] | None = None,
    hfss: Any = None,
) -> dict[str, Any]:
    """HFSS live 导出 x_t/step + dims 快照（需 pyAEDT+AEDT；hfss 可注入）."""
    own = False
    if hfss is None:
        try:
            from ansys.aedt.core import Hfss  # type: ignore
        except Exception as e:
            return error_envelope([f"pyAEDT/AEDT 不可用: {e}"], needs="rfauto[hfss] + AEDT")
        try:
            hfss = Hfss(project=str(project) if project else None,
                        design=design,
                        non_graphical=True,
                        new_desktop=False)
            own = True  # 自建会话自释放（#265 家法：finally 必 release 防孤儿）
        except Exception as e:
            return error_envelope([f"HFSS 连接失败: {e}"])
    try:
        from rfauto.adapters.fab_export.hfss_dims import write_dims_from_hfss
        from rfauto.adapters.fab_export.hfss_export import export_fab_geometry

        report = export_fab_geometry(
            hfss,
            out_dir,
            part_name=part_name,
            do_heal=do_heal,
            keep=keep,
            drop=drop,
        )
        dims = write_dims_from_hfss(
            hfss,
            Path(out_dir) / "dims.json",
            part_name,
            roles={"a": "rf_critical", "b": "rf_critical"},
            tol_classes={"a": "WG_AB", "b": "WG_AB"},
        )
        # ge8e W2 快偿（R5-06）：裸 ok 信封 → 构造器（键集/键序/语义零变化）
        if report.ok:
            return ok_envelope(
                errors=report.errors,
                paths=report.paths,
                objects=report.exported_objects,
                skipped=report.skipped_objects,
                dims_vars=len(dims.variables),
            )
        return error_envelope(
            report.errors,
            paths=report.paths,
            objects=report.exported_objects,
            skipped=report.skipped_objects,
            dims_vars=len(dims.variables),
        )
    finally:
        if own:
            with contextlib.suppress(Exception):
                hfss.release_desktop(close_projects=False, close_desktop=False)


# ─── 覆铜板复合层导出 + DXF 真值对照（ge5 Goal Wave3 F 组） ────────────


def _composite_object_from_dict(d: dict[str, Any]) -> CompositeObject:
    return CompositeObject(
        name=str(d.get("name") or "obj"),
        material=str(d.get("material") or "metal"),
        z0=float(d.get("z0") or 0.0),
        z1=float(d.get("z1") or 0.0),
        outlines=[[tuple(map(float, p)) for p in loop] for loop in d.get("outlines") or []],
        circles=[(tuple(map(float, c)), float(r)) for c, r in d.get("circles") or []],
    )


def fab_composite_export(
    objects: Sequence[dict[str, Any]],
    out_path: str | Path,
    *,
    keep_edge_mm: float = 0.1,
    dxf_layers: Sequence[str] | None = None,
) -> dict[str, Any]:
    """复合层组板 → 悬空孔过滤 → 四图层 DXF（JSON 进出信封）.

    objects: [{name, material("metal"/"dielectric"), z0, z1,
    outlines:[[(x,y),...]], circles:[[(x,y),r],...]}]（纯几何描述，
    零 HFSS 依赖）。流程：group_composite_layers 按 Z 向物理贴合组板
    （M1/M2/sub/patch）→ 板外形上做无依托孔过滤（留痕清单随报告）→
    write_composite_dxf 写 DXF → 读回逐图层实体计数自证。
    """
    objs = [_composite_object_from_dict(d) for d in objects]
    grouped = group_composite_layers(objs)
    if grouped.unassigned:
        return error_envelope(
            [
                f"unassigned objects cannot form composite layer: "
                f"{[o.name for o in grouped.unassigned]}",
            ],
            grouping=grouped.as_dict(),
            notes=grouped.notes,
        )

    # 无依托孔过滤：以介质外形为支撑面（逐板判定——孔被任一单板包含即
    # 有依托，多板 XY 重叠叠层不做跨板奇偶混计，ge5 审查 F8）。
    # 圆孔逐一过滤；外形槽孔（无 circles）不过滤直通并留痕（骑边槽孔
    # 按工艺裁定，源仓 §6-3 口径）。
    board_loops: list[list[list[tuple[float, float]]]] = [
        [list(map(tuple, loop)) for loop in b.outlines] for b in grouped.sub
    ]
    circular = [(o.name, o.circles[0][0], o.circles[0][1]) for o in grouped.patch if o.circles]
    slot_names = [o.name for o in grouped.patch if not o.circles]
    # 多圆 patch 对象只消费首圆（单孔 per 对象惯例）；其余圆如实留痕
    # 不静默丢弃（ge5 审查 F10，多报不放过 #316 方向）
    for o in grouped.patch:
        if len(o.circles) > 1:
            grouped.notes.append(
                f"multi-circle patch '{o.name}' has {len(o.circles)} circles, "
                "only the first is exported/filtered")
    hole_filter = filter_unsupported_holes(
        circular,
        board_loops,
        keep_edge_mm=keep_edge_mm,
    ) if circular else {"kept": [], "removed": [], "counts": {"kept": 0, "removed": 0, "total": 0}, "rule": "no-holes"}

    kept_by_name = {name: (c, r) for name, c, r in hole_filter["kept"]}
    slot_set = set(slot_names)
    patch_layer: list[CompositeObject] = [
        CompositeObject(
            name=o.name,
            material=o.material,
            z0=o.z0,
            z1=o.z1,
            outlines=o.outlines,
            circles=[kept_by_name[o.name]] if o.name in kept_by_name else [],
        )
        for o in grouped.patch
        if o.name in kept_by_name or o.name in slot_set
    ]
    if slot_names:
        grouped.notes.append(
            f"slot patches passed through unfiltered: {slot_names} (outline-based)"
        )

    layers = {"M1": grouped.M1, "M2": grouped.M2, "sub": grouped.sub, "patch": patch_layer}
    want = list(dxf_layers) if dxf_layers else None
    path = write_composite_dxf(layers, out_path)
    readback = read_composite_dxf(path, layers=want or ["M1", "M2", "sub", "patch"])
    counts = {
        layer: {"segments": len(v["segments"]), "circles": len(v["circles"])}
        for layer, v in readback.items()
    }
    return ok_envelope(
        path=str(path),
        grouping=grouped.as_dict(),
        notes=grouped.notes,
        hole_filter={
            "rule": hole_filter["rule"],
            "counts": hole_filter["counts"],
            "removed": [
                {"name": rh.name, "center": list(rh.center), "radius": rh.radius, "reason": rh.reason}
                for rh in hole_filter["removed"]
            ],
        },
        dxf_entity_counts=counts,
    )


def fab_dxf_truth_compare(
    produced: str | Path,
    truth: str | Path,
    *,
    expand_insert: bool = True,
    dedup: bool = True,
    y_normalize: bool = True,
    tol_mm: float = 1e-3,
    layers: Sequence[str] | None = None,
) -> dict[str, Any]:
    """DXF 与外部真值逐图层对照（JSON 信封薄包装，判据在 core）.

    三归一（INSERT 展开/去重/Y 归一）缺省全开；报告含归一步骤留痕、
    逐实体差与总判 passed（源仓 §2.11/§6-10 口径）。
    """
    report = compare_dxf_to_truth(
        produced,
        truth,
        expand_insert=expand_insert,
        dedup=dedup,
        y_normalize=y_normalize,
        tol_mm=tol_mm,
        layers=list(layers) if layers else None,
    )
    return ok_envelope(**report)
