"""LC-3 RF 保护结构套件单测（round15 §四 LC-3 验收锚）。

锚树（#212 离线审计精神：判据量在实测产物上，秒级零仿真）：
① 几何生成正确性——间距（arc-length=pitch）/连续性（孔全部落在折线上/
   跨段共享端点去重）/闭合性（护环首末闭合、周长/pitch 整除时零重复角孔）；
② 参数化扫描——pitch/尺寸扫描计数公式随动 + 同参确定性逐位相等；
③ 负例——退化几何/越界参数 fail-fast ValueError + bool 拒收（df7+⑯）；
④ 复验闭环（LC-3 验收原文）——生成 → return_path_check R1/R2 零违规
   自检（含 R1 跨窗/R2 超距/R2a 出平面负例与 d==h 边界容忍钉）；
⑤ PCell 注册表集成——guard_* 四内核/四单元入 KERNEL_REGISTRY/
   PCELL_LIBRARY，rfauto pcell list/show/eval/render 自动可达，渲染桥直产。
"""

from __future__ import annotations

import math
from itertools import pairwise
from pathlib import Path

import pytest

from rfauto.core.pcell_dsl import (
    KERNEL_REGISTRY,
    PCELL_LIBRARY,
    def_from_dict,
    def_to_dict,
    evaluate_pcell,
    get_pcell,
)
from rfauto.core.return_path_check import (
    FLAG_CODES,
    SplitRegion,
    TraceSpec,
    ViaSpec,
    point_in_polygon,
    point_polygon_boundary_distance,
    point_segment_closest,
)
from rfauto.core.rf_guard_structures import (
    GuardVia,
    cpw_ground_stitch,
    ground_void,
    guard_return_path_check,
    stitch_mesh,
    via_fence_polyline,
    via_fence_ring,
)

# ─── ① 任意折线 via fence：间距/连续性/闭合性 ────────────────────────────────


def test_fence_straight_line_exact_pitch_positions() -> None:
    vias = via_fence_polyline([(0.0, 0.0), (4.0, 0.0)], 1.0, 0.6, 0.3)
    assert len(vias) == 5
    assert [v.position for v in vias] == [
        (0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0), (4.0, 0.0)]
    assert all(v.pad_diameter_mm == 0.6 and v.drill_diameter_mm == 0.3
               for v in vias)
    assert all(isinstance(v, GuardVia) for v in vias)


def test_fence_l_polyline_all_vias_on_path_and_pitch_continuous() -> None:
    """连续性：每个孔到折线最近距离为 0；段内 arc 间距恰 = pitch。"""
    pts = [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0)]
    vias = via_fence_polyline(pts, 1.0, 0.6, 0.3)
    assert len(vias) == 8  # 底边 5 + 右边 s=1,2,3（角点去重）
    for v in vias:
        d_min = min(point_segment_closest(v.position, a, b)[0]
                    for a, b in pairwise(pts))
        assert d_min == pytest.approx(0.0, abs=1e-9)
    bottom = sorted(v.position[0] for v in vias if v.position[1] == 0.0)
    assert bottom == [0.0, 1.0, 2.0, 3.0, 4.0]
    right = sorted(v.position[1] for v in vias if v.position[0] == 4.0)
    assert right == [0.0, 1.0, 2.0, 3.0]  # 共享角点 (4,0) 只出现一次


def test_fence_offset_starts_and_truncates_at_end() -> None:
    vias = via_fence_polyline([(0.0, 0.0), (4.0, 0.0)], 1.0, 0.6, 0.3,
                              offset_mm=0.5)
    assert [v.position[0] for v in vias] == [0.5, 1.5, 2.5, 3.5]
    # offset 超过段长 → 零孔（不报错）
    assert via_fence_polyline([(0.0, 0.0), (4.0, 0.0)], 1.0, 0.6, 0.3,
                              offset_mm=5.0) == ()


def test_fence_ring_closure_count_equals_perimeter_over_pitch() -> None:
    """闭合性：w=10,h=6,pitch=1 周长 32 → 恰 32 孔，四角各只一孔。"""
    vias = via_fence_ring(10.0, 6.0, 1.0, 0.6, 0.3)
    assert len(vias) == 32
    assert vias[0].position == (0.0, 0.0)
    corners = [(0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)]
    for c in corners:
        hits = [v for v in vias
                if abs(v.position[0] - c[0]) < 1e-9
                and abs(v.position[1] - c[1]) < 1e-9]
        assert len(hits) == 1, c
    names = [v.name for v in vias]
    assert len(set(names)) == len(names)  # 命名唯一（确定性序）


