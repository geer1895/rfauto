"""LEF/DEF 解析内核+服务+CLI 单测（aurora_q Q-X57 席位，2026-11-07）。

覆盖面（任务书 ≥60 条）：

- 词法面：``#`` 词首注释/词中名字、字符串（转义/未闭合容忍）、贴身标点
  ``0.14;``/``(0 0)``、总线位名 ``a(0)`` 一词、关键字大小写容忍 vs 名字
  原文、行号、多行语句（续行）与单行同解、数字字面量白名单；
- LEF 结构逐键：头部/UNITS/MANUFACTURINGGRID、LAYER 字段（TYPE/DIRECTION
  枚举、PITCH 单双值、SPACING 首值+规则原文、未建模语句收原文不记警告）、
  VIA/VIARULE/SITE、MACRO（CLASS 主子类/SIZE/ORIGIN/FOREIGN/SYMMETRY/
  SITE）、PIN（DIRECTION 枚举含 TRISTATE/USE/SHAPE、多 PORT 多 RECT+VIA
  落点 port_index）、OBS 多层、POLYGON/PATH/MASK；
- DEF 结构逐键：头部/DIEAREA（矩形+多边形）/ROW/TRACKS/VIAS、COMPONENTS
  （PLACED/FIXED/UNPLACED/SOURCE/朝向 8 值）、PINS（NET/DIRECTION/USE/
  LAYER 矩形 µm/多 PORT/SPECIAL）、NETS（连接含 PIN、ROUTED 多段+NEW+
  ``*``+VIA、延伸值/RECT/MASK、SYNTHESIZED）、SPECIALNETS（线宽/SHAPE
  续接/通配）、DBU→µm 显式换算（语句序无关预扫、缺 UNITS 如实 None）；
- fail-soft：未知关键字/未知选项 warning、缺 ``;``、缺 END 隐式收尾、
  截断文件逐位置不崩、病态数值降级、节计数对账；
- 拓扑三函数：闭合缺名/闭合/多 LEF 合并、连接度直方图/悬空/单连接/
  未知引用、top-level 引脚对齐差异/不适用/macro 覆盖、实例引脚缺席与
  跳过计数、方向判定不做；
- 服务信封契约（ok/error 同键、空文件/纯注释/不可读/Latin-1）与 CLI
  ``lefdef parse/check``（--json 成败两路信封+exit 码、human 面、树形钉、
  help 字符卫生自检）。CLI 经域根 ``lefdef_app`` 直连（citi/gdsii 同款
  挂账合流形态：本席不碰 cli/main.py，零导入钉随主代接线一同移除）。

单测零网络零真机；一律 chdir 到 tmp_path（#144 家法：run 湖零写入），
夹具全部内嵌文本、文件型用例写 tmp_path。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from rfauto.cli.domains.lefdef import lefdef_app
from rfauto.core.lef_def_parser import (
    LEF_LAYER_TYPES,
    ORIENTATIONS,
    PARSER_SCHEMA_VERSION,
    PIN_DIRECTIONS,
    Token,
    def_component_macro_closure,
    def_net_connectivity,
    def_pin_lef_alignment,
    parse_def,
    parse_lef,
    parse_lefdef_number,
    tokenize_lefdef,
)
from rfauto.service.lef_def_service import (
    ISSUE_KEYS,
    lef_def_check,
    parse_def_file,
    parse_lef_def,
    parse_lef_file,
)

runner = CliRunner()

LEF_TEXT = """\
# 科技+单元 LEF 夹具（Q-X57）
VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;

UNITS
  DATABASE MICRONS 2000 ;
END UNITS

MANUFACTURINGGRID 0.005 ;

LAYER metal1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.19 ;
  WIDTH 0.07 ;
  SPACING 0.065 ;
  SPACING 0.1 RANGE 0.2 10 ;
  THICKNESS 0.13 ;
  RESISTANCE RPERSQ 0.38 ;
END metal1

LAYER via1
  TYPE CUT ;
  SPACING 0.08 ;
  WIDTH 0.07 ;
END via1

LAYER metal2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.19 0.2 ;
  WIDTH 0.07 ;
  SPACING 0.07 ;
END metal2

VIA via1_0 DEFAULT
  RESISTANCE 1.5 ;
  LAYER metal1 ;
    RECT -0.035 -0.065 0.035 0.065 ;
  LAYER via1 ;
    RECT -0.035 -0.035 0.035 0.035 ;
  LAYER metal2 ;
    RECT -0.065 -0.035 0.065 0.035 ;
END via1_0

VIARULE M1_M2 GENERATE
  LAYER metal1 ;
    ENCLOSURE 0 0.035 ;
  LAYER metal2 ;
    ENCLOSURE 0 0.035 ;
  LAYER via1 ;
    RECT -0.035 -0.035 0.035 0.035 ;
    SPACING 0.15 BY 0.15 ;
END M1_M2

SITE core
  CLASS CORE ;
  SYMMETRY Y ;
  SIZE 0.19 BY 1.4 ;
END core

MACRO INV_X1
  CLASS CORE ;
  ORIGIN 0 0 ;
  FOREIGN INV_X1 0 0 ;
  SIZE 0.38 BY 1.4 ;
  SYMMETRY X Y ;
  SITE core ;
  PIN A
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER metal1 ;
        RECT 0.06 0.525 0.15 0.7 ;
    END
  END A
  PIN ZN
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER metal1 ;
        RECT 0.23 0.15 0.32 1.25 ;
        RECT 0.2 0.15 0.32 0.25 ;
    END
  END ZN
  PIN VDD
    DIRECTION INOUT ;
    USE POWER ;
    SHAPE ABUTMENT ;
    PORT
      LAYER metal1 ;
        RECT 0 1.315 0.38 1.485 ;
    END
  END VDD
  PIN VSS
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER metal1 ;
        RECT 0 -0.085 0.38 0.085 ;
    END
  END VSS
  OBS
    LAYER metal1 ;
      RECT 0.1 0.3 0.2 0.4 ;
  END
END INV_X1

MACRO NAND2_X1
  CLASS CORE ;
  SIZE 0.57 BY 1.4 ;
  SITE core ;
  PIN A1
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER metal1 ;
        RECT 0.06 0.525 0.15 0.7 ;
    END
  END A1
  PIN A2
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER metal1 ;
        RECT 0.25 0.525 0.34 0.7 ;
    END
    PORT
      LAYER metal2 ;
        RECT 0.25 0.8 0.34 0.9 ;
        RECT 0.25 0.9 0.4 1.0 ;
      VIA 0.295 0.85 via1_0 ;
    END
  END A2
  PIN ZN
    DIRECTION OUTPUT TRISTATE ;
    USE SIGNAL ;
    PORT
      LAYER metal1 ;
        RECT 0.42 0.15 0.51 1.25 ;
    END
  END ZN
  OBS
    LAYER metal1 ;
      RECT 0.1 0.1 0.2 0.2 ;
      RECT 0.3 0.1 0.4 0.2 ;
    LAYER metal2 ;
      RECT 0.0 0.0 0.57 0.05 ;
  END
END NAND2_X1

MACRO top
  CLASS BLOCK ;
  SIZE 20 BY 10 ;
  PIN in1
    DIRECTION INPUT ;
    PORT
      LAYER metal2 ;
        RECT 0 4.9 0.07 5.1 ;
    END
  END in1
  PIN in2
    DIRECTION OUTPUT ;
    PORT
      LAYER metal2 ;
        RECT 0 6.9 0.07 7.1 ;
    END
  END in2
  PIN out1
    DIRECTION OUTPUT ;
    PORT
      LAYER metal2 ;
        RECT 19.93 4.9 20 5.1 ;
    END
  END out1
  PIN clk
    DIRECTION INPUT ;
    USE CLOCK ;
    PORT
      LAYER metal2 ;
        RECT 10 0 10.07 0.07 ;
    END
  END clk
