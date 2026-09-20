"""B3 STEP/STL 导入单测：解析度量 / 分类器 / 闭环一致性 / 服务契约 / #212 离线审计。

夹具全部在 tmp_path 程序化生成（12 三角盒、N 边棱柱、缺面盒、ASCII 变体、
坏头长度），不入库二进制。判据口径：
- 度量裁判 = 闭式解（盒 V=abc、N 边棱柱 V=(N/2)r²sin(2π/N)h → πr²h 收敛）；
- 闭环 = 整数坐标盒（float32 精确可表示）STL→解析→分类器→计算器 与直接盒参数
  结果 dict 相等（浮点逐位一致）；
- #212 离线几何审计 = 最小 ContinuousStructure 场景应用/exec 生成行，
  CSXCAD 实测原语 bbox 与 STL bbox 一致（≤1e-9 m），不做字符串存在性检查；
  PolyhedronReader 原语 ReadFile 后 bbox 为文件原生 mm、IsInside 按 Scale
  变换后的 m 坐标（2026-09-15 绑定实测），据此审计而非标 unmeasured。
"""

from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "src"
for p in (str(SRC), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rfauto.adapters.solid_import import (
    apply_solids,
    classify_solid,
    csx_lines,
)
from rfauto.core.solid_mesh import (
    SolidMeshError,
    parse_stl_bytes,
    parse_stl_file,
    solid_mesh_from_triangles,
)
from rfauto.service.calculator_service import run_calculator
from rfauto.service.solid_import_service import (
    REJECTED_SUFFIXES,
    import_solid_payload,
    scale_solid_payload,
)

# ─── 程序化 STL 夹具 ─────────────────────────────────────────────────────────


def _box_triangles(lo, hi) -> np.ndarray:
    """12 三角轴对齐盒（外法向定向）。"""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]],
                 dtype=float)
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    out = []
    for a, b, c, d in quads:
        out.append([v[a], v[b], v[c]])
        out.append([v[a], v[c], v[d]])
    return np.array(out)


def _prism_triangles(n_side: int, radius: float, z0: float, z1: float,
                     center=(0.0, 0.0)) -> np.ndarray:
    """N 边正棱柱（帽面扇形三角化含中心点——CAD 网格化惯例，外法向）。"""
    cx, cy = center
    ang = np.arange(n_side) * 2.0 * np.pi / n_side
    pts = np.stack([cx + radius * np.cos(ang), cy + radius * np.sin(ang)], axis=1)
    tris = []
    for k in range(n_side):
        a, b = pts[k], pts[(k + 1) % n_side]
        tris.append([[a[0], a[1], z0], [b[0], b[1], z0], [b[0], b[1], z1]])
        tris.append([[a[0], a[1], z0], [b[0], b[1], z1], [a[0], a[1], z1]])
    for k in range(n_side):
        a, b = pts[k], pts[(k + 1) % n_side]
        tris.append([[cx, cy, z0], [b[0], b[1], z0], [a[0], a[1], z0]])
        tris.append([[cx, cy, z1], [a[0], a[1], z1], [b[0], b[1], z1]])
    return np.array(tris, dtype=float)


def _tetra_triangles() -> np.ndarray:
    """外法向定向四面体（顶点 0/(4,0,0)/(0,4,0)/(0,0,4)），V=64/6。"""
    return np.array([
        [[0, 0, 0], [0, 4, 0], [4, 0, 0]],
        [[0, 0, 0], [4, 0, 0], [0, 0, 4]],
        [[0, 0, 0], [0, 0, 4], [0, 4, 0]],
        [[4, 0, 0], [0, 4, 0], [0, 0, 4]],
    ], dtype=float)


def _write_binary_stl(path: Path, tris: np.ndarray) -> None:
    t32 = np.asarray(tris, dtype=np.float32)
    buf = bytearray(b"\0" * 80)
    buf += struct.pack("<I", len(t32))
    for tri in t32:
        nrm = np.cross(tri[1] - tri[0], tri[2] - tri[0]).astype(float)
        nrm = nrm / max(float(np.linalg.norm(nrm)), 1e-30)
        buf += struct.pack("<12fH", *nrm, *[float(c) for v in tri for c in v], 0)
    path.write_bytes(bytes(buf))


def _write_ascii_stl(path: Path, tris: np.ndarray) -> None:
    t32 = np.asarray(tris, dtype=np.float32)
    lines = ["solid fixture"]
    for tri in t32:
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        for v in tri:
            lines.append(f"      vertex {float(v[0])!r} {float(v[1])!r} {float(v[2])!r}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid fixture")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