def test_fence_determinism_bitwise() -> None:
    kw = dict(pitch_mm=0.8, pad_diameter_mm=0.6, drill_diameter_mm=0.3)
    a = via_fence_polyline([(0.0, 0.0), (3.0, 1.0), (6.0, 0.0)], **kw)
    b = via_fence_polyline([(0.0, 0.0), (3.0, 1.0), (6.0, 0.0)], **kw)
    assert a == b


# ─── ② 参数化扫描 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pitch,expect", [(0.5, 21), (1.0, 11), (2.0, 6),
                                          (2.5, 5)])
def test_fence_pitch_sweep_count_formula(pitch: float, expect: int) -> None:
    vias = via_fence_polyline([(0.0, 0.0), (10.0, 0.0)], pitch, 0.6, 0.3)
    assert len(vias) == expect  # floor(L/pitch)+1


@pytest.mark.parametrize("w,h,px,py,nx,ny", [
    (5.0, 2.5, 1.0, 1.0, 6, 3),
    (5.0, 2.5, 2.0, 0.5, 3, 6),
    (1.0, 1.0, 1.0, 1.0, 2, 2),
])
def test_mesh_dims_sweep(w: float, h: float, px: float, py: float,
                         nx: int, ny: int) -> None:
    mesh = stitch_mesh(w, h, px, py, 0.6, 0.3)
    assert (mesh.n_x, mesh.n_y) == (nx, ny)
    assert len(mesh.vias) == nx * ny


def test_cpw_strap_count_scales_with_length() -> None:
    for length, n_expect in ((20.0, 10), (10.0, 5), (4.0, 2)):
        st = cpw_ground_stitch(length, 0.8, 0.3, 2.0, 2.0, 0.6, 0.3)
        # n = floor((length-pad)/pitch)+1，每 strap 上下各一孔
        assert len(st.vias) == 2 * n_expect, length


# ─── CPW 共面地+缝合带几何 ────────────────────────────────────────────────────


def test_cpw_geometry_symmetry_and_pad_fit() -> None:
    st = cpw_ground_stitch(20.0, 0.8, 0.3, 2.0, 2.0, 0.6, 0.3, inset_mm=0.5)
    edge = 0.8 / 2.0 + 0.3
    assert st.gap_edge_offset_mm == pytest.approx(edge)
    assert st.ground_left == ((0.0, edge), (20.0, edge), (20.0, edge + 2.0),
                              (0.0, edge + 2.0))
    assert st.ground_right == ((0.0, -edge - 2.0), (20.0, -edge - 2.0),
                               (20.0, -edge), (0.0, -edge))
    assert st.center_trace == ((0.0, -0.4), (20.0, -0.4), (20.0, 0.4),
                               (0.0, 0.4))
    ys = sorted({round(v.position[1], 9) for v in st.vias})
    assert ys == [pytest.approx(-(edge + 0.5)), pytest.approx(edge + 0.5)]
    for v in st.vias:  # 焊盘完整落在地矩形内（含边界）且不越缝缘
        assert v.position[0] - 0.3 >= -1e-9
        assert v.position[0] + 0.3 <= 20.0 + 1e-9
        assert abs(v.position[1]) - edge - 0.5 == pytest.approx(0.0, abs=1e-9)


# ─── 缝合网格几何 ─────────────────────────────────────────────────────────────


def test_mesh_grid_positions_and_spacing() -> None:
    mesh = stitch_mesh(5.0, 2.0, 1.0, 1.0, 0.6, 0.3, x0_mm=10.0, y0_mm=-1.0)
    assert (mesh.n_x, mesh.n_y) == (6, 3)
    grid = {(round(v.position[0], 9), round(v.position[1], 9))
            for v in mesh.vias}
    assert grid == {(10.0 + i, -1.0 + j) for i in range(6) for j in range(3)}
    row0 = sorted(v.position[0] for v in mesh.vias
                  if v.position[1] == pytest.approx(-1.0))
    assert all(b - a == pytest.approx(1.0)
               for a, b in pairwise(row0))


# ─── 地板开窗：闭合性/护窗栅栏净距 ────────────────────────────────────────────


def test_void_polygon_closed_four_edges() -> None:
    void = ground_void(40.0, 30.0, 20.0, 15.0, 6.0, 4.0)
    poly = void.void_polygon
    assert len(poly) == 4
    assert poly[0] != poly[-1]  # 闭合不重复首点（边绕回口径）
    assert poly == ((17.0, 13.0), (23.0, 13.0), (23.0, 17.0), (17.0, 17.0))
    edges = [math.dist(poly[i], poly[(i + 1) % 4]) for i in range(4)]
    assert edges == [6.0, 4.0, 6.0, 4.0]