END top

END LIBRARY
"""

DEF_TEXT = """\
# 设计 DEF 夹具（Q-X57）
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN top ;
UNITS DISTANCE MICRONS 1000 ;

DIEAREA ( 0 0 ) ( 20000 10000 ) ;

ROW ROW_0 core 0 0 N DO 100 BY 1 STEP 190 0 ;
ROW ROW_1 core 0 1400 FS DO 100 BY 1 STEP 190 0 ;

TRACKS X 95 DO 105 STEP 190 LAYER metal2 ;
TRACKS Y 70 DO 71 STEP 140 LAYER metal1 ;

VIAS 1 ;
  - via_big + RECT metal1 ( -70 -70 ) ( 70 70 ) + RECT via1 ( -35 -35 ) ( 35 35 )
    + RECT metal2 ( -70 -70 ) ( 70 70 ) ;
END VIAS

COMPONENTS 4 ;
  - u1 INV_X1 + PLACED ( 1000 0 ) N ;
  - u2 NAND2_X1 + FIXED ( 3000 1400 ) FS ;
  - u3 INV_X1
      + SOURCE NETLIST
      + PLACED ( 5000 0 ) N ;
  - u4 BUF_X1 + UNPLACED ;
END COMPONENTS

PINS 4 ;
  - in1 + NET in1 + DIRECTION INPUT + USE SIGNAL
    + LAYER metal2 ( -35 0 ) ( 35 70 )
    + PLACED ( 0 5000 ) E ;
  - in2 + NET in2 + DIRECTION INPUT + USE SIGNAL
    + LAYER metal2 ( -35 0 ) ( 35 70 ) + FIXED ( 0 7000 ) E ;
  - out1 + NET out1 + DIRECTION OUTPUT + USE SIGNAL
    + LAYER metal2 ( -35 0 ) ( 35 70 ) + PLACED ( 20000 5000 ) W ;
  - VDD + NET VDD + SPECIAL + DIRECTION INOUT + USE POWER ;
END PINS

SPECIALNETS 1 ;
  - VDD ( * VDD ) + USE POWER
    + ROUTED metal1 170 + SHAPE STRIPE ( 0 1400 ) ( 20000 1400 )
      NEW metal1 170 ( 0 4200 ) ( 20000 * ) ;
END SPECIALNETS

NETS 7 ;
  - in1 ( PIN in1 ) ( u1 A ) + USE SIGNAL
    + ROUTED metal2 ( 0 5000 ) ( 1100 * ) via1_0
      NEW metal1 ( 1100 5000 ) ( 1100 600 ) ;
  - in2 ( PIN in2 ) ( u2 A1 ) ;
  - n1 ( u1 ZN ) ( u2 A2 ) ( u3 A )
    + ROUTED metal1 ( 1300 600 ) ( 3300 600 ) via1_0 ( 3300 900 ) ;
  - out1 ( u2 ZN ) ( PIN out1 ) ;
  - n2 ( u3 ZN ) ( u1 Q ) ;
  - n3 ( u4 A ) ;
  - spare ;
END NETS

END DESIGN
"""

#: 闭合+无悬空+零警告的干净 DEF（verdict=clean 用；设计名 blk 无同名
#: macro → top-level 对齐不适用）。
CLEAN_DEF_TEXT = """\
VERSION 5.8 ;
DESIGN blk ;
UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 2 ;
  - u1 INV_X1 + PLACED ( 0 0 ) N ;
  - u2 INV_X1 + PLACED ( 1000 0 ) N ;
END COMPONENTS
NETS 1 ;
  - n1 ( u1 ZN ) ( u2 A ) ;
END NETS
END DESIGN
"""

@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run 湖零写入（#144 家法）：一律 chdir 到 tmp_path。"""
    monkeypatch.chdir(tmp_path)

@pytest.fixture(scope="module")
def lef() -> dict:
    return parse_lef(LEF_TEXT)

@pytest.fixture(scope="module")
def ddef() -> dict:
    return parse_def(DEF_TEXT)

def _warn_names(doc: dict) -> list[str]:
    return [w["name"] for w in doc["warnings"]]

def _write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)

# ── 词法面 ──────────────────────────────────────────────────────────────────

class TestLexer:
    def test_hash_comment_at_token_start(self) -> None:
        toks = tokenize_lefdef("# head\nVERSION 5.8 ; # tail\n")
        assert [t.text for t in toks] == ["VERSION", "5.8", ";"]

    def test_hash_inside_word_is_name(self) -> None:
        toks = tokenize_lefdef("- net#1 ;")
        assert [t.text for t in toks] == ["-", "net#1", ";"]

    def test_string_token_unquoted_and_escape(self) -> None:
        toks = tokenize_lefdef('BUSBITCHARS "[]" ; PROPERTY p "a\\"b" ;')
        strs = [t for t in toks if t.kind == "str"]
        assert [t.text for t in strs] == ["[]", 'a"b']

    def test_unterminated_string_warns_not_raises(self) -> None:
        doc = parse_lef('VERSION 5.8 ;\nBUSBITCHARS "[] ;\n')
        assert "unterminated_string" in _warn_names(doc)
        assert doc["version"] == "5.8"

    def test_tight_punctuation_split(self) -> None:
        toks = tokenize_lefdef("WIDTH 0.14;(0 0)")
        assert [(t.kind, t.text) for t in toks] == [
            ("word", "WIDTH"), ("word", "0.14"), ("punct", ";"),
            ("punct", "("), ("word", "0"), ("word", "0"), ("punct", ")")]

    def test_bus_bit_paren_name_stays_one_word(self) -> None:
        toks = tokenize_lefdef("( u1 a(0) ) ( u2 d[3] )")
        assert [t.text for t in toks] == ["(", "u1", "a(0)", ")", "(", "u2", "d[3]", ")"]

    def test_keyword_key_uppercased_text_preserved(self) -> None:
        tok = tokenize_lefdef("layer")[0]
        assert isinstance(tok, Token)
        assert (tok.kind, tok.text, tok.key) == ("word", "layer", "LAYER")
        assert tokenize_lefdef('"x"')[0].key == ""

    def test_line_numbers(self) -> None:
        toks = tokenize_lefdef("A ;\n\nB\n  C ;")
        assert [(t.text, t.line) for t in toks] == [
            ("A", 1), (";", 1), ("B", 3), ("C", 4), (";", 4)]

    def test_multiline_statement_equals_single_line(self) -> None:
        one = parse_def("UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 1 ;\n"
                        "- u1 INV_X1 + SOURCE NETLIST + PLACED ( 5000 0 ) N ;\nEND COMPONENTS\n")
        many = parse_def("UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 1 ;\n- u1\n INV_X1\n"
                         " + SOURCE NETLIST\n + PLACED\n ( 5000\n 0 )\n N\n ;\nEND COMPONENTS\n")
        strip = [{k: v for k, v in c.items() if k != "line"} for c in one["components"]]
        assert strip == [{k: v for k, v in c.items() if k != "line"} for c in many["components"]]
        assert many["warnings"] == []

    @pytest.mark.parametrize(("text", "expected"), [
        ("2000", 2000), ("-35", -35), ("0.005", 0.005), ("-0.035", -0.035),
        (".5", 0.5), ("1e-3", 0.001), ("4.0E-05", 4.0e-05),
        ("nan", None), ("inf", None), ("abc", None), ("1.2.3", None),
    ])
    def test_number_literal_whitelist(self, text: str, expected: object) -> None:
        val = parse_lefdef_number(text)
        assert val == expected
        if expected is not None:
            assert type(val) is type(expected)

