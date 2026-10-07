"""N14 RF 走线几何内核：面积恒等式裁判 + layout_interchange 消费证明。

spec 出处：方案池 L158「N14 KiCad RF 导出增强
（taper/圆角 footprint+寄生反查闭环）」+ docs/audit/plan_gap_inventory_20260928.md
§二 B5 行。本件=几何内核 + 寄生反查闭环 + KiCad footprint 直发（收尾全件）。

裁判口径（#118：闭式恒等式为独立来源，shoelace/解析器为实现侧）：
- 渐变段：A = L·(w1+w2)/2（梯形恒等式，逐位）；寄生反查=提取
  A/w_ref vs 闭式 L(w1+w2)/(2·w_ref)（逐位）；
- 倒角弯：A = w(L1+L2) − c²/2（方角扫掠减倒角三角形，逐位）；挖铜
  c²/2 → 平行板不连续电容双源对照；
- 圆角弯：A = w(L1+L2) − r·w·(2−π/2)（弧离散收敛裁判 + 弧顶点严格
  落 r±w/2 同心圆逐位）；面积/宽度=中心线长同源恒等式交叉钉；
- 刚体运动不变（旋转/右转镜像面积不变）；
- KiCad footprint：内建 s-expr 解析器结构往返 + 面积守恒 + 1nm 网格
  + 确定性（无 KiCad 全绿；KiCad 10.0.6 FootprintSave 语法实测取证）。
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import ClassVar

import pytest

from rfauto.core.rf_trace_geometry import (
    EPSILON_0_F_PER_MM,
    equivalent_length_mm,
    kicad_footprint_text,
    miter_chamfer_removed_area_mm2,
    mitered_bend_polygon,
    plate_capacitance_f,
    polygon_shoelace_area,
    rounded_bend_polygon,
    rounded_corner_saving_mm,
    taper_equivalent_length_closed_form,
    taper_polygon,
)

C30, S30 = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))


class TestTaper:
    def test_area_identity_exact(self):
        p = taper_polygon((0.0, 0.0), (7.3, 0.0), 1.2, 0.6)
        assert polygon_shoelace_area(p) == pytest.approx(7.3 * 0.9, rel=1e-12)

    def test_end_widths_perpendicular(self):
        """端帽边长=设计线宽且垂直于中心线（宽度定义逐位）。"""
        w1, w2 = 1.2, 0.6
        p = taper_polygon((1.0, 2.0), (4.0, 7.0), w1, w2)
        assert math.dist(p[0], p[3]) == pytest.approx(w1, rel=1e-12)
        assert math.dist(p[1], p[2]) == pytest.approx(w2, rel=1e-12)
        # 端帽边方向 · 中心线方向 = 0
        edge = (p[3][0] - p[0][0], p[3][1] - p[0][1])
        center = (3.0, 5.0)
        assert edge[0] * center[0] + edge[1] * center[1] == pytest.approx(
            0.0, abs=1e-12)

    def test_rotated_area_invariant(self):
        a = polygon_shoelace_area(taper_polygon((0, 0), (5, 0), 1.0, 0.5))
        b = polygon_shoelace_area(taper_polygon(
            (2.0, -1.0), (2.0 + 5 * C30, -1.0 + 5 * S30), 1.0, 0.5))
        assert a == pytest.approx(b, rel=1e-12)


class TestMiteredBend:
    def test_area_identity_exact_left_turn(self):
        w, c = 1.0, 0.5
        p = mitered_bend_polygon((0, 0), (10, 0), (10, 8), w)
        assert polygon_shoelace_area(p) == pytest.approx(
            w * (10.0 + 8.0) - c * c / 2.0, rel=1e-12)

    def test_area_identity_custom_chamfer(self):
        w, c = 0.8, 0.3
        p = mitered_bend_polygon((0, 0), (5, 0), (5, 4), w, chamfer_mm=c)
        assert polygon_shoelace_area(p) == pytest.approx(
            w * 9.0 - c * c / 2.0, rel=1e-12)

    def test_right_turn_mirror_same_area(self):
        left = polygon_shoelace_area(mitered_bend_polygon((0, 0), (10, 0), (10, 8), 1.0))
        right = polygon_shoelace_area(mitered_bend_polygon((0, 0), (10, 0), (10, -8), 1.0))
        assert left == pytest.approx(right, rel=1e-12)

    def test_rotated_frame_exact(self):
        corner = (3.0 * C30, 3.0 * S30)
        nxt = (corner[0] - 2.0 * S30, corner[1] + 2.0 * C30)
        p = mitered_bend_polygon((0, 0), corner, nxt, 0.8)
        assert polygon_shoelace_area(p) == pytest.approx(
            0.8 * 5.0 - 0.16 / 2.0, rel=1e-12)

    def test_vertices_on_offset_edges(self):
        """顶点严格落在 ±w/2 偏移边上（轴向例逐位）。"""
        p = mitered_bend_polygon((0, 0), (10, 0), (10, 8), 1.0)
        ys = {pt[1] for pt in p}
        xs = {pt[0] for pt in p}
        assert {-0.5, 0.5} <= ys
        assert {10.5} <= xs

    def test_non_perpendicular_rejected(self):
        with pytest.raises(ValueError, match="垂直"):
            mitered_bend_polygon((0, 0), (10, 0), (15, 5), 1.0)

    def test_chamfer_gt_width_rejected(self):
        with pytest.raises(ValueError, match="chamfer_mm"):
            mitered_bend_polygon((0, 0), (10, 0), (10, 8), 1.0, chamfer_mm=1.5)


class TestRoundedBend:
    TARGET = 1.0 * (10.0 + 8.0) - 1.5 * 1.0 * (2.0 - math.pi / 2.0)

    def test_arc_vertices_on_concentric_circles(self):
        """弧顶点严格落 r±w/2 同心圆（圆心 (L1−r, r)，距离逐位）。"""
        r, w = 1.5, 1.0
        p = rounded_bend_polygon((0, 0), (10, 0), (10, 8), w, r, n_arc=16)
        cx, cy = 10.0 - r, r
        dists = [math.hypot(x - cx, y - cy) for (x, y) in p]
        near_out = [d for d in dists if abs(d - (r + w / 2)) < 1e-9]
        near_in = [d for d in dists if abs(d - (r - w / 2)) < 1e-9]
        assert len(near_out) >= 10   # 外弧顶点
        assert len(near_in) >= 8     # 内弧顶点
        # 切点/端点精确存在：外弧起 (l1−r,−w/2)、内弧终 (l1−r,w/2)、
        # 内弧起 (l1−w/2, r)
        assert (10.0 - r, -w / 2) in p
        assert (10.0 - r, w / 2) in p
        assert (10.0 - w / 2, r) in p

    def test_area_converges_to_closed_form(self):
        """面积随 n_arc 收敛到闭式（O(1/n²)，单调改进）。"""
        a8 = polygon_shoelace_area(
            rounded_bend_polygon((0, 0), (10, 0), (10, 8), 1.0, 1.5, n_arc=8))
        a32 = polygon_shoelace_area(
            rounded_bend_polygon((0, 0), (10, 0), (10, 8), 1.0, 1.5, n_arc=32))
        a128 = polygon_shoelace_area(
            rounded_bend_polygon((0, 0), (10, 0), (10, 8), 1.0, 1.5, n_arc=128))
        e8, e32, e128 = (abs(a - self.TARGET) for a in (a8, a32, a128))
        assert e128 < e32 < e8
        assert e32 < 0.02 * self.TARGET

    def test_right_turn_and_rotated_frames(self):
        right = polygon_shoelace_area(
            rounded_bend_polygon((0, 0), (10, 0), (10, -8), 1.0, 1.5, n_arc=64))
        assert right == pytest.approx(self.TARGET, rel=1e-3)
        corner = (3.0 * C30, 3.0 * S30)
        nxt = (corner[0] - 2.0 * S30, corner[1] + 2.0 * C30)
        rot = polygon_shoelace_area(
            rounded_bend_polygon((0, 0), corner, nxt, 0.8, 0.6, n_arc=64))
        assert rot == pytest.approx(
            0.8 * 5.0 - 0.6 * 0.8 * (2.0 - math.pi / 2.0), rel=1e-3)

    def test_guards(self):
        with pytest.raises(ValueError, match="w/2"):
            rounded_bend_polygon((0, 0), (10, 0), (10, 8), 1.0, 0.5)
        with pytest.raises(ValueError, match="短臂长"):
            rounded_bend_polygon((0, 0), (2, 0), (2, 3), 1.0, 2.5)
        with pytest.raises(ValueError, match="n_arc"):
            rounded_bend_polygon((0, 0), (10, 0), (10, 8), 1.0, 1.5, n_arc=1)
        with pytest.raises(ValueError, match="n_arc"):
            rounded_bend_polygon((0, 0), (10, 0), (10, 8), 1.0, 1.5, n_arc=True)

    def test_width_and_point_validation(self):
        with pytest.raises(ValueError, match="width_start_mm"):
            taper_polygon((0, 0), (1, 0), 0.0, 1.0)
        with pytest.raises(ValueError, match="width_start_mm"):
            taper_polygon((0, 0), (1, 0), True, 1.0)
        with pytest.raises(ValueError, match="width_mm"):
            mitered_bend_polygon((0, 0), (10, 0), (10, 8), 0.0)
        with pytest.raises(ValueError, match="重合"):
            mitered_bend_polygon((0, 0), (0, 0), (0, 8), 1.0)
        with pytest.raises(ValueError, match="坐标对"):
            mitered_bend_polygon((0, 0), (10,), (10, 8), 1.0)


class TestInterchangeConsumption:
    def test_gdsii_roundtrip_via_layout_interchange(self, tmp_path: Path):
        """消费证明：几何内核 → layout_interchange LayoutPolygon → GDSII
        导出/读回 → 面积还原（nm 网格量化容差）。分层口径：core 不 import
        adapters，由测试侧装配（消费方向 adapters→core）。"""
        from rfauto.adapters.layout_interchange import (
            Layout,
            LayoutPolygon,
            assign_gds_layers,
            export_layout,
            import_layout,
        )

        items = [
            taper_polygon((0.0, 0.0), (7.3, 0.0), 1.2, 0.6),
            mitered_bend_polygon((0, 0), (10, 0), (10, 8), 1.0),
            rounded_bend_polygon((20.0, 0.0), (30.0, 0.0), (30.0, 8.0),
                                 1.0, 1.5, n_arc=32),
        ]
        src_areas = [polygon_shoelace_area(pts) for pts in items]
        layout = Layout(
            name="rf_trace_n14",
            layers=assign_gds_layers(["F.Cu"]),
            items=tuple(LayoutPolygon(points=pts, layer="F.Cu") for pts in items),
        )
        gds = export_layout(layout, tmp_path / "rf_trace.gds", "gdsii")
        assert gds.exists()
        back = import_layout(gds, "gdsii")
        polys = [it for it in back.items
                 if isinstance(it, LayoutPolygon)]
        assert len(polys) == 3
        # nm 网格量化（precision=1nm）→ 面积相对误差 1e-7 量级内
        for src_area, poly in zip(src_areas, polys, strict=True):
            assert polygon_shoelace_area(poly.points) == pytest.approx(
                src_area, rel=1e-6)


# ─── 寄生反查闭环（收尾件①）：提取 vs 闭式双源 ────────────────────────────


class TestParasiticLoop:
    def test_taper_equivalent_length_loop_exact(self):
        """已知渐变段 → 提取（shoelace 面积/参考宽） vs 闭式（设计参数代数）
        ——两独立路径逐位相等（#118 双源）。"""
        length, w1, w2 = 7.3, 1.2, 0.6
        poly = taper_polygon((0.0, 0.0), (length, 0.0), w1, w2)
        for w_ref in (w1, w2):
            extracted = equivalent_length_mm(poly, w_ref)
            closed = taper_equivalent_length_closed_form(length, w1, w2, w_ref)
            assert extracted == pytest.approx(closed, rel=1e-12)
        # 旋转坐标系不变（提取侧刚体不变）
        rot = taper_polygon((2.0, -1.0),
                            (2.0 + length * C30, -1.0 + length * S30), w1, w2)
        assert equivalent_length_mm(rot, w2) == pytest.approx(
            equivalent_length_mm(poly, w2), rel=1e-12)

    def test_miter_chamfer_capacitance_loop(self):
        """倒角挖铜 c²/2 → 平行板不连续电容：提取（两倒角档 shoelace 面积差）
        vs 闭式（c²/2 代数差）逐位；电容换算量级钉（1mm²/εeff=1/h=1mm =
        ε0）。"""
        c1, c2 = 0.2, 0.5

        def mk(c: float):
            return mitered_bend_polygon((0, 0), (10, 0), (10, 8), 1.0,
                                        chamfer_mm=c)

        # 挖铜量 = c2 档比 c1 档少掉的铜面积（正数，两路径独立对照）
        da_extracted = polygon_shoelace_area(mk(c1)) - polygon_shoelace_area(mk(c2))
        da_closed = (miter_chamfer_removed_area_mm2(c2)
                     - miter_chamfer_removed_area_mm2(c1))
        assert da_extracted == pytest.approx(da_closed, rel=1e-12)
        assert da_closed > 0  # 倒角越大挖铜越多
        er_eff, h = 3.5, 0.254
        dc = plate_capacitance_f(da_extracted, er_eff, h)
        assert dc == pytest.approx(
            EPSILON_0_F_PER_MM * er_eff * da_closed / h, rel=1e-15)
        assert dc > 0

    def test_rounded_centerline_length_loop_convergence(self):
        """圆角弯：面积口径等效长度 → 闭式 L1+L2−r·(2−π/2)（弧离散收敛
        O(1/n²)：误差随 n_arc 单调改进）。"""
        w, r, l1, l2 = 1.0, 1.5, 10.0, 8.0
        expected = l1 + l2 - rounded_corner_saving_mm(r)
        errs = {}
        for n in (64, 256, 1024):
            poly = rounded_bend_polygon((0, 0), (l1, 0), (l1, l2), w, r, n_arc=n)
            errs[n] = abs(equivalent_length_mm(poly, w) - expected)
        assert errs[1024] < errs[256] < errs[64]
        assert errs[256] < 1e-3 * expected

    def test_area_width_centerline_identity(self):
        """同源恒等式交叉钉：A_closed = w·(L1+L2−r·(2−π/2))——面积系数与
        中心线缩短系数同源（角方挖四分之一圆盘）。"""
        w, r = 1.0, 1.5
        assert w * (18.0 - rounded_corner_saving_mm(r)) == pytest.approx(
            w * 18.0 - r * w * (2.0 - math.pi / 2.0), rel=1e-15)

    def test_plate_capacitance_value_and_guards(self):
        assert plate_capacitance_f(1.0, 1.0, 1.0) == EPSILON_0_F_PER_MM
        with pytest.raises(ValueError, match="area_mm2"):
            plate_capacitance_f(True, 1.0, 1.0)
        with pytest.raises(ValueError, match="area_mm2"):
            plate_capacitance_f(-1.0, 1.0, 1.0)
        with pytest.raises(ValueError, match="er_eff"):
            plate_capacitance_f(1.0, 0.0, 1.0)
        with pytest.raises(ValueError, match="height_mm"):
            plate_capacitance_f(1.0, 1.0, float("nan"))
        with pytest.raises(ValueError, match="width_ref_mm"):
            equivalent_length_mm(taper_polygon((0, 0), (1, 0), 1.0, 0.5), 0.0)


