"""交付打包：目录布局 + 哈希 + 索引."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rfauto.core.fab_export.schema import DimsDocument, Manifest
from rfauto.core.fab_export.standards import catalog_tables

from .artifact_io import save_manifest
from .audit_io import file_hashes


@dataclass
class DeliverableIndex:
    root: Path
    files: dict[str, str] = field(default_factory=dict)  # rel -> sha256
    audit_passed: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "files": self.files,
            "audit_passed": self.audit_passed,
            "errors": self.errors,
        }


DEFAULT_LAYOUT = {
    "manifest": "manifest.json",
    "dims": "dims.json",
    "chars": "critical_chars.csv",
    "notes": "drawing_notes.txt",
    "drawing_pdf": "drawing.pdf",
    "drawing_dxf": "drawing.dxf",
    "audit_json": "audit_report.json",
    "audit_md": "audit_report.md",
    "step": "part.step",
    "xt": "part.x_t",
    "face_top": "faces/top.dxf",
    "face_bottom": "faces/bottom.dxf",
    "qif": "qif_characteristics.xml",
    "qif3": "qif3_document.xml",
    "cam_notes": "cam_notes.md",
    "mbd_note": "mbd_note.md",
    "gcode": "cam_ops.nc",
    "cam_report": "cam_ops_report.md",
    "gltf": "model.gltf",
    "html3d": "model_3d.html",
    "pdf3d": "model_3d.pdf",
    "spaceclaim_script": "spaceclaim_heal.py",
    "btp_cover": "build_to_print_cover.md",
    "capability_table": "optional/capability_table.md",
}


def pack_deliverable(
    out_dir: str | Path,
    *,
    dims: DimsDocument,
    files: dict[str, str | Path],
    audit_passed: bool,
    audit_errors: Sequence[str] = (),
    heal_log: Sequence[dict[str, Any]] = (),
    objects: Sequence[str] = (),
    write_notes: Sequence[str] = (),
    manifest_extra: dict[str, Any] | None = None,
    copy_files: bool = True,
) -> DeliverableIndex:
    """组装 fab_<part>_<rev>_* 目录.

    files: 逻辑名→源路径；逻辑名见 DEFAULT_LAYOUT 或自定义。
    """
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "faces").mkdir(exist_ok=True)
    (root / "optional").mkdir(exist_ok=True)

    errors = list(audit_errors)
    if not audit_passed:
        errors.append("AUDIT_FAIL: 禁止发图（仅归档）")

    # 复制文件
    for logical, src in files.items():
        src_p = Path(src)
        if not src_p.exists():
            errors.append(f"missing source: {logical}={src}")
            continue
        dest_name = DEFAULT_LAYOUT.get(logical, logical)
        dest = root / dest_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if copy_files:
            shutil.copy2(src_p, dest)
        else:
            dest.write_bytes(src_p.read_bytes())

    # notes
    if write_notes:
        (root / DEFAULT_LAYOUT["notes"]).write_text("\n".join(write_notes) + "\n", encoding="utf-8")

    man = Manifest(
        part_id=dims.part_id,
        rev=dims.rev,
        units="mm",
        formats=[k for k in files if k in ("step", "xt")],
        wcs=dims.wcs,
        export_tool="fab_export",
        heal_log=list(heal_log),
        audit_gate={"passed": audit_passed, "errors": list(errors)},
        objects=list(objects),
        hashes={},
    )
    if manifest_extra:
        man.audit_gate.update(manifest_extra)
    man_path = save_manifest(root / DEFAULT_LAYOUT["manifest"], man)

    hashes = file_hashes(root)
    man.hashes = hashes
    save_manifest(man_path, man)

    # audit json/md
    audit_obj = {"passed": audit_passed, "errors": list(errors), "hashes": hashes}
    (root / DEFAULT_LAYOUT["audit_json"]).write_text(
        json.dumps(audit_obj, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"# 审计报告 — {dims.part_id} Rev{dims.rev}",
        "",
        f"- 状态: **{'PASS' if audit_passed else 'FAIL'}**",
        "- 单位: mm",
        "",
        "## 错误",
    ]
    lines += [f"- {e}" for e in errors] or ["- （无）"]
    lines += ["", "## 文件哈希 (sha256)", ""]
    for rel, h in sorted(hashes.items()):
        lines.append(f"- `{rel}`: `{h}`")
    (root / DEFAULT_LAYOUT["audit_md"]).write_text("\n".join(lines) + "\n", encoding="utf-8")

    return DeliverableIndex(root=root, files=hashes, audit_passed=audit_passed, errors=errors)


def rfq_checklist(dim_names: Iterable[str], critical: Iterable[str] = ()) -> list[str]:
    """生成发给厂家前的勾选清单.

    覆盖细则 §6.1 文件 / §6.2 图面 / §6.3 商务三节 + 主方案 §13.2 书面
    确认清单（公差表认可、格式、法兰型号、图框模板、镀前镀后检、变更
    流程、设备能力——线切割台数、质量体系 ISO9001/GJB）。
    """
    lines = [
        "# RFQ 发图前清单",
        "",
        "## 文件（细则 §6.1）",
        "- [ ] drawing.pdf（2D 合同图）",
        "- [ ] part.step（AP214，mm）",
        "- [ ] part.x_t（可选）",
        "- [ ] faces/*.dxf（若厂家要 2.5D）",
        "- [ ] critical_chars.csv",
        "- [ ] build_to_print_cover.md（零件号/Rev/数量/材料/表处）",
        "- [ ] 数量 / 交期 / 材料 / 表处",
        "",
        "## 图面必备（细则 §6.2）",
        "- [ ] 图号 + Rev",
        "- [ ] 材料标记",
        "- [ ] 表处厚度（单边补偿）",
        "- [ ] 关键尺寸公差（iris、a、b）",
        "- [ ] 基准 A/B/C（型腔位置相对基准）",
        "- [ ] 螺纹：规格+有效牙深+底孔+6H",
        "- [ ] 法兰/波导标准号（FBP100 / UG-39 / MIL-DTL-85/3）",
        "- [ ] 检验方法（CMM/影像）",
        "- [ ] 未注公差 1804-m / 1184-K",
        "",
        "## 商务与书面确认（细则 §6.3 / 主方案 §13.2）",
        "- [ ] 是否保密/NDA",
        "- [ ] 是否 GJB 检验规范（军工件另附检验规范）",
        "- [ ] 变更流程：关键尺寸只回写 HFSS 后重导，禁止口头改",
        "- [ ] 公差表书面认可（IRIS ±0.02 / WG_AB ±0.03 / H7 / 6H）",
        "- [ ] 交付格式确认：x_t + step + pdf；是否要 dwg",
        "- [ ] 法兰型号确认（UG-39 / FBP100 / CPR-90G）并核对孔距",
        "- [ ] 图框模板是否用厂家模板",
        "- [ ] 镀前/镀后检验分工确认",
        "- [ ] 设备能力确认：iris 走 WEDM 是否本厂（线切割台数）",
        "- [ ] 质量体系：ISO9001 / GJB",
        "",
        "## 变量清单",
    ]
    for n in dim_names:
        mark = "（关键）" if n in set(critical) else ""
        lines.append(f"- [ ] {n} {mark}")
    return lines


BTP_COVER_FILENAME = "build_to_print_cover.md"


def write_btp_cover(
    out_dir: str | Path,
    dims: DimsDocument,
    *,
    quantity: str = "____",
    material: str = "AL6061-T6",
    finish: str = "铝导电氧化（或外漆+内酸洗）",
    delivery: str = "____",
    flange_standard: str = "FBP100 / UG-39/U（发前与厂家图核对孔距）",
    wg_standard: str = "WR-90 / BJ100（GB/T 11450；MIL-W-85）",
    nda: bool = True,
) -> Path:
    """Build-to-print 封面（主方案 §13A.4 增补 #5：零件号/Rev/数量/材料/表处）.

    Flann/QuinStar 行业实践：图纸包封面声明「按图制造」，列出零件号/
    Rev/数量/材料/表处/引用标准/检验要求/保密级别，附厂家签收栏。
    """
    critical = [v for v in dims.variables if v.role == "rf_critical"]
    lines = [
        "# Build-to-Print 制造封面",
        "",
        f"- 零件号/图号：**{dims.part_id}**",
        f"- Rev：**{dims.rev}**",
        f"- 数量：{quantity}",
        f"- 材料：{material}",
        f"- 表面处理：{finish}",
        f"- 交期：{delivery}",
        "- 单位：mm（全包强制；禁止按导入模型缩放/测量改图）",
        "",
        "## 引用标准",
        f"- 波导：{wg_standard}",
        f"- 法兰：{flange_standard}",
        "- 未注公差：GB/T 1804-m；未注形位：GB/T 1184-K",
        "- 关键特性与检验方法：见 critical_chars.csv（镀前 100%）",
        "",
        "## 关键尺寸（RF）",
    ]
    for v in critical:
        lines.append(f"- {v.drawing_label or v.name} = {v.value:g}（变量 {v.name}；"
                     f"{v.standard_ref or 'dims.json 为真源'}）")
    lines += [
        "",
        "## 制造声明",
        "- 本包为 build-to-print：厂家按 2D 图纸（drawing.pdf）制造，STEP/x_t 仅供 CAM 参考。",
        "- 关键尺寸变更只接受 HFSS 变量回写后的新版图（Rev 递增）。",
        f"- 保密：{'需 NDA' if nda else '无特殊保密要求'}。",
        "",
        "## 厂家签收（书面确认）",
        "- 公差表认可：____（签字/日期）",
        "- 交期确认：____（签字/日期）",
        "- 质量体系：____（ISO9001 / GJB）",
    ]
    p = Path(out_dir) / BTP_COVER_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


CAPABILITY_TABLE_FILENAME = "optional/capability_table.md"


def write_capability_table(out_dir: str | Path) -> Path:
    """能力表附件（主方案 §13A.4 增补 #6，Precision Micro 能力表模式）.

    内容取自 core.standards.catalog_tables（波导/法兰/嘉立创配合带/表处
    单边厚度/Kerr 规则）——作为规则库参考附件随包，非厂家能力承诺。
    """
    cat = catalog_tables()
    lines = [
        "# 能力参考表（附件，随包备查）",
        "",
        "> 来源：规则库内置标准表（evidence O=公开产品表，K=行业共识）；",
        "> 合同前须与厂家书面核实。",
        "",
        "## 波导",
        "",
        "| 型号 | BJ | a | b | A | B | t | 频段 GHz | R1 | R2 | 证据 |",
        "|------|----|---|---|---|---|---|----------|----|----|------|",
    ]
    for name, w in cat["waveguides"].items():
        lines.append(
            f"| {name} | {w['bj']} | {w['a']:g} | {w['b']:g} | {w['A']:g} | {w['B']:g} | "
            f"{w['t']:g} | {w['freq_ghz'][0]}–{w['freq_ghz'][1]} | {w.get('r1', 0.8):g} | "
            f"{w.get('r2', (0.65, 1.15))[0]:g}–{w.get('r2', (0.65, 1.15))[1]:g} | {w['evidence']} |"
        )
    lines += [
        "",
        "## 法兰",
        "",
        "| 型号 | 外廓 | 厚 | 螺栓孔 | 销孔 | 平面度 | 垂直度(mm/100) | 证据 |",
        "|------|------|----|--------|------|--------|----------------|------|",
    ]
    for name, f in cat["flanges"].items():
        lines.append(
            f"| {name} | {f['outer']:g} | {f['thickness']:g} | {f['bolt']} | {f['pin']} | "
            f"{f['flatness']:g} | {f.get('perpendicularity_mm_per_100', 0.05):g} | {f['evidence']} |"
        )
    lines += [
        "",
        "## 配合带（嘉立创公开，参考）",
        "",
        "| 类型 | 带宽 mm |",
        "|------|---------|",
    ]
    for kind, (lo, hi) in cat["fit_bands_mm"].items():
        lines.append(f"| {kind} | {lo:+g} ~ {hi:+g} |")
    lines += [
        "",
        "## 表面处理单边厚度",
        "",
        "| 工艺 | 单边 mm |",
        "|------|---------|",
    ]
    for kind, (lo, hi) in cat["finish_one_side_mm"].items():
        lines.append(f"| {kind} | {lo:g} – {hi:g} |")
    kerr = cat["kerr"]
    lines += [
        "",
        "## Kerr/NRAO 经验规则",
        "",
        f"- 线性公差 {kerr['linear_tol_pct']:g}% 名义",
        f"- 内角 R ≤ {kerr['corner_r_max_frac_of_a']:g}·a",
        f"- 法兰错位 < {kerr['flange_misalign_pct']:g}% / < {kerr['flange_misalign_deg']:g}°",
        "",
    ]
    p = Path(out_dir) / CAPABILITY_TABLE_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class FilesystemPackPort:
    name = "filesystem"

    def pack(self, **kwargs):
        return pack_deliverable(**kwargs)
