"""kicad_edb_bridge 单元测试：KiCad 提取 dict → EDB spec 桥接（离线合成）。

四条必测路径：正常映射 / 未知层跳过告警 / 空板 / 单位换算；另补
介质缺失占位、多层板 via 层对不确定、失败契约、非法策略、坏几何、
zones 如实告警等诚实性路径。全部合成 KiCad 提取 dict，不依赖
KiCad 子进程。几何断言容差 1e-9（桥接层恒等直传、零算术，理论
上应逐位相等，1e-9 是任务书门口径）。
"""

from __future__ import annotations

import pytest

from rfauto.adapters.kicad_edb_bridge import (
    STACKUP_POLICIES,
    kicad_to_edb_spec,
)

TOL = 1e-9


def _two_layer() -> dict:
    """合成双层板提取产物（extract_pcb 成功契约形态，mm 口径）。"""
    return {
        "ok": True,
        "board": {
            "kicad_version": "10.0.6",
            "layer_count": 2,
            "copper_layers": ["F.Cu", "B.Cu"],  # 层 id 升序 = 物理顶→底
            "thickness_mm": 0.578,
            "substrate_er": 3.66,
            "substrate_note": "er 来自 .kicad_pcb (stackup) s-expression 文本解析",
            "stackup": {"dielectrics": [
                {"name": "dielectric 1", "thickness_mm": 0.508,
                 "er": 3.66, "tan_d": 0.0037},
            ]},
        },
        "traces": [
            {"net": "RF1", "layer": "F.Cu", "width_mm": 0.849,
             "length_mm": 45.0,
             "points_mm": [[10.0, 15.0], [50.0, 15.0], [50.0, 20.0]]},
            {"net": "GND", "layer": "B.Cu", "width_mm": 1.2,
             "length_mm": 5.0,
             "points_mm": [[20.0, 25.0], [25.0, 25.0]]},
        ],
        "vias": [
            {"net": "GND", "x_mm": 12.0, "y_mm": 18.0,
             "pad_diameter_mm": 0.6, "drill_mm": 0.3},
            {"net": "GND", "x_mm": 24.0, "y_mm": 18.0,
             "pad_diameter_mm": 0.6, "drill_mm": 0.3},
        ],
        "outline": {"min_mm": [0.0, 0.0], "max_mm": [60.0, 30.0],
                    "width_mm": 60.0, "height_mm": 30.0},
        "zones": [],
        "footprints": [
            {"reference": "X1", "value": "LAUNCH", "x_mm": 10.0,
             "y_mm": 15.0,
             "pads": [
                 {"number": "1", "net": "RF1", "shape": 1,
                  "x_mm": 10.0, "y_mm": 15.0, "w_mm": 0.8, "h_mm": 0.6,
                  "layers": ["F.Cu"]},
                 {"number": "2", "net": "RF1", "shape": 1,
                  "x_mm": 50.0, "y_mm": 15.0, "w_mm": 0.8, "h_mm": 0.6,
                  "layers": ["F.Cu"]},
             ]},
        ],
    }


def _assert_pt_eq(a: list, b: list) -> None:
    """点列逐点一致（容差 1e-9）。"""
    assert len(a) == len(b)
    for (ax, ay), (bx, by) in zip(a, b, strict=True):
        assert ax == pytest.approx(bx, abs=TOL)
        assert ay == pytest.approx(by, abs=TOL)


