"""r4 HS-4：回流路径不连续几何检测器单测（core.return_path_check + service）。

判据口径（#122 先行、#118 双路径裁判）：
- 求交双路径：路径 A = 被测 polygons_intersect（边相交+顶点包含）；路径 B =
  本测试内第二实现（耳切三角化=凸分解 + 凸多边形分离轴 SAT + 三角形含点
  判定，独立算法族）——平移/旋转/尺寸参数化网格上布尔逐位一致；
- 恒等式：无分割平面→零违规逐位；走线完全在平面内→零违规；走线恰好横跨
  缝→恰 1 flag（R3 对同对不双报）；
- 距离恒等式：点到矩形最近距离手算网格对照（rel 1e-12）；缝合孔距离
  对称性 d(a,b)=d(b,a)（逐位）；
- 边界口径钉死：R3 严格 ``d < 3w``（恰等不警）；R2 严格 ``d > h``（恰等
  不 flag）；接触算相交；过孔贴平面边（含边界口径）不算 outside；
- 退化输入：<3 点/共线/零长边/零长或非正宽走线/NaN/bool → ValueError。
"""

from __future__ import annotations

import json
import math

import pytest

from rfauto.core.return_path_check import (
    RETURN_CURRENT_MODEL_FORMULA,
    RETURN_CURRENT_MODEL_NOTE,
    ReturnPathReport,
    SplitRegion,
    TraceSpec,
    ViaSpec,
    check_return_path,
    point_distance,
    point_in_polygon,
    point_polygon_boundary_distance,
    point_polygon_distance,
    polygons_distance,
    polygons_intersect,
    trace_rectangle,
)
from rfauto.service.return_path_check_service import (
    RETURN_PATH_CHECK_SCHEMA_VERSION,
    check_return_path_report,
)

# ─── 测试几何常量 ─────────────────────────────────────────────────────────────

#: L 形（非凸，带凹点）分割多边形——耳切三角化的非平凡输入
L_POLY = (
    (12.2, -3.3),
    (17.8, -3.3),
    (17.8, -0.4),
    (15.1, -0.4),
    (15.1, 2.6),
    (12.2, 2.6),
)
TRI = ((12.6, -4.2), (17.3, -2.1), (13.9, 1.8))
QUAD = ((20.4, -1.1), (23.2, 0.7), (21.4, 3.5), (18.6, 1.7))
SMALL_SQUARE = ((4.5, -0.2), (5.5, -0.2), (5.5, 0.4), (4.5, 0.4))

PLANE = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
#: 槽形分割：x∈[4,6] 全高缝（走线 (0,0)→(10,0) 必横跨）
SLOT = ((4.0, -3.0), (6.0, -3.0), (6.0, 3.0), (4.0, 3.0))


# ─── 双路径第二实现（测试内，独立算法族：耳切凸分解 + SAT + 三角含点） ────────


def _point_in_tri_incl(p, tri) -> bool:
    """点在三角形内（含边界；符号法）。"""
    (ax, ay), (bx, by), (cx, cy) = tri
    px, py = p
    d1 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    d2 = (cx - bx) * (py - by) - (cy - by) * (px - bx)
    d3 = (ax - cx) * (py - cy) - (ay - cy) * (px - cx)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _ear_clip(poly):
    """耳切三角化（简单多边形凸分解；测试第二实现用）。"""
    pts = [(float(x), float(y)) for x, y in poly]
    area = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        area += x0 * y1 - x1 * y0
    if area < 0:
        pts = pts[::-1]
    idx = list(range(len(pts)))
    tris = []
    while len(idx) > 3:
        n = len(idx)
        found = False
        for k in range(n):
            i0, i1, i2 = idx[(k - 1) % n], idx[k], idx[(k + 1) % n]
            a, b, c = pts[i0], pts[i1], pts[i2]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cross <= 0:
                continue
            bad = False
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                if _point_in_tri_incl(pts[j], (a, b, c)):
                    bad = True
                    break
            if bad:
                continue
            tris.append((a, b, c))
            idx.pop(k)
            found = True
            break
        if not found:
            raise AssertionError("ear clip 失败（非简单多边形？）")
    tris.append(tuple(pts[i] for i in idx))
    return tris