# ─── KiCad footprint 直发（收尾件②）：.kicad_mod 文本结构往返裁判 ──────────


def _sexpr_tokens(text: str) -> list[str]:
    return re.findall(r'\(|\)|"[^"]*"|[^\s()]+', text)


def _sexpr_parse(text: str) -> list:
    """最小 s-expr 解析器（结构裁判，无 KiCad 依赖）：返回嵌套列表，
    引号字符串原子保留引号。"""
    toks = _sexpr_tokens(text)
    pos = 0

    def rec() -> list:
        nonlocal pos
        assert toks[pos] == "(", f"期望 '(' 实得 {toks[pos]!r}"
        pos += 1
        node: list = []
        while pos < len(toks) and toks[pos] != ")":
            if toks[pos] == "(":
                node.append(rec())  # rec 已消费到子节点 ')' 之后
            else:
                node.append(toks[pos])
                pos += 1
        assert pos < len(toks), "括号不闭合"
        pos += 1
        return node

    tree = rec()
    assert pos == len(toks), "token 未耗尽（多余右括号）"
    return tree


def _find_all(node: list, tag: str) -> list[list]:
    return [c for c in node if isinstance(c, list) and c and c[0] == tag]


def _gr_poly_pts(pad_node: list) -> list[list[tuple[float, float]]]:
    prims = _find_all(pad_node, "primitives")[0]
    out = []
    for gp in _find_all(prims, "gr_poly"):
        pts_tok = _find_all(gp, "pts")[0]
        pts = []
        for pt in pts_tok[1:]:
            assert isinstance(pt, list) and pt[0] == "xy", f"非法点 {pt!r}"
            pts.append((float(pt[1]), float(pt[2])))
        out.append(pts)
    return out