class TestNormalMapping:
    """路径 1：双层板正常映射——叠层/走线/过孔/焊盘逐点一致。"""

    def test_spec_ok_and_clean(self):
        spec = kicad_to_edb_spec(_two_layer())
        assert spec["ok"] is True
        assert spec["errors"] == []
        assert spec["warnings"] == []  # 零跳过
        assert spec["units"] == "mm"

    def test_stackup_bottom_to_top(self):
        spec = kicad_to_edb_spec(_two_layer())
        st = spec["stackup"]
        # EDB/pyedb 惯例：index 0 = 底层（B.Cu）
        assert [ly["name"] for ly in st["layers"]] == \
            ["B.Cu", "dielectric 1", "F.Cu"]
        assert [ly["type"] for ly in st["layers"]] == \
            ["copper", "dielectric", "copper"]
        diel = st["layers"][1]
        assert diel["thickness_mm"] == pytest.approx(0.508, abs=TOL)
        assert diel["er"] == pytest.approx(3.66, abs=TOL)
        assert diel["tan_d"] == pytest.approx(0.0037, abs=TOL)
        assert diel["material"] is None  # 材料名不在 KiCad 契约，不编造
        for cu in (st["layers"][0], st["layers"][2]):
            assert cu["thickness_mm"] is None  # 铜厚契约未含，如实 None
        assert st["copper_layer_count"] == 2
        assert st["total_thickness_mm"] == pytest.approx(0.578, abs=TOL)
        assert st["substrate_er"] == pytest.approx(3.66, abs=TOL)
        assert st["dielectric_source"] == "kicad_stackup"
        assert st["order"] == "bottom_to_top"
        # auto 策略=按层序号：映射表显式、同名直通
        assert st["kicad_to_edb_layers"] == {"F.Cu": "F.Cu", "B.Cu": "B.Cu"}

    def test_traces_pointwise_identity(self):
        spec = kicad_to_edb_spec(_two_layer())
        traces = spec["traces"]
        assert len(traces) == 2
        t0 = traces[0]
        assert t0["name"] == "TRACE_0000"
        assert t0["net"] == "RF1"
        assert t0["layer"] == "F.Cu"
        assert t0["width_mm"] == pytest.approx(0.849, abs=TOL)
        _assert_pt_eq(t0["points_mm"], [[10.0, 15.0], [50.0, 15.0],
                                        [50.0, 20.0]])
        t1 = traces[1]
        assert (t1["net"], t1["layer"]) == ("GND", "B.Cu")
        _assert_pt_eq(t1["points_mm"], [[20.0, 25.0], [25.0, 25.0]])

    def test_vias_two_layer_pair_proven(self):
        spec = kicad_to_edb_spec(_two_layer())
        vias = spec["vias"]
        assert len(vias) == 2
        v0 = vias[0]
        assert v0["name"] == "VIA_0000"
        assert v0["net"] == "GND"
        assert v0["x_mm"] == pytest.approx(12.0, abs=TOL)
        assert v0["y_mm"] == pytest.approx(18.0, abs=TOL)
        assert v0["pad_diameter_mm"] == pytest.approx(0.6, abs=TOL)
        assert v0["drill_mm"] == pytest.approx(0.3, abs=TOL)
        # 两层板：via 层对唯一可能 = F.Cu↔B.Cu，可确证（start=顶层侧）
        assert v0["start_layer"] == "F.Cu"
        assert v0["stop_layer"] == "B.Cu"
        assert vias[1]["x_mm"] == pytest.approx(24.0, abs=TOL)

    def test_pads_expanded_from_footprints(self):
        spec = kicad_to_edb_spec(_two_layer())
        pads = spec["pads"]
        assert len(pads) == 2
        p0 = pads[0]
        assert p0["name"] == "X1-1"
        assert p0["reference"] == "X1"
        assert p0["number"] == "1"
        assert p0["net"] == "RF1"
        assert p0["layers"] == ["F.Cu"]
        assert p0["shape_code"] == 1
        assert p0["shape"] == "rectangle"  # KiCad pad_shapes.h 码 1
        assert p0["x_mm"] == pytest.approx(10.0, abs=TOL)
        assert p0["w_mm"] == pytest.approx(0.8, abs=TOL)  # w×h 不等抓轴交换
        assert p0["h_mm"] == pytest.approx(0.6, abs=TOL)

    def test_outline_and_counts(self):
        spec = kicad_to_edb_spec(_two_layer())
        assert spec["outline"]["width_mm"] == pytest.approx(60.0, abs=TOL)
        assert spec["counts"] == {"traces": 2, "vias": 2, "pads": 2,
                                  "warnings": 0}


class TestUnknownLayerSkip:
    """路径 2：未知层跳过 + 告警（绝不静默丢弃）。"""

    def test_unknown_trace_and_pad_layers_warned(self):
        data = _two_layer()
        data["traces"].append(
            {"net": "CLK", "layer": "In6.Cu", "width_mm": 0.2,
             "length_mm": 3.0, "points_mm": [[1.0, 1.0], [4.0, 1.0]]})
        data["footprints"][0]["pads"][1]["layers"] = ["In4.Cu"]
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is True  # 跳过不是失败
        # 未知层 trace/pad 均不入 spec
        assert len(spec["traces"]) == 2
        assert all(t["layer"] != "In6.Cu" for t in spec["traces"])
        assert len(spec["pads"]) == 1
        assert spec["pads"][0]["number"] == "1"
        # 告警逐条点名（层名 + 元素定位 + 跳过语义）
        joined = "\n".join(spec["warnings"])
        assert "In6.Cu" in joined and "trace[2]" in joined
        assert "In4.Cu" in joined and "X1-2" in joined
        assert "跳过" in joined
        assert spec["counts"]["warnings"] == len(spec["warnings"])
        assert spec["counts"]["traces"] == 2
        assert spec["counts"]["pads"] == 1