def _sat_intersect(pa, pb) -> bool:
    """凸多边形分离轴试验（凸-凸精确相交；接触算相交）。"""
    for poly in (pa, pb):
        n = len(poly)
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            ax, ay = y1 - y0, x0 - x1
            pa_proj = [ax * x + ay * y for x, y in pa]
            pb_proj = [ax * x + ay * y for x, y in pb]
            if max(pa_proj) < min(pb_proj) or max(pb_proj) < min(pa_proj):
                return False
    return True


def _rect_intersects_polygon_path_b(rect, poly) -> bool:
    """路径 B：矩形 ×（耳切三角化后的每个三角形）SAT 求交的并。"""
    return any(_sat_intersect(rect, list(tri)) for tri in _ear_clip(poly))


# ─── 1. 几何原语：手算锚 ──────────────────────────────────────────────────────


def test_trace_rectangle_axis_aligned_corners():
    corners = trace_rectangle((0.0, 0.0), (10.0, 0.0), 2.0)
    assert corners == ((0.0, 1.0), (10.0, 1.0), (10.0, -1.0), (0.0, -1.0))


def test_trace_rectangle_rotated_corners_and_area():
    ang = math.radians(45.0)
    p0 = (0.0, 0.0)
    p1 = (10.0 * math.cos(ang), 10.0 * math.sin(ang))
    corners = trace_rectangle(p0, p1, 2.0)
    nx, ny = -math.sin(ang), math.cos(ang)  # 独立推导：方向向量的垂直单位量 ×w/2=1
    expect = [
        (p0[0] + nx, p0[1] + ny),
        (p1[0] + nx, p1[1] + ny),
        (p1[0] - nx, p1[1] - ny),
        (p0[0] - nx, p0[1] - ny),
    ]
    for got, exp in zip(corners, expect, strict=True):
        assert got == pytest.approx(exp, rel=1e-12, abs=1e-12)
    # 面积恒等：|shoelace| = L·w = 20
    area = 0.0
    for i in range(4):
        x0, y0 = corners[i]
        x1, y1 = corners[(i + 1) % 4]
        area += x0 * y1 - x1 * y0
    assert abs(0.5 * area) == pytest.approx(20.0, rel=1e-12)


def test_point_polygon_distance_hand_grid():
    poly = ((0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0))
    for px in range(-2, 7):
        for py in range(-2, 6):
            dx = max(-px, px - 4, 0)
            dy = max(-py, py - 3, 0)
            region_exp = math.hypot(dx, dy)
            assert point_polygon_distance((float(px), float(py)), poly) == pytest.approx(
                region_exp, rel=1e-12, abs=1e-12
            )
            b_exp = (
                float(min(px, 4 - px, py, 3 - py)) if region_exp == 0.0 else region_exp
            )
            assert point_polygon_boundary_distance(
                (float(px), float(py)), poly
            ) == pytest.approx(b_exp, rel=1e-12, abs=1e-12)


def test_point_in_polygon_dual_path_sampling():
    tris = _ear_clip(L_POLY)
    assert len(tris) == len(L_POLY) - 2  # 三角化恒等式：n 顶点 → n−2 个三角形
    n_checked = 0
    px = 11.0
    while px <= 19.0:
        py = -4.0
        while py <= 3.5:
            p = (px, py)
            # 跳过近边界带（两实现对边界点的归属本就允许不同约定）
            if point_polygon_boundary_distance(p, L_POLY) > 1e-6:
                in_a = point_in_polygon(p, L_POLY)
                in_b = any(_point_in_tri_incl(p, tri) for tri in tris)
                assert in_a == in_b, f"双路径分歧 @ {p}"
                n_checked += 1
            py += 0.41
        px += 0.37
    assert n_checked > 200


