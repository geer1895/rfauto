"""fab_export（HFSS→可机加交付包）离线单元测试（T43 吸收批）.

自 E:\\协助调研\\cad导出 原型 6 个测试文件（30 条）移植并适配本仓分层：
- import 面改 rfauto.core/adapters/service.fab_export*；
- 原型 core 内文件 IO 挪 adapters（artifact_io/audit_io/qif_io/cam_io），
  对应断言改走新家；
- A7/A12 审计注入式参数（dxf_closed/hashes）新增回归钉；
- 原型 test_real_vars_file / test_go_from_wr90_example 读原型仓 examples/，
  本仓改为内联等值 JSON（金样 WR90 变量集不变）。

全部离线零 AEDT 零网络（ezdxf/matplotlib 已在 venv；pyaedt 仅 import 面）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from rfauto.adapters.fab_export.artifact_io import (
    load_critical_chars,
    load_dims,
    load_ruleset,
    save_critical_chars,
    save_dims,
)
from rfauto.adapters.fab_export.audit_io import (
    audit_package_with_dir,
    dxf_closed_map,
    file_hashes,
)
from rfauto.adapters.fab_export.base import (
    ensure_builtin_plugins,
    get_registry,
    load_entry_point_plugins,
)
from rfauto.adapters.fab_export.cam_io import write_cam_report, write_gcode
from rfauto.adapters.fab_export.doc3d import write_3d_pdf, write_gltf_from_dims, write_html_viewer
from rfauto.adapters.fab_export.ezdxf_draw import (
    DrawingConfig,
    _apply_tolerance,
    _dim_text,
    default_notes,
    render_drawing,
)
from rfauto.adapters.fab_export.face_dxf import rect_loop, write_face_dxf
from rfauto.adapters.fab_export.geometry_io import (
    compare_geometry,
    geometry_from_dims_envelope,
    load_geometry_summary_json,
    write_geometry_summary_json,
)
from rfauto.adapters.fab_export.multisheet import render_two_sheet
from rfauto.adapters.fab_export.pack_store import (
    pack_deliverable,
    rfq_checklist,
    write_btp_cover,
    write_capability_table,
)
from rfauto.adapters.fab_export.pcb_notes import PCB_DELIVERABLE_CHECKLIST, write_pcb_checklist
from rfauto.adapters.fab_export.qif_io import (
    write_qif3_document,
)
from rfauto.adapters.fab_export.spaceclaim import HealRequest, NullHealer, SpaceClaimScriptHealer
from rfauto.core.fab_export.audit import AUDIT_CHECKS, AuditResult, GeometrySummary, audit_package
from rfauto.core.fab_export.dims import parse_dim_value, snapshot_from_dict
from rfauto.core.fab_export.gcode import ToolSpec, build_wr90_program
from rfauto.core.fab_export.infer import infer_role_and_tol, split_mapping
from rfauto.core.fab_export.process_notes import dfm_notes, finish_note, process_tag_for, thread_note
from rfauto.core.fab_export.qif3 import render_qif3_document
from rfauto.core.fab_export.rules import default_ruleset
from rfauto.core.fab_export.schema import CriticalChar, flange_critical_chars
from rfauto.core.fab_export.standards import (
    FIT_BANDS_MM,
    KERR_RULES,
    catalog_tables,
    get_flange,
    get_waveguide,
)
from rfauto.core.fab_export.views import build_wr90_views, flange_hole_table, rect
from rfauto.service.fab_export_service import fab_go_from_vars, fab_pipeline

# 金样 WR90 变量集（原型 examples/wr90_vars.json 内联等值）
WR90_VARS = {
    "part_id": "wg_straight_wr90_001",
    "rev": "A",
    "hfss": {"project": "wg_straight.aedt", "design": "HFSSDesign1"},
    "roles": {"a": "rf_critical", "b": "rf_critical", "L": "assembly", "wall": "free"},
    "tol_classes": {"a": "WG_AB", "b": "WG_AB", "L": "FREE", "wall": "FREE"},
    "labels": {"a": "内腔宽边a", "b": "内腔窄边b", "L": "总长", "wall": "壁厚"},
    "standards": {"a": "WR-90/BJ100", "b": "WR-90/BJ100"},
    "variables": {"a": "22.86mm", "b": "10.16mm", "L": "60mm", "wall": "1.27mm", "A_outer": "25.4mm"},
    "derived": [{"name": "flange", "value": "FBP100", "from": ["std:FBP100"], "role": "assembly"}],
}


# ─── core：解析/快照/规则（原型 test_fab_export.py 移植） ─────────────


def test_parse_dim_value_mm():
    assert parse_dim_value("2.3mm") == pytest.approx(2.3)
    assert parse_dim_value("100um") == pytest.approx(0.1)
    assert parse_dim_value("2.54cm") == pytest.approx(25.4)


def test_parse_dim_value_um_single_source():
    """审查项 R1 回归钉：µm（µ/μ 变体）全仓单源可解析（原型 adapters
    副本正则收不下 µ 直接抛 cannot parse——已并单源）。"""
    from rfauto.adapters.fab_export.hfss_dims import parse_dim_value as adapter_parse

    assert parse_dim_value("5µm") == pytest.approx(0.005)
    assert parse_dim_value("5μm") == pytest.approx(0.005)
    assert adapter_parse("5µm") == pytest.approx(0.005)
    with pytest.raises(ValueError):
        parse_dim_value("abc")


def test_snapshot_and_roundtrip(tmp_path: Path):
    doc = snapshot_from_dict(
        "p1",
        {"a": "22.86mm", "b": "10.16mm"},
        roles={"a": "rf_critical", "b": "rf_critical"},
        tol_classes={"a": "WG_AB", "b": "WG_AB"},
    )
    assert doc.units == "mm"
    p = save_dims(tmp_path / "dims.json", doc)
    doc2 = load_dims(p)
    assert doc2.part_id == "p1"
    assert abs(doc2.variables[0].value - 22.86) < 1e-12


def test_ruleset_default_and_yaml(tmp_path: Path):
    rs = default_ruleset()
    assert rs.tol_for("IRIS").plus == pytest.approx(0.02)
    y = tmp_path / "r.yaml"
    y.write_text("ruleset: t\naudit:\n  snap_max_mm: 0.001\n", encoding="utf-8")
    rs2 = load_ruleset(y)
    assert rs2.snap_max_mm == pytest.approx(0.001)
    assert rs2.name == "t"


# ─── core：审计（A1–A12 纯判据 + 注入式 A7/A12） ─────────────────────


def test_audit_checks_inventory():
    assert len(AUDIT_CHECKS) == 12
    assert AUDIT_CHECKS[0] == "A1_variable_closure"
    assert AUDIT_CHECKS[-1] == "A12_hashes"


def test_audit_pass_and_fail():
    doc = snapshot_from_dict("p", {"a": "22.86mm"}, roles={"a": "rf_critical"}, tol_classes={"a": "WG_AB"})
    g = GeometrySummary((0, 0, 0), (25.4, 60, 12.7), 100.0, (12.7, 30, 6.35), True, 1, ["housing"])
    ok = audit_package(doc, g, g, snaps=[0.0], cut_volume=0.0)
    assert ok.passed, ok.errors

    bad = GeometrySummary((0, 0, 0), (25.4, 60, 12.7), 120.0, (0, 0, 0), True, 1, ["Region"])
    bad_r = audit_package(doc, g, bad, snaps=[0.01], cut_volume=1.0)
    assert not bad_r.passed
    assert any("A3" in e or "A4" in e or "A8" in e or "A11" in e for e in bad_r.errors)


def test_audit_injected_a7_a12():
    """A7/A12 注入式（T43 分层差异）：None 不判、闭合坏/空哈希要报。"""
    doc = snapshot_from_dict("p", {"a": "22.86mm"})
    g = GeometrySummary((0, 0, 0), (25.4, 60, 12.7), 100.0, (12.7, 30, 6.35), True, 1, ["housing"])

    # None：不判（不凑 PASS 也不冒 FAIL）
    r_skip = audit_package(doc, g, g, dxf_closed=None, hashes=None)
    assert r_skip.passed
    assert "dxf_open_loops" not in r_skip.details

    # 有开环 → A7 报
    r_a7 = audit_package(doc, g, g, dxf_closed={"faces/top.dxf": True, "drawing.dxf": False})
    assert not r_a7.passed
    assert any("A7" in e and "drawing.dxf" in e for e in r_a7.errors)

    # 空 hashes → A12 告警不 FAIL
    r_a12 = audit_package(doc, g, g, hashes={})
    assert r_a12.passed
    assert any("A12" in w for w in r_a12.warnings)


def test_audit_package_with_dir(tmp_path: Path):
    """目录级审计包装：真实 DXF 采集 + 哈希（ezdxf 主路径）。"""
    doc = snapshot_from_dict("p", {"a": "22.86mm"})
    write_face_dxf(tmp_path / "faces_top.dxf", [("OUT", rect_loop(0, 0, 10, 20))])
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    g = GeometrySummary((0, 0, 0), (25.4, 60, 12.7), 100.0, (12.7, 30, 6.35), True, 1, ["housing"])
    res = audit_package_with_dir(doc, g, g, package_dir=tmp_path, snaps=[0.0], cut_volume=0.0)
    assert res.passed, res.errors
    assert res.details["hashes"].get("faces_top.dxf")
    assert dxf_closed_map(tmp_path) == {"faces_top.dxf": True}
    assert file_hashes(tmp_path)["notes.txt"]


# ─── core：视图/QIF/CAM/标准库/工艺标注（原型 views_qif/standards 移植） ──


def test_wr90_views():
    views = build_wr90_views({"L": 60.0, "a": 22.86, "b": 10.16, "wall": 1.27, "iris_w": 4.0, "iris_t": 1.2})
    names = {v.name for v in views}
    assert {"front", "top", "section", "detail"} <= names
    front = next(v for v in views if v.name == "front")
    assert front.circles  # 螺栓孔


def test_wr90_section_view_uses_outer_height():
    """审查项 R10 回归钉：A-A 剖视外廓=外高 B、内腔=腔高 b（原型误用外宽 A）。"""
    views = build_wr90_views({"L": 60.0, "a": 22.86, "b": 10.16, "wall": 1.27})
    sec = next(v for v in views if v.name == "section")
    out_loop = dict(sec.loops)["OUT"]
    pocket = dict(sec.loops)["POCKET"]
    assert out_loop[2][1] - out_loop[0][1] == pytest.approx(10.16 + 2 * 1.27)  # B
    assert pocket[2][1] - pocket[0][1] == pytest.approx(10.16)  # b


def test_flange_holes():
    rows = flange_hole_table("FBP100")
    assert len(rows) == 6  # 4 bolt + 2 pin
    assert any(r["type"] == "pin" for r in rows)


def test_rect():
    assert rect(0, 0, 2, 3) == [(0, 0), (2, 0), (2, 3), (0, 3)]


def test_waveguide_wr90():
    wg = get_waveguide("WR-90")
    assert wg.a == 22.86 and wg.b == 10.16
    assert get_waveguide("BJ100").bj == "BJ100"
    assert get_waveguide("WR-112").bj == "BJ84"  # 勿混


def test_flange_and_catalog():
    fl = get_flange("FBP100")
    assert fl.bolt_count == 4
    cat = catalog_tables()
    assert "WR-90" in cat["waveguides"]
    assert "press_interference" in FIT_BANDS_MM
    assert KERR_RULES["linear_tol_pct"] == 0.5


def test_process_notes():
    assert process_tag_for("iris_w") == "WEDM"
    assert process_tag_for("h_pocket") == "3-axis"
    assert "6H" in thread_note()
    assert "镀银" in finish_note(False) or "导电" in finish_note(True)


def test_infer_common_names():
    assert infer_role_and_tol("a") == ("rf_critical", "WG_AB")
    assert infer_role_and_tol("iris_w") == ("rf_critical", "IRIS")
    assert infer_role_and_tol("pin_hole") == ("assembly", "PIN_H7")
    role, tol = infer_role_and_tol("m3_thread")
    assert role == "assembly" and tol == "THD"
    roles, tols = split_mapping(["a", "iris_w", "wall"])
    assert roles["iris_w"] == "rf_critical"
    assert tols["wall"] == "FREE"


# ─── adapters：DXF/图纸/打包/几何 IO/PCB（原型移植） ──────────────────


def test_face_dxf_closed(tmp_path: Path):
    p = write_face_dxf(
        tmp_path / "f.dxf",
        [("OUT", rect_loop(0, 0, 10, 20))],
        circles=[("HOLE", (5, 5), 1.0)],
    )
    assert p.exists()
    text = p.read_text(encoding="utf-8", errors="ignore")
    assert "LWPOLYLINE" in text


def test_draw_engine(tmp_path: Path):
    doc = snapshot_from_dict(
        "p",
        {"a": "22.86mm", "b": "10.16mm"},
        roles={"a": "rf_critical", "b": "rf_critical"},
        tol_classes={"a": "WG_AB", "b": "WG_AB"},
        labels={"a": "a", "b": "b"},
    )
    out = render_drawing(tmp_path / "d.dxf", doc, config=DrawingConfig(part_id="p"))
    assert out.exists()
    t = out.read_text(encoding="utf-8", errors="ignore")
    assert "TEXT" in t or "MTEXT" in t


def test_multisheet(tmp_path: Path):
    dims = snapshot_from_dict(
        "p1", {"a": "22.86mm", "L": "40mm"}, roles={"a": "rf_critical"}, tol_classes={"a": "WG_AB"}
    )
    chars = [CriticalChar("CH-001", "a", 22.86, 0.03, 0.03, source_var="a")]
    out = render_two_sheet(tmp_path / "ms.dxf", dims, chars)
    assert out.exists()
    text = out.read_text(encoding="utf-8", errors="ignore")
    assert "CHARACTERIST" in text.upper() or "CH-001" in text or "TEXT" in text


def test_pack_and_chars(tmp_path: Path):
    doc = snapshot_from_dict("p", {"a": "1.0mm"}, roles={"a": "rf_critical"}, tol_classes={"a": "IRIS"})
    dims_p = save_dims(tmp_path / "dims.json", doc)
    chars_p = save_critical_chars(
        tmp_path / "c.csv",
        [CriticalChar("CH-001", "a", 1.0, 0.02, 0.02, source_var="a")],
    )
    assert load_critical_chars(chars_p)[0].nominal == pytest.approx(1.0)
    idx = pack_deliverable(
        tmp_path / "out",
        dims=doc,
        files={"dims": dims_p, "chars": chars_p},
        audit_passed=True,
        write_notes=["note"],
    )
    assert (idx.root / "manifest.json").exists()
    assert (idx.root / "audit_report.md").exists()
    assert idx.audit_passed


def test_pack_manifest_hashes_present(tmp_path: Path):
    """打包 manifest 哈希面：二次 save 后 manifest 自身哈希收录（R3 原型
    pack_store 行为保真钉）。"""
    doc = snapshot_from_dict("p2", {"a": "2.0mm"})
    dims_p = save_dims(tmp_path / "dims.json", doc)
    idx = pack_deliverable(tmp_path / "pkg", dims=doc, files={"dims": dims_p}, audit_passed=True)
    man = json.loads((idx.root / "manifest.json").read_text(encoding="utf-8"))
    assert man["hashes"].get("dims.json")
    assert man["audit_gate"]["passed"] is True


def test_rfq_checklist():
    lines = rfq_checklist(["a", "b"], ["a"])
    assert any("关键" in x for x in lines)
    assert any("part.step" in x for x in lines)


def test_geometry_envelope_and_summary(tmp_path: Path):
    g = geometry_from_dims_envelope(60, 25.4, 12.7, ["housing"])
    assert g.volume == 60 * 25.4 * 12.7
    g2 = geometry_from_dims_envelope(60, 25.4, 12.7)
    assert compare_geometry(g, g2)["d_vol_rel"] < 1e-15
    p = write_geometry_summary_json(tmp_path / "g.json", g, g2, 0.0)
    loaded = load_geometry_summary_json(p)
    assert abs(loaded["hfss"].volume - g.volume) < 1e-9


def test_pcb_checklist(tmp_path: Path):
    p = write_pcb_checklist(tmp_path)
    assert p.exists()
    assert any("IPC-2581" in line for line in PCB_DELIVERABLE_CHECKLIST)


# ─── adapters：QIF/G 代码/3D 文档/SpaceClaim（原型 enhancements 移植） ──


def test_qif3_document(tmp_path: Path):
    dims = snapshot_from_dict("p1", {"a": "22.86mm"})
    chars = [CriticalChar("CH-001", "a", 22.86, 0.03, 0.03, source_var="a", meas_method="CMM")]
    p = write_qif3_document(tmp_path / "qif3.xml", dims, chars)
    t = p.read_text(encoding="utf-8")
    assert "QIFDocument" in t
    assert "CharacteristicDef" in t
    assert "millimeter" in t
    # 纯渲染函数与写盘同源（L0/IO 分界钉）
    assert render_qif3_document(dims, chars) == t


def test_gcode_program(tmp_path: Path):
    prog = build_wr90_program()
    assert len(prog.ops) == 3
    text = prog.render()
    assert "G21" in text and "M30" in text
    p = write_gcode(tmp_path / "ops.nc", prog)
    assert p.exists()
    rep = write_cam_report(tmp_path / "rep.md", prog)
    rep_text = rep.read_text(encoding="utf-8")
    assert "bolt_holes" in rep_text
    assert ToolSpec().dia == 6.0


def test_doc3d(tmp_path: Path):
    dims = snapshot_from_dict("p1", {"a": "22.86mm", "L": "40mm", "b": "10.16mm", "wall": "1.27mm"})
    g = write_gltf_from_dims(tmp_path / "m.gltf", dims)
    assert g.exists()
    assert (tmp_path / "m.bin").exists()
    h = write_html_viewer(tmp_path / "m.html", dims)
    html = h.read_text(encoding="utf-8")
    assert "canvas" in html
    # 审查项 R7 回归钉：HTML 线框 B=b+2·wall（原型误用 a → 方截面）
    assert f"B={10.16 + 2 * 1.27}" in html
    pdf = write_3d_pdf(tmp_path / "m3d.pdf", dims)
    assert pdf.exists() and pdf.stat().st_size > 1000


def test_spaceclaim_script_and_null(tmp_path: Path):
    req = HealRequest(input_step=tmp_path / "in.step", output_step=tmp_path / "out.step")
    r = SpaceClaimScriptHealer().heal(req)
    assert r.ok and r.mode == "script"
    assert Path(r.script_path).exists()
    n = NullHealer().heal(req)
    assert n.mode == "none"


# ─── 注册表（原型 plugins 移植，FabPortRegistry 归一名） ─────────────


def test_builtin_plugins_registered():
    reg = ensure_builtin_plugins()
    assert "pyaedt" in reg.names("geometry_export")
    assert "mock" in reg.names("geometry_export")
    assert "ezdxf" in reg.names("draw")
    assert "filesystem" in reg.names("pack")
    assert "file" in reg.names("geometry_read")
    assert "dict" in reg.names("dims")
    assert "gltf" in reg.names("doc3d")
    assert "qif3" in reg.names("qif")
    assert "gcode" in reg.names("cam")
    assert "spaceclaim_script" in reg.names("heal")
    assert "none" in reg.names("heal")


def test_create_mock_exporter():
    reg = get_registry()
    ensure_builtin_plugins()
    exp = reg.create("geometry_export", "mock")
    assert exp.name == "mock"


def test_entry_points_safe():
    n = load_entry_point_plugins()
    assert isinstance(n, int)


# ─── service：一键编排（原型 go 移植；examples 内联） ─────────────────


def test_go_from_vars_ready(tmp_path: Path):
    vars_path = tmp_path / "v.json"
    vars_path.write_text(
        json.dumps({
            "part_id": "t1",
            "rev": "B",
            "variables": {"a": "22.86mm", "b": "10.16mm", "L": "40mm", "iris_w": "3.2mm"},
        }),
        encoding="utf-8",
    )
    env = fab_go_from_vars(vars_path, tmp_path / "pkg", work_dir=tmp_path / "work")
    assert env["ok"], env["errors"]
    assert env["package_ready"]
    pkg = Path(env["package_dir"])
    assert (pkg / "drawing.dxf").exists()
    assert (pkg / "dims.json").exists()
    assert (pkg / "audit_report.md").exists()
    assert (pkg / "go_result.json").exists()
    assert (pkg / "rfq_checklist.md").exists()
    # 自动推断 iris
    dims = json.loads((pkg / "dims.json").read_text(encoding="utf-8"))
    by = {v["name"]: v for v in dims["variables"]}
    assert by["iris_w"]["tol_class"] == "IRIS"
    assert by["a"]["tol_class"] == "WG_AB"


def test_go_from_wr90_golden_vars(tmp_path: Path):
    """金样 WR90 变量集端到端（原型 examples/wr90_vars.json 内联等值）."""
    vars_path = tmp_path / "wr90_vars.json"
    vars_path.write_text(json.dumps(WR90_VARS, ensure_ascii=False), encoding="utf-8")
    env = fab_go_from_vars(vars_path, tmp_path / "fab_wr90_go", work_dir=tmp_path / "_work_go")
    assert env["ok"], env["errors"]
    pkg = Path(env["package_dir"])
    assert (pkg / "go_result.json").exists()
    dims = json.loads((pkg / "dims.json").read_text(encoding="utf-8"))
    by = {v["name"]: v for v in dims["variables"]}
    assert by["a"]["value"] == pytest.approx(22.86)
    assert by["a"]["role"] == "rf_critical"
    assert by["L"]["role"] == "assembly"


def test_fab_pipeline_offline(tmp_path: Path):
    """轻量离线链（原型 cmd_pipeline 下沉 service）：FAIL 信封如实."""
    vars_path = tmp_path / "v.json"
    vars_path.write_text(
        json.dumps({"part_id": "pp", "variables": {"a": "22.86mm", "L": "40mm"},
                    "roles": {"a": "rf_critical"}, "tol_classes": {"a": "WG_AB"}}),
        encoding="utf-8",
    )
    env = fab_pipeline(vars_path, tmp_path / "work")
    assert env["ok"], env["audit_errors"]
    out = Path(env["package_dir"])
    assert (out / "rfq_checklist.md").exists()
    assert (out / "dims.json").exists()
    assert isinstance(env["files"], dict)


def test_audit_result_envelope_shape():
    """AuditResult 数据类契约（service 信封化的判据底座）."""
    doc = snapshot_from_dict("p", {"a": "22.86mm"})
    g = GeometrySummary((0, 0, 0), (25.4, 60, 12.7), 100.0)
    r = audit_package(doc, g, g)
    assert isinstance(r, AuditResult)
    assert r.raise_if_failed() is None


# ─── T48 方案↔实现差距补全（细则 §10.2/§10.3、主方案 §6.2/§6.3/§12/§13A.4） ─


def test_heal_kwargs_plan_table_aligned():
    """细则 §10.3 heal 保守预设逐参数对齐（pyaedt 1.4.0 签名核对）.

    关键钉：geometry_simplification_tolerance 官方缺省 1（mm，会吃 iris）
    必须钉 0.001；孔/倒角/圆角移除全 False；体积/面积变化容差 5%→0.01。
    """
    from rfauto.adapters.fab_export.hfss_export import conservative_heal_kwargs

    kw = conservative_heal_kwargs()
    assert kw["max_stitch_tolerance"] == pytest.approx(0.001)
    assert kw["geometry_simplification_tolerance"] == pytest.approx(0.001)
    assert kw["simplify_geometry"] is False
    assert kw["tighten_gaps"] is True
    assert kw["tighten_gaps_width"] == pytest.approx(1e-5)
    assert kw["remove_holes"] is False
    assert kw["remove_chamfers"] is False
    assert kw["remove_blends"] is False
    assert kw["remove_silver_faces"] is True
    assert kw["remove_small_edges"] is True
    assert kw["allowable_volume_change"] == pytest.approx(0.01)
    assert kw["allowable_surface_area_change"] == pytest.approx(0.01)
    assert kw["auto_heal"] is False
    assert kw["heal_to_solid"] is False
    assert kw["explode_and_stitch"] is True


class _MockModeler:
    def __init__(self):
        self.objects = {"housing": type("_Obj", (), {"volume": 100.0})()}
        self.heal_calls: list[dict] = []
        self.import_calls: list[dict] = []

    def heal_objects(self, **kwargs):
        self.heal_calls.append(kwargs)
        return True

    def import_3d_cad(self, path, **kwargs):
        self.import_calls.append({"path": path, **kwargs})
        return True


def test_heal_for_fab_logs_volume_before_after():
    """细则 §10.3「每次 heal 必须写 heal_log（参数+前后体积）」——体积
    best-effort 采集（mock 对象有 volume → 记录；无则 None 不阻塞）。"""
    from types import SimpleNamespace

    from rfauto.adapters.fab_export.hfss_export import heal_for_fab

    m = _MockModeler()
    entry = heal_for_fab(SimpleNamespace(modeler=m), "housing")
    assert entry["ok"] is True
    assert entry["params"]["simplify_geometry"] is False
    assert entry["volume_before"] == pytest.approx(100.0)
    assert entry["volume_after"] == pytest.approx(100.0)

    class _NoVol:
        pass

    m2 = _MockModeler()
    m2.objects = {"housing": _NoVol()}
    entry2 = heal_for_fab(SimpleNamespace(modeler=m2), "housing")
    assert entry2["volume_before"] is None and entry2["volume_after"] is None


def test_conservative_import_kwargs_and_import_for_fab():
    """细则 §10.2 import_3d_cad 生产钉法：禁 Auto 单位（input_file_unit
    缺省 Auto 是官方文档陷阱）、先不 heal、reduce_stl 以签名为准 False。"""
    from types import SimpleNamespace

    from rfauto.adapters.fab_export.hfss_export import (
        conservative_import_kwargs,
        import_for_fab,
    )

    kw = conservative_import_kwargs()
    assert kw["input_file_unit"] == "mm"
    assert kw["healing"] is False
    assert kw["point_coincidence_tolerance"] == pytest.approx(1e-6)
    assert kw["merge_planar_faces"] is True
    assert kw["merge_angle"] == pytest.approx(0.02)
    assert kw["reduce_stl"] is False

    m = _MockModeler()
    rep = import_for_fab(SimpleNamespace(modeler=m), "part.step")
    assert rep["ok"] is True and rep["params"]["input_file_unit"] == "mm"
    assert m.import_calls[0]["path"] == "part.step"


def test_dfm_notes_cam_friendly():
    """主方案 §6.2 CAM 友好标注的 DFM 图注行：穿丝/预钻孔、型腔基准、薄壁."""
    lines = dfm_notes(wall=0.8)
    joined = "\n".join(lines)
    assert "穿丝" in joined and "预钻" in joined
    assert "型腔基准 A/B/C" in joined and "禁止只标外轮廓" in joined
    assert "薄壁警示" in joined and "0.8" in joined
    # 壁厚达标时无薄壁警示、按 1184-K 兜底
    plain = "\n".join(dfm_notes(wall=1.27))
    assert "薄壁警示" not in plain and "GB/T 1184-K" in plain


def test_flange_critical_chars_cmm_template():
    """细则 §1.1c/§1.3：法兰族检验特性（平面度无名义值、销孔 H7 +0.010/0）."""
    chars = flange_critical_chars("FBP100")
    ids = {c.char_id for c in chars}
    assert {"CH-F01", "CH-F02", "CH-F03", "CH-F04"} <= ids
    flat = next(c for c in chars if c.char_id == "CH-F01")
    assert flat.nominal is None  # 平面度无名义值（细则 CH-004 同形态）
    assert flat.tol_plus == pytest.approx(0.03)
    pin = next(c for c in chars if c.char_id == "CH-F04")
    assert pin.nominal == pytest.approx(2.5)
    assert pin.tol_plus == pytest.approx(0.010) and pin.tol_minus == pytest.approx(0.0)


def test_standards_r2_and_perpendicularity():
    """细则 §1.1 R2 外圆角范围 + §1.1b 法兰垂直度入标准库与目录."""
    wg = get_waveguide("WR-90")
    assert wg.r2 == (0.65, 1.15)
    fl = get_flange("UG-39")
    assert fl.perpendicularity == pytest.approx(0.05)
    cat = catalog_tables()
    assert cat["waveguides"]["WR-90"]["r2"] == (0.65, 1.15)
    assert cat["flanges"]["FBP100"]["perpendicularity_mm_per_100"] == pytest.approx(0.05)


def test_apply_tolerance_dimstyle_override():
    """细则 §3.1 set_tolerance 模式：偏差写 dimtol/dimtp/dimtm（非纯文本）；
    fit（H7/6H）与零偏差回退文本形态。"""
    import ezdxf


    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    rs = default_ruleset()
    dim = msp.add_linear_dim(base=(10, 10), p1=(0, 0), p2=(20, 0))
    assert _apply_tolerance(dim, rs.tol_for("WG_AB")) is True
    assert dim.dimstyle_attribs["dimtol"] == 1
    assert dim.dimstyle_attribs["dimtp"] == pytest.approx(0.03)
    assert dim.dimstyle_attribs["dimtm"] == pytest.approx(0.03)
    # 不对称偏差：+0.05/-0.02 → dimtm 存幅度正值
    dim2 = msp.add_linear_dim(base=(10, 0), p1=(0, 0), p2=(20, 0))
    asym = type("_T", (), {"fit": None, "plus": 0.05, "minus": 0.02})()
    assert _apply_tolerance(dim2, asym) is True
    assert dim2.dimstyle_attribs["dimtp"] == pytest.approx(0.05)
    assert dim2.dimstyle_attribs["dimtm"] == pytest.approx(0.02)
    # fit 类不叠排
    dim3 = msp.add_linear_dim(base=(10, -10), p1=(0, 0), p2=(20, 0))
    assert _apply_tolerance(dim3, rs.tol_for("PIN_H7")) is False


def test_dim_text_appends_var_name_suffix():
    """主方案 §12：关键尺寸后缀 (变量名)——label≠name 时追加可回溯后缀."""

    v = snapshot_from_dict(
        "p", {"a": "22.86mm"}, roles={"a": "rf_critical"}, tol_classes={"a": "WG_AB"},
        labels={"a": "内腔宽边a"},
    ).variables[0]
    tol = default_ruleset().tol_for("WG_AB")
    assert _dim_text(v, tol) == "内腔宽边a 22.86±0.03(a)"
    v2 = snapshot_from_dict("p", {"b": "10.16mm"}).variables[0]  # label 缺省=名
    assert _dim_text(v2, tol) == "b 10.16±0.03"


def test_render_process_table_and_gb_fields(tmp_path: Path):
    """主方案 §6.2 特征旁注（工艺表 WEDM）+ 细则 §2.1/§13.1 GB 标题栏字段
    全集（年月日/阶段标记/标准化/共_张 第_张）上图。"""

    doc = snapshot_from_dict(
        "p1",
        {"a": "22.86mm", "b": "10.16mm", "iris_w": "3.2mm", "wall": "1.27mm"},
        roles={"a": "rf_critical", "b": "rf_critical", "iris_w": "rf_critical"},
        tol_classes={"a": "WG_AB", "b": "WG_AB", "iris_w": "IRIS"},
        labels={"a": "内腔宽边a", "b": "内腔窄边b", "iris_w": "耦合窗宽"},
    )
    cfg = DrawingConfig(
        part_id="P-48", date="2026-09-29", stage="S1", standardize="王五",
        technologist="李四", sheet_no=1, sheet_total=2,
    )
    out = render_drawing(tmp_path / "gb.dxf", doc, config=cfg)
    t = out.read_text(encoding="utf-8", errors="ignore")
    assert "工艺表" in t and "WEDM" in t  # §6.2 特征旁注
    assert "2026-09-29" in t and "S1" in t and "王五" in t  # GB 字段
    assert "共 2 张  第 1 张" in t
    assert "薄壁警示" not in t  # wall=1.27 ≥ 1.0：无薄壁警示、有通用行
    assert "型腔基准 A/B/C" in t  # dims 传入 → DFM 行自动追加


def test_default_notes_plan_sections():
    """主方案 §6.3 七条 + §13A.4 #2：法兰平面度/销孔 H7、镀后复测、表处
    单边厚度补偿进默认图注."""
    notes = default_notes()
    joined = "\n".join(notes)
    assert "GB/T 1804-m" in joined and "GB/T 1184-K" in joined
    assert "法兰贴合面平面度" in joined and "H7" in joined
    assert "镀后复测内腔" in joined
    assert "0.005–0.008mm" in joined  # 表处单边厚度（镀前留量）
    assert len(notes) == 9


def test_write_btp_cover_fields(tmp_path: Path):
    """主方案 §13A.4 增补 #5：build-to-print 封面（零件号/Rev/数量/材料/表处）."""
    doc = snapshot_from_dict(
        "wg_wr90", {"a": "22.86mm"},
        roles={"a": "rf_critical"}, tol_classes={"a": "WG_AB"},
        standards={"a": "WR-90/BJ100"},
    )
    p = write_btp_cover(tmp_path, doc, quantity="10", material="AL6061-T6")
    t = p.read_text(encoding="utf-8")
    assert "wg_wr90" in t and "Rev" in t and "10" in t
    assert "AL6061-T6" in t and "表面处理" in t
    assert "WR-90/BJ100" in t  # 关键尺寸带标准引用
    assert "build-to-print" in t.lower()
    assert p.name == "build_to_print_cover.md"