BOX_LO, BOX_HI = (10.0, 4.0, 5.0), (20.0, 14.0, 15.0)   # 10×10×10 盒


@pytest.fixture
def box_stl(tmp_path: Path) -> Path:
    path = tmp_path / "box.stl"
    _write_binary_stl(path, _box_triangles(BOX_LO, BOX_HI))
    return path


# ─── 解析与度量（core/solid_mesh）───────────────────────────────────────────


class TestSolidMeshParse:
    def test_binary_box_metrics_match_closed_form(self, box_stl: Path):
        mesh = parse_stl_file(box_stl)
        assert mesh.n_triangles == 12
        assert mesh.volume_mm3 == pytest.approx(1000.0, abs=1e-9)
        assert mesh.signed_volume_mm3 > 0  # 外法向
        lo, hi = mesh.bbox_mm
        assert lo.tolist() == list(BOX_LO) and hi.tolist() == list(BOX_HI)
        assert mesh.is_watertight and mesh.is_edge_manifold
        assert mesh.n_connected_components == 1
        assert mesh.n_degenerate_triangles == 0

    def test_ascii_variant_bitwise_same_metrics(self, tmp_path: Path, box_stl: Path):
        ascii_path = tmp_path / "box_ascii.stl"
        _write_ascii_stl(ascii_path, _box_triangles(BOX_LO, BOX_HI))
        a = parse_stl_file(ascii_path)
        b = parse_stl_file(box_stl)
        assert a.n_triangles == b.n_triangles == 12
        assert a.volume_mm3 == b.volume_mm3
        assert np.array_equal(a.bbox_mm[0], b.bbox_mm[0])
        assert np.array_equal(a.bbox_mm[1], b.bbox_mm[1])
        assert a.is_watertight

    def test_binary_header_length_mismatch_is_explicit_error(self, box_stl: Path):
        data = box_stl.read_bytes()
        truncated = data[:-7]  # 坏头：声明 12 三角，字节数对不上
        with pytest.raises(SolidMeshError, match="STL"):
            parse_stl_bytes(truncated)

    def test_non_stl_bytes_rejected(self):
        with pytest.raises(SolidMeshError):
            parse_stl_bytes(b"solid nothing here\nendsolid\n")
        with pytest.raises(SolidMeshError):
            parse_stl_bytes(bytes(range(256)) * 2)

    def test_open_box_missing_face_not_watertight(self):
        closed = _box_triangles(BOX_LO, BOX_HI)
        open_box = np.delete(closed, 4, axis=0)  # 去掉一片侧面（x-z 面）三角
        mesh = solid_mesh_from_triangles(open_box)
        assert not mesh.is_watertight
        assert not mesh.is_edge_manifold or mesh.n_triangles == 11
        assert mesh.n_connected_components == 1
        closed_mesh = solid_mesh_from_triangles(closed)
        assert closed_mesh.is_watertight
        # 缺面后散度体积不再等于闭式 1000（通量缺口如实体现）
        assert mesh.volume_mm3 != pytest.approx(1000.0, abs=1e-6)

    def test_prism_volume_converges_to_pi_r2_h(self):
        r, h = 3.0, 10.0
        ideal = math.pi * r * r * h
        errors = []
        for n in (12, 48, 192):
            mesh = solid_mesh_from_triangles(_prism_triangles(n, r, 0.0, h))
            assert mesh.is_watertight
            # 闭式：V_N = (N/2)·r²·sin(2π/N)·h（独立裁判）
            v_closed = n / 2.0 * r * r * math.sin(2 * math.pi / n) * h
            assert mesh.volume_mm3 == pytest.approx(v_closed, rel=1e-12)
            errors.append(abs(mesh.volume_mm3 - ideal) / ideal)
        assert errors[0] > errors[1] > errors[2]
        assert errors[2] < 2e-4

    def test_tetrahedron_watertight_volume(self):
        mesh = solid_mesh_from_triangles(_tetra_triangles())
        assert mesh.is_watertight
        assert mesh.volume_mm3 == pytest.approx(64.0 / 6.0, rel=1e-12)

    def test_scaled_volume_cubed_and_degenerate_count(self):
        base = _box_triangles(BOX_LO, BOX_HI)
        mesh = solid_mesh_from_triangles(base)
        assert mesh.scaled(2.0).volume_mm3 == pytest.approx(8.0 * mesh.volume_mm3, rel=1e-12)
        with_degenerate = np.concatenate(
            [base, np.array([[[1.0, 1.0, 1.0], [2.0, 2.0, 2.0], [3.0, 3.0, 3.0]]])])
        assert solid_mesh_from_triangles(with_degenerate).n_degenerate_triangles == 1
        with pytest.raises(SolidMeshError):
            solid_mesh_from_triangles([[0.0, 0.0, 0.0]])