def test_polygons_intersect_hand_cases():
    sq_a = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
    crossing = ((1.0, -1.0), (3.0, -1.0), (3.0, 1.0), (1.0, 1.0))
    edge_touch = ((2.0, 0.5), (4.0, 0.5), (4.0, 1.5), (2.0, 1.5))
    corner_touch = ((2.0, 2.0), (3.0, 2.0), (3.0, 3.0), (2.0, 3.0))
    disjoint = ((5.0, 5.0), (6.0, 5.0), (6.0, 6.0), (5.0, 6.0))
    contained = ((0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5))
    assert polygons_intersect(sq_a, crossing) is True
    assert polygons_intersect(sq_a, edge_touch) is True  # 接触算相交（口径钉）
    assert polygons_intersect(sq_a, corner_touch) is True
    assert polygons_intersect(sq_a, disjoint) is False
    assert polygons_intersect(sq_a, contained) is True  # 纯包含（无边交）
    assert polygons_intersect(contained, sq_a) is True


def test_dual_path_intersection_parameterized_sweep():
    shapes = (TRI, QUAD, L_POLY, SMALL_SQUARE)
    dxs = (-20.0, -13.7, -6.3, -0.9, 3.1, 7.7, 12.3, 18.1)
    dys = (-2.2, 0.0, 0.8, 3.4)
    angles = (0.0, 17.0)
    widths = (1.0, 2.0)
    n_cases = 0
    for w in widths:
        for ang_deg in angles:
            ang = math.radians(ang_deg)
            p1 = (10.0 * math.cos(ang), 10.0 * math.sin(ang))
            rect = trace_rectangle((0.0, 0.0), p1, w)
            for shape in shapes:
                for dx in dxs:
                    for dy in dys:
                        moved = tuple((x + dx, y + dy) for x, y in shape)
                        path_a = polygons_intersect(rect, moved)
                        path_b = _rect_intersects_polygon_path_b(rect, moved)
                        assert path_a == path_b, (
                            f"双路径分歧 w={w} ang={ang_deg} shape dx={dx} dy={dy}: "
                            f"A={path_a} B={path_b}"
                        )
                        n_cases += 1
    assert n_cases >= 400


def test_polygons_distance_symmetry_hand():
    sq_a = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
    sq_b = ((3.0, 3.0), (5.0, 3.0), (5.0, 5.0), (3.0, 5.0))
    d_ab = polygons_distance(sq_a, sq_b)
    d_ba = polygons_distance(sq_b, sq_a)
    assert d_ab == d_ba  # 对称性：逐位
    assert d_ab == pytest.approx(math.hypot(1.0, 1.0), rel=1e-12)  # 手算 (2,2)-(3,3)
    # 点-点距离原语对称性
    assert point_distance((1.0, 2.0), (4.0, 6.0)) == point_distance((4.0, 6.0), (1.0, 2.0))
    assert point_distance((1.0, 2.0), (4.0, 6.0)) == 5.0


# ─── 2. 恒等式与规则族 ────────────────────────────────────────────────────────


def test_no_splits_zero_violations_identity():
    report = check_return_path(
        traces=[TraceSpec("t1", 0.0, 5.0, 6.0, 5.0, 1.0)], plane=PLANE
    )
    assert report.issues == []
    assert report.verdict == "PASS"
    assert report.ok is True
    assert report.counts["total"] == 0
    for code in ("TRACE_CROSS_SPLIT", "VIA_STITCH_DISTANCE", "TRACE_EDGE_MARGIN"):
        assert report.counts[code] == 0


def test_trace_fully_inside_plane_zero_violations():
    far_split = ((20.0, 20.0), (22.0, 20.0), (22.0, 22.0), (20.0, 22.0))
    report = check_return_path(
        traces=[TraceSpec("t1", 1.0, 5.0, 8.0, 5.0, 1.0)],
        splits=[SplitRegion("far", far_split)],
        plane=PLANE,
    )
    assert report.issues == []
    assert report.verdict == "PASS"