def test_write_capability_table(tmp_path: Path):
    """主方案 §13A.4 增补 #6：能力表附件（optional/，Precision Micro 模式）."""
    p = write_capability_table(tmp_path)
    assert p.parts[-3:-1] == ("optional", "capability_table.md") or p.parent.name == "optional"
    t = p.read_text(encoding="utf-8")
    assert "WR-90" in t and "FBP100" in t
    assert "press_interference" in t  # 嘉立创配合带
    assert "Kerr" in t or "kerr" in t


def test_rfq_checklist_business_sections():
    """主方案 §13.2/细则 §6.3：商务（NDA/GJB/变更流程）+ 设备能力 + 质量体系."""
    lines = rfq_checklist(["a"], ["a"])
    joined = "\n".join(lines)
    assert "NDA" in joined and "GJB" in joined
    assert "回写 HFSS" in joined
    assert "WEDM" in joined  # 设备能力：iris 走线切割是否本厂
    assert "ISO9001" in joined
    assert "build_to_print_cover.md" in joined


def test_multisheet_meas_method_column(tmp_path: Path):
    """主方案 §13A.4 增补 #4：检验方法栏上特性表（Sheet2 列头含 meas_method）."""
    from rfauto.adapters.fab_export.multisheet import render_two_sheet

    dims = snapshot_from_dict(
        "p1", {"a": "22.86mm"}, roles={"a": "rf_critical"}, tol_classes={"a": "WG_AB"}
    )
    chars = flange_critical_chars("FBP100")
    out = render_two_sheet(tmp_path / "ms.dxf", dims, chars)
    t = out.read_text(encoding="utf-8", errors="ignore")
    assert "meas_method" in t
    assert "CH-F01" in t and "CMM" in t
    assert "共 2 张" in t  # 标题栏 sheet 口径落地