# ─── 分类器（adapters/solid_import）─────────────────────────────────────────


class TestClassifier:
    def test_box_route_exact_addbox(self, box_stl: Path):
        payload = classify_solid(parse_stl_file(box_stl), name="blk",
                                 stl_path=str(box_stl))
        assert payload["kind"] == "box" and payload["primitive"] == "AddBox"
        assert payload["approximation"] == {"kind": "exact", "volume_rel_err": 0.0}
        assert payload["requires_stl_at_solve_time"] is False
        assert payload["stl_path"] is None
        assert payload["csx_args_m"]["start"] == [v / 1000.0 for v in BOX_LO]
        assert payload["csx_args_m"]["stop"] == [v / 1000.0 for v in BOX_HI]
        assert payload["bbox_mm"] == {"lo": list(BOX_LO), "hi": list(BOX_HI)}
        assert payload["volume_mm3"] == pytest.approx(1000.0, abs=1e-9)

    def test_hexagon_prism_linpoly_exact(self):
        mesh = solid_mesh_from_triangles(_prism_triangles(6, 5.0, 2.0, 10.0, (1.0, -3.0)))
        payload = classify_solid(mesh, name="hex")
        assert payload["kind"] == "linpoly" and payload["primitive"] == "AddLinPoly"
        assert payload["approximation"]["kind"] == "exact"
        assert payload["approximation"]["volume_rel_err"] < 1e-12
        args = payload["csx_args_m"]
        assert args["norm_dir"] == 2
        assert args["elevation"] == pytest.approx(0.002) and args["length"] == pytest.approx(0.008)
        # CSXCAD 约定：points=[xs, ys] 两列（绑定 .pyx 断言 len==2，实测）
        assert len(args["points"]) == 2 and len(args["points"][0]) == 6
        assert payload["requires_stl_at_solve_time"] is False

    def test_high_n_ring_cylinder_lsq_declared(self):
        n, r, h = 64, 3.0, 12.0
        mesh = solid_mesh_from_triangles(_prism_triangles(n, r, 0.0, h, (5.0, -2.0)))
        payload = classify_solid(mesh, name="cyl")
        assert payload["kind"] == "cylinder" and payload["primitive"] == "AddCylinder"
        approx = payload["approximation"]
        assert approx["kind"] == "lsq_radius" and approx["n_ring_vertices"] == n
        assert approx["ring_lsq_residual"] < 1e-9
        # 申报的体积近似误差 = 1 − (N/2π)·sin(2π/N)（独立闭式）
        expect_err = abs(1.0 - n / (2 * math.pi) * math.sin(2 * math.pi / n)) / (
            n / (2 * math.pi) * math.sin(2 * math.pi / n))
        assert approx["volume_rel_err"] == pytest.approx(expect_err, rel=1e-6)
        args = payload["csx_args_m"]
        assert args["radius"] == pytest.approx(r / 1000.0, rel=1e-9)
        assert args["start"] == pytest.approx([0.005, -0.002, 0.0], abs=1e-12)
        assert args["stop"] == pytest.approx([0.005, -0.002, 0.012], abs=1e-12)

    def test_fallback_engine_route_requires_stl_path(self, box_stl: Path):
        mesh = solid_mesh_from_triangles(_tetra_triangles())
        with pytest.raises(ValueError, match="stl_path"):
            classify_solid(mesh, name="tet")
        payload = classify_solid(mesh, name="tet", stl_path=str(box_stl))
        assert payload["kind"] == "polyhedron_reader"
        assert payload["requires_stl_at_solve_time"] is True
        assert payload["approximation"] == {"kind": "engine_stl", "volume_rel_err": 0.0}
        assert payload["csx_args_m"]["scale_to_m"] == 1e-3
        assert payload["csx_args_m"]["file_units"] == "mm"

    def test_csx_lines_shapes(self, box_stl: Path):
        box = classify_solid(parse_stl_file(box_stl), name="blk")
        cyl = classify_solid(solid_mesh_from_triangles(
            _prism_triangles(64, 3.0, 0.0, 12.0)), name="cyl")
        hexa = classify_solid(solid_mesh_from_triangles(
            _prism_triangles(6, 5.0, 0.0, 8.0)), name="hex", material="metal")
        tet = classify_solid(solid_mesh_from_triangles(_tetra_triangles()),
                             name="tet", material="screw", stl_path=str(box_stl))
        lines = csx_lines([box, cyl, hexa, tet], csx_var="CSX")
        # 同 material 共享一条属性行；不同 material 各一条
        assert sum(".AddMetal(" in ln for ln in lines) == 2
        assert lines[0] == "_solid_import_metal = CSX.AddMetal('metal')"
        assert any(".AddBox(start=" in ln for ln in lines)
        assert any(".AddCylinder(start=" in ln and "radius=" in ln for ln in lines)
        assert any(".AddLinPoly(points=" in ln and "norm_dir=2" in ln for ln in lines)
        assert any(".AddPolyhedronReader(" in ln for ln in lines)
        assert any(".AddTransform('Scale', 0.001)" in ln for ln in lines)