def test_trace_exactly_crossing_seam_single_flag():
    report = check_return_path(
        traces=[TraceSpec("t1", 0.0, 0.0, 10.0, 0.0, 2.0)],
        splits=[SplitRegion("slot", SLOT)],
        plane=PLANE,
    )
    assert len(report.issues) == 1  # 恰 1 flag（R1 优先，同对不双报 R3）
    issue = report.issues[0]
    assert issue.code == "TRACE_CROSS_SPLIT"
    assert issue.severity == "flag"
    assert issue.rule == "R1"
    assert issue.element_id == "t1"
    assert issue.related_id == "slot"
    assert issue.position == (6.0, 1.0)  # 首条真交边对交点（逐位）
    assert report.verdict == "FAIL"
    assert report.ok is False
    assert report.counts["flag"] == 1


def test_trace_crossing_two_splits_two_flags():
    slot2 = ((8.0, -3.0), (9.5, -3.0), (9.5, 3.0), (8.0, 3.0))
    report = check_return_path(
        traces=[TraceSpec("t1", 0.0, 0.0, 10.0, 0.0, 2.0)],
        splits=[SplitRegion("slot_a", SLOT), SplitRegion("slot_b", slot2)],
        plane=PLANE,
    )
    assert report.counts["TRACE_CROSS_SPLIT"] == 2
    assert {i.related_id for i in report.issues} == {"slot_a", "slot_b"}


def test_3w_warning_below_margin():
    # 走线带宽 y∈[-0.5,0.5]，槽下缘 y=3.4 → d=2.9 < 3w=3.0 → warning
    strip = ((0.0, 3.4), (10.0, 3.4), (10.0, 3.6), (0.0, 3.6))
    report = check_return_path(
        traces=[TraceSpec("t1", 0.0, 0.0, 10.0, 0.0, 1.0)],
        splits=[SplitRegion("strip", strip)],
        plane=PLANE,
    )
    assert report.counts["TRACE_EDGE_MARGIN"] == 1
    issue = report.issues[0]
    assert issue.code == "TRACE_EDGE_MARGIN"
    assert issue.severity == "warning"
    assert issue.rule == "R3"
    assert issue.value_mm == pytest.approx(2.9, rel=1e-12)
    assert issue.limit_mm == pytest.approx(3.0, rel=1e-12)
    assert issue.position == pytest.approx((0.0, 3.4), rel=1e-12)


def test_3w_boundary_exact_pass_strict_lt():
    # 恰等口径钉死：d == 3w（3.0）不警（严格 <）
    strip = ((0.0, 3.5), (10.0, 3.5), (10.0, 3.7), (0.0, 3.7))
    report = check_return_path(
        traces=[TraceSpec("t1", 0.0, 0.0, 10.0, 0.0, 1.0)],
        splits=[SplitRegion("strip", strip)],
        plane=PLANE,
    )
    assert report.issues == []
    assert report.verdict == "PASS"


def test_3w_epsilon_below_warns():
    strip = ((0.0, 3.5 - 1e-9), (10.0, 3.5 - 1e-9), (10.0, 3.7), (0.0, 3.7))
    report = check_return_path(
        traces=[TraceSpec("t1", 0.0, 0.0, 10.0, 0.0, 1.0)],
        splits=[SplitRegion("strip", strip)],
        plane=PLANE,
    )
    assert report.counts["TRACE_EDGE_MARGIN"] == 1


def test_warning_does_not_fail_verdict():
    strip = ((0.0, 2.0), (10.0, 2.0), (10.0, 2.2), (0.0, 2.2))  # d=1.5 < 3 → warning
    report = check_return_path(
        traces=[TraceSpec("t1", 0.0, 0.0, 10.0, 0.0, 1.0)],
        splits=[SplitRegion("strip", strip)],
        plane=PLANE,
    )
    assert report.counts["warning"] == 1
    assert report.counts["flag"] == 0
    assert report.verdict == "PASS"  # warning 不改 flag 级 verdict
    assert report.ok is True


# ─── 3. R2：换层过孔-缝合孔距离 ───────────────────────────────────────────────


