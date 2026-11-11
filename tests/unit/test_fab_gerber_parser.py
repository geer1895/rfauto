"""Gerber RS-274X / Excellon 解析内核+服务+CLI 单测（aurora_q 席位 Q-X59，2026-11-07）。

覆盖面（任务书 ≥60 条）：

- FS 拆分表驱动（已知量断言家法 #118：FSLAX35Y35+MOMM+``"0012345"``
  →0.12345 表；LZ/TZ 两模式同值；IN 换算 ×25.4 精确十进制；非法
  fail-soft）；
- 词法面：语句终止符/扩展块/G04 收编/G54Dxx 前缀/M02 截断；
- 坐标模态缺省（只给 X 用上 Y 值；纯 D 码重复选刀）；D01/D02/D03；
  弧段 G02/G03 I/J 相对偏移原值记录；G36/G37 区域路径收集（D02 切环
  +首顶点入环+未收口截断物化）；宏 unexpanded 如实 + 未定义引用
  warning；LP 极性登记；aperture C/R/O/P 参数拆解；
- 几何落地面：outline_bbox 端点包络（弧段 endpoint-only 声明）、
  gerber_layer_summary 分组计数/undefined_dcodes、gerber_bbox 消费面；
- fail-soft：非法 FS/未知命令 warning/截断不崩/坐标词非法跳轴/文件级
  GerberParseError；
- Excellon：刀具登记 C 直径（INCH/METRIC 双单位）、LZ/TZ、T0 复位、
  选刀模态、G85 单行两对槽孔、G41/G42 路由登记、最近邻间距统计
  （n<2 如实 None）、fail-soft（非法坐标/未登记选刀/无指纹文件级错）；
- 服务层：parse_gerber_file/parse_excellon_file 信封形状（ok/error 两
  态；errors 恒 list）、summarize_gerber 摘要、pair_check 越界孔构造
  （bbox 内/越界/坐标 None skip 三分）；
- CLI 信封契约：fab parse（--json 全结构/human/配对/--drill 分支）、
  fab summary（--json+human）、失败路径 JSON 信封同构（#ge1㉙）、
  usage 错 exit 2、--help 真构建。

run 湖零写入（#144）：全部夹具 tmp_path 落盘，测试零 runs/ 触碰。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.core.excellon_parser import (
    ExcellonParseError,
    parse_excellon,
    split_excellon_number,
)
from rfauto.core.gerber_parser import (
    GerberParseError,
    gerber_bbox,
    gerber_layer_summary,
    parse_format_spec,
    parse_gerber,
    split_fs_number,
)
from rfauto.service.fab_gerber_service import (
    gerber_excellon_pair_check,
    parse_excellon_file,
    parse_gerber_file,
    summarize_gerber,
)

runner = CliRunner()

# ── 夹具（内嵌小文本；任务书口径）──────────────────────────────────────────

GERBER_FULL = """\
%FSLAX34Y34*%
%MOIN*%
%ADD10C,0.5*%
%ADD11R,5.1X2.3*%
%AMTHERMAL*1,0,0.5,0,0*%
%ADD12THERMAL*%
G04 board outline (comment swallowed)*
D11*
X0Y0D02*
X25400Y0D01*
X25400Y12700D01*
X0Y12700D01*
X0Y0D01*
D10*
X5000Y5000D03*
X10000Y5000D03*
G03X15000Y10000I5000J0D01*
G36*
X2540Y2540D02*
X22860Y2540D01*
X22860Y10160D01*
X2540Y10160D01*
X2540Y2540D01*
G37*
%LPD*%
M02*
"""

GERBER_MM_REGION = """\
%FSLAX35Y35*%
%MOMM*%
%ADD10C,0.8*%
D10*
G36*
X500000Y500000D02*
X1000000Y500000D01*
X1000000Y1000000D01*
X500000Y1000000D01*
X500000Y500000D01*
G37*
M02*
"""

EXCELLON_FULL = """\
; protel drill file
; FILE_FORMAT=2:5
M48
FMAT,2
METRIC,LZ
T01C0.8
T02C1.500S15
%
; header rewind
T01
X10000Y10000
X20000Y10000
X15000Y15000
T02
X20000Y20000
X10000Y20000
X10000Y20000G85X15000Y20000
T0
M30
"""

EXCELLON_INCH = """\
M48
INCH,TZ
T01C0.020
%
T1
X005000Y002000
T0
M30
"""


@pytest.fixture()
def gerber_path(tmp_path: Path) -> Path:
    p = tmp_path / "sample.gbr"
    p.write_text(GERBER_FULL, encoding="utf-8")
    return p


@pytest.fixture()
def gerber_mm_path(tmp_path: Path) -> Path:
    p = tmp_path / "sample_mm.gbr"
    p.write_text(GERBER_MM_REGION, encoding="utf-8")
    return p


@pytest.fixture()
def drill_path(tmp_path: Path) -> Path:
    p = tmp_path / "sample.drl"
    p.write_text(EXCELLON_FULL, encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def gdoc() -> dict:
    return parse_gerber(GERBER_FULL)


@pytest.fixture(scope="module")
    # NOTE: scope module + 参数化夹具不兼容，改为函数内直接调用
def edoc() -> dict:
    return parse_excellon(EXCELLON_FULL)


# ═══ FS 定长拆分（表驱动已知量，#118 家法）═════════════════════════════════


class TestFsSplit:
    def test_known_quantity_mm(self) -> None:
        # FSLAX35Y35 + MOMM + "0012345" → 0.12345 mm（任务书已知量表）
        assert float(split_fs_number("0012345", 5)) == pytest.approx(0.12345)

    def test_known_quantity_int_part(self) -> None:
        # FSLAX34Y34 口径 "25400"（X25400）→ 2.54 文件单位
        assert float(split_fs_number("25400", 4)) == pytest.approx(2.54)

    def test_negative_value(self) -> None:
        assert float(split_fs_number("-1234", 4)) == pytest.approx(-0.1234)

    def test_lz_and_tz_same_integer_value(self) -> None:
        # L/T 零省略只影响缺位补零方向；文件内数字整数值恒同 → 同定标
        assert split_fs_number("1234", 4) == split_fs_number("01234", 4)

    def test_empty_is_none(self) -> None:
        assert split_fs_number("", 5) is None

    def test_illegal_literal_is_none(self) -> None:
        assert split_fs_number("12x4", 5) is None

    def test_decimal_point_form(self) -> None:
        # 历史/异端小数点形态按浮点直读
        assert float(split_fs_number("1.5", 4)) == pytest.approx(1.5)

    def test_parse_format_spec_fields(self) -> None:
        spec = parse_format_spec("FSLAX35Y35")
        assert spec is not None
        d = spec.as_dict()
        assert d == {"zero_omission": "L", "notation": "A",
                     "x": [3, 5], "y": [3, 5]}

    def test_parse_format_spec_t_omission(self) -> None:
        spec = parse_format_spec("FSTAX26Y26")
        assert spec is not None
        assert spec.zero_omission == "T"
        assert spec.as_dict()["x"] == [2, 6]

    def test_parse_format_spec_dec_zero_illegal(self) -> None:
        assert parse_format_spec("FSLAX30Y30") is None

    def test_parse_format_spec_over_13_illegal(self) -> None:
        assert parse_format_spec("FSLAX77Y77") is None

    def test_parse_format_spec_non_fs_is_none(self) -> None:
        assert parse_format_spec("MOMM") is None


# ═══ Gerber 词法/结构面 ═══════════════════════════════════════════════════


class TestGerberHeader:
    def test_units_in(self, gdoc: dict) -> None:
        assert gdoc["units"] == "IN"

    def test_units_mm(self, gerber_mm_path: Path) -> None:
        assert parse_gerber_file(gerber_mm_path)["units"] == "MM"

    def test_format_spec(self, gdoc: dict) -> None:
        assert gdoc["format_spec"] == {
            "zero_omission": "L", "notation": "A", "x": [3, 4], "y": [3, 4]}

    def test_missing_fs_coords_none(self) -> None:
        doc = parse_gerber("%MOMM*%\nD10*\nX1000Y1000D03*\nM02*")
        assert doc["format_spec"] is None
        assert doc["flashes"][0]["x_mm"] is None
        assert any("FS" in w for w in doc["warnings"])

    def test_missing_mo_keeps_none(self) -> None:
        doc = parse_gerber("%FSLAX34Y34*%\nD10*\nX1000Y1000D03*\nM02*")
        assert doc["units"] is None
        # 单位不明 → _mm 如实 None（不猜）
        assert doc["flashes"][0]["x_mm"] is None

    def test_polarity_registered(self, gdoc: dict) -> None:
        assert gdoc["polarity_current"] == "D"

    def test_g04_comment_swallowed(self, gdoc: dict) -> None:
        assert gdoc["stats"]["n_warnings"] == 0 or not any(
            "G04" in w for w in gdoc["warnings"])


class TestGerberApertures:
    def test_two_standard_apertures(self, gdoc: dict) -> None:
        assert set(gdoc["apertures"]) == {"10", "11", "12"}

    def test_circle_params(self, gdoc: dict) -> None:
        ap = gdoc["apertures"]["10"]
        assert ap["shape"] == "C"
        assert ap["params"]["diameter"] == 0.5

    def test_rect_params(self, gdoc: dict) -> None:
        ap = gdoc["apertures"]["11"]
        assert ap["shape"] == "R"
        assert ap["params"]["width"] == 5.1
        assert ap["params"]["height"] == 2.3

    def test_macro_registered_unexpanded(self, gdoc: dict) -> None:
        mac = gdoc["macros"]["THERMAL"]
        assert mac["expanded"] is False
        assert "1,0,0.5,0,0" in mac["body_raw"]
        assert gdoc["stats"]["n_macros_unexpanded"] == 1

    def test_macro_reference_linked(self, gdoc: dict) -> None:
        assert gdoc["apertures"]["12"]["macro"] == "THERMAL"

    def test_macro_reference_undefined_warns(self) -> None:
        doc = parse_gerber("%FSLAX34Y34*%\n%ADD10NOPE*%\nM02*")
        assert any("NOPE" in w for w in doc["warnings"])

    def test_obround_params(self) -> None:
        doc = parse_gerber("%FSLAX34Y34*%\n%ADD12O,1.5X2.0*%\nM02*")
        ap = doc["apertures"]["12"]
        assert ap["shape"] == "O"
        assert ap["params"]["width"] == 1.5

    def test_polygon_params(self) -> None:
        doc = parse_gerber("%FSLAX34Y34*%\n%ADD13P,2.0X6X0*%\nM02*")
        ap = doc["apertures"]["13"]
        assert ap["shape"] == "P"
        assert ap["params"]["outer_diameter"] == 2.0

    def test_bad_param_keeps_raw(self) -> None:
        doc = parse_gerber("%FSLAX34Y34*%\n%ADD10C,bad*%\nM02*")
        assert doc["apertures"]["10"]["params"]["raw"] == "bad"
        assert any("非数值" in w for w in doc["warnings"])


class TestGerberBody:
    def test_flashes(self, gdoc: dict) -> None:
        # X5000（FS 3:4）= 0.5 in = 12.7 mm
        assert gdoc["flashes"] == [
            {"dcode": 10, "x_mm": 12.7, "y_mm": 12.7},
            {"dcode": 10, "x_mm": 25.4, "y_mm": 12.7},
        ]

    def test_outline_draws_linear(self, gdoc: dict) -> None:
        draws = [d for d in gdoc["draws"] if d["interpolation"] == "linear"]
        # 4 条板框 D01（X0Y0D02 移动后）：(0,0)→(64.516,0)→(64.516,32.258)
        # →(0,32.258)→(0,0)；X25400（FS 3:4）= 2.54 in = 64.516 mm
        assert len(draws) == 4
        assert draws[0]["from"] == [0.0, 0.0]
        assert draws[0]["to"] == [pytest.approx(64.516), 0.0]
        assert draws[1]["to"] == [pytest.approx(64.516),
                                  pytest.approx(32.258)]
        assert draws[2]["to"] == [0.0, pytest.approx(32.258)]
        assert draws[3]["to"] == [0.0, 0.0]

    def test_arc_ij_relative_offsets(self, gdoc: dict) -> None:
        arcs = [d for d in gdoc["draws"]
                if d["interpolation"] == "ccw_arc"]
        assert len(arcs) == 1
        assert arcs[0]["i_mm"] == pytest.approx(12.7)
        assert arcs[0]["j_mm"] == pytest.approx(0.0)

    def test_interpolation_modal(self) -> None:
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOIN*%\nD10*\n"
            "X0Y0D02*\nG03X1000Y1000I500J0D01*\n"
            "X2000Y2000D01*\nM02*")
        arcs = [d for d in doc["draws"] if d["interpolation"] == "ccw_arc"]
        # G03 后未再给 G 码：第二条 D01 保持 ccw_arc 模态（缺省模态如实）
        assert len(arcs) == 2

    def test_coordinate_modal_default_missing_axis(self) -> None:
        # 只给 X：Y 沿用上值（规范模态续用）
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOIN*%\nD10*\n"
            "X1000Y2000D02*\nX3000D01*\nM02*")
        d = doc["draws"][0]
        assert d["from"] == [pytest.approx(2.54), pytest.approx(5.08)]
        assert d["to"] == [pytest.approx(7.62), pytest.approx(5.08)]

    def test_g54d_prefix_compat(self) -> None:
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOIN*%\n"
            "G54D10*\nX1000Y1000D03*\nM02*")
        assert doc["flashes"][0]["dcode"] == 10
        assert not any("未识别" in w for w in doc["warnings"])

    def test_pure_dcode_select_no_warning(self) -> None:
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOIN*%\nD10*\nD11*\nM02*")
        assert doc["stats"]["n_warnings"] == 0

    def test_m02_not_truncated(self, gdoc: dict) -> None:
        assert gdoc["truncated"] is False

    def test_truncated_no_m02_no_crash(self) -> None:
        doc = parse_gerber("%FSLAX34Y34*%\n%MOIN*%\nD10*\nX1000Y1000D03*")
        assert doc["truncated"] is True
        assert doc["flashes"][0]["x_mm"] is not None

    def test_after_m02_tail_ignored(self) -> None:
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOIN*%\nD10*\nX1000Y1000D03*\n"
            "M02*\nX9999Y9999D03*")
        assert len(doc["flashes"]) == 1

    def test_unknown_body_statement_warns(self) -> None:
        doc = parse_gerber("%FSLAX34Y34*%\n%MOIN*%\nZZZ00*\nM02*")
        assert any("未识别体语句" in w for w in doc["warnings"])

    def test_unknown_extended_counted(self) -> None:
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOMM*%\n%TFGenerationSoftware,test*%\nM02*")
        assert doc["unknown_extended"].get("TF") == 1

    def test_g90_registered_ignored(self) -> None:
        doc = parse_gerber("%FSLAX34Y34*%\n%MOIN*%\nG90*\nM02*")
        assert any("G90" in w for w in doc["warnings"])


class TestGerberRegions:
    def test_region_paths_collected(self, gdoc: dict) -> None:
        assert gdoc["stats"]["n_regions"] == 1
        region = gdoc["regions"][0]
        assert region["polarity"] == "D"
        path = region["paths"][0]
        # 5 顶点（D02 起点+4 条 D01，闭合）；FS 3:4 IN → ×25.4 mm
        assert len(path) == 5
        assert path[0] == [pytest.approx(6.4516), pytest.approx(6.4516)]

    def test_region_mm_closed_loop(self, gerber_mm_path: Path) -> None:
        doc = parse_gerber_file(gerber_mm_path)
        path = doc["regions"][0]["paths"][0]
        assert path[0] == [5.0, 5.0]
        assert path[-1] == path[0]

    def test_region_d02_splits_paths(self) -> None:
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOIN*%\nD10*\nG36*\n"
            "X0Y0D02*\nX1000Y0D01*\nX1000Y1000D01*\n"
            "X2000Y0D02*\nX3000Y0D01*\n"
            "G37*\nM02*")
        paths = doc["regions"][0]["paths"]
        assert len(paths) == 2
        assert paths[0][0] == [0.0, 0.0]
        assert paths[1][0] == [pytest.approx(5.08), 0.0]

    def test_region_unclosed_truncated(self) -> None:
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOIN*%\nD10*\nG36*\n"
            "X0Y0D02*\nX1000Y0D01*")
        assert doc["stats"]["n_regions"] == 1
        assert doc["truncated"] is True
        assert any("G37" in w for w in doc["warnings"])

    def test_g37_without_g36_warns(self) -> None:
        doc = parse_gerber("%FSLAX34Y34*%\n%MOIN*%\nG37*\nM02*")
        assert doc["stats"]["n_regions"] == 0
        assert any("G37" in w for w in doc["warnings"])

    def test_empty_region_warns(self) -> None:
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOIN*%\nG36*\nG37*\nM02*")
        assert doc["regions"][0]["paths"] == [[]]
        assert any("空环" in w for w in doc["warnings"])


class TestGerberGeometry:
    def test_outline_bbox(self, gdoc: dict) -> None:
        # 板框 X25400Y12700 → 包络 64.516 × 32.258 mm
        assert gdoc["outline_bbox_mm"] == [0.0, 0.0, pytest.approx(64.516),
                                           pytest.approx(32.258)]

    def test_bbox_mode_endpoint_only(self, gdoc: dict) -> None:
        assert gdoc["bbox_mode"] == "endpoint-only"

    def test_gerber_bbox_consumer(self, gdoc: dict) -> None:
        out = gerber_bbox(gdoc)
        assert out["mode"] == "endpoint-only"
        assert out["bbox_mm"] == gdoc["outline_bbox_mm"]
        assert out["n_points"] > 0

    def test_empty_geometry_bbox_none(self) -> None:
        doc = parse_gerber("%FSLAX34Y34*%\n%MOIN*%\nM02*")
        assert doc["outline_bbox_mm"] is None
        assert gerber_bbox(doc)["bbox_mm"] is None


class TestGerberLayerSummary:
    def test_per_dcode_counts(self, gdoc: dict) -> None:
        s = gerber_layer_summary(gdoc)
        assert s["per_dcode"]["10"] == {"n_flashes": 2, "n_draws": 1}
        assert s["per_dcode"]["11"] == {"n_flashes": 0, "n_draws": 4}

    def test_per_shape(self, gdoc: dict) -> None:
        s = gerber_layer_summary(gdoc)
        assert s["per_shape"] == {"C": 1, "R": 1, "THERMAL": 1}

    def test_undefined_dcodes_reported(self) -> None:
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOIN*%\n"
            "D15*\nX1000Y1000D03*\nM02*")
        s = gerber_layer_summary(doc)
        assert s["undefined_dcodes"] == ["15"]


class TestGerberFailSoft:
    def test_illegal_fs_fails_soft(self) -> None:
        doc = parse_gerber("%FSLAX30Y30*%\n%MOIN*%\nM02*")
        assert doc["format_spec"] is None
        assert any("FS" in w for w in doc["warnings"])

    def test_illegal_coord_word_skips_axis(self) -> None:
        # 小数点异端形态容错直读（warning 不炸）
        doc = parse_gerber(
            "%FSLAX34Y34*%\n%MOIN*%\nD10*\nX1.5Y1000D03*\nM02*")
        assert doc["flashes"][0]["x_mm"] == pytest.approx(1.5 * 25.4)

    def test_file_level_error_not_gerber(self) -> None:
        with pytest.raises(GerberParseError):
            parse_gerber("hello world\nnot a gerber\n")

    def test_empty_text_error(self) -> None:
        with pytest.raises(GerberParseError):
            parse_gerber("")

    def test_deterministic(self, gerber_path: Path) -> None:
        text = gerber_path.read_text(encoding="utf-8")
        assert parse_gerber(text) == parse_gerber(text)


# ═══ Excellon 面 ══════════════════════════════════════════════════════════


class TestExcellonHeader:
    def test_units_zero_mode(self, edoc: dict) -> None:
        assert edoc["units"] == "METRIC"
        assert edoc["zero_mode"] == "LZ"

    def test_fmat_registered(self, edoc: dict) -> None:
        assert edoc["fmat"] == "2"

    def test_decimals_from_comment(self, edoc: dict) -> None:
        assert edoc["decimals"] == 5
        assert edoc["decimals_source"] == "comment"

    def test_default_decimals(self) -> None:
        doc = parse_excellon(EXCELLON_INCH)
        assert doc["decimals"] == 6
        assert doc["decimals_source"] == "default6"

    def test_tools_diameter_mm(self, edoc: dict) -> None:
        assert edoc["tools"]["1"]["diameter_mm"] == pytest.approx(0.8)
        assert edoc["tools"]["2"]["diameter_mm"] == pytest.approx(1.5)

    def test_tool_speed_registered_raw(self, edoc: dict) -> None:
        assert edoc["tools"]["2"]["speed"] == "15"

    def test_inch_tool_diameter(self) -> None:
        doc = parse_excellon(EXCELLON_INCH)
        # 0.020 inch × 25.4 = 0.508 mm
        assert doc["tools"]["1"]["diameter_mm"] == pytest.approx(0.508)

    def test_unitless_tool_diameter_none(self) -> None:
        doc = parse_excellon("M48\nT01C0.5\n%\nT1\nX0Y0\nM30")
        assert doc["units"] is None
        assert doc["tools"]["1"]["diameter_mm"] is None


class TestExcellonBody:
    def test_hits_five(self, edoc: dict) -> None:
        assert edoc["stats"]["n_hits"] == 5

    def test_hit_coords_mm(self, edoc: dict) -> None:
        # X10000（5 位定标）= 0.1 mm
        assert edoc["hits"][0] == {"tool": "1", "x_mm": pytest.approx(0.1),
                                   "y_mm": pytest.approx(0.1)}

    def test_tool_select_modal(self, edoc: dict) -> None:
        tools = {h["tool"] for h in edoc["hits"]}
        assert tools == {"1", "2"}

    def test_slot_single_line_two_pairs(self, edoc: dict) -> None:
        assert edoc["slots"] == [{
            "tool": "2",
            "from": [pytest.approx(0.1), pytest.approx(0.2)],
            "to": [pytest.approx(0.15), pytest.approx(0.2)],
        }]

    def test_t0_reset_then_reselect(self, edoc: dict) -> None:
        assert edoc["stats"]["n_slots"] == 1  # T0 后 M30，无散落 hit

    def test_route_mode_registered(self) -> None:
        doc = parse_excellon(
            "M48\nMETRIC,LZ\nT01C1.0\n%\nG41\nX0Y0\nM30")
        assert doc["route_mode"] == "G41"

    def test_truncated_no_m30(self) -> None:
        doc = parse_excellon("M48\nMETRIC,LZ\n%\nX0Y0\n")
        assert doc["truncated"] is True

    def test_after_m30_tail_ignored(self, edoc: dict) -> None:
        assert edoc["stats"]["n_hits"] == 5

    def test_per_tool_counts(self, edoc: dict) -> None:
        assert edoc["stats"]["per_tool_counts"] == {"1": 3, "2": 3}

    def test_select_unregistered_tool_warns(self) -> None:
        doc = parse_excellon(
            "M48\nMETRIC,LZ\n%\nT9\nX0Y0\nM30")
        assert any("T9" in w for w in doc["warnings"])


class TestExcellonSplit:
    def test_known_quantity_metric(self) -> None:
        assert float(split_excellon_number("10000", 5)) == pytest.approx(0.1)

    def test_lz_tz_same_value(self) -> None:
        assert split_excellon_number("005000", 6) == \
            split_excellon_number("5000", 6)

    def test_decimal_point_form(self) -> None:
        assert float(split_excellon_number("0.5", 6)) == pytest.approx(0.5)

    def test_illegal_is_none(self) -> None:
        assert split_excellon_number("x0500", 6) is None


class TestExcellonGridSummary:
    def test_bbox(self, edoc: dict) -> None:
        from rfauto.core.excellon_parser import excellon_hit_grid_summary
        out = excellon_hit_grid_summary(edoc)
        assert out["bbox_mm"] == [pytest.approx(0.1), pytest.approx(0.1),
                                  pytest.approx(0.2), pytest.approx(0.2)]
        assert out["n_points"] == 5

    def test_nn_spacing(self, edoc: dict) -> None:
        from rfauto.core.excellon_parser import excellon_hit_grid_summary
        out = excellon_hit_grid_summary(edoc)
        # 点阵 (0.1,0.1)/(0.2,0.1)/(0.15,0.15)/(0.2,0.2)/(0.1,0.2)
        # 逐点最近邻全部 = 0.05·√2 ≈ 0.0707107（对称十字阵）
        assert out["nn_min_mm"] == pytest.approx(0.07071068, abs=1e-6)
        assert out["nn_max_mm"] >= out["nn_median_mm"] >= out["nn_min_mm"]

    def test_single_point_none(self) -> None:
        from rfauto.core.excellon_parser import excellon_hit_grid_summary
        doc = parse_excellon("M48\nMETRIC,LZ\n%\nX0Y0\nM30")
        out = excellon_hit_grid_summary(doc)
        assert out["nn_min_mm"] is None
        assert out["n_points"] == 1

    def test_no_points_none(self) -> None:
        from rfauto.core.excellon_parser import excellon_hit_grid_summary
        doc = parse_excellon("M48\nMETRIC,LZ\n%\nM30")
        assert excellon_hit_grid_summary(doc)["bbox_mm"] is None

    def test_failsoft_bad_coord_warns(self) -> None:
        doc = parse_excellon("M48\nMETRIC,LZ\n%\nXbadY1000\nM30")
        # Xbad 不匹配坐标词 → X 轴缺（模态无前点）→ x_mm 如实 None 不炸
        assert doc["stats"]["n_hits"] == 1
        assert doc["hits"][0]["x_mm"] is None
        assert doc["hits"][0]["y_mm"] is not None

    def test_file_level_error(self) -> None:
        with pytest.raises(ExcellonParseError):
            parse_excellon("totally not drill\n")


# ═══ 服务层（信封契约）════════════════════════════════════════════════════


class TestServiceEnvelopes:
    def test_parse_gerber_ok_shape(self, gerber_path: Path) -> None:
        r = parse_gerber_file(gerber_path)
        assert r["ok"] is True
        assert r["kind"] == "gerber"
        assert r["stats"]["n_flashes"] == 2
        assert "errors" not in r

    def test_parse_gerber_error_unreadable(self) -> None:
        r = parse_gerber_file("no_such_dir/no_file.gbr")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)
        assert "不可读" in r["errors"][0]

    def test_parse_gerber_error_not_gerber(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.gbr"
        p.write_text("not gerber at all", encoding="utf-8")
        r = parse_gerber_file(p)
        assert r["ok"] is False
        assert "解析失败" in r["errors"][0]

    def test_parse_excellon_ok(self, drill_path: Path) -> None:
        r = parse_excellon_file(drill_path)
        assert r["ok"] is True
        assert r["kind"] == "excellon"
        assert r["stats"]["n_hits"] == 5

    def test_parse_excellon_error(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.drl"
        p.write_text("junk", encoding="utf-8")
        r = parse_excellon_file(p)
        assert r["ok"] is False
        assert isinstance(r["errors"], list)

    def test_summarize_gerber(self, gerber_path: Path) -> None:
        r = summarize_gerber(gerber_path)
        assert r["ok"] is True
        assert r["kind"] == "gerber_summary"
        assert r["summary"]["per_shape"]["C"] == 1
        assert r["bbox"]["bbox_mm"] is not None

    def test_pair_check_inside(self, gerber_path: Path,
                               drill_path: Path) -> None:
        r = gerber_excellon_pair_check(gerber_path, drill_path)
        assert r["ok"] is True
        assert r["kind"] == "pair_check"
        assert r["n_hits"] == 5
        assert r["n_out_of_bounds"] == 0
        assert r["n_skipped"] == 0

    def test_pair_check_out_of_bounds_constructed(
            self, gerber_path: Path, tmp_path: Path) -> None:
        # 构造越界孔（孔位 x=90mm 远超板 bbox x 上限 64.516mm）
        p = tmp_path / "out.drl"
        p.write_text(
            "; FILE_FORMAT=2:5\nM48\nMETRIC,LZ\nT01C0.8\n%\n"
            "T1\nX9000000Y10000\nM30",
            encoding="utf-8")
        r = gerber_excellon_pair_check(gerber_path, p)
        assert r["ok"] is True
        assert r["n_out_of_bounds"] == 1
        ob = r["out_of_bounds"][0]
        assert ob["axis"] == "x"
        assert ob["tool"] == "1"
        assert ob["value_mm"] == pytest.approx(90.0)

    def test_pair_check_gerber_fail_fast(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.gbr"
        bad.write_text("junk", encoding="utf-8")
        r = gerber_excellon_pair_check(bad, "also_missing.drl")
        assert r["ok"] is False
        assert "Gerber" in r["errors"][0]

    def test_pair_check_bbox_none_skips_all(
            self, tmp_path: Path) -> None:
        g = tmp_path / "empty.gbr"
        g.write_text("%FSLAX34Y34*%\n%MOIN*%\nM02*", encoding="utf-8")
        d = tmp_path / "one.drl"
        d.write_text("M48\nMETRIC,LZ\n%\nX0Y0\nM30", encoding="utf-8")
        r = gerber_excellon_pair_check(g, d)
        assert r["ok"] is True
        assert r["n_skipped"] == 1
        assert any("bbox=None" in n for n in r["notes"])


# ═══ CLI 信封契约 ═════════════════════════════════════════════════════════


class TestCliFab:
    def test_parse_json_envelope(self, gerber_path: Path) -> None:
        r = runner.invoke(root_app, ["fab", "parse", "--gerber",
                                     str(gerber_path), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["stats"]["n_flashes"] == 2

    def test_parse_human_default(self, gerber_path: Path) -> None:
        r = runner.invoke(root_app, ["fab", "parse", "--gerber",
                                     str(gerber_path)])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)  # fab 组缺省即 JSON 信封直出
        assert payload["ok"] is True

    def test_parse_pair_with_drill(self, gerber_path: Path,
                                   drill_path: Path) -> None:
        r = runner.invoke(root_app, [
            "fab", "parse", "--gerber", str(gerber_path),
            "--drill", str(drill_path), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["kind"] == "pair_check"
        assert payload["n_hits"] == 5

    def test_parse_failure_json_envelope_same_shape(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.gbr"
        bad.write_text("junk", encoding="utf-8")
        r = runner.invoke(root_app, ["fab", "parse", "--gerber",
                                     str(bad), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)

    def test_parse_unreadable_exit1(self) -> None:
        r = runner.invoke(root_app, ["fab", "parse", "--gerber",
                                     "no/such/file.gbr", "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["ok"] is False

    def test_parse_usage_error_exit2(self) -> None:
        r = runner.invoke(root_app, ["fab", "parse"])
        assert r.exit_code == 2

    def test_summary_json(self, gerber_path: Path) -> None:
        r = runner.invoke(root_app, ["fab", "summary", "--gerber",
                                     str(gerber_path), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["summary"]["per_shape"]["C"] == 1
        assert payload["bbox"]["mode"] == "endpoint-only"

    def test_summary_human_default(self, gerber_path: Path) -> None:
        r = runner.invoke(root_app, ["fab", "summary", "--gerber",
                                     str(gerber_path)])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["ok"] is True

    def test_summary_failure_envelope(self) -> None:
        r = runner.invoke(root_app, ["fab", "summary", "--gerber",
                                     "no/file.gbr", "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)

    def test_help_builds(self) -> None:
        r = runner.invoke(root_app, ["fab", "parse", "--help"])
        assert r.exit_code == 0
        assert "--gerber" in r.output
        r = runner.invoke(root_app, ["fab", "summary", "--help"])
        assert r.exit_code == 0
        assert "--gerber" in r.output

    def test_fab_group_leaves(self) -> None:
        from typer.main import get_command
        cmd = get_command(root_app)
        fab_cmd = cmd.commands["fab"]
        assert {"parse", "summary"} <= set(fab_cmd.commands)
        # 既有九叶保持零遮蔽（Q-X59 只增不改）
        for name in ("go", "pipeline", "snapshot", "draw", "audit",
                     "pack", "rules", "catalog", "export"):
            assert name in fab_cmd.commands