# ── LEF 结构 ────────────────────────────────────────────────────────────────

class TestLefHeader:
    def test_schema_format_and_zero_warnings(self, lef: dict) -> None:
        assert lef["schema"] == f"lef_def/{PARSER_SCHEMA_VERSION}"
        assert lef["format"] == "LEF"
        assert lef["warnings"] == []
        assert lef["ended"] is True

    def test_version_busbit_divider(self, lef: dict) -> None:
        assert (lef["version"], lef["bus_bit_chars"], lef["divider_char"]) == ("5.8", "[]", "/")

    def test_units_and_grid(self, lef: dict) -> None:
        assert lef["units"] == {"database_microns": 2000}
        assert lef["manufacturing_grid_um"] == 0.005

    def test_units_generic_keys(self) -> None:
        doc = parse_lef("UNITS\n DATABASE MICRONS 1000 ;\n CAPACITANCE PICOFARADS 1 ;\n"
                        " TIME NANOSECONDS 1 ;\nEND UNITS\n")
        assert doc["units"] == {"database_microns": 1000,
                                "capacitance_picofarads": 1, "time_nanoseconds": 1}

    def test_stats(self, lef: dict) -> None:
        assert lef["stats"] == {
            "n_tokens": lef["stats"]["n_tokens"], "n_layers": 3,
            "n_routing_layers": 2, "n_cut_layers": 1, "n_vias": 1,
            "n_viarules": 1, "n_sites": 1, "n_macros": 3, "n_pins": 11,
            "n_warnings": 0}

class TestLefLayers:
    def test_layer_order(self, lef: dict) -> None:
        assert [lay["name"] for lay in lef["layers"]] == ["metal1", "via1", "metal2"]

    def test_routing_layer_fields(self, lef: dict) -> None:
        m1 = lef["layers"][0]
        assert (m1["type"], m1["direction"]) == ("ROUTING", "HORIZONTAL")
        assert (m1["pitch_um"], m1["pitch_y_um"], m1["width_um"]) == (0.19, None, 0.07)
        assert (m1["spacing_um"], m1["thickness_um"]) == (0.065, 0.13)

    def test_spacing_first_value_and_all_rules(self, lef: dict) -> None:
        assert lef["layers"][0]["spacing_rules"] == ["SPACING 0.065", "SPACING 0.1 RANGE 0.2 10"]

    def test_cut_layer(self, lef: dict) -> None:
        via1 = lef["layers"][1]
        assert (via1["type"], via1["direction"], via1["spacing_um"], via1["width_um"]) == (
            "CUT", None, 0.08, 0.07)

    def test_pitch_xy(self, lef: dict) -> None:
        m2 = lef["layers"][2]
        assert (m2["direction"], m2["pitch_um"], m2["pitch_y_um"]) == ("VERTICAL", 0.19, 0.2)

    def test_known_unmodeled_statement_kept_raw_no_warning(self, lef: dict) -> None:
        assert lef["layers"][0]["other_statements"] == [
            {"keyword": "RESISTANCE", "raw": "RESISTANCE RPERSQ 0.38", "line": 20}]
        assert lef["warnings"] == []

    @pytest.mark.parametrize("layer_type", LEF_LAYER_TYPES)
    def test_layer_type_enum(self, layer_type: str) -> None:
        doc = parse_lef(f"LAYER x\n TYPE {layer_type.lower()} ;\nEND x\n")
        assert doc["layers"][0]["type"] == layer_type
        assert doc["warnings"] == []

    def test_invalid_layer_type_warns_and_none(self) -> None:
        doc = parse_lef("LAYER x\n TYPE WIRE ;\n WIDTH 0.1 ;\nEND x\n")
        assert doc["layers"][0]["type"] is None
        assert doc["layers"][0]["width_um"] == 0.1
        assert _warn_names(doc) == ["invalid_enum"]

    def test_lowercase_keywords_names_case_preserved(self) -> None:
        doc = parse_lef("layer Metal1\n type routing ;\n direction vertical ;\nend Metal1\n")
        lay = doc["layers"][0]
        assert (lay["name"], lay["type"], lay["direction"]) == ("Metal1", "ROUTING", "VERTICAL")
        assert doc["warnings"] == []

class TestLefViaSite:
    def test_via_default_and_resistance(self, lef: dict) -> None:
        via = lef["vias"][0]
        assert (via["name"], via["default"], via["generated"], via["resistance"]) == (
            "via1_0", True, False, 1.5)

    def test_via_layer_rects(self, lef: dict) -> None:
        layers = lef["vias"][0]["layers"]
        assert [g["layer"] for g in layers] == ["metal1", "via1", "metal2"]
        assert layers[0]["rects"] == [[-0.035, -0.065, 0.035, 0.065]]
        assert layers[2]["rects"] == [[-0.065, -0.035, 0.065, 0.035]]

    def test_viarule_generate_enclosure_spacing(self, lef: dict) -> None:
        rule = lef["viarules"][0]
        assert (rule["name"], rule["generate"], rule["default"]) == ("M1_M2", True, False)
        assert [lay["enclosure_um"] for lay in rule["layers"]] == [[0.0, 0.035], [0.0, 0.035], None]
        cut = rule["layers"][2]
        assert cut["rects"] == [[-0.035, -0.035, 0.035, 0.035]]
        assert cut["spacing_um"] == [0.15, 0.15]

    def test_generated_via_inline_viarule_not_new_block(self) -> None:
        doc = parse_lef("VIA v1\n VIARULE M1M2 ;\n CUTSIZE 0.15 0.15 ;\nEND v1\n"
                        "LAYER m1\n TYPE ROUTING ;\nEND m1\n")
        assert doc["warnings"] == []
        assert [o["keyword"] for o in doc["vias"][0]["other_statements"]] == ["VIARULE", "CUTSIZE"]
        assert doc["viarules"] == []
        assert doc["layers"][0]["name"] == "m1"

    def test_site(self, lef: dict) -> None:
        site = lef["sites"][0]
        assert (site["name"], site["class"], site["symmetry"]) == ("core", "CORE", ["Y"])
        assert site["size"] == {"width_um": 0.19, "height_um": 1.4}

