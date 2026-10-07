"""F-I P1 核心段测试：RF 叠层 schema / 斜段矩形化 / 渲染原语桥 / 有效性守卫。

验收口径（任务书 §二）：schema round-trip 逐字段相等；斜段矩形化水平/垂直/45°
三例的顶点数与面积守恒（容差 = 步长×width×段数，#212 离线几何审计惯例——
纯几何断言，零仿真零真机）；validate_polygon 可修复/不可修复两态；桥接层
匹配统计如实（unmatched 显式计数不猜）。gdstk 链为可选（在装才跑，
不进核心 import——与 B2 惰性导入惯例同源）。全部确定性、tmp_path 隔离。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from rfauto.adapters.layout_interchange import (
    Layout,
    LayoutCircle,
    LayoutLayer,
    LayoutPath,
    LayoutPolygon,
    LayoutVia,
    assign_gds_layers,
)
from rfauto.adapters.layout_stack import (
    PRIMITIVE_SCHEMA_VERSION,
    RFRouteLayer,
    RFStackup,
    bridge_layout_to_stackup,
    dump_stackup,
    load_stackup,
    polygon_to_render_primitives,
    rectangularize_segment,
    stackup_from_dict,
    stackup_to_dict,
    validate_polygon,
)

# ---------------------------------------------------------------------------
# 公共 fixture
# ---------------------------------------------------------------------------


def _layer(**overrides: object) -> RFRouteLayer:
    base: dict[str, object] = {
        "name": "F.Cu",
        "zmin_m": 1.535e-3,
        "thickness_m": 3.5e-5,
        "material": "copper",
        "kind": "signal",
        "gds_layer": 1,
        "gds_datatype": 0,
        "mesh_hint_mm": 0.1,
    }
    base.update(overrides)
    return RFRouteLayer(**base)  # type: ignore[arg-type]


def _two_layer_stackup() -> RFStackup:
    return RFStackup(
        name="two_layer",
        layers=(
            _layer(),
            _layer(name="B.Cu", zmin_m=0.0, kind="ground", gds_layer=2, mesh_hint_mm=None),
            _layer(name="FR4", zmin_m=3.5e-5, thickness_m=1.5e-3, material="fr4_epoxy",
                   kind="dielectric", gds_layer=None, gds_datatype=None),
        ),
    )


def _area(rects: list[list[tuple[float, float]]]) -> float:
    """矩形序列的联合面积（shapely 精确并集，重叠只计一次）。"""
    return float(unary_union([Polygon(r) for r in rects]).area)


# ---------------------------------------------------------------------------
# schema round-trip
# ---------------------------------------------------------------------------


class TestStackupSchema:
    def test_round_trip_field_by_field(self, tmp_path: Path) -> None:
        stackup = _two_layer_stackup()
        yaml_path = dump_stackup(stackup, tmp_path / "stackup.yaml")
        loaded = load_stackup(yaml_path)
        assert loaded.name == stackup.name
        assert len(loaded.layers) == len(stackup.layers)
        for got, want in zip(loaded.layers, stackup.layers, strict=True):
            assert got.name == want.name
            assert got.zmin_m == want.zmin_m
            assert got.thickness_m == want.thickness_m
            assert got.material == want.material
            assert got.kind == want.kind
            assert got.gds_layer == want.gds_layer
            assert got.gds_datatype == want.gds_datatype
            assert got.mesh_hint_mm == want.mesh_hint_mm

    def test_dict_round_trip_preserves_none_fields(self) -> None:
        stackup = _two_layer_stackup()
        rebuilt = stackup_from_dict(stackup_to_dict(stackup))
        assert rebuilt == stackup

    def test_yaml_text_is_utf8_and_sorted_off(self, tmp_path: Path) -> None:
        stackup = _two_layer_stackup()
        yaml_path = dump_stackup(stackup, tmp_path / "s.yaml")
        text = yaml_path.read_text(encoding="utf-8")
        assert "name: two_layer" in text
        assert text.index("name: F.Cu") < text.index("zmin_m")

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_stackup(tmp_path / "absent.yaml")

    @pytest.mark.parametrize(
        "overrides",
        [
            {"kind": "cosmetic"},
            {"thickness_m": -1e-6},
            {"mesh_hint_mm": 0.0},
            {"mesh_hint_mm": -0.2},
            {"name": ""},
            {"material": ""},
        ],
    )
    def test_invalid_layer_fields_raise(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            _layer(**overrides)

    def test_zero_thickness_metal_is_legal(self) -> None:
        layer = _layer(thickness_m=0.0)
        assert layer.thickness_m == 0.0

    def test_datatype_without_gds_layer_raises(self) -> None:
        with pytest.raises(ValueError):
            _layer(gds_layer=None, gds_datatype=0)

    def test_missing_field_in_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="缺字段"):
            stackup_from_dict({"name": "s", "layers": [{"name": "F.Cu"}]})

    def test_selector_semantics_strict(self) -> None:
        gds_layer = _layer(gds_layer=5, gds_datatype=None)
        assert gds_layer.matches(5, 99, "anything")  # datatype 通配
        assert not gds_layer.matches(6, 0, "F.Cu")  # 层号优先，不回落层名
        name_layer = _layer(gds_layer=None, gds_datatype=None)
        assert name_layer.matches(7, 0, "F.Cu")  # 名字命中
        assert not name_layer.matches(7, 0, "B.Cu")

    def test_find_layer_first_match_and_miss(self) -> None:
        stackup = _two_layer_stackup()
        hit = stackup.find_layer(2, 0, "B.Cu")
        assert hit is not None and hit.kind == "ground"
        assert stackup.find_layer(999, 0, "nope") is None
        with pytest.raises(KeyError):
            stackup.require_layer("nope")


# ---------------------------------------------------------------------------
# 斜段矩形化
# ---------------------------------------------------------------------------


class TestRectangularize:
    def test_horizontal_single_rect_exact(self) -> None:
        rects = rectangularize_segment([(0.0, 0.0), (10.0, 0.0)], 0.5)
        assert len(rects) == 1
        xs = sorted({p[0] for p in rects[0]})
        ys = sorted({p[1] for p in rects[0]})
        assert xs == pytest.approx([0.0, 10.0])
        assert ys == pytest.approx([-0.25, 0.25])
        assert _area(rects) == pytest.approx(10.0 * 0.5)

    def test_vertical_single_rect_exact(self) -> None:
        rects = rectangularize_segment([(3.0, -2.0), (3.0, 6.0)], 0.4)
        assert len(rects) == 1
        xs = sorted({p[0] for p in rects[0]})
        assert xs == pytest.approx([2.8, 3.2])
        assert _area(rects) == pytest.approx(8.0 * 0.4)

    def test_45deg_staircase_area_conserved(self) -> None:
        """45° 特例：联合面积 vs 真实斜带面积，容差 = 步长×width×段数。

        实测（shapely 精确并集，#212 离线几何审计惯例）：缺省步长 width/2 下
        45° 阶梯联合面积偏差 −13%（阶梯内角切割 vs 端面方块增补的净效果），
        远小于容差 step×width×nsteps。面积偏差随步长非单调（细步长内角切割
        占优、粗步长跳越占优），故只按任务容差断言并记录量级。
        """
        w = 0.5
        seg = [(0.0, 0.0), (10.0, 10.0)]
        length = 10.0 * math.sqrt(2.0)
        rects = rectangularize_segment(seg, w)
        # 步长缺省 = width/2；步数 = ceil(L/step)
        step = w / 2.0
        n_steps = math.ceil(length / step)
        assert len(rects) == 2 * n_steps + 2  # 每步 L 形两支 + 两端面方块
        union_area = _area(rects)
        true_area = w * length
        tolerance = step * w * n_steps
        assert abs(union_area - true_area) <= tolerance
        assert union_area == pytest.approx(true_area, rel=0.15), (
            f"45° 联合面积 {union_area:.4f} vs 斜带 {true_area:.4f}（实测偏差 −13% 量级）"
        )

    def test_oblique_covers_both_end_faces(self) -> None:
        """端面方块守卫：倾斜端面的轴对齐包络被完整覆盖（RF 端口连通性）。"""
        w = 0.6
        (x0, y0), (x1, y1) = (1.0, 2.0), (7.0, 11.0)
        rects = rectangularize_segment([(x0, y0), (x1, y1)], w)
        union = unary_union([Polygon(r) for r in rects])
        half = w / 2.0
        assert union.contains(Polygon([(x0 - half, y0 - half), (x0 + half, y0 - half),
                                       (x0 + half, y0 + half), (x0 - half, y0 + half)]))
        assert union.contains(Polygon([(x1 - half, y1 - half), (x1 + half, y1 - half),
                                       (x1 + half, y1 + half), (x1 - half, y1 + half)]))

    def test_oblique_axis_aligned_is_exact_no_staircase(self) -> None:
        rects = rectangularize_segment([(0.0, 0.0), (0.0, 5.0)], 1.0)
        assert len(rects) == 1  # 直通例不引入阶梯图元

    def test_max_step_override_increases_fidelity(self) -> None:
        """细步长：图元数增多（角部几何更贴斜带），面积偏差仍在任务容差内。

        实测细步长面积偏差 −22%（内角切割占优）反而大于缺省步长的 −13%——
        步长语义是几何保真旋钮而非面积旋钮，如实断言容差与图元数关系。
        """
        w = 0.5
        seg = [(0.0, 0.0), (10.0, 10.0)]
        default_rects = rectangularize_segment(seg, w)
        fine_rects = rectangularize_segment(seg, w, max_step_m=w / 8.0)
        assert len(fine_rects) > len(default_rects)
        length = 10.0 * math.sqrt(2.0)
        fine_step = w / 8.0
        n_steps = math.ceil(length / fine_step)
        assert abs(_area(fine_rects) - w * length) <= fine_step * w * n_steps

    def test_polyline_mixed_axis_and_oblique(self) -> None:
        w = 0.4
        pts = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (8.0, 8.0)]
        rects = rectangularize_segment(pts, w)
        union_area = _area(rects)
        true_area = w * (4.0 + 4.0 + 4.0 * math.sqrt(2.0))
        n_steps = math.ceil(4.0 * math.sqrt(2.0) / (w / 2.0))
        assert abs(union_area - true_area) <= (w / 2.0) * w * n_steps

    def test_duplicate_consecutive_points_tolerated(self) -> None:
        rects = rectangularize_segment([(0.0, 0.0), (0.0, 0.0), (5.0, 0.0)], 0.5)
        assert len(rects) == 1

    def test_width_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            rectangularize_segment([(0.0, 0.0), (1.0, 0.0)], 0.0)
        with pytest.raises(ValueError):
            rectangularize_segment([(0.0, 0.0), (1.0, 0.0)], -0.3)

    def test_fewer_than_two_points_raises(self) -> None:
        with pytest.raises(ValueError):
            rectangularize_segment([(0.0, 0.0)], 0.5)
        with pytest.raises(ValueError):
            rectangularize_segment([], 0.5)

    def test_invalid_step_raises(self) -> None:
        with pytest.raises(ValueError):
            rectangularize_segment([(0.0, 0.0), (1.0, 1.0)], 0.5, max_step_m=0.0)


# ---------------------------------------------------------------------------
# validate_polygon / 渲染原语
# ---------------------------------------------------------------------------


class TestValidatePolygon:
    def test_convex_ring_passthrough(self) -> None:
        ring = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]
        poly = validate_polygon(ring)
        assert poly.is_valid
        assert poly.area == pytest.approx(2.0)

    def test_closing_duplicate_point_removed(self) -> None:
        ring = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
        poly = validate_polygon(ring)
        assert poly.area == pytest.approx(2.0)

    def test_self_intersection_repairable(self) -> None:
        # 尖刺自相交：外环带一条折回窄刺——make_valid 可修复为有效面
        ring = [(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (1.5, 3.0),
                (1.0, 2.0), (0.0, 2.0)]
        poly = validate_polygon(ring)
        assert poly.is_valid
        assert poly.area > 0.0

    def test_self_intersection_unrepairable_raises(self) -> None:
        # 全共线零面积环：make_valid 后仍无面片 → 显式 ValueError（判据⑤负例）
        with pytest.raises(ValueError, match="make_valid"):
            validate_polygon([(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)])

    def test_fewer_than_three_points_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_polygon([(0.0, 0.0), (1.0, 1.0)])


class TestRenderPrimitives:
    def test_polygon_with_hole_carries_rings(self) -> None:
        layer = _layer()
        poly = Polygon([(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],
                       [[(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]])
        prims = polygon_to_render_primitives(poly, layer)
        assert len(prims) == 1
        prim = prims[0]
        assert prim["kind"] == "polygon"
        assert len(prim["coords"]) == 4
        assert len(prim["holes"]) == 1
        assert len(prim["holes"][0]) == 4
        # 外环末点不重复首点
        assert prim["coords"][0] != prim["coords"][-1]
        assert prim["layer"] == "F.Cu"
        assert prim["layer_kind"] == "signal"
        assert prim["material"] == "copper"
        assert prim["zmin_m"] == layer.zmin_m
        assert prim["thickness_m"] == layer.thickness_m
        assert prim["mesh_hint_mm"] == layer.mesh_hint_mm

    def test_multipolygon_yields_one_primitive_per_part(self) -> None:
        from shapely.geometry import MultiPolygon

        layer = _layer()
        a = Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        b = Polygon([(5.0, 5.0), (6.0, 5.0), (6.0, 6.0), (5.0, 6.0)])
        prims = polygon_to_render_primitives(MultiPolygon([a, b]), layer)
        assert len(prims) == 2

    def test_raw_ring_validated_then_converted(self) -> None:
        layer = _layer(name="GND", kind="ground")
        prims = polygon_to_render_primitives([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)], layer)
        assert prims[0]["layer_kind"] == "ground"

    def test_invalid_ring_rejected_at_conversion(self) -> None:
        layer = _layer()
        with pytest.raises(ValueError):
            polygon_to_render_primitives([(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)], layer)

    def test_schema_version_anchor(self) -> None:
        assert PRIMITIVE_SCHEMA_VERSION == 1


# ---------------------------------------------------------------------------
# 桥接（B2 Layout → RFStackup）
# ---------------------------------------------------------------------------


def _reference_layout() -> Layout:
    return Layout(
        name="bridge_ref",
        layers=(*assign_gds_layers(["F.Cu", "B.Cu", "Silk"]),
                LayoutLayer(name="FR4", gds_layer=70)),
        items=(
            # 水平走线（F.Cu=信号）：单矩形
            LayoutPath(points=((1.0, 5.0), (9.0, 5.0)), width_mm=0.5, layer="F.Cu"),
            # 45° 斜走线（F.Cu）：阶梯化多矩形
            LayoutPath(points=((9.0, 5.0), (13.0, 9.0)), width_mm=0.5, layer="F.Cu"),
            # 地层焊盘圆（B.Cu）
            LayoutCircle(center=(2.0, 2.0), radius_mm=0.5, layer="B.Cu"),
            # 丝印层不在叠层 → unmatched
            LayoutPolygon(points=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)), layer="Silk"),
            # 过孔 → v1 显式跳过计数
            LayoutVia(position=(5.0, 5.0), pad_diameter_mm=0.6, drill_diameter_mm=0.3,
                      pad_layer="F.Cu"),
        ),
    )


class TestBridge:
    def test_two_matched_one_unmatched_stats_honest(self) -> None:
        result = bridge_layout_to_stackup(_reference_layout(), _two_layer_stackup())
        assert result["unmatched_layers"] == ["Silk"]
        stats = result["stats"]
        assert stats["n_items"] == 5
        assert stats["skipped_vias"] == 1
        assert stats["skipped_unmatched_items"] == 1
        assert stats["matched_layers"] == {"B.Cu": "B.Cu", "F.Cu": "F.Cu"}
        # FR4（介质层）无几何 → 如实进 unused
        assert stats["stackup_layers_unused"] == ["FR4"]

    def test_units_mm_to_m(self) -> None:
        result = bridge_layout_to_stackup(_reference_layout(), _two_layer_stackup())
        rects = [p for p in result["primitives"] if p["layer"] == "F.Cu"]
        # 水平走线首矩形：x∈[1,9]mm、y∈[5±0.25]mm → 米制
        first = rects[0]
        xs = sorted({p[0] for p in first["coords"]})
        ys = sorted({p[1] for p in first["coords"]})
        assert xs == pytest.approx([1e-3, 9e-3])
        assert ys == pytest.approx([4.75e-3, 5.25e-3])

    def test_oblique_path_staircased_in_bridge(self) -> None:
        result = bridge_layout_to_stackup(_reference_layout(), _two_layer_stackup())
        f_cu_prims = [p for p in result["primitives"] if p["layer"] == "F.Cu"]
        # 1 水平直通矩形 + 斜段阶梯（>1）＝ F.Cu 图元数 >2
        assert len(f_cu_prims) > 2
        # 斜段阶梯任意图元非轴对齐退化（全部是合法矩形环）
        for prim in f_cu_prims:
            ring = prim["coords"]
            assert len(ring) >= 4

    def test_kind_mapping_carried(self) -> None:
        result = bridge_layout_to_stackup(_reference_layout(), _two_layer_stackup())
        kinds = {p["layer"]: p["layer_kind"] for p in result["primitives"]}
        assert kinds["F.Cu"] == "signal"
        assert kinds["B.Cu"] == "ground"

    def test_circle_becomes_polygon_primitive(self) -> None:
        result = bridge_layout_to_stackup(_reference_layout(), _two_layer_stackup())
        b_cu = [p for p in result["primitives"] if p["layer"] == "B.Cu"]
        assert len(b_cu) == 1
        # 半径 0.5mm 内接 64 段圆的米制面积 ≈ π r²
        ring = b_cu[0]["coords"]
        poly = Polygon(ring)
        assert poly.area == pytest.approx(math.pi * 0.25e-6, rel=0.01)

    def test_gds_selector_match_via_layer_table(self) -> None:
        """层名不匹配但 GDS 层号匹配的选择器路径（导入 GDS 层名=层号串场景）。"""
        layout = Layout(
            name="gds_named",
            layers=(LayoutLayer(name="1", gds_layer=1, gds_datatype=0),),
            items=(LayoutPath(points=((0.0, 0.0), (2.0, 0.0)), width_mm=0.3, layer="1"),),
        )
        stackup = RFStackup(name="s", layers=(_layer(),))  # 选择器 gds_layer=1
        result = bridge_layout_to_stackup(layout, stackup)
        assert result["unmatched_layers"] == []
        assert result["stats"]["n_primitives"] == 1
        assert result["stats"]["matched_layers"] == {"1": "F.Cu"}

    def test_name_only_selector_for_unregistered_layer(self) -> None:
        """几何项引用未注册层名 + 叠层为层名选择器 → 兜底按名匹配。"""
        layout = Layout(
            name="loose",
            layers=(),
            items=(LayoutPolygon(points=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)), layer="F.Cu"),),
        )
        stackup = RFStackup(name="s", layers=(_layer(gds_layer=None, gds_datatype=None),))
        result = bridge_layout_to_stackup(layout, stackup)
        assert result["unmatched_layers"] == []
        assert result["stats"]["n_primitives"] == 1

    def test_stackup_mismatch_all_unmatched(self) -> None:
        stackup = RFStackup(name="s", layers=(_layer(name="Top", gds_layer=42),))
        result = bridge_layout_to_stackup(_reference_layout(), stackup)
        assert set(result["unmatched_layers"]) == {"F.Cu", "B.Cu", "Silk"}
        assert result["primitives"] == []
        assert result["stats"]["skipped_unmatched_items"] == 5


# ---------------------------------------------------------------------------
# gdstk 链（在装才跑：GDS 导出→B2 读入→桥接一条链；不进核心 import）
# ---------------------------------------------------------------------------


try:  # 模块级可用性探测（skipif 依据），不进核心 import
    import gdstk  # type: ignore[import-untyped]  # noqa: F401

    HAS_GDSTK = True
except ImportError:
    HAS_GDSTK = False


@pytest.mark.skipif(not HAS_GDSTK, reason="gdstk 未安装（可选 fixture 链）")
class TestGdstkChain:
    def test_export_gds_import_bridge(self, tmp_path: Path) -> None:
        from rfauto.adapters.layout_interchange import export_gdsii, import_gdsii

        layout = Layout(
            name="gds_chain",
            layers=assign_gds_layers(["F.Cu", "B.Cu"]),
            items=(
                LayoutPath(points=((1.0, 1.0), (9.0, 1.0), (9.0, 5.0)), width_mm=0.4,
                           layer="F.Cu"),
                LayoutPolygon(points=((0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)),
                              layer="B.Cu"),
            ),
        )
        gds_path = export_gdsii(layout, tmp_path / "chain.gds")
        readback = import_gdsii(gds_path)
        stackup = RFStackup(
            name="chain",
            layers=(
                _layer(name="1", gds_layer=1, gds_datatype=0),  # GDS 读回层名=层号串
                _layer(name="2", zmin_m=0.0, kind="ground", gds_layer=2, gds_datatype=0),
            ),
        )
        result = bridge_layout_to_stackup(readback, stackup)
        assert result["unmatched_layers"] == []
        stats = result["stats"]
        assert stats["skipped_vias"] == 0
        assert stats["n_primitives"] > 0
        assert set(stats["matched_layers"].values()) == {"1", "2"}
        # 面积守恒粗判（米制）：B.Cu 板面 80mm² 直通
        board = [p for p in result["primitives"] if p["layer"] == "2"]
        assert len(board) == 1
        assert Polygon(board[0]["coords"]).area == pytest.approx(80e-6, rel=1e-6)
