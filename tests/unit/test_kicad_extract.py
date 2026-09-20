"""B6 stage-1 KiCad PCB→EM 提取器测试：往返锚 + 错误路径 + JSON 契约。

真机路径依赖 KiCad 自带 Python（子进程惯例，硬规则 2——项目 venv 不碰
pcbnew）；KiCad 缺失时走 skipif 降级（同 test_kicad_cli 离线口径）。
单元换算口径：KiCad 内部单位 nm，1e6 nm = 1 mm，生成参数经
int(x*1e6) 无损写入，提取侧 nm/1e6 还原——往返容差取 1e-6 mm（=1nm）。
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from rfauto.adapters.kicad_extract import (
    _BUILD_SCRIPT_TEMPLATE,
    _FILL_SCRIPT_TEMPLATE,
    DEMO_BOARD_MM,
    DEMO_ER,
    DEMO_GAP_MM,
    DEMO_LINE_LEN_MM,
    DEMO_PAD_H_MM,
    DEMO_PAD_W_MM,
    DEMO_VIA_DRILL_MM,
    DEMO_VIA_PAD_MM,
    DEMO_VIA_XS_MM,
    DEMO_VIA_Y_MM,
    DEMO_W_MM,
    KICAD_PYTHON,
    _aggregate_traces,
    _parse_footprints,
    _parse_stackup,
    _parse_zones,
    build_demo_cpwg_pcb,
    extract_pcb,
)

KICAD_AVAILABLE = Path(KICAD_PYTHON).exists()
TOL = 1e-6  # mm（KiCad nm 整数无损换算，1e-6 mm = 1 nm）

requires_kicad = pytest.mark.skipif(
    not KICAD_AVAILABLE, reason="KiCad Python 不存在（离线降级）")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    """构建一次 demo 板 + 提取一次（子进程 ~2s，避免逐用例重复开销）。"""
    out = tmp_path_factory.mktemp("kicad_extract") / "demo_cpwg.kicad_pcb"
    build = build_demo_cpwg_pcb(out)
    ext = extract_pcb(out) if build["success"] else {"ok": False, "errors": []}
    return {"build": build, "ext": ext, "path": out}


@pytest.fixture(scope="module")
def demo_filled(tmp_path_factory):
    """opt-in fill 腿：填充 demo 板 + 提取（B6 stage-2 深化往返锚）。"""
    out = (tmp_path_factory.mktemp("kicad_extract_fill")
           / "demo_cpwg_filled.kicad_pcb")
    build = build_demo_cpwg_pcb(out, fill_zones=True)
    ext = (extract_pcb(out) if build["success"]
           else {"ok": False, "errors": []})
    return {"build": build, "ext": ext, "path": out}


def point_in_polys_mm(x: float, y: float,
                      fill_polys: list[dict]) -> bool:
    """填充纹理点归属（even-odd 含孔洞判定）：外轮廓内且不在任何孔内。

    KiCad 侧 Unfracture 还原孔洞后 outer 已不含走廊绕行——孔洞判定
    双保险，对合成/真实填充纹理同口径。
    """
    def in_ring(ring: list[list[float]]) -> bool:
        inside = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < x_cross:
                    inside = not inside
        return inside

    for poly in fill_polys:
        outer = poly["outer_mm"]
        if in_ring(outer) and not any(in_ring(h)
                                      for h in poly.get("holes_mm", [])):
            return True
    return False


def _rf_trace(ext: dict) -> dict:
    traces = [t for t in ext["traces"] if t["net"] == "RF1"]
    assert len(traces) == 1, f"RF1 主线应恰一条，得 {len(traces)}"
    return traces[0]


class TestRoundTripAnchor:
    """往返锚：生成参数 == 提取值（KiCad 10.0.6 真机子进程）。"""

    @requires_kicad
    def test_demo_board_builds(self, demo):
        assert demo["build"]["success"], demo["build"]
        assert Path(demo["build"]["output_path"]).exists()

    @requires_kicad
    def test_extraction_ok(self, demo):
        assert demo["ext"]["ok"] is True, demo["ext"]

    @requires_kicad
    def test_trace_width_length_anchor(self, demo):
        trace = _rf_trace(demo["ext"])
        assert trace["width_mm"] == pytest.approx(DEMO_W_MM, abs=TOL)
        assert trace["length_mm"] == pytest.approx(DEMO_LINE_LEN_MM, abs=TOL)

    @requires_kicad
    def test_trace_geometry_anchor(self, demo):
        trace = _rf_trace(demo["ext"])
        assert trace["layer"] == "F.Cu"
        pts = trace["points_mm"]
        assert len(pts) == 2
        assert pts[0][0] == pytest.approx(10.0, abs=TOL)
        assert pts[0][1] == pytest.approx(15.0, abs=TOL)
        assert pts[1][0] == pytest.approx(10.0 + DEMO_LINE_LEN_MM, abs=TOL)
        assert pts[1][1] == pytest.approx(15.0, abs=TOL)

    @requires_kicad
    def test_via_anchor(self, demo):
        vias = [v for v in demo["ext"]["vias"] if v["net"] == "GND"]
        assert len(vias) == len(DEMO_VIA_XS_MM)
        assert sorted(v["x_mm"] for v in vias) == pytest.approx(
            sorted(DEMO_VIA_XS_MM), abs=TOL)
        for v in vias:
            assert v["y_mm"] == pytest.approx(DEMO_VIA_Y_MM, abs=TOL)
            assert v["drill_mm"] == pytest.approx(DEMO_VIA_DRILL_MM, abs=TOL)
            assert v["pad_diameter_mm"] == pytest.approx(
                DEMO_VIA_PAD_MM, abs=TOL)

    @requires_kicad
    def test_outline_anchor(self, demo):
        outline = demo["ext"]["outline"]
        assert outline["min_mm"] == pytest.approx([0.0, 0.0], abs=TOL)
        assert outline["max_mm"] == pytest.approx(list(DEMO_BOARD_MM), abs=TOL)
        assert outline["width_mm"] == pytest.approx(DEMO_BOARD_MM[0], abs=TOL)
        assert outline["height_mm"] == pytest.approx(DEMO_BOARD_MM[1], abs=TOL)

    @requires_kicad
    def test_stackup_anchor(self, demo):
        board = demo["ext"]["board"]
        assert board["layer_count"] == 2
        assert board["copper_layers"] == ["F.Cu", "B.Cu"]
        # 叠层总和：芯板 0.508 + 两面铜 0.035×2（KiCad 按叠层重算板厚）
        assert board["thickness_mm"] == pytest.approx(0.578, abs=TOL)
        assert board["substrate_er"] == pytest.approx(DEMO_ER, abs=1e-9)

    @requires_kicad
    def test_gap_note_in_board(self, demo):
        # CPWG 缝宽以 zone clearance=gap_mm 形式写在板内（stage-2 起
        # 提取契约读 zone，service 层 gap 可出自板内事实）。
        note = demo["ext"]["board"]["substrate_note"]
        assert isinstance(note, str) and note


class TestJsonContract:
    """JSON 契约结构（成功侧完整键集）。"""

    @requires_kicad
    def test_success_keys(self, demo):
        ext = demo["ext"]
        assert set(ext.keys()) == {"ok", "board", "traces", "vias", "outline",
                                   "zones", "footprints"}
        assert ext["ok"] is True

    @requires_kicad
    def test_board_keys(self, demo):
        assert set(demo["ext"]["board"].keys()) == {
            "kicad_version", "layer_count", "copper_layers", "thickness_mm",
            "substrate_er", "substrate_note", "stackup",
        }
        assert demo["ext"]["board"]["kicad_version"].startswith("10.")

    @requires_kicad
    def test_trace_keys(self, demo):
        trace = _rf_trace(demo["ext"])
        assert set(trace.keys()) == {
            "net", "layer", "width_mm", "length_mm", "points_mm"}

    @requires_kicad
    def test_via_and_outline_keys(self, demo):
        via = demo["ext"]["vias"][0]
        assert set(via.keys()) == {
            "net", "x_mm", "y_mm", "pad_diameter_mm", "drill_mm"}
        assert set(demo["ext"]["outline"].keys()) == {
            "min_mm", "max_mm", "width_mm", "height_mm"}


class TestExtractErrors:
    """错误路径：ok=False + errors（部分用例离线确定性，不依赖真机）。"""

    def test_nonexistent_file(self, tmp_path):
        ext = extract_pcb(tmp_path / "nope.kicad_pcb")
        assert ext["ok"] is False
        assert ext["errors"]
        assert all(isinstance(e, str) for e in ext["errors"])

    @requires_kicad
    def test_bad_file(self, tmp_path):
        bad = tmp_path / "bad.kicad_pcb"
        bad.write_text("(kicad_pcb (version 20260206) garbage", encoding="utf-8")
        ext = extract_pcb(bad)
        assert ext["ok"] is False
        assert ext["errors"]

    def test_kicad_python_missing(self, tmp_path):
        dummy = tmp_path / "dummy.kicad_pcb"
        dummy.write_text("()", encoding="utf-8")
        fake_py = tmp_path / "no_kicad" / "python.exe"
        ext = extract_pcb(dummy, kicad_python=str(fake_py))
        assert ext["ok"] is False
        assert any("不存在" in e for e in ext["errors"])

    @requires_kicad
    def test_build_with_missing_python(self, tmp_path):
        fake_py = tmp_path / "no_kicad" / "python.exe"
        result = build_demo_cpwg_pcb(
            tmp_path / "x.kicad_pcb", kicad_python=str(fake_py))
        assert result["success"] is False
        assert result["output_path"] is None


class TestZoneExtraction:
    """B6 stage-2 zone 深化往返锚（KiCad 10.0.6 真机子进程）。

    坑（2026-09-12 探针实测）：ZONE 自带 GetLayerName() 恒返回 "F.Cu"
    （B.Cu zone 亦然），提取层名必须走 board.GetLayerName(GetLayer())——
    B.Cu 锚就是这条坑的回归绊线。
    """

    @requires_kicad
    def test_two_gnd_zones(self, demo):
        zones = [z for z in demo["ext"]["zones"] if z["net"] == "GND"]
        assert len(zones) == 2
        assert sorted(z["layer"] for z in zones) == ["B.Cu", "F.Cu"]

    @requires_kicad
    def test_zone_clearance_is_cpwg_gap(self, demo):
        # CPWG 缝宽事实源：F.Cu GND zone clearance == gap_mm
        fz = next(z for z in demo["ext"]["zones"] if z["layer"] == "F.Cu")
        assert fz["clearance_mm"] == pytest.approx(DEMO_GAP_MM, abs=TOL)
        assert fz["min_thickness_mm"] == pytest.approx(0.1, abs=TOL)
        assert fz["filled"] is False
        assert fz["priority"] == 0

    @requires_kicad
    def test_zone_outline_anchor(self, demo):
        # 板框外扩 2mm 的 GND 轮廓（生成侧 AppendCorner 写 zone 自有 poly）
        fz = next(z for z in demo["ext"]["zones"] if z["layer"] == "F.Cu")
        pts = fz["outline_points_mm"]
        assert fz["n_outlines"] == 1
        assert len(pts) == 4
        assert pts[0] == pytest.approx([-2.0, -2.0], abs=TOL)
        assert pts[1] == pytest.approx(
            [DEMO_BOARD_MM[0] + 2.0, -2.0], abs=TOL)
        assert pts[2] == pytest.approx(
            [DEMO_BOARD_MM[0] + 2.0, DEMO_BOARD_MM[1] + 2.0], abs=TOL)
        assert pts[3] == pytest.approx([-2.0, DEMO_BOARD_MM[1] + 2.0],
                                       abs=TOL)

    @requires_kicad
    def test_zone_keys(self, demo):
        zone = demo["ext"]["zones"][0]
        assert set(zone.keys()) == {
            "net", "layer", "layers", "clearance_mm", "min_thickness_mm",
            "priority", "filled", "outline_points_mm", "n_outlines",
            # B6 stage-2 深化三键（2026-09-15）：全部设计轮廓/填充孔洞/
            # 填充纹理（cpw_design_from_extract 兼容：旧键保留）
            "outlines_mm", "holes_mm", "filled_polys_mm"}


class TestFillExtraction:
    """B6 stage-2 深化：填充纹理往返锚（KiCad 10.0.6 真机，opt-in fill 腿）。

    实测口径（2026-09-15，判据按现实修正）：
    - KiCad 填充多边形以断裂（fractured）形式存储，孔洞=外轮廓零宽
      狭缝，HoleCount 恒 0——提取侧拷贝后 Unfracture 才还原孔洞；
    - demo 板 F.Cu 填充 = 1 外轮廓 + **1 孔洞**（主线走廊 + 两端射焊盘
      cutout 空间相连，ZONE_FILLER 先并障碍物再切 → 合并为一个走廊孔；
      原判据"孔洞≥2"对本 demo 几何物理上不可达，如实按 ≥1 + 走廊
      包住主线与焊盘钉住）；B.Cu 实平面 0 孔；
    - 走廊边到主线边实测缝 = clearance + KiCad 填充圆角补偿 ≈0.5µm
      （0.2005 vs 0.2，±0.01mm 判据内）。
    """

    # KiCad 10.0.6 实测走廊孔包围盒（mm）：x=pad 边 9.6/50.4 外扩 0.225，
    # y=主线边 15±0.4245 外扩 0.2005（顶点 nm 整数，1e-6 mm 精度）
    CORRIDOR_BBOX_MM: ClassVar[tuple[float, float, float, float]] = (
        9.375, 14.375, 50.625, 15.625)

    @requires_kicad
    def test_filled_board_builds(self, demo_filled):
        build = demo_filled["build"]
        assert build["success"], build
        assert build["filled"] is True
        assert "填充" in build["message"]
        assert demo_filled["ext"]["ok"] is True, demo_filled["ext"]

    @requires_kicad
    def test_f_cu_fill_one_poly_one_corridor_hole(self, demo_filled):
        fz = next(z for z in demo_filled["ext"]["zones"]
                  if z["layer"] == "F.Cu")
        assert fz["filled"] is True
        assert len(fz["filled_polys_mm"]) == 1
        fp = fz["filled_polys_mm"][0]
        assert len(fp["outer_mm"]) >= 4
        # 孔洞≥1（走廊+焊盘 cutout 合并为一孔，见类 docstring）
        assert len(fp["holes_mm"]) >= 1
        assert fz["holes_mm"] == fp["holes_mm"]
        hole = fp["holes_mm"][0]
        xs = [p[0] for p in hole]
        ys = [p[1] for p in hole]
        x0, y0, x1, y1 = self.CORRIDOR_BBOX_MM
        assert (min(xs), min(ys), max(xs), max(ys)) == pytest.approx(
            (x0, y0, x1, y1), abs=TOL)
        # 走廊孔包住主线（10..50）与两端射焊盘（9.6..50.4）
        assert min(xs) < 10.0 - DEMO_PAD_W_MM / 2
        assert max(xs) > 10.0 + DEMO_LINE_LEN_MM + DEMO_PAD_W_MM / 2

    @requires_kicad
    def test_b_cu_fill_solid(self, demo_filled):
        bz = next(z for z in demo_filled["ext"]["zones"]
                  if z["layer"] == "B.Cu")
        assert bz["filled"] is True
        assert len(bz["filled_polys_mm"]) == 1
        assert bz["holes_mm"] == []  # 地过孔同网，不切孔

    @requires_kicad
    def test_fill_even_odd_probe_points(self, demo_filled):
        """填充含板角探针点、不含主线中线点与焊盘中心（even-odd 含孔洞）。"""
        fz = next(z for z in demo_filled["ext"]["zones"]
                  if z["layer"] == "F.Cu")
        polys = fz["filled_polys_mm"]
        assert point_in_polys_mm(5.0, 5.0, polys) is True     # 板角探针
        assert point_in_polys_mm(30.0, 15.0, polys) is False  # 主线中线
        assert point_in_polys_mm(10.0, 15.0, polys) is False  # 焊盘 1 中心
        assert point_in_polys_mm(50.0, 15.0, polys) is False  # 焊盘 2 中心
        # 填充被板边铜距 0.5mm 收缩：板外 (-1,-1) 不在填充内
        assert point_in_polys_mm(-1.0, -1.0, polys) is False

    @requires_kicad
    def test_measured_fill_gap_matches_clearance(self, demo_filled):
        """实测 fill gap == clearance ±0.01mm（KiCad 填充圆角补偿 ≤0.5µm）。"""
        from rfauto.service.kicad_em_service import (
            GAP_CONSISTENCY_TOL_MM,
            board_facts_from_extract,
        )

        facts = board_facts_from_extract(demo_filled["ext"])
        assert facts["gap_source"] == "measured_fill"
        assert facts["gap_clearance_mm"] == pytest.approx(DEMO_GAP_MM, abs=TOL)
        assert facts["gap_measured_mm"] == pytest.approx(
            DEMO_GAP_MM, abs=GAP_CONSISTENCY_TOL_MM)
        assert facts["gap_consistent"] is True
        assert facts["gap_mm"] == facts["gap_measured_mm"]

    @requires_kicad
    def test_unfilled_board_reports_empty_fill(self, demo):
        """未填充板（默认 builder）：filled=False 且填充纹理为空，不臆造。"""
        for z in demo["ext"]["zones"]:
            assert z["filled"] is False
            assert z["filled_polys_mm"] == []
            assert z["holes_mm"] == []
        assert demo["build"]["filled"] is False


class TestPadExtraction:
    """B6 stage-2 footprint/pad 往返锚（KiCad 10.0.6 真机子进程）。

    demo 板端射焊盘：SMD 属性 + LSET(F.Cu)——默认 PTH 会把铜层铺到
    全铜层（探针实测 F.Cu+B.Cu），SMD 才钉得住单面。
    """

    @requires_kicad
    def test_one_footprint_two_pads(self, demo):
        fps = demo["ext"]["footprints"]
        assert len(fps) == 1
        fp = fps[0]
        assert fp["reference"] == "X1"
        assert fp["value"] == "CPWG_LAUNCH"
        assert fp["x_mm"] == pytest.approx(10.0, abs=TOL)
        assert fp["y_mm"] == pytest.approx(15.0, abs=TOL)
        assert len(fp["pads"]) == 2

    @requires_kicad
    def test_pad_geometry_anchor(self, demo):
        pads = demo["ext"]["footprints"][0]["pads"]
        xs = sorted(p["x_mm"] for p in pads)
        assert xs == pytest.approx([10.0, 10.0 + DEMO_LINE_LEN_MM], abs=TOL)
        for p in pads:
            assert p["net"] == "RF1"
            assert p["number"] in {"1", "2"}
            assert p["w_mm"] == pytest.approx(DEMO_PAD_W_MM, abs=TOL)
            assert p["h_mm"] == pytest.approx(DEMO_PAD_H_MM, abs=TOL)
            assert p["y_mm"] == pytest.approx(15.0, abs=TOL)
            assert p["layers"] == ["F.Cu"]  # SMD 单面（PTH 会带 B.Cu）

    @requires_kicad
    def test_pad_keys(self, demo):
        pad = demo["ext"]["footprints"][0]["pads"][0]
        assert set(pad.keys()) == {
            "number", "net", "shape", "x_mm", "y_mm", "w_mm", "h_mm",
            "layers"}


class TestParseZonesFootprints:
    """zone/footprint 契约解析（纯项目侧，无子进程）。"""

    RAW_ZONE: ClassVar[dict] = {
        "net": "GND", "layer_id": 2, "layer": "B.Cu", "layers": ["B.Cu"],
        "clearance_nm": 200_000, "min_thickness_nm": 100_000,
        "priority": 3, "filled": True,
        "outlines_nm": [[[0, 0], [62_000_000, 0],
                         [62_000_000, 32_000_000], [0, 32_000_000]],
                        [[1, 1], [2, 1], [2, 2]]],
        "filled_polys_nm": [
            {"outer_nm": [[0, 0], [60_000_000, 0], [60_000_000, 30_000_000],
                          [0, 30_000_000]],
             "holes_nm": [[[9_375_000, 14_375_000], [50_625_000, 14_375_000],
                           [50_625_000, 15_625_000],
                           [9_375_000, 15_625_000]]]},
            {"outer_nm": [[70_000_000, 0], [80_000_000, 0],
                          [80_000_000, 10_000_000]],
             "holes_nm": []},
        ],
    }

    def test_zone_parse_mm_and_ordering(self):
        out = _parse_zones([self.RAW_ZONE,
                            {**self.RAW_ZONE, "net": "AGND"}])
        assert out[0]["net"] == "AGND"  # 按 (net, layer, 首点) 排序
        z = out[1]
        assert z["clearance_mm"] == pytest.approx(0.2, abs=TOL)
        assert z["min_thickness_mm"] == pytest.approx(0.1, abs=TOL)
        assert z["priority"] == 3 and z["filled"] is True
        assert z["outline_points_mm"][0] == [0.0, 0.0]
        assert z["n_outlines"] == 2  # 多轮廓只取首轮廓点列（旧键兼容）
        # stage-2 深化：全部设计轮廓进 outlines_mm
        assert len(z["outlines_mm"]) == 2
        for got, want in zip(z["outlines_mm"][1],
                             [[1e-6, 1e-6], [2e-6, 1e-6], [2e-6, 2e-6]],
                             strict=True):
            assert got == pytest.approx(want, abs=1e-12)  # 1nm = 1e-6mm
        # 填充纹理：outer + holes 逐点 nm→mm；holes_mm 跨填充轮廓展平
        assert len(z["filled_polys_mm"]) == 2
        fp0 = z["filled_polys_mm"][0]
        assert fp0["outer_mm"][1] == [60.0, 0.0]
        assert fp0["holes_mm"][0][0] == pytest.approx([9.375, 14.375], abs=TOL)
        assert z["holes_mm"] == fp0["holes_mm"]  # 仅 poly0 有孔

    def test_zone_parse_without_fill_keys(self):
        """无 filled_polys_nm 的旧产物（stage-1 原始件）解析不炸。"""
        legacy = {k: v for k, v in self.RAW_ZONE.items()
                  if k != "filled_polys_nm"}
        out = _parse_zones([legacy])
        assert out[0]["filled_polys_mm"] == []
        assert out[0]["holes_mm"] == []
        assert len(out[0]["outlines_mm"]) == 2  # 设计轮廓照常

    def test_zone_unset_clearance_is_none(self):
        out = _parse_zones([{**self.RAW_ZONE, "clearance_nm": -1}])
        assert out[0]["clearance_mm"] is None

    RAW_FP: ClassVar[dict] = {
        "reference": "X1", "value": "PADDEMO",
        "x_nm": 10_000_000, "y_nm": 15_000_000,
        "pads": [{"number": "1", "net": "RF1", "shape": 1,
                  "x_nm": 10_000_000, "y_nm": 15_000_000,
                  "w_nm": 800_000, "h_nm": 600_000, "layers": ["F.Cu"]}],
    }

    def test_footprint_parse(self):
        out = _parse_footprints([self.RAW_FP])
        fp = out[0]
        assert fp["x_mm"] == pytest.approx(10.0, abs=TOL)
        pad = fp["pads"][0]
        assert pad["w_mm"] == pytest.approx(0.8, abs=TOL)
        assert pad["h_mm"] == pytest.approx(0.6, abs=TOL)
        assert pad["layers"] == ["F.Cu"]

    def test_empty_inputs(self):
        assert _parse_zones([]) == []
        assert _parse_footprints([]) == []


class TestAggregateTraces:
    """折线聚合（纯项目侧，无子进程）：同 net/层/宽 端点重合才拼。"""

    @staticmethod
    def _seg(net, x1, y1, x2, y2, width_nm=849_000, layer="F.Cu"):
        return {"net": net, "layer": layer, "width_nm": width_nm,
                "x1_nm": x1, "y1_nm": y1, "x2_nm": x2, "y2_nm": y2,
                "length_nm": 0}

    def test_collinear_chain(self):
        segs = [self._seg("RF1", 0, 0, 10_000_000, 0),
                self._seg("RF1", 10_000_000, 0, 20_000_000, 0)]
        traces = _aggregate_traces(segs)
        assert len(traces) == 1
        assert traces[0]["points_mm"] == [[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]]
        assert traces[0]["length_mm"] == pytest.approx(20.0, abs=TOL)

    def test_reverse_direction_chains(self):
        segs = [self._seg("RF1", 10_000_000, 0, 0, 0),
                self._seg("RF1", 10_000_000, 0, 20_000_000, 0)]
        traces = _aggregate_traces(segs)
        assert len(traces) == 1
        assert len(traces[0]["points_mm"]) == 3

    def test_disjoint_same_net_stay_separate(self):
        segs = [self._seg("RF1", 0, 0, 10_000_000, 0),
                self._seg("RF1", 15_000_000, 0, 20_000_000, 0)]
        traces = _aggregate_traces(segs)
        assert len(traces) == 2

    def test_cross_net_never_chains(self):
        segs = [self._seg("RF1", 0, 0, 10_000_000, 0),
                self._seg("RF2", 10_000_000, 0, 20_000_000, 0)]
        assert len(_aggregate_traces(segs)) == 2

    def test_cross_width_never_chains(self):
        segs = [self._seg("RF1", 0, 0, 10_000_000, 0, width_nm=849_000),
                self._seg("RF1", 10_000_000, 0, 20_000_000, 0,
                          width_nm=1_113_000)]
        assert len(_aggregate_traces(segs)) == 2

    def test_cross_layer_never_chains(self):
        segs = [self._seg("RF1", 0, 0, 10_000_000, 0, layer="F.Cu"),
                self._seg("RF1", 10_000_000, 0, 20_000_000, 0, layer="B.Cu")]
        assert len(_aggregate_traces(segs)) == 2

    def test_gap_width_value_consistent(self):
        # demo 参数与 cpw 模板名义一致（锚判据同一口径）
        assert DEMO_W_MM == 0.849
        assert DEMO_GAP_MM == 0.2
        assert DEMO_LINE_LEN_MM == 40.0


class TestParseStackup:
    """stackup s-expression 解析（KiCad 10 绑定无 wrapper 的文本路）。"""

    SAMPLE = """
		(setup
		(stackup
			(layer "F.SilkS" (type "Top Silk"))
			(layer "F.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 1" (type "core") (thickness 0.508)
				(epsilon_r 3.66) (loss_tangent 0.0037))
			(layer "B.Cu" (type "copper") (thickness 0.035))
			(copper_finish "None")
		)
		)
	"""

    def test_parse_dielectric(self):
        out = _parse_stackup(self.SAMPLE)
        assert out["er"] == pytest.approx(3.66, abs=1e-9)
        assert len(out["dielectrics"]) == 1
        d = out["dielectrics"][0]
        assert d["name"] == "dielectric 1"
        assert d["thickness_mm"] == pytest.approx(0.508, abs=1e-9)
        assert d["tan_d"] == pytest.approx(0.0037, abs=1e-9)
        assert "stackup" in out["note"]

    def test_no_stackup_returns_none_with_note(self):
        out = _parse_stackup("(kicad_pcb (general (thickness 1.6)))")
        assert out["er"] is None
        assert out["dielectrics"] == []
        assert "无 stackup" in out["note"]

    def test_unbalanced_block_no_crash(self):
        out = _parse_stackup("(setup (stackup (layer \"dielectric 1\"")
        assert out["er"] is None


class TestBuildScriptOwnership:
    """demo 板脚本的 SWIG 归属绊线（离线，秒级）。

    ZONE::SetOutline 裸指针接管 Python 持有的 SHAPE_POLY_SET → 函数返回即
    被释放 → SaveBoard 序列化 zone 读悬空指针（#210 ③ 间歇 0xC0000005 的
    真根因，全量下重试也会耗尽）。轮廓只能经 ZONE::AppendCorner 写 zone
    自有 m_Poly。
    """

    def test_zone_outline_via_append_corner_only(self):
        code_lines = [ln for ln in _BUILD_SCRIPT_TEMPLATE.splitlines()
                      if not ln.lstrip().startswith("#")]
        code = "\n".join(code_lines)
        assert "SetOutline(" not in code
        assert "AppendCorner(" in code

    def test_fill_leg_is_separate_two_arg_subprocess(self):
        """#214 铁律：ZONE_FILLER.Fill 两参（aCheck=False）+ 与建板脚本分离。

        单参 Fill 段错误（10.0.6 实测）；同会话建板+Fill 间歇段错误 →
        fill 腿是独立脚本（LoadBoard 走已保存文件），建板脚本本体不含 Fill。
        """
        fill_code = "\n".join(ln for ln in _FILL_SCRIPT_TEMPLATE.splitlines()
                              if not ln.lstrip().startswith("#"))
        assert "ZONE_FILLER(board).Fill(zones, False)" in fill_code
        assert "LoadBoard(" in fill_code
        build_code = "\n".join(ln for ln in _BUILD_SCRIPT_TEMPLATE.splitlines()
                               if not ln.lstrip().startswith("#"))
        assert "ZONE_FILLER" not in build_code
        assert ".Fill(" not in build_code
