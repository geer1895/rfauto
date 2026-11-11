"""KiCad .kicad_pcb 逐层 3D 渲染导出测试（aurora_q Q-X39，2026-11-07）。

覆盖面（任务书验收五项逐条落钉）：
1. 逐层渲染钉：铜/阻焊/丝印/钻孔（Edge.Cuts）独立 PNG+叠层合成
   预览 PNG/SVG（信封键+产物字节）；
2. plot_style 单源消费钉：dpi/figsize=plot_style 常量恒等（只读消费，
   不冻结 plot_style 数值本身——单源漂移不假红）；
3. CLI 叶+计数链：layer-3d render --json 双路径（成功+失败信封同构）+
   usage 错 exit 2 JSON（#ge1㉙）+ count_cli 权威锚对拍；
4. GLB/STEP 接口预留：skipped 信封如实（零 silently-wrong 产物）；
5. 几何忠实（铁律 7）：旋转矩阵手算锚 + pcbnew oracle 实测值字面锚
   （真机互证产物作常量锚——单测零真机，oracle 全量对拍见
   runs/aurora_q/qx39_render/oracle_crosscheck.json，worst ≤3e-14 mm）
   + 通配层名展开（pcbnew LSET 口径）+ stackup z 累加（根级/setup
   双形态）+ 确定性（同输入两跑逐字节，SVG 盐固定）。

零网络零真机零 license：几何 fixture 全部 tmp_path 内联 s-expr 文本+
仓内 tracked minimal_board；matplotlib Agg OO 后端（零 GUI）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app as cli_app
from rfauto.service.layer_3d_render_service import (
    DEFAULT_LAYERS,
    EXPORT_FORMATS,
    _arc_polyline,
    _expand_layer_tokens,
    _pad_absolute,
    _pad_polygon,
    _pad_polygons,
    layer_kind,
    parse_pcb_scene,
    render_pcb_layers,
    rotate_y_down,
)

_REPO = Path(__file__).resolve().parents[2]
_MINIMAL_PCB = (_REPO / "tests" / "unit" / "fixtures" / "format_overview"
                / "minimal_board.kicad_pcb")

_RUNNER = CliRunner()

# ── 内联合成板（旋转 footprint+通配层名 pad+trapezoid+弧段走线；根级
#    stackup 形态——minimal_board 同款，KiCad 简化手写板常见口径）──────
_ROTATED_PCB = """(kicad_pcb
	(version 20241229)
	(generator "pcbnew")
	(generator_version "9.0")
	(general (thickness 1.6))
	(paper "A4")
	(layers
		(0 "F.Cu" signal)
		(31 "B.Cu" signal)
		(37 "F.SilkS" user "F.Silkscreen")
		(44 "Edge.Cuts" user)
	)
	(setup
		(stackup
			(layer "F.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 1" (type "core") (thickness 1.51)
				(epsilon_r 4.5) (loss_tangent 0.02))
			(layer "B.Cu" (type "copper") (thickness 0.035))
		)
	)
	(net 0 "")
	(net 1 "GND")
	(footprint "Test:R_rot90"
		(layer "F.Cu")
		(at 100 50 90)
		(pad "1" smd rect
			(at 0 0 90)
			(size 2 1.2)
			(layers "F.Cu" "F.Mask")
			(net 1 "GND")
		)
		(pad "2" thru_hole circle
			(at 5 0 90)
			(size 2 2)
			(drill 1)
			(layers "*.Cu" "*.Mask")
			(net 1 "GND")
		)
		(fp_line (start -3 -2) (end 3 2)
			(stroke (width 0.12) (type solid)) (layer "F.SilkS"))
	)
	(footprint "Test:TRAP"
		(layer "F.Cu")
		(at 120 50 -90)
		(pad "1" smd trapezoid
			(at 0 0 -90)
			(size 2 1)
			(rect_delta 0.4 0)
			(layers "F.Cu")
			(net 1 "GND")
		)
	)
	(segment (start 100 50) (end 105 50) (width 0.25) (layer "F.Cu")
		(net 1))
	(segment (start 105 50) (end 105 55) (width 0.25) (layer "B.Cu")
		(net 1))
	(arc (start 100 60) (mid 105 65) (end 110 60) (width 0.3)
		(layer "F.Cu") (net 1))
	(via (at 105 50) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu")
		(net 1))
	(gr_rect (start 95 45) (end 115 70) (stroke (width 0.1) (type solid))
		(fill none) (layer "Edge.Cuts"))
)
"""


def _write_pcb(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "synth.kicad_pcb"
    p.write_text(text, encoding="utf-8")
    return p


# ═════════════════════ 几何忠实（铁律 7）═════════════════════════════

class TestGeometryFidelity:
    def test_rotation_y_down_hand_derived(self):
        """y-down 旋转手算锚（独立推导，非实现同源）。

        R(θ)=[[c,s],[−s,c]]：(5,0,90°)→(0,−5)；(0,5,180°)→(0,−5)；
        (1,0,−90°)→(0,1)；(1,1,90°)→(1,−1)。
        """
        assert rotate_y_down(5.0, 0.0, 90.0) == pytest.approx((0.0, -5.0))
        assert rotate_y_down(0.0, 5.0, 180.0) == pytest.approx((0.0, -5.0))
        assert rotate_y_down(1.0, 0.0, -90.0) == pytest.approx((0.0, 1.0))
        assert rotate_y_down(1.0, 1.0, 90.0) == pytest.approx((1.0, -1.0))

    def test_pad_absolute_matches_pcbnew_oracle_anchor(self):
        """pad 装配坐标 = pcbnew 真机 oracle 实测字面锚（常量，零真机）。

        oracle 源=ecc83-pp 真板 C1（fp at 141.605,99.695,90；pad2 文件
        at 5,0,90）经 ``pcbnew.GetPosition`` 实测 (141.605, 94.695)
        （runs/aurora_q/qx39_render/oracle_crosscheck.json，33 pad 全量
        对拍 worst ≤3e-14 mm / 0°）。
        """
        pad_node = ["pad", "2", "thru_hole", "circle",
                    ["at", "5", "0", "90"],
                    ["size", "2", "2"],
                    ["drill", "1"],
                    ["layers", "*.Cu", "*.Mask"],
                    ["net", "1", "GND"]]
        info = _pad_absolute(141.605, 99.695, 90.0, pad_node)
        assert (info["x_mm"], info["y_mm"]) == pytest.approx(
            (141.605, 94.695), abs=1e-9)
        assert info["angle_deg"] == pytest.approx(90.0)
        assert info["drill_mm"] == pytest.approx(1.0)
        assert info["layers"] == ["*.Cu", "*.Mask"]  # 直读层名原文

    def test_backside_pad_position_uses_footprint_angle(self):
        """背面翻转 fp 回归钉：pad **位置**旋 footprint 角，pad 文件角只管
        形状朝向（早期实现误用 pad 角旋位置——正面巧合正确，背面偏
        1.025 mm，oracle 互证抓出）。

        oracle 字面锚=StickHub 真板背面 fp（at 157.25,105.9,90；pad 局部
        at −0.975,0.05 文件角 0）经 ``pcbnew.GetPosition`` 实测
        (157.3, 106.875)、绝对角 0°。手算：R(90)（c=0,s=1）·(−0.975,0.05)
        =(0.05, 0.975)+at ✓；误用 pad 角 0 会得 (156.275, 105.95) ✗。
        """
        pad_node = ["pad", "1", "smd", "roundrect",
                    ["at", "-0.975", "0.05"],
                    ["size", "0.8", "0.6"],
                    ["layers", "B.Cu", "B.Paste", "B.Mask"]]
        info = _pad_absolute(157.25, 105.9, 90.0, pad_node)
        assert (info["x_mm"], info["y_mm"]) == pytest.approx(
            (157.3, 106.875), abs=1e-9)
        assert info["angle_deg"] == pytest.approx(0.0)  # 形状朝向=文件角

    def test_wildcard_layers_expand_pcbnew_lset(self):
        """通配层名 `*.Cu`/`*.Mask` 展开=pcbnew LSET 口径（真板实证：thru
        pad 层集写通配名，ecc83 R1 pad1 LSET 实测含 F.Cu/B.Cu/F.Mask/
        B.Mask 全四面）。"""
        out, expanded = _expand_layer_tokens(
            ["*.Cu", "*.Mask"], ["F.Cu", "B.Cu"])
        assert expanded is True
        assert out == ["F.Cu", "B.Cu", "F.Mask", "B.Mask"]
        out2, exp2 = _expand_layer_tokens(["F.Cu"], ["F.Cu", "B.Cu"])
        assert exp2 is False and out2 == ["F.Cu"]
        out3, exp3 = _expand_layer_tokens(["F&B.Cu"], ["F.Cu", "B.Cu"])
        assert exp3 is True and out3 == ["F.Cu", "B.Cu"]
        # 去重保序
        out4, _ = _expand_layer_tokens(
            ["F.Cu", "*.Cu"], ["F.Cu", "B.Cu"])
        assert out4 == ["F.Cu", "B.Cu"]

    def test_trapezoid_matches_pcbnew_shape_oracle(self):
        """trapezoid 顶点集=pcbnew ``GetEffectivePolygon`` 字面锚（常量，
        零真机；oracle/oracle_shapes.json）。早期实现角式错成平行四边形
        且 delta 双重旋转——仅钉面积（w·h 两者同值）的弱测抓不到，故
        改钉逐顶点（左/右竖边 h±dx 是梯形判别式）。"""
        def corners(fp_at, pad_at, delta):
            node = ["pad", "1", "smd", "trapezoid",
                    ["at", *[str(v) for v in pad_at]],
                    ["size", "2", "1"],
                    ["rect_delta", str(delta[0]), str(delta[1])],
                    ["layers", "F.Cu"]]
            info = _pad_absolute(*fp_at, node)
            return {(round(x, 9), round(y, 9)) for x, y in _pad_polygon(info)}

        # trap0：fp (10,10,0)、pad (0,0)、delta (0.4,0)
        assert corners((10.0, 10.0, 0.0), (0, 0), (0.4, 0)) == {
            (9.0, 9.3), (11.0, 9.7), (11.0, 10.3), (9.0, 10.7)}
        # trap90：fp (20,10,90)、pad 局部 (1,0) 文件角 90
        assert corners((20.0, 10.0, 90.0), (1, 0, 90), (0.4, 0)) == {
            (19.3, 10.0), (19.7, 8.0), (20.3, 8.0), (20.7, 10.0)}
        # trapdy：delta (0,0.3) → 上横边 w−dy/下横边 w+dy
        assert corners((30.0, 10.0, 0.0), (0, 0), (0, 0.3)) == {
            (29.15, 9.5), (30.85, 9.5), (31.15, 10.5), (28.85, 10.5)}

    def test_oval_is_stadium_and_custom_primitives(self):
        """oval=stadium（非椭圆）+custom 锚形+primitives——pcbnew 形状
        oracle 字面锚：oval 3×1@45° bbox 半宽 1.2071（=√½+0.5，椭圆
        假设 1.118 被证伪）；custom@90° 三角 primitive 顶点 (60,8)/(61,8)
        +rect 锚 bbox [59.75,8,61,10.25]。"""
        oval = _pad_absolute(50.0, 10.0, 45.0, [
            "pad", "1", "smd", "oval", ["at", "0", "0", "45"],
            ["size", "3", "1"], ["layers", "F.Cu"]])
        pts = _pad_polygon(oval)
        assert max(p[0] for p in pts) == pytest.approx(51.2071, abs=1e-4)
        assert min(p[1] for p in pts) == pytest.approx(8.7929, abs=1e-4)
        custom = _pad_absolute(60.0, 10.0, 90.0, [
            "pad", "1", "smd", "custom", ["at", "0", "0", "90"],
            ["size", "0.5", "0.5"], ["layers", "F.Cu"],
            ["options", ["clearance", "outline"], ["anchor", "rect"]],
            ["primitives", ["gr_poly", ["pts", ["xy", "0", "0"],
                                        ["xy", "2", "0"], ["xy", "2", "1"]],
                            ["width", "0"], ["fill", "yes"]]]])
        polys = _pad_polygons(custom)
        assert len(polys) == 2  # 锚形 + 1 primitive
        tri = {(round(x, 9), round(y, 9)) for x, y in polys[1]}
        assert tri == {(60.0, 10.0), (60.0, 8.0), (61.0, 8.0)}
        allp = [p for poly in polys for p in poly]
        assert [min(p[0] for p in allp), min(p[1] for p in allp),
                max(p[0] for p in allp), max(p[1] for p in allp)] == \
            pytest.approx([59.75, 8.0, 61.0, 10.25], abs=1e-9)

    def test_graphic_shapes_by_named_nodes(self, tmp_path):
        """图形项按节点名取点回归钉（早期 tag 遍历序 bug：gr_rect 两点
        画成对角线、gr_circle 画成圆心连线、gr_arc 当 (start,end,mid) 画
        成长弧 ¾ 圆——NFC 天线板框圆角实证）。"""
        text = _ROTATED_PCB.replace(
            '\t(gr_rect (start 95 45) (end 115 70)',
            '\t(gr_circle (center 200 200) (end 203 200) (stroke (width 0.1)'
            ' (type solid)) (fill none) (layer "Edge.Cuts"))\n'
            '\t(gr_arc (start 300 0) (mid 302 2) (end 300 4) (stroke (width'
            ' 0.1) (type solid)) (layer "Edge.Cuts"))\n'
            '\t(gr_rect (start 95 45) (end 115 70)')
        r = parse_pcb_scene(_write_pcb(tmp_path, text))
        edge = {g["item"]: g for g in r["graphics_by_layer"]["Edge.Cuts"]}
        rect = {tuple(p) for p in edge["gr_rect"]["points_mm"]}
        assert rect == {(95.0, 45.0), (115.0, 45.0), (115.0, 70.0),
                        (95.0, 70.0)} and edge["gr_rect"]["closed"]
        circ = edge["gr_circle"]["points_mm"]
        assert len(circ) > 8 and all(
            ((x - 200) ** 2 + (y - 200) ** 2) ** 0.5 == pytest.approx(3.0)
            for x, y in circ)
        arc = edge["gr_arc"]["points_mm"]
        assert arc[0] == pytest.approx([300.0, 0.0], abs=1e-9)
        assert arc[-1] == pytest.approx([300.0, 4.0], abs=1e-9)
        # 短弧经 mid (302,2)：全部点 x≥300（长弧会绕到 x<300 一侧）
        assert min(p[0] for p in arc) >= 300.0 - 1e-9

    def test_arc_polyline_on_circle(self):
        """三点圆弧离散：全部离散点距圆心=半径（独立几何恒等式；
        start(0,0)/mid(5,−5)/end(10,0) → 圆心 (5,0) 半径 5）。"""
        pts = _arc_polyline((0.0, 0.0), (5.0, -5.0), (10.0, 0.0))
        for (x, y) in pts:
            assert ((x - 5.0) ** 2 + y ** 2) ** 0.5 == \
                pytest.approx(5.0, rel=1e-6)
        assert pts[0] == pytest.approx((0.0, 0.0), abs=1e-12)
        assert pts[-1] == pytest.approx((10.0, 0.0), abs=1e-12)
        # 反向（CCW 上半弧）+竖弧：终点精确可达（扫掠方向回归钉——
        # 早期绝对角/增量混用 bug 曾使终点落回起点，本钉直接捕获）
        up = _arc_polyline((0.0, 0.0), (5.0, 5.0), (10.0, 0.0))
        assert up[-1] == pytest.approx((10.0, 0.0), abs=1e-12)
        assert min(((x - 5.0) ** 2 + (y - 5.0) ** 2) ** 0.5
                   for (x, y) in up) == pytest.approx(0.0, abs=1e-9)
        vert = _arc_polyline((5.0, 0.0), (0.0, 5.0), (5.0, 10.0))
        assert vert[-1] == pytest.approx((5.0, 10.0), abs=1e-12)
        # 三点共线退化：折线直连零编造
        deg = _arc_polyline((0.0, 0.0), (5.0, 0.0), (10.0, 0.0))
        assert deg == [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]


# ═════════════════════ 场景解析 ══════════════════════════════════════

class TestParseScene:
    def test_scene_minimal_fixture(self):
        """仓内 tracked fixture：铜层序/bbox/计数/pad 装配坐标手算锚。

        stackup 根级形态直读（silk/mask 缺厚→声明式缺省 0.01+warning）：
        F.Cu z_top=0.02（silk+mask 之上累加）；R1 无旋转 pad1 局部
        (−0.75,0)+fp at (10,10) → 装配 (9.25,10)（手算锚）。
        """
        r = parse_pcb_scene(_MINIMAL_PCB)
        assert r["ok"] is True
        assert r["units"] == "mm"
        assert r["copper_layers"] == ["F.Cu", "B.Cu"]
        assert r["counts"]["footprints"] == 2
        assert r["counts"]["traces"] == 3
        assert r["counts"]["vias"] == 1
        assert r["edge_outline"]["bbox_mm"] == {
            "min_mm": [0.0, 0.0], "max_mm": [30.0, 20.0]}
        names = [(e["name"], e["z_top_mm"]) for e in r["stackup"]]
        assert [n for n, _ in names] == [
            "F.SilkS", "F.Mask", "F.Cu", "dielectric 1", "B.Cu"]
        assert [z for _, z in names] == pytest.approx(
            [0.0, 0.01, 0.02, 0.055, 1.565], abs=1e-12)
        p1 = r["pads_by_layer"]["F.Cu"][0]
        assert (p1["x_mm"], p1["y_mm"]) == pytest.approx((9.25, 10.0))

    def test_scene_rotated_board_full_stack(self, tmp_path):
        """setup.stackup 形态+旋转 fp+通配层名+trapezoid+弧段全栈解析。

        旋转锚（手算）：fp at (100,50,90) 局部 fp_line (−3,−2)→(3,2)
        经 R(90)（c=0,s=1）逐点：(−3,−2)→(−2,3)+at → (98,53)；
        (3,2)→(2,−3)+at → (102,47)。弧段圆心 (105,60) 半径 5（三点独立
        解，全离散点恒等）。
        """
        p = _write_pcb(tmp_path, _ROTATED_PCB)
        r = parse_pcb_scene(p)
        assert r["ok"] is True
        zs = [(e["name"], e["z_top_mm"]) for e in r["stackup"]]
        assert zs == [("F.Cu", 0.0), ("dielectric 1", 0.035),
                      ("B.Cu", 1.545)]
        # F.Cu 桶=rect pad+thru pad（*.Cu 展开）+TRAP trapezoid pad=3
        assert len(r["pads_by_layer"]["F.Cu"]) == 3
        assert len(r["pads_by_layer"]["B.Cu"]) == 1
        assert len(r["pads_by_layer"]["F.Mask"]) == 2
        thru = [q for q in r["pads_by_layer"]["F.Cu"] if q["drill_mm"]]
        assert len(thru) == 1 and thru[0]["number"] == "2"
        silk = r["graphics_by_layer"]["F.SilkS"]
        line = next(g for g in silk if g["item"] == "fp_line")
        assert line["points_mm"][0] == pytest.approx([98.0, 53.0])
        assert line["points_mm"][1] == pytest.approx([102.0, 47.0])
        arc = r["arcs_by_layer"]["F.Cu"][0]["points_mm"]
        for (x, y) in arc:
            assert ((x - 105.0) ** 2 + (y - 60.0) ** 2) ** 0.5 == \
                pytest.approx(5.0, rel=1e-6)
        assert len(r["graphics_by_layer"]["Edge.Cuts"]) == 1

    def test_scene_missing_thickness_declared_default(self, tmp_path):
        """stackup 缺厚度→声明式缺省+warning 如实（缺失不编造）：
        首铜层厚度缺→copper 档 0.035。"""
        text = _ROTATED_PCB.replace('(thickness 0.035))', ')', 1)
        p = _write_pcb(tmp_path, text)
        r = parse_pcb_scene(p)
        assert r["ok"] is True
        assert any("声明式缺省" in w for w in r["warnings"])
        assert r["stackup"][0]["thickness_mm"] == pytest.approx(0.035)

    def test_scene_error_envelopes(self, tmp_path):
        """失败契约：非 kicad 根/文件缺失 → error envelope（ok=False，
        errors 恒 list[str]）。"""
        bad = tmp_path / "bad.kicad_pcb"
        bad.write_text("(schematic (version 1))", encoding="utf-8")
        r = parse_pcb_scene(bad)
        assert r["ok"] is False and isinstance(r["errors"], list)
        r2 = parse_pcb_scene(tmp_path / "nope.kicad_pcb")
        assert r2["ok"] is False and r2["errors"]

    def test_layer_kind_single_source(self):
        """层语义分组单源：任务书口径双别名（Silkscreen/SilkS 同组）+
        内层铜后缀判定。"""
        assert layer_kind("F.Cu") == "copper"
        assert layer_kind("In2.Cu") == "copper"
        assert layer_kind("B.Mask") == "mask"
        assert layer_kind("F.Silkscreen") == "silk"
        assert layer_kind("B.SilkS") == "silk"
        assert layer_kind("Edge.Cuts") == "edge"
        assert layer_kind("User.1") == "other"

    def test_copper_order_by_name_kicad10_ids(self, tmp_path):
        """铜层物理顶→底按**名称**排：KiCad 9/10 层 id 重排（F.Cu=0/
        B.Cu=2/In1.Cu=4/In2.Cu=6）下 id 序会把 B.Cu 排进内层之前——
        kicad_extract 同坑实证；名称序=F.Cu,In1,In2,B.Cu。"""
        text = _ROTATED_PCB.replace(
            '(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)',
            '(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n'
            '\t\t(4 "In1.Cu" signal)\n\t\t(6 "In2.Cu" signal)')
        assert '(6 "In2.Cu" signal)' in text
        r = parse_pcb_scene(_write_pcb(tmp_path, text))
        assert r["copper_layers"] == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        # `*.Cu` 展开随名称序覆盖全部四层（thru pad 落四桶）
        assert all(len(r["pads_by_layer"].get(n, [])) >= 1
                   for n in ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"))

    def test_user_layer_name_alias_resolves(self, tmp_path):
        """任务书口径用户名（F.Silkscreen）→ 文件 canonical（F.SilkS）：
        板层表第 4 token 优先；缺 token 时标准回退表兜底。图形项恒写
        canonical 名，未解析则用户名请求会渲染空场景（本钉防回归）。"""
        p = _write_pcb(tmp_path, _ROTATED_PCB)
        r = render_pcb_layers(p, layers=["F.Silkscreen"])
        assert r["ok"] is True
        assert r["layer_canonical"] == {"F.Silkscreen": "F.SilkS"}
        assert r["layer_geometry_counts"]["F.Silkscreen"]["graphics"] == 1
        assert not any("F.Silkscreen" in w for w in r["warnings"])
        # 层表无第 4 token → 标准回退表（KiCad 标准用户名对）
        bare = _ROTATED_PCB.replace(
            '(37 "F.SilkS" user "F.Silkscreen")', '(37 "F.SilkS" user)')
        s = parse_pcb_scene(_write_pcb(tmp_path, bare))
        assert s["layer_aliases"]["F.Silkscreen"] == "F.SilkS"
        assert s["layer_aliases"]["B.Courtyard"] == "B.CrtYd"


# ═════════════════════ 渲染（逐层+合成+确定性）═══════════════════════

class TestRender:
    def test_plot_style_single_source_consumed(self):
        """plot_style 只读消费钉：dpi/figsize=STYLE 常量恒等（单源漂移
        不假红——断言恒等不断数值）。"""
        import rfauto.service.layer_3d_render_service as svc
        from rfauto.core import plot_style
        assert int(plot_style.STYLE["savefig.dpi"]) == svc._FIG_DPI
        assert plot_style.PAPER_FIGSIZE_DOUBLE == svc._FIGSIZE_COMPOSITE

    def test_render_layers_png_composite(self, tmp_path):
        """逐层 PNG+合成 PNG/SVG 落盘：每请求层一张+composite 双件，
        信封键齐全（png_paths/composite/layer_z_mm/view 声明式落档）。"""
        out = tmp_path / "render"
        r = render_pcb_layers(
            _MINIMAL_PCB, out_dir=out,
            layers=["F.Cu", "B.Cu", "F.Mask", "F.SilkS", "Edge.Cuts"])
        assert r["ok"] is True
        assert r["renderer"] == "layer_3d_render_service"
        assert len(r["png_paths"]) == 5
        assert r["composite"]["png"] and r["composite"]["svg"]
        for p in r["png_paths"] + [r["composite"]["png"],
                                   r["composite"]["svg"]]:
            assert Path(p).is_file() and Path(p).stat().st_size > 0
        assert r["layer_z_mm"]["F.Cu"] == pytest.approx(0.02)
        assert r["layer_z_mm"]["B.Cu"] == pytest.approx(1.565)
        assert r["view"]["explode"] == 0.0
        assert r["view"]["elev_deg"] == r["view"]["azim_deg"] * 0 + 35.0

    def test_render_svg_gid_groups(self, tmp_path):
        """合成 SVG 逐 collection gid=layer3d-composite-<层名>（下游按层
        挑组；G1 出图同源思路）。"""
        out = tmp_path / "svg"
        r = render_pcb_layers(_MINIMAL_PCB, out_dir=out,
                              layers=["F.Cu", "B.Cu"])
        svg = Path(r["composite"]["svg"]).read_text(encoding="utf-8")
        assert 'id="layer3d-composite-F.Cu-traces"' in svg
        assert 'id="layer3d-composite-B.Cu-traces"' in svg
        assert 'id="layer3d-composite-drills"' in svg

    def test_render_determinism_byte_identical(self, tmp_path):
        """确定性：同输入两跑全部产物逐字节一致（Agg OO+SVG 盐固定+
        零时间戳 metadata）。"""
        o1, o2 = tmp_path / "r1", tmp_path / "r2"
        render_pcb_layers(_MINIMAL_PCB, out_dir=o1,
                          layers=["F.Cu", "B.Cu", "Edge.Cuts"])
        render_pcb_layers(_MINIMAL_PCB, out_dir=o2,
                          layers=["F.Cu", "B.Cu", "Edge.Cuts"])
        f1 = sorted(p.name for p in o1.iterdir())
        f2 = sorted(p.name for p in o2.iterdir())
        assert f1 == f2 and len(f1) == 5  # 3 层 PNG+composite png/svg
        for name in f1:
            h1 = hashlib.sha256((o1 / name).read_bytes()).hexdigest()
            h2 = hashlib.sha256((o2 / name).read_bytes()).hexdigest()
            assert h1 == h2, f"{name} 两跑字节漂移"

    def test_render_unknown_layer_empty_scene_warning(self, tmp_path):
        """请求层不在板文件→空场景如实渲染+warning（板文件常省略空层，
        不拒绝）。"""
        out = tmp_path / "u"
        r = render_pcb_layers(_MINIMAL_PCB, out_dir=out,
                              layers=["F.Cu", "In30.Cu"])
        assert r["ok"] is True
        assert any("In30.Cu" in w for w in r["warnings"])
        assert len(r["png_paths"]) == 2

    def test_render_edge_layer_has_drills(self, tmp_path):
        """Edge.Cuts 钻孔面：过孔+thru pad drill 全量画出（合成板 1 via
        +1 thru drill → 钻孔 collection 非空场景出 PNG）。"""
        out = tmp_path / "e"
        r = render_pcb_layers(_write_pcb(tmp_path, _ROTATED_PCB),
                              out_dir=out, layers=["Edge.Cuts"])
        assert r["ok"] is True
        assert len(r["png_paths"]) == 1
        assert Path(r["png_paths"][0]).stat().st_size > 0

    def test_render_no_outdir_envelope_only(self, tmp_path):
        """缺省零落盘（out_dir=None）：信封恒 ok、零文件面（确定性面：
        文件名固定无时间戳——落盘由调用方显式 --out-dir）。"""
        before = set(tmp_path.iterdir())
        r = render_pcb_layers(_MINIMAL_PCB, layers=["F.Cu"])
        assert r["ok"] is True and r["png_paths"] == []
        assert r["composite"] == {"png": None, "svg": None}
        assert set(tmp_path.iterdir()) == before

    def test_render_glb_step_reserved_skipped(self, tmp_path):
        """GLB/STEP 接口预留（任务书第 5 项）：skipped 信封如实+reason
        声明预留语义+零产物零落盘（零 silently-wrong）。"""
        before = set(tmp_path.iterdir())
        for fmt in ("glb", "step"):
            r = render_pcb_layers(_MINIMAL_PCB, out_dir=tmp_path,
                                  export_format=fmt)
            assert r["ok"] is True and r.get("skipped") is True
            assert "接口预留" in r["reason"]
            assert r["export_format"] == fmt
        assert set(tmp_path.iterdir()) == before
        assert set(EXPORT_FORMATS) == {"png", "svg", "glb", "step"}
        assert tuple(DEFAULT_LAYERS) == ("F.Cu", "B.Cu")

    def test_render_unknown_format_error(self):
        """未知 export_format → error envelope（注册面外显式拒绝）。"""
        r = render_pcb_layers(_MINIMAL_PCB, export_format="obj")
        assert r["ok"] is False
        assert "obj" in r["errors"][0]


# ═════════════════════ CLI 叶+计数链 ════════════════════════════════

class TestCliLayer3d:
    def test_render_json_success(self, tmp_path):
        """--json 成功信封：ok=True 可解析+产物路径在信封（Agent 面）+
        固定名落盘（零时间戳）。"""
        out = tmp_path / "cli_out"
        res = _RUNNER.invoke(cli_app, [
            "layer-3d", "render", str(_MINIMAL_PCB),
            "--layers", "F.Cu,B.Cu", "--out-dir", str(out), "--json"])
        assert res.exit_code == 0, res.output
        payload = json.loads(res.output)
        assert payload["ok"] is True
        assert payload["layers"] == ["F.Cu", "B.Cu"]
        assert len(payload["png_paths"]) == 2
        assert (out / "minimal_board_layer_F_Cu.png").is_file()
        assert (out / "minimal_board_composite.svg").is_file()

    def test_render_json_failure_envelope(self, tmp_path):
        """--json 失败信封同构（ok=False/errors 恒 list；#ge1㉙——失败
        路径禁红字裸文本）。"""
        res = _RUNNER.invoke(cli_app, [
            "layer-3d", "render", str(tmp_path / "missing.kicad_pcb"),
            "--json"])
        assert res.exit_code == 1
        payload = json.loads(res.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list) and payload["errors"]

    def test_render_usage_error_exit2_json(self, tmp_path):
        """usage 错（未知 --export-format/--layers 空）→ exit 2+JSON 信封
        （#ge1㉙ 契约：usage 错在 --json 下禁红字裸文本）。"""
        res = _RUNNER.invoke(cli_app, [
            "layer-3d", "render", "x.kicad_pcb",
            "--export-format", "obj", "--json"])
        assert res.exit_code == 2
        assert json.loads(res.output)["ok"] is False
        res2 = _RUNNER.invoke(cli_app, [
            "layer-3d", "render", "x.kicad_pcb", "--layers", " , ",
            "--json"])
        assert res2.exit_code == 2

    def test_render_human_branch(self, tmp_path):
        """缺省人读分支：逐产物 ✓ 行（动态段 escape，无 MarkupError）。"""
        out = tmp_path / "h"
        res = _RUNNER.invoke(cli_app, [
            "layer-3d", "render", str(_MINIMAL_PCB),
            "--layers", "F.Cu", "--out-dir", str(out), "--no-svg"])
        assert res.exit_code == 0
        assert "逐层渲染" in res.output
        assert "minimal_board_layer_F_Cu.png" in res.output

    def test_glb_skipped_human_branch(self):
        """glb 预留面 human 分支：○ 接口预留 行+exit 0（零产物）。"""
        res = _RUNNER.invoke(cli_app, [
            "layer-3d", "render", str(_MINIMAL_PCB),
            "--export-format", "glb"])
        assert res.exit_code == 0
        assert "接口预留" in res.output

    def test_help_hygiene_no_bare_percent(self):
        """--help 构建成功+零裸 % 炸格式扩展（#305 家法真构建 parser）。"""
        res = _RUNNER.invoke(cli_app, ["layer-3d", "--help"])
        assert res.exit_code == 0
        res2 = _RUNNER.invoke(cli_app, ["layer-3d", "render", "--help"])
        assert res2.exit_code == 0
        assert "--layers" in res2.output

    def test_help_panel_registered(self):
        """HELP_PANEL_OF 含 layer-3d（覆盖完整性集合相等守由
        test_aurora_n_wave_ui_c 承担，此处钉本席键）。"""
        from rfauto.cli.help_groups import HELP_PANEL_OF
        assert HELP_PANEL_OF["layer-3d"] == "综合与设计"

    def test_layer_3d_leaf_registration(self):
        """typer 注册面：layer-3d 组内恰 render 一叶（zero-shadow 面）。"""
        from typer.main import get_command
        root = get_command(cli_app)
        assert "layer-3d" in root.commands
        assert list(root.commands["layer-3d"].commands) == ["render"]

    def test_count_chain_cli_315(self):
        """CLI 315（Q-X39 +2：layer-3d render 单叶→314+同窗已落树未钉面
        exploded-view render 单叶桥接口径折入→315——Q-X33 spice 桥接
        同款先例；上锚 Q-X36 sdc 两叶 313）。权威计数=check_numbers
        count_cli 单源；layer-3d 域恰 1 叶。"""
        import importlib.util as ilu
        spec = ilu.spec_from_file_location(
            "cn_gate", _REPO / "scripts" / "check_numbers.py")
        cn = ilu.module_from_spec(spec)
        spec.loader.exec_module(cn)
        assert cn.count_cli() == 357  # aurora_r M-6 统一重钉 358 后，v0.14.0 移除笔 -1
        counts = cn.cli_leaf_counts()
        assert counts["layer-3d"] == 1
        assert sum(counts.values()) == cn.count_cli()