def test_void_fence_clearance_equals_offset() -> None:
    void = ground_void(40.0, 30.0, 20.0, 15.0, 6.0, 4.0,
                       fence_offset_mm=0.8, fence_pitch_mm=1.0)
    assert len(void.fence_vias) == 28  # 周长 26.4，四角不在整格 → 28 孔
    dists = [point_polygon_boundary_distance(v.position, void.void_polygon)
             for v in void.fence_vias]
    assert min(dists) == pytest.approx(0.8, abs=1e-9)
    assert all(d >= 0.8 - 1e-9 for d in dists)
    assert all(not point_in_polygon(v.position, void.void_polygon)
               for v in void.fence_vias)  # 栅栏孔全部在窗处平面金属上


def test_void_without_fence_and_zero_offset_rejected() -> None:
    void = ground_void(40.0, 30.0, 20.0, 15.0, 6.0, 4.0, fence_offset_mm=None)
    assert void.fence_vias == () and void.fence_path == ()
    assert void.fence_offset_mm is None
    with pytest.raises(ValueError, match="fence_offset_mm"):
        ground_void(40.0, 30.0, 20.0, 15.0, 6.0, 4.0, fence_offset_mm=0.0)


# ─── ③ 负例（fail-fast + bool 拒收） ─────────────────────────────────────────


@pytest.mark.parametrize("kw", [
    dict(pitch_mm=0.0), dict(pitch_mm=-1.0), dict(pitch_mm=True),
    dict(pitch_mm=1.0, pad_diameter_mm=0.3, drill_diameter_mm=0.3),
    dict(pitch_mm=1.0, pad_diameter_mm=0.2, drill_diameter_mm=0.3),
])
def test_fence_negative_params(kw: dict) -> None:
    with pytest.raises(ValueError):
        via_fence_polyline([(0.0, 0.0), (4.0, 0.0)],
                           kw.pop("pitch_mm"), kw.pop("pad_diameter_mm", 0.6),
                           kw.pop("drill_diameter_mm", 0.3), **kw)


@pytest.mark.parametrize("pts", [[(0.0, 0.0)], [], None])
def test_fence_degenerate_polyline_rejected(pts: object) -> None:
    with pytest.raises(ValueError):
        via_fence_polyline(pts, 1.0, 0.6, 0.3)  # type: ignore[arg-type]


@pytest.mark.parametrize("call", [
    lambda: via_fence_ring(0.0, 6.0, 1.0, 0.6, 0.3),
    lambda: via_fence_ring(10.0, -1.0, 1.0, 0.6, 0.3),
    lambda: stitch_mesh(0.0, 4.0, 1.0, 1.0, 0.6, 0.3),
    lambda: stitch_mesh(5.0, 4.0, 1.0, 0.0, 0.6, 0.3),
    lambda: stitch_mesh(5.0, 4.0, True, 1.0, 0.6, 0.3),
    lambda: cpw_ground_stitch(0.5, 0.8, 0.3, 2.0, 2.0, 0.6, 0.3),
    lambda: cpw_ground_stitch(20.0, 0.8, 0.3, 2.0, 2.0, 0.6, 0.3,
                              inset_mm=True),
    lambda: cpw_ground_stitch(20.0, 0.8, 0.3, 2.0, 2.0, 0.6, 0.3,
                              inset_mm=0.1),  # inset < pad/2 越缝缘
    lambda: cpw_ground_stitch(20.0, 0.8, 0.3, 2.0, 2.0, 0.6, 0.3,
                              inset_mm=1.9),  # inset+pad/2 > 地宽
    lambda: ground_void(40.0, 30.0, 20.0, 15.0, 40.0, 4.0),  # 贴边
    lambda: ground_void(40.0, 30.0, 20.0, 15.0, 6.0, 40.0),  # 越界
    lambda: ground_void(40.0, 30.0, 2.5, 15.0, 4.0, 4.0,
                        fence_offset_mm=1.5),  # 栅栏环越平面边
    lambda: ground_void(40.0, 30.0, 20.0, 15.0, 6.0, 4.0,
                        fence_offset_mm=-0.5),
    lambda: ground_void(True, 30.0, 20.0, 15.0, 6.0, 4.0),
])
def test_generator_negatives_fail_fast(call) -> None:
    with pytest.raises(ValueError):
        call()


# ─── ④ 统一复验闭环（LC-3 验收：生成 → R1/R2 零违规自检） ─────────────────────