def test_via_stitch_distance_flag_and_exact_boundary_pass():
    via = ViaSpec("v1", 5.0, 5.0)
    stitch = ViaSpec("s1", 8.0, 9.0)  # d = hypot(3,4) = 5.0 手算
    base = dict(
        traces=[TraceSpec("t1", 1.0, 5.0, 4.0, 5.0, 1.0)],
        plane=PLANE,
        layer_change_vias=[via],
    )
    # 恰等 d == h → 不 flag（严格 > 口径钉死）
    report_eq = check_return_path(**base, stitch_vias=[stitch], via_return_distance_h_mm=5.0)
    assert report_eq.issues == []
    assert report_eq.verdict == "PASS"
    # d > h → flag
    report_flag = check_return_path(**base, stitch_vias=[stitch], via_return_distance_h_mm=4.999)
    assert report_flag.counts["VIA_STITCH_DISTANCE"] == 1
    issue = report_flag.issues[0]
    assert issue.value_mm == pytest.approx(5.0, rel=1e-12)
    assert issue.limit_mm == pytest.approx(4.999, rel=1e-12)
    assert issue.related_id == "s1"
    assert issue.element_id == "v1"
    # 最近缝合孔选择：两个缝合孔取最近
    near = ViaSpec("near", 5.0, 9.0)  # d = 4.0
    report2 = check_return_path(
        **base, stitch_vias=[stitch, near], via_return_distance_h_mm=3.9
    )
    issue2 = report2.issues[0]
    assert issue2.value_mm == pytest.approx(4.0, rel=1e-12)
    assert issue2.related_id == "near"


def test_via_stitch_distance_symmetry():
    # 几何原语级：d(a,b)=d(b,a) 逐位
    assert point_distance((5.0, 5.0), (8.0, 9.0)) == point_distance((8.0, 9.0), (5.0, 5.0))
    # 报告级：过孔/缝合孔角色互换，flag value 逐位相等。
    # 大平面（30mm）保证 d_edge ≥ 8 恒大于缝合孔距离 5——d 取缝合孔通道，
    # 排除平面边缘通道干扰对称性对照。
    big_plane = ((0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0))
    trace = [TraceSpec("t", 1.0, 1.0, 2.0, 1.0, 1.0)]
    rep_a = check_return_path(
        traces=trace,
        plane=big_plane,
        layer_change_vias=[ViaSpec("v", 5.0, 5.0)],
        stitch_vias=[ViaSpec("s", 8.0, 9.0)],
        via_return_distance_h_mm=1.0,
    )
    rep_b = check_return_path(
        traces=trace,
        plane=big_plane,
        layer_change_vias=[ViaSpec("s", 8.0, 9.0)],
        stitch_vias=[ViaSpec("v", 5.0, 5.0)],
        via_return_distance_h_mm=1.0,
    )
    va = next(i.value_mm for i in rep_a.issues if i.code == "VIA_STITCH_DISTANCE")
    vb = next(i.value_mm for i in rep_b.issues if i.code == "VIA_STITCH_DISTANCE")
    assert va == vb


def test_via_outside_plane_flag():
    report = check_return_path(
        traces=[TraceSpec("t", 1.0, 1.0, 2.0, 1.0, 1.0)],
        plane=PLANE,
        layer_change_vias=[ViaSpec("v_out", 15.0, 5.0)],
        stitch_vias=[ViaSpec("s", 6.0, 5.0)],
        via_return_distance_h_mm=10.0,
    )
    assert report.counts["VIA_OUTSIDE_PLANE"] == 1
    issue = report.issues[0]
    assert issue.code == "VIA_OUTSIDE_PLANE"
    assert issue.severity == "flag"
    assert issue.element_id == "v_out"
    assert report.verdict == "FAIL"


