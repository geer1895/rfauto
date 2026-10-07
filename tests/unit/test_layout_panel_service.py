"""LC-8 拼板闭式面测试（席D3）。

裁判纪律（#118/#300：≥2 独立基准，禁自我推导自证）：

- 面板算术：显式手算期望值 + **蒙特卡洛面积采样独立复核利用率**
  （随机点落在板矩形内的频率 → 利用率，与闭式比值独立同源）；
- V 槽几何：三角恒等回代（atan(s/2d)=θ/2、web=t−2d）+ 1/3 比例锚；
- 出处值：0.075/0.125 in 换算（VSE 原文）精确到浮点；
- 邮票孔：孔心落缝中线（解析位置）+ 计数守恒。
"""

from __future__ import annotations

import math
import random

import pytest

from rfauto.service.layout_panel_service import (
    TAB_MIN_COMPONENT_CLEARANCE_MM,
    VSCORE_MIN_COMPONENT_CLEARANCE_MM,
    fiducial_layout,
    panelize,
    vcut_geometry,
)


class TestVcutGeometry:
    def test_web_one_third_anchor(self):
        # 模块出处锚：web=板厚 1/3（HopetimePCB+行业指南）
        g = vcut_geometry(1.6)
        assert g["web_mm"] == pytest.approx(1.6 / 3.0)
        assert g["web_ratio"] == pytest.approx(1.0 / 3.0)

    def test_trig_identity_roundtrip(self):
        # 独立基准：atan 回代恒等式 s=2d·tan(θ/2) → θ=2·atan(s/(2d))
        for t in (0.6, 1.0, 1.6, 2.0):
            for angle in (30.0, 45.0, 60.0):
                g = vcut_geometry(t, angle_deg=angle)
                d, s = g["depth_per_side_mm"], g["surface_opening_mm"]
                assert g["web_mm"] == pytest.approx(t - 2.0 * d)
                assert 2.0 * math.degrees(math.atan(s / (2.0 * d))) == \
                    pytest.approx(angle, abs=1e-9)

    def test_web_ratio_zero_full_cut(self):
        # web_ratio=0 → 全切透（web=0、面开口=t·tan(θ/2)）
        g = vcut_geometry(2.0, web_ratio=0.0, angle_deg=45.0)
        assert g["web_mm"] == 0.0
        assert g["surface_opening_mm"] == pytest.approx(2.0 * math.tan(
            math.radians(22.5)))

    def test_invalid_args(self):
        with pytest.raises(ValueError, match="正"):
            vcut_geometry(0.0)
        with pytest.raises(ValueError, match="web_ratio"):
            vcut_geometry(1.6, web_ratio=1.0)
        with pytest.raises(ValueError, match="angle_deg"):
            vcut_geometry(1.6, angle_deg=180.0)