def test_closed_loop_fence_protects_layer_via_zero_violation() -> None:
    """护墙闭环：换层孔距护墙 1.0 ≤ h=1.5 → R1/R2 零违规。"""
    fence = via_fence_ring(32.0, 6.0, 1.0, 0.6, 0.3, x0_mm=4.0, y0_mm=12.0)
    report = guard_return_path_check(
        plane=[(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)],
        traces=[TraceSpec("sig", 8.0, 15.0, 32.0, 15.0, 0.3)],
        stitch_vias=fence,
        layer_change_vias=[ViaSpec("lh", 20.0, 19.0)],  # 距护墙顶排恰 1.0
        via_return_distance_h_mm=1.5)
    assert report.ok
    assert report.issues == []


def test_closed_loop_void_trace_clear_and_via_stitched() -> None:
    """开窗闭环（验收主锚）：走线绕行开窗 + 换层孔贴护窗栅栏 → 零违规。"""
    void = ground_void(40.0, 30.0, 20.0, 15.0, 6.0, 4.0,
                       fence_offset_mm=0.8, fence_pitch_mm=1.0)
    report = guard_return_path_check(
        plane=void.plane_polygon,
        traces=[TraceSpec("sig", 3.0, 25.0, 37.0, 25.0, 0.5)],
        splits=[void.void_polygon],
        stitch_vias=void.fence_vias,
        layer_change_vias=[ViaSpec("lh", 20.0, 12.2)],
        via_return_distance_h_mm=1.0)
    assert report.ok
    assert report.issues == []


def test_closed_loop_boundary_d_equal_h_not_flag() -> None:
    """R2 边界口径钉：d == h 恰等不 flag（return_path_check 容忍口径）。"""
    void = ground_void(40.0, 30.0, 20.0, 15.0, 6.0, 4.0,
                       fence_offset_mm=0.8, fence_pitch_mm=1.0)
    report = guard_return_path_check(
        plane=void.plane_polygon,
        traces=[TraceSpec("sig", 3.0, 25.0, 37.0, 25.0, 0.5)],
        splits=[void.void_polygon],
        stitch_vias=void.fence_vias,
        layer_change_vias=[ViaSpec("lh", 16.2, 13.2)],  # 距角孔 (16.2,12.2) 恰 1.0
        via_return_distance_h_mm=1.0)
    assert report.ok
    assert report.issues == []


def test_closed_loop_negative_r1_trace_through_void() -> None:
    void = ground_void(40.0, 30.0, 20.0, 15.0, 6.0, 4.0)
    report = guard_return_path_check(
        plane=void.plane_polygon,
        traces=[TraceSpec("bad", 14.0, 15.0, 26.0, 15.0, 0.5)],
        splits=[void.void_polygon])
    assert not report.ok
    flags = [i for i in report.issues if i.code in FLAG_CODES]
    assert [i.code for i in flags] == ["TRACE_CROSS_SPLIT"]
    assert flags[0].related_id == "guard_split_0"


def test_closed_loop_negative_r2_via_far_and_r2a_outside_plane() -> None:
    fence = via_fence_ring(32.0, 6.0, 1.0, 0.6, 0.3, x0_mm=4.0, y0_mm=12.0)
    report = guard_return_path_check(
        plane=[(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)],
        traces=[TraceSpec("sig", 8.0, 15.0, 32.0, 15.0, 0.3)],
        stitch_vias=fence,
        layer_change_vias=[ViaSpec("lh_far", 20.0, 24.0),  # 距护墙 6 > h
                           ViaSpec("lh_out", 45.0, 15.0)],  # 平面外 → R2a
        via_return_distance_h_mm=1.5)
    assert not report.ok
    by_via = {i.element_id: i.code for i in report.issues
              if i.code in FLAG_CODES}
    assert by_via == {"lh_far": "VIA_STITCH_DISTANCE",
                      "lh_out": "VIA_OUTSIDE_PLANE"}


def test_closed_loop_missing_h_fail_fast_passthrough() -> None:
    fence = via_fence_ring(32.0, 6.0, 1.0, 0.6, 0.3, x0_mm=4.0, y0_mm=12.0)
    with pytest.raises(ValueError, match="via_return_distance_h_mm"):
        guard_return_path_check(
            plane=[(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)],
            traces=[TraceSpec("sig", 8.0, 15.0, 32.0, 15.0, 0.3)],
            stitch_vias=fence,
            layer_change_vias=[ViaSpec("lh", 20.0, 19.0)])