class TestLefMacros:
    def test_macro_order(self, lef: dict) -> None:
        assert lef["macro_order"] == ["INV_X1", "NAND2_X1", "top"]
        assert set(lef["macros"]) == {"INV_X1", "NAND2_X1", "top"}

    def test_macro_header_fields(self, lef: dict) -> None:
        inv = lef["macros"]["INV_X1"]
        assert (inv["class"], inv["class_subtype"], inv["site"]) == ("CORE", None, "core")
        assert inv["size"] == {"width_um": 0.38, "height_um": 1.4}
        assert inv["origin"] == {"x_um": 0.0, "y_um": 0.0}
        assert inv["foreign"] == {"name": "INV_X1", "x_um": 0.0, "y_um": 0.0, "orientation": None}
        assert inv["symmetry"] == ["X", "Y"]

    def test_macro_class_subtype(self) -> None:
        doc = parse_lef("MACRO io\n CLASS PAD INPUT ;\n FOREIGN io 1 2 FN ;\nEND io\n")
        io = doc["macros"]["io"]
        assert (io["class"], io["class_subtype"]) == ("PAD", "INPUT")
        assert io["foreign"] == {"name": "io", "x_um": 1.0, "y_um": 2.0, "orientation": "FN"}

    def test_pin_order_direction_use_shape(self, lef: dict) -> None:
        inv = lef["macros"]["INV_X1"]
        assert inv["pin_order"] == ["A", "ZN", "VDD", "VSS"]
        got = {n: (p["direction"], p["use"], p["shape"]) for n, p in inv["pins"].items()}
        assert got == {"A": ("INPUT", "SIGNAL", None), "ZN": ("OUTPUT", "SIGNAL", None),
                       "VDD": ("INOUT", "POWER", "ABUTMENT"), "VSS": ("INOUT", "GROUND", None)}

    def test_pin_tristate(self, lef: dict) -> None:
        zn = lef["macros"]["NAND2_X1"]["pins"]["ZN"]
        assert (zn["direction"], zn["tristate"]) == ("OUTPUT", True)
        assert lef["macros"]["INV_X1"]["pins"]["ZN"]["tristate"] is False

    def test_port_multi_rect(self, lef: dict) -> None:
        geoms = lef["macros"]["INV_X1"]["pins"]["ZN"]["port_geoms"]
        assert geoms == [{"port_index": 0, "layer": "metal1",
                          "rects": [[0.23, 0.15, 0.32, 1.25], [0.2, 0.15, 0.32, 0.25]],
                          "polygons": [], "paths": []}]

    def test_multi_port_pin_with_via(self, lef: dict) -> None:
        a2 = lef["macros"]["NAND2_X1"]["pins"]["A2"]
        assert a2["n_ports"] == 2
        assert [(g["port_index"], g["layer"], len(g["rects"])) for g in a2["port_geoms"]] == [
            (0, "metal1", 1), (1, "metal2", 2)]
        assert a2["port_vias"] == [{"port_index": 1, "name": "via1_0", "x_um": 0.295, "y_um": 0.85}]

    def test_obs_multi_layer(self, lef: dict) -> None:
        obs = lef["macros"]["NAND2_X1"]["obs_geoms"]
        assert [(g["layer"], g["rects"]) for g in obs] == [
            ("metal1", [[0.1, 0.1, 0.2, 0.2], [0.3, 0.1, 0.4, 0.2]]),
            ("metal2", [[0.0, 0.0, 0.57, 0.05]])]
        assert "port_index" not in obs[0]

    @pytest.mark.parametrize("direction", PIN_DIRECTIONS)
    def test_pin_direction_enum_case_tolerant(self, direction: str) -> None:
        doc = parse_lef(f"MACRO c\n PIN p\n  DIRECTION {direction.lower()} ;\n END p\nEND c\n")
        assert doc["macros"]["c"]["pins"]["p"]["direction"] == direction
        assert doc["warnings"] == []

    def test_invalid_pin_direction_warns_none(self) -> None:
        doc = parse_lef("MACRO c\n PIN p\n  DIRECTION BIDIR ;\n  USE SIGNAL ;\n END p\nEND c\n")
        pin = doc["macros"]["c"]["pins"]["p"]
        assert (pin["direction"], pin["use"]) == (None, "SIGNAL")
        assert _warn_names(doc) == ["invalid_enum"]

    def test_polygon_path_and_mask(self) -> None:
        doc = parse_lef("MACRO c\n OBS\n  LAYER m1 ;\n   POLYGON 0 0 1 0 1 1 ;\n"
                        "   WIDTH 0.2 ;\n   PATH 0 0 2 0 ;\n   RECT MASK 1 0 0 3 3 ;\n END\nEND c\n")
        g = doc["macros"]["c"]["obs_geoms"][0]
        assert g["polygons"] == [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]]
        assert g["paths"] == [{"width_um": 0.2, "points": [[0.0, 0.0], [2.0, 0.0]]}]
        assert g["rects"] == [[0.0, 0.0, 3.0, 3.0]]
        assert doc["warnings"] == []

    def test_duplicate_macro_warns_later_overrides(self) -> None:
        doc = parse_lef("MACRO c\n CLASS CORE ;\nEND c\nMACRO c\n CLASS BLOCK ;\nEND c\n")
        assert doc["macro_order"] == ["c"]
        assert doc["macros"]["c"]["class"] == "BLOCK"
        assert _warn_names(doc) == ["duplicate_macro"]

# ── DEF 结构 ────────────────────────────────────────────────────────────────

class TestDefHeader:
    def test_schema_header_zero_warnings(self, ddef: dict) -> None:
        assert (ddef["format"], ddef["version"], ddef["design_name"]) == ("DEF", "5.8", "top")
        assert (ddef["divider_char"], ddef["bus_bit_chars"]) == ("/", "[]")
        assert ddef["units"] == {"distance_microns": 1000}
        assert ddef["warnings"] == []
        assert ddef["ended"] is True

    def test_die_area_rectangle(self, ddef: dict) -> None:
        die = ddef["die_area"]
        assert die["points_dbu"] == [[0, 0], [20000, 10000]]
        assert die["bbox_um"] == [0.0, 0.0, 20.0, 10.0]
        assert die["is_rectangle"] is True

    def test_die_area_polygon(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 100 ;\n"
                        "DIEAREA ( 0 0 ) ( 0 500 ) ( 300 500 ) ( 300 200 ) ( 600 200 ) ( 600 0 ) ;\n")
        die = doc["die_area"]
        assert die["is_rectangle"] is False
        assert die["bbox_dbu"] == [0, 0, 600, 500]
        assert die["bbox_um"] == [0.0, 0.0, 6.0, 5.0]

    def test_rows(self, ddef: dict) -> None:
        row0, row1 = ddef["rows"]
        assert (row0["name"], row0["site"], row0["orientation"]) == ("ROW_0", "core", "N")
        assert (row0["num_x"], row0["num_y"], row0["step_x_um"], row0["step_y_um"]) == (
            100, 1, 0.19, 0.0)
        assert (row1["y_dbu"], row1["y_um"], row1["orientation"]) == (1400, 1.4, "FS")

    def test_tracks(self, ddef: dict) -> None:
        tx, ty = ddef["tracks"]
        assert (tx["direction"], tx["start_um"], tx["num"], tx["step_um"], tx["layers"]) == (
            "X", 0.095, 105, 0.19, ["metal2"])
        assert (ty["direction"], ty["start_dbu"], ty["layers"]) == ("Y", 70, ["metal1"])

    def test_dbu_conversion_explicit(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 2000 ;\nCOMPONENTS 1 ;\n"
                        "- u1 c + PLACED ( 1000 -3000 ) S ;\nEND COMPONENTS\n")
        comp = doc["components"][0]
        assert (comp["x_dbu"], comp["y_dbu"], comp["x_um"], comp["y_um"]) == (1000, -3000, 0.5, -1.5)

    def test_units_after_coordinates_still_converted(self) -> None:
        doc = parse_def("COMPONENTS 1 ;\n- u1 c + PLACED ( 2500 0 ) N ;\nEND COMPONENTS\n"
                        "UNITS DISTANCE MICRONS 1000 ;\n")
        assert doc["components"][0]["x_um"] == 2.5
        assert "missing_units" not in _warn_names(doc)

    def test_missing_units_um_none_and_warning(self) -> None:
        doc = parse_def("DESIGN t ;\nDIEAREA ( 0 0 ) ( 100 100 ) ;\nCOMPONENTS 1 ;\n"
                        "- u1 c + PLACED ( 10 20 ) N ;\nEND COMPONENTS\nEND DESIGN\n")
        assert doc["units"]["distance_microns"] is None
        assert (doc["components"][0]["x_dbu"], doc["components"][0]["x_um"]) == (10, None)
        assert doc["die_area"]["points_um"] is None
        assert _warn_names(doc) == ["missing_units"]

    def test_stats_and_section_counts(self, ddef: dict) -> None:
        stats = ddef["stats"]
        assert (stats["n_components"], stats["n_placed"], stats["n_unplaced"]) == (4, 3, 1)
        assert (stats["n_pins"], stats["n_nets"], stats["n_specialnets"]) == (4, 7, 1)
        assert (stats["n_conns"], stats["n_route_segments"], stats["n_warnings"]) == (13, 5, 0)
        assert ddef["section_counts"] == {
            "VIAS": {"declared": 1, "parsed": 1}, "COMPONENTS": {"declared": 4, "parsed": 4},
            "PINS": {"declared": 4, "parsed": 4}, "SPECIALNETS": {"declared": 1, "parsed": 1},
            "NETS": {"declared": 7, "parsed": 7}}