class TestEmptyBoard:
    """路径 3：空板（零走线/零过孔/零焊盘）——ok 且零告警。"""

    def test_empty_lists_map_clean(self):
        data = _two_layer()
        data["traces"] = []
        data["vias"] = []
        data["footprints"] = []
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is True
        assert spec["warnings"] == []
        assert spec["traces"] == []
        assert spec["vias"] == []
        assert spec["pads"] == []
        assert spec["counts"] == {"traces": 0, "vias": 0, "pads": 0,
                                  "warnings": 0}
        # 叠层映射与板框不因空板丢失
        assert [ly["name"] for ly in spec["stackup"]["layers"]] == \
            ["B.Cu", "dielectric 1", "F.Cu"]
        assert spec["outline"]["height_mm"] == pytest.approx(30.0, abs=TOL)


class TestUnitDiscipline:
    """路径 4：单位纪律——KiCad nm 精度值经 /1e6 进桥接，恒等直传。"""

    def test_nm_precision_values_pass_through(self):
        # 提取侧 _nm_to_mm = nm/1e6（KiCad 内部 1e6 nm = 1 mm）；
        # 桥接层零算术直传 → spec 值应与 nm/1e6 逐位相等（== 最强断言，
        # 1e-9 为任务书门口径）。
        w_nm = 2345678
        x_nm, y_nm = 12345678, 87654321
        drill_nm, pad_nm = 300000, 600000
        data = _two_layer()
        data["traces"] = [{
            "net": "RF1", "layer": "F.Cu", "width_mm": w_nm / 1e6,
            "length_mm": 40.0,
            "points_mm": [[x_nm / 1e6, y_nm / 1e6],
                          [(x_nm + 40_000_000) / 1e6, y_nm / 1e6]],
        }]
        data["vias"] = [{"net": "GND", "x_mm": 12.0, "y_mm": 18.0,
                         "pad_diameter_mm": pad_nm / 1e6,
                         "drill_mm": drill_nm / 1e6}]
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is True and spec["warnings"] == []
        t = spec["traces"][0]
        assert t["width_mm"] == w_nm / 1e6  # 2.345678 mm
        assert t["width_mm"] == pytest.approx(2.345678, abs=TOL)
        _assert_pt_eq(t["points_mm"],
                      [[x_nm / 1e6, y_nm / 1e6], [52.345678, y_nm / 1e6]])
        v = spec["vias"][0]
        assert v["drill_mm"] == drill_nm / 1e6 == 0.3
        assert v["pad_diameter_mm"] == pad_nm / 1e6 == 0.6
        assert v["drill_mm"] == pytest.approx(0.3, abs=TOL)
        # 板总厚同口径（nm 整数 /1e6）
        data["board"]["thickness_mm"] = 578000 / 1e6
        spec2 = kicad_to_edb_spec(data)
        assert spec2["stackup"]["total_thickness_mm"] == 0.578
        assert spec2["units"] == "mm"


