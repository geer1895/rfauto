"""B6 stage-2 板级全要素 EM 渲染审计（#212 制度化手法：零仿真 CSXCAD 实测）。

链路：extract_pcb（真填充 demo 板 / 合成契约）→ board_facts_from_extract
→ render_script("cpw", {**nominal, "b6_board": facts}) → exec 几何段 →
CSXCAD 实测原语/优先级解析/网格。判据全部量在 CSXCAD 对象上，不做字符串门。

判据（按实测口径落地）：
① 直通：gh.load_geometry("cpw", {**nominal, "b6_board": facts}) 不炸；
② 2 pad 0.8×0.6 @(10,15)/(50,15)（w×h 不等抓轴交换）、4 via 桶壁
   @y=18 x=12/24/36/48、主线矩形、F.Cu/B.Cu 填充多边形、走廊切除多边形；
③ 优先级解析语义（CSX.GetPropertyByCoordPriority，CSX.Update 后）：
   走廊内主线/焊盘点 → b6_rf（RF 12 盖过切除 11）；走廊缝隙点 → substrate
   （切除 11 刻穿模板名义地 10）；过孔壁点 → b6_via；钻孔中心 → substrate
   （桶壁中空）；板角探针 → 地金属（模板名义地 10 > 板级地 5，同为地）；
④ RF 分量（主线+2 pad）单连通、GND 分量（fill+B.Cu+via 桶）单连通；
   RF/GND 不短路由 ③ 的优先级解析 + 渲染坐标 even-odd 裁决（多边形包围盒
   盖住孔洞，bbox 连通性天然无法仲裁 RF-GND——这是 bbox 手法的已知
   局限，不是几何缺陷）；
⑤ 原语零厚面落网格线、#152 最小网格间距守卫；
⑥ 缺省键（无 b6_board）cpw 渲染逐字节不变。

叠加口径（kicad_board_render 模块 docstring）：b6_board 是审计叠加层，
名义中心带/两侧地/CPWPort 照常存在；真机共仿真前须定名义地替换策略
（followUp #25）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.kicad_board_render import (
    B6_PRIORITY_CUT,
    B6_PRIORITY_GND,
    B6_PRIORITY_RF,
    board_geometry_lines,
)
from rfauto.adapters.kicad_extract import (
    KICAD_PYTHON,
    build_demo_cpwg_pcb,
    extract_pcb,
)
from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script
from rfauto.service.kicad_em_service import board_facts_from_extract
from tests.unit import _geometry_audit_helpers as gh
from tests.unit.test_kicad_em_service import _synthetic_filled_extract
from tests.unit.test_kicad_extract import point_in_polys_mm

KICAD_AVAILABLE = Path(KICAD_PYTHON).exists()
MM = 1e-3
TOL_M = 1e-9  # 米（坐标 repr 往返 + mm→m 换算）

# demo 板实测走廊孔包围盒（mm；KiCad 10.0.6，test_kicad_extract 同源）
CORRIDOR_MM = (9.375, 14.375, 50.625, 15.625)
PAD_CENTERS_MM = ((10.0, 15.0), (50.0, 15.0))
VIA_XS_MM = (12.0, 24.0, 36.0, 48.0)
VIA_Y_MM = 18.0


@pytest.fixture(scope="module")
def facts_by_source(tmp_path_factory):
    """两路事实源：合成契约（零 KiCad）+ 真填充 demo 板（KiCad 子进程）。"""
    out: dict[str, dict | None] = {
        "synthetic": board_facts_from_extract(_synthetic_filled_extract()),
        "kicad": None,
    }
    if KICAD_AVAILABLE:
        pcb = (tmp_path_factory.mktemp("kicad_render")
               / "demo_cpwg_filled.kicad_pcb")
        build = build_demo_cpwg_pcb(pcb, fill_zones=True)
        if build["success"]:
            ext = extract_pcb(pcb)
            if ext.get("ok"):
                out["kicad"] = board_facts_from_extract(ext)
    return out


def _facts(facts_by_source, source):
    facts = facts_by_source[source]
    if facts is None:
        pytest.skip("KiCad Python 不存在或真填充板生成失败（离线降级）")
    return facts


def _geometry(facts):
    return gh.load_geometry("cpw", {**TEMPLATE_NOMINAL["cpw"],
                                    "b6_board": facts})


def _prims_of(prims, prop):
    return [p for p in prims if p.prop == prop]


def _resolved(csx, x_mm, y_mm, z_m):
    prop = csx.GetPropertyByCoordPriority([x_mm * MM, y_mm * MM, z_m])
    return (str(prop.GetName()), str(prop.GetTypeString())) if prop else (
        None, None)


def _polygon_coords_mm(prop, elevation_m):
    """属性内指定 elevation 的多边形原语 → [[x,y]…] mm（渲染坐标实测）。"""
    rings = []
    for prim in prop.GetAllPrimitives():
        if str(prim.GetTypeName()) != "Polygon":
            continue
        if abs(float(prim.GetElevation()) - elevation_m) > TOL_M:
            continue
        xs, ys = prim.GetCoords()
        rings.append([[float(x) / MM, float(y) / MM] for x, y in zip(xs, ys,
                                                                    strict=True)])
    return rings


SOURCES = ("synthetic", "kicad")


# ─── ⑥ 缺省键逐字节不变 ───────────────────────────────────────────────────────

def test_default_cpw_render_byte_identical_without_b6_board():
    band = gh.band_for("cpw")
    base = render_script("cpw", dict(TEMPLATE_NOMINAL["cpw"]), band,
                         mesh_resolution_mm=gh.DEFAULT_MESH_MM)
    none_key = render_script("cpw", {**TEMPLATE_NOMINAL["cpw"],
                                     "b6_board": None}, band,
                             mesh_resolution_mm=gh.DEFAULT_MESH_MM)
    assert base == none_key
    assert "b6_" not in base
    assert "AddPolygon" not in base  # 名义 cpw 全盒渲染，无多边形


def test_priority_ladder():
    """RF(12) > 切除(11) > 模板既有 10 > 板级地(5)——刻穿名义地、RF 保真。"""
    assert B6_PRIORITY_RF > B6_PRIORITY_CUT > 10 > B6_PRIORITY_GND


class TestBoardGeometryLinesErrors:
    def test_no_fill_raises(self):
        facts = board_facts_from_extract(_synthetic_filled_extract())
        facts["gnd_fill_f"] = []
        with pytest.raises(ValueError, match="gnd_fill_f"):
            board_geometry_lines(facts)

    def test_via_pad_not_larger_than_drill_raises(self):
        facts = board_facts_from_extract(_synthetic_filled_extract())
        facts["vias"][0]["drill_mm"] = 0.6  # == pad⌀ → 桶壁宽 0
        with pytest.raises(ValueError, match="桶壁"):
            board_geometry_lines(facts)

    def test_slanted_trace_segment_raises(self):
        facts = board_facts_from_extract(_synthetic_filled_extract())
        facts["trace"]["points_mm"] = [[10.0, 15.0], [50.0, 16.0]]
        with pytest.raises(ValueError, match="斜段"):
            board_geometry_lines(facts)

    def test_missing_trace_raises(self):
        facts = board_facts_from_extract(_synthetic_filled_extract())
        facts["trace"] = {}
        with pytest.raises(ValueError, match="trace"):
            board_geometry_lines(facts)

    def test_code_block_names_and_priorities(self):
        facts = board_facts_from_extract(_synthetic_filled_extract())
        code = board_geometry_lines(facts)
        compile(code, "b6_block", "exec")  # 语法合法
        assert 'CSX.AddMetal("b6_gnd")' in code
        assert 'CSX.AddMetal("b6_via")' in code
        assert 'CSX.AddMetal("b6_rf")' in code
        assert "b6_rf_via" not in code  # demo 无信号过孔，不建空属性
        assert code.count("AddCylindricalShell") == 4
        assert code.count("b6_rf.AddBox") == 2
        assert f"priority={B6_PRIORITY_CUT}" in code  # 孔洞切除
        assert "sub.AddPolygon" in code               # 基板同面切除


# ─── ①②③④⑤ 全要素 CSXCAD 审计（两路事实源）───────────────────────────────────

@pytest.mark.parametrize("source", SOURCES)
class TestBoardRenderAudit:
    def test_load_geometry_passthrough(self, facts_by_source, source):
        scope, prims = _geometry(_facts(facts_by_source, source))
        names = {p.prop for p in prims}
        assert {"b6_gnd", "b6_via", "b6_rf", "cpw", "substrate"} <= names
        assert scope["H_SUB"] == pytest.approx(0.508 * MM)

    def test_two_pads_axis_faithful(self, facts_by_source, source):
        scope, prims = _geometry(_facts(facts_by_source, source))
        h = float(scope["H_SUB"])
        pads = [p for p in _prims_of(prims, "b6_rf") if p.prim_type == "1"]
        assert len(pads) == 2
        centers = sorted((float((p.lo[0] + p.hi[0]) / 2 / MM),
                          float((p.lo[1] + p.hi[1]) / 2 / MM)) for p in pads)
        for got, want in zip(centers, PAD_CENTERS_MM, strict=True):
            assert got == pytest.approx(want, abs=1e-6)
        for p in pads:
            ext_mm = p.extent / MM
            assert ext_mm[0] == pytest.approx(0.8, abs=1e-6)  # w（x）
            assert ext_mm[1] == pytest.approx(0.6, abs=1e-6)  # h（y）≠ w
            assert p.lo[2] == pytest.approx(h, abs=TOL_M)
            assert p.hi[2] == pytest.approx(h, abs=TOL_M)

    def test_trace_rectangle(self, facts_by_source, source):
        scope, prims = _geometry(_facts(facts_by_source, source))
        h = float(scope["H_SUB"])
        traces = [p for p in _prims_of(prims, "b6_rf") if p.prim_type == "7"]
        assert len(traces) == 1
        t = traces[0]
        assert (t.lo / MM)[:2] == pytest.approx([10.0, 15.0 - 0.849 / 2],
                                                abs=1e-6)
        assert (t.hi / MM)[:2] == pytest.approx([50.0, 15.0 + 0.849 / 2],
                                                abs=1e-6)
        assert t.lo[2] == pytest.approx(h, abs=TOL_M)

    def test_four_via_barrels(self, facts_by_source, source):
        scope, prims = _geometry(_facts(facts_by_source, source))
        h = float(scope["H_SUB"])
        vias = _prims_of(prims, "b6_via")
        assert len(vias) == 4
        assert all(p.prim_type == "6" for p in vias)  # CylindricalShell
        xs = sorted(float((p.lo[0] + p.hi[0]) / 2 / MM) for p in vias)
        assert xs == pytest.approx(list(VIA_XS_MM), abs=1e-6)
        for p in vias:
            assert float((p.lo[1] + p.hi[1]) / 2 / MM) == pytest.approx(
                VIA_Y_MM, abs=1e-6)
            # 包围盒 = 桶壁外缘 = pad⌀ 0.6（中径 0.225 ± 壁厚 0.15/2 → 外缘 0.3）
            assert (p.extent / MM)[0] == pytest.approx(0.6, abs=1e-6)
            assert p.radius == pytest.approx(0.225 * MM, abs=TOL_M)  # 中径
            assert p.lo[2] == pytest.approx(0.0, abs=TOL_M)
            assert p.hi[2] == pytest.approx(h, abs=TOL_M)

    def test_fill_polygons_and_corridor_cut(self, facts_by_source, source):
        facts = _facts(facts_by_source, source)
        scope, prims = _geometry(facts)
        h = float(scope["H_SUB"])
        fills = [p for p in _prims_of(prims, "b6_gnd") if p.prim_type == "7"]
        assert len(fills) == 2  # F.Cu（z=H）+ B.Cu（z=0）
        assert sorted(float(p.lo[2]) for p in fills) == pytest.approx(
            [0.0, h], abs=TOL_M)
        cuts = [p for p in _prims_of(prims, "substrate") if p.prim_type == "7"]
        assert len(cuts) >= 1
        lo = np.min([c.lo for c in cuts], axis=0) / MM
        hi = np.max([c.hi for c in cuts], axis=0) / MM
        # 渲染保真：切除多边形包围盒 == facts 孔洞包围盒（两路事实源同判）
        holes = [h_ for fp in facts["gnd_fill_f"] for h_ in fp["holes_mm"]]
        hx = [p[0] for h_ in holes for p in h_]
        hy = [p[1] for h_ in holes for p in h_]
        assert (lo[0], lo[1], hi[0], hi[1]) == pytest.approx(
            (min(hx), min(hy), max(hx), max(hy)), abs=1e-9)
        if source == "kicad":  # KiCad 10.0.6 实测走廊真值
            assert (lo[0], lo[1], hi[0], hi[1]) == pytest.approx(
                CORRIDOR_MM, abs=1e-6)
        assert all(c.lo[2] == pytest.approx(h, abs=TOL_M) for c in cuts)

    def test_priority_resolution_semantics(self, facts_by_source, source):
        """CSXCAD 优先级解析（真栅格化语义）：走廊刻穿、RF 保真、桶壁中空。"""
        scope, _ = _geometry(_facts(facts_by_source, source))
        csx = scope["CSX"]
        csx.Update()  # IsInside/点查询需先 Update（2026-09-15 实测）
        h = float(scope["H_SUB"])
        # 走廊内 RF 金属：主线中点、两焊盘中心
        assert _resolved(csx, 30.0, 15.0, h)[0] == "b6_rf"
        for cx, cy in PAD_CENTERS_MM:
            assert _resolved(csx, cx, cy, h)[0] == "b6_rf"
        # 走廊缝隙：切除刻穿模板名义地（10）与板级地（5）→ 基板
        assert _resolved(csx, 30.0, 15.5, h)[0] == "substrate"
        assert _resolved(csx, 9.5, 15.0, h)[0] == "substrate"  # 焊盘左侧孔内
        # 过孔：壁点（r=0.2∈[0.15,0.3]）=桶壁金属；钻孔中心/钻孔内（r=0.1）
        # =中空基板；pad 外缘外（r=0.35）=基板——钉住 shell 中径口径
        assert _resolved(csx, VIA_XS_MM[0], VIA_Y_MM + 0.2, h / 2)[0] == "b6_via"
        assert _resolved(csx, VIA_XS_MM[0], VIA_Y_MM, h / 2)[0] == "substrate"
        assert _resolved(csx, VIA_XS_MM[0], VIA_Y_MM + 0.1, h / 2)[0] == "substrate"
        assert _resolved(csx, VIA_XS_MM[0], VIA_Y_MM + 0.35, h / 2)[0] == "substrate"
        # 板角探针：地金属（名义地 10 > 板级地 5，同为地）
        name, kind = _resolved(csx, 5.0, 5.0, h)
        assert kind == "Metal" and name in {"cpw", "b6_gnd"}
        # 板外（域内、板级填充外、名义地覆盖）：仍是名义地金属——叠加口径
        name2, kind2 = _resolved(csx, -30.0, -30.0, h)
        assert kind2 == "Metal" and name2 == "cpw"

    def test_rendered_fill_even_odd(self, facts_by_source, source):
        """渲染坐标 even-odd：填充含板角探针、不含主线中线与焊盘中心。"""
        scope, _ = _geometry(_facts(facts_by_source, source))
        csx = scope["CSX"]
        h = float(scope["H_SUB"])
        props = {str(csx.GetProperty(i).GetName()): csx.GetProperty(i)
                 for i in range(csx.GetQtyProperties())}
        outer_rings = _polygon_coords_mm(props["b6_gnd"], h)
        cut_rings = _polygon_coords_mm(props["substrate"], h)
        assert len(outer_rings) == 1 and len(cut_rings) >= 1
        rendered = [{"outer_mm": outer_rings[0], "holes_mm": cut_rings}]
        assert point_in_polys_mm(5.0, 5.0, rendered) is True
        assert point_in_polys_mm(30.0, 15.0, rendered) is False
        for cx, cy in PAD_CENTERS_MM:
            assert point_in_polys_mm(cx, cy, rendered) is False
        # 主线四角与焊盘四角全部落在切除区（RF 与填充无重叠）
        for x in (10.0, 50.0):
            for y in (15.0 - 0.849 / 2, 15.0 + 0.849 / 2):
                assert point_in_polys_mm(x, y, rendered) is False
        for cx, cy in PAD_CENTERS_MM:
            for dx in (-0.4, 0.4):
                for dy in (-0.3, 0.3):
                    assert point_in_polys_mm(cx + dx, cy + dy, rendered) is False

    def test_rf_and_gnd_groups_each_connected(self, facts_by_source, source):
        _, prims = _geometry(_facts(facts_by_source, source))
        rf = _prims_of(prims, "b6_rf")
        gnd = _prims_of(prims, "b6_gnd") + _prims_of(prims, "b6_via")
        assert len(rf) == 3 and len(gnd) == 6
        assert len(set(gh.component_labels(rf))) == 1   # 主线+2 pad
        assert len(set(gh.component_labels(gnd))) == 1  # fill+B.Cu+4 via
        assert all(gh.is_conductor(p) for p in rf + gnd)

    def test_primitives_on_mesh_and_min_spacing(self, facts_by_source, source):
        scope, prims = _geometry(_facts(facts_by_source, source))
        b6 = [p for p in prims if p.prop.startswith("b6")
              or (p.prop == "substrate" and p.prim_type == "7")]
        assert len(b6) >= 10
        assert gh.off_mesh_planes(b6, scope) == []
        for ax in ("x", "y", "z"):
            lines = gh.mesh_lines(scope, ax)
            assert float(np.min(np.diff(lines))) > 1e-6  # #152 守卫
        # 板级要素落在域内（±60mm）
        for p in b6:
            assert np.all(p.lo >= -60 * MM - TOL_M)
            assert np.all(p.hi <= 60 * MM + TOL_M)

    def test_nominal_cpw_untouched_by_overlay(self, facts_by_source, source):
        """叠加不改名义 cpw 原语（中心带 + 两侧地 + 端口自画段）。"""
        _, prims_b6 = _geometry(_facts(facts_by_source, source))
        _, prims_base = gh.load_geometry("cpw")
        sig = gh.conductor_signature
        assert sig(_prims_of(prims_b6, "cpw")) == sig(_prims_of(prims_base, "cpw"))