class TestDefComponents:
    def test_placed(self, ddef: dict) -> None:
        u1 = ddef["components"][0]
        assert {k: u1[k] for k in ("name", "model", "status", "x_dbu", "y_dbu",
                                   "x_um", "y_um", "orientation", "source")} == {
            "name": "u1", "model": "INV_X1", "status": "PLACED", "x_dbu": 1000,
            "y_dbu": 0, "x_um": 1.0, "y_um": 0.0, "orientation": "N", "source": None}

    def test_fixed_fs(self, ddef: dict) -> None:
        u2 = ddef["components"][1]
        assert (u2["status"], u2["x_um"], u2["y_um"], u2["orientation"]) == ("FIXED", 3.0, 1.4, "FS")

    def test_source_multiline_entry(self, ddef: dict) -> None:
        u3 = ddef["components"][2]
        assert (u3["source"], u3["status"], u3["x_um"]) == ("NETLIST", "PLACED", 5.0)

    def test_unplaced(self, ddef: dict) -> None:
        u4 = ddef["components"][3]
        assert (u4["model"], u4["status"], u4["x_dbu"], u4["orientation"]) == (
            "BUF_X1", "UNPLACED", None, None)

    @pytest.mark.parametrize("orient", ORIENTATIONS)
    def test_orientation_enum(self, orient: str) -> None:
        doc = parse_def(f"UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 1 ;\n"
                        f"- u1 c + PLACED ( 0 0 ) {orient.lower()} ;\nEND COMPONENTS\n")
        assert doc["components"][0]["orientation"] == orient
        assert doc["warnings"] == []

    def test_invalid_orientation_warns_component_kept(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 1 ;\n"
                        "- u1 c + PLACED ( 5 5 ) R90 ;\nEND COMPONENTS\n")
        comp = doc["components"][0]
        assert (comp["status"], comp["x_dbu"], comp["orientation"]) == ("PLACED", 5, None)
        assert _warn_names(doc) == ["invalid_enum"]

    def test_section_count_mismatch_warns(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 3 ;\n"
                        "- u1 c + UNPLACED ;\nEND COMPONENTS\n")
        assert doc["section_counts"]["COMPONENTS"] == {"declared": 3, "parsed": 1}
        assert _warn_names(doc) == ["count_mismatch"]

class TestDefPins:
    def test_pin_fields(self, ddef: dict) -> None:
        in1 = ddef["pins"][0]
        assert {k: in1[k] for k in ("name", "net", "special", "direction", "use",
                                    "status", "x_um", "y_um", "orientation")} == {
            "name": "in1", "net": "in1", "special": False, "direction": "INPUT",
            "use": "SIGNAL", "status": "PLACED", "x_um": 0.0, "y_um": 5.0, "orientation": "E"}

    def test_pin_layer_rect_relative_um(self, ddef: dict) -> None:
        geom = ddef["pins"][0]["layer_geoms"]
        assert geom == [{"port_index": 0, "layer": "metal2", "kind": "rect",
                         "rect_dbu": [-35, 0, 35, 70], "rect_um": [-0.035, 0.0, 0.035, 0.07]}]

    def test_fixed_and_output_pins(self, ddef: dict) -> None:
        in2, out1 = ddef["pins"][1], ddef["pins"][2]
        assert (in2["status"], in2["y_um"]) == ("FIXED", 7.0)
        assert (out1["direction"], out1["x_um"], out1["orientation"]) == ("OUTPUT", 20.0, "W")

    def test_special_pin_without_placement(self, ddef: dict) -> None:
        vdd = ddef["pins"][3]
        assert (vdd["special"], vdd["use"], vdd["status"], vdd["placements"]) == (
            True, "POWER", None, [])

    def test_multi_port_pin(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 1000 ;\nPINS 1 ;\n- p + NET n\n"
                        " + PORT + LAYER m1 ( 0 0 ) ( 10 10 ) + PLACED ( 100 0 ) N\n"
                        " + PORT + LAYER m2 ( 0 0 ) ( 20 20 ) + FIXED ( 300 0 ) S ;\nEND PINS\n")
        pin = doc["pins"][0]
        assert [(g["port_index"], g["layer"]) for g in pin["layer_geoms"]] == [(0, "m1"), (1, "m2")]
        assert [(p["port_index"], p["status"], p["x_um"]) for p in pin["placements"]] == [
            (0, "PLACED", 0.1), (1, "FIXED", 0.3)]
        assert (pin["status"], pin["x_um"]) == ("PLACED", 0.1)

class TestDefNets:
    def test_conns_including_toplevel_pin(self, ddef: dict) -> None:
        nets = {n["name"]: n for n in ddef["nets"]}
        assert nets["in1"]["conns"] == [["PIN", "in1"], ["u1", "A"]]
        assert nets["n1"]["conns"] == [["u1", "ZN"], ["u2", "A2"], ["u3", "A"]]
        assert nets["spare"]["conns"] == []

    def test_routed_multi_segment_new_star_via(self, ddef: dict) -> None:
        routes = ddef["nets"][0]["routes"]
        assert [(r["status"], r["layer"]) for r in routes] == [("ROUTED", "metal2"), ("ROUTED", "metal1")]
        assert routes[0]["points_dbu"] == [[0, 5000], [1100, 5000]]  # '*' 沿用前点 y
        assert routes[0]["points_um"] == [[0.0, 5.0], [1.1, 5.0]]
        assert routes[0]["vias"] == [{"name": "via1_0", "x_dbu": 1100, "y_dbu": 5000,
                                      "x_um": 1.1, "y_um": 5.0, "orientation": None}]
        assert routes[1]["points_dbu"] == [[1100, 5000], [1100, 600]]

    def test_via_mid_path(self, ddef: dict) -> None:
        n1 = ddef["nets"][2]["routes"][0]
        assert n1["points_dbu"] == [[1300, 600], [3300, 600], [3300, 900]]
        assert [(v["name"], v["x_dbu"], v["y_dbu"]) for v in n1["vias"]] == [("via1_0", 3300, 600)]

    def test_net_use(self, ddef: dict) -> None:
        assert [n["use"] for n in ddef["nets"]][:2] == ["SIGNAL", None]

    def test_specialnet_width_shape_new_star(self, ddef: dict) -> None:
        vdd = ddef["specialnets"][0]
        assert (vdd["special"], vdd["conns"], vdd["use"]) == (True, [["*", "VDD"]], "POWER")
        seg0, seg1 = vdd["routes"]
        assert (seg0["width_dbu"], seg0["width_um"], seg0["shape"]) == (170, 0.17, "STRIPE")
        assert seg0["points_dbu"] == [[0, 1400], [20000, 1400]]
        assert (seg1["shape"], seg1["points_dbu"]) == (None, [[0, 4200], [20000, 4200]])

    def test_route_extension_rect_mask_taper(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 1000 ;\nNETS 1 ;\n- n ( a b )\n"
                        " + ROUTED m2 TAPER ( 0 0 0 ) ( * 500 ) M1M2\n"
                        " NEW m1 ( 0 500 ) RECT ( -5 -5 5 5 )\n"
                        " NEW m1 STYLE 2 ( 0 500 ) MASK 2 ( 900 * ) ;\nEND NETS\n")
        segs = doc["nets"][0]["routes"]
        assert segs[0]["points_dbu"] == [[0, 0], [0, 500]]
        assert segs[0]["vias"][0]["name"] == "M1M2"
        assert segs[1]["rects_dbu"] == [[-5, -5, 5, 5]]
        assert (segs[2]["style"], segs[2]["points_dbu"]) == ("2", [[0, 500], [900, 500]])
        assert doc["warnings"] == []

    def test_synthesized_marker_stripped(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 1000 ;\nNETS 1 ;\n"
                        "- n ( u1 A + SYNTHESIZED ) ( u2 B ) ;\nEND NETS\n")
        assert doc["nets"][0]["conns"] == [["u1", "A"], ["u2", "B"]]
        assert doc["warnings"] == []

    def test_def_vias_rect_and_viarule(self, ddef: dict) -> None:
        via = ddef["vias"][0]
        assert (via["name"], [r["layer"] for r in via["rects"]]) == (
            "via_big", ["metal1", "via1", "metal2"])
        assert via["rects"][1]["rect_um"] == [-0.035, -0.035, 0.035, 0.035]
        gen = parse_def("UNITS DISTANCE MICRONS 1000 ;\nVIAS 1 ;\n- v + VIARULE R1"
                        " + CUTSIZE 200 200 + LAYERS m1 c1 m2 ;\nEND VIAS\n")["vias"][0]
        assert gen["viarule"] == "R1"
        assert gen["rule_params"] == {"CUTSIZE": ["200", "200"], "LAYERS": ["m1", "c1", "m2"]}