class TestStackupEdgeCases:
    """介质缺失占位与多层板 via 层对不确定（诚实性路径）。"""

    def test_missing_stackup_placeholder_with_warning(self):
        data = _two_layer()
        data["board"]["stackup"] = {"dielectrics": []}  # python 新建板口径
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is True
        assert spec["stackup"]["dielectric_source"] == "placeholder_unresolved"
        names = [ly["name"] for ly in spec["stackup"]["layers"]]
        assert names == ["B.Cu", "unresolved_dielectric_1", "F.Cu"]
        diel = spec["stackup"]["layers"][1]
        assert diel["thickness_mm"] is None  # 不按总厚均摊编造
        assert diel["er"] is None and diel["tan_d"] is None
        assert any("介质层数目失配" in w for w in spec["warnings"])

    def test_four_layer_interleave_and_via_pair_unknown(self):
        data = _two_layer()
        data["board"]["copper_layers"] = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        data["board"]["layer_count"] = 4
        data["board"]["stackup"]["dielectrics"] = [
            {"name": "dielectric 1", "thickness_mm": 0.1, "er": 4.0,
             "tan_d": 0.02},
            {"name": "dielectric 2", "thickness_mm": 0.2, "er": 4.2,
             "tan_d": 0.02},
            {"name": "dielectric 3", "thickness_mm": 0.15, "er": 4.1,
             "tan_d": 0.02},
        ]
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is True
        names = [ly["name"] for ly in spec["stackup"]["layers"]]
        # bottom→top：介质按文件序（顶→底）反转插入相邻铜层之间
        assert names == ["B.Cu", "dielectric 3", "In2.Cu", "dielectric 2",
                         "In1.Cu", "dielectric 1", "F.Cu"]
        assert spec["stackup"]["copper_layer_count"] == 4
        assert spec["stackup"]["kicad_to_edb_layers"] == {
            "F.Cu": "F.Cu", "In1.Cu": "In1.Cu", "In2.Cu": "In2.Cu",
            "B.Cu": "B.Cu"}
        # 多层板 via 层对不可确证：None + 一次性告警
        assert len(spec["vias"]) == 2
        assert spec["vias"][0]["start_layer"] is None
        assert spec["vias"][0]["stop_layer"] is None
        pair_warns = [w for w in spec["warnings"] if "layer pair" in w]
        assert len(pair_warns) == 1


class TestFailureContracts:
    """失败契约：ok=False 输入 / 非 dict / 非法策略 / 容器类型错。"""

    def test_not_ok_input_fails(self):
        spec = kicad_to_edb_spec({"ok": False, "errors": ["KiCad 提取失败"]})
        assert spec["ok"] is False
        assert any("ok=False" in e for e in spec["errors"])
        assert "KiCad 提取失败" in spec["errors"][1]

    def test_non_dict_input_fails(self):
        spec = kicad_to_edb_spec(["not", "a", "dict"])  # type: ignore[arg-type]
        assert spec["ok"] is False
        assert spec["errors"] and "非 dict" in spec["errors"][0]

    def test_invalid_policy_fails(self):
        spec = kicad_to_edb_spec(_two_layer(), stackup_policy="explicit")
        assert spec["ok"] is False
        assert "stackup_policy" in spec["errors"][0]
        assert STACKUP_POLICIES == ("auto",)  # spike 仅 auto

    def test_missing_board_fails(self):
        data = _two_layer()
        del data["board"]
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is False

    def test_non_list_traces_fails(self):
        data = _two_layer()
        data["traces"] = "bogus"
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is False
        assert any("'traces'" in e for e in spec["errors"])


class TestHonestHandling:
    """坏几何 / 缺键 / zones 不静默丢弃。"""

    def test_bad_geometry_skipped_with_warning(self):
        data = _two_layer()
        data["traces"] = [
            {"net": "BAD1", "layer": "F.Cu", "width_mm": 0.5,
             "length_mm": 0.0, "points_mm": [[1.0, 1.0]]},  # <2 点
            {"net": "BAD2", "layer": "F.Cu", "width_mm": 0.0,
             "length_mm": 1.0, "points_mm": [[1.0, 1.0], [2.0, 1.0]]},
        ]
        data["vias"] = [{"net": "GND", "x_mm": "oops", "y_mm": 18.0,
                         "pad_diameter_mm": 0.6, "drill_mm": 0.3}]
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is True
        assert spec["traces"] == []
        assert spec["vias"] == []
        joined = "\n".join(spec["warnings"])
        assert "BAD1" in joined and "BAD2" in joined
        assert "via[0]" in joined
        assert spec["counts"]["traces"] == 0
        assert spec["counts"]["vias"] == 0

    def test_missing_element_keys_warn_treated_empty(self):
        data = _two_layer()
        del data["traces"]
        del data["vias"]
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is True
        assert spec["traces"] == [] and spec["vias"] == []
        joined = "\n".join(spec["warnings"])
        assert "'traces'" in joined and "'vias'" in joined

    def test_zones_not_mapped_but_not_silent(self):
        data = _two_layer()
        data["zones"] = [{"net": "GND", "layer": "B.Cu"}]
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is True
        assert "zones" not in spec  # 不入 spec
        assert any("zones[1]" in w and "暂不映射" in w
                   for w in spec["warnings"])  # 但绝不静默

    def test_missing_outline_warns(self):
        data = _two_layer()
        data["outline"] = {}
        spec = kicad_to_edb_spec(data)
        assert spec["ok"] is True
        assert spec["outline"] == {}
        assert any("板框缺失" in w for w in spec["warnings"])