def test_via_on_plane_edge_inclusive_no_flag():
    # 过孔恰在平面下边缘 (5,0)：含边界口径 → 不算 outside；d_edge=0 → 不 flag
    report = check_return_path(
        traces=[TraceSpec("t", 1.0, 1.0, 2.0, 1.0, 1.0)],
        plane=PLANE,
        layer_change_vias=[ViaSpec("v_edge", 5.0, 0.0)],
        via_return_distance_h_mm=2.0,
    )
    assert report.issues == []
    assert report.verdict == "PASS"


def test_via_without_h_raises():
    with pytest.raises(ValueError, match="via_return_distance_h_mm"):
        check_return_path(
            traces=[TraceSpec("t", 1.0, 1.0, 2.0, 1.0, 1.0)],
            plane=PLANE,
            layer_change_vias=[ViaSpec("v", 5.0, 5.0)],
        )


def test_via_without_reference_geometry_raises():
    with pytest.raises(ValueError, match="无从评估"):
        check_return_path(
            traces=[TraceSpec("t", 1.0, 1.0, 2.0, 1.0, 1.0)],
            layer_change_vias=[ViaSpec("v", 5.0, 5.0)],
            via_return_distance_h_mm=2.0,
        )


# ─── 4. 退化输入守卫 ──────────────────────────────────────────────────────────


def test_degenerate_polygon_valueerror():
    with pytest.raises(ValueError, match="退化多边形"):
        SplitRegion("bad2", [(0.0, 0.0), (1.0, 1.0)])  # <3 点
    with pytest.raises(ValueError, match="退化多边形"):
        SplitRegion("collinear", [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)])  # 共线
    with pytest.raises(ValueError, match="退化多边形"):
        SplitRegion("dup", [(0.0, 0.0), (2.0, 0.0), (2.0, 0.0), (0.0, 2.0)])  # 零长边
    with pytest.raises(ValueError, match="plane"):
        check_return_path(traces=[], plane=[(0.0, 0.0), (1.0, 1.0)])  # 平面同守卫


def test_degenerate_trace_raises():
    with pytest.raises(ValueError):
        TraceSpec("w0", 0.0, 0.0, 1.0, 0.0, 0.0)  # 零宽
    with pytest.raises(ValueError):
        TraceSpec("wneg", 0.0, 0.0, 1.0, 0.0, -1.0)  # 负宽
    with pytest.raises(ValueError, match="零长度"):
        TraceSpec("t0", 0.0, 0.0, 0.0, 0.0, 1.0).polygon()  # 零长度段


def test_nan_and_bool_inputs_raise():
    with pytest.raises(ValueError):
        SplitRegion("nan", [(0.0, 0.0), (float("nan"), 0.0), (1.0, 1.0)])
    with pytest.raises(ValueError):
        ViaSpec("v", True, 1.0)  # bool 显式拒收
    with pytest.raises(ValueError):
        TraceSpec("t", 0.0, 0.0, 1.0, 0.0, True)
    with pytest.raises(ValueError):
        check_return_path(
            traces=[TraceSpec("t", 1.0, 1.0, 2.0, 1.0, 1.0)],
            plane=PLANE,
            layer_change_vias=[ViaSpec("v", 5.0, 5.0)],
            via_return_distance_h_mm=True,  # bool 拒收
        )
    with pytest.raises(ValueError):
        check_return_path(traces=[], edge_margin_widths=0.0)


# ─── 5. 报告面与 J(d) 文档化（NO-GO 边界） ────────────────────────────────────


def test_j_model_documentation_only():
    report = check_return_path(traces=[TraceSpec("t", 0.0, 0.0, 1.0, 0.0, 1.0)])
    assert set(report.j_model.keys()) == {"formula", "note", "quantitative"}
    assert report.j_model["formula"] == RETURN_CURRENT_MODEL_FORMULA
    assert "J(d)" in report.j_model["formula"]
    assert "(d/h)" in report.j_model["formula"]
    assert report.j_model["quantitative"] is False
    assert report.j_model["note"] == RETURN_CURRENT_MODEL_NOTE
    assert "NO-GO" in report.j_model["note"]
    d = report.to_dict()
    assert "current_density" not in d and "j_density" not in d  # 无量化数字字段