# ── fail-soft ───────────────────────────────────────────────────────────────

class TestFailSoft:
    def test_unknown_lef_statements_warn_and_continue(self) -> None:
        doc = parse_lef("VERSION 5.8 ;\nFOOBAR 1 2 ;\nMACRO c\n BOGUS x ;\n CLASS CORE ;\nEND c\n")
        assert _warn_names(doc) == ["unknown_statement", "unknown_statement"]
        assert [w["line"] for w in doc["warnings"]] == [2, 4]
        assert doc["other_statements"] == [{"keyword": "FOOBAR", "raw": "FOOBAR 1 2", "line": 2}]
        assert doc["macros"]["c"]["class"] == "CORE"

    def test_unknown_def_statement_and_option(self) -> None:
        doc = parse_def("DESIGN t ;\nUNITS DISTANCE MICRONS 1000 ;\nWIDGET 3 ;\nCOMPONENTS 1 ;\n"
                        "- u1 c + FROB 3 + PLACED ( 0 0 ) N ;\nEND COMPONENTS\nEND DESIGN\n")
        assert _warn_names(doc) == ["unknown_statement", "unknown_option"]
        comp = doc["components"][0]
        assert (comp["status"], comp["other_options"]) == (
            "PLACED", [{"keyword": "FROB", "raw": "FROB 3"}])

    def test_missing_semicolon_stops_at_end(self) -> None:
        doc = parse_lef("LAYER m1\n TYPE ROUTING\nEND m1\nLAYER m2\n TYPE CUT ;\nEND m2\n")
        assert [(lay["name"], lay["type"]) for lay in doc["layers"]] == [("m1", "ROUTING"), ("m2", "CUT")]
        assert _warn_names(doc) == ["missing_semicolon"]

    def test_missing_end_closed_by_next_block_header(self) -> None:
        doc = parse_lef("LAYER m1\n TYPE ROUTING ;\nLAYER m2\n TYPE ROUTING ;\nEND m2\n")
        assert [lay["name"] for lay in doc["layers"]] == ["m1", "m2"]
        assert _warn_names(doc) == ["unterminated_block"]

    def test_port_missing_end_closed_by_pin_end(self) -> None:
        doc = parse_lef("MACRO c\n PIN a\n  PORT\n   LAYER m1 ;\n   RECT 0 0 1 1 ;\n END a\n"
                        " PIN b\n  DIRECTION OUTPUT ;\n END b\nEND c\n")
        pins = doc["macros"]["c"]["pins"]
        assert pins["a"]["port_geoms"][0]["rects"] == [[0.0, 0.0, 1.0, 1.0]]
        assert pins["b"]["direction"] == "OUTPUT"
        assert _warn_names(doc) == ["unterminated_block"]

    def test_pin_missing_end_closed_by_next_pin(self) -> None:
        doc = parse_lef("MACRO c\n PIN a\n  DIRECTION INPUT ;\n PIN b\n  DIRECTION OUTPUT ;\n"
                        " END b\nEND c\n")
        assert doc["macros"]["c"]["pin_order"] == ["a", "b"]
        assert _warn_names(doc) == ["unterminated_block"]

    def test_bad_number_statement_dropped_rest_kept(self) -> None:
        doc = parse_lef("MACRO c\n OBS\n  LAYER m1 ;\n  RECT 0 0 abc 1 ;\n  RECT 0 0 1 1 ;\n END\nEND c\n")
        assert doc["macros"]["c"]["obs_geoms"][0]["rects"] == [[0.0, 0.0, 1.0, 1.0]]
        assert _warn_names(doc) == ["statement_parse_failed"]

    def test_bad_point_option_dropped_entry_kept(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 1 ;\n"
                        "- u1 c + SOURCE USER + PLACED ( 0 x ) N ;\nEND COMPONENTS\n")
        comp = doc["components"][0]
        assert (comp["name"], comp["source"], comp["status"]) == ("u1", "USER", None)
        assert _warn_names(doc) == ["option_parse_failed"]

    def test_section_missing_end_closed_by_next_section(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 1 ;\n- u1 c + UNPLACED ;\n"
                        "NETS 1 ;\n- n1 ( u1 a ) ;\nEND NETS\nEND DESIGN\n")
        assert (len(doc["components"]), len(doc["nets"])) == (1, 1)
        assert _warn_names(doc) == ["unterminated_section"]

    def test_entry_missing_semicolon_stops_at_dash(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 2 ;\n"
                        "- u1 c + PLACED ( 0 0 ) N\n- u2 c + PLACED ( 1 1 ) S ;\nEND COMPONENTS\n")
        assert [c["name"] for c in doc["components"]] == ["u1", "u2"]
        assert _warn_names(doc) == ["missing_semicolon"]

    @pytest.mark.parametrize("which", ["lef", "def"])
    def test_truncated_files_never_raise(self, which: str) -> None:
        text, fn = (LEF_TEXT, parse_lef) if which == "lef" else (DEF_TEXT, parse_def)
        for cut in range(0, len(text), 11):
            doc = fn(text[:cut])
            assert isinstance(doc["warnings"], list)
            assert doc["stats"]["n_warnings"] == len(doc["warnings"])

    def test_trailing_after_end_design(self) -> None:
        doc = parse_def("DESIGN t ;\nUNITS DISTANCE MICRONS 1000 ;\nEND DESIGN\nextra ;\n")
        assert doc["ended"] is True
        assert _warn_names(doc) == ["trailing_after_end"]

    def test_known_blocks_skipped_and_recorded(self) -> None:
        lef_doc = parse_lef("PROPERTYDEFINITIONS\n MACRO CLASS STRING ;\nEND PROPERTYDEFINITIONS\n"
                            "NONDEFAULTRULE ndr\n LAYER m1\n  WIDTH 0.2 ;\n END m1\nEND ndr\n"
                            "LAYER m1\n TYPE ROUTING ;\nEND m1\n")
        assert [(b["keyword"], b["name"]) for b in lef_doc["skipped_blocks"]] == [
            ("PROPERTYDEFINITIONS", None), ("NONDEFAULTRULE", "ndr")]
        assert [lay["name"] for lay in lef_doc["layers"]] == ["m1"]
        def_doc = parse_def("UNITS DISTANCE MICRONS 1000 ;\nBLOCKAGES 1 ;\n"
                            "- LAYER m1 RECT ( 0 0 ) ( 1 1 ) ;\nEND BLOCKAGES\nEND DESIGN\n")
        assert [s["keyword"] for s in def_doc["skipped_sections"]] == ["BLOCKAGES"]
        assert lef_doc["warnings"] == [] and def_doc["warnings"] == []

    def test_no_recognized_constructs_warning(self) -> None:
        doc = parse_lef("hello world ;\n")
        assert _warn_names(doc) == ["unknown_statement", "no_recognized_constructs"]

    def test_deterministic(self) -> None:
        a = json.dumps(parse_def(DEF_TEXT), sort_keys=True)
        b = json.dumps(parse_def(DEF_TEXT), sort_keys=True)
        assert a == b