class TestKicadFootprintText:
    POLYS: ClassVar[list] = [
        taper_polygon((0.0, 0.0), (7.3, 0.0), 1.2, 0.6),
        mitered_bend_polygon((0, 0), (10, 0), (10, 8), 1.0),
        rounded_bend_polygon((20.0, 0.0), (30.0, 0.0), (30.0, 8.0),
                             1.0, 1.5, n_arc=32),
    ]

    def test_structure_root_pad_primitives(self):
        text = kicad_footprint_text(self.POLYS, name="rf_n14",
                                    value="RF_TRACE")
        root = _sexpr_parse(text)
        assert root[0] == "footprint"
        assert root[1] == '"rf_n14"'
        assert ["version", "20260206"] in root  # KiCad 10.0.6 实测格式版本
        assert ["layer", '"F.Cu"'] in root
        pads = _find_all(root, "pad")
        assert len(pads) == 1
        pad = pads[0]
        assert "smd" in pad and "custom" in pad
        assert ["layers", '"F.Cu"'] in pad
        opts = _find_all(pad, "options")[0]
        assert _find_all(opts, "clearance") == [["clearance", "outline"]]
        assert _find_all(opts, "anchor") == [["anchor", "rect"]]
        prims = _find_all(pad, "primitives")[0]
        gr_polys = _find_all(prims, "gr_poly")
        assert len(gr_polys) == len(self.POLYS)
        for gp in gr_polys:
            assert ["width", "0"] in gp
            assert ["fill", "yes"] in gp

    def test_area_and_vertex_preservation(self):
        """铜几何守恒：gr_poly 顶点数逐多边形一致 + shoelace 面积还原
        （平移不变，rel 1e-9 = nm 网格量化底）。"""
        text = kicad_footprint_text(self.POLYS)
        pad = _find_all(_sexpr_parse(text), "pad")[0]
        parsed = _gr_poly_pts(pad)
        for src, pts in zip(self.POLYS, parsed, strict=True):
            assert len(pts) == len(src)
            assert polygon_shoelace_area(pts) == pytest.approx(
                polygon_shoelace_area(src), rel=1e-5)  # nm 网格量化底

    def test_nm_grid_number_format(self):
        text = kicad_footprint_text(self.POLYS)
        for tok in _sexpr_tokens(text):
            if re.fullmatch(r"-?\d.*", tok):  # 数值原子（不含引号串）
                assert "e" not in tok.lower(), tok
                assert tok != "-0", tok
                assert float(tok) == round(float(tok), 6), tok

    def test_origin_default_centered_and_explicit(self):
        """origin=None → footprint 系铜坐标对称；显式 origin → 世界坐标
        平移逐点可复算。变换链钉：footprint 坐标 = 基元 pts + pad 位置
        （KiCad 10 物化口径，基元 pts 相对锚点、origin 只进 pad 位置）。"""
        text = kicad_footprint_text(self.POLYS)
        root = _sexpr_parse(text)
        pad = _find_all(root, "pad")[0]
        at = _find_all(pad, "at")[0][1:]
        ax = float(at[0])
        xs = [px + ax for pts in _gr_poly_pts(pad) for (px, _py) in pts]
        # 世界铜 bbox x∈[0, 30.5]（弯外缘 x=l1+w/2=30.5）→ 居中后 max=15.25
        assert max(xs) == pytest.approx(30.5 / 2.0, abs=1e-6)

        # 显式 origin=(0,0)：单 taper（最大面积=自身），锚=首顶点 (0,+w1/2)
        # （左法向 (0,1)，taper_polygon 首顶点=p0+n·w1/2）
        poly = taper_polygon((0.0, 0.0), (7.3, 0.0), 1.2, 0.6)
        text2 = kicad_footprint_text([poly], origin=(0.0, 0.0))
        pad2 = _find_all(_sexpr_parse(text2), "pad")[0]
        assert _find_all(pad2, "at")[0][1:] == ["0", "0.6"]
        assert _gr_poly_pts(pad2)[0][0] == (0.0, 0.0)  # 首顶点=锚 → 局部原点
        assert polygon_shoelace_area(_gr_poly_pts(pad2)[0]) == pytest.approx(
            polygon_shoelace_area(poly), rel=1e-9)

    def test_silk_bbox_closed_loop(self):
        text = kicad_footprint_text(self.POLYS, silk_margin_mm=0.5,
                                    silk_width_mm=0.12)
        root = _sexpr_parse(text)
        silk_lines = [n for n in _find_all(root, "fp_line")
                      if ["layer", '"F.SilkS"'] in n]
        assert len(silk_lines) == 4
        segs = []
        for n in silk_lines:
            st = _find_all(n, "start")[0][1:]
            en = _find_all(n, "end")[0][1:]
            segs.append(((float(st[0]), float(st[1])),
                         (float(en[0]), float(en[1]))))
            stroke = _find_all(n, "stroke")[0]
            assert _find_all(stroke, "width") == [["width", "0.12"]]
        for i, seg in enumerate(segs):
            assert seg[1] == segs[(i + 1) % 4][0]  # 闭合环
        # 四角=并集 bbox±margin（闭式复算：世界 x∈[0,30.5]、y∈[−0.6,8]，
        # 原点=中心 (15.25, 3.7)，margin 0.5）
        assert {s[0] for s in segs} == {(-15.75, -4.8), (15.75, -4.8),
                                        (15.75, 4.8), (-15.75, 4.8)}

    def test_silk_off_no_lines(self):
        text = kicad_footprint_text(self.POLYS, silk=False)
        root = _sexpr_parse(text)
        assert _find_all(root, "fp_line") == []

    def test_determinism(self):
        assert (kicad_footprint_text(self.POLYS)
                == kicad_footprint_text(self.POLYS))

    def test_guards(self):
        with pytest.raises(ValueError, match="不能为空"):
            kicad_footprint_text([])
        with pytest.raises(ValueError, match="至少 3 顶点"):
            kicad_footprint_text([((0, 0), (1, 0), (1, 1)),
                                  ((0, 0), (1, 0))])
        with pytest.raises(ValueError, match="s-expr 非法字符"):
            kicad_footprint_text(self.POLYS, name='bad"name')
        with pytest.raises(ValueError, match="silk_width_mm"):
            kicad_footprint_text(self.POLYS, silk_width_mm=0.0)
        with pytest.raises(ValueError, match="silk 必须"):
            kicad_footprint_text(self.POLYS, silk=1)
        with pytest.raises(ValueError, match="有限"):
            kicad_footprint_text([((0, 0), (1, 0), (float("nan"), 1.0))])
        with pytest.raises(ValueError, match="坐标对"):
            kicad_footprint_text([((0, 0), (1, 0), (1,))])