def test_go_package_btp_flange_chars_and_dated_dir(tmp_path: Path):
    """go 全链：封面/能力表/法兰检验特性入包；缺省目录名带日期
    （主方案 §5.1 fab_<part>_<rev>_<date>）。"""
    vars_path = tmp_path / "v.json"
    vars_path.write_text(
        json.dumps({
            "part_id": "t48",
            "rev": "C",
            "variables": {"a": "22.86mm", "b": "10.16mm", "L": "40mm"},
            "roles": {"a": "rf_critical", "b": "rf_critical"},
            "tol_classes": {"a": "WG_AB", "b": "WG_AB"},
        }),
        encoding="utf-8",
    )
    env = fab_go_from_vars(vars_path, None, work_dir=tmp_path / "w")
    assert env["ok"], env["errors"]
    pkg = Path(env["package_dir"])
    assert re.fullmatch(r"fab_t48_C_\d{8}", pkg.name), pkg.name
    assert (pkg / "build_to_print_cover.md").exists()
    assert (pkg / "optional" / "capability_table.md").exists()
    chars_csv = (pkg / "critical_chars.csv").read_text(encoding="utf-8")
    assert "CH-F01" in chars_csv and "平面度" in chars_csv
    assert (pkg / "rfq_checklist.md").exists()