# ── 拓扑三函数 ──────────────────────────────────────────────────────────────

class TestTopology:
    def test_closure_missing_model(self, lef: dict, ddef: dict) -> None:
        res = def_component_macro_closure(ddef, lef)
        assert res["closed"] is False
        assert res["models_used"] == ["BUF_X1", "INV_X1", "NAND2_X1"]
        assert res["missing_models"] == ["BUF_X1"]
        assert res["components_missing_model"] == {"BUF_X1": ["u4"]}
        assert (res["n_components"], res["n_components_missing_model"]) == (4, 1)
        assert res["unused_lef_macros"] == ["top"]

    def test_closure_closed(self, lef: dict) -> None:
        res = def_component_macro_closure(parse_def(CLEAN_DEF_TEXT), lef)
        assert (res["closed"], res["missing_models"], res["n_models"]) == (True, [], 1)

    def test_closure_multi_lef_merge(self, lef: dict, ddef: dict) -> None:
        buf = parse_lef("MACRO BUF_X1\n CLASS CORE ;\n PIN A\n  DIRECTION INPUT ;\n END A\nEND BUF_X1\n")
        assert def_component_macro_closure(ddef, [lef, buf])["closed"] is True

    def test_connectivity_histogram_dangling_single(self, ddef: dict) -> None:
        res = def_net_connectivity(ddef)
        assert res["degree_histogram"] == [[0, 1], [1, 1], [2, 4], [3, 1]]
        assert (res["max_degree"], res["dangling_nets"], res["single_connection_nets"]) == (
            3, ["spare"], ["n3"])
        rows = {r["name"]: r for r in res["nets"]}
        assert (rows["in1"]["n_pin_conns"], rows["in1"]["n_component_conns"]) == (1, 1)
        assert (rows["in1"]["routed"], rows["in1"]["n_route_segments"]) == (True, 2)

    def test_connectivity_clean_refs(self, ddef: dict) -> None:
        res = def_net_connectivity(ddef)
        assert res["unknown_component_refs"] == []
        assert res["unknown_toplevel_pin_refs"] == []
        assert res["pins_with_unknown_net"] == [] and res["pins_without_net"] == []

    def test_connectivity_unknown_refs(self) -> None:
        doc = parse_def("UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 1 ;\n- u1 c + UNPLACED ;\n"
                        "END COMPONENTS\nPINS 2 ;\n- p1 + NET ghost ;\n- p2 + DIRECTION INPUT ;\n"
                        "END PINS\nNETS 1 ;\n- n1 ( u1 a ) ( u9 b ) ( PIN pX ) ;\nEND NETS\n")
        res = def_net_connectivity(doc)
        assert res["unknown_component_refs"] == [["n1", "u9", "b"]]
        assert res["unknown_toplevel_pin_refs"] == [["n1", "pX"]]
        assert res["pins_with_unknown_net"] == [["p1", "ghost"]]
        assert res["pins_without_net"] == ["p2"]

    def test_connectivity_specialnet_wildcard(self, ddef: dict) -> None:
        res = def_net_connectivity(ddef)
        assert res["specialnets"] == [{"name": "VDD", "degree": 1, "wildcard_conns": 1,
                                       "n_route_segments": 2, "use": "POWER"}]

    def test_no_direction_analysis(self, ddef: dict) -> None:
        res = def_net_connectivity(ddef)
        assert res["direction_analysis"] is None
        assert "驱动" in res["note"]

    def test_alignment_top_level_diffs(self, lef: dict, ddef: dict) -> None:
        top = def_pin_lef_alignment(ddef, lef)["top_level"]
        assert (top["macro"], top["applicable"], top["reason"]) == ("top", True, None)
        assert top["missing_in_lef"] == ["VDD"]
        assert top["missing_in_def"] == ["clk"]
        assert top["direction_mismatches"] == [
            {"pin": "in2", "def_direction": "INPUT", "lef_direction": "OUTPUT"}]

    def test_alignment_not_applicable(self, lef: dict) -> None:
        top = def_pin_lef_alignment(parse_def(CLEAN_DEF_TEXT), lef)["top_level"]
        assert (top["macro"], top["applicable"]) == ("blk", False)
        assert "blk" in top["reason"]
        assert top["missing_in_lef"] == [] and top["missing_in_def"] == []

    def test_alignment_macro_override(self, lef: dict, ddef: dict) -> None:
        top = def_pin_lef_alignment(ddef, lef, macro="INV_X1")["top_level"]
        assert top["applicable"] is True
        # INV_X1 自带 VDD（DEF VDD 两侧都有且方向同为 INOUT → 不缺席不失配）
        assert top["missing_in_lef"] == ["in1", "in2", "out1"]
        assert top["missing_in_def"] == ["A", "ZN", "VSS"]
        assert top["direction_mismatches"] == []

    def test_alignment_instance_pins(self, lef: dict, ddef: dict) -> None:
        inst = def_pin_lef_alignment(ddef, lef)["instance_pins"]
        assert (inst["checked_refs"], inst["skipped_refs"]) == (8, 1)
        assert inst["unknown_pin_refs"] == [
            {"net": "n2", "component": "u1", "model": "INV_X1", "pin": "Q"}]

# ── 服务信封 ────────────────────────────────────────────────────────────────