def test_report_to_dict_json_roundtrip_counts():
    report = check_return_path(
        traces=[TraceSpec("t1", 0.0, 0.0, 10.0, 0.0, 2.0)],
        splits=[SplitRegion("slot", SLOT)],
        plane=PLANE,
        layer_change_vias=[ViaSpec("v", 5.0, 5.0)],
        stitch_vias=[ViaSpec("s", 8.0, 9.0)],
        via_return_distance_h_mm=1.0,
    )
    d = report.to_dict()
    json.dumps(d)  # JSON 可序列化
    assert d["verdict"] == "FAIL" and d["ok"] is False
    assert isinstance(report, ReturnPathReport)
    assert d["counts"]["total"] == len(d["issues"])
    assert d["counts"]["flag"] + d["counts"]["warning"] == d["counts"]["total"]
    per_code = sum(d["counts"][c] for c in ("TRACE_CROSS_SPLIT", "VIA_STITCH_DISTANCE",
                                            "VIA_OUTSIDE_PLANE", "TRACE_EDGE_MARGIN"))
    assert per_code == d["counts"]["total"]
    for issue in d["issues"]:
        assert {"code", "severity", "rule", "element_id", "detail"} <= set(issue.keys())
    # PASS 路径 roundtrip
    ok_report = check_return_path(traces=[])
    assert ok_report.to_dict()["ok"] is True


def test_empty_input_trivial_pass():
    report = check_return_path(traces=[])
    assert report.verdict == "PASS"
    assert report.ok is True
    assert report.counts["total"] == 0
    assert report.checked["n_traces"] == 0
    assert report.checked["units"] == "mm"
    assert report.checked["via_return_distance_h_mm"] is None  # 判缺失 is not None 口径


# ─── 6. service 薄壳（JSON 信封） ─────────────────────────────────────────────


def test_service_envelope_ok_and_fail_paths():
    payload = {
        "traces": [
            {"trace_id": "t1", "x0": 0, "y0": 0, "x1": 10, "y1": 0, "width_mm": 2}
        ],
        "splits": [{"split_id": "slot", "polygon": [[4, -3], [6, -3], [6, 3], [4, 3]]}],
        "plane": [[0, 0], [20, 0], [20, 20], [0, 20]],
        "layer_change_vias": [{"via_id": "v1", "x": 5, "y": 5}],
        "stitch_vias": [{"via_id": "s1", "x": 8, "y": 9}],
        "via_return_distance_h_mm": 1.0,
    }
    res = check_return_path_report(payload)
    assert res["ok"] is True  # 执行成功（判 FAIL ≠ ok=False）
    assert res["schema_version"] == RETURN_PATH_CHECK_SCHEMA_VERSION
    assert res["verdict"] == "FAIL"
    codes = {i["code"] for i in res["report"]["issues"]}
    assert {"TRACE_CROSS_SPLIT", "VIA_STITCH_DISTANCE"} <= codes
    json.dumps(res)
    # PASS 路径
    payload_pass = dict(payload, via_return_distance_h_mm=50.0, splits=[])
    res_pass = check_return_path_report(payload_pass)
    assert res_pass["ok"] is True
    assert res_pass["verdict"] == "PASS"
    assert res_pass["report"]["j_model"]["quantitative"] is False  # NO-GO 面透传


def test_service_never_raises_ok_false():
    bad_payloads = (
        "not a dict",
        {"traces": "x"},
        {"traces": [{"trace_id": "t", "x0": "abc", "y0": 0, "x1": 1, "y1": 0,
                     "width_mm": 1}]},
        {"traces": [], "splits": [{"split_id": "s", "polygon": [[0, 0], [1, 1]]}]},
        {"traces": [], "layer_change_vias": [{"via_id": "v", "x": 1, "y": 1}]},
        {"traces": [], "via_return_distance_h_mm": -1.0},
    )
    for payload in bad_payloads:
        res = check_return_path_report(payload)
        assert res["ok"] is False
        assert isinstance(res.get("errors"), list) and res["errors"]
