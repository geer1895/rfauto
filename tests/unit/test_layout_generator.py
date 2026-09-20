"""B5 参数化版图生成器测试（§10.2 B5，与 B2 合并验收：往返无损）。

放杆规则（via fence 计数/偏移/去重）、几何数值（板框/贴片/焊盘阵）、注册表
行为、以及生成产物经 B2 四格式的往返无损。全部确定性离线。
"""

from __future__ import annotations

import pytest

from rfauto.adapters.layout_generator import (
    LAYOUT_GENERATORS,
    generate_layout,
    generate_microstrip,
    generate_pad_array,
    generate_patch_antenna,
    register_layout_generator,
    via_fence_items,
)
from rfauto.adapters.layout_interchange import (
    LAYOUT_INTERCHANGE_FORMATS,
    LayoutCircle,
    LayoutPath,
    LayoutPolygon,
    LayoutVia,
    verify_round_trip,
)


class TestMicrostrip:
    def test_geometry_numbers(self):
        layout = generate_microstrip({"width_mm": 0.5, "length_mm": 20.0, "margin_mm": 2.5})
        board = layout.items[0]
        assert isinstance(board, LayoutPolygon)
        assert board.points == ((0.0, 0.0), (25.0, 0.0), (25.0, 5.5), (0.0, 5.5))
        trace = layout.items[1]
        assert isinstance(trace, LayoutPath)
        assert trace.width_mm == 0.5
        assert trace.points == ((2.5, 2.75), (22.5, 2.75))  # 居中水平馈线

    def test_explicit_board_overrides_margin(self):
        layout = generate_microstrip(
            {"width_mm": 0.5, "length_mm": 10.0, "board_width_mm": 30.0, "board_height_mm": 8.0}
        )
        assert layout.items[0].points == ((0.0, 0.0), (30.0, 0.0), (30.0, 8.0), (0.0, 8.0))

    def test_end_pads(self):
        layout = generate_microstrip(
            {"width_mm": 0.5, "length_mm": 10.0, "end_pad_diameter_mm": 1.0}
        )
        pads = [item for item in layout.items if isinstance(item, LayoutCircle)]
        assert len(pads) == 2
        assert pads[0].radius_mm == 0.5
        # 板 15×5.5（margin 2.5），y_mid=2.75
        assert pads[0].center == (2.5, 2.75)

    def test_via_fence_rails(self):
        layout = generate_microstrip(
            {
                "width_mm": 0.5,
                "length_mm": 10.0,
                "via_fence": {
                    "pitch_mm": 2.5,
                    "pad_diameter_mm": 0.6,
                    "drill_diameter_mm": 0.3,
                    "inset_mm": 1.0,
                },
            }
        )
        vias = [item for item in layout.items if isinstance(item, LayoutVia)]
        # 每侧轨 s=0,2.5,5,7.5,10 → 5 个，两侧 10 个
        assert len(vias) == 10
        ys = sorted({round(via.position[1], 6) for via in vias})
        assert ys == [1.75, 3.75]  # y_mid=2.75 ± inset 1.0
        assert all(via.drill_diameter_mm == 0.3 for via in vias)


class TestViaFenceRule:
    def test_offset_semantics(self):
        """放杆规则：offset=1.0、pitch=3.0、段长 10 → s=1,4,7,10 共 4 孔。"""
        vias = via_fence_items(
            points=[(0.0, 0.0), (10.0, 0.0)],
            pitch_mm=3.0,
            pad_diameter_mm=0.6,
            drill_diameter_mm=0.3,
            offset_mm=1.0,
        )
        assert [round(via.position[0], 9) for via in vias] == [1.0, 4.0, 7.0, 10.0]

    def test_short_segment_below_offset_yields_none(self):
        vias = via_fence_items(
            points=[(0.0, 0.0), (0.5, 0.0)],
            pitch_mm=2.0,
            pad_diameter_mm=0.6,
            drill_diameter_mm=0.3,
            offset_mm=1.0,
        )
        assert vias == []

    def test_shared_corner_dedup(self):
        """L 形折线共享端点按 1nm 格点去重：角点只 1 孔。"""
        vias = via_fence_items(
            points=[(0.0, 0.0), (4.0, 0.0), (4.0, 4.0)],
            pitch_mm=2.0,
            pad_diameter_mm=0.6,
            drill_diameter_mm=0.3,
        )
        positions = [(round(via.position[0], 6), round(via.position[1], 6)) for via in vias]
        assert (4.0, 0.0) in positions
        assert positions.count((4.0, 0.0)) == 1
        assert len(vias) == 5  # (0,0)(2,0)(4,0)(4,2)(4,4)

    def test_diagonal_segment(self):
        vias = via_fence_items(
            points=[(0.0, 0.0), (3.0, 4.0)],  # 段长 5
            pitch_mm=2.5,
            pad_diameter_mm=0.6,
            drill_diameter_mm=0.3,
        )
        assert len(vias) == 3  # s=0,2.5,5
        assert vias[2].position == (3.0, 4.0)

    def test_rejects_nonpositive_pitch(self):
        with pytest.raises(ValueError, match="pitch"):
            via_fence_items([(0.0, 0.0), (1.0, 0.0)], 0.0, 0.6, 0.3)

    def test_rejects_pad_not_wider_than_drill(self):
        with pytest.raises(ValueError, match="焊盘直径"):
            via_fence_items([(0.0, 0.0), (1.0, 0.0)], 1.0, 0.3, 0.3)