# ─── 闭环：STL 盒 → 解析 → 分类器 → 计算器 与直接盒参数逐位一致 ───────────────


class TestClosedLoop:
    CAVITY: ClassVar[dict[str, float]] = {"a_mm": 30.0, "b_mm": 10.0, "d_mm": 40.0}
    SAMPLE_LO, SAMPLE_HI = (14.0, 4.0, 19.0), (16.0, 6.0, 21.0)  # 整数坐标：float32 精确

    def test_stl_loop_bitwise_equals_direct_box(self, tmp_path: Path):
        direct = run_calculator("cavity_perturbation_shift", {
            **self.CAVITY, "sample_box_mm": list(self.SAMPLE_LO) + list(self.SAMPLE_HI),
            "sample_eps_r": 2.1})
        assert direct["ok"], direct
        path = tmp_path / "sample.stl"
        _write_binary_stl(path, _box_triangles(self.SAMPLE_LO, self.SAMPLE_HI))
        payload = classify_solid(parse_stl_file(path), name="sample", stl_path=str(path))
        assert payload["kind"] == "box"
        loop_box = payload["bbox_mm"]["lo"] + payload["bbox_mm"]["hi"]
        via = run_calculator("cavity_perturbation_shift", {
            **self.CAVITY, "sample_box_mm": loop_box, "sample_eps_r": 2.1})
        assert via == direct  # dict 相等 ⇒ 浮点逐位一致（含 df_over_f/f0）
        assert via["result"]["route"] == "analytic_box"

    def test_mesh_route_converges_to_analytic_box(self, tmp_path: Path):
        """#118 双裁判：体素网格路线随步长收敛到解析盒路线（同一 STL 盒）。"""
        path = tmp_path / "sample.stl"
        _write_binary_stl(path, _box_triangles(self.SAMPLE_LO, self.SAMPLE_HI))
        mesh = parse_stl_file(path)
        analytic = run_calculator("cavity_perturbation_shift", {
            **self.CAVITY, "sample_box_mm": list(self.SAMPLE_LO) + list(self.SAMPLE_HI),
            "sample_eps_r": 2.1})["result"]["df_over_f"]
        errors = []
        for vox in (1.0, 0.5, 0.25):
            out = run_calculator("cavity_perturbation_shift", {
                **self.CAVITY, "sample_triangles_mm": mesh.triangles_mm.tolist(),
                "sample_eps_r": 2.1, "voxel_mm": vox})
            assert out["ok"], out
            r = out["result"]
            assert r["route"] == "voxel_mesh"
            assert r["voxel_vs_mesh_volume_rel_err"] == pytest.approx(0.0, abs=1e-12)
            errors.append(abs(r["df_over_f"] - analytic) / abs(analytic))
        assert errors[0] > errors[1] > errors[2]
        assert errors[2] < 2e-4

    def test_mesh_route_rejects_non_watertight_and_out_of_cavity(self):
        open_box = np.delete(_box_triangles(self.SAMPLE_LO, self.SAMPLE_HI), 4, axis=0)
        out = run_calculator("cavity_perturbation_shift", {
            **self.CAVITY, "sample_triangles_mm": open_box.tolist()})
        assert not out["ok"] and "水密" in out["error"]
        outside = _box_triangles((28.0, 4.0, 19.0), (32.0, 6.0, 21.0))
        out2 = run_calculator("cavity_perturbation_shift", {
            **self.CAVITY, "sample_triangles_mm": outside.tolist()})
        assert not out2["ok"] and "出腔" in out2["error"]