class TestPanelize:
    def test_2x2_vcut_hand_arithmetic(self):
        r = panelize(
            50.0, 40.0, cols=2, rows=2, separation="vcut",
            edge_rail_mm=5.0, board_gap_mm=2.0, board_thickness_mm=1.6)
        assert r["ok"] is True
        # 手算：W=5+2*50+2+5=112，H=5+2*40+2+5=92
        assert r["panel"]["w_mm"] == pytest.approx(112.0)
        assert r["panel"]["h_mm"] == pytest.approx(92.0)
        assert r["panel"]["area_mm2"] == pytest.approx(112.0 * 92.0)
        assert r["n_boards"] == 4
        util = 4 * 50.0 * 40.0 / (112.0 * 92.0)
        assert r["utilization"] == pytest.approx(util)
        # V 槽线位置：内部缝在 rail+第一列板宽+半 gap
        assert r["separation_spec"]["vcut_lines_x_mm"] == \
            pytest.approx([5.0 + 50.0 + 1.0])
        assert r["separation_spec"]["vcut_lines_y_mm"] == \
            pytest.approx([5.0 + 40.0 + 1.0])
        assert r["separation_spec"]["web_mm"] == pytest.approx(1.6 / 3.0)

    def test_utilization_monte_carlo_independent(self):
        # 独立基准：均匀撒点计数落板频率 ≈ 闭式利用率（同一几何两路径）
        r = panelize(
            30.0, 20.0, cols=3, rows=2, separation="vcut",
            edge_rail_mm=4.0, board_gap_mm=1.5)
        assert r["ok"] is True
        rng = random.Random(20261003)
        w, h = r["panel"]["w_mm"], r["panel"]["h_mm"]
        n_hit = 0
        n_tot = 200_000
        rects = [(x, y, x + 30.0, y + 20.0) for x, y in r["board_origins"]]
        for _ in range(n_tot):
            px, py = rng.uniform(0.0, w), rng.uniform(0.0, h)
            if any(x0 <= px <= x1 and y0 <= py <= y1
                   for x0, y0, x1, y1 in rects):
                n_hit += 1
        assert n_hit / n_tot == pytest.approx(r["utilization"], abs=5e-3)

    def test_single_board_no_rail_utilization_one(self):
        # 1×1 零 rail 零 gap → 利用率恒等 1（退化守恒锚）
        r = panelize(10.0, 10.0, edge_rail_mm=0.0, board_gap_mm=0.0)
        assert r["ok"] is True
        assert r["utilization"] == pytest.approx(1.0)

    def test_utilization_monotone_in_rail(self):
        # rail 加宽 → 利用率单调降（方向性守卫）
        utils = [
            panelize(50.0, 40.0, edge_rail_mm=r)["utilization"]
            for r in (0.0, 5.0, 10.0)
        ]
        assert utils[0] > utils[1] > utils[2]

    def test_tab_positions_on_seam_midline(self):
        r = panelize(
            40.0, 30.0, cols=2, rows=1, separation="tab",
            edge_rail_mm=5.0, board_gap_mm=0.5, tab_holes=3,
            tab_len_mm=4.0, tabs_per_edge=2, fiducials=False)
        assert r["ok"] is True
        spec = r["separation_spec"]
        # 单条竖缝中线 x=5+40+0.25=45.25；孔心 x 恒等
        seam_x = 5.0 + 40.0 + 0.25
        for x, _y in spec["hole_centers_mm"]:
            assert x == pytest.approx(seam_x)
        # 计数守恒：竖缝 1×(行 1×每边 2 桥×每桥 3 孔)=6
        assert len(spec["hole_centers_mm"]) == 1 * 1 * 2 * 3

    def test_tab_gap_zero_rejected(self):
        r = panelize(40.0, 30.0, separation="tab", board_gap_mm=0.0)
        assert r["ok"] is False
        assert any("board_gap_mm" in e for e in r["errors"])

    def test_clearance_constants_inch_source(self):
        # VSE 原文：0.075 in / 0.125 in → mm 精确换算
        assert pytest.approx(1.905) == VSCORE_MIN_COMPONENT_CLEARANCE_MM
        assert pytest.approx(3.175) == TAB_MIN_COMPONENT_CLEARANCE_MM

    def test_fiducials_default_three_asymmetric(self):
        r = panelize(50.0, 40.0)
        fid = r["fiducials"]
        assert len(fid) == 3
        xs = [p["x_mm"] for p in fid]
        ys = [p["y_mm"] for p in fid]
        # 非共线：三点三角形面积非零
        area = abs((xs[1] - xs[0]) * (ys[2] - ys[0])
                   - (xs[2] - xs[0]) * (ys[1] - ys[0]))
        assert area > 0.0
        # 不对称：无右下角点（防反插）
        corners = {(round(x), round(y)) for x, y in zip(xs, ys, strict=True)}
        assert (round(r["panel"]["w_mm"] - 3.0),
                round(r["panel"]["h_mm"] - 3.0)) not in corners

    def test_fiducial_inset_too_large_rejected(self):
        with pytest.raises(ValueError, match="inset"):
            fiducial_layout(10.0, 10.0, inset_mm=6.0)

    def test_error_envelope_bad_args(self):
        r = panelize(50.0, -1.0)
        assert r["ok"] is False
        assert r["errors"]
        r2 = panelize(50.0, 40.0, separation="laser")
        assert r2["ok"] is False
        r3 = panelize(50.0, 40.0, cols=0)
        assert r3["ok"] is False

    def test_vcut_bad_thickness_error(self):
        r = panelize(50.0, 40.0, board_thickness_mm=0.0)
        assert r["ok"] is False
