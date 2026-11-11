"""Liberty (.lib) 解析内核单测（aurora_q Q-X34 席位，2026-11-07）。

覆盖面（任务书 ≥20 条之解析内核半边）：
- 夹具正例：库头/单位、cell 清单、pin 元数据（direction/function/
  capacitance）、模板继承表、显式 index 表、一维表归一、双 timing 组
  同 related_pin 消歧、internal_power、leakage_power 两种写法、
  lu_table_template、operating_conditions；
- NLDM 双线性插值：内点手算锚+越界夹取+一维插值；
- 词法保真：块注释剥离（字符串内不剥）、函数表达式字符串保真、
  bool/数字值归一、行尾反斜杠续行；
- 负例：未闭合组/缺分号/values 形状不符/顶层多余 token/缺 library/
  零维表非单值/一维表形状不符——全部 LibertyParseError 断言。

单测零网络零真机零写盘（夹具只读；负例用内联字符串）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.core.liberty_parser import (
    LibertyGroup,
    LibertyParseError,
    extract_library,
    extract_table,
    lookup_table,
    parse_liberty,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "liberty" / "sample.lib"


@pytest.fixture(scope="module")
def lib() -> LibertyGroup:
    return parse_liberty(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def data(lib: LibertyGroup) -> dict:
    return extract_library(lib)


# ── 库头/单位/版本 ──────────────────────────────────────────────────────────


class TestLibraryHeader:
    def test_library_name(self, lib: LibertyGroup) -> None:
        assert lib.name == "sample_lib_rfauto"

    def test_file_version_and_revision(self, data: dict) -> None:
        # file_version 显式属性优先；revision 同在（file_version 取显式键）
        assert data["file_version"] == "1.0"

    def test_units_passthrough(self, data: dict) -> None:
        units = data["units"]
        assert units["time_unit"] == "1ns"
        assert units["nom_voltage"] == 1.25
        # 复合属性原样（数字保型+词保字符串）
        assert units["capacitive_load_unit"] == [1.0, "pf"]
        assert units["delay_model"] == "table_lookup"

    def test_attrs_complete(self, data: dict) -> None:
        assert data["attrs"]["default_max_transition"] == 0.6
        assert data["attrs"]["nom_temperature"] == 25.0


# ── cell/pin 元数据 ─────────────────────────────────────────────────────────


class TestCellsPins:
    def test_cell_inventory_and_areas(self, data: dict) -> None:
        assert set(data["cells"]) == {"INVX1", "BUFX2", "DFFX1"}
        assert data["cells"]["INVX1"]["area"] == 4.5
        assert data["cells"]["BUFX2"]["area"] == 6.0
        assert data["cells"]["DFFX1"]["area"] == 12.0

    def test_pin_metadata(self, data: dict) -> None:
        zn = data["cells"]["INVX1"]["pins"]["ZN"]
        assert zn["direction"] == "output"
        assert zn["function"] == "!(A)"
        assert zn["capacitance"] == 0.0
        assert zn["max_capacitance"] == 0.12

    def test_pin_input_capacitance(self, data: dict) -> None:
        a = data["cells"]["INVX1"]["pins"]["A"]
        assert a["direction"] == "input"
        assert a["capacitance"] == 0.0021
        assert a["timing"] == {}

    def test_clock_pin_boolean(self, data: dict) -> None:
        ck = data["cells"]["DFFX1"]["pins"]["CK"]
        assert ck["clock"] is True
        # 非布尔 pin：clock 缺失如实 None（不编造 False）
        assert data["cells"]["INVX1"]["pins"]["A"]["clock"] is None

    def test_cell_attr_bool_passthrough(self, data: dict) -> None:
        assert data["cells"]["BUFX2"]["attrs"]["is_macro_cell"] is False
        assert data["cells"]["INVX1"]["cell_leakage_power"] == 0.123


# ── timing 查找表（NLDM）───────────────────────────────────────────────────


class TestTimingTables:
    def test_template_inherited_table(self, data: dict) -> None:
        # cell_rise (delay_template_2x2) 无本地 index → 从模板继承
        tg = data["cells"]["INVX1"]["pins"]["ZN"]["timing"]["A"]
        assert tg["timing_sense"] == "negative_unate"
        assert tg["timing_type"] == "combinational"
        t = tg["cell_rise"]
        assert t["template"] == "delay_template_2x2"
        assert t["dims"] == 2
        assert t["index_1"] == [0.01, 0.20]
        assert t["index_2"] == [0.005, 0.050]
        assert t["values"][0][0] == pytest.approx(0.0314605)
        assert t["values"][1][1] == pytest.approx(0.2122158)

    def test_four_nldm_tables_present(self, data: dict) -> None:
        tg = data["cells"]["INVX1"]["pins"]["ZN"]["timing"]["A"]
        for k in ("cell_rise", "cell_fall", "rise_transition", "fall_transition"):
            assert tg[k] is not None, k

    def test_explicit_index_table(self, data: dict) -> None:
        t = data["cells"]["BUFX2"]["pins"]["Z"]["timing"]["A"]["cell_rise"]
        assert t["template"] == "explicit_index"
        assert t["index_2"] == [0.01, 0.10]
        assert t["values"][0][1] == pytest.approx(0.1305058)

    def test_one_dimensional_table_normalized(self, data: dict) -> None:
        # 无名表组（rise_transition ()）+ 仅 index_1 → dims=1 单行归一
        t = data["cells"]["BUFX2"]["pins"]["Z"]["timing"]["A"]["rise_transition"]
        assert t["dims"] == 1
        assert t["template"] is None
        assert t["index_1"] == [0.01, 0.20]
        assert t["values"] == [[0.0200001, 0.1500002]]
        assert "index_2" not in t

    def test_same_related_pin_disambiguation(self, data: dict) -> None:
        timing = data["cells"]["DFFX1"]["pins"]["Q"]["timing"]
        assert set(timing) == {"CK", "CK@falling_edge"}
        assert timing["CK"]["timing_type"] == "rising_edge"
        assert timing["CK@falling_edge"]["timing_type"] == "falling_edge"
        assert timing["CK"]["cell_rise"]["values"][0][0] == pytest.approx(0.1026981)
        assert timing["CK@falling_edge"]["cell_rise"]["values"][0][0] == pytest.approx(
            0.1086423)


# ── NLDM 双线性插值（确定性内核，手算锚）────────────────────────────────────


class TestLookup:
    def test_bilinear_interior_hand_anchor(self, data: dict) -> None:
        # index_1=[0.01,0.20] index_2=[0.005,0.05]：内点 (0.105, 0.0275)
        # 两轴均取半程 → 四角均值（手算独立复核）
        t = data["cells"]["INVX1"]["pins"]["ZN"]["timing"]["A"]["cell_rise"]
        expected = (0.0314605 + 0.0948593 + 0.1090630 + 0.2122158) / 4.0
        assert lookup_table(t, 0.105, 0.0275) == pytest.approx(expected)

    def test_bilinear_axis_linear(self, data: dict) -> None:
        # x1=0.01（首行）、x2=0.0275（半程）→ 首行两列均值
        t = data["cells"]["INVX1"]["pins"]["ZN"]["timing"]["A"]["cell_rise"]
        expected = (0.0314605 + 0.0948593) / 2.0
        assert lookup_table(t, 0.01, 0.0275) == pytest.approx(expected)

    def test_lookup_clamps_outside_range(self, data: dict) -> None:
        # NLDM 惯例：越界按边界夹取
        t = data["cells"]["INVX1"]["pins"]["ZN"]["timing"]["A"]["cell_rise"]
        assert lookup_table(t, -5.0, -5.0) == pytest.approx(0.0314605)
        assert lookup_table(t, 99.0, 99.0) == pytest.approx(0.2122158)

    def test_lookup_one_dimensional(self, data: dict) -> None:
        t = data["cells"]["BUFX2"]["pins"]["Z"]["timing"]["A"]["rise_transition"]
        expected = (0.0200001 + 0.1500002) / 2.0
        assert lookup_table(t, 0.105) == pytest.approx(expected)

    def test_lookup_2d_requires_x2(self, data: dict) -> None:
        t = data["cells"]["INVX1"]["pins"]["ZN"]["timing"]["A"]["cell_rise"]
        with pytest.raises(ValueError, match="x2"):
            lookup_table(t, 0.105)


# ── 功率面 ──────────────────────────────────────────────────────────────────


class TestPower:
    def test_internal_power_tables(self, data: dict) -> None:
        ips = data["cells"]["INVX1"]["pins"]["ZN"]["internal_power"]
        assert len(ips) == 1
        ip = ips[0]
        assert ip["related_pin"] == "A"
        assert ip["rise_power"]["template"] == "power_template_2x2"
        assert ip["rise_power"]["dims"] == 2
        assert ip["fall_power"]["values"][0][0] == pytest.approx(0.700948)

    def test_leakage_power_two_forms(self, data: dict) -> None:
        # 简单属性串（values : "1.234";）与复合属性（values ("2.345");）两写法
        lk = data["cells"]["INVX1"]["leakage_power"]
        assert [(e["value"], e["when"]) for e in lk] == [(1.234, "!A"), (2.345, "A")]


# ── 模板/工况 ───────────────────────────────────────────────────────────────


class TestTemplatesConditions:
    def test_lu_templates(self, data: dict) -> None:
        tpl = data["lu_templates"]["delay_template_2x2"]
        assert tpl["variable_1"] == "input_net_transition"
        assert tpl["variable_2"] == "total_output_net_capacitance"
        assert tpl["index_1"] == [0.01, 0.20]
        assert tpl["index_2"] == [0.005, 0.050]
        assert set(data["lu_templates"]) == {"delay_template_2x2", "power_template_2x2"}

    def test_operating_conditions(self, data: dict) -> None:
        oc = data["operating_conditions"]["TYP_1V25_25C"]
        assert oc["process"] == 1.0
        assert oc["temperature"] == 25.0
        assert oc["voltage"] == 1.25
        assert oc["tree_type"] == "balanced_tree"


# ── 词法保真 ────────────────────────────────────────────────────────────────


class TestLexer:
    def test_comment_with_braces_stripped(self) -> None:
        text = 'library (c) { /* cell (X) { area : 1; } */ area : 2; }'
        lib = parse_liberty(text)
        assert lib.name == "c"
        assert lib.get("area") == 2
        assert lib.find("cell") == []

    def test_function_expression_string_fidelity(self) -> None:
        text = 'library (f) { cell (C) { pin (P) { function : "!(A & B) | C"; } } }'
        data = extract_library(parse_liberty(text))
        assert data["cells"]["C"]["pins"]["P"]["function"] == "!(A & B) | C"

    def test_backslash_line_continuation_in_values(self) -> None:
        text = (
            'library (k) {\n'
            '  cell (C) {\n'
            '    pin (P) {\n'
            '      timing () {\n'
            '        related_pin : "P";\n'
            '        cell_rise (t) {\n'
            '          index_1 ("1, 2");\n'
            '          index_2 ("10, 20");\n'
            '          values ("1.5, 2.5", \\\n'
            '                  "3.5, 4.5");\n'
            '        }\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}\n'
        )
        data = extract_library(parse_liberty(text))
        t = data["cells"]["C"]["pins"]["P"]["timing"]["P"]["cell_rise"]
        assert t["dims"] == 2
        assert t["values"] == [[1.5, 2.5], [3.5, 4.5]]

    def test_one_d_rows_of_one_normalized(self) -> None:
        # N 行单值写法 → 归一为单行
        text = (
            'library (k) {\n'
            '  cell (C) {\n'
            '    pin (P) {\n'
            '      timing () {\n'
            '        related_pin : "P";\n'
            '        rise_transition () {\n'
            '          index_1 ("1, 2");\n'
            '          values ("0.5", "1.5");\n'
            '        }\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}\n'
        )
        data = extract_library(parse_liberty(text))
        t = data["cells"]["C"]["pins"]["P"]["timing"]["P"]["rise_transition"]
        assert t["dims"] == 1
        assert t["values"] == [[0.5, 1.5]]

    def test_zero_dim_table(self) -> None:
        text = (
            'library (k) {\n'
            '  cell (C) {\n'
            '    pin (P) {\n'
            '      timing () {\n'
            '        related_pin : "P";\n'
            '        cell_rise () {\n'
            '          values ("7.25");\n'
            '        }\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}\n'
        )
        data = extract_library(parse_liberty(text))
        t = data["cells"]["C"]["pins"]["P"]["timing"]["P"]["cell_rise"]
        assert t["dims"] == 0
        assert lookup_table(t, 0.0) == 7.25

    def test_include_flags_strip_faces(self, lib: LibertyGroup) -> None:
        data = extract_library(lib, include_timing=False, include_power=False)
        pin = data["cells"]["INVX1"]["pins"]["ZN"]
        assert "timing" not in pin
        assert "internal_power" not in pin
        assert "leakage_power" not in data["cells"]["INVX1"]
        assert data["cells"]["INVX1"]["pins"]["A"]["direction"] == "input"  # 元数据保留


# ── 负例（LibertyParseError 全家福）────────────────────────────────────────


class TestParseErrors:
    def test_unclosed_group(self) -> None:
        with pytest.raises(LibertyParseError, match="未闭合"):
            parse_liberty("library (x) { area : 1;")

    def test_missing_semicolon_eof(self) -> None:
        with pytest.raises(LibertyParseError, match="EOF"):
            parse_liberty("library (x) { area : 1")

    def test_attr_without_value(self) -> None:
        with pytest.raises(LibertyParseError, match="缺值"):
            parse_liberty("library (x) { area : ; }")

    def test_values_shape_mismatch(self) -> None:
        text = (
            'library (k) {\n'
            '  cell (C) {\n'
            '    pin (P) {\n'
            '      timing () {\n'
            '        related_pin : "P";\n'
            '        cell_rise () {\n'
            '          index_1 ("1, 2");\n'
            '          index_2 ("1, 2");\n'
            '          values ("1.0, 2.0");\n'
            '        }\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}\n'
        )
        lib = parse_liberty(text)
        tg = lib.find("cell")[0].find("pin")[0].find("timing")[0]
        with pytest.raises(LibertyParseError, match="不符"):
            extract_table(tg.find("cell_rise")[0])

    def test_one_dim_shape_mismatch(self) -> None:
        text = (
            'library (k) {\n'
            '  cell (C) {\n'
            '    pin (P) {\n'
            '      timing () {\n'
            '        related_pin : "P";\n'
            '        cell_rise () {\n'
            '          index_1 ("1, 2");\n'
            '          values ("1.0");\n'
            '        }\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}\n'
        )
        lib = parse_liberty(text)
        tg = lib.find("cell")[0].find("pin")[0].find("timing")[0]
        with pytest.raises(LibertyParseError, match="一维表"):
            extract_table(tg.find("cell_rise")[0])

    def test_zero_dim_non_scalar_rejected(self) -> None:
        text = (
            'library (k) {\n'
            '  cell (C) {\n'
            '    pin (P) {\n'
            '      timing () {\n'
            '        related_pin : "P";\n'
            '        cell_rise () {\n'
            '          values ("1.0, 2.0");\n'
            '        }\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}\n'
        )
        lib = parse_liberty(text)
        tg = lib.find("cell")[0].find("pin")[0].find("timing")[0]
        with pytest.raises(LibertyParseError, match="零维表"):
            extract_table(tg.find("cell_rise")[0])

    def test_stray_top_level_token(self) -> None:
        # 顶层孤立 '}' 充当收束符后被吞，其后残余 token 才是"多余"红面
        with pytest.raises(LibertyParseError, match="多余"):
            parse_liberty("library (x) { } } area : 1;")

    def test_no_library_group(self) -> None:
        with pytest.raises(LibertyParseError, match="library"):
            parse_liberty("cell (C) { area : 1; }")

    def test_two_libraries_rejected(self) -> None:
        with pytest.raises(LibertyParseError, match="多于一个"):
            parse_liberty("library (a) { } library (b) { }")

    def test_unterminated_string(self) -> None:
        with pytest.raises(LibertyParseError, match="字符串"):
            parse_liberty('library (x) { time_unit : "1ns; }')

    def test_unterminated_comment(self) -> None:
        with pytest.raises(LibertyParseError, match="注释"):
            parse_liberty("library (x) { /* 未闭合 }")

    def test_non_numeric_index_value(self) -> None:
        text = (
            'library (k) {\n'
            '  lu_table_template (t) {\n'
            '    variable_1 : input_net_transition;\n'
            '    index_1 ("1, abc");\n'
            '  }\n'
            '}\n'
        )
        lib = parse_liberty(text)
        with pytest.raises(LibertyParseError, match="非数字"):
            extract_library(lib)


# ── 夹具/索引继承杂项 ───────────────────────────────────────────────────────


class TestMisc:
    def test_template_inherits_into_explicit_empty_index(self) -> None:
        # 表组引用模板名但只给 values → index 全从模板继承（Liberty 惯例）
        text = (
            'library (k) {\n'
            '  lu_table_template (t2x2) {\n'
            '    variable_1 : input_net_transition;\n'
            '    index_1 ("1, 2");\n'
            '    index_2 ("10, 20");\n'
            '  }\n'
            '  cell (C) {\n'
            '    pin (P) {\n'
            '      timing () {\n'
            '        related_pin : "P";\n'
            '        cell_fall (t2x2) {\n'
            '          values ("1, 2", "3, 4");\n'
            '        }\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}\n'
        )
        data = extract_library(parse_liberty(text))
        t = data["cells"]["C"]["pins"]["P"]["timing"]["P"]["cell_fall"]
        assert t["index_1"] == [1.0, 2.0]
        assert t["index_2"] == [10.0, 20.0]
        assert t["dims"] == 2

    def test_fixture_file_exists(self) -> None:
        assert FIXTURE.is_file()