# ─── 服务层契约（solid_import_service）───────────────────────────────────────


class TestService:
    def test_import_payload_ok_json_deterministic(self, box_stl: Path):
        first = import_solid_payload(str(box_stl))
        assert first["ok"], first
        assert first["format"] == "stl_binary" and first["units"] == "mm"
        mesh = first["mesh"]
        assert mesh["n_triangles"] == 12 and mesh["is_watertight"] is True
        assert mesh["volume_mm3"] == pytest.approx(1000.0, abs=1e-9)
        assert mesh["n_connected_components"] == 1
        assert len(first["solids"]) == 1
        solid = first["solids"][0]
        assert solid["kind"] == "box" and solid["csx_lines"]
        text = json.dumps(first, sort_keys=True, ensure_ascii=False, allow_nan=False)
        second = import_solid_payload(str(box_stl))
        assert json.dumps(second, sort_keys=True, ensure_ascii=False, allow_nan=False) == text

    def test_ascii_import_reports_format(self, tmp_path: Path):
        path = tmp_path / "a.stl"
        _write_ascii_stl(path, _box_triangles(BOX_LO, BOX_HI))
        out = import_solid_payload(str(path))
        assert out["ok"] and out["format"] == "stl_ascii"

    def test_step_rejected_with_explicit_reason(self, tmp_path: Path):
        for suffix in (".step", ".stp", ".STEP"):
            out = import_solid_payload(str(tmp_path / f"part{suffix}"))
            assert out["ok"] is False
            assert "STEP" in out["error"] and "STL/PLY" in out["error"]
        assert set(REJECTED_SUFFIXES) == {".step", ".stp"}

    def test_unknown_suffix_missing_file_and_bad_content(self, tmp_path: Path):
        out = import_solid_payload(str(tmp_path / "part.obj"))
        assert out["ok"] is False and "不支持" in out["error"]
        out = import_solid_payload(str(tmp_path / "missing.stl"))
        assert out["ok"] is False and "不存在" in out["error"]
        bad = tmp_path / "bad.stl"
        bad.write_bytes(b"\0" * 90)
        out = import_solid_payload(str(bad))
        assert out["ok"] is False and "解析失败" in out["error"]

    def test_engine_route_import_and_scale_note(self, tmp_path: Path):
        path = tmp_path / "tet.stl"
        _write_binary_stl(path, _tetra_triangles())
        out = import_solid_payload(str(path), material="screw")
        assert out["ok"], out
        solid = out["solids"][0]
        assert solid["kind"] == "polyhedron_reader"
        assert solid["requires_stl_at_solve_time"] is True
        assert solid["stl_path"] == str(path)
        assert any("AddTransform('Scale', 0.001)" in ln for ln in solid["csx_lines"])
        scaled = scale_solid_payload(out, 1.01)
        assert "scale_note" in scaled["solids"][0]
        assert scaled["solids"][0]["csx_args_m"]["scale_to_m"] == 1e-3  # 单位映射不随缩放

    def test_scale_payload_volume_cubed_and_input_untouched(self, box_stl: Path):
        base = import_solid_payload(str(box_stl))
        snapshot = json.dumps(base, sort_keys=True)
        factor = 1.0 + 17e-6 * 100.0  # CTE 17 ppm/K × ΔT 100 K（D14 互操作口径）
        scaled = scale_solid_payload(base, factor)
        assert json.dumps(base, sort_keys=True) == snapshot  # 深拷贝，不改输入
        assert scaled["scaled_by"] == factor
        assert scaled["mesh"]["volume_mm3"] == pytest.approx(1000.0 * factor ** 3, rel=1e-12)
        assert scaled["solids"][0]["volume_mm3"] == pytest.approx(1000.0 * factor ** 3, rel=1e-12)
        assert scaled["mesh"]["bbox_mm"]["hi"] == pytest.approx(
            [v * factor for v in BOX_HI], rel=1e-12)
        assert scaled["solids"][0]["csx_args_m"]["stop"] == pytest.approx(
            [v * factor / 1000.0 for v in BOX_HI], rel=1e-12)
        assert scaled["solids"][0]["csx_lines"] != base["solids"][0]["csx_lines"]
        for bad in (0.0, -1.0, float("nan")):
            with pytest.raises(ValueError):
                scale_solid_payload(base, bad)


# ─── #212 离线几何审计：最小 ContinuousStructure 场景实测原语 ────────────────


def _extract(csx):
    from _geometry_audit_helpers import extract_primitives

    return extract_primitives(csx)