def test_closed_loop_accepts_splitregion_and_viaspec_inputs() -> None:
    """装配薄层双形态：SplitRegion/原始多边形、GuardVia/ViaSpec 同判。"""
    void = ground_void(40.0, 30.0, 20.0, 15.0, 6.0, 4.0)
    kwargs = dict(
        plane=void.plane_polygon,
        traces=[TraceSpec("sig", 3.0, 25.0, 37.0, 25.0, 0.5)],
        layer_change_vias=[ViaSpec("lh", 20.0, 12.2)],
        via_return_distance_h_mm=1.0)
    raw = guard_return_path_check(
        splits=[void.void_polygon],
        stitch_vias=[GuardVia("v1", (20.0, 12.2), 0.6, 0.3)], **kwargs)
    typed = guard_return_path_check(
        splits=[SplitRegion("s0", void.void_polygon)],
        stitch_vias=[ViaSpec("v1", 20.0, 12.2)], **kwargs)
    assert raw.verdict == typed.verdict == "PASS"
    assert raw.to_dict() == typed.to_dict()


# ─── ⑤ PCell 注册表集成（KERNEL_REGISTRY 生态，LC-2 协同） ───────────────────

GUARD_CELLS = ("guard_ring_fence", "cpw_ground_stitch", "stitch_mesh",
               "ground_void")


def test_guard_kernels_registered() -> None:
    assert set(GUARD_CELLS) <= set(KERNEL_REGISTRY)


def test_guard_cells_in_library_and_default_eval() -> None:
    assert set(GUARD_CELLS) <= set(PCELL_LIBRARY)
    assert len(PCELL_LIBRARY) == 14  # 3 迁移 + LC-2 七 + LC-3 四
    fence = evaluate_pcell(get_pcell("guard_ring_fence"), {})
    assert len(fence.vias) == 32  # 缺省 w10×h6 周长 32 / pitch 1 → 32
    assert fence.vias[0].position == pytest.approx((0.0, 0.0))
    cpw = evaluate_pcell(get_pcell("cpw_ground_stitch"), {})
    assert len(cpw.polygons) == 3 and len(cpw.vias) == 20
    mesh = evaluate_pcell(get_pcell("stitch_mesh"), {})
    assert len(mesh.vias) == 30  # 6×5
    void = evaluate_pcell(get_pcell("ground_void"), {})
    assert len(void.polygons) == 1 and len(void.vias) == 28


def test_guard_cells_param_override_and_fence_off() -> None:
    mesh = evaluate_pcell(get_pcell("stitch_mesh"),
                          {"width_mm": 2.0, "height_mm": 1.0,
                           "pitch_x_mm": 1.0, "pitch_y_mm": 1.0})
    assert len(mesh.vias) == 6  # 3×2
    void_off = evaluate_pcell(get_pcell("ground_void"),
                              {"fence_offset_mm": 0.0})
    assert len(void_off.polygons) == 1 and void_off.vias == ()
    with pytest.raises(ValueError, match="严格落在平面"):
        evaluate_pcell(get_pcell("ground_void"),
                       {"void_cx_mm": 1.0, "void_cy_mm": 15.0})


def test_guard_cells_dict_roundtrip_and_determinism() -> None:
    for name in GUARD_CELLS:
        defn = get_pcell(name)
        assert def_from_dict(def_to_dict(defn)) == defn, name
        sig_a = evaluate_pcell(defn, {}).signature()
        sig_b = evaluate_pcell(def_from_dict(def_to_dict(defn)), {}).signature()
        assert sig_a == sig_b, name


def test_guard_cells_primitive_kinds_cover_suite() -> None:
    kinds = {name: {row["kind"] for row in
                    evaluate_pcell(get_pcell(name), {}).to_dicts()}
             for name in GUARD_CELLS}
    assert kinds["guard_ring_fence"] == {"via"}
    assert kinds["cpw_ground_stitch"] == {"polygon", "via"}
    assert kinds["stitch_mesh"] == {"via"}
    assert kinds["ground_void"] == {"polygon", "via"}


def test_render_bridge_consumes_guard_cell(tmp_path: Path) -> None:
    """渲染桥直产 Layout（rfauto pcell render 消费链离线冒烟）。"""
    from rfauto.adapters.layout_interchange import export_layout
    from rfauto.cli.domains.scattered import _pcell_geometry_to_layout

    geo = evaluate_pcell(get_pcell("guard_ring_fence"), {})
    layout = _pcell_geometry_to_layout(geo)
    assert len(layout.items) == 32
    assert layout.layer_names() == ["F.Cu"]
    out = tmp_path / "guard.dxf"
    export_layout(layout, str(out), "dxf")
    assert out.exists() and out.stat().st_size > 0