class TestPatchAntenna:
    def test_geometry_numbers(self):
        layout = generate_patch_antenna(
            {
                "patch_width_mm": 10.0,
                "patch_length_mm": 7.0,
                "feed_width_mm": 0.3,
                "feed_length_mm": 4.0,
                "margin_mm": 3.0,
            }
        )
        board, patch, feed = layout.items
        assert isinstance(board, LayoutPolygon)
        assert board.points == ((0.0, 0.0), (16.0, 0.0), (16.0, 14.0), (0.0, 14.0))
        assert isinstance(patch, LayoutPolygon)
        assert patch.points[0] == (3.0, 4.0) and patch.points[2] == (13.0, 11.0)
        assert isinstance(feed, LayoutPath)
        assert feed.width_mm == 0.3
        assert feed.points == ((8.0, 0.0), (8.0, 4.0))


class TestPadArray:
    def test_grid_centers(self):
        layout = generate_pad_array(
            {
                "rows": 2,
                "cols": 3,
                "pitch_mm": 1.0,
                "pad_diameter_mm": 0.5,
                "origin": (10.0, 5.0),
            }
        )
        circles = [item for item in layout.items if isinstance(item, LayoutCircle)]
        assert len(circles) == 6
        centers = sorted((round(c.center[0], 6), round(c.center[1], 6)) for c in circles)
        assert centers[0] == (9.0, 4.5) and centers[-1] == (11.0, 5.5)
        assert all(c.radius_mm == 0.25 for c in circles)

    def test_rejects_zero_rows(self):
        with pytest.raises(ValueError, match="rows/cols"):
            generate_pad_array({"rows": 0, "cols": 2, "pitch_mm": 1.0, "pad_diameter_mm": 0.5})


class TestRegistry:
    def test_builtin_generators_registered(self):
        assert set(LAYOUT_GENERATORS) >= {"microstrip", "patch_antenna", "via_fence", "pad_array"}

    def test_dispatch_and_unknown(self):
        layout = generate_layout("microstrip", {"width_mm": 0.5, "length_mm": 5.0})
        assert layout.name == "microstrip"
        with pytest.raises(ValueError, match="未知版图生成器"):
            generate_layout("waveguide", {})

    def test_duplicate_registration_rejected(self):
        def factory(_params):
            return generate_layout("microstrip", {"width_mm": 0.1, "length_mm": 1.0})

        with pytest.raises(ValueError, match="已注册"):
            register_layout_generator("microstrip", factory)


@pytest.mark.parametrize("fmt", LAYOUT_INTERCHANGE_FORMATS)
@pytest.mark.parametrize(
    "kind",
    ["microstrip", "patch_antenna", "via_fence", "pad_array"],
)
def test_generated_layouts_roundtrip_lossless(tmp_path, kind, fmt):
    """B5×B2 合并验收：每个参数化生成器产物经四格式往返无损（delta==0.0）。"""
    params = {
        "microstrip": {
            "width_mm": 0.25,
            "length_mm": 10.0,
            "via_fence": {"pitch_mm": 2.5, "pad_diameter_mm": 0.6, "drill_diameter_mm": 0.3},
        },
        "patch_antenna": {
            "patch_width_mm": 10.0,
            "patch_length_mm": 7.0,
            "feed_width_mm": 0.3,
            "feed_length_mm": 4.0,
        },
        "via_fence": {
            "points": [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0]],
            "pitch_mm": 2.0,
            "pad_diameter_mm": 0.6,
            "drill_diameter_mm": 0.3,
        },
        "pad_array": {"rows": 2, "cols": 3, "pitch_mm": 1.0, "pad_diameter_mm": 0.5},
    }[kind]
    layout = generate_layout(kind, params)
    verdict = verify_round_trip(layout, fmt, tmp_path)
    assert verdict["lossless"] is True, f"{kind}/{fmt} delta={verdict['delta']}"