# ─── R3-2 STEP 几何溯源（runs/review_ge8e/f3_fix/REPORT.md）───────────────────


def test_go_from_vars_geometry_source_envelope_fallback(tmp_path: Path):
    """R3-2 回归钉：STEP 读失败/缺失回退包络估计必须留痕
    （geometry_source=envelope_estimate + warnings 非空 + go_result.json 落键）。"""
    vars_path = tmp_path / "v_fb.json"
    vars_path.write_text(json.dumps({
        "part_id": "t1", "rev": "B",
        "variables": {"a": "22.86mm", "b": "10.16mm", "L": "40mm"},
    }), encoding="utf-8")
    env = fab_go_from_vars(vars_path, tmp_path / "pkg_fb",
                           work_dir=tmp_path / "work_fb")
    assert env["ok"], env["errors"]
    assert env["geometry_source"] == "envelope_estimate"
    assert env["warnings"], "回退必须追加 warning（静默回退禁令）"
    assert any("envelope_estimate" in w for w in env["warnings"])
    go = json.loads((Path(env["package_dir"]) / "go_result.json").read_text(
        encoding="utf-8"))
    assert go["geometry_source"] == "envelope_estimate"


def test_board_thickness_constant_is_50mil_fr4(tmp_path: Path):
    """F-4/S3：包络估计板厚魔数收敛为单源常量 _BOARD_THICKNESS_MM。

    出处：1.27mm = 0.050in×25.4 = 50mil FR4 标称板厚；bbox/volume/com-z
    全部从该常量派生（含半厚 0.635），不再多点内联漂移。"""
    from rfauto.service.fab_export_service import (
        _BOARD_MID_Z_MM,
        _BOARD_THICKNESS_MM,
    )

    thickness_mm = _BOARD_THICKNESS_MM
    mid_z_mm = _BOARD_MID_Z_MM
    assert thickness_mm == pytest.approx(0.050 * 25.4)
    assert mid_z_mm == pytest.approx(thickness_mm / 2)
    # go_from_vars 包络回退几何面逐值吃该常量（bbox_max z / volume）
    vars_path = tmp_path / "v_bt.json"
    vars_path.write_text(json.dumps({
        "part_id": "t1", "rev": "B",
        "variables": {"a": "22.86mm", "b": "10.16mm", "L": "40mm"},
    }), encoding="utf-8")
    env = fab_go_from_vars(vars_path, tmp_path / "pkg_bt",
                           work_dir=tmp_path / "work_bt")
    assert env["ok"], env["errors"]
    assert env["geometry_source"] == "envelope_estimate"


def test_go_from_vars_geometry_source_step(tmp_path: Path, monkeypatch):
    """R3-2 对照钉：STEP 读取成功 → geometry_source="step"。"""
    from rfauto.adapters.fab_export import geometry_io
    from rfauto.core.fab_export.audit import GeometrySummary

    monkeypatch.setattr(
        geometry_io, "geometry_from_brep_file",
        lambda path: GeometrySummary((0, 0, 0), (25.4, 60, 12.7), 100.0))
    work = tmp_path / "work_step"
    work.mkdir()
    (work / "part.step").write_text("ISO-10303-21;\n", encoding="utf-8")
    vars_path = tmp_path / "v_step.json"
    vars_path.write_text(json.dumps({
        "part_id": "t1", "rev": "B",
        "variables": {"a": "22.86mm", "b": "10.16mm", "L": "40mm"},
    }), encoding="utf-8")
    env = fab_go_from_vars(vars_path, tmp_path / "pkg_step", work_dir=work)
    assert env["ok"], env["errors"]
    assert env["geometry_source"] == "step"