class TestService:
    def test_parse_lef_file_ok(self, tmp_path: Path) -> None:
        env = parse_lef_file(_write(tmp_path, "cells.lef", LEF_TEXT))
        assert env["ok"] is True
        assert env["path"].endswith("cells.lef")
        assert (env["format"], env["stats"]["n_macros"]) == ("LEF", 3)

    def test_parse_def_file_ok(self, tmp_path: Path) -> None:
        env = parse_def_file(_write(tmp_path, "top.def", DEF_TEXT))
        assert (env["ok"], env["format"], env["design_name"]) == (True, "DEF", "top")

    def test_missing_file_error_envelope(self) -> None:
        env = parse_lef_file("no_such_file.lef")
        assert env["ok"] is False
        assert isinstance(env["errors"], list) and len(env["errors"]) == 1
        assert "不可读" in env["errors"][0]
        assert (env["path"], env["format"]) == ("no_such_file.lef", "LEF")

    def test_empty_file_error_envelope(self, tmp_path: Path) -> None:
        env = parse_def_file(_write(tmp_path, "empty.def", ""))
        assert env["ok"] is False
        assert "为空" in env["errors"][0]

    def test_comment_only_file_is_empty(self, tmp_path: Path) -> None:
        env = parse_lef_file(_write(tmp_path, "c.lef", "# only\n   # comments\n"))
        assert env["ok"] is False and "为空" in env["errors"][0]

    def test_latin1_fallback(self, tmp_path: Path) -> None:
        path = tmp_path / "l1.lef"
        path.write_bytes(b"# caf\xe9\nVERSION 5.8 ;\n")
        env = parse_lef_file(str(path))
        assert (env["ok"], env["version"]) == (True, "5.8")

    def test_parse_lef_def_combo(self, tmp_path: Path) -> None:
        env = parse_lef_def([_write(tmp_path, "a.lef", LEF_TEXT)], _write(tmp_path, "t.def", DEF_TEXT))
        assert env["ok"] is True
        assert len(env["lef"]) == 1 and env["lef"][0]["ok"] is True
        assert env["def"]["design_name"] == "top"
        only_def = parse_lef_def(None, _write(tmp_path, "t2.def", DEF_TEXT))
        assert (only_def["ok"], only_def["lef"]) == (True, [])

    def test_parse_lef_def_errors(self, tmp_path: Path) -> None:
        none = parse_lef_def(None, None)
        assert (none["ok"], none["lef"], none["def"]) == (False, [], None)
        bad = parse_lef_def(["missing.lef"], _write(tmp_path, "t.def", DEF_TEXT))
        assert bad["ok"] is False and len(bad["errors"]) == 1
        assert bad["def"]["ok"] is True  # 逐文件信封保留供定位

    def test_check_issues_verdict(self, tmp_path: Path) -> None:
        env = lef_def_check([_write(tmp_path, "a.lef", LEF_TEXT)], _write(tmp_path, "t.def", DEF_TEXT))
        assert (env["ok"], env["verdict"], env["design_name"]) == (True, "issues", "top")
        summary = env["summary"]
        assert {k: summary[k] for k in ISSUE_KEYS} == {
            "missing_models": 1, "unknown_component_refs": 0,
            "unknown_toplevel_pin_refs": 0, "pins_with_unknown_net": 0,
            "unknown_pin_refs": 1, "top_level_missing_in_lef": 1,
            "top_level_missing_in_def": 1, "direction_mismatches": 1}
        assert (summary["dangling_nets"], summary["parse_warnings"]) == (1, 0)
        assert env["units"] == {"lef_database_microns": [2000], "def_distance_microns": 1000}

    def test_check_clean_verdict_multi_lef(self, tmp_path: Path) -> None:
        tech = "VERSION 5.8 ;\nLAYER metal1\n TYPE ROUTING ;\nEND metal1\n"
        env = lef_def_check([_write(tmp_path, "tech.lef", tech), _write(tmp_path, "c.lef", LEF_TEXT)],
                            _write(tmp_path, "blk.def", CLEAN_DEF_TEXT))
        assert (env["ok"], env["verdict"]) == (True, "clean")
        assert env["units"]["lef_database_microns"] == [None, 2000]
        assert [w["path"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for w in env["warnings"]["lef"]] == [
            "tech.lef", "c.lef"]

    def test_check_attention_verdict(self, tmp_path: Path) -> None:
        text = CLEAN_DEF_TEXT.replace("NETS 1 ;", "NETS 2 ;").replace(
            "END NETS", "  - spare ;\nEND NETS")
        env = lef_def_check(_write(tmp_path, "c.lef", LEF_TEXT), _write(tmp_path, "b.def", text))
        assert env["verdict"] == "attention"
        assert env["connectivity"]["dangling_nets"] == ["spare"]

    def test_check_missing_inputs_isomorphic_keys(self, tmp_path: Path) -> None:
        ok_env = lef_def_check([_write(tmp_path, "c.lef", LEF_TEXT)], _write(tmp_path, "b.def", CLEAN_DEF_TEXT))
        err_env = lef_def_check(None, None)
        assert err_env["ok"] is False and len(err_env["errors"]) == 2
        assert set(err_env) - {"errors"} == set(ok_env)
        assert err_env["verdict"] is None

# ── CLI ─────────────────────────────────────────────────────────────────────

class TestCli:
    """域根 ``lefdef_app`` 直连（挂账合流形态：参数序=叶名起，无顶层 lefdef 前缀）。"""

    def test_parse_json_full_envelope(self, tmp_path: Path) -> None:
        r = runner.invoke(lefdef_app, ["parse", "--lef", _write(tmp_path, "a.lef", LEF_TEXT),
                                       "--def", _write(tmp_path, "t.def", DEF_TEXT), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["lef"][0]["macro_order"] == ["INV_X1", "NAND2_X1", "top"]
        assert payload["def"]["stats"]["n_nets"] == 7

    def test_parse_json_repeated_lef(self, tmp_path: Path) -> None:
        r = runner.invoke(lefdef_app, ["parse", "--lef", _write(tmp_path, "a.lef", LEF_TEXT),
                                       "--lef", _write(tmp_path, "b.lef", "VERSION 5.7 ;\n"), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert [e["version"] for e in payload["lef"]] == ["5.8", "5.7"]
        assert payload["def"] is None

    def test_parse_human_output(self, tmp_path: Path) -> None:
        r = runner.invoke(lefdef_app, ["parse", "--lef", _write(tmp_path, "a.lef", LEF_TEXT),
                                       "--def", _write(tmp_path, "t.def", DEF_TEXT)])
        assert r.exit_code == 0, r.output
        assert "LEF" in r.output and "macro INV_X1" in r.output
        assert "design=top" in r.output

    def test_parse_failure_json_envelope_exit1(self) -> None:
        r = runner.invoke(lefdef_app, ["parse", "--lef", "no_such.lef", "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False and isinstance(payload["errors"], list)

    def test_parse_no_input_json_envelope_exit1(self) -> None:
        r = runner.invoke(lefdef_app, ["parse", "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert (payload["ok"], payload["lef"], payload["def"]) == (False, [], None)

    def test_parse_failure_human_exit1(self) -> None:
        r = runner.invoke(lefdef_app, ["parse", "--def", "no_such.def"])
        assert r.exit_code == 1
        assert "LEF/DEF 解析失败" in r.output

    def test_check_json_envelope(self, tmp_path: Path) -> None:
        r = runner.invoke(lefdef_app, ["check", "--lef", _write(tmp_path, "a.lef", LEF_TEXT),
                                       "--def", _write(tmp_path, "t.def", DEF_TEXT), "--json"])
        assert r.exit_code == 0, r.output  # 违规≠exit 1（verdict 承载）
        payload = json.loads(r.output)
        assert (payload["ok"], payload["verdict"]) == (True, "issues")
        assert payload["closure"]["missing_models"] == ["BUF_X1"]

    def test_check_human_output(self, tmp_path: Path) -> None:
        r = runner.invoke(lefdef_app, ["check", "--lef", _write(tmp_path, "a.lef", LEF_TEXT),
                                       "--def", _write(tmp_path, "t.def", DEF_TEXT)])
        assert r.exit_code == 0, r.output
        assert "verdict=issues" in r.output
        assert "BUF_X1" in r.output and "spare" in r.output

    def test_check_missing_def_json_exit1(self, tmp_path: Path) -> None:
        r = runner.invoke(lefdef_app, ["check", "--lef", _write(tmp_path, "a.lef", LEF_TEXT), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False and any("DEF" in e for e in payload["errors"])

    def test_leaves_with_json_flag(self) -> None:
        # 本席域形状钉：恰 parse/check 两叶、每叶带 --json（新面必红清单①）
        group = get_command(lefdef_app)
        assert set(group.commands) == {"parse", "check"}
        for leaf in group.commands.values():
            assert "--json" in {o for p in leaf.params for o in p.opts}

    @pytest.mark.parametrize("leaf", ["parse", "check"])
    def test_help_builds(self, leaf: str) -> None:
        r = runner.invoke(lefdef_app, [leaf, "--help"])
        assert r.exit_code == 0, r.output
        assert "--json" in r.output and "--lef" in r.output

    def test_help_text_char_hygiene(self) -> None:
        # D-06/#305 自检（未接线域不在全局 help 卫生门扫描面）：命令与参数
        # help 零裸 '[' 零 '%'
        group = get_command(lefdef_app)
        texts = [group.help or ""]
        for leaf in group.commands.values():
            texts.append(leaf.help or "")
            texts.extend(getattr(p, "help", None) or "" for p in leaf.params)
        assert not [t for t in texts if "[" in t or "%" in t]