@pytest.fixture
def csx():
    from CSXCAD import ContinuousStructure

    return ContinuousStructure()


class TestOfflineGeometryAudit:
    def test_box_prim_bbox_matches_stl(self, csx, box_stl: Path):
        payload = classify_solid(parse_stl_file(box_stl), name="blk")
        prims = apply_solids(csx, [payload])
        assert len(prims) == 1
        found = _extract(csx)
        assert len(found) == 1
        prim = found[0]
        assert prim.kind == "Metal" and prim.prim_type == "1"
        assert np.max(np.abs(prim.lo - np.array(BOX_LO) / 1000.0)) <= 1e-9
        assert np.max(np.abs(prim.hi - np.array(BOX_HI) / 1000.0)) <= 1e-9

    def test_generated_lines_exec_route_matches_direct_apply(self, csx, box_stl: Path):
        """生成行经 exec 注入（render 脚本口径）与直接应用得到同一原语。"""
        payload = classify_solid(parse_stl_file(box_stl), name="blk")
        scope = {"CSX": csx}
        exec(compile("\n".join(csx_lines([payload])), "solid_import_lines", "exec"), scope)
        found = _extract(csx)
        assert len(found) == 1 and found[0].prim_type == "1"
        assert np.max(np.abs(found[0].lo - np.array(BOX_LO) / 1000.0)) <= 1e-9
        assert np.max(np.abs(found[0].hi - np.array(BOX_HI) / 1000.0)) <= 1e-9

    def test_cylinder_prim_axis_and_radius(self, csx):
        mesh = solid_mesh_from_triangles(_prism_triangles(64, 3.0, 0.0, 12.0, (5.0, -2.0)))
        payload = classify_solid(mesh, name="cyl")
        apply_solids(csx, [payload])
        found = _extract(csx)
        assert len(found) == 1 and found[0].prim_type == "5"
        assert found[0].radius == pytest.approx(0.003, abs=1e-9)
        # extract_primitives 把柱按半径外扩成等效盒：中心 (0.005,−0.002)，z 0..0.012
        assert np.max(np.abs(found[0].lo - np.array([0.002, -0.005, 0.0]))) <= 1e-9
        assert np.max(np.abs(found[0].hi - np.array([0.008, 0.001, 0.012]))) <= 1e-9

    def test_linpoly_prim_bbox_matches_stl(self, csx):
        mesh = solid_mesh_from_triangles(_prism_triangles(6, 4.0, 0.0, 6.0, (1.0, 2.0)))
        payload = classify_solid(mesh, name="hex")
        apply_solids(csx, [payload])
        found = _extract(csx)
        assert len(found) == 1 and found[0].prim_type == "8"
        lo, hi = mesh.bbox_mm
        assert np.max(np.abs(found[0].lo - lo / 1000.0)) <= 1e-9
        assert np.max(np.abs(found[0].hi - hi / 1000.0)) <= 1e-9

    def test_polyhedron_reader_prim_reads_file_and_scales(self, csx, box_stl: Path):
        """引擎路线实测：ReadFile 后顶点/面数与 bbox（文件原生 mm）对上；
        Scale 变换矩阵 diag=1e-3；IsInside 按变换后 m 坐标判定。"""
        mesh = solid_mesh_from_triangles(_tetra_triangles())
        payload = classify_solid(mesh, name="tet", stl_path=str(box_stl))
        prims = apply_solids(csx, [payload])
        prim = prims[0]
        assert str(prim.GetType()) == "14"
        assert prim.ReadFile() is True
        assert prim.GetNumVertices() == 8 and prim.GetNumFaces() == 12
        bb = np.asarray(prim.GetBoundBox(), dtype=float)
        assert np.max(np.abs(bb[0] - np.array(BOX_LO))) <= 1e-9   # 原生 mm，不随变换
        assert np.max(np.abs(bb[1] - np.array(BOX_HI))) <= 1e-9
        assert prim.HasTransform()
        mat = np.asarray(prim.GetTransform().GetMatrix(), dtype=float)
        assert mat.shape == (4, 4)
        assert np.allclose(np.diag(mat), [1e-3, 1e-3, 1e-3, 1.0], rtol=0, atol=1e-15)
        center_m = [(BOX_LO[k] + BOX_HI[k]) / 2000.0 for k in range(3)]
        assert prim.IsInside(center_m) is True
        assert prim.IsInside([c * 1000.0 for c in center_m]) is False  # mm 坐标已不在域内
        assert prim.IsInside([0.5, 0.5, 0.5]) is False
